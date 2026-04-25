import bpy
import importlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Quaternion, Vector

from .auth import (
    allows_balanced_full_quality_for_context,
    is_authenticated,
)
from .planetka_ops.account_ops import (
    PLANETKA_OT_AccountCancelLogin,
    PLANETKA_OT_AccountContact,
    PLANETKA_OT_AccountLogin,
    PLANETKA_OT_AccountLogout,
    PLANETKA_OT_AccountOpenLogin,
    PLANETKA_OT_AccountUpgrade,
    PLANETKA_OT_CheckUpdates,
    PLANETKA_OT_UpdateNow,
)
from .planetka_ops import location_ops as _location_ops
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
    _restore_view_selection,
    _set_default_world_background_to_black,
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
from .planetka_ops.scene_setup_ops import (
    PLANETKA_OT_RemoveDefaultScene,
    PLANETKA_OT_SetBackgroundBlack,
)
from .asset_builder import (
    PLANETKA_ROOT_OBJECT_NAME,
    ensure_planetka_assets,
    ensure_planetka_root,
)
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
    get_download_progress,
    is_download_active,
    is_remote_source_configured,
    texture_file_exists,
)
from .state import (
    ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY,
    _is_render_job_active,
    _initialize_props_from_imported_planetka,
    _sync_idprops_from_props,
    ensure_preview_object,
    ensure_planetka_temp_collection,
    logger,
    remove_object_and_unused_mesh,
    resume_navigation_shot_updates,
    suspend_navigation_shot_updates,
    warm_base_sphere_mesh_cache,
)
from .updater import kickoff_background_update_check

_IMPORT_TEXTURE_EXTENSIONS = {
    "S2": ".exr",
    "EL": ".exr",
    "WT": ".exr",
    "PO": ".tif",
}
_IMPORT_TILE_FILENAME_RE = re.compile(
    r"^(S2|EL|WT|PO)_x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})\.(exr|tif)$",
    re.IGNORECASE,
)
_RECOVERABLE_LOG_COUNTS = {}
_DOWNLOAD_POPUP_WM_FLAG = "planetka_download_popup_running"


def _persist_user_preferences():
    # Planetka must not write Blender's global user preferences automatically.
    return False


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1


def _require_authenticated_account(operator, prefs):
    if not is_authenticated(prefs):
        operator.report({'ERROR'}, "Connect Planetka API key before using remote Earth data.")
        return False
    return True


def _paths_equivalent(path_a, path_b):
    if not path_a or not path_b:
        return False
    try:
        return os.path.samefile(path_a, path_b)
    except (OSError, TypeError, ValueError, AttributeError):
        a = os.path.normcase(os.path.realpath(path_a))
        b = os.path.normcase(os.path.realpath(path_b))
        return a == b


def _canonical_import_filename(texture_type, x_code, y_code, z_code, d_code):
    texture_prefix = str(texture_type).upper()
    ext = _IMPORT_TEXTURE_EXTENSIONS.get(texture_prefix)
    if not ext:
        return None
    return (
        f"{texture_prefix}_x{int(x_code):03d}_y{int(y_code):03d}_z{int(z_code):03d}_d{int(d_code):03d}{ext}"
    )


def _collect_import_sources(source_directory):
    by_canonical_name = {}
    duplicates_skipped = 0

    for root, _dirs, files in os.walk(source_directory):
        for filename in files:
            match = _IMPORT_TILE_FILENAME_RE.match(filename or "")
            if not match:
                continue

            texture_type = str(match.group(1)).upper()
            extension = "." + str(match.group(6)).lower()
            expected_ext = _IMPORT_TEXTURE_EXTENSIONS.get(texture_type)
            if expected_ext != extension:
                continue

            canonical_name = _canonical_import_filename(
                texture_type=texture_type,
                x_code=match.group(2),
                y_code=match.group(3),
                z_code=match.group(4),
                d_code=match.group(5),
            )
            if not canonical_name:
                continue

            source_path = os.path.join(root, filename)
            existing = by_canonical_name.get(canonical_name)
            if existing is None:
                by_canonical_name[canonical_name] = source_path
                continue

            duplicates_skipped += 1
            try:
                existing_mtime = os.path.getmtime(existing)
                current_mtime = os.path.getmtime(source_path)
                if current_mtime > existing_mtime:
                    by_canonical_name[canonical_name] = source_path
            except (OSError, TypeError, ValueError):
                continue

    return by_canonical_name, duplicates_skipped


