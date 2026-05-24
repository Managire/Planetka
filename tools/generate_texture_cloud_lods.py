#!/usr/bin/env python3
"""Generate published d-level EXR variants for Planetka texture-based clouds."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import OpenImageIO as oiio


D_LEVELS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 360)


def _read_cloud_file_list(repo_root: Path) -> list[str]:
    namespace: dict[str, object] = {}
    source = (repo_root / "clouds_local.py").read_text(encoding="utf-8")
    start = source.index("REMOTE_LOCAL_CLOUD_FILES = (")
    end = source.index(")\n", start) + 2
    exec(source[start:end], namespace)
    return list(namespace["REMOTE_LOCAL_CLOUD_FILES"])


def _resize_exr(source_path: Path, target_path: Path, d_level: int) -> None:
    image = oiio.ImageBuf(str(source_path))
    spec = image.spec()
    width = int(spec.width)
    height = int(spec.height)
    channels = int(spec.nchannels)
    if width <= 0 or height <= 0 or channels <= 0:
        raise RuntimeError(f"Invalid source image dimensions: {source_path}")

    if d_level <= 1:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        return

    edge = max(1, int(round(max(width, height) / float(d_level))))
    scale = min(1.0, edge / float(max(width, height)))
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))

    target_spec = oiio.ImageSpec(target_width, target_height, channels, oiio.HALF)
    target = oiio.ImageBuf(target_spec)
    if not oiio.ImageBufAlgo.resize(target, image, "lanczos3"):
        raise RuntimeError(f"Resize failed for {source_path}: {image.geterror()} {target.geterror()}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not target.write(str(target_path)):
        raise RuntimeError(f"Write failed for {target_path}: {target.geterror()}")


def generate(repo_root: Path, source_dir: Path, output_dir: Path, force: bool = False) -> tuple[int, int]:
    cloud_files = _read_cloud_file_list(repo_root)
    written = 0
    skipped = 0
    for filename in cloud_files:
        source_path = source_dir / filename
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing source cloud mask: {source_path}")
        stem = source_path.stem
        source_mtime = source_path.stat().st_mtime
        for d_level in D_LEVELS:
            target_path = output_dir / f"{stem}_d{d_level:03d}.exr"
            if (
                not force
                and target_path.is_file()
                and target_path.stat().st_size > 0
                and target_path.stat().st_mtime >= source_mtime
            ):
                skipped += 1
                continue
            print(f"{filename}: d{d_level:03d} -> {target_path}")
            _resize_exr(source_path, target_path, d_level)
            written += 1
    return written, skipped


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default="/Volumes/SSDA/Planetka Assets/Clouds/Local Clouds",
        help="Directory containing original texture-based cloud EXR masks.",
    )
    parser.add_argument(
        "--output",
        default=str(repo_root / "generated" / "local_cloud_adaptive"),
        help="Output directory for d-level EXR variants.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate existing files.")
    args = parser.parse_args()

    written, skipped = generate(
        repo_root=repo_root,
        source_dir=Path(args.source).expanduser().resolve(),
        output_dir=Path(args.output).expanduser().resolve(),
        force=bool(args.force),
    )
    print(f"Generated {written} file(s), skipped {skipped} existing file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
