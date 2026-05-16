#!/usr/bin/env python3
"""Build static high-resolution preview backgrounds for Full Quality data-pack maps.

The web maps are static product views. This tool renders their photographic
backgrounds offline from the local tile pyramid, so the Worker only serves
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
DEFAULT_WT_DIR = Path("/Volumes/SSDA/Planetka Assets/WT")
DEFAULT_ASSETS_DIR = Path("/tmp/planetka_region_pack_map_assets")
DEFAULT_OUT_DIR = Path("/tmp/planetka_region_pack_preview_backgrounds")
DEFAULT_WT_WATER_RGB = (18, 64, 125)
DEFAULT_WT_LAND_RGB = (0, 0, 0)


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
        return float(self.x - 180 + self.lon_span)

    @property
    def lat_min(self) -> float:
        return float(self.y - 90)

    @property
    def lat_max(self) -> float:
        return float(self.y - 90 + self.lat_span)

    @property
    def lon_span(self) -> float:
        return float(self.z)

    @property
    def lat_span(self) -> float:
        # The global z360 source spans 360 degrees in longitude but only the
        # normal Earth latitude range, -90..90. Regular square tiles use z for
        # both axes.
        if self.x == 0 and self.y == 0 and self.z == 360:
            return 180.0
        return float(self.z)

    @property
    def ppd_x(self) -> float:
        return self.width / max(1.0, self.lon_span)

    @property
    def ppd_y(self) -> float:
        return self.height / max(1.0, self.lat_span)


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


class SourceTileIndex:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], list[tuple[Path, int, int, int, int]]] = {}

    def paths(self, source_dir: Path, source_kind: str) -> list[tuple[Path, int, int, int, int]]:
        cache_key = (str(source_dir), source_kind)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        prefix = source_prefix_for_kind(source_kind)
        allowed_z = {1, 2, 4, 8, 15, 30}
        rows: list[tuple[Path, int, int, int, int]] = []
        for path in source_dir.glob(f"{prefix}_x*_y*_z*_d*.exr"):
            parsed = parse_tile_key(path.name)
            if not parsed:
                continue
            x, y, z, d = parsed
            if z not in allowed_z or d != z:
                continue
            rows.append((path, x, y, z, d))
        self._cache[cache_key] = rows
        return rows


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
    return {
        "bounds": bounds,
        "width": width,
        "height": height,
        "scale": scale,
        "used_w": used_w,
        "used_h": used_h,
        "ox": (width - used_w) / 2.0,
        "oy": (height - used_h) / 2.0,
    }


def full_canvas_bounds(bounds: dict[str, float], width: int = 1000, min_height: int = 320, max_height: int = 820, pad: int = 20) -> dict[str, float]:
    frame = frame_for_bounds(bounds, width=width, min_height=min_height, max_height=max_height, pad=pad)
    scale = max(1e-9, float(frame["scale"]))
    min_lon = float(bounds["min_lon"]) - float(frame["ox"]) / scale
    max_lon = float(bounds["max_lon"]) + (float(frame["width"]) - float(frame["ox"]) - float(frame["used_w"])) / scale
    max_lat = float(bounds["max_lat"]) + float(frame["oy"]) / scale
    min_lat = float(bounds["min_lat"]) - (float(frame["height"]) - float(frame["oy"]) - float(frame["used_h"])) / scale
    return {
        # Keep the full padded SVG canvas, even when the product touches the
        # world edge. Source tile reads are clipped later; clamping here shifts
        # the rendered background relative to the SVG tile overlay.
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
    }


def target_size(bounds: dict[str, float], device_scale: float, max_side: int) -> tuple[int, int]:
    frame = frame_for_bounds(bounds)
    width = max(1, round(frame["width"] * device_scale))
    height = max(1, round(frame["height"] * device_scale))
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


def load_product_bounds(products_file: Path | None) -> dict[str, dict[str, float]]:
    if not products_file:
        return {}
    text = products_file.read_text()
    match = re.search(r"GENERATED_REGION_PACK_PRODUCTS\s*=\s*(\[.*?\]);", text, re.S)
    if not match:
        raise RuntimeError(f"failed to find GENERATED_REGION_PACK_PRODUCTS in {products_file}")
    products = json.loads(match.group(1))
    result: dict[str, dict[str, float]] = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("id") or "").strip()
        bounds = normalize_bounds(product.get("bounds") or product.get("bbox"))
        if product_id and bounds:
            result[product_id] = bounds
    return result


def tile_display_shifts(tile: TileInfo, bounds: dict[str, float]) -> list[float]:
    if tile.lat_max <= bounds["min_lat"] or tile.lat_min >= bounds["max_lat"]:
        return []
    shifts: list[float] = []
    for shift in (-360.0, 0.0, 360.0):
        if tile.lon_max + shift > bounds["min_lon"] and tile.lon_min + shift < bounds["max_lon"]:
            shifts.append(shift)
    return shifts


def intersects(tile: TileInfo, bounds: dict[str, float]) -> bool:
    return bool(tile_display_shifts(tile, bounds))


def source_pixel_area(tile: TileInfo, bounds: dict[str, float]) -> int:
    lat_min = max(bounds["min_lat"], tile.lat_min)
    lat_max = min(bounds["max_lat"], tile.lat_max)
    if lat_max <= lat_min:
        return 0
    total = 0
    for shift in tile_display_shifts(tile, bounds):
        lon_min = max(bounds["min_lon"], tile.lon_min + shift) - shift
        lon_max = min(bounds["max_lon"], tile.lon_max + shift) - shift
        if lon_max <= lon_min:
            continue
        px = max(1, math.ceil((lon_max - lon_min) / tile.lon_span * tile.width))
        py = max(1, math.ceil((lat_max - lat_min) / tile.lat_span * tile.height))
        total += px * py
    return total


def parse_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    parts = [item.strip() for item in str(value or "").split(",")]
    if len(parts) != 3:
        return fallback
    try:
        rgb = tuple(max(0, min(255, int(part))) for part in parts)
    except ValueError:
        return fallback
    return rgb  # type: ignore[return-value]


def normalize_source_kind(value: str) -> str:
    kind = str(value or "").strip().lower()
    if kind not in {"s2", "wt"}:
        raise ValueError(f"unsupported source kind: {value}")
    return kind


def source_prefix_for_kind(source_kind: str) -> str:
    return "WT" if source_kind == "wt" else "S2"


def global_tile_info(source_dir: Path, source_kind: str, cache: ImageInfoCache) -> TileInfo | None:
    prefix = source_prefix_for_kind(source_kind)
    for key in ("x000_y000_z360_d360", "x000_y000_z360_d720", "x000_y000_z180_d180", "x000_y000_z360_d000"):
        path = source_dir / f"{prefix}_{key}.exr"
        if not path.exists():
            continue
        parsed = parse_tile_key(key)
        if not parsed:
            continue
        x, y, z, d = parsed
        width, height = cache.dimensions(path)
        return TileInfo(key=key, x=x, y=y, z=z, d=d, path=path, width=width, height=height)
    return None


def tile_info_for_row(row: dict[str, object], source_dir: Path, source_kind: str, cache: ImageInfoCache) -> TileInfo | None:
    parsed = parse_tile_key(str(row.get("tile_key") or ""))
    if not parsed:
        return None
    x, y, z, d = parsed
    key = f"x{x:03d}_y{y:03d}_z{z:03d}_d{d:03d}"
    path = source_dir / f"{source_prefix_for_kind(source_kind)}_{key}.exr"
    if not path.exists():
        return None
    width, height = cache.dimensions(path)
    return TileInfo(key=key, x=x, y=y, z=z, d=d, path=path, width=width, height=height)


def tile_info_for_path(path: Path, source_kind: str, cache: ImageInfoCache) -> TileInfo | None:
    parsed = parse_tile_key(path.name)
    if not parsed:
        return None
    x, y, z, d = parsed
    expected_prefix = f"{source_prefix_for_kind(source_kind)}_"
    if not path.name.startswith(expected_prefix):
        return None
    width, height = cache.dimensions(path)
    return TileInfo(key=f"x{x:03d}_y{y:03d}_z{z:03d}_d{d:03d}", x=x, y=y, z=z, d=d, path=path, width=width, height=height)


def source_tiles_for_bounds(source_dir: Path, source_kind: str, bounds: dict[str, float], cache: ImageInfoCache, source_index: SourceTileIndex | None = None) -> list[TileInfo]:
    tiles: list[TileInfo] = []
    # Backgrounds are preview imagery. Use real source tiles at sensible map
    # levels, not the global fallback image and not only the licensable product
    # tile rows. This keeps map context complete without silently switching to a
    # different global source.
    rows = source_index.paths(source_dir, source_kind) if source_index else []
    if not rows:
        prefix = source_prefix_for_kind(source_kind)
        rows = []
        for path in source_dir.glob(f"{prefix}_x*_y*_z*_d*.exr"):
            parsed = parse_tile_key(path.name)
            if not parsed:
                continue
            x, y, z, d = parsed
            if z in {1, 2, 4, 8, 15, 30} and d == z:
                rows.append((path, x, y, z, d))
    for path, x, y, z, d in rows:
        probe = TileInfo(key=f"x{x:03d}_y{y:03d}_z{z:03d}_d{d:03d}", x=x, y=y, z=z, d=d, path=path, width=1, height=1)
        if not intersects(probe, bounds):
            continue
        info = tile_info_for_path(path, source_kind, cache)
        if info:
            tiles.append(info)
    return tiles


def choose_tiles_from_source_bounds(bounds: dict[str, float], out_w: int, out_h: int, source_dir: Path, source_kind: str, cache: ImageInfoCache, source_index: SourceTileIndex | None = None) -> tuple[list[TileInfo], str]:
    lon_span = max(1e-6, bounds["max_lon"] - bounds["min_lon"])
    lat_span = max(1e-6, bounds["max_lat"] - bounds["min_lat"])
    required_ppd_x = out_w / lon_span
    required_ppd_y = out_h / lat_span
    groups: dict[tuple[int, int], list[TileInfo]] = {}
    for info in source_tiles_for_bounds(source_dir, source_kind, bounds, cache, source_index=source_index):
        groups.setdefault((info.z, info.d), []).append(info)
    if not groups:
        raise RuntimeError(f"no source {source_prefix_for_kind(source_kind)} tiles available for bounds")
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
        chosen = min(candidates, key=lambda item: (item[3], -item[0], item[1]))
        reason = "source_bounds_no_upscale"
    else:
        chosen = fallback
        reason = f"source_bounds_best_available_ratio_{chosen[2]:.3f}" if chosen else "source_bounds_missing"
    if not chosen:
        raise RuntimeError(f"no usable source-bound {source_prefix_for_kind(source_kind)} tile group")
    return chosen[4], reason


def choose_tiles(asset: dict[str, object], bounds: dict[str, float], out_w: int, out_h: int, source_dir: Path, source_kind: str, cache: ImageInfoCache, use_global_source: bool = True) -> tuple[list[TileInfo], str]:
    lon_span = max(1e-6, bounds["max_lon"] - bounds["min_lon"])
    lat_span = max(1e-6, bounds["max_lat"] - bounds["min_lat"])
    required_ppd_x = out_w / lon_span
    required_ppd_y = out_h / lat_span

    groups: dict[tuple[int, int], list[TileInfo]] = {}
    global_info = global_tile_info(source_dir, source_kind, cache) if use_global_source else None
    if global_info and global_info.d > 0 and intersects(global_info, bounds):
        global_ratio = min(global_info.ppd_x / required_ppd_x, global_info.ppd_y / required_ppd_y)
        if global_ratio >= 1.0:
            return [global_info], f"global_no_upscale_ratio_{global_ratio:.3f}"
        groups.setdefault((global_info.z, global_info.d), []).append(global_info)
    for row in asset.get("tiles") or []:
        if not isinstance(row, dict):
            continue
        info = tile_info_for_row(row, source_dir, source_kind, cache)
        if not info or info.d <= 0 or not intersects(info, bounds):
            continue
        groups.setdefault((info.z, info.d), []).append(info)

    if not groups:
        raise RuntimeError(f"no source {source_prefix_for_kind(source_kind)} tiles available")

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
        raise RuntimeError(f"no usable {source_prefix_for_kind(source_kind)} tile group")
    return chosen[4], reason


def exr_rgb_to_output(arr: np.ndarray, source_kind: str, wt_water_rgb: tuple[int, int, int], wt_land_rgb: tuple[int, int, int]) -> np.ndarray:
    arr = np.clip(arr, 0.0, 1.0)
    if source_kind == "wt":
        # WT uses black for land and several colors for water classes. For web
        # previews all non-black classes are intentionally merged into one blue
        # water color while preserving antialiased coast intensity.
        intensity = np.max(arr, axis=2, keepdims=True)
        intensity = np.power(np.clip(intensity, 0.0, 1.0), 1.0 / 2.2)
        water = np.array(wt_water_rgb, dtype=np.float32).reshape(1, 1, 3)
        land = np.array(wt_land_rgb, dtype=np.float32).reshape(1, 1, 3)
        rgb = land * (1.0 - intensity) + water * intensity
        return np.clip(rgb + 0.5, 0, 255).astype(np.uint8)

    arr = np.power(arr, 1.0 / 2.2)
    return np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)


def read_tile_crop(tile: TileInfo, bounds: dict[str, float], source_kind: str, wt_water_rgb: tuple[int, int, int], wt_land_rgb: tuple[int, int, int], shift: float = 0.0) -> tuple[Image.Image, tuple[float, float, float, float]] | None:
    display_lon_min = max(bounds["min_lon"], tile.lon_min + shift)
    display_lon_max = min(bounds["max_lon"], tile.lon_max + shift)
    lon_min = display_lon_min - shift
    lon_max = display_lon_max - shift
    lat_min = max(bounds["min_lat"], tile.lat_min)
    lat_max = min(bounds["max_lat"], tile.lat_max)
    if display_lon_max <= display_lon_min or lon_max <= lon_min or lat_max <= lat_min:
        return None

    px0 = max(0, min(tile.width - 1, math.floor((lon_min - tile.lon_min) / tile.lon_span * tile.width)))
    px1 = max(px0 + 1, min(tile.width, math.ceil((lon_max - tile.lon_min) / tile.lon_span * tile.width)))
    py0 = max(0, min(tile.height - 1, math.floor((tile.lat_max - lat_max) / tile.lat_span * tile.height)))
    py1 = max(py0 + 1, min(tile.height, math.ceil((tile.lat_max - lat_min) / tile.lat_span * tile.height)))

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
    arr8 = exr_rgb_to_output(arr, source_kind, wt_water_rgb, wt_land_rgb)
    return Image.fromarray(arr8, mode="RGB"), (display_lon_min, lat_min, display_lon_max, lat_max)


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


def paste_tile_to_canvas(canvas: Image.Image, tile: TileInfo, bounds: dict[str, float], source_kind: str, wt_water_rgb: tuple[int, int, int], wt_land_rgb: tuple[int, int, int]) -> bool:
    pasted = False
    for shift in tile_display_shifts(tile, bounds):
        crop = read_tile_crop(tile, bounds, source_kind, wt_water_rgb, wt_land_rgb, shift=shift)
        if not crop:
            continue
        image, crop_bounds = crop
        x0, y0, x1, y1 = output_rect(bounds, canvas.width, canvas.height, crop_bounds)
        dest_size = (x1 - x0, y1 - y0)
        if image.size != dest_size:
            image = image.resize(dest_size, Image.Resampling.LANCZOS)
        canvas.paste(image, (x0, y0))
        pasted = True
    return pasted


def render_background(asset_path: Path, out_path: Path, source_dir: Path, source_kind: str, cache: ImageInfoCache, device_scale: float, max_side: int, quality: int, wt_water_rgb: tuple[int, int, int], wt_land_rgb: tuple[int, int, int], use_global_source: bool = True, use_source_bounds: bool = False, product_bounds_overrides: dict[str, dict[str, float]] | None = None, source_index: SourceTileIndex | None = None) -> dict[str, object]:
    asset = json.loads(asset_path.read_text())
    product = asset.get("region_pack") if isinstance(asset.get("region_pack"), dict) else {}
    product_id = str(product.get("id") or asset_path.stem)
    product_bounds = (product_bounds_overrides or {}).get(product_id) or normalize_bounds(asset.get("bounds"))
    if not product_bounds:
        raise RuntimeError("missing or invalid bounds")
    bounds = full_canvas_bounds(product_bounds)
    out_w, out_h = target_size(product_bounds, device_scale=device_scale, max_side=max_side)
    if use_source_bounds:
        tiles, reason = choose_tiles_from_source_bounds(bounds, out_w, out_h, source_dir, source_kind, cache, source_index=source_index)
    else:
        tiles, reason = choose_tiles(asset, bounds, out_w, out_h, source_dir, source_kind, cache, use_global_source=use_global_source)
    canvas_fill = wt_water_rgb if source_kind == "wt" else (13, 17, 24)
    canvas = Image.new("RGB", (out_w, out_h), canvas_fill)
    pasted = 0
    base_tile = global_tile_info(source_dir, source_kind, cache) if use_global_source else None
    if base_tile and intersects(base_tile, bounds):
        if paste_tile_to_canvas(canvas, base_tile, bounds, source_kind, wt_water_rgb, wt_land_rgb):
            pasted += 1
    for tile in tiles:
        if base_tile and tile.path == base_tile.path:
            continue
        if paste_tile_to_canvas(canvas, tile, bounds, source_kind, wt_water_rgb, wt_land_rgb):
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
        "source_kind": source_kind,
    }


def render_world_background(out_path: Path, source_dir: Path, source_kind: str, max_side: int, quality: int, wt_water_rgb: tuple[int, int, int], wt_land_rgb: tuple[int, int, int]) -> dict[str, object]:
    prefix = source_prefix_for_kind(source_kind)
    candidates = [
        source_dir / f"{prefix}_x000_y000_z360_d360.exr",
        source_dir / f"{prefix}_x000_y000_z360_d720.exr",
        source_dir / f"{prefix}_x000_y000_z180_d180.exr",
        source_dir / f"{prefix}_x000_y000_z360_d000.exr",
    ]
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        raise RuntimeError(f"no world {prefix} source tile found")
    inp = oiio.ImageInput.open(str(source))
    if inp is None:
        raise RuntimeError(f"failed to open world source image: {source}")
    try:
        spec = inp.spec()
        arr = np.asarray(inp.read_scanlines(0, int(spec.height), 0, 0, 3, oiio.FLOAT), dtype=np.float32)
    finally:
        inp.close()
    arr = arr.reshape((int(spec.height), int(spec.width), 3))
    arr8 = exr_rgb_to_output(arr, source_kind, wt_water_rgb, wt_land_rgb)
    image = Image.fromarray(arr8, mode="RGB")
    if max(image.size) > max_side:
        ratio = max_side / max(image.size)
        image = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=quality, optimize=True, progressive=True)
    return {
        "id": "world",
        "width": image.width,
        "height": image.height,
        "source": str(source),
        "bytes": out_path.stat().st_size,
        "path": str(out_path),
        "source_kind": source_kind,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR, help="Directory containing generated region-pack JSON map assets")
    parser.add_argument("--source-kind", choices=("s2", "wt"), default="s2", help="Source imagery kind for backgrounds")
    parser.add_argument("--source-dir", type=Path, default=None, help="Directory containing source *_xNNN_yNNN_zNNN_dNNN.exr tiles")
    parser.add_argument("--s2-dir", type=Path, default=DEFAULT_S2_DIR, help="Directory containing local S2_*.exr source tiles")
    parser.add_argument("--wt-dir", type=Path, default=DEFAULT_WT_DIR, help="Directory containing local WT_*.exr source tiles")
    parser.add_argument("--wt-water-rgb", default=",".join(str(v) for v in DEFAULT_WT_WATER_RGB), help="RGB color for merged WT water classes, e.g. 0,66,180")
    parser.add_argument("--wt-land-rgb", default=",".join(str(v) for v in DEFAULT_WT_LAND_RGB), help="RGB color for WT land pixels, e.g. 0,0,0")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for JPEG backgrounds")
    parser.add_argument("--device-scale", type=float, default=2.0, help="CSS pixel multiplier for generated backgrounds")
    parser.add_argument("--max-side", type=int, default=2400, help="Maximum generated image side in pixels")
    parser.add_argument("--quality", type=int, default=86, help="JPEG quality")
    parser.add_argument("--only", action="append", default=[], help="Only render selected product id; may be repeated")
    parser.add_argument("--limit", type=int, default=0, help="Render at most this many products")
    parser.add_argument("--manifest", type=Path, default=None, help="Optional manifest JSON path")
    parser.add_argument("--products-file", type=Path, default=None, help="Optional generated products JS file; when set, product bbox values are used as the map frame to match the live web pages")
    parser.add_argument("--world-output", type=Path, default=None, help="Optional output path for global fallback background")
    parser.add_argument("--skip-world", action="store_true", help="Do not render the global fallback background")
    parser.add_argument("--no-global-source", action="store_true", help="Render product backgrounds only from product tile rows, not the global fallback tile")
    parser.add_argument("--source-bounds", action="store_true", help="Render product backgrounds from real source tiles intersecting the map bounds, without using the global fallback image")
    args = parser.parse_args()

    assets_dir = args.assets_dir
    if not assets_dir.exists():
        raise SystemExit(f"assets dir does not exist: {assets_dir}")
    source_kind = normalize_source_kind(args.source_kind)
    source_dir = args.source_dir or (args.wt_dir if source_kind == "wt" else args.s2_dir)
    if not source_dir.exists():
        raise SystemExit(f"{source_prefix_for_kind(source_kind)} dir does not exist: {source_dir}")
    wt_water_rgb = parse_rgb(args.wt_water_rgb, DEFAULT_WT_WATER_RGB)
    wt_land_rgb = parse_rgb(args.wt_land_rgb, DEFAULT_WT_LAND_RGB)
    args.out.mkdir(parents=True, exist_ok=True)

    selected = {item.strip().lower() for item in args.only if item.strip()}
    asset_paths = sorted(path for path in assets_dir.glob("*.json") if path.name != "catalog.json")
    if selected:
        asset_paths = [path for path in asset_paths if path.stem.lower() in selected]
    if args.limit and args.limit > 0:
        asset_paths = asset_paths[: args.limit]

    cache = ImageInfoCache()
    source_index = SourceTileIndex()
    product_bounds_overrides = load_product_bounds(args.products_file)
    manifest: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    world_row = None
    if not args.skip_world:
        world_path = args.world_output or args.out / f"world_{source_kind}_background.jpg"
        try:
            world_row = render_world_background(world_path, source_dir, source_kind, args.max_side, args.quality, wt_water_rgb, wt_land_rgb)
            print(f"[world] {world_row['width']}x{world_row['height']} bytes={world_row['bytes']} source={world_row['source']}")
        except Exception as error:  # noqa: BLE001
            failures.append({"id": "world", "error": str(error)})
            print(f"[world] FAILED {error}", file=sys.stderr)
    for index, asset_path in enumerate(asset_paths, start=1):
        out_path = args.out / f"{asset_path.stem}.jpg"
        try:
            row = render_background(asset_path, out_path, source_dir, source_kind, cache, args.device_scale, args.max_side, args.quality, wt_water_rgb, wt_land_rgb, use_global_source=not args.no_global_source, use_source_bounds=args.source_bounds, product_bounds_overrides=product_bounds_overrides, source_index=source_index)
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
        "source_kind": source_kind,
        "world": world_row,
        "backgrounds": manifest,
        "failures": failures,
    }
    manifest_path = args.manifest or args.out / "manifest.json"
    manifest_path.write_text(json.dumps(output, indent=2))
    print(json.dumps({k: output[k] for k in ("ok", "count", "failed", "total_bytes")}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
