#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import OpenEXR


TILE_RE = re.compile(r"^S2_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.exr$", re.IGNORECASE)
Z_ORDER = (1, 2, 4, 8, 15, 16, 30, 32, 60, 90, 180, 360)
Z_BASE_SOURCE = {
    2: 1,
    4: 1,
    8: 1,
    15: 1,
    16: 8,
    32: 8,
    30: 15,
    60: 15,
    90: 15,
    180: 15,
    360: 15,
}


def _ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _decode_d(d_code: int) -> int:
    return 1440 if int(d_code) == 0 else int(d_code)


def _encode_d(d_eff: int) -> int:
    return 0 if int(d_eff) == 1440 else int(d_eff)


def _name(x: int, y: int, z: int, d_eff: int) -> str:
    return f"S2_x{x:03d}_y{y:03d}_z{z:03d}_d{_encode_d(d_eff):03d}.exr"


def _tile_bbox_lonlat(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    lon0 = float(x) - 180.0
    lon1 = lon0 + float(z)
    lat0 = float(y) - 90.0
    lat1 = lat0 + float(z)
    return lon0, lon1, lat0, lat1


def _overlaps_region(x: int, y: int, z: int, lon_min: float, lon_max: float, lat_min: float, lat_max: float) -> bool:
    lon0, lon1, lat0, lat1 = _tile_bbox_lonlat(x, y, z)
    return (max(lon0, lon_min) < min(lon1, lon_max)) and (max(lat0, lat_min) < min(lat1, lat_max))


def _smoothstep01(v: float) -> float:
    if v <= 0.0:
        return 0.0
    if v >= 1.0:
        return 1.0
    return v * v * (3.0 - 2.0 * v)


def _tile_region_strength(
    x: int,
    y: int,
    z: int,
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    feather_deg: float,
) -> float:
    lon0, lon1, lat0, lat1 = _tile_bbox_lonlat(x, y, z)
    lon_c = 0.5 * (lon0 + lon1)
    lat_c = 0.5 * (lat0 + lat1)
    wl = _smoothstep01((lon_c - lon_min) / feather_deg)
    wr = _smoothstep01((lon_max - lon_c) / feather_deg)
    wb = _smoothstep01((lat_c - lat_min) / feather_deg)
    wt = _smoothstep01((lat_max - lat_c) / feather_deg)
    return float(max(0.0, min(wl, wr, wb, wt)))


def _read_rgb_exr(path: Path) -> np.ndarray:
    exr = OpenEXR.File(str(path))
    ch = exr.parts[0].channels
    if "RGB" in ch:
        arr = np.asarray(ch["RGB"].pixels, dtype=np.float32)
    elif all(k in ch for k in ("R", "G", "B")):
        r = np.asarray(ch["R"].pixels, dtype=np.float32)
        g = np.asarray(ch["G"].pixels, dtype=np.float32)
        b = np.asarray(ch["B"].pixels, dtype=np.float32)
        arr = np.stack((r, g, b), axis=2)
    else:
        raise RuntimeError(f"Missing RGB channels in {path}")
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    arr = arr[:, :, :3]
    return arr.astype(np.float32, copy=False)


def _get_spec_wh(path: Path) -> tuple[int, int]:
    exr = OpenEXR.File(str(path))
    part = exr.parts[0]
    # OpenEXR Python exposes shape via channel arrays; keep this cheap by reading one channel only.
    ch = part.channels
    if "R" in ch:
        arr = np.asarray(ch["R"].pixels, dtype=np.float32)
    elif "RGB" in ch:
        arr = np.asarray(ch["RGB"].pixels, dtype=np.float32)[:, :, 0]
    else:
        raise RuntimeError(f"Missing channel in {path}")
    h, w = int(arr.shape[0]), int(arr.shape[1])
    return w, h


def _write_rgb_exr(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    rgb16 = np.ascontiguousarray(np.clip(rgb, 0.0, 1.0), dtype=np.float16)
    header = {"compression": OpenEXR.DWAA_COMPRESSION, "type": OpenEXR.scanlineimage}
    with OpenEXR.File(header, {"RGB": rgb16}) as out:
        out.write(str(tmp))
    os.replace(tmp, path)


def _resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    src_h = int(image.shape[0])
    src_w = int(image.shape[1])
    dst_w = int(width)
    dst_h = int(height)
    if src_w == dst_w and src_h == dst_h:
        return image
    if dst_w <= src_w and dst_h <= src_h and (dst_w < src_w or dst_h < src_h):
        interp = cv2.INTER_AREA
    else:
        interp = cv2.INTER_LINEAR
    return cv2.resize(image, (dst_w, dst_h), interpolation=interp)


def _edge_positions(length: int, cells: int) -> np.ndarray:
    arr = np.rint(np.linspace(0.0, float(length), int(cells) + 1)).astype(np.int32)
    arr[0] = 0
    arr[-1] = int(length)
    for i in range(1, len(arr)):
        if arr[i] < arr[i - 1]:
            arr[i] = arr[i - 1]
    return arr


@dataclass(frozen=True)
class Entry:
    name: str
    x: int
    y: int
    z: int
    d_eff: int


class Pipeline:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.source_root = Path(args.source_root).expanduser().resolve()
        self.output_root = Path(args.output_root).expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.output_root / "_s2_india_tint_rebuild.log"
        self.report_path = self.output_root / "_s2_india_tint_rebuild_report.json"
        self.workers = max(1, int(args.workers))
        self.lon_min = float(args.lon_min)
        self.lon_max = float(args.lon_max)
        self.lat_min = float(args.lat_min)
        self.lat_max = float(args.lat_max)
        self.feather = max(0.01, float(args.feather_deg))
        self.hue_shift = float(args.hue_shift_deg)
        self.sat_scale = float(args.sat_scale)
        self.bg_gain = float(args.bg_gain)
        self.strength = float(args.strength)
        self._lock = threading.Lock()

        fb_base = Path(args.fallback_dir).expanduser().resolve()
        self.ocean_fallback_path = fb_base / "ocean_pixel_final_20.exr"
        self.white_fallback_path = fb_base / "white_pixel_20.exr"
        if not self.ocean_fallback_path.is_file() or not self.white_fallback_path.is_file():
            raise RuntimeError(
                f"Fallback files missing under {fb_base} "
                f"(need ocean_pixel_final_20.exr and white_pixel_20.exr)"
            )
        self._ocean_fallback = _read_rgb_exr(self.ocean_fallback_path)
        self._white_fallback = _read_rgb_exr(self.white_fallback_path)

        self.entries = self._scan_entries()
        self.affected = [e for e in self.entries if _overlaps_region(
            e.x, e.y, e.z, self.lon_min, self.lon_max, self.lat_min, self.lat_max
        )]
        self.by_name: dict[str, Entry] = {e.name: e for e in self.entries}

    def _log(self, msg: str) -> None:
        line = f"[{_ts()}] {msg}"
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        print(line, flush=True)

    def _scan_entries(self) -> list[Entry]:
        out: list[Entry] = []
        with os.scandir(self.source_root) as it:
            for ent in it:
                if not ent.is_file():
                    continue
                m = TILE_RE.match(ent.name)
                if not m:
                    continue
                x = int(m.group("x"))
                y = int(m.group("y"))
                z = int(m.group("z"))
                d_eff = _decode_d(int(m.group("d")))
                out.append(Entry(ent.name, x, y, z, d_eff))
        return out

    def _source_path(self, name: str) -> Path:
        return self.source_root / name

    def _output_path(self, name: str) -> Path:
        return self.output_root / name

    def _read_or_fallback(self, x: int, y: int, z: int, d_eff: int) -> np.ndarray:
        name = _name(x, y, z, d_eff)
        outp = self._output_path(name)
        if outp.is_file():
            return _read_rgb_exr(outp)
        srcp = self._source_path(name)
        if srcp.is_file():
            return _read_rgb_exr(srcp)
        if int(y) + int(z) < 9:
            return self._white_fallback
        return self._ocean_fallback

    def _tint_fix_tile(self, ent: Entry) -> tuple[bool, str]:
        src = self._source_path(ent.name)
        dst = self._output_path(ent.name)
        if dst.is_file() and not self.args.force:
            return True, "skip_exists"
        if not src.is_file():
            return False, f"missing_source:{src}"

        rgb_lin = np.clip(np.nan_to_num(_read_rgb_exr(src), nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
        # display-like domain for hue/sat operations
        disp = np.power(rgb_lin, 1.0 / 2.2, dtype=np.float32)
        bgr = disp[:, :, ::-1]
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        h = hsv[:, :, 0]
        s = hsv[:, :, 1]
        v = hsv[:, :, 2]
        r = disp[:, :, 0]
        g = disp[:, :, 1]
        b = disp[:, :, 2]

        veg = (
            (h >= 45.0)
            & (h <= 180.0)
            & (s > 0.08)
            & (v > 0.08)
            & (v < 0.95)
            & (g > r * 0.90)
            & (g > b * 0.80)
        )
        veg_f = veg.astype(np.float32)
        veg_conf = np.clip((s - 0.08) / 0.25, 0.0, 1.0).astype(np.float32)

        tile_strength = _tile_region_strength(
            ent.x,
            ent.y,
            ent.z,
            self.lon_min,
            self.lon_max,
            self.lat_min,
            self.lat_max,
            self.feather,
        )
        blend_strength = float(np.clip(self.strength * tile_strength, 0.0, 1.0))
        if blend_strength <= 1e-6:
            # Outside feathered region center influence.
            _write_rgb_exr(dst, rgb_lin)
            return True, "copy_only"

        # full correction
        hsv2 = hsv.copy()
        hsv2[:, :, 0] = (hsv2[:, :, 0] + self.hue_shift) % 360.0
        hsv2[:, :, 1] = np.clip(hsv2[:, :, 1] * self.sat_scale, 0.0, 1.0)
        adj_disp = cv2.cvtColor(hsv2, cv2.COLOR_HSV2BGR)[:, :, ::-1]
        adj_disp[:, :, 2] = np.clip(adj_disp[:, :, 2] * self.bg_gain, 0.0, 1.0)

        w = (blend_strength * veg_f * veg_conf)[:, :, None]
        out_disp = disp * (1.0 - w) + adj_disp * w
        out_lin = np.power(np.clip(out_disp, 0.0, 1.0), 2.2, dtype=np.float32)
        _write_rgb_exr(dst, out_lin)
        return True, "fixed"

    def _build_base(self, ent: Entry) -> tuple[bool, str]:
        dst = self._output_path(ent.name)
        if dst.is_file() and not self.args.force:
            return True, "skip_exists"
        src_z = int(Z_BASE_SOURCE.get(int(ent.z), int(ent.z)))
        if int(ent.z) <= 1:
            return False, "invalid_base_z"
        if int(ent.z) % src_z != 0:
            return False, f"z_source_mismatch:{ent.z}:{src_z}"

        ratio_x = int(ent.z) // src_z
        ratio_y = ratio_x // 2 if int(ent.z) == 360 else ratio_x
        if ratio_y <= 0:
            return False, "invalid_ratio"

        sw, sh = _get_spec_wh(self._source_path(ent.name))
        x_edges = _edge_positions(sw, ratio_x)
        y_edges = _edge_positions(sh, ratio_y)
        out = np.zeros((sh, sw, 3), dtype=np.float32)

        for y_idx in range(ratio_y):
            for x_idx in range(ratio_x):
                sx = int(ent.x) + x_idx * src_z
                sy = int(ent.y) + y_idx * src_z
                src = self._read_or_fallback(sx, sy, src_z, src_z)
                dx0 = int(x_edges[x_idx])
                dx1 = int(x_edges[x_idx + 1])
                dy0 = int(y_edges[ratio_y - 1 - y_idx])
                dy1 = int(y_edges[ratio_y - y_idx])
                cw = max(1, dx1 - dx0)
                chh = max(1, dy1 - dy0)
                rs = _resize(src, cw, chh)
                out[dy0:dy1, dx0:dx1] = rs
        _write_rgb_exr(dst, out)
        return True, "rebuilt_base"

    def _build_d(self, ent: Entry) -> tuple[bool, str]:
        dst = self._output_path(ent.name)
        if dst.is_file() and not self.args.force:
            return True, "skip_exists"

        base_d = 1 if int(ent.z) == 1 else int(ent.z)
        src_name = _name(ent.x, ent.y, ent.z, base_d)
        src = self._read_or_fallback(ent.x, ent.y, ent.z, base_d)
        tw, th = _get_spec_wh(self._source_path(ent.name))
        out = _resize(src, tw, th)
        _write_rgb_exr(dst, out)
        return True, f"rebuilt_d_from_{src_name}"

    def _run_pool(
        self,
        label: str,
        tasks: list[Entry],
        fn,
        workers: int,
        progress_every: int = 20,
    ) -> tuple[int, int]:
        if not tasks:
            self._log(f"[{label}] no tasks")
            return 0, 0
        ok = 0
        fail = 0
        done = 0
        total = len(tasks)
        started = time.perf_counter()
        with cf.ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
            futures = [ex.submit(fn, t) for t in tasks]
            for fut in cf.as_completed(futures):
                done += 1
                try:
                    st, msg = fut.result()
                except Exception as exc:  # noqa: BLE001
                    st = False
                    msg = f"exception:{exc}"
                if st:
                    ok += 1
                else:
                    fail += 1
                if done % progress_every == 0 or done == total:
                    self._log(f"[{label}] {done}/{total} ok={ok} fail={fail} last={msg}")
        elapsed = time.perf_counter() - started
        self._log(f"[{label}] done total={total} ok={ok} fail={fail} elapsed={elapsed:.1f}s")
        return ok, fail

    def run(self) -> int:
        z001_tasks = [e for e in self.affected if e.z == 1 and e.d_eff == 1]
        base_tasks = [e for e in self.affected if e.z > 1 and e.d_eff == e.z]
        d_tasks = [e for e in self.affected if not (e.z == 1 and e.d_eff == 1) and not (e.z > 1 and e.d_eff == e.z)]

        # deterministic order for reproducibility
        z001_tasks.sort(key=lambda e: (e.y, e.x))
        base_tasks.sort(key=lambda e: (Z_ORDER.index(e.z), e.y, e.x))
        d_tasks.sort(key=lambda e: (Z_ORDER.index(e.z), e.y, e.x, e.d_eff))

        self._log(
            f"start source={self.source_root} output={self.output_root} "
            f"affected={len(self.affected)} z001={len(z001_tasks)} base={len(base_tasks)} d={len(d_tasks)} "
            f"workers={self.workers}"
        )

        start = time.perf_counter()
        z001_ok, z001_fail = self._run_pool("z001_tint_fix", z001_tasks, self._tint_fix_tile, workers=1, progress_every=5)

        # Base stage by z-level, up to requested workers.
        base_ok = 0
        base_fail = 0
        for z in Z_ORDER:
            z_tasks = [e for e in base_tasks if e.z == z]
            if not z_tasks:
                continue
            ok, fail = self._run_pool(f"base_z{z:03d}", z_tasks, self._build_base, workers=self.workers, progress_every=10)
            base_ok += ok
            base_fail += fail

        # D stage by z-level.
        d_ok = 0
        d_fail = 0
        for z in Z_ORDER:
            z_tasks = [e for e in d_tasks if e.z == z]
            if not z_tasks:
                continue
            ok, fail = self._run_pool(f"d_z{z:03d}", z_tasks, self._build_d, workers=self.workers, progress_every=25)
            d_ok += ok
            d_fail += fail

        elapsed = time.perf_counter() - start
        report = {
            "source_root": str(self.source_root),
            "output_root": str(self.output_root),
            "region": {
                "lon_min": self.lon_min,
                "lon_max": self.lon_max,
                "lat_min": self.lat_min,
                "lat_max": self.lat_max,
                "feather_deg": self.feather,
            },
            "tint": {
                "hue_shift_deg": self.hue_shift,
                "sat_scale": self.sat_scale,
                "bg_gain": self.bg_gain,
                "strength": self.strength,
            },
            "workers": self.workers,
            "counts": {
                "affected_total": len(self.affected),
                "z001_tasks": len(z001_tasks),
                "base_tasks": len(base_tasks),
                "d_tasks": len(d_tasks),
            },
            "results": {
                "z001_ok": z001_ok,
                "z001_fail": z001_fail,
                "base_ok": base_ok,
                "base_fail": base_fail,
                "d_ok": d_ok,
                "d_fail": d_fail,
            },
            "elapsed_sec": elapsed,
            "finished_at": _ts(),
        }
        self.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self._log(f"finished elapsed={elapsed:.1f}s report={self.report_path}")
        return 1 if (z001_fail or base_fail or d_fail) else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Regenerate India-tint-affected S2 tiles into a separate output folder: "
            "z001_d001 tint fix, then affected higher-z/higher-d rebuild."
        )
    )
    p.add_argument("--source-root", default="/Volumes/SSDA/Planetka Assets/S2")
    p.add_argument("--output-root", default="/Volumes/SSDA/S2_New_fix")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument(
        "--fallback-dir",
        default=(
            "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
            "user_default/Planetka/Resources/Fallback Images"
        ),
        help="Directory containing ocean_pixel_final_20.exr and white_pixel_20.exr",
    )
    p.add_argument("--lon-min", type=float, default=67.0)
    p.add_argument("--lon-max", type=float, default=92.0)
    p.add_argument("--lat-min", type=float, default=7.0)
    p.add_argument("--lat-max", type=float, default=31.0)
    p.add_argument("--feather-deg", type=float, default=2.0)
    p.add_argument("--hue-shift-deg", type=float, default=18.0)
    p.add_argument("--sat-scale", type=float, default=0.75)
    p.add_argument("--bg-gain", type=float, default=1.143407846188169)
    p.add_argument("--strength", type=float, default=0.75, help="Overall correction blend strength")
    p.add_argument("--force", action="store_true", help="Overwrite output files if they already exist")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    pipe = Pipeline(args)
    return pipe.run()


if __name__ == "__main__":
    raise SystemExit(main())
