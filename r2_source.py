"""Cloudflare/API tile streaming + cache + download telemetry helpers."""

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from collections import OrderedDict

from .auth import AuthApiError, get_authorized_headers, get_api_base_url, refresh_auth_session, sync_account_profile
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

logger = logging.getLogger(__name__)


_R2_TIMEOUT_SECONDS = 30
_R2_RETRIES = 2
_R2_DEFAULT_CACHE_MAX_GB = 5.0
_R2_DEFAULT_CACHE_PRUNE_TARGET_RATIO = 0.9
_R2_DEFAULT_PREFIX = "planetka-assets"
_R2_CACHE_PRUNE_INTERVAL_SECONDS = 30.0
_HEAD_CACHE_MAX_ENTRIES = 20000
_STREAM_HEALTH_CACHE_TTL_SECONDS = 120.0
_STREAM_HEALTH_SENTINEL = None
_R2_READ_CHUNK_BYTES = 4 * 1024 * 1024
_R2_PROGRESS_FLUSH_BYTES = 4 * 1024 * 1024
_R2_PROGRESS_FLUSH_INTERVAL_SECONDS = 0.25
_R2_PREFETCH_MAX_WORKERS = 8


@dataclass(frozen=True)
class _R2Config:
    bucket: str
    endpoint: str
    access_key_id: str
    secret_access_key: str
    region: str
    prefix: str
    cache_root: str
    cache_max_bytes: int
    cache_prune_target_ratio: float
    prefer_remote: bool
    allow_local_fallback: bool


_CONFIG_LOCK = threading.Lock()
_CONFIG_CACHE = None
_HEAD_CACHE = OrderedDict()
_HEAD_CACHE_LOCK = threading.Lock()
_HEAD_SIZE_CACHE = OrderedDict()
_HEAD_SIZE_CACHE_LOCK = threading.Lock()
_METRICS_LOCK = threading.Lock()
_CACHE_PRUNE_LOCK = threading.Lock()
_CACHE_PRUNE_SUSPEND_LOCK = threading.Lock()
_ACTIVE_DOWNLOADS = 0
_ACTIVE_DOWNLOAD_BYTES = 0
_ACTIVE_EXPECTED_BYTES = 0
_CAPTURE_ENABLED = False
_CAPTURE_DOWNLOAD_BYTES = 0
_CAPTURE_DOWNLOAD_MS = 0.0
_CAPTURE_TOTAL_BYTES = 0
_CAPTURE_PLANNED_TOTAL_BYTES = 0
_CAPTURE_STARTED_AT = 0.0
_LAST_UI_REDRAW_AT = 0.0
_LAST_CACHE_PRUNE_AT = 0.0
_LOCAL_SIZE_CACHE = {}
_LOCAL_SIZE_CACHE_LOCK = threading.Lock()
_STREAM_HEALTH_OK = None
_STREAM_HEALTH_CHECKED_AT = 0.0
_AUTH_CHECK_LOCK = threading.Lock()
_AUTH_LAST_BEARER = ""
_AUTH_LAST_CHECKED_AT = 0.0
_AUTH_CHECK_TTL_SECONDS = 15.0
_CACHE_PRUNE_SUSPEND_COUNT = 0
_REQUEST_CONTEXT_LOCK = threading.Lock()
_REQUEST_CONTEXT_RESOLVE_ID = ""
_REQUEST_CONTEXT_TEXTURE_MODE = ""


def _env(name, fallback=None):
    value = os.getenv(name)
    if value is None and fallback:
        for alt in fallback:
            value = os.getenv(alt)
            if value is not None:
                break
    return str(value or "").strip()


def _default_cache_root():
    home = os.path.expanduser("~")
    if home and home != "~":
        return os.path.join(home, "Library", "Caches", "Planetka", "r2_cache")
    return os.path.join(os.path.abspath(os.path.expanduser("~")), ".planetka", "r2_cache")


def _parse_positive_float(value, default):
    try:
        parsed = float(value)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    return float(default)


def _parse_positive_int(value, default):
    try:
        parsed = int(float(value))
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    return int(default)


def _parse_cache_max_bytes(max_bytes_raw, max_gb_raw, default_gb):
    if str(max_bytes_raw or "").strip():
        try:
            parsed = int(float(str(max_bytes_raw).strip()))
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            pass
    max_gb = _parse_positive_float(max_gb_raw, default_gb)
    return int(max_gb * (1024 ** 3))


def _scene_cache_max_gb():
    if threading.current_thread() is not threading.main_thread():
        return None

    try:
        import bpy  # Imported lazily so non-Blender contexts can still import this module.
    except (ImportError, ModuleNotFoundError):
        return None

    try:
        context = getattr(bpy, "context", None)
        scene = getattr(context, "scene", None) if context else None
        props = getattr(scene, "planetka", None) if scene else None
        if props is not None and hasattr(props, "r2_cache_max_gb"):
            return _parse_positive_float(getattr(props, "r2_cache_max_gb", None), _R2_DEFAULT_CACHE_MAX_GB)

        data = getattr(bpy, "data", None)
        for data_scene in getattr(data, "scenes", ()):
            props = getattr(data_scene, "planetka", None)
            if props is not None and hasattr(props, "r2_cache_max_gb"):
                return _parse_positive_float(getattr(props, "r2_cache_max_gb", None), _R2_DEFAULT_CACHE_MAX_GB)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed reading scene cache size setting", exc_info=True)
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed reading scene cache size setting", exc_info=True)
        return None

    return None

