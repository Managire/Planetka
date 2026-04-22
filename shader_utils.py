import bpy
import os
import gc
import importlib
import logging
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

from .extension_prefs import get_prefs
from .fallback_utils import ecosystem_safe_fallback

logger = logging.getLogger(__name__)
_RECOVERABLE_LOG_COUNTS = {}


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

POWER_Z = {1, 2, 4, 8, 16, 32, 64}
POLE_CAP_Z_LEVELS = frozenset({1, 2, 4, 8})
PAD_TILE_PREFIX = "__PKA_PAD_TILE"
TEXTURE_TYPES = ("S2", "EL", "WT", "PO")
TEXTURE_EXTENSIONS = {
    "S2": (".exr",),
    "EL": (".exr",),
    "WT": (".exr",),
    "PO": (".tif",),
}
TILE_GROUP_NODE_PREFIXES = ("Planetka Tile_", "Tile_")
TILE_MASK_NODE_PREFIX = "TileMask_"
TEXTURE_LOADING_GROUP_NAME = "Planetka Textures Loading Group"
LEGACY_TEXTURE_LOADING_TEST_GROUP_NAME = "Planetka Textures Loading Group - Testing"
TILE_PLACEMENT_GROUP_NAME = "Planetka Tile Placement"
TILE_PLACEMENT_GROUP_360_NAME = "Planetka Tile Placement 360"
SURFACE_GRADING_GROUP_NAME = "Planetka Surface Grading Group"
SURFACE_GRADING_SAMPLER_OPT_KEY = "planetka_surface_static_rgb_v1"
TEST_TILE_IMAGE_NODE_PREFIX = "TileImg_"
TILE_PLACEMENT_GROUP_SCHEMA_VERSION = 2
TEXTURE_LOADING_CHANNELS_RGBA = ("S2", "WT", "SE")
TEXTURE_LOADING_CHANNELS_SCALAR = ("EL", "Alpha")
SHADER_TILE_BUDGET_EXPECTED = 12
_COVERAGE_MAP = None
BASE_EMBEDDED_TILE_GROUP_COUNT = 1
TESTING_STATIC_SLOT_COUNT = int(SHADER_TILE_BUDGET_EXPECTED)
TESTING_LOADER_SCHEMA_VERSION_KEY = "planetka_testing_loader_schema_v"
TESTING_LOADER_SCHEMA_VERSION = 2
ANIMATION_SEGMENT_GROUP_TAG_KEY = "planetka_animation_segment_group"


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _is_dynamic_texture_loading_group_name(name):
    token = str(name or "").strip()
    if not token:
        return False
    return bool(
        token in {
            TEXTURE_LOADING_GROUP_NAME,
            LEGACY_TEXTURE_LOADING_TEST_GROUP_NAME,
        }
        or token.startswith(f"{TEXTURE_LOADING_GROUP_NAME}_")
        or token.startswith(f"{LEGACY_TEXTURE_LOADING_TEST_GROUP_NAME}_")
    )


def _is_testing_texture_loading_group(group_tree):
    if group_tree is None:
        return False
    if _is_dynamic_texture_loading_group_name(getattr(group_tree, "name", "")):
        return True
    try:
        schema = int(group_tree.get(TESTING_LOADER_SCHEMA_VERSION_KEY, 0) or 0)
        if schema >= 1:
            return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    try:
        nodes = getattr(group_tree, "nodes", None)
        if nodes is None:
            return False
        if nodes.get(f"{TEST_TILE_IMAGE_NODE_PREFIX}001_S2") is not None:
            return True
        if nodes.get("TileActive_001") is not None:
            return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    return False


def _is_animation_segment_group(group_tree):
    if group_tree is None:
        return False
    try:
        if bool(group_tree.get(ANIMATION_SEGMENT_GROUP_TAG_KEY, False)):
            return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    name = str(getattr(group_tree, "name", "") or "")
    return "_frames_" in name and "Planetka Textures Loading Group" in name

def parse_tile(tile):
    try:
        parts = str(tile).split("_")
        if len(parts) != 4:
            return None
        d_code = int(parts[3][1:])
        if d_code == 0:
            d_code = 1440
        return (
            int(parts[0][1:]),
            int(parts[1][1:]),
            int(parts[2][1:]),
            d_code,
        )
    except (TypeError, ValueError, IndexError):
        return None


def _tile_sort_key(tile):
    parsed = parse_tile(tile)
    if not parsed:
        return (10**9, 10**9, 10**9, 10**9, str(tile))
    x, y, z, d = parsed
    return (d, z, x, y, tile)


def _tiles_overlap(a, b):
    parsed_a = parse_tile(a)
    parsed_b = parse_tile(b)
    if not parsed_a or not parsed_b:
        return False
    xa, ya, za, _ = parsed_a
    xb, yb, zb, _ = parsed_b
    return not (
        xa + za <= xb
        or xb + zb <= xa
        or ya + za <= yb
        or yb + zb <= ya
    )


def _is_land_tile(tile, coverage):
    parsed = parse_tile(tile)
    if not parsed:
        return False
    x, y, z, _ = parsed
    level = coverage.get(int(z), set()) if coverage else set()
    return (int(x), int(y)) in level


def _normalize_requested_tiles(visible_tiles):
    normalized = []
    warned = False
    for tile in visible_tiles or ():
        tile_str = str(tile)
        if tile_str.startswith(PAD_TILE_PREFIX):
            normalized.append(tile_str)
            continue
        if parse_tile(tile_str) is None:
            if not warned:
                logger.warning("Planetka: ignoring malformed tile id(s) in shader input")
                warned = True
            continue
        normalized.append(tile_str)
    return normalized


def _pole_cap_kind(tile):
    parsed = parse_tile(tile)
    if not parsed:
        return ""
    _x, y, z, _d = parsed
    try:
        z_i = int(z)
        y_i = int(y)
    except (TypeError, ValueError):
        return ""
    if z_i not in POLE_CAP_Z_LEVELS:
        return ""
    if y_i <= 0:
        return "south"
    if (y_i + z_i) >= 180:
        return "north"
    return ""


def _get_coverage_map():
    global _COVERAGE_MAP
    if _COVERAGE_MAP is None:
        module_name = f"{__package__}.coverage" if __package__ else "coverage"
        coverage_module = importlib.import_module(module_name)
        _COVERAGE_MAP = getattr(coverage_module, "COVERAGE", {})
    return _COVERAGE_MAP


def detect_ecosystem(tiles):
    for t in tiles or ():
        parsed = parse_tile(t)
        if not parsed:
            continue
        _x, _y, z, _d = parsed
        if int(z) in POWER_Z:
            return "power"
    return "decimal"


def _load_image_cached(path, cache_by_path, image_name=None):
    norm_path = os.path.normcase(os.path.normpath(path)) if path else ""
    if norm_path in cache_by_path:
        return cache_by_path[norm_path]

    if not path or not os.path.exists(path):
        cache_by_path[norm_path] = None
        return None

    try:
        img = bpy.data.images.load(path, check_existing=True)
        if image_name:
            img.name = image_name
        try:
            img.use_fake_user = False
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-001", "Failed to clear fake-user on loaded image")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.warning("Planetka: failed loading image '%s'", path, exc_info=True)
        img = None

    cache_by_path[norm_path] = img
    return img


def _assign_image_to_node(img_node, image, img_type, use_fallback):
    img_node.image = image
    try:
        img_node.interpolation = "Closest" if use_fallback else "Linear"
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-SHADER-002", "Failed setting image node interpolation")
    try:
        img_node.extension = "EXTEND"
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-SHADER-003", "Failed setting image node extension")

    if image is None:
        return
    _set_image_colorspace_safe(image, "Non-Color" if img_type == "EL" else "Linear Rec.709")


def _set_image_colorspace_safe(image, colorspace):
    if image is None:
        return
    settings = getattr(image, "colorspace_settings", None)
    if settings is None or not hasattr(settings, "name"):
        return

    candidates = [colorspace]
    if colorspace == "Linear Rec.709":
        candidates.extend(["Linear", "Raw"])
    elif colorspace == "Non-Color":
        candidates.extend(["Raw"])

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


def _first_image_rgb(image, default_rgb):
    if image is None:
        return tuple(default_rgb)
    try:
        pixels = getattr(image, "pixels", None)
        if pixels is None or len(pixels) < 3:
            return tuple(default_rgb)
        return (float(pixels[0]), float(pixels[1]), float(pixels[2]))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
        return tuple(default_rgb)


def _ensure_surface_grading_static_rgb_sources():
    surface_group = bpy.data.node_groups.get(SURFACE_GRADING_GROUP_NAME)
    if surface_group is None:
        return
    try:
        if int(surface_group.get(SURFACE_GRADING_SAMPLER_OPT_KEY, 0) or 0) >= 1:
            return
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
        pass

    extension_dir = os.path.dirname(os.path.abspath(__file__))
    fallback_dir = os.path.join(extension_dir, "Resources", "Fallback Images")
    image_cache = {}
    bindings = (
        ("Image Texture", os.path.join(fallback_dir, "ocean_pixel_final_20.exr"), (0.0, 0.0, 0.0)),
        ("Image Texture.001", os.path.join(fallback_dir, "blue_pixel_20.exr"), (0.0, 0.0, 1.0)),
    )

    for node_name, image_path, default_rgb in bindings:
        node = surface_group.nodes.get(node_name)
        if node is None:
            continue
        if node.bl_idname == "ShaderNodeRGB":
            continue
        if node.bl_idname != "ShaderNodeTexImage":
            continue

        image = _load_image_cached(image_path, image_cache, image_name=os.path.basename(image_path))
        rgb = _first_image_rgb(image, default_rgb)
        old_location = tuple(getattr(node, "location", (0.0, 0.0)))
        old_parent = getattr(node, "parent", None)
        to_sockets = []
        try:
            color_output = node.outputs.get("Color")
            if color_output is not None:
                to_sockets = [link.to_socket for link in color_output.links]
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            to_sockets = []

        try:
            surface_group.nodes.remove(node)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-041", "Failed replacing surface grading texture sampler")
            continue

        rgb_node = surface_group.nodes.new("ShaderNodeRGB")
        rgb_node.name = node_name
        rgb_node.label = node_name
        rgb_node.outputs[0].default_value = (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)
        try:
            rgb_node.location = old_location
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            pass
        try:
            rgb_node.parent = old_parent
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            pass

        for to_socket in to_sockets:
            try:
                surface_group.links.new(rgb_node.outputs[0], to_socket)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-SHADER-042", "Failed reconnecting surface grading RGB constant")

    try:
        surface_group[SURFACE_GRADING_SAMPLER_OPT_KEY] = 1
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass


