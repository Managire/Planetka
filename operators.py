import bpy
import importlib
import math
import os
import re
import shutil
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Quaternion, Vector

from .asset_builder import ensure_planetka_assets
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import (
    get_earth_object,
    get_prefs,
    mark_earth_object,
    read_saved_locations,
    write_saved_locations,
)
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .render_prep import FORCE_EMPTY_RESOLVE_ONCE_KEY
from .sanity_utils import _normalize_texture_source_path, invalidate_texture_source_health_cache
from .state import (
    _apply_fake_atmosphere_from_props,
    _initialize_props_from_imported_planetka,
    _sync_idprops_from_props,
    delete_temp_meshes,
    ensure_preview_object,
    ensure_planetka_temp_collection,
    logger,
    remove_object_and_unused_mesh,
    resume_navigation_shot_updates,
    suspend_navigation_shot_updates,
    warm_base_sphere_mesh_cache,
)

_IMPORT_TEXTURE_EXTENSIONS = {
    "S2": ".exr",
    "EL": ".exr",
    "WT": ".exr",
    "PO": ".tif",
}
_IMPORT_TILE_FILENAME_RE = re.compile(
    r"^(S2|EL|WT|PO)_x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})\.(exr|tif)$",
    re.IGNORECASE,
)


def _validate_create_earth_texture_source(base_path):
    normalized = _normalize_texture_source_path(base_path)
    if not normalized:
        return "", "Texture source directory is not set."

    if not os.path.isdir(normalized):
        return "", f"Texture source directory is not a valid path: {normalized}"

    required_folders = ("S2", "EL", "WT", "PO")
    missing = [name for name in required_folders if not os.path.isdir(os.path.join(normalized, name))]
    if missing:
        return "", (
            "Texture source is invalid: missing required folder(s): "
            + ", ".join(missing)
        )

    s2_dir = os.path.join(normalized, "S2")
    try:
        has_s2_exr = any(
            entry.lower().endswith(".exr") and os.path.isfile(os.path.join(s2_dir, entry))
            for entry in os.listdir(s2_dir)
        )
    except (OSError, TypeError, ValueError):
        has_s2_exr = False
    if not has_s2_exr:
        return "", "Texture source is invalid: folder 'S2' must contain at least one .exr file."

    return normalized, ""


def _paths_equivalent(path_a, path_b):
    if not path_a or not path_b:
        return False
    try:
        return os.path.samefile(path_a, path_b)
    except (OSError, TypeError, ValueError, AttributeError):
        a = os.path.normcase(os.path.realpath(path_a))
        b = os.path.normcase(os.path.realpath(path_b))
        return a == b


def _canonical_import_filename(texture_type, x_code, y_code, z_code, d_code):
    texture_prefix = str(texture_type).upper()
    ext = _IMPORT_TEXTURE_EXTENSIONS.get(texture_prefix)
    if not ext:
        return None
    return (
        f"{texture_prefix}_x{int(x_code):03d}_y{int(y_code):03d}_z{int(z_code):03d}_d{int(d_code):03d}{ext}"
    )


def _collect_import_sources(source_directory):
    by_canonical_name = {}
    duplicates_skipped = 0

    for root, _dirs, files in os.walk(source_directory):
        for filename in files:
            match = _IMPORT_TILE_FILENAME_RE.match(filename or "")
            if not match:
                continue

            texture_type = str(match.group(1)).upper()
            extension = "." + str(match.group(6)).lower()
            expected_ext = _IMPORT_TEXTURE_EXTENSIONS.get(texture_type)
            if expected_ext != extension:
                continue

            canonical_name = _canonical_import_filename(
                texture_type=texture_type,
                x_code=match.group(2),
                y_code=match.group(3),
                z_code=match.group(4),
                d_code=match.group(5),
            )
            if not canonical_name:
                continue

            source_path = os.path.join(root, filename)
            existing = by_canonical_name.get(canonical_name)
            if existing is None:
                by_canonical_name[canonical_name] = source_path
                continue

            duplicates_skipped += 1
            try:
                existing_mtime = os.path.getmtime(existing)
                current_mtime = os.path.getmtime(source_path)
                if current_mtime > existing_mtime:
                    by_canonical_name[canonical_name] = source_path
            except (OSError, TypeError, ValueError):
                continue

    return by_canonical_name, duplicates_skipped


def _build_texture_import_plan(source_directory, destination_directory):
    sources, duplicates_skipped = _collect_import_sources(source_directory)

    jobs = []
    new_file_count = 0
    update_file_count = 0
    added_size_bytes = 0

    for canonical_name in sorted(sources):
        source_path = sources[canonical_name]
        texture_type = canonical_name.split("_", 1)[0]
        destination_path = os.path.join(destination_directory, texture_type, canonical_name)

        if _paths_equivalent(source_path, destination_path):
            continue

        destination_exists = os.path.isfile(destination_path)
        try:
            file_size = int(os.path.getsize(source_path))
        except (OSError, TypeError, ValueError):
            file_size = 0

        if destination_exists:
            update_file_count += 1
        else:
            new_file_count += 1
            added_size_bytes += max(0, file_size)

        jobs.append({
            "source_path": source_path,
            "destination_path": destination_path,
        })

    return {
        "jobs": jobs,
        "new_file_count": new_file_count,
        "update_file_count": update_file_count,
        "added_size_bytes": max(0, int(added_size_bytes)),
        "duplicates_skipped": int(max(0, duplicates_skipped)),
    }


def _bytes_to_gb(size_bytes):
    return float(max(0, int(size_bytes))) / float(1000 ** 3)


def _prompt_texture_source_selection():
    if bool(getattr(bpy.app, "background", False)):
        return False

    try:
        result = bpy.ops.planetka.select_texture_source('INVOKE_DEFAULT')
        if "RUNNING_MODAL" in result:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    except (RuntimeError, TypeError, ValueError):
        pass

    module_name = __package__ or __name__
    try:
        bpy.ops.preferences.addon_show(module=module_name)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError):
        return False


def _persist_user_preferences():
    if bool(getattr(bpy.app, "background", False)):
        return True
    try:
        result = bpy.ops.wm.save_userpref()
        return "FINISHED" in result
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed saving user preferences", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed saving user preferences", exc_info=True)
        return False


def _ensure_close_clip_limits(scene, min_clip=0.001):
    camera_changed = False
    viewport_changed = False

    camera = getattr(scene, "camera", None) if scene else None
    if camera and getattr(camera, "type", None) == 'CAMERA':
        camera_data = getattr(camera, "data", None)
        if camera_data:
            try:
                current_clip = float(getattr(camera_data, "clip_start", min_clip))
                if current_clip > float(min_clip):
                    camera_data.clip_start = float(min_clip)
                    camera_changed = True
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

    wm = getattr(bpy.context, "window_manager", None)
    if wm:
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if not screen:
                continue
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if space.type != 'VIEW_3D':
                        continue
                    try:
                        current_clip = float(getattr(space, "clip_start", min_clip))
                        if current_clip > float(min_clip):
                            space.clip_start = float(min_clip)
                            viewport_changed = True
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        continue

    return camera_changed, viewport_changed


def _switch_solid_viewports_to_rendered(context):
    switched = False
    wm = getattr(context, "window_manager", None) if context else None
    if wm is None:
        return switched

    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type != 'VIEW_3D':
                    continue
                shading = getattr(space, "shading", None)
                if shading is None:
                    continue
                try:
                    if str(getattr(shading, "type", "")) == "SOLID":
                        shading.type = 'RENDERED'
                        switched = True
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                    continue
    return switched


def _create_placeholder_surface_object(scene):
    placeholder_mesh = bpy.data.meshes.new("Planetka Earth Surface Placeholder Mesh")
    obj = bpy.data.objects.new("Planetka Earth Surface", placeholder_mesh)
    scene.collection.objects.link(obj)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (2.0, 2.0, 2.0)
    obj["planetka_surface_local_radius"] = 1.0
    return obj


