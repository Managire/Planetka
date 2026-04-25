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
from dataclasses import dataclass, field

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
from .planetka_runtime import cache_recovery as _cache_recovery
from .planetka_runtime import navigation_runtime as _navigation_runtime
from .planetka_runtime import scene_sync as _scene_sync
from .planetka_runtime import view_telemetry as _view_telemetry
from .planetka_runtime import auto_resolve_pipeline as _auto_resolve_pipeline
from .scene_schema import migrate_scene_schema


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


@dataclass
class SceneAutoResolveState:
    scene_id: int
    next_due_time: object = None
    last_camera_signature: object = None
    last_output_signature: object = None
    last_change_time: object = None
    last_resolve_time: object = None
    last_processed_signature: object = None
    pending_output_change: bool = False
    trigger_last_signature: object = None


@dataclass
class AutoResolveDownloadJob:
    epoch: int
    request_id: int
    scene_id: int
    target_tiles: tuple = ()
    camera_signature: object = None
    output_signature: object = None
    manual_request: bool = False
    base_path: str = ""
    texture_quality_mode: str = "PREVIEW"
    nav_latitude_deg: float = 0.0
    nav_longitude_deg: float = 0.0
    nav_altitude_km: float = 0.0
    cancel_event: object = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.monotonic)
    scene_missing_since: float = 0.0
    scene_missing_attempts: int = 0


def _is_auto_resolve_download_job(job):
    return isinstance(job, (AutoResolveDownloadJob, dict))


def _job_field(job, name, default=None):
    if isinstance(job, AutoResolveDownloadJob):
        return getattr(job, name, default)
    if isinstance(job, dict):
        return job.get(name, default)
    return default


def _job_set_field(job, name, value):
    if isinstance(job, AutoResolveDownloadJob):
        setattr(job, name, value)
    elif isinstance(job, dict):
        job[name] = value


def _build_auto_resolve_download_job(
    *,
    epoch,
    request_id,
    scene_id,
    target_tiles,
    camera_signature,
    output_signature,
    manual_request,
    base_path,
    texture_quality_mode,
    nav_latitude_deg,
    nav_longitude_deg,
    nav_altitude_km,
):
    return AutoResolveDownloadJob(
        epoch=int(epoch),
        request_id=int(request_id),
        scene_id=int(scene_id),
        target_tiles=tuple(target_tiles or ()),
        camera_signature=camera_signature,
        output_signature=output_signature,
        manual_request=bool(manual_request),
        base_path=str(base_path or ""),
        texture_quality_mode=_normalize_texture_quality_mode(texture_quality_mode),
        nav_latitude_deg=float(nav_latitude_deg or 0.0),
        nav_longitude_deg=float(nav_longitude_deg or 0.0),
        nav_altitude_km=float(nav_altitude_km or 0.0),
    )


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


def _set_atmosphere_collection_enabled(scene, enabled):
    # Atmosphere runtime loading is disabled in current release.
    # Keep callback as no-op to prevent accidental collection creation.
    _ = (scene, enabled)


def _remove_object_and_unused_data_any_type(obj):
    if obj is None:
        return False
    obj_type = str(getattr(obj, "type", "") or "")
    data_block = getattr(obj, "data", None)
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka cleanup: failed removing object %s", getattr(obj, "name", "<unknown>"), exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka cleanup: failed removing object %s", getattr(obj, "name", "<unknown>"), exc_info=True)
        return False

    try:
        if data_block is None or int(getattr(data_block, "users", 0)) > 0:
            return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        return True

    try:
        if obj_type == "MESH":
            bpy.data.meshes.remove(data_block)
        elif obj_type == "VOLUME" and hasattr(bpy.data, "volumes"):
            bpy.data.volumes.remove(data_block)
        elif obj_type == "LIGHT" and hasattr(bpy.data, "lights"):
            bpy.data.lights.remove(data_block)
        elif obj_type == "CURVE" and hasattr(bpy.data, "curves"):
            bpy.data.curves.remove(data_block)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka cleanup: failed removing data block for %s", getattr(obj, "name", "<unknown>"), exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka cleanup: failed removing data block for %s", getattr(obj, "name", "<unknown>"), exc_info=True)
    return True


def _remove_collection_if_exists(collection_name):
    collection = bpy.data.collections.get(str(collection_name or ""))
    if collection is None:
        return False
    try:
        for parent in list(getattr(bpy.data, "collections", ())):
            try:
                if collection.name in tuple(getattr(parent, "children", ()).keys()):
                    parent.children.unlink(collection)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                continue
        for scene in list(getattr(bpy.data, "scenes", ())):
            root = getattr(scene, "collection", None)
            if root is None:
                continue
            try:
                if collection.name in tuple(getattr(root, "children", ()).keys()):
                    root.children.unlink(collection)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                continue
        bpy.data.collections.remove(collection)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka cleanup: failed removing collection %s", collection_name, exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka cleanup: failed removing collection %s", collection_name, exc_info=True)
    return False


