import bpy
import os
import gc
import importlib
import logging
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

from .extension_prefs import get_prefs
from .fallback_utils import ecosystem_safe_fallback

logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

POWER_Z = {1, 2, 4, 8, 16, 32, 64}
TEXTURE_TYPES = ("S2", "EL", "WT", "PO")
TEXTURE_EXTENSIONS = {
    "S2": (".exr",),
    "EL": (".exr",),
    "WT": (".exr",),
    "PO": (".tif",),
}
TILE_GROUP_NODE_PREFIXES = ("Planetka Tile_", "Tile_")
TILE_MASK_NODE_PREFIX = "TileMask_"
TEXTURE_LOADING_CHANNELS_RGBA = ("S2", "WT", "SE")
TEXTURE_LOADING_CHANNELS_SCALAR = ("EL", "Alpha")
_COVERAGE_MAP = None
BASE_EMBEDDED_TILE_GROUP_COUNT = 32


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

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
        if parse_tile(tile_str) is None:
            if not warned:
                logger.warning("Planetka: ignoring malformed tile id(s) in shader input")
                warned = True
            continue
        normalized.append(tile_str)
    return normalized


def _get_coverage_map():
    global _COVERAGE_MAP
    if _COVERAGE_MAP is None:
        module_name = f"{__package__}.coverage" if __package__ else "coverage"
        coverage_module = importlib.import_module(module_name)
        _COVERAGE_MAP = getattr(coverage_module, "COVERAGE", {})
    return _COVERAGE_MAP


def detect_ecosystem(tiles):
    for t in tiles:
        z = int(t.split("_")[2][1:])
        if z in POWER_Z:
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
            pass
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
        pass
    try:
        img_node.extension = "EXTEND"
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError, AttributeError):
        pass

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


def _get_tile_group_by_index(index):
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


def _ensure_tile_group_for_index(index):
    group = _get_tile_group_by_index(index)
    if group is not None:
        return group

    template = _get_tile_group_template()
    if template is None:
        raise RuntimeError("Planetka: no tile node group template is available.")

    new_group = template.copy()
    new_group.name = f"Planetka Tile_{int(index):03d}"
    try:
        new_group.use_fake_user = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    return new_group


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


def _stabilize_tile_group_mask_sources(tile_group):
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
                    pass
            separate = nodes.new("ShaderNodeSeparateXYZ")
            separate.name = "PKA AlphaMask Separate"
        _set_node_location_safe(separate, mapping_x + 220.0, mapping_y)

        x_gt = nodes.get("PKA AlphaMask XMin")
        if x_gt is None or x_gt.bl_idname != "ShaderNodeMath":
            if x_gt is not None:
                try:
                    nodes.remove(x_gt)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    pass
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
                    pass
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
                    pass
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
                    pass
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
                    pass
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
                    pass
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
                    pass
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
            if group_input is not None:
                z_input_socket = group_input.outputs.get("Z") or group_input.outputs.get("z")
                if z_input_socket is None:
                    group_outputs = list(getattr(group_input, "outputs", ()))
                    if len(group_outputs) > 2:
                        z_input_socket = group_outputs[2]

            if z_input_socket is not None and texture_nodes:
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
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass

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
            pass
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass

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

    current = sockets[0]
    for index, source in enumerate(sockets[1:], start=1):
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "ADD"
        mix.inputs[0].default_value = 1.0  # Factor
        if hasattr(mix, "clamp_factor"):
            mix.clamp_factor = True
        _set_node_location_safe(mix, x_start + float(index - 1) * float(x_step), y)
        links.new(current, mix.inputs[6])  # A (RGBA)
        links.new(source, mix.inputs[7])   # B (RGBA)
        current = mix.outputs[2]           # Result (RGBA)
    return current


def _build_scalar_add_chain(nodes, links, sockets, *, x_start=200.0, y=0.0, x_step=220.0):
    if not sockets:
        return None
    if len(sockets) == 1:
        return sockets[0]

    current = sockets[0]
    for index, source in enumerate(sockets[1:], start=1):
        math = nodes.new("ShaderNodeMath")
        math.operation = "ADD"
        _set_node_location_safe(math, x_start + float(index - 1) * float(x_step), y)
        links.new(current, math.inputs[0])
        links.new(source, math.inputs[1])
        current = math.outputs[0]
    return current


