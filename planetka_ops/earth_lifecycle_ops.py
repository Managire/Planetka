import bpy


def _snapshot_camera_view_areas(context):
    snapshots = []
    seen_region_data = set()

    def _capture_screen(screen):
        if screen is None:
            return
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if str(getattr(area, "type", "") or "") != "VIEW_3D":
                continue
            space = getattr(getattr(area, "spaces", None), "active", None)
            if space is None or str(getattr(space, "type", "") or "") != "VIEW_3D":
                continue
            rv3d = getattr(space, "region_3d", None)
            if rv3d is None:
                continue
            rv3d_id = id(rv3d)
            if rv3d_id in seen_region_data:
                continue
            seen_region_data.add(rv3d_id)
            snapshots.append({
                "area": area,
                "rv3d": rv3d,
                "was_camera": str(getattr(rv3d, "view_perspective", "") or "") == "CAMERA",
            })

    window_manager = getattr(context, "window_manager", None)
    if window_manager is not None:
        for window in tuple(getattr(window_manager, "windows", ()) or ()):
            _capture_screen(getattr(window, "screen", None))

    _capture_screen(getattr(context, "screen", None))
    return tuple(snapshots)


def _restore_camera_view_areas(context, scene, snapshots, logger, recoverable_exceptions):
    del context
    if scene is None or not snapshots:
        return False
    camera = getattr(scene, "camera", None)
    if camera is None:
        return False

    restored = False
    for snapshot in snapshots:
        if not bool(snapshot.get("was_camera", False)):
            continue
        rv3d = snapshot.get("rv3d", None)
        if rv3d is None:
            continue
        try:
            if getattr(scene, "camera", None) is not camera:
                scene.camera = camera
            if str(getattr(rv3d, "view_perspective", "") or "") != "CAMERA":
                rv3d.view_perspective = "CAMERA"
                restored = True
            area = snapshot.get("area", None)
            if area is not None:
                area.tag_redraw()
        except recoverable_exceptions:
            logger.debug("Planetka: failed restoring camera viewport state after rebuild", exc_info=True)
    return restored


def rebuild_earth_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    require_planetka_props = deps["require_planetka_props"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    _snapshot_view_selection = deps["_snapshot_view_selection"]
    _restore_view_selection = deps["_restore_view_selection"]
    _pick_scene_camera = deps["_pick_scene_camera"]
    _snapshot_camera_state_for_rebuild = deps["_snapshot_camera_state_for_rebuild"]
    _snapshot_earth_settings_for_rebuild = deps["_snapshot_earth_settings_for_rebuild"]
    _earth_graph_cleanup_for_rebuild = deps["_earth_graph_cleanup_for_rebuild"]
    _REBUILD_EXCEPTIONS = deps["_REBUILD_EXCEPTIONS"]
    _SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY = deps["_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY"]
    _earth_graph_restore_after_rebuild = deps["_earth_graph_restore_after_rebuild"]

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}

    selected_names_before, active_name_before = _snapshot_view_selection(context)
    camera_view_snapshot = _snapshot_camera_view_areas(context)

    def _return_with_selection(result):
        _restore_view_selection(context, scene, selected_names_before, active_name_before)
        _restore_camera_view_areas(context, scene, camera_view_snapshot, logger, _REBUILD_EXCEPTIONS)
        return result

    camera = _pick_scene_camera(scene, context=context)
    camera_snapshot = _snapshot_camera_state_for_rebuild(scene, camera)
    earth_settings_snapshot = _snapshot_earth_settings_for_rebuild(scene, props)

    cleanup_stats = _earth_graph_cleanup_for_rebuild(scene)
    detached_cameras = int(cleanup_stats.get("detached_cameras", 0))
    removed_objects = int(cleanup_stats.get("removed_objects", 0))
    removed_collections = int(cleanup_stats.get("removed_collections", 0))
    removed_data = dict(cleanup_stats.get("removed_data", {}) or {})
    scene_keys_cleared = int(cleanup_stats.get("scene_keys_cleared", 0))
    cleanup_counts = dict(cleanup_stats.get("cleanup_counts", {}) or {})

    if camera is not None and str(getattr(camera, "type", "")) == "CAMERA":
        try:
            scene.camera = camera
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed preserving active camera before rebuild", exc_info=True)

    try:
        scene[_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY] = True
    except _REBUILD_EXCEPTIONS:
        logger.debug("Planetka: failed setting create-earth camera-skip flag for rebuild", exc_info=True)
    try:
        rebuild_result = bpy.ops.planetka.add_earth()
    finally:
        try:
            if _SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY in scene:
                del scene[_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY]
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed clearing create-earth camera-skip flag after rebuild", exc_info=True)

    _earth_graph_restore_after_rebuild(scene, props, earth_settings_snapshot, camera_snapshot)
    _restore_camera_view_areas(context, scene, camera_view_snapshot, logger, _REBUILD_EXCEPTIONS)

    if "FINISHED" not in rebuild_result:
        return _return_with_selection(fail(
            operator,
            "Rebuild cleanup completed, but Create Earth failed. Resolve integrity may remain invalid.",
            code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
            logger=logger,
        ))

    logger.info(
        "Planetka rebuild completed (detached_cameras=%d, removed_objects=%d, "
        "removed_collections=%d, removed_meshes=%d, removed_images=%d, "
        "removed_materials=%d, removed_node_groups=%d, removed_lights=%d, "
        "scene_keys_cleared=%d, cleanup_objects=%d, cleanup_meshes=%d, cleanup_images=%d, "
        "cleanup_materials=%d, cleanup_node_groups=%d).",
        int(detached_cameras),
        int(removed_objects),
        int(removed_collections),
        int(removed_data.get("meshes", 0)),
        int(removed_data.get("images", 0)),
        int(removed_data.get("materials", 0)),
        int(removed_data.get("node_groups", 0)),
        int(removed_data.get("lights", 0)),
        int(scene_keys_cleared),
        int(cleanup_counts.get("objects", 0) or 0),
        int(cleanup_counts.get("meshes", 0) or 0),
        int(cleanup_counts.get("images", 0) or 0),
        int(cleanup_counts.get("materials", 0) or 0),
        int(cleanup_counts.get("node_groups", 0) or 0),
    )
    operator.report({'INFO'}, "Planetka Earth rebuilt successfully.")
    return _return_with_selection({'FINISHED'})


