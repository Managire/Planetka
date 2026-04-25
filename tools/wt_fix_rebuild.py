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
import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

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


TILE_RE = re.compile(
    r"^WT_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.exr$",
    re.IGNORECASE,
)

Z_BUILD_ORDER = [2, 4, 8, 15, 16, 30, 32, 60, 90, 180, 360]
Z_2X2 = {2, 4, 8, 16, 30, 32, 60, 180}

FIX_RATIO = 3601.0 / 11133.0

CASPIAN_REGION = (226, 236, 125, 139)
SUPERIOR_REGION = (86, 98, 134, 142)
PACIFIC_BLUE_REGION = (46, 55, 125, 140)
ANTARCTICA_TARGET_REGION = (0, 359, 9, 15)

OUT_ROOT: str = ""
BLUE_FALLBACK_PATH: str = ""
RED_FALLBACK_PATH: str = ""
BLACK_FALLBACK_PATH: str = ""
_BLUE_FALLBACK: np.ndarray | None = None
_RED_FALLBACK: np.ndarray | None = None
_BLACK_FALLBACK: np.ndarray | None = None
_D_LEVELS_BY_Z: dict[int, list[int]] = {}
SKIP_EXISTING: bool = False
MAX_TASK_RETRIES: int = 2


def _encode_d_for_name(d_effective: int) -> int:
    return 0 if int(d_effective) == 1440 else int(d_effective)


def _decode_d_from_name(d_code: int) -> int:
    return 1440 if int(d_code) == 0 else int(d_code)


def _tile_name(x: int, y: int, z: int, d_code: int) -> str:
    return f"WT_x{x:03d}_y{y:03d}_z{z:03d}_d{d_code:03d}.exr"


def _tile_path(x: int, y: int, z: int, d_code: int) -> str:
    return str(Path(OUT_ROOT) / _tile_name(x, y, z, d_code))


def _read_image(path: str) -> np.ndarray:
    try:
        exr = OpenEXR.File(path)
        part = exr.parts[0]
        channels = part.channels
        if "RGB" in channels:
            array = np.asarray(channels["RGB"].pixels, dtype=np.float32)
        elif all(name in channels for name in ("R", "G", "B")):
            r = np.asarray(channels["R"].pixels, dtype=np.float32)
            g = np.asarray(channels["G"].pixels, dtype=np.float32)
            b = np.asarray(channels["B"].pixels, dtype=np.float32)
            array = np.stack((r, g, b), axis=2)
        else:
            raise RuntimeError(f"Unsupported EXR channels for {path}: {list(channels.keys())}")
        if array.ndim == 2:
            array = np.repeat(array[:, :, None], 3, axis=2)
        if array.ndim != 3 or array.shape[2] < 3:
            raise RuntimeError(f"Unexpected shape for image {path}: {array.shape}")
        if array.shape[2] > 3:
            array = array[:, :, :3]
        image = array[:, :, [2, 1, 0]]
    except TOOL_RECOVERABLE_EXCEPTIONS:
        image = None

    if image is None:
        buf = oiio.ImageBuf(path)
        if buf.has_error():
            raise RuntimeError(f"Failed to read image via OIIO: {path}: {buf.geterror()}")
        pixels = buf.get_pixels(oiio.FLOAT)
        array = np.asarray(pixels, dtype=np.float32)
        if array.ndim != 3 or array.shape[2] < 3:
            raise RuntimeError(f"Unexpected OIIO shape for image {path}: {array.shape}")
        image = array[:, :, :3][:, :, [2, 1, 0]]

    if image is None:
        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        raise RuntimeError(f"Unexpected shape for image {path}: {None if image is None else image.shape}")
    if image.shape[2] > 3:
        image = image[:, :, :3]
    if image.dtype != np.float32:
        image = image.astype(np.float32, copy=False)
    return image