def _build_config():
    env_cfg = {
        "bucket": "planetka-api",
        "endpoint": _env("PLANETKA_API_BASE_URL") or get_api_base_url(),
        "access_key_id": "planetka-api",
        "secret_access_key": "planetka-api",
        "region": "auto",
        "prefix": _env("PLANETKA_R2_PREFIX") or _R2_DEFAULT_PREFIX,
        "cache_root": _env("PLANETKA_R2_CACHE_DIR") or _default_cache_root(),
        "cache_max_bytes": _env("PLANETKA_R2_CACHE_MAX_BYTES"),
        "cache_max_gb": _env("PLANETKA_R2_CACHE_MAX_GB", fallback=("R2_CACHE_MAX_GB",)),
        "cache_prune_target_ratio": _env("PLANETKA_R2_CACHE_PRUNE_TARGET_RATIO"),
        # Force remote-only texture loading; local source files are never used by resolver.
        "prefer_remote": True,
        "allow_local_fallback": False,
    }

    merged = dict(env_cfg)

    bucket = str(merged.get("bucket", "")).strip()
    endpoint = str(merged.get("endpoint", "")).strip().rstrip("/")
    access_key_id = str(merged.get("access_key_id", "")).strip()
    secret_access_key = str(merged.get("secret_access_key", "")).strip()
    region = str(merged.get("region", "auto") or "auto").strip()
    prefix = str(merged.get("prefix", _R2_DEFAULT_PREFIX) or _R2_DEFAULT_PREFIX).strip("/")
    cache_root = str(merged.get("cache_root", _default_cache_root()) or _default_cache_root())
    scene_cache_max_gb = _scene_cache_max_gb()
    cache_max_bytes_raw = merged.get("cache_max_bytes")
    cache_max_gb_raw = merged.get("cache_max_gb")
    if scene_cache_max_gb:
        # UI setting should be the primary user control in Blender.
        cache_max_bytes_raw = ""
        cache_max_gb_raw = scene_cache_max_gb

    default_cache_max_gb = scene_cache_max_gb if scene_cache_max_gb else _R2_DEFAULT_CACHE_MAX_GB
    cache_max_bytes = _parse_cache_max_bytes(
        cache_max_bytes_raw,
        cache_max_gb_raw,
        default_cache_max_gb,
    )
    cache_prune_target_ratio = _parse_positive_float(
        merged.get("cache_prune_target_ratio"),
        _R2_DEFAULT_CACHE_PRUNE_TARGET_RATIO,
    )
    cache_prune_target_ratio = min(max(cache_prune_target_ratio, 0.5), 0.99)
    prefer_remote = bool(merged.get("prefer_remote", True))
    allow_local_fallback = bool(merged.get("allow_local_fallback", False))

    if not endpoint:
        return None

    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"https://{endpoint}"

    return _R2Config(
        bucket=bucket,
        endpoint=endpoint,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region=region,
        prefix=prefix,
        cache_root=cache_root,
        cache_max_bytes=cache_max_bytes,
        cache_prune_target_ratio=cache_prune_target_ratio,
        prefer_remote=prefer_remote,
        allow_local_fallback=allow_local_fallback,
    )


def _get_config():
    global _CONFIG_CACHE
    with _CONFIG_LOCK:
        if _CONFIG_CACHE is None:
            _CONFIG_CACHE = _build_config()
        return _CONFIG_CACHE


def reset_config_cache():
    global _CONFIG_CACHE
    global _LAST_CACHE_PRUNE_AT
    with _CONFIG_LOCK:
        _CONFIG_CACHE = None
    with _HEAD_CACHE_LOCK:
        _HEAD_CACHE.clear()
    with _HEAD_SIZE_CACHE_LOCK:
        _HEAD_SIZE_CACHE.clear()
    _LAST_CACHE_PRUNE_AT = 0.0


def on_cache_settings_updated(force_prune=False):
    reset_config_cache()
    if force_prune:
        cfg = _get_config()
        _maybe_prune_cache(cfg, force=True)


