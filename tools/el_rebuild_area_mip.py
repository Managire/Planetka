#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Iterable
from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np
import OpenEXR
import OpenImageIO as oiio

try:
    cv2.setLogLevel(0)
except TOOL_RECOVERABLE_EXCEPTIONS:
    pass


TILE_RE = re.compile(r"^EL_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.exr$", re.IGNORECASE)

Z_BUILD_ORDER = [2, 4, 8, 15, 16, 30, 32, 60, 90, 180, 360]
Z_2X2 = {2, 4, 8, 16, 30, 32, 60, 180}

ROOT_DIR: str = ""
BLACK_FALLBACK_PATH: str = ""
_BLACK_FALLBACK: np.ndarray | None = None
_D_LEVELS_BY_Z: dict[int, list[int]] = {}
SKIP_EXISTING: bool = False
MAX_TASK_RETRIES: int = 2


def _encode_d_for_name(d_effective: int) -> int:
    return 0 if int(d_effective) == 1440 else int(d_effective)


def _decode_d_from_name(d_code: int) -> int:
    return 1440 if int(d_code) == 0 else int(d_code)


def _tile_name(x: int, y: int, z: int, d_code: int) -> str:
    return f"EL_x{x:03d}_y{y:03d}_z{z:03d}_d{d_code:03d}.exr"


def _tile_path(x: int, y: int, z: int, d_code: int) -> str:
    return str(Path(ROOT_DIR) / _tile_name(x, y, z, d_code))


def _buf_has_error(buf) -> bool:
    flag = getattr(buf, "has_error", False)
    if callable(flag):
        try:
            return bool(flag())
        except TOOL_RECOVERABLE_EXCEPTIONS:
            return False
    return bool(flag)


def _read_image(path: str) -> np.ndarray:
    try:
        exr = OpenEXR.File(path)
        part = exr.parts[0]
        channels = part.channels
        if "R" in channels:
            image = np.asarray(channels["R"].pixels, dtype=np.float32)
        elif "RGB" in channels:
            array = np.asarray(channels["RGB"].pixels, dtype=np.float32)
            if array.ndim == 3:
                image = np.asarray(array[:, :, 0], dtype=np.float32)
            else:
                image = np.asarray(array, dtype=np.float32)
        elif all(name in channels for name in ("R", "G", "B")):
            image = np.asarray(channels["R"].pixels, dtype=np.float32)
        elif channels:
            first = next(iter(channels.keys()))
            image = np.asarray(channels[first].pixels, dtype=np.float32)
        else:
            raise RuntimeError(f"Unsupported EXR channels for {path}: {list(channels.keys())}")
        if image.ndim == 3:
            image = image[:, :, 0]
        if image.ndim != 2:
            raise RuntimeError(f"Unexpected EL shape for image {path}: {image.shape}")
    except TOOL_RECOVERABLE_EXCEPTIONS:
        image = None

    if image is None:
        buf = oiio.ImageBuf(path)
        if _buf_has_error(buf):
            raise RuntimeError(f"Failed to read image via OIIO: {path}: {buf.geterror()}")
        pixels = buf.get_pixels(oiio.FLOAT)
        array = np.asarray(pixels, dtype=np.float32)
        if array.ndim == 2:
            image = array
        elif array.ndim == 3 and array.shape[2] >= 1:
            image = array[:, :, 0]
        else:
            raise RuntimeError(f"Unexpected OIIO shape for image {path}: {array.shape}")

    if image is None:
        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Failed to read EL image {path}")
    if image.ndim == 3:
        image = image[:, :, 0]
    if image.ndim != 2:
        raise RuntimeError(f"Unexpected shape for image {path}: {None if image is None else image.shape}")
    if image.dtype != np.float32:
        image = image.astype(np.float32, copy=False)
    return image


def _write_exr(path: str, image_scalar: np.ndarray) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"

    image = image_scalar.astype(np.float32, copy=False)
    if image.ndim == 3:
        image = image[:, :, 0]
    if image.ndim != 2:
        raise RuntimeError(f"EL write expected 2D array, got {image.shape}")
    np.clip(image, 0.0, 1.0, out=image)
    image = image.astype(np.float16, copy=False)
    r = np.ascontiguousarray(image)

    header = {
        "compression": OpenEXR.ZIP_COMPRESSION,
        "type": OpenEXR.scanlineimage,
    }
    channels = {"R": r}
    try:
        with OpenEXR.File(header, channels) as out:
            out.write(tmp_path)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _get_black_fallback() -> np.ndarray:
    global _BLACK_FALLBACK
    if _BLACK_FALLBACK is None:
        _BLACK_FALLBACK = _read_image(BLACK_FALLBACK_PATH)
    return _BLACK_FALLBACK


