#!/usr/bin/env python3
"""Dissolve child administrative outlines in generated region-pack map assets.

The source catalog stores many large products as ADM1 pieces, for example
Canada as provinces and territories. Drawing those pieces directly makes
internal borders look like random diagonals on the customer-facing map. This
post-process keeps separate country silhouettes, but dissolves administrative
pieces within each country before the JSON assets are uploaded to R2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


def _group_key(outline_id: str) -> str:
    safe_id = str(outline_id or "").strip()
    if "." in safe_id:
        return safe_id.split(".", 1)[0]
    return safe_id


def _clean_geometry(geometry):
    if geometry.is_empty:
        return geometry
    if geometry.is_valid:
        return geometry
    return geometry.buffer(0)


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


def dissolve_outlines(outlines, precision: int):
    groups = {}
    names = {}
    for outline in outlines if isinstance(outlines, list) else []:
        outline_id = str(outline.get("id") or "").strip()
        key = _group_key(outline_id)
        if not key:
            continue
        names.setdefault(key, str(outline.get("name") or key).strip() or key)
        for ring in outline.get("polygons") or []:
            polygon = _polygon_from_ring(ring)
            if polygon is None:
                continue
            groups.setdefault(key, []).append(polygon)

    dissolved = []
    for key, polygons in groups.items():
        if not polygons:
            continue
        union = _clean_geometry(unary_union(polygons))
        rings = [
            ring
            for polygon in _iter_polygons(union)
            for ring in [_ring_from_polygon(polygon, precision)]
            if ring
        ]
        if not rings:
            continue
        dissolved.append({
            "id": key,
            "name": names.get(key, key),
            "polygons": rings,
        })
    return dissolved


def process_asset(path: Path, precision: int, in_place: bool) -> tuple[bool, int, int]:
    data = json.loads(path.read_text())
    original = data.get("outlines") or []
    dissolved = dissolve_outlines(original, precision)
    original_points = sum(
        len(ring)
        for outline in original
        for ring in outline.get("polygons", [])
        if isinstance(ring, list)
    )
    dissolved_points = sum(
        len(ring)
        for outline in dissolved
        for ring in outline.get("polygons", [])
        if isinstance(ring, list)
    )
    if dissolved:
        data["outlines"] = dissolved
        if in_place:
            path.write_text(json.dumps(data, separators=(",", ":")))
    return bool(dissolved), original_points, dissolved_points


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-dir", required=True, help="Directory containing generated *.json map assets")
    parser.add_argument("--precision", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    assets_dir = Path(args.assets_dir)
    changed = 0
    total_original = 0
    total_dissolved = 0
    for path in sorted(assets_dir.glob("*.json")):
        if path.name == "catalog.json":
            continue
        ok, original_points, dissolved_points = process_asset(path, args.precision, not args.dry_run)
        if ok:
            changed += 1
            total_original += original_points
            total_dissolved += dissolved_points
    print(json.dumps({
        "ok": True,
        "assets_dir": str(assets_dir),
        "assets_processed": changed,
        "original_outline_points": total_original,
        "dissolved_outline_points": total_dissolved,
        "dry_run": bool(args.dry_run),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