def purge_disabled_atmosphere_and_cloud_assets(scene=None):
    """Hard-disable atmosphere/cloud assets in current release by removing them from data-blocks."""
    _ = scene

    object_names = {
        "Atmosphere - EEVEE supplement",
        "Atmosphere - Volumetric",
        "Planetka Atmosphere",
        "Planetka Atmosphere Fake",
        "Planetka Global Cloud Layer",
        "Planetka Cloud VDB",
    }
    object_prefixes = (
        "Local Cloud No ",
        "VDB Cloud No ",
        "Planetka Local Cloud Cap Mesh",
    )
    collection_names = {
        "Atmosphere",
        "Atmpshere",
        "Clouds",
        "Global Clouds",
        "Local Clouds",
        "VDB Clouds",
    }
    material_exact = {
        "Planetka Atmosphere Fake Material",
        "Planetka Atmosphere Material",
        "Planetka Global Clouds Shader",
        "Planetka Local Clouds Shader",
        "Planetka VDB Cloud Shader",
    }
    material_prefixes = (
        "Planetka Local Clouds Shader",
        "Planetka VDB Cloud Shader",
    )
    node_group_exact = {
        "Planetka Atmosphere Group",
        "Planetka Atmosphere Fake Group",
        "Planetka Fake Atmosphere Textures Group",
        "Planetka Global Clouds Shader Group",
        "Planetka Local Clouds Shader Group",
        "Cloud Preview Switch",
    }

    try:
        asset_builder_module = importlib.import_module(f"{__package__}.asset_builder" if __package__ else "asset_builder")
        for attr in (
            "FAKE_ATMOSPHERE_OBJECT_NAME",
            "FAKE_ATMOSPHERE_SOURCE_OBJECT_NAME",
            "VOLUMETRIC_ATMOSPHERE_OBJECT_NAME",
            "VOLUMETRIC_ATMOSPHERE_SOURCE_OBJECT_NAME",
        ):
            value = str(getattr(asset_builder_module, attr, "") or "").strip()
            if value:
                object_names.add(value)
        for attr in (
            "FAKE_ATMOSPHERE_COLLECTION_NAME",
            "_LEGACY_FAKE_ATMOSPHERE_COLLECTION_NAMES",
        ):
            value = getattr(asset_builder_module, attr, None)
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    text = str(item or "").strip()
                    if text:
                        collection_names.add(text)
            else:
                text = str(value or "").strip()
                if text:
                    collection_names.add(text)
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        pass

    try:
        clouds_module = importlib.import_module(f"{__package__}.clouds_local" if __package__ else "clouds_local")
        for attr in (
            "CLOUDS_ROOT_COLLECTION_NAME",
            "GLOBAL_CLOUDS_COLLECTION_NAME",
            "LOCAL_CLOUDS_COLLECTION_NAME",
            "VDB_CLOUDS_COLLECTION_NAME",
            "GLOBAL_CLOUD_LAYER_NAME",
            "VDB_CLOUD_TEMPLATE_OBJECT_NAME",
        ):
            text = str(getattr(clouds_module, attr, "") or "").strip()
            if not text:
                continue
            if "COLLECTION" in attr:
                collection_names.add(text)
            else:
                object_names.add(text)
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        pass

    removed_objects = 0
    removed_collections = 0
    removed_materials = 0
    removed_node_groups = 0

    for obj in list(getattr(bpy.data, "objects", ())):
        name = str(getattr(obj, "name", "") or "")
        role = str(obj.get("planetka_role", "") or "")
        cloud_role = str(obj.get("planetka_cloud_role", "") or "")
        should_remove = (
            name in object_names
            or any(name.startswith(prefix) for prefix in object_prefixes)
            or role in {"fake_atmosphere", "atmosphere_volumetric"}
            or bool(cloud_role)
        )
        if not should_remove:
            continue
        if _remove_object_and_unused_data_any_type(obj):
            removed_objects += 1

    for name in sorted(collection_names):
        if _remove_collection_if_exists(name):
            removed_collections += 1

    for material in list(getattr(bpy.data, "materials", ())):
        name = str(getattr(material, "name", "") or "")
        if not (name in material_exact or any(name.startswith(prefix) for prefix in material_prefixes)):
            continue
        try:
            if int(getattr(material, "users", 0)) == 0:
                bpy.data.materials.remove(material)
                removed_materials += 1
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka cleanup: failed removing atmosphere/cloud material %s", name, exc_info=True)

    for group in list(getattr(bpy.data, "node_groups", ())):
        name = str(getattr(group, "name", "") or "")
        if name not in node_group_exact:
            continue
        try:
            if int(getattr(group, "users", 0)) == 0:
                bpy.data.node_groups.remove(group)
                removed_node_groups += 1
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka cleanup: failed removing atmosphere/cloud node group %s", name, exc_info=True)

    return {
        "objects": int(removed_objects),
        "collections": int(removed_collections),
        "materials": int(removed_materials),
        "node_groups": int(removed_node_groups),
    }


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
    if _IDPROP_SYNCING:
        return
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene, ("show_earth_preview",))

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



def update_atmosphere_enabled(self, context):
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(scene, ("atmosphere_enabled",))
    _set_atmosphere_collection_enabled(
        scene,
        bool(getattr(self, "atmosphere_enabled", True)),
    )


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
        globals(),
        scene,
        bpy=bpy,
        scene_key=_scene_key,
        camera_control_sync_signature=_camera_control_sync_signature,
    )


