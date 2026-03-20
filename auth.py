import base64
import json
import os
import time
import urllib.error
import urllib.request

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_prefs


DEFAULT_API_BASE_URL = str(os.getenv("PLANETKA_API_BASE_URL") or "https://api.planetka.io").rstrip("/")
_DEVICE_LOGIN_TIMER_REGISTERED = False


class AuthApiError(RuntimeError):
    def __init__(self, status, error, payload=None):
        super().__init__(str(error or f"http_{status}"))
        self.status = int(status or 0)
        self.error = str(error or f"http_{status}")
        self.payload = payload if isinstance(payload, dict) else {}


def describe_auth_error(error):
    message = str(getattr(error, "error", error) or "login_failed")
    lowered = message.lower()
    if "1010" in lowered:
        return "Planetka API access is blocked by API gateway. Disable Browser Integrity Check for api.planetka.io."
    if "device_session_invalid" in lowered or "device_session_expired" in lowered:
        return "The Planetka browser session expired. Start login again."
    if "network_error" in lowered:
        return "Planetka could not reach the API. Check the internet connection and Worker deployment."
    if "missing_stripe_payment_link_url" in lowered:
        return "Planetka activation flow is not configured on the API."
    return f"Planetka login failed: {message.replace('_', ' ')}."


def get_api_base_url():
    return DEFAULT_API_BASE_URL


def _tag_ui_redraw():
    try:
        import bpy
    except Exception:
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
    except Exception:
        return


def _save_user_prefs():
    try:
        import bpy
    except Exception:
        return False

    try:
        result = bpy.ops.wm.save_userpref()
        return "FINISHED" in result
    except Exception:
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
    prefs.auth_access_token = ""
    prefs.auth_refresh_token = ""
    prefs.auth_subscription_status = ""
    prefs.auth_renews_at = ""
    prefs.auth_trial_ends_at = ""
    prefs.auth_login_state = str(state or "logged_out")
    prefs.auth_status_message = str(status_message or "")
    _clear_pending_login_fields(prefs)
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
    except Exception:
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
        except Exception:
            data = {"error": text or f"http_{exc.code}"}
        raise AuthApiError(exc.code, data.get("error") or f"http_{exc.code}", payload=data) from exc
    except urllib.error.URLError as exc:
        raise AuthApiError(0, f"network_error_{exc.reason}") from exc
    except ValueError as exc:
        raise AuthApiError(0, "invalid_json_response") from exc


def _apply_auth_payload(prefs, payload, login_state="authenticated", status_message=""):
    prefs.auth_email = str(payload.get("email", "") or "").strip()
    prefs.auth_access_token = str(payload.get("access_token", "") or "").strip()
    prefs.auth_refresh_token = str(payload.get("refresh_token", "") or "").strip()
    prefs.auth_subscription_status = str(payload.get("subscription_status", "") or "").strip()
    prefs.auth_renews_at = str(payload.get("renews_at", "") or "").strip()
    prefs.auth_trial_ends_at = str(payload.get("trial_ends_at", "") or "").strip()
    prefs.auth_login_state = str(login_state or "authenticated")
    prefs.auth_status_message = str(status_message or "")
    _clear_pending_login_fields(prefs)
    _save_user_prefs()
    _tag_ui_redraw()


def refresh_auth_session(prefs=None):
    prefs = prefs or get_prefs()
    if prefs is None:
        raise AuthApiError(0, "prefs_unavailable")

    refresh_token = str(getattr(prefs, "auth_refresh_token", "") or "").strip()
    if not refresh_token:
        clear_auth_session(prefs, state="logged_out", status_message="")
        raise AuthApiError(401, "missing_refresh_token")

    _status = None
    payload = None
    try:
        _status, payload = _json_request("POST", "/auth/refresh", {"refresh_token": refresh_token})
    except AuthApiError:
        clear_auth_session(prefs, state="logged_out", status_message="Session expired. Connect again.")
        raise

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
        return access_token
    return refresh_auth_session(prefs)


def get_authorized_headers(prefs=None, allow_refresh=True):
    token = get_access_token(prefs=prefs, allow_refresh=allow_refresh)
    if not token:
        raise AuthApiError(401, "account_not_connected")
    return {"Authorization": f"Bearer {token}"}


def _device_login_timer():
    global _DEVICE_LOGIN_TIMER_REGISTERED
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
        prefs.auth_status_message = "Waiting for email activation..."
        _tag_ui_redraw()
        return interval

    status = str(payload.get("status", "") or "").strip().lower()
    if status == "completed":
        _apply_auth_payload(prefs, payload, login_state="authenticated")
        _DEVICE_LOGIN_TIMER_REGISTERED = False
        return None

    prefs.auth_status_message = "Waiting for email activation..."
    _tag_ui_redraw()
    return interval


def ensure_device_login_polling():
    global _DEVICE_LOGIN_TIMER_REGISTERED
    if _DEVICE_LOGIN_TIMER_REGISTERED:
        return

    try:
        import bpy
    except Exception:
        return

    try:
        if not bpy.app.timers.is_registered(_device_login_timer):
            bpy.app.timers.register(_device_login_timer, first_interval=1.0)
        _DEVICE_LOGIN_TIMER_REGISTERED = True
    except Exception:
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
        ensure_device_login_polling()
        return {
            "verification_url": existing_url,
            "device_code": str(getattr(prefs, "auth_device_code", "") or "").strip(),
            "expires_at": str(getattr(prefs, "auth_device_expires_at", "") or "").strip(),
            "interval_seconds": int(getattr(prefs, "auth_poll_interval_seconds", 2) or 2),
        }

    _status, payload = _json_request("POST", "/device/start", {})
    clear_auth_session(prefs, state="pending", status_message="Waiting for email activation...")
    prefs.auth_login_state = "pending"
    prefs.auth_status_message = "Waiting for email activation..."
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
