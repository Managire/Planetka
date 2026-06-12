import math
import time

from mathutils import Vector

_NAVIGATION_RUNTIME_CTX = None
_NAVIGATION_ADAPTIVE_RESTORE_DELAY_SECONDS = 0.35
_ADAPTIVE_SUBDIVISION_MODIFIER_NAME = "Adaptive Subdivision"


def _require_ctx():
    ctx = _NAVIGATION_RUNTIME_CTX
    if ctx is None:
        raise RuntimeError("Planetka navigation runtime context is not configured.")
    return ctx


def _is_context(value):
    return hasattr(value, "deps") and hasattr(value, "state")


def _coerce_ctx(value=None):
    if _is_context(value):
        return value
    return _require_ctx()


def navigation_shot_update_timer(runtime=None, *, bpy=None, get_earth_object=None, apply_navigation_shot_now=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    bpy_module = bpy if bpy is not None else deps.bpy
    get_earth = get_earth_object if callable(get_earth_object) else deps.get_earth_object
    apply_shot = apply_navigation_shot_now
    if not callable(apply_shot):
        apply_shot = lambda: apply_navigation_shot_now_fn(ctx)
    state.navigation_shot_update_pending = False

    if deps.is_idprop_syncing():
        return None

    context = getattr(bpy_module, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return None
    props = getattr(scene, "planetka", None)
    if props is None:
        return None
    earth = get_earth()
    if earth is None:
        return None
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    apply_shot()
    return None


def apply_navigation_shot_now_fn(runtime=None, *, bpy=None, recoverable_exceptions=None, logger=None, get_earth_object=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    bpy_module = bpy if bpy is not None else deps.bpy
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions
    runtime_logger = logger if logger is not None else deps.logger
    get_earth = get_earth_object if callable(get_earth_object) else deps.get_earth_object
    if state.navigation_shot_update_reentrant:
        return False
    state.navigation_shot_update_reentrant = True
    try:
        force_camera_view = True
        sync_active_view_when_not_camera = False
        context = getattr(bpy_module, "context", None)
        scene = getattr(context, "scene", None) if context else None
        camera = getattr(scene, "camera", None) if scene is not None else None
        earth = get_earth() if callable(get_earth) else None
        if scene is None or earth is None or camera is None or getattr(camera, "type", None) != 'CAMERA':
            return False
        if scene is not None:
            try:
                if deps.nav_force_camera_once_key in scene:
                    force_camera_view = bool(scene.get(deps.nav_force_camera_once_key, True))
                    del scene[deps.nav_force_camera_once_key]
            except (recoverable, RuntimeError, TypeError, ValueError, AttributeError):
                runtime_logger.debug("Planetka: failed reading one-shot nav force-camera override", exc_info=True)
            try:
                if deps.nav_sync_active_view_once_key in scene:
                    sync_active_view_when_not_camera = bool(scene.get(deps.nav_sync_active_view_once_key, False))
                    del scene[deps.nav_sync_active_view_once_key]
            except (recoverable, RuntimeError, TypeError, ValueError, AttributeError):
                runtime_logger.debug("Planetka: failed reading one-shot nav sync-active-view override", exc_info=True)
        result = bpy_module.ops.planetka.navigation_apply_shot(
            force_camera_view=force_camera_view,
            sync_active_view_when_not_camera=sync_active_view_when_not_camera,
        )
        return "FINISHED" in result
    except recoverable:
        runtime_logger.debug("Planetka: immediate navigation shot update failed", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError):
        runtime_logger.debug("Planetka: immediate navigation shot update failed", exc_info=True)
        return False
    finally:
        state.navigation_shot_update_reentrant = False


def request_next_navigation_apply_behavior(
    runtime,
    scene,
    *,
    force_camera_view=None,
    sync_active_view_when_not_camera=None,
    recoverable_exceptions=None,
    logger=None,
):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions
    runtime_logger = logger if logger is not None else deps.logger
    if scene is None:
        return
    if force_camera_view is not None:
        try:
            scene[deps.nav_force_camera_once_key] = bool(force_camera_view)
        except (recoverable, RuntimeError, TypeError, ValueError, AttributeError):
            runtime_logger.debug("Planetka: failed storing one-shot nav force-camera override", exc_info=True)
    if sync_active_view_when_not_camera is not None:
        try:
            scene[deps.nav_sync_active_view_once_key] = bool(sync_active_view_when_not_camera)
        except (recoverable, RuntimeError, TypeError, ValueError, AttributeError):
            runtime_logger.debug("Planetka: failed storing one-shot nav sync-active-view override", exc_info=True)


def _surface_adaptive_subdivision_modifier(ctx):
    deps = ctx.deps
    try:
        earth = deps.get_earth_object()
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed reading Earth object for navigation adaptive subdivision suspend", exc_info=True)
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed reading Earth object for navigation adaptive subdivision suspend", exc_info=True)
        return None
    if earth is None:
        return None
    modifiers = getattr(earth, "modifiers", None)
    if modifiers is None:
        return None
    try:
        modifier = modifiers.get(_ADAPTIVE_SUBDIVISION_MODIFIER_NAME)
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed reading Earth adaptive subdivision modifier", exc_info=True)
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed reading Earth adaptive subdivision modifier", exc_info=True)
        return None
    if modifier is None or not hasattr(modifier, "show_viewport"):
        return None
    return modifier


def _navigation_adaptive_restore_timer(runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    elapsed = time.monotonic() - float(state.navigation_user_edit_last_touch or 0.0)
    if elapsed < float(_NAVIGATION_ADAPTIVE_RESTORE_DELAY_SECONDS):
        return max(0.05, float(_NAVIGATION_ADAPTIVE_RESTORE_DELAY_SECONDS) - float(elapsed))
    force_restore_navigation_adaptive_state(ctx)
    return None


def suspend_surface_adaptive_subdivision_for_navigation(runtime=None, scene=None):
    del scene
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    state.navigation_user_edit_last_touch = time.monotonic()

    modifier = _surface_adaptive_subdivision_modifier(ctx)
    if modifier is None:
        return False

    key = str(getattr(modifier, "name", _ADAPTIVE_SUBDIVISION_MODIFIER_NAME) or _ADAPTIVE_SUBDIVISION_MODIFIER_NAME)
    try:
        if key not in state.navigation_adaptive_restore_states:
            state.navigation_adaptive_restore_states[key] = bool(getattr(modifier, "show_viewport", True))
        modifier.show_viewport = False
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed suspending Earth adaptive subdivision while navigating", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed suspending Earth adaptive subdivision while navigating", exc_info=True)
        return False

    if not bool(state.navigation_adaptive_restore_pending):
        state.navigation_adaptive_restore_pending = True
        try:
            deps.bpy.app.timers.register(lambda: _navigation_adaptive_restore_timer(ctx), first_interval=float(_NAVIGATION_ADAPTIVE_RESTORE_DELAY_SECONDS))
        except deps.recoverable_exceptions:
            state.navigation_adaptive_restore_pending = False
            deps.logger.debug("Planetka: failed scheduling adaptive subdivision restore timer", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            state.navigation_adaptive_restore_pending = False
            deps.logger.debug("Planetka: failed scheduling adaptive subdivision restore timer", exc_info=True)
    return True


def force_restore_navigation_adaptive_state(runtime=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    modifier = _surface_adaptive_subdivision_modifier(ctx)
    restore_states = dict(state.navigation_adaptive_restore_states or {})
    state.navigation_adaptive_restore_states.clear()
    state.navigation_adaptive_restore_pending = False
    if modifier is None or not restore_states:
        return False
    key = str(getattr(modifier, "name", _ADAPTIVE_SUBDIVISION_MODIFIER_NAME) or _ADAPTIVE_SUBDIVISION_MODIFIER_NAME)
    target_value = restore_states.get(key)
    if target_value is None and len(restore_states) == 1:
        target_value = next(iter(restore_states.values()))
    if target_value is None:
        return False
    try:
        modifier.show_viewport = bool(target_value)
        return True
    except deps.recoverable_exceptions:
        deps.logger.debug("Planetka: failed restoring Earth adaptive subdivision after navigation", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        deps.logger.debug("Planetka: failed restoring Earth adaptive subdivision after navigation", exc_info=True)
    return False


def suspend_navigation_shot_updates(runtime=None):
    ctx = _coerce_ctx(runtime)
    ctx.state.navigation_shot_suspend_count = int(ctx.state.navigation_shot_suspend_count) + 1


def resume_navigation_shot_updates(runtime=None):
    ctx = _coerce_ctx(runtime)
    ctx.state.navigation_shot_suspend_count = max(0, int(ctx.state.navigation_shot_suspend_count) - 1)


def suspend_navigation_camera_control_sync(runtime=None):
    ctx = _coerce_ctx(runtime)
    ctx.state.nav_camera_control_sync_suspend_count = int(ctx.state.nav_camera_control_sync_suspend_count) + 1


def resume_navigation_camera_control_sync(runtime=None):
    ctx = _coerce_ctx(runtime)
    ctx.state.nav_camera_control_sync_suspend_count = max(0, int(ctx.state.nav_camera_control_sync_suspend_count) - 1)


def is_navigation_or_camera_sync_suspended(runtime=None):
    ctx = _coerce_ctx(runtime)
    state = ctx.state
    return bool(
        int(state.navigation_shot_suspend_count) > 0
        or state.nav_camera_control_syncing
        or int(state.nav_camera_control_sync_suspend_count) > 0
    )


def mark_navigation_camera_control_signature(runtime=None, scene=None, *, bpy=None, scene_key=None, camera_control_sync_signature=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    bpy_module = bpy if bpy is not None else deps.bpy
    scene_key_fn = scene_key if callable(scene_key) else deps.scene_key
    signature_fn = (
        camera_control_sync_signature
        if callable(camera_control_sync_signature)
        else deps.camera_control_sync_signature
    )
    target_scene = scene
    if target_scene is None:
        target_scene = getattr(getattr(bpy_module, "context", None), "scene", None)
    if target_scene is None:
        return
    current_scene_id = scene_key_fn(target_scene)
    signature = signature_fn(target_scene)
    last_map = state.nav_camera_control_last_signature
    if signature is None:
        last_map.pop(current_scene_id, None)
        return
    last_map[current_scene_id] = signature


def get_planetka_sunlight_object(runtime=None, scene=None, *, bpy=None, recoverable_exceptions=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    bpy_module = bpy if bpy is not None else deps.bpy
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions

    def _is_valid_sunlight_object(obj):
        if obj is None or str(getattr(obj, "type", "")) != "LIGHT":
            return False
        light_data = getattr(obj, "data", None)
        return bool(light_data is not None and str(getattr(light_data, "type", "")) == "SUN")

    target_scene = scene
    if target_scene is None:
        target_scene = getattr(getattr(bpy_module, "context", None), "scene", None)

    # STRICT RULE: only Planetka Sunlight is allowed to be modified.
    # Never target arbitrary SUN lights.
    if target_scene is not None:
        scene_objects = getattr(target_scene, "objects", None)
        if scene_objects is not None:
            try:
                exact = scene_objects.get(deps.sunlight_object_name)
            except (recoverable, RuntimeError, TypeError, ValueError, AttributeError):
                exact = None
            if _is_valid_sunlight_object(exact):
                return exact

    # Fallback to exact global object lookup.
    sunlight = bpy_module.data.objects.get(deps.sunlight_object_name)
    if _is_valid_sunlight_object(sunlight):
        return sunlight
    return None


def apply_sunlight_from_props(runtime=None, scene=None, *, bpy=None, recoverable_exceptions=None, logger=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    bpy_module = bpy if bpy is not None else deps.bpy
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions
    runtime_logger = logger if logger is not None else deps.logger
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    sunlight = get_planetka_sunlight_object(
        ctx,
        scene=scene,
        bpy=bpy_module,
        recoverable_exceptions=recoverable,
    )
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
    except recoverable:
        runtime_logger.debug("Planetka: failed applying sunlight transform", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        runtime_logger.debug("Planetka: failed applying sunlight transform", exc_info=True)


def apply_sunlight_strength_from_props(runtime=None, scene=None, *, bpy=None, recoverable_exceptions=None, logger=None):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    bpy_module = bpy if bpy is not None else deps.bpy
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions
    runtime_logger = logger if logger is not None else deps.logger
    if scene is None:
        return
    props = getattr(scene, "planetka", None)
    if props is None:
        return
    sunlight = get_planetka_sunlight_object(
        ctx,
        scene=scene,
        bpy=bpy_module,
        recoverable_exceptions=recoverable,
    )
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
    except recoverable:
        runtime_logger.debug("Planetka: failed applying sunlight strength", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        runtime_logger.debug("Planetka: failed applying sunlight strength", exc_info=True)


def update_sunlight_controls(
    runtime,
    self,
    context,
    *,
    sync_idprops_from_props=None,
    apply_sunlight_from_props_fn=None,
    apply_sunlight_strength_from_props_fn=None,
):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    sync_idprops = sync_idprops_from_props or deps.sync_idprops_from_props
    apply_sunlight = apply_sunlight_from_props_fn or apply_sunlight_from_props
    apply_strength = apply_sunlight_strength_from_props_fn or apply_sunlight_strength_from_props
    scene = getattr(context, "scene", None) if context else None
    if scene:
        sync_idprops(scene, ("sunlight_longitude_deg", "sunlight_seasonal_tilt_deg"))
    apply_sunlight(ctx, scene)
    apply_strength(ctx, scene)


def update_sunlight_strength(
    runtime,
    self,
    context,
    *,
    sync_idprops_from_props=None,
    apply_sunlight_strength_from_props_fn=None,
):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    sync_idprops = sync_idprops_from_props or deps.sync_idprops_from_props
    apply_strength = apply_sunlight_strength_from_props_fn or apply_sunlight_strength_from_props
    scene = getattr(context, "scene", None) if context else None
    if scene:
        sync_idprops(scene, ("sunlight_strength",))
    apply_strength(ctx, scene)


def update_navigation_shot(
    runtime,
    self,
    context,
    *,
    sync_navigation_idprops_from_props=None,
    apply_navigation_shot_now=None,
    bpy=None,
    recoverable_exceptions=None,
):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    sync_navigation_idprops = sync_navigation_idprops_from_props or deps.sync_navigation_idprops_from_props
    apply_shot = apply_navigation_shot_now or (lambda: apply_navigation_shot_now_fn(ctx))
    bpy_module = bpy if bpy is not None else deps.bpy
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions
    if int(state.navigation_shot_suspend_count) > 0:
        return
    if deps.is_idprop_syncing() or state.navigation_shot_update_reentrant:
        return

    scene = getattr(context, "scene", None) if context else None
    if scene:
        state.navigation_user_edit_last_touch = time.monotonic()
        suspend_surface_adaptive_subdivision_for_navigation(ctx, scene=scene)
        sync_navigation_idprops(scene)
    if apply_shot():
        state.navigation_shot_update_pending = False
        return
    if state.navigation_shot_update_pending:
        return
    state.navigation_shot_update_pending = True
    try:
        bpy_module.app.timers.register(lambda: navigation_shot_update_timer(ctx), first_interval=0.0)
    except recoverable:
        state.navigation_shot_update_pending = False
    except (RuntimeError, TypeError, ValueError):
        state.navigation_shot_update_pending = False


def update_navigation_focal_length(
    runtime,
    self,
    context,
    *,
    sync_navigation_idprops_from_props=None,
    logger=None,
    recoverable_exceptions=None,
):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    sync_navigation_idprops = sync_navigation_idprops_from_props or deps.sync_navigation_idprops_from_props
    runtime_logger = logger if logger is not None else deps.logger
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions
    if int(state.navigation_shot_suspend_count) > 0:
        return
    if deps.is_idprop_syncing() or state.navigation_shot_update_reentrant or state.nav_camera_control_syncing:
        return

    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return

    state.navigation_user_edit_last_touch = time.monotonic()
    suspend_surface_adaptive_subdivision_for_navigation(ctx, scene=scene)
    sync_navigation_idprops(scene)

    camera = getattr(scene, "camera", None)
    camera_data = getattr(camera, "data", None) if camera is not None else None
    if camera is not None and getattr(camera, "type", None) == 'CAMERA' and camera_data is not None:
        try:
            lens_mm = max(1.0, float(getattr(self, "nav_focal_length_mm", 50.0)))
            camera_data.lens = lens_mm
        except recoverable:
            runtime_logger.debug("Planetka: failed applying camera focal length", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            runtime_logger.debug("Planetka: failed applying camera focal length", exc_info=True)


def reset_navigation_shot_runtime_state(runtime=None):
    ctx = _coerce_ctx(runtime)
    force_restore_navigation_adaptive_state(ctx)
    state = ctx.state
    state.navigation_shot_update_pending = False
    state.navigation_shot_update_reentrant = False
    state.navigation_shot_suspend_count = 0


def reset_navigation_camera_control_runtime_state(runtime=None):
    ctx = _coerce_ctx(runtime)
    state = ctx.state
    state.nav_camera_control_syncing = False
    state.nav_camera_control_sync_suspend_count = 0


def apply_navigation_shot_now(runtime=None, **kwargs):
    return apply_navigation_shot_now_fn(runtime, **kwargs)


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
    get_earth_object=None,
    scene_key=None,
    get_operators_module=None,
    suspend_navigation_shot_updates=None,
    resume_navigation_shot_updates=None,
    recoverable_exceptions=None,
    logger=None,
):
    ctx = _coerce_ctx(runtime)
    deps = ctx.deps
    state = ctx.state
    get_earth = get_earth_object if callable(get_earth_object) else deps.get_earth_object
    scene_key_fn = scene_key if callable(scene_key) else deps.scene_key
    get_ops_module = get_operators_module if callable(get_operators_module) else deps.get_operators_module
    suspend_shot_updates = suspend_navigation_shot_updates or deps.suspend_navigation_shot_updates
    resume_shot_updates = resume_navigation_shot_updates or deps.resume_navigation_shot_updates
    recoverable = recoverable_exceptions if recoverable_exceptions is not None else deps.recoverable_exceptions
    runtime_logger = logger if logger is not None else deps.logger
    if scene is None:
        return
    if deps.is_idprop_syncing() or state.nav_camera_control_syncing:
        return
    if int(state.navigation_shot_suspend_count) > 0 or state.navigation_shot_update_reentrant:
        return

    props = getattr(scene, "planetka", None)
    if props is None:
        return

    scene_id = scene_key_fn(scene)
    last_map = state.nav_camera_control_last_signature
    if get_earth() is None:
        last_map.pop(scene_id, None)
        return

    signature = camera_control_sync_signature(scene)
    if signature is None:
        last_map.pop(scene_id, None)
        return
    if int(state.nav_camera_control_sync_suspend_count) > 0:
        last_map[scene_id] = signature
        return
    if last_map.get(scene_id) == signature:
        return

    operators_module = get_ops_module()
    if operators_module is None:
        return
    read_full_globe_lock = getattr(operators_module, "_read_full_globe_tilt_lock", None)
    if callable(read_full_globe_lock):
        try:
            locked, _locked_tilt = read_full_globe_lock(scene)
            if bool(locked):
                last_map[scene_id] = signature
                return
        except recoverable:
            runtime_logger.debug("Planetka Full Globe navigation lock check failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            runtime_logger.debug("Planetka Full Globe navigation lock check failed", exc_info=True)
    is_below_surface = getattr(operators_module, "_is_scene_camera_below_surface", None)
    if callable(is_below_surface):
        try:
            if bool(is_below_surface(scene)):
                last_map[scene_id] = signature
                return
        except recoverable:
            runtime_logger.debug("Planetka camera control surface-state check failed", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            runtime_logger.debug("Planetka camera control surface-state check failed", exc_info=True)
    populate = getattr(operators_module, "_populate_navigation_from_scene_camera", None)
    if not callable(populate):
        return

    state.nav_camera_control_syncing = True
    suspend_shot_updates()
    synced = False
    try:
        synced = bool(populate(scene, props))
    except recoverable:
        runtime_logger.debug("Planetka camera control sync failed", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        runtime_logger.debug("Planetka camera control sync failed", exc_info=True)
    finally:
        resume_shot_updates()
        state.nav_camera_control_syncing = False

    if synced:
        last_map[scene_id] = signature
    else:
        last_map.pop(scene_id, None)
