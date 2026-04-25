import base64
import datetime
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
# Backward-compat alias for older local prefs/payloads.
ACCOUNT_TIER_LITE = "lite"
ACCOUNT_TIER_PRO = "pro"
PLAN_CODE_FREE = "free"
PLAN_CODE_LITE = "lite"
PLAN_CODE_PRO = "pro"
PLAN_CODE_PLANETKA = "planetka"
PLAN_CODE_PLANETKA_PRO = "planetka_pro"
PLAN_NAME_FREE = "Planetka Free"
PLAN_NAME_PERSONAL = "Planetka Personal"
PLAN_NAME_PRO = "Planetka Commercial"
PENDING_AUTH_MESSAGE = "Waiting for browser sign-in..."
_DEVICE_LOGIN_TIMER_REGISTERED = False
_ADDON_VERSION_CACHE = None
THROTTLE_STATUS_PREFIX = "Account throttled until "


class AuthApiError(RuntimeError):
    def __init__(self, status, error, payload=None):
        super().__init__(str(error or f"http_{status}"))
        self.status = int(status or 0)
        self.error = str(error or f"http_{status}")
        self.payload = payload if isinstance(payload, dict) else {}


def describe_auth_error(error):
    message = str(getattr(error, "error", error) or "login_failed")
    lowered = message.lower()
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
    if "device_session_invalid" in lowered or "device_session_expired" in lowered:
        return "The Planetka browser session expired. Start login again."
    if "network_error" in lowered:
        return "Planetka could not connect right now. Check your internet connection and try again."
    if "missing_stripe_payment_link_url" in lowered:
        return "Planetka checkout URL is not configured on the API."
    if "quality_mode_not_allowed" in lowered or "not_allowed_for_tier" in lowered or "insufficient_data" in lowered:
        return "Planetka account does not currently have access to this texture quality."
    if "missing_resolve_id" in lowered:
        return "Resolve metadata is missing. Retry Resolve and ensure Planetka is up to date."
    return f"Planetka login failed: {message.replace('_', ' ')}."


def _normalize_account_tier(value):
    plan_code = _normalize_plan_code(value)
    if plan_code == PLAN_CODE_PRO:
        return ACCOUNT_TIER_PRO
    if plan_code == PLAN_CODE_LITE:
        return ACCOUNT_TIER_PERSONAL
    if plan_code == PLAN_CODE_FREE:
        return ACCOUNT_TIER_FREE
    tier = str(value or "").strip().lower()
    if tier in {ACCOUNT_TIER_FREE, ACCOUNT_TIER_PRO, ACCOUNT_TIER_PERSONAL, ACCOUNT_TIER_LITE}:
        return ACCOUNT_TIER_PERSONAL if tier in {ACCOUNT_TIER_PERSONAL, ACCOUNT_TIER_LITE} else tier
    if tier in {"indie", "studio"}:
        return ACCOUNT_TIER_PERSONAL if tier == "indie" else ACCOUNT_TIER_PRO
    return ""


def _normalize_plan_code(value):
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if token in {"", "none", "null"}:
        return ""
    if token in {PLAN_CODE_FREE, "trial"}:
        return PLAN_CODE_FREE
    if token in {"indie", "creator"}:
        return PLAN_CODE_LITE
    if token in {PLAN_CODE_LITE, PLAN_CODE_PLANETKA, "basic", "personal"}:
        return PLAN_CODE_LITE
    if token in {
        PLAN_CODE_PRO,
        PLAN_CODE_PLANETKA_PRO,
        "pro",
        "planetkapro",
        "planetka_pro_monthly",
        "commercial",
        "planetka_commercial",
        "planetka_commercial_monthly",
    }:
        return PLAN_CODE_PRO
    if token in {"planetka_studio", "studio", "enterprise"}:
        return PLAN_CODE_PRO
    return token


def _plan_name_for_code(plan_code):
    safe = _normalize_plan_code(plan_code)
    if safe == PLAN_CODE_PRO:
        return PLAN_NAME_PRO
    if safe == PLAN_CODE_FREE:
        return PLAN_NAME_FREE
    if safe == PLAN_CODE_LITE:
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


