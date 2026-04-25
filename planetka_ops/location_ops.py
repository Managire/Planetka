import bpy

from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_prefs, read_saved_locations, write_saved_locations
from ..operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from ..state import resume_navigation_shot_updates, suspend_navigation_shot_updates, logger
from .navigation_helpers import _apply_navigation_shot


def _next_saved_location_name(locations):
    used = {str(loc.get("name", "")).strip() for loc in (locations or ()) if isinstance(loc, dict)}
    index = 1
    while True:
        candidate = f"Location {index}"
        if candidate not in used:
            return candidate
        index += 1


def _get_saved_location_by_name(locations, name):
    target = str(name or "")
    for loc in locations or ():
        if not isinstance(loc, dict):
            continue
        if str(loc.get("name", "")) == target:
            return loc
    return None


def save_location_execute(
    operator,
    context,
    *,
    logger,
    get_prefs,
    require_planetka_props,
    read_saved_locations,
    write_saved_locations,
    fail,
    error_code,
    persist_user_preferences,
):
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}
    prefs = get_prefs()
    if prefs is None:
        return fail(
            operator,
            "Planetka preferences not available.",
            code=error_code.RESOLVE_PREFS_MISSING,
            logger=logger,
        )

    locations = read_saved_locations(prefs)
    name = str(getattr(props, "nav_saved_location_name", "") or "").strip()
    if not name:
        name = _next_saved_location_name(locations)

    payload = {
        "name": name,
        "lon": float(getattr(props, "nav_longitude_deg", 0.0)),
        "lat": float(getattr(props, "nav_latitude_deg", 0.0)),
        "alt_km": float(getattr(props, "nav_altitude_km", 0.0)),
    }

    replaced = False
    for index, loc in enumerate(locations):
        if str(loc.get("name", "")) == name:
            locations[index] = payload
            replaced = True
            break
    if not replaced:
        locations.append(payload)

    if not write_saved_locations(prefs, locations):
        return fail(
            operator,
            "Failed to save location.",
            code=error_code.NAV_APPLY_FAILED,
            logger=logger,
        )

    props.nav_saved_location_name = name
    try:
        props.nav_saved_location_id = name
    except (AttributeError, TypeError, ValueError):
        pass

    if not persist_user_preferences():
        operator.report({'WARNING'}, "Location saved for this session only. Save Preferences to persist globally.")

    operator.report({'INFO'}, f"Saved location: {name}")
    return {'FINISHED'}


