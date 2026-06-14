"""Runtime state and orchestration for Planetka.

Core responsibilities:
- sync Scene <-> Planetka properties
- coordinate background download jobs and resolve finalization
"""

import logging
import importlib
import threading
import time

import bpy
from . import streaming_utils, tile_utils
from .error_utils import PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS, PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .auth import get_authorized_headers
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


_IDPROP_SYNCING = False
_FINAL_ANIMATION_RENDER_ACTIVE = False
_SYNC_IDPROP_MAP = {
    "show_earth_preview": "planetka_show_earth_preview",
    "texture_quality_mode": "planetka_texture_quality_mode",
    "resolution_bias": "planetka_resolution_bias",
    "lock_resolve_during_animation": "planetka_lock_resolve_during_animation",
}
SURFACE_COLLECTION_NAME = "Planetka Earth Surface Collection"

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
_VIEWPORT_SCOPE_LAST = {}
_VIEWPORT_SCOPE_LAST_RESOLVE_TIME = {}
_COVERAGE_MAP = None
_R2_SOURCE_MODULE = None
_SURFACE_GRADING_GROUP_NAME = "Planetka Surface Grading Group"
_RESOLVE_TRACE_ENABLED = False
_STATUS_NOTICE_KEYS = (
    "planetka_status_clip_auto_notice",
    "planetka_status_cache_notice",
)
_STATUS_NOTICE_CLEAR_SKIP_KEY = "planetka_status_notice_clear_skip_count"


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
    props = getattr(scene, "planetka_public", None) if scene else None
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


def _scene_key(scene):
    return _resolve_state._scene_key(scene)


def _scene_from_key(scene_id):
    return _resolve_state._scene_from_key(scene_id, _RESOLVE_STATE_CTX)


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


def _set_camera_inside_earth_warning(scene):
    return _view_telemetry.set_camera_inside_earth_warning(scene, ctx=_VIEW_TELEMETRY_CTX)


def _resolve_scope_altitude_info(scene, scope_mode="AUTO"):
    return _view_telemetry.resolve_scope_altitude_info(scene, _VIEW_TELEMETRY_CTX, scope_mode=scope_mode)


def _camera_signature(scene):
    return _view_telemetry.camera_signature(scene)


def _is_resolve_busy():
    return _resolve_state._is_resolve_busy(_RESOLVE_STATE_CTX)


def _normalize_texture_quality_mode(value):
    return _view_telemetry.normalize_texture_quality_mode(value)


def _output_resolution_signature(scene):
    return _view_telemetry.output_resolution_signature(scene, _VIEW_TELEMETRY_CTX)


def _tag_view3d_redraw():
    return _view_telemetry.tag_view3d_redraw(_VIEW_TELEMETRY_CTX)


def _canonical_tiles(tiles):
    return _view_telemetry.canonical_tiles(tiles)


def _estimate_download_bytes_for_visible_tiles(tiles, texture_quality_mode="PREVIEW"):
    return _view_telemetry.estimate_download_bytes_for_visible_tiles(
        tiles,
        _VIEW_TELEMETRY_CTX,
        texture_quality_mode=texture_quality_mode,
    )


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
        camera_inside_earth_warning_key=CAMERA_INSIDE_EARTH_WARNING_KEY,
        get_earth_object=get_earth_object,
        get_tile_utils=lambda: tile_utils,
        get_streaming_utils=lambda: streaming_utils,
        normalize_texture_quality_mode=_normalize_texture_quality_mode,
    )
    return ViewTelemetryContext(deps=deps)


def _build_handler_runtime_context():
    deps = HandlerRuntimeDeps(
        bpy=bpy,
        logger=logger,
        recoverable_exceptions=PLANETKA_RECOVERABLE_EXCEPTIONS,
        import_recoverable_exceptions=PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS,
        clear_resolve_in_flight=_clear_resolve_in_flight,
        iter_scenes=_iter_scenes,
        sync_idprops_from_props=_sync_idprops_from_props,
        get_earth_object=get_earth_object,
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
        get_streaming_utils=lambda: streaming_utils,
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
_HANDLER_RUNTIME_CTX = _build_handler_runtime_context()

# state.py remains the owner of the singleton view-telemetry context; the
# runtime module receives it explicitly instead of pulling facade globals.
_view_telemetry._VIEW_TELEMETRY_CTX = _VIEW_TELEMETRY_CTX
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
