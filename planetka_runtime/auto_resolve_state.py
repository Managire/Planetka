import time
import threading
from dataclasses import dataclass, field


_MOVED_NAMES = {
    "SceneAutoResolveState",
    "AutoResolveDownloadJob",
    "_is_auto_resolve_download_job",
    "_job_field",
    "_job_set_field",
    "_build_auto_resolve_download_job",
    "_scene_key",
    "_scene_from_key",
    "_coerce_scene_id",
    "_set_scene_auto_resolve_map_entry",
    "_read_scene_auto_resolve_state",
    "_write_scene_auto_resolve_state",
    "_make_depsgraph_trigger_signature",
    "_depsgraph_trigger_output_signature",
    "_mark_auto_resolve_from_depsgraph_trigger",
    "_is_resolve_pipeline_busy",
    "get_resolve_runtime_status",
}


def configure(runtime):
    module_globals = globals()
    for key, value in runtime.items():
        if key in _MOVED_NAMES:
            continue
        module_globals[key] = value


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


def get_resolve_runtime_status(scene=None):
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
