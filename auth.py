import base64
import json
import logging
import os
import platform
import time
import uuid
import urllib.error
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
    or os.getenv("PLANETKA_PRICING_URL")
    or "https://www.planetka.io/blender/pricing"
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


ACCOUNT_TIER_FREE = "free"
ACCOUNT_TIER_PERSONAL = "personal"
ACCOUNT_TIER_COMMERCIAL = "commercial"
PLAN_CODE_FREE = "free"
PLAN_CODE_PERSONAL = "personal"
PLAN_CODE_COMMERCIAL = "commercial"
PLAN_NAME_FREE = "Free"
PLAN_NAME_PERSONAL = "Personal"
PLAN_NAME_COMMERCIAL = "Commercial"
TIER_INTEGRITY_ERROR_CODE = "tier_integrity_violation"
TIER_INTEGRITY_STATUS_MESSAGE = (
    "Critical account tier integrity error detected. "
    "Planetka is locked until resolved. Contact info@planetka.io."
)
_ADDON_VERSION_CACHE = None
_CLOUD_CONNECTION_CACHE = {
    "checked": False,
    "timestamp": 0.0,
    "online": True,
    "message": "",
}
_CLOUD_CONNECTION_TTL_SECONDS = 5.0
_CLOUD_CONNECTION_OFFLINE_MESSAGE = "Planetka Cloud is not reachable. Check your internet connection."


class AuthApiError(RuntimeError):
    def __init__(self, status, error, payload=None):
        super().__init__(str(error or f"http_{status}"))
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
    if status in {401, 403} and code not in {"network_error", "invalid_json_response"}:
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
    return "Session expired. Connect again."


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
    lowered = message.lower()
    if TIER_INTEGRITY_ERROR_CODE in lowered:
        return (
            "Critical account tier integrity error detected. "
            "Planetka was locked for safety. Reconnect and contact info@planetka.io if it persists."
        )
    if "invalid_api_key" in lowered:
        return "Invalid Planetka API key."
    if "api_key_expired" in lowered:
        return "Planetka API key expired. Request a new key."
    if "api_key_revoked" in lowered:
        return "Planetka API key is revoked. Request a new key."
    if "device_limit_exceeded" in lowered:
        return "This API key is already active on the maximum number of computers."
    if "missing_device_id" in lowered:
        return "Planetka device identity is missing. Restart Blender and try again."
    if "account_blocked" in lowered or "account is blocked" in lowered:
        return "Planetka account is blocked. Contact info@planetka.io."
    if "1010" in lowered:
        return "Planetka connection was blocked by a security check. Please try again later or contact support."
    if "network_error" in lowered:
        return _CLOUD_CONNECTION_OFFLINE_MESSAGE
    if "missing_stripe_payment_link_url" in lowered:
        return "Planetka checkout URL is not configured on the API."
    if "quality_mode_not_allowed" in lowered or "not_allowed_for_tier" in lowered or "insufficient_data" in lowered:
        return "This Resolve needs Full Quality licensing for the selected tiles."
    if "insufficient_credits" in lowered:
        return "Monthly Billing is not available or the monthly cap is reached for this Resolve."
    if "missing_resolve_id" in lowered:
        return "Resolve metadata is missing. Retry Resolve and ensure Planetka is up to date."
    return f"Planetka login failed: {message.replace('_', ' ')}."


def _normalize_account_tier(value):
    plan_code = _normalize_plan_code(value)
    if plan_code == PLAN_CODE_COMMERCIAL:
        return ACCOUNT_TIER_COMMERCIAL
    if plan_code == PLAN_CODE_PERSONAL:
        return ACCOUNT_TIER_PERSONAL
    if plan_code == PLAN_CODE_FREE:
        return ACCOUNT_TIER_FREE
    tier = str(value or "").strip().lower()
    if tier in {ACCOUNT_TIER_FREE, ACCOUNT_TIER_PERSONAL, ACCOUNT_TIER_COMMERCIAL}:
        return tier
    return ""


def _normalize_plan_code(value):
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if token in {"", "none", "null"}:
        return ""
    if token == PLAN_CODE_FREE:
        return PLAN_CODE_FREE
    if token == PLAN_CODE_PERSONAL:
        return PLAN_CODE_PERSONAL
    if token == PLAN_CODE_COMMERCIAL:
        return PLAN_CODE_COMMERCIAL
    return ""