REAL_EARTH_RADIUS_M = 6371000.0
MAX_TERRAIN_HEIGHT_M = 9000.0
MAX_PROXIMITY_TARGET_SAFETY_RATIO = 1.08
DATASET_MPP_BASE_D1 = 10.0
FULL_GLOBE_EXTRA_MARGIN = 1.3
SHOT_ANCHOR_OBJECT_NAME = "Planetka Shot Anchor"
NAV_LAST_APPLIED_KEYS = {
    "lon": "planetka_nav_last_lon_deg",
    "lat": "planetka_nav_last_lat_deg",
    "alt": "planetka_nav_last_altitude_km",
    "heading": "planetka_nav_last_heading_deg",
    "tilt": "planetka_nav_last_tilt_deg",
    "roll": "planetka_nav_last_roll_deg",
}
NAV_CHANGE_EPS = 1e-6
NAV_D_LEVELS_BY_Z = {
    1: [1, 2, 4, 8, 15, 30, 60],
    2: [2, 4, 8, 15, 30, 60],
    4: [4, 8, 15, 30, 60],
    8: [8, 15, 30, 60],
    15: [15, 30, 60],
    30: [30, 60, 90, 180, 360],
    60: [60, 90, 180, 360],
    90: [90, 180, 360],
    180: [180, 360, 720],
    360: [360, 720, 1440],
}
_COVERAGE_MAP = None


def _read_last_navigation_values(scene):
    if scene is None:
        return None
    try:
        values = {
            "lon": float(scene.get(NAV_LAST_APPLIED_KEYS["lon"])),
            "lat": float(scene.get(NAV_LAST_APPLIED_KEYS["lat"])),
            "alt": float(scene.get(NAV_LAST_APPLIED_KEYS["alt"])),
            "heading": float(scene.get(NAV_LAST_APPLIED_KEYS["heading"])),
            "tilt": float(scene.get(NAV_LAST_APPLIED_KEYS["tilt"])),
            "roll": float(scene.get(NAV_LAST_APPLIED_KEYS["roll"])),
        }
        return values
    except (TypeError, ValueError, AttributeError):
        return None


def _store_last_navigation_values(scene, lon_deg, lat_deg, altitude_km, heading_deg, tilt_deg, roll_deg):
    if scene is None:
        return
    try:
        scene[NAV_LAST_APPLIED_KEYS["lon"]] = float(lon_deg)
        scene[NAV_LAST_APPLIED_KEYS["lat"]] = float(lat_deg)
        scene[NAV_LAST_APPLIED_KEYS["alt"]] = float(altitude_km)
        scene[NAV_LAST_APPLIED_KEYS["heading"]] = float(heading_deg)
        scene[NAV_LAST_APPLIED_KEYS["tilt"]] = float(tilt_deg)
        scene[NAV_LAST_APPLIED_KEYS["roll"]] = float(roll_deg)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    except (TypeError, ValueError, AttributeError):
        pass


def _get_coverage_map():
    global _COVERAGE_MAP
    if _COVERAGE_MAP is None:
        module_name = f"{__package__}.coverage" if __package__ else "coverage"
        module = importlib.import_module(module_name)
        _COVERAGE_MAP = getattr(module, "COVERAGE", {})
    return _COVERAGE_MAP


def _earth_radius_blender_units(earth_obj):
    if not earth_obj:
        return 1.0

    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0

    if stored_local_radius > 1e-9:
        world_scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
        return stored_local_radius * float(max_scale)

    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    if vertices:
        try:
            local_radius = max(v.co.length for v in vertices)
            if local_radius > 1e-9:
                world_scale = earth_obj.matrix_world.to_scale()
                max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
                return float(local_radius) * float(max_scale)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    scale = earth_obj.matrix_world.to_scale()
    return max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)


def _meters_per_blender_unit(earth_radius_bu):
    safe_radius = max(float(earth_radius_bu), 1e-9)
    return REAL_EARTH_RADIUS_M / safe_radius


def _km_to_bu(km_value, earth_radius_bu):
    return (float(km_value) * 1000.0) / _meters_per_blender_unit(earth_radius_bu)


def _bu_to_km(distance_bu, earth_radius_bu):
    return (float(distance_bu) * _meters_per_blender_unit(earth_radius_bu)) / 1000.0


def _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad):
    radius = float(max(1e-9, earth_radius_bu))
    safe_altitude_bu = max(0.0, float(altitude_bu))
    tilt_cos = math.cos(float(tilt_rad))

    root_term = max(
        0.0,
        (radius * radius * tilt_cos * tilt_cos) + (2.0 * radius * safe_altitude_bu) + (safe_altitude_bu * safe_altitude_bu),
    )
    anchor_distance = (-radius * tilt_cos) + math.sqrt(root_term)
    return max(1e-6, float(anchor_distance))


def _lon_lat_normal_local(lon_deg, lat_deg):
    lon = math.radians(float(lon_deg))
    lat = math.radians(float(lat_deg))
    cos_lat = math.cos(lat)
    return Vector((
        cos_lat * math.cos(lon),
        cos_lat * math.sin(lon),
        math.sin(lat),
    ))