def _set_node_location_safe(node, x, y):
    if node is None:
        return
    try:
        node.location = (float(x), float(y))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        return


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
                continue


def _image_file_size_bytes(image):
    if image is None:
        return 0
    raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", ""))
    if not raw_path:
        return 0
    abs_path = bpy.path.abspath(raw_path)
    if not abs_path or not os.path.isfile(abs_path):
        return 0
    try:
        return int(os.path.getsize(abs_path))
    except (OSError, TypeError, ValueError):
        return 0


def _iter_tile_group_nodes(node_tree):
    for node in node_tree.nodes:
        if node.type != "GROUP":
            continue
        if node.name.startswith(TILE_GROUP_NODE_PREFIXES):
            yield node


def _trailing_int_or_default(name, default=10**9):
    parts = str(name).rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return default


def _sorted_tile_group_nodes(node_tree):
    nodes = list(_iter_tile_group_nodes(node_tree))
    nodes.sort(key=lambda node: (_trailing_int_or_default(node.name), node.name))
    return nodes


def _tile_group_name_candidates(index):
    idx = int(index)
    return (
        f"Planetka Tile_{idx:02d}",
        f"Planetka Tile_{idx:03d}",
        f"Planetka Tile_{idx}",
    )


def _tile_group_name_for_variant(index, variant="regular"):
    idx = int(index)
    if str(variant or "regular").lower() == "z360":
        return f"Planetka Tile360_{idx:03d}"
    return f"Planetka Tile_{idx:03d}"


def _get_tile_group_by_index(index, variant="regular"):
    if str(variant or "regular").lower() == "z360":
        group = bpy.data.node_groups.get(_tile_group_name_for_variant(index, variant="z360"))
        if group is not None:
            return group
        return None
    for name in _tile_group_name_candidates(index):
        group = bpy.data.node_groups.get(name)
        if group is not None:
            return group
    return None


def _get_tile_group_template():
    for index in range(1, BASE_EMBEDDED_TILE_GROUP_COUNT + 1):
        group = _get_tile_group_by_index(index)
        if group is not None:
            return group
    for group in bpy.data.node_groups:
        if group.name.startswith("Planetka Tile_"):
            return group
    return None


def _strip_z360_logic_from_tile_group(tile_group):
    if tile_group is None:
        return
    nodes = getattr(tile_group, "nodes", None)
    links = getattr(tile_group, "links", None)
    if nodes is None or links is None:
        return

    mapping_node = nodes.get("Mapping.001")
    if mapping_node is None:
        mapping_node = nodes.get("Mapping")
    if mapping_node is None:
        return

    group_output = next((node for node in nodes if node.type == "GROUP_OUTPUT"), None)
    alpha_input = group_output.inputs.get("Alpha") if group_output is not None else None
    mul_xy = nodes.get("PKA AlphaMask MulXY")

    for node in list(nodes):
        node_name = str(getattr(node, "name", "") or "")
        if node_name.startswith("PKA Z360 "):
            try:
                nodes.remove(node)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-SHADER-020", "Failed removing z360 helper node from regular tile group")
            except (RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-SHADER-021", "Failed removing z360 helper node from regular tile group")
            continue
        if node_name == "PKA AlphaMask Z360 Mix":
            try:
                nodes.remove(node)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-SHADER-022", "Failed removing z360 alpha mix node from regular tile group")
            except (RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-SHADER-023", "Failed removing z360 alpha mix node from regular tile group")

    texture_nodes = []
    for img_type in TEXTURE_TYPES:
        tex_node = nodes.get(img_type)
        if tex_node is not None and str(getattr(tex_node, "bl_idname", "")) == "ShaderNodeTexImage":
            texture_nodes.append(tex_node)

    for tex_node in texture_nodes:
        vector_input = tex_node.inputs.get("Vector") if hasattr(tex_node, "inputs") else None
        if vector_input is None:
            continue
        try:
            for old_link in list(vector_input.links):
                links.remove(old_link)
            links.new(mapping_node.outputs["Vector"], vector_input)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-024", "Failed rewiring regular tile vector input")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-025", "Failed rewiring regular tile vector input")

    if alpha_input is not None and mul_xy is not None:
        try:
            for old_link in list(alpha_input.links):
                links.remove(old_link)
            links.new(mul_xy.outputs[0], alpha_input)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-026", "Failed rewiring regular tile alpha mask")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-027", "Failed rewiring regular tile alpha mask")


def _ensure_tile_group_for_index(index, variant="regular"):
    variant_text = str(variant or "regular").lower()
    group = _get_tile_group_by_index(index, variant=variant_text)
    if group is not None:
        if variant_text != "z360":
            _strip_z360_logic_from_tile_group(group)
        return group

    template = _get_tile_group_template()
    if template is None:
        raise RuntimeError("Planetka: no tile node group template is available.")

    new_group = template.copy()
    new_group.name = _tile_group_name_for_variant(index, variant=variant_text)
    try:
        new_group.use_fake_user = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-SHADER-004", "Failed to set fake-user on dynamic tile group")
    if variant_text != "z360":
        _strip_z360_logic_from_tile_group(new_group)
    return new_group


def _ensure_testing_texture_loading_group(source_group):
    if source_group is None:
        return None
    existing = bpy.data.node_groups.get(TEXTURE_LOADING_GROUP_NAME)
    if existing is not None:
        return existing
    legacy = bpy.data.node_groups.get(LEGACY_TEXTURE_LOADING_TEST_GROUP_NAME)
    if legacy is not None:
        try:
            legacy.name = TEXTURE_LOADING_GROUP_NAME
            return legacy
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-019A", "Failed renaming legacy testing texture loading group")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-019B", "Failed renaming legacy testing texture loading group")
    testing_group = source_group.copy()
    testing_group.name = TEXTURE_LOADING_GROUP_NAME
    try:
        testing_group.use_fake_user = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-SHADER-019", "Failed to set fake-user on testing texture loading group")
    return testing_group


def _get_socket_by_name_or_index(socket_collection, socket_name, fallback_index):
    if socket_collection is None:
        return None
    socket = socket_collection.get(str(socket_name)) if hasattr(socket_collection, "get") else None
    if socket is not None:
        return socket
    sockets = list(socket_collection)
    if 0 <= int(fallback_index) < len(sockets):
        return sockets[int(fallback_index)]
    return None


def _build_regular_tile_placement_group(target_name):
    template = _ensure_tile_group_for_index(1, variant="regular")
    if template is None:
        raise RuntimeError("Planetka: no regular tile group template is available for placement group.")

    placement = template.copy()
    placement.name = str(target_name)
    try:
        placement.use_fake_user = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-SHADER-028", "Failed setting fake-user on tile placement group")

    nodes = placement.nodes
    links = placement.links

    group_input = next((node for node in nodes if node.type == "GROUP_INPUT"), None)
    group_output = next((node for node in nodes if node.type == "GROUP_OUTPUT"), None)
    texcoord = nodes.get("Texture Coordinate") or next(
        (node for node in nodes if str(getattr(node, "bl_idname", "")) == "ShaderNodeTexCoord"),
        None,
    )
    mapping = nodes.get("Mapping.001") or nodes.get("Mapping") or next(
        (node for node in nodes if str(getattr(node, "bl_idname", "")) == "ShaderNodeMapping"),
        None,
    )
    if group_input is None or group_output is None or texcoord is None or mapping is None:
        raise RuntimeError("Planetka: failed preparing regular tile placement core nodes.")

    for link in list(links):
        links.remove(link)
    for node in list(nodes):
        if node in {group_input, group_output, texcoord, mapping}:
            continue
        nodes.remove(node)

    x_input = _get_socket_by_name_or_index(getattr(group_input, "outputs", None), "x", 0)
    y_input = _get_socket_by_name_or_index(getattr(group_input, "outputs", None), "y", 1)
    z_input = _get_socket_by_name_or_index(getattr(group_input, "outputs", None), "z", 2)
    if x_input is None or y_input is None or z_input is None:
        raise RuntimeError("Planetka: tile placement group inputs x/y/z are unavailable.")

    s2_output = _get_socket_by_name_or_index(getattr(group_output, "inputs", None), "S2", 0)
    alpha_output = _get_socket_by_name_or_index(getattr(group_output, "inputs", None), "Alpha", 3)
    if s2_output is None or alpha_output is None:
        raise RuntimeError("Planetka: tile placement group outputs S2/Alpha are unavailable.")

    inv_z = nodes.new("ShaderNodeMath")
    inv_z.name = "PKA Pl InvZ"
    inv_z.operation = "DIVIDE"
    inv_z.inputs[0].default_value = 1.0

    scale_x = nodes.new("ShaderNodeMath")
    scale_x.name = "PKA Pl ScaleX"
    scale_x.operation = "MULTIPLY"
    scale_x.inputs[1].default_value = 360.0

    scale_y = nodes.new("ShaderNodeMath")
    scale_y.name = "PKA Pl ScaleY"
    scale_y.operation = "MULTIPLY"
    scale_y.inputs[1].default_value = 180.0

    combine_scale = nodes.new("ShaderNodeCombineXYZ")
    combine_scale.name = "PKA Pl CombineScale"
    combine_scale.inputs[2].default_value = 1.0

    combine_xy = nodes.new("ShaderNodeCombineXYZ")
    combine_xy.name = "PKA Pl CombineXY"
    combine_xy.inputs[2].default_value = 0.0

    xy_scale = nodes.new("ShaderNodeVectorMath")
    xy_scale.name = "PKA Pl XYScale"
    xy_scale.operation = "SCALE"

    xy_neg = nodes.new("ShaderNodeVectorMath")
    xy_neg.name = "PKA Pl XYNeg"
    xy_neg.operation = "SCALE"
    xy_neg.inputs[3].default_value = -1.0

    alpha_max = nodes.new("ShaderNodeVectorMath")
    alpha_max.name = "PKA Pl AlphaMax"
    alpha_max.operation = "MAXIMUM"
    alpha_max.inputs[1].default_value = (0.0, 0.0, 0.0)

    alpha_min = nodes.new("ShaderNodeVectorMath")
    alpha_min.name = "PKA Pl AlphaMin"
    alpha_min.operation = "MINIMUM"
    alpha_min.inputs[1].default_value = (1.0, 1.0, 1.0)

    alpha_delta = nodes.new("ShaderNodeVectorMath")
    alpha_delta.name = "PKA Pl AlphaDelta"
    alpha_delta.operation = "SUBTRACT"

    alpha_len = nodes.new("ShaderNodeVectorMath")
    alpha_len.name = "PKA Pl AlphaLen"
    alpha_len.operation = "LENGTH"

    alpha_cmp = nodes.new("ShaderNodeMath")
    alpha_cmp.name = "PKA Pl AlphaCmp"
    alpha_cmp.operation = "LESS_THAN"
    alpha_cmp.inputs[1].default_value = 1e-6

    links.new(z_input, inv_z.inputs[1])
    links.new(inv_z.outputs[0], scale_x.inputs[0])
    links.new(inv_z.outputs[0], scale_y.inputs[0])
    links.new(scale_x.outputs[0], combine_scale.inputs[0])
    links.new(scale_y.outputs[0], combine_scale.inputs[1])

    links.new(x_input, combine_xy.inputs[0])
    links.new(y_input, combine_xy.inputs[1])
    links.new(combine_xy.outputs[0], xy_scale.inputs[0])
    links.new(inv_z.outputs[0], xy_scale.inputs[3])
    links.new(xy_scale.outputs[0], xy_neg.inputs[0])

    links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])
    links.new(combine_scale.outputs[0], mapping.inputs["Scale"])
    links.new(xy_neg.outputs[0], mapping.inputs["Location"])

    links.new(mapping.outputs["Vector"], s2_output)

    links.new(mapping.outputs["Vector"], alpha_max.inputs[0])
    links.new(alpha_max.outputs[0], alpha_min.inputs[0])
    links.new(mapping.outputs["Vector"], alpha_delta.inputs[0])
    links.new(alpha_min.outputs[0], alpha_delta.inputs[1])
    links.new(alpha_delta.outputs[0], alpha_len.inputs[0])
    links.new(alpha_len.outputs[1], alpha_cmp.inputs[0])
    links.new(alpha_cmp.outputs[0], alpha_output)

    _set_node_location_safe(group_input, -1420.0, 120.0)
    _set_node_location_safe(texcoord, -1420.0, -220.0)
    _set_node_location_safe(inv_z, -1160.0, 160.0)
    _set_node_location_safe(scale_x, -920.0, 260.0)
    _set_node_location_safe(scale_y, -920.0, 140.0)
    _set_node_location_safe(combine_scale, -680.0, 220.0)
    _set_node_location_safe(combine_xy, -920.0, -40.0)
    _set_node_location_safe(xy_scale, -680.0, -40.0)
    _set_node_location_safe(xy_neg, -460.0, -40.0)
    _set_node_location_safe(mapping, -220.0, 20.0)
    _set_node_location_safe(alpha_max, 20.0, -200.0)
    _set_node_location_safe(alpha_min, 260.0, -200.0)
    _set_node_location_safe(alpha_delta, 500.0, -200.0)
    _set_node_location_safe(alpha_len, 740.0, -200.0)
    _set_node_location_safe(alpha_cmp, 980.0, -200.0)
    _set_node_location_safe(group_output, 1240.0, 20.0)

    placement["planetka_variant"] = "regular"
    placement["planetka_schema_v"] = int(TILE_PLACEMENT_GROUP_SCHEMA_VERSION)
    _hide_unconnected_group_input_sockets(placement)
    return placement


