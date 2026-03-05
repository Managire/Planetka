import bpy

from .extension_prefs import get_earth_object, get_prefs
from .geonames_db import get_search_status_text
from .sanity_utils import get_texture_source_health
from .diagnostics import read_diagnostics
from .animation_tools import (
    ANIMATION_STATS_END_KEY,
    ANIMATION_STATS_SEGMENTS_KEY,
    ANIMATION_STATS_START_KEY,
    ANIMATION_STATS_TEXTURE_MB_KEY,
)
from .state import (
    ADD_EARTH_BUTTON_SCALE_X,
    ADD_EARTH_BUTTON_SCALE_Y,
    REFRESH_BUTTON_ALERT,
    REFRESH_BUTTON_SCALE_X,
    REFRESH_BUTTON_SCALE_Y,
)

SHOW_INTERNAL_ANIMATION_UI = False


def _fmt_int(value):
    if value is None:
        return "—"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "—"


def _fmt_ms(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f} ms"
    except (TypeError, ValueError):
        return "—"


def _fmt_km(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f} km"
    except (TypeError, ValueError):
        return "—"


def _fmt_deg(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.4f}°"
    except (TypeError, ValueError):
        return "—"

def _fmt_m(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f} m"
    except (TypeError, ValueError):
        return "—"


def _fmt_mb(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f} MB"
    except (TypeError, ValueError):
        return "—"


def _fmt_gb_from_mb(value_mb):
    if value_mb is None:
        return "—"
    try:
        return f"{float(value_mb) / 1024.0:.2f} GB"
    except (TypeError, ValueError):
        return "—"


class _PLANETKA_PT_BaseSection:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    bl_options = {'DEFAULT_CLOSED'}


def _has_earth():
    return get_earth_object() is not None


def _is_animation_prepared(scene):
    if scene is None:
        return False
    try:
        return int(scene.get(ANIMATION_STATS_SEGMENTS_KEY, 0)) > 0
    except (TypeError, ValueError):
        return False


def _draw_animation_ready_message(layout):
    message = layout.box()
    message.alert = False
    message.label(text="Ready to Render Animation.", icon="CHECKMARK")
    message.label(text="Clear Prepared to return to editing.", icon="INFO")
    return message


def _show_internal_animation_ui():
    return bool(SHOW_INTERNAL_ANIMATION_UI)