def _camera_projection_info(scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    camera_data = getattr(camera, "data", None)
    if camera_data is None:
        return None

    render = scene.render
    scale = float(render.resolution_percentage) / 100.0
    res_x = max(1.0, float(render.resolution_x) * scale)
    res_y = max(1.0, float(render.resolution_y) * scale)

    camera_type = str(getattr(camera_data, "type", "PERSP"))
    if camera_type == "ORTHO":
        aspect = max(1e-9, res_x / max(1.0, res_y))
        return {
            "camera_type": camera_type,
            "h_fov": math.radians(50.0),
            "v_fov": math.radians(35.0),
            "ortho_scale": float(getattr(camera_data, "ortho_scale", 1.0)),
            "res_x": res_x,
            "res_y": res_y,
            "aspect": aspect,
        }

    return {
        "camera_type": camera_type,
        "h_fov": float(getattr(camera_data, "angle_x", math.radians(50.0))),
        "v_fov": float(getattr(camera_data, "angle_y", math.radians(35.0))),
        "ortho_scale": float(getattr(camera_data, "ortho_scale", 1.0)),
        "res_x": res_x,
        "res_y": res_y,
        "aspect": max(1e-9, res_x / max(1.0, res_y)),
    }


def _find_active_view3d_context_details():
    context = bpy.context
    window = getattr(context, "window", None)
    screen = getattr(window, "screen", None) if window else None
    area = getattr(context, "area", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(context, "region_data", None)
    region = getattr(context, "region", None)
    if (
        area is not None
        and area.type == 'VIEW_3D'
        and space is not None
        and space.type == 'VIEW_3D'
        and rv3d is not None
    ):
        if region is None or getattr(region, "type", "") != 'WINDOW':
            region = next((candidate for candidate in area.regions if candidate.type == 'WINDOW'), None)
        return {
            "window": window,
            "screen": screen,
            "area": area,
            "space": space,
            "region": region,
            "rv3d": rv3d,
        }

    wm = getattr(context, "window_manager", None)
    if not wm:
        return None
    for candidate_window in wm.windows:
        candidate_screen = getattr(candidate_window, "screen", None)
        if not candidate_screen:
            continue
        for candidate_area in candidate_screen.areas:
            if candidate_area.type != 'VIEW_3D':
                continue
            candidate_space = getattr(candidate_area.spaces, "active", None)
            if not candidate_space or candidate_space.type != 'VIEW_3D':
                continue
            candidate_rv3d = getattr(candidate_space, "region_3d", None)
            if candidate_rv3d is None:
                continue
            candidate_region = next(
                (candidate for candidate in candidate_area.regions if candidate.type == 'WINDOW'),
                None,
            )
            return {
                "window": candidate_window,
                "screen": candidate_screen,
                "area": candidate_area,
                "space": candidate_space,
                "region": candidate_region,
                "rv3d": candidate_rv3d,
            }
    return None


def _find_active_view3d_context():
    details = _find_active_view3d_context_details()
    if details is None:
        return None
    return details["area"], details["space"], details["rv3d"]


def _switch_viewport_to_camera_view(context, scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return False

    switched = False
    area = getattr(context, "area", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(context, "region_data", None)
    if (
        area is not None
        and area.type == 'VIEW_3D'
        and space is not None
        and space.type == 'VIEW_3D'
        and rv3d is not None
    ):
        try:
            if scene.camera is not camera:
                scene.camera = camera
            rv3d.view_perspective = 'CAMERA'
            switched = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            pass

    wm = getattr(context, "window_manager", None)
    if wm:
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if not screen:
                continue
            for candidate_area in screen.areas:
                if candidate_area.type != 'VIEW_3D':
                    continue
                candidate_space = getattr(candidate_area.spaces, "active", None)
                candidate_rv3d = getattr(candidate_space, "region_3d", None) if candidate_space else None
                if candidate_rv3d is None:
                    continue
                try:
                    if scene.camera is not camera:
                        scene.camera = camera
                    candidate_rv3d.view_perspective = 'CAMERA'
                    switched = True
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                    continue
    return switched


def _ray_sphere_hit_nearest(origin, direction, radius):
    a = float(direction.dot(direction))
    if a <= 1e-12:
        return None
    b = 2.0 * float(origin.dot(direction))
    c = float(origin.dot(origin)) - float(radius) * float(radius)
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    sqrt_disc = math.sqrt(disc)
    inv = 0.5 / a
    t0 = (-b - sqrt_disc) * inv
    t1 = (-b + sqrt_disc) * inv
    for t in (t0, t1):
        if t > 1e-6:
            return origin + direction * t
    return None


def _compute_current_view_navigation_values(scene):
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None

    active_view = _find_active_view3d_context()
    if active_view is not None:
        _area, _space, rv3d = active_view
        view_matrix = rv3d.view_matrix.inverted()
        cam_pos_world = view_matrix.translation.copy()
        cam_forward_world = (-view_matrix.col[2].xyz).normalized()
    else:
        camera = getattr(scene, "camera", None)
        if camera is None:
            return None
        matrix = camera.matrix_world
        cam_pos_world = matrix.translation.copy()
        cam_forward_world = (-matrix.col[2].xyz).normalized()

    center, rotation, _scale = earth_obj.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        return None
    cam_forward_local.normalize()

    earth_radius = _earth_radius_blender_units(earth_obj)
    hit_local = _ray_sphere_hit_nearest(cam_pos_local, cam_forward_local, earth_radius)
    if hit_local is None:
        return None

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    altitude_bu = max(0.0, float(cam_pos_local.length) - float(earth_radius))
    altitude_km = _bu_to_km(altitude_bu, earth_radius)
    return lat, lon, altitude_km


def _compute_scene_camera_navigation_values(scene):
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    cam_matrix = camera.matrix_world
    cam_pos_world = cam_matrix.translation.copy()
    cam_forward_world = (-cam_matrix.col[2].xyz).normalized()

    center, rotation, _scale = earth_obj.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        return None
    cam_forward_local.normalize()

    earth_radius = _earth_radius_blender_units(earth_obj)
    hit_local = _ray_sphere_hit_nearest(cam_pos_local, cam_forward_local, earth_radius)
    if hit_local is None:
        return None

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    altitude_bu = max(0.0, float(cam_pos_local.length) - float(earth_radius))
    altitude_km = _bu_to_km(altitude_bu, earth_radius)
    return lat, lon, altitude_km


def _tile_xy_for_lon_lat(lon_deg, lat_deg, z):
    lon_shift = (float(lon_deg) + 180.0) % 360.0
    lat_shift = max(0.0, min(179.999999, float(lat_deg) + 90.0))
    zf = float(z)
    x = int(lon_shift // zf) * int(zf)
    y = int(lat_shift // zf) * int(zf)
    return x % 360, max(0, min(179, y))


def _best_available_d_for_tile(base_path, x, y, z):
    normalized = _normalize_texture_source_path(base_path)
    if not normalized:
        return None

    s2_dir = os.path.join(normalized, "S2")
    if not os.path.isdir(s2_dir):
        return None

    d_candidates = sorted(set(NAV_D_LEVELS_BY_Z.get(int(z), [int(z)])))
    for d in d_candidates:
        d_code = 0 if int(d) == 1440 else int(d)
        file_name = f"S2_x{x:03d}_y{y:03d}_z{int(z):03d}_d{int(d_code):03d}.exr"
        if os.path.isfile(os.path.join(s2_dir, file_name)):
            return int(d)
    return None


def _finest_available_d_for_location(lon_deg, lat_deg, base_path):
    coverage = _get_coverage_map()
    for z in sorted(NAV_D_LEVELS_BY_Z.keys()):
        tiles = coverage.get(int(z), set())
        if not tiles:
            continue
        x, y = _tile_xy_for_lon_lat(lon_deg, lat_deg, z)
        if (x, y) not in tiles:
            continue
        exact_d = _best_available_d_for_tile(base_path, x, y, z)
        if exact_d is not None:
            return max(1, int(exact_d))
        return max(1, int(z))
    return 360


def _max_proximity_altitude_km(scene, earth_obj, earth_radius_bu, lon_deg, lat_deg):
    projection = _camera_projection_info(scene)
    if projection is None:
        return None, "Scene camera is required for navigation."

    if projection["camera_type"] == "ORTHO":
        center = earth_obj.matrix_world.translation
        cam_loc = scene.camera.matrix_world.translation
        altitude_bu = max(0.0, float((cam_loc - center).length) - float(earth_radius_bu))
        return _bu_to_km(altitude_bu, earth_radius_bu), (
            "Orthographic camera detected: altitude does not control detail; keeping current altitude."
        )

    prefs = get_prefs()
    base_path = getattr(prefs, "texture_base_path", "") if prefs else ""
    best_d = _finest_available_d_for_location(lon_deg, lat_deg, base_path)

    required_mpp_limit = (
        float(best_d)
        * DATASET_MPP_BASE_D1
        / max(1e-6, float(MAX_PROXIMITY_TARGET_SAFETY_RATIO))
    )
    px_angle = max(
        float(projection["h_fov"]) / max(1.0, float(projection["res_x"])),
        float(projection["v_fov"]) / max(1.0, float(projection["res_y"])),
    )
    px_angle = max(1e-9, float(px_angle))

    meters_per_bu = _meters_per_blender_unit(earth_radius_bu)
    effective_distance_bu = (required_mpp_limit / meters_per_bu) / (2.0 * math.tan(px_angle * 0.5))
    terrain_offset_bu = MAX_TERRAIN_HEIGHT_M / meters_per_bu
    altitude_bu = max(0.0, effective_distance_bu + terrain_offset_bu)
    return _bu_to_km(altitude_bu, earth_radius_bu), None


def _full_globe_altitude_km(scene, earth_radius_bu):
    projection = _camera_projection_info(scene)
    if projection is None:
        return None

    if projection["camera_type"] == "ORTHO":
        return None

    half_fov = min(float(projection["h_fov"]), float(projection["v_fov"])) * 0.5
    half_fov = max(1e-6, half_fov)
    center_distance_bu = (float(earth_radius_bu) * FULL_GLOBE_EXTRA_MARGIN) / math.sin(half_fov)
    altitude_bu = max(0.0, center_distance_bu - float(earth_radius_bu))
    return _bu_to_km(altitude_bu, earth_radius_bu)


def _ensure_ortho_full_globe_if_needed(scene, earth_radius_bu):
    camera = getattr(scene, "camera", None) if scene else None
    camera_data = getattr(camera, "data", None) if camera else None
    if not camera_data or str(getattr(camera_data, "type", "")) != "ORTHO":
        return False

    projection = _camera_projection_info(scene)
    if projection is None:
        return False

    aspect = max(1e-9, float(projection["aspect"]))
    margin_radius = float(earth_radius_bu) * FULL_GLOBE_EXTRA_MARGIN
    if aspect >= 1.0:
        needed_scale = 2.0 * margin_radius * aspect
    else:
        needed_scale = 2.0 * margin_radius / aspect

    try:
        if float(getattr(camera_data, "ortho_scale", 1.0)) < float(needed_scale):
            camera_data.ortho_scale = float(needed_scale)
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return False


def _navigate_camera_internal(scene, lon_deg, lat_deg, altitude_km, look_at_center=False):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    earth_center, earth_rot, _scale = earth_obj.matrix_world.decompose()
    earth_radius_bu = _earth_radius_blender_units(earth_obj)

    altitude_bu = _km_to_bu(max(0.0, float(altitude_km)), earth_radius_bu)
    normal_local = _lon_lat_normal_local(lon_deg, lat_deg)
    if normal_local.length_squared <= 1e-12:
        normal_local = Vector((1.0, 0.0, 0.0))
    normal_local.normalize()
    normal_world = (earth_rot @ normal_local).normalized()

    if look_at_center:
        target_point = earth_center.copy()
    else:
        target_point = earth_center + normal_world * float(earth_radius_bu)
    camera_position = earth_center + normal_world * (float(earth_radius_bu) + altitude_bu)
    look_direction = (target_point - camera_position)
    if look_direction.length_squared <= 1e-12:
        look_direction = -normal_world
    look_direction.normalize()

    try:
        _loc, _rot, cam_scale = camera.matrix_world.decompose()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        cam_scale = Vector((1.0, 1.0, 1.0))

    cam_rotation = look_direction.to_track_quat('-Z', 'Y')
    camera.matrix_world = Matrix.LocRotScale(camera_position, cam_rotation, cam_scale)
    return earth_obj, earth_radius_bu


def _anchor_frame_world(earth_obj, lon_deg, lat_deg):
    earth_center, earth_rot, _scale = earth_obj.matrix_world.decompose()
    earth_radius_bu = _earth_radius_blender_units(earth_obj)
    lon_rad = math.radians(float(lon_deg))
    up_local = _lon_lat_normal_local(lon_deg, lat_deg)
    if up_local.length_squared <= 1e-12:
        up_local = Vector((1.0, 0.0, 0.0))
    up_local.normalize()

    east_local = Vector((-math.sin(lon_rad), math.cos(lon_rad), 0.0))
    if east_local.length_squared <= 1e-12:
        east_local = Vector((0.0, 1.0, 0.0))
    east_local.normalize()

    north_local = up_local.cross(east_local)
    if north_local.length_squared <= 1e-12:
        north_local = Vector((0.0, 0.0, 1.0))
    north_local.normalize()

    up_world = (earth_rot @ up_local).normalized()
    east_world = (earth_rot @ east_local).normalized()
    north_world = (earth_rot @ north_local).normalized()
    anchor_world = earth_center + up_world * float(earth_radius_bu)
    return anchor_world, east_world, north_world, up_world, earth_radius_bu


def _look_rotation_quaternion(camera_location, target_point, up_hint):
    forward = (target_point - camera_location)
    if forward.length_squared <= 1e-12:
        raise RuntimeError("Camera is at the target location; cannot orient.")
    forward.normalize()

    if up_hint is None or up_hint.length_squared <= 1e-12:
        up_hint = Vector((0.0, 0.0, 1.0))
    else:
        up_hint = up_hint.normalized()

    right = forward.cross(up_hint)
    if right.length_squared <= 1e-12:
        fallback = Vector((0.0, 1.0, 0.0))
        right = forward.cross(fallback)
        if right.length_squared <= 1e-12:
            fallback = Vector((1.0, 0.0, 0.0))
            right = forward.cross(fallback)
    right.normalize()
    true_up = right.cross(forward)
    if true_up.length_squared <= 1e-12:
        true_up = Vector((0.0, 0.0, 1.0))
    true_up.normalize()

    rotation_matrix = Matrix((right, true_up, -forward)).transposed()
    return rotation_matrix.to_quaternion(), forward


def _ensure_shot_anchor_object(scene):
    anchor_obj = bpy.data.objects.get(SHOT_ANCHOR_OBJECT_NAME)
    if anchor_obj is not None and getattr(anchor_obj, "type", None) != 'EMPTY':
        try:
            bpy.data.objects.remove(anchor_obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            anchor_obj = None
    if anchor_obj is None:
        anchor_obj = bpy.data.objects.new(SHOT_ANCHOR_OBJECT_NAME, None)
        try:
            anchor_obj.empty_display_type = 'ARROWS'
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            anchor_obj.empty_display_size = 0.1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    target_collection = ensure_planetka_temp_collection() or getattr(scene, "collection", None)
    if target_collection is not None:
        for collection in tuple(getattr(anchor_obj, "users_collection", ())):
            if collection is target_collection:
                continue
            try:
                collection.objects.unlink(anchor_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
        try:
            if anchor_obj.name not in target_collection.objects:
                target_collection.objects.link(anchor_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
    return anchor_obj


def _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world):
    anchor_obj = _ensure_shot_anchor_object(scene)
    if anchor_obj is None:
        return
    frame_rotation = Matrix((east_world, north_world, up_world)).transposed().to_quaternion()
    try:
        anchor_obj.matrix_world = Matrix.LocRotScale(anchor_world, frame_rotation, Vector((1.0, 1.0, 1.0)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass


def _signed_angle_around_axis(from_vec, to_vec, axis):
    if (
        from_vec is None
        or to_vec is None
        or axis is None
        or from_vec.length_squared <= 1e-12
        or to_vec.length_squared <= 1e-12
        or axis.length_squared <= 1e-12
    ):
        return 0.0
    from_n = from_vec.normalized()
    to_n = to_vec.normalized()
    axis_n = axis.normalized()
    cross = from_n.cross(to_n)
    sin_v = axis_n.dot(cross)
    cos_v = max(-1.0, min(1.0, float(from_n.dot(to_n))))
    return math.atan2(float(sin_v), float(cos_v))


def _camera_to_current_view(scene):
    context_details = _find_active_view3d_context_details()
    if context_details is None:
        raise RuntimeError("No active 3D viewport found.")
    window = context_details.get("window")
    screen = context_details.get("screen")
    area = context_details.get("area")
    region = context_details.get("region")
    space = context_details.get("space")
    rv3d = context_details.get("rv3d")

    if window is None or screen is None or area is None or region is None or space is None or rv3d is None:
        raise RuntimeError("Current viewport context is incomplete.")

    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    if str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
        return False

    try:
        with bpy.context.temp_override(
            window=window,
            screen=screen,
            area=area,
            region=region,
            space_data=space,
            region_data=rv3d,
            scene=scene,
        ):
            result = bpy.ops.view3d.camera_to_view()
    except RuntimeError as exc:
        message = str(exc)
        if "context is incorrect" in message and str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
            return False
        raise

    if "FINISHED" in result:
        return True
    if str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
        return False
    raise RuntimeError("Failed to move camera to current view.")


def _derive_navigation_shot_from_camera(scene, lon_deg, lat_deg):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    anchor_world, east_world, north_world, up_world, earth_radius_bu = _anchor_frame_world(
        earth_obj,
        lon_deg,
        lat_deg,
    )
    earth_center = earth_obj.matrix_world.translation.copy()

    camera_matrix = camera.matrix_world
    camera_position = camera_matrix.translation.copy()
    camera_forward = (-camera_matrix.col[2].xyz).normalized()
    camera_up = camera_matrix.col[1].xyz.normalized()

    anchor_to_camera = camera_position - anchor_world
    anchor_distance = max(1e-9, float(anchor_to_camera.length))
    anchor_to_camera_dir = anchor_to_camera / anchor_distance

    up_component = max(-1.0, min(1.0, float(anchor_to_camera_dir.dot(up_world))))
    horizontal_vec = anchor_to_camera_dir - (up_world * up_component)
    horizontal_len = float(horizontal_vec.length)

    if horizontal_len <= 1e-9:
        heading_rad = 0.0
    else:
        horizontal_dir = horizontal_vec / horizontal_len
        look_horizontal_dir = -horizontal_dir
        heading_rad = math.atan2(
            float(look_horizontal_dir.dot(east_world)),
            float(look_horizontal_dir.dot(north_world)),
        )
    look_tangent = (north_world * math.cos(heading_rad)) + (east_world * math.sin(heading_rad))
    if look_tangent.length_squared <= 1e-12:
        look_tangent = north_world.copy()
    look_tangent.normalize()
    position_tangent = -look_tangent

    tilt_abs_rad = math.atan2(horizontal_len, up_component)
    sin_component = float(anchor_to_camera_dir.dot(position_tangent))
    if abs(sin_component) <= 1e-9:
        tilt_rad = tilt_abs_rad
    else:
        tilt_rad = math.copysign(tilt_abs_rad, sin_component)

    center_to_camera = camera_position - earth_center
    center_to_camera_len = max(1e-9, float(center_to_camera.length))
    altitude_bu = max(0.0, center_to_camera_len - float(earth_radius_bu))

    base_rotation, _forward = _look_rotation_quaternion(camera_position, anchor_world, look_tangent)
    base_up = (base_rotation @ Vector((0.0, 1.0, 0.0))).normalized()
    roll_rad = _signed_angle_around_axis(base_up, camera_up, camera_forward)

    return {
        "altitude_km": _bu_to_km(altitude_bu, earth_radius_bu),
        "azimuth_deg": math.degrees(heading_rad),
        "tilt_deg": math.degrees(tilt_rad),
        "roll_deg": math.degrees(roll_rad),
    }


def _apply_navigation_shot(context, scene, props):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
    lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
    altitude_km = max(0.0, float(getattr(props, "nav_altitude_km", 0.0)))
    heading_deg = float(getattr(props, "nav_azimuth_deg", 0.0))
    tilt_deg = float(getattr(props, "nav_tilt_deg", 0.0))
    roll_deg = float(getattr(props, "nav_roll_deg", 0.0))

    anchor_world, east_world, north_world, up_world, earth_radius_bu = _anchor_frame_world(
        earth_obj, lon_deg, lat_deg
    )
    earth_center = earth_obj.matrix_world.translation.copy()
    _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)

    altitude_bu = _km_to_bu(altitude_km, earth_radius_bu)
    heading_rad = math.radians(float(heading_deg))
    tilt_rad = math.radians(float(tilt_deg))
    roll_rad = math.radians(float(roll_deg))

    look_tangent = (north_world * math.cos(heading_rad)) + (east_world * math.sin(heading_rad))
    if look_tangent.length_squared <= 1e-12:
        look_tangent = north_world.copy()
    look_tangent.normalize()

    position_tangent = -look_tangent
    offset_direction = (up_world * math.cos(tilt_rad)) + (position_tangent * math.sin(tilt_rad))
    if offset_direction.length_squared <= 1e-12:
        offset_direction = up_world.copy()
    offset_direction.normalize()

    current_camera_position = camera.matrix_world.translation.copy()
    current_center_distance = max(1e-9, float((current_camera_position - earth_center).length))
    current_altitude_bu = max(0.0, current_center_distance - float(earth_radius_bu))
    current_altitude_km = _bu_to_km(current_altitude_bu, earth_radius_bu)

    last_values = _read_last_navigation_values(scene)
    lon_changed = False
    lat_changed = False
    altitude_prop_changed = False
    heading_changed = False
    tilt_changed = False
    roll_changed = False
    if last_values is not None:
        lon_changed = abs(float(lon_deg) - float(last_values["lon"])) > NAV_CHANGE_EPS
        lat_changed = abs(float(lat_deg) - float(last_values["lat"])) > NAV_CHANGE_EPS
        altitude_prop_changed = abs(float(altitude_km) - float(last_values["alt"])) > NAV_CHANGE_EPS
        heading_changed = abs(float(heading_deg) - float(last_values["heading"])) > NAV_CHANGE_EPS
        tilt_changed = abs(float(tilt_deg) - float(last_values["tilt"])) > NAV_CHANGE_EPS
        roll_changed = abs(float(roll_deg) - float(last_values["roll"])) > NAV_CHANGE_EPS
    else:
        altitude_prop_changed = abs(float(altitude_km) - float(current_altitude_km)) > 1e-4

    tilt_only_change = (
        tilt_changed
        and not lon_changed
        and not lat_changed
        and not altitude_prop_changed
        and not heading_changed
        and not roll_changed
    )

    if tilt_only_change:
        anchor_distance = float((current_camera_position - anchor_world).length)
        if anchor_distance <= 1e-9:
            anchor_distance = _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad)
    else:
        anchor_distance = _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad)

    camera_position = anchor_world + (offset_direction * anchor_distance)
    center_distance = max(1e-9, float((camera_position - earth_center).length))
    derived_altitude_bu = max(0.0, center_distance - float(earth_radius_bu))
    derived_altitude_km = _bu_to_km(derived_altitude_bu, earth_radius_bu)

    try:
        if abs(float(getattr(props, "nav_altitude_km", 0.0)) - float(derived_altitude_km)) > 1e-6:
            props.nav_altitude_km = max(0.0, float(derived_altitude_km))
    except (AttributeError, TypeError, ValueError):
        pass

    look_target = anchor_world.copy()
    if (look_target - camera_position).length_squared <= 1e-12:
        look_target = camera_position - up_world

    _loc, _existing_rotation, camera_scale = camera.matrix_world.decompose()
    base_rotation, forward = _look_rotation_quaternion(camera_position, look_target, look_tangent)
    if abs(roll_rad) > 1e-9:
        roll_quaternion = Quaternion(forward, roll_rad)
        final_rotation = roll_quaternion @ base_rotation
    else:
        final_rotation = base_rotation

    camera.matrix_world = Matrix.LocRotScale(camera_position, final_rotation, camera_scale)
    _ensure_close_clip_limits(scene, min_clip=0.001)
    _switch_viewport_to_camera_view(context, scene)
    _store_last_navigation_values(
        scene,
        lon_deg=lon_deg,
        lat_deg=lat_deg,
        altitude_km=float(getattr(props, "nav_altitude_km", altitude_km)),
        heading_deg=heading_deg,
        tilt_deg=tilt_deg,
        roll_deg=roll_deg,
    )
    return earth_obj, earth_radius_bu


def _populate_navigation_from_scene_camera(scene, props):
    if scene is None or props is None:
        return False
    nav_values = _compute_scene_camera_navigation_values(scene)
    if nav_values is None:
        return False
    lat, lon, _alt_km = nav_values
    derived = _derive_navigation_shot_from_camera(scene, lon, lat)
    try:
        props.nav_latitude_deg = max(-90.0, min(90.0, float(lat)))
        props.nav_longitude_deg = max(-180.0, min(180.0, float(lon)))
        props.nav_altitude_km = max(0.0, float(derived.get("altitude_km", 0.0)))
        props.nav_azimuth_deg = float(derived.get("azimuth_deg", 0.0))
        props.nav_tilt_deg = float(derived.get("tilt_deg", 0.0))
        props.nav_roll_deg = float(derived.get("roll_deg", 0.0))
        _store_last_navigation_values(
            scene,
            lon_deg=float(props.nav_longitude_deg),
            lat_deg=float(props.nav_latitude_deg),
            altitude_km=float(props.nav_altitude_km),
            heading_deg=float(props.nav_azimuth_deg),
            tilt_deg=float(props.nav_tilt_deg),
            roll_deg=float(props.nav_roll_deg),
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _next_saved_location_name(locations):
    used = {str(loc.get("name", "")).strip() for loc in (locations or ()) if isinstance(loc, dict)}
    index = 1
    while True:
        candidate = f"Location {index}"
        if candidate not in used:
            return candidate
        index += 1


def _get_saved_location_by_name(locations, name):
    target = str(name or "")
    for loc in locations or ():
        if not isinstance(loc, dict):
            continue
        if str(loc.get("name", "")) == target:
            return loc
    return None


class PLANETKA_OT_ImportNewData(bpy.types.Operator):
    bl_idname = "planetka.import_new_data"
    bl_label = "Import New Data"
    bl_description = "Import downloaded tile files into the current Texture Source directory"

    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        destination_directory = _normalize_texture_source_path(getattr(prefs, "texture_base_path", ""))
        if not destination_directory:
            self.report({'ERROR'}, "Texture source directory is not set. Set it first in Settings.")
            return {'CANCELLED'}
        if not os.path.isdir(destination_directory):
            self.report({'ERROR'}, f"Texture source directory is not a valid path: {destination_directory}")
            return {'CANCELLED'}

        source_directory = _normalize_texture_source_path(self.directory)
        if not source_directory or not os.path.isdir(source_directory):
            self.report({'ERROR'}, "Select a valid folder with downloaded texture files.")
            return {'CANCELLED'}
        if _paths_equivalent(source_directory, destination_directory):
            self.report({'ERROR'}, "Selected folder is already the Texture Source directory.")
            return {'CANCELLED'}

        plan = _build_texture_import_plan(source_directory, destination_directory)
        if not plan["jobs"]:
            self.report({'WARNING'}, "No importable texture files were found in the selected folder.")
            return {'CANCELLED'}

        try:
            result = bpy.ops.planetka.confirm_import_new_data(
                'INVOKE_DEFAULT',
                source_directory=source_directory,
                destination_directory=destination_directory,
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Failed to start import confirmation: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Failed to start import confirmation: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        if "CANCELLED" in result:
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'CANCELLED'}
        self.directory = ""
        wm.fileselect_add(self)
        return {'RUNNING_MODAL'}


class PLANETKA_OT_ConfirmImportNewData(bpy.types.Operator):
    bl_idname = "planetka.confirm_import_new_data"
    bl_label = "Confirm Data Import"
    bl_description = "Review import changes and confirm copy into the Texture Source directory"

    source_directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN'})
    destination_directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN'})
    new_file_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    update_file_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    added_size_gb: FloatProperty(default=0.0, min=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    total_file_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    duplicate_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})

    def _refresh_preview(self):
        source_directory = _normalize_texture_source_path(self.source_directory)
        destination_directory = _normalize_texture_source_path(self.destination_directory)
        if not source_directory or not os.path.isdir(source_directory):
            return None, "Selected source folder is no longer available."
        if not destination_directory or not os.path.isdir(destination_directory):
            return None, "Texture source directory is no longer available."

        plan = _build_texture_import_plan(source_directory, destination_directory)
        self.new_file_count = int(plan.get("new_file_count", 0))
        self.update_file_count = int(plan.get("update_file_count", 0))
        self.total_file_count = int(len(plan.get("jobs", ())))
        self.duplicate_count = int(plan.get("duplicates_skipped", 0))
        self.added_size_gb = _bytes_to_gb(plan.get("added_size_bytes", 0))
        return plan, ""

    def invoke(self, context, event):
        plan, issue = self._refresh_preview()
        if issue:
            self.report({'ERROR'}, issue)
            return {'CANCELLED'}
        if not plan.get("jobs"):
            self.report({'WARNING'}, "No importable texture files were found in the selected folder.")
            return {'CANCELLED'}

        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'CANCELLED'}
        return wm.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text=f"Source: {self.source_directory}")
        col.label(text=f"Destination: {self.destination_directory}")
        col.label(text="The following changes will be applied:")
        col.label(text=f"Total files to copy: {int(self.total_file_count)}")
        col.label(text=f"New files to import: {int(self.new_file_count)}")
        col.label(text=f"Existing files to update: {int(self.update_file_count)}")
        col.label(text=f"New data added: {float(self.added_size_gb):.3f} GB")
        if int(self.duplicate_count) > 0:
            col.label(text=f"Duplicate source tiles detected: {int(self.duplicate_count)} (newest file kept)")

    def execute(self, context):
        plan, issue = self._refresh_preview()
        if issue:
            return fail(
                self,
                issue,
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
        jobs = list(plan.get("jobs", ()))
        if not jobs:
            self.report({'WARNING'}, "No importable texture files were found to copy.")
            return {'CANCELLED'}

        copied = 0
        for job in jobs:
            source_path = job.get("source_path", "")
            destination_path = job.get("destination_path", "")
            if not source_path or not destination_path:
                continue
            try:
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.copy2(source_path, destination_path)
                copied += 1
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                return fail(
                    self,
                    f"Import failed while copying '{os.path.basename(source_path)}': {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )

        destination_directory = _normalize_texture_source_path(self.destination_directory)
        if destination_directory:
            invalidate_texture_source_health_cache(destination_directory)

        self.report(
            {'INFO'},
            (
                f"Imported {copied} files "
                f"({int(self.new_file_count)} new, {int(self.update_file_count)} updated; "
                f"+{float(self.added_size_gb):.3f} GB)."
            ),
        )
        return {'FINISHED'}


class PLANETKA_OT_SelectTextureSource(bpy.types.Operator):
    bl_idname = "planetka.select_texture_source"
    bl_label = "Set Texture Source Directory"
    bl_description = "Select Planetka's base texture directory (must contain S2, EL, WT, and PO folders)"

    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        normalized, issue = _validate_create_earth_texture_source(self.directory)
        if issue:
            self.report({'ERROR'}, issue)
            self.report({'INFO'}, "Select a directory that contains S2, EL, WT, and PO folders.")
            return {'CANCELLED'}

        prefs.texture_base_path = normalized
        invalidate_texture_source_health_cache(normalized)
        self.report({'INFO'}, "Texture source directory updated.")
        return {'FINISHED'}

    def invoke(self, context, event):
        prefs = get_prefs()
        if prefs:
            self.directory = _normalize_texture_source_path(getattr(prefs, "texture_base_path", "")) or ""
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'CANCELLED'}
        wm.fileselect_add(self)
        return {'RUNNING_MODAL'}


class PLANETKA_OT_AddEarth(bpy.types.Operator):
    bl_idname = "planetka.add_earth"
    bl_label = "Create Earth"
    bl_description = "Create Planetka Earth assets and run an initial Resolve from the configured texture source"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        def _set_default_fake_atmosphere_values():
            try:
                props.enable_fake_atmosphere = True
                props.atmosphere_mode = "QUICK"
                props.fake_atmosphere_density = (1.0 / 3.0)
                props.fake_atmosphere_height_km = 50.0
                props.fake_atmosphere_falloff_exp = 0.05
                props.fake_atmosphere_color = (0.26225066, 0.44520119, 0.76815115, 1.0)
                _sync_idprops_from_props(scene)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed setting default atmosphere values for Create Earth", exc_info=True)

        # Create Earth should start with atmosphere enabled and sane defaults.
        _set_default_fake_atmosphere_values()

        switched_to_cycles = False
        render = getattr(scene, "render", None)
        if render is not None:
            current_engine = str(getattr(render, "engine", ""))
            if current_engine != "CYCLES":
                try:
                    render.engine = "CYCLES"
                    switched_to_cycles = (str(getattr(render, "engine", "")) == "CYCLES")
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    logger.debug("Planetka: failed switching render engine to Cycles", exc_info=True)

        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )
        normalized, path_issue = _validate_create_earth_texture_source(getattr(prefs, "texture_base_path", ""))
        if path_issue:
            self.report(
                {'ERROR'},
                (
                    "Create Earth requires a valid Texture Source Directory "
                    "(folders S2, EL, WT, PO; and at least one .exr in S2)."
                ),
            )
            self.report({'ERROR'}, path_issue)
            _prompt_texture_source_selection()
            return {'CANCELLED'}
        prefs.texture_base_path = normalized
        invalidate_texture_source_health_cache(normalized)

        camera_clip_changed, viewport_clip_changed = _ensure_close_clip_limits(scene, min_clip=0.001)

        try:
            ensure_planetka_assets(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Create Earth failed while creating Planetka assets: {exc}",
                code=ErrorCode.ADD_EARTH_IMPORT_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka add_earth asset build failed",
            )

        _initialize_props_from_imported_planetka(scene)
        _sync_idprops_from_props(scene)
        warm_base_sphere_mesh_cache()

        surface_collection = ensure_planetka_temp_collection()
        new_obj = None
        try:
            new_obj = _create_placeholder_surface_object(scene)
            if not new_obj:
                raise RuntimeError("Failed to create bootstrap Earth surface mesh")
            if surface_collection is not None:
                for collection in list(new_obj.users_collection):
                    if collection is surface_collection:
                        continue
                    collection.objects.unlink(new_obj)
                if new_obj.name not in surface_collection.objects:
                    surface_collection.objects.link(new_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            if new_obj:
                remove_object_and_unused_mesh(new_obj)
            return fail(
                self,
                f"Create Earth failed while creating bootstrap Earth surface: {exc}",
                code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka add_earth bootstrap build failed",
            )

        delete_temp_meshes(keep_obj=new_obj)
        try:
            new_obj.name = "Planetka Earth Surface"
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        mark_earth_object(new_obj)
        try:
            _apply_fake_atmosphere_from_props(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed applying atmosphere defaults before initial resolve", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed applying atmosphere defaults before initial resolve", exc_info=True)

        try:
            scene[FORCE_EMPTY_RESOLVE_ONCE_KEY] = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed setting one-shot empty resolve flag", exc_info=True)

        resolve_result = bpy.ops.planetka.load_textures()

        final_surface = get_earth_object() or new_obj
        if final_surface and bool(getattr(props, "show_earth_preview", False)):
            try:
                ensure_preview_object(final_surface)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed creating preview object", exc_info=True)
                self.report({'WARNING'}, "Planetka preview object refresh failed.")
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed creating preview object", exc_info=True)
                self.report({'WARNING'}, "Planetka preview object refresh failed.")

        if "FINISHED" not in resolve_result:
            self.report({'WARNING'}, "Planetka Earth created, but initial Resolve failed.")
            return {'CANCELLED'}

        _set_default_fake_atmosphere_values()
        try:
            _apply_fake_atmosphere_from_props(scene)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed reapplying default atmosphere values after initial resolve", exc_info=True)

        if props is not None:
            suspend_navigation_shot_updates()
            try:
                _populate_navigation_from_scene_camera(scene, props)
            finally:
                resume_navigation_shot_updates()
        _switch_solid_viewports_to_rendered(context)

        if camera_clip_changed or viewport_clip_changed:
            self.report(
                {'INFO'},
                "Planetka adjusted clipping minimum to 0.001 to avoid close-surface image clipping.",
            )
        if switched_to_cycles:
            self.report(
                {'INFO'},
                "Planetka switched Blender to Cycles for optimal performance.",
            )
        self.report({'INFO'}, "Planetka Earth created successfully.")
        return {'FINISHED'}


class PLANETKA_OT_NavigationApplyShot(bpy.types.Operator):
    bl_idname = "planetka.navigation_apply_shot"
    bl_label = "Apply Navigation Shot"
    bl_description = "Apply current Navigation shot values to the Planetka camera rig"
    bl_options = {'INTERNAL'}

    silent: BoolProperty(
        name="Silent",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        try:
            _apply_navigation_shot(context, scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Apply Shot failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka apply-shot failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Apply Shot failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        if not bool(getattr(self, "silent", False)):
            self.report({'INFO'}, "Shot updated.")
        return {'FINISHED'}


class PLANETKA_OT_UseCurrentViewNavigation(bpy.types.Operator):
    bl_idname = "planetka.navigation_use_current_view"
    bl_label = "Camera to Current View"
    bl_description = "Read the active viewport camera transform and sync it into Navigation shot values"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        camera = getattr(scene, "camera", None)
        if camera is None or getattr(camera, "type", None) != 'CAMERA':
            return fail(
                self,
                "Scene camera is missing. Set an active camera and retry.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        try:
            moved_camera = bool(_camera_to_current_view(scene))
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Camera to Current View failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka camera_to_current_view failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Camera to Current View failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        computed = _compute_current_view_navigation_values(scene)
        if computed is None:
            return fail(
                self,
                "Current view telemetry is unavailable. Ensure Earth is visible in the viewport.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
        lat, lon, _alt_km = computed

        try:
            derived = _derive_navigation_shot_from_camera(scene, lon, lat)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Failed to derive shot values from current view: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka derive shot from camera failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Failed to derive shot values from current view: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        try:
            props.nav_latitude_deg = max(-90.0, min(90.0, float(lat)))
            props.nav_longitude_deg = max(-180.0, min(180.0, float(lon)))
            props.nav_altitude_km = max(0.0, float(derived.get("altitude_km", 0.0)))
            props.nav_azimuth_deg = float(derived.get("azimuth_deg", 0.0))
            props.nav_tilt_deg = float(derived.get("tilt_deg", 0.0))
            props.nav_roll_deg = float(derived.get("roll_deg", 0.0))
            _store_last_navigation_values(
                scene,
                lon_deg=float(props.nav_longitude_deg),
                lat_deg=float(props.nav_latitude_deg),
                altitude_km=float(props.nav_altitude_km),
                heading_deg=float(props.nav_azimuth_deg),
                tilt_deg=float(props.nav_tilt_deg),
                roll_deg=float(props.nav_roll_deg),
            )
        except (AttributeError, TypeError, ValueError):
            return fail(
                self,
                "Failed to apply current view values to Navigation fields.",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        _switch_viewport_to_camera_view(context, scene)
        if moved_camera:
            self.report({'INFO'}, "Camera and Navigation fields updated from current view.")
        else:
            self.report({'INFO'}, "Camera is already in current view. Navigation fields synced.")
        return {'FINISHED'}


class PLANETKA_OT_SaveLocation(bpy.types.Operator):
    bl_idname = "planetka.save_location"
    bl_label = "Save Location"
    bl_description = "Save the current Navigation longitude, latitude, and altitude as a reusable location"

    def execute(self, context):
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        prefs = get_prefs()
        if prefs is None:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        locations = read_saved_locations(prefs)
        name = str(getattr(props, "nav_saved_location_name", "") or "").strip()
        if not name:
            name = _next_saved_location_name(locations)

        payload = {
            "name": name,
            "lon": float(getattr(props, "nav_longitude_deg", 0.0)),
            "lat": float(getattr(props, "nav_latitude_deg", 0.0)),
            "alt_km": float(getattr(props, "nav_altitude_km", 0.0)),
        }

        replaced = False
        for index, loc in enumerate(locations):
            if str(loc.get("name", "")) == name:
                locations[index] = payload
                replaced = True
                break
        if not replaced:
            locations.append(payload)

        if not write_saved_locations(prefs, locations):
            return fail(
                self,
                "Failed to save location.",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        props.nav_saved_location_name = name
        try:
            props.nav_saved_location_id = name
        except (AttributeError, TypeError, ValueError):
            pass

        if not _persist_user_preferences():
            self.report({'WARNING'}, "Location saved for this session only. Save Preferences to persist globally.")

        self.report({'INFO'}, f"Saved location: {name}")
        return {'FINISHED'}


class PLANETKA_OT_LoadSavedLocation(bpy.types.Operator):
    bl_idname = "planetka.load_saved_location"
    bl_label = "Load Location"
    bl_description = "Load the selected saved location into Navigation fields and move the camera"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        prefs = get_prefs()
        if prefs is None:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        selected_name = str(getattr(props, "nav_saved_location_id", "") or "")
        if not selected_name or selected_name == "__NONE__":
            return fail(
                self,
                "No saved location selected.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        locations = read_saved_locations(prefs)
        selected = _get_saved_location_by_name(locations, selected_name)
        if not selected:
            return fail(
                self,
                f"Saved location not found: {selected_name}",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        suspend_navigation_shot_updates()
        try:
            props.nav_longitude_deg = float(selected.get("lon", 0.0))
            props.nav_latitude_deg = float(selected.get("lat", 0.0))
            props.nav_altitude_km = float(selected.get("alt_km", 0.0))
            props.nav_saved_location_name = str(selected.get("name", ""))
        finally:
            resume_navigation_shot_updates()

        try:
            _apply_navigation_shot(context, scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Loaded location but failed to move camera: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka load-saved-location camera apply failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Loaded location but failed to move camera: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        self.report({'INFO'}, f"Loaded location: {selected_name}")
        return {'FINISHED'}


class PLANETKA_OT_DeleteSavedLocation(bpy.types.Operator):
    bl_idname = "planetka.delete_saved_location"
    bl_label = "Delete Location"
    bl_description = "Delete the selected saved location from Planetka preferences"

    def execute(self, context):
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        prefs = get_prefs()
        if prefs is None:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        selected_name = str(getattr(props, "nav_saved_location_id", "") or "")
        if not selected_name or selected_name == "__NONE__":
            return fail(
                self,
                "No saved location selected.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        locations = read_saved_locations(prefs)
        filtered = [loc for loc in locations if str(loc.get("name", "")) != selected_name]
        if len(filtered) == len(locations):
            return fail(
                self,
                f"Saved location not found: {selected_name}",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        if not write_saved_locations(prefs, filtered):
            return fail(
                self,
                "Failed to delete saved location.",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        if filtered:
            fallback_name = str(filtered[0].get("name", ""))
            try:
                props.nav_saved_location_id = fallback_name
            except (AttributeError, TypeError, ValueError):
                pass
        props.nav_saved_location_name = ""
        if not _persist_user_preferences():
            self.report({'WARNING'}, "Deletion saved for this session only. Save Preferences to persist globally.")
        self.report({'INFO'}, f"Deleted location: {selected_name}")
        return {'FINISHED'}


class PLANETKA_OT_NavigationPreset(bpy.types.Operator):
    bl_idname = "planetka.navigation_preset"
    bl_label = "Set Navigation Preset"
    bl_description = "Apply a Navigation altitude preset and update camera placement for the current location"

    preset: EnumProperty(
        name="Preset",
        items=(
            ("MAX_PROXIMITY", "Max Proximity", "Closest altitude near texture quality limit (Caution target)"),
            ("ISS_ORBIT", "ISS Orbit", "Set altitude to 400 km"),
            ("GEOSYNCHRONOUS", "Geosynchronous", "Set altitude to 35786 km"),
            ("HIGH_ORBIT", "Globe View", "Fit full Earth with room around edges"),
        ),
        default="ISS_ORBIT",
    )

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        earth_obj = get_earth_object()
        if earth_obj is None:
            return fail(
                self,
                "Create Earth first, then use Navigation presets.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
        if getattr(scene, "camera", None) is None:
            return fail(
                self,
                "Scene camera is missing. Set an active camera and retry.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        earth_radius_bu = _earth_radius_blender_units(earth_obj)
        preset = str(getattr(self, "preset", "ISS_ORBIT"))
        if preset == "ISS_ORBIT":
            props.nav_altitude_km = 400.0
        elif preset == "GEOSYNCHRONOUS":
            props.nav_altitude_km = 35786.0
        elif preset == "HIGH_ORBIT":
            full_globe_km = _full_globe_altitude_km(scene, earth_radius_bu)
            if full_globe_km is not None:
                props.nav_altitude_km = max(0.0, float(full_globe_km))
            ortho_adjusted = _ensure_ortho_full_globe_if_needed(scene, earth_radius_bu)
            if ortho_adjusted:
                self.report({'INFO'}, "Orthographic scale expanded to fit full globe with margin.")
        elif preset == "MAX_PROXIMITY":
            lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
            lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
            max_km, note = _max_proximity_altitude_km(scene, earth_obj, earth_radius_bu, lon_deg, lat_deg)
            if max_km is None:
                return fail(
                    self,
                    "Unable to compute Max Proximity for current camera.",
                    code=ErrorCode.NAV_PRECHECK_FAILED,
                    logger=logger,
                )
            props.nav_altitude_km = max(0.0, float(max_km))
            if note:
                self.report({'INFO'}, note)
        else:
            return fail(
                self,
                f"Unknown navigation preset: {preset}",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        try:
            if preset == "HIGH_ORBIT":
                lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
                lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
                altitude_km = float(getattr(props, "nav_altitude_km", 0.0))
                _navigate_camera_internal(
                    scene,
                    lon_deg,
                    lat_deg,
                    altitude_km,
                    look_at_center=True,
                )
                earth_obj = get_earth_object()
                if earth_obj is not None:
                    anchor_world, east_world, north_world, up_world, _radius = _anchor_frame_world(
                        earth_obj,
                        lon_deg,
                        lat_deg,
                    )
                    _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)
                _ensure_close_clip_limits(scene, min_clip=0.001)
                _switch_viewport_to_camera_view(context, scene)
            else:
                _apply_navigation_shot(context, scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Navigation preset apply failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka navigation preset apply failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Navigation preset apply failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        preset_label = "Globe View" if preset == "HIGH_ORBIT" else preset.replace('_', ' ').title()
        self.report({'INFO'}, f"Navigation preset applied: {preset_label}.")
        return {'FINISHED'}


class PLANETKA_OT_SunlightPreset(bpy.types.Operator):
    bl_idname = "planetka.sunlight_preset"
    bl_label = "Sunlight Preset"
    bl_description = (
        "Set Planetka Sunlight using common lighting presets around the current location "
        "(seasonal tilt is clamped to ±23.5°)"
    )

    preset: EnumProperty(
        name="Preset",
        items=(
            ("DAWN", "Dawn", ""),
            ("SUNRISE", "Sunrise", ""),
            ("EARLY_MORNING", "Early Morning", ""),
            ("SUNSET", "Sunset", ""),
            ("MID_MORNING", "Mid-morning", ""),
            ("MID_AFTERNOON", "Mid-afternoon", ""),
            ("LATE_AFTERNOON", "Late Afternoon", ""),
            ("NOON", "Noon", ""),
            ("DUSK", "Dusk", ""),
            ("NIGHT", "Night", ""),
        ),
        default="NOON",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        try:
            lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
            lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
        except (TypeError, ValueError):
            lon_deg = 0.0
            lat_deg = 0.0

        lon = math.radians(lon_deg)
        lat = math.radians(lat_deg)

        up = Vector(
            (
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            )
        )
        if up.length < 1e-9:
            return {'CANCELLED'}
        up.normalize()
        east = Vector((-math.sin(lon), math.cos(lon), 0.0))
        if east.length < 1e-9:
            east = Vector((0.0, 1.0, 0.0))
        east.normalize()
        west = -east

        preset = str(getattr(self, "preset", "NOON") or "NOON").upper()
        if preset == "NOON":
            sun_dir = up
        elif preset == "NIGHT":
            sun_dir = -up
        else:
            if preset in {"DAWN", "DUSK"}:
                elev_deg = 0.5
            elif preset in {"SUNRISE", "SUNSET"}:
                elev_deg = 6.0
            elif preset in {"EARLY_MORNING", "LATE_AFTERNOON"}:
                elev_deg = 25.0
            else:
                elev_deg = 45.0

            horiz = east if preset in {"DAWN", "SUNRISE", "EARLY_MORNING", "MID_MORNING"} else west
            elev = math.radians(elev_deg)
            sun_dir = (horiz * math.cos(elev)) + (up * math.sin(elev))
            if sun_dir.length < 1e-9:
                sun_dir = up
            sun_dir.normalize()

        try:
            sun_lon = math.degrees(math.atan2(float(sun_dir.y), float(sun_dir.x)))
            sun_lat = math.degrees(math.asin(max(-1.0, min(1.0, float(sun_dir.z)))))
            sun_lat = max(-23.5, min(23.5, float(sun_lat)))
            props.sunlight_longitude_deg = float(sun_lon)
            props.sunlight_seasonal_tilt_deg = float(sun_lat)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed setting sunlight preset properties", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed setting sunlight preset properties", exc_info=True)

        self.report({'INFO'}, f"Sunlight preset applied: {preset.replace('_', ' ').title()}.")
        return {'FINISHED'}
