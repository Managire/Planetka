"""Runtime state and orchestration for Planetka.

Core responsibilities:
- sync Scene <-> Planetka properties
- coordinate background download jobs and resolve finalization
"""

import logging
import importlib
import math
import json
import os
import threading
import time

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

from .error_utils import PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS, PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .auth import get_authorized_headers
from .asset_builder import ensure_atmosphere_for_mode
from .diagnostics import write_realtime_view_diagnostics
from .planetka_runtime.mesh_lifecycle import (
    cleanup_planetka_unused_data,
    create_temp_mesh,
    delete_temp_meshes,
    ensure_planetka_temp_collection,
    ensure_preview_object,
    remove_object_and_unused_mesh,
    replace_tiles,
    warm_base_sphere_mesh_cache,
)
from .planetka_runtime.asset_cleanup import (
    _set_atmosphere_collection_enabled,
    _remove_object_and_unused_data_any_type,
    _remove_collection_if_exists,
    purge_disabled_atmosphere_and_cloud_assets,
    _remove_preview_assets,
    update_show_earth_preview,
    update_atmosphere_enabled,
)
from .planetka_runtime import navigation_runtime as _navigation_runtime
from .planetka_runtime import scene_sync as _scene_sync
from .planetka_runtime import view_telemetry as _view_telemetry
from .planetka_runtime import resolve as _resolve
from .planetka_runtime import resolve_state as _resolve_state
from .planetka_runtime.resolve_context import (
    ResolveDownloadContext,
    ResolveDownloadDeps,
    ResolveSettings,
    ResolveStateContext,
    ResolveStateDeps,
    ResolveSharedState,
)
from .planetka_runtime.view_telemetry_context import (
    ViewTelemetryContext,
    ViewTelemetryDeps,
    ViewTelemetryState,
)
from .planetka_runtime.navigation_runtime_context import (
    NavigationRuntimeContext,
    NavigationRuntimeDeps,
    NavigationRuntimeState,
)
from .planetka_runtime.handler_runtime_context import (
    HandlerRuntimeContext,
    HandlerRuntimeDeps,
    HandlerRuntimeState,
)
from .planetka_runtime import handler_runtime as _handler_runtime


logger = logging.getLogger(__name__)

ADD_EARTH_BUTTON_SCALE_X = 1.0
ADD_EARTH_BUTTON_SCALE_Y = 1.2
REFRESH_BUTTON_SCALE_X = 1.2
REFRESH_BUTTON_SCALE_Y = 1.6
REFRESH_BUTTON_ALERT = False

_NAV_FORCE_CAMERA_ONCE_KEY = "planetka_nav_force_camera_once"
_NAV_SYNC_ACTIVE_VIEW_ONCE_KEY = "planetka_nav_sync_active_view_once"

_IDPROP_SYNCING = False
_LOGGING_SYNCING = False
_FINAL_ANIMATION_RENDER_ACTIVE = False
_PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT = 0
_ATMOSPHERE_RENDER_ENGINE_MSGBUS_OWNER = object()

_SYNC_IDPROP_MAP = {
    "show_earth_preview": "planetka_show_earth_preview",
    "atmosphere_enabled": "planetka_atmosphere_enabled",
    "atmosphere_mode": "planetka_atmosphere_mode",
    "auto_switch_atmosphere": "planetka_auto_switch_atmosphere",
    "auto_switch_cloud_shaders": "planetka_auto_switch_cloud_shaders",
    "enable_global_clouds": "planetka_enable_global_clouds",
    "enable_local_clouds": "planetka_enable_local_clouds",
    "enable_vdb_clouds": "planetka_enable_vdb_clouds",
    "vdb_cloud_preset": "planetka_vdb_cloud_preset",
    "local_cloud_texture": "planetka_local_cloud_texture",
    "nav_longitude_deg": "planetka_nav_longitude_deg",
    "nav_latitude_deg": "planetka_nav_latitude_deg",
    "nav_altitude_km": "planetka_nav_altitude_km",
    "nav_azimuth_deg": "planetka_nav_azimuth_deg",
    "nav_tilt_deg": "planetka_nav_tilt_deg",
    "nav_roll_deg": "planetka_nav_roll_deg",
    "nav_focal_length_mm": "planetka_nav_focal_length_mm",
    "nav_custom_preset_altitude_km": "planetka_nav_custom_preset_altitude_km",
    "nav_city_search": "planetka_nav_city_search",
    "nav_saved_location_name": "planetka_nav_saved_location_name",
    "nav_saved_location_id": "planetka_nav_saved_location_id",
    "sunlight_longitude_deg": "planetka_sunlight_longitude_deg",
    "sunlight_seasonal_tilt_deg": "planetka_sunlight_seasonal_tilt_deg",
    "sunlight_strength": "planetka_sunlight_strength",
    "anim_camera_preset": "planetka_anim_camera_preset",
    "anim_frame_start": "planetka_anim_frame_start",
    "anim_frame_end": "planetka_anim_frame_end",
    "anim_camera_strength": "planetka_anim_camera_strength",
    "anim_motion_curve": "planetka_anim_motion_curve",
    "anim_end_altitude_km": "planetka_anim_end_altitude_km",
    "anim_orbit_degrees": "planetka_anim_orbit_degrees",
    "anim_circle_direction": "planetka_anim_circle_direction",
    "anim_zoom_rotate_degrees": "planetka_anim_zoom_rotate_degrees",
    "anim_prepare_max_segments": "planetka_anim_prepare_max_segments",
    "anim_prepare_max_textures_mb": "planetka_anim_prepare_max_textures_mb",
    "anim_ab_a_location": "planetka_anim_ab_a_location",
    "anim_ab_a_rotation": "planetka_anim_ab_a_rotation",
    "anim_ab_a_valid": "planetka_anim_ab_a_valid",
    "anim_ab_a_capture_frame": "planetka_anim_ab_a_capture_frame",
    "anim_ab_a_capture_timecode": "planetka_anim_ab_a_capture_timecode",
    "anim_ab_b_location": "planetka_anim_ab_b_location",
    "anim_ab_b_rotation": "planetka_anim_ab_b_rotation",
    "anim_ab_b_valid": "planetka_anim_ab_b_valid",
    "anim_ab_b_capture_frame": "planetka_anim_ab_b_capture_frame",
    "anim_ab_b_capture_timecode": "planetka_anim_ab_b_capture_timecode",
    "texture_quality_mode": "planetka_texture_quality_mode",
    "resolution_bias": "planetka_resolution_bias",
    "lock_resolve_during_animation": "planetka_lock_resolve_during_animation",
    "debug_logging": "planetka_debug_logging",
}
_NAVIGATION_SYNC_IDPROP_MAP = (
    ("nav_longitude_deg", "planetka_nav_longitude_deg"),
    ("nav_latitude_deg", "planetka_nav_latitude_deg"),
    ("nav_altitude_km", "planetka_nav_altitude_km"),
    ("nav_azimuth_deg", "planetka_nav_azimuth_deg"),
    ("nav_tilt_deg", "planetka_nav_tilt_deg"),
    ("nav_roll_deg", "planetka_nav_roll_deg"),
    ("nav_focal_length_mm", "planetka_nav_focal_length_mm"),
)
SURFACE_COLLECTION_NAME = "Planetka Earth Surface Collection"
_MESH_UTILS_MODULE = None
_SHADER_UTILS_MODULE = None
_OPERATORS_MODULE = None
_TILE_UTILS_MODULE = None
_STREAMING_UTILS_MODULE = None

