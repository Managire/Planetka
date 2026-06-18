import importlib
import json
import os
import time
from dataclasses import dataclass

import bpy
from bpy.props import BoolProperty

from .auth import (
    AuthApiError,
    get_authorized_headers,
    get_status_message,
    is_authenticated,
    refresh_cloud_session,
)
from .error_utils import PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS, PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .r2_source import (
    get_remote_cache_folder,
    plan_resolve_downloads,
)
from .state import (
    _get_render_job_heartbeat,
    _is_render_handler_job_active,
    _is_render_job_active,
    create_temp_mesh,
    cleanup_planetka_unused_data,
    get_resolve_runtime_status,
    logger,
    remove_object_and_unused_mesh,
    recover_post_render_state,
    stop_resolve,
    set_final_animation_render_active,
)
from . import shader_utils, streaming_utils, tile_utils


_ACTIVE_ANIMATION_RENDER_OPERATOR = None


ANIMATION_COLLECTION_NAME = "Planetka Animation Preview"
ANIMATION_SEGMENT_OBJECT_PREFIX = "Planetka Anim Preview"
ANIMATION_SEGMENT_MATERIAL_PREFIX = "Planetka Anim Material"
ANIMATION_SEGMENT_TAG_KEY = "planetka_animation_segment"
ANIMATION_SEGMENT_GROUP_TAG_KEY = "planetka_animation_segment_group"
ANIMATION_SEGMENT_MATERIAL_TAG_KEY = "planetka_animation_segment_material"
ANIMATION_STATS_SEGMENTS_KEY = "planetka_anim_prepared_segments"
ANIMATION_STATS_TEXTURE_MB_KEY = "planetka_anim_prepared_textures_mb"
ANIMATION_STATS_START_KEY = "planetka_anim_prepared_start_frame"
ANIMATION_STATS_END_KEY = "planetka_anim_prepared_end_frame"
ANIMATION_RENDER_STATUS_TEXT_KEY = "planetka_anim_render_status_text"
ANIMATION_RENDER_STATUS_ICON_KEY = "planetka_anim_render_status_icon"
ANIMATION_BASE_SURFACE_NAME_KEY = "planetka_anim_base_surface_name"
ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY = "planetka_anim_base_surface_hide_render"
ANIMATION_BASE_SURFACE_HIDE_VIEWPORT_KEY = "planetka_anim_base_surface_hide_viewport"
QUICK_PREVIEW_SCENE_STATE_KEYS = (
    ANIMATION_STATS_SEGMENTS_KEY,
    ANIMATION_STATS_TEXTURE_MB_KEY,
    ANIMATION_STATS_START_KEY,
    ANIMATION_STATS_END_KEY,
    ANIMATION_BASE_SURFACE_NAME_KEY,
    ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY,
    ANIMATION_BASE_SURFACE_HIDE_VIEWPORT_KEY,
)
QUICK_PREVIEW_MAX_SEGMENTS = 99
ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY = "planetka_anim_render_eevee_force_bump"
TEXTURE_TYPES = ("S2", "EL", "WT", "PO")
TEXTURE_EXTENSIONS = {
    "S2": ".exr",
    "EL": ".exr",
    "WT": ".exr",
    "PO": ".tif",
}
TILE_GROUP_NODE_PREFIXES = ("Planetka Tile_", "Tile_")
_COVERAGE_MAP = None
ANIMATION_RENDER_OUTPUT_SETTLE_TIMEOUT_SEC = 15.0
ANIMATION_RENDER_USER_STOP_SETTLE_SEC = 1.0
ANIMATION_RENDER_APP_JOB_FALLBACK_GRACE_SEC = 5.0
ANIMATION_RENDER_LAUNCH_RETRY_MAX_ATTEMPTS = 2
ANIMATION_HORIZON_SEGMENT_HYSTERESIS_ENABLED = True


@dataclass
class AnimationSegmentPlan:
    frame_start: int
    frame_end: int
    frame_step: int
    texture_quality_mode: str
    segments: list


def _normalize_animation_render_texture_quality_mode(value):
    token = str(value or "").strip().upper()
    if token not in {"PREVIEW", "BALANCED", "FULL"}:
        token = "PREVIEW"
    return token


def _require_animation_texture_quality_access(operator, prefs=None, texture_quality_mode="FULL"):
    del operator, prefs, texture_quality_mode
    return True


def _ensure_remote_auth_ready_for_final_render(operator, prefs):
    if not is_authenticated(prefs):
        status_message = str(get_status_message(prefs) or "").strip()
        message = "Planetka Cloud is not connected. Retry Animation Render after the cloud session reconnects."
        if status_message:
            message = f"{message} ({status_message})"
        fail(
            operator,
            message,
            code=ErrorCode.RESOLVE_REFRESH_FAILED,
            logger=logger,
        )
        return False

    try:
        refresh_cloud_session(prefs)
        headers = get_authorized_headers(prefs=prefs, allow_refresh=True)
    except AuthApiError as exc:
        detail = str(describe_cloud_session_error(exc) or "").strip()
        message = "Planetka Cloud is not connected. Retry Animation Render after the cloud session reconnects."
        if detail:
            message = f"{message} {detail}"
        fail(
            operator,
            message,
            code=ErrorCode.RESOLVE_REFRESH_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka animation render auth preflight failed",
        )
        return False
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        fail(
            operator,
            f"Planetka Cloud auth preflight failed: {exc}",
            code=ErrorCode.RESOLVE_REFRESH_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka animation render auth preflight failed",
        )
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
        fail(
            operator,
            f"Planetka Cloud auth preflight failed: {exc}",
            code=ErrorCode.RESOLVE_REFRESH_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka animation render auth preflight failed",
        )
        return False

    if not isinstance(headers, dict) or not headers:
        fail(
            operator,
            "Planetka Cloud is not connected. Retry Animation Render after the cloud session reconnects.",
            code=ErrorCode.RESOLVE_REFRESH_FAILED,
            logger=logger,
        )
        return False

    return True


def _cancel_if_animation_render_active(operator, action_label):
    try:
        if bool(_is_render_job_active()):
            label = str(action_label or "This action").strip() or "This action"
            operator.report(
                {'WARNING'},
                f"{label} is unavailable while Final Animation Render is running.",
            )
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: failed checking active render lock for action cancel guard", exc_info=True)
    return False


def _set_active_animation_render_operator(operator=None):
    global _ACTIVE_ANIMATION_RENDER_OPERATOR
    _ACTIVE_ANIMATION_RENDER_OPERATOR = operator


def _get_active_animation_render_operator():
    return _ACTIVE_ANIMATION_RENDER_OPERATOR


def _update_active_view_layer():
    try:
        view_layer = getattr(getattr(bpy, "context", None), "view_layer", None)
        if view_layer is not None:
            view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: active view-layer update failed", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka animation: active view-layer update failed", exc_info=True)


def _canonical_tiles(tiles):
    if not isinstance(tiles, (list, tuple)):
        return tuple()
    normalized = []
    for tile in tiles:
        tile_text = str(tile)
        if _parse_tile(tile_text) is None:
            continue
        normalized.append(tile_text)
    return tuple(sorted(normalized))


def _parse_tile(tile):
    try:
        parts = str(tile).split("_")
        if len(parts) != 4:
            return None
        d_code = int(parts[3][1:])
        if d_code == 0:
            d_code = 1440
        return (
            int(parts[0][1:]),
            int(parts[1][1:]),
            int(parts[2][1:]),
            d_code,
        )
    except (TypeError, ValueError, IndexError):
        return None


def _get_coverage_map():
    global _COVERAGE_MAP
    if _COVERAGE_MAP is None:
        module_name = f"{__package__}.coverage" if __package__ else "coverage"
        coverage_module = importlib.import_module(module_name)
        _COVERAGE_MAP = getattr(coverage_module, "COVERAGE", {})
    return _COVERAGE_MAP or {}


def _is_land_tile(tile):
    parsed = _parse_tile(tile)
    if not parsed:
        return False
    x, y, z, _d = parsed
    coverage = _get_coverage_map()
    level = coverage.get(int(z), set()) if coverage else set()
    return (int(x), int(y)) in level


def _iter_texture_requests_for_tile(tile):
    parsed = _parse_tile(tile)
    if not parsed:
        return
    _x, _y, z, d = parsed
    for texture_type in TEXTURE_TYPES:
        tile_code = str(tile)
        if texture_type == "EL" and int(z) == 1 and int(d) == 2:
            tile_code = tile_code.replace("_d002", "_d001")
        extension = TEXTURE_EXTENSIONS.get(texture_type, ".exr")
        yield (texture_type, texture_type, tile_code, (extension,))


def _estimate_remote_texture_bytes_for_requests(requests):
    deduped = []
    seen = set()
    for request in requests or ():
        if not isinstance(request, (tuple, list)) or len(request) != 4:
            continue
        folder, prefix, filename, extensions = request
        normalized = (
            str(folder or "").strip(),
            str(prefix or "").strip(),
            str(filename or "").strip(),
            tuple(extensions or (".exr",)),
        )
        if not normalized[0] or not normalized[1] or not normalized[2]:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    cached_bytes = 0
    unresolved = []
    for folder, prefix, filename, exts in deduped:
        cache_folder = get_remote_cache_folder(folder)
        found_cached = False
        if cache_folder:
            for ext in exts:
                candidate = os.path.join(cache_folder, f"{prefix}_{filename}{str(ext or '')}")
                if not os.path.isfile(candidate):
                    continue
                found_cached = True
                try:
                    cached_bytes += int(os.path.getsize(candidate))
                except (OSError, TypeError, ValueError):
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
                break
        if not found_cached:
            unresolved.append((folder, prefix, filename, exts))

    planned_total = 0
    unknown_files = 0
    if unresolved:
        try:
            plan = plan_resolve_downloads(unresolved)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            plan = {}
        except (RuntimeError, TypeError, ValueError):
            plan = {}
        planned_total = int(plan.get("planned_total_bytes", 0) or 0)
        unknown_files = int(plan.get("unknown_file_count", 0) or 0)

    return int(max(0, cached_bytes + planned_total)), int(max(0, unknown_files))


