import bpy
import re
import bmesh
import logging
import os
from mathutils import Matrix
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object

TILE_RE = re.compile(r"x(\d+)_y(\d+)_z(\d+)_d(\d+)")

logger = logging.getLogger(__name__)
_RECOVERABLE_LOG_COUNTS = {}


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1


SURFACE_CULL_MOD_NAME = "Camera Cull Surface"
SURFACE_COLLECTION_NAME = "Planetka Earth Surface Collection"
EARTH_SURFACE_DEFAULT_RADIUS = 2.0
EARTH_SURFACE_DEFAULT_SCALE = (1.0, 1.0, 1.0)
BASE_SPHERE_CACHE_MESH_NAME = "Planetka__BaseSphereMeshCache_v1"
BASE_SPHERE_CACHE_BLEND_PATH = os.path.join("Resources", "planetka_base_sphere_mesh_cache.blend")
BASE_SPHERE_CACHE_MIN_VERTS = 10000
PREVIEW_OBJECT_NAME = "Planetka Preview Object"
PREVIEW_MATERIAL_NAME = "Planetka Preview Material"
PREVIEW_SEGMENTS = 36
PREVIEW_RING_COUNT = 18
PREVIEW_SCALE_FACTOR = 0.998
_PREVIEW_STATIC_BINDINGS = (
    ("S2", "S2_x000_y000_z360_d000.exr", "Linear Rec.709", ("Image Texture", "Preview S2")),
    ("EL", "EL_x000_y000_z360_d000.exr", "Linear Rec.709", ("Image Texture.001", "Preview EL")),
    ("WT", "WT_x000_y000_z360_d000.exr", "Linear Rec.709", ("Image Texture.002", "Preview WT")),
    ("PO", "PO_x000_y000_z360_d000.tif", "Linear Rec.709", ("Image Texture.003", "Preview PO")),
)
_ADAPTIVE_ENUM_WARNING_EMITTED = False


