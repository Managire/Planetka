import json
import textwrap
import time

import bpy
from bpy.props import BoolProperty, EnumProperty

from .planetka_ops.update_ops import (
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_UpdateNow,
)
from .planetka_ops.location_ops import (
    PLANETKA_OT_DeleteSavedLocation,
    PLANETKA_OT_LoadSavedLocation,
    PLANETKA_OT_SaveLocation,
)
from .planetka_ops.startup_profile_ops import (
    _SURFACE_GRADING_SECTION_SOCKET_NAMES,
    _apply_startup_setup_for_create_earth,
    _apply_startup_setup_profile,
    _apply_surface_grading_values,
    _build_factory_startup_setup_profile,
    _iter_surface_grading_input_sockets,
    _iter_surface_grading_nodes,
    _normalize_startup_texture_quality_mode,
    _serialize_current_startup_setup_profile,
    _serialize_surface_grading_values,
    _store_startup_setup_profile,
    _surface_grading_factory_values,
)
from .planetka_ops.earth_lifecycle_helpers import (
    _DEFAULT_SCENE_REMOVED_KEY,
    _PLANETKA_CREATE_CAMERA_NAME,
    _REBUILD_EXCEPTIONS,
    _SKIP_ATMOSPHERE_CLOUD_SETUP_ON_CREATE_EARTH_KEY,
    _SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY,
    _apply_create_earth_clipping_defaults,
    _apply_radius_based_clipping,
    _earth_graph_cleanup_for_rebuild,
    _earth_graph_create_bootstrap_surface,
    _earth_graph_rebind,
    _earth_graph_restore_after_rebuild,
    _ensure_close_clip_limits,
    _ensure_planetka_create_camera,
    _is_planetka_create_camera,
    _pick_scene_camera,
    _position_planetka_create_camera,
    _require_planetka_cloud_session,
    _restore_view_selection,
    _snapshot_camera_state_for_rebuild,
    _snapshot_earth_settings_for_rebuild,
    _snapshot_view_selection,
    _validate_create_earth_texture_source,
)
from .planetka_ops.import_export_ops import (
    PLANETKA_OT_ConfirmImportNewData,
    PLANETKA_OT_CreateStandaloneFile,
    PLANETKA_OT_ImportNewData,
    PLANETKA_OT_SelectTextureSource,
)
from .planetka_ops import earth_lifecycle_ops as _earth_lifecycle_ops
from .planetka_ops import navigation_ops as _navigation_ops
from .planetka_ops.navigation_ops import (
    PLANETKA_OT_NavigationPreset,
    PLANETKA_OT_SunlightPreset,
)
from .planetka_ops.scene_setup_ops import (
    PLANETKA_OT_OptimizeRenderSettings,
    PLANETKA_OT_RemoveDefaultScene,
    PLANETKA_OT_SetBackgroundBlack,
)
from .asset_builder import (
    PLANETKA_ROOT_OBJECT_NAME,
    ensure_atmosphere_for_mode,
    ensure_planetka_assets,
    ensure_planetka_root,
)
from .clouds_global import ensure_global_cloud_layer
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import (
    get_earth_object,
    get_prefs,
    read_saved_locations,
    write_saved_locations,
)
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .sanity_utils import (
    _normalize_texture_source_path,
    invalidate_texture_source_health_cache,
)
from .r2_source import (
    is_remote_source_configured,
    texture_file_exists,
)

