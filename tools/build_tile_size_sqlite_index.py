#!/usr/bin/env python3
"""Build a read-only tile-size sqlite index for fast resolve size estimates.

Usage:
  python3 tools/build_tile_size_sqlite_index.py \
    --assets-root "/Volumes/SSDA/Planetka Assets" \
    --output "/Users/.../Planetka/Resources/tile_sizes.sqlite"
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


ALLOWED_FOLDERS = ("S2", "EL", "WT", "PO")
ALLOWED_EXTENSIONS = {".exr", ".tif"}


def iter_tile_files(assets_root: Path):
    for folder in ALLOWED_FOLDERS:
        folder_path = assets_root / folder
        if not folder_path.is_dir():
            continue
        for dir_path, _, file_names in os.walk(folder_path):
            for file_name in file_names:
                ext = Path(file_name).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    continue
                abs_path = Path(dir_path) / file_name
                rel_key = abs_path.relative_to(assets_root).as_posix()
                name = abs_path.name
                try:
                    stem, ext = name.rsplit(".", 1)
                    parts = stem.split("_")
                    # Prefix_x000_y000_z000_d000.ext
                    x = int(parts[1][1:])
                    y = int(parts[2][1:])
                    z = int(parts[3][1:])
                    d = int(parts[4][1:])
                    ext_text = ext.lower()
                except (IndexError, ValueError):
                    continue
                try:
                    size_bytes = int(max(0, abs_path.stat().st_size))
                except OSError:
                    continue
                yield rel_key, folder, x, y, z, d, ext_text, size_bytes


def build_index(assets_root: Path, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(str(output_path))
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA page_size=4096")
        conn.execute(
            """
            CREATE TABLE tile_sizes (
              folder TEXT NOT NULL,
              x INTEGER NOT NULL,
              y INTEGER NOT NULL,
              z INTEGER NOT NULL,
              d INTEGER NOT NULL,
              ext TEXT NOT NULL,
              size_bytes INTEGER NOT NULL,
              PRIMARY KEY(folder, x, y, z, d, ext)
            ) WITHOUT ROWID
            """
        )

        batch = []
        rows = 0
        total_bytes = 0
        for _key, folder, x, y, z, d, ext_text, size_bytes in iter_tile_files(assets_root):
            batch.append((str(folder), int(x), int(y), int(z), int(d), str(ext_text), int(size_bytes)))
            rows += 1
            total_bytes += int(size_bytes)
            if len(batch) >= 10000:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO tile_sizes(folder, x, y, z, d, ext, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                conn.commit()
                batch.clear()
        if batch:
            conn.executemany(
                """
                INSERT OR REPLACE INTO tile_sizes(folder, x, y, z, d, ext, size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            conn.commit()

        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    db_size = output_path.stat().st_size if output_path.exists() else 0
    print(f"rows={rows}")
    print(f"indexed_total_bytes={total_bytes}")
    print(f"sqlite_bytes={db_size}")
    print(f"sqlite_path={output_path}")


def main():
    parser = argparse.ArgumentParser(description="Build Planetka tile-size sqlite index")
    parser.add_argument("--assets-root", required=True, help="Root directory containing S2/EL/WT/PO folders")
    parser.add_argument("--output", required=True, help="Output sqlite file path")
    args = parser.parse_args()

    assets_root = Path(args.assets_root).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not assets_root.is_dir():
        raise SystemExit(f"Assets root does not exist: {assets_root}")

    build_index(assets_root, output_path)


if __name__ == "__main__":
    main()
