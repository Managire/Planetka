"""Land-credit pricing helpers for the experimental credit branch.

The runtime only reads static metadata from ``Resources/tile_sizes.sqlite``.
The heavy S2 ocean-color scan is implemented in
``tools/build_tile_land_stats.py`` so normal resolves do not decode large image
textures or classify pixels on the fly.
"""

from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Iterable


logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0088
DATASET_BASE_MPP = 10.0
FREE_D_THRESHOLD = 60
PAID_LAT_MIN_DEG = -60.0
PAID_LAT_MAX_DEG = 75.0
EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2

TILE_RE = re.compile(r"x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})", re.IGNORECASE)
TILE_FILE_RE = re.compile(
    r"^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$",
    re.IGNORECASE,
)

_DB_LOCK = threading.Lock()
_DB_CONN = None
_DB_PATH = ""
_LAND_STATS_READY = None


@dataclass(frozen=True)
class TileCode:
    x: int
    y: int
    z: int
    d: int

    @property
    def key(self) -> str:
        return f"x{self.x:03d}_y{self.y:03d}_z{self.z:03d}_d{self.d:03d}"


def tile_family_key(tile: TileCode | str | None) -> str:
    parsed = parse_tile_key(tile) if not isinstance(tile, TileCode) else tile
    if parsed is None:
        return ""
    return f"x{parsed.x:03d}_y{parsed.y:03d}_z{parsed.z:03d}"


def detail_ratio(tile: TileCode | str | None) -> float:
    parsed = parse_tile_key(tile) if not isinstance(tile, TileCode) else tile
    if parsed is None:
        return float("inf")
    try:
        z = max(1.0, float(parsed.z))
        d = float(parsed.d)
    except (TypeError, ValueError):
        return float("inf")
    if d <= 0:
        return float("inf")
    return float(d / z)


def detail_price_factor(tile: TileCode | str | None) -> float:
    parsed = parse_tile_key(tile) if not isinstance(tile, TileCode) else tile
    if parsed is None:
        return 0.0
    if int(parsed.d) >= FREE_D_THRESHOLD:
        return 0.0
    ratio = detail_ratio(parsed)
    if not math.isfinite(ratio) or ratio <= 0.0:
        return 0.0
    mpp = delivered_mpp_for_d(parsed.d)
    return float((DATASET_BASE_MPP / max(DATASET_BASE_MPP, mpp)) ** 2)


def normalize_quality_mode(value: str) -> str:
    token = str(value or "").strip().upper()
    if token in {"HALF", "BALANCED"}:
        return "FULL"
    if token in {"FULL", "PREVIEW"}:
        return token
    return "PREVIEW"


def normalize_tile_key(value: str) -> str:
    text = str(value or "").strip()
    match = TILE_FILE_RE.match(os.path.basename(text))
    if match:
        text = match.group(1)
    match = TILE_RE.search(text)
    if not match:
        return ""
    x, y, z, d = (int(part) for part in match.groups())
    return f"x{x:03d}_y{y:03d}_z{z:03d}_d{d:03d}"


def parse_tile_key(value: str) -> TileCode | None:
    key = normalize_tile_key(value)
    match = TILE_RE.fullmatch(key)
    if not match:
        return None
    x, y, z, d = (int(part) for part in match.groups())
    return TileCode(x=x, y=y, z=z, d=d)


def delivered_mpp_for_d(d_value: int) -> float:
    try:
        d = int(d_value)
    except (TypeError, ValueError):
        d = FREE_D_THRESHOLD
    if d <= 0:
        d = 1440
    return float(DATASET_BASE_MPP * max(1, d))


def tile_lat_bounds(tile: TileCode) -> tuple[float, float]:
    south = float(tile.y) - 90.0
    north = float(tile.y + tile.z) - 90.0
    return max(-90.0, south), min(90.0, north)


def tile_lon_bounds(tile: TileCode) -> tuple[float, float]:
    west = float(tile.x) - 180.0
    east = float(tile.x + tile.z) - 180.0
    return max(-180.0, west), min(180.0, east)


def spherical_area_km2(lon_west: float, lon_east: float, lat_south: float, lat_north: float) -> float:
    if lon_east <= lon_west or lat_north <= lat_south:
        return 0.0
    lon_delta = math.radians(float(lon_east) - float(lon_west))
    south_rad = math.radians(float(lat_south))
    north_rad = math.radians(float(lat_north))
    area = (EARTH_RADIUS_KM ** 2) * lon_delta * abs(math.sin(north_rad) - math.sin(south_rad))
    return float(max(0.0, area))


def tile_area_km2(tile: TileCode) -> float:
    west, east = tile_lon_bounds(tile)
    south, north = tile_lat_bounds(tile)
    return spherical_area_km2(west, east, south, north)


