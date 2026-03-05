#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import OpenImageIO as oiio


TARGET_D_BY_Z = {
    30: (60, 90, 180, 360),
    60: (90, 180, 360),
    90: (180, 360),
    180: (360, 720),
    360: (720, 1440),  # 1440 is encoded in filenames as d000.
}

TILE_RE = re.compile(
    r"^(?P<kind>S2|EL|WT|PO)_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.(?P<ext>exr|tif)$",
    re.IGNORECASE,
)


def _encode_d_for_name(d: int) -> int:
    return 0 if int(d) == 1440 else int(d)


def _decode_d_from_name(d_code: int) -> int:
    return 1440 if int(d_code) == 0 else int(d_code)


@dataclass
class Stats:
    scanned: int = 0
    eligible_sources: int = 0
    resized: int = 0
    skipped_exists: int = 0
    skipped_nonmatching: int = 0
    failed: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create extended d-level tiles for z030/z060/z090/z180/z360 while preserving "
            "original image format and compression."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/Volumes/SSDA/Planetka Assets"),
        help="Root folder with S2/EL/WT/PO subfolders.",
    )
    parser.add_argument(
        "--types",
        default="S2,EL,WT,PO",
        help="Comma-separated tile types to process.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite destination files if they already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be created.",
    )
    parser.add_argument(
        "--limit-sources",
        type=int,
        default=0,
        help="Optional cap on number of eligible source files to process (0 = no cap).",
    )
    return parser.parse_args()


def _iter_source_files(folder: Path):
    with os.scandir(folder) as it:
        for entry in it:
            if not entry.is_file():
                continue
            name = entry.name
            match = TILE_RE.match(name)
            if not match:
                continue
            yield Path(entry.path), match


def _resize_and_write(src_path: Path, dst_path: Path, dst_w: int, dst_h: int) -> tuple[bool, str]:
    src_buf = oiio.ImageBuf(str(src_path))
    if src_buf.has_error:
        return False, src_buf.geterror()
    src_spec = src_buf.spec()
    if src_spec is None:
        return False, "Missing source spec"

    roi = oiio.ROI(0, int(dst_w), 0, int(dst_h), 0, 1, 0, int(src_spec.nchannels))
    dst_buf = oiio.ImageBuf()
    ok = oiio.ImageBufAlgo.resize(dst_buf, src_buf, roi=roi)
    if not ok:
        return False, dst_buf.geterror() or "Resize failed"

    dst_spec = dst_buf.specmod()
    dst_spec.set_format(src_spec.format)
    compression = src_spec.getattribute("compression")
    if compression:
        dst_spec.attribute("compression", str(compression))

    ok = dst_buf.write(str(dst_path))
    if not ok:
        return False, dst_buf.geterror() or "Write failed"
    return True, ""


def _target_dimensions(src_w: int, src_h: int, z: int, d_effective: int) -> tuple[int, int]:
    scale = float(z) / float(d_effective)
    dst_w = max(1, int(round(float(src_w) * scale)))
    dst_h = max(1, int(round(float(src_h) * scale)))
    return dst_w, dst_h


def _process_type(root: Path, tile_type: str, overwrite: bool, dry_run: bool, limit_sources: int) -> Stats:
    stats = Stats()
    folder = root / tile_type
    if not folder.is_dir():
        return stats

    processed_sources = 0
    start = time.perf_counter()
    for src_path, match in _iter_source_files(folder):
        stats.scanned += 1

        z = int(match.group("z"))
        d_code = int(match.group("d"))
        d_effective = _decode_d_from_name(d_code)
        ext = str(match.group("ext"))
        kind = str(match.group("kind"))
        x = int(match.group("x"))
        y = int(match.group("y"))

        if z not in TARGET_D_BY_Z or d_effective != z:
            stats.skipped_nonmatching += 1
            continue

        stats.eligible_sources += 1
        processed_sources += 1
        if limit_sources > 0 and processed_sources > limit_sources:
            break

        src_buf = oiio.ImageBuf(str(src_path))
        if src_buf.has_error:
            stats.failed += 1
            print(f"[FAIL] {src_path.name}: {src_buf.geterror()}")
            continue
        src_spec = src_buf.spec()
        if src_spec is None:
            stats.failed += 1
            print(f"[FAIL] {src_path.name}: missing image spec")
            continue
        src_w = int(src_spec.width)
        src_h = int(src_spec.height)

        for target_d in TARGET_D_BY_Z[z]:
            d_name = _encode_d_for_name(int(target_d))
            dst_name = f"{kind}_x{x:03d}_y{y:03d}_z{z:03d}_d{d_name:03d}.{ext}"
            dst_path = folder / dst_name
            if dst_path.exists() and not overwrite:
                stats.skipped_exists += 1
                continue

            dst_w, dst_h = _target_dimensions(src_w, src_h, z, int(target_d))
            if dry_run:
                stats.resized += 1
                print(f"[DRY] {src_path.name} -> {dst_name} ({src_w}x{src_h} -> {dst_w}x{dst_h})")
                continue

            ok, error = _resize_and_write(src_path=src_path, dst_path=dst_path, dst_w=dst_w, dst_h=dst_h)
            if not ok:
                stats.failed += 1
                print(f"[FAIL] {src_path.name} -> {dst_name}: {error}")
                continue
            stats.resized += 1

    elapsed = time.perf_counter() - start
    print(
        f"[{tile_type}] scanned={stats.scanned} eligible={stats.eligible_sources} "
        f"created={stats.resized} exists={stats.skipped_exists} "
        f"nonmatching={stats.skipped_nonmatching} failed={stats.failed} "
        f"time={elapsed:.1f}s"
    )
    return stats


def main() -> int:
    args = _parse_args()
    root = args.root.expanduser().resolve()
    types = [token.strip().upper() for token in str(args.types).split(",") if token.strip()]
    types = [token for token in types if token in {"S2", "EL", "WT", "PO"}]
    if not types:
        print("No valid tile types selected. Use --types with S2,EL,WT,PO.")
        return 2
    if not root.is_dir():
        print(f"Root path does not exist: {root}")
        return 2

    total = Stats()
    started = time.perf_counter()
    for tile_type in types:
        stats = _process_type(
            root=root,
            tile_type=tile_type,
            overwrite=bool(args.overwrite),
            dry_run=bool(args.dry_run),
            limit_sources=max(0, int(args.limit_sources)),
        )
        total.scanned += stats.scanned
        total.eligible_sources += stats.eligible_sources
        total.resized += stats.resized
        total.skipped_exists += stats.skipped_exists
        total.skipped_nonmatching += stats.skipped_nonmatching
        total.failed += stats.failed

    elapsed = time.perf_counter() - started
    print(
        "TOTAL "
        f"scanned={total.scanned} eligible={total.eligible_sources} created={total.resized} "
        f"exists={total.skipped_exists} nonmatching={total.skipped_nonmatching} "
        f"failed={total.failed} time={elapsed:.1f}s"
    )
    return 1 if total.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
