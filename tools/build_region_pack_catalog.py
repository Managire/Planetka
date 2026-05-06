#!/usr/bin/env python3
"""Build precomputed Full Quality region-pack tile memberships from GADM.

The output is intentionally static. Blender and the Cloudflare Worker should
not do polygon intersection work at runtime; they should only consume the
generated tile-key memberships and pre-simplified country outlines.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.prepared import prep


DEFAULT_GPKG = Path("/Volumes/SSDA/Planetka Assets Extra/BO/gadm_410-levels.gpkg")
DEFAULT_JSON = Path("Resources/Region Packs/europe_region_packs_gadm.json")
DEFAULT_JS = Path("cloudflare-api/src/worker/region_packs.generated.js")
DEFAULT_PNG = Path("Resources/Region Packs/europe_region_packs_gadm.png")
CATALOG_VERSION = "europe_gadm_v2"
PAID_Z_LEVELS = (1, 2, 4, 8, 15, 30)
FREE_D_THRESHOLD = 60
EUROPE_CLIP_BBOX = (-25.0, 34.0, 45.0, 72.0)
MERGE_DIFFERENCE_RATIO = 0.50
SMALL_COUNTRY_AUTO_MERGE_TILE_LIMIT = 30

# Small sovereign states are intentionally excluded from first-pack products;
# they are usually covered by neighbouring tile licences or can be licensed
# through the normal scene purchase path.
EXCLUDED_MICROSTATES = {
    "AND": "Andorra",
    "LIE": "Liechtenstein",
    "MCO": "Monaco",
    "SMR": "San Marino",
    "VAT": "Vatican City",
}

# Russia and Turkey need a separate Europe/Asia boundary decision. Including
# whole ADM_0 geometries would make the Europe pack include large non-European
# areas, so they are excluded until that boundary is explicitly defined.
EXCLUDED_TRANSCONTINENTAL = {
    "RUS": "Russia",
    "TUR": "Turkey",
}

EUROPE_COUNTRY_CODES = (
    "ALB",
    "AUT",
    "BEL",
    "BIH",
    "BGR",
    "BLR",
    "CHE",
    "CYP",
    "CZE",
    "DEU",
    "DNK",
    "ESP",
    "EST",
    "FIN",
    "FRA",
    "GBR",
    "GRC",
    "HRV",
    "HUN",
    "IRL",
    "ISL",
    "ITA",
    "LTU",
    "LUX",
    "LVA",
    "MDA",
    "MKD",
    "MLT",
    "MNE",
    "NLD",
    "NOR",
    "POL",
    "PRT",
    "ROU",
    "SRB",
    "SVK",
    "SVN",
    "SWE",
    "UKR",
    "XKO",
)

MACRO_PACKS = (
    {
        "id": "western_europe",
        "name": "Western Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("AUT", "BEL", "CHE", "DEU", "FRA", "GBR", "IRL", "LUX", "NLD"),
    },
    {
        "id": "southern_europe",
        "name": "Southern Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": (
            "ALB",
            "BIH",
            "BGR",
            "CYP",
            "GRC",
            "HRV",
            "ITA",
            "MKD",
            "MLT",
            "MNE",
            "PRT",
            "SRB",
            "SVN",
            "ESP",
            "XKO",
        ),
    },
    {
        "id": "northern_europe",
        "name": "Northern Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("DNK", "EST", "FIN", "GBR", "IRL", "ISL", "LTU", "LVA", "NOR", "SWE"),
    },
    {
        "id": "eastern_europe",
        "name": "Eastern Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("BLR", "BGR", "CZE", "HUN", "MDA", "POL", "ROU", "SVK", "UKR"),
    },
    {
        "id": "balkans",
        "name": "Balkans",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("ALB", "BIH", "BGR", "GRC", "HRV", "MKD", "MNE", "ROU", "SRB", "SVN", "XKO"),
    },
    {
        "id": "scandinavia",
        "name": "Scandinavia",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("DNK", "FIN", "ISL", "NOR", "SWE"),
    },
    {
        "id": "mediterranean_europe",
        "name": "Mediterranean Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("ALB", "BIH", "CYP", "ESP", "FRA", "GRC", "HRV", "ITA", "MLT", "MNE", "PRT", "SVN"),
    },
    {
        "id": "central_europe",
        "name": "Central Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("AUT", "CHE", "CZE", "DEU", "HUN", "POL", "SVK", "SVN"),
    },
    {
        "id": "baltics",
        "name": "Baltics",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("EST", "LTU", "LVA"),
    },
    {
        "id": "europe",
        "name": "Europe",
        "type": "continent",
        "discount_percent": 50,
        "adm0_codes": EUROPE_COUNTRY_CODES,
    },
)

SPECIAL_GROUP_NAMES = {
    frozenset(("ALB", "MKD", "MNE", "XKO")): ("southwestern_balkans", "Southwestern Balkans"),
    frozenset(("BEL", "LUX", "NLD")): ("benelux", "Benelux"),
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())
    return re.sub(r"_+", "_", slug).strip("_") or "region_pack"


def list_name(values: list[str]) -> str:
    names = [str(value).strip() for value in values if str(value).strip()]
    if not names:
        return "Region Pack"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{', '.join(names[:-1])} & {names[-1]}"


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
    if geometry is None or geometry.is_empty:
        return []
    keys = []
    seen = set()
    prepared_bounds = geometry.bounds
    prepared_geometry = prep(geometry)
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
                if not prepared_geometry.intersects(poly):
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


def read_adm0(gpkg_path: Path):
    countries = gpd.read_file(gpkg_path, layer="ADM_0", columns=["GID_0", "COUNTRY", "geometry"])
    countries["GID_0"] = countries["GID_0"].astype(str).str.upper()
    return countries


def selected_for_codes(countries, codes: tuple[str, ...] | list[str], clip_bbox=EUROPE_CLIP_BBOX):
    safe_codes = tuple(str(code).strip().upper() for code in codes if str(code).strip())
    if not safe_codes:
        raise ValueError("No ADM_0 country codes supplied")
    selected = countries[countries["GID_0"].isin(safe_codes)].copy()
    missing = sorted(set(safe_codes) - set(selected["GID_0"].astype(str)))
    if missing:
        raise ValueError(f"Missing ADM_0 code(s): {', '.join(missing)}")
    if clip_bbox:
        clip = box(*clip_bbox)
        selected["geometry"] = selected.geometry.intersection(clip)
        selected = selected[~selected.geometry.is_empty].copy()
    if selected.empty:
        raise ValueError(f"ADM_0 code(s) clipped to empty geometry: {', '.join(safe_codes)}")
    return selected.sort_values("COUNTRY").reset_index(drop=True)


def union_geometry(selected):
    geometry = unary_union(selected.geometry.values)
    if geometry is not None and not geometry.is_empty and not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def counts_by_z(tile_keys: list[str]) -> dict[str, int]:
    counts = {}
    for key in tile_keys:
        z_value = key.split("_z", 1)[1].split("_", 1)[0]
        counts[z_value] = counts.get(z_value, 0) + 1
    return dict(sorted(counts.items()))


def country_records(selected) -> list[dict]:
    records = []
    for row in selected[["GID_0", "COUNTRY"]].drop_duplicates().sort_values("COUNTRY").itertuples(index=False):
        records.append({"GID_0": str(row.GID_0), "COUNTRY": str(row.COUNTRY)})
    return records


def _iter_polygon_geometries(geometry):
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
        return
    if isinstance(geometry, MultiPolygon):
        for part in geometry.geoms:
            yield from _iter_polygon_geometries(part)
        return
    if isinstance(geometry, GeometryCollection):
        for part in geometry.geoms:
            yield from _iter_polygon_geometries(part)


def country_outlines_for_web(selected, simplify_tolerance: float = 0.035, min_polygon_area: float = 0.002) -> list[dict]:
    outlines = []
    for row in selected.sort_values("COUNTRY").itertuples(index=False):
        geometry = getattr(row, "geometry", None)
        if geometry is None or geometry.is_empty:
            continue
        simplified = geometry.simplify(float(simplify_tolerance), preserve_topology=True)
        polygons = []
        for polygon in _iter_polygon_geometries(simplified):
            if polygon.area < float(min_polygon_area):
                continue
            coords = [
                [round(float(x_value), 4), round(float(y_value), 4)]
                for x_value, y_value in polygon.exterior.coords
            ]
            if len(coords) >= 4:
                polygons.append(coords)
        if not polygons:
            continue
        outlines.append(
            {
                "id": str(getattr(row, "GID_0", "") or ""),
                "name": str(getattr(row, "COUNTRY", "") or ""),
                "polygons": polygons,
            }
        )
    return outlines


def payload_from_selected(
    *,
    product_id: str,
    name: str,
    product_type: str,
    discount_percent: int,
    selected,
    adm0_codes: tuple[str, ...] | list[str],
    member_product_ids: list[str] | None = None,
    source_note: str = "GADM 4.10 ADM_0 polygon intersection",
    tile_keys_override: list[str] | None = None,
) -> dict:
    geometry = union_geometry(selected)
    tile_keys = sorted(set(tile_keys_override)) if tile_keys_override is not None else region_tiles_for_geometry(geometry)
    bounds = [float(value) for value in selected.total_bounds]
    return {
        "id": product_id,
        "name": name,
        "type": product_type,
        "discount_percent": int(discount_percent),
        "catalog_version": CATALOG_VERSION,
        "source": source_note,
        "adm0_codes": sorted(set(str(code).upper() for code in adm0_codes)),
        "countries": country_records(selected),
        "country_product_ids": list(member_product_ids or []),
        "tile_count": len(tile_keys),
        "counts_by_z": counts_by_z(tile_keys),
        "bounds": bounds,
        "bbox": bounds,
        "outlines": country_outlines_for_web(selected),
        "tile_keys": tile_keys,
    }


def build_country_payloads(countries) -> list[dict]:
    payloads = []
    for index, code in enumerate(EUROPE_COUNTRY_CODES, start=1):
        print(f"Building country {index}/{len(EUROPE_COUNTRY_CODES)}: {code}", file=sys.stderr, flush=True)
        selected = selected_for_codes(countries, [code])
        records = country_records(selected)
        name = records[0]["COUNTRY"] if records else code
        payloads.append(
            payload_from_selected(
                product_id=slugify(name),
                name=name,
                product_type="country",
                discount_percent=20,
                selected=selected,
                adm0_codes=[code],
            )
        )
    return payloads


def merge_reason(a: dict, b: dict) -> str:
    tiles_a = set(a.get("tile_keys") or [])
    tiles_b = set(b.get("tile_keys") or [])
    if not tiles_a or not tiles_b:
        return ""
    if tiles_a == tiles_b:
        return "identical_tile_set"
    if tiles_a.issubset(tiles_b):
        return f"{a['id']}_subset_of_{b['id']}"
    if tiles_b.issubset(tiles_a):
        return f"{b['id']}_subset_of_{a['id']}"
    if len(tiles_a) > SMALL_COUNTRY_AUTO_MERGE_TILE_LIMIT or len(tiles_b) > SMALL_COUNTRY_AUTO_MERGE_TILE_LIMIT:
        return ""
    unique_a = len(tiles_a - tiles_b)
    unique_b = len(tiles_b - tiles_a)
    if unique_a < MERGE_DIFFERENCE_RATIO * len(tiles_a):
        return f"{a['id']}_unique_tiles_{unique_a}_lt_{MERGE_DIFFERENCE_RATIO:.2f}_of_{len(tiles_a)}"
    if unique_b < MERGE_DIFFERENCE_RATIO * len(tiles_b):
        return f"{b['id']}_unique_tiles_{unique_b}_lt_{MERGE_DIFFERENCE_RATIO:.2f}_of_{len(tiles_b)}"
    return ""


def connected_components(size: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(size))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int):
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for left, right in edges:
        union(left, right)
    grouped = defaultdict(list)
    for index in range(size):
        grouped[find(index)].append(index)
    return list(grouped.values())


def merged_product_identity(codes: list[str], names: list[str]) -> tuple[str, str]:
    code_key = frozenset(codes)
    if code_key in SPECIAL_GROUP_NAMES:
        return SPECIAL_GROUP_NAMES[code_key]
    return slugify("_".join(names)), list_name(names)


def merge_country_payloads(country_payloads: list[dict], countries) -> tuple[list[dict], list[dict], dict[str, str]]:
    edges = []
    pair_report = []
    for left in range(len(country_payloads)):
        for right in range(left + 1, len(country_payloads)):
            reason = merge_reason(country_payloads[left], country_payloads[right])
            if not reason:
                continue
            edges.append((left, right))
            pair_report.append(
                {
                    "left": country_payloads[left]["id"],
                    "right": country_payloads[right]["id"],
                    "reason": reason,
                    "left_tile_count": country_payloads[left]["tile_count"],
                    "right_tile_count": country_payloads[right]["tile_count"],
                }
            )
    components = connected_components(len(country_payloads), edges)
    merged = []
    code_to_product_id = {}
    for component in components:
        component_payloads = [country_payloads[index] for index in sorted(component, key=lambda idx: country_payloads[idx]["name"])]
        codes = sorted({code for payload in component_payloads for code in payload.get("adm0_codes", [])})
        names = sorted({record["COUNTRY"] for payload in component_payloads for record in payload.get("countries", [])})
        if len(component_payloads) == 1:
            payload = dict(component_payloads[0])
            payload["country_product_ids"] = [payload["id"]]
        else:
            selected = selected_for_codes(countries, codes)
            product_id, name = merged_product_identity(codes, names)
            merged_tile_keys = sorted({
                key
                for source in component_payloads
                for key in source.get("tile_keys", [])
            })
            payload = payload_from_selected(
                product_id=product_id,
                name=name,
                product_type="country",
                discount_percent=20,
                selected=selected,
                adm0_codes=codes,
                member_product_ids=[payload["id"] for payload in component_payloads],
                source_note="GADM 4.10 ADM_0 polygon intersection; merged by paid tile-set overlap",
                tile_keys_override=merged_tile_keys,
            )
            payload["merged_from"] = [
                {
                    "id": source["id"],
                    "name": source["name"],
                    "tile_count": source["tile_count"],
                }
                for source in component_payloads
            ]
        for code in codes:
            code_to_product_id[code] = payload["id"]
        merged.append(payload)
    merged.sort(key=lambda payload: (payload["name"], payload["id"]))
    return merged, pair_report, code_to_product_id


def product_ids_for_codes(codes: tuple[str, ...] | list[str], code_to_product_id: dict[str, str]) -> list[str]:
    seen = set()
    ids = []
    for code in codes:
        product_id = code_to_product_id.get(str(code).upper())
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        ids.append(product_id)
    return ids


def build_macro_payloads(countries, code_to_product_id: dict[str, str], country_payloads_by_code: dict[str, dict]) -> list[dict]:
    payloads = []
    for index, pack in enumerate(MACRO_PACKS, start=1):
        print(f"Building macro {index}/{len(MACRO_PACKS)}: {pack['id']}", file=sys.stderr, flush=True)
        selected = selected_for_codes(countries, pack["adm0_codes"])
        tile_keys = sorted({
            key
            for code in pack["adm0_codes"]
            for key in (country_payloads_by_code.get(str(code).upper(), {}).get("tile_keys") or [])
        })
        payloads.append(
            payload_from_selected(
                product_id=pack["id"],
                name=pack["name"],
                product_type=pack["type"],
                discount_percent=pack["discount_percent"],
                selected=selected,
                adm0_codes=pack["adm0_codes"],
                member_product_ids=product_ids_for_codes(pack["adm0_codes"], code_to_product_id),
                tile_keys_override=tile_keys,
            )
        )
    return payloads


def build_catalog(gpkg_path: Path) -> dict:
    countries = read_adm0(gpkg_path)
    raw_countries = build_country_payloads(countries)
    country_payloads_by_code = {
        (payload.get("adm0_codes") or [""])[0]: payload
        for payload in raw_countries
        if payload.get("adm0_codes")
    }
    country_products, merge_report, code_to_product_id = merge_country_payloads(raw_countries, countries)
    macro_products = build_macro_payloads(countries, code_to_product_id, country_payloads_by_code)
    products = country_products + [payload for payload in macro_products if payload["id"] != "europe"]
    europe = next((payload for payload in macro_products if payload["id"] == "europe"), None)
    if europe:
        products.append(europe)
    products.sort(key=lambda payload: (0 if payload["type"] == "country" else 1 if payload["type"] == "macro_region" else 2, payload["name"]))
    return {
        "catalog_version": CATALOG_VERSION,
        "source": "GADM 4.10 ADM_0 polygon intersection clipped to Europe working extent",
        "europe_clip_bbox": list(EUROPE_CLIP_BBOX),
        "paid_z_levels": list(PAID_Z_LEVELS),
        "free_d_threshold": FREE_D_THRESHOLD,
        "merge_difference_ratio": MERGE_DIFFERENCE_RATIO,
        "small_country_auto_merge_tile_limit": SMALL_COUNTRY_AUTO_MERGE_TILE_LIMIT,
        "excluded_microstates": EXCLUDED_MICROSTATES,
        "excluded_transcontinental": EXCLUDED_TRANSCONTINENTAL,
        "raw_country_count": len(raw_countries),
        "country_product_count": len(country_products),
        "product_count": len(products),
        "merge_report": merge_report,
        "products": products,
    }


def public_product_payload(payload: dict) -> dict:
    result = {
        "id": payload["id"],
        "name": payload["name"],
        "type": payload["type"],
        "discount_percent": payload["discount_percent"],
        "bbox": payload.get("bbox") or payload.get("bounds") or [],
    }
    if payload.get("country_product_ids"):
        result["countries"] = payload["country_product_ids"]
    if payload.get("adm0_codes"):
        result["adm0_codes"] = payload["adm0_codes"]
    return result


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_js(path: Path, catalog: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    pack_payloads = catalog.get("products") or []
    lines = [
        "// Generated by tools/build_region_pack_catalog.py. Do not edit by hand.",
        f"export const GENERATED_REGION_PACK_CATALOG_VERSION = {json.dumps(catalog.get('catalog_version') or CATALOG_VERSION)};",
        f"export const GENERATED_REGION_PACK_PRODUCTS = {json.dumps([public_product_payload(payload) for payload in pack_payloads], ensure_ascii=True, separators=(',', ':'))};",
        "export const GENERATED_REGION_PACK_TILE_KEYS = {",
    ]
    for payload in pack_payloads:
        lines.append(f"  {json.dumps(payload['id'])}: [")
        for key in payload["tile_keys"]:
            lines.append(f"    {json.dumps(key)},")
        lines.append("  ],")
    lines.append("};")
    detail_payload = {}
    for payload in pack_payloads:
        detail_payload[payload["id"]] = {
            "bounds": payload.get("bounds", []),
            "countries": payload.get("countries", []),
            "outlines": payload.get("outlines", []),
            "adm0_codes": payload.get("adm0_codes", []),
            "merged_from": payload.get("merged_from", []),
            "counts_by_z": payload.get("counts_by_z", {}),
        }
    lines.append("")
    lines.append(f"export const GENERATED_REGION_PACK_DETAILS = {json.dumps(detail_payload, ensure_ascii=True, separators=(',', ':'))};")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_png(path: Path, catalog: dict, product_id: str = "europe"):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    product = next((entry for entry in catalog.get("products", []) if entry.get("id") == product_id), None)
    if not product:
        return
    gpkg_path = Path(catalog.get("gpkg_path") or DEFAULT_GPKG)
    countries = read_adm0(gpkg_path)
    selected = selected_for_codes(countries, product.get("adm0_codes") or [])
    tile_keys = product.get("tile_keys") or []
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
            linewidth=0.35,
            alpha=0.75,
        )
        ax.add_patch(rect)
    minx, miny, maxx, maxy = selected.total_bounds
    pad_x = max(1.0, (maxx - minx) * 0.08)
    pad_y = max(1.0, (maxy - miny) * 0.08)
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(f"{product['name']} GADM pack: exact country polygons + z001 tile coverage")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, color="#999999", alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def summarize_catalog(catalog: dict) -> dict:
    products = catalog.get("products") or []
    merged = [entry for entry in products if entry.get("merged_from")]
    return {
        "catalog_version": catalog.get("catalog_version"),
        "product_count": len(products),
        "country_product_count": sum(1 for entry in products if entry.get("type") == "country"),
        "macro_region_count": sum(1 for entry in products if entry.get("type") == "macro_region"),
        "continent_count": sum(1 for entry in products if entry.get("type") == "continent"),
        "merged_product_count": len(merged),
        "merged_products": [
            {
                "id": entry.get("id"),
                "name": entry.get("name"),
                "countries": [source.get("name") for source in entry.get("merged_from") or []],
                "tile_count": entry.get("tile_count"),
            }
            for entry in merged
        ],
        "products": [
            {
                "id": entry.get("id"),
                "name": entry.get("name"),
                "type": entry.get("type"),
                "tile_count": entry.get("tile_count"),
                "counts_by_z": entry.get("counts_by_z"),
            }
            for entry in products
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpkg", type=Path, default=DEFAULT_GPKG)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--js-output", type=Path, default=DEFAULT_JS)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG)
    parser.add_argument("--skip-png", action="store_true")
    args = parser.parse_args()

    catalog = build_catalog(args.gpkg)
    catalog["gpkg_path"] = str(args.gpkg)
    write_json(args.json_output, catalog)
    write_js(args.js_output, catalog)
    if not args.skip_png:
        write_png(args.png_output, catalog, "europe")
    summary = summarize_catalog(catalog)
    summary.update(
        {
            "json_output": str(args.json_output),
            "js_output": str(args.js_output),
            "png_output": "" if args.skip_png else str(args.png_output),
        }
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
