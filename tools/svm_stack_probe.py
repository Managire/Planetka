#!/usr/bin/env python3
"""Isolate Cycles SVM overflow bottlenecks for Planetka texture-loading shader.

Usage:
  blender --background Cairo.blend --python tools/svm_stack_probe.py -- --scenario baseline_v3 --tiles 13
"""

from __future__ import annotations

import argparse
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
    p.add_argument("--scenario", required=True)
    p.add_argument("--tiles", type=int, required=True)
    return p.parse_args(argv)


def _linear_rgba_add(nodes, links, sockets):
    if not sockets:
        return None
    current = sockets[0]
    for src in sockets[1:]:
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "ADD"
        mix.inputs[0].default_value = 1.0
        links.new(current, mix.inputs[6])
        links.new(src, mix.inputs[7])
        current = mix.outputs[2]
    return current


def _balanced_rgba_add(nodes, links, sockets):
    if not sockets:
        return None
    layer = list(sockets)
    while len(layer) > 1:
        nxt = []
        i = 0
        while i < len(layer):
            if i + 1 >= len(layer):
                nxt.append(layer[i])
                i += 1
                continue
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "ADD"
            mix.inputs[0].default_value = 1.0
            links.new(layer[i], mix.inputs[6])
            links.new(layer[i + 1], mix.inputs[7])
            nxt.append(mix.outputs[2])
            i += 2
        layer = nxt
    return layer[0]


def _load_images(addon_dir: Path):
    fb = addon_dir / "Resources" / "Fallback Images"
    s2 = bpy.data.images.load(str(fb / "ocean_pixel_final_20.exr"), check_existing=True)
    dt = bpy.data.images.get("PKA_DT_STACK_PROBE")
    if dt is None:
        dt = bpy.data.images.new("PKA_DT_STACK_PROBE", width=1, height=1, alpha=True, float_buffer=True)
        dt.pixels = [0.25, 0.5, 0.75, 1.0]
    return s2, dt


def _copy_group_template(name: str):
    src = bpy.data.node_groups.get("Planetka Textures Loading Group - Testing") or bpy.data.node_groups.get(
        "Planetka Textures Loading Group"
    )
    if src is None:
        raise RuntimeError("Missing Planetka texture loading source group")
    old = bpy.data.node_groups.get(name)
    if old is not None:
        bpy.data.node_groups.remove(old, do_unlink=True)
    g = src.copy()
    g.name = name
    nodes = g.nodes
    links = g.links
    out = next((n for n in nodes if n.type == "GROUP_OUTPUT"), None)
    if out is None:
        raise RuntimeError("Group output missing")
    for n in list(nodes):
        if n != out:
            nodes.remove(n)
    for l in list(links):
        links.remove(l)
    return g, out


