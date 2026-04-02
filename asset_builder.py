import io
import logging
import math
import os
import tempfile

import bpy

from .embedded_material_library import (
    MATERIAL_LIBRARY_MATERIALS,
    MATERIAL_LIBRARY_NODE_GROUPS,
    MATERIAL_LIBRARY_SHA256,
    get_material_library_bytes,
)
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
PLANETKA_ROOT_OBJECT_NAME = "Planetka Root"
FAKE_ATMOSPHERE_OBJECT_NAME = "Atmosphere - EEVEE supplement"
FAKE_ATMOSPHERE_MATERIAL_NAME = "Planetka Atmosphere Fake Material"
FAKE_ATMOSPHERE_GROUP_NAME = "Planetka Atmosphere Fake Group"
FAKE_ATMOSPHERE_TEXTURE_GROUP_NAME = "Planetka Fake Atmosphere Textures Group"
FAKE_ATMOSPHERE_COLLECTION_NAME = "Atmosphere"
FAKE_ATMOSPHERE_ROLE_KEY = "planetka_role"
FAKE_ATMOSPHERE_ROLE_VALUE = "fake_atmosphere"
FAKE_ATMOSPHERE_SOURCE_OBJECT_NAME = "Planetka Atmosphere Fake"
FAKE_ATMOSPHERE_SCALE_FACTOR = 2.01
_LEGACY_FAKE_ATMOSPHERE_COLLECTION_NAMES = ("Atmpshere",)
_LEGACY_FAKE_ATMOSPHERE_OBJECT_NAMES = (
    "Planetka Atmosphere Fake",
    "Atmosphere - Fake",
    "Fake Atmosphere",
)
VOLUMETRIC_ATMOSPHERE_OBJECT_NAME = "Atmosphere - Volumetric"
VOLUMETRIC_ATMOSPHERE_SOURCE_OBJECT_NAME = "Planetka Atmosphere"
VOLUMETRIC_ATMOSPHERE_MATERIAL_NAME = "Planetka Atmosphere Material"
VOLUMETRIC_ATMOSPHERE_GROUP_NAME = "Planetka Atmosphere Group"
VOLUMETRIC_ATMOSPHERE_ROLE_VALUE = "atmosphere_volumetric"
VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR = 2.0
DEFAULT_ELEVATION_COEFFICIENT = 1.0
ELEVATION_SCALE_MULTIPLIER = 0.012
DEFAULT_SURFACE_SATURATION = 1.2
DEFAULT_WATER_ROUGHNESS = 0.6
_LIBRARY_SIGNATURE_KEY = "planetka_embedded_material_sha256"
_PREVIEW_TEXTURE_GROUP_VERSION_KEY = "planetka_preview_texture_group_v"
_PREVIEW_TEXTURE_GROUP_VERSION = 1
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_LEGACY_LIBRARY_RELATIVE_PATH = ("Resources", "planetka_material_lib_45.blend")
_FAKE_ATMOSPHERE_LIBRARY_RELATIVE_PATH = ("Resources", "planetka_fake_atmosphere.blend")
_VOLUMETRIC_ATMOSPHERE_LIBRARY_RELATIVE_PATH = ("Resources", "planetka_volumetric_atmosphere.blend")
_LEGACY_VOLUMETRIC_ATMOSPHERE_SOURCE_BLEND_PATH = (
    "/Volumes/SSDA/Projects/Planetka Mini/Planetka 32K/Planetka_Mini_32K.blend"
)
_LEGACY_LIBRARY_MATERIALS_TO_PURGE = (
    LEGACY_PREVIEW_MATERIAL_NAME,
)
_LEGACY_LIBRARY_GROUPS_TO_PURGE = (
    "Planetka Ocean Shader Group",
    PREVIEW_TEXTURE_LOADING_GROUP_NAME,
)
_SURFACE_DETAIL_VERSION_KEY = "planetka_surface_detail_v"
_SURFACE_DETAIL_VERSION = 1
_SURFACE_SHADER_UPDATE_VERSION_KEY = "planetka_surface_shader_update_v"
_SURFACE_SHADER_UPDATE_VERSION = 3

_DETAIL_SOCKET_SCALE = "Procedural Detail Scale"
_DETAIL_SOCKET_FOREST = "Forest Detail Strength"
_DETAIL_SOCKET_ROCK = "Rock Detail Strength"
_DETAIL_SOCKET_ROCK_COLOR = "Rock Color Variation"
_DETAIL_SOCKET_MICRO_DISP = "Micro Displacement Strength"