def _write_wt_exr(path: str, image_bgr: np.ndarray) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    image = image_bgr.astype(np.float32, copy=False)
    np.clip(image, 0.0, 1.0, out=image)
    image = image.astype(np.float16, copy=False)
    rgb = np.empty((image.shape[0], image.shape[1], 3), dtype=np.float16)
    rgb[:, :, 0] = image[:, :, 2]
    rgb[:, :, 1] = image[:, :, 1]
    rgb[:, :, 2] = image[:, :, 0]
    rgb = np.ascontiguousarray(rgb)
    header = {
        "compression": OpenEXR.ZIP_COMPRESSION,
        "type": OpenEXR.scanlineimage,
    }
    channels = {"RGB": rgb}
    try:
        with OpenEXR.File(header, channels) as out:
            out.write(tmp_path)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _get_blue_fallback() -> np.ndarray:
    global _BLUE_FALLBACK
    if _BLUE_FALLBACK is None:
        _BLUE_FALLBACK = _read_image(BLUE_FALLBACK_PATH)
    return _BLUE_FALLBACK


def _get_red_fallback() -> np.ndarray:
    global _RED_FALLBACK
    if _RED_FALLBACK is None:
        _RED_FALLBACK = _read_image(RED_FALLBACK_PATH)
    return _RED_FALLBACK


def _get_black_fallback() -> np.ndarray:
    global _BLACK_FALLBACK
    if _BLACK_FALLBACK is None:
        _BLACK_FALLBACK = _read_image(BLACK_FALLBACK_PATH)
    return _BLACK_FALLBACK


def _resize(image: np.ndarray, width: int, height: int, force_linear: bool = False) -> np.ndarray:
    if image.shape[1] == int(width) and image.shape[0] == int(height):
        return image
    src_w = int(image.shape[1])
    src_h = int(image.shape[0])
    dst_w = int(width)
    dst_h = int(height)
    if force_linear:
        interp = cv2.INTER_LINEAR
    elif dst_w <= src_w and dst_h <= src_h and (dst_w < src_w or dst_h < src_h):
        interp = cv2.INTER_AREA
    else:
        interp = cv2.INTER_LINEAR
    return cv2.resize(image, (dst_w, dst_h), interpolation=interp)


def _wrap_x(x: int) -> int:
    return int(x) % 360


def _tile_x_ranges(x: int, z: int) -> list[tuple[float, float]]:
    x0 = float(_wrap_x(x))
    x1 = x0 + float(z)
    if x1 <= 360.0:
        return [(x0, x1)]
    return [(x0, 360.0), (0.0, x1 - 360.0)]


def _intersects_1d(a0: float, a1: float, b0: float, b1: float) -> bool:
    return max(a0, b0) < min(a1, b1)


def _tile_intersects_region(x: int, y: int, z: int, rx0: int, rx1: int, ry0: int, ry1: int) -> bool:
    # Regions are inclusive tile-index ranges.
    region_x0 = float(rx0)
    region_x1 = float(rx1 + 1)
    region_y0 = float(ry0)
    region_y1 = float(ry1 + 1)
    tile_y0 = float(y)
    tile_y1 = float(y + z)
    if not _intersects_1d(tile_y0, tile_y1, region_y0, region_y1):
        return False
    for tx0, tx1 in _tile_x_ranges(x, z):
        if _intersects_1d(tx0, tx1, region_x0, region_x1):
            return True
    return False


def _is_caspian_or_superior_region(x: int, y: int, z: int) -> bool:
    # Explicit tile-index regions:
    # - Caspian Sea: around x226-x236, y125-y139
    # - Lake Superior: around x086-x098, y134-y142
    red_regions = (
        CASPIAN_REGION,
        SUPERIOR_REGION,
    )
    for rx0, rx1, ry0, ry1 in red_regions:
        if _tile_intersects_region(x, y, z, rx0, rx1, ry0, ry1):
            return True
    return False


def _is_forced_blue_region(x: int, y: int, z: int) -> bool:
    # Pacific override requested by user.
    return _tile_intersects_region(x, y, z, *PACIFIC_BLUE_REGION)


