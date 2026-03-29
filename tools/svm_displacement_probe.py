#!/usr/bin/env python3
"""Probe whether SVM overflow is tied to displacement wiring.

Example:
  blender --background Cairo.blend --python tools/svm_displacement_probe.py -- --variant v1 --tiles 13 --mode no_displacement
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

import addon_utils
import bpy


def _parse_args() -> argparse.Namespace:
    argv = []
    if "--" in os.sys.argv:
        argv = os.sys.argv[os.sys.argv.index("--") + 1 :]
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=("v1", "v1_no_el", "v1_el_like_wt"), default="v1")
    p.add_argument("--tiles", type=int, default=13)
    p.add_argument("--mode", choices=("full", "no_displacement", "displacement_only"), default="full")
    p.add_argument("--s2-image-path", default="")
    p.add_argument("--el-image-path", default="")
    return p.parse_args(argv)


def _load_experiment_module(path: Path):
    spec = importlib.util.spec_from_file_location("svm_loading_group_experiment", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _get_socket(node, name):
    return node.outputs.get(name)


def main() -> None:
    args = _parse_args()
    addon_utils.enable("bl_ext.user_default.Planetka", default_set=False, persistent=False)

    from bl_ext.user_default.Planetka import asset_builder, shader_utils, tile_utils

    scene = bpy.context.scene
    asset_builder.ensure_planetka_assets(scene)
    tiles = list(tile_utils.main(scope_mode="CAMERA")[: max(1, int(args.tiles))])

    experiment_py = Path(__file__).with_name("svm_loading_group_experiment.py")
    exp = _load_experiment_module(experiment_py)

    addon_dir = Path(__file__).resolve().parents[1]
    images = exp._load_fallback_images(
        addon_dir,
        overrides={
            "S2": args.s2_image_path,
            "EL": args.el_image_path,
            "WT": "",
            "PO": "",
        },
    )
    placement_group = shader_utils._ensure_tile_placement_group("regular")
    group_name = f"Planetka Displacement Probe - {args.variant}"
    loading_group = exp._build_variant_group(
        group_name=group_name,
        variant=args.variant,
        tiles=tiles,
        parse_tile=shader_utils.parse_tile,
        placement_group=placement_group,
        images=images,
    )

    material = bpy.data.materials.get("Planetka Earth Material")
    if material is None or material.node_tree is None:
        raise RuntimeError("Planetka Earth Material missing")
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links

    loading_node = nodes.get("Planetka Textures Loading")
    shading_node = nodes.get("Group")
    output_node = nodes.get("Material Output")
    if loading_node is None or shading_node is None or output_node is None:
        raise RuntimeError("Required nodes missing (Planetka Textures Loading / Group / Material Output)")

    loading_node.node_tree = loading_group

    # Clear material output links.
    for l in list(links):
        if l.to_node == output_node and l.to_socket.name in {"Surface", "Displacement"}:
            links.remove(l)

    if args.mode in {"full", "no_displacement"}:
        shader_out = _get_socket(shading_node, "Shader")
        if shader_out is not None:
            links.new(shader_out, output_node.inputs["Surface"])

    if args.mode in {"full", "displacement_only"}:
        disp_out = _get_socket(shading_node, "Displacement")
        if disp_out is not None:
            links.new(disp_out, output_node.inputs["Displacement"])

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180

    print(
        "DISP_PROBE_META",
        json.dumps(
            {
                "variant": args.variant,
                "mode": args.mode,
                "tiles": len(tiles),
                "node_count": len(loading_group.nodes),
                "link_count": len(loading_group.links),
            },
            sort_keys=True,
        ),
    )
    print("DISP_PROBE_RENDER_START")
    bpy.ops.render.render(write_still=False)
    print("DISP_PROBE_RENDER_DONE")


if __name__ == "__main__":
    main()
