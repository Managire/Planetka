import importlib
import os
import time
import re

import bpy
from bpy.props import BoolProperty, EnumProperty

from .asset_builder import ensure_planetka_assets
from .compatibility_utils import ensure_adaptive_subdivision_compat
from .diagnostics import write_resolve_diagnostics, write_tile_view_diagnostics
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_earth_surface_candidates, get_prefs, mark_earth_object
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .sanity_utils import _normalize_texture_source_path
from .state import (
    _apply_fake_atmosphere_from_props,
    _is_animation_playing,
    create_temp_mesh,
    cleanup_planetka_unused_data,
    delete_temp_meshes,
    ensure_preview_object,
    ensure_planetka_temp_collection,
    logger,
    remove_object_and_unused_mesh,
    replace_tiles,
)


_TILE_UTILS_MODULE = None
FORCE_EMPTY_RESOLVE_ONCE_KEY = "planetka_force_empty_resolve_once"
LAST_REQUIRED_MPP_KEY = "planetka_last_required_mpp_m"
ANIMATION_PREPARED_SEGMENTS_KEY = "planetka_anim_prepared_segments"


_TILE_ZD_PATTERN = re.compile(r"_z(\d+)_d(\d+)$")


def _get_tile_utils():
    global _TILE_UTILS_MODULE
    if _TILE_UTILS_MODULE is None:
        module_name = f"{__package__}.tile_utils" if __package__ else "tile_utils"
        try:
            _TILE_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _TILE_UTILS_MODULE = False
    return _TILE_UTILS_MODULE or None


def _validate_texture_source(base_path):
    normalized = _normalize_texture_source_path(base_path)
    if not normalized:
        return "", "Texture source directory is missing or invalid."
    if not os.path.isdir(normalized):
        return "", f"Texture source directory is not a valid path: {normalized}"

    s2_dir = os.path.join(normalized, "S2")
    if not os.path.isdir(s2_dir):
        return "", "Texture source is invalid: missing required folder 'S2'."

    # Quick sanity for speed: one matching S2 file is enough for Resolve precheck.
    try:
        has_s2 = any(
            name.startswith("S2_") and name.lower().endswith(".exr")
            for name in os.listdir(s2_dir)
            if os.path.isfile(os.path.join(s2_dir, name))
        )
    except (OSError, TypeError, ValueError):
        has_s2 = False
    if not has_s2:
        return "", "Texture source is invalid: no 'S2_*.exr' files found in 'S2'."

    return normalized, ""


def _tile_d_value(tile):
    if not tile:
        return None
    text = str(tile)
    match = _TILE_ZD_PATTERN.search(text)
    if not match:
        return None
    try:
        z = int(match.group(1))
        d_code = int(match.group(2))
        if z == 360 and d_code == 0:
            return 1440
        return d_code
    except (TypeError, ValueError):
        return None


def _resolve_safety(required_mpp, resolved_tiles):
    if not resolved_tiles:
        return "OK"

    if required_mpp is None:
        return "OK"
    try:
        required_mpp_value = float(required_mpp)
    except (TypeError, ValueError):
        return None
    if required_mpp_value <= 0.0:
        return None

    d_values = []
    for tile in resolved_tiles or ():
        d_value = _tile_d_value(tile)
        if d_value is not None and d_value > 0:
            d_values.append(int(d_value))
    if not d_values:
        return "WARNING"

    best_available_mpp = min(d_values) * 10.0
    ratio = best_available_mpp / required_mpp_value
    if ratio <= 1.0:
        return "OK"
    if ratio <= 1.15:
        return "CAUTION"
    return "WARNING"