_RESOLVE_IN_FLIGHT = False
_RENDER_JOB_ACTIVE = False
_RENDER_JOB_EPOCH = 0
_RENDER_JOB_LAST_ENDED_EPOCH = 0
CAMERA_INSIDE_EARTH_WARNING_KEY = "planetka_camera_inside_earth_warning"
_RENDER_JOB_LAST_CANCELLED_EPOCH = 0
_RENDER_JOB_LAST_ENDED_AT = 0.0
_RENDER_JOB_POST_END_GUARD_SEC = 8.0
_RENDER_JOB_LAST_PROGRESS_AT = 0.0
_RENDER_JOB_LAST_FRAME_WRITTEN_AT = 0.0
_RENDER_JOB_LAST_FRAME_WRITTEN = -1
_RESOLVE_DOWNLOAD_LOCK = threading.Lock()
_RESOLVE_DOWNLOAD_TIMER_RUNNING = False
_RESOLVE_DOWNLOAD_THREAD = None
_RESOLVE_DOWNLOAD_ACTIVE_JOB = None
_RESOLVE_DOWNLOAD_COMPLETED = None
_RESOLVE_DOWNLOAD_REQUEST_COUNTER = 0
_RESOLVE_DOWNLOAD_EPOCH = 0
_RESOLVE_DOWNLOAD_PUMP_INTERVAL_SEC = 0.5
_RESOLVE_DOWNLOAD_SCENE_WAIT_SEC = 1.5
_RESOLVE_DOWNLOAD_COMPLETED_MAX_AGE_SEC = 15.0
LAST_RESOLVE_TILE_COUNT_KEY = "planetka_last_manual_resolve_tile_count"
LAST_RESOLVE_DOWNLOADED_MB_KEY = "planetka_last_manual_resolve_downloaded_mb"
LAST_RESOLVE_TOTAL_SECONDS_KEY = "planetka_last_manual_resolve_total_seconds"
_VIEWPORT_OPT_LAST_SIGNATURE = {}
_SUNLIGHT_LAST_SIGNATURE = {}
_SUNLIGHT_OBJECT_NAME_CACHE = {}
_VIEWPORT_SCOPE_LAST = {}
_VIEWPORT_SCOPE_LAST_RESOLVE_TIME = {}
_LAST_REALTIME_TELEMETRY = {}
_COVERAGE_MAP = None
_R2_SOURCE_MODULE = None
_REAL_EARTH_RADIUS_M = 6371000.0
_MAX_TERRAIN_HEIGHT_M = 9000.0
_DATASET_MPP_BASE_D1 = 10.0
_LIVE_SAFETY_CAUTION_RATIO = 1.15
_LIVE_FALLBACK_MPP_M = 3600.0
_LIVE_Z_LEVELS = (1, 2, 4, 8, 15, 30, 60, 90, 180, 360)
_NAVIGATION_SHOT_UPDATE_PENDING = False
_NAVIGATION_SHOT_UPDATE_REENTRANT = False
_NAVIGATION_SHOT_SUSPEND_COUNT = 0
_NAVIGATION_USER_EDIT_LAST_TOUCH = 0.0
_NAV_CAMERA_CONTROL_LAST_SIGNATURE = {}
_NAV_CAMERA_CONTROL_SYNCING = False
_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT = 0
_NAV_CAMERA_CONTROL_SYNC_GRACE_SEC = 1.5
_SUNLIGHT_OBJECT_NAME = "Planetka Sunlight"
_SURFACE_GRADING_GROUP_NAME = "Planetka Surface Grading Group"
_RESOLVE_TRACE_ENABLED = False
_STATUS_NOTICE_KEYS = (
    "planetka_status_clip_auto_notice",
    "planetka_status_cache_notice",
    "planetka_status_radius_sync_notice",
)
_STATUS_NOTICE_CLEAR_SKIP_KEY = "planetka_status_notice_clear_skip_count"
_KEYED_RUNTIME_NAV_PROP_PATHS = (
    "planetka.nav_longitude_deg",
    "planetka.nav_latitude_deg",
    "planetka.nav_altitude_km",
    "planetka.nav_azimuth_deg",
    "planetka.nav_tilt_deg",
    "planetka.nav_roll_deg",
)
_KEYED_RUNTIME_FOCAL_PROP_PATHS = (
    "planetka.nav_focal_length_mm",
)
_KEYED_RUNTIME_SUN_PROP_PATHS = (
    "planetka.sunlight_longitude_deg",
    "planetka.sunlight_seasonal_tilt_deg",
    "planetka.sunlight_strength",
)
_KEYED_RUNTIME_ALL_PROP_PATHS = (
    _KEYED_RUNTIME_NAV_PROP_PATHS
    + _KEYED_RUNTIME_FOCAL_PROP_PATHS
    + _KEYED_RUNTIME_SUN_PROP_PATHS
)


