import importlib
import logging
import math
import os
import re

import bpy
import bpy.utils.previews
from bpy.props import EnumProperty, FloatProperty, StringProperty
from mathutils import Vector

from .asset_builder import ensure_planetka_root
from .auth import is_authenticated
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .r2_source import get_remote_cache_folder, resolve_remote_asset


logger = logging.getLogger(__name__)
_RECOVERABLE_LOG_COUNTS = {}


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1

COMMERCIAL_REFERENCE_BLEND_PATH = os.path.abspath(
    os.getenv(
        "PLANETKA_CLOUDS_REFERENCE_BLEND_PATH",
        "/Volumes/SSDA/Projects/planetka_commercial/Planetka.blend",
    ),
)
GLOBAL_CLOUD_REFERENCE_BLEND_PATH = os.path.join(
    os.path.dirname(__file__),
    "Resources",
    "planetka_global_cloud_layer_min.blend",
)
REMOTE_GLOBAL_CLOUDS_FOLDER = "clouds/global"
REMOTE_GLOBAL_CLOUD_TEXTURE_FILE = "Planetka_Global_Clouds_16K.tif"
REMOTE_LOCAL_CLOUDS_FOLDER = "clouds/local"
REMOTE_VDB_CLOUDS_FOLDER = "clouds/vdb"
REMOTE_TEST_LOCAL_CLOUD_FILES = (
    "Planetka Cloud 005 4700x4400.exr",
    "Planetka Cloud 006 6300x6700.exr",
    "Planetka Cloud 012 7600x5500.exr",
)
REMOTE_TEST_VDB_CLOUD_FILES = (
    "cloud003_vox100_50.vdb",
    "cloud001_vox100_50.vdb",
    "cloud004_vox100_50.vdb",
)

CLOUDS_ROOT_COLLECTION_NAME = "Clouds"
GLOBAL_CLOUDS_COLLECTION_NAME = "Global Clouds"
LOCAL_CLOUDS_COLLECTION_NAME = "Local Clouds"
VDB_CLOUDS_COLLECTION_NAME = "VDB Clouds"

GLOBAL_CLOUD_LAYER_NAME = "Planetka Global Cloud Layer"
GLOBAL_CLOUD_MATERIAL_NAME = "Planetka Global Clouds Shader"
GLOBAL_CLOUD_IMAGE_NODE_NAME = "Global Clouds Texture"
GLOBAL_CLOUD_RELATIVE_SCALE = 1.00157
LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME = "Planetka Local Clouds Shader"
VDB_CLOUD_TEMPLATE_OBJECT_NAME = "Planetka Cloud VDB"
VDB_CLOUD_MATERIAL_TEMPLATE_NAME = "Planetka VDB Cloud Shader"

LOCAL_CLOUD_SHADER_GROUP_NAME = "Planetka Local Clouds Shader Group"
GLOBAL_CLOUD_SHADER_GROUP_NAME = "Planetka Global Clouds Shader Group"
CLOUD_PREVIEW_SWITCH_GROUP_NAME = "Cloud Preview Switch"
LOCAL_CLOUD_PREVIEW_VALUE_NODE_NAME = "Preview_On_Off"
LOCAL_CLOUD_PREVIEW_INPUT_NAMES = ("Preview_On_Off", "Preview On Off")

LOCAL_CLOUD_LON_NODE_NAMES = ("Target Longitude -90 (deg)", "Target Longitude (deg)")
LOCAL_CLOUD_LAT_NODE_NAMES = ("Target Latitude +90 (deg)", "Target Latitude (deg)")
LOCAL_CLOUD_SIZE_NODE_NAMES = ("Local Cloud Size (deg)", "Local Cloud Size")
LOCAL_CLOUD_ROT_NODE_NAMES = ("Local Cloud Rotation (deg)", "Local Cloud Rotation")

LOCAL_CLOUD_NUMBERED_PREFIX = "Local Cloud No "
VDB_CLOUD_NUMBERED_PREFIX = "VDB Cloud No "
LOCAL_CLOUD_CAP_MESH_PREFIX = "Planetka Local Cloud Cap Mesh"

CLOUD_ROLE_KEY = "planetka_cloud_role"
GLOBAL_CLOUD_ROLE = "global_cloud"
LOCAL_CLOUD_ROLE = "local_cloud"
VDB_CLOUD_ROLE = "vdb_cloud"
GLOBAL_CLOUD_TEMPLATE_ROLE = "global_cloud_template"
VDB_CLOUD_TEMPLATE_ROLE = "vdb_cloud_template"

LOCAL_CLOUD_PROP_LONGITUDE = "planetka_local_cloud_longitude"
LOCAL_CLOUD_PROP_LATITUDE = "planetka_local_cloud_latitude"
LOCAL_CLOUD_PROP_ALTITUDE_M = "planetka_local_cloud_altitude_m"
LOCAL_CLOUD_PROP_SIZE_COEF = "planetka_local_cloud_size_coef"
LOCAL_CLOUD_PROP_ROTATION_DEG = "planetka_local_cloud_rotation_deg"
LOCAL_CLOUD_PROP_THICKNESS_M = "planetka_local_cloud_thickness_m"
LOCAL_CLOUD_PROP_DENSITY = "planetka_local_cloud_density"
LOCAL_CLOUD_PROP_DENSITY_GAMMA = "planetka_local_cloud_density_gamma"
LOCAL_CLOUD_PROP_BASE_SCALE = "planetka_local_cloud_base_scale"
LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG = "planetka_local_cloud_cap_half_angle_deg"
LOCAL_CLOUD_OBJ_TEXTURE_PROP = "planetka_local_cloud_texture"

VDB_CLOUD_PROP_LONGITUDE = "planetka_vdb_cloud_longitude"
VDB_CLOUD_PROP_LATITUDE = "planetka_vdb_cloud_latitude"
VDB_CLOUD_PROP_ALTITUDE_M = "planetka_vdb_cloud_altitude_m"
VDB_CLOUD_PROP_SIZE_COEF = "planetka_vdb_cloud_size_coef"
VDB_CLOUD_PROP_ROTATION_DEG = "planetka_vdb_cloud_rotation_deg"
VDB_CLOUD_PROP_DENSITY = "planetka_vdb_cloud_density"
VDB_CLOUD_PROP_BASE_SCALE_X = "planetka_vdb_cloud_base_scale_x"
VDB_CLOUD_PROP_BASE_SCALE_Y = "planetka_vdb_cloud_base_scale_y"
VDB_CLOUD_PROP_BASE_SCALE_Z = "planetka_vdb_cloud_base_scale_z"
VDB_CLOUD_PROP_BASE_RADIUS = "planetka_vdb_cloud_base_radius"
VDB_CLOUD_OBJ_FILE_PROP = "planetka_vdb_cloud_file"
VDB_CLOUD_DENSITY_NODE_NAME = "VDB Density"
DEFAULT_CLOUD_ALTITUDE_M = 2000.0
LOCAL_CLOUD_BASE_HALF_ANGLE_DEG = 0.08
LOCAL_CLOUD_MIN_HALF_ANGLE_DEG = 0.01
LOCAL_CLOUD_MAX_HALF_ANGLE_DEG = 70.0
LOCAL_CLOUD_SIZE_REMOTE_SCALE = 0.01

_local_cloud_preview_collection = None
_local_cloud_preview_signature = None
_local_cloud_enum_items = []
_cloud_update_suspend_count = 0
_local_cloud_asset_paths = {}
_vdb_cloud_asset_paths = {}


def _is_cloud_updates_suspended():
    return _cloud_update_suspend_count > 0


def _begin_cloud_update_suspend():
    global _cloud_update_suspend_count
    _cloud_update_suspend_count += 1


def _end_cloud_update_suspend():
    global _cloud_update_suspend_count
    _cloud_update_suspend_count = max(0, _cloud_update_suspend_count - 1)


def _sync_scene_idprops(scene, prop_names=None):
    if scene is None:
        return
    module_name = f"{__package__}.state" if __package__ else "state"
    try:
        state_module = importlib.import_module(module_name)
    except ImportError:
        return
    sync_fn = getattr(state_module, "_sync_idprops_from_props", None)
    if callable(sync_fn):
        try:
            sync_fn(scene, prop_names=prop_names)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed syncing idprops", exc_info=True)


def _get_clouds_global_module():
    module_name = f"{__package__}.clouds_global" if __package__ else "clouds_global"
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


def _local_clouds_dir():
    return get_remote_cache_folder(REMOTE_LOCAL_CLOUDS_FOLDER)


def _vdb_clouds_dir():
    return get_remote_cache_folder(REMOTE_VDB_CLOUDS_FOLDER)


def _refresh_remote_local_cloud_assets(force=False):
    global _local_cloud_asset_paths

    if _local_cloud_asset_paths and not force:
        return dict(_local_cloud_asset_paths)

    resolved = {}
    cache_dir = _local_clouds_dir()
    for file_name in REMOTE_TEST_LOCAL_CLOUD_FILES:
        path = ""
        if cache_dir:
            candidate = os.path.join(cache_dir, file_name)
            if os.path.isfile(candidate):
                path = candidate
        if not path and force:
            try:
                path = resolve_remote_asset(REMOTE_LOCAL_CLOUDS_FOLDER, file_name)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed resolving local cloud texture asset", exc_info=True)
                path = ""
        if path and os.path.isfile(path):
            resolved[file_name] = path
    _local_cloud_asset_paths = resolved
    return dict(_local_cloud_asset_paths)


def _refresh_remote_vdb_cloud_assets(force=False):
    global _vdb_cloud_asset_paths

    if _vdb_cloud_asset_paths and not force:
        return dict(_vdb_cloud_asset_paths)

    resolved = {}
    cache_dir = _vdb_clouds_dir()
    for file_name in REMOTE_TEST_VDB_CLOUD_FILES:
        path = ""
        if cache_dir:
            candidate = os.path.join(cache_dir, file_name)
            if os.path.isfile(candidate):
                path = candidate
        if not path and force:
            try:
                path = resolve_remote_asset(REMOTE_VDB_CLOUDS_FOLDER, file_name)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed resolving VDB cloud asset", exc_info=True)
                path = ""
        if path and os.path.isfile(path):
            resolved[file_name] = path
    _vdb_cloud_asset_paths = resolved
    return dict(_vdb_cloud_asset_paths)


