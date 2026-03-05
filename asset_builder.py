import io
import logging
import math
import os
import tempfile

import bpy
import bmesh

from .embedded_material_library import (
    MATERIAL_LIBRARY_MATERIALS,
    MATERIAL_LIBRARY_NODE_GROUPS,
    MATERIAL_LIBRARY_SHA256,
    get_material_library_bytes,
)
from .extension_prefs import get_earth_object
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)

SURFACE_COLLECTION_NAME = "Planetka - Earth Surface Collection"
PREVIEW_MATERIAL_NAME = "Planetka Preview Material"
LEGACY_PREVIEW_MATERIAL_NAME = "Planetka Preview Shader"
EARTH_MATERIAL_NAME = "Planetka Earth Material"
SURFACE_GRADING_GROUP_NAME = "Planetka Surface Grading Group"
TEXTURE_LOADING_GROUP_NAME = "Planetka Textures Loading Group"
PREVIEW_TEXTURE_LOADING_GROUP_NAME = "Planetka Preview Textures Loading Group"
NIGHTDAY_GROUP_NAME = "Planetka NightDay Transition Group"
SUNLIGHT_OBJECT_NAME = "Planetka Sunlight"
DEFAULT_ELEVATION_COEFFICIENT = 1.0
ELEVATION_SCALE_MULTIPLIER = 0.012
_LIBRARY_SIGNATURE_KEY = "planetka_embedded_material_sha256"
_PREVIEW_TEXTURE_GROUP_VERSION_KEY = "planetka_preview_texture_group_v"
_PREVIEW_TEXTURE_GROUP_VERSION = 1
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_LEGACY_LIBRARY_RELATIVE_PATH = ("Resources", "planetka_material_lib_45.blend")
_SURFACE_DETAIL_VERSION_KEY = "planetka_surface_detail_v"
_SURFACE_DETAIL_VERSION = 1
_SURFACE_FAKE_ATMOSPHERE_VERSION_KEY = "planetka_surface_fake_atmosphere_v"
_SURFACE_FAKE_ATMOSPHERE_VERSION = 1
_SURFACE_SHADER_UPDATE_VERSION_KEY = "planetka_surface_shader_update_v"
_SURFACE_SHADER_UPDATE_VERSION = 2
ATMOSPHERE_GRADING_GROUP_NAME = "Planetka Atmosphere Grading Group"
ATMOSPHERE_SHELL_OBJECT_NAME = "Planetka Atmosphere Shell"
ATMOSPHERE_SHELL_MESH_NAME = "Planetka Atmosphere Shell Mesh"
ATMOSPHERE_SHELL_MATERIAL_NAME = "Planetka Atmosphere Shell Material"
ATMOSPHERE_SHELL_SHADING_GROUP_NAME = "Planetka Atmosphere Shell Shading Group"
ATMOSPHERE_SHELL_MESH_VERSION_KEY = "planetka_atmosphere_shell_mesh_v"
ATMOSPHERE_SHELL_MESH_VERSION = 2
ATMOSPHERE_SHELL_MATERIAL_VERSION_KEY = "planetka_atmosphere_shell_material_v"
ATMOSPHERE_SHELL_MATERIAL_VERSION = 12

_DETAIL_SOCKET_SCALE = "Procedural Detail Scale"
_DETAIL_SOCKET_FOREST = "Forest Detail Strength"
_DETAIL_SOCKET_ROCK = "Rock Detail Strength"
_DETAIL_SOCKET_ROCK_COLOR = "Rock Color Variation"
_DETAIL_SOCKET_MICRO_DISP = "Micro Displacement Strength"
_FAKE_ATMOSPHERE_DENSITY_SOCKET = "Atmosphere Density"
_FAKE_ATMOSPHERE_DENSITY_SOCKET_LEGACY = "Fake Atmosphere Density"
_FAKE_ATMOSPHERE_HEIGHT_SOCKET = "Fake Atmosphere Height (km)"
_FAKE_ATMOSPHERE_FALLOFF_SOCKET = "Atmosphere Exponential Falloff"
_FAKE_ATMOSPHERE_COLOR_SOCKET = "Atmosphere Color"
_FAKE_ATMOSPHERE_DENSITY_UI_TO_SHADER = 0.25
# Linear-space RGBA that displays as sRGB #8CB2E3FF in Blender color UI.
_FAKE_ATMOSPHERE_DEFAULT_COLOR = (0.26225066, 0.44520119, 0.76815115, 1.0)

_SURFACE_DEFAULT_INPUT_SPECS = (
    ("Surface Brightness", 3.0, 0.0, 10.0),
    ("Surface Saturation", 1.1, 0.0, 5.0),
    ("Roughness", 0.25, 0.0, 1.0),
    ("IOR", 1.333, 0.0, 3.0),
    ("Saturation", 1.0, 0.0, 2.0),
    ("Water Texture Strength", 0.5, 0.0, 1.0),
    ("Intensity", 1.0, 0.0, 10.0),
)

_SURFACE_EXTRA_INPUT_SPECS = (
    ("Water Waves On/Off", 0.0, 0.0, 1.0),
    ("Snow On/Off", 0.0, 0.0, 1.0),
    ("Snow Line (m)", 3000.0, 0.0, 100000.0),
    ("Waves Density Coefficient", 2.0, 0.0, 10.0),
    ("Waves Height Coefficient", 0.75, 0.0, 10.0),
)
_SURFACE_PANEL_EXTRA = "Extra"
_SURFACE_PANEL_SNOW = "Snow"
_SURFACE_PANEL_WAVES = "Waves"
_SURFACE_PANEL_ATMOSPHERE = "Atmosphere"
_SHADER_INPUT_DESCRIPTIONS = {
    "Surface Brightness": "Multiplier for land/base-color brightness before final shading.",
    "Surface Saturation": "Multiplier for land/base-color saturation.",
    "Roughness": "Base surface roughness (0 = mirror-like, 1 = fully diffuse).",
    "IOR": "Index of refraction used by water/specular shading.",
    "Saturation": "Water color saturation adjustment.",
    "Water Texture Strength": "Blend strength of water texture detail.",
    "Intensity": "Night-lights emission intensity multiplier.",
    "Water Waves On/Off": "Enable procedural ocean-wave contribution (0 = off, 1 = on).",
    "Snow On/Off": "Enable snow coverage contribution (0 = off, 1 = on).",
    "Snow Line (m)": "Altitude threshold for snow coverage in meters.",
    "Waves Density Coefficient": "Controls ocean wave frequency/detail density.",
    "Waves Height Coefficient": "Controls ocean wave height amplitude.",
    "Procedural Detail Scale": "Global scale of procedural land detail patterns.",
    "Forest Detail Strength": "Strength of procedural forest-like micro detail.",
    "Rock Detail Strength": "Strength of procedural rocky micro detail.",
    "Rock Color Variation": "Amount of procedural rock color variation.",
    "Micro Displacement Strength": "Additional micro displacement amplitude from procedural detail.",
    "Atmosphere Density": "Overall strength of atmospheric haze and rim glow.",
    "Fake Atmosphere Height (km)": "Effective haze height in kilometers.",
    "Atmosphere Exponential Falloff": "Atmosphere falloff curve (0 = linear, 1 = strongly exponential).",
    "Atmosphere Color": "Tint color for atmospheric haze and rim glow.",
}

_STATIC_IMAGE_SPECS = {
    "S2_x000_y000_z360_d360.exr": {
        "relative_path": ("Resources", "Basic Textures", "S2_x000_y000_z360_d360.exr"),
        "colorspace": "Linear Rec.709",
        "alpha_mode": "PREMUL",
    },
    "EL_x000_y000_z360_d360.exr": {
        "relative_path": ("Resources", "Basic Textures", "EL_x000_y000_z360_d360.exr"),
        "colorspace": "Non-Color",
        "alpha_mode": "PREMUL",
    },
    "WT_x000_y000_z360_d360.exr": {
        "relative_path": ("Resources", "Basic Textures", "WT_x000_y000_z360_d360.exr"),
        "colorspace": "Linear Rec.709",
        "alpha_mode": "PREMUL",
    },
    "PO_x000_y000_z360_d360.tif": {
        "relative_path": ("Resources", "Basic Textures", "PO_x000_y000_z360_d360.tif"),
        "colorspace": "sRGB",
        "alpha_mode": "STRAIGHT",
    },
    "WF_x000_y000_z360_d360.exr": {
        "relative_path": ("Resources", "Basic Textures", "WF_x000_y000_z360_d360.exr"),
        "colorspace": "Linear Rec.709",
        "alpha_mode": "PREMUL",
    },
    "ocean_pixel_final_20.exr": {
        "relative_path": ("Resources", "Fallback Images", "ocean_pixel_final_20.exr"),
        "colorspace": "Linear Rec.709",
        "alpha_mode": "PREMUL",
    },
    "blue_pixel_20.exr": {
        "relative_path": ("Resources", "Fallback Images", "blue_pixel_20.exr"),
        "colorspace": "Linear Rec.709",
        "alpha_mode": "PREMUL",
    },
}

_PREVIEW_IMAGE_BINDINGS = (
    ("Image Texture", "S2_x000_y000_z360_d360.exr"),
    ("Image Texture.001", "EL_x000_y000_z360_d360.exr"),
    ("Image Texture.002", "WT_x000_y000_z360_d360.exr"),
    ("Image Texture.003", "PO_x000_y000_z360_d360.tif"),
)

_SURFACE_GROUP_IMAGE_BINDINGS = (
    ("Image Texture", "ocean_pixel_final_20.exr"),
    ("Image Texture.001", "blue_pixel_20.exr"),
    ("Image Texture.002", "WF_x000_y000_z360_d360.exr"),
)


def _normalize_surface_elevation_defaults(material):
    if material is None or not getattr(material, "use_nodes", False):
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return

    surface_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if surface_group and getattr(surface_group, "nodes", None):
        scale_node = surface_group.nodes.get("Math.011")
        if scale_node and getattr(scale_node, "bl_idname", "") == "ShaderNodeMath":
            try:
                scale_node.inputs[1].default_value = float(ELEVATION_SCALE_MULTIPLIER)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, TypeError, ValueError, IndexError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    surface_nodes = [
        node
        for node in node_tree.nodes
        if getattr(node, "bl_idname", "") == "ShaderNodeGroup"
        and getattr(getattr(node, "node_tree", None), "name", "") == SURFACE_GRADING_GROUP_NAME
    ]
    for node in surface_nodes:
        coeff_socket = None
        try:
            coeff_socket = node.inputs.get("Coefficient")
        except (AttributeError, TypeError, ValueError):
            coeff_socket = None
        if coeff_socket is None:
            continue
        try:
            current = float(coeff_socket.default_value)
        except (AttributeError, TypeError, ValueError):
            continue
        # Keep custom user edits untouched; normalize known defaults to 1.0.
        if (
            abs(current - 1.0) <= 1e-6
            or abs(current - 0.905) <= 1e-6
            or abs(current - 0.83335673) <= 1e-6
            or abs(current - 0.41667837) <= 1e-6
        ):
            try:
                coeff_socket.default_value = float(DEFAULT_ELEVATION_COEFFICIENT)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, TypeError, ValueError):
                continue


def _ensure_interface_float_socket(node_group, name, *, default, min_value=0.0, max_value=1.0, description=""):
    if node_group is None:
        return None
    interface = getattr(node_group, "interface", None)
    items = getattr(interface, "items_tree", None) if interface else None
    if items is None:
        return None

    existing = None
    for item in items:
        if getattr(item, "item_type", None) != "SOCKET":
            continue
        if getattr(item, "in_out", None) != "INPUT":
            continue
        if str(getattr(item, "name", "")) == str(name):
            existing = item
            break

    if existing is None:
        try:
            existing = interface.new_socket(name=str(name), in_out="INPUT", socket_type="NodeSocketFloat")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        except (AttributeError, TypeError, ValueError):
            return None

    for attr, value in (
        ("default_value", default),
        ("min_value", min_value),
        ("max_value", max_value),
    ):
        if hasattr(existing, attr):
            try:
                setattr(existing, attr, float(value))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if description and hasattr(existing, "description"):
        try:
            existing.description = str(description)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    return existing


def _ensure_interface_socket(node_group, name, *, in_out, socket_type, description=""):
    if node_group is None:
        return None
    interface = getattr(node_group, "interface", None)
    items = getattr(interface, "items_tree", None) if interface else None
    if items is None:
        return None

    existing = None
    for item in items:
        if getattr(item, "item_type", None) != "SOCKET":
            continue
        if str(getattr(item, "in_out", "")) != str(in_out):
            continue
        if str(getattr(item, "name", "")) == str(name):
            existing = item
            break
    if existing is not None:
        if description and hasattr(existing, "description"):
            try:
                existing.description = str(description)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        return existing

    try:
        created = interface.new_socket(name=str(name), in_out=str(in_out), socket_type=str(socket_type))
        if description and hasattr(created, "description"):
            try:
                created.description = str(description)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        return created
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return None
    except (AttributeError, TypeError, ValueError):
        return None


