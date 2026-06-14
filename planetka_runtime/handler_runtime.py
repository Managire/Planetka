import time


_HANDLER_RUNTIME_CTX = None


def _require_ctx():
    ctx = _HANDLER_RUNTIME_CTX
    if ctx is None:
        raise RuntimeError("Planetka handler runtime context is not configured.")
    return ctx


def _is_context(value):
    return hasattr(value, "deps") and hasattr(value, "state")


def _coerce_ctx(value=None):
    if _is_context(value):
        return value
    return _require_ctx()


def _safe_context_scene(deps):
    try:
        return getattr(getattr(deps.bpy, "context", None), "scene", None)
    except deps.recoverable_exceptions:
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None


def recover_post_render_state(scene=None, cancelled=False, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    state = ctx.state

    deps.clear_resolve_in_flight()
    state.render_job_active = False
    state.render_job_last_ended_epoch = int(state.render_job_epoch)
    ended_at = float(time.monotonic())
    state.render_job_last_ended_at = ended_at
    state.render_job_last_progress_at = ended_at
    if bool(cancelled):
        state.render_job_last_cancelled_epoch = int(state.render_job_epoch)


def mark_render_job_started(scene=None, ctx=None):
    if ctx is None and _is_context(scene):
        ctx = scene
        scene = None
    ctx = _coerce_ctx(ctx)
    state = ctx.state

    if state.render_job_active:
        # Blender calls render_pre per frame during animation renders.
        # Treat the whole animation as one render job to avoid per-frame
        # self-heal churn and epoch flips during segment rendering.
        return int(state.render_job_epoch)
    started_at = float(time.monotonic())
    _ = scene
    # Render start must not resolve, download, or mutate texture assignments.
    # Rendering should use the scene exactly as currently prepared.
    state.render_job_epoch = int(state.render_job_epoch) + 1
    state.render_job_active = True
    state.render_job_last_ended_at = 0.0
    state.render_job_last_progress_at = started_at
    state.render_job_last_frame_written_at = 0.0
    state.render_job_last_frame_written = -1
    return int(state.render_job_epoch)


def mark_render_job_progress(scene=None, frame_written=False, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    state = ctx.state

    now = float(time.monotonic())
    state.render_job_last_progress_at = now
    if not bool(frame_written):
        return

    state.render_job_last_frame_written_at = now
    frame_value = -1
    target_scene = scene
    if target_scene is None:
        target_scene = _safe_context_scene(deps)
    if target_scene is not None:
        try:
            frame_value = int(getattr(target_scene, "frame_current", -1))
        except deps.recoverable_exceptions:
            frame_value = -1
        except (RuntimeError, TypeError, ValueError, AttributeError):
            frame_value = -1
    state.render_job_last_frame_written = int(frame_value)


def render_job_heartbeat(ctx=None):
    ctx = _coerce_ctx(ctx)
    state = ctx.state
    return {
        "active": bool(state.render_job_active),
        "epoch": int(state.render_job_epoch),
        "last_cancelled_epoch": int(state.render_job_last_cancelled_epoch),
        "last_progress_at": float(state.render_job_last_progress_at or 0.0),
        "last_frame_written_at": float(state.render_job_last_frame_written_at or 0.0),
        "last_frame_written": int(state.render_job_last_frame_written),
        "last_ended_at": float(state.render_job_last_ended_at or 0.0),
    }


