import bpy
import re
import bmesh
import logging
import hashlib
from collections import OrderedDict
from mathutils import Matrix
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object

# Precompile regex for speed
TILE_RE = re.compile(r"x(\d+)_y(\d+)_z(\d+)_d(\d+)")

logger = logging.getLogger(__name__)


SURFACE_CULL_MOD_NAME = "Camera Cull Surface"
SURFACE_COLLECTION_NAME = "Planetka - Earth Surface Collection"
EARTH_SURFACE_DEFAULT_RADIUS = 1.0
EARTH_SURFACE_DEFAULT_SCALE = (2.0, 2.0, 2.0)
BASE_SPHERE_CACHE_MESH_NAME = "Planetka__BaseSphereMeshCache_v1"
BASE_SPHERE_CACHE_MIN_VERTS = 10000
RESOLVED_MESH_CACHE_PREFIX = "Planetka__ResolvedMeshCache_v1__"
RESOLVED_MESH_CACHE_MAX_ENTRIES = 0
FACE_TILE_CACHE_VERSION = 1
FACE_TILE_CACHE_VERSION_KEY = "planetka_face_tile_cache_version"
FACE_TILE_LON_ATTR_NAME = "planetka_face_lon"
FACE_TILE_LAT_ATTR_NAME = "planetka_face_lat"
PREVIEW_OBJECT_NAME = "Planetka Preview Object"
PREVIEW_MATERIAL_NAME = "Planetka Preview Material"
PREVIEW_SEGMENTS = 36
PREVIEW_RING_COUNT = 18
PREVIEW_SCALE_FACTOR = 0.999
_RESOLVED_MESH_CACHE = OrderedDict()
_RESOLVED_CACHE_CLEANED = False
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
            pass

    obj_cycles = getattr(obj, "cycles", None) if obj is not None else None
    if obj_cycles is not None:
        if hasattr(obj_cycles, "use_adaptive_subdivision"):
            try:
                obj_cycles.use_adaptive_subdivision = True
                adaptive_enabled = adaptive_enabled or bool(
                    getattr(obj_cycles, "use_adaptive_subdivision", False)
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
        if hasattr(obj_cycles, "dicing_rate"):
            try:
                obj_cycles.dicing_rate = 1.0
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
        if hasattr(obj_cycles, "preview_dicing_rate"):
            try:
                obj_cycles.preview_dicing_rate = 1.0
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass

    return adaptive_enabled


def parse_tile(tile):
    m = TILE_RE.match(tile)
    if not m:
        return None
    x, y, z, d = map(int, m.groups())
    if d == 0:
        d = 1440
    return x, y, z, d


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
            pass
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


def _is_valid_resolved_mesh(mesh_data):
    if mesh_data is None:
        return False
    if len(getattr(mesh_data, "vertices", ())) == 0:
        return False
    if len(getattr(mesh_data, "polygons", ())) == 0:
        return False
    uv_layers = getattr(mesh_data, "uv_layers", None)
    if uv_layers is None or len(uv_layers) == 0:
        return False
    return True


def _cleanup_all_resolved_mesh_cache_datablocks_once():
    global _RESOLVED_CACHE_CLEANED
    if _RESOLVED_CACHE_CLEANED:
        return
    _RESOLVED_CACHE_CLEANED = True
    for mesh_data in list(getattr(bpy.data, "meshes", ())):
        if not str(getattr(mesh_data, "name", "")).startswith(RESOLVED_MESH_CACHE_PREFIX):
            continue
        try:
            if int(getattr(mesh_data, "users", 0)) == 0:
                bpy.data.meshes.remove(mesh_data)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed cleaning stale resolved mesh cache datablock", exc_info=True)


def _normalized_tile_cache_key(tiles, local_radius):
    normalized = []
    for tile in (tiles or ()):
        parsed = parse_tile(str(tile))
        if not parsed:
            continue
        x, y, z, d = parsed
        normalized.append(f"x{x:03d}_y{y:03d}_z{z:03d}_d{d:03d}")
    normalized.sort()
    payload = ",".join(normalized)
    return f"r{float(local_radius):.9f}|{payload}"


def _resolved_mesh_cache_name(cache_key):
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:20]
    return f"{RESOLVED_MESH_CACHE_PREFIX}{digest}"