def _resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    src_w = int(image.shape[1])
    src_h = int(image.shape[0])
    dst_w = int(width)
    dst_h = int(height)
    if src_w == dst_w and src_h == dst_h:
        return image
    if dst_w <= src_w and dst_h <= src_h and (dst_w < src_w or dst_h < src_h):
        interp = cv2.INTER_AREA
    else:
        interp = cv2.INTER_LINEAR
    return cv2.resize(image, (dst_w, dst_h), interpolation=interp)


def _wrap_x(x: int) -> int:
    return int(x) % 360


def _read_or_fallback(x: int, y: int, z: int, d_effective: int) -> np.ndarray:
    xw = _wrap_x(x)
    d_code = _encode_d_for_name(d_effective)
    path = _tile_path(xw, int(y), int(z), int(d_code))
    if os.path.isfile(path):
        return _read_image(path)
    return _get_black_fallback()


def _x_size_for_z15(y: int) -> int:
    if y in (0, 165):
        return 2889 // 15
    if y in (15, 150):
        return 5742 // 15
    if y in (30, 135):
        return 8010 // 15
    if y in (45, 120):
        return 9738 // 15
    if y in (60, 105):
        return 10809 // 15
    if y in (75, 90):
        return 11133 // 15
    return 11133 // 15


def _build_z_base(task: tuple[int, int, int]) -> tuple[bool, str]:
    x, y, z = task
    try:
        dst = _tile_path(x, y, z, _encode_d_for_name(z))
        os.makedirs(os.path.dirname(dst), exist_ok=True)

        if SKIP_EXISTING and os.path.isfile(dst):
            try:
                _read_image(dst)
                return True, ""
            except TOOL_RECOVERABLE_EXCEPTIONS:
                try:
                    os.unlink(dst)
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass

        if z in Z_2X2:
            child_z = z // 2
            image1 = _read_or_fallback(x, y, child_z, child_z)
            image2 = _read_or_fallback(x + child_z, y, child_z, child_z)
            image3 = _read_or_fallback(x, y + child_z, child_z, child_z)
            image4 = _read_or_fallback(x + child_z, y + child_z, child_z, child_z)

            x_size = max(image1.shape[1], image2.shape[1], image3.shape[1], image4.shape[1])
            y_size = max(image1.shape[0], image2.shape[0], image3.shape[0], image4.shape[0])
            new_im = np.zeros((y_size * 2, x_size * 2), dtype=np.float32)

            new_im[y_size : y_size * 2, 0:x_size] = _resize(image1, x_size, y_size)
            new_im[y_size : y_size * 2, x_size : x_size * 2] = _resize(image2, x_size, y_size)
            new_im[0:y_size, 0:x_size] = _resize(image3, x_size, y_size)
            new_im[0:y_size, x_size : x_size * 2] = _resize(image4, x_size, y_size)

            new_im = cv2.resize(new_im, (x_size, y_size), interpolation=cv2.INTER_AREA)
            _write_exr(dst, new_im)
            return True, ""

        if z == 15:
            y_size = 11133 // 15
            x_size = _x_size_for_z15(y)
            new_im = np.zeros((y_size * 15, x_size * 15), dtype=np.float32)
            for y_coord in range(15):
                for x_coord in range(15):
                    image = _read_or_fallback(x + x_coord, y + y_coord, 1, 1)
                    ys = (14 - y_coord) * y_size
                    xs = x_coord * x_size
                    new_im[ys : ys + y_size, xs : xs + x_size] = _resize(image, x_size, y_size)
            _write_exr(dst, new_im)
            return True, ""

        if z == 90:
            y_size = x_size = 11133 // 3
            new_im = np.zeros((11133, 11133), dtype=np.float32)
            for y_coord in range(3):
                for x_coord in range(3):
                    image = _read_or_fallback(x + x_coord * 30, y + y_coord * 30, 30, 30)
                    ys = (2 - y_coord) * y_size
                    xs = x_coord * x_size
                    new_im[ys : ys + y_size, xs : xs + x_size] = _resize(image, x_size, y_size)
            _write_exr(dst, new_im)
            return True, ""

        if z == 360:
            x_size = 11133
            y_size = 11133
            new_im = np.zeros((11133, 11133 * 2), dtype=np.float32)
            image1 = _read_or_fallback(0, 0, 180, 180)
            image2 = _read_or_fallback(180, 0, 180, 180)
            new_im[0:11133, 0:11133] = _resize(image1, x_size, y_size)
            new_im[0:11133, 11133 : 11133 * 2] = _resize(image2, x_size, y_size)
            new_im = cv2.resize(new_im, (x_size, y_size // 2), interpolation=cv2.INTER_AREA)
            _write_exr(dst, new_im)
            return True, ""

        return False, f"Unsupported z build level: {z}"
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
        return False, f"{_tile_name(x, y, z, _encode_d_for_name(z))}: {exc}"


def _select_prev_mip_source(x: int, y: int, z: int, d_effective: int) -> tuple[int, str | None]:
    levels = sorted(set(_D_LEVELS_BY_Z.get(int(z), [int(z)])))
    lower = [int(lv) for lv in levels if int(lv) < int(d_effective)]
    predecessor = int(lower[-1]) if lower else int(z)
    src = _tile_path(x, y, z, _encode_d_for_name(predecessor))
    if os.path.isfile(src):
        return predecessor, src
    return predecessor, None


def _rebuild_d_variant(task: tuple[int, int, int, int]) -> tuple[bool, str]:
    x, y, z, d_code = task
    d_effective = _decode_d_from_name(d_code)
    dst = _tile_path(x, y, z, d_code)

    if SKIP_EXISTING and os.path.isfile(dst):
        try:
            _read_image(dst)
            return True, ""
        except TOOL_RECOVERABLE_EXCEPTIONS:
            try:
                os.unlink(dst)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    last_err = ""
    for attempt in range(max(0, int(MAX_TASK_RETRIES)) + 1):
        try:
            prev_level, src = _select_prev_mip_source(x, y, z, d_effective)
            if src is None:
                return False, f"Missing source for d rebuild: z={z} d={d_effective} at x={x} y={y}"
            image = _read_image(src)
            src_h, src_w = image.shape[0], image.shape[1]
            scale = float(prev_level) / float(d_effective)
            dst_w = max(1, int(round(float(src_w) * scale)))
            dst_h = max(1, int(round(float(src_h) * scale)))
            out = _resize(image, dst_w, dst_h)
            _write_exr(dst, out)
            return True, ""
        except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
            last_err = str(exc)
            if attempt >= int(MAX_TASK_RETRIES):
                break
            time.sleep(0.2 * float(attempt + 1))
    return False, f"{_tile_name(x, y, z, d_code)}: {last_err}"


def _run_stage(
    label: str,
    tasks: Iterable,
    worker_count: int,
    worker_fn,
    progress_every: int = 100,
    chunksize: int = 8,
) -> tuple[int, int]:
    tasks = list(tasks)
    total = len(tasks)
    if total == 0:
        print(f"[{label}] no tasks")
        return 0, 0

    start = time.perf_counter()
    done = 0
    failed = 0
    print(f"[{label}] start tasks={total} workers={worker_count}")

    if worker_count <= 1:
        for task in tasks:
            ok, err = worker_fn(task)
            done += 1
            if not ok:
                failed += 1
                print(f"[{label}] FAIL {err}")
            if done % progress_every == 0 or done == total:
                elapsed = time.perf_counter() - start
                print(f"[{label}] progress {done}/{total} failed={failed} elapsed={elapsed:.1f}s")
    else:
        with Pool(
            processes=worker_count,
            maxtasksperchild=500,
            initializer=_init_worker_globals,
            initargs=(ROOT_DIR, BLACK_FALLBACK_PATH, _D_LEVELS_BY_Z, SKIP_EXISTING, MAX_TASK_RETRIES),
        ) as pool:
            for ok, err in pool.imap_unordered(worker_fn, tasks, chunksize=max(1, int(chunksize))):
                done += 1
                if not ok:
                    failed += 1
                    print(f"[{label}] FAIL {err}")
                if done % progress_every == 0 or done == total:
                    elapsed = time.perf_counter() - start
                    print(f"[{label}] progress {done}/{total} failed={failed} elapsed={elapsed:.1f}s")

    elapsed = time.perf_counter() - start
    print(f"[{label}] done total={total} failed={failed} elapsed={elapsed:.1f}s")
    return total, failed


def _init_worker_globals(
    root_dir: str,
    black_fallback: str,
    d_levels_by_z: dict[int, list[int]] | None = None,
    skip_existing: bool = False,
    max_task_retries: int = 2,
) -> None:
    global ROOT_DIR, BLACK_FALLBACK_PATH, _BLACK_FALLBACK, _D_LEVELS_BY_Z, SKIP_EXISTING, MAX_TASK_RETRIES
    ROOT_DIR = str(root_dir or "")
    BLACK_FALLBACK_PATH = str(black_fallback or "")
    _D_LEVELS_BY_Z = dict(d_levels_by_z or {})
    SKIP_EXISTING = bool(skip_existing)
    MAX_TASK_RETRIES = max(0, int(max_task_retries))
    _BLACK_FALLBACK = None


def _collect_manifest(
    manifest_root: Path,
    older_than_hours: float = 0.0,
) -> tuple[
    dict[int, list[tuple[int, int]]],
    dict[int, list[tuple[int, int, int, int]]],
]:
    z_base_coords: dict[int, set[tuple[int, int]]] = defaultdict(set)
    d_tasks_by_z: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)
    cutoff_mtime: float | None = None
    if float(older_than_hours) > 0.0:
        cutoff_mtime = time.time() - (float(older_than_hours) * 3600.0)

    with os.scandir(manifest_root) as it:
        for entry in it:
            if not entry.is_file():
                continue
            match = TILE_RE.match(entry.name)
            if not match:
                continue
            x = int(match.group("x"))
            y = int(match.group("y"))
            z = int(match.group("z"))
            d_code = int(match.group("d"))
            d_effective = _decode_d_from_name(d_code)
            if cutoff_mtime is not None:
                try:
                    mtime = float(entry.stat(follow_symlinks=False).st_mtime)
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    mtime = 0.0
                if mtime >= cutoff_mtime:
                    continue

            if z > 1 and d_effective == z:
                z_base_coords[z].add((x, y))
                continue
            if z >= 1 and d_effective > z:
                d_tasks_by_z[z].append((x, y, z, d_code))

    z_base_list: dict[int, list[tuple[int, int]]] = {
        z: sorted(coords, key=lambda p: (p[1], p[0])) for z, coords in z_base_coords.items()
    }
    for z in list(d_tasks_by_z.keys()):
        d_tasks_by_z[z] = sorted(d_tasks_by_z[z], key=lambda t: (t[1], t[0], t[3]))

    return z_base_list, d_tasks_by_z


def _build_d_levels_by_z(
    z_base_list: dict[int, list[tuple[int, int]]],
    d_tasks_by_z: dict[int, list[tuple[int, int, int, int]]],
) -> dict[int, list[int]]:
    levels: dict[int, set[int]] = defaultdict(set)
    for z in z_base_list.keys():
        levels[int(z)].add(int(z))
    for z, tasks in d_tasks_by_z.items():
        z_int = int(z)
        levels[z_int].add(z_int)
        for _, _, _, d_code in tasks:
            levels[z_int].add(_decode_d_from_name(int(d_code)))
    return {z: sorted(vals) for z, vals in levels.items()}


def _group_d_tasks_by_effective(
    d_tasks: list[tuple[int, int, int, int]]
) -> list[tuple[int, list[tuple[int, int, int, int]]]]:
    groups: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)
    for task in d_tasks:
        groups[_decode_d_from_name(task[3])].append(task)
    out: list[tuple[int, list[tuple[int, int, int, int]]]] = []
    for d_effective in sorted(groups.keys()):
        out.append((d_effective, sorted(groups[d_effective], key=lambda t: (t[1], t[0], t[3]))))
    return out


