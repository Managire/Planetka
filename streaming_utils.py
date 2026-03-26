import importlib
import logging
import os
import threading
import time

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .r2_source import (
    begin_resolve_download_capture,
    end_resolve_download_capture,
    get_remote_cache_folder,
    plan_resolve_downloads,
    prefetch_resolve_downloads,
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

_STAGED_PREFETCH_LOCK = threading.Lock()
_STAGED_PREFETCH = {}
_STAGED_PREFETCH_TTL_SECONDS = 60.0


def _normalize_tiles(visible_tiles):
    return tuple(sorted(str(tile) for tile in (visible_tiles or ())))


def _normalize_base_path(base_path):
    text = str(base_path or "").strip()
    return text.rstrip("/\\")


def _staged_prefetch_key(visible_tiles, base_path):
    return (_normalize_tiles(visible_tiles), _normalize_base_path(base_path))


def _prune_staged_prefetch_locked(now_ts):
    expired_keys = []
    for key, value in _STAGED_PREFETCH.items():
        timestamp = float(value.get("timestamp", 0.0) or 0.0)
        if (now_ts - timestamp) > _STAGED_PREFETCH_TTL_SECONDS:
            expired_keys.append(key)
    for key in expired_keys:
        _STAGED_PREFETCH.pop(key, None)


def stage_prefetch_payload(visible_tiles, base_path, payload):
    if not isinstance(payload, dict):
        return
    key = _staged_prefetch_key(visible_tiles, base_path)
    now_ts = time.monotonic()
    with _STAGED_PREFETCH_LOCK:
        _prune_staged_prefetch_locked(now_ts)
        _STAGED_PREFETCH[key] = {
            "timestamp": now_ts,
            "payload": dict(payload),
        }


def consume_staged_prefetch_payload(visible_tiles, base_path):
    key = _staged_prefetch_key(visible_tiles, base_path)
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


def _prefetch_index(resolved_tiles, ocean_tiles=None):
    index = []
    ocean_lookup = set(ocean_tiles or ())
    for tile in resolved_tiles or ():
        tile_text = str(tile)
        if tile_text in ocean_lookup:
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


def _build_prefetched_paths(index, base_path, allow_fallback=False):
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


def build_resolve_download_requests_for_visible_tiles(visible_tiles, base_path):
    shader_utils = _get_shader_utils_module()
    resolve_tiles_fn = getattr(shader_utils, "resolve_tiles_for_shader", None)
    if not callable(resolve_tiles_fn):
        raise RuntimeError("Planetka shader tile resolve helper is unavailable.")

    resolved_tiles, ocean_tiles = resolve_tiles_fn(visible_tiles, base_path)
    requests = _build_resolve_download_requests(resolved_tiles, ocean_tiles)
    return {
        "resolved_tiles": list(resolved_tiles),
        "ocean_tiles": list(ocean_tiles),
        "requests": list(requests),
    }


def prefetch_resolve_plan(plan_payload, base_path, cancel_event=None, capture=False):
    resolved_tiles = list(plan_payload.get("resolved_tiles", ())) if isinstance(plan_payload, dict) else []
    ocean_tiles = list(plan_payload.get("ocean_tiles", ())) if isinstance(plan_payload, dict) else []
    requests = list(plan_payload.get("requests", ())) if isinstance(plan_payload, dict) else []
    index = _prefetch_index(resolved_tiles, ocean_tiles)

    prefetch_result = {}
    capture_result = {}
    cancelled = False
    prefetch_failed = False
    prefetch_error_text = ""

    if capture:
        begin_resolve_download_capture()
    try:
        try:
            plan_resolve_downloads(requests)
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
        if capture:
            capture_result = end_resolve_download_capture() or {}

    if isinstance(prefetch_result, dict):
        cancelled = bool(prefetch_result.get("cancelled", False))
    else:
        prefetch_result = {}

    # Resolve integrity:
    # - no post-prefetch fallback fetches here (shader fallback images handle EL/WT/PO misses)
    # - only missing S2 is fatal; missing EL/WT/PO proceeds with fallback images
    resolved_paths = _build_prefetched_paths(index, base_path, allow_fallback=False)
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
        "resolved_tiles": list(resolved_tiles),
        "ocean_tiles": list(ocean_tiles),
        "requests": list(requests),
        "resolved_paths": resolved_paths,
        "prefetch_result": dict(prefetch_result) if isinstance(prefetch_result, dict) else {},
        "download_capture": dict(capture_result) if isinstance(capture_result, dict) else {},
        "cancelled": bool(cancelled),
    }


def prepare_resolve_streaming_for_visible_tiles(visible_tiles, base_path, cancel_event=None, capture=False):
    plan_payload = build_resolve_download_requests_for_visible_tiles(visible_tiles, base_path)
    prefetch_payload = prefetch_resolve_plan(
        plan_payload,
        base_path=base_path,
        cancel_event=cancel_event,
        capture=capture,
    )
    result = dict(plan_payload)
    result.update(prefetch_payload)
    return result