ResolveDownloadJob = _resolve_state.ResolveDownloadJob


def _is_resolve_download_job(job):
    return _resolve_state._is_resolve_download_job(job)


def _job_field(job, name, default=None):
    return _resolve_state._job_field(job, name, default=default)


def _job_set_field(job, name, value):
    return _resolve_state._job_set_field(job, name, value)


def _build_resolve_download_job(*args, **kwargs):
    return _resolve_state._build_resolve_download_job(*args, ctx=_RESOLVE_STATE_CTX, **kwargs)


def _get_r2_source():
    global _R2_SOURCE_MODULE
    if _R2_SOURCE_MODULE is None:
        module_name = f"{__package__}.r2_source" if __package__ else "r2_source"
        try:
            _R2_SOURCE_MODULE = importlib.import_module(module_name)
        except ImportError:
            _R2_SOURCE_MODULE = False
    return _R2_SOURCE_MODULE or None


def _resolve_trace(message):
    if not bool(_RESOLVE_TRACE_ENABLED):
        return
    text = str(message or "").strip()
    if not text:
        return
    print(f"Planetka Resolve: {text}")


def _clear_status_notices(scene):
    return _scene_sync.clear_status_notices(
        scene,
        status_notice_clear_skip_key=_STATUS_NOTICE_CLEAR_SKIP_KEY,
        status_notice_keys=_STATUS_NOTICE_KEYS,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


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


def _get_operators_module():
    global _OPERATORS_MODULE
    if _OPERATORS_MODULE is None:
        module_name = f"{__package__}.operators" if __package__ else "operators"
        try:
            _OPERATORS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _OPERATORS_MODULE = False
    return _OPERATORS_MODULE or None


def _get_tile_utils():
    global _TILE_UTILS_MODULE
    if _TILE_UTILS_MODULE is None:
        module_name = f"{__package__}.tile_utils" if __package__ else "tile_utils"
        try:
            _TILE_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _TILE_UTILS_MODULE = False
    return _TILE_UTILS_MODULE or None


def _get_streaming_utils():
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
        try:
            coverage_module = importlib.import_module(module_name)
            _COVERAGE_MAP = getattr(coverage_module, "COVERAGE", {})
        except ImportError:
            _COVERAGE_MAP = {}
    return _COVERAGE_MAP or {}


def _iter_scenes():
    return _scene_sync.iter_scenes(bpy)


def _sync_idprops_from_props(scene, prop_names=None):
    global _IDPROP_SYNCING
    if _IDPROP_SYNCING:
        return
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return
    _IDPROP_SYNCING = True
    try:
        _scene_sync.sync_idprops_from_props(
            scene,
            props,
            sync_idprop_map=_SYNC_IDPROP_MAP,
            recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
            logger=logger,
            prop_names=prop_names,
        )
    finally:
        _IDPROP_SYNCING = False


def _sync_navigation_idprops_from_props(scene):
    global _IDPROP_SYNCING
    if _IDPROP_SYNCING:
        return
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return
    _IDPROP_SYNCING = True
    try:
        _scene_sync.sync_navigation_idprops_from_props(
            scene,
            props,
            navigation_sync_idprop_map=_NAVIGATION_SYNC_IDPROP_MAP,
            recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
            logger=logger,
        )
    finally:
        _IDPROP_SYNCING = False


def update_auto_switch_atmosphere(self, context):
    scene = getattr(context, "scene", None) if context else None
    if scene is not None:
        _sync_idprops_from_props(scene, ("auto_switch_atmosphere",))
        if bool(getattr(self, "auto_switch_atmosphere", True)):
            sync_atmosphere_mode_to_render_engine(scene)


def update_auto_switch_cloud_shaders(self, context):
    scene = getattr(context, "scene", None) if context else None
    if scene is not None:
        _sync_idprops_from_props(scene, ("auto_switch_cloud_shaders",))


def _on_render_engine_changed():
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    if scene is None:
        return
    try:
        sync_atmosphere_mode_to_render_engine(scene)
        from .clouds_local import sanitize_texture_based_cloud_image_assignments
        sanitize_texture_based_cloud_image_assignments(scene=scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed syncing atmosphere after render engine change", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed syncing atmosphere after render engine change", exc_info=True)


def register_atmosphere_render_engine_msgbus():
    clear_atmosphere_render_engine_msgbus()
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.RenderSettings, "engine"),
            owner=_ATMOSPHERE_RENDER_ENGINE_MSGBUS_OWNER,
            args=(),
            notify=_on_render_engine_changed,
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed registering atmosphere render-engine msgbus", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed registering atmosphere render-engine msgbus", exc_info=True)


