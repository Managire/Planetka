#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Iterable

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np
import OpenEXR
import OpenImageIO as oiio

try:
    cv2.setLogLevel(0)
except Exception:
    pass


TILE_RE = re.compile(
    r"^S2_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.exr$",
    re.IGNORECASE,
)

Z_BUILD_ORDER = [2, 4, 8, 15, 16, 30, 32, 60, 90, 180, 360]
Z_2X2 = {2, 4, 8, 16, 30, 32, 60, 180}

ROOT_DIR: str = ""
OCEAN_FALLBACK_PATH: str = ""
WHITE_FALLBACK_PATH: str = ""
_OCEAN_FALLBACK: np.ndarray | None = None
_WHITE_FALLBACK: np.ndarray | None = None
_R2_ENDPOINT_URL: str | None = None
_D_LEVELS_BY_Z: dict[int, list[int]] = {}


def _encode_d_for_name(d_effective: int) -> int:
    return 0 if int(d_effective) == 1440 else int(d_effective)


def _decode_d_from_name(d_code: int) -> int:
    return 1440 if int(d_code) == 0 else int(d_code)


def _tile_name(x: int, y: int, z: int, d_code: int) -> str:
    return f"S2_x{x:03d}_y{y:03d}_z{z:03d}_d{d_code:03d}.exr"


def _tile_path(x: int, y: int, z: int, d_code: int) -> str:
    return str(Path(ROOT_DIR) / _tile_name(x, y, z, d_code))


def _read_image(path: str) -> np.ndarray:
    # Prefer OpenEXR native decode to avoid OpenCV EXR decoder artifacts.
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
            raise RuntimeError(f"Unsupported EXR channel layout for {path}: {list(channels.keys())}")
        if array.ndim == 2:
            array = np.repeat(array[:, :, None], 3, axis=2)
        if array.ndim != 3 or array.shape[2] < 3:
            raise RuntimeError(f"Unexpected shape for image {path}: {array.shape}")
        if array.shape[2] > 3:
            array = array[:, :, :3]
        # OpenEXR returns RGB; convert to BGR for the rest of the pipeline.
        image = array[:, :, [2, 1, 0]]
    except Exception:
        image = None

    if image is None:
        # Fallback to OIIO for files that fail OpenEXR decode.
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
    if image.ndim != 3 or image.shape[2] < 3:
        raise RuntimeError(f"Unexpected shape for image {path}: {image.shape}")
    if image.shape[2] > 3:
        image = image[:, :, :3]
    if image.dtype != np.float32:
        image = image.astype(np.float32, copy=False)
    return image


def _resolve_r2_endpoint() -> str | None:
    global _R2_ENDPOINT_URL
    if _R2_ENDPOINT_URL:
        return _R2_ENDPOINT_URL

    env_endpoint = str(os.environ.get("PLANETKA_R2_ENDPOINT_URL", "")).strip()
    if env_endpoint:
        _R2_ENDPOINT_URL = env_endpoint
        return _R2_ENDPOINT_URL

    secrets_file = str(
        os.environ.get(
            "PLANETKA_R2_SECRETS_FILE",
            f"{Path.home()}/.planetka/secrets/Cloudflare_API_from_stash_2026-03-17.txt",
        )
    )
    try:
        with open(secrets_file, "r", encoding="utf-8") as handle:
            for line in handle:
                normalized = line.replace("\u00a0", " ")
                match = re.match(r"^\s*R2_ACCOUNT_ID\s*=\s*(\S+)\s*$", normalized)
                if match:
                    account_id = str(match.group(1)).strip()
                    if account_id:
                        _R2_ENDPOINT_URL = f"https://{account_id}.r2.cloudflarestorage.com"
                        return _R2_ENDPOINT_URL
    except Exception:
        return None
    return None


def _get_ocean_fallback() -> np.ndarray:
    global _OCEAN_FALLBACK
    if _OCEAN_FALLBACK is None:
        _OCEAN_FALLBACK = _read_image(OCEAN_FALLBACK_PATH)
    return _OCEAN_FALLBACK


def _get_white_fallback() -> np.ndarray:
    global _WHITE_FALLBACK
    if _WHITE_FALLBACK is None:
        _WHITE_FALLBACK = _read_image(WHITE_FALLBACK_PATH)
    return _WHITE_FALLBACK


def _wrap_x(x: int) -> int:
    return int(x) % 360


def _read_or_fallback(x: int, y: int, z: int, d_effective: int) -> np.ndarray:
    xw = _wrap_x(x)
    d_code = _encode_d_for_name(d_effective)
    path = _tile_path(xw, int(y), int(z), int(d_code))
    if os.path.isfile(path):
        return _read_image(path)
    if int(y) + int(z) < 9:
        return _get_white_fallback()
    return _get_ocean_fallback()


