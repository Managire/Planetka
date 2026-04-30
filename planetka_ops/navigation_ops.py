import bpy
import math
from bpy.props import EnumProperty

from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_earth_object
from ..operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from ..state import _is_render_job_active, logger, resume_navigation_shot_updates, suspend_navigation_shot_updates
from .navigation_helpers import (
    _anchor_frame_world,
    _apply_navigation_shot,
    _clear_full_globe_tilt_lock,
    _earth_radius_blender_units,
    _ensure_close_clip_limits,
    _ensure_ortho_full_globe_if_needed,
    _full_globe_altitude_km,
    _max_proximity_altitude_km,
    _navigate_camera_internal,
    _set_full_globe_tilt_lock,
    _switch_viewport_to_camera_view,
    _update_shot_anchor_object,
)


def _module_deps():
    return {
        "require_scene": require_scene,
        "require_planetka_props": require_planetka_props,
        "logger": logger,
        "fail": fail,
        "ErrorCode": ErrorCode,
        "PLANETKA_RECOVERABLE_EXCEPTIONS": PLANETKA_RECOVERABLE_EXCEPTIONS,
        "get_earth_object": get_earth_object,
        "_earth_radius_blender_units": _earth_radius_blender_units,
        "_full_globe_altitude_km": _full_globe_altitude_km,
        "_ensure_ortho_full_globe_if_needed": _ensure_ortho_full_globe_if_needed,
        "_max_proximity_altitude_km": _max_proximity_altitude_km,
        "_navigate_camera_internal": _navigate_camera_internal,
        "_set_full_globe_tilt_lock": _set_full_globe_tilt_lock,
        "_clear_full_globe_tilt_lock": _clear_full_globe_tilt_lock,
        "_anchor_frame_world": _anchor_frame_world,
        "_update_shot_anchor_object": _update_shot_anchor_object,
        "_ensure_close_clip_limits": _ensure_close_clip_limits,
        "_switch_viewport_to_camera_view": _switch_viewport_to_camera_view,
        "_apply_navigation_shot": _apply_navigation_shot,
        "suspend_navigation_shot_updates": suspend_navigation_shot_updates,
        "resume_navigation_shot_updates": resume_navigation_shot_updates,
        "_is_render_job_active": _is_render_job_active,
    }


def _cancel_if_animation_render_active(operator, deps, action_label):
    is_render_job_active = deps.get("_is_render_job_active")
    try:
        if callable(is_render_job_active) and bool(is_render_job_active()):
            label = str(action_label or "This action").strip() or "This action"
            operator.report(
                {'WARNING'},
                f"{label} is unavailable while Final Animation Render is running.",
            )
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return False