def _prune_resolved_mesh_cache():
    while len(_RESOLVED_MESH_CACHE) > RESOLVED_MESH_CACHE_MAX_ENTRIES:
        _, mesh_name = _RESOLVED_MESH_CACHE.popitem(last=False)
        mesh_data = bpy.data.meshes.get(mesh_name)
        if mesh_data is None:
            continue
        try:
            if int(getattr(mesh_data, "users", 0)) == 0:
                bpy.data.meshes.remove(mesh_data)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed pruning resolved mesh cache entry", exc_info=True)


def _get_cached_resolved_mesh(tiles, local_radius):
    if RESOLVED_MESH_CACHE_MAX_ENTRIES <= 0:
        return None
    cache_key = _normalized_tile_cache_key(tiles, local_radius)
    mesh_name = _RESOLVED_MESH_CACHE.get(cache_key)
    if not mesh_name:
        return None

    mesh_data = bpy.data.meshes.get(mesh_name)
    if not _is_valid_resolved_mesh(mesh_data):
        _RESOLVED_MESH_CACHE.pop(cache_key, None)
        return None

    _RESOLVED_MESH_CACHE.move_to_end(cache_key)
    return mesh_data


def _store_resolved_mesh_cache(tiles, local_radius, mesh_data):
    if RESOLVED_MESH_CACHE_MAX_ENTRIES <= 0:
        return
    if not _is_valid_resolved_mesh(mesh_data):
        return

    cache_key = _normalized_tile_cache_key(tiles, local_radius)
    mesh_name = _RESOLVED_MESH_CACHE.get(cache_key)
    existing = bpy.data.meshes.get(mesh_name) if mesh_name else None
    if _is_valid_resolved_mesh(existing):
        _RESOLVED_MESH_CACHE.move_to_end(cache_key)
        return

    cached_copy = mesh_data.copy()
    cached_copy.name = _resolved_mesh_cache_name(cache_key)
    cached_copy.use_fake_user = False
    _RESOLVED_MESH_CACHE[cache_key] = cached_copy.name
    _RESOLVED_MESH_CACHE.move_to_end(cache_key)
    _prune_resolved_mesh_cache()


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

    try:
        _ensure_face_tile_lookup(cache_mesh)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed precomputing face-tile lookup cache", exc_info=True)

    return cache_mesh


def ensure_base_sphere_mesh_cache():
    _cleanup_all_resolved_mesh_cache_datablocks_once()
    cache_mesh = bpy.data.meshes.get(BASE_SPHERE_CACHE_MESH_NAME)
    if _is_valid_base_sphere_mesh(cache_mesh):
        return cache_mesh

    if cache_mesh is not None:
        try:
            bpy.data.meshes.remove(cache_mesh)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed removing invalid base sphere cache mesh", exc_info=True)

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


def _create_object_from_mesh_data(mesh_data, name, location, rotation):
    scene = getattr(bpy.context, "scene", None)
    if scene is None or mesh_data is None:
        return None
    obj = bpy.data.objects.new(name, mesh_data)
    scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = rotation
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
    preview.scale = (PREVIEW_SCALE_FACTOR, PREVIEW_SCALE_FACTOR, PREVIEW_SCALE_FACTOR)
    preview.hide_render = False
    preview.hide_viewport = False
    try:
        preview.display_type = 'TEXTURED'
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
        pass

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


def _remove_attribute_if_exists(mesh, attr_name):
    attributes = getattr(mesh, "attributes", None)
    if not attributes:
        return
    attr = attributes.get(attr_name)
    if attr is None:
        return
    try:
        attributes.remove(attr)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing mesh attribute %s", attr_name, exc_info=True)


