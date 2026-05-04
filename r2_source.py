"""Cloud/API tile streaming + cache + download telemetry helpers."""

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import tempfile
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

try:
    from .unsupported import (
        get_unsupported_texture_source_mode,
    )
except (ImportError, ModuleNotFoundError):
    def get_unsupported_texture_source_mode() -> str:
        return "CLOUD"

logger = logging.getLogger(__name__)


_R2_TIMEOUT_SECONDS = 30
_R2_RETRIES = 2
_R2_DEFAULT_CACHE_MAX_GB = 1.0
_R2_DEFAULT_CACHE_PRUNE_TARGET_RATIO = 0.9
_R2_DEFAULT_PREFIX = "planetka-assets"
_R2_CACHE_PRUNE_INTERVAL_SECONDS = 30.0
_HEAD_CACHE_MAX_ENTRIES = 20000
_STREAM_HEALTH_CACHE_TTL_SECONDS = 120.0
_STREAM_HEALTH_SENTINEL = None
_R2_READ_CHUNK_BYTES = 4 * 1024 * 1024
_R2_PROGRESS_FLUSH_BYTES = 4 * 1024 * 1024
_R2_PROGRESS_FLUSH_INTERVAL_SECONDS = 0.25
_R2_PREFETCH_MAX_WORKERS = 16
_R2_PREFETCH_ABSOLUTE_MAX_WORKERS = 32


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
_TILE_SIZE_DB_LOCK = threading.Lock()
_TILE_SIZE_DB_CONN = None
_TILE_SIZE_DB_PATH = ""
_TILE_SIZE_DB_MODE = ""
_TILE_SIZE_DB_FAILURE_KEYS = set()
_STREAM_HEALTH_OK = None
_STREAM_HEALTH_CHECKED_AT = 0.0
_LOCAL_SOURCE_FRESHNESS_CHECKED = set()
_LOCAL_SOURCE_STALE_NOTICE = ""
_AUTH_CHECK_LOCK = threading.Lock()
_AUTH_LAST_BEARER = ""
_AUTH_LAST_CHECKED_AT = 0.0
_AUTH_CHECK_TTL_SECONDS = 15.0
_CACHE_PRUNE_SUSPEND_COUNT = 0
_REQUEST_CONTEXT_LOCK = threading.Lock()
_REQUEST_CONTEXT_TILE_TOKEN_FETCH_LOCK = threading.Lock()
_REQUEST_CONTEXT_RESOLVE_ID = ""
_REQUEST_CONTEXT_TEXTURE_MODE = ""
_REQUEST_CONTEXT_CANCEL_EVENT = None
_REQUEST_CONTEXT_FORCE_CANCEL = False
_REQUEST_CONTEXT_NAV_LAT = ""
_REQUEST_CONTEXT_NAV_LON = ""
_REQUEST_CONTEXT_NAV_ALT_KM = ""
_REQUEST_CONTEXT_TILE_TOKEN = ""
_REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT = 0.0
_REQUEST_CONTEXT_PRICING_TILES = ()
_TILE_FILE_RE = re.compile(
    r"^(S2|EL|WT|PO)_x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})\.(exr|tif)$",
    re.IGNORECASE,
)

def _env(name, fallback=None):
    value = os.getenv(name)
    if value is None and fallback:
        for alt in fallback:
            value = os.getenv(alt)
            if value is not None:
                break
    return str(value or "").strip()


def _default_cache_root():
    return os.path.join(str(tempfile.gettempdir() or "/tmp"), "planetka_cache")


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


def _parse_bool_env(name, default=False):
    raw = str(_env(name) or "").strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _build_config():
    env_cfg = {
        "bucket": "planetka-api",
        "endpoint": _env("PLANETKA_API_BASE_URL") or get_api_base_url(),
        "access_key_id": "planetka-api",
        "secret_access_key": "planetka-api",
        "region": "auto",
        "prefix": _env("PLANETKA_R2_PREFIX") or _R2_DEFAULT_PREFIX,
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
    cache_root = _default_cache_root()
    cache_max_bytes = int(float(_R2_DEFAULT_CACHE_MAX_GB) * (1024 ** 3))
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
    global _TILE_SIZE_DB_CONN
    global _TILE_SIZE_DB_PATH
    global _TILE_SIZE_DB_MODE
    with _CONFIG_LOCK:
        _CONFIG_CACHE = None
    with _HEAD_CACHE_LOCK:
        _HEAD_CACHE.clear()
    with _HEAD_SIZE_CACHE_LOCK:
        _HEAD_SIZE_CACHE.clear()
    with _LOCAL_SIZE_CACHE_LOCK:
        _LOCAL_SIZE_CACHE.clear()
    with _TILE_SIZE_DB_LOCK:
        conn = _TILE_SIZE_DB_CONN
        _TILE_SIZE_DB_CONN = None
        _TILE_SIZE_DB_PATH = ""
        _TILE_SIZE_DB_MODE = ""
        _TILE_SIZE_DB_FAILURE_KEYS.clear()
    if conn is not None:
        try:
            conn.close()
        except (sqlite3.Error, RuntimeError, TypeError, ValueError, OSError):
            logger.debug("Planetka: failed closing tile-size sqlite connection", exc_info=True)
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
    mode = str(get_unsupported_texture_source_mode() or "CLOUD").strip().upper()
    if mode == "LOCAL":
        return "LOCAL"
    return "CLOUDFLARE"


def is_remote_source_configured(base_path=None):
    if _get_texture_source_mode() == "LOCAL":
        if base_path is not None and _looks_like_remote_source(base_path):
            return True
        return False
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
        # Prefer real per-request totals collected from response headers (or
        # download fallback) over preflight planning estimates. This keeps the
        # final total aligned with what was actually transferred in this resolve.
        if int(_CAPTURE_TOTAL_BYTES) > 0:
            total_bytes = int(max(downloaded_bytes, _CAPTURE_TOTAL_BYTES))
        else:
            total_bytes = int(max(downloaded_bytes, _CAPTURE_PLANNED_TOTAL_BYTES))
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
        active_requests = int(max(0, _ACTIVE_DOWNLOADS))
        capture_enabled = bool(_CAPTURE_ENABLED)
        downloaded_bytes = int(max(0, _CAPTURE_DOWNLOAD_BYTES + _ACTIVE_DOWNLOAD_BYTES))
        # Keep UI total fixed to the preplanned estimate from local size DB so
        # "X / Y MB" remains stable during the whole download. Only downloaded
        # bytes should move while a resolve is in progress.
        total_bytes = int(max(0, _CAPTURE_PLANNED_TOTAL_BYTES))
        return {
            "download_active": bool(active_requests > 0 or capture_enabled),
            "active_requests": active_requests,
            "capture_enabled": capture_enabled,
            "preparing": bool(capture_enabled and active_requests <= 0),
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }


def _texture_size_source_root():
    configured = _env("PLANETKA_TEXTURE_SIZE_SOURCE_DIR")
    if configured:
        return configured
    return ""


def _bundled_texture_size_db_path():
    try:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "Resources", "tile_sizes.sqlite")
    except (RuntimeError, TypeError, ValueError, OSError):
        return ""