def navigation_apply_shot_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    require_planetka_props = deps["require_planetka_props"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = deps["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    _apply_navigation_shot = deps["_apply_navigation_shot"]

    if _cancel_if_animation_render_active(operator, deps, "Navigation apply"):
        return {'CANCELLED'}

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}
    try:
        _apply_navigation_shot(
            context,
            scene,
            props,
            switch_viewport_to_camera=bool(getattr(operator, "force_camera_view", True)),
            sync_active_view_when_not_camera=bool(
                getattr(operator, "sync_active_view_when_not_camera", False)
            ),
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        return fail(
            operator,
            f"Apply Shot failed: {exc}",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka apply-shot failed",
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return fail(
            operator,
            f"Apply Shot failed: {exc}",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
        )

    return {'FINISHED'}


def use_current_view_navigation_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = deps["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    _pick_scene_camera = deps["_pick_scene_camera"]
    _camera_to_current_view = deps["_camera_to_current_view"]
    _compute_current_view_navigation_values = deps["_compute_current_view_navigation_values"]
    _derive_navigation_shot_from_camera = deps["_derive_navigation_shot_from_camera"]
    _quantize_navigation_ui_payload = deps["_quantize_navigation_ui_payload"]
    _store_last_navigation_values = deps["_store_last_navigation_values"]

    if _cancel_if_animation_render_active(operator, deps, "Bring Camera to View"):
        return {'CANCELLED'}

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}

    camera = _pick_scene_camera(scene, context=context)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return fail(
            operator,
            "No active camera found. Select a camera (or add one) and retry.",
            code=ErrorCode.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    try:
        moved_camera = bool(_camera_to_current_view(scene))
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        return fail(
            operator,
            f"Bring Camera to View failed: {exc}",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka bring_camera_to_view failed",
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return fail(
            operator,
            f"Bring Camera to View failed: {exc}",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
        )

    props = getattr(scene, "planetka", None)
    if props is None:
        if moved_camera:
            operator.report({'INFO'}, "Camera brought to current view.")
        else:
            operator.report({'INFO'}, "Camera is already in current view.")
        return {'FINISHED'}

    computed = _compute_current_view_navigation_values(scene)
    if computed is None:
        operator.report(
            {'WARNING'},
            "Camera updated, but Planetka controls were not synced (Earth is not visible in current view).",
        )
        return {'FINISHED'}
    lat, lon, _alt_km = computed

    try:
        derived = _derive_navigation_shot_from_camera(scene, lon, lat)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        operator.report({'WARNING'}, f"Camera updated, but Planetka controls were not synced: {exc}")
        return {'FINISHED'}
    except (RuntimeError, TypeError, ValueError) as exc:
        operator.report({'WARNING'}, f"Camera updated, but Planetka controls were not synced: {exc}")
        return {'FINISHED'}

    try:
        camera_data = getattr(camera, "data", None)
        quantized = _quantize_navigation_ui_payload(
            lat_deg=float(lat),
            lon_deg=float(lon),
            altitude_km=float(derived.get("altitude_km", 0.0)),
            heading_deg=float(derived.get("azimuth_deg", 0.0)),
            tilt_deg=float(derived.get("tilt_deg", 0.0)),
            roll_deg=float(derived.get("roll_deg", 0.0)),
            focal_length_mm=float(getattr(camera_data, "lens", 50.0)) if camera_data is not None else float(getattr(props, "nav_focal_length_mm", 50.0)),
        )
        props.nav_latitude_deg = float(quantized["lat_deg"])
        props.nav_longitude_deg = float(quantized["lon_deg"])
        props.nav_altitude_km = float(quantized["altitude_km"])
        props.nav_azimuth_deg = float(quantized["heading_deg"])
        props.nav_tilt_deg = float(quantized["tilt_deg"])
        props.nav_roll_deg = float(quantized["roll_deg"])
        if camera_data is not None:
            props.nav_focal_length_mm = float(quantized["focal_length_mm"])
        _store_last_navigation_values(
            scene,
            lon_deg=float(props.nav_longitude_deg),
            lat_deg=float(props.nav_latitude_deg),
            altitude_km=float(props.nav_altitude_km),
            heading_deg=float(props.nav_azimuth_deg),
            tilt_deg=float(props.nav_tilt_deg),
            roll_deg=float(props.nav_roll_deg),
        )
    except (AttributeError, TypeError, ValueError):
        operator.report({'WARNING'}, "Camera updated, but Planetka controls failed to update.")
        return {'FINISHED'}

    if moved_camera:
        operator.report({'INFO'}, "Camera and Navigation fields updated from current view.")
    else:
        operator.report({'INFO'}, "Camera is already in current view. Navigation fields synced.")
    return {'FINISHED'}


def auto_adjust_clipping_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    logger = deps["logger"]
    get_earth_object = deps["get_earth_object"]
    _earth_radius_blender_units = deps["_earth_radius_blender_units"]

    if _cancel_if_animation_render_active(operator, deps, "Clipping adjustment"):
        return {'CANCELLED'}

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}

    earth_obj = get_earth_object()
    if earth_obj is None:
        operator.report({'WARNING'}, "Create Earth first, then adjust clipping.")
        return {'CANCELLED'}

    try:
        earth_center = earth_obj.matrix_world.translation.copy()
        earth_radius = float(_earth_radius_blender_units(earth_obj))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        operator.report({'WARNING'}, "Unable to evaluate Earth radius for clipping adjustment.")
        return {'CANCELLED'}

    if earth_radius <= 0.0:
        operator.report({'WARNING'}, "Earth radius is invalid for clipping adjustment.")
        return {'CANCELLED'}

    mode = "CAMERA"
    clip_owner = None
    probe_pos = None

    space = getattr(context, "space_data", None)
    rv3d = getattr(space, "region_3d", None) if space is not None else None
    is_view3d = bool(space is not None and str(getattr(space, "type", "")) == "VIEW_3D")
    in_camera_view = bool(rv3d is not None and str(getattr(rv3d, "view_perspective", "")) == "CAMERA")

    if is_view3d and not in_camera_view and rv3d is not None:
        try:
            view_matrix = rv3d.view_matrix.inverted()
            probe_pos = view_matrix.translation.copy()
            clip_owner = space
            mode = "VIEWPORT"
        except (AttributeError, RuntimeError, TypeError, ValueError):
            clip_owner = None
            probe_pos = None

    if clip_owner is None or probe_pos is None:
        camera = getattr(scene, "camera", None)
        camera_data = getattr(camera, "data", None) if camera is not None else None
        if camera is None or str(getattr(camera, "type", "")) != "CAMERA" or camera_data is None:
            operator.report({'WARNING'}, "Active camera not found for clipping adjustment.")
            return {'CANCELLED'}
        try:
            probe_pos = camera.matrix_world.translation.copy()
            clip_owner = camera_data
            mode = "CAMERA"
        except (AttributeError, RuntimeError, TypeError, ValueError):
            operator.report({'WARNING'}, "Unable to read camera clipping values.")
            return {'CANCELLED'}

    try:
        clip_start = float(getattr(clip_owner, "clip_start", 0.0))
        clip_end = float(getattr(clip_owner, "clip_end", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        operator.report({'WARNING'}, "Unable to read clipping values.")
        return {'CANCELLED'}

    if clip_start <= 0.0 or clip_end <= 0.0:
        operator.report({'WARNING'}, "Clipping values must be positive.")
        return {'CANCELLED'}

    try:
        proximity_bu = float((probe_pos - earth_center).length) - float(earth_radius)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        operator.report({'WARNING'}, "Unable to evaluate camera proximity for clipping adjustment.")
        return {'CANCELLED'}

    breach_min = bool(proximity_bu < clip_start)
    breach_max = bool(proximity_bu > clip_end)
    if not breach_min and not breach_max:
        operator.report({'INFO'}, "Clipping is already within range.")
        return {'CANCELLED'}

    new_start = float(clip_start)
    new_end = float(clip_end)

    if breach_min:
        new_start = max(1e-9, float(clip_start) / 10.0)
    if breach_max:
        new_end = max(new_start * 1.000001, float(clip_end) * 10.0)

    if new_end <= new_start:
        new_end = max(new_start * 10.0, new_start + 1e-9)

    max_ratio = 10_000_000.0
    ratio = float(new_end) / max(float(new_start), 1e-9)
    if ratio > max_ratio:
        if breach_max and not breach_min:
            new_start = max(1e-9, float(new_end) / max_ratio)
        else:
            new_end = float(new_start) * max_ratio

    try:
        clip_owner.clip_start = float(new_start)
        clip_owner.clip_end = float(new_end)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        operator.report({'WARNING'}, "Failed applying clipping changes.")
        return {'CANCELLED'}

    target_label = "Viewport" if mode == "VIEWPORT" else "Camera"
    operator.report(
        {'INFO'},
        f"{target_label} clipping adjusted (start={new_start:.6g}, end={new_end:.6g}).",
    )
    return {'FINISHED'}


def navigation_preset_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    require_planetka_props = deps["require_planetka_props"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    get_earth_object = deps["get_earth_object"]
    _earth_radius_blender_units = deps["_earth_radius_blender_units"]
    _full_globe_altitude_km = deps["_full_globe_altitude_km"]
    _ensure_ortho_full_globe_if_needed = deps["_ensure_ortho_full_globe_if_needed"]
    _max_proximity_altitude_km = deps["_max_proximity_altitude_km"]
    _set_full_globe_tilt_lock = deps["_set_full_globe_tilt_lock"]
    _clear_full_globe_tilt_lock = deps["_clear_full_globe_tilt_lock"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = deps["PLANETKA_RECOVERABLE_EXCEPTIONS"]
    _navigate_camera_internal = deps["_navigate_camera_internal"]
    _anchor_frame_world = deps["_anchor_frame_world"]
    _update_shot_anchor_object = deps["_update_shot_anchor_object"]
    _ensure_close_clip_limits = deps["_ensure_close_clip_limits"]
    _switch_viewport_to_camera_view = deps["_switch_viewport_to_camera_view"]
    _apply_navigation_shot = deps["_apply_navigation_shot"]
    suspend_navigation_shot_updates = deps["suspend_navigation_shot_updates"]
    resume_navigation_shot_updates = deps["resume_navigation_shot_updates"]

    if _cancel_if_animation_render_active(operator, deps, "Navigation preset"):
        return {'CANCELLED'}

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}

    earth_obj = get_earth_object()
    if earth_obj is None:
        return fail(
            operator,
            "Create Earth first, then use Navigation presets.",
            code=ErrorCode.NAV_PRECHECK_FAILED,
            logger=logger,
        )
    if getattr(scene, "camera", None) is None:
        return fail(
            operator,
            "Scene camera is missing. Set an active camera and retry.",
            code=ErrorCode.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    earth_radius_bu = _earth_radius_blender_units(earth_obj)
    preset = str(getattr(operator, "preset", "ISS_ORBIT"))
    nav_updates_suspended = False
    try:
        suspend_navigation_shot_updates()
        nav_updates_suspended = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        nav_updates_suspended = False
    try:
        if preset == "ISS_ORBIT":
            _clear_full_globe_tilt_lock(scene)
            props.nav_altitude_km = 400.0
        elif preset == "SENTINEL2":
            _clear_full_globe_tilt_lock(scene)
            props.nav_altitude_km = 786.0
        elif preset == "HIGH_ORBIT":
            _set_full_globe_tilt_lock(scene, float(getattr(props, "nav_tilt_deg", 0.0)))
            full_globe_km = _full_globe_altitude_km(scene, earth_radius_bu)
            if full_globe_km is not None:
                props.nav_altitude_km = max(0.0, float(full_globe_km))
            ortho_adjusted = _ensure_ortho_full_globe_if_needed(scene, earth_radius_bu)
            if ortho_adjusted:
                operator.report({'INFO'}, "Orthographic scale expanded to fit full globe with margin.")
        elif preset == "MAX_PROXIMITY":
            _clear_full_globe_tilt_lock(scene)
            lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
            lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
            max_km, note = _max_proximity_altitude_km(scene, earth_obj, earth_radius_bu, lon_deg, lat_deg)
            if max_km is None:
                return fail(
                    operator,
                    "Unable to compute Max Proximity for current camera.",
                    code=ErrorCode.NAV_PRECHECK_FAILED,
                    logger=logger,
                )
            props.nav_altitude_km = max(0.0, float(max_km))
            if note:
                operator.report({'INFO'}, note)
        else:
            return fail(
                operator,
                f"Unknown navigation preset: {preset}",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
    finally:
        if nav_updates_suspended:
            try:
                resume_navigation_shot_updates()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass

    try:
        if preset == "HIGH_ORBIT":
            lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
            lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
            altitude_km = float(getattr(props, "nav_altitude_km", 0.0))
            _navigate_camera_internal(
                scene,
                lon_deg,
                lat_deg,
                altitude_km,
                look_at_center=True,
            )
            earth_obj = get_earth_object()
            if earth_obj is not None:
                anchor_world, east_world, north_world, up_world, _radius = _anchor_frame_world(
                    earth_obj,
                    lon_deg,
                    lat_deg,
                )
                _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)
            _ensure_close_clip_limits(scene, min_clip=0.001)
            _switch_viewport_to_camera_view(context, scene)
        else:
            _apply_navigation_shot(context, scene, props)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        return fail(
            operator,
            f"Navigation preset apply failed: {exc}",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka navigation preset apply failed",
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return fail(
            operator,
            f"Navigation preset apply failed: {exc}",
            code=ErrorCode.NAV_APPLY_FAILED,
            logger=logger,
        )

    if preset == "HIGH_ORBIT":
        preset_label = "Full Globe"
    elif preset == "SENTINEL2":
        preset_label = "ESA Sentinel-2"
    elif preset == "ISS_ORBIT":
        preset_label = "ISS Orbit"
    elif preset == "MAX_PROXIMITY":
        preset_label = "Max Proximity"
    else:
        preset_label = preset.replace('_', ' ').title()
    operator.report({'INFO'}, f"Navigation preset applied: {preset_label}.")
    return {'FINISHED'}


def sunlight_preset_execute(operator, context, deps):
    require_scene = deps["require_scene"]
    require_planetka_props = deps["require_planetka_props"]
    logger = deps["logger"]
    fail = deps["fail"]
    ErrorCode = deps["ErrorCode"]
    get_earth_object = deps["get_earth_object"]
    _anchor_frame_world = deps["_anchor_frame_world"]
    PLANETKA_RECOVERABLE_EXCEPTIONS = deps["PLANETKA_RECOVERABLE_EXCEPTIONS"]

    if _cancel_if_animation_render_active(operator, deps, "Sunlight preset"):
        return {'CANCELLED'}

    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}

    earth_obj = get_earth_object()
    if earth_obj is None:
        return fail(
            operator,
            "Create Earth first, then use Sunlight presets.",
            code=ErrorCode.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    preset = str(getattr(operator, "preset", "NOON") or "NOON").strip().upper()
    lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
    lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
    _anchor, east, north, up, _radius = _anchor_frame_world(earth_obj, lon_deg, lat_deg)
    west = -east
    south = -north

    if preset == "NOON":
        sun_dir = up
    elif preset == "NIGHT":
        sun_dir = -up
    else:
        elev_deg = {
            "DAWN": 0.0,
            "SUNRISE": 8.0,
            "EARLY_MORNING": 22.0,
            "MID_MORNING": 38.0,
            "MID_AFTERNOON": 38.0,
            "LATE_AFTERNOON": 22.0,
            "SUNSET": 8.0,
            "DUSK": 0.0,
        }.get(preset, 45.0)
        if preset == "DUSK":
            elev_deg = 0.0
        elif preset == "DAWN":
            elev_deg = 0.0
        elif preset == "SUNSET":
            elev_deg = 8.0
        elif preset == "SUNRISE":
            elev_deg = 8.0
        elif preset == "EARLY_MORNING":
            elev_deg = 22.0
        elif preset == "LATE_AFTERNOON":
            elev_deg = 22.0
        elif preset == "MID_MORNING":
            elev_deg = 38.0
        elif preset == "MID_AFTERNOON":
            elev_deg = 38.0
        else:
            elev_deg = 45.0

        horiz = east if preset in {"DAWN", "SUNRISE", "EARLY_MORNING", "MID_MORNING"} else west
        elev = math.radians(elev_deg)
        sun_dir = (horiz * math.cos(elev)) + (up * math.sin(elev))
        if sun_dir.length < 1e-9:
            sun_dir = up
        sun_dir.normalize()

    try:
        sun_lon = math.degrees(math.atan2(float(sun_dir.y), float(sun_dir.x)))
        sun_lat = math.degrees(math.asin(max(-1.0, min(1.0, float(sun_dir.z)))))
        sun_lat = max(-23.5, min(23.5, float(sun_lat)))
        props.sunlight_longitude_deg = float(sun_lon)
        props.sunlight_seasonal_tilt_deg = float(sun_lat)
        props.sunlight_last_preset = preset
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed setting sunlight preset properties", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed setting sunlight preset properties", exc_info=True)

    operator.report({'INFO'}, f"Sunlight preset applied: {preset.replace('_', ' ').title()}.")
    return {'FINISHED'}


class PLANETKA_OT_NavigationPreset(bpy.types.Operator):
    bl_idname = "planetka.navigation_preset"
    bl_label = "Set Navigation Preset"
    bl_description = "Apply a Navigation altitude preset and update camera placement for the current location"

    preset: EnumProperty(
        name="Preset",
        items=(
            ("MAX_PROXIMITY", "Max Proximity", "Closest altitude near texture quality limit (Caution target)"),
            ("ISS_ORBIT", "ISS Orbit", "Set altitude to 400 km"),
            ("SENTINEL2", "ESA Sentinel-2", "Set altitude to 786 km (Sentinel-2 nominal orbit)"),
            ("HIGH_ORBIT", "Full Globe", "Fit full Earth with room around edges"),
        ),
        default="ISS_ORBIT",
    )

    def execute(self, context):
        return navigation_preset_execute(self, context, _module_deps())


class PLANETKA_OT_SunlightPreset(bpy.types.Operator):
    bl_idname = "planetka.sunlight_preset"
    bl_label = "Sunlight Preset"
    bl_description = (
        "Set Planetka Sunlight using common lighting presets around the current location "
        "(seasonal tilt is clamped to ±23.5°)"
    )

    preset: EnumProperty(
        name="Preset",
        items=(
            ("DAWN", "Dawn", ""),
            ("SUNRISE", "Sunrise", ""),
            ("EARLY_MORNING", "Early Morning", ""),
            ("SUNSET", "Sunset", ""),
            ("MID_MORNING", "Mid-morning", ""),
            ("MID_AFTERNOON", "Mid-afternoon", ""),
            ("LATE_AFTERNOON", "Late Afternoon", ""),
            ("NOON", "Noon", ""),
            ("DUSK", "Dusk", ""),
            ("NIGHT", "Night", ""),
        ),
        default="NOON",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        return sunlight_preset_execute(self, context, _module_deps())