def _build_local_cloud_signature(asset_paths):
    if not asset_paths:
        return None
    entries = []
    for name, path in sorted(asset_paths.items()):
        try:
            mtime_ns = os.stat(path).st_mtime_ns
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            mtime_ns = 0
        entries.append((name, mtime_ns))
    return (
        os.path.normcase(os.path.normpath(_local_clouds_dir() or "")),
        tuple(entries),
    )


def _ensure_local_cloud_previews(force=False):
    global _local_cloud_preview_collection
    global _local_cloud_preview_signature
    global _local_cloud_enum_items

    asset_paths = _refresh_remote_local_cloud_assets(force=force)
    signature = _build_local_cloud_signature(asset_paths)

    if (
        not force
        and _local_cloud_preview_collection is not None
        and signature == _local_cloud_preview_signature
        and _local_cloud_enum_items
    ):
        return _local_cloud_enum_items

    if _local_cloud_preview_collection is None:
        _local_cloud_preview_collection = bpy.utils.previews.new()
    else:
        _local_cloud_preview_collection.clear()

    _local_cloud_enum_items = []
    _local_cloud_preview_signature = signature

    if not signature:
        return _local_cloud_enum_items

    _folder_key, file_entries = signature
    for idx, (filename, _mtime_ns) in enumerate(file_entries):
        path = asset_paths.get(filename, "")
        if not path:
            continue
        key = f"local_cloud_{filename}"
        try:
            thumb = _local_cloud_preview_collection.load(key, path, 'IMAGE')
            icon_id = thumb.icon_id
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            icon_id = 0
        label = os.path.splitext(filename)[0]
        _local_cloud_enum_items.append((filename, label, path, icon_id, idx))
    return _local_cloud_enum_items


def _local_cloud_texture_items(_self, _context):
    items = _ensure_local_cloud_previews()
    if items:
        return items
    return [("NONE", "No Local Cloud Textures Found", _local_clouds_dir(), 0, 0)]