def load_saved_location_execute(
    operator,
    context,
    *,
    logger,
    get_prefs,
    require_scene,
    require_planetka_props,
    read_saved_locations,
    suspend_navigation_shot_updates,
    resume_navigation_shot_updates,
    apply_navigation_shot,
    fail,
    error_code,
):
    scene = require_scene(operator, context, logger=logger)
    if scene is None:
        return {'CANCELLED'}
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}
    prefs = get_prefs()
    if prefs is None:
        return fail(
            operator,
            "Planetka preferences not available.",
            code=error_code.RESOLVE_PREFS_MISSING,
            logger=logger,
        )

    selected_name = str(getattr(props, "nav_saved_location_id", "") or "")
    if not selected_name or selected_name == "__NONE__":
        return fail(
            operator,
            "No saved location selected.",
            code=error_code.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    locations = read_saved_locations(prefs)
    selected = _get_saved_location_by_name(locations, selected_name)
    if not selected:
        return fail(
            operator,
            f"Saved location not found: {selected_name}",
            code=error_code.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    suspend_navigation_shot_updates()
    try:
        props.nav_longitude_deg = float(selected.get("lon", 0.0))
        props.nav_latitude_deg = float(selected.get("lat", 0.0))
        props.nav_altitude_km = float(selected.get("alt_km", 0.0))
        props.nav_saved_location_name = str(selected.get("name", ""))
    finally:
        resume_navigation_shot_updates()

    try:
        apply_navigation_shot(context, scene, props)
    except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
        return fail(
            operator,
            f"Loaded location but failed to move camera: {exc}",
            code=error_code.NAV_APPLY_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka load-saved-location camera apply failed",
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return fail(
            operator,
            f"Loaded location but failed to move camera: {exc}",
            code=error_code.NAV_APPLY_FAILED,
            logger=logger,
        )

    operator.report({'INFO'}, f"Loaded location: {selected_name}")
    return {'FINISHED'}


def delete_saved_location_execute(
    operator,
    context,
    *,
    logger,
    get_prefs,
    require_planetka_props,
    read_saved_locations,
    write_saved_locations,
    fail,
    error_code,
    persist_user_preferences,
):
    props = require_planetka_props(operator, context, logger=logger)
    if props is None:
        return {'CANCELLED'}
    prefs = get_prefs()
    if prefs is None:
        return fail(
            operator,
            "Planetka preferences not available.",
            code=error_code.RESOLVE_PREFS_MISSING,
            logger=logger,
        )

    selected_name = str(getattr(props, "nav_saved_location_id", "") or "")
    if not selected_name or selected_name == "__NONE__":
        return fail(
            operator,
            "No saved location selected.",
            code=error_code.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    locations = read_saved_locations(prefs)
    filtered = [loc for loc in locations if str(loc.get("name", "")) != selected_name]
    if len(filtered) == len(locations):
        return fail(
            operator,
            f"Saved location not found: {selected_name}",
            code=error_code.NAV_PRECHECK_FAILED,
            logger=logger,
        )

    if not write_saved_locations(prefs, filtered):
        return fail(
            operator,
            "Failed to delete saved location.",
            code=error_code.NAV_APPLY_FAILED,
            logger=logger,
        )

    if filtered:
        fallback_name = str(filtered[0].get("name", ""))
        try:
            props.nav_saved_location_id = fallback_name
        except (AttributeError, TypeError, ValueError):
            pass
    props.nav_saved_location_name = ""
    if not persist_user_preferences():
        operator.report({'WARNING'}, "Deletion saved for this session only. Save Preferences to persist globally.")
    operator.report({'INFO'}, f"Deleted location: {selected_name}")
    return {'FINISHED'}


def _persist_user_preferences():
    return False


class PLANETKA_OT_SaveLocation(bpy.types.Operator):
    bl_idname = "planetka.save_location"
    bl_label = "Save Location"
    bl_description = "Save the current Navigation longitude, latitude, and altitude as a reusable location"

    def execute(self, context):
        return save_location_execute(
            self,
            context,
            logger=logger,
            get_prefs=get_prefs,
            require_planetka_props=require_planetka_props,
            read_saved_locations=read_saved_locations,
            write_saved_locations=write_saved_locations,
            fail=fail,
            error_code=ErrorCode,
            persist_user_preferences=_persist_user_preferences,
        )


class PLANETKA_OT_LoadSavedLocation(bpy.types.Operator):
    bl_idname = "planetka.load_saved_location"
    bl_label = "Load Location"
    bl_description = "Load the selected saved location into Navigation fields and move the camera"

    def execute(self, context):
        return load_saved_location_execute(
            self,
            context,
            logger=logger,
            get_prefs=get_prefs,
            require_scene=require_scene,
            require_planetka_props=require_planetka_props,
            read_saved_locations=read_saved_locations,
            suspend_navigation_shot_updates=suspend_navigation_shot_updates,
            resume_navigation_shot_updates=resume_navigation_shot_updates,
            apply_navigation_shot=_apply_navigation_shot,
            fail=fail,
            error_code=ErrorCode,
        )


class PLANETKA_OT_DeleteSavedLocation(bpy.types.Operator):
    bl_idname = "planetka.delete_saved_location"
    bl_label = "Delete Location"
    bl_description = "Delete the selected saved location from Planetka preferences"

    def execute(self, context):
        return delete_saved_location_execute(
            self,
            context,
            logger=logger,
            get_prefs=get_prefs,
            require_planetka_props=require_planetka_props,
            read_saved_locations=read_saved_locations,
            write_saved_locations=write_saved_locations,
            fail=fail,
            error_code=ErrorCode,
            persist_user_preferences=_persist_user_preferences,
        )
