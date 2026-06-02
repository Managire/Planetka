import time


_HANDLER_RUNTIME_CTX = None
ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY = "planetka_anim_render_eevee_force_bump"
ATMOSPHERE_AUTO_SWITCH_ENGINE_KEY = "planetka_atmosphere_auto_switch_engine"


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

    deps.reset_navigation_shot_runtime_state()
    deps.reset_navigation_camera_control_runtime_state()


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


def sync_logging_from_scenes(ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    state = ctx.state

    if state.logging_syncing:
        return
    state.logging_syncing = True
    try:
        enabled = False
        for scene in deps.iter_scenes():
            props = getattr(scene, "planetka", None)
            if props and bool(getattr(props, "debug_logging", False)):
                enabled = True
                break
        deps.set_planetka_logging(enabled)
    finally:
        state.logging_syncing = False


def initialize_props_from_imported_planetka(scene, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    props = getattr(scene, "planetka", None) if scene else None
    if not props:
        return

    deps.sync_idprops_from_props(scene)


def _enforce_planetka_earth_surface_displacement_mode(scene, deps):
    if scene is None:
        return
    try:
        force_eevee_bump = bool(scene.get(ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY, False))
    except deps.recoverable_exceptions:
        force_eevee_bump = False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        force_eevee_bump = False
    if bool(force_eevee_bump):
        try:
            module_name = f"{deps.package_name}.animation_tools" if deps.package_name else "animation_tools"
            animation_tools = deps.import_module(module_name)
            enforce_bump_fn = getattr(animation_tools, "_set_earth_surface_materials_bump_only", None)
            if callable(enforce_bump_fn):
                enforce_bump_fn()
            return
        except deps.recoverable_exceptions:
            deps.logger.debug(
                "Planetka: failed enforcing EEVEE bump-only displacement mode in depsgraph runtime",
                exc_info=True,
            )
            return
        except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
            deps.logger.debug(
                "Planetka: failed enforcing EEVEE bump-only displacement mode in depsgraph runtime",
                exc_info=True,
            )
            return
    try:
        module_name = f"{deps.package_name}.asset_builder" if deps.package_name else "asset_builder"
        asset_builder = deps.import_module(module_name)
        enforce_fn = getattr(asset_builder, "enforce_earth_surface_displacement_and_bump", None)
        if callable(enforce_fn):
            enforce_fn(scene)
    except deps.recoverable_exceptions:
        deps.logger.debug(
            "Planetka: failed enforcing Earth surface displacement mode in depsgraph runtime",
            exc_info=True,
        )
    except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
        deps.logger.debug(
            "Planetka: failed enforcing Earth surface displacement mode in depsgraph runtime",
            exc_info=True,
        )


def _atmosphere_mode_for_render_engine(scene):
    try:
        engine = str(getattr(getattr(scene, "render", None), "engine", "") or "").strip().upper()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        engine = ""
    if engine == "CYCLES":
        return engine, "VOLUMETRIC"
    if engine.startswith("BLENDER_EEVEE"):
        return engine, "EEVEE"
    return engine, ""


def _sync_atmosphere_mode_to_render_engine(scene, deps):
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    try:
        enabled = bool(getattr(props, "auto_switch_atmosphere", True))
    except deps.recoverable_exceptions:
        enabled = True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        enabled = True
    if not enabled:
        return

    engine, desired_mode = _atmosphere_mode_for_render_engine(scene)
    if not desired_mode:
        return

    try:
        previous_engine = str(scene.get(ATMOSPHERE_AUTO_SWITCH_ENGINE_KEY, "") or "").strip().upper()
    except deps.recoverable_exceptions:
        previous_engine = ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        previous_engine = ""

    try:
        scene[ATMOSPHERE_AUTO_SWITCH_ENGINE_KEY] = engine
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing atmosphere auto-switch engine", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing atmosphere auto-switch engine", exc_info=True)

    try:
        current_mode = str(getattr(props, "atmosphere_mode", "VOLUMETRIC") or "VOLUMETRIC").strip().upper()
    except deps.recoverable_exceptions:
        current_mode = "VOLUMETRIC"
    except (RuntimeError, TypeError, ValueError, AttributeError):
        current_mode = "VOLUMETRIC"
    if previous_engine == engine and current_mode == desired_mode:
        return
    if current_mode == desired_mode:
        return
    try:
        if deps.get_earth_object() is None:
            return
    except deps.recoverable_exceptions:
        return
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return

    try:
        props.atmosphere_mode = desired_mode
        deps.sync_idprops_from_props(scene, ("atmosphere_mode", "auto_switch_atmosphere"))
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed auto-switching atmosphere for render engine", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed auto-switching atmosphere for render engine", exc_info=True)


def sync_atmosphere_mode_to_render_engine(scene=None, ctx=None):
    """Explicitly sync Planetka atmosphere mode to the active render engine.

    This is intentionally called from Planetka-controlled operations such as
    Resolve/Create Earth instead of depsgraph updates. Renderer changes alone
    should not mutate the scene until the user runs Resolve Planetka.
    """
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    target_scene = scene
    if target_scene is None:
        target_scene = _safe_context_scene(deps)
    if target_scene is None:
        return
    _sync_atmosphere_mode_to_render_engine(target_scene, deps)


def depsgraph_update_post(_scene, _depsgraph, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps

    scene = _scene
    if scene is None:
        scene = _safe_context_scene(deps)
    if scene is None:
        return

    _enforce_planetka_earth_surface_displacement_mode(scene, deps)

    if deps.is_navigation_user_edit_active(scene):
        return


def load_post(_dummy, ctx=None):
    ctx = _coerce_ctx(ctx)
    sync_logging_from_scenes(ctx)
