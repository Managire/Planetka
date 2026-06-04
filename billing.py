"""Planetka paid Full/Animation access helpers.

The add-on keeps Preview and Balanced fully direct. Free edition Full quality and
Final Animation start with a small backend billing check. Pro edition bypasses
these checks as pre-paid access.
"""

import time
import webbrowser

from .auth import AuthApiError, _json_request, get_authorized_headers, get_session_edition
from .extension_prefs import get_prefs

_PRICE_CACHE = {
    "timestamp": 0.0,
    "payload": {},
}
_PRICE_CACHE_TTL_SECONDS = 300.0
_PRICE_REQUEST_RUNNING = False


def _price_cache_valid():
    return (time.time() - float(_PRICE_CACHE.get("timestamp", 0.0) or 0.0)) <= _PRICE_CACHE_TTL_SECONDS


def cached_billing_prices():
    return dict(_PRICE_CACHE.get("payload") or {}) if _price_cache_valid() else {}


def request_billing_prices_async():
    global _PRICE_REQUEST_RUNNING
    if _PRICE_REQUEST_RUNNING or _price_cache_valid():
        return
    import threading

    def _worker():
        global _PRICE_REQUEST_RUNNING
        try:
            get_billing_prices(prefs=None, allow_cached=False)
        except Exception:
            pass
        finally:
            _PRICE_REQUEST_RUNNING = False

    _PRICE_REQUEST_RUNNING = True
    thread = threading.Thread(target=_worker, name="PlanetkaBillingPrices", daemon=True)
    thread.start()


def get_billing_prices(prefs=None, allow_cached=True):
    if allow_cached and _price_cache_valid():
        payload = dict(_PRICE_CACHE.get("payload") or {})
        if payload:
            return payload
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    _status, payload = _json_request("GET", "/billing/prices", {}, headers=headers, timeout=15)
    if not isinstance(payload, dict):
        payload = {}
    _PRICE_CACHE["timestamp"] = time.time()
    _PRICE_CACHE["payload"] = dict(payload)
    return dict(payload)


def billing_price_label(cents, currency="EUR"):
    try:
        amount = max(0, int(cents or 0)) / 100.0
    except (TypeError, ValueError):
        amount = 0.0
    safe_currency = str(currency or "EUR").strip().upper() or "EUR"
    if safe_currency == "EUR":
        return f"€{amount:.2f}"
    return f"{amount:.2f} {safe_currency}"


def current_install_is_pro(prefs=None):
    try:
        return str(get_session_edition(prefs or get_prefs()) or "").strip().lower() == "pro"
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return True


def full_resolve_button_label(prefs=None):
    if current_install_is_pro(prefs):
        return "Full"
    prices = cached_billing_prices()
    if prices:
        return f"Full ({billing_price_label(prices.get('full_resolve_price_cents'), prices.get('currency'))})"
    request_billing_prices_async()
    return "Full"


def animation_render_button_label(frame_count=1, prefs=None):
    if current_install_is_pro(prefs):
        return "Render Animation"
    prices = cached_billing_prices()
    if prices:
        per_unit = int(prices.get("animation_price_per_300_cents", 0) or 0)
        units = max(1, (max(1, int(frame_count or 1)) + 299) // 300)
        return f"Render Animation ({billing_price_label(per_unit * units, prices.get('currency'))})"
    request_billing_prices_async()
    return "Render Animation"


def consume_paid_access(kind, frame_count=0, prefs=None):
    prefs = prefs or get_prefs()
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    payload = {"kind": str(kind or "")}
    if frame_count:
        payload["frame_count"] = int(frame_count)
    _status, response = _json_request("POST", "/billing/consume", payload, headers=headers, timeout=20)
    return dict(response or {})


def create_checkout(kind, frame_count=0, prefs=None):
    prefs = prefs or get_prefs()
    headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    payload = {"kind": str(kind or "")}
    if frame_count:
        payload["frame_count"] = int(frame_count)
    _status, response = _json_request("POST", "/billing/checkout", payload, headers=headers, timeout=30)
    return dict(response or {})


def ensure_paid_access_or_open_checkout(kind, frame_count=0, prefs=None):
    """Return (allowed, message). Opens checkout when payment is required."""
    prefs = prefs or get_prefs()
    if current_install_is_pro(prefs):
        return True, ""
    try:
        consume = consume_paid_access(kind, frame_count=frame_count, prefs=prefs)
        if bool(consume.get("allowed")):
            return True, ""
    except AuthApiError as exc:
        if int(getattr(exc, "status", 0) or 0) != 402:
            raise
    checkout = create_checkout(kind, frame_count=frame_count, prefs=prefs)
    if checkout.get("paid") and not checkout.get("required"):
        return True, ""
    checkout_url = str(checkout.get("checkout_url", "") or "").strip()
    if not checkout_url:
        raise AuthApiError(503, "checkout_unavailable", payload=checkout)
    webbrowser.open(checkout_url)
    return False, "Planetka checkout opened. Complete payment, then press the button again."