def _select_fallback(x: int, y: int, z: int) -> np.ndarray:
    # Antarctica override: only y <= 9 uses black fallback.
    if int(y) <= 9:
        return _get_black_fallback()
    # Pacific override wins before lake-red regions.
    if _is_forced_blue_region(x, y, z):
        return _get_blue_fallback()
    if _is_caspian_or_superior_region(x, y, z):
        return _get_red_fallback()
    return _get_blue_fallback()


def _read_or_fallback(x: int, y: int, z: int, d_effective: int) -> np.ndarray:
    xw = _wrap_x(x)
    d_code = _encode_d_for_name(d_effective)
    path = _tile_path(xw, int(y), int(z), int(d_code))
    if os.path.isfile(path):
        return _read_image(path)
    return _select_fallback(xw, int(y), int(z))


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


def _fix_z001(task: tuple[str, str]) -> tuple[bool, str]:
    src_path, dst_path = task
    try:
        image = _read_image(src_path)
        src_h, src_w = int(image.shape[0]), int(image.shape[1])
        down_w = max(1, int(round(float(src_w) * FIX_RATIO)))
        down_h = max(1, int(round(float(src_h) * FIX_RATIO)))
        down = _resize(image, down_w, down_h)
        out = _resize(down, src_w, src_h)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        _write_wt_exr(dst_path, out)
        return True, ""
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
        return False, f"{src_path}: {exc}"


