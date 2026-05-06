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
import pandas as pd
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.prepared import prep


DEFAULT_GPKG = Path("/Volumes/SSDA/Planetka Assets Extra/BO/gadm_410-levels.gpkg")
DEFAULT_JSON = Path("Resources/Region Packs/region_packs_gadm.json")
DEFAULT_JS = Path("cloudflare-api/src/worker/region_packs.generated.js")
DEFAULT_PNG = Path("Resources/Region Packs/region_packs_gadm.png")
CATALOG_VERSION = "gadm_regions_v5"
PAID_Z_LEVELS = (1, 2, 4, 8, 15, 30)
FREE_D_THRESHOLD = 60
MERGE_DIFFERENCE_RATIO = 0.50
SMALL_COUNTRY_AUTO_MERGE_TILE_LIMIT = 30

EUROPE_CLIP_BBOX = (-25.0, 34.0, 45.0, 72.0)
SOUTH_AMERICA_CLIP_BBOX = (-92.5, -60.0, -30.0, 15.0)
CARIBBEAN_CLIP_BBOX = (-90.0, 5.0, -55.0, 30.0)
AUSTRALIA_CLIP_BBOX = (110.0, -45.0, 155.0, -9.0)

EXCLUDED_EUROPE_MICROSTATES = {
    "AND": "Andorra",
    "LIE": "Liechtenstein",
    "MCO": "Monaco",
    "SMR": "San Marino",
    "VAT": "Vatican City",
}

EXCLUDED_EUROPE_TRANSCONTINENTAL = {
    "RUS": "Russia",
    "TUR": "Turkey",
}

EUROPE_COUNTRY_CODES = (
    "ALB", "AUT", "BEL", "BIH", "BGR", "BLR", "CHE", "CYP", "CZE", "DEU",
    "DNK", "ESP", "EST", "FIN", "FRA", "GBR", "GRC", "HRV", "HUN", "IRL",
    "ISL", "ITA", "LTU", "LUX", "LVA", "MDA", "MKD", "MLT", "MNE", "NLD",
    "NOR", "POL", "PRT", "ROU", "SRB", "SVK", "SVN", "SWE", "UKR", "XKO",
)

SOUTH_AMERICA_COUNTRY_CODES = (
    "ARG", "BOL", "BRA", "CHL", "COL", "ECU", "FLK", "GUF", "GUY", "PRY",
    "PER", "SUR", "URY", "VEN",
)

CARIBBEAN_LARGE_ISLAND_CODES = (
    "BHS", "CUB", "DOM", "HTI", "JAM", "TTO",
)

CARIBBEAN_SMALL_ISLAND_CODES = (
    "ABW", "AIA", "ATG", "BES", "BRB", "CUW", "CYM", "DMA", "GLP", "GRD",
    "KNA", "LCA", "MSR", "MTQ", "SXM", "TCA", "VCT", "VGB", "VIR",
)

AUSTRALIA_MAINLAND_REGION_CODES = (
    "AUS.5_1",   # New South Wales
    "AUS.6_1",   # Northern Territory
    "AUS.7_1",   # Queensland
    "AUS.8_1",   # South Australia
    "AUS.9_1",   # Tasmania
    "AUS.10_1",  # Victoria
    "AUS.11_1",  # Western Australia
)

AUSTRALIA_ACT_AND_JERVIS_CODES = (
    "AUS.2_1",  # Australian Capital Territory
    "AUS.4_1",  # Jervis Bay Territory
)

AUSTRALIA_EXTERNAL_ISLAND_CODES = (
    "AUS.1_1",  # Ashmore and Cartier Islands
    "AUS.3_1",  # Coral Sea Islands Territory
)

AUSTRALIA_ALL_REGION_CODES = (
    *AUSTRALIA_MAINLAND_REGION_CODES,
    *AUSTRALIA_ACT_AND_JERVIS_CODES,
    *AUSTRALIA_EXTERNAL_ISLAND_CODES,
)

USA_STATE_CODES = (
    "USA.1_1", "USA.2_1", "USA.3_1", "USA.4_1", "USA.5_1", "USA.6_1",
    "USA.7_1", "USA.8_1", "USA.9_1", "USA.10_1", "USA.11_1", "USA.12_1",
    "USA.13_1", "USA.14_1", "USA.15_1", "USA.16_1", "USA.17_1", "USA.18_1",
    "USA.19_1", "USA.20_1", "USA.21_1", "USA.22_1", "USA.23_1", "USA.24_1",
    "USA.25_1", "USA.26_1", "USA.27_1", "USA.28_1", "USA.29_1", "USA.30_1",
    "USA.31_1", "USA.32_1", "USA.33_1", "USA.34_1", "USA.35_1", "USA.36_1",
    "USA.37_1", "USA.38_1", "USA.39_1", "USA.40_1", "USA.41_1", "USA.42_1",
    "USA.43_1", "USA.44_1", "USA.45_1", "USA.46_1", "USA.47_1", "USA.48_1",
    "USA.49_1", "USA.50_1", "USA.51_1",
)