def _ensure_tile_placement_group(variant="regular"):
    variant_text = str(variant or "regular").lower()
    target_name = TILE_PLACEMENT_GROUP_360_NAME if variant_text == "z360" else TILE_PLACEMENT_GROUP_NAME
    existing = bpy.data.node_groups.get(target_name)
    if existing is not None:
        try:
            existing_variant = str(existing.get("planetka_variant", "") or "").lower()
            existing_schema = int(existing.get("planetka_schema_v", 0) or 0)
        except (TypeError, ValueError):
            existing_variant = ""
            existing_schema = 0
        if existing_variant == variant_text and existing_schema >= int(TILE_PLACEMENT_GROUP_SCHEMA_VERSION):
            return existing
        try:
            bpy.data.node_groups.remove(existing, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-039", "Failed replacing outdated tile placement group")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-040", "Failed replacing outdated tile placement group")

    if variant_text == "regular":
        return _build_regular_tile_placement_group(target_name)

    if variant_text == "z360":
        template = _get_tile_group_template()
    else:
        template = _ensure_tile_group_for_index(1, variant="regular")
    if template is None:
        raise RuntimeError("Planetka: no tile node group template is available for placement group.")

    placement = template.copy()
    placement.name = target_name
    try:
        placement.use_fake_user = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-SHADER-028", "Failed setting fake-user on tile placement group")

    # Keep mapping/mask/z360 math, remove texture samplers.
    nodes = placement.nodes
    links = placement.links
    for node_name in ("S2", "EL", "WT", "PO", "Separate Color"):
        node = nodes.get(node_name)
        if node is not None:
            try:
                nodes.remove(node)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-SHADER-029", "Failed removing texture node from placement group")
            except (RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-SHADER-030", "Failed removing texture node from placement group")

    _stabilize_tile_group_mask_sources(placement, enable_z360=(variant_text == "z360"))

    output_node = next((node for node in nodes if node.type == "GROUP_OUTPUT"), None)
    if output_node is None:
        return placement

    output_inputs = {socket.name: socket for socket in output_node.inputs}
    if variant_text == "z360":
        vector_out = nodes.get("PKA Z360 Vector Mix")
        alpha_out = nodes.get("PKA AlphaMask Z360 Mix") or nodes.get("PKA AlphaMask MulXY")
    else:
        vector_out = nodes.get("Mapping.001") or nodes.get("Mapping")
        alpha_out = nodes.get("PKA AlphaMask MulXY")

    # Rewire outputs so existing sockets carry placement data:
    # - S2 socket carries UV vector (RGBA->Vector is accepted by Blender links)
    # - Alpha socket carries tile alpha mask
    s2_socket = output_inputs.get("S2")
    alpha_socket = output_inputs.get("Alpha")
    if s2_socket is not None and vector_out is not None:
        try:
            for link in list(s2_socket.links):
                links.remove(link)
            links.new(vector_out.outputs[0], s2_socket)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-031", "Failed rewiring placement vector output")
        except (RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            _log_recoverable_once("PKA-SHADER-032", "Failed rewiring placement vector output")
    if alpha_socket is not None and alpha_out is not None:
        try:
            for link in list(alpha_socket.links):
                links.remove(link)
            links.new(alpha_out.outputs[0], alpha_socket)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-033", "Failed rewiring placement alpha output")
        except (RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            _log_recoverable_once("PKA-SHADER-034", "Failed rewiring placement alpha output")

    # Explicitly disconnect texture-specific outputs not used by placement variant.
    for name in ("EL", "WT", "SE"):
        socket = output_inputs.get(name)
        if socket is None:
            continue
        try:
            for link in list(socket.links):
                links.remove(link)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-035", "Failed disconnecting unused placement output")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-036", "Failed disconnecting unused placement output")

    placement["planetka_variant"] = "z360"
    placement["planetka_schema_v"] = int(TILE_PLACEMENT_GROUP_SCHEMA_VERSION)
    return placement


def _layout_tile_group_readable(nodes, mapping_node, group_input, group_output, texture_nodes):
    if nodes is None or mapping_node is None:
        return
    try:
        base_x = float(mapping_node.location[0])
        base_y = float(mapping_node.location[1])
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError):
        base_x = 0.0
        base_y = 0.0

    if group_input is not None:
        # Keep group inputs clearly detached on the far-left edge.
        _set_node_location_safe(group_input, base_x - 900.0, base_y + 20.0)
    _set_node_location_safe(mapping_node, base_x, base_y)

    name_to_pos = {
        # Use larger lane spacing to prevent visual overlap in Blender's node editor.
        "PKA AlphaMask Separate": (base_x + 240.0, base_y + 40.0),
        "PKA AlphaMask XMin": (base_x + 520.0, base_y + 260.0),
        "PKA AlphaMask XMax": (base_x + 520.0, base_y + 120.0),
        "PKA AlphaMask YMin": (base_x + 520.0, base_y - 20.0),
        "PKA AlphaMask YMax": (base_x + 520.0, base_y - 160.0),
        "PKA AlphaMask MulX": (base_x + 800.0, base_y + 200.0),
        "PKA AlphaMask MulY": (base_x + 800.0, base_y - 90.0),
        "PKA AlphaMask MulXY": (base_x + 1080.0, base_y + 40.0),
        "PKA Z360 TexCoord": (base_x + 240.0, base_y - 420.0),
        "PKA Z360 Flag": (base_x + 520.0, base_y - 420.0),
        "PKA Z360 Inv Flag": (base_x + 800.0, base_y - 420.0),
        "PKA Z360 Mapped Scale": (base_x + 1080.0, base_y - 340.0),
        "PKA Z360 Native Scale": (base_x + 1080.0, base_y - 500.0),
        "PKA Z360 Vector Mix": (base_x + 1360.0, base_y - 420.0),
        "PKA AlphaMask Z360 Mix": (base_x + 1360.0, base_y + 40.0),
    }
    for node_name, (node_x, node_y) in name_to_pos.items():
        node = nodes.get(node_name)
        if node is not None:
            _set_node_location_safe(node, node_x, node_y)

    texture_base_x = base_x + 1680.0
    texture_y_map = {
        "S2": base_y + 320.0,
        "EL": base_y + 100.0,
        "WT": base_y - 120.0,
        "PO": base_y - 340.0,
    }
    for tex_node in texture_nodes or ():
        node_name = str(getattr(tex_node, "name", "") or "")
        tex_y = texture_y_map.get(node_name, base_y)
        _set_node_location_safe(tex_node, texture_base_x, tex_y)

    output_x = texture_base_x + 460.0
    output_y = base_y - 20.0
    if group_output is not None:
        _set_node_location_safe(group_output, output_x, output_y)

    # Keep EL channel separator nodes in the final lane near outputs.
    # This prevents orphan "Separate Color" nodes from sitting in the middle of the graph.
    el_sep_y = texture_y_map.get("EL", base_y)
    el_sep_offset = 0.0
    for node in list(nodes):
        node_type = str(getattr(node, "bl_idname", "") or "")
        if node_type not in {"ShaderNodeSeparateColor", "ShaderNodeSeparateRGB"}:
            continue

        receives_el = False
        feeds_group_output = False

        for in_socket in getattr(node, "inputs", ()):
            for link in getattr(in_socket, "links", ()):
                from_node = getattr(link, "from_node", None)
                from_name = str(getattr(from_node, "name", "") or "")
                if from_name == "EL":
                    receives_el = True
                    break
            if receives_el:
                break

        for out_socket in getattr(node, "outputs", ()):
            for link in getattr(out_socket, "links", ()):
                to_node = getattr(link, "to_node", None)
                if to_node is not None and getattr(to_node, "type", "") == "GROUP_OUTPUT":
                    feeds_group_output = True
                    break
            if feeds_group_output:
                break

        if not (receives_el or feeds_group_output):
            continue

        _set_node_location_safe(node, output_x - 300.0, el_sep_y - 20.0 - el_sep_offset)
        el_sep_offset += 160.0


def _stabilize_tile_group_mask_sources(tile_group, enable_z360=True):
    if tile_group is None:
        return
    nodes = getattr(tile_group, "nodes", None)
    links = getattr(tile_group, "links", None)
    if nodes is None or links is None:
        return

    group_output = next((node for node in nodes if node.type == "GROUP_OUTPUT"), None)
    group_input = next((node for node in nodes if node.type == "GROUP_INPUT"), None)
    mapping_node = nodes.get("Mapping.001")
    if mapping_node is None:
        mapping_node = nodes.get("Mapping")
    alpha_input = group_output.inputs.get("Alpha") if group_output else None
    texture_nodes = []
    for img_type in TEXTURE_TYPES:
        tex_node = nodes.get(img_type)
        if tex_node is not None and str(getattr(tex_node, "bl_idname", "")) == "ShaderNodeTexImage":
            texture_nodes.append(tex_node)

    if mapping_node is not None and alpha_input is not None:
        mask_eps = 1e-6
        try:
            mapping_x = float(mapping_node.location[0])
            mapping_y = float(mapping_node.location[1])
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError):
            mapping_x = 0.0
            mapping_y = 0.0

        separate = nodes.get("PKA AlphaMask Separate")
        if separate is None or separate.bl_idname != "ShaderNodeSeparateXYZ":
            if separate is not None:
                try:
                    nodes.remove(separate)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-005", "Failed removing stale alpha-mask separate node")
            separate = nodes.new("ShaderNodeSeparateXYZ")
            separate.name = "PKA AlphaMask Separate"
        _set_node_location_safe(separate, mapping_x + 220.0, mapping_y)

        x_gt = nodes.get("PKA AlphaMask XMin")
        if x_gt is None or x_gt.bl_idname != "ShaderNodeMath":
            if x_gt is not None:
                try:
                    nodes.remove(x_gt)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-006", "Failed removing stale alpha-mask XMin node")
            x_gt = nodes.new("ShaderNodeMath")
            x_gt.name = "PKA AlphaMask XMin"
        x_gt.operation = "GREATER_THAN"
        x_gt.inputs[1].default_value = -mask_eps
        _set_node_location_safe(x_gt, mapping_x + 440.0, mapping_y + 110.0)

        x_lt = nodes.get("PKA AlphaMask XMax")
        if x_lt is None or x_lt.bl_idname != "ShaderNodeMath":
            if x_lt is not None:
                try:
                    nodes.remove(x_lt)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-007", "Failed removing stale alpha-mask XMax node")
            x_lt = nodes.new("ShaderNodeMath")
            x_lt.name = "PKA AlphaMask XMax"
        x_lt.operation = "LESS_THAN"
        x_lt.inputs[1].default_value = 1.0 + mask_eps
        _set_node_location_safe(x_lt, mapping_x + 440.0, mapping_y + 30.0)

        y_gt = nodes.get("PKA AlphaMask YMin")
        if y_gt is None or y_gt.bl_idname != "ShaderNodeMath":
            if y_gt is not None:
                try:
                    nodes.remove(y_gt)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-008", "Failed removing stale alpha-mask YMin node")
            y_gt = nodes.new("ShaderNodeMath")
            y_gt.name = "PKA AlphaMask YMin"
        y_gt.operation = "GREATER_THAN"
        y_gt.inputs[1].default_value = -mask_eps
        _set_node_location_safe(y_gt, mapping_x + 440.0, mapping_y - 50.0)

        y_lt = nodes.get("PKA AlphaMask YMax")
        if y_lt is None or y_lt.bl_idname != "ShaderNodeMath":
            if y_lt is not None:
                try:
                    nodes.remove(y_lt)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-009", "Failed removing stale alpha-mask YMax node")
            y_lt = nodes.new("ShaderNodeMath")
            y_lt.name = "PKA AlphaMask YMax"
        y_lt.operation = "LESS_THAN"
        y_lt.inputs[1].default_value = 1.0 + mask_eps
        _set_node_location_safe(y_lt, mapping_x + 440.0, mapping_y - 130.0)

        mul_x = nodes.get("PKA AlphaMask MulX")
        if mul_x is None or mul_x.bl_idname != "ShaderNodeMath":
            if mul_x is not None:
                try:
                    nodes.remove(mul_x)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-010", "Failed removing stale alpha-mask MulX node")
            mul_x = nodes.new("ShaderNodeMath")
            mul_x.name = "PKA AlphaMask MulX"
        mul_x.operation = "MULTIPLY"
        _set_node_location_safe(mul_x, mapping_x + 660.0, mapping_y + 70.0)

        mul_y = nodes.get("PKA AlphaMask MulY")
        if mul_y is None or mul_y.bl_idname != "ShaderNodeMath":
            if mul_y is not None:
                try:
                    nodes.remove(mul_y)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-011", "Failed removing stale alpha-mask MulY node")
            mul_y = nodes.new("ShaderNodeMath")
            mul_y.name = "PKA AlphaMask MulY"
        mul_y.operation = "MULTIPLY"
        _set_node_location_safe(mul_y, mapping_x + 660.0, mapping_y - 70.0)

        mul_xy = nodes.get("PKA AlphaMask MulXY")
        if mul_xy is None or mul_xy.bl_idname != "ShaderNodeMath":
            if mul_xy is not None:
                try:
                    nodes.remove(mul_xy)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-SHADER-012", "Failed removing stale alpha-mask MulXY node")
            mul_xy = nodes.new("ShaderNodeMath")
            mul_xy.name = "PKA AlphaMask MulXY"
        mul_xy.operation = "MULTIPLY"
        _set_node_location_safe(mul_xy, mapping_x + 880.0, mapping_y)

        try:
            links.new(mapping_node.outputs["Vector"], separate.inputs["Vector"])
            links.new(separate.outputs["X"], x_gt.inputs[0])
            links.new(separate.outputs["X"], x_lt.inputs[0])
            links.new(separate.outputs["Y"], y_gt.inputs[0])
            links.new(separate.outputs["Y"], y_lt.inputs[0])
            links.new(x_gt.outputs[0], mul_x.inputs[0])
            links.new(x_lt.outputs[0], mul_x.inputs[1])
            links.new(y_gt.outputs[0], mul_y.inputs[0])
            links.new(y_lt.outputs[0], mul_y.inputs[1])
            links.new(mul_x.outputs[0], mul_xy.inputs[0])
            links.new(mul_y.outputs[0], mul_xy.inputs[1])

            existing = alpha_input.links[0] if alpha_input.links else None
            if existing is None or existing.from_socket != mul_xy.outputs[0]:
                for link in list(alpha_input.links):
                    links.remove(link)
                links.new(mul_xy.outputs[0], alpha_input)

            # z360 tiles bypass XY tile mapping and use native UVs directly.
            # A 360x180 texture already matches sphere UVs and should not be remapped.
            z_input_socket = None
            if bool(enable_z360):
                if group_input is not None:
                    z_input_socket = group_input.outputs.get("Z") or group_input.outputs.get("z")
                    if z_input_socket is None:
                        group_outputs = list(getattr(group_input, "outputs", ()))
                        if len(group_outputs) > 2:
                            z_input_socket = group_outputs[2]

            if bool(enable_z360) and z_input_socket is not None and texture_nodes:
                texcoord = nodes.get("PKA Z360 TexCoord")
                if texcoord is None or texcoord.bl_idname != "ShaderNodeTexCoord":
                    if texcoord is not None:
                        nodes.remove(texcoord)
                    texcoord = nodes.new("ShaderNodeTexCoord")
                    texcoord.name = "PKA Z360 TexCoord"
                _set_node_location_safe(texcoord, mapping_x + 220.0, mapping_y - 320.0)

                z360_flag = nodes.get("PKA Z360 Flag")
                if z360_flag is None or z360_flag.bl_idname != "ShaderNodeMath":
                    if z360_flag is not None:
                        nodes.remove(z360_flag)
                    z360_flag = nodes.new("ShaderNodeMath")
                    z360_flag.name = "PKA Z360 Flag"
                z360_flag.operation = "GREATER_THAN"
                z360_flag.inputs[1].default_value = 359.0
                _set_node_location_safe(z360_flag, mapping_x + 440.0, mapping_y - 320.0)

                inv_flag = nodes.get("PKA Z360 Inv Flag")
                if inv_flag is None or inv_flag.bl_idname != "ShaderNodeMath":
                    if inv_flag is not None:
                        nodes.remove(inv_flag)
                    inv_flag = nodes.new("ShaderNodeMath")
                    inv_flag.name = "PKA Z360 Inv Flag"
                inv_flag.operation = "SUBTRACT"
                inv_flag.inputs[0].default_value = 1.0
                _set_node_location_safe(inv_flag, mapping_x + 660.0, mapping_y - 320.0)

                mapped_scale = nodes.get("PKA Z360 Mapped Scale")
                if mapped_scale is None or mapped_scale.bl_idname != "ShaderNodeVectorMath":
                    if mapped_scale is not None:
                        nodes.remove(mapped_scale)
                    mapped_scale = nodes.new("ShaderNodeVectorMath")
                    mapped_scale.name = "PKA Z360 Mapped Scale"
                mapped_scale.operation = "SCALE"
                _set_node_location_safe(mapped_scale, mapping_x + 880.0, mapping_y - 260.0)

                native_scale = nodes.get("PKA Z360 Native Scale")
                if native_scale is None or native_scale.bl_idname != "ShaderNodeVectorMath":
                    if native_scale is not None:
                        nodes.remove(native_scale)
                    native_scale = nodes.new("ShaderNodeVectorMath")
                    native_scale.name = "PKA Z360 Native Scale"
                native_scale.operation = "SCALE"
                _set_node_location_safe(native_scale, mapping_x + 880.0, mapping_y - 380.0)

                vector_mix = nodes.get("PKA Z360 Vector Mix")
                if vector_mix is None or vector_mix.bl_idname != "ShaderNodeVectorMath":
                    if vector_mix is not None:
                        nodes.remove(vector_mix)
                    vector_mix = nodes.new("ShaderNodeVectorMath")
                    vector_mix.name = "PKA Z360 Vector Mix"
                vector_mix.operation = "ADD"
                _set_node_location_safe(vector_mix, mapping_x + 1100.0, mapping_y - 320.0)

                alpha_z360 = nodes.get("PKA AlphaMask Z360 Mix")
                if alpha_z360 is None or alpha_z360.bl_idname != "ShaderNodeMath":
                    if alpha_z360 is not None:
                        nodes.remove(alpha_z360)
                    alpha_z360 = nodes.new("ShaderNodeMath")
                    alpha_z360.name = "PKA AlphaMask Z360 Mix"
                alpha_z360.operation = "MAXIMUM"
                _set_node_location_safe(alpha_z360, mapping_x + 1100.0, mapping_y + 10.0)

                links.new(z_input_socket, z360_flag.inputs[0])
                links.new(z360_flag.outputs[0], inv_flag.inputs[1])
                links.new(mapping_node.outputs["Vector"], mapped_scale.inputs[0])
                links.new(inv_flag.outputs[0], mapped_scale.inputs[3])
                links.new(texcoord.outputs["UV"], native_scale.inputs[0])
                links.new(z360_flag.outputs[0], native_scale.inputs[3])
                links.new(mapped_scale.outputs[0], vector_mix.inputs[0])
                links.new(native_scale.outputs[0], vector_mix.inputs[1])
                links.new(mul_xy.outputs[0], alpha_z360.inputs[0])
                links.new(z360_flag.outputs[0], alpha_z360.inputs[1])

                for tex_node in texture_nodes:
                    vector_input = tex_node.inputs.get("Vector") if hasattr(tex_node, "inputs") else None
                    if vector_input is None:
                        continue
                    for old_link in list(vector_input.links):
                        links.remove(old_link)
                    links.new(vector_mix.outputs[0], vector_input)

                for old_link in list(alpha_input.links):
                    links.remove(old_link)
                links.new(alpha_z360.outputs[0], alpha_input)
            elif not bool(enable_z360):
                _strip_z360_logic_from_tile_group(tile_group)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-013", "Failed wiring z360/native UV stabilization links")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-014", "Failed wiring z360/native UV stabilization links")

        # Remove legacy tight-mask gating nodes (introduced experimentally for WT seams).
        try:
            for channel_name in ("WT", "SE"):
                channel_input = group_output.inputs.get(channel_name) if group_output else None
                if channel_input is None or not channel_input.links:
                    continue
                link0 = channel_input.links[0]
                from_node = getattr(link0, "from_node", None)
                if from_node is None:
                    continue
                from_name = str(getattr(from_node, "name", "") or "")
                if not from_name.startswith("PKA TightMask Gate"):
                    continue
                gate_in = getattr(from_node, "inputs", None)
                gate_in = gate_in[0] if gate_in and len(gate_in) > 0 else None
                upstream = gate_in.links[0].from_socket if gate_in and gate_in.links else None
                if upstream is None:
                    continue
                for link in list(channel_input.links):
                    links.remove(link)
                links.new(upstream, channel_input)

            for node in list(nodes):
                if str(getattr(node, "name", "") or "").startswith("PKA TightMask"):
                    nodes.remove(node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-015", "Failed removing legacy tight-mask nodes")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-016", "Failed removing legacy tight-mask nodes")

        _layout_tile_group_readable(
            nodes=nodes,
            mapping_node=mapping_node,
            group_input=group_input,
            group_output=group_output,
            texture_nodes=texture_nodes,
        )
        _hide_unconnected_group_input_sockets(tile_group)

