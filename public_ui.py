import bpy

from .auth import (
    CLOUD_OVERLOADED_MESSAGE,
    addon_edition_label,
    ensure_authenticated_session,
    get_cached_cloud_connection_status,
    get_service_status,
    get_status_message,
    is_authenticated,
    local_addon_edition_code,
)
from .extension_prefs import get_earth_object, get_prefs
from .r2_source import get_download_progress
from .state import (
    LAST_RESOLVE_DOWNLOADED_MB_KEY,
    LAST_RESOLVE_TILE_COUNT_KEY,
    get_resolve_runtime_status,
    is_final_animation_render_active,
)


CREATE_EARTH_STATUS_KEY = "planetka_create_earth_status"
CREATE_EARTH_STATUS_ACTIVE_KEY = "planetka_create_earth_status_active"


def _has_earth():
    return get_earth_object() is not None


def _fmt_mb(value):
    try:
        return f"{float(value or 0.0) / (1024.0 * 1024.0):.2f} MB"
    except (TypeError, ValueError):
        return "0.00 MB"


def _runtime_display(scene):
    try:
        status = get_resolve_runtime_status(scene=scene) or {}
    except (RuntimeError, TypeError, ValueError, AttributeError):
        status = {}
    running = bool(status.get("running", False))
    text = str(status.get("text", "") or "").strip()
    code = str(status.get("code", "") or "").strip().upper()
    if running:
        return text or "Resolving", code or "RUNNING", True
    if text.lower() == "idle":
        text = ""
    return text or "Resolved successfully", code or "DONE", False


def _scene_number(scene, key, default=0.0):
    if scene is None:
        return default
    try:
        return float(scene.get(key, default) or default)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return default


def _progress_display(scene, progress):
    active = bool(progress.get("download_active", False))
    downloaded = int(progress.get("downloaded_bytes", 0) or 0)
    expected = int(progress.get("expected_bytes", 0) or progress.get("total_bytes", 0) or 0)
    if active:
        if expected > 0:
            return f"Downloading: {_fmt_mb(downloaded)} / {_fmt_mb(expected)}", "IMPORT"
        return f"Downloading: {_fmt_mb(downloaded)}", "IMPORT"

    last_downloaded_mb = _scene_number(scene, LAST_RESOLVE_DOWNLOADED_MB_KEY, 0.0)
    last_tile_count = int(_scene_number(scene, LAST_RESOLVE_TILE_COUNT_KEY, 0.0))
    if last_downloaded_mb > 0.0:
        if last_tile_count > 0:
            return f"Last download: {last_downloaded_mb:.2f} MB, {last_tile_count} tiles", "CHECKMARK"
        return f"Last download: {last_downloaded_mb:.2f} MB", "CHECKMARK"
    return "Ready to download", "IMPORT"


def _draw_data_summary(layout):
    has_earth = _has_earth()
    prefs = get_prefs()
    if prefs is not None and not is_authenticated(prefs):
        try:
            ensure_authenticated_session(prefs)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
    authenticated = bool(is_authenticated(prefs))
    cloud = get_cached_cloud_connection_status() if authenticated else {"checked": False, "online": False, "message": ""}
    checked = bool(cloud.get("checked", False))
    online = bool(authenticated and checked and cloud.get("online", False))
    message = str(cloud.get("message", "") or "").strip()
    overloaded = message == CLOUD_OVERLOADED_MESSAGE
    service_status = get_service_status(prefs)
    service_message = str((service_status or {}).get("message", "") or "").strip()
    service_url = str((service_status or {}).get("url", "") or "").strip()
    service_severity = str((service_status or {}).get("severity", "info") or "info").strip().lower()
    session_status_message = str(get_status_message(prefs) or "").strip()

    status_icon = "INFO"
    status_text = "Starting session"
    if service_message:
        status_text = service_message
        status_icon = "ERROR" if service_severity in {"warning", "error", "maintenance"} else "INFO"
    elif session_status_message:
        status_text = session_status_message
        status_icon = "ERROR" if (overloaded or not online) else "INFO"
    elif online:
        status_text = "Connected"
        status_icon = "CHECKMARK"
    elif authenticated and not checked:
        status_text = "Connected" if has_earth else "Ready"
        status_icon = "CHECKMARK"
    elif authenticated and overloaded:
        status_text = "Cloud busy"
        status_icon = "ERROR"
    elif authenticated:
        status_text = "Not connected"
        status_icon = "ERROR"

    box = layout.box()
    box.label(text="Planetka Data", icon="WORLD")
    row = box.row(align=True)
    row.label(text="Status")
    row.label(text=status_text, icon=status_icon)
    if service_message and service_url:
        op = row.operator("planetka_public.open_link", text="", icon="URL")
        op.link_type = "CUSTOM"
        op.url = service_url
        op.tooltip = "Open details for the current Planetka Data status message."

    row = box.row(align=True)
    row.label(text="Edition")
    row.label(text=addon_edition_label(), icon="SOLO_ON")


def _create_status(scene):
    try:
        status = str(scene.get(CREATE_EARTH_STATUS_KEY, "") or "").strip() if scene is not None else ""
        active = bool(scene.get(CREATE_EARTH_STATUS_ACTIVE_KEY, False)) if scene is not None else False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        status = ""
        active = False
    return status, active


def _draw_quality_and_resolve(layout, scene):
    props = getattr(scene, "planetka_public", None) if scene is not None else None
    if props is None:
        layout.label(text="Planetka settings unavailable.", icon="ERROR")
        return

    box = layout.box()
    box.label(text="Quality Level", icon="TEXTURE")
    selected = str(getattr(props, "texture_quality_mode", "PREVIEW") or "PREVIEW").upper()
    row = box.row(align=True)
    for key, label in (("PREVIEW", "Preview"), ("BALANCED", "Balanced"), ("FULL", "Full")):
        op = row.operator("planetka_public.set_texture_quality", text=label, depress=selected == key)
        op.texture_quality_mode = key

    has_earth = _has_earth()
    resolve = box.row()
    resolve.scale_y = 1.3
    if has_earth:
        resolve.operator("planetka_public.resolve_planetka", text="Resolve Planetka", icon="FILE_REFRESH")
    else:
        resolve.operator("planetka_public.add_earth", text="Create New Earth", icon="WORLD_DATA")

    runtime_text, runtime_code, running = _runtime_display(scene)
    create_status, create_active = _create_status(scene)
    if not has_earth and create_status:
        runtime_text = create_status
        running = bool(create_active)
    elif not has_earth:
        runtime_text = "Ready to create Earth"
    elif runtime_code == "DONE":
        runtime_text = "Resolved successfully"
    progress = get_download_progress() or {}
    box.label(text=runtime_text, icon="TIME" if running else "CHECKMARK")
    progress_text, progress_icon = _progress_display(scene, progress)
    box.label(text=progress_text, icon=progress_icon)


def _draw_links(layout):
    box = layout.box()
    box.label(text="Links", icon="URL")
    tutorials = box.operator("planetka_public.open_link", text="Tutorials", icon="PLAY")
    tutorials.link_type = "TUTORIALS"
    resources = box.operator("planetka_public.open_link", text="Resources", icon="VOLUME_DATA")
    resources.link_type = "RESOURCES"


class PLANETKA_PT_PublicMainPanel(bpy.types.Panel):
    bl_label = "Planetka by Tomas Griger"
    bl_idname = "PLANETKA_PT_public_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Planetka"
    bl_order = 0

    def draw(self, context):
        scene = getattr(context, "scene", None)
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        _draw_data_summary(layout)
        _draw_quality_and_resolve(layout, scene)
        _draw_links(layout)


class PLANETKA_PT_PublicAnimationPanel(bpy.types.Panel):
    bl_label = "Planetka Animation"
    bl_idname = "PLANETKA_PT_public_animation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Planetka"
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        del context
        return local_addon_edition_code() == "studio"

    def draw(self, context):
        scene = getattr(context, "scene", None)
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        quick = layout.box()
        quick.label(text="Quick Preview", icon="SHADING_RENDERED")
        row = quick.row(align=True)
        row.enabled = _has_earth()
        row.operator("planetka_public.animation_make_ready", text="Build Quick Preview", icon="SHADING_RENDERED")
        row = quick.row(align=True)
        row.operator("planetka_public.animation_preview_shot", text="Play / Pause", icon="PLAY")
        row.operator("planetka_public.animation_clear_prepared", text="Clear", icon="TRASH")

        final = layout.box()
        final.label(text="Final Animation Render", icon="RENDER_ANIMATION")
        running = is_final_animation_render_active()
        if running:
            runtime_text, _runtime_code, _running = _runtime_display(scene)
            final.label(text=runtime_text, icon="TIME")
        row = final.row()
        row.scale_y = 1.2
        row.enabled = _has_earth()
        if running:
            row.alert = True
            row.operator("planetka_public.animation_stop", text="Stop", icon="CANCEL")
        else:
            row.operator("planetka_public.animation_render", text="Render Animation", icon="RENDER_ANIMATION")