def _texture_size_db_path():
    configured = _env("PLANETKA_TEXTURE_SIZE_DB_PATH")
    if configured:
        return configured

    source_root = _texture_size_source_root()
    if source_root:
        candidate = os.path.join(source_root, "tile_sizes.sqlite")
        if os.path.isfile(candidate):
            return candidate

    bundled = _bundled_texture_size_db_path()
    if bundled and os.path.isfile(bundled):
        return bundled
    return ""


def _tile_size_db_connect(path):
    uri = f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=1.5)
    try:
        conn.execute("PRAGMA query_only=ON")
    except sqlite3.Error:
        pass
    conn.execute("SELECT 1 FROM tile_sizes LIMIT 1")
    return conn


def _detect_tile_size_db_mode(conn):
    rows = conn.execute("PRAGMA table_info(tile_sizes)").fetchall()
    columns = {str(row[1] or "").strip().lower() for row in rows if isinstance(row, (tuple, list)) and len(row) > 1}
    if {"key", "size_bytes"}.issubset(columns):
        return "key"
    if {"folder", "x", "y", "z", "d", "ext", "size_bytes"}.issubset(columns):
        return "dense"
    raise sqlite3.DatabaseError("Unsupported tile_sizes schema")


def _get_tile_size_db_connection():
    global _TILE_SIZE_DB_CONN
    global _TILE_SIZE_DB_PATH
    global _TILE_SIZE_DB_MODE

    db_path = _texture_size_db_path()
    if not db_path:
        return None, ""

    normalized = os.path.abspath(db_path)
    with _TILE_SIZE_DB_LOCK:
        if _TILE_SIZE_DB_CONN is not None and _TILE_SIZE_DB_PATH == normalized:
            return _TILE_SIZE_DB_CONN, str(_TILE_SIZE_DB_MODE or "")

        if _TILE_SIZE_DB_CONN is not None:
            try:
                _TILE_SIZE_DB_CONN.close()
            except (sqlite3.Error, RuntimeError, TypeError, ValueError, OSError):
                logger.debug("Planetka: failed closing stale tile-size sqlite connection", exc_info=True)
            _TILE_SIZE_DB_CONN = None
            _TILE_SIZE_DB_PATH = ""

        failure_key = f"open::{normalized}"
        if failure_key in _TILE_SIZE_DB_FAILURE_KEYS:
            return None, ""

        try:
            conn = _tile_size_db_connect(normalized)
            mode = _detect_tile_size_db_mode(conn)
            _TILE_SIZE_DB_CONN = conn
            _TILE_SIZE_DB_PATH = normalized
            _TILE_SIZE_DB_MODE = mode
            return _TILE_SIZE_DB_CONN, str(_TILE_SIZE_DB_MODE or "")
        except (sqlite3.Error, RuntimeError, TypeError, ValueError, OSError):
            logger.debug("Planetka: failed opening tile-size sqlite index '%s'", normalized, exc_info=True)
            _TILE_SIZE_DB_FAILURE_KEYS.add(failure_key)
            _TILE_SIZE_DB_CONN = None
            _TILE_SIZE_DB_PATH = ""
            _TILE_SIZE_DB_MODE = ""
            return None, ""


