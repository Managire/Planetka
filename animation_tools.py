import importlib
import math
import os

import bpy
from bpy.props import EnumProperty
from mathutils import Matrix, Quaternion, Vector

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .state import (
    create_temp_mesh,
    cleanup_planetka_unused_data,
    logger,
    remove_object_and_unused_mesh,
)
from . import shader_utils


ANIMATION_COLLECTION_NAME = "Planetka Animation Prepared"
ANIMATION_SEGMENT_OBJECT_PREFIX = "Planetka Anim Frames"
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


def _estimate_texture_bytes_for_segments(segments, base_path):
    unique_paths = set()
    total_bytes = 0
    for segment in segments:
        for tile in segment.get("tiles", ()):
            if not _is_land_tile(tile):
                continue
            for path in _iter_texture_paths_for_tile(base_path, tile):
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


def _make_texture_groups_unique(material, segment_index):
    if not material or not material.use_nodes or not material.node_tree:
        raise RuntimeError("Segment material node tree is missing.")
    loading_node = material.node_tree.nodes.get("Planetka Textures Loading")
    if not loading_node or not getattr(loading_node, "node_tree", None):
        raise RuntimeError("Segment material is missing 'Planetka Textures Loading'.")

    created_groups = []
    loading_tree = loading_node.node_tree.copy()
    loading_tree.name = f"{loading_tree.name}_anim_{int(segment_index):04d}"
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
        tile_tree.name = f"{tile_tree.name}_anim_{int(segment_index):04d}"
        node.node_tree = tile_tree
        try:
            tile_tree.use_fake_user = False
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        tile_tree[ANIMATION_SEGMENT_GROUP_TAG_KEY] = True
        created_groups.append(tile_tree)
    return created_groups


def _create_segment_material(segment_index):
    base_material = bpy.data.materials.get("Planetka Earth Material")
    if base_material is None:
        raise RuntimeError("Base material 'Planetka Earth Material' is missing.")
    segment_material = base_material.copy()
    segment_material.name = f"{ANIMATION_SEGMENT_MATERIAL_PREFIX} {int(segment_index):04d}"
    segment_material[ANIMATION_SEGMENT_MATERIAL_TAG_KEY] = True
    _make_texture_groups_unique(segment_material, segment_index)
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


def _resolve_tiles_for_frame(scene, frame):
    tile_utils = _get_tile_utils()
    if tile_utils is None:
        raise RuntimeError("Tile utilities are unavailable.")
    scene.frame_set(int(frame))
    try:
        bpy.context.view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    try:
        return list(tile_utils.main(scope_mode="CAMERA"))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: tile resolve failed at frame %s", frame, exc_info=True)
        return []
    except RuntimeError:
        logger.debug("Planetka animation: tile resolve runtime failure at frame %s", frame, exc_info=True)
        return []


def _build_segments(scene, frame_start, frame_end, frame_step):
    frames = list(range(int(frame_start), int(frame_end) + 1, max(1, int(frame_step))))
    if not frames:
        return []

    segments = []
    current_start = int(frames[0])
    current_tiles = _canonical_tiles(_resolve_tiles_for_frame(scene, current_start))
    segment_index = 1

    for index in range(1, len(frames)):
        frame = int(frames[index])
        sampled_tiles = _canonical_tiles(_resolve_tiles_for_frame(scene, frame))
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


def _segment_display_name(segment_start, segment_end):
    try:
        start = int(segment_start)
        end = int(segment_end)
    except (TypeError, ValueError):
        start = 0
        end = 0
    return f"Planetka Earth Surface Frames {start:04d}-{end:04d}"


def _estimate_texture_bytes_for_tiles(tiles, base_path):
    unique_paths = set()
    total_bytes = 0
    for tile in tiles or ():
        if not _is_land_tile(tile):
            continue
        for path in _iter_texture_paths_for_tile(base_path, tile):
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

    collection = bpy.data.collections.get(ANIMATION_COLLECTION_NAME)
    if collection is not None and not collection.objects:
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

    for key in (
        ANIMATION_STATS_SEGMENTS_KEY,
        ANIMATION_STATS_TEXTURE_MB_KEY,
        ANIMATION_STATS_START_KEY,
        ANIMATION_STATS_END_KEY,
        ANIMATION_PREPARED_AUTO_RESOLVE_PREV_KEY,
        ANIMATION_BASE_SURFACE_NAME_KEY,
        ANIMATION_BASE_SURFACE_HIDE_RENDER_KEY,
        ANIMATION_BASE_SURFACE_HIDE_VIEWPORT_KEY,
    ):
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


def _prepare_segments(scene, segments, frame_start, frame_end):
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

            segment_material = _create_segment_material(segment_index)
            _assign_material(segment_obj, segment_material)
            shader_utils.main(
                segment_tiles,
                material_name=segment_material.name,
                force_remove_datablocks=False,
                allow_slot_shrink=True,
            )
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
    except Exception:
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
    return value * value * (3.0 - (2.0 * value))


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