def _resolve_tiles_for_shader(visible_tiles, base_path):
    requested_tiles = _normalize_requested_tiles(visible_tiles)
    if not requested_tiles:
        return [], set()
    ecosystem = detect_ecosystem(requested_tiles)
    coverage = _get_coverage_map()

    land_tiles = []
    ocean_tiles = []
    for tile in requested_tiles:
        if _is_land_tile(tile, coverage):
            land_tiles.append(tile)
        else:
            ocean_tiles.append(tile)

    resolved_land = ecosystem_safe_fallback(
        normalized_tiles=land_tiles,
        ecosystem=ecosystem,
        coverage=coverage,
        base_path=base_path,
    ) if land_tiles else []

    if land_tiles and not resolved_land:
        resolved_land = list(land_tiles)

    resolved_ocean = []
    if resolved_land:
        for tile in ocean_tiles:
            if any(_tiles_overlap(tile, land_tile) for land_tile in resolved_land):
                continue
            resolved_ocean.append(tile)
    else:
        resolved_ocean = list(ocean_tiles)

    resolved_tiles = list(resolved_land) + list(resolved_ocean)
    if not resolved_tiles:
        resolved_tiles = list(requested_tiles)

    resolved_tiles = sorted(set(resolved_tiles), key=_tile_sort_key)
    ocean_tile_set = set(resolved_ocean).intersection(resolved_tiles)
    return resolved_tiles, ocean_tile_set


