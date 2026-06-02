import bpy

from ..asset_builder import (
    EARTH_MATERIAL_NAME,
    PLANETKA_ROOT_OBJECT_NAME,
    PREVIEW_MATERIAL_NAME,
    SURFACE_GRADING_GROUP_NAME,
)
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_earth_object
from ..state import (
    _apply_sunlight_from_props,
    _apply_sunlight_strength_from_props,
    _sync_idprops_from_props,
    logger,
    resume_navigation_shot_updates,
    resume_property_update_side_effects,
    suspend_navigation_shot_updates,
    suspend_property_update_side_effects,
)

_STARTUP_PROFILE_PROP_NAMES = (
    "nav_longitude_deg",
    "nav_latitude_deg",
    "nav_altitude_km",
    "nav_azimuth_deg",
    "nav_tilt_deg",
    "nav_roll_deg",
    "nav_focal_length_mm",
    "nav_custom_preset_altitude_km",
    "sunlight_longitude_deg",
    "sunlight_strength",
    "sunlight_seasonal_tilt_deg",
    "earth_radius_bu",
    "show_earth_preview",
    "auto_adjust_clipping_values",
    "texture_quality_mode",
    "anim_camera_preset",
    "anim_frame_start",
    "anim_frame_end",
    "anim_motion_curve",
    "anim_end_altitude_km",
    "anim_orbit_degrees",
    "anim_circle_direction",
    "anim_zoom_rotate_degrees",
    "anim_render_texture_quality_mode",
    "anim_ab_a_location",
    "anim_ab_a_rotation",
    "anim_ab_a_valid",
    "anim_ab_a_capture_frame",
    "anim_ab_a_capture_timecode",
    "anim_ab_b_location",
    "anim_ab_b_rotation",
    "anim_ab_b_valid",
    "anim_ab_b_capture_frame",
    "anim_ab_b_capture_timecode",
)
_STARTUP_PROFILE_FACTORY_PROP_VALUES = {
    "nav_longitude_deg": 15.0,
    "nav_latitude_deg": 46.0,
    "nav_altitude_km": 6000.0,
    "nav_azimuth_deg": 0.0,
    "nav_tilt_deg": 25.0,
    "nav_roll_deg": 0.0,
    "nav_focal_length_mm": 50.0,
    "nav_custom_preset_altitude_km": 6000.0,
    "sunlight_longitude_deg": 70.21390025528626,
    "sunlight_strength": 10.0,
    "sunlight_seasonal_tilt_deg": 23.44,
    "earth_radius_bu": 2.0,
    "show_earth_preview": True,
    "auto_adjust_clipping_values": True,
    "texture_quality_mode": "PREVIEW",
    "anim_camera_preset": "NONE",
    "anim_frame_start": 1,
    "anim_frame_end": 250,
    "anim_motion_curve": "LINEAR",
    "anim_end_altitude_km": 400.0,
    "anim_orbit_degrees": 120.0,
    "anim_circle_direction": "CLOCKWISE",
    "anim_zoom_rotate_degrees": 20.0,
    "anim_render_texture_quality_mode": "FULL",
    "anim_ab_a_location": [0.0, 0.0, 0.0],
    "anim_ab_a_rotation": [0.0, 0.0, 0.0],
    "anim_ab_a_valid": False,
    "anim_ab_a_capture_frame": 0,
    "anim_ab_a_capture_timecode": "",
    "anim_ab_b_location": [0.0, 0.0, 0.0],
    "anim_ab_b_rotation": [0.0, 0.0, 0.0],
    "anim_ab_b_valid": False,
    "anim_ab_b_capture_frame": 0,
    "anim_ab_b_capture_timecode": "",
}
_SURFACE_GRADING_FACTORY_VALUES = {
    "Surface Brightness": 1.0,
    "Surface Saturation": 1.0,
    "Surface Contrast": 1.0,
    "Roughness": 0.4,
    "IOR": 1.333,
    "Hue": 0.5,
    "Saturation": 1.0,
    "Brightness": 0.5,
    "Coefficient": 1.0,
    "Water Texture Strength": 0.5,
    "Intensity": 1.0,
    "Color Temperature": 4500.0,
    "Night Terminator Shift": 0.0,
    "Water Waves On/Off": 0.0,
    "Snow On/Off": 0.0,
    "Snow Line (m)": 3000.0,
    "Waves Density Coefficient": 2.0,
    "Waves Height Coefficient": 0.75,
}
_SURFACE_GRADING_SECTION_SOCKET_NAMES = {
    "GLOBAL": {
        "surface brightness",
        "surface saturation",
        "surface contrast",
    },
    "WATER": {
        "roughness",
        "ior",
        "hue",
        "saturation",
        "brightness",
    },
    "ELEVATION": {
        "coefficient",
    },
    "NIGHT": {
        "intensity",
        "color temperature",
        "night terminator shift",
    },
}
_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY = "planetka_skip_camera_changes_on_create_earth"

