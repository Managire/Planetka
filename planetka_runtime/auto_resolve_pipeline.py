_MOVED_NAMES = {
    "_mark_auto_resolve_dirty",
    "_auto_resolve_idle_seconds",
    "_is_navigation_user_edit_active",
    "_active_view_monitor_interval_seconds",
    "_arm_auto_resolve_timer",
    "_auto_resolve_download_job_signature",
    "_arm_auto_resolve_download_timer",
    "_start_auto_resolve_download_thread",
    "_show_download_status_popup",
    "_schedule_auto_resolve_download",
    "queue_resolve_download",
    "_mark_manual_queued_resolve_error",
    "_read_scene_last_resolve_error",
    "_store_resolve_summary",
    "_write_last_resolve_summary",
    "_is_non_retryable_resolve_error",
    "_mark_auto_resolve_terminal_failure",
    "_handle_auto_resolve_download_failure",
    "_auto_resolve_completion_epoch_state",
    "_auto_resolve_handle_cancel_or_failure",
    "_auto_resolve_log_pending_request_overlap",
    "_auto_resolve_prepare_apply_context",
    "_auto_resolve_apply_downloaded_tiles",
    "_auto_resolve_summary_total_bytes",
    "_finalize_auto_resolve_apply",
    "_handle_auto_resolve_download_complete",
    "_auto_resolve_download_worker",
    "_auto_resolve_download_pump_timer",
    "stop_auto_resolve_download_pipeline",
    "request_auto_resolve",
    "_can_auto_resolve_run",
    "update_auto_resolve",
    "_auto_resolve_collect_scope_signatures",
    "_auto_resolve_sync_state_signatures",
    "_auto_resolve_update_size_estimation",
    "_arm_auto_resolve_noncritical_timer",
    "_auto_resolve_enqueue_size_estimation",
    "_auto_resolve_noncritical_timer",
    "_auto_resolve_detect_change",
    "_auto_resolve_plan_job",
    "_auto_resolve_dispatch_job",
    "_auto_resolve_tick_once",
    "_auto_resolve_timer",
    "ensure_auto_resolve_service_running",
    "stop_auto_resolve_service",
}


def configure(runtime):
    module_globals = globals()
    for key, value in runtime.items():
        if key in _MOVED_NAMES:
            continue
        module_globals[key] = value


def _mark_auto_resolve_dirty(scene, immediate=False, force_resolve=False):
    if not scene:
        return
    scene_state = _read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return
    now = time.monotonic()
    scene_state.last_camera_signature = None
    scene_state.last_output_signature = None
    scene_state.last_processed_signature = None
    scene_state.pending_output_change = bool(force_resolve)
    scene_state.last_change_time = now - (AUTO_RESOLVE_IDLE_SEC_DEFAULT if immediate else 0.0)
    _write_scene_auto_resolve_state(scene_state)


def _auto_resolve_idle_seconds(scene):
    props = getattr(scene, "planetka", None) if scene is not None else None
    try:
        idle_sec = float(getattr(props, "auto_resolve_idle_sec", AUTO_RESOLVE_IDLE_SEC_DEFAULT))
    except (TypeError, ValueError):
        idle_sec = AUTO_RESOLVE_IDLE_SEC_DEFAULT
    return max(0.1, min(3.0, idle_sec))


def _is_navigation_user_edit_active(scene):
    if scene is None:
        return False
    now = time.monotonic()
    idle_window = _auto_resolve_idle_seconds(scene)
    guard_window = max(float(idle_window), float(_NAV_CAMERA_CONTROL_SYNC_GRACE_SEC))
    return (now - float(_NAVIGATION_USER_EDIT_LAST_TOUCH)) < guard_window


def _active_view_monitor_interval_seconds(scene):
    return _auto_resolve_idle_seconds(scene)