def _ensure_node(nodes, name, bl_idname):
    if nodes is None:
        return None
    node = nodes.get(name)
    if node is not None and str(getattr(node, "bl_idname", "")) != str(bl_idname):
        try:
            nodes.remove(node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        node = None
    if node is None:
        try:
            node = nodes.new(bl_idname)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        except (RuntimeError, TypeError, ValueError):
            return None
        node.name = name
    return node


def _safe_setattr(obj, name, value):
    if obj is None or not hasattr(obj, name):
        return
    try:
        setattr(obj, name, value)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _safe_set_node_location(node, x, y):
    if node is None:
        return
    try:
        node.location = (float(x), float(y))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _replace_input_link(links, to_socket, from_socket):
    if links is None or to_socket is None or from_socket is None:
        return
    try:
        for link in list(getattr(to_socket, "links", ())):
            links.remove(link)
        links.new(from_socket, to_socket)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _socket_by_name_or_index(sockets, name, fallback_index=None):
    if sockets is None:
        return None
    socket = sockets.get(name) if hasattr(sockets, "get") else None
    if socket is not None:
        return socket
    if fallback_index is None:
        return None
    try:
        if len(sockets) > int(fallback_index):
            return sockets[int(fallback_index)]
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        return None
    return None


def _socket_output_by_name_or_index(sockets, name, fallback_index=0):
    return _socket_by_name_or_index(sockets, name, fallback_index)


def _socket_input_by_name_or_index(sockets, name, fallback_index=None):
    return _socket_by_name_or_index(sockets, name, fallback_index)


def _ensure_planetka_atmosphere_grading_group():
    group = bpy.data.node_groups.get(ATMOSPHERE_GRADING_GROUP_NAME)
    if group is None:
        try:
            group = bpy.data.node_groups.new(ATMOSPHERE_GRADING_GROUP_NAME, "ShaderNodeTree")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        except (RuntimeError, TypeError, ValueError):
            return None

    _remove_interface_input_socket(group, _FAKE_ATMOSPHERE_DENSITY_SOCKET_LEGACY)

    _ensure_interface_socket(group, "Base Color", in_out="INPUT", socket_type="NodeSocketColor")
    _ensure_interface_socket(group, "EL", in_out="INPUT", socket_type="NodeSocketColor")
    density_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_DENSITY_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_DENSITY_SOCKET, ""),
    )
    height_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_HEIGHT_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_HEIGHT_SOCKET, ""),
    )
    falloff_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_FALLOFF_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_FALLOFF_SOCKET, ""),
    )
    color_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_COLOR_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketColor",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_COLOR_SOCKET, ""),
    )
    _ensure_interface_socket(group, "Color", in_out="OUTPUT", socket_type="NodeSocketColor")

    if density_item and hasattr(density_item, "default_value"):
        try:
            density_item.default_value = 0.0
            density_item.min_value = 0.0
            density_item.max_value = 2.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if height_item and hasattr(height_item, "default_value"):
        try:
            height_item.default_value = 50.0
            height_item.min_value = 0.0
            height_item.max_value = 400.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if falloff_item and hasattr(falloff_item, "default_value"):
        try:
            falloff_item.default_value = 0.05
            falloff_item.min_value = 0.0
            falloff_item.max_value = 1.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if color_item and hasattr(color_item, "default_value"):
        try:
            color_item.default_value = _FAKE_ATMOSPHERE_DEFAULT_COLOR
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    nodes = group.nodes
    links = group.links
    group_input = _ensure_node(nodes, "Group Input", "NodeGroupInput")
    group_output = _ensure_node(nodes, "Group Output", "NodeGroupOutput")
    if group_input is None or group_output is None:
        return group

    haze_mix = _ensure_node(nodes, "PKA Atmo Color Mix", "ShaderNodeMix")
    camera_data = _ensure_node(nodes, "PKA Atmo Camera Data", "ShaderNodeCameraData")
    distance_range = _ensure_node(nodes, "PKA Atmo Distance", "ShaderNodeMapRange")
    layer_weight = _ensure_node(nodes, "PKA Atmo Layer Weight", "ShaderNodeLayerWeight")
    horizon_invert = _ensure_node(nodes, "PKA Atmo Horizon Invert", "ShaderNodeMath")
    height_range = _ensure_node(nodes, "PKA Atmo Height Range", "ShaderNodeMapRange")
    horizon_height = _ensure_node(nodes, "PKA Atmo Horizon Height", "ShaderNodeMath")
    distance_horizon = _ensure_node(nodes, "PKA Atmo Distance Horizon", "ShaderNodeMath")
    el_separate = _ensure_node(nodes, "PKA Atmo Elevation Separate", "ShaderNodeSeparateColor")
    elevation_mask = _ensure_node(nodes, "PKA Atmo Elevation Mask", "ShaderNodeMapRange")
    falloff_power = _ensure_node(nodes, "PKA Atmo Falloff Power", "ShaderNodeMapRange")
    elevation_falloff = _ensure_node(nodes, "PKA Atmo Elevation Falloff", "ShaderNodeMath")
    elev_distance_mul = _ensure_node(nodes, "PKA Atmo Elevation Distance", "ShaderNodeMath")
    haze_density = _ensure_node(nodes, "PKA Atmo Density", "ShaderNodeMath")

    _safe_setattr(haze_mix, "data_type", "RGBA")
    _safe_setattr(haze_mix, "blend_type", "MIX")
    _safe_setattr(distance_range, "clamp", True)
    _safe_setattr(height_range, "clamp", True)
    _safe_setattr(elevation_mask, "clamp", True)
    _safe_setattr(falloff_power, "clamp", True)
    _safe_setattr(horizon_invert, "operation", "SUBTRACT")
    _safe_setattr(horizon_height, "operation", "MULTIPLY")
    _safe_setattr(distance_horizon, "operation", "MAXIMUM")
    _safe_setattr(elevation_falloff, "operation", "POWER")
    _safe_setattr(elev_distance_mul, "operation", "MULTIPLY")
    _safe_setattr(haze_density, "operation", "MULTIPLY")
    _safe_setattr(haze_density, "use_clamp", True)
    _safe_setattr(el_separate, "mode", "RGB")

    try:
        distance_range.inputs[1].default_value = 0.05
        distance_range.inputs[2].default_value = 2.0
        distance_range.inputs[3].default_value = 0.0
        distance_range.inputs[4].default_value = 1.0
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    try:
        horizon_invert.inputs[0].default_value = 1.0
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    try:
        height_range.inputs[1].default_value = 0.0
        height_range.inputs[2].default_value = 150.0
        height_range.inputs[3].default_value = 0.75
        height_range.inputs[4].default_value = 2.5
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    try:
        elevation_mask.inputs[1].default_value = 0.42
        elevation_mask.inputs[2].default_value = 0.72
        elevation_mask.inputs[3].default_value = 1.0
        elevation_mask.inputs[4].default_value = 0.0
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    try:
        falloff_power.inputs[1].default_value = 0.0
        falloff_power.inputs[2].default_value = 1.0
        falloff_power.inputs[3].default_value = 1.0
        falloff_power.inputs[4].default_value = 8.0
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    mix_factor_in = _socket_input_by_name_or_index(haze_mix.inputs, "Factor", 0)
    mix_color_a = _socket_input_by_name_or_index(haze_mix.inputs, "A", 6)
    mix_color_b = _socket_input_by_name_or_index(haze_mix.inputs, "B", 7)
    mix_result = _socket_output_by_name_or_index(haze_mix.outputs, "Result", 2)
    if mix_color_b is not None:
        try:
            mix_color_b.default_value = _FAKE_ATMOSPHERE_DEFAULT_COLOR
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    _replace_input_link(
        links,
        _socket_input_by_name_or_index(distance_range.inputs, "Value", 0),
        _socket_output_by_name_or_index(camera_data.outputs, "View Distance"),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(horizon_invert.inputs, "Value", 1),
        _socket_output_by_name_or_index(layer_weight.outputs, "Facing"),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(height_range.inputs, "Value", 0),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(horizon_height.inputs, "Value", 0),
        _socket_output_by_name_or_index(horizon_invert.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(horizon_height.inputs, "Value", 1),
        _socket_output_by_name_or_index(height_range.outputs, "Result", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(distance_horizon.inputs, "Value", 0),
        _socket_output_by_name_or_index(distance_range.outputs, "Result", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(distance_horizon.inputs, "Value", 1),
        _socket_output_by_name_or_index(horizon_height.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(el_separate.inputs, "Color"),
        _socket_output_by_name_or_index(group_input.outputs, "EL"),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(elevation_mask.inputs, "Value", 0),
        _socket_output_by_name_or_index(el_separate.outputs, "Red", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(falloff_power.inputs, "Value", 0),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(elevation_falloff.inputs, "Value", 0),
        _socket_output_by_name_or_index(elevation_mask.outputs, "Result", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(elevation_falloff.inputs, "Value", 1),
        _socket_output_by_name_or_index(falloff_power.outputs, "Result", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(elev_distance_mul.inputs, "Value", 0),
        _socket_output_by_name_or_index(distance_horizon.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(elev_distance_mul.inputs, "Value", 1),
        _socket_output_by_name_or_index(elevation_falloff.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(haze_density.inputs, "Value", 0),
        _socket_output_by_name_or_index(elev_distance_mul.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(haze_density.inputs, "Value", 1),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET),
    )
    _replace_input_link(links, mix_factor_in, _socket_output_by_name_or_index(haze_density.outputs, "Value", 0))
    _replace_input_link(links, mix_color_a, _socket_output_by_name_or_index(group_input.outputs, "Base Color"))
    _replace_input_link(links, mix_color_b, _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_COLOR_SOCKET))
    _replace_input_link(links, _socket_input_by_name_or_index(group_output.inputs, "Color"), mix_result)

    _safe_set_node_location(group_input, -1200.0, 0.0)
    _safe_set_node_location(camera_data, -930.0, 120.0)
    _safe_set_node_location(distance_range, -700.0, 120.0)
    _safe_set_node_location(layer_weight, -930.0, -40.0)
    _safe_set_node_location(horizon_invert, -700.0, -40.0)
    _safe_set_node_location(height_range, -930.0, -240.0)
    _safe_set_node_location(horizon_height, -470.0, -20.0)
    _safe_set_node_location(distance_horizon, -230.0, 70.0)
    _safe_set_node_location(el_separate, -700.0, -380.0)
    _safe_set_node_location(elevation_mask, -470.0, -380.0)
    _safe_set_node_location(falloff_power, -470.0, -540.0)
    _safe_set_node_location(elevation_falloff, -230.0, -380.0)
    _safe_set_node_location(elev_distance_mul, -10.0, -40.0)
    _safe_set_node_location(haze_density, 200.0, -40.0)
    _safe_set_node_location(haze_mix, 420.0, 20.0)
    _safe_set_node_location(group_output, 650.0, 0.0)
    return group


def _ensure_surface_fake_atmosphere_nodes():
    node_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if not node_group or not getattr(node_group, "nodes", None) or not getattr(node_group, "links", None):
        return

    atmosphere_group = _ensure_planetka_atmosphere_grading_group()
    if atmosphere_group is None:
        return

    nodes = node_group.nodes
    links = node_group.links
    _remove_interface_input_socket(node_group, _FAKE_ATMOSPHERE_DENSITY_SOCKET_LEGACY)
    _ensure_interface_float_socket(
        node_group,
        _FAKE_ATMOSPHERE_DENSITY_SOCKET,
        default=0.0,
        min_value=0.0,
        max_value=2.0,
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_DENSITY_SOCKET, ""),
    )
    _ensure_interface_float_socket(
        node_group,
        _FAKE_ATMOSPHERE_HEIGHT_SOCKET,
        default=50.0,
        min_value=0.0,
        max_value=400.0,
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_HEIGHT_SOCKET, ""),
    )
    _ensure_interface_float_socket(
        node_group,
        _FAKE_ATMOSPHERE_FALLOFF_SOCKET,
        default=0.05,
        min_value=0.0,
        max_value=1.0,
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_FALLOFF_SOCKET, ""),
    )
    color_item = _ensure_interface_socket(
        node_group,
        _FAKE_ATMOSPHERE_COLOR_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketColor",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_COLOR_SOCKET, ""),
    )
    if color_item and hasattr(color_item, "default_value"):
        try:
            color_item.default_value = _FAKE_ATMOSPHERE_DEFAULT_COLOR
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    legacy_haze_nodes = (
        "PKA Haze Color Mix",
        "PKA Haze Camera Data",
        "PKA Haze Distance",
        "PKA Haze Layer Weight",
        "PKA Haze Horizon Invert",
        "PKA Haze Horizon Strength",
        "PKA Haze Distance Horizon",
        "PKA Haze Elevation Separate",
        "PKA Haze Elevation Mask",
        "PKA Haze Elevation Distance",
        "PKA Haze Density",
    )
    for node_name in legacy_haze_nodes:
        node = nodes.get(node_name)
        if node is None:
            continue
        try:
            nodes.remove(node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    group_input = nodes.get("Group Input.001") or nodes.get("Group Input")
    principled = nodes.get("Principled BSDF")
    if group_input is None or principled is None:
        return

    base_color_in = _socket_input_by_name_or_index(principled.inputs, "Base Color")
    if base_color_in is None:
        return

    atmo_node = _ensure_node(nodes, ATMOSPHERE_GRADING_GROUP_NAME, "ShaderNodeGroup")
    if atmo_node is None:
        return
    try:
        atmo_node.node_tree = atmosphere_group
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return

    atmo_color_out = _socket_output_by_name_or_index(atmo_node.outputs, "Color", 0)
    atmo_color_in = _socket_input_by_name_or_index(atmo_node.inputs, "Base Color", 0)
    atmo_el_in = _socket_input_by_name_or_index(atmo_node.inputs, "EL")
    atmo_density_in = _socket_input_by_name_or_index(atmo_node.inputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET)
    atmo_height_in = _socket_input_by_name_or_index(atmo_node.inputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET)
    atmo_falloff_in = _socket_input_by_name_or_index(atmo_node.inputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET)
    atmo_haze_color_in = _socket_input_by_name_or_index(atmo_node.inputs, _FAKE_ATMOSPHERE_COLOR_SOCKET)

    base_source = None
    if getattr(base_color_in, "is_linked", False):
        try:
            current_from = base_color_in.links[0].from_socket
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, IndexError, TypeError, ValueError):
            current_from = None

        if (
            current_from is not None
            and atmo_color_out is not None
            and current_from == atmo_color_out
            and atmo_color_in is not None
            and getattr(atmo_color_in, "is_linked", False)
        ):
            try:
                base_source = atmo_color_in.links[0].from_socket
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, IndexError, TypeError, ValueError):
                base_source = None
        else:
            base_source = current_from

    if base_source is not None and atmo_color_in is not None:
        _replace_input_link(links, atmo_color_in, base_source)
    elif atmo_color_in is not None:
        try:
            atmo_color_in.default_value = tuple(base_color_in.default_value)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    _replace_input_link(
        links,
        atmo_el_in,
        _socket_output_by_name_or_index(group_input.outputs, "EL"),
    )
    _replace_input_link(
        links,
        atmo_density_in,
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET),
    )
    _replace_input_link(
        links,
        atmo_height_in,
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET),
    )
    _replace_input_link(
        links,
        atmo_falloff_in,
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET),
    )
    _replace_input_link(
        links,
        atmo_haze_color_in,
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_COLOR_SOCKET),
    )
    _replace_input_link(links, base_color_in, atmo_color_out)

    try:
        node_group[_SURFACE_FAKE_ATMOSPHERE_VERSION_KEY] = int(_SURFACE_FAKE_ATMOSPHERE_VERSION)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        x0, y0 = principled.location
    except Exception:
        x0, y0 = 0.0, 0.0
    _safe_set_node_location(atmo_node, x0 - 270.0, y0 + 40.0)
    _organize_surface_group_interface(node_group)


def ensure_surface_fake_atmosphere_nodes():
    _apply_surface_shader_updates()
    _ensure_surface_fake_atmosphere_nodes()