def clear_atmosphere_render_engine_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_ATMOSPHERE_RENDER_ENGINE_MSGBUS_OWNER)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed clearing atmosphere render-engine msgbus", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed clearing atmosphere render-engine msgbus", exc_info=True)


def set_planetka_logging(enabled):
    level = logging.DEBUG if enabled else logging.INFO
    logger.setLevel(level)


def update_debug_logging(self, context):
    set_planetka_logging(bool(getattr(self, "debug_logging", False)))
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene, ("debug_logging",))


def _navigation_shot_update_timer():
    return _navigation_runtime.navigation_shot_update_timer(
        _NAVIGATION_RUNTIME_CTX,
    )


def _apply_navigation_shot_now():
    return _navigation_runtime.apply_navigation_shot_now(
        _NAVIGATION_RUNTIME_CTX,
    )


def request_next_navigation_apply_behavior(scene, *, force_camera_view=None, sync_active_view_when_not_camera=None):
    return _navigation_runtime.request_next_navigation_apply_behavior(
        _NAVIGATION_RUNTIME_CTX,
        scene,
        force_camera_view=force_camera_view,
        sync_active_view_when_not_camera=sync_active_view_when_not_camera,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


def suspend_navigation_shot_updates():
    return _navigation_runtime.suspend_navigation_shot_updates(_NAVIGATION_RUNTIME_CTX)


def resume_navigation_shot_updates():
    return _navigation_runtime.resume_navigation_shot_updates(_NAVIGATION_RUNTIME_CTX)


def suspend_navigation_camera_control_sync():
    return _navigation_runtime.suspend_navigation_camera_control_sync(_NAVIGATION_RUNTIME_CTX)


def resume_navigation_camera_control_sync():
    return _navigation_runtime.resume_navigation_camera_control_sync(_NAVIGATION_RUNTIME_CTX)


def is_navigation_or_camera_sync_suspended():
    return _navigation_runtime.is_navigation_or_camera_sync_suspended(_NAVIGATION_RUNTIME_CTX)


def suspend_property_update_side_effects():
    global _PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT
    _PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT = int(_PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT) + 1


def resume_property_update_side_effects():
    global _PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT
    _PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT = max(0, int(_PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT) - 1)


def is_property_update_side_effects_suspended():
    return int(_PROPERTY_UPDATE_SIDE_EFFECTS_SUSPEND_COUNT) > 0


def mark_navigation_camera_control_signature(scene=None):
    return _navigation_runtime.mark_navigation_camera_control_signature(
        _NAVIGATION_RUNTIME_CTX,
        scene,
    )


def _get_planetka_sunlight_object():
    return _navigation_runtime.get_planetka_sunlight_object(_NAVIGATION_RUNTIME_CTX)


def _apply_sunlight_from_props(scene):
    return _navigation_runtime.apply_sunlight_from_props(
        _NAVIGATION_RUNTIME_CTX,
        scene,
    )


def _apply_sunlight_strength_from_props(scene):
    return _navigation_runtime.apply_sunlight_strength_from_props(
        _NAVIGATION_RUNTIME_CTX,
        scene,
    )


def update_sunlight_controls(self, context):
    return _navigation_runtime.update_sunlight_controls(
        _NAVIGATION_RUNTIME_CTX,
        self,
        context,
    )


def update_sunlight_strength(self, context):
    return _navigation_runtime.update_sunlight_strength(
        _NAVIGATION_RUNTIME_CTX,
        self,
        context,
    )


def update_navigation_shot(self, context):
    return _navigation_runtime.update_navigation_shot(
        _NAVIGATION_RUNTIME_CTX,
        self,
        context,
    )


def update_navigation_focal_length(self, context):
    return _navigation_runtime.update_navigation_focal_length(
        _NAVIGATION_RUNTIME_CTX,
        self,
        context,
    )


def _is_animation_playing():
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False
    if not wm:
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


def _is_render_handler_job_active():
    # Reliable signal maintained by Planetka render handlers.
    if "_HANDLER_RUNTIME_CTX" in globals() and _HANDLER_RUNTIME_CTX is not None:
        try:
            return bool(_HANDLER_RUNTIME_CTX.state.render_job_active)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed reading handler render-job active state; using fallback flag", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed reading handler render-job active state; using fallback flag", exc_info=True)
    return bool(_RENDER_JOB_ACTIVE)


def _get_render_job_heartbeat():
    if "_HANDLER_RUNTIME_CTX" in globals() and _HANDLER_RUNTIME_CTX is not None:
        try:
            return dict(_handler_runtime.render_job_heartbeat(_HANDLER_RUNTIME_CTX) or {})
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return {}
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return {}
    return {
        "active": bool(_RENDER_JOB_ACTIVE),
        "epoch": int(_RENDER_JOB_EPOCH),
        "last_cancelled_epoch": int(_RENDER_JOB_LAST_CANCELLED_EPOCH),
        "last_progress_at": float(_RENDER_JOB_LAST_PROGRESS_AT or 0.0),
        "last_frame_written_at": float(_RENDER_JOB_LAST_FRAME_WRITTEN_AT or 0.0),
        "last_frame_written": int(_RENDER_JOB_LAST_FRAME_WRITTEN),
        "last_ended_at": float(_RENDER_JOB_LAST_ENDED_AT or 0.0),
    }