def resolve_tiles_for_shader(visible_tiles, base_path):
    return _resolve_tiles_for_shader(visible_tiles, base_path)


def _build_rgba_add_chain(nodes, links, sockets, *, x_start=200.0, y=0.0, x_step=220.0):
    if not sockets:
        return None
    if len(sockets) == 1:
        return sockets[0]

    # Build a balanced binary ADD tree instead of a linear chain.
    # This reduces shader stack depth in Cycles for larger tile counts.
    current_level = list(sockets)
    level_index = 0
    while len(current_level) > 1:
        next_level = []
        pair_count = len(current_level) // 2
        for pair_idx in range(pair_count):
            source_a = current_level[pair_idx * 2]
            source_b = current_level[pair_idx * 2 + 1]
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "ADD"
            mix.inputs[0].default_value = 1.0  # Factor
            if hasattr(mix, "clamp_factor"):
                mix.clamp_factor = True
            _set_node_location_safe(
                mix,
                x_start + float(level_index) * float(x_step),
                y - float(pair_idx) * 46.0,
            )
            links.new(source_a, mix.inputs[6])  # A (RGBA)
            links.new(source_b, mix.inputs[7])  # B (RGBA)
            next_level.append(mix.outputs[2])   # Result (RGBA)
        if len(current_level) % 2 == 1:
            next_level.append(current_level[-1])
        current_level = next_level
        level_index += 1
    return current_level[0]


def _build_scalar_add_chain(nodes, links, sockets, *, x_start=200.0, y=0.0, x_step=220.0):
    if not sockets:
        return None
    if len(sockets) == 1:
        return sockets[0]

    # Balanced binary ADD tree to keep scalar merge depth low.
    current_level = list(sockets)
    level_index = 0
    while len(current_level) > 1:
        next_level = []
        pair_count = len(current_level) // 2
        for pair_idx in range(pair_count):
            source_a = current_level[pair_idx * 2]
            source_b = current_level[pair_idx * 2 + 1]
            math = nodes.new("ShaderNodeMath")
            math.operation = "ADD"
            _set_node_location_safe(
                math,
                x_start + float(level_index) * float(x_step),
                y - float(pair_idx) * 42.0,
            )
            links.new(source_a, math.inputs[0])
            links.new(source_b, math.inputs[1])
            next_level.append(math.outputs[0])
        if len(current_level) % 2 == 1:
            next_level.append(current_level[-1])
        current_level = next_level
        level_index += 1
    return current_level[0]


