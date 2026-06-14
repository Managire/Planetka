import logging
import os
import threading
import time
import uuid

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .r2_source import (
    begin_resolve_download_capture,
    end_resolve_download_capture,
    estimate_resolve_download_availability,
    get_remote_cache_folder,
    plan_resolve_downloads,
    prefetch_resolve_downloads,
    report_resolve_usage_summary,
    resolve_request_context,
)
from .shader_utils import resolve_tiles_for_shader


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
    "cloud session not connected",
    "cloud_session_not_connected",
    "login expired",
    "session expired",
    "log in again",
    "missing_refresh_token",
)

def _normalize_tiles(visible_tiles):
    return tuple(sorted(str(tile) for tile in (visible_tiles or ())))


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


def _staged_prefetch_key(visible_tiles, texture_quality_mode="PREVIEW"):
    return (
        _normalize_tiles(visible_tiles),
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


def stage_prefetch_payload(visible_tiles, payload, texture_quality_mode="PREVIEW"):
    if not isinstance(payload, dict):
        return
    key = _staged_prefetch_key(visible_tiles, texture_quality_mode=texture_quality_mode)
    now_ts = time.monotonic()
    with _STAGED_PREFETCH_LOCK:
        _prune_staged_prefetch_locked(now_ts)
        _STAGED_PREFETCH[key] = {
            "timestamp": now_ts,
            "payload": dict(payload),
        }


def consume_staged_prefetch_payload(visible_tiles, texture_quality_mode="PREVIEW"):
    key = _staged_prefetch_key(visible_tiles, texture_quality_mode=texture_quality_mode)
    now_ts = time.monotonic()
    with _STAGED_PREFETCH_LOCK:
        _prune_staged_prefetch_locked(now_ts)
        record = _STAGED_PREFETCH.pop(key, None)
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, dict) else None


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
    if token in {"FULL", "BALANCED", "PREVIEW"}:
        return token
    return "PREVIEW"


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


def _build_prefetched_paths(index):
    resolved_paths = {}
    for tile, image_type, filename, exts in index:
        cached_path = ""
        cache_folder = str(get_remote_cache_folder(image_type) or "")
        if cache_folder:
            for ext in exts:
                candidate = os.path.join(cache_folder, f"{image_type}_{filename}{ext}")
                if os.path.isfile(candidate):
                    cached_path = candidate
                    break
        resolved_paths[(tile, image_type)] = str(cached_path or "")
    return resolved_paths


def build_resolve_download_requests_for_visible_tiles(
    visible_tiles,
    texture_quality_mode="PREVIEW",
):
    resolved_tiles, ocean_tiles = resolve_tiles_for_shader(visible_tiles)
    requests = _build_resolve_download_requests(resolved_tiles, ocean_tiles)
    return {
        "resolved_tiles": list(resolved_tiles),
        "ocean_tiles": list(ocean_tiles),
        "requests": list(requests),
    }


def prefetch_resolve_plan(
    plan_payload,
    cancel_event=None,
    capture=False,
    resolve_id="",
    texture_quality_mode="PREVIEW",
    feature="",
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
    if capture:
        begin_resolve_download_capture()
    try:
        with resolve_request_context(
            normalized_resolve_id,
            texture_quality_mode=normalized_quality_mode,
            cancel_event=cancel_event,
            feature=feature,
        ):
            try:
                # Fast resolve path: skip remote HEAD preflight size probes so first GET
                # requests start immediately.
                plan_resolve_downloads(requests, allow_remote_probe=False)
                prefetch_result = prefetch_resolve_downloads(
                    requests,
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
        if capture:
            capture_result = end_resolve_download_capture() or {}
            try:
                report_resolve_usage_summary(
                    resolve_id=normalized_resolve_id,
                    texture_quality_mode=normalized_quality_mode,
                    downloaded_bytes=int(capture_result.get("downloaded_bytes", 0) or 0),
                    total_bytes=int(capture_result.get("total_bytes", 0) or 0),
                    tile_count=len(resolved_tiles),
                    duration_ms=int(capture_result.get("download_ms", 0) or 0),
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed scheduling resolve usage summary telemetry", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed scheduling resolve usage summary telemetry", exc_info=True)

    if isinstance(prefetch_result, dict):
        cancelled = bool(prefetch_result.get("cancelled", False))
    else:
        prefetch_result = {}

    if prefetch_failed and not cancelled:
        prefetch_result["fatal_error"] = str(prefetch_result.get("fatal_error", "") or "").strip() or (
            str(prefetch_error_text or "").strip() or "Planetka resolve prefetch failed."
        )
        prefetch_result["error_count"] = max(int(prefetch_result.get("error_count", 0) or 0), 1)

    # Resolve integrity:
    # - no post-prefetch fallback fetches here (shader fallback images handle EL/WT/PO misses)
    # - only missing S2 is fatal; missing EL/WT/PO proceeds with fallback images
    # - texture quality only changes which S2 level is requested; access is
    #   decided by the active Planetka Cloud tile session.
    resolved_paths = _build_prefetched_paths(index)
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
                    "Planetka Cloud session is not connected. "
                    "Restart Blender or retry Resolve."
                )
            else:
                prefetch_result["fatal_error"] = (
                    "Planetka resolve requires S2 tile assets. "
                    "One or more required S2 files are unavailable."
                )
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
    cancel_event=None,
    capture=False,
    resolve_id="",
    texture_quality_mode="PREVIEW",
    feature="",
):
    plan_payload = build_resolve_download_requests_for_visible_tiles(
        visible_tiles,
        texture_quality_mode=texture_quality_mode,
    )
    prefetch_payload = prefetch_resolve_plan(
        plan_payload,
        cancel_event=cancel_event,
        capture=capture,
        resolve_id=resolve_id,
        texture_quality_mode=texture_quality_mode,
        feature=feature,
    )
    result = dict(plan_payload)
    result.update(prefetch_payload)
    return result


def estimate_remote_download_bytes_for_visible_tiles(
    visible_tiles,
    allow_remote_probe=False,
    texture_quality_mode="PREVIEW",
):
    plan_payload = build_resolve_download_requests_for_visible_tiles(
        visible_tiles,
        texture_quality_mode=texture_quality_mode,
    )
    requests = list(plan_payload.get("requests", ()) or ())
    # Estimate required remote bytes and what is already available in cache.
    estimate = estimate_resolve_download_availability(
        requests,
        allow_remote_probe=bool(allow_remote_probe),
    )
    if not isinstance(estimate, dict):
        return {
            "planned_total_bytes": 0,
            "local_available_bytes": 0,
            "planned_download_bytes": 0,
            "planned_file_count": 0,
            "planned_download_file_count": 0,
            "unknown_file_count": 0,
        }
    return {
        "planned_total_bytes": int(estimate.get("planned_total_bytes", 0) or 0),
        "local_available_bytes": int(estimate.get("local_available_bytes", 0) or 0),
        "planned_download_bytes": int(estimate.get("planned_download_bytes", 0) or 0),
        "planned_file_count": int(estimate.get("planned_file_count", 0) or 0),
        "planned_download_file_count": int(estimate.get("planned_download_file_count", 0) or 0),
        "unknown_file_count": int(estimate.get("unknown_file_count", 0) or 0),
    }
