import time
import threading
from dataclasses import dataclass, field


_AUTO_RESOLVE_STATE_CTX = None
_ORPHAN_FINALIZE_QUEUE_GRACE_SEC = 5.0


def _require_ctx():
    ctx = _AUTO_RESOLVE_STATE_CTX
    if ctx is None:
        raise RuntimeError("Planetka auto resolve state context is not configured.")
    return ctx


def _coerce_ctx(value=None):
    if value is not None and hasattr(value, "deps") and hasattr(value, "state"):
        return value
    return _require_ctx()


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
    ctx=None,
):
    ctx = _coerce_ctx(ctx)
    return AutoResolveDownloadJob(
        epoch=int(epoch),
        request_id=int(request_id),
        scene_id=int(scene_id),
        target_tiles=tuple(target_tiles or ()),
        camera_signature=camera_signature,
        output_signature=output_signature,
        manual_request=bool(manual_request),
        base_path=str(base_path or ""),
        texture_quality_mode=ctx.deps.normalize_texture_quality_mode(texture_quality_mode),
        nav_latitude_deg=float(nav_latitude_deg or 0.0),
        nav_longitude_deg=float(nav_longitude_deg or 0.0),
        nav_altitude_km=float(nav_altitude_km or 0.0),
    )


def _scene_key(scene):
    return int(getattr(scene, "as_pointer", lambda: id(scene))())


def _scene_from_key(scene_id, ctx=None):
    ctx = _coerce_ctx(ctx)
    try:
        target_id = int(scene_id)
    except (TypeError, ValueError):
        return None
    for scene in ctx.deps.iter_scenes():
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


def _read_scene_auto_resolve_state(scene_or_id, ctx=None):
    ctx = _coerce_ctx(ctx)
    scene_id = _coerce_scene_id(scene_or_id)
    if scene_id is None:
        return None
    state = ctx.state
    return SceneAutoResolveState(
        scene_id=scene_id,
        next_due_time=state.next_due_time.get(scene_id),
        last_camera_signature=state.last_camera_signature.get(scene_id),
        last_output_signature=state.last_output_signature.get(scene_id),
        last_change_time=state.last_change_time.get(scene_id),
        last_resolve_time=state.last_resolve_time.get(scene_id),
        last_processed_signature=state.last_processed_signature.get(scene_id),
        pending_output_change=bool(state.pending_output_change.get(scene_id, False)),
        trigger_last_signature=state.trigger_last_signature.get(scene_id),
    )


def _write_scene_auto_resolve_state(scene_state, ctx=None):
    ctx = _coerce_ctx(ctx)
    if not isinstance(scene_state, SceneAutoResolveState):
        return
    scene_id = int(scene_state.scene_id)
    state = ctx.state
    _set_scene_auto_resolve_map_entry(state.next_due_time, scene_id, scene_state.next_due_time)
    _set_scene_auto_resolve_map_entry(state.last_camera_signature, scene_id, scene_state.last_camera_signature)
    _set_scene_auto_resolve_map_entry(state.last_output_signature, scene_id, scene_state.last_output_signature)
    _set_scene_auto_resolve_map_entry(state.last_change_time, scene_id, scene_state.last_change_time)
    _set_scene_auto_resolve_map_entry(state.last_resolve_time, scene_id, scene_state.last_resolve_time)
    _set_scene_auto_resolve_map_entry(
        state.last_processed_signature,
        scene_id,
        scene_state.last_processed_signature,
    )
    if bool(scene_state.pending_output_change):
        state.pending_output_change[scene_id] = True
    else:
        state.pending_output_change.pop(scene_id, None)
    _set_scene_auto_resolve_map_entry(state.trigger_last_signature, scene_id, scene_state.trigger_last_signature)


