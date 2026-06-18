import logging
import os

import bpy

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)

SURFACE_COLLECTION_NAME = "Planetka Earth Surface Collection"
PREVIEW_MATERIAL_NAME = "Planetka Preview Material"
EARTH_MATERIAL_NAME = "Planetka Earth Material"
SURFACE_GRADING_GROUP_NAME = "Planetka Surface Grading Group"
TEXTURE_LOADING_GROUP_NAME = "Planetka Textures Loading Group"
PREVIEW_TEXTURE_LOADING_GROUP_NAME = "Planetka Preview Textures Loading Group"
NIGHTDAY_GROUP_NAME = "Planetka NightDay Transition Group"
PLANETKA_ROOT_OBJECT_NAME = "Planetka Root"
SURFACE_MATERIAL_LIBRARY_SHA256 = "b500c019b92423ac8e72e9959e712d6307740f4e71f63dbe0b4293b0d94e59bb"
SURFACE_MATERIAL_LIBRARY_MATERIALS = (
    PREVIEW_MATERIAL_NAME,
    EARTH_MATERIAL_NAME,
)
SURFACE_MATERIAL_LIBRARY_NODE_GROUPS = (
    "Planetka Tile_01",
    "Planetka Tile Placement",
    "Planetka Tile Placement 360",
    TEXTURE_LOADING_GROUP_NAME,
    SURFACE_GRADING_GROUP_NAME,
    NIGHTDAY_GROUP_NAME,
)
_LIBRARY_SIGNATURE_KEY = "planetka_surface_material_library_sha256"
_SURFACE_MATERIAL_LIBRARY_RELATIVE_PATH = ("Resources", "planetka_surface_material_library.blend")

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

_SURFACE_GROUP_IMAGE_BINDINGS = (
    ("Image Texture", "ocean_pixel_final_20.exr"),
    ("Image Texture.001", "blue_pixel_20.exr"),
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
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _set_material_displacement_and_bump(material):
    if material is None:
        return False

    changed = False

    # Blender 5.x exposes displacement on the material; Blender 4.5 exposes it
    # through Cycles settings. Set whichever API is available.
    if hasattr(material, "displacement_method"):
        preferred_material = ("BOTH", "DISPLACEMENT_AND_BUMP", "DISPLACEMENT", "DISPLACEMENT_ONLY")
        available = set()
        try:
            prop_def = material.bl_rna.properties.get("displacement_method")
            if prop_def and hasattr(prop_def, "enum_items"):
                available = {item.identifier for item in prop_def.enum_items}
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            available = set()

        for identifier in preferred_material:
            if available and identifier not in available:
                continue
            try:
                current = str(getattr(material, "displacement_method", "") or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                current = ""
            if current == identifier:
                break
            try:
                material.displacement_method = identifier
                changed = True
                break
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue

    cycles_settings = getattr(material, "cycles", None)
    if cycles_settings is None or not hasattr(cycles_settings, "displacement_method"):
        return changed

    preferred_cycles = ("BOTH", "DISPLACEMENT_AND_BUMP", "DISPLACEMENT", "DISPLACEMENT_ONLY")
    available = set()
    try:
        prop_def = cycles_settings.bl_rna.properties.get("displacement_method")
        if prop_def and hasattr(prop_def, "enum_items"):
            available = {item.identifier for item in prop_def.enum_items}
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        available = set()

    for identifier in preferred_cycles:
        if available and identifier not in available:
            continue
        try:
            current = str(getattr(cycles_settings, "displacement_method", "") or "")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            current = ""
        if current == identifier:
            break
        try:
            cycles_settings.displacement_method = identifier
            changed = True
            break
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
    return changed


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
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue


def _surface_material_library_path():
    return os.path.join(os.path.dirname(__file__), *_SURFACE_MATERIAL_LIBRARY_RELATIVE_PATH)


def _append_material_library_from_blend(blend_path):
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        available_materials = set(data_from.materials)
        available_groups = set(data_from.node_groups)
        data_to.materials = [name for name in SURFACE_MATERIAL_LIBRARY_MATERIALS if name in available_materials]
        data_to.node_groups = [name for name in SURFACE_MATERIAL_LIBRARY_NODE_GROUPS if name in available_groups]


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


def ensure_surface_collection(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None
    root_collection = getattr(scene, "collection", None)
    if root_collection is None:
        return None
    return _ensure_collection(root_collection, SURFACE_COLLECTION_NAME)


def remove_planetka_root_object():
    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    if root is None:
        return False
    for child in tuple(getattr(root, "children", ()) or ()):
        try:
            matrix_world = child.matrix_world.copy()
            child.parent = None
            child.matrix_world = matrix_world
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka asset builder: failed unparenting object from Planetka Root", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka asset builder: failed unparenting object from Planetka Root", exc_info=True)
    try:
        bpy.data.objects.remove(root, do_unlink=True)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: failed removing Planetka Root", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: failed removing Planetka Root", exc_info=True)
    return False


def ensure_earth_surface_unparented(scene=None, earth_surface=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None or earth_surface is None:
        return earth_surface
    surface_collection = ensure_surface_collection(scene)

    try:
        if surface_collection is not None and earth_surface.name not in surface_collection.objects:
            surface_collection.objects.link(earth_surface)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)

    try:
        if getattr(earth_surface, "parent", None) is not None:
            matrix_world = earth_surface.matrix_world.copy()
            earth_surface.parent = None
            earth_surface.matrix_world = matrix_world
        earth_surface.matrix_parent_inverse.identity()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: failed clearing Earth Surface parent", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka asset builder: failed clearing Earth Surface parent", exc_info=True)

    remove_planetka_root_object()
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


