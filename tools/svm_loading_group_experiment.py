#!/usr/bin/env python3
"""Build SVM-loading-group experiment variants and run one Cycles render.

Usage (inside Blender):
  blender --background Cairo.blend --python tools/svm_loading_group_experiment.py -- --variant v1 --tiles 13
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=("v1", "v1_no_el", "v1_el_like_wt", "v1_el_loaded_unused", "v1_el_no_norm", "v1_el_const", "v2", "v3"),
        required=True,
    )
    parser.add_argument("--tiles", type=int, required=True)
    parser.add_argument("--s2-image-path", default="")
    parser.add_argument("--el-image-path", default="")
    parser.add_argument("--wt-image-path", default="")
    parser.add_argument("--po-image-path", default="")
    parser.add_argument("--force-el-colorspace", choices=("NON_COLOR", "LINEAR_REC709", "RAW"), default="")
    return parser.parse_args(argv)


def _add_rgba_chain(nodes, links, sockets):
    if not sockets:
        return None
    current = sockets[0]
    for idx, source in enumerate(sockets[1:], start=1):
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "ADD"
        mix.inputs[0].default_value = 1.0
        mix.location = (320.0 + idx * 220.0, 0.0 - idx * 20.0)
        links.new(current, mix.inputs[6])
        links.new(source, mix.inputs[7])
        current = mix.outputs[2]
    return current


def _add_scalar_chain(nodes, links, sockets):
    if not sockets:
        return None
    current = sockets[0]
    for idx, source in enumerate(sockets[1:], start=1):
        math = nodes.new("ShaderNodeMath")
        math.operation = "ADD"
        math.location = (320.0 + idx * 220.0, -280.0 - idx * 20.0)
        links.new(current, math.inputs[0])
        links.new(source, math.inputs[1])
        current = math.outputs[0]
    return current


def _set_image_colorspace_safe(image, colorspace):
    if image is None:
        return
    settings = getattr(image, "colorspace_settings", None)
    if settings is None or not hasattr(settings, "name"):
        return

    candidates = [colorspace]
    if colorspace == "Linear Rec.709":
        candidates.extend(["Linear", "Raw"])
    elif colorspace == "Non-Color":
        candidates.extend(["Raw"])

    available = set()
    try:
        prop = settings.bl_rna.properties.get("name")
        if prop and hasattr(prop, "enum_items"):
            available = {item.identifier for item in prop.enum_items}
    except Exception:
        available = set()

    for candidate in candidates:
        if available and candidate not in available:
            continue
        try:
            settings.name = candidate
            return
        except Exception:
            continue


def _load_fallback_images(addon_dir: Path, overrides: dict[str, str] | None = None, el_colorspace: str = ""):
    overrides = overrides or {}
    fallback_dir = addon_dir / "Resources" / "Fallback Images"
    default_paths = {
        "S2": fallback_dir / "ocean_pixel_final_20.exr",
        "EL": fallback_dir / "black_pixel_20.exr",
        "WT": fallback_dir / "blue_pixel_20.exr",
        "PO": fallback_dir / "black_pixel_20.exr",
    }
    images = {}
    for key, default_path in default_paths.items():
        override_path = str(overrides.get(key, "") or "").strip()
        path = Path(override_path) if override_path else default_path
        images[key] = bpy.data.images.load(str(path), check_existing=True) if path.exists() else None

    if images.get("EL") is not None and el_colorspace:
        if el_colorspace == "NON_COLOR":
            _set_image_colorspace_safe(images["EL"], "Non-Color")
        elif el_colorspace == "LINEAR_REC709":
            _set_image_colorspace_safe(images["EL"], "Linear Rec.709")
        elif el_colorspace == "RAW":
            _set_image_colorspace_safe(images["EL"], "Raw")
    dt_name = "PKA_DT_PLACEHOLDER_EXPERIMENT"
    dt = bpy.data.images.get(dt_name)
    if dt is None:
        dt = bpy.data.images.new(dt_name, width=1, height=1, alpha=True, float_buffer=True)
        dt.pixels = [0.25, 0.5, 0.75, 1.0]
    images["DT"] = dt
    return images


def _build_variant_group(group_name, variant, tiles, parse_tile, placement_group, images):
    existing = bpy.data.node_groups.get(group_name)
    if existing is not None:
        bpy.data.node_groups.remove(existing, do_unlink=True)

    source = bpy.data.node_groups.get("Planetka Textures Loading Group") or bpy.data.node_groups.get(
        "Planetka Textures Loading Group - Testing"
    )
    if source is None:
        raise RuntimeError("Missing source texture loading group")
    group = source.copy()
    group.name = group_name
    nodes = group.nodes
    links = group.links

    output = next((n for n in nodes if n.type == "GROUP_OUTPUT"), None)
    if output is None:
        raise RuntimeError("Group output missing in copied texture loading group")

    for node in list(nodes):
        if node == output:
            continue
        nodes.remove(node)
    for link in list(links):
        links.remove(link)

    outputs = {s.name: s for s in output.inputs}

    s2_weighted = []
    wt_weighted = []
    se_weighted = []
    el_weighted = []
    el_vec_weighted = []
    dt_weighted = []
    alpha_sockets = []

    for idx, tile in enumerate(tiles, start=1):
        parsed = parse_tile(tile)
        if not parsed:
            continue
        x, y, z, d = parsed
        base_y = 440.0 - (idx - 1) * 460.0

        place = nodes.new("ShaderNodeGroup")
        place.name = f"Tile_{idx:03d}"
        place.node_tree = placement_group
        place.location = (-900.0, base_y)
        place.inputs[0].default_value = x
        place.inputs[1].default_value = y
        place.inputs[2].default_value = z
        place.inputs[3].default_value = d
        alpha = place.outputs.get("Alpha")
        vec = place.outputs.get("S2")
        alpha_sockets.append(alpha)

        img_s2 = nodes.new("ShaderNodeTexImage")
        img_s2.name = f"TileImg_{idx:03d}_S2"
        img_s2.image = images["S2"]
        img_s2.location = (-650.0, base_y + 170.0)
        links.new(vec, img_s2.inputs["Vector"])

        def _weight_vec(sock, y_off):
            node = nodes.new("ShaderNodeVectorMath")
            node.operation = "SCALE"
            node.location = (-360.0, base_y + y_off)
            links.new(sock, node.inputs[0])
            links.new(alpha, node.inputs[3])
            return node.outputs[0]

        s2_weighted.append(_weight_vec(img_s2.outputs["Color"], 140.0))

        if variant in {"v1", "v1_no_el", "v1_el_like_wt", "v1_el_loaded_unused", "v1_el_no_norm", "v1_el_const"}:
            img_el = nodes.new("ShaderNodeTexImage")
            img_el.name = f"TileImg_{idx:03d}_EL"
            img_el.image = images["EL"]
            img_el.location = (-650.0, base_y + 20.0)
            links.new(vec, img_el.inputs["Vector"])

            img_wt = nodes.new("ShaderNodeTexImage")
            img_wt.name = f"TileImg_{idx:03d}_WT"
            img_wt.image = images["WT"]
            img_wt.location = (-650.0, base_y - 130.0)
            links.new(vec, img_wt.inputs["Vector"])

            img_po = nodes.new("ShaderNodeTexImage")
            img_po.name = f"TileImg_{idx:03d}_PO"
            img_po.image = images["PO"]
            img_po.location = (-650.0, base_y - 280.0)
            links.new(vec, img_po.inputs["Vector"])

            wt_weighted.append(_weight_vec(img_wt.outputs["Color"], -10.0))
            se_weighted.append(_weight_vec(img_po.outputs["Color"], -150.0))

            if variant in {"v1", "v1_el_no_norm"}:
                sep_el = nodes.new("ShaderNodeSeparateColor")
                sep_el.location = (-360.0, base_y + 20.0)
                links.new(img_el.outputs["Color"], sep_el.inputs["Color"])
                el_mul = nodes.new("ShaderNodeMath")
                el_mul.operation = "MULTIPLY"
                el_mul.location = (-150.0, base_y + 20.0)
                links.new(sep_el.outputs["Red"], el_mul.inputs[0])
                links.new(alpha, el_mul.inputs[1])
                el_weighted.append(el_mul.outputs[0])
            elif variant == "v1_el_like_wt":
                # EL branch with the same vector weighting/merge strategy as WT/PO.
                el_vec_weighted.append(_weight_vec(img_el.outputs["Color"], 20.0))

        elif variant == "v2":
            img_el = nodes.new("ShaderNodeTexImage")
            img_el.name = f"TileImg_{idx:03d}_EL"
            img_el.image = images["EL"]
            img_el.location = (-650.0, base_y + 20.0)
            links.new(vec, img_el.inputs["Vector"])

            img_wt = nodes.new("ShaderNodeTexImage")
            img_wt.name = f"TileImg_{idx:03d}_WT"
            img_wt.image = images["WT"]
            img_wt.location = (-650.0, base_y - 130.0)
            links.new(vec, img_wt.inputs["Vector"])

            img_po = nodes.new("ShaderNodeTexImage")
            img_po.name = f"TileImg_{idx:03d}_PO"
            img_po.image = images["PO"]
            img_po.location = (-650.0, base_y - 280.0)
            links.new(vec, img_po.inputs["Vector"])

            sep_el = nodes.new("ShaderNodeSeparateColor")
            sep_el.location = (-400.0, base_y + 20.0)
            links.new(img_el.outputs["Color"], sep_el.inputs["Color"])
            bw_wt = nodes.new("ShaderNodeRGBToBW")
            bw_wt.location = (-400.0, base_y - 120.0)
            links.new(img_wt.outputs["Color"], bw_wt.inputs["Color"])
            bw_po = nodes.new("ShaderNodeRGBToBW")
            bw_po.location = (-400.0, base_y - 260.0)
            links.new(img_po.outputs["Color"], bw_po.inputs["Color"])

            dt_combine = nodes.new("ShaderNodeCombineColor")
            dt_combine.mode = "RGB"
            dt_combine.location = (-180.0, base_y - 80.0)
            links.new(sep_el.outputs["Red"], dt_combine.inputs["Red"])
            links.new(bw_wt.outputs["Val"], dt_combine.inputs["Green"])
            links.new(bw_po.outputs["Val"], dt_combine.inputs["Blue"])
            dt_weighted.append(_weight_vec(dt_combine.outputs["Color"], -80.0))

        elif variant == "v3":
            img_dt = nodes.new("ShaderNodeTexImage")
            img_dt.name = f"TileImg_{idx:03d}_DT"
            img_dt.image = images["DT"]
            img_dt.location = (-650.0, base_y - 80.0)
            links.new(vec, img_dt.inputs["Vector"])
            dt_weighted.append(_weight_vec(img_dt.outputs["Color"], -80.0))

    alpha_sum = _add_scalar_chain(nodes, links, [s for s in alpha_sockets if s is not None])
    alpha_den = nodes.new("ShaderNodeMath")
    alpha_den.operation = "MAXIMUM"
    alpha_den.inputs[1].default_value = 1.0
    alpha_den.location = (920.0, -260.0)
    if alpha_sum is not None:
        links.new(alpha_sum, alpha_den.inputs[0])
    else:
        alpha_den.inputs[0].default_value = 1.0
    inv_alpha = nodes.new("ShaderNodeMath")
    inv_alpha.operation = "DIVIDE"
    inv_alpha.inputs[0].default_value = 1.0
    inv_alpha.location = (1140.0, -260.0)
    links.new(alpha_den.outputs[0], inv_alpha.inputs[1])

    def _normalize_vec(sock, y):
        if sock is None:
            return None
        node = nodes.new("ShaderNodeVectorMath")
        node.operation = "SCALE"
        node.location = (1360.0, y)
        links.new(sock, node.inputs[0])
        links.new(inv_alpha.outputs[0], node.inputs[3])
        return node.outputs[0]

    def _normalize_scalar(sock, y):
        if sock is None:
            return None
        node = nodes.new("ShaderNodeMath")
        node.operation = "DIVIDE"
        node.location = (1360.0, y)
        links.new(sock, node.inputs[0])
        links.new(alpha_den.outputs[0], node.inputs[1])
        return node.outputs[0]

    s2_sum = _add_rgba_chain(nodes, links, s2_weighted)
    s2_norm = _normalize_vec(s2_sum, 240.0)
    if s2_norm is not None and outputs.get("S2") is not None:
        links.new(s2_norm, outputs["S2"])

    if variant in {"v1", "v1_no_el", "v1_el_like_wt", "v1_el_loaded_unused", "v1_el_no_norm", "v1_el_const"}:
        wt_sum = _add_rgba_chain(nodes, links, wt_weighted)
        se_sum = _add_rgba_chain(nodes, links, se_weighted)

        wt_norm = _normalize_vec(wt_sum, 0.0)
        se_norm = _normalize_vec(se_sum, -160.0)
        if wt_norm is not None and outputs.get("WT") is not None:
            links.new(wt_norm, outputs["WT"])
        if se_norm is not None and outputs.get("SE") is not None:
            links.new(se_norm, outputs["SE"])
        if variant == "v1":
            el_sum = _add_scalar_chain(nodes, links, el_weighted)
            el_norm = _normalize_scalar(el_sum, -320.0)
            if el_norm is not None and outputs.get("EL") is not None:
                links.new(el_norm, outputs["EL"])
        elif variant == "v1_el_no_norm":
            el_sum = _add_scalar_chain(nodes, links, el_weighted)
            if el_sum is not None and outputs.get("EL") is not None:
                links.new(el_sum, outputs["EL"])
        elif variant == "v1_el_like_wt":
            el_vec_sum = _add_rgba_chain(nodes, links, el_vec_weighted)
            el_vec_norm = _normalize_vec(el_vec_sum, -320.0)
            if el_vec_norm is not None and outputs.get("EL") is not None:
                el_sep = nodes.new("ShaderNodeSeparateColor")
                el_sep.location = (1600.0, -320.0)
                links.new(el_vec_norm, el_sep.inputs["Color"])
                links.new(el_sep.outputs["Red"], outputs["EL"])
        elif variant == "v1_el_const":
            if outputs.get("EL") is not None:
                el_const = nodes.new("ShaderNodeValue")
                el_const.outputs[0].default_value = 0.00276184
                links.new(el_const.outputs[0], outputs["EL"])

    else:
        dt_sum = _add_rgba_chain(nodes, links, dt_weighted)
        dt_norm = _normalize_vec(dt_sum, -80.0)
        if dt_norm is not None:
            dt_sep = nodes.new("ShaderNodeSeparateColor")
            dt_sep.location = (1600.0, -80.0)
            links.new(dt_norm, dt_sep.inputs["Color"])

            wt_pack = nodes.new("ShaderNodeCombineColor")
            wt_pack.mode = "RGB"
            wt_pack.location = (1840.0, -20.0)
            links.new(dt_sep.outputs["Green"], wt_pack.inputs["Red"])
            links.new(dt_sep.outputs["Green"], wt_pack.inputs["Green"])
            links.new(dt_sep.outputs["Green"], wt_pack.inputs["Blue"])

            se_pack = nodes.new("ShaderNodeCombineColor")
            se_pack.mode = "RGB"
            se_pack.location = (1840.0, -180.0)
            links.new(dt_sep.outputs["Blue"], se_pack.inputs["Red"])
            links.new(dt_sep.outputs["Blue"], se_pack.inputs["Green"])
            links.new(dt_sep.outputs["Blue"], se_pack.inputs["Blue"])

            if outputs.get("EL") is not None:
                links.new(dt_sep.outputs["Red"], outputs["EL"])
            if outputs.get("WT") is not None:
                links.new(wt_pack.outputs["Color"], outputs["WT"])
            if outputs.get("SE") is not None:
                links.new(se_pack.outputs["Color"], outputs["SE"])

    alpha_clamp = nodes.new("ShaderNodeMath")
    alpha_clamp.operation = "MINIMUM"
    alpha_clamp.inputs[1].default_value = 1.0
    alpha_clamp.location = (1360.0, -520.0)
    links.new(alpha_den.outputs[0], alpha_clamp.inputs[0])
    if outputs.get("Alpha") is not None:
        links.new(alpha_clamp.outputs[0], outputs["Alpha"])

    return group


def main() -> None:
    args = _parse_args()
    addon_utils.enable("bl_ext.user_default.Planetka", default_set=False, persistent=False)

    from bl_ext.user_default.Planetka import asset_builder, shader_utils, tile_utils

    scene = bpy.context.scene
    asset_builder.ensure_planetka_assets(scene)
    tiles = tile_utils.main(scope_mode="CAMERA")
    tiles = list(tiles[: max(1, int(args.tiles))])

    addon_dir = Path(__file__).resolve().parents[1]
    images = _load_fallback_images(
        addon_dir,
        overrides={
            "S2": args.s2_image_path,
            "EL": args.el_image_path,
            "WT": args.wt_image_path,
            "PO": args.po_image_path,
        },
        el_colorspace=args.force_el_colorspace,
    )
    placement_group = shader_utils._ensure_tile_placement_group("regular")

    variant_to_group = {
        "v1": "Planetka Textures Loading Group - Test V1",
        "v1_no_el": "Planetka Textures Loading Group - Test V1 No EL",
        "v1_el_like_wt": "Planetka Textures Loading Group - Test V1 EL Like WT",
        "v1_el_loaded_unused": "Planetka Textures Loading Group - Test V1 EL Loaded Unused",
        "v1_el_no_norm": "Planetka Textures Loading Group - Test V1 EL No Norm",
        "v1_el_const": "Planetka Textures Loading Group - Test V1 EL Const",
        "v2": "Planetka Textures Loading Group - Test V2",
        "v3": "Planetka Textures Loading Group - Test V3",
    }
    group_name = variant_to_group[args.variant]
    group = _build_variant_group(
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
    loading_node = material.node_tree.nodes.get("Planetka Textures Loading")
    if loading_node is None:
        raise RuntimeError("Planetka Textures Loading node missing")
    loading_node.node_tree = group

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180

    print(
        "EXPERIMENT_META",
        json.dumps(
            {
                "variant": args.variant,
                "tiles": len(tiles),
                "group": group.name,
                "node_count": len(group.nodes),
                "link_count": len(group.links),
            },
            sort_keys=True,
        ),
    )
    print("EXPERIMENT_RENDER_START")
    bpy.ops.render.render(write_still=False)
    print("EXPERIMENT_RENDER_DONE")


if __name__ == "__main__":
    main()
