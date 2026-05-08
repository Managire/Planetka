#!/usr/bin/env python3
"""Build internal commercial-value tiers for future Full Quality analysis.

This is an offline build step. It reads GeoNames populated places, assigns a
commercial-value tier to every Planetka S2 tile footprint, smooths the tiers so
neighbouring tiles cannot jump by more than one tier, writes the result into
Resources/tile_sizes.sqlite, and generates a before/after comparison report.
The active public pricing model intentionally ignores this table and prices
tiles from billable land area only.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


DEFAULT_TILE_DB = Path("Resources/tile_sizes.sqlite")
DEFAULT_GEONAMES = Path("/Volumes/SSDA/Planetka Assets Extra/allCountries.txt")
DEFAULT_REGION_PACK_JSON = Path("Resources/Region Packs/region_packs_gadm.json")
DEFAULT_REPORT_PREFIX = Path("Documentation/Developer/tile_commercial_value_comparison")

DATASET_BASE_MPP = Decimal("10.0")
EQUATOR_Z001_AREA_KM2 = (Decimal("40075.016686") / Decimal("360.0")) ** 2
MONEY_CENTS = Decimal("100")
FREE_D_THRESHOLD = 60
TILE_KEY_RE = re.compile(r"x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})", re.IGNORECASE)

VALUE_MULTIPLIERS: dict[int, Decimal] = {
    1: Decimal("0.25"),
    2: Decimal("0.50"),
    3: Decimal("1.00"),
    4: Decimal("1.50"),
    5: Decimal("2.00"),
}

# Historical/abandoned/destroyed populated-place records should not raise
# commercial value. Normal tiny P/PPL records still raise a footprint to tier 2.
EXCLUDED_POPULATED_PLACE_CODES = {
    "PPLH",  # historical populated place
    "PPLQ",  # abandoned populated place
    "PPLW",  # destroyed populated place
}


@dataclass
class TileRow:
    tile_key: str
    x: int
    y: int
    z: int
    d: int
    billable_land_km2: float
    free_reason: str


@dataclass
class CellValue:
    initial_tier: int = 1
    value_tier: int = 1
    max_population: int = 0
    max_population_name: str = ""
    max_population_country: str = ""
    max_population_feature_code: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_tile_key(value: str) -> tuple[int, int, int, int] | None:
    match = TILE_KEY_RE.search(str(value or ""))
    if not match:
        return None
    return tuple(int(match.group(index)) for index in range(1, 5))


def tile_key(x_value: int, y_value: int, z_value: int, d_value: int) -> str:
    return f"x{x_value:03d}_y{y_value:03d}_z{z_value:03d}_d{d_value:03d}"


def free_reason_for_tile_key(value: str) -> str:
    parsed = parse_tile_key(value)
    if not parsed:
        return "invalid_tile_key"
    _x_value, _y_value, _z_value, d_value = parsed
    if d_value <= 0:
        return "d000_global_free"
    if d_value >= FREE_D_THRESHOLD:
        return "coarse_detail_free"
    return ""


def delivered_mpp_for_d(d_value: int) -> Decimal:
    if d_value <= 0:
        return Decimal("1440")
    return DATASET_BASE_MPP * Decimal(max(1, int(d_value)))


def base_eur_for_land(tile_key_value: str, billable_land_km2: float, free_reason: str = "") -> Decimal:
    if free_reason_for_tile_key(tile_key_value) or str(free_reason or "").strip():
        return Decimal("0")
    parsed = parse_tile_key(tile_key_value)
    if not parsed:
        return Decimal("0")
    _x_value, _y_value, _z_value, d_value = parsed
    billable = Decimal(str(max(0.0, float(billable_land_km2 or 0.0))))
    if billable <= 0:
        return Decimal("0")
    mpp = delivered_mpp_for_d(d_value)
    quality_factor = (DATASET_BASE_MPP / max(DATASET_BASE_MPP, mpp)) ** 2
    return (billable / EQUATOR_Z001_AREA_KM2) * quality_factor


def cents_from_eur(value: Decimal) -> int:
    return int((max(Decimal("0"), value) * MONEY_CENTS).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def eur_from_cents(cents: int) -> str:
    return str((Decimal(max(0, int(cents))) / MONEY_CENTS).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def discounted_cents(gross_cents: int, discount_percent: int) -> int:
    gross = max(0, int(gross_cents or 0))
    percent = max(0, min(95, int(discount_percent or 0)))
    # Match backend EUR rounding: the discount is rounded to cents first,
    # then subtracted from the gross amount.
    discount = (gross * percent + 50) // 100
    return max(0, gross - discount)


def population_tier(population: int) -> int:
    if population >= 1_000_000:
        return 5
    if population >= 100_000:
        return 4
    if population >= 15_000:
        return 3
    if population >= 1_000:
        return 2
    return 1


def tile_xy_for_point(latitude: float, longitude: float, z_value: int) -> tuple[int, int]:
    lon = ((float(longitude) + 180.0) % 360.0) - 180.0
    lat = max(-89.999999, min(89.999999, float(latitude)))
    x_value = math.floor((lon + 180.0) / z_value) * z_value
    y_value = math.floor((lat + 90.0) / z_value) * z_value
    x_value = max(0, min(360 - z_value, int(x_value)))
    y_value = max(0, min(180 - z_value, int(y_value)))
    return x_value, y_value


def load_tile_rows(tile_db_path: Path) -> tuple[list[TileRow], dict[int, dict[tuple[int, int], CellValue]]]:
    conn = sqlite3.connect(str(tile_db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "tile_land_stats" not in tables:
            raise RuntimeError(f"{tile_db_path} does not contain tile_land_stats")
        rows = conn.execute(
            """
              SELECT tile_key, x, y, z, d, billable_land_km2, free_reason
              FROM tile_land_stats
              WHERE tile_key IS NOT NULL
              ORDER BY z, d, x, y
            """
        ).fetchall()
    finally:
        conn.close()

    tile_rows: list[TileRow] = []
    cells_by_z: dict[int, dict[tuple[int, int], CellValue]] = {}
    for row in rows:
        key = str(row["tile_key"] or "").strip()
        if not key:
            continue
        item = TileRow(
            tile_key=key,
            x=int(row["x"]),
            y=int(row["y"]),
            z=int(row["z"]),
            d=int(row["d"]),
            billable_land_km2=float(row["billable_land_km2"] or 0.0),
            free_reason=str(row["free_reason"] or "").strip(),
        )
        tile_rows.append(item)
        cells_by_z.setdefault(item.z, {}).setdefault((item.x, item.y), CellValue())
    return tile_rows, cells_by_z


def assign_geonames_values(
    cells_by_z: dict[int, dict[tuple[int, int], CellValue]],
    geonames_path: Path,
    progress_lines: int = 1_000_000,
    max_lines: int | None = None,
) -> dict:
    z_values = sorted(cells_by_z.keys())
    file_size = geonames_path.stat().st_size
    start = time.monotonic()
    stats = {
        "source_file": str(geonames_path),
        "source_file_bytes": file_size,
        "lines_read": 0,
        "populated_place_rows": 0,
        "excluded_populated_place_rows": 0,
        "invalid_populated_place_rows": 0,
        "assigned_place_rows": 0,
        "tier1_place_rows": 0,
        "tier2_place_rows": 0,
        "tier3_place_rows": 0,
        "tier4_place_rows": 0,
        "tier5_place_rows": 0,
    }

    def maybe_progress(handle) -> None:
        if not progress_lines or stats["lines_read"] % progress_lines:
            return
        elapsed = max(0.001, time.monotonic() - start)
        position = handle.tell()
        pct = min(100.0, (position / max(1, file_size)) * 100.0)
        eta = (elapsed / max(0.001, pct)) * (100.0 - pct) if pct > 0 else 0.0
        print(
            f"GeoNames pass: {stats['lines_read']:,} lines, "
            f"{stats['populated_place_rows']:,} populated places, "
            f"{pct:5.1f}% complete, ETA {eta / 60.0:,.1f} min",
            flush=True,
        )

    with geonames_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        while True:
            line = handle.readline()
            if not line:
                break
            stats["lines_read"] += 1
            if max_lines and stats["lines_read"] > max_lines:
                break
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= 14 or parts[6] != "P":
                maybe_progress(handle)
                continue
            feature_code = parts[7].strip().upper()
            if feature_code in EXCLUDED_POPULATED_PLACE_CODES:
                stats["excluded_populated_place_rows"] += 1
                maybe_progress(handle)
                continue
            stats["populated_place_rows"] += 1
            try:
                latitude = float(parts[4])
                longitude = float(parts[5])
                population = int(parts[14] or "0")
            except (TypeError, ValueError):
                stats["invalid_populated_place_rows"] += 1
                maybe_progress(handle)
                continue
            tier = population_tier(population)
            stats[f"tier{tier}_place_rows"] += 1
            assigned = False
            name = (parts[1] or parts[2] or "").strip()
            country = (parts[8] or "").strip().upper()
            for z_value in z_values:
                x_value, y_value = tile_xy_for_point(latitude, longitude, z_value)
                cell = cells_by_z[z_value].get((x_value, y_value))
                if cell is None:
                    continue
                assigned = True
                if tier > cell.initial_tier:
                    cell.initial_tier = tier
                    cell.value_tier = max(cell.value_tier, tier)
                if population > cell.max_population:
                    cell.max_population = population
                    cell.max_population_name = name
                    cell.max_population_country = country
                    cell.max_population_feature_code = feature_code
            if assigned:
                stats["assigned_place_rows"] += 1
            maybe_progress(handle)
    stats["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return stats


def smooth_values(cells_by_z: dict[int, dict[tuple[int, int], CellValue]]) -> dict:
    stats = {
        "updated_cells_by_tier": {str(tier): 0 for tier in range(1, 6)},
        "z_levels": sorted(cells_by_z.keys()),
    }
    for z_value, cells in cells_by_z.items():
        for tier in range(5, 1, -1):
            origins = [
                (x_value, y_value)
                for (x_value, y_value), cell in cells.items()
                if cell.value_tier >= tier
            ]
            target_tier = tier - 1
            for x_value, y_value in origins:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx = (x_value + (dx * z_value)) % 360
                    ny = y_value + (dy * z_value)
                    if ny < 0 or ny > 180 - z_value:
                        continue
                    neighbour = cells.get((nx, ny))
                    if neighbour is None or neighbour.value_tier >= target_tier:
                        continue
                    neighbour.value_tier = target_tier
                    stats["updated_cells_by_tier"][str(target_tier)] += 1
    return stats


def build_commercial_rows(tile_rows: list[TileRow], cells_by_z: dict[int, dict[tuple[int, int], CellValue]]) -> list[tuple]:
    generated_at = now_iso()
    records = []
    for row in tile_rows:
        cell = cells_by_z.get(row.z, {}).get((row.x, row.y), CellValue())
        tier = max(1, min(5, int(cell.value_tier or 1)))
        multiplier = VALUE_MULTIPLIERS[tier]
        base_eur = base_eur_for_land(row.tile_key, row.billable_land_km2, row.free_reason)
        base_cents = cents_from_eur(base_eur)
        commercial_cents = cents_from_eur(base_eur * multiplier)
        records.append(
            (
                row.tile_key,
                row.x,
                row.y,
                row.z,
                row.d,
                max(1, min(5, int(cell.initial_tier or 1))),
                tier,
                float(multiplier),
                int(cell.max_population or 0),
                cell.max_population_name,
                cell.max_population_country,
                cell.max_population_feature_code,
                base_cents,
                commercial_cents,
                generated_at,
            )
        )
    return records


def write_commercial_table(tile_db_path: Path, records: list[tuple], meta: dict) -> None:
    conn = sqlite3.connect(str(tile_db_path))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tile_commercial_value (
              tile_key TEXT PRIMARY KEY,
              x INTEGER NOT NULL,
              y INTEGER NOT NULL,
              z INTEGER NOT NULL,
              d INTEGER NOT NULL,
              initial_value_tier INTEGER NOT NULL,
              value_tier INTEGER NOT NULL,
              value_multiplier REAL NOT NULL,
              max_population INTEGER NOT NULL DEFAULT 0,
              max_population_name TEXT NOT NULL DEFAULT '',
              max_population_country TEXT NOT NULL DEFAULT '',
              max_population_feature_code TEXT NOT NULL DEFAULT '',
              base_gross_cents INTEGER NOT NULL DEFAULT 0,
              commercial_gross_cents INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tile_commercial_value_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        conn.execute("DELETE FROM tile_commercial_value")
        conn.executemany(
            """
            INSERT INTO tile_commercial_value (
              tile_key, x, y, z, d, initial_value_tier, value_tier,
              value_multiplier, max_population, max_population_name,
              max_population_country, max_population_feature_code,
              base_gross_cents, commercial_gross_cents, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.execute("DELETE FROM tile_commercial_value_meta")
        for key, value in sorted(meta.items()):
            conn.execute(
                "INSERT INTO tile_commercial_value_meta (key, value) VALUES (?, ?)",
                (str(key), json.dumps(value, ensure_ascii=True, sort_keys=True)),
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tile_commercial_value_zd ON tile_commercial_value(z, d)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tile_commercial_value_tier ON tile_commercial_value(value_tier)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tile_commercial_value_commercial_cents "
            "ON tile_commercial_value(commercial_gross_cents)"
        )
        conn.commit()
    finally:
        conn.close()


def summarize_tiers(records: list[tuple]) -> dict:
    summary = {
        str(tier): {"tile_rows": 0, "charged_tile_rows": 0, "base_cents": 0, "commercial_cents": 0}
        for tier in range(1, 6)
    }
    for record in records:
        tier = str(record[6])
        summary[tier]["tile_rows"] += 1
        base_cents = int(record[12])
        commercial_cents = int(record[13])
        summary[tier]["base_cents"] += base_cents
        summary[tier]["commercial_cents"] += commercial_cents
        if commercial_cents > 0:
            summary[tier]["charged_tile_rows"] += 1
    return summary


def load_commercial_cents(tile_db_path: Path) -> dict[str, dict]:
    conn = sqlite3.connect(str(tile_db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
              SELECT tile_key, value_tier, value_multiplier, base_gross_cents,
                     commercial_gross_cents, max_population, max_population_name
              FROM tile_commercial_value
              ORDER BY tile_key
            """
        ).fetchall()
    finally:
        conn.close()
    return {
        str(row["tile_key"]): {
            "value_tier": int(row["value_tier"]),
            "value_multiplier": float(row["value_multiplier"]),
            "base_gross_cents": int(row["base_gross_cents"]),
            "commercial_gross_cents": int(row["commercial_gross_cents"]),
            "max_population": int(row["max_population"]),
            "max_population_name": str(row["max_population_name"] or ""),
        }
        for row in rows
    }


def product_type_rank(product_type: str) -> int:
    ranks = {"world": 0, "continent": 1, "macro_region": 2, "country": 3}
    return ranks.get(str(product_type or ""), 9)


def generate_comparison_report(
    region_pack_json: Path,
    tile_db_path: Path,
    report_prefix: Path,
    build_meta: dict,
) -> dict:
    catalog = json.loads(region_pack_json.read_text(encoding="utf-8"))
    products = list(catalog.get("products") or [])
    pricing = load_commercial_cents(tile_db_path)
    rows = []
    missing_tile_keys: set[str] = set()
    for product in products:
        tile_keys = [str(key).strip() for key in product.get("tile_keys") or [] if str(key).strip()]
        discount = int(product.get("discount_percent") or 0)
        current_gross = int(product.get("gross_cents") or 0)
        current_final = discounted_cents(current_gross, discount)
        new_gross = 0
        tier_counts = {tier: 0 for tier in range(1, 6)}
        charged_tier_counts = {tier: 0 for tier in range(1, 6)}
        for key in tile_keys:
            record = pricing.get(key)
            if record is None:
                missing_tile_keys.add(key)
                continue
            tier = int(record["value_tier"])
            tier_counts[tier] += 1
            cents = int(record["commercial_gross_cents"])
            new_gross += cents
            if cents > 0:
                charged_tier_counts[tier] += 1
        new_final = discounted_cents(new_gross, discount)
        delta = new_final - current_final
        delta_pct = (float(delta) / float(current_final) * 100.0) if current_final else 0.0
        rows.append(
            {
                "id": product.get("id", ""),
                "name": product.get("name", ""),
                "type": product.get("type", ""),
                "discount_percent": discount,
                "tile_count": len(tile_keys),
                "current_gross_cents": current_gross,
                "current_final_cents": current_final,
                "new_gross_cents": new_gross,
                "new_final_cents": new_final,
                "delta_cents": delta,
                "delta_percent": round(delta_pct, 2),
                **{f"tier_{tier}_tiles": tier_counts[tier] for tier in range(1, 6)},
                **{f"tier_{tier}_charged_tiles": charged_tier_counts[tier] for tier in range(1, 6)},
            }
        )

    report_prefix.parent.mkdir(parents=True, exist_ok=True)
    csv_path = report_prefix.with_suffix(".csv")
    md_path = report_prefix.with_suffix(".md")
    fieldnames = [
        "id",
        "name",
        "type",
        "discount_percent",
        "tile_count",
        "current_gross_cents",
        "current_final_cents",
        "new_gross_cents",
        "new_final_cents",
        "delta_cents",
        "delta_percent",
        *[f"tier_{tier}_tiles" for tier in range(1, 6)],
        *[f"tier_{tier}_charged_tiles" for tier in range(1, 6)],
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (product_type_rank(item["type"]), str(item["name"]))):
            writer.writerow(row)

    def table_line(row: dict) -> str:
        return (
            f"| {row['name']} | {row['type']} | {eur_from_cents(row['current_final_cents'])} | "
            f"{eur_from_cents(row['new_final_cents'])} | {eur_from_cents(row['delta_cents']) if row['delta_cents'] >= 0 else '-' + eur_from_cents(abs(row['delta_cents']))} | "
            f"{row['delta_percent']:.2f}% | {row['tier_1_charged_tiles']}/{row['tier_2_charged_tiles']}/"
            f"{row['tier_3_charged_tiles']}/{row['tier_4_charged_tiles']}/{row['tier_5_charged_tiles']} |"
        )

    continents = [
        row for row in rows
        if str(row["type"]) in {"world", "continent"} or str(row["id"]) in {"europe", "asia", "africa", "north_america", "south_america", "australia"}
    ]
    top_increases = sorted(rows, key=lambda item: item["delta_cents"], reverse=True)[:20]
    top_decreases = sorted(rows, key=lambda item: item["delta_cents"])[:20]

    lines = [
        "# Tile Commercial Value Pricing Comparison",
        "",
        f"Generated: {build_meta.get('generated_at')}",
        f"GeoNames source: `{build_meta.get('geonames_source')}`",
        f"Region-pack source: `{region_pack_json}`",
        "",
        "Multipliers: Tier 1 = 0.25x, Tier 2 = 0.50x, Tier 3 = 1.00x, Tier 4 = 1.50x, Tier 5 = 2.00x.",
        "",
        "## Build Summary",
        "",
        f"- Tile rows written: {build_meta.get('tile_rows'):,}",
        f"- Tile footprints valued: {build_meta.get('tile_footprints'):,}",
        f"- GeoNames populated places read: {build_meta.get('geonames_stats', {}).get('populated_place_rows', 0):,}",
        f"- GeoNames populated places assigned to Planetka tile footprints: {build_meta.get('geonames_stats', {}).get('assigned_place_rows', 0):,}",
        f"- Missing pricing rows in report: {len(missing_tile_keys):,}",
        "",
        "## Continent / World Summary",
        "",
        "| Product | Type | Current final EUR | New final EUR | Delta EUR | Delta % | Charged tiers 1/2/3/4/5 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(table_line(row) for row in sorted(continents, key=lambda item: product_type_rank(item["type"])))
    lines.extend([
        "",
        "## Largest Increases",
        "",
        "| Product | Type | Current final EUR | New final EUR | Delta EUR | Delta % | Charged tiers 1/2/3/4/5 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    lines.extend(table_line(row) for row in top_increases)
    lines.extend([
        "",
        "## Largest Decreases",
        "",
        "| Product | Type | Current final EUR | New final EUR | Delta EUR | Delta % | Charged tiers 1/2/3/4/5 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    lines.extend(table_line(row) for row in top_decreases)
    lines.extend([
        "",
        "## Files",
        "",
        f"- CSV: `{csv_path}`",
        f"- SQLite table: `{tile_db_path}` table `tile_commercial_value`",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "csv": str(csv_path),
        "markdown": str(md_path),
        "product_count": len(products),
        "missing_tile_key_count": len(missing_tile_keys),
        "top_increases": top_increases[:5],
        "top_decreases": top_decreases[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tile-db", type=Path, default=DEFAULT_TILE_DB)
    parser.add_argument("--geonames", type=Path, default=DEFAULT_GEONAMES)
    parser.add_argument("--region-pack-json", type=Path, default=DEFAULT_REGION_PACK_JSON)
    parser.add_argument("--report-prefix", type=Path, default=DEFAULT_REPORT_PREFIX)
    parser.add_argument("--progress-lines", type=int, default=1_000_000)
    parser.add_argument("--max-lines", type=int, default=0, help="Debug only: stop after N GeoNames lines")
    args = parser.parse_args()

    if not args.tile_db.exists():
        raise FileNotFoundError(args.tile_db)
    if not args.geonames.exists():
        raise FileNotFoundError(args.geonames)
    if not args.region_pack_json.exists():
        raise FileNotFoundError(args.region_pack_json)

    started = time.monotonic()
    print(f"Loading tile metadata from {args.tile_db} ...", flush=True)
    tile_rows, cells_by_z = load_tile_rows(args.tile_db)
    print(
        f"Loaded {len(tile_rows):,} tile rows and "
        f"{sum(len(cells) for cells in cells_by_z.values()):,} tile footprints.",
        flush=True,
    )
    print(f"Parsing GeoNames populated places from {args.geonames} ...", flush=True)
    geonames_stats = assign_geonames_values(
        cells_by_z,
        args.geonames,
        progress_lines=max(0, int(args.progress_lines or 0)),
        max_lines=(int(args.max_lines) if int(args.max_lines or 0) > 0 else None),
    )
    print("Applying neighbour smoothing ...", flush=True)
    smoothing_stats = smooth_values(cells_by_z)
    print("Computing commercial gross cents ...", flush=True)
    records = build_commercial_rows(tile_rows, cells_by_z)
    tier_summary = summarize_tiers(records)
    build_meta = {
        "generated_at": now_iso(),
        "geonames_source": str(args.geonames),
        "tile_rows": len(tile_rows),
        "tile_footprints": sum(len(cells) for cells in cells_by_z.values()),
        "multipliers": {str(key): str(value) for key, value in VALUE_MULTIPLIERS.items()},
        "population_tier_thresholds": {
            "1": "populated place below 1,000 inhabitants or no populated place",
            "2": "populated place from 1,000 to 14,999 inhabitants",
            "3": "populated place from 15,000 to 99,999 inhabitants",
            "4": "populated place from 100,000 to 999,999 inhabitants",
            "5": "populated place with 1,000,000 or more inhabitants",
        },
        "smoothing_mode": "edge_neighbours_only",
        "excluded_populated_place_codes": sorted(EXCLUDED_POPULATED_PLACE_CODES),
        "geonames_stats": geonames_stats,
        "smoothing_stats": smoothing_stats,
        "tier_summary": tier_summary,
    }
    print("Writing tile_commercial_value table ...", flush=True)
    write_commercial_table(args.tile_db, records, build_meta)
    print("Generating comparison report ...", flush=True)
    report = generate_comparison_report(args.region_pack_json, args.tile_db, args.report_prefix, build_meta)
    elapsed = time.monotonic() - started
    result = {
        "ok": True,
        "elapsed_seconds": round(elapsed, 3),
        "tile_db": str(args.tile_db),
        "geonames": str(args.geonames),
        "report": report,
        "tier_summary": tier_summary,
        "geonames_stats": geonames_stats,
    }
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
