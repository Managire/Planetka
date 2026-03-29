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

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_prefs

logger = logging.getLogger(__name__)


DEFAULT_API_BASE_URL = str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/")
DEFAULT_UPGRADE_URL = str(
    os.getenv("PLANETKA_UPGRADE_URL")
    or os.getenv("PLANETKA_PRICING_URL")
    or "https://www.planetka.io/pricing"
).strip()
DEFAULT_MANAGE_SUBSCRIPTION_URL = str(
    os.getenv("PLANETKA_MANAGE_SUBSCRIPTION_URL")
    or os.getenv("PLANETKA_BILLING_URL")
    or "https://www.planetka.io/account"
).strip()
DEFAULT_CONTACT_URL = str(
    os.getenv("PLANETKA_CONTACT_URL")
    or os.getenv("PLANETKA_SUPPORT_URL")
    or "mailto:info@planetka.io?subject=Planetka%20support%20request"
).strip()
DEFAULT_TOPUP_URL = str(
    os.getenv("PLANETKA_TOPUP_URL")
    or os.getenv("PLANETKA_DATA_TOPUP_URL")
    or "https://www.planetka.io/signup"
).strip()
DEFAULT_API_KEY_REQUEST_URL = str(
    os.getenv("PLANETKA_API_KEY_REQUEST_URL")
    or f"{DEFAULT_API_BASE_URL}/api-key"
).strip()


def _env_int(name, default):
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _env_float(name, default):
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


DEFAULT_LOW_DATA_WARNING_GB = max(1, _env_int("PLANETKA_LOW_DATA_WARNING_GB", 10))
DEFAULT_LOW_DATA_WARNING_RATIO = min(max(_env_float("PLANETKA_LOW_DATA_WARNING_RATIO", 0.10), 0.01), 0.95)
DEFAULT_LOW_DATA_WARNING_BYTES = int(DEFAULT_LOW_DATA_WARNING_GB * (1024 ** 3))
ACCOUNT_TIER_FREE = "free"
ACCOUNT_TIER_PRO = "pro"
ACCOUNT_TIER_STUDIO = "studio"
PLAN_CODE_PLANETKA = "planetka"
PLAN_CODE_PLANETKA_PRO = "planetka_pro"
PLAN_CODE_PLANETKA_STUDIO = "planetka_studio"
PLAN_NAME_PLANETKA = "Planetka"
PLAN_NAME_PLANETKA_PRO = "Planetka Pro"
PLAN_NAME_PLANETKA_STUDIO = "Planetka Studio"
DEFAULT_DATA_COUNTING_RULE = "Only newly downloaded data counts. Reused local cache does not consume allowance."
PENDING_AUTH_MESSAGE = "Waiting for browser sign-in..."
_DEVICE_LOGIN_TIMER_REGISTERED = False
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
        return "Planetka API access is blocked by API gateway. Disable Browser Integrity Check for api.planetka.io."
    if "device_session_invalid" in lowered or "device_session_expired" in lowered:
        return "The Planetka browser session expired. Start login again."
    if "network_error" in lowered:
        return "Planetka could not reach the API. Check the internet connection and Worker deployment."
    if "missing_stripe_payment_link_url" in lowered:
        return "Planetka upgrade checkout URL is not configured on the API."
    if "allowance" in lowered or "quota_exceeded" in lowered or "insufficient_data" in lowered:
        return "Planetka account access for this request was denied. Verify your account status and try again."
    return f"Planetka login failed: {message.replace('_', ' ')}."


def _normalize_account_tier(value):
    plan_code = _normalize_plan_code(value)
    if plan_code == PLAN_CODE_PLANETKA_PRO:
        return ACCOUNT_TIER_PRO
    if plan_code == PLAN_CODE_PLANETKA_STUDIO:
        return ACCOUNT_TIER_STUDIO
    if plan_code == PLAN_CODE_PLANETKA:
        return ACCOUNT_TIER_FREE
    tier = str(value or "").strip().lower()
    if tier in {ACCOUNT_TIER_FREE, ACCOUNT_TIER_PRO, ACCOUNT_TIER_STUDIO}:
        return tier
    return ""


