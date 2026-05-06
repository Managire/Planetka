"""Client helpers for the experimental land-credit backend."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from .auth import AuthApiError, get_api_base_url, get_authorized_headers, refresh_auth_session


logger = logging.getLogger(__name__)

_ACCOUNT_CACHE = {"timestamp": 0.0, "payload": {}}
_UNLOCKED_CACHE = {"timestamp": 0.0, "payload": []}
_REGION_OFFERS_CACHE = {"timestamp": 0.0, "key": "", "payload": []}
_ACCOUNT_CACHE_TTL_SECONDS = 5.0
_UNLOCKED_CACHE_TTL_SECONDS = 10.0
_REGION_OFFERS_CACHE_TTL_SECONDS = 30.0
_UNLOCKED_DOWNLOAD_LOCK = threading.Lock()
_UNLOCKED_DOWNLOAD_CANCEL = None
_UNLOCKED_DOWNLOAD_THREAD = None
_UNLOCKED_DOWNLOAD_PLANS = {}
_UNLOCKED_DOWNLOAD_PROGRESS = {
    "active": False,
    "status": "IDLE",
    "message": "",
    "period": "ALL",
    "period_label": "all data",
    "directory": "",
    "total_bytes": 0,
    "downloaded_bytes": 0,
    "downloaded_files": 0,
    "total_files": 0,
    "selected_tiles": 0,
    "missing_files": 0,
    "skipped_existing_files": 0,
    "error": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}

_PRICE_FIELDS = {
    "credits",
    "credits_spent",
    "price_eur",
    "gross_credits",
    "gross_price_eur",
    "upgrade_credit_applied",
    "paid_eur",
    "nominal_eur",
    "gross_eur",
    "discount_eur",
    "minimum_eur",
    "added_eur",
    "added_credits",
}
_CENT = Decimal("0.01")
_TILE_RE = re.compile(r"x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})", re.IGNORECASE)
_ASSET_RE = re.compile(r"^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$", re.IGNORECASE)


class CreditApiError(RuntimeError):
    def __init__(self, status=0, error="", payload=None):
        super().__init__(str(error or f"http_{status}"))
        self.status = int(status or 0)
        self.error = str(error or f"http_{status}")
        self.payload = payload if isinstance(payload, dict) else {}


def _api_url(path: str) -> str:
    return f"{get_api_base_url().rstrip('/')}/{str(path or '').lstrip('/')}"


def _money_round(value) -> float:
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0
    if amount <= 0:
        return 0.0
    return float(amount.quantize(_CENT, rounding=ROUND_HALF_UP))


def _normalize_tile_key(value) -> str:
    if isinstance(value, dict):
        raw = str(value.get("tile_key") or value.get("tileKey") or value.get("key") or "").strip()
    else:
        raw = str(value or "").strip()
    asset_match = _ASSET_RE.match(os.path.basename(raw))
    source = asset_match.group(1) if asset_match else raw
    match = _TILE_RE.search(source)
    if not match:
        return ""
    x, y, z, d = (int(part) for part in match.groups())
    return f"x{x:03d}_y{y:03d}_z{z:03d}_d{d:03d}"


def _normalize_tile_keys(tiles) -> list[str]:
    keys = []
    seen = set()
    for entry in tiles or ():
        key = _normalize_tile_key(entry)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _summarize_pricing_rows(rows) -> dict:
    total = 0.0
    paid = 0
    free = 0
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        credits = _money_round(row.get("credits", row.get("price_eur", 0.0)))
        total = _money_round(total + credits)
        if credits > 0:
            paid += 1
        else:
            free += 1
    return {
        "credits": _money_round(total),
        "paid_tile_count": int(paid),
        "free_tile_count": int(free),
        "tile_count": int(paid + free),
    }


def _zero_backend_unavailable_payload(tile_keys, reason="backend_unavailable") -> dict:
    safe_keys = _normalize_tile_keys(tile_keys)
    return {
        "credits": 0.0,
        "paid_tile_count": 0,
        "free_tile_count": 0,
        "tile_count": int(len(safe_keys)),
        "tiles": [{"tile_key": key} for key in safe_keys],
        "excluded_tiles": [],
        "authoritative": False,
        "pricing_source": reason,
    }


def _log_pricing_integrity_warnings(payload):
    if not isinstance(payload, dict):
        return
    warnings = payload.get("integrity_warnings") or payload.get("integrityWarnings") or ()
    if not isinstance(warnings, (list, tuple)):
        warnings = ()
    missing = []
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        code = str(warning.get("code", "") or "").strip()
        if code != "pricing_metadata_missing":
            continue
        keys = warning.get("tile_keys") or warning.get("tileKeys") or ()
        if isinstance(keys, (list, tuple)):
            missing.extend(str(key or "").strip() for key in keys if str(key or "").strip())
    direct = payload.get("metadata_missing_tile_keys") or payload.get("metadataMissingTileKeys") or ()
    if isinstance(direct, (list, tuple)):
        missing.extend(str(key or "").strip() for key in direct if str(key or "").strip())
    missing = sorted(set(missing))
    if missing:
        logger.error(
            "Planetka pricing integrity warning: backend missing pricing metadata for %d actual Resolve tile(s): %s",
            len(missing),
            ", ".join(missing[:20]),
        )


def _request_json(method: str, path: str, body=None, allow_refresh=True, timeout=30):
    payload = None
    headers = {
        "User-Agent": "Planetka-Blender",
        **get_authorized_headers(allow_refresh=allow_refresh),
    }
    if body is not None:
        payload = json.dumps(body, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(_api_url(path), method=str(method or "GET").upper(), headers=headers, data=payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read() or b"{}"
        text = raw.decode("utf-8", errors="replace")
        return json.loads(text or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b"{}"
        text = raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(text or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {"error": text or f"http_{exc.code}"}
        if int(getattr(exc, "code", 0) or 0) == 401 and allow_refresh:
            try:
                refresh_auth_session()
                return _request_json(method, path, body=body, allow_refresh=False, timeout=timeout)
            except AuthApiError as refresh_error:
                raise CreditApiError(exc.code, data.get("error") or "auth_failed", payload=data) from refresh_error
        raise CreditApiError(exc.code, data.get("error") or f"http_{exc.code}", payload=data) from exc
    except urllib.error.URLError as exc:
        raise CreditApiError(0, f"network_error_{exc.reason}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreditApiError(0, "invalid_json_response") from exc


def _round_price_fields(entry):
    if not isinstance(entry, dict):
        return entry
    out = dict(entry)
    for field in _PRICE_FIELDS:
        if field in out:
            out[field] = _money_round(out.get(field, 0.0))
    return out


def _signed_money_round(value):
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if amount < 0:
        return -_money_round(abs(amount))
    return _money_round(amount)


def _normalize_account_payload(payload):
    if not isinstance(payload, dict):
        return {}
    out = dict(payload)
    for field in ("balance_credits", "balance_eur", "total_granted_credits", "total_spent_credits"):
        if field in out:
            out[field] = _signed_money_round(out.get(field, 0.0))
    return out


def clear_credit_caches():
    _ACCOUNT_CACHE["timestamp"] = 0.0
    _ACCOUNT_CACHE["payload"] = {}
    _UNLOCKED_CACHE["timestamp"] = 0.0
    _UNLOCKED_CACHE["payload"] = []
    _REGION_OFFERS_CACHE["timestamp"] = 0.0
    _REGION_OFFERS_CACHE["key"] = ""
    _REGION_OFFERS_CACHE["payload"] = []


def get_credit_account(force=False) -> dict:
    now = time.monotonic()
    payload = _ACCOUNT_CACHE.get("payload")
    if (
        not force
        and isinstance(payload, dict)
        and payload
        and (now - float(_ACCOUNT_CACHE.get("timestamp", 0.0) or 0.0)) < _ACCOUNT_CACHE_TTL_SECONDS
    ):
        return dict(payload) if isinstance(payload, dict) else {}
    try:
        payload = _request_json("GET", "/credits/me", timeout=15)
    except (AuthApiError, CreditApiError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed fetching credit account", exc_info=True)
        return {}
    payload = _normalize_account_payload(payload)
    _ACCOUNT_CACHE["timestamp"] = now
    _ACCOUNT_CACHE["payload"] = dict(payload or {})
    return dict(payload or {})


def has_standard_quality_access_cached() -> bool:
    account = _ACCOUNT_CACHE.get("payload")
    if not isinstance(account, dict) or not account:
        return False
    return bool(
        account.get("standard_quality_unlocked", False)
        or account.get("balanced_quality_unlocked", False)
        or str(account.get("standard_quality_unlocked_at", "") or "").strip()
        or str(account.get("balanced_quality_unlocked_at", "") or "").strip()
    )


def has_standard_quality_access(force=False) -> bool:
    account = get_credit_account(force=bool(force))
    if not isinstance(account, dict):
        return False
    return bool(
        account.get("standard_quality_unlocked", False)
        or account.get("balanced_quality_unlocked", False)
        or str(account.get("standard_quality_unlocked_at", "") or "").strip()
        or str(account.get("balanced_quality_unlocked_at", "") or "").strip()
    )


def get_unlocked_tiles(force=False) -> list[dict]:
    now = time.monotonic()
    payload = _UNLOCKED_CACHE.get("payload")
    if (
        not force
        and isinstance(payload, list)
        and (now - float(_UNLOCKED_CACHE.get("timestamp", 0.0) or 0.0)) < _UNLOCKED_CACHE_TTL_SECONDS
    ):
        return list(payload) if isinstance(payload, list) else []
    try:
        payload = _request_json("GET", "/credits/unlocked", timeout=30)
    except (AuthApiError, CreditApiError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed fetching unlocked tile list", exc_info=True)
        return []
    tiles = payload.get("tiles", []) if isinstance(payload, dict) else []
    if not isinstance(tiles, list):
        tiles = []
    tiles = [_round_price_fields(entry) for entry in tiles]
    _UNLOCKED_CACHE["timestamp"] = now
    _UNLOCKED_CACHE["payload"] = list(tiles)
    return list(tiles)


def unlocked_tile_keys(force=False) -> set[str]:
    keys = set()
    for entry in get_unlocked_tiles(force=force):
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("tile_key", "") or "").strip()
        if key:
            keys.add(key)
    return keys


def build_pricing_payload_for_tiles(tiles, quality_mode="FULL") -> list[dict]:
    mode = str(quality_mode or "FULL").strip().lower()
    return [{"tile_key": key, "quality_mode": mode} for key in _normalize_tile_keys(tiles)]


def estimate_credits_for_tiles(tiles, quality_mode="FULL") -> dict:
    tile_keys = _normalize_tile_keys(tiles)
    if not tile_keys:
        return {
            "credits": 0.0,
            "paid_tile_count": 0,
            "free_tile_count": 0,
            "tile_count": 0,
            "tiles": [],
            "excluded_tiles": [],
            "authoritative": True,
            "pricing_source": "backend",
        }
    try:
        payload = _request_json(
            "POST",
            "/credits/estimate",
            body={
                "quality_mode": str(quality_mode or "FULL").strip().lower(),
                "tile_keys": tile_keys,
            },
            timeout=20,
        )
    except (AuthApiError, CreditApiError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: backend credit estimate unavailable; no local pricing fallback is allowed", exc_info=True)
        return _zero_backend_unavailable_payload(tile_keys, reason="backend_unavailable")
    if not isinstance(payload, dict) or not payload.get("ok", False):
        return _zero_backend_unavailable_payload(tile_keys, reason="backend_rejected")
    _log_pricing_integrity_warnings(payload)
    if "balance_credits" in payload:
        cached_account = dict(_ACCOUNT_CACHE.get("payload") or {})
        account_update = {
            "ok": True,
            "account_type": str(payload.get("account_type", "standard") or "standard"),
            "unlimited_credits": bool(payload.get("unlimited_credits", False)),
            "balance_credits": _signed_money_round(payload.get("balance_credits", 0.0)),
            "balance_eur": _signed_money_round(payload.get("balance_eur", payload.get("balance_credits", 0.0))),
        }
        for key in (
            "unlocked_tile_count",
            "standard_quality_unlocked",
            "standard_quality_unlocked_at",
            "standard_quality_price_eur",
            "balanced_quality_unlocked",
            "balanced_quality_unlocked_at",
            "balanced_quality_price_eur",
        ):
            if key in payload:
                account_update[key] = payload.get(key)
        _ACCOUNT_CACHE["timestamp"] = time.monotonic()
        _ACCOUNT_CACHE["payload"] = _normalize_account_payload({**cached_account, **account_update})
    payload_tiles = [_round_price_fields(entry) for entry in list(payload.get("tiles", ()) or ())]
    returned_keys = {
        str(entry.get("tile_key", "") or "").strip()
        for entry in payload_tiles
        if isinstance(entry, dict) and str(entry.get("tile_key", "") or "").strip()
    }
    missing_response_keys = [key for key in tile_keys if key not in returned_keys]
    if missing_response_keys:
        logger.error(
            "Planetka pricing integrity warning: backend response omitted %d requested tile price row(s): %s",
            len(missing_response_keys),
            ", ".join(missing_response_keys[:20]),
        )
        return _zero_backend_unavailable_payload(tile_keys, reason="backend_incomplete")
    payload_summary = _summarize_pricing_rows(payload_tiles)
    return {
        "credits": _money_round(payload_summary.get("credits", 0.0)),
        "paid_tile_count": int(payload_summary.get("paid_tile_count", 0) or 0),
        "free_tile_count": int(payload_summary.get("free_tile_count", 0) or 0),
        "tile_count": int(payload_summary.get("tile_count", len(payload_tiles)) or 0),
        "balance_credits": _signed_money_round(payload.get("balance_eur", payload.get("balance_credits", 0.0))),
        "tiles": payload_tiles,
        "excluded_tiles": [_round_price_fields(entry) for entry in list(payload.get("excluded_tiles", ()) or ())],
        "authoritative": True,
        "pricing_source": "backend",
    }


def estimate_credit_breakdown_for_tiles(tiles, quality_mode="FULL") -> dict:
    mode = str(quality_mode or "FULL").strip().upper()
    if mode in {"PREVIEW", "BALANCED", "HALF"}:
        normalized_tiles = _normalize_tile_keys(tiles)
        free_reason = "standard_quality_unlock" if mode in {"BALANCED", "HALF"} else "preview_quality"
        return {
            "credits": 0.0,
            "paid_tile_count": 0,
            "free_tile_count": int(len(normalized_tiles)),
            "tile_count": int(len(normalized_tiles)),
            "tiles": [
                {
                    "tile_key": tile,
                    "credits": 0.0,
                    "gross_credits": 0.0,
                    "free_reason": free_reason,
                    "already_owned": False,
                }
                for tile in normalized_tiles
            ],
            "excluded_tiles": [],
            "authoritative": True,
            "pricing_source": "preview_free",
        }
    return estimate_credits_for_tiles(tiles, quality_mode=mode)


def get_region_pack_offers(latitude_deg, longitude_deg, force=False) -> list[dict]:
    try:
        lat = max(-90.0, min(90.0, float(latitude_deg or 0.0)))
        lon = max(-180.0, min(180.0, float(longitude_deg or 0.0)))
    except (TypeError, ValueError):
        return []
    key = f"{round(lat, 3):.3f}:{round(lon, 3):.3f}"
    now = time.monotonic()
    cached = _REGION_OFFERS_CACHE.get("payload")
    if (
        not force
        and _REGION_OFFERS_CACHE.get("key") == key
        and isinstance(cached, list)
        and (now - float(_REGION_OFFERS_CACHE.get("timestamp", 0.0) or 0.0)) < _REGION_OFFERS_CACHE_TTL_SECONDS
    ):
        return [dict(item) for item in cached if isinstance(item, dict)]
    try:
        payload = _request_json(
            "POST",
            "/credits/region-offers",
            body={"latitude_deg": lat, "longitude_deg": lon},
            timeout=45,
        )
    except (AuthApiError, CreditApiError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed fetching region pack offers", exc_info=True)
        return []
    offers = payload.get("offers", []) if isinstance(payload, dict) else []
    if not isinstance(offers, list):
        offers = []
    offers = [_round_price_fields(entry) for entry in offers if isinstance(entry, dict)]
    _REGION_OFFERS_CACHE["timestamp"] = now
    _REGION_OFFERS_CACHE["key"] = key
    _REGION_OFFERS_CACHE["payload"] = [dict(item) for item in offers]
    return [dict(item) for item in offers]


def create_checkout_session(option: str, tiles=None, quality_mode="FULL", region_pack_id: str = "") -> dict:
    """Create a Stripe Checkout Session for scene data or a fixed balance top-up."""
    safe_option = str(option or "scene").strip().lower()
    if safe_option not in {
        "scene",
        "balance_10",
        "top_up_10",
        "topup_10",
        "standard_unlock",
        "balanced_unlock",
        "region_pack",
        "broader_pack",
    }:
        safe_option = "scene"
    tile_keys = []
    if safe_option == "scene":
        for entry in list(tiles or ()):
            if isinstance(entry, dict):
                key = str(entry.get("tile_key") or entry.get("tileKey") or entry.get("key") or "").strip()
            else:
                key = str(entry or "").strip()
            if key and key not in tile_keys:
                tile_keys.append(key)
    payload = {
        "option": (
            "balance_10"
            if safe_option in {"balance_10", "top_up_10", "topup_10"}
            else (
                "standard_unlock"
                if safe_option in {"standard_unlock", "balanced_unlock"}
                else ("region_pack" if safe_option in {"region_pack", "broader_pack"} else "scene")
            )
        ),
        "quality_mode": str(quality_mode or "FULL").strip().lower(),
        "tile_keys": tile_keys,
    }
    if safe_option in {"region_pack", "broader_pack"}:
        payload["region_pack_id"] = str(region_pack_id or "").strip()
    result = _request_json("POST", "/credits/checkout", body=payload, timeout=30)
    if isinstance(result, dict) and result.get("ok", False):
        normalized = _round_price_fields(result)
        if "balance_credits" in normalized or "balance_eur" in normalized:
            normalized = _normalize_account_payload(normalized)
        return dict(normalized)
    error = "checkout_create_failed"
    if isinstance(result, dict):
        error = str(result.get("error", "") or error)
    raise CreditApiError(0, error, payload=result if isinstance(result, dict) else {})


def _parse_unlocked_at(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def _period_label(period: str) -> str:
    token = str(period or "ALL").strip().upper()
    if token == "TODAY":
        return "today"
    if token == "THIS_WEEK":
        return "this week"
    if token == "THIS_MONTH":
        return "this month"
    return "all data"


def _entry_matches_download_period(entry, period: str) -> bool:
    token = str(period or "ALL").strip().upper()
    if token in {"", "ALL"}:
        return True
    unlocked_at = _parse_unlocked_at(entry.get("unlocked_at", "") if isinstance(entry, dict) else "")
    if unlocked_at is None:
        return False
    now = datetime.now().astimezone()
    if token == "TODAY":
        return unlocked_at.date() == now.date()
    if token == "THIS_WEEK":
        return unlocked_at.isocalendar().year == now.isocalendar().year and unlocked_at.isocalendar().week == now.isocalendar().week
    if token == "THIS_MONTH":
        return unlocked_at.year == now.year and unlocked_at.month == now.month
    return True


def _is_usable_file(path: str) -> bool:
    try:
        return bool(os.path.isfile(path) and os.path.getsize(path) > 0)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _asset_target_path(directory: str, folder: str, file_name: str) -> str:
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return ""
    return os.path.join(directory, safe_folder, safe_name)


def _safe_asset_size(folder: str, file_name: str) -> int:
    try:
        from .r2_source import texture_asset_size_bytes
        size = texture_asset_size_bytes(folder, file_name, allow_remote_probe=False)
        return int(max(0, int(size or 0)))
    except (ImportError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed estimating unlocked asset size", exc_info=True)
        return 0


def _download_period_sorted_entries(period: str) -> tuple[list[dict], int]:
    entries = []
    scanned = 0
    for entry in get_unlocked_tiles(force=True):
        if not isinstance(entry, dict):
            continue
        scanned += 1
        if _entry_matches_download_period(entry, period):
            entries.append(dict(entry))
    return entries, scanned


def prepare_unlocked_download_plan(directory: str, period: str = "ALL") -> dict:
    target = os.path.abspath(os.path.expanduser(str(directory or "").strip()))
    if not target:
        raise CreditApiError(400, "missing_directory")
    selected_entries, scanned_tiles = _download_period_sorted_entries(period)
    assets_to_download = []
    selected_tiles = 0
    total_bytes = 0
    skipped_existing = 0
    missing_size = 0
    seen_assets = set()
    for entry in selected_entries:
        tile_key = str(entry.get("tile_key", "") or "").strip()
        if not tile_key:
            continue
        selected_tiles += 1
        assets = entry.get("assets", ())
        if not isinstance(assets, (list, tuple)):
            continue
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            folder = str(asset.get("folder", "") or "").strip()
            file_name = str(asset.get("file_name", "") or "").strip()
            target_path = _asset_target_path(target, folder, file_name)
            if not folder or not file_name or not target_path:
                continue
            dedupe_key = f"{folder}/{os.path.basename(file_name)}"
            if dedupe_key in seen_assets:
                continue
            seen_assets.add(dedupe_key)
            if _is_usable_file(target_path):
                skipped_existing += 1
                continue
            size_bytes = _safe_asset_size(folder, file_name)
            if size_bytes <= 0:
                missing_size += 1
            total_bytes += int(max(0, size_bytes))
            assets_to_download.append(
                {
                    "tile_key": tile_key,
                    "folder": folder,
                    "file_name": os.path.basename(file_name),
                    "target_path": target_path,
                    "size_bytes": int(max(0, size_bytes)),
                }
            )
    plan_id = uuid4().hex
    plan = {
        "plan_id": plan_id,
        "directory": target,
        "period": str(period or "ALL").strip().upper() or "ALL",
        "period_label": _period_label(period),
        "scanned_tiles": int(scanned_tiles),
        "selected_tiles": int(selected_tiles),
        "assets": assets_to_download,
        "total_files": int(len(assets_to_download)),
        "total_bytes": int(max(0, total_bytes)),
        "skipped_existing_files": int(skipped_existing),
        "missing_size_files": int(missing_size),
    }
    with _UNLOCKED_DOWNLOAD_LOCK:
        _UNLOCKED_DOWNLOAD_PLANS[plan_id] = dict(plan)
    return dict(plan)


def _set_unlocked_download_progress(**updates):
    with _UNLOCKED_DOWNLOAD_LOCK:
        _UNLOCKED_DOWNLOAD_PROGRESS.update(updates)
        return dict(_UNLOCKED_DOWNLOAD_PROGRESS)


def get_unlocked_download_progress() -> dict:
    with _UNLOCKED_DOWNLOAD_LOCK:
        return dict(_UNLOCKED_DOWNLOAD_PROGRESS)


def is_unlocked_download_active() -> bool:
    with _UNLOCKED_DOWNLOAD_LOCK:
        return bool(_UNLOCKED_DOWNLOAD_PROGRESS.get("active", False))


def cancel_unlocked_download() -> bool:
    with _UNLOCKED_DOWNLOAD_LOCK:
        event = _UNLOCKED_DOWNLOAD_CANCEL
        active = bool(_UNLOCKED_DOWNLOAD_PROGRESS.get("active", False))
        if event is not None:
            try:
                event.set()
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
        if active:
            _UNLOCKED_DOWNLOAD_PROGRESS["message"] = "Cancelling licenced tile download..."
            _UNLOCKED_DOWNLOAD_PROGRESS["status"] = "CANCELLING"
        return active


def _write_asset_metadata_sidecar(path: str, folder: str, file_name: str) -> None:
    try:
        from .r2_source import remote_asset_metadata
        metadata = remote_asset_metadata(folder, file_name)
    except (ImportError, RuntimeError, TypeError, ValueError, OSError):
        metadata = {}
    if not metadata:
        return
    try:
        with open(f"{path}.planetka.json", "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, sort_keys=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed writing local source metadata sidecar", exc_info=True)


def _run_unlocked_download_plan(plan: dict, cancel_event: threading.Event) -> None:
    downloaded_files = 0
    missing_files = 0
    downloaded_bytes = 0
    total_bytes = int(max(0, int(plan.get("total_bytes", 0) or 0)))
    total_files = int(max(0, int(plan.get("total_files", 0) or 0)))
    selected_tiles = int(max(0, int(plan.get("selected_tiles", 0) or 0)))
    skipped_existing_files = int(max(0, int(plan.get("skipped_existing_files", 0) or 0)))

    def progress_callback(delta_bytes: int, _total_bytes: int) -> None:
        nonlocal downloaded_bytes
        if cancel_event.is_set():
            return
        downloaded_bytes += int(max(0, int(delta_bytes or 0)))
        _set_unlocked_download_progress(
            downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
            message="Downloading licenced tiles...",
        )

    try:
        from .r2_source import clear_local_source_stale_notice, download_remote_asset_to_path
        assets = list(plan.get("assets", ()) or ())
        _set_unlocked_download_progress(
            active=True,
            status="RUNNING",
            message="Downloading licenced tiles...",
            period=str(plan.get("period", "ALL") or "ALL"),
            period_label=str(plan.get("period_label", "") or "all data"),
            directory=str(plan.get("directory", "") or ""),
            total_bytes=total_bytes,
            downloaded_bytes=0,
            downloaded_files=0,
            total_files=total_files,
            selected_tiles=selected_tiles,
            missing_files=0,
            skipped_existing_files=skipped_existing_files,
            error="",
            started_at=time.monotonic(),
            finished_at=0.0,
        )
        for asset in assets:
            if cancel_event.is_set():
                raise RuntimeError("cancelled")
            folder = str(asset.get("folder", "") or "")
            file_name = str(asset.get("file_name", "") or "")
            target_path = str(asset.get("target_path", "") or "")
            tile_key = str(asset.get("tile_key", "") or "")
            if not folder or not file_name or not target_path:
                continue
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            ok = download_remote_asset_to_path(
                folder,
                file_name,
                target_path,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
                texture_quality_mode="FULL",
                resolve_id=f"download-unlocked-{uuid4().hex[:12]}",
                pricing_tiles=[tile_key] if tile_key else (),
                track_global_progress=False,
            )
            if cancel_event.is_set():
                raise RuntimeError("cancelled")
            if not ok or not _is_usable_file(target_path):
                missing_files += 1
                _set_unlocked_download_progress(missing_files=missing_files)
                continue
            _write_asset_metadata_sidecar(target_path, folder, file_name)
            downloaded_files += 1
            expected_size = int(max(0, int(asset.get("size_bytes", 0) or 0)))
            if expected_size > 0 and downloaded_bytes < sum(
                int(max(0, int(item.get("size_bytes", 0) or 0)))
                for item in assets[:downloaded_files]
            ):
                downloaded_bytes = min(total_bytes, downloaded_bytes + expected_size)
            _set_unlocked_download_progress(
                downloaded_files=downloaded_files,
                downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
            )
        clear_local_source_stale_notice()
        if total_files <= 0 and skipped_existing_files > 0:
            message = "Licenced tile files already downloaded."
        elif total_files <= 0 and selected_tiles <= 0:
            message = "No licenced tiles found for this range."
        elif total_files <= 0:
            message = "No downloadable files found for licenced tiles."
        else:
            message = "Licenced tile download complete."
        _set_unlocked_download_progress(
            active=False,
            status="FINISHED",
            message=message,
            downloaded_files=downloaded_files,
            missing_files=missing_files,
            downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
            finished_at=time.monotonic(),
        )
    except RuntimeError as exc:
        if str(exc).strip().lower() == "cancelled" or cancel_event.is_set():
            _set_unlocked_download_progress(
                active=False,
                status="CANCELLED",
                message="Licenced tile download cancelled.",
                downloaded_files=downloaded_files,
                missing_files=missing_files,
                downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
                finished_at=time.monotonic(),
            )
            return
        _set_unlocked_download_progress(
            active=False,
            status="ERROR",
            message="Licenced tile download failed.",
            error=str(exc),
            downloaded_files=downloaded_files,
            missing_files=missing_files,
            downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
            finished_at=time.monotonic(),
        )
        logger.debug("Planetka: unlocked tile download failed", exc_info=True)
    except Exception as exc:
        _set_unlocked_download_progress(
            active=False,
            status="ERROR",
            message="Licenced tile download failed.",
            error=str(exc),
            downloaded_files=downloaded_files,
            missing_files=missing_files,
            downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
            finished_at=time.monotonic(),
        )
        logger.debug("Planetka: unlocked tile download failed", exc_info=True)


def start_unlocked_download_plan(plan_id: str) -> dict:
    global _UNLOCKED_DOWNLOAD_CANCEL
    global _UNLOCKED_DOWNLOAD_THREAD
    with _UNLOCKED_DOWNLOAD_LOCK:
        if bool(_UNLOCKED_DOWNLOAD_PROGRESS.get("active", False)):
            raise CreditApiError(409, "download_already_running")
        plan = _UNLOCKED_DOWNLOAD_PLANS.pop(str(plan_id or ""), None)
        if not isinstance(plan, dict):
            raise CreditApiError(404, "download_plan_not_found")
        cancel_event = threading.Event()
        _UNLOCKED_DOWNLOAD_CANCEL = cancel_event
        thread = threading.Thread(
            target=_run_unlocked_download_plan,
            args=(dict(plan), cancel_event),
            name="PlanetkaUnlockedDownload",
            daemon=True,
        )
        _UNLOCKED_DOWNLOAD_THREAD = thread
        _UNLOCKED_DOWNLOAD_PROGRESS.update(
            {
                "active": True,
                "status": "STARTING",
                "message": "Starting licenced tile download...",
                "period": str(plan.get("period", "ALL") or "ALL"),
                "period_label": str(plan.get("period_label", "") or "all data"),
                "directory": str(plan.get("directory", "") or ""),
                "total_bytes": int(plan.get("total_bytes", 0) or 0),
                "downloaded_bytes": 0,
                "downloaded_files": 0,
                "total_files": int(plan.get("total_files", 0) or 0),
                "selected_tiles": int(plan.get("selected_tiles", 0) or 0),
                "missing_files": 0,
                "skipped_existing_files": int(plan.get("skipped_existing_files", 0) or 0),
                "error": "",
                "started_at": time.monotonic(),
                "finished_at": 0.0,
            }
        )
    thread.start()
    return get_unlocked_download_progress()


def download_unlocked_tiles_to_directory(directory: str, period: str = "ALL") -> dict:
    """Download all licenced assets to a user-selected local source directory."""
    target = os.path.abspath(os.path.expanduser(str(directory or "")))
    if not target:
        raise CreditApiError(400, "missing_directory")
    os.makedirs(target, exist_ok=True)

    # Lazy import avoids r2_source importing credit_api back through session token setup.
    from .r2_source import clear_local_source_stale_notice, remote_asset_metadata, resolve_remote_asset

    downloaded = 0
    missing = 0
    scanned_tiles = 0
    selected_tiles = 0
    for entry in get_unlocked_tiles(force=True):
        if not isinstance(entry, dict):
            continue
        scanned_tiles += 1
        if not _entry_matches_download_period(entry, period):
            continue
        selected_tiles += 1
        assets = entry.get("assets", ())
        if not isinstance(assets, (list, tuple)):
            assets = ()
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            folder = str(asset.get("folder", "") or "").strip()
            file_name = str(asset.get("file_name", "") or "").strip()
            if not folder or not file_name:
                continue
            source_path = resolve_remote_asset(folder, file_name)
            if not source_path or not os.path.isfile(source_path):
                missing += 1
                continue
            out_dir = os.path.join(target, folder)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, os.path.basename(file_name))
            if os.path.abspath(source_path) != os.path.abspath(out_path):
                with open(source_path, "rb") as src, open(out_path, "wb") as dst:
                    while True:
                        chunk = src.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
            metadata = remote_asset_metadata(folder, file_name)
            if metadata:
                try:
                    with open(f"{out_path}.planetka.json", "w", encoding="utf-8") as handle:
                        json.dump(metadata, handle, sort_keys=True)
                except (OSError, RuntimeError, TypeError, ValueError):
                    logger.debug("Planetka: failed writing local source metadata sidecar", exc_info=True)
            downloaded += 1
    clear_local_source_stale_notice()
    return {
        "downloaded_files": int(downloaded),
        "missing_files": int(missing),
        "directory": target,
        "period": str(period or "ALL").strip().upper() or "ALL",
        "period_label": _period_label(period),
        "scanned_tiles": int(scanned_tiles),
        "selected_tiles": int(selected_tiles),
    }