USA_NORTHEAST_CODES = (
    "USA.7_1", "USA.20_1", "USA.22_1", "USA.30_1", "USA.31_1", "USA.33_1",
    "USA.39_1", "USA.40_1", "USA.46_1",
)

USA_MIDWEST_CODES = (
    "USA.14_1", "USA.15_1", "USA.16_1", "USA.17_1", "USA.23_1", "USA.24_1",
    "USA.26_1", "USA.28_1", "USA.35_1", "USA.36_1", "USA.42_1", "USA.50_1",
)

USA_SOUTH_CODES = (
    "USA.1_1", "USA.4_1", "USA.8_1", "USA.9_1", "USA.10_1", "USA.11_1",
    "USA.18_1", "USA.19_1", "USA.21_1", "USA.25_1", "USA.34_1", "USA.37_1",
    "USA.41_1", "USA.43_1", "USA.44_1", "USA.47_1", "USA.49_1",
)

USA_WEST_CODES = (
    "USA.2_1", "USA.3_1", "USA.5_1", "USA.6_1", "USA.12_1", "USA.13_1",
    "USA.27_1", "USA.29_1", "USA.32_1", "USA.38_1", "USA.45_1", "USA.48_1",
    "USA.51_1",
)

CANADA_REGION_SPECS = (
    ("CAN.1_1", "alberta", "Alberta"),
    ("CAN.2_1", "british_columbia", "British Columbia"),
    ("CAN.3_1", "manitoba", "Manitoba"),
    ("CAN.4_1", "new_brunswick", "New Brunswick"),
    ("CAN.5_1", "newfoundland_and_labrador", "Newfoundland and Labrador"),
    ("CAN.6_1", "northwest_territories", "Northwest Territories"),
    ("CAN.7_1", "nova_scotia", "Nova Scotia"),
    ("CAN.8_1", "nunavut", "Nunavut"),
    ("CAN.9_1", "ontario", "Ontario"),
    ("CAN.10_1", "prince_edward_island", "Prince Edward Island"),
    ("CAN.11_1", "quebec", "Québec"),
    ("CAN.12_1", "saskatchewan", "Saskatchewan"),
    ("CAN.13_1", "yukon", "Yukon"),
)

CANADA_REGION_CODES = tuple(code for code, _product_id, _name in CANADA_REGION_SPECS)
CANADA_WEST_CODES = ("CAN.1_1", "CAN.2_1", "CAN.3_1", "CAN.12_1")
CANADA_EAST_CODES = ("CAN.4_1", "CAN.5_1", "CAN.7_1", "CAN.9_1", "CAN.10_1", "CAN.11_1")
CANADA_NORTH_CODES = ("CAN.6_1", "CAN.8_1", "CAN.13_1")

NORTH_ATLANTIC_ISLAND_CODES = ("BMU", "SPM")
NORTH_AMERICA_COUNTRY_CODES = ("GRL", "MEX", *NORTH_ATLANTIC_ISLAND_CODES)
NORTH_AMERICA_ALL_MEMBERS = (
    *USA_STATE_CODES,
    *CANADA_REGION_CODES,
    *NORTH_AMERICA_COUNTRY_CODES,
)

