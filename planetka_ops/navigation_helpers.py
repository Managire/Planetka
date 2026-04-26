import bpy
import importlib
import math
from mathutils import Matrix, Quaternion, Vector

from ..asset_builder import ensure_planetka_root
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_earth_object, get_prefs
from ..sanity_utils import _normalize_texture_source_path
from ..r2_source import is_remote_source_configured, texture_file_exists
from ..state import (
    ensure_planetka_temp_collection,
    ensure_preview_object,
    logger,
    mark_navigation_camera_control_signature,
)
from .earth_lifecycle_helpers import _ensure_close_clip_limits, _is_planetka_create_camera

_RECOVERABLE_LOG_COUNTS = {}


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1

REAL_EARTH_RADIUS_M = 6371000.0
MAX_TERRAIN_HEIGHT_M = 9000.0
MAX_PROXIMITY_TARGET_SAFETY_RATIO = 1.08
DATASET_MPP_BASE_D1 = 10.0
FULL_GLOBE_EXTRA_MARGIN = 1.3
SHOT_ANCHOR_OBJECT_NAME = "Planetka Shot Anchor"
NAV_LAST_APPLIED_KEYS = {
    "lon": "planetka_nav_last_lon_deg",
    "lat": "planetka_nav_last_lat_deg",
    "alt": "planetka_nav_last_altitude_km",
    "heading": "planetka_nav_last_heading_deg",
    "tilt": "planetka_nav_last_tilt_deg",
    "roll": "planetka_nav_last_roll_deg",
}
NAV_FULL_GLOBE_TILT_LOCK_ENABLED_KEY = "planetka_nav_full_globe_tilt_lock_enabled"
NAV_FULL_GLOBE_TILT_LOCK_VALUE_KEY = "planetka_nav_full_globe_tilt_lock_value_deg"
RADIUS_SYNC_NOTICE_KEY = "planetka_status_radius_sync_notice"
NAV_CHANGE_EPS = 1e-6
NAV_UI_DECIMALS = 2
NAV_UI_ZERO_EPS = 0.005
NAV_D_LEVELS_BY_Z = {
    1: [1, 2, 4, 8, 15, 30, 60],
    2: [2, 4, 8, 15, 30, 60],
    4: [4, 8, 15, 30, 60],
    8: [8, 15, 30, 60],
    15: [15, 30, 60],
    30: [30, 60, 90, 180, 360],
    60: [60, 90, 180, 360],
    90: [90, 180, 360],
    180: [180, 360, 720],
    360: [360, 720, 1440],
}
_COVERAGE_MAP = None


def _read_last_navigation_values(scene):
    if scene is None:
        return None
    try:
        values = {
            "lon": float(scene.get(NAV_LAST_APPLIED_KEYS["lon"])),
            "lat": float(scene.get(NAV_LAST_APPLIED_KEYS["lat"])),
            "alt": float(scene.get(NAV_LAST_APPLIED_KEYS["alt"])),
            "heading": float(scene.get(NAV_LAST_APPLIED_KEYS["heading"])),
            "tilt": float(scene.get(NAV_LAST_APPLIED_KEYS["tilt"])),
            "roll": float(scene.get(NAV_LAST_APPLIED_KEYS["roll"])),
        }
        return values
    except (TypeError, ValueError, AttributeError):
        return None


