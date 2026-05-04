"""Client helpers for the experimental land-credit backend."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .auth import AuthApiError, get_api_base_url, get_authorized_headers, refresh_auth_session
from .land_credits import pricing_records_for_tiles, summarize_pricing_records


logger = logging.getLogger(__name__)

_ACCOUNT_CACHE = {"timestamp": 0.0, "payload": {}}
_UNLOCKED_CACHE = {"timestamp": 0.0, "payload": []}


class CreditApiError(RuntimeError):
    def __init__(self, status=0, error="", payload=None):
        super().__init__(str(error or f"http_{status}"))
        self.status = int(status or 0)
        self.error = str(error or f"http_{status}")
        self.payload = payload if isinstance(payload, dict) else {}


def _api_url(path: str) -> str:
    return f"{get_api_base_url().rstrip('/')}/{str(path or '').lstrip('/')}"


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


def clear_credit_caches():
    _ACCOUNT_CACHE["timestamp"] = 0.0
    _ACCOUNT_CACHE["payload"] = {}
    _UNLOCKED_CACHE["timestamp"] = 0.0
    _UNLOCKED_CACHE["payload"] = []


def get_credit_account(force=False) -> dict:
    now = time.monotonic()
    if not force:
        payload = _ACCOUNT_CACHE.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}
    try:
        payload = _request_json("GET", "/credits/me", timeout=15)
    except (AuthApiError, CreditApiError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed fetching credit account", exc_info=True)
        return {}
    _ACCOUNT_CACHE["timestamp"] = now
    _ACCOUNT_CACHE["payload"] = dict(payload or {})
    return dict(payload or {})


def get_unlocked_tiles(force=False) -> list[dict]:
    now = time.monotonic()
    if not force:
        payload = _UNLOCKED_CACHE.get("payload")
        return list(payload) if isinstance(payload, list) else []
    try:
        payload = _request_json("GET", "/credits/unlocked", timeout=30)
    except (AuthApiError, CreditApiError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: failed fetching unlocked tile list", exc_info=True)
        return []
    tiles = payload.get("tiles", []) if isinstance(payload, dict) else []
    if not isinstance(tiles, list):
        tiles = []
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
    return pricing_records_for_tiles(
        tiles,
        quality_mode=quality_mode,
        owned_tile_keys=unlocked_tile_keys(force=False),
        allow_estimate=True,
    )


def estimate_credits_for_tiles(tiles, quality_mode="FULL") -> dict:
    pricing_tiles = build_pricing_payload_for_tiles(tiles, quality_mode=quality_mode)
    fallback_summary = summarize_pricing_records(pricing_tiles)
    if not pricing_tiles:
        return dict(fallback_summary)
    try:
        payload = _request_json(
            "POST",
            "/credits/estimate",
            body={
                "quality_mode": str(quality_mode or "FULL").strip().lower(),
                "tiles": pricing_tiles,
            },
            timeout=20,
        )
    except (AuthApiError, CreditApiError, RuntimeError, TypeError, ValueError, OSError):
        logger.debug("Planetka: backend credit estimate unavailable; using local estimate", exc_info=True)
        return dict(fallback_summary)
    if not isinstance(payload, dict) or not payload.get("ok", False):
        return dict(fallback_summary)
    return {
        "credits": float(payload.get("credits", fallback_summary.get("credits", 0.0)) or 0.0),
        "paid_tile_count": int(payload.get("paid_tile_count", fallback_summary.get("paid_tile_count", 0)) or 0),
        "free_tile_count": int(payload.get("free_tile_count", fallback_summary.get("free_tile_count", 0)) or 0),
        "tile_count": int(payload.get("tile_count", fallback_summary.get("tile_count", 0)) or 0),
        "balance_credits": float(payload.get("balance_credits", 0.0) or 0.0),
    }


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


def download_unlocked_tiles_to_directory(directory: str, period: str = "ALL") -> dict:
    """Download all unlocked assets to a user-selected local source directory."""
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
