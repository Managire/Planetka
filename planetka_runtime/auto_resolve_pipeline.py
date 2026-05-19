import json
import threading
import time

_AUTO_RESOLVE_DOWNLOAD_CTX = None
_AUTO_RESOLVE_DECISION_CTX = None
_AUTO_RESOLVE_NONCRITICAL_CTX = None
_LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY = "planetka_last_resolve_texture_quality_mode"
_FULL_QUALITY_HOLD_SIGNATURE_KEY = "planetka_full_quality_hold_signature"
_LAST_FULL_SOURCE_TILES_KEY = "planetka_last_full_source_tiles"


def _quality_mode_for_job(deps, job):
    try:
        return deps.normalize_texture_quality_mode(
            deps.job_field(job, "texture_quality_mode", "PREVIEW")
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return "PREVIEW"


def _signature_token(signature):
    try:
        return json.dumps(signature, sort_keys=True, separators=(",", ":"), default=str)
    except (RuntimeError, TypeError, ValueError):
        return repr(signature)


def _scene_last_resolve_quality(scene, deps):
    if scene is None:
        return "PREVIEW"
    try:
        return deps.normalize_texture_quality_mode(
            scene.get(_LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY, "PREVIEW")
        )
    except deps.recoverable_exceptions:
        return "PREVIEW"
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return "PREVIEW"


def _scene_last_full_source_tiles(scene, deps):
    if scene is None:
        return ()
    try:
        return deps.canonical_tiles(scene.get(_LAST_FULL_SOURCE_TILES_KEY, ()))
    except deps.recoverable_exceptions:
        return ()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ()


def _store_full_quality_hold(scene, deps, signature):
    if scene is None or signature is None:
        return
    try:
        scene[_FULL_QUALITY_HOLD_SIGNATURE_KEY] = _signature_token(signature)
        scene[_LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY] = "FULL"
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing Full Quality hold signature", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed storing Full Quality hold signature", exc_info=True)


def _clear_full_quality_hold(scene, deps, *, mark_preview=False):
    if scene is None:
        return
    try:
        if _FULL_QUALITY_HOLD_SIGNATURE_KEY in scene:
            del scene[_FULL_QUALITY_HOLD_SIGNATURE_KEY]
        if bool(mark_preview) and _scene_last_resolve_quality(scene, deps) == "FULL":
            scene[_LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY] = "PREVIEW"
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed clearing Full Quality hold signature", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed clearing Full Quality hold signature", exc_info=True)


def _full_quality_hold_status(scene, deps, scope, resolve_signature):
    if _scene_last_resolve_quality(scene, deps) != "FULL":
        return "NONE"
    try:
        stored_token = str(scene.get(_FULL_QUALITY_HOLD_SIGNATURE_KEY, "") or "").strip()
    except deps.recoverable_exceptions:
        stored_token = ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        stored_token = ""
    if not stored_token:
        return "NONE"
    if str(scope or "").strip().upper() == "ACTIVE_VIEW" or _is_active_view_resolve_signature(resolve_signature):
        _clear_full_quality_hold(scene, deps, mark_preview=True)
        return "CLEARED"
    if stored_token != _signature_token(resolve_signature):
        _clear_full_quality_hold(scene, deps, mark_preview=True)
        return "CLEARED"
    return "HOLD"


def _require_download_ctx():
    ctx = _AUTO_RESOLVE_DOWNLOAD_CTX
    if ctx is None:
        raise RuntimeError("Planetka auto-resolve download context is not configured.")
    return ctx


def _require_decision_ctx():
    ctx = _AUTO_RESOLVE_DECISION_CTX
    if ctx is None:
        raise RuntimeError("Planetka auto-resolve decision context is not configured.")
    return ctx


def _require_noncritical_ctx():
    ctx = _AUTO_RESOLVE_NONCRITICAL_CTX
    if ctx is None:
        raise RuntimeError("Planetka auto-resolve noncritical context is not configured.")
    return ctx


def _ctx_mark_auto_resolve_dirty(ctx, scene, immediate=False, force_resolve=False):
    deps = ctx.deps
    settings = ctx.settings
    if not scene:
        return
    scene_state = deps.read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return
    now = time.monotonic()
    scene_state.last_camera_signature = None
    scene_state.last_output_signature = None
    scene_state.last_processed_signature = None
    scene_state.pending_output_change = bool(force_resolve)
    scene_state.last_change_time = now - (settings.idle_sec_default if immediate else 0.0)
    deps.write_scene_auto_resolve_state(scene_state)


def _mark_auto_resolve_dirty(scene, immediate=False, force_resolve=False):
    return _ctx_mark_auto_resolve_dirty(
        _require_decision_ctx(),
        scene,
        immediate=immediate,
        force_resolve=force_resolve,
    )


def _ctx_auto_resolve_idle_seconds(ctx, scene):
    settings = ctx.settings
    props = getattr(scene, "planetka", None) if scene is not None else None
    try:
        idle_sec = float(getattr(props, "auto_resolve_idle_sec", settings.idle_sec_default))
    except (TypeError, ValueError):
        idle_sec = settings.idle_sec_default
    return max(0.1, min(3.0, idle_sec))


def _auto_resolve_idle_seconds(scene):
    return _ctx_auto_resolve_idle_seconds(_require_decision_ctx(), scene)


def _ctx_is_navigation_user_edit_active(ctx, scene):
    deps = ctx.deps
    if scene is None:
        return False
    now = time.monotonic()
    idle_window = _ctx_auto_resolve_idle_seconds(ctx, scene)
    guard_window = max(float(idle_window), float(deps.nav_camera_control_sync_grace_sec))
    return (now - float(deps.get_navigation_user_edit_last_touch())) < guard_window


def _is_navigation_user_edit_active(scene):
    return _ctx_is_navigation_user_edit_active(_require_decision_ctx(), scene)


def _ctx_active_view_monitor_interval_seconds(ctx, scene):
    return _ctx_auto_resolve_idle_seconds(ctx, scene)


def _active_view_monitor_interval_seconds(scene):
    return _ctx_active_view_monitor_interval_seconds(_require_decision_ctx(), scene)