LOCAL_PRODUCT_SPECS = (
    *(
        {
            "adm0_codes": (code,),
            "clip_bbox": EUROPE_CLIP_BBOX,
            "merge_scope": "europe",
            "auto_merge": True,
            "discount_percent": 20,
        }
        for code in EUROPE_COUNTRY_CODES
    ),
    *(
        {
            "adm0_codes": (code,),
            "clip_bbox": SOUTH_AMERICA_CLIP_BBOX,
            "merge_scope": "south_america",
            "auto_merge": False,
            "discount_percent": 20,
        }
        for code in SOUTH_AMERICA_COUNTRY_CODES
    ),
    *(
        {
            "adm0_codes": (code,),
            "clip_bbox": CARIBBEAN_CLIP_BBOX,
            "merge_scope": "caribbean",
            "auto_merge": False,
            "discount_percent": 20,
        }
        for code in CARIBBEAN_LARGE_ISLAND_CODES
    ),
    {
        "id": "caribbean_islands",
        "name": "Caribbean Islands",
        "adm0_codes": CARIBBEAN_SMALL_ISLAND_CODES,
        "clip_bbox": CARIBBEAN_CLIP_BBOX,
        "merge_scope": "caribbean",
        "auto_merge": False,
        "discount_percent": 20,
        "source_note": "GADM 4.10 ADM_0 polygon intersection; grouped small Caribbean island nations and territories",
    },
    *(
        {
            "adm1_codes": (code,),
            "clip_bbox": AUSTRALIA_CLIP_BBOX,
            "merge_scope": "australia",
            "auto_merge": False,
            "discount_percent": 20,
        }
        for code in AUSTRALIA_MAINLAND_REGION_CODES
    ),
    {
        "id": "australian_capital_territory_and_jervis_bay",
        "name": "Australian Capital Territory & Jervis Bay",
        "adm1_codes": AUSTRALIA_ACT_AND_JERVIS_CODES,
        "clip_bbox": AUSTRALIA_CLIP_BBOX,
        "merge_scope": "australia",
        "auto_merge": False,
        "discount_percent": 20,
        "source_note": "GADM 4.10 ADM_1 polygon intersection; grouped ACT and Jervis Bay Territory",
    },
    {
        "id": "australian_external_islands",
        "name": "Australian External Islands",
        "adm1_codes": AUSTRALIA_EXTERNAL_ISLAND_CODES,
        "clip_bbox": AUSTRALIA_CLIP_BBOX,
        "merge_scope": "australia",
        "auto_merge": False,
        "discount_percent": 20,
        "source_note": "GADM 4.10 ADM_1 polygon intersection; grouped small Australian external island territories",
    },
    *(
        {
            "adm1_codes": (code,),
            "merge_scope": "north_america",
            "auto_merge": False,
            "discount_percent": 20,
        }
        for code in USA_STATE_CODES
    ),
    *(
        {
            "id": product_id,
            "name": name,
            "adm1_codes": (code,),
            "merge_scope": "north_america",
            "auto_merge": False,
            "discount_percent": 20,
        }
        for code, product_id, name in CANADA_REGION_SPECS
    ),
    {
        "id": "greenland",
        "name": "Greenland",
        "adm0_codes": ("GRL",),
        "merge_scope": "north_america",
        "auto_merge": False,
        "discount_percent": 20,
    },
    {
        "id": "mexico",
        "name": "Mexico",
        "adm0_codes": ("MEX",),
        "merge_scope": "north_america",
        "auto_merge": False,
        "discount_percent": 20,
    },
    {
        "id": "north_atlantic_islands",
        "name": "North Atlantic Islands",
        "adm0_codes": NORTH_ATLANTIC_ISLAND_CODES,
        "merge_scope": "north_america",
        "auto_merge": False,
        "discount_percent": 20,
        "source_note": "GADM 4.10 ADM_0 polygon intersection; grouped small North Atlantic island territories",
    },
)