def _set_camera_from_shot(scene, shot, frame, look_target_override=None, up_hint_override=None):
    camera = getattr(scene, "camera", None)
    if camera is None:
        raise RuntimeError("Active camera is missing.")
    pose = _compute_navigation_pose(
        scene,
        shot,
        look_target_override=look_target_override,
        up_hint_override=up_hint_override,
    )
    scene.frame_set(int(frame))
    camera.matrix_world = Matrix.LocRotScale(pose["location"], pose["rotation"], pose["scale"])
    camera.keyframe_insert(data_path="location", frame=int(frame))
    camera.keyframe_insert(data_path="rotation_euler", frame=int(frame))
    return pose


def _set_camera_transform_keyframe(scene, frame, location, rotation_euler):
    camera = getattr(scene, "camera", None)
    if camera is None:
        raise RuntimeError("Active camera is missing.")
    scene.frame_set(int(frame))
    camera.location = Vector(location)
    camera.rotation_euler = rotation_euler
    camera.keyframe_insert(data_path="location", frame=int(frame))
    camera.keyframe_insert(data_path="rotation_euler", frame=int(frame))


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


def _build_shot_pair(scene, props):
    preset = str(getattr(props, "anim_camera_preset", "ORBIT")).upper()
    strength = max(0.1, float(getattr(props, "anim_camera_strength", 1.0)))
    base = _current_camera_base_shot(scene, props)
    base_lon = float(base.get("lon", 0.0))
    base_lat = float(base.get("lat", 0.0))
    base_alt = max(0.0, float(base.get("alt_km", 400.0)))
    base_heading = float(base.get("heading_deg", 0.0))
    base_tilt = float(base.get("tilt_deg", 25.0))
    base_roll = float(base.get("roll_deg", 0.0))

    default_start_alt = max(1.0, base_alt * 1.8)
    start_alt = max(0.0, float(getattr(props, "anim_start_altitude_km", default_start_alt)))
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
        direction = str(getattr(props, "anim_circle_direction", "CLOCKWISE")).upper()
        orbit_sign = 1.0 if direction != "COUNTERCLOCKWISE" else -1.0
        end["heading_deg"] = float(base_heading + (orbit_degrees * orbit_sign))
    elif preset == "ARC_LEFT":
        end["heading_deg"] = float(base_heading - (orbit_degrees * 0.6))
        end["tilt_deg"] = float(max(-90.0, min(90.0, base_tilt + (10.0 * strength))))
        end["alt_km"] = max(0.0, base_alt * (1.2 + (0.2 * strength)))
    elif preset == "ARC_RIGHT":
        end["heading_deg"] = float(base_heading + (orbit_degrees * 0.6))
        end["tilt_deg"] = float(max(-90.0, min(90.0, base_tilt + (10.0 * strength))))
        end["alt_km"] = max(0.0, base_alt * (1.2 + (0.2 * strength)))
    elif preset == "PUSH_IN":
        start["alt_km"] = max(start_alt, end_alt)
        end["alt_km"] = min(start_alt, end_alt)
        end["heading_deg"] = float(base_heading + zoom_rotate_degrees)
    elif preset == "PULL_BACK":
        start["alt_km"] = min(start_alt, end_alt)
        end["alt_km"] = max(start_alt, end_alt)
        end["heading_deg"] = float(base_heading + zoom_rotate_degrees)
    elif preset == "HELIX_DOWN":
        direction = str(getattr(props, "anim_circle_direction", "CLOCKWISE")).upper()
        orbit_sign = 1.0 if direction != "COUNTERCLOCKWISE" else -1.0
        start["alt_km"] = max(start_alt, end_alt)
        end["alt_km"] = min(start_alt, end_alt)
        end["heading_deg"] = float(base_heading + (orbit_degrees * orbit_sign))
    elif preset == "HELIX_UP":
        direction = str(getattr(props, "anim_circle_direction", "CLOCKWISE")).upper()
        orbit_sign = 1.0 if direction != "COUNTERCLOCKWISE" else -1.0
        start["alt_km"] = min(start_alt, end_alt)
        end["alt_km"] = max(start_alt, end_alt)
        end["heading_deg"] = float(base_heading + (orbit_degrees * orbit_sign))

    return start, end


def _build_simple_flyby(scene, props):
    strength = max(0.1, float(getattr(props, "anim_camera_strength", 1.0)))
    base = _current_camera_base_shot(scene, props)
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
    for frame in range(int(start_frame), int(end_frame) + 1):
        raw_t = 0.0 if total <= 0 else float(frame - int(start_frame)) / float(total)
        t = _eased_progress(raw_t, motion_curve)
        shot = _interpolate_shot(start_shot, end_shot, t)
        _set_camera_from_shot(scene, shot, frame)


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
    start_position = base_position - (travel_direction * half_distance)
    end_position = base_position + (travel_direction * half_distance)

    camera = getattr(scene, "camera", None)
    if camera is None:
        raise RuntimeError("Active camera is missing.")

    total = max(1, int(end_frame) - int(start_frame))
    for frame in range(int(start_frame), int(end_frame) + 1):
        raw_t = 0.0 if total <= 0 else float(frame - int(start_frame)) / float(total)
        t = _eased_progress(raw_t, motion_curve)
        position = start_position.lerp(end_position, t)
        scene.frame_set(int(frame))
        camera.matrix_world = Matrix.LocRotScale(position, base_rotation, camera_scale)
        camera.keyframe_insert(data_path="location", frame=int(frame))
        camera.keyframe_insert(data_path="rotation_euler", frame=int(frame))