_SURFACE_DEFAULT_INPUT_SPECS = (
    ("Surface Brightness", 5.0, 0.0, 10.0),
    ("Surface Saturation", 1.2, 0.0, 5.0),
    ("Roughness", 0.6, 0.0, 1.0),
    ("IOR", 1.333, 0.0, 3.0),
    ("Saturation", 1.0, 0.0, 2.0),
    ("Water Texture Strength", 0.5, 0.0, 1.0),
    ("Intensity", 1.0, 0.0, 10.0),
    ("Night Terminator Shift", 0.0, -25.0, 25.0),
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
_SHADER_INPUT_DESCRIPTIONS = {
    "Surface Brightness": "Multiplier for land/base-color brightness before final shading.",
    "Surface Saturation": "Multiplier for land/base-color saturation.",
    "Roughness": "Base surface roughness (0 = mirror-like, 1 = fully diffuse).",
    "IOR": "Index of refraction used by water/specular shading.",
    "Saturation": "Water color saturation adjustment.",
    "Water Texture Strength": "Blend strength of water texture detail.",
    "Intensity": "Night-lights emission intensity multiplier.",
    "Night Terminator Shift": (
        "Offsets the day/night transition used by city lights. "
        "Internal shader scales this by 1/100 for practical UI range."
    ),
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
}

_STATIC_IMAGE_SPECS = {
    "ocean_pixel_final_20.exr": {
        "relative_path": ("Resources", "Fallback Images", "ocean_pixel_final_20.exr"),
        "colorspace": "Linear Rec.709",
        "alpha_mode": "PREMUL",
    },
    "black_pixel_20.exr": {
        "relative_path": ("Resources", "Fallback Images", "black_pixel_20.exr"),
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
    ("Image Texture", "ocean_pixel_final_20.exr"),
    ("Image Texture.001", "black_pixel_20.exr"),
    ("Image Texture.002", "blue_pixel_20.exr"),
    ("Image Texture.003", "black_pixel_20.exr"),
)

_SURFACE_GROUP_IMAGE_BINDINGS = (
    ("Image Texture", "ocean_pixel_final_20.exr"),
    ("Image Texture.001", "blue_pixel_20.exr"),
)

_FAKE_ATMOSPHERE_IMAGE_BINDINGS = (
    ("surface", "ocean_pixel_final_20.exr"),
    ("elevation", "black_pixel_20.exr"),
    ("mask", "black_pixel_20.exr"),
)


def _hide_unconnected_group_input_sockets(node_tree):
    if node_tree is None:
        return
    nodes = getattr(node_tree, "nodes", None)
    if nodes is None:
        return

    for node in nodes:
        if str(getattr(node, "type", "")) != "GROUP_INPUT":
            continue
        for socket in getattr(node, "outputs", ()):
            try:
                linked = bool(getattr(socket, "is_linked", False))
                if not linked:
                    linked = bool(getattr(socket, "links", ()))
                socket.hide = not linked
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _hide_unconnected_group_input_sockets_everywhere():
    seen = set()

    for material in getattr(bpy.data, "materials", ()):
        if getattr(material, "node_tree", None) is None:
            continue
        node_tree = getattr(material, "node_tree", None)
        if node_tree is None:
            continue
        ptr = int(getattr(node_tree, "as_pointer", lambda: id(node_tree))())
        if ptr in seen:
            continue
        seen.add(ptr)
        _hide_unconnected_group_input_sockets(node_tree)

    for node_group in getattr(bpy.data, "node_groups", ()):
        if str(getattr(node_group, "bl_idname", "")) != "ShaderNodeTree":
            continue
        ptr = int(getattr(node_group, "as_pointer", lambda: id(node_group))())
        if ptr in seen:
            continue
        seen.add(ptr)
        _hide_unconnected_group_input_sockets(node_group)


def _is_fallback_static_image(image_name):
    spec = _STATIC_IMAGE_SPECS.get(str(image_name))
    if not isinstance(spec, dict):
        return False
    rel = spec.get("relative_path")
    if not isinstance(rel, (tuple, list)):
        return False
    rel_text = "/".join(str(part).strip().lower() for part in rel if part is not None)
    return "fallback images" in rel_text


def _set_tex_image_node_interpolation(node, use_fallback):
    if not node or str(getattr(node, "bl_idname", "")) != "ShaderNodeTexImage":
        return
    try:
        node.interpolation = "Closest" if bool(use_fallback) else "Linear"
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _set_material_displacement_and_bump(material):
    if material is None:
        return False

    changed = False

    # Blender 5.x path.
    if hasattr(material, "displacement_method"):
        preferred_material = ("BOTH", "DISPLACEMENT_BUMP", "DISPLACEMENT_AND_BUMP")
        available = set()
        try:
            prop_def = material.bl_rna.properties.get("displacement_method")
            if prop_def and hasattr(prop_def, "enum_items"):
                available = {item.identifier for item in prop_def.enum_items}
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            available = set()

        for identifier in preferred_material:
            if available and identifier not in available:
                continue
            try:
                material.displacement_method = identifier
                changed = True
                break
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                continue

    # Legacy path.
    cycles_settings = getattr(material, "cycles", None)
    if cycles_settings is None or not hasattr(cycles_settings, "displacement_method"):
        return changed

    preferred_cycles = ("BOTH", "DISPLACEMENT_BUMP", "DISPLACEMENT_AND_BUMP")
    available = set()
    try:
        prop_def = cycles_settings.bl_rna.properties.get("displacement_method")
        if prop_def and hasattr(prop_def, "enum_items"):
            available = {item.identifier for item in prop_def.enum_items}
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        available = set()

    for identifier in preferred_cycles:
        if available and identifier not in available:
            continue
        try:
            cycles_settings.displacement_method = identifier
            changed = True
            break
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return changed


def _normalize_surface_elevation_defaults(material):
    if material is None or getattr(material, "node_tree", None) is None:
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
        if coeff_socket is not None:
            try:
                current = float(coeff_socket.default_value)
            except (AttributeError, TypeError, ValueError):
                current = None
            # Keep custom user edits untouched; normalize known defaults to 1.0.
            if current is not None and (
                abs(current - 1.0) <= 1e-6
                or abs(current - 0.905) <= 1e-6
                or abs(current - 0.83335673) <= 1e-6
                or abs(current - 0.41667837) <= 1e-6
            ):
                try:
                    coeff_socket.default_value = float(DEFAULT_ELEVATION_COEFFICIENT)
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, TypeError, ValueError):
                    pass

        roughness_socket = None
        try:
            roughness_socket = node.inputs.get("Roughness")
        except (AttributeError, TypeError, ValueError):
            roughness_socket = None
        if roughness_socket is not None:
            try:
                roughness_value = float(roughness_socket.default_value)
            except (AttributeError, TypeError, ValueError):
                roughness_value = None
            # Preserve custom user edits; normalize only legacy defaults to 0.6.
            if roughness_value is not None and (
                abs(roughness_value - 0.6) <= 1e-6
                or abs(roughness_value - 0.5) <= 1e-6
                or abs(roughness_value - 0.4) <= 1e-6
                or abs(roughness_value - 0.25) <= 1e-6
            ):
                try:
                    roughness_socket.default_value = float(DEFAULT_WATER_ROUGHNESS)
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, TypeError, ValueError):
                    pass

        surface_sat_socket = None
        try:
            surface_sat_socket = node.inputs.get("Surface Saturation")
        except (AttributeError, TypeError, ValueError):
            surface_sat_socket = None
        if surface_sat_socket is not None:
            try:
                surface_sat_value = float(surface_sat_socket.default_value)
            except (AttributeError, TypeError, ValueError):
                surface_sat_value = None
            # Preserve custom user edits; normalize old defaults to 1.2.
            if surface_sat_value is not None and (
                abs(surface_sat_value - 1.2) <= 1e-6
                or abs(surface_sat_value - 1.25) <= 1e-6
                or abs(surface_sat_value - 1.1) <= 1e-6
            ):
                try:
                    surface_sat_socket.default_value = float(DEFAULT_SURFACE_SATURATION)
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, TypeError, ValueError):
                    pass


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
    except (RuntimeError, TypeError, ValueError, AttributeError):
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