def _ensure_dynamic_texture_loading_slots(group_tree, slot_count, allow_shrink=True):
    if _is_testing_texture_loading_group(group_tree) or _is_animation_segment_group(group_tree):
        return _ensure_dynamic_texture_loading_slots_testing(group_tree, slot_count, allow_shrink=allow_shrink)

    slot_count = max(1, int(slot_count))
    existing_tiles = _sorted_tile_group_nodes(group_tree)
    if not allow_shrink and len(existing_tiles) >= slot_count:
        slot_count = len(existing_tiles)

    nodes = group_tree.nodes
    links = group_tree.links

    output_node = next((node for node in nodes if node.type == "GROUP_OUTPUT"), None)
    if output_node is None:
        raise RuntimeError("Planetka: texture loading group output node is missing.")

    for node in list(nodes):
        if node == output_node:
            continue
        if node.type == "GROUP" and node.name.startswith(TILE_GROUP_NODE_PREFIXES):
            nodes.remove(node)
            continue
        if node.type == "GROUP" and node.name.startswith(TILE_MASK_NODE_PREFIX):
            nodes.remove(node)
            continue
        if node.bl_idname in {"ShaderNodeMix", "ShaderNodeMixRGB", "ShaderNodeMath", "ShaderNodeVectorMath"}:
            nodes.remove(node)

    tile_nodes = []
    tile_node_groups = [
        _ensure_tile_group_for_index(index, variant="regular")
        for index in range(1, slot_count + 1)
    ]
    for tile_group in tile_node_groups:
        _stabilize_tile_group_mask_sources(tile_group, enable_z360=False)

    y_start = 420.0
    y_step = 520.0
    for index, tile_group in enumerate(tile_node_groups, start=1):
        tile_node = nodes.new("ShaderNodeGroup")
        tile_node.name = f"Tile_{index:03d}"
        tile_node.label = tile_node.name
        tile_node.node_tree = tile_group
        tile_node.location = (-520.0, y_start - (index - 1) * y_step)
        tile_node.inputs[0].default_value = 0
        tile_node.inputs[1].default_value = 0
        tile_node.inputs[2].default_value = 1
        tile_node.inputs[3].default_value = 1
        tile_nodes.append(tile_node)

    chain_x_start = 200.0
    chain_x_step = 240.0
    chain_tail_x = chain_x_start + float(max(0, len(tile_nodes) - 2)) * chain_x_step
    post_x_1 = chain_tail_x + 300.0
    post_x_2 = post_x_1 + 260.0
    post_x_3 = post_x_2 + 260.0
    output_x = post_x_3 + 360.0
    _set_node_location_safe(output_node, output_x, -220.0)

    # Cosmetic node layout lanes (for readability in Shader Editor).
    lane_y = {}
    base_y = 300.0
    lane_step = 240.0
    for idx, channel in enumerate(TEXTURE_LOADING_CHANNELS_RGBA, start=0):
        lane_y[channel] = base_y - float(idx) * lane_step
    lane_y["Alpha"] = base_y - float(len(TEXTURE_LOADING_CHANNELS_RGBA)) * lane_step
    lane_y["EL"] = lane_y["Alpha"] - lane_step

    alpha_sockets = [node.outputs["Alpha"] for node in tile_nodes]
    el_sockets = [node.outputs["EL"] for node in tile_nodes]
    scalar_results = {}

    rgba_weighted_sockets = {channel: [] for channel in TEXTURE_LOADING_CHANNELS_RGBA}
    rgba_weight_y_offset = {"S2": 120.0, "WT": 0.0, "SE": -120.0}
    for idx, tile_node in enumerate(tile_nodes, start=1):
        alpha_socket = alpha_sockets[idx - 1]
        try:
            tile_y = float(tile_node.location[1])
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError):
            tile_y = 0.0
        for channel in TEXTURE_LOADING_CHANNELS_RGBA:
            color_socket = tile_node.outputs[channel]
            color_weight = nodes.new("ShaderNodeVectorMath")
            color_weight.operation = "SCALE"
            _set_node_location_safe(
                color_weight,
                chain_x_start - 280.0,
                tile_y + float(rgba_weight_y_offset.get(channel, 0.0)),
            )
            links.new(color_socket, color_weight.inputs[0])
            links.new(alpha_socket, color_weight.inputs[3])
            rgba_weighted_sockets[channel].append(color_weight.outputs[0])

    rgba_results = {}
    for channel in TEXTURE_LOADING_CHANNELS_RGBA:
        rgba_results[channel] = _build_rgba_add_chain(
            nodes,
            links,
            rgba_weighted_sockets.get(channel, []),
            x_start=chain_x_start,
            y=lane_y.get(channel, 0.0),
            x_step=chain_x_step,
        )

    scalar_results["Alpha"] = _build_scalar_add_chain(
        nodes,
        links,
        alpha_sockets,
        x_start=chain_x_start,
        y=lane_y.get("Alpha", -200.0),
        x_step=chain_x_step,
    )

    weighted_el_sockets = []
    for idx, (el_socket, alpha_socket) in enumerate(zip(el_sockets, alpha_sockets), start=1):
        el_weight = nodes.new("ShaderNodeMath")
        el_weight.operation = "MULTIPLY"
        try:
            tile_y = float(tile_nodes[idx - 1].location[1])
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError):
            tile_y = 0.0
        _set_node_location_safe(el_weight, chain_x_start - 360.0, tile_y - 220.0)
        links.new(el_socket, el_weight.inputs[0])
        links.new(alpha_socket, el_weight.inputs[1])
        weighted_el_sockets.append(el_weight.outputs[0])
    scalar_results["EL"] = _build_scalar_add_chain(
        nodes,
        links,
        weighted_el_sockets,
        x_start=chain_x_start,
        y=lane_y.get("EL", -500.0),
        x_step=chain_x_step,
    )

    alpha_raw_socket = scalar_results.get("Alpha")
    alpha_den_socket = None
    if alpha_raw_socket is not None:
        alpha_max = nodes.new("ShaderNodeMath")
        alpha_max.operation = "MAXIMUM"
        alpha_max.inputs[1].default_value = 0.0
        _set_node_location_safe(alpha_max, post_x_1, lane_y.get("Alpha", -200.0) + 60.0)
        links.new(alpha_raw_socket, alpha_max.inputs[0])

        alpha_clamp = nodes.new("ShaderNodeMath")
        alpha_clamp.operation = "MINIMUM"
        alpha_clamp.inputs[1].default_value = 1.0
        _set_node_location_safe(alpha_clamp, post_x_2, lane_y.get("Alpha", -200.0) + 60.0)
        links.new(alpha_max.outputs[0], alpha_clamp.inputs[0])
        scalar_results["Alpha"] = alpha_clamp.outputs[0]

        alpha_den = nodes.new("ShaderNodeMath")
        alpha_den.operation = "MAXIMUM"
        alpha_den.inputs[1].default_value = 1.0
        _set_node_location_safe(alpha_den, post_x_1, lane_y.get("Alpha", -200.0) - 40.0)
        links.new(alpha_raw_socket, alpha_den.inputs[0])
        alpha_den_socket = alpha_den.outputs[0]

        inv_alpha_den = nodes.new("ShaderNodeMath")
        inv_alpha_den.operation = "DIVIDE"
        inv_alpha_den.inputs[0].default_value = 1.0
        _set_node_location_safe(inv_alpha_den, post_x_2, lane_y.get("Alpha", -200.0) - 40.0)
        links.new(alpha_den_socket, inv_alpha_den.inputs[1])

        for channel, result_socket in list(rgba_results.items()):
            if result_socket is None:
                continue
            color_scale = nodes.new("ShaderNodeVectorMath")
            color_scale.operation = "SCALE"
            _set_node_location_safe(color_scale, post_x_3, lane_y.get(channel, 0.0))
            links.new(result_socket, color_scale.inputs[0])
            links.new(inv_alpha_den.outputs[0], color_scale.inputs[3])
            rgba_results[channel] = color_scale.outputs[0]

    el_socket = scalar_results.get("EL")
    if el_socket is not None and alpha_raw_socket is not None:
        # Prevent EL amplification when alpha dips along tile edges.
        # We only normalize overlaps above 1.0; below that we keep raw weighted EL.
        el_norm = nodes.new("ShaderNodeMath")
        el_norm.operation = "DIVIDE"
        _set_node_location_safe(el_norm, post_x_3, lane_y.get("EL", -500.0))
        links.new(el_socket, el_norm.inputs[0])
        if alpha_den_socket is not None:
            links.new(alpha_den_socket, el_norm.inputs[1])
        else:
            el_norm.inputs[1].default_value = 1.0
        scalar_results["EL"] = el_norm.outputs[0]

    output_socket_map = {socket.name: socket for socket in output_node.inputs}
    for channel, result_socket in rgba_results.items():
        out_socket = output_socket_map.get(channel)
        if out_socket and result_socket:
            links.new(result_socket, out_socket)
    for channel, result_socket in scalar_results.items():
        out_socket = output_socket_map.get(channel)
        if out_socket and result_socket:
            links.new(result_socket, out_socket)

    _hide_unconnected_group_input_sockets(group_tree)
    return _sorted_tile_group_nodes(group_tree)