def _plan_name_for_code(plan_code):
    safe = _normalize_plan_code(plan_code)
    if safe == PLAN_CODE_COMMERCIAL:
        return PLAN_NAME_COMMERCIAL
    if safe == PLAN_CODE_FREE:
        return PLAN_NAME_FREE
    if safe == PLAN_CODE_PERSONAL:
        return PLAN_NAME_PERSONAL
    return ""


def _parse_int_or_none(value):
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"none", "null", "unlimited", "inf", "infinite"}:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    token = str(value or "").strip().lower()
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    return False


def _parse_optional_bool(value):
    text = str(value or "").strip().lower()
    if text in {"", "none", "null"}:
        return None
    return bool(_parse_bool(value))


def _first_non_empty(*values):
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_account_tier(payload):
    if not isinstance(payload, dict):
        return ""
    return _normalize_account_tier(payload.get("account_tier"))


def _extract_stored_account_tier(payload):
    if not isinstance(payload, dict):
        return ""
    return _normalize_account_tier(
        _first_non_empty(
            payload.get("stored_account_tier"),
            payload.get("storedAccountTier"),
            payload.get("stored_plan_code"),
            payload.get("storedPlanCode"),
        ),
    )


def _extract_plan(payload):
    if not isinstance(payload, dict):
        return {"code": "", "name": ""}

    plan_obj = payload.get("plan")
    if not isinstance(plan_obj, dict):
        plan_obj = {}

    code = _normalize_plan_code(
        _first_non_empty(
            plan_obj.get("code"),
            payload.get("plan_code"),
            payload.get("account_tier"),
        ),
    )
    return {
        "code": code or "",
        "name": _plan_name_for_code(code) or "",
    }


def _extract_stored_plan(payload):
    if not isinstance(payload, dict):
        return {"code": "", "name": ""}

    code = _normalize_plan_code(
        _first_non_empty(
            payload.get("stored_plan_code"),
            payload.get("storedPlanCode"),
            payload.get("stored_account_tier"),
            payload.get("storedAccountTier"),
        ),
    )

    return {
        "code": code or "",
        "name": _plan_name_for_code(code) or "",
    }


def _extract_quality_access_plan(payload):
    if not isinstance(payload, dict):
        return ""
    code = _normalize_plan_code(
        _first_non_empty(
            payload.get("quality_access_plan_code"),
            payload.get("qualityAccessPlanCode"),
        ),
    )
    if code:
        return code
    if _extract_unrestricted_quality_access(payload):
        return PLAN_CODE_COMMERCIAL
    return _extract_plan(payload)["code"]


def _extract_unrestricted_quality_access(payload):
    if not isinstance(payload, dict):
        return False
    for candidate in (
        payload.get("unrestricted_quality_access"),
        payload.get("unrestrictedQualityAccess"),
    ):
        parsed = _parse_optional_bool(candidate)
        if parsed is not None:
            return bool(parsed)
    return False


def _extract_unrestricted_quality_override(payload):
    if not isinstance(payload, dict):
        return ""
    token = str(
        _first_non_empty(
            payload.get("unrestricted_quality_override"),
            payload.get("unrestrictedQualityOverride"),
        ),
    ).strip().lower()
    if token in {"normal", "unrestricted"}:
        return token
    return ""


def _extract_unrestricted_quality_global(payload):
    if not isinstance(payload, dict):
        return False
    for candidate in (
        payload.get("unrestricted_quality_global"),
        payload.get("unrestrictedQualityGlobal"),
    ):
        parsed = _parse_optional_bool(candidate)
        if parsed is not None:
            return bool(parsed)
    return False


def _derive_commercial_use_allowed(plan_code):
    safe = _normalize_plan_code(plan_code)
    return bool(safe == PLAN_CODE_COMMERCIAL)


