import logging
import importlib
import math
import time

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object
from .diagnostics import write_realtime_view_diagnostics
from .scene_schema import migrate_scene_schema


logger = logging.getLogger(__name__)

ADD_EARTH_BUTTON_SCALE_X = 1.0
ADD_EARTH_BUTTON_SCALE_Y = 1.2
REFRESH_BUTTON_SCALE_X = 1.2
REFRESH_BUTTON_SCALE_Y = 1.6
REFRESH_BUTTON_ALERT = False

_IDPROP_SYNCING = False
_LOGGING_SYNCING = False
_FAKE_ATMOSPHERE_PROP_SYNCING = False

_SYNC_IDPROP_MAP = {
    "viewport_opt_suspend_subdivision": "planetka_viewport_opt_suspend_subdivision",
    "viewport_opt_subdivision_restore_delay_sec": "planetka_viewport_opt_subdivision_restore_delay_sec",
    "viewport_opt_active_view_coarse_textures": "planetka_viewport_opt_active_view_coarse_textures",
    "show_earth_preview": "planetka_show_earth_preview",
    "auto_resolve": "planetka_auto_resolve",
    "auto_resolve_idle_sec": "planetka_auto_resolve_idle_sec",
    "nav_longitude_deg": "planetka_nav_longitude_deg",
    "nav_latitude_deg": "planetka_nav_latitude_deg",
    "nav_altitude_km": "planetka_nav_altitude_km",
    "nav_azimuth_deg": "planetka_nav_azimuth_deg",
    "nav_tilt_deg": "planetka_nav_tilt_deg",
    "nav_roll_deg": "planetka_nav_roll_deg",
    "nav_city_search": "planetka_nav_city_search",
    "nav_saved_location_name": "planetka_nav_saved_location_name",
    "nav_saved_location_id": "planetka_nav_saved_location_id",
    "sunlight_longitude_deg": "planetka_sunlight_longitude_deg",
    "sunlight_seasonal_tilt_deg": "planetka_sunlight_seasonal_tilt_deg",
    "enable_fake_atmosphere": "planetka_enable_fake_atmosphere",
    "atmosphere_mode": "planetka_atmosphere_mode",
    "fake_atmosphere_density": "planetka_fake_atmosphere_density",
    "fake_atmosphere_height_km": "planetka_fake_atmosphere_height_km",
    "fake_atmosphere_falloff_exp": "planetka_fake_atmosphere_falloff_exp",
    "fake_atmosphere_color": "planetka_fake_atmosphere_color",
    "anim_camera_preset": "planetka_anim_camera_preset",
    "anim_frame_start": "planetka_anim_frame_start",
    "anim_frame_end": "planetka_anim_frame_end",
    "anim_camera_strength": "planetka_anim_camera_strength",
    "anim_motion_curve": "planetka_anim_motion_curve",
    "anim_start_altitude_km": "planetka_anim_start_altitude_km",
    "anim_end_altitude_km": "planetka_anim_end_altitude_km",
    "anim_orbit_degrees": "planetka_anim_orbit_degrees",
    "anim_circle_direction": "planetka_anim_circle_direction",
    "anim_flyby_degrees": "planetka_anim_flyby_degrees",
    "anim_zoom_rotate_degrees": "planetka_anim_zoom_rotate_degrees",
    "anim_prepare_max_segments": "planetka_anim_prepare_max_segments",
    "anim_prepare_max_textures_mb": "planetka_anim_prepare_max_textures_mb",
    "anim_ab_a_location": "planetka_anim_ab_a_location",
    "anim_ab_a_rotation": "planetka_anim_ab_a_rotation",
    "anim_ab_a_valid": "planetka_anim_ab_a_valid",
    "anim_ab_b_location": "planetka_anim_ab_b_location",
    "anim_ab_b_rotation": "planetka_anim_ab_b_rotation",
    "anim_ab_b_valid": "planetka_anim_ab_b_valid",
    "texture_quality_mode": "planetka_texture_quality_mode",
    "resolution_bias": "planetka_resolution_bias",
    "lock_resolve_during_animation": "planetka_lock_resolve_during_animation",
    "debug_logging": "planetka_debug_logging",
}
SURFACE_COLLECTION_NAME = "Planetka - Earth Surface Collection"
_MESH_UTILS_MODULE = None
_SHADER_UTILS_MODULE = None
_LEGACY_SCENE_IDPROPS = (
    "planetka_view_elevation",
    "planetka_sampling_grid_density",
    "planetka_mesh_expansion",
    "planetka_auto_resolve_interval_sec",
    "planetka_resolve_scope",
    "planetka_nav_look_offset_km",
    "planetka_nav_keep_facing_anchor",
    "planetka_nav_azimuth_step_deg",
    "planetka_nav_tilt_step_deg",
    "planetka_nav_altitude_step_km",
    "planetka_nav_look_offset_horizontal_km",
    "planetka_nav_look_offset_vertical_km",
    "planetka_anim_prepare_frame_step",
    "planetka_anim_flyby_look_mode",
)
_TILE_UTILS_MODULE = None

AUTO_RESOLVE_TIMER_INTERVAL_SEC = 1.0 / 3.0
AUTO_RESOLVE_TIMER_BUDGET_MS = 20.0
AUTO_RESOLVE_BUDGET_SKIP_LOG_COOLDOWN_SEC = 5.0
AUTO_RESOLVE_MIN_INTERVAL_SEC_DEFAULT = 1.0
AUTO_RESOLVE_IDLE_SEC_DEFAULT = 0.6

_AUTO_RESOLVE_TIMER_RUNNING = False
_AUTO_RESOLVE_IN_FLIGHT = False
_RENDER_JOB_ACTIVE = False
_AUTO_RESOLVE_LAST_CAMERA_SIGNATURE = {}
_AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE = {}
_AUTO_RESOLVE_LAST_CHANGE_TIME = {}
_AUTO_RESOLVE_LAST_RESOLVE_TIME = {}
_AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE = {}
_AUTO_RESOLVE_PENDING_OUTPUT_CHANGE = {}
_VIEWPORT_OPT_LAST_SIGNATURE = {}
_SUNLIGHT_LAST_SIGNATURE = {}
_SUNLIGHT_OBJECT_NAME_CACHE = {}
_VIEWPORT_SCOPE_LAST = {}
_VIEWPORT_SCOPE_LAST_RESOLVE_TIME = {}
_LAST_REALTIME_TELEMETRY = {}
_TIMELINE_LAST_SIGNATURE = {}
_AUTO_RESOLVE_LAST_BUDGET_SKIP_LOG_AT = 0.0
_COVERAGE_MAP = None
_REAL_EARTH_RADIUS_M = 6371000.0
_MAX_TERRAIN_HEIGHT_M = 9000.0
_DATASET_MPP_BASE_D1 = 10.0
_LIVE_SAFETY_CAUTION_RATIO = 1.15
_LIVE_FALLBACK_MPP_M = 3600.0
_LIVE_Z_LEVELS = (1, 2, 4, 8, 15, 30, 60, 90, 180, 360)
_NAVIGATION_SHOT_UPDATE_PENDING = False
_NAVIGATION_SHOT_UPDATE_REENTRANT = False
_NAVIGATION_ADAPTIVE_SUSPENDED = None
_NAVIGATION_ADAPTIVE_LAST_TOUCH = 0.0
_NAVIGATION_ADAPTIVE_TIMER_RUNNING = False
_NAVIGATION_ADAPTIVE_IDLE_SEC = 0.5
_NAVIGATION_SHOT_SUSPEND_COUNT = 0
_SUNLIGHT_OBJECT_NAME = "Planetka Sunlight"
_SURFACE_GRADING_GROUP_NAME = "Planetka Surface Grading Group"
_FAKE_ATMOSPHERE_DENSITY_SOCKET = "Atmosphere Density"
_FAKE_ATMOSPHERE_DENSITY_SOCKET_LEGACY = "Fake Atmosphere Density"
_FAKE_ATMOSPHERE_HEIGHT_SOCKET = "Fake Atmosphere Height (km)"
_FAKE_ATMOSPHERE_FALLOFF_SOCKET = "Atmosphere Exponential Falloff"
_FAKE_ATMOSPHERE_COLOR_SOCKET = "Atmosphere Color"
_FAKE_ATMOSPHERE_SURFACE_DENSITY_SCALE = 0.2
# Linear-space RGBA that displays as sRGB #8CB2E3FF in Blender color UI.
_FAKE_ATMOSPHERE_DEFAULT_COLOR = (0.26225066, 0.44520119, 0.76815115, 1.0)
ANIMATION_PREPARED_SEGMENTS_KEY = "planetka_anim_prepared_segments"