def _ensure_surface_detail_nodes():
    node_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if not node_group or not getattr(node_group, "nodes", None) or not getattr(node_group, "links", None):
        return

    nodes = node_group.nodes
    links = node_group.links

    if nodes.get("PKA Forest Bump") and nodes.get("PKA Rock Bump") and nodes.get("PKA Detail Disp Add"):
        return

    try:
        _ensure_interface_float_socket(
            node_group,
            _DETAIL_SOCKET_SCALE,
            default=1.0,
            min_value=0.1,
            max_value=5.0,
            description=_SHADER_INPUT_DESCRIPTIONS.get(_DETAIL_SOCKET_SCALE, ""),
        )
        _ensure_interface_float_socket(
            node_group,
            _DETAIL_SOCKET_FOREST,
            default=0.25,
            min_value=0.0,
            max_value=2.0,
            description=_SHADER_INPUT_DESCRIPTIONS.get(_DETAIL_SOCKET_FOREST, ""),
        )
        _ensure_interface_float_socket(
            node_group,
            _DETAIL_SOCKET_ROCK,
            default=0.30,
            min_value=0.0,
            max_value=2.0,
            description=_SHADER_INPUT_DESCRIPTIONS.get(_DETAIL_SOCKET_ROCK, ""),
        )
        _ensure_interface_float_socket(
            node_group,
            _DETAIL_SOCKET_ROCK_COLOR,
            default=0.20,
            min_value=0.0,
            max_value=1.0,
            description=_SHADER_INPUT_DESCRIPTIONS.get(_DETAIL_SOCKET_ROCK_COLOR, ""),
        )
        _ensure_interface_float_socket(
            node_group,
            _DETAIL_SOCKET_MICRO_DISP,
            default=0.0,
            min_value=0.0,
            max_value=0.02,
            description=_SHADER_INPUT_DESCRIPTIONS.get(_DETAIL_SOCKET_MICRO_DISP, ""),
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return

    group_input = nodes.get("Group Input.001") or nodes.get("Group Input")
    group_output = nodes.get("Group Output")
    principled = nodes.get("Principled BSDF")
    snow_map = nodes.get("Map Range.002")
    disp_add_base = nodes.get("Vector Math")

    if group_input is None or group_output is None or principled is None:
        return

    s2 = group_input.outputs.get("S2")
    if s2 is None:
        return

    bsdf_base_in = principled.inputs.get("Base Color")
    bsdf_norm_in = principled.inputs.get("Normal")
    if bsdf_base_in is None or bsdf_norm_in is None:
        return

    base_color_source = bsdf_base_in.links[0].from_socket if getattr(bsdf_base_in, "is_linked", False) else None

    # -------------------------
    # Masks (forest / rock)
    # -------------------------
    sep_s2 = _ensure_node(nodes, "PKA Detail Separate S2", "ShaderNodeSeparateColor")
    _safe_setattr(sep_s2, "mode", "RGB")
    _replace_input_link(links, sep_s2.inputs.get("Color") if sep_s2 else None, s2)

    max_rb = _ensure_node(nodes, "PKA Forest MaxRB", "ShaderNodeMath")
    _safe_setattr(max_rb, "operation", "MAXIMUM")
    _replace_input_link(links, max_rb.inputs[0] if max_rb else None, sep_s2.outputs.get("Red") if sep_s2 else None)
    _replace_input_link(links, max_rb.inputs[1] if max_rb else None, sep_s2.outputs.get("Blue") if sep_s2 else None)

    green_dom = _ensure_node(nodes, "PKA Forest GreenDom", "ShaderNodeMath")
    _safe_setattr(green_dom, "operation", "SUBTRACT")
    _replace_input_link(links, green_dom.inputs[0] if green_dom else None, sep_s2.outputs.get("Green") if sep_s2 else None)
    _replace_input_link(links, green_dom.inputs[1] if green_dom else None, max_rb.outputs[0] if max_rb else None)

    green_mask = _ensure_node(nodes, "PKA Forest GreenMask", "ShaderNodeMapRange")
    if green_mask is not None:
        _safe_setattr(green_mask, "clamp", True)
        try:
            green_mask.inputs[1].default_value = 0.04  # From Min
            green_mask.inputs[2].default_value = 0.15  # From Max
            green_mask.inputs[3].default_value = 0.0   # To Min
            green_mask.inputs[4].default_value = 1.0   # To Max
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, green_mask.inputs[0] if green_mask else None, green_dom.outputs[0] if green_dom else None)

    luma = _ensure_node(nodes, "PKA Detail S2 Luma", "ShaderNodeRGBToBW")
    _replace_input_link(links, luma.inputs.get("Color") if luma else None, s2)

    dark_mask = _ensure_node(nodes, "PKA Forest DarkMask", "ShaderNodeMapRange")
    if dark_mask is not None:
        _safe_setattr(dark_mask, "clamp", True)
        try:
            dark_mask.inputs[1].default_value = 0.25  # From Min
            dark_mask.inputs[2].default_value = 0.50  # From Max
            dark_mask.inputs[3].default_value = 1.0   # To Min (invert)
            dark_mask.inputs[4].default_value = 0.0   # To Max
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, dark_mask.inputs[0] if dark_mask else None, luma.outputs[0] if luma else None)

    forest_mask = _ensure_node(nodes, "PKA Forest Mask", "ShaderNodeMath")
    _safe_setattr(forest_mask, "operation", "MULTIPLY")
    _replace_input_link(links, forest_mask.inputs[0] if forest_mask else None, green_mask.outputs.get("Result") if green_mask else None)
    _replace_input_link(links, forest_mask.inputs[1] if forest_mask else None, dark_mask.outputs.get("Result") if dark_mask else None)

    high_alt = snow_map.outputs.get("Result") if snow_map else None
    low_alt = None
    if high_alt is not None:
        inv = _ensure_node(nodes, "PKA Detail LowAlt", "ShaderNodeMath")
        _safe_setattr(inv, "operation", "MULTIPLY_ADD")
        if inv is not None:
            try:
                inv.inputs[1].default_value = -1.0
                inv.inputs[2].default_value = 1.0
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        _replace_input_link(links, inv.inputs[0] if inv else None, high_alt)
        low_alt = inv.outputs[0] if inv else None

    if low_alt is not None:
        forest_mask_low = _ensure_node(nodes, "PKA Forest Mask LowAlt", "ShaderNodeMath")
        _safe_setattr(forest_mask_low, "operation", "MULTIPLY")
        _replace_input_link(links, forest_mask_low.inputs[0] if forest_mask_low else None, forest_mask.outputs[0] if forest_mask else None)
        _replace_input_link(links, forest_mask_low.inputs[1] if forest_mask_low else None, low_alt)
        forest_mask_out = forest_mask_low.outputs[0] if forest_mask_low else forest_mask.outputs[0] if forest_mask else None
    else:
        forest_mask_out = forest_mask.outputs[0] if forest_mask else None

    geo = _ensure_node(nodes, "PKA Detail Geometry", "ShaderNodeNewGeometry")
    pos_norm = _ensure_node(nodes, "PKA Detail Normalize Pos", "ShaderNodeVectorMath")
    _safe_setattr(pos_norm, "operation", "NORMALIZE")
    _replace_input_link(links, pos_norm.inputs[0] if pos_norm else None, geo.outputs.get("Position") if geo else None)

    dot = _ensure_node(nodes, "PKA Detail Dot", "ShaderNodeVectorMath")
    _safe_setattr(dot, "operation", "DOT_PRODUCT")
    _replace_input_link(links, dot.inputs[0] if dot else None, pos_norm.outputs.get("Vector") if pos_norm else None)
    _replace_input_link(links, dot.inputs[1] if dot else None, geo.outputs.get("Normal") if geo else None)

    slope = _ensure_node(nodes, "PKA Detail Slope", "ShaderNodeMath")
    _safe_setattr(slope, "operation", "SUBTRACT")
    if slope is not None:
        try:
            slope.inputs[0].default_value = 1.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, slope.inputs[1] if slope else None, dot.outputs.get("Value") if dot else None)

    slope_mask = _ensure_node(nodes, "PKA Detail SlopeMask", "ShaderNodeMapRange")
    if slope_mask is not None:
        _safe_setattr(slope_mask, "clamp", True)
        try:
            slope_mask.inputs[1].default_value = 0.00  # From Min
            slope_mask.inputs[2].default_value = 0.25  # From Max
            slope_mask.inputs[3].default_value = 0.0   # To Min
            slope_mask.inputs[4].default_value = 1.0   # To Max
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, slope_mask.inputs[0] if slope_mask else None, slope.outputs[0] if slope else None)

    rock_mask = _ensure_node(nodes, "PKA Rock Mask", "ShaderNodeMath")
    _safe_setattr(rock_mask, "operation", "MULTIPLY")
    _replace_input_link(links, rock_mask.inputs[0] if rock_mask else None, slope_mask.outputs.get("Result") if slope_mask else None)
    if high_alt is not None:
        _replace_input_link(links, rock_mask.inputs[1] if rock_mask else None, high_alt)
        rock_mask_out = rock_mask.outputs[0] if rock_mask else None
    else:
        # Fallback: slope-only
        rock_mask_out = slope_mask.outputs.get("Result") if slope_mask else None

    # -------------------------
    # Detail scale / strengths
    # -------------------------
    detail_scale = group_input.outputs.get(_DETAIL_SOCKET_SCALE)
    forest_strength = group_input.outputs.get(_DETAIL_SOCKET_FOREST)
    rock_strength = group_input.outputs.get(_DETAIL_SOCKET_ROCK)
    rock_color_strength = group_input.outputs.get(_DETAIL_SOCKET_ROCK_COLOR)
    micro_disp_strength = group_input.outputs.get(_DETAIL_SOCKET_MICRO_DISP)

    forest_strength_masked = _ensure_node(nodes, "PKA Forest Strength", "ShaderNodeMath")
    _safe_setattr(forest_strength_masked, "operation", "MULTIPLY")
    _replace_input_link(links, forest_strength_masked.inputs[0] if forest_strength_masked else None, forest_strength)
    _replace_input_link(links, forest_strength_masked.inputs[1] if forest_strength_masked else None, forest_mask_out)

    rock_strength_masked = _ensure_node(nodes, "PKA Rock Strength", "ShaderNodeMath")
    _safe_setattr(rock_strength_masked, "operation", "MULTIPLY")
    _replace_input_link(links, rock_strength_masked.inputs[0] if rock_strength_masked else None, rock_strength)
    _replace_input_link(links, rock_strength_masked.inputs[1] if rock_strength_masked else None, rock_mask_out)

    # -------------------------
    # Forest detail (trees)
    # -------------------------
    forest_scale = _ensure_node(nodes, "PKA Forest Scale", "ShaderNodeMath")
    _safe_setattr(forest_scale, "operation", "MULTIPLY")
    if forest_scale is not None:
        try:
            forest_scale.inputs[1].default_value = 800.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, forest_scale.inputs[0] if forest_scale else None, detail_scale)

    forest_noise = _ensure_node(nodes, "PKA Forest Noise", "ShaderNodeTexNoise")
    if forest_noise is not None:
        try:
            forest_noise.inputs["Detail"].default_value = 8.0
            forest_noise.inputs["Roughness"].default_value = 0.55
            forest_noise.inputs["Distortion"].default_value = 0.10
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, KeyError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, forest_noise.inputs.get("Vector") if forest_noise else None, geo.outputs.get("Position") if geo else None)
    _replace_input_link(links, forest_noise.inputs.get("Scale") if forest_noise else None, forest_scale.outputs[0] if forest_scale else None)

    forest_height = _ensure_node(nodes, "PKA Forest Height", "ShaderNodeMapRange")
    if forest_height is not None:
        _safe_setattr(forest_height, "clamp", True)
        try:
            forest_height.inputs[1].default_value = 0.35  # From Min
            forest_height.inputs[2].default_value = 0.65  # From Max
            forest_height.inputs[3].default_value = 0.0
            forest_height.inputs[4].default_value = 1.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, forest_height.inputs[0] if forest_height else None, forest_noise.outputs.get("Fac") if forest_noise else None)

    forest_bump = _ensure_node(nodes, "PKA Forest Bump", "ShaderNodeBump")
    _replace_input_link(links, forest_bump.inputs.get("Height") if forest_bump else None, forest_height.outputs.get("Result") if forest_height else None)
    _replace_input_link(links, forest_bump.inputs.get("Strength") if forest_bump else None, forest_strength_masked.outputs[0] if forest_strength_masked else None)

    # -------------------------
    # Rock detail (cracks)
    # -------------------------
    rock_voronoi_scale = _ensure_node(nodes, "PKA Rock Voronoi Scale", "ShaderNodeMath")
    _safe_setattr(rock_voronoi_scale, "operation", "MULTIPLY")
    if rock_voronoi_scale is not None:
        try:
            rock_voronoi_scale.inputs[1].default_value = 140.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, rock_voronoi_scale.inputs[0] if rock_voronoi_scale else None, detail_scale)

    rock_voronoi = _ensure_node(nodes, "PKA Rock Voronoi", "ShaderNodeTexVoronoi")
    _safe_setattr(rock_voronoi, "feature", "F1")
    _safe_setattr(rock_voronoi, "distance", "EUCLIDEAN")
    _replace_input_link(links, rock_voronoi.inputs.get("Vector") if rock_voronoi else None, geo.outputs.get("Position") if geo else None)
    _replace_input_link(links, rock_voronoi.inputs.get("Scale") if rock_voronoi else None, rock_voronoi_scale.outputs[0] if rock_voronoi_scale else None)

    rock_cracks = _ensure_node(nodes, "PKA Rock Cracks", "ShaderNodeMapRange")
    if rock_cracks is not None:
        _safe_setattr(rock_cracks, "clamp", True)
        try:
            rock_cracks.inputs[1].default_value = 0.00  # From Min
            rock_cracks.inputs[2].default_value = 0.04  # From Max
            rock_cracks.inputs[3].default_value = 1.0   # To Min (invert)
            rock_cracks.inputs[4].default_value = 0.0   # To Max
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(
        links,
        rock_cracks.inputs[0] if rock_cracks else None,
        rock_voronoi.outputs.get("Distance to Edge") if rock_voronoi else None,
    )

    rock_noise_scale = _ensure_node(nodes, "PKA Rock Noise Scale", "ShaderNodeMath")
    _safe_setattr(rock_noise_scale, "operation", "MULTIPLY")
    if rock_noise_scale is not None:
        try:
            rock_noise_scale.inputs[1].default_value = 40.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, rock_noise_scale.inputs[0] if rock_noise_scale else None, detail_scale)

    rock_noise = _ensure_node(nodes, "PKA Rock Noise", "ShaderNodeTexNoise")
    if rock_noise is not None:
        try:
            rock_noise.inputs["Detail"].default_value = 12.0
            rock_noise.inputs["Roughness"].default_value = 0.60
            rock_noise.inputs["Distortion"].default_value = 0.15
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, KeyError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, rock_noise.inputs.get("Vector") if rock_noise else None, geo.outputs.get("Position") if geo else None)
    _replace_input_link(links, rock_noise.inputs.get("Scale") if rock_noise else None, rock_noise_scale.outputs[0] if rock_noise_scale else None)

    crack_w = _ensure_node(nodes, "PKA Rock Crack Weight", "ShaderNodeMath")
    _safe_setattr(crack_w, "operation", "MULTIPLY")
    if crack_w is not None:
        try:
            crack_w.inputs[1].default_value = 0.75
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, crack_w.inputs[0] if crack_w else None, rock_cracks.outputs.get("Result") if rock_cracks else None)

    noise_w = _ensure_node(nodes, "PKA Rock Noise Weight", "ShaderNodeMath")
    _safe_setattr(noise_w, "operation", "MULTIPLY")
    if noise_w is not None:
        try:
            noise_w.inputs[1].default_value = 0.25
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(links, noise_w.inputs[0] if noise_w else None, rock_noise.outputs.get("Fac") if rock_noise else None)

    rock_height_sum = _ensure_node(nodes, "PKA Rock Height", "ShaderNodeMath")
    _safe_setattr(rock_height_sum, "operation", "ADD")
    _replace_input_link(links, rock_height_sum.inputs[0] if rock_height_sum else None, crack_w.outputs[0] if crack_w else None)
    _replace_input_link(links, rock_height_sum.inputs[1] if rock_height_sum else None, noise_w.outputs[0] if noise_w else None)

    rock_bump = _ensure_node(nodes, "PKA Rock Bump", "ShaderNodeBump")
    _replace_input_link(links, rock_bump.inputs.get("Height") if rock_bump else None, rock_height_sum.outputs[0] if rock_height_sum else None)
    _replace_input_link(links, rock_bump.inputs.get("Strength") if rock_bump else None, rock_strength_masked.outputs[0] if rock_strength_masked else None)
    _replace_input_link(links, rock_bump.inputs.get("Normal") if rock_bump else None, forest_bump.outputs.get("Normal") if forest_bump else None)

    _replace_input_link(links, bsdf_norm_in, rock_bump.outputs.get("Normal") if rock_bump else None)

    # -------------------------
    # Rock color variation (subtle brightness variation)
    # -------------------------
    if base_color_source is not None:
        noise_center = _ensure_node(nodes, "PKA Rock Noise Center", "ShaderNodeMath")
        _safe_setattr(noise_center, "operation", "SUBTRACT")
        if noise_center is not None:
            try:
                noise_center.inputs[1].default_value = 0.5
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        _replace_input_link(links, noise_center.inputs[0] if noise_center else None, rock_noise.outputs.get("Fac") if rock_noise else None)

        noise_center2 = _ensure_node(nodes, "PKA Rock Noise Center2", "ShaderNodeMath")
        _safe_setattr(noise_center2, "operation", "MULTIPLY")
        if noise_center2 is not None:
            try:
                noise_center2.inputs[1].default_value = 2.0
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        _replace_input_link(links, noise_center2.inputs[0] if noise_center2 else None, noise_center.outputs[0] if noise_center else None)

        rock_color_amount = _ensure_node(nodes, "PKA Rock Color Amount", "ShaderNodeMath")
        _safe_setattr(rock_color_amount, "operation", "MULTIPLY")
        _replace_input_link(links, rock_color_amount.inputs[0] if rock_color_amount else None, rock_mask_out)
        _replace_input_link(links, rock_color_amount.inputs[1] if rock_color_amount else None, rock_color_strength)

        rock_color_amount2 = _ensure_node(nodes, "PKA Rock Color Amount2", "ShaderNodeMath")
        _safe_setattr(rock_color_amount2, "operation", "MULTIPLY")
        if rock_color_amount2 is not None:
            try:
                rock_color_amount2.inputs[1].default_value = 0.12
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        _replace_input_link(links, rock_color_amount2.inputs[0] if rock_color_amount2 else None, rock_color_amount.outputs[0] if rock_color_amount else None)

        rock_color_delta = _ensure_node(nodes, "PKA Rock Color Delta", "ShaderNodeMath")
        _safe_setattr(rock_color_delta, "operation", "MULTIPLY")
        _replace_input_link(links, rock_color_delta.inputs[0] if rock_color_delta else None, noise_center2.outputs[0] if noise_center2 else None)
        _replace_input_link(links, rock_color_delta.inputs[1] if rock_color_delta else None, rock_color_amount2.outputs[0] if rock_color_amount2 else None)

        rock_color_scale = _ensure_node(nodes, "PKA Rock Color Scale", "ShaderNodeMath")
        _safe_setattr(rock_color_scale, "operation", "ADD")
        if rock_color_scale is not None:
            try:
                rock_color_scale.inputs[0].default_value = 1.0
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        _replace_input_link(links, rock_color_scale.inputs[1] if rock_color_scale else None, rock_color_delta.outputs[0] if rock_color_delta else None)

        scale_rgb = _ensure_node(nodes, "PKA Rock Color RGB", "ShaderNodeCombineColor")
        _safe_setattr(scale_rgb, "mode", "RGB")
        _replace_input_link(links, scale_rgb.inputs.get("Red") if scale_rgb else None, rock_color_scale.outputs[0] if rock_color_scale else None)
        _replace_input_link(links, scale_rgb.inputs.get("Green") if scale_rgb else None, rock_color_scale.outputs[0] if rock_color_scale else None)
        _replace_input_link(links, scale_rgb.inputs.get("Blue") if scale_rgb else None, rock_color_scale.outputs[0] if rock_color_scale else None)

        color_mul = _ensure_node(nodes, "PKA Rock Color Multiply", "ShaderNodeMix")
        _safe_setattr(color_mul, "data_type", "RGBA")
        _safe_setattr(color_mul, "blend_type", "MULTIPLY")
        if color_mul is not None:
            try:
                color_mul.inputs[0].default_value = 1.0
                if hasattr(color_mul, "clamp_factor"):
                    color_mul.clamp_factor = True
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        _replace_input_link(links, color_mul.inputs[6] if color_mul else None, base_color_source)
        _replace_input_link(links, color_mul.inputs[7] if color_mul else None, scale_rgb.outputs.get("Color") if scale_rgb else None)

        _replace_input_link(links, bsdf_base_in, color_mul.outputs.get("Result") if color_mul else None)

    # -------------------------
    # Optional micro displacement (disabled by default)
    # -------------------------
    if disp_add_base is not None and group_output.inputs.get("Displacement") is not None:
        forest_disp = _ensure_node(nodes, "PKA Forest MicroDisp", "ShaderNodeMath")
        _safe_setattr(forest_disp, "operation", "MULTIPLY")
        _replace_input_link(links, forest_disp.inputs[0] if forest_disp else None, forest_mask_out)
        _replace_input_link(links, forest_disp.inputs[1] if forest_disp else None, forest_height.outputs.get("Result") if forest_height else None)

        rock_disp = _ensure_node(nodes, "PKA Rock MicroDisp", "ShaderNodeMath")
        _safe_setattr(rock_disp, "operation", "MULTIPLY")
        _replace_input_link(links, rock_disp.inputs[0] if rock_disp else None, rock_mask_out)
        _replace_input_link(links, rock_disp.inputs[1] if rock_disp else None, rock_height_sum.outputs[0] if rock_height_sum else None)

        micro_sum = _ensure_node(nodes, "PKA Detail MicroDisp Sum", "ShaderNodeMath")
        _safe_setattr(micro_sum, "operation", "ADD")
        _replace_input_link(links, micro_sum.inputs[0] if micro_sum else None, forest_disp.outputs[0] if forest_disp else None)
        _replace_input_link(links, micro_sum.inputs[1] if micro_sum else None, rock_disp.outputs[0] if rock_disp else None)

        micro_scaled = _ensure_node(nodes, "PKA Detail MicroDisp Strength", "ShaderNodeMath")
        _safe_setattr(micro_scaled, "operation", "MULTIPLY")
        _replace_input_link(links, micro_scaled.inputs[0] if micro_scaled else None, micro_disp_strength)
        _replace_input_link(links, micro_scaled.inputs[1] if micro_scaled else None, micro_sum.outputs[0] if micro_sum else None)

        disp_vec = _ensure_node(nodes, "PKA Detail MicroDisp Vec", "ShaderNodeVectorMath")
        _safe_setattr(disp_vec, "operation", "SCALE")
        _replace_input_link(links, disp_vec.inputs.get("Vector") if disp_vec else None, geo.outputs.get("Normal") if geo else None)
        _replace_input_link(links, disp_vec.inputs.get("Scale") if disp_vec else None, micro_scaled.outputs[0] if micro_scaled else None)

        disp_add = _ensure_node(nodes, "PKA Detail Disp Add", "ShaderNodeVectorMath")
        _safe_setattr(disp_add, "operation", "ADD")
        _replace_input_link(links, disp_add.inputs[0] if disp_add else None, disp_add_base.outputs.get("Vector") if disp_add_base else None)
        _replace_input_link(links, disp_add.inputs[1] if disp_add else None, disp_vec.outputs.get("Vector") if disp_vec else None)

        _replace_input_link(links, group_output.inputs.get("Displacement"), disp_add.outputs.get("Vector") if disp_add else None)

    try:
        node_group[_SURFACE_DETAIL_VERSION_KEY] = int(_SURFACE_DETAIL_VERSION)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    # Best-effort node placement (cosmetic only).
    try:
        x0, y0 = principled.location
    except Exception:
        x0, y0 = 0.0, 0.0
    _safe_set_node_location(sep_s2, x0 - 1050.0, y0 + 280.0)
    _safe_set_node_location(luma, x0 - 1050.0, y0 + 40.0)
    _safe_set_node_location(forest_noise, x0 - 650.0, y0 + 260.0)
    _safe_set_node_location(forest_bump, x0 - 280.0, y0 + 260.0)
    _safe_set_node_location(rock_voronoi, x0 - 650.0, y0 - 40.0)
    _safe_set_node_location(rock_noise, x0 - 650.0, y0 - 220.0)
    _safe_set_node_location(rock_bump, x0 - 280.0, y0 - 90.0)


