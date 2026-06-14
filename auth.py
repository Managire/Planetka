import base64
import json
import logging
import os
import platform
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
try:
    import tomllib
except (ImportError, ModuleNotFoundError):
    tomllib = None

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_prefs

logger = logging.getLogger(__name__)


DEFAULT_API_BASE_URL = str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/")
CLOUD_OVERLOADED_ERROR_CODE = "planetka_cloud_overloaded"
CLOUD_OVERLOADED_MESSAGE = "Planetka servers are temporarily overloaded. Please wait a few moments and try again."
SESSION_EXPIRED_MESSAGE = "Planetka Cloud session expired. Restart Blender and try again."
NETWORK_UNAVAILABLE_MESSAGE = "Planetka Cloud is not reachable. Check your internet connection, then try again."
DOWNLOAD_INTERRUPTED_MESSAGE = "Planetka download was interrupted because the internet connection was lost. Check your connection, then click Resolve Planetka again."
_ADDON_VERSION_CACHE = None
_ADDON_EDITION_CACHE = None
_CLOUD_CONNECTION_CACHE = {
    "checked": False,
    "timestamp": 0.0,
    "online": True,
    "message": "",
}
_AUTHORIZED_HEADERS_CACHE_LOCK = threading.Lock()
_AUTHORIZED_HEADERS_CACHE = {}
_CLOUD_CONNECTION_OFFLINE_MESSAGE = NETWORK_UNAVAILABLE_MESSAGE
_OVERLOAD_HTTP_STATUSES = {429, 503, 520, 522, 524, 529}
_SESSION_LIMIT_OR_ACCESS_TOKENS = (
    "request limit reached",
    "planetka request limit reached",
    "rate_limit_auth",
    "device_limit_exceeded",
    "session_blocked",
    "access_denied",
)
_KNOWN_NON_OVERLOAD_ERROR_TOKENS = ()
_OVERLOAD_TEXT_TOKENS = (
    CLOUD_OVERLOADED_ERROR_CODE,
    "1102",
    "worker exceeded resource",
    "worker exceeded cpu",
    "exceeded resource limits",
    "service unavailable",
    "temporarily overloaded",
    "server overloaded",
    "too many requests",
    "rate limited",
    "bad gateway",
    "gateway timeout",
    "connection timed out",
)
_NETWORK_ERROR_TEXT_TOKENS = (
    "network_error",
    "timed out",
    "timeout",
    "temporary failure in name resolution",
    "nodename nor servname",
    "name or service not known",
    "dns",
    "connection refused",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "unreachable",
    "no route to host",
    "network is down",
    "connection was lost",
    "lost connection",
    "not connected to the internet",
    "internet connection appears to be offline",
    "cannot connect",
    "check your connection",
    "failed to establish a new connection",
    "remote end closed connection",
    "incomplete read",
)


class AuthApiError(RuntimeError):
    def __init__(self, status, error, payload=None):
        display = CLOUD_OVERLOADED_MESSAGE if str(error or "") == CLOUD_OVERLOADED_ERROR_CODE else str(error or f"http_{status}")
        super().__init__(display)
        self.status = int(status or 0)
        self.error = str(error or f"http_{status}")
        self.payload = payload if isinstance(payload, dict) else {}


_TERMINAL_AUTH_ERROR_CODES = {
    "missing_refresh_token",
    "invalid_refresh_token",
    "refresh_token_revoked",
    "refresh_token_expired",
    "session_not_connected",
    "session_blocked",
}


def _cloud_session_error_code(error):
    return str(getattr(error, "error", error) or "").strip().lower()


def is_terminal_cloud_session_error(error):
    code = _cloud_session_error_code(error)
    try:
        status = int(getattr(error, "status", 0) or 0)
    except (TypeError, ValueError):
        status = 0

    if code in _TERMINAL_AUTH_ERROR_CODES:
        return True
    if code.startswith("http_"):
        try:
            http_code = int(code.split("_", 1)[1] or 0)
        except (TypeError, ValueError, IndexError):
            http_code = 0
        if http_code in {401, 403}:
            return True
    if status == 401 and code not in {"network_error", "invalid_json_response"}:
        return True
    if status == 403 and code in _TERMINAL_AUTH_ERROR_CODES:
        return True
    return False