def _active_view_signature():
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return None

    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = getattr(area.spaces, "active", None)
            if not space or space.type != 'VIEW_3D':
                continue
            rv3d = getattr(space, "region_3d", None)
            if rv3d is None:
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            region_sig = (
                int(getattr(region, "width", 0)) if region else 0,
                int(getattr(region, "height", 0)) if region else 0,
            )
            matrix_signature = tuple(
                round(float(value), 6)
                for row in rv3d.view_matrix
                for value in row
            )
            return (
                str(getattr(rv3d, "view_perspective", "")),
                bool(getattr(rv3d, "is_perspective", True)),
                round(float(getattr(space, "lens", 50.0)), 6),
                region_sig,
                matrix_signature,
            )
    return None


def _get_mesh_utils():
    global _MESH_UTILS_MODULE
    if _MESH_UTILS_MODULE is None:
        module_name = f"{__package__}.mesh_utils" if __package__ else "mesh_utils"
        try:
            _MESH_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _MESH_UTILS_MODULE = False
    return _MESH_UTILS_MODULE or None


def _get_shader_utils():
    global _SHADER_UTILS_MODULE
    if _SHADER_UTILS_MODULE is None:
        module_name = f"{__package__}.shader_utils" if __package__ else "shader_utils"
        try:
            _SHADER_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _SHADER_UTILS_MODULE = False
    return _SHADER_UTILS_MODULE or None


def _get_tile_utils():
    global _TILE_UTILS_MODULE
    if _TILE_UTILS_MODULE is None:
        module_name = f"{__package__}.tile_utils" if __package__ else "tile_utils"
        try:
            _TILE_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _TILE_UTILS_MODULE = False
    return _TILE_UTILS_MODULE or None


def _get_coverage_map():
    global _COVERAGE_MAP
    if _COVERAGE_MAP is None:
        module_name = f"{__package__}.coverage" if __package__ else "coverage"
        try:
            coverage_module = importlib.import_module(module_name)
            _COVERAGE_MAP = getattr(coverage_module, "COVERAGE", {})
        except ImportError:
            _COVERAGE_MAP = {}
    return _COVERAGE_MAP or {}


def _iter_scenes():
    return tuple(getattr(bpy.data, "scenes", ()))


def _coerce_storage_value(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _sync_idprops_from_props(scene):
    global _IDPROP_SYNCING
    if _IDPROP_SYNCING:
        return
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return
    _IDPROP_SYNCING = True
    try:
        for prop_name, scene_key in _SYNC_IDPROP_MAP.items():
            if not hasattr(props, prop_name):
                continue
            try:
                scene[scene_key] = _coerce_storage_value(getattr(props, prop_name))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed syncing idprop %s", scene_key, exc_info=True)
    finally:
        _IDPROP_SYNCING = False


def _sync_props_from_idprops(scene):
    global _IDPROP_SYNCING
    if _IDPROP_SYNCING:
        return
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return
    _IDPROP_SYNCING = True
    try:
        for prop_name, scene_key in _SYNC_IDPROP_MAP.items():
            if scene_key not in scene or not hasattr(props, prop_name):
                continue
            value = scene.get(scene_key)
            try:
                current = getattr(props, prop_name)
                if isinstance(current, (list, tuple)) and isinstance(value, (list, tuple)):
                    setattr(props, prop_name, tuple(value))
                else:
                    setattr(props, prop_name, value)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed restoring prop %s", prop_name, exc_info=True)

    finally:
        _IDPROP_SYNCING = False


def set_planetka_logging(enabled):
    level = logging.DEBUG if enabled else logging.INFO
    logger.setLevel(level)


def update_debug_logging(self, context):
    set_planetka_logging(bool(getattr(self, "debug_logging", False)))
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene)
    ensure_auto_resolve_service_running()


def _remove_preview_assets():
    preview_obj = bpy.data.objects.get("Planetka Preview Object")
    if preview_obj is not None:
        remove_object_and_unused_mesh(preview_obj)

    for mat_name in ("Planetka Preview Material", "Planetka Preview Shader"):
        material = bpy.data.materials.get(mat_name)
        if material is None:
            continue
        try:
            if int(getattr(material, "users", 0)) == 0:
                bpy.data.materials.remove(material)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing preview material %s", mat_name, exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed removing preview material %s", mat_name, exc_info=True)


def update_show_earth_preview(self, context):
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene)

    show_preview = bool(getattr(self, "show_earth_preview", False))
    if show_preview:
        earth = get_earth_object()
        if earth is not None:
            try:
                ensure_preview_object(earth)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed enabling preview object", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed enabling preview object", exc_info=True)
    else:
        _remove_preview_assets()

    ensure_auto_resolve_service_running()


def _navigation_shot_update_timer():
    global _NAVIGATION_SHOT_UPDATE_PENDING
    _NAVIGATION_SHOT_UPDATE_PENDING = False

    if _IDPROP_SYNCING:
        return None

    context = getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    if props is None:
        return None
    earth = get_earth_object()
    if earth is None:
        return None
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    _apply_navigation_shot_now()
    return None


def _apply_navigation_shot_now():
    global _NAVIGATION_SHOT_UPDATE_REENTRANT

    if _NAVIGATION_SHOT_UPDATE_REENTRANT:
        return False
    _NAVIGATION_SHOT_UPDATE_REENTRANT = True
    try:
        result = bpy.ops.planetka.navigation_apply_shot(silent=True)
        return "FINISHED" in result
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: immediate navigation shot update failed", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: immediate navigation shot update failed", exc_info=True)
        return False
    finally:
        _NAVIGATION_SHOT_UPDATE_REENTRANT = False


def _resolve_navigation_adaptive_modifier():
    earth = get_earth_object()
    if earth is None:
        return None, None
    modifiers = getattr(earth, "modifiers", None)
    if modifiers is None:
        return None, None
    subsurf = modifiers.get("Adaptive Subdivision")
    if subsurf is not None and str(getattr(subsurf, "type", "")) == "SUBSURF":
        return earth, subsurf
    for modifier in modifiers:
        if str(getattr(modifier, "type", "")) != "SUBSURF":
            continue
        if "Adaptive" in str(getattr(modifier, "name", "")):
            return earth, modifier
        if bool(getattr(modifier, "use_adaptive_subdivision", False)):
            return earth, modifier
    return None, None


def _navigation_adaptive_restore_timer():
    global _NAVIGATION_ADAPTIVE_TIMER_RUNNING
    global _NAVIGATION_ADAPTIVE_SUSPENDED
    if (time.monotonic() - float(_NAVIGATION_ADAPTIVE_LAST_TOUCH)) < float(_NAVIGATION_ADAPTIVE_IDLE_SEC):
        return 0.05

    suspended = _NAVIGATION_ADAPTIVE_SUSPENDED
    _NAVIGATION_ADAPTIVE_SUSPENDED = None
    _NAVIGATION_ADAPTIVE_TIMER_RUNNING = False
    if not suspended:
        return None

    obj_name, modifier_name, was_viewport_enabled = suspended
    try:
        obj = bpy.data.objects.get(str(obj_name))
        if obj is None:
            return None
        modifier = obj.modifiers.get(str(modifier_name))
        if modifier is None or str(getattr(modifier, "type", "")) != "SUBSURF":
            return None
        modifier.show_viewport = bool(was_viewport_enabled)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed restoring adaptive viewport state", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed restoring adaptive viewport state", exc_info=True)
    return None


