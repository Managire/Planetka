#!/usr/bin/env python3
"""Build small S2 tile preview images for a single product pilot.

This is intentionally offline/local. It does not upload previews or change the
web UI; it creates reviewable JPEGs and a contact sheet for visual approval.
"""

from __future__ import annotations

import argparse
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import OpenEXR
from PIL import Image, ImageDraw, ImageFont


TILE_RE = re.compile(r"x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})")
DEFAULT_TILE_DATA = Path("cloudflare-api/src/worker/region_packs.tile_data.generated.js")
DEFAULT_S2_DIR = Path("/Volumes/SSDA/Planetka Assets/S2")
DEFAULT_OUT_DIR = Path("/Volumes/SSDA/Planetka Tile Preview Pilot")


def _extract_product_tiles(tile_data_path: Path, product_id: str) -> list[str]:
    text = tile_data_path.read_text()
    match = re.search(rf'"{re.escape(product_id)}"\s*:\s*\[', text)
    if not match:
        raise RuntimeError(f"product tile data not found: {product_id}")
    start = match.end()
    end = text.find("\n  ],", start)
    if end < 0:
        raise RuntimeError(f"could not find tile list end for: {product_id}")
    return re.findall(r'"(x\d{3}_y\d{3}_z\d{3}_d\d{3})"', text[start:end])


def _read_rgb_exr(path: Path) -> np.ndarray:
    exr = OpenEXR.File(str(path))
    channels = exr.parts[0].channels
    if "RGB" in channels:
        rgb = np.asarray(channels["RGB"].pixels, dtype=np.float32)
    elif all(name in channels for name in ("R", "G", "B")):
        rgb = np.stack(
            [
                np.asarray(channels["R"].pixels, dtype=np.float32),
                np.asarray(channels["G"].pixels, dtype=np.float32),
                np.asarray(channels["B"].pixels, dtype=np.float32),
            ],
            axis=2,
        )
    else:
        raise RuntimeError(f"missing RGB channels: {path}")
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[:, :, None], 3, axis=2)
    return rgb[:, :, :3].astype(np.float32, copy=False)


def _source_preview_path(s2_dir: Path, tile_key: str) -> tuple[Path, str]:
    match = TILE_RE.fullmatch(tile_key)
    if not match:
        raise RuntimeError(f"invalid tile key: {tile_key}")
    x, y, z, _d = match.groups()
    z_int = int(z)
    if z_int in {1, 2, 4, 8, 15}:
        preview_d = "060"
    elif z_int == 30:
        # Requested pilot target was z030/d120, but the current local S2 source
        # set does not contain d120. Use d060 for this pilot because it is more
        # detailed and can be downscaled later if d120 assets are added.
        preview_d = "060"
    else:
        preview_d = _d
    path = s2_dir / f"S2_x{x}_y{y}_z{z}_d{preview_d}.exr"
    return path, f"z{z}_d{preview_d}"


def _to_display_image(rgb: np.ndarray, brightness: float, size: tuple[int, int]) -> Image.Image:
    # S2 files are dark linear floats; boost then apply a simple display gamma.
    rgb = np.clip(rgb * float(brightness), 0.0, 1.0)
    rgb = np.power(rgb, 1.0 / 2.2)
    image = Image.fromarray((rgb * 255.0 + 0.5).astype(np.uint8), "RGB")
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image


def _make_contact_sheet(images: list[tuple[str, Image.Image]], output: Path, thumb: int = 180) -> None:
    if not images:
        return
    cols = 6
    label_h = 34
    rows = math.ceil(len(images) / cols)
    sheet = Image.new("RGB", (cols * thumb, rows * (thumb + label_h)), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for idx, (label, image) in enumerate(images):
        row, col = divmod(idx, cols)
        x = col * thumb
        y = row * (thumb + label_h)
        tile = Image.new("RGB", (thumb, thumb), (5, 5, 5))
        fitted = image.copy()
        fitted.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        px = (thumb - fitted.width) // 2
        py = (thumb - fitted.height) // 2
        tile.paste(fitted, (px, py))
        sheet.paste(tile, (x, y))
        draw.text((x + 4, y + thumb + 4), label[:28], fill=(235, 235, 235), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=88, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", default="new_zealand")
    parser.add_argument("--tile-data", type=Path, default=DEFAULT_TILE_DATA)
    parser.add_argument("--s2-dir", type=Path, default=DEFAULT_S2_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--brightness", type=float, default=2.0)
    parser.add_argument("--quality", type=int, default=82)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    args = parser.parse_args()

    tiles = _extract_product_tiles(args.tile_data, args.product_id)
    out_dir = args.out_dir / args.product_id
    out_dir.mkdir(parents=True, exist_ok=True)

    missing: list[tuple[str, Path]] = []
    generated: list[tuple[str, Image.Image]] = []
    source_counts: Counter[str] = Counter()
    for tile_key in tiles:
        source_path, source_level = _source_preview_path(args.s2_dir, tile_key)
        source_counts[source_level] += 1
        if not source_path.exists():
            missing.append((tile_key, source_path))
            continue
        rgb = _read_rgb_exr(source_path)
        image = _to_display_image(rgb, args.brightness, (args.width, args.height))
        target = out_dir / f"{tile_key}.jpg"
        image.save(target, quality=args.quality, optimize=True, progressive=True)
        generated.append((tile_key, image))

    contact_sheet = out_dir / f"{args.product_id}_contact_sheet.jpg"
    _make_contact_sheet(generated, contact_sheet)

    print(f"product_id={args.product_id}")
    print(f"tiles={len(tiles)} generated={len(generated)} missing={len(missing)}")
    print(f"output_dir={out_dir}")
    print(f"contact_sheet={contact_sheet}")
    print("source_levels=" + ", ".join(f"{k}:{v}" for k, v in sorted(source_counts.items())))
    if missing:
        print("missing_sources:")
        for tile_key, path in missing[:50]:
            print(f"  {tile_key} -> {path}")
        if len(missing) > 50:
            print(f"  ... {len(missing) - 50} more")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