def _free_local_cloud_previews():
    global _local_cloud_preview_collection
    global _local_cloud_preview_signature
    global _local_cloud_enum_items

    if _local_cloud_preview_collection is not None:
        try:
            bpy.utils.previews.remove(_local_cloud_preview_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-001", "Failed removing local cloud preview collection")
        _local_cloud_preview_collection = None
    _local_cloud_preview_signature = None
    _local_cloud_enum_items = []


def _find_layer_collection_recursive(layer_collection, target_name):
    if layer_collection is None:
        return None
    if str(getattr(getattr(layer_collection, "collection", None), "name", "")) == str(target_name):
        return layer_collection
    for child in getattr(layer_collection, "children", ()): 
        found = _find_layer_collection_recursive(child, target_name)
        if found is not None:
            return found
    return None


def _set_collection_enabled(scene, collection_name, enabled):
    collection = bpy.data.collections.get(collection_name)
    if collection is not None:
        hidden = not bool(enabled)
        try:
            collection.hide_viewport = hidden
            collection.hide_render = hidden
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating collection hide flags", exc_info=True)

    if scene is None:
        return

    for view_layer in getattr(scene, "view_layers", ()): 
        layer_collection = _find_layer_collection_recursive(getattr(view_layer, "layer_collection", None), collection_name)
        if layer_collection is None:
            continue
        try:
            layer_collection.exclude = not bool(enabled)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating collection exclusion", exc_info=True)


def _ensure_child_collection(parent_collection, name):
    if parent_collection is None:
        return None
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    try:
        if collection.name not in parent_collection.children:
            parent_collection.children.link(collection)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed linking collection", exc_info=True)
    return collection


def _ensure_cloud_collections(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    root = getattr(scene, "collection", None) if scene else None
    if root is None:
        return None, None, None, None

    clouds = _ensure_child_collection(root, CLOUDS_ROOT_COLLECTION_NAME)
    global_clouds = _ensure_child_collection(clouds, GLOBAL_CLOUDS_COLLECTION_NAME)
    local_clouds = _ensure_child_collection(clouds, LOCAL_CLOUDS_COLLECTION_NAME)
    vdb_clouds = _ensure_child_collection(clouds, VDB_CLOUDS_COLLECTION_NAME)
    return clouds, global_clouds, local_clouds, vdb_clouds


def _sync_cloud_collection_visibility(scene, props):
    _ensure_cloud_collections(scene)
    enable_global = bool(getattr(props, "enable_global_clouds", True)) if props else False
    enable_local = bool(getattr(props, "enable_local_clouds", False)) if props else False
    enable_vdb = bool(getattr(props, "enable_vdb_clouds", False)) if props else False

    _set_collection_enabled(scene, CLOUDS_ROOT_COLLECTION_NAME, enable_global or enable_local or enable_vdb)
    _set_collection_enabled(scene, GLOBAL_CLOUDS_COLLECTION_NAME, enable_global)
    _set_collection_enabled(scene, LOCAL_CLOUDS_COLLECTION_NAME, enable_local)
    _set_collection_enabled(scene, VDB_CLOUDS_COLLECTION_NAME, enable_vdb)


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
            logger.debug("Planetka clouds: failed unlinking object from collection", exc_info=True)

    for col in desired:
        try:
            if obj.name not in col.objects:
                col.objects.link(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed linking object to collection", exc_info=True)


def _is_cloud_cull_modifier(modifier):
    if modifier is None:
        return False

    name = str(getattr(modifier, "name", "") or "").lower()
    if any(token in name for token in ("cull", "frustum", "camera cull")):
        return True

    mod_type = str(getattr(modifier, "type", "") or "")
    if mod_type == "NODES":
        node_group = getattr(modifier, "node_group", None)
        group_name = str(getattr(node_group, "name", "") or "").lower()
        if any(token in group_name for token in ("cull", "frustum", "camera cull")):
            return True
    return False


def _remove_cloud_cull_modifiers(obj):
    if obj is None:
        return 0
    removed = 0
    modifiers = getattr(obj, "modifiers", None)
    if modifiers is None:
        return 0
    for modifier in list(modifiers):
        if not _is_cloud_cull_modifier(modifier):
            continue
        try:
            modifiers.remove(modifier)
            removed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed removing cloud cull modifier on '%s'", obj.name, exc_info=True)
    return removed


def _clear_drivers_on_id_data(id_data):
    if id_data is None:
        return
    anim = getattr(id_data, "animation_data", None)
    drivers = getattr(anim, "drivers", None) if anim else None
    if not drivers:
        return
    for fcurve in list(drivers):
        try:
            drivers.remove(fcurve)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed removing driver", exc_info=True)


def _clear_drivers_on_node_tree(node_tree, visited=None):
    if node_tree is None:
        return
    if visited is None:
        visited = set()
    try:
        ptr = int(node_tree.as_pointer())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        ptr = id(node_tree)
    if ptr in visited:
        return
    visited.add(ptr)

    _clear_drivers_on_id_data(node_tree)
    for node in getattr(node_tree, "nodes", ()): 
        child = getattr(node, "node_tree", None)
        if child is not None:
            _clear_drivers_on_node_tree(child, visited=visited)


def _clear_cloud_drivers(obj):
    if obj is None:
        return
    try:
        obj.animation_data_clear()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed clearing object animation data", exc_info=True)

    data_block = getattr(obj, "data", None)
    _clear_drivers_on_id_data(data_block)

    materials = []
    if data_block is not None and hasattr(data_block, "materials"):
        materials.extend(mat for mat in data_block.materials if mat)
    active = getattr(obj, "active_material", None)
    if active is not None:
        materials.append(active)

    seen = set()
    for mat in materials:
        if mat is None:
            continue
        try:
            key = int(mat.as_pointer())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            key = id(mat)
        if key in seen:
            continue
        seen.add(key)
        _clear_drivers_on_id_data(mat)
        _clear_drivers_on_node_tree(getattr(mat, "node_tree", None))


def _append_from_reference(object_names=(), material_names=(), blend_path=None):
    blend_path = os.path.abspath(blend_path or COMMERCIAL_REFERENCE_BLEND_PATH)
    if not os.path.isfile(blend_path):
        raise RuntimeError(f"Planetka clouds reference blend missing: {blend_path}")

    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        available_objects = set(data_from.objects)
        available_materials = set(data_from.materials)

        object_targets = [name for name in object_names if name in available_objects]
        material_targets = [name for name in material_names if name in available_materials]

        if object_names and not object_targets:
            raise RuntimeError(
                "Planetka clouds reference object missing: " + ", ".join(object_names)
            )
        if material_names and not material_targets:
            raise RuntimeError(
                "Planetka clouds reference material missing: " + ", ".join(material_names)
            )

        data_to.objects = object_targets
        data_to.materials = material_targets


def _is_local_cloud_object(obj):
    if obj is None or str(getattr(obj, "type", "")) != "MESH":
        return False
    try:
        if str(obj.get(CLOUD_ROLE_KEY, "")) == LOCAL_CLOUD_ROLE:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDL-002", "Failed reading local-cloud role custom property")
    if str(getattr(obj, "name", "")).startswith(LOCAL_CLOUD_NUMBERED_PREFIX):
        return True
    coll = bpy.data.collections.get(LOCAL_CLOUDS_COLLECTION_NAME)
    if coll is None:
        return False
    return any(member == obj for member in coll.all_objects)


def _is_vdb_cloud_object(obj):
    if obj is None:
        return False
    try:
        if str(obj.get(CLOUD_ROLE_KEY, "")) == VDB_CLOUD_ROLE:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDL-003", "Failed reading VDB-cloud role custom property")
    if str(getattr(obj, "name", "")).startswith(VDB_CLOUD_NUMBERED_PREFIX):
        return True
    coll = bpy.data.collections.get(VDB_CLOUDS_COLLECTION_NAME)
    if coll is None:
        return False
    return any(member == obj for member in coll.all_objects)


def _iter_local_cloud_objects():
    seen = set()
    coll = bpy.data.collections.get(LOCAL_CLOUDS_COLLECTION_NAME)
    if coll:
        for obj in coll.all_objects:
            if not _is_local_cloud_object(obj):
                continue
            ptr = int(obj.as_pointer())
            if ptr in seen:
                continue
            seen.add(ptr)
            yield obj
    for obj in getattr(bpy.data, "objects", ()): 
        if not _is_local_cloud_object(obj):
            continue
        ptr = int(obj.as_pointer())
        if ptr in seen:
            continue
        seen.add(ptr)
        yield obj


def _iter_vdb_cloud_objects():
    seen = set()
    coll = bpy.data.collections.get(VDB_CLOUDS_COLLECTION_NAME)
    if coll:
        for obj in coll.all_objects:
            if not _is_vdb_cloud_object(obj):
                continue
            ptr = int(obj.as_pointer())
            if ptr in seen:
                continue
            seen.add(ptr)
            yield obj
    for obj in getattr(bpy.data, "objects", ()): 
        if not _is_vdb_cloud_object(obj):
            continue
        ptr = int(obj.as_pointer())
        if ptr in seen:
            continue
        seen.add(ptr)
        yield obj


def _sort_cloud_objects_by_suffix(objects):
    number_re = re.compile(r"(\d+)$")

    def _sort_key(obj):
        name = str(getattr(obj, "name", "") or "")
        match = number_re.search(name)
        if match:
            try:
                return (0, int(match.group(1)), name)
            except (TypeError, ValueError):
                pass
        return (1, name)

    return sorted(objects, key=_sort_key)


def _next_local_cloud_name():
    pattern = re.compile(rf"^{re.escape(LOCAL_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$")
    max_num = 0
    for obj in getattr(bpy.data, "objects", ()): 
        match = pattern.match(str(getattr(obj, "name", "")))
        if match:
            try:
                max_num = max(max_num, int(match.group(1)))
            except (TypeError, ValueError):
                continue
    return f"{LOCAL_CLOUD_NUMBERED_PREFIX}{max_num + 1:03d}"


def _next_vdb_cloud_name():
    pattern = re.compile(rf"^{re.escape(VDB_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$")
    max_num = 0
    for obj in getattr(bpy.data, "objects", ()): 
        match = pattern.match(str(getattr(obj, "name", "")))
        if match:
            try:
                max_num = max(max_num, int(match.group(1)))
            except (TypeError, ValueError):
                continue
    return f"{VDB_CLOUD_NUMBERED_PREFIX}{max_num + 1:03d}"


def _local_cloud_material_name_for_object(object_name):
    match = re.match(rf"^{re.escape(LOCAL_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$", str(object_name or ""))
    if match:
        return f"Planetka Local Cloud Shader No {match.group(1)}"
    return "Planetka Local Cloud Shader"


def _vdb_cloud_material_name_for_object(object_name):
    match = re.match(rf"^{re.escape(VDB_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$", str(object_name or ""))
    if match:
        return f"Planetka VDB Cloud Shader No {match.group(1)}"
    return "Planetka VDB Cloud Shader"


def _find_image_texture_node(material):
    if material is None or not getattr(material, "node_tree", None):
        return None
    node_tree = material.node_tree
    node = node_tree.nodes.get("Image Texture")
    if node is not None and str(getattr(node, "type", "")) == "TEX_IMAGE":
        return node
    for candidate in node_tree.nodes:
        if str(getattr(candidate, "type", "")) == "TEX_IMAGE":
            return candidate
    return None


def _resolve_object_material(obj):
    material = getattr(obj, "active_material", None)
    if material is not None:
        return material
    data = getattr(obj, "data", None)
    materials = getattr(data, "materials", None) if data is not None else None
    if materials:
        return materials[0]
    return None


def _set_local_cloud_texture_by_filename(obj, filename):
    if not _is_local_cloud_object(obj):
        return False
    if not filename or filename == "NONE":
        return False
    assets = _refresh_remote_local_cloud_assets(force=False)
    if str(filename) not in assets:
        assets = _refresh_remote_local_cloud_assets(force=True)
    texture_path = assets.get(str(filename), "")
    if not texture_path and os.path.isfile(str(filename)):
        texture_path = str(filename)
    if not os.path.isfile(texture_path):
        return False

    material = _resolve_object_material(obj)
    image_node = _find_image_texture_node(material)
    if image_node is None:
        return False

    try:
        image = bpy.data.images.load(texture_path, check_existing=True)
        image_node.image = image
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed loading local cloud texture", exc_info=True)
    return False


def _is_named_value_node(node, node_name):
    if node is None or str(getattr(node, "type", "")) != "VALUE":
        return False
    target = str(node_name or "").strip()
    if not target:
        return False
    name = str(getattr(node, "name", "") or "")
    label = str(getattr(node, "label", "") or "")
    if name == target or label == target:
        return True
    # Be tolerant to Blender's auto-suffixed duplicates (e.g. ".001").
    return name.startswith(f"{target}.") or label.startswith(f"{target}.")


def _iter_named_value_nodes_recursive(node_tree, node_name, visited=None):
    if node_tree is None:
        return []
    if visited is None:
        visited = set()
    try:
        ptr = int(node_tree.as_pointer())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        ptr = id(node_tree)
    if ptr in visited:
        return []
    visited.add(ptr)

    found = []
    for node in node_tree.nodes:
        if _is_named_value_node(node, node_name):
            found.append((node_tree, node))
    for node in node_tree.nodes:
        child = getattr(node, "node_tree", None)
        if child is not None:
            found.extend(_iter_named_value_nodes_recursive(child, node_name, visited=visited))
    return found


def _set_named_value_nodes_recursive(node_tree, node_names, value):
    changed = False
    for node_name in node_names:
        for _tree, node in _iter_named_value_nodes_recursive(node_tree, node_name):
            try:
                node.outputs[0].default_value = float(value)
                changed = True
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed updating value node", exc_info=True)
    return changed


def _find_first_value_node(nodes, candidate_names):
    if nodes is None:
        return None
    for candidate in candidate_names:
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            continue
        node = nodes.get(candidate_text)
        if node is not None and str(getattr(node, "type", "")) == "VALUE":
            return node
        dotted_prefix = f"{candidate_text}."
        for iter_node in nodes:
            if str(getattr(iter_node, "type", "")) != "VALUE":
                continue
            name = str(getattr(iter_node, "name", "") or "")
            label = str(getattr(iter_node, "label", "") or "")
            if name.startswith(dotted_prefix) or label.startswith(dotted_prefix):
                return iter_node
    return None


def _set_value_node_output(node, value):
    if node is None:
        return False
    try:
        node.outputs[0].default_value = float(value)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed writing value node output", exc_info=True)
    except (AttributeError, RuntimeError, TypeError, ValueError, IndexError):
        logger.debug("Planetka clouds: failed writing value node output", exc_info=True)
    return False


def _mesh_local_radius(obj):
    if obj is None:
        return 0.0
    mesh = getattr(obj, "data", None)
    vertices = getattr(mesh, "vertices", None) if mesh is not None else None
    if not vertices:
        return 0.0
    try:
        return max(float(v.co.length) for v in vertices)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0.0


def _derived_local_cloud_base_scale(obj):
    earth = get_earth_object()
    earth_radius = _earth_radius_blender_units(earth)
    mesh_radius = _mesh_local_radius(obj)
    if earth_radius <= 1e-9 or mesh_radius <= 1e-9:
        return max(
            abs(float(getattr(obj, "scale", (1.0, 1.0, 1.0))[0])),
            abs(float(getattr(obj, "scale", (1.0, 1.0, 1.0))[1])),
            abs(float(getattr(obj, "scale", (1.0, 1.0, 1.0))[2])),
            1.0,
        )
    return float(earth_radius) / float(mesh_radius)


def _iter_group_nodes_recursive(node_tree, group_name, visited=None):
    if node_tree is None:
        return []
    if visited is None:
        visited = set()
    try:
        ptr = int(node_tree.as_pointer())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        ptr = id(node_tree)
    if ptr in visited:
        return []
    visited.add(ptr)

    found = []
    for node in node_tree.nodes:
        child_tree = getattr(node, "node_tree", None)
        if child_tree is None:
            continue
        child_name = str(getattr(child_tree, "name", ""))
        if str(getattr(node, "name", "")) == group_name or child_name == group_name:
            found.append(node)
        found.extend(_iter_group_nodes_recursive(child_tree, group_name, visited=visited))
    return found


def _set_group_input_if_present(group_node, input_names, value):
    if group_node is None:
        return False
    for input_name in input_names:
        if input_name not in group_node.inputs:
            continue
        try:
            group_node.inputs[input_name].default_value = float(value)
            return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating group input '%s'", input_name, exc_info=True)
    return False


def _local_cloud_half_angle_deg(size_coef):
    try:
        safe_size = float(size_coef)
    except (TypeError, ValueError):
        safe_size = 1.0
    safe_size = max(0.05, min(10.0, safe_size))
    angle = float(LOCAL_CLOUD_BASE_HALF_ANGLE_DEG) * safe_size
    return max(float(LOCAL_CLOUD_MIN_HALF_ANGLE_DEG), min(float(LOCAL_CLOUD_MAX_HALF_ANGLE_DEG), angle))


def _build_local_cloud_cap_mesh(mesh, half_angle_deg, segments=96, rings=24, inner_ratio=0.992):
    if mesh is None:
        return

    half_angle_rad = math.radians(max(0.1, float(half_angle_deg)))
    segments = max(12, int(segments))
    rings = max(4, int(rings))
    inner_ratio = max(0.8, min(0.9999, float(inner_ratio)))

    ring_radius_max = max(1e-6, math.sin(half_angle_rad))

    verts = []
    uvs = []
    faces = []

    def add_vertex(x, y, z):
        verts.append((float(x), float(y), float(z)))
        u = 0.5 + 0.5 * (float(x) / ring_radius_max)
        v = 0.5 + 0.5 * (float(y) / ring_radius_max)
        uvs.append((max(0.0, min(1.0, u)), max(0.0, min(1.0, v))))
        return len(verts) - 1

    outer_top = add_vertex(0.0, 0.0, 1.0)
    inner_top = add_vertex(0.0, 0.0, inner_ratio)

    outer_rings = []
    inner_rings = []

    for ring_index in range(1, rings + 1):
        theta = half_angle_rad * (float(ring_index) / float(rings))
        sin_theta = math.sin(theta)
        cos_theta = math.cos(theta)
        outer_ring = []
        inner_ring = []
        for seg_index in range(segments):
            phi = (2.0 * math.pi) * (float(seg_index) / float(segments))
            cos_phi = math.cos(phi)
            sin_phi = math.sin(phi)
            ox = sin_theta * cos_phi
            oy = sin_theta * sin_phi
            oz = cos_theta
            ix = ox * inner_ratio
            iy = oy * inner_ratio
            iz = oz * inner_ratio
            outer_ring.append(add_vertex(ox, oy, oz))
            inner_ring.append(add_vertex(ix, iy, iz))
        outer_rings.append(outer_ring)
        inner_rings.append(inner_ring)

    first_outer = outer_rings[0]
    first_inner = inner_rings[0]

    for seg_index in range(segments):
        next_index = (seg_index + 1) % segments
        faces.append((outer_top, first_outer[seg_index], first_outer[next_index]))
        faces.append((inner_top, first_inner[next_index], first_inner[seg_index]))

    for ring_index in range(len(outer_rings) - 1):
        outer_a = outer_rings[ring_index]
        outer_b = outer_rings[ring_index + 1]
        inner_a = inner_rings[ring_index]
        inner_b = inner_rings[ring_index + 1]
        for seg_index in range(segments):
            next_index = (seg_index + 1) % segments
            faces.append((outer_a[seg_index], outer_a[next_index], outer_b[next_index], outer_b[seg_index]))
            faces.append((inner_a[seg_index], inner_b[seg_index], inner_b[next_index], inner_a[next_index]))

    outer_boundary = outer_rings[-1]
    inner_boundary = inner_rings[-1]
    for seg_index in range(segments):
        next_index = (seg_index + 1) % segments
        faces.append(
            (
                outer_boundary[seg_index],
                outer_boundary[next_index],
                inner_boundary[next_index],
                inner_boundary[seg_index],
            )
        )

    try:
        mesh.clear_geometry()
        mesh.from_pydata(verts, [], faces)
        mesh.update(calc_edges=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed rebuilding local cloud cap mesh", exc_info=True)
        return
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka clouds: failed rebuilding local cloud cap mesh", exc_info=True)
        return

    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        try:
            uv_layer = mesh.uv_layers.new(name="UVMap")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            uv_layer = None

    if uv_layer is not None:
        for poly in mesh.polygons:
            for loop_index in poly.loop_indices:
                vert_index = mesh.loops[loop_index].vertex_index
                try:
                    uv_layer.data[loop_index].uv = uvs[vert_index]
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka clouds: failed assigning UV to local cloud cap", exc_info=True)
                except (TypeError, ValueError, IndexError):
                    logger.debug("Planetka clouds: failed assigning UV to local cloud cap", exc_info=True)

    for polygon in mesh.polygons:
        polygon.use_smooth = True


def _ensure_local_cloud_subdivision_modifier(obj):
    if obj is None:
        return None
    modifier = None
    for candidate in getattr(obj, "modifiers", ()):
        if str(getattr(candidate, "type", "")) == "SUBSURF":
            modifier = candidate
            break
    if modifier is None:
        try:
            modifier = obj.modifiers.new(name="Subdivision", type='SUBSURF')
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating local cloud subdivision modifier", exc_info=True)
            return None
    try:
        modifier.levels = max(0, int(getattr(modifier, "levels", 1)))
        modifier.render_levels = max(1, int(getattr(modifier, "render_levels", 2)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed configuring local cloud subdivision modifier", exc_info=True)
    return modifier


def _ensure_local_cloud_cap_geometry(obj):
    if obj is None:
        return
    half_angle = _local_cloud_half_angle_deg(getattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0))
    stored_angle = float(getattr(obj, LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG, -1.0))

    mesh = getattr(obj, "data", None)
    if mesh is None or str(getattr(obj, "type", "")) != "MESH":
        mesh_name = f"{LOCAL_CLOUD_CAP_MESH_PREFIX} {obj.name}"
        mesh = bpy.data.meshes.new(mesh_name)
        obj.data = mesh

    needs_rebuild = (
        len(getattr(mesh, "vertices", ())) == 0
        or abs(stored_angle - float(half_angle)) > 1e-3
    )
    if not needs_rebuild:
        return

    _build_local_cloud_cap_mesh(mesh, half_angle_deg=half_angle)
    _begin_cloud_update_suspend()
    try:
        setattr(obj, LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG, float(half_angle))
    finally:
        _end_cloud_update_suspend()


def _configure_local_cloud_material_for_cap(material):
    if material is None or getattr(material, "node_tree", None) is None:
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return

    nodes = node_tree.nodes
    links = node_tree.links

    image_node = _find_image_texture_node(material)
    if image_node is None:
        return

    rotate_node = nodes.get("Local Cloud UV Rotate")
    if rotate_node is None or str(getattr(rotate_node, "type", "")) != "VECTOR_ROTATE":
        rotate_node = next((node for node in nodes if str(getattr(node, "type", "")) == "VECTOR_ROTATE"), None)
    if rotate_node is None:
        try:
            rotate_node = nodes.new("ShaderNodeVectorRotate")
            rotate_node.name = "Local Cloud UV Rotate"
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating UV rotate node", exc_info=True)
            return

    tex_coord = nodes.get("Local Cloud Texture Coordinate")
    if tex_coord is None or str(getattr(tex_coord, "type", "")) != "TEX_COORD":
        tex_coord = next((node for node in nodes if str(getattr(node, "type", "")) == "TEX_COORD"), None)
    if tex_coord is None:
        try:
            tex_coord = nodes.new("ShaderNodeTexCoord")
            tex_coord.name = "Local Cloud Texture Coordinate"
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating texture coordinate node", exc_info=True)
            return

    try:
        rotate_node.rotation_type = 'AXIS_ANGLE'
        rotate_node.inputs["Center"].default_value = (0.5, 0.5, 0.0)
        rotate_node.inputs["Axis"].default_value = (0.0, 0.0, 1.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed configuring UV rotate node", exc_info=True)

    try:
        for link in list(rotate_node.inputs["Vector"].links):
            links.remove(link)
        for link in list(image_node.inputs["Vector"].links):
            links.remove(link)
        links.new(tex_coord.outputs["UV"], rotate_node.inputs["Vector"])
        links.new(rotate_node.outputs["Vector"], image_node.inputs["Vector"])
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed wiring UV mapping nodes", exc_info=True)


def _iter_cloud_subdivision_modifiers(cloud_obj):
    if cloud_obj is None:
        return []
    out = []
    seen = set()
    for mod in getattr(cloud_obj, "modifiers", ()): 
        if str(getattr(mod, "type", "")) in {"SUBSURF", "MULTIRES"}:
            ptr = int(mod.as_pointer())
            if ptr not in seen:
                out.append(mod)
                seen.add(ptr)
                continue
        if "subdiv" in str(getattr(mod, "name", "")).lower():
            ptr = int(mod.as_pointer())
            if ptr not in seen:
                out.append(mod)
                seen.add(ptr)
    return out


def _set_universal_cloud_preview_value(preview_value):
    changed = False
    roots = (
        bpy.data.node_groups.get(CLOUD_PREVIEW_SWITCH_GROUP_NAME),
        bpy.data.node_groups.get(LOCAL_CLOUD_SHADER_GROUP_NAME),
        bpy.data.node_groups.get(GLOBAL_CLOUD_SHADER_GROUP_NAME),
    )
    for root in roots:
        if root is None:
            continue
        if _set_named_value_nodes_recursive(root, (LOCAL_CLOUD_PREVIEW_VALUE_NODE_NAME,), preview_value):
            changed = True
    return changed


def _apply_universal_cloud_preview_state(props, context=None):
    final_look = bool(getattr(props, "view_cloud_subdivision", False)) if props else False
    preview_value = 0.0 if final_look else 1.0
    _set_universal_cloud_preview_value(preview_value)

    for cloud_obj in list(_iter_local_cloud_objects()) + list(_iter_vdb_cloud_objects()):
        for mod in _iter_cloud_subdivision_modifiers(cloud_obj):
            try:
                mod.show_viewport = final_look
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed updating subdivision modifier state", exc_info=True)

    try:
        if context is not None and getattr(context, "view_layer", None):
            context.view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating view layer", exc_info=True)


def _earth_radius_blender_units(earth_obj):
    if earth_obj is None:
        return 1.0
    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0

    if stored_local_radius > 1e-9:
        scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(scale.x), abs(scale.y), abs(scale.z), 1e-9)
        return stored_local_radius * float(max_scale)

    vertices = getattr(getattr(earth_obj, "data", None), "vertices", None)
    if vertices:
        try:
            local_radius = max(v.co.length for v in vertices)
            if local_radius > 1e-9:
                scale = earth_obj.matrix_world.to_scale()
                max_scale = max(abs(scale.x), abs(scale.y), abs(scale.z), 1e-9)
                return float(local_radius) * float(max_scale)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    scale = earth_obj.matrix_world.to_scale()
    return max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)


def _scene_target_lon_lat_alt(scene):
    props = getattr(scene, "planetka", None) if scene else None

    lon = 0.0
    lat = 0.0
    alt_km = 0.0

    if props is not None:
        try:
            lon = float(getattr(props, "nav_longitude_deg", 0.0))
            lat = float(getattr(props, "nav_latitude_deg", 0.0))
            alt_km = float(getattr(props, "nav_altitude_km", 0.0))
        except (AttributeError, TypeError, ValueError):
            pass

    if scene is not None:
        try:
            lon = float(scene.get("planetka_nav_longitude_deg", lon))
            lat = float(scene.get("planetka_nav_latitude_deg", lat))
            alt_km = float(scene.get("planetka_nav_altitude_km", alt_km))
        except (TypeError, ValueError):
            pass

    return lon, lat, alt_km


def _ensure_vdb_cloud_template(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    source_obj = bpy.data.objects.get(VDB_CLOUD_TEMPLATE_OBJECT_NAME)

    if source_obj is None:
        _append_from_reference(
            object_names=(VDB_CLOUD_TEMPLATE_OBJECT_NAME,),
            material_names=(VDB_CLOUD_MATERIAL_TEMPLATE_NAME,),
        )
        source_obj = bpy.data.objects.get(VDB_CLOUD_TEMPLATE_OBJECT_NAME)

    if source_obj is None:
        raise RuntimeError(f"VDB cloud template object '{VDB_CLOUD_TEMPLATE_OBJECT_NAME}' not found in reference blend.")

    _clear_cloud_drivers(source_obj)
    _remove_cloud_cull_modifiers(source_obj)

    if scene is not None:
        _clouds, _global_clouds, _local_clouds, vdb_clouds = _ensure_cloud_collections(scene)
        _set_object_collections(source_obj, [vdb_clouds])
        root = ensure_planetka_root(scene)
        try:
            if root is not None:
                source_obj.parent = root
                source_obj.matrix_parent_inverse = root.matrix_world.inverted()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed parenting VDB cloud template", exc_info=True)

    try:
        source_obj[CLOUD_ROLE_KEY] = VDB_CLOUD_TEMPLATE_ROLE
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDL-004", "Failed tagging VDB template with cloud role")

    try:
        source_obj.hide_viewport = True
        source_obj.hide_render = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed hiding VDB cloud template", exc_info=True)

    mat = bpy.data.materials.get(VDB_CLOUD_MATERIAL_TEMPLATE_NAME)
    if mat is None:
        _append_from_reference(material_names=(VDB_CLOUD_MATERIAL_TEMPLATE_NAME,))
        mat = bpy.data.materials.get(VDB_CLOUD_MATERIAL_TEMPLATE_NAME)
    if mat is not None:
        _clear_drivers_on_id_data(mat)
        _clear_drivers_on_node_tree(getattr(mat, "node_tree", None))

    return source_obj


def _apply_local_cloud_material_controls(obj, material, final_look=False):
    if material is None or getattr(material, "node_tree", None) is None:
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return

    size = max(1e-6, float(getattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0)) * float(LOCAL_CLOUD_SIZE_REMOTE_SCALE))
    rot = float(getattr(obj, LOCAL_CLOUD_PROP_ROTATION_DEG, 0.0))
    thickness_m = max(0.0, float(getattr(obj, LOCAL_CLOUD_PROP_THICKNESS_M, 50.0)))
    density = max(0.0, float(getattr(obj, LOCAL_CLOUD_PROP_DENSITY, 10.0)))
    gamma = max(0.0, float(getattr(obj, LOCAL_CLOUD_PROP_DENSITY_GAMMA, 1.0)))
    _configure_local_cloud_material_for_cap(material)

    rotate_node = node_tree.nodes.get("Local Cloud UV Rotate")
    if rotate_node is not None and str(getattr(rotate_node, "type", "")) == "VECTOR_ROTATE":
        try:
            rotate_node.inputs["Angle"].default_value = math.radians(rot)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed setting local cloud UV rotation", exc_info=True)

    preview_value = 0.0 if bool(final_look) else 1.0
    _set_named_value_nodes_recursive(node_tree, (LOCAL_CLOUD_PREVIEW_VALUE_NODE_NAME,), preview_value)

    for shader_node in _iter_group_nodes_recursive(node_tree, LOCAL_CLOUD_SHADER_GROUP_NAME):
        _set_group_input_if_present(shader_node, ("Local Cloud Size", "Local Cloud Size Coef", "Size Coefficient"), size)
        if not _set_group_input_if_present(shader_node, ("Cloud Thickness (m)",), thickness_m):
            _set_group_input_if_present(shader_node, ("Cloud Thickness (km)",), thickness_m / 1000.0)
        _set_group_input_if_present(shader_node, ("Cloud Density",), density)
        _set_group_input_if_present(shader_node, ("Density Gamma",), gamma)
        _set_group_input_if_present(shader_node, LOCAL_CLOUD_PREVIEW_INPUT_NAMES, preview_value)


def _apply_local_cloud_object(obj, scene=None):
    if not _is_local_cloud_object(obj):
        return
    scene = scene or getattr(bpy.context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None

    lon = float(getattr(obj, LOCAL_CLOUD_PROP_LONGITUDE, 0.0))
    lat = float(getattr(obj, LOCAL_CLOUD_PROP_LATITUDE, 0.0))
    altitude_m = float(getattr(obj, LOCAL_CLOUD_PROP_ALTITUDE_M, DEFAULT_CLOUD_ALTITUDE_M))
    size_coef = max(0.05, float(getattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0)))

    _ensure_local_cloud_cap_geometry(obj)
    _ensure_local_cloud_subdivision_modifier(obj)

    earth = get_earth_object()
    earth_radius = max(1e-6, float(_earth_radius_blender_units(earth)))
    radius = earth_radius * max(0.001, (1.0 + (altitude_m / 6371000.0)))

    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    normal = Vector((
        math.cos(lat_rad) * math.cos(lon_rad),
        math.cos(lat_rad) * math.sin(lon_rad),
        math.sin(lat_rad),
    ))
    if normal.length <= 1e-9:
        normal = Vector((0.0, 0.0, 1.0))
    else:
        normal.normalize()

    try:
        align_quat = Vector((0.0, 0.0, 1.0)).rotation_difference(normal)
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = align_quat
        obj.location = (0.0, 0.0, 0.0)
        obj.scale = (radius, radius, radius)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating local cloud transform", exc_info=True)

    _begin_cloud_update_suspend()
    try:
        setattr(obj, LOCAL_CLOUD_PROP_BASE_SCALE, float(earth_radius))
        setattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, float(size_coef))
    finally:
        _end_cloud_update_suspend()

    final_look = bool(getattr(props, "view_cloud_subdivision", False)) if props else False

    for mod in _iter_cloud_subdivision_modifiers(obj):
        try:
            mod.show_viewport = final_look
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed setting local cloud subdivision visibility", exc_info=True)

    material = _resolve_object_material(obj)
    _apply_local_cloud_material_controls(obj, material, final_look=final_look)


def _set_vdb_cloud_filepath(obj, filepath):
    if obj is None or not filepath:
        return False
    volume_data = getattr(obj, "data", None)
    if volume_data is None or not hasattr(volume_data, "filepath"):
        return False
    abs_path = bpy.path.abspath(filepath)
    try:
        volume_data.filepath = abs_path
        if hasattr(volume_data, "is_sequence"):
            volume_data.is_sequence = False
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed assigning VDB filepath", exc_info=True)
        return False


def _apply_vdb_cloud_material_density(obj):
    material = _resolve_object_material(obj)
    if material is None or getattr(material, "node_tree", None) is None:
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return
    density = max(0.0, float(getattr(obj, VDB_CLOUD_PROP_DENSITY, 0.1)))
    _set_named_value_nodes_recursive(node_tree, (VDB_CLOUD_DENSITY_NODE_NAME,), density)


def _apply_vdb_cloud_object(obj, scene=None):
    if not _is_vdb_cloud_object(obj):
        return

    lon = float(getattr(obj, VDB_CLOUD_PROP_LONGITUDE, 0.0))
    lat = float(getattr(obj, VDB_CLOUD_PROP_LATITUDE, 0.0))
    alt = float(getattr(obj, VDB_CLOUD_PROP_ALTITUDE_M, 5000.0))
    size = max(0.001, float(getattr(obj, VDB_CLOUD_PROP_SIZE_COEF, 1.0)))
    rot = float(getattr(obj, VDB_CLOUD_PROP_ROTATION_DEG, 0.0))

    base_radius = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_BASE_RADIUS, 1.0)))
    radius = base_radius * (1.0 + alt / 6371000.0)

    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    rot_rad = math.radians(rot)

    x = radius * math.cos(lat_rad) * math.cos(lon_rad)
    y = radius * math.cos(lat_rad) * math.sin(lon_rad)
    z = radius * math.sin(lat_rad)

    try:
        obj.location = (x, y, z)
        obj.rotation_mode = 'XYZ'
        obj.rotation_euler = (
            math.atan2(math.cos(rot_rad) * math.cos(lat_rad), math.sin(lat_rad)) + math.radians(90.0),
            math.asin(max(-1.0, min(1.0, -math.sin(rot_rad) * math.cos(lat_rad)))),
            math.atan2(
                math.cos(rot_rad) * math.cos(lon_rad) - math.sin(rot_rad) * math.sin(lat_rad) * math.sin(lon_rad),
                -math.cos(rot_rad) * math.sin(lon_rad) - math.sin(rot_rad) * math.sin(lat_rad) * math.cos(lon_rad),
            ),
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating VDB cloud transform", exc_info=True)

    base_x = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_BASE_SCALE_X, abs(obj.scale.x) if obj.scale else 1.0)))
    base_y = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_BASE_SCALE_Y, abs(obj.scale.y) if obj.scale else 1.0)))
    base_z = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_BASE_SCALE_Z, abs(obj.scale.z) if obj.scale else 1.0)))

    try:
        obj.scale = (base_x * size, base_y * size, base_z * size)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating VDB cloud scale", exc_info=True)

    file_path = str(getattr(obj, VDB_CLOUD_OBJ_FILE_PROP, "") or "")
    if file_path:
        _set_vdb_cloud_filepath(obj, file_path)

    _apply_vdb_cloud_material_density(obj)


