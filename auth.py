import base64
import json
import logging
import os
import platform
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
DEFAULT_UPGRADE_URL = str(
    os.getenv("PLANETKA_UPGRADE_URL")
    or "https://www.planetka.io/blender/upgrade"
).strip()
DEFAULT_CONTACT_URL = str(
    os.getenv("PLANETKA_CONTACT_URL")
    or os.getenv("PLANETKA_SUPPORT_URL")
    or "mailto:info@planetka.io?subject=Planetka%20support%20request"
).strip()
DEFAULT_API_KEY_REQUEST_URL = str(
    os.getenv("PLANETKA_API_KEY_REQUEST_URL")
    or f"{DEFAULT_API_BASE_URL}/api-key"
).strip()


TIER_INTEGRITY_ERROR_CODE = "tier_integrity_violation"
TIER_INTEGRITY_STATUS_MESSAGE = (
    "Critical account tier integrity error detected. "
    "Planetka is locked until resolved. Contact info@planetka.io."
)
CLOUD_OVERLOADED_ERROR_CODE = "planetka_cloud_overloaded"
CLOUD_OVERLOADED_MESSAGE = "Planetka servers are temporarily overloaded. Please wait a few moments and try again."
SESSION_EXPIRED_MESSAGE = "Planetka session expired. Connect your account again."
_ADDON_VERSION_CACHE = None
_CLOUD_CONNECTION_CACHE = {
    "checked": False,
    "timestamp": 0.0,
    "online": True,
    "message": "",
}
_CLOUD_CONNECTION_TTL_SECONDS = 5.0
_CLOUD_CONNECTION_OFFLINE_MESSAGE = "Planetka Cloud is not reachable. Check your internet connection or try again later."
_OVERLOAD_HTTP_STATUSES = {429, 503, 520, 522, 524, 529}
_ACCOUNT_LIMIT_OR_ACCESS_TOKENS = (
    "request limit reached",
    "request limit reached for this account",
    "planetka request limit reached for this account",
    "rate_limit_auth",
    "device_limit_exceeded",
    "account_blocked",
    "access_denied",
    "not_allowed_for_tier",
    "quality_mode_not_allowed",
)
_KNOWN_NON_OVERLOAD_ERROR_TOKENS = (
    "full quality requires a pro",
)
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


class AuthApiError(RuntimeError):
    def __init__(self, status, error, payload=None):
        display = CLOUD_OVERLOADED_MESSAGE if str(error or "") == CLOUD_OVERLOADED_ERROR_CODE else str(error or f"http_{status}")
        super().__init__(display)
        self.status = int(status or 0)
        self.error = str(error or f"http_{status}")
        self.payload = payload if isinstance(payload, dict) else {}


_TERMINAL_AUTH_ERROR_CODES = {
    "invalid_api_key",
    "api_key_expired",
    "api_key_revoked",
    "missing_api_key",
    "missing_refresh_token",
    "invalid_refresh_token",
    "refresh_token_revoked",
    "refresh_token_expired",
    "account_not_connected",
    "account_blocked",
    "invalid_user_status",
}


def _auth_error_code(error):
    return str(getattr(error, "error", error) or "").strip().lower()


def is_terminal_auth_error(error):
    code = _auth_error_code(error)
    try:
        status = int(getattr(error, "status", 0) or 0)
    except (TypeError, ValueError):
        status = 0

    if TIER_INTEGRITY_ERROR_CODE in code:
        return True
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
        message = describe_auth_error(primary_error)
        if message:
            return message
    if secondary_error is not None:
        message = describe_auth_error(secondary_error)
        if message:
            return message
    return SESSION_EXPIRED_MESSAGE


def _report_critical_disconnect(prefs, source, primary_error=None, secondary_error=None):
    logger.error(
        "Planetka critical auth disconnect: source=%s primary_error=%s primary_status=%s "
        "secondary_error=%s secondary_status=%s email=%s device_id=%s",
        str(source or "").strip() or "unknown",
        _auth_error_code(primary_error),
        int(getattr(primary_error, "status", 0) or 0) if primary_error is not None else 0,
        _auth_error_code(secondary_error),
        int(getattr(secondary_error, "status", 0) or 0) if secondary_error is not None else 0,
        str(getattr(prefs, "auth_email", "") or "").strip().lower(),
        str(getattr(prefs, "auth_device_id", "") or "").strip(),
    )


