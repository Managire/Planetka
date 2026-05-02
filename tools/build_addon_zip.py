#!/usr/bin/env python3
"""Build a deterministic Planetka addon zip from an explicit allowlist.

The package is staged outside the repo root path and zipped from the staging
payload, never from the repository itself. SQLite files are snapshotted into
standalone databases so `-wal` / `-shm` sidecars never leak into the package.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = ROOT / "package_allowlist_public.txt"
DEFAULT_STAGE_ROOT = ROOT / ".build" / "staging"
DEFAULT_DIST_DIR = ROOT / "dist"
FORBIDDEN_STAGE_NAMES = {
    ".ds_store",
}
FORBIDDEN_STAGE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".log",
    ".zip",
    ".wal",
    ".shm",
}


def _read_manifest() -> dict:
    manifest_path = ROOT / "blender_manifest.toml"
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required to read blender_manifest.toml")
    with manifest_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("blender_manifest.toml is invalid")
    return payload


def _sanitize_output_stem(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    return safe.strip("._") or "Planetka"


def _load_allowlist(path: Path) -> list[Path]:
    entries: list[Path] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if any(token in line for token in ("*", "?", "[", "]")):
                raise RuntimeError(f"Wildcards are not allowed in allowlist: {line}")
            rel = Path(line)
            if rel.is_absolute():
                raise RuntimeError(f"Allowlist entry must be repo-relative: {line}")
            normalized = rel.as_posix()
            if normalized.startswith("../") or normalized == "..":
                raise RuntimeError(f"Allowlist entry escapes repo root: {line}")
            if normalized in seen:
                continue
            seen.add(normalized)
            entries.append(rel)
    if not entries:
        raise RuntimeError("Allowlist is empty")
    return entries


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _snapshot_sqlite(src: Path, dst: Path) -> None:
    _ensure_parent(dst)
    tmp = dst.with_suffix(f"{dst.suffix}.tmp")
    if tmp.exists():
        tmp.unlink()
    source_uri = f"file:{src.resolve().as_posix()}?mode=ro"
    src_conn = sqlite3.connect(source_uri, uri=True)
    dst_conn = sqlite3.connect(str(tmp))
    try:
        src_conn.backup(dst_conn)
        dst_conn.commit()
    finally:
        dst_conn.close()
        src_conn.close()
    os.replace(tmp, dst)


def _copy_allowlisted_file(src: Path, dst: Path) -> None:
    if src.is_symlink():
        raise RuntimeError(f"Symlinks are not allowed in package input: {src}")
    if src.suffix.lower() in {".sqlite", ".sqlite3"}:
        _snapshot_sqlite(src, dst)
        return
    _ensure_parent(dst)
    shutil.copy2(src, dst)


def _iter_stage_files(payload_root: Path) -> list[Path]:
    return sorted(path for path in payload_root.rglob("*") if path.is_file())


def _validate_stage(payload_root: Path, expected_files: set[str]) -> None:
    actual_files = {path.relative_to(payload_root).as_posix() for path in _iter_stage_files(payload_root)}
    missing = sorted(expected_files - actual_files)
    unexpected = sorted(actual_files - expected_files)
    if missing:
        raise RuntimeError(f"Stage is missing allowlisted files: {missing}")
    if unexpected:
        raise RuntimeError(f"Stage contains unexpected files: {unexpected}")

    for rel in sorted(actual_files):
        leaf = Path(rel).name.lower()
        suffix = Path(rel).suffix.lower()
        if leaf in FORBIDDEN_STAGE_NAMES:
            raise RuntimeError(f"Forbidden file staged: {rel}")
        if suffix in FORBIDDEN_STAGE_SUFFIXES:
            raise RuntimeError(f"Forbidden staged suffix for {rel}")
        if "__pycache__" in Path(rel).parts:
            raise RuntimeError(f"__pycache__ content staged: {rel}")


def _zip_payload(payload_root: Path, zip_path: Path) -> tuple[int, int]:
    _ensure_parent(zip_path)
    if zip_path.exists():
        zip_path.unlink()
    file_count = 0
    total_bytes = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in _iter_stage_files(payload_root):
            rel = file_path.relative_to(payload_root).as_posix()
            zf.write(file_path, arcname=rel)
            stat = file_path.stat()
            file_count += 1
            total_bytes += int(stat.st_size)
    return file_count, total_bytes


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text(path: Path, text: str) -> None:
    _ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_package(allowlist_path: Path, stage_root: Path, output_path: Path, keep_stage: bool) -> dict:
    manifest = _read_manifest()
    addon_id = str(manifest.get("id") or "planetka").strip() or "planetka"
    version = str(manifest.get("version") or "0").strip() or "0"
    allowlist_entries = _load_allowlist(allowlist_path)

    stage_dir = stage_root / f"{addon_id}_{version}"
    payload_root = stage_dir / "payload"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    payload_root.mkdir(parents=True, exist_ok=True)

    expected_files: set[str] = set()
    for rel in allowlist_entries:
        src = ROOT / rel
        if not src.is_file():
            raise RuntimeError(f"Allowlisted file is missing: {rel.as_posix()}")
        dst = payload_root / rel
        _copy_allowlisted_file(src, dst)
        expected_files.add(rel.as_posix())

    _validate_stage(payload_root, expected_files)
    file_count, total_bytes = _zip_payload(payload_root, output_path)
    sha256 = _sha256_file(output_path)

    filelist_path = output_path.with_suffix(".filelist.txt")
    sha_path = output_path.with_suffix(".sha256")
    manifest_path = output_path.with_suffix(".manifest.json")

    staged_files = [path.relative_to(payload_root).as_posix() for path in _iter_stage_files(payload_root)]
    _write_text(filelist_path, "\n".join(staged_files) + "\n")
    _write_text(sha_path, f"{sha256}  {output_path.name}\n")
    _write_text(
        manifest_path,
        "{\n"
        f'  "addon_id": "{addon_id}",\n'
        f'  "version": "{version}",\n'
        f'  "allowlist": "{allowlist_path.relative_to(ROOT).as_posix()}",\n'
        f'  "zip_path": "{_display_path(output_path)}",\n'
        f'  "stage_path": "{_display_path(stage_dir)}",\n'
        f'  "file_count": {file_count},\n'
        f'  "total_uncompressed_bytes": {total_bytes},\n'
        f'  "sha256": "{sha256}"\n'
        "}\n",
    )

    result = {
        "addon_id": addon_id,
        "version": version,
        "output_path": output_path,
        "stage_dir": stage_dir,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "sha256": sha256,
        "filelist_path": filelist_path,
        "sha_path": sha_path,
        "manifest_path": manifest_path,
    }

    if not keep_stage:
        shutil.rmtree(stage_dir)

    return result


def main(argv: list[str]) -> int:
    manifest = _read_manifest()
    version = str(manifest.get("version") or "0").strip() or "0"
    default_output = DEFAULT_DIST_DIR / f"{_sanitize_output_stem('Planetka')}_{version}_public.zip"

    parser = argparse.ArgumentParser(description="Build a deterministic Planetka addon zip from an explicit allowlist.")
    parser.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST), help="Path to explicit package allowlist")
    parser.add_argument("--stage-root", default=str(DEFAULT_STAGE_ROOT), help="Directory used for staging payload files")
    parser.add_argument("--output", default=str(default_output), help="Output zip path")
    parser.add_argument("--keep-stage", action="store_true", help="Keep staging directory after packaging")
    args = parser.parse_args(argv)

    result = build_package(
        allowlist_path=Path(args.allowlist).resolve(),
        stage_root=Path(args.stage_root).resolve(),
        output_path=Path(args.output).resolve(),
        keep_stage=bool(args.keep_stage),
    )

    print("Planetka package built")
    print(f"version: {result['version']}")
    print(f"zip: {result['output_path']}")
    print(f"sha256: {result['sha256']}")
    print(f"files: {result['file_count']}")
    print(f"size_bytes: {result['total_bytes']}")
    print(f"filelist: {result['filelist_path']}")
    print(f"manifest: {result['manifest_path']}")
    if args.keep_stage:
        print(f"stage: {result['stage_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