def _build_probe_group(scenario: str, tiles, parse_tile, placement_group, s2_image, dt_image):
    name = f"Planetka SVM Probe - {scenario}"
    g, out = _copy_group_template(name)
    nodes = g.nodes
    links = g.links
    outputs = {s.name: s for s in out.inputs}

    # shared constant vector path
    texcoord = nodes.new("ShaderNodeTexCoord")
    shared_vec = texcoord.outputs["Generated"]

    s2_socks = []
    dt_socks = []
    alpha_socks = []

    use_place = scenario not in {"flat_linear", "flat_balanced", "flat_nochain"}
    use_dt = scenario not in {"s2_only", "place_only", "s2_weighted"}
    use_s2 = scenario not in {
        "dt_only",
        "place_only",
        "dt_weighted",
        "dt_weighted_raw",
        "dt_only_raw",
        "dt_weighted_el",
        "dt_weighted_wt",
        "dt_weighted_se",
    }
    use_alpha_weight = scenario in {
        "place_weighted",
        "place_weighted_norm",
        "place_weighted_norm_balanced",
        "s2_weighted",
        "dt_weighted",
        "dt_weighted_raw",
        "dt_weighted_el",
        "dt_weighted_wt",
        "dt_weighted_se",
    }
    use_norm = scenario in {"place_weighted_norm", "place_weighted_norm_balanced"}
    decode_mode = "all"
    if scenario in {"dt_weighted_raw", "dt_only_raw"}:
        decode_mode = "raw"
    elif scenario == "dt_weighted_el":
        decode_mode = "el"
    elif scenario == "dt_weighted_wt":
        decode_mode = "wt"
    elif scenario == "dt_weighted_se":
        decode_mode = "se"
    chain = "linear"
    if scenario.endswith("balanced"):
        chain = "balanced"
    if scenario.endswith("nochain"):
        chain = "none"

    for idx, tile in enumerate(tiles, start=1):
        if use_place:
            p = parse_tile(tile)
            if not p:
                continue
            x, y, z, d = p
            place = nodes.new("ShaderNodeGroup")
            place.node_tree = placement_group
            place.inputs[0].default_value = x
            place.inputs[1].default_value = y
            place.inputs[2].default_value = z
            place.inputs[3].default_value = d
            vec = place.outputs.get("S2")
            alpha = place.outputs.get("Alpha")
            alpha_socks.append(alpha)
        else:
            vec = shared_vec
            alpha = None

        if use_s2:
            s2 = nodes.new("ShaderNodeTexImage")
            s2.name = f"Probe_{idx:03d}_S2"
            s2.image = s2_image
            links.new(vec, s2.inputs["Vector"])
            if use_alpha_weight and alpha is not None:
                mul = nodes.new("ShaderNodeVectorMath")
                mul.operation = "SCALE"
                links.new(s2.outputs["Color"], mul.inputs[0])
                links.new(alpha, mul.inputs[3])
                s2_socks.append(mul.outputs[0])
            else:
                s2_socks.append(s2.outputs["Color"])

        if use_dt:
            dt = nodes.new("ShaderNodeTexImage")
            dt.name = f"Probe_{idx:03d}_DT"
            dt.image = dt_image
            links.new(vec, dt.inputs["Vector"])
            if use_alpha_weight and alpha is not None:
                mul = nodes.new("ShaderNodeVectorMath")
                mul.operation = "SCALE"
                links.new(dt.outputs["Color"], mul.inputs[0])
                links.new(alpha, mul.inputs[3])
                dt_socks.append(mul.outputs[0])
            else:
                dt_socks.append(dt.outputs["Color"])

    def _combine(socks):
        if not socks:
            return None
        if chain == "none":
            return socks[0]
        if chain == "balanced":
            return _balanced_rgba_add(nodes, links, socks)
        return _linear_rgba_add(nodes, links, socks)

    s2_out = _combine(s2_socks)
    dt_out = _combine(dt_socks)
    alpha_den = None

    if use_norm and alpha_socks:
        alpha_sum = alpha_socks[0]
        for sock in alpha_socks[1:]:
            add = nodes.new("ShaderNodeMath")
            add.operation = "ADD"
            links.new(alpha_sum, add.inputs[0])
            links.new(sock, add.inputs[1])
            alpha_sum = add.outputs[0]

        alpha_den = nodes.new("ShaderNodeMath")
        alpha_den.operation = "MAXIMUM"
        alpha_den.inputs[1].default_value = 1.0
        links.new(alpha_sum, alpha_den.inputs[0])

        if s2_out is not None:
            inv = nodes.new("ShaderNodeMath")
            inv.operation = "DIVIDE"
            inv.inputs[0].default_value = 1.0
            links.new(alpha_den.outputs[0], inv.inputs[1])
            s2_norm = nodes.new("ShaderNodeVectorMath")
            s2_norm.operation = "SCALE"
            links.new(s2_out, s2_norm.inputs[0])
            links.new(inv.outputs[0], s2_norm.inputs[3])
            s2_out = s2_norm.outputs[0]

        if dt_out is not None:
            inv = nodes.new("ShaderNodeMath")
            inv.operation = "DIVIDE"
            inv.inputs[0].default_value = 1.0
            links.new(alpha_den.outputs[0], inv.inputs[1])
            dt_norm = nodes.new("ShaderNodeVectorMath")
            dt_norm.operation = "SCALE"
            links.new(dt_out, dt_norm.inputs[0])
            links.new(inv.outputs[0], dt_norm.inputs[3])
            dt_out = dt_norm.outputs[0]

    if s2_out is not None and outputs.get("S2") is not None:
        links.new(s2_out, outputs["S2"])

    if dt_out is not None and decode_mode != "raw":
        sep = nodes.new("ShaderNodeSeparateColor")
        links.new(dt_out, sep.inputs["Color"])

        if decode_mode in {"all", "el"} and outputs.get("EL") is not None:
            links.new(sep.outputs["Red"], outputs["EL"])

        if decode_mode in {"all", "wt"} and outputs.get("WT") is not None:
            wt = nodes.new("ShaderNodeCombineColor")
            wt.mode = "RGB"
            links.new(sep.outputs["Green"], wt.inputs["Red"])
            links.new(sep.outputs["Green"], wt.inputs["Green"])
            links.new(sep.outputs["Green"], wt.inputs["Blue"])
            links.new(wt.outputs["Color"], outputs["WT"])

        if decode_mode in {"all", "se"} and outputs.get("SE") is not None:
            se = nodes.new("ShaderNodeCombineColor")
            se.mode = "RGB"
            links.new(sep.outputs["Blue"], se.inputs["Red"])
            links.new(sep.outputs["Blue"], se.inputs["Green"])
            links.new(sep.outputs["Blue"], se.inputs["Blue"])
            links.new(se.outputs["Color"], outputs["SE"])
    elif dt_out is not None and outputs.get("S2") is not None and s2_out is None:
        # Raw DT pass-through probe: isolates DT merge/decode node cost.
        links.new(dt_out, outputs["S2"])

    # stable alpha output so group compiles similarly
    if outputs.get("Alpha") is not None:
        if alpha_den is not None:
            alpha_clamp = nodes.new("ShaderNodeMath")
            alpha_clamp.operation = "MINIMUM"
            alpha_clamp.inputs[1].default_value = 1.0
            links.new(alpha_den.outputs[0], alpha_clamp.inputs[0])
            links.new(alpha_clamp.outputs[0], outputs["Alpha"])
        else:
            val = nodes.new("ShaderNodeValue")
            val.outputs[0].default_value = 1.0
            links.new(val.outputs[0], outputs["Alpha"])

    return g