def describe_auth_error(error):
    message = str(getattr(error, "error", error) or "login_failed")
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
    if TIER_INTEGRITY_ERROR_CODE in lowered:
        return (
            "Planetka could not verify this account safely. "
            "Reconnect and contact info@planetka.io if the problem persists."
        )
    if "invalid_api_key" in lowered:
        return "Invalid Planetka access key."
    if "api_key_expired" in lowered:
        return "Planetka access key expired. Request a new key."
    if "api_key_revoked" in lowered:
        return "Planetka access key is no longer valid. Request a new key."
    if any(
        token in lowered
        for token in (
            "account_not_connected",
            "missing_refresh_token",
            "invalid_refresh_token",
            "refresh_token_revoked",
            "refresh_token_expired",
            "auth_failed",
        )
    ):
        return SESSION_EXPIRED_MESSAGE
    if "device_limit_exceeded" in lowered:
        return "This Planetka account is already active on the maximum number of computers."
    if "missing_device_id" in lowered:
        return "Planetka device identity is missing. Restart Blender and try again."
    if "account_blocked" in lowered or "account is blocked" in lowered:
        return "Planetka account is blocked. Contact info@planetka.io."
    if "1010" in lowered:
        return "Planetka connection was blocked by a security check. Please try again later or contact support."
    if "network_error" in lowered:
        return _CLOUD_CONNECTION_OFFLINE_MESSAGE
    if "quality_mode_not_allowed" in lowered or "not_allowed_for_tier" in lowered or "insufficient_data" in lowered:
        return "Planetka Cloud could not stream the selected texture quality. Please retry."
    if "lemonsqueezy" in lowered or "checkout" in lowered:
        return "Planetka checkout is temporarily unavailable. Please try again shortly."
    if "missing_resolve_id" in lowered:
        return "Purchase details are missing. Retry Resolve and ensure Planetka is up to date."
    return f"Planetka login failed: {message.replace('_', ' ')}."


def recover_from_terminal_auth_error(error, prefs=None, source=""):
    """Clear stale local auth after backend-confirmed terminal auth failures.

    Network outages and Cloudflare overloads must not log the user out. This is
    only for definitive auth/session failures such as revoked or expired saved
    sessions.
    """
    if not is_terminal_auth_error(error):
        return False
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    _report_critical_disconnect(
        prefs,
        str(source or "terminal_auth_error").strip() or "terminal_auth_error",
        primary_error=error,
    )
    _clear_auth_session_preserve_api_key(
        prefs,
        state="logged_out",
        status_message=_critical_disconnect_status_message(error),
    )
    return True


def _first_non_empty(*values):
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


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
    if combined and any(token in combined for token in _ACCOUNT_LIMIT_OR_ACCESS_TOKENS):
        return False
    if combined and any(token in combined for token in _OVERLOAD_TEXT_TOKENS):
        return True
    if combined and any(token in combined for token in _KNOWN_NON_OVERLOAD_ERROR_TOKENS):
        return False
    if status_code in _OVERLOAD_HTTP_STATUSES and not combined:
        return True
    return False


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
        _set_auth_status_message(prefs, CLOUD_OVERLOADED_MESSAGE)
    _tag_ui_redraw()


def _is_cloud_offline_status_message(message):
    lowered = str(message or "").strip().lower()
    return bool(
        lowered.startswith(_CLOUD_CONNECTION_OFFLINE_MESSAGE.lower())
        or lowered.startswith(CLOUD_OVERLOADED_MESSAGE.lower())
        or "check your internet connection" in lowered
        or "could not connect right now" in lowered
    )


def _set_auth_status_message(prefs, message):
    if prefs is None:
        return
    try:
        prefs.auth_status_message = str(message or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing auth connection status", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed storing auth connection status", exc_info=True)


def mark_planetka_cloud_online(prefs=None):
    _CLOUD_CONNECTION_CACHE["checked"] = True
    _CLOUD_CONNECTION_CACHE["timestamp"] = time.monotonic()
    _CLOUD_CONNECTION_CACHE["online"] = True
    _CLOUD_CONNECTION_CACHE["message"] = ""
    prefs = prefs or get_prefs()
    if prefs is not None and _is_cloud_offline_status_message(get_status_message(prefs)):
        _set_auth_status_message(prefs, "")
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
        _set_auth_status_message(prefs, message)
    _tag_ui_redraw()


