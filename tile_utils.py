import logging
import math
import re
from collections import defaultdict

import bpy
import mathutils
from mathutils import Vector

from .diagnostics import write_tile_view_diagnostics
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs

logger = logging.getLogger(__name__)

REAL_EARTH_RADIUS_M = 6371000.0
DATASET_MPP_BASE_D1 = 10.0
# Bias tile upgrades to happen a bit earlier than strict mathematical minimum.
# 0.75 means target detail is requested at 75% of nominal threshold distance.
QUALITY_SAFETY_MARGIN = 0.75
MAX_TERRAIN_HEIGHT_M = 9000.0
DEFAULT_PLANET_RADIUS_BU = 1.0
Z_LEVELS = (1, 2, 4, 8, 15, 30, 60, 90, 180, 360)
MAX_RESOLVE_Z_LEVEL = 180
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
# Active View intentionally over-scans to reduce edge dropouts when the user
# orbits in perspective viewport (treat as ~2x wider capture window).
ACTIVE_VIEW_FRUSTUM_MARGIN = 2.0
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
LAST_PANORAMA_MODE_KEY = "planetka_last_panorama_mode"
LAST_PANORAMA_LIMIT_EXCEEDED_KEY = "planetka_last_panorama_limit_exceeded"
LAST_PANORAMA_REQUIRED_TILES_KEY = "planetka_last_panorama_required_tiles"
LAST_PANORAMA_REQUIRED_Z_KEY = "planetka_last_panorama_required_z"
LAST_SELECTED_Z_LEVEL_KEY = "planetka_last_selected_z_level"
LAST_Z_SWITCH_DISTANCE_KEY = "planetka_last_z_switch_distance_bu"
TEMPORAL_HYSTERESIS_DISTANCE_RATIO = 0.05  # 5%
MAX_SHADER_TILE_BUDGET = 12
# Padding low tile counts with synthetic placeholder slots can trigger
# EEVEE/Metal sampler overflow in some camera states (e.g. Cairo frame 105).
# Keep only real resolved tiles unless future renderer-safe padding is introduced.
MIN_SHADER_TILE_FLOOR = 0
SHADER_PAD_TILE_PREFIX = "__PKA_PAD_TILE"
VIEWPORT_RESOLUTION_X = 1920.0
VIEWPORT_RESOLUTION_Y = 1080.0
LAST_TILE_BUDGET_TRACE = []
LAST_TILE_BUDGET_INPUT = []
LAST_TILE_BUDGET_OUTPUT = []
LAST_FULL_SOURCE_TILES_KEY = "planetka_last_full_source_tiles"
ADAPTIVE_HORIZON_PRECISION_ENABLED = True
ADAPTIVE_HORIZON_REFINE_MAX_Z = 2
ADAPTIVE_HORIZON_NEAR_MISS_NDC_THRESHOLD = 0.012
ADAPTIVE_HORIZON_FORCE_INCLUDE_NDC_THRESHOLD = 0.0045
ADAPTIVE_HORIZON_NEAR_HEMISPHERE_NORM_THRESHOLD = 0.01
ANIMATION_ADAPTIVE_HORIZON_SCENE_KEY = "planetka_anim_adaptive_horizon_precision"
ANIMATION_HORIZON_HYSTERESIS_NDC_THRESHOLD = 0.008
ANIMATION_HORIZON_HYSTERESIS_HEMISPHERE_NORM_THRESHOLD = 0.015
ANIMATION_HORIZON_HYSTERESIS_MAX_RETAINED_TILES = 1
ANIMATION_HORIZON_BAND_FRONT_DEG = 0.5
ANIMATION_HORIZON_BAND_STEP_DEG = 0.25
ANIMATION_HORIZON_BAND_U_SAMPLES = 101
ANIMATION_HORIZON_BAND_VIEW_NDC_MARGIN = 0.02
ANIMATION_HORIZON_BAND_V_SCAN_MIN = -1.5
ANIMATION_HORIZON_BAND_V_SCAN_MAX = 1.5
ANIMATION_HORIZON_BAND_V_SCAN_STEPS = 180
ANIMATION_HORIZON_BAND_BACK_DEG = math.degrees(
    math.acos(REAL_EARTH_RADIUS_M / (REAL_EARTH_RADIUS_M + MAX_TERRAIN_HEIGHT_M))
)


def get_earth_radius_blender_units(earth_obj):
    if not earth_obj:
        return 1.0

    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed reading stored Earth local radius metadata", exc_info=True)
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
        except (RuntimeError, TypeError, ValueError, AttributeError):
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


def _equivalent_d(a, b):
    return {int(a), int(b)} in ({15, 16}, {30, 32}, {60, 64})


def _quality_not_worse(parent_d, child_d):
    parent_d = int(parent_d)
    child_d = int(child_d)
    return parent_d <= child_d or _equivalent_d(parent_d, child_d)


def _sort_tiles_for_apply(tiles):
    def _sort_key(tile):
        parsed = parse_tile(tile)
        if not parsed:
            return (10_000, 10_000, str(tile))
        _, _, z, d = parsed
        ratio = float(d) / max(1.0, float(z))
        return (int(d), ratio, str(tile))

    return sorted(set(tiles), key=_sort_key)


def _tile_bounds(parsed_tile):
    x, y, z, _d = parsed_tile
    x0 = int(x)
    y0 = int(y)
    x1 = x0 + int(z)
    y1 = y0 + int(z)
    return x0, y0, x1, y1


def _bounds_overlap(ax0, ay0, ax1, ay1, bx0, by0, bx1, by1):
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _tile_center_distance_from_camera(tile, cam_pos_local=None, earth_radius=None):
    if cam_pos_local is None or earth_radius is None:
        return 0.0
    parsed = parse_tile(tile)
    if not parsed:
        return 0.0
    x, y, z, _d = parsed
    lon = ((float(x) + (float(z) * 0.5)) % 360.0) - 180.0
    lat = max(0.0, min(179.999999, float(y) + (float(z) * 0.5)))
    try:
        cx, cy, cz = lonlat_to_cartesian(lon, lat, float(earth_radius))
        tile_center = Vector((float(cx), float(cy), float(cz)))
        return float((tile_center - cam_pos_local).length)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return 0.0


def _select_parent_d_for_merge(parent_z, child_ds):
    parent_z = int(parent_z)
    child_ds = [int(d) for d in child_ds]
    if not child_ds:
        return None
    allowed = sorted({int(d) for d in D_LEVELS_BY_Z.get(parent_z, [parent_z])})
    candidates = [d for d in allowed if all(_quality_not_worse(d, cd) for cd in child_ds)]
    if candidates:
        return max(candidates)
    # Fallback for equivalent sets in mixed decimal/power ecosystems.
    relaxed = []
    for d in allowed:
        ok = True
        for cd in child_ds:
            if not (_quality_not_worse(d, cd) or _equivalent_d(d, cd)):
                ok = False
                break
        if ok:
            relaxed.append(d)
    if relaxed:
        return max(relaxed)
    return None


