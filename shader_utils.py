import bpy
import os
import importlib
import logging
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

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

POLE_CAP_Z_LEVELS = frozenset({1, 2, 4, 8})
PAD_TILE_PREFIX = "__PKA_PAD_TILE"
TEXTURE_TYPES = ("S2", "EL", "WT", "PO")
TEXTURE_LOADING_GROUP_NAME = "Planetka Textures Loading Group"
TILE_PLACEMENT_GROUP_NAME = "Planetka Tile Placement"
TILE_PLACEMENT_GROUP_360_NAME = "Planetka Tile Placement 360"
TEST_TILE_IMAGE_NODE_PREFIX = "TileImg_"
SHADER_TILE_BUDGET_EXPECTED = 12
_COVERAGE_MAP = None


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
    if parsed is None:
        return (10**9, 10**9, 10**9, 10**9, str(tile))
    x, y, z, d = parsed
    return (int(d), int(z), int(y), int(x), str(tile))


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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-SHADER-002", "Failed setting image node interpolation")
    try:
        img_node.extension = "EXTEND"
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
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


def _fixed_tile_nodes(group_tree):
    if group_tree is None or getattr(group_tree, "nodes", None) is None:
        raise RuntimeError("Planetka: texture loading node group is missing.")
    nodes = group_tree.nodes
    slots = []
    for index in range(1, int(SHADER_TILE_BUDGET_EXPECTED) + 1):
        tile_node = nodes.get(f"Tile_{index:03d}")
        active_node = nodes.get(f"TileActive_{index:03d}")
        if tile_node is None or str(getattr(tile_node, "bl_idname", "")) != "ShaderNodeGroup":
            raise RuntimeError(f"Planetka: fixed shader slot Tile_{index:03d} is missing.")
        if active_node is None or str(getattr(active_node, "bl_idname", "")) != "ShaderNodeValue":
            raise RuntimeError(f"Planetka: fixed shader slot TileActive_{index:03d} is missing.")
        for img_type in TEXTURE_TYPES:
            img_node = nodes.get(f"{TEST_TILE_IMAGE_NODE_PREFIX}{index:03d}_{img_type}")
            if img_node is None or str(getattr(img_node, "bl_idname", "")) != "ShaderNodeTexImage":
                raise RuntimeError(f"Planetka: fixed shader image node {TEST_TILE_IMAGE_NODE_PREFIX}{index:03d}_{img_type} is missing.")
        slots.append(tile_node)
    return slots


def _fixed_image_node(group_tree, slot_index, img_type):
    return group_tree.nodes.get(f"{TEST_TILE_IMAGE_NODE_PREFIX}{int(slot_index):03d}_{str(img_type)}")


def _fixed_active_node(group_tree, slot_index):
    return group_tree.nodes.get(f"TileActive_{int(slot_index):03d}")


def _fixed_placement_group(variant):
    variant_text = str(variant or "regular").strip().lower()
    group_name = TILE_PLACEMENT_GROUP_360_NAME if variant_text == "z360" else TILE_PLACEMENT_GROUP_NAME
    group = bpy.data.node_groups.get(group_name)
    if group is None:
        raise RuntimeError(f"Planetka: required material-library node group '{group_name}' is missing.")
    return group

def _resolve_tiles_for_shader(visible_tiles):
    requested_tiles = _normalize_requested_tiles(visible_tiles)
    if not requested_tiles:
        return [], set()
    coverage = _get_coverage_map()

    land_tiles = []
    ocean_tiles = []
    for tile in requested_tiles:
        if _is_land_tile(tile, coverage):
            land_tiles.append(tile)
        else:
            ocean_tiles.append(tile)

    resolved_tiles = sorted(set(requested_tiles), key=_tile_sort_key)
    ocean_tile_set = set(ocean_tiles).intersection(resolved_tiles)
    return resolved_tiles, ocean_tile_set


def resolve_tiles_for_shader(visible_tiles):
    return _resolve_tiles_for_shader(visible_tiles)


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


# ------------------------------------------------------------
# Shader update (UNCHANGED CORE)
# ------------------------------------------------------------

def update_shader_nodes(
    visible_tiles,
    material_name="Planetka Earth Material",
    force_remove_datablocks=False,
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
    nodes = material.node_tree.nodes
    group = nodes.get("Planetka Textures Loading")
    if not group:
        logger.error("Planetka: texture loading group missing in material %r", material_name)
        return stats
    active_group_tree = getattr(group, "node_tree", None)
    if active_group_tree is None:
        logger.error("Planetka: texture loading group tree missing in material %r", material_name)
        return stats

    try:
        tile_nodes = _fixed_tile_nodes(active_group_tree)
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.error("Planetka: fixed material library is invalid: %s", exc)
        return stats
    if len(tile_nodes) < len(visible_tiles):
        logger.error(
            "Planetka: shader has %d fixed slots for %d requested tiles",
            len(tile_nodes),
            len(visible_tiles),
        )
        return stats

    def _set_slot_active(slot_index, enabled):
        active_node = _fixed_active_node(active_group_tree, slot_index)
        if active_node is None:
            return
        try:
            active_node.outputs[0].default_value = 1.0 if bool(enabled) else 0.0
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-044", "Failed setting shader slot active state")

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
        variant = "z360" if parsed and int(parsed[2]) >= 360 else "regular"
        try:
            expected_group = _fixed_placement_group(variant)
            if getattr(node, "node_tree", None) != expected_group:
                node.node_tree = expected_group
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-SHADER-037", "Failed assigning fixed placement group")
        except (RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-SHADER-038", "Failed assigning fixed placement group")

        if not parsed:
            node.mute = False
            _set_slot_active(i + 1, False)
            tile_text = str(tile or "")
            is_placeholder = tile_text.startswith(PAD_TILE_PREFIX)
            node.label = "Placeholder" if is_placeholder else "Invalid"
            for img_type in TEXTURE_TYPES:
                img_node = _fixed_image_node(active_group_tree, i + 1, img_type)
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
        _set_slot_active(i + 1, True)
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
            img_node = _fixed_image_node(active_group_tree, i + 1, img_type)
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
            # Resolve by filepath only so Blender cannot reuse an image datablock
            # whose filepath no longer matches the requested texture.
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
        _set_slot_active(extra_index, False)
        node.label = "Empty"
        for img_type in TEXTURE_TYPES:
            img_node = _fixed_image_node(active_group_tree, extra_index, img_type)
            if not img_node:
                continue
            extra_fallback = fallback_images.get(img_type)
            # Keep unused fixed slots neutral-black across all channels.
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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed validating incoming tile budget", exc_info=True)
    if resolved_tiles_override is None or ocean_tiles_override is None:
        raise RuntimeError("Planetka shader requires upstream resolved tile classification.")
    resolved_tiles = list(resolved_tiles_override or ())
    ocean_tiles = set(ocean_tiles_override or ())
    requested_tiles = list(visible_tiles)
    result = update_shader_nodes(
        resolved_tiles,
        material_name=material_name,
        force_remove_datablocks=force_remove_datablocks,
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