def _critical_disconnect_status_message(primary_error=None, secondary_error=None):
    if primary_error is not None:
        message = describe_cloud_session_error(primary_error)
        if message:
            return message
    if secondary_error is not None:
        message = describe_cloud_session_error(secondary_error)
        if message:
            return message
    return SESSION_EXPIRED_MESSAGE


def _report_critical_cloud_disconnect(prefs, source, primary_error=None, secondary_error=None):
    logger.error(
        "Planetka critical cloud session disconnect: source=%s primary_error=%s primary_status=%s "
        "secondary_error=%s secondary_status=%s device_id=%s",
        str(source or "").strip() or "unknown",
        _cloud_session_error_code(primary_error),
        int(getattr(primary_error, "status", 0) or 0) if primary_error is not None else 0,
        _cloud_session_error_code(secondary_error),
        int(getattr(secondary_error, "status", 0) or 0) if secondary_error is not None else 0,
        str(getattr(prefs, "cloud_install_id", "") or "").strip(),
    )


def describe_cloud_session_error(error):
    message = str(getattr(error, "error", error) or "session_failed")
    payload = getattr(error, "payload", {})
    payload_text = ""
    if isinstance(payload, dict):
        payload_text = " ".join(str(payload.get(key, "") or "") for key in ("error", "message", "detail"))
    if looks_like_planetka_overload(
        getattr(error, "status", 0),
        message,
        payload_text,
    ):
        return CLOUD_OVERLOADED_MESSAGE
    lowered = message.lower()
    if any(
        token in lowered
        for token in (
            "session_not_connected",
            "missing_refresh_token",
            "invalid_refresh_token",
            "refresh_token_revoked",
            "refresh_token_expired",
            "auth_failed",
        )
    ):
        return SESSION_EXPIRED_MESSAGE
    if "device_limit_exceeded" in lowered:
        return "This Planetka Cloud session is already active on the maximum number of computers."
    if "missing_device_id" in lowered:
        return "Planetka device identity is missing. Restart Blender and try again."
    if "session_blocked" in lowered or "blocked" in lowered:
        return "Planetka Cloud access is blocked. Contact info@planetka.io."
    if "1010" in lowered:
        return "Planetka connection was blocked by a security check. Please try again later or contact support."
    if "network_error" in lowered:
        return _CLOUD_CONNECTION_OFFLINE_MESSAGE
    if "missing_resolve_id" in lowered:
        return "Planetka request details are missing. Retry Resolve and ensure Planetka is up to date."
    return f"Planetka Cloud session failed: {message.replace('_', ' ')}."


def recover_from_terminal_cloud_session_error(error, prefs=None, source=""):
    """Clear stale local auth after backend-confirmed terminal auth failures.

    Network outages and Planetka Cloud overloads must not log the user out. This is
    only for definitive auth/session failures such as revoked or expired saved
    sessions.
    """
    if not is_terminal_cloud_session_error(error):
        return False
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    _report_critical_cloud_disconnect(
        prefs,
        str(source or "terminal_cloud_session_error").strip() or "terminal_cloud_session_error",
        primary_error=error,
    )
    _clear_cloud_session_preserve_install_id(
        prefs,
        state="logged_out",
        status_message=_critical_disconnect_status_message(error),
    )
    return True


def get_api_base_url():
    return DEFAULT_API_BASE_URL


def _coerce_status_code(status):
    try:
        return int(status or 0)
    except (TypeError, ValueError):
        return 0


def looks_like_planetka_overload(status=0, *details):
    status_code = _coerce_status_code(status)
    combined = " ".join(str(detail or "") for detail in details if detail is not None).strip().lower()
    if combined and any(token in combined for token in _SESSION_LIMIT_OR_ACCESS_TOKENS):
        return False
    if combined and any(token in combined for token in _OVERLOAD_TEXT_TOKENS):
        return True
    if combined and any(token in combined for token in _KNOWN_NON_OVERLOAD_ERROR_TOKENS):
        return False
    if status_code in _OVERLOAD_HTTP_STATUSES and not combined:
        return True
    return False


def looks_like_network_error(*details):
    combined_parts = []
    for detail in details:
        if detail is None:
            continue
        if isinstance(detail, urllib.error.URLError):
            return True
        combined_parts.append(str(detail))
        reason = getattr(detail, "reason", None)
        if reason is not None:
            combined_parts.append(str(reason))
    combined = " ".join(combined_parts).strip().lower()
    if not combined:
        return False
    return any(token in combined for token in _NETWORK_ERROR_TEXT_TOKENS)


def describe_network_error(stage="session"):
    if str(stage or "").strip().lower() == "download":
        return DOWNLOAD_INTERRUPTED_MESSAGE
    return NETWORK_UNAVAILABLE_MESSAGE


def mark_planetka_cloud_overloaded(prefs=None, reason=""):
    reason_text = str(reason or "").strip()
    if reason_text:
        logger.debug("Planetka Cloud overload detected: %s", reason_text[:300])
    _CLOUD_CONNECTION_CACHE["checked"] = True
    _CLOUD_CONNECTION_CACHE["timestamp"] = time.monotonic()
    _CLOUD_CONNECTION_CACHE["online"] = False
    _CLOUD_CONNECTION_CACHE["message"] = CLOUD_OVERLOADED_MESSAGE
    prefs = prefs or get_prefs()
    if prefs is not None and is_authenticated(prefs):
        _set_cloud_session_status_message(prefs, CLOUD_OVERLOADED_MESSAGE)
    _tag_ui_redraw()


def _is_cloud_offline_status_message(message):
    lowered = str(message or "").strip().lower()
    return bool(
        lowered.startswith(_CLOUD_CONNECTION_OFFLINE_MESSAGE.lower())
        or lowered.startswith(CLOUD_OVERLOADED_MESSAGE.lower())
        or "check your internet connection" in lowered
        or "could not connect right now" in lowered
    )


def _set_cloud_session_status_message(prefs, message):
    if prefs is None:
        return
    try:
        prefs.cloud_session_status_message = str(message or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing cloud session connection status", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed storing cloud session connection status", exc_info=True)


def mark_planetka_cloud_online(prefs=None):
    _CLOUD_CONNECTION_CACHE["checked"] = True
    _CLOUD_CONNECTION_CACHE["timestamp"] = time.monotonic()
    _CLOUD_CONNECTION_CACHE["online"] = True
    _CLOUD_CONNECTION_CACHE["message"] = ""
    prefs = prefs or get_prefs()
    if prefs is not None and _is_cloud_offline_status_message(get_status_message(prefs)):
        _set_cloud_session_status_message(prefs, "")
    _tag_ui_redraw()


def mark_planetka_cloud_offline(reason="", prefs=None):
    reason_text = str(reason or "").strip()
    message = _CLOUD_CONNECTION_OFFLINE_MESSAGE
    if reason_text:
        logger.debug("Planetka Cloud reachability check failed: %s", reason_text)
    _CLOUD_CONNECTION_CACHE["checked"] = True
    _CLOUD_CONNECTION_CACHE["timestamp"] = time.monotonic()
    _CLOUD_CONNECTION_CACHE["online"] = False
    _CLOUD_CONNECTION_CACHE["message"] = message
    prefs = prefs or get_prefs()
    if prefs is not None and is_authenticated(prefs):
        _set_cloud_session_status_message(prefs, message)
    _tag_ui_redraw()


def get_cached_cloud_connection_status():
    return {
        "online": bool(_CLOUD_CONNECTION_CACHE.get("online", False)),
        "message": str(_CLOUD_CONNECTION_CACHE.get("message", "") or ""),
        "checked": bool(_CLOUD_CONNECTION_CACHE.get("checked", False)),
    }


def _tag_ui_redraw():
    try:
        import bpy
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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed triggering cloud session UI redraw", exc_info=True)
        return
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed triggering cloud session UI redraw", exc_info=True)
        return


def _save_user_prefs():
    # Planetka must not write Blender's global user preferences automatically.
    return False


