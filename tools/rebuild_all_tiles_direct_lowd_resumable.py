#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
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


TILE_RE = re.compile(
    r"^(?P<ds>S2|EL|WT|PO)_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.(?P<ext>exr|tif)$",
    re.IGNORECASE,
)

DATASETS = ("S2", "EL", "WT", "PO")
Z_ORDER = (1, 2, 4, 8, 15, 16, 30, 32, 60, 90, 180, 360)
EXCLUDED_FILES: set[tuple[str, str]] = set()

# Higher-z base source map requested by user.
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


def _decode_d(d_code: int) -> int:
    return 1440 if int(d_code) == 0 else int(d_code)


def _encode_d(d_eff: int) -> int:
    return 0 if int(d_eff) == 1440 else int(d_eff)


def _ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _wrap_x(x: int) -> int:
    return int(x) % 360


def _edge_positions(length: int, cells: int) -> np.ndarray:
    # Robust integer partition where edge[-1] == length.
    arr = np.rint(np.linspace(0.0, float(length), int(cells) + 1)).astype(np.int32)
    arr[0] = 0
    arr[-1] = int(length)
    for i in range(1, len(arr)):
        if arr[i] < arr[i - 1]:
            arr[i] = arr[i - 1]
    return arr


def _retry_sleep(attempt: int) -> None:
    time.sleep(min(5.0, 0.4 * (attempt + 1)))


@dataclass(frozen=True)
class Task:
    dataset: str
    filename: str
    x: int
    y: int
    z: int
    d_eff: int
    ext: str
    kind: str


