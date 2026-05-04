import importlib
import logging
import os
import threading
import time
import uuid

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .r2_source import (
    begin_resolve_download_capture,
    end_resolve_download_capture,
    estimate_total_resolve_bytes,
    find_local_source_asset,
    get_remote_cache_folder,
    ensure_resolve_pricing_session,
    is_remote_source_configured,
    plan_resolve_downloads,
    prefetch_resolve_downloads,
    resolve_request_context,
    resolve_texture_file,
)


logger = logging.getLogger(__name__)

TEXTURE_TYPES = ("S2", "EL", "WT", "PO")
TEXTURE_EXTENSIONS = {
    "S2": (".exr",),
    "EL": (".exr",),
    "WT": (".exr",),
    "PO": (".tif",),
}
POLE_CAP_Z_LEVELS = frozenset({1, 2, 4, 8})

_STAGED_PREFETCH_LOCK = threading.Lock()
_STAGED_PREFETCH = {}
_STAGED_PREFETCH_TTL_SECONDS = 60.0
_AUTH_DISCONNECT_TOKENS = (
    "account not connected",
    "account_not_connected",
    "login expired",
    "session expired",
    "log in again",
    "missing_refresh_token",
    "invalid_api_key",
)


def _normalize_tiles(visible_tiles):
    return tuple(sorted(str(tile) for tile in (visible_tiles or ())))


def _normalize_base_path(base_path):
    text = str(base_path or "").strip()
    return text.rstrip("/\\")


def _contains_auth_disconnect_text(value):
    text = str(value or "").strip().lower()
    if not text:
        return False
    for token in _AUTH_DISCONNECT_TOKENS:
        if token in text:
            return True
    return False


def _prefetch_result_indicates_auth_disconnect(prefetch_result):
    if not isinstance(prefetch_result, dict):
        return False
    if _contains_auth_disconnect_text(prefetch_result.get("fatal_error", "")):
        return True
    details = prefetch_result.get("missing_details", ())
    if not isinstance(details, (tuple, list)):
        return False
    for entry in details:
        if not isinstance(entry, dict):
            continue
        folder_value = str(entry.get("folder", "") or "").strip().upper()
        if folder_value != "S2":
            continue
        if _contains_auth_disconnect_text(entry.get("fetch_error", "")):
            return True
        if _contains_auth_disconnect_text(entry.get("remote_error", "")):
            return True
    return False


def _staged_prefetch_key(visible_tiles, base_path, texture_quality_mode="PREVIEW"):
    return (
        _normalize_tiles(visible_tiles),
        _normalize_base_path(base_path),
        _normalize_texture_quality_mode(texture_quality_mode),
    )


def _prune_staged_prefetch_locked(now_ts):
    expired_keys = []
    for key, value in _STAGED_PREFETCH.items():
        timestamp = float(value.get("timestamp", 0.0) or 0.0)
        if (now_ts - timestamp) > _STAGED_PREFETCH_TTL_SECONDS:
            expired_keys.append(key)
    for key in expired_keys:
        _STAGED_PREFETCH.pop(key, None)


def stage_prefetch_payload(visible_tiles, base_path, payload, texture_quality_mode="PREVIEW"):
    if not isinstance(payload, dict):
        return
    key = _staged_prefetch_key(visible_tiles, base_path, texture_quality_mode=texture_quality_mode)
    now_ts = time.monotonic()
    with _STAGED_PREFETCH_LOCK:
        _prune_staged_prefetch_locked(now_ts)
        _STAGED_PREFETCH[key] = {
            "timestamp": now_ts,
            "payload": dict(payload),
        }


def consume_staged_prefetch_payload(visible_tiles, base_path, texture_quality_mode="PREVIEW"):
    key = _staged_prefetch_key(visible_tiles, base_path, texture_quality_mode=texture_quality_mode)
    now_ts = time.monotonic()
    with _STAGED_PREFETCH_LOCK:
        _prune_staged_prefetch_locked(now_ts)
        record = _STAGED_PREFETCH.pop(key, None)
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, dict) else None


def _get_shader_utils_module():
    module_name = f"{__package__}.shader_utils" if __package__ else "shader_utils"
    return importlib.import_module(module_name)


