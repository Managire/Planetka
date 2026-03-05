import logging
import math
import re
from collections import defaultdict

import bpy
import mathutils
from mathutils import Vector

from .diagnostics import write_tile_view_diagnostics
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object

logger = logging.getLogger(__name__)

REAL_EARTH_RADIUS_M = 6371000.0
DATASET_MPP_BASE_D1 = 10.0
QUALITY_SAFETY_MARGIN = 0.9
MAX_TERRAIN_HEIGHT_M = 9000.0
DEFAULT_PLANET_RADIUS_BU = 1.0
Z_LEVELS = (1, 2, 4, 8, 15, 30, 60, 90, 180, 360)
D_LEVELS_BY_Z = {
    1: [1, 2, 4, 8, 15, 30, 60],
    2: [2, 4, 8, 15, 30, 60],
    4: [4, 8, 15, 30, 60],
    8: [8, 15, 30, 60],
    15: [15, 30, 60],
    16: [16, 32, 64],
    30: [30, 60, 90, 180, 360],
    32: [32, 64],
    60: [60, 90, 180, 360],
    90: [90, 180, 360],
    180: [180, 360, 720],
    360: [360, 720, 1440],
}

FRUSTUM_MARGIN = 1.05
ACTIVE_VIEW_FRUSTUM_MARGIN = 1.25
HORIZON_DOT_MARGIN = 0.995
ONE_PASS_REFINEMENT_CHILD_Z = {
    60: 30,
    30: 15,
    8: 4,
    4: 2,
    2: 1,
}
LAST_REQUIRED_MPP_KEY = "planetka_last_required_mpp_m"
LAST_TARGET_D_KEY = "planetka_last_target_d"
LAST_SCOPE_USED_KEY = "planetka_last_scope_used"
TEXTURE_QUALITY_MODES = {"FULL", "HALF", "QUARTER"}
VIEWPORT_RESOLUTION_X = 1920.0
VIEWPORT_RESOLUTION_Y = 1080.0


def get_earth_radius_blender_units(earth_obj):
    if not earth_obj:
        return 1.0

    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except Exception:
        stored_local_radius = 0.0
    if stored_local_radius > 1e-9:
        world_scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
        return stored_local_radius * float(max_scale)

    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    if vertices and len(vertices) > 0:
        try:
            local_radius = max(v.co.length for v in vertices)
            if local_radius > 1e-9:
                world_scale = earth_obj.matrix_world.to_scale()
                max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
                return float(local_radius) * float(max_scale)
        except Exception:
            logger.debug("Planetka: vertex-based Earth radius inference failed", exc_info=True)

    scale = earth_obj.matrix_world.to_scale()
    max_scale = max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)
    return DEFAULT_PLANET_RADIUS_BU * max_scale


def get_planet_root():
    earth = get_earth_object()
    if earth and earth.parent:
        return earth.parent
    return None


def get_planet_radius(earth_obj=None):
    if earth_obj:
        return get_earth_radius_blender_units(earth_obj)
    return DEFAULT_PLANET_RADIUS_BU


MERGE_GROUPS = [
    {1, 2, 4, 8, 16, 32},
    {15, 30, 60},
]


def parse_tile(tile):
    match = re.match(r"x(\d+)_y(\d+)_z(\d+)_d(\d+)", tile)
    if not match:
        return None
    x, y, z, d_code = map(int, match.groups())
    if d_code == 0:
        d_code = 1440
    return x, y, z, d_code


def format_tile(x, y, z, d):
    d_code = 0 if int(d) == 1440 else int(d)
    return f"x{x:03d}_y{y:03d}_z{z:03d}_d{d_code:03d}"


def is_mergeable(z):
    for group in MERGE_GROUPS:
        if z in group and z != max(group):
            return True
    return False