def _arm_auto_resolve_timer(force_immediate=False):
    global _AUTO_RESOLVE_TIMER_RUNNING
    try:
        if force_immediate and bpy.app.timers.is_registered(_auto_resolve_timer):
            bpy.app.timers.unregister(_auto_resolve_timer)
            _AUTO_RESOLVE_TIMER_RUNNING = False
        if not bpy.app.timers.is_registered(_auto_resolve_timer):
            bpy.app.timers.register(
                _auto_resolve_timer,
                first_interval=0.0 if force_immediate else 0.05,
                persistent=True,
            )
        _AUTO_RESOLVE_TIMER_RUNNING = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _AUTO_RESOLVE_TIMER_RUNNING = False
        logger.debug("Planetka: failed arming auto-resolve timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        _AUTO_RESOLVE_TIMER_RUNNING = False
        logger.debug("Planetka: failed arming auto-resolve timer", exc_info=True)


def _auto_resolve_download_job_signature(job):
    if not _is_auto_resolve_download_job(job):
        return None
    return (
        int(_job_field(job, "scene_id", 0) or 0),
        tuple(_job_field(job, "target_tiles", ()) or ()),
        _job_field(job, "camera_signature"),
        _job_field(job, "output_signature"),
        _normalize_texture_quality_mode(_job_field(job, "texture_quality_mode", "PREVIEW")),
    )


def _arm_auto_resolve_download_timer():
    global _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING
    try:
        already = bool(bpy.app.timers.is_registered(_auto_resolve_download_pump_timer))
        if not already:
            bpy.app.timers.register(
                _auto_resolve_download_pump_timer,
                first_interval=_AUTO_RESOLVE_DOWNLOAD_PUMP_INTERVAL_SEC,
                persistent=True,
            )
        now_registered = bool(bpy.app.timers.is_registered(_auto_resolve_download_pump_timer))
        _resolve_trace(
            f"Pump arm requested (already={already}, now_registered={now_registered})"
        )
        _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = False
        _resolve_trace("Pump arm failed with recoverable exception")
        logger.debug("Planetka: failed arming auto-resolve download timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = False
        _resolve_trace("Pump arm failed with runtime/type/value exception")
        logger.debug("Planetka: failed arming auto-resolve download timer", exc_info=True)


def _start_auto_resolve_download_thread(job):
    global _AUTO_RESOLVE_DOWNLOAD_THREAD
    if not _is_auto_resolve_download_job(job):
        return
    worker = threading.Thread(
        target=_auto_resolve_download_worker,
        args=(job,),
        name="PlanetkaAutoResolveDownload",
        daemon=True,
    )
    _AUTO_RESOLVE_DOWNLOAD_THREAD = worker
    worker.start()
    _show_download_status_popup()


def _show_download_status_popup():
    # Disabled due Blender 5.1 native crash inside popup cancel path:
    # wm_operator_ui_popup_cancel -> ui_popup_handler (SIGSEGV).
    # Keep runtime status in Status Check panel only until a safer overlay path is implemented.
    return


def _schedule_auto_resolve_download(
    scene,
    target_tiles,
    camera_signature,
    output_signature,
    manual_request=False,
):
    global _AUTO_RESOLVE_DOWNLOAD_REQUEST_COUNTER
    global _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB
    global _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB

    if scene is None:
        return False

    # Keep auto-fix notices visible only until the next resolve request starts.
    _clear_status_notices(scene)

    scene_id = _scene_key(scene)
    prefs = get_prefs()
    props = getattr(scene, "planetka", None)
    base_path = str(getattr(prefs, "texture_base_path", "") or "") if prefs else ""
    texture_quality_mode = "PREVIEW"
    try:
        texture_quality_mode = _enforce_texture_quality_mode_for_account(
            scene,
            getattr(props, "texture_quality_mode", "PREVIEW"),
        )
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        texture_quality_mode = "PREVIEW"
    target_tiles_tuple = tuple(target_tiles or ())
    try:
        nav_latitude_deg = float(getattr(props, "nav_latitude_deg", 0.0)) if props is not None else 0.0
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        nav_latitude_deg = 0.0
    try:
        nav_longitude_deg = float(getattr(props, "nav_longitude_deg", 0.0)) if props is not None else 0.0
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        nav_longitude_deg = 0.0
    try:
        nav_altitude_km = max(0.0, float(getattr(props, "nav_altitude_km", 0.0))) if props is not None else 0.0
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        nav_altitude_km = 0.0

    job_to_start = None
    should_arm_timer = False
    with _AUTO_RESOLVE_DOWNLOAD_LOCK:
        epoch = int(_AUTO_RESOLVE_DOWNLOAD_EPOCH)
        _AUTO_RESOLVE_DOWNLOAD_REQUEST_COUNTER += 1
        request_id = int(_AUTO_RESOLVE_DOWNLOAD_REQUEST_COUNTER)
        new_job = _build_auto_resolve_download_job(
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

        new_sig = _auto_resolve_download_job_signature(new_job)
        active_sig = _auto_resolve_download_job_signature(_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB)
        pending_sig = _auto_resolve_download_job_signature(_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB)
        if new_sig == active_sig or new_sig == pending_sig:
            if bool(manual_request):
                if new_sig == active_sig and _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB):
                    _job_set_field(_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB, "manual_request", True)
                if new_sig == pending_sig and _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB):
                    _job_set_field(_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB, "manual_request", True)
            _resolve_trace(
                f"queue dedupe request_id={request_id} manual={bool(manual_request)} signature={new_sig!r}"
            )
            should_arm_timer = (
                _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB is not None
                or _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB is not None
                or _AUTO_RESOLVE_DOWNLOAD_COMPLETED is not None
            )
        else:
            _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB = new_job
            # Cancel in-flight download immediately when a newer request arrives.
            # The latest request should start as soon as possible.
            if _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB):
                active_cancel_event = _job_field(_AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB, "cancel_event")
                if active_cancel_event is not None:
                    try:
                        active_cancel_event.set()
                    except PLANETKA_RECOVERABLE_EXCEPTIONS:
                        logger.debug("Planetka: failed signaling active resolve cancellation", exc_info=True)
                    except (RuntimeError, TypeError, ValueError, AttributeError):
                        logger.debug("Planetka: failed signaling active resolve cancellation", exc_info=True)
            if _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB is None:
                _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB = _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB
                _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB = None
                job_to_start = _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB
            _resolve_trace(
                f"queue request_id={request_id} manual={bool(manual_request)} scene={scene_id} tiles={len(target_tiles_tuple)}"
            )
            should_arm_timer = True

    if _is_auto_resolve_download_job(job_to_start):
        _start_auto_resolve_download_thread(job_to_start)
    if should_arm_timer:
        _arm_auto_resolve_download_timer()
    return should_arm_timer


def queue_resolve_download(scene, target_tiles, manual_request=False):
    if scene is None:
        return False
    camera_signature = _camera_signature(scene)
    if camera_signature is None:
        return False
    output_signature = _output_resolution_signature(scene)
    queued = _schedule_auto_resolve_download(
        scene,
        tuple(target_tiles or ()),
        camera_signature,
        output_signature,
        manual_request=bool(manual_request),
    )
    if queued:
        _AUTO_RESOLVE_LAST_CHANGE_TIME[_scene_key(scene)] = time.monotonic()
    return bool(queued)


def _mark_manual_queued_resolve_error(scene, message):
    text = str(message or "Unknown queued resolve error")
    logger.error("Planetka queued resolve failed: %s", text)
    if scene is None:
        return
    try:
        scene["planetka_last_resolve_error"] = text
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing queued resolve error on scene", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed storing queued resolve error on scene", exc_info=True)


def _read_scene_last_resolve_error(scene):
    if scene is None:
        return ""
    try:
        return str(scene.get("planetka_last_resolve_error", "") or "").strip()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return ""
    except (RuntimeError, TypeError, ValueError):
        return ""


