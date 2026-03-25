"""Planetka UI panels and telemetry rendering."""

import bpy
import datetime

from .auth import (
    PLAN_CODE_PLANETKA_PRO,
    PLAN_CODE_PLANETKA_STUDIO,
    get_commercial_use_allowed,
    get_connected_email,
    get_login_state,
    get_plan_code,
    get_status_message,
    is_authenticated,
    is_pro_account,
)
from .extension_prefs import get_earth_object
from .geonames_db import get_search_status_text
from .diagnostics import read_diagnostics
from .r2_source import get_download_progress, is_download_active
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
    get_resolve_runtime_status,
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


def _status_activity_suffix(running):
    if not bool(running):
        return ""
    phase = int(datetime.datetime.now().timestamp() * 2.0) % 3
    return "." * (phase + 1)


def _status_icon(code):
    token = str(code or "").upper()
    if token == "DOWNLOADING":
        return "IMPORT"
    if token in {"FINALIZING", "FINALIZE_QUEUED"}:
        return "MOD_REMESH"
    if token == "QUEUED":
        return "SORTTIME"
    if token == "MONITORING":
        return "VIEW_CAMERA"
    if token == "IDLE":
        return "CHECKMARK"
    return "INFO"


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


def _full_texture_quality_allowed():
    from .extension_prefs import get_prefs

    prefs = get_prefs()
    if prefs is None:
        return False
    return bool(is_pro_account(prefs) or get_commercial_use_allowed(prefs))


def _is_cloud_source_mode():
    return True


def _is_earth_workflow_enabled():
    if not _has_earth():
        return False
    if _is_cloud_source_mode():
        return _is_connected()
    return True


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


def _draw_subscription(layout):
    layout.use_property_split = False
    layout.use_property_decorate = False

    from .extension_prefs import get_prefs

    prefs = get_prefs()
    login_state = get_login_state(prefs)
    connected = is_authenticated(prefs)
    status_message = get_status_message(prefs)

    if not connected:
        layout.label(text="Sign in to start using Planetka", icon="INFO")
        auth_row = layout.row(align=True)
        if login_state == "pending":
            auth_row.operator("planetka.account_open_login", text="Open Login Page", icon="URL")
            auth_row.operator("planetka.account_cancel_login", text="Cancel", icon="X")
        else:
            auth_row.operator("planetka.account_login", text="Sign In / Create Account", icon="URL")
        if status_message:
            layout.label(text=status_message, icon="INFO")
        return

    email = get_connected_email(prefs)
    plan_code = get_plan_code(prefs)
    commercial_use_allowed = get_commercial_use_allowed(prefs)

    if commercial_use_allowed or plan_code in {PLAN_CODE_PLANETKA_PRO, PLAN_CODE_PLANETKA_STUDIO}:
        license_text = "Pro - Commercial"
    else:
        license_text = "Free - Personal use only"

    layout.label(text=f"Account: {email}", icon="CHECKMARK")
    layout.label(text=f"Licence: {license_text}", icon="INFO")

    action_row = layout.row(align=True)
    action_row.operator("wm.url_open", text="Contact me", icon="URL").url = "https://www.planetka.io/contact-me"
    action_row.operator("planetka.account_logout", text="Log Out", icon="X")

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

    progress = get_download_progress()
    active_download = is_download_active()
    downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
    total_bytes = int(progress.get("total_bytes", 0) or 0)
    downloaded_mb = float(downloaded_bytes) / (1024.0 * 1024.0)
    total_mb = float(total_bytes) / (1024.0 * 1024.0)
    runtime = get_resolve_runtime_status(scene)
    runtime_code = str(runtime.get("code", "IDLE") or "IDLE").upper()
    runtime_text = str(runtime.get("text", "Idle") or "Idle")
    if active_download and runtime_code not in {"DOWNLOADING", "FINALIZING"}:
        runtime_code = "DOWNLOADING"
        runtime_text = "Downloading Data"

    layout.label(
        text=f"{runtime_text}{_status_activity_suffix(runtime.get('running', False))}",
        icon=_status_icon(runtime_code),
    )

    if runtime_code == "DOWNLOADING":
        if total_bytes > 0:
            layout.label(text=f"{downloaded_mb:.2f} / {total_mb:.2f} MB")
        else:
            layout.label(text=f"{downloaded_mb:.2f} MB")
    elif runtime_code in {"QUEUED", "FINALIZE_QUEUED"}:
        request_id = runtime.get("active_request_id")
        pending_count = int(runtime.get("pending_count", 0) or 0)
        if request_id is not None:
            layout.label(text=f"Request: #{request_id}")
        if pending_count > 0:
            layout.label(text=f"Queued jobs: {pending_count}")