def _build_texture_requests_for_tiles(tiles):
    requests = []
    for tile in tiles or ():
        if not _is_land_tile(tile):
            continue
        requests.extend(_iter_texture_requests_for_tile(tile))
    return requests


def _estimate_texture_bytes_for_segments(segments):
    requests = []
    for segment in segments or ():
        requests.extend(_build_texture_requests_for_tiles(segment.get("tiles", ())))
    total_bytes, _unknown = _estimate_remote_texture_bytes_for_requests(requests)
    return int(total_bytes)


def _ensure_collection(scene, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if all(child.name != collection.name for child in scene.collection.children):
        try:
            scene.collection.children.link(collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    return collection


def _set_object_collection_only(obj, collection):
    if obj is None or collection is None:
        return
    for existing_collection in list(getattr(obj, "users_collection", ())):
        try:
            existing_collection.objects.unlink(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError):
            continue
    try:
        collection.objects.link(obj)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)


def _clear_earth_role_tag(obj):
    if obj is None:
        return
    try:
        if "planetka_role" in obj:
            del obj["planetka_role"]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)


def _make_texture_groups_unique(material, segment_index, segment_start=None, segment_end=None):
    if not material or not material.node_tree:
        raise RuntimeError("Segment material node tree is missing.")
    loading_node = material.node_tree.nodes.get("Planetka Textures Loading")
    if not loading_node or not getattr(loading_node, "node_tree", None):
        raise RuntimeError("Segment material is missing 'Planetka Textures Loading'.")

    if segment_start is not None and segment_end is not None:
        segment_tag = f"{int(segment_start):04d}-{int(segment_end):04d}"
    else:
        segment_tag = f"{int(segment_index):04d}"

    created_groups = []
    loading_tree = loading_node.node_tree.copy()
    loading_tree.name = f"{loading_tree.name}_frames_{segment_tag}"
    loading_node.node_tree = loading_tree
    try:
        loading_tree.use_fake_user = False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    loading_tree[ANIMATION_SEGMENT_GROUP_TAG_KEY] = True
    created_groups.append(loading_tree)

    for node in loading_tree.nodes:
        if node.type != "GROUP" or not node.node_tree:
            continue
        if not node.name.startswith(TILE_GROUP_NODE_PREFIXES):
            continue
        tile_tree = node.node_tree.copy()
        tile_tree.name = f"{tile_tree.name}_frames_{segment_tag}"
        node.node_tree = tile_tree
        try:
            tile_tree.use_fake_user = False
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        tile_tree[ANIMATION_SEGMENT_GROUP_TAG_KEY] = True
        created_groups.append(tile_tree)
    return created_groups


def _create_segment_material(segment_index, segment_start=None, segment_end=None):
    base_material = bpy.data.materials.get("Planetka Earth Material")
    if base_material is None:
        raise RuntimeError("Base material 'Planetka Earth Material' is missing.")
    segment_material = base_material.copy()
    if segment_start is not None and segment_end is not None:
        segment_material.name = (
            f"{ANIMATION_SEGMENT_MATERIAL_PREFIX} {int(segment_start):04d}-{int(segment_end):04d}"
        )
    else:
        segment_material.name = f"{ANIMATION_SEGMENT_MATERIAL_PREFIX} {int(segment_index):04d}"
    segment_material[ANIMATION_SEGMENT_MATERIAL_TAG_KEY] = True
    _make_texture_groups_unique(
        segment_material,
        segment_index,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    # Quick Preview segment materials must stay bump-only for stable EEVEE/Cycles preview playback.
    _set_material_displacement_bump_only(segment_material)
    return segment_material


def _assign_material(obj, material):
    mesh_data = getattr(obj, "data", None)
    if mesh_data is None:
        return
    mesh_data.materials.clear()
    mesh_data.materials.append(material)
    for polygon in mesh_data.polygons:
        polygon.material_index = 0


def _set_constant_visibility_keyframes(obj, segment_start, segment_end, timeline_start, timeline_end):
    obj.hide_viewport = True
    obj.hide_render = True
    for data_path in ("hide_viewport", "hide_render"):
        if int(segment_start) > int(timeline_start):
            setattr(obj, data_path, True)
            obj.keyframe_insert(data_path=data_path, frame=int(timeline_start))
            obj.keyframe_insert(data_path=data_path, frame=int(segment_start) - 1)

        setattr(obj, data_path, False)
        obj.keyframe_insert(data_path=data_path, frame=int(segment_start))
        obj.keyframe_insert(data_path=data_path, frame=int(segment_end))

        if int(segment_end) < int(timeline_end):
            setattr(obj, data_path, True)
            obj.keyframe_insert(data_path=data_path, frame=int(segment_end) + 1)
            obj.keyframe_insert(data_path=data_path, frame=int(timeline_end))

    anim = getattr(obj, "animation_data", None)
    action = getattr(anim, "action", None) if anim else None
    fcurves = getattr(action, "fcurves", None) if action else None
    if not fcurves:
        return
    for fcurve in fcurves:
        if fcurve.data_path not in {"hide_viewport", "hide_render"}:
            continue
        for keyframe_point in fcurve.keyframe_points:
            keyframe_point.interpolation = 'CONSTANT'


def _resolve_tiles_for_frame(scene, frame, texture_quality_mode_override=None):
    scene.frame_set(int(frame))
    try:
        _update_active_view_layer()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    try:
        full_source_tiles = tile_utils.main(scope_mode="CAMERA")
        from .render_prep import apply_texture_quality_to_full_tiles
        return list(apply_texture_quality_to_full_tiles(full_source_tiles, texture_quality_mode_override))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: tile resolve failed at frame %s", frame, exc_info=True)
        return []
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka animation: tile resolve runtime failure at frame %s", frame, exc_info=True)
        return []


def _apply_horizon_segment_tile_retention(tile_utils, sampled_tiles, retained_tiles):
    sampled_set = {str(tile) for tile in (sampled_tiles or ()) if _parse_tile(str(tile)) is not None}
    retained_set = {str(tile) for tile in (retained_tiles or ()) if _parse_tile(str(tile)) is not None}
    combined = list(sampled_set | retained_set)
    if not combined:
        return tuple()

    max_budget = 12
    try:
        max_budget = int(getattr(tile_utils, "MAX_SHADER_TILE_BUDGET", 12) or 12) if tile_utils is not None else 12
    except (TypeError, ValueError, AttributeError):
        max_budget = 12
    max_budget = max(1, int(max_budget))

    if len(combined) <= max_budget or tile_utils is None:
        return _canonical_tiles(combined)

    try:
        budgeted_tiles, _trace, _success = tile_utils.enforce_shader_tile_budget_for_tiles(
            combined,
            max_tiles=max_budget,
            scope_mode="CAMERA",
        )
        normalized = _canonical_tiles(list(budgeted_tiles or ()))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: horizon tile retention budget fallback failed", exc_info=True)
        normalized = _canonical_tiles(combined[:max_budget])
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka animation: horizon tile retention budget fallback failed", exc_info=True)
        normalized = _canonical_tiles(combined[:max_budget])

    if not retained_set:
        return normalized

    missing_retained = [tile for tile in sorted(retained_set) if tile not in set(normalized)]
    if missing_retained:
        # If budget optimization cannot keep retained edge tiles without destabilizing
        # the set, skip retention for this segment transition.
        return _canonical_tiles(sampled_set)
    return normalized


def _classify_horizon_drops_for_next_segment(tile_utils, previous_tiles, next_raw_tiles):
    if tile_utils is None:
        return tuple()
    previous_set = set(previous_tiles or ())
    next_set = set(next_raw_tiles or ())
    dropped = sorted(previous_set - next_set)
    if not dropped:
        return tuple()
    try:
        max_budget = int(getattr(tile_utils, "MAX_SHADER_TILE_BUDGET", 12) or 12)
    except (TypeError, ValueError, AttributeError):
        max_budget = 12
    max_budget = max(1, int(max_budget))
    # Avoid retention when next segment is already budget-full, because that tends to
    # force compensating swaps and can fragment segment boundaries.
    if len(next_set) >= max_budget:
        return tuple()
    # Keep retention highly targeted to avoid broad timeline-side effects.
    if len(dropped) != 1:
        return tuple()
    try:
        retained = tile_utils.classify_horizon_edge_near_miss_tiles(dropped, scope_mode="CAMERA")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: failed classifying horizon edge drops", exc_info=True)
        return tuple()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka animation: failed classifying horizon edge drops", exc_info=True)
        return tuple()
    return _canonical_tiles(retained)


def _build_segments(
    scene,
    frame_start,
    frame_end,
    frame_step,
    texture_quality_mode_override=None,
    apply_segment_horizon_hysteresis=False,
    enable_adaptive_horizon_precision=False,
):
    frames = list(range(int(frame_start), int(frame_end) + 1, max(1, int(frame_step))))
    if not frames:
        return []

    adaptive_scene_key = None
    adaptive_was_present = False
    adaptive_previous_value = None
    if bool(enable_adaptive_horizon_precision) and scene is not None:
        adaptive_scene_key = str(
            getattr(
                tile_utils,
                "ANIMATION_ADAPTIVE_HORIZON_SCENE_KEY",
                "planetka_anim_adaptive_horizon_precision",
            )
        )
        try:
            adaptive_was_present = bool(adaptive_scene_key in scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            adaptive_was_present = False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            adaptive_was_present = False
        try:
            adaptive_previous_value = scene.get(adaptive_scene_key, None)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            adaptive_previous_value = None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            adaptive_previous_value = None
        try:
            scene[adaptive_scene_key] = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed enabling adaptive horizon precision flag", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed enabling adaptive horizon precision flag", exc_info=True)

    try:
        segments = []
        current_start = int(frames[0])
        current_hold_tiles = tuple()
        current_tiles = _canonical_tiles(
            _resolve_tiles_for_frame(
                scene,
                current_start,
                texture_quality_mode_override=texture_quality_mode_override,
            )
        )
        segment_index = 1

        for index in range(1, len(frames)):
            frame = int(frames[index])
            sampled_raw_tiles = _canonical_tiles(
                _resolve_tiles_for_frame(
                    scene,
                    frame,
                    texture_quality_mode_override=texture_quality_mode_override,
                )
            )
            if bool(apply_segment_horizon_hysteresis):
                sampled_tiles = sampled_raw_tiles
                if current_hold_tiles:
                    sampled_tiles = _apply_horizon_segment_tile_retention(
                        tile_utils,
                        sampled_raw_tiles,
                        current_hold_tiles,
                    )
            else:
                sampled_tiles = sampled_raw_tiles

            if sampled_tiles != current_tiles:
                previous_frame = int(frames[index - 1])
                segments.append(
                    {
                        "index": int(segment_index),
                        "start": int(current_start),
                        "end": int(previous_frame),
                        "tiles": list(current_tiles),
                    }
                )
                segment_index += 1
                current_start = frame
                if bool(apply_segment_horizon_hysteresis):
                    current_hold_tiles = _classify_horizon_drops_for_next_segment(
                        tile_utils,
                        current_tiles,
                        sampled_raw_tiles,
                    )
                    if current_hold_tiles:
                        sampled_tiles = _apply_horizon_segment_tile_retention(
                            tile_utils,
                            sampled_raw_tiles,
                            current_hold_tiles,
                        )
                else:
                    current_hold_tiles = tuple()
                current_tiles = _canonical_tiles(sampled_tiles)

        segments.append(
            {
                "index": int(segment_index),
                "start": int(current_start),
                "end": int(frames[-1]),
                "tiles": list(current_tiles),
            }
        )
        return segments
    finally:
        if adaptive_scene_key and scene is not None:
            try:
                if adaptive_was_present:
                    scene[adaptive_scene_key] = adaptive_previous_value
                elif adaptive_scene_key in scene:
                    del scene[adaptive_scene_key]
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed restoring adaptive horizon precision flag", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: failed restoring adaptive horizon precision flag", exc_info=True)