def _resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    if image.shape[1] == int(width) and image.shape[0] == int(height):
        return image
    src_w = int(image.shape[1])
    src_h = int(image.shape[0])
    dst_w = int(width)
    dst_h = int(height)
    # Use box/area when downsampling; fallback to linear for other cases.
    if dst_w <= src_w and dst_h <= src_h and (dst_w < src_w or dst_h < src_h):
        interp = cv2.INTER_AREA
    else:
        interp = cv2.INTER_LINEAR
    return cv2.resize(image, (dst_w, dst_h), interpolation=interp)


def _clip_range(image: np.ndarray) -> np.ndarray:
    np.clip(image, 0.001, 1.0, out=image)
    return image


def _write_s2_exr(path: str, image_bgr: np.ndarray) -> None:
    image = _clip_range(image_bgr.astype(np.float32, copy=False)).astype(np.float16, copy=False)
    # OpenEXR writer is sensitive to array strides; force packed contiguous RGB memory.
    rgb = np.empty((image.shape[0], image.shape[1], 3), dtype=np.float16)
    rgb[:, :, 0] = image[:, :, 2]
    rgb[:, :, 1] = image[:, :, 1]
    rgb[:, :, 2] = image[:, :, 0]
    rgb = np.ascontiguousarray(rgb)
    header = {"compression": OpenEXR.DWAA_COMPRESSION, "type": OpenEXR.scanlineimage}
    channels = {"RGB": rgb}
    with OpenEXR.File(header, channels) as out:
        out.write(path)


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

        if z in Z_2X2:
            child_z = z // 2
            image1 = _read_or_fallback(x, y, child_z, child_z)
            image2 = _read_or_fallback(x + child_z, y, child_z, child_z)
            image3 = _read_or_fallback(x, y + child_z, child_z, child_z)
            image4 = _read_or_fallback(x + child_z, y + child_z, child_z, child_z)

            x_size = max(image1.shape[1], image2.shape[1], image3.shape[1], image4.shape[1])
            y_size = max(image1.shape[0], image2.shape[0], image3.shape[0], image4.shape[0])
            new_im = np.zeros((y_size * 2, x_size * 2, 3), dtype=np.float32)

            new_im[y_size : y_size * 2, 0:x_size] = _resize(image1, x_size, y_size)
            new_im[y_size : y_size * 2, x_size : x_size * 2] = _resize(image2, x_size, y_size)
            new_im[0:y_size, 0:x_size] = _resize(image3, x_size, y_size)
            new_im[0:y_size, x_size : x_size * 2] = _resize(image4, x_size, y_size)

            new_im = cv2.resize(new_im, (x_size, y_size), interpolation=cv2.INTER_AREA)
            _write_s2_exr(dst, new_im)
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
                    new_im[ys : ys + y_size, xs : xs + x_size] = _resize(image, x_size, y_size)
            _write_s2_exr(dst, new_im)
            return True, ""

        if z == 90:
            y_size = x_size = 11133 // 3
            new_im = np.zeros((11133, 11133, 3), dtype=np.float32)
            for y_coord in range(3):
                for x_coord in range(3):
                    image = _read_or_fallback(x + x_coord * 30, y + y_coord * 30, 30, 30)
                    ys = (2 - y_coord) * y_size
                    xs = x_coord * x_size
                    new_im[ys : ys + y_size, xs : xs + x_size] = _resize(image, x_size, y_size)
            _write_s2_exr(dst, new_im)
            return True, ""

        if z == 360:
            x_size = 11133
            y_size = 11133
            new_im = np.zeros((11133, 11133 * 2, 3), dtype=np.float32)
            image1 = _read_or_fallback(0, 0, 180, 180)
            image2 = _read_or_fallback(180, 0, 180, 180)
            new_im[0:11133, 0:11133] = _resize(image1, x_size, y_size)
            new_im[0:11133, 11133 : 11133 * 2] = _resize(image2, x_size, y_size)
            new_im = cv2.resize(new_im, (x_size, y_size // 2), interpolation=cv2.INTER_AREA)
            _write_s2_exr(dst, new_im)
            return True, ""

        return False, f"Unsupported z build level: {z}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{_tile_name(x, y, z, _encode_d_for_name(z))}: {exc}"


def _rebuild_d_variant(task: tuple[int, int, int, int]) -> tuple[bool, str]:
    x, y, z, d_code = task
    try:
        d_effective = _decode_d_from_name(d_code)
        prev_level, src = _select_prev_mip_source(x, y, z, d_effective)
        if src is None:
            return False, f"Missing source for d rebuild: z={z} d={d_effective} at x={x} y={y}"
        dst = _tile_path(x, y, z, d_code)
        image = _read_image(src)
        src_h, src_w = image.shape[0], image.shape[1]
        scale = float(prev_level) / float(d_effective)
        dst_w = max(1, int(round(float(src_w) * scale)))
        dst_h = max(1, int(round(float(src_h) * scale)))
        out = _resize(image, dst_w, dst_h)
        _write_s2_exr(dst, out)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{_tile_name(x, y, z, d_code)}: {exc}"


def _clamp_z001(task: str) -> tuple[bool, str]:
    path = task
    try:
        try:
            image = _read_image(path)
        except Exception:
            recovered = _recover_z001_from_cloudflare(path)
            if not recovered:
                raise
            image = _read_image(path)
        _write_s2_exr(path, image)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{path}: {exc}"


def _recover_z001_from_cloudflare(path: str) -> bool:
    name = os.path.basename(path)
    match = TILE_RE.match(name)
    if not match:
        return False
    if int(match.group("z")) != 1 or _decode_d_from_name(int(match.group("d"))) != 1:
        return False

    aws_bin = shutil.which("aws")
    if not aws_bin:
        return False
    endpoint = _resolve_r2_endpoint()
    if not endpoint:
        return False

    profile = str(os.environ.get("PLANETKA_R2_PROFILE", "planetka-r2")).strip()
    bucket = str(os.environ.get("PLANETKA_R2_BUCKET", "planetka-data")).strip()
    prefix = str(os.environ.get("PLANETKA_R2_PREFIX", "planetka-assets/S2")).strip("/")
    remote_key = f"s3://{bucket}/{prefix}/{name}"

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix="pka_s2_",
            suffix=".exr",
            dir=str(Path(path).parent),
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
        cmd = [
            aws_bin,
            "s3",
            "cp",
            remote_key,
            tmp_path,
            "--profile",
            profile,
            "--endpoint-url",
            endpoint,
            "--no-progress",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return False
        _ = _read_image(tmp_path)
        os.replace(tmp_path, path)
        tmp_path = ""
        return True
    except Exception:
        return False
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _run_stage(
    label: str,
    tasks: Iterable,
    worker_count: int,
    worker_fn,
    progress_every: int = 100,
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
            maxtasksperchild=20,
            initializer=_init_worker_globals,
            initargs=(ROOT_DIR, OCEAN_FALLBACK_PATH, WHITE_FALLBACK_PATH, _D_LEVELS_BY_Z),
        ) as pool:
            for ok, err in pool.imap_unordered(worker_fn, tasks, chunksize=1):
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
    root_dir: str, ocean_fallback: str, white_fallback: str, d_levels_by_z: dict[int, list[int]] | None = None
) -> None:
    global ROOT_DIR, OCEAN_FALLBACK_PATH, WHITE_FALLBACK_PATH, _OCEAN_FALLBACK, _WHITE_FALLBACK, _D_LEVELS_BY_Z
    ROOT_DIR = str(root_dir or "")
    OCEAN_FALLBACK_PATH = str(ocean_fallback or "")
    WHITE_FALLBACK_PATH = str(white_fallback or "")
    _D_LEVELS_BY_Z = dict(d_levels_by_z or {})
    # Ensure each process lazily reloads fallback images in its own memory space.
    _OCEAN_FALLBACK = None
    _WHITE_FALLBACK = None


def _collect_manifest(root: Path) -> tuple[list[str], dict[int, list[tuple[int, int]]], dict[int, list[tuple[int, int, int, int]]]]:
    clamp_paths: list[str] = []
    z_base_coords: dict[int, set[tuple[int, int]]] = defaultdict(set)
    d_tasks_by_z: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)

    with os.scandir(root) as it:
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
                clamp_paths.append(entry.path)
                continue
            if d_effective == z and z > 1:
                z_base_coords[z].add((x, y))
                continue
            d_tasks_by_z[z].append((x, y, z, d_code))

    z_base_list: dict[int, list[tuple[int, int]]] = {
        z: sorted(coords, key=lambda p: (p[1], p[0])) for z, coords in z_base_coords.items()
    }
    for z in list(d_tasks_by_z.keys()):
        d_tasks_by_z[z] = sorted(d_tasks_by_z[z], key=lambda t: (t[1], t[0], t[3]))

    clamp_paths.sort()
    return clamp_paths, z_base_list, d_tasks_by_z


def _workers_for_z(max_workers: int, z: int) -> int:
    if z >= 180:
        return 1
    if z >= 90:
        return min(2, max_workers)
    if z >= 60:
        return min(4, max_workers)
    return max_workers


def _build_d_levels_by_z(
    z_base_list: dict[int, list[tuple[int, int]]], d_tasks_by_z: dict[int, list[tuple[int, int, int, int]]]
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


def _group_d_tasks_by_effective(d_tasks: list[tuple[int, int, int, int]]) -> list[tuple[int, list[tuple[int, int, int, int]]]]:
    groups: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)
    for task in d_tasks:
        groups[_decode_d_from_name(task[3])].append(task)
    out: list[tuple[int, list[tuple[int, int, int, int]]]] = []
    for d_effective in sorted(groups.keys()):
        out.append((d_effective, sorted(groups[d_effective], key=lambda t: (t[1], t[0], t[3]))))
    return out


def _select_prev_mip_source(x: int, y: int, z: int, d_effective: int) -> tuple[int, str | None]:
    levels = _D_LEVELS_BY_Z.get(int(z), [int(z)])
    lower = [lv for lv in levels if int(z) <= lv < int(d_effective)]
    if not lower:
        src = _tile_path(x, y, z, _encode_d_for_name(z))
        if os.path.isfile(src):
            return int(z), src
        return int(z), None

    # Prefer strict mip step (ratio ~2x), then the largest available lower level.
    ranked = sorted(
        lower,
        key=lambda lv: (abs(math.log2(float(d_effective) / float(lv)) - 1.0), -lv),
    )
    for lv in ranked:
        src = _tile_path(x, y, z, _encode_d_for_name(lv))
        if os.path.isfile(src):
            return int(lv), src
    # Fallback to base z if no lower d source file exists.
    src = _tile_path(x, y, z, _encode_d_for_name(z))
    if os.path.isfile(src):
        return int(z), src
    return int(z), None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clamp S2 z001_d001 to [0.001,1] and rebuild all higher z/d variants in-place."
    )
    parser.add_argument(
        "--root",
        default="/Volumes/SSDA/Planetka Assets/S2",
        help="S2 folder root",
    )
    parser.add_argument(
        "--ocean-fallback",
        default=(
            "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
            "user_default/Planetka/Resources/Fallback Images/ocean_pixel_final_20.exr"
        ),
        help="Ocean fallback EXR",
    )
    parser.add_argument(
        "--white-fallback",
        default=(
            "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
            "user_default/Planetka/Resources/Fallback Images/white_pixel_20.exr"
        ),
        help="White fallback EXR (polar)",
    )
    parser.add_argument("--workers", type=int, default=4, help="Max workers (capped by stage)")
    parser.add_argument("--skip-clamp", action="store_true", help="Skip z001_d001 clamping stage")
    parser.add_argument("--skip-z-rebuild", action="store_true", help="Skip z=z rebuild stage")
    parser.add_argument("--skip-d-rebuild", action="store_true", help="Skip d rebuild stage")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"S2 root not found: {root}")
        return 2
    if not Path(args.ocean_fallback).is_file():
        print(f"Ocean fallback missing: {args.ocean_fallback}")
        return 2
    if not Path(args.white_fallback).is_file():
        print(f"White fallback missing: {args.white_fallback}")
        return 2

    global ROOT_DIR, OCEAN_FALLBACK_PATH, WHITE_FALLBACK_PATH
    ROOT_DIR = str(root)
    OCEAN_FALLBACK_PATH = str(Path(args.ocean_fallback).expanduser().resolve())
    WHITE_FALLBACK_PATH = str(Path(args.white_fallback).expanduser().resolve())

    max_workers = max(1, min(int(args.workers), 8))
    started = time.perf_counter()
    print(f"S2 clamp+rebuild start root={ROOT_DIR} max_workers={max_workers}")

    clamp_paths, z_base_list, d_tasks_by_z = _collect_manifest(root)
    global _D_LEVELS_BY_Z
    _D_LEVELS_BY_Z = _build_d_levels_by_z(z_base_list, d_tasks_by_z)
    total_targets = sum(len(v) for v in z_base_list.values()) + sum(len(v) for v in d_tasks_by_z.values())
    print(
        f"manifest z001_d001={len(clamp_paths)} z_bases={sum(len(v) for v in z_base_list.values())} "
        f"d_targets={sum(len(v) for v in d_tasks_by_z.values())} total_targets={total_targets}"
    )

    failures = 0
    if not args.skip_clamp:
        _, failed = _run_stage("clamp-z001-d001", clamp_paths, max_workers, _clamp_z001, progress_every=200)
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
                )
                failures += failed

    elapsed = time.perf_counter() - started
    print(f"S2 clamp+rebuild finished failures={failures} elapsed={elapsed:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