def _draw_advanced_telemetry(layout, scene):
    layout.use_property_split = False
    layout.use_property_decorate = False
    diag = read_diagnostics(scene)
    advanced_col = layout.column(align=True)
    download_size_mb = diag.get("resolve_downloaded_mb")
    download_time_ms = diag.get("resolve_download_ms")
    download_thread_ms = diag.get("resolve_download_thread_ms")
    advanced_col.label(text=f"Tiles: {_fmt_int(diag.get('last_tile_count'))}")
    advanced_col.label(text=f"Spatial Resolution: {_fmt_m(diag.get('resolve_required_mpp_m'))}")
    advanced_col.label(text=f"Tiles Size: {_fmt_mb(diag.get('resolve_textures_mb'))}")
    advanced_col.label(text=f"Pre-calculation Time: {_fmt_ms(diag.get('last_resolve_ms'))}")
    advanced_col.label(text=f"Download Time (Wall): {_fmt_ms(download_time_ms)}")
    if download_thread_ms is not None:
        advanced_col.label(text=f"Download Time (Summed Requests): {_fmt_ms(download_thread_ms)}")
    advanced_col.label(text=f"Download Size: {_fmt_mb(download_size_mb)}")
    advanced_col.label(text=f"Effective Download Speed: {_fmt_mbps(download_size_mb, download_time_ms)}")


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
    shot_box.prop(props, "nav_focal_length_mm", text="Focal Length (mm)")

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

    resolve_box = layout.box()
    resolve_box.enabled = not prepared
    resolve_box.label(text="Resolve Settings", icon="MOD_REMESH")
    resolve_op = resolve_box.operator(
        "planetka.load_textures",
        text="Resolve Earth Surface",
        icon="MOD_REMESH",
    )
    # Keep Blender responsive while downloading; finalize resolve after download completes.
    resolve_op.defer_download = True
    resolve_box.prop(
        props,
        "auto_resolve",
        text="Auto Resolve",
        toggle=True,
        icon="FILE_REFRESH",
    )
    if _show_internal_animation_ui():
        resolve_box.prop(
            props,
            "lock_resolve_during_animation",
            text="Lock Resolve During Animation",
            toggle=True,
        )


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


_SURFACE_GRADING_SECTION_ORDER = (
    "Global",
    "Water",
    "Elevation",
    "Night Lights",
)

_SURFACE_GRADING_SECTION_SOCKET_MAP = {
    "Global": {
        "surface brightness",
        "surface saturation",
    },
    "Water": {
        "roughness",
        "ior",
        "saturation",
        "water texture strength",
        "hue",
        "brightness",
    },
    "Elevation": {
        "coefficient",
        "procedural detail scale",
        "forest detail strength",
        "rock detail strength",
        "rock color variation",
        "micro displacement strength",
    },
    "Night Lights": {
        "intensity",
        "color temperature",
    },
}


def _surface_grading_section_for_socket(socket_name):
    normalized = str(socket_name or "").strip().lower()
    for section in _SURFACE_GRADING_SECTION_ORDER:
        names = _SURFACE_GRADING_SECTION_SOCKET_MAP.get(section, set())
        if normalized in names:
            return section
    return None


