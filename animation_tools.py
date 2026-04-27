import importlib
import json
import math
import os
import time
from dataclasses import dataclass

import bpy
from bpy.props import EnumProperty, IntProperty
from mathutils import Euler, Matrix, Quaternion, Vector

from .auth import allows_animation_render_for_context
from .error_utils import PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS, PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .r2_source import (
    get_remote_cache_folder,
    is_remote_source_configured,
    plan_resolve_downloads,
    prefetch_resolve_downloads,
)
from .state import (
    _apply_sunlight_from_props,
    _apply_sunlight_strength_from_props,
    create_temp_mesh,
    cleanup_planetka_unused_data,
    logger,
    mark_navigation_camera_control_signature,
    remove_object_and_unused_mesh,
    resume_navigation_camera_control_sync,
    resume_navigation_shot_updates,
    suspend_navigation_camera_control_sync,
    suspend_navigation_shot_updates,
    update_navigation_shot,
)
from . import shader_utils


ANIMATION_COLLECTION_NAME = "Planetka Animation Preview"
LEGACY_ANIMATION_COLLECTION_NAMES = ("Planetka Animation Prepared",)
ANIMATION_SEGMENT_OBJECT_PREFIX = "Planetka Anim Preview"
ANIMATION_SEGMENT_MATERIAL_PREFIX = "Planetka Anim Material"
ANIMATION_SEGMENT_TAG_KEY = "planetka_animation_segment"
ANIMATION_SEGMENT_GROUP_TAG_KEY = "planetka_animation_segment_group"
ANIMATION_SEGMENT_MATERIAL_TAG_KEY = "planetka_animation_segment_material"
ANIMATION_STATS_SEGMENTS_KEY = "planetka_anim_prepared_segments"
ANIMATION_STATS_TEXTURE_MB_KEY = "planetka_anim_prepared_textures_mb"
ANIMATION_STATS_START_KEY = "planetka_anim_prepared_start_frame"
ANIMATION_STATS_END_KEY = "planetka_anim_prepared_end_frame"
ANIMATION_PREPARED_AUTO_RESOLVE_PREV_KEY = "planetka_anim_prepared_auto_resolve_prev"
ANIMATION_BASE_SURFACE_NAME_KEY = "planetka_anim_base_surface_name"
ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY = "planetka_anim_base_surface_hide_render"
ANIMATION_BASE_SURFACE_HIDE_VIEWPORT_KEY = "planetka_anim_base_surface_hide_viewport"
QUICK_PREVIEW_SCENE_STATE_KEYS = (
    ANIMATION_STATS_SEGMENTS_KEY,
    ANIMATION_STATS_TEXTURE_MB_KEY,
    ANIMATION_STATS_START_KEY,
    ANIMATION_STATS_END_KEY,
    ANIMATION_PREPARED_AUTO_RESOLVE_PREV_KEY,
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
_TILE_UTILS_MODULE = None
_OPERATORS_MODULE = None
_STREAMING_UTILS_MODULE = None


@dataclass
class AnimationSegmentPlan:
    frame_start: int
    frame_end: int
    frame_step: int
    texture_quality_mode: str
    segments: list


def _format_frame_timecode(scene, frame_value):
    try:
        render = getattr(scene, "render", None)
        fps = float(getattr(render, "fps", 24.0))
        fps_base = float(getattr(render, "fps_base", 1.0))
        effective_fps = fps / max(fps_base, 1e-9)
        if effective_fps <= 0.0:
            return "00:00:00.00"
        total_seconds = max(0.0, float(frame_value)) / effective_fps
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return "00:00:00.00"

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    centiseconds = int(round((total_seconds - int(total_seconds)) * 100.0))
    if centiseconds >= 100:
        centiseconds = 0
        seconds += 1
        if seconds >= 60:
            seconds = 0
            minutes += 1
            if minutes >= 60:
                minutes = 0
                hours += 1
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _require_commercial_animation_render_access(operator, prefs=None):
    del operator, prefs
    return True


def _require_full_animation_access(operator, prefs=None):
    if allows_animation_render_for_context(prefs):
        return True
    if operator is not None:
        operator.report({'ERROR'}, "Final Animation Rendering requires Full Quality texture access.")
    return False


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


def _get_tile_utils():
    global _TILE_UTILS_MODULE
    if _TILE_UTILS_MODULE is None:
        module_name = f"{__package__}.tile_utils" if __package__ else "tile_utils"
        try:
            _TILE_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _TILE_UTILS_MODULE = False
    return _TILE_UTILS_MODULE or None


def _get_operators_module():
    global _OPERATORS_MODULE
    if _OPERATORS_MODULE is None:
        module_name = f"{__package__}.operators" if __package__ else "operators"
        try:
            _OPERATORS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _OPERATORS_MODULE = False
    return _OPERATORS_MODULE or None


def _get_streaming_utils_module():
    global _STREAMING_UTILS_MODULE
    if _STREAMING_UTILS_MODULE is None:
        module_name = f"{__package__}.streaming_utils" if __package__ else "streaming_utils"
        try:
            _STREAMING_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _STREAMING_UTILS_MODULE = False
    return _STREAMING_UTILS_MODULE or None


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


def _iter_texture_paths_for_tile(base_path, tile):
    parsed = _parse_tile(tile)
    if not parsed:
        return
    _x, _y, z, d = parsed
    for texture_type in TEXTURE_TYPES:
        tile_code = tile
        if texture_type == "EL" and int(z) == 1 and int(d) == 2:
            tile_code = tile.replace("_d002", "_d001")
        extension = TEXTURE_EXTENSIONS.get(texture_type, ".exr")
        path = os.path.join(base_path, texture_type, f"{texture_type}_{tile_code}{extension}")
        yield path


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


def _estimate_local_texture_bytes_for_requests(base_path, requests):
    unique_paths = set()
    total_bytes = 0
    for request in requests or ():
        if not isinstance(request, (tuple, list)) or len(request) != 4:
            continue
        folder, prefix, filename, extensions = request
        folder = str(folder or "").strip()
        prefix = str(prefix or "").strip()
        filename = str(filename or "").strip()
        if not folder or not prefix or not filename:
            continue
        exts = tuple(extensions or (".exr",))
        for ext in exts:
            path = os.path.join(base_path, folder, f"{prefix}_{filename}{str(ext or '')}")
            abs_path = os.path.abspath(path)
            if abs_path in unique_paths:
                continue
            unique_paths.add(abs_path)
            if os.path.isfile(abs_path):
                try:
                    total_bytes += int(os.path.getsize(abs_path))
                except (OSError, TypeError, ValueError):
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    return int(total_bytes)


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


def _estimate_remote_download_bytes_for_requests(requests):
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

    if not deduped:
        return 0, 0

    try:
        plan = plan_resolve_downloads(deduped)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        plan = {}
    except (RuntimeError, TypeError, ValueError):
        plan = {}

    return (
        int(max(0, int(plan.get("planned_total_bytes", 0) or 0))),
        int(max(0, int(plan.get("unknown_file_count", 0) or 0))),
    )


def _build_texture_requests_for_tiles(tiles):
    requests = []
    for tile in tiles or ():
        if not _is_land_tile(tile):
            continue
        requests.extend(_iter_texture_requests_for_tile(tile))
    return requests


def _estimate_texture_bytes_for_segments(segments, base_path):
    requests = []
    for segment in segments or ():
        requests.extend(_build_texture_requests_for_tiles(segment.get("tiles", ())))

    if is_remote_source_configured(base_path) and (not base_path or not os.path.isdir(base_path)):
        total_bytes, _unknown = _estimate_remote_texture_bytes_for_requests(requests)
        return int(total_bytes)
    return int(_estimate_local_texture_bytes_for_requests(base_path, requests))


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
    tile_utils = _get_tile_utils()
    if tile_utils is None:
        raise RuntimeError("Tile utilities are unavailable.")
    scene.frame_set(int(frame))
    try:
        bpy.context.view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    try:
        return list(
            tile_utils.main(
                scope_mode="CAMERA",
                texture_quality_mode_override=texture_quality_mode_override,
            )
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: tile resolve failed at frame %s", frame, exc_info=True)
        return []
    except RuntimeError:
        logger.debug("Planetka animation: tile resolve runtime failure at frame %s", frame, exc_info=True)
        return []


def _build_segments(scene, frame_start, frame_end, frame_step, texture_quality_mode_override=None):
    frames = list(range(int(frame_start), int(frame_end) + 1, max(1, int(frame_step))))
    if not frames:
        return []

    segments = []
    current_start = int(frames[0])
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
        sampled_tiles = _canonical_tiles(
            _resolve_tiles_for_frame(
                scene,
                frame,
                texture_quality_mode_override=texture_quality_mode_override,
            )
        )
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
            current_tiles = sampled_tiles

    segments.append(
        {
            "index": int(segment_index),
            "start": int(current_start),
            "end": int(frames[-1]),
            "tiles": list(current_tiles),
        }
    )
    return segments


def _plan_animation_segments(scene, frame_start, frame_end, frame_step=1, texture_quality_mode_override=None):
    safe_start = int(frame_start)
    safe_end = int(frame_end)
    safe_step = max(1, int(frame_step))
    try:
        original_frame = int(getattr(scene, "frame_current", safe_start))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        original_frame = int(safe_start)
    try:
        segments = _build_segments(
            scene,
            safe_start,
            safe_end,
            safe_step,
            texture_quality_mode_override=texture_quality_mode_override,
        )
    finally:
        try:
            scene.frame_set(int(original_frame))
            bpy.context.view_layer.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
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
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        prepared_segments = 0
    if prepared_segments > 0:
        return True
    for obj in tuple(bpy.data.objects):
        try:
            if bool(obj.get(ANIMATION_SEGMENT_TAG_KEY, False)):
                return True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            continue
    return False


def _store_quick_preview_scene_state(scene, segments, texture_mb, frame_start, frame_end, auto_resolve_value):
    if scene is None:
        return
    scene[ANIMATION_STATS_SEGMENTS_KEY] = int(max(0, int(segments)))
    scene[ANIMATION_STATS_TEXTURE_MB_KEY] = float(max(0.0, float(texture_mb)))
    scene[ANIMATION_STATS_START_KEY] = int(frame_start)
    scene[ANIMATION_STATS_END_KEY] = int(frame_end)
    try:
        scene[ANIMATION_PREPARED_AUTO_RESOLVE_PREV_KEY] = bool(auto_resolve_value)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)


def _segment_display_name(segment_start, segment_end):
    try:
        start = int(segment_start)
        end = int(segment_end)
    except (TypeError, ValueError):
        start = 0
        end = 0
    return f"Planetka Earth Surface Frames {start:04d}-{end:04d}"


def _estimate_texture_bytes_for_tiles(tiles, base_path):
    requests = _build_texture_requests_for_tiles(tiles)
    if is_remote_source_configured(base_path) and (not base_path or not os.path.isdir(base_path)):
        total_bytes, unknown_files = _estimate_remote_texture_bytes_for_requests(requests)
        if int(total_bytes) <= 0 and int(unknown_files) > 0:
            return None
        return int(total_bytes)
    return int(_estimate_local_texture_bytes_for_requests(base_path, requests))


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
    props = getattr(scene, "planetka", None) if scene is not None else None
    try:
        previous_auto_resolve = scene.get(ANIMATION_PREPARED_AUTO_RESOLVE_PREV_KEY, None) if scene is not None else None
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        previous_auto_resolve = None
    except (RuntimeError, TypeError, ValueError):
        previous_auto_resolve = None
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

    collection_names = [str(ANIMATION_COLLECTION_NAME or "").strip()]
    collection_names.extend(
        str(name or "").strip()
        for name in tuple(LEGACY_ANIMATION_COLLECTION_NAMES or ())
        if str(name or "").strip()
    )
    for collection_name in dict.fromkeys(collection_names):
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

    if props is not None and previous_auto_resolve is not None:
        try:
            props.auto_resolve = bool(previous_auto_resolve)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

    try:
        shader_utils.cleanup_planetka_images(force_remove_datablocks=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: cleanup images failed", exc_info=True)


def _prepare_segments(scene, segments, frame_start, frame_end, base_path="", texture_quality_mode="PREVIEW"):
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
            streaming_utils = _get_streaming_utils_module()
            if streaming_utils is not None:
                prepare_streaming_fn = getattr(streaming_utils, "prepare_resolve_streaming_for_visible_tiles", None)
                if callable(prepare_streaming_fn):
                    stream_payload = prepare_streaming_fn(
                        segment_tiles,
                        str(base_path or ""),
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
                allow_slot_shrink=True,
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


def _clamp_latitude(lat):
    return max(-89.9999, min(89.9999, float(lat)))


def _normalize_longitude(lon):
    value = (float(lon) + 180.0) % 360.0
    return value - 180.0


def _normalize_angle_deg(value):
    return ((float(value) + 180.0) % 360.0) - 180.0


def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)


def _lerp_angle_deg(a, b, t):
    delta = _normalize_angle_deg(float(b) - float(a))
    return _normalize_angle_deg(float(a) + (delta * float(t)))


def _eased_progress(t, motion_curve):
    value = max(0.0, min(1.0, float(t)))
    curve = str(motion_curve or "EASE_IN_OUT").upper()
    if curve == "LINEAR":
        return value
    if curve == "EASE_IN":
        return value * value
    if curve == "EASE_OUT":
        inv = 1.0 - value
        return 1.0 - (inv * inv)
    # Use smootherstep for C2 continuity (smoother acceleration/deceleration at segment ends).
    return (value * value * value) * (value * ((value * 6.0) - 15.0) + 10.0)


def _interpolate_shot(start, end, t):
    return {
        "lon": _normalize_longitude(_lerp_angle_deg(start.get("lon", 0.0), end.get("lon", 0.0), t)),
        "lat": _clamp_latitude(_lerp(start.get("lat", 0.0), end.get("lat", 0.0), t)),
        "alt_km": max(0.0, _lerp(start.get("alt_km", 0.0), end.get("alt_km", 0.0), t)),
        # Heading/roll must stay continuous (no wrap to [-180, 180]) to avoid jumps.
        "heading_deg": _lerp(start.get("heading_deg", 0.0), end.get("heading_deg", 0.0), t),
        "tilt_deg": max(-90.0, min(90.0, _lerp(start.get("tilt_deg", 0.0), end.get("tilt_deg", 0.0), t))),
        "roll_deg": _lerp(start.get("roll_deg", 0.0), end.get("roll_deg", 0.0), t),
    }


def _compute_navigation_pose(scene, shot, look_target_override=None, up_hint_override=None):
    operators = _get_operators_module()
    if operators is None:
        raise RuntimeError("Planetka operators module is unavailable.")

    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != "CAMERA":
        raise RuntimeError("Active camera is missing.")
    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use animation tools.")

    anchor_frame_world = getattr(operators, "_anchor_frame_world", None)
    km_to_bu = getattr(operators, "_km_to_bu", None)
    anchor_distance_fn = getattr(operators, "_anchor_distance_from_altitude_and_tilt", None)
    look_rotation_quaternion = getattr(operators, "_look_rotation_quaternion", None)
    update_shot_anchor_object = getattr(operators, "_update_shot_anchor_object", None)
    ensure_close_clip_limits = getattr(operators, "_ensure_close_clip_limits", None)
    if not all((anchor_frame_world, km_to_bu, anchor_distance_fn, look_rotation_quaternion)):
        raise RuntimeError("Planetka navigation helpers are unavailable.")

    lon_deg = _normalize_longitude(float(shot.get("lon", 0.0)))
    lat_deg = _clamp_latitude(float(shot.get("lat", 0.0)))
    altitude_km = max(0.0, float(shot.get("alt_km", 0.0)))
    heading_deg = float(shot.get("heading_deg", 0.0))
    tilt_deg = float(shot.get("tilt_deg", 0.0))
    roll_deg = float(shot.get("roll_deg", 0.0))

    anchor_world, east_world, north_world, up_world, earth_radius_bu = anchor_frame_world(
        earth_obj, lon_deg, lat_deg
    )
    earth_center = earth_obj.matrix_world.translation.copy()
    try:
        if callable(update_shot_anchor_object):
            update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

    altitude_bu = km_to_bu(altitude_km, earth_radius_bu)
    heading_rad = math.radians(heading_deg)
    tilt_rad = math.radians(tilt_deg)
    roll_rad = math.radians(roll_deg)

    look_tangent = (north_world * math.cos(heading_rad)) + (east_world * math.sin(heading_rad))
    # Ensure the tangent axis is orthogonal to up to keep altitude stable under heading changes.
    try:
        look_tangent = look_tangent - (up_world * float(look_tangent.dot(up_world)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    if look_tangent.length_squared <= 1e-12:
        look_tangent = north_world.copy()
    look_tangent.normalize()
    position_tangent = -look_tangent

    offset_direction = (up_world * math.cos(tilt_rad)) + (position_tangent * math.sin(tilt_rad))
    if offset_direction.length_squared <= 1e-12:
        offset_direction = up_world.copy()
    offset_direction.normalize()

    anchor_distance = float(anchor_distance_fn(earth_radius_bu, altitude_bu, tilt_rad))
    camera_position = anchor_world + (offset_direction * anchor_distance)
    # Re-normalize to the intended altitude above the Earth center to avoid tiny numerical drift.
    desired_center_distance = float(earth_radius_bu) + float(altitude_bu)
    try:
        center_dir = camera_position - earth_center
        if center_dir.length_squared <= 1e-12:
            center_dir = up_world.copy()
        center_dir.normalize()
        camera_position = earth_center + (center_dir * desired_center_distance)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

    look_target = look_target_override.copy() if look_target_override is not None else anchor_world.copy()
    if (look_target - camera_position).length_squared <= 1e-12:
        look_target = camera_position - up_world

    up_hint = up_hint_override.copy() if up_hint_override is not None else look_tangent.copy()
    if up_hint.length_squared <= 1e-12:
        up_hint = up_world.copy()
    up_hint.normalize()

    _loc, _existing_rotation, camera_scale = camera.matrix_world.decompose()
    base_rotation, forward = look_rotation_quaternion(camera_position, look_target, up_hint)
    if abs(roll_rad) > 1e-9:
        final_rotation = Quaternion(forward, roll_rad) @ base_rotation
    else:
        final_rotation = base_rotation

    try:
        if callable(ensure_close_clip_limits):
            ensure_close_clip_limits(scene, min_clip=0.001)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

    return {
        "location": camera_position,
        "rotation": final_rotation,
        "scale": camera_scale,
        "anchor_world": anchor_world,
        "east_world": east_world,
        "north_world": north_world,
        "up_world": up_world,
        "earth_radius_bu": float(earth_radius_bu),
    }


def _set_camera_from_shot(
    scene,
    shot,
    frame,
    look_target_override=None,
    up_hint_override=None,
    rotation_compat_euler=None,
):
    camera = getattr(scene, "camera", None)
    if camera is None:
        raise RuntimeError("Active camera is missing.")
    pose = _compute_navigation_pose(
        scene,
        shot,
        look_target_override=look_target_override,
        up_hint_override=up_hint_override,
    )
    rotation_euler = _quaternion_to_camera_euler(camera, pose["rotation"], compat_euler=rotation_compat_euler)
    _write_camera_transform_keyframe(camera, int(frame), pose["location"], rotation_euler)
    pose["rotation_euler"] = rotation_euler.copy()
    return pose


def _set_camera_transform_keyframe(scene, frame, location, rotation_euler):
    camera = getattr(scene, "camera", None)
    if camera is None:
        raise RuntimeError("Active camera is missing.")
    _write_camera_transform_keyframe(camera, int(frame), location, rotation_euler)


def _ensure_camera_action(camera):
    if camera is None:
        raise RuntimeError("Active camera is missing.")
    try:
        animation_data = camera.animation_data_create()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError(f"Unable to create camera animation data: {exc}") from exc
    action = getattr(animation_data, "action", None)
    if action is None:
        action_name = f"{getattr(camera, 'name', 'Camera')}_Action"
        try:
            action = bpy.data.actions.new(name=action_name)
            animation_data.action = action
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(f"Unable to create camera action: {exc}") from exc
    return action


def _camera_fcurve_collection(camera):
    action = _ensure_camera_action(camera)
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        return fcurves

    animation_data = getattr(camera, "animation_data", None)
    slot = getattr(animation_data, "action_slot", None) if animation_data is not None else None
    if slot is None:
        slots = getattr(action, "slots", None)
        if slots is None:
            raise RuntimeError("Camera action has no slots collection.")
        slot_name = str(getattr(camera, "name", "Camera") or "Camera")
        try:
            slot = slots.new(camera.id_type, slot_name)
            animation_data.action_slot = slot
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(f"Unable to create/assign action slot: {exc}") from exc

    try:
        from bpy_extras import anim_utils as _anim_utils
        channelbag = _anim_utils.action_ensure_channelbag_for_slot(action, slot)
        channelbag_fcurves = getattr(channelbag, "fcurves", None)
        if channelbag_fcurves is None:
            raise RuntimeError("Action channelbag does not expose fcurves.")
        return channelbag_fcurves
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS as exc:
        raise RuntimeError(f"Unable to access action channelbag fcurves: {exc}") from exc


def _ensure_action_fcurve(fcurves, data_path, index):
    if fcurves is None:
        raise RuntimeError("Camera action has no writable fcurves collection.")
    try:
        fcurve = fcurves.find(data_path, index=index)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        fcurve = None
    if fcurve is None:
        last_exc = None
        for kwargs in (
            {"data_path": data_path, "index": index, "action_group": "Transform"},
            {"data_path": data_path, "index": index, "group_name": "Transform"},
            {"data_path": data_path, "index": index},
        ):
            try:
                fcurve = fcurves.new(**kwargs)
                break
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                last_exc = exc
                fcurve = None
        if fcurve is None:
            raise RuntimeError(
                f"Unable to create fcurve {data_path}[{index}]: {last_exc}"
            ) from last_exc
    return fcurve


def _insert_or_update_fcurve_key(fcurve, frame, value):
    target_frame = float(frame)
    target_value = float(value)
    points = getattr(fcurve, "keyframe_points", None)
    if points is None:
        raise RuntimeError("Fcurve has no keyframe points collection.")

    for keyframe in points:
        try:
            keyframe_frame = float(getattr(keyframe, "co", (0.0, 0.0))[0])
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if abs(keyframe_frame - target_frame) <= 1e-6:
            try:
                keyframe.co = (target_frame, target_value)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError) as exc:
                raise RuntimeError(f"Unable to update keyframe at frame {target_frame}: {exc}") from exc
            return

    try:
        points.insert(frame=target_frame, value=target_value, options={'FAST'})
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        points.insert(frame=target_frame, value=target_value)


def _rotation_order_for_camera(camera):
    raw_mode = str(getattr(camera, "rotation_mode", "") or "").upper()
    if raw_mode in {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}:
        return raw_mode
    return "XYZ"


def _quaternion_to_camera_euler(camera, rotation_quaternion, compat_euler=None):
    order = _rotation_order_for_camera(camera)
    compat = None
    if compat_euler is not None:
        try:
            compat = compat_euler.copy()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            compat = None
    if compat is None:
        try:
            compat = getattr(camera, "rotation_euler", None)
            compat = compat.copy() if compat is not None else None
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            compat = None
    try:
        if compat is not None:
            return rotation_quaternion.to_euler(order, compat)
        return rotation_quaternion.to_euler(order)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        return rotation_quaternion.to_euler("XYZ")


def _write_camera_transform_keyframe(camera, frame, location, rotation_euler):
    fcurves = _camera_fcurve_collection(camera)
    location_vec = Vector(location)
    rotation_vec = Vector(rotation_euler)

    for axis in range(3):
        fcurve = _ensure_action_fcurve(fcurves, "location", axis)
        _insert_or_update_fcurve_key(fcurve, frame, float(location_vec[axis]))
    for axis in range(3):
        fcurve = _ensure_action_fcurve(fcurves, "rotation_euler", axis)
        _insert_or_update_fcurve_key(fcurve, frame, float(rotation_vec[axis]))


def _set_camera_linear_interpolation_in_range(scene, frame_start, frame_end):
    camera = getattr(scene, "camera", None)
    anim = getattr(camera, "animation_data", None) if camera else None
    action = getattr(anim, "action", None) if anim else None
    if action is None:
        return
    start = int(frame_start)
    end = int(frame_end)
    lo = min(start, end) - 1e-6
    hi = max(start, end) + 1e-6
    for fcurve in _iter_action_fcurves(action):
        if str(getattr(fcurve, "data_path", "")) not in {"location", "rotation_euler"}:
            continue
        keyframe_points = getattr(fcurve, "keyframe_points", None)
        if not keyframe_points:
            continue
        for keyframe_point in keyframe_points:
            try:
                frame = float(getattr(keyframe_point, "co", (0.0, 0.0))[0])
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                continue
            if frame < lo or frame > hi:
                continue
            try:
                keyframe_point.interpolation = 'LINEAR'
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                continue


def _clear_camera_preview_keyframes(scene, frame_start, frame_end):
    camera = getattr(scene, "camera", None)
    anim = getattr(camera, "animation_data", None) if camera else None
    action = getattr(anim, "action", None) if anim else None
    if action is None:
        return
    start = int(frame_start)
    end = int(frame_end)
    lo = min(start, end) - 1e-6
    hi = max(start, end) + 1e-6
    for fcurve in _iter_action_fcurves(action):
        if str(getattr(fcurve, "data_path", "")) not in {"location", "rotation_euler"}:
            continue
        keyframe_points = getattr(fcurve, "keyframe_points", None)
        if not keyframe_points:
            continue
        for index in range(len(keyframe_points) - 1, -1, -1):
            try:
                keyframe = keyframe_points[index]
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError, IndexError):
                continue
            frame = float(getattr(keyframe, "co", (0.0, 0.0))[0])
            if frame < lo or frame > hi:
                continue
            try:
                keyframe_points.remove(keyframe)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError):
                continue


def _iter_action_fcurves(action):
    if action is None:
        return

    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        for fcurve in legacy_fcurves:
            yield fcurve
        return

    layers = getattr(action, "layers", None)
    slots = getattr(action, "slots", None)
    if not layers or not slots:
        return

    seen = set()
    for layer in layers:
        strips = getattr(layer, "strips", None)
        if not strips:
            continue
        for strip in strips:
            channelbag_fn = getattr(strip, "channelbag", None)
            if not callable(channelbag_fn):
                continue
            for slot in slots:
                try:
                    channelbag = channelbag_fn(slot)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    continue
                except (RuntimeError, TypeError, ValueError):
                    continue
                if channelbag is None:
                    continue
                for fcurve in getattr(channelbag, "fcurves", ()):
                    try:
                        token = int(fcurve.as_pointer())
                    except PLANETKA_RECOVERABLE_EXCEPTIONS:
                        token = id(fcurve)
                    except (RuntimeError, TypeError, ValueError):
                        token = id(fcurve)
                    if token in seen:
                        continue
                    seen.add(token)
                    yield fcurve


def _set_keyframe_motion_curve(keyframe_point, motion_curve):
    curve = str(motion_curve or "EASE_IN_OUT").upper()
    if curve == "LINEAR":
        keyframe_point.interpolation = 'LINEAR'
        return

    try:
        interpolation_items = {
            item.identifier
            for item in keyframe_point.bl_rna.properties["interpolation"].enum_items
        }
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        interpolation_items = {"BEZIER"}
    except (KeyError, RuntimeError, TypeError, ValueError, AttributeError):
        interpolation_items = {"BEZIER"}

    if "SINE" in interpolation_items:
        keyframe_point.interpolation = 'SINE'
    else:
        keyframe_point.interpolation = 'BEZIER'

    if not hasattr(keyframe_point, "easing"):
        return

    try:
        easing_items = {
            item.identifier
            for item in keyframe_point.bl_rna.properties["easing"].enum_items
        }
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        easing_items = {"AUTO"}
    except (KeyError, RuntimeError, TypeError, ValueError, AttributeError):
        easing_items = {"AUTO"}

    if curve in easing_items:
        keyframe_point.easing = curve
    elif "AUTO" in easing_items:
        keyframe_point.easing = 'AUTO'


def _normalize_cinematic_preset(value):
    token = str(value or "NONE").strip().upper()
    if token in {"PUSH_IN", "PULL_BACK"}:
        return "ZOOM"
    if token in {"ARC_LEFT", "ARC_RIGHT"}:
        return "ARC"
    if token == "FLYBY":
        return "NONE"
    if token in {"NONE", "ORBIT", "ARC", "ZOOM", "A_TO_B", "WAYPOINTS"}:
        return token
    return "NONE"


def _active_timeline_frame_range(scene):
    if scene is None:
        return 1, 250
    try:
        use_preview = bool(getattr(scene, "use_preview_range", False))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        use_preview = False
    if use_preview:
        try:
            start = int(getattr(scene, "frame_preview_start", getattr(scene, "frame_start", 1)))
            end = int(getattr(scene, "frame_preview_end", getattr(scene, "frame_end", 250)))
            return start, end
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass
    try:
        start = int(getattr(scene, "frame_start", 1))
        end = int(getattr(scene, "frame_end", 250))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        start, end = 1, 250
    return start, end


def _apply_camera_motion_curve(scene, motion_curve):
    camera = getattr(scene, "camera", None)
    anim = getattr(camera, "animation_data", None) if camera else None
    action = getattr(anim, "action", None) if anim else None
    if action is None:
        return

    for fcurve in _iter_action_fcurves(action):
        if str(getattr(fcurve, "data_path", "")) not in {"location", "rotation_euler"}:
            continue
        keyframes = getattr(fcurve, "keyframe_points", None)
        if not keyframes:
            continue
        for keyframe_point in keyframes:
            try:
                _set_keyframe_motion_curve(keyframe_point, motion_curve)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError, AttributeError):
                continue


