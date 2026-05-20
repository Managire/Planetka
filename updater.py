import hashlib
import json
import logging
import os
import platform
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None


logger = logging.getLogger(__name__)

ADDON_ID = "planetka"
STATE_FILE_NAME = "state.json"
DOWNLOAD_DIR_NAME = "downloads"
BACKUP_DIR_NAME = "backups"
DEFAULT_CHECK_INTERVAL_SECONDS = int(os.getenv("PLANETKA_UPDATE_CHECK_INTERVAL_SECONDS") or "21600")
DEFAULT_REQUEST_TIMEOUT_SECONDS = int(os.getenv("PLANETKA_UPDATE_TIMEOUT_SECONDS") or "15")
DEFAULT_MANIFEST_URL = str(
    os.getenv("PLANETKA_UPDATE_MANIFEST_URL")
    or os.getenv("PLANETKA_ADDON_UPDATE_MANIFEST_URL")
    or "https://api.planetka.io/addon/update-manifest"
).strip()

_LOCK = threading.Lock()
_CHECK_THREAD = None
_RUNTIME = {
    "checking": False,
    "message": "",
    "latest_version": "",
    "current_version": "",
    "update_ready": False,
    "last_error": "",
    "last_check_at": 0,
    "release_notes_url": "",
    "phase": "idle",
    "downloaded_bytes": 0,
    "download_total_bytes": 0,
}

_UPDATER_RUNTIME_EXCEPTIONS = (
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    AttributeError,
    KeyError,
    LookupError,
    ReferenceError,
    shutil.Error,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
)


def _addon_root():
    return os.path.dirname(os.path.abspath(__file__))


def _cache_root():
    if platform.system().lower() == "darwin":
        base = os.path.expanduser("~/Library/Caches/Planetka")
    else:
        base = os.path.expanduser("~/.cache/planetka")
    return os.path.join(base, "updater")


def _state_path():
    return os.path.join(_cache_root(), STATE_FILE_NAME)


def _ensure_cache_dirs():
    root = _cache_root()
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, DOWNLOAD_DIR_NAME), exist_ok=True)
    os.makedirs(os.path.join(root, BACKUP_DIR_NAME), exist_ok=True)


def _load_state():
    _ensure_cache_dirs()
    path = _state_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError, TypeError):
        logger.debug("Planetka updater: failed reading updater state", exc_info=True)
    return {}


def _save_state(state):
    _ensure_cache_dirs()
    target = _state_path()
    tmp = f"{target}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state if isinstance(state, dict) else {}, handle, indent=2, sort_keys=True)
        os.replace(tmp, target)
    except OSError:
        logger.debug("Planetka updater: failed writing updater state", exc_info=True)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _version_tokens(version_text):
    text = str(version_text or "").strip()
    if not text:
        return ()
    tokens = []
    for part in text.split("."):
        match = re.match(r"^(\d+)", str(part).strip())
        if not match:
            break
        tokens.append(int(match.group(1)))
    return tuple(tokens)


def _is_newer_version(remote_version, local_version):
    remote = _version_tokens(remote_version)
    local = _version_tokens(local_version)
    if remote and local:
        length = max(len(remote), len(local))
        remote = remote + (0,) * (length - len(remote))
        local = local + (0,) * (length - len(local))
        return remote > local
    return str(remote_version or "").strip() != str(local_version or "").strip()