def _remove_interface_socket(node_group, socket_name, *, in_out):
    if node_group is None:
        return False
    interface = getattr(node_group, "interface", None)
    items = getattr(interface, "items_tree", None) if interface else None
    if items is None:
        return False
    target = None
    for item in items:
        if getattr(item, "item_type", None) != "SOCKET":
            continue
        if str(getattr(item, "in_out", "")) != str(in_out):
            continue
        if str(getattr(item, "name", "")) == str(socket_name):
            target = item
            break
    if target is None:
        return False
    try:
        interface.remove(target)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        return False


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
    night_terminator_shift_out = _find_group_input_output_socket(surface_group, "Night Terminator Shift")

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

    for node in nodes:
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        node_tree = getattr(node, "node_tree", None)
        node_tree_name = str(getattr(node_tree, "name", ""))
        if not (
            node_tree_name == NIGHTDAY_GROUP_NAME
            or node_tree_name.startswith(f"{NIGHTDAY_GROUP_NAME}.")
        ):
            continue
        _replace_input_link(
            links,
            _socket_input_by_name_or_index(node.inputs, "Terminator Shift"),
            night_terminator_shift_out,
        )


def _iter_nightday_groups():
    for group in getattr(bpy.data, "node_groups", ()):
        group_name = str(getattr(group, "name", ""))
        if group_name == NIGHTDAY_GROUP_NAME or group_name.startswith(f"{NIGHTDAY_GROUP_NAME}."):
            yield group


def _nightday_variant_suffix(name):
    group_name = str(name or "")
    if group_name == NIGHTDAY_GROUP_NAME:
        return -1
    prefix = f"{NIGHTDAY_GROUP_NAME}."
    if not group_name.startswith(prefix):
        return -2
    suffix = group_name[len(prefix):]
    try:
        return int(suffix)
    except (TypeError, ValueError):
        return -2


def _iter_node_trees_for_group_relink():
    for material in getattr(bpy.data, "materials", ()):
        if getattr(material, "node_tree", None) is None:
            continue
        node_tree = getattr(material, "node_tree", None)
        if node_tree is not None:
            yield node_tree
    for world in getattr(bpy.data, "worlds", ()):
        if getattr(world, "node_tree", None) is None:
            continue
        node_tree = getattr(world, "node_tree", None)
        if node_tree is not None:
            yield node_tree
    for node_group in getattr(bpy.data, "node_groups", ()):
        if node_group is not None:
            yield node_group