def _ensure_dynamic_texture_loading_slots(group_tree, slot_count, allow_shrink=True):
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
    tile_mask_nodes = []
    tile_node_groups = [_ensure_tile_group_for_index(index) for index in range(1, slot_count + 1)]
    for tile_group in tile_node_groups:
        _stabilize_tile_group_mask_sources(tile_group)

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

        # Hidden companion node: keeps per-tile alpha mask stable even if user mutes the visible tile node.
        mask_node = nodes.new("ShaderNodeGroup")
        mask_node.name = f"{TILE_MASK_NODE_PREFIX}{index:03d}"
        mask_node.label = mask_node.name
        mask_node.node_tree = tile_group
        mask_node.location = (-980.0, y_start - (index - 1) * y_step)
        mask_node.hide = True
        mask_node.mute = False
        mask_node.inputs[0].default_value = 0
        mask_node.inputs[1].default_value = 0
        mask_node.inputs[2].default_value = 1
        mask_node.inputs[3].default_value = 1
        tile_mask_nodes.append(mask_node)

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

    alpha_sockets = [node.outputs["Alpha"] for node in tile_mask_nodes]
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
    seen_image_paths = set()

    material = bpy.data.materials.get(material_name)
    if not material or not material.node_tree:
        logger.error("Planetka: material %r missing or invalid", material_name)
        return stats

    nodes = material.node_tree.nodes
    group = nodes.get("Planetka Textures Loading")
    if not group or not group.node_tree:
        logger.error("Planetka: texture loading group missing in material %r", material_name)
        return stats

    try:
        tile_nodes = _ensure_dynamic_texture_loading_slots(
            group.node_tree,
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

    # Ensure alpha mask stability on every update (not only when slot count changes).
    for tile_node in tile_nodes:
        try:
            _stabilize_tile_group_mask_sources(getattr(tile_node, "node_tree", None))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass

    extension_dir = os.path.dirname(os.path.abspath(__file__))
    fallback_dir = os.path.join(extension_dir, "Resources", "Fallback Images")

    fallback_paths = {
        "S2": os.path.join(fallback_dir, "ocean_pixel_final_20.exr"),
        "EL": os.path.join(fallback_dir, "black_pixel_20.exr"),
        "WT": os.path.join(fallback_dir, "blue_pixel_20.exr"),
        "PO": os.path.join(fallback_dir, "black_pixel_20.exr"),
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
        mask_node = group.node_tree.nodes.get(f"{TILE_MASK_NODE_PREFIX}{i + 1:03d}")
        parsed = parse_tile(tile)
        if not parsed:
            node.mute = True
            node.label = "Invalid"
            if mask_node is not None:
                mask_node.mute = True
            for img_type in TEXTURE_TYPES:
                img_node = node.node_tree.nodes.get(img_type)
                if not img_node:
                    continue
                _assign_image_to_node(
                    img_node,
                    fallback_images.get(img_type),
                    img_type=img_type,
                    use_fallback=True,
                )
            continue
        x, y, z, d = parsed
        node.mute = False
        node.label = tile
        node.inputs[0].default_value = x
        node.inputs[1].default_value = y
        node.inputs[2].default_value = z
        node.inputs[3].default_value = d
        if mask_node is not None:
            mask_node.mute = False
            mask_node.inputs[0].default_value = x
            mask_node.inputs[1].default_value = y
            mask_node.inputs[2].default_value = z
            mask_node.inputs[3].default_value = d
        is_ocean_tile = bool(ocean_tiles and tile in ocean_tiles)

        for img_type in TEXTURE_TYPES:
            img_node = node.node_tree.nodes.get(img_type)
            if not img_node:
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

    for index, node in enumerate(tile_nodes[len(visible_tiles):], start=len(visible_tiles) + 1):
        node.mute = True
        node.label = "Empty"
        mask_node = group.node_tree.nodes.get(f"{TILE_MASK_NODE_PREFIX}{index:03d}")
        if mask_node is not None:
            mask_node.mute = True
        for img_type in TEXTURE_TYPES:
            img_node = node.node_tree.nodes.get(img_type)
            if not img_node:
                continue
            _assign_image_to_node(
                img_node,
                fallback_images.get(img_type),
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
    result["higher_z_fallback_count"] = len(set(resolved_tiles) - set(requested_tiles))
    result["resolved_tiles"] = list(resolved_tiles)
    result["requested_tiles"] = list(requested_tiles)
    cleanup_planetka_images(force_remove_datablocks=force_remove_datablocks)
    return result