def _resolve_vdb_path(raw_value):
    raw = str(raw_value or "").strip()
    assets = _refresh_remote_vdb_cloud_assets(force=False)
    if raw and raw not in assets:
        assets = _refresh_remote_vdb_cloud_assets(force=True)
    if not raw:
        if assets:
            first_key = sorted(assets.keys())[0]
            return assets.get(first_key, "")
        return ""
    if raw in assets:
        return assets.get(raw, "")
    candidate = bpy.path.abspath(raw)
    if os.path.isdir(candidate):
        first = _first_vdb_in_dir(candidate)
        if first:
            return first
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)

    fallback = assets.get(os.path.basename(raw), "")
    if fallback and os.path.isfile(fallback):
        return os.path.abspath(fallback)

    return os.path.abspath(candidate)


def _first_vdb_in_dir(folder):
    assets = _refresh_remote_vdb_cloud_assets(force=False)
    if not assets:
        assets = _refresh_remote_vdb_cloud_assets(force=True)
    if assets:
        first_key = sorted(assets.keys())[0]
        first_path = assets.get(first_key, "")
        if first_path and os.path.isfile(first_path):
            return os.path.abspath(first_path)
    if not folder or not os.path.isdir(folder):
        return ""
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name.lower().endswith(".vdb"):
            return os.path.abspath(path)
    return ""