def _is_render_post_end_guard_active():
    guard_window_sec = float(max(0.0, _RENDER_JOB_POST_END_GUARD_SEC))
    if guard_window_sec <= 0.0:
        return False
    if "_HANDLER_RUNTIME_CTX" in globals() and _HANDLER_RUNTIME_CTX is not None:
        try:
            ended_at = float(getattr(_HANDLER_RUNTIME_CTX.state, "render_job_last_ended_at", 0.0) or 0.0)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            ended_at = 0.0
        except (RuntimeError, TypeError, ValueError, AttributeError):
            ended_at = 0.0
    else:
        ended_at = float(_RENDER_JOB_LAST_ENDED_AT or 0.0)
    if ended_at <= 0.0:
        return False
    return (time.monotonic() - ended_at) < guard_window_sec


def _is_render_job_active():
    if bool(_FINAL_ANIMATION_RENDER_ACTIVE):
        return True

    # bpy.app.is_job_running("RENDER") has been observed to get stuck True on some systems after F12
    # renders, which would permanently disable resolve. Track render state via handlers and
    # prefer that signal.
    if _is_render_handler_job_active():
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


def _is_resolve_render_guard_active():
    if _is_render_job_active():
        return True
    return _is_render_post_end_guard_active()


def set_final_animation_render_active(active=False):
    global _FINAL_ANIMATION_RENDER_ACTIVE
    _FINAL_ANIMATION_RENDER_ACTIVE = bool(active)
    try:
        _tag_view3d_redraw()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed tagging View3D redraw for render UI lock", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed tagging View3D redraw for render UI lock", exc_info=True)


def is_final_animation_render_active():
    return bool(_FINAL_ANIMATION_RENDER_ACTIVE)


def _clear_resolve_in_flight():
    global _RESOLVE_IN_FLIGHT
    _RESOLVE_IN_FLIGHT = False
    shared_state = globals().get("_RESOLVE_SHARED_STATE")
    if shared_state is not None:
        shared_state.in_flight = False


def _is_idprop_syncing():
    return bool(_IDPROP_SYNCING)


def _is_navigation_camera_control_syncing():
    if _NAVIGATION_RUNTIME_CTX is not None:
        return bool(_NAVIGATION_RUNTIME_CTX.state.nav_camera_control_syncing)
    return bool(_NAV_CAMERA_CONTROL_SYNCING)


def _get_navigation_camera_control_sync_suspend_count():
    if _NAVIGATION_RUNTIME_CTX is not None:
        return int(_NAVIGATION_RUNTIME_CTX.state.nav_camera_control_sync_suspend_count)
    return int(_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT)


def _get_navigation_user_edit_last_touch():
    if _NAVIGATION_RUNTIME_CTX is not None:
        return float(_NAVIGATION_RUNTIME_CTX.state.navigation_user_edit_last_touch)
    return float(_NAVIGATION_USER_EDIT_LAST_TOUCH)


def _reset_navigation_shot_runtime_state():
    if _NAVIGATION_RUNTIME_CTX is None:
        return
    _navigation_runtime.reset_navigation_shot_runtime_state(_NAVIGATION_RUNTIME_CTX)


def _reset_navigation_camera_control_runtime_state():
    if _NAVIGATION_RUNTIME_CTX is None:
        return
    _navigation_runtime.reset_navigation_camera_control_runtime_state(_NAVIGATION_RUNTIME_CTX)


def force_restore_navigation_adaptive_state():
    if _NAVIGATION_RUNTIME_CTX is None:
        return False
    return _navigation_runtime.force_restore_navigation_adaptive_state(_NAVIGATION_RUNTIME_CTX)


def _scene_key(scene):
    return _resolve_state._scene_key(scene)


def _scene_from_key(scene_id):
    return _resolve_state._scene_from_key(scene_id, _RESOLVE_STATE_CTX)


def _is_navigation_user_edit_active(scene=None):
    del scene
    return (time.monotonic() - float(_get_navigation_user_edit_last_touch())) < float(_NAV_CAMERA_CONTROL_SYNC_GRACE_SEC)


def mark_resolve_clean_after_resolve(scene):
    if scene is None:
        return
    try:
        _VIEWPORT_SCOPE_LAST_RESOLVE_TIME[_scene_key(scene)] = time.monotonic()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed marking resolve timestamp", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed marking resolve timestamp", exc_info=True)


def get_resolve_runtime_status(scene=None):
    return _resolve_state.get_resolve_runtime_status(scene=scene, ctx=_RESOLVE_STATE_CTX)


def get_camera_inside_earth_warning(scene=None):
    return _view_telemetry.get_camera_inside_earth_warning(scene, _VIEW_TELEMETRY_CTX)


def _clear_camera_inside_earth_warning(scene):
    return _view_telemetry.clear_camera_inside_earth_warning(scene, _VIEW_TELEMETRY_CTX)


def _set_camera_inside_earth_warning(scene, altitude_km=None):
    return _view_telemetry.set_camera_inside_earth_warning(scene, altitude_km=altitude_km, ctx=_VIEW_TELEMETRY_CTX)


def _resolve_scope_altitude_info(scene, scope_mode="AUTO"):
    return _view_telemetry.resolve_scope_altitude_info(scene, _VIEW_TELEMETRY_CTX, scope_mode=scope_mode)


def _camera_control_sync_signature(scene):
    return _navigation_runtime.camera_control_sync_signature(scene)


def _camera_signature(scene):
    return _view_telemetry.camera_signature(scene)