def _build_resolve_download_requests(resolved_tiles, ocean_tiles=None):
    requests = []
    ocean_lookup = set(ocean_tiles or ())
    for tile in resolved_tiles or ():
        tile_text = str(tile)
        if tile_text in ocean_lookup:
            continue
        if _tile_uses_pole_cap(tile_text):
            continue
        parts = tile_text.split("_")
        if len(parts) != 4:
            continue
        try:
            z_value = int(parts[2][1:])
            d_value = int(parts[3][1:])
        except (TypeError, ValueError, IndexError):
            continue
        for image_type in TEXTURE_TYPES:
            filename = tile_text
            if image_type == "EL" and z_value == 1 and d_value == 2:
                filename = tile_text.replace("d002", "d001")
            requests.append((image_type, image_type, filename, TEXTURE_EXTENSIONS.get(image_type, (".exr",))))
    return requests


def _normalize_texture_quality_mode(value):
    token = str(value or "").strip().upper()
    if token in {"HALF", "BALANCED"}:
        return "FULL"
    if token == "FULL":
        return "FULL"
    if token == "PREVIEW":
        return "PREVIEW"
    return "PREVIEW"


def _apply_fixed_z180_quality_targets(visible_tiles, texture_quality_mode="PREVIEW"):
    mode = _normalize_texture_quality_mode(texture_quality_mode)
    target_by_mode = {
        "PREVIEW": 720,
        "FULL": 180,
    }
    target_d = int(target_by_mode.get(mode, 720))
    out = []
    for tile in visible_tiles or ():
        tile_text = str(tile or "").strip()
        if not tile_text:
            continue
        parts = tile_text.split("_")
        if len(parts) != 4:
            out.append(tile_text)
            continue
        try:
            x_value = int(parts[0][1:])
            y_value = int(parts[1][1:])
            z_value = int(parts[2][1:])
            d_value = int(parts[3][1:])
            if d_value == 0:
                d_value = 1440
        except (TypeError, ValueError, IndexError):
            out.append(tile_text)
            continue
        if z_value == 180 and d_value != target_d:
            d_code = 0 if target_d == 1440 else int(target_d)
            out.append(f"x{x_value:03d}_y{y_value:03d}_z{z_value:03d}_d{d_code:03d}")
            continue
        out.append(tile_text)
    return out


def _prefetch_index(resolved_tiles, ocean_tiles=None):
    index = []
    ocean_lookup = set(ocean_tiles or ())
    for tile in resolved_tiles or ():
        tile_text = str(tile)
        if tile_text in ocean_lookup:
            continue
        if _tile_uses_pole_cap(tile_text):
            continue
        parts = tile_text.split("_")
        if len(parts) != 4:
            continue
        try:
            z_value = int(parts[2][1:])
            d_value = int(parts[3][1:])
        except (TypeError, ValueError, IndexError):
            continue
        for image_type in TEXTURE_TYPES:
            filename = tile_text
            if image_type == "EL" and z_value == 1 and d_value == 2:
                filename = tile_text.replace("d002", "d001")
            exts = TEXTURE_EXTENSIONS.get(image_type, (".exr",))
            index.append((tile_text, image_type, filename, exts))
    return index


def _tile_uses_pole_cap(tile_text):
    parts = str(tile_text or "").split("_")
    if len(parts) != 4:
        return False
    try:
        y_value = int(parts[1][1:])
        z_value = int(parts[2][1:])
    except (TypeError, ValueError, IndexError):
        return False
    if z_value not in POLE_CAP_Z_LEVELS:
        return False
    if y_value <= 0:
        return True
    if (y_value + z_value) >= 180:
        return True
    return False


def _build_prefetched_paths(index, base_path, allow_fallback=False):
    resolved_paths = {}
    use_remote = bool(is_remote_source_configured(base_path))
    for tile, image_type, filename, exts in index:
        cached_path = ""
        cache_folder = str(get_remote_cache_folder(image_type) or "") if use_remote else ""
        if use_remote:
            for ext in exts:
                local_candidate = find_local_source_asset(image_type, f"{image_type}_{filename}{ext}")
                if local_candidate:
                    cached_path = local_candidate
                    break
        if use_remote and cache_folder and not cached_path:
            for ext in exts:
                candidate = os.path.join(cache_folder, f"{image_type}_{filename}{ext}")
                if os.path.isfile(candidate):
                    cached_path = candidate
                    break
        if not cached_path and allow_fallback:
            cached_path = resolve_texture_file(
                base_path=base_path,
                folder=image_type,
                prefix=image_type,
                filename=filename,
                extensions=exts,
            )
        resolved_paths[(tile, image_type)] = str(cached_path or "")
    return resolved_paths