def _apply_cloud_object_updates_for_scene(scene):
    if scene is None:
        return
    # Explicitly remove cloud culling from all cloud objects.
    clouds_global = _get_clouds_global_module()
    ensure_global_fn = getattr(clouds_global, "ensure_global_cloud_layer", None) if clouds_global else None
    apply_global_fn = getattr(clouds_global, "apply_global_cloud_object", None) if clouds_global else None
    if callable(ensure_global_fn):
        global_obj = ensure_global_fn(scene=scene)
        _remove_cloud_cull_modifiers(global_obj)
        if callable(apply_global_fn):
            apply_global_fn(global_obj, scene=scene)
    for obj in _iter_local_cloud_objects():
        _remove_cloud_cull_modifiers(obj)
        _apply_local_cloud_object(obj, scene=scene)
    for obj in _iter_vdb_cloud_objects():
        _remove_cloud_cull_modifiers(obj)
        _apply_vdb_cloud_object(obj, scene=scene)


def update_enable_local_clouds(self, context):
    scene = getattr(context, "scene", None) if context else None
    _sync_scene_idprops(scene, ("enable_local_clouds",))
    _sync_cloud_collection_visibility(scene, self)
    if bool(getattr(self, "enable_local_clouds", False)):
        _apply_universal_cloud_preview_state(self, context=context)