def _read_manifest(path):
    if not os.path.isfile(path):
        return {}
    if tomllib is not None:
        try:
            with open(path, "rb") as handle:
                payload = tomllib.load(handle)
            if isinstance(payload, dict):
                return payload
        except (OSError, ValueError, TypeError):
            logger.debug("Planetka updater: tomllib manifest parse failed", exc_info=True)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return {}
    result = {}
    id_match = re.search(r'^\s*id\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    version_match = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if id_match:
        result["id"] = id_match.group(1).strip()
    if version_match:
        result["version"] = version_match.group(1).strip()
    return result


def get_local_version():
    manifest = _read_manifest(os.path.join(_addon_root(), "blender_manifest.toml"))
    return str(manifest.get("version", "") or "").strip()


def _set_runtime(**kwargs):
    with _LOCK:
        _RUNTIME.update(kwargs)


def get_public_status():
    with _LOCK:
        status = dict(_RUNTIME)
    state = _load_state()
    if int(status.get("last_check_at", 0) or 0) <= 0:
        try:
            last_check_at = int(state.get("last_check_at", 0) or 0)
        except (TypeError, ValueError):
            last_check_at = 0
        if last_check_at > 0:
            status["last_check_at"] = last_check_at
            _set_runtime(last_check_at=last_check_at)
    current = str(status.get("current_version") or "").strip() or get_local_version()
    status["current_version"] = current
    if not bool(status.get("update_ready", False)):
        available = state.get("available_update")
        if isinstance(available, dict):
            available_version = str(available.get("version") or "").strip()
            if available_version and _is_newer_version(available_version, current):
                status["update_ready"] = True
                status["latest_version"] = available_version
                release_notes_url = str(available.get("release_notes_url") or "").strip()
                if release_notes_url:
                    status["release_notes_url"] = release_notes_url
                _set_runtime(
                    update_ready=True,
                    latest_version=available_version,
                    release_notes_url=release_notes_url,
                )
    return status


def _fetch_manifest():
    request = urllib.request.Request(
        DEFAULT_MANIFEST_URL,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": f"Planetka-Addon-Updater/{get_local_version() or '0'}",
        },
    )
    with urllib.request.urlopen(request, timeout=max(3, int(DEFAULT_REQUEST_TIMEOUT_SECONDS))) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_manifest_payload")
    if not bool(payload.get("ok", True)):
        raise RuntimeError(str(payload.get("error") or "manifest_not_ok"))
    addon_id = str(payload.get("addon_id") or payload.get("id") or ADDON_ID).strip().lower()
    if addon_id and addon_id != ADDON_ID:
        raise RuntimeError(f"manifest_addon_id_mismatch:{addon_id}")
    version = str(payload.get("version") or "").strip()
    download_url = str(payload.get("download_url") or "").strip()
    sha256_hex = str(payload.get("sha256") or "").strip().lower()
    release_notes_url = str(payload.get("release_notes_url") or "").strip()
    mandatory = bool(payload.get("mandatory", False))
    if not version:
        raise RuntimeError("manifest_missing_version")
    return {
        "version": version,
        "download_url": download_url,
        "sha256": sha256_hex,
        "release_notes_url": release_notes_url,
        "mandatory": mandatory,
        "raw": payload,
    }


def _sha256_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _format_mb_progress(downloaded_bytes, total_bytes):
    downloaded_mb = float(max(0, int(downloaded_bytes or 0))) / (1024.0 * 1024.0)
    total = int(total_bytes or 0)
    if total > 0:
        total_mb = float(total) / (1024.0 * 1024.0)
        return f"{downloaded_mb:.2f} / {total_mb:.2f} MB"
    return f"{downloaded_mb:.2f} MB"