MACRO_PACKS = (
    {
        "id": "western_europe",
        "name": "Western Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("AUT", "BEL", "CHE", "DEU", "FRA", "GBR", "IRL", "LUX", "NLD"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "southern_europe",
        "name": "Southern Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("ALB", "BIH", "BGR", "CYP", "GRC", "HRV", "ITA", "MKD", "MLT", "MNE", "PRT", "SRB", "SVN", "ESP", "XKO"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "northern_europe",
        "name": "Northern Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("DNK", "EST", "FIN", "GBR", "IRL", "ISL", "LTU", "LVA", "NOR", "SWE"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "eastern_europe",
        "name": "Eastern Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("BLR", "BGR", "CZE", "HUN", "MDA", "POL", "ROU", "SVK", "UKR"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "balkans",
        "name": "Balkans",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("ALB", "BIH", "BGR", "GRC", "HRV", "MKD", "MNE", "ROU", "SRB", "SVN", "XKO"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "scandinavia",
        "name": "Scandinavia",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("DNK", "FIN", "ISL", "NOR", "SWE"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "mediterranean_europe",
        "name": "Mediterranean Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("ALB", "BIH", "CYP", "ESP", "FRA", "GRC", "HRV", "ITA", "MLT", "MNE", "PRT", "SVN"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "central_europe",
        "name": "Central Europe",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("AUT", "CHE", "CZE", "DEU", "HUN", "POL", "SVK", "SVN"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "baltics",
        "name": "Baltics",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("EST", "LTU", "LVA"),
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "europe",
        "name": "Europe",
        "type": "continent",
        "discount_percent": 50,
        "adm0_codes": EUROPE_COUNTRY_CODES,
        "clip_bbox": EUROPE_CLIP_BBOX,
    },
    {
        "id": "andean_south_america",
        "name": "Andean South America",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("BOL", "CHL", "COL", "ECU", "PER", "VEN"),
        "clip_bbox": SOUTH_AMERICA_CLIP_BBOX,
    },
    {
        "id": "southern_cone",
        "name": "Southern Cone",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("ARG", "CHL", "FLK", "PRY", "URY"),
        "clip_bbox": SOUTH_AMERICA_CLIP_BBOX,
    },
    {
        "id": "guianas",
        "name": "Guianas",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("GUF", "GUY", "SUR"),
        "clip_bbox": SOUTH_AMERICA_CLIP_BBOX,
    },
    {
        "id": "amazon_basin",
        "name": "Amazon Basin",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": ("BOL", "BRA", "COL", "ECU", "GUF", "GUY", "PER", "SUR", "VEN"),
        "clip_bbox": SOUTH_AMERICA_CLIP_BBOX,
    },
    {
        "id": "south_america",
        "name": "South America",
        "type": "continent",
        "discount_percent": 50,
        "adm0_codes": SOUTH_AMERICA_COUNTRY_CODES,
        "clip_bbox": SOUTH_AMERICA_CLIP_BBOX,
    },
    {
        "id": "caribbean",
        "name": "Caribbean",
        "type": "macro_region",
        "discount_percent": 30,
        "adm0_codes": CARIBBEAN_LARGE_ISLAND_CODES + CARIBBEAN_SMALL_ISLAND_CODES,
        "clip_bbox": CARIBBEAN_CLIP_BBOX,
    },
    {
        "id": "eastern_australia",
        "name": "Eastern Australia",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": (
            *AUSTRALIA_ACT_AND_JERVIS_CODES,
            "AUS.5_1",   # New South Wales
            "AUS.7_1",   # Queensland
            "AUS.9_1",   # Tasmania
            "AUS.10_1",  # Victoria
        ),
        "clip_bbox": AUSTRALIA_CLIP_BBOX,
    },
    {
        "id": "western_and_central_australia",
        "name": "Western & Central Australia",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": (
            "AUS.6_1",   # Northern Territory
            "AUS.8_1",   # South Australia
            "AUS.11_1",  # Western Australia
            *AUSTRALIA_EXTERNAL_ISLAND_CODES,
        ),
        "clip_bbox": AUSTRALIA_CLIP_BBOX,
    },
    {
        "id": "australia",
        "name": "Australia",
        "type": "continent",
        "discount_percent": 50,
        "adm1_codes": AUSTRALIA_ALL_REGION_CODES,
        "clip_bbox": AUSTRALIA_CLIP_BBOX,
    },
    {
        "id": "western_united_states",
        "name": "Western United States",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": USA_WEST_CODES,
    },
    {
        "id": "southern_united_states",
        "name": "Southern United States",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": USA_SOUTH_CODES,
    },
    {
        "id": "midwestern_united_states",
        "name": "Midwestern United States",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": USA_MIDWEST_CODES,
    },
    {
        "id": "northeastern_united_states",
        "name": "Northeastern United States",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": USA_NORTHEAST_CODES,
    },
    {
        "id": "united_states",
        "name": "United States",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": USA_STATE_CODES,
    },
    {
        "id": "western_canada",
        "name": "Western Canada",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": CANADA_WEST_CODES,
    },
    {
        "id": "eastern_canada",
        "name": "Eastern Canada",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": CANADA_EAST_CODES,
    },
    {
        "id": "northern_canada",
        "name": "Northern Canada",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": CANADA_NORTH_CODES,
    },
    {
        "id": "canada",
        "name": "Canada",
        "type": "macro_region",
        "discount_percent": 30,
        "adm1_codes": CANADA_REGION_CODES,
    },
    {
        "id": "north_america",
        "name": "North America",
        "type": "continent",
        "discount_percent": 50,
        "adm0_codes": NORTH_AMERICA_COUNTRY_CODES,
        "adm1_codes": (*USA_STATE_CODES, *CANADA_REGION_CODES),
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


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tile_key(x_value: int, y_value: int, z_value: int, d_value: int) -> str:
    return f"x{x_value:03d}_y{y_value:03d}_z{z_value:03d}_d{d_value:03d}"


def paid_d_levels_for_z(z_value: int) -> tuple[int, ...]:
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


def region_tiles_for_geometry(geometry, min_intersection_area: float = 1e-10) -> list[str]:
    if geometry is None or geometry.is_empty:
        return []
    keys = []
    seen = set()
    polygon_parts = list(_iter_polygon_geometries(geometry))
    if not polygon_parts:
        return []
    for z_value in PAID_Z_LEVELS:
        d_levels = paid_d_levels_for_z(z_value)
        if not d_levels:
            continue
        for polygon_part in polygon_parts:
            if polygon_part is None or polygon_part.is_empty:
                continue
            prepared_geometry = prep(polygon_part)
            start_x, end_x, start_y, end_y = candidate_ranges(polygon_part.bounds, z_value)
            for x_value in range(start_x, end_x + 1, z_value):
                if x_value < 0 or x_value > 359:
                    continue
                for y_value in range(start_y, end_y + 1, z_value):
                    if y_value < 0 or y_value > 179:
                        continue
                    poly = tile_polygon(x_value, y_value, z_value)
                    if not prepared_geometry.intersects(poly):
                        continue
                    if polygon_part.intersection(poly).area <= min_intersection_area:
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
    countries["GID_1"] = ""
    countries["NAME_1"] = ""
    return countries


def read_adm1(gpkg_path: Path):
    regions = gpd.read_file(gpkg_path, layer="ADM_1", columns=["GID_0", "COUNTRY", "GID_1", "NAME_1", "geometry"])
    regions["GID_0"] = regions["GID_0"].astype(str).str.upper()
    regions["GID_1"] = regions["GID_1"].astype(str).str.upper()
    return regions


def selected_for_codes(countries, codes: tuple[str, ...] | list[str], clip_bbox=None):
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


def selected_for_adm1_codes(regions, codes: tuple[str, ...] | list[str], clip_bbox=None):
    safe_codes = tuple(str(code).strip().upper() for code in codes if str(code).strip())
    if not safe_codes:
        raise ValueError("No ADM_1 region codes supplied")
    selected = regions[regions["GID_1"].isin(safe_codes)].copy()
    missing = sorted(set(safe_codes) - set(selected["GID_1"].astype(str)))
    if missing:
        raise ValueError(f"Missing ADM_1 code(s): {', '.join(missing)}")
    if clip_bbox:
        clip = box(*clip_bbox)
        selected["geometry"] = selected.geometry.intersection(clip)
        selected = selected[~selected.geometry.is_empty].copy()
    if selected.empty:
        raise ValueError(f"ADM_1 code(s) clipped to empty geometry: {', '.join(safe_codes)}")
    return selected.sort_values(["COUNTRY", "NAME_1"]).reset_index(drop=True)


def selected_for_spec(layers: dict[str, object], spec: dict):
    parts = []
    if spec.get("adm0_codes"):
        parts.append(selected_for_codes(layers["adm0"], spec["adm0_codes"], spec.get("clip_bbox")))
    if spec.get("adm1_codes"):
        parts.append(selected_for_adm1_codes(layers["adm1"], spec["adm1_codes"], spec.get("clip_bbox")))
    if not parts:
        raise ValueError("No ADM_0 or ADM_1 codes supplied")
    if len(parts) == 1:
        return parts[0]
    combined = pd.concat(parts, ignore_index=True, sort=False)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs=getattr(parts[0], "crs", None))


def spec_membership_codes(spec: dict) -> tuple[str, ...]:
    adm0_codes = tuple(str(code).strip().upper() for code in spec.get("adm0_codes") or [] if str(code).strip())
    adm1_codes = tuple(str(code).strip().upper() for code in spec.get("adm1_codes") or [] if str(code).strip())
    return adm0_codes + adm1_codes


def payload_membership_codes(payload: dict) -> list[str]:
    codes = payload.get("membership_codes") or payload.get("adm1_codes") or payload.get("adm0_codes") or []
    return [str(code).strip().upper() for code in codes if str(code).strip()]


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
    if "GID_1" in selected.columns and "NAME_1" in selected.columns:
        columns = ["GID_0", "COUNTRY", "GID_1", "NAME_1"]
        for row in selected[columns].drop_duplicates().sort_values(["COUNTRY", "NAME_1"]).itertuples(index=False):
            region_name = clean_text(row.NAME_1)
            country_name = clean_text(row.COUNTRY)
            gid0 = clean_text(row.GID_0)
            gid1 = clean_text(row.GID_1)
            if region_name:
                records.append({
                    "GID_0": gid0,
                    "COUNTRY": country_name,
                    "GID_1": gid1,
                    "NAME_1": region_name,
                    "name": region_name,
                    "country": country_name,
                })
            elif country_name:
                records.append({"GID_0": gid0, "COUNTRY": country_name, "name": country_name})
        return records
    for row in selected[["GID_0", "COUNTRY"]].drop_duplicates().sort_values("COUNTRY").itertuples(index=False):
        country_name = clean_text(row.COUNTRY)
        if country_name:
            records.append({"GID_0": clean_text(row.GID_0), "COUNTRY": country_name, "name": country_name})
    return records


def country_outlines_for_web(selected, simplify_tolerance: float = 0.005, min_polygon_area: float = 0.001) -> list[dict]:
    outlines = []
    sort_columns = ["COUNTRY"]
    if "NAME_1" in selected.columns:
        sort_columns.append("NAME_1")
    for row in selected.sort_values(sort_columns).itertuples(index=False):
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
        outline_id = clean_text(getattr(row, "GID_1", "")) or clean_text(getattr(row, "GID_0", ""))
        outline_name = clean_text(getattr(row, "NAME_1", "")) or clean_text(getattr(row, "COUNTRY", ""))
        outlines.append({"id": outline_id, "name": outline_name, "polygons": polygons})
    return outlines


def payload_from_selected(
    *,
    product_id: str,
    name: str,
    product_type: str,
    discount_percent: int,
    selected,
    adm0_codes: tuple[str, ...] | list[str] = (),
    adm1_codes: tuple[str, ...] | list[str] = (),
    clip_bbox=None,
    merge_scope: str = "",
    auto_merge: bool = False,
    member_product_ids: list[str] | None = None,
    source_note: str = "GADM 4.10 ADM_0 polygon intersection",
    tile_keys_override: list[str] | None = None,
) -> dict:
    geometry = union_geometry(selected)
    tile_keys = sorted(set(tile_keys_override)) if tile_keys_override is not None else region_tiles_for_geometry(geometry)
    bounds = [float(value) for value in selected.total_bounds]
    safe_adm0_codes = sorted(set(str(code).upper() for code in adm0_codes if str(code).strip()))
    if not safe_adm0_codes and "GID_0" in selected.columns:
        safe_adm0_codes = sorted(set(str(value).upper() for value in selected["GID_0"].astype(str)))
    safe_adm1_codes = sorted(set(str(code).upper() for code in adm1_codes if str(code).strip()))
    membership_codes = safe_adm1_codes or safe_adm0_codes
    return {
        "id": product_id,
        "name": name,
        "type": product_type,
        "discount_percent": int(discount_percent),
        "catalog_version": CATALOG_VERSION,
        "source": source_note,
        "adm0_codes": safe_adm0_codes,
        "adm1_codes": safe_adm1_codes,
        "membership_codes": membership_codes,
        "clip_bbox": list(clip_bbox or []),
        "merge_scope": str(merge_scope or ""),
        "auto_merge": bool(auto_merge),
        "countries": country_records(selected),
        "country_product_ids": list(member_product_ids or []),
        "tile_count": len(tile_keys),
        "counts_by_z": counts_by_z(tile_keys),
        "bounds": bounds,
        "bbox": bounds,
        "outlines": country_outlines_for_web(selected),
        "tile_keys": tile_keys,
    }


def product_name_from_selected(selected, fallback: str) -> str:
    records = country_records(selected)
    if len(records) == 1:
        return records[0].get("NAME_1") or records[0].get("COUNTRY") or fallback
    return fallback


def build_local_payloads(layers: dict[str, object]) -> list[dict]:
    payloads = []
    specs = list(LOCAL_PRODUCT_SPECS)
    for index, spec in enumerate(specs, start=1):
        adm0_codes = tuple(spec.get("adm0_codes") or ())
        adm1_codes = tuple(spec.get("adm1_codes") or ())
        codes = spec_membership_codes(spec)
        label = str(spec.get("name") or ",".join(codes))
        print(f"Building local product {index}/{len(specs)}: {label}", file=sys.stderr, flush=True)
        selected = selected_for_spec(layers, spec)
        name = str(spec.get("name") or "").strip() or product_name_from_selected(selected, codes[0])
        product_id = str(spec.get("id") or "").strip() or slugify(name)
        payloads.append(
            payload_from_selected(
                product_id=product_id,
                name=name,
                product_type="country",
                discount_percent=int(spec.get("discount_percent", 20)),
                selected=selected,
                adm0_codes=adm0_codes,
                adm1_codes=adm1_codes,
                clip_bbox=spec.get("clip_bbox"),
                merge_scope=str(spec.get("merge_scope") or ""),
                auto_merge=bool(spec.get("auto_merge", False)),
                source_note=str(spec.get("source_note") or "GADM 4.10 ADM_0 polygon intersection"),
            )
        )
    return payloads


def merge_reason(a: dict, b: dict) -> str:
    if not (a.get("auto_merge") and b.get("auto_merge")):
        return ""
    if str(a.get("merge_scope") or "") != str(b.get("merge_scope") or ""):
        return ""
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


def merge_local_payloads(local_payloads: list[dict], layers: dict[str, object]) -> tuple[list[dict], list[dict], dict[str, str], dict[str, dict]]:
    edges = []
    pair_report = []
    for left in range(len(local_payloads)):
        for right in range(left + 1, len(local_payloads)):
            reason = merge_reason(local_payloads[left], local_payloads[right])
            if not reason:
                continue
            edges.append((left, right))
            pair_report.append({
                "left": local_payloads[left]["id"],
                "right": local_payloads[right]["id"],
                "reason": reason,
                "left_tile_count": local_payloads[left]["tile_count"],
                "right_tile_count": local_payloads[right]["tile_count"],
            })
    components = connected_components(len(local_payloads), edges)
    merged = []
    code_to_product_id = {}
    code_to_payload = {}
    for component in components:
        component_payloads = [local_payloads[index] for index in sorted(component, key=lambda idx: local_payloads[idx]["name"])]
        codes = sorted({code for payload in component_payloads for code in payload_membership_codes(payload)})
        adm0_codes = sorted({code for payload in component_payloads for code in payload.get("adm0_codes", [])})
        adm1_codes = sorted({code for payload in component_payloads for code in payload.get("adm1_codes", [])})
        names = sorted({
            record.get("NAME_1") or record.get("COUNTRY")
            for payload in component_payloads
            for record in payload.get("countries", [])
            if record.get("NAME_1") or record.get("COUNTRY")
        })
        clip_bbox = component_payloads[0].get("clip_bbox") or None
        merge_scope = str(component_payloads[0].get("merge_scope") or "")
        if len(component_payloads) == 1:
            payload = dict(component_payloads[0])
            payload["country_product_ids"] = [payload["id"]]
        else:
            if adm1_codes:
                selected = selected_for_adm1_codes(layers["adm1"], adm1_codes, clip_bbox)
            else:
                selected = selected_for_codes(layers["adm0"], adm0_codes, clip_bbox)
            product_id, name = merged_product_identity(codes, names)
            merged_tile_keys = sorted({key for source in component_payloads for key in source.get("tile_keys", [])})
            payload = payload_from_selected(
                product_id=product_id,
                name=name,
                product_type="country",
                discount_percent=20,
                selected=selected,
                adm0_codes=adm0_codes,
                adm1_codes=adm1_codes,
                clip_bbox=clip_bbox,
                merge_scope=merge_scope,
                auto_merge=False,
                member_product_ids=[payload["id"] for payload in component_payloads],
                source_note="GADM 4.10 ADM_0 polygon intersection; merged by paid tile-set overlap",
                tile_keys_override=merged_tile_keys,
            )
            payload["merged_from"] = [{"id": source["id"], "name": source["name"], "tile_count": source["tile_count"]} for source in component_payloads]
        for code in codes:
            code_to_product_id[code] = payload["id"]
            code_to_payload[code] = payload
        merged.append(payload)
    merged.sort(key=lambda payload: (payload["name"], payload["id"]))
    return merged, pair_report, code_to_product_id, code_to_payload


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


def tile_keys_for_codes(codes: tuple[str, ...] | list[str], code_to_payload: dict[str, dict]) -> list[str]:
    return sorted({key for code in codes for key in (code_to_payload.get(str(code).upper(), {}).get("tile_keys") or [])})


def spec_codes_for_macro(pack: dict) -> tuple[str, ...]:
    return spec_membership_codes(pack)


def selected_for_macro(layers: dict[str, object], pack: dict):
    return selected_for_spec(layers, pack)


def build_macro_payloads(layers: dict[str, object], code_to_product_id: dict[str, str], code_to_payload: dict[str, dict]) -> list[dict]:
    payloads = []
    for index, pack in enumerate(MACRO_PACKS, start=1):
        print(f"Building macro {index}/{len(MACRO_PACKS)}: {pack['id']}", file=sys.stderr, flush=True)
        codes = spec_codes_for_macro(pack)
        selected = selected_for_macro(layers, pack)
        tile_keys = tile_keys_for_codes(codes, code_to_payload)
        payloads.append(
            payload_from_selected(
                product_id=pack["id"],
                name=pack["name"],
                product_type=pack["type"],
                discount_percent=pack["discount_percent"],
                selected=selected,
                adm0_codes=tuple(pack.get("adm0_codes") or ()),
                adm1_codes=tuple(pack.get("adm1_codes") or ()),
                clip_bbox=pack.get("clip_bbox"),
                member_product_ids=product_ids_for_codes(codes, code_to_product_id),
                tile_keys_override=tile_keys,
            )
        )
    return payloads


def build_catalog(gpkg_path: Path) -> dict:
    layers = {
        "adm0": read_adm0(gpkg_path),
        "adm1": read_adm1(gpkg_path),
    }
    raw_local = build_local_payloads(layers)
    local_products, merge_report, code_to_product_id, code_to_payload = merge_local_payloads(raw_local, layers)
    macro_products = build_macro_payloads(layers, code_to_product_id, code_to_payload)
    products = local_products + macro_products
    products.sort(key=lambda payload: (0 if payload["type"] == "country" else 1 if payload["type"] == "macro_region" else 2, payload["name"]))
    return {
        "catalog_version": CATALOG_VERSION,
        "source": "GADM 4.10 ADM_0 polygon intersection clipped per product region",
        "paid_z_levels": list(PAID_Z_LEVELS),
        "free_d_threshold": FREE_D_THRESHOLD,
        "merge_difference_ratio": MERGE_DIFFERENCE_RATIO,
        "small_country_auto_merge_tile_limit": SMALL_COUNTRY_AUTO_MERGE_TILE_LIMIT,
        "excluded_europe_microstates": EXCLUDED_EUROPE_MICROSTATES,
        "excluded_europe_transcontinental": EXCLUDED_EUROPE_TRANSCONTINENTAL,
        "raw_local_product_count": len(raw_local),
        "local_product_count": len(local_products),
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
        "tile_count": int(payload.get("tile_count") or 0),
        "bbox": payload.get("bbox") or payload.get("bounds") or [],
    }
    if payload.get("country_product_ids"):
        result["countries"] = payload["country_product_ids"]
    if payload.get("adm0_codes"):
        result["adm0_codes"] = payload["adm0_codes"]
    if payload.get("adm1_codes"):
        result["adm1_codes"] = payload["adm1_codes"]
    return result


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized_outline_catalog(payload), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def normalized_outline_catalog(catalog: dict) -> dict:
    payload = dict(catalog)
    outlines = {}
    products = []
    for product in catalog.get("products") or []:
        product_payload = dict(product)
        refs = []
        for outline in product_payload.pop("outlines", []) or []:
            outline_id = str(outline.get("id") or "").strip()
            if not outline_id:
                continue
            outlines.setdefault(outline_id, outline)
            refs.append(outline_id)
        product_payload["outline_refs"] = refs
        products.append(product_payload)
    payload["products"] = products
    payload["outlines"] = outlines
    return payload


def write_js(path: Path, catalog: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    pack_payloads = catalog.get("products") or []
    outline_payload = {}
    outline_refs_by_product = {}
    for payload in pack_payloads:
        refs = []
        for outline in payload.get("outlines", []) or []:
            outline_id = str(outline.get("id") or "").strip()
            if not outline_id:
                continue
            outline_payload.setdefault(outline_id, outline)
            refs.append(outline_id)
        outline_refs_by_product[payload["id"]] = refs
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
            "outline_refs": outline_refs_by_product.get(payload["id"], []),
            "adm0_codes": payload.get("adm0_codes", []),
            "adm1_codes": payload.get("adm1_codes", []),
            "merged_from": payload.get("merged_from", []),
            "counts_by_z": payload.get("counts_by_z", {}),
        }
    lines.append("")
    lines.append(f"export const GENERATED_REGION_PACK_DETAILS = {json.dumps(detail_payload, ensure_ascii=True, separators=(',', ':'))};")
    lines.append("")
    lines.append(f"export const GENERATED_REGION_PACK_OUTLINES = {json.dumps(outline_payload, ensure_ascii=True, separators=(',', ':'))};")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_png(path: Path, catalog: dict, product_id: str = "south_america"):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    product = next((entry for entry in catalog.get("products", []) if entry.get("id") == product_id), None)
    if not product:
        return
    gpkg_path = Path(catalog.get("gpkg_path") or DEFAULT_GPKG)
    if product.get("adm1_codes"):
        selected = selected_for_adm1_codes(read_adm1(gpkg_path), product.get("adm1_codes") or [], product.get("clip_bbox") or None)
    else:
        selected = selected_for_codes(read_adm0(gpkg_path), product.get("adm0_codes") or [], product.get("clip_bbox") or None)
    tile_keys = product.get("tile_keys") or []
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(13, 8), dpi=160)
    selected.boundary.plot(ax=ax, color="#111111", linewidth=0.8)
    selected.plot(ax=ax, color="#d9e8ff", edgecolor="#111111", linewidth=0.25, alpha=0.65)
    z001 = [key for key in tile_keys if "_z001_" in key]
    for key in z001:
        x_value = int(key[1:4])
        y_value = int(key[6:9])
        rect = Rectangle((x_value - 180.0, y_value - 90.0), 1.0, 1.0, fill=False, edgecolor="#ff3b30", linewidth=0.35, alpha=0.75)
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
        "local_product_count": sum(1 for entry in products if entry.get("type") == "country"),
        "macro_region_count": sum(1 for entry in products if entry.get("type") == "macro_region"),
        "continent_count": sum(1 for entry in products if entry.get("type") == "continent"),
        "merged_product_count": len(merged),
        "merged_products": [{"id": entry.get("id"), "name": entry.get("name"), "countries": [source.get("name") for source in entry.get("merged_from") or []], "tile_count": entry.get("tile_count")} for entry in merged],
        "products": [{"id": entry.get("id"), "name": entry.get("name"), "type": entry.get("type"), "tile_count": entry.get("tile_count"), "counts_by_z": entry.get("counts_by_z")} for entry in products],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpkg", type=Path, default=DEFAULT_GPKG)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--js-output", type=Path, default=DEFAULT_JS)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG)
    parser.add_argument("--png-product", default="australia")
    parser.add_argument("--skip-png", action="store_true")
    args = parser.parse_args()

    catalog = build_catalog(args.gpkg)
    catalog["gpkg_path"] = str(args.gpkg)
    write_json(args.json_output, catalog)
    write_js(args.js_output, catalog)
    if not args.skip_png:
        write_png(args.png_output, catalog, args.png_product)
    summary = summarize_catalog(catalog)
    summary.update({"json_output": str(args.json_output), "js_output": str(args.js_output), "png_output": "" if args.skip_png else str(args.png_output)})
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