def _build_texture_import_plan(source_directory, destination_directory):
    sources, duplicates_skipped = _collect_import_sources(source_directory)

    jobs = []
    new_file_count = 0
    update_file_count = 0
    added_size_bytes = 0

    for canonical_name in sorted(sources):
        source_path = sources[canonical_name]
        texture_type = canonical_name.split("_", 1)[0]
        destination_path = os.path.join(destination_directory, texture_type, canonical_name)

        if _paths_equivalent(source_path, destination_path):
            continue

        destination_exists = os.path.isfile(destination_path)
        try:
            file_size = int(os.path.getsize(source_path))
        except (OSError, TypeError, ValueError):
            file_size = 0

        if destination_exists:
            update_file_count += 1
        else:
            new_file_count += 1
            added_size_bytes += max(0, file_size)

        jobs.append({
            "source_path": source_path,
            "destination_path": destination_path,
        })

    return {
        "jobs": jobs,
        "new_file_count": new_file_count,
        "update_file_count": update_file_count,
        "added_size_bytes": max(0, int(added_size_bytes)),
        "duplicates_skipped": int(max(0, duplicates_skipped)),
    }


def _bytes_to_mb(size_bytes):
    return float(max(0, int(size_bytes))) / float(1024 ** 2)


def _prompt_texture_source_selection():
    if bool(getattr(bpy.app, "background", False)):
        return False

    try:
        result = bpy.ops.planetka.select_texture_source('INVOKE_DEFAULT')
        if "RUNNING_MODAL" in result:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-001", "Failed invoking texture-source selector operator")
    except (RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-002", "Failed invoking texture-source selector operator")

    module_name = __package__ or __name__
    try:
        bpy.ops.preferences.addon_show(module=module_name)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    except (RuntimeError, TypeError, ValueError):
        return False


def _persist_user_preferences():
    if bool(getattr(bpy.app, "background", False)):
        return False
    # Planetka must not write Blender's global user preferences automatically.
    return False


def _position_planetka_create_camera(scene, props, camera_obj, activate=False):
    if scene is None or props is None or camera_obj is None:
        return False
    if str(getattr(camera_obj, "type", "")) != "CAMERA":
        return False

    previous_camera = getattr(scene, "camera", None)
    try:
        scene.camera = camera_obj
        _apply_navigation_shot(
            bpy.context,
            scene,
            props,
            switch_viewport_to_camera=False,
            sync_active_view_when_not_camera=False,
        )
        camera_data = getattr(camera_obj, "data", None)
        if camera_data is not None:
            camera_data.lens = max(1.0, float(getattr(props, "nav_focal_length_mm", 50.0)))
    finally:
        if bool(activate):
            try:
                scene.camera = camera_obj
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed activating Planetka Camera", exc_info=True)
        else:
            try:
                scene.camera = previous_camera
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed restoring previously active scene camera", exc_info=True)

    return True


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
    bl_label = "Set Texture Quality"
    bl_description = "Set texture quality mode"

    texture_quality_mode: EnumProperty(
        name="Texture Quality",
        items=(
            (
                "PREVIEW",
                "Preview",
                "Uses 1/4 texture size of Full Quality on each axis (effective 1/16 resolution)",
            ),
            (
                "BALANCED",
                "Balanced",
                "Uses 1/2 texture size of Full Quality on each axis (effective 1/4 resolution)",
            ),
            (
                "FULL",
                "Full Quality",
                "Highest quality texture data (baseline for Preview and Balanced scaling)",
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
            return "Preview: 1/4 texture size on each axis (1/16 of Full Quality resolution)."
        if mode == "BALANCED":
            return "Balanced: 1/2 texture size on each axis (1/4 of Full Quality resolution)."
        return "Full Quality: full-resolution textures."

    def execute(self, context):
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

        target_mode = _normalize_startup_texture_quality_mode(getattr(self, "texture_quality_mode", "PREVIEW"))
        if not allows_balanced_full_quality_for_context(
            prefs=prefs,
            source=props,
            requested_mode=target_mode,
        ):
            if target_mode == "BALANCED":
                return fail(
                    self,
                    "Balanced quality requires Personal or Commercial licence.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            if target_mode == "FULL":
                return fail(
                    self,
                    "Full Quality requires Commercial licence.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            return fail(
                self,
                "Selected texture quality is not available for this account tier.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        try:
            props.texture_quality_mode = target_mode
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed setting texture quality mode via Data Control", exc_info=True)
            return fail(
                self,
                "Unable to set texture quality mode.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        result = bpy.ops.planetka.load_textures(skip_render_compatibility=True, defer_download=True)
        if "FINISHED" not in result:
            return {'CANCELLED'}
        return {'FINISHED'}


class PLANETKA_OT_DownloadStatusPopup(bpy.types.Operator):
    bl_idname = "planetka.download_status_popup"
    bl_label = "Planetka Download"
    bl_description = "Shows active Planetka download progress"
    bl_options = {'INTERNAL'}

    _timer = None

    @classmethod
    def poll(cls, context):
        return context is not None and not bool(getattr(bpy.app, "background", False))

    def _clear_running_flag(self, context):
        wm = getattr(context, "window_manager", None) if context is not None else None
        if wm is None:
            return
        try:
            if _DOWNLOAD_POPUP_WM_FLAG in wm:
                del wm[_DOWNLOAD_POPUP_WM_FLAG]
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-OPS-038", "Failed clearing download popup running flag")

    def _finish(self, context):
        wm = getattr(context, "window_manager", None) if context is not None else None
        if wm is not None and self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-OPS-039", "Failed removing download popup timer")
        self._timer = None
        self._clear_running_flag(context)

    def invoke(self, context, _event):
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return {'CANCELLED'}

        try:
            if bool(wm.get(_DOWNLOAD_POPUP_WM_FLAG, False)):
                return {'CANCELLED'}
            wm[_DOWNLOAD_POPUP_WM_FLAG] = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-OPS-040", "Failed setting download popup running flag")

        if not is_download_active():
            self._clear_running_flag(context)
            return {'CANCELLED'}

        try:
            self._timer = wm.event_timer_add(0.2, window=getattr(context, "window", None))
            wm.modal_handler_add(self)
            return wm.invoke_popup(self, width=280)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            self._finish(context)
            return {'CANCELLED'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if not is_download_active():
            self._finish(context)
            return {'FINISHED'}
        try:
            for window in tuple(getattr(getattr(context, "window_manager", None), "windows", ())):
                screen = getattr(window, "screen", None)
                if screen is None:
                    continue
                for area in tuple(getattr(screen, "areas", ())):
                    if str(getattr(area, "type", "")) in {"VIEW_3D", "PROPERTIES"}:
                        area.tag_redraw()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(context)

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        progress = get_download_progress()
        downloaded_bytes = int(progress.get("downloaded_bytes", 0) or 0)
        total_bytes = int(progress.get("total_bytes", 0) or 0)
        downloaded_mb = float(downloaded_bytes) / (1024.0 * 1024.0)
        total_mb = float(total_bytes) / (1024.0 * 1024.0)

        row = layout.row()
        row.alert = True
        row.label(text="Downloading Planetka data…", icon='IMPORT')
        if total_bytes > 0:
            fraction = max(0.0, min(1.0, float(downloaded_bytes) / float(max(1, total_bytes))))
            if hasattr(layout, "progress"):
                layout.progress(factor=fraction, type='BAR', text=f"{downloaded_mb:.2f} / {total_mb:.2f} MB")
            else:
                layout.label(text=f"{downloaded_mb:.2f} / {total_mb:.2f} MB")
        else:
            if hasattr(layout, "progress"):
                layout.progress(factor=0.0, type='BAR', text=f"{downloaded_mb:.2f} MB")
            else:
                layout.label(text=f"{downloaded_mb:.2f} MB")
        layout.label(text="Window closes automatically when download completes.", icon='INFO')


class PLANETKA_OT_RebuildEarth(bpy.types.Operator):
    bl_idname = "planetka.rebuild_earth"
    bl_label = "Rebuild Earth"
    bl_description = (
        "Emergency rebuild: remove Planetka objects/shaders/runtime data from memory, "
        "preserve camera transform and keyframes, then run Create Earth"
    )

    def execute(self, context):
        return _earth_lifecycle_ops.rebuild_earth_execute(self, context, globals())


class PLANETKA_OT_AddEarth(bpy.types.Operator):
    bl_idname = "planetka.add_earth"
    bl_label = "Create Earth"
    bl_description = "Create Planetka Earth assets and run an initial Resolve"

    def execute(self, context):
        return _earth_lifecycle_ops.add_earth_execute(self, context, globals())


class PLANETKA_OT_SaveStartupSetup(bpy.types.Operator):
    bl_idname = "planetka.save_startup_setup"
    bl_label = "Save Current Setup as Startup Default"
    bl_description = (
        "Save current Planetka setup (Location, Sunlight, Earth Transform, Earth Grading, "
        "Animation, and Settings) and reuse it for Create Earth in new Blender files"
    )

    def execute(self, context):
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
    bl_description = "Apply current Navigation shot values to the Planetka camera rig"
    bl_options = {'INTERNAL'}

    silent: BoolProperty(
        name="Silent",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
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
        return _navigation_ops.navigation_apply_shot_execute(self, context, globals())


class PLANETKA_OT_UseCurrentViewNavigation(bpy.types.Operator):
    bl_idname = "planetka.navigation_use_current_view"
    bl_label = "Bring Camera to View"
    bl_description = "Move active camera to current viewport view and sync Navigation values"

    def execute(self, context):
        return _navigation_ops.use_current_view_navigation_execute(self, context, globals())


class PLANETKA_OT_AutoAdjustClipping(bpy.types.Operator):
    bl_idname = "planetka.auto_adjust_clipping"
    bl_label = "Change Clipping Automatically"
    bl_description = (
        "Automatically adjust Camera/Viewport clipping based on current Earth size and camera proximity"
    )

    def execute(self, context):
        return _navigation_ops.auto_adjust_clipping_execute(self, context, globals())


class PLANETKA_OT_ResetEarthTransform(bpy.types.Operator):
    bl_idname = "planetka.reset_earth_transform"
    bl_label = "Reset Transform"
    bl_description = "Reset Planetka Root Location and Rotation to defaults (0, 0, 0)"

    def execute(self, context):
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
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
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


class PLANETKA_OT_SaveLocation(bpy.types.Operator):
    bl_idname = "planetka.save_location"
    bl_label = "Save Location"
    bl_description = "Save the current Navigation longitude, latitude, and altitude as a reusable location"

    def execute(self, context):
        return _location_ops.save_location_execute(
            self,
            context,
            logger=logger,
            get_prefs=get_prefs,
            require_planetka_props=require_planetka_props,
            read_saved_locations=read_saved_locations,
            write_saved_locations=write_saved_locations,
            fail=fail,
            error_code=ErrorCode,
            persist_user_preferences=_persist_user_preferences,
        )


class PLANETKA_OT_LoadSavedLocation(bpy.types.Operator):
    bl_idname = "planetka.load_saved_location"
    bl_label = "Load Location"
    bl_description = "Load the selected saved location into Navigation fields and move the camera"

    def execute(self, context):
        return _location_ops.load_saved_location_execute(
            self,
            context,
            logger=logger,
            get_prefs=get_prefs,
            require_scene=require_scene,
            require_planetka_props=require_planetka_props,
            read_saved_locations=read_saved_locations,
            suspend_navigation_shot_updates=suspend_navigation_shot_updates,
            resume_navigation_shot_updates=resume_navigation_shot_updates,
            apply_navigation_shot=_apply_navigation_shot,
            fail=fail,
            error_code=ErrorCode,
        )


class PLANETKA_OT_DeleteSavedLocation(bpy.types.Operator):
    bl_idname = "planetka.delete_saved_location"
    bl_label = "Delete Location"
    bl_description = "Delete the selected saved location from Planetka preferences"

    def execute(self, context):
        return _location_ops.delete_saved_location_execute(
            self,
            context,
            logger=logger,
            get_prefs=get_prefs,
            require_planetka_props=require_planetka_props,
            read_saved_locations=read_saved_locations,
            write_saved_locations=write_saved_locations,
            fail=fail,
            error_code=ErrorCode,
            persist_user_preferences=_persist_user_preferences,
        )


class PLANETKA_OT_NavigationPreset(bpy.types.Operator):
    bl_idname = "planetka.navigation_preset"
    bl_label = "Set Navigation Preset"
    bl_description = "Apply a Navigation altitude preset and update camera placement for the current location"

    preset: EnumProperty(
        name="Preset",
        items=(
            ("MAX_PROXIMITY", "Max Proximity", "Closest altitude near texture quality limit (Caution target)"),
            ("ISS_ORBIT", "ISS Orbit", "Set altitude to 400 km"),
            ("SENTINEL2", "ESA Sentinel-2", "Set altitude to 786 km (Sentinel-2 nominal orbit)"),
            ("HIGH_ORBIT", "Full Globe", "Fit full Earth with room around edges"),
        ),
        default="ISS_ORBIT",
    )

    def execute(self, context):
        return _navigation_ops.navigation_preset_execute(self, context, globals())


class PLANETKA_OT_SunlightPreset(bpy.types.Operator):
    bl_idname = "planetka.sunlight_preset"
    bl_label = "Sunlight Preset"
    bl_description = (
        "Set Planetka Sunlight using common lighting presets around the current location "
        "(seasonal tilt is clamped to ±23.5°)"
    )

    preset: EnumProperty(
        name="Preset",
        items=(
            ("DAWN", "Dawn", ""),
            ("SUNRISE", "Sunrise", ""),
            ("EARLY_MORNING", "Early Morning", ""),
            ("SUNSET", "Sunset", ""),
            ("MID_MORNING", "Mid-morning", ""),
            ("MID_AFTERNOON", "Mid-afternoon", ""),
            ("LATE_AFTERNOON", "Late Afternoon", ""),
            ("NOON", "Noon", ""),
            ("DUSK", "Dusk", ""),
            ("NIGHT", "Night", ""),
        ),
        default="NOON",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        return _navigation_ops.sunlight_preset_execute(self, context, globals())