def _plan_animation_segments(
    scene,
    frame_start,
    frame_end,
    frame_step=1,
    texture_quality_mode_override=None,
    apply_segment_horizon_hysteresis=False,
    enable_adaptive_horizon_precision=False,
):
    safe_start = int(frame_start)
    safe_end = int(frame_end)
    safe_step = max(1, int(frame_step))
    try:
        original_frame = int(getattr(scene, "frame_current", safe_start))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        original_frame = int(safe_start)
    try:
        segments = _build_segments(
            scene,
            safe_start,
            safe_end,
            safe_step,
            texture_quality_mode_override=texture_quality_mode_override,
            apply_segment_horizon_hysteresis=bool(apply_segment_horizon_hysteresis),
            enable_adaptive_horizon_precision=bool(enable_adaptive_horizon_precision),
        )
    finally:
        try:
            scene.frame_set(int(original_frame))
            _update_active_view_layer()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    return AnimationSegmentPlan(
        frame_start=safe_start,
        frame_end=safe_end,
        frame_step=safe_step,
        texture_quality_mode=str(texture_quality_mode_override or ""),
        segments=list(segments or ()),
    )


def _quick_preview_is_prepared(scene):
    if scene is None:
        return False
    try:
        prepared_segments = int(scene.get(ANIMATION_STATS_SEGMENTS_KEY, 0) or 0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        prepared_segments = 0
    if prepared_segments > 0:
        return True
    for obj in tuple(bpy.data.objects):
        try:
            if bool(obj.get(ANIMATION_SEGMENT_TAG_KEY, False)):
                return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
    return False


def _store_quick_preview_scene_state(scene, segments, texture_mb, frame_start, frame_end):
    if scene is None:
        return
    scene[ANIMATION_STATS_SEGMENTS_KEY] = int(max(0, int(segments)))
    scene[ANIMATION_STATS_TEXTURE_MB_KEY] = float(max(0.0, float(texture_mb)))
    scene[ANIMATION_STATS_START_KEY] = int(frame_start)
    scene[ANIMATION_STATS_END_KEY] = int(frame_end)


def _restore_base_surface_visibility(scene):
    base_name = str(scene.get(ANIMATION_BASE_SURFACE_NAME_KEY, "") or "")
    if not base_name:
        return
    obj = bpy.data.objects.get(base_name)
    if obj is None:
        return
    try:
        if ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY in scene:
            obj.hide_render = bool(scene.get(ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY, False))
        if ANIMATION_BASE_SURFACE_HIDE_VIEWPORT_KEY in scene:
            obj.hide_viewport = bool(scene.get(ANIMATION_BASE_SURFACE_HIDE_VIEWPORT_KEY, False))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)


