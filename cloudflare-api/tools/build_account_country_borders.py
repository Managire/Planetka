#!/usr/bin/env python3
"""Build the lightweight world country-border overlay for account pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


def _group_key(outline_id: str) -> str:
    safe_id = str(outline_id or "").strip()
    if "." in safe_id:
        return safe_id.split(".", 1)[0]
    return safe_id


def _clean_geometry(geometry):
    if geometry.is_empty or geometry.is_valid:
        return geometry
    try:
        return geometry.buffer(0)
    except GEOSException:
        return geometry


def _polygon_from_ring(ring):
    if not isinstance(ring, list) or len(ring) < 4:
        return None
    coords = []
    for point in ring:
        if not isinstance(point, list) or len(point) < 2:
            continue
        try:
            coords.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if len(coords) < 4:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    try:
        polygon = _clean_geometry(Polygon(coords))
    except Exception:
        return None
    if polygon.is_empty:
        return None
    return polygon


def _iter_polygons(geometry):
    geometry = _clean_geometry(geometry)
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        polygons = []
        for child in geometry.geoms:
            polygons.extend(_iter_polygons(child))
        return polygons
    return []


def _ring_from_polygon(polygon: Polygon, precision: int):
    coords = [
        [round(float(lon), precision), round(float(lat), precision)]
        for lon, lat in polygon.exterior.coords
    ]
    return coords if len(coords) >= 4 else []


def build_country_borders(source_catalog: Path, tolerance: float, precision: int) -> dict:
    data = json.loads(source_catalog.read_text())
    raw_outlines = list((data.get("outlines") or {}).values())
    groups: dict[str, list] = {}
    names: dict[str, str] = {}
    for outline in raw_outlines:
        if not isinstance(outline, dict):
            continue
        group_key = _group_key(str(outline.get("id") or ""))
        if not group_key:
            continue
        names.setdefault(group_key, str(outline.get("name") or group_key).strip() or group_key)
        for ring in outline.get("polygons") or []:
            polygon = _polygon_from_ring(ring)
            if polygon is not None:
                groups.setdefault(group_key, []).append(polygon)

    outlines = []
    for group_key, polygons in sorted(groups.items()):
        if not polygons:
            continue
        try:
            geometry = _clean_geometry(unary_union(polygons))
            geometry = _clean_geometry(geometry.simplify(tolerance, preserve_topology=True))
        except Exception:
            geometry = _clean_geometry(unary_union([
                polygon.simplify(tolerance, preserve_topology=False)
                for polygon in polygons
            ]))
        rings = [
            ring
            for polygon in _iter_polygons(geometry)
            for ring in [_ring_from_polygon(polygon, precision)]
            if ring
        ]
        if rings:
            outlines.append({
                "id": group_key,
                "name": names.get(group_key, group_key),
                "polygons": rings,
            })

    return {
        "ok": True,
        "catalog_version": data.get("catalog_version") or "gadm_regions_v8",
        "asset_type": "account_country_borders",
        "projection": "equirectangular_lonlat",
        "simplify_tolerance_degrees": tolerance,
        "outlines": outlines,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="Resources/Region Packs/region_packs_gadm.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--tolerance", type=float, default=0.5)
    parser.add_argument("--precision", type=int, default=2)
    args = parser.parse_args()

    payload = build_country_borders(Path(args.source), args.tolerance, args.precision)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")))
    points = sum(
        len(ring)
        for outline in payload["outlines"]
        for ring in outline.get("polygons", [])
        if isinstance(ring, list)
    )
    print(json.dumps({
        "ok": True,
        "output": str(output),
        "outlines": len(payload["outlines"]),
        "points": points,
        "bytes": output.stat().st_size,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