def _ensure_camera_and_earth(scene):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Set an active camera and retry.")
    earth = get_earth_object()
    if earth is None:
        raise RuntimeError("Create Earth first, then use animation tools.")
    return camera, earth


def apply_cinematic_preview(scene, props):
    _ensure_camera_and_earth(scene)
    start_frame = int(getattr(props, "anim_frame_start", int(scene.frame_start)))
    end_frame = int(getattr(props, "anim_frame_end", int(scene.frame_end)))
    if end_frame <= start_frame:
        raise RuntimeError("End frame must be greater than start frame.")
    motion_curve = str(getattr(props, "anim_motion_curve", "EASE_IN_OUT")).upper()
    _clear_camera_preview_keyframes(scene, start_frame, end_frame)

    preset = str(getattr(props, "anim_camera_preset", "ORBIT")).upper()
    if preset == "A_TO_B":
        if not bool(getattr(props, "anim_ab_a_valid", False)) or not bool(getattr(props, "anim_ab_b_valid", False)):
            raise RuntimeError("Save both View A and View B first.")
        camera = scene.camera
        current_matrix = camera.matrix_world.copy()
        try:
            _set_camera_transform_keyframe(
                scene,
                start_frame,
                tuple(getattr(props, "anim_ab_a_location", (0.0, 0.0, 0.0))),
                tuple(getattr(props, "anim_ab_a_rotation", (0.0, 0.0, 0.0))),
            )
            _set_camera_transform_keyframe(
                scene,
                end_frame,
                tuple(getattr(props, "anim_ab_b_location", (0.0, 0.0, 0.0))),
                tuple(getattr(props, "anim_ab_b_rotation", (0.0, 0.0, 0.0))),
            )
        finally:
            camera.matrix_world = current_matrix
        _apply_camera_motion_curve(scene, motion_curve)
    elif preset == "FLYBY":
        flyby = _build_simple_flyby(scene, props)
        _apply_simple_flyby_preview(scene, flyby, start_frame, end_frame, motion_curve)
    else:
        start_shot, end_shot = _build_shot_pair(scene, props)
        _apply_sampled_navigation_preview(
            scene,
            start_shot,
            end_shot,
            start_frame,
            end_frame,
            motion_curve,
        )

    scene.frame_set(start_frame)
    try:
        bpy.context.view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
    return start_frame, end_frame


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


def _force_viewports_to_solid_shading():
    """
    Best-effort switch all VIEW_3D spaces to Solid shading to reduce memory usage
    during heavy animation renders. Returns a list of (space, previous_type) for restore.
    """
    restored = []
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return restored
    for window in getattr(wm, "windows", ()):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in getattr(screen, "areas", ()):
            if getattr(area, "type", None) != 'VIEW_3D':
                continue
            for space in getattr(area, "spaces", ()):
                if getattr(space, "type", None) != 'VIEW_3D':
                    continue
                shading = getattr(space, "shading", None)
                if shading is None:
                    continue
                try:
                    prev = str(getattr(shading, "type", "") or "")
                    if prev and prev != "SOLID":
                        restored.append((space, prev))
                        shading.type = 'SOLID'
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    continue
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    continue
    return restored


def _restore_viewports_shading(shading_backup):
    for space, shading_type in shading_backup or ():
        shading = getattr(space, "shading", None)
        if shading is None:
            continue
        try:
            shading.type = str(shading_type)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue


def _is_movie_output(scene):
    render = getattr(scene, "render", None) if scene else None
    image_settings = getattr(render, "image_settings", None) if render else None
    fmt = str(getattr(image_settings, "file_format", "") or "") if image_settings else ""
    return fmt in {"FFMPEG", "AVI_JPEG", "AVI_RAW"}


def _movie_extension(scene):
    render = getattr(scene, "render", None) if scene else None
    image_settings = getattr(render, "image_settings", None) if render else None
    fmt = str(getattr(image_settings, "file_format", "") or "") if image_settings else ""
    if fmt == "AVI_JPEG" or fmt == "AVI_RAW":
        return ".avi"
    if fmt != "FFMPEG":
        return ""
    ffmpeg = getattr(render, "ffmpeg", None) if render else None
    container = str(getattr(ffmpeg, "format", "") or "") if ffmpeg else ""
    return {
        "MPEG4": ".mp4",
        "QUICKTIME": ".mov",
        "MATROSKA": ".mkv",
        "WEBM": ".webm",
        "OGG": ".ogv",
    }.get(container, ".mp4")


_MOVIE_EXTS = (
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".ogv",
    ".mpeg",
    ".mpg",
)


def _list_dir_safe(path):
    try:
        return set(os.listdir(path)) if path and os.path.isdir(path) else set()
    except OSError:
        return set()