def clear_prepared_animation_assets(scene):
    props = getattr(scene, "planetka_public", None) if scene is not None else None
    _restore_base_surface_visibility(scene)

    prepared_objects = [
        obj for obj in list(bpy.data.objects)
        if bool(obj.get(ANIMATION_SEGMENT_TAG_KEY, False))
    ]
    for obj in prepared_objects:
        remove_object_and_unused_mesh(obj)

    for material in list(bpy.data.materials):
        if not bool(material.get(ANIMATION_SEGMENT_MATERIAL_TAG_KEY, False)):
            continue
        try:
            if int(getattr(material, "users", 0)) == 0:
                bpy.data.materials.remove(material, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError):
            continue

    for group in list(bpy.data.node_groups):
        if not bool(group.get(ANIMATION_SEGMENT_GROUP_TAG_KEY, False)):
            continue
        try:
            if int(getattr(group, "users", 0)) == 0:
                bpy.data.node_groups.remove(group, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError):
            continue

    for collection_name in (str(ANIMATION_COLLECTION_NAME or "").strip(),):
        collection = bpy.data.collections.get(collection_name)
        if collection is None or collection.objects:
            continue
        try:
            for parent in bpy.data.collections:
                if collection.name in parent.children:
                    parent.children.unlink(collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        try:
            bpy.data.collections.remove(collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

    for key in QUICK_PREVIEW_SCENE_STATE_KEYS:
        try:
            if key in scene:
                del scene[key]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

    try:
        shader_utils.cleanup_planetka_images(force_remove_datablocks=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: cleanup images failed", exc_info=True)


def _prepare_segments(scene, segments, frame_start, frame_end, texture_quality_mode="PREVIEW"):
    source_surface = get_earth_object()
    if source_surface is None:
        raise RuntimeError("Create Earth first, then prepare animation render setup.")

    clear_prepared_animation_assets(scene)
    target_collection = _ensure_collection(scene, ANIMATION_COLLECTION_NAME)

    scene[ANIMATION_BASE_SURFACE_NAME_KEY] = str(source_surface.name)
    scene[ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY] = bool(source_surface.hide_render)
    scene[ANIMATION_BASE_SURFACE_HIDE_VIEWPORT_KEY] = bool(source_surface.hide_viewport)
    source_surface.hide_render = True
    source_surface.hide_viewport = True

    created_count = 0
    try:
        for segment in segments:
            segment_tiles = list(segment.get("tiles", ()))
            if not segment_tiles:
                continue
            resolved_paths = {}
            resolved_tiles_override = list(segment_tiles)
            ocean_tiles_override = set()
            stream_payload = streaming_utils.prepare_resolve_streaming_for_visible_tiles(
                segment_tiles,
                texture_quality_mode=str(texture_quality_mode or "PREVIEW"),
            )
            if isinstance(stream_payload, dict):
                if bool(stream_payload.get("cancelled", False)):
                    raise RuntimeError("Quick Preview download was cancelled.")
                fatal_error = str(stream_payload.get("prefetch_result", {}).get("fatal_error", "") or "").strip()
                if fatal_error:
                    raise RuntimeError(fatal_error)
                resolved_paths = dict(stream_payload.get("resolved_paths", {}) or {})
                resolved_tiles_override = list(stream_payload.get("resolved_tiles", ()) or resolved_tiles_override)
                ocean_tiles_override = set(stream_payload.get("ocean_tiles", ()) or ocean_tiles_override)
            segment_index = int(segment.get("index", 0))
            segment_start = int(segment.get("start", frame_start))
            segment_end = int(segment.get("end", frame_end))
            segment_name = f"{ANIMATION_SEGMENT_OBJECT_PREFIX} {segment_start:04d}-{segment_end:04d}"
            segment_obj = create_temp_mesh(
                segment_tiles,
                name=segment_name,
                collection_policy="surface_only",
            )
            if segment_obj is None:
                raise RuntimeError(f"Failed to build segment mesh {segment_index}.")
            try:
                segment_obj.name = segment_name
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            _clear_earth_role_tag(segment_obj)
            _set_object_collection_only(segment_obj, target_collection)
            segment_obj[ANIMATION_SEGMENT_TAG_KEY] = True
            segment_obj["planetka_segment_index"] = segment_index
            segment_obj["planetka_segment_start"] = segment_start
            segment_obj["planetka_segment_end"] = segment_end
            _enforce_cycles_simple_subdivision_on_object(scene, segment_obj)

            segment_material = _create_segment_material(
                segment_index,
                segment_start=segment_start,
                segment_end=segment_end,
            )
            _assign_material(segment_obj, segment_material)
            shader_utils.main(
                segment_tiles,
                material_name=segment_material.name,
                force_remove_datablocks=False,
                resolved_paths=resolved_paths,
                resolved_tiles_override=resolved_tiles_override,
                ocean_tiles_override=ocean_tiles_override,
            )
            # Keep Quick Preview segment shaders in bump-only mode regardless of active render engine.
            _set_material_displacement_bump_only(segment_material)
            _set_constant_visibility_keyframes(
                segment_obj,
                segment_start=segment_start,
                segment_end=segment_end,
                timeline_start=int(frame_start),
                timeline_end=int(frame_end),
            )
            created_count += 1
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        clear_prepared_animation_assets(scene)
        raise
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka animation: failed preparing segment assets", exc_info=True)
        clear_prepared_animation_assets(scene)
        raise

    if created_count == 0:
        source_surface.hide_render = bool(scene.get(ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY, False))

    return int(created_count)


def _active_timeline_frame_range(scene):
    if scene is None:
        return 1, 250
    try:
        use_preview = bool(getattr(scene, "use_preview_range", False))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        use_preview = False
    if use_preview:
        try:
            start = int(getattr(scene, "frame_preview_start", getattr(scene, "frame_start", 1)))
            end = int(getattr(scene, "frame_preview_end", getattr(scene, "frame_end", 250)))
            return start, end
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed reading preview timeline range; falling back to scene range", exc_info=True)
    try:
        start = int(getattr(scene, "frame_start", 1))
        end = int(getattr(scene, "frame_end", 250))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        start, end = 1, 250
    return start, end


def _apply_keyed_runtime_scene_state(scene, props):
    del scene, props
    return


def _is_animation_playing():
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False
    if wm is None:
        return False
    try:
        windows = tuple(getattr(wm, "windows", ()) or ())
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False
    for window in windows:
        try:
            screen = getattr(window, "screen", None)
            if screen and bool(getattr(screen, "is_animation_playing", False)):
                return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
    return False


def _try_start_preview_playback():
    if _is_animation_playing():
        return
    try:
        bpy.ops.screen.animation_play()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return
    except (RuntimeError, TypeError, ValueError):
        return


def _is_movie_output(scene):
    render = getattr(scene, "render", None) if scene else None
    image_settings = getattr(render, "image_settings", None) if render else None
    fmt = str(getattr(image_settings, "file_format", "") or "") if image_settings else ""
    return fmt in {"FFMPEG", "AVI_JPEG", "AVI_RAW"}


def _count_missing_tile_loading_images(material_name="Planetka Earth Material"):
    material = bpy.data.materials.get(str(material_name or ""))
    if material is None or getattr(material, "node_tree", None) is None:
        return 0
    node_tree = getattr(material, "node_tree", None)
    nodes = getattr(node_tree, "nodes", None) if node_tree else None
    if nodes is None:
        return 0

    loading_group_node = nodes.get("Planetka Textures Loading")
    loading_group = getattr(loading_group_node, "node_tree", None) if loading_group_node else None
    group_nodes = getattr(loading_group, "nodes", None) if loading_group else None
    if group_nodes is None:
        return 0

    missing = 0
    for node in group_nodes:
        if str(getattr(node, "type", "")) != "GROUP":
            continue
        node_name = str(getattr(node, "name", "") or "")
        if not node_name.startswith(("Tile_", "Planetka Tile_")):
            continue
        if bool(getattr(node, "mute", False)):
            continue
        tile_tree = getattr(node, "node_tree", None)
        tile_nodes = getattr(tile_tree, "nodes", None) if tile_tree else None
        if tile_nodes is None:
            continue
        for image_type in ("S2", "EL", "WT", "PO"):
            image_node = tile_nodes.get(image_type)
            if image_node is None:
                continue
            image = getattr(image_node, "image", None)
            if image is None:
                missing += 1
                continue
            image_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", ""))
            if not image_path:
                missing += 1
                continue
            abs_path = bpy.path.abspath(image_path)
            if abs_path and not os.path.isfile(abs_path):
                missing += 1
    return int(missing)


def _wait_for_resolve_idle(scene, timeout_sec=45.0, poll_sec=0.1):
    started = time.monotonic()
    last_status = {}
    while True:
        try:
            status = get_resolve_runtime_status(scene=scene) or {}
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            status = {}
        running = bool(status.get("running", False))
        if not running:
            return True, status
        last_status = dict(status)
        if (time.monotonic() - started) >= float(max(0.5, timeout_sec)):
            return False, last_status
        try:
            _update_active_view_layer()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: view-layer update failed while waiting for resolve idle", exc_info=True)
        time.sleep(float(max(0.02, poll_sec)))


def _set_enum_property_if_available(target, prop_name, preferred_values):
    if target is None or not hasattr(target, prop_name):
        return False
    candidates = [str(v or "").strip() for v in (preferred_values or ()) if str(v or "").strip()]
    if not candidates:
        return False
    available = set()
    try:
        rna = getattr(target, "bl_rna", None)
        properties = getattr(rna, "properties", None) if rna is not None else None
        prop_def = properties.get(prop_name) if properties is not None else None
        if prop_def and hasattr(prop_def, "enum_items"):
            available = {str(item.identifier) for item in prop_def.enum_items}
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        available = set()
    for identifier in candidates:
        if available and identifier not in available:
            continue
        try:
            setattr(target, prop_name, identifier)
            return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
    return False


def _capture_earth_material_displacement_mode_state(material):
    state = {}
    if material is None:
        return state
    try:
        if hasattr(material, "displacement_method"):
            state["material"] = str(getattr(material, "displacement_method", "") or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: failed capturing material displacement method state", exc_info=True)
    cycles_settings = getattr(material, "cycles", None)
    try:
        if cycles_settings is not None and hasattr(cycles_settings, "displacement_method"):
            state["cycles"] = str(getattr(cycles_settings, "displacement_method", "") or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: failed capturing cycles displacement method state", exc_info=True)
    return state


def _set_material_displacement_bump_only(material):
    if material is None:
        return False
    changed_any = False
    # Blender 5.x material-level property.
    changed_any = _set_enum_property_if_available(
        material,
        "displacement_method",
        ("BUMP", "BUMP_ONLY"),
    ) or changed_any
    # Some Blender builds still expose displacement mode under material.cycles.
    cycles_settings = getattr(material, "cycles", None)
    changed_any = _set_enum_property_if_available(
        cycles_settings,
        "displacement_method",
        ("BUMP", "BUMP_ONLY"),
    ) or changed_any
    return changed_any


def _earth_surface_materials():
    materials = []
    seen = set()

    def _add_material(material):
        if material is None:
            return
        try:
            key = int(material.as_pointer())
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            key = id(material)
        if key in seen:
            return
        seen.add(key)
        materials.append(material)

    earth_obj = get_earth_object()
    if earth_obj is not None:
        try:
            _add_material(getattr(earth_obj, "active_material", None))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed reading active Earth material while collecting materials", exc_info=True)
        try:
            mesh_data = getattr(earth_obj, "data", None)
            slots = getattr(mesh_data, "materials", None) if mesh_data is not None else None
            if slots is not None:
                for slot_material in slots:
                    _add_material(slot_material)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed reading Earth material slots while collecting materials", exc_info=True)

    # Include material variants that can appear during resolve swaps.
    try:
        for material in tuple(getattr(bpy.data, "materials", ()) or ()):
            mat_name = str(getattr(material, "name", "") or "")
            if mat_name == "Planetka Earth Material" or mat_name.startswith("Planetka Earth Material."):
                _add_material(material)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: failed scanning material variants while collecting Earth materials", exc_info=True)
    return materials


def _capture_material_displacement_mode_states(materials):
    states = []
    for material in (materials or ()):
        try:
            state = _capture_earth_material_displacement_mode_state(material)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            state = {}
        if isinstance(state, dict) and state:
            states.append({"material": material, "state": state})
    return states


def _restore_material_displacement_mode_states(states):
    for entry in (states or ()):
        if not isinstance(entry, dict):
            continue
        material = entry.get("material")
        state = entry.get("state")
        try:
            _restore_earth_material_displacement_mode_state(material, state)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed restoring displacement mode state", exc_info=True)


def _set_earth_surface_materials_bump_only():
    changed_any = False
    for material in _earth_surface_materials():
        changed_any = _set_material_displacement_bump_only(material) or changed_any
    return changed_any


def _restore_earth_material_displacement_mode_state(material, state):
    if material is None or not isinstance(state, dict):
        return
    material_mode = str(state.get("material", "") or "").strip()
    if material_mode:
        _set_enum_property_if_available(material, "displacement_method", (material_mode,))
    cycles_settings = getattr(material, "cycles", None)
    cycles_mode = str(state.get("cycles", "") or "").strip()
    if cycles_mode:
        _set_enum_property_if_available(cycles_settings, "displacement_method", (cycles_mode,))


def _enforce_cycles_simple_subdivision_on_object(scene, obj):
    if scene is None or obj is None:
        return False
    render = getattr(scene, "render", None)
    try:
        engine = str(getattr(render, "engine", "") or "").strip().upper()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        engine = ""
    if engine != "CYCLES":
        return False
    if getattr(obj, "type", None) != 'MESH':
        return False
    modifiers = getattr(obj, "modifiers", None)
    if modifiers is None:
        return False
    subsurf = modifiers.get("Adaptive Subdivision")
    if subsurf is None or getattr(subsurf, "type", None) != 'SUBSURF':
        return False
    if not hasattr(subsurf, "subdivision_type"):
        return False
    return _set_enum_property_if_available(subsurf, "subdivision_type", ("SIMPLE",))


class PLANETKA_OT_AnimationPreviewShot(bpy.types.Operator):
    bl_idname = "planetka_public.animation_preview_shot"
    bl_label = "Preview Animation"
    bl_description = "Play or pause the current camera animation using already prepared Quick Preview data; no new Resolve or download is started."

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Quick Preview playback"):
            return {'CANCELLED'}
        if _is_animation_playing():
            try:
                bpy.ops.screen.animation_play()
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    f"Pause preview failed: {exc}",
                    code=ErrorCode.APPLY_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation preview pause failed",
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                return fail(
                    self,
                    f"Pause preview failed: {exc}",
                    code=ErrorCode.APPLY_FAILED,
                    logger=logger,
                )
            self.report({'INFO'}, "Animation preview paused.")
            return {'FINISHED'}

        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        start_frame, end_frame = _active_timeline_frame_range(scene)
        if int(end_frame) < int(start_frame):
            return fail(
                self,
                f"Invalid frame range: {int(start_frame)}-{int(end_frame)}.",
                code=ErrorCode.PRECHECK_FAILED,
                logger=logger,
            )

        try:
            scene.use_preview_range = True
            scene.frame_preview_start = int(start_frame)
            scene.frame_preview_end = int(end_frame)
            scene.frame_set(int(start_frame))
            _update_active_view_layer()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation preview: failed setting playback range", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation preview: failed setting playback range", exc_info=True)

        _try_start_preview_playback()
        self.report({'INFO'}, "Preview animation started on currently loaded data.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationClearPrepared(bpy.types.Operator):
    bl_idname = "planetka_public.animation_clear_prepared"
    bl_label = "Clear Quick Preview"
    bl_description = "Remove prepared Quick Preview segment meshes, materials, and visibility keys, then restore the normal Earth rendering workflow."

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Clear Quick Preview"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        try:
            clear_prepared_animation_assets(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Clear prepared animation failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka animation clear prepared failed",
            )
        self.report({'INFO'}, "Prepared animation assets cleared.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationRender(bpy.types.Operator):
    bl_idname = "planetka_public.animation_render"
    bl_label = "Render Animation"
    bl_description = "Render the active timeline frame range segment by segment, resolving the required Earth data for the selected quality level."

    confirmed: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    _timer = None
    _scene = None
    _props = None
    _segments = None
    _segment_index = 0
    _active_segment = None
    _state = "IDLE"
    _render_seen_active = False
    _render_launch_time = 0.0
    _render_launch_wall_time = 0.0
    _render_result_window_baseline_count = 0
    _render_result_window_peak_count = 0
    _render_result_window_seen = False
    _render_result_window_absent_since_time = 0.0
    _original_frame = 1
    _original_frame_start = 1
    _original_frame_end = 1
    _eevee_temp_displacement_state = None
    _segment_failures = None
    _stop_requested = False
    _stop_notice_sent = False
    _segment_cancel_epoch_before_launch = -1
    _animation_tiles = None
    _animation_resolve_id = ""
    _animation_id = ""
    _texture_quality_mode = "FULL"

    def invoke(self, context, event):
        del event
        if not bool(getattr(self, "confirmed", False)):
            self.confirmed = True
        return self.execute(context)

    def draw(self, _context):
        layout = self.layout
        layout.label(text="Confirm Final Animation Render", icon="RENDER_ANIMATION")
        layout.label(text="Planetka will stream the selected quality level segment by segment.", icon="TEXTURE")

    def _get_selected_texture_quality_mode(self, props):
        return _normalize_animation_render_texture_quality_mode(
            getattr(props, "texture_quality_mode", "PREVIEW")
        )

    def _remove_timer(self, context):
        wm = getattr(context, "window_manager", None)
        if self._timer is not None and wm is not None:
            try:
                wm.event_timer_remove(self._timer)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed removing render timer", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: failed removing render timer", exc_info=True)
        self._timer = None

    def _report_user_stopped_render(self):
        message = "Animation Render stopped by user."
        logger.info("Planetka animation: %s", message)
        print(f"Planetka: {message}")

    def _set_ui_status(self, text="", icon="RENDER_ANIMATION"):
        scene = self._scene
        if scene is None:
            return
        safe_text = str(text or "").strip()
        safe_icon = str(icon or "RENDER_ANIMATION").strip() or "RENDER_ANIMATION"
        try:
            if safe_text:
                scene[ANIMATION_RENDER_STATUS_TEXT_KEY] = safe_text
                scene[ANIMATION_RENDER_STATUS_ICON_KEY] = safe_icon
            else:
                if ANIMATION_RENDER_STATUS_TEXT_KEY in scene:
                    del scene[ANIMATION_RENDER_STATUS_TEXT_KEY]
                if ANIMATION_RENDER_STATUS_ICON_KEY in scene:
                    del scene[ANIMATION_RENDER_STATUS_ICON_KEY]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed updating render UI status", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed updating render UI status", exc_info=True)

    def _count_render_result_windows(self):
        try:
            wm = getattr(getattr(bpy, "context", None), "window_manager", None)
            windows = getattr(wm, "windows", ()) if wm is not None else ()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed reading window manager for render-window tracking", exc_info=True)
            return 0
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed reading window manager for render-window tracking", exc_info=True)
            return 0

        count = 0
        for window in list(windows or ()):
            try:
                screen = getattr(window, "screen", None)
                areas = getattr(screen, "areas", ()) if screen is not None else ()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError, AttributeError):
                continue
            has_render_result = False
            area_types = set()
            for area in list(areas or ()):
                try:
                    area_type = str(getattr(area, "type", "") or "")
                    if area_type:
                        area_types.add(area_type)
                    if area_type != "IMAGE_EDITOR":
                        continue
                    spaces = getattr(area, "spaces", ())
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    continue
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    continue
                for space in list(spaces or ()):
                    try:
                        image = getattr(space, "image", None)
                        image_name = str(getattr(image, "name", "") or "")
                        mode = str(getattr(space, "mode", "") or "").upper()
                    except PLANETKA_RECOVERABLE_EXCEPTIONS:
                        continue
                    except (RuntimeError, TypeError, ValueError, AttributeError):
                        continue
                    if image_name == "Render Result" or mode == "RENDER":
                        has_render_result = True
                        break
                if has_render_result:
                    break
            if not has_render_result and area_types == {"IMAGE_EDITOR"}:
                has_render_result = True
            if has_render_result:
                count += 1
        return int(count)

    def _reset_render_result_window_tracking(self):
        baseline_count = int(max(0, self._count_render_result_windows()))
        self._render_result_window_baseline_count = baseline_count
        self._render_result_window_peak_count = baseline_count
        self._render_result_window_seen = bool(baseline_count > 0)
        self._render_result_window_absent_since_time = 0.0

    def _render_result_window_closed_since_segment_launch(self):
        count = int(max(0, self._count_render_result_windows()))
        baseline = int(max(0, getattr(self, "_render_result_window_baseline_count", 0) or 0))
        peak = int(max(baseline, getattr(self, "_render_result_window_peak_count", baseline) or baseline))
        seen = bool(getattr(self, "_render_result_window_seen", False))

        if count > peak:
            peak = int(count)
            self._render_result_window_peak_count = int(peak)
        if count > baseline or (baseline > 0 and count >= baseline):
            seen = True
            self._render_result_window_seen = True

        if not seen:
            self._render_result_window_absent_since_time = 0.0
            return False

        if peak > baseline:
            closed = count <= baseline
        elif baseline > 0:
            closed = count < baseline
        else:
            closed = count == 0

        if not closed:
            self._render_result_window_absent_since_time = 0.0
            return False

        absent_since = float(getattr(self, "_render_result_window_absent_since_time", 0.0) or 0.0)
        if absent_since <= 0.0:
            absent_since = float(time.monotonic())
            self._render_result_window_absent_since_time = absent_since
            return False
        return (float(time.monotonic()) - absent_since) >= float(max(0.25, ANIMATION_RENDER_USER_STOP_SETTLE_SEC))

    def _render_result_window_open_since_segment_launch(self):
        count = int(max(0, self._count_render_result_windows()))
        baseline = int(max(0, getattr(self, "_render_result_window_baseline_count", 0) or 0))
        peak = int(max(baseline, getattr(self, "_render_result_window_peak_count", baseline) or baseline))
        seen = bool(getattr(self, "_render_result_window_seen", False))

        if count > peak:
            peak = int(count)
            self._render_result_window_peak_count = int(peak)
        if count > baseline or (baseline > 0 and count >= baseline):
            seen = True
            self._render_result_window_seen = True

        if not seen:
            return False
        if baseline > 0:
            return bool(count >= baseline)
        return bool(count > 0)

    def _request_render_stop(self):
        try:
            render_ops = getattr(bpy.ops, "render", None)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            render_ops = None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            render_ops = None

        if render_ops is None:
            return

        cancel_ops = (
            getattr(render_ops, "cancel", None),
            getattr(render_ops, "view_cancel", None),
        )
        for cancel_op in cancel_ops:
            if not callable(cancel_op):
                continue
            try:
                cancel_op()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: render cancel op raised recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: render cancel op raised unexpected exception", exc_info=True)

    def _request_external_stop(self):
        self._stop_requested = True
        self._set_ui_status("Stopping after current render pass", icon="CANCEL")
        try:
            stop_resolve()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed stopping resolve during external stop", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed stopping resolve during external stop", exc_info=True)

    def _read_render_heartbeat(self):
        try:
            return dict(_get_render_job_heartbeat() or {})
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return {}
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return {}
        return {}

    def _is_render_cancelled_since_segment_launch(self):
        heartbeat = self._read_render_heartbeat()
        try:
            last_cancelled_epoch = int(heartbeat.get("last_cancelled_epoch", -1) or -1)
        except (TypeError, ValueError, AttributeError):
            last_cancelled_epoch = -1
        try:
            baseline_epoch = int(getattr(self, "_segment_cancel_epoch_before_launch", -1) or -1)
        except (TypeError, ValueError, AttributeError):
            baseline_epoch = -1
        return bool(last_cancelled_epoch > baseline_epoch)

    def _reset_segment_cancel_epoch_baseline(self):
        heartbeat = self._read_render_heartbeat()
        try:
            self._segment_cancel_epoch_before_launch = int(heartbeat.get("last_cancelled_epoch", -1) or -1)
        except (TypeError, ValueError, AttributeError):
            self._segment_cancel_epoch_before_launch = -1

    def _is_render_handler_running(self):
        try:
            return bool(_is_render_handler_job_active())
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return False
        return False

    def _stop_render_before_cleanup(self):
        if not self._is_render_job_running(allow_app_fallback=True):
            return
        self._request_render_stop()
        wait_started = float(time.monotonic())
        while (float(time.monotonic()) - wait_started) < 2.0:
            if not self._is_render_job_running(allow_app_fallback=True):
                break
            try:
                _update_active_view_layer()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: view-layer update failed while waiting for render stop", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: view-layer update failed while waiting for render stop", exc_info=True)
            time.sleep(0.05)
        if self._is_render_job_running(allow_app_fallback=True):
            logger.warning("Planetka animation: render job remained active during cleanup after cancel/error.")

    def _finalize_success_render_state(self):
        scene = self._scene
        try:
            recover_post_render_state(scene, cancelled=False)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed forcing post-render recovery after success", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed forcing post-render recovery after success", exc_info=True)

        try:
            is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
            if not callable(is_job_running) or not bool(is_job_running("RENDER")):
                return
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return

        wait_started = float(time.monotonic())
        while (float(time.monotonic()) - wait_started) < 2.0:
            try:
                if not bool(is_job_running("RENDER")):
                    return
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return
            except (RuntimeError, TypeError, ValueError, AttributeError):
                return
            try:
                _update_active_view_layer()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: view-layer update failed while draining successful render", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: view-layer update failed while draining successful render", exc_info=True)
            time.sleep(0.05)

        try:
            if bool(is_job_running("RENDER")):
                logger.warning("Planetka animation: residual render job remained active after successful completion; requesting cleanup cancel.")
                self._request_render_stop()
                cancel_wait_started = float(time.monotonic())
                while (float(time.monotonic()) - cancel_wait_started) < 2.0:
                    try:
                        if not bool(is_job_running("RENDER")):
                            break
                    except PLANETKA_RECOVERABLE_EXCEPTIONS:
                        break
                    except (RuntimeError, TypeError, ValueError, AttributeError):
                        break
                    time.sleep(0.05)
                try:
                    recover_post_render_state(scene, cancelled=False)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: failed restoring success state after residual render cleanup", exc_info=True)
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    logger.debug("Planetka animation: failed restoring success state after residual render cleanup", exc_info=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed clearing residual render job after success", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed clearing residual render job after success", exc_info=True)

    def _restore_runtime_state(self):
        try:
            set_final_animation_render_active(False)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed clearing final-render UI lock", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed clearing final-render UI lock", exc_info=True)
        try:
            stop_resolve()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed clearing resolve during restore", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed clearing resolve during restore", exc_info=True)

        scene = self._scene
        props = self._props
        if scene is not None:
            self._set_ui_status("")
            try:
                scene.frame_start = int(self._original_frame_start)
                scene.frame_end = int(self._original_frame_end)
                scene.frame_set(int(self._original_frame))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed restoring frame range", exc_info=True)
            try:
                if ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY in scene:
                    del scene[ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY]
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed clearing EEVEE bump-only runtime flag", exc_info=True)

        if self._eevee_temp_displacement_state:
            try:
                _restore_material_displacement_mode_states(self._eevee_temp_displacement_state)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed restoring Earth displacement mode after render", exc_info=True)
        self._eevee_temp_displacement_state = None
        if _get_active_animation_render_operator() is self:
            _set_active_animation_render_operator(None)

    def _cleanup(self, context, stop_render=False, cancelled=True):
        if bool(stop_render):
            self._stop_render_before_cleanup()
        self._remove_timer(context)
        try:
            recover_post_render_state(self._scene, cancelled=bool(cancelled))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed recovering post-render state during cleanup", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed recovering post-render state during cleanup", exc_info=True)
        self._restore_runtime_state()
        self._scene = None
        self._props = None
        self._segments = []
        self._segment_index = 0
        self._active_segment = None
        self._state = "IDLE"
        self._render_seen_active = False
        self._render_launch_time = 0.0
        self._render_launch_wall_time = 0.0
        self._render_result_window_baseline_count = 0
        self._render_result_window_peak_count = 0
        self._render_result_window_seen = False
        self._render_result_window_absent_since_time = 0.0
        self._stop_requested = False
        self._stop_notice_sent = False
        self._segment_cancel_epoch_before_launch = -1
        self._animation_tiles = []
        self._animation_resolve_id = ""
        self._texture_quality_mode = "FULL"

    def _cancel_with_error(self, context, message):
        text = str(message or "Animation render failed.").strip() or "Animation render failed."
        fail(
            self,
            text,
            code=ErrorCode.RENDER_FAILED,
            logger=logger,
            log_message=f"Planetka animation render failed: {text}",
        )
        self._cleanup(context, stop_render=True)
        return {'CANCELLED'}

    def _finish_success(self, context):
        failures = list(self._segment_failures or ())
        segment_count = len(self._segments or ())
        self._finalize_success_render_state()
        self._cleanup_successful_animation_cache()
        self._cleanup(context, cancelled=False)
        self.report({'INFO'}, f"Animation render complete ({segment_count} segments).")
        if failures:
            self.report({'WARNING'}, f"{len(failures)} segment step(s) reported issues. See console.")
        return {'FINISHED'}

    def _is_render_job_running(self, allow_app_fallback=False):
        # Use handler state as the durable signal. Blender's app job flag is only
        # safe as a short launch/transition fallback because it can stick True.
        handler_active = None
        try:
            handler_active = bool(_is_render_handler_job_active())
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: handler render-state probe failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: handler render-state probe failed", exc_info=True)
        if handler_active is True:
            return True

        if not bool(allow_app_fallback):
            return False

        try:
            is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
            if callable(is_job_running):
                app_running = bool(is_job_running("RENDER"))
                if app_running:
                    return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return False
        return False

    def _dedupe_texture_requests(self, requests):
        deduped = []
        seen = set()
        for request in requests or ():
            if not isinstance(request, (tuple, list)) or len(request) != 4:
                continue
            folder, prefix, filename, exts = request
            key = (
                str(folder or "").strip(),
                str(prefix or "").strip(),
                str(filename or "").strip(),
                tuple(exts or (".exr",)),
            )
            if not key[0] or not key[1] or not key[2] or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    def _segment_texture_requests(self, segment_index):
        segments = list(self._segments or ())
        if segment_index < 0 or segment_index >= len(segments):
            return []
        segment = segments[segment_index]
        if not isinstance(segment, dict):
            return []
        segment_tiles = list(segment.get("tiles", ()) or ())
        if not segment_tiles:
            return []
        return self._dedupe_texture_requests(_build_texture_requests_for_tiles(segment_tiles))

    def _cleanup_completed_segment_cache(self, segment_index):
        segments = list(self._segments or ())
        if int(segment_index) < 0 or int(segment_index) >= len(segments):
            return
        # Keep final-segment textures on disk so the finished scene remains renderable/viewable.
        if int(segment_index) >= (len(segments) - 1):
            return
        current_requests = self._segment_texture_requests(int(segment_index))
        next_requests = self._segment_texture_requests(int(segment_index) + 1)
        if not current_requests:
            return
        keep_keys = set(next_requests or ())
        removed_files = 0
        for request in current_requests:
            if request in keep_keys:
                continue
            folder, prefix, filename, exts = request
            cache_folder = str(get_remote_cache_folder(folder) or "")
            if not cache_folder:
                continue
            for ext in (exts or (".exr",)):
                cache_path = os.path.join(cache_folder, f"{prefix}_{filename}{str(ext or '')}")
                if not os.path.isfile(cache_path):
                    continue
                try:
                    os.remove(cache_path)
                    removed_files += 1
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: failed deleting completed-segment cache file", exc_info=True)
                except (OSError, RuntimeError, TypeError, ValueError):
                    logger.debug("Planetka animation: failed deleting completed-segment cache file", exc_info=True)
        if removed_files > 0:
            logger.debug(
                "Planetka animation: removed %d cache file(s) after segment %d.",
                int(removed_files),
                int(segment_index) + 1,
            )

    def _cleanup_successful_animation_cache(self):
        """Remove temporary animation downloads from the temp cache after success."""
        requests = []
        for index, _segment in enumerate(list(self._segments or ())):
            requests.extend(self._segment_texture_requests(index))
        requests = self._dedupe_texture_requests(requests)
        if not requests:
            return
        removed_files = 0
        removed_bytes = 0
        for folder, prefix, filename, exts in requests:
            cache_folder = str(get_remote_cache_folder(folder) or "")
            if not cache_folder:
                continue
            for ext in (exts or (".exr",)):
                cache_path = os.path.join(cache_folder, f"{prefix}_{filename}{str(ext or '')}")
                if not os.path.isfile(cache_path):
                    continue
                try:
                    file_size = int(os.path.getsize(cache_path))
                except (OSError, RuntimeError, TypeError, ValueError):
                    file_size = 0
                try:
                    os.remove(cache_path)
                    removed_files += 1
                    removed_bytes += max(0, file_size)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: failed deleting successful-render cache file", exc_info=True)
                except (OSError, RuntimeError, TypeError, ValueError):
                    logger.debug("Planetka animation: failed deleting successful-render cache file", exc_info=True)
        if removed_files > 0:
            logger.info(
                "Planetka animation: removed %d temporary animation cache file(s) after successful render (%.2f MB).",
                int(removed_files),
                float(removed_bytes) / (1024.0 * 1024.0),
            )

    def _resolve_segment_frame(self, frame_value, tiles_override=None):
        scene = self._scene
        props = self._props
        frame_int = int(frame_value)
        if scene is None or props is None:
            return False, "Scene context became unavailable."
        try:
            scene.frame_set(frame_int)
            _update_active_view_layer()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        _apply_keyed_runtime_scene_state(scene, props)
        op_kwargs = {
            "scope_mode": "CAMERA",
            "defer_download": False,
            "texture_quality_mode_override": _normalize_animation_render_texture_quality_mode(
                getattr(self, "_texture_quality_mode", "PREVIEW")
            ),
            # Final Animation downloads only the current segment before rendering it.
            # EL/WT/PO support layers intentionally fall back if absent.
            "capture_download_progress": True,
            "streaming_feature": "final_animation_render",
        }
        normalized_tiles = [str(tile or "").strip() for tile in (tiles_override or ()) if str(tile or "").strip()]
        if normalized_tiles:
            try:
                op_kwargs["tiles_override_json"] = json.dumps(normalized_tiles, separators=(",", ":"))
            except (TypeError, ValueError):
                logger.debug("Planetka animation: failed serializing segment tile override", exc_info=True)
        try:
            result = bpy.ops.planetka_public.load_textures(**op_kwargs)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return False, f"Resolve failed at frame {frame_int:04d}: {exc}"
        except (RuntimeError, TypeError, ValueError) as exc:
            return False, f"Resolve failed at frame {frame_int:04d}: {exc}"
        if "FINISHED" not in result:
            return False, f"Resolve returned {result} at frame {frame_int:04d}."
        missing_images = _count_missing_tile_loading_images(material_name="Planetka Earth Material")
        if int(missing_images) > 0:
            return (
                False,
                f"Resolve left {int(missing_images)} missing shader image assignment(s) at frame {frame_int:04d}.",
            )
        try:
            cleanup_planetka_unused_data()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        return True, ""

    def _launch_segment_render(self, segment):
        scene = self._scene
        if scene is None:
            return False, "Scene context became unavailable."
        self._enforce_eevee_bump_only_for_segment()
        if self._is_render_job_running(allow_app_fallback=True):
            return None, "Blender render job is still settling."
        heartbeat = self._read_render_heartbeat()
        try:
            self._segment_cancel_epoch_before_launch = int(heartbeat.get("last_cancelled_epoch", -1) or -1)
        except (TypeError, ValueError, AttributeError):
            self._segment_cancel_epoch_before_launch = -1
        self._reset_render_result_window_tracking()
        start = int(segment.get("start", 1))
        end = int(segment.get("end", start))
        try:
            scene.frame_start = int(start)
            scene.frame_end = int(end)
            scene.frame_set(int(start))
            _update_active_view_layer()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        last_result = None
        attempts = int(max(1, ANIMATION_RENDER_LAUNCH_RETRY_MAX_ATTEMPTS))
        attempt = 0
        while True:
            attempt += 1
            try:
                # Mark launch wall-time immediately before invoking Blender render op.
                # This avoids false "cancelled" detection on fast first frames.
                self._render_launch_wall_time = time.time()
                result = bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return False, f"Render launch failed for frames {start:04d}-{end:04d}: {exc}"
            except (RuntimeError, TypeError, ValueError) as exc:
                return False, f"Render launch failed for frames {start:04d}-{end:04d}: {exc}"
            last_result = result
            if "RUNNING_MODAL" in result or "FINISHED" in result:
                self._render_result_window_closed_since_segment_launch()
                return True, ""
            if "CANCELLED" in result:
                # Blender can transiently return CANCELLED while previous render teardown is settling.
                render_busy = bool(self._is_render_job_running(allow_app_fallback=True))
                if render_busy:
                    return None, "Blender render job is still settling."
                retry_allowed = int(attempt) < int(attempts)
                if retry_allowed:
                    time.sleep(0.2)
                    continue
            break
        return False, f"Render launch returned {last_result} for frames {start:04d}-{end:04d}."

    def _attempt_launch_active_segment(self, context):
        active_segment = self._active_segment
        if not isinstance(active_segment, dict):
            return self._cancel_with_error(
                context,
                "Render segment state was lost before launch.",
            )
        seg_start = int(active_segment.get("start", 1))
        seg_end = int(active_segment.get("end", seg_start))
        if self._is_render_cancelled_since_segment_launch():
            self._report_user_stopped_render()
            self._cleanup(context, stop_render=False)
            return {'CANCELLED'}
        ok, message = self._launch_segment_render(active_segment)
        if ok is None:
            self._state = "LAUNCH"
            self._set_ui_status(
                f"Waiting to render segment {seg_start:04d}-{seg_end:04d}",
                icon="SORTTIME",
            )
            return {'RUNNING_MODAL'}
        if not ok:
            return self._cancel_with_error(context, message)
        self._set_ui_status(
            f"Rendering segment {seg_start:04d}-{seg_end:04d}",
            icon="RENDER_ANIMATION",
        )
        self._state = "RENDER"
        self._render_seen_active = False
        self._render_launch_time = time.monotonic()
        return {'RUNNING_MODAL'}

    def _segment_output_status(self, segment, min_mtime=None):
        scene = self._scene
        if scene is None or _is_movie_output(scene):
            return 0, 0
        start = int(segment.get("start", 1))
        end = int(segment.get("end", start))
        total = int(max(0, (end - start) + 1))
        min_mtime_value = None
        if min_mtime is not None:
            try:
                min_mtime_value = float(min_mtime)
            except (TypeError, ValueError):
                min_mtime_value = None
        complete = 0
        for frame in range(start, end + 1):
            try:
                frame_path = bpy.path.abspath(scene.render.frame_path(frame=int(frame)))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed resolving segment frame output path", exc_info=True)
                return complete, total
            if not frame_path or not os.path.isfile(frame_path):
                continue
            if min_mtime_value is not None:
                try:
                    frame_mtime = float(os.path.getmtime(frame_path))
                except (OSError, ValueError, TypeError):
                    continue
                if frame_mtime < (min_mtime_value - 0.2):
                    continue
            complete += 1
        return int(complete), int(total)

    def _is_eevee_render_engine(self, scene):
        if scene is None:
            return False
        render = getattr(scene, "render", None)
        try:
            engine = str(getattr(render, "engine", "") or "").strip().upper()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            engine = ""
        return engine in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}

    def _enforce_eevee_bump_only_for_segment(self):
        scene = self._scene
        if not self._is_eevee_render_engine(scene):
            return
        try:
            _set_earth_surface_materials_bump_only()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed enforcing EEVEE bump-only mode after segment resolve", exc_info=True)
        if scene is not None:
            try:
                scene[ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY] = True
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed reasserting EEVEE bump-only runtime flag", exc_info=True)

    def _enforce_cycles_simple_subdivision_for_segment(self):
        scene = self._scene
        if scene is None:
            return
        if self._is_eevee_render_engine(scene):
            return
        earth = get_earth_object()
        _enforce_cycles_simple_subdivision_on_object(scene, earth)

    def execute(self, context):
        if not bool(getattr(self, "confirmed", False)) and not bool(getattr(bpy.app, "background", False)):
            self.confirmed = True
        if _cancel_if_animation_render_active(self, "Render Animation"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        if _quick_preview_is_prepared(scene):
            try:
                clear_prepared_animation_assets(scene)
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    f"Failed to clear Quick Preview before rendering: {exc}",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation render failed clearing Quick Preview state",
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                return fail(
                    self,
                    f"Failed to clear Quick Preview before rendering: {exc}",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
        camera = getattr(scene, "camera", None)
        if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
            return fail(
                self,
                "Scene camera is missing. Set an active Camera and retry.",
                code=ErrorCode.PRECHECK_FAILED,
                logger=logger,
            )

        selected_texture_quality_mode = self._get_selected_texture_quality_mode(props)
        prefs = get_prefs()
        if not _require_animation_texture_quality_access(self, prefs, selected_texture_quality_mode):
            return {'CANCELLED'}
        if not _ensure_remote_auth_ready_for_final_render(self, prefs):
            return {'CANCELLED'}
        if _is_movie_output(scene):
            return fail(
                self,
                "Render Animation requires image-sequence output (PNG/EXR).",
                code=ErrorCode.RENDER_FAILED,
                logger=logger,
            )

        try:
            runtime_status = get_resolve_runtime_status(scene=scene) or {}
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            runtime_status = {}
        if bool(runtime_status.get("running", False)):
            self.report({'INFO'}, "Waiting for Planetka resolve to finish before Animation Render starts.")
            idle, final_status = _wait_for_resolve_idle(scene, timeout_sec=90.0, poll_sec=0.1)
            if not idle:
                try:
                    final_code = str((final_status or {}).get("code", "") or "").strip().upper()
                except (TypeError, ValueError, AttributeError):
                    final_code = ""
                if final_code == "APPLYING":
                    self.report(
                        {'WARNING'},
                        (
                            "Queued resolve finalize appears stalled; "
                            "attempting automatic refresh before starting Animation Render."
                        ),
                    )
                    try:
                        stop_resolve()
                    except PLANETKA_RECOVERABLE_EXCEPTIONS:
                        logger.debug("Planetka animation: failed refreshing stuck pre-render resolve", exc_info=True)
                    except (RuntimeError, TypeError, ValueError, AttributeError):
                        logger.debug("Planetka animation: failed refreshing stuck pre-render resolve", exc_info=True)
                    idle, final_status = _wait_for_resolve_idle(scene, timeout_sec=10.0, poll_sec=0.1)
            if not idle:
                status_text = str((final_status or {}).get("text", "Resolve running") or "Resolve running")
                return fail(
                    self,
                    f"Cannot start Animation Render while resolve is active ({status_text}).",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )

        try:
            stop_resolve()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: failed stopping resolve for final render", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed stopping resolve for final render", exc_info=True)

        render_start, render_end = _active_timeline_frame_range(scene)
        frame_start = int(render_start)
        frame_end = int(render_end)
        if frame_end < frame_start:
            return fail(
                self,
                f"Invalid frame range: {frame_start}-{frame_end}.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        original_frame = int(getattr(scene, "frame_current", frame_start))
        render = getattr(scene, "render", None)
        eevee_temp_displacement_state = None
        original_frame_start = int(getattr(scene, "frame_start", frame_start))
        original_frame_end = int(getattr(scene, "frame_end", frame_end))

        segments = []
        try:
            segment_plan = _plan_animation_segments(
                scene,
                frame_start,
                frame_end,
                frame_step=1,
                texture_quality_mode_override=str(selected_texture_quality_mode),
                apply_segment_horizon_hysteresis=bool(ANIMATION_HORIZON_SEGMENT_HYSTERESIS_ENABLED),
                enable_adaptive_horizon_precision=True,
            )
            segments = list(segment_plan.segments or ())
            if not segments:
                return self._cancel_with_error(
                    context,
                    "No animation segments were generated for the selected frame range.",
                )
            animation_id = ""

            try:
                render_engine = str(getattr(render, "engine", "") or "").strip().upper()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                render_engine = ""
            if render_engine in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
                eevee_materials = _earth_surface_materials()
                eevee_temp_displacement_state = _capture_material_displacement_mode_states(eevee_materials)
                _set_earth_surface_materials_bump_only()
                try:
                    scene[ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY] = True
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: failed setting EEVEE bump-only runtime flag", exc_info=True)
            self._scene = scene
            self._props = props
            self._segments = list(segments)
            self._segment_index = 0
            self._active_segment = None
            self._state = "RESOLVE"
            self._render_seen_active = False
            self._render_launch_time = 0.0
            self._render_launch_wall_time = 0.0
            self._render_result_window_baseline_count = 0
            self._render_result_window_peak_count = 0
            self._render_result_window_seen = False
            self._render_result_window_absent_since_time = 0.0
            self._original_frame = int(original_frame)
            self._original_frame_start = int(original_frame_start)
            self._original_frame_end = int(original_frame_end)
            self._eevee_temp_displacement_state = eevee_temp_displacement_state
            self._segment_failures = []
            self._stop_requested = False
            self._stop_notice_sent = False
            self._reset_segment_cancel_epoch_baseline()
            self._animation_tiles = []
            self._animation_resolve_id = f"anim-{int(time.time() * 1000)}"
            self._texture_quality_mode = _normalize_animation_render_texture_quality_mode(selected_texture_quality_mode)
            try:
                set_final_animation_render_active(True)
                _set_active_animation_render_operator(self)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed setting final-render UI lock", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: failed setting final-render UI lock", exc_info=True)
            self._set_ui_status("Preparing animation data", icon="IMPORT")

            wm = getattr(context, "window_manager", None)
            if wm is None:
                self._restore_runtime_state()
                return fail(
                    self,
                    "Window manager unavailable. Render Animation requires Blender UI mode.",
                    code=ErrorCode.RENDER_FAILED,
                    logger=logger,
                )
            self._timer = wm.event_timer_add(0.2, window=context.window)
            wm.modal_handler_add(self)
            self.report({'INFO'}, f"Render Animation started ({len(self._segments)} segments).")
            return {'RUNNING_MODAL'}
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self._restore_runtime_state()
            return fail(
                self,
                f"Animation render failed: {exc}",
                code=ErrorCode.RENDER_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka full animation render setup failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            self._restore_runtime_state()
            return fail(
                self,
                f"Animation render failed: {exc}",
                code=ErrorCode.RENDER_FAILED,
                logger=logger,
            )

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        if bool(self._stop_requested):
            if not bool(self._stop_notice_sent):
                self.report({'INFO'}, "Stopping Final Animation Render...")
                self._stop_notice_sent = True
            self._set_ui_status("Stopping after current render pass", icon="CANCEL")
            if self._state != "RENDER":
                self._report_user_stopped_render()
                self._cleanup(context, stop_render=False)
                return {'CANCELLED'}

        scene = self._scene
        if scene is None:
            return self._cancel_with_error(context, "Animation scene context was lost.")

        if self._state == "RESOLVE":
            if self._segment_index >= len(self._segments or ()):
                return self._finish_success(context)
            try:
                stop_resolve()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: failed stopping resolve download before segment resolve", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: failed stopping resolve download before segment resolve", exc_info=True)
            segment = dict((self._segments or [])[self._segment_index])
            self._active_segment = segment
            seg_start = int(segment.get("start", 1))
            seg_end = int(segment.get("end", seg_start))
            self._set_ui_status(f"Resolving segment {seg_start:04d}-{seg_end:04d}", icon="TEXTURE")
            print(f"[Planetka] Segment {self._segment_index + 1}/{len(self._segments)}: resolve {seg_start:04d}-{seg_end:04d}")
            ok, message = self._resolve_segment_frame(seg_start, tiles_override=segment.get("tiles", ()))
            if not ok:
                return self._cancel_with_error(context, message)
            self._enforce_eevee_bump_only_for_segment()
            self._enforce_cycles_simple_subdivision_for_segment()
            return self._attempt_launch_active_segment(context)

        if self._state == "LAUNCH":
            return self._attempt_launch_active_segment(context)

        if self._state == "RENDER":
            elapsed = float(time.monotonic() - float(self._render_launch_time))
            app_fallback_allowed = elapsed <= float(max(0.0, ANIMATION_RENDER_APP_JOB_FALLBACK_GRACE_SEC))
            running = self._is_render_job_running(allow_app_fallback=app_fallback_allowed)
            active_segment = self._active_segment
            if not isinstance(active_segment, dict):
                return self._cancel_with_error(
                    context,
                    "Render segment state was lost before completion.",
                )
            output_count, output_total = self._segment_output_status(
                active_segment,
                min_mtime=self._render_launch_wall_time,
            )
            outputs_complete = bool(output_total > 0 and output_count >= output_total)
            if outputs_complete:
                if self._is_render_handler_running():
                    self._render_seen_active = True
                    return {'RUNNING_MODAL'}
                if bool(self._stop_requested):
                    self._report_user_stopped_render()
                    self._cleanup(context, stop_render=False)
                    return {'CANCELLED'}
                self._cleanup_completed_segment_cache(self._segment_index)
                self._segment_index += 1
                self._active_segment = None
                self._state = "RESOLVE"
                self._render_seen_active = False
                self._render_result_window_baseline_count = 0
                self._render_result_window_peak_count = 0
                self._render_result_window_seen = False
                self._render_result_window_absent_since_time = 0.0
                return {'RUNNING_MODAL'}
            if running:
                self._render_seen_active = True
                if (
                    self._render_result_window_closed_since_segment_launch()
                    and not self._is_render_handler_running()
                ):
                    self._report_user_stopped_render()
                    self._cleanup(context, stop_render=False)
                    return {'CANCELLED'}
                return {'RUNNING_MODAL'}
            if (not self._render_seen_active) and elapsed < 0.75:
                return {'RUNNING_MODAL'}
            if self._is_render_cancelled_since_segment_launch():
                self._report_user_stopped_render()
                self._cleanup(context, stop_render=False)
                return {'CANCELLED'}
            if not outputs_complete:
                cancelled_by_user = (
                    bool(self._stop_requested)
                    or self._is_render_cancelled_since_segment_launch()
                )
                render_window_closed_by_user = bool(self._render_result_window_closed_since_segment_launch())
                if cancelled_by_user or render_window_closed_by_user:
                    self._report_user_stopped_render()
                    self._cleanup(context, stop_render=False)
                    return {'CANCELLED'}
                render_window_close_pending = bool(
                    getattr(self, "_render_result_window_seen", False)
                    and float(getattr(self, "_render_result_window_absent_since_time", 0.0) or 0.0) > 0.0
                )
                if render_window_close_pending:
                    return {'RUNNING_MODAL'}
                if self._render_result_window_open_since_segment_launch():
                    return {'RUNNING_MODAL'}
                if elapsed < float(max(0.75, ANIMATION_RENDER_OUTPUT_SETTLE_TIMEOUT_SEC)):
                    return {'RUNNING_MODAL'}
                seg_start = int(active_segment.get("start", 1))
                seg_end = int(active_segment.get("end", seg_start))
                if int(output_count) <= 0:
                    return self._cancel_with_error(
                        context,
                        f"Render segment did not start writing output ({seg_start:04d}-{seg_end:04d}).",
                    )
                return self._cancel_with_error(
                    context,
                    (
                        "Render segment stopped before all output frames were written "
                        f"({seg_start:04d}-{seg_end:04d}, saved {int(output_count)}/{int(output_total)})."
                    ),
                )
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}