def _split_surface_grading_sockets(sockets):
    grouped = {section: [] for section in _SURFACE_GRADING_SECTION_ORDER}
    for socket in sockets or ():
        section = _surface_grading_section_for_socket(getattr(socket, "name", ""))
        if section is None:
            continue
        grouped.setdefault(section, []).append(socket)
    return grouped


def _surface_grading_socket_label(socket_name):
    normalized = str(socket_name or "").strip().lower()
    if normalized == "surface brightness":
        return "Brightness"
    if normalized == "surface saturation":
        return "Saturation"
    return str(socket_name or "Value")


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
        grouped = _split_surface_grading_sockets(sockets)
        for section in _SURFACE_GRADING_SECTION_ORDER:
            section_sockets = grouped.get(section, [])
            if not section_sockets:
                continue
            section_box = container.box()
            section_box.label(text=section)
            for socket in section_sockets:
                row = section_box.row()
                try:
                    row.prop(socket, "default_value", text=_surface_grading_socket_label(getattr(socket, "name", "")))
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    continue


def _iter_atmosphere_nodes():
    object_name = "Atmosphere - Volumetric"
    group_name = "Planetka Atmosphere Group"
    try:
        from .asset_builder import VOLUMETRIC_ATMOSPHERE_GROUP_NAME, VOLUMETRIC_ATMOSPHERE_OBJECT_NAME

        object_name = str(VOLUMETRIC_ATMOSPHERE_OBJECT_NAME or object_name)
        group_name = str(VOLUMETRIC_ATMOSPHERE_GROUP_NAME or group_name)
    except Exception:
        pass

    atmosphere_obj = bpy.data.objects.get(object_name)
    if atmosphere_obj is None:
        return []

    nodes = []
    for slot in getattr(atmosphere_obj, "material_slots", ()):
        material = getattr(slot, "material", None)
        if material is None or not bool(getattr(material, "use_nodes", False)):
            continue
        node_tree = getattr(material, "node_tree", None)
        if node_tree is None:
            continue
        for node in getattr(node_tree, "nodes", ()):
            if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                continue
            node_group = getattr(node, "node_tree", None)
            node_group_name = str(getattr(node_group, "name", ""))
            lowered = node_group_name.lower()
            if node_group_name == group_name or ("atmosphere" in lowered and "fake" not in lowered):
                nodes.append(node)
    return nodes


def _iter_atmosphere_input_sockets(node):
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