def _workers_for_z(max_workers: int, z: int) -> int:
    if z >= 180:
        return 1
    if z >= 90:
        return min(2, max_workers)
    if z >= 60:
        return min(4, max_workers)
    return max_workers


def _parse_int_set(text: str) -> set[int]:
    out: set[int] = set()
    for part in str(text or "").split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild EL higher-z and higher-d in place using area/box downsampling, "
            "strict mip predecessor sourcing, and black fallback for missing tiles."
        )
    )
    parser.add_argument("--root", default="/Volumes/SSDA/Planetka Assets/EL", help="EL dataset folder")
    parser.add_argument("--manifest-root", default="", help="Folder used only to enumerate expected EL filenames")
    parser.add_argument(
        "--black-fallback",
        default="/Volumes/SSDA/Planetka Assets Extra/FB/black_pixel_20.exr",
        help="Black fallback EXR for missing EL source tiles",
    )
    parser.add_argument("--workers", type=int, default=8, help="Max workers")
    parser.add_argument("--resume-existing", action="store_true", help="Skip already valid destination files")
    parser.add_argument("--task-retries", type=int, default=2, help="Retry count per task")
    parser.add_argument("--skip-z-rebuild", action="store_true", help="Skip z=z rebuild stage")
    parser.add_argument("--skip-d-rebuild", action="store_true", help="Skip d rebuild stage")
    parser.add_argument("--only-z", default="", help="Optional comma-separated z levels")
    parser.add_argument("--only-d-effective", default="", help="Optional comma-separated effective d levels")
    parser.add_argument(
        "--older-than-hours",
        type=float,
        default=0.0,
        help="Only rebuild outputs older than this many hours (0 disables age filter)",
    )
    parser.add_argument("--limit-z-per-level", type=int, default=0)
    parser.add_argument("--limit-d-per-level", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(args.root).expanduser().resolve()
    manifest_root = Path(args.manifest_root).expanduser().resolve() if str(args.manifest_root).strip() else root

    if not root.is_dir():
        print(f"EL root not found: {root}")
        return 2
    if not manifest_root.is_dir():
        print(f"EL manifest root not found: {manifest_root}")
        return 2
    if not Path(args.black_fallback).is_file():
        print(f"Black fallback missing: {args.black_fallback}")
        return 2

    global ROOT_DIR, BLACK_FALLBACK_PATH, _D_LEVELS_BY_Z, SKIP_EXISTING, MAX_TASK_RETRIES
    ROOT_DIR = str(root)
    BLACK_FALLBACK_PATH = str(Path(args.black_fallback).expanduser().resolve())
    SKIP_EXISTING = bool(args.resume_existing)
    MAX_TASK_RETRIES = max(0, int(args.task_retries))

    max_workers = max(1, min(int(args.workers), 16))
    started = time.perf_counter()
    print(
        f"EL rebuild start root={ROOT_DIR} manifest={manifest_root} max_workers={max_workers} "
        f"resume_existing={SKIP_EXISTING} task_retries={MAX_TASK_RETRIES}"
    )

    z_base_list, d_tasks_by_z = _collect_manifest(manifest_root, older_than_hours=float(args.older_than_hours))

    only_z = _parse_int_set(args.only_z)
    if only_z:
        z_base_list = {z: tasks for z, tasks in z_base_list.items() if int(z) in only_z}
        d_tasks_by_z = {z: tasks for z, tasks in d_tasks_by_z.items() if int(z) in only_z}

    only_d = _parse_int_set(args.only_d_effective)
    if only_d:
        filtered: dict[int, list[tuple[int, int, int, int]]] = {}
        for z, tasks in d_tasks_by_z.items():
            kept = [t for t in tasks if _decode_d_from_name(int(t[3])) in only_d]
            if kept:
                filtered[z] = kept
        d_tasks_by_z = filtered

    if int(args.limit_z_per_level) > 0:
        for z in list(z_base_list.keys()):
            z_base_list[z] = z_base_list[z][: int(args.limit_z_per_level)]
    if int(args.limit_d_per_level) > 0:
        for z in list(d_tasks_by_z.keys()):
            d_tasks_by_z[z] = d_tasks_by_z[z][: int(args.limit_d_per_level)]

    _D_LEVELS_BY_Z = _build_d_levels_by_z(z_base_list, d_tasks_by_z)

    print(
        f"manifest z_bases={sum(len(v) for v in z_base_list.values())} "
        f"d_targets={sum(len(v) for v in d_tasks_by_z.values())}"
    )
    if float(args.older_than_hours) > 0.0:
        print(f"age filter: older_than_hours={float(args.older_than_hours):.2f}")

    failures = 0

    if not args.skip_z_rebuild:
        for z in Z_BUILD_ORDER:
            coords = z_base_list.get(z, [])
            tasks = [(x, y, z) for x, y in coords]
            workers = _workers_for_z(max_workers, z)
            _, failed = _run_stage(f"rebuild-z{z:03d}", tasks, workers, _build_z_base, progress_every=25, chunksize=4)
            failures += failed

    if not args.skip_d_rebuild:
        for z in sorted(d_tasks_by_z.keys()):
            workers = _workers_for_z(max_workers, z)
            for d_effective, tasks in _group_d_tasks_by_effective(d_tasks_by_z[z]):
                _, failed = _run_stage(
                    f"rebuild-d-z{z:03d}-d{_encode_d_for_name(d_effective):03d}",
                    tasks,
                    workers,
                    _rebuild_d_variant,
                    progress_every=100,
                    chunksize=16,
                )
                failures += failed

    elapsed = time.perf_counter() - started
    print(f"EL rebuild finished failures={failures} elapsed={elapsed:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