def _store_last_navigation_values(scene, lon_deg, lat_deg, altitude_km, heading_deg, tilt_deg, roll_deg):
    if scene is None:
        return
    try:
        scene[NAV_LAST_APPLIED_KEYS["lon"]] = float(lon_deg)
        scene[NAV_LAST_APPLIED_KEYS["lat"]] = float(lat_deg)
        scene[NAV_LAST_APPLIED_KEYS["alt"]] = float(altitude_km)
        scene[NAV_LAST_APPLIED_KEYS["heading"]] = float(heading_deg)
        scene[NAV_LAST_APPLIED_KEYS["tilt"]] = float(tilt_deg)
        scene[NAV_LAST_APPLIED_KEYS["roll"]] = float(roll_deg)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-003", "Failed storing last navigation values to scene idprops")
    except (TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-004", "Failed storing last navigation values to scene idprops")


def _set_full_globe_tilt_lock(scene, tilt_deg):
    if scene is None:
        return
    try:
        scene[NAV_FULL_GLOBE_TILT_LOCK_ENABLED_KEY] = True
        scene[NAV_FULL_GLOBE_TILT_LOCK_VALUE_KEY] = float(tilt_deg)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-101", "Failed storing Full Globe tilt lock state")
    except (TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-102", "Failed storing Full Globe tilt lock state")


def _clear_full_globe_tilt_lock(scene):
    if scene is None:
        return
    try:
        if NAV_FULL_GLOBE_TILT_LOCK_ENABLED_KEY in scene:
            del scene[NAV_FULL_GLOBE_TILT_LOCK_ENABLED_KEY]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-103", "Failed clearing Full Globe tilt lock flag")
    except (TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-104", "Failed clearing Full Globe tilt lock flag")
    try:
        if NAV_FULL_GLOBE_TILT_LOCK_VALUE_KEY in scene:
            del scene[NAV_FULL_GLOBE_TILT_LOCK_VALUE_KEY]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-105", "Failed clearing Full Globe tilt lock value")
    except (TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-106", "Failed clearing Full Globe tilt lock value")


def _read_full_globe_tilt_lock(scene):
    if scene is None:
        return False, None
    try:
        enabled = bool(scene.get(NAV_FULL_GLOBE_TILT_LOCK_ENABLED_KEY, False))
    except (TypeError, ValueError, AttributeError):
        enabled = False
    if not enabled:
        return False, None
    try:
        locked_tilt_deg = float(scene.get(NAV_FULL_GLOBE_TILT_LOCK_VALUE_KEY))
    except (TypeError, ValueError, AttributeError):
        locked_tilt_deg = None
    return True, locked_tilt_deg


def _set_radius_sync_notice(scene, message):
    if scene is None:
        return
    text = str(message or "").strip()
    if not text:
        return
    try:
        scene[RADIUS_SYNC_NOTICE_KEY] = text
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-107", "Failed storing radius-sync status notice")
    except (TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-108", "Failed storing radius-sync status notice")


def _clear_radius_sync_notice(scene):
    if scene is None:
        return
    try:
        if RADIUS_SYNC_NOTICE_KEY in scene:
            del scene[RADIUS_SYNC_NOTICE_KEY]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-109", "Failed clearing radius-sync status notice")
    except (TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-110", "Failed clearing radius-sync status notice")


def _find_planetka_scene_camera(scene):
    if scene is None:
        return None
    scene_camera = getattr(scene, "camera", None)
    if (
        scene_camera is not None
        and str(getattr(scene_camera, "type", "")) == "CAMERA"
        and _is_planetka_create_camera(scene_camera)
    ):
        return scene_camera
    for obj in tuple(getattr(scene, "objects", ())):
        if (
            obj is not None
            and str(getattr(obj, "type", "")) == "CAMERA"
            and _is_planetka_create_camera(obj)
        ):
            return obj
    return None


def _quantize_navigation_ui_value(value, minimum=None):
    try:
        normalized = float(value)
    except (TypeError, ValueError, AttributeError):
        normalized = 0.0
    if minimum is not None:
        try:
            min_value = float(minimum)
            if normalized < min_value:
                normalized = min_value
        except (TypeError, ValueError, AttributeError):
            pass
    quantized = round(float(normalized), int(NAV_UI_DECIMALS))
    if abs(float(quantized)) < float(NAV_UI_ZERO_EPS):
        quantized = 0.0
    return float(quantized)


def _quantize_navigation_ui_payload(
    *,
    lat_deg,
    lon_deg,
    altitude_km,
    heading_deg,
    tilt_deg,
    roll_deg,
    focal_length_mm,
):
    return {
        "lat_deg": _quantize_navigation_ui_value(lat_deg),
        "lon_deg": _quantize_navigation_ui_value(lon_deg),
        "altitude_km": _quantize_navigation_ui_value(altitude_km, minimum=0.0),
        "heading_deg": _quantize_navigation_ui_value(heading_deg),
        "tilt_deg": _quantize_navigation_ui_value(tilt_deg),
        "roll_deg": _quantize_navigation_ui_value(roll_deg),
        "focal_length_mm": _quantize_navigation_ui_value(focal_length_mm, minimum=1.0),
    }


def _get_coverage_map():
    global _COVERAGE_MAP
    if _COVERAGE_MAP is None:
        root_package = (__package__ or "").rsplit(".", 1)[0] if __package__ else ""
        module_name = f"{root_package}.coverage" if root_package else "coverage"
        module = importlib.import_module(module_name)
        _COVERAGE_MAP = getattr(module, "COVERAGE", {})
    return _COVERAGE_MAP


def _earth_radius_blender_units(earth_obj):
    if not earth_obj:
        return 1.0

    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0

    if stored_local_radius > 1e-9:
        world_scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
        return stored_local_radius * float(max_scale)

    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    if vertices:
        try:
            local_radius = max(v.co.length for v in vertices)
            if local_radius > 1e-9:
                world_scale = earth_obj.matrix_world.to_scale()
                max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
                return float(local_radius) * float(max_scale)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    scale = earth_obj.matrix_world.to_scale()
    return max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)


def _set_planetka_earth_radius_bu(scene, target_radius_bu):
    earth_obj = get_earth_object()
    if earth_obj is None or str(getattr(earth_obj, "type", "")) != "MESH":
        return False

    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    can_resize_mesh = bool(mesh_data is not None and vertices)

    target_radius = max(1e-6, float(target_radius_bu))

    changed = False
    try:
        sx, sy, sz = (float(v) for v in tuple(getattr(earth_obj, "scale", (1.0, 1.0, 1.0))))
    except (TypeError, ValueError, AttributeError):
        sx, sy, sz = 1.0, 1.0, 1.0
    if not math.isfinite(sx):
        sx = 1.0
    if not math.isfinite(sy):
        sy = 1.0
    if not math.isfinite(sz):
        sz = 1.0

    if can_resize_mesh:
        # Keep object scale neutral and encode size directly in mesh radius.
        if abs(sx - 1.0) > 1e-9 or abs(sy - 1.0) > 1e-9 or abs(sz - 1.0) > 1e-9:
            # Prevent accidental mesh collapse when an axis scale is (near) zero.
            bake_sx = sx if abs(sx) > 1e-6 else 1.0
            bake_sy = sy if abs(sy) > 1e-6 else 1.0
            bake_sz = sz if abs(sz) > 1e-6 else 1.0
            try:
                mesh_data.transform(Matrix.Diagonal((bake_sx, bake_sy, bake_sz, 1.0)))
                earth_obj.scale = (1.0, 1.0, 1.0)
                changed = True
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-OPS-036", "Failed normalizing Earth object scale while applying radius")

        try:
            current_local_radius = max(float(v.co.length) for v in vertices)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            current_local_radius = 0.0

        if current_local_radius <= 1e-9:
            current_local_radius = 1.0

        ratio = float(target_radius) / float(current_local_radius)
        if abs(ratio - 1.0) > 1e-9:
            try:
                mesh_data.transform(Matrix.Scale(float(ratio), 4))
                changed = True
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-OPS-037", "Failed scaling Earth mesh to requested radius")

        try:
            mesh_data.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass

    try:
        earth_obj["planetka_surface_local_radius"] = float(target_radius)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-038", "Failed storing Earth local radius metadata")

    try:
        props = getattr(scene, "planetka", None) if scene is not None else None
        preview_exists = bpy.data.objects.get("Planetka Preview Object") is not None
        if preview_exists or bool(getattr(props, "show_earth_preview", False)):
            ensure_preview_object(earth_obj)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-039", "Failed syncing preview radius after Earth radius change")

    # Keep Planetka camera in the same relative navigation shot immediately
    # after radius change (without requiring a manual UI nudge), regardless
    # of which scene camera is currently active.
    try:
        scene_for_camera = scene if isinstance(scene, bpy.types.Scene) else getattr(bpy.context, "scene", None)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        scene_for_camera = None
    if scene_for_camera is not None:
        _clear_radius_sync_notice(scene_for_camera)
        try:
            props = getattr(scene_for_camera, "planetka", None)
            planetka_camera = _find_planetka_scene_camera(scene_for_camera)
            if props is not None and planetka_camera is not None:
                _apply_navigation_shot(
                    bpy.context,
                    scene_for_camera,
                    props,
                    switch_viewport_to_camera=False,
                    sync_active_view_when_not_camera=False,
                    camera_override=planetka_camera,
                )
                mark_navigation_camera_control_signature(scene_for_camera)
            elif props is not None and planetka_camera is None:
                _set_radius_sync_notice(
                    scene_for_camera,
                    "Planetka Camera not found after Earth Radius change.",
                )
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _set_radius_sync_notice(
                scene_for_camera,
                "Earth Radius changed, but Planetka camera shot reapply failed.",
            )
            logger.warning(
                "Planetka: failed reapplying Planetka camera shot after Earth radius change.",
                exc_info=True,
            )
            _log_recoverable_once(
                "PKA-OPS-064",
                "Failed reapplying Planetka camera shot after Earth radius change",
            )

    return bool(changed)


def _meters_per_blender_unit(earth_radius_bu):
    safe_radius = max(float(earth_radius_bu), 1e-9)
    return REAL_EARTH_RADIUS_M / safe_radius


def _km_to_bu(km_value, earth_radius_bu):
    return (float(km_value) * 1000.0) / _meters_per_blender_unit(earth_radius_bu)


def _bu_to_km(distance_bu, earth_radius_bu):
    return (float(distance_bu) * _meters_per_blender_unit(earth_radius_bu)) / 1000.0


def _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad):
    radius = float(max(1e-9, earth_radius_bu))
    safe_altitude_bu = max(0.0, float(altitude_bu))
    tilt_cos = math.cos(float(tilt_rad))

    root_term = max(
        0.0,
        (radius * radius * tilt_cos * tilt_cos) + (2.0 * radius * safe_altitude_bu) + (safe_altitude_bu * safe_altitude_bu),
    )
    anchor_distance = (-radius * tilt_cos) + math.sqrt(root_term)
    return max(1e-6, float(anchor_distance))


def _lon_lat_normal_local(lon_deg, lat_deg):
    lon = math.radians(float(lon_deg))
    lat = math.radians(float(lat_deg))
    cos_lat = math.cos(lat)
    return Vector((
        cos_lat * math.cos(lon),
        cos_lat * math.sin(lon),
        math.sin(lat),
    ))


def _camera_projection_info(scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    camera_data = getattr(camera, "data", None)
    if camera_data is None:
        return None

    render = scene.render
    scale = float(render.resolution_percentage) / 100.0
    res_x = max(1.0, float(render.resolution_x) * scale)
    res_y = max(1.0, float(render.resolution_y) * scale)

    camera_type = str(getattr(camera_data, "type", "PERSP"))
    if camera_type == "ORTHO":
        aspect = max(1e-9, res_x / max(1.0, res_y))
        return {
            "camera_type": camera_type,
            "h_fov": math.radians(50.0),
            "v_fov": math.radians(35.0),
            "ortho_scale": float(getattr(camera_data, "ortho_scale", 1.0)),
            "res_x": res_x,
            "res_y": res_y,
            "aspect": aspect,
        }

    return {
        "camera_type": camera_type,
        "h_fov": float(getattr(camera_data, "angle_x", math.radians(50.0))),
        "v_fov": float(getattr(camera_data, "angle_y", math.radians(35.0))),
        "ortho_scale": float(getattr(camera_data, "ortho_scale", 1.0)),
        "res_x": res_x,
        "res_y": res_y,
        "aspect": max(1e-9, res_x / max(1.0, res_y)),
    }


def _find_active_view3d_context_details():
    context = bpy.context
    window = getattr(context, "window", None)
    screen = getattr(window, "screen", None) if window else None
    area = getattr(context, "area", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(context, "region_data", None)
    region = getattr(context, "region", None)
    if (
        area is not None
        and area.type == 'VIEW_3D'
        and space is not None
        and space.type == 'VIEW_3D'
        and rv3d is not None
    ):
        if region is None or getattr(region, "type", "") != 'WINDOW':
            region = next((candidate for candidate in area.regions if candidate.type == 'WINDOW'), None)
        return {
            "window": window,
            "screen": screen,
            "area": area,
            "space": space,
            "region": region,
            "rv3d": rv3d,
        }

    wm = getattr(context, "window_manager", None)
    if not wm:
        return None
    for candidate_window in wm.windows:
        candidate_screen = getattr(candidate_window, "screen", None)
        if not candidate_screen:
            continue
        for candidate_area in candidate_screen.areas:
            if candidate_area.type != 'VIEW_3D':
                continue
            candidate_space = getattr(candidate_area.spaces, "active", None)
            if not candidate_space or candidate_space.type != 'VIEW_3D':
                continue
            candidate_rv3d = getattr(candidate_space, "region_3d", None)
            if candidate_rv3d is None:
                continue
            candidate_region = next(
                (candidate for candidate in candidate_area.regions if candidate.type == 'WINDOW'),
                None,
            )
            return {
                "window": candidate_window,
                "screen": candidate_screen,
                "area": candidate_area,
                "space": candidate_space,
                "region": candidate_region,
                "rv3d": candidate_rv3d,
            }
    return None


def _find_active_view3d_context():
    details = _find_active_view3d_context_details()
    if details is None:
        return None
    return details["area"], details["space"], details["rv3d"]


def _switch_viewport_to_camera_view(context, scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return False

    switched = False
    area = getattr(context, "area", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(context, "region_data", None)
    if (
        area is not None
        and area.type == 'VIEW_3D'
        and space is not None
        and space.type == 'VIEW_3D'
        and rv3d is not None
    ):
        try:
            if scene.camera is not camera:
                scene.camera = camera
            rv3d.view_perspective = 'CAMERA'
            switched = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            _log_recoverable_once("PKA-OPS-016", "Failed switching active viewport to camera perspective")

    wm = getattr(context, "window_manager", None)
    if wm:
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if not screen:
                continue
            for candidate_area in screen.areas:
                if candidate_area.type != 'VIEW_3D':
                    continue
                candidate_space = getattr(candidate_area.spaces, "active", None)
                candidate_rv3d = getattr(candidate_space, "region_3d", None) if candidate_space else None
                if candidate_rv3d is None:
                    continue
                try:
                    if scene.camera is not camera:
                        scene.camera = camera
                    candidate_rv3d.view_perspective = 'CAMERA'
                    switched = True
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                    continue
    return switched


def _sync_active_view_to_scene_camera(scene):
    if scene is None:
        return False
    camera = getattr(scene, "camera", None)
    if camera is None:
        return False

    details = _find_active_view3d_context_details()
    if details is None:
        return False
    window = details.get("window")
    screen = details.get("screen")
    area = details.get("area")
    region = details.get("region")
    space = details.get("space")
    rv3d = details.get("rv3d")
    if window is None or screen is None or area is None or region is None or space is None or rv3d is None:
        return False

    original_perspective = str(getattr(rv3d, "view_perspective", "") or "")
    if original_perspective == "CAMERA":
        return False

    try:
        if getattr(scene, "camera", None) is not camera:
            scene.camera = camera
        with bpy.context.temp_override(
            window=window,
            screen=screen,
            area=area,
            region=region,
            space_data=space,
            region_data=rv3d,
            scene=scene,
        ):
            result = bpy.ops.view3d.view_camera()
        if "FINISHED" not in set(result):
            return False
        if original_perspective in {"PERSP", "ORTHO"}:
            rv3d.view_perspective = original_perspective
        else:
            rv3d.view_perspective = "PERSP"
        return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-061", "Failed syncing active viewport to camera pose")
        return False


def _ray_sphere_hit_nearest(origin, direction, radius):
    a = float(direction.dot(direction))
    if a <= 1e-12:
        return None
    b = 2.0 * float(origin.dot(direction))
    c = float(origin.dot(origin)) - float(radius) * float(radius)
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    sqrt_disc = math.sqrt(disc)
    inv = 0.5 / a
    t0 = (-b - sqrt_disc) * inv
    t1 = (-b + sqrt_disc) * inv
    for t in (t0, t1):
        if t > 1e-6:
            return origin + direction * t
    return None


def _compute_current_view_navigation_values(scene):
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None

    active_view = _find_active_view3d_context()
    if active_view is not None:
        _area, _space, rv3d = active_view
        view_matrix = rv3d.view_matrix.inverted()
        cam_pos_world = view_matrix.translation.copy()
        cam_forward_world = (-view_matrix.col[2].xyz).normalized()
    else:
        camera = getattr(scene, "camera", None)
        if camera is None:
            return None
        matrix = camera.matrix_world
        cam_pos_world = matrix.translation.copy()
        cam_forward_world = (-matrix.col[2].xyz).normalized()

    center, rotation, _scale = earth_obj.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        return None
    cam_forward_local.normalize()

    earth_radius = _earth_radius_blender_units(earth_obj)
    hit_local = _ray_sphere_hit_nearest(cam_pos_local, cam_forward_local, earth_radius)
    if hit_local is None:
        return None

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    altitude_bu = max(0.0, float(cam_pos_local.length) - float(earth_radius))
    altitude_km = _bu_to_km(altitude_bu, earth_radius)
    return lat, lon, altitude_km


def _compute_scene_camera_navigation_values(scene):
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    cam_matrix = camera.matrix_world
    cam_pos_world = cam_matrix.translation.copy()
    cam_forward_world = (-cam_matrix.col[2].xyz).normalized()

    center, rotation, _scale = earth_obj.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        return None
    cam_forward_local.normalize()

    earth_radius = _earth_radius_blender_units(earth_obj)
    hit_local = _ray_sphere_hit_nearest(cam_pos_local, cam_forward_local, earth_radius)
    if hit_local is None:
        cam_len = float(cam_pos_local.length)
        if cam_len <= 1e-9:
            return None
        hit_local = (cam_pos_local / cam_len) * float(earth_radius)

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    altitude_bu = max(0.0, float(cam_pos_local.length) - float(earth_radius))
    altitude_km = _bu_to_km(altitude_bu, earth_radius)
    return lat, lon, altitude_km


def _scene_camera_altitude_bu(scene):
    """Return camera altitude above Earth surface in Blender units (can be negative)."""
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or getattr(camera, "type", None) != "CAMERA":
        return None
    try:
        center = earth_obj.matrix_world.translation.copy()
        cam_pos = camera.matrix_world.translation.copy()
        radius = float(_earth_radius_blender_units(earth_obj))
        return float((cam_pos - center).length) - radius
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _is_scene_camera_below_surface(scene, tolerance_bu=1e-6):
    altitude_bu = _scene_camera_altitude_bu(scene)
    if altitude_bu is None:
        return False
    return float(altitude_bu) <= float(tolerance_bu)


def _tile_xy_for_lon_lat(lon_deg, lat_deg, z):
    lon_shift = (float(lon_deg) + 180.0) % 360.0
    lat_shift = max(0.0, min(179.999999, float(lat_deg) + 90.0))
    zf = float(z)
    x = int(lon_shift // zf) * int(zf)
    y = int(lat_shift // zf) * int(zf)
    return x % 360, max(0, min(179, y))


def _best_available_d_for_tile(base_path, x, y, z):
    normalized = _normalize_texture_source_path(base_path)
    if not normalized and not is_remote_source_configured(base_path):
        return None

    d_candidates = sorted(set(NAV_D_LEVELS_BY_Z.get(int(z), [int(z)])))
    for d in d_candidates:
        d_code = 0 if int(d) == 1440 else int(d)
        file_name = f"S2_x{x:03d}_y{y:03d}_z{int(z):03d}_d{int(d_code):03d}.exr"
        try:
            if texture_file_exists(normalized or base_path, "S2", file_name):
                return int(d)
        except RuntimeError:
            logger.debug("Planetka: failed checking available S2 detail level for navigation", exc_info=True)
            return None
    return None


def _finest_available_d_for_location(lon_deg, lat_deg, base_path):
    coverage = _get_coverage_map()
    for z in sorted(NAV_D_LEVELS_BY_Z.keys()):
        tiles = coverage.get(int(z), set())
        if not tiles:
            continue
        x, y = _tile_xy_for_lon_lat(lon_deg, lat_deg, z)
        if (x, y) not in tiles:
            continue
        exact_d = _best_available_d_for_tile(base_path, x, y, z)
        if exact_d is not None:
            return max(1, int(exact_d))
        return max(1, int(z))
    return 360


def _max_proximity_altitude_km(scene, earth_obj, earth_radius_bu, lon_deg, lat_deg):
    projection = _camera_projection_info(scene)
    if projection is None:
        return None, "Scene camera is required for navigation."

    if projection["camera_type"] == "ORTHO":
        center = earth_obj.matrix_world.translation
        cam_loc = scene.camera.matrix_world.translation
        altitude_bu = max(0.0, float((cam_loc - center).length) - float(earth_radius_bu))
        return _bu_to_km(altitude_bu, earth_radius_bu), (
            "Orthographic camera detected: altitude does not control detail; keeping current altitude."
        )

    prefs = get_prefs()
    base_path = getattr(prefs, "texture_base_path", "") if prefs else ""
    best_d = _finest_available_d_for_location(lon_deg, lat_deg, base_path)

    required_mpp_limit = (
        float(best_d)
        * DATASET_MPP_BASE_D1
        / max(1e-6, float(MAX_PROXIMITY_TARGET_SAFETY_RATIO))
    )
    px_angle = max(
        float(projection["h_fov"]) / max(1.0, float(projection["res_x"])),
        float(projection["v_fov"]) / max(1.0, float(projection["res_y"])),
    )
    px_angle = max(1e-9, float(px_angle))

    meters_per_bu = _meters_per_blender_unit(earth_radius_bu)
    effective_distance_bu = (required_mpp_limit / meters_per_bu) / (2.0 * math.tan(px_angle * 0.5))
    terrain_offset_bu = MAX_TERRAIN_HEIGHT_M / meters_per_bu
    altitude_bu = max(0.0, effective_distance_bu + terrain_offset_bu)
    return _bu_to_km(altitude_bu, earth_radius_bu), None


def _full_globe_altitude_km(scene, earth_radius_bu):
    projection = _camera_projection_info(scene)
    if projection is None:
        return None

    if projection["camera_type"] == "ORTHO":
        return None

    half_fov = min(float(projection["h_fov"]), float(projection["v_fov"])) * 0.5
    half_fov = max(1e-6, half_fov)
    center_distance_bu = (float(earth_radius_bu) * FULL_GLOBE_EXTRA_MARGIN) / math.sin(half_fov)
    altitude_bu = max(0.0, center_distance_bu - float(earth_radius_bu))
    return _bu_to_km(altitude_bu, earth_radius_bu)


def _ensure_ortho_full_globe_if_needed(scene, earth_radius_bu):
    camera = getattr(scene, "camera", None) if scene else None
    camera_data = getattr(camera, "data", None) if camera else None
    if not camera_data or str(getattr(camera_data, "type", "")) != "ORTHO":
        return False

    projection = _camera_projection_info(scene)
    if projection is None:
        return False

    aspect = max(1e-9, float(projection["aspect"]))
    margin_radius = float(earth_radius_bu) * FULL_GLOBE_EXTRA_MARGIN
    if aspect >= 1.0:
        needed_scale = 2.0 * margin_radius * aspect
    else:
        needed_scale = 2.0 * margin_radius / aspect

    try:
        if float(getattr(camera_data, "ortho_scale", 1.0)) < float(needed_scale):
            camera_data.ortho_scale = float(needed_scale)
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return False


def _navigate_camera_internal(scene, lon_deg, lat_deg, altitude_km, look_at_center=False, camera_override=None):
    camera = camera_override if camera_override is not None else (getattr(scene, "camera", None) if scene else None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    earth_center, earth_rot, _scale = earth_obj.matrix_world.decompose()
    earth_radius_bu = _earth_radius_blender_units(earth_obj)

    altitude_bu = _km_to_bu(max(0.0, float(altitude_km)), earth_radius_bu)
    normal_local = _lon_lat_normal_local(lon_deg, lat_deg)
    if normal_local.length_squared <= 1e-12:
        normal_local = Vector((1.0, 0.0, 0.0))
    normal_local.normalize()
    normal_world = (earth_rot @ normal_local).normalized()

    if look_at_center:
        target_point = earth_center.copy()
    else:
        target_point = earth_center + normal_world * float(earth_radius_bu)
    camera_position = earth_center + normal_world * (float(earth_radius_bu) + altitude_bu)
    look_direction = (target_point - camera_position)
    if look_direction.length_squared <= 1e-12:
        look_direction = -normal_world
    look_direction.normalize()

    try:
        _loc, _rot, cam_scale = camera.matrix_world.decompose()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        cam_scale = Vector((1.0, 1.0, 1.0))

    cam_rotation = look_direction.to_track_quat('-Z', 'Y')
    camera.matrix_world = Matrix.LocRotScale(camera_position, cam_rotation, cam_scale)
    return earth_obj, earth_radius_bu


def _anchor_frame_world(earth_obj, lon_deg, lat_deg):
    earth_center, earth_rot, _scale = earth_obj.matrix_world.decompose()
    earth_radius_bu = _earth_radius_blender_units(earth_obj)
    lon_rad = math.radians(float(lon_deg))
    up_local = _lon_lat_normal_local(lon_deg, lat_deg)
    if up_local.length_squared <= 1e-12:
        up_local = Vector((1.0, 0.0, 0.0))
    up_local.normalize()

    east_local = Vector((-math.sin(lon_rad), math.cos(lon_rad), 0.0))
    if east_local.length_squared <= 1e-12:
        east_local = Vector((0.0, 1.0, 0.0))
    east_local.normalize()

    north_local = up_local.cross(east_local)
    if north_local.length_squared <= 1e-12:
        north_local = Vector((0.0, 0.0, 1.0))
    north_local.normalize()

    up_world = (earth_rot @ up_local).normalized()
    east_world = (earth_rot @ east_local).normalized()
    north_world = (earth_rot @ north_local).normalized()
    anchor_world = earth_center + up_world * float(earth_radius_bu)
    return anchor_world, east_world, north_world, up_world, earth_radius_bu


def _look_rotation_quaternion(camera_location, target_point, up_hint):
    forward = (target_point - camera_location)
    if forward.length_squared <= 1e-12:
        raise RuntimeError("Camera is at the target location; cannot orient.")
    forward.normalize()

    if up_hint is None or up_hint.length_squared <= 1e-12:
        up_hint = Vector((0.0, 0.0, 1.0))
    else:
        up_hint = up_hint.normalized()

    right = forward.cross(up_hint)
    if right.length_squared <= 1e-12:
        fallback = Vector((0.0, 1.0, 0.0))
        right = forward.cross(fallback)
        if right.length_squared <= 1e-12:
            fallback = Vector((1.0, 0.0, 0.0))
            right = forward.cross(fallback)
    right.normalize()
    true_up = right.cross(forward)
    if true_up.length_squared <= 1e-12:
        true_up = Vector((0.0, 0.0, 1.0))
    true_up.normalize()

    rotation_matrix = Matrix((right, true_up, -forward)).transposed()
    return rotation_matrix.to_quaternion(), forward


def _ensure_shot_anchor_object(scene):
    anchor_obj = bpy.data.objects.get(SHOT_ANCHOR_OBJECT_NAME)
    if anchor_obj is not None and getattr(anchor_obj, "type", None) != 'EMPTY':
        try:
            bpy.data.objects.remove(anchor_obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            anchor_obj = None
    if anchor_obj is None:
        anchor_obj = bpy.data.objects.new(SHOT_ANCHOR_OBJECT_NAME, None)
        try:
            anchor_obj.empty_display_type = 'ARROWS'
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            anchor_obj.empty_display_size = 0.1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    target_collection = ensure_planetka_temp_collection() or getattr(scene, "collection", None)
    if target_collection is not None:
        for collection in tuple(getattr(anchor_obj, "users_collection", ())):
            if collection is target_collection:
                continue
            try:
                collection.objects.unlink(anchor_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-OPS-005", "Failed unlinking shot anchor from non-target collection")
        try:
            if anchor_obj.name not in target_collection.objects:
                target_collection.objects.link(anchor_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-006", "Failed linking shot anchor to target collection")
    try:
        anchor_obj.hide_viewport = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-007", "Failed hiding shot anchor in viewport")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-008", "Failed hiding shot anchor in viewport")
    try:
        anchor_obj.hide_set(True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-009", "Failed hide_set on shot anchor")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-010", "Failed hide_set on shot anchor")
    try:
        root = ensure_planetka_root(scene)
        if root is not None and getattr(anchor_obj, "parent", None) is not root:
            anchor_obj.parent = root
            anchor_obj.matrix_parent_inverse = root.matrix_world.inverted()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-036", "Failed parenting shot anchor to Planetka Root")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-037", "Failed parenting shot anchor to Planetka Root")
    return anchor_obj


def _hide_shot_anchor_in_viewport():
    anchor_obj = bpy.data.objects.get(SHOT_ANCHOR_OBJECT_NAME)
    if anchor_obj is None:
        return
    try:
        anchor_obj.hide_viewport = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-011", "Failed hiding existing shot anchor in viewport")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-012", "Failed hiding existing shot anchor in viewport")
    try:
        anchor_obj.hide_set(True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-013", "Failed hide_set on existing shot anchor")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-014", "Failed hide_set on existing shot anchor")


def _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world):
    anchor_obj = _ensure_shot_anchor_object(scene)
    if anchor_obj is None:
        return
    frame_rotation = Matrix((east_world, north_world, up_world)).transposed().to_quaternion()
    try:
        anchor_obj.matrix_world = Matrix.LocRotScale(anchor_world, frame_rotation, Vector((1.0, 1.0, 1.0)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-015", "Failed updating shot anchor transform")


def _signed_angle_around_axis(from_vec, to_vec, axis):
    if (
        from_vec is None
        or to_vec is None
        or axis is None
        or from_vec.length_squared <= 1e-12
        or to_vec.length_squared <= 1e-12
        or axis.length_squared <= 1e-12
    ):
        return 0.0
    from_n = from_vec.normalized()
    to_n = to_vec.normalized()
    axis_n = axis.normalized()
    cross = from_n.cross(to_n)
    sin_v = axis_n.dot(cross)
    cos_v = max(-1.0, min(1.0, float(from_n.dot(to_n))))
    return math.atan2(float(sin_v), float(cos_v))


def _camera_to_current_view(scene):
    context_details = _find_active_view3d_context_details()
    if context_details is None:
        raise RuntimeError("No active 3D viewport found.")
    window = context_details.get("window")
    screen = context_details.get("screen")
    area = context_details.get("area")
    region = context_details.get("region")
    space = context_details.get("space")
    rv3d = context_details.get("rv3d")

    if window is None or screen is None or area is None or region is None or space is None or rv3d is None:
        raise RuntimeError("Current viewport context is incomplete.")

    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    if str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
        return False

    try:
        with bpy.context.temp_override(
            window=window,
            screen=screen,
            area=area,
            region=region,
            space_data=space,
            region_data=rv3d,
            scene=scene,
        ):
            result = bpy.ops.view3d.camera_to_view()
    except RuntimeError as exc:
        message = str(exc)
        if "context is incorrect" in message and str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
            return False
        raise

    if "FINISHED" in result:
        return True
    if str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
        return False
    raise RuntimeError("Failed to move camera to current view.")


def _derive_navigation_shot_from_camera(scene, lon_deg, lat_deg):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    anchor_world, east_world, north_world, up_world, earth_radius_bu = _anchor_frame_world(
        earth_obj,
        lon_deg,
        lat_deg,
    )
    earth_center = earth_obj.matrix_world.translation.copy()

    camera_matrix = camera.matrix_world
    camera_position = camera_matrix.translation.copy()
    camera_forward = (-camera_matrix.col[2].xyz).normalized()
    camera_up = camera_matrix.col[1].xyz.normalized()

    anchor_to_camera = camera_position - anchor_world
    anchor_distance = max(1e-9, float(anchor_to_camera.length))
    anchor_to_camera_dir = anchor_to_camera / anchor_distance

    up_component = max(-1.0, min(1.0, float(anchor_to_camera_dir.dot(up_world))))
    horizontal_vec = anchor_to_camera_dir - (up_world * up_component)
    horizontal_len = float(horizontal_vec.length)

    if horizontal_len <= 1e-9:
        heading_rad = 0.0
    else:
        horizontal_dir = horizontal_vec / horizontal_len
        look_horizontal_dir = -horizontal_dir
        heading_rad = math.atan2(
            float(look_horizontal_dir.dot(east_world)),
            float(look_horizontal_dir.dot(north_world)),
        )
    look_tangent = (north_world * math.cos(heading_rad)) + (east_world * math.sin(heading_rad))
    if look_tangent.length_squared <= 1e-12:
        look_tangent = north_world.copy()
    look_tangent.normalize()
    position_tangent = -look_tangent

    tilt_abs_rad = math.atan2(horizontal_len, up_component)
    sin_component = float(anchor_to_camera_dir.dot(position_tangent))
    if abs(sin_component) <= 1e-9:
        tilt_rad = tilt_abs_rad
    else:
        tilt_rad = math.copysign(tilt_abs_rad, sin_component)

    center_to_camera = camera_position - earth_center
    center_to_camera_len = max(1e-9, float(center_to_camera.length))
    altitude_bu = max(0.0, center_to_camera_len - float(earth_radius_bu))

    base_rotation, _forward = _look_rotation_quaternion(camera_position, anchor_world, look_tangent)
    base_up = (base_rotation @ Vector((0.0, 1.0, 0.0))).normalized()
    roll_rad = _signed_angle_around_axis(base_up, camera_up, camera_forward)

    return {
        "altitude_km": _bu_to_km(altitude_bu, earth_radius_bu),
        "azimuth_deg": math.degrees(heading_rad),
        "tilt_deg": math.degrees(tilt_rad),
        "roll_deg": math.degrees(roll_rad),
    }


def _apply_navigation_shot(
    context,
    scene,
    props,
    switch_viewport_to_camera=True,
    sync_active_view_when_not_camera=False,
    camera_override=None,
):
    camera = camera_override if camera_override is not None else getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
    lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
    altitude_km = max(0.0, float(getattr(props, "nav_altitude_km", 0.0)))
    heading_deg = float(getattr(props, "nav_azimuth_deg", 0.0))
    tilt_deg = float(getattr(props, "nav_tilt_deg", 0.0))
    roll_deg = float(getattr(props, "nav_roll_deg", 0.0))

    full_globe_tilt_lock_enabled, full_globe_tilt_lock_value = _read_full_globe_tilt_lock(scene)
    if full_globe_tilt_lock_enabled:
        # Full Globe must keep Earth centered and target stable until user explicitly
        # changes Tilt. Ignore stored tilt value while lock is active.
        if (
            full_globe_tilt_lock_value is None
            or abs(float(tilt_deg) - float(full_globe_tilt_lock_value)) <= NAV_CHANGE_EPS
        ):
            earth_obj, earth_radius_bu = _navigate_camera_internal(
                scene,
                lon_deg,
                lat_deg,
                altitude_km,
                look_at_center=True,
                camera_override=camera,
            )
            anchor_world, east_world, north_world, up_world, _radius = _anchor_frame_world(
                earth_obj,
                lon_deg,
                lat_deg,
            )
            _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)
            _ensure_close_clip_limits(scene, min_clip=0.001)
            if bool(switch_viewport_to_camera):
                _switch_viewport_to_camera_view(context, scene)
            elif bool(sync_active_view_when_not_camera):
                _sync_active_view_to_scene_camera(scene)
            _store_last_navigation_values(
                scene,
                lon_deg=lon_deg,
                lat_deg=lat_deg,
                altitude_km=float(altitude_km),
                heading_deg=heading_deg,
                tilt_deg=tilt_deg,
                roll_deg=roll_deg,
            )
            return earth_obj, earth_radius_bu
        _clear_full_globe_tilt_lock(scene)

    anchor_world, east_world, north_world, up_world, earth_radius_bu = _anchor_frame_world(
        earth_obj, lon_deg, lat_deg
    )
    earth_center = earth_obj.matrix_world.translation.copy()
    _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)

    altitude_bu = _km_to_bu(altitude_km, earth_radius_bu)
    heading_rad = math.radians(float(heading_deg))
    tilt_rad = math.radians(float(tilt_deg))
    roll_rad = math.radians(float(roll_deg))

    look_tangent = (north_world * math.cos(heading_rad)) + (east_world * math.sin(heading_rad))
    if look_tangent.length_squared <= 1e-12:
        look_tangent = north_world.copy()
    look_tangent.normalize()

    position_tangent = -look_tangent
    offset_direction = (up_world * math.cos(tilt_rad)) + (position_tangent * math.sin(tilt_rad))
    if offset_direction.length_squared <= 1e-12:
        offset_direction = up_world.copy()
    offset_direction.normalize()

    current_camera_position = camera.matrix_world.translation.copy()
    current_center_distance = max(1e-9, float((current_camera_position - earth_center).length))
    current_altitude_bu = max(0.0, current_center_distance - float(earth_radius_bu))
    current_altitude_km = _bu_to_km(current_altitude_bu, earth_radius_bu)

    last_values = _read_last_navigation_values(scene)
    lon_changed = False
    lat_changed = False
    altitude_prop_changed = False
    heading_changed = False
    tilt_changed = False
    roll_changed = False
    if last_values is not None:
        lon_changed = abs(float(lon_deg) - float(last_values["lon"])) > NAV_CHANGE_EPS
        lat_changed = abs(float(lat_deg) - float(last_values["lat"])) > NAV_CHANGE_EPS
        altitude_prop_changed = abs(float(altitude_km) - float(last_values["alt"])) > NAV_CHANGE_EPS
        heading_changed = abs(float(heading_deg) - float(last_values["heading"])) > NAV_CHANGE_EPS
        tilt_changed = abs(float(tilt_deg) - float(last_values["tilt"])) > NAV_CHANGE_EPS
        roll_changed = abs(float(roll_deg) - float(last_values["roll"])) > NAV_CHANGE_EPS
    else:
        altitude_prop_changed = abs(float(altitude_km) - float(current_altitude_km)) > 1e-4

    tilt_only_change = (
        tilt_changed
        and not lon_changed
        and not lat_changed
        and not altitude_prop_changed
        and not heading_changed
        and not roll_changed
    )

    if tilt_only_change:
        anchor_distance = float((current_camera_position - anchor_world).length)
        if anchor_distance <= 1e-9:
            anchor_distance = _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad)
    else:
        anchor_distance = _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad)

    camera_position = anchor_world + (offset_direction * anchor_distance)
    # Keep the UI altitude value under direct user control while dragging.
    # Writing nav_altitude_km back from derived camera math here can interrupt
    # Blender's live numeric drag interaction.

    look_target = anchor_world.copy()
    if (look_target - camera_position).length_squared <= 1e-12:
        look_target = camera_position - up_world

    _loc, _existing_rotation, camera_scale = camera.matrix_world.decompose()
    base_rotation, forward = _look_rotation_quaternion(camera_position, look_target, look_tangent)
    if abs(roll_rad) > 1e-9:
        roll_quaternion = Quaternion(forward, roll_rad)
        final_rotation = roll_quaternion @ base_rotation
    else:
        final_rotation = base_rotation

    camera.matrix_world = Matrix.LocRotScale(camera_position, final_rotation, camera_scale)
    _ensure_close_clip_limits(scene, min_clip=0.001)
    if bool(switch_viewport_to_camera):
        _switch_viewport_to_camera_view(context, scene)
    elif bool(sync_active_view_when_not_camera):
        _sync_active_view_to_scene_camera(scene)
    _store_last_navigation_values(
        scene,
        lon_deg=lon_deg,
        lat_deg=lat_deg,
        altitude_km=float(altitude_km),
        heading_deg=heading_deg,
        tilt_deg=tilt_deg,
        roll_deg=roll_deg,
    )
    return earth_obj, earth_radius_bu


def _populate_navigation_from_scene_camera(scene, props):
    if scene is None or props is None:
        return False
    # When camera is inside/at surface (common right after large Earth radius changes),
    # deriving heading/roll from camera matrix is unstable and can overwrite user controls.
    if _is_scene_camera_below_surface(scene):
        return False
    nav_values = _compute_scene_camera_navigation_values(scene)
    if nav_values is None:
        return False
    lat, lon, _alt_km = nav_values
    derived = _derive_navigation_shot_from_camera(scene, lon, lat)
    try:
        camera = getattr(scene, "camera", None)
        camera_data = getattr(camera, "data", None) if camera is not None else None
        quantized = _quantize_navigation_ui_payload(
            lat_deg=float(lat),
            lon_deg=float(lon),
            altitude_km=float(derived.get("altitude_km", 0.0)),
            heading_deg=float(derived.get("azimuth_deg", 0.0)),
            tilt_deg=float(derived.get("tilt_deg", 0.0)),
            roll_deg=float(derived.get("roll_deg", 0.0)),
            focal_length_mm=float(getattr(camera_data, "lens", 50.0)) if camera_data is not None else float(getattr(props, "nav_focal_length_mm", 50.0)),
        )
        props.nav_latitude_deg = float(quantized["lat_deg"])
        props.nav_longitude_deg = float(quantized["lon_deg"])
        props.nav_altitude_km = float(quantized["altitude_km"])
        props.nav_azimuth_deg = float(quantized["heading_deg"])
        props.nav_tilt_deg = float(quantized["tilt_deg"])
        props.nav_roll_deg = float(quantized["roll_deg"])
        if camera_data is not None:
            props.nav_focal_length_mm = float(quantized["focal_length_mm"])
        _store_last_navigation_values(
            scene,
            lon_deg=float(props.nav_longitude_deg),
            lat_deg=float(props.nav_latitude_deg),
            altitude_km=float(props.nav_altitude_km),
            heading_deg=float(props.nav_azimuth_deg),
            tilt_deg=float(props.nav_tilt_deg),
            roll_deg=float(props.nav_roll_deg),
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return True