def _get_planetka_sunlight_object():
    return _navigation_runtime.get_planetka_sunlight_object(globals(), bpy=bpy)


def _apply_sunlight_from_props(scene):
    return _navigation_runtime.apply_sunlight_from_props(
        globals(),
        scene,
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


def _apply_sunlight_strength_from_props(scene):
    return _navigation_runtime.apply_sunlight_strength_from_props(
        globals(),
        scene,
        bpy=bpy,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        logger=logger,
    )


def update_sunlight_controls(self, context):
    return _navigation_runtime.update_sunlight_controls(
        globals(),
        self,
        context,
        sync_idprops_from_props=_sync_idprops_from_props,
        suspend_adaptive_viewport_during_navigation=_suspend_adaptive_viewport_during_navigation,
        request_auto_resolve=request_auto_resolve,
        apply_sunlight_from_props=_apply_sunlight_from_props,
        apply_sunlight_strength_from_props=_apply_sunlight_strength_from_props,
    )


def update_sunlight_strength(self, context):
    return _navigation_runtime.update_sunlight_strength(
        globals(),
        self,
        context,
        sync_idprops_from_props=_sync_idprops_from_props,
        suspend_adaptive_viewport_during_navigation=_suspend_adaptive_viewport_during_navigation,
        apply_sunlight_strength_from_props=_apply_sunlight_strength_from_props,
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
    return int(getattr(scene, "as_pointer", lambda: id(scene))())


def _scene_from_key(scene_id):
    try:
        target_id = int(scene_id)
    except (TypeError, ValueError):
        return None
    for scene in _iter_scenes():
        try:
            if _scene_key(scene) == target_id:
                return scene
        except (TypeError, ValueError, RuntimeError):
            continue
    return None


def _coerce_scene_id(scene_or_id):
    if scene_or_id is None:
        return None
    if isinstance(scene_or_id, int):
        return int(scene_or_id)
    try:
        return int(_scene_key(scene_or_id))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return None


def _set_scene_auto_resolve_map_entry(target_map, scene_id, value):
    if value is None:
        target_map.pop(scene_id, None)
        return
    target_map[scene_id] = value


def _read_scene_auto_resolve_state(scene_or_id):
    scene_id = _coerce_scene_id(scene_or_id)
    if scene_id is None:
        return None
    return SceneAutoResolveState(
        scene_id=scene_id,
        next_due_time=_AUTO_RESOLVE_NEXT_DUE_TIME.get(scene_id),
        last_camera_signature=_AUTO_RESOLVE_LAST_CAMERA_SIGNATURE.get(scene_id),
        last_output_signature=_AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE.get(scene_id),
        last_change_time=_AUTO_RESOLVE_LAST_CHANGE_TIME.get(scene_id),
        last_resolve_time=_AUTO_RESOLVE_LAST_RESOLVE_TIME.get(scene_id),
        last_processed_signature=_AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE.get(scene_id),
        pending_output_change=bool(_AUTO_RESOLVE_PENDING_OUTPUT_CHANGE.get(scene_id, False)),
        trigger_last_signature=_AUTO_RESOLVE_TRIGGER_LAST_SIGNATURE.get(scene_id),
    )


def _write_scene_auto_resolve_state(state):
    if not isinstance(state, SceneAutoResolveState):
        return
    scene_id = int(state.scene_id)
    _set_scene_auto_resolve_map_entry(_AUTO_RESOLVE_NEXT_DUE_TIME, scene_id, state.next_due_time)
    _set_scene_auto_resolve_map_entry(_AUTO_RESOLVE_LAST_CAMERA_SIGNATURE, scene_id, state.last_camera_signature)
    _set_scene_auto_resolve_map_entry(_AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE, scene_id, state.last_output_signature)
    _set_scene_auto_resolve_map_entry(_AUTO_RESOLVE_LAST_CHANGE_TIME, scene_id, state.last_change_time)
    _set_scene_auto_resolve_map_entry(_AUTO_RESOLVE_LAST_RESOLVE_TIME, scene_id, state.last_resolve_time)
    _set_scene_auto_resolve_map_entry(
        _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE,
        scene_id,
        state.last_processed_signature,
    )
    if bool(state.pending_output_change):
        _AUTO_RESOLVE_PENDING_OUTPUT_CHANGE[scene_id] = True
    else:
        _AUTO_RESOLVE_PENDING_OUTPUT_CHANGE.pop(scene_id, None)
    _set_scene_auto_resolve_map_entry(_AUTO_RESOLVE_TRIGGER_LAST_SIGNATURE, scene_id, state.trigger_last_signature)


def _make_depsgraph_trigger_signature(scene):
    resolve_signature = _camera_signature(scene)
    if _auto_resolve_scope_mode(scene) == "ACTIVE_VIEW":
        active_signature = _active_view_signature()
        if active_signature is not None:
            resolve_signature = ("ACTIVE_VIEW", active_signature)
    if resolve_signature is None:
        return None
    output_signature = _output_resolution_signature(scene)
    return ("TRIGGER_V2", resolve_signature, output_signature)


def _depsgraph_trigger_output_signature(signature):
    if (
        isinstance(signature, tuple)
        and len(signature) == 3
        and str(signature[0]) == "TRIGGER_V2"
    ):
        return signature[2]
    return None


def _mark_auto_resolve_from_depsgraph_trigger(scene, trigger_signature):
    if scene is None or trigger_signature is None:
        return False
    scene_state = _read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return False

    previous_trigger_signature = scene_state.trigger_last_signature
    if previous_trigger_signature is None:
        scene_state.trigger_last_signature = trigger_signature
        _write_scene_auto_resolve_state(scene_state)
        return False
    if previous_trigger_signature == trigger_signature:
        return False

    immediate = False
    previous_output_signature = _depsgraph_trigger_output_signature(previous_trigger_signature)
    current_output_signature = _depsgraph_trigger_output_signature(trigger_signature)
    if (
        previous_output_signature is not None
        and current_output_signature is not None
        and previous_output_signature != current_output_signature
    ):
        immediate = True

    scene_state.trigger_last_signature = trigger_signature
    _write_scene_auto_resolve_state(scene_state)
    request_auto_resolve(scene, immediate=bool(immediate), mark_dirty=False)
    return True


def get_resolve_runtime_status(scene=None):
    """Return current resolve runtime stage for telemetry UI."""
    if scene is None:
        scene = getattr(getattr(bpy, "context", None), "scene", None)

    with _AUTO_RESOLVE_DOWNLOAD_LOCK:
        active_job = _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB if _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB) else None
        pending_job = _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB if _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB) else None
        completed_payload = dict(_AUTO_RESOLVE_DOWNLOAD_COMPLETED) if isinstance(_AUTO_RESOLVE_DOWNLOAD_COMPLETED, dict) else None

    thread_running = _AUTO_RESOLVE_DOWNLOAD_THREAD is not None
    in_flight = bool(_AUTO_RESOLVE_IN_FLIGHT)
    pending_count = int((1 if active_job else 0) + (1 if pending_job else 0))
    active_request_id = None
    if _is_auto_resolve_download_job(active_job):
        active_request_id = _job_field(active_job, "request_id")
    elif _is_auto_resolve_download_job(pending_job):
        active_request_id = _job_field(pending_job, "request_id")

    status = {
        "code": "IDLE",
        "text": "Idle",
        "running": False,
        "active_request_id": active_request_id,
        "pending_count": pending_count,
        "completed_pending": bool(completed_payload),
    }

    if in_flight:
        status.update({
            "code": "FINALIZING",
            "text": "Finalizing Resolve (mesh/shader update)",
            "running": True,
        })
        return status

    if thread_running and _is_auto_resolve_download_job(active_job):
        preparing = False
        try:
            r2_source = _get_r2_source()
            get_progress = getattr(r2_source, "get_download_progress", None) if r2_source is not None else None
            if callable(get_progress):
                progress = get_progress() or {}
                active_requests = int(progress.get("active_requests", 0) or 0)
                downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
                preparing = bool(active_requests <= 0 and downloaded_bytes <= 0)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            preparing = False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            preparing = False
        status.update({
            "code": "PREPARING" if preparing else "DOWNLOADING",
            "text": "Preparing Download" if preparing else "Downloading Data",
            "running": True,
        })
        return status

    if isinstance(completed_payload, dict):
        status.update({
            "code": "FINALIZE_QUEUED",
            "text": "Download finished, waiting to finalize",
            "running": True,
        })
        return status

    if pending_count > 0:
        status.update({
            "code": "QUEUED",
            "text": "Resolve queued",
            "running": True,
        })
        return status

    return status