def _make_depsgraph_trigger_signature(scene, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    resolve_signature = deps.camera_signature(scene)
    if deps.auto_resolve_scope_mode(scene) == "ACTIVE_VIEW":
        active_signature = deps.active_view_signature()
        if active_signature is not None:
            resolve_signature = ("ACTIVE_VIEW", active_signature)
    if resolve_signature is None:
        return None
    output_signature = deps.output_resolution_signature(scene)
    return ("TRIGGER_V2", resolve_signature, output_signature)


def _depsgraph_trigger_output_signature(signature):
    if (
        isinstance(signature, tuple)
        and len(signature) == 3
        and str(signature[0]) == "TRIGGER_V2"
    ):
        return signature[2]
    return None


def _mark_auto_resolve_from_depsgraph_trigger(scene, trigger_signature, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    if scene is None or trigger_signature is None:
        return False
    scene_state = _read_scene_auto_resolve_state(scene, ctx)
    if scene_state is None:
        return False

    previous_trigger_signature = scene_state.trigger_last_signature
    if previous_trigger_signature is None:
        scene_state.trigger_last_signature = trigger_signature
        _write_scene_auto_resolve_state(scene_state, ctx)
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
    _write_scene_auto_resolve_state(scene_state, ctx)
    deps.request_auto_resolve(scene, immediate=bool(immediate), mark_dirty=False)
    return True


def _is_resolve_pipeline_busy(ctx=None):
    ctx = _coerce_ctx(ctx)
    state = ctx.state
    if state.in_flight:
        return True
    if state.download_thread is not None:
        return True
    with state.download_lock:
        if _is_auto_resolve_download_job(state.download_active_job):
            return True
        if _is_auto_resolve_download_job(state.download_pending_job):
            return True
        if isinstance(state.download_completed, dict):
            return True
    return False


def _job_quality_mode(job, deps):
    if not _is_auto_resolve_download_job(job):
        return ""
    try:
        return deps.normalize_texture_quality_mode(_job_field(job, "texture_quality_mode", "PREVIEW"))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return "PREVIEW"


def get_resolve_runtime_status(scene=None, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    state = ctx.state
    if scene is None:
        scene = getattr(getattr(deps.bpy, "context", None), "scene", None)

    with state.download_lock:
        active_job = state.download_active_job if _is_auto_resolve_download_job(state.download_active_job) else None
        pending_job = state.download_pending_job if _is_auto_resolve_download_job(state.download_pending_job) else None
        completed_payload = dict(state.download_completed) if isinstance(state.download_completed, dict) else None

    thread_running = state.download_thread is not None
    in_flight = bool(state.in_flight)
    pending_count = int((1 if active_job else 0) + (1 if pending_job else 0))
    active_request_id = None
    active_quality_mode = ""
    if _is_auto_resolve_download_job(active_job):
        active_request_id = _job_field(active_job, "request_id")
        active_quality_mode = _job_quality_mode(active_job, deps)
    elif _is_auto_resolve_download_job(pending_job):
        active_request_id = _job_field(pending_job, "request_id")
        active_quality_mode = _job_quality_mode(pending_job, deps)
    if not active_quality_mode and isinstance(completed_payload, dict):
        active_quality_mode = _job_quality_mode(completed_payload.get("job"), deps)

    status = {
        "code": "IDLE",
        "text": "Idle",
        "running": False,
        "active_request_id": active_request_id,
        "pending_count": pending_count,
        "completed_pending": bool(completed_payload),
        "quality_mode": active_quality_mode,
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
            r2_source = deps.get_r2_source()
            get_progress = getattr(r2_source, "get_download_progress", None) if r2_source is not None else None
            if callable(get_progress):
                progress = get_progress() or {}
                active_requests = int(progress.get("active_requests", 0) or 0)
                downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
                preparing = bool(active_requests <= 0 and downloaded_bytes <= 0)
        except deps.recoverable_exceptions:
            preparing = False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            preparing = False
        status.update({
            "code": "PREPARING" if preparing else "DOWNLOADING",
            "text": "Preparing Textures" if preparing else "Downloading Data",
            "running": True,
        })
        return status

    if isinstance(completed_payload, dict):
        # Self-heal stale completed payloads that got orphaned (no active/pending/thread work
        # and not currently rendering), otherwise UI can stay stuck on FINALIZE_QUEUED forever.
        can_orphan = (
            not bool(in_flight)
            and not bool(thread_running)
            and active_job is None
            and pending_job is None
        )
        if can_orphan:
            render_running = False
            try:
                is_render_job_active = getattr(deps, "is_render_job_active", None)
                if callable(is_render_job_active):
                    render_running = bool(is_render_job_active())
            except deps.recoverable_exceptions:
                render_running = False
            except (RuntimeError, TypeError, ValueError, AttributeError):
                render_running = False
            if not render_running:
                now = float(time.monotonic())
                completed_at = 0.0
                try:
                    completed_at = float(completed_payload.get("completed_at", 0.0) or 0.0)
                except (TypeError, ValueError, AttributeError):
                    completed_at = 0.0
                age = max(0.0, now - completed_at) if completed_at > 0.0 else float(_ORPHAN_FINALIZE_QUEUE_GRACE_SEC)
                if age >= float(_ORPHAN_FINALIZE_QUEUE_GRACE_SEC):
                    with state.download_lock:
                        if isinstance(state.download_completed, dict):
                            state.download_completed = None
                    completed_payload = None

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