class PLANETKA_OT_AnimationStop(bpy.types.Operator):
    bl_idname = "planetka_public.animation_stop"
    bl_label = "Stop Animation Render"
    bl_description = "Stop the active Final Animation Render after the current render operation and restore Planetka render state."

    def execute(self, context):
        active_operator = _get_active_animation_render_operator()
        if active_operator is not None:
            try:
                active_operator._request_external_stop()
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    "Animation Render could not be stopped cleanly.",
                    code=ErrorCode.RENDER_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation external stop failed",
                )
            except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
                return fail(
                    self,
                    "Animation Render could not be stopped cleanly.",
                    code=ErrorCode.RENDER_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation external stop failed",
                )
            self.report({'INFO'}, "Stopping Final Animation Render...")
            return {'FINISHED'}

        try:
            stop_resolve()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: fallback stop pipeline cleanup failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: fallback stop pipeline cleanup failed", exc_info=True)
        try:
            recover_post_render_state(getattr(context, "scene", None), cancelled=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: fallback stop recovery failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: fallback stop recovery failed", exc_info=True)
        try:
            set_final_animation_render_active(False)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: fallback stop lock cleanup failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: fallback stop lock cleanup failed", exc_info=True)
        _set_active_animation_render_operator(None)
        self.report({'INFO'}, "Final Animation Render stopped.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationMakeReady(bpy.types.Operator):
    bl_idname = "planetka_public.animation_make_ready"
    bl_label = "Build Quick Preview"
    bl_description = (
        "Download Preview-quality data for all animation segments, build preview segment meshes/materials, "
        "and animate their visibility for smooth timeline playback."
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Build Quick Preview"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        try:
            prefs = get_prefs()
            if prefs is None:
                return fail(
                    self,
                    "Planetka preferences not available.",
                    code=ErrorCode.RESOLVE_PREFS_MISSING,
                    logger=logger,
                )
            # Quick Preview follows the active timeline range, including Blender preview range when enabled.
            start_frame, end_frame = _active_timeline_frame_range(scene)
            if int(end_frame) < int(start_frame):
                return fail(
                    self,
                    f"Invalid frame range: {int(start_frame)}-{int(end_frame)}.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )

            frame_step = 1
            try:
                segment_plan = _plan_animation_segments(
                    scene,
                    start_frame,
                    end_frame,
                    frame_step,
                    texture_quality_mode_override="PREVIEW",
                )
                segments = list(segment_plan.segments or ())
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    f"Segment analysis failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation segment analysis failed",
                )

            if not segments:
                return fail(
                    self,
                    "No animation segments were generated for the selected frame range.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )

            max_segments = min(
                int(QUICK_PREVIEW_MAX_SEGMENTS),
                max(1, int(getattr(props, "anim_prepare_max_segments", QUICK_PREVIEW_MAX_SEGMENTS))),
            )
            if len(segments) > max_segments:
                return fail(
                    self,
                    (
                        f"Animation requires {len(segments)} segments, exceeding Preview limit {max_segments}."
                    ),
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )

            texture_bytes = _estimate_texture_bytes_for_segments(segments)
            texture_mb = float(texture_bytes) / (1024.0 * 1024.0)
            max_texture_mb = float(getattr(props, "anim_prepare_max_textures_mb", 4096.0))
            if max_texture_mb > 0.0 and texture_mb > max_texture_mb:
                return fail(
                    self,
                    (
                        f"Prepared animation needs about {texture_mb:.0f} MB textures, "
                        f"exceeding limit {max_texture_mb:.0f} MB."
                    ),
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )

            try:
                created_count = _prepare_segments(
                    scene,
                    segments,
                    start_frame,
                    end_frame,
                    texture_quality_mode="PREVIEW",
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    f"Preparing animation render setup failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation make-ready failed",
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                return fail(
                    self,
                    f"Preparing animation render setup failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )

            _store_quick_preview_scene_state(
                scene,
                segments=len(segments),
                texture_mb=float(texture_mb),
                frame_start=int(start_frame),
                frame_end=int(end_frame),
            )
            self.report(
                {'INFO'},
                (
                    f"Quick Preview ready: {len(segments)} segments "
                    f"({created_count} mesh assets), ~{texture_mb:.0f} MB textures. "
                    "Preview quality preloaded; use timeline playback."
                ),
            )
            return {'FINISHED'}
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Preparing animation render setup failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka animation make-ready failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Preparing animation render setup failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )
