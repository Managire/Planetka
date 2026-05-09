#!/usr/bin/env python3
"""Build static high-resolution preview backgrounds for Full Quality data-pack maps.

The web maps are static product views. This tool renders their photographic
backgrounds offline from the local S2 tile pyramid, so the Worker only serves
prebuilt JPEGs and never stitches imagery at request time.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import OpenImageIO as oiio
from PIL import Image


TILE_KEY_RE = re.compile(r"x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})", re.IGNORECASE)
DEFAULT_S2_DIR = Path("/Volumes/SSDA/Planetka Assets/S2")
DEFAULT_ASSETS_DIR = Path("/tmp/planetka_region_pack_map_assets")
DEFAULT_OUT_DIR = Path("/tmp/planetka_region_pack_preview_backgrounds")


@dataclass(frozen=True)
class TileInfo:
    key: str
    x: int
    y: int
    z: int
    d: int
    path: Path
    width: int
    height: int

    @property
    def lon_min(self) -> float:
        return float(self.x - 180)

    @property
    def lon_max(self) -> float:
        return float(self.x - 180 + self.z)

    @property
    def lat_min(self) -> float:
        return float(self.y - 90)

    @property
    def lat_max(self) -> float:
        return float(self.y - 90 + self.z)

    @property
    def ppd_x(self) -> float:
        return self.width / max(1.0, float(self.z))

    @property
    def ppd_y(self) -> float:
        return self.height / max(1.0, float(self.z))


class ImageInfoCache:
    def __init__(self) -> None:
        self._cache: dict[Path, tuple[int, int]] = {}

    def dimensions(self, path: Path) -> tuple[int, int]:
        cached = self._cache.get(path)
        if cached:
            return cached
        inp = oiio.ImageInput.open(str(path))
        if inp is None:
            raise RuntimeError(f"failed to open image: {path}")
        try:
            spec = inp.spec()
            dims = (int(spec.width), int(spec.height))
        finally:
            inp.close()
        self._cache[path] = dims
        return dims


def parse_tile_key(value: str) -> tuple[int, int, int, int] | None:
    match = TILE_KEY_RE.search(str(value or ""))
    if not match:
        return None
    return tuple(int(match.group(i)) for i in range(1, 5))


def frame_for_bounds(bounds: dict[str, float], width: int = 1000, min_height: int = 320, max_height: int = 820, pad: int = 20) -> dict[str, float]:
    min_lon = float(bounds["min_lon"])
    min_lat = float(bounds["min_lat"])
    max_lon = float(bounds["max_lon"])
    max_lat = float(bounds["max_lat"])
    lon_span = max(1e-6, max_lon - min_lon)
    lat_span = max(1e-6, max_lat - min_lat)
    inner_w = max(1, width - pad * 2)
    natural_h = round(lat_span * (inner_w / lon_span)) + pad * 2
    height = max(min_height, min(max_height, natural_h))
    inner_h = max(1, height - pad * 2)
    scale = min(inner_w / lon_span, inner_h / lat_span)
    used_w = lon_span * scale
    used_h = lat_span * scale
    return {"used_w": used_w, "used_h": used_h, "height": height}


def target_size(bounds: dict[str, float], device_scale: float, max_side: int) -> tuple[int, int]:
    frame = frame_for_bounds(bounds)
    width = max(1, round(frame["used_w"] * device_scale))
    height = max(1, round(frame["used_h"] * device_scale))
    largest = max(width, height)
    if largest > max_side:
        ratio = max_side / largest
        width = max(1, round(width * ratio))
        height = max(1, round(height * ratio))
    return width, height


def normalize_bounds(raw: object) -> dict[str, float] | None:
    if isinstance(raw, dict):
        try:
            bounds = {
                "min_lon": float(raw["min_lon"]),
                "min_lat": float(raw["min_lat"]),
                "max_lon": float(raw["max_lon"]),
                "max_lat": float(raw["max_lat"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    elif isinstance(raw, list) and len(raw) >= 4:
        try:
            bounds = {
                "min_lon": float(raw[0]),
                "min_lat": float(raw[1]),
                "max_lon": float(raw[2]),
                "max_lat": float(raw[3]),
            }
        except (TypeError, ValueError):
            return None
    else:
        return None
    if bounds["max_lon"] <= bounds["min_lon"] or bounds["max_lat"] <= bounds["min_lat"]:
        return None
    return bounds


def intersects(tile: TileInfo, bounds: dict[str, float]) -> bool:
    return (
        tile.lon_max > bounds["min_lon"]
        and tile.lon_min < bounds["max_lon"]
        and tile.lat_max > bounds["min_lat"]
        and tile.lat_min < bounds["max_lat"]
    )


def source_pixel_area(tile: TileInfo, bounds: dict[str, float]) -> int:
    lon_min = max(bounds["min_lon"], tile.lon_min)
    lon_max = min(bounds["max_lon"], tile.lon_max)
    lat_min = max(bounds["min_lat"], tile.lat_min)
    lat_max = min(bounds["max_lat"], tile.lat_max)
    if lon_max <= lon_min or lat_max <= lat_min:
        return 0
    px = max(1, math.ceil((lon_max - lon_min) / tile.z * tile.width))
    py = max(1, math.ceil((lat_max - lat_min) / tile.z * tile.height))
    return px * py


def tile_info_for_row(row: dict[str, object], s2_dir: Path, cache: ImageInfoCache) -> TileInfo | None:
    parsed = parse_tile_key(str(row.get("tile_key") or ""))
    if not parsed:
        return None
    x, y, z, d = parsed
    key = f"x{x:03d}_y{y:03d}_z{z:03d}_d{d:03d}"
    path = s2_dir / f"S2_{key}.exr"
    if not path.exists():
        return None
    width, height = cache.dimensions(path)
    return TileInfo(key=key, x=x, y=y, z=z, d=d, path=path, width=width, height=height)


def choose_tiles(asset: dict[str, object], bounds: dict[str, float], out_w: int, out_h: int, s2_dir: Path, cache: ImageInfoCache) -> tuple[list[TileInfo], str]:
    lon_span = max(1e-6, bounds["max_lon"] - bounds["min_lon"])
    lat_span = max(1e-6, bounds["max_lat"] - bounds["min_lat"])
    required_ppd_x = out_w / lon_span
    required_ppd_y = out_h / lat_span

    groups: dict[tuple[int, int], list[TileInfo]] = {}
    for row in asset.get("tiles") or []:
        if not isinstance(row, dict):
            continue
        info = tile_info_for_row(row, s2_dir, cache)
        if not info or info.d <= 0 or not intersects(info, bounds):
            continue
        groups.setdefault((info.z, info.d), []).append(info)

    if not groups:
        raise RuntimeError("no source S2 tiles available")

    candidates: list[tuple[int, int, float, int, list[TileInfo]]] = []
    fallback: tuple[int, int, float, int, list[TileInfo]] | None = None
    for (z, d), tiles in groups.items():
        min_ratio = min(
            min(tile.ppd_x / required_ppd_x, tile.ppd_y / required_ppd_y)
            for tile in tiles
        )
        area = sum(source_pixel_area(tile, bounds) for tile in tiles)
        entry = (d, z, min_ratio, area, tiles)
        if min_ratio >= 1.0:
            candidates.append(entry)
        if fallback is None or min_ratio > fallback[2] or (math.isclose(min_ratio, fallback[2]) and area < fallback[3]):
            fallback = entry

    if candidates:
        # Prefer the cheapest source read among groups that do not upscale.
        chosen = min(candidates, key=lambda item: (item[3], -item[0], item[1]))
        reason = "no_upscale"
    else:
        chosen = fallback
        reason = f"best_available_ratio_{chosen[2]:.3f}" if chosen else "missing"
    if not chosen:
        raise RuntimeError("no usable S2 tile group")
    return chosen[4], reason


def read_tile_crop(tile: TileInfo, bounds: dict[str, float]) -> tuple[Image.Image, tuple[int, int, int, int]] | None:
    lon_min = max(bounds["min_lon"], tile.lon_min)
    lon_max = min(bounds["max_lon"], tile.lon_max)
    lat_min = max(bounds["min_lat"], tile.lat_min)
    lat_max = min(bounds["max_lat"], tile.lat_max)
    if lon_max <= lon_min or lat_max <= lat_min:
        return None

    px0 = max(0, min(tile.width - 1, math.floor((lon_min - tile.lon_min) / tile.z * tile.width)))
    px1 = max(px0 + 1, min(tile.width, math.ceil((lon_max - tile.lon_min) / tile.z * tile.width)))
    py0 = max(0, min(tile.height - 1, math.floor((tile.lat_max - lat_max) / tile.z * tile.height)))
    py1 = max(py0 + 1, min(tile.height, math.ceil((tile.lat_max - lat_min) / tile.z * tile.height)))

    inp = oiio.ImageInput.open(str(tile.path))
    if inp is None:
        raise RuntimeError(f"failed to open tile image: {tile.path}")
    try:
        arr = np.asarray(inp.read_scanlines(py0, py1, 0, 0, 3, oiio.FLOAT), dtype=np.float32)
    finally:
        inp.close()
    arr = arr[:, px0:px1, :3]
    if arr.size == 0:
        return None
    arr = np.clip(arr, 0.0, 1.0)
    arr = np.power(arr, 1.0 / 2.2)
    arr8 = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(arr8, mode="RGB"), (lon_min, lat_min, lon_max, lat_max)


def output_rect(bounds: dict[str, float], out_w: int, out_h: int, crop_bounds: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    lon_min, lat_min, lon_max, lat_max = crop_bounds
    lon_span = max(1e-6, bounds["max_lon"] - bounds["min_lon"])
    lat_span = max(1e-6, bounds["max_lat"] - bounds["min_lat"])
    x0 = round((lon_min - bounds["min_lon"]) / lon_span * out_w)
    x1 = round((lon_max - bounds["min_lon"]) / lon_span * out_w)
    y0 = round((bounds["max_lat"] - lat_max) / lat_span * out_h)
    y1 = round((bounds["max_lat"] - lat_min) / lat_span * out_h)
    x0 = max(0, min(out_w - 1, x0))
    y0 = max(0, min(out_h - 1, y0))
    x1 = max(x0 + 1, min(out_w, x1))
    y1 = max(y0 + 1, min(out_h, y1))
    return x0, y0, x1, y1


def render_background(asset_path: Path, out_path: Path, s2_dir: Path, cache: ImageInfoCache, device_scale: float, max_side: int, quality: int) -> dict[str, object]:
    asset = json.loads(asset_path.read_text())
    product = asset.get("region_pack") if isinstance(asset.get("region_pack"), dict) else {}
    product_id = str(product.get("id") or asset_path.stem)
    bounds = normalize_bounds(asset.get("bounds"))
    if not bounds:
        raise RuntimeError("missing or invalid bounds")
    out_w, out_h = target_size(bounds, device_scale=device_scale, max_side=max_side)
    tiles, reason = choose_tiles(asset, bounds, out_w, out_h, s2_dir, cache)
    canvas = Image.new("RGB", (out_w, out_h), (13, 17, 24))
    pasted = 0
    for tile in tiles:
        crop = read_tile_crop(tile, bounds)
        if not crop:
            continue
        image, crop_bounds = crop
        x0, y0, x1, y1 = output_rect(bounds, out_w, out_h, crop_bounds)
        dest_size = (x1 - x0, y1 - y0)
        if image.size != dest_size:
            image = image.resize(dest_size, Image.Resampling.LANCZOS)
        canvas.paste(image, (x0, y0))
        pasted += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=quality, optimize=True, progressive=True)
    min_ratio = min(
        min(tile.ppd_x / (out_w / max(1e-6, bounds["max_lon"] - bounds["min_lon"])),
            tile.ppd_y / (out_h / max(1e-6, bounds["max_lat"] - bounds["min_lat"])))
        for tile in tiles
    )
    display_ratio = min_ratio * max(0.1, device_scale)
    return {
        "id": product_id,
        "width": out_w,
        "height": out_h,
        "source_tiles": len(tiles),
        "pasted_tiles": pasted,
        "source_z": sorted({tile.z for tile in tiles}),
        "source_d": sorted({tile.d for tile in tiles}),
        "min_source_to_output_ratio": round(min_ratio, 4),
        "min_source_to_display_ratio": round(display_ratio, 4),
        "choice": reason,
        "bytes": out_path.stat().st_size,
        "path": str(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR, help="Directory containing generated region-pack JSON map assets")
    parser.add_argument("--s2-dir", type=Path, default=DEFAULT_S2_DIR, help="Directory containing local S2_*.exr source tiles")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for JPEG backgrounds")
    parser.add_argument("--device-scale", type=float, default=2.0, help="CSS pixel multiplier for generated backgrounds")
    parser.add_argument("--max-side", type=int, default=2400, help="Maximum generated image side in pixels")
    parser.add_argument("--quality", type=int, default=86, help="JPEG quality")
    parser.add_argument("--only", action="append", default=[], help="Only render selected product id; may be repeated")
    parser.add_argument("--limit", type=int, default=0, help="Render at most this many products")
    parser.add_argument("--manifest", type=Path, default=None, help="Optional manifest JSON path")
    args = parser.parse_args()

    assets_dir = args.assets_dir
    if not assets_dir.exists():
        raise SystemExit(f"assets dir does not exist: {assets_dir}")
    if not args.s2_dir.exists():
        raise SystemExit(f"S2 dir does not exist: {args.s2_dir}")
    args.out.mkdir(parents=True, exist_ok=True)

    selected = {item.strip().lower() for item in args.only if item.strip()}
    asset_paths = sorted(path for path in assets_dir.glob("*.json") if path.name != "catalog.json")
    if selected:
        asset_paths = [path for path in asset_paths if path.stem.lower() in selected]
    if args.limit and args.limit > 0:
        asset_paths = asset_paths[: args.limit]

    cache = ImageInfoCache()
    manifest: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for index, asset_path in enumerate(asset_paths, start=1):
        out_path = args.out / f"{asset_path.stem}.jpg"
        try:
            row = render_background(asset_path, out_path, args.s2_dir, cache, args.device_scale, args.max_side, args.quality)
            manifest.append(row)
            print(f"[{index}/{len(asset_paths)}] {row['id']}: {row['width']}x{row['height']} z={row['source_z']} d={row['source_d']} output_ratio={row['min_source_to_output_ratio']} display_ratio={row['min_source_to_display_ratio']} bytes={row['bytes']}")
        except Exception as error:  # noqa: BLE001 - CLI should keep rendering other products.
            failures.append({"id": asset_path.stem, "error": str(error)})
            print(f"[{index}/{len(asset_paths)}] {asset_path.stem}: FAILED {error}", file=sys.stderr)

    output = {
        "ok": not failures,
        "count": len(manifest),
        "failed": len(failures),
        "total_bytes": sum(int(row.get("bytes") or 0) for row in manifest),
        "backgrounds": manifest,
        "failures": failures,
    }
    manifest_path = args.manifest or args.out / "manifest.json"
    manifest_path.write_text(json.dumps(output, indent=2))
    print(json.dumps({k: output[k] for k in ("ok", "count", "failed", "total_bytes")}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
