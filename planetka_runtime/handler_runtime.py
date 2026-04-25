_MOVED_NAMES = {
    "recover_post_render_state",
    "mark_render_job_started",
    "_sync_logging_from_scenes",
    "migrate_scene",
    "_initialize_props_from_imported_planetka",
    "_planetka_depsgraph_update_post",
    "_planetka_frame_change_post",
    "_planetka_load_post",
}


def configure(runtime):
    module_globals = globals()
    for key, value in runtime.items():
        if key in _MOVED_NAMES:
            continue
        module_globals[key] = value


def recover_post_render_state(scene=None, cancelled=False):
    global _AUTO_RESOLVE_IN_FLIGHT
    global _RENDER_JOB_ACTIVE
    global _RENDER_JOB_LAST_ENDED_EPOCH
    global _RENDER_JOB_LAST_CANCELLED_EPOCH

    _AUTO_RESOLVE_IN_FLIGHT = False
    _RENDER_JOB_ACTIVE = False
    _RENDER_JOB_LAST_ENDED_EPOCH = int(_RENDER_JOB_EPOCH)
    if bool(cancelled):
        _RENDER_JOB_LAST_CANCELLED_EPOCH = int(_RENDER_JOB_EPOCH)
    reset_navigation_shot_runtime_state = globals().get("_reset_navigation_shot_runtime_state")
    if callable(reset_navigation_shot_runtime_state):
        reset_navigation_shot_runtime_state()
    reset_navigation_camera_control_runtime_state = globals().get("_reset_navigation_camera_control_runtime_state")
    if callable(reset_navigation_camera_control_runtime_state):
        reset_navigation_camera_control_runtime_state()
    _force_restore_navigation_adaptive_state()

    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        _mark_auto_resolve_dirty(scene, immediate=True)
        request_auto_resolve(scene, immediate=True, mark_dirty=False)


def mark_render_job_started():
    global _RENDER_JOB_ACTIVE
    global _RENDER_JOB_EPOCH
    if _RENDER_JOB_ACTIVE:
        # Blender calls render_pre per frame during animation renders.
        # Treat the whole animation as one render job to avoid per-frame
        # self-heal churn and epoch flips during segment rendering.
        return int(_RENDER_JOB_EPOCH)
    try:
        self_heal_missing_cache_images_for_render(getattr(getattr(bpy, "context", None), "scene", None))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Planetka: render self-heal preflight failed", exc_info=True)
    _RENDER_JOB_EPOCH = int(_RENDER_JOB_EPOCH) + 1
    _RENDER_JOB_ACTIVE = True
    return int(_RENDER_JOB_EPOCH)


def _sync_logging_from_scenes():
    global _LOGGING_SYNCING
    if _LOGGING_SYNCING:
        return
    _LOGGING_SYNCING = True
    try:
        enabled = False
        for scene in _iter_scenes():
            props = getattr(scene, "planetka", None)
            if props and bool(getattr(props, "debug_logging", False)):
                enabled = True
                break
        set_planetka_logging(enabled)
    finally:
        _LOGGING_SYNCING = False


def migrate_scene(scene):
    migrate_scene_schema(scene, sync_idprops_fn=_sync_idprops_from_props, logger=logger)
    for key in _LEGACY_SCENE_IDPROPS:
        try:
            if key in scene:
                del scene[key]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing legacy scene idprop %s", key, exc_info=True)


def _initialize_props_from_imported_planetka(scene):
    props = getattr(scene, "planetka", None) if scene else None
    if not props:
        return

    try:
        # Atmosphere/cloud runtime features are disabled in this release.
        scene["planetka_atmosphere_enabled"] = False
        scene["planetka_enable_global_clouds"] = False
        scene["planetka_enable_local_clouds"] = False
        scene["planetka_enable_vdb_clouds"] = False
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed forcing atmosphere/cloud scene idprops off", exc_info=True)

    _sync_idprops_from_props(scene)