def _download_file(url, target_path, progress_callback=None):
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": f"Planetka-Addon-Updater/{get_local_version() or '0'}",
        },
    )
    tmp_path = f"{target_path}.tmp"
    downloaded_bytes = 0
    total_bytes = 0
    last_report_at = 0.0
    with urllib.request.urlopen(request, timeout=max(5, int(DEFAULT_REQUEST_TIMEOUT_SECONDS) * 6)) as response:
        try:
            total_bytes = int(response.headers.get("Content-Length", "0") or 0)
        except (TypeError, ValueError):
            total_bytes = 0
        if callable(progress_callback):
            progress_callback(downloaded_bytes, total_bytes, False)
        with open(tmp_path, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded_bytes += len(chunk)
                now = time.monotonic()
                should_report = (now - last_report_at) >= 0.15
                if total_bytes > 0 and downloaded_bytes >= total_bytes:
                    should_report = True
                if should_report and callable(progress_callback):
                    progress_callback(downloaded_bytes, total_bytes, False)
                    last_report_at = now
    os.replace(tmp_path, target_path)
    if callable(progress_callback):
        progress_callback(downloaded_bytes, total_bytes, True)


def _safe_zip_relpath(member_name, root_prefix):
    member = str(member_name or "").replace("\\", "/").strip()
    if not member or member.endswith("/"):
        return ""
    if member.startswith("/") or member.startswith("../") or "/../" in member:
        return ""
    if root_prefix:
        root = f"{root_prefix}/"
        if not member.startswith(root):
            return ""
        rel = member[len(root):]
    else:
        rel = member
    rel = rel.strip("/")
    if not rel or rel.startswith(".git/") or "/.git/" in rel:
        return ""
    if rel.startswith("__pycache__/") or "/__pycache__/" in rel:
        return ""
    if rel.endswith(".pyc") or rel.endswith(".pyo"):
        return ""
    return rel


def _zip_manifest_candidates(zip_file):
    candidates = []
    for name in zip_file.namelist():
        if name.endswith("/blender_manifest.toml") or name == "blender_manifest.toml":
            candidates.append(name)
    return candidates


def _select_zip_root(zip_file):
    manifest_paths = _zip_manifest_candidates(zip_file)
    if not manifest_paths:
        raise RuntimeError("update_package_missing_blender_manifest")

    best = None
    for manifest_path in manifest_paths:
        try:
            raw = zip_file.read(manifest_path)
        except KeyError:
            continue
        manifest = {}
        if tomllib is not None:
            try:
                manifest = tomllib.loads(raw.decode("utf-8"))
            except (ValueError, TypeError):
                manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        addon_id = str(manifest.get("id", "") or "").strip().lower()
        version = str(manifest.get("version", "") or "").strip()
        prefix = os.path.dirname(manifest_path).strip("/")
        score = 1 if addon_id == ADDON_ID else 0
        candidate = (score, prefix, addon_id, version)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        raise RuntimeError("update_package_manifest_unreadable")
    if best[2] and best[2] != ADDON_ID:
        raise RuntimeError(f"update_package_addon_id_mismatch:{best[2]}")
    return best[1], best[3]


def _apply_zip_update(zip_path, expected_version=""):
    addon_root = _addon_root()
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    backup_root = os.path.join(_cache_root(), BACKUP_DIR_NAME, f"apply_{timestamp}")
    os.makedirs(backup_root, exist_ok=True)

    written_new_files = []
    backup_files = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_root, package_version = _select_zip_root(zip_file)
            if expected_version and package_version and package_version != expected_version:
                logger.warning(
                    "Planetka updater: package version mismatch expected=%s package=%s",
                    expected_version,
                    package_version,
                )

            members = []
            for name in zip_file.namelist():
                rel = _safe_zip_relpath(name, zip_root)
                if rel:
                    members.append((name, rel))
            if not members:
                raise RuntimeError("update_package_empty")

            for member_name, rel in members:
                destination = os.path.join(addon_root, rel)
                os.makedirs(os.path.dirname(destination), exist_ok=True)

                if os.path.isfile(destination):
                    backup_target = os.path.join(backup_root, rel)
                    os.makedirs(os.path.dirname(backup_target), exist_ok=True)
                    shutil.copy2(destination, backup_target)
                    backup_files.append((destination, backup_target))
                else:
                    written_new_files.append(destination)

                data = zip_file.read(member_name)
                tmp_destination = f"{destination}.pka_tmp"
                with open(tmp_destination, "wb") as handle:
                    handle.write(data)
                os.replace(tmp_destination, destination)
    except _UPDATER_RUNTIME_EXCEPTIONS:
        logger.exception("Planetka updater: failed applying staged update, rolling back")
        for path in written_new_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        for destination, backup_target in reversed(backup_files):
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(backup_target, destination)
            except OSError:
                pass
        raise


def apply_pending_update_on_import():
    state = _load_state()
    pending = state.get("pending")
    local_version = get_local_version()
    _set_runtime(current_version=local_version)
    if not isinstance(pending, dict):
        return False

    version = str(pending.get("version") or "").strip()
    zip_path = str(pending.get("zip_path") or "").strip()
    if not zip_path or not os.path.isfile(zip_path):
        state["pending"] = None
        state["last_error"] = "pending_update_missing_zip"
        _save_state(state)
        _set_runtime(last_error="pending_update_missing_zip")
        return False

    if version and (not _is_newer_version(version, local_version)):
        state["pending"] = None
        _save_state(state)
        return False

    try:
        _apply_zip_update(zip_path, expected_version=version)
        refreshed = get_local_version()
        state["pending"] = None
        state["last_apply_at"] = int(time.time())
        state["last_applied_version"] = str(version or refreshed or "").strip()
        state["current_version"] = str(refreshed or "").strip()
        state["last_error"] = ""
        _save_state(state)
        _set_runtime(
            current_version=str(refreshed or local_version),
            update_ready=False,
            latest_version="",
            message=f"Planetka updated to {str(refreshed or version or '').strip()}.",
            last_error="",
        )
        logger.info("Planetka updater: applied staged update to version %s", str(refreshed or version or "").strip())
        return True
    except _UPDATER_RUNTIME_EXCEPTIONS as exc:
        state["last_error"] = f"apply_failed:{exc}"
        state["pending"] = None
        _save_state(state)
        _set_runtime(last_error=str(state["last_error"]))
        return False


def _run_update_check_worker(force=False):
    manual_check = bool(force)
    state = _load_state()
    now_ts = int(time.time())
    local_version = get_local_version()
    _set_runtime(
        checking=True,
        current_version=local_version,
        last_check_at=int(state.get("last_check_at", 0) or 0),
        last_error="",
        message="Checking for updates…",
        phase="checking_manifest",
        downloaded_bytes=0,
        download_total_bytes=0,
    )
    try:
        manifest = _fetch_manifest()
        latest_version = manifest.get("version", "")
        release_notes_url = manifest.get("release_notes_url", "")
        state["last_manifest"] = manifest.get("raw", {})
        state["last_check_at"] = now_ts
        state["last_error"] = ""
        state["current_version"] = local_version

        if not manifest.get("download_url"):
            _set_runtime(
                checking=False,
                latest_version=str(latest_version or ""),
                release_notes_url=str(release_notes_url or ""),
                update_ready=False,
                last_check_at=now_ts,
                message="Planetka is up to date." if manual_check else "",
                phase="checked" if manual_check else "idle",
                downloaded_bytes=0,
                download_total_bytes=0,
            )
            state["available_update"] = None
            _save_state(state)
            return

        if not _is_newer_version(latest_version, local_version):
            version_label = str(local_version or latest_version or "").strip()
            if manual_check and version_label:
                message = f"Planetka is up to date ({version_label})."
            elif manual_check:
                message = "Planetka is up to date."
            else:
                message = ""
            state["available_update"] = None
            state["pending"] = None
            _save_state(state)
            _set_runtime(
                checking=False,
                latest_version=str(latest_version or "") if manual_check else "",
                release_notes_url=str(release_notes_url or "") if manual_check else "",
                update_ready=False,
                last_check_at=now_ts,
                message=message,
                phase="checked" if manual_check else "idle",
                downloaded_bytes=0,
                download_total_bytes=0,
            )
            return

        state["available_update"] = {
            "version": str(latest_version or "").strip(),
            "download_url": str(manifest.get("download_url") or "").strip(),
            "sha256": str(manifest.get("sha256") or "").strip().lower(),
            "release_notes_url": str(release_notes_url or "").strip(),
            "checked_at": now_ts,
        }
        _save_state(state)
        _set_runtime(
            checking=False,
            latest_version=str(latest_version or ""),
            release_notes_url=str(release_notes_url or ""),
            update_ready=True,
            last_check_at=now_ts,
            message=f"Update available: {str(latest_version or '').strip()}",
            last_error="",
            phase="ready",
            downloaded_bytes=0,
            download_total_bytes=0,
        )
        return

    except urllib.error.HTTPError as exc:
        state["last_check_at"] = now_ts
        if int(getattr(exc, "code", 0) or 0) == 404:
            # Endpoint not deployed yet: stay silent and retry on next interval.
            state["last_error"] = ""
            _save_state(state)
            _set_runtime(
                checking=False,
                last_error="",
                last_check_at=now_ts,
                message="",
                update_ready=False,
                latest_version="",
                release_notes_url="",
                phase="idle",
                downloaded_bytes=0,
                download_total_bytes=0,
            )
            logger.debug("Planetka updater: manifest endpoint not found (404)")
            return
        state["last_error"] = f"network:{exc}"
        _save_state(state)
        _set_runtime(
            checking=False,
            last_error=str(state["last_error"]),
            last_check_at=now_ts,
            message="Update check failed (network).",
            phase="error",
        )
        logger.debug("Planetka updater: update check failed (http)", exc_info=True)
    except (urllib.error.URLError, TimeoutError) as exc:
        state["last_check_at"] = now_ts
        state["last_error"] = f"network:{exc}"
        _save_state(state)
        _set_runtime(
            checking=False,
            last_error=str(state["last_error"]),
            last_check_at=now_ts,
            message="Update check failed (network timeout).",
            phase="error",
        )
        logger.debug("Planetka updater: update check failed (network)", exc_info=True)
    except _UPDATER_RUNTIME_EXCEPTIONS as exc:
        state["last_check_at"] = now_ts
        state["last_error"] = str(exc)
        _save_state(state)
        _set_runtime(
            checking=False,
            last_error=str(exc),
            last_check_at=now_ts,
            message="Update check failed.",
            phase="error",
        )
        logger.debug("Planetka updater: update check failed", exc_info=True)
    finally:
        with _LOCK:
            global _CHECK_THREAD
            _CHECK_THREAD = None


def kickoff_background_update_check(force=False):
    state = _load_state()
    now_ts = int(time.time())
    last_check_at = int(state.get("last_check_at", 0) or 0)
    interval = max(300, int(DEFAULT_CHECK_INTERVAL_SECONDS))
    with _LOCK:
        global _CHECK_THREAD
        if _CHECK_THREAD is not None and _CHECK_THREAD.is_alive():
            return False
        if (not force) and last_check_at and (now_ts - last_check_at) < interval:
            return False
        _CHECK_THREAD = threading.Thread(
            target=_run_update_check_worker,
            kwargs={"force": bool(force)},
            name="planetka-updater-check",
            daemon=True,
        )
        _CHECK_THREAD.start()
        return True


def _run_update_install_worker(force=False):
    del force
    state = _load_state()
    now_ts = int(time.time())
    local_version = get_local_version()
    _set_runtime(
        checking=True,
        current_version=local_version,
        last_check_at=int(state.get("last_check_at", 0) or 0),
        last_error="",
        message="Preparing update…",
        phase="checking_manifest",
        downloaded_bytes=0,
        download_total_bytes=0,
    )
    try:
        manifest = _fetch_manifest()
        latest_version = str(manifest.get("version") or "").strip()
        release_notes_url = str(manifest.get("release_notes_url") or "").strip()
        download_url = str(manifest.get("download_url") or "").strip()
        expected_sha = str(manifest.get("sha256") or "").strip().lower()

        state["last_manifest"] = manifest.get("raw", {})
        state["last_check_at"] = now_ts
        state["last_error"] = ""
        state["current_version"] = local_version

        if not download_url or not _is_newer_version(latest_version, local_version):
            state["available_update"] = None
            state["pending"] = None
            _save_state(state)
            _set_runtime(
                checking=False,
                latest_version="",
                release_notes_url="",
                update_ready=False,
                last_check_at=now_ts,
                message="",
                last_error="",
                phase="idle",
                downloaded_bytes=0,
                download_total_bytes=0,
            )
            return

        download_dir = os.path.join(_cache_root(), DOWNLOAD_DIR_NAME)
        os.makedirs(download_dir, exist_ok=True)
        zip_path = os.path.join(download_dir, f"planetka_{latest_version}.zip")

        _set_runtime(
            checking=True,
            latest_version=latest_version,
            release_notes_url=release_notes_url,
            update_ready=False,
            message=f"Downloading update {latest_version}…",
            phase="downloading",
            downloaded_bytes=0,
            download_total_bytes=0,
        )

        def _progress(downloaded_bytes, total_bytes, done):
            progress_text = _format_mb_progress(downloaded_bytes, total_bytes)
            message = f"Downloading update {latest_version}… ({progress_text})"
            if done:
                message = f"Downloaded update {latest_version} ({progress_text})."
            _set_runtime(
                checking=True,
                latest_version=latest_version,
                release_notes_url=release_notes_url,
                update_ready=False,
                message=message,
                phase="downloading",
                downloaded_bytes=int(downloaded_bytes or 0),
                download_total_bytes=int(total_bytes or 0),
            )

        _download_file(download_url, zip_path, progress_callback=_progress)

        _set_runtime(
            checking=True,
            latest_version=latest_version,
            release_notes_url=release_notes_url,
            update_ready=False,
            message="Verifying update package…",
            phase="verifying",
        )

        if expected_sha:
            actual_sha = _sha256_file(zip_path)
            if actual_sha != expected_sha:
                raise RuntimeError("update_sha256_mismatch")

        state["pending"] = {
            "version": latest_version,
            "zip_path": str(zip_path),
            "sha256": expected_sha,
            "download_url": download_url,
            "release_notes_url": release_notes_url,
            "downloaded_at": now_ts,
        }
        state["available_update"] = None
        _save_state(state)
        _set_runtime(
            checking=False,
            latest_version="",
            release_notes_url="",
            update_ready=False,
            last_check_at=now_ts,
            message=f"Update {latest_version} downloaded. Restart Blender to finish installation.",
            last_error="",
            phase="ready",
            downloaded_bytes=0,
            download_total_bytes=0,
        )
        logger.info("Planetka updater: staged version %s for restart apply", latest_version)
    except urllib.error.HTTPError as exc:
        state["last_check_at"] = now_ts
        state["last_error"] = f"network:{exc}"
        _save_state(state)
        _set_runtime(
            checking=False,
            last_error=str(state["last_error"]),
            last_check_at=now_ts,
            message="Update failed (network).",
            phase="error",
            update_ready=bool(get_public_status().get("update_ready", False)),
        )
        logger.debug("Planetka updater: update install failed (http)", exc_info=True)
    except (urllib.error.URLError, TimeoutError) as exc:
        state["last_check_at"] = now_ts
        state["last_error"] = f"network:{exc}"
        _save_state(state)
        _set_runtime(
            checking=False,
            last_error=str(state["last_error"]),
            last_check_at=now_ts,
            message="Update failed (network timeout).",
            phase="error",
            update_ready=bool(get_public_status().get("update_ready", False)),
        )
        logger.debug("Planetka updater: update install failed (network)", exc_info=True)
    except _UPDATER_RUNTIME_EXCEPTIONS as exc:
        state["last_check_at"] = now_ts
        state["last_error"] = str(exc)
        _save_state(state)
        _set_runtime(
            checking=False,
            last_error=str(exc),
            last_check_at=now_ts,
            message="Update failed.",
            phase="error",
            update_ready=bool(get_public_status().get("update_ready", False)),
        )
        logger.debug("Planetka updater: update install failed", exc_info=True)
    finally:
        with _LOCK:
            global _CHECK_THREAD
            _CHECK_THREAD = None


def kickoff_background_update_install(force=False):
    del force
    with _LOCK:
        global _CHECK_THREAD
        if _CHECK_THREAD is not None and _CHECK_THREAD.is_alive():
            return False
        _CHECK_THREAD = threading.Thread(
            target=_run_update_install_worker,
            kwargs={"force": True},
            name="planetka-updater-install",
            daemon=True,
        )
        _CHECK_THREAD.start()
        return True