def _force_restore_navigation_adaptive_state():
    global _NAVIGATION_ADAPTIVE_SUSPENDED
    global _NAVIGATION_ADAPTIVE_TIMER_RUNNING

    suspended = _NAVIGATION_ADAPTIVE_SUSPENDED
    _NAVIGATION_ADAPTIVE_SUSPENDED = None
    _NAVIGATION_ADAPTIVE_TIMER_RUNNING = False
    if not suspended:
        return

    obj_name, modifier_name, was_viewport_enabled = suspended
    try:
        obj = bpy.data.objects.get(str(obj_name))
        if obj is None:
            return
        modifier = obj.modifiers.get(str(modifier_name))
        if modifier is None or str(getattr(modifier, "type", "")) != "SUBSURF":
            return
        modifier.show_viewport = bool(was_viewport_enabled)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed forced restore of adaptive viewport state", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed forced restore of adaptive viewport state", exc_info=True)


def _suspend_adaptive_viewport_during_navigation(scene):
    global _NAVIGATION_ADAPTIVE_TIMER_RUNNING
    global _NAVIGATION_ADAPTIVE_SUSPENDED
    global _NAVIGATION_ADAPTIVE_LAST_TOUCH
    global _NAVIGATION_ADAPTIVE_IDLE_SEC

    render = getattr(scene, "render", None) if scene else None
    if str(getattr(render, "engine", "")) != "CYCLES":
        return
    props = getattr(scene, "planetka", None) if scene else None
    if props is not None and not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return
    if props is not None:
        try:
            restore_delay = float(getattr(props, "viewport_opt_subdivision_restore_delay_sec", 0.5))
        except (TypeError, ValueError):
            restore_delay = 0.5
        _NAVIGATION_ADAPTIVE_IDLE_SEC = max(0.1, min(2.0, restore_delay))

    obj, modifier = _resolve_navigation_adaptive_modifier()
    if obj is None or modifier is None:
        return

    if _NAVIGATION_ADAPTIVE_SUSPENDED is None:
        _NAVIGATION_ADAPTIVE_SUSPENDED = (
            str(getattr(obj, "name", "")),
            str(getattr(modifier, "name", "")),
            bool(getattr(modifier, "show_viewport", True)),
        )

    try:
        if bool(getattr(modifier, "show_viewport", False)):
            modifier.show_viewport = False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed suspending adaptive viewport", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed suspending adaptive viewport", exc_info=True)

    _NAVIGATION_ADAPTIVE_LAST_TOUCH = time.monotonic()
    if _NAVIGATION_ADAPTIVE_TIMER_RUNNING:
        return
    _NAVIGATION_ADAPTIVE_TIMER_RUNNING = True
    try:
        bpy.app.timers.register(_navigation_adaptive_restore_timer, first_interval=0.05)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _NAVIGATION_ADAPTIVE_TIMER_RUNNING = False
    except (RuntimeError, TypeError, ValueError):
        _NAVIGATION_ADAPTIVE_TIMER_RUNNING = False


def suspend_navigation_shot_updates():
    global _NAVIGATION_SHOT_SUSPEND_COUNT
    _NAVIGATION_SHOT_SUSPEND_COUNT += 1


def resume_navigation_shot_updates():
    global _NAVIGATION_SHOT_SUSPEND_COUNT
    _NAVIGATION_SHOT_SUSPEND_COUNT = max(0, int(_NAVIGATION_SHOT_SUSPEND_COUNT) - 1)


def _get_planetka_sunlight_object():
    sunlight = bpy.data.objects.get(_SUNLIGHT_OBJECT_NAME)
    if sunlight is None:
        return None
    if str(getattr(sunlight, "type", "")) != "LIGHT":
        return None
    light_data = getattr(sunlight, "data", None)
    if light_data is None or str(getattr(light_data, "type", "")) != "SUN":
        return None
    return sunlight


def _ensure_surface_fake_atmosphere_nodes():
    module_name = f"{__package__}.asset_builder" if __package__ else "asset_builder"
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return False

    ensure_fn = getattr(module, "ensure_surface_fake_atmosphere_nodes", None)
    if not callable(ensure_fn):
        return False
    try:
        ensure_fn()
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed ensuring fake atmosphere shader nodes", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed ensuring fake atmosphere shader nodes", exc_info=True)
        return False


def _apply_fake_atmosphere_shell(scene, *, enabled, density, height_km, falloff, color):
    module_name = f"{__package__}.asset_builder" if __package__ else "asset_builder"
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return False

    apply_fn = getattr(module, "apply_fake_atmosphere_shell", None)
    if not callable(apply_fn):
        return False
    try:
        apply_fn(
            scene=scene,
            enabled=bool(enabled),
            density=float(density),
            height_km=float(height_km),
            falloff=float(falloff),
            color=tuple(color),
        )
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed applying atmosphere shell", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed applying atmosphere shell", exc_info=True)
        return False


def _read_fake_atmosphere_shell_inputs(scene):
    module_name = f"{__package__}.asset_builder" if __package__ else "asset_builder"
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None

    read_fn = getattr(module, "read_fake_atmosphere_shell_inputs", None)
    if not callable(read_fn):
        return None
    try:
        result = read_fn(scene=scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed reading atmosphere shell inputs", exc_info=True)
        return None
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed reading atmosphere shell inputs", exc_info=True)
        return None
    return result if isinstance(result, dict) else None


def _sync_fake_atmosphere_props_from_shell(scene):
    global _FAKE_ATMOSPHERE_PROP_SYNCING
    if scene is None:
        return False
    props = getattr(scene, "planetka", None)
    if props is None:
        return False
    shell_values = _read_fake_atmosphere_shell_inputs(scene)
    if not shell_values:
        return False

    changed = False
    _FAKE_ATMOSPHERE_PROP_SYNCING = True
    try:
        density = max(0.0, min(2.0, float(shell_values.get("density", getattr(props, "fake_atmosphere_density", (1.0 / 3.0))))))
        height_km = max(0.0, min(400.0, float(shell_values.get("height_km", getattr(props, "fake_atmosphere_height_km", 50.0)))))
        falloff = max(0.0, min(1.0, float(shell_values.get("falloff", getattr(props, "fake_atmosphere_falloff_exp", 0.05)))))
        color_raw = shell_values.get("color", getattr(props, "fake_atmosphere_color", _FAKE_ATMOSPHERE_DEFAULT_COLOR))
        color = tuple(max(0.0, min(1.0, float(color_raw[i]))) for i in range(4))

        if abs(float(getattr(props, "fake_atmosphere_density", (1.0 / 3.0))) - density) > 1e-6:
            props.fake_atmosphere_density = density
            changed = True
        if abs(float(getattr(props, "fake_atmosphere_height_km", 50.0)) - height_km) > 1e-6:
            props.fake_atmosphere_height_km = height_km
            changed = True
        if abs(float(getattr(props, "fake_atmosphere_falloff_exp", 0.05)) - falloff) > 1e-6:
            props.fake_atmosphere_falloff_exp = falloff
            changed = True

        current_color = tuple(float(getattr(props, "fake_atmosphere_color", _FAKE_ATMOSPHERE_DEFAULT_COLOR)[i]) for i in range(4))
        if any(abs(current_color[i] - color[i]) > 1e-6 for i in range(4)):
            props.fake_atmosphere_color = color
            changed = True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, IndexError):
        logger.debug("Planetka: failed syncing atmosphere props from shell", exc_info=True)
        changed = False
    finally:
        _FAKE_ATMOSPHERE_PROP_SYNCING = False

    if changed:
        _sync_idprops_from_props(scene)
    return changed


def _iter_group_nodes_recursive(node_tree, group_name, visited=None, depth=0, depth_cap=64):
    if node_tree is None or depth > depth_cap:
        return ()
    if visited is None:
        visited = set()
    try:
        ptr = node_tree.as_pointer()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return ()
    if ptr in visited:
        return ()
    visited.add(ptr)

    found = []
    for node in getattr(node_tree, "nodes", ()):
        if str(getattr(node, "type", "")) != "GROUP":
            continue
        inner_tree = getattr(node, "node_tree", None)
        if inner_tree is None:
            continue
        if str(getattr(inner_tree, "name", "")) == str(group_name):
            found.append(node)
        found.extend(_iter_group_nodes_recursive(inner_tree, group_name, visited, depth + 1, depth_cap))
    return found


def _iter_surface_grading_nodes():
    for material in getattr(bpy.data, "materials", ()):
        node_tree = getattr(material, "node_tree", None)
        if node_tree is None:
            continue
        for node in _iter_group_nodes_recursive(node_tree, _SURFACE_GRADING_GROUP_NAME):
            yield node