def get_camera_inside_earth_warning(scene=None):
    target_scene = scene if scene is not None else getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return ""
    try:
        return str(target_scene.get(CAMERA_INSIDE_EARTH_WARNING_KEY, "") or "").strip()
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        return ""


def _clear_camera_inside_earth_warning(scene):
    if scene is None:
        return
    try:
        if CAMERA_INSIDE_EARTH_WARNING_KEY in scene:
            del scene[CAMERA_INSIDE_EARTH_WARNING_KEY]
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed clearing inside-Earth warning", exc_info=True)


def _set_camera_inside_earth_warning(scene, altitude_km=None):
    if scene is None:
        return ""
    _ = altitude_km
    message = "Below Earth's surface"
    try:
        scene[CAMERA_INSIDE_EARTH_WARNING_KEY] = str(message)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed storing inside-Earth warning", exc_info=True)
    return message


def _resolve_scope_altitude_info(scene, scope_mode="AUTO"):
    result = {
        "inside_earth": False,
        "altitude_km": None,
        "altitude_bu": None,
        "scope_used": None,
    }
    if scene is None:
        return result
    earth = get_earth_object()
    if earth is None:
        return result

    tile_utils = _get_tile_utils()
    if tile_utils is None:
        return result
    get_camera_info = getattr(tile_utils, "get_camera_info", None)
    get_radius = getattr(tile_utils, "get_earth_radius_blender_units", None)
    if not callable(get_camera_info) or not callable(get_radius):
        return result

    try:
        camera_info = get_camera_info(scene, scope_mode=str(scope_mode or "AUTO"))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed reading resolve camera info for inside-Earth check", exc_info=True)
        return result
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed reading resolve camera info for inside-Earth check", exc_info=True)
        return result

    if not isinstance(camera_info, dict):
        return result

    camera_position = camera_info.get("position")
    if camera_position is None:
        return result

    try:
        earth_center = earth.matrix_world.translation.copy()
        radius_bu = float(get_radius(earth))
        altitude_bu = float((camera_position - earth_center).length) - radius_bu
        meters_per_bu = float(6371000.0 / max(radius_bu, 1e-9))
        altitude_km = float((altitude_bu * meters_per_bu) / 1000.0)
        inside_epsilon_bu = float(max(1e-9, radius_bu * 1e-6))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, ZeroDivisionError):
        logger.debug("Planetka: failed computing resolve altitude for inside-Earth check", exc_info=True)
        return result

    result["scope_used"] = str(camera_info.get("scope_used", "CAMERA") or "CAMERA")
    result["altitude_bu"] = altitude_bu
    result["altitude_km"] = altitude_km
    result["inside_earth"] = bool(altitude_bu < (-inside_epsilon_bu))
    return result


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
    camera = getattr(scene, "camera", None)
    if camera is None:
        return None
    camera_data = getattr(camera, "data", None)
    if camera_data is None:
        return None

    matrix_signature = tuple(round(float(value), 6) for row in camera.matrix_world for value in row)

    return (
        str(getattr(camera, "name_full", camera.name)),
        str(getattr(camera_data, "type", "")),
        round(float(getattr(camera_data, "lens", 0.0)), 6),
        round(float(getattr(camera_data, "ortho_scale", 0.0)), 6),
        matrix_signature,
    )