def _remove_interface_input_socket(node_group, socket_name):
    interface = getattr(node_group, "interface", None) if node_group else None
    items = getattr(interface, "items_tree", None) if interface else None
    if items is None:
        return
    for item in list(items):
        if getattr(item, "item_type", None) != "SOCKET":
            continue
        if getattr(item, "in_out", None) != "INPUT":
            continue
        if str(getattr(item, "name", "")) != str(socket_name):
            continue
        try:
            interface.remove(item)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue


def _find_interface_panel(interface, panel_name, parent=None):
    if interface is None or not hasattr(interface, "items_tree"):
        return None
    fallback = None
    for item in interface.items_tree:
        if getattr(item, "item_type", None) != "PANEL":
            continue
        if str(getattr(item, "name", "")) != str(panel_name):
            continue
        if fallback is None:
            fallback = item
        if getattr(item, "parent", None) is parent:
            return item
    return fallback


def _find_interface_input_socket_item(interface, socket_name):
    if interface is None or not hasattr(interface, "items_tree"):
        return None
    for item in interface.items_tree:
        if getattr(item, "item_type", None) != "SOCKET":
            continue
        if getattr(item, "in_out", None) != "INPUT":
            continue
        if str(getattr(item, "name", "")) == str(socket_name):
            return item
    return None


def _interface_child_count(interface, parent):
    if interface is None or not hasattr(interface, "items_tree"):
        return 0
    count = 0
    for item in interface.items_tree:
        if getattr(item, "parent", None) is parent:
            count += 1
    return count


def _ensure_interface_panel(interface, panel_name, *, parent=None, default_closed=True):
    if interface is None:
        return None
    panel = _find_interface_panel(interface, panel_name, parent=parent)
    if panel is None:
        try:
            panel = interface.new_panel(name=str(panel_name), description="", default_closed=bool(default_closed))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return None
    if hasattr(panel, "default_closed"):
        try:
            panel.default_closed = bool(default_closed)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    current_parent = getattr(panel, "parent", None)
    if current_parent is not parent:
        try:
            interface.move_to_parent(panel, parent, _interface_child_count(interface, parent))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return panel


def _move_interface_item_to_panel(interface, item, panel):
    if interface is None or item is None or panel is None:
        return
    if getattr(item, "parent", None) is panel:
        return
    try:
        interface.move_to_parent(item, panel, _interface_child_count(interface, panel))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _organize_surface_group_interface(node_group):
    interface = getattr(node_group, "interface", None) if node_group else None
    if interface is None:
        return

    extra_panel = _ensure_interface_panel(
        interface,
        _SURFACE_PANEL_EXTRA,
        parent=None,
        default_closed=True,
    )
    snow_panel = _ensure_interface_panel(
        interface,
        _SURFACE_PANEL_SNOW,
        parent=extra_panel,
        default_closed=True,
    )
    waves_panel = _ensure_interface_panel(
        interface,
        _SURFACE_PANEL_WAVES,
        parent=extra_panel,
        default_closed=True,
    )
    atmosphere_panel = _ensure_interface_panel(
        interface,
        _SURFACE_PANEL_ATMOSPHERE,
        parent=None,
        default_closed=True,
    )

    for socket_name in ("Snow On/Off", "Snow Line (m)"):
        _move_interface_item_to_panel(
            interface,
            _find_interface_input_socket_item(interface, socket_name),
            snow_panel,
        )
    for socket_name in ("Water Waves On/Off", "Waves Density Coefficient", "Waves Height Coefficient"):
        _move_interface_item_to_panel(
            interface,
            _find_interface_input_socket_item(interface, socket_name),
            waves_panel,
        )
    for socket_name in (
        _FAKE_ATMOSPHERE_DENSITY_SOCKET,
        _FAKE_ATMOSPHERE_HEIGHT_SOCKET,
        _FAKE_ATMOSPHERE_FALLOFF_SOCKET,
        _FAKE_ATMOSPHERE_COLOR_SOCKET,
    ):
        _move_interface_item_to_panel(
            interface,
            _find_interface_input_socket_item(interface, socket_name),
            atmosphere_panel,
        )


def _find_group_input_output_socket(node_group, socket_name):
    nodes = getattr(node_group, "nodes", None) if node_group else None
    if nodes is None:
        return None
    for node in nodes:
        if str(getattr(node, "bl_idname", "")) != "NodeGroupInput":
            continue
        output = _socket_output_by_name_or_index(getattr(node, "outputs", None), socket_name)
        if output is not None:
            return output
    try:
        node = nodes.new("NodeGroupInput")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return None
    except (RuntimeError, TypeError, ValueError):
        return None
    return _socket_output_by_name_or_index(getattr(node, "outputs", None), socket_name)


def _rewire_value_node_output(node_group, value_node_name, replacement_output):
    if replacement_output is None or node_group is None:
        return False
    nodes = getattr(node_group, "nodes", None)
    links = getattr(node_group, "links", None)
    if nodes is None or links is None:
        return False
    node = nodes.get(value_node_name)
    if node is None or str(getattr(node, "bl_idname", "")) != "ShaderNodeValue":
        return False
    out_socket = _socket_output_by_name_or_index(getattr(node, "outputs", None), "Value", 0)
    if out_socket is None:
        return False
    for link in list(getattr(out_socket, "links", ())):
        _replace_input_link(links, getattr(link, "to_socket", None), replacement_output)
    try:
        nodes.remove(node)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return True