def build_resolve_download_requests_for_visible_tiles(
    visible_tiles,
    base_path,
    texture_quality_mode="PREVIEW",
):
    shader_utils = _get_shader_utils_module()
    resolve_tiles_fn = getattr(shader_utils, "resolve_tiles_for_shader", None)
    if not callable(resolve_tiles_fn):
        raise RuntimeError("Planetka shader tile resolve helper is unavailable.")

    normalized_quality_mode = _normalize_texture_quality_mode(texture_quality_mode)
    visible_tiles_adjusted = _apply_fixed_z180_quality_targets(
        visible_tiles,
        texture_quality_mode=normalized_quality_mode,
    )
    resolved_tiles, ocean_tiles = resolve_tiles_fn(visible_tiles_adjusted, base_path)
    requests = _build_resolve_download_requests(resolved_tiles, ocean_tiles)
    return {
        "resolved_tiles": list(resolved_tiles),
        "ocean_tiles": list(ocean_tiles),
        "requests": list(requests),
    }


def prefetch_resolve_plan(
    plan_payload,
    base_path,
    cancel_event=None,
    capture=False,
    resolve_id="",
    texture_quality_mode="PREVIEW",
    nav_latitude_deg="",
    nav_longitude_deg="",
    nav_altitude_km="",
):
    resolved_tiles = list(plan_payload.get("resolved_tiles", ())) if isinstance(plan_payload, dict) else []
    ocean_tiles = list(plan_payload.get("ocean_tiles", ())) if isinstance(plan_payload, dict) else []
    requests = list(plan_payload.get("requests", ())) if isinstance(plan_payload, dict) else []
    index = _prefetch_index(resolved_tiles, ocean_tiles)

    prefetch_result = {}
    capture_result = {}
    cancelled = False
    prefetch_failed = False
    prefetch_error_text = ""
    normalized_resolve_id = str(resolve_id or "").strip()[:128]
    if not normalized_resolve_id:
        normalized_resolve_id = str(uuid.uuid4())

    normalized_quality_mode = _normalize_texture_quality_mode(texture_quality_mode)
    use_remote = bool(is_remote_source_configured(base_path))
    ocean_lookup = set(ocean_tiles or ())
    credit_tile_keys = []
    if normalized_quality_mode == "FULL":
        credit_tile_keys = [
            str(tile)
            for tile in resolved_tiles
            if str(tile) not in ocean_lookup
        ]

    if capture and use_remote:
        begin_resolve_download_capture()
    try:
        if use_remote:
            with resolve_request_context(
                normalized_resolve_id,
                texture_quality_mode=normalized_quality_mode,
                cancel_event=cancel_event,
                nav_latitude_deg=nav_latitude_deg,
                nav_longitude_deg=nav_longitude_deg,
                nav_altitude_km=nav_altitude_km,
                pricing_tiles=credit_tile_keys,
            ):
                try:
                    if normalized_quality_mode == "FULL" and credit_tile_keys:
                        ensure_resolve_pricing_session()
                    # Fast resolve path: skip remote HEAD preflight size probes so first GET
                    # requests start immediately.
                    plan_resolve_downloads(requests, allow_remote_probe=False)
                    prefetch_result = prefetch_resolve_downloads(
                        requests,
                        base_path=str(base_path or ""),
                        cancel_event=cancel_event,
                    )
                except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                    prefetch_failed = True
                    prefetch_error_text = str(exc)
                    logger.debug("Planetka: resolve prefetch failed", exc_info=True)
                except (RuntimeError, TypeError, ValueError) as exc:
                    prefetch_failed = True
                    prefetch_error_text = str(exc)
                    logger.debug("Planetka: resolve prefetch failed", exc_info=True)
    finally:
        if capture and use_remote:
            capture_result = end_resolve_download_capture() or {}

    if isinstance(prefetch_result, dict):
        cancelled = bool(prefetch_result.get("cancelled", False))
    else:
        prefetch_result = {}

    # Resolve integrity:
    # - no post-prefetch fallback fetches here (shader fallback images handle EL/WT/PO misses)
    # - only missing S2 is fatal; missing EL/WT/PO proceeds with fallback images
    resolved_paths = _build_prefetched_paths(index, base_path, allow_fallback=not use_remote)
    unresolved_s2_required = sum(
        1
        for key, path in resolved_paths.items()
        if isinstance(key, tuple)
        and len(key) == 2
        and str(key[1] or "") == "S2"
        and not str(path or "").strip()
    )
    if unresolved_s2_required > 0:
        prefetch_result["missing_count"] = max(
            int(prefetch_result.get("missing_count", 0) or 0),
            int(unresolved_s2_required),
        )
        prefetch_result["resolved_count"] = int(prefetch_result.get("resolved_count", 0) or 0)
        prefetch_result["error_count"] = max(int(prefetch_result.get("error_count", 0) or 0), 0)
        if not str(prefetch_result.get("fatal_error", "") or "").strip():
            if _prefetch_result_indicates_auth_disconnect(prefetch_result):
                prefetch_result["fatal_error"] = (
                    "Planetka Cloud is not connected. "
                    "Reconnect your account and retry Resolve."
                )
            else:
                prefetch_result["fatal_error"] = (
                    "Planetka resolve requires S2 tile assets. "
                    "One or more required S2 files are unavailable."
                )
    if prefetch_failed and not cancelled:
        prefetch_result["fatal_error"] = str(prefetch_result.get("fatal_error", "") or "").strip() or (
            str(prefetch_error_text or "").strip() or "Planetka resolve prefetch failed."
        )
        prefetch_result["error_count"] = max(int(prefetch_result.get("error_count", 0) or 0), 1)
    prefetch_result["cancelled"] = bool(cancelled)

    return {
        "resolve_id": normalized_resolve_id,
        "texture_quality_mode": normalized_quality_mode,
        "resolved_tiles": list(resolved_tiles),
        "ocean_tiles": list(ocean_tiles),
        "requests": list(requests),
        "resolved_paths": resolved_paths,
        "prefetch_result": dict(prefetch_result) if isinstance(prefetch_result, dict) else {},
        "download_capture": dict(capture_result) if isinstance(capture_result, dict) else {},
        "cancelled": bool(cancelled),
    }


