import bpy

from .auth import get_connected_email, get_login_state, get_status_message, is_authenticated
from .extension_prefs import get_earth_object
from .geonames_db import get_search_status_text
from .diagnostics import read_diagnostics
from .r2_source import get_download_progress, is_download_active
from .state import (
    ADD_EARTH_BUTTON_SCALE_X,
    ADD_EARTH_BUTTON_SCALE_Y,
    REFRESH_BUTTON_ALERT,
    REFRESH_BUTTON_SCALE_X,
    REFRESH_BUTTON_SCALE_Y,
)

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


def _fmt_mbps(downloaded_mb, download_ms):
    if downloaded_mb is None or download_ms is None:
        return "—"
    try:
        size_mb = float(downloaded_mb)
        elapsed_ms = float(download_ms)
        if elapsed_ms <= 0.0:
            return "—"
        return f"{size_mb / (elapsed_ms / 1000.0):.2f} MB/s"
    except (TypeError, ValueError, ZeroDivisionError):
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


def _is_connected():
    from .extension_prefs import get_prefs

    return is_authenticated(get_prefs())


def _is_earth_workflow_enabled():
    return _has_earth() and _is_connected()


def _is_animation_prepared(scene):
    _ = scene
    return False


def _draw_animation_ready_message(layout):
    message = layout.box()
    message.alert = False
    message.label(text="Ready to Render Animation.", icon="CHECKMARK")
    message.label(text="Clear Prepared to return to editing.", icon="INFO")
    return message


def _draw_subscription(layout):
    layout.use_property_split = False
    layout.use_property_decorate = False

    from .extension_prefs import get_prefs

    prefs = get_prefs()
    login_state = get_login_state(prefs)
    connected = is_authenticated(prefs)
    email = get_connected_email(prefs)
    status_message = get_status_message(prefs)

    layout.label(text="Licence: Free pre-release", icon="INFO")
    layout.label(text="Activation flow: email only, no payment gate.", icon="CHECKMARK")
    layout.label(text="1) Enter your email on the activation page.", icon="INFO")
    layout.label(text="2) Click the activation link in your email.", icon="INFO")
    layout.label(text="3) Blender signs in automatically.", icon="INFO")

    if connected:
        layout.label(text=f"Account: {email}", icon="CHECKMARK")
        layout.label(text="Status: Activated", icon="CHECKMARK")
        auth_row = layout.row(align=True)
        auth_row.operator("planetka.account_logout", text="Log Out", icon="X")
    elif login_state == "pending":
        layout.label(text="Account: Waiting for email activation", icon="TIME")
        auth_row = layout.row(align=True)
        auth_row.operator("planetka.account_open_login", text="Open Activation Page", icon="URL")
        auth_row.operator("planetka.account_cancel_login", text="Cancel", icon="X")
    else:
        layout.label(text="Account: Not Connected", icon="USER")
        auth_row = layout.row(align=True)
        auth_row.operator("planetka.account_login", text="Activate Free Pre-release", icon="URL")

    if status_message:
        layout.label(text=status_message, icon="INFO")

def _draw_new_earth(layout):
    layout.use_property_split = False
    layout.use_property_decorate = False
    connected = _is_connected()
    has_earth = _has_earth()

    row = layout.row()
    row.scale_x = ADD_EARTH_BUTTON_SCALE_X
    row.scale_y = ADD_EARTH_BUTTON_SCALE_Y
    row.alert = False
    row.enabled = (not has_earth) and connected
    row.operator("planetka.add_earth", text="Create Earth", icon="WORLD_DATA")