def _set_library_signature(id_block):
    if not id_block:
        return
    try:
        id_block[_LIBRARY_SIGNATURE_KEY] = SURFACE_MATERIAL_LIBRARY_SHA256
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka asset builder: suppressed recoverable exception", exc_info=True)


def _has_library_signature(id_block):
    if not id_block:
        return False
    try:
        return id_block.get(_LIBRARY_SIGNATURE_KEY) == SURFACE_MATERIAL_LIBRARY_SHA256
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


def _sanitize_surface_material_library_assets():
    def _material_library_group_matches(name, base):
        text = str(name or "")
        return text == base or text.startswith(f"{base}.")

    for node_group in tuple(getattr(bpy.data, "node_groups", ())):
        group_name = str(getattr(node_group, "name", "") or "")
        if not any(_material_library_group_matches(group_name, base) for base in SURFACE_MATERIAL_LIBRARY_NODE_GROUPS):
            continue
        _clear_animation_data(node_group)
        for node in tuple(getattr(node_group, "nodes", ())):
            if str(getattr(node, "bl_idname", "")) == "ShaderNodeTexImage":
                try:
                    node.image = None
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka asset builder: failed clearing surface material library image node", exc_info=True)

    for material in tuple(getattr(bpy.data, "materials", ())):
        material_name = str(getattr(material, "name", "") or "")
        if not any(_material_library_group_matches(material_name, base) for base in SURFACE_MATERIAL_LIBRARY_MATERIALS):
            continue
        if not material or not material.node_tree:
            continue
        _clear_animation_data(material)
        _clear_animation_data(material.node_tree)
        for node in tuple(getattr(material.node_tree, "nodes", ())):
            if str(getattr(node, "bl_idname", "")) == "ShaderNodeTexImage":
                try:
                    node.image = None
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka asset builder: failed clearing surface material image node", exc_info=True)


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


def _is_surface_material_library_ready():
    for material_name in SURFACE_MATERIAL_LIBRARY_MATERIALS:
        material = bpy.data.materials.get(material_name)
        if not material or not _has_library_signature(material):
            return False
    for group_name in SURFACE_MATERIAL_LIBRARY_NODE_GROUPS:
        node_group = bpy.data.node_groups.get(group_name)
        if not node_group or not _has_library_signature(node_group):
            return False
    for node_group in getattr(bpy.data, "node_groups", ()):
        group_name = str(getattr(node_group, "name", ""))
        if group_name.startswith(f"{NIGHTDAY_GROUP_NAME}."):
            return False
    return True


def _load_surface_material_library():
    for material_name in SURFACE_MATERIAL_LIBRARY_MATERIALS:
        _remove_material_if_exists(material_name)
    for group_name in SURFACE_MATERIAL_LIBRARY_NODE_GROUPS:
        _remove_node_group_if_exists(group_name)
    for node_group in list(getattr(bpy.data, "node_groups", ())):
        group_name = str(getattr(node_group, "name", ""))
        if group_name.startswith(f"{NIGHTDAY_GROUP_NAME}."):
            _remove_node_group_if_exists(group_name)

    blend_path = _surface_material_library_path()
    if not os.path.isfile(blend_path):
        raise RuntimeError(f"Planetka: surface material library is missing: {blend_path}")
    _append_material_library_from_blend(blend_path)

    missing_materials = [name for name in SURFACE_MATERIAL_LIBRARY_MATERIALS if bpy.data.materials.get(name) is None]
    missing_groups = [name for name in SURFACE_MATERIAL_LIBRARY_NODE_GROUPS if bpy.data.node_groups.get(name) is None]
    if missing_materials or missing_groups:
        raise RuntimeError(
            "Planetka: surface material library failed to load "
            f"(materials missing: {missing_materials}, node groups missing: {missing_groups})"
        )

    for material_name in SURFACE_MATERIAL_LIBRARY_MATERIALS:
        material = bpy.data.materials.get(material_name)
        if material:
            material.use_fake_user = True
            _set_library_signature(material)

    for group_name in SURFACE_MATERIAL_LIBRARY_NODE_GROUPS:
        node_group = bpy.data.node_groups.get(group_name)
        if node_group:
            node_group.use_fake_user = True
            _set_library_signature(node_group)


def _ensure_surface_material_library(scene=None):
    if not _is_surface_material_library_ready():
        _load_surface_material_library()
    # Hard reset image-node bindings on every Create Earth asset ensure so
    # stale/missing cached paths from prior sessions cannot trigger GPU texture
    # creation errors before resolve or preview rebinding completes.
    _sanitize_surface_material_library_assets()
    _bind_static_images()

    earth_material = bpy.data.materials.get(EARTH_MATERIAL_NAME)
    if not earth_material:
        raise RuntimeError("Planetka: surface shader materials are missing after load.")
    _set_material_displacement_and_bump(earth_material)
    preview_material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)
    if preview_material is None:
        raise RuntimeError("Planetka: preview material is missing after loading reference shaders.")
    _set_material_displacement_and_bump(preview_material)
    _hide_unconnected_group_input_sockets_everywhere()
    return preview_material, earth_material
