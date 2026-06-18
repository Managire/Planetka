import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty


def _noop_update(_self, _context):
    return None


class PlanetkaProperties(bpy.types.PropertyGroup):
    __slots__ = ()

    show_earth_preview: BoolProperty(
        name="Show Earth Preview",
        default=True,
        description="Show the lightweight whole-Earth preview while detailed textures are loading",
    )

    anim_prepare_max_segments: IntProperty(
        name="Max Segments",
        default=99,
        min=1,
        max=99,
        description="Maximum number of prepared segment meshes allowed in Quick Preview mode",
    )

    anim_prepare_max_textures_mb: FloatProperty(
        name="Max Textures (MB)",
        default=4096.0,
        min=0.0,
        max=262144.0,
        precision=1,
        description="Maximum total texture footprint for prepared animation assets in MB",
    )

    texture_quality_mode: EnumProperty(
        name="Quality Level",
        items=(
            ("PREVIEW", "Preview", "Downloaded textures are 1/4 of the edge size of Full resolution textures, making them 1/16 of the pixel size"),
            ("BALANCED", "Balanced", "Downloaded textures are 1/2 of the edge size of Full resolution textures, making them 1/4 of the pixel size"),
            ("FULL", "Full", "Makes sure at least one pixel from the source texture is used for every pixel in the final render if proximity to Earth allows"),
        ),
        default="PREVIEW",
        description="Choose the streaming texture quality used the next time Resolve Planetka runs",
        update=_noop_update,
    )

    resolution_bias: FloatProperty(
        name="Resolution Bias",
        default=0.0,
        min=-2.0,
        max=2.0,
        precision=2,
        description="Internal Resolve tile detail bias",
    )

    lock_resolve_during_animation: BoolProperty(
        name="Lock Resolve During Animation",
        default=True,
        description="Prevent Resolve updates while timeline playback is running",
    )