def _lookup_indexed_texture_size(folder, file_name):
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return None

    conn, mode = _get_tile_size_db_connection()
    if conn is None:
        return None

    key = f"{safe_folder}/{safe_name}"
    failure_key = f"query::{key}"
    if failure_key in _TILE_SIZE_DB_FAILURE_KEYS:
        return None

    try:
        with _TILE_SIZE_DB_LOCK:
            if mode == "dense":
                match = _TILE_FILE_RE.match(safe_name)
                if not match:
                    return None
                _prefix, x_text, y_text, z_text, d_text, ext_text = match.groups()
                row = conn.execute(
                    """
                    SELECT size_bytes
                    FROM tile_sizes
                    WHERE folder = ? AND x = ? AND y = ? AND z = ? AND d = ? AND ext = ?
                    LIMIT 1
                    """,
                    (
                        safe_folder.upper(),
                        int(x_text),
                        int(y_text),
                        int(z_text),
                        int(d_text),
                        str(ext_text or "").lower(),
                    ),
                ).fetchone()
            else:
                row = conn.execute("SELECT size_bytes FROM tile_sizes WHERE key = ? LIMIT 1", (key,)).fetchone()
    except (sqlite3.Error, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: tile-size sqlite lookup failed for key '%s'", key, exc_info=True)
        _TILE_SIZE_DB_FAILURE_KEYS.add(failure_key)
        return None

    if not row:
        return None
    try:
        return int(max(0, int(row[0] or 0)))
    except (TypeError, ValueError):
        return None


def is_indexed_tile_asset(folder, file_name):
    """Return True when the tile key exists in tile_sizes.sqlite."""
    try:
        return _lookup_indexed_texture_size(folder, file_name) is not None
    except (sqlite3.Error, RuntimeError, TypeError, ValueError, OSError):
        return False


def _lookup_local_texture_size(folder, file_name):
    key = f"{folder}/{file_name}"
    with _LOCAL_SIZE_CACHE_LOCK:
        if key in _LOCAL_SIZE_CACHE:
            cached = _LOCAL_SIZE_CACHE[key]
            if cached is None:
                return None
            return int(cached)

    indexed_size = _lookup_indexed_texture_size(folder, file_name)
    if indexed_size is not None:
        with _LOCAL_SIZE_CACHE_LOCK:
            _LOCAL_SIZE_CACHE[key] = int(indexed_size)
        return int(indexed_size)

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


def plan_resolve_downloads(requests, allow_remote_probe=None):
    global _CAPTURE_PLANNED_TOTAL_BYTES

    if allow_remote_probe is None:
        # Avoid remote HEAD probes during resolve preflight by default.
        # This keeps "download start" latency low for small Preview resolves.
        allow_remote_probe = _parse_bool_env("PLANETKA_R2_PLAN_REMOTE_HEAD", default=False)
    allow_remote_probe = bool(allow_remote_probe)

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
            if _find_user_local_source_file(folder, candidate_file_name):
                selected_file_name = ""
                break
            cached_path = _cached_remote_path(folder, candidate_file_name)
            if cached_path and _is_cache_file_usable(cached_path):
                selected_file_name = ""
                break
            _remove_invalid_cache_file(cached_path)
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
            if not allow_remote_probe:
                unknown_files += 1
                continue
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


def texture_asset_size_bytes(folder, file_name, allow_remote_probe=False):
    """Return the best known final asset size, regardless of cache/local source."""
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return None
    indexed_size = _lookup_local_texture_size(safe_folder, safe_name)
    if indexed_size is not None:
        return int(max(0, int(indexed_size)))
    if allow_remote_probe:
        remote_size = _lookup_remote_texture_size(safe_folder, safe_name)
        if remote_size is not None:
            return int(max(0, int(remote_size)))
    return None


def estimate_total_resolve_bytes(requests, allow_remote_probe=None):
    """Estimate total dataset bytes for resolve requests, ignoring cache hit state."""
    if allow_remote_probe is None:
        allow_remote_probe = _parse_bool_env("PLANETKA_R2_PLAN_REMOTE_HEAD", default=False)
    allow_remote_probe = bool(allow_remote_probe)

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
        selected_size = None
        for ext in exts:
            ext_text = str(ext or "")
            candidate_file_name = f"{prefix}_{filename}{ext_text}"
            local_source_path = _find_user_local_source_file(folder, candidate_file_name)
            if local_source_path:
                selected_file_name = candidate_file_name
                try:
                    selected_size = int(max(0, os.path.getsize(local_source_path)))
                except (OSError, RuntimeError, TypeError, ValueError):
                    selected_size = texture_asset_size_bytes(folder, candidate_file_name, allow_remote_probe=allow_remote_probe)
                break
            if not selected_file_name:
                selected_file_name = candidate_file_name
            local_size = texture_asset_size_bytes(folder, candidate_file_name, allow_remote_probe=False)
            if local_size is not None:
                selected_file_name = candidate_file_name
                selected_size = int(max(0, int(local_size)))
                break
            if allow_remote_probe:
                remote_size = _lookup_remote_texture_size(folder, candidate_file_name)
                if remote_size is not None:
                    selected_file_name = candidate_file_name
                    selected_size = int(max(0, int(remote_size)))
                    break

        if not selected_file_name:
            continue

        dedupe_key = f"{folder}/{selected_file_name}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        planned_files += 1

        if selected_size is None:
            unknown_files += 1
            continue
        planned_total += int(max(0, selected_size))

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


def retain_recent_resolve_cache(resolved_paths, keep_count=2):
    del resolved_paths, keep_count
    cfg = _get_config()
    if cfg is None:
        return {"kept_snapshots": 0, "kept_files": 0, "removed_files": 0}
    _maybe_prune_cache(cfg, force=False)
    return {
        "kept_snapshots": 0,
        "kept_files": 0,
        "removed_files": 0,
    }


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


def set_resolve_request_context(
    resolve_id="",
    texture_quality_mode="",
    cancel_event=None,
    nav_latitude_deg="",
    nav_longitude_deg="",
    nav_altitude_km="",
    pricing_tiles=None,
):
    global _REQUEST_CONTEXT_RESOLVE_ID
    global _REQUEST_CONTEXT_TEXTURE_MODE
    global _REQUEST_CONTEXT_CANCEL_EVENT
    global _REQUEST_CONTEXT_NAV_LAT
    global _REQUEST_CONTEXT_NAV_LON
    global _REQUEST_CONTEXT_NAV_ALT_KM
    global _REQUEST_CONTEXT_TILE_TOKEN
    global _REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT
    global _REQUEST_CONTEXT_PRICING_TILES
    with _REQUEST_CONTEXT_LOCK:
        _REQUEST_CONTEXT_RESOLVE_ID = str(resolve_id or "").strip()[:128]
        safe_mode = str(texture_quality_mode or "").strip().lower()
        if safe_mode in {"half", "balanced"}:
            safe_mode = "full"
        elif safe_mode == "full":
            safe_mode = "full"
        elif safe_mode != "preview":
            safe_mode = ""
        _REQUEST_CONTEXT_TEXTURE_MODE = safe_mode
        _REQUEST_CONTEXT_CANCEL_EVENT = cancel_event
        try:
            _REQUEST_CONTEXT_NAV_LAT = str(float(nav_latitude_deg)).strip()
        except (TypeError, ValueError):
            _REQUEST_CONTEXT_NAV_LAT = ""
        try:
            _REQUEST_CONTEXT_NAV_LON = str(float(nav_longitude_deg)).strip()
        except (TypeError, ValueError):
            _REQUEST_CONTEXT_NAV_LON = ""
        try:
            _REQUEST_CONTEXT_NAV_ALT_KM = str(max(0.0, float(nav_altitude_km))).strip()
        except (TypeError, ValueError):
            _REQUEST_CONTEXT_NAV_ALT_KM = ""
        _REQUEST_CONTEXT_TILE_TOKEN = ""
        _REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT = 0.0
        if isinstance(pricing_tiles, (list, tuple)):
            _REQUEST_CONTEXT_PRICING_TILES = tuple(
                str(entry.get("tile_key") or entry.get("tileKey") or entry.get("key") or "").strip()
                if isinstance(entry, dict)
                else str(entry or "").strip()
                for entry in pricing_tiles
            )
        else:
            _REQUEST_CONTEXT_PRICING_TILES = ()


def clear_resolve_request_context():
    set_resolve_request_context(
        "",
        "",
        cancel_event=None,
        nav_latitude_deg="",
        nav_longitude_deg="",
        nav_altitude_km="",
        pricing_tiles=None,
    )


def request_global_resolve_cancel():
    global _REQUEST_CONTEXT_FORCE_CANCEL
    with _REQUEST_CONTEXT_LOCK:
        _REQUEST_CONTEXT_FORCE_CANCEL = True


def clear_global_resolve_cancel():
    global _REQUEST_CONTEXT_FORCE_CANCEL
    with _REQUEST_CONTEXT_LOCK:
        _REQUEST_CONTEXT_FORCE_CANCEL = False


def _invalidate_request_context_tile_token():
    global _REQUEST_CONTEXT_TILE_TOKEN
    global _REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT
    with _REQUEST_CONTEXT_LOCK:
        _REQUEST_CONTEXT_TILE_TOKEN = ""
        _REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT = 0.0


def _request_tile_session_token(resolve_id, quality_mode, allow_refresh=True):
    cfg = _get_config()
    if cfg is None:
        return "", 0.0
    safe_resolve_id = str(resolve_id or "").strip()[:128]
    safe_quality_mode = str(quality_mode or "").strip().lower()
    if safe_quality_mode == "balanced":
        safe_quality_mode = "full"
    if safe_quality_mode not in {"preview", "full"}:
        return "", 0.0
    if not safe_resolve_id:
        return "", 0.0

    url = cfg.endpoint.rstrip("/") + "/tiles/session"
    payload = {
        "resolve_id": safe_resolve_id,
        "quality_mode": safe_quality_mode,
    }
    with _REQUEST_CONTEXT_LOCK:
        tile_keys = tuple(key for key in (_REQUEST_CONTEXT_PRICING_TILES or ()) if str(key or "").strip())
    if tile_keys:
        payload["credit_protocol"] = "land_credits_v1"
        payload["tile_keys"] = list(tile_keys)
    payload_bytes = json.dumps(payload, ensure_ascii=True).encode("utf-8")

    def _attempt(refresh_allowed):
        headers = {
            "User-Agent": "Planetka-Blender",
            "Content-Type": "application/json; charset=utf-8",
            **get_authorized_headers(allow_refresh=refresh_allowed),
        }
        request = urllib.request.Request(url, method="POST", headers=headers, data=payload_bytes)
        with urllib.request.urlopen(request, timeout=_R2_TIMEOUT_SECONDS) as response:
            raw = response.read() or b"{}"
        try:
            decoded = raw.decode("utf-8", errors="replace")
        except (TypeError, ValueError, AttributeError):
            decoded = "{}"
        try:
            data = json.loads(decoded)
        except (TypeError, ValueError):
            data = {}
        try:
            credits_charged = float(data.get("credits_charged", 0.0) or 0.0)
        except (TypeError, ValueError, AttributeError):
            credits_charged = 0.0
        if credits_charged > 0.0:
            try:
                from .credit_api import clear_credit_caches
                clear_credit_caches()
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed clearing credit cache after tile unlock", exc_info=True)
        token = str(data.get("tile_token", "") or "").strip()
        if not token:
            return "", 0.0
        expires_in_seconds = 0
        try:
            expires_in_seconds = int(float(data.get("expires_in_seconds", 0) or 0))
        except (TypeError, ValueError):
            expires_in_seconds = 0
        expires_in_seconds = max(30, min(3600, int(expires_in_seconds or 900)))
        return token, float(time.time() + float(expires_in_seconds))

    try:
        return _attempt(bool(allow_refresh))
    except AuthApiError:
        return "", 0.0
    except urllib.error.HTTPError as exc:
        error_payload = {}
        try:
            raw_error = exc.read() or b"{}"
            error_payload = json.loads(raw_error.decode("utf-8", errors="replace") or "{}")
        except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
            error_payload = {}
        error_code = str(error_payload.get("error", "") or "").strip().lower()
        if int(getattr(exc, "code", 0) or 0) == 402 and error_code == "insufficient_credits":
            required = error_payload.get("required_credits", 0)
            balance = error_payload.get("balance_credits", 0)
            raise RuntimeError(
                f"Not enough Planetka credits for this Resolve (required={required}, balance={balance})."
            ) from exc
        if int(getattr(exc, "code", 0)) == 401 and bool(allow_refresh):
            try:
                refresh_auth_session()
                return _attempt(False)
            except (AuthApiError, urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TypeError, ValueError, AttributeError, OSError):
                return "", 0.0
        return "", 0.0
    except (urllib.error.URLError, RuntimeError, TypeError, ValueError, AttributeError, OSError):
        return "", 0.0


def _get_request_context_tile_token(allow_refresh=True):
    global _REQUEST_CONTEXT_TILE_TOKEN
    global _REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT
    global _REQUEST_CONTEXT_RESOLVE_ID
    global _REQUEST_CONTEXT_TEXTURE_MODE
    with _REQUEST_CONTEXT_LOCK:
        current_token = str(_REQUEST_CONTEXT_TILE_TOKEN or "").strip()
        current_expiry = float(_REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT or 0.0)
        resolve_id = str(_REQUEST_CONTEXT_RESOLVE_ID or "").strip()
        quality_mode = str(_REQUEST_CONTEXT_TEXTURE_MODE or "").strip().lower()
        now = float(time.time())
        if current_token and current_expiry > (now + 5.0):
            return current_token
        if quality_mode == "balanced":
            quality_mode = "full"
        if quality_mode not in {"preview", "full"}:
            return ""
    # Do not hold _REQUEST_CONTEXT_LOCK while requesting a tile session token:
    # _request_tile_session_token() also reads request context. Holding the lock
    # here deadlocks downloads before the first GET, leaving UI at 0.00 MB.
    #
    # A separate fetch lock is still required: S2/EL/WT/PO downloads start in
    # parallel, and without serialization each worker can create its own paid
    # tile session before the first token is cached.
    with _REQUEST_CONTEXT_TILE_TOKEN_FETCH_LOCK:
        with _REQUEST_CONTEXT_LOCK:
            current_token = str(_REQUEST_CONTEXT_TILE_TOKEN or "").strip()
            current_expiry = float(_REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT or 0.0)
            current_resolve_id = str(_REQUEST_CONTEXT_RESOLVE_ID or "").strip()
            current_quality_mode = str(_REQUEST_CONTEXT_TEXTURE_MODE or "").strip().lower()
            now = float(time.time())
            if current_quality_mode == "balanced":
                current_quality_mode = "full"
            if (
                current_resolve_id == resolve_id
                and current_quality_mode == quality_mode
                and current_token
                and current_expiry > (now + 5.0)
            ):
                return current_token
        token, expires_at = _request_tile_session_token(
            resolve_id=resolve_id,
            quality_mode=quality_mode,
            allow_refresh=allow_refresh,
        )
    safe_token = str(token or "").strip()
    safe_expires_at = float(expires_at or 0.0)
    with _REQUEST_CONTEXT_LOCK:
        if (
            str(_REQUEST_CONTEXT_RESOLVE_ID or "").strip() == resolve_id
            and str(_REQUEST_CONTEXT_TEXTURE_MODE or "").strip().lower() == quality_mode
        ):
            _REQUEST_CONTEXT_TILE_TOKEN = safe_token
            _REQUEST_CONTEXT_TILE_TOKEN_EXPIRES_AT = safe_expires_at
            return str(_REQUEST_CONTEXT_TILE_TOKEN or "").strip()
    return safe_token


def ensure_resolve_pricing_session(allow_refresh=True):
    """Ensure the current Full Quality resolve has a backend unlock session.

    Full Quality files may already be present in the local cache or Local Source.
    Pricing must still be enforced per account before those files are used; the
    download token is just the transport mechanism for the same unlock call.
    """
    with _REQUEST_CONTEXT_LOCK:
        quality_mode = str(_REQUEST_CONTEXT_TEXTURE_MODE or "").strip().lower()
        pricing_tiles = tuple(key for key in (_REQUEST_CONTEXT_PRICING_TILES or ()) if str(key or "").strip())
    if quality_mode == "balanced":
        quality_mode = "full"
    if quality_mode != "full" or not pricing_tiles:
        return ""
    return _get_request_context_tile_token(allow_refresh=allow_refresh)


@contextmanager
def resolve_request_context(
    resolve_id="",
    texture_quality_mode="",
    cancel_event=None,
    nav_latitude_deg="",
    nav_longitude_deg="",
    nav_altitude_km="",
    pricing_tiles=None,
):
    set_resolve_request_context(
        resolve_id,
        texture_quality_mode=texture_quality_mode,
        cancel_event=cancel_event,
        nav_latitude_deg=nav_latitude_deg,
        nav_longitude_deg=nav_longitude_deg,
        nav_altitude_km=nav_altitude_km,
        pricing_tiles=pricing_tiles,
    )
    try:
        yield
    finally:
        clear_resolve_request_context()


def _is_request_cancelled():
    with _REQUEST_CONTEXT_LOCK:
        event = _REQUEST_CONTEXT_CANCEL_EVENT
        forced_cancel = bool(_REQUEST_CONTEXT_FORCE_CANCEL)
    if forced_cancel:
        return True
    if event is None:
        return False
    is_set = getattr(event, "is_set", None)
    if not callable(is_set):
        return False
    try:
        return bool(is_set())
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _signed_headers(cfg, method, key, allow_refresh=True):
    del method
    headers = {
        "User-Agent": "Planetka-Blender",
        **get_authorized_headers(allow_refresh=allow_refresh),
    }
    with _REQUEST_CONTEXT_LOCK:
        resolve_id = str(_REQUEST_CONTEXT_RESOLVE_ID or "").strip()
        quality_mode = str(_REQUEST_CONTEXT_TEXTURE_MODE or "").strip().lower()
        nav_lat = str(_REQUEST_CONTEXT_NAV_LAT or "").strip()
        nav_lon = str(_REQUEST_CONTEXT_NAV_LON or "").strip()
        nav_alt = str(_REQUEST_CONTEXT_NAV_ALT_KM or "").strip()
    if resolve_id:
        headers["X-Planetka-Resolve-Id"] = resolve_id
    if quality_mode == "balanced":
        quality_mode = "full"
    if quality_mode in {"full", "preview"}:
        headers["X-Planetka-Quality-Mode"] = quality_mode
    if nav_lat:
        headers["X-Planetka-Nav-Latitude"] = nav_lat
    if nav_lon:
        headers["X-Planetka-Nav-Longitude"] = nav_lon
    if nav_alt:
        headers["X-Planetka-Nav-Altitude-Km"] = nav_alt
    tile_token = _get_request_context_tile_token(allow_refresh=allow_refresh)
    if tile_token:
        headers["X-Planetka-Tile-Token"] = tile_token
        headers.pop("Authorization", None)
    url = cfg.endpoint.rstrip("/") + "/tiles/" + urllib.parse.quote(key, safe="/-_.~")
    return url, headers


def _r2_request(
    method,
    key,
    destination_path=None,
    cancel_event=None,
    progress_callback=None,
    track_global_progress=True,
):
    global _ACTIVE_DOWNLOADS
    global _ACTIVE_DOWNLOAD_BYTES
    global _ACTIVE_EXPECTED_BYTES
    global _CAPTURE_DOWNLOAD_BYTES
    global _CAPTURE_DOWNLOAD_MS
    global _CAPTURE_TOTAL_BYTES
    cfg = _get_config()
    if cfg is None:
        return False

    def _cancelled():
        if _is_request_cancelled():
            return True
        if cancel_event is None:
            return False
        is_set = getattr(cancel_event, "is_set", None)
        if not callable(is_set):
            return False
        try:
            return bool(is_set())
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return False

    def _report_progress(delta_bytes=0, total_bytes=0):
        if not callable(progress_callback):
            return
        try:
            progress_callback(int(max(0, int(delta_bytes or 0))), int(max(0, int(total_bytes or 0))))
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: unlocked-download progress callback failed", exc_info=True)

    if _cancelled():
        raise RuntimeError("Planetka resolve request cancelled.")

    last_error = None
    for _ in range(_R2_RETRIES + 1):
        if _cancelled():
            raise RuntimeError("Planetka resolve request cancelled.")
        refreshed = False
        file_download = bool(method == "GET" and destination_path is not None)
        capture_download = bool(file_download and track_global_progress)
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
                if file_download:
                    content_length_raw = response.headers.get("Content-Length", "")
                    try:
                        parsed_length = int(content_length_raw or 0)
                        attempt_expected = max(0, parsed_length)
                    except (TypeError, ValueError):
                        attempt_expected = 0
                    _report_progress(0, attempt_expected)
                if capture_download:
                    if attempt_expected > 0:
                        with _METRICS_LOCK:
                            _ACTIVE_EXPECTED_BYTES += attempt_expected
                if destination_path is not None:
                    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                    temp_path = f"{destination_path}.part.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1_000_000)}"
                    try:
                        with open(temp_path, "wb") as handle:
                            while True:
                                if _cancelled():
                                    raise RuntimeError("Planetka resolve request cancelled.")
                                chunk = response.read(_R2_READ_CHUNK_BYTES)
                                if not chunk:
                                    break
                                handle.write(chunk)
                                if file_download:
                                    chunk_len = int(len(chunk))
                                    attempt_downloaded += chunk_len
                                    _report_progress(chunk_len, attempt_expected)
                                if capture_download:
                                    pending_progress_bytes += int(len(chunk))
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
                        if _cancelled():
                            raise RuntimeError("Planetka resolve request cancelled.")
                        os.replace(temp_path, destination_path)
                    finally:
                        try:
                            if os.path.isfile(temp_path):
                                os.remove(temp_path)
                        except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
                            pass
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
                request_headers = headers if isinstance(headers, dict) else {}
                if str(request_headers.get("X-Planetka-Tile-Token", "") or "").strip():
                    _invalidate_request_context_tile_token()
                    refreshed = True
                    continue
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
                if "insufficient_credits" in combined or "tile_not_unlocked" in combined:
                    if error_message:
                        raise RuntimeError(error_message)
                    raise RuntimeError("Not enough Planetka credits for this Resolve.")
                if any(token in combined for token in ("quality_mode_not_allowed", "not_allowed_for_tier", "access_denied")):
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
                if any(token in combined for token in ("quality_mode_not_allowed", "not_allowed_for_tier", "access_denied")):
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


def download_remote_asset_to_path(
    folder,
    file_name,
    destination_path,
    cancel_event=None,
    progress_callback=None,
    texture_quality_mode="FULL",
    resolve_id="",
    pricing_tiles=None,
    track_global_progress=True,
):
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    target = os.path.abspath(os.path.expanduser(str(destination_path or "")))
    if not safe_folder or not safe_name or not target:
        return False
    safe_resolve_id = str(resolve_id or "").strip()[:128]
    if not safe_resolve_id:
        safe_resolve_id = f"download-unlocked-{int(time.time() * 1000)}"
    with resolve_request_context(
        safe_resolve_id,
        texture_quality_mode=texture_quality_mode,
        cancel_event=cancel_event,
        pricing_tiles=pricing_tiles or (),
    ):
        return _r2_request(
            "GET",
            _remote_key(safe_folder, safe_name),
            destination_path=target,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
            track_global_progress=track_global_progress,
        )


def _local_candidate_paths(base_path, folder, file_name):
    base_abs = ""
    try:
        base_abs = str(base_path or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        base_abs = ""

    if not base_abs:
        return []

    return [os.path.join(base_abs, folder, file_name)]


def _get_user_local_source_root():
    try:
        from .extension_prefs import get_prefs
        prefs = get_prefs()
        root = str(getattr(prefs, "local_texture_source_path", "") or "").strip()
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        root = ""
    if not root:
        root = str(_env("PLANETKA_LOCAL_TEXTURE_SOURCE_PATH") or "").strip()
    if not root:
        return ""
    try:
        root = os.path.abspath(os.path.expanduser(root))
    except (RuntimeError, TypeError, ValueError, OSError):
        return ""
    return root if os.path.isdir(root) else ""


def _is_auto_download_unlocked_tiles_enabled():
    try:
        from .extension_prefs import get_prefs
        prefs = get_prefs()
        return bool(getattr(prefs, "auto_download_unlocked_tiles", False))
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _current_request_texture_mode():
    with _REQUEST_CONTEXT_LOCK:
        return str(_REQUEST_CONTEXT_TEXTURE_MODE or "").strip().lower()


def _local_source_candidate_paths(folder, file_name):
    root = _get_user_local_source_root()
    if not root:
        return []
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return []
    return [os.path.join(root, safe_folder, safe_name)]


def _find_user_local_source_file(folder, file_name):
    for candidate in _local_source_candidate_paths(folder, file_name):
        if _is_cache_file_usable(candidate):
            return candidate
    return ""


def find_local_source_asset(folder, file_name):
    return _find_user_local_source_file(folder, file_name)


def get_local_source_stale_notice():
    return str(_LOCAL_SOURCE_STALE_NOTICE or "")


def clear_local_source_stale_notice():
    global _LOCAL_SOURCE_STALE_NOTICE
    _LOCAL_SOURCE_STALE_NOTICE = ""


def remote_asset_metadata(folder, file_name):
    cfg = _get_config()
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if cfg is None or not safe_folder or not safe_name:
        return {}
    key = _remote_key(safe_folder, safe_name)
    try:
        url, headers = _signed_headers(cfg, method="HEAD", key=key)
        request = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(request, timeout=_R2_TIMEOUT_SECONDS) as response:
            return {
                "etag": str(response.headers.get("ETag", "") or "").strip(),
                "size": int(max(0, int(response.headers.get("Content-Length", "0") or 0))),
            }
    except (AuthApiError, urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed reading remote asset metadata", exc_info=True)
        return {}


def _check_local_source_freshness(folder, file_name, path):
    global _LOCAL_SOURCE_STALE_NOTICE
    sidecar_path = f"{path}.planetka.json"
    key = f"{folder}/{file_name}"
    if key in _LOCAL_SOURCE_FRESHNESS_CHECKED:
        return
    _LOCAL_SOURCE_FRESHNESS_CHECKED.add(key)
    try:
        with open(sidecar_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return
    local_etag = str(payload.get("etag", "") or "").strip()
    if not local_etag:
        return
    remote = remote_asset_metadata(folder, file_name)
    remote_etag = str(remote.get("etag", "") or "").strip()
    if remote_etag and remote_etag != local_etag:
        _LOCAL_SOURCE_STALE_NOTICE = (
            f"Local Source has older unlocked data for {key}. Use Download Unlocked to refresh it."
        )
        logger.warning(
            "Planetka local source asset is older than Cloudflare copy; re-download unlocked tiles: %s",
            key,
        )


def _copy_to_local_source(folder, file_name, source_path):
    root = _get_user_local_source_root()
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    source = str(source_path or "").strip()
    if not root or not safe_folder or not safe_name or not source or not _is_cache_file_usable(source):
        return False
    target_dir = os.path.join(root, safe_folder)
    target_path = os.path.join(target_dir, safe_name)
    try:
        if os.path.abspath(source) == os.path.abspath(target_path):
            return True
        os.makedirs(target_dir, exist_ok=True)
        if _is_cache_file_usable(target_path):
            return True
        temp_path = f"{target_path}.part.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1_000_000)}"
        try:
            shutil.copyfile(source, temp_path)
            os.replace(temp_path, target_path)
        finally:
            try:
                if os.path.isfile(temp_path):
                    os.remove(temp_path)
            except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
                pass
        return True
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed auto-copying unlocked tile to Local Source", exc_info=True)
        return False


def _maybe_auto_copy_unlocked_asset(folder, file_name, source_path):
    if not _is_auto_download_unlocked_tiles_enabled():
        return
    mode = _current_request_texture_mode()
    if mode != "full":
        return
    _copy_to_local_source(folder, file_name, source_path)


def _cached_remote_path(folder, file_name):
    cfg = _get_config()
    if cfg is None:
        return ""
    return os.path.join(cfg.cache_root, folder, file_name)


def _is_cache_file_usable(path):
    safe_path = str(path or "").strip()
    if not safe_path:
        return False
    try:
        return bool(os.path.isfile(safe_path) and int(os.path.getsize(safe_path)) > 0)
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _remove_invalid_cache_file(path):
    safe_path = str(path or "").strip()
    if not safe_path:
        return
    try:
        if os.path.isfile(safe_path) and int(os.path.getsize(safe_path)) <= 0:
            os.remove(safe_path)
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        return


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
    if cached_path and _is_cache_file_usable(cached_path):
        _maybe_auto_copy_unlocked_asset(safe_folder, safe_name, cached_path)
        return cached_path
    _remove_invalid_cache_file(cached_path)

    key = _remote_key(safe_folder, safe_name)
    if key and cached_path:
        downloaded = _r2_request("GET", key, destination_path=cached_path)
        if downloaded and _is_cache_file_usable(cached_path):
            _maybe_auto_copy_unlocked_asset(safe_folder, safe_name, cached_path)
            return cached_path
    return ""


def resolve_texture_file(base_path, folder, prefix, filename, extensions):
    exts = tuple(extensions or (".exr",))

    for ext in exts:
        file_name = f"{prefix}_{filename}{ext}"
        local_source_path = _find_user_local_source_file(folder, file_name)
        if local_source_path:
            return local_source_path

    if not is_remote_source_configured(base_path):
        for ext in exts:
            file_name = f"{prefix}_{filename}{ext}"
            for candidate in _local_candidate_paths(base_path, folder, file_name):
                if _is_cache_file_usable(candidate):
                    return candidate
        return ""

    cfg = _get_config()
    if cfg is None:
        return ""

    for ext in exts:
        file_name = f"{prefix}_{filename}{ext}"
        cached_path = _cached_remote_path(folder, file_name)
        if cached_path and _is_cache_file_usable(cached_path):
            _maybe_auto_copy_unlocked_asset(folder, file_name, cached_path)
            return cached_path
        _remove_invalid_cache_file(cached_path)

    for ext in exts:
        file_name = f"{prefix}_{filename}{ext}"
        cached_path = _cached_remote_path(folder, file_name)
        key = _remote_key(folder, file_name)
        if key and cached_path:
            downloaded = _r2_request("GET", key, destination_path=cached_path)
            if downloaded and _is_cache_file_usable(cached_path):
                _maybe_auto_copy_unlocked_asset(folder, file_name, cached_path)
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

    def _is_cancelled_prefetch_error(message):
        text = str(message or "").strip().lower()
        if not text:
            return False
        return ("cancel" in text) and ("resolve" in text or "request" in text)

    for request in requests or ():
        if _is_request_cancelled() or (cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set()):
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
    worker_cap = max(1, min(int(worker_cap), int(_R2_PREFETCH_ABSOLUTE_MAX_WORKERS)))
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
        cache_exists = bool(cache_path and _is_cache_file_usable(cache_path))
        if cache_path and not cache_exists:
            _remove_invalid_cache_file(cache_path)
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
        if _is_request_cancelled() or (cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set()):
            return {"state": "cancelled", "task": task}
        try:
            path = resolve_texture_file(
                base_path=resolved_base_path,
                folder=task_folder,
                prefix=task_prefix,
                filename=task_filename,
                extensions=task_exts,
            )
            if path and _is_cache_file_usable(path):
                return {"state": "resolved", "task": task}
            return {"state": "missing", "task": task}
        except RuntimeError as exc:
            error_text = str(exc)
            if _is_cancelled_prefetch_error(error_text):
                return {"state": "cancelled", "task": task}
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
                    if _is_request_cancelled() or (cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set()):
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
        reportable_missing_details = []
        for entry in missing_details:
            if not isinstance(entry, dict):
                continue
            folder_value = str(entry.get("folder", "") or "").strip().upper()
            prefix_value = str(entry.get("prefix", "") or "").strip()
            tile_value = str(entry.get("tile", "") or "").strip()
            ext_value = str(entry.get("ext", "") or "").strip().lower()
            if not folder_value or not prefix_value or not tile_value:
                continue
            if ext_value and not ext_value.startswith("."):
                ext_value = f".{ext_value}"
            if not ext_value:
                ext_value = ".exr"
            file_name = f"{prefix_value}_{tile_value}{ext_value}"
            if not is_indexed_tile_asset(folder_value, file_name):
                continue
            reportable_missing_details.append(entry)
        if reportable_missing_details:
            logger.warning(
                "Planetka resolve prefetch diagnostics: required_missing=%d resolved=%d error=%d sample=%s",
                int(len(reportable_missing_details)),
                int(resolved_count),
                int(error_count),
                json.dumps(reportable_missing_details, ensure_ascii=True),
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
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return False

    if not is_remote_source_configured(base_path):
        for candidate in _local_candidate_paths(base_path, safe_folder, safe_name):
            if _is_cache_file_usable(candidate):
                return True
        return False

    cfg = _get_config()
    if cfg is None:
        return False

    cached_path = _cached_remote_path(safe_folder, safe_name)
    if cached_path and _is_cache_file_usable(cached_path):
        return True
    _remove_invalid_cache_file(cached_path)

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