def _is_resolve_pipeline_busy():
    if _AUTO_RESOLVE_IN_FLIGHT:
        return True
    if _AUTO_RESOLVE_DOWNLOAD_THREAD is not None:
        return True
    with _AUTO_RESOLVE_DOWNLOAD_LOCK:
        if _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB):
            return True
        if _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB):
            return True
        if isinstance(_AUTO_RESOLVE_DOWNLOAD_COMPLETED, dict):
            return True
    return False


def _normalize_texture_quality_mode(value):
    token = str(value or "").strip().upper()
    if token == "HALF":
        return "BALANCED"
    if token in {"FULL", "BALANCED", "PREVIEW"}:
        return token
    return "PREVIEW"


def _enforce_texture_quality_mode_for_account(scene, requested_mode):
    del scene
    mode = _normalize_texture_quality_mode(requested_mode)
    if mode == "PREVIEW":
        return mode
    try:
        from .auth import get_account_tier
        prefs = get_prefs()
        tier = str(get_account_tier(prefs) or "").strip().lower()
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        tier = ""

    if mode == "BALANCED":
        if tier in {"personal", "commercial"}:
            return "BALANCED"
        return "PREVIEW"

    # FULL mode
    if tier == "commercial":
        return "FULL"
    if tier == "personal":
        return "BALANCED"
    return "PREVIEW"