def update_enable_vdb_clouds(self, context):
    scene = getattr(context, "scene", None) if context else None
    _sync_scene_idprops(scene, ("enable_vdb_clouds",))
    _sync_cloud_collection_visibility(scene, self)


def update_view_cloud_subdivision(self, context):
    scene = getattr(context, "scene", None) if context else None
    _sync_scene_idprops(scene, ("view_cloud_subdivision",))
    _apply_universal_cloud_preview_state(self, context=context)


def update_local_cloud_object_texture(self, context):
    obj = self
    if _is_cloud_updates_suspended() or not _is_local_cloud_object(obj):
        return
    filename = str(getattr(obj, LOCAL_CLOUD_OBJ_TEXTURE_PROP, "") or "")
    _set_local_cloud_texture_by_filename(obj, filename)
    _apply_local_cloud_object(obj, scene=getattr(context, "scene", None) if context else None)


def update_local_cloud_object_prop(self, context):
    if _is_cloud_updates_suspended() or not _is_local_cloud_object(self):
        return
    _apply_local_cloud_object(self, scene=getattr(context, "scene", None) if context else None)


def update_vdb_cloud_object_prop(self, context):
    if _is_cloud_updates_suspended() or not _is_vdb_cloud_object(self):
        return
    _apply_vdb_cloud_object(self, scene=getattr(context, "scene", None) if context else None)


def sync_cloud_system_scene(scene):
    props = getattr(scene, "planetka", None) if scene else None
    _sync_cloud_collection_visibility(scene, props)
    if props is None or bool(getattr(props, "enable_global_clouds", True)):
        clouds_global = _get_clouds_global_module()
        ensure_global_fn = getattr(clouds_global, "ensure_global_cloud_layer", None) if clouds_global else None
        if callable(ensure_global_fn):
            try:
                ensure_global_fn(scene=scene)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed ensuring global cloud layer during sync", exc_info=True)
    if props is not None:
        _apply_universal_cloud_preview_state(props, context=None)
    _apply_cloud_object_updates_for_scene(scene)


def _is_workflow_enabled():
    try:
        return bool(is_authenticated(get_prefs())) and (get_earth_object() is not None)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False


def _cloud_title(name, fallback_index, prefix):
    match = re.search(r"(\d+)$", str(name or ""))
    if match:
        try:
            return f"{prefix} {int(match.group(1)):03d}"
        except (TypeError, ValueError):
            pass
    return f"{prefix} {fallback_index:03d}"


def _vdb_file_label(obj):
    path = str(getattr(obj, VDB_CLOUD_OBJ_FILE_PROP, "") or "")
    if not path:
        data = getattr(obj, "data", None)
        path = str(getattr(data, "filepath", "") or "") if data else ""
    if not path:
        return "No VDB file assigned"
    return os.path.basename(bpy.path.abspath(path))


class PLANETKA_OT_SetCloudViewMode(bpy.types.Operator):
    bl_idname = "planetka.set_cloud_view_mode"
    bl_label = "Set Cloud View Mode"
    bl_description = "Switch cloud shading mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=(
            ("PREVIEW", "Preview", ""),
            ("VOLUME", "Final Look", ""),
        ),
        default="VOLUME",
    )

    def execute(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}

        desired_final_look = self.mode == "VOLUME"
        if bool(getattr(props, "view_cloud_subdivision", False)) != desired_final_look:
            props.view_cloud_subdivision = desired_final_look
        else:
            _apply_universal_cloud_preview_state(props, context=context)

        self.report({'INFO'}, f"Cloud mode: {'Final Look' if desired_final_look else 'Preview'}")
        return {'FINISHED'}