def paid_band_area_km2(tile: TileCode) -> float:
    west, east = tile_lon_bounds(tile)
    south, north = tile_lat_bounds(tile)
    billable_south = max(float(south), PAID_LAT_MIN_DEG)
    billable_north = min(float(north), PAID_LAT_MAX_DEG)
    return spherical_area_km2(west, east, billable_south, billable_north)


def _effective_billable_land_km2(tile: TileCode, stats: dict, free_reason: str = "") -> float:
    if str(free_reason or "").strip():
        return 0.0
    try:
        billable = float(stats.get("billable_land_km2", 0.0) or 0.0)
    except (AttributeError, TypeError, ValueError):
        billable = 0.0
    if billable > 0.0:
        return max(0.0, billable)
    try:
        land = float(stats.get("land_km2", 0.0) or 0.0)
    except (AttributeError, TypeError, ValueError):
        land = 0.0
    if land <= 0.0:
        return 0.0
    total_area = tile_area_km2(tile)
    paid_area = paid_band_area_km2(tile)
    if total_area <= 0.0 or paid_area <= 0.0:
        return 0.0
    return max(0.0, land * min(1.0, paid_area / total_area))


def free_reason_for_tile(tile: TileCode) -> str:
    if int(tile.d) <= 0:
        return "d000_global_free"
    if int(tile.d) >= FREE_D_THRESHOLD:
        return "coarse_detail_free"
    south, north = tile_lat_bounds(tile)
    if north <= PAID_LAT_MIN_DEG:
        return "south_polar_free"
    if south >= PAID_LAT_MAX_DEG:
        return "north_polar_free"
    return ""


def _default_stats_db_path() -> str:
    try:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "Resources", "tile_sizes.sqlite")
    except (RuntimeError, TypeError, ValueError, OSError):
        return ""


def land_stats_db_path() -> str:
    configured = str(os.getenv("PLANETKA_LAND_STATS_DB_PATH") or "").strip()
    if configured:
        return configured
    return _default_stats_db_path()


def _connect_stats_db(path: str):
    uri = f"file:{os.path.abspath(path)}?mode=ro"
    # Credit estimates must never make Blender feel stuck. If the stats DB is
    # temporarily busy, fall back to geometric estimates instead of waiting.
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=0.05)
    conn.execute("SELECT 1 FROM tile_land_stats LIMIT 1")
    return conn


def _get_stats_conn():
    global _DB_CONN, _DB_PATH, _LAND_STATS_READY
    path = land_stats_db_path()
    if not path or not os.path.isfile(path):
        return None
    normalized = os.path.abspath(path)
    with _DB_LOCK:
        if _LAND_STATS_READY is False and _DB_PATH == normalized:
            return None
        if _DB_CONN is not None and _DB_PATH == normalized:
            return _DB_CONN
        if _DB_CONN is not None:
            try:
                _DB_CONN.close()
            except sqlite3.Error:
                logger.debug("Planetka: failed closing land-stats sqlite connection", exc_info=True)
        _DB_CONN = None
        _DB_PATH = normalized
        try:
            _DB_CONN = _connect_stats_db(normalized)
            _LAND_STATS_READY = True
            return _DB_CONN
        except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError):
            _LAND_STATS_READY = False
            logger.debug("Planetka: tile_land_stats table is unavailable", exc_info=True)
            return None