def _set_enum_property_safe(owner, prop_name, preferred_identifiers):
    if not owner or not hasattr(owner, prop_name):
        return False

    try:
        prop_def = owner.bl_rna.properties.get(prop_name)
        available = (
            {item.identifier for item in prop_def.enum_items}
            if prop_def and hasattr(prop_def, "enum_items")
            else set()
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        available = set()

    for identifier in preferred_identifiers:
        if available and identifier not in available:
            continue
        try:
            setattr(owner, prop_name, identifier)
            return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
    return False


def _get_enum_property_identifiers(owner, prop_name):
    if not owner or not hasattr(owner, prop_name):
        return ()
    try:
        prop_def = owner.bl_rna.properties.get(prop_name)
        if prop_def and hasattr(prop_def, "enum_items"):
            return tuple(item.identifier for item in prop_def.enum_items)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return ()
    return ()


def _warn_if_adaptive_enum_fallback(subsurf_mod):
    global _ADAPTIVE_ENUM_WARNING_EMITTED
    if _ADAPTIVE_ENUM_WARNING_EMITTED or subsurf_mod is None:
        return

    uv_value = str(getattr(subsurf_mod, "uv_smooth", "") or "")
    boundary_value = str(getattr(subsurf_mod, "boundary_smooth", "") or "")
    uv_ok = uv_value in {"ALL", "SMOOTH_ALL"}
    boundary_ok = boundary_value == "KEEP_CORNERS"
    if uv_ok and boundary_ok:
        return

    uv_options = _get_enum_property_identifiers(subsurf_mod, "uv_smooth")
    boundary_options = _get_enum_property_identifiers(subsurf_mod, "boundary_smooth")
    logger.warning(
        "Planetka: Adaptive Subdivision enum fallback detected "
        "(uv_smooth=%s, boundary_smooth=%s, uv_options=%s, boundary_options=%s).",
        uv_value or "<unavailable>",
        boundary_value or "<unavailable>",
        ",".join(uv_options) if uv_options else "<unknown>",
        ",".join(boundary_options) if boundary_options else "<unknown>",
    )
    _ADAPTIVE_ENUM_WARNING_EMITTED = True


def _enable_adaptive_subdivision(obj, subsurf_mod):
    adaptive_enabled = False

    if subsurf_mod is not None and hasattr(subsurf_mod, "use_adaptive_subdivision"):
        try:
            subsurf_mod.use_adaptive_subdivision = True
            adaptive_enabled = bool(getattr(subsurf_mod, "use_adaptive_subdivision", False))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-MESH-002", "Failed enabling adaptive subdivision on subsurf modifier")

    obj_cycles = getattr(obj, "cycles", None) if obj is not None else None
    if obj_cycles is not None:
        if hasattr(obj_cycles, "use_adaptive_subdivision"):
            try:
                obj_cycles.use_adaptive_subdivision = True
                adaptive_enabled = adaptive_enabled or bool(
                    getattr(obj_cycles, "use_adaptive_subdivision", False)
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-MESH-003", "Failed enabling adaptive subdivision on object cycles settings")
    return adaptive_enabled


def ensure_surface_collection():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return None
    surface_col = bpy.data.collections.get(SURFACE_COLLECTION_NAME)
    if surface_col is None:
        surface_col = bpy.data.collections.new(SURFACE_COLLECTION_NAME)
        scene.collection.children.link(surface_col)
    elif SURFACE_COLLECTION_NAME not in scene.collection.children:
        try:
            scene.collection.children.link(surface_col)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-MESH-006", "Failed relinking surface collection to scene root")
    return surface_col


def _set_object_collections(obj, collections):
    if not obj:
        return

    desired = [col for col in collections if col]
    desired_ids = {id(col) for col in desired}

    for col in list(obj.users_collection):
        if id(col) in desired_ids:
            continue
        try:
            col.objects.unlink(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed unlinking surface from collection %s", col.name, exc_info=True)

    for col in desired:
        try:
            if obj.name not in col.objects:
                col.objects.link(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed linking surface to collection %s", col.name, exc_info=True)


def _is_valid_base_sphere_mesh(mesh_data):
    if mesh_data is None:
        return False
    if len(getattr(mesh_data, "vertices", ())) < BASE_SPHERE_CACHE_MIN_VERTS:
        return False
    if len(getattr(mesh_data, "polygons", ())) == 0:
        return False
    uv_layers = getattr(mesh_data, "uv_layers", None)
    if uv_layers is None or len(uv_layers) == 0:
        return False
    return True


def _build_base_sphere_mesh_cache():
    bm = bmesh.new()
    try:
        bm.loops.layers.uv.new("UVMap")
        try:
            bmesh.ops.create_uvsphere(
                bm,
                u_segments=360,
                v_segments=180,
                radius=1.0,
                calc_uvs=True,
            )
        except TypeError:
            bmesh.ops.create_uvsphere(
                bm,
                u_segments=360,
                v_segments=180,
                radius=1.0,
            )
        cache_mesh = bpy.data.meshes.new(BASE_SPHERE_CACHE_MESH_NAME)
        bm.to_mesh(cache_mesh)
        cache_mesh.update()
        cache_mesh.use_fake_user = True
    finally:
        bm.free()

    return cache_mesh


def _load_bundled_base_sphere_mesh_cache():
    blend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BASE_SPHERE_CACHE_BLEND_PATH)
    if not os.path.isfile(blend_path):
        return None

    try:
        with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
            if BASE_SPHERE_CACHE_MESH_NAME not in set(data_from.meshes):
                return None
            data_to.meshes = [BASE_SPHERE_CACHE_MESH_NAME]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed loading bundled base sphere cache mesh", exc_info=True)
        return None

    cache_mesh = bpy.data.meshes.get(BASE_SPHERE_CACHE_MESH_NAME)
    if not _is_valid_base_sphere_mesh(cache_mesh):
        if cache_mesh is not None:
            try:
                bpy.data.meshes.remove(cache_mesh)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed removing invalid bundled base sphere cache mesh", exc_info=True)
        return None

    cache_mesh.use_fake_user = True
    return cache_mesh


def ensure_base_sphere_mesh_cache():
    cache_mesh = bpy.data.meshes.get(BASE_SPHERE_CACHE_MESH_NAME)
    if _is_valid_base_sphere_mesh(cache_mesh):
        return cache_mesh

    if cache_mesh is not None:
        try:
            bpy.data.meshes.remove(cache_mesh)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing invalid base sphere cache mesh", exc_info=True)

    cache_mesh = _load_bundled_base_sphere_mesh_cache()
    if _is_valid_base_sphere_mesh(cache_mesh):
        return cache_mesh

    try:
        return _build_base_sphere_mesh_cache()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.exception("Planetka: failed rebuilding base sphere cache mesh")
        return None


def create_uv_sphere(radius, location, rotation, name="Planetka Earth Surface"):
    cache_mesh = ensure_base_sphere_mesh_cache()
    if cache_mesh and _is_valid_base_sphere_mesh(cache_mesh):
        scene = getattr(bpy.context, "scene", None)
        if scene is not None:
            mesh_data = cache_mesh.copy()
            mesh_data.use_fake_user = False
            if abs(float(radius) - 1.0) > 1e-9:
                mesh_data.transform(Matrix.Scale(float(radius), 4))
            obj = bpy.data.objects.new(name, mesh_data)
            scene.collection.objects.link(obj)
            obj.location = location
            obj.rotation_euler = rotation
            return obj

    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=360,
        ring_count=180,
        radius=radius,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.object
    obj.name = name
    return obj


def _is_valid_preview_mesh(mesh):
    if not mesh:
        return False
    return len(getattr(mesh, "vertices", ())) >= 100 and len(getattr(mesh, "polygons", ())) >= 100


def _create_preview_object():
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=PREVIEW_SEGMENTS,
        ring_count=PREVIEW_RING_COUNT,
        radius=EARTH_SURFACE_DEFAULT_RADIUS,
        location=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
    )
    preview = bpy.context.object
    preview.name = PREVIEW_OBJECT_NAME
    return preview


def _remove_subsurf_modifiers(obj):
    for modifier in list(getattr(obj, "modifiers", ())):
        if modifier.type != 'SUBSURF':
            continue
        try:
            obj.modifiers.remove(modifier)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing subsurf modifier from preview", exc_info=True)


def _remove_object_and_unused_mesh(obj):
    if obj is None:
        return
    mesh_data = getattr(obj, "data", None) if getattr(obj, "type", None) == 'MESH' else None
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing object %s", getattr(obj, "name", "<unknown>"), exc_info=True)
        return

    if mesh_data is None:
        return
    try:
        if int(getattr(mesh_data, "users", 0)) == 0:
            bpy.data.meshes.remove(mesh_data)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing unused mesh data", exc_info=True)


def _set_image_colorspace_safe(image, colorspace):
    if image is None or not colorspace:
        return
    settings = getattr(image, "colorspace_settings", None)
    if settings is None or not hasattr(settings, "name"):
        return
    try:
        settings.name = str(colorspace)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-MESH-007", "Failed setting preview image colorspace")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-MESH-008", "Failed setting preview image colorspace")


def _load_preview_image(path, image_name, colorspace):
    if not path or not os.path.isfile(path):
        return None
    try:
        image = bpy.data.images.load(path, check_existing=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed loading preview texture image %s", path, exc_info=True)
        return None
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed loading preview texture image %s", path, exc_info=True)
        return None

    try:
        if image_name:
            image.name = str(image_name)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("[PKA-MESH-001] Planetka: failed setting preview image name", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("[PKA-MESH-001] Planetka: failed setting preview image name", exc_info=True)

    _set_image_colorspace_safe(image, colorspace)
    return image


def _preview_texture_static_path(file_name):
    return os.path.join(
        os.path.dirname(__file__),
        "Resources",
        "Preview Textures",
        str(file_name),
    )


def _resolve_preview_texture_path(folder, file_name):
    safe_folder = str(folder or "").strip()
    safe_name = str(file_name or "").strip()
    if not safe_folder or not safe_name:
        return ""
    local_path = _preview_texture_static_path(safe_name)
    return local_path if os.path.isfile(local_path) else ""


def _assign_preview_texture_images(preview_material):
    if not preview_material or getattr(preview_material, "node_tree", None) is None:
        return
    node_tree = getattr(preview_material, "node_tree", None)
    if node_tree is None:
        return

    loading_group = None
    loading_node = node_tree.nodes.get("Planetka Textures Loading")
    if loading_node is not None and getattr(loading_node, "bl_idname", "") == "ShaderNodeGroup":
        loading_group = getattr(loading_node, "node_tree", None)

    for folder, file_name, colorspace, node_names in _PREVIEW_STATIC_BINDINGS:
        path = _resolve_preview_texture_path(folder, file_name)
        if not path:
            continue
        image = _load_preview_image(path, image_name=file_name, colorspace=colorspace)
        if image is None:
            continue
        for node_name in node_names:
            tex_node = node_tree.nodes.get(node_name)
            if tex_node is not None and getattr(tex_node, "bl_idname", "") == "ShaderNodeTexImage":
                tex_node.image = image
            if loading_group is None:
                continue
            loading_tex_node = loading_group.nodes.get(node_name)
            if loading_tex_node is not None and getattr(loading_tex_node, "bl_idname", "") == "ShaderNodeTexImage":
                loading_tex_node.image = image


def _surface_local_radius(parent_surface):
    if parent_surface is None:
        return 1.0
    try:
        stored = float(parent_surface.get("planetka_surface_local_radius", 0.0))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        stored = 0.0
    if stored > 1e-9:
        return float(stored)

    mesh = getattr(parent_surface, "data", None)
    vertices = getattr(mesh, "vertices", None)
    if vertices:
        try:
            inferred = max(float(v.co.length) for v in vertices)
            if inferred > 1e-9:
                return float(inferred)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed inferring surface extent for preview scale", exc_info=True)
    return 1.0


def _object_dimensions_tuple(obj):
    if obj is None:
        return None
    try:
        dimensions = tuple(float(value) for value in obj.dimensions)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed reading existing surface dimensions", exc_info=True)
        return None
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed reading existing surface dimensions", exc_info=True)
        return None
    if len(dimensions) != 3:
        return None
    if any(value <= 1e-9 for value in dimensions):
        return None
    return dimensions


def _local_dimensions_from_object_dimensions(dimensions, scale):
    if dimensions is None or scale is None:
        return None
    try:
        local_dimensions = tuple(
            float(dimension) / max(abs(float(scale_value)), 1e-9)
            for dimension, scale_value in zip(dimensions, scale)
        )
    except (RuntimeError, TypeError, ValueError, AttributeError, ZeroDivisionError):
        logger.debug("Planetka: failed computing preserved Earth Surface local dimensions", exc_info=True)
        return None
    if len(local_dimensions) != 3:
        return None
    if any(value <= 1e-9 for value in local_dimensions):
        return None
    return local_dimensions


def _add_mesh_bounds_reference_vertices(mesh, local_dimensions):
    if mesh is None or local_dimensions is None:
        return False
    try:
        half_x = float(local_dimensions[0]) * 0.5
        half_y = float(local_dimensions[1]) * 0.5
        half_z = float(local_dimensions[2]) * 0.5
        # Loose vertices keep Blender's object Dimensions stable without
        # changing the rendered, tile-clipped surface faces.
        base_count = len(getattr(mesh, "vertices", ()) or ())
        mesh.vertices.add(8)
        coords = (
            (-half_x, -half_y, -half_z),
            (-half_x, -half_y, half_z),
            (-half_x, half_y, -half_z),
            (-half_x, half_y, half_z),
            (half_x, -half_y, -half_z),
            (half_x, -half_y, half_z),
            (half_x, half_y, -half_z),
            (half_x, half_y, half_z),
        )
        for offset, coord in enumerate(coords):
            mesh.vertices[base_count + offset].co = coord
        mesh.update()
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed adding Earth Surface bounds reference vertices", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed adding Earth Surface bounds reference vertices", exc_info=True)
    return False


def _preserve_object_scale_and_dimensions(obj, scale, dimensions):
    if obj is None:
        return False
    local_dimensions = _local_dimensions_from_object_dimensions(dimensions, scale)
    try:
        obj.scale = scale
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed preserving Earth Surface scale", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed preserving Earth Surface scale", exc_info=True)
    changed = _add_mesh_bounds_reference_vertices(getattr(obj, "data", None), local_dimensions)
    try:
        bpy.context.view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed updating preserved Earth Surface transform", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed updating preserved Earth Surface transform", exc_info=True)
    return bool(changed)