class PLANETKA_OT_AddLocalCloud(bpy.types.Operator):
    bl_idname = "planetka.add_local_cloud"
    bl_label = "Add Cloud"
    bl_description = "Add a local cloud cap layer"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}

        selected = str(getattr(props, "local_cloud_texture", "") or "")
        if not selected or selected == "NONE":
            self.report({'ERROR'}, "Select a local cloud texture first.")
            return {'CANCELLED'}

        texture_path = _refresh_remote_local_cloud_assets(force=True).get(selected, "")
        if not os.path.isfile(texture_path):
            self.report({'ERROR'}, f"Selected texture not found: {texture_path}")
            return {'CANCELLED'}

        _clouds, _global_clouds, local_clouds, _vdb_clouds = _ensure_cloud_collections(scene)

        template_mat = bpy.data.materials.get(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME)
        if template_mat is None:
            try:
                _append_from_reference(material_names=(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME,))
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                self.report({'ERROR'}, f"Failed loading local cloud material template: {exc}")
                return {'CANCELLED'}
            template_mat = bpy.data.materials.get(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME)
        if template_mat is None:
            self.report({'ERROR'}, f"Material '{LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME}' not found.")
            return {'CANCELLED'}

        new_name = _next_local_cloud_name()
        mesh_name = f"{LOCAL_CLOUD_CAP_MESH_PREFIX} {new_name}"
        try:
            mesh = bpy.data.meshes.new(mesh_name)
            new_obj = bpy.data.objects.new(new_name, mesh)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed creating local cloud cap object: {exc}")
            return {'CANCELLED'}

        try:
            local_clouds.objects.link(new_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            try:
                bpy.data.objects.remove(new_obj, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-CLOUDL-005", "Failed cleanup-removing local cloud object after link failure")
            if mesh is not None and int(getattr(mesh, "users", 0)) == 0:
                try:
                    bpy.data.meshes.remove(mesh)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-CLOUDL-006", "Failed cleanup-removing local cloud mesh after link failure")
            self.report({'ERROR'}, f"Failed linking local cloud: {exc}")
            return {'CANCELLED'}

        new_mat = template_mat.copy()
        new_mat.name = _local_cloud_material_name_for_object(new_obj.name)
        _clear_drivers_on_id_data(new_mat)
        _clear_drivers_on_node_tree(getattr(new_mat, "node_tree", None))

        mesh = getattr(new_obj, "data", None)
        if mesh is not None and hasattr(mesh, "materials"):
            try:
                mesh.materials.clear()
                mesh.materials.append(new_mat)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed assigning local cloud material", exc_info=True)

        root = ensure_planetka_root(scene)
        try:
            if root is not None:
                new_obj.parent = root
                new_obj.matrix_parent_inverse = root.matrix_world.inverted()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed parenting local cloud", exc_info=True)

        try:
            new_obj[CLOUD_ROLE_KEY] = LOCAL_CLOUD_ROLE
            new_obj.hide_viewport = False
            new_obj.hide_render = False
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-007", "Failed setting local cloud role/visibility flags")

        lon, lat, _alt_km = _scene_target_lon_lat_alt(scene)

        _begin_cloud_update_suspend()
        try:
            setattr(new_obj, LOCAL_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(new_obj, LOCAL_CLOUD_PROP_LATITUDE, float(lat))
            setattr(new_obj, LOCAL_CLOUD_PROP_ALTITUDE_M, float(DEFAULT_CLOUD_ALTITUDE_M))
            setattr(new_obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_ROTATION_DEG, 0.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_THICKNESS_M, 50.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_DENSITY, 10.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_DENSITY_GAMMA, 1.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_BASE_SCALE, float(max(1e-6, _earth_radius_blender_units(get_earth_object()))))
            setattr(new_obj, LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG, -1.0)
            setattr(new_obj, LOCAL_CLOUD_OBJ_TEXTURE_PROP, selected)
        finally:
            _end_cloud_update_suspend()

        _set_local_cloud_texture_by_filename(new_obj, selected)
        _apply_local_cloud_object(new_obj, scene=scene)

        try:
            props.enable_local_clouds = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _sync_cloud_collection_visibility(scene, props)

        _apply_universal_cloud_preview_state(props, context=context)

        try:
            context.view_layer.objects.active = new_obj
            new_obj.select_set(True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-008", "Failed selecting newly created local cloud object")

        self.report({'INFO'}, f"Added local cloud: {new_obj.name}")
        return {'FINISHED'}


class PLANETKA_OT_ResetLocalCloudToCameraView(bpy.types.Operator):
    bl_idname = "planetka.reset_local_cloud_to_camera_view"
    bl_label = "Reset Cloud Position"
    bl_description = "Reset selected local cloud to current Planetka camera target"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_local_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_local_cloud_object(active_obj):
            return active_obj
        return None

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a local cloud object first.")
            return {'CANCELLED'}

        lon, lat, alt_km = _scene_target_lon_lat_alt(getattr(context, "scene", None))
        _begin_cloud_update_suspend()
        try:
            setattr(obj, LOCAL_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(obj, LOCAL_CLOUD_PROP_LATITUDE, float(lat))
            setattr(obj, LOCAL_CLOUD_PROP_ALTITUDE_M, (float(alt_km) + 10.0) * 1000.0)
        finally:
            _end_cloud_update_suspend()

        _apply_local_cloud_object(obj, scene=getattr(context, "scene", None))
        self.report({'INFO'}, f"{obj.name}: moved to camera target")
        return {'FINISHED'}


class PLANETKA_OT_DeleteLocalCloud(bpy.types.Operator):
    bl_idname = "planetka.delete_local_cloud"
    bl_label = "Delete Cloud"
    bl_description = "Delete this local cloud"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_local_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_local_cloud_object(active_obj):
            return active_obj
        return None

    def invoke(self, context, event):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a local cloud object first.")
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a local cloud object first.")
            return {'CANCELLED'}

        mesh = getattr(obj, "data", None)
        materials = []
        if mesh is not None and hasattr(mesh, "materials"):
            materials = [mat for mat in mesh.materials if mat]

        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed deleting cloud: {exc}")
            return {'CANCELLED'}

        if mesh is not None and int(getattr(mesh, "users", 0)) == 0:
            try:
                bpy.data.meshes.remove(mesh)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed removing unused local cloud mesh", exc_info=True)

        for mat in materials:
            if mat is not None and int(getattr(mat, "users", 0)) == 0:
                try:
                    bpy.data.materials.remove(mat)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka clouds: failed removing local cloud material", exc_info=True)

        self.report({'INFO'}, "Local cloud deleted")
        return {'FINISHED'}


class PLANETKA_OT_AddVDBCloud(bpy.types.Operator):
    bl_idname = "planetka.add_vdb_cloud"
    bl_label = "Add VDB Cloud"
    bl_description = "Add a VDB cloud from template"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}

        vdb_path = _resolve_vdb_path(getattr(props, "vdb_cloud_file", ""))
        if not vdb_path:
            vdb_path = _first_vdb_in_dir(_vdb_clouds_dir())
            if vdb_path:
                props.vdb_cloud_file = vdb_path

        if not vdb_path or not os.path.isfile(vdb_path):
            self.report({'ERROR'}, "Select a valid VDB file first.")
            return {'CANCELLED'}

        if not str(vdb_path).lower().endswith(".vdb"):
            self.report({'ERROR'}, f"Selected file is not a VDB: {vdb_path}")
            return {'CANCELLED'}

        try:
            source_obj = _ensure_vdb_cloud_template(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed preparing VDB cloud template: {exc}")
            return {'CANCELLED'}

        _clouds, _global_clouds, _local_clouds, vdb_clouds = _ensure_cloud_collections(scene)

        new_obj = source_obj.copy()
        if getattr(source_obj, "data", None) is not None:
            try:
                new_obj.data = source_obj.data.copy()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-CLOUDL-009", "Failed duplicating VDB cloud mesh data; using shared data")
        try:
            new_obj.animation_data_clear()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-010", "Failed clearing animation data on duplicated VDB cloud")
        _remove_cloud_cull_modifiers(new_obj)
        new_obj.name = _next_vdb_cloud_name()

        try:
            vdb_clouds.objects.link(new_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed linking VDB cloud: {exc}")
            return {'CANCELLED'}

        for col in list(new_obj.users_collection):
            if col == vdb_clouds:
                continue
            try:
                col.objects.unlink(new_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-CLOUDL-011", "Failed unlinking VDB cloud from non-target collection")

        template_mat = _resolve_object_material(source_obj) or bpy.data.materials.get(VDB_CLOUD_MATERIAL_TEMPLATE_NAME)
        if template_mat is None:
            self.report({'ERROR'}, f"Material '{VDB_CLOUD_MATERIAL_TEMPLATE_NAME}' not found.")
            try:
                bpy.data.objects.remove(new_obj, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-CLOUDL-012", "Failed cleanup-removing VDB cloud object after material error")
            return {'CANCELLED'}

        new_mat = template_mat.copy()
        new_mat.name = _vdb_cloud_material_name_for_object(new_obj.name)
        _clear_drivers_on_id_data(new_mat)
        _clear_drivers_on_node_tree(getattr(new_mat, "node_tree", None))

        data = getattr(new_obj, "data", None)
        if data is not None and hasattr(data, "materials"):
            try:
                data.materials.clear()
                data.materials.append(new_mat)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed assigning VDB material", exc_info=True)

        root = ensure_planetka_root(scene)
        try:
            if root is not None:
                new_obj.parent = root
                new_obj.matrix_parent_inverse = root.matrix_world.inverted()
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed parenting VDB cloud", exc_info=True)

        try:
            new_obj[CLOUD_ROLE_KEY] = VDB_CLOUD_ROLE
            new_obj.hide_viewport = False
            new_obj.hide_render = False
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-013", "Failed setting VDB cloud role/visibility flags")

        earth = get_earth_object()
        earth_radius = _earth_radius_blender_units(earth)
        parent_scale = 1.0
        if getattr(new_obj, "parent", None) is not None:
            try:
                pscale = new_obj.parent.scale
                parent_scale = max(abs(float(pscale.x)), abs(float(pscale.y)), abs(float(pscale.z)), 1e-6)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                parent_scale = 1.0
        base_radius = max(1e-6, earth_radius / parent_scale)

        lon, lat, _alt_km = _scene_target_lon_lat_alt(scene)
        _begin_cloud_update_suspend()
        try:
            setattr(new_obj, VDB_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(new_obj, VDB_CLOUD_PROP_LATITUDE, float(lat))
            setattr(new_obj, VDB_CLOUD_PROP_ALTITUDE_M, float(DEFAULT_CLOUD_ALTITUDE_M))
            setattr(new_obj, VDB_CLOUD_PROP_SIZE_COEF, 1.0)
            setattr(new_obj, VDB_CLOUD_PROP_ROTATION_DEG, 0.0)
            setattr(new_obj, VDB_CLOUD_PROP_DENSITY, 0.1)
            setattr(new_obj, VDB_CLOUD_PROP_BASE_SCALE_X, abs(float(new_obj.scale.x)))
            setattr(new_obj, VDB_CLOUD_PROP_BASE_SCALE_Y, abs(float(new_obj.scale.y)))
            setattr(new_obj, VDB_CLOUD_PROP_BASE_SCALE_Z, abs(float(new_obj.scale.z)))
            setattr(new_obj, VDB_CLOUD_PROP_BASE_RADIUS, float(base_radius))
            setattr(new_obj, VDB_CLOUD_OBJ_FILE_PROP, os.path.abspath(vdb_path))
        finally:
            _end_cloud_update_suspend()

        _set_vdb_cloud_filepath(new_obj, vdb_path)
        _apply_vdb_cloud_object(new_obj, scene=scene)

        props.vdb_cloud_file = os.path.abspath(vdb_path)
        try:
            props.enable_vdb_clouds = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _sync_cloud_collection_visibility(scene, props)

        try:
            context.view_layer.objects.active = new_obj
            new_obj.select_set(True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-014", "Failed selecting newly created VDB cloud object")

        self.report({'INFO'}, f"Added VDB cloud: {new_obj.name}")
        return {'FINISHED'}


class PLANETKA_OT_ResetVDBCloudToCameraView(bpy.types.Operator):
    bl_idname = "planetka.reset_vdb_cloud_to_camera_view"
    bl_label = "Reset Cloud Position"
    bl_description = "Reset selected VDB cloud to current Planetka camera target"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_vdb_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_vdb_cloud_object(active_obj):
            return active_obj
        return None

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a VDB cloud object first.")
            return {'CANCELLED'}

        lon, lat, alt_km = _scene_target_lon_lat_alt(getattr(context, "scene", None))
        _begin_cloud_update_suspend()
        try:
            setattr(obj, VDB_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(obj, VDB_CLOUD_PROP_LATITUDE, float(lat))
            setattr(obj, VDB_CLOUD_PROP_ALTITUDE_M, (float(alt_km) + 10.0) * 1000.0)
        finally:
            _end_cloud_update_suspend()

        _apply_vdb_cloud_object(obj, scene=getattr(context, "scene", None))
        self.report({'INFO'}, f"{obj.name}: moved to camera target")
        return {'FINISHED'}


class PLANETKA_OT_DeleteVDBCloud(bpy.types.Operator):
    bl_idname = "planetka.delete_vdb_cloud"
    bl_label = "Delete Cloud"
    bl_description = "Delete this VDB cloud"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_vdb_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_vdb_cloud_object(active_obj):
            return active_obj
        return None

    def invoke(self, context, event):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a VDB cloud object first.")
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a VDB cloud object first.")
            return {'CANCELLED'}

        data_block = getattr(obj, "data", None)
        materials = []
        if data_block is not None and hasattr(data_block, "materials"):
            materials = [mat for mat in data_block.materials if mat]

        obj_type = str(getattr(obj, "type", ""))
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed deleting cloud: {exc}")
            return {'CANCELLED'}

        if data_block is not None and int(getattr(data_block, "users", 0)) == 0:
            try:
                if obj_type == "VOLUME" and hasattr(bpy.data, "volumes"):
                    bpy.data.volumes.remove(data_block)
                elif obj_type == "MESH" and hasattr(bpy.data, "meshes"):
                    bpy.data.meshes.remove(data_block)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed removing VDB data block", exc_info=True)

        for mat in materials:
            if mat is not None and int(getattr(mat, "users", 0)) == 0:
                try:
                    bpy.data.materials.remove(mat)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka clouds: failed removing VDB material", exc_info=True)

        self.report({'INFO'}, "VDB cloud deleted")
        return {'FINISHED'}


class PLANETKA_PT_LocalCloudsPanel(bpy.types.Panel):
    bl_label = "Local Clouds"
    bl_idname = "PLANETKA_PT_local_clouds"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 9007

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.use_property_split = False
        row.prop(
            props,
            "enable_local_clouds",
            text="Disable Local Clouds" if bool(getattr(props, "enable_local_clouds", False)) else "Enable Local Clouds",
            toggle=True,
            invert_checkbox=True,
        )

        if not bool(getattr(props, "enable_local_clouds", False)):
            return

        items = _ensure_local_cloud_previews()

        box = layout.box()
        box.label(text="Texture Picker", icon="IMAGE_DATA")
        if not items:
            box.label(text="No Cloud local-cloud test textures available.", icon="ERROR")
            cache_dir = _local_clouds_dir()
            if cache_dir:
                box.label(text=cache_dir, icon="FILE_FOLDER")
        else:
            box.template_icon_view(props, "local_cloud_texture", show_labels=True, scale=6.0, scale_popup=6.0)

        row = box.row()
        row.use_property_split = False
        row.operator("planetka.add_local_cloud", text="Add Cloud", icon="ADD")

        mode_row = box.row(align=True)
        mode_row.use_property_split = False
        preview_on = not bool(getattr(props, "view_cloud_subdivision", False))
        op = mode_row.operator("planetka.set_cloud_view_mode", text="Preview", depress=preview_on)
        op.mode = "PREVIEW"
        op = mode_row.operator("planetka.set_cloud_view_mode", text="Final Look", depress=not preview_on)
        op.mode = "VOLUME"

        clouds = _sort_cloud_objects_by_suffix(list(_iter_local_cloud_objects()))
        if not clouds:
            info = layout.box()
            info.label(text="No local clouds added yet.", icon="INFO")
            return

        for idx, cloud_obj in enumerate(clouds, start=1):
            panel_body = layout.box()
            panel_body.label(text=_cloud_title(cloud_obj.name, idx, "Cloud No"), icon="MODIFIER")

            vis_row = panel_body.row()
            vis_row.use_property_split = False
            vis_row.prop(
                cloud_obj,
                "hide_viewport",
                text="Show in Viewport" if bool(getattr(cloud_obj, "hide_viewport", False)) else "Hide in Viewport",
                toggle=True,
                icon="HIDE_OFF",
            )

            panel_body.template_icon_view(
                cloud_obj,
                LOCAL_CLOUD_OBJ_TEXTURE_PROP,
                show_labels=True,
                scale=6.0,
                scale_popup=6.0,
            )

            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_SIZE_COEF, text="Size Coefficient")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_LATITUDE, text="Latitude")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_LONGITUDE, text="Longitude")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_ROTATION_DEG, text="Rotation (deg)")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_ALTITUDE_M, text="Altitude (m)")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_THICKNESS_M, text="Thickness (m)")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_DENSITY, text="Density")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_DENSITY_GAMMA, text="Density Gamma")

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.reset_local_cloud_to_camera_view", text="Reset Cloud Position", icon="TRACKING")
            op.object_name = cloud_obj.name

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.delete_local_cloud", text="Delete Cloud", icon="TRASH")
            op.object_name = cloud_obj.name


class PLANETKA_PT_VDBCloudsPanel(bpy.types.Panel):
    bl_label = "VDB Clouds"
    bl_idname = "PLANETKA_PT_vdb_clouds"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 9008

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.use_property_split = False
        row.prop(
            props,
            "enable_vdb_clouds",
            text="Disable VDB Clouds" if bool(getattr(props, "enable_vdb_clouds", False)) else "Enable VDB Clouds",
            toggle=True,
            invert_checkbox=True,
        )

        if not bool(getattr(props, "enable_vdb_clouds", False)):
            return

        box = layout.box()
        box.label(text="VDB File", icon="VOLUME_DATA")
        box.prop(props, "vdb_cloud_file", text="")
        box.label(text=f"Default folder: {_vdb_clouds_dir()}", icon="FILE_FOLDER")

        row = box.row()
        row.use_property_split = False
        row.operator("planetka.add_vdb_cloud", text="Add VDB Cloud", icon="ADD")

        clouds = _sort_cloud_objects_by_suffix(list(_iter_vdb_cloud_objects()))
        if not clouds:
            info = layout.box()
            info.label(text="No VDB clouds added yet.", icon="INFO")
            return

        for idx, cloud_obj in enumerate(clouds, start=1):
            panel_body = layout.box()
            panel_body.label(text=_cloud_title(cloud_obj.name, idx, "VDB Cloud No"), icon="VOLUME_DATA")

            vis_row = panel_body.row()
            vis_row.use_property_split = False
            vis_row.prop(
                cloud_obj,
                "hide_viewport",
                text="Show in Viewport" if bool(getattr(cloud_obj, "hide_viewport", False)) else "Hide in Viewport",
                toggle=True,
                icon="HIDE_OFF",
            )

            panel_body.label(text=f"File: {_vdb_file_label(cloud_obj)}", icon="FILE")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_SIZE_COEF, text="Size Coefficient")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_LATITUDE, text="Latitude")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_LONGITUDE, text="Longitude")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_ROTATION_DEG, text="Rotation (deg)")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_ALTITUDE_M, text="Altitude (m)")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_DENSITY, text="Density")

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.reset_vdb_cloud_to_camera_view", text="Reset Cloud Position", icon="TRACKING")
            op.object_name = cloud_obj.name

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.delete_vdb_cloud", text="Delete Cloud", icon="TRASH")
            op.object_name = cloud_obj.name