def _draw_resolve(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False
    scene = getattr(bpy.context, "scene", None)
    from .extension_prefs import get_prefs

    prefs = get_prefs()
    connected = is_authenticated(prefs)
    status_message = get_status_message(prefs)
    prepared = _is_animation_prepared(scene)
    workflow_enabled = _has_earth() and connected
    layout.enabled = workflow_enabled
    if prepared:
        _draw_animation_ready_message(layout)
    if not connected:
        layout.label(text=status_message or "Log in to Planetka before resolving Earth data.", icon="INFO")
    row = layout.row()
    row.scale_x = REFRESH_BUTTON_SCALE_X
    row.scale_y = REFRESH_BUTTON_SCALE_Y
    row.alert = REFRESH_BUTTON_ALERT
    row.enabled = (not prepared) and workflow_enabled and connected
    row.operator("planetka.load_textures", text="Resolve Earth Surface", icon="MOD_REMESH")


def _draw_live_telemetry(layout, scene):
    layout.use_property_split = False
    layout.use_property_decorate = False
    diag = read_diagnostics(scene)
    note_text = _texture_quality_note_text(scene)
    if note_text:
        note_box = layout.box()
        note_box.alert = False
        note_box.label(text=note_text, icon="INFO")
    live_col = layout.column(align=True)
    live_col.label(text=f"Latitude: {_fmt_deg(diag.get('view_latitude_deg'))}")
    live_col.label(text=f"Longitude: {_fmt_deg(diag.get('view_longitude_deg'))}")
    live_col.label(text=f"Altitude: {_fmt_km(diag.get('view_altitude_km'))}")


def _draw_advanced_telemetry(layout, scene):
    layout.use_property_split = False
    layout.use_property_decorate = False
    diag = read_diagnostics(scene)
    advanced_col = layout.column(align=True)
    download_size_mb = diag.get("resolve_downloaded_mb")
    download_time_ms = diag.get("resolve_download_ms")
    advanced_col.label(text=f"Tiles: {_fmt_int(diag.get('last_tile_count'))}")
    advanced_col.label(text=f"Spatial Resolution: {_fmt_m(diag.get('resolve_required_mpp_m'))}")
    advanced_col.label(text=f"Tiles Size: {_fmt_mb(diag.get('resolve_textures_mb'))}")
    advanced_col.label(text=f"Pre-calculation Time: {_fmt_ms(diag.get('last_resolve_ms'))}")
    advanced_col.label(text=f"Download Time: {_fmt_ms(download_time_ms)}")
    advanced_col.label(text=f"Download Size: {_fmt_mb(download_size_mb)}")
    advanced_col.label(text=f"Effective Download Speed: {_fmt_mbps(download_size_mb, download_time_ms)}")
    progress = get_download_progress()
    active_download = is_download_active()
    downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
    total_bytes = int(progress.get("total_bytes", 0) or 0)
    downloaded_mb = float(downloaded_bytes) / (1024.0 * 1024.0)
    total_mb = float(total_bytes) / (1024.0 * 1024.0)

    advanced_col.label(text="Downloading Data", icon="FILE_REFRESH")
    if active_download:
        if total_bytes > 0:
            advanced_col.label(text=f"{downloaded_mb:.2f} / {total_mb:.2f} MB")
        else:
            advanced_col.label(text=f"{downloaded_mb:.2f} / -- MB")
    else:
        advanced_col.label(text="Idle")


def _texture_quality_note_text(scene):
    props = getattr(scene, "planetka", None) if scene else None
    if props is None:
        return ""

    mode = str(getattr(props, "texture_quality_mode", "FULL") or "FULL").upper()
    if mode == "HALF":
        return "Texture Quality set to Half."
    if mode == "QUARTER":
        return "Texture Quality set to Quarter."
    return ""


def _draw_navigation(layout, context):
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


def _iter_surface_grading_nodes():
    material_name = "Planetka Earth Material"
    group_name = "Planetka Surface Grading Group"
    try:
        from .asset_builder import EARTH_MATERIAL_NAME, SURFACE_GRADING_GROUP_NAME

        material_name = str(EARTH_MATERIAL_NAME or material_name)
        group_name = str(SURFACE_GRADING_GROUP_NAME or group_name)
    except Exception:
        pass

    material = bpy.data.materials.get(material_name)
    if material is None or not bool(getattr(material, "use_nodes", False)):
        return []
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return []

    nodes = []
    for node in getattr(node_tree, "nodes", ()):
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        node_group = getattr(node, "node_tree", None)
        if str(getattr(node_group, "name", "")) == group_name:
            nodes.append(node)
    return nodes


def _iter_surface_grading_input_sockets(node):
    sockets = []
    for socket in getattr(node, "inputs", ()):
        if bool(getattr(socket, "is_linked", False)):
            continue
        if not hasattr(socket, "default_value"):
            continue
        socket_type = str(getattr(socket, "bl_socket_idname", "")).strip()
        if socket_type in {"NodeSocketShader", "NodeSocketVirtual"}:
            continue
        sockets.append(socket)
    return sockets


def _draw_surface_grading(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False

    nodes = _iter_surface_grading_nodes()
    if not nodes:
        layout.label(text="Earth Surface Grading node group not found.", icon="INFO")
        return

    many_nodes = len(nodes) > 1
    for index, node in enumerate(nodes, start=1):
        container = layout.box() if many_nodes else layout
        if many_nodes:
            container.label(text=f"Surface Grading Node {index}", icon="NODETREE")
        sockets = _iter_surface_grading_input_sockets(node)
        if not sockets:
            container.label(text="No adjustable inputs found.", icon="INFO")
            continue
        for socket in sockets:
            row = container.row()
            try:
                row.prop(socket, "default_value", text=str(getattr(socket, "name", "Value")))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue


class PLANETKA_PT_SubscriptionPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Subscription"
    bl_idname = "PLANETKA_PT_subscription"
    bl_order = 0
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not _is_connected()

    def draw(self, context):
        _draw_subscription(self.layout)


class PLANETKA_PT_SubscriptionPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Subscription"
    bl_idname = "PLANETKA_PT_subscription_collapsed"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return _is_connected()

    def draw(self, context):
        _draw_subscription(self.layout)


class PLANETKA_PT_NewEarthPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "New Earth"
    bl_idname = "PLANETKA_PT_new_earth"
    bl_order = 1
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_connected()
        _draw_new_earth(layout)


class PLANETKA_PT_NewEarthPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "New Earth"
    bl_idname = "PLANETKA_PT_new_earth_collapsed"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return _has_earth()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_connected()
        _draw_new_earth(layout)


class PLANETKA_PT_ResolvePanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Resolve"
    bl_idname = "PLANETKA_PT_resolve"
    bl_order = 2
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        _draw_resolve(self.layout)


class PLANETKA_PT_ResolvePanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Resolve"
    bl_idname = "PLANETKA_PT_resolve_collapsed"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        _draw_resolve(self.layout)


class PLANETKA_PT_SettingsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Settings"
    bl_idname = "PLANETKA_PT_settings"
    bl_order = 6

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        prepared = _is_animation_prepared(scene)
        workflow_enabled = _is_earth_workflow_enabled()

        source_box = layout.box()
        source_box.label(text="Data Source", icon="URL")
        source_box.label(text="Cloudflare", icon="CHECKMARK")
        source_box.label(text="Pre-release is Cloudflare-only.", icon="INFO")

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
            resolve_box.enabled = workflow_enabled and (not prepared)
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
            render_engine_box = layout.box()
            render_engine_box.label(text="Renderer Optimization", icon="RENDER_STILL")
            render_engine_box.label(text="Switch and Optimize for:")
            render_engine_box.enabled = workflow_enabled
            render_toggle_row = render_engine_box.row(align=True)
            render_toggle_row.use_property_split = False
            render_toggle_row.prop_enum(
                props,
                "render_engine_optimization",
                "EEVEE",
                text="EEVEE",
            )
            render_toggle_row.prop_enum(
                props,
                "render_engine_optimization",
                "CYCLES",
                text="Cycles",
            )

            quality_box = layout.box()
            quality_box.label(text="Texture Quality", icon="TEXTURE")
            quality_box.enabled = workflow_enabled
            quality_box.prop(props, "texture_quality_mode", text="Texture Quality")

            viewport_box = layout.box()
            viewport_box.label(text="Viewport Optimization", icon="VIEW3D")
            viewport_box.enabled = workflow_enabled
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

            objects_box = layout.box()
            objects_box.label(text="Scene Objects", icon="OUTLINER_OB_EMPTY")
            objects_box.enabled = workflow_enabled
            objects_box.prop(
                props,
                "show_earth_preview",
                text="Show Earth Preview",
                toggle=True,
            )

class PLANETKA_PT_LiveTelemetryPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Telemetry"
    bl_idname = "PLANETKA_PT_live_telemetry"
    bl_order = 3
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        self.layout.enabled = _is_earth_workflow_enabled()
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LiveTelemetryPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Telemetry"
    bl_idname = "PLANETKA_PT_live_telemetry_collapsed"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        self.layout.enabled = False
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LiveTelemetryAdvancedPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Advanced Telemetry"
    bl_idname = "PLANETKA_PT_live_telemetry_advanced"
    bl_parent_id = "PLANETKA_PT_live_telemetry"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        scene = getattr(context, "scene", None)
        _draw_advanced_telemetry(self.layout, scene)


class PLANETKA_PT_LiveTelemetryAdvancedPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Advanced Telemetry"
    bl_idname = "PLANETKA_PT_live_telemetry_advanced_collapsed"
    bl_parent_id = "PLANETKA_PT_live_telemetry_collapsed"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        self.layout.enabled = False
        scene = getattr(context, "scene", None)
        _draw_advanced_telemetry(self.layout, scene)


class PLANETKA_PT_LinksPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Knowledge Base"
    bl_idname = "PLANETKA_PT_links"
    bl_order = 1000

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_earth_workflow_enabled()
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
        return _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_earth_workflow_enabled()
        _draw_navigation(layout, context)


class PLANETKA_PT_NavigationPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Navigation"
    bl_idname = "PLANETKA_PT_navigation_collapsed"
    bl_order = 4

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
        _draw_navigation(layout, context)


class PLANETKA_PT_NavigationSavedLocationsPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Save / Load Location"
    bl_idname = "PLANETKA_PT_navigation_saved_locations"
    bl_parent_id = "PLANETKA_PT_navigation"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 10

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_earth_workflow_enabled()
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


class PLANETKA_PT_NavigationSavedLocationsPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Save / Load Location"
    bl_idname = "PLANETKA_PT_navigation_saved_locations_collapsed"
    bl_parent_id = "PLANETKA_PT_navigation_collapsed"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 10

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
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


class PLANETKA_PT_SurfaceGradingPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Surface Grading"
    bl_idname = "PLANETKA_PT_surface_grading"
    bl_order = 5

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_earth_workflow_enabled()
        _draw_surface_grading(layout)


class PLANETKA_PT_SurfaceGradingPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Surface Grading"
    bl_idname = "PLANETKA_PT_surface_grading_collapsed"
    bl_order = 5

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
        _draw_surface_grading(layout)


class PLANETKA_PT_SunlightPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Sunlight"
    bl_idname = "PLANETKA_PT_sunlight"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_earth_workflow_enabled()
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
