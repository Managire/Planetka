import bpy

from .auth import (
    CLOUD_OVERLOADED_MESSAGE,
    addon_edition_label,
    ensure_authenticated_session,
    get_cached_cloud_connection_status,
    get_status_message,
    is_authenticated,
    local_addon_edition_code,
)
from .extension_prefs import get_earth_object, get_prefs
from .r2_source import get_download_progress
from .state import get_resolve_runtime_status, is_final_animation_render_active


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
    return text or "Idle", code or "IDLE", False


def _draw_data_summary(layout):
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

    box = layout.box()
    box.label(text="Planetka Data", icon="WORLD")
    row = box.row(align=True)
    row.label(text="Status")
    if online:
        row.label(text="Connected", icon="CHECKMARK")
    elif authenticated and not checked:
        row.label(text="Checking", icon="INFO")
    elif authenticated and overloaded:
        row.label(text="Cloud busy", icon="ERROR")
    elif authenticated:
        row.label(text="Not connected", icon="ERROR")
    else:
        row.label(text="Starting session", icon="INFO")

    row = box.row(align=True)
    row.label(text="Edition")
    row.label(text=addon_edition_label(), icon="SOLO_ON")

    status_message = str(get_status_message(prefs) or "").strip()
    if status_message:
        box.label(text=status_message, icon="INFO")


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
    runtime_text, runtime_code, running = _runtime_display(scene)
    create_status, create_active = _create_status(scene)
    if not has_earth and create_status:
        runtime_text = create_status
        running = bool(create_active)
    progress = get_download_progress() or {}
    box.label(text=runtime_text, icon="TIME" if running else "CHECKMARK")
    if running or bool(progress.get("download_active", False)):
        downloaded = int(progress.get("downloaded_bytes", 0) or 0)
        expected = int(progress.get("expected_bytes", 0) or progress.get("total_bytes", 0) or 0)
        box.label(text=f"Progress: {_fmt_mb(downloaded)} / {_fmt_mb(expected)}", icon="IMPORT")

    resolve = box.row()
    resolve.scale_y = 1.3
    if has_earth:
        resolve.operator("planetka_public.resolve_planetka", text="Resolve Planetka", icon="FILE_REFRESH")
    else:
        resolve.operator("planetka_public.add_earth", text="Create New Earth", icon="WORLD_DATA")


def _draw_links(layout):
    box = layout.box()
    box.label(text="Links", icon="URL")
    box.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.youtube.com/@tomasgriger-planetka/videos"
    box.operator("wm.url_open", text="www.planetka.io", icon="URL").url = "https://www.planetka.io"


def _draw_diagnostics(layout):
    box = layout.box()
    box.label(text="Diagnostics", icon="CHECKMARK")
    box.operator("planetka_public.scene_health_check", text="Scene Health Check", icon="CHECKMARK")


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
        _draw_diagnostics(layout)
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
