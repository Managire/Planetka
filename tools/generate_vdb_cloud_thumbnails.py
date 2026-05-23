"""Generate PNG thumbnails for Planetka VDB cloud presets.

Run with Blender, for example:
  /Applications/Blender5.0.app/Contents/MacOS/Blender --background --python tools/generate_vdb_cloud_thumbnails.py
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import bpy
from mathutils import Vector


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = tuple(
    Path("/Volumes/SSDA/Volumetric Clouds") / f"Cloud{index:03d}" / "VDB"
    for index in range(1, 6)
)
OUTPUT_DIR = REPO_ROOT / "generated" / "vdb_cloud_thumbnails"
RESOLUTION = 512


def _clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _bounds_center_and_scale(obj):
    min_x = min(v[0] for v in obj.bound_box)
    max_x = max(v[0] for v in obj.bound_box)
    min_y = min(v[1] for v in obj.bound_box)
    max_y = max(v[1] for v in obj.bound_box)
    min_z = min(v[2] for v in obj.bound_box)
    max_z = max(v[2] for v in obj.bound_box)
    center = Vector(((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, (min_z + max_z) / 2.0))
    scale = max(max_x - min_x, max_z - min_z, 1.0)
    return center, scale


def _assign_preview_material(obj):
    material = bpy.data.materials.new("Planetka VDB Thumbnail Material")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    attribute = nodes.new("ShaderNodeAttribute")
    attribute.attribute_name = "density"
    density_scale = nodes.new("ShaderNodeMath")
    density_scale.operation = "MULTIPLY"
    density_scale.inputs[1].default_value = 3.0
    scatter = nodes.new("ShaderNodeVolumeScatter")
    scatter.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    scatter.inputs["Density"].default_value = 1.25
    scatter.inputs["Anisotropy"].default_value = 0.08
    if "Weight" in scatter.inputs:
        scatter.inputs["Weight"].default_value = 1.0

    links = material.node_tree.links
    links.new(attribute.outputs["Fac"], density_scale.inputs[0])
    links.new(density_scale.outputs[0], scatter.inputs["Density"])
    links.new(scatter.outputs["Volume"], output.inputs["Volume"])

    obj.data.materials.clear()
    obj.data.materials.append(material)


def _render_thumbnail(vdb_path: Path, output_path: Path):
    _clear_scene()
    bpy.ops.object.volume_import(filepath=str(vdb_path))
    obj = bpy.context.object
    obj.data.grids.load()
    _assign_preview_material(obj)

    center, scale = _bounds_center_and_scale(obj)
    scene = bpy.context.scene
    scene.world.color = (0.015, 0.025, 0.04)

    bpy.ops.object.light_add(type="AREA", location=(center.x - 500.0, center.y + 900.0, center.z + 900.0))
    light = bpy.context.object
    light.data.energy = 16000.0
    light.data.size = 2600.0

    bpy.ops.object.light_add(type="AREA", location=(center.x + 900.0, center.y - 300.0, center.z + 500.0))
    fill = bpy.context.object
    fill.data.energy = 4500.0
    fill.data.size = 3000.0

    bpy.ops.object.camera_add(location=(center.x, center.y + 1800.0, center.z))
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = scale * 1.18
    camera.data.clip_end = 10000.0
    scene.camera = camera

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 40
    scene.cycles.max_bounces = 4
    scene.cycles.volume_bounces = 4
    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.7
    scene.view_settings.gamma = 1.0
    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    vdb_files = []
    for source_dir in SOURCE_DIRS:
        vdb_files.extend(sorted(source_dir.glob("*.vdb")))
    if not vdb_files:
        raise SystemExit(f"No VDB files found in {', '.join(str(path) for path in SOURCE_DIRS)}")
    for vdb_path in vdb_files:
        output_path = OUTPUT_DIR / f"{vdb_path.stem}.png"
        _render_thumbnail(vdb_path, output_path)
        print(f"Generated {output_path} ({os.path.getsize(output_path):,} bytes)")


if __name__ == "__main__":
    main()