def _mesh_local_radius(mesh):
    vertices = getattr(mesh, "vertices", None)
    if not vertices:
        return 0.0
    try:
        return max(float(v.co.length) for v in vertices)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed inferring preview mesh extent", exc_info=True)
    return 0.0


def _sync_preview_mesh_radius(preview_obj, target_radius):
    if preview_obj is None:
        return
    mesh = getattr(preview_obj, "data", None)
    if mesh is None:
        return
    current_radius = _mesh_local_radius(mesh)
    target = max(1e-6, float(target_radius))
    if current_radius <= 1e-9:
        return
    ratio = float(target) / float(current_radius)
    if abs(ratio - 1.0) <= 1e-9:
        return
    try:
        mesh.transform(Matrix.Scale(float(ratio), 4))
        mesh.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed syncing preview mesh radius", exc_info=True)


def ensure_preview_object(parent_surface):
    if not parent_surface or getattr(parent_surface, "type", None) != 'MESH':
        return None

    preview = bpy.data.objects.get(PREVIEW_OBJECT_NAME)
    if preview and getattr(preview, "type", None) != 'MESH':
        _remove_object_and_unused_mesh(preview)
        preview = None

    if preview is None or not _is_valid_preview_mesh(getattr(preview, "data", None)):
        if preview:
            _remove_object_and_unused_mesh(preview)
        preview = _create_preview_object()

    preview_material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)
    if not preview_material:
        raise RuntimeError(f"Planetka: material '{PREVIEW_MATERIAL_NAME}' not found.")
    _assign_preview_texture_images(preview_material)

    preview.data.materials.clear()
    preview.data.materials.append(preview_material)
    for poly in preview.data.polygons:
        poly.material_index = 0
    apply_smooth_shading(preview.data)

    _remove_subsurf_modifiers(preview)

    target_collections = list(parent_surface.users_collection)
    if not target_collections:
        surface_collection = ensure_surface_collection()
        if surface_collection:
            target_collections = [surface_collection]
    _set_object_collections(preview, target_collections)

    preview.parent = parent_surface
    preview.matrix_parent_inverse = Matrix.Identity(4)
    preview.location = (0.0, 0.0, 0.0)
    preview.rotation_euler = (0.0, 0.0, 0.0)
    _sync_preview_mesh_radius(preview, _surface_local_radius(parent_surface))
    preview.scale = (PREVIEW_SCALE_FACTOR, PREVIEW_SCALE_FACTOR, PREVIEW_SCALE_FACTOR)
    # Preview sphere is viewport-only and must never appear in final renders.
    preview.hide_render = True
    preview.hide_viewport = False
    try:
        preview.display_type = 'TEXTURED'
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-MESH-009", "Failed setting preview object display type")

    return preview