def _ctx_arm_auto_resolve_timer(ctx, force_immediate=False):
    deps = ctx.deps
    state = ctx.state
    try:
        if force_immediate and deps.bpy.app.timers.is_registered(_auto_resolve_timer):
            deps.bpy.app.timers.unregister(_auto_resolve_timer)
            state.timer_running = False
        if not deps.bpy.app.timers.is_registered(_auto_resolve_timer):
            deps.bpy.app.timers.register(
                _auto_resolve_timer,
                first_interval=0.0 if force_immediate else 0.05,
                persistent=True,
            )
        state.timer_running = True
    except deps.recoverable_exceptions:
        state.timer_running = False
        deps.logger.debug("Planetka: failed arming auto-resolve timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        state.timer_running = False
        deps.logger.debug("Planetka: failed arming auto-resolve timer", exc_info=True)


def _arm_auto_resolve_timer(force_immediate=False):
    return _ctx_arm_auto_resolve_timer(_require_decision_ctx(), force_immediate=force_immediate)


def _ctx_auto_resolve_download_job_signature(ctx, job):
    deps = ctx.deps
    if not deps.is_auto_resolve_download_job(job):
        return None
    return (
        int(deps.job_field(job, "scene_id", 0) or 0),
        tuple(deps.job_field(job, "target_tiles", ()) or ()),
        deps.job_field(job, "camera_signature"),
        deps.job_field(job, "output_signature"),
        deps.normalize_texture_quality_mode(deps.job_field(job, "texture_quality_mode", "PREVIEW")),
    )


def _auto_resolve_download_job_signature(job):
    return _ctx_auto_resolve_download_job_signature(_require_download_ctx(), job)


def _ctx_arm_auto_resolve_download_timer(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings
    try:
        already = bool(deps.bpy.app.timers.is_registered(_auto_resolve_download_pump_timer))
        if not already:
            deps.bpy.app.timers.register(
                _auto_resolve_download_pump_timer,
                first_interval=settings.download_pump_interval_sec,
                persistent=True,
            )
        now_registered = bool(deps.bpy.app.timers.is_registered(_auto_resolve_download_pump_timer))
        deps.resolve_trace(
            f"Pump arm requested (already={already}, now_registered={now_registered})"
        )
        state.download_timer_running = True
    except deps.recoverable_exceptions:
        state.download_timer_running = False
        deps.resolve_trace("Pump arm failed with recoverable exception")
        deps.logger.debug("Planetka: failed arming auto-resolve download timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        state.download_timer_running = False
        deps.resolve_trace("Pump arm failed with runtime/type/value exception")
        deps.logger.debug("Planetka: failed arming auto-resolve download timer", exc_info=True)


def _arm_auto_resolve_download_timer():
    return _ctx_arm_auto_resolve_download_timer(_require_download_ctx())


def _ctx_start_auto_resolve_download_thread(ctx, job):
    deps = ctx.deps
    state = ctx.state
    if not deps.is_auto_resolve_download_job(job):
        return
    worker = threading.Thread(
        target=_ctx_auto_resolve_download_worker,
        args=(ctx, job),
        name="PlanetkaAutoResolveDownload",
        daemon=True,
    )
    state.download_thread = worker
    worker.start()
    _show_download_status_popup()


def _start_auto_resolve_download_thread(job):
    return _ctx_start_auto_resolve_download_thread(_require_download_ctx(), job)


def _show_download_status_popup():
    # Disabled due Blender 5.1 native crash inside popup cancel path:
    # wm_operator_ui_popup_cancel -> ui_popup_handler (SIGSEGV).
    # Keep runtime status in Status Check panel only until a safer overlay path is implemented.
    return


def _ctx_auto_resolve_texture_quality_mode(
    ctx,
    scene,
    props=None,
    manual_request=False,
    texture_quality_mode_override=None,
):
    deps = ctx.deps
    try:
        override_text = str(texture_quality_mode_override or "").strip()
        return deps.normalize_texture_quality_mode(
            override_text if override_text else getattr(props, "texture_quality_mode", "PREVIEW")
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass
    return "PREVIEW"


def _ctx_schedule_auto_resolve_download(
    ctx,
    scene,
    target_tiles,
    camera_signature,
    output_signature,
    manual_request=False,
    texture_quality_mode_override=None,
):
    deps = ctx.deps
    state = ctx.state

    if scene is None:
        return False

    # Keep auto-fix notices visible only until the next resolve request starts.
    deps.clear_status_notices(scene)

    scene_id = deps.scene_key(scene)
    prefs = deps.get_prefs()
    props = getattr(scene, "planetka", None)
    base_path = str(getattr(prefs, "texture_base_path", "") or "") if prefs else ""
    texture_quality_mode = _ctx_auto_resolve_texture_quality_mode(
        ctx,
        scene,
        props,
        manual_request=manual_request,
        texture_quality_mode_override=texture_quality_mode_override,
    )
    target_tiles_tuple = tuple(target_tiles or ())
    try:
        nav_latitude_deg = float(getattr(props, "nav_latitude_deg", 0.0)) if props is not None else 0.0
    except deps.recoverable_exceptions:
        nav_latitude_deg = 0.0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        nav_latitude_deg = 0.0
    try:
        nav_longitude_deg = float(getattr(props, "nav_longitude_deg", 0.0)) if props is not None else 0.0
    except deps.recoverable_exceptions:
        nav_longitude_deg = 0.0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        nav_longitude_deg = 0.0
    try:
        nav_altitude_km = max(0.0, float(getattr(props, "nav_altitude_km", 0.0))) if props is not None else 0.0
    except deps.recoverable_exceptions:
        nav_altitude_km = 0.0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        nav_altitude_km = 0.0

    def _is_manual_full_job(job):
        return (
            deps.is_auto_resolve_download_job(job)
            and bool(deps.job_field(job, "manual_request", False))
            and deps.normalize_texture_quality_mode(
                deps.job_field(job, "texture_quality_mode", "PREVIEW")
            ) == "FULL"
        )

    job_to_start = None
    should_arm_timer = False
    with state.download_lock:
        epoch = int(state.download_epoch)
        state.download_request_counter += 1
        request_id = int(state.download_request_counter)
        new_job = deps.build_auto_resolve_download_job(
            epoch=epoch,
            request_id=request_id,
            scene_id=scene_id,
            target_tiles=target_tiles_tuple,
            camera_signature=camera_signature,
            output_signature=output_signature,
            manual_request=manual_request,
            base_path=base_path,
            texture_quality_mode=texture_quality_mode,
            nav_latitude_deg=nav_latitude_deg,
            nav_longitude_deg=nav_longitude_deg,
            nav_altitude_km=nav_altitude_km,
        )

        new_sig = _ctx_auto_resolve_download_job_signature(ctx, new_job)
        active_sig = _ctx_auto_resolve_download_job_signature(ctx, state.download_active_job)
        pending_sig = _ctx_auto_resolve_download_job_signature(ctx, state.download_pending_job)
        completed_job = (
            state.download_completed.get("job")
            if isinstance(state.download_completed, dict)
            else None
        )
        suppress_auto_preview_for_manual_full = (
            not bool(manual_request)
            and texture_quality_mode == "PREVIEW"
            and (
                _is_manual_full_job(state.download_active_job)
                or _is_manual_full_job(state.download_pending_job)
                or _is_manual_full_job(completed_job)
            )
        )
        if suppress_auto_preview_for_manual_full:
            deps.resolve_trace(
                f"queue suppressed automatic Preview request_id={request_id}; "
                "manual Full Quality resolve is active"
            )
            should_arm_timer = (
                state.download_active_job is not None
                or state.download_pending_job is not None
                or state.download_completed is not None
            )
        elif new_sig == active_sig or new_sig == pending_sig:
            if bool(manual_request):
                if new_sig == active_sig and deps.is_auto_resolve_download_job(state.download_active_job):
                    deps.job_set_field(state.download_active_job, "manual_request", True)
                if new_sig == pending_sig and deps.is_auto_resolve_download_job(state.download_pending_job):
                    deps.job_set_field(state.download_pending_job, "manual_request", True)
            deps.resolve_trace(
                f"queue dedupe request_id={request_id} manual={bool(manual_request)} signature={new_sig!r}"
            )
            should_arm_timer = (
                state.download_active_job is not None
                or state.download_pending_job is not None
                or state.download_completed is not None
            )
        else:
            state.download_pending_job = new_job
            # Cancel in-flight download immediately when a newer request arrives.
            # The latest request should start as soon as possible.
            if deps.is_auto_resolve_download_job(state.download_active_job):
                active_cancel_event = deps.job_field(state.download_active_job, "cancel_event")
                if active_cancel_event is not None:
                    try:
                        active_cancel_event.set()
                    except deps.recoverable_exceptions:
                        deps.logger.debug("Planetka: failed signaling active resolve cancellation", exc_info=True)
                    except (RuntimeError, TypeError, ValueError, AttributeError):
                        deps.logger.debug("Planetka: failed signaling active resolve cancellation", exc_info=True)
            if state.download_active_job is None:
                state.download_active_job = state.download_pending_job
                state.download_pending_job = None
                job_to_start = state.download_active_job
            deps.resolve_trace(
                f"queue request_id={request_id} manual={bool(manual_request)} scene={scene_id} tiles={len(target_tiles_tuple)}"
            )
            should_arm_timer = True

    if deps.is_auto_resolve_download_job(job_to_start):
        _ctx_start_auto_resolve_download_thread(ctx, job_to_start)
    if should_arm_timer:
        _ctx_arm_auto_resolve_download_timer(ctx)
    return should_arm_timer


def _schedule_auto_resolve_download(
    scene,
    target_tiles,
    camera_signature,
    output_signature,
    manual_request=False,
    texture_quality_mode_override=None,
):
    return _ctx_schedule_auto_resolve_download(
        _require_download_ctx(),
        scene,
        target_tiles,
        camera_signature,
        output_signature,
        manual_request=manual_request,
        texture_quality_mode_override=texture_quality_mode_override,
    )


def _ctx_queue_resolve_download(ctx, scene, target_tiles, manual_request=False, texture_quality_mode_override=None):
    deps = ctx.deps
    state = ctx.state
    if scene is None:
        return False
    if bool(manual_request) and deps.is_render_job_active():
        # Manual resolves should be blocked only while Blender is actually write-locked.
        # A short post-render guard window is used for auto-resolve reliability, but should
        # not reject explicit user resolve actions once write access is available again.
        lock_reason = _ctx_blend_data_write_lock_reason(ctx)
        if lock_reason:
            deps.logger.info(
                "Planetka: ignoring deferred queued resolve request during active render lock (%s).",
                str(lock_reason),
            )
            return False
    camera_signature = deps.camera_signature(scene)
    if camera_signature is None:
        return False
    output_signature = deps.output_resolution_signature(scene)
    queued = _ctx_schedule_auto_resolve_download(
        ctx,
        scene,
        tuple(target_tiles or ()),
        camera_signature,
        output_signature,
        manual_request=bool(manual_request),
        texture_quality_mode_override=texture_quality_mode_override,
    )
    if queued:
        state.last_change_time[deps.scene_key(scene)] = time.monotonic()
    return bool(queued)


def queue_resolve_download(scene, target_tiles, manual_request=False, texture_quality_mode_override=None):
    return _ctx_queue_resolve_download(
        _require_download_ctx(),
        scene,
        target_tiles,
        manual_request=manual_request,
        texture_quality_mode_override=texture_quality_mode_override,
    )


def _ctx_mark_manual_queued_resolve_error(ctx, scene, message):
    deps = ctx.deps
    text = str(message or "Unknown queued resolve error")
    deps.logger.error("Planetka queued resolve failed: %s", text)
    if scene is None:
        return
    try:
        scene["planetka_last_resolve_error"] = text
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing queued resolve error on scene", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed storing queued resolve error on scene", exc_info=True)


def _mark_manual_queued_resolve_error(scene, message):
    return _ctx_mark_manual_queued_resolve_error(_require_download_ctx(), scene, message)


def _ctx_read_scene_last_resolve_error(_ctx, scene):
    recoverable_exceptions = _ctx.deps.recoverable_exceptions
    if scene is None:
        return ""
    try:
        return str(scene.get("planetka_last_resolve_error", "") or "").strip()
    except recoverable_exceptions:
        return ""
    except (RuntimeError, TypeError, ValueError):
        return ""


def _read_scene_last_resolve_error(scene):
    return _ctx_read_scene_last_resolve_error(_require_download_ctx(), scene)


def _ctx_store_resolve_summary(
    ctx,
    scene,
    tile_count,
    summary_total_bytes,
    total_seconds,
    *,
    log_label="Planetka: failed storing resolve summary",
):
    deps = ctx.deps
    if scene is None:
        return
    try:
        scene[deps.last_resolve_tile_count_key] = int(max(0, int(tile_count)))
        scene[deps.last_resolve_downloaded_mb_key] = float(
            max(0.0, float(summary_total_bytes) / float(1024.0 ** 2))
        )
        # Keep legacy key updated for backward compatibility with older UI builds.
        scene[deps.last_resolve_downloaded_gb_key] = float(
            max(0.0, float(summary_total_bytes) / float(1024.0 ** 3))
        )
        scene[deps.last_resolve_total_seconds_key] = float(max(0.0, float(total_seconds)))
    except deps.recoverable_exceptions:
        deps.logger.debug(str(log_label or "Planetka: failed storing resolve summary"), exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug(str(log_label or "Planetka: failed storing resolve summary"), exc_info=True)


def _store_resolve_summary(
    scene,
    tile_count,
    summary_total_bytes,
    total_seconds,
    *,
    log_label="Planetka: failed storing resolve summary",
):
    return _ctx_store_resolve_summary(
        _require_download_ctx(),
        scene,
        tile_count,
        summary_total_bytes,
        total_seconds,
        log_label=log_label,
    )


def _ctx_write_last_resolve_summary(ctx, scene, tile_count, summary_total_bytes, total_seconds):
    _ctx_store_resolve_summary(
        ctx,
        scene,
        tile_count,
        summary_total_bytes,
        total_seconds,
        log_label="Planetka: failed storing queued/auto resolve summary",
    )


def _write_last_resolve_summary(scene, tile_count, summary_total_bytes, total_seconds):
    return _ctx_write_last_resolve_summary(
        _require_download_ctx(),
        scene,
        tile_count,
        summary_total_bytes,
        total_seconds,
    )


def _is_non_retryable_resolve_error(message):
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            "pka-res-006",
            "download completed with missing files",
            "resolve integrity check failed",
            "panorama resolve exceeds tile limit",
            "no fallback parent found",
            "account blocked",
        )
    )


def _is_blend_data_readonly_error(message):
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            "cannot modify blend data in this state",
            "writing to id classes in this context is not allowed",
            "readonly state",
            "read-only state",
            "drawing/rendering",
        )
    )


