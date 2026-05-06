#!/usr/bin/env python3
"""Build precomputed Full Quality region-pack tile memberships from GADM.

The output is intentionally static. Blender and the Cloudflare Worker should
not do polygon intersection work at runtime; they should only consume the
generated tile-key memberships.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box
from shapely.ops import unary_union


DEFAULT_GPKG = Path("/Volumes/SSDA/Planetka Assets Extra/BO/gadm_410-levels.gpkg")
DEFAULT_JSON = Path("Resources/Region Packs/southern_europe_gadm_test.json")
DEFAULT_JS = Path("cloudflare-api/src/worker/region_packs.generated.js")
DEFAULT_PNG = Path("Resources/Region Packs/southern_europe_gadm_test.png")
PAID_Z_LEVELS = (1, 2, 4, 8, 15, 30)
FREE_D_THRESHOLD = 60

PACKS = {
    "southern_europe": {
        "id": "southern_europe",
        "name": "Southern Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": (
            "ALB",
            "BIH",
            "BGR",
            "HRV",
            "GRC",
            "ITA",
            "XKO",
            "MNE",
            "MKD",
            "PRT",
            "SRB",
            "SVN",
            "ESP",
        ),
        "clip_bbox": (-10.0, 35.0, 30.0, 47.5),
    },
}


def tile_key(x_value: int, y_value: int, z_value: int, d_value: int) -> str:
    return f"x{x_value:03d}_y{y_value:03d}_z{z_value:03d}_d{d_value:03d}"


def paid_d_levels_for_z(z_value: int) -> tuple[int, ...]:
    # A finer d-level licence covers all coarser d-levels in the same tile
    # family, so only the finest paid d-level is needed for pack ownership.
    return (z_value,) if 0 < z_value < FREE_D_THRESHOLD else ()


def candidate_ranges(bounds, z_value: int):
    min_lon, min_lat, max_lon, max_lat = bounds
    min_x = max(0, min(359, math.floor(float(min_lon) + 180.0)))
    max_x = max(0, min(359, math.ceil(float(max_lon) + 180.0) - 1))
    min_y = max(0, min(179, math.floor(float(min_lat) + 90.0)))
    max_y = max(0, min(179, math.ceil(float(max_lat) + 90.0) - 1))
    start_x = math.floor(min_x / z_value) * z_value
    end_x = math.floor(max_x / z_value) * z_value
    start_y = math.floor(min_y / z_value) * z_value
    end_y = math.floor(max_y / z_value) * z_value
    return start_x, end_x, start_y, end_y


def tile_polygon(x_value: int, y_value: int, z_value: int):
    return box(
        float(x_value) - 180.0,
        float(y_value) - 90.0,
        float(x_value + z_value) - 180.0,
        float(y_value + z_value) - 90.0,
    )


def region_tiles_for_geometry(geometry, min_intersection_area: float = 1e-10) -> list[str]:
    keys = []
    seen = set()
    prepared_bounds = geometry.bounds
    for z_value in PAID_Z_LEVELS:
        d_levels = paid_d_levels_for_z(z_value)
        if not d_levels:
            continue
        start_x, end_x, start_y, end_y = candidate_ranges(prepared_bounds, z_value)
        for x_value in range(start_x, end_x + 1, z_value):
            if x_value < 0 or x_value > 359:
                continue
            for y_value in range(start_y, end_y + 1, z_value):
                if y_value < 0 or y_value > 179:
                    continue
                poly = tile_polygon(x_value, y_value, z_value)
                if not geometry.intersects(poly):
                    continue
                if geometry.intersection(poly).area <= min_intersection_area:
                    continue
                for d_value in d_levels:
                    key = tile_key(x_value, y_value, z_value, d_value)
                    if key in seen:
                        continue
                    seen.add(key)
                    keys.append(key)
    return sorted(keys)


def read_pack_geometry(gpkg_path: Path, pack: dict):
    codes = tuple(str(code).strip().upper() for code in pack.get("adm0_codes", ()) if str(code).strip())
    if not codes:
        raise ValueError(f"Pack {pack.get('id')} has no ADM_0 country codes")
    countries = gpd.read_file(gpkg_path, layer="ADM_0", columns=["GID_0", "COUNTRY", "geometry"])
    selected = countries[countries["GID_0"].isin(codes)].copy()
    missing = sorted(set(codes) - set(selected["GID_0"].astype(str)))
    if missing:
        raise ValueError(f"Missing ADM_0 code(s) in {gpkg_path}: {', '.join(missing)}")
    geometry = unary_union(selected.geometry.values)
    clip_bbox = pack.get("clip_bbox")
    if clip_bbox:
        geometry = geometry.intersection(box(*clip_bbox))
        selected = selected.copy()
        selected["geometry"] = selected.geometry.intersection(box(*clip_bbox))
        selected = selected[~selected.geometry.is_empty].copy()
    return selected, geometry


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_js(path: Path, pack_payloads: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "// Generated by tools/build_region_pack_catalog.py. Do not edit by hand.",
        "export const GENERATED_REGION_PACK_TILE_KEYS = {",
    ]
    for payload in pack_payloads:
        lines.append(f"  {json.dumps(payload['id'])}: [")
        for key in payload["tile_keys"]:
            lines.append(f"    {json.dumps(key)},")
        lines.append("  ],")
    lines.append("};")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_png(path: Path, selected, tile_keys: list[str]):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(13, 8), dpi=160)
    selected.boundary.plot(ax=ax, color="#111111", linewidth=0.8)
    selected.plot(ax=ax, color="#d9e8ff", edgecolor="#111111", linewidth=0.25, alpha=0.65)
    z001 = [key for key in tile_keys if "_z001_" in key]
    for key in z001:
        x_value = int(key[1:4])
        y_value = int(key[6:9])
        rect = Rectangle(
            (x_value - 180.0, y_value - 90.0),
            1.0,
            1.0,
            fill=False,
            edgecolor="#ff3b30",
            linewidth=0.45,
            alpha=0.8,
        )
        ax.add_patch(rect)
    minx, miny, maxx, maxy = selected.total_bounds
    pad_x = max(1.0, (maxx - minx) * 0.08)
    pad_y = max(1.0, (maxy - miny) * 0.08)
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Southern Europe GADM pack: exact country polygons + z001 tile coverage")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, color="#999999", alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def build_pack(pack_id: str, gpkg_path: Path) -> dict:
    pack = PACKS.get(pack_id)
    if not pack:
        raise ValueError(f"Unknown pack id: {pack_id}")
    selected, geometry = read_pack_geometry(gpkg_path, pack)
    tile_keys = region_tiles_for_geometry(geometry)
    counts_by_z = {}
    for key in tile_keys:
        z_value = key.split("_z", 1)[1].split("_", 1)[0]
        counts_by_z[z_value] = counts_by_z.get(z_value, 0) + 1
    return {
        "id": pack["id"],
        "name": pack["name"],
        "type": pack["type"],
        "discount_percent": pack["discount_percent"],
        "source": "GADM 4.10 ADM_0 polygon intersection",
        "adm0_codes": list(pack["adm0_codes"]),
        "clip_bbox": list(pack.get("clip_bbox", ())),
        "countries": selected[["GID_0", "COUNTRY"]].sort_values("COUNTRY").to_dict("records"),
        "tile_count": len(tile_keys),
        "counts_by_z": dict(sorted(counts_by_z.items())),
        "bounds": [float(value) for value in selected.total_bounds],
        "tile_keys": tile_keys,
    }, selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpkg", type=Path, default=DEFAULT_GPKG)
    parser.add_argument("--pack", default="southern_europe", choices=sorted(PACKS))
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--js-output", type=Path, default=DEFAULT_JS)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG)
    args = parser.parse_args()

    payload, selected = build_pack(args.pack, args.gpkg)
    write_json(args.json_output, payload)
    write_js(args.js_output, [payload])
    write_png(args.png_output, selected, payload["tile_keys"])
    print(json.dumps({
        "pack": payload["id"],
        "tile_count": payload["tile_count"],
        "counts_by_z": payload["counts_by_z"],
        "countries": [entry["COUNTRY"] for entry in payload["countries"]],
        "json_output": str(args.json_output),
        "js_output": str(args.js_output),
        "png_output": str(args.png_output),
    }, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