class Pipeline:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.assets_root = Path(args.assets_root).expanduser().resolve()
        self.state_dir = Path(args.state_dir).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.state_dir / "rebuild.log"
        self.events_path = self.state_dir / "events.jsonl"
        self.db_path = self.state_dir / "state.sqlite3"
        self.profile = args.profile
        self.bucket = args.bucket
        self.prefix_root = args.prefix_root.strip("/").strip()
        self.secrets_file = Path(args.secrets_file).expanduser().resolve()
        self.endpoint_url = self._resolve_endpoint()
        self.dataset_ext: dict[str, str] = {}
        self.remote_key_by_name: dict[tuple[str, str], str] = {}
        self._fallback_rgb: dict[str, np.ndarray] = {}
        self._fallback_scalar: dict[str, np.ndarray] = {}
        self._fallback_lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self._log(
            f"pipeline init assets_root={self.assets_root} state_dir={self.state_dir} "
            f"bucket={self.bucket} prefix_root={self.prefix_root} endpoint={self.endpoint_url}"
        )

    def _log(self, msg: str) -> None:
        line = f"[{_ts()}] {msg}"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)

    def _event(self, event: str, **payload) -> None:
        payload = {"ts": _ts(), "event": event, **payload}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _resolve_endpoint(self) -> str:
        env = str(os.environ.get("PLANETKA_R2_ENDPOINT_URL", "")).strip()
        if env:
            return env
        if not self.secrets_file.is_file():
            raise RuntimeError(f"secrets file missing: {self.secrets_file}")
        account_id = ""
        with self.secrets_file.open("r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*R2_ACCOUNT_ID\s*=\s*(\S+)\s*$", line.replace("\u00a0", " "))
                if m:
                    account_id = str(m.group(1)).strip()
                    break
        if not account_id:
            raise RuntimeError(f"failed parsing R2_ACCOUNT_ID from {self.secrets_file}")
        return f"https://{account_id}.r2.cloudflarestorage.com"

    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS manifest (
                dataset TEXT NOT NULL,
                filename TEXT NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                d_eff INTEGER NOT NULL,
                ext TEXT NOT NULL,
                remote_key TEXT NOT NULL,
                PRIMARY KEY (dataset, filename)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                dataset TEXT NOT NULL,
                filename TEXT NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                d_eff INTEGER NOT NULL,
                ext TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (dataset, filename)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_order ON tasks(z, kind, y, x, dataset, d_eff)")
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass

    def _run_aws(self, argv: list[str], retry: int = 0) -> subprocess.CompletedProcess:
        cmd = [
            "aws",
            *argv,
            "--profile",
            self.profile,
            "--endpoint-url",
            self.endpoint_url,
        ]
        last_exc: Exception | None = None
        for attempt in range(retry + 1):
            try:
                return subprocess.run(cmd, check=True, capture_output=True, text=True)
            except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= retry:
                    break
                _retry_sleep(attempt)
        raise RuntimeError(f"AWS command failed: {' '.join(cmd)}; last={last_exc}")

    def _load_remote_manifest(self, dataset: str) -> list[tuple[str, int, int, int, int, str, str]]:
        prefix = f"{self.prefix_root}/{dataset}/"
        self._log(f"[manifest] listing remote {dataset} prefix={prefix}")
        cmd = [
            "aws",
            "s3",
            "ls",
            f"s3://{self.bucket}/{prefix}",
            "--recursive",
            "--profile",
            self.profile,
            "--endpoint-url",
            self.endpoint_url,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        rows: list[tuple[str, int, int, int, int, str, str]] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=3)
            if len(parts) < 4:
                continue
            key = parts[3]
            filename = Path(key).name
            m = TILE_RE.match(filename)
            if not m:
                continue
            if str(m.group("ds")).upper() != dataset:
                continue
            x = int(m.group("x"))
            y = int(m.group("y"))
            z = int(m.group("z"))
            d_eff = _decode_d(int(m.group("d")))
            ext = str(m.group("ext")).lower()
            rows.append((filename, x, y, z, d_eff, ext, key))
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"manifest list failed for {dataset}: rc={rc} err={stderr.strip()}")
        self._log(f"[manifest] {dataset} rows={len(rows)}")
        return rows

    def refresh_manifest(self) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM manifest")
        self.conn.commit()

        for ds in DATASETS:
            rows = self._load_remote_manifest(ds)
            if not rows:
                self._log(f"[manifest] warning: no remote rows for dataset={ds}")
            rows = [row for row in rows if (ds, str(row[0])) not in EXCLUDED_FILES]
            cur.executemany(
                """
                INSERT OR REPLACE INTO manifest (dataset, filename, x, y, z, d_eff, ext, remote_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(ds, *row) for row in rows],
            )
        self.conn.commit()
        self._reload_manifest_cache()
        self._log("[manifest] refresh complete")

    def _reload_manifest_cache(self) -> None:
        self.dataset_ext.clear()
        self.remote_key_by_name.clear()
        cur = self.conn.cursor()
        for row in cur.execute("SELECT dataset, filename, ext, remote_key FROM manifest"):
            ds = str(row["dataset"])
            fn = str(row["filename"])
            if (ds, fn) in EXCLUDED_FILES:
                continue
            ext = str(row["ext"]).lower()
            self.remote_key_by_name[(ds, fn)] = str(row["remote_key"])
            if ds not in self.dataset_ext:
                self.dataset_ext[ds] = ext
        for ds in DATASETS:
            if ds not in self.dataset_ext:
                self.dataset_ext[ds] = "exr" if ds != "PO" else "tif"

    def sync_tasks(self) -> None:
        cur = self.conn.cursor()
        # Reset in-progress tasks for crash recovery.
        cur.execute(
            "UPDATE tasks SET status='pending', updated_at=? WHERE status='in_progress'",
            (_ts(),),
        )

        rows = list(
            cur.execute(
                "SELECT dataset, filename, x, y, z, d_eff, ext FROM manifest ORDER BY dataset, z, y, x, d_eff"
            )
        )
        inserted = 0
        for row in rows:
            ds = str(row["dataset"])
            fn = str(row["filename"])
            if (ds, fn) in EXCLUDED_FILES:
                continue
            z = int(row["z"])
            d_eff = int(row["d_eff"])
            # Protected source: never touch z001_d001.
            if z == 1 and d_eff == 1:
                continue
            kind = ""
            if d_eff == z and z > 1:
                kind = "base"
            elif d_eff > z:
                kind = "d"
            else:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO tasks
                (dataset, filename, x, y, z, d_eff, ext, kind, status, attempts, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, '', ?)
                """,
                (
                    ds,
                    fn,
                    int(row["x"]),
                    int(row["y"]),
                    z,
                    d_eff,
                    str(row["ext"]).lower(),
                    kind,
                    _ts(),
                ),
            )
            if cur.rowcount:
                inserted += 1
        self.conn.commit()
        self._log(f"[tasks] synced, inserted={inserted}")

    def prune_local_extras(self) -> None:
        cur = self.conn.cursor()
        expected_by_ds: dict[str, set[str]] = {ds: set() for ds in DATASETS}
        for row in cur.execute("SELECT dataset, filename FROM manifest"):
            expected_by_ds[str(row["dataset"])].add(str(row["filename"]))

        deleted = 0
        for ds in DATASETS:
            ds_dir = self.assets_root / ds
            if not ds_dir.is_dir():
                continue
            expected = expected_by_ds.get(ds, set())
            for entry in ds_dir.iterdir():
                if not entry.is_file():
                    continue
                m = TILE_RE.match(entry.name)
                if not m:
                    continue
                if str(m.group("ds")).upper() != ds:
                    continue
                if entry.name in expected:
                    continue
                try:
                    entry.unlink()
                    deleted += 1
                    self._event("prune_local_extra", dataset=ds, filename=entry.name)
                except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
                    self._log(f"[prune] failed removing {entry}: {exc}")
        self._log(f"[prune] deleted_local_extras={deleted}")

    def _local_path(self, dataset: str, filename: str) -> Path:
        return self.assets_root / dataset / filename

    def _name(self, dataset: str, x: int, y: int, z: int, d_eff: int) -> str:
        ext = self.dataset_ext.get(dataset, "exr")
        return f"{dataset}_x{x:03d}_y{y:03d}_z{z:03d}_d{_encode_d(d_eff):03d}.{ext}"

    def _remote_uri(self, dataset: str, filename: str) -> str:
        key = self.remote_key_by_name.get((dataset, filename))
        if key:
            return f"s3://{self.bucket}/{key}"
        return f"s3://{self.bucket}/{self.prefix_root}/{dataset}/{filename}"

    def _upload_file(self, dataset: str, filename: str) -> None:
        local = self._local_path(dataset, filename)
        uri = self._remote_uri(dataset, filename)
        args = ["s3", "cp", str(local), uri, "--only-show-errors"]
        last_exc: Exception | None = None
        for attempt in range(self.args.upload_retries + 1):
            try:
                self._run_aws(args, retry=0)
                return
            except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= self.args.upload_retries:
                    break
                _retry_sleep(attempt)
        raise RuntimeError(f"upload failed dataset={dataset} filename={filename}: {last_exc}")

    def _get_spec(self, path: Path) -> tuple[int, int, int]:
        inp = oiio.ImageInput.open(str(path))
        if inp is None:
            raise RuntimeError(f"failed to open spec for {path}")
        try:
            spec = inp.spec()
            return int(spec.width), int(spec.height), int(spec.nchannels)
        finally:
            inp.close()

    def _read_rgb_exr(self, path: Path) -> np.ndarray:
        try:
            exr = OpenEXR.File(str(path))
            part = exr.parts[0]
            ch = part.channels
            if "RGB" in ch:
                arr = np.asarray(ch["RGB"].pixels, dtype=np.float32)
            elif all(k in ch for k in ("R", "G", "B")):
                r = np.asarray(ch["R"].pixels, dtype=np.float32)
                g = np.asarray(ch["G"].pixels, dtype=np.float32)
                b = np.asarray(ch["B"].pixels, dtype=np.float32)
                arr = np.stack((r, g, b), axis=2)
            else:
                raise RuntimeError("missing RGB channels")
            if arr.ndim == 2:
                arr = np.repeat(arr[:, :, None], 3, axis=2)
            if arr.shape[2] > 3:
                arr = arr[:, :, :3]
            return arr.astype(np.float32, copy=False)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            buf = oiio.ImageBuf(str(path))
            if buf.has_error():
                raise RuntimeError(f"read failed {path}: {buf.geterror()}")
            arr = np.asarray(buf.get_pixels(oiio.FLOAT), dtype=np.float32)
            if arr.ndim == 2:
                arr = np.repeat(arr[:, :, None], 3, axis=2)
            if arr.ndim == 3 and arr.shape[2] >= 3:
                return arr[:, :, :3]
            raise RuntimeError(f"unexpected rgb exr shape for {path}: {arr.shape}")

    def _read_scalar_exr(self, path: Path) -> np.ndarray:
        try:
            exr = OpenEXR.File(str(path))
            part = exr.parts[0]
            ch = part.channels
            if "R" in ch:
                arr = np.asarray(ch["R"].pixels, dtype=np.float32)
            elif "RGB" in ch:
                arr = np.asarray(ch["RGB"].pixels, dtype=np.float32)
                if arr.ndim == 3:
                    arr = arr[:, :, 0]
            else:
                first = next(iter(ch.keys()))
                arr = np.asarray(ch[first].pixels, dtype=np.float32)
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            return arr.astype(np.float32, copy=False)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            buf = oiio.ImageBuf(str(path))
            if buf.has_error():
                raise RuntimeError(f"read failed {path}: {buf.geterror()}")
            arr = np.asarray(buf.get_pixels(oiio.FLOAT), dtype=np.float32)
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            return arr.astype(np.float32, copy=False)

    def _read_scalar_tif(self, path: Path) -> np.ndarray:
        buf = oiio.ImageBuf(str(path))
        if buf.has_error():
            raise RuntimeError(f"read failed {path}: {buf.geterror()}")
        arr = np.asarray(buf.get_pixels(oiio.FLOAT), dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        return arr.astype(np.float32, copy=False)

    def _write_rgb_exr(self, path: Path, image: np.ndarray, compression) -> None:
        _ensure_parent(path)
        im = np.asarray(image, dtype=np.float32)
        if im.ndim != 3 or im.shape[2] < 3:
            raise RuntimeError(f"expected rgb image for {path}, got {im.shape}")
        im = im[:, :, :3]
        if compression == OpenEXR.DWAA_COMPRESSION:
            np.clip(im, 0.001, 1.0, out=im)
        else:
            np.clip(im, 0.0, 1.0, out=im)
        rgb16 = np.ascontiguousarray(im.astype(np.float16, copy=False))
        tmp = Path(str(path) + ".tmp")
        header = {"compression": compression, "type": OpenEXR.scanlineimage}
        with OpenEXR.File(header, {"RGB": rgb16}) as out:
            out.write(str(tmp))
        tmp.replace(path)

    def _write_scalar_exr(self, path: Path, image: np.ndarray, compression) -> None:
        _ensure_parent(path)
        im = np.asarray(image, dtype=np.float32)
        if im.ndim == 3:
            im = im[:, :, 0]
        if im.ndim != 2:
            raise RuntimeError(f"expected scalar image for {path}, got {im.shape}")
        np.clip(im, 0.0, 1.0, out=im)
        r16 = np.ascontiguousarray(im.astype(np.float16, copy=False))
        tmp = Path(str(path) + ".tmp")
        header = {"compression": compression, "type": OpenEXR.scanlineimage}
        with OpenEXR.File(header, {"R": r16}) as out:
            out.write(str(tmp))
        tmp.replace(path)

    def _write_scalar_tif(self, path: Path, image: np.ndarray) -> None:
        _ensure_parent(path)
        im = np.asarray(image, dtype=np.float32)
        if im.ndim == 3:
            im = im[:, :, 0]
        np.clip(im, 0.0, 1.0, out=im)
        data = np.ascontiguousarray(np.rint(im * 255.0).astype(np.uint8, copy=False))
        tmp = Path(str(path) + ".tmp")
        out = oiio.ImageOutput.create(str(tmp))
        if out is None:
            raise RuntimeError(f"failed creating output for {tmp}")
        spec = oiio.ImageSpec(int(data.shape[1]), int(data.shape[0]), 1, oiio.UINT8)
        spec.attribute("compression", "lzw")
        if not out.open(str(tmp), spec):
            err = out.geterror()
            out.close()
            raise RuntimeError(f"failed opening tif {tmp}: {err}")
        if not out.write_image(data):
            err = out.geterror()
            out.close()
            raise RuntimeError(f"failed writing tif {tmp}: {err}")
        out.close()
        tmp.replace(path)

    def _ensure_local_from_remote(self, dataset: str, filename: str) -> bool:
        key = self.remote_key_by_name.get((dataset, filename))
        if not key:
            return False
        local = self._local_path(dataset, filename)
        if local.is_file():
            return True
        _ensure_parent(local)
        uri = f"s3://{self.bucket}/{key}"
        args = ["s3", "cp", uri, str(local), "--only-show-errors"]
        for attempt in range(self.args.download_retries + 1):
            try:
                self._run_aws(args, retry=0)
                return local.is_file()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                if attempt >= self.args.download_retries:
                    break
                _retry_sleep(attempt)
        return False

    def _load_fallbacks(self) -> None:
        if self._fallback_rgb or self._fallback_scalar:
            return
        with self._fallback_lock:
            if self._fallback_rgb or self._fallback_scalar:
                return
            # S2 fallbacks
            s2_ocean = Path(
                "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
                "user_default/Planetka/Resources/Fallback Images/ocean_pixel_final_20.exr"
            )
            s2_white = Path(
                "/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/"
                "user_default/Planetka/Resources/Fallback Images/white_pixel_20.exr"
            )
            # WT/EL/PO shared fb set
            blue = Path("/Volumes/SSDA/Planetka Assets Extra/FB/blue_pixel_20.exr")
            red = Path("/Volumes/SSDA/Planetka Assets Extra/FB/red_pixel_20.exr")
            black = Path("/Volumes/SSDA/Planetka Assets Extra/FB/black_pixel_20.exr")

            self._fallback_rgb["S2_OCEAN"] = self._read_rgb_exr(s2_ocean)
            self._fallback_rgb["S2_WHITE"] = self._read_rgb_exr(s2_white)
            self._fallback_rgb["WT_BLUE"] = self._read_rgb_exr(blue)
            self._fallback_rgb["WT_RED"] = self._read_rgb_exr(red)
            self._fallback_rgb["WT_BLACK"] = self._read_rgb_exr(black)
            self._fallback_scalar["EL_BLACK"] = self._read_scalar_exr(black)
            self._fallback_scalar["PO_BLACK"] = self._read_scalar_exr(black)

    def _wt_fallback_rgb(self, x: int, y: int, z: int) -> np.ndarray:
        xw = _wrap_x(x)
        if int(y) <= 9:
            return self._fallback_rgb["WT_BLACK"]
        if 46 <= xw <= 55 and 125 <= int(y) <= 140:
            return self._fallback_rgb["WT_BLUE"]
        if (226 <= xw <= 236 and 125 <= int(y) <= 139) or (86 <= xw <= 98 and 134 <= int(y) <= 142):
            return self._fallback_rgb["WT_RED"]
        return self._fallback_rgb["WT_BLUE"]

    def _read_or_fallback(self, dataset: str, x: int, y: int, z: int, d_eff: int):
        xw = _wrap_x(x)
        ext = self.dataset_ext.get(dataset, "exr")
        name = self._name(dataset, xw, int(y), int(z), int(d_eff))
        path = self._local_path(dataset, name)
        if path.is_file():
            return self._read_image(dataset, path)
        # If the exact source is part of manifest but missing locally, try remote fetch once.
        if self._ensure_local_from_remote(dataset, name) and path.is_file():
            return self._read_image(dataset, path)
        # Missing is acceptable and uses dataset-specific fallback.
        self._load_fallbacks()
        if dataset == "S2":
            if int(y) + int(z) < 9:
                return self._fallback_rgb["S2_WHITE"]
            return self._fallback_rgb["S2_OCEAN"]
        if dataset == "WT":
            return self._wt_fallback_rgb(xw, int(y), int(z))
        if dataset == "EL":
            return self._fallback_scalar["EL_BLACK"]
        if dataset == "PO":
            return self._fallback_scalar["PO_BLACK"]
        raise RuntimeError(f"unknown dataset for fallback: {dataset}")

    def _read_image(self, dataset: str, path: Path):
        if dataset in ("S2", "WT"):
            return self._read_rgb_exr(path)
        if dataset == "EL":
            return self._read_scalar_exr(path)
        if dataset == "PO":
            return self._read_scalar_tif(path)
        raise RuntimeError(f"unknown dataset: {dataset}")

    def _write_image(self, dataset: str, path: Path, image) -> None:
        if dataset == "S2":
            self._write_rgb_exr(path, image, OpenEXR.DWAA_COMPRESSION)
            return
        if dataset == "WT":
            self._write_rgb_exr(path, image, OpenEXR.ZIP_COMPRESSION)
            return
        if dataset == "EL":
            self._write_scalar_exr(path, image, OpenEXR.ZIP_COMPRESSION)
            return
        if dataset == "PO":
            self._write_scalar_tif(path, image)
            return
        raise RuntimeError(f"unknown dataset: {dataset}")

    def _resize(self, dataset: str, image, width: int, height: int):
        src_h = int(image.shape[0])
        src_w = int(image.shape[1])
        dst_w = int(width)
        dst_h = int(height)
        if src_w == dst_w and src_h == dst_h:
            return image
        if dataset == "WT":
            interp = cv2.INTER_LINEAR
        else:
            if dst_w <= src_w and dst_h <= src_h and (dst_w < src_w or dst_h < src_h):
                interp = cv2.INTER_AREA
            else:
                interp = cv2.INTER_LINEAR
        out = cv2.resize(image, (dst_w, dst_h), interpolation=interp)
        return out

    def _ensure_target_spec(self, task: Task, local_path: Path) -> tuple[int, int, int]:
        if not local_path.is_file():
            self._ensure_local_from_remote(task.dataset, task.filename)
        if local_path.is_file():
            return self._get_spec(local_path)
        # Fallback inference if target isn't locally available.
        if task.kind == "d":
            base_d = 1 if task.z == 1 else task.z
            src_name = self._name(task.dataset, task.x, task.y, task.z, base_d)
            src_path = self._local_path(task.dataset, src_name)
            if not src_path.is_file():
                self._ensure_local_from_remote(task.dataset, src_name)
            if src_path.is_file():
                sw, sh, ch = self._get_spec(src_path)
                scale = float(base_d) / float(task.d_eff)
                return max(1, int(round(sw * scale))), max(1, int(round(sh * scale))), ch
        raise RuntimeError(f"target spec unavailable for {task.dataset} {task.filename}")

    def _build_base(self, task: Task, local_path: Path) -> None:
        src_z = int(Z_BASE_SOURCE.get(int(task.z), int(task.z)))
        if int(task.z) <= 1:
            raise RuntimeError(f"invalid base task z={task.z}")
        if int(task.z) % int(src_z) != 0:
            raise RuntimeError(f"z/source mismatch target_z={task.z} src_z={src_z}")
        ratio_x = int(task.z) // int(src_z)
        # z360 spans full longitude but only half latitude (2:1), so Y source grid is half of X.
        ratio_y = ratio_x // 2 if int(task.z) == 360 else ratio_x
        if ratio_y <= 0:
            raise RuntimeError(f"invalid source ratio target_z={task.z} src_z={src_z}")
        tw, th, ch = self._ensure_target_spec(task, local_path)
        x_edges = _edge_positions(tw, ratio_x)
        y_edges = _edge_positions(th, ratio_y)

        if task.dataset in ("S2", "WT"):
            out = np.zeros((th, tw, 3), dtype=np.float32)
        else:
            out = np.zeros((th, tw), dtype=np.float32)

        for y_idx in range(ratio_y):
            for x_idx in range(ratio_x):
                sx = int(task.x) + x_idx * src_z
                sy = int(task.y) + y_idx * src_z
                src = self._read_or_fallback(task.dataset, sx, sy, src_z, src_z)
                dx0 = int(x_edges[x_idx])
                dx1 = int(x_edges[x_idx + 1])
                # Invert Y placement to match existing generation orientation.
                dy0 = int(y_edges[ratio_y - 1 - y_idx])
                dy1 = int(y_edges[ratio_y - y_idx])
                cw = max(1, dx1 - dx0)
                chh = max(1, dy1 - dy0)
                rs = self._resize(task.dataset, src, cw, chh)
                out[dy0:dy1, dx0:dx1] = rs

        self._write_image(task.dataset, local_path, out)

    def _build_d(self, task: Task, local_path: Path) -> None:
        base_d = 1 if int(task.z) == 1 else int(task.z)
        src_name = self._name(task.dataset, int(task.x), int(task.y), int(task.z), base_d)
        src = self._read_or_fallback(task.dataset, int(task.x), int(task.y), int(task.z), int(base_d))
        tw, th, _ = self._ensure_target_spec(task, local_path)
        out = self._resize(task.dataset, src, tw, th)
        self._write_image(task.dataset, local_path, out)

    def _task_iter(self) -> Iterable[Task]:
        cur = self.conn.cursor()
        q = """
        SELECT dataset, filename, x, y, z, d_eff, ext, kind
        FROM tasks
        WHERE status IN ('pending','failed')
        ORDER BY
          CASE z
            WHEN 1 THEN 1
            WHEN 2 THEN 2
            WHEN 4 THEN 3
            WHEN 8 THEN 4
            WHEN 15 THEN 5
            WHEN 16 THEN 6
            WHEN 30 THEN 7
            WHEN 32 THEN 8
            WHEN 60 THEN 9
            WHEN 90 THEN 10
            WHEN 180 THEN 11
            WHEN 360 THEN 12
            ELSE 99
          END ASC,
          CASE kind WHEN 'base' THEN 0 ELSE 1 END ASC,
          y ASC, x ASC, dataset ASC, d_eff ASC
        """
        for row in cur.execute(q):
            yield Task(
                dataset=str(row["dataset"]),
                filename=str(row["filename"]),
                x=int(row["x"]),
                y=int(row["y"]),
                z=int(row["z"]),
                d_eff=int(row["d_eff"]),
                ext=str(row["ext"]).lower(),
                kind=str(row["kind"]),
            )

    def _tasks_for_kind(self, kind: str) -> list[Task]:
        cur = self.conn.cursor()
        q = """
        SELECT dataset, filename, x, y, z, d_eff, ext, kind
        FROM tasks
        WHERE status IN ('pending','failed') AND kind=?
        ORDER BY
          CASE z
            WHEN 1 THEN 1
            WHEN 2 THEN 2
            WHEN 4 THEN 3
            WHEN 8 THEN 4
            WHEN 15 THEN 5
            WHEN 16 THEN 6
            WHEN 30 THEN 7
            WHEN 32 THEN 8
            WHEN 60 THEN 9
            WHEN 90 THEN 10
            WHEN 180 THEN 11
            WHEN 360 THEN 12
            ELSE 99
          END ASC,
          y ASC, x ASC, dataset ASC, d_eff ASC
        """
        out: list[Task] = []
        for row in cur.execute(q, (kind,)):
            out.append(
                Task(
                    dataset=str(row["dataset"]),
                    filename=str(row["filename"]),
                    x=int(row["x"]),
                    y=int(row["y"]),
                    z=int(row["z"]),
                    d_eff=int(row["d_eff"]),
                    ext=str(row["ext"]).lower(),
                    kind=str(row["kind"]),
                )
            )
        return out

    def _set_status(self, task: Task, status: str, error: str = "", attempts_inc: bool = False) -> None:
        cur = self.conn.cursor()
        if attempts_inc:
            cur.execute(
                """
                UPDATE tasks
                SET status=?, attempts=attempts+1, last_error=?, updated_at=?
                WHERE dataset=? AND filename=?
                """,
                (status, error[:8000], _ts(), task.dataset, task.filename),
            )
        else:
            cur.execute(
                """
                UPDATE tasks
                SET status=?, last_error=?, updated_at=?
                WHERE dataset=? AND filename=?
                """,
                (status, error[:8000], _ts(), task.dataset, task.filename),
            )
        self.conn.commit()

    def _execute_task(self, task: Task) -> tuple[bool, str]:
        local_path = self._local_path(task.dataset, task.filename)
        last_error = ""
        for attempt in range(self.args.task_retries + 1):
            try:
                if task.kind == "base":
                    self._build_base(task, local_path)
                else:
                    self._build_d(task, local_path)
                self._upload_file(task.dataset, task.filename)
                return True, ""
            except TOOL_RECOVERABLE_EXCEPTIONS as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt >= self.args.task_retries:
                    break
                _retry_sleep(attempt)
        return False, last_error

    def _count_status(self) -> tuple[int, int, int]:
        cur = self.conn.cursor()
        done_now = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0])
        remaining = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('pending','failed')").fetchone()[0])
        failed_now = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status='failed'").fetchone()[0])
        return done_now, remaining, failed_now

    def _run_task_list(self, tasks: list[Task], workers: int, processed: int, started: float, total: int) -> tuple[int, int]:
        if not tasks:
            return processed, 0
        failed_stage = 0
        progress_every = max(1, int(self.args.progress_every))

        if int(workers) <= 1:
            for task in tasks:
                self._set_status(task, "in_progress", attempts_inc=True)
                ok, err = self._execute_task(task)
                if ok:
                    self._set_status(task, "done", "")
                    processed += 1
                else:
                    failed_stage += 1
                    self._set_status(task, "failed", err)
                    self._log(
                        f"[run] FAIL dataset={task.dataset} file={task.filename} "
                        f"kind={task.kind} error={err}"
                    )
                    self._event(
                        "task_failed",
                        dataset=task.dataset,
                        filename=task.filename,
                        kind=task.kind,
                        error=err,
                    )
                if processed % progress_every == 0:
                    done_now, remaining, _ = self._count_status()
                    elapsed = time.perf_counter() - started
                    self._log(
                        f"[run] progress processed={processed} done_total={done_now}/{total} "
                        f"remaining={remaining} elapsed={elapsed:.1f}s"
                    )
            return processed, failed_stage

        submit_idx = 0
        in_flight: dict[cf.Future, Task] = {}
        with cf.ThreadPoolExecutor(max_workers=int(workers)) as executor:
            while submit_idx < len(tasks) or in_flight:
                while submit_idx < len(tasks) and len(in_flight) < int(workers) * 2:
                    task = tasks[submit_idx]
                    submit_idx += 1
                    self._set_status(task, "in_progress", attempts_inc=True)
                    fut = executor.submit(self._execute_task, task)
                    in_flight[fut] = task
                if not in_flight:
                    continue
                done_set, _ = cf.wait(in_flight.keys(), return_when=cf.FIRST_COMPLETED)
                for fut in done_set:
                    task = in_flight.pop(fut)
                    ok, err = fut.result()
                    if ok:
                        self._set_status(task, "done", "")
                        processed += 1
                    else:
                        failed_stage += 1
                        self._set_status(task, "failed", err)
                        self._log(
                            f"[run] FAIL dataset={task.dataset} file={task.filename} "
                            f"kind={task.kind} error={err}"
                        )
                        self._event(
                            "task_failed",
                            dataset=task.dataset,
                            filename=task.filename,
                            kind=task.kind,
                            error=err,
                        )
                    if processed % progress_every == 0:
                        done_now, remaining, _ = self._count_status()
                        elapsed = time.perf_counter() - started
                        self._log(
                            f"[run] progress processed={processed} done_total={done_now}/{total} "
                            f"remaining={remaining} elapsed={elapsed:.1f}s"
                        )
        return processed, failed_stage

    def _run_stage(self, kind: str, workers: int, processed: int, started: float, total: int) -> tuple[int, int]:
        tasks = self._tasks_for_kind(kind)
        if not tasks:
            self._log(f"[run] stage={kind} workers={workers} tasks=0")
            return processed, 0
        self._log(f"[run] stage={kind} workers={workers} tasks={len(tasks)}")
        if kind != "base":
            return self._run_task_list(tasks, int(workers), processed, started, total)

        # Base-stage worker policy: use the stage worker count for all z-levels.
        workers_by_z: dict[int, int] = {}
        default_higher_z_workers = int(workers)
        by_z: dict[int, list[Task]] = {}
        for t in tasks:
            z = int(t.z)
            by_z.setdefault(z, []).append(t)
        failed_stage = 0

        z_order_idx = {z: i for i, z in enumerate(Z_ORDER)}
        for z in sorted(by_z.keys(), key=lambda zz: z_order_idx.get(int(zz), 10_000 + int(zz))):
            batch = by_z.get(z, [])
            if not batch:
                continue
            z_workers = int(workers_by_z.get(int(z), default_higher_z_workers))
            self._log(f"[run] substage=base_z{int(z):03d} workers={z_workers} tasks={len(batch)}")
            processed, failed = self._run_task_list(batch, z_workers, processed, started, total)
            failed_stage += failed

        return processed, failed_stage

    def run(self) -> int:
        self._reload_manifest_cache()
        cur = self.conn.cursor()
        total = int(cur.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
        done = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0])
        pending = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('pending','failed')").fetchone()[0])
        self._log(
            f"[run] tasks total={total} done={done} pending={pending} "
            f"workers_base={self.args.workers_base} workers_d={self.args.workers_d}"
        )
        self._event("run_start", total=total, done=done, pending=pending)
        if pending == 0:
            self._log("[run] nothing to do")
            self._event("run_done", total=total, done=done, pending=0, failed=0)
            return 0

        processed = done
        failed = 0
        started = time.perf_counter()
        processed, failed_base = self._run_stage("base", int(self.args.workers_base), processed, started, total)
        failed += failed_base
        processed, failed_d = self._run_stage("d", int(self.args.workers_d), processed, started, total)
        failed += failed_d

        done_final = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0])
        failed_final = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status='failed'").fetchone()[0])
        remaining_final = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0])
        elapsed = time.perf_counter() - started
        self._log(
            f"[run] finished done={done_final}/{total} failed={failed_final} "
            f"pending={remaining_final} elapsed={elapsed:.1f}s"
        )
        self._event(
            "run_done",
            total=total,
            done=done_final,
            failed=failed_final,
            pending=remaining_final,
            elapsed_sec=elapsed,
        )
        return 1 if failed_final or remaining_final else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Single-core resumable full rebuild for S2/EL/WT/PO higher-z/higher-d tiles "
            "using direct-from-lowest-d policy with immediate Cloud upload."
        )
    )
    parser.add_argument("--assets-root", default="/Volumes/SSDA/Planetka Assets", help="Root with S2/EL/WT/PO folders")
    parser.add_argument(
        "--state-dir",
        default="/Volumes/SSDA/Planetka Assets/.rebuild_direct_lowd_state",
        help="Persistent state/log directory",
    )
    parser.add_argument("--bucket", default="planetka-data")
    parser.add_argument("--prefix-root", default="planetka-assets")
    parser.add_argument("--profile", default="planetka-r2")
    parser.add_argument(
        "--secrets-file",
        default=f"{Path.home()}/.planetka/secrets/Cloudflare_API_from_stash_2026-03-17.txt",
    )
    parser.add_argument("--refresh-manifest", action="store_true", help="Re-fetch remote manifest from Cloud")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare manifest/tasks and exit")
    parser.add_argument("--prune-local-extras", action="store_true", help="Delete local files not present in remote manifest")
    parser.add_argument("--task-retries", type=int, default=2, help="Per-task generation/upload retries")
    parser.add_argument("--upload-retries", type=int, default=3, help="Retries for single-file upload")
    parser.add_argument("--download-retries", type=int, default=2, help="Retries for lazy source/target download")
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--workers-base", type=int, default=1, help="Worker count for higher-z base stage")
    parser.add_argument("--workers-d", type=int, default=8, help="Worker count for higher-d stage")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pipeline = Pipeline(args)
    try:
        cur = pipeline.conn.cursor()
        manifest_count = int(cur.execute("SELECT COUNT(*) FROM manifest").fetchone()[0])
        if args.refresh_manifest or manifest_count == 0:
            pipeline.refresh_manifest()
        else:
            pipeline._reload_manifest_cache()
            pipeline._log(f"[manifest] using existing sqlite manifest rows={manifest_count}")

        pipeline.sync_tasks()
        if args.prune_local_extras:
            pipeline.prune_local_extras()

        if args.prepare_only:
            cur = pipeline.conn.cursor()
            total = int(cur.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
            done = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0])
            pending = int(cur.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('pending','failed')").fetchone()[0])
            pipeline._log(f"[prepare] ready total={total} done={done} pending={pending}")
            return 0

        return pipeline.run()
    finally:
        pipeline.close()


if __name__ == "__main__":
    raise SystemExit(main())