def prepare_resolve_streaming_for_visible_tiles(
    visible_tiles,
    base_path,
    cancel_event=None,
    capture=False,
    resolve_id="",
    texture_quality_mode="PREVIEW",
    nav_latitude_deg="",
    nav_longitude_deg="",
    nav_altitude_km="",
):
    plan_payload = build_resolve_download_requests_for_visible_tiles(
        visible_tiles,
        base_path,
        texture_quality_mode=texture_quality_mode,
    )
    prefetch_payload = prefetch_resolve_plan(
        plan_payload,
        base_path=base_path,
        cancel_event=cancel_event,
        capture=capture,
        resolve_id=resolve_id,
        texture_quality_mode=texture_quality_mode,
        nav_latitude_deg=nav_latitude_deg,
        nav_longitude_deg=nav_longitude_deg,
        nav_altitude_km=nav_altitude_km,
    )
    result = dict(plan_payload)
    result.update(prefetch_payload)
    return result


def estimate_remote_download_bytes_for_visible_tiles(
    visible_tiles,
    base_path,
    allow_remote_probe=False,
    texture_quality_mode="PREVIEW",
):
    if not is_remote_source_configured(base_path):
        return {
            "planned_total_bytes": 0,
            "planned_file_count": 0,
            "unknown_file_count": 0,
        }
    plan_payload = build_resolve_download_requests_for_visible_tiles(
        visible_tiles,
        base_path,
        texture_quality_mode=texture_quality_mode,
    )
    requests = list(plan_payload.get("requests", ()) or ())
    # Estimate full dataset size for the currently required tile set,
    # independent of what's already cached locally.
    estimate = estimate_total_resolve_bytes(requests, allow_remote_probe=bool(allow_remote_probe))
    if not isinstance(estimate, dict):
        return {
            "planned_total_bytes": 0,
            "planned_file_count": 0,
            "unknown_file_count": 0,
        }
    return {
        "planned_total_bytes": int(estimate.get("planned_total_bytes", 0) or 0),
        "planned_file_count": int(estimate.get("planned_file_count", 0) or 0),
        "unknown_file_count": int(estimate.get("unknown_file_count", 0) or 0),
    }