def main():
    args = _parse_args()
    addon_utils.enable("bl_ext.user_default.Planetka", default_set=False, persistent=False)

    from bl_ext.user_default.Planetka import asset_builder, shader_utils, tile_utils

    scene = bpy.context.scene
    asset_builder.ensure_planetka_assets(scene)

    # baseline uses existing v3 experiment builder to mirror current measurements.
    if args.scenario == "baseline_v3":
        import importlib.util

        script_path = Path(__file__).with_name("svm_loading_group_experiment.py")
        spec = importlib.util.spec_from_file_location("svm_loading_group_experiment", str(script_path))
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)

        tiles = tile_utils.main(scope_mode="CAMERA")
        tiles = list(tiles[: max(1, int(args.tiles))])
        images = mod._load_fallback_images(Path(__file__).resolve().parents[1])
        placement_group = shader_utils._ensure_tile_placement_group("regular")
        group = mod._build_variant_group(
            group_name="Planetka Textures Loading Group - Probe Baseline V3",
            variant="v3",
            tiles=tiles,
            parse_tile=shader_utils.parse_tile,
            placement_group=placement_group,
            images=images,
        )
    else:
        tiles = tile_utils.main(scope_mode="CAMERA")
        tiles = list(tiles[: max(1, int(args.tiles))])
        addon_dir = Path(__file__).resolve().parents[1]
        s2_image, dt_image = _load_images(addon_dir)
        placement_group = shader_utils._ensure_tile_placement_group("regular")
        group = _build_probe_group(
            scenario=args.scenario,
            tiles=tiles,
            parse_tile=shader_utils.parse_tile,
            placement_group=placement_group,
            s2_image=s2_image,
            dt_image=dt_image,
        )

    material = bpy.data.materials.get("Planetka Earth Material")
    if material is None or material.node_tree is None:
        raise RuntimeError("Planetka Earth Material missing")
    loading_node = material.node_tree.nodes.get("Planetka Textures Loading")
    if loading_node is None:
        raise RuntimeError("Planetka Textures Loading node missing")
    loading_node.node_tree = group

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180

    print(
        "SVM_PROBE_META",
        json.dumps(
            {
                "scenario": args.scenario,
                "tiles": len(tiles),
                "group": group.name,
                "node_count": len(group.nodes),
                "link_count": len(group.links),
            },
            sort_keys=True,
        ),
    )
    print("SVM_PROBE_RENDER_START")
    bpy.ops.render.render(write_still=False)
    print("SVM_PROBE_RENDER_DONE")


if __name__ == "__main__":
    main()