def _ctx_handle_apply_readonly_failure(ctx, scene, job, manual_request, lock_reason):
    deps = ctx.deps
    settings = ctx.settings
    reason = str(lock_reason or "blend data read-only").strip() or "blend data read-only"
    now = time.monotonic()
    try:
        lock_since = float(deps.job_field(job, "apply_operator_lock_since", 0.0) or 0.0)
    except (TypeError, ValueError):
        lock_since = 0.0
    if lock_since <= 0.0:
        lock_since = now
    try:
        lock_attempts = int(deps.job_field(job, "apply_operator_lock_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        lock_attempts = 1
    deps.job_set_field(job, "apply_operator_lock_since", float(lock_since))
    deps.job_set_field(job, "apply_operator_lock_attempts", int(max(1, lock_attempts)))
    waited_sec = max(0.0, float(now) - float(lock_since))
    wait_budget_sec = min(
        float(settings.download_completed_max_age_sec),
        max(float(settings.download_scene_wait_sec), 6.0),
    )
    if waited_sec < wait_budget_sec:
        deps.resolve_trace(
            "Apply deferred because Blender data is still read-only "
            f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, "
            f"attempts={lock_attempts}, reason={reason})"
        )
        # Keep completed payload queued; pump will retry the same apply later.
        return None

    deps.resolve_trace(
        "Apply payload dropped after persistent read-only Blender state "
        f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, "
        f"attempts={lock_attempts}, reason={reason})"
    )
    deps.logger.warning(
        "Planetka: dropping completed auto-resolve payload after %.2fs waiting for apply write access "
        "(request_id=%s, attempts=%d, reason=%s).",
        float(waited_sec),
        str(deps.job_field(job, "request_id", "")),
        int(lock_attempts),
        str(reason),
    )
    deps.job_set_field(job, "apply_operator_lock_since", 0.0)
    deps.job_set_field(job, "apply_operator_lock_attempts", 0)
    if manual_request:
        _ctx_mark_manual_queued_resolve_error(
            ctx,
            scene,
            (
                "Apply deferred too long because Blender data stayed read-only "
                f"({reason}); try Resolve again."
            ),
        )
    else:
        deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
    return False


def _ctx_mark_auto_resolve_terminal_failure(ctx, scene, scene_id, job, message):
    deps = ctx.deps
    if scene is None:
        return
    text = str(message or "Planetka auto-resolve failed.").strip() or "Planetka auto-resolve failed."
    try:
        scene["planetka_last_resolve_error"] = text
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing auto-resolve terminal error on scene", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed storing auto-resolve terminal error on scene", exc_info=True)

    now = time.monotonic()
    latest_signature = None
    if deps.is_auto_resolve_download_job(job):
        latest_signature = deps.job_field(job, "camera_signature")
    if latest_signature is None:
        latest_signature = deps.camera_signature(scene)
    scene_state = deps.read_scene_auto_resolve_state(scene_id)
    if scene_state is not None:
        if latest_signature is not None:
            scene_state.last_camera_signature = latest_signature
            scene_state.last_processed_signature = latest_signature
        scene_state.last_resolve_time = now
        scene_state.last_change_time = now
        scene_state.pending_output_change = False
        deps.write_scene_auto_resolve_state(scene_state)
    deps.viewport_scope_last_resolve_time[scene_id] = now


def _mark_auto_resolve_terminal_failure(scene, scene_id, job, message):
    return _ctx_mark_auto_resolve_terminal_failure(_require_download_ctx(), scene, scene_id, job, message)


def _ctx_handle_auto_resolve_download_failure(ctx, job, error_message):
    deps = ctx.deps
    try:
        scene_id = int(deps.job_field(job, "scene_id", 0) or 0)
    except (TypeError, ValueError):
        return
    scene = deps.scene_from_key(scene_id)
    if scene is None:
        return

    if bool(deps.job_field(job, "manual_request", False)):
        deps.resolve_trace(
            "Download finished with error "
            f"(manual={bool(deps.job_field(job, 'manual_request', False))}, request_id={deps.job_field(job, 'request_id')}, "
            f"error={str(error_message or '').strip() or 'unknown'})"
        )
        if _quality_mode_for_job(deps, job) == "FULL":
            _clear_full_quality_hold(scene, deps, mark_preview=True)
        _ctx_mark_manual_queued_resolve_error(
            ctx,
            scene,
            f"Download failed: {str(error_message or '').strip() or 'Unknown error'}",
        )
        if error_message:
            deps.logger.warning("Planetka manual resolve download failed: %s", error_message)
        return

    if _is_non_retryable_resolve_error(error_message):
        deps.resolve_trace(
            "Download finished with terminal error "
            f"(request_id={deps.job_field(job, 'request_id')}, error={str(error_message or '').strip() or 'unknown'})"
        )
        _ctx_mark_auto_resolve_terminal_failure(
            ctx,
            scene,
            scene_id,
            job,
            f"Download failed: {str(error_message or '').strip() or 'Unknown error'}",
        )
        if error_message:
            deps.logger.warning("Planetka auto-resolve download terminal failure: %s", error_message)
        return

    scene_state = deps.read_scene_auto_resolve_state(scene_id)
    if scene_state is not None:
        scene_state.last_processed_signature = None
        scene_state.last_change_time = time.monotonic()
        deps.write_scene_auto_resolve_state(scene_state)
    deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
    if error_message:
        deps.logger.debug("Planetka auto-resolve download failed: %s", error_message)


def _handle_auto_resolve_download_failure(job, error_message):
    return _ctx_handle_auto_resolve_download_failure(_require_download_ctx(), job, error_message)


def _ctx_auto_resolve_completion_epoch_state(ctx, job):
    deps = ctx.deps
    state = ctx.state
    try:
        job_epoch = int(deps.job_field(job, "epoch", -1))
    except (TypeError, ValueError):
        job_epoch = -1
    with state.download_lock:
        current_epoch = int(state.download_epoch)
        pending_job = state.download_pending_job
    return (job_epoch == current_epoch), pending_job


def _auto_resolve_completion_epoch_state(job):
    return _ctx_auto_resolve_completion_epoch_state(_require_download_ctx(), job)


def _ctx_auto_resolve_handle_cancel_or_failure(ctx, result, job, manual_request):
    deps = ctx.deps
    if bool(result.get("cancelled", False)):
        deps.resolve_trace(
            f"Download finished cancelled (request_id={deps.job_field(job, 'request_id')}, manual={manual_request})"
        )
        if bool(manual_request) and _quality_mode_for_job(deps, job) == "FULL":
            try:
                scene_id = int(deps.job_field(job, "scene_id", 0) or 0)
            except (TypeError, ValueError):
                scene_id = 0
            scene = deps.scene_from_key(scene_id) if scene_id else None
            _clear_full_quality_hold(scene, deps, mark_preview=True)
        return True

    if not bool(result.get("success", False)):
        _ctx_handle_auto_resolve_download_failure(ctx, job, str(result.get("error", "") or ""))
        return True

    return False


def _auto_resolve_handle_cancel_or_failure(result, job, manual_request):
    return _ctx_auto_resolve_handle_cancel_or_failure(_require_download_ctx(), result, job, manual_request)


def _ctx_auto_resolve_log_pending_request_overlap(ctx, job, pending_job):
    deps = ctx.deps
    # Never drop a completed download just because a newer request exists.
    # Finalize this resolve first; pending jobs will run immediately after.
    if deps.is_auto_resolve_download_job(pending_job):
        try:
            pending_request_id = int(deps.job_field(pending_job, "request_id", 0) or 0)
            job_request_id = int(deps.job_field(job, "request_id", 0) or 0)
            if pending_request_id > job_request_id:
                deps.logger.debug(
                    "Planetka: finalizing completed resolve %d while newer request %d is pending.",
                    job_request_id,
                    pending_request_id,
                )
        except (TypeError, ValueError):
            pass


def _auto_resolve_log_pending_request_overlap(job, pending_job):
    return _ctx_auto_resolve_log_pending_request_overlap(_require_download_ctx(), job, pending_job)


def _ctx_blend_data_write_lock_reason(ctx):
    deps = ctx.deps
    bpy_context = getattr(deps.bpy, "context", None)
    wm = getattr(bpy_context, "window_manager", None) if bpy_context is not None else None
    try:
        if wm is not None and bool(getattr(wm, "is_interface_locked", False)):
            return "window_manager interface lock"
    except deps.recoverable_exceptions:
        return ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return ""
    return ""


def _ctx_auto_resolve_prepare_apply_context(ctx, job, manual_request):
    deps = ctx.deps
    settings = ctx.settings
    scene_id = int(deps.job_field(job, "scene_id", 0) or 0)
    scene = deps.scene_from_key(scene_id)
    if scene is None:
        # Grace period: Blender can briefly lose scene context around file/load/UI transitions.
        # If context does not return quickly, consume/drop this completion to avoid a stuck pump loop.
        now = time.monotonic()
        try:
            missing_since = float(deps.job_field(job, "scene_missing_since", 0.0) or 0.0)
        except (TypeError, ValueError):
            missing_since = 0.0
        if missing_since <= 0.0:
            missing_since = now
        try:
            attempts = int(deps.job_field(job, "scene_missing_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        deps.job_set_field(job, "scene_missing_since", float(missing_since))
        deps.job_set_field(job, "scene_missing_attempts", int(max(1, attempts)))
        waited_sec = max(0.0, float(now) - float(missing_since))
        if waited_sec < float(settings.download_scene_wait_sec):
            deps.resolve_trace(
                "Download finished but scene context unavailable yet "
                f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, attempts={attempts}); waiting"
            )
            return False, None, None, None
        deps.resolve_trace(
            "Download completion dropped due stale missing scene context "
            f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, attempts={attempts})"
        )
        deps.logger.debug(
            "Planetka: dropping completed auto-resolve payload because scene context did not return "
            "(request_id=%s, waited=%.2fs, attempts=%d).",
            str(deps.job_field(job, "request_id", "")),
            float(waited_sec),
            int(attempts),
        )
        return True, None, None, None
    deps.job_set_field(job, "scene_missing_since", 0.0)
    deps.job_set_field(job, "scene_missing_attempts", 0)
    lock_reason = _ctx_blend_data_write_lock_reason(ctx)
    if lock_reason:
        now = time.monotonic()
        try:
            lock_since = float(deps.job_field(job, "apply_lock_since", 0.0) or 0.0)
        except (TypeError, ValueError):
            lock_since = 0.0
        if lock_since <= 0.0:
            lock_since = now
        try:
            lock_attempts = int(deps.job_field(job, "apply_lock_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            lock_attempts = 1
        deps.job_set_field(job, "apply_lock_since", float(lock_since))
        deps.job_set_field(job, "apply_lock_attempts", int(max(1, lock_attempts)))
        waited_sec = max(0.0, float(now) - float(lock_since))
        wait_budget_sec = min(
            float(settings.download_completed_max_age_sec),
            max(float(settings.download_scene_wait_sec), 6.0),
        )
        if waited_sec < wait_budget_sec:
            deps.resolve_trace(
                "Download finished but blend data is read-only; waiting "
                f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, "
                f"attempts={lock_attempts}, reason={lock_reason})"
            )
            return False, None, None, None
        deps.resolve_trace(
            "Download completion dropped due persistent read-only blend data state "
            f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, "
            f"attempts={lock_attempts}, reason={lock_reason})"
        )
        deps.logger.warning(
            "Planetka: dropping completed auto-resolve payload after %.2fs waiting for write access "
            "(request_id=%s, attempts=%d, reason=%s).",
            float(waited_sec),
            str(deps.job_field(job, "request_id", "")),
            int(lock_attempts),
            str(lock_reason),
        )
        if manual_request:
            _ctx_mark_manual_queued_resolve_error(
                ctx,
                scene,
                (
                    "Apply deferred too long because Blender data stayed read-only "
                    f"({lock_reason}); try Resolve again."
                ),
            )
        else:
            deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return True, None, None, None
    deps.job_set_field(job, "apply_lock_since", 0.0)
    deps.job_set_field(job, "apply_lock_attempts", 0)
    job_target_tiles = deps.canonical_tiles(deps.job_field(job, "target_tiles", ()))

    if deps.is_render_job_active():
        if manual_request:
            deps.logger.info(
                "Planetka: waiting to apply queued manual resolve during active render "
                "(request_id=%s).",
                str(deps.job_field(job, "request_id", "")),
            )
            return False, None, None, None
        else:
            deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return True, None, None, None

    props = getattr(scene, "planetka", None)
    if deps.is_animation_playing() and bool(getattr(props, "lock_resolve_during_animation", True)):
        if manual_request:
            _ctx_mark_manual_queued_resolve_error(ctx, scene, "Blocked by animation playback lock.")
        else:
            deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return True, None, None, None

    if manual_request:
        current_output_signature = deps.output_resolution_signature(scene)
        if current_output_signature != deps.job_field(job, "output_signature"):
            deps.logger.warning("Planetka queued resolve continuing despite output signature change.")
    return True, scene, scene_id, job_target_tiles


def _auto_resolve_prepare_apply_context(job, manual_request):
    return _ctx_auto_resolve_prepare_apply_context(_require_download_ctx(), job, manual_request)


def _ctx_auto_resolve_apply_downloaded_tiles(ctx, scene, scene_id, job, manual_request, job_target_tiles):
    deps = ctx.deps
    state = ctx.state
    state.in_flight = True
    try:
        deps.resolve_trace(
            f"Shader update started (request_id={deps.job_field(job, 'request_id')}, manual={manual_request}, tiles={len(job_target_tiles)})"
        )
        op_kwargs = {
            "scope_mode": "CAMERA",
            "skip_render_compatibility": True,
            "skip_pricing_session": True,
            "defer_download": False,
            "tiles_override_json": json.dumps(list(job_target_tiles)),
            "texture_quality_mode_override": deps.normalize_texture_quality_mode(
                deps.job_field(job, "texture_quality_mode", "PREVIEW")
            ),
        }
        try:
            context_scene = getattr(getattr(deps.bpy, "context", None), "scene", None)
        except deps.recoverable_exceptions:
            context_scene = None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            context_scene = None
        if context_scene is not scene:
            deps.resolve_trace(
                f"Shader update deferred: target scene is not the active context scene "
                f"(request_id={deps.job_field(job, 'request_id')})"
            )
            return None
        op_result = deps.bpy.ops.planetka.load_textures(**op_kwargs)
        if "FINISHED" not in op_result:
            deps.resolve_trace(
                f"Shader update failed (request_id={deps.job_field(job, 'request_id')} op_result={str(op_result)})"
            )
            scene_error = _ctx_read_scene_last_resolve_error(ctx, scene)
            apply_error = scene_error or f"Apply operator returned {str(op_result)} for {len(job_target_tiles)} tile(s)."
            if _is_blend_data_readonly_error(apply_error):
                return _ctx_handle_apply_readonly_failure(
                    ctx,
                    scene,
                    job,
                    manual_request,
                    apply_error,
                )
            deps.logger.warning(
                "Planetka queued resolve apply returned %s for %d tile(s).",
                str(op_result),
                len(job_target_tiles),
            )
            if manual_request:
                _ctx_mark_manual_queued_resolve_error(ctx, scene, apply_error)
            else:
                if _is_non_retryable_resolve_error(apply_error):
                    _ctx_mark_auto_resolve_terminal_failure(ctx, scene, scene_id, job, apply_error)
                else:
                    deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
            return False
    except deps.recoverable_exceptions as exc:
        deps.resolve_trace(
            f"Shader update failed with recoverable exception (request_id={deps.job_field(job, 'request_id')})"
        )
        exc_text = f"{type(exc).__name__}: {exc}" if str(exc or "").strip() else str(type(exc).__name__)
        scene_error = _ctx_read_scene_last_resolve_error(ctx, scene)
        apply_error = scene_error or f"Apply failed with recoverable exception: {str(exc_text or 'unknown')}."
        if _is_blend_data_readonly_error(apply_error) or _is_blend_data_readonly_error(exc_text):
            return _ctx_handle_apply_readonly_failure(
                ctx,
                scene,
                job,
                manual_request,
                apply_error,
            )
        deps.logger.exception(
            "Planetka auto-resolve apply failed with recoverable exception "
            "(request_id=%s, manual=%s, tiles=%d): %s",
            str(deps.job_field(job, "request_id", "")),
            bool(manual_request),
            int(len(job_target_tiles)),
            str(exc_text or "unknown"),
        )
        if manual_request:
            _ctx_mark_manual_queued_resolve_error(ctx, scene, apply_error)
        else:
            if _is_non_retryable_resolve_error(apply_error):
                _ctx_mark_auto_resolve_terminal_failure(ctx, scene, scene_id, job, apply_error)
            else:
                deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
        deps.resolve_trace(
            f"Shader update failed with unexpected exception (request_id={deps.job_field(job, 'request_id')})"
        )
        exc_text = f"{type(exc).__name__}: {exc}" if str(exc or "").strip() else str(type(exc).__name__)
        scene_error = _ctx_read_scene_last_resolve_error(ctx, scene)
        apply_error = scene_error or f"Apply failed with unexpected exception: {str(exc_text or 'unknown')}."
        if _is_blend_data_readonly_error(apply_error) or _is_blend_data_readonly_error(exc_text):
            return _ctx_handle_apply_readonly_failure(
                ctx,
                scene,
                job,
                manual_request,
                apply_error,
            )
        deps.logger.exception(
            "Planetka auto-resolve apply failed unexpectedly "
            "(request_id=%s, manual=%s, tiles=%d): %s",
            str(deps.job_field(job, "request_id", "")),
            bool(manual_request),
            int(len(job_target_tiles)),
            str(exc_text or "unknown"),
        )
        if manual_request:
            _ctx_mark_manual_queued_resolve_error(ctx, scene, apply_error)
        else:
            if _is_non_retryable_resolve_error(apply_error):
                _ctx_mark_auto_resolve_terminal_failure(ctx, scene, scene_id, job, apply_error)
            else:
                deps.request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return False
    finally:
        state.in_flight = False
    return True


def _auto_resolve_apply_downloaded_tiles(scene, scene_id, job, manual_request, job_target_tiles):
    return _ctx_auto_resolve_apply_downloaded_tiles(
        _require_download_ctx(),
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
    )


def _ctx_auto_resolve_summary_total_bytes(ctx, job_target_tiles, job, result):
    deps = ctx.deps
    summary_total_bytes = 0
    try:
        summary_total_bytes = int(
            max(
                0,
                int(
                    deps.estimate_download_bytes_for_visible_tiles(
                        job_target_tiles,
                        str(deps.job_field(job, "base_path", "") or ""),
                        texture_quality_mode=deps.normalize_texture_quality_mode(
                            deps.job_field(job, "texture_quality_mode", "PREVIEW")
                        ),
                    )
                    or 0
                ),
            )
        )
    except deps.recoverable_exceptions:
        summary_total_bytes = 0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        summary_total_bytes = 0
    if summary_total_bytes <= 0:
        downloaded_bytes = 0
        capture = result.get("download_capture", {}) if isinstance(result, dict) else {}
        if isinstance(capture, dict):
            try:
                downloaded_bytes = int(capture.get("downloaded_bytes", 0) or 0)
            except (TypeError, ValueError):
                downloaded_bytes = 0
        summary_total_bytes = int(max(0, int(downloaded_bytes)))
    return summary_total_bytes


def _auto_resolve_summary_total_bytes(job_target_tiles, job, result):
    return _ctx_auto_resolve_summary_total_bytes(_require_download_ctx(), job_target_tiles, job, result)


def _ctx_finalize_auto_resolve_apply(ctx, scene, scene_id, job, manual_request, job_target_tiles, resolved_at, summary_total_bytes):
    deps = ctx.deps
    job_quality_mode = _quality_mode_for_job(deps, job)
    try:
        created_at = float(deps.job_field(job, "created_at", resolved_at) or resolved_at)
    except (TypeError, ValueError):
        created_at = resolved_at
    total_seconds = max(0.0, float(resolved_at) - float(created_at))
    _ctx_write_last_resolve_summary(ctx, scene, len(job_target_tiles), summary_total_bytes, total_seconds)

    scene_id = deps.scene_key(scene)
    latest_signature = deps.camera_signature(scene) or deps.job_field(job, "camera_signature")
    latest_output_signature = deps.output_resolution_signature(scene)
    scene_state = deps.read_scene_auto_resolve_state(scene_id)
    if scene_state is not None:
        scene_state.last_resolve_time = resolved_at
        scene_state.last_change_time = resolved_at
        scene_state.last_camera_signature = latest_signature
        scene_state.last_output_signature = latest_output_signature
        scene_state.last_processed_signature = latest_signature
        scene_state.pending_output_change = False
        deps.write_scene_auto_resolve_state(scene_state)
    deps.viewport_scope_last_resolve_time[scene_id] = resolved_at
    try:
        if "planetka_last_resolve_error" in scene:
            del scene["planetka_last_resolve_error"]
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed clearing queued resolve error marker", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed clearing queued resolve error marker", exc_info=True)
    latest_camera_signature = deps.camera_signature(scene)
    job_camera_signature = deps.job_field(job, "camera_signature")
    job_output_signature = deps.job_field(job, "output_signature")

    if manual_request:
        if job_quality_mode == "FULL":
            _store_full_quality_hold(scene, deps, job_camera_signature or latest_camera_signature)
        elif job_quality_mode == "PREVIEW":
            _clear_full_quality_hold(scene, deps, mark_preview=True)
        deps.logger.warning(
            "Planetka queued resolve applied successfully (%d tile(s)).",
            len(job_target_tiles),
        )
    else:
        if job_quality_mode == "PREVIEW":
            _clear_full_quality_hold(scene, deps, mark_preview=True)
        # Auto-resolve should always finalize once download completes.
        # If the camera/output changed while downloading, queue another pass after this apply.
        if (
            latest_camera_signature != job_camera_signature
            or latest_output_signature != job_output_signature
        ):
            deps.request_auto_resolve(scene, immediate=False, mark_dirty=True)
    deps.resolve_trace(
        f"Shader update finished (request_id={deps.job_field(job, 'request_id')}, tiles={len(job_target_tiles)})"
    )


def _finalize_auto_resolve_apply(scene, scene_id, job, manual_request, job_target_tiles, resolved_at, summary_total_bytes):
    return _ctx_finalize_auto_resolve_apply(
        _require_download_ctx(),
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
        resolved_at,
        summary_total_bytes,
    )


def _ctx_handle_auto_resolve_download_complete(ctx, result):
    deps = ctx.deps
    if not isinstance(result, dict):
        return True
    job = result.get("job")
    if not deps.is_auto_resolve_download_job(job):
        return True
    manual_request = bool(deps.job_field(job, "manual_request", False))

    epoch_matches, pending_job = _ctx_auto_resolve_completion_epoch_state(ctx, job)
    if not epoch_matches:
        return True

    if _ctx_auto_resolve_handle_cancel_or_failure(ctx, result, job, manual_request):
        return True

    _ctx_auto_resolve_log_pending_request_overlap(ctx, job, pending_job)

    consume, scene, scene_id, job_target_tiles = _ctx_auto_resolve_prepare_apply_context(ctx, job, manual_request)
    if not consume:
        return False
    if scene is None:
        return True

    apply_result = _ctx_auto_resolve_apply_downloaded_tiles(
        ctx,
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
    )
    if apply_result is None:
        # Keep completed payload queued; pump will retry apply after transient read-only states clear.
        return False
    if not apply_result:
        return True

    resolved_at = time.monotonic()
    summary_total_bytes = _ctx_auto_resolve_summary_total_bytes(ctx, job_target_tiles, job, result)
    _ctx_finalize_auto_resolve_apply(
        ctx,
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
        resolved_at,
        summary_total_bytes,
    )
    return True


def _handle_auto_resolve_download_complete(result):
    return _ctx_handle_auto_resolve_download_complete(_require_download_ctx(), result)


def _ctx_auto_resolve_download_worker(ctx, job):
    deps = ctx.deps
    state = ctx.state

    result = {
        "job": job,
        "success": False,
        "cancelled": False,
        "error": "",
        "download_capture": {},
    }

    try:
        deps.resolve_trace(
            "Download started "
            f"(request_id={deps.job_field(job, 'request_id')}, manual={bool(deps.job_field(job, 'manual_request', False))}, "
            f"tiles={len(tuple(deps.job_field(job, 'target_tiles', ())))})"
        )
        streaming_module = deps.get_streaming_utils()
        prepare_fn = getattr(streaming_module, "prepare_resolve_streaming_for_visible_tiles", None)
        stage_fn = getattr(streaming_module, "stage_prefetch_payload", None)
        if not callable(prepare_fn):
            raise RuntimeError("Planetka streaming pipeline is unavailable.")

        prepared_payload = prepare_fn(
            tuple(deps.job_field(job, "target_tiles", ())),
            str(deps.job_field(job, "base_path", "") or ""),
            cancel_event=deps.job_field(job, "cancel_event"),
            capture=True,
            texture_quality_mode=deps.normalize_texture_quality_mode(deps.job_field(job, "texture_quality_mode", "PREVIEW")),
            nav_latitude_deg=deps.job_field(job, "nav_latitude_deg", ""),
            nav_longitude_deg=deps.job_field(job, "nav_longitude_deg", ""),
            nav_altitude_km=deps.job_field(job, "nav_altitude_km", ""),
        )
        cancelled = (
            bool(prepared_payload.get("cancelled", False))
            if isinstance(prepared_payload, dict)
            else False
        )
        if not cancelled and isinstance(prepared_payload, dict) and callable(stage_fn):
            stage_fn(
                tuple(deps.job_field(job, "target_tiles", ()) or ()),
                str(deps.job_field(job, "base_path", "") or ""),
                prepared_payload,
                texture_quality_mode=deps.normalize_texture_quality_mode(deps.job_field(job, "texture_quality_mode", "PREVIEW")),
            )
        result["success"] = not cancelled
        result["cancelled"] = cancelled
        result["download_capture"] = (
            dict(prepared_payload.get("download_capture", {}))
            if isinstance(prepared_payload, dict)
            else {}
        )
        capture = result.get("download_capture", {}) or {}
        downloaded_bytes = int(capture.get("downloaded_bytes", 0) or 0) if isinstance(capture, dict) else 0
        total_bytes = int(capture.get("total_bytes", 0) or 0) if isinstance(capture, dict) else 0
        deps.resolve_trace(
            "Download finished "
            f"(request_id={deps.job_field(job, 'request_id')}, cancelled={cancelled}, downloaded={downloaded_bytes}, total={total_bytes})"
        )
    except deps.recoverable_exceptions as exc:
        result["error"] = str(exc)
        deps.resolve_trace(
            f"Download failed with recoverable exception (request_id={deps.job_field(job, 'request_id')}, error={str(exc)})"
        )
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
        result["error"] = str(exc)
        deps.resolve_trace(
            f"Download failed with unexpected exception (request_id={deps.job_field(job, 'request_id')}, error={str(exc)})"
        )
    finally:
        result["completed_at"] = float(time.monotonic())
        with state.download_lock:
            if state.download_active_job is job:
                state.download_active_job = None
            state.download_thread = None
            job_epoch = int(deps.job_field(job, "epoch", -1))
            current_epoch = int(state.download_epoch)
            store_completed = (job_epoch == current_epoch)
            if store_completed:
                state.download_completed = result
            deps.resolve_trace(
                f"Worker finalize (request_id={deps.job_field(job, 'request_id')}, job_epoch={job_epoch}, "
                f"current_epoch={current_epoch}, store_completed={store_completed})"
            )


def _auto_resolve_download_worker(job):
    return _ctx_auto_resolve_download_worker(_require_download_ctx(), job)


def _ctx_resume_or_stop_download_pump_after_error(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings
    with state.download_lock:
        has_active = state.download_active_job is not None
        has_pending = state.download_pending_job is not None
        has_completed = state.download_completed is not None
    has_thread = state.download_thread is not None
    if has_active or has_pending or has_completed or has_thread:
        state.download_timer_running = True
        return settings.download_pump_interval_sec
    state.download_timer_running = False
    return None


def _ctx_auto_resolve_download_pump_timer(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings

    try:
        deps.resolve_trace("Pump tick")
        if not hasattr(deps.bpy.types.Scene, "planetka"):
            state.download_timer_running = False
            deps.resolve_trace("Pump stop: Scene.planetka missing")
            return None

        completed = None
        with state.download_lock:
            if isinstance(state.download_completed, dict):
                completed = state.download_completed

        if isinstance(completed, dict):
            completed_job = completed.get("job") if isinstance(completed, dict) else None
            completed_request_id = deps.job_field(completed_job, "request_id")
            now = time.monotonic()
            try:
                completed_at = float(completed.get("completed_at", 0.0) or 0.0)
            except (TypeError, ValueError):
                completed_at = 0.0
            if completed_at <= 0.0:
                try:
                    completed_at = float(completed.get("_pump_seen_at", 0.0) or 0.0)
                except (TypeError, ValueError):
                    completed_at = 0.0
                if completed_at <= 0.0:
                    completed_at = float(now)
                    completed["_pump_seen_at"] = float(completed_at)
            completed_age = max(0.0, float(now) - float(completed_at))
            if completed_age >= float(settings.download_completed_max_age_sec):
                deps.resolve_trace(
                    "Pump dropped stale completed download payload "
                    f"(request_id={completed_request_id}, age={completed_age:.2f}s)"
                )
                with state.download_lock:
                    if state.download_completed is completed:
                        state.download_completed = None
                completed = None
            else:
                deps.resolve_trace(
                    f"Pump received completed download (request_id={completed_request_id}, age={completed_age:.2f}s)"
                )
                consume_completed = False
                try:
                    consume_completed = bool(_ctx_handle_auto_resolve_download_complete(ctx, completed))
                except deps.recoverable_exceptions:
                    _ctx_handle_auto_resolve_download_failure(
                        ctx,
                        completed_job,
                        "Finalize crashed with recoverable exception.",
                    )
                    deps.logger.exception(
                        "Planetka: auto-resolve finalize crashed for completed payload "
                        "(request_id=%s). Dropping payload to keep pipeline alive.",
                        str(completed_request_id),
                    )
                    consume_completed = True
                except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
                    _ctx_handle_auto_resolve_download_failure(
                        ctx,
                        completed_job,
                        "Finalize crashed with unexpected exception.",
                    )
                    deps.logger.exception(
                        "Planetka: auto-resolve finalize crashed unexpectedly for completed payload "
                        "(request_id=%s). Dropping payload to keep pipeline alive.",
                        str(completed_request_id),
                    )
                    consume_completed = True
                if consume_completed:
                    with state.download_lock:
                        if state.download_completed is completed:
                            state.download_completed = None

        job_to_start = None
        with state.download_lock:
            can_start_pending = state.download_completed is None
            if (
                can_start_pending
                and state.download_active_job is None
                and deps.is_auto_resolve_download_job(state.download_pending_job)
            ):
                state.download_active_job = state.download_pending_job
                state.download_pending_job = None
                job_to_start = state.download_active_job

            has_active = state.download_active_job is not None
            has_pending = state.download_pending_job is not None
            has_completed = state.download_completed is not None

        if deps.is_auto_resolve_download_job(job_to_start):
            _ctx_start_auto_resolve_download_thread(ctx, job_to_start)
            has_active = True

        try:
            scene = getattr(getattr(deps.bpy, "context", None), "scene", None)
        except deps.recoverable_exceptions:
            scene = None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            scene = None
        if scene is not None:
            if not (has_active or has_pending):
                deps.update_realtime_telemetry(scene)
            deps.tag_view3d_redraw()

        if not has_active and not has_pending and not has_completed:
            state.download_timer_running = False
            deps.resolve_trace("Pump stop: no active/pending/completed jobs")
            return None

        state.download_timer_running = True
        return settings.download_pump_interval_sec
    except deps.recoverable_exceptions:
        deps.resolve_trace("Pump failed with recoverable exception")
        deps.logger.exception("Planetka auto-resolve download timer failed")
        with state.download_lock:
            state.download_completed = None
        return _ctx_resume_or_stop_download_pump_after_error(ctx)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        deps.resolve_trace("Pump failed with unexpected exception")
        deps.logger.exception("Planetka auto-resolve download timer failed unexpectedly")
        with state.download_lock:
            state.download_completed = None
        return _ctx_resume_or_stop_download_pump_after_error(ctx)

    state.download_timer_running = False
    return None


def _auto_resolve_download_pump_timer():
    return _ctx_auto_resolve_download_pump_timer(_require_download_ctx())


def _ctx_stop_auto_resolve_download_pipeline(ctx):
    deps = ctx.deps
    state = ctx.state

    with state.download_lock:
        state.download_epoch = int(state.download_epoch) + 1
        deps.resolve_trace(f"Pipeline stop called; epoch advanced to {state.download_epoch}")

        active_job = state.download_active_job
        if deps.is_auto_resolve_download_job(active_job):
            cancel_event = deps.job_field(active_job, "cancel_event")
            if cancel_event is not None:
                try:
                    cancel_event.set()
                except deps.recoverable_exceptions:
                    deps.logger.debug("[PKA-STATE-001] Planetka: failed signaling resolve cancel event", exc_info=True)

        state.download_active_job = None
        state.download_pending_job = None
        state.download_completed = None

    try:
        if deps.bpy.app.timers.is_registered(_auto_resolve_download_pump_timer):
            deps.bpy.app.timers.unregister(_auto_resolve_download_pump_timer)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed stopping auto-resolve download timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed stopping auto-resolve download timer", exc_info=True)

    state.download_timer_running = False


def stop_auto_resolve_download_pipeline():
    return _ctx_stop_auto_resolve_download_pipeline(_require_download_ctx())


def _ctx_request_auto_resolve(ctx, scene, immediate=False, mark_dirty=True):
    deps = ctx.deps
    state = ctx.state
    if not _ctx_can_auto_resolve_run(ctx, scene):
        state.next_due_time.clear()
        state.timer_running = False
        try:
            if deps.bpy.app.timers.is_registered(_auto_resolve_timer):
                deps.bpy.app.timers.unregister(_auto_resolve_timer)
        except deps.recoverable_exceptions:
            deps.logger.debug("Planetka: failed stopping auto-resolve timer", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            deps.logger.debug("Planetka: failed stopping auto-resolve timer", exc_info=True)
        return
    if scene is None:
        return

    if deps.auto_resolve_scope_mode(scene) == "NONE":
        return

    if mark_dirty:
        _ctx_mark_auto_resolve_dirty(ctx, scene, immediate=bool(immediate))

    scene_state = deps.read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return
    now = time.monotonic()
    delay_sec = 0.0 if immediate else _ctx_auto_resolve_idle_seconds(ctx, scene)
    scene_state.next_due_time = now + delay_sec
    deps.write_scene_auto_resolve_state(scene_state)
    _ctx_arm_auto_resolve_timer(ctx, force_immediate=bool(immediate))


def request_auto_resolve(scene, immediate=False, mark_dirty=True):
    return _ctx_request_auto_resolve(
        _require_decision_ctx(),
        scene,
        immediate=immediate,
        mark_dirty=mark_dirty,
    )


def _ctx_can_auto_resolve_run(ctx, scene):
    deps = ctx.deps
    if scene is None:
        return False
    props = getattr(scene, "planetka", None)
    if props is None:
        return False
    if not bool(getattr(props, "auto_resolve", False)):
        return False
    if deps.get_earth_object() is None:
        return False
    return True


def _can_auto_resolve_run(scene):
    return _ctx_can_auto_resolve_run(_require_decision_ctx(), scene)


def _ctx_update_auto_resolve(ctx, self, context):
    deps = ctx.deps
    scene = getattr(context, "scene", None) if context else None
    if scene:
        deps.sync_idprops_from_props(
            scene,
            (
                "viewport_opt_suspend_subdivision",
                "viewport_opt_subdivision_restore_delay_sec",
                "viewport_opt_active_view_coarse_textures",
                "auto_resolve",
                "auto_resolve_idle_sec",
                "texture_quality_mode",
                "resolution_bias",
                "lock_resolve_during_animation",
            ),
        )
        props = getattr(scene, "planetka", None)
        if props is not None and not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
            deps.force_restore_navigation_adaptive_state()
        _ctx_mark_auto_resolve_dirty(ctx, scene, immediate=True, force_resolve=True)
    if _ctx_can_auto_resolve_run(ctx, scene):
        _ctx_request_auto_resolve(ctx, scene, immediate=True, mark_dirty=False)
    else:
        _ctx_stop_auto_resolve_service(ctx)


def update_auto_resolve(self, context):
    return _ctx_update_auto_resolve(_require_decision_ctx(), self, context)


def _ctx_auto_resolve_collect_scope_signatures(ctx, scene, scope_mode):
    deps = ctx.deps
    scope = str(scope_mode or "NONE")
    active_view_signature = None
    if scope == "ACTIVE_VIEW":
        active_view_signature = deps.active_view_signature()
    camera_signature = deps.camera_signature(scene)
    resolve_signature = (
        ("ACTIVE_VIEW", active_view_signature)
        if active_view_signature is not None
        else camera_signature
    )
    return scope, active_view_signature, resolve_signature


def _auto_resolve_collect_scope_signatures(scene, scope_mode):
    return _ctx_auto_resolve_collect_scope_signatures(_require_decision_ctx(), scene, scope_mode)


def _ctx_auto_resolve_sync_state_signatures(ctx, scene_state, resolve_signature, output_signature, now_monotonic):
    deps = ctx.deps
    state_dirty = False
    previous_output_signature = scene_state.last_output_signature
    if previous_output_signature != output_signature:
        scene_state.last_output_signature = output_signature
        state_dirty = True
        if previous_output_signature is not None:
            scene_state.pending_output_change = True
            scene_state.last_processed_signature = None
            scene_state.last_change_time = now_monotonic

    previous_signature = scene_state.last_camera_signature
    if previous_signature != resolve_signature:
        scene_state.last_camera_signature = resolve_signature
        scene_state.last_processed_signature = None
        state_dirty = True

    if state_dirty:
        deps.write_scene_auto_resolve_state(scene_state)
    return bool(scene_state.pending_output_change)


def _auto_resolve_sync_state_signatures(scene_state, resolve_signature, output_signature, now_monotonic):
    return _ctx_auto_resolve_sync_state_signatures(
        _require_decision_ctx(),
        scene_state,
        resolve_signature,
        output_signature,
        now_monotonic,
    )


def _ctx_auto_resolve_update_size_estimation(ctx, scene, scope, active_view_signature, target_tiles, props):
    deps = ctx.deps
    estimation_scope = "ACTIVE_VIEW" if (scope == "ACTIVE_VIEW" and active_view_signature is not None) else "CAMERA"
    base_path_for_estimate = ""
    try:
        prefs = deps.get_prefs()
        if prefs is not None:
            base_path_for_estimate = str(getattr(prefs, "texture_base_path", "") or "")
    except deps.recoverable_exceptions:
        base_path_for_estimate = ""
    except (RuntimeError, TypeError, ValueError, AttributeError):
        base_path_for_estimate = ""

    full_tiles_override = None
    include_full_price = False
    try:
        deps.update_resolve_size_estimates(
            scene,
            scope_mode=estimation_scope,
            base_path=base_path_for_estimate,
            full_tiles_override=full_tiles_override,
            include_full_price=include_full_price,
            async_full_price=include_full_price,
        )
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka auto-resolve: failed updating resolve size estimates", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka auto-resolve: failed updating resolve size estimates", exc_info=True)


def _auto_resolve_update_size_estimation(scene, scope, active_view_signature, target_tiles, props):
    return _ctx_auto_resolve_update_size_estimation(
        _require_noncritical_ctx(),
        scene,
        scope,
        active_view_signature,
        target_tiles,
        props,
    )


def _is_active_view_resolve_signature(signature):
    return (
        isinstance(signature, (tuple, list))
        and len(signature) >= 1
        and str(signature[0] or "").strip().upper() == "ACTIVE_VIEW"
    )


def _ctx_arm_auto_resolve_noncritical_timer(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings
    try:
        if deps.bpy.app.timers.is_registered(_auto_resolve_noncritical_timer):
            state.noncritical_timer_running = True
            return
        deps.bpy.app.timers.register(
            _auto_resolve_noncritical_timer,
            first_interval=max(0.05, float(settings.noncritical_interval_sec)),
            persistent=True,
        )
        state.noncritical_timer_running = True
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed arming non-critical auto-resolve timer", exc_info=True)
        state.noncritical_timer_running = False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        deps.logger.debug("Planetka: failed arming non-critical auto-resolve timer", exc_info=True)
        state.noncritical_timer_running = False


def _arm_auto_resolve_noncritical_timer():
    return _ctx_arm_auto_resolve_noncritical_timer(_require_noncritical_ctx())


def _ctx_auto_resolve_enqueue_size_estimation(ctx, scene, scope, active_view_signature, target_tiles, props):
    deps = ctx.deps
    state = ctx.state
    if scene is None or props is None:
        return
    try:
        scene_id = deps.scene_key(scene)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return
    current_quality_mode = _ctx_auto_resolve_texture_quality_mode(ctx, scene, props)
    safe_scope = str(scope or "CAMERA")
    safe_active_signature = active_view_signature if safe_scope == "ACTIVE_VIEW" else None
    safe_tiles = tuple(target_tiles or ())
    request_signature = (safe_scope, safe_active_signature, current_quality_mode, safe_tiles)
    if state.size_estimate_last_signature.get(scene_id) == request_signature:
        return
    state.size_estimate_last_signature[scene_id] = request_signature
    state.noncritical_pending[scene_id] = {
        "scope": safe_scope,
        "active_view_signature": safe_active_signature,
        "target_tiles": safe_tiles,
    }
    _ctx_arm_auto_resolve_noncritical_timer(ctx)


def _auto_resolve_enqueue_size_estimation(scene, scope, active_view_signature, target_tiles, props):
    return _ctx_auto_resolve_enqueue_size_estimation(
        _require_noncritical_ctx(),
        scene,
        scope,
        active_view_signature,
        target_tiles,
        props,
    )


def _ctx_auto_resolve_noncritical_timer(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings
    try:
        if not hasattr(deps.bpy.types.Scene, "planetka"):
            state.noncritical_pending.clear()
            state.noncritical_timer_running = False
            return None
        if not state.noncritical_pending:
            state.noncritical_timer_running = False
            return None

        try:
            scene = getattr(getattr(deps.bpy, "context", None), "scene", None)
        except deps.recoverable_exceptions:
            scene = None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            scene = None
        scene_id = deps.scene_key(scene) if scene is not None else None
        request = None
        if scene_id is not None:
            request = state.noncritical_pending.pop(scene_id, None)

        if request is None:
            pending_scene_id, request = next(iter(state.noncritical_pending.items()))
            state.noncritical_pending.pop(pending_scene_id, None)
            scene = deps.scene_from_key(pending_scene_id)

        if scene is not None and request:
            props = getattr(scene, "planetka", None)
            if props is not None:
                _ctx_auto_resolve_update_size_estimation(
                    ctx,
                    scene,
                    request.get("scope"),
                    request.get("active_view_signature"),
                    request.get("target_tiles"),
                    props,
                )

        if state.noncritical_pending:
            return max(0.05, float(settings.noncritical_interval_sec))
        state.noncritical_timer_running = False
        return None
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka non-critical auto-resolve timer tick failed", exc_info=True)
        state.noncritical_timer_running = False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        deps.logger.debug("Planetka non-critical auto-resolve timer tick failed unexpectedly", exc_info=True)
        state.noncritical_timer_running = False
    return None


def _auto_resolve_noncritical_timer():
    return _ctx_auto_resolve_noncritical_timer(_require_noncritical_ctx())


def _ctx_auto_resolve_detect_change(ctx, scene, props):
    deps = ctx.deps
    settings = ctx.settings
    if scene is None:
        return {"event": "STOP", "retry_delay": None}
    if props is None or not bool(getattr(props, "auto_resolve", False)):
        return {"event": "STOP", "retry_delay": None}

    scope_mode = deps.auto_resolve_scope_mode(scene)
    if scope_mode == "NONE":
        return {"event": "STOP", "retry_delay": None}

    if deps.is_animation_playing() and bool(getattr(props, "lock_resolve_during_animation", True)):
        return {"event": "RETRY", "retry_delay": settings.retry_delay_sec}
    if deps.is_render_job_active():
        return {"event": "RETRY", "retry_delay": settings.retry_delay_sec}
    if deps.get_earth_object() is None:
        return {"event": "STOP", "retry_delay": None}

    scope, active_view_signature, resolve_signature = _ctx_auto_resolve_collect_scope_signatures(ctx, scene, scope_mode)
    if resolve_signature is None:
        return {"event": "RETRY", "retry_delay": settings.retry_delay_sec}

    altitude_info = deps.resolve_scope_altitude_info(scene, scope_mode=scope)
    if bool(altitude_info.get("inside_earth", False)):
        deps.set_camera_inside_earth_warning(scene, altitude_info.get("altitude_km"))
        deps.stop_auto_resolve_download_pipeline()
        return {"event": "STOP", "retry_delay": None}
    deps.clear_camera_inside_earth_warning(scene)

    scene_state = deps.read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return {"event": "STOP", "retry_delay": None}

    now = time.monotonic()
    output_signature = deps.output_resolution_signature(scene)
    pending_output_change = _ctx_auto_resolve_sync_state_signatures(
        ctx,
        scene_state,
        resolve_signature,
        output_signature,
        now,
    )
    current_quality_mode = _ctx_auto_resolve_texture_quality_mode(ctx, scene, props)
    quality_mode_changed = _scene_last_resolve_quality(scene, deps) != current_quality_mode

    min_interval_sec = settings.min_interval_sec_default
    last_resolve = float(scene_state.last_resolve_time or 0.0)
    if not quality_mode_changed and now - last_resolve < min_interval_sec:
        return {
            "event": "RETRY",
            "retry_delay": max(0.05, min_interval_sec - (now - last_resolve)),
            "scene_state": scene_state,
        }

    if (
        scene_state.last_processed_signature == resolve_signature
        and not pending_output_change
        and not quality_mode_changed
    ):
        return {
            "event": "NO_CHANGE",
            "retry_delay": None,
            "scene_state": scene_state,
        }

    return {
        "event": "PLAN",
        "retry_delay": None,
        "scene_state": scene_state,
        "scope": scope,
        "active_view_signature": active_view_signature,
        "resolve_signature": resolve_signature,
        "output_signature": output_signature,
        "pending_output_change": bool(pending_output_change),
        "quality_mode_changed": bool(quality_mode_changed),
        "current_quality_mode": current_quality_mode,
        "now": now,
    }


def _auto_resolve_detect_change(scene, props):
    return _ctx_auto_resolve_detect_change(_require_decision_ctx(), scene, props)


def _ctx_auto_resolve_plan_job(ctx, scene, props, detect_ctx):
    deps = ctx.deps
    settings = ctx.settings
    if scene is None:
        return {"event": "STOP", "retry_delay": None}
    if not isinstance(detect_ctx, dict):
        return {"event": "STOP", "retry_delay": None}
    if str(detect_ctx.get("event", "")) != "PLAN":
        return {
            "event": str(detect_ctx.get("event", "STOP") or "STOP"),
            "retry_delay": detect_ctx.get("retry_delay", None),
        }

    tile_utils = deps.get_tile_utils()
    if tile_utils is None:
        return {"event": "STOP", "retry_delay": None}

    scope = str(detect_ctx.get("scope", "CAMERA") or "CAMERA")
    active_view_signature = detect_ctx.get("active_view_signature")
    current_quality_mode = str(
        detect_ctx.get("current_quality_mode")
        or _ctx_auto_resolve_texture_quality_mode(ctx, scene, props)
    )
    if bool(detect_ctx.get("quality_mode_changed", False)) and not bool(detect_ctx.get("pending_output_change", False)):
        source_tiles = _scene_last_full_source_tiles(scene, deps)
        max_tile_budget = int(getattr(tile_utils, "MAX_SHADER_TILE_BUDGET", 12) or 12)
        if source_tiles:
            try:
                from ..render_prep import apply_texture_quality_to_full_tiles
                target_tiles = deps.canonical_tiles(
                    apply_texture_quality_to_full_tiles(source_tiles, current_quality_mode)
                )
            except deps.recoverable_exceptions:
                deps.logger.debug("Planetka auto-resolve: quality switch tile transform failed", exc_info=True)
                target_tiles = ()
            except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
                deps.logger.debug("Planetka auto-resolve: unexpected quality switch tile transform failure", exc_info=True)
                target_tiles = ()
            if target_tiles and len(target_tiles) <= max_tile_budget:
                deps.enqueue_size_estimation(scene, scope, active_view_signature, target_tiles, props)
                return {
                    "event": "DISPATCH",
                    "target_tiles": target_tiles,
                    "retry_delay": None,
                    "quality_switch_fast_path": True,
                }

    try:
        full_source_tiles = tile_utils.main(
            scope_mode="ACTIVE_VIEW" if (scope == "ACTIVE_VIEW" and active_view_signature is not None) else "CAMERA",
        )
        from ..render_prep import apply_texture_quality_to_full_tiles
        target_tiles = deps.canonical_tiles(
            apply_texture_quality_to_full_tiles(full_source_tiles, current_quality_mode)
        )
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka auto-resolve: tile computation failed", exc_info=True)
        return {"event": "RETRY", "retry_delay": settings.retry_delay_sec}
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka auto-resolve: unexpected tile computation failure", exc_info=True)
        return {"event": "RETRY", "retry_delay": settings.retry_delay_sec}

    deps.enqueue_size_estimation(scene, scope, active_view_signature, target_tiles, props)

    last_quality_mode = _scene_last_resolve_quality(scene, deps)
    if (
        target_tiles == deps.last_resolved_tiles(scene)
        and last_quality_mode == current_quality_mode
        and not bool(detect_ctx.get("pending_output_change", False))
    ):
        return {"event": "NO_CHANGE", "target_tiles": target_tiles, "retry_delay": None}

    return {"event": "DISPATCH", "target_tiles": target_tiles, "retry_delay": None}


def _auto_resolve_plan_job(scene, props, detect_ctx):
    return _ctx_auto_resolve_plan_job(_require_decision_ctx(), scene, props, detect_ctx)


def _ctx_auto_resolve_dispatch_job(ctx, scene, detect_ctx, plan_ctx):
    deps = ctx.deps
    settings = ctx.settings
    if scene is None:
        return {"event": "STOP", "retry_delay": None}
    if not isinstance(detect_ctx, dict) or not isinstance(plan_ctx, dict):
        return {"event": "STOP", "retry_delay": None}

    scene_state = detect_ctx.get("scene_state")
    if scene_state is None:
        return {"event": "STOP", "retry_delay": None}

    plan_event = str(plan_ctx.get("event", "STOP") or "STOP")
    if plan_event == "NO_CHANGE":
        scene_state.last_processed_signature = detect_ctx.get("resolve_signature")
        scene_state.last_resolve_time = float(detect_ctx.get("now", time.monotonic()) or time.monotonic())
        deps.write_scene_auto_resolve_state(scene_state)
        return {"event": "NO_CHANGE", "retry_delay": None}

    if plan_event != "DISPATCH":
        return {"event": plan_event, "retry_delay": plan_ctx.get("retry_delay", None)}

    target_tiles = tuple(plan_ctx.get("target_tiles", ()) or ())
    output_signature = deps.output_resolution_signature(scene)
    queued = deps.schedule_auto_resolve_download(
        scene,
        target_tiles,
        detect_ctx.get("resolve_signature"),
        output_signature,
    )
    if not queued:
        return {"event": "RETRY", "retry_delay": settings.retry_delay_sec}

    scene_state.last_change_time = time.monotonic()
    deps.write_scene_auto_resolve_state(scene_state)
    return {"event": "DISPATCH", "retry_delay": None}


def _auto_resolve_dispatch_job(scene, detect_ctx, plan_ctx):
    return _ctx_auto_resolve_dispatch_job(_require_decision_ctx(), scene, detect_ctx, plan_ctx)


def _ctx_auto_resolve_tick_once(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings

    if state.in_flight:
        return 0.1

    try:
        scene = getattr(getattr(deps.bpy, "context", None), "scene", None)
    except deps.recoverable_exceptions:
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)

    detect_ctx = _ctx_auto_resolve_detect_change(ctx, scene, props)
    detect_event = str(detect_ctx.get("event", "STOP") or "STOP")
    if detect_event == "STOP":
        return None
    if detect_event == "RETRY":
        return float(detect_ctx.get("retry_delay", settings.retry_delay_sec) or settings.retry_delay_sec)
    if detect_event == "NO_CHANGE":
        return None

    plan_ctx = _ctx_auto_resolve_plan_job(ctx, scene, props, detect_ctx)
    plan_event = str(plan_ctx.get("event", "STOP") or "STOP")
    if plan_event == "STOP":
        return None
    if plan_event == "RETRY":
        return float(plan_ctx.get("retry_delay", settings.retry_delay_sec) or settings.retry_delay_sec)
    if plan_event == "NO_CHANGE":
        return None

    dispatch_ctx = _ctx_auto_resolve_dispatch_job(ctx, scene, detect_ctx, plan_ctx)
    dispatch_event = str(dispatch_ctx.get("event", "STOP") or "STOP")
    if dispatch_event == "RETRY":
        return float(dispatch_ctx.get("retry_delay", settings.retry_delay_sec) or settings.retry_delay_sec)
    return None


def _auto_resolve_tick_once():
    return _ctx_auto_resolve_tick_once(_require_decision_ctx())


def _ctx_auto_resolve_timer(ctx):
    deps = ctx.deps
    state = ctx.state
    try:
        if not hasattr(deps.bpy.types.Scene, "planetka"):
            state.timer_running = False
            return None

        scene = getattr(getattr(deps.bpy, "context", None), "scene", None)
        if scene is None:
            state.timer_running = False
            return None

        scene_state = deps.read_scene_auto_resolve_state(scene)
        if scene_state is None:
            state.timer_running = False
            return None
        monitor_interval = max(0.05, _ctx_active_view_monitor_interval_seconds(ctx, scene))
        due_time = scene_state.next_due_time
        if due_time is None:
            scene_state.next_due_time = time.monotonic()
            deps.write_scene_auto_resolve_state(scene_state)
            due_time = scene_state.next_due_time

        if not _ctx_can_auto_resolve_run(ctx, scene):
            scene_state.next_due_time = None
            deps.write_scene_auto_resolve_state(scene_state)
            state.timer_running = False
            return None

        now = time.monotonic()
        remaining = float(due_time) - now
        if remaining > 0.0:
            return max(0.05, min(remaining, 1.0))

        deps.update_realtime_telemetry(scene)
        camera_signature = deps.camera_signature(scene)
        deps.handle_timeline_motion_optimization(scene)
        deps.handle_viewport_motion_optimization(scene, camera_signature)
        deps.handle_sunlight_motion_optimization(scene)
        deps.handle_view_scope_quality_transition(scene)
        retry_delay = _ctx_auto_resolve_tick_once(ctx)
        if retry_delay is not None:
            scene_state.next_due_time = time.monotonic() + max(0.05, float(retry_delay))
            deps.write_scene_auto_resolve_state(scene_state)
            return max(0.05, float(retry_delay))

        scene_state.next_due_time = time.monotonic() + monitor_interval
        deps.write_scene_auto_resolve_state(scene_state)
        return monitor_interval
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka auto-resolve timer tick failed", exc_info=True)
        state.timer_running = False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        deps.logger.debug("Planetka auto-resolve timer tick failed unexpectedly", exc_info=True)
        state.timer_running = False
    return None


def _auto_resolve_timer():
    return _ctx_auto_resolve_timer(_require_decision_ctx())


def _ctx_ensure_auto_resolve_service_running(ctx):
    deps = ctx.deps
    try:
        scene = getattr(getattr(deps.bpy, "context", None), "scene", None)
    except deps.recoverable_exceptions:
        scene = None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        scene = None
    if not _ctx_can_auto_resolve_run(ctx, scene):
        _ctx_stop_auto_resolve_service(ctx)
        return
    if scene is None:
        return
    scene_state = deps.read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return
    if scene_state.next_due_time is None:
        scene_state.next_due_time = time.monotonic() + max(0.05, _ctx_active_view_monitor_interval_seconds(ctx, scene))
        deps.write_scene_auto_resolve_state(scene_state)
    _ctx_arm_auto_resolve_timer(ctx, force_immediate=False)


def ensure_auto_resolve_service_running():
    return _ctx_ensure_auto_resolve_service_running(_require_decision_ctx())


def _ctx_stop_auto_resolve_service(ctx):
    deps = ctx.deps
    state = ctx.state
    try:
        if deps.bpy.app.timers.is_registered(_auto_resolve_timer):
            deps.bpy.app.timers.unregister(_auto_resolve_timer)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed stopping auto-resolve timer", exc_info=True)
    try:
        if deps.bpy.app.timers.is_registered(_auto_resolve_noncritical_timer):
            deps.bpy.app.timers.unregister(_auto_resolve_noncritical_timer)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed stopping non-critical auto-resolve timer", exc_info=True)
    state.timer_running = False
    state.noncritical_timer_running = False
    deps.stop_auto_resolve_download_pipeline()
    state.next_due_time.clear()
    state.last_camera_signature.clear()
    state.last_output_signature.clear()
    state.last_change_time.clear()
    state.last_resolve_time.clear()
    state.last_processed_signature.clear()
    state.pending_output_change.clear()
    state.trigger_last_signature.clear()
    deps.viewport_opt_last_signature.clear()
    deps.sunlight_last_signature.clear()
    deps.viewport_scope_last.clear()
    deps.viewport_scope_last_resolve_time.clear()
    deps.last_realtime_telemetry.clear()
    deps.timeline_last_signature.clear()
    deps.frame_keyed_runtime_last_signature.clear()
    deps.nav_camera_control_last_signature.clear()
    deps.sunlight_object_name_cache.clear()
    state.noncritical_pending.clear()
    state.size_estimate_last_signature.clear()


def stop_auto_resolve_service():
    return _ctx_stop_auto_resolve_service(_require_decision_ctx())