def _mark_planetka_cloud_http_unavailable(status, detail="", prefs=None):
    status_code = _coerce_status_code(status)
    detail_text = str(detail or "").strip()
    if looks_like_planetka_overload(status_code, detail_text):
        mark_planetka_cloud_overloaded(prefs=prefs, reason=detail_text or f"http_{status_code}")
        return CLOUD_OVERLOADED_MESSAGE
    message = f"Planetka Cloud is unavailable right now (HTTP {status_code})."
    _CLOUD_CONNECTION_CACHE["checked"] = True
    _CLOUD_CONNECTION_CACHE["timestamp"] = time.monotonic()
    _CLOUD_CONNECTION_CACHE["online"] = False
    _CLOUD_CONNECTION_CACHE["message"] = message
    if prefs is not None and is_authenticated(prefs):
        _set_auth_status_message(prefs, message)
    _tag_ui_redraw()
    return message


def get_cloud_connection_status(prefs=None, force=False, timeout=2.0):
    prefs = prefs or get_prefs()
    now = time.monotonic()
    if (
        not bool(force)
        and bool(_CLOUD_CONNECTION_CACHE.get("checked", False))
        and (now - float(_CLOUD_CONNECTION_CACHE.get("timestamp", 0.0) or 0.0)) < _CLOUD_CONNECTION_TTL_SECONDS
    ):
        return {
            "online": bool(_CLOUD_CONNECTION_CACHE.get("online", False)),
            "message": str(_CLOUD_CONNECTION_CACHE.get("message", "") or ""),
            "checked": True,
        }

    url = f"{get_api_base_url().rstrip('/')}/health"
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "Planetka-Blender"})
    try:
        with urllib.request.urlopen(request, timeout=max(0.5, float(timeout or 2.0))) as response:
            status = int(getattr(response, "status", 200) or 200)
            # Read a tiny response body so connection failures surface while
            # keeping the check cheap for UI redraws.
            raw = response.read(256)
            detail = raw.decode("utf-8", errors="replace") if raw else ""
        if 200 <= status < 500:
            mark_planetka_cloud_online(prefs)
            return {"online": True, "message": "", "checked": True}
        message = _mark_planetka_cloud_http_unavailable(status, detail, prefs=prefs)
        return {"online": False, "message": message, "checked": True}
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        try:
            raw = exc.read(512)
        except (RuntimeError, ValueError, OSError):
            raw = b""
        detail = raw.decode("utf-8", errors="replace") if raw else ""
        if 200 <= status < 500:
            mark_planetka_cloud_online(prefs)
            return {"online": True, "message": "", "checked": True}
        message = _mark_planetka_cloud_http_unavailable(status, detail, prefs=prefs)
        return {"online": False, "message": message, "checked": True}
    except urllib.error.URLError as exc:
        mark_planetka_cloud_offline(str(getattr(exc, "reason", exc) or exc), prefs=prefs)
    except (TimeoutError, OSError, RuntimeError, TypeError, ValueError) as exc:
        mark_planetka_cloud_offline(str(exc), prefs=prefs)
    return {
        "online": False,
        "message": str(_CLOUD_CONNECTION_CACHE.get("message", "") or _CLOUD_CONNECTION_OFFLINE_MESSAGE),
        "checked": True,
    }


def get_cached_cloud_connection_status():
    return {
        "online": bool(_CLOUD_CONNECTION_CACHE.get("online", False)),
        "message": str(_CLOUD_CONNECTION_CACHE.get("message", "") or ""),
        "checked": bool(_CLOUD_CONNECTION_CACHE.get("checked", False)),
    }


def is_planetka_cloud_online(prefs=None, force=False, timeout=2.0):
    return bool(get_cloud_connection_status(prefs=prefs, force=force, timeout=timeout).get("online", False))


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
        logger.debug("Planetka: failed triggering auth UI redraw", exc_info=True)
        return
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed triggering auth UI redraw", exc_info=True)
        return


def _save_user_prefs():
    # Planetka must not write Blender's global user preferences automatically.
    return False