def lookup_tile_land_stats(tile_key: str) -> dict:
    tile = parse_tile_key(tile_key)
    if tile is None:
        return {}
    conn = _get_stats_conn()
    if conn is None:
        return {}
    try:
        with _DB_LOCK:
            row = conn.execute(
                """
                SELECT land_km2, billable_land_km2, base_credits, free_reason
                FROM tile_land_stats
                WHERE tile_key = ?
                LIMIT 1
                """,
                (tile.key,),
            ).fetchone()
    except (sqlite3.Error, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: land-stats lookup failed for %s", tile.key, exc_info=True)
        return {}
    if not row:
        return {}
    try:
        return {
            "tile_key": tile.key,
            "land_km2": max(0.0, float(row[0] or 0.0)),
            "billable_land_km2": max(0.0, float(row[1] or 0.0)),
            "base_credits": max(0.0, float(row[2] or 0.0)),
            "free_reason": str(row[3] or "").strip(),
            "source": "sqlite",
        }
    except (TypeError, ValueError):
        return {}


def estimate_tile_land_stats(tile_key: str) -> dict:
    """Fallback estimate when S2-derived land metadata is unavailable.

    This intentionally assumes all land inside the paid latitude band. It is a
    conservative testing fallback; production should populate tile_land_stats
    by excluding S2 pixels that match the ocean fallback color.
    """
    tile = parse_tile_key(tile_key)
    if tile is None:
        return {}
    reason = free_reason_for_tile(tile)
    total_area = tile_area_km2(tile)
    billable_area = 0.0 if reason else paid_band_area_km2(tile)
    base_credits = billable_area / EQUATOR_Z001_AREA_KM2
    return {
        "tile_key": tile.key,
        "land_km2": total_area,
        "billable_land_km2": billable_area,
        "base_credits": max(0.0, float(base_credits)),
        "free_reason": reason,
        "source": "geometric_estimate",
    }


def get_tile_land_stats(tile_key: str, allow_estimate: bool = True) -> dict:
    stats = lookup_tile_land_stats(tile_key)
    if stats:
        return stats
    if allow_estimate:
        return estimate_tile_land_stats(tile_key)
    return {}


def credits_for_tile(tile_key: str, quality_mode: str = "FULL", allow_estimate: bool = True) -> dict:
    mode = normalize_quality_mode(quality_mode)
    key = normalize_tile_key(tile_key)
    if not key:
        return {}
    stats = get_tile_land_stats(key, allow_estimate=allow_estimate)
    if not stats:
        return {}
    tile = parse_tile_key(key)
    if tile is None:
        return {}
    free_reason = free_reason_for_tile(tile)
    if mode == "PREVIEW":
        free_reason = free_reason or "preview_quality"
    mpp = delivered_mpp_for_d(tile.d)
    billable_land_km2 = _effective_billable_land_km2(tile, stats, free_reason=free_reason)
    base_credits = max(0.0, billable_land_km2 / EQUATOR_Z001_AREA_KM2)
    price_factor = detail_price_factor(tile)
    credits = 0.0 if free_reason else (base_credits * price_factor)
    return {
        "tile_key": key,
        "quality_mode": mode.lower(),
        "credits": round(max(0.0, float(credits)), 6),
        "land_km2": round(max(0.0, float(stats.get("land_km2", 0.0) or 0.0)), 6),
        "billable_land_km2": round(max(0.0, float(billable_land_km2)), 6),
        "delivered_mpp": round(float(mpp), 6),
        "detail_ratio": round(float(detail_ratio(tile)), 6),
        "price_factor": round(float(price_factor), 6),
        "free_reason": free_reason,
        "stats_source": str(stats.get("source", "") or ""),
    }


def pricing_records_for_tiles(
    tiles: Iterable[str],
    quality_mode: str = "FULL",
    owned_tile_keys: Iterable[str] | None = None,
    allow_estimate: bool = True,
) -> list[dict]:
    owned = {normalize_tile_key(tile) for tile in (owned_tile_keys or ())}
    owned_by_family: dict[str, list[tuple[int, float]]] = {}
    for owned_key in owned:
        owned_tile = parse_tile_key(owned_key)
        if owned_tile is None:
            continue
        owned_record = credits_for_tile(owned_key, quality_mode="FULL", allow_estimate=allow_estimate)
        owned_by_family.setdefault(tile_family_key(owned_tile), []).append(
            (int(owned_tile.d), max(0.0, float(owned_record.get("credits", 0.0) or 0.0)))
        )

    pending = []
    seen = set()
    for tile in tiles or ():
        key = normalize_tile_key(tile)
        if not key or key in seen:
            continue
        seen.add(key)
        record = credits_for_tile(key, quality_mode=quality_mode, allow_estimate=allow_estimate)
        if not record:
            continue
        parsed = parse_tile_key(key)
        if parsed is None:
            continue
        pending.append((tile_family_key(parsed), int(parsed.d), record))

    out = []
    for family, d_value, record in sorted(pending, key=lambda item: (item[0], item[1])):
        gross = max(0.0, float(record.get("credits", 0.0) or 0.0))
        family_entitlements = owned_by_family.setdefault(family, [])
        covered_by_finer = any(int(owned_d) <= int(d_value) for owned_d, _value in family_entitlements)
        if gross <= 0.0:
            out.append(record)
            continue
        if covered_by_finer:
            record = dict(record)
            record["credits"] = 0.0
            record["free_reason"] = str(record.get("free_reason") or "already_unlocked")
            out.append(record)
            continue
        coarser_value = max(
            (float(value) for owned_d, value in family_entitlements if int(owned_d) > int(d_value)),
            default=0.0,
        )
        due = max(0.0, gross - coarser_value)
        record = dict(record)
        record["credits"] = round(float(due), 6)
        if due <= 0.0:
            record["free_reason"] = str(record.get("free_reason") or "already_unlocked")
        elif coarser_value > 0.0:
            record["upgrade_credit_applied"] = round(float(coarser_value), 6)
        family_entitlements.append((int(d_value), gross))
        out.append(record)
    return out


def summarize_pricing_records(records: Iterable[dict]) -> dict:
    total = 0.0
    paid = 0
    free = 0
    for record in records or ():
        try:
            credits = max(0.0, float(record.get("credits", 0.0) or 0.0))
        except (TypeError, ValueError, AttributeError):
            credits = 0.0
        total += credits
        if credits > 0:
            paid += 1
        else:
            free += 1
    return {
        "credits": round(max(0.0, float(total)), 6),
        "paid_tile_count": int(paid),
        "free_tile_count": int(free),
        "tile_count": int(paid + free),
    }
