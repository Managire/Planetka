#!/usr/bin/env python3
"""Populate tile_land_stats in Resources/tile_sizes.sqlite from S2 textures.

S2 convention:
- every pixel is counted as billable surface unless it matches the S2 ocean-fill color
- billing/free latitude criteria remain independent from pixel classification

The script is incremental. Existing rows are skipped unless --force is used.
Large EXR files are streamed scanline-by-scanline through OpenImageIO.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import datetime as _dt
import math
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    import OpenImageIO as oiio
except Exception as exc:  # pragma: no cover - depends on local Blender/Python install
    raise SystemExit(f"OpenImageIO is required to read S2 textures: {exc}")

try:
    import numpy as np
except Exception as exc:  # pragma: no cover - depends on local Python install
    raise SystemExit(f"NumPy is required to scan S2 textures efficiently: {exc}")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "Resources" / "tile_sizes.sqlite"
DEFAULT_S2_ROOT = Path("/Volumes/SSDA/Planetka Assets/S2")
DEFAULT_OCEAN_FALLBACK = ROOT / "Resources" / "Fallback Images" / "ocean_pixel_final_20.exr"
TILE_RE = re.compile(r"^S2_(x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3}))\.exr$", re.IGNORECASE)
EARTH_RADIUS_KM = 6371.0088
FREE_D_THRESHOLD = 15
FREE_DETAIL_RATIO = 4.0
PAID_LAT_MIN_DEG = -60.0
PAID_LAT_MAX_DEG = 75.0
EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2
S2_OCEAN_TOLERANCE = np.float32(1e-5)


def read_ocean_rgb_from_fallback(path: Path = DEFAULT_OCEAN_FALLBACK) -> np.ndarray:
    inp = oiio.ImageInput.open(str(path))
    if inp is None:
        raise RuntimeError(f"Unable to open S2 ocean fallback: {path}")
    try:
        spec = inp.spec()
        if int(spec.width) <= 0 or int(spec.height) <= 0 or int(spec.nchannels) < 3:
            raise RuntimeError(
                f"Unsupported S2 ocean fallback shape for {path}: "
                f"{spec.width}x{spec.height}x{spec.nchannels}"
            )
        scanline = inp.read_scanline(0, 0, oiio.FLOAT)
        if scanline is None:
            raise RuntimeError(f"Unable to read S2 ocean fallback: {path}")
        arr = np.asarray(scanline, dtype=np.float32).reshape(int(spec.width), int(spec.nchannels))
        return np.array(arr[0, :3], dtype=np.float32)
    finally:
        inp.close()


S2_OCEAN_RGB = read_ocean_rgb_from_fallback()


def now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_duration(seconds: float) -> str:
    total = int(max(0, float(seconds or 0.0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def count_source_files(root: Path) -> int:
    count = 0
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_file() and TILE_RE.match(entry.name):
                count += 1
    return count


def spherical_area_km2(lon_west, lon_east, lat_south, lat_north) -> float:
    if lon_east <= lon_west or lat_north <= lat_south:
        return 0.0
    lon_delta = math.radians(float(lon_east) - float(lon_west))
    south_rad = math.radians(float(lat_south))
    north_rad = math.radians(float(lat_north))
    return max(0.0, (EARTH_RADIUS_KM ** 2) * lon_delta * abs(math.sin(north_rad) - math.sin(south_rad)))


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tile_land_stats (
            tile_key TEXT PRIMARY KEY,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            z INTEGER NOT NULL,
            d INTEGER NOT NULL,
            land_km2 REAL NOT NULL DEFAULT 0,
            billable_land_km2 REAL NOT NULL DEFAULT 0,
            base_credits REAL NOT NULL DEFAULT 0,
            land_fraction REAL NOT NULL DEFAULT 0,
            paid_lat_fraction REAL NOT NULL DEFAULT 0,
            free_reason TEXT,
            source TEXT NOT NULL DEFAULT 'S2',
            updated_at TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tile_land_stats_zd ON tile_land_stats(z, d)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tile_land_stats_free_reason ON tile_land_stats(free_reason)")


def classify_land_rgb(rgb) -> bool:
    try:
        r = float(rgb[0])
        g = float(rgb[1])
        b = float(rgb[2])
    except (TypeError, ValueError, IndexError):
        return False
    values = np.array((r, g, b), dtype=np.float32)
    return not bool(np.all(np.abs(values - S2_OCEAN_RGB) <= S2_OCEAN_TOLERANCE))


def count_land_pixels(scanline, width: int, channels: int) -> int:
    arr = np.asarray(scanline, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(int(width), int(channels))
    elif arr.ndim == 2:
        arr = arr.reshape(int(width), int(channels))
    else:
        arr = arr.reshape(-1, int(channels))
    rgb = arr[:, :3]
    ocean = np.all(np.abs(rgb - S2_OCEAN_RGB) <= S2_OCEAN_TOLERANCE, axis=1)
    return int(np.count_nonzero(~ocean))


def scan_s2_file(path: Path, x: int, y: int, z: int, d: int):
    inp = oiio.ImageInput.open(str(path))
    if inp is None:
        raise RuntimeError(f"Unable to open {path}")
    try:
        spec = inp.spec()
        width = int(spec.width)
        height = int(spec.height)
        channels = int(spec.nchannels)
        if width <= 0 or height <= 0 or channels < 3:
            raise RuntimeError(f"Unsupported S2 image shape for {path}: {width}x{height}x{channels}")

        lon_west = float(x) - 180.0
        lon_east = float(x + z) - 180.0
        lat_south = max(-90.0, float(y) - 90.0)
        lat_north = min(90.0, float(y + z) - 90.0)
        tile_area = spherical_area_km2(lon_west, lon_east, lat_south, lat_north)
        detail_ratio = (float(d) / max(1.0, float(z))) if d > 0 else float("inf")
        if d <= 0:
            free_reason = "d000_global_free"
        elif d >= FREE_D_THRESHOLD:
            free_reason = "coarse_detail_free"
        elif detail_ratio >= FREE_DETAIL_RATIO:
            free_reason = "preview_detail_free"
        elif lat_north <= PAID_LAT_MIN_DEG:
            free_reason = "south_polar_free"
        elif lat_south >= PAID_LAT_MAX_DEG:
            free_reason = "north_polar_free"
        else:
            free_reason = ""

        land_area = 0.0
        billable_area = 0.0
        paid_area = spherical_area_km2(
            lon_west,
            lon_east,
            max(lat_south, PAID_LAT_MIN_DEG),
            min(lat_north, PAID_LAT_MAX_DEG),
        )
        for row in range(height):
            # OIIO image origin is top-left for normal image files. This maps
            # row 0 to northern latitude.
            row_north = lat_north - (float(row) / float(height)) * (lat_north - lat_south)
            row_south = lat_north - (float(row + 1) / float(height)) * (lat_north - lat_south)
            row_area = spherical_area_km2(lon_west, lon_east, row_south, row_north)
            paid_row_area = 0.0 if free_reason else spherical_area_km2(
                lon_west,
                lon_east,
                max(row_south, PAID_LAT_MIN_DEG),
                min(row_north, PAID_LAT_MAX_DEG),
            )
            scanline = inp.read_scanline(row, 0, oiio.FLOAT)
            if scanline is None:
                raise RuntimeError(f"Unable to read scanline {row} from {path}")
            land_pixels = count_land_pixels(scanline, width, channels)
            fraction = float(land_pixels) / float(width)
            land_area += row_area * fraction
            billable_area += paid_row_area * fraction

        base_credits = max(0.0, billable_area / EQUATOR_Z001_AREA_KM2)
        return {
            "land_km2": land_area,
            "billable_land_km2": billable_area,
            "base_credits": base_credits,
            "land_fraction": (land_area / tile_area) if tile_area > 0 else 0.0,
            "paid_lat_fraction": (paid_area / tile_area) if tile_area > 0 else 0.0,
            "free_reason": free_reason,
        }
    finally:
        inp.close()


def process_source_entry(entry):
    path_text, tile_key, x, y, z, d = entry
    stats = scan_s2_file(Path(path_text), int(x), int(y), int(z), int(d))
    return path_text, tile_key, int(x), int(y), int(z), int(d), stats


def iter_source_files(root: Path, limit: int = 0):
    count = 0
    with os.scandir(root) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            match = TILE_RE.match(entry.name)
            if not match:
                continue
            tile_key = match.group(1)
            x, y, z, d = (int(match.group(index)) for index in range(2, 6))
            yield str(entry.path), tile_key, x, y, z, d
            count += 1
            if limit and count >= limit:
                return


def write_tile_stats(conn: sqlite3.Connection, tile_key: str, x: int, y: int, z: int, d: int, stats: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tile_land_stats (
            tile_key, x, y, z, d,
            land_km2, billable_land_km2, base_credits,
            land_fraction, paid_lat_fraction, free_reason, source, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'S2', ?)
        """,
        (
            tile_key,
            x,
            y,
            z,
            d,
            float(stats["land_km2"]),
            float(stats["billable_land_km2"]),
            float(stats["base_credits"]),
            float(stats["land_fraction"]),
            float(stats["paid_lat_fraction"]),
            str(stats["free_reason"] or ""),
            now_iso(),
        ),
    )