def _canonicalize_nightday_group_variants():
    variants = list(_iter_nightday_groups())
    if not variants:
        return None

    preferred = None
    surface_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if surface_group is not None and getattr(surface_group, "nodes", None):
        night_node = surface_group.nodes.get("Night_day")
        night_tree = getattr(night_node, "node_tree", None) if night_node is not None else None
        if night_tree in variants:
            preferred = night_tree
    if preferred is None:
        preferred = max(variants, key=lambda grp: _nightday_variant_suffix(getattr(grp, "name", "")))

    # Re-link every group node using any NightDay variant to the preferred group.
    for node_tree in _iter_node_trees_for_group_relink():
        nodes = getattr(node_tree, "nodes", None)
        if nodes is None:
            continue
        for node in nodes:
            if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                continue
            node_group = getattr(node, "node_tree", None)
            node_group_name = str(getattr(node_group, "name", ""))
            if not (
                node_group_name == NIGHTDAY_GROUP_NAME
                or node_group_name.startswith(f"{NIGHTDAY_GROUP_NAME}.")
            ):
                continue
            if node_group is preferred:
                continue
            try:
                node.node_tree = preferred
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    # Remove old variants now that links are normalized.
    for group in list(_iter_nightday_groups()):
        if group is preferred:
            continue
        try:
            bpy.data.node_groups.remove(group, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    # Force canonical name without .001/.002.
    existing = bpy.data.node_groups.get(NIGHTDAY_GROUP_NAME)
    if existing is not None and existing is not preferred:
        try:
            bpy.data.node_groups.remove(existing, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    try:
        preferred.name = NIGHTDAY_GROUP_NAME
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    return bpy.data.node_groups.get(NIGHTDAY_GROUP_NAME) or preferred


def _wire_nightday_terminator_shift():
    for nightday_group in _iter_nightday_groups():
        _ensure_interface_float_socket(
            nightday_group,
            "Terminator Shift",
            default=0.0,
            min_value=-25.0,
            max_value=25.0,
            description=(
                "Shift of day/night transition used for city-lights masking "
                "(positive = toward day, negative = toward night)."
            ),
        )
        _remove_interface_socket(nightday_group, "Result", in_out="OUTPUT")

        nodes = getattr(nightday_group, "nodes", None)
        links = getattr(nightday_group, "links", None)
        if nodes is None or links is None:
            continue

        color_ramp = nodes.get("Color Ramp")
        if color_ramp is None:
            continue

        group_input = None
        for node in nodes:
            if str(getattr(node, "bl_idname", "")) == "NodeGroupInput":
                group_input = node
                break
        if group_input is None:
            try:
                group_input = nodes.new("NodeGroupInput")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError):
                continue

        shift_socket = _socket_output_by_name_or_index(getattr(group_input, "outputs", None), "Terminator Shift")
        if shift_socket is None:
            continue

        # Find current source driving Color Ramp factor (typically Normal.001 Dot).
        source_socket = None
        fac_input = _socket_input_by_name_or_index(getattr(color_ramp, "inputs", None), "Fac", 0)
        if fac_input is None:
            continue
        if fac_input.links:
            source_socket = fac_input.links[0].from_socket
        if source_socket is None:
            normal_node = nodes.get("Normal.001")
            if normal_node is not None:
                source_socket = _socket_output_by_name_or_index(getattr(normal_node, "outputs", None), "Dot")
        if source_socket is None:
            continue

        shift_add = nodes.get("PKA Terminator Shift Add")
        if shift_add is None or str(getattr(shift_add, "bl_idname", "")) != "ShaderNodeMath":
            if shift_add is not None:
                try:
                    nodes.remove(shift_add)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    pass
                except (RuntimeError, TypeError, ValueError):
                    pass
            try:
                shift_add = nodes.new("ShaderNodeMath")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError):
                continue
            shift_add.name = "PKA Terminator Shift Add"
        try:
            shift_add.operation = "ADD"
            shift_add.use_clamp = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

        shift_scale = nodes.get("PKA Terminator Shift Scale")
        if shift_scale is None or str(getattr(shift_scale, "bl_idname", "")) != "ShaderNodeMath":
            if shift_scale is not None:
                try:
                    nodes.remove(shift_scale)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    pass
                except (RuntimeError, TypeError, ValueError):
                    pass
            try:
                shift_scale = nodes.new("ShaderNodeMath")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError):
                continue
            shift_scale.name = "PKA Terminator Shift Scale"
        try:
            shift_scale.operation = "DIVIDE"
            shift_scale.use_clamp = False
            shift_scale.inputs[1].default_value = 100.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

        try:
            shift_add.location = (float(color_ramp.location[0]) - 240.0, float(color_ramp.location[1]))
            shift_scale.location = (float(shift_add.location[0]) - 220.0, float(shift_add.location[1]) + 120.0)
            group_input.location = (float(shift_scale.location[0]) - 220.0, float(shift_scale.location[1]) + 40.0)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass

        # Remove legacy unused Map Range node if present.
        legacy_map_range = nodes.get("Map Range")
        if legacy_map_range is not None and str(getattr(legacy_map_range, "bl_idname", "")) == "ShaderNodeMapRange":
            try:
                nodes.remove(legacy_map_range)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

        for link in list(getattr(fac_input, "links", ())):
            try:
                links.remove(link)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
            except (RuntimeError, TypeError, ValueError, AttributeError):
                continue

        # Slightly smoother day/night transition edge.
        try:
            ramp = getattr(color_ramp, "color_ramp", None)
            elements = getattr(ramp, "elements", None) if ramp else None
            if elements and len(elements) >= 2:
                elements[1].position = 0.017104
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

        try:
            links.new(source_socket, shift_add.inputs[0])
            links.new(shift_socket, shift_scale.inputs[0])
            links.new(shift_scale.outputs[0], shift_add.inputs[1])
            links.new(shift_add.outputs[0], fac_input)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


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

    _wire_nightday_terminator_shift()
    _remove_surface_detail_nodes(surface_group)
    _apply_surface_group_input_defaults(surface_group)
    _wire_surface_extra_feature_inputs(surface_group)
    _canonicalize_nightday_group_variants()
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
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError(
                "Planetka: embedded material library uses zstd compression but zstandard module is unavailable."
            ) from exc
        try:
            with zstd.ZstdDecompressor().stream_reader(io.BytesIO(payload)) as reader:
                payload = reader.read()
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            raise RuntimeError("Planetka: failed to decompress embedded material library payload.") from exc

    if not payload.startswith(b"BLENDER"):
        raise RuntimeError("Planetka: embedded material library payload is invalid.")
    return payload


def _legacy_material_library_path():
    return os.path.join(os.path.dirname(__file__), *_LEGACY_LIBRARY_RELATIVE_PATH)


def _fake_atmosphere_library_path():
    return os.path.join(os.path.dirname(__file__), *_FAKE_ATMOSPHERE_LIBRARY_RELATIVE_PATH)


def _volumetric_atmosphere_library_path():
    return os.path.join(os.path.dirname(__file__), *_VOLUMETRIC_ATMOSPHERE_LIBRARY_RELATIVE_PATH)