def _build_z_base(task: tuple[int, int, int]) -> tuple[bool, str]:
    x, y, z = task
    try:
        dst = _tile_path(x, y, z, _encode_d_for_name(z))
        os.makedirs(os.path.dirname(dst), exist_ok=True)

        if z in Z_2X2:
            child_z = z // 2
            image1 = _read_or_fallback(x, y, child_z, child_z)
            image2 = _read_or_fallback(x + child_z, y, child_z, child_z)
            image3 = _read_or_fallback(x, y + child_z, child_z, child_z)
            image4 = _read_or_fallback(x + child_z, y + child_z, child_z, child_z)

            x_size = max(image1.shape[1], image2.shape[1], image3.shape[1], image4.shape[1])
            y_size = max(image1.shape[0], image2.shape[0], image3.shape[0], image4.shape[0])
            new_im = np.zeros((y_size * 2, x_size * 2, 3), dtype=np.float32)

            new_im[y_size : y_size * 2, 0:x_size] = _resize(image1, x_size, y_size, force_linear=True)
            new_im[y_size : y_size * 2, x_size : x_size * 2] = _resize(image2, x_size, y_size, force_linear=True)
            new_im[0:y_size, 0:x_size] = _resize(image3, x_size, y_size, force_linear=True)
            new_im[0:y_size, x_size : x_size * 2] = _resize(image4, x_size, y_size, force_linear=True)

            new_im = cv2.resize(new_im, (x_size, y_size), interpolation=cv2.INTER_LINEAR)
            _write_wt_exr(dst, new_im)
            return True, ""

        if z == 15:
            y_size = 11133 // 15
            x_size = _x_size_for_z15(y)
            new_im = np.zeros((y_size * 15, x_size * 15, 3), dtype=np.float32)
            for y_coord in range(15):
                for x_coord in range(15):
                    image = _read_or_fallback(x + x_coord, y + y_coord, 1, 1)
                    ys = (14 - y_coord) * y_size
                    xs = x_coord * x_size
                    new_im[ys : ys + y_size, xs : xs + x_size] = _resize(image, x_size, y_size, force_linear=True)
            _write_wt_exr(dst, new_im)
            return True, ""

        if z == 90:
            y_size = x_size = 11133 // 3
            new_im = np.zeros((11133, 11133, 3), dtype=np.float32)
            for y_coord in range(3):
                for x_coord in range(3):
                    image = _read_or_fallback(x + x_coord * 30, y + y_coord * 30, 30, 30)
                    ys = (2 - y_coord) * y_size
                    xs = x_coord * x_size
                    new_im[ys : ys + y_size, xs : xs + x_size] = _resize(image, x_size, y_size, force_linear=True)
            _write_wt_exr(dst, new_im)
            return True, ""

        if z == 360:
            x_size = 11133
            y_size = 11133
            new_im = np.zeros((11133, 11133 * 2, 3), dtype=np.float32)
            image1 = _read_or_fallback(0, 0, 180, 180)
            image2 = _read_or_fallback(180, 0, 180, 180)
            new_im[0:11133, 0:11133] = _resize(image1, x_size, y_size, force_linear=True)
            new_im[0:11133, 11133 : 11133 * 2] = _resize(image2, x_size, y_size, force_linear=True)
            new_im = cv2.resize(new_im, (x_size, y_size // 2), interpolation=cv2.INTER_LINEAR)
            _write_wt_exr(dst, new_im)
            return True, ""

        return False, f"Unsupported z build level: {z}"
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
        return False, f"{_tile_name(x, y, z, _encode_d_for_name(z))}: {exc}"


def _select_prev_mip_source(x: int, y: int, z: int, d_effective: int) -> tuple[int, str | None]:
    # Prefer the true one-step mip predecessor (d/2) when available.
    # If that file is missing for this tile, fall back to the highest
    # lower existing level for this tile (sparse-manifest safety).
    z_int = int(z)
    d_int = int(d_effective)
    levels = sorted(set(_D_LEVELS_BY_Z.get(z_int, [z_int])))
    lower_levels = [int(lv) for lv in levels if int(lv) < d_int]
    if not lower_levels:
        lower_levels = [z_int]

    preferred: list[int] = []
    if d_int % 2 == 0:
        half = d_int // 2
        if half in lower_levels:
            preferred.append(half)

    # If half-level is not present (or missing for this tile), try other
    # lower levels from highest to lowest.
    for lv in sorted(lower_levels, reverse=True):
        if lv not in preferred:
            preferred.append(lv)

    for predecessor in preferred:
        src = _tile_path(x, y, z_int, _encode_d_for_name(predecessor))
        if os.path.isfile(src):
            return int(predecessor), src

    return int(preferred[0]), None


def _rebuild_d_variant(task: tuple[int, int, int, int]) -> tuple[bool, str]:
    x, y, z, d_code = task
    d_effective = _decode_d_from_name(d_code)
    dst = _tile_path(x, y, z, d_code)
    if SKIP_EXISTING and os.path.isfile(dst):
        try:
            _read_image(dst)
            return True, ""
        except TOOL_RECOVERABLE_EXCEPTIONS:
            # Corrupted/partial file: force rebuild.
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
            out = _resize(image, dst_w, dst_h, force_linear=True)
            _write_wt_exr(dst, out)
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
    chunksize: int = 1,
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
            maxtasksperchild=None,
            initializer=_init_worker_globals,
            initargs=(
                OUT_ROOT,
                BLUE_FALLBACK_PATH,
                RED_FALLBACK_PATH,
                BLACK_FALLBACK_PATH,
                _D_LEVELS_BY_Z,
                SKIP_EXISTING,
                MAX_TASK_RETRIES,
            ),
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
    out_root: str,
    blue_fallback: str,
    red_fallback: str,
    black_fallback: str,
    d_levels_by_z: dict[int, list[int]] | None = None,
    skip_existing: bool = False,
    max_task_retries: int = 2,
) -> None:
    global OUT_ROOT, BLUE_FALLBACK_PATH, RED_FALLBACK_PATH, BLACK_FALLBACK_PATH
    global _BLUE_FALLBACK, _RED_FALLBACK, _BLACK_FALLBACK, _D_LEVELS_BY_Z, SKIP_EXISTING, MAX_TASK_RETRIES
    OUT_ROOT = str(out_root or "")
    BLUE_FALLBACK_PATH = str(blue_fallback or "")
    RED_FALLBACK_PATH = str(red_fallback or "")
    BLACK_FALLBACK_PATH = str(black_fallback or "")
    _D_LEVELS_BY_Z = dict(d_levels_by_z or {})
    SKIP_EXISTING = bool(skip_existing)
    MAX_TASK_RETRIES = max(0, int(max_task_retries))
    _BLUE_FALLBACK = None
    _RED_FALLBACK = None
    _BLACK_FALLBACK = None


def _collect_manifest(
    manifest_root: Path,
    source_root: Path,
    output_root: Path,
) -> tuple[
    list[tuple[str, str]],
    dict[int, list[tuple[int, int]]],
    dict[int, list[tuple[int, int, int, int]]],
]:
    z001_tasks: list[tuple[str, str]] = []
    z_base_coords: dict[int, set[tuple[int, int]]] = defaultdict(set)
    d_tasks_by_z: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)

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

            if z == 1 and d_effective == 1:
                src = source_root / entry.name
                dst = output_root / entry.name
                z001_tasks.append((str(src), str(dst)))
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

    z001_tasks = sorted(z001_tasks, key=lambda t: Path(t[0]).name)
    return z001_tasks, z_base_list, d_tasks_by_z