def _current_camera_base_shot(scene, props):
    default_shot = {
        "lon": _normalize_longitude(float(getattr(props, "nav_longitude_deg", 0.0))),
        "lat": _clamp_latitude(float(getattr(props, "nav_latitude_deg", 0.0))),
        "alt_km": max(0.0, float(getattr(props, "nav_altitude_km", 400.0))),
        "heading_deg": float(getattr(props, "nav_azimuth_deg", 0.0)),
        "tilt_deg": float(getattr(props, "nav_tilt_deg", 25.0)),
        "roll_deg": float(getattr(props, "nav_roll_deg", 0.0)),
    }

    operators = _get_operators_module()
    if operators is None:
        return default_shot
    nav_from_camera = getattr(operators, "_compute_scene_camera_navigation_values", None)
    derive_from_camera = getattr(operators, "_derive_navigation_shot_from_camera", None)
    if not callable(nav_from_camera) or not callable(derive_from_camera):
        return default_shot

    try:
        nav_values = nav_from_camera(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return default_shot
    except (RuntimeError, TypeError, ValueError):
        return default_shot
    if not nav_values or len(nav_values) < 2:
        return default_shot

    lat_deg = _clamp_latitude(float(nav_values[0]))
    lon_deg = _normalize_longitude(float(nav_values[1]))
    try:
        derived = derive_from_camera(scene, lon_deg, lat_deg) or {}
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        derived = {}
    except (RuntimeError, TypeError, ValueError):
        derived = {}

    default_shot.update(
        {
            "lon": lon_deg,
            "lat": lat_deg,
            "alt_km": max(0.0, float(derived.get("altitude_km", default_shot["alt_km"]))),
            "heading_deg": float(derived.get("azimuth_deg", default_shot["heading_deg"])),
            "tilt_deg": float(derived.get("tilt_deg", default_shot["tilt_deg"])),
            "roll_deg": float(derived.get("roll_deg", default_shot["roll_deg"])),
        }
    )
    return default_shot


def _navigation_base_shot_from_props(props, fallback=None):
    base = dict(fallback) if isinstance(fallback, dict) else {}
    base_lon = _normalize_longitude(float(base.get("lon", 0.0)))
    base_lat = _clamp_latitude(float(base.get("lat", 0.0)))
    base_alt = max(0.0, float(base.get("alt_km", 400.0)))
    base_heading = float(base.get("heading_deg", 0.0))
    base_tilt = float(base.get("tilt_deg", 25.0))
    base_roll = float(base.get("roll_deg", 0.0))
    return {
        "lon": _normalize_longitude(float(getattr(props, "nav_longitude_deg", base_lon))),
        "lat": _clamp_latitude(float(getattr(props, "nav_latitude_deg", base_lat))),
        "alt_km": max(0.0, float(getattr(props, "nav_altitude_km", base_alt))),
        "heading_deg": float(getattr(props, "nav_azimuth_deg", base_heading)),
        "tilt_deg": float(getattr(props, "nav_tilt_deg", base_tilt)),
        "roll_deg": float(getattr(props, "nav_roll_deg", base_roll)),
    }


def _camera_base_shot_from_transform(scene, props, location, rotation_euler):
    camera = getattr(scene, "camera", None) if scene is not None else None
    if camera is None:
        raise RuntimeError("Active camera is missing.")
    try:
        camera_matrix_before = camera.matrix_world.copy()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        camera_matrix_before = None
    try:
        _loc, _rot, camera_scale = camera.matrix_world.decompose()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        camera_scale = Vector((1.0, 1.0, 1.0))
    try:
        target_location = Vector(tuple(float(v) for v in tuple(location)))
        target_rotation = Euler(tuple(float(v) for v in tuple(rotation_euler)), _rotation_order_for_camera(camera))
        camera.matrix_world = Matrix.LocRotScale(target_location, target_rotation, camera_scale)
        try:
            bpy.context.view_layer.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed updating view layer while deriving saved camera shot", exc_info=True)
        return _current_camera_base_shot(scene, props)
    finally:
        if camera_matrix_before is not None:
            try:
                camera.matrix_world = camera_matrix_before
                bpy.context.view_layer.update()
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: failed restoring camera after deriving saved shot", exc_info=True)


def _frame_one_navigation_base_shot(scene, props):
    fallback = _navigation_base_shot_from_props(props, fallback=_current_camera_base_shot(scene, props))
    if scene is None:
        return fallback
    frame_before = int(getattr(scene, "frame_current", 1))
    sampled = dict(fallback)
    try:
        scene.frame_set(1)
        try:
            bpy.context.view_layer.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed updating view layer during frame-1 base-shot sampling", exc_info=True)
        sampled = _navigation_base_shot_from_props(props, fallback=fallback)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka animation: failed sampling frame-1 navigation base shot", exc_info=True)
    finally:
        try:
            scene.frame_set(int(frame_before))
            bpy.context.view_layer.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed restoring frame after frame-1 base-shot sampling", exc_info=True)
    return sampled


def _waypoint_index_label(index):
    idx = int(max(0, int(index)))
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    base = len(alphabet)
    label = ""
    while True:
        label = alphabet[idx % base] + label
        idx = (idx // base) - 1
        if idx < 0:
            break
    return label


def _waypoint_shot_from_item(item):
    return {
        "lon": _normalize_longitude(float(getattr(item, "longitude_deg", 0.0))),
        "lat": _clamp_latitude(float(getattr(item, "latitude_deg", 0.0))),
        "alt_km": max(0.0, float(getattr(item, "altitude_km", 0.0))),
        "heading_deg": float(getattr(item, "heading_deg", 0.0)),
        "tilt_deg": float(getattr(item, "tilt_deg", 0.0)),
        "roll_deg": float(getattr(item, "roll_deg", 0.0)),
    }


def _build_waypoint_shots(props):
    waypoints = getattr(props, "anim_waypoints", None)
    if waypoints is None:
        return []
    shots = []
    for waypoint in waypoints:
        try:
            shots.append(_waypoint_shot_from_item(waypoint))
        except (TypeError, ValueError, AttributeError):
            continue
    return shots


def _apply_waypoints_preview(scene, waypoint_shots, start_frame, end_frame, motion_curve):
    shots = list(waypoint_shots or ())
    if not shots:
        raise RuntimeError("Add at least one waypoint first.")
    compat_euler = None
    if len(shots) == 1:
        start_pose = _set_camera_from_shot(
            scene, shots[0], int(start_frame), rotation_compat_euler=compat_euler
        )
        compat_euler = start_pose.get("rotation_euler")
        _set_camera_from_shot(
            scene, shots[0], int(end_frame), rotation_compat_euler=compat_euler
        )
        return

    total = max(1, int(end_frame) - int(start_frame))
    segment_count = max(1, len(shots) - 1)
    for frame in range(int(start_frame), int(end_frame) + 1):
        global_t = 0.0 if total <= 0 else float(frame - int(start_frame)) / float(total)
        segment_f = min(float(segment_count), max(0.0, global_t * float(segment_count)))
        segment_idx = min(segment_count - 1, int(math.floor(segment_f)))
        local_raw_t = min(1.0, max(0.0, segment_f - float(segment_idx)))
        local_t = _eased_progress(local_raw_t, motion_curve)
        shot = _interpolate_shot(shots[segment_idx], shots[segment_idx + 1], local_t)
        pose = _set_camera_from_shot(scene, shot, frame, rotation_compat_euler=compat_euler)
        compat_euler = pose.get("rotation_euler")


def _apply_waypoints_keyframes(scene, waypoint_shots, start_frame, end_frame):
    shots = list(waypoint_shots or ())
    if not shots:
        raise RuntimeError("Add at least one waypoint first.")
    compat_euler = None
    if len(shots) == 1:
        start_pose = _set_camera_from_shot(
            scene, shots[0], int(start_frame), rotation_compat_euler=compat_euler
        )
        compat_euler = start_pose.get("rotation_euler")
        _set_camera_from_shot(
            scene, shots[0], int(end_frame), rotation_compat_euler=compat_euler
        )
        return

    span = max(1, int(end_frame) - int(start_frame))
    count = max(2, len(shots))
    for index, shot in enumerate(shots):
        t = float(index) / float(count - 1)
        frame = int(round(int(start_frame) + (span * t)))
        pose = _set_camera_from_shot(scene, shot, frame, rotation_compat_euler=compat_euler)
        compat_euler = pose.get("rotation_euler")


def _clamp_waypoint_active_index(props):
    waypoints = getattr(props, "anim_waypoints", None)
    count = len(waypoints) if waypoints is not None else 0
    if count <= 0:
        props.anim_waypoint_active_index = 0
        return 0
    active = int(getattr(props, "anim_waypoint_active_index", 0))
    active = max(0, min(count - 1, active))
    props.anim_waypoint_active_index = active
    return active


def _apply_keyed_runtime_scene_state(scene, props):
    if scene is None:
        return
    _apply_sunlight_from_props(scene)
    _apply_sunlight_strength_from_props(scene)
    camera = getattr(scene, "camera", None)
    camera_data = getattr(camera, "data", None) if camera is not None else None
    if camera is not None and getattr(camera, "type", None) == 'CAMERA' and camera_data is not None:
        try:
            lens_mm = max(1.0, float(getattr(props, "nav_focal_length_mm", 50.0)))
            camera_data.lens = lens_mm
        except (TypeError, ValueError, AttributeError):
            pass


def _build_shot_pair(scene, props, base_shot=None):
    preset_raw = str(getattr(props, "anim_camera_preset", "NONE")).upper()
    preset = _normalize_cinematic_preset(preset_raw)
    strength = 1.0
    base = dict(base_shot) if isinstance(base_shot, dict) else _current_camera_base_shot(scene, props)
    base_lon = float(base.get("lon", 0.0))
    base_lat = float(base.get("lat", 0.0))
    base_alt = max(0.0, float(base.get("alt_km", 400.0)))
    base_heading = float(base.get("heading_deg", 0.0))
    base_tilt = float(base.get("tilt_deg", 25.0))
    base_roll = float(base.get("roll_deg", 0.0))

    end_alt = max(0.0, float(getattr(props, "anim_end_altitude_km", base_alt)))
    orbit_degrees = float(getattr(props, "anim_orbit_degrees", 120.0)) * strength
    zoom_rotate_degrees = float(getattr(props, "anim_zoom_rotate_degrees", 20.0)) * strength

    start = {
        "lon": base_lon,
        "lat": base_lat,
        "alt_km": base_alt,
        "heading_deg": base_heading,
        "tilt_deg": base_tilt,
        "roll_deg": base_roll,
    }
    end = dict(start)

    if preset == "ORBIT":
        # Circle is always built from the current Navigation-panel base shot.
        direction = str(getattr(props, "anim_circle_direction", "CLOCKWISE")).upper()
        orbit_sign = 1.0 if direction != "COUNTERCLOCKWISE" else -1.0
        end["heading_deg"] = float(start["heading_deg"] + (orbit_degrees * orbit_sign))
    elif preset == "ARC":
        direction = str(getattr(props, "anim_circle_direction", "CLOCKWISE")).upper()
        if preset_raw == "ARC_LEFT":
            direction = "COUNTERCLOCKWISE"
        elif preset_raw == "ARC_RIGHT":
            direction = "CLOCKWISE"
        arc_sign = 1.0 if direction != "COUNTERCLOCKWISE" else -1.0
        end["heading_deg"] = float(base_heading + (orbit_degrees * 0.6 * arc_sign))
        end["tilt_deg"] = float(max(-90.0, min(90.0, base_tilt + (10.0 * strength))))
        end["alt_km"] = max(0.0, base_alt * (1.2 + (0.2 * strength)))
    elif preset == "ZOOM":
        # Keep frame 1 fixed to the current Navigation pose. Zoom is driven by
        # End Altitude (+ optional Rotate), independent from timeline scrubbing.
        zoom_end_alt = end_alt
        if preset_raw == "PUSH_IN":
            zoom_end_alt = min(base_alt, end_alt)
        elif preset_raw == "PULL_BACK":
            zoom_end_alt = max(base_alt, end_alt)
        end["alt_km"] = max(0.0, float(zoom_end_alt))
        # Zoom rotate is applied as camera roll (twist), not heading/orbit.
        # This keeps POI centered with start/end-only keyframes.
        end["roll_deg"] = float(base_roll + zoom_rotate_degrees)

    return start, end


def _build_simple_flyby(scene, props, base_shot=None):
    strength = 1.0
    base = dict(base_shot) if isinstance(base_shot, dict) else _current_camera_base_shot(scene, props)
    return {
        "lon": _normalize_longitude(float(base.get("lon", 0.0))),
        "lat": _clamp_latitude(float(base.get("lat", 0.0))),
        "alt_km": max(0.0, float(base.get("alt_km", 400.0))),
        "heading_deg": float(base.get("heading_deg", 0.0)),
        "tilt_deg": float(base.get("tilt_deg", 25.0)),
        "roll_deg": float(base.get("roll_deg", 0.0)),
        "flyby_degrees": max(0.1, abs(float(getattr(props, "anim_flyby_degrees", 12.0)) * strength)),
        "camera_heading_deg": float(getattr(props, "anim_flyby_camera_heading_deg", 0.0)),
    }


def _apply_sampled_navigation_preview(scene, start_shot, end_shot, start_frame, end_frame, motion_curve):
    total = max(1, int(end_frame) - int(start_frame))
    compat_euler = None
    for frame in range(int(start_frame), int(end_frame) + 1):
        raw_t = 0.0 if total <= 0 else float(frame - int(start_frame)) / float(total)
        t = _eased_progress(raw_t, motion_curve)
        shot = _interpolate_shot(start_shot, end_shot, t)
        pose = _set_camera_from_shot(scene, shot, frame, rotation_compat_euler=compat_euler)
        compat_euler = pose.get("rotation_euler")


def _apply_simple_flyby_preview(scene, flyby, start_frame, end_frame, motion_curve):
    base_shot = {
        "lon": float(flyby.get("lon", 0.0)),
        "lat": float(flyby.get("lat", 0.0)),
        "alt_km": float(flyby.get("alt_km", 0.0)),
        "heading_deg": float(flyby.get("heading_deg", 0.0)),
        "tilt_deg": float(flyby.get("tilt_deg", 0.0)),
        "roll_deg": float(flyby.get("roll_deg", 0.0)),
    }
    base_pose = _compute_navigation_pose(scene, base_shot)
    base_position = base_pose["location"].copy()
    base_rotation = base_pose["rotation"].copy()
    camera_heading_deg = float(flyby.get("camera_heading_deg", 0.0))
    if abs(camera_heading_deg) > 1e-9:
        try:
            up_axis = base_pose["up_world"].copy()
            if up_axis.length_squared <= 1e-12:
                up_axis = Vector((0.0, 0.0, 1.0))
            up_axis.normalize()
            base_rotation = Quaternion(up_axis, math.radians(camera_heading_deg)) @ base_rotation
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, KeyError, AttributeError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    north = base_pose["north_world"].copy()
    east = base_pose["east_world"].copy()
    heading_rad = math.radians(float(flyby.get("heading_deg", 0.0)))
    travel_direction = (north * math.cos(heading_rad)) + (east * math.sin(heading_rad))
    if travel_direction.length_squared <= 1e-12:
        travel_direction = north
    travel_direction.normalize()

    travel_distance = float(base_pose["earth_radius_bu"]) * math.radians(float(flyby.get("flyby_degrees", 12.0)))
    half_distance = max(1e-6, travel_distance * 0.5)
    start_position = base_position.copy()
    end_position = base_position + (travel_direction * (half_distance * 2.0))

    camera = getattr(scene, "camera", None)
    if camera is None:
        raise RuntimeError("Active camera is missing.")

    total = max(1, int(end_frame) - int(start_frame))
    compat_euler = None
    for frame in range(int(start_frame), int(end_frame) + 1):
        raw_t = 0.0 if total <= 0 else float(frame - int(start_frame)) / float(total)
        t = _eased_progress(raw_t, motion_curve)
        position = start_position.lerp(end_position, t)
        rotation_euler = _quaternion_to_camera_euler(camera, base_rotation, compat_euler=compat_euler)
        compat_euler = rotation_euler.copy()
        _write_camera_transform_keyframe(camera, int(frame), position, rotation_euler)


def _compute_simple_flyby_endpoints(scene, flyby):
    base_shot = {
        "lon": float(flyby.get("lon", 0.0)),
        "lat": float(flyby.get("lat", 0.0)),
        "alt_km": float(flyby.get("alt_km", 0.0)),
        "heading_deg": float(flyby.get("heading_deg", 0.0)),
        "tilt_deg": float(flyby.get("tilt_deg", 0.0)),
        "roll_deg": float(flyby.get("roll_deg", 0.0)),
    }
    base_pose = _compute_navigation_pose(scene, base_shot)
    base_position = base_pose["location"].copy()
    base_rotation = base_pose["rotation"].copy()
    camera_heading_deg = float(flyby.get("camera_heading_deg", 0.0))
    if abs(camera_heading_deg) > 1e-9:
        try:
            up_axis = base_pose["up_world"].copy()
            if up_axis.length_squared <= 1e-12:
                up_axis = Vector((0.0, 0.0, 1.0))
            up_axis.normalize()
            base_rotation = Quaternion(up_axis, math.radians(camera_heading_deg)) @ base_rotation
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, KeyError, AttributeError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    camera_scale = base_pose["scale"]
    north = base_pose["north_world"].copy()
    east = base_pose["east_world"].copy()
    heading_rad = math.radians(float(flyby.get("heading_deg", 0.0)))
    travel_direction = (north * math.cos(heading_rad)) + (east * math.sin(heading_rad))
    if travel_direction.length_squared <= 1e-12:
        travel_direction = north
    travel_direction.normalize()

    travel_distance = float(base_pose["earth_radius_bu"]) * math.radians(float(flyby.get("flyby_degrees", 12.0)))
    half_distance = max(1e-6, travel_distance * 0.5)
    start_position = base_position.copy()
    end_position = base_position + (travel_direction * (half_distance * 2.0))
    return {
        "start_position": start_position,
        "end_position": end_position,
        "rotation": base_rotation,
        "scale": camera_scale,
    }


def _apply_simple_flyby_keyframes(scene, flyby, start_frame, end_frame):
    camera = getattr(scene, "camera", None)
    if camera is None:
        raise RuntimeError("Active camera is missing.")
    endpoints = _compute_simple_flyby_endpoints(scene, flyby)
    start_position = endpoints.get("start_position")
    end_position = endpoints.get("end_position")
    base_rotation = endpoints.get("rotation")
    if start_position is None or end_position is None or base_rotation is None:
        raise RuntimeError("Failed to compute flyby camera path.")
    start_euler = _quaternion_to_camera_euler(camera, base_rotation)
    end_euler = _quaternion_to_camera_euler(camera, base_rotation, compat_euler=start_euler)
    _write_camera_transform_keyframe(camera, int(start_frame), start_position, start_euler)
    _write_camera_transform_keyframe(camera, int(end_frame), end_position, end_euler)


def _ensure_camera_and_earth(scene):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Set an active camera and retry.")
    earth = get_earth_object()
    if earth is None:
        raise RuntimeError("Create Earth first, then use animation tools.")
    return camera, earth


def apply_cinematic_preview(scene, props):
    camera, _earth = _ensure_camera_and_earth(scene)
    frame_before = int(getattr(scene, "frame_current", 1))
    camera_matrix_before = None
    camera_lens_before = None
    try:
        camera_matrix_before = camera.matrix_world.copy()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        camera_matrix_before = None
    camera_data_before = getattr(camera, "data", None) if camera is not None else None
    if camera_data_before is not None:
        try:
            camera_lens_before = float(getattr(camera_data_before, "lens", 50.0))
        except (TypeError, ValueError, AttributeError):
            camera_lens_before = None

    suspend_navigation_camera_control_sync()
    try:
        start_frame, end_frame = _active_timeline_frame_range(scene)
        if end_frame <= start_frame:
            raise RuntimeError("End frame must be greater than start frame.")
        motion_curve = str(getattr(props, "anim_motion_curve", "EASE_IN_OUT")).upper()
        preset = _normalize_cinematic_preset(getattr(props, "anim_camera_preset", "NONE"))
        if preset in {"", "NONE"}:
            # Support custom user camera rigs/animation with no Planetka preset selected.
            # In this mode, keep user keyframes untouched and use timeline range as-is.
            return start_frame, end_frame

        # Always use current Navigation controls as the preset reference.
        # Timeline scrubbing must never redefine the animation anchor.
        reference_shot = None
        if preset in {"ORBIT", "ARC", "ZOOM"}:
            reference_shot = _navigation_base_shot_from_props(
                props,
                fallback=_current_camera_base_shot(scene, props),
            )

        _clear_camera_preview_keyframes(scene, start_frame, end_frame)

        if preset == "A_TO_B":
            if not bool(getattr(props, "anim_ab_a_valid", False)) or not bool(getattr(props, "anim_ab_b_valid", False)):
                raise RuntimeError("Save both View A and View B first.")
            start_shot = _camera_base_shot_from_transform(
                scene,
                props,
                tuple(getattr(props, "anim_ab_a_location", (0.0, 0.0, 0.0))),
                tuple(getattr(props, "anim_ab_a_rotation", (0.0, 0.0, 0.0))),
            )
            end_shot = _camera_base_shot_from_transform(
                scene,
                props,
                tuple(getattr(props, "anim_ab_b_location", (0.0, 0.0, 0.0))),
                tuple(getattr(props, "anim_ab_b_rotation", (0.0, 0.0, 0.0))),
            )
            _apply_sampled_navigation_preview(
                scene,
                start_shot,
                end_shot,
                int(start_frame),
                int(end_frame),
                motion_curve,
            )
        elif preset == "WAYPOINTS":
            waypoint_shots = _build_waypoint_shots(props)
            if len(waypoint_shots) < 2:
                raise RuntimeError("Add at least two waypoints first.")
            _apply_waypoints_keyframes(scene, waypoint_shots, start_frame, end_frame)
            _apply_camera_motion_curve(scene, motion_curve)
        else:
            start_shot, end_shot = _build_shot_pair(scene, props, base_shot=reference_shot)
            if preset == "ORBIT":
                # Keep constant POI distance by sampling the navigation path every frame.
                # Start/end-only keyframes would interpolate along a straight chord.
                _apply_sampled_navigation_preview(
                    scene,
                    start_shot,
                    end_shot,
                    int(start_frame),
                    int(end_frame),
                    motion_curve,
                )
            else:
                start_pose = _set_camera_from_shot(scene, start_shot, int(start_frame))
                _set_camera_from_shot(
                    scene,
                    end_shot,
                    int(end_frame),
                    rotation_compat_euler=start_pose.get("rotation_euler"),
                )
                _apply_camera_motion_curve(scene, motion_curve)
        return start_frame, end_frame
    finally:
        # Animation preset edits must never rewrite live camera controls/location.
        if camera is not None:
            try:
                if camera_matrix_before is not None:
                    camera.matrix_world = camera_matrix_before
                camera_data = getattr(camera, "data", None)
                if camera_data is not None and camera_lens_before is not None:
                    camera_data.lens = float(camera_lens_before)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: failed restoring live camera pose after preview keyframe update", exc_info=True)
        try:
            scene.frame_set(int(frame_before))
            bpy.context.view_layer.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed restoring frame after preview keyframe update", exc_info=True)
        try:
            mark_navigation_camera_control_signature(scene)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed marking camera-control sync signature", exc_info=True)
        resume_navigation_camera_control_sync()


def _is_animation_playing():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return False
    for window in getattr(wm, "windows", ()):
        screen = getattr(window, "screen", None)
        if screen and bool(getattr(screen, "is_animation_playing", False)):
            return True
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


def _image_has_blender_pink(path, min_pixels=32, sample_limit=400000):
    image_path = str(path or "").strip()
    if not image_path or not os.path.isfile(image_path):
        return False

    image = None
    try:
        image = bpy.data.images.load(image_path, check_existing=False)
        size = getattr(image, "size", None)
        width = int(size[0]) if size and len(size) >= 2 else 0
        height = int(size[1]) if size and len(size) >= 2 else 0
        total_pixels = max(0, width * height)
        if total_pixels <= 0:
            return False
        pixels = image.pixels[:]
        if not pixels:
            return False
        step = max(1, int(total_pixels / max(1, int(sample_limit))))
        pink_hits = 0
        for pixel_index in range(0, total_pixels, step):
            base = int(pixel_index) * 4
            if base + 2 >= len(pixels):
                break
            r = float(pixels[base + 0])
            g = float(pixels[base + 1])
            b = float(pixels[base + 2])
            if r >= 0.95 and b >= 0.95 and g <= 0.20:
                pink_hits += 1
                if pink_hits >= int(max(1, min_pixels)):
                    return True
        return False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("[PKA-ANIM-001] Planetka animation: failed pink-frame probe", exc_info=True)
        return False
    finally:
        if image is not None:
            try:
                bpy.data.images.remove(image)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("[PKA-ANIM-002] Planetka animation: failed removing probe image", exc_info=True)


def _collect_pink_frames(scene, frame_start, frame_end):
    if scene is None or _is_movie_output(scene):
        return []
    pink_frames = []
    for frame in range(int(frame_start), int(frame_end) + 1):
        try:
            frame_path = bpy.path.abspath(scene.render.frame_path(frame=int(frame)))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("[PKA-ANIM-003] Planetka animation: failed resolving frame path", exc_info=True)
            continue
        if _image_has_blender_pink(frame_path):
            pink_frames.append(int(frame))
    return pink_frames


def _render_output_display(scene):
    render = getattr(scene, "render", None) if scene else None
    if render is None:
        return "—"
    raw = str(getattr(render, "filepath", "") or "")
    try:
        abs_path = bpy.path.abspath(raw) if raw else ""
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        abs_path = raw
    return abs_path or raw or "—"


def _render_engine_display(scene):
    render = getattr(scene, "render", None) if scene else None
    engine = str(getattr(render, "engine", "") or "") if render else ""
    if engine == "BLENDER_EEVEE_NEXT" or engine == "BLENDER_EEVEE":
        return "Eevee"
    if engine == "CYCLES":
        cycles = getattr(scene, "cycles", None)
        device = str(getattr(cycles, "device", "") or "") if cycles else ""
        if device == "GPU":
            return "Cycles (GPU)"
        return "Cycles (CPU)"
    return engine or "—"


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
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        available = set()
    for identifier in candidates:
        if available and identifier not in available:
            continue
        try:
            setattr(target, prop_name, identifier)
            return True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            continue
    return False


def _capture_earth_material_displacement_mode_state(material):
    state = {}
    if material is None:
        return state
    try:
        if hasattr(material, "displacement_method"):
            state["material"] = str(getattr(material, "displacement_method", "") or "")
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    cycles_settings = getattr(material, "cycles", None)
    try:
        if cycles_settings is not None and hasattr(cycles_settings, "displacement_method"):
            state["cycles"] = str(getattr(cycles_settings, "displacement_method", "") or "")
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
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
    # Legacy cycles-level property (kept for compatibility).
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
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            key = id(material)
        if key in seen:
            return
        seen.add(key)
        materials.append(material)

    earth_obj = get_earth_object()
    if earth_obj is not None:
        try:
            _add_material(getattr(earth_obj, "active_material", None))
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass
        try:
            mesh_data = getattr(earth_obj, "data", None)
            slots = getattr(mesh_data, "materials", None) if mesh_data is not None else None
            if slots is not None:
                for slot_material in slots:
                    _add_material(slot_material)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass

    # Keep explicit-name fallback for old scenes where Earth object lookup can fail.
    try:
        _add_material(bpy.data.materials.get("Planetka Earth Material"))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    # Include material variants that can appear during resolve swaps.
    try:
        for material in tuple(getattr(bpy.data, "materials", ()) or ()):
            mat_name = str(getattr(material, "name", "") or "")
            if mat_name == "Planetka Earth Material" or mat_name.startswith("Planetka Earth Material."):
                _add_material(material)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    return materials


def _capture_material_displacement_mode_states(materials):
    states = []
    for material in (materials or ()):
        try:
            state = _capture_earth_material_displacement_mode_state(material)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
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
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
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


def _ensure_saved_blend_before_animation_render(operator, prompt_if_unsaved=False):
    save_required_message = "Save the .blend file first, then run Animation Render again."
    blend_path = str(getattr(bpy.data, "filepath", "") or "").strip()
    if not blend_path:
        if bool(prompt_if_unsaved):
            try:
                bpy.ops.wm.save_mainfile('INVOKE_DEFAULT')
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
            except (RuntimeError, TypeError, ValueError):
                pass
            operator.report({'INFO'}, save_required_message)
            return False
        operator.report({'INFO'}, save_required_message)
        return False

    try:
        save_result = bpy.ops.wm.save_mainfile()
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        fail(
            operator,
            f"Failed saving .blend before render: {exc}",
            code=ErrorCode.RENDER_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka animation save-before-render failed",
        )
        return False
    except (RuntimeError, TypeError, ValueError) as exc:
        fail(
            operator,
            f"Failed saving .blend before render: {exc}",
            code=ErrorCode.RENDER_FAILED,
            logger=logger,
        )
        return False
    if "FINISHED" not in save_result:
        fail(
            operator,
            "Saving .blend was cancelled. Animation render did not start.",
            code=ErrorCode.RENDER_FAILED,
            logger=logger,
        )
        return False
    return True


class PLANETKA_OT_AnimationSaveView(bpy.types.Operator):
    bl_idname = "planetka.animation_save_view"
    bl_label = "Save Animation View"
    bl_description = "Store the current camera transform as View A or View B for A-to-B cinematic shots"

    slot: EnumProperty(
        name="Slot",
        items=(
            ("A", "A", ""),
            ("B", "B", ""),
        ),
        default="A",
    )

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        camera = getattr(scene, "camera", None)
        if camera is None or getattr(camera, "type", None) != 'CAMERA':
            return fail(
                self,
                "Set an active camera and retry.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        slot = str(getattr(self, "slot", "A")).upper()
        location = tuple(float(v) for v in camera.location)
        rotation = tuple(float(v) for v in camera.rotation_euler)
        current_frame = int(getattr(scene, "frame_current", 0))
        current_timecode = _format_frame_timecode(scene, current_frame)
        if slot == "A":
            props.anim_ab_a_location = location
            props.anim_ab_a_rotation = rotation
            props.anim_ab_a_valid = True
            props.anim_ab_a_capture_frame = current_frame
            props.anim_ab_a_capture_timecode = current_timecode
        else:
            props.anim_ab_b_location = location
            props.anim_ab_b_rotation = rotation
            props.anim_ab_b_valid = True
            props.anim_ab_b_capture_frame = current_frame
            props.anim_ab_b_capture_timecode = current_timecode

        preset = str(getattr(props, "anim_camera_preset", "NONE") or "NONE").strip().upper()
        if preset == "A_TO_B":
            has_a = bool(getattr(props, "anim_ab_a_valid", False))
            has_b = bool(getattr(props, "anim_ab_b_valid", False))
            if has_a and has_b:
                try:
                    apply_cinematic_preview(scene, props)
                    self.report({'INFO'}, f"Saved camera view {slot}. A-to-B keyframes rebuilt.")
                except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                    self.report({'WARNING'}, f"Saved camera view {slot}. A-to-B rebuild failed: {exc}")
                except (RuntimeError, TypeError, ValueError) as exc:
                    self.report({'WARNING'}, f"Saved camera view {slot}. A-to-B rebuild failed: {exc}")
            else:
                self.report({'INFO'}, f"Saved camera view {slot}. Set the other view to build A-to-B keyframes.")
        else:
            self.report({'INFO'}, f"Saved camera view {slot}.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationWaypointAdd(bpy.types.Operator):
    bl_idname = "planetka.animation_waypoint_add"
    bl_label = "Add Waypoint"
    bl_description = "Add a new waypoint based on current Navigation/camera state"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        shot = _current_camera_base_shot(scene, props)
        waypoint = props.anim_waypoints.add()
        waypoint.latitude_deg = float(shot.get("lat", 0.0))
        waypoint.longitude_deg = float(shot.get("lon", 0.0))
        waypoint.altitude_km = float(shot.get("alt_km", 400.0))
        waypoint.heading_deg = float(shot.get("heading_deg", 0.0))
        waypoint.tilt_deg = float(shot.get("tilt_deg", 25.0))
        waypoint.roll_deg = float(shot.get("roll_deg", 0.0))
        waypoint.expanded = True
        props.anim_waypoint_active_index = max(0, len(props.anim_waypoints) - 1)
        label = _waypoint_index_label(props.anim_waypoint_active_index)
        self.report({'INFO'}, f"Waypoint {label} added.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationWaypointRemove(bpy.types.Operator):
    bl_idname = "planetka.animation_waypoint_remove"
    bl_label = "Remove Waypoint"
    bl_description = "Remove a waypoint from the cinematic path"

    index: IntProperty(default=-1, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        waypoints = getattr(props, "anim_waypoints", None)
        if waypoints is None or len(waypoints) == 0:
            return {'CANCELLED'}
        index = int(getattr(self, "index", -1))
        if index < 0 or index >= len(waypoints):
            index = int(getattr(props, "anim_waypoint_active_index", 0))
        if index < 0 or index >= len(waypoints):
            return {'CANCELLED'}
        label = _waypoint_index_label(index)
        waypoints.remove(index)
        _clamp_waypoint_active_index(props)
        self.report({'INFO'}, f"Waypoint {label} removed.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationWaypointCaptureCurrent(bpy.types.Operator):
    bl_idname = "planetka.animation_waypoint_capture_current"
    bl_label = "Capture Current View"
    bl_description = "Overwrite a waypoint with the current camera/navigation state"

    index: IntProperty(default=-1, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        waypoints = getattr(props, "anim_waypoints", None)
        if waypoints is None or len(waypoints) == 0:
            return fail(
                self,
                "Add at least one waypoint first.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
        index = int(getattr(self, "index", -1))
        if index < 0 or index >= len(waypoints):
            index = _clamp_waypoint_active_index(props)
        waypoint = waypoints[index]
        shot = _current_camera_base_shot(scene, props)
        waypoint.latitude_deg = float(shot.get("lat", 0.0))
        waypoint.longitude_deg = float(shot.get("lon", 0.0))
        waypoint.altitude_km = float(shot.get("alt_km", 400.0))
        waypoint.heading_deg = float(shot.get("heading_deg", 0.0))
        waypoint.tilt_deg = float(shot.get("tilt_deg", 25.0))
        waypoint.roll_deg = float(shot.get("roll_deg", 0.0))
        props.anim_waypoint_active_index = int(index)
        self.report({'INFO'}, f"Waypoint {_waypoint_index_label(index)} updated from current view.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationWaypointApply(bpy.types.Operator):
    bl_idname = "planetka.animation_waypoint_apply"
    bl_label = "Go To Waypoint"
    bl_description = "Apply selected waypoint to Navigation and move camera"

    index: IntProperty(default=-1, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        waypoints = getattr(props, "anim_waypoints", None)
        if waypoints is None or len(waypoints) == 0:
            return fail(
                self,
                "Add at least one waypoint first.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
        index = int(getattr(self, "index", -1))
        if index < 0 or index >= len(waypoints):
            index = _clamp_waypoint_active_index(props)
        waypoint = waypoints[index]
        nav_suspended = False
        try:
            suspend_navigation_shot_updates()
            nav_suspended = True
            props.nav_latitude_deg = float(getattr(waypoint, "latitude_deg", 0.0))
            props.nav_longitude_deg = float(getattr(waypoint, "longitude_deg", 0.0))
            props.nav_altitude_km = max(0.0, float(getattr(waypoint, "altitude_km", 0.0)))
            props.nav_azimuth_deg = float(getattr(waypoint, "heading_deg", 0.0))
            props.nav_tilt_deg = float(getattr(waypoint, "tilt_deg", 0.0))
            props.nav_roll_deg = float(getattr(waypoint, "roll_deg", 0.0))
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Failed applying waypoint: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka animation waypoint apply failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Failed applying waypoint: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )
        finally:
            if nav_suspended:
                resume_navigation_shot_updates()

        update_navigation_shot(props, context)
        props.anim_waypoint_active_index = int(index)
        self.report({'INFO'}, f"Waypoint {_waypoint_index_label(index)} applied.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationPreviewShot(bpy.types.Operator):
    bl_idname = "planetka.animation_preview_shot"
    bl_label = "Preview Animation"
    bl_description = "Preview camera animation on currently loaded tiles (no resolve/prefetch)"

    _timer = None
    _frame_change_handler = None
    _running = False
    _scene = None
    _props = None
    _frame_start = 0
    _frame_end = 0
    _pending_starts = None
    _last_frame = None
    _handler_last_frame = None
    _boundary_pause_until = 0.0
    _boundary_failures = None
    _original_auto_resolve = True
    _original_use_preview_range = False
    _original_preview_start = 0
    _original_preview_end = 0

    def _dedupe_requests(self, requests):
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

    def _resolve_frame_with_integrity(self, scene, props, frame_value, max_attempts=3):
        frame_int = int(frame_value)
        attempts = max(1, int(max_attempts))
        last_message = ""
        for _attempt in range(1, attempts + 1):
            try:
                scene.frame_set(frame_int)
                bpy.context.view_layer.update()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation preview: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation preview: suppressed recoverable exception", exc_info=True)
            _apply_keyed_runtime_scene_state(scene, props)
            try:
                result = bpy.ops.planetka.load_textures(scope_mode='CAMERA', silent=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                last_message = f"Resolve failed at frame {frame_int:04d}: {exc}"
                continue
            except (RuntimeError, TypeError, ValueError) as exc:
                last_message = f"Resolve failed at frame {frame_int:04d}: {exc}"
                continue
            if "FINISHED" not in result:
                last_message = f"Resolve returned {result} at frame {frame_int:04d}"
                continue
            missing_images = _count_missing_tile_loading_images(material_name="Planetka Earth Material")
            if int(missing_images) > 0:
                last_message = (
                    f"Resolve left {int(missing_images)} missing shader image assignment(s) at frame {frame_int:04d}"
                )
                continue
            return True, ""
        return False, (last_message or f"Resolve failed at frame {frame_int:04d}")

    def _stop_playback(self):
        if _is_animation_playing():
            try:
                bpy.ops.screen.animation_play()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation preview: failed stopping playback", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation preview: failed stopping playback", exc_info=True)

    def _cleanup_preview_runtime(self, context):
        wm = getattr(context, "window_manager", None)
        if self._timer is not None and wm is not None:
            try:
                wm.event_timer_remove(self._timer)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation preview: failed removing modal timer", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation preview: failed removing modal timer", exc_info=True)
        self._timer = None

        if self._frame_change_handler is not None:
            try:
                if self._frame_change_handler in bpy.app.handlers.frame_change_pre:
                    bpy.app.handlers.frame_change_pre.remove(self._frame_change_handler)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation preview: failed removing frame-change handler", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation preview: failed removing frame-change handler", exc_info=True)
        self._frame_change_handler = None

        scene = self._scene
        props = self._props
        if scene is not None:
            try:
                scene.use_preview_range = bool(self._original_use_preview_range)
                scene.frame_preview_start = int(self._original_preview_start)
                scene.frame_preview_end = int(self._original_preview_end)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation preview: failed restoring preview-range settings", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation preview: failed restoring preview-range settings", exc_info=True)
        if props is not None:
            try:
                props.auto_resolve = bool(self._original_auto_resolve)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation preview: failed restoring auto-resolve", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation preview: failed restoring auto-resolve", exc_info=True)

        self._scene = None
        self._props = None
        self._pending_starts = set()
        self._boundary_failures = []
        self._handler_last_frame = None
        self._running = False

    def _finish_preview(self, context, cancelled=False):
        self._stop_playback()
        failures = list(self._boundary_failures or ())
        self._cleanup_preview_runtime(context)
        if cancelled:
            self.report({'INFO'}, "Animation preview cancelled.")
            return {'CANCELLED'}
        if failures:
            self.report(
                {'WARNING'},
                (
                    f"Animation preview finished with {len(failures)} segment resolve issue(s). "
                    "See system console for details."
                ),
            )
        else:
            self.report({'INFO'}, "Animation preview finished.")
        return {'FINISHED'}

    def execute(self, context):
        if _is_animation_playing():
            try:
                bpy.ops.screen.animation_play()
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    f"Pause preview failed: {exc}",
                    code=ErrorCode.NAV_APPLY_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation preview pause failed",
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                return fail(
                    self,
                    f"Pause preview failed: {exc}",
                    code=ErrorCode.NAV_APPLY_FAILED,
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

        prefs = get_prefs()
        if not _require_commercial_animation_render_access(self, prefs):
            return {'CANCELLED'}
        try:
            start_frame, end_frame = apply_cinematic_preview(scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Preview animation failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka animation preview setup failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Preview animation failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        try:
            scene.use_preview_range = True
            scene.frame_preview_start = int(start_frame)
            scene.frame_preview_end = int(end_frame)
            scene.frame_set(int(start_frame))
            bpy.context.view_layer.update()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation preview: failed setting playback range", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation preview: failed setting playback range", exc_info=True)

        _try_start_preview_playback()
        self.report({'INFO'}, "Preview animation started on currently loaded tiles.")
        return {'FINISHED'}

    def modal(self, context, event):
        if not self._running:
            return {'CANCELLED'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return self._finish_preview(context, cancelled=True)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        scene = self._scene
        if scene is None:
            return self._finish_preview(context, cancelled=True)

        now = time.monotonic()
        current_frame = int(getattr(scene, "frame_current", self._frame_start))
        wrapped = (self._last_frame is not None and current_frame < int(self._last_frame))
        reached_end = current_frame >= int(self._frame_end)
        self._last_frame = int(current_frame)

        if wrapped or reached_end:
            return self._finish_preview(context, cancelled=False)

        # If playback is temporarily paused during boundary resolve, wait a bit.
        if (not _is_animation_playing()) and now < float(self._boundary_pause_until):
            return {'RUNNING_MODAL'}

        # User paused preview manually before end -> finish gracefully.
        if not _is_animation_playing():
            return self._finish_preview(context, cancelled=False)

        return {'RUNNING_MODAL'}


class PLANETKA_OT_AnimationClearPrepared(bpy.types.Operator):
    bl_idname = "planetka.animation_clear_prepared"
    bl_label = "Clear Quick Preview"
    bl_description = "Remove prepared segment assets and restore the normal Earth rendering workflow"

    def execute(self, context):
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


class PLANETKA_OT_AnimationRenderHeadless(bpy.types.Operator):
    bl_idname = "planetka.animation_render_headless"
    bl_label = "Render Animation"
    bl_description = "Render animation in UI, segment-by-segment, always using Full Quality textures"

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
    _original_frame = 1
    _original_frame_start = 1
    _original_frame_end = 1
    _original_auto_resolve = True
    _original_texture_quality_mode = "PREVIEW"
    _eevee_temp_displacement_state = None
    _segment_failures = None

    def invoke(self, context, event):
        del event
        return self.execute(context)

    def _get_selected_texture_quality_mode(self, props):
        del props
        # Final Animation Render is fixed to Full Quality by design.
        return "FULL"

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

    def _restore_runtime_state(self):
        scene = self._scene
        props = self._props
        if props is not None:
            try:
                props.auto_resolve = bool(self._original_auto_resolve)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: failed restoring auto-resolve", exc_info=True)
            try:
                props.texture_quality_mode = str(self._original_texture_quality_mode or "PREVIEW")
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: failed restoring texture quality mode", exc_info=True)

        if scene is not None:
            try:
                scene.frame_start = int(self._original_frame_start)
                scene.frame_end = int(self._original_frame_end)
                scene.frame_set(int(self._original_frame))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: failed restoring frame range", exc_info=True)
            try:
                if ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY in scene:
                    del scene[ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY]
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: failed clearing EEVEE bump-only runtime flag", exc_info=True)

        if self._eevee_temp_displacement_state:
            try:
                _restore_material_displacement_mode_states(self._eevee_temp_displacement_state)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: failed restoring Earth displacement mode after render", exc_info=True)
        self._eevee_temp_displacement_state = None

    def _cleanup(self, context):
        self._remove_timer(context)
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

    def _cancel_with_error(self, context, message):
        text = str(message or "Animation render failed.").strip() or "Animation render failed."
        self.report({'ERROR'}, text)
        logger.error("Planetka animation render failed: %s", text)
        self._cleanup(context)
        return {'CANCELLED'}

    def _finish_success(self, context):
        failures = list(self._segment_failures or ())
        segment_count = len(self._segments or ())
        self._cleanup(context)
        self.report({'INFO'}, f"Animation render complete ({segment_count} segments).")
        if failures:
            self.report({'WARNING'}, f"{len(failures)} segment step(s) reported issues. See console.")
        return {'FINISHED'}

    def _is_render_job_running(self):
        try:
            is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
            if callable(is_job_running):
                return bool(is_job_running("RENDER"))
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
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
        prefs = get_prefs()
        base_path = str(getattr(prefs, "texture_base_path", "") or "")
        if not is_remote_source_configured(base_path):
            return
        segments = list(self._segments or ())
        if int(segment_index) < 0 or int(segment_index) >= len(segments):
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
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, OSError):
                    logger.debug("Planetka animation: failed deleting completed-segment cache file", exc_info=True)
        if removed_files > 0:
            logger.debug(
                "Planetka animation: removed %d cache file(s) after segment %d.",
                int(removed_files),
                int(segment_index) + 1,
            )

    def _resolve_segment_frame(self, frame_value, tiles_override=None):
        scene = self._scene
        props = self._props
        frame_int = int(frame_value)
        if scene is None or props is None:
            return False, "Scene context became unavailable."
        try:
            scene.frame_set(frame_int)
            bpy.context.view_layer.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        _apply_keyed_runtime_scene_state(scene, props)
        op_kwargs = {
            "scope_mode": "CAMERA",
            "silent": True,
        }
        selected_mode = self._get_selected_texture_quality_mode(props)
        if selected_mode in {"PREVIEW", "BALANCED", "FULL"}:
            op_kwargs["texture_quality_mode_override"] = str(selected_mode)
        normalized_tiles = [str(tile or "").strip() for tile in (tiles_override or ()) if str(tile or "").strip()]
        if normalized_tiles:
            try:
                op_kwargs["tiles_override_json"] = json.dumps(normalized_tiles, separators=(",", ":"))
            except (TypeError, ValueError):
                logger.debug("Planetka animation: failed serializing segment tile override", exc_info=True)
        try:
            result = bpy.ops.planetka.load_textures(**op_kwargs)
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
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        return True, ""

    def _launch_segment_render(self, segment, invoke_ui=True):
        scene = self._scene
        if scene is None:
            return False, "Scene context became unavailable."
        start = int(segment.get("start", 1))
        end = int(segment.get("end", start))
        try:
            scene.frame_start = int(start)
            scene.frame_end = int(end)
            scene.frame_set(int(start))
            bpy.context.view_layer.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        try:
            # Mark launch wall-time immediately before invoking Blender render op.
            # This avoids false "cancelled" detection on fast first frames.
            self._render_launch_wall_time = time.time()
            if bool(invoke_ui):
                result = bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
            else:
                try:
                    result = bpy.ops.render.render('EXEC_DEFAULT', animation=True, use_viewport=False)
                except TypeError:
                    result = bpy.ops.render.render('EXEC_DEFAULT', animation=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return False, f"Render launch failed for frames {start:04d}-{end:04d}: {exc}"
        except (RuntimeError, TypeError, ValueError) as exc:
            return False, f"Render launch failed for frames {start:04d}-{end:04d}: {exc}"
        if "RUNNING_MODAL" in result or "FINISHED" in result:
            return True, ""
        return False, f"Render launch returned {result} for frames {start:04d}-{end:04d}."

    def _segment_outputs_complete(self, segment, min_mtime=None):
        scene = self._scene
        if scene is None or _is_movie_output(scene):
            return False
        start = int(segment.get("start", 1))
        end = int(segment.get("end", start))
        min_mtime_value = None
        if min_mtime is not None:
            try:
                min_mtime_value = float(min_mtime)
            except (TypeError, ValueError):
                min_mtime_value = None
        for frame in range(start, end + 1):
            try:
                frame_path = bpy.path.abspath(scene.render.frame_path(frame=int(frame)))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: failed resolving segment frame output path", exc_info=True)
                return False
            if not frame_path or not os.path.isfile(frame_path):
                return False
            if min_mtime_value is not None:
                try:
                    frame_mtime = float(os.path.getmtime(frame_path))
                except (OSError, ValueError, TypeError):
                    return False
                if frame_mtime < (min_mtime_value - 0.2):
                    return False
        return True

    def execute(self, context):
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
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        prefs = get_prefs()
        if not _require_full_animation_access(self, prefs):
            return {'CANCELLED'}
        base_path = str(getattr(prefs, "texture_base_path", "") or "") if prefs else ""
        if (not base_path or not os.path.isdir(base_path)) and not is_remote_source_configured(base_path):
            return fail(
                self,
                "Planetka Cloud source is not available. Log in and retry.",
                code=ErrorCode.RESOLVE_PATH_INVALID,
                logger=logger,
            )
        if _is_movie_output(scene):
            return fail(
                self,
                "Render Animation requires image-sequence output (PNG/EXR).",
                code=ErrorCode.RENDER_FAILED,
                logger=logger,
            )

        try:
            start_frame, end_frame = apply_cinematic_preview(scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Failed to set cinematic keyframes: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka full animation preview setup failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Failed to set cinematic keyframes: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        frame_start = int(start_frame)
        frame_end = int(end_frame)
        if frame_end < frame_start:
            return fail(
                self,
                f"Invalid frame range: {frame_start}-{frame_end}.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        original_frame = int(getattr(scene, "frame_current", frame_start))
        original_auto_resolve = bool(getattr(props, "auto_resolve", True))
        original_texture_quality_mode = str(getattr(props, "texture_quality_mode", "PREVIEW") or "PREVIEW").upper()
        selected_texture_quality_mode = self._get_selected_texture_quality_mode(props)
        render = getattr(scene, "render", None)
        eevee_temp_displacement_state = None
        original_frame_start = int(getattr(scene, "frame_start", frame_start))
        original_frame_end = int(getattr(scene, "frame_end", frame_end))

        segments = []
        try:
            props.auto_resolve = False
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: failed disabling auto-resolve for animation render", exc_info=True)
        try:
            props.texture_quality_mode = str(selected_texture_quality_mode)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: failed applying selected texture quality mode for animation render", exc_info=True)

        try:
            segment_plan = _plan_animation_segments(
                scene,
                frame_start,
                frame_end,
                frame_step=1,
                texture_quality_mode_override=str(selected_texture_quality_mode),
            )
            segments = list(segment_plan.segments or ())
            if not segments:
                return self._cancel_with_error(
                    context,
                    "No animation segments were generated for the selected frame range.",
                )

            try:
                render_engine = str(getattr(render, "engine", "") or "").strip().upper()
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                render_engine = ""
            if render_engine in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
                eevee_materials = _earth_surface_materials()
                eevee_temp_displacement_state = _capture_material_displacement_mode_states(eevee_materials)
                _set_earth_surface_materials_bump_only()
                try:
                    scene[ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY] = True
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                    logger.debug("Planetka animation: failed setting EEVEE bump-only runtime flag", exc_info=True)
            self._scene = scene
            self._props = props
            self._segments = list(segments)
            self._segment_index = 0
            self._active_segment = None
            self._state = "RESOLVE"
            self._render_seen_active = False
            self._render_launch_time = 0.0
            self._original_frame = int(original_frame)
            self._original_frame_start = int(original_frame_start)
            self._original_frame_end = int(original_frame_end)
            self._original_auto_resolve = bool(original_auto_resolve)
            self._original_texture_quality_mode = str(original_texture_quality_mode)
            self._eevee_temp_displacement_state = eevee_temp_displacement_state
            self._segment_failures = []

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
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self.report({'INFO'}, "Render Animation cancelled.")
            self._cleanup(context)
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        scene = self._scene
        if scene is None:
            return self._cancel_with_error(context, "Animation scene context was lost.")

        if self._state == "RESOLVE":
            if self._segment_index >= len(self._segments or ()):
                return self._finish_success(context)
            segment = dict((self._segments or [])[self._segment_index])
            self._active_segment = segment
            seg_start = int(segment.get("start", 1))
            seg_end = int(segment.get("end", seg_start))
            print(f"[Planetka] Segment {self._segment_index + 1}/{len(self._segments)}: resolve {seg_start:04d}-{seg_end:04d}")
            ok, message = self._resolve_segment_frame(seg_start, tiles_override=segment.get("tiles", ()))
            if not ok:
                return self._cancel_with_error(context, message)
            ok, message = self._launch_segment_render(segment, invoke_ui=True)
            if not ok:
                return self._cancel_with_error(context, message)
            self._state = "RENDER"
            self._render_seen_active = False
            self._render_launch_time = time.monotonic()
            return {'RUNNING_MODAL'}

        if self._state == "RENDER":
            running = self._is_render_job_running()
            if running:
                self._render_seen_active = True
                return {'RUNNING_MODAL'}
            elapsed = float(time.monotonic() - float(self._render_launch_time))
            if (not self._render_seen_active) and elapsed < 0.75:
                return {'RUNNING_MODAL'}
            active_segment = self._active_segment or {}
            if not self._segment_outputs_complete(
                active_segment,
                min_mtime=self._render_launch_wall_time,
            ):
                # User closed/cancelled the render window before segment completed.
                self._cleanup(context)
                return {'CANCELLED'}
            self._cleanup_completed_segment_cache(self._segment_index)
            self._segment_index += 1
            self._active_segment = None
            self._state = "RESOLVE"
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}


class PLANETKA_OT_AnimationRenderInfo(bpy.types.Operator):
    bl_idname = "planetka.animation_render_info"
    bl_label = "Planetka Animation Render Info"
    bl_description = "Explain how Planetka Final Animation Render works"

    def execute(self, context):
        if bool(getattr(bpy.app, "background", False)):
            return {'FINISHED'}

        wm = getattr(context, "window_manager", None)
        windows = tuple(getattr(wm, "windows", ()) or ()) if wm is not None else ()
        if wm is None or not windows:
            return {'FINISHED'}

        lines = (
            "Render Animation dynamically loads tiles (LODs)",
            "during the rendering process.",
            "",
            "Planetka Animation Render always uses Full Quality textures",
            "to ensure smooth seamless tile transitions.",
        )

        def _draw(_self, _popup_context):
            layout = getattr(_self, "layout", None)
            if layout is None:
                return
            col = layout.column(align=True)
            for line in lines:
                if str(line).strip():
                    col.label(text=str(line))
                else:
                    col.separator()

        try:
            wm.popup_menu(_draw, title="Planetka Animation Render", icon='QUESTION')
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: failed opening render info popup", exc_info=True)
        return {'FINISHED'}


class PLANETKA_OT_AnimationMakeReady(bpy.types.Operator):
    bl_idname = "planetka.animation_make_ready"
    bl_label = "Build Quick Preview"
    bl_description = (
        "Download Preview-quality data for all animation segments, build segment meshes/materials, "
        "and key visibility for smooth timeline playback"
    )

    def execute(self, context):
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
            base_path = str(getattr(prefs, "texture_base_path", "") or "")
            if (not base_path or not os.path.isdir(base_path)) and not is_remote_source_configured(base_path):
                return fail(
                    self,
                    "Planetka Cloud source is not available. Log in and retry.",
                    code=ErrorCode.RESOLVE_PATH_INVALID,
                    logger=logger,
                )

            try:
                start_frame, end_frame = apply_cinematic_preview(scene, props)
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                return fail(
                    self,
                    f"Failed to set cinematic keyframes: {exc}",
                    code=ErrorCode.NAV_APPLY_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation make-ready preview failed",
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                return fail(
                    self,
                    f"Failed to set cinematic keyframes: {exc}",
                    code=ErrorCode.NAV_APPLY_FAILED,
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

            texture_bytes = _estimate_texture_bytes_for_segments(segments, base_path)
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
                    base_path=base_path,
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
                auto_resolve_value=bool(getattr(props, "auto_resolve", True)),
            )
            try:
                props.auto_resolve = False
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            self.report(
                {'INFO'},
                (
                    f"Quick Preview ready: {len(segments)} segments "
                    f"({created_count} mesh assets), ~{texture_mb:.0f} MB textures. "
                    "Preview quality preloaded. Auto Resolve disabled; use timeline playback."
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