def clear_cloud_session(prefs=None, state="logged_out", status_message=""):
    del state
    prefs = prefs or get_prefs()
    if prefs is None:
        return

    prefs.cloud_session_access_token = ""
    prefs.cloud_session_refresh_token = ""
    prefs.cloud_session_edition = _normalize_addon_edition(read_local_addon_edition().get("edition", "free"))
    prefs.cloud_session_status_message = str(status_message or "")
    _save_user_prefs()
    _tag_ui_redraw()


def _clear_cloud_session_preserve_install_id(prefs=None, state="logged_out", status_message=""):
    prefs = prefs or get_prefs()
    if prefs is None:
        return
    device_id = str(getattr(prefs, "cloud_install_id", "") or "").strip()
    clear_cloud_session(prefs=prefs, state=state, status_message=status_message)
    if device_id:
        prefs.cloud_install_id = device_id
    _save_user_prefs()
    _tag_ui_redraw()



def is_authenticated(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    return bool(str(getattr(prefs, "cloud_session_access_token", "") or "").strip())


def get_status_message(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "cloud_session_status_message", "") or "").strip()


def _ensure_cloud_install_id(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    current = str(getattr(prefs, "cloud_install_id", "") or "").strip()
    if current:
        return current
    generated = str(uuid.uuid4())
    prefs.cloud_install_id = generated
    _save_user_prefs()
    return generated


def _build_device_name():
    try:
        machine = str(platform.node() or "").strip()
    except (RuntimeError, TypeError, ValueError):
        machine = ""
    try:
        system = str(platform.system() or "").strip()
    except (RuntimeError, TypeError, ValueError):
        system = ""
    safe = " ".join(part for part in (machine, system) if part)
    return safe[:80]


def _decode_jwt_payload(token):
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1].replace("-", "+").replace("_", "/")
    while len(payload) % 4 != 0:
        payload += "="
    try:
        decoded = base64.b64decode(payload.encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        logger.debug("Planetka: failed decoding JWT payload", exc_info=True)
        return {}


def _token_expires_soon(token, skew_seconds=120):
    payload = _decode_jwt_payload(token)
    try:
        exp = int(payload.get("exp", 0) or 0)
    except (TypeError, ValueError):
        return True
    if exp <= 0:
        return True
    return exp <= int(time.time()) + int(max(0, skew_seconds))


def _json_request(method, path, body=None, headers=None, timeout=30):
    url = f"{get_api_base_url()}{path}"
    request_headers = dict(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace") if raw else "{}"
            data = json.loads(text or "{}")
            mark_planetka_cloud_online()
            return int(getattr(response, "status", 200) or 200), data
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        text = raw.decode("utf-8", errors="replace") if raw else "{}"
        try:
            data = json.loads(text or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {"error": text or f"http_{exc.code}"}
        error_text = " ".join(str(data.get(key, "") or "") for key in ("error", "message", "detail"))
        if looks_like_planetka_overload(exc.code, error_text, text):
            mark_planetka_cloud_overloaded(reason=text or error_text or f"http_{exc.code}")
            raise AuthApiError(
                exc.code,
                CLOUD_OVERLOADED_ERROR_CODE,
                payload={"error": CLOUD_OVERLOADED_ERROR_CODE, "message": CLOUD_OVERLOADED_MESSAGE},
            ) from exc
        mark_planetka_cloud_online()
        raise AuthApiError(exc.code, data.get("error") or f"http_{exc.code}", payload=data) from exc
    except urllib.error.URLError as exc:
        mark_planetka_cloud_offline(str(getattr(exc, "reason", exc) or exc))
        raise AuthApiError(0, f"network_error_{exc.reason}") from exc
    except OSError as exc:
        if looks_like_network_error(exc):
            mark_planetka_cloud_offline(str(exc))
            raise AuthApiError(0, "network_error", payload={"message": NETWORK_UNAVAILABLE_MESSAGE}) from exc
        raise
    except ValueError as exc:
        mark_planetka_cloud_online()
        raise AuthApiError(0, "invalid_json_response") from exc


def _read_local_addon_version():
    global _ADDON_VERSION_CACHE
    cached = _ADDON_VERSION_CACHE
    if isinstance(cached, str):
        return cached
    version_text = ""
    if tomllib is not None:
        try:
            manifest_path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
            with open(manifest_path, "rb") as handle:
                payload = tomllib.load(handle)
            version_text = str((payload or {}).get("version", "") or "").strip()
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
            version_text = ""
    _ADDON_VERSION_CACHE = version_text
    return version_text


def _normalize_addon_edition(value):
    normalized = str(value or "").strip().lower()
    if normalized == "private":
        return "pro"
    if normalized in {"hobby", "pro", "studio"}:
        return normalized
    return "free"


def addon_edition_label(value=None):
    if value is None:
        local_label = str(read_local_addon_edition().get("label", "") or "").strip()
        if local_label:
            return local_label
    edition = _normalize_addon_edition(value if value is not None else read_local_addon_edition().get("edition", "free"))
    if edition == "hobby":
        return "Hobby"
    if edition == "pro":
        return "Pro"
    if edition == "studio":
        return "Studio"
    return "Free"


def read_local_addon_edition():
    global _ADDON_EDITION_CACHE
    cached = _ADDON_EDITION_CACHE
    if isinstance(cached, dict):
        return dict(cached)
    payload = {
        "edition": "free",
        "label": "Free",
        "signature": "",
        "signature_version": 1,
    }
    try:
        marker_path = os.path.join(os.path.dirname(__file__), "Resources", "planetka_edition.json")
        with open(marker_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle) or {}
        payload["edition"] = _normalize_addon_edition(raw.get("edition", "free"))
        payload["label"] = addon_edition_label(payload["edition"])
        payload["signature"] = str(raw.get("signature", "") or "").strip()
        try:
            payload["signature_version"] = int(raw.get("signature_version", 1) or 1)
        except (TypeError, ValueError):
            payload["signature_version"] = 1
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        payload["edition"] = "free"
        payload["label"] = "Free"
    _ADDON_EDITION_CACHE = dict(payload)
    return dict(payload)


def _store_session_edition(prefs, payload):
    edition = _normalize_addon_edition(
        payload.get("install_edition")
        or payload.get("edition")
        or payload.get("access_tier")
        or read_local_addon_edition().get("edition", "free")
    )
    try:
        prefs.cloud_session_edition = edition
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    return edition


def get_session_edition(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is not None:
        stored_raw = str(getattr(prefs, "cloud_session_edition", "") or "").strip()
        if stored_raw:
            return _normalize_addon_edition(stored_raw)
    return _normalize_addon_edition(read_local_addon_edition().get("edition", "free"))


def local_addon_edition_code():
    return _normalize_addon_edition(read_local_addon_edition().get("edition", "free"))


def session_edition_matches_package(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return True
    return get_session_edition(prefs) == local_addon_edition_code()



def _apply_auth_payload(prefs, payload, status_message=""):
    prefs.cloud_session_access_token = str(payload.get("access_token", "") or "").strip()
    prefs.cloud_session_refresh_token = str(payload.get("refresh_token", "") or "").strip()
    _store_session_edition(prefs, payload if isinstance(payload, dict) else {})
    prefs.cloud_session_status_message = str(status_message or "")
    _save_user_prefs()
    _tag_ui_redraw()


def connect_anonymous(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    device_id = _ensure_cloud_install_id(prefs)
    headers = {}
    if device_id:
        headers["X-Planetka-Device-Id"] = device_id
    edition = read_local_addon_edition()
    _status, payload = _json_request(
        "POST",
        "/auth/anonymous",
        {
            "device_id": device_id,
            "device_name": _build_device_name(),
            "addon_version": _read_local_addon_version(),
            "install_edition": edition.get("edition", "free"),
            "edition_signature": edition.get("signature", ""),
            "edition_signature_version": edition.get("signature_version", 1),
        },
        headers=headers,
        timeout=15,
    )
    _apply_auth_payload(prefs, payload)
    return payload


def ensure_authenticated_session(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if is_authenticated(prefs):
        if not session_edition_matches_package(prefs):
            refresh_cloud_session(prefs)
        return True
    connect_anonymous(prefs)
    return True


def refresh_cloud_session(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    refresh_token = str(getattr(prefs, "cloud_session_refresh_token", "") or "").strip()
    if not refresh_token:
        connect_anonymous(prefs)
        return str(getattr(prefs, "cloud_session_access_token", "") or "").strip()

    _status = None
    payload = None
    try:
        device_id = _ensure_cloud_install_id(prefs)
        headers = {}
        if device_id:
            headers["X-Planetka-Device-Id"] = device_id
        edition = read_local_addon_edition()
        _status, payload = _json_request(
            "POST",
            "/auth/refresh",
            {
                "refresh_token": refresh_token,
                "device_id": device_id,
                "install_edition": edition.get("edition", "free"),
                "edition_signature": edition.get("signature", ""),
                "edition_signature_version": edition.get("signature_version", 1),
            },
            headers=headers,
        )
    except AuthApiError as refresh_error:
        try:
            connect_anonymous(prefs)
            return str(getattr(prefs, "cloud_session_access_token", "") or "").strip()
        except AuthApiError:
            if is_terminal_cloud_session_error(refresh_error):
                _report_critical_cloud_disconnect(
                    prefs,
                    "refresh_cloud_session_refresh_failed",
                    primary_error=refresh_error,
                )
                _clear_cloud_session_preserve_install_id(
                    prefs,
                    state="logged_out",
                    status_message=_critical_disconnect_status_message(refresh_error),
                )
            else:
                logger.warning(
                    "Planetka: transient session refresh failure; preserving local session "
                    "(refresh_error=%s refresh_status=%s).",
                    _cloud_session_error_code(refresh_error),
                    int(getattr(refresh_error, "status", 0) or 0),
                )
            raise refresh_error

    _apply_auth_payload(prefs, payload)
    return str(getattr(prefs, "cloud_session_access_token", "") or "").strip()


def get_access_token(prefs=None, allow_refresh=True):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""

    access_token = str(getattr(prefs, "cloud_session_access_token", "") or "").strip()
    if access_token and not _token_expires_soon(access_token):
        return access_token
    if access_token and not allow_refresh:
        return access_token
    if not str(getattr(prefs, "cloud_session_refresh_token", "") or "").strip():
        connect_anonymous(prefs)
        return str(getattr(prefs, "cloud_session_access_token", "") or "").strip()
    return refresh_cloud_session(prefs)


def _cache_authorized_headers(headers):
    safe_headers = dict(headers or {})
    if not str(safe_headers.get("Authorization", "") or "").strip():
        return
    with _AUTHORIZED_HEADERS_CACHE_LOCK:
        _AUTHORIZED_HEADERS_CACHE.clear()
        _AUTHORIZED_HEADERS_CACHE.update(safe_headers)


def _cached_authorized_headers():
    with _AUTHORIZED_HEADERS_CACHE_LOCK:
        headers = dict(_AUTHORIZED_HEADERS_CACHE)
    token_header = str(headers.get("Authorization", "") or "").strip()
    token = token_header.split(" ", 1)[1].strip() if token_header.lower().startswith("bearer ") else ""
    if not token or _token_expires_soon(token):
        return {}
    return headers


def get_authorized_headers(prefs=None, allow_refresh=True):
    if prefs is None and threading.current_thread() is not threading.main_thread():
        cached_headers = _cached_authorized_headers()
        if cached_headers:
            return cached_headers
        raise AuthApiError(401, "cloud_session_snapshot_unavailable")

    prefs = prefs or get_prefs()
    token = get_access_token(prefs=prefs, allow_refresh=allow_refresh)
    if not token:
        raise AuthApiError(401, "session_not_connected")
    headers = {"Authorization": f"Bearer {token}"}
    device_id = _ensure_cloud_install_id(prefs)
    if device_id:
        headers["X-Planetka-Device-Id"] = device_id
    addon_version = _read_local_addon_version()
    if addon_version:
        headers["X-Planetka-Addon-Version"] = addon_version
    _cache_authorized_headers(headers)
    return headers