def _extract_commercial_use_allowed(payload, plan=None):
    if not isinstance(payload, dict):
        code = plan["code"] if isinstance(plan, dict) else PLAN_CODE_FREE
        return _derive_commercial_use_allowed(code)

    plan_obj = payload.get("plan")
    if not isinstance(plan_obj, dict):
        plan_obj = {}
    entitlements_obj = payload.get("entitlements")
    if not isinstance(entitlements_obj, dict):
        entitlements_obj = {}

    plan_code = ""
    if isinstance(plan, dict):
        plan_code = _normalize_plan_code(plan.get("code"))
    if not plan_code:
        plan_code = _normalize_plan_code(payload.get("plan_code") or payload.get("account_tier"))

    for candidate in (
        plan_obj.get("commercial_use_allowed"),
        payload.get("commercial_use_allowed"),
        payload.get("license_commercial_use_allowed"),
        entitlements_obj.get("commercial_use_allowed"),
    ):
        parsed = _parse_optional_bool(candidate)
        if parsed is not None:
            return bool(parsed)

    if plan_code:
        return _derive_commercial_use_allowed(plan_code)
    if isinstance(plan, dict):
        return _derive_commercial_use_allowed(plan.get("code"))
    return _derive_commercial_use_allowed(payload.get("plan_code") or payload.get("account_tier"))


def get_api_base_url():
    return DEFAULT_API_BASE_URL