def _looks_like_remote_source(base_path):
    text = str(base_path or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in {"remote", "cloud", "r2", "planetka-remote"}:
        return True
    if lowered.startswith(("r2://", "cloud://", "planetka://", "https://", "http://")):
        return True
    return False


def _get_texture_source_mode():
    # Local-disk texture source mode is deprecated. Planetka always streams
    # through Cloudflare/API so users cannot accidentally resolve from stale
    # local datasets.
    return "CLOUDFLARE"


def is_remote_source_configured(base_path=None):
    if _get_config() is None:
        return False
    if base_path is not None and str(base_path).strip():
        if _looks_like_remote_source(base_path):
            return True
    return True


def _ensure_remote_authentication(allow_cached_on_network_error=False):
    global _AUTH_LAST_BEARER
    global _AUTH_LAST_CHECKED_AT

    now = time.monotonic()
    with _AUTH_CHECK_LOCK:
        if _AUTH_LAST_BEARER and (now - float(_AUTH_LAST_CHECKED_AT)) <= _AUTH_CHECK_TTL_SECONDS:
            return _AUTH_LAST_BEARER

    cfg = _get_config()
    if cfg is None:
        raise RuntimeError("Planetka API endpoint is not configured.")

    try:
        headers = {
            "User-Agent": "Planetka-Blender",
            **get_authorized_headers(allow_refresh=True),
        }
    except AuthApiError as exc:
        raise RuntimeError("Planetka login expired. Log in again.") from exc

    auth_header = str(headers.get("Authorization", "") or "").strip()
    if not auth_header:
        raise RuntimeError("Planetka login expired. Log in again.")

    if _STREAM_HEALTH_SENTINEL:
        folder, file_name = _STREAM_HEALTH_SENTINEL
        key = _remote_key(folder, file_name)
        url = cfg.endpoint.rstrip("/") + "/tiles/" + urllib.parse.quote(key, safe="/-_.~")
        request = urllib.request.Request(url, method="HEAD", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=_R2_TIMEOUT_SECONDS):
                pass
        except urllib.error.HTTPError as exc:
            if int(getattr(exc, "code", 0)) in {401, 403}:
                raise RuntimeError("Planetka login expired. Log in again.") from exc
            if int(getattr(exc, "code", 0)) != 404:
                raise RuntimeError(f"Planetka could not verify login session: HTTP {exc.code}.") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if allow_cached_on_network_error:
                # Keep already-cached files usable while temporarily offline.
                return auth_header
            raise RuntimeError("Planetka could not verify login session. Check internet connection and retry.") from exc

    with _AUTH_CHECK_LOCK:
        _AUTH_LAST_BEARER = auth_header
        _AUTH_LAST_CHECKED_AT = time.monotonic()
    return auth_header


def begin_resolve_download_capture():
    global _CAPTURE_ENABLED
    global _CAPTURE_DOWNLOAD_BYTES
    global _CAPTURE_DOWNLOAD_MS
    global _CAPTURE_TOTAL_BYTES
    global _CAPTURE_PLANNED_TOTAL_BYTES
    global _CAPTURE_STARTED_AT
    with _METRICS_LOCK:
        _CAPTURE_ENABLED = True
        _CAPTURE_DOWNLOAD_BYTES = 0
        _CAPTURE_DOWNLOAD_MS = 0.0
        _CAPTURE_TOTAL_BYTES = 0
        _CAPTURE_PLANNED_TOTAL_BYTES = 0
        _CAPTURE_STARTED_AT = time.perf_counter()


def end_resolve_download_capture():
    global _CAPTURE_ENABLED
    global _CAPTURE_STARTED_AT
    with _METRICS_LOCK:
        downloaded_bytes = int(max(0, _CAPTURE_DOWNLOAD_BYTES))
        total_bytes = int(max(downloaded_bytes, _CAPTURE_PLANNED_TOTAL_BYTES, _CAPTURE_TOTAL_BYTES))
        thread_ms = float(max(0.0, _CAPTURE_DOWNLOAD_MS))
        wall_ms = 0.0
        if _CAPTURE_STARTED_AT > 0.0:
            wall_ms = float(max(0.0, (time.perf_counter() - _CAPTURE_STARTED_AT) * 1000.0))
        result = {
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
            # Wall-clock duration across the whole capture window.
            "download_ms": wall_ms,
            "download_wall_ms": wall_ms,
            # Sum of request durations across concurrent workers (debug only).
            "download_thread_ms": thread_ms,
            "download_active": bool(_ACTIVE_DOWNLOADS > 0),
        }
        _CAPTURE_ENABLED = False
        _CAPTURE_STARTED_AT = 0.0
        return result


def is_download_active():
    with _METRICS_LOCK:
        return bool(_ACTIVE_DOWNLOADS > 0 or _CAPTURE_ENABLED)


def verify_remote_stream_health(force=False):
    global _STREAM_HEALTH_OK
    global _STREAM_HEALTH_CHECKED_AT

    cfg = _get_config()
    if cfg is None:
        return False, "Planetka API endpoint is not configured."
    if not _STREAM_HEALTH_SENTINEL:
        return True, ""

    now_ts = time.time()
    if not force and _STREAM_HEALTH_OK is not None:
        if (now_ts - float(_STREAM_HEALTH_CHECKED_AT)) <= _STREAM_HEALTH_CACHE_TTL_SECONDS:
            return bool(_STREAM_HEALTH_OK), ""

    folder, file_name = _STREAM_HEALTH_SENTINEL
    key = _remote_key(folder, file_name)

    try:
        ok = bool(_r2_request("HEAD", key))
    except RuntimeError as exc:
        _STREAM_HEALTH_OK = False
        _STREAM_HEALTH_CHECKED_AT = now_ts
        return False, str(exc)

    _STREAM_HEALTH_OK = ok
    _STREAM_HEALTH_CHECKED_AT = now_ts
    if ok:
        return True, ""

    return (
        False,
        (
            "Planetka tile stream is online but the active data prefix does not contain "
            "the expected sentinel tile. Ensure Worker R2_PREFIX is set to 'planetka-assets'."
        ),
    )


def get_download_progress():
    with _METRICS_LOCK:
        downloaded_bytes = int(max(0, _CAPTURE_DOWNLOAD_BYTES + _ACTIVE_DOWNLOAD_BYTES))
        if _CAPTURE_PLANNED_TOTAL_BYTES > 0:
            total_bytes = int(max(downloaded_bytes, _CAPTURE_PLANNED_TOTAL_BYTES))
        else:
            total_bytes = int(max(downloaded_bytes, _CAPTURE_TOTAL_BYTES + _ACTIVE_EXPECTED_BYTES))
        return {
            "download_active": bool(_ACTIVE_DOWNLOADS > 0 or _CAPTURE_ENABLED),
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }


def _texture_size_source_root():
    configured = _env("PLANETKA_TEXTURE_SIZE_SOURCE_DIR")
    if configured:
        return configured
    return ""


def _lookup_local_texture_size(folder, file_name):
    key = f"{folder}/{file_name}"
    with _LOCAL_SIZE_CACHE_LOCK:
        if key in _LOCAL_SIZE_CACHE:
            cached = _LOCAL_SIZE_CACHE[key]
            if cached is None:
                return None
            return int(cached)

    source_root = _texture_size_source_root()
    if not source_root:
        return None
    candidate = os.path.join(source_root, str(folder or ""), str(file_name or ""))
    size = None
    try:
        if os.path.isfile(candidate):
            size = int(max(0, os.path.getsize(candidate)))
    except (OSError, ValueError, TypeError):
        size = None

    with _LOCAL_SIZE_CACHE_LOCK:
        _LOCAL_SIZE_CACHE[key] = size
    return size


def _lookup_remote_texture_size(folder, file_name):
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return None

    key = _remote_key(safe_folder, safe_name)
    with _HEAD_SIZE_CACHE_LOCK:
        if key in _HEAD_SIZE_CACHE:
            cached = _HEAD_SIZE_CACHE[key]
            if cached is None:
                return None
            return int(max(0, int(cached)))

    cfg = _get_config()
    if cfg is None:
        return None

    try:
        _ensure_remote_authentication()
        url, headers = _signed_headers(cfg, method="HEAD", key=key)
        request = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(request, timeout=_R2_TIMEOUT_SECONDS) as response:
            raw_length = response.headers.get("Content-Length", "")
        size = int(max(0, int(raw_length or 0)))
    except (AuthApiError, urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed reading remote tile size with HEAD request", exc_info=True)
        size = None

    with _HEAD_SIZE_CACHE_LOCK:
        _HEAD_SIZE_CACHE[key] = size
        if len(_HEAD_SIZE_CACHE) > _HEAD_CACHE_MAX_ENTRIES:
            _HEAD_SIZE_CACHE.popitem(last=False)

    return size


def plan_resolve_downloads(requests):
    global _CAPTURE_PLANNED_TOTAL_BYTES

    if not is_remote_source_configured(None):
        return {"planned_total_bytes": 0, "planned_file_count": 0, "unknown_file_count": 0}

    cfg = _get_config()
    if cfg is None:
        return {"planned_total_bytes": 0, "planned_file_count": 0, "unknown_file_count": 0}

    seen = set()
    planned_total = 0
    planned_files = 0
    unknown_files = 0

    for request in requests or ():
        if not isinstance(request, (tuple, list)) or len(request) != 4:
            continue
        folder, prefix, filename, extensions = request
        folder = str(folder or "").strip()
        prefix = str(prefix or "").strip()
        filename = str(filename or "").strip()
        if not folder or not prefix or not filename:
            continue
        exts = tuple(extensions or (".exr",))

        selected_file_name = ""
        for ext in exts:
            ext_text = str(ext or "")
            candidate_file_name = f"{prefix}_{filename}{ext_text}"
            cached_path = _cached_remote_path(folder, candidate_file_name)
            if cached_path and os.path.isfile(cached_path):
                selected_file_name = ""
                break
            selected_file_name = candidate_file_name
            break

        if not selected_file_name:
            continue

        dedupe_key = f"{folder}/{selected_file_name}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        planned_files += 1

        local_size = _lookup_local_texture_size(folder, selected_file_name)
        if local_size is None:
            remote_size = _lookup_remote_texture_size(folder, selected_file_name)
            if remote_size is None:
                unknown_files += 1
                continue
            planned_total += int(max(0, remote_size))
            continue
        planned_total += int(max(0, local_size))

    with _METRICS_LOCK:
        if _CAPTURE_ENABLED:
            _CAPTURE_PLANNED_TOTAL_BYTES = int(max(0, planned_total))

    return {
        "planned_total_bytes": int(max(0, planned_total)),
        "planned_file_count": int(max(0, planned_files)),
        "unknown_file_count": int(max(0, unknown_files)),
    }


def _request_ui_redraw(force=False):
    if threading.current_thread() is not threading.main_thread():
        return

    global _LAST_UI_REDRAW_AT
    now = time.perf_counter()
    if not force and (now - _LAST_UI_REDRAW_AT) < 0.2:
        return
    _LAST_UI_REDRAW_AT = now

    try:
        import bpy  # Imported lazily so non-Blender contexts can still import this module.
    except (ImportError, ModuleNotFoundError):
        return

    try:
        context = getattr(bpy, "context", None)
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        wm_ops = getattr(getattr(bpy, "ops", None), "wm", None)
        redraw_timer = getattr(wm_ops, "redraw_timer", None)
        if redraw_timer is not None:
            redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed requesting UI redraw", exc_info=True)
        return
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed requesting UI redraw", exc_info=True)
        return


def _prune_cache_root(cache_root, max_bytes, target_ratio):
    if not cache_root or max_bytes <= 0:
        return 0, 0

    entries = []
    total_bytes = 0
    for dir_path, _, file_names in os.walk(cache_root):
        for file_name in file_names:
            path = os.path.join(dir_path, file_name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            size = int(max(0, stat.st_size))
            total_bytes += size
            entries.append((stat.st_mtime, path, size))

    if total_bytes <= max_bytes:
        return total_bytes, 0

    target_bytes = int(max_bytes * target_ratio)
    if target_bytes < 0:
        target_bytes = 0

    removed = 0
    entries.sort(key=lambda item: item[0])  # oldest first
    for _, path, size in entries:
        if total_bytes <= target_bytes:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        removed += 1
        total_bytes = max(0, total_bytes - size)

    return total_bytes, removed


def _maybe_prune_cache(cfg, force=False):
    global _LAST_CACHE_PRUNE_AT
    with _CACHE_PRUNE_SUSPEND_LOCK:
        suspended = int(_CACHE_PRUNE_SUSPEND_COUNT) > 0
    if suspended and not force:
        return
    if cfg is None or cfg.cache_max_bytes <= 0:
        return

    now = time.time()
    if not force and (now - _LAST_CACHE_PRUNE_AT) < _R2_CACHE_PRUNE_INTERVAL_SECONDS:
        return

    if not _CACHE_PRUNE_LOCK.acquire(blocking=False):
        return
    try:
        _LAST_CACHE_PRUNE_AT = now
        _prune_cache_root(
            cfg.cache_root,
            cfg.cache_max_bytes,
            cfg.cache_prune_target_ratio,
        )
    finally:
        _CACHE_PRUNE_LOCK.release()


def _suspend_cache_prune():
    global _CACHE_PRUNE_SUSPEND_COUNT
    with _CACHE_PRUNE_SUSPEND_LOCK:
        _CACHE_PRUNE_SUSPEND_COUNT = int(_CACHE_PRUNE_SUSPEND_COUNT) + 1


def _resume_cache_prune():
    global _CACHE_PRUNE_SUSPEND_COUNT
    with _CACHE_PRUNE_SUSPEND_LOCK:
        _CACHE_PRUNE_SUSPEND_COUNT = max(0, int(_CACHE_PRUNE_SUSPEND_COUNT) - 1)


def _aws_sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _aws_signing_key(secret_key, date_stamp, region, service):
    k_date = _aws_sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _aws_sign(k_date, region)
    k_service = _aws_sign(k_region, service)
    return _aws_sign(k_service, "aws4_request")


def set_resolve_request_context(resolve_id="", texture_quality_mode=""):
    global _REQUEST_CONTEXT_RESOLVE_ID
    global _REQUEST_CONTEXT_TEXTURE_MODE
    with _REQUEST_CONTEXT_LOCK:
        _REQUEST_CONTEXT_RESOLVE_ID = str(resolve_id or "").strip()[:128]
        safe_mode = str(texture_quality_mode or "").strip().lower()
        if safe_mode == "half":
            safe_mode = "preview"
        elif safe_mode == "full":
            safe_mode = "full"
        elif safe_mode != "preview":
            safe_mode = ""
        _REQUEST_CONTEXT_TEXTURE_MODE = safe_mode


def clear_resolve_request_context():
    set_resolve_request_context("", "")


@contextmanager
def resolve_request_context(resolve_id="", texture_quality_mode=""):
    set_resolve_request_context(resolve_id, texture_quality_mode=texture_quality_mode)
    try:
        yield
    finally:
        clear_resolve_request_context()


def _signed_headers(cfg, method, key, allow_refresh=True):
    del method
    headers = {
        "User-Agent": "Planetka-Blender",
        **get_authorized_headers(allow_refresh=allow_refresh),
    }
    with _REQUEST_CONTEXT_LOCK:
        resolve_id = str(_REQUEST_CONTEXT_RESOLVE_ID or "").strip()
        quality_mode = str(_REQUEST_CONTEXT_TEXTURE_MODE or "").strip().lower()
    if resolve_id:
        headers["X-Planetka-Resolve-Id"] = resolve_id
    if quality_mode in {"full", "preview"}:
        headers["X-Planetka-Quality-Mode"] = quality_mode
    url = cfg.endpoint.rstrip("/") + "/tiles/" + urllib.parse.quote(key, safe="/-_.~")
    return url, headers


def _r2_request(method, key, destination_path=None):
    global _ACTIVE_DOWNLOADS
    global _ACTIVE_DOWNLOAD_BYTES
    global _ACTIVE_EXPECTED_BYTES
    global _CAPTURE_DOWNLOAD_BYTES
    global _CAPTURE_DOWNLOAD_MS
    global _CAPTURE_TOTAL_BYTES
    cfg = _get_config()
    if cfg is None:
        return False

    last_error = None
    for _ in range(_R2_RETRIES + 1):
        refreshed = False
        capture_download = bool(method == "GET" and destination_path is not None)
        attempt_downloaded = 0
        attempt_expected = 0
        attempt_start = 0.0
        pending_progress_bytes = 0
        last_progress_flush_at = 0.0
        active_started = False
        if capture_download:
            attempt_start = time.perf_counter()
            last_progress_flush_at = attempt_start
            with _METRICS_LOCK:
                _ACTIVE_DOWNLOADS += 1
            active_started = True
            _request_ui_redraw(force=True)
        try:
            url, headers = _signed_headers(cfg, method=method, key=key)
            request = urllib.request.Request(url, method=method, headers=headers)
            with urllib.request.urlopen(request, timeout=_R2_TIMEOUT_SECONDS) as response:
                if method == "HEAD":
                    return True
                if capture_download:
                    content_length_raw = response.headers.get("Content-Length", "")
                    try:
                        parsed_length = int(content_length_raw or 0)
                        attempt_expected = max(0, parsed_length)
                    except (TypeError, ValueError):
                        attempt_expected = 0
                    if attempt_expected > 0:
                        with _METRICS_LOCK:
                            _ACTIVE_EXPECTED_BYTES += attempt_expected
                if destination_path is not None:
                    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                    with open(destination_path, "wb") as handle:
                        while True:
                            chunk = response.read(_R2_READ_CHUNK_BYTES)
                            if not chunk:
                                break
                            handle.write(chunk)
                            if capture_download:
                                chunk_len = int(len(chunk))
                                attempt_downloaded += chunk_len
                                pending_progress_bytes += chunk_len
                                now = time.perf_counter()
                                should_flush = (
                                    pending_progress_bytes >= _R2_PROGRESS_FLUSH_BYTES
                                    or (now - last_progress_flush_at) >= _R2_PROGRESS_FLUSH_INTERVAL_SECONDS
                                )
                                if should_flush:
                                    with _METRICS_LOCK:
                                        _ACTIVE_DOWNLOAD_BYTES += int(max(0, pending_progress_bytes))
                                    pending_progress_bytes = 0
                                    last_progress_flush_at = now
                                    _request_ui_redraw()
                    if capture_download and pending_progress_bytes > 0:
                        with _METRICS_LOCK:
                            _ACTIVE_DOWNLOAD_BYTES += int(max(0, pending_progress_bytes))
                        pending_progress_bytes = 0
                        _request_ui_redraw()
                    if capture_download:
                        _maybe_prune_cache(cfg)
                if capture_download:
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000.0
                    with _METRICS_LOCK:
                        if _CAPTURE_ENABLED:
                            _CAPTURE_DOWNLOAD_BYTES += int(max(0, attempt_downloaded))
                            _CAPTURE_TOTAL_BYTES += int(max(0, attempt_expected or attempt_downloaded))
                            _CAPTURE_DOWNLOAD_MS += float(max(0.0, elapsed_ms))
                return True
        except urllib.error.HTTPError as exc:
            error_message = ""
            error_code = ""
            try:
                raw = exc.read()
            except (RuntimeError, ValueError, OSError):
                raw = b""
            if raw:
                text = raw.decode("utf-8", errors="replace").strip()
                if text:
                    try:
                        payload = json.loads(text)
                    except (TypeError, ValueError):
                        payload = None
                    if isinstance(payload, dict):
                        error_code = str(payload.get("error", "") or payload.get("code", "") or "").strip().lower()
                        error_message = str(
                            payload.get("message", "")
                            or payload.get("detail", "")
                            or payload.get("error_description", "")
                            or ""
                        ).strip()
                    else:
                        error_message = text
            if exc.code == 401 and not refreshed:
                try:
                    refresh_auth_session()
                    refreshed = True
                    continue
                except AuthApiError as refresh_exc:
                    raise RuntimeError("Planetka login expired. Log in again.") from refresh_exc
            if exc.code == 404:
                return False
            if exc.code in {402, 429}:
                combined = f"{error_code} {error_message}".lower()
                if "download_throttled" in combined or "throttl" in combined:
                    try:
                        sync_account_profile()
                    except (AuthApiError, RuntimeError, TypeError, ValueError, AttributeError, OSError):
                        logger.debug("Planetka: failed syncing account profile after throttling response", exc_info=True)
                    raise RuntimeError(
                        "Planetka account is temporarily throttled due to high data volume."
                    )
                if any(token in combined for token in ("allowance", "quota", "insufficient", "exhausted", "topup", "top_up", "top-up")):
                    try:
                        sync_account_profile()
                    except (AuthApiError, RuntimeError, TypeError, ValueError, AttributeError, OSError):
                        logger.debug("Planetka: failed syncing account profile after request-limit response", exc_info=True)
                    raise RuntimeError(
                        "Planetka account does not currently have access to this remote data request."
                    )
                if error_message:
                    raise RuntimeError(f"Planetka request limit reached: {error_message}")
                raise RuntimeError("Planetka request limit reached for this account.")
            if exc.code == 403:
                combined = f"{error_code} {error_message}".lower()
                if "account_blocked" in combined or "account is blocked" in combined:
                    raise RuntimeError("Planetka account is blocked. Contact info@planetka.io.")
                if any(token in combined for token in ("allowance", "quota", "insufficient", "exhausted", "topup", "top_up", "top-up")):
                    try:
                        sync_account_profile()
                    except (AuthApiError, RuntimeError, TypeError, ValueError, AttributeError, OSError):
                        logger.debug("Planetka: failed syncing account profile after access-denied response", exc_info=True)
                    raise RuntimeError(
                        "Planetka account does not currently have access to this remote data request."
                    )
                if error_message:
                    raise RuntimeError(f"Planetka account does not have access to remote Earth data: {error_message}")
                raise RuntimeError("Planetka account does not have access to remote Earth data.")
            last_error = exc
        except AuthApiError as exc:
            raise RuntimeError(str(exc.error).replace("_", " ")) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = exc
        finally:
            if active_started:
                if pending_progress_bytes > 0:
                    with _METRICS_LOCK:
                        _ACTIVE_DOWNLOAD_BYTES += int(max(0, pending_progress_bytes))
                    pending_progress_bytes = 0
                with _METRICS_LOCK:
                    _ACTIVE_DOWNLOADS = max(0, int(_ACTIVE_DOWNLOADS) - 1)
                    _ACTIVE_DOWNLOAD_BYTES = max(0, int(_ACTIVE_DOWNLOAD_BYTES) - int(attempt_downloaded))
                    if attempt_expected > 0:
                        _ACTIVE_EXPECTED_BYTES = max(0, int(_ACTIVE_EXPECTED_BYTES) - int(attempt_expected))
                _request_ui_redraw(force=True)

    if last_error:
        raise RuntimeError(f"Planetka R2 request failed for key '{key}': {last_error}")
    return False


def _remote_key(folder, file_name):
    return f"{folder}/{file_name}"


def _local_candidate_paths(base_path, folder, file_name):
    base_abs = ""
    try:
        base_abs = str(base_path or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        base_abs = ""

    if not base_abs:
        return []

    return [os.path.join(base_abs, folder, file_name)]


def _cached_remote_path(folder, file_name):
    cfg = _get_config()
    if cfg is None:
        return ""
    return os.path.join(cfg.cache_root, folder, file_name)


def get_remote_cache_folder(folder):
    cfg = _get_config()
    if cfg is None:
        return ""
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    if not safe_folder:
        return cfg.cache_root
    return os.path.join(cfg.cache_root, safe_folder)


def resolve_remote_asset(folder, file_name):
    cfg = _get_config()
    if cfg is None:
        return ""

    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return ""

    cached_path = _cached_remote_path(safe_folder, safe_name)
    if cached_path and os.path.isfile(cached_path):
        _ensure_remote_authentication(allow_cached_on_network_error=True)
        return cached_path

    _ensure_remote_authentication()

    key = _remote_key(safe_folder, safe_name)
    if key and cached_path:
        downloaded = _r2_request("GET", key, destination_path=cached_path)
        if downloaded and os.path.isfile(cached_path):
            return cached_path
    return ""


def resolve_texture_file(base_path, folder, prefix, filename, extensions):
    del base_path
    exts = tuple(extensions or (".exr",))

    cfg = _get_config()
    if cfg is None:
        return ""

    for ext in exts:
        file_name = f"{prefix}_{filename}{ext}"
        cached_path = _cached_remote_path(folder, file_name)
        if cached_path and os.path.isfile(cached_path):
            _ensure_remote_authentication(allow_cached_on_network_error=True)
            return cached_path

    _ensure_remote_authentication()

    for ext in exts:
        file_name = f"{prefix}_{filename}{ext}"
        cached_path = _cached_remote_path(folder, file_name)
        key = _remote_key(folder, file_name)
        if key and cached_path:
            downloaded = _r2_request("GET", key, destination_path=cached_path)
            if downloaded and os.path.isfile(cached_path):
                return cached_path

    return ""


def prefetch_resolve_downloads(requests, base_path=None, cancel_event=None):
    resolved_count = 0
    missing_count = 0
    error_count = 0
    cancelled = False
    seen = set()
    resolved_base_path = str(base_path or "")
    tasks = []
    diagnostics_max = _parse_positive_int(_env("PLANETKA_R2_PREFETCH_DIAGNOSTICS_MAX_KEYS"), 24)
    diagnostics_max = max(1, int(diagnostics_max))
    missing_details = []
    fatal_error = ""

    def _is_fatal_prefetch_error(message):
        text = str(message or "").strip().lower()
        if not text:
            return False
        return any(
            token in text
            for token in (
                "account blocked",
                "account_blocked",
                "login expired",
                "log in again",
                "does not have access to remote earth data",
                "does not currently have access to this remote data request",
            )
        )

    for request in requests or ():
        if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
            cancelled = True
            break

        if not isinstance(request, (tuple, list)) or len(request) != 4:
            continue

        folder, prefix, filename, extensions = request
        folder = str(folder or "").strip()
        prefix = str(prefix or "").strip()
        filename = str(filename or "").strip()
        exts = tuple(extensions or (".exr",))
        if not folder or not prefix or not filename:
            continue

        dedupe_key = (folder, prefix, filename, exts)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tasks.append((folder, prefix, filename, exts))

    worker_cap = _parse_positive_int(_env("PLANETKA_R2_PREFETCH_WORKERS"), _R2_PREFETCH_MAX_WORKERS)
    worker_count = max(1, min(worker_cap, len(tasks) if tasks else 1))
    cfg = _get_config()
    # Pre-prune stale cache entries once before the resolve prefetch starts.
    # During a resolve prefetch we suspend pruning to avoid evicting files needed
    # by the same in-flight resolve (which can cause fallback tiles/pink textures).
    _maybe_prune_cache(cfg, force=False)
    _suspend_cache_prune()

    def _probe_missing_asset(task_folder, task_prefix, task_filename, task_ext, task_error=""):
        file_name = f"{task_prefix}_{task_filename}{task_ext}"
        key = _remote_key(task_folder, file_name)
        cache_path = _cached_remote_path(task_folder, file_name)
        cache_exists = bool(cache_path and os.path.isfile(cache_path))
        remote_exists = None
        remote_error = ""
        if key and not cache_exists:
            try:
                remote_exists = bool(_r2_request("HEAD", key))
            except (AuthApiError, urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TypeError, ValueError, OSError) as exc:
                remote_exists = None
                remote_error = str(exc)
        return {
            "folder": str(task_folder),
            "prefix": str(task_prefix),
            "tile": str(task_filename),
            "ext": str(task_ext),
            "key": str(key or ""),
            "cache_path": str(cache_path or ""),
            "cache_exists": bool(cache_exists),
            "remote_exists": remote_exists,
            "remote_error": str(remote_error or ""),
            "fetch_error": str(task_error or ""),
        }

    def _append_missing_details(task, task_error=""):
        nonlocal missing_details
        if len(missing_details) >= diagnostics_max:
            return
        task_folder, task_prefix, task_filename, task_exts = task
        for task_ext in task_exts:
            if len(missing_details) >= diagnostics_max:
                break
            missing_details.append(
                _probe_missing_asset(task_folder, task_prefix, task_filename, task_ext, task_error=task_error)
            )

    def _fetch_one(task):
        task_folder, task_prefix, task_filename, task_exts = task
        if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
            return {"state": "cancelled", "task": task}
        try:
            path = resolve_texture_file(
                base_path=resolved_base_path,
                folder=task_folder,
                prefix=task_prefix,
                filename=task_filename,
                extensions=task_exts,
            )
            if path and os.path.isfile(path):
                return {"state": "resolved", "task": task}
            return {"state": "missing", "task": task}
        except RuntimeError as exc:
            error_text = str(exc)
            if _is_fatal_prefetch_error(error_text):
                return {"state": "fatal", "task": task, "error": error_text}
            return {"state": "error", "task": task, "error": error_text}
        except (AuthApiError, urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TypeError, ValueError, OSError) as exc:
            return {"state": "error", "task": task, "error": str(exc)}

    try:
        if worker_count <= 1:
            for task in tasks:
                result = _fetch_one(task)
                if not isinstance(result, dict):
                    error_count += 1
                    missing_count += 1
                    _append_missing_details(task, task_error="invalid_prefetch_result")
                    continue
                state = str(result.get("state", "") or "")
                if state == "cancelled":
                    cancelled = True
                    break
                if state == "fatal":
                    fatal_error = str(result.get("error", "") or "Planetka resolve download failed.")
                    _append_missing_details(task, task_error=fatal_error)
                    cancelled = True
                    break
                if state == "resolved":
                    resolved_count += 1
                else:
                    missing_count += 1
                    if state == "error":
                        error_count += 1
                    _append_missing_details(task, task_error=str(result.get("error", "") or ""))
        else:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="planetka-r2") as executor:
                futures = [executor.submit(_fetch_one, task) for task in tasks]
                pending = set(futures)
                while pending:
                    done, pending = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                    _request_ui_redraw()
                    if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
                        cancelled = True
                        for pending_future in pending:
                            pending_future.cancel()
                        break
                    for future in done:
                        try:
                            result = future.result()
                        except (AuthApiError, urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TypeError, ValueError, OSError):
                            logger.debug("Planetka: prefetch worker future failed", exc_info=True)
                            result = {"state": "error", "task": None, "error": "future_result_failed"}
                        if not isinstance(result, dict):
                            error_count += 1
                            missing_count += 1
                            continue
                        state = str(result.get("state", "") or "")
                        if state == "cancelled":
                            cancelled = True
                            continue
                        if state == "fatal":
                            fatal_error = str(result.get("error", "") or "Planetka resolve download failed.")
                            task = result.get("task")
                            if isinstance(task, (tuple, list)) and len(task) == 4:
                                _append_missing_details(tuple(task), task_error=fatal_error)
                            cancelled = True
                            for pending_future in pending:
                                pending_future.cancel()
                            break
                        if state == "resolved":
                            resolved_count += 1
                        else:
                            missing_count += 1
                            if state == "error":
                                error_count += 1
                            task = result.get("task")
                            if isinstance(task, (tuple, list)) and len(task) == 4:
                                _append_missing_details(tuple(task), task_error=str(result.get("error", "") or ""))
                    if cancelled:
                        break
    finally:
        _resume_cache_prune()

    if missing_details:
        logger.error(
            "Planetka resolve prefetch diagnostics: missing=%d resolved=%d error=%d sample=%s",
            int(missing_count),
            int(resolved_count),
            int(error_count),
            json.dumps(missing_details, ensure_ascii=True),
        )

    return {
        "resolved_count": int(resolved_count),
        "missing_count": int(missing_count),
        "error_count": int(error_count),
        "missing_details": list(missing_details),
        "cancelled": bool(cancelled),
        "fatal_error": str(fatal_error or ""),
    }


def texture_file_exists(base_path, folder, file_name):
    del base_path
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return False

    cfg = _get_config()
    if cfg is None:
        return False

    cached_path = _cached_remote_path(safe_folder, safe_name)
    if cached_path and os.path.isfile(cached_path):
        _ensure_remote_authentication(allow_cached_on_network_error=True)
        return True

    _ensure_remote_authentication()

    key = _remote_key(safe_folder, safe_name)
    if key:
        with _HEAD_CACHE_LOCK:
            if key in _HEAD_CACHE:
                return bool(_HEAD_CACHE[key])
        exists = _r2_request("HEAD", key)
        with _HEAD_CACHE_LOCK:
            _HEAD_CACHE[key] = bool(exists)
            if len(_HEAD_CACHE) > _HEAD_CACHE_MAX_ENTRIES:
                _HEAD_CACHE.popitem(last=False)
        if exists:
            return True

    return False