def _set_group_node_input_default(node, socket_name, value):
    if node is None or not hasattr(node, "inputs"):
        return
    socket = _socket_input_by_name_or_index(node.inputs, socket_name)
    if socket is None:
        return
    try:
        socket.default_value = float(value)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _remove_surface_detail_nodes(node_group):
    if not node_group or not getattr(node_group, "nodes", None) or not getattr(node_group, "links", None):
        return
    nodes = node_group.nodes
    links = node_group.links

    for socket_name in (
        _DETAIL_SOCKET_SCALE,
        _DETAIL_SOCKET_FOREST,
        _DETAIL_SOCKET_ROCK,
        _DETAIL_SOCKET_ROCK_COLOR,
        _DETAIL_SOCKET_MICRO_DISP,
    ):
        _remove_interface_input_socket(node_group, socket_name)

    principled = nodes.get("Principled BSDF")
    mix_surface = nodes.get("Mix.003")
    if principled is not None and mix_surface is not None:
        _replace_input_link(
            links,
            _socket_input_by_name_or_index(principled.inputs, "Base Color"),
            _socket_output_by_name_or_index(mix_surface.outputs, "Result", 2),
        )
        normal_in = _socket_input_by_name_or_index(principled.inputs, "Normal")
        if normal_in is not None:
            for link in list(getattr(normal_in, "links", ())):
                try:
                    links.remove(link)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    continue
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    continue

    group_output = nodes.get("Group Output")
    disp_base = nodes.get("Vector Math")
    if group_output is not None and disp_base is not None:
        _replace_input_link(
            links,
            _socket_input_by_name_or_index(group_output.inputs, "Displacement"),
            _socket_output_by_name_or_index(disp_base.outputs, "Vector", 0),
        )

    for node in list(nodes):
        name = str(getattr(node, "name", ""))
        if not name.startswith(("PKA Forest", "PKA Rock", "PKA Detail")):
            continue
        try:
            nodes.remove(node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError):
            continue

    try:
        if _SURFACE_DETAIL_VERSION_KEY in node_group:
            del node_group[_SURFACE_DETAIL_VERSION_KEY]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _apply_surface_group_input_defaults(surface_group):
    if surface_group is None:
        return
    _remove_interface_input_socket(surface_group, _FAKE_ATMOSPHERE_DENSITY_SOCKET_LEGACY)
    for socket_name, default, min_value, max_value in _SURFACE_DEFAULT_INPUT_SPECS:
        _ensure_interface_float_socket(
            surface_group,
            socket_name,
            default=default,
            min_value=min_value,
            max_value=max_value,
            description=_SHADER_INPUT_DESCRIPTIONS.get(socket_name, ""),
        )
    for socket_name, default, min_value, max_value in _SURFACE_EXTRA_INPUT_SPECS:
        _ensure_interface_float_socket(
            surface_group,
            socket_name,
            default=default,
            min_value=min_value,
            max_value=max_value,
            description=_SHADER_INPUT_DESCRIPTIONS.get(socket_name, ""),
        )

    ocean_group = bpy.data.node_groups.get("Planetka Ocean Shader Group")
    if ocean_group is not None:
        _ensure_interface_float_socket(
            ocean_group,
            "Waves Density Coefficient",
            default=2.0,
            min_value=0.0,
            max_value=10.0,
            description=_SHADER_INPUT_DESCRIPTIONS.get("Waves Density Coefficient", ""),
        )
        _ensure_interface_float_socket(
            ocean_group,
            "Waves Height Coefficient",
            default=0.75,
            min_value=0.0,
            max_value=10.0,
            description=_SHADER_INPUT_DESCRIPTIONS.get("Waves Height Coefficient", ""),
        )


def _wire_surface_extra_feature_inputs(surface_group):
    if not surface_group or not getattr(surface_group, "nodes", None) or not getattr(surface_group, "links", None):
        return
    nodes = surface_group.nodes
    links = surface_group.links

    waves_toggle_out = _find_group_input_output_socket(surface_group, "Water Waves On/Off")
    snow_toggle_out = _find_group_input_output_socket(surface_group, "Snow On/Off")
    snow_line_out = _find_group_input_output_socket(surface_group, "Snow Line (m)")
    waves_density_out = _find_group_input_output_socket(surface_group, "Waves Density Coefficient")
    waves_height_out = _find_group_input_output_socket(surface_group, "Waves Height Coefficient")

    _rewire_value_node_output(surface_group, "Waves_On_Off", waves_toggle_out)
    _rewire_value_node_output(surface_group, "Snow_On_Off", snow_toggle_out)
    _rewire_value_node_output(surface_group, "Snow Line", snow_line_out)

    for node in nodes:
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        node_tree = getattr(node, "node_tree", None)
        if str(getattr(node_tree, "name", "")) != "Planetka Ocean Shader Group":
            continue
        _replace_input_link(
            links,
            _socket_input_by_name_or_index(node.inputs, "Waves Density Coefficient"),
            waves_density_out,
        )
        _replace_input_link(
            links,
            _socket_input_by_name_or_index(node.inputs, "Waves Height Coefficient"),
            waves_height_out,
        )


def _apply_surface_group_node_defaults():
    for material in getattr(bpy.data, "materials", ()):
        node_tree = getattr(material, "node_tree", None)
        if node_tree is None:
            continue
        for node in node_tree.nodes:
            if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                continue
            node_tree_ref = getattr(node, "node_tree", None)
            group_name = str(getattr(node_tree_ref, "name", ""))
            if group_name == SURFACE_GRADING_GROUP_NAME:
                for socket_name, default, _min_value, _max_value in _SURFACE_DEFAULT_INPUT_SPECS:
                    _set_group_node_input_default(node, socket_name, default)
                for socket_name, default, _min_value, _max_value in _SURFACE_EXTRA_INPUT_SPECS:
                    _set_group_node_input_default(node, socket_name, default)
            elif group_name == "Planetka Ocean Shader Group":
                _set_group_node_input_default(node, "Waves Density Coefficient", 2.0)
                _set_group_node_input_default(node, "Waves Height Coefficient", 0.75)


def _apply_surface_shader_updates():
    surface_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if surface_group is None:
        return
    try:
        if int(surface_group.get(_SURFACE_SHADER_UPDATE_VERSION_KEY, 0)) >= int(_SURFACE_SHADER_UPDATE_VERSION):
            return
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    _remove_surface_detail_nodes(surface_group)
    _apply_surface_group_input_defaults(surface_group)
    _wire_surface_extra_feature_inputs(surface_group)
    _organize_surface_group_interface(surface_group)
    _apply_surface_group_node_defaults()
    try:
        surface_group[_SURFACE_SHADER_UPDATE_VERSION_KEY] = int(_SURFACE_SHADER_UPDATE_VERSION)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _set_image_colorspace_safe(image, colorspace):
    if not image or not colorspace:
        return

    settings = getattr(image, "colorspace_settings", None)
    if settings is None or not hasattr(settings, "name"):
        return

    candidates = [colorspace]
    if colorspace == "Linear Rec.709":
        candidates.extend(["Linear", "Raw"])
    elif colorspace == "Non-Color":
        candidates.extend(["Raw"])
    elif colorspace == "sRGB":
        candidates.extend(["Filmic sRGB"])

    available = set()
    try:
        prop = settings.bl_rna.properties.get("name")
        if prop and hasattr(prop, "enum_items"):
            available = {item.identifier for item in prop.enum_items}
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        available = set()

    for candidate in candidates:
        if available and candidate not in available:
            continue
        try:
            settings.name = candidate
            return
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            continue


def _get_embedded_material_library_payload():
    payload = get_material_library_bytes()
    if payload.startswith(b"BLENDER"):
        return payload

    if payload.startswith(_ZSTD_MAGIC):
        try:
            import zstandard as zstd
        except Exception as exc:
            raise RuntimeError(
                "Planetka: embedded material library uses zstd compression but zstandard module is unavailable."
            ) from exc
        try:
            with zstd.ZstdDecompressor().stream_reader(io.BytesIO(payload)) as reader:
                payload = reader.read()
        except Exception as exc:
            raise RuntimeError("Planetka: failed to decompress embedded material library payload.") from exc

    if not payload.startswith(b"BLENDER"):
        raise RuntimeError("Planetka: embedded material library payload is invalid.")
    return payload


def _legacy_material_library_path():
    return os.path.join(os.path.dirname(__file__), *_LEGACY_LIBRARY_RELATIVE_PATH)


def _append_material_library_from_blend(blend_path):
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        available_materials = set(data_from.materials)
        available_groups = set(data_from.node_groups)
        data_to.materials = [name for name in MATERIAL_LIBRARY_MATERIALS if name in available_materials]
        data_to.node_groups = [name for name in MATERIAL_LIBRARY_NODE_GROUPS if name in available_groups]