def assign_higher_level_tile(x, y, z):
    higher_z = z * 2
    new_x = (x // higher_z) * higher_z
    new_y = (y // higher_z) * higher_z
    return format_tile(new_x, new_y, higher_z, higher_z)


def find_optimizable_tiles(tiles):
    def equivalent_d(a, b):
        return {a, b} in ({15, 16}, {30, 32}, {60, 64})

    def quality_not_worse(parent_d, child_d):
        return parent_d <= child_d or equivalent_d(parent_d, child_d)

    def optimize_once(tile_list):
        assigned = defaultdict(list)
        banned = set()
        final = set()

        parsed = {t: parse_tile(t) for t in tile_list if parse_tile(t)}

        for tile, (x, y, z, d) in parsed.items():
            if d == z and is_mergeable(z):
                banned.add(assign_higher_level_tile(x, y, z))

        for tile, (x, y, z, d) in parsed.items():
            if not is_mergeable(z):
                final.add(tile)
                continue

            higher = assign_higher_level_tile(x, y, z)
            if higher in banned:
                final.add(tile)
            else:
                assigned[higher].append(tile)

        for higher_tile, children in assigned.items():
            if higher_tile in banned:
                final.update(children)
                continue

            child_info = []
            for tile in children:
                parsed_tile = parsed.get(tile)
                if not parsed_tile:
                    continue
                x, y, z, d = parsed_tile
                child_info.append((x, y, z, d, tile))

            if len(child_info) < 2:
                final.update(children)
                continue

            xh, yh, zh, _ = parse_tile(higher_tile)
            min_child_d = min(d for _x, _y, _z, d, _t in child_info)
            merged_d = max(zh, min_child_d)

            def contains(px, py, pz):
                return (
                    px >= xh
                    and py >= yh
                    and px + pz <= xh + zh
                    and py + pz <= yh + zh
                )

            for _t, (tx, ty, tz, td) in parsed.items():
                if contains(tx, ty, tz) and not quality_not_worse(merged_d, td):
                    final.update(children)
                    break
            else:
                merged = format_tile(xh, yh, zh, merged_d)
                if zh in {16, 32}:
                    if merged_d == 30:
                        merged = merged.replace("_d030", "_d032")
                    elif merged_d == 60:
                        merged = merged.replace("_d060", "_d064")
                final.add(merged)
                continue

        return list(final)

    prev = set(tiles)
    for _ in range(100):
        cur = set(optimize_once(prev))
        if cur == prev:
            break
        prev = cur

    optimized = list(prev)
    parsed = [parse_tile(t) + (t,) for t in optimized if parse_tile(t)]
    parsed.sort(key=lambda tup: (tup[3], -tup[2], tup[4]))

    kept = []
    for x, y, z, d, tile_code in parsed:
        fully_covered = False
        for kx, ky, kz, kd, _kept_code in kept:
            if (
                kx <= x
                and ky <= y
                and x + z <= kx + kz
                and y + z <= ky + kz
                and kd <= d
            ):
                fully_covered = True
                break
        if not fully_covered:
            kept.append((x, y, z, d, tile_code))

    final_tiles = [tup[4] for tup in kept]

    overlap_warned = False
    for i in range(len(final_tiles)):
        for j in range(i + 1, len(final_tiles)):
            xa, ya, za, _ = parse_tile(final_tiles[i])
            xb, yb, zb, _ = parse_tile(final_tiles[j])
            if not (xa + za <= xb or xb + zb <= xa or ya + za <= yb or yb + zb <= ya):
                if not overlap_warned:
                    logger.warning("Planetka: overlapping tiles detected after optimization")
                    overlap_warned = True
                break

    def sort_key(tile):
        _, _, z, d = parse_tile(tile)
        return (d, d / z)

    return sorted(final_tiles, key=sort_key)


def lonlat_to_cartesian(lon, lat, radius):
    lat_deg = float(lat) - 90.0
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(float(lon))

    x = radius * math.cos(lat_rad) * math.cos(lon_rad)
    y = radius * math.cos(lat_rad) * math.sin(lon_rad)
    z = radius * math.sin(lat_rad)
    return x, y, z


def get_tile_from_coordinates(lon, lat, z, d):
    lon = (lon + 180.0) % 360.0
    x = int(lon // z) * z
    y = int(lat // z) * z
    x %= 360
    if y < 0 or y > 179:
        return None
    return format_tile(x, y, z, d)


def _render_resolution_px(scene):
    render = getattr(scene, "render", None) if scene is not None else None
    if render is None:
        return VIEWPORT_RESOLUTION_X, VIEWPORT_RESOLUTION_Y
    try:
        scale = max(0.01, float(getattr(render, "resolution_percentage", 100.0))) / 100.0
        res_x = max(1.0, float(getattr(render, "resolution_x", VIEWPORT_RESOLUTION_X)) * scale)
        res_y = max(1.0, float(getattr(render, "resolution_y", VIEWPORT_RESOLUTION_Y)) * scale)
        return res_x, res_y
    except (TypeError, ValueError, RuntimeError):
        return VIEWPORT_RESOLUTION_X, VIEWPORT_RESOLUTION_Y


def _meters_per_blender_unit(earth_radius):
    safe_radius = max(float(earth_radius), 1e-9)
    return REAL_EARTH_RADIUS_M / safe_radius


def _blender_units_from_meters(distance_m, earth_radius):
    return float(distance_m) / _meters_per_blender_unit(earth_radius)


def _required_mpp_from_distance(
    distance,
    earth_radius,
    camera_type,
    h_fov,
    v_fov,
    res_x,
    res_y,
    ortho_scale,
):
    terrain_offset_bl = _blender_units_from_meters(MAX_TERRAIN_HEIGHT_M, earth_radius)
    effective_distance = max(0.0, float(distance) - terrain_offset_bl)

    if camera_type == "ORTHO":
        px_world_x = float(ortho_scale) / max(1.0, res_x)
        px_world_y = float(ortho_scale) / max(1.0, res_y)
        footprint_world = max(px_world_x, px_world_y)
    else:
        px_angle = max(float(h_fov) / max(1.0, res_x), float(v_fov) / max(1.0, res_y))
        footprint_world = 2.0 * effective_distance * math.tan(max(1e-9, px_angle) * 0.5)

    return footprint_world * _meters_per_blender_unit(earth_radius)


def _target_d_from_required_mpp(required_mpp):
    if required_mpp is None:
        return 1
    safe_required_mpp = max(0.0, float(required_mpp)) * QUALITY_SAFETY_MARGIN
    target = int(math.floor(safe_required_mpp / DATASET_MPP_BASE_D1))
    return max(1, target)


def _resolution_bias_factor(scene):
    return 1.0


def _texture_quality_mode(scene):
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return "FULL"
    mode = str(
        getattr(
            props,
            "texture_quality_mode",
            "FULL",
        )
        or "FULL"
    ).upper()
    if mode in {"NORMAL", "DOUBLE"}:
        mode = "FULL"
    if mode not in TEXTURE_QUALITY_MODES:
        return "FULL"
    return mode


def _use_active_view_coarse_textures(scene):
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return True
    return bool(getattr(props, "viewport_opt_active_view_coarse_textures", True))


def compute_z_value(required_mpp, bias_factor=1.0):
    target_d = _target_d_from_required_mpp(float(required_mpp) * float(bias_factor))
    for z in reversed(Z_LEVELS):
        if z <= target_d:
            return z
    return Z_LEVELS[0]


def compute_d_value(required_mpp, z, bias_factor=1.0):
    allowed_d = D_LEVELS_BY_Z.get(int(z), [int(z)])
    target_d = _target_d_from_required_mpp(float(required_mpp) * float(bias_factor))
    candidates = [d for d in allowed_d if d <= target_d]
    if candidates:
        return max(candidates)
    return min(allowed_d)


def _iter_tile_candidates(z):
    step = max(1, int(z))
    for x in range(0, 360, step):
        for y in range(0, 180, step):
            yield x, y


def _tile_sample_uv(z):
    z = int(z)
    if z <= 4:
        grid = 11
    elif z <= 8:
        grid = 9
    elif z <= 15:
        grid = 7
    elif z <= 30:
        grid = 6
    elif z <= 60:
        grid = 5
    elif z <= 90:
        grid = 4
    else:
        grid = 3

    if grid <= 1:
        return ((0.5, 0.5),)

    uv = set()
    step = 1.0 / float(grid - 1)
    for i in range(grid):
        u = i * step
        for j in range(grid):
            v = j * step
            uv.add((u, v))

    if grid >= 5:
        for i in range(grid - 1):
            u = (i + 0.5) * step
            for j in range(grid - 1):
                v = (j + 0.5) * step
                uv.add((u, v))

    return tuple(sorted(uv))


def _tile_sample_points(x, y, z, earth_radius, uv_samples):
    points = []
    zf = float(z)
    for u, v in uv_samples:
        lon_shift = (float(x) + zf * float(u)) % 360.0
        lon = lon_shift - 180.0
        lat = min(180.0, max(0.0, float(y) + zf * float(v)))
        px, py, pz = lonlat_to_cartesian(lon, lat, earth_radius)
        points.append(Vector((px, py, pz)))
    return points


def _point_on_visible_hemisphere(point, cam_pos_local, radius_sq):
    return point.dot(cam_pos_local) >= (radius_sq * HORIZON_DOT_MARGIN)


def _point_in_camera_view(
    point,
    cam_pos_local,
    cam_forward_local,
    cam_right_local,
    cam_up_local,
    camera_type,
    tan_half_h,
    tan_half_v,
    ortho_half_w,
    ortho_half_h,
    frustum_margin,
):
    rel = point - cam_pos_local
    depth = rel.dot(cam_forward_local)
    if depth <= 0.0:
        return False

    x_val = rel.dot(cam_right_local)
    y_val = rel.dot(cam_up_local)

    if camera_type == "ORTHO":
        return (
            abs(x_val) <= (ortho_half_w * frustum_margin)
            and abs(y_val) <= (ortho_half_h * frustum_margin)
        )

    max_x = depth * tan_half_h * frustum_margin
    max_y = depth * tan_half_v * frustum_margin
    return abs(x_val) <= max_x and abs(y_val) <= max_y


def _frustum_guard_ndc_points(sample_count):
    sample_count = max(3, int(sample_count))
    inset = 0.995
    step = 2.0 / float(sample_count - 1)
    values = [-1.0 + i * step for i in range(sample_count)]

    points = {(0.0, 0.0)}
    for value in values:
        points.add((value, inset))
        points.add((value, -inset))
        points.add((inset, value))
        points.add((-inset, value))
    points.add((inset, inset))
    points.add((-inset, inset))
    points.add((inset, -inset))
    points.add((-inset, -inset))
    return tuple(points)


def _intersect_ray_sphere_nearest(origin, direction, radius):
    a = float(direction.dot(direction))
    if a <= 1e-12:
        return None

    b = 2.0 * float(origin.dot(direction))
    c = float(origin.dot(origin)) - float(radius) * float(radius)
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0.0:
        return None

    sqrt_d = math.sqrt(discriminant)
    inv = 0.5 / a
    t0 = (-b - sqrt_d) * inv
    t1 = (-b + sqrt_d) * inv

    for t in (t0, t1):
        if t > 1e-6:
            point = origin + direction * t
            return point
    return None


def _cartesian_to_lonlat(point):
    radius = float(point.length)
    if radius <= 1e-12:
        return None

    x = float(point.x) / radius
    y = float(point.y) / radius
    z = float(point.z) / radius
    z = max(-1.0, min(1.0, z))

    lon = math.degrees(math.atan2(y, x))
    lat = math.degrees(math.asin(z)) + 90.0
    return lon, max(0.0, min(179.999999, lat))


def _collect_guard_tiles_for_frustum(
    z,
    earth_radius,
    cam_pos_local,
    cam_forward_local,
    cam_right_local,
    cam_up_local,
    camera_type,
    h_fov,
    v_fov,
    res_x,
    res_y,
    ortho_scale,
    bias_factor,
    frustum_margin=FRUSTUM_MARGIN,
    guard_distances=None,
    edge_boost=False,
):
    distances = guard_distances or _collect_guard_hit_distances(
        z=z,
        earth_radius=earth_radius,
        cam_pos_local=cam_pos_local,
        cam_forward_local=cam_forward_local,
        cam_right_local=cam_right_local,
        cam_up_local=cam_up_local,
        camera_type=camera_type,
        h_fov=h_fov,
        v_fov=v_fov,
        res_x=res_x,
        res_y=res_y,
        ortho_scale=ortho_scale,
        frustum_margin=frustum_margin,
        edge_boost=edge_boost,
    )

    guarded_tiles = set()
    nearest_distance = None
    for (x, y), distance in distances.items():
        required_mpp = _required_mpp_from_distance(
            distance=distance,
            earth_radius=earth_radius,
            camera_type=camera_type,
            h_fov=h_fov,
            v_fov=v_fov,
            res_x=res_x,
            res_y=res_y,
            ortho_scale=ortho_scale,
        )
        d_value = compute_d_value(required_mpp, z, bias_factor=bias_factor)
        guarded_tiles.add(format_tile(x, y, z, d_value))
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance

    return guarded_tiles, nearest_distance


def _collect_guard_hit_distances(
    z,
    earth_radius,
    cam_pos_local,
    cam_forward_local,
    cam_right_local,
    cam_up_local,
    camera_type,
    h_fov,
    v_fov,
    res_x,
    res_y,
    ortho_scale,
    frustum_margin=FRUSTUM_MARGIN,
    edge_boost=False,
):
    if z <= 8:
        sample_count = 11
    elif z <= 30:
        sample_count = 9
    else:
        sample_count = 7
    if edge_boost:
        sample_count += 4

    tan_half_h = math.tan(max(1e-9, float(h_fov)) * 0.5) * float(frustum_margin)
    tan_half_v = math.tan(max(1e-9, float(v_fov)) * 0.5) * float(frustum_margin)
    ortho_half_w, ortho_half_h = _orthographic_half_extents(ortho_scale, res_x, res_y)
    ortho_half_w *= float(frustum_margin)
    ortho_half_h *= float(frustum_margin)

    distances = {}
    for nx, ny in _frustum_guard_ndc_points(sample_count):
        if camera_type == "ORTHO":
            ray_origin = (
                cam_pos_local
                + cam_right_local * (float(nx) * float(ortho_half_w))
                + cam_up_local * (float(ny) * float(ortho_half_h))
            )
            ray_direction = cam_forward_local
        else:
            ray_origin = cam_pos_local
            ray_direction = (
                cam_forward_local
                + cam_right_local * (float(nx) * float(tan_half_h))
                + cam_up_local * (float(ny) * float(tan_half_v))
            )
            if ray_direction.length_squared <= 1e-12:
                continue
            ray_direction.normalize()

        hit = _intersect_ray_sphere_nearest(ray_origin, ray_direction, earth_radius)
        if hit is None:
            continue

        lonlat = _cartesian_to_lonlat(hit)
        if lonlat is None:
            continue
        lon, lat = lonlat

        tile_at_level = get_tile_from_coordinates(lon, lat, z, z)
        if tile_at_level is None:
            continue
        parsed = parse_tile(tile_at_level)
        if not parsed:
            continue
        x, y, _, _ = parsed
        distance = float((hit - cam_pos_local).length)
        key = (x, y)
        if key not in distances or distance < distances[key]:
            distances[key] = distance
    return distances


def _candidate_tiles_for_level(z, guard_distances, edge_boost=False):
    if int(z) > 8 or not guard_distances:
        return list(_iter_tile_candidates(z))

    step = int(z)
    if step <= 1:
        expand = 3
    elif step <= 2:
        expand = 2
    else:
        expand = 1
    if edge_boost:
        expand += 1

    candidates = set()
    for x, y in guard_distances.keys():
        for dx in range(-expand, expand + 1):
            for dy in range(-expand, expand + 1):
                nx = (int(x) + dx * step) % 360
                ny = int(y) + dy * step
                if 0 <= ny <= 179:
                    candidates.add((nx, ny))

    return sorted(candidates)


def _orthographic_half_extents(ortho_scale, res_x, res_y):
    aspect = max(1e-9, float(res_x) / max(1.0, float(res_y)))
    if aspect >= 1.0:
        half_w = float(ortho_scale) * 0.5
        half_h = half_w / aspect
    else:
        half_h = float(ortho_scale) * 0.5
        half_w = half_h * aspect
    return half_w, half_h


def _is_earth_in_view(
    cam_pos_local,
    cam_forward_local,
    cam_right_local,
    cam_up_local,
    earth_radius,
    camera_type,
    tan_half_h,
    tan_half_v,
    ortho_half_w,
    ortho_half_h,
    frustum_margin,
):
    radius = max(1e-9, float(earth_radius))
    cam_dist = float(cam_pos_local.length)
    if cam_dist <= radius:
        return True

    if camera_type == "ORTHO":
        center_rel = -cam_pos_local
        depth = center_rel.dot(cam_forward_local)
        if depth + radius <= 0.0:
            return False
        center_x = abs(center_rel.dot(cam_right_local))
        center_y = abs(center_rel.dot(cam_up_local))
        return (
            center_x <= ((ortho_half_w * frustum_margin) + radius)
            and center_y <= ((ortho_half_h * frustum_margin) + radius)
        )

    to_center = (-cam_pos_local).normalized()
    cos_gamma = max(-1.0, min(1.0, cam_forward_local.dot(to_center)))
    gamma = math.acos(cos_gamma)
    alpha = math.asin(min(1.0, radius / cam_dist))
    half_diag = math.atan(math.hypot(tan_half_h * frustum_margin, tan_half_v * frustum_margin))
    return gamma <= (half_diag + alpha)


def _transform_to_planet_space(cam_pos_world, cam_forward_world, cam_right_world, cam_up_world, earth, root):
    if earth:
        loc, rot_quat, _ = earth.matrix_world.decompose()
        no_scale = mathutils.Matrix.Translation(loc) @ rot_quat.to_matrix().to_4x4()
        inv = no_scale.inverted()
    elif root:
        loc, rot_quat, _ = root.matrix_world.decompose()
        no_scale = mathutils.Matrix.Translation(loc) @ rot_quat.to_matrix().to_4x4()
        inv = no_scale.inverted()
    else:
        inv = None

    if inv is None:
        return (
            cam_pos_world.copy(),
            cam_forward_world.normalized(),
            cam_right_world.normalized(),
            cam_up_world.normalized(),
        )

    rot_mat = inv.to_3x3()
    return (
        inv @ cam_pos_world,
        (rot_mat @ cam_forward_world).normalized(),
        (rot_mat @ cam_right_world).normalized(),
        (rot_mat @ cam_up_world).normalized(),
    )


def _collect_visible_tiles(
    z,
    cam_pos_local,
    cam_forward_local,
    cam_right_local,
    cam_up_local,
    earth_radius,
    camera_type,
    h_fov,
    v_fov,
    res_x,
    res_y,
    ortho_scale,
    bias_factor,
    frustum_margin=FRUSTUM_MARGIN,
    edge_boost=False,
):
    tan_half_h = math.tan(max(1e-9, float(h_fov)) * 0.5)
    tan_half_v = math.tan(max(1e-9, float(v_fov)) * 0.5)
    ortho_half_w, ortho_half_h = _orthographic_half_extents(ortho_scale, res_x, res_y)

    if not _is_earth_in_view(
        cam_pos_local,
        cam_forward_local,
        cam_right_local,
        cam_up_local,
        earth_radius,
        camera_type,
        tan_half_h,
        tan_half_v,
        ortho_half_w,
        ortho_half_h,
        frustum_margin,
    ):
        return set(), None

    radius_sq = float(earth_radius) * float(earth_radius)
    uv_samples = _tile_sample_uv(z)
    final_tiles = set()
    nearest_distance = None
    guard_distances = _collect_guard_hit_distances(
        z=z,
        earth_radius=earth_radius,
        cam_pos_local=cam_pos_local,
        cam_forward_local=cam_forward_local,
        cam_right_local=cam_right_local,
        cam_up_local=cam_up_local,
        camera_type=camera_type,
        h_fov=h_fov,
        v_fov=v_fov,
        res_x=res_x,
        res_y=res_y,
        ortho_scale=ortho_scale,
        frustum_margin=frustum_margin,
        edge_boost=edge_boost,
    )

    for x, y in _candidate_tiles_for_level(z, guard_distances, edge_boost=edge_boost):
        min_distance = None
        points = _tile_sample_points(x, y, z, earth_radius, uv_samples)
        for point in points:
            if not _point_on_visible_hemisphere(point, cam_pos_local, radius_sq):
                continue
            if not _point_in_camera_view(
                point,
                cam_pos_local,
                cam_forward_local,
                cam_right_local,
                cam_up_local,
                camera_type,
                tan_half_h,
                tan_half_v,
                ortho_half_w,
                ortho_half_h,
                frustum_margin,
            ):
                continue
            distance = (point - cam_pos_local).length
            if min_distance is None or distance < min_distance:
                min_distance = distance

        if min_distance is None:
            continue

        required_mpp = _required_mpp_from_distance(
            distance=min_distance,
            earth_radius=earth_radius,
            camera_type=camera_type,
            h_fov=h_fov,
            v_fov=v_fov,
            res_x=res_x,
            res_y=res_y,
            ortho_scale=ortho_scale,
        )
        d_value = compute_d_value(required_mpp, z, bias_factor=bias_factor)
        final_tiles.add(format_tile(x, y, z, d_value))
        if nearest_distance is None or min_distance < nearest_distance:
            nearest_distance = min_distance

    guard_tiles, guard_nearest_distance = _collect_guard_tiles_for_frustum(
        z=z,
        earth_radius=earth_radius,
        cam_pos_local=cam_pos_local,
        cam_forward_local=cam_forward_local,
        cam_right_local=cam_right_local,
        cam_up_local=cam_up_local,
        camera_type=camera_type,
        h_fov=h_fov,
        v_fov=v_fov,
        res_x=res_x,
        res_y=res_y,
        ortho_scale=ortho_scale,
        bias_factor=bias_factor,
        frustum_margin=frustum_margin,
        guard_distances=guard_distances,
        edge_boost=edge_boost,
    )
    final_tiles.update(guard_tiles)
    if guard_nearest_distance is not None and (nearest_distance is None or guard_nearest_distance < nearest_distance):
        nearest_distance = guard_nearest_distance

    return final_tiles, nearest_distance


def _derive_child_d(parent_d, child_z):
    allowed = D_LEVELS_BY_Z.get(int(child_z), [int(child_z)])
    not_worse = [d for d in allowed if d <= int(parent_d)]
    if not_worse:
        return max(not_worse)
    return min(allowed)


def _split_tile_one_level(tile):
    parsed = parse_tile(tile)
    if not parsed:
        return []
    x, y, z, d = parsed
    child_z = ONE_PASS_REFINEMENT_CHILD_Z.get(int(z))
    if not child_z:
        return []
    child_d = _derive_child_d(d, child_z)
    return [
        format_tile((x + dx) % 360, y + dy, child_z, child_d)
        for dx in (0, child_z)
        for dy in (0, child_z)
        if 0 <= (y + dy) <= 179
    ]


def _tile_min_visible_distance(
    x,
    y,
    z,
    earth_radius,
    cam_pos_local,
    cam_forward_local,
    cam_right_local,
    cam_up_local,
    camera_type,
    tan_half_h,
    tan_half_v,
    ortho_half_w,
    ortho_half_h,
    frustum_margin,
):
    radius_sq = float(earth_radius) * float(earth_radius)
    uv_samples = _tile_sample_uv(z)
    points = _tile_sample_points(x, y, z, earth_radius, uv_samples)

    min_distance = None
    for point in points:
        if not _point_on_visible_hemisphere(point, cam_pos_local, radius_sq):
            continue
        if not _point_in_camera_view(
            point,
            cam_pos_local,
            cam_forward_local,
            cam_right_local,
            cam_up_local,
            camera_type,
            tan_half_h,
            tan_half_v,
            ortho_half_w,
            ortho_half_h,
            frustum_margin,
        ):
            continue
        distance = (point - cam_pos_local).length
        if min_distance is None or distance < min_distance:
            min_distance = distance
    return min_distance


def _one_pass_selective_refinement(
    tiles,
    earth_radius,
    cam_pos_local,
    cam_forward_local,
    cam_right_local,
    cam_up_local,
    camera_type,
    h_fov,
    v_fov,
    res_x,
    res_y,
    ortho_scale,
    frustum_margin=FRUSTUM_MARGIN,
):
    if not tiles:
        return []

    tan_half_h = math.tan(max(1e-9, float(h_fov)) * 0.5)
    tan_half_v = math.tan(max(1e-9, float(v_fov)) * 0.5)
    ortho_half_w, ortho_half_h = _orthographic_half_extents(ortho_scale, res_x, res_y)

    refined = []
    for tile in tiles:
        children = _split_tile_one_level(tile)
        if not children:
            refined.append(tile)
            continue

        visible_children = []
        for child in children:
            parsed = parse_tile(child)
            if not parsed:
                continue
            x, y, z, _ = parsed
            min_distance = _tile_min_visible_distance(
                x=x,
                y=y,
                z=z,
                earth_radius=earth_radius,
                cam_pos_local=cam_pos_local,
                cam_forward_local=cam_forward_local,
                cam_right_local=cam_right_local,
                cam_up_local=cam_up_local,
                camera_type=camera_type,
                tan_half_h=tan_half_h,
                tan_half_v=tan_half_v,
                ortho_half_w=ortho_half_w,
                ortho_half_h=ortho_half_h,
                frustum_margin=frustum_margin,
            )
            if min_distance is not None:
                visible_children.append(child)

        if 0 < len(visible_children) < len(children):
            refined.extend(visible_children)
        else:
            refined.append(tile)

    deduped = list(dict.fromkeys(refined))
    return sorted(
        deduped,
        key=lambda tile: (
            parse_tile(tile)[3] if parse_tile(tile) else 10**9,
            (parse_tile(tile)[3] / parse_tile(tile)[2]) if parse_tile(tile) else 10**9,
            tile,
        ),
    )


def _coarsen_tile_one_d_level(tile):
    parsed = parse_tile(tile)
    if not parsed:
        return tile
    x, y, z, d = parsed
    allowed = sorted(set(D_LEVELS_BY_Z.get(int(z), [int(z)])))
    if not allowed:
        return tile
    if int(d) not in allowed:
        allowed.append(int(d))
        allowed = sorted(set(allowed))
    for candidate in allowed:
        if candidate > int(d):
            return format_tile(x, y, z, candidate)
    return tile


def _coarsen_tiles_one_d_level(tiles):
    coarsened = [_coarsen_tile_one_d_level(tile) for tile in (tiles or [])]
    return sorted(
        list(dict.fromkeys(coarsened)),
        key=lambda tile: (
            parse_tile(tile)[3] if parse_tile(tile) else 10**9,
            (parse_tile(tile)[3] / parse_tile(tile)[2]) if parse_tile(tile) else 10**9,
            tile,
        ),
    )


def _coarsen_tiles_n_d_levels(tiles, steps):
    count = max(0, int(steps))
    result = list(tiles or [])
    for _ in range(count):
        result = _coarsen_tiles_one_d_level(result)
    return result


def _apply_texture_quality_mode(tiles, scene):
    mode = _texture_quality_mode(scene)
    if mode == "HALF":
        return _coarsen_tiles_n_d_levels(tiles, 1)
    if mode == "QUARTER":
        return _coarsen_tiles_n_d_levels(tiles, 2)
    return list(tiles or [])


def _find_active_view3d_context():
    context = bpy.context
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
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        return area, space, rv3d, region

    wm = getattr(context, "window_manager", None)
    if not wm:
        return None
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = getattr(area.spaces, "active", None)
            if not space or space.type != 'VIEW_3D':
                continue
            rv3d = getattr(space, "region_3d", None)
            if rv3d is None:
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            return area, space, rv3d, region
    return None


def _active_view_camera_info(scene):
    view_context = _find_active_view3d_context()
    if view_context is None:
        return None
    _area, space, rv3d, region = view_context

    if str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
        return None

    cam_matrix = rv3d.view_matrix.inverted()
    cam_pos = cam_matrix.translation.copy()
    cam_forward = (-cam_matrix.col[2].xyz).normalized()
    cam_right = cam_matrix.col[0].xyz.normalized()
    cam_up = cam_matrix.col[1].xyz.normalized()

    viewport_w = float(getattr(region, "width", 0)) if region else 0.0
    viewport_h = float(getattr(region, "height", 0)) if region else 0.0
    if viewport_w <= 0.0 or viewport_h <= 0.0:
        viewport_w, viewport_h = _render_resolution_px(scene)

    is_perspective = bool(getattr(rv3d, "is_perspective", True))
    if is_perspective:
        lens = max(1e-6, float(getattr(space, "lens", 50.0)))
        sensor_width = 36.0
        h_fov = 2.0 * math.atan(sensor_width / (2.0 * lens))
        aspect_ratio = max(1e-6, viewport_w / max(1.0, viewport_h))
        v_fov = 2.0 * math.atan(math.tan(h_fov * 0.5) / aspect_ratio)
        camera_type = "PERSP"
        ortho_scale = 1.0
    else:
        h_fov = math.radians(50.0)
        v_fov = math.radians(35.0)
        camera_type = "ORTHO"
        ortho_scale = max(1e-6, float(getattr(rv3d, "view_distance", 1.0)) * 2.0)

    return {
        "position": cam_pos,
        "forward": cam_forward,
        "right": cam_right,
        "up": cam_up,
        "h_fov": h_fov,
        "v_fov": v_fov,
        "camera_type": camera_type,
        "ortho_scale": ortho_scale,
        "res_x": viewport_w,
        "res_y": viewport_h,
    }


def get_camera_info(scene, scope_mode="AUTO"):
    requested_scope = str(scope_mode or "AUTO")

    if requested_scope == "AUTO":
        active_view_info = _active_view_camera_info(scene)
        if active_view_info is not None:
            active_view_info["scope_used"] = "ACTIVE_VIEW"
            return active_view_info
    elif requested_scope == "ACTIVE_VIEW":
        active_view_info = _active_view_camera_info(scene)
        if active_view_info is not None:
            active_view_info["scope_used"] = "ACTIVE_VIEW"
            return active_view_info

    cam = scene.camera
    if cam is None:
        raise RuntimeError(
            "Planetka error: No active camera set.\n"
            "Please assign a camera in Scene Properties → Camera, "
            "or select which camera Planetka should use."
        )

    cam_matrix = cam.matrix_world
    cam_pos = cam_matrix.translation.copy()
    cam_forward = (-cam_matrix.col[2].xyz).normalized()
    cam_right = cam_matrix.col[0].xyz.normalized()
    cam_up = cam_matrix.col[1].xyz.normalized()
    res_x, res_y = _render_resolution_px(scene)

    if cam.data.type == "PERSP":
        h_fov = cam.data.angle_x
        v_fov = cam.data.angle_y
    else:
        focal_length = float(getattr(cam.data, "lens", 0.0))
        sensor_width = float(getattr(cam.data, "sensor_width", 36.0))
        aspect_ratio = res_x / max(1.0, res_y)
        h_fov = (
            2.0 * math.atan(sensor_width / (2.0 * focal_length))
            if focal_length
            else math.radians(50.0)
        )
        v_fov = 2.0 * math.atan(math.tan(h_fov / 2.0) / aspect_ratio)

    return {
        "position": cam_pos,
        "forward": cam_forward,
        "right": cam_right,
        "up": cam_up,
        "h_fov": h_fov,
        "v_fov": v_fov,
        "camera_type": str(getattr(cam.data, "type", "PERSP")),
        "ortho_scale": float(getattr(cam.data, "ortho_scale", 1.0)),
        "res_x": res_x,
        "res_y": res_y,
        "scope_used": "CAMERA",
    }


def main(scope_mode="AUTO", edge_boost=False):
    scene = bpy.context.scene
    camera_info = get_camera_info(scene, scope_mode=scope_mode)
    cam_pos_world = camera_info["position"]
    h_fov = camera_info["h_fov"]
    v_fov = camera_info["v_fov"]
    camera_type = camera_info["camera_type"]
    ortho_scale = float(camera_info["ortho_scale"])
    res_x = float(camera_info["res_x"])
    res_y = float(camera_info["res_y"])
    cam_forward_world = camera_info["forward"]
    cam_right_world = camera_info["right"]
    cam_up_world = camera_info["up"]
    scope_used = str(camera_info.get("scope_used", "CAMERA"))
    try:
        scene[LAST_SCOPE_USED_KEY] = scope_used
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing resolve scope in scene diagnostics", exc_info=True)
    bias_factor = _resolution_bias_factor(scene)

    earth = get_earth_object()
    earth_radius = get_planet_radius(earth)
    root = get_planet_root()

    if earth:
        earth_center_world = earth.matrix_world.translation
        cam_dist_from_center = (cam_pos_world - earth_center_world).length
        camera_altitude = cam_dist_from_center - earth_radius
    elif root:
        earth_center_world = root.matrix_world.translation
        cam_dist_from_center = (cam_pos_world - earth_center_world).length
        camera_altitude = cam_dist_from_center - earth_radius
    else:
        camera_altitude = cam_pos_world.length - earth_radius

    logger.debug("Camera altitude: %s Blender Units", camera_altitude)
    logger.debug("Earth radius: %s Blender Units", earth_radius)

    if camera_altitude < 0:
        try:
            if LAST_REQUIRED_MPP_KEY in scene:
                del scene[LAST_REQUIRED_MPP_KEY]
            if LAST_TARGET_D_KEY in scene:
                del scene[LAST_TARGET_D_KEY]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed clearing tile target diagnostics for below-surface camera", exc_info=True)
        write_tile_view_diagnostics(
            scene=scene,
            camera_altitude_bu=float(camera_altitude),
            nearest_visible_distance_bu=None,
            earth_radius_bu=earth_radius,
        )
        return []

    required_mpp_near = _required_mpp_from_distance(
        distance=max(0.0, float(camera_altitude)),
        earth_radius=earth_radius,
        camera_type=camera_type,
        h_fov=h_fov,
        v_fov=v_fov,
        res_x=res_x,
        res_y=res_y,
        ortho_scale=ortho_scale,
    )
    target_z_mpp = int(compute_z_value(required_mpp_near, bias_factor=bias_factor))
    target_z = target_z_mpp
    logger.debug(
        "z target: %s (mpp=%s)",
        target_z,
        target_z_mpp,
    )

    cam_pos_local, cam_forward_local, cam_right_local, cam_up_local = _transform_to_planet_space(
        cam_pos_world,
        cam_forward_world,
        cam_right_world,
        cam_up_world,
        earth,
        root,
    )

    candidate_z_levels = [z_level for z_level in Z_LEVELS if int(target_z) <= int(z_level) <= 180]
    if not candidate_z_levels:
        candidate_z_levels = [180]

    selected_tiles = set()
    selected_z = None
    selected_nearest_distance = None
    frustum_margin = ACTIVE_VIEW_FRUSTUM_MARGIN if scope_used == "ACTIVE_VIEW" else FRUSTUM_MARGIN
    visibility_edge_boost = bool(edge_boost or scope_used == "ACTIVE_VIEW")

    for z_level in candidate_z_levels:
        visible_tiles, nearest_distance = _collect_visible_tiles(
            z=z_level,
            cam_pos_local=cam_pos_local,
            cam_forward_local=cam_forward_local,
            cam_right_local=cam_right_local,
            cam_up_local=cam_up_local,
            earth_radius=earth_radius,
            camera_type=camera_type,
            h_fov=h_fov,
            v_fov=v_fov,
            res_x=res_x,
            res_y=res_y,
            ortho_scale=ortho_scale,
            bias_factor=bias_factor,
            frustum_margin=frustum_margin,
            edge_boost=visibility_edge_boost,
        )
        if not visible_tiles:
            continue
        selected_z = int(z_level)
        selected_nearest_distance = nearest_distance
        selected_tiles = set(visible_tiles)
        break

    if selected_z is None or not selected_tiles:
        try:
            scene[LAST_REQUIRED_MPP_KEY] = float(required_mpp_near)
            scene[LAST_TARGET_D_KEY] = int(_target_d_from_required_mpp(required_mpp_near))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed writing tile target diagnostics", exc_info=True)
        write_tile_view_diagnostics(
            scene=scene,
            camera_altitude_bu=float(camera_altitude),
            nearest_visible_distance_bu=None,
            earth_radius_bu=earth_radius,
        )
        return []

    required_mpp_selected = required_mpp_near
    if selected_nearest_distance is not None:
        required_mpp_selected = _required_mpp_from_distance(
            distance=float(selected_nearest_distance),
            earth_radius=earth_radius,
            camera_type=camera_type,
            h_fov=h_fov,
            v_fov=v_fov,
            res_x=res_x,
            res_y=res_y,
            ortho_scale=ortho_scale,
        )
    try:
        scene[LAST_REQUIRED_MPP_KEY] = float(required_mpp_selected)
        scene[LAST_TARGET_D_KEY] = int(_target_d_from_required_mpp(required_mpp_selected))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed writing selected tile diagnostics", exc_info=True)

    final_tiles = find_optimizable_tiles(list(selected_tiles))
    final_tiles = _one_pass_selective_refinement(
        tiles=final_tiles,
        earth_radius=earth_radius,
        cam_pos_local=cam_pos_local,
        cam_forward_local=cam_forward_local,
        cam_right_local=cam_right_local,
        cam_up_local=cam_up_local,
        camera_type=camera_type,
        h_fov=h_fov,
        v_fov=v_fov,
        res_x=res_x,
        res_y=res_y,
        ortho_scale=ortho_scale,
        frustum_margin=frustum_margin,
    )
    final_tiles = _apply_texture_quality_mode(final_tiles, scene)
    if scope_used == "ACTIVE_VIEW" and _use_active_view_coarse_textures(scene):
        final_tiles = _coarsen_tiles_one_d_level(final_tiles)
    write_tile_view_diagnostics(
        scene=scene,
        camera_altitude_bu=float(camera_altitude),
        nearest_visible_distance_bu=None if selected_nearest_distance is None else float(selected_nearest_distance),
        earth_radius_bu=earth_radius,
    )
    return final_tiles