def _build_strict_budget_merge_proposals(current_tiles):
    parsed = {}
    for tile in current_tiles:
        info = parse_tile(tile)
        if info:
            parsed[tile] = info

    buckets = defaultdict(list)
    for tile, (x, y, z, d) in parsed.items():
        if not is_mergeable(z):
            continue
        parent_z = int(z) * 2
        parent_x = (int(x) // parent_z) * parent_z
        parent_y = (int(y) // parent_z) * parent_z
        key = (parent_x, parent_y, parent_z)
        buckets[key].append((tile, int(d)))

    proposals = []
    for (parent_x, parent_y, parent_z), children in buckets.items():
        if len(children) < 2:
            continue
        child_tiles = sorted({tile for tile, _d in children})
        child_ds = [d for _tile, d in children]
        parent_d = _select_parent_d_for_merge(parent_z, child_ds)
        if parent_d is None:
            continue
        parent_tile = format_tile(parent_x, parent_y, parent_z, parent_d)
        reduction = len(child_tiles) - 1
        if reduction <= 0:
            continue
        proposals.append(
            {
                "mode": "strict_parent_merge",
                "parent_tile": parent_tile,
                "parent_d": int(parent_d),
                "parent_z": int(parent_z),
                "children": child_tiles,
                "child_ds": child_ds,
                "reduction": int(reduction),
                "area_growth": 0,
            }
        )

    proposals.sort(
        key=lambda p: (
            -int(p["reduction"]),
            int(p.get("area_growth", 0)),
            int(p["parent_d"]),
            -int(p["parent_z"]),
            str(p["parent_tile"]),
        )
    )
    return proposals


def _build_same_d_parent_cover_proposals(current_tiles):
    parsed = {}
    for tile in current_tiles:
        info = parse_tile(tile)
        if info:
            parsed[tile] = info

    ancestor_buckets = defaultdict(set)
    for tile, (x, y, z, d) in parsed.items():
        ancestor_z = int(z)
        while is_mergeable(ancestor_z):
            parent_z = int(ancestor_z) * 2
            parent_x = (int(x) // parent_z) * parent_z
            parent_y = (int(y) // parent_z) * parent_z
            ancestor_buckets[(parent_x, parent_y, parent_z, int(d))].add(tile)
            ancestor_z = int(parent_z)

    proposals = []
    for (parent_x, parent_y, parent_z, parent_d), child_set in ancestor_buckets.items():
        child_tiles = sorted(child_set)
        if len(child_tiles) < 2:
            continue

        allowed_parent_ds = {int(d) for d in D_LEVELS_BY_Z.get(int(parent_z), [int(parent_z)])}
        if int(parent_d) not in allowed_parent_ds:
            continue

        parent_x0 = int(parent_x)
        parent_y0 = int(parent_y)
        parent_x1 = int(parent_x) + int(parent_z)
        parent_y1 = int(parent_y) + int(parent_z)

        child_area = 0
        blocked = False
        for child in child_tiles:
            child_info = parsed.get(child)
            if child_info is None:
                blocked = True
                break
            cx0, cy0, cx1, cy1 = _tile_bounds(child_info)
            if not (cx0 >= parent_x0 and cy0 >= parent_y0 and cx1 <= parent_x1 and cy1 <= parent_y1):
                blocked = True
                break
            child_area += int(child_info[2]) * int(child_info[2])
        if blocked:
            continue

        for other_tile, other_info in parsed.items():
            if other_tile in child_set:
                continue
            ox0, oy0, ox1, oy1 = _tile_bounds(other_info)
            if _bounds_overlap(parent_x0, parent_y0, parent_x1, parent_y1, ox0, oy0, ox1, oy1):
                blocked = True
                break
        if blocked:
            continue

        reduction = len(child_tiles) - 1
        if reduction <= 0:
            continue

        parent_tile = format_tile(int(parent_x), int(parent_y), int(parent_z), int(parent_d))
        area_growth = max(0, int(parent_z) * int(parent_z) - int(child_area))
        proposals.append(
            {
                "mode": "same_d_expand",
                "parent_tile": parent_tile,
                "parent_d": int(parent_d),
                "parent_z": int(parent_z),
                "children": child_tiles,
                "child_ds": [int(parent_d) for _ in child_tiles],
                "reduction": int(reduction),
                "area_growth": int(area_growth),
            }
        )

    proposals.sort(
        key=lambda p: (
            -int(p["reduction"]),
            int(p.get("area_growth", 0)),
            int(p["parent_d"]),
            -int(p["parent_z"]),
            str(p["parent_tile"]),
        )
    )
    return proposals


def _build_budget_merge_proposals(current_tiles):
    strict = _build_strict_budget_merge_proposals(current_tiles)
    same_d_expand = _build_same_d_parent_cover_proposals(current_tiles)
    proposals = list(strict) + list(same_d_expand)
    mode_order = {
        "strict_parent_merge": 0,
        "same_d_expand": 1,
    }
    proposals.sort(
        key=lambda p: (
            int(mode_order.get(str(p.get("mode", "")), 99)),
            -int(p["reduction"]),
            int(p.get("area_growth", 0)),
            int(p["parent_d"]),
            -int(p["parent_z"]),
            str(p["parent_tile"]),
        )
    )
    return proposals


def _apply_destructive_budget_trim(current_tiles, max_tiles, cam_pos_local=None, earth_radius=None):
    current = set(current_tiles)
    removed = []
    while len(current) > int(max_tiles):
        scored = []
        for tile in current:
            parsed = parse_tile(tile)
            if parsed:
                _x, _y, z, d = parsed
                ratio = float(d) / max(1.0, float(z))
            else:
                ratio = float("inf")
            distance = _tile_center_distance_from_camera(
                tile,
                cam_pos_local=cam_pos_local,
                earth_radius=earth_radius,
            )
            scored.append((float(ratio), float(distance), str(tile), tile))

        if not scored:
            break
        scored.sort(key=lambda item: (-float(item[0]), -float(item[1]), str(item[2])))
        ratio, distance, _tile_name, chosen_tile = scored[0]
        current.discard(chosen_tile)
        removed.append(
            {
                "mode": "destructive_drop",
                "dropped": str(chosen_tile),
                "ratio": float(ratio),
                "distance": float(distance),
                "reduction": 1,
            }
        )
    return current, removed


def _next_coarser_d_for_tile(tile):
    parsed = parse_tile(tile)
    if not parsed:
        return None
    _x, _y, z, d = parsed
    allowed = sorted({int(v) for v in D_LEVELS_BY_Z.get(int(z), [int(z)])})
    if not allowed:
        return None
    if int(d) not in allowed:
        allowed.append(int(d))
        allowed = sorted(set(allowed))
    for candidate in allowed:
        if int(candidate) > int(d):
            return int(candidate)
    return None


def _replace_tile_d(tile, new_d):
    parsed = parse_tile(tile)
    if not parsed:
        return str(tile)
    x, y, z, _d = parsed
    return format_tile(int(x), int(y), int(z), int(new_d))


def _apply_budget_merges_only(current_tiles, max_tiles):
    current = set(current_tiles or ())
    trace = []

    for _ in range(128):
        if len(current) <= int(max_tiles):
            break
        proposals = _build_budget_merge_proposals(current)
        if not proposals:
            break
        changed = False
        for proposal in proposals:
            if len(current) <= int(max_tiles):
                break
            children = proposal["children"]
            if any(child not in current for child in children):
                continue
            for child in children:
                current.discard(child)
            current.add(proposal["parent_tile"])
            trace.append(
                {
                    "mode": str(proposal.get("mode", "strict_parent_merge")),
                    "children": list(children),
                    "parent": str(proposal["parent_tile"]),
                    "parent_d": int(proposal["parent_d"]),
                    "parent_z": int(proposal["parent_z"]),
                    "reduction": int(proposal["reduction"]),
                    "area_growth": int(proposal.get("area_growth", 0)),
                }
            )
            changed = True
        if not changed:
            break

    return current, trace


def _apply_quality_degrade_budget_adjustment(
    current_tiles,
    max_tiles,
    cam_pos_local=None,
    earth_radius=None,
):
    current = set(current_tiles or ())
    trace = []
    visited = {frozenset(current)}
    max_steps = max(1, min(64, len(current) * 8))
    steps = 0

    while len(current) > int(max_tiles) and steps < max_steps:
        steps += 1
        candidates = []
        for tile in list(current):
            parsed = parse_tile(tile)
            if not parsed:
                continue
            _x, _y, _z, old_d = parsed
            next_d = _next_coarser_d_for_tile(tile)
            if next_d is None:
                continue
            replacement_tile = _replace_tile_d(tile, next_d)
            if str(replacement_tile) == str(tile):
                continue

            trial = set(current)
            trial.discard(tile)
            trial.add(replacement_tile)

            merged, merge_trace = _apply_budget_merges_only(trial, max_tiles=max_tiles)
            out_count = int(len(merged))
            solved = out_count <= int(max_tiles)
            distance = _tile_center_distance_from_camera(
                tile,
                cam_pos_local=cam_pos_local,
                earth_radius=earth_radius,
            )
            candidates.append(
                {
                    "from_tile": str(tile),
                    "to_tile": str(replacement_tile),
                    "from_d": int(old_d),
                    "to_d": int(next_d),
                    "distance": float(distance),
                    "out_count": int(out_count),
                    "solved": bool(solved),
                    "merged_state": set(merged),
                    "merge_trace": list(merge_trace),
                }
            )

        if not candidates:
            break

        # Preference:
        # 1) any candidate that reaches budget
        # 2) lowest resulting tile count
        # 3) when equivalent, coarsen the tile farther from camera first
        # 4) deterministic fallback by tile code
        candidates.sort(
            key=lambda c: (
                0 if bool(c["solved"]) else 1,
                int(c["out_count"]),
                -float(c["distance"]),
                str(c["from_tile"]),
                str(c["to_tile"]),
            )
        )
        best = candidates[0]
        merged_state = set(best["merged_state"])
        merged_key = frozenset(merged_state)
        if merged_key in visited:
            break
        visited.add(merged_key)

        reduction = int(len(current) - len(merged_state))
        trace.append(
            {
                "mode": "quality_degrade",
                "from_tile": str(best["from_tile"]),
                "to_tile": str(best["to_tile"]),
                "from_d": int(best["from_d"]),
                "to_d": int(best["to_d"]),
                "distance": float(best["distance"]),
                "reduction": int(reduction),
                "post_count": int(best["out_count"]),
            }
        )
        trace.extend(list(best["merge_trace"]))
        current = merged_state

    return current, trace


def _log_destructive_budget_trim(removed, before_trim_count, after_trim_count, max_tiles):
    if not removed:
        return
    removed_count = int(len(removed))
    budget_value = int(max_tiles)
    input_count = int(before_trim_count)
    output_count = int(after_trim_count)
    logger.debug(
        "Planetka: tile budget trim removed=%d input=%d output=%d budget=%d",
        removed_count,
        input_count,
        output_count,
        budget_value,
    )
    for index, event in enumerate(removed, start=1):
        dropped_tile = str(event.get("dropped", "") or "").strip()
        ratio = float(event.get("ratio", 0.0) or 0.0)
        distance = float(event.get("distance", 0.0) or 0.0)
        logger.debug(
            "Planetka: tile budget trimmed drop #%d/%d tile=%s ratio=%.6f distance=%.3f",
            int(index),
            removed_count,
            dropped_tile,
            ratio,
            distance,
        )


def _enforce_shader_tile_budget(
    tiles,
    max_tiles=MAX_SHADER_TILE_BUDGET,
    cam_pos_local=None,
    earth_radius=None,
):
    max_tiles = max(1, int(max_tiles))
    current = set(_sort_tiles_for_apply(tiles))
    trace = []

    if len(current) <= max_tiles:
        return _sort_tiles_for_apply(current), trace, True

    current, merge_trace = _apply_budget_merges_only(current, max_tiles=max_tiles)
    trace.extend(merge_trace)

    if len(current) > max_tiles:
        current, degrade_trace = _apply_quality_degrade_budget_adjustment(
            current,
            max_tiles=max_tiles,
            cam_pos_local=cam_pos_local,
            earth_radius=earth_radius,
        )
        trace.extend(degrade_trace)

    if len(current) > max_tiles:
        before_trim_count = len(current)
        current, removed = _apply_destructive_budget_trim(
            current,
            max_tiles=max_tiles,
            cam_pos_local=cam_pos_local,
            earth_radius=earth_radius,
        )
        if removed:
            trace.extend(removed)
            _log_destructive_budget_trim(
                removed,
                before_trim_count=int(before_trim_count),
                after_trim_count=len(current),
                max_tiles=int(max_tiles),
            )

    success = len(current) <= max_tiles
    return _sort_tiles_for_apply(current), trace, success


def _enforce_shader_tile_floor(tiles, min_tiles=MIN_SHADER_TILE_FLOOR, max_tiles=MAX_SHADER_TILE_BUDGET):
    min_tiles = max(0, int(min_tiles))
    max_tiles = max(1, int(max_tiles))
    target = min(min_tiles, max_tiles)

    current = list(_sort_tiles_for_apply(tiles))
    if not current:
        return current, []
    if len(current) >= target:
        return current, []

    existing = set(current)
    added = []
    pad_index = 1
    while len(current) < target:
        pad_tile = f"{SHADER_PAD_TILE_PREFIX}_{int(pad_index):02d}"
        pad_index += 1
        if pad_tile in existing:
            continue
        existing.add(pad_tile)
        current.append(pad_tile)
        added.append(pad_tile)
    return current, added


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


def _apply_temporal_z_hysteresis(scene, requested_z, distance_value):
    """Keep z-level stable near threshold using a tiny distance hysteresis band."""
    try:
        requested_z = int(requested_z)
    except (TypeError, ValueError):
        return requested_z

    if scene is None:
        return requested_z

    try:
        previous_z = int(scene.get(LAST_SELECTED_Z_LEVEL_KEY, 0) or 0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        previous_z = 0

    if previous_z <= 0 or previous_z == requested_z:
        return requested_z

    try:
        current_distance = max(0.0, float(distance_value))
    except (TypeError, ValueError):
        current_distance = 0.0

    try:
        switch_distance = max(
            0.0,
            float(scene.get(LAST_Z_SWITCH_DISTANCE_KEY, current_distance) or current_distance),
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        switch_distance = current_distance

    band = float(switch_distance) * float(TEMPORAL_HYSTERESIS_DISTANCE_RATIO)

    # Requested finer tiles (smaller z): require moving a bit closer than the
    # prior switch threshold.
    if requested_z < previous_z:
        if current_distance >= max(0.0, switch_distance - band):
            return previous_z
        return requested_z

    # Requested coarser tiles (larger z): require moving a bit farther than the
    # prior switch threshold.
    if current_distance <= (switch_distance + band):
        return previous_z
    return requested_z


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


def _tile_sample_uv_adaptive(z):
    z = int(z)
    if z <= 2:
        grid = 21
    elif z <= 4:
        grid = 19
    elif z <= 8:
        grid = 17
    else:
        grid = 15

    if grid <= 1:
        return ((0.5, 0.5),)

    uv = set()
    step = 1.0 / float(grid - 1)
    for i in range(grid):
        u = i * step
        for j in range(grid):
            v = j * step
            uv.add((u, v))

    # Add edge-biased half-step samples to catch thin horizon/frustum slivers.
    for i in range(grid - 1):
        u = (i + 0.5) * step
        uv.add((u, 0.0))
        uv.add((u, 1.0))
    for j in range(grid - 1):
        v = (j + 0.5) * step
        uv.add((0.0, v))
        uv.add((1.0, v))

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


def _point_view_state_and_overflow_ndc(
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
        return False, None, None

    x_val = rel.dot(cam_right_local)
    y_val = rel.dot(cam_up_local)

    if camera_type == "ORTHO":
        max_x = max(1e-9, float(ortho_half_w) * float(frustum_margin))
        max_y = max(1e-9, float(ortho_half_h) * float(frustum_margin))
    else:
        max_x = max(1e-9, float(depth) * float(tan_half_h) * float(frustum_margin))
        max_y = max(1e-9, float(depth) * float(tan_half_v) * float(frustum_margin))

    ndc_x = abs(float(x_val)) / max_x
    ndc_y = abs(float(y_val)) / max_y
    overflow_ndc = max(float(ndc_x) - 1.0, float(ndc_y) - 1.0)
    inside = overflow_ndc <= 0.0
    return bool(inside), float(overflow_ndc), float(rel.length)


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


def _evaluate_tile_visibility(
    points,
    *,
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
    radius_sq,
):
    threshold = float(radius_sq) * float(HORIZON_DOT_MARGIN)
    min_distance_visible = None
    min_distance_depth = None
    hemisphere_hits = 0
    camera_hits = 0
    both_hits = 0
    min_abs_horizon_norm = None
    min_positive_ndc_overflow = None
    has_depth_samples = False
    any_horizon_positive = False
    any_horizon_negative = False

    for point in points:
        horizon_margin = float(point.dot(cam_pos_local)) - threshold
        horizon_norm = float(horizon_margin) / max(float(radius_sq), 1e-9)
        if horizon_norm >= 0.0:
            any_horizon_positive = True
            hemisphere_hits += 1
        else:
            any_horizon_negative = True
        abs_horizon = abs(float(horizon_norm))
        if min_abs_horizon_norm is None or abs_horizon < min_abs_horizon_norm:
            min_abs_horizon_norm = abs_horizon

        inside_view, overflow_ndc, rel_distance = _point_view_state_and_overflow_ndc(
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
        )
        if overflow_ndc is None:
            continue
        has_depth_samples = True
        positive_overflow = max(0.0, float(overflow_ndc))
        if min_positive_ndc_overflow is None or positive_overflow < min_positive_ndc_overflow:
            min_positive_ndc_overflow = positive_overflow
        if min_distance_depth is None or rel_distance < min_distance_depth:
            min_distance_depth = float(rel_distance)
        if inside_view:
            camera_hits += 1
            if horizon_norm >= 0.0:
                both_hits += 1
                if min_distance_visible is None or rel_distance < min_distance_visible:
                    min_distance_visible = float(rel_distance)

    return {
        "hemisphere_hits": int(hemisphere_hits),
        "camera_hits": int(camera_hits),
        "both_hits": int(both_hits),
        "min_distance_visible": None if min_distance_visible is None else float(min_distance_visible),
        "min_distance_depth": None if min_distance_depth is None else float(min_distance_depth),
        "min_abs_horizon_norm": None if min_abs_horizon_norm is None else float(min_abs_horizon_norm),
        "min_positive_ndc_overflow": None if min_positive_ndc_overflow is None else float(min_positive_ndc_overflow),
        "has_depth_samples": bool(has_depth_samples),
        "horizon_crossing": bool(any_horizon_positive and any_horizon_negative),
    }


def _adaptive_horizon_precision_active():
    if not bool(ADAPTIVE_HORIZON_PRECISION_ENABLED):
        return False
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    try:
        return bool(scene.get(ANIMATION_ADAPTIVE_HORIZON_SCENE_KEY, False))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _cycles_render_engine_active():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    render = getattr(scene, "render", None)
    if render is None:
        return False
    try:
        engine = str(getattr(render, "engine", "") or "").strip().upper()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False
    return engine == "CYCLES"


def _should_adaptive_refine_tile(stats, z):
    if not _adaptive_horizon_precision_active():
        return False
    if int(z) > int(ADAPTIVE_HORIZON_REFINE_MAX_Z):
        return False
    if int(stats.get("both_hits", 0) or 0) > 0:
        return False
    if int(stats.get("hemisphere_hits", 0) or 0) <= 0:
        return False
    if not bool(stats.get("has_depth_samples", False)):
        return False
    overflow = stats.get("min_positive_ndc_overflow", None)
    if overflow is None:
        return False
    return float(overflow) <= float(ADAPTIVE_HORIZON_NEAR_MISS_NDC_THRESHOLD)


def _should_force_include_near_edge_tile(stats):
    if int(stats.get("both_hits", 0) or 0) > 0:
        return True
    if int(stats.get("hemisphere_hits", 0) or 0) <= 0:
        return False
    overflow = stats.get("min_positive_ndc_overflow", None)
    if overflow is None:
        return False
    near_horizon = bool(stats.get("horizon_crossing", False)) or (
        stats.get("min_abs_horizon_norm", None) is not None
        and float(stats.get("min_abs_horizon_norm", 1e9)) <= float(ADAPTIVE_HORIZON_NEAR_HEMISPHERE_NORM_THRESHOLD)
    )
    return bool(near_horizon) and float(overflow) <= float(ADAPTIVE_HORIZON_FORCE_INCLUDE_NDC_THRESHOLD)


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


def _ray_sphere_discriminant_for_ndc(
    *,
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
    u,
    v,
    earth_radius,
):
    if camera_type == "ORTHO":
        ray_origin = (
            cam_pos_local
            + cam_right_local * (float(u) * float(ortho_half_w) * float(frustum_margin))
            + cam_up_local * (float(v) * float(ortho_half_h) * float(frustum_margin))
        )
        ray_direction = cam_forward_local
    else:
        ray_origin = cam_pos_local
        ray_direction = (
            cam_forward_local
            + cam_right_local * (float(u) * float(tan_half_h) * float(frustum_margin))
            + cam_up_local * (float(v) * float(tan_half_v) * float(frustum_margin))
        )
        if ray_direction.length_squared <= 1e-12:
            return None, None, None, None, None
        ray_direction.normalize()

    a = float(ray_direction.dot(ray_direction))
    if a <= 1e-12:
        return None, None, None, None, None
    b = 2.0 * float(ray_origin.dot(ray_direction))
    c = float(ray_origin.dot(ray_origin)) - float(earth_radius) * float(earth_radius)
    discriminant = b * b - 4.0 * a * c
    return float(discriminant), ray_origin, ray_direction, float(a), float(b)


def _ray_hits_earth(discriminant, ray_origin, ray_direction, earth_radius):
    if discriminant is None or ray_origin is None or ray_direction is None:
        return False
    if float(discriminant) < 0.0:
        return False
    hit = _intersect_ray_sphere_nearest(ray_origin, ray_direction, earth_radius)
    return hit is not None


def _find_horizon_v_root_for_u(
    *,
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
    earth_radius,
    u,
):
    v_values = [
        float(ANIMATION_HORIZON_BAND_V_SCAN_MIN)
        + (float(ANIMATION_HORIZON_BAND_V_SCAN_MAX) - float(ANIMATION_HORIZON_BAND_V_SCAN_MIN))
        * (float(i) / float(max(1, int(ANIMATION_HORIZON_BAND_V_SCAN_STEPS))))
        for i in range(int(ANIMATION_HORIZON_BAND_V_SCAN_STEPS) + 1)
    ]

    samples = []
    for v in v_values:
        disc, ray_origin, ray_direction, _a, _b = _ray_sphere_discriminant_for_ndc(
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
            u=u,
            v=v,
            earth_radius=earth_radius,
        )
        if disc is None:
            continue
        samples.append(
            (
                float(v),
                float(disc),
                bool(_ray_hits_earth(disc, ray_origin, ray_direction, earth_radius)),
            )
        )

    if len(samples) < 2:
        return None

    transitions = []
    for idx in range(len(samples) - 1):
        v0, _d0, hit0 = samples[idx]
        v1, _d1, hit1 = samples[idx + 1]
        if bool(hit0) == bool(hit1):
            continue
        transitions.append((abs((float(v0) + float(v1)) * 0.5), idx))

    if not transitions:
        return None

    transitions.sort(key=lambda item: float(item[0]))
    _, idx = transitions[0]
    v0, d0, _h0 = samples[idx]
    v1, d1, _h1 = samples[idx + 1]

    if float(d0) == 0.0:
        return float(v0)
    if float(d1) == 0.0:
        return float(v1)

    if float(d0) * float(d1) > 0.0:
        return float(v0 if abs(float(d0)) <= abs(float(d1)) else v1)

    lo = float(v0)
    hi = float(v1)
    dlo = float(d0)
    for _ in range(52):
        mid = 0.5 * (lo + hi)
        dmid, _ro, _rd, _a, _b = _ray_sphere_discriminant_for_ndc(
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
            u=u,
            v=mid,
            earth_radius=earth_radius,
        )
        if dmid is None:
            break
        if abs(float(dmid)) < 1e-12:
            return float(mid)
        if float(dlo) * float(dmid) <= 0.0:
            hi = float(mid)
        else:
            lo = float(mid)
            dlo = float(dmid)
    return float(0.5 * (lo + hi))


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


def _collect_horizon_band_tiles(
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
):
    if str(camera_type or "").upper() == "ORTHO":
        return set(), None

    tan_half_h = math.tan(max(1e-9, float(h_fov)) * 0.5)
    tan_half_v = math.tan(max(1e-9, float(v_fov)) * 0.5)
    ortho_half_w, ortho_half_h = _orthographic_half_extents(ortho_scale, res_x, res_y)
    step = max(1, int(z))

    cam_norm = cam_pos_local.normalized() if cam_pos_local.length > 1e-12 else None
    if cam_norm is None:
        return set(), None

    horizon_tiles_by_key = {}
    nearest_distance = None
    view_ndc_margin = max(0.0, float(ANIMATION_HORIZON_BAND_VIEW_NDC_MARGIN))
    horizon_frustum_margin = 1.0

    back_band = float(ANIMATION_HORIZON_BAND_BACK_DEG)
    front_band = float(ANIMATION_HORIZON_BAND_FRONT_DEG)
    delta_values = []
    current = -front_band
    while current <= (back_band + 1e-9):
        delta_values.append(float(current))
        current += float(ANIMATION_HORIZON_BAND_STEP_DEG)

    for i in range(max(2, int(ANIMATION_HORIZON_BAND_U_SAMPLES))):
        u = -1.0 + 2.0 * (float(i) / float(max(1, int(ANIMATION_HORIZON_BAND_U_SAMPLES) - 1)))
        v_root = _find_horizon_v_root_for_u(
            cam_pos_local=cam_pos_local,
            cam_forward_local=cam_forward_local,
            cam_right_local=cam_right_local,
            cam_up_local=cam_up_local,
            camera_type=camera_type,
            tan_half_h=tan_half_h,
            tan_half_v=tan_half_v,
            ortho_half_w=ortho_half_w,
            ortho_half_h=ortho_half_h,
            frustum_margin=horizon_frustum_margin,
            earth_radius=earth_radius,
            u=u,
        )
        if v_root is None:
            continue
        if abs(float(v_root)) > (1.0 + view_ndc_margin):
            continue

        disc, ray_origin, ray_direction, a, b = _ray_sphere_discriminant_for_ndc(
            cam_pos_local=cam_pos_local,
            cam_forward_local=cam_forward_local,
            cam_right_local=cam_right_local,
            cam_up_local=cam_up_local,
            camera_type=camera_type,
            tan_half_h=tan_half_h,
            tan_half_v=tan_half_v,
            ortho_half_w=ortho_half_w,
            ortho_half_h=ortho_half_h,
            frustum_margin=horizon_frustum_margin,
            u=u,
            v=v_root,
            earth_radius=earth_radius,
        )
        if disc is None or ray_origin is None or ray_direction is None or a is None or b is None:
            continue

        t_tangent = -float(b) / (2.0 * float(a))
        if t_tangent <= 1e-8:
            continue
        tangent_point = ray_origin + ray_direction * float(t_tangent)
        if tangent_point.length <= 1e-12:
            continue
        tangent_dir = tangent_point.normalized()

        axis = cam_norm.cross(tangent_dir)
        if axis.length <= 1e-12:
            continue
        axis.normalize()

        cos_tangent = max(-1.0, min(1.0, float(cam_norm.dot(tangent_dir))))
        psi_tangent = math.acos(cos_tangent)

        for delta_deg in delta_values:
            psi = psi_tangent + math.radians(float(delta_deg))
            psi = max(0.0, min(math.pi, float(psi)))
            rotated = mathutils.Matrix.Rotation(float(psi), 3, axis) @ cam_norm
            if rotated.length <= 1e-12:
                continue
            rotated.normalize()
            surface_point = rotated * float(earth_radius)

            _inside_view, overflow_ndc, _distance = _point_view_state_and_overflow_ndc(
                surface_point,
                cam_pos_local=cam_pos_local,
                cam_forward_local=cam_forward_local,
                cam_right_local=cam_right_local,
                cam_up_local=cam_up_local,
                camera_type=camera_type,
                tan_half_h=tan_half_h,
                tan_half_v=tan_half_v,
                ortho_half_w=ortho_half_w,
                ortho_half_h=ortho_half_h,
                frustum_margin=1.0,
            )
            if overflow_ndc is None or float(overflow_ndc) > view_ndc_margin:
                continue

            lonlat = _cartesian_to_lonlat(surface_point)
            if lonlat is None:
                continue
            lon, lat = lonlat
            tile_at_level = get_tile_from_coordinates(lon, lat, z, z)
            parsed = parse_tile(tile_at_level) if tile_at_level else None
            if not parsed:
                continue
            x, y, _z, _d = parsed

            min_distance = float((surface_point - cam_pos_local).length)
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
            d_value = int(compute_d_value(required_mpp, z, bias_factor=bias_factor))
            key = (int(x), int(y), int(step))
            candidate = {
                "tile": format_tile(int(x), int(y), int(step), int(d_value)),
                "distance": float(min_distance),
                "abs_delta": abs(float(delta_deg)),
                "d_value": int(d_value),
            }
            existing = horizon_tiles_by_key.get(key)
            if existing is None:
                horizon_tiles_by_key[key] = candidate
            else:
                old_score = (float(existing["abs_delta"]), int(existing["d_value"]))
                new_score = (float(candidate["abs_delta"]), int(candidate["d_value"]))
                if new_score < old_score:
                    horizon_tiles_by_key[key] = candidate

            if nearest_distance is None or min_distance < nearest_distance:
                nearest_distance = min_distance

    horizon_tiles = {row["tile"] for row in horizon_tiles_by_key.values()}
    return horizon_tiles, nearest_distance


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
    adaptive_mode = _adaptive_horizon_precision_active()
    horizon_band_mode = _cycles_render_engine_active()
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
        if not adaptive_mode:
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
        else:
            stats = _evaluate_tile_visibility(
                points,
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
                radius_sq=radius_sq,
            )
            min_distance = stats.get("min_distance_visible", None)
            if min_distance is None and _should_adaptive_refine_tile(stats, z):
                adaptive_points = _tile_sample_points(x, y, z, earth_radius, _tile_sample_uv_adaptive(z))
                adaptive_stats = _evaluate_tile_visibility(
                    adaptive_points,
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
                    radius_sq=radius_sq,
                )
                min_distance = adaptive_stats.get("min_distance_visible", None)
                if min_distance is None and _should_force_include_near_edge_tile(adaptive_stats):
                    min_distance = adaptive_stats.get("min_distance_depth", None)

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

    if horizon_band_mode:
        horizon_tiles, horizon_nearest_distance = _collect_horizon_band_tiles(
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
        )
        base_tile_index = {}
        for tile in final_tiles:
            parsed = parse_tile(tile)
            if not parsed:
                continue
            x, y, z_level, d_value = parsed
            key = (int(x), int(y), int(z_level))
            existing = base_tile_index.get(key)
            if existing is None or int(d_value) > int(existing[3]):
                base_tile_index[key] = (int(x), int(y), int(z_level), int(d_value), str(tile))

        for tile in horizon_tiles:
            parsed = parse_tile(tile)
            if not parsed:
                continue
            x, y, z_level, _d_value = parsed
            key = (int(x), int(y), int(z_level))
            if key in base_tile_index:
                # Keep original regular-visibility tile quality for already selected coverage.
                continue
            final_tiles.add(tile)
        if horizon_nearest_distance is not None and (
            nearest_distance is None or horizon_nearest_distance < nearest_distance
        ):
            nearest_distance = horizon_nearest_distance

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
    adaptive_mode = _adaptive_horizon_precision_active()
    radius_sq = float(earth_radius) * float(earth_radius)
    uv_samples = _tile_sample_uv(z)
    points = _tile_sample_points(x, y, z, earth_radius, uv_samples)
    if not adaptive_mode:
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
        if min_distance is not None:
            return float(min_distance)
    else:
        stats = _evaluate_tile_visibility(
            points,
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
                radius_sq=radius_sq,
            )
        min_distance = stats.get("min_distance_visible", None)
        if min_distance is not None:
            return float(min_distance)

        if _should_adaptive_refine_tile(stats, z):
            adaptive_points = _tile_sample_points(x, y, z, earth_radius, _tile_sample_uv_adaptive(z))
            adaptive_stats = _evaluate_tile_visibility(
                adaptive_points,
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
                radius_sq=radius_sq,
            )
            min_distance = adaptive_stats.get("min_distance_visible", None)
            if min_distance is not None:
                return float(min_distance)
            if _should_force_include_near_edge_tile(adaptive_stats):
                fallback_distance = adaptive_stats.get("min_distance_depth", None)
                if fallback_distance is not None:
                    return float(fallback_distance)
    return None


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


def _store_last_full_source_tiles(scene, tiles):
    if scene is None:
        return
    try:
        scene[LAST_FULL_SOURCE_TILES_KEY] = _sort_tiles_for_apply(tiles)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing optimal source tiles for quality switching", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed storing optimal source tiles for quality switching", exc_info=True)


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

    cam_data_type = str(getattr(cam.data, "type", "PERSP"))
    panorama_type = str(getattr(cam.data, "panorama_type", ""))
    is_panorama_equirect = cam_data_type == "PANO" and panorama_type == "EQUIRECTANGULAR"

    if cam_data_type == "PERSP":
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
        "camera_type": cam_data_type,
        "is_panorama_equirect": bool(is_panorama_equirect),
        "ortho_scale": float(getattr(cam.data, "ortho_scale", 1.0)),
        "res_x": res_x,
        "res_y": res_y,
        "scope_used": "CAMERA",
    }


def _resolve_camera_local_context(scene, scope_mode="CAMERA"):
    camera_info = get_camera_info(scene, scope_mode=scope_mode)
    cam_pos_world = camera_info["position"]
    cam_forward_world = camera_info["forward"]
    cam_right_world = camera_info["right"]
    cam_up_world = camera_info["up"]
    earth = get_earth_object()
    root = get_planet_root()
    earth_radius = get_planet_radius(earth)
    cam_pos_local, cam_forward_local, cam_right_local, cam_up_local = _transform_to_planet_space(
        cam_pos_world,
        cam_forward_world,
        cam_right_world,
        cam_up_world,
        earth,
        root,
    )
    return {
        "camera_info": camera_info,
        "earth": earth,
        "root": root,
        "earth_radius": float(earth_radius),
        "cam_pos_local": cam_pos_local,
        "cam_forward_local": cam_forward_local,
        "cam_right_local": cam_right_local,
        "cam_up_local": cam_up_local,
    }


def _tile_visibility_stats_with_optional_adaptive(
    tile,
    *,
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
    frustum_margin,
    earth_radius,
):
    parsed = parse_tile(tile)
    if not parsed:
        return None
    x, y, z, _d = parsed
    tan_half_h = math.tan(max(1e-9, float(h_fov)) * 0.5)
    tan_half_v = math.tan(max(1e-9, float(v_fov)) * 0.5)
    ortho_half_w, ortho_half_h = _orthographic_half_extents(ortho_scale, res_x, res_y)
    radius_sq = float(earth_radius) * float(earth_radius)

    points = _tile_sample_points(x, y, z, earth_radius, _tile_sample_uv(z))
    stats = _evaluate_tile_visibility(
        points,
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
        radius_sq=radius_sq,
    )

    used_adaptive = False
    if _should_adaptive_refine_tile(stats, z):
        adaptive_points = _tile_sample_points(x, y, z, earth_radius, _tile_sample_uv_adaptive(z))
        stats = _evaluate_tile_visibility(
            adaptive_points,
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
            radius_sq=radius_sq,
        )
        used_adaptive = True
    stats["used_adaptive"] = bool(used_adaptive)
    return stats


def classify_horizon_edge_near_miss_tiles(tiles, scope_mode="CAMERA"):
    scene = bpy.context.scene
    if scene is None:
        return []
    context = _resolve_camera_local_context(scene, scope_mode=scope_mode)
    camera_info = context["camera_info"]
    cam_pos_local = context["cam_pos_local"]
    cam_forward_local = context["cam_forward_local"]
    cam_right_local = context["cam_right_local"]
    cam_up_local = context["cam_up_local"]
    earth_radius = float(context["earth_radius"])

    camera_type = str(camera_info.get("camera_type", "PERSP"))
    h_fov = float(camera_info.get("h_fov", math.radians(50.0)))
    v_fov = float(camera_info.get("v_fov", math.radians(35.0)))
    res_x = float(camera_info.get("res_x", VIEWPORT_RESOLUTION_X))
    res_y = float(camera_info.get("res_y", VIEWPORT_RESOLUTION_Y))
    ortho_scale = float(camera_info.get("ortho_scale", 1.0))
    frustum_margin = FRUSTUM_MARGIN

    scored_retained = []
    for tile in list(tiles or ()):
        tile_text = str(tile or "").strip()
        if not tile_text or parse_tile(tile_text) is None:
            continue
        stats = _tile_visibility_stats_with_optional_adaptive(
            tile_text,
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
            earth_radius=earth_radius,
        )
        if not stats:
            continue
        if int(stats.get("both_hits", 0) or 0) > 0:
            continue
        if int(stats.get("hemisphere_hits", 0) or 0) <= 0:
            continue
        if not bool(stats.get("has_depth_samples", False)):
            continue
        overflow = stats.get("min_positive_ndc_overflow", None)
        if overflow is None:
            continue
        near_horizon = bool(stats.get("horizon_crossing", False)) or (
            stats.get("min_abs_horizon_norm", None) is not None
            and float(stats.get("min_abs_horizon_norm", 1e9))
            <= float(ANIMATION_HORIZON_HYSTERESIS_HEMISPHERE_NORM_THRESHOLD)
        )
        if not near_horizon:
            continue
        overflow_value = float(overflow)
        if overflow_value <= 0.0:
            continue
        if overflow_value > float(ANIMATION_HORIZON_HYSTERESIS_NDC_THRESHOLD):
            continue
        scored_retained.append(
            (
                overflow_value,
                float(stats.get("min_abs_horizon_norm", 1e9) or 1e9),
                tile_text,
            )
        )

    if not scored_retained:
        return []
    scored_retained.sort(key=lambda item: (float(item[0]), float(item[1]), str(item[2])))
    max_retain = max(0, int(ANIMATION_HORIZON_HYSTERESIS_MAX_RETAINED_TILES))
    chosen = [item[2] for item in scored_retained[:max_retain]] if max_retain > 0 else []
    return _sort_tiles_for_apply(chosen)


def enforce_shader_tile_budget_for_tiles(tiles, max_tiles=MAX_SHADER_TILE_BUDGET, scope_mode="CAMERA"):
    scene = bpy.context.scene
    cam_pos_local = None
    earth_radius = None
    if scene is not None:
        try:
            context = _resolve_camera_local_context(scene, scope_mode=scope_mode)
            cam_pos_local = context.get("cam_pos_local", None)
            earth_radius = context.get("earth_radius", None)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed reading camera context for budget enforcement", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed reading camera context for budget enforcement", exc_info=True)
    return _enforce_shader_tile_budget(
        tiles,
        max_tiles=max_tiles,
        cam_pos_local=cam_pos_local,
        earth_radius=earth_radius,
    )


def main(scope_mode="AUTO", edge_boost=False):
    global LAST_TILE_BUDGET_TRACE, LAST_TILE_BUDGET_INPUT, LAST_TILE_BUDGET_OUTPUT
    scene = bpy.context.scene
    camera_info = get_camera_info(scene, scope_mode=scope_mode)
    cam_pos_world = camera_info["position"]
    h_fov = camera_info["h_fov"]
    v_fov = camera_info["v_fov"]
    camera_type = camera_info["camera_type"]
    is_panorama_equirect = bool(camera_info.get("is_panorama_equirect", False))
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
    try:
        scene[LAST_PANORAMA_MODE_KEY] = bool(is_panorama_equirect)
        scene[LAST_PANORAMA_LIMIT_EXCEEDED_KEY] = False
        scene[LAST_PANORAMA_REQUIRED_TILES_KEY] = 0
        scene[LAST_PANORAMA_REQUIRED_Z_KEY] = 0
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing panorama resolve diagnostics", exc_info=True)
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
    target_z = int(
        _apply_temporal_z_hysteresis(
            scene,
            target_z_mpp,
            max(0.0, float(camera_altitude)),
        )
    )
    logger.debug(
        "z target: %s (mpp=%s)",
        target_z,
        target_z_mpp,
    )
    if int(target_z) != int(target_z_mpp):
        logger.debug(
            "Planetka: temporal z hysteresis held target z at %03d (raw %03d, camera_altitude_bu=%.6f, band=%.4f%%).",
            int(target_z),
            int(target_z_mpp),
            float(max(0.0, float(camera_altitude))),
            float(TEMPORAL_HYSTERESIS_DISTANCE_RATIO) * 100.0,
        )

    cam_pos_local, cam_forward_local, cam_right_local, cam_up_local = _transform_to_planet_space(
        cam_pos_world,
        cam_forward_world,
        cam_right_world,
        cam_up_world,
        earth,
        root,
    )

    max_available_z = int(min(max(Z_LEVELS), int(MAX_RESOLVE_Z_LEVEL)))
    candidate_z_levels = [
        z_level for z_level in Z_LEVELS
        if int(target_z) <= int(z_level) <= max_available_z
    ]
    if not candidate_z_levels:
        candidate_z_levels = [max_available_z]

    selected_tiles = set()
    selected_z = None
    selected_nearest_distance = None
    frustum_margin = ACTIVE_VIEW_FRUSTUM_MARGIN if scope_used == "ACTIVE_VIEW" else FRUSTUM_MARGIN
    visibility_edge_boost = bool(edge_boost or scope_used == "ACTIVE_VIEW")

    if is_panorama_equirect:
        requested_z = int(candidate_z_levels[0]) if candidate_z_levels else int(max_available_z)
        selected_z = int(requested_z)
        tile_count = len(range(0, 360, int(selected_z))) * len(range(0, 180, int(selected_z)))
        if int(tile_count) > int(MAX_SHADER_TILE_BUDGET):
            for z_level in candidate_z_levels[1:]:
                candidate_count = len(range(0, 360, int(z_level))) * len(range(0, 180, int(z_level)))
                if int(candidate_count) <= int(MAX_SHADER_TILE_BUDGET):
                    selected_z = int(z_level)
                    tile_count = int(candidate_count)
                    break
            else:
                # Defensive fallback: choose the coarsest available level.
                selected_z = int(candidate_z_levels[-1]) if candidate_z_levels else int(max_available_z)
                tile_count = len(range(0, 360, int(selected_z))) * len(range(0, 180, int(selected_z)))
        try:
            scene[LAST_PANORAMA_REQUIRED_TILES_KEY] = int(tile_count)
            scene[LAST_PANORAMA_REQUIRED_Z_KEY] = int(selected_z)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed writing panorama required tile diagnostics", exc_info=True)
        try:
            scene[LAST_PANORAMA_LIMIT_EXCEEDED_KEY] = bool(int(tile_count) > int(MAX_SHADER_TILE_BUDGET))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed setting panorama limit exceeded flag", exc_info=True)
        if int(selected_z) != int(requested_z):
            logger.info(
                "Planetka panorama resolve: coarsened z from %03d to %03d to satisfy tile budget (%d <= %d).",
                int(requested_z),
                int(selected_z),
                int(tile_count),
                int(MAX_SHADER_TILE_BUDGET),
            )
        d_value = compute_d_value(required_mpp_near, selected_z, bias_factor=bias_factor)
        for x in range(0, 360, int(selected_z)):
            for y in range(0, 180, int(selected_z)):
                selected_tiles.add(format_tile(x, y, int(selected_z), int(d_value)))
        selected_nearest_distance = float(max(0.0, float(camera_altitude)))
    else:
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

    try:
        previous_selected_z = int(scene.get(LAST_SELECTED_Z_LEVEL_KEY, 0) or 0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        previous_selected_z = 0
    try:
        scene[LAST_SELECTED_Z_LEVEL_KEY] = int(selected_z)
        reference_distance = (
            float(selected_nearest_distance)
            if selected_nearest_distance is not None
            else float(max(0.0, float(camera_altitude)))
        )
        if int(previous_selected_z) != int(selected_z):
            scene[LAST_Z_SWITCH_DISTANCE_KEY] = max(0.0, float(reference_distance))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing temporal z hysteresis diagnostics", exc_info=True)

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
    full_source_tiles = _sort_tiles_for_apply(final_tiles)
    fast_switch_source_tiles, _fast_switch_budget_trace, _fast_switch_budget_success = _enforce_shader_tile_budget(
        full_source_tiles,
        max_tiles=MAX_SHADER_TILE_BUDGET,
        cam_pos_local=cam_pos_local,
        earth_radius=earth_radius,
    )
    fast_switch_source_tiles, _fast_switch_floor_added = _enforce_shader_tile_floor(
        fast_switch_source_tiles,
        min_tiles=MIN_SHADER_TILE_FLOOR,
        max_tiles=MAX_SHADER_TILE_BUDGET,
    )
    _store_last_full_source_tiles(
        scene,
        fast_switch_source_tiles,
    )
    LAST_TILE_BUDGET_INPUT = list(full_source_tiles)
    budgeted_tiles, budget_trace, budget_success = _enforce_shader_tile_budget(
        full_source_tiles,
        max_tiles=MAX_SHADER_TILE_BUDGET,
        cam_pos_local=cam_pos_local,
        earth_radius=earth_radius,
    )
    LAST_TILE_BUDGET_TRACE = list(budget_trace)
    if budget_trace:
        logger.info(
            "Planetka: tile budget optimization applied merges=%d input=%d output=%d budget=%d",
            len(budget_trace),
            len(full_source_tiles),
            len(budgeted_tiles),
            int(MAX_SHADER_TILE_BUDGET),
        )
    if not budget_success:
        logger.warning(
            "Planetka: unable to satisfy tile budget (budget=%d input=%d output=%d). Keeping quality constraints.",
            int(MAX_SHADER_TILE_BUDGET),
            len(full_source_tiles),
            len(budgeted_tiles),
        )
    final_tiles = list(budgeted_tiles)
    final_tiles, floor_added_tiles = _enforce_shader_tile_floor(
        final_tiles,
        min_tiles=MIN_SHADER_TILE_FLOOR,
        max_tiles=MAX_SHADER_TILE_BUDGET,
    )
    if floor_added_tiles:
        logger.info(
            "Planetka: tile floor padding applied added=%d input=%d output=%d floor=%d budget=%d",
            len(floor_added_tiles),
            len(budgeted_tiles),
            len(final_tiles),
            int(MIN_SHADER_TILE_FLOOR),
            int(MAX_SHADER_TILE_BUDGET),
        )
    LAST_TILE_BUDGET_OUTPUT = list(final_tiles)
    write_tile_view_diagnostics(
        scene=scene,
        camera_altitude_bu=float(camera_altitude),
        nearest_visible_distance_bu=None if selected_nearest_distance is None else float(selected_nearest_distance),
        earth_radius_bu=earth_radius,
    )
    return final_tiles


def get_last_tile_budget_trace():
    return {
        "input_tiles": list(LAST_TILE_BUDGET_INPUT),
        "output_tiles": list(LAST_TILE_BUDGET_OUTPUT),
        "merges": list(LAST_TILE_BUDGET_TRACE),
        "min_floor": int(MIN_SHADER_TILE_FLOOR),
        "budget": int(MAX_SHADER_TILE_BUDGET),
    }
