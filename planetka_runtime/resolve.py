import json
import threading
import time

_RESOLVE_DOWNLOAD_CTX = None
_LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY = "planetka_last_resolve_texture_quality_mode"


def _quality_mode_for_job(deps, job):
    try:
        return deps.normalize_texture_quality_mode(
            deps.job_field(job, "texture_quality_mode", "PREVIEW")
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return "PREVIEW"


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


def _require_download_ctx():
    ctx = _RESOLVE_DOWNLOAD_CTX
    if ctx is None:
        raise RuntimeError("Planetka resolve download context is not configured.")
    return ctx


def _ctx_arm_resolve_timer(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings
    try:
        already = bool(deps.bpy.app.timers.is_registered(_resolve_pump_timer))
        if not already:
            deps.bpy.app.timers.register(
                _resolve_pump_timer,
                first_interval=settings.download_pump_interval_sec,
                persistent=True,
            )
        now_registered = bool(deps.bpy.app.timers.is_registered(_resolve_pump_timer))
        deps.resolve_trace(
            f"Pump arm requested (already={already}, now_registered={now_registered})"
        )
        state.download_timer_running = True
    except deps.recoverable_exceptions:
        state.download_timer_running = False
        deps.resolve_trace("Pump arm failed with recoverable exception")
        deps.logger.debug("Planetka: failed arming resolve timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        state.download_timer_running = False
        deps.resolve_trace("Pump arm failed with runtime/type/value exception")
        deps.logger.debug("Planetka: failed arming resolve timer", exc_info=True)


def _arm_resolve_timer():
    return _ctx_arm_resolve_timer(_require_download_ctx())


def _ctx_start_resolve_download_thread(ctx, job):
    deps = ctx.deps
    state = ctx.state
    if not deps.is_resolve_download_job(job):
        return
    worker = threading.Thread(
        target=_ctx_resolve_download_worker,
        args=(ctx, job),
        name="PlanetkaResolve",
        daemon=True,
    )
    state.download_thread = worker
    worker.start()


def _ctx_resolve_texture_quality_mode(
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


def _ctx_schedule_resolve_download(
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
    texture_quality_mode = _ctx_resolve_texture_quality_mode(
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

    with state.download_lock:
        # Manual resolve is authoritative. Any older worker is cancelled by epoch
        # mismatch and must not apply or store data after this point.
        state.download_epoch = int(state.download_epoch) + 1
        epoch = int(state.download_epoch)
        state.download_request_counter += 1
        request_id = int(state.download_request_counter)

        active_job = state.download_active_job
        if deps.is_resolve_download_job(active_job):
            cancel_event = deps.job_field(active_job, "cancel_event")
            if cancel_event is not None:
                try:
                    cancel_event.set()
                except deps.recoverable_exceptions:
                    deps.logger.debug("Planetka: failed signaling active resolve cancellation", exc_info=True)
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    deps.logger.debug("Planetka: failed signaling active resolve cancellation", exc_info=True)

        new_job = deps.build_resolve_download_job(
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
        state.download_completed = None
        state.download_active_job = new_job
        job_to_start = new_job
        deps.resolve_trace(
            f"resolve start request_id={request_id} manual={bool(manual_request)} scene={scene_id} "
            f"tiles={len(target_tiles_tuple)} epoch={epoch}"
        )

    _ctx_start_resolve_download_thread(ctx, job_to_start)
    _ctx_arm_resolve_timer(ctx)
    return True

def _ctx_start_resolve_download(ctx, scene, target_tiles, manual_request=False, texture_quality_mode_override=None):
    deps = ctx.deps
    state = ctx.state
    if scene is None:
        return False
    if bool(manual_request) and deps.is_render_job_active():
        # Manual resolves should be blocked only while Blender is actually write-locked.
        # A short post-render guard window is used for resolve reliability, but should
        # not reject explicit user resolve actions once write access is available again.
        lock_reason = _ctx_blend_data_write_lock_reason(ctx)
        if lock_reason:
            deps.logger.info(
                "Planetka: ignoring deferred resolve request during active render lock (%s).",
                str(lock_reason),
            )
            return False
    camera_signature = deps.camera_signature(scene)
    if camera_signature is None:
        return False
    output_signature = deps.output_resolution_signature(scene)
    started = _ctx_schedule_resolve_download(
        ctx,
        scene,
        tuple(target_tiles or ()),
        camera_signature,
        output_signature,
        manual_request=bool(manual_request),
        texture_quality_mode_override=texture_quality_mode_override,
    )
    return bool(started)


def start_resolve_download(scene, target_tiles, manual_request=False, texture_quality_mode_override=None):
    return _ctx_start_resolve_download(
        _require_download_ctx(),
        scene,
        target_tiles,
        manual_request=manual_request,
        texture_quality_mode_override=texture_quality_mode_override,
    )


def _ctx_mark_manual_resolve_error(ctx, scene, message):
    deps = ctx.deps
    text = str(message or "Unknown resolve error")
    deps.logger.error("Planetka resolve failed: %s", text)
    if scene is None:
        return
    try:
        scene["planetka_last_resolve_error"] = text
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing resolve error on scene", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed storing resolve error on scene", exc_info=True)


def _mark_manual_resolve_error(scene, message):
    return _ctx_mark_manual_resolve_error(_require_download_ctx(), scene, message)


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
        log_label="Planetka: failed storing resolve summary",
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
            "session blocked",
            "planetka cloud could not stream",
            "does not have access to remote earth data",
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
        # Keep the completed payload until the pump can retry the same apply.
        return None

    deps.resolve_trace(
        "Apply payload dropped after persistent read-only Blender state "
        f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, "
        f"attempts={lock_attempts}, reason={reason})"
    )
    deps.logger.warning(
        "Planetka: dropping completed resolve payload after %.2fs waiting for apply write access "
        "(request_id=%s, attempts=%d, reason=%s).",
        float(waited_sec),
        str(deps.job_field(job, "request_id", "")),
        int(lock_attempts),
        str(reason),
    )
    deps.job_set_field(job, "apply_operator_lock_since", 0.0)
    deps.job_set_field(job, "apply_operator_lock_attempts", 0)
    _ctx_mark_manual_resolve_error(
        ctx,
        scene,
        (
            "Apply deferred too long because Blender data stayed read-only "
            f"({reason}); try Resolve again."
        ),
    )
    return False


def _ctx_wait_or_drop_completed_during_guard(ctx, scene, job, manual_request, *, guard_name, user_message):
    deps = ctx.deps
    settings = ctx.settings
    field_prefix = f"apply_{guard_name}_guard"
    now = time.monotonic()
    try:
        guard_since = float(deps.job_field(job, f"{field_prefix}_since", 0.0) or 0.0)
    except (TypeError, ValueError):
        guard_since = 0.0
    if guard_since <= 0.0:
        guard_since = now
    try:
        guard_attempts = int(deps.job_field(job, f"{field_prefix}_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        guard_attempts = 1
    deps.job_set_field(job, f"{field_prefix}_since", float(guard_since))
    deps.job_set_field(job, f"{field_prefix}_attempts", int(max(1, guard_attempts)))
    waited_sec = max(0.0, float(now) - float(guard_since))
    wait_budget_sec = min(
        float(settings.download_completed_max_age_sec),
        max(float(settings.download_scene_wait_sec), 6.0),
    )
    if waited_sec < wait_budget_sec:
        deps.resolve_trace(
            f"Download finished but {guard_name} guard is active; waiting "
            f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, "
            f"attempts={guard_attempts})"
        )
        return False, None, None, None

    deps.resolve_trace(
        f"Download completion dropped after persistent {guard_name} guard "
        f"(request_id={deps.job_field(job, 'request_id')}, waited={waited_sec:.2f}s, "
        f"attempts={guard_attempts})"
    )
    deps.logger.warning(
        "Planetka: dropping completed resolve payload after %.2fs waiting for %s guard "
        "(request_id=%s, attempts=%d).",
        float(waited_sec),
        str(guard_name),
        str(deps.job_field(job, "request_id", "")),
        int(guard_attempts),
    )
    deps.job_set_field(job, f"{field_prefix}_since", 0.0)
    deps.job_set_field(job, f"{field_prefix}_attempts", 0)
    _ctx_mark_manual_resolve_error(ctx, scene, str(user_message or "Resolve was blocked."))
    return True, None, None, None


def _ctx_mark_resolve_terminal_failure(ctx, scene, scene_id, job, message):
    deps = ctx.deps
    if scene is None:
        return
    text = str(message or "Planetka resolve failed.").strip() or "Planetka resolve failed."
    try:
        scene["planetka_last_resolve_error"] = text
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed storing resolve terminal error on scene", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed storing resolve terminal error on scene", exc_info=True)


def _mark_resolve_terminal_failure(scene, scene_id, job, message):
    return _ctx_mark_resolve_terminal_failure(_require_download_ctx(), scene, scene_id, job, message)


def _ctx_handle_resolve_download_failure(ctx, job, error_message):
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
        _ctx_mark_manual_resolve_error(
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
        _ctx_mark_resolve_terminal_failure(
            ctx,
            scene,
            scene_id,
            job,
            f"Download failed: {str(error_message or '').strip() or 'Unknown error'}",
        )
        if error_message:
            deps.logger.warning("Planetka resolve download terminal failure: %s", error_message)
        return

    if error_message:
        deps.logger.warning("Planetka resolve download failed: %s", error_message)


def _handle_resolve_download_failure(job, error_message):
    return _ctx_handle_resolve_download_failure(_require_download_ctx(), job, error_message)


def _ctx_resolve_completion_epoch_matches(ctx, job):
    deps = ctx.deps
    state = ctx.state
    try:
        job_epoch = int(deps.job_field(job, "epoch", -1))
    except (TypeError, ValueError):
        job_epoch = -1
    with state.download_lock:
        current_epoch = int(state.download_epoch)
    return job_epoch == current_epoch


def _ctx_resolve_handle_cancel_or_failure(ctx, result, job, manual_request):
    deps = ctx.deps
    if bool(result.get("cancelled", False)):
        deps.resolve_trace(
            f"Download finished cancelled (request_id={deps.job_field(job, 'request_id')}, manual={manual_request})"
        )
        return True

    if not bool(result.get("success", False)):
        _ctx_handle_resolve_download_failure(ctx, job, str(result.get("error", "") or ""))
        return True

    return False


def _resolve_handle_cancel_or_failure(result, job, manual_request):
    return _ctx_resolve_handle_cancel_or_failure(_require_download_ctx(), result, job, manual_request)


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


def _ctx_resolve_prepare_apply_context(ctx, job, manual_request):
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
            "Planetka: dropping completed resolve payload because scene context did not return "
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
            "Planetka: dropping completed resolve payload after %.2fs waiting for write access "
            "(request_id=%s, attempts=%d, reason=%s).",
            float(waited_sec),
            str(deps.job_field(job, "request_id", "")),
            int(lock_attempts),
            str(lock_reason),
        )
        _ctx_mark_manual_resolve_error(
            ctx,
            scene,
            (
                "Apply deferred too long because Blender data stayed read-only "
                f"({lock_reason}); try Resolve again."
            ),
        )
        return True, None, None, None
    deps.job_set_field(job, "apply_lock_since", 0.0)
    deps.job_set_field(job, "apply_lock_attempts", 0)
    job_target_tiles = deps.canonical_tiles(deps.job_field(job, "target_tiles", ()))

    if deps.is_render_job_active():
        deps.logger.info(
            "Planetka: applying resolve despite render guard because Blender data is writable "
            "(request_id=%s).",
            str(deps.job_field(job, "request_id", "")),
        )

    props = getattr(scene, "planetka", None)
    if deps.is_animation_playing() and bool(getattr(props, "lock_resolve_during_animation", True)):
        _ctx_mark_manual_resolve_error(ctx, scene, "Blocked by animation playback lock.")
        return True, None, None, None

    if manual_request:
        current_output_signature = deps.output_resolution_signature(scene)
        if current_output_signature != deps.job_field(job, "output_signature"):
            deps.logger.warning("Planetka resolve continuing despite output signature change.")
    return True, scene, scene_id, job_target_tiles


def _resolve_prepare_apply_context(job, manual_request):
    return _ctx_resolve_prepare_apply_context(_require_download_ctx(), job, manual_request)


def _ctx_resolve_apply_downloaded_tiles(ctx, scene, scene_id, job, manual_request, job_target_tiles):
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
                "Planetka resolve apply returned %s for %d tile(s).",
                str(op_result),
                len(job_target_tiles),
            )
            _ctx_mark_manual_resolve_error(ctx, scene, apply_error)
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
            "Planetka resolve apply failed with recoverable exception "
            "(request_id=%s, manual=%s, tiles=%d): %s",
            str(deps.job_field(job, "request_id", "")),
            bool(manual_request),
            int(len(job_target_tiles)),
            str(exc_text or "unknown"),
        )
        _ctx_mark_manual_resolve_error(ctx, scene, apply_error)
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
            "Planetka resolve apply failed unexpectedly "
            "(request_id=%s, manual=%s, tiles=%d): %s",
            str(deps.job_field(job, "request_id", "")),
            bool(manual_request),
            int(len(job_target_tiles)),
            str(exc_text or "unknown"),
        )
        _ctx_mark_manual_resolve_error(ctx, scene, apply_error)
        return False
    finally:
        state.in_flight = False
    return True


def _resolve_apply_downloaded_tiles(scene, scene_id, job, manual_request, job_target_tiles):
    return _ctx_resolve_apply_downloaded_tiles(
        _require_download_ctx(),
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
    )


def _ctx_resolve_summary_total_bytes(ctx, job_target_tiles, job, result):
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


def _resolve_summary_total_bytes(job_target_tiles, job, result):
    return _ctx_resolve_summary_total_bytes(_require_download_ctx(), job_target_tiles, job, result)


def _ctx_finalize_resolve_apply(ctx, scene, scene_id, job, manual_request, job_target_tiles, resolved_at, summary_total_bytes):
    deps = ctx.deps
    job_quality_mode = _quality_mode_for_job(deps, job)
    try:
        created_at = float(deps.job_field(job, "created_at", resolved_at) or resolved_at)
    except (TypeError, ValueError):
        created_at = resolved_at
    total_seconds = max(0.0, float(resolved_at) - float(created_at))
    _ctx_write_last_resolve_summary(ctx, scene, len(job_target_tiles), summary_total_bytes, total_seconds)

    scene_id = deps.scene_key(scene)
    try:
        if "planetka_last_resolve_error" in scene:
            del scene["planetka_last_resolve_error"]
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed clearing resolve error marker", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed clearing resolve error marker", exc_info=True)
    if manual_request:
        try:
            scene[_LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY] = job_quality_mode
        except deps.recoverable_exceptions:
            deps.logger.debug("Planetka: failed storing last manual resolve quality", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            deps.logger.debug("Planetka: failed storing last manual resolve quality", exc_info=True)
        deps.logger.warning(
            "Planetka resolve applied successfully (%d tile(s)).",
            len(job_target_tiles),
        )
    deps.resolve_trace(
        f"Shader update finished (request_id={deps.job_field(job, 'request_id')}, tiles={len(job_target_tiles)})"
    )


def _finalize_resolve_apply(scene, scene_id, job, manual_request, job_target_tiles, resolved_at, summary_total_bytes):
    return _ctx_finalize_resolve_apply(
        _require_download_ctx(),
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
        resolved_at,
        summary_total_bytes,
    )


def _ctx_handle_resolve_download_complete(ctx, result):
    deps = ctx.deps
    if not isinstance(result, dict):
        return True
    job = result.get("job")
    if not deps.is_resolve_download_job(job):
        return True
    manual_request = bool(deps.job_field(job, "manual_request", False))

    if not _ctx_resolve_completion_epoch_matches(ctx, job):
        return True

    if _ctx_resolve_handle_cancel_or_failure(ctx, result, job, manual_request):
        return True

    consume, scene, scene_id, job_target_tiles = _ctx_resolve_prepare_apply_context(ctx, job, manual_request)
    if not consume:
        return False
    if scene is None:
        return True

    apply_result = _ctx_resolve_apply_downloaded_tiles(
        ctx,
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
    )
    if apply_result is None:
        # Keep the completed payload until transient read-only states clear.
        return False
    if not apply_result:
        return True

    resolved_at = time.monotonic()
    summary_total_bytes = _ctx_resolve_summary_total_bytes(ctx, job_target_tiles, job, result)
    _ctx_finalize_resolve_apply(
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


def _handle_resolve_download_complete(result):
    return _ctx_handle_resolve_download_complete(_require_download_ctx(), result)


def _ctx_resolve_download_worker(ctx, job):
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
            job_epoch = int(deps.job_field(job, "epoch", -1))
            current_epoch = int(state.download_epoch)
            store_completed = bool(state.download_active_job is job and job_epoch == current_epoch)
            if state.download_active_job is job:
                state.download_active_job = None
                state.download_thread = None
            if store_completed:
                state.download_completed = result
            deps.resolve_trace(
                f"Worker finalize (request_id={deps.job_field(job, 'request_id')}, job_epoch={job_epoch}, "
                f"current_epoch={current_epoch}, store_completed={store_completed})"
            )


def _resolve_download_worker(job):
    return _ctx_resolve_download_worker(_require_download_ctx(), job)


def _ctx_resume_or_stop_download_pump_after_error(ctx):
    deps = ctx.deps
    state = ctx.state
    settings = ctx.settings
    with state.download_lock:
        has_active = state.download_active_job is not None
        has_completed = state.download_completed is not None
    has_thread = state.download_thread is not None
    if has_active or has_completed or has_thread:
        state.download_timer_running = True
        return settings.download_pump_interval_sec
    state.download_timer_running = False
    return None


def _ctx_resolve_pump_timer(ctx):
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
            if completed is not None:
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
                        consume_completed = bool(_ctx_handle_resolve_download_complete(ctx, completed))
                    except deps.recoverable_exceptions:
                        _ctx_handle_resolve_download_failure(
                            ctx,
                            completed_job,
                            "Finalize crashed with recoverable exception.",
                        )
                        deps.logger.exception(
                            "Planetka: resolve finalize crashed for completed payload "
                            "(request_id=%s). Dropping payload to keep pipeline alive.",
                            str(completed_request_id),
                        )
                        consume_completed = True
                    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
                        _ctx_handle_resolve_download_failure(
                            ctx,
                            completed_job,
                            "Finalize crashed with unexpected exception.",
                        )
                        deps.logger.exception(
                            "Planetka: resolve finalize crashed unexpectedly for completed payload "
                            "(request_id=%s). Dropping payload to keep pipeline alive.",
                            str(completed_request_id),
                        )
                        consume_completed = True
                    if consume_completed:
                        with state.download_lock:
                            if state.download_completed is completed:
                                state.download_completed = None

        with state.download_lock:
            has_active = state.download_active_job is not None
            has_completed = state.download_completed is not None

        try:
            scene = getattr(getattr(deps.bpy, "context", None), "scene", None)
        except deps.recoverable_exceptions:
            scene = None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            scene = None
        if scene is not None:
            deps.tag_view3d_redraw()

        if not has_active and not has_completed:
            state.download_timer_running = False
            deps.resolve_trace("Pump stop: no active/completed jobs")
            return None

        state.download_timer_running = True
        return settings.download_pump_interval_sec
    except deps.recoverable_exceptions:
        deps.resolve_trace("Pump failed with recoverable exception")
        deps.logger.exception("Planetka resolve timer failed")
        with state.download_lock:
            state.download_completed = None
        return _ctx_resume_or_stop_download_pump_after_error(ctx)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        deps.resolve_trace("Pump failed with unexpected exception")
        deps.logger.exception("Planetka resolve timer failed unexpectedly")
        with state.download_lock:
            state.download_completed = None
        return _ctx_resume_or_stop_download_pump_after_error(ctx)

    state.download_timer_running = False
    return None


def _resolve_pump_timer():
    return _ctx_resolve_pump_timer(_require_download_ctx())


def _ctx_stop_resolve(ctx):
    deps = ctx.deps
    state = ctx.state

    with state.download_lock:
        state.download_epoch = int(state.download_epoch) + 1
        deps.resolve_trace(f"Pipeline stop called; epoch advanced to {state.download_epoch}")

        active_job = state.download_active_job
        if deps.is_resolve_download_job(active_job):
            cancel_event = deps.job_field(active_job, "cancel_event")
            if cancel_event is not None:
                try:
                    cancel_event.set()
                except deps.recoverable_exceptions:
                    deps.logger.debug("[PKA-STATE-001] Planetka: failed signaling resolve cancel event", exc_info=True)

        state.download_active_job = None
        state.download_completed = None

    try:
        if deps.bpy.app.timers.is_registered(_resolve_pump_timer):
            deps.bpy.app.timers.unregister(_resolve_pump_timer)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed stopping resolve timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        deps.logger.debug("Planetka: failed stopping resolve timer", exc_info=True)

    state.download_timer_running = False


def stop_resolve():
    return _ctx_stop_resolve(_require_download_ctx())