def _planetka_depsgraph_update_post(_scene, _depsgraph):
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    if scene is None:
        return

    if _is_navigation_user_edit_active(scene):
        return

    keyed_runtime_active = _scene_has_keyed_runtime_path(scene, _KEYED_RUNTIME_ALL_PROP_PATHS)
    props = getattr(scene, "planetka", None)
    preset_active = False
    if props is not None:
        try:
            preset_token = str(getattr(props, "anim_camera_preset", "NONE") or "NONE").strip().upper()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            preset_token = "NONE"
        if preset_token in {"PUSH_IN", "PULL_BACK"}:
            preset_token = "ZOOM"
        elif preset_token in {"ARC_LEFT", "ARC_RIGHT"}:
            preset_token = "ARC"
        elif preset_token == "FLYBY":
            preset_token = "NONE"
        preset_active = preset_token not in {"", "NONE"}
    if not (_is_render_job_active() or _is_animation_playing() or keyed_runtime_active or preset_active):
        _sync_navigation_controls_from_scene_camera(scene)

    if not _can_auto_resolve_run(scene):
        return

    ensure_auto_resolve_service_running()
    _update_realtime_telemetry(scene)

    if _is_resolve_pipeline_busy():
        return

    trigger_signature = _make_depsgraph_trigger_signature(scene)
    _handle_timeline_motion_optimization(scene)
    _handle_viewport_motion_optimization(
        scene,
        _camera_signature(scene),
    )
    _handle_sunlight_motion_optimization(scene)
    _mark_auto_resolve_from_depsgraph_trigger(scene, trigger_signature)


def _planetka_frame_change_post(scene, _depsgraph=None):
    global _NAVIGATION_USER_EDIT_LAST_TOUCH
    target_scene = scene
    if target_scene is None:
        target_scene = getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return

    signature = _keyed_runtime_signature(target_scene)
    scene_id = _scene_key(target_scene)
    if signature is None:
        _FRAME_KEYED_RUNTIME_LAST_SIGNATURE.pop(scene_id, None)
        return

    previous = _FRAME_KEYED_RUNTIME_LAST_SIGNATURE.get(scene_id)
    if previous == signature:
        return
    _FRAME_KEYED_RUNTIME_LAST_SIGNATURE[scene_id] = signature

    nav_keyed = _scene_has_keyed_runtime_path(target_scene, _KEYED_RUNTIME_NAV_PROP_PATHS)
    focal_keyed = _scene_has_keyed_runtime_path(target_scene, _KEYED_RUNTIME_FOCAL_PROP_PATHS)
    sun_keyed = _scene_has_keyed_runtime_path(target_scene, _KEYED_RUNTIME_SUN_PROP_PATHS)
    if not (nav_keyed or focal_keyed or sun_keyed):
        return
    return


def _planetka_load_post(_dummy):
    _FRAME_KEYED_RUNTIME_LAST_SIGNATURE.clear()
    _sync_logging_from_scenes()
    missing_cache_images, recovered_cache_images = _recover_missing_cache_image_paths_to_fallback()
    if int(missing_cache_images) > 0:
        logger.warning(
            "Planetka: detected %d missing cached tile image(s) on file load; redirected %d to fallback placeholders.",
            int(missing_cache_images),
            int(recovered_cache_images),
        )
        scene = getattr(getattr(bpy, "context", None), "scene", None)
        if scene is None:
            scene = next(iter(_iter_scenes()), None)
        if scene is not None:
            _schedule_load_recovery_resolve(scene)
    try:
        module_name = f"{__package__}.unsupported" if __package__ else "unsupported"
        unsupported_module = importlib.import_module(module_name)
        apply_fn = getattr(unsupported_module, "apply_runtime_unsupported_overrides", None)
        if callable(apply_fn):
            apply_fn()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed applying unsupported startup overrides", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
        logger.debug("Planetka: failed applying unsupported startup overrides", exc_info=True)
    try:
        auth_module = importlib.import_module(f"{__package__}.auth")
        is_authenticated = getattr(auth_module, "is_authenticated")
        prefs = get_prefs()
        connected = bool(is_authenticated(prefs))
    except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
        connected = False

    for scene in _iter_scenes():
        try:
            if connected:
                scene[ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY] = True
            elif ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY in scene:
                del scene[ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY]
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed syncing account panel default-collapsed state", exc_info=True)
    ensure_auto_resolve_service_running()