def _normalize_plan_code(value):
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if token in {"", "none", "null"}:
        return ""
    if token in {PLAN_CODE_PLANETKA, "free", "basic"}:
        return PLAN_CODE_PLANETKA
    if token in {PLAN_CODE_PLANETKA_PRO, "pro", "planetkapro", "planetka_pro_monthly"}:
        return PLAN_CODE_PLANETKA_PRO
    if token in {PLAN_CODE_PLANETKA_STUDIO, "studio", "enterprise"}:
        return PLAN_CODE_PLANETKA_STUDIO
    return token


def _plan_name_for_code(plan_code):
    safe = _normalize_plan_code(plan_code)
    if safe == PLAN_CODE_PLANETKA_PRO:
        return PLAN_NAME_PLANETKA_PRO
    if safe == PLAN_CODE_PLANETKA_STUDIO:
        return PLAN_NAME_PLANETKA_STUDIO
    if safe == PLAN_CODE_PLANETKA:
        return PLAN_NAME_PLANETKA
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
        return {"code": PLAN_CODE_PLANETKA, "name": PLAN_NAME_PLANETKA}

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
        code = PLAN_CODE_PLANETKA

    name = _first_non_empty(
        plan_obj.get("name"),
        payload.get("plan_name"),
        _plan_name_for_code(code),
    )

    return {
        "code": code,
        "name": name or _plan_name_for_code(code) or PLAN_NAME_PLANETKA,
    }


def _derive_commercial_use_allowed(plan_code):
    safe = _normalize_plan_code(plan_code)
    return bool(safe in {PLAN_CODE_PLANETKA_PRO, PLAN_CODE_PLANETKA_STUDIO})


def _extract_commercial_use_allowed(payload, plan=None):
    if not isinstance(payload, dict):
        code = plan["code"] if isinstance(plan, dict) else PLAN_CODE_PLANETKA
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
            if plan_code == PLAN_CODE_PLANETKA:
                return False
            return bool(parsed)

    if plan_code:
        return _derive_commercial_use_allowed(plan_code)
    if isinstance(plan, dict):
        return _derive_commercial_use_allowed(plan.get("code"))
    return _derive_commercial_use_allowed(payload.get("plan_code") or payload.get("account_tier"))


def _extract_tile_quota(payload):
    if not isinstance(payload, dict):
        return {
            "used": "",
            "limit": "",
            "reset_at": "",
            "period": "",
        }

    quota_obj = payload.get("tile_quota")
    if not isinstance(quota_obj, dict):
        quota_obj = {}

    used_raw = quota_obj.get("used", payload.get("tile_quota_used", payload.get("monthly_tiles_used", payload.get("tiles_used", ""))))
    limit_raw = quota_obj.get("limit", payload.get("tile_quota_limit", payload.get("monthly_tiles_limit", payload.get("free_tiles_limit", ""))))
    reset_raw = quota_obj.get("reset_at", payload.get("tile_quota_reset_at", payload.get("monthly_tiles_reset_at", payload.get("reset_at", ""))))
    period_raw = quota_obj.get("period", payload.get("tile_quota_period", payload.get("tiles_period", "month")))
    unlimited_raw = quota_obj.get("unlimited", payload.get("tile_quota_unlimited", ""))
    rule_raw = quota_obj.get(
        "rule",
        payload.get("tile_quota_rule", payload.get("counting_rule", DEFAULT_DATA_COUNTING_RULE)),
    )

    used_value = _parse_int_or_none(used_raw)
    limit_value = _parse_int_or_none(limit_raw)
    is_unlimited = bool(unlimited_raw is True or str(unlimited_raw or "").strip().lower() in {"1", "true", "yes", "unlimited"})

    return {
        "used": "" if used_value is None else str(max(0, int(used_value))),
        "limit": "" if (is_unlimited or limit_value is None) else str(max(0, int(limit_value))),
        "reset_at": str(reset_raw or "").strip(),
        "period": str(period_raw or "month").strip().lower() or "month",
        "rule": str(rule_raw or "").strip(),
    }