def _volumetric_atmosphere_library_candidates():
    candidates = [_volumetric_atmosphere_library_path(), _LEGACY_VOLUMETRIC_ATMOSPHERE_SOURCE_BLEND_PATH]
    ordered = []
    seen = set()
    for path in candidates:
        normalized = os.path.abspath(str(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(normalized):
            ordered.append(normalized)
    return ordered


def _append_material_library_from_blend(blend_path):
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        available_materials = set(data_from.materials)
        available_groups = set(data_from.node_groups)
        data_to.materials = [name for name in MATERIAL_LIBRARY_MATERIALS if name in available_materials]
        data_to.node_groups = [name for name in MATERIAL_LIBRARY_NODE_GROUPS if name in available_groups]


def _append_fake_atmosphere_assets_from_blend(blend_path):
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        available_objects = set(data_from.objects)
        available_materials = set(data_from.materials)
        available_groups = set(data_from.node_groups)

        object_names = []
        if FAKE_ATMOSPHERE_SOURCE_OBJECT_NAME in available_objects:
            object_names.append(FAKE_ATMOSPHERE_SOURCE_OBJECT_NAME)
        else:
            object_names.extend(
                name
                for name in data_from.objects
                if "atmosphere" in str(name).lower() and "fake" in str(name).lower()
            )
        if not object_names:
            raise RuntimeError(
                f"Planetka: fake atmosphere object is missing in reference blend '{blend_path}'."
            )
        data_to.objects = [object_names[0]]

        data_to.materials = [FAKE_ATMOSPHERE_MATERIAL_NAME] if FAKE_ATMOSPHERE_MATERIAL_NAME in available_materials else []
        data_to.node_groups = [
            name
            for name in (FAKE_ATMOSPHERE_GROUP_NAME, FAKE_ATMOSPHERE_TEXTURE_GROUP_NAME)
            if name in available_groups
        ]


def _append_volumetric_atmosphere_assets_from_blend(blend_path):
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        available_objects = set(data_from.objects)
        object_names = []
        if VOLUMETRIC_ATMOSPHERE_SOURCE_OBJECT_NAME in available_objects:
            object_names.append(VOLUMETRIC_ATMOSPHERE_SOURCE_OBJECT_NAME)
        else:
            for name in data_from.objects:
                lowered = str(name).lower()
                if "atmosphere" not in lowered:
                    continue
                if any(token in lowered for token in ("fake", "suplement", "supplement", "eevee")):
                    continue
                object_names.append(name)
        if not object_names:
            raise RuntimeError(
                f"Planetka: volumetric atmosphere object is missing in reference blend '{blend_path}'."
            )
        data_to.objects = [object_names[0]]


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


def ensure_planetka_root(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None
    root_collection = getattr(scene, "collection", None)
    if root_collection is None:
        return None
    surface_collection = _ensure_collection(root_collection, SURFACE_COLLECTION_NAME)
    if surface_collection is None:
        return None

    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    created_new = False
    if root is None or str(getattr(root, "type", "")) != "EMPTY":
        if root is not None:
            try:
                bpy.data.objects.remove(root, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        root = bpy.data.objects.new(PLANETKA_ROOT_OBJECT_NAME, None)
        created_new = True

    for collection in tuple(getattr(root, "users_collection", ())):
        if collection == surface_collection:
            continue
        try:
            collection.objects.unlink(root)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        if root.name not in surface_collection.objects:
            surface_collection.objects.link(root)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        root.empty_display_type = 'PLAIN_AXES'
        root.empty_display_size = 0.25
        if created_new:
            root.location = (0.0, 0.0, 0.0)
            root.rotation_euler = (0.0, 0.0, 0.0)
            root.scale = (1.0, 1.0, 1.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    return root


def ensure_earth_surface_parent(scene=None, earth_surface=None):
    scene = scene or getattr(bpy.context, "scene", None)
    earth_surface = _resolve_surface_object_for_fake_atmosphere(earth_surface)
    if scene is None or earth_surface is None:
        return earth_surface
    root = ensure_planetka_root(scene)
    if root is None:
        return earth_surface

    try:
        if getattr(earth_surface, "parent", None) is not root:
            earth_surface.parent = root
            earth_surface.matrix_parent_inverse = root.matrix_world.inverted()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return earth_surface


def _set_object_collections(obj, collections):
    if obj is None:
        return

    desired = [col for col in collections if col]
    desired_ids = {id(col) for col in desired}

    for col in list(getattr(obj, "users_collection", ())):
        if id(col) in desired_ids:
            continue
        try:
            col.objects.unlink(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    for col in desired:
        try:
            if obj.name not in col.objects:
                col.objects.link(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _find_fake_atmosphere_object():
    candidates = _iter_fake_atmosphere_objects()
    if not candidates:
        return None

    for obj in candidates:
        if str(getattr(obj, "name", "")) == FAKE_ATMOSPHERE_OBJECT_NAME:
            return obj

    for obj in candidates:
        try:
            if obj.get(FAKE_ATMOSPHERE_ROLE_KEY) == FAKE_ATMOSPHERE_ROLE_VALUE:
                return obj
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue

    for obj in candidates:
        if _object_uses_fake_atmosphere_material(obj):
            return obj

    return candidates[0]


def _find_volumetric_atmosphere_object():
    by_name = bpy.data.objects.get(VOLUMETRIC_ATMOSPHERE_OBJECT_NAME)
    if by_name and str(getattr(by_name, "type", "")) == "MESH":
        return by_name

    for obj in getattr(bpy.data, "objects", ()):
        if str(getattr(obj, "type", "")) != "MESH":
            continue
        try:
            if obj.get(FAKE_ATMOSPHERE_ROLE_KEY) == VOLUMETRIC_ATMOSPHERE_ROLE_VALUE:
                return obj
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue

    for obj in getattr(bpy.data, "objects", ()):
        if str(getattr(obj, "type", "")) != "MESH":
            continue
        name = str(getattr(obj, "name", ""))
        lowered = name.lower()
        if name == FAKE_ATMOSPHERE_OBJECT_NAME or name.startswith(f"{FAKE_ATMOSPHERE_OBJECT_NAME}."):
            continue
        if "atmosphere" not in lowered:
            continue
        if any(token in lowered for token in ("fake", "suplement", "supplement", "eevee")):
            continue
        return obj
    return None


def _object_uses_fake_atmosphere_material(obj):
    materials = getattr(getattr(obj, "data", None), "materials", None)
    if not materials:
        return False
    for mat in materials:
        if mat and str(getattr(mat, "name", "")) == FAKE_ATMOSPHERE_MATERIAL_NAME:
            return True
    return False


def _is_fake_atmosphere_candidate(obj):
    if obj is None or str(getattr(obj, "type", "")) != "MESH":
        return False

    name = str(getattr(obj, "name", ""))
    lowered = name.lower()
    legacy_names = {item.lower() for item in _LEGACY_FAKE_ATMOSPHERE_OBJECT_NAMES}
    if (
        name == FAKE_ATMOSPHERE_OBJECT_NAME
        or name.startswith(f"{FAKE_ATMOSPHERE_OBJECT_NAME}.")
        or lowered in legacy_names
        or ("atmosphere" in lowered and "fake" in lowered)
    ):
        return True

    try:
        if obj.get(FAKE_ATMOSPHERE_ROLE_KEY) == FAKE_ATMOSPHERE_ROLE_VALUE:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass

    return _object_uses_fake_atmosphere_material(obj)


def _iter_fake_atmosphere_objects():
    results = []
    seen = set()
    for obj in getattr(bpy.data, "objects", ()):
        if not _is_fake_atmosphere_candidate(obj):
            continue
        try:
            key = int(obj.as_pointer())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            key = id(obj)
        if key in seen:
            continue
        seen.add(key)
        results.append(obj)
    return results


def _resolve_fake_atmosphere_object(ensure_exists=False):
    fake_obj = _find_fake_atmosphere_object()
    if fake_obj is not None:
        return fake_obj
    if not ensure_exists:
        return None

    blend_path = _fake_atmosphere_library_path()
    if not os.path.isfile(blend_path):
        raise RuntimeError(f"Planetka: fake atmosphere reference blend is missing: {blend_path}")

    _append_fake_atmosphere_assets_from_blend(blend_path)
    fake_obj = _find_fake_atmosphere_object()
    if fake_obj is None:
        for obj in getattr(bpy.data, "objects", ()):
            if str(getattr(obj, "type", "")) != "MESH":
                continue
            materials = getattr(getattr(obj, "data", None), "materials", None)
            if any(mat and mat.name == FAKE_ATMOSPHERE_MATERIAL_NAME for mat in (materials or ())):
                fake_obj = obj
                break
    if fake_obj is None:
        raise RuntimeError("Planetka: failed importing fake atmosphere object from reference blend.")

    try:
        fake_obj.name = FAKE_ATMOSPHERE_OBJECT_NAME
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        fake_obj[FAKE_ATMOSPHERE_ROLE_KEY] = FAKE_ATMOSPHERE_ROLE_VALUE
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return fake_obj


def _resolve_volumetric_atmosphere_object(ensure_exists=False):
    obj = _find_volumetric_atmosphere_object()
    if obj is not None:
        return obj
    if not ensure_exists:
        return None

    candidates = _volumetric_atmosphere_library_candidates()
    if not candidates:
        raise RuntimeError(
            "Planetka: volumetric atmosphere reference blend is missing. Expected either "
            "'Resources/planetka_volumetric_atmosphere.blend' or the Planetka Mini source blend."
        )

    errors = []
    for blend_path in candidates:
        try:
            _append_volumetric_atmosphere_assets_from_blend(blend_path)
            obj = _find_volumetric_atmosphere_object()
            if obj is not None:
                break
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError) as exc:
            errors.append(f"{blend_path}: {exc}")
            continue

    if obj is None:
        error_text = "; ".join(errors) if errors else "unknown append error"
        raise RuntimeError(f"Planetka: failed importing volumetric atmosphere object ({error_text}).")
    return obj


def _bind_fake_atmosphere_images():
    texture_group = bpy.data.node_groups.get(FAKE_ATMOSPHERE_TEXTURE_GROUP_NAME)
    if texture_group is None:
        return

    for node in texture_group.nodes:
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeTexImage":
            continue
        node_name = str(getattr(node, "name", "")).lower()
        image_name = None
        for label, candidate_image in _FAKE_ATMOSPHERE_IMAGE_BINDINGS:
            if label in node_name:
                image_name = candidate_image
                break
        if image_name is None:
            continue
        node.image = _load_static_image(image_name)
        _set_tex_image_node_interpolation(
            node,
            use_fallback=_is_fallback_static_image(image_name),
        )


def _bind_fake_atmosphere_sunlight_object():
    sunlight_obj = bpy.data.objects.get(SUNLIGHT_OBJECT_NAME)
    if sunlight_obj is None:
        return

    target_groups = (
        bpy.data.node_groups.get(FAKE_ATMOSPHERE_GROUP_NAME),
        bpy.data.node_groups.get(FAKE_ATMOSPHERE_TEXTURE_GROUP_NAME),
    )
    for node_group in target_groups:
        if node_group is None:
            continue

        target_nodes = []
        named_node = node_group.nodes.get("Texture Coordinate")
        if named_node and getattr(named_node, "bl_idname", "") == "ShaderNodeTexCoord":
            target_nodes.append(named_node)
        else:
            target_nodes.extend(
                node for node in node_group.nodes
                if getattr(node, "bl_idname", "") == "ShaderNodeTexCoord"
            )

        for node in target_nodes:
            try:
                node.object = sunlight_obj
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _resolve_surface_object_for_fake_atmosphere(earth_surface):
    if (
        earth_surface
        and str(getattr(earth_surface, "type", "")) == "MESH"
        and len(getattr(getattr(earth_surface, "data", None), "vertices", ())) > 0
    ):
        return earth_surface
    by_name = bpy.data.objects.get("Planetka Earth Surface")
    if (
        by_name
        and str(getattr(by_name, "type", "")) == "MESH"
        and len(getattr(getattr(by_name, "data", None), "vertices", ())) > 0
    ):
        return by_name
    return None


def _ensure_fake_atmosphere_collection(scene):
    scene = scene or getattr(bpy.context, "scene", None)
    root = getattr(scene, "collection", None) if scene else None
    if root is None:
        return None

    target = bpy.data.collections.get(FAKE_ATMOSPHERE_COLLECTION_NAME)
    if target is None:
        for legacy_name in _LEGACY_FAKE_ATMOSPHERE_COLLECTION_NAMES:
            legacy = bpy.data.collections.get(legacy_name)
            if legacy is None:
                continue
            try:
                legacy.name = FAKE_ATMOSPHERE_COLLECTION_NAME
                target = legacy
                break
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
                target = legacy
                break
    if target is None:
        target = _ensure_collection(root, FAKE_ATMOSPHERE_COLLECTION_NAME)
    else:
        try:
            if target.name not in root.children:
                root.children.link(target)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return target


def _configure_fake_atmosphere_object(fake_obj):
    if fake_obj is None:
        return
    try:
        if str(getattr(fake_obj, "name", "")) != FAKE_ATMOSPHERE_OBJECT_NAME:
            fake_obj.name = FAKE_ATMOSPHERE_OBJECT_NAME
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    # Keep supplement shell smooth to avoid faceted artifact bands.
    try:
        mesh = getattr(fake_obj, "data", None)
        if mesh is not None and hasattr(mesh, "polygons"):
            for poly in mesh.polygons:
                if not bool(getattr(poly, "use_smooth", False)):
                    poly.use_smooth = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    # Prevent noisy Eevee shadow artifacts from the transparent shell.
    try:
        if hasattr(fake_obj, "visible_shadow") and bool(getattr(fake_obj, "visible_shadow", True)):
            fake_obj.visible_shadow = False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _configure_volumetric_atmosphere_object(obj):
    if obj is None:
        return
    try:
        if str(getattr(obj, "name", "")) != VOLUMETRIC_ATMOSPHERE_OBJECT_NAME:
            obj.name = VOLUMETRIC_ATMOSPHERE_OBJECT_NAME
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        obj[FAKE_ATMOSPHERE_ROLE_KEY] = VOLUMETRIC_ATMOSPHERE_ROLE_VALUE
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def ensure_static_fake_atmosphere(scene=None, earth_surface=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None

    earth_surface = ensure_earth_surface_parent(scene=scene, earth_surface=earth_surface)
    root = ensure_planetka_root(scene)

    fake_obj = _find_fake_atmosphere_object() or _resolve_fake_atmosphere_object(ensure_exists=True)
    if fake_obj is None:
        return None

    fake_material = bpy.data.materials.get(FAKE_ATMOSPHERE_MATERIAL_NAME)
    if (
        fake_material is not None
        and str(getattr(fake_obj, "type", "")) == "MESH"
        and getattr(getattr(fake_obj, "data", None), "materials", None) is not None
    ):
        try:
            fake_obj.data.materials.clear()
            fake_obj.data.materials.append(fake_material)
            for poly in fake_obj.data.polygons:
                poly.material_index = 0
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    _bind_fake_atmosphere_images()
    _bind_fake_atmosphere_sunlight_object()
    _configure_fake_atmosphere_object(fake_obj)

    fake_collection = _ensure_fake_atmosphere_collection(scene)
    target_collections = [fake_collection] if fake_collection is not None else []
    _set_object_collections(fake_obj, target_collections)

    try:
        if root is not None:
            fake_obj.parent = root
            fake_obj.matrix_parent_inverse = root.matrix_world.inverted()
            fake_obj.location = (0.0, 0.0, 0.0)
            fake_obj.rotation_euler = (0.0, 0.0, 0.0)
            fake_obj.scale = (
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
            )
        elif earth_surface is not None:
            fake_obj.parent = earth_surface
            fake_obj.matrix_parent_inverse = earth_surface.matrix_world.inverted()
            fake_obj.location = (0.0, 0.0, 0.0)
            fake_obj.rotation_euler = (0.0, 0.0, 0.0)
            fake_obj.scale = (
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
            )
        else:
            fake_obj.parent = None
            fake_obj.scale = (
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
                float(FAKE_ATMOSPHERE_SCALE_FACTOR),
            )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        fake_obj[FAKE_ATMOSPHERE_ROLE_KEY] = FAKE_ATMOSPHERE_ROLE_VALUE
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    return fake_obj


def ensure_volumetric_atmosphere(scene=None, earth_surface=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None

    earth_surface = ensure_earth_surface_parent(scene=scene, earth_surface=earth_surface)
    root = ensure_planetka_root(scene)
    atmosphere_obj = _find_volumetric_atmosphere_object() or _resolve_volumetric_atmosphere_object(ensure_exists=True)
    if atmosphere_obj is None:
        return None

    _configure_volumetric_atmosphere_object(atmosphere_obj)

    atmosphere_collection = _ensure_fake_atmosphere_collection(scene)
    target_collections = [atmosphere_collection] if atmosphere_collection is not None else []
    _set_object_collections(atmosphere_obj, target_collections)

    try:
        if root is not None:
            atmosphere_obj.parent = root
            atmosphere_obj.matrix_parent_inverse = root.matrix_world.inverted()
            atmosphere_obj.location = (0.0, 0.0, 0.0)
            atmosphere_obj.rotation_euler = (0.0, 0.0, 0.0)
            atmosphere_obj.scale = (
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
            )
        elif earth_surface is not None:
            atmosphere_obj.parent = earth_surface
            atmosphere_obj.matrix_parent_inverse = earth_surface.matrix_world.inverted()
            atmosphere_obj.location = (0.0, 0.0, 0.0)
            atmosphere_obj.rotation_euler = (0.0, 0.0, 0.0)
            atmosphere_obj.scale = (
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
            )
        else:
            atmosphere_obj.scale = (
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
                float(VOLUMETRIC_ATMOSPHERE_SCALE_FACTOR),
            )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    return atmosphere_obj


def set_atmosphere_collection_enabled(scene=None, enabled=True):
    scene = scene or getattr(bpy.context, "scene", None)
    collection = _ensure_fake_atmosphere_collection(scene) if scene is not None else bpy.data.collections.get(
        FAKE_ATMOSPHERE_COLLECTION_NAME
    )
    if collection is None:
        return False
    hidden = not bool(enabled)
    try:
        if bool(getattr(collection, "hide_viewport", False)) != hidden:
            collection.hide_viewport = hidden
        if bool(getattr(collection, "hide_render", False)) != hidden:
            collection.hide_render = hidden
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    return True


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

    for nightday_group in _iter_nightday_groups():
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


def _remove_mesh_if_exists(name):
    mesh = bpy.data.meshes.get(name)
    if mesh is None:
        return
    try:
        bpy.data.meshes.remove(mesh, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _remove_object_if_exists(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        return
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
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
        if not material or not material.node_tree:
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
    surface_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if not surface_group:
        raise RuntimeError(f"Planetka: node group '{SURFACE_GRADING_GROUP_NAME}' is missing.")

    for node_name, image_name in _SURFACE_GROUP_IMAGE_BINDINGS:
        node = surface_group.nodes.get(node_name)
        if not node or node.bl_idname != "ShaderNodeTexImage":
            continue
        node.image = _load_static_image(image_name)
        _set_tex_image_node_interpolation(
            node,
            use_fallback=_is_fallback_static_image(image_name),
        )


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
    node_s2.image = _load_static_image("ocean_pixel_final_20.exr")

    node_wt = group.nodes.new("ShaderNodeTexImage")
    node_wt.name = "Preview WT"
    node_wt.label = "Preview WT"
    node_wt.location = (-640.0, -20.0)
    node_wt.image = _load_static_image("blue_pixel_20.exr")

    node_po = group.nodes.new("ShaderNodeTexImage")
    node_po.name = "Preview PO"
    node_po.label = "Preview PO"
    node_po.location = (-640.0, -300.0)
    node_po.image = _load_static_image("black_pixel_20.exr")

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
            ("Preview S2", "ocean_pixel_final_20.exr"),
            ("Preview WT", "blue_pixel_20.exr"),
            ("Preview PO", "black_pixel_20.exr"),
        ):
            node = group.nodes.get(node_name)
            if node and node.bl_idname == "ShaderNodeTexImage":
                node.image = _load_static_image(image_name)
        return group
    return _build_preview_texture_loading_group()


def _ensure_preview_material(earth_material):
    if not earth_material or not earth_material.node_tree:
        raise RuntimeError("Planetka: earth material node tree is missing.")

    preview_material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)
    needs_rebuild = not (
        preview_material
        and preview_material.node_tree is not None
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
    for legacy_material in _LEGACY_LIBRARY_MATERIALS_TO_PURGE:
        if bpy.data.materials.get(legacy_material) is not None:
            return False
    for legacy_group in _LEGACY_LIBRARY_GROUPS_TO_PURGE:
        if bpy.data.node_groups.get(legacy_group) is not None:
            return False
    for node_group in getattr(bpy.data, "node_groups", ()):
        group_name = str(getattr(node_group, "name", ""))
        if group_name.startswith(f"{NIGHTDAY_GROUP_NAME}."):
            return False
    return True


def _load_embedded_material_library():
    for material_name in set(MATERIAL_LIBRARY_MATERIALS).union(_LEGACY_LIBRARY_MATERIALS_TO_PURGE):
        _remove_material_if_exists(material_name)
    for group_name in set(MATERIAL_LIBRARY_NODE_GROUPS).union(_LEGACY_LIBRARY_GROUPS_TO_PURGE):
        _remove_node_group_if_exists(group_name)
    for node_group in list(getattr(bpy.data, "node_groups", ())):
        group_name = str(getattr(node_group, "name", ""))
        if group_name.startswith(f"{NIGHTDAY_GROUP_NAME}."):
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

    earth_material = bpy.data.materials.get(EARTH_MATERIAL_NAME)
    if not earth_material:
        raise RuntimeError("Planetka: embedded shader materials are missing after load.")
    _normalize_surface_elevation_defaults(earth_material)
    _set_material_displacement_and_bump(earth_material)
    preview_material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)
    if preview_material is None:
        preview_material = bpy.data.materials.get(LEGACY_PREVIEW_MATERIAL_NAME)
        if preview_material is not None:
            preview_material.name = PREVIEW_MATERIAL_NAME
    if preview_material is None:
        raise RuntimeError("Planetka: preview material is missing after loading reference shaders.")
    _normalize_surface_elevation_defaults(preview_material)
    _set_material_displacement_and_bump(preview_material)
    _hide_unconnected_group_input_sockets_everywhere()
    return preview_material, earth_material


def ensure_planetka_assets(scene=None):
    scene = scene or bpy.context.scene
    root = getattr(scene, "collection", None)
    if root is None:
        raise RuntimeError("Planetka: active scene collection is missing.")

    surface_collection = _ensure_collection(root, SURFACE_COLLECTION_NAME)

    preview_material, earth_material = _ensure_embedded_material_library()
    sunlight_object = _ensure_planetka_sunlight(surface_collection)

    return {
        "collection": surface_collection,
        "surface_collection": surface_collection,
        "preview_object": None,
        "preview_material": preview_material,
        "earth_material": earth_material,
        "sunlight_object": sunlight_object,
    }