def _workers_for_z(max_workers: int, z: int) -> int:
    if z >= 180:
        return 1
    if z >= 90:
        return min(2, max_workers)
    if z >= 60:
        return min(4, max_workers)
    return max_workers


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


def _task_intersects_requested_regions(x: int, y: int, z: int) -> bool:
    regions = (
        CASPIAN_REGION,
        SUPERIOR_REGION,
        PACIFIC_BLUE_REGION,
        ANTARCTICA_TARGET_REGION,
    )
    for rx0, rx1, ry0, ry1 in regions:
        if _tile_intersects_region(x, y, z, rx0, rx1, ry0, ry1):
            return True
    return False


def _child_requirements_for_z_task(x: int, y: int, z: int) -> list[tuple[int, int, int, int]]:
    specs: list[tuple[int, int, int, int]] = []
    if z in Z_2X2:
        child_z = z // 2
        specs.extend(
            [
                (x, y, child_z, child_z),
                (x + child_z, y, child_z, child_z),
                (x, y + child_z, child_z, child_z),
                (x + child_z, y + child_z, child_z, child_z),
            ]
        )
        return specs
    if z == 15:
        for y_coord in range(15):
            for x_coord in range(15):
                specs.append((x + x_coord, y + y_coord, 1, 1))
        return specs
    if z == 90:
        for y_coord in range(3):
            for x_coord in range(3):
                specs.append((x + x_coord * 30, y + y_coord * 30, 30, 30))
        return specs
    if z == 360:
        return [(0, 0, 180, 180), (180, 0, 180, 180)]
    return specs


def _z_task_would_use_fallback(x: int, y: int, z: int) -> bool:
    for cx, cy, cz, cd_effective in _child_requirements_for_z_task(x, y, z):
        d_code = _encode_d_for_name(cd_effective)
        path = _tile_path(_wrap_x(cx), int(cy), int(cz), int(d_code))
        if not os.path.isfile(path):
            return True
    return False