def _read_face_tile_lookup(mesh):
    attributes = getattr(mesh, "attributes", None)
    if not attributes:
        return None

    poly_count = len(mesh.polygons)
    if poly_count == 0:
        return None

    version = int(mesh.get(FACE_TILE_CACHE_VERSION_KEY, 0))
    if version != FACE_TILE_CACHE_VERSION:
        return None

    lon_attr = attributes.get(FACE_TILE_LON_ATTR_NAME)
    lat_attr = attributes.get(FACE_TILE_LAT_ATTR_NAME)
    if lon_attr is None or lat_attr is None:
        return None
    if lon_attr.domain != 'FACE' or lat_attr.domain != 'FACE':
        return None
    if lon_attr.data_type != 'INT' or lat_attr.data_type != 'INT':
        return None
    if len(lon_attr.data) != poly_count or len(lat_attr.data) != poly_count:
        return None

    lon_values = [0] * poly_count
    lat_values = [0] * poly_count
    lon_attr.data.foreach_get("value", lon_values)
    lat_attr.data.foreach_get("value", lat_values)
    return lon_values, lat_values


def _build_face_tile_lookup(mesh):
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        return False

    poly_count = len(mesh.polygons)
    if poly_count == 0:
        return False

    loops_len = len(mesh.loops)
    uvs = [0.0] * (2 * loops_len)
    uv_layer.data.foreach_get("uv", uvs)

    loop_starts = [0] * poly_count
    loop_totals = [0] * poly_count
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)

    lon_values = [0] * poly_count
    lat_values = [0] * poly_count
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
        u = u_total / total
        v = v_total / total
        lon = int(u * 360.0) % 360
        lat = int(v * 180.0)
        if lat < 0:
            lat = 0
        elif lat > 179:
            lat = 179
        lon_values[i] = lon
        lat_values[i] = lat

    attributes = getattr(mesh, "attributes", None)
    if not attributes:
        return False

    _remove_attribute_if_exists(mesh, FACE_TILE_LON_ATTR_NAME)
    _remove_attribute_if_exists(mesh, FACE_TILE_LAT_ATTR_NAME)

    lon_attr = attributes.new(name=FACE_TILE_LON_ATTR_NAME, type='INT', domain='FACE')
    lat_attr = attributes.new(name=FACE_TILE_LAT_ATTR_NAME, type='INT', domain='FACE')
    lon_attr.data.foreach_set("value", lon_values)
    lat_attr.data.foreach_set("value", lat_values)
    mesh[FACE_TILE_CACHE_VERSION_KEY] = FACE_TILE_CACHE_VERSION
    return True


def _ensure_face_tile_lookup(mesh):
    cached = _read_face_tile_lookup(mesh)
    if cached is not None:
        return cached
    if not _build_face_tile_lookup(mesh):
        return None
    return _read_face_tile_lookup(mesh)


def compute_faces_to_delete_indices(mesh, coverage):
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        return []

    poly_count = len(mesh.polygons)
    if poly_count == 0:
        return []

    # Mark smooth shading in bulk
    try:
        mesh.polygons.foreach_set("use_smooth", [True] * poly_count)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        for poly in mesh.polygons:
            poly.use_smooth = True

    try:
        cached_lookup = _ensure_face_tile_lookup(mesh)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        cached_lookup = None
    if cached_lookup is not None:
        lon_values, lat_values = cached_lookup
        return [
            i
            for i in range(poly_count)
            if not coverage[lon_values[i]][lat_values[i]]
        ]

    # Fallback (should be rare): compute directly from UV loops.
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
        u = u_total / total
        v = v_total / total

        lon = int(u * 360.0) % 360
        lat = int(v * 180.0)
        if lat < 0:
            lat = 0
        elif lat > 179:
            lat = 179
        if not coverage[lon][lat]:
            faces_to_delete.append(i)
    return faces_to_delete