def _compute_allowance_warning_state(total_remaining_bytes, included_limit_bytes, exhausted_flag):
    if exhausted_flag:
        return "exhausted"
    if isinstance(total_remaining_bytes, int) and total_remaining_bytes <= 0:
        return "exhausted"
    if not isinstance(total_remaining_bytes, int):
        return "unknown"

    low_threshold_bytes = int(DEFAULT_LOW_DATA_WARNING_BYTES)
    if isinstance(included_limit_bytes, int) and included_limit_bytes > 0:
        pct_threshold = int(float(included_limit_bytes) * float(DEFAULT_LOW_DATA_WARNING_RATIO))
        low_threshold_bytes = max(low_threshold_bytes, pct_threshold)

    if total_remaining_bytes <= max(1, low_threshold_bytes):
        return "low"
    return "ok"


def _extract_data_allowance(payload):
    if not isinstance(payload, dict):
        return {
            "included_limit_bytes": "",
            "included_remaining_bytes": "",
            "topup_remaining_bytes": "0",
            "total_remaining_bytes": "",
            "period_end": "",
            "period": "month",
            "counting_rule": DEFAULT_DATA_COUNTING_RULE,
            "warning_state": "unknown",
            "exhausted": "",
            "downloaded_period_bytes": "",
        }

    allowance_obj = payload.get("data_allowance")
    if not isinstance(allowance_obj, dict):
        allowance_obj = payload.get("allowance")
    if not isinstance(allowance_obj, dict):
        allowance_obj = {}

    included_limit_value = _parse_int_or_none(
        allowance_obj.get(
            "included_limit_bytes",
            payload.get("included_limit_bytes", payload.get("monthly_included_bytes", "")),
        )
    )
    included_remaining_value = _parse_int_or_none(
        allowance_obj.get(
            "included_remaining_bytes",
            payload.get("included_remaining_bytes", payload.get("monthly_remaining_bytes", "")),
        )
    )
    topup_remaining_value = _parse_int_or_none(
        allowance_obj.get(
            "topup_remaining_bytes",
            payload.get("topup_remaining_bytes", payload.get("add_on_remaining_bytes", "")),
        )
    )
    total_remaining_value = _parse_int_or_none(
        allowance_obj.get(
            "total_remaining_bytes",
            payload.get("total_remaining_bytes", ""),
        )
    )
    # Single-pool allowance model:
    # show one remaining value in UI; extra/manual credits are folded into monthly remaining on backend.
    if included_remaining_value is None and isinstance(total_remaining_value, int):
        included_remaining_value = max(0, int(total_remaining_value))
    if included_remaining_value is None and isinstance(topup_remaining_value, int):
        included_remaining_value = max(0, int(topup_remaining_value))
    if total_remaining_value is None and isinstance(included_remaining_value, int):
        total_remaining_value = max(0, int(included_remaining_value))

    exhausted_flag = _parse_bool(
        allowance_obj.get("exhausted", payload.get("allowance_exhausted", "")),
    )
    warning_state_raw = str(
        allowance_obj.get("warning_state", payload.get("allowance_warning_state", ""))
    ).strip().lower()
    warning_state = warning_state_raw or _compute_allowance_warning_state(
        total_remaining_value,
        included_limit_value,
        exhausted_flag,
    )
    if warning_state not in {"ok", "low", "exhausted", "unknown"}:
        warning_state = "unknown"

    period_end = _first_non_empty(
        allowance_obj.get("period_end"),
        allowance_obj.get("period_ends_at"),
        payload.get("allowance_period_end"),
        payload.get("billing_period_end"),
    )
    period = _first_non_empty(
        allowance_obj.get("period"),
        payload.get("allowance_period"),
        "month",
    ).lower()
    downloaded_period_value = _parse_int_or_none(
        allowance_obj.get(
            "downloaded_period_bytes",
            payload.get("downloaded_period_bytes", payload.get("fresh_downloaded_period_bytes", "")),
        )
    )

    counting_rule = _first_non_empty(
        allowance_obj.get("counting_rule"),
        payload.get("counting_rule"),
        DEFAULT_DATA_COUNTING_RULE,
    )

    return {
        "included_limit_bytes": "" if included_limit_value is None else str(max(0, int(included_limit_value))),
        "included_remaining_bytes": "" if included_remaining_value is None else str(max(0, int(included_remaining_value))),
        "topup_remaining_bytes": "0",
        "total_remaining_bytes": "" if total_remaining_value is None else str(max(0, int(total_remaining_value))),
        "period_end": str(period_end or "").strip(),
        "period": str(period or "month"),
        "counting_rule": str(counting_rule or DEFAULT_DATA_COUNTING_RULE).strip(),
        "warning_state": str(warning_state or "unknown"),
        "exhausted": "1" if (exhausted_flag or warning_state == "exhausted") else "0",
        "downloaded_period_bytes": "" if downloaded_period_value is None else str(max(0, int(downloaded_period_value))),
    }


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
    try:
        import bpy
    except (ImportError, ModuleNotFoundError):
        return False

    try:
        result = bpy.ops.wm.save_userpref()
        return "FINISHED" in result
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed saving user preferences after auth state change", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed saving user preferences after auth state change", exc_info=True)
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
    prefs.auth_billing_period_end = ""
    prefs.auth_contact_url = ""
    prefs.auth_upgrade_url = ""
    prefs.auth_topup_url = ""
    prefs.auth_manage_subscription_url = ""
    prefs.auth_tile_quota_used = ""
    prefs.auth_tile_quota_limit = ""
    prefs.auth_tile_quota_reset_at = ""
    prefs.auth_tile_quota_period = ""
    prefs.auth_tile_quota_rule = ""
    prefs.auth_allowance_included_limit_bytes = ""
    prefs.auth_allowance_included_remaining_bytes = ""
    prefs.auth_allowance_topup_remaining_bytes = ""
    prefs.auth_allowance_total_remaining_bytes = ""
    prefs.auth_allowance_period_end = ""
    prefs.auth_allowance_period = ""
    prefs.auth_allowance_counting_rule = ""
    prefs.auth_allowance_warning_state = ""
    prefs.auth_allowance_exhausted = ""
    prefs.auth_allowance_downloaded_period_bytes = ""
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
    return get_account_tier(prefs) == ACCOUNT_TIER_STUDIO


