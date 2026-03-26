# fallback_utils.py

import logging
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .r2_source import texture_file_exists

# ------------------------
# Z-level fallback chains
# ------------------------

POWER_CHAIN   = [1, 2, 4, 8, 16, 32, 64]
DECIMAL_CHAIN = [15, 30, 60, 90, 180, 360]

logger = logging.getLogger(__name__)

# ------------------------
# Parsing helpers
# ------------------------

def parse_tile(tile):
    parts = tile.split("_")
    d_code = int(parts[3][1:])
    if d_code == 0:
        d_code = 1440
    return (
        int(parts[0][1:]),
        int(parts[1][1:]),
        int(parts[2][1:]),
        d_code
    )

def format_tile(x, y, z, d):
    d_code = 0 if int(d) == 1440 else int(d)
    return f"x{x:03d}_y{y:03d}_z{z:03d}_d{d_code:03d}"

# ------------------------
# Ecosystem helpers
# ------------------------

def snap_to_parent(x, y, child_z, parent_z):
    # Tile coordinates are absolute grid-aligned degrees; snap directly to parent grid.
    return (x // parent_z) * parent_z, (y // parent_z) * parent_z

# ------------------------
# Disk helpers
# ------------------------

_TEXTURE_EXT = {
    "S2": ".exr",
    "EL": ".exr",
    "WT": ".exr",
    "PO": ".tif",
}


def _asset_file_name(prefix, x, y, z, d):
    d_value = int(d)
    # EL z001_d002 is intentionally remapped to d001 in shader/streaming logic.
    if str(prefix) == "EL" and int(z) == 1 and d_value == 2:
        d_value = 1
    d_code = 0 if d_value == 1440 else d_value
    ext = _TEXTURE_EXT.get(str(prefix), ".exr")
    return f"{prefix}_x{x:03d}_y{y:03d}_z{z:03d}_d{d_code:03d}{ext}"


def tile_assets_exist_on_disk(x, y, z, d, base_path):
    try:
        for prefix in ("S2", "EL", "WT", "PO"):
            file_name = _asset_file_name(prefix, x, y, z, d)
            if not texture_file_exists(base_path, prefix, file_name):
                return False
        return True
    except RuntimeError:
        logger.debug("Planetka: failed checking tile asset existence for fallback", exc_info=True)
        return False


def is_land_tile(x, y, z, coverage):
    if not coverage:
        return False
    try:
        level = coverage.get(z, set())
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    return (x, y) in level


# ------------------------
# Core resolution logic
# ------------------------

def resolve_tile_in_chain(tile, chain, coverage, base_path, warn_on_missing=True):
    x, y, z, d = parse_tile(tile)

    # Ocean tiles are never fallback-promoted to parent tiles.
    if not is_land_tile(x, y, z, coverage):
        logger.debug("Skipping ocean tile (not in coverage): %s", tile)
        return None

    # Start from nearest matching z in chain
    start_index = None
    for i, candidate_z in enumerate(chain):
        if candidate_z >= z:
            start_index = i
            break
    if start_index is None:
        return None

    for parent_z in chain[start_index:]:
        px, py = snap_to_parent(x, y, z, parent_z)
        pd = max(d, parent_z)
        if tile_assets_exist_on_disk(px, py, parent_z, pd, base_path):
            resolved = format_tile(px, py, parent_z, pd)
            if resolved != tile:
                logger.debug("Tile fallback: %s -> %s", tile, resolved)
            return resolved

    if warn_on_missing:
        logger.warning(
            "Land tile unavailable in cache/remote lookup (no fallback parent found): %s",
            tile,
        )
    return None

# ------------------------
# Overlap resolution
# ------------------------

def tiles_overlap(a, b):
    xa, ya, za, _ = parse_tile(a)
    xb, yb, zb, _ = parse_tile(b)

    return not (
        xa + za <= xb or
        xb + zb <= xa or
        ya + za <= yb or
        yb + zb <= ya
    )

def resolve_overlaps(tiles):
    # Prefer higher-quality (lower d), then finer spatial tiles (lower z).
    tiles = sorted(tiles, key=lambda t: (parse_tile(t)[3], parse_tile(t)[2], t))
    final = []

    for tile in tiles:
        if any(tiles_overlap(tile, kept) for kept in final):
            continue
        final.append(tile)

    return final

# ------------------------
# Main entry point
# ------------------------

def ecosystem_safe_fallback(normalized_tiles, ecosystem, coverage, base_path):
    del ecosystem, coverage, base_path
    # Resolve integrity rule: never replace requested tiles with parent candidates.
    # If any requested tile asset is missing, prefetch must fail fast and stop resolve.
    return list(normalized_tiles or [])