def _extract_plan(payload):
    if not isinstance(payload, dict):
        return {"code": PLAN_CODE_FREE, "name": PLAN_NAME_FREE}

    plan_obj = payload.get("plan")
    if not isinstance(plan_obj, dict):
        plan_obj = {}

    code = _normalize_plan_code(
        _first_non_empty(
            plan_obj.get("code"),
            payload.get("plan_code"),
            payload.get("account_plan"),
            payload.get("account_tier"),
            payload.get("tier"),
        ),
    )
    if not code:
        code = PLAN_CODE_FREE

    name = _first_non_empty(
        plan_obj.get("name"),
        payload.get("plan_name"),
        _plan_name_for_code(code),
    )

    return {
        "code": code,
        "name": name or _plan_name_for_code(code) or PLAN_NAME_FREE,
    }


def _derive_commercial_use_allowed(plan_code):
    safe = _normalize_plan_code(plan_code)
    return bool(safe in {PLAN_CODE_PRO})


def _extract_commercial_use_allowed(payload, plan=None):
    if not isinstance(payload, dict):
        code = plan["code"] if isinstance(plan, dict) else PLAN_CODE_LITE
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


def _parse_iso_timestamp_seconds(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return float(parsed.timestamp())


def _extract_throttled_until(payload):
    if not isinstance(payload, dict):
        return ""
    for key in ("throttled_until", "download_throttled_until"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _build_throttle_status_message(payload):
    throttled_until = _extract_throttled_until(payload)
    if not throttled_until:
        return ""
    expiry_seconds = _parse_iso_timestamp_seconds(throttled_until)
    if expiry_seconds is not None and expiry_seconds <= float(time.time()):
        return ""
    return (
        f"{THROTTLE_STATUS_PREFIX}{throttled_until}. "
        "High-volume data use detected. Download speed is temporarily reduced."
    )


def _is_throttle_status_message(message):
    text = str(message or "").strip().lower()
    return text.startswith(THROTTLE_STATUS_PREFIX.lower())


def get_api_base_url():
    return DEFAULT_API_BASE_URL


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


def _clear_pending_login_fields(prefs):
    prefs.auth_device_code = ""
    prefs.auth_device_verification_url = ""
    prefs.auth_device_expires_at = ""
    prefs.auth_poll_interval_seconds = 2


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
    prefs.auth_commercial_use_allowed = ""
    prefs.auth_plan_code = ""
    prefs.auth_plan_name = ""
    prefs.auth_contact_url = ""
    prefs.auth_upgrade_url = ""
    prefs.auth_login_state = str(state or "logged_out")
    prefs.auth_status_message = str(status_message or "")
    _clear_pending_login_fields(prefs)
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


def get_device_verification_url(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_device_verification_url", "") or "").strip()


def get_api_key_request_url():
    return DEFAULT_API_KEY_REQUEST_URL


def get_api_key_mask(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_api_key_mask", "") or "").strip()


def get_account_tier(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    if not is_authenticated(prefs):
        return ""
    explicit_tier = _normalize_account_tier(getattr(prefs, "auth_account_tier", ""))
    if explicit_tier:
        return explicit_tier
    return _normalize_account_tier(get_plan_code(prefs)) or ACCOUNT_TIER_FREE


def is_pro_account(prefs=None):
    return get_account_tier(prefs) == ACCOUNT_TIER_PRO


def is_studio_account(prefs=None):
    return False


def is_free_account(prefs=None):
    return get_account_tier(prefs) == ACCOUNT_TIER_FREE


def is_lite_account(prefs=None):
    return get_account_tier(prefs) in {ACCOUNT_TIER_PERSONAL, ACCOUNT_TIER_LITE}


def is_personal_account(prefs=None):
    return get_account_tier(prefs) == ACCOUNT_TIER_PERSONAL


def is_indie_account(prefs=None):
    return False


def allows_balanced_full_quality(prefs=None):
    return is_lite_account(prefs) or is_pro_account(prefs)


def _normalize_texture_quality_token(value):
    token = str(value or "").strip().upper()
    if token == "HALF":
        return "BALANCED"
    if token in {"PREVIEW", "BALANCED", "FULL"}:
        return token
    return "PREVIEW"


def _is_high_quality_mode(value):
    return _normalize_texture_quality_token(value) in {"BALANCED", "FULL"}


def allows_balanced_for_context(prefs=None, source=None):
    del source
    tier = get_account_tier(prefs)
    return tier in {ACCOUNT_TIER_PERSONAL, ACCOUNT_TIER_LITE, ACCOUNT_TIER_PRO}


def allows_full_quality_for_context(prefs=None, source=None):
    del source
    return get_account_tier(prefs) == ACCOUNT_TIER_PRO


def allows_animation_render_for_context(prefs=None, source=None):
    del source
    return get_account_tier(prefs) == ACCOUNT_TIER_PRO


def requires_d090_cap_for_context(prefs=None, source=None):
    del prefs, source
    return False


def allows_balanced_full_quality_for_context(prefs=None, source=None, requested_mode="PREVIEW"):
    del source
    mode = _normalize_texture_quality_token(requested_mode)
    tier = get_account_tier(prefs)
    if mode == "PREVIEW":
        return True
    if mode == "BALANCED":
        return tier in {ACCOUNT_TIER_PERSONAL, ACCOUNT_TIER_LITE, ACCOUNT_TIER_PRO}
    if mode == "FULL":
        return tier == ACCOUNT_TIER_PRO
    return False


def get_plan_code(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    if not is_authenticated(prefs):
        return ""
    value = _normalize_plan_code(getattr(prefs, "auth_plan_code", ""))
    if value:
        return value
    return _normalize_plan_code(getattr(prefs, "auth_account_tier", "")) or PLAN_CODE_FREE


def get_plan_name(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    if not is_authenticated(prefs):
        return ""
    value = str(getattr(prefs, "auth_plan_name", "") or "").strip()
    if value:
        return value
    return _plan_name_for_code(get_plan_code(prefs)) or PLAN_NAME_FREE


def get_commercial_use_allowed(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    if not is_authenticated(prefs):
        return False
    explicit = _parse_optional_bool(getattr(prefs, "auth_commercial_use_allowed", ""))
    if explicit is not None:
        return bool(explicit)
    return bool(_derive_commercial_use_allowed(get_plan_code(prefs)))


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
            return int(getattr(response, "status", 200) or 200), data
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        text = raw.decode("utf-8", errors="replace") if raw else "{}"
        try:
            data = json.loads(text or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {"error": text or f"http_{exc.code}"}
        raise AuthApiError(exc.code, data.get("error") or f"http_{exc.code}", payload=data) from exc
    except urllib.error.URLError as exc:
        raise AuthApiError(0, f"network_error_{exc.reason}") from exc
    except ValueError as exc:
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
    plan = _extract_plan(payload)
    prefs.auth_plan_code = plan["code"]
    prefs.auth_plan_name = plan["name"]
    prefs.auth_commercial_use_allowed = "1" if _extract_commercial_use_allowed(payload, plan=plan) else "0"
    account_tier = _extract_account_tier(payload) or _normalize_account_tier(plan["code"])
    prefs.auth_account_tier = account_tier or ACCOUNT_TIER_FREE
    prefs.auth_contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
    )
    prefs.auth_upgrade_url = _first_non_empty(payload.get("upgrade_url"))
    prefs.auth_login_state = str(login_state or "authenticated")
    throttle_status_message = _build_throttle_status_message(payload)
    if throttle_status_message:
        prefs.auth_status_message = throttle_status_message
    else:
        prefs.auth_status_message = str(status_message or "")
    _clear_pending_login_fields(prefs)
    _save_user_prefs()
    _tag_ui_redraw()


def _apply_account_profile_fields(prefs, payload):
    if not isinstance(payload, dict):
        return
    email = str(payload.get("email", "") or "").strip()
    if email:
        prefs.auth_email = email

    plan = _extract_plan(payload)
    if plan["code"]:
        prefs.auth_plan_code = plan["code"]
    if plan["name"]:
        prefs.auth_plan_name = plan["name"]
    prefs.auth_commercial_use_allowed = "1" if _extract_commercial_use_allowed(payload, plan=plan) else "0"

    account_tier = _extract_account_tier(payload) or _normalize_account_tier(plan["code"])
    if account_tier:
        prefs.auth_account_tier = account_tier

    contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
    )
    if contact_url:
        prefs.auth_contact_url = contact_url

    upgrade_url = _first_non_empty(payload.get("upgrade_url"))
    if upgrade_url:
        prefs.auth_upgrade_url = upgrade_url
    throttle_status_message = _build_throttle_status_message(payload)
    if throttle_status_message:
        prefs.auth_status_message = throttle_status_message
    elif _is_throttle_status_message(getattr(prefs, "auth_status_message", "")):
        prefs.auth_status_message = ""


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
        except AuthApiError:
            _clear_auth_session_preserve_api_key(prefs, state="logged_out", status_message="")
            raise AuthApiError(401, "missing_refresh_token")

    _status = None
    payload = None
    try:
        _status, payload = _json_request("POST", "/auth/refresh", {"refresh_token": refresh_token})
    except AuthApiError as refresh_error:
        try:
            _reauth_with_api_key(prefs)
            return str(getattr(prefs, "auth_access_token", "") or "").strip()
        except AuthApiError:
            _clear_auth_session_preserve_api_key(prefs, state="logged_out", status_message="Session expired. Connect again.")
            raise refresh_error

    _apply_auth_payload(prefs, payload, login_state="authenticated")
    return str(getattr(prefs, "auth_access_token", "") or "").strip()


def get_access_token(prefs=None, allow_refresh=True):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""

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


def _device_login_timer():
    global _DEVICE_LOGIN_TIMER_REGISTERED
    try:
        prefs = get_prefs()
        if prefs is None:
            _DEVICE_LOGIN_TIMER_REGISTERED = False
            return None

        if get_login_state(prefs) != "pending":
            _DEVICE_LOGIN_TIMER_REGISTERED = False
            return None

        device_code = str(getattr(prefs, "auth_device_code", "") or "").strip()
        if not device_code:
            prefs.auth_login_state = "logged_out"
            prefs.auth_status_message = ""
            _DEVICE_LOGIN_TIMER_REGISTERED = False
            _tag_ui_redraw()
            return None

        expires_at = str(getattr(prefs, "auth_device_expires_at", "") or "").strip()
        if expires_at:
            try:
                if time.time() >= float(expires_at):
                    clear_auth_session(prefs, state="logged_out", status_message="Browser session timed out. Connect again.")
                    _DEVICE_LOGIN_TIMER_REGISTERED = False
                    return None
            except (TypeError, ValueError):
                pass

        interval = max(1.0, float(getattr(prefs, "auth_poll_interval_seconds", 2) or 2))
        try:
            _status, payload = _json_request("POST", "/device/poll", {"device_code": device_code})
        except AuthApiError as exc:
            if exc.status in {404, 410, 408}:
                clear_auth_session(prefs, state="logged_out", status_message="Browser session expired. Connect again.")
                _DEVICE_LOGIN_TIMER_REGISTERED = False
                return None
            if exc.status == 429:
                retry_after = 0.0
                try:
                    retry_after = float((exc.payload or {}).get("retry_after_seconds", 0) or 0)
                except (TypeError, ValueError):
                    retry_after = 0.0
                interval = max(interval, max(1.0, retry_after))
            prefs.auth_status_message = PENDING_AUTH_MESSAGE
            _tag_ui_redraw()
            return interval

        status = str(payload.get("status", "") or "").strip().lower()
        if status == "completed":
            _apply_auth_payload(prefs, payload, login_state="authenticated")
            _DEVICE_LOGIN_TIMER_REGISTERED = False
            return None

        prefs.auth_status_message = PENDING_AUTH_MESSAGE
        _tag_ui_redraw()
        return interval
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        # Keep polling alive on unexpected runtime errors instead of silently stalling login.
        logger.debug("Planetka: auth device polling loop failed", exc_info=True)
        _DEVICE_LOGIN_TIMER_REGISTERED = False
        prefs = get_prefs()
        if prefs is not None and get_login_state(prefs) == "pending":
            prefs.auth_status_message = PENDING_AUTH_MESSAGE
            _tag_ui_redraw()
            return max(1.0, float(getattr(prefs, "auth_poll_interval_seconds", 2) or 2))
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        # Keep polling alive on unexpected runtime errors instead of silently stalling login.
        logger.debug("Planetka: auth device polling loop failed", exc_info=True)
        _DEVICE_LOGIN_TIMER_REGISTERED = False
        prefs = get_prefs()
        if prefs is not None and get_login_state(prefs) == "pending":
            prefs.auth_status_message = PENDING_AUTH_MESSAGE
            _tag_ui_redraw()
            return max(1.0, float(getattr(prefs, "auth_poll_interval_seconds", 2) or 2))
        return None


def ensure_device_login_polling():
    global _DEVICE_LOGIN_TIMER_REGISTERED
    try:
        import bpy
    except (ImportError, ModuleNotFoundError):
        return

    try:
        # Self-heal stale in-memory flag after timer interruptions/add-on reloads.
        if _DEVICE_LOGIN_TIMER_REGISTERED and not bpy.app.timers.is_registered(_device_login_timer):
            _DEVICE_LOGIN_TIMER_REGISTERED = False
        if _DEVICE_LOGIN_TIMER_REGISTERED:
            return
        if not bpy.app.timers.is_registered(_device_login_timer):
            bpy.app.timers.register(_device_login_timer, first_interval=1.0)
        _DEVICE_LOGIN_TIMER_REGISTERED = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed registering auth device polling timer", exc_info=True)
        _DEVICE_LOGIN_TIMER_REGISTERED = False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed registering auth device polling timer", exc_info=True)
        _DEVICE_LOGIN_TIMER_REGISTERED = False


def cancel_pending_device_login(prefs=None, status_message=""):
    prefs = prefs or get_prefs()
    if prefs is None:
        return
    clear_auth_session(prefs, state="logged_out", status_message=status_message)


def start_device_login(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    existing_url = get_device_verification_url(prefs)
    if get_login_state(prefs) == "pending" and existing_url:
        existing_code = str(getattr(prefs, "auth_device_code", "") or "").strip()
        existing_expires_at = str(getattr(prefs, "auth_device_expires_at", "") or "").strip()
        session_is_fresh = bool(existing_code)
        if session_is_fresh and existing_expires_at:
            try:
                session_is_fresh = float(existing_expires_at) > time.time()
            except (TypeError, ValueError):
                session_is_fresh = True
        if session_is_fresh:
            ensure_device_login_polling()
            return {
                "verification_url": existing_url,
                "device_code": existing_code,
                "expires_at": existing_expires_at,
                "interval_seconds": int(getattr(prefs, "auth_poll_interval_seconds", 2) or 2),
            }
        clear_auth_session(prefs, state="logged_out", status_message="Previous browser session expired. Starting a new one.")

    _status, payload = _json_request("POST", "/device/start", {})
    clear_auth_session(prefs, state="pending", status_message=PENDING_AUTH_MESSAGE)
    prefs.auth_login_state = "pending"
    prefs.auth_status_message = PENDING_AUTH_MESSAGE
    prefs.auth_device_code = str(payload.get("device_code", "") or "").strip()
    prefs.auth_device_verification_url = str(payload.get("verification_url", "") or "").strip()
    prefs.auth_device_expires_at = str(payload.get("expires_at_ts", "") or "").strip()
    try:
        prefs.auth_poll_interval_seconds = int(payload.get("interval_seconds", 2) or 2)
    except (TypeError, ValueError):
        prefs.auth_poll_interval_seconds = 2
    _save_user_prefs()
    _tag_ui_redraw()
    ensure_device_login_polling()
    return payload