def apply_smooth_shading(mesh):
    poly_count = len(mesh.polygons)
    if poly_count == 0:
        return
    try:
        mesh.polygons.foreach_set("use_smooth", [True] * poly_count)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        for poly in mesh.polygons:
            poly.use_smooth = True


def parse_tile(tile):
    match = TILE_RE.match(str(tile or ""))
    if not match:
        return None
    x, y, z, d = map(int, match.groups())
    if d == 0:
        d = 1440
    return x, y, z, d


def compute_faces_to_delete_indices(mesh, coverage):
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        return []

    poly_count = len(mesh.polygons)
    if poly_count == 0:
        return []

    loops_len = len(mesh.loops)
    uvs = [0.0] * (2 * loops_len)
    uv_layer.data.foreach_get("uv", uvs)

    loop_starts = [0] * poly_count
    loop_totals = [0] * poly_count
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)

    faces_to_delete = []
    for i in range(poly_count):
        start = loop_starts[i]
        total = loop_totals[i]
        if total <= 0:
            continue

        idx = start * 2
        u_total = 0.0
        v_total = 0.0
        for _ in range(total):
            u_total += uvs[idx]
            v_total += uvs[idx + 1]
            idx += 2

        lon = int((u_total / total) * 360.0) % 360
        lat = int((v_total / total) * 180.0)
        if lat < 0:
            lat = 0
        elif lat > 179:
            lat = 179
        if not coverage[lon][lat]:
            faces_to_delete.append(i)
    return faces_to_delete