def _pick_best_movie_path(directory, prefix_basename, candidates):
    best_path = ""
    best_score = (-1.0, -1)  # (mtime, size)
    for name in candidates:
        if not name.startswith(prefix_basename):
            continue
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext and ext not in _MOVIE_EXTS:
            continue
        try:
            stat = os.stat(full)
            score = (float(stat.st_mtime), int(stat.st_size))
        except OSError:
            continue
        if score > best_score:
            best_score = score
            best_path = full
    return best_path


def _find_segment_movie_output(segment_base_abs, before_listing, expected_ext):
    """
    After rendering, locate the produced movie file for a segment.
    Blender output naming can vary depending on file extension settings, so this
    uses a prefix scan instead of assuming exact filename.
    """
    if not segment_base_abs:
        return ""
    directory = os.path.dirname(segment_base_abs) or ""
    prefix = os.path.basename(segment_base_abs)
    if not directory or not os.path.isdir(directory):
        return ""

    after = _list_dir_safe(directory)
    new = after - (before_listing or set())
    if expected_ext:
        expected_name = f"{prefix}{expected_ext}"
        if expected_name in after:
            return os.path.join(directory, expected_name)

    # Prefer newly created/changed files, then fallback to any matching prefix.
    picked = _pick_best_movie_path(directory, prefix, new)
    if picked:
        return picked
    return _pick_best_movie_path(directory, prefix, after)


def _resolve_movie_output_base(scene):
    """
    Returns (base_path_without_ext, ext).
    Keeps user intent: if render.filepath points to a directory, derive a sane filename.
    """
    render = getattr(scene, "render", None) if scene else None
    raw = str(getattr(render, "filepath", "") or "") if render else ""
    abs_path = bpy.path.abspath(raw) if raw else ""
    ext = _movie_extension(scene)

    if not abs_path:
        return "", ext

    # Blender allows render.filepath to be a directory (ending with /).
    is_dir_hint = abs_path.endswith(os.sep) or (os.path.isdir(abs_path) and not os.path.splitext(abs_path)[1])
    if is_dir_hint:
        output_dir = abs_path.rstrip(os.sep)
        blend_name = bpy.path.display_name_from_filepath(getattr(bpy.data, "filepath", "") or "")
        base_name = blend_name or "Planetka_Animation"
        return os.path.join(output_dir, base_name), ext

    root, existing_ext = os.path.splitext(abs_path)
    if existing_ext:
        return root, existing_ext
    return abs_path, ext


def _copy_ffmpeg_settings(src_render, dst_render):
    src = getattr(src_render, "ffmpeg", None) if src_render else None
    dst = getattr(dst_render, "ffmpeg", None) if dst_render else None
    if src is None or dst is None:
        return
    for prop in getattr(src.bl_rna, "properties", ()):
        ident = getattr(prop, "identifier", "")
        if not ident or ident in {"rna_type"}:
            continue
        try:
            setattr(dst, ident, getattr(src, ident))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue


def _render_output_display(scene):
    render = getattr(scene, "render", None) if scene else None
    if render is None:
        return "—"
    raw = str(getattr(render, "filepath", "") or "")
    try:
        abs_path = bpy.path.abspath(raw) if raw else ""
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        abs_path = raw
    image_settings = getattr(render, "image_settings", None)
    fmt = str(getattr(image_settings, "file_format", "") or "") if image_settings else ""
    if fmt in {"FFMPEG", "AVI_JPEG", "AVI_RAW"}:
        base, ext = _resolve_movie_output_base(scene)
        if base:
            return f"{base}{ext}"
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