def create_temp_mesh_for_all_tiles(tiles, name="Planetka Earth Surface", collection_policy="inherit_old"):
    # --- Sphere Creation (common to both paths) ---
    existing_surface = get_earth_object() or bpy.data.objects.get("Planetka Earth Surface")
    location = (0.0, 0.0, 0.0)
    rotation = (0.0, 0.0, 0.0)
    scale = EARTH_SURFACE_DEFAULT_SCALE
    local_radius = EARTH_SURFACE_DEFAULT_RADIUS

    if existing_surface and getattr(existing_surface, "type", None) == 'MESH':
        location = tuple(existing_surface.location)
        rotation = tuple(existing_surface.rotation_euler)
        scale = tuple(existing_surface.scale)
        mesh_data = getattr(existing_surface, "data", None)
        if mesh_data and hasattr(mesh_data, "vertices") and len(mesh_data.vertices) > 0:
            try:
                inferred_radius = max(v.co.length for v in mesh_data.vertices)
                if inferred_radius > 1e-6:
                    local_radius = float(inferred_radius)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed inferring local sphere radius from old mesh", exc_info=True)

    cached_resolved_mesh = _get_cached_resolved_mesh(tiles, local_radius)
    surface_col = ensure_surface_collection()
    if cached_resolved_mesh is not None:
        temp_mesh = cached_resolved_mesh.copy()
        temp_mesh.use_fake_user = False
        temp = _create_object_from_mesh_data(temp_mesh, name=name, location=location, rotation=rotation)
        if temp is None:
            raise RuntimeError("Failed to create Earth surface from cached resolved mesh")
    else:
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
            else:
                target_collections = list(existing_surface_collections)
                if not target_collections and surface_col:
                    target_collections = [surface_col]

            _set_object_collections(preserved_obj, target_collections)

            _remove_object_and_unused_mesh(temp)
            temp = preserved_obj
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed preserving old surface object state", exc_info=True)

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
        logger.debug("Planetka: failed storing surface local radius", exc_info=True)

    planetka_surface = bpy.data.materials.get("Planetka Earth Material")
    if not planetka_surface:
        raise RuntimeError("Planetka: Material 'Planetka Earth Material' not found")

    temp.data.materials.clear()
    temp.data.materials.append(planetka_surface)
    for poly in temp.data.polygons:
        poly.material_index = 0

    mesh = temp.data
    if cached_resolved_mesh is None:
        # --- Conditional Face Deletion ---
        # Build coverage grid (lon 0-359, lat 0-179)
        coverage = [[False] * 180 for _ in range(360)]
        for t in tiles:
            p = parse_tile(t)
            if not p:
                continue
            x, y, z, _ = p
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

    apply_smooth_shading(temp.data)
    if cached_resolved_mesh is None:
        _store_resolved_mesh_cache(tiles, local_radius, temp.data)

    # --- Modifiers (common to both paths) ---
    try:
        existing_cull = temp.modifiers.get(SURFACE_CULL_MOD_NAME)
        if existing_cull:
            temp.modifiers.remove(existing_cull)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed removing legacy surface cull modifier", exc_info=True)

    subsurf_mod = temp.modifiers.get("Adaptive Subdivision")
    if subsurf_mod is None or subsurf_mod.type != 'SUBSURF':
        if subsurf_mod and subsurf_mod.type != 'SUBSURF':
            try:
                temp.modifiers.remove(subsurf_mod)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
        subsurf_mod = temp.modifiers.new(name="Adaptive Subdivision", type='SUBSURF')
    _set_enum_property_safe(subsurf_mod, "subdivision_type", ("CATMULL_CLARK",))
    subsurf_mod.levels = 1
    subsurf_mod.render_levels = 1
    _enable_adaptive_subdivision(temp, subsurf_mod)
    subsurf_mod.show_render = True
    subsurf_mod.show_viewport = True
    if hasattr(subsurf_mod, "dicing_rate"):
        subsurf_mod.dicing_rate = 1.0
    if hasattr(subsurf_mod, "use_limit_surface"):
        subsurf_mod.use_limit_surface = False
    if hasattr(subsurf_mod, "quality"):
        subsurf_mod.quality = 1
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

    return temp