def clear_auth_session(prefs=None, state="logged_out", status_message=""):
    prefs = prefs or get_prefs()
    if prefs is None:
        return

    prefs.auth_email = ""
    prefs.auth_api_key = ""
    prefs.auth_api_key_mask = ""
    prefs.auth_api_key_input = ""
    prefs.auth_access_token = ""
    prefs.auth_refresh_token = ""
    prefs.auth_account_tier = ""
    prefs.auth_stored_account_tier = ""
    prefs.auth_plan_code = ""
    prefs.auth_plan_name = ""
    prefs.auth_stored_plan_code = ""
    prefs.auth_stored_plan_name = ""
    prefs.auth_contact_url = ""
    prefs.auth_upgrade_url = ""
    prefs.scene_licence_price_label = ""
    prefs.scene_licence_price_cents = 0
    prefs.auth_login_state = str(state or "logged_out")
    prefs.auth_status_message = str(status_message or "")
    _save_user_prefs()
    _tag_ui_redraw()


def _clear_auth_session_preserve_api_key(prefs=None, state="logged_out", status_message=""):
    prefs = prefs or get_prefs()
    if prefs is None:
        return
    api_key = str(getattr(prefs, "auth_api_key", "") or "").strip()
    api_key_input = str(getattr(prefs, "auth_api_key_input", "") or "").strip()
    api_key_mask = str(getattr(prefs, "auth_api_key_mask", "") or "").strip()
    device_id = str(getattr(prefs, "auth_device_id", "") or "").strip()
    clear_auth_session(prefs=prefs, state=state, status_message=status_message)
    if api_key:
        prefs.auth_api_key = api_key
    if api_key_input:
        prefs.auth_api_key_input = api_key_input
    if api_key_mask:
        prefs.auth_api_key_mask = api_key_mask
    if device_id:
        prefs.auth_device_id = device_id
    _save_user_prefs()
    _tag_ui_redraw()