try:
    _PLANETKA_RECOVERABLE_TUPLE = tuple(PLANETKA_RECOVERABLE_EXCEPTIONS)
except TypeError:
    _PLANETKA_RECOVERABLE_TUPLE = (PLANETKA_RECOVERABLE_EXCEPTIONS,)

_STARTUP_PROFILE_EXCEPTIONS = _PLANETKA_RECOVERABLE_TUPLE + (
    AttributeError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _profile_value_to_json(value):
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_profile_value_to_json(v) for v in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None



def _property_default_value(owner, prop_name):
    if owner is None or not hasattr(owner, "bl_rna"):
        return None
    try:
        prop = owner.bl_rna.properties.get(prop_name)
    except _STARTUP_PROFILE_EXCEPTIONS:
        prop = None
    if prop is None:
        return None
    try:
        if hasattr(prop, "default_array"):
            arr = tuple(float(v) for v in prop.default_array)
            if arr:
                return arr
    except _STARTUP_PROFILE_EXCEPTIONS:
        pass
    try:
        return prop.default
    except _STARTUP_PROFILE_EXCEPTIONS:
        return None



def _normalize_startup_texture_quality_mode(value):
    token = str(value or "").strip().upper()
    if token not in {"PREVIEW", "BALANCED", "FULL"}:
        token = "PREVIEW"
    return token



def _iter_surface_grading_nodes():
    material_names = (
        str(EARTH_MATERIAL_NAME or "Planetka Earth Material"),
        str(PREVIEW_MATERIAL_NAME or "Planetka Preview Material"),
    )
    out = []
    for material_name in material_names:
        material = bpy.data.materials.get(material_name)
        if material is None or getattr(material, "node_tree", None) is None:
            continue
        nodes = getattr(material.node_tree, "nodes", None)
        if nodes is None:
            continue
        for node in nodes:
            if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                continue
            node_group = getattr(node, "node_tree", None)
            if str(getattr(node_group, "name", "")) == str(SURFACE_GRADING_GROUP_NAME or "Planetka Surface Grading Group"):
                out.append(node)
    return tuple(out)



def _iter_surface_grading_input_sockets(node):
    for socket in getattr(node, "inputs", ()):
        if bool(getattr(socket, "is_linked", False)):
            continue
        if not hasattr(socket, "default_value"):
            continue
        socket_type = str(getattr(socket, "bl_socket_idname", "")).strip()
        if socket_type in {"NodeSocketShader", "NodeSocketVirtual"}:
            continue
        yield socket



def _surface_grading_factory_values():
    defaults = {
        str(name): _profile_value_to_json(value)
        for name, value in _SURFACE_GRADING_FACTORY_VALUES.items()
    }
    return {k: v for k, v in defaults.items() if v is not None}



def _apply_surface_grading_values(values):
    if not isinstance(values, dict) or not values:
        return
    for node in _iter_surface_grading_nodes():
        for socket in _iter_surface_grading_input_sockets(node):
            socket_name = str(getattr(socket, "name", "")).strip()
            if not socket_name or socket_name not in values:
                continue
            raw_value = values.get(socket_name)
            try:
                if isinstance(raw_value, (list, tuple)):
                    socket.default_value = tuple(raw_value)
                else:
                    socket.default_value = raw_value
            except _STARTUP_PROFILE_EXCEPTIONS:
                logger.debug("Planetka: failed applying surface grading default for '%s'", socket_name, exc_info=True)



def _build_factory_startup_setup_profile(scene, props):
    del scene
    profile_props = {}
    for prop_name in _STARTUP_PROFILE_PROP_NAMES:
        if prop_name in _STARTUP_PROFILE_FACTORY_PROP_VALUES:
            default_value = _STARTUP_PROFILE_FACTORY_PROP_VALUES[prop_name]
        else:
            default_value = _property_default_value(props, prop_name)
        encoded = _profile_value_to_json(default_value)
        if encoded is None:
            continue
        profile_props[prop_name] = encoded
    profile_props["texture_quality_mode"] = _normalize_startup_texture_quality_mode(
        profile_props.get("texture_quality_mode", "PREVIEW")
    )
    return {
        "props": profile_props,
        "root": {
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
        },
        "surface_grading": _surface_grading_factory_values(),
    }



def _apply_startup_setup_profile(scene, props, profile, apply_navigation_shot=True):
    if scene is None or props is None or not isinstance(profile, dict):
        return False

    prop_values = profile.get("props")
    if isinstance(prop_values, dict):
        nav_suspended = False
        side_effects_suspended = False
        try:
            suspend_navigation_shot_updates()
            nav_suspended = True
        except _STARTUP_PROFILE_EXCEPTIONS:
            nav_suspended = False
        try:
            suspend_property_update_side_effects()
            side_effects_suspended = True
        except _STARTUP_PROFILE_EXCEPTIONS:
            side_effects_suspended = False

        try:
            for prop_name in _STARTUP_PROFILE_PROP_NAMES:
                if prop_name not in prop_values or not hasattr(props, prop_name):
                    continue
                raw_value = prop_values.get(prop_name)
                try:
                    if isinstance(raw_value, list):
                        setattr(props, prop_name, tuple(raw_value))
                    else:
                        setattr(props, prop_name, raw_value)
                except _STARTUP_PROFILE_EXCEPTIONS:
                    logger.debug("Planetka: failed applying Create Earth default prop '%s'", prop_name, exc_info=True)

            if hasattr(props, "texture_quality_mode"):
                try:
                    desired_mode = _normalize_startup_texture_quality_mode(
                        prop_values.get("texture_quality_mode", "PREVIEW")
                    )
                    props.texture_quality_mode = desired_mode
                except _STARTUP_PROFILE_EXCEPTIONS:
                    logger.debug("Planetka: failed applying Create Earth default texture quality mode", exc_info=True)
        finally:
            if side_effects_suspended:
                try:
                    resume_property_update_side_effects()
                except _STARTUP_PROFILE_EXCEPTIONS:
                    logger.debug("Planetka: failed resuming property update side effects", exc_info=True)

        if nav_suspended:
            try:
                resume_navigation_shot_updates()
            except _STARTUP_PROFILE_EXCEPTIONS:
                logger.debug("Planetka: failed resuming navigation shot updates", exc_info=True)

        scene_camera = getattr(scene, "camera", None) if scene is not None else None
        if (
            bool(apply_navigation_shot)
            and get_earth_object() is not None
            and scene_camera is not None
            and getattr(scene_camera, "type", "") == 'CAMERA'
        ):
            try:
                nav_result = bpy.ops.planetka.navigation_apply_shot(
                    force_camera_view=False,
                )
                if 'FINISHED' not in set(nav_result):
                    logger.debug("Planetka: startup navigation_apply_shot returned %s", nav_result)
            except _PLANETKA_RECOVERABLE_TUPLE:
                logger.debug("Planetka: failed applying startup navigation shot", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed applying startup navigation shot", exc_info=True)

        try:
            _apply_sunlight_from_props(scene)
            _apply_sunlight_strength_from_props(scene)
        except _PLANETKA_RECOVERABLE_TUPLE:
            logger.debug("Planetka: failed applying startup sunlight", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed applying startup sunlight", exc_info=True)

    root_values = profile.get("root")
    if isinstance(root_values, dict):
        root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
        if root is not None:
            location = root_values.get("location")
            rotation = root_values.get("rotation_euler")
            try:
                if isinstance(location, (list, tuple)) and len(location) >= 3:
                    root.location = (float(location[0]), float(location[1]), float(location[2]))
            except _STARTUP_PROFILE_EXCEPTIONS:
                logger.debug("Planetka: failed applying startup root location", exc_info=True)
            try:
                if isinstance(rotation, (list, tuple)) and len(rotation) >= 3:
                    root.rotation_euler = (float(rotation[0]), float(rotation[1]), float(rotation[2]))
            except _STARTUP_PROFILE_EXCEPTIONS:
                logger.debug("Planetka: failed applying startup root rotation", exc_info=True)

    grading_values = profile.get("surface_grading")
    if isinstance(grading_values, dict):
        _apply_surface_grading_values(grading_values)

    try:
        _sync_idprops_from_props(scene)
    except _STARTUP_PROFILE_EXCEPTIONS:
        logger.debug("Planetka: failed syncing Create Earth default idprops", exc_info=True)

    return True



def _apply_startup_setup_for_create_earth(scene, props):
    profile = _build_factory_startup_setup_profile(scene, props)
    apply_navigation_shot = False
    try:
        if bool(scene.get(_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY, False)):
            apply_navigation_shot = False
    except _STARTUP_PROFILE_EXCEPTIONS:
        logger.debug("Planetka: failed reading create-earth camera-skip flag", exc_info=True)

    applied = _apply_startup_setup_profile(
        scene,
        props,
        profile,
        apply_navigation_shot=apply_navigation_shot,
    )
    try:
        if hasattr(props, "anim_camera_preset"):
            props.anim_camera_preset = "NONE"
    except _STARTUP_PROFILE_EXCEPTIONS:
        logger.debug("Planetka: failed forcing animation preset to Select Preset on Create Earth", exc_info=True)
    return applied