def _store_resolve_summary(
    scene,
    tile_count,
    summary_total_bytes,
    total_seconds,
    *,
    log_label="Planetka: failed storing resolve summary",
):
    if scene is None:
        return
    try:
        scene[LAST_RESOLVE_TILE_COUNT_KEY] = int(max(0, int(tile_count)))
        scene[LAST_RESOLVE_DOWNLOADED_MB_KEY] = float(
            max(0.0, float(summary_total_bytes) / float(1024.0 ** 2))
        )
        # Keep legacy key updated for backward compatibility with older UI builds.
        scene[LAST_RESOLVE_DOWNLOADED_GB_KEY] = float(
            max(0.0, float(summary_total_bytes) / float(1024.0 ** 3))
        )
        scene[LAST_RESOLVE_TOTAL_SECONDS_KEY] = float(max(0.0, float(total_seconds)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug(str(log_label or "Planetka: failed storing resolve summary"), exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug(str(log_label or "Planetka: failed storing resolve summary"), exc_info=True)


def _write_last_resolve_summary(scene, tile_count, summary_total_bytes, total_seconds):
    _store_resolve_summary(
        scene,
        tile_count,
        summary_total_bytes,
        total_seconds,
        log_label="Planetka: failed storing queued/auto resolve summary",
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
            "does not currently have access to this remote data request",
            "does not have access to remote earth data",
            "account blocked",
        )
    )


def _mark_auto_resolve_terminal_failure(scene, scene_id, job, message):
    if scene is None:
        return
    text = str(message or "Planetka auto-resolve failed.").strip() or "Planetka auto-resolve failed."
    try:
        scene["planetka_last_resolve_error"] = text
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing auto-resolve terminal error on scene", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed storing auto-resolve terminal error on scene", exc_info=True)

    now = time.monotonic()
    latest_signature = None
    if _is_auto_resolve_download_job(job):
        latest_signature = _job_field(job, "camera_signature")
    if latest_signature is None:
        latest_signature = _camera_signature(scene)
    scene_state = _read_scene_auto_resolve_state(scene_id)
    if scene_state is not None:
        if latest_signature is not None:
            scene_state.last_camera_signature = latest_signature
            scene_state.last_processed_signature = latest_signature
        scene_state.last_resolve_time = now
        scene_state.last_change_time = now
        scene_state.pending_output_change = False
        _write_scene_auto_resolve_state(scene_state)
    _VIEWPORT_SCOPE_LAST_RESOLVE_TIME[scene_id] = now


def _handle_auto_resolve_download_failure(job, error_message):
    try:
        scene_id = int(_job_field(job, "scene_id", 0) or 0)
    except (TypeError, ValueError):
        return
    scene = _scene_from_key(scene_id)
    if scene is None:
        return

    if bool(_job_field(job, "manual_request", False)):
        _resolve_trace(
            "Download finished with error "
            f"(manual={bool(_job_field(job, 'manual_request', False))}, request_id={_job_field(job, 'request_id')}, "
            f"error={str(error_message or '').strip() or 'unknown'})"
        )
        _mark_manual_queued_resolve_error(
            scene,
            f"Download failed: {str(error_message or '').strip() or 'Unknown error'}",
        )
        if error_message:
            logger.warning("Planetka manual resolve download failed: %s", error_message)
        return

    if _is_non_retryable_resolve_error(error_message):
        _resolve_trace(
            "Download finished with terminal error "
            f"(request_id={_job_field(job, 'request_id')}, error={str(error_message or '').strip() or 'unknown'})"
        )
        _mark_auto_resolve_terminal_failure(
            scene,
            scene_id,
            job,
            f"Download failed: {str(error_message or '').strip() or 'Unknown error'}",
        )
        if error_message:
            logger.warning("Planetka auto-resolve download terminal failure: %s", error_message)
        return

    scene_state = _read_scene_auto_resolve_state(scene_id)
    if scene_state is not None:
        scene_state.last_processed_signature = None
        scene_state.last_change_time = time.monotonic()
        _write_scene_auto_resolve_state(scene_state)
    request_auto_resolve(scene, immediate=False, mark_dirty=False)
    if error_message:
        logger.debug("Planetka auto-resolve download failed: %s", error_message)


def _auto_resolve_completion_epoch_state(job):
    try:
        job_epoch = int(_job_field(job, "epoch", -1))
    except (TypeError, ValueError):
        job_epoch = -1
    with _AUTO_RESOLVE_DOWNLOAD_LOCK:
        current_epoch = int(_AUTO_RESOLVE_DOWNLOAD_EPOCH)
        pending_job = _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB
    return (job_epoch == current_epoch), pending_job


def _auto_resolve_handle_cancel_or_failure(result, job, manual_request):
    if bool(result.get("cancelled", False)):
        _resolve_trace(
            f"Download finished cancelled (request_id={_job_field(job, 'request_id')}, manual={manual_request})"
        )
        return True

    if not bool(result.get("success", False)):
        _handle_auto_resolve_download_failure(job, str(result.get("error", "") or ""))
        return True

    return False


def _auto_resolve_log_pending_request_overlap(job, pending_job):
    # Never drop a completed download just because a newer request exists.
    # Finalize this resolve first; pending jobs will run immediately after.
    if _is_auto_resolve_download_job(pending_job):
        try:
            pending_request_id = int(_job_field(pending_job, "request_id", 0) or 0)
            job_request_id = int(_job_field(job, "request_id", 0) or 0)
            if pending_request_id > job_request_id:
                logger.debug(
                    "Planetka: finalizing completed resolve %d while newer request %d is pending.",
                    job_request_id,
                    pending_request_id,
                )
        except (TypeError, ValueError):
            pass


def _auto_resolve_prepare_apply_context(job, manual_request):
    scene_id = int(_job_field(job, "scene_id", 0) or 0)
    scene = _scene_from_key(scene_id)
    if scene is None:
        # Grace period: Blender can briefly lose scene context around file/load/UI transitions.
        # If context does not return quickly, consume/drop this completion to avoid a stuck pump loop.
        now = time.monotonic()
        try:
            missing_since = float(_job_field(job, "scene_missing_since", 0.0) or 0.0)
        except (TypeError, ValueError):
            missing_since = 0.0
        if missing_since <= 0.0:
            missing_since = now
        try:
            attempts = int(_job_field(job, "scene_missing_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        _job_set_field(job, "scene_missing_since", float(missing_since))
        _job_set_field(job, "scene_missing_attempts", int(max(1, attempts)))
        waited_sec = max(0.0, float(now) - float(missing_since))
        if waited_sec < float(_AUTO_RESOLVE_DOWNLOAD_SCENE_WAIT_SEC):
            _resolve_trace(
                "Download finished but scene context unavailable yet "
                f"(request_id={_job_field(job, 'request_id')}, waited={waited_sec:.2f}s, attempts={attempts}); waiting"
            )
            return False, None, None, None
        _resolve_trace(
            "Download completion dropped due stale missing scene context "
            f"(request_id={_job_field(job, 'request_id')}, waited={waited_sec:.2f}s, attempts={attempts})"
        )
        logger.debug(
            "Planetka: dropping completed auto-resolve payload because scene context did not return "
            "(request_id=%s, waited=%.2fs, attempts=%d).",
            str(_job_field(job, "request_id", "")),
            float(waited_sec),
            int(attempts),
        )
        return True, None, None, None
    _job_set_field(job, "scene_missing_since", 0.0)
    _job_set_field(job, "scene_missing_attempts", 0)
    job_target_tiles = _canonical_tiles(_job_field(job, "target_tiles", ()))

    if _is_render_job_active():
        if manual_request:
            _mark_manual_queued_resolve_error(scene, "Blocked by active render job.")
        else:
            request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return True, None, None, None

    props = getattr(scene, "planetka", None)
    if _is_animation_playing() and bool(getattr(props, "lock_resolve_during_animation", True)):
        if manual_request:
            _mark_manual_queued_resolve_error(scene, "Blocked by animation playback lock.")
        else:
            request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return True, None, None, None

    if manual_request:
        current_output_signature = _output_resolution_signature(scene)
        if current_output_signature != _job_field(job, "output_signature"):
            logger.warning("Planetka queued resolve continuing despite output signature change.")
    return True, scene, scene_id, job_target_tiles


def _auto_resolve_apply_downloaded_tiles(scene, scene_id, job, manual_request, job_target_tiles):
    global _AUTO_RESOLVE_IN_FLIGHT
    _AUTO_RESOLVE_IN_FLIGHT = True
    try:
        _resolve_trace(
            f"Shader update started (request_id={_job_field(job, 'request_id')}, manual={manual_request}, tiles={len(job_target_tiles)})"
        )
        op_kwargs = {
            "scope_mode": "CAMERA",
            "silent": True,
            "skip_render_compatibility": True,
            "defer_download": False,
            "tiles_override_json": json.dumps(list(job_target_tiles)),
            "texture_quality_mode_override": _normalize_texture_quality_mode(
                _job_field(job, "texture_quality_mode", "PREVIEW")
            ),
        }
        context_scene = getattr(bpy.context, "scene", None)
        if context_scene is scene or not hasattr(bpy.context, "temp_override"):
            op_result = bpy.ops.planetka.load_textures(**op_kwargs)
        else:
            with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
                op_result = bpy.ops.planetka.load_textures(**op_kwargs)
        if "FINISHED" not in op_result:
            _resolve_trace(
                f"Shader update failed (request_id={_job_field(job, 'request_id')} op_result={str(op_result)})"
            )
            scene_error = _read_scene_last_resolve_error(scene)
            apply_error = scene_error or f"Apply operator returned {str(op_result)} for {len(job_target_tiles)} tile(s)."
            logger.warning(
                "Planetka queued resolve apply returned %s for %d tile(s).",
                str(op_result),
                len(job_target_tiles),
            )
            if manual_request:
                _mark_manual_queued_resolve_error(
                    scene,
                    apply_error,
                )
            else:
                if _is_non_retryable_resolve_error(apply_error):
                    _mark_auto_resolve_terminal_failure(scene, scene_id, job, apply_error)
                else:
                    request_auto_resolve(scene, immediate=False, mark_dirty=False)
            return False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _resolve_trace(
            f"Shader update failed with recoverable exception (request_id={_job_field(job, 'request_id')})"
        )
        logger.debug("Planetka auto-resolve apply failed", exc_info=True)
        scene_error = _read_scene_last_resolve_error(scene)
        apply_error = scene_error or "Apply failed with recoverable exception."
        if manual_request:
            _mark_manual_queued_resolve_error(scene, apply_error)
        else:
            if _is_non_retryable_resolve_error(apply_error):
                _mark_auto_resolve_terminal_failure(scene, scene_id, job, apply_error)
            else:
                request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        _resolve_trace(
            f"Shader update failed with unexpected exception (request_id={_job_field(job, 'request_id')})"
        )
        logger.debug("Planetka auto-resolve apply failed unexpectedly", exc_info=True)
        scene_error = _read_scene_last_resolve_error(scene)
        apply_error = scene_error or "Apply failed with unexpected exception."
        if manual_request:
            _mark_manual_queued_resolve_error(scene, apply_error)
        else:
            if _is_non_retryable_resolve_error(apply_error):
                _mark_auto_resolve_terminal_failure(scene, scene_id, job, apply_error)
            else:
                request_auto_resolve(scene, immediate=False, mark_dirty=False)
        return False
    finally:
        _AUTO_RESOLVE_IN_FLIGHT = False
    return True


def _auto_resolve_summary_total_bytes(job_target_tiles, job, result):
    summary_total_bytes = 0
    try:
        summary_total_bytes = int(
            max(
                0,
                int(
                        _estimate_download_bytes_for_visible_tiles(
                            job_target_tiles,
                        str(_job_field(job, "base_path", "") or ""),
                        texture_quality_mode=_normalize_texture_quality_mode(
                            _job_field(job, "texture_quality_mode", "PREVIEW")
                        ),
                    )
                    or 0
                ),
            )
        )
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
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


def _finalize_auto_resolve_apply(scene, scene_id, job, manual_request, job_target_tiles, resolved_at, summary_total_bytes):
    try:
        created_at = float(_job_field(job, "created_at", resolved_at) or resolved_at)
    except (TypeError, ValueError):
        created_at = resolved_at
    total_seconds = max(0.0, float(resolved_at) - float(created_at))
    _write_last_resolve_summary(scene, len(job_target_tiles), summary_total_bytes, total_seconds)

    scene_id = _scene_key(scene)
    latest_signature = _camera_signature(scene) or _job_field(job, "camera_signature")
    scene_state = _read_scene_auto_resolve_state(scene_id)
    if scene_state is not None:
        scene_state.last_resolve_time = resolved_at
        scene_state.last_change_time = resolved_at
        scene_state.last_camera_signature = latest_signature
        scene_state.last_processed_signature = latest_signature
        scene_state.pending_output_change = False
        _write_scene_auto_resolve_state(scene_state)
    _VIEWPORT_SCOPE_LAST_RESOLVE_TIME[scene_id] = resolved_at
    try:
        if "planetka_last_resolve_error" in scene:
            del scene["planetka_last_resolve_error"]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed clearing queued resolve error marker", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed clearing queued resolve error marker", exc_info=True)
    if manual_request:
        logger.warning(
            "Planetka queued resolve applied successfully (%d tile(s)).",
            len(job_target_tiles),
        )
    else:
        # Auto-resolve should always finalize once download completes.
        # If the camera/output changed while downloading, queue another pass after this apply.
        latest_camera_signature = _camera_signature(scene)
        latest_output_signature = _output_resolution_signature(scene)
        if (
            latest_camera_signature != _job_field(job, "camera_signature")
            or latest_output_signature != _job_field(job, "output_signature")
        ):
            request_auto_resolve(scene, immediate=False, mark_dirty=True)
    _resolve_trace(
        f"Shader update finished (request_id={_job_field(job, 'request_id')}, tiles={len(job_target_tiles)})"
    )


def _handle_auto_resolve_download_complete(result):
    if not isinstance(result, dict):
        return True
    job = result.get("job")
    if not _is_auto_resolve_download_job(job):
        return True
    manual_request = bool(_job_field(job, "manual_request", False))

    epoch_matches, pending_job = _auto_resolve_completion_epoch_state(job)
    if not epoch_matches:
        return True

    if _auto_resolve_handle_cancel_or_failure(result, job, manual_request):
        return True

    _auto_resolve_log_pending_request_overlap(job, pending_job)

    consume, scene, scene_id, job_target_tiles = _auto_resolve_prepare_apply_context(job, manual_request)
    if not consume:
        return False
    if scene is None:
        return True

    if not _auto_resolve_apply_downloaded_tiles(scene, scene_id, job, manual_request, job_target_tiles):
        return True

    resolved_at = time.monotonic()
    summary_total_bytes = _auto_resolve_summary_total_bytes(job_target_tiles, job, result)
    _finalize_auto_resolve_apply(
        scene,
        scene_id,
        job,
        manual_request,
        job_target_tiles,
        resolved_at,
        summary_total_bytes,
    )
    return True


def _auto_resolve_download_worker(job):
    global _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB
    global _AUTO_RESOLVE_DOWNLOAD_COMPLETED
    global _AUTO_RESOLVE_DOWNLOAD_THREAD

    result = {
        "job": job,
        "success": False,
        "cancelled": False,
        "error": "",
        "download_capture": {},
    }

    try:
        _resolve_trace(
            "Download started "
            f"(request_id={_job_field(job, 'request_id')}, manual={bool(_job_field(job, 'manual_request', False))}, "
            f"tiles={len(tuple(_job_field(job, 'target_tiles', ())))})"
        )
        module_name = f"{__package__}.streaming_utils" if __package__ else "streaming_utils"
        streaming_module = importlib.import_module(module_name)
        prepare_fn = getattr(streaming_module, "prepare_resolve_streaming_for_visible_tiles", None)
        stage_fn = getattr(streaming_module, "stage_prefetch_payload", None)
        if not callable(prepare_fn):
            raise RuntimeError("Planetka streaming pipeline is unavailable.")

        prepared_payload = prepare_fn(
            tuple(_job_field(job, "target_tiles", ())),
            str(_job_field(job, "base_path", "") or ""),
            cancel_event=_job_field(job, "cancel_event"),
            capture=True,
            texture_quality_mode=_normalize_texture_quality_mode(_job_field(job, "texture_quality_mode", "PREVIEW")),
            nav_latitude_deg=_job_field(job, "nav_latitude_deg", ""),
            nav_longitude_deg=_job_field(job, "nav_longitude_deg", ""),
            nav_altitude_km=_job_field(job, "nav_altitude_km", ""),
        )
        cancelled = (
            bool(prepared_payload.get("cancelled", False))
            if isinstance(prepared_payload, dict)
            else False
        )
        if not cancelled and isinstance(prepared_payload, dict) and callable(stage_fn):
            stage_fn(
                tuple(_job_field(job, "target_tiles", ()) or ()),
                str(_job_field(job, "base_path", "") or ""),
                prepared_payload,
                texture_quality_mode=_normalize_texture_quality_mode(_job_field(job, "texture_quality_mode", "PREVIEW")),
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
        _resolve_trace(
            "Download finished "
            f"(request_id={_job_field(job, 'request_id')}, cancelled={cancelled}, downloaded={downloaded_bytes}, total={total_bytes})"
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        result["error"] = str(exc)
        _resolve_trace(
            f"Download failed with recoverable exception (request_id={_job_field(job, 'request_id')}, error={str(exc)})"
        )
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
        result["error"] = str(exc)
        _resolve_trace(
            f"Download failed with unexpected exception (request_id={_job_field(job, 'request_id')}, error={str(exc)})"
        )
    finally:
        result["completed_at"] = float(time.monotonic())
        with _AUTO_RESOLVE_DOWNLOAD_LOCK:
            if _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB is job:
                _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB = None
            _AUTO_RESOLVE_DOWNLOAD_THREAD = None
            job_epoch = int(_job_field(job, "epoch", -1))
            current_epoch = int(_AUTO_RESOLVE_DOWNLOAD_EPOCH)
            store_completed = (job_epoch == current_epoch)
            if store_completed:
                _AUTO_RESOLVE_DOWNLOAD_COMPLETED = result
            _resolve_trace(
                f"Worker finalize (request_id={_job_field(job, 'request_id')}, job_epoch={job_epoch}, "
                f"current_epoch={current_epoch}, store_completed={store_completed})"
            )


def _auto_resolve_download_pump_timer():
    global _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING
    global _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB
    global _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB
    global _AUTO_RESOLVE_DOWNLOAD_COMPLETED

    try:
        _resolve_trace("Pump tick")
        if not hasattr(bpy.types.Scene, "planetka"):
            _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = False
            _resolve_trace("Pump stop: Scene.planetka missing")
            return None

        completed = None
        with _AUTO_RESOLVE_DOWNLOAD_LOCK:
            if isinstance(_AUTO_RESOLVE_DOWNLOAD_COMPLETED, dict):
                completed = _AUTO_RESOLVE_DOWNLOAD_COMPLETED

        if isinstance(completed, dict):
            completed_job = completed.get("job") if isinstance(completed, dict) else None
            completed_request_id = _job_field(completed_job, "request_id")
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
            if completed_age >= float(_AUTO_RESOLVE_DOWNLOAD_COMPLETED_MAX_AGE_SEC):
                _resolve_trace(
                    "Pump dropped stale completed download payload "
                    f"(request_id={completed_request_id}, age={completed_age:.2f}s)"
                )
                with _AUTO_RESOLVE_DOWNLOAD_LOCK:
                    if _AUTO_RESOLVE_DOWNLOAD_COMPLETED is completed:
                        _AUTO_RESOLVE_DOWNLOAD_COMPLETED = None
                completed = None
            else:
                _resolve_trace(
                    f"Pump received completed download (request_id={completed_request_id}, age={completed_age:.2f}s)"
                )
                consume_completed = bool(_handle_auto_resolve_download_complete(completed))
                if consume_completed:
                    with _AUTO_RESOLVE_DOWNLOAD_LOCK:
                        if _AUTO_RESOLVE_DOWNLOAD_COMPLETED is completed:
                            _AUTO_RESOLVE_DOWNLOAD_COMPLETED = None

        job_to_start = None
        with _AUTO_RESOLVE_DOWNLOAD_LOCK:
            if _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB is None and _is_auto_resolve_download_job(_AUTO_RESOLVE_DOWNLOAD_PENDING_JOB):
                _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB = _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB
                _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB = None
                job_to_start = _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB

            has_active = _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB is not None
            has_pending = _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB is not None
            has_completed = _AUTO_RESOLVE_DOWNLOAD_COMPLETED is not None

        if _is_auto_resolve_download_job(job_to_start):
            _start_auto_resolve_download_thread(job_to_start)
            has_active = True

        scene = getattr(bpy.context, "scene", None)
        if scene is not None:
            _update_realtime_telemetry(scene)
            _tag_view3d_redraw()

        if not has_active and not has_pending and not has_completed:
            _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = False
            _resolve_trace("Pump stop: no active/pending/completed jobs")
            return None

        _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = True
        return _AUTO_RESOLVE_DOWNLOAD_PUMP_INTERVAL_SEC
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _resolve_trace("Pump failed with recoverable exception")
        logger.debug("Planetka auto-resolve download timer failed", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        _resolve_trace("Pump failed with unexpected exception")
        logger.debug("Planetka auto-resolve download timer failed unexpectedly", exc_info=True)

    _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = False
    return None


def stop_auto_resolve_download_pipeline():
    global _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING
    global _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB
    global _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB
    global _AUTO_RESOLVE_DOWNLOAD_COMPLETED
    global _AUTO_RESOLVE_DOWNLOAD_EPOCH

    with _AUTO_RESOLVE_DOWNLOAD_LOCK:
        _AUTO_RESOLVE_DOWNLOAD_EPOCH = int(_AUTO_RESOLVE_DOWNLOAD_EPOCH) + 1
        _resolve_trace(f"Pipeline stop called; epoch advanced to {_AUTO_RESOLVE_DOWNLOAD_EPOCH}")

        active_job = _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB
        if _is_auto_resolve_download_job(active_job):
            cancel_event = _job_field(active_job, "cancel_event")
            if cancel_event is not None:
                try:
                    cancel_event.set()
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("[PKA-STATE-001] Planetka: failed signaling resolve cancel event", exc_info=True)

        _AUTO_RESOLVE_DOWNLOAD_ACTIVE_JOB = None
        _AUTO_RESOLVE_DOWNLOAD_PENDING_JOB = None
        _AUTO_RESOLVE_DOWNLOAD_COMPLETED = None

    try:
        if bpy.app.timers.is_registered(_auto_resolve_download_pump_timer):
            bpy.app.timers.unregister(_auto_resolve_download_pump_timer)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed stopping auto-resolve download timer", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed stopping auto-resolve download timer", exc_info=True)

    _AUTO_RESOLVE_DOWNLOAD_TIMER_RUNNING = False


def request_auto_resolve(scene, immediate=False, mark_dirty=True):
    global _AUTO_RESOLVE_TIMER_RUNNING
    if not _can_auto_resolve_run(scene):
        _AUTO_RESOLVE_NEXT_DUE_TIME.clear()
        _AUTO_RESOLVE_TIMER_RUNNING = False
        try:
            if bpy.app.timers.is_registered(_auto_resolve_timer):
                bpy.app.timers.unregister(_auto_resolve_timer)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed stopping auto-resolve timer", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed stopping auto-resolve timer", exc_info=True)
        return
    if scene is None:
        return

    if _auto_resolve_scope_mode(scene) == "NONE":
        return

    if mark_dirty:
        _mark_auto_resolve_dirty(scene, immediate=bool(immediate))

    scene_state = _read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return
    now = time.monotonic()
    delay_sec = 0.0 if immediate else _auto_resolve_idle_seconds(scene)
    scene_state.next_due_time = now + delay_sec
    _write_scene_auto_resolve_state(scene_state)
    _arm_auto_resolve_timer(force_immediate=bool(immediate))


def _can_auto_resolve_run(scene):
    if scene is None:
        return False
    props = getattr(scene, "planetka", None)
    if props is None:
        return False
    if not bool(getattr(props, "auto_resolve", False)):
        return False
    if get_earth_object() is None:
        return False
    return True


def update_auto_resolve(self, context):
    scene = getattr(context, "scene", None) if context else None
    if scene:
        _sync_idprops_from_props(
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
            _force_restore_navigation_adaptive_state()
        _mark_auto_resolve_dirty(scene, immediate=True, force_resolve=True)
    if _can_auto_resolve_run(scene):
        request_auto_resolve(scene, immediate=True, mark_dirty=False)
    else:
        stop_auto_resolve_service()


def _auto_resolve_collect_scope_signatures(scene, scope_mode):
    scope = str(scope_mode or "NONE")
    active_view_signature = None
    if scope == "ACTIVE_VIEW":
        active_view_signature = _active_view_signature()
    camera_signature = _camera_signature(scene)
    resolve_signature = (
        ("ACTIVE_VIEW", active_view_signature)
        if active_view_signature is not None
        else camera_signature
    )
    return scope, active_view_signature, resolve_signature


def _auto_resolve_sync_state_signatures(scene_state, resolve_signature, output_signature, now_monotonic):
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
        _write_scene_auto_resolve_state(scene_state)
    return bool(scene_state.pending_output_change)


def _auto_resolve_update_size_estimation(scene, scope, active_view_signature, target_tiles, props):
    estimation_scope = "ACTIVE_VIEW" if (scope == "ACTIVE_VIEW" and active_view_signature is not None) else "CAMERA"
    base_path_for_estimate = ""
    try:
        prefs = get_prefs()
        if prefs is not None:
            base_path_for_estimate = str(getattr(prefs, "texture_base_path", "") or "")
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        base_path_for_estimate = ""

    current_quality_mode = _normalize_texture_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW"))
    full_tiles_override = target_tiles if current_quality_mode == "FULL" else None
    try:
        update_resolve_size_estimates(
            scene,
            scope_mode=estimation_scope,
            base_path=base_path_for_estimate,
            full_tiles_override=full_tiles_override,
        )
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka auto-resolve: failed updating resolve size estimates", exc_info=True)


def _arm_auto_resolve_noncritical_timer():
    global _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING
    try:
        if bpy.app.timers.is_registered(_auto_resolve_noncritical_timer):
            _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = True
            return
        bpy.app.timers.register(
            _auto_resolve_noncritical_timer,
            first_interval=max(0.05, float(_AUTO_RESOLVE_NONCRITICAL_INTERVAL_SEC)),
            persistent=True,
        )
        _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed arming non-critical auto-resolve timer", exc_info=True)
        _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka: failed arming non-critical auto-resolve timer", exc_info=True)
        _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False


def _auto_resolve_enqueue_size_estimation(scene, scope, active_view_signature, target_tiles, props):
    if scene is None or props is None:
        return
    try:
        scene_id = _scene_key(scene)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return
    current_quality_mode = _normalize_texture_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW"))
    safe_scope = str(scope or "CAMERA")
    safe_active_signature = active_view_signature if safe_scope == "ACTIVE_VIEW" else None
    safe_tiles = tuple(target_tiles or ())
    request_signature = (safe_scope, safe_active_signature, current_quality_mode, safe_tiles)
    if _AUTO_RESOLVE_SIZE_ESTIMATE_LAST_SIGNATURE.get(scene_id) == request_signature:
        return
    _AUTO_RESOLVE_SIZE_ESTIMATE_LAST_SIGNATURE[scene_id] = request_signature
    _AUTO_RESOLVE_NONCRITICAL_PENDING[scene_id] = {
        "scope": safe_scope,
        "active_view_signature": safe_active_signature,
        "target_tiles": safe_tiles,
    }
    _arm_auto_resolve_noncritical_timer()


def _auto_resolve_noncritical_timer():
    global _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING
    try:
        if not hasattr(bpy.types.Scene, "planetka"):
            _AUTO_RESOLVE_NONCRITICAL_PENDING.clear()
            _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
            return None
        if not _AUTO_RESOLVE_NONCRITICAL_PENDING:
            _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
            return None

        scene = getattr(bpy.context, "scene", None)
        scene_id = _scene_key(scene) if scene is not None else None
        request = None
        if scene_id is not None:
            request = _AUTO_RESOLVE_NONCRITICAL_PENDING.pop(scene_id, None)

        if request is None:
            pending_scene_id, request = next(iter(_AUTO_RESOLVE_NONCRITICAL_PENDING.items()))
            _AUTO_RESOLVE_NONCRITICAL_PENDING.pop(pending_scene_id, None)
            scene = _scene_from_key(pending_scene_id)

        if scene is not None and request:
            props = getattr(scene, "planetka", None)
            if props is not None:
                _auto_resolve_update_size_estimation(
                    scene,
                    request.get("scope"),
                    request.get("active_view_signature"),
                    request.get("target_tiles"),
                    props,
                )

        if _AUTO_RESOLVE_NONCRITICAL_PENDING:
            return max(0.05, float(_AUTO_RESOLVE_NONCRITICAL_INTERVAL_SEC))
        _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
        return None
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka non-critical auto-resolve timer tick failed", exc_info=True)
        _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka non-critical auto-resolve timer tick failed unexpectedly", exc_info=True)
        _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
    return None


def _auto_resolve_detect_change(scene, props):
    if scene is None:
        return {"event": "STOP", "retry_delay": None}
    if props is None or not bool(getattr(props, "auto_resolve", False)):
        return {"event": "STOP", "retry_delay": None}

    scope_mode = _auto_resolve_scope_mode(scene)
    if scope_mode == "NONE":
        return {"event": "STOP", "retry_delay": None}

    if _is_animation_playing() and bool(getattr(props, "lock_resolve_during_animation", True)):
        return {"event": "RETRY", "retry_delay": AUTO_RESOLVE_RETRY_DELAY_SEC}
    if _is_render_job_active():
        return {"event": "RETRY", "retry_delay": AUTO_RESOLVE_RETRY_DELAY_SEC}
    if get_earth_object() is None:
        return {"event": "STOP", "retry_delay": None}

    scope, active_view_signature, resolve_signature = _auto_resolve_collect_scope_signatures(scene, scope_mode)
    if resolve_signature is None:
        return {"event": "RETRY", "retry_delay": AUTO_RESOLVE_RETRY_DELAY_SEC}

    altitude_info = _resolve_scope_altitude_info(scene, scope_mode=scope)
    if bool(altitude_info.get("inside_earth", False)):
        _set_camera_inside_earth_warning(scene, altitude_info.get("altitude_km"))
        stop_auto_resolve_download_pipeline()
        return {"event": "STOP", "retry_delay": None}
    _clear_camera_inside_earth_warning(scene)

    scene_state = _read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return {"event": "STOP", "retry_delay": None}

    now = time.monotonic()
    output_signature = _output_resolution_signature(scene)
    pending_output_change = _auto_resolve_sync_state_signatures(
        scene_state,
        resolve_signature,
        output_signature,
        now,
    )

    min_interval_sec = AUTO_RESOLVE_MIN_INTERVAL_SEC_DEFAULT
    last_resolve = float(scene_state.last_resolve_time or 0.0)
    if now - last_resolve < min_interval_sec:
        return {
            "event": "RETRY",
            "retry_delay": max(0.05, min_interval_sec - (now - last_resolve)),
            "scene_state": scene_state,
        }

    if scene_state.last_processed_signature == resolve_signature and not pending_output_change:
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
        "now": now,
    }


def _auto_resolve_plan_job(scene, props, detect_ctx):
    if scene is None:
        return {"event": "STOP", "retry_delay": None}
    if not isinstance(detect_ctx, dict):
        return {"event": "STOP", "retry_delay": None}
    if str(detect_ctx.get("event", "")) != "PLAN":
        return {
            "event": str(detect_ctx.get("event", "STOP") or "STOP"),
            "retry_delay": detect_ctx.get("retry_delay", None),
        }

    tile_utils = _get_tile_utils()
    if tile_utils is None:
        return {"event": "STOP", "retry_delay": None}

    scope = str(detect_ctx.get("scope", "CAMERA") or "CAMERA")
    active_view_signature = detect_ctx.get("active_view_signature")
    try:
        target_tiles = _canonical_tiles(
            tile_utils.main(
                scope_mode="ACTIVE_VIEW" if (scope == "ACTIVE_VIEW" and active_view_signature is not None) else "CAMERA",
            )
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka auto-resolve: tile computation failed", exc_info=True)
        return {"event": "RETRY", "retry_delay": AUTO_RESOLVE_RETRY_DELAY_SEC}
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka auto-resolve: unexpected tile computation failure", exc_info=True)
        return {"event": "RETRY", "retry_delay": AUTO_RESOLVE_RETRY_DELAY_SEC}

    _auto_resolve_enqueue_size_estimation(scene, scope, active_view_signature, target_tiles, props)

    if target_tiles == _last_resolved_tiles(scene) and not bool(detect_ctx.get("pending_output_change", False)):
        return {"event": "NO_CHANGE", "target_tiles": target_tiles, "retry_delay": None}

    return {"event": "DISPATCH", "target_tiles": target_tiles, "retry_delay": None}


def _auto_resolve_dispatch_job(scene, detect_ctx, plan_ctx):
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
        _write_scene_auto_resolve_state(scene_state)
        return {"event": "NO_CHANGE", "retry_delay": None}

    if plan_event != "DISPATCH":
        return {"event": plan_event, "retry_delay": plan_ctx.get("retry_delay", None)}

    target_tiles = tuple(plan_ctx.get("target_tiles", ()) or ())
    output_signature = _output_resolution_signature(scene)
    queued = _schedule_auto_resolve_download(
        scene,
        target_tiles,
        detect_ctx.get("resolve_signature"),
        output_signature,
    )
    if not queued:
        return {"event": "RETRY", "retry_delay": AUTO_RESOLVE_RETRY_DELAY_SEC}

    scene_state.last_change_time = time.monotonic()
    _write_scene_auto_resolve_state(scene_state)
    return {"event": "DISPATCH", "retry_delay": None}


def _auto_resolve_tick_once():
    global _AUTO_RESOLVE_IN_FLIGHT

    if _AUTO_RESOLVE_IN_FLIGHT:
        return 0.1

    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)

    detect_ctx = _auto_resolve_detect_change(scene, props)
    detect_event = str(detect_ctx.get("event", "STOP") or "STOP")
    if detect_event == "STOP":
        return None
    if detect_event == "RETRY":
        return float(detect_ctx.get("retry_delay", AUTO_RESOLVE_RETRY_DELAY_SEC) or AUTO_RESOLVE_RETRY_DELAY_SEC)
    if detect_event == "NO_CHANGE":
        return None

    plan_ctx = _auto_resolve_plan_job(scene, props, detect_ctx)
    plan_event = str(plan_ctx.get("event", "STOP") or "STOP")
    if plan_event == "STOP":
        return None
    if plan_event == "RETRY":
        return float(plan_ctx.get("retry_delay", AUTO_RESOLVE_RETRY_DELAY_SEC) or AUTO_RESOLVE_RETRY_DELAY_SEC)
    if plan_event == "NO_CHANGE":
        return None

    dispatch_ctx = _auto_resolve_dispatch_job(scene, detect_ctx, plan_ctx)
    dispatch_event = str(dispatch_ctx.get("event", "STOP") or "STOP")
    if dispatch_event == "RETRY":
        return float(dispatch_ctx.get("retry_delay", AUTO_RESOLVE_RETRY_DELAY_SEC) or AUTO_RESOLVE_RETRY_DELAY_SEC)
    return None


def _auto_resolve_timer():
    global _AUTO_RESOLVE_TIMER_RUNNING
    try:
        if not hasattr(bpy.types.Scene, "planetka"):
            _AUTO_RESOLVE_TIMER_RUNNING = False
            return None

        scene = getattr(bpy.context, "scene", None)
        if scene is None:
            _AUTO_RESOLVE_TIMER_RUNNING = False
            return None

        scene_state = _read_scene_auto_resolve_state(scene)
        if scene_state is None:
            _AUTO_RESOLVE_TIMER_RUNNING = False
            return None
        monitor_interval = max(0.05, _active_view_monitor_interval_seconds(scene))
        due_time = scene_state.next_due_time
        if due_time is None:
            scene_state.next_due_time = time.monotonic()
            _write_scene_auto_resolve_state(scene_state)
            due_time = scene_state.next_due_time

        if not _can_auto_resolve_run(scene):
            scene_state.next_due_time = None
            _write_scene_auto_resolve_state(scene_state)
            _AUTO_RESOLVE_TIMER_RUNNING = False
            return None

        now = time.monotonic()
        remaining = float(due_time) - now
        if remaining > 0.0:
            return max(0.05, min(remaining, 1.0))

        _update_realtime_telemetry(scene)
        camera_signature = _camera_signature(scene)
        _handle_timeline_motion_optimization(scene)
        _handle_viewport_motion_optimization(scene, camera_signature)
        _handle_sunlight_motion_optimization(scene)
        _handle_view_scope_quality_transition(scene)
        retry_delay = _auto_resolve_tick_once()
        if retry_delay is not None:
            scene_state.next_due_time = time.monotonic() + max(0.05, float(retry_delay))
            _write_scene_auto_resolve_state(scene_state)
            return max(0.05, float(retry_delay))

        scene_state.next_due_time = time.monotonic() + monitor_interval
        _write_scene_auto_resolve_state(scene_state)
        return monitor_interval
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka auto-resolve timer tick failed", exc_info=True)
        _AUTO_RESOLVE_TIMER_RUNNING = False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka auto-resolve timer tick failed unexpectedly", exc_info=True)
        _AUTO_RESOLVE_TIMER_RUNNING = False
    return None


def ensure_auto_resolve_service_running():
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    if not _can_auto_resolve_run(scene):
        stop_auto_resolve_service()
        return
    if scene is None:
        return
    scene_state = _read_scene_auto_resolve_state(scene)
    if scene_state is None:
        return
    if scene_state.next_due_time is None:
        scene_state.next_due_time = time.monotonic() + max(0.05, _active_view_monitor_interval_seconds(scene))
        _write_scene_auto_resolve_state(scene_state)
    _arm_auto_resolve_timer(force_immediate=False)


def stop_auto_resolve_service():
    global _AUTO_RESOLVE_TIMER_RUNNING
    global _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING
    try:
        if bpy.app.timers.is_registered(_auto_resolve_timer):
            bpy.app.timers.unregister(_auto_resolve_timer)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed stopping auto-resolve timer", exc_info=True)
    try:
        if bpy.app.timers.is_registered(_auto_resolve_noncritical_timer):
            bpy.app.timers.unregister(_auto_resolve_noncritical_timer)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed stopping non-critical auto-resolve timer", exc_info=True)
    _AUTO_RESOLVE_TIMER_RUNNING = False
    _AUTO_RESOLVE_NONCRITICAL_TIMER_RUNNING = False
    stop_auto_resolve_download_pipeline()
    _AUTO_RESOLVE_NEXT_DUE_TIME.clear()
    _AUTO_RESOLVE_LAST_CAMERA_SIGNATURE.clear()
    _AUTO_RESOLVE_LAST_OUTPUT_SIGNATURE.clear()
    _AUTO_RESOLVE_LAST_CHANGE_TIME.clear()
    _AUTO_RESOLVE_LAST_RESOLVE_TIME.clear()
    _AUTO_RESOLVE_LAST_PROCESSED_SIGNATURE.clear()
    _AUTO_RESOLVE_PENDING_OUTPUT_CHANGE.clear()
    _AUTO_RESOLVE_TRIGGER_LAST_SIGNATURE.clear()
    _VIEWPORT_OPT_LAST_SIGNATURE.clear()
    _SUNLIGHT_LAST_SIGNATURE.clear()
    _VIEWPORT_SCOPE_LAST.clear()
    _VIEWPORT_SCOPE_LAST_RESOLVE_TIME.clear()
    _LAST_REALTIME_TELEMETRY.clear()
    _TIMELINE_LAST_SIGNATURE.clear()
    _FRAME_KEYED_RUNTIME_LAST_SIGNATURE.clear()
    _NAV_CAMERA_CONTROL_LAST_SIGNATURE.clear()
    _SUNLIGHT_OBJECT_NAME_CACHE.clear()
    _AUTO_RESOLVE_NONCRITICAL_PENDING.clear()
    _AUTO_RESOLVE_SIZE_ESTIMATE_LAST_SIGNATURE.clear()


