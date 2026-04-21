#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import time
from pathlib import Path

import cv2
import numpy as np


TILE_RE = re.compile(r"^S2_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.exr$", re.IGNORECASE)

# New S2 policy for higher-z base source level.
Z_BASE_SOURCE = {
    2: 1,
    4: 1,
    8: 1,
    15: 1,
    16: 8,
    30: 15,
    32: 8,
    60: 15,
    90: 15,
    180: 15,
    360: 15,
}


def _decode_d_from_name(d_code: int) -> int:
    return 1440 if int(d_code) == 0 else int(d_code)


def _encode_d_for_name(d_effective: int) -> int:
    return 0 if int(d_effective) == 1440 else int(d_effective)


def _load_s2_module(module_path: Path):
    spec = importlib.util.spec_from_file_location("s2_clamp_rebuild", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bbox_inside(x: int, y: int, z: int, rx: int, ry: int, rz: int) -> bool:
    return x >= rx and y >= ry and (x + z) <= (rx + rz) and (y + z) <= (ry + rz)


def _collect_region_coords(root: Path, z_levels: set[int], rx: int, ry: int, rz: int):
    coords_by_z: dict[int, list[tuple[int, int]]] = {z: [] for z in z_levels}
    d_levels_by_z: dict[int, set[int]] = {z: set() for z in z_levels}
    with os.scandir(root) as it:
        for entry in it:
            if not entry.is_file():
                continue
            m = TILE_RE.match(entry.name)
            if not m:
                continue
            x = int(m.group("x"))
            y = int(m.group("y"))
            z = int(m.group("z"))
            if z not in z_levels:
                continue
            d_code = int(m.group("d"))
            d_eff = _decode_d_from_name(d_code)
            d_levels_by_z[z].add(d_eff)

    # Rebuild every coordinate fully contained inside the region tile, aligned to each z grid.
    for z in sorted(z_levels):
        x_first = ((int(rx) + z - 1) // z) * z
        y_first = ((int(ry) + z - 1) // z) * z
        x_last = int(rx) + int(rz) - int(z)
        y_last = int(ry) + int(rz) - int(z)
        if x_first > x_last or y_first > y_last:
            coords_by_z[z] = []
            continue
        xs = list(range(x_first, x_last + 1, z))
        ys = list(range(y_first, y_last + 1, z))
        coords_by_z[z] = [(x, y) for y in ys for x in xs]

    out_coords = {z: list(v) for z, v in coords_by_z.items()}
    out_d = {z: sorted(v) for z, v in d_levels_by_z.items()}
    return out_coords, out_d


def _build_from_z001(mod, target_x: int, target_y: int, target_z: int) -> np.ndarray:
    if target_z == 15:
        y_size = 11133 // 15
        x_size = mod._x_size_for_z15(target_y)
        out = np.zeros((y_size * 15, x_size * 15, 3), dtype=np.float32)
        for y_coord in range(15):
            for x_coord in range(15):
                image = mod._read_or_fallback(target_x + x_coord, target_y + y_coord, 1, 1)
                ys = (14 - y_coord) * y_size
                xs = x_coord * x_size
                out[ys : ys + y_size, xs : xs + x_size] = mod._resize(image, x_size, y_size)
        return out

    if target_z in (2, 4, 8):
        cells = target_z
        tile_images: list[list[np.ndarray]] = []
        max_w = 0
        max_h = 0
        for y_coord in range(cells):
            row: list[np.ndarray] = []
            for x_coord in range(cells):
                img = mod._read_or_fallback(target_x + x_coord, target_y + y_coord, 1, 1)
                row.append(img)
                max_h = max(max_h, int(img.shape[0]))
                max_w = max(max_w, int(img.shape[1]))
            tile_images.append(row)

        mosaic = np.zeros((max_h * cells, max_w * cells, 3), dtype=np.float32)
        for y_coord in range(cells):
            for x_coord in range(cells):
                rs = mod._resize(tile_images[y_coord][x_coord], max_w, max_h)
                ys = (cells - 1 - y_coord) * max_h
                xs = x_coord * max_w
                mosaic[ys : ys + max_h, xs : xs + max_w] = rs

        return cv2.resize(mosaic, (max_w, max_h), interpolation=cv2.INTER_AREA)

    raise RuntimeError(f"Unsupported direct-from-z001 target z={target_z}")


def _build_base_tile(mod, x: int, y: int, z: int):
    src_z = int(Z_BASE_SOURCE.get(int(z), int(z)))
    if z == 1:
        return

    if src_z == 1:
        out = _build_from_z001(mod, x, y, z)
        mod._write_s2_exr(mod._tile_path(x, y, z, _encode_d_for_name(z)), out)
        return

    # For source levels > 1 keep existing policy builder.
    ok, err = mod._build_z_base((x, y, z))
    if not ok:
        raise RuntimeError(err)


def _rebuild_d_from_lowest(mod, x: int, y: int, z: int, d_levels: list[int]):
    base_d = 1 if int(z) == 1 else int(z)

    src_path = mod._tile_path(x, y, z, _encode_d_for_name(base_d))
    if int(z) == 1 and not os.path.isfile(src_path):
        # Synthesize missing z001 base from fallback so full region grids can be rebuilt.
        fb = mod._read_or_fallback(x, y, 1, 1)
        dst_w = int(mod._x_size_for_z15(int(y))) * 15
        dst_h = 11133
        base_img = mod._resize(fb, dst_w, dst_h)
        mod._write_s2_exr(src_path, base_img)
    if not os.path.isfile(src_path):
        raise RuntimeError(f"Missing base source tile: {src_path}")

    src = mod._read_image(src_path)
    src_h = int(src.shape[0])
    src_w = int(src.shape[1])

    rebuilt = 0
    for d_eff in sorted(set(int(v) for v in d_levels)):
        if d_eff < base_d:
            continue
        if d_eff == base_d:
            continue
        scale = float(base_d) / float(d_eff)
        dst_w = max(1, int(round(float(src_w) * scale)))
        dst_h = max(1, int(round(float(src_h) * scale)))
        out = mod._resize(src, dst_w, dst_h)
        dst_path = mod._tile_path(x, y, z, _encode_d_for_name(d_eff))
        mod._write_s2_exr(dst_path, out)
        rebuilt += 1
    return rebuilt


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild S2 tiles inside a region using direct-from-lowest-d policy "
            "for higher-z/higher-d generation."
        )
    )
    parser.add_argument("--root", default="/Volumes/SSDA/Planetka Assets/S2", help="S2 root folder")
    parser.add_argument(
        "--module",
        default=(
            "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
            "user_default/Planetka/tools/s2_clamp_rebuild.py"
        ),
        help="Path to s2_clamp_rebuild.py",
    )
    parser.add_argument(
        "--ocean-fallback",
        default=(
            "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
            "user_default/Planetka/Resources/Fallback Images/ocean_pixel_final_20.exr"
        ),
    )
    parser.add_argument(
        "--white-fallback",
        default=(
            "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
            "user_default/Planetka/Resources/Fallback Images/white_pixel_20.exr"
        ),
    )
    parser.add_argument("--region-x", type=int, required=True, help="Region tile x")
    parser.add_argument("--region-y", type=int, required=True, help="Region tile y")
    parser.add_argument("--region-z", type=int, required=True, help="Region tile z (extent)")
    parser.add_argument("--z-max", type=int, default=15, help="Maximum z level to include")
    parser.add_argument(
        "--only-z",
        default="",
        help="Optional comma-separated z levels to process (example: 2,4,8,15)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(args.root).expanduser().resolve()
    module_path = Path(args.module).expanduser().resolve()
    if not root.is_dir():
        print(f"S2 root not found: {root}")
        return 2
    if not module_path.is_file():
        print(f"Module not found: {module_path}")
        return 2

    mod = _load_s2_module(module_path)
    mod.ROOT_DIR = str(root)
    mod.OCEAN_FALLBACK_PATH = str(Path(args.ocean_fallback).expanduser().resolve())
    mod.WHITE_FALLBACK_PATH = str(Path(args.white_fallback).expanduser().resolve())
    mod._OCEAN_FALLBACK = None
    mod._WHITE_FALLBACK = None

    z_levels = {z for z in (1, 2, 4, 8, 15) if z <= int(args.z_max)}
    if str(args.only_z).strip():
        selected = {int(part.strip()) for part in str(args.only_z).split(",") if part.strip()}
        z_levels = {z for z in z_levels if z in selected}
    rx = int(args.region_x)
    ry = int(args.region_y)
    rz = int(args.region_z)

    started = time.perf_counter()
    print(
        f"s2 direct-lowd rebuild start root={root} region=x{rx:03d}_y{ry:03d}_z{rz:03d} "
        f"z_levels={sorted(z_levels)}"
    )

    coords_by_z, d_levels_by_z = _collect_region_coords(root, z_levels, rx, ry, rz)
    counts = {z: len(coords_by_z.get(z, [])) for z in sorted(z_levels)}
    print(f"coords_by_z={counts}")
    print(f"d_levels_by_z={{{', '.join(f'{z}:{d_levels_by_z.get(z, [])}' for z in sorted(z_levels))}}}")

    # Rebuild higher-z bases first.
    base_done = 0
    for z in sorted(v for v in z_levels if v > 1):
        coords = coords_by_z.get(z, [])
        for idx, (x, y) in enumerate(coords, start=1):
            _build_base_tile(mod, x, y, z)
            base_done += 1
            if idx % 10 == 0 or idx == len(coords):
                print(f"[base-z{z:03d}] {idx}/{len(coords)}")

    # Rebuild all d-levels from the lowest source for each selected tile.
    d_done = 0
    for z in sorted(z_levels):
        coords = coords_by_z.get(z, [])
        d_levels = d_levels_by_z.get(z, [])
        z_rebuilt = 0
        for idx, (x, y) in enumerate(coords, start=1):
            z_rebuilt += _rebuild_d_from_lowest(mod, x, y, z, d_levels)
            if idx % 20 == 0 or idx == len(coords):
                print(f"[d-z{z:03d}] {idx}/{len(coords)} rebuilt={z_rebuilt}")
        d_done += z_rebuilt

    elapsed = time.perf_counter() - started
    print(f"s2 direct-lowd rebuild done base_tiles={base_done} d_tiles={d_done} elapsed={elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