def create_temp_mesh_for_all_tiles(tiles, name="Planetka Earth Surface", collection_policy="preserve_surface"):
    # --- Sphere Creation (common to both paths) ---
    existing_surface = get_earth_object() or bpy.data.objects.get("Planetka Earth Surface")
    location = (0.0, 0.0, 0.0)
    rotation = (0.0, 0.0, 0.0)
    scale = EARTH_SURFACE_DEFAULT_SCALE
    local_radius = EARTH_SURFACE_DEFAULT_RADIUS
    target_dimensions = None

    if existing_surface and getattr(existing_surface, "type", None) == 'MESH':
        location = tuple(existing_surface.location)
        rotation = tuple(existing_surface.rotation_euler)
        scale = tuple(existing_surface.scale)
        target_dimensions = _object_dimensions_tuple(existing_surface)
        # Keep the base sphere extent stable across resolve rebuilds.
        # Re-inferring from the visible subset of vertices can introduce tiny
        # frame-to-frame drift when segment tile coverage changes.
        try:
            stable_radius = float(_surface_local_radius(existing_surface))
            if stable_radius > 1e-6:
                local_radius = float(stable_radius)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed reading stable sphere extent from existing surface", exc_info=True)

    surface_col = ensure_surface_collection()
    temp = create_uv_sphere(local_radius, location, rotation, name=name)
    temp.scale = scale

    existing_surface_collections = []
    if existing_surface and getattr(existing_surface, "type", None) == 'MESH':
        existing_surface_collections = list(existing_surface.users_collection)
        generated_mesh = temp.data
        try:
            preserved_obj = existing_surface.copy()
            preserved_obj.data = generated_mesh
            preserved_obj.name = name

            target_collections = []
            if collection_policy == "surface_only":
                if surface_col:
                    target_collections = [surface_col]
            elif collection_policy == "preserve_surface":
                target_collections = list(existing_surface_collections)
                if not target_collections and surface_col:
                    target_collections = [surface_col]
            else:
                target_collections = [surface_col] if surface_col else []

            _set_object_collections(preserved_obj, target_collections)

            _remove_object_and_unused_mesh(temp)
            temp = preserved_obj
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed preserving surface object state", exc_info=True)

    if collection_policy == "surface_only":
        if surface_col:
            _set_object_collections(temp, [surface_col])
    elif existing_surface_collections:
        _set_object_collections(temp, existing_surface_collections)
    elif surface_col and not temp.users_collection:
        _set_object_collections(temp, [surface_col])

    temp.hide_render = False
    temp.hide_viewport = False
    try:
        temp["planetka_surface_local_radius"] = float(local_radius)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing surface extent metadata", exc_info=True)

    planetka_surface = bpy.data.materials.get("Planetka Earth Material")
    if not planetka_surface:
        raise RuntimeError("Planetka: Material 'Planetka Earth Material' not found")
    temp.data.materials.clear()
    temp.data.materials.append(planetka_surface)
    for poly in temp.data.polygons:
        poly.material_index = 0

    mesh = temp.data
    coverage = [[False] * 180 for _ in range(360)]
    for tile in tiles:
        parsed = parse_tile(tile)
        if not parsed:
            continue
        x, y, z, _d = parsed
        for lon in range(x, x + z):
            lon_mod = lon % 360
            for lat in range(y, y + z):
                if 0 <= lat < 180:
                    coverage[lon_mod][lat] = True

    if not mesh.uv_layers or not mesh.uv_layers.active:
        logger.warning("Planetka: no UV map found on Earth surface mesh")
    else:
        faces_to_delete_idx = compute_faces_to_delete_indices(mesh, coverage)
        if faces_to_delete_idx:
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bm.faces.ensure_lookup_table()
            faces_to_delete = [bm.faces[i] for i in faces_to_delete_idx if i < len(bm.faces)]
            if faces_to_delete:
                bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
            bm.to_mesh(mesh)
            bm.free()
            mesh.update()

    apply_smooth_shading(temp.data)

    # --- Modifiers (common to both paths) ---
    try:
        existing_cull = temp.modifiers.get(SURFACE_CULL_MOD_NAME)
        if existing_cull:
            temp.modifiers.remove(existing_cull)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing obsolete surface cull modifier", exc_info=True)

    subsurf_mod = temp.modifiers.get("Adaptive Subdivision")
    if subsurf_mod is None or subsurf_mod.type != 'SUBSURF':
        if subsurf_mod and subsurf_mod.type != 'SUBSURF':
            try:
                temp.modifiers.remove(subsurf_mod)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-MESH-010", "Failed removing non-subsurf modifier named Adaptive Subdivision")
        subsurf_mod = temp.modifiers.new(name="Adaptive Subdivision", type='SUBSURF')
    _set_enum_property_safe(subsurf_mod, "subdivision_type", ("CATMULL_CLARK", "SIMPLE"))
    # Testing profile: keep subdivision levels at 0/0 to minimize EEVEE sampler
    # pressure and viewport memory usage on wide-coverage shots.
    subsurf_mod.levels = 0
    subsurf_mod.render_levels = 0
    _enable_adaptive_subdivision(temp, subsurf_mod)
    subsurf_mod.show_render = True
    subsurf_mod.show_viewport = True
    if hasattr(subsurf_mod, "dicing_rate"):
        subsurf_mod.dicing_rate = 1.0
    if hasattr(subsurf_mod, "use_limit_surface"):
        subsurf_mod.use_limit_surface = False
    if hasattr(subsurf_mod, "quality"):
        subsurf_mod.quality = 3
    _set_enum_property_safe(
        subsurf_mod,
        "uv_smooth",
        ("ALL", "SMOOTH_ALL", "PRESERVE_BOUNDARIES", "KEEP_BOUNDARIES", "PRESERVE_CORNERS"),
    )
    _set_enum_property_safe(
        subsurf_mod,
        "boundary_smooth",
        ("KEEP_CORNERS", "PRESERVE_CORNERS"),
    )
    _warn_if_adaptive_enum_fallback(subsurf_mod)
    if hasattr(subsurf_mod, "use_creases"):
        subsurf_mod.use_creases = False
    if hasattr(subsurf_mod, "use_custom_normals"):
        subsurf_mod.use_custom_normals = False

    _preserve_object_scale_and_dimensions(temp, scale, target_dimensions)

    return temp
