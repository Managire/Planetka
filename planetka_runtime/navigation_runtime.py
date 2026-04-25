import math
import time

from mathutils import Vector


def navigation_shot_update_timer(runtime, *, bpy, get_earth_object, apply_navigation_shot_now):
    runtime["_NAVIGATION_SHOT_UPDATE_PENDING"] = False

    if runtime.get("_IDPROP_SYNCING"):
        return None

    context = getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    if props is None:
        return None
    earth = get_earth_object()
    if earth is None:
        return None
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    apply_navigation_shot_now()
    return None


def apply_navigation_shot_now(runtime, *, bpy, recoverable_exceptions, logger, get_earth_object):
    if runtime.get("_NAVIGATION_SHOT_UPDATE_REENTRANT"):
        return False
    runtime["_NAVIGATION_SHOT_UPDATE_REENTRANT"] = True
    try:
        force_camera_view = True
        sync_active_view_when_not_camera = False
        context = getattr(bpy, "context", None)
        scene = getattr(context, "scene", None) if context else None
        camera = getattr(scene, "camera", None) if scene is not None else None
        earth = get_earth_object() if callable(get_earth_object) else None
        if scene is None or earth is None or camera is None or getattr(camera, "type", None) != 'CAMERA':
            return False
        if scene is not None:
            try:
                if runtime["_NAV_FORCE_CAMERA_ONCE_KEY"] in scene:
                    force_camera_view = bool(scene.get(runtime["_NAV_FORCE_CAMERA_ONCE_KEY"], True))
                    del scene[runtime["_NAV_FORCE_CAMERA_ONCE_KEY"]]
            except (recoverable_exceptions, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed reading one-shot nav force-camera override", exc_info=True)
            try:
                if runtime["_NAV_SYNC_ACTIVE_VIEW_ONCE_KEY"] in scene:
                    sync_active_view_when_not_camera = bool(scene.get(runtime["_NAV_SYNC_ACTIVE_VIEW_ONCE_KEY"], False))
                    del scene[runtime["_NAV_SYNC_ACTIVE_VIEW_ONCE_KEY"]]
            except (recoverable_exceptions, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed reading one-shot nav sync-active-view override", exc_info=True)
        result = bpy.ops.planetka.navigation_apply_shot(
            silent=True,
            force_camera_view=force_camera_view,
            sync_active_view_when_not_camera=sync_active_view_when_not_camera,
        )
        return "FINISHED" in result
    except recoverable_exceptions:
        logger.debug("Planetka: immediate navigation shot update failed", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: immediate navigation shot update failed", exc_info=True)
        return False
    finally:
        runtime["_NAVIGATION_SHOT_UPDATE_REENTRANT"] = False


def request_next_navigation_apply_behavior(
    runtime,
    scene,
    *,
    force_camera_view=None,
    sync_active_view_when_not_camera=None,
    recoverable_exceptions,
    logger,
):
    if scene is None:
        return
    if force_camera_view is not None:
        try:
            scene[runtime["_NAV_FORCE_CAMERA_ONCE_KEY"]] = bool(force_camera_view)
        except (recoverable_exceptions, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed storing one-shot nav force-camera override", exc_info=True)
    if sync_active_view_when_not_camera is not None:
        try:
            scene[runtime["_NAV_SYNC_ACTIVE_VIEW_ONCE_KEY"]] = bool(sync_active_view_when_not_camera)
        except (recoverable_exceptions, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed storing one-shot nav sync-active-view override", exc_info=True)


def resolve_navigation_adaptive_modifier(*, get_earth_object):
    earth = get_earth_object()
    if earth is None:
        return None, None
    modifiers = getattr(earth, "modifiers", None)
    if modifiers is None:
        return None, None
    subsurf = modifiers.get("Adaptive Subdivision")
    if subsurf is not None and str(getattr(subsurf, "type", "")) == "SUBSURF":
        return earth, subsurf
    for modifier in modifiers:
        if str(getattr(modifier, "type", "")) != "SUBSURF":
            continue
        if "Adaptive" in str(getattr(modifier, "name", "")):
            return earth, modifier
        if bool(getattr(modifier, "use_adaptive_subdivision", False)):
            return earth, modifier
    return None, None


def navigation_adaptive_restore_timer(runtime, *, bpy, recoverable_exceptions, logger, time_module=time):
    if (time_module.monotonic() - float(runtime.get("_NAVIGATION_ADAPTIVE_LAST_TOUCH", 0.0))) < float(runtime.get("_NAVIGATION_ADAPTIVE_IDLE_SEC", 0.5)):
        return 0.05

    suspended = runtime.get("_NAVIGATION_ADAPTIVE_SUSPENDED")
    runtime["_NAVIGATION_ADAPTIVE_SUSPENDED"] = None
    runtime["_NAVIGATION_ADAPTIVE_TIMER_RUNNING"] = False
    if not suspended:
        return None

    obj_name, modifier_name, was_viewport_enabled = suspended
    try:
        obj = bpy.data.objects.get(str(obj_name))
        if obj is None:
            return None
        modifier = obj.modifiers.get(str(modifier_name))
        if modifier is None or str(getattr(modifier, "type", "")) != "SUBSURF":
            return None
        modifier.show_viewport = bool(was_viewport_enabled)
    except recoverable_exceptions:
        logger.debug("Planetka: failed restoring adaptive viewport state", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed restoring adaptive viewport state", exc_info=True)
    return None


def force_restore_navigation_adaptive_state(runtime, *, bpy, recoverable_exceptions, logger):
    suspended = runtime.get("_NAVIGATION_ADAPTIVE_SUSPENDED")
    runtime["_NAVIGATION_ADAPTIVE_SUSPENDED"] = None
    runtime["_NAVIGATION_ADAPTIVE_TIMER_RUNNING"] = False
    if not suspended:
        return

    obj_name, modifier_name, was_viewport_enabled = suspended
    try:
        obj = bpy.data.objects.get(str(obj_name))
        if obj is None:
            return
        modifier = obj.modifiers.get(str(modifier_name))
        if modifier is None or str(getattr(modifier, "type", "")) != "SUBSURF":
            return
        modifier.show_viewport = bool(was_viewport_enabled)
    except recoverable_exceptions:
        logger.debug("Planetka: failed forced restore of adaptive viewport state", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed forced restore of adaptive viewport state", exc_info=True)


def suspend_adaptive_viewport_during_navigation(
    runtime,
    scene,
    *,
    bpy,
    recoverable_exceptions,
    logger,
    resolve_navigation_adaptive_modifier,
    force_restore_navigation_adaptive_state,
    navigation_adaptive_restore_timer,
    time_module=time,
):
    render = getattr(scene, "render", None) if scene else None
    if str(getattr(render, "engine", "")) != "CYCLES":
        force_restore_navigation_adaptive_state()
        return
    props = getattr(scene, "planetka", None) if scene else None
    if props is not None and not bool(getattr(props, "viewport_opt_suspend_subdivision", True)):
        force_restore_navigation_adaptive_state()
        return
    if props is not None:
        try:
            restore_delay = float(getattr(props, "viewport_opt_subdivision_restore_delay_sec", 0.5))
        except (TypeError, ValueError):
            restore_delay = 0.5
        runtime["_NAVIGATION_ADAPTIVE_IDLE_SEC"] = max(0.1, min(2.0, restore_delay))

    obj, modifier = resolve_navigation_adaptive_modifier()
    if obj is None or modifier is None:
        return

    if runtime.get("_NAVIGATION_ADAPTIVE_SUSPENDED") is None:
        runtime["_NAVIGATION_ADAPTIVE_SUSPENDED"] = (
            str(getattr(obj, "name", "")),
            str(getattr(modifier, "name", "")),
            bool(getattr(modifier, "show_viewport", True)),
        )

    try:
        if bool(getattr(modifier, "show_viewport", False)):
            modifier.show_viewport = False
    except recoverable_exceptions:
        logger.debug("Planetka: failed suspending adaptive viewport", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed suspending adaptive viewport", exc_info=True)

    runtime["_NAVIGATION_ADAPTIVE_LAST_TOUCH"] = time_module.monotonic()
    if runtime.get("_NAVIGATION_ADAPTIVE_TIMER_RUNNING"):
        return
    runtime["_NAVIGATION_ADAPTIVE_TIMER_RUNNING"] = True
    try:
        bpy.app.timers.register(navigation_adaptive_restore_timer, first_interval=0.05)
    except recoverable_exceptions:
        runtime["_NAVIGATION_ADAPTIVE_TIMER_RUNNING"] = False
    except (RuntimeError, TypeError, ValueError):
        runtime["_NAVIGATION_ADAPTIVE_TIMER_RUNNING"] = False


def suspend_navigation_shot_updates(runtime):
    runtime["_NAVIGATION_SHOT_SUSPEND_COUNT"] = int(runtime.get("_NAVIGATION_SHOT_SUSPEND_COUNT", 0)) + 1


def resume_navigation_shot_updates(runtime):
    runtime["_NAVIGATION_SHOT_SUSPEND_COUNT"] = max(0, int(runtime.get("_NAVIGATION_SHOT_SUSPEND_COUNT", 0)) - 1)


def suspend_navigation_camera_control_sync(runtime):
    runtime["_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT"] = int(runtime.get("_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT", 0)) + 1


def resume_navigation_camera_control_sync(runtime):
    runtime["_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT"] = max(0, int(runtime.get("_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT", 0)) - 1)


def is_navigation_or_camera_sync_suspended(runtime):
    return bool(
        int(runtime.get("_NAVIGATION_SHOT_SUSPEND_COUNT", 0)) > 0
        or runtime.get("_NAV_CAMERA_CONTROL_SYNCING")
        or int(runtime.get("_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT", 0)) > 0
    )


def mark_navigation_camera_control_signature(runtime, scene=None, *, bpy, scene_key, camera_control_sync_signature):
    target_scene = scene
    if target_scene is None:
        target_scene = getattr(getattr(bpy, "context", None), "scene", None)
    if target_scene is None:
        return
    current_scene_id = scene_key(target_scene)
    signature = camera_control_sync_signature(target_scene)
    last_map = runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"]
    if signature is None:
        last_map.pop(current_scene_id, None)
        return
    last_map[current_scene_id] = signature


def get_planetka_sunlight_object(runtime, *, bpy):
    sunlight = bpy.data.objects.get(runtime["_SUNLIGHT_OBJECT_NAME"])
    if sunlight is None:
        return None
    if str(getattr(sunlight, "type", "")) != "LIGHT":
        return None
    light_data = getattr(sunlight, "data", None)
    if light_data is None or str(getattr(light_data, "type", "")) != "SUN":
        return None
    return sunlight


def apply_sunlight_from_props(runtime, scene, *, bpy, recoverable_exceptions, logger):
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    sunlight = get_planetka_sunlight_object(runtime, bpy=bpy)
    if sunlight is None:
        return

    try:
        lon_deg = float(getattr(props, "sunlight_longitude_deg", 0.0))
        lat_deg = float(getattr(props, "sunlight_seasonal_tilt_deg", 0.0))
    except (TypeError, ValueError):
        return

    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    try:
        direction = Vector(
            (
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            )
        )
        if direction.length < 1e-9:
            return
        direction.normalize()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return

    try:
        quat = direction.to_track_quat('Z', 'Y')
        sunlight.rotation_mode = 'XYZ'
        sunlight.rotation_euler = quat.to_euler('XYZ')
    except recoverable_exceptions:
        logger.debug("Planetka: failed applying sunlight transform", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed applying sunlight transform", exc_info=True)


def apply_sunlight_strength_from_props(runtime, scene, *, bpy, recoverable_exceptions, logger):
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    sunlight = get_planetka_sunlight_object(runtime, bpy=bpy)
    if sunlight is None:
        return

    light_data = getattr(sunlight, "data", None)
    if light_data is None:
        return

    try:
        strength = max(0.0, float(getattr(props, "sunlight_strength", 10.0)))
    except (TypeError, ValueError):
        return

    try:
        light_data.energy = strength
    except recoverable_exceptions:
        logger.debug("Planetka: failed applying sunlight strength", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed applying sunlight strength", exc_info=True)


def update_sunlight_controls(
    runtime,
    self,
    context,
    *,
    sync_idprops_from_props,
    suspend_adaptive_viewport_during_navigation,
    request_auto_resolve,
    apply_sunlight_from_props,
    apply_sunlight_strength_from_props,
):
    scene = getattr(context, "scene", None) if context else None
    if scene:
        sync_idprops_from_props(scene, ("sunlight_longitude_deg", "sunlight_seasonal_tilt_deg"))
        suspend_adaptive_viewport_during_navigation(scene)
        request_auto_resolve(scene, immediate=False)
    apply_sunlight_from_props(scene)
    apply_sunlight_strength_from_props(scene)


def update_sunlight_strength(
    runtime,
    self,
    context,
    *,
    sync_idprops_from_props,
    suspend_adaptive_viewport_during_navigation,
    apply_sunlight_strength_from_props,
):
    scene = getattr(context, "scene", None) if context else None
    if scene:
        sync_idprops_from_props(scene, ("sunlight_strength",))
        suspend_adaptive_viewport_during_navigation(scene)
    apply_sunlight_strength_from_props(scene)


def update_navigation_shot(
    runtime,
    self,
    context,
    *,
    sync_navigation_idprops_from_props,
    suspend_adaptive_viewport_during_navigation,
    request_auto_resolve,
    apply_navigation_shot_now,
    bpy,
    recoverable_exceptions,
):
    if int(runtime.get("_NAVIGATION_SHOT_SUSPEND_COUNT", 0)) > 0:
        return
    if runtime.get("_IDPROP_SYNCING") or runtime.get("_NAVIGATION_SHOT_UPDATE_REENTRANT"):
        return

    scene = getattr(context, "scene", None) if context else None
    if scene:
        runtime["_NAVIGATION_USER_EDIT_LAST_TOUCH"] = time.monotonic()
        sync_navigation_idprops_from_props(scene)
        suspend_adaptive_viewport_during_navigation(scene)
        request_auto_resolve(scene, immediate=False)
    if apply_navigation_shot_now():
        runtime["_NAVIGATION_SHOT_UPDATE_PENDING"] = False
        return
    if runtime.get("_NAVIGATION_SHOT_UPDATE_PENDING"):
        return
    runtime["_NAVIGATION_SHOT_UPDATE_PENDING"] = True
    try:
        bpy.app.timers.register(runtime["_navigation_shot_update_timer_wrapper"], first_interval=0.0)
    except recoverable_exceptions:
        runtime["_NAVIGATION_SHOT_UPDATE_PENDING"] = False
    except (RuntimeError, TypeError, ValueError):
        runtime["_NAVIGATION_SHOT_UPDATE_PENDING"] = False


def update_navigation_focal_length(
    runtime,
    self,
    context,
    *,
    sync_navigation_idprops_from_props,
    suspend_adaptive_viewport_during_navigation,
    request_auto_resolve,
    logger,
    recoverable_exceptions,
):
    if int(runtime.get("_NAVIGATION_SHOT_SUSPEND_COUNT", 0)) > 0:
        return
    if runtime.get("_IDPROP_SYNCING") or runtime.get("_NAVIGATION_SHOT_UPDATE_REENTRANT") or runtime.get("_NAV_CAMERA_CONTROL_SYNCING"):
        return

    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return

    runtime["_NAVIGATION_USER_EDIT_LAST_TOUCH"] = time.monotonic()
    sync_navigation_idprops_from_props(scene)
    suspend_adaptive_viewport_during_navigation(scene)

    camera = getattr(scene, "camera", None)
    camera_data = getattr(camera, "data", None) if camera is not None else None
    if camera is not None and getattr(camera, "type", None) == 'CAMERA' and camera_data is not None:
        try:
            lens_mm = max(1.0, float(getattr(self, "nav_focal_length_mm", 50.0)))
            camera_data.lens = lens_mm
        except recoverable_exceptions:
            logger.debug("Planetka: failed applying camera focal length", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed applying camera focal length", exc_info=True)

    request_auto_resolve(scene, immediate=False)


def camera_control_sync_signature(scene):
    if scene is None:
        return None

    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None
    camera_data = getattr(camera, "data", None)
    if camera_data is None:
        return None

    try:
        camera_matrix_signature = tuple(
            round(float(value), 6)
            for row in camera.matrix_world
            for value in row
        )
    except (TypeError, ValueError, RuntimeError):
        return None

    return (
        str(getattr(camera, "name_full", camera.name)),
        str(getattr(camera_data, "type", "")),
        round(float(getattr(camera_data, "lens", 0.0)), 6),
        round(float(getattr(camera_data, "ortho_scale", 0.0)), 6),
        camera_matrix_signature,
    )


def sync_navigation_controls_from_scene_camera(
    runtime,
    scene,
    *,
    get_earth_object,
    scene_key,
    get_operators_module,
    suspend_navigation_shot_updates,
    resume_navigation_shot_updates,
    recoverable_exceptions,
    logger,
):
    if scene is None:
        return
    if runtime.get("_IDPROP_SYNCING") or runtime.get("_NAV_CAMERA_CONTROL_SYNCING"):
        return
    if int(runtime.get("_NAVIGATION_SHOT_SUSPEND_COUNT", 0)) > 0 or runtime.get("_NAVIGATION_SHOT_UPDATE_REENTRANT"):
        return

    props = getattr(scene, "planetka", None)
    if props is None:
        return

    scene_id = scene_key(scene)
    if get_earth_object() is None:
        runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"].pop(scene_id, None)
        return

    signature = camera_control_sync_signature(scene)
    if signature is None:
        runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"].pop(scene_id, None)
        return
    if int(runtime.get("_NAV_CAMERA_CONTROL_SYNC_SUSPEND_COUNT", 0)) > 0:
        runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"][scene_id] = signature
        return
    if runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"].get(scene_id) == signature:
        return

    operators_module = get_operators_module()
    if operators_module is None:
        return
    is_below_surface = getattr(operators_module, "_is_scene_camera_below_surface", None)
    if callable(is_below_surface):
        try:
            if bool(is_below_surface(scene)):
                runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"][scene_id] = signature
                return
        except recoverable_exceptions:
            logger.debug("Planetka camera control surface-state check failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka camera control surface-state check failed", exc_info=True)
    populate = getattr(operators_module, "_populate_navigation_from_scene_camera", None)
    if not callable(populate):
        return

    runtime["_NAV_CAMERA_CONTROL_SYNCING"] = True
    suspend_navigation_shot_updates()
    synced = False
    try:
        synced = bool(populate(scene, props))
    except recoverable_exceptions:
        logger.debug("Planetka camera control sync failed", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka camera control sync failed", exc_info=True)
    finally:
        resume_navigation_shot_updates()
        runtime["_NAV_CAMERA_CONTROL_SYNCING"] = False

    if synced:
        runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"][scene_id] = signature
    else:
        runtime["_NAV_CAMERA_CONTROL_LAST_SIGNATURE"].pop(scene_id, None)
