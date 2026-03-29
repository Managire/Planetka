#!/usr/bin/env python3
"""Generate expected support-layer missing tile manifest.

The manifest captures PO/EL/WT filenames that are expected to be missing
while corresponding S2 tiles exist. This is for diagnostics classification
(so expected support fallback misses are not treated as failures).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Set

FILE_RE = re.compile(r"^(?P<layer>S2|EL|WT|PO)_x(?P<x>\d{3})_y(?P<y>\d{3})_z(?P<z>\d{3})_d(?P<d>\d{3})\.(?P<ext>exr|tif)$", re.IGNORECASE)


LAYER_EXT = {
    "S2": "exr",
    "EL": "exr",
    "WT": "exr",
    "PO": "tif",
}


def scan_layer_suffixes(layer_dir: str, layer_name: str) -> Set[str]:
    suffixes: Set[str] = set()
    if not os.path.isdir(layer_dir):
        return suffixes
    with os.scandir(layer_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            name = entry.name
            match = FILE_RE.match(name)
            if not match:
                continue
            if match.group("layer").upper() != layer_name:
                continue
            suffix = f"x{match.group('x')}_y{match.group('y')}_z{match.group('z')}_d{match.group('d')}"
            suffixes.add(suffix)
    return suffixes


def build_manifest(assets_root: str) -> Dict[str, object]:
    layer_suffixes: Dict[str, Set[str]] = {}
    for layer in ("S2", "EL", "WT", "PO"):
        layer_dir = os.path.join(assets_root, layer)
        layer_suffixes[layer] = scan_layer_suffixes(layer_dir, layer)

    s2_suffixes = layer_suffixes.get("S2", set())
    expected_missing = {}
    stats = {}

    for layer in ("EL", "WT", "PO"):
        missing_suffixes = sorted(s2_suffixes - layer_suffixes.get(layer, set()))
        ext = LAYER_EXT[layer]
        expected_missing[layer] = [f"{layer}_{suffix}.{ext}" for suffix in missing_suffixes]
        stats[layer] = {
            "s2_suffix_count": len(s2_suffixes),
            "layer_suffix_count": len(layer_suffixes.get(layer, set())),
            "expected_missing_count": len(missing_suffixes),
        }

    return {
        "version": "support-missing-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets_root": os.path.abspath(assets_root),
        "expected_missing": expected_missing,
        "stats": {
            "s2_suffix_count": len(s2_suffixes),
            "layers": stats,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate expected support missing manifest from Planetka Assets")
    parser.add_argument(
        "--assets-root",
        default="/Volumes/SSDA/Planetka Assets",
        help="Planetka assets root containing S2/EL/WT/PO folders",
    )
    parser.add_argument(
        "--output",
        default="/tmp/support_missing_manifest.json",
        help="Output JSON file path",
    )
    args = parser.parse_args()

    manifest = build_manifest(args.assets_root)
    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)

    stats = manifest.get("stats", {})
    layers = stats.get("layers", {}) if isinstance(stats, dict) else {}
    print(f"Wrote manifest: {output_path}")
    print(f"S2 suffixes: {stats.get('s2_suffix_count', 0)}")
    for layer in ("EL", "WT", "PO"):
        layer_stats = layers.get(layer, {}) if isinstance(layers, dict) else {}
        print(
            f"{layer}: present={layer_stats.get('layer_suffix_count', 0)} "
            f"expected_missing={layer_stats.get('expected_missing_count', 0)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