def _is_resolve_busy():
    return _resolve_state._is_resolve_busy(_RESOLVE_STATE_CTX)


def _normalize_texture_quality_mode(value):
    return _view_telemetry.normalize_texture_quality_mode(value)


def _enforce_texture_quality_mode(scene, requested_mode):
    return _view_telemetry.enforce_texture_quality_mode(scene, requested_mode, _VIEW_TELEMETRY_CTX)


def _output_resolution_signature(scene):
    return _view_telemetry.output_resolution_signature(scene, _VIEW_TELEMETRY_CTX)


def _handle_viewport_motion_optimization(scene, camera_signature):
    return _view_telemetry.handle_viewport_motion_optimization(scene, camera_signature, _VIEW_TELEMETRY_CTX)




def _iter_scene_animation_fcurves(scene):
    yield from _view_telemetry.iter_scene_animation_fcurves(scene, _VIEW_TELEMETRY_CTX)


def _scene_has_keyed_runtime_path(scene, accepted_paths):
    return _view_telemetry.scene_has_keyed_runtime_path(scene, accepted_paths, _VIEW_TELEMETRY_CTX)



def _sunlight_signature(scene):
    return _view_telemetry.sunlight_signature(scene, _VIEW_TELEMETRY_CTX)


def _handle_sunlight_motion_optimization(scene):
    return _view_telemetry.handle_sunlight_motion_optimization(scene, _VIEW_TELEMETRY_CTX)


def _earth_radius_blender_units(earth_obj):
    return _view_telemetry.earth_radius_blender_units(earth_obj)


def _intersect_ray_sphere_nearest(origin, direction, radius):
    return _view_telemetry.intersect_ray_sphere_nearest(origin, direction, radius)


def _realtime_view_camera_info(scene):
    return _view_telemetry.realtime_view_camera_info(scene, _VIEW_TELEMETRY_CTX)


def _active_camera_projection_info(scene):
    return _view_telemetry.active_camera_projection_info(scene)


def _tag_view3d_redraw():
    return _view_telemetry.tag_view3d_redraw(_VIEW_TELEMETRY_CTX)


def _tile_xy_for_lon_lat(lon_deg, lat_deg, z):
    return _view_telemetry.tile_xy_for_lon_lat(lon_deg, lat_deg, z)


def _best_available_mpp_for_lon_lat(lon_deg, lat_deg):
    return _view_telemetry.best_available_mpp_for_lon_lat(lon_deg, lat_deg, _VIEW_TELEMETRY_CTX)


def _safety_for_required_vs_available(required_mpp, available_mpp):
    return _view_telemetry.safety_for_required_vs_available(required_mpp, available_mpp, _VIEW_TELEMETRY_CTX)


def _update_realtime_telemetry(scene):
    return _view_telemetry.update_realtime_telemetry(scene, _VIEW_TELEMETRY_CTX)


def _canonical_tiles(tiles):
    return _view_telemetry.canonical_tiles(tiles)


def _estimate_download_bytes_for_visible_tiles(tiles, base_path, texture_quality_mode="PREVIEW"):
    return _view_telemetry.estimate_download_bytes_for_visible_tiles(
        tiles,
        base_path,
        _VIEW_TELEMETRY_CTX,
        texture_quality_mode=texture_quality_mode,
    )


def _last_resolved_tiles(scene):
    return _view_telemetry.last_resolved_tiles(scene, _VIEW_TELEMETRY_CTX)


def start_resolve_download(*args, **kwargs):
    return _resolve.start_resolve_download(*args, **kwargs)


def _mark_manual_resolve_error(*args, **kwargs):
    return _resolve._mark_manual_resolve_error(*args, **kwargs)


def _read_scene_last_resolve_error(*args, **kwargs):
    return _resolve._read_scene_last_resolve_error(*args, **kwargs)


def _store_resolve_summary(*args, **kwargs):
    return _resolve._store_resolve_summary(*args, **kwargs)


def _write_last_resolve_summary(*args, **kwargs):
    return _resolve._write_last_resolve_summary(*args, **kwargs)


def _resolve_pump_timer(*args, **kwargs):
    return _resolve._resolve_pump_timer(*args, **kwargs)


def stop_resolve(*args, **kwargs):
    return _resolve.stop_resolve(*args, **kwargs)


def _build_view_telemetry_context():
    deps = ViewTelemetryDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        import_recoverable_exceptions=PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS,
        get_prefs=get_prefs,
        write_realtime_view_diagnostics=write_realtime_view_diagnostics,
        camera_inside_earth_warning_key=CAMERA_INSIDE_EARTH_WARNING_KEY,
        scene_key=_scene_key,
        is_render_job_active=_is_render_job_active,
        is_animation_playing=_is_animation_playing,
        get_earth_object=get_earth_object,
        get_tile_utils=_get_tile_utils,
        get_streaming_utils=_get_streaming_utils,
        get_coverage_map=_get_coverage_map,
        normalize_texture_quality_mode=_normalize_texture_quality_mode,
        get_resolve_in_flight=lambda: bool(_RESOLVE_SHARED_STATE.in_flight),
        sunlight_object_name=_SUNLIGHT_OBJECT_NAME,
        monotonic=time.monotonic,
        real_earth_radius_m=_REAL_EARTH_RADIUS_M,
        max_terrain_height_m=_MAX_TERRAIN_HEIGHT_M,
        dataset_mpp_base_d1=_DATASET_MPP_BASE_D1,
        live_safety_caution_ratio=_LIVE_SAFETY_CAUTION_RATIO,
        live_fallback_mpp_m=_LIVE_FALLBACK_MPP_M,
        live_z_levels=_LIVE_Z_LEVELS,
    )
    state = ViewTelemetryState(
        viewport_opt_last_signature=_VIEWPORT_OPT_LAST_SIGNATURE,
        sunlight_last_signature=_SUNLIGHT_LAST_SIGNATURE,
        sunlight_object_name_cache=_SUNLIGHT_OBJECT_NAME_CACHE,
        last_realtime_telemetry=_LAST_REALTIME_TELEMETRY,
    )
    return ViewTelemetryContext(
        deps=deps,
        state=state,
    )