def _format_bytes_for_ui(size_bytes):
    try:
        value = float(size_bytes or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value >= 1024.0 ** 3:
        return f"{value / (1024.0 ** 3):,.2f} GB"
    return f"{value / (1024.0 ** 2):,.2f} MB"


def _format_pack_data_size_for_ui(size_bytes):
    try:
        value = max(0.0, float(size_bytes or 0))
    except (TypeError, ValueError):
        value = 0.0
    mb = value / 1_000_000.0
    if mb < 1000.0:
        return f"{mb:,.2f} MB"
    gb = value / 1_000_000_000.0
    if gb < 1000.0:
        return f"{gb:,.2f} GB"
    return f"{value / 1_000_000_000_000.0:,.2f} TB"


def _format_int_for_ui(value):
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def _format_eur_for_ui(value):
    try:
        return f"€{max(0.0, float(value or 0.0)):,.2f}"
    except (TypeError, ValueError):
        return "€0.00"


def _wrapped_label(layout, text, icon='NONE', width=58):
    safe_text = str(text or "").strip()
    if not safe_text:
        return
    lines = textwrap.wrap(safe_text, width=max(20, int(width or 58))) or [safe_text]
    for index, line in enumerate(lines):
        layout.label(text=line, icon=icon if index == 0 else 'BLANK1')


from .state import (
    _is_render_job_active,
    _tag_view3d_redraw,
    _initialize_props_from_imported_planetka,
    _sync_idprops_from_props,
    ensure_preview_object,
    ensure_planetka_temp_collection,
    logger,
    remove_object_and_unused_mesh,
    resume_navigation_shot_updates,
    suspend_navigation_shot_updates,
    update_resolve_size_estimates,
    warm_base_sphere_mesh_cache,
)
from .updater import kickoff_background_update_check

_RECOVERABLE_LOG_COUNTS = {}
_LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY = "planetka_last_resolve_texture_quality_mode"


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1


def _persist_user_preferences():
    if bool(getattr(bpy.app, "background", False)):
        return False
    # Planetka must not write Blender's global user preferences automatically.
    return False


def _cancel_if_animation_render_active(operator, action_label="This action"):
    try:
        if callable(_is_render_job_active) and bool(_is_render_job_active()):
            label = str(action_label or "This action").strip() or "This action"
            operator.report(
                {'WARNING'},
                f"{label} is unavailable while Final Animation Render is running.",
            )
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return False


from .planetka_ops.navigation_helpers import (
    _anchor_distance_from_altitude_and_tilt,
    _anchor_frame_world,
    _apply_navigation_shot,
    _best_available_d_for_tile,
    _bu_to_km,
    _camera_projection_info,
    _camera_to_current_view,
    _compute_current_view_navigation_values,
    _compute_scene_camera_navigation_values,
    _derive_navigation_shot_from_camera,
    _earth_radius_blender_units,
    _ensure_ortho_full_globe_if_needed,
    _ensure_shot_anchor_object,
    _find_active_view3d_context,
    _find_active_view3d_context_details,
    _finest_available_d_for_location,
    _full_globe_altitude_km,
    _get_coverage_map,
    _hide_shot_anchor_in_viewport,
    _is_scene_camera_below_surface,
    _km_to_bu,
    _lon_lat_normal_local,
    _look_rotation_quaternion,
    _max_proximity_altitude_km,
    _meters_per_blender_unit,
    _navigate_camera_internal,
    _populate_navigation_from_scene_camera,
    _quantize_navigation_ui_payload,
    _quantize_navigation_ui_value,
    _ray_sphere_hit_nearest,
    _read_full_globe_tilt_lock,
    _read_last_navigation_values,
    _scene_camera_altitude_bu,
    _set_planetka_earth_radius_bu,
    _signed_angle_around_axis,
    _store_last_navigation_values,
    _switch_viewport_to_camera_view,
    _sync_active_view_to_scene_camera,
    _tile_xy_for_lon_lat,
    _update_shot_anchor_object,
)


class PLANETKA_OT_SetTextureQualityAndResolve(bpy.types.Operator):
    bl_idname = "planetka.set_texture_quality_and_resolve"
    bl_label = "Set Quality Level"
    bl_description = "Set Planetka Quality Level. Press Resolve Planetka to apply it."

    texture_quality_mode: EnumProperty(
        name="Quality Level",
        items=(
            (
                "PREVIEW",
                "Preview",
                "Uses two higher d-levels than Full Quality (effective 1/16 resolution); fastest download with lowest memory and recalculation cost",
            ),
            (
                "BALANCED",
                "Balanced",
                "Uses 1/2 width x 1/2 height of Full Quality textures (effective 1/4 resolution)",
            ),
            (
                "FULL",
                "Full Quality",
                "Highest quality texture data",
            ),
        ),
        default="PREVIEW",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    @classmethod
    def description(cls, _context, properties):
        mode = _normalize_startup_texture_quality_mode(
            getattr(properties, "texture_quality_mode", "PREVIEW")
        )
        if mode == "PREVIEW":
            return "Uses two higher d-levels than Full Quality (effective 1/16 resolution); fastest download with lowest memory and recalculation cost"
        if mode == "BALANCED":
            return "Uses 1/2 width x 1/2 height of Full Quality textures (effective 1/4 resolution)"
        return "Highest quality texture data"

    def invoke(self, context, event):
        del event
        target_mode = _normalize_startup_texture_quality_mode(getattr(self, "texture_quality_mode", "PREVIEW"))
        return self.execute(context)

    def draw(self, _context):
        return

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Texture quality change"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        target_mode = _normalize_startup_texture_quality_mode(getattr(self, "texture_quality_mode", "PREVIEW"))
        try:
            previous_mode = _normalize_startup_texture_quality_mode(
                getattr(props, "texture_quality_mode", "PREVIEW")
            )
            if previous_mode != target_mode:
                props.texture_quality_mode = target_mode
            _tag_view3d_redraw()
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                "Texture quality could not be changed. Please retry.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka texture quality selection failed",
            )

        return {'FINISHED'}


class PLANETKA_OT_ResolvePlanetka(bpy.types.Operator):
    bl_idname = "planetka.resolve_planetka"
    bl_label = "Resolve Planetka"
    bl_description = (
        "Manually resolve Planetka for the current camera: calculate required Earth surface tiles, "
        "download/apply the selected Quality Level, and optimize texture-based and VDB cloud LODs"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Resolve Planetka"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        quality_mode = _normalize_startup_texture_quality_mode(
            getattr(props, "texture_quality_mode", "PREVIEW")
        )
        try:
            result = bpy.ops.planetka.load_textures(
                scope_mode="CAMERA",
                skip_render_compatibility=True,
                defer_download=True,
                tiles_override_json="",
                texture_quality_mode_override=quality_mode,
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                "Resolve Planetka failed. Please retry.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Resolve Planetka failed",
            )
        except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
            return fail(
                self,
                f"Resolve Planetka failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )
        if "FINISHED" not in result:
            return fail(
                self,
                "Resolve Planetka could not start. Please retry.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )
        _tag_view3d_redraw()
        return {'FINISHED'}


class PLANETKA_OT_RebuildEarth(bpy.types.Operator):
    bl_idname = "planetka.rebuild_earth"
    bl_label = "Rebuild Earth"
    bl_description = (
        "Emergency rebuild: remove Planetka objects/shaders/runtime data from memory, "
        "preserve camera transform and keyframes, then run Create Earth"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Rebuild Earth"):
            return {'CANCELLED'}
        return _earth_lifecycle_ops.rebuild_earth_execute(self, context, globals())


class PLANETKA_OT_AddEarth(bpy.types.Operator):
    bl_idname = "planetka.add_earth"
    bl_label = "Create Earth"
    bl_description = "Create Planetka Earth assets"

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Create Earth"):
            return {'CANCELLED'}
        return _earth_lifecycle_ops.add_earth_execute(self, context, globals())


class PLANETKA_OT_SaveStartupSetup(bpy.types.Operator):
    bl_idname = "planetka.save_startup_setup"
    bl_label = "Save Current Setup as Startup Default"
    bl_description = (
        "Save current Planetka setup (Location, Sunlight, Earth Transform, Earth Grading, "
        "Animation, and Settings) and reuse it for Create Earth in new Blender files"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Save startup setup"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        if get_earth_object() is None:
            return fail(self, "Create Earth first, then save startup setup defaults.", logger=logger)
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        profile = _serialize_current_startup_setup_profile(scene, props)
        if not _store_startup_setup_profile(prefs, profile):
            return fail(self, "Failed to save startup setup defaults.", logger=logger)
        if not _persist_user_preferences():
            self.report({'WARNING'}, "Startup setup saved for this session only. Use Blender Save Preferences to persist it.")
        else:
            self.report({'INFO'}, "Startup setup saved. New Create Earth actions will reuse this setup.")
        return {'FINISHED'}


class PLANETKA_OT_ResetStartupSetupFactory(bpy.types.Operator):
    bl_idname = "planetka.reset_startup_setup_factory"
    bl_label = "Reset Startup Setup"
    bl_description = (
        "Clear custom startup setup and restore Planetka factory startup values "
        "(Location, Sunlight, Earth Transform, Earth Grading, Animation, and Settings)"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Reset startup setup"):
            return {'CANCELLED'}
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        if not _store_startup_setup_profile(prefs, None):
            return fail(self, "Failed to clear custom startup setup.", logger=logger)
        if not _persist_user_preferences():
            self.report({'WARNING'}, "Startup setup reset for this session only. Use Blender Save Preferences to persist it.")

        factory_profile = _build_factory_startup_setup_profile(scene, props)
        _apply_startup_setup_profile(scene, props, factory_profile, apply_navigation_shot=False)
        if _persist_user_preferences():
            self.report({'INFO'}, "Startup setup reset to factory defaults.")
        return {'FINISHED'}


class PLANETKA_OT_NavigationApplyShot(bpy.types.Operator):
    bl_idname = "planetka.navigation_apply_shot"
    bl_label = "Apply Navigation Shot"
    bl_description = "Apply current Navigation shot values to the active scene camera"
    bl_options = {'INTERNAL'}

    force_camera_view: BoolProperty(
        name="Force Camera View",
        default=True,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    sync_active_view_when_not_camera: BoolProperty(
        name="Sync Active View",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Navigation apply"):
            return {'CANCELLED'}
        return _navigation_ops.navigation_apply_shot_execute(self, context, globals())


class PLANETKA_OT_UseCurrentViewNavigation(bpy.types.Operator):
    bl_idname = "planetka.navigation_use_current_view"
    bl_label = "Bring Camera to View"
    bl_description = "Move active camera to current viewport view and sync Navigation values"

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Bring Camera to View"):
            return {'CANCELLED'}
        return _navigation_ops.use_current_view_navigation_execute(self, context, globals())


class PLANETKA_OT_AutoAdjustClipping(bpy.types.Operator):
    bl_idname = "planetka.auto_adjust_clipping"
    bl_label = "Change Clipping Automatically"
    bl_description = (
        "Automatically adjust Camera/Viewport clipping based on current Earth size and camera proximity"
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Clipping adjustment"):
            return {'CANCELLED'}
        return _navigation_ops.auto_adjust_clipping_execute(self, context, globals())


class PLANETKA_OT_ResetEarthTransform(bpy.types.Operator):
    bl_idname = "planetka.reset_earth_transform"
    bl_label = "Reset Transform"
    bl_description = "Reset Planetka Root Location and Rotation to defaults (0, 0, 0)"

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Reset transform"):
            return {'CANCELLED'}
        return _earth_lifecycle_ops.reset_earth_transform_execute(self, context, globals())


class PLANETKA_OT_ResetSurfaceGradingSection(bpy.types.Operator):
    bl_idname = "planetka.reset_surface_grading_section"
    bl_label = "Reset Surface Grading Section"
    bl_description = "Reset one Surface Grading section to Planetka defaults"

    section: EnumProperty(
        name="Section",
        items=(
            ("GLOBAL", "Global", "Reset Global section values"),
            ("WATER", "Water", "Reset Water section values"),
            ("ELEVATION", "Elevation", "Reset Elevation section values"),
            ("NIGHT", "Night", "Reset Night section values"),
        ),
        default="GLOBAL",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        if _cancel_if_animation_render_active(self, "Surface grading reset"):
            return {'CANCELLED'}
        _ = context
        nodes = tuple(_iter_surface_grading_nodes())
        if not nodes:
            return fail(
                self,
                "Earth Surface Grading node group not found.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        section_key = str(getattr(self, "section", "GLOBAL") or "GLOBAL").strip().upper()
        section_socket_names = _SURFACE_GRADING_SECTION_SOCKET_NAMES.get(section_key, set())
        if not section_socket_names:
            return fail(
                self,
                f"Unknown Surface Grading section: {section_key}",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        defaults_by_name = {}
        for key, value in _surface_grading_factory_values().items():
            normalized = str(key or "").strip().lower()
            if normalized:
                defaults_by_name[normalized] = value

        reset_count = 0
        touched_count = 0
        for node in nodes:
            for socket in _iter_surface_grading_input_sockets(node):
                socket_name_raw = str(getattr(socket, "name", "") or "").strip()
                socket_name = socket_name_raw.lower()
                if socket_name not in section_socket_names:
                    continue
                touched_count += 1
                if socket_name not in defaults_by_name:
                    continue
                target_value = defaults_by_name.get(socket_name)
                try:
                    if isinstance(target_value, (list, tuple)):
                        socket.default_value = tuple(target_value)
                    else:
                        socket.default_value = target_value
                    reset_count += 1
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug(
                        "Planetka: failed resetting surface grading socket '%s' in section '%s'",
                        socket_name_raw,
                        section_key,
                        exc_info=True,
                    )

        if touched_count <= 0:
            return fail(
                self,
                f"No sockets found for Surface Grading section '{section_key.title()}'.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        self.report({'INFO'}, f"Surface Grading '{section_key.title()}' reset ({reset_count}/{touched_count} values).")
        return {'FINISHED'}