def _draw_atmosphere(layout, context):
    layout.use_property_split = True
    layout.use_property_decorate = False

    scene = getattr(context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    if not props:
        layout.label(text="Planetka settings unavailable.", icon="ERROR")
        return

    layout.prop(props, "atmosphere_enabled", text="Enable Atmosphere")

    nodes = _iter_atmosphere_nodes()
    if not nodes:
        layout.label(text="Volumetric atmosphere shader not found.", icon="INFO")
        return

    many_nodes = len(nodes) > 1
    for index, node in enumerate(nodes, start=1):
        container = layout.box() if many_nodes else layout
        if many_nodes:
            container.label(text=f"Atmosphere Shader Node {index}", icon="NODETREE")
        sockets = _iter_atmosphere_input_sockets(node)
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
    bl_label = "Account"
    bl_idname = "PLANETKA_PT_subscription"
    bl_order = 0
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not _is_connected()

    def draw(self, context):
        _draw_subscription(self.layout)


class PLANETKA_PT_SubscriptionPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Account"
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
    bl_order = 2
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
    bl_order = 2

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
    bl_order = 3
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        _draw_resolve(self.layout)


class PLANETKA_PT_ResolvePanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Resolve"
    bl_idname = "PLANETKA_PT_resolve_collapsed"
    bl_order = 3

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

        from .extension_prefs import get_prefs
        prefs = get_prefs()

        if props:
            auto_resolve_box = layout.box()
            auto_resolve_box.label(text="Auto Resolve", icon="FILE_REFRESH")
            auto_resolve_box.enabled = workflow_enabled and bool(getattr(props, "auto_resolve", False))
            auto_resolve_box.prop(
                props,
                "auto_resolve_idle_sec",
                text="Auto Resolve Idle Delay (s)",
                slider=True,
            )

            texture_quality_box = layout.box()
            texture_quality_box.label(text="Texture Quality", icon="TEXTURE")
            texture_quality_box.enabled = workflow_enabled
            quality_row = texture_quality_box.row(align=True)
            quality_row.use_property_split = False
            full_row = quality_row.row(align=True)
            full_row.enabled = _full_texture_quality_allowed()
            full_row.prop_enum(props, "texture_quality_mode", "FULL", text="Full")
            quality_row.prop_enum(props, "texture_quality_mode", "HALF", text="Half")
            quality_row.prop_enum(props, "texture_quality_mode", "QUARTER", text="Quarter")
            if not _full_texture_quality_allowed():
                texture_quality_box.label(text="Full quality is available for Pro licence only.", icon="INFO")

            viewport_box = layout.box()
            viewport_box.label(text="Viewport Optimization", icon="VIEW3D")
            viewport_box.enabled = workflow_enabled
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
    bl_label = "Status Check"
    bl_idname = "PLANETKA_PT_live_telemetry"
    bl_order = 4
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _is_earth_workflow_enabled()

    def draw(self, context):
        self.layout.enabled = _is_earth_workflow_enabled()
        scene = getattr(context, "scene", None)
        _draw_live_telemetry(self.layout, scene)


class PLANETKA_PT_LiveTelemetryPanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Status Check"
    bl_idname = "PLANETKA_PT_live_telemetry_collapsed"
    bl_order = 4

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
        return False

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
        return False

    def draw(self, context):
        self.layout.enabled = False
        scene = getattr(context, "scene", None)
        _draw_advanced_telemetry(self.layout, scene)


class PLANETKA_PT_LinksPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Knowledge Base"
    bl_idname = "PLANETKA_PT_links"
    bl_order = 1000
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator("wm.url_open", text="Documentation", icon="HELP").url = "https://www.planetka.io/blender/documentation/"
        row.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.planetka.io/blender/tutorials/"
        row = layout.row(align=True)
        row.operator("planetka.report_bug", text="Report Bug", icon="ERROR")
        row.operator("wm.url_open", text="Discord", icon="URL").url = "https://discord.com/channels/1484086341099589742/1484087649722699846"

        layout.operator(
            "wm.url_open",
            text="www.planetka.io",
            icon="URL",
        ).url = "https://www.planetka.io"


class PLANETKA_PT_NavigationPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Navigation"
    bl_idname = "PLANETKA_PT_navigation"
    bl_order = 5
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
    bl_order = 5

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
        return False

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
        return False

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
    bl_label = "Earth Grading"
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
    bl_label = "Earth Grading"
    bl_idname = "PLANETKA_PT_surface_grading_collapsed"
    bl_order = 5

    @classmethod
    def poll(cls, context):
        return not _is_earth_workflow_enabled()

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
        _draw_surface_grading(layout)


class PLANETKA_PT_AtmospherePanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Atmosphere"
    bl_idname = "PLANETKA_PT_atmosphere"
    bl_order = 5

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_earth_workflow_enabled()
        _draw_atmosphere(layout, context)


class PLANETKA_PT_AtmospherePanelCollapsed(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Atmosphere"
    bl_idname = "PLANETKA_PT_atmosphere_collapsed"
    bl_order = 5

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        layout.enabled = False
        _draw_atmosphere(layout, context)


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

        layout.prop(props, "sunlight_strength", text="Strength")
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


class PLANETKA_PT_AnimationPanel(_PLANETKA_PT_BaseSection, bpy.types.Panel):
    bl_label = "Animation"
    bl_idname = "PLANETKA_PT_animation"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # Cinematic presets are part of the public UI; render-setup stays internal-only.
        return True

    def draw(self, context):
        layout = self.layout
        layout.enabled = _is_earth_workflow_enabled()
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