def _build_navigation_runtime_context():
    deps = NavigationRuntimeDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        scene_key=_scene_key,
        camera_control_sync_signature=_camera_control_sync_signature,
        get_earth_object=get_earth_object,
        is_idprop_syncing=_is_idprop_syncing,
        is_camera_control_syncing=_is_navigation_camera_control_syncing,
        get_camera_control_sync_suspend_count=_get_navigation_camera_control_sync_suspend_count,
        get_operators_module=_get_operators_module,
        nav_force_camera_once_key=_NAV_FORCE_CAMERA_ONCE_KEY,
        nav_sync_active_view_once_key=_NAV_SYNC_ACTIVE_VIEW_ONCE_KEY,
        sunlight_object_name=_SUNLIGHT_OBJECT_NAME,
        sync_idprops_from_props=_sync_idprops_from_props,
        sync_navigation_idprops_from_props=_sync_navigation_idprops_from_props,
        suspend_navigation_shot_updates=suspend_navigation_shot_updates,
        resume_navigation_shot_updates=resume_navigation_shot_updates,
    )
    state = NavigationRuntimeState(
        nav_camera_control_last_signature=_NAV_CAMERA_CONTROL_LAST_SIGNATURE,
        nav_camera_control_syncing=_NAV_CAMERA_CONTROL_SYNCING,
        nav_camera_control_sync_suspend_count=_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT,
        navigation_shot_update_pending=_NAVIGATION_SHOT_UPDATE_PENDING,
        navigation_shot_update_reentrant=_NAVIGATION_SHOT_UPDATE_REENTRANT,
        navigation_shot_suspend_count=_NAVIGATION_SHOT_SUSPEND_COUNT,
        navigation_user_edit_last_touch=_NAVIGATION_USER_EDIT_LAST_TOUCH,
    )
    return NavigationRuntimeContext(
        deps=deps,
        state=state,
    )


def _build_handler_runtime_context():
    deps = HandlerRuntimeDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        import_recoverable_exceptions=PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS,
        clear_resolve_in_flight=_clear_resolve_in_flight,
        reset_navigation_shot_runtime_state=_reset_navigation_shot_runtime_state,
        reset_navigation_camera_control_runtime_state=_reset_navigation_camera_control_runtime_state,
        iter_scenes=_iter_scenes,
        set_planetka_logging=set_planetka_logging,
        sync_idprops_from_props=_sync_idprops_from_props,
        get_earth_object=get_earth_object,
        ensure_atmosphere_for_mode=ensure_atmosphere_for_mode,
    )
    state = HandlerRuntimeState(
        render_job_active=_RENDER_JOB_ACTIVE,
        render_job_epoch=_RENDER_JOB_EPOCH,
        render_job_last_ended_epoch=_RENDER_JOB_LAST_ENDED_EPOCH,
        render_job_last_ended_at=_RENDER_JOB_LAST_ENDED_AT,
        render_job_last_cancelled_epoch=_RENDER_JOB_LAST_CANCELLED_EPOCH,
        render_job_last_progress_at=_RENDER_JOB_LAST_PROGRESS_AT,
        render_job_last_frame_written_at=_RENDER_JOB_LAST_FRAME_WRITTEN_AT,
        render_job_last_frame_written=_RENDER_JOB_LAST_FRAME_WRITTEN,
        logging_syncing=_LOGGING_SYNCING,
    )
    return HandlerRuntimeContext(
        deps=deps,
        state=state,
    )


def recover_post_render_state(scene=None, cancelled=False):
    return _handler_runtime.recover_post_render_state(scene=scene, cancelled=cancelled, ctx=_HANDLER_RUNTIME_CTX)


def mark_render_job_started(scene=None):
    return _handler_runtime.mark_render_job_started(scene=scene, ctx=_HANDLER_RUNTIME_CTX)


def mark_render_job_progress(scene=None, frame_written=False):
    return _handler_runtime.mark_render_job_progress(
        scene=scene,
        frame_written=bool(frame_written),
        ctx=_HANDLER_RUNTIME_CTX,
    )


def _sync_logging_from_scenes():
    return _handler_runtime.sync_logging_from_scenes(_HANDLER_RUNTIME_CTX)


def _initialize_props_from_imported_planetka(scene):
    return _handler_runtime.initialize_props_from_imported_planetka(scene, _HANDLER_RUNTIME_CTX)


def sync_atmosphere_mode_to_render_engine(scene=None):
    return _handler_runtime.sync_atmosphere_mode_to_render_engine(scene, _HANDLER_RUNTIME_CTX)


