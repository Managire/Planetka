"""Runtime state and orchestration for Planetka.

Core responsibilities:
- sync Scene <-> Planetka properties
- react to camera/navigation/sunlight changes
- schedule auto-resolve triggers
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
from .planetka_runtime import cache_recovery as _cache_recovery
from .planetka_runtime import navigation_runtime as _navigation_runtime
from .planetka_runtime import scene_sync as _scene_sync
from .planetka_runtime import view_telemetry as _view_telemetry
from .planetka_runtime import auto_resolve_pipeline as _auto_resolve_pipeline
from .planetka_runtime import auto_resolve_state as _auto_resolve_state
from .planetka_runtime.auto_resolve_context import (
    AutoResolveDecisionContext,
    AutoResolveDecisionDeps,
    AutoResolveDownloadContext,
    AutoResolveDownloadDeps,
    AutoResolveNonCriticalContext,
    AutoResolveNonCriticalDeps,
    AutoResolveSettings,
    AutoResolveSharedState,
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

_SYNC_IDPROP_MAP = {
    "viewport_opt_suspend_subdivision": "planetka_viewport_opt_suspend_subdivision",
    "viewport_opt_subdivision_restore_delay_sec": "planetka_viewport_opt_subdivision_restore_delay_sec",
    "viewport_opt_active_view_coarse_textures": "planetka_viewport_opt_active_view_coarse_textures",
    "show_earth_preview": "planetka_show_earth_preview",
    "atmosphere_enabled": "planetka_atmosphere_enabled",
    "enable_global_clouds": "planetka_enable_global_clouds",
    "enable_local_clouds": "planetka_enable_local_clouds",
    "enable_vdb_clouds": "planetka_enable_vdb_clouds",
    "view_cloud_subdivision": "planetka_view_cloud_subdivision",
    "local_cloud_texture": "planetka_local_cloud_texture",
    "vdb_cloud_file": "planetka_vdb_cloud_file",
    "auto_resolve": "planetka_auto_resolve",
    "auto_resolve_idle_sec": "planetka_auto_resolve_idle_sec",
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
SURFACE_COLLECTION_NAME = "Planetka - Earth Surface Collection"
_MESH_UTILS_MODULE = None
_SHADER_UTILS_MODULE = None
_OPERATORS_MODULE = None
_LEGACY_SCENE_IDPROPS = (
    "planetka_view_elevation",
    "planetka_sampling_grid_density",
    "planetka_mesh_expansion",
    "planetka_auto_resolve_interval_sec",
    "planetka_auto_resolve_active_view",
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
    "planetka_render_engine_optimization",
)
_TILE_UTILS_MODULE = None
_STREAMING_UTILS_MODULE = None

AUTO_RESOLVE_RETRY_DELAY_SEC = 0.25
AUTO_RESOLVE_MIN_INTERVAL_SEC_DEFAULT = 1.0
AUTO_RESOLVE_IDLE_SEC_DEFAULT = 0.5
_AUTO_RESOLVE_TIMER_RUNNING = False
_AUTO_RESOLVE_IN_FLIGHT = False
_RENDER_JOB_ACTIVE = False
_RENDER_JOB_EPOCH = 0
_RENDER_JOB_LAST_ENDED_EPOCH = 0
CAMERA_INSIDE_EARTH_WARNING_KEY = "planetka_camera_inside_earth_warning"
_RENDER_JOB_LAST_CANCELLED_EPOCH = 0
_AUTO_RESOLVE_NEXT_DUE_TIME = {}
_AUTO_RESOLVE_LAST_CAMERA_SIGNATURE = {}
_AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE = {}
_AUTO_RESOLVE_LAST_CHANGE_TIME = {}
_AUTO_RESOLVE_LAST_RESOLVE_TIME = {}
_AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE = {}
_AUTO_RESOLVE_PENDING_OUTPUT_CHANGE = {}
_AUTO_RESOLVE_TRIGGER_LAST_SIGNATURE = {}
_AUTO_RESOLVE_DOWNLOAD_LOCK = threading.Lock()
_AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = False
_AUTO_RESOLVE_DOWNLOAD_THREAD = None
_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB = None
_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB = None
_AUTO_RESOLVE_DOWNLOAD_COMPLETED = None
_AUTO_RESOLVE_DOWNLOAD_REQUEST_COUNTER = 0
_AUTO_RESOLVE_DOWNLOAD_EPOCH = 0
_AUTO_RESOLVE_DOWNLOAD_PUMP_INTERVAL_SEC = 0.2
_AUTO_RESOLVE_DOWNLOAD_SCENE_WAIT_SEC = 1.5
_AUTO_RESOLVE_DOWNLOAD_COMPLETED_MAX_AGE_SEC = 15.0
_AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
_AUTO_RESOLVE_NONCRITICAL_INTERVAL_SEC = 0.25
_AUTO_RESOLVE_NONCRITICAL_PENDING = {}
_AUTO_RESOLVE_SIZE_ESTIMATE_LAST_SIGNATURE = {}
LAST_RESOLVE_TILE_COUNT_KEY = "planetka_last_manual_resolve_tile_count"
LAST_RESOLVE_DOWNLOADED_MB_KEY = "planetka_last_manual_resolve_downloaded_mb"
LAST_RESOLVE_DOWNLOADED_GB_KEY = "planetka_last_manual_resolve_downloaded_gb"
LAST_RESOLVE_TOTAL_SECONDS_KEY = "planetka_last_manual_resolve_total_seconds"
RESOLVE_ESTIMATE_FULL_BYTES_KEY = "planetka_resolve_estimate_full_bytes"
RESOLVE_ESTIMATE_BALANCED_BYTES_KEY = "planetka_resolve_estimate_balanced_bytes"
RESOLVE_ESTIMATE_PREVIEW_BYTES_KEY = "planetka_resolve_estimate_preview_bytes"
_VIEWPORT_OPT_LAST_SIGNATURE = {}
_SUNLIGHT_LAST_SIGNATURE = {}
_SUNLIGHT_OBJECT_NAME_CACHE = {}
_VIEWPORT_SCOPE_LAST = {}
_VIEWPORT_SCOPE_LAST_RESOLVE_TIME = {}
_LAST_REALTIME_TELEMETRY = {}
_TIMELINE_LAST_SIGNATURE = {}
_FRAME_KEYED_RUNTIME_LAST_SIGNATURE = {}
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
_NAVIGATION_ADAPTIVE_SUSPENDED = None
_NAVIGATION_ADAPTIVE_LAST_TOUCH = 0.0
_NAVIGATION_ADAPTIVE_TIMER_RUNNING = False
_NAVIGATION_ADAPTIVE_IDLE_SEC = 0.5
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
    "planetka_status_bg_auto_black_notice",
    "planetka_status_clip_auto_notice",
    "planetka_status_cache_notice",
)
_STATUS_NOTICE_CLEAR_SKIP_KEY = "planetka_status_notice_clear_skip_count"
ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY = "planetka_ui_account_default_collapsed"
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


SceneAutoResolveState = _auto_resolve_state.SceneAutoResolveState
AutoResolveDownloadJob = _auto_resolve_state.AutoResolveDownloadJob


def _is_auto_resolve_download_job(job):
    return _auto_resolve_state._is_auto_resolve_download_job(job)


def _job_field(job, name, default=None):
    return _auto_resolve_state._job_field(job, name, default=default)


def _job_set_field(job, name, value):
    return _auto_resolve_state._job_set_field(job, name, value)


def _build_auto_resolve_download_job(*args, **kwargs):
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state._build_auto_resolve_download_job(*args, **kwargs)


def _get_r2_source():
    global _R2_SOURCE_MODULE
    if _R2_SOURCE_MODULE is None:
        module_name = f"{__package__}.r2_source" if __package__ else "r2_source"
        try:
            _R2_SOURCE_MODULE = importlib.import_module(module_name)
        except ImportError:
            _R2_SOURCE_MODULE = False
    return _R2_SOURCE_MODULE or None


def self_heal_missing_cache_images_for_render(scene=None):
    return _cache_recovery.self_heal_missing_cache_images_for_render(
        scene,
        get_prefs=get_prefs,
        get_r2_source=_get_r2_source,
    )


def _recover_missing_cache_image_paths_to_fallback():
    return _cache_recovery.recover_missing_cache_image_paths_to_fallback(_get_r2_source)


def _queue_manual_resolve_download_for_scene(scene):
    return _cache_recovery.queue_manual_resolve_download_for_scene(
        scene,
        get_earth_object=get_earth_object,
    )


def _schedule_load_recovery_resolve(scene):
    return _cache_recovery.schedule_load_recovery_resolve(
        scene,
        queue_manual_resolve_download_for_scene=_queue_manual_resolve_download_for_scene,
    )


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


def _active_view_signature():
    return _view_telemetry.active_view_signature(_VIEW_TELEMETRY_CTX)


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


def _sync_props_from_idprops(scene):
    global _IDPROP_SYNCING
    if _IDPROP_SYNCING:
        return
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return
    _IDPROP_SYNCING = True
    try:
        _scene_sync.sync_props_from_idprops(
            scene,
            props,
            sync_idprop_map=_SYNC_IDPROP_MAP,
            recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
            logger=logger,
        )
    finally:
        _IDPROP_SYNCING = False


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
        globals(),
        bpy=bpy,
        get_earth_object=get_earth_object,
        apply_navigation_shot_now=_apply_navigation_shot_now,
    )


def _apply_navigation_shot_now():
    return _navigation_runtime.apply_navigation_shot_now(
        globals(),
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
        get_earth_object=get_earth_object,
    )


def request_next_navigation_apply_behavior(scene, *, force_camera_view=None, sync_active_view_when_not_camera=None):
    return _navigation_runtime.request_next_navigation_apply_behavior(
        globals(),
        scene,
        force_camera_view=force_camera_view,
        sync_active_view_when_not_camera=sync_active_view_when_not_camera,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


def _resolve_navigation_adaptive_modifier():
    return _navigation_runtime.resolve_navigation_adaptive_modifier(get_earth_object=get_earth_object)


def _navigation_adaptive_restore_timer():
    return _navigation_runtime.navigation_adaptive_restore_timer(
        globals(),
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


def _force_restore_navigation_adaptive_state():
    return _navigation_runtime.force_restore_navigation_adaptive_state(
        globals(),
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


def _suspend_adaptive_viewport_during_navigation(scene):
    return _navigation_runtime.suspend_adaptive_viewport_during_navigation(
        globals(),
        scene,
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
        resolve_navigation_adaptive_modifier=_resolve_navigation_adaptive_modifier,
        force_restore_navigation_adaptive_state=_force_restore_navigation_adaptive_state,
        navigation_adaptive_restore_timer=_navigation_adaptive_restore_timer,
    )


def suspend_navigation_shot_updates():
    return _navigation_runtime.suspend_navigation_shot_updates(globals())


def resume_navigation_shot_updates():
    return _navigation_runtime.resume_navigation_shot_updates(globals())


def suspend_navigation_camera_control_sync():
    return _navigation_runtime.suspend_navigation_camera_control_sync(globals())


def resume_navigation_camera_control_sync():
    return _navigation_runtime.resume_navigation_camera_control_sync(globals())


def is_navigation_or_camera_sync_suspended():
    return _navigation_runtime.is_navigation_or_camera_sync_suspended(globals())


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
    globals()["_navigation_shot_update_timer_wrapper"] = _navigation_shot_update_timer
    return _navigation_runtime.update_navigation_shot(
        globals(),
        self,
        context,
        sync_navigation_idprops_from_props=_sync_navigation_idprops_from_props,
        suspend_adaptive_viewport_during_navigation=_suspend_adaptive_viewport_during_navigation,
        request_auto_resolve=request_auto_resolve,
        apply_navigation_shot_now=_apply_navigation_shot_now,
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
    )


def update_navigation_focal_length(self, context):
    return _navigation_runtime.update_navigation_focal_length(
        globals(),
        self,
        context,
        sync_navigation_idprops_from_props=_sync_navigation_idprops_from_props,
        suspend_adaptive_viewport_during_navigation=_suspend_adaptive_viewport_during_navigation,
        request_auto_resolve=request_auto_resolve,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
    )


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
    return _auto_resolve_state._scene_key(scene)


def _scene_from_key(scene_id):
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state._scene_from_key(scene_id)


def _coerce_scene_id(scene_or_id):
    return _auto_resolve_state._coerce_scene_id(scene_or_id)


def _set_scene_auto_resolve_map_entry(target_map, scene_id, value):
    return _auto_resolve_state._set_scene_auto_resolve_map_entry(target_map, scene_id, value)


def _read_scene_auto_resolve_state(scene_or_id):
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state._read_scene_auto_resolve_state(scene_or_id)


def _write_scene_auto_resolve_state(state):
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state._write_scene_auto_resolve_state(state)


def _make_depsgraph_trigger_signature(scene):
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state._make_depsgraph_trigger_signature(scene)


def _depsgraph_trigger_output_signature(signature):
    return _auto_resolve_state._depsgraph_trigger_output_signature(signature)


def _mark_auto_resolve_from_depsgraph_trigger(scene, trigger_signature):
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state._mark_auto_resolve_from_depsgraph_trigger(scene, trigger_signature)


def get_resolve_runtime_status(scene=None):
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state.get_resolve_runtime_status(scene=scene)


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


def _sync_navigation_controls_from_scene_camera(scene):
    return _navigation_runtime.sync_navigation_controls_from_scene_camera(
        globals(),
        scene,
        get_earth_object=get_earth_object,
        scene_key=_scene_key,
        get_operators_module=_get_operators_module,
        suspend_navigation_shot_updates=suspend_navigation_shot_updates,
        resume_navigation_shot_updates=resume_navigation_shot_updates,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


def _camera_signature(scene):
    return _view_telemetry.camera_signature(scene)


def _is_resolve_pipeline_busy():
    _auto_resolve_state.configure(globals())
    return _auto_resolve_state._is_resolve_pipeline_busy()


def _normalize_texture_quality_mode(value):
    return _view_telemetry.normalize_texture_quality_mode(value)


def _enforce_texture_quality_mode_for_account(scene, requested_mode):
    return _view_telemetry.enforce_texture_quality_mode_for_account(scene, requested_mode, _VIEW_TELEMETRY_CTX)


def _output_resolution_signature(scene):
    return _view_telemetry.output_resolution_signature(scene, _VIEW_TELEMETRY_CTX)


def _current_view_scope(scene):
    return _view_telemetry.current_view_scope(scene, _VIEW_TELEMETRY_CTX)


def _auto_resolve_scope_mode(scene):
    return _view_telemetry.auto_resolve_scope_mode(scene, _VIEW_TELEMETRY_CTX)


def _handle_viewport_motion_optimization(scene, camera_signature):
    return _view_telemetry.handle_viewport_motion_optimization(scene, camera_signature, _VIEW_TELEMETRY_CTX)


def _timeline_signature(scene):
    return _view_telemetry.timeline_signature(scene)


def _keyed_runtime_signature(scene):
    return _view_telemetry.keyed_runtime_signature(scene)


def _iter_scene_animation_fcurves(scene):
    yield from _view_telemetry.iter_scene_animation_fcurves(scene, _VIEW_TELEMETRY_CTX)


def _scene_has_keyed_runtime_path(scene, accepted_paths):
    return _view_telemetry.scene_has_keyed_runtime_path(scene, accepted_paths, _VIEW_TELEMETRY_CTX)


def _handle_timeline_motion_optimization(scene):
    return _view_telemetry.handle_timeline_motion_optimization(scene, _VIEW_TELEMETRY_CTX)


def _sunlight_signature(scene):
    return _view_telemetry.sunlight_signature(scene, _VIEW_TELEMETRY_CTX)


def _handle_sunlight_motion_optimization(scene):
    return _view_telemetry.handle_sunlight_motion_optimization(scene, _VIEW_TELEMETRY_CTX)


def _handle_view_scope_quality_transition(scene):
    return _view_telemetry.handle_view_scope_quality_transition(scene, _VIEW_TELEMETRY_CTX)


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


def _clear_resolve_size_estimates(scene):
    return _view_telemetry.clear_resolve_size_estimates(scene, _VIEW_TELEMETRY_CTX)


def _estimate_download_bytes_for_visible_tiles(tiles, base_path, texture_quality_mode="PREVIEW"):
    return _view_telemetry.estimate_download_bytes_for_visible_tiles(
        tiles,
        base_path,
        _VIEW_TELEMETRY_CTX,
        texture_quality_mode=texture_quality_mode,
    )


def update_resolve_size_estimates(scene, scope_mode="CAMERA", base_path="", full_tiles_override=None):
    return _view_telemetry.update_resolve_size_estimates(
        scene,
        _VIEW_TELEMETRY_CTX,
        scope_mode=scope_mode,
        base_path=base_path,
        full_tiles_override=full_tiles_override,
    )


def get_resolve_size_estimates(scene=None):
    return _view_telemetry.get_resolve_size_estimates(scene=scene, runtime=_VIEW_TELEMETRY_CTX)


def _last_resolved_tiles(scene):
    return _view_telemetry.last_resolved_tiles(scene, _VIEW_TELEMETRY_CTX)


def _mark_auto_resolve_dirty(*args, **kwargs):
    return _auto_resolve_pipeline._mark_auto_resolve_dirty(*args, **kwargs)


def _auto_resolve_idle_seconds(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_idle_seconds(*args, **kwargs)


def _is_navigation_user_edit_active(*args, **kwargs):
    return _auto_resolve_pipeline._is_navigation_user_edit_active(*args, **kwargs)


def _active_view_monitor_interval_seconds(*args, **kwargs):
    return _auto_resolve_pipeline._active_view_monitor_interval_seconds(*args, **kwargs)


def _arm_auto_resolve_timer(*args, **kwargs):
    return _auto_resolve_pipeline._arm_auto_resolve_timer(*args, **kwargs)


def _auto_resolve_download_job_signature(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_download_job_signature(*args, **kwargs)


def _arm_auto_resolve_download_timer(*args, **kwargs):
    return _auto_resolve_pipeline._arm_auto_resolve_download_timer(*args, **kwargs)


def _start_auto_resolve_download_thread(*args, **kwargs):
    return _auto_resolve_pipeline._start_auto_resolve_download_thread(*args, **kwargs)


def _show_download_status_popup(*args, **kwargs):
    return _auto_resolve_pipeline._show_download_status_popup(*args, **kwargs)


def _schedule_auto_resolve_download(*args, **kwargs):
    return _auto_resolve_pipeline._schedule_auto_resolve_download(*args, **kwargs)


def queue_resolve_download(*args, **kwargs):
    return _auto_resolve_pipeline.queue_resolve_download(*args, **kwargs)


def _mark_manual_queued_resolve_error(*args, **kwargs):
    return _auto_resolve_pipeline._mark_manual_queued_resolve_error(*args, **kwargs)


def _read_scene_last_resolve_error(*args, **kwargs):
    return _auto_resolve_pipeline._read_scene_last_resolve_error(*args, **kwargs)


def _store_resolve_summary(*args, **kwargs):
    return _auto_resolve_pipeline._store_resolve_summary(*args, **kwargs)


def _write_last_resolve_summary(*args, **kwargs):
    return _auto_resolve_pipeline._write_last_resolve_summary(*args, **kwargs)


def _is_non_retryable_resolve_error(*args, **kwargs):
    return _auto_resolve_pipeline._is_non_retryable_resolve_error(*args, **kwargs)


def _mark_auto_resolve_terminal_failure(*args, **kwargs):
    return _auto_resolve_pipeline._mark_auto_resolve_terminal_failure(*args, **kwargs)


def _handle_auto_resolve_download_failure(*args, **kwargs):
    return _auto_resolve_pipeline._handle_auto_resolve_download_failure(*args, **kwargs)


def _auto_resolve_completion_epoch_state(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_completion_epoch_state(*args, **kwargs)


def _auto_resolve_handle_cancel_or_failure(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_handle_cancel_or_failure(*args, **kwargs)


def _auto_resolve_log_pending_request_overlap(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_log_pending_request_overlap(*args, **kwargs)


def _auto_resolve_prepare_apply_context(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_prepare_apply_context(*args, **kwargs)


def _auto_resolve_apply_downloaded_tiles(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_apply_downloaded_tiles(*args, **kwargs)


def _auto_resolve_summary_total_bytes(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_summary_total_bytes(*args, **kwargs)


def _finalize_auto_resolve_apply(*args, **kwargs):
    return _auto_resolve_pipeline._finalize_auto_resolve_apply(*args, **kwargs)


def _handle_auto_resolve_download_complete(*args, **kwargs):
    return _auto_resolve_pipeline._handle_auto_resolve_download_complete(*args, **kwargs)


def _auto_resolve_download_worker(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_download_worker(*args, **kwargs)


def _auto_resolve_download_pump_timer(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_download_pump_timer(*args, **kwargs)


def stop_auto_resolve_download_pipeline(*args, **kwargs):
    return _auto_resolve_pipeline.stop_auto_resolve_download_pipeline(*args, **kwargs)


def request_auto_resolve(*args, **kwargs):
    return _auto_resolve_pipeline.request_auto_resolve(*args, **kwargs)


def _can_auto_resolve_run(*args, **kwargs):
    return _auto_resolve_pipeline._can_auto_resolve_run(*args, **kwargs)


def update_auto_resolve(self, context):
    return _auto_resolve_pipeline.update_auto_resolve(self, context)


def _auto_resolve_collect_scope_signatures(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_collect_scope_signatures(*args, **kwargs)


def _auto_resolve_sync_state_signatures(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_sync_state_signatures(*args, **kwargs)


def _auto_resolve_update_size_estimation(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_update_size_estimation(*args, **kwargs)


def _arm_auto_resolve_noncritical_timer(*args, **kwargs):
    return _auto_resolve_pipeline._arm_auto_resolve_noncritical_timer(*args, **kwargs)


def _auto_resolve_enqueue_size_estimation(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_enqueue_size_estimation(*args, **kwargs)


def _auto_resolve_noncritical_timer(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_noncritical_timer(*args, **kwargs)


def _auto_resolve_detect_change(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_detect_change(*args, **kwargs)


def _auto_resolve_plan_job(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_plan_job(*args, **kwargs)


def _auto_resolve_dispatch_job(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_dispatch_job(*args, **kwargs)


def _auto_resolve_tick_once(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_tick_once(*args, **kwargs)


def _auto_resolve_timer(*args, **kwargs):
    return _auto_resolve_pipeline._auto_resolve_timer(*args, **kwargs)


def ensure_auto_resolve_service_running(*args, **kwargs):
    return _auto_resolve_pipeline.ensure_auto_resolve_service_running(*args, **kwargs)


def stop_auto_resolve_service(*args, **kwargs):
    return _auto_resolve_pipeline.stop_auto_resolve_service(*args, **kwargs)


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
        suspend_adaptive_viewport_during_navigation=_suspend_adaptive_viewport_during_navigation,
        is_render_job_active=_is_render_job_active,
        is_animation_playing=_is_animation_playing,
        get_earth_object=get_earth_object,
        get_tile_utils=_get_tile_utils,
        get_streaming_utils=_get_streaming_utils,
        get_coverage_map=_get_coverage_map,
        normalize_texture_quality_mode=_normalize_texture_quality_mode,
        request_auto_resolve=request_auto_resolve,
        get_auto_resolve_in_flight=lambda: bool(_AUTO_RESOLVE_SHARED_STATE.in_flight),
        sunlight_object_name=_SUNLIGHT_OBJECT_NAME,
        monotonic=time.monotonic,
        real_earth_radius_m=_REAL_EARTH_RADIUS_M,
        max_terrain_height_m=_MAX_TERRAIN_HEIGHT_M,
        dataset_mpp_base_d1=_DATASET_MPP_BASE_D1,
        live_safety_caution_ratio=_LIVE_SAFETY_CAUTION_RATIO,
        live_fallback_mpp_m=_LIVE_FALLBACK_MPP_M,
        live_z_levels=_LIVE_Z_LEVELS,
        resolve_estimate_full_bytes_key=RESOLVE_ESTIMATE_FULL_BYTES_KEY,
        resolve_estimate_balanced_bytes_key=RESOLVE_ESTIMATE_BALANCED_BYTES_KEY,
        resolve_estimate_preview_bytes_key=RESOLVE_ESTIMATE_PREVIEW_BYTES_KEY,
    )
    state = ViewTelemetryState(
        viewport_opt_last_signature=_VIEWPORT_OPT_LAST_SIGNATURE,
        sunlight_last_signature=_SUNLIGHT_LAST_SIGNATURE,
        sunlight_object_name_cache=_SUNLIGHT_OBJECT_NAME_CACHE,
        viewport_scope_last=_VIEWPORT_SCOPE_LAST,
        viewport_scope_last_resolve_time=_VIEWPORT_SCOPE_LAST_RESOLVE_TIME,
        last_realtime_telemetry=_LAST_REALTIME_TELEMETRY,
        timeline_last_signature=_TIMELINE_LAST_SIGNATURE,
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
        sunlight_object_name=_SUNLIGHT_OBJECT_NAME,
        sync_idprops_from_props=_sync_idprops_from_props,
        suspend_adaptive_viewport_during_navigation=_suspend_adaptive_viewport_during_navigation,
        request_auto_resolve=request_auto_resolve,
    )
    state = NavigationRuntimeState(
        nav_camera_control_last_signature=_NAV_CAMERA_CONTROL_LAST_SIGNATURE,
    )
    return NavigationRuntimeContext(
        deps=deps,
        state=state,
    )


def recover_post_render_state(scene=None, cancelled=False):
    _handler_runtime.configure(globals())
    return _handler_runtime.recover_post_render_state(scene=scene, cancelled=cancelled)


def mark_render_job_started():
    _handler_runtime.configure(globals())
    return _handler_runtime.mark_render_job_started()


def _sync_logging_from_scenes():
    _handler_runtime.configure(globals())
    return _handler_runtime._sync_logging_from_scenes()


def migrate_scene(scene):
    _handler_runtime.configure(globals())
    return _handler_runtime.migrate_scene(scene)


def _initialize_props_from_imported_planetka(scene):
    _handler_runtime.configure(globals())
    return _handler_runtime._initialize_props_from_imported_planetka(scene)


@persistent
def _planetka_depsgraph_update_post(_scene, _depsgraph):
    _handler_runtime.configure(globals())
    return _handler_runtime._planetka_depsgraph_update_post(_scene, _depsgraph)


@persistent
def _planetka_frame_change_post(scene, _depsgraph=None):
    _handler_runtime.configure(globals())
    return _handler_runtime._planetka_frame_change_post(scene, _depsgraph=_depsgraph)


@persistent
def _planetka_load_post(_dummy):
    _handler_runtime.configure(globals())
    return _handler_runtime._planetka_load_post(_dummy)


def _build_auto_resolve_contexts():
    settings = AutoResolveSettings(
        retry_delay_sec=AUTO_RESOLVE_RETRY_DELAY_SEC,
        min_interval_sec_default=AUTO_RESOLVE_MIN_INTERVAL_SEC_DEFAULT,
        idle_sec_default=AUTO_RESOLVE_IDLE_SEC_DEFAULT,
        download_pump_interval_sec=_AUTO_RESOLVE_DOWNLOAD_PUMP_INTERVAL_SEC,
        download_scene_wait_sec=_AUTO_RESOLVE_DOWNLOAD_SCENE_WAIT_SEC,
        download_completed_max_age_sec=_AUTO_RESOLVE_DOWNLOAD_COMPLETED_MAX_AGE_SEC,
        noncritical_interval_sec=_AUTO_RESOLVE_NONCRITICAL_INTERVAL_SEC,
    )
    shared_state = AutoResolveSharedState(
        in_flight=_AUTO_RESOLVE_IN_FLIGHT,
        timer_running=_AUTO_RESOLVE_TIMER_RUNNING,
        download_timer_running=_AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING,
        download_thread=_AUTO_RESOLVE_DOWNLOAD_THREAD,
        download_active_job=_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB,
        download_pending_job=_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB,
        download_completed=_AUTO_RESOLVE_DOWNLOAD_COMPLETED,
        download_request_counter=_AUTO_RESOLVE_DOWNLOAD_REQUEST_COUNTER,
        download_epoch=_AUTO_RESOLVE_DOWNLOAD_EPOCH,
        download_lock=_AUTO_RESOLVE_DOWNLOAD_LOCK,
        next_due_time=_AUTO_RESOLVE_NEXT_DUE_TIME,
        last_camera_signature=_AUTO_RESOLVE_LAST_CAMERA_SIGNATURE,
        last_output_signature=_AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE,
        last_change_time=_AUTO_RESOLVE_LAST_CHANGE_TIME,
        last_resolve_time=_AUTO_RESOLVE_LAST_RESOLVE_TIME,
        last_processed_signature=_AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE,
        pending_output_change=_AUTO_RESOLVE_PENDING_OUTPUT_CHANGE,
        trigger_last_signature=_AUTO_RESOLVE_TRIGGER_LAST_SIGNATURE,
        noncritical_timer_running=_AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING,
        noncritical_pending=_AUTO_RESOLVE_NONCRITICAL_PENDING,
        size_estimate_last_signature=_AUTO_RESOLVE_SIZE_ESTIMATE_LAST_SIGNATURE,
    )
    download_deps = AutoResolveDownloadDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        resolve_trace=_resolve_trace,
        get_prefs=get_prefs,
        get_streaming_utils=_get_streaming_utils,
        clear_status_notices=_clear_status_notices,
        scene_key=_scene_key,
        scene_from_key=_scene_from_key,
        read_scene_auto_resolve_state=_read_scene_auto_resolve_state,
        write_scene_auto_resolve_state=_write_scene_auto_resolve_state,
        build_auto_resolve_download_job=_build_auto_resolve_download_job,
        is_auto_resolve_download_job=_is_auto_resolve_download_job,
        job_field=_job_field,
        job_set_field=_job_set_field,
        normalize_texture_quality_mode=_normalize_texture_quality_mode,
        enforce_texture_quality_mode_for_account=_enforce_texture_quality_mode_for_account,
        camera_signature=_camera_signature,
        output_resolution_signature=_output_resolution_signature,
        canonical_tiles=_canonical_tiles,
        is_render_job_active=_is_render_job_active,
        is_animation_playing=_is_animation_playing,
        mark_manual_queued_resolve_error=_mark_manual_queued_resolve_error,
        read_scene_last_resolve_error=_read_scene_last_resolve_error,
        last_resolved_tiles=_last_resolved_tiles,
        request_auto_resolve=request_auto_resolve,
        estimate_download_bytes_for_visible_tiles=_estimate_download_bytes_for_visible_tiles,
        update_realtime_telemetry=_update_realtime_telemetry,
        tag_view3d_redraw=_tag_view3d_redraw,
        last_resolve_tile_count_key=LAST_RESOLVE_TILE_COUNT_KEY,
        last_resolve_downloaded_mb_key=LAST_RESOLVE_DOWNLOADED_MB_KEY,
        last_resolve_downloaded_gb_key=LAST_RESOLVE_DOWNLOADED_GB_KEY,
        last_resolve_total_seconds_key=LAST_RESOLVE_TOTAL_SECONDS_KEY,
        viewport_scope_last_resolve_time=_VIEWPORT_SCOPE_LAST_RESOLVE_TIME,
    )
    decision_deps = AutoResolveDecisionDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        resolve_trace=_resolve_trace,
        get_navigation_user_edit_last_touch=lambda: _NAVIGATION_USER_EDIT_LAST_TOUCH,
        nav_camera_control_sync_grace_sec=_NAV_CAMERA_CONTROL_SYNC_GRACE_SEC,
        iter_scenes=_iter_scenes,
        scene_key=_scene_key,
        read_scene_auto_resolve_state=_read_scene_auto_resolve_state,
        write_scene_auto_resolve_state=_write_scene_auto_resolve_state,
        make_depsgraph_trigger_signature=_make_depsgraph_trigger_signature,
        depsgraph_trigger_output_signature=_depsgraph_trigger_output_signature,
        camera_signature=_camera_signature,
        output_resolution_signature=_output_resolution_signature,
        current_view_scope=_current_view_scope,
        auto_resolve_scope_mode=_auto_resolve_scope_mode,
        resolve_scope_altitude_info=_resolve_scope_altitude_info,
        set_camera_inside_earth_warning=_set_camera_inside_earth_warning,
        clear_camera_inside_earth_warning=_clear_camera_inside_earth_warning,
        active_view_signature=_active_view_signature,
        last_resolved_tiles=_last_resolved_tiles,
        get_earth_object=get_earth_object,
        get_tile_utils=_get_tile_utils,
        canonical_tiles=_canonical_tiles,
        is_render_job_active=_is_render_job_active,
        is_animation_playing=_is_animation_playing,
        is_navigation_user_edit_active=_is_navigation_user_edit_active,
        stop_auto_resolve_download_pipeline=stop_auto_resolve_download_pipeline,
        schedule_auto_resolve_download=_schedule_auto_resolve_download,
        arm_auto_resolve_timer=_arm_auto_resolve_timer,
        enqueue_size_estimation=_auto_resolve_enqueue_size_estimation,
        update_realtime_telemetry=_update_realtime_telemetry,
        handle_viewport_motion_optimization=_handle_viewport_motion_optimization,
        handle_timeline_motion_optimization=_handle_timeline_motion_optimization,
        handle_sunlight_motion_optimization=_handle_sunlight_motion_optimization,
        handle_view_scope_quality_transition=_handle_view_scope_quality_transition,
        keyed_runtime_signature=_keyed_runtime_signature,
        timeline_signature=_timeline_signature,
        sunlight_signature=_sunlight_signature,
        sync_idprops_from_props=_sync_idprops_from_props,
        force_restore_navigation_adaptive_state=_force_restore_navigation_adaptive_state,
        viewport_opt_last_signature=_VIEWPORT_OPT_LAST_SIGNATURE,
        sunlight_last_signature=_SUNLIGHT_LAST_SIGNATURE,
        viewport_scope_last=_VIEWPORT_SCOPE_LAST,
        viewport_scope_last_resolve_time=_VIEWPORT_SCOPE_LAST_RESOLVE_TIME,
        last_realtime_telemetry=_LAST_REALTIME_TELEMETRY,
        timeline_last_signature=_TIMELINE_LAST_SIGNATURE,
        frame_keyed_runtime_last_signature=_FRAME_KEYED_RUNTIME_LAST_SIGNATURE,
        nav_camera_control_last_signature=_NAV_CAMERA_CONTROL_LAST_SIGNATURE,
        sunlight_object_name_cache=_SUNLIGHT_OBJECT_NAME_CACHE,
    )
    noncritical_deps = AutoResolveNonCriticalDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        get_prefs=get_prefs,
        normalize_texture_quality_mode=_normalize_texture_quality_mode,
        scene_key=_scene_key,
        scene_from_key=_scene_from_key,
        update_resolve_size_estimates=update_resolve_size_estimates,
    )
    return (
        settings,
        shared_state,
        AutoResolveDownloadContext(
            deps=download_deps,
            state=shared_state,
            settings=settings,
        ),
        AutoResolveDecisionContext(
            deps=decision_deps,
            state=shared_state,
            settings=settings,
        ),
        AutoResolveNonCriticalContext(
            deps=noncritical_deps,
            state=shared_state,
            settings=settings,
        ),
    )


_VIEW_TELEMETRY_CTX = _build_view_telemetry_context()
_NAVIGATION_RUNTIME_CTX = _build_navigation_runtime_context()

# state.py remains the owner of the singleton view-telemetry context; the
# runtime module receives it explicitly instead of pulling facade globals.
_view_telemetry._VIEW_TELEMETRY_CTX = _VIEW_TELEMETRY_CTX
_navigation_runtime._NAVIGATION_RUNTIME_CTX = _NAVIGATION_RUNTIME_CTX


(
    _AUTO_RESOLVE_SETTINGS,
    _AUTO_RESOLVE_SHARED_STATE,
    _AUTO_RESOLVE_DOWNLOAD_CTX,
    _AUTO_RESOLVE_DECISION_CTX,
    _AUTO_RESOLVE_NONCRITICAL_CTX,
) = _build_auto_resolve_contexts()

# state.py remains the owner of the singleton auto-resolve contexts; the
# pipeline module receives them explicitly instead of pulling facade globals.
_auto_resolve_pipeline._AUTO_RESOLVE_DOWNLOAD_CTX = _AUTO_RESOLVE_DOWNLOAD_CTX
_auto_resolve_pipeline._AUTO_RESOLVE_DECISION_CTX = _AUTO_RESOLVE_DECISION_CTX
_auto_resolve_pipeline._AUTO_RESOLVE_NONCRITICAL_CTX = _AUTO_RESOLVE_NONCRITICAL_CTX
