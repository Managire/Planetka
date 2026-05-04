"""Client helpers for the experimental land-credit backend."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

from .auth import AuthApiError, get_api_base_url, get_authorized_headers, refresh_auth_session
from .land_credits import pricing_records_for_tiles, summarize_pricing_records


logger = logging.getLogger(__name__)

_ACCOUNT_CACHE = {"timestamp": 0.0, "payload": {}}
_UNLOCKED_CACHE = {"timestamp": 0.0, "payload": []}
_ACCOUNT_CACHE_TTL_SECONDS = 5.0
_UNLOCKED_CACHE_TTL_SECONDS = 10.0
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
    _ACCOUNT_CACHE["timestamp"] = now
    _ACCOUNT_CACHE["payload"] = dict(payload or {})
    return dict(payload or {})


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
    fallback_payload = {
        **dict(fallback_summary),
        "tiles": list(pricing_tiles or ()),
        "excluded_tiles": [
            dict(entry)
            for entry in pricing_tiles
            if isinstance(entry, dict)
            and float(entry.get("credits", 0.0) or 0.0) <= 0.0
            and str(entry.get("free_reason", "") or "").strip() == "already_unlocked"
        ],
    }
    tile_keys = [
        str(entry.get("tile_key", "") or "").strip()
        for entry in pricing_tiles
        if isinstance(entry, dict) and str(entry.get("tile_key", "") or "").strip()
    ]
    if not tile_keys:
        return dict(fallback_payload)
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
        logger.debug("Planetka: backend credit estimate unavailable; using local estimate", exc_info=True)
        return dict(fallback_payload)
    if not isinstance(payload, dict) or not payload.get("ok", False):
        return dict(fallback_payload)
    if "balance_credits" in payload:
        _ACCOUNT_CACHE["timestamp"] = time.monotonic()
        _ACCOUNT_CACHE["payload"] = {
            **dict(_ACCOUNT_CACHE.get("payload") or {}),
            "ok": True,
            "account_type": str(payload.get("account_type", "standard") or "standard"),
            "unlimited_credits": bool(payload.get("unlimited_credits", False)),
            "balance_credits": float(payload.get("balance_credits", 0.0) or 0.0),
        }
    return {
        "credits": float(payload.get("price_eur", payload.get("credits", fallback_summary.get("credits", 0.0))) or 0.0),
        "paid_tile_count": int(payload.get("paid_tile_count", fallback_summary.get("paid_tile_count", 0)) or 0),
        "free_tile_count": int(payload.get("free_tile_count", fallback_summary.get("free_tile_count", 0)) or 0),
        "tile_count": int(payload.get("tile_count", fallback_summary.get("tile_count", 0)) or 0),
        "balance_credits": float(payload.get("balance_eur", payload.get("balance_credits", 0.0)) or 0.0),
        "tiles": list(payload.get("tiles", pricing_tiles) or ()),
        "excluded_tiles": list(payload.get("excluded_tiles", ()) or ()),
    }


def estimate_credit_breakdown_for_tiles(tiles, quality_mode="FULL") -> dict:
    mode = str(quality_mode or "FULL").strip().upper()
    if mode == "PREVIEW":
        normalized_tiles = [
            str(entry.get("tile_key", "") or "").strip()
            for entry in pricing_records_for_tiles(tiles, quality_mode="PREVIEW", owned_tile_keys=(), allow_estimate=True)
            if isinstance(entry, dict) and str(entry.get("tile_key", "") or "").strip()
        ]
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
                    "free_reason": "preview_quality",
                    "already_owned": False,
                }
                for tile in normalized_tiles
            ],
            "excluded_tiles": [],
        }
    return estimate_credits_for_tiles(tiles, quality_mode=mode)


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
            _UNLOCKED_DOWNLOAD_PROGRESS["message"] = "Cancelling unlocked tile download..."
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

    def progress_callback(delta_bytes: int, _total_bytes: int) -> None:
        nonlocal downloaded_bytes
        if cancel_event.is_set():
            return
        downloaded_bytes += int(max(0, int(delta_bytes or 0)))
        _set_unlocked_download_progress(
            downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
            message="Downloading unlocked tiles...",
        )

    try:
        from .r2_source import clear_local_source_stale_notice, download_remote_asset_to_path
        assets = list(plan.get("assets", ()) or ())
        _set_unlocked_download_progress(
            active=True,
            status="RUNNING",
            message="Downloading unlocked tiles...",
            period=str(plan.get("period", "ALL") or "ALL"),
            period_label=str(plan.get("period_label", "") or "all data"),
            directory=str(plan.get("directory", "") or ""),
            total_bytes=total_bytes,
            downloaded_bytes=0,
            downloaded_files=0,
            total_files=total_files,
            selected_tiles=int(plan.get("selected_tiles", 0) or 0),
            missing_files=0,
            skipped_existing_files=int(plan.get("skipped_existing_files", 0) or 0),
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
        _set_unlocked_download_progress(
            active=False,
            status="FINISHED",
            message="Unlocked tile download complete.",
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
                message="Unlocked tile download cancelled.",
                downloaded_files=downloaded_files,
                missing_files=missing_files,
                downloaded_bytes=int(min(max(downloaded_bytes, 0), max(total_bytes, downloaded_bytes))),
                finished_at=time.monotonic(),
            )
            return
        _set_unlocked_download_progress(
            active=False,
            status="ERROR",
            message="Unlocked tile download failed.",
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
            message="Unlocked tile download failed.",
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
                "message": "Starting unlocked tile download...",
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
