import time


_HANDLER_RUNTIME_CTX = None
ANIMATION_EEVEE_FORCE_BUMP_RUNTIME_KEY = "planetka_anim_render_eevee_force_bump"


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

    deps.clear_auto_resolve_in_flight()
    state.render_job_active = False
    state.render_job_last_ended_epoch = int(state.render_job_epoch)
    ended_at = float(time.monotonic())
    state.render_job_last_ended_at = ended_at
    state.render_job_last_progress_at = ended_at
    if bool(cancelled):
        state.render_job_last_cancelled_epoch = int(state.render_job_epoch)

    deps.reset_navigation_shot_runtime_state()
    deps.reset_navigation_camera_control_runtime_state()
    deps.force_restore_navigation_adaptive_state()

    target_scene = scene
    if target_scene is None:
        target_scene = _safe_context_scene(deps)
    if target_scene is not None:
        props = getattr(target_scene, "planetka", None)
        try:
            auto_resolve_enabled = bool(getattr(props, "auto_resolve", False)) if props is not None else False
        except deps.recoverable_exceptions:
            auto_resolve_enabled = False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            auto_resolve_enabled = False
        if auto_resolve_enabled and not bool(cancelled):
            # Render completion can still be in a transient drawing/read-only state.
            # Avoid immediate post-render resolve requests to reduce write-state races.
            deps.mark_auto_resolve_dirty(target_scene, immediate=False)
            deps.request_auto_resolve(target_scene, immediate=False, mark_dirty=False)


def mark_render_job_started(scene=None, ctx=None):
    if ctx is None and _is_context(scene):
        ctx = scene
        scene = None
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    state = ctx.state

    if state.render_job_active:
        # Blender calls render_pre per frame during animation renders.
        # Treat the whole animation as one render job to avoid per-frame
        # self-heal churn and epoch flips during segment rendering.
        return int(state.render_job_epoch)
    started_at = float(time.monotonic())
    target_scene = scene
    if target_scene is None:
        target_scene = _safe_context_scene(deps)
    try:
        deps.self_heal_missing_cache_images_for_render(target_scene)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: render self-heal preflight failed", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        deps.logger.debug("Planetka: render self-heal preflight failed", exc_info=True)
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


def migrate_scene(scene, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps

    deps.migrate_scene_schema(scene, sync_idprops_fn=deps.sync_idprops_from_props, logger=deps.logger)
    for key in deps.legacy_scene_idprops:
        try:
            if key in scene:
                del scene[key]
        except deps.recoverable_exceptions:
            deps.logger.debug("Planetka: failed removing legacy scene idprop %s", key, exc_info=True)


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

    keyed_runtime_active = deps.scene_has_keyed_runtime_path(scene, deps.keyed_runtime_all_prop_paths)
    props = getattr(scene, "planetka", None)
    preset_active = False
    if props is not None:
        try:
            preset_token = str(getattr(props, "anim_camera_preset", "NONE") or "NONE").strip().upper()
        except deps.recoverable_exceptions:
            preset_token = "NONE"
        except (RuntimeError, TypeError, ValueError, AttributeError):
            preset_token = "NONE"
        if preset_token in {"PUSH_IN", "PULL_BACK"}:
            preset_token = "ZOOM"
        elif preset_token in {"ARC_LEFT", "ARC_RIGHT"}:
            preset_token = "ARC"
        elif preset_token == "FLYBY":
            preset_token = "NONE"
        preset_active = preset_token not in {"", "NONE"}
    if not (deps.is_render_job_active() or deps.is_animation_playing() or keyed_runtime_active or preset_active):
        deps.sync_navigation_controls_from_scene_camera(scene)

    if not deps.can_auto_resolve_run(scene):
        return

    deps.ensure_auto_resolve_service_running()
    deps.update_realtime_telemetry(scene)

    if deps.is_resolve_pipeline_busy():
        return

    trigger_signature = deps.make_depsgraph_trigger_signature(scene)
    deps.handle_timeline_motion_optimization(scene)
    deps.handle_viewport_motion_optimization(
        scene,
        deps.camera_signature(scene),
    )
    deps.handle_sunlight_motion_optimization(scene)
    deps.mark_auto_resolve_from_depsgraph_trigger(scene, trigger_signature)


def frame_change_post(scene, _depsgraph=None, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    state = ctx.state
    target_scene = scene
    if target_scene is None:
        target_scene = _safe_context_scene(deps)
    if target_scene is None:
        return

    signature = deps.keyed_runtime_signature(target_scene)
    scene_id = deps.scene_key(target_scene)
    last_map = state.frame_keyed_runtime_last_signature
    if signature is None:
        last_map.pop(scene_id, None)
        return

    previous = last_map.get(scene_id)
    if previous == signature:
        return
    last_map[scene_id] = signature

    nav_keyed = deps.scene_has_keyed_runtime_path(target_scene, deps.keyed_runtime_nav_prop_paths)
    focal_keyed = deps.scene_has_keyed_runtime_path(target_scene, deps.keyed_runtime_focal_prop_paths)
    sun_keyed = deps.scene_has_keyed_runtime_path(target_scene, deps.keyed_runtime_sun_prop_paths)
    if not (nav_keyed or focal_keyed or sun_keyed):
        return
    return


def load_post(_dummy, ctx=None):
    ctx = _coerce_ctx(ctx)
    deps = ctx.deps
    state = ctx.state

    state.frame_keyed_runtime_last_signature.clear()
    sync_logging_from_scenes(ctx)
    missing_cache_images, recovered_cache_images = deps.recover_missing_cache_image_paths_to_fallback()
    if int(missing_cache_images) > 0:
        deps.logger.warning(
            "Planetka: detected %d missing cached tile image(s) on file load; redirected %d to fallback placeholders.",
            int(missing_cache_images),
            int(recovered_cache_images),
        )
        scene = _safe_context_scene(deps)
        if scene is None:
            scene = next(iter(deps.iter_scenes()), None)
        if scene is not None:
            deps.schedule_load_recovery_resolve(scene)
    try:
        module_name = f"{deps.package_name}.unsupported" if deps.package_name else "unsupported"
        unsupported_module = deps.import_module(module_name)
        apply_fn = getattr(unsupported_module, "apply_runtime_unsupported_overrides", None)
        if callable(apply_fn):
            apply_fn()
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed applying unsupported startup overrides", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
        deps.logger.debug("Planetka: failed applying unsupported startup overrides", exc_info=True)
    try:
        auth_module = deps.import_module(f"{deps.package_name}.auth")
        is_authenticated = getattr(auth_module, deps.auth_is_authenticated_attr)
        prefs = deps.get_prefs()
        connected = bool(is_authenticated(prefs))
    except deps.import_recoverable_exceptions:
        connected = False

    for scene in deps.iter_scenes():
        try:
            if connected:
                scene[deps.account_panel_default_collapsed_key] = True
            elif deps.account_panel_default_collapsed_key in scene:
                del scene[deps.account_panel_default_collapsed_key]
        except deps.recoverable_exceptions:
            deps.logger.debug("Planetka: failed syncing account panel default-collapsed state", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            deps.logger.debug("Planetka: failed syncing account panel default-collapsed state", exc_info=True)
    deps.ensure_auto_resolve_service_running()
