#!/usr/bin/env python3
"""Validate texture files by checking naming and openability."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

try:
    import OpenImageIO as oiio
except Exception:  # pragma: no cover - optional dependency
    oiio = None

try:
    import OpenEXR
except Exception:  # pragma: no cover - optional dependency
    OpenEXR = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


DEFAULT_ROOT = Path("/Volumes/SSDA/Planetka Assets")
DEFAULT_EXTS = {".exr", ".tif", ".tiff"}
KNOWN_TILE_FOLDERS = {"S2", "WT", "EL", "PO", "WF"}
TILE_NAME_RE = re.compile(r"^[A-Z0-9]+_x\d{3}_y\d{3}_z\d{3}_d\d{3}\.[A-Za-z0-9]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a texture tree and report files that fail naming checks or "
            "cannot be opened."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"Asset root to scan (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--ext",
        action="append",
        default=[],
        help="Extension to include (repeatable). Default: .exr .tif .tiff",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and directories (dot-prefixed).",
    )
    parser.add_argument(
        "--check-name",
        action="store_true",
        help="Check tile naming convention in known tile folders.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=5000,
        help="Print progress every N files. Set 0 to disable.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only scan first N matching files (for quick tests). 0 = no limit.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="Write full failure list to JSON file.",
    )
    return parser.parse_args()


def _normalize_exts(raw_exts: list[str]) -> set[str]:
    if not raw_exts:
        return set(DEFAULT_EXTS)
    normalized = set()
    for ext in raw_exts:
        item = ext.strip().lower()
        if not item:
            continue
        if not item.startswith("."):
            item = "." + item
        normalized.add(item)
    return normalized or set(DEFAULT_EXTS)


def discover_files(
    root: Path, exts: set[str], include_hidden: bool, limit: int
) -> list[Path]:
    matches: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if not include_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not include_hidden and name.startswith("."):
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() not in exts:
                continue
            matches.append(path)
            if limit > 0 and len(matches) >= limit:
                return matches
    return matches


def can_open_oiio(path: Path) -> tuple[bool, str]:
    if oiio is None:
        return False, "OpenImageIO not available"
    inp = oiio.ImageInput.open(str(path))
    if inp is None:
        return False, "OpenImageIO failed to open"
    try:
        spec = inp.spec()
        if spec is None:
            return False, "OpenImageIO opened file but returned no image spec"
        if spec.width <= 0 or spec.height <= 0:
            return False, f"Invalid dimensions {spec.width}x{spec.height}"
        return True, ""
    finally:
        try:
            inp.close()
        except Exception:
            pass


def can_open_openexr(path: Path) -> tuple[bool, str]:
    if OpenEXR is None:
        return False, "OpenEXR not available"
    try:
        file_obj = OpenEXR.InputFile(str(path))
        file_obj.header()
        file_obj.close()
        return True, ""
    except Exception as exc:  # noqa: BLE001 - report all loader errors
        return False, f"OpenEXR failed: {exc}"


def can_open_pillow(path: Path) -> tuple[bool, str]:
    if Image is None:
        return False, "Pillow not available"
    try:
        with Image.open(path) as img:
            img.verify()
        return True, ""
    except Exception as exc:  # noqa: BLE001 - report all loader errors
        return False, f"Pillow failed: {exc}"


def choose_validator(path: Path) -> Callable[[Path], tuple[bool, str]]:
    suffix = path.suffix.lower()
    if oiio is not None:
        return can_open_oiio
    if suffix == ".exr":
        return can_open_openexr
    return can_open_pillow


def naming_error(path: Path) -> str:
    parent = path.parent.name
    if parent not in KNOWN_TILE_FOLDERS:
        return ""
    if TILE_NAME_RE.match(path.name):
        return ""
    return (
        "Invalid tile filename for known folder "
        f"'{parent}': {path.name}"
    )


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    exts = _normalize_exts(args.ext)

    if not root.exists():
        print(f"[FAIL] Root does not exist: {root}")
        return 2

    files = discover_files(root, exts, args.include_hidden, args.limit)
    total = len(files)
    print(f"Texture open check")
    print(f"- root: {root}")
    print(f"- matching files: {total}")
    print(f"- extensions: {', '.join(sorted(exts))}")

    failures: list[dict[str, str]] = []
    started = time.time()

    for idx, path in enumerate(files, start=1):
        if args.check_name:
            name_issue = naming_error(path)
            if name_issue:
                failures.append(
                    {
                        "path": str(path),
                        "reason": "name",
                        "detail": name_issue,
                    }
                )
                continue

        if path.stat().st_size <= 0:
            failures.append(
                {
                    "path": str(path),
                    "reason": "open",
                    "detail": "File size is zero bytes",
                }
            )
            continue

        validate = choose_validator(path)
        ok, message = validate(path)
        if not ok:
            failures.append(
                {
                    "path": str(path),
                    "reason": "open",
                    "detail": message,
                }
            )

        if args.progress_every > 0 and idx % args.progress_every == 0:
            elapsed = time.time() - started
            print(f"- scanned {idx}/{total} files ({elapsed:.1f}s)")

    elapsed = time.time() - started
    print(f"- finished in {elapsed:.1f}s")
    print(f"- failures: {len(failures)}")

    if failures:
        print("Sample failures:")
        for row in failures[:20]:
            print(f"  {row['path']} :: {row['detail']}")

    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(
                {
                    "root": str(root),
                    "total_files": total,
                    "failure_count": len(failures),
                    "failures": failures,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"- wrote report: {args.report_json}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