def _draw_create_new_earth(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False

    prefs = get_prefs()
    status_text = "Texture Source: Not Set"
    status_icon = "ERROR"
    show_texture_source_fix = False
    if prefs:
        health = get_texture_source_health(getattr(prefs, "texture_base_path", ""))
        status = str(health.get("status", "INVALID"))
        if status == "INVALID":
            status_text = "Texture Source: Invalid"
            status_icon = "ERROR"
            show_texture_source_fix = True
        elif status == "PARTIAL":
            status_text = "Texture Source: Partial"
            status_icon = "QUESTION"
        elif status == "READY":
            status_text = "Texture Source: Ready"
            status_icon = "CHECKMARK"
        else:
            status_text = "Texture Source: Not Set"
            status_icon = "ERROR"
            show_texture_source_fix = True
    layout.label(text=status_text, icon=status_icon)

    if show_texture_source_fix:
        layout.operator(
            "planetka.select_texture_source",
            text="Locate Texture Source Directory",
            icon="FILE_FOLDER",
        )

    row = layout.row()
    row.scale_x = ADD_EARTH_BUTTON_SCALE_X
    row.scale_y = ADD_EARTH_BUTTON_SCALE_Y
    row.alert = False
    row.operator("planetka.add_earth", text="Create Earth", icon="WORLD_DATA")


def _draw_resolve(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False
    scene = getattr(bpy.context, "scene", None)
    prepared = _is_animation_prepared(scene)
    if prepared:
        _draw_animation_ready_message(layout)
    row = layout.row()
    row.scale_x = REFRESH_BUTTON_SCALE_X
    row.scale_y = REFRESH_BUTTON_SCALE_Y
    row.alert = REFRESH_BUTTON_ALERT
    row.enabled = not prepared
    row.operator("planetka.load_textures", text="Resolve Earth Surface", icon="MOD_REMESH")


def _draw_live_telemetry(layout, scene):
    layout.use_property_split = False
    layout.use_property_decorate = False
    diag = read_diagnostics(scene)
    live_col = layout.column(align=True)
    live_col.label(text=f"Latitude: {_fmt_deg(diag.get('view_latitude_deg'))}")
    live_col.label(text=f"Longitude: {_fmt_deg(diag.get('view_longitude_deg'))}")
    live_col.label(text=f"Altitude: {_fmt_km(diag.get('view_altitude_km'))}")


def _draw_advanced_telemetry(layout, scene):
    layout.use_property_split = False
    layout.use_property_decorate = False
    diag = read_diagnostics(scene)
    advanced_col = layout.column(align=True)
    advanced_col.label(text=f"Tiles: {_fmt_int(diag.get('last_tile_count'))}")
    advanced_col.label(text=f"Last Resolve: {_fmt_ms(diag.get('last_resolve_ms'))}")
    advanced_col.label(text=f"Spatial Resolution: {_fmt_m(diag.get('resolve_required_mpp_m'))}")
    advanced_col.label(text=f"Text Size: {_fmt_mb(diag.get('resolve_textures_mb'))}")


class PLANETKA_PT_NewEarthPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Create New Earth"
    bl_idname = "PLANETKA_PT_new_earth"
    bl_order = 0
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not _has_earth()

    def draw(self, context):
        _draw_create_new_earth(self.layout)


class PLANETKA_PT_NewEarthPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Create New Earth"
    bl_idname = "PLANETKA_PT_new_earth_collapsed"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        _draw_create_new_earth(self.layout)


class PLANETKA_PT_ResolvePanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Resolve"
    bl_idname = "PLANETKA_PT_resolve"
    bl_order = 2
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        _draw_resolve(self.layout)


class PLANETKA_PT_ResolvePanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Resolve"
    bl_idname = "PLANETKA_PT_resolve_collapsed"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return not _has_earth()

    def draw(self, context):
        _draw_resolve(self.layout)


class PLANETKA_PT_SettingsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Settings"
    bl_idname = "PLANETKA_PT_settings"
    bl_order = 6

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        prepared = _is_animation_prepared(scene)

        if props:
            resolve_box = layout.box()
            resolve_box.label(text="Resolve Settings", icon="MOD_REMESH")
            if prepared:
                _draw_animation_ready_message(resolve_box)
            resolve_box.operator(
                "planetka.load_textures",
                text="Resolve Earth Surface",
                icon="MOD_REMESH",
            )
            resolve_box.enabled = not prepared
            row = resolve_box.row()
            row.use_property_split = False
            row.prop(
                props,
                "auto_resolve",
                text="Auto Resolve",
                toggle=True,
                icon="FILE_REFRESH",
            )
            idle_row = resolve_box.row()
            idle_row.enabled = bool(getattr(props, "auto_resolve", False))
            idle_row.prop(
                props,
                "auto_resolve_idle_sec",
                text="Auto Resolve Idle Delay (s)",
                slider=True,
            )
            if _show_internal_animation_ui():
                resolve_box.prop(
                    props,
                    "lock_resolve_during_animation",
                    text="Lock Resolve During Animation",
                    toggle=True,
                )

            quality_box = layout.box()
            quality_box.label(text="Texture Quality", icon="TEXTURE")
            quality_box.prop(props, "texture_quality_mode", text="Texture Quality")

            viewport_box = layout.box()
            viewport_box.label(text="Viewport Optimization", icon="VIEW3D")
            viewport_box.prop(
                props,
                "viewport_opt_active_view_coarse_textures",
                text="Use Lower Texture Quality in Active View",
                toggle=True,
            )
            viewport_box.prop(
                props,
                "viewport_opt_suspend_subdivision",
                text="Suspend Adaptive Subdivision While Navigating",
                toggle=True,
            )
            delay_row = viewport_box.row()
            delay_row.enabled = bool(getattr(props, "viewport_opt_suspend_subdivision", True))
            delay_row.prop(
                props,
                "viewport_opt_subdivision_restore_delay_sec",
                text="Subdivision Restore Delay (s)",
                slider=True,
            )

            source_box = layout.box()
            source_box.label(text="Texture Source", icon="FILE_FOLDER")
            source_box.operator(
                "planetka.select_texture_source",
                text="Set Texture Source Directory",
                icon="FILE_FOLDER",
            )
            source_box.operator(
                "planetka.import_new_data",
                text="Import New Data",
                icon="IMPORT",
            )
            source_box.operator(
                "planetka.validate_texture_source",
                text="Validate Texture Source",
                icon="CHECKMARK",
            )

            objects_box = layout.box()
            objects_box.label(text="Scene Objects", icon="OUTLINER_OB_EMPTY")
            objects_box.prop(
                props,
                "show_earth_preview",
                text="Show Earth Preview",
                toggle=True,
            )

            telemetry_box = layout.box()
            telemetry_box.label(text="Advanced Telemetry", icon="INFO")
            _draw_advanced_telemetry(telemetry_box, scene)


class PLANETKA_PT_LiveTelemetryPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Telemetry"
    bl_idname = "PLANETKA_PT_live_telemetry"
    bl_order = 3
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LiveTelemetryPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Telemetry"
    bl_idname = "PLANETKA_PT_live_telemetry_collapsed"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LinksPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Knowledge Base"
    bl_idname = "PLANETKA_PT_links"
    bl_order = 1000

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator("wm.url_open", text="Documentation", icon="HELP").url = "https://www.planetka.io/blender/documentation/"
        row.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.planetka.io/blender/tutorials/"
        row = layout.row(align=True)
        row.operator("planetka.report_bug", text="Report Bug", icon="ERROR")
        row.operator("wm.url_open", text="Discord", icon="URL").url = "https://www.planetka.io"

        layout.operator(
            "wm.url_open",
            text="www.planetka.io",
            icon="URL",
        ).url = "https://www.planetka.io"


class PLANETKA_PT_NavigationPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Navigation"
    bl_idname = "PLANETKA_PT_navigation"
    bl_order = 4
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        prepared = _is_animation_prepared(scene)
        if not props:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        if prepared:
            _draw_animation_ready_message(layout)

        location_box = layout.box()
        location_box.enabled = not prepared
        location_box.operator(
            "planetka.navigation_use_current_view",
            text="Camera to Current View",
            icon="VIEWZOOM",
        )
        geonames_status = str(get_search_status_text() or "")
        if geonames_status:
            status_icon = "ERROR" if "not configured" in geonames_status else "INFO"
            location_box.label(text=geonames_status, icon=status_icon)
        location_box.label(text="Location", icon="PINNED")
        location_box.prop(props, "nav_city_search", text="Place Search")
        selected_place = str(getattr(props, "nav_city_selected_name", "") or "")
        if selected_place:
            location_box.label(text=f"Selected: {selected_place}", icon="BOOKMARKS")
        location_box.prop(props, "nav_latitude_deg", text="Latitude")
        location_box.prop(props, "nav_longitude_deg", text="Longitude")

        shot_box = layout.box()
        shot_box.enabled = not prepared
        shot_box.label(text="Camera Controls", icon="CAMERA_DATA")
        shot_box.prop(props, "nav_altitude_km", text="Altitude (km)")
        shot_box.prop(props, "nav_azimuth_deg", text="Heading (°)")
        shot_box.prop(props, "nav_tilt_deg", text="Tilt (°)")
        shot_box.prop(props, "nav_roll_deg", text="Roll (°)")

        preset_box = layout.box()
        preset_box.enabled = not prepared
        preset_box.label(text="Altitude Presets", icon="ORIENTATION_GLOBAL")
        preset_row_top = preset_box.row(align=True)
        preset_row_top.operator(
            "planetka.navigation_preset",
            text="Max Proximity",
            icon="ZOOM_IN",
        ).preset = "MAX_PROXIMITY"
        preset_row_top.operator(
            "planetka.navigation_preset",
            text="ISS Orbit",
            icon="ORIENTATION_GLOBAL",
        ).preset = "ISS_ORBIT"
        preset_row_bottom = preset_box.row(align=True)
        preset_row_bottom.operator(
            "planetka.navigation_preset",
            text="Geosynchronous",
            icon="CON_SIZELIMIT",
        ).preset = "GEOSYNCHRONOUS"
        preset_row_bottom.operator(
            "planetka.navigation_preset",
            text="Globe View",
            icon="WORLD_DATA",
        ).preset = "HIGH_ORBIT"


class PLANETKA_PT_NavigationSavedLocationsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Save / Load Location"
    bl_idname = "PLANETKA_PT_navigation_saved_locations"
    bl_parent_id = "PLANETKA_PT_navigation"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 10

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if not props:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.prop(props, "nav_saved_location_name", text="Location Name")
        save_row = layout.row(align=True)
        save_row.operator(
            "planetka.save_location",
            text="Save Location",
            icon="ADD",
        )
        save_row.operator(
            "planetka.delete_saved_location",
            text="",
            icon="TRASH",
        )
        layout.prop(props, "nav_saved_location_id", text="Saved Locations")
        layout.operator(
            "planetka.load_saved_location",
            text="Load Saved Location",
            icon="IMPORT",
        )


class PLANETKA_PT_SunlightPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Sunlight"
    bl_idname = "PLANETKA_PT_sunlight"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if not props:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.prop(props, "sunlight_longitude_deg", text="Longitude (°)")
        layout.prop(props, "sunlight_seasonal_tilt_deg", text="Seasonal Tilt (°)")

        layout.separator()
        layout.label(text="Presets", icon="LIGHT_SUN")

        row1 = layout.row(align=True)
        row1.operator("planetka.sunlight_preset", text="Dawn").preset = "DAWN"
        row1.operator("planetka.sunlight_preset", text="Dusk").preset = "DUSK"

        row2 = layout.row(align=True)
        row2.operator("planetka.sunlight_preset", text="Sunrise").preset = "SUNRISE"
        row2.operator("planetka.sunlight_preset", text="Sunset").preset = "SUNSET"

        row3 = layout.row(align=True)
        row3.operator("planetka.sunlight_preset", text="Early Morning").preset = "EARLY_MORNING"
        row3.operator("planetka.sunlight_preset", text="Late Afternoon").preset = "LATE_AFTERNOON"

        row4 = layout.row(align=True)
        row4.operator("planetka.sunlight_preset", text="Mid-morning").preset = "MID_MORNING"
        row4.operator("planetka.sunlight_preset", text="Mid-afternoon").preset = "MID_AFTERNOON"

        row5 = layout.row(align=True)
        row5.operator("planetka.sunlight_preset", text="Noon").preset = "NOON"
        row5.operator("planetka.sunlight_preset", text="Night").preset = "NIGHT"


class PLANETKA_PT_AtmospherePanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Atmosphere"
    bl_idname = "PLANETKA_PT_atmosphere"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if not props:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        row = layout.row()
        row.use_property_split = False
        row.prop(props, "enable_fake_atmosphere", text="Enable Atmosphere", toggle=True)

        density_row = layout.row()
        density_row.enabled = bool(getattr(props, "enable_fake_atmosphere", False))
        density_row.prop(props, "fake_atmosphere_density", text="Atmosphere Density", slider=True)

        height_row = layout.row()
        height_row.enabled = bool(getattr(props, "enable_fake_atmosphere", False))
        height_row.prop(props, "fake_atmosphere_height_km", text="Atmosphere Height (km)", slider=True)

        color_row = layout.row()
        color_row.enabled = bool(getattr(props, "enable_fake_atmosphere", False))
        color_row.prop(props, "fake_atmosphere_color", text="Atmosphere Color")

class PLANETKA_PT_AnimationPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Animation"
    bl_idname = "PLANETKA_PT_animation"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # Cinematic presets are part of the public UI; render-setup stays internal-only.
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        cinematic_box = layout.box()
        cinematic_box.label(text="Cinematic Camera", icon="CAMERA_DATA")
        cinematic_box.prop(props, "anim_camera_preset", text="Preset")
        cinematic_box.prop(props, "anim_frame_start", text="Start Frame")
        cinematic_box.prop(props, "anim_frame_end", text="End Frame")
        cinematic_box.prop(props, "anim_camera_strength", text="Preset Strength")
        cinematic_box.prop(props, "anim_motion_curve", text="Motion Curve")

        preset = str(getattr(props, "anim_camera_preset", "ORBIT")).upper()
        if preset in {"ORBIT", "ARC_LEFT", "ARC_RIGHT", "HELIX_DOWN", "HELIX_UP"}:
            cinematic_box.prop(props, "anim_orbit_degrees", text="Orbit Degrees")
        if preset in {"ORBIT", "HELIX_DOWN", "HELIX_UP"}:
            cinematic_box.prop(props, "anim_circle_direction", text="Direction")
        if preset in {"PUSH_IN", "PULL_BACK", "HELIX_DOWN", "HELIX_UP"}:
            cinematic_box.prop(props, "anim_start_altitude_km", text="Start Altitude (km)")
            cinematic_box.prop(props, "anim_end_altitude_km", text="End Altitude (km)")
        if preset in {"PUSH_IN", "PULL_BACK"}:
            cinematic_box.prop(props, "anim_zoom_rotate_degrees", text="Rotate (°)")
        if preset == "FLYBY":
            cinematic_box.prop(props, "anim_flyby_degrees", text="Flyby Degrees")
            cinematic_box.prop(props, "anim_flyby_camera_heading_deg", text="Camera Heading (°)")
        if preset == "A_TO_B":
            view_row = cinematic_box.row(align=True)
            view_row.operator("planetka.animation_save_view", text="Save View A", icon="BOOKMARKS").slot = "A"
            view_row.operator("planetka.animation_save_view", text="Save View B", icon="BOOKMARKS").slot = "B"
            status_a = "Ready" if bool(getattr(props, "anim_ab_a_valid", False)) else "Not Set"
            status_b = "Ready" if bool(getattr(props, "anim_ab_b_valid", False)) else "Not Set"
            cinematic_box.label(text=f"View A: {status_a}")
            cinematic_box.label(text=f"View B: {status_b}")

        preview_row = cinematic_box.row()
        preview_row.scale_y = 1.15
        preview_row.operator(
            "planetka.animation_preview_shot",
            text="Preview Shot",
            icon="PLAY",
        )

        render_box = layout.box()
        render_box.label(text="Rendering", icon="RENDER_ANIMATION")
        if _is_animation_prepared(scene):
            render_box.label(text="Prepared animation setup will be cleared.", icon="INFO")

        preset_row = render_box.row(align=True)
        preset_row.use_property_split = False
        preset_row.prop_enum(props, "anim_render_preset", "SPEED", text="Speed Optimized")
        preset_row.prop_enum(props, "anim_render_preset", "MEMORY", text="Memory Optimized")

        render_box.separator()
        subdiv_box = render_box.box()
        subdiv_box.label(text="Subdivision", icon="MOD_SUBSURF")
        subdiv_box.prop(props, "anim_render_dicing_rate", text="Dicing Rate Render")
        subdiv_box.prop(props, "anim_render_offscreen_scale", text="Offscreen Scale")

        perf_box = render_box.box()
        perf_box.label(text="Performance", icon="TIME")
        perf_box.prop(props, "anim_render_persistent_data", text="Persistent Data")

        render_box.separator()
        render_box.label(text="Blender will be unresponsive during render", icon="INFO")
        render_row = render_box.row()
        render_row.scale_y = 1.2
        render_row.operator(
            "planetka.animation_render_headless",
            text="Prepare Animation Render",
            icon="RENDER_ANIMATION",
        )

        # Hide the memory-intensive, preloaded-segment render workflow from public UI.
        if _show_internal_animation_ui():
            prepared = _is_animation_prepared(scene)
            prep_box = layout.box()
            prep_box.label(text="Animation Render Setup", icon="RENDER_ANIMATION")
            if prepared:
                _draw_animation_ready_message(prep_box)
            prep_box.prop(props, "anim_prepare_max_segments", text="Max Segments")
            prep_box.prop(props, "anim_prepare_max_textures_mb", text="Max Textures (MB)")
            make_ready_row = prep_box.row()
            make_ready_row.scale_y = 1.2
            make_ready_row.enabled = not prepared
            make_ready_row.operator(
                "planetka.animation_make_ready",
                text="Make Ready to Render",
                icon="RENDER_ANIMATION",
            )
            clear_row = prep_box.row()
            clear_row.scale_y = 1.05
            clear_row.operator(
                "planetka.animation_clear_prepared",
                text="Clear Prepared",
                icon="TRASH",
            )

            prepared_segments = scene.get(ANIMATION_STATS_SEGMENTS_KEY)
            prepared_mb = scene.get(ANIMATION_STATS_TEXTURE_MB_KEY)
            prepared_start = scene.get(ANIMATION_STATS_START_KEY)
            prepared_end = scene.get(ANIMATION_STATS_END_KEY)
            if prepared_segments is not None:
                prep_box.separator()
                prep_box.label(text=f"Prepared Segments: {_fmt_int(prepared_segments)}")
                prep_box.label(text=f"Prepared Textures: {_fmt_mb(prepared_mb)}")
                prep_box.label(text=f"Prepared Frames: {_fmt_int(prepared_start)}-{_fmt_int(prepared_end)}")