def _effective_fake_atmosphere_density(props):
    if props is None:
        return 0.0
    enabled = bool(getattr(props, "enable_fake_atmosphere", False))
    if not enabled:
        return 0.0
    try:
        density = float(getattr(props, "fake_atmosphere_density", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(2.0, density))


def _effective_fake_atmosphere_height_km(props):
    if props is None:
        return 0.0
    enabled = bool(getattr(props, "enable_fake_atmosphere", False))
    if not enabled:
        return 0.0
    try:
        height_km = float(getattr(props, "fake_atmosphere_height_km", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(400.0, height_km))


def _effective_fake_atmosphere_falloff(props):
    if props is None:
        return 0.0
    enabled = bool(getattr(props, "enable_fake_atmosphere", False))
    if not enabled:
        return 0.0
    try:
        falloff = float(getattr(props, "fake_atmosphere_falloff_exp", 0.05))
    except (TypeError, ValueError):
        return 0.05
    return max(0.0, min(1.0, falloff))


def _effective_fake_atmosphere_color(props):
    default = _FAKE_ATMOSPHERE_DEFAULT_COLOR
    if props is None:
        return default
    value = getattr(props, "fake_atmosphere_color", default)
    try:
        rgba = [float(value[i]) for i in range(4)]
    except (TypeError, ValueError, IndexError):
        return default
    return (
        max(0.0, min(1.0, rgba[0])),
        max(0.0, min(1.0, rgba[1])),
        max(0.0, min(1.0, rgba[2])),
        max(0.0, min(1.0, rgba[3])),
    )


def _apply_fake_atmosphere_from_props(scene):
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return

    _ensure_surface_fake_atmosphere_nodes()
    shell_density = _effective_fake_atmosphere_density(props)
    shell_height = _effective_fake_atmosphere_height_km(props)
    shell_falloff = _effective_fake_atmosphere_falloff(props)
    shell_color = _effective_fake_atmosphere_color(props)
    enabled = bool(getattr(props, "enable_fake_atmosphere", False))
    quick_enabled = enabled
    # Keep shell as primary atmosphere while allowing low-elevation surface haze.
    target_density = shell_density * float(_FAKE_ATMOSPHERE_SURFACE_DENSITY_SCALE) if quick_enabled else 0.0
    target_height = shell_height if quick_enabled else 0.0
    target_falloff = shell_falloff if quick_enabled else 0.0
    target_color = shell_color

    changed = 0
    for node in _iter_surface_grading_nodes():
        try:
            density_socket = (
                node.inputs.get(_FAKE_ATMOSPHERE_DENSITY_SOCKET)
                or node.inputs.get(_FAKE_ATMOSPHERE_DENSITY_SOCKET_LEGACY)
            )
            height_socket = node.inputs.get(_FAKE_ATMOSPHERE_HEIGHT_SOCKET)
            falloff_socket = node.inputs.get(_FAKE_ATMOSPHERE_FALLOFF_SOCKET)
            color_socket = node.inputs.get(_FAKE_ATMOSPHERE_COLOR_SOCKET)
        except (AttributeError, TypeError, ValueError):
            density_socket = None
            height_socket = None
            falloff_socket = None
            color_socket = None
        if density_socket is None and height_socket is None and falloff_socket is None and color_socket is None:
            continue
        try:
            if density_socket is not None and abs(float(density_socket.default_value) - float(target_density)) > 1e-6:
                density_socket.default_value = float(target_density)
                changed += 1
            if height_socket is not None and abs(float(height_socket.default_value) - float(target_height)) > 1e-6:
                height_socket.default_value = float(target_height)
                changed += 1
            if falloff_socket is not None and abs(float(falloff_socket.default_value) - float(target_falloff)) > 1e-6:
                falloff_socket.default_value = float(target_falloff)
                changed += 1
            if color_socket is not None:
                current_color = tuple(float(color_socket.default_value[i]) for i in range(4))
                if any(abs(current_color[i] - float(target_color[i])) > 1e-6 for i in range(4)):
                    color_socket.default_value = tuple(target_color)
                    changed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed setting fake atmosphere settings", exc_info=True)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed setting fake atmosphere settings", exc_info=True)

    if changed > 0:
        _tag_view3d_redraw()
    shell_applied = _apply_fake_atmosphere_shell(
        scene,
        enabled=quick_enabled,
        density=shell_density,
        height_km=shell_height if quick_enabled else 0.0,
        falloff=shell_falloff if quick_enabled else 0.0,
        color=shell_color,
    )
    if shell_applied and changed == 0:
        _tag_view3d_redraw()


def _apply_sunlight_from_props(scene):
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    sunlight = _get_planetka_sunlight_object()
    if sunlight is None:
        return

    try:
        lon_deg = float(getattr(props, "sunlight_longitude_deg", 0.0))
        lat_deg = float(getattr(props, "sunlight_seasonal_tilt_deg", 0.0))
    except (TypeError, ValueError):
        return

    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    try:
        direction = Vector(
            (
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            )
        )
        if direction.length < 1e-9:
            return
        direction.normalize()
    except Exception:
        return

    try:
        quat = direction.to_track_quat('Z', 'Y')
        sunlight.rotation_mode = 'XYZ'
        sunlight.rotation_euler = quat.to_euler('XYZ')
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed applying sunlight transform", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed applying sunlight transform", exc_info=True)


def update_sunlight_controls(self, context):
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene)
        _suspend_adaptive_viewport_during_navigation(scene)
        ensure_auto_resolve_service_running()
    _apply_sunlight_from_props(scene)


def update_fake_atmosphere(self, context):
    if _FAKE_ATMOSPHERE_PROP_SYNCING:
        return
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene)
    _apply_fake_atmosphere_from_props(scene)
    ensure_auto_resolve_service_running()