def _concat_movie_segments_vse(scene, segment_movie_paths, final_movie_base, final_ext, frame_start, frame_end):
    if not segment_movie_paths:
        return False, "No segment movies to combine."
    concat_scene = bpy.data.scenes.new("Planetka Concat Temp")
    try:
        concat_scene.sequence_editor_create()
        concat_scene.render.use_sequencer = True
        concat_scene.frame_start = int(frame_start)
        concat_scene.frame_end = int(frame_end)
        try:
            concat_scene.render.resolution_x = int(scene.render.resolution_x)
            concat_scene.render.resolution_y = int(scene.render.resolution_y)
            concat_scene.render.resolution_percentage = int(scene.render.resolution_percentage)
            concat_scene.render.fps = int(scene.render.fps)
            concat_scene.render.fps_base = float(scene.render.fps_base)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

        # Some Blender versions still require a valid camera even when using the VSE.
        try:
            if getattr(scene, "camera", None) is not None:
                concat_scene.camera = scene.camera
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

        # Copy output settings so the final movie matches the user's chosen container/codec.
        src_render = getattr(scene, "render", None)
        dst_render = getattr(concat_scene, "render", None)
        if src_render and dst_render:
            try:
                dst_render.image_settings.file_format = src_render.image_settings.file_format
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            _copy_ffmpeg_settings(src_render, dst_render)
            try:
                dst_render.filepath = str(final_movie_base)
                if hasattr(dst_render, "use_file_extension"):
                    dst_render.use_file_extension = True
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

        # Insert each segment at its real frame start.
        seq_editor = concat_scene.sequence_editor
        sequences = getattr(seq_editor, "sequences", None)
        if sequences is None:
            sequences = getattr(seq_editor, "strips", None)
        if sequences is None:
            return False, "Blender VSE API unavailable (no sequences/strips collection)."
        for path in segment_movie_paths:
            seg_name = os.path.basename(path)
            # Parse "...__Frames_0001-0035.ext" if present; fallback: append sequentially.
            insert_at = None
            try:
                base = os.path.splitext(seg_name)[0]
                if "Frames_" in base and "-" in base:
                    frag = base.split("Frames_", 1)[1]
                    start_str = frag.split("-", 1)[0]
                    insert_at = int(start_str)
            except Exception:
                insert_at = None
            if insert_at is None:
                insert_at = int(concat_scene.frame_start)
            try:
                sequences.new_movie(seg_name, path, channel=1, frame_start=insert_at)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return False, f"Failed to add segment movie strip: {seg_name}"
            except (RuntimeError, TypeError, ValueError):
                return False, f"Failed to add segment movie strip: {seg_name}"

        # Render the sequencer-only scene to the final output movie.
        override = None
        try:
            override = bpy.context.copy()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            override = {}
        except Exception:
            override = {}
        if override is None:
            override = {}
        override["scene"] = concat_scene
        override["view_layer"] = concat_scene.view_layers[0] if concat_scene.view_layers else None
        try:
            wm = getattr(bpy.context, "window_manager", None)
            window = wm.windows[0] if wm and getattr(wm, "windows", None) else None
            if window:
                override["window"] = window
                override["screen"] = window.screen
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except Exception:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

        with bpy.context.temp_override(**override):
            result = bpy.ops.render.render(animation=True, use_viewport=False)
        ok = "FINISHED" in result
        final_path = f"{final_movie_base}{final_ext}"
        if ok and final_path and os.path.isfile(final_path):
            return True, ""
        if ok:
            # Blender may pick extension differently; locate by prefix.
            directory = os.path.dirname(final_movie_base) or ""
            prefix = os.path.basename(final_movie_base)
            picked = _pick_best_movie_path(directory, prefix, _list_dir_safe(directory))
            if picked:
                return True, ""
            return False, "Sequencer render finished but output movie was not created."
        return False, "Sequencer render was cancelled."
    finally:
        try:
            bpy.data.scenes.remove(concat_scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)


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
        if slot == "A":
            props.anim_ab_a_location = location
            props.anim_ab_a_rotation = rotation
            props.anim_ab_a_valid = True
        else:
            props.anim_ab_b_location = location
            props.anim_ab_b_rotation = rotation
            props.anim_ab_b_valid = True

        self.report({'INFO'}, f"Saved camera view {slot}.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationPreviewShot(bpy.types.Operator):
    bl_idname = "planetka.animation_preview_shot"
    bl_label = "Preview Shot"
    bl_description = "Generate preview keyframes for the selected cinematic preset on the timeline"

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
            self.report({'INFO'}, "Cinematic preview paused.")
            return {'FINISHED'}

        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        try:
            start_frame, end_frame = apply_cinematic_preview(scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Preview shot failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka animation preview failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Preview shot failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        _try_start_preview_playback()
        self.report({'INFO'}, f"Cinematic preview set on frames {int(start_frame)}-{int(end_frame)}.")
        return {'FINISHED'}


class PLANETKA_OT_AnimationClearPrepared(bpy.types.Operator):
    bl_idname = "planetka.animation_clear_prepared"
    bl_label = "Clear Prepared Animation"
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
    bl_label = "Prepare Animation Render"
    bl_description = "Render animation with segment-boundary Resolve updates to reduce peak memory usage"

    def _build_preview_data(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return False
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return False

        prefs = get_prefs()
        base_path = str(getattr(prefs, "texture_base_path", "") or "") if prefs else ""
        if not base_path or not os.path.isdir(base_path):
            fail(
                self,
                "Set a valid Texture Source Directory before rendering.",
                code=ErrorCode.RESOLVE_PATH_INVALID,
                logger=logger,
            )
            return False

        frame_start = int(getattr(scene, "frame_start", 1))
        frame_end = int(getattr(scene, "frame_end", 1))
        if frame_end < frame_start:
            fail(
                self,
                f"Invalid frame range: {frame_start}-{frame_end}.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
            return False

        render = getattr(scene, "render", None)
        res_x = 0
        res_y = 0
        if render is not None:
            try:
                scale = float(getattr(render, "resolution_percentage", 100.0)) / 100.0
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
                scale = 1.0
            try:
                res_x = int(round(float(getattr(render, "resolution_x", 1920)) * scale))
                res_y = int(round(float(getattr(render, "resolution_y", 1080)) * scale))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
                res_x = 0
                res_y = 0
        output_path = _render_output_display(scene)
        engine_text = _render_engine_display(scene)
        file_format = None
        try:
            image_settings = getattr(render, "image_settings", None) if render else None
            file_format = str(getattr(image_settings, "file_format", "") or "") if image_settings else ""
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            file_format = ""

        original_frame = int(getattr(scene, "frame_current", frame_start))
        try:
            segments = _build_segments(scene, frame_start, frame_end, frame_step=1)
        finally:
            try:
                scene.frame_set(original_frame)
                bpy.context.view_layer.update()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

        if not segments:
            fail(
                self,
                "No animation segments were generated for the selected frame range.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
            return False

        segment_lines = []
        if len(segments) > 10:
            head = segments[:5]
            tail = segments[-4:]
            for seg in head:
                segment_lines.append(_segment_display_name(seg.get("start"), seg.get("end")))
            segment_lines.append("...")
            for seg in tail:
                segment_lines.append(_segment_display_name(seg.get("start"), seg.get("end")))
        else:
            for seg in segments:
                segment_lines.append(_segment_display_name(seg.get("start"), seg.get("end")))

        max_segment = None
        max_bytes = -1
        for seg in segments:
            seg_tiles = list(seg.get("tiles", ()))
            seg_bytes = _estimate_texture_bytes_for_tiles(seg_tiles, base_path)
            if seg_bytes > max_bytes:
                max_bytes = seg_bytes
                max_segment = seg

        self._preview_res_x = int(res_x)
        self._preview_res_y = int(res_y)
        self._preview_output_path = str(output_path or "—")
        self._preview_engine_text = str(engine_text or "—")
        self._preview_output_format = str(file_format or "")
        self._preview_frame_start = int(frame_start)
        self._preview_frame_end = int(frame_end)
        self._preview_frames_total = int(frame_end - frame_start + 1)
        self._preview_segments = list(segments)
        self._preview_segment_lines = list(segment_lines)
        self._preview_max_segment_name = (
            _segment_display_name(max_segment.get("start"), max_segment.get("end")) if isinstance(max_segment, dict) else "—"
        )
        self._preview_max_segment_mb = float(max(0, int(max_bytes))) / (1024.0 * 1024.0) if max_bytes >= 0 else 0.0
        return True

    def invoke(self, context, event):
        if not self._build_preview_data(context):
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        res_x = int(getattr(self, "_preview_res_x", 0))
        res_y = int(getattr(self, "_preview_res_y", 0))
        output_path = str(getattr(self, "_preview_output_path", "—") or "—")
        engine_text = str(getattr(self, "_preview_engine_text", "—") or "—")
        output_format = str(getattr(self, "_preview_output_format", "") or "")
        frame_start = int(getattr(self, "_preview_frame_start", 0))
        frame_end = int(getattr(self, "_preview_frame_end", 0))
        frames_total = int(getattr(self, "_preview_frames_total", 0))
        segments = getattr(self, "_preview_segments", None) or ()
        segment_lines = getattr(self, "_preview_segment_lines", None) or ()
        max_name = str(getattr(self, "_preview_max_segment_name", "—") or "—")
        max_mb = float(getattr(self, "_preview_max_segment_mb", 0.0) or 0.0)

        layout.label(text="Confirm Animation Render", icon="RENDER_ANIMATION")
        layout.separator()

        layout.label(text=f"Resolution: {res_x} x {res_y}" if res_x > 0 and res_y > 0 else "Resolution: —")
        layout.label(text=f"Engine: {engine_text}", icon="RESTRICT_RENDER_OFF" if engine_text == "—" else "RENDER_STILL")
        layout.label(
            text=f"Output: {output_path}",
            icon="FILE_FOLDER",
        )
        if output_format:
            layout.label(text=f"Format: {output_format}", icon="FILE")
        layout.label(text=f"Frames to render: {frames_total} ({frame_start:04d}-{frame_end:04d})")
        layout.label(text=f"Time segments: {len(segments)}")
        layout.separator()

        layout.label(text=f"Most expensive segment: {max_name} ({max_mb:.1f} MB textures)", icon="INFO")

        seg_box = layout.box()
        seg_box.label(text="Segments", icon="OUTLINER")
        col = seg_box.column(align=True)
        for line in segment_lines:
            col.label(text=str(line))

        layout.separator()
        layout.label(text="Blender will be unresponsive until rendering is finished.", icon="ERROR")
        layout.label(text="Press OK to confirm the render.", icon="INFO")

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        camera = getattr(scene, "camera", None)
        if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
            return fail(
                self,
                "Scene camera is missing. Set an active Camera and retry.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        prefs = get_prefs()
        base_path = str(getattr(prefs, "texture_base_path", "") or "") if prefs else ""
        if not base_path or not os.path.isdir(base_path):
            return fail(
                self,
                "Set a valid Texture Source Directory before rendering.",
                code=ErrorCode.RESOLVE_PATH_INVALID,
                logger=logger,
            )

        frame_start = int(getattr(scene, "frame_start", 1))
        frame_end = int(getattr(scene, "frame_end", 1))
        if frame_end < frame_start:
            return fail(
                self,
                f"Invalid frame range: {frame_start}-{frame_end}.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        original_frame = int(getattr(scene, "frame_current", frame_start))
        original_auto_resolve = bool(getattr(props, "auto_resolve", True))
        viewport_shading_backup = _force_viewports_to_solid_shading()

        render = getattr(scene, "render", None)
        cycles = getattr(scene, "cycles", None)

        original_settings = {
            "frame_start": int(getattr(scene, "frame_start", frame_start)),
            "frame_end": int(getattr(scene, "frame_end", frame_end)),
            "render_filepath": str(getattr(render, "filepath", "")) if render else None,
            "use_file_extension": bool(getattr(render, "use_file_extension", True))
            if render and hasattr(render, "use_file_extension")
            else None,
            "use_persistent_data": bool(getattr(render, "use_persistent_data", False)) if render else None,
            "display_mode": str(getattr(render, "display_mode", "")) if render and hasattr(render, "display_mode") else None,
            "use_lock_interface": bool(getattr(render, "use_lock_interface", False))
            if render and hasattr(render, "use_lock_interface")
            else None,
            "cycles_dicing_rate": float(getattr(cycles, "dicing_rate", 0.0)) if cycles and hasattr(cycles, "dicing_rate") else None,
            "cycles_offscreen_scale": float(getattr(cycles, "offscreen_dicing_scale", 0.0))
            if cycles and hasattr(cycles, "offscreen_dicing_scale")
            else None,
        }

        segments = []
        frame_change_handler = None
        segment_boundary_failures = []
        try:
            if bool(scene.get(ANIMATION_STATS_SEGMENTS_KEY, 0)):
                clear_prepared_animation_assets(scene)
                self.report({'INFO'}, "Prepared animation setup cleared (using headless segmented render).")

            props.auto_resolve = False

            try:
                segments = _build_segments(scene, frame_start, frame_end, frame_step=1)
            finally:
                try:
                    scene.frame_set(original_frame)
                    bpy.context.view_layer.update()
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            if not segments:
                return fail(
                    self,
                    "No animation segments were generated for the selected frame range.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )

            if render is not None:
                if hasattr(render, "use_persistent_data"):
                    render.use_persistent_data = bool(getattr(props, "anim_render_persistent_data", True))
                if hasattr(render, "use_lock_interface"):
                    render.use_lock_interface = True
                if hasattr(render, "display_mode"):
                    try:
                        render.display_mode = 'NONE'
                    except PLANETKA_RECOVERABLE_EXCEPTIONS:
                        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
                    except (RuntimeError, TypeError, ValueError):
                        logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            if cycles is not None:
                try:
                    if hasattr(cycles, "dicing_rate"):
                        cycles.dicing_rate = float(getattr(props, "anim_render_dicing_rate", 1.5))
                    if hasattr(cycles, "offscreen_dicing_scale"):
                        cycles.offscreen_dicing_scale = float(getattr(props, "anim_render_offscreen_scale", 1.5))
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
                except (RuntimeError, TypeError, ValueError):
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            # Resolve once at the first frame, then only on segment boundaries.
            segment_starts = sorted({int(seg.get("start", frame_start)) for seg in segments if isinstance(seg, dict)})
            pending_starts = {s for s in segment_starts if s > int(frame_start)}

            try:
                scene.frame_start = int(frame_start)
                scene.frame_end = int(frame_end)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            try:
                scene.frame_set(int(frame_start))
                bpy.context.view_layer.update()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            resolve_result = bpy.ops.planetka.load_textures(scope_mode='CAMERA', silent=True)
            if "FINISHED" not in resolve_result:
                return fail(
                    self,
                    f"Resolve failed at frame {int(frame_start)}.",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )
            try:
                cleanup_planetka_unused_data()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            guard = {"in_handler": False}

            def _planetka_segment_boundary_resolve(_scene):
                if guard["in_handler"]:
                    return
                try:
                    current = int(getattr(_scene, "frame_current", 0))
                except (TypeError, ValueError):
                    return
                if current not in pending_starts:
                    return
                guard["in_handler"] = True
                try:
                    print(f"[Planetka] Segment boundary at frame {current:04d}: resolving…")
                    try:
                        result = bpy.ops.planetka.load_textures(scope_mode='CAMERA', silent=True)
                    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                        message = f"Resolve failed at frame {current:04d}: {exc}"
                        print(f"[Planetka] WARNING: {message}")
                        segment_boundary_failures.append(message)
                        return
                    except (RuntimeError, TypeError, ValueError) as exc:
                        message = f"Resolve failed at frame {current:04d}: {exc}"
                        print(f"[Planetka] WARNING: {message}")
                        segment_boundary_failures.append(message)
                        return

                    if "FINISHED" in result:
                        try:
                            cleanup_planetka_unused_data()
                        except PLANETKA_RECOVERABLE_EXCEPTIONS:
                            logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
                        if not bool(getattr(props, "anim_render_persistent_data", True)):
                            try:
                                shader_utils.cleanup_planetka_images(force_remove_datablocks=True)
                            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
                    else:
                        message = f"Resolve operator returned {result} at frame {current:04d}"
                        print(f"[Planetka] WARNING: {message}")
                        segment_boundary_failures.append(message)
                    pending_starts.discard(current)
                finally:
                    guard["in_handler"] = False

            frame_change_handler = _planetka_segment_boundary_resolve
            bpy.app.handlers.frame_change_pre.append(frame_change_handler)

            render_result = bpy.ops.render.render(animation=True, use_viewport=False)
            if "FINISHED" not in render_result:
                return fail(
                    self,
                    "Render cancelled.",
                    code=ErrorCode.RENDER_FAILED,
                    logger=logger,
                )
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Animation render failed: {exc}",
                code=ErrorCode.RENDER_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka animation headless render failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Animation render failed: {exc}",
                code=ErrorCode.RENDER_FAILED,
                logger=logger,
            )
        finally:
            try:
                if frame_change_handler and frame_change_handler in bpy.app.handlers.frame_change_pre:
                    bpy.app.handlers.frame_change_pre.remove(frame_change_handler)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            _restore_viewports_shading(viewport_shading_backup)
            try:
                props.auto_resolve = bool(original_auto_resolve)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            try:
                scene.frame_set(original_frame)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            try:
                scene.frame_start = int(original_settings["frame_start"])
                scene.frame_end = int(original_settings["frame_end"])
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            if render is not None:
                try:
                    if original_settings["render_filepath"] is not None:
                        render.filepath = str(original_settings["render_filepath"])
                    if original_settings["use_file_extension"] is not None and hasattr(render, "use_file_extension"):
                        render.use_file_extension = bool(original_settings["use_file_extension"])
                    if original_settings["use_persistent_data"] is not None and hasattr(render, "use_persistent_data"):
                        render.use_persistent_data = bool(original_settings["use_persistent_data"])
                    if original_settings["display_mode"] is not None and hasattr(render, "display_mode"):
                        render.display_mode = str(original_settings["display_mode"])
                    if original_settings["use_lock_interface"] is not None and hasattr(render, "use_lock_interface"):
                        render.use_lock_interface = bool(original_settings["use_lock_interface"])
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
                except (RuntimeError, TypeError, ValueError):
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            if cycles is not None:
                try:
                    if original_settings["cycles_dicing_rate"] is not None and hasattr(cycles, "dicing_rate"):
                        cycles.dicing_rate = float(original_settings["cycles_dicing_rate"])
                    if original_settings["cycles_offscreen_scale"] is not None and hasattr(cycles, "offscreen_dicing_scale"):
                        cycles.offscreen_dicing_scale = float(original_settings["cycles_offscreen_scale"])
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
                except (RuntimeError, TypeError, ValueError):
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

        self.report({'INFO'}, f"Animation render complete ({len(segments)} segments).")
        if segment_boundary_failures:
            self.report(
                {'WARNING'},
                (
                    f"{len(segment_boundary_failures)} segment-boundary resolve step(s) failed. "
                    "See system console for details."
                ),
            )
        return {'FINISHED'}


class PLANETKA_OT_AnimationMakeReady(bpy.types.Operator):
    bl_idname = "planetka.animation_make_ready"
    bl_label = "Make Ready to Render"
    bl_description = "Prebuild segment meshes/materials, key visibility, and prepare the scene for segmented animation rendering"

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
            if not base_path or not os.path.isdir(base_path):
                return fail(
                    self,
                    "Set a valid Texture Source Directory before preparing animation render setup.",
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
            current_frame = int(scene.frame_current)
            try:
                segments = _build_segments(scene, start_frame, end_frame, frame_step)
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                scene.frame_set(current_frame)
                return fail(
                    self,
                    f"Segment analysis failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka animation segment analysis failed",
                )
            finally:
                try:
                    scene.frame_set(current_frame)
                    bpy.context.view_layer.update()
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            if not segments:
                return fail(
                    self,
                    "No animation segments were generated for the selected frame range.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )

            max_segments = max(1, int(getattr(props, "anim_prepare_max_segments", 64)))
            if len(segments) > max_segments:
                return fail(
                    self,
                    (
                        f"Animation requires {len(segments)} segments, exceeding limit {max_segments}. "
                        "Increase Max Segments or simplify movement."
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
                        f"Prepared animation needs about {texture_mb:.1f} MB textures, "
                        f"exceeding limit {max_texture_mb:.1f} MB."
                    ),
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )

            try:
                created_count = _prepare_segments(scene, segments, start_frame, end_frame)
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

            scene[ANIMATION_STATS_SEGMENTS_KEY] = int(len(segments))
            scene[ANIMATION_STATS_TEXTURE_MB_KEY] = float(texture_mb)
            scene[ANIMATION_STATS_START_KEY] = int(start_frame)
            scene[ANIMATION_STATS_END_KEY] = int(end_frame)
            try:
                scene[ANIMATION_PREPARED_AUTO_RESOLVE_PREV_KEY] = bool(getattr(props, "auto_resolve", True))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            try:
                props.auto_resolve = False
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka animation: suppressed recoverable exception", exc_info=True)

            self.report(
                {'INFO'},
                (
                    f"Animation render setup ready: {len(segments)} segments "
                    f"({created_count} mesh assets), ~{texture_mb:.1f} MB textures. "
                    "Auto Resolve disabled; render now."
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