def _ensure_collection(parent_collection, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if parent_collection:
        try:
            if name not in parent_collection.children:
                parent_collection.children.link(collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return collection


def _ensure_planetka_sunlight(surface_collection):
    sunlight_obj = bpy.data.objects.get(SUNLIGHT_OBJECT_NAME)
    sunlight_data = getattr(sunlight_obj, "data", None) if sunlight_obj else None
    created_new = False
    if sunlight_obj is None or getattr(sunlight_obj, "type", None) != 'LIGHT' or getattr(sunlight_data, "type", None) != 'SUN':
        if sunlight_obj is not None:
            try:
                bpy.data.objects.remove(sunlight_obj, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        sun_data = bpy.data.lights.new(name=SUNLIGHT_OBJECT_NAME, type='SUN')
        sunlight_obj = bpy.data.objects.new(SUNLIGHT_OBJECT_NAME, sun_data)
        created_new = True

    if created_new:
        try:
            sunlight_obj.rotation_mode = 'XYZ'
            sunlight_obj.rotation_euler = (math.pi, -math.pi * 0.5, 0.0)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    if surface_collection is not None:
        for collection in list(getattr(sunlight_obj, "users_collection", ())):
            if collection is surface_collection:
                continue
            try:
                collection.objects.unlink(sunlight_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        if sunlight_obj.name not in surface_collection.objects:
            try:
                surface_collection.objects.link(sunlight_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    nightday_group = bpy.data.node_groups.get(NIGHTDAY_GROUP_NAME)
    if nightday_group:
        target_nodes = []
        named_node = nightday_group.nodes.get("Texture Coordinate")
        if named_node and getattr(named_node, "bl_idname", "") == "ShaderNodeTexCoord":
            target_nodes.append(named_node)
        else:
            target_nodes.extend(
                node for node in nightday_group.nodes
                if getattr(node, "bl_idname", "") == "ShaderNodeTexCoord"
            )
        for node in target_nodes:
            try:
                node.object = sunlight_obj
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue

    return sunlight_obj


def _ensure_atmosphere_shell_mesh():
    mesh = bpy.data.meshes.get(ATMOSPHERE_SHELL_MESH_NAME)
    if mesh is not None and len(getattr(mesh, "vertices", ())) > 0:
        try:
            if int(mesh.get(ATMOSPHERE_SHELL_MESH_VERSION_KEY, 0)) == int(ATMOSPHERE_SHELL_MESH_VERSION):
                return mesh
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if mesh is not None:
        try:
            bpy.data.meshes.remove(mesh)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        mesh = bpy.data.meshes.new(ATMOSPHERE_SHELL_MESH_NAME)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=1.0)
        try:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        bm.normal_update()
        orientation_sum = 0.0
        for face in bm.faces:
            orientation_sum += float(face.normal.dot(face.calc_center_median()))
        if orientation_sum < 0.0:
            try:
                bmesh.ops.reverse_faces(bm, faces=bm.faces)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
            bm.normal_update()
        bm.to_mesh(mesh)
        bm.free()
        for poly in mesh.polygons:
            poly.use_smooth = True
        try:
            mesh[ATMOSPHERE_SHELL_MESH_VERSION_KEY] = int(ATMOSPHERE_SHELL_MESH_VERSION)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        mesh.update()
        return mesh
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return None
    except (RuntimeError, TypeError, ValueError):
        return None


def _ensure_atmosphere_shell_shading_group():
    group = bpy.data.node_groups.get(ATMOSPHERE_SHELL_SHADING_GROUP_NAME)
    if group is None:
        try:
            group = bpy.data.node_groups.new(ATMOSPHERE_SHELL_SHADING_GROUP_NAME, "ShaderNodeTree")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        except (RuntimeError, TypeError, ValueError):
            return None

    density_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_DENSITY_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_DENSITY_SOCKET, ""),
    )
    height_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_HEIGHT_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_HEIGHT_SOCKET, ""),
    )
    falloff_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_FALLOFF_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_FALLOFF_SOCKET, ""),
    )
    color_item = _ensure_interface_socket(
        group,
        _FAKE_ATMOSPHERE_COLOR_SOCKET,
        in_out="INPUT",
        socket_type="NodeSocketColor",
        description=_SHADER_INPUT_DESCRIPTIONS.get(_FAKE_ATMOSPHERE_COLOR_SOCKET, ""),
    )

    _ensure_interface_socket(group, "Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    _ensure_interface_socket(group, _FAKE_ATMOSPHERE_DENSITY_SOCKET, in_out="OUTPUT", socket_type="NodeSocketFloat")
    _ensure_interface_socket(group, _FAKE_ATMOSPHERE_HEIGHT_SOCKET, in_out="OUTPUT", socket_type="NodeSocketFloat")
    _ensure_interface_socket(group, _FAKE_ATMOSPHERE_FALLOFF_SOCKET, in_out="OUTPUT", socket_type="NodeSocketFloat")
    _ensure_interface_socket(group, _FAKE_ATMOSPHERE_COLOR_SOCKET, in_out="OUTPUT", socket_type="NodeSocketColor")

    if density_item and hasattr(density_item, "default_value"):
        try:
            density_item.default_value = (1.0 / 3.0)
            density_item.min_value = 0.0
            density_item.max_value = 2.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if height_item and hasattr(height_item, "default_value"):
        try:
            height_item.default_value = 50.0
            height_item.min_value = 0.0
            height_item.max_value = 400.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if falloff_item and hasattr(falloff_item, "default_value"):
        try:
            falloff_item.default_value = 0.05
            falloff_item.min_value = 0.0
            falloff_item.max_value = 1.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if color_item and hasattr(color_item, "default_value"):
        try:
            color_item.default_value = _FAKE_ATMOSPHERE_DEFAULT_COLOR
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    nodes = group.nodes
    links = group.links
    for node in list(nodes):
        try:
            nodes.remove(node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
        except (RuntimeError, TypeError, ValueError):
            continue
    group_input = nodes.new("NodeGroupInput")
    group_output = nodes.new("NodeGroupOutput")
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.name = "PKA Atmosphere Transparent"
    emission = nodes.new("ShaderNodeEmission")
    emission.name = "PKA Atmosphere Emission"
    day_mask_fallback = nodes.new("ShaderNodeValue")
    day_mask_fallback.name = "PKA Atmosphere Day Mask Fallback"
    space_color_mix = nodes.new("ShaderNodeMix")
    space_color_mix.name = "PKA Atmosphere Space Color"
    horizon_color_mix = nodes.new("ShaderNodeMix")
    horizon_color_mix.name = "PKA Atmosphere Horizon Color"
    color_gradient_mix = nodes.new("ShaderNodeMix")
    color_gradient_mix.name = "PKA Atmosphere Color Gradient"
    layer_weight = nodes.new("ShaderNodeLayerWeight")
    layer_weight.name = "PKA Atmosphere Layer Weight"
    rim = nodes.new("ShaderNodeMapRange")
    rim.name = "PKA Atmosphere Rim"
    rim_power = nodes.new("ShaderNodeMath")
    rim_power.name = "PKA Atmosphere Rim Power"
    density_ui_scale = nodes.new("ShaderNodeMath")
    density_ui_scale.name = "PKA Atmosphere Density UiScale"
    density_scale = nodes.new("ShaderNodeMath")
    density_scale.name = "PKA Atmosphere Density Scale"
    height_scale = nodes.new("ShaderNodeMapRange")
    height_scale.name = "PKA Atmosphere Height Scale"
    falloff_power = nodes.new("ShaderNodeMapRange")
    falloff_power.name = "PKA Atmosphere Falloff Power"
    legacy_exp_scale = nodes.new("ShaderNodeMapRange")
    legacy_exp_scale.name = "PKA Atmosphere Legacy Exp Scale"
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.name = "PKA Atmosphere Geometry"
    view_dot = nodes.new("ShaderNodeVectorMath")
    view_dot.name = "PKA Atmosphere View Dot"
    dot_abs = nodes.new("ShaderNodeMath")
    dot_abs.name = "PKA Atmosphere Dot Abs"
    cos_sq = nodes.new("ShaderNodeMath")
    cos_sq.name = "PKA Atmosphere Cos Squared"
    sin_sq = nodes.new("ShaderNodeMath")
    sin_sq.name = "PKA Atmosphere Sin Squared"
    height_norm = nodes.new("ShaderNodeMath")
    height_norm.name = "PKA Atmosphere Height Norm"
    outer_ratio = nodes.new("ShaderNodeMath")
    outer_ratio.name = "PKA Atmosphere Outer Ratio"
    inner_ratio = nodes.new("ShaderNodeMath")
    inner_ratio.name = "PKA Atmosphere Inner Ratio"
    inner_ratio_sq = nodes.new("ShaderNodeMath")
    inner_ratio_sq.name = "PKA Atmosphere Inner Ratio Sq"
    inner_disc = nodes.new("ShaderNodeMath")
    inner_disc.name = "PKA Atmosphere Inner Disc"
    inner_disc_max = nodes.new("ShaderNodeMath")
    inner_disc_max.name = "PKA Atmosphere Inner Disc Max"
    inner_term = nodes.new("ShaderNodeMath")
    inner_term.name = "PKA Atmosphere Inner Term"
    optical_depth = nodes.new("ShaderNodeMath")
    optical_depth.name = "PKA Atmosphere Optical Depth"
    optical_depth_max = nodes.new("ShaderNodeMath")
    optical_depth_max.name = "PKA Atmosphere Optical Depth Max"
    exp_exponent = nodes.new("ShaderNodeMath")
    exp_exponent.name = "PKA Atmosphere Exp Exponent"
    exp_decay = nodes.new("ShaderNodeMath")
    exp_decay.name = "PKA Atmosphere Exp Decay"
    exp_profile = nodes.new("ShaderNodeMath")
    exp_profile.name = "PKA Atmosphere Exp Profile"
    optical_profile = nodes.new("ShaderNodeMath")
    optical_profile.name = "PKA Atmosphere Optical Profile"
    opacity_raw_mul = nodes.new("ShaderNodeMath")
    opacity_raw_mul.name = "PKA Atmosphere Opacity Raw"
    opacity_mul = nodes.new("ShaderNodeMath")
    opacity_mul.name = "PKA Atmosphere Opacity"
    emission_strength_mul = nodes.new("ShaderNodeMath")
    emission_strength_mul.name = "PKA Atmosphere Emission Strength"
    emission_strength_add = nodes.new("ShaderNodeMath")
    emission_strength_add.name = "PKA Atmosphere Emission Offset"
    emission_rim_scale = nodes.new("ShaderNodeMapRange")
    emission_rim_scale.name = "PKA Atmosphere Emission Rim Scale"
    emission_day_mul = nodes.new("ShaderNodeMath")
    emission_day_mul.name = "PKA Atmosphere Emission Day"
    emission_total_mul = nodes.new("ShaderNodeMath")
    emission_total_mul.name = "PKA Atmosphere Emission Total"
    mix_shader = nodes.new("ShaderNodeMixShader")
    mix_shader.name = "PKA Atmosphere Mix"

    try:
        day_mask_fallback.outputs[0].default_value = 1.0
        emission.inputs["Color"].default_value = _FAKE_ATMOSPHERE_DEFAULT_COLOR
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, KeyError, IndexError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    _safe_setattr(space_color_mix, "data_type", "RGBA")
    _safe_setattr(space_color_mix, "blend_type", "MIX")
    _safe_setattr(horizon_color_mix, "data_type", "RGBA")
    _safe_setattr(horizon_color_mix, "blend_type", "MIX")
    _safe_setattr(color_gradient_mix, "data_type", "RGBA")
    _safe_setattr(color_gradient_mix, "blend_type", "MIX")
    _safe_setattr(rim, "clamp", True)
    _safe_setattr(height_scale, "clamp", True)
    _safe_setattr(falloff_power, "clamp", True)
    _safe_setattr(legacy_exp_scale, "clamp", True)
    _safe_setattr(emission_rim_scale, "clamp", True)
    _safe_setattr(rim_power, "operation", "POWER")
    _safe_setattr(view_dot, "operation", "DOT_PRODUCT")
    _safe_setattr(dot_abs, "operation", "ABSOLUTE")
    _safe_setattr(cos_sq, "operation", "MULTIPLY")
    _safe_setattr(sin_sq, "operation", "SUBTRACT")
    _safe_setattr(height_norm, "operation", "DIVIDE")
    _safe_setattr(outer_ratio, "operation", "ADD")
    _safe_setattr(inner_ratio, "operation", "DIVIDE")
    _safe_setattr(inner_ratio_sq, "operation", "MULTIPLY")
    _safe_setattr(inner_disc, "operation", "SUBTRACT")
    _safe_setattr(inner_disc_max, "operation", "MAXIMUM")
    _safe_setattr(inner_term, "operation", "SQRT")
    _safe_setattr(optical_depth, "operation", "SUBTRACT")
    _safe_setattr(optical_depth_max, "operation", "MAXIMUM")
    _safe_setattr(exp_exponent, "operation", "MULTIPLY")
    _safe_setattr(exp_decay, "operation", "POWER")
    _safe_setattr(exp_profile, "operation", "SUBTRACT")
    _safe_setattr(optical_profile, "operation", "MULTIPLY")
    _safe_setattr(density_ui_scale, "operation", "MULTIPLY")
    _safe_setattr(density_scale, "operation", "MULTIPLY")
    _safe_setattr(density_scale, "use_clamp", True)
    _safe_setattr(opacity_raw_mul, "operation", "MULTIPLY")
    _safe_setattr(opacity_raw_mul, "use_clamp", True)
    _safe_setattr(opacity_mul, "operation", "MULTIPLY")
    _safe_setattr(opacity_mul, "use_clamp", True)
    _safe_setattr(emission_strength_mul, "operation", "MULTIPLY")
    _safe_setattr(emission_strength_add, "operation", "ADD")
    _safe_setattr(emission_day_mul, "operation", "MULTIPLY")
    _safe_setattr(emission_total_mul, "operation", "MULTIPLY")

    try:
        rim.inputs[1].default_value = 0.0
        rim.inputs[2].default_value = 1.0
        rim.inputs[3].default_value = 0.0
        rim.inputs[4].default_value = 1.0

        height_scale.inputs[1].default_value = 0.0
        height_scale.inputs[2].default_value = 400.0
        height_scale.inputs[3].default_value = 0.65
        height_scale.inputs[4].default_value = 1.35

        falloff_power.inputs[1].default_value = 0.0
        falloff_power.inputs[2].default_value = 1.0
        falloff_power.inputs[3].default_value = 1.0
        falloff_power.inputs[4].default_value = 8.0

        legacy_exp_scale.inputs[1].default_value = 0.0
        legacy_exp_scale.inputs[2].default_value = 1.0
        legacy_exp_scale.inputs[3].default_value = 16.0
        legacy_exp_scale.inputs[4].default_value = 4.0

        sin_sq.inputs[0].default_value = 1.0
        height_norm.inputs[1].default_value = 6371.0
        outer_ratio.inputs[0].default_value = 1.0
        inner_ratio.inputs[0].default_value = 1.0
        inner_disc_max.inputs[1].default_value = 0.0
        optical_depth_max.inputs[1].default_value = 0.0
        exp_decay.inputs[0].default_value = 0.5
        exp_profile.inputs[0].default_value = 1.0

        density_ui_scale.inputs[1].default_value = float(_FAKE_ATMOSPHERE_DENSITY_UI_TO_SHADER)

        space_color_mix.inputs[0].default_value = 0.72
        _socket_input_by_name_or_index(space_color_mix.inputs, "B", 7).default_value = (0.03, 0.05, 0.10, 1.0)
        horizon_color_mix.inputs[0].default_value = 0.85
        _socket_input_by_name_or_index(horizon_color_mix.inputs, "B", 7).default_value = (1.0, 1.0, 1.0, 1.0)

        emission_rim_scale.inputs[1].default_value = 0.0
        emission_rim_scale.inputs[2].default_value = 1.0
        emission_rim_scale.inputs[3].default_value = 1.0
        emission_rim_scale.inputs[4].default_value = 3.0
        density_scale.inputs[1].default_value = 1.0
        emission_strength_mul.inputs[1].default_value = 10.0
        emission_strength_add.inputs[0].default_value = 0.35
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    def _input_idx(node, idx):
        try:
            return node.inputs[idx]
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            return None

    links.new(layer_weight.outputs.get("Fresnel"), rim.inputs[0])
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(density_ui_scale.inputs, "Value", 0),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET),
    )
    links.new(density_ui_scale.outputs[0], density_scale.inputs[0])
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(height_scale.inputs, "Value", 0),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET),
    )
    links.new(height_scale.outputs.get("Result"), density_scale.inputs[1])
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(falloff_power.inputs, "Value", 0),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(legacy_exp_scale.inputs, "Value", 0),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET),
    )
    links.new(falloff_power.outputs.get("Result"), rim_power.inputs[1])
    links.new(rim.outputs.get("Result"), rim_power.inputs[0])

    _replace_input_link(
        links,
        _input_idx(view_dot, 0),
        _socket_output_by_name_or_index(geometry.outputs, "Normal", 1),
    )
    _replace_input_link(
        links,
        _input_idx(view_dot, 1),
        _socket_output_by_name_or_index(geometry.outputs, "Incoming", 4),
    )
    _replace_input_link(
        links,
        _input_idx(dot_abs, 0),
        _socket_output_by_name_or_index(view_dot.outputs, "Value", 1),
    )
    _replace_input_link(
        links,
        _input_idx(cos_sq, 0),
        _socket_output_by_name_or_index(dot_abs.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(cos_sq, 1),
        _socket_output_by_name_or_index(dot_abs.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(sin_sq, 1),
        _socket_output_by_name_or_index(cos_sq.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(height_norm, 0),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET),
    )
    _replace_input_link(
        links,
        _input_idx(outer_ratio, 1),
        _socket_output_by_name_or_index(height_norm.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(inner_ratio, 1),
        _socket_output_by_name_or_index(outer_ratio.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(inner_ratio_sq, 0),
        _socket_output_by_name_or_index(inner_ratio.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(inner_ratio_sq, 1),
        _socket_output_by_name_or_index(inner_ratio.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(inner_disc, 0),
        _socket_output_by_name_or_index(inner_ratio_sq.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(inner_disc, 1),
        _socket_output_by_name_or_index(sin_sq.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(inner_disc_max, 0),
        _socket_output_by_name_or_index(inner_disc.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(inner_term, 0),
        _socket_output_by_name_or_index(inner_disc_max.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(optical_depth, 0),
        _socket_output_by_name_or_index(dot_abs.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(optical_depth, 1),
        _socket_output_by_name_or_index(inner_term.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(optical_depth_max, 0),
        _socket_output_by_name_or_index(optical_depth.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(exp_exponent, 0),
        _socket_output_by_name_or_index(optical_depth_max.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(exp_exponent, 1),
        _socket_output_by_name_or_index(legacy_exp_scale.outputs, "Result", 0),
    )
    _replace_input_link(
        links,
        _input_idx(exp_decay, 1),
        _socket_output_by_name_or_index(exp_exponent.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(exp_profile, 1),
        _socket_output_by_name_or_index(exp_decay.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(optical_profile, 0),
        _socket_output_by_name_or_index(exp_profile.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(optical_profile, 1),
        _socket_output_by_name_or_index(rim_power.outputs, "Value", 0),
    )
    links.new(optical_profile.outputs.get("Value"), opacity_raw_mul.inputs[0])
    links.new(density_scale.outputs[0], opacity_raw_mul.inputs[1])

    day_mask_output = _socket_output_by_name_or_index(day_mask_fallback.outputs, "Value", 0)
    _replace_input_link(
        links,
        _input_idx(opacity_mul, 0),
        _socket_output_by_name_or_index(opacity_raw_mul.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(opacity_mul, 1),
        day_mask_output,
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(space_color_mix.inputs, "A", 6),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_COLOR_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(horizon_color_mix.inputs, "A", 6),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_COLOR_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(color_gradient_mix.inputs, "Factor", 0),
        _socket_output_by_name_or_index(rim_power.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(color_gradient_mix.inputs, "A", 6),
        _socket_output_by_name_or_index(space_color_mix.outputs, "Result", 2),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(color_gradient_mix.inputs, "B", 7),
        _socket_output_by_name_or_index(horizon_color_mix.outputs, "Result", 2),
    )
    _replace_input_link(
        links,
        emission.inputs.get("Color"),
        _socket_output_by_name_or_index(color_gradient_mix.outputs, "Result", 2),
    )
    _replace_input_link(
        links,
        _input_idx(mix_shader, 0),
        _socket_output_by_name_or_index(opacity_mul.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(mix_shader, 1),
        _socket_output_by_name_or_index(transparent.outputs, "BSDF", 0),
    )
    _replace_input_link(
        links,
        _input_idx(mix_shader, 2),
        _socket_output_by_name_or_index(emission.outputs, "Emission", 0),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(group_output.inputs, "Shader"),
        _socket_output_by_name_or_index(mix_shader.outputs, "Shader", 0),
    )
    links.new(density_scale.outputs[0], emission_strength_mul.inputs[0])
    links.new(emission_strength_mul.outputs[0], emission_strength_add.inputs[1])
    links.new(optical_profile.outputs.get("Value"), emission_rim_scale.inputs[0])
    _replace_input_link(
        links,
        _input_idx(emission_day_mul, 0),
        _socket_output_by_name_or_index(emission_strength_add.outputs, "Value", 0),
    )
    _replace_input_link(
        links,
        _input_idx(emission_day_mul, 1),
        day_mask_output,
    )
    links.new(emission_day_mul.outputs[0], emission_total_mul.inputs[0])
    links.new(emission_rim_scale.outputs.get("Result"), emission_total_mul.inputs[1])
    links.new(emission_total_mul.outputs[0], emission.inputs.get("Strength"))

    _replace_input_link(
        links,
        _socket_input_by_name_or_index(group_output.inputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(group_output.inputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(group_output.inputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET),
    )
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(group_output.inputs, _FAKE_ATMOSPHERE_COLOR_SOCKET),
        _socket_output_by_name_or_index(group_input.outputs, _FAKE_ATMOSPHERE_COLOR_SOCKET),
    )

    _safe_set_node_location(group_input, -1330.0, -40.0)
    _safe_set_node_location(day_mask_fallback, -1120.0, -640.0)
    _safe_set_node_location(space_color_mix, -880.0, 470.0)
    _safe_set_node_location(horizon_color_mix, -880.0, 330.0)
    _safe_set_node_location(color_gradient_mix, -650.0, 400.0)
    _safe_set_node_location(layer_weight, -1120.0, 160.0)
    _safe_set_node_location(rim, -650.0, 160.0)
    _safe_set_node_location(rim_power, -430.0, 160.0)
    _safe_set_node_location(geometry, -1120.0, -560.0)
    _safe_set_node_location(view_dot, -880.0, -560.0)
    _safe_set_node_location(dot_abs, -650.0, -560.0)
    _safe_set_node_location(cos_sq, -430.0, -560.0)
    _safe_set_node_location(sin_sq, -210.0, -560.0)
    _safe_set_node_location(height_norm, -880.0, -760.0)
    _safe_set_node_location(outer_ratio, -650.0, -760.0)
    _safe_set_node_location(inner_ratio, -430.0, -760.0)
    _safe_set_node_location(inner_ratio_sq, -210.0, -760.0)
    _safe_set_node_location(inner_disc, 10.0, -760.0)
    _safe_set_node_location(inner_disc_max, 230.0, -760.0)
    _safe_set_node_location(inner_term, 450.0, -760.0)
    _safe_set_node_location(optical_depth, 450.0, -560.0)
    _safe_set_node_location(optical_depth_max, 670.0, -560.0)
    _safe_set_node_location(legacy_exp_scale, 670.0, -760.0)
    _safe_set_node_location(exp_exponent, 900.0, -650.0)
    _safe_set_node_location(exp_decay, 1120.0, -650.0)
    _safe_set_node_location(exp_profile, 1340.0, -650.0)
    _safe_set_node_location(optical_profile, 1560.0, -500.0)
    _safe_set_node_location(density_ui_scale, -880.0, -40.0)
    _safe_set_node_location(density_scale, -650.0, -40.0)
    _safe_set_node_location(height_scale, -410.0, -40.0)
    _safe_set_node_location(falloff_power, -650.0, -420.0)
    _safe_set_node_location(opacity_raw_mul, -190.0, -40.0)
    _safe_set_node_location(opacity_mul, 40.0, -40.0)
    _safe_set_node_location(transparent, 40.0, 10.0)
    _safe_set_node_location(emission, 40.0, 230.0)
    _safe_set_node_location(emission_strength_mul, -410.0, -230.0)
    _safe_set_node_location(emission_strength_add, -190.0, -230.0)
    _safe_set_node_location(emission_rim_scale, -430.0, -110.0)
    _safe_set_node_location(emission_day_mul, 20.0, -230.0)
    _safe_set_node_location(emission_total_mul, 240.0, -180.0)
    _safe_set_node_location(mix_shader, 270.0, 90.0)
    _safe_set_node_location(group_output, 510.0, 90.0)

    group.use_fake_user = True
    return group


def _get_atmosphere_shell_shading_node(node_tree):
    if node_tree is None or not hasattr(node_tree, "nodes"):
        return None
    nodes = node_tree.nodes
    node = nodes.get("PKA Atmosphere Shell Shading")
    if (
        node is not None
        and str(getattr(node, "bl_idname", "")) == "ShaderNodeGroup"
        and str(getattr(getattr(node, "node_tree", None), "name", "")) == ATMOSPHERE_SHELL_SHADING_GROUP_NAME
    ):
        return node
    for candidate in nodes:
        if str(getattr(candidate, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        if str(getattr(getattr(candidate, "node_tree", None), "name", "")) == ATMOSPHERE_SHELL_SHADING_GROUP_NAME:
            return candidate
    return None


def _read_atmosphere_shell_values_from_material(material):
    defaults = {
        "density": (1.0 / 3.0),
        "height_km": 50.0,
        "falloff": 0.05,
        "color": _FAKE_ATMOSPHERE_DEFAULT_COLOR,
    }
    node_tree = getattr(material, "node_tree", None) if material else None
    nodes = getattr(node_tree, "nodes", None) if node_tree else None
    if nodes is None:
        return defaults

    shell_node = _get_atmosphere_shell_shading_node(node_tree)
    try:
        if shell_node is not None:
            density_in = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET)
            height_in = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET)
            falloff_in = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET)
            color_in = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_COLOR_SOCKET)
            if density_in is not None:
                defaults["density"] = float(density_in.default_value)
            if height_in is not None:
                defaults["height_km"] = float(height_in.default_value)
            if falloff_in is not None:
                defaults["falloff"] = float(falloff_in.default_value)
            if color_in is not None:
                defaults["color"] = tuple(float(color_in.default_value[i]) for i in range(4))
        else:
            density_node = nodes.get("PKA Atmosphere Density")
            height_node = nodes.get("PKA Atmosphere HeightKm")
            falloff_node = nodes.get("PKA Atmosphere Falloff")
            color_node = nodes.get("PKA Atmosphere Color")
            if density_node and density_node.outputs:
                defaults["density"] = float(density_node.outputs[0].default_value)
            if height_node and height_node.outputs:
                defaults["height_km"] = float(height_node.outputs[0].default_value)
            if falloff_node and falloff_node.outputs:
                defaults["falloff"] = float(falloff_node.outputs[0].default_value)
            if color_node and color_node.outputs:
                defaults["color"] = tuple(float(color_node.outputs[0].default_value[i]) for i in range(4))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return defaults


def _enforce_atmosphere_shell_mix_links(material):
    node_tree = getattr(material, "node_tree", None) if material else None
    nodes = getattr(node_tree, "nodes", None) if node_tree else None
    links = getattr(node_tree, "links", None) if node_tree else None
    if nodes is None or links is None:
        return

    opacity_mul = nodes.get("PKA Atmosphere Opacity")
    transparent = nodes.get("PKA Atmosphere Transparent")
    emission = nodes.get("PKA Atmosphere Emission")
    output = nodes.get("PKA Atmosphere Output")
    mix_shaders = [node for node in nodes if str(getattr(node, "bl_idname", "")) == "ShaderNodeMixShader"]
    if not mix_shaders:
        return

    preferred_mix = nodes.get("PKA Atmosphere Mix")
    if preferred_mix not in mix_shaders:
        preferred_mix = mix_shaders[0]

    for mix_shader in mix_shaders:
        mix_inputs = getattr(mix_shader, "inputs", None)
        if mix_inputs is None:
            continue
        try:
            fac_in = mix_inputs[0] if len(mix_inputs) > 0 else None
            shader1_in = mix_inputs[1] if len(mix_inputs) > 1 else None
            shader2_in = mix_inputs[2] if len(mix_inputs) > 2 else None
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            fac_in = None
            shader1_in = None
            shader2_in = None

        _replace_input_link(
            links,
            fac_in,
            _socket_output_by_name_or_index(getattr(opacity_mul, "outputs", None), "Value", 0),
        )
        _replace_input_link(
            links,
            shader1_in,
            _socket_output_by_name_or_index(getattr(transparent, "outputs", None), "BSDF", 0),
        )
        _replace_input_link(
            links,
            shader2_in,
            _socket_output_by_name_or_index(getattr(emission, "outputs", None), "Emission", 0),
        )

    _replace_input_link(
        links,
        _socket_input_by_name_or_index(getattr(output, "inputs", None), "Surface", 0),
        _socket_output_by_name_or_index(getattr(preferred_mix, "outputs", None), "Shader", 0),
    )


def _ensure_atmosphere_shell_material():
    material = bpy.data.materials.get(ATMOSPHERE_SHELL_MATERIAL_NAME)
    if material is None:
        try:
            material = bpy.data.materials.new(ATMOSPHERE_SHELL_MATERIAL_NAME)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        except (RuntimeError, TypeError, ValueError):
            return None

    material.use_nodes = True
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return None
    nodes = node_tree.nodes
    links = node_tree.links

    for node in list(nodes):
        try:
            nodes.remove(node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue

    shell_group = _ensure_atmosphere_shell_shading_group()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.name = "PKA Atmosphere Output"
    shell_node = nodes.new("ShaderNodeGroup")
    shell_node.name = "PKA Atmosphere Shell Shading"
    if shell_group is not None:
        try:
            shell_node.node_tree = shell_group
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    _replace_input_link(
        links,
        _socket_input_by_name_or_index(output.inputs, "Surface", 0),
        _socket_output_by_name_or_index(shell_node.outputs, "Shader", 0),
    )

    _safe_set_node_location(shell_node, -180.0, 90.0)
    _safe_set_node_location(output, 80.0, 90.0)

    if hasattr(material, "blend_method"):
        try:
            material.blend_method = 'HASHED'
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if hasattr(material, "shadow_method"):
        try:
            material.shadow_method = 'NONE'
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if hasattr(material, "use_backface_culling"):
        try:
            material.use_backface_culling = False
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    if hasattr(material, "show_transparent_back"):
        try:
            material.show_transparent_back = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        material[ATMOSPHERE_SHELL_MATERIAL_VERSION_KEY] = int(ATMOSPHERE_SHELL_MATERIAL_VERSION)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    material.use_fake_user = True
    return material


def _ensure_atmosphere_shell_object(surface_collection, earth_obj):
    shell_obj = bpy.data.objects.get(ATMOSPHERE_SHELL_OBJECT_NAME)
    if shell_obj is not None and str(getattr(shell_obj, "type", "")) != "MESH":
        try:
            bpy.data.objects.remove(shell_obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        shell_obj = None

    mesh = _ensure_atmosphere_shell_mesh()
    if mesh is None:
        return None

    if shell_obj is None:
        try:
            shell_obj = bpy.data.objects.new(ATMOSPHERE_SHELL_OBJECT_NAME, mesh)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            return None
        except (RuntimeError, TypeError, ValueError):
            return None
    else:
        shell_obj.data = mesh

    if surface_collection is not None:
        for collection in list(getattr(shell_obj, "users_collection", ())):
            if collection is surface_collection:
                continue
            try:
                collection.objects.unlink(shell_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        if shell_obj.name not in surface_collection.objects:
            try:
                surface_collection.objects.link(shell_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    material = _ensure_atmosphere_shell_material()
    if material is not None:
        mats = getattr(getattr(shell_obj, "data", None), "materials", None)
        if mats is not None:
            try:
                if len(mats) == 0:
                    mats.append(material)
                else:
                    mats[0] = material
                while len(mats) > 1:
                    mats.pop(index=len(mats) - 1)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        try:
            shell_obj.active_material = material
            if hasattr(shell_obj, "active_material_index"):
                shell_obj.active_material_index = 0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    if earth_obj is not None:
        try:
            if shell_obj.parent is not earth_obj:
                shell_obj.parent = earth_obj
            shell_obj.location = (0.0, 0.0, 0.0)
            shell_obj.rotation_euler = (0.0, 0.0, 0.0)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    if hasattr(shell_obj, "visible_shadow"):
        try:
            shell_obj.visible_shadow = False
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    return shell_obj


def _earth_surface_local_radius(earth_obj):
    if earth_obj is None:
        return 1.0
    try:
        stored = float(earth_obj.get("planetka_surface_local_radius", 0.0))
        if stored > 1e-6:
            return stored
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None) if mesh_data is not None else None
    if vertices:
        try:
            inferred = max(v.co.length for v in vertices)
            if inferred > 1e-6:
                return float(inferred)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return 1.0


def apply_fake_atmosphere_shell(
    scene=None,
    enabled=False,
    density=0.0,
    height_km=50.0,
    falloff=0.05,
    color=_FAKE_ATMOSPHERE_DEFAULT_COLOR,
):
    scene = scene or getattr(bpy.context, "scene", None)
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None

    root = getattr(scene, "collection", None) if scene else None
    surface_collection = _ensure_collection(root, SURFACE_COLLECTION_NAME) if root is not None else bpy.data.collections.get(SURFACE_COLLECTION_NAME)
    shell_obj = _ensure_atmosphere_shell_object(surface_collection, earth_obj)
    if shell_obj is None:
        return None

    density_value = max(0.0, min(2.0, float(density)))
    height_value = max(0.0, min(400.0, float(height_km)))
    falloff_value = max(0.0, min(1.0, float(falloff)))
    try:
        color_value = (
            max(0.0, min(1.0, float(color[0]))),
            max(0.0, min(1.0, float(color[1]))),
            max(0.0, min(1.0, float(color[2]))),
            max(0.0, min(1.0, float(color[3]))),
        )
    except (TypeError, ValueError, IndexError):
        color_value = _FAKE_ATMOSPHERE_DEFAULT_COLOR
    earth_local_radius = _earth_surface_local_radius(earth_obj)
    scale_mult = earth_local_radius * (1.0 + (height_value / 6371.0))

    try:
        shell_obj.scale = (scale_mult, scale_mult, scale_mult)
        shell_obj.hide_viewport = not bool(enabled)
        shell_obj.hide_render = not bool(enabled)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    material = getattr(shell_obj, "active_material", None)
    node_tree = getattr(material, "node_tree", None) if material else None
    nodes = getattr(node_tree, "nodes", None) if node_tree else None
    if nodes is not None:
        try:
            shell_node = _get_atmosphere_shell_shading_node(node_tree)
            if shell_node is not None:
                density_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET)
                height_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET)
                falloff_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET)
                color_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_COLOR_SOCKET)
                if density_socket is not None:
                    density_socket.default_value = density_value
                if height_socket is not None:
                    height_socket.default_value = height_value
                if falloff_socket is not None:
                    falloff_socket.default_value = falloff_value
                if color_socket is not None:
                    color_socket.default_value = color_value
            else:
                # Legacy fallback for old materials before group migration.
                density_node = nodes.get("PKA Atmosphere Density")
                height_node = nodes.get("PKA Atmosphere HeightKm")
                falloff_node = nodes.get("PKA Atmosphere Falloff")
                color_node = nodes.get("PKA Atmosphere Color")
                if density_node is not None and getattr(density_node, "outputs", None):
                    density_node.outputs[0].default_value = density_value
                if height_node is not None and getattr(height_node, "outputs", None):
                    height_node.outputs[0].default_value = height_value
                if falloff_node is not None and getattr(falloff_node, "outputs", None):
                    falloff_node.outputs[0].default_value = falloff_value
                if color_node is not None and getattr(color_node, "outputs", None):
                    color_node.outputs[0].default_value = color_value
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return shell_obj


def read_fake_atmosphere_shell_inputs(scene=None):
    _scene = scene or getattr(bpy.context, "scene", None)
    shell_obj = bpy.data.objects.get(ATMOSPHERE_SHELL_OBJECT_NAME)
    if shell_obj is None and _scene is not None:
        surface_collection = bpy.data.collections.get(SURFACE_COLLECTION_NAME)
        if surface_collection is not None:
            shell_obj = surface_collection.objects.get(ATMOSPHERE_SHELL_OBJECT_NAME)
    if shell_obj is None:
        return None

    material = getattr(shell_obj, "active_material", None)
    node_tree = getattr(material, "node_tree", None) if material else None
    nodes = getattr(node_tree, "nodes", None) if node_tree else None
    if nodes is None:
        return None

    result = {
        "enabled": not bool(getattr(shell_obj, "hide_viewport", False)),
        "density": (1.0 / 3.0),
        "height_km": 50.0,
        "falloff": 0.05,
        "color": _FAKE_ATMOSPHERE_DEFAULT_COLOR,
    }
    try:
        shell_node = _get_atmosphere_shell_shading_node(node_tree)
        if shell_node is not None:
            density_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_DENSITY_SOCKET)
            height_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_HEIGHT_SOCKET)
            falloff_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_FALLOFF_SOCKET)
            color_socket = _socket_input_by_name_or_index(shell_node.inputs, _FAKE_ATMOSPHERE_COLOR_SOCKET)
            if density_socket is not None:
                result["density"] = float(density_socket.default_value)
            if height_socket is not None:
                result["height_km"] = float(height_socket.default_value)
            if falloff_socket is not None:
                result["falloff"] = float(falloff_socket.default_value)
            if color_socket is not None:
                result["color"] = tuple(float(color_socket.default_value[i]) for i in range(4))
        else:
            density_node = nodes.get("PKA Atmosphere Density")
            height_node = nodes.get("PKA Atmosphere HeightKm")
            falloff_node = nodes.get("PKA Atmosphere Falloff")
            color_node = nodes.get("PKA Atmosphere Color")
            if density_node is not None and getattr(density_node, "outputs", None):
                result["density"] = float(density_node.outputs[0].default_value)
            if height_node is not None and getattr(height_node, "outputs", None):
                result["height_km"] = float(height_node.outputs[0].default_value)
            if falloff_node is not None and getattr(falloff_node, "outputs", None):
                result["falloff"] = float(falloff_node.outputs[0].default_value)
            if color_node is not None and getattr(color_node, "outputs", None):
                result["color"] = tuple(float(color_node.outputs[0].default_value[i]) for i in range(4))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, IndexError):
        return None
    return result


def _set_library_signature(id_block):
    if not id_block:
        return
    try:
        id_block[_LIBRARY_SIGNATURE_KEY] = MATERIAL_LIBRARY_SHA256
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _has_library_signature(id_block):
    if not id_block:
        return False
    try:
        return id_block.get(_LIBRARY_SIGNATURE_KEY) == MATERIAL_LIBRARY_SHA256
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False


def _remove_material_if_exists(name):
    material = bpy.data.materials.get(name)
    if material is None:
        return
    try:
        bpy.data.materials.remove(material, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _remove_node_group_if_exists(name):
    node_group = bpy.data.node_groups.get(name)
    if node_group is None:
        return
    try:
        bpy.data.node_groups.remove(node_group, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _clear_animation_data(id_block):
    if not id_block:
        return
    try:
        if getattr(id_block, "animation_data", None):
            id_block.animation_data_clear()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _sanitize_embedded_assets():
    for group_name in MATERIAL_LIBRARY_NODE_GROUPS:
        node_group = bpy.data.node_groups.get(group_name)
        if not node_group:
            continue
        _clear_animation_data(node_group)
        for node in node_group.nodes:
            if node.bl_idname == "ShaderNodeTexImage":
                node.image = None

    for material_name in MATERIAL_LIBRARY_MATERIALS:
        material = bpy.data.materials.get(material_name)
        if not material or not material.use_nodes or not material.node_tree:
            continue
        _clear_animation_data(material)
        _clear_animation_data(material.node_tree)
        for node in material.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage":
                node.image = None


def _load_static_image(image_name):
    spec = _STATIC_IMAGE_SPECS.get(image_name)
    if not spec:
        raise RuntimeError(f"Planetka: missing static image specification for '{image_name}'.")

    image_path = os.path.join(os.path.dirname(__file__), *spec["relative_path"])
    if not os.path.isfile(image_path):
        raise RuntimeError(f"Planetka: required static image is missing: {image_path}")

    image = bpy.data.images.load(image_path, check_existing=True)
    image.filepath = image_path
    image.source = 'FILE'

    colorspace = spec.get("colorspace")
    _set_image_colorspace_safe(image, colorspace)

    alpha_mode = spec.get("alpha_mode")
    if alpha_mode and hasattr(image, "alpha_mode"):
        image.alpha_mode = alpha_mode

    return image


def _bind_static_images():
    preview_material = bpy.data.materials.get(LEGACY_PREVIEW_MATERIAL_NAME)
    if preview_material and preview_material.use_nodes and preview_material.node_tree:
        for node_name, image_name in _PREVIEW_IMAGE_BINDINGS:
            node = preview_material.node_tree.nodes.get(node_name)
            if not node or node.bl_idname != "ShaderNodeTexImage":
                continue
            node.image = _load_static_image(image_name)

    surface_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if not surface_group:
        raise RuntimeError(f"Planetka: node group '{SURFACE_GRADING_GROUP_NAME}' is missing.")

    for node_name, image_name in _SURFACE_GROUP_IMAGE_BINDINGS:
        node = surface_group.nodes.get(node_name)
        if not node or node.bl_idname != "ShaderNodeTexImage":
            raise RuntimeError(
                f"Planetka: expected image node '{node_name}' in node group '{SURFACE_GRADING_GROUP_NAME}' was not found."
            )
        node.image = _load_static_image(image_name)


def _build_preview_texture_loading_group():
    existing_group = bpy.data.node_groups.get(PREVIEW_TEXTURE_LOADING_GROUP_NAME)
    if existing_group:
        try:
            bpy.data.node_groups.remove(existing_group, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    source_group = bpy.data.node_groups.get(TEXTURE_LOADING_GROUP_NAME)
    if not source_group:
        raise RuntimeError(f"Planetka: node group '{TEXTURE_LOADING_GROUP_NAME}' is missing.")

    group = source_group.copy()
    group.name = PREVIEW_TEXTURE_LOADING_GROUP_NAME
    group.use_fake_user = True

    for node in list(group.nodes):
        if node.type != "GROUP_OUTPUT":
            group.nodes.remove(node)
    for link in list(group.links):
        group.links.remove(link)

    output_node = next((node for node in group.nodes if node.type == "GROUP_OUTPUT"), None)
    if output_node is None:
        raise RuntimeError("Planetka: preview texture loading output node is missing.")

    node_s2 = group.nodes.new("ShaderNodeTexImage")
    node_s2.name = "Preview S2"
    node_s2.label = "Preview S2"
    node_s2.location = (-640.0, 260.0)
    node_s2.image = _load_static_image("S2_x000_y000_z360_d360.exr")

    node_wt = group.nodes.new("ShaderNodeTexImage")
    node_wt.name = "Preview WT"
    node_wt.label = "Preview WT"
    node_wt.location = (-640.0, -20.0)
    node_wt.image = _load_static_image("WT_x000_y000_z360_d360.exr")

    node_po = group.nodes.new("ShaderNodeTexImage")
    node_po.name = "Preview PO"
    node_po.label = "Preview PO"
    node_po.location = (-640.0, -300.0)
    node_po.image = _load_static_image("PO_x000_y000_z360_d360.tif")

    node_el = group.nodes.new("ShaderNodeValue")
    node_el.name = "Preview EL"
    node_el.label = "Preview EL"
    node_el.location = (-640.0, -520.0)
    node_el.outputs[0].default_value = 0.0

    outputs = {socket.name: socket for socket in output_node.inputs}
    required_outputs = ("S2", "EL", "WT", "Alpha", "SE")
    missing_outputs = [name for name in required_outputs if name not in outputs]
    if missing_outputs:
        raise RuntimeError(
            f"Planetka: preview texture loading outputs are missing: {missing_outputs}"
        )

    group.links.new(node_s2.outputs["Color"], outputs["S2"])
    group.links.new(node_el.outputs[0], outputs["EL"])
    group.links.new(node_wt.outputs["Color"], outputs["WT"])
    group.links.new(node_wt.outputs["Alpha"], outputs["Alpha"])
    group.links.new(node_po.outputs["Color"], outputs["SE"])

    group[_PREVIEW_TEXTURE_GROUP_VERSION_KEY] = _PREVIEW_TEXTURE_GROUP_VERSION
    return group


def _is_preview_texture_loading_group_ready(group):
    if not group:
        return False
    try:
        return int(group.get(_PREVIEW_TEXTURE_GROUP_VERSION_KEY, 0)) == _PREVIEW_TEXTURE_GROUP_VERSION
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False


def _ensure_preview_texture_loading_group():
    group = bpy.data.node_groups.get(PREVIEW_TEXTURE_LOADING_GROUP_NAME)
    if _is_preview_texture_loading_group_ready(group):
        for node_name, image_name in (
            ("Preview S2", "S2_x000_y000_z360_d360.exr"),
            ("Preview WT", "WT_x000_y000_z360_d360.exr"),
            ("Preview PO", "PO_x000_y000_z360_d360.tif"),
        ):
            node = group.nodes.get(node_name)
            if node and node.bl_idname == "ShaderNodeTexImage":
                node.image = _load_static_image(image_name)
        return group
    return _build_preview_texture_loading_group()


def _ensure_preview_material(earth_material):
    if not earth_material or not earth_material.use_nodes or not earth_material.node_tree:
        raise RuntimeError("Planetka: earth material node tree is missing.")

    preview_material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)
    needs_rebuild = not (
        preview_material
        and preview_material.use_nodes
        and preview_material.node_tree
        and preview_material.node_tree.nodes.get("Planetka Textures Loading")
    )

    if needs_rebuild:
        if preview_material:
            try:
                bpy.data.materials.remove(preview_material, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        preview_material = earth_material.copy()
        preview_material.name = PREVIEW_MATERIAL_NAME

    texture_loading_node = preview_material.node_tree.nodes.get("Planetka Textures Loading")
    if not texture_loading_node or texture_loading_node.bl_idname != "ShaderNodeGroup":
        try:
            bpy.data.materials.remove(preview_material, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        preview_material = earth_material.copy()
        preview_material.name = PREVIEW_MATERIAL_NAME
        texture_loading_node = preview_material.node_tree.nodes.get("Planetka Textures Loading")
        if not texture_loading_node or texture_loading_node.bl_idname != "ShaderNodeGroup":
            raise RuntimeError(
                "Planetka: preview material must contain a 'Planetka Textures Loading' group node."
            )

    texture_loading_node.node_tree = _ensure_preview_texture_loading_group()
    preview_material.use_fake_user = True
    return preview_material


def _is_embedded_material_library_ready():
    for material_name in MATERIAL_LIBRARY_MATERIALS:
        material = bpy.data.materials.get(material_name)
        if not material or not _has_library_signature(material):
            return False
    for group_name in MATERIAL_LIBRARY_NODE_GROUPS:
        node_group = bpy.data.node_groups.get(group_name)
        if not node_group or not _has_library_signature(node_group):
            return False
    return True


def _load_embedded_material_library():
    for material_name in MATERIAL_LIBRARY_MATERIALS:
        _remove_material_if_exists(material_name)
    for group_name in MATERIAL_LIBRARY_NODE_GROUPS:
        _remove_node_group_if_exists(group_name)

    legacy_path = _legacy_material_library_path()
    if bpy.app.version < (5, 0, 0) and os.path.isfile(legacy_path):
        _append_material_library_from_blend(legacy_path)
    else:
        temp_path = ""
        load_error = None
        try:
            with tempfile.NamedTemporaryFile(prefix="planetka_material_lib_", suffix=".blend", delete=False) as handle:
                handle.write(_get_embedded_material_library_payload())
                temp_path = handle.name

            _append_material_library_from_blend(temp_path)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            load_error = exc
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

        if load_error is not None:
            if not os.path.isfile(legacy_path):
                raise load_error
            _append_material_library_from_blend(legacy_path)

    missing_materials = [name for name in MATERIAL_LIBRARY_MATERIALS if bpy.data.materials.get(name) is None]
    missing_groups = [name for name in MATERIAL_LIBRARY_NODE_GROUPS if bpy.data.node_groups.get(name) is None]
    if missing_materials or missing_groups:
        raise RuntimeError(
            "Planetka: embedded material library failed to load "
            f"(materials missing: {missing_materials}, node groups missing: {missing_groups})"
        )

    _sanitize_embedded_assets()

    for material_name in MATERIAL_LIBRARY_MATERIALS:
        material = bpy.data.materials.get(material_name)
        if material:
            material.use_fake_user = True
            _set_library_signature(material)

    for group_name in MATERIAL_LIBRARY_NODE_GROUPS:
        node_group = bpy.data.node_groups.get(group_name)
        if node_group:
            node_group.use_fake_user = True
            _set_library_signature(node_group)


def _ensure_embedded_material_library():
    if not _is_embedded_material_library_ready():
        _load_embedded_material_library()
    _bind_static_images()
    _apply_surface_shader_updates()
    _ensure_surface_fake_atmosphere_nodes()

    earth_material = bpy.data.materials.get(EARTH_MATERIAL_NAME)
    if not earth_material:
        raise RuntimeError("Planetka: embedded materials are missing after load.")
    _normalize_surface_elevation_defaults(earth_material)
    preview_material = _ensure_preview_material(earth_material)
    _normalize_surface_elevation_defaults(preview_material)
    return preview_material, earth_material


def ensure_planetka_assets(scene=None):
    scene = scene or bpy.context.scene
    root = getattr(scene, "collection", None)
    if root is None:
        raise RuntimeError("Planetka: active scene collection is missing.")

    surface_collection = _ensure_collection(root, SURFACE_COLLECTION_NAME)

    preview_material, earth_material = _ensure_embedded_material_library()
    sunlight_object = _ensure_planetka_sunlight(surface_collection)
    props = getattr(scene, "planetka", None) if scene else None
    enabled = bool(getattr(props, "enable_fake_atmosphere", False)) if props else False
    density = float(getattr(props, "fake_atmosphere_density", 0.0)) if props else 0.0
    height_km = float(getattr(props, "fake_atmosphere_height_km", 50.0)) if props else 50.0
    falloff = float(getattr(props, "fake_atmosphere_falloff_exp", 0.05)) if props else 0.05
    color = tuple(getattr(props, "fake_atmosphere_color", _FAKE_ATMOSPHERE_DEFAULT_COLOR)) if props else _FAKE_ATMOSPHERE_DEFAULT_COLOR
    atmosphere_shell_object = apply_fake_atmosphere_shell(
        scene=scene,
        enabled=enabled,
        density=density,
        height_km=height_km,
        falloff=falloff,
        color=color,
    )

    return {
        "collection": surface_collection,
        "surface_collection": surface_collection,
        "preview_object": None,
        "preview_material": preview_material,
        "earth_material": earth_material,
        "sunlight_object": sunlight_object,
        "atmosphere_shell_object": atmosphere_shell_object,
    }