def update_navigation_shot(self, context):
    global _NAVIGATION_SHOT_UPDATE_PENDING
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene)
        _suspend_adaptive_viewport_during_navigation(scene)
        ensure_auto_resolve_service_running()
    if _NAVIGATION_SHOT_SUSPEND_COUNT > 0:
        return
    if _IDPROP_SYNCING or _NAVIGATION_SHOT_UPDATE_REENTRANT:
        return
    if _apply_navigation_shot_now():
        _NAVIGATION_SHOT_UPDATE_PENDING = False
        return
    if _NAVIGATION_SHOT_UPDATE_PENDING:
        return
    _NAVIGATION_SHOT_UPDATE_PENDING = True
    try:
        bpy.app.timers.register(_navigation_shot_update_timer, first_interval=0.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _NAVIGATION_SHOT_UPDATE_PENDING = False
    except (RuntimeError, TypeError, ValueError):
        _NAVIGATION_SHOT_UPDATE_PENDING = False


def _is_animation_playing():
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return False
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen and bool(getattr(screen, "is_animation_playing", False)):
            return True
    return False


def _is_render_job_active():
    global _RENDER_JOB_ACTIVE
    # bpy.app.is_job_running("RENDER") has been observed to get stuck True on some systems after F12
    # renders, which would permanently disable auto-resolve. Track render state via handlers and
    # prefer that signal.
    if _RENDER_JOB_ACTIVE:
        return True

    app = getattr(bpy, "app", None)
    is_job_running = getattr(app, "is_job_running", None) if app else None
    if not callable(is_job_running):
        return False

    # Ignore the "RENDER" job here to avoid false positives; use handler state instead.
    for job_name in ("OBJECT_BAKE",):
        try:
            if bool(is_job_running(job_name)):
                return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
    return False


def _scene_key(scene):
    return int(getattr(scene, "as_pointer", lambda: id(scene))())


def _camera_signature(scene):
    active_sig = _active_view_signature()
    if active_sig is not None and str(active_sig[0]) != "CAMERA":
        earth = get_earth_object()
        earth_matrix_signature = None
        if earth is not None:
            earth_matrix_signature = tuple(round(float(value), 6) for row in earth.matrix_world for value in row)
        return ("ACTIVE_VIEW", active_sig, earth_matrix_signature)

    camera = getattr(scene, "camera", None)
    if camera is None:
        return None
    camera_data = getattr(camera, "data", None)
    if camera_data is None:
        return None

    matrix_signature = tuple(round(float(value), 6) for row in camera.matrix_world for value in row)
    earth = get_earth_object()
    earth_matrix_signature = None
    if earth is not None:
        earth_matrix_signature = tuple(round(float(value), 6) for row in earth.matrix_world for value in row)

    return (
        str(getattr(camera, "name_full", camera.name)),
        str(getattr(camera_data, "type", "")),
        round(float(getattr(camera_data, "lens", 0.0)), 6),
        round(float(getattr(camera_data, "ortho_scale", 0.0)), 6),
        matrix_signature,
        earth_matrix_signature,
    )


def _output_resolution_signature(scene):
    render = getattr(scene, "render", None) if scene is not None else None
    if render is None:
        return None
    try:
        return (
            int(getattr(render, "resolution_x", 1920)),
            int(getattr(render, "resolution_y", 1080)),
            int(getattr(render, "resolution_percentage", 100)),
        )
    except (TypeError, ValueError, RuntimeError):
        return None


def _current_view_scope(scene):
    active_sig = _active_view_signature()
    if active_sig is not None and str(active_sig[0]) != "CAMERA":
        return "ACTIVE_VIEW"
    if getattr(scene, "camera", None) is not None:
        return "CAMERA"
    return "NONE"


def _handle_viewport_motion_optimization(scene, camera_signature):
    if scene is None or camera_signature is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = _scene_key(scene)
    previous_signature = _VIEWPORT_OPT_LAST_SIGNATURE.get(scene_id)
    if previous_signature == camera_signature:
        return
    _VIEWPORT_OPT_LAST_SIGNATURE[scene_id] = camera_signature
    _suspend_adaptive_viewport_during_navigation(scene)


def _timeline_signature(scene):
    if scene is None:
        return None
    try:
        frame = int(getattr(scene, "frame_current", 0))
    except (TypeError, ValueError, RuntimeError):
        frame = 0
    try:
        subframe = round(float(getattr(scene, "frame_subframe", 0.0)), 4)
    except (TypeError, ValueError, RuntimeError):
        subframe = 0.0
    return (frame, subframe)


def _handle_timeline_motion_optimization(scene):
    if scene is None:
        return
    if _is_render_job_active():
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = _scene_key(scene)
    current_signature = _timeline_signature(scene)
    previous_signature = _TIMELINE_LAST_SIGNATURE.get(scene_id)
    _TIMELINE_LAST_SIGNATURE[scene_id] = current_signature

    if _is_animation_playing():
        _suspend_adaptive_viewport_during_navigation(scene)
        return

    if previous_signature is None:
        return
    if current_signature == previous_signature:
        return
    _suspend_adaptive_viewport_during_navigation(scene)


def _sunlight_signature(scene):
    scene_id = _scene_key(scene) if scene is not None else None

    def _is_valid_sunlight_object(obj):
        if obj is None or str(getattr(obj, "type", "")) != "LIGHT":
            return False
        light_data = getattr(obj, "data", None)
        return str(getattr(light_data, "type", "")) == "SUN"

    def _scene_object_by_name(name):
        if scene is None or not name:
            return None
        scene_objects = getattr(scene, "objects", None)
        if scene_objects is None:
            return None
        try:
            return scene_objects.get(name)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None

    sunlight = _scene_object_by_name(_SUNLIGHT_OBJECT_NAME)
    if not _is_valid_sunlight_object(sunlight):
        sunlight = None

    if sunlight is None and scene_id is not None:
        cached_name = str(_SUNLIGHT_OBJECT_NAME_CACHE.get(scene_id, "") or "")
        cached_obj = _scene_object_by_name(cached_name)
        if _is_valid_sunlight_object(cached_obj):
            sunlight = cached_obj

    if sunlight is None and scene is not None:
        fallback = None
        fallback_name = ""
        for obj in getattr(scene, "objects", ()):
            if not _is_valid_sunlight_object(obj):
                continue
            name = str(getattr(obj, "name", ""))
            if name == _SUNLIGHT_OBJECT_NAME:
                sunlight = obj
                break
            if name.startswith(_SUNLIGHT_OBJECT_NAME):
                if fallback is None or name < fallback_name:
                    fallback = obj
                    fallback_name = name
        if sunlight is None:
            sunlight = fallback

    if sunlight is None:
        fallback_obj = bpy.data.objects.get(_SUNLIGHT_OBJECT_NAME)
        if _is_valid_sunlight_object(fallback_obj):
            sunlight = fallback_obj

    if scene_id is not None:
        if sunlight is not None:
            _SUNLIGHT_OBJECT_NAME_CACHE[scene_id] = str(getattr(sunlight, "name", ""))
        else:
            _SUNLIGHT_OBJECT_NAME_CACHE.pop(scene_id, None)

    if sunlight is None:
        return None
    matrix_signature = tuple(
        round(float(value), 6)
        for row in sunlight.matrix_world
        for value in row
    )
    return (
        str(getattr(sunlight, "name", _SUNLIGHT_OBJECT_NAME)),
        matrix_signature,
    )


def _handle_sunlight_motion_optimization(scene):
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        return

    scene_id = _scene_key(scene)
    signature = _sunlight_signature(scene)
    previous_signature = _SUNLIGHT_LAST_SIGNATURE.get(scene_id)
    _SUNLIGHT_LAST_SIGNATURE[scene_id] = signature
    if signature is None or previous_signature is None:
        return
    if signature == previous_signature:
        return
    _suspend_adaptive_viewport_during_navigation(scene)


def _handle_view_scope_quality_transition(scene):
    global _AUTO_RESOLVE_IN_FLIGHT

    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if get_earth_object() is None:
        return
    try:
        if int(scene.get(ANIMATION_PREPARED_SEGMENTS_KEY, 0)) > 0:
            return
    except (TypeError, ValueError):
        pass

    scene_id = _scene_key(scene)
    current_scope = _current_view_scope(scene)
    previous_scope = _VIEWPORT_SCOPE_LAST.get(scene_id)
    _VIEWPORT_SCOPE_LAST[scene_id] = current_scope
    if previous_scope is None or previous_scope == current_scope:
        return

    if previous_scope != "ACTIVE_VIEW" or current_scope != "CAMERA":
        return
    if not bool(getattr(props, "auto_resolve", False)):
        return
    if not bool(getattr(props, "viewport_opt_active_view_coarse_textures", True)):
        return
    if _AUTO_RESOLVE_IN_FLIGHT:
        return
    if _is_render_job_active():
        return
    if _is_animation_playing() and bool(getattr(props, "lock_resolve_during_animation", True)):
        return

    now = time.monotonic()
    last_transition_resolve = _VIEWPORT_SCOPE_LAST_RESOLVE_TIME.get(scene_id, 0.0)
    if now - float(last_transition_resolve) < 0.2:
        return

    tile_utils = _get_tile_utils()
    if tile_utils is None:
        return

    try:
        target_tiles = _canonical_tiles(tile_utils.main(scope_mode="CAMERA"))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka scope transition resolve: tile computation failed", exc_info=True)
        return
    except Exception:
        logger.debug("Planetka scope transition resolve: unexpected tile computation failure", exc_info=True)
        return

    if target_tiles == _last_resolved_tiles(scene):
        _VIEWPORT_SCOPE_LAST_RESOLVE_TIME[scene_id] = now
        return

    _AUTO_RESOLVE_IN_FLIGHT = True
    try:
        result = bpy.ops.planetka.load_textures()
        if "FINISHED" in result:
            resolved_at = time.monotonic()
            _VIEWPORT_SCOPE_LAST_RESOLVE_TIME[scene_id] = resolved_at
            _AUTO_RESOLVE_LAST_RESOLVE_TIME[scene_id] = resolved_at
            latest_signature = _camera_signature(scene)
            if latest_signature is not None:
                _AUTO_RESOLVE_LAST_CAMERA_SIGNATURE[scene_id] = latest_signature
                _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE[scene_id] = latest_signature
            _AUTO_RESOLVE_LAST_CHANGE_TIME[scene_id] = resolved_at
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka scope transition resolve failed", exc_info=True)
    except Exception:
        logger.debug("Planetka scope transition resolve failed unexpectedly", exc_info=True)
    finally:
        _AUTO_RESOLVE_IN_FLIGHT = False


def _earth_radius_blender_units(earth_obj):
    if not earth_obj:
        return 1.0
    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0
    if stored_local_radius > 1e-9:
        scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(scale.x), abs(scale.y), abs(scale.z), 1e-9)
        return stored_local_radius * float(max_scale)
    scale = earth_obj.matrix_world.to_scale()
    return max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)