@persistent
def _planetka_load_post(_dummy):
    result = _handler_runtime.load_post(_dummy, _HANDLER_RUNTIME_CTX)
    try:
        register_atmosphere_render_engine_msgbus()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed re-registering atmosphere render-engine msgbus after file load", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed re-registering atmosphere render-engine msgbus after file load", exc_info=True)
    try:
        bpy.app.timers.register(_detach_planetka_camera_after_load_timer, first_interval=0.1)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed scheduling Planetka Camera detach after file load", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed scheduling Planetka Camera detach after file load", exc_info=True)
    try:
        from .clouds_local import sanitize_texture_based_cloud_image_assignments
        sanitize_texture_based_cloud_image_assignments(scene=getattr(bpy.context, "scene", None))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed sanitizing texture-based clouds after file load", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed sanitizing texture-based clouds after file load", exc_info=True)
    try:
        from .shader_utils import sanitize_missing_planetka_texture_images
        sanitize_missing_planetka_texture_images()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed sanitizing missing Earth texture images after file load", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
        logger.debug("Planetka: failed sanitizing missing Earth texture images after file load", exc_info=True)
    try:
        sync_atmosphere_mode_to_render_engine(getattr(bpy.context, "scene", None))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed syncing atmosphere after file load", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed syncing atmosphere after file load", exc_info=True)
    return result


def _detach_planetka_camera_after_load_timer():
    try:
        from .planetka_ops.earth_lifecycle_helpers import detach_planetka_camera_from_root
        detach_planetka_camera_from_root(scene=getattr(bpy.context, "scene", None))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed detaching Planetka Camera after file load", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
        logger.debug("Planetka: failed detaching Planetka Camera after file load", exc_info=True)
    return None


def _build_resolve_contexts():
    settings = ResolveSettings(
        download_pump_interval_sec=_RESOLVE_DOWNLOAD_PUMP_INTERVAL_SEC,
        download_scene_wait_sec=_RESOLVE_DOWNLOAD_SCENE_WAIT_SEC,
        download_completed_max_age_sec=_RESOLVE_DOWNLOAD_COMPLETED_MAX_AGE_SEC,
    )
    shared_state = ResolveSharedState(
        in_flight=_RESOLVE_IN_FLIGHT,
        download_timer_running=_RESOLVE_DOWNLOAD_TIMER_RUNNING,
        download_thread=_RESOLVE_DOWNLOAD_THREAD,
        download_active_job=_RESOLVE_DOWNLOAD_ACTIVE_JOB,
        download_completed=_RESOLVE_DOWNLOAD_COMPLETED,
        download_request_counter=_RESOLVE_DOWNLOAD_REQUEST_COUNTER,
        download_epoch=_RESOLVE_DOWNLOAD_EPOCH,
        download_lock=_RESOLVE_DOWNLOAD_LOCK,
    )
    download_deps = ResolveDownloadDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        resolve_trace=_resolve_trace,
        get_prefs=get_prefs,
        get_authorized_headers=get_authorized_headers,
        get_streaming_utils=_get_streaming_utils,
        clear_status_notices=_clear_status_notices,
        scene_key=_scene_key,
        scene_from_key=_scene_from_key,
        build_resolve_download_job=_build_resolve_download_job,
        is_resolve_download_job=_is_resolve_download_job,
        job_field=_job_field,
        job_set_field=_job_set_field,
        normalize_texture_quality_mode=_normalize_texture_quality_mode,
        camera_signature=_camera_signature,
        output_resolution_signature=_output_resolution_signature,
        canonical_tiles=_canonical_tiles,
        is_render_job_active=_is_resolve_render_guard_active,
        is_animation_playing=_is_animation_playing,
        estimate_download_bytes_for_visible_tiles=_estimate_download_bytes_for_visible_tiles,
        tag_view3d_redraw=_tag_view3d_redraw,
        last_resolve_tile_count_key=LAST_RESOLVE_TILE_COUNT_KEY,
        last_resolve_downloaded_mb_key=LAST_RESOLVE_DOWNLOADED_MB_KEY,
        last_resolve_total_seconds_key=LAST_RESOLVE_TOTAL_SECONDS_KEY,
    )
    state_deps = ResolveStateDeps(
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        iter_scenes=_iter_scenes,
        normalize_texture_quality_mode=_normalize_texture_quality_mode,
        get_r2_source=_get_r2_source,
        is_render_job_active=_is_resolve_render_guard_active,
    )
    return (
        settings,
        shared_state,
        ResolveDownloadContext(
            deps=download_deps,
            state=shared_state,
            settings=settings,
        ),
        ResolveStateContext(
            deps=state_deps,
            state=shared_state,
        ),
    )


_VIEW_TELEMETRY_CTX = _build_view_telemetry_context()
_NAVIGATION_RUNTIME_CTX = _build_navigation_runtime_context()
_HANDLER_RUNTIME_CTX = _build_handler_runtime_context()

# state.py remains the owner of the singleton view-telemetry context; the
# runtime module receives it explicitly instead of pulling facade globals.
_view_telemetry._VIEW_TELEMETRY_CTX = _VIEW_TELEMETRY_CTX
_navigation_runtime._NAVIGATION_RUNTIME_CTX = _NAVIGATION_RUNTIME_CTX
_handler_runtime._HANDLER_RUNTIME_CTX = _HANDLER_RUNTIME_CTX


(
    _RESOLVE_SETTINGS,
    _RESOLVE_SHARED_STATE,
    _RESOLVE_DOWNLOAD_CTX,
    _RESOLVE_STATE_CTX,
) = _build_resolve_contexts()

# state.py remains the owner of the singleton resolve contexts; the runtime
# modules receive them explicitly instead of pulling facade globals.
_resolve._RESOLVE_DOWNLOAD_CTX = _RESOLVE_DOWNLOAD_CTX
_resolve_state._RESOLVE_STATE_CTX = _RESOLVE_STATE_CTX