def register_object_properties():
    object_props = bpy.types.Object

    if not hasattr(object_props, LOCAL_CLOUD_OBJ_TEXTURE_PROP):
        setattr(
            object_props,
            LOCAL_CLOUD_OBJ_TEXTURE_PROP,
            EnumProperty(
                name="Local Cloud Texture",
                description="Select a local cloud texture",
                items=_local_cloud_texture_items,
                update=update_local_cloud_object_texture,
            ),
        )

    for name, kwargs in (
        (
            LOCAL_CLOUD_PROP_LONGITUDE,
            dict(name="Local Cloud Longitude", default=0.0, min=-360.0, max=360.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_LATITUDE,
            dict(name="Local Cloud Latitude", default=0.0, min=-90.0, max=90.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_ALTITUDE_M,
            dict(name="Local Cloud Altitude (m)", default=5000.0, min=-100000.0, max=200000000.0, precision=2, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_SIZE_COEF,
            dict(name="Local Cloud Size Coef", default=1.0, min=0.001, max=1000.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_ROTATION_DEG,
            dict(name="Local Cloud Rotation (deg)", default=0.0, min=-360.0, max=360.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_THICKNESS_M,
            dict(name="Local Cloud Thickness (m)", default=50.0, min=0.0, max=1000000.0, precision=2, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_DENSITY,
            dict(name="Local Cloud Density", default=10.0, min=0.0, max=1000.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_DENSITY_GAMMA,
            dict(name="Local Cloud Density Gamma", default=1.0, min=0.0, max=1000.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_BASE_SCALE,
            dict(name="Local Cloud Base Scale", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG,
            dict(name="Local Cloud Cap Half Angle", default=-1.0, min=-1.0, max=180.0, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_LONGITUDE,
            dict(name="VDB Cloud Longitude", default=0.0, min=-360.0, max=360.0, precision=3, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_LATITUDE,
            dict(name="VDB Cloud Latitude", default=0.0, min=-90.0, max=90.0, precision=3, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_ALTITUDE_M,
            dict(name="VDB Cloud Altitude (m)", default=float(DEFAULT_CLOUD_ALTITUDE_M), min=-100000.0, max=200000000.0, precision=2, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_SIZE_COEF,
            dict(name="VDB Cloud Size Coef", default=1.0, min=0.001, max=1000.0, precision=3, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_ROTATION_DEG,
            dict(name="VDB Cloud Rotation", default=0.0, min=-360.0, max=360.0, precision=3, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_DENSITY,
            dict(name="VDB Cloud Density", default=0.1, min=0.0, max=1000.0, precision=3, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_BASE_SCALE_X,
            dict(name="VDB Cloud Base Scale X", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_BASE_SCALE_Y,
            dict(name="VDB Cloud Base Scale Y", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_BASE_SCALE_Z,
            dict(name="VDB Cloud Base Scale Z", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_BASE_RADIUS,
            dict(name="VDB Cloud Base Radius", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_OBJ_FILE_PROP,
            dict(name="VDB Cloud File", default="", subtype='FILE_PATH', update=update_vdb_cloud_object_prop),
        ),
    ):
        if hasattr(object_props, name):
            continue
        prop_factory = FloatProperty
        if name in {VDB_CLOUD_OBJ_FILE_PROP}:
            prop_factory = StringProperty
        kwargs = dict(kwargs)
        setattr(object_props, name, prop_factory(**kwargs))


def unregister_object_properties():
    object_props = bpy.types.Object
    names = (
        LOCAL_CLOUD_OBJ_TEXTURE_PROP,
        LOCAL_CLOUD_PROP_LONGITUDE,
        LOCAL_CLOUD_PROP_LATITUDE,
        LOCAL_CLOUD_PROP_ALTITUDE_M,
        LOCAL_CLOUD_PROP_SIZE_COEF,
        LOCAL_CLOUD_PROP_ROTATION_DEG,
        LOCAL_CLOUD_PROP_THICKNESS_M,
        LOCAL_CLOUD_PROP_DENSITY,
        LOCAL_CLOUD_PROP_DENSITY_GAMMA,
        LOCAL_CLOUD_PROP_BASE_SCALE,
        LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG,
        VDB_CLOUD_PROP_LONGITUDE,
        VDB_CLOUD_PROP_LATITUDE,
        VDB_CLOUD_PROP_ALTITUDE_M,
        VDB_CLOUD_PROP_SIZE_COEF,
        VDB_CLOUD_PROP_ROTATION_DEG,
        VDB_CLOUD_PROP_DENSITY,
        VDB_CLOUD_PROP_BASE_SCALE_X,
        VDB_CLOUD_PROP_BASE_SCALE_Y,
        VDB_CLOUD_PROP_BASE_SCALE_Z,
        VDB_CLOUD_PROP_BASE_RADIUS,
        VDB_CLOUD_OBJ_FILE_PROP,
    )
    for name in names:
        if hasattr(object_props, name):
            try:
                delattr(object_props, name)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed unregistering object property %s", name, exc_info=True)

    _free_local_cloud_previews()