def _ensure_dynamic_texture_loading_slots_testing(group_tree, slot_count, allow_shrink=True):
    del allow_shrink
    slot_count = max(1, int(slot_count))
    static_slot_count = max(1, int(TESTING_STATIC_SLOT_COUNT))

    nodes = group_tree.nodes
    links = group_tree.links
    output_node = next((node for node in nodes if node.type == "GROUP_OUTPUT"), None)
    if output_node is None:
        raise RuntimeError("Planetka: texture loading group output node is missing.")

    try:
        existing_schema = int(group_tree.get(TESTING_LOADER_SCHEMA_VERSION_KEY, 0) or 0)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        existing_schema = 0

    def _collect_existing_tile_nodes():
        collected = []
        for index in range(1, static_slot_count + 1):
            node = nodes.get(f"Tile_{index:03d}")
            if node is None or str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                return []
            active_node = nodes.get(f"TileActive_{index:03d}")
            if active_node is None or str(getattr(active_node, "bl_idname", "")) != "ShaderNodeValue":
                return []
            collected.append(node)
        return collected

    tile_nodes = _collect_existing_tile_nodes()
    if (
        tile_nodes
        and int(len(tile_nodes)) == int(static_slot_count)
        and int(existing_schema) >= int(TESTING_LOADER_SCHEMA_VERSION)
    ):
        return tile_nodes

    # Rebuild generated testing graph only when schema is missing/outdated.
    for node in list(nodes):
        if node == output_node:
            continue
        nodes.remove(node)
    for link in list(links):
        links.remove(link)

    placement_group = _ensure_tile_placement_group(variant="regular")

    tile_nodes = []
    alpha_sockets = []
    el_sockets = []
    rgba_weighted_sockets = {channel: [] for channel in TEXTURE_LOADING_CHANNELS_RGBA}

    y_start = 420.0
    y_step = 520.0
    chain_x_start = 200.0
    chain_x_step = 240.0

    for index in range(1, static_slot_count + 1):
        tile_y = y_start - float(index - 1) * y_step

        placement_node = nodes.new("ShaderNodeGroup")
        placement_node.name = f"Tile_{index:03d}"
        placement_node.label = placement_node.name
        placement_node.node_tree = placement_group
        placement_node.location = (-980.0, tile_y)
        placement_node.inputs[0].default_value = 0
        placement_node.inputs[1].default_value = 0
        placement_node.inputs[2].default_value = 1
        placement_node.inputs[3].default_value = 1
        tile_nodes.append(placement_node)
        alpha_socket = placement_node.outputs.get("Alpha")
        vector_socket = placement_node.outputs.get("S2")
        if vector_socket is None:
            outputs = list(getattr(placement_node, "outputs", ()))
            if outputs:
                vector_socket = outputs[0]
        if alpha_socket is None:
            outputs = list(getattr(placement_node, "outputs", ()))
            if len(outputs) > 3:
                alpha_socket = outputs[3]

        active_node = nodes.new("ShaderNodeValue")
        active_node.name = f"TileActive_{index:03d}"
        active_node.label = active_node.name
        _set_node_location_safe(active_node, -1260.0, tile_y + 260.0)
        try:
            active_node.outputs[0].default_value = 0.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            pass

        alpha_effective = nodes.new("ShaderNodeMath")
        alpha_effective.operation = "MULTIPLY"
        alpha_effective.name = f"TileAlpha_{index:03d}"
        _set_node_location_safe(alpha_effective, -760.0, tile_y + 260.0)
        if alpha_socket is not None:
            links.new(alpha_socket, alpha_effective.inputs[0])
        else:
            alpha_effective.inputs[0].default_value = 0.0
        links.new(active_node.outputs[0], alpha_effective.inputs[1])
        alpha_sockets.append(alpha_effective.outputs[0])

        # Direct per-tile image samplers in testing loading group.
        image_nodes = {}
        image_y_offset = {"S2": 180.0, "EL": 40.0, "WT": -100.0, "PO": -240.0}
        for img_type in TEXTURE_TYPES:
            img_node = nodes.new("ShaderNodeTexImage")
            img_node.name = f"{TEST_TILE_IMAGE_NODE_PREFIX}{index:03d}_{img_type}"
            img_node.label = img_node.name
            _set_node_location_safe(
                img_node,
                -620.0,
                tile_y + float(image_y_offset.get(img_type, 0.0)),
            )
            if vector_socket is not None:
                links.new(vector_socket, img_node.inputs["Vector"])
            image_nodes[img_type] = img_node

        # EL is scalar from red channel.
        el_sep = nodes.new("ShaderNodeSeparateColor")
        el_sep.name = f"TileSep_{index:03d}_EL"
        el_sep.label = el_sep.name
        _set_node_location_safe(el_sep, -360.0, tile_y + 40.0)
        links.new(image_nodes["EL"].outputs["Color"], el_sep.inputs["Color"])
        el_scalar = el_sep.outputs["Red"]
        el_sockets.append(el_scalar)

        # RGBA vector channels.
        channel_sources = {
            "S2": image_nodes["S2"].outputs["Color"],
            "WT": image_nodes["WT"].outputs["Color"],
            "SE": image_nodes["PO"].outputs["Color"],
        }
        rgba_weight_y_offset = {"S2": 120.0, "WT": 0.0, "SE": -120.0}
        for channel, source_socket in channel_sources.items():
            color_weight = nodes.new("ShaderNodeVectorMath")
            color_weight.operation = "SCALE"
            _set_node_location_safe(
                color_weight,
                chain_x_start - 280.0,
                tile_y + float(rgba_weight_y_offset.get(channel, 0.0)),
            )
            links.new(source_socket, color_weight.inputs[0])
            if alpha_socket is not None:
                links.new(alpha_socket, color_weight.inputs[3])
            else:
                color_weight.inputs[3].default_value = 0.0
            rgba_weighted_sockets[channel].append(color_weight.outputs[0])

    # Cosmetic node layout lanes (for readability in Shader Editor).
    lane_y = {}
    base_y = 300.0
    lane_step = 240.0
    for idx, channel in enumerate(TEXTURE_LOADING_CHANNELS_RGBA, start=0):
        lane_y[channel] = base_y - float(idx) * lane_step
    lane_y["Alpha"] = base_y - float(len(TEXTURE_LOADING_CHANNELS_RGBA)) * lane_step
    lane_y["EL"] = lane_y["Alpha"] - lane_step

    rgba_results = {}
    for channel in TEXTURE_LOADING_CHANNELS_RGBA:
        rgba_results[channel] = _build_rgba_add_chain(
            nodes,
            links,
            rgba_weighted_sockets.get(channel, []),
            x_start=chain_x_start,
            y=lane_y.get(channel, 0.0),
            x_step=chain_x_step,
        )

    scalar_results = {}
    scalar_results["Alpha"] = _build_scalar_add_chain(
        nodes,
        links,
        [sock for sock in alpha_sockets if sock is not None],
        x_start=chain_x_start,
        y=lane_y.get("Alpha", -200.0),
        x_step=chain_x_step,
    )

    weighted_el_sockets = []
    for idx, (el_socket, alpha_socket) in enumerate(zip(el_sockets, alpha_sockets), start=1):
        if el_socket is None:
            continue
        el_weight = nodes.new("ShaderNodeMath")
        el_weight.operation = "MULTIPLY"
        try:
            tile_y = float(tile_nodes[idx - 1].location[1])
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, IndexError):
            tile_y = 0.0
        _set_node_location_safe(el_weight, chain_x_start - 360.0, tile_y - 220.0)
        links.new(el_socket, el_weight.inputs[0])
        if alpha_socket is not None:
            links.new(alpha_socket, el_weight.inputs[1])
        else:
            el_weight.inputs[1].default_value = 0.0
        weighted_el_sockets.append(el_weight.outputs[0])
    scalar_results["EL"] = _build_scalar_add_chain(
        nodes,
        links,
        weighted_el_sockets,
        x_start=chain_x_start,
        y=lane_y.get("EL", -500.0),
        x_step=chain_x_step,
    )

    chain_tail_x = chain_x_start + float(max(0, len(tile_nodes) - 2)) * chain_x_step
    post_x_1 = chain_tail_x + 300.0
    post_x_2 = post_x_1 + 260.0
    post_x_3 = post_x_2 + 260.0
    output_x = post_x_3 + 360.0
    _set_node_location_safe(output_node, output_x, -220.0)

    alpha_raw_socket = scalar_results.get("Alpha")
    alpha_den_socket = None
    if alpha_raw_socket is not None:
        alpha_max = nodes.new("ShaderNodeMath")
        alpha_max.operation = "MAXIMUM"
        alpha_max.inputs[1].default_value = 0.0
        _set_node_location_safe(alpha_max, post_x_1, lane_y.get("Alpha", -200.0) + 60.0)
        links.new(alpha_raw_socket, alpha_max.inputs[0])

        alpha_clamp = nodes.new("ShaderNodeMath")
        alpha_clamp.operation = "MINIMUM"
        alpha_clamp.inputs[1].default_value = 1.0
        _set_node_location_safe(alpha_clamp, post_x_2, lane_y.get("Alpha", -200.0) + 60.0)
        links.new(alpha_max.outputs[0], alpha_clamp.inputs[0])
        scalar_results["Alpha"] = alpha_clamp.outputs[0]

        alpha_den = nodes.new("ShaderNodeMath")
        alpha_den.operation = "MAXIMUM"
        alpha_den.inputs[1].default_value = 1.0
        _set_node_location_safe(alpha_den, post_x_1, lane_y.get("Alpha", -200.0) - 40.0)
        links.new(alpha_raw_socket, alpha_den.inputs[0])
        alpha_den_socket = alpha_den.outputs[0]

        inv_alpha_den = nodes.new("ShaderNodeMath")
        inv_alpha_den.operation = "DIVIDE"
        inv_alpha_den.inputs[0].default_value = 1.0
        _set_node_location_safe(inv_alpha_den, post_x_2, lane_y.get("Alpha", -200.0) - 40.0)
        links.new(alpha_den_socket, inv_alpha_den.inputs[1])

        for channel, result_socket in list(rgba_results.items()):
            if result_socket is None:
                continue
            color_scale = nodes.new("ShaderNodeVectorMath")
            color_scale.operation = "SCALE"
            _set_node_location_safe(color_scale, post_x_3, lane_y.get(channel, 0.0))
            links.new(result_socket, color_scale.inputs[0])
            links.new(inv_alpha_den.outputs[0], color_scale.inputs[3])
            rgba_results[channel] = color_scale.outputs[0]

    el_socket = scalar_results.get("EL")
    if el_socket is not None and alpha_raw_socket is not None:
        el_norm = nodes.new("ShaderNodeMath")
        el_norm.operation = "DIVIDE"
        _set_node_location_safe(el_norm, post_x_3, lane_y.get("EL", -500.0))
        links.new(el_socket, el_norm.inputs[0])
        if alpha_den_socket is not None:
            links.new(alpha_den_socket, el_norm.inputs[1])
        else:
            el_norm.inputs[1].default_value = 1.0
        scalar_results["EL"] = el_norm.outputs[0]

    output_socket_map = {socket.name: socket for socket in output_node.inputs}
    for channel, result_socket in rgba_results.items():
        out_socket = output_socket_map.get(channel)
        if out_socket and result_socket:
            links.new(result_socket, out_socket)
    for channel, result_socket in scalar_results.items():
        out_socket = output_socket_map.get(channel)
        if out_socket and result_socket:
            links.new(result_socket, out_socket)

    try:
        group_tree[TESTING_LOADER_SCHEMA_VERSION_KEY] = int(TESTING_LOADER_SCHEMA_VERSION)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-SHADER-043", "Failed writing testing loader schema version")

    _hide_unconnected_group_input_sockets(group_tree)
    return tile_nodes


# ------------------------------------------------------------
# Memory cleanup (extension-safe)
# ------------------------------------------------------------


def cleanup_planetka_images(force_remove_datablocks=False):
    removed = 0
    failed = 0
    candidates = 0

    for img in list(bpy.data.images):
        if img.users != 0:
            continue
        if not img.name.startswith(("S2_", "EL_", "WT_", "PO_")):
            continue

        candidates += 1

        try:
            bpy.data.images.remove(img)
            removed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            failed += 1
            logger.warning(
                "Planetka: failed removing unused image '%s'",
                img.name,
                exc_info=True,
            )

    if candidates > 0:
        logger.debug(
            "Planetka: surface image cleanup candidates=%d removed=%d failed=%d",
            candidates,
            removed,
            failed,
        )

    gc.collect()


# ------------------------------------------------------------
# Shader update (UNCHANGED CORE)
# ------------------------------------------------------------