class PLANETKA_OT_LoadTextures(bpy.types.Operator):
    bl_idname = "planetka.load_textures"
    bl_label = "Resolve Earth"
    bl_description = "Resolve visible Earth tiles and rebuild the Planetka surface mesh/material assignment"

    scope_mode: EnumProperty(
        name="Scope Mode",
        items=(
            ("AUTO", "Auto", ""),
            ("CAMERA", "Camera", ""),
            ("ACTIVE_VIEW", "Active View", ""),
        ),
        default="AUTO",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    silent: BoolProperty(
        name="Silent",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        resolve_start = time.perf_counter()
        phase_assets_ms = 0.0
        phase_tile_select_ms = 0.0
        phase_mesh_ms = 0.0
        phase_shader_ms = 0.0
        phase_post_ms = 0.0
        phase_post_delete_ms = 0.0
        phase_post_mark_ms = 0.0
        phase_post_preview_ms = 0.0
        phase_unaccounted_ms = 0.0

        phase_start = time.perf_counter()
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        try:
            prepared_segments = int(scene.get(ANIMATION_PREPARED_SEGMENTS_KEY, 0))
        except (TypeError, ValueError):
            prepared_segments = 0
        if prepared_segments > 0:
            return fail(
                self,
                "Animation is prepared for render. Use Clear Prepared before resolving/navigating again.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        if bool(getattr(props, "lock_resolve_during_animation", True)) and _is_animation_playing():
            self.report({'WARNING'}, "Resolve skipped during animation playback (disabled in Settings).")
            return {'CANCELLED'}

        try:
            ensure_planetka_assets(scene)
            compat_info = ensure_adaptive_subdivision_compat(scene, return_details=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Resolve precheck failed while rebuilding Planetka assets: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka Resolve asset rebuild failed",
            )
        if isinstance(compat_info, dict) and bool(compat_info.get("viewport_dicing_adjusted", False)):
            self.report(
                {'INFO'},
                "Planetka set Cycles Viewport Dicing Rate to 2.0 for better surface quality.",
            )
        phase_assets_ms = (time.perf_counter() - phase_start) * 1000.0

        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        normalized = _normalize_texture_source_path(getattr(prefs, "texture_base_path", ""))
        normalized, issue = _validate_texture_source(normalized)
        if issue:
            return fail(
                self,
                issue,
                code=ErrorCode.RESOLVE_PATH_INVALID,
                logger=logger,
            )
        prefs.texture_base_path = normalized
        phase_assets_ms = (time.perf_counter() - phase_start) * 1000.0

        try:
            force_empty_once = bool(scene.get(FORCE_EMPTY_RESOLVE_ONCE_KEY, False))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            force_empty_once = False
        if force_empty_once:
            try:
                if FORCE_EMPTY_RESOLVE_ONCE_KEY in scene:
                    del scene[FORCE_EMPTY_RESOLVE_ONCE_KEY]
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed clearing one-shot empty resolve flag", exc_info=True)

        earth_surface = get_earth_object()
        if earth_surface is None:
            candidates = get_earth_surface_candidates()
            if len(candidates) > 1:
                candidate_names = ", ".join(sorted(obj.name for obj in candidates[:5]))
                if len(candidates) > 5:
                    candidate_names = f"{candidate_names}, ..."
                return fail(
                    self,
                    (
                        "Resolve requires one unambiguous Earth surface object. "
                        f"Found {len(candidates)} candidates: {candidate_names}. "
                        "Keep one Planetka Earth surface and retry."
                    ),
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            return fail(
                self,
                "Resolve requires an existing Planetka Earth surface. Run Create Earth first.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        tile_utils = _get_tile_utils()
        if tile_utils is None:
            return fail(
                self,
                "Resolve failed because tile utilities are unavailable.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        phase_start = time.perf_counter()
        try:
            computed_tiles = tile_utils.main(
                scope_mode=str(getattr(self, "scope_mode", "AUTO") or "AUTO"),
            )
            tiles = [] if force_empty_once else computed_tiles
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.exception("Planetka tile resolve failed; resolving to no visible tiles")
            tiles = []
            self.report({'WARNING'}, "Tile detection failed; resolving to no visible tiles.")
        except RuntimeError as exc:
            try:
                if LAST_REQUIRED_MPP_KEY in scene:
                    del scene[LAST_REQUIRED_MPP_KEY]
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed clearing required-mpp key after tile resolve runtime failure", exc_info=True)
            write_tile_view_diagnostics(
                scene=scene,
                camera_altitude_bu=None,
                nearest_visible_distance_bu=None,
                earth_radius_bu=None,
            )
            logger.debug("Planetka tile resolve runtime failure: %s", exc, exc_info=True)
            tiles = []
            self.report({'WARNING'}, "No active camera/view found; resolving to no visible tiles.")
        phase_tile_select_ms = (time.perf_counter() - phase_start) * 1000.0

        try:
            scene["planetka_last_resolved_tiles"] = list(tiles)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed caching resolved tiles", exc_info=True)

        ensure_planetka_temp_collection()
        new_obj = None
        try:
            phase_start = time.perf_counter()
            new_obj = create_temp_mesh(
                tiles,
                name="Planetka Earth Surface (New)",
                collection_policy="inherit_old",
            )
            if not new_obj:
                raise RuntimeError("Failed to create new Earth surface mesh")
            phase_mesh_ms = (time.perf_counter() - phase_start) * 1000.0

            phase_start = time.perf_counter()
            shader_result = replace_tiles(tiles, force_remove_unused=True) or {}
            phase_shader_ms = (time.perf_counter() - phase_start) * 1000.0
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            if new_obj:
                remove_object_and_unused_mesh(new_obj)
            return fail(
                self,
                f"Planetka resolve failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka resolve failed",
            )

        phase_start = time.perf_counter()
        delete_temp_meshes(keep_obj=new_obj)
        phase_post_delete_ms = (time.perf_counter() - phase_start) * 1000.0

        phase_start = time.perf_counter()
        try:
            new_obj.name = "Planetka Earth Surface"
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed renaming resolved Earth surface object", exc_info=True)
        mark_earth_object(new_obj)
        # Resolve replaces the Earth object; re-apply atmosphere so shell scale
        # matches the freshly resolved surface immediately.
        try:
            _apply_fake_atmosphere_from_props(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed reapplying atmosphere after resolve", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed reapplying atmosphere after resolve", exc_info=True)
        phase_post_mark_ms = (time.perf_counter() - phase_start) * 1000.0

        if not force_empty_once and bool(getattr(props, "show_earth_preview", False)):
            phase_start = time.perf_counter()
            try:
                ensure_preview_object(new_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed refreshing preview object", exc_info=True)
                self.report({'WARNING'}, "Planetka preview object refresh failed.")
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed refreshing preview object", exc_info=True)
                self.report({'WARNING'}, "Planetka preview object refresh failed.")
            phase_post_preview_ms = (time.perf_counter() - phase_start) * 1000.0

        phase_post_ms = phase_post_delete_ms + phase_post_mark_ms + phase_post_preview_ms

        if not bool(getattr(self, "silent", False)) and not (force_empty_once and len(tiles) == 0):
            self.report({'INFO'}, f"Planetka resolved ({len(tiles)} tiles)")
        resolve_total_ms = (time.perf_counter() - resolve_start) * 1000.0
        measured_sum_ms = phase_assets_ms + phase_tile_select_ms + phase_mesh_ms + phase_shader_ms + phase_post_ms
        if measured_sum_ms < resolve_total_ms:
            phase_unaccounted_ms = resolve_total_ms - measured_sum_ms
        fallback_count = int(shader_result.get("missing_texture_count", 0)) + int(
            shader_result.get("higher_z_fallback_count", 0)
        )
        loaded_texture_bytes = 0
        if isinstance(shader_result, dict):
            try:
                loaded_texture_bytes = int(shader_result.get("loaded_texture_bytes", 0) or 0)
            except (TypeError, ValueError):
                loaded_texture_bytes = 0
        loaded_textures_mb = float(loaded_texture_bytes) / (1024.0 * 1024.0)
        try:
            required_mpp = scene.get(LAST_REQUIRED_MPP_KEY)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            required_mpp = None
        resolved_tiles = shader_result.get("resolved_tiles", []) if isinstance(shader_result, dict) else []
        resolution_safety = _resolve_safety(required_mpp, resolved_tiles)
        try:
            scope_used = str(scene.get("planetka_last_scope_used", "CAMERA"))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            scope_used = "CAMERA"
        if (
            scope_used == "ACTIVE_VIEW"
            and bool(getattr(props, "viewport_opt_active_view_coarse_textures", True))
            and str(resolution_safety) == "WARNING"
        ):
            resolution_safety = "CAUTION"
        write_resolve_diagnostics(
            scene=scene,
            tile_count=len(tiles),
            resolve_ms=resolve_total_ms,
            fallback_count=fallback_count,
            breakdown={
                "assets_ms": phase_assets_ms,
                "tile_select_ms": phase_tile_select_ms,
                "mesh_ms": phase_mesh_ms,
                "shader_ms": phase_shader_ms,
                "post_ms": phase_post_ms,
                "post_delete_ms": phase_post_delete_ms,
                "post_mark_ms": phase_post_mark_ms,
                "post_preview_ms": phase_post_preview_ms,
                "unaccounted_ms": phase_unaccounted_ms,
                "required_mpp_m": required_mpp,
                "resolution_safety": resolution_safety,
                "loaded_textures_mb": loaded_textures_mb,
            },
        )
        return {'FINISHED'}


class PLANETKA_OT_CleanupUnusedData(bpy.types.Operator):
    bl_idname = "planetka.cleanup_unused_data"
    bl_label = "Cleanup Unused Planetka Data"
    bl_description = "Remove stale Planetka objects and unused Planetka meshes, images, materials, and node groups"

    def execute(self, context):
        try:
            counts = cleanup_planetka_unused_data()
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Cleanup failed: {exc}",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka cleanup failed",
            )

        self.report(
            {'INFO'},
            (
                "Cleanup complete: "
                f"{counts.get('objects', 0)} objects, "
                f"{counts.get('meshes', 0)} meshes, "
                f"{counts.get('images', 0)} images, "
                f"{counts.get('materials', 0)} materials, "
                f"{counts.get('node_groups', 0)} node groups removed."
            ),
        )
        return {'FINISHED'}
