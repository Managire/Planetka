import bpy
import time

from ..extension_prefs import get_earth_object, get_prefs

CREATE_EARTH_STATUS_KEY = "planetka_create_earth_status"
CREATE_EARTH_STATUS_ACTIVE_KEY = "planetka_create_earth_status_active"


def _atmosphere_mode_for_create_earth(scene):
    try:
        engine = str(getattr(getattr(scene, "render", None), "engine", "") or "").upper()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        engine = ""
    return "VOLUMETRIC" if engine == "CYCLES" else "EEVEE"

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
    _validate_create_earth_texture_source = deps["_validate_create_earth_texture_source"]
    is_remote_source_configured = deps["is_remote_source_configured"]
    _require_planetka_cloud_session = deps["_require_planetka_cloud_session"]
    invalidate_texture_source_health_cache = deps["invalidate_texture_source_health_cache"]
    ensure_planetka_assets = deps["ensure_planetka_assets"]
    ensure_atmosphere_for_mode = deps.get("ensure_atmosphere_for_mode")
    ensure_global_cloud_layer = deps.get("ensure_global_cloud_layer")
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

    def _set_create_status(message, active=True):
        text = str(message or "").strip()
        try:
            scene[CREATE_EARTH_STATUS_KEY] = text
            scene[CREATE_EARTH_STATUS_ACTIVE_KEY] = bool(active)
        except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
            pass
        if text:
            try:
                logger.info("Planetka Create Earth: %s", text)
            except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
                pass
        try:
            for area in tuple(getattr(getattr(context, "screen", None), "areas", ()) or ()):
                area.tag_redraw()
        except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
            pass
        try:
            if not bool(getattr(bpy.app, "background", False)):
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
            pass

    def _log_phase_timing(label, started_at):
        try:
            elapsed_ms = (time.perf_counter() - float(started_at)) * 1000.0
            logger.info("Planetka Create Earth timing: %s %.1f ms", str(label), elapsed_ms)
        except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
            pass

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
        _set_create_status("Planetka preferences unavailable.", active=False)
        return _return_with_selection(fail(
            operator,
            "Planetka preferences not available.",
            code=ErrorCode.RESOLVE_PREFS_MISSING,
            logger=logger,
        ))
    _set_create_status("Checking Planetka Cloud connection...")
    _set_create_status("Validating Planetka data source...")
    normalized, path_issue = _validate_create_earth_texture_source(getattr(prefs, "texture_base_path", ""))
    if path_issue:
        _set_create_status("Create Earth failed: data source invalid.", active=False)
        return _return_with_selection(
            fail(
                operator,
                f"Create Earth data configuration is invalid. {path_issue}",
                code=ErrorCode.RESOLVE_PATH_INVALID,
                logger=logger,
            )
        )
    if is_remote_source_configured(normalized) and not _require_planetka_cloud_session(operator, prefs):
        _set_create_status("Create Earth cancelled: Planetka Cloud connection unavailable.", active=False)
        return _return_with_selection({'CANCELLED'})
    prefs.texture_base_path = normalized
    invalidate_texture_source_health_cache(normalized)

    try:
        _set_create_status("Creating Planetka assets...")
        ensure_planetka_assets(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        _set_create_status("Create Earth failed while creating Planetka assets.", active=False)
        return _return_with_selection(fail(
            operator,
            f"Create Earth failed while creating Planetka assets: {exc}",
            code=ErrorCode.ADD_EARTH_IMPORT_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka add_earth asset build failed",
        ))

    _set_create_status("Initializing Planetka settings...")
    _initialize_props_from_imported_planetka(scene)
    _sync_idprops_from_props(scene)
    try:
        _set_create_status("Creating Planetka Root...")
        ensure_planetka_root(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed ensuring Planetka Root before Create Earth", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed ensuring Planetka Root before Create Earth", exc_info=True)

    try:
        props.texture_quality_mode = "PREVIEW"
        _sync_idprops_from_props(scene, ("texture_quality_mode",))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed setting default texture quality", exc_info=True)
    _set_create_status("Preparing Earth mesh cache...")
    warm_base_sphere_mesh_cache()

    new_obj = None
    try:
        _set_create_status("Creating Earth surface mesh...")
        new_obj = _earth_graph_create_bootstrap_surface(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        if new_obj:
            remove_object_and_unused_mesh(new_obj)
        _set_create_status("Create Earth failed while creating Earth surface mesh.", active=False)
        return _return_with_selection(fail(
            operator,
            f"Create Earth failed while creating bootstrap Earth surface: {exc}",
            code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka add_earth bootstrap build failed",
        ))

    try:
        phase_start = time.perf_counter()
        _set_create_status("Applying startup defaults...")
        _apply_startup_setup_for_create_earth(scene, props)
        _log_phase_timing("startup defaults", phase_start)
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed applying Create Earth defaults", exc_info=True)

    try:
        _set_create_status("Creating atmosphere...")
        atmosphere_mode = _atmosphere_mode_for_create_earth(scene)
        props.atmosphere_mode = atmosphere_mode
        props.atmosphere_enabled = True
        _sync_idprops_from_props(scene, ("atmosphere_mode", "atmosphere_enabled"))
        if callable(ensure_atmosphere_for_mode):
            ensure_atmosphere_for_mode(scene=scene, earth_surface=new_obj, mode=atmosphere_mode)
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed creating default atmosphere on Create Earth", exc_info=True)

    try:
        _set_create_status("Creating global clouds...")
        clouds_were_enabled = bool(getattr(props, "enable_global_clouds", False))
        if not clouds_were_enabled:
            props.enable_global_clouds = True
            _sync_idprops_from_props(scene, ("enable_global_clouds",))
        elif callable(ensure_global_cloud_layer):
            ensure_global_cloud_layer(scene=scene)
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed creating global clouds on Create Earth", exc_info=True)

    _set_create_status("Creating Planetka Camera...")
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
        logger.debug("Planetka: failed enforcing Create Earth default texture quality", exc_info=True)
    if bool(getattr(props, "auto_adjust_clipping_values", True)):
        try:
            _set_create_status("Applying camera clipping...")
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

    final_surface = get_earth_object() or new_obj
    if final_surface and bool(getattr(props, "show_earth_preview", False)):
        try:
            phase_start = time.perf_counter()
            _set_create_status("Creating Earth preview object...")
            ensure_preview_object(final_surface)
            _log_phase_timing("Earth preview object", phase_start)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed creating preview object", exc_info=True)
            operator.report({'WARNING'}, "Planetka preview object refresh failed.")
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed creating preview object", exc_info=True)
            operator.report({'WARNING'}, "Planetka preview object refresh failed.")

    try:
        props.texture_quality_mode = "PREVIEW"
        _sync_idprops_from_props(scene, ("texture_quality_mode",))
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed enforcing post-resolve Create Earth texture quality", exc_info=True)

    _set_create_status("Binding Earth material graph...")
    _earth_graph_rebind(scene=scene, earth_surface=get_earth_object() or new_obj)
    try:
        _set_create_status("Applying startup texture data...")
        bpy.ops.planetka.load_textures(
            scope_mode="CAMERA",
            skip_render_compatibility=True,
            defer_download=True,
            tiles_override_json="",
            texture_quality_mode_override="PREVIEW",
        )
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS as exc:
        _set_create_status("Create Earth failed while applying startup texture data.", active=False)
        return _return_with_selection(fail(
            operator,
            f"Create Earth failed while starting Planetka Resolve: {exc}",
            code=ErrorCode.RESOLVE_REFRESH_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka add_earth initial resolve failed",
        ))
    _hide_shot_anchor_in_viewport()
    try:
        if _DEFAULT_SCENE_REMOVED_KEY in scene:
            del scene[_DEFAULT_SCENE_REMOVED_KEY]
    except PLANETKA_CREATE_EARTH_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed clearing default-scene removal marker", exc_info=True)

    _set_create_status("Planetka Earth created successfully.", active=False)
    operator.report({'INFO'}, "Planetka Earth created successfully.")
    return _return_with_selection({'FINISHED'})


def reset_earth_transform_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = deps["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    PLANETKA_ROOT_OBJECT_NAME = deps["PLANETKA_ROOT_OBJECT_NAME"]
    set_radius_fn = deps.get("_set_planetka_earth_radius_bu")
    sync_idprops_from_props = deps.get("_sync_idprops_from_props")

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
        from .earth_lifecycle_helpers import detach_planetka_camera_from_root
        detach_planetka_camera_from_root(scene)
        root.location = (0.0, 0.0, 0.0)
        root.rotation_euler = (0.0, 0.0, 0.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return fail(
            operator,
            "Failed to reset Planetka Root transform.",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
        )

    try:
        props = getattr(scene, "planetka", None)
        if props is not None:
            props.earth_radius_bu = 2.0
            if callable(sync_idprops_from_props):
                sync_idprops_from_props(scene, ("earth_radius_bu",))
        elif callable(set_radius_fn):
            set_radius_fn(scene, 2.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return fail(
            operator,
            "Failed to reset Earth Radius.",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return fail(
            operator,
            "Failed to reset Earth Radius.",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
        )

    operator.report({'INFO'}, "Planetka Earth transform reset.")
    return {'FINISHED'}