def _filter_targeted_z_tasks(
    z_base_list: dict[int, list[tuple[int, int]]]
) -> dict[int, list[tuple[int, int]]]:
    filtered: dict[int, list[tuple[int, int]]] = {}
    for z, coords in sorted(z_base_list.items()):
        kept: list[tuple[int, int]] = []
        intersects_count = 0
        fallback_count = 0
        for x, y in coords:
            if not _task_intersects_requested_regions(x, y, z):
                continue
            intersects_count += 1
            # Requested behavior:
            # - z002: rebuild only region-intersecting tiles that would use fallback.
            # - z004 and higher: rebuild all region-intersecting tiles, regardless of fallback.
            if int(z) == 2:
                if not _z_task_would_use_fallback(x, y, z):
                    continue
                fallback_count += 1
            kept.append((x, y))
        filtered[z] = kept
        if int(z) == 2:
            print(
                f"[targeted-z] z={z:03d} selected={len(kept)} "
                f"intersects={intersects_count} fallback={fallback_count} total={len(coords)}"
            )
        else:
            print(
                f"[targeted-z] z={z:03d} selected={len(kept)} "
                f"intersects={intersects_count} total={len(coords)}"
            )
    return filtered


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fix WT z001_d001 with 3601/11133 area->linear resampling and rebuild higher z/d variants "
            "using linear/area interpolation and WT fallback policy."
        )
    )
    parser.add_argument(
        "--source-root",
        default="/Volumes/SSDA/Planetka Assets/WT",
        help="WT source folder containing original dataset.",
    )
    parser.add_argument(
        "--root",
        default="/Volumes/SSDA/WT-fixed",
        help="WT output folder (new rebuilt dataset).",
    )
    parser.add_argument(
        "--manifest-root",
        default="",
        help="Folder used only to enumerate expected WT filenames. Defaults to --source-root.",
    )
    parser.add_argument(
        "--blue-fallback",
        default="/Volumes/SSDA/Planetka Assets Extra/FB/blue_pixel_20.exr",
        help="Default WT fallback EXR (ocean).",
    )
    parser.add_argument(
        "--red-fallback",
        default="/Volumes/SSDA/Planetka Assets Extra/FB/red_pixel_20.exr",
        help="WT fallback EXR for lake regions (Caspian + Superior).",
    )
    parser.add_argument(
        "--black-fallback",
        default="/Volumes/SSDA/Planetka Assets Extra/FB/black_pixel_20.exr",
        help="WT fallback EXR for Antarctica (y < 15).",
    )
    parser.add_argument("--workers", type=int, default=6, help="Max workers (capped by stage)")
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="For d-rebuild stage, skip already valid destination files and rebuild only missing/corrupt ones.",
    )
    parser.add_argument(
        "--task-retries",
        type=int,
        default=2,
        help="Retry count for each d-rebuild task on transient I/O/read errors.",
    )
    parser.add_argument("--skip-z001-fix", action="store_true", help="Skip z001_d001 fix stage")
    parser.add_argument("--skip-z-rebuild", action="store_true", help="Skip z=z rebuild stage")
    parser.add_argument("--skip-d-rebuild", action="store_true", help="Skip d rebuild stage")
    parser.add_argument(
        "--targeted-higher-z-fallback-only",
        action="store_true",
        help=(
            "Targeted rebuild policy: z002 only where fallback would be used within selected regions; "
            "z004+ rebuild all tiles that intersect selected regions. "
            "Regions: Caspian, Superior, Pacific override, Antarctica y009-y015."
        ),
    )
    parser.add_argument("--limit-z001", type=int, default=0, help="Debug: limit z001 task count")
    parser.add_argument("--limit-z-per-level", type=int, default=0, help="Debug: limit z task count per z level")
    parser.add_argument("--limit-d-per-level", type=int, default=0, help="Debug: limit d task count per d level")
    parser.add_argument(
        "--only-z",
        default="",
        help="Optional comma-separated z levels to process for d-rebuild (example: 1,2,4).",
    )
    parser.add_argument(
        "--only-d-effective",
        default="",
        help="Optional comma-separated effective d levels to process for d-rebuild (example: 30,60,90,1440).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source_root = Path(args.source_root).expanduser().resolve()
    output_root = Path(args.root).expanduser().resolve()
    manifest_root = Path(args.manifest_root).expanduser().resolve() if str(args.manifest_root).strip() else source_root

    if not source_root.is_dir():
        print(f"WT source root not found: {source_root}")
        return 2
    if not manifest_root.is_dir():
        print(f"WT manifest root not found: {manifest_root}")
        return 2
    if not Path(args.blue_fallback).is_file():
        print(f"Blue fallback missing: {args.blue_fallback}")
        return 2
    if not Path(args.red_fallback).is_file():
        print(f"Red fallback missing: {args.red_fallback}")
        return 2
    if not Path(args.black_fallback).is_file():
        print(f"Black fallback missing: {args.black_fallback}")
        return 2

    output_root.mkdir(parents=True, exist_ok=True)

    global OUT_ROOT, BLUE_FALLBACK_PATH, RED_FALLBACK_PATH, BLACK_FALLBACK_PATH, _D_LEVELS_BY_Z, SKIP_EXISTING, MAX_TASK_RETRIES
    OUT_ROOT = str(output_root)
    BLUE_FALLBACK_PATH = str(Path(args.blue_fallback).expanduser().resolve())
    RED_FALLBACK_PATH = str(Path(args.red_fallback).expanduser().resolve())
    BLACK_FALLBACK_PATH = str(Path(args.black_fallback).expanduser().resolve())
    SKIP_EXISTING = bool(args.resume_existing)
    MAX_TASK_RETRIES = max(0, int(args.task_retries))

    max_workers = max(1, min(int(args.workers), 16))
    started = time.perf_counter()
    print(
        f"WT fix+rebuild start source={source_root} output={OUT_ROOT} manifest={manifest_root} "
        f"max_workers={max_workers} ratio={FIX_RATIO:.9f} "
        f"resume_existing={SKIP_EXISTING} task_retries={MAX_TASK_RETRIES}"
    )

    z001_tasks, z_base_list, d_tasks_by_z = _collect_manifest(manifest_root, source_root, output_root)

    only_z_filter: set[int] = set()
    if str(args.only_z).strip():
        only_z_filter = {
            int(part.strip())
            for part in str(args.only_z).split(",")
            if str(part).strip()
        }

    only_d_filter: set[int] = set()
    if str(args.only_d_effective).strip():
        only_d_filter = {
            int(part.strip())
            for part in str(args.only_d_effective).split(",")
            if str(part).strip()
        }

    if only_z_filter:
        d_tasks_by_z = {z: tasks for z, tasks in d_tasks_by_z.items() if int(z) in only_z_filter}
        z_base_list = {z: tasks for z, tasks in z_base_list.items() if int(z) in only_z_filter}

    if only_d_filter:
        filtered: dict[int, list[tuple[int, int, int, int]]] = {}
        for z, tasks in d_tasks_by_z.items():
            kept = [t for t in tasks if _decode_d_from_name(int(t[3])) in only_d_filter]
            if kept:
                filtered[z] = kept
        d_tasks_by_z = filtered

    _D_LEVELS_BY_Z = _build_d_levels_by_z(z_base_list, d_tasks_by_z)
    total_targets = sum(len(v) for v in z_base_list.values()) + sum(len(v) for v in d_tasks_by_z.values())
    print(
        f"manifest z001_d001={len(z001_tasks)} z_bases={sum(len(v) for v in z_base_list.values())} "
        f"d_targets={sum(len(v) for v in d_tasks_by_z.values())} total_targets={total_targets}"
    )

    if int(args.limit_z001) > 0:
        z001_tasks = z001_tasks[: int(args.limit_z001)]
    if int(args.limit_z_per_level) > 0:
        for z in list(z_base_list.keys()):
            z_base_list[z] = z_base_list[z][: int(args.limit_z_per_level)]
    if int(args.limit_d_per_level) > 0:
        for z in list(d_tasks_by_z.keys()):
            d_tasks_by_z[z] = d_tasks_by_z[z][: int(args.limit_d_per_level)]

    if args.targeted_higher_z_fallback_only:
        z_base_list = _filter_targeted_z_tasks(z_base_list)

    failures = 0
    if not args.skip_z001_fix:
        _, failed = _run_stage("fix-z001-d001", z001_tasks, max_workers, _fix_z001, progress_every=200)
        failures += failed

    if not args.skip_z_rebuild:
        for z in Z_BUILD_ORDER:
            coords = z_base_list.get(z, [])
            tasks = [(x, y, z) for x, y in coords]
            workers = _workers_for_z(max_workers, z)
            _, failed = _run_stage(f"rebuild-z{z:03d}", tasks, workers, _build_z_base, progress_every=25)
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
                    chunksize=8,
                )
                failures += failed

    elapsed = time.perf_counter() - started
    print(f"WT fix+rebuild finished failures={failures} elapsed={elapsed:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