def is_authenticated(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    return bool(str(getattr(prefs, "auth_access_token", "") or "").strip())


def get_login_state(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return "logged_out"
    if is_authenticated(prefs):
        return "authenticated"
    state = str(getattr(prefs, "auth_login_state", "") or "").strip().lower()
    return state or "logged_out"


def get_status_message(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_status_message", "") or "").strip()


def get_connected_email(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_email", "") or "").strip()


def get_api_key_request_url():
    return DEFAULT_API_KEY_REQUEST_URL


def get_api_key_mask(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_api_key_mask", "") or "").strip()


def _raise_tier_integrity_violation(prefs, reason, details=None):
    payload = {"reason": str(reason or "tier_integrity_violation").strip() or "tier_integrity_violation"}
    if isinstance(details, dict):
        payload.update(details)
    logger.error("Planetka: account tier integrity violation: %s", payload)
    try:
        _clear_auth_session_preserve_api_key(
            prefs=prefs,
            state="tier_integrity_error",
            status_message=TIER_INTEGRITY_STATUS_MESSAGE,
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed preserving API key while handling tier integrity violation", exc_info=True)
        clear_auth_session(
            prefs=prefs,
            state="tier_integrity_error",
            status_message=TIER_INTEGRITY_STATUS_MESSAGE,
        )
    raise AuthApiError(500, TIER_INTEGRITY_ERROR_CODE, payload=payload)


def _require_valid_authenticated_tier(prefs=None, context="runtime"):
    del prefs, context
    return ""


def _normalize_account_plan_code(value):
    token = str(value or "").strip().lower()
    if token in {"professional", "pro", "paid", "unlimited"}:
        return "pro"
    if token in {"personal", "free", ""}:
        return "free"
    return token


def _account_plan_name(plan_code):
    normalized = _normalize_account_plan_code(plan_code)
    if normalized == "pro":
        return "Pro"
    return "Free"


def _first_plan_code_from_payload(payload, *keys):
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _first_non_empty(value.get("code"), value.get("plan_code"), value.get("id"))
            if nested:
                return nested
        else:
            value = _first_non_empty(value)
            if value:
                return value
    return ""


def _apply_account_plan_fields(prefs, payload):
    if prefs is None or not isinstance(payload, dict):
        return
    plan_code = _normalize_account_plan_code(
        _first_plan_code_from_payload(payload, "plan_code", "plan", "user_status", "account_tier")
    )
    stored_plan_code = _normalize_account_plan_code(
        _first_plan_code_from_payload(payload, "stored_plan_code", "storedPlanCode", "stored_account_tier")
        or plan_code
    )
    account_tier = _normalize_account_plan_code(
        _first_plan_code_from_payload(payload, "account_tier", "accountTier")
        or plan_code
    )
    prefs.auth_plan_code = plan_code
    prefs.auth_plan_name = _account_plan_name(plan_code)
    prefs.auth_stored_plan_code = stored_plan_code
    prefs.auth_stored_plan_name = _account_plan_name(stored_plan_code)
    prefs.auth_stored_account_tier = stored_plan_code
    prefs.auth_account_tier = account_tier


def get_account_tier(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return _normalize_account_plan_code(
        getattr(prefs, "auth_account_tier", "")
        or getattr(prefs, "auth_plan_code", "")
        or getattr(prefs, "auth_stored_plan_code", "")
    )


def get_account_plan_name(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_plan_name", "") or _account_plan_name(get_account_tier(prefs))).strip()


def is_professional_account(prefs=None):
    return get_account_tier(prefs) == "pro"


def is_pro_account(prefs=None):
    return is_professional_account(prefs)


def account_access_summary(prefs=None):
    tier = get_account_tier(prefs)
    if tier == "pro":
        return "Pro account: Preview, Balanced, and Full texture quality with commercial licence."
    return "Free account: Preview and Balanced texture quality for personal use."


def professional_account_required_message():
    return "This feature requires Pro."


def _normalize_texture_quality_token(value):
    token = str(value or "").strip().upper()
    if token in {"PREVIEW", "BALANCED", "FULL"}:
        return token
    return "PREVIEW"


def allows_texture_quality_for_context(prefs=None, requested_mode=None):
    mode = _normalize_texture_quality_token(requested_mode or "PREVIEW")
    tier = get_account_tier(prefs)
    if tier == "pro":
        return True
    return mode in {"PREVIEW", "BALANCED", "FULL"}


def texture_quality_not_allowed_message(prefs=None, requested_mode=None):
    mode = _normalize_texture_quality_token(requested_mode or "PREVIEW")
    if mode == "FULL":
        return "Full Quality requires a scene licence."
    return "Selected texture quality is not available for this account."


def allows_full_quality_for_context(prefs=None, source=None):
    del source
    return allows_texture_quality_for_context(prefs, "FULL")


def allows_animation_render_for_context(prefs=None, source=None, requested_mode=None):
    del source, requested_mode
    return True


def get_upgrade_url(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return DEFAULT_UPGRADE_URL
    value = str(getattr(prefs, "auth_upgrade_url", "") or "").strip()
    return value or DEFAULT_UPGRADE_URL


def get_contact_url(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return DEFAULT_CONTACT_URL
    value = str(getattr(prefs, "auth_contact_url", "") or "").strip()
    return value or DEFAULT_CONTACT_URL
def _mask_api_key(value):
    token = str(value or "").strip()
    if not token:
        return ""
    if len(token) <= 12:
        return f"{token[:4]}***"
    return f"{token[:8]}...{token[-4:]}"


def _ensure_device_id(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    current = str(getattr(prefs, "auth_device_id", "") or "").strip()
    if current:
        return current
    generated = str(uuid.uuid4())
    prefs.auth_device_id = generated
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


def connect_with_api_key(api_key, prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    token = str(api_key or "").strip()
    if not token:
        raise AuthApiError(400, "invalid_api_key")

    device_id = _ensure_device_id(prefs)
    payload = {
        "api_key": token,
        "device_id": device_id,
        "device_name": _build_device_name(),
    }
    _status, response = _json_request("POST", "/auth/api-key/exchange", payload)
    _apply_auth_payload(prefs, response, login_state="authenticated")
    prefs.auth_api_key = token
    prefs.auth_api_key_input = token
    prefs.auth_api_key_mask = _mask_api_key(token)
    _save_user_prefs()
    _tag_ui_redraw()
    return response


def connect_anonymous(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    device_id = _ensure_device_id(prefs)
    payload = {
        "device_id": device_id,
        "device_name": _build_device_name(),
        "addon_version": _read_local_addon_version(),
    }
    headers = {}
    if device_id:
        headers["X-Planetka-Device-Id"] = device_id
    _status, response = _json_request("POST", "/auth/anonymous", payload, headers=headers, timeout=15)
    _apply_auth_payload(prefs, response, login_state="authenticated")
    prefs.auth_api_key = ""
    prefs.auth_api_key_input = ""
    prefs.auth_api_key_mask = ""
    _save_user_prefs()
    _tag_ui_redraw()
    return response


def ensure_authenticated_session(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if is_authenticated(prefs):
        return True
    connect_anonymous(prefs)
    return True


def _reauth_with_api_key(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    api_key = str(getattr(prefs, "auth_api_key", "") or "").strip()
    if not api_key:
        raise AuthApiError(401, "missing_api_key")
    return connect_with_api_key(api_key, prefs=prefs)


def connect_with_prefs_api_key(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    entered = str(getattr(prefs, "auth_api_key_input", "") or "").strip()
    if not entered:
        entered = str(getattr(prefs, "auth_api_key", "") or "").strip()
    if not entered:
        raise AuthApiError(400, "invalid_api_key")
    return connect_with_api_key(entered, prefs=prefs)


def _apply_auth_payload(prefs, payload, login_state="authenticated", status_message=""):
    prefs.auth_email = str(payload.get("email", "") or "").strip()
    prefs.auth_access_token = str(payload.get("access_token", "") or "").strip()
    prefs.auth_refresh_token = str(payload.get("refresh_token", "") or "").strip()
    api_key_mask = str(payload.get("api_key_mask", "") or "").strip()
    if api_key_mask:
        prefs.auth_api_key_mask = api_key_mask
    _apply_account_plan_fields(prefs, payload)
    prefs.auth_contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
    )
    prefs.auth_upgrade_url = _first_non_empty(payload.get("upgrade_url"))
    price_label = str(payload.get("scene_licence_price_label", "") or "").strip()
    if price_label:
        prefs.scene_licence_price_label = price_label
    try:
        prefs.scene_licence_price_cents = max(0, int(payload.get("scene_licence_price_cents", 0) or 0))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        prefs.scene_licence_price_cents = 0
    prefs.auth_login_state = str(login_state or "authenticated")
    prefs.auth_status_message = str(status_message or "")
    _require_valid_authenticated_tier(prefs, context="auth_payload")
    _save_user_prefs()
    _tag_ui_redraw()


def _apply_account_profile_fields(prefs, payload):
    if not isinstance(payload, dict):
        return
    email = str(payload.get("email", "") or "").strip()
    if email:
        prefs.auth_email = email

    _apply_account_plan_fields(prefs, payload)

    contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
    )
    if contact_url:
        prefs.auth_contact_url = contact_url

    upgrade_url = _first_non_empty(payload.get("upgrade_url"))
    if upgrade_url:
        prefs.auth_upgrade_url = upgrade_url
    price_label = str(payload.get("scene_licence_price_label", "") or "").strip()
    if price_label:
        prefs.scene_licence_price_label = price_label
    try:
        prefs.scene_licence_price_cents = max(0, int(payload.get("scene_licence_price_cents", 0) or 0))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        prefs.scene_licence_price_cents = 0
    _require_valid_authenticated_tier(prefs, context="account_profile")


def sync_account_profile(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)

    try:
        headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
        _status, payload = _json_request("GET", "/me", None, headers=headers)
    except AuthApiError as exc:
        recover_from_terminal_auth_error(exc, prefs=prefs, source="sync_account_profile")
        raise
    _apply_account_profile_fields(prefs, payload)
    _save_user_prefs()
    _tag_ui_redraw()
    return True


def create_pro_upgrade_checkout(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, payload = _json_request("POST", "/billing/lemonsqueezy/checkout", {}, headers=headers, timeout=30)
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise AuthApiError(_status or 0, payload.get("error") if isinstance(payload, dict) else "checkout_create_failed", payload=payload)
    if payload.get("already_pro"):
        _apply_account_profile_fields(prefs, payload)
        _save_user_prefs()
        _tag_ui_redraw()
        return {"already_pro": True, "checkout_url": ""}
    checkout_url = str(payload.get("checkout_url", "") or "").strip()
    if not checkout_url:
        raise AuthApiError(_status or 0, "checkout_url_missing", payload=payload)
    return payload


def create_scene_full_quality_checkout(scene_payload, prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    payload = dict(scene_payload or {})
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, response = _json_request(
        "POST",
        "/billing/lemonsqueezy/scene-checkout",
        payload,
        headers=headers,
        timeout=30,
    )
    if not isinstance(response, dict) or not response.get("ok"):
        raise AuthApiError(_status or 0, response.get("error") if isinstance(response, dict) else "scene_checkout_failed", payload=response)
    return response


def check_scene_full_quality_purchase(scene_id, prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    safe_scene_id = str(scene_id or "").strip()
    if not safe_scene_id:
        raise AuthApiError(400, "missing_scene_id")
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    path = "/billing/scene-purchases/check?scene_id=" + urllib.parse.quote(safe_scene_id, safe="")
    _status, response = _json_request("GET", path, {}, headers=headers, timeout=15)
    if not isinstance(response, dict) or not response.get("ok"):
        raise AuthApiError(_status or 0, response.get("error") if isinstance(response, dict) else "scene_purchase_check_failed", payload=response)
    return response


def create_animation_render_checkout(animation_payload, prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    payload = dict(animation_payload or {})
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, response = _json_request(
        "POST",
        "/billing/lemonsqueezy/animation-checkout",
        payload,
        headers=headers,
        timeout=30,
    )
    if not isinstance(response, dict) or not response.get("ok"):
        raise AuthApiError(_status or 0, response.get("error") if isinstance(response, dict) else "animation_checkout_failed", payload=response)
    return response


def check_animation_render_purchase(animation_id, prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    safe_animation_id = str(animation_id or "").strip()
    if not safe_animation_id:
        raise AuthApiError(400, "missing_animation_id")
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    path = "/billing/animation-purchases/check?animation_id=" + urllib.parse.quote(safe_animation_id, safe="")
    _status, response = _json_request("GET", path, {}, headers=headers, timeout=15)
    if not isinstance(response, dict) or not response.get("ok"):
        raise AuthApiError(_status or 0, response.get("error") if isinstance(response, dict) else "animation_purchase_check_failed", payload=response)
    return response


def list_scene_full_quality_purchases(prefs=None, limit=50):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    safe_limit = max(1, min(200, int(limit or 50)))
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, response = _json_request("GET", f"/billing/scene-purchases/list?limit={safe_limit}", {}, headers=headers, timeout=20)
    if not isinstance(response, dict) or not response.get("ok"):
        raise AuthApiError(_status or 0, response.get("error") if isinstance(response, dict) else "scene_purchases_failed", payload=response)
    return list(response.get("purchases", []) or [])


def request_scene_licence_restore_link(email, prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    safe_email = str(email or "").strip()
    if not safe_email or "@" not in safe_email:
        raise AuthApiError(400, "invalid_email")
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, response = _json_request(
        "POST",
        "/billing/scene-purchases/restore/request",
        {"email": safe_email},
        headers=headers,
        timeout=30,
    )
    if not isinstance(response, dict) or not response.get("ok"):
        raise AuthApiError(_status or 0, response.get("error") if isinstance(response, dict) else "scene_licence_restore_failed", payload=response)
    return response


def restore_pro_with_license_key(license_key, prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")
    if not is_authenticated(prefs):
        ensure_authenticated_session(prefs)
    token = str(license_key or "").strip()
    if not token:
        raise AuthApiError(400, "missing_license_key")
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, payload = _json_request(
        "POST",
        "/billing/lemonsqueezy/restore",
        {"license_key": token},
        headers=headers,
        timeout=30,
    )
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise AuthApiError(_status or 0, payload.get("error") if isinstance(payload, dict) else "pro_restore_failed", payload=payload)
    sync_account_profile(prefs)
    return payload


def refresh_auth_session(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    refresh_token = str(getattr(prefs, "auth_refresh_token", "") or "").strip()
    if not refresh_token:
        if not str(getattr(prefs, "auth_api_key", "") or "").strip():
            connect_anonymous(prefs)
            return str(getattr(prefs, "auth_access_token", "") or "").strip()
        try:
            _reauth_with_api_key(prefs)
            return str(getattr(prefs, "auth_access_token", "") or "").strip()
        except AuthApiError as reauth_error:
            if is_terminal_auth_error(reauth_error):
                _report_critical_disconnect(
                    prefs,
                    "refresh_auth_session_missing_refresh_token_reauth_failed",
                    primary_error=reauth_error,
                )
                _clear_auth_session_preserve_api_key(
                    prefs,
                    state="logged_out",
                    status_message=_critical_disconnect_status_message(reauth_error),
                )
            else:
                logger.warning(
                    "Planetka: transient auth reauth failure while refresh token missing; preserving local session "
                    "(error=%s status=%s).",
                    _auth_error_code(reauth_error),
                    int(getattr(reauth_error, "status", 0) or 0),
                )
            raise reauth_error

    _status = None
    payload = None
    try:
        _status, payload = _json_request("POST", "/auth/refresh", {"refresh_token": refresh_token})
    except AuthApiError as refresh_error:
        if not str(getattr(prefs, "auth_api_key", "") or "").strip():
            try:
                connect_anonymous(prefs)
                return str(getattr(prefs, "auth_access_token", "") or "").strip()
            except AuthApiError:
                raise refresh_error
        try:
            _reauth_with_api_key(prefs)
            return str(getattr(prefs, "auth_access_token", "") or "").strip()
        except AuthApiError as reauth_error:
            if is_terminal_auth_error(refresh_error) or is_terminal_auth_error(reauth_error):
                _report_critical_disconnect(
                    prefs,
                    "refresh_auth_session_refresh_and_reauth_failed",
                    primary_error=refresh_error,
                    secondary_error=reauth_error,
                )
                _clear_auth_session_preserve_api_key(
                    prefs,
                    state="logged_out",
                    status_message=_critical_disconnect_status_message(refresh_error, reauth_error),
                )
            else:
                logger.warning(
                    "Planetka: transient auth refresh failure; preserving local session "
                    "(refresh_error=%s refresh_status=%s reauth_error=%s reauth_status=%s).",
                    _auth_error_code(refresh_error),
                    int(getattr(refresh_error, "status", 0) or 0),
                    _auth_error_code(reauth_error),
                    int(getattr(reauth_error, "status", 0) or 0),
                )
            raise refresh_error

    _apply_auth_payload(prefs, payload, login_state="authenticated")
    return str(getattr(prefs, "auth_access_token", "") or "").strip()


def get_access_token(prefs=None, allow_refresh=True):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    if is_authenticated(prefs):
        _require_valid_authenticated_tier(prefs, context="get_access_token")

    access_token = str(getattr(prefs, "auth_access_token", "") or "").strip()
    if access_token and not _token_expires_soon(access_token):
        return access_token
    if access_token and not allow_refresh:
        return access_token
    if not str(getattr(prefs, "auth_refresh_token", "") or "").strip():
        if not str(getattr(prefs, "auth_api_key", "") or "").strip():
            connect_anonymous(prefs)
            return str(getattr(prefs, "auth_access_token", "") or "").strip()
        try:
            _reauth_with_api_key(prefs)
            return str(getattr(prefs, "auth_access_token", "") or "").strip()
        except AuthApiError as exc:
            if is_terminal_auth_error(exc):
                recover_from_terminal_auth_error(exc, prefs=prefs, source="get_access_token_reauth_failed")
                return ""
            return access_token
    return refresh_auth_session(prefs)


def get_authorized_headers(prefs=None, allow_refresh=True):
    prefs = prefs or get_prefs()
    _require_valid_authenticated_tier(prefs, context="get_authorized_headers")
    token = get_access_token(prefs=prefs, allow_refresh=allow_refresh)
    if not token:
        raise AuthApiError(401, "account_not_connected")
    headers = {"Authorization": f"Bearer {token}"}
    device_id = _ensure_device_id(prefs)
    if device_id:
        headers["X-Planetka-Device-Id"] = device_id
    addon_version = _read_local_addon_version()
    if addon_version:
        headers["X-Planetka-Addon-Version"] = addon_version
    return headers


def logout_remote_session(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False

    refresh_token = str(getattr(prefs, "auth_refresh_token", "") or "").strip()
    access_token = str(getattr(prefs, "auth_access_token", "") or "").strip()
    device_id = str(getattr(prefs, "auth_device_id", "") or "").strip()

    payload = {}
    if refresh_token:
        payload["refresh_token"] = refresh_token
    if device_id:
        payload["device_id"] = device_id

    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if device_id:
        headers["X-Planetka-Device-Id"] = device_id

    try:
        _json_request("POST", "/auth/logout", payload, headers=headers, timeout=10)
        return True
    except AuthApiError as exc:
        # Keep logout resilient with older/backward-incompatible backends and
        # expired tokens; local logout should always proceed.
        if int(exc.status or 0) in {400, 401, 404}:
            return False
        logger.debug("Planetka: remote logout failed", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka: remote logout failed", exc_info=True)
        return False