def _is_cloud_offline_status_message(message):
    lowered = str(message or "").strip().lower()
    return bool(
        lowered.startswith(_CLOUD_CONNECTION_OFFLINE_MESSAGE.lower())
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
            response.read(256)
        if 200 <= status < 500:
            mark_planetka_cloud_online(prefs)
            return {"online": True, "message": "", "checked": True}
        message = f"Planetka Cloud is unavailable right now (HTTP {status})."
        _CLOUD_CONNECTION_CACHE["checked"] = True
        _CLOUD_CONNECTION_CACHE["timestamp"] = time.monotonic()
        _CLOUD_CONNECTION_CACHE["online"] = False
        _CLOUD_CONNECTION_CACHE["message"] = message
        if prefs is not None and is_authenticated(prefs):
            _set_auth_status_message(prefs, message)
        _tag_ui_redraw()
        return {"online": False, "message": message, "checked": True}
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        if 200 <= status < 500:
            mark_planetka_cloud_online(prefs)
            return {"online": True, "message": "", "checked": True}
        message = f"Planetka Cloud is unavailable right now (HTTP {status})."
        _CLOUD_CONNECTION_CACHE["checked"] = True
        _CLOUD_CONNECTION_CACHE["timestamp"] = time.monotonic()
        _CLOUD_CONNECTION_CACHE["online"] = False
        _CLOUD_CONNECTION_CACHE["message"] = message
        if prefs is not None and is_authenticated(prefs):
            _set_auth_status_message(prefs, message)
        _tag_ui_redraw()
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
    prefs.auth_commercial_use_allowed = ""
    prefs.auth_plan_code = ""
    prefs.auth_plan_name = ""
    prefs.auth_stored_plan_code = ""
    prefs.auth_stored_plan_name = ""
    prefs.auth_quality_access_plan_code = ""
    prefs.auth_unrestricted_quality_access = ""
    prefs.auth_unrestricted_quality_override = ""
    prefs.auth_unrestricted_quality_global = ""
    prefs.auth_contact_url = ""
    prefs.auth_upgrade_url = ""
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
    return bool(str(getattr(prefs, "auth_access_token", "") or "").strip() and str(getattr(prefs, "auth_email", "") or "").strip())


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


def get_account_tier(prefs=None):
    del prefs
    return ""


def get_stored_account_tier(prefs=None):
    return get_account_tier(prefs)


def is_commercial_account(prefs=None):
    return get_account_tier(prefs) == ACCOUNT_TIER_COMMERCIAL


def is_free_account(prefs=None):
    return get_account_tier(prefs) == ACCOUNT_TIER_FREE


def is_personal_account(prefs=None):
    return get_account_tier(prefs) == ACCOUNT_TIER_PERSONAL


def allows_balanced_full_quality(prefs=None):
    del prefs
    return True


def _normalize_texture_quality_token(value):
    token = str(value or "").strip().upper()
    if token in {"HALF", "BALANCED"}:
        return "PREVIEW"
    if token in {"PREVIEW", "FULL"}:
        return token
    return "PREVIEW"


def _is_high_quality_mode(value):
    return _normalize_texture_quality_token(value) == "FULL"


def allows_balanced_for_context(prefs=None, source=None):
    del prefs, source
    return False


def allows_full_quality_for_context(prefs=None, source=None):
    del prefs, source
    return True


def allows_animation_render_for_context(prefs=None, source=None, requested_mode=None):
    mode = requested_mode
    if mode is None and source is not None:
        try:
            mode = getattr(source, "anim_render_texture_quality_mode", "FULL")
        except (TypeError, ValueError, AttributeError):
            mode = "FULL"
    mode = _normalize_texture_quality_token(mode or "FULL")
    return allows_full_quality_for_context(prefs)


def requires_d090_cap_for_context(prefs=None, source=None):
    del prefs, source
    return False


def allows_balanced_full_quality_for_context(prefs=None, source=None, requested_mode="PREVIEW"):
    del prefs, source
    mode = _normalize_texture_quality_token(requested_mode)
    if mode == "PREVIEW":
        return True
    return mode == "FULL"


def get_plan_code(prefs=None):
    del prefs
    return ""


def get_stored_plan_code(prefs=None):
    return get_plan_code(prefs)


def get_stored_plan_name(prefs=None):
    del prefs
    return ""


def get_plan_name(prefs=None):
    del prefs
    return ""


def get_quality_access_plan_code(prefs=None):
    del prefs
    return ""


def has_unrestricted_quality_access(prefs=None):
    del prefs
    return False


def get_commercial_use_allowed(prefs=None):
    return bool(is_authenticated(prefs or get_prefs()))


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
        mark_planetka_cloud_online()
        raw = exc.read()
        text = raw.decode("utf-8", errors="replace") if raw else "{}"
        try:
            data = json.loads(text or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {"error": text or f"http_{exc.code}"}
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
    prefs.auth_plan_code = ""
    prefs.auth_plan_name = ""
    prefs.auth_stored_plan_code = ""
    prefs.auth_stored_plan_name = ""
    prefs.auth_quality_access_plan_code = ""
    prefs.auth_unrestricted_quality_access = ""
    prefs.auth_unrestricted_quality_override = ""
    prefs.auth_unrestricted_quality_global = ""
    prefs.auth_commercial_use_allowed = "1"
    prefs.auth_stored_account_tier = ""
    prefs.auth_account_tier = ""
    prefs.auth_contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
    )
    prefs.auth_upgrade_url = _first_non_empty(payload.get("upgrade_url"))
    prefs.auth_login_state = str(login_state or "authenticated")
    prefs.auth_status_message = str(status_message or "")
    _require_valid_authenticated_tier(prefs, context="auth_payload")
    try:
        from .credit_api import clear_credit_caches
        clear_credit_caches()
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed clearing credit caches after auth payload update", exc_info=True)
    _save_user_prefs()
    _tag_ui_redraw()


def _apply_account_profile_fields(prefs, payload):
    if not isinstance(payload, dict):
        return
    email = str(payload.get("email", "") or "").strip()
    if email:
        prefs.auth_email = email

    prefs.auth_plan_code = ""
    prefs.auth_plan_name = ""
    prefs.auth_stored_plan_code = ""
    prefs.auth_stored_plan_name = ""
    prefs.auth_quality_access_plan_code = ""
    prefs.auth_unrestricted_quality_access = ""
    prefs.auth_unrestricted_quality_override = ""
    prefs.auth_unrestricted_quality_global = ""
    prefs.auth_commercial_use_allowed = "1"
    prefs.auth_stored_account_tier = ""
    prefs.auth_account_tier = ""

    contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
    )
    if contact_url:
        prefs.auth_contact_url = contact_url

    upgrade_url = _first_non_empty(payload.get("upgrade_url"))
    if upgrade_url:
        prefs.auth_upgrade_url = upgrade_url
    _require_valid_authenticated_tier(prefs, context="account_profile")


def sync_account_profile(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    if not is_authenticated(prefs):
        return False

    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, payload = _json_request("GET", "/me", None, headers=headers)
    _apply_account_profile_fields(prefs, payload)
    _save_user_prefs()
    _tag_ui_redraw()
    return True


def refresh_auth_session(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    refresh_token = str(getattr(prefs, "auth_refresh_token", "") or "").strip()
    if not refresh_token:
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
        try:
            _reauth_with_api_key(prefs)
            return str(getattr(prefs, "auth_access_token", "") or "").strip()
        except AuthApiError:
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