def _output_resolution_signature(scene):
    render = getattr(scene, "render", None) if scene is not None else None
    if render is None:
        return None
    props = getattr(scene, "planetka", None) if scene is not None else None
    texture_quality_mode = "PREVIEW"
    try:
        texture_quality_mode = _enforce_texture_quality_mode_for_account(
            scene,
            getattr(props, "texture_quality_mode", "PREVIEW"),
        )
    except (TypeError, ValueError, RuntimeError):
        texture_quality_mode = "PREVIEW"
    try:
        return (
            int(getattr(render, "resolution_x", 1920)),
            int(getattr(render, "resolution_y", 1080)),
            int(getattr(render, "resolution_percentage", 100)),
            texture_quality_mode,
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


def _auto_resolve_scope_mode(scene):
    current_scope = _current_view_scope(scene)
    if current_scope == "ACTIVE_VIEW":
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


def _keyed_runtime_signature(scene):
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    if props is None:
        return None

    def _as_float(value, fallback=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(fallback)

    nav_lon = _as_float(getattr(props, "nav_longitude_deg", 0.0), 0.0)
    nav_lat = _as_float(getattr(props, "nav_latitude_deg", 0.0), 0.0)
    nav_alt = max(0.0, _as_float(getattr(props, "nav_altitude_km", 0.0), 0.0))
    nav_heading = _as_float(getattr(props, "nav_azimuth_deg", 0.0), 0.0)
    nav_tilt = _as_float(getattr(props, "nav_tilt_deg", 0.0), 0.0)
    nav_roll = _as_float(getattr(props, "nav_roll_deg", 0.0), 0.0)
    nav_focal = max(1.0, _as_float(getattr(props, "nav_focal_length_mm", 50.0), 50.0))
    sun_lon = _as_float(getattr(props, "sunlight_longitude_deg", 0.0), 0.0)
    sun_tilt = _as_float(getattr(props, "sunlight_seasonal_tilt_deg", 0.0), 0.0)
    sun_strength = max(0.0, _as_float(getattr(props, "sunlight_strength", 10.0), 10.0))

    return (
        round(nav_lon, 6),
        round(nav_lat, 6),
        round(nav_alt, 6),
        round(nav_heading, 6),
        round(nav_tilt, 6),
        round(nav_roll, 6),
        round(nav_focal, 6),
        round(sun_lon, 6),
        round(sun_tilt, 6),
        round(sun_strength, 6),
    )


def _iter_scene_animation_fcurves(scene):
    if scene is None:
        return
    animation_data = getattr(scene, "animation_data", None)
    if animation_data is None:
        return
    seen = set()

    def _yield_action_fcurves(action):
        fcurves = getattr(action, "fcurves", None) if action is not None else None
        if not fcurves:
            return
        for fcurve in fcurves:
            if fcurve is None:
                continue
            try:
                token = int(fcurve.as_pointer())
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                token = id(fcurve)
            if token in seen:
                continue
            seen.add(token)
            yield fcurve

    action = getattr(animation_data, "action", None)
    for fcurve in _yield_action_fcurves(action):
        yield fcurve

    nla_tracks = getattr(animation_data, "nla_tracks", None)
    if not nla_tracks:
        return
    for track in nla_tracks:
        strips = getattr(track, "strips", None)
        if not strips:
            continue
        for strip in strips:
            strip_action = getattr(strip, "action", None)
            for fcurve in _yield_action_fcurves(strip_action):
                yield fcurve


def _scene_has_keyed_runtime_path(scene, accepted_paths):
    allowed = {str(path or "").strip() for path in (accepted_paths or ()) if str(path or "").strip()}
    if not allowed:
        return False
    for fcurve in _iter_scene_animation_fcurves(scene):
        data_path = str(getattr(fcurve, "data_path", "") or "").strip()
        if data_path in allowed:
            return True
    return False


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
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    if get_earth_object() is None:
        return

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

    # Always re-resolve on Active View -> Camera transition so Camera view
    # is guaranteed to refresh with camera-scope tiles/settings.
    request_auto_resolve(scene, immediate=True, mark_dirty=True)


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
    return _view_telemetry.active_camera_projection_info(scene)


def _tag_view3d_redraw():
    return _view_telemetry.tag_view3d_redraw(globals())


def _tile_xy_for_lon_lat(lon_deg, lat_deg, z):
    return _view_telemetry.tile_xy_for_lon_lat(lon_deg, lat_deg, z)


def _best_available_mpp_for_lon_lat(lon_deg, lat_deg):
    return _view_telemetry.best_available_mpp_for_lon_lat(lon_deg, lat_deg, globals())


def _safety_for_required_vs_available(required_mpp, available_mpp):
    return _view_telemetry.safety_for_required_vs_available(required_mpp, available_mpp, globals())


def _update_realtime_telemetry(scene):
    return _view_telemetry.update_realtime_telemetry(
        scene,
        globals(),
        write_realtime_view_diagnostics=write_realtime_view_diagnostics,
    )


def _canonical_tiles(tiles):
    return _view_telemetry.canonical_tiles(tiles)


def _clear_resolve_size_estimates(scene):
    return _view_telemetry.clear_resolve_size_estimates(scene, globals())


def _estimate_download_bytes_for_visible_tiles(tiles, base_path, texture_quality_mode="PREVIEW"):
    return _view_telemetry.estimate_download_bytes_for_visible_tiles(
        tiles,
        base_path,
        globals(),
        texture_quality_mode=texture_quality_mode,
    )


def update_resolve_size_estimates(scene, scope_mode="CAMERA", base_path="", full_tiles_override=None):
    return _view_telemetry.update_resolve_size_estimates(
        scene,
        globals(),
        scope_mode=scope_mode,
        base_path=base_path,
        full_tiles_override=full_tiles_override,
    )


def get_resolve_size_estimates(scene=None):
    return _view_telemetry.get_resolve_size_estimates(scene=scene, runtime=globals())


def _last_resolved_tiles(scene):
    return _view_telemetry.last_resolved_tiles(scene, globals())


def _mark_auto_resolve_dirty(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._mark_auto_resolve_dirty(*args, **kwargs)


def _auto_resolve_idle_seconds(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_idle_seconds(*args, **kwargs)


def _is_navigation_user_edit_active(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._is_navigation_user_edit_active(*args, **kwargs)


def _active_view_monitor_interval_seconds(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._active_view_monitor_interval_seconds(*args, **kwargs)


def _arm_auto_resolve_timer(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._arm_auto_resolve_timer(*args, **kwargs)


def _auto_resolve_download_job_signature(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_download_job_signature(*args, **kwargs)


def _arm_auto_resolve_download_timer(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._arm_auto_resolve_download_timer(*args, **kwargs)


def _start_auto_resolve_download_thread(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._start_auto_resolve_download_thread(*args, **kwargs)


def _show_download_status_popup(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._show_download_status_popup(*args, **kwargs)


def _schedule_auto_resolve_download(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._schedule_auto_resolve_download(*args, **kwargs)


def queue_resolve_download(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline.queue_resolve_download(*args, **kwargs)


def _mark_manual_queued_resolve_error(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._mark_manual_queued_resolve_error(*args, **kwargs)


def _read_scene_last_resolve_error(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._read_scene_last_resolve_error(*args, **kwargs)


def _store_resolve_summary(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._store_resolve_summary(*args, **kwargs)


def _write_last_resolve_summary(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._write_last_resolve_summary(*args, **kwargs)


def _is_non_retryable_resolve_error(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._is_non_retryable_resolve_error(*args, **kwargs)


def _mark_auto_resolve_terminal_failure(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._mark_auto_resolve_terminal_failure(*args, **kwargs)


def _handle_auto_resolve_download_failure(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._handle_auto_resolve_download_failure(*args, **kwargs)


def _auto_resolve_completion_epoch_state(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_completion_epoch_state(*args, **kwargs)


def _auto_resolve_handle_cancel_or_failure(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_handle_cancel_or_failure(*args, **kwargs)


def _auto_resolve_log_pending_request_overlap(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_log_pending_request_overlap(*args, **kwargs)


def _auto_resolve_prepare_apply_context(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_prepare_apply_context(*args, **kwargs)


def _auto_resolve_apply_downloaded_tiles(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_apply_downloaded_tiles(*args, **kwargs)


def _auto_resolve_summary_total_bytes(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_summary_total_bytes(*args, **kwargs)


def _finalize_auto_resolve_apply(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._finalize_auto_resolve_apply(*args, **kwargs)


def _handle_auto_resolve_download_complete(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._handle_auto_resolve_download_complete(*args, **kwargs)


def _auto_resolve_download_worker(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_download_worker(*args, **kwargs)


def _auto_resolve_download_pump_timer(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_download_pump_timer(*args, **kwargs)


def stop_auto_resolve_download_pipeline(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline.stop_auto_resolve_download_pipeline(*args, **kwargs)


def request_auto_resolve(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline.request_auto_resolve(*args, **kwargs)


def _can_auto_resolve_run(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._can_auto_resolve_run(*args, **kwargs)


def update_auto_resolve(self, context):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline.update_auto_resolve(self, context)


def _auto_resolve_collect_scope_signatures(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_collect_scope_signatures(*args, **kwargs)


def _auto_resolve_sync_state_signatures(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_sync_state_signatures(*args, **kwargs)


def _auto_resolve_update_size_estimation(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_update_size_estimation(*args, **kwargs)


def _arm_auto_resolve_noncritical_timer(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._arm_auto_resolve_noncritical_timer(*args, **kwargs)


def _auto_resolve_enqueue_size_estimation(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_enqueue_size_estimation(*args, **kwargs)


def _auto_resolve_noncritical_timer(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_noncritical_timer(*args, **kwargs)


def _auto_resolve_detect_change(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_detect_change(*args, **kwargs)


def _auto_resolve_plan_job(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_plan_job(*args, **kwargs)


def _auto_resolve_dispatch_job(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_dispatch_job(*args, **kwargs)


def _auto_resolve_tick_once(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_tick_once(*args, **kwargs)


def _auto_resolve_timer(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline._auto_resolve_timer(*args, **kwargs)


def ensure_auto_resolve_service_running(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline.ensure_auto_resolve_service_running(*args, **kwargs)


def stop_auto_resolve_service(*args, **kwargs):
    _auto_resolve_pipeline.configure(globals())
    return _auto_resolve_pipeline.stop_auto_resolve_service(*args, **kwargs)


def recover_post_render_state(scene=None, cancelled=False):
    global _AUTO_RESOLVE_IN_FLIGHT
    global _RENDER_JOB_ACTIVE
    global _RENDER_JOB_LAST_ENDED_EPOCH
    global _RENDER_JOB_LAST_CANCELLED_EPOCH
    global _NAVIGATION_SHOT_UPDATE_PENDING
    global _NAVIGATION_SHOT_UPDATE_REENTRANT
    global _NAVIGATION_SHOT_SUSPEND_COUNT
    global _NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT

    _AUTO_RESOLVE_IN_FLIGHT = False
    _RENDER_JOB_ACTIVE = False
    _RENDER_JOB_LAST_ENDED_EPOCH = int(_RENDER_JOB_EPOCH)
    if bool(cancelled):
        _RENDER_JOB_LAST_CANCELLED_EPOCH = int(_RENDER_JOB_EPOCH)
    _NAVIGATION_SHOT_UPDATE_PENDING = False
    _NAVIGATION_SHOT_UPDATE_REENTRANT = False
    _NAVIGATION_SHOT_SUSPEND_COUNT = 0
    _NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT = 0
    _force_restore_navigation_adaptive_state()

    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        _mark_auto_resolve_dirty(scene, immediate=True)
        request_auto_resolve(scene, immediate=True, mark_dirty=False)


def mark_render_job_started():
    global _RENDER_JOB_ACTIVE
    global _RENDER_JOB_EPOCH
    if _RENDER_JOB_ACTIVE:
        # Blender calls render_pre per frame during animation renders.
        # Treat the whole animation as one render job to avoid per-frame
        # self-heal churn and epoch flips during segment rendering.
        return int(_RENDER_JOB_EPOCH)
    try:
        self_heal_missing_cache_images_for_render(getattr(getattr(bpy, "context", None), "scene", None))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka: render self-heal preflight failed", exc_info=True)
    _RENDER_JOB_EPOCH = int(_RENDER_JOB_EPOCH) + 1
    _RENDER_JOB_ACTIVE = True
    return int(_RENDER_JOB_EPOCH)


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

    try:
        # Atmosphere/cloud runtime features are disabled in this release.
        scene["planetka_atmosphere_enabled"] = False
        scene["planetka_enable_global_clouds"] = False
        scene["planetka_enable_local_clouds"] = False
        scene["planetka_enable_vdb_clouds"] = False
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed forcing atmosphere/cloud scene idprops off", exc_info=True)

    _sync_idprops_from_props(scene)


@persistent
def _planetka_depsgraph_update_post(_scene, _depsgraph):
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    if scene is None:
        return

    if _is_navigation_user_edit_active(scene):
        return

    keyed_runtime_active = _scene_has_keyed_runtime_path(scene, _KEYED_RUNTIME_ALL_PROP_PATHS)
    props = getattr(scene, "planetka", None)
    preset_active = False
    if props is not None:
        try:
            preset_token = str(getattr(props, "anim_camera_preset", "NONE") or "NONE").strip().upper()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            preset_token = "NONE"
        if preset_token in {"PUSH_IN", "PULL_BACK"}:
            preset_token = "ZOOM"
        elif preset_token in {"ARC_LEFT", "ARC_RIGHT"}:
            preset_token = "ARC"
        elif preset_token == "FLYBY":
            preset_token = "NONE"
        preset_active = preset_token not in {"", "NONE"}
    # During playback/render and for keyed runtime scenes, keep camera->nav sync disabled
    # to avoid feedback loops that can cause "stuck then jump" camera motion in renders.
    if not (_is_render_job_active() or _is_animation_playing() or keyed_runtime_active or preset_active):
        _sync_navigation_controls_from_scene_camera(scene)

    if not _can_auto_resolve_run(scene):
        return

    ensure_auto_resolve_service_running()

    _update_realtime_telemetry(scene)

    # Ignore depsgraph-triggered requeue while resolve/download pipeline is working.
    # Internal mesh/shader swaps during finalize can otherwise self-trigger endless cycles.
    if _is_resolve_pipeline_busy():
        return

    trigger_signature = _make_depsgraph_trigger_signature(scene)
    _handle_timeline_motion_optimization(scene)
    _handle_viewport_motion_optimization(
        scene,
        _camera_signature(scene),
    )
    _handle_sunlight_motion_optimization(scene)
    _mark_auto_resolve_from_depsgraph_trigger(scene, trigger_signature)


@persistent
def _planetka_frame_change_post(scene, _depsgraph=None):
    global _NAVIGATION_USER_EDIT_LAST_TOUCH
    target_scene = scene
    if target_scene is None:
        target_scene = getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return

    signature = _keyed_runtime_signature(target_scene)
    scene_id = _scene_key(target_scene)
    if signature is None:
        _FRAME_KEYED_RUNTIME_LAST_SIGNATURE.pop(scene_id, None)
        return

    previous = _FRAME_KEYED_RUNTIME_LAST_SIGNATURE.get(scene_id)
    if previous == signature:
        return
    _FRAME_KEYED_RUNTIME_LAST_SIGNATURE[scene_id] = signature

    nav_keyed = _scene_has_keyed_runtime_path(target_scene, _KEYED_RUNTIME_NAV_PROP_PATHS)
    focal_keyed = _scene_has_keyed_runtime_path(target_scene, _KEYED_RUNTIME_FOCAL_PROP_PATHS)
    sun_keyed = _scene_has_keyed_runtime_path(target_scene, _KEYED_RUNTIME_SUN_PROP_PATHS)
    if not (nav_keyed or focal_keyed or sun_keyed):
        return
    # Strict rule: timeline playback/scrubbing must never mutate Navigation,
    # camera-control props, sunlight props, or animation preset values.
    return


@persistent
def _planetka_load_post(_dummy):
    _FRAME_KEYED_RUNTIME_LAST_SIGNATURE.clear()
    _sync_logging_from_scenes()
    missing_cache_images, recovered_cache_images = _recover_missing_cache_image_paths_to_fallback()
    if int(missing_cache_images) > 0:
        logger.warning(
            "Planetka: detected %d missing cached tile image(s) on file load; redirected %d to fallback placeholders.",
            int(missing_cache_images),
            int(recovered_cache_images),
        )
        scene = getattr(getattr(bpy, "context", None), "scene", None)
        if scene is None:
            scene = next(iter(_iter_scenes()), None)
        if scene is not None:
            _schedule_load_recovery_resolve(scene)
    try:
        module_name = f"{__package__}.unsupported" if __package__ else "unsupported"
        unsupported_module = importlib.import_module(module_name)
        apply_fn = getattr(unsupported_module, "apply_runtime_unsupported_overrides", None)
        if callable(apply_fn):
            apply_fn()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed applying unsupported startup overrides", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
        logger.debug("Planetka: failed applying unsupported startup overrides", exc_info=True)
    try:
        from .auth import is_authenticated

        prefs = get_prefs()
        connected = bool(is_authenticated(prefs))
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        connected = False

    for scene in _iter_scenes():
        try:
            if connected:
                scene[ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY] = True
            elif ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY in scene:
                del scene[ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY]
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed syncing account panel default-collapsed state", exc_info=True)
    ensure_auto_resolve_service_running()
