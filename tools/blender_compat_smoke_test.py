#!/usr/bin/env python3
"""Smoke check for Blender 6 compatibility-sensitive patterns."""

from __future__ import annotations

import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = (
    "asset_builder.py",
    "operators.py",
    "render_prep.py",
    "mesh_utils.py",
    "animation_tools.py",
    "clouds_global.py",
    "clouds_local.py",
    "ui.py",
    "validation.py",
    "planetka_ops/scene_setup_ops.py",
    "tools/planetka_e2e_common.py",
)
DEPRECATED_PATTERN = re.compile(r"\buse_nodes\b")


def main() -> int:
    violations: list[str] = []
    for rel_path in TARGETS:
        file_path = ROOT / rel_path
        if not file_path.is_file():
            violations.append(f"missing file: {file_path}")
            continue
        for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            if DEPRECATED_PATTERN.search(line):
                violations.append(f"{file_path}:{line_no}: contains deprecated use_nodes reference")
    if violations:
        print("Blender compatibility smoke check FAILED:")
        for item in violations:
            print(f"- {item}")
        return 1
    print("Blender compatibility smoke check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