def get_plan_code(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    if not is_authenticated(prefs):
        return ""
    value = _normalize_plan_code(getattr(prefs, "auth_plan_code", ""))
    if value:
        return value
    return _normalize_plan_code(getattr(prefs, "auth_account_tier", "")) or PLAN_CODE_PLANETKA


def get_plan_name(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    if not is_authenticated(prefs):
        return ""
    value = str(getattr(prefs, "auth_plan_name", "") or "").strip()
    if value:
        return value
    return _plan_name_for_code(get_plan_code(prefs)) or PLAN_NAME_PLANETKA


def get_commercial_use_allowed(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    if not is_authenticated(prefs):
        return False
    explicit = _parse_optional_bool(getattr(prefs, "auth_commercial_use_allowed", ""))
    if explicit is not None:
        return bool(explicit)
    return _derive_commercial_use_allowed(get_plan_code(prefs))


def get_billing_period_end(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_billing_period_end", "") or "").strip()


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


def get_topup_url(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return DEFAULT_TOPUP_URL
    value = str(getattr(prefs, "auth_topup_url", "") or "").strip()
    return value or DEFAULT_TOPUP_URL


def get_manage_subscription_url(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return DEFAULT_MANAGE_SUBSCRIPTION_URL
    value = str(getattr(prefs, "auth_manage_subscription_url", "") or "").strip()
    return value or DEFAULT_MANAGE_SUBSCRIPTION_URL


def get_tile_quota_used(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return None
    return _parse_int_or_none(getattr(prefs, "auth_tile_quota_used", ""))


def get_tile_quota_limit(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return None
    return _parse_int_or_none(getattr(prefs, "auth_tile_quota_limit", ""))


def get_tile_quota_reset_at(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_tile_quota_reset_at", "") or "").strip()


def get_tile_quota_period(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return "month"
    value = str(getattr(prefs, "auth_tile_quota_period", "") or "").strip().lower()
    return value or "month"


def get_tile_quota_rule(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_tile_quota_rule", "") or "").strip()


def get_allowance_included_limit_bytes(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return None
    return _parse_int_or_none(getattr(prefs, "auth_allowance_included_limit_bytes", ""))


def get_allowance_included_remaining_bytes(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return None
    return _parse_int_or_none(getattr(prefs, "auth_allowance_included_remaining_bytes", ""))


def get_allowance_topup_remaining_bytes(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return None
    return _parse_int_or_none(getattr(prefs, "auth_allowance_topup_remaining_bytes", ""))


def get_allowance_total_remaining_bytes(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return None
    included = get_allowance_included_remaining_bytes(prefs)
    if isinstance(included, int):
        return max(0, int(included))
    parsed_total = _parse_int_or_none(getattr(prefs, "auth_allowance_total_remaining_bytes", ""))
    if isinstance(parsed_total, int):
        return max(0, int(parsed_total))
    topup = get_allowance_topup_remaining_bytes(prefs)
    if isinstance(topup, int):
        return max(0, int(topup))
    return None


def get_allowance_period_end(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return ""
    value = str(getattr(prefs, "auth_allowance_period_end", "") or "").strip()
    if value:
        return value
    return str(getattr(prefs, "auth_billing_period_end", "") or "").strip()


def get_allowance_period(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return "month"
    value = str(getattr(prefs, "auth_allowance_period", "") or "").strip().lower()
    return value or "month"


def get_allowance_counting_rule(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return DEFAULT_DATA_COUNTING_RULE
    value = str(getattr(prefs, "auth_allowance_counting_rule", "") or "").strip()
    return value or DEFAULT_DATA_COUNTING_RULE


def get_allowance_warning_state(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return "unknown"
    value = str(getattr(prefs, "auth_allowance_warning_state", "") or "").strip().lower()
    if value in {"ok", "low", "exhausted", "unknown"}:
        return value
    return _compute_allowance_warning_state(
        get_allowance_total_remaining_bytes(prefs),
        get_allowance_included_limit_bytes(prefs),
        is_data_exhausted(prefs),
    )


def is_data_exhausted(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return False
    explicit = str(getattr(prefs, "auth_allowance_exhausted", "") or "").strip().lower()
    if explicit in {"1", "true", "yes"}:
        return True
    total = get_allowance_total_remaining_bytes(prefs)
    return isinstance(total, int) and total <= 0


def get_allowance_downloaded_period_bytes(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        return None
    return _parse_int_or_none(getattr(prefs, "auth_allowance_downloaded_period_bytes", ""))


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


def _apply_data_allowance_fields(prefs, payload):
    allowance = _extract_data_allowance(payload)
    prefs.auth_allowance_included_limit_bytes = allowance["included_limit_bytes"]
    prefs.auth_allowance_included_remaining_bytes = allowance["included_remaining_bytes"]
    prefs.auth_allowance_topup_remaining_bytes = allowance["topup_remaining_bytes"]
    prefs.auth_allowance_total_remaining_bytes = allowance["total_remaining_bytes"]
    prefs.auth_allowance_period_end = allowance["period_end"]
    prefs.auth_allowance_period = allowance["period"]
    prefs.auth_allowance_counting_rule = allowance["counting_rule"]
    prefs.auth_allowance_warning_state = allowance["warning_state"]
    prefs.auth_allowance_exhausted = allowance["exhausted"]
    prefs.auth_allowance_downloaded_period_bytes = allowance["downloaded_period_bytes"]


def _apply_auth_payload(prefs, payload, login_state="authenticated", status_message=""):
    allowance_obj = payload.get("data_allowance")
    if not isinstance(allowance_obj, dict):
        allowance_obj = payload.get("allowance")
    if not isinstance(allowance_obj, dict):
        allowance_obj = {}

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
    prefs.auth_billing_period_end = _first_non_empty(
        payload.get("billing_period_end"),
        allowance_obj.get("period_end"),
        allowance_obj.get("period_ends_at"),
    )
    prefs.auth_contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
        allowance_obj.get("contact_url"),
        allowance_obj.get("support_url"),
    )
    prefs.auth_upgrade_url = _first_non_empty(payload.get("upgrade_url"), allowance_obj.get("upgrade_url"))
    prefs.auth_topup_url = _first_non_empty(
        payload.get("topup_url"),
        payload.get("purchase_topup_url"),
        allowance_obj.get("topup_url"),
    )
    prefs.auth_manage_subscription_url = _first_non_empty(
        payload.get("manage_subscription_url"),
        allowance_obj.get("manage_subscription_url"),
    )
    quota = _extract_tile_quota(payload)
    prefs.auth_tile_quota_used = quota["used"]
    prefs.auth_tile_quota_limit = quota["limit"]
    prefs.auth_tile_quota_reset_at = quota["reset_at"]
    prefs.auth_tile_quota_period = quota["period"]
    prefs.auth_tile_quota_rule = quota["rule"]
    _apply_data_allowance_fields(prefs, payload)
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
    allowance_obj = payload.get("data_allowance")
    if not isinstance(allowance_obj, dict):
        allowance_obj = payload.get("allowance")
    if not isinstance(allowance_obj, dict):
        allowance_obj = {}

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

    billing_period_end = _first_non_empty(
        payload.get("billing_period_end"),
        allowance_obj.get("period_end"),
        allowance_obj.get("period_ends_at"),
    )
    if billing_period_end:
        prefs.auth_billing_period_end = billing_period_end

    contact_url = _first_non_empty(
        payload.get("contact_url"),
        payload.get("support_url"),
        allowance_obj.get("contact_url"),
        allowance_obj.get("support_url"),
    )
    if contact_url:
        prefs.auth_contact_url = contact_url

    upgrade_url = _first_non_empty(payload.get("upgrade_url"), allowance_obj.get("upgrade_url"))
    if upgrade_url:
        prefs.auth_upgrade_url = upgrade_url

    topup_url = _first_non_empty(
        payload.get("topup_url"),
        payload.get("purchase_topup_url"),
        allowance_obj.get("topup_url"),
    )
    if topup_url:
        prefs.auth_topup_url = topup_url

    manage_subscription_url = _first_non_empty(
        payload.get("manage_subscription_url"),
        allowance_obj.get("manage_subscription_url"),
    )
    if manage_subscription_url:
        prefs.auth_manage_subscription_url = manage_subscription_url

    quota = _extract_tile_quota(payload)
    prefs.auth_tile_quota_used = quota["used"]
    prefs.auth_tile_quota_limit = quota["limit"]
    prefs.auth_tile_quota_reset_at = quota["reset_at"]
    prefs.auth_tile_quota_period = quota["period"]
    prefs.auth_tile_quota_rule = quota["rule"]
    _apply_data_allowance_fields(prefs, payload)
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
    return headers


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