def add_earth_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    require_planetka_props = deps["require_planetka_props"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = deps["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS = tuple(PLANETKA_RECOVERABLE_EXCEPTIONS) + (
        RuntimeError,
        TypeError,
        ValueError,
        AttributeError,
    )
    _snapshot_view_selection = deps["_snapshot_view_selection"]
    _restore_view_selection = deps["_restore_view_selection"]
    _is_planetka_create_camera = deps["_is_planetka_create_camera"]
    get_prefs = deps["get_prefs"]
    kickoff_background_update_check = deps["kickoff_background_update_check"]
    _validate_create_earth_texture_source = deps["_validate_create_earth_texture_source"]
    is_remote_source_configured = deps["is_remote_source_configured"]
    _require_authenticated_account = deps["_require_authenticated_account"]
    invalidate_texture_source_health_cache = deps["invalidate_texture_source_health_cache"]
    ensure_planetka_assets = deps["ensure_planetka_assets"]
    _initialize_props_from_imported_planetka = deps["_initialize_props_from_imported_planetka"]
    _sync_idprops_from_props = deps["_sync_idprops_from_props"]
    ensure_planetka_root = deps["ensure_planetka_root"]
    warm_base_sphere_mesh_cache = deps["warm_base_sphere_mesh_cache"]
    _earth_graph_create_bootstrap_surface = deps["_earth_graph_create_bootstrap_surface"]
    remove_object_and_unused_mesh = deps["remove_object_and_unused_mesh"]
    _apply_startup_setup_for_create_earth = deps["_apply_startup_setup_for_create_earth"]
    _ensure_planetka_create_camera = deps["_ensure_planetka_create_camera"]
    _position_planetka_create_camera = deps["_position_planetka_create_camera"]
    _apply_create_earth_clipping_defaults = deps["_apply_create_earth_clipping_defaults"]
    get_earth_object = deps["get_earth_object"]
    ensure_preview_object = deps["ensure_preview_object"]
    _earth_graph_rebind = deps["_earth_graph_rebind"]
    _hide_shot_anchor_in_viewport = deps["_hide_shot_anchor_in_viewport"]
    _DEFAULT_SCENE_REMOVED_KEY = deps["_DEFAULT_SCENE_REMOVED_KEY"]

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}
    selected_names_before, active_name_before = _snapshot_view_selection(context)
    preexisting_active_camera = getattr(scene, "camera", None)
    preexisting_cameras = [
        obj for obj in tuple(getattr(scene, "objects", ()))
        if str(getattr(obj, "type", "")) == "CAMERA"
    ]
    preexisting_non_planetka_cameras = [
        obj for obj in preexisting_cameras
        if not _is_planetka_create_camera(obj)
    ]
    activate_planetka_camera = not bool(preexisting_non_planetka_cameras)

    def _return_with_selection(result):
        _restore_view_selection(context, scene, selected_names_before, active_name_before)
        return result

    prefs = get_prefs()
    if not prefs:
        return _return_with_selection(fail(
            operator,
            "Planetka preferences not available.",
            code=ErrorCode.RESOLVE_PREFS_MISSING,
            logger=logger,
        ))
    try:
        kickoff_background_update_check(force=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: updater check kickoff failed", exc_info=True)
    normalized, path_issue = _validate_create_earth_texture_source(getattr(prefs, "texture_base_path", ""))
    if path_issue:
        return _return_with_selection(
            fail(
                operator,
                f"Create Earth data configuration is invalid. {path_issue}",
                code=ErrorCode.RESOLVE_PATH_INVALID,
                logger=logger,
            )
        )
    if is_remote_source_configured(normalized) and not _require_authenticated_account(operator, prefs):
        return _return_with_selection({'CANCELLED'})
    prefs.texture_base_path = normalized
    invalidate_texture_source_health_cache(normalized)

    try:
        ensure_planetka_assets(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        return _return_with_selection(fail(
            operator,
            f"Create Earth failed while creating Planetka assets: {exc}",
            code=ErrorCode.ADD_EARTH_IMPORT_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka add_earth asset build failed",
        ))

    _initialize_props_from_imported_planetka(scene)
    _sync_idprops_from_props(scene)
    try:
        ensure_planetka_root(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed ensuring Planetka Root before Create Earth", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed ensuring Planetka Root before Create Earth", exc_info=True)

    try:
        props.texture_quality_mode = "PREVIEW"
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed setting default texture quality to Preview", exc_info=True)
    warm_base_sphere_mesh_cache()

    new_obj = None
    try:
        new_obj = _earth_graph_create_bootstrap_surface(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        if new_obj:
            remove_object_and_unused_mesh(new_obj)
        return _return_with_selection(fail(
            operator,
            f"Create Earth failed while creating bootstrap Earth surface: {exc}",
            code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka add_earth bootstrap build failed",
        ))

    try:
        _apply_startup_setup_for_create_earth(scene, props)
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed applying startup setup profile", exc_info=True)
    planetka_camera = _ensure_planetka_create_camera(scene)
    if planetka_camera is None:
        logger.debug("Planetka: failed creating Planetka Camera", exc_info=True)
    else:
        try:
            _position_planetka_create_camera(
                scene,
                props,
                planetka_camera,
                activate=bool(activate_planetka_camera),
            )
        except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed positioning Planetka Camera on Create Earth", exc_info=True)
    try:
        props.texture_quality_mode = "PREVIEW"
        _sync_idprops_from_props(scene, ("texture_quality_mode",))
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed enforcing Create Earth default texture quality mode", exc_info=True)
    if bool(getattr(props, "auto_adjust_clipping_values", True)):
        try:
            camera_before_clip = getattr(scene, "camera", None)
            try:
                if planetka_camera is not None and str(getattr(planetka_camera, "type", "")) == "CAMERA":
                    scene.camera = planetka_camera
                _apply_create_earth_clipping_defaults(scene)
            finally:
                if (
                    not bool(activate_planetka_camera)
                    and preexisting_active_camera is not None
                    and str(getattr(preexisting_active_camera, "type", "")) == "CAMERA"
                ):
                    scene.camera = preexisting_active_camera
                elif (
                    not bool(activate_planetka_camera)
                    and preexisting_active_camera is None
                ):
                    scene.camera = camera_before_clip
        except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed applying create-earth clipping defaults", exc_info=True)
    try:
        scene["planetka_status_notice_clear_skip_count"] = 1
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        pass

    resolve_result = bpy.ops.planetka.load_textures(
        skip_render_compatibility=True,
        defer_download=True,
    )
    final_surface = get_earth_object() or new_obj
    if final_surface and bool(getattr(props, "show_earth_preview", False)):
        try:
            ensure_preview_object(final_surface)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed creating preview object", exc_info=True)
            operator.report({'WARNING'}, "Planetka preview object refresh failed.")
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed creating preview object", exc_info=True)
            operator.report({'WARNING'}, "Planetka preview object refresh failed.")

    if "FINISHED" not in resolve_result:
        operator.report({'WARNING'}, "Planetka Earth created, but initial Resolve failed.")
        return _return_with_selection({'CANCELLED'})

    try:
        _apply_startup_setup_for_create_earth(scene, props)
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: post-resolve startup setup re-apply failed", exc_info=True)
    try:
        props.texture_quality_mode = "PREVIEW"
        _sync_idprops_from_props(scene, ("texture_quality_mode",))
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed enforcing post-resolve Create Earth texture quality mode", exc_info=True)

    _earth_graph_rebind(scene=scene, earth_surface=get_earth_object() or new_obj)
    _hide_shot_anchor_in_viewport()
    try:
        if _DEFAULT_SCENE_REMOVED_KEY in scene:
            del scene[_DEFAULT_SCENE_REMOVED_KEY]
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed clearing default-scene removal marker", exc_info=True)

    operator.report({'INFO'}, "Planetka Earth created successfully.")
    return _return_with_selection({'FINISHED'})


def reset_earth_transform_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = deps["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    PLANETKA_ROOT_OBJECT_NAME = deps["PLANETKA_ROOT_OBJECT_NAME"]

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}

    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    if root is None:
        return fail(
            operator,
            "Planetka Root not found. Create Earth first.",
            code=ErrorCode.NAV_PRECHECK_FAILED,
            logger=logger,
        )
    if str(getattr(root, "type", "")) != "EMPTY":
        return fail(
            operator,
            "Planetka Root has invalid type.",
            code=ErrorCode.NAV_PRECHECK_FAILED,
            logger=logger,
        )
    if root not in tuple(getattr(scene, "objects", ())):
        return fail(
            operator,
            "Planetka Root is not in active scene.",
            code=ErrorCode.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    try:
        root.location = (0.0, 0.0, 0.0)
        root.rotation_euler = (0.0, 0.0, 0.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return fail(
            operator,
            "Failed to reset Planetka Root transform.",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
        )

    operator.report({'INFO'}, "Planetka Root transform reset.")
    return {'FINISHED'}