def update_shader_nodes(
    visible_tiles,
    material_name="Planetka Earth Material",
    force_remove_datablocks=False,
    allow_slot_shrink=True,
    ocean_tiles=None,
    resolved_paths=None,
):
    stats = {
        "higher_z_fallback_count": 0,
        "missing_texture_count": 0,
        "loaded_texture_bytes": 0,
    }
    visible_tiles = list(visible_tiles or ())
    stats["applied_tiles"] = list(visible_tiles)
    seen_image_paths = set()

    material = bpy.data.materials.get(material_name)
    if not material or not material.node_tree:
        logger.error("Planetka: material %r missing or invalid", material_name)
        return stats
    _ensure_surface_grading_static_rgb_sources()

    nodes = material.node_tree.nodes
    group = nodes.get("Planetka Textures Loading")
    if not group:
        logger.error("Planetka: texture loading group missing in material %r", material_name)
        return stats
    source_group_tree = getattr(group, "node_tree", None)
    if source_group_tree is None:
        logger.error("Planetka: texture loading group tree missing in material %r", material_name)
        return stats
    if _is_animation_segment_group(source_group_tree):
        testing_group = source_group_tree
    else:
        testing_group = _ensure_testing_texture_loading_group(source_group_tree)
        if testing_group is not None and getattr(group, "node_tree", None) != testing_group:
            try:
                group.node_tree = testing_group
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed assigning testing texture loading group", exc_info=True)
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed assigning testing texture loading group", exc_info=True)
    active_group_tree = getattr(group, "node_tree", None)
    if active_group_tree is None:
        logger.error("Planetka: active texture loading group tree is unavailable in material %r", material_name)
        return stats

    testing_mode = bool(
        _is_testing_texture_loading_group(active_group_tree)
        or _is_animation_segment_group(active_group_tree)
    )

    try:
        tile_nodes = _ensure_dynamic_texture_loading_slots(
            active_group_tree,
            len(visible_tiles),
            allow_shrink=allow_slot_shrink,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.error("Planetka: failed to build dynamic tile slots: %s", exc)
        return stats
    if len(tile_nodes) < len(visible_tiles):
        logger.error(
            "Planetka: dynamic tile slot build returned %d slots for %d tiles",
            len(tile_nodes),
            len(visible_tiles),
        )
        return stats

    def _testing_img_node(slot_index, img_type):
        if not testing_mode:
            return None
        node_name = f"{TEST_TILE_IMAGE_NODE_PREFIX}{int(slot_index):03d}_{str(img_type)}"
        return active_group_tree.nodes.get(node_name)

    def _testing_active_node(slot_index):
        if not testing_mode:
            return None
        return active_group_tree.nodes.get(f"TileActive_{int(slot_index):03d}")

    def _set_testing_slot_active(slot_index, enabled):
        active_node = _testing_active_node(slot_index)
        if active_node is None:
            return
        try:
            active_node.outputs[0].default_value = 1.0 if bool(enabled) else 0.0
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError, IndexError):
            _log_recoverable_once("PKA-SHADER-044", "Failed setting testing slot active state")

    extension_dir = os.path.dirname(os.path.abspath(__file__))
    fallback_dir = os.path.join(extension_dir, "Resources", "Fallback Images")

    fallback_paths = {
        "S2": os.path.join(fallback_dir, "ocean_pixel_final_20.exr"),
        "EL": os.path.join(fallback_dir, "black_pixel_20.exr"),
        "WT": os.path.join(fallback_dir, "blue_pixel_20.exr"),
        "PO": os.path.join(fallback_dir, "black_pixel_20.exr"),
        "S2_WHITE": os.path.join(fallback_dir, "white_pixel_20.exr"),
        "EL_SOUTH": os.path.join(fallback_dir, "el_south_cap_pixel_20.exr"),
    }
    image_cache_by_path = {}
    fallback_images = {}
    for img_type, fallback_path in fallback_paths.items():
        fallback_images[img_type] = _load_image_cached(
            fallback_path,
            image_cache_by_path,
            image_name=os.path.basename(fallback_path),
        )

    for i, tile in enumerate(visible_tiles):
        node = tile_nodes[i]
        parsed = parse_tile(tile)
        if testing_mode:
            placement_variant = "regular"
            if parsed:
                try:
                    if int(parsed[2]) >= 360:
                        placement_variant = "z360"
                except (TypeError, ValueError, IndexError):
                    placement_variant = "regular"
            try:
                expected_group = _ensure_tile_placement_group(variant=placement_variant)
                if getattr(node, "node_tree", None) != expected_group:
                    node.node_tree = expected_group
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-SHADER-037", "Failed assigning testing placement group variant")
            except (RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-SHADER-038", "Failed assigning testing placement group variant")
        if not testing_mode:
            variant = "regular"
            if parsed:
                _, _, parsed_z, _ = parsed
                if int(parsed_z) >= 360:
                    variant = "z360"
            try:
                expected_group = _ensure_tile_group_for_index(i + 1, variant=variant)
                if getattr(node, "node_tree", None) != expected_group:
                    node.node_tree = expected_group
                _stabilize_tile_group_mask_sources(
                    getattr(node, "node_tree", None),
                    enable_z360=(variant == "z360"),
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-SHADER-017", "Failed stabilizing tile-group alpha mask sources")
            except (RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-SHADER-018", "Failed stabilizing tile-group alpha mask sources")

        if not parsed:
            node.mute = False
            _set_testing_slot_active(i + 1, False)
            tile_text = str(tile or "")
            is_placeholder = tile_text.startswith(PAD_TILE_PREFIX)
            node.label = "Placeholder" if is_placeholder else "Invalid"
            for img_type in TEXTURE_TYPES:
                img_node = _testing_img_node(i + 1, img_type) if testing_mode else node.node_tree.nodes.get(img_type)
                if not img_node:
                    continue
                fallback_img = fallback_images.get(img_type)
                if is_placeholder and img_type in {"S2", "WT"}:
                    # Placeholder slots must stay visually neutral.
                    fallback_img = fallback_images.get("EL") or fallback_img
                _assign_image_to_node(
                    img_node,
                    fallback_img,
                    img_type=img_type,
                    use_fallback=True,
                )
            continue
        x, y, z, d = parsed
        node.mute = False
        _set_testing_slot_active(i + 1, True)
        node.label = tile
        node.inputs[0].default_value = x
        node.inputs[1].default_value = y
        node.inputs[2].default_value = z
        node.inputs[3].default_value = d
        is_ocean_tile = bool(ocean_tiles and tile in ocean_tiles)
        pole_cap_kind = _pole_cap_kind(tile)

        def _cap_image_for(img_type):
            if pole_cap_kind == "north":
                if img_type == "S2":
                    return fallback_images.get("S2")
                if img_type == "EL":
                    return fallback_images.get("EL")
                if img_type == "WT":
                    return fallback_images.get("WT")
                return fallback_images.get("PO")
            if pole_cap_kind == "south":
                if img_type == "S2":
                    return fallback_images.get("S2_WHITE") or fallback_images.get("S2")
                if img_type == "EL":
                    return fallback_images.get("EL_SOUTH") or fallback_images.get("EL")
                if img_type == "WT":
                    return fallback_images.get("PO") or fallback_images.get("EL")
                return fallback_images.get("PO")
            return None

        for img_type in TEXTURE_TYPES:
            img_node = _testing_img_node(i + 1, img_type) if testing_mode else node.node_tree.nodes.get(img_type)
            if not img_node:
                continue

            if pole_cap_kind:
                img = _cap_image_for(img_type)
                _assign_image_to_node(
                    img_node,
                    img,
                    img_type=img_type,
                    use_fallback=True,
                )
                if img is not None:
                    raw_path = str(getattr(img, "filepath_raw", "") or getattr(img, "filepath", ""))
                    abs_path = bpy.path.abspath(raw_path) if raw_path else ""
                    if abs_path and abs_path not in seen_image_paths:
                        seen_image_paths.add(abs_path)
                        stats["loaded_texture_bytes"] += _image_file_size_bytes(img)
                continue

            if is_ocean_tile:
                img = fallback_images.get(img_type)
                _assign_image_to_node(
                    img_node,
                    img,
                    img_type=img_type,
                    use_fallback=True,
                )
                if img is not None:
                    raw_path = str(getattr(img, "filepath_raw", "") or getattr(img, "filepath", ""))
                    abs_path = bpy.path.abspath(raw_path) if raw_path else ""
                    if abs_path and abs_path not in seen_image_paths:
                        seen_image_paths.add(abs_path)
                        stats["loaded_texture_bytes"] += _image_file_size_bytes(img)
                continue

            filename = tile
            if img_type == "EL" and z == 1 and d == 2:
                filename = tile.replace("d002", "d001")

            path = ""
            prefetched_key = (tile, img_type)
            if isinstance(resolved_paths, dict) and prefetched_key in resolved_paths:
                path = str(resolved_paths.get(prefetched_key, "") or "")
            img_name = f"{img_type}_{filename}"
            # Resolve by filepath only. Reusing bpy.data.images.get(img_name)
            # can incorrectly keep stale datablocks from an old source folder.
            img = _load_image_cached(
                path,
                image_cache_by_path,
                image_name=img_name,
            )
            if img is None:
                img = fallback_images.get(img_type)
                stats["missing_texture_count"] += 1

            _assign_image_to_node(
                img_node,
                img,
                img_type=img_type,
                use_fallback=(img is fallback_images.get(img_type)),
            )
            if img is not None:
                raw_path = str(getattr(img, "filepath_raw", "") or getattr(img, "filepath", ""))
                abs_path = bpy.path.abspath(raw_path) if raw_path else ""
                if abs_path and abs_path not in seen_image_paths:
                    seen_image_paths.add(abs_path)
                    stats["loaded_texture_bytes"] += _image_file_size_bytes(img)

    for extra_index, node in enumerate(tile_nodes[len(visible_tiles):], start=len(visible_tiles) + 1):
        node.mute = False
        _set_testing_slot_active(extra_index, False)
        node.label = "Empty"
        for img_type in TEXTURE_TYPES:
            img_node = _testing_img_node(extra_index, img_type) if testing_mode else node.node_tree.nodes.get(img_type)
            if not img_node:
                continue
            extra_fallback = fallback_images.get(img_type)
            if testing_mode:
                # Keep static unused slots neutral-black across all channels.
                extra_fallback = fallback_images.get("EL") or extra_fallback
            _assign_image_to_node(
                img_node,
                extra_fallback,
                img_type=img_type,
                use_fallback=True,
            )

    # Offload unreferenced textures only after target assignments are in place.
    if force_remove_datablocks:
        try:
            bpy.context.view_layer.update()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: view layer update before surface hard-offload failed", exc_info=True)
    cleanup_planetka_images(force_remove_datablocks=force_remove_datablocks)

    return stats


# ------------------------------------------------------------
# Main entry
# ------------------------------------------------------------

def main(
    visible_tiles,
    material_name="Planetka Earth Material",
    force_remove_datablocks=False,
    allow_slot_shrink=True,
    resolved_paths=None,
    resolved_tiles_override=None,
    ocean_tiles_override=None,
):
    logger.debug("Planetka visible tiles: %s", visible_tiles)
    try:
        incoming_count = len(list(visible_tiles or ()))
        if incoming_count > int(SHADER_TILE_BUDGET_EXPECTED):
            logger.error(
                "Planetka: shader received %d tiles (expected <= %d). Upstream tile selection should enforce budget.",
                int(incoming_count),
                int(SHADER_TILE_BUDGET_EXPECTED),
            )
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, RuntimeError):
        logger.debug("Planetka: failed validating incoming tile budget", exc_info=True)
    prefs = get_prefs()
    base_path = prefs.texture_base_path
    logger.debug("Texture base path: %s", base_path)

    if resolved_tiles_override is None or ocean_tiles_override is None:
        resolved_tiles, ocean_tiles = _resolve_tiles_for_shader(visible_tiles, base_path)
    else:
        resolved_tiles = list(resolved_tiles_override or ())
        ocean_tiles = set(ocean_tiles_override or ())
    requested_tiles = list(visible_tiles)
    result = update_shader_nodes(
        resolved_tiles,
        material_name=material_name,
        force_remove_datablocks=force_remove_datablocks,
        allow_slot_shrink=allow_slot_shrink,
        ocean_tiles=ocean_tiles,
        resolved_paths=resolved_paths,
    )
    applied_tiles = list(result.get("applied_tiles", resolved_tiles))
    result["higher_z_fallback_count"] = len(set(applied_tiles) - set(requested_tiles))
    result["resolved_tiles"] = list(applied_tiles)
    result["resolved_tiles_full"] = list(resolved_tiles)
    result["requested_tiles"] = list(requested_tiles)
    cleanup_planetka_images(force_remove_datablocks=force_remove_datablocks)
    return result
