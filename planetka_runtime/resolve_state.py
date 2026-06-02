import time
import threading
from dataclasses import dataclass, field


_RESOLVE_STATE_CTX = None
_ORPHAN_FINALIZE_QUEUE_GRACE_SEC = 5.0


def _require_ctx():
    ctx = _RESOLVE_STATE_CTX
    if ctx is None:
        raise RuntimeError("Planetka resolve state context is not configured.")
    return ctx


def _coerce_ctx(value=None):
    if value is not None and hasattr(value, "deps") and hasattr(value, "state"):
        return value
    return _require_ctx()


@dataclass
class ResolveDownloadJob:
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


def _is_resolve_download_job(job):
    return isinstance(job, (ResolveDownloadJob, dict))


def _job_field(job, name, default=None):
    if isinstance(job, ResolveDownloadJob):
        return getattr(job, name, default)
    if isinstance(job, dict):
        return job.get(name, default)
    return default


def _job_set_field(job, name, value):
    if isinstance(job, ResolveDownloadJob):
        setattr(job, name, value)
    elif isinstance(job, dict):
        job[name] = value


def _build_resolve_download_job(
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
    return ResolveDownloadJob(
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


def _is_resolve_busy(ctx=None):
    ctx = _coerce_ctx(ctx)
    state = ctx.state
    if state.in_flight:
        return True
    if state.download_thread is not None:
        return True
    with state.download_lock:
        if _is_resolve_download_job(state.download_active_job):
            return True
        if _is_resolve_download_job(state.download_pending_job):
            return True
        if isinstance(state.download_completed, dict):
            return True
    return False


def _job_quality_mode(job, deps):
    if not _is_resolve_download_job(job):
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
        active_job = state.download_active_job if _is_resolve_download_job(state.download_active_job) else None
        pending_job = state.download_pending_job if _is_resolve_download_job(state.download_pending_job) else None
        completed_payload = dict(state.download_completed) if isinstance(state.download_completed, dict) else None

    thread_running = state.download_thread is not None
    in_flight = bool(state.in_flight)
    pending_count = int((1 if active_job else 0) + (1 if pending_job else 0))
    active_request_id = None
    active_quality_mode = ""
    if _is_resolve_download_job(active_job):
        active_request_id = _job_field(active_job, "request_id")
        active_quality_mode = _job_quality_mode(active_job, deps)
    elif _is_resolve_download_job(pending_job):
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
        status.update({"code": "FINALIZING", "text": "Finalizing Resolve", "running": True})
        return status

    if thread_running and _is_resolve_download_job(active_job):
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
        can_orphan = not bool(in_flight) and not bool(thread_running) and active_job is None and pending_job is None
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
        status.update({"code": "FINALIZE_QUEUED", "text": "Download finished, waiting to finalize", "running": True})
        return status

    if pending_count > 0:
        status.update({"code": "QUEUED", "text": "Resolve queued", "running": True})
        return status

    return status