def install_stats_to_live_db(work_db_path: Path, live_db_path: Path) -> int:
    columns = (
        "tile_key",
        "x",
        "y",
        "z",
        "d",
        "land_km2",
        "billable_land_km2",
        "base_credits",
        "land_fraction",
        "paid_lat_fraction",
        "free_reason",
        "source",
        "updated_at",
    )
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    select_sql = f"SELECT {column_sql} FROM tile_land_stats ORDER BY tile_key"
    insert_sql = f"INSERT OR REPLACE INTO tile_land_stats ({column_sql}) VALUES ({placeholders})"
    installed = 0
    stage = sqlite3.connect(str(work_db_path))
    live = sqlite3.connect(str(live_db_path))
    try:
        create_schema(live)
        live.execute("BEGIN")
        live.execute("DELETE FROM tile_land_stats")
        cursor = stage.execute(select_sql)
        while True:
            rows = cursor.fetchmany(2000)
            if not rows:
                break
            live.executemany(insert_sql, rows)
            installed += len(rows)
        live.commit()
    except Exception:
        live.rollback()
        raise
    finally:
        stage.close()
        live.close()
    return installed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument(
        "--work-db",
        default="",
        help="Staging DB used while scanning. Defaults to <db>.land_stats_build so Blender never reads partial stats.",
    )
    parser.add_argument("--s2-root", default=str(DEFAULT_S2_ROOT))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Do not copy the completed staging table into --db.",
    )
    parser.add_argument(
        "--install-partial",
        action="store_true",
        help="Install even when --limit is used. Useful only for controlled tests.",
    )
    parser.add_argument("--only", default="", help="Comma-separated tile keys without S2_ prefix")
    parser.add_argument("--workers", type=int, default=1, help="Number of S2 reader processes")
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser()
    work_db_path = Path(args.work_db).expanduser() if str(args.work_db or "").strip() else db_path.with_name(f"{db_path.name}.land_stats_build")
    s2_root = Path(args.s2_root).expanduser()
    if not s2_root.is_dir():
        raise SystemExit(f"S2 root does not exist: {s2_root}")
    if work_db_path.resolve() == db_path.resolve():
        raise SystemExit("Refusing to build land stats directly into the live DB. Use a separate --work-db.")

    only = {token.strip() for token in str(args.only or "").split(",") if token.strip()}
    conn = sqlite3.connect(str(work_db_path))
    create_schema(conn)
    processed = 0
    skipped = 0
    failed = 0
    workers = max(1, int(args.workers or 1))
    pending_limit = max(1, workers * 4)
    commit_every = 100
    total_files = count_source_files(s2_root)
    install_at_end = not bool(args.no_install) and (not bool(args.limit) or bool(args.install_partial))
    started_at = time.perf_counter()
    print(
        "tile_land_stats starting: total_files={total_files} workers={workers} "
        "s2_root={s2_root} work_db={work_db} live_db={live_db} install_at_end={install} "
        "ocean_rgb=({r:.8f},{g:.8f},{b:.8f})".format(
            total_files=total_files,
            workers=workers,
            s2_root=s2_root,
            work_db=work_db_path,
            live_db=db_path,
            install=bool(install_at_end),
            r=float(S2_OCEAN_RGB[0]),
            g=float(S2_OCEAN_RGB[1]),
            b=float(S2_OCEAN_RGB[2]),
        ),
        flush=True,
    )

    def should_skip(tile_key: str) -> bool:
        if args.force:
            return False
        row = conn.execute(
            "SELECT 1 FROM tile_land_stats WHERE tile_key = ? AND source = 'S2' LIMIT 1",
            (tile_key,),
        ).fetchone()
        return bool(row)

    try:
        source_iter = iter(iter_source_files(s2_root, limit=max(0, int(args.limit or 0))))

        def next_work_item():
            nonlocal skipped
            for entry in source_iter:
                _path, tile_key, _x, _y, _z, _d = entry
                if only and tile_key not in only:
                    continue
                if should_skip(tile_key):
                    skipped += 1
                    continue
                return entry
            return None

        def commit_progress(force=False):
            if force or (processed and processed % commit_every == 0):
                conn.commit()
                elapsed = max(0.001, time.perf_counter() - started_at)
                handled = int(processed + skipped + failed)
                rate = (float(handled) / elapsed) * 60.0
                remaining = max(0, int(total_files) - handled)
                eta_seconds = (float(remaining) / (rate / 60.0)) if rate > 0.0 else 0.0
                percent = (float(handled) / float(total_files) * 100.0) if total_files > 0 else 0.0
                print(
                    "processed={processed} skipped={skipped} failed={failed} "
                    "handled={handled}/{total_files} ({percent:.2f}%) "
                    "rate={rate:.1f}/min eta={eta}".format(
                        processed=processed,
                        skipped=skipped,
                        failed=failed,
                        handled=handled,
                        total_files=total_files,
                        percent=percent,
                        rate=rate,
                        eta=format_duration(eta_seconds),
                    ),
                    flush=True,
                )

        if workers <= 1:
            while True:
                entry = next_work_item()
                if entry is None:
                    break
                try:
                    _path, tile_key, x, y, z, d, stats = process_source_entry(entry)
                    write_tile_stats(conn, tile_key, x, y, z, d, stats)
                    processed += 1
                except Exception as exc:
                    failed += 1
                    print(f"failed={failed}: {exc}", file=sys.stderr, flush=True)
                commit_progress()
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = set()
                exhausted = False

                def fill_queue():
                    nonlocal exhausted
                    while not exhausted and len(futures) < pending_limit:
                        entry = next_work_item()
                        if entry is None:
                            exhausted = True
                            break
                        futures.add(executor.submit(process_source_entry, entry))

                fill_queue()
                while futures:
                    done, futures = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        try:
                            _path, tile_key, x, y, z, d, stats = future.result()
                            write_tile_stats(conn, tile_key, x, y, z, d, stats)
                            processed += 1
                        except Exception as exc:
                            failed += 1
                            print(f"failed={failed}: {exc}", file=sys.stderr, flush=True)
                        commit_progress()
                    fill_queue()
        conn.commit()
    finally:
        conn.close()
    if failed == 0 and install_at_end:
        print(f"tile_land_stats installing complete stats into live DB: {db_path}", flush=True)
        installed = install_stats_to_live_db(work_db_path, db_path)
        print(f"tile_land_stats installed rows={installed}", flush=True)
    elif args.limit and not args.install_partial:
        print("tile_land_stats not installed because --limit was used.", flush=True)
    elapsed = time.perf_counter() - started_at
    print(
        f"tile_land_stats complete: processed={processed} skipped={skipped} failed={failed} elapsed={format_duration(elapsed)}"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
