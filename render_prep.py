"""Resolve operator pipeline.

This module executes the Earth resolve flow:
1) validate scene/prefs
2) compute visible tiles
3) fetch/prepare tile data
4) rebuild mesh + shader assignments
5) write diagnostics/telemetry
"""

import importlib
import json
import os
import time
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from .auth import get_login_state, is_authenticated, sync_account_profile
from .asset_builder import ensure_planetka_assets
from .compatibility_utils import ensure_adaptive_subdivision_compat
from .diagnostics import write_resolve_diagnostics, write_tile_view_diagnostics
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_earth_surface_candidates, get_prefs, mark_earth_object
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .r2_source import (
    is_remote_source_configured,
    texture_file_exists,
    verify_remote_stream_health,
)
from .sanity_utils import _normalize_texture_source_path
from .streaming_utils import (
    consume_staged_prefetch_payload,
    prepare_resolve_streaming_for_visible_tiles,
)
from .state import (
    _is_animation_playing,
    create_temp_mesh,
    cleanup_planetka_unused_data,
    delete_temp_meshes,
    ensure_preview_object,
    ensure_planetka_temp_collection,
    logger,
    queue_resolve_download,
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
    if not is_remote_source_configured(normalized):
        return "", "Planetka Cloudflare source is not configured."

    # Quick sanity for speed: one matching S2 file is enough for Resolve precheck.
    try:
        has_s2 = texture_file_exists(normalized, "S2", "S2_x180_y000_z180_d180.exr") or texture_file_exists(
            normalized,
            "S2",
            "S2_x000_y000_z180_d180.exr",
        )
    except RuntimeError as exc:
        return "", str(exc)
    if not has_s2:
        return "", "Planetka Cloudflare source is reachable but required S2 sentinel tiles are missing."

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


def _parse_tiles_override(raw_json):
    text = str(raw_json or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, (list, tuple)):
        return None
    return [str(tile) for tile in payload if str(tile or "").strip()]


def _count_missing_tile_loading_images(material_name="Planetka Earth Material"):
    material = bpy.data.materials.get(str(material_name or ""))
    if material is None or not bool(getattr(material, "use_nodes", False)):
        return 0
    node_tree = getattr(material, "node_tree", None)
    nodes = getattr(node_tree, "nodes", None) if node_tree else None
    if nodes is None:
        return 0

    loading_group = nodes.get("Planetka Textures Loading")
    group_tree = getattr(loading_group, "node_tree", None) if loading_group else None
    group_nodes = getattr(group_tree, "nodes", None) if group_tree else None
    if group_nodes is None:
        return 0

    missing = 0
    for node in group_nodes:
        if str(getattr(node, "type", "")) != "GROUP":
            continue
        node_name = str(getattr(node, "name", "") or "")
        if not node_name.startswith(("Tile_", "Planetka Tile_")):
            continue
        if bool(getattr(node, "mute", False)):
            continue
        tile_tree = getattr(node, "node_tree", None)
        tile_nodes = getattr(tile_tree, "nodes", None) if tile_tree else None
        if tile_nodes is None:
            continue
        for image_type in ("S2", "EL", "WT", "PO"):
            image_node = tile_nodes.get(image_type)
            if image_node is None:
                continue
            image = getattr(image_node, "image", None)
            if image is None:
                missing += 1
                continue
            image_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", ""))
            if not image_path:
                missing += 1
                continue
            abs_path = bpy.path.abspath(image_path)
            if abs_path and not os.path.isfile(abs_path):
                missing += 1
    return int(missing)


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

    skip_render_compatibility: BoolProperty(
        name="Skip Render Compatibility",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    defer_download: BoolProperty(
        name="Defer Download",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    tiles_override_json: StringProperty(
        name="Tiles Override",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    repair_retry_depth: IntProperty(
        name="Repair Retry Depth",
        default=0,
        min=0,
        max=4,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        resolve_start = time.perf_counter()
        phase_assets_ms = 0.0
        phase_tile_select_ms = 0.0
        phase_stream_ms = 0.0
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
            compat_info = {}
            if not bool(getattr(self, "skip_render_compatibility", False)):
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
        if (
            not bool(getattr(self, "skip_render_compatibility", False))
            and isinstance(compat_info, dict)
            and bool(compat_info.get("viewport_dicing_adjusted", False))
        ):
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
        if is_remote_source_configured(normalized):
            if get_login_state(prefs) == "pending":
                return fail(
                    self,
                    "Finish Planetka login in your browser before resolving Earth data.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            if not is_authenticated(prefs):
                return fail(
                    self,
                    "Log in to Planetka before resolving remote Earth data.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                )
            stream_ok, stream_issue = verify_remote_stream_health(force=False)
            if not stream_ok:
                return fail(
                    self,
                    stream_issue or "Planetka remote tile stream check failed.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
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

        tiles_override = _parse_tiles_override(getattr(self, "tiles_override_json", ""))
        phase_start = time.perf_counter()
        if tiles_override is not None:
            tiles = [] if force_empty_once else list(tiles_override)
        else:
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

        if bool(getattr(self, "defer_download", False)):
            queued = queue_resolve_download(
                scene,
                [str(tile) for tile in (tiles or ()) if str(tile or "").strip()],
                manual_request=True,
            )
            if not queued:
                return fail(
                    self,
                    "Planetka could not queue resolve download.",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )
            self.report({'INFO'}, "Planetka resolve queued. Downloading data in background.")
            return {'FINISHED'}

        resolved_paths = {}
        resolved_tiles_override = None
        ocean_tiles_override = None
        download_capture = {
            "downloaded_bytes": 0,
            "download_ms": 0.0,
        }
        phase_start = time.perf_counter()
        try:
            stream_payload = consume_staged_prefetch_payload(tiles, normalized)
            if not isinstance(stream_payload, dict):
                stream_payload = prepare_resolve_streaming_for_visible_tiles(
                    tiles,
                    normalized,
                    capture=True,
                )
            if bool(stream_payload.get("cancelled", False)):
                return fail(
                    self,
                    "Planetka resolve download was cancelled.",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )
            resolved_paths = dict(stream_payload.get("resolved_paths", {}) or {})
            resolved_tiles_override = list(stream_payload.get("resolved_tiles", ()) or ())
            ocean_tiles_override = set(stream_payload.get("ocean_tiles", ()) or ())
            capture_payload = stream_payload.get("download_capture", {})
            if isinstance(capture_payload, dict):
                download_capture = capture_payload
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Planetka resolve download failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka resolve download failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Planetka resolve download failed: {exc}",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )
        phase_stream_ms = (time.perf_counter() - phase_start) * 1000.0

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
            shader_result = replace_tiles(
                tiles,
                force_remove_unused=True,
                resolved_paths=resolved_paths,
                resolved_tiles_override=resolved_tiles_override,
                ocean_tiles_override=ocean_tiles_override,
            ) or {}
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
        phase_post_mark_ms = (time.perf_counter() - phase_start) * 1000.0

        try:
            scene["planetka_last_resolved_tiles"] = list(tiles)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed caching resolved tiles", exc_info=True)

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
        missing_node_images = _count_missing_tile_loading_images(material_name="Planetka Earth Material")

        if not bool(getattr(self, "silent", False)) and not (force_empty_once and len(tiles) == 0):
            self.report({'INFO'}, f"Planetka resolved ({len(tiles)} tiles)")
        resolve_total_ms = (time.perf_counter() - resolve_start) * 1000.0
        measured_sum_ms = (
            phase_assets_ms
            + phase_tile_select_ms
            + phase_stream_ms
            + phase_mesh_ms
            + phase_shader_ms
            + phase_post_ms
        )
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
        downloaded_bytes = 0
        downloaded_ms = 0.0
        downloaded_thread_ms = 0.0
        if isinstance(download_capture, dict):
            try:
                downloaded_bytes = int(download_capture.get("downloaded_bytes", 0) or 0)
            except (TypeError, ValueError):
                downloaded_bytes = 0
            try:
                downloaded_ms = float(download_capture.get("download_ms", 0.0) or 0.0)
            except (TypeError, ValueError):
                downloaded_ms = 0.0
            try:
                downloaded_thread_ms = float(download_capture.get("download_thread_ms", 0.0) or 0.0)
            except (TypeError, ValueError):
                downloaded_thread_ms = 0.0
        if isinstance(shader_result, dict):
            # Backward-compatible fallback if shader path provides explicit download stats.
            try:
                downloaded_bytes = max(downloaded_bytes, int(shader_result.get("r2_download_bytes", 0) or 0))
            except (TypeError, ValueError):
                pass
            try:
                downloaded_ms = max(downloaded_ms, float(shader_result.get("r2_download_ms", 0.0) or 0.0))
            except (TypeError, ValueError):
                pass
        downloaded_mb = float(downloaded_bytes) / (1024.0 * 1024.0)
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
                "stream_ms": phase_stream_ms,
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
                "download_ms": downloaded_ms,
                "download_thread_ms": downloaded_thread_ms,
                "downloaded_mb": downloaded_mb,
            },
        )

        if int(missing_node_images) > 0:
            logger.warning(
                "Planetka: detected %d texture node(s) without image assignment after resolve.",
                int(missing_node_images),
            )
            if int(getattr(self, "repair_retry_depth", 0)) < 1:
                retry_tiles_json = json.dumps([str(tile) for tile in (tiles or ()) if str(tile or "").strip()])
                retry_result = bpy.ops.planetka.load_textures(
                    scope_mode=str(getattr(self, "scope_mode", "AUTO") or "AUTO"),
                    silent=True,
                    skip_render_compatibility=True,
                    defer_download=False,
                    tiles_override_json=retry_tiles_json,
                    repair_retry_depth=int(getattr(self, "repair_retry_depth", 0)) + 1,
                )
                if "FINISHED" not in retry_result:
                    self.report(
                        {'WARNING'},
                        "Planetka detected missing texture node images and retry resolve did not finish.",
                    )
            else:
                self.report(
                    {'WARNING'},
                    "Planetka detected missing texture node images after retry.",
                )

        if is_remote_source_configured(normalized) and is_authenticated(prefs):
            try:
                sync_account_profile(prefs)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed syncing account profile after resolve", exc_info=True)
            except Exception:
                logger.debug("Planetka: failed syncing account profile after resolve", exc_info=True)
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