def _intersect_ray_sphere_nearest(origin, direction, radius):
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


def _realtime_view_camera_info(scene):
    context = bpy.context
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
        cam_matrix = rv3d.view_matrix.inverted()
        return {
            "position": cam_matrix.translation.copy(),
            "forward": (-cam_matrix.col[2].xyz).normalized(),
        }

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
                if not candidate_space or candidate_space.type != 'VIEW_3D':
                    continue
                candidate_rv3d = getattr(candidate_space, "region_3d", None)
                if candidate_rv3d is None:
                    continue
                cam_matrix = candidate_rv3d.view_matrix.inverted()
                return {
                    "position": cam_matrix.translation.copy(),
                    "forward": (-cam_matrix.col[2].xyz).normalized(),
                }

    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return None
    matrix = camera.matrix_world
    return {
        "position": matrix.translation.copy(),
        "forward": (-matrix.col[2].xyz).normalized(),
    }


def _active_camera_projection_info(scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return None
    cam_data = getattr(camera, "data", None)
    if cam_data is None:
        return None

    render = getattr(scene, "render", None) if scene else None
    scale = float(getattr(render, "resolution_percentage", 100)) / 100.0 if render else 1.0
    res_x = max(1.0, float(getattr(render, "resolution_x", 1920)) * scale) if render else 1920.0
    res_y = max(1.0, float(getattr(render, "resolution_y", 1080)) * scale) if render else 1080.0
    cam_type = str(getattr(cam_data, "type", "PERSP"))

    if cam_type == "ORTHO":
        h_fov = math.radians(50.0)
        v_fov = math.radians(35.0)
        ortho_scale = float(getattr(cam_data, "ortho_scale", 1.0))
    else:
        h_fov = float(getattr(cam_data, "angle_x", math.radians(50.0)))
        v_fov = float(getattr(cam_data, "angle_y", math.radians(35.0)))
        ortho_scale = 1.0

    return {
        "camera_type": cam_type,
        "h_fov": h_fov,
        "v_fov": v_fov,
        "res_x": float(res_x),
        "res_y": float(res_y),
        "ortho_scale": float(ortho_scale),
    }


def _tag_view3d_redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _tile_xy_for_lon_lat(lon_deg, lat_deg, z):
    lon_shift = (float(lon_deg) + 180.0) % 360.0
    lat_shift = max(0.0, min(179.999999, float(lat_deg) + 90.0))
    step = max(1, int(z))
    x = int(lon_shift // step) * step
    y = int(lat_shift // step) * step
    return x % 360, max(0, min(179, y))


def _best_available_mpp_for_lon_lat(lon_deg, lat_deg):
    coverage = _get_coverage_map()
    for z in _LIVE_Z_LEVELS:
        level = coverage.get(int(z), set()) if coverage else set()
        if not level:
            continue
        x, y = _tile_xy_for_lon_lat(lon_deg, lat_deg, z)
        if (x, y) in level:
            return float(z) * _DATASET_MPP_BASE_D1
    return None


def _safety_for_required_vs_available(required_mpp, available_mpp):
    if required_mpp is None:
        return "OK"
    try:
        required = max(1e-9, float(required_mpp))
    except (TypeError, ValueError):
        return "OK"
    try:
        available = float(available_mpp)
    except (TypeError, ValueError):
        return "WARNING"

    ratio = available / required
    if ratio <= 1.0:
        return "OK"
    if ratio <= _LIVE_SAFETY_CAUTION_RATIO:
        return "CAUTION"
    return "WARNING"


def _update_realtime_telemetry(scene):
    if scene is None:
        return
    scene_id = _scene_key(scene)

    earth = get_earth_object()
    if earth is None:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            _tag_view3d_redraw()
        return

    camera_info = _realtime_view_camera_info(scene)
    if not camera_info:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            _tag_view3d_redraw()
        return

    cam_pos_world = camera_info.get("position")
    cam_forward_world = camera_info.get("forward")
    projection_info = _active_camera_projection_info(scene)
    if projection_info is None:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            _tag_view3d_redraw()
        return
    camera_type = str(projection_info.get("camera_type", "PERSP"))
    h_fov = float(projection_info.get("h_fov", math.radians(50.0)))
    v_fov = float(projection_info.get("v_fov", math.radians(35.0)))
    res_x = max(1.0, float(projection_info.get("res_x", 1920.0)))
    res_y = max(1.0, float(projection_info.get("res_y", 1080.0)))
    ortho_scale = float(projection_info.get("ortho_scale", 1.0))
    if cam_pos_world is None or cam_forward_world is None or cam_forward_world.length_squared <= 1e-12:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            _tag_view3d_redraw()
        return

    center, rotation, _scale = earth.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        telemetry = (None, None, None, None, None)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, None, None, None)
            _tag_view3d_redraw()
        return
    cam_forward_local.normalize()

    radius_bu = _earth_radius_blender_units(earth)
    hit_local = _intersect_ray_sphere_nearest(cam_pos_local, cam_forward_local, radius_bu)

    cam_dist = float(cam_pos_local.length)
    altitude_bu = max(0.0, cam_dist - float(radius_bu))
    meters_per_bu = _REAL_EARTH_RADIUS_M / max(float(radius_bu), 1e-9)
    altitude_km = (altitude_bu * meters_per_bu) / 1000.0
    terrain_offset_bu = _MAX_TERRAIN_HEIGHT_M / max(meters_per_bu, 1e-9)
    effective_distance = max(0.0, float(altitude_bu) - float(terrain_offset_bu))
    if camera_type == "ORTHO":
        px_world = max(float(ortho_scale) / res_x, float(ortho_scale) / res_y)
        estimated_mpp = px_world * meters_per_bu
    else:
        px_angle = max(h_fov / res_x, v_fov / res_y)
        px_angle = max(1e-9, float(px_angle))
        footprint_world = 2.0 * effective_distance * math.tan(px_angle * 0.5)
        estimated_mpp = footprint_world * meters_per_bu

    if hit_local is None:
        live_safety = "OK"
        telemetry = (None, None, round(float(altitude_km), 3), round(float(estimated_mpp), 3), live_safety)
        if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
            _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
            write_realtime_view_diagnostics(scene, None, None, altitude_km, estimated_mpp, live_safety)
            _tag_view3d_redraw()
        return

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    available_mpp = _best_available_mpp_for_lon_lat(lon, lat)
    if available_mpp is None:
        available_mpp = _LIVE_FALLBACK_MPP_M
    live_safety = _safety_for_required_vs_available(estimated_mpp, available_mpp)
    telemetry = (
        round(float(lat), 4),
        round(float(lon), 4),
        round(float(altitude_km), 3),
        round(float(estimated_mpp), 3),
        live_safety,
    )
    if _LAST_REALTIME_TELEMETRY.get(scene_id) != telemetry:
        _LAST_REALTIME_TELEMETRY[scene_id] = telemetry
        write_realtime_view_diagnostics(scene, lat, lon, altitude_km, estimated_mpp, live_safety)
        _tag_view3d_redraw()


def _canonical_tiles(tiles):
    if not isinstance(tiles, (list, tuple)):
        return tuple()
    return tuple(sorted(str(tile) for tile in tiles if tile))


def _last_resolved_tiles(scene):
    try:
        return _canonical_tiles(scene.get("planetka_last_resolved_tiles", ()))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return tuple()


def _mark_auto_resolve_dirty(scene, immediate=False):
    if not scene:
        return
    scene_id = _scene_key(scene)
    now = time.monotonic()
    _AUTO_RESOLVE_LAST_CAMERA_SIGNATURE.pop(scene_id, None)
    _AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE.pop(scene_id, None)
    _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE.pop(scene_id, None)
    _AUTO_RESOLVE_PENDING_OUTPUT_CHANGE.pop(scene_id, None)
    _AUTO_RESOLVE_LAST_CHANGE_TIME[scene_id] = now - (AUTO_RESOLVE_IDLE_SEC_DEFAULT if immediate else 0.0)


def update_auto_resolve(self, context):
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene)
        _mark_auto_resolve_dirty(scene, immediate=True)
    ensure_auto_resolve_service_running()


def _auto_resolve_tick_once():
    global _AUTO_RESOLVE_IN_FLIGHT

    if _AUTO_RESOLVE_IN_FLIGHT:
        return

    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return

    props = getattr(scene, "planetka", None)
    if not props or not bool(getattr(props, "auto_resolve", False)):
        return
    try:
        if int(scene.get(ANIMATION_PREPARED_SEGMENTS_KEY, 0)) > 0:
            return
    except (TypeError, ValueError):
        pass

    min_interval_sec = AUTO_RESOLVE_MIN_INTERVAL_SEC_DEFAULT

    try:
        idle_sec = float(getattr(props, "auto_resolve_idle_sec", AUTO_RESOLVE_IDLE_SEC_DEFAULT))
    except (TypeError, ValueError):
        idle_sec = AUTO_RESOLVE_IDLE_SEC_DEFAULT
    idle_sec = max(0.1, min(3.0, idle_sec))

    if _is_animation_playing():
        if bool(getattr(props, "lock_resolve_during_animation", True)):
            return

    if _is_render_job_active():
        return

    if get_earth_object() is None:
        return

    camera_signature = _camera_signature(scene)
    if camera_signature is None:
        return

    scene_id = _scene_key(scene)
    now = time.monotonic()
    output_signature = _output_resolution_signature(scene)
    previous_output_signature = _AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE.get(scene_id)
    if previous_output_signature != output_signature:
        _AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE[scene_id] = output_signature
        if previous_output_signature is not None:
            _AUTO_RESOLVE_PENDING_OUTPUT_CHANGE[scene_id] = True
            _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE.pop(scene_id, None)
            _AUTO_RESOLVE_LAST_CHANGE_TIME[scene_id] = now

    previous_signature = _AUTO_RESOLVE_LAST_CAMERA_SIGNATURE.get(scene_id)
    if previous_signature != camera_signature:
        _AUTO_RESOLVE_LAST_CAMERA_SIGNATURE[scene_id] = camera_signature
        _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE.pop(scene_id, None)
        _AUTO_RESOLVE_LAST_CHANGE_TIME[scene_id] = now
        return

    last_change = _AUTO_RESOLVE_LAST_CHANGE_TIME.get(scene_id)
    if last_change is None:
        _AUTO_RESOLVE_LAST_CHANGE_TIME[scene_id] = now
        return

    if now - last_change < idle_sec:
        return

    last_resolve = _AUTO_RESOLVE_LAST_RESOLVE_TIME.get(scene_id, 0.0)
    if now - last_resolve < min_interval_sec:
        return

    pending_output_change = bool(_AUTO_RESOLVE_PENDING_OUTPUT_CHANGE.get(scene_id, False))
    if _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE.get(scene_id) == camera_signature and not pending_output_change:
        return

    tile_utils = _get_tile_utils()
    if tile_utils is None:
        return

    try:
        target_tiles = _canonical_tiles(
            tile_utils.main(
                scope_mode="AUTO",
            )
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka auto-resolve: tile computation failed", exc_info=True)
        return
    except Exception:
        logger.debug("Planetka auto-resolve: unexpected tile computation failure", exc_info=True)
        return

    if target_tiles == _last_resolved_tiles(scene) and not pending_output_change:
        _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE[scene_id] = camera_signature
        _AUTO_RESOLVE_LAST_RESOLVE_TIME[scene_id] = now
        return

    _AUTO_RESOLVE_IN_FLIGHT = True
    try:
        result = bpy.ops.planetka.load_textures()
        if "FINISHED" in result:
            resolved_at = time.monotonic()
            _AUTO_RESOLVE_LAST_RESOLVE_TIME[scene_id] = resolved_at
            _AUTO_RESOLVE_LAST_CHANGE_TIME[scene_id] = resolved_at
            latest_signature = _camera_signature(scene) or camera_signature
            _AUTO_RESOLVE_LAST_CAMERA_SIGNATURE[scene_id] = latest_signature
            _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE[scene_id] = latest_signature
            _AUTO_RESOLVE_PENDING_OUTPUT_CHANGE.pop(scene_id, None)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka auto-resolve failed", exc_info=True)
    except Exception:
        logger.debug("Planetka auto-resolve failed unexpectedly", exc_info=True)
    finally:
        _AUTO_RESOLVE_IN_FLIGHT = False


def _auto_resolve_timer():
    global _AUTO_RESOLVE_TIMER_RUNNING
    global _AUTO_RESOLVE_LAST_BUDGET_SKIP_LOG_AT

    def _budget_exceeded(timer_start, phase_name):
        elapsed_ms = (time.perf_counter() - timer_start) * 1000.0
        if elapsed_ms <= AUTO_RESOLVE_TIMER_BUDGET_MS:
            return False
        now = time.monotonic()
        if now - float(_AUTO_RESOLVE_LAST_BUDGET_SKIP_LOG_AT) >= AUTO_RESOLVE_BUDGET_SKIP_LOG_COOLDOWN_SEC:
            logger.debug(
                "Planetka auto-resolve timer over budget after %s (%.2f ms > %.2f ms); "
                "deferring remaining work to next tick.",
                phase_name,
                elapsed_ms,
                AUTO_RESOLVE_TIMER_BUDGET_MS,
            )
            _AUTO_RESOLVE_LAST_BUDGET_SKIP_LOG_AT = now
        return True

    try:
        if not hasattr(bpy.types.Scene, "planetka"):
            _AUTO_RESOLVE_TIMER_RUNNING = False
            return None

        tick_start = time.perf_counter()
        scene = getattr(bpy.context, "scene", None)
        _update_realtime_telemetry(scene)
        if _budget_exceeded(tick_start, "realtime telemetry"):
            return AUTO_RESOLVE_TIMER_INTERVAL_SEC

        camera_signature = _camera_signature(scene) if scene is not None else None
        if _budget_exceeded(tick_start, "camera signature"):
            return AUTO_RESOLVE_TIMER_INTERVAL_SEC

        _handle_timeline_motion_optimization(scene)
        if _budget_exceeded(tick_start, "timeline motion optimization"):
            return AUTO_RESOLVE_TIMER_INTERVAL_SEC

        _handle_viewport_motion_optimization(scene, camera_signature)
        if _budget_exceeded(tick_start, "viewport motion optimization"):
            return AUTO_RESOLVE_TIMER_INTERVAL_SEC

        _handle_sunlight_motion_optimization(scene)
        if _budget_exceeded(tick_start, "sunlight motion optimization"):
            return AUTO_RESOLVE_TIMER_INTERVAL_SEC

        _handle_view_scope_quality_transition(scene)
        if _budget_exceeded(tick_start, "view-scope quality transition"):
            return AUTO_RESOLVE_TIMER_INTERVAL_SEC

        _auto_resolve_tick_once()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka auto-resolve timer tick failed", exc_info=True)
    except Exception:
        logger.debug("Planetka auto-resolve timer tick failed unexpectedly", exc_info=True)
    return AUTO_RESOLVE_TIMER_INTERVAL_SEC


def ensure_auto_resolve_service_running():
    global _AUTO_RESOLVE_TIMER_RUNNING
    try:
        if not bpy.app.timers.is_registered(_auto_resolve_timer):
            bpy.app.timers.register(
                _auto_resolve_timer,
                first_interval=AUTO_RESOLVE_TIMER_INTERVAL_SEC,
                persistent=True,
            )
        _AUTO_RESOLVE_TIMER_RUNNING = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed starting auto-resolve timer", exc_info=True)


def stop_auto_resolve_service():
    global _AUTO_RESOLVE_TIMER_RUNNING
    global _AUTO_RESOLVE_LAST_BUDGET_SKIP_LOG_AT
    try:
        if bpy.app.timers.is_registered(_auto_resolve_timer):
            bpy.app.timers.unregister(_auto_resolve_timer)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed stopping auto-resolve timer", exc_info=True)
    _AUTO_RESOLVE_TIMER_RUNNING = False
    _AUTO_RESOLVE_LAST_CAMERA_SIGNATURE.clear()
    _AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE.clear()
    _AUTO_RESOLVE_LAST_CHANGE_TIME.clear()
    _AUTO_RESOLVE_LAST_RESOLVE_TIME.clear()
    _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE.clear()
    _AUTO_RESOLVE_PENDING_OUTPUT_CHANGE.clear()
    _VIEWPORT_OPT_LAST_SIGNATURE.clear()
    _SUNLIGHT_LAST_SIGNATURE.clear()
    _VIEWPORT_SCOPE_LAST.clear()
    _VIEWPORT_SCOPE_LAST_RESOLVE_TIME.clear()
    _LAST_REALTIME_TELEMETRY.clear()
    _TIMELINE_LAST_SIGNATURE.clear()
    _SUNLIGHT_OBJECT_NAME_CACHE.clear()
    _AUTO_RESOLVE_LAST_BUDGET_SKIP_LOG_AT = 0.0


def recover_post_render_state(scene=None):
    global _AUTO_RESOLVE_IN_FLIGHT
    global _RENDER_JOB_ACTIVE
    global _NAVIGATION_SHOT_UPDATE_PENDING
    global _NAVIGATION_SHOT_UPDATE_REENTRANT
    global _NAVIGATION_SHOT_SUSPEND_COUNT

    _AUTO_RESOLVE_IN_FLIGHT = False
    _RENDER_JOB_ACTIVE = False
    _NAVIGATION_SHOT_UPDATE_PENDING = False
    _NAVIGATION_SHOT_UPDATE_REENTRANT = False
    _NAVIGATION_SHOT_SUSPEND_COUNT = 0
    _force_restore_navigation_adaptive_state()

    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        _mark_auto_resolve_dirty(scene, immediate=True)
    ensure_auto_resolve_service_running()


def mark_render_job_started():
    global _RENDER_JOB_ACTIVE
    _RENDER_JOB_ACTIVE = True


def _sync_logging_from_scenes():
    global _LOGGING_SYNCING
    if _LOGGING_SYNCING:
        return
    _LOGGING_SYNCING = True
    try:
        enabled = False
        for scene in _iter_scenes():
            props = getattr(scene, "planetka", None)
            if props and bool(getattr(props, "debug_logging", False)):
                enabled = True
                break
        set_planetka_logging(enabled)
    finally:
        _LOGGING_SYNCING = False


def migrate_scene(scene):
    migrate_scene_schema(scene, sync_idprops_fn=_sync_idprops_from_props, logger=logger)
    for key in _LEGACY_SCENE_IDPROPS:
        try:
            if key in scene:
                del scene[key]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing legacy scene idprop %s", key, exc_info=True)


def _initialize_props_from_imported_planetka(scene):
    props = getattr(scene, "planetka", None) if scene else None
    if not props:
        return

    _sync_idprops_from_props(scene)
    _apply_fake_atmosphere_from_props(scene)


@persistent
def _planetka_load_post(_dummy):
    for scene in _iter_scenes():
        _sync_props_from_idprops(scene)
        migrate_scene(scene)
        _apply_fake_atmosphere_from_props(scene)
    _sync_logging_from_scenes()
    ensure_auto_resolve_service_running()


def create_temp_mesh(tiles, name="Planetka Earth Surface", collection_policy="inherit_old"):
    mesh_utils = _get_mesh_utils()
    if mesh_utils:
        return mesh_utils.create_temp_mesh_for_all_tiles(
            tiles,
            name=name,
            collection_policy=collection_policy,
        )
    return None


def warm_base_sphere_mesh_cache():
    mesh_utils = _get_mesh_utils()
    if mesh_utils and hasattr(mesh_utils, "ensure_base_sphere_mesh_cache"):
        return mesh_utils.ensure_base_sphere_mesh_cache()
    return None


def ensure_preview_object(parent_surface):
    mesh_utils = _get_mesh_utils()
    if mesh_utils and hasattr(mesh_utils, "ensure_preview_object"):
        return mesh_utils.ensure_preview_object(parent_surface)
    return None


def replace_tiles(
    tiles,
    material_name="Planetka Earth Material",
    force_remove_unused=False,
    allow_slot_shrink=True,
):
    shader_utils = _get_shader_utils()
    if shader_utils:
        return shader_utils.main(
            tiles,
            material_name=material_name,
            force_remove_datablocks=force_remove_unused,
            allow_slot_shrink=allow_slot_shrink,
        )
    return None


def remove_object_and_unused_mesh(obj):
    if obj is None:
        return
    mesh_data = getattr(obj, "data", None) if getattr(obj, "type", None) == 'MESH' else None
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing object %s", getattr(obj, "name", "<unknown>"), exc_info=True)
        return

    if mesh_data is None:
        return
    try:
        if int(getattr(mesh_data, "users", 0)) == 0:
            bpy.data.meshes.remove(mesh_data)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing unused mesh data", exc_info=True)


def delete_temp_meshes(keep_obj=None):
    for obj in list(getattr(bpy.data, "objects", ())):
        if obj is keep_obj:
            continue
        if obj.name.startswith("Earth Surface") or obj.name.startswith("Planetka Earth Surface"):
            remove_object_and_unused_mesh(obj)


def ensure_planetka_temp_collection():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return None
    root = scene.collection
    surface_collection = bpy.data.collections.get(SURFACE_COLLECTION_NAME)
    if surface_collection is None:
        surface_collection = bpy.data.collections.new(SURFACE_COLLECTION_NAME)
        root.children.link(surface_collection)
    elif SURFACE_COLLECTION_NAME not in root.children:
        try:
            root.children.link(surface_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
    return surface_collection


def cleanup_planetka_unused_data():
    counts = {
        "objects": 0,
        "meshes": 0,
        "images": 0,
        "materials": 0,
        "node_groups": 0,
    }

    keep_surface = get_earth_object()
    keep_preview = bpy.data.objects.get("Planetka Preview Object")
    for obj in list(getattr(bpy.data, "objects", ())):
        if obj in (keep_surface, keep_preview):
            continue
        name = str(getattr(obj, "name", ""))
        if not (
            name.startswith("Planetka Earth Surface")
            or name.startswith("Earth Surface")
            or name.startswith("Planetka Preview Object")
        ):
            continue
        remove_object_and_unused_mesh(obj)
        counts["objects"] += 1

    for mesh_data in list(getattr(bpy.data, "meshes", ())):
        name = str(getattr(mesh_data, "name", ""))
        if not (
            name.startswith("Planetka")
            or name.startswith("Earth Surface")
            or name.startswith("Planetka__ResolvedMeshCache")
        ):
            continue
        try:
            if int(getattr(mesh_data, "users", 0)) == 0:
                bpy.data.meshes.remove(mesh_data)
                counts["meshes"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing mesh %s", name, exc_info=True)

    image_prefixes = ("S2_", "EL_", "WT_", "PO_")
    for image in list(getattr(bpy.data, "images", ())):
        name = str(getattr(image, "name", ""))
        filepath = str(getattr(image, "filepath", "")).lower()
        looks_planetka = (
            name.startswith(image_prefixes)
            or "planetka" in name.lower()
            or "/s2/" in filepath
            or "/el/" in filepath
            or "/wt/" in filepath
            or "/po/" in filepath
            or "basic textures" in filepath
            or "fallback images" in filepath
        )
        if not looks_planetka:
            continue
        try:
            if int(getattr(image, "users", 0)) == 0:
                bpy.data.images.remove(image)
                counts["images"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing image %s", name, exc_info=True)

    for material in list(getattr(bpy.data, "materials", ())):
        name = str(getattr(material, "name", ""))
        if not name.startswith("Planetka"):
            continue
        try:
            if int(getattr(material, "users", 0)) == 0:
                bpy.data.materials.remove(material)
                counts["materials"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing material %s", name, exc_info=True)

    for node_group in list(getattr(bpy.data, "node_groups", ())):
        name = str(getattr(node_group, "name", ""))
        if not name.startswith("Planetka"):
            continue
        try:
            if int(getattr(node_group, "users", 0)) == 0:
                bpy.data.node_groups.remove(node_group)
                counts["node_groups"] += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka cleanup: failed removing node group %s", name, exc_info=True)

    return counts
