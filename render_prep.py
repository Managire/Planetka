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
import math
import os
import time
import re
from dataclasses import dataclass, field

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .auth import (
    ensure_authenticated_session,
    get_authorized_headers,
    is_authenticated,
)
from .asset_builder import (
    _ensure_surface_elevation_radius_driver,
    ensure_earth_surface_parent,
    sync_surface_elevation_scale_for_radius,
)
from .diagnostics import write_resolve_diagnostics, write_tile_view_diagnostics
from .error_utils import PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS, PLANETKA_RECOVERABLE_EXCEPTIONS, with_error_code
from .extension_prefs import get_earth_object, get_earth_surface_candidates, get_prefs
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .r2_source import (
    is_remote_source_configured,
    remote_tile_asset_exists,
    retain_recent_resolve_cache,
)
from .sanity_utils import _normalize_texture_source_path, validate_known_good_texture_source
from .streaming_utils import (
    consume_staged_prefetch_payload,
    prepare_resolve_streaming_for_visible_tiles,
)
from .state import (
    _clear_camera_inside_earth_warning,
    _estimate_download_bytes_for_visible_tiles,
    _is_animation_playing,
    _is_render_job_active,
    _resolve_scope_altitude_info,
    _set_camera_inside_earth_warning,
    create_temp_mesh,
    cleanup_planetka_unused_data,
    delete_temp_meshes,
    ensure_preview_object,
    ensure_planetka_temp_collection,
    logger,
    mark_resolve_clean_after_resolve,
    start_resolve_download,
    remove_object_and_unused_mesh,
    replace_tiles,
    sync_atmosphere_mode_to_render_engine,
    _store_resolve_summary,
)


_TILE_UTILS_MODULE = None
FORCE_EMPTY_RESOLVE_ONCE_KEY = "planetka_force_empty_resolve_once"
LAST_REQUIRED_MPP_KEY = "planetka_last_required_mpp_m"
LAST_PANORAMA_MODE_KEY = "planetka_last_panorama_mode"
LAST_PANORAMA_LIMIT_EXCEEDED_KEY = "planetka_last_panorama_limit_exceeded"
LAST_PANORAMA_REQUIRED_TILES_KEY = "planetka_last_panorama_required_tiles"
LAST_PANORAMA_REQUIRED_Z_KEY = "planetka_last_panorama_required_z"
LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY = "planetka_last_resolve_texture_quality_mode"
RESOLVE_FAILURE_FLAG_KEY = "planetka_resolve_integrity_failed"
RESOLVE_FAILURE_MESSAGE_KEY = "planetka_resolve_integrity_message"
LAST_MANUAL_RESOLVE_TILE_COUNT_KEY = "planetka_last_manual_resolve_tile_count"
LAST_MANUAL_RESOLVE_DOWNLOADED_MB_KEY = "planetka_last_manual_resolve_downloaded_mb"
LAST_MANUAL_RESOLVE_TOTAL_SECONDS_KEY = "planetka_last_manual_resolve_total_seconds"


_TILE_ZD_PATTERN = re.compile(r"_z(\d+)_d(\d+)$")
_PREFETCH_ACCESS_FAILURE_TOKENS = (
    "request limit reached",
)


@dataclass
class ResolveUiReport:
    level: str
    message: str


@dataclass
class ResolvePrepareContextResult:
    response: object = None
    scene: object = None
    props: object = None
    prefs: object = None
    normalized: str = ""
    manual_summary_requested: bool = False
    force_empty_once: bool = False
    earth_surface: object = None
    target_surface_name: str = "Planetka Earth Surface"
    tile_utils: object = None
    phase_assets_ms: float = 0.0
    ui_reports: list = field(default_factory=list)


@dataclass
class ResolveTileSelectionResult:
    response: object = None
    tiles: list = field(default_factory=list)
    full_source_tiles: list = field(default_factory=list)
    texture_quality_mode: str = "PREVIEW"
    nav_latitude_deg: float = 0.0
    nav_longitude_deg: float = 0.0
    nav_altitude_km: float = 0.0
    phase_tile_select_ms: float = 0.0
    ui_reports: list = field(default_factory=list)


def _scene_uses_equirectangular_panorama(scene):
    try:
        cam = getattr(scene, "camera", None)
        cam_data = getattr(cam, "data", None)
        return (
            str(getattr(cam_data, "type", "") or "").upper() == "PANO"
            and str(getattr(cam_data, "panorama_type", "") or "").upper() == "EQUIRECTANGULAR"
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


@dataclass
class ResolveStreamingResult:
    response: object = None
    resolved_paths: dict = field(default_factory=dict)
    resolved_tiles_override: object = None
    ocean_tiles_override: object = None
    full_quality_cost_bytes: int = 0
    download_capture: dict = field(default_factory=dict)
    phase_stream_ms: float = 0.0
    ui_reports: list = field(default_factory=list)


@dataclass
class ResolveStreamingPayloadData:
    resolved_paths: dict = field(default_factory=dict)
    resolved_tiles_override: object = None
    ocean_tiles_override: object = None
    full_quality_cost_bytes: int = 0
    download_capture: dict = field(default_factory=dict)
    prefetch_missing_count: int = 0
    prefetch_resolved_count: int = 0
    prefetch_error_count: int = 0
    prefetch_missing_details: list = field(default_factory=list)
    prefetch_cancelled: bool = False
    prefetch_fatal_error: str = ""


@dataclass
class ResolveBuildResult:
    response: object = None
    new_obj: object = None
    shader_result: dict = field(default_factory=dict)
    old_surface_viewport_hidden: bool = False
    old_surface_render_hidden: bool = False
    phase_mesh_ms: float = 0.0
    phase_shader_ms: float = 0.0
    target_surface_name: str = "Planetka Earth Surface"
    ui_reports: list = field(default_factory=list)


@dataclass
class ResolveFinalizeResult:
    phase_post_ms: float = 0.0
    phase_post_delete_ms: float = 0.0
    phase_post_mark_ms: float = 0.0
    phase_post_preview_ms: float = 0.0
    phase_cloud_optimize_ms: float = 0.0
    cloud_optimize_optimized: int = 0
    cloud_optimize_failed: int = 0
    missing_node_images: int = 0


@dataclass
class ResolveEarlyResult:
    response: object = None
    ui_reports: list = field(default_factory=list)


def _normalize_texture_quality_mode(value):
    token = str(value or "").strip().upper()
    if token in {"FULL", "BALANCED", "PREVIEW"}:
        return token
    return "PREVIEW"


def _optimize_enabled_clouds_for_resolve(scene, props, texture_quality_mode="PREVIEW"):
    """Update cloud LODs as part of the resolve path, not as a separate UI action."""
    if scene is None or props is None:
        return 0, 0, 0.0
    local_enabled = bool(getattr(props, "enable_local_clouds", False))
    vdb_enabled = bool(getattr(props, "enable_vdb_clouds", False))
    if not local_enabled and not vdb_enabled:
        return 0, 0, 0.0

    phase_start = time.perf_counter()
    optimized = 0
    failed = 0
    try:
        from . import clouds_local as cloud_runtime
        if local_enabled:
            local_optimized, local_failed = cloud_runtime.optimize_texture_based_clouds_for_camera(
                scene=scene,
                quality_mode=texture_quality_mode,
            )
            optimized += int(local_optimized or 0)
            failed += int(local_failed or 0)
        if vdb_enabled:
            vdb_optimized, vdb_failed = cloud_runtime.optimize_vdb_clouds_for_camera(
                scene=scene,
                quality_mode=texture_quality_mode,
            )
            optimized += int(vdb_optimized or 0)
            failed += int(vdb_failed or 0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed optimizing clouds after resolve", exc_info=True)
        failed += 1
    except (ImportError, ModuleNotFoundError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed optimizing clouds after resolve", exc_info=True)
        failed += 1

    return int(optimized), int(failed), (time.perf_counter() - phase_start) * 1000.0


def _get_tile_utils():
    global _TILE_UTILS_MODULE
    if _TILE_UTILS_MODULE is None:
        module_name = f"{__package__}.tile_utils" if __package__ else "tile_utils"
        try:
            _TILE_UTILS_MODULE = importlib.import_module(module_name)
        except ImportError:
            _TILE_UTILS_MODULE = False
    return _TILE_UTILS_MODULE or None


def apply_texture_quality_to_full_tiles(tiles, texture_quality_mode="PREVIEW"):
    """Transform full-quality source tiles to the selected Quality Level.

    This is the only resolve-stage function allowed to alter S2 D-levels.
    Z-levels are preserved. D-levels only move coarser, never sharper.
    """
    tile_utils = _get_tile_utils()
    if tile_utils is None:
        return [str(tile).strip() for tile in (tiles or ()) if str(tile or "").strip()]

    sort_tiles = getattr(tile_utils, "_sort_tiles_for_apply", None)
    parse_tile = getattr(tile_utils, "parse_tile", None)
    format_tile = getattr(tile_utils, "format_tile", None)
    d_levels_by_z = getattr(tile_utils, "D_LEVELS_BY_Z", {})
    if not callable(sort_tiles) or not callable(parse_tile) or not callable(format_tile):
        return [str(tile).strip() for tile in (tiles or ()) if str(tile or "").strip()]

    mode = _normalize_texture_quality_mode(texture_quality_mode)
    factor = 1
    if mode == "BALANCED":
        factor = 2
    elif mode == "PREVIEW":
        factor = 4
    if factor == 1:
        return list(sort_tiles(tiles or ()))

    adjusted = []
    for tile in (tiles or ()):
        tile_text = str(tile or "").strip()
        if not tile_text:
            continue
        parsed = parse_tile(tile_text)
        if not parsed:
            adjusted.append(tile_text)
            continue
        x, y, z, d = parsed
        source_d = 1440 if int(d) == 0 else int(d)
        target_d = int(source_d) * int(factor)
        allowed = sorted({int(value) for value in d_levels_by_z.get(int(z), [int(z)])})
        replacement = None
        for candidate in allowed:
            if int(candidate) >= int(target_d):
                replacement = int(candidate)
                break
        if replacement is None:
            replacement = int(max(allowed)) if allowed else int(target_d)
        adjusted.append(format_tile(int(x), int(y), int(z), int(replacement)))
    return list(sort_tiles(adjusted))


def _validate_texture_source(base_path):
    normalized = _normalize_texture_source_path(base_path)
    if not is_remote_source_configured(normalized):
        details = validate_known_good_texture_source(normalized)
        normalized = str(details.get("normalized_path", "") or normalized)
        issues = list(details.get("issues", ()) or ())
        for level, _code, message in issues:
            if str(level).upper() == "ERROR":
                return "", str(message or "Unsupported local texture source is invalid.")
        return normalized, ""

    # Remote resolves validate access while fetching the exact requested assets.
    # A sentinel HEAD request here blocks every resolve and can refresh
    # auth on the UI/operator path before the background worker even starts.
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


def _show_popup_lines(context, title, icon, lines):
    wm = getattr(context, "window_manager", None) if context else None
    if wm is None:
        return

    def _draw(_self, popup_context):
        layout = getattr(_self, "layout", None)
        if layout is None:
            return
        for line in lines:
            layout.label(text=str(line))

    try:
        wm.popup_menu(_draw, title=str(title or "Planetka"), icon=str(icon or "INFO"))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed showing popup warning", exc_info=True)


def _wrap_popup_text_lines(text, width=86):
    raw = str(text or "").strip()
    if not raw:
        return ()
    tokens = raw.split()
    if not tokens:
        return ()
    lines = []
    current = []
    current_len = 0
    for token in tokens:
        token_len = len(token)
        sep = 1 if current else 0
        if current and (current_len + sep + token_len) > int(max(20, int(width))):
            lines.append(" ".join(current))
            current = [token]
            current_len = token_len
        else:
            if current:
                current_len += 1 + token_len
                current.append(token)
            else:
                current = [token]
                current_len = token_len
    if current:
        lines.append(" ".join(current))
    return tuple(lines)


def _set_resolve_failure_notice(scene, message):
    if scene is None:
        return
    safe_message = (
        str(message or "").strip()
        or "Resolve failed. Please click Resolve Planetka"
    )
    try:
        scene[RESOLVE_FAILURE_FLAG_KEY] = True
        scene[RESOLVE_FAILURE_MESSAGE_KEY] = safe_message
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed storing resolve failure notice on scene", exc_info=True)


def _clear_resolve_failure_notice(scene):
    if scene is None:
        return
    try:
        if RESOLVE_FAILURE_FLAG_KEY in scene:
            del scene[RESOLVE_FAILURE_FLAG_KEY]
        if RESOLVE_FAILURE_MESSAGE_KEY in scene:
            del scene[RESOLVE_FAILURE_MESSAGE_KEY]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed clearing resolve failure notice on scene", exc_info=True)


def _store_last_resolve_error(scene, message, log_label):
    if scene is None:
        return
    try:
        scene["planetka_last_resolve_error"] = str(message or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: %s", str(log_label or "failed storing resolve error marker"), exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: %s", str(log_label or "failed storing resolve error marker"), exc_info=True)


def _count_missing_tile_loading_images(material_name="Planetka Earth Material"):
    material = bpy.data.materials.get(str(material_name or ""))
    if material is None or getattr(material, "node_tree", None) is None:
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

    group_name = str(getattr(group_tree, "name", "") or "")
    group_name = group_name.strip()
    testing_mode = group_name in {
        "Planetka Textures Loading Group",
        "Planetka Textures Loading Group - Testing",
    }
    image_types = ("S2", "EL", "WT", "PO")

    if testing_mode:
        missing = 0
        for node in group_nodes:
            if str(getattr(node, "type", "")) != "GROUP":
                continue
            node_name = str(getattr(node, "name", "") or "")
            if not node_name.startswith("Tile_"):
                continue
            if bool(getattr(node, "mute", False)):
                continue
            suffix = node_name.split("_", 1)[1] if "_" in node_name else ""
            if not suffix.isdigit():
                continue
            index = int(suffix)
            for image_type in image_types:
                img_node = group_nodes.get(f"TileImg_{index:03d}_{image_type}")
                if img_node is None:
                    missing += 1
                    continue
                image = getattr(img_node, "image", None)
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
        for image_type in image_types:
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


def _set_object_hidden_state(obj, viewport_hidden=None, render_hidden=None):
    if obj is None:
        return
    try:
        if viewport_hidden is not None and hasattr(obj, "hide_viewport"):
            obj.hide_viewport = bool(viewport_hidden)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed setting object viewport hidden state", exc_info=True)
    try:
        if render_hidden is not None and hasattr(obj, "hide_render"):
            obj.hide_render = bool(render_hidden)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed setting object render hidden state", exc_info=True)


def _earth_radius_blender_units(earth_obj):
    if earth_obj is None:
        return 2.0
    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0
    try:
        world_scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        max_scale = 1.0
    if stored_local_radius > 1e-9:
        return float(stored_local_radius) * float(max_scale)
    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    if vertices:
        try:
            local_radius = max(float(v.co.length) for v in vertices)
            if local_radius > 1e-9:
                return float(local_radius) * float(max_scale)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    return max(float(max_scale), 1.0)


def _validate_resolve_scene_integrity(earth_surface):
    if earth_surface is None:
        return "Resolve requires an existing Earth surface object."
    if str(getattr(earth_surface, "type", "")) != "MESH":
        return "Earth surface object must be a mesh."

    material = bpy.data.materials.get("Planetka Earth Material")
    if material is None:
        return "Missing required material: Planetka Earth Material."
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return "Planetka Earth Material has no node tree."

    material_slots = tuple(getattr(getattr(earth_surface, "data", None), "materials", ()) or ())
    if material not in material_slots:
        return (
            f"Earth surface object '{earth_surface.name}' is not using 'Planetka Earth Material'. "
            "Restore required material assignments and retry."
        )

    loading_node = getattr(node_tree, "nodes", None).get("Planetka Textures Loading") if getattr(node_tree, "nodes", None) else None
    if loading_node is None:
        return "Planetka Earth Material is missing node 'Planetka Textures Loading'."
    if str(getattr(loading_node, "type", "")) != "GROUP":
        return "Node 'Planetka Textures Loading' has invalid type."
    if getattr(loading_node, "node_tree", None) is None:
        return "Node 'Planetka Textures Loading' is missing its group tree."

    return ""


def _validate_resolve_completion_integrity(scene, earth_surface, requested_tiles, shader_result, missing_node_images):
    issues = []
    final_surface = get_earth_object() or earth_surface
    if final_surface is None:
        issues.append("Earth surface object is missing after resolve.")
        return issues

    scene_integrity_issue = _validate_resolve_scene_integrity(final_surface)
    if scene_integrity_issue:
        issues.append(scene_integrity_issue)

    mesh_data = getattr(final_surface, "data", None)
    try:
        vertex_count = len(getattr(mesh_data, "vertices", ()) or ())
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        vertex_count = 0
    if int(vertex_count) <= 0:
        issues.append("Earth surface mesh has no vertices after resolve.")

    try:
        users_collection = tuple(getattr(final_surface, "users_collection", ()) or ())
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        users_collection = ()
    if not users_collection:
        issues.append("Earth surface object is not linked to any collection.")

    try:
        missing_count = int(missing_node_images or 0)
    except (TypeError, ValueError):
        missing_count = 0
    if missing_count > 0:
        issues.append(f"Texture node images missing after resolve: {missing_count}.")

    requested_count = 0
    for tile in requested_tiles or ():
        if str(tile or "").strip():
            requested_count += 1
    applied_tiles = ()
    if isinstance(shader_result, dict):
        payload = shader_result.get("resolved_tiles", None)
        if payload is None:
            payload = shader_result.get("applied_tiles", ())
        if isinstance(payload, (list, tuple, set)):
            applied_tiles = tuple(str(tile) for tile in payload if str(tile or "").strip())
    if requested_count > 0 and len(applied_tiles) <= 0:
        issues.append("Shader did not apply any resolved tiles.")

    if scene is not None:
        try:
            scene_root = getattr(scene, "collection", None)
            if scene_root is None:
                issues.append("Scene root collection is unavailable after resolve.")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            issues.append("Scene root collection is unavailable after resolve.")
    return issues


def _prefetch_missing_details_indicate_access_failure(details):
    if not isinstance(details, (tuple, list)):
        return False
    for entry in details:
        if not isinstance(entry, dict):
            continue
        folder_value = str(entry.get("folder", "") or "").strip().upper()
        if folder_value != "S2":
            continue
        combined = " ".join((
            str(entry.get("fetch_error", "") or ""),
            str(entry.get("remote_error", "") or ""),
        )).lower()
        if any(token in combined for token in _PREFETCH_ACCESS_FAILURE_TOKENS):
            return True
    return False


class PLANETKA_OT_LoadTextures(bpy.types.Operator):
    bl_idname = "planetka.load_textures"
    bl_label = "Resolve Earth"
    bl_description = "Resolve visible Earth tiles and rebuild the Planetka surface mesh/material assignment"

    scope_mode: EnumProperty(
        name="Scope Mode",
        items=(
            ("AUTO", "Auto", ""),
            ("CAMERA", "Camera", ""),
        ),
        default="AUTO",
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

    capture_download_progress: BoolProperty(
        name="Capture Download Progress",
        default=True,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    tiles_override_json: StringProperty(
        name="Tiles Override",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    texture_quality_mode_override: StringProperty(
        name="Quality Level Override",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    streaming_feature: StringProperty(
        name="Streaming Feature",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )


    def _abort_resolve(self, message, code=ErrorCode.RESOLVE_REFRESH_FAILED, exc=None, log_message=None, cleanup_obj=None):
        if cleanup_obj is not None:
            try:
                remove_object_and_unused_mesh(cleanup_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed removing temporary Earth object during resolve abort", exc_info=True)
        if exc is not None and log_message is not None:
            return fail(
                self,
                str(message or ""),
                code=code,
                logger=logger,
                exc=exc,
                log_message=str(log_message or ""),
            )
        if exc is not None:
            return fail(
                self,
                str(message or ""),
                code=code,
                logger=logger,
                exc=exc,
            )
        return fail(
            self,
            str(message or ""),
            code=code,
            logger=logger,
        )

    def _ui_report(self, level, message):
        return ResolveUiReport(str(level or "INFO").upper(), str(message or ""))

    def _flush_ui_reports(self, ui_reports):
        for entry in list(ui_reports or ()):
            if not isinstance(entry, ResolveUiReport):
                continue
            level = str(entry.level or "INFO").upper()
            if level not in {"INFO", "WARNING", "ERROR"}:
                level = "INFO"
            text = str(entry.message or "").strip()
            if not text:
                continue
            try:
                self.report({level}, text)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed emitting resolve UI report", exc_info=True)

    def _phase_prepare_context(self, context):
        phase_start = time.perf_counter()
        ui_reports = []
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return ResolvePrepareContextResult(response={'CANCELLED'})
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return ResolvePrepareContextResult(response={'CANCELLED'})
        manual_summary_requested = not bool(getattr(self, "defer_download", False))

        if bool(getattr(props, "lock_resolve_during_animation", True)) and _is_animation_playing():
            ui_reports.append(self._ui_report("WARNING", "Resolve skipped during animation playback (disabled in Settings)."))
            return ResolvePrepareContextResult(response={'CANCELLED'}, ui_reports=ui_reports)

        prefs = get_prefs()
        if not prefs:
            return ResolvePrepareContextResult(
                response=fail(
                    self,
                    "Planetka preferences not available.",
                    code=ErrorCode.RESOLVE_PREFS_MISSING,
                    logger=logger,
                ),
                ui_reports=ui_reports,
            )

        normalized = _normalize_texture_source_path(getattr(prefs, "texture_base_path", ""))
        normalized, issue = _validate_texture_source(normalized)
        if issue:
            return ResolvePrepareContextResult(
                response=fail(
                    self,
                    issue,
                    code=ErrorCode.RESOLVE_PATH_INVALID,
                    logger=logger,
                ),
                ui_reports=ui_reports,
            )
        if is_remote_source_configured(normalized):
            try:
                if not is_authenticated(prefs):
                    ensure_authenticated_session(prefs)
                # Download workers cannot read Blender preferences off-thread.
                # Prime the authorized-header snapshot on the main thread before
                # any parallel tile/cloud fetch starts.
                get_authorized_headers(prefs=prefs, allow_refresh=True)
            except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
                return ResolvePrepareContextResult(
                    response=fail(
                        self,
                        "Planetka session could not be started. Check your connection and try again.",
                        code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                        logger=logger,
                        exc=exc,
                    ),
                    ui_reports=ui_reports,
                )
        prefs.texture_base_path = normalized

        try:
            sync_atmosphere_mode_to_render_engine(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed syncing atmosphere mode during resolve", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed syncing atmosphere mode during resolve", exc_info=True)

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
                return ResolvePrepareContextResult(
                    response=fail(
                        self,
                        (
                            "Resolve requires one unambiguous Earth surface object. "
                            f"Found {len(candidates)} candidates: {candidate_names}. "
                            "Keep one Planetka Earth surface and retry."
                        ),
                        code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                        logger=logger,
                    ),
                    ui_reports=ui_reports,
                )
            return ResolvePrepareContextResult(
                response=fail(
                    self,
                    "Resolve requires an existing Planetka Earth surface. Run Create Earth first.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                ),
                ui_reports=ui_reports,
            )
        integrity_issue = _validate_resolve_scene_integrity(earth_surface)
        if integrity_issue:
            return ResolvePrepareContextResult(
                response=fail(
                    self,
                    integrity_issue,
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                ),
                ui_reports=ui_reports,
            )
        target_surface_name = str(getattr(earth_surface, "name", "") or "Planetka Earth Surface")

        # Apply requested Earth Radius on resolve as a safe fallback in case the UI
        # setter was invoked in a context where direct mesh update could not run.
        try:
            desired_radius = float(getattr(props, "earth_radius_bu", 2.0))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            desired_radius = 2.0
        if not math.isfinite(desired_radius):
            desired_radius = 2.0
        desired_radius = max(1e-6, float(desired_radius))
        try:
            current_radius = float(_earth_radius_blender_units(earth_surface))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            current_radius = desired_radius
        if math.isfinite(current_radius) and abs(current_radius - desired_radius) > 1e-6:
            try:
                operators_module = importlib.import_module(f"{__package__}.operators" if __package__ else "operators")
                set_radius_fn = getattr(operators_module, "_set_planetka_earth_radius_bu", None)
                if callable(set_radius_fn):
                    set_radius_fn(scene, desired_radius)
            except PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed applying deferred Earth Radius during resolve", exc_info=True)
        try:
            earth_radius_bu = _earth_radius_blender_units(earth_surface)
            driver_bound = _ensure_surface_elevation_radius_driver(scene)
            if driver_bound:
                logger.debug(
                    "Planetka: bound elevation-radius displacement driver during resolve migration.",
                )
            scale_value, scale_changed = sync_surface_elevation_scale_for_radius(earth_radius_bu)
            if scale_changed:
                logger.debug(
                    "Planetka: synchronized elevation displacement scale for Earth radius %.6f (scale=%.9f).",
                    float(earth_radius_bu),
                    float(scale_value),
                )
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed syncing elevation displacement scale from Earth radius", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed syncing elevation displacement scale from Earth radius", exc_info=True)

        tile_utils = _get_tile_utils()
        if tile_utils is None:
            return ResolvePrepareContextResult(
                response=fail(
                    self,
                    "Resolve failed because tile utilities are unavailable.",
                    code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                    logger=logger,
                ),
                ui_reports=ui_reports,
            )

        scope_mode = str(getattr(self, "scope_mode", "AUTO") or "AUTO")
        altitude_info = _resolve_scope_altitude_info(scene, scope_mode=scope_mode)
        if bool(altitude_info.get("inside_earth", False)):
            _set_camera_inside_earth_warning(scene, altitude_info.get("altitude_km"))
            return ResolvePrepareContextResult(response={'CANCELLED'}, ui_reports=ui_reports)
        _clear_camera_inside_earth_warning(scene)

        return ResolvePrepareContextResult(
            response=None,
            scene=scene,
            props=props,
            prefs=prefs,
            normalized=normalized,
            manual_summary_requested=bool(manual_summary_requested),
            force_empty_once=bool(force_empty_once),
            earth_surface=earth_surface,
            target_surface_name=target_surface_name,
            tile_utils=tile_utils,
            phase_assets_ms=(time.perf_counter() - phase_start) * 1000.0,
            ui_reports=ui_reports,
        )

    def _phase_select_tiles(self, scene, props, tile_utils, force_empty_once):
        ui_reports = []
        tiles_override = _parse_tiles_override(getattr(self, "tiles_override_json", ""))
        try:
            override_mode = str(getattr(self, "texture_quality_mode_override", "") or "").strip()
            if override_mode:
                texture_quality_mode = _normalize_texture_quality_mode(override_mode)
            else:
                texture_quality_mode = _normalize_texture_quality_mode(
                    getattr(props, "texture_quality_mode", "PREVIEW")
                )
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            texture_quality_mode = "PREVIEW"
        try:
            nav_latitude_deg = float(getattr(props, "nav_latitude_deg", 0.0))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            nav_latitude_deg = 0.0
        try:
            nav_longitude_deg = float(getattr(props, "nav_longitude_deg", 0.0))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            nav_longitude_deg = 0.0
        try:
            nav_altitude_km = max(0.0, float(getattr(props, "nav_altitude_km", 0.0)))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            nav_altitude_km = 0.0

        phase_start = time.perf_counter()
        if tiles_override is not None:
            tiles = [] if force_empty_once else list(tiles_override)
            full_source_tiles = list(tiles or ())
        else:
            try:
                full_source_tiles = tile_utils.main(
                    scope_mode=str(getattr(self, "scope_mode", "AUTO") or "AUTO"),
                )
                tiles = [] if force_empty_once else apply_texture_quality_to_full_tiles(
                    full_source_tiles,
                    texture_quality_mode,
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.exception("Planetka tile resolve failed; resolving to no visible tiles")
                tiles = []
                full_source_tiles = []
                ui_reports.append(self._ui_report("WARNING", "Tile detection failed; resolving to no visible tiles."))
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
                full_source_tiles = []
                ui_reports.append(self._ui_report("WARNING", "No active camera/view found; resolving to no visible tiles."))

        return ResolveTileSelectionResult(
            response=None,
            tiles=list(tiles or ()),
            full_source_tiles=list(full_source_tiles or ()),
            texture_quality_mode=texture_quality_mode,
            nav_latitude_deg=nav_latitude_deg,
            nav_longitude_deg=nav_longitude_deg,
            nav_altitude_km=nav_altitude_km,
            phase_tile_select_ms=(time.perf_counter() - phase_start) * 1000.0,
            ui_reports=ui_reports,
        )

    def _phase_handle_panorama_or_defer(
        self,
        context,
        scene,
        props,
        tiles,
        full_source_tiles,
        texture_quality_mode,
        normalized,
    ):
        ui_reports = []
        try:
            panorama_mode = bool(scene.get(LAST_PANORAMA_MODE_KEY, False))
            panorama_limit_exceeded = bool(scene.get(LAST_PANORAMA_LIMIT_EXCEEDED_KEY, False))
            panorama_required_tiles = int(scene.get(LAST_PANORAMA_REQUIRED_TILES_KEY, 0) or 0)
            panorama_required_z = int(scene.get(LAST_PANORAMA_REQUIRED_Z_KEY, 0) or 0)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            panorama_mode = False
            panorama_limit_exceeded = False
            panorama_required_tiles = 0
            panorama_required_z = 0

        if panorama_mode and panorama_limit_exceeded:
            panorama_message = (
                f"Panorama resolve exceeds tile limit: {int(panorama_required_tiles)} required "
                f"(limit 12, z{int(panorama_required_z):03d})."
            )
            coded_panorama_message = with_error_code(ErrorCode.RESOLVE_PRECHECK_FAILED, panorama_message)
            _store_last_resolve_error(
                scene,
                coded_panorama_message,
                "failed storing panorama tile-limit resolve error",
            )
            _show_popup_lines(
                context,
                "Panorama Resolve Warning",
                "ERROR",
                (
                    "Equirectangular panorama needs too many tiles for this view.",
                    f"Required tiles: {int(panorama_required_tiles)} at z{int(panorama_required_z):03d}.",
                    "Current shader limit is 12 tiles.",
                    "Increase camera altitude or reduce required quality and resolve again.",
                ),
            )
            ui_reports.append(self._ui_report("WARNING", panorama_message))
            return ResolveEarlyResult(response={'CANCELLED'}, ui_reports=ui_reports)

        if bool(getattr(self, "defer_download", False)):
            if _is_render_job_active():
                logger.info("Planetka: ignored deferred resolve request during active render job.")
                ui_reports.append(
                    self._ui_report(
                        "WARNING",
                        "Planetka deferred resolve is disabled while rendering.",
                    )
                )
                return ResolveEarlyResult(response={'CANCELLED'}, ui_reports=ui_reports)
            started = start_resolve_download(
                scene,
                [str(tile) for tile in (tiles or ()) if str(tile or "").strip()],
                manual_request=True,
                texture_quality_mode_override=texture_quality_mode,
            )
            if not started:
                return ResolveEarlyResult(
                    response=fail(
                        self,
                        "Planetka could not start resolve download.",
                        code=ErrorCode.RESOLVE_REFRESH_FAILED,
                        logger=logger,
                    ),
                    ui_reports=ui_reports,
                )
            ui_reports.append(self._ui_report("INFO", "Planetka resolve started. Preparing textures in background."))
            return ResolveEarlyResult(response={'FINISHED'}, ui_reports=ui_reports)

        _ = props
        return ResolveEarlyResult(response=None, ui_reports=ui_reports)

    def _phase_prepare_streaming(
        self,
        scene,
        tiles,
        normalized,
        texture_quality_mode,
        nav_latitude_deg,
        nav_longitude_deg,
        nav_altitude_km,
        capture_download_progress=True,
        feature="",
        ):
        ui_reports = []
        phase_start = time.perf_counter()
        try:
            stream_payload = self._get_stream_payload(
                tiles=tiles,
                normalized=normalized,
                texture_quality_mode=texture_quality_mode,
                nav_latitude_deg=nav_latitude_deg,
                nav_longitude_deg=nav_longitude_deg,
                nav_altitude_km=nav_altitude_km,
                feature=feature,
                capture_download_progress=bool(capture_download_progress),
            )
            payload_data = self._parse_stream_payload(stream_payload)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return ResolveStreamingResult(
                response=fail(
                    self,
                    f"Planetka resolve download failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                    exc=exc,
                    log_message="Planetka resolve download failed",
                ),
                ui_reports=ui_reports,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return ResolveStreamingResult(
                response=fail(
                    self,
                    f"Planetka resolve download failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                ),
                ui_reports=ui_reports,
            )

        policy_response = self._enforce_streaming_result_policy(scene, payload_data)
        if policy_response is not None:
            return ResolveStreamingResult(response=policy_response, ui_reports=ui_reports)

        return ResolveStreamingResult(
            response=None,
            resolved_paths=dict(payload_data.resolved_paths or {}),
            resolved_tiles_override=payload_data.resolved_tiles_override,
            ocean_tiles_override=payload_data.ocean_tiles_override,
            full_quality_cost_bytes=int(payload_data.full_quality_cost_bytes or 0),
            download_capture=dict(payload_data.download_capture or {}),
            phase_stream_ms=(time.perf_counter() - phase_start) * 1000.0,
            ui_reports=ui_reports,
        )

    def _get_stream_payload(
        self,
        *,
        tiles,
        normalized,
        texture_quality_mode,
        nav_latitude_deg,
        nav_longitude_deg,
        nav_altitude_km,
        capture_download_progress=True,
        feature="",
        ):
        stream_payload = consume_staged_prefetch_payload(
            tiles,
            normalized,
            texture_quality_mode=texture_quality_mode,
        )
        if not isinstance(stream_payload, dict):
            return prepare_resolve_streaming_for_visible_tiles(
                tiles,
                normalized,
                texture_quality_mode=texture_quality_mode,
                capture=bool(capture_download_progress),
                nav_latitude_deg=nav_latitude_deg,
                nav_longitude_deg=nav_longitude_deg,
                nav_altitude_km=nav_altitude_km,
                feature=feature,
            )
        if _normalize_texture_quality_mode(stream_payload.get("texture_quality_mode", "PREVIEW")) != texture_quality_mode:
            return prepare_resolve_streaming_for_visible_tiles(
                tiles,
                normalized,
                capture=bool(capture_download_progress),
                texture_quality_mode=texture_quality_mode,
                nav_latitude_deg=nav_latitude_deg,
                nav_longitude_deg=nav_longitude_deg,
                nav_altitude_km=nav_altitude_km,
                feature=feature,
            )
        return stream_payload

    def _parse_stream_payload(self, stream_payload):
        resolved_paths = dict(stream_payload.get("resolved_paths", {}) or {})
        resolved_tiles_override = list(stream_payload.get("resolved_tiles", ()) or ())
        ocean_tiles_override = set(stream_payload.get("ocean_tiles", ()) or ())
        download_capture = {
            "downloaded_bytes": 0,
            "download_ms": 0.0,
        }
        prefetch_missing_count = 0
        prefetch_resolved_count = 0
        prefetch_error_count = 0
        prefetch_missing_details = []
        prefetch_cancelled = bool(stream_payload.get("cancelled", False))
        prefetch_fatal_error = ""

        prefetch_payload = stream_payload.get("prefetch_result", {})
        if isinstance(prefetch_payload, dict):
            try:
                prefetch_missing_count = int(prefetch_payload.get("missing_count", 0) or 0)
            except (TypeError, ValueError):
                prefetch_missing_count = 0
            try:
                prefetch_resolved_count = int(prefetch_payload.get("resolved_count", 0) or 0)
            except (TypeError, ValueError):
                prefetch_resolved_count = 0
            try:
                prefetch_error_count = int(prefetch_payload.get("error_count", 0) or 0)
            except (TypeError, ValueError):
                prefetch_error_count = 0
            details_payload = prefetch_payload.get("missing_details", ())
            if isinstance(details_payload, (list, tuple)):
                prefetch_missing_details = [dict(item) for item in details_payload if isinstance(item, dict)]
            prefetch_cancelled = bool(prefetch_payload.get("cancelled", False)) or prefetch_cancelled
            prefetch_fatal_error = str(prefetch_payload.get("fatal_error", "") or "").strip()
        capture_payload = stream_payload.get("download_capture", {})
        if isinstance(capture_payload, dict):
            download_capture = capture_payload

        return ResolveStreamingPayloadData(
            resolved_paths=resolved_paths,
            resolved_tiles_override=resolved_tiles_override,
            ocean_tiles_override=ocean_tiles_override,
            full_quality_cost_bytes=0,
            download_capture=dict(download_capture or {}),
            prefetch_missing_count=int(prefetch_missing_count or 0),
            prefetch_resolved_count=int(prefetch_resolved_count or 0),
            prefetch_error_count=int(prefetch_error_count or 0),
            prefetch_missing_details=list(prefetch_missing_details or ()),
            prefetch_cancelled=bool(prefetch_cancelled),
            prefetch_fatal_error=prefetch_fatal_error,
        )

    def _enforce_streaming_result_policy(self, scene, payload_data):
        if bool(payload_data.prefetch_fatal_error):
            coded_fatal_message = with_error_code(
                ErrorCode.RESOLVE_REFRESH_FAILED,
                payload_data.prefetch_fatal_error,
            )
            _store_last_resolve_error(
                scene,
                coded_fatal_message,
                "failed storing fatal resolve error on scene",
            )
            return fail(
                self,
                payload_data.prefetch_fatal_error,
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )
        if bool(payload_data.prefetch_cancelled):
            return fail(
                self,
                "Planetka resolve download was cancelled.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )
        if int(payload_data.prefetch_missing_count) > 0:
            if _prefetch_missing_details_indicate_access_failure(payload_data.prefetch_missing_details):
                access_message = "Planetka data download could not be confirmed. Please retry."
                coded_access_message = with_error_code(ErrorCode.RESOLVE_REFRESH_FAILED, access_message)
                _store_last_resolve_error(
                    scene,
                    coded_access_message,
                    "failed storing access resolve error on scene",
                )
                return fail(
                    self,
                    access_message,
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )
            required_missing_details = []
            if payload_data.prefetch_missing_details:
                for entry in payload_data.prefetch_missing_details:
                    if not isinstance(entry, dict):
                        continue
                    folder_value = str(entry.get("folder", "") or "").strip().upper()
                    prefix_value = str(entry.get("prefix", "") or "").strip()
                    tile_value = str(entry.get("tile", "") or "").strip()
                    ext_value = str(entry.get("ext", "") or "").strip().lower()
                    if not folder_value or not prefix_value or not tile_value:
                        continue
                    if folder_value != "S2":
                        continue
                    if ext_value and not ext_value.startswith("."):
                        ext_value = f".{ext_value}"
                    if not ext_value:
                        ext_value = ".exr"
                    file_name = f"{prefix_value}_{tile_value}{ext_value}"
                    if not remote_tile_asset_exists(folder_value, file_name):
                        continue
                    required_missing_details.append(entry)
            required_missing_count = int(len(required_missing_details))
            if required_missing_count > 0:
                required_missing_s2_count = int(required_missing_count)
                logger.warning(
                    "Planetka: resolve prefetch missing required S2 files "
                    "(required_s2=%d total_missing=%d resolved=%d errors=%d).",
                    int(required_missing_s2_count),
                    int(payload_data.prefetch_missing_count),
                    int(payload_data.prefetch_resolved_count),
                    int(payload_data.prefetch_error_count),
                )
                for entry in required_missing_details:
                    logger.warning(
                        "Planetka prefetch missing required asset: key=%s tile=%s cache_exists=%s remote_exists=%s fetch_error=%s remote_error=%s",
                        str(entry.get("key", "") or ""),
                        str(entry.get("tile", "") or ""),
                        bool(entry.get("cache_exists", False)),
                        entry.get("remote_exists"),
                        str(entry.get("fetch_error", "") or ""),
                        str(entry.get("remote_error", "") or ""),
                    )
                missing_message = "Some required texture data could not be downloaded. Please retry."
                coded_missing_message = with_error_code(ErrorCode.RESOLVE_REFRESH_FAILED, missing_message)
                _store_last_resolve_error(
                    scene,
                    coded_missing_message,
                    "failed storing missing-file resolve error on scene",
                )
                return fail(
                    self,
                    missing_message,
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    logger=logger,
                )
        return None

    def _phase_build_surface(
        self,
        scene,
        earth_surface,
        target_surface_name,
        tiles,
        resolved_paths,
        resolved_tiles_override,
        ocean_tiles_override,
    ):
        ui_reports = []
        ensure_planetka_temp_collection()
        new_obj = None
        old_surface_viewport_hidden = bool(getattr(earth_surface, "hide_viewport", False))
        old_surface_render_hidden = bool(getattr(earth_surface, "hide_render", False))
        try:
            phase_start = time.perf_counter()
            new_obj = create_temp_mesh(
                tiles,
                name="Planetka Earth Surface (New)",
                collection_policy="inherit_old",
            )
            if not new_obj:
                raise RuntimeError("Failed to create new Earth surface mesh")
            try:
                ensure_earth_surface_parent(scene=scene, earth_surface=new_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed early-parenting staging Earth surface to Planetka Root", exc_info=True)
            # Keep the existing resolved surface visible while we build/rebind the new
            # surface in the background. Hiding both surfaces can cause visible white/black
            # flashes in Active View because there is a frame with no textured surface.
            _set_object_hidden_state(new_obj, viewport_hidden=True, render_hidden=True)
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
            return ResolveBuildResult(
                response=self._abort_resolve(
                    f"Planetka resolve failed: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    exc=exc,
                    log_message="Planetka resolve failed",
                    cleanup_obj=new_obj,
                ),
                ui_reports=ui_reports,
            )
        except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
            return ResolveBuildResult(
                response=self._abort_resolve(
                    f"Planetka resolve failed unexpectedly: {exc}",
                    code=ErrorCode.RESOLVE_REFRESH_FAILED,
                    exc=exc,
                    log_message="Planetka resolve failed unexpectedly",
                    cleanup_obj=new_obj,
                ),
                ui_reports=ui_reports,
            )

        return ResolveBuildResult(
            response=None,
            new_obj=new_obj,
            shader_result=dict(shader_result or {}),
            old_surface_viewport_hidden=bool(old_surface_viewport_hidden),
            old_surface_render_hidden=bool(old_surface_render_hidden),
            phase_mesh_ms=float(phase_mesh_ms or 0.0),
            phase_shader_ms=float(phase_shader_ms or 0.0),
            target_surface_name=str(target_surface_name or "Planetka Earth Surface"),
            ui_reports=ui_reports,
        )

    def _phase_finalize_surface(
        self,
        scene,
        props,
        new_obj,
        target_surface_name,
        old_surface_viewport_hidden,
        old_surface_render_hidden,
        resolved_paths,
        force_empty_once,
        tiles,
        ui_reports,
        texture_quality_mode,
    ):
        phase_start = time.perf_counter()
        try:
            new_obj.name = str(target_surface_name or "Planetka Earth Surface")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed renaming resolved Earth surface object", exc_info=True)
        try:
            ensure_earth_surface_parent(scene=scene, earth_surface=new_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed parenting resolved Earth surface to Planetka Root", exc_info=True)
        # Reveal the new surface first, then remove old surfaces to avoid blank-frame flashes.
        _set_object_hidden_state(
            new_obj,
            viewport_hidden=old_surface_viewport_hidden,
            render_hidden=old_surface_render_hidden,
        )
        phase_post_mark_ms = (time.perf_counter() - phase_start) * 1000.0

        phase_start = time.perf_counter()
        delete_temp_meshes(keep_obj=new_obj)
        phase_post_delete_ms = (time.perf_counter() - phase_start) * 1000.0
        # Final naming pass after old surfaces are deleted.
        # This removes Blender suffixes such as ".001" that can appear when the
        # first rename happens before temporary/old surfaces are removed.
        try:
            new_obj.name = "Planetka Earth Surface"
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed final canonical rename for Earth surface object", exc_info=True)

        try:
            scene["planetka_last_resolved_tiles"] = list(tiles)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed caching resolved tiles", exc_info=True)

        try:
            applied_quality_mode = _normalize_texture_quality_mode(texture_quality_mode)
            props.texture_quality_mode = applied_quality_mode
            scene["planetka_last_resolve_texture_quality_mode"] = applied_quality_mode
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed storing applied texture quality mode", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed storing applied texture quality mode", exc_info=True)

        try:
            retain_recent_resolve_cache(resolved_paths, keep_count=2)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed pruning cache to current+previous resolve snapshots", exc_info=True)

        phase_post_preview_ms = 0.0
        if not force_empty_once and bool(getattr(props, "show_earth_preview", False)):
            phase_start = time.perf_counter()
            try:
                ensure_preview_object(new_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed refreshing preview object", exc_info=True)
                ui_reports.append(self._ui_report("WARNING", "Planetka preview object refresh failed."))
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed refreshing preview object", exc_info=True)
                ui_reports.append(self._ui_report("WARNING", "Planetka preview object refresh failed."))
            phase_post_preview_ms = (time.perf_counter() - phase_start) * 1000.0

        cloud_optimized, cloud_failed, phase_cloud_optimize_ms = _optimize_enabled_clouds_for_resolve(
            scene,
            props,
            texture_quality_mode=texture_quality_mode,
        )
        if int(cloud_failed) > 0:
            ui_reports.append(self._ui_report("WARNING", "One or more clouds could not be optimized for this camera view."))

        return ResolveFinalizeResult(
            phase_post_ms=phase_post_delete_ms + phase_post_mark_ms + phase_post_preview_ms + phase_cloud_optimize_ms,
            phase_post_delete_ms=phase_post_delete_ms,
            phase_post_mark_ms=phase_post_mark_ms,
            phase_post_preview_ms=phase_post_preview_ms,
            phase_cloud_optimize_ms=phase_cloud_optimize_ms,
            cloud_optimize_optimized=int(cloud_optimized),
            cloud_optimize_failed=int(cloud_failed),
            missing_node_images=_count_missing_tile_loading_images(material_name="Planetka Earth Material"),
        )

    def _store_manual_resolve_summary(
        self,
        scene,
        tiles,
        normalized,
        texture_quality_mode,
        resolve_total_ms,
        downloaded_bytes,
    ):
        try:
            summary_total_bytes = int(
                max(
                    0,
                    int(
                        _estimate_download_bytes_for_visible_tiles(
                            tiles,
                            normalized,
                            texture_quality_mode=texture_quality_mode,
                        )
                        or 0
                    ),
                )
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            summary_total_bytes = int(max(0, int(downloaded_bytes)))
        _store_resolve_summary(
            scene,
            int(max(0, int(len(tiles)))),
            int(max(0, int(summary_total_bytes))),
            float(max(0.0, float(resolve_total_ms) / 1000.0)),
            log_label="Planetka: failed storing manual resolve summary stats",
        )
        

    def execute(self, context):
        resolve_start = time.perf_counter()
        ui_reports = []
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

        prepare_ctx = self._phase_prepare_context(context)
        self._flush_ui_reports(getattr(prepare_ctx, "ui_reports", ()))
        if getattr(prepare_ctx, "response", None) is not None:
            return prepare_ctx.response
        scene = prepare_ctx.scene
        props = prepare_ctx.props
        prefs = prepare_ctx.prefs
        normalized = str(prepare_ctx.normalized or "")
        manual_summary_requested = bool(prepare_ctx.manual_summary_requested)
        force_empty_once = bool(prepare_ctx.force_empty_once)
        earth_surface = prepare_ctx.earth_surface
        target_surface_name = str(prepare_ctx.target_surface_name or "Planetka Earth Surface")
        tile_utils = prepare_ctx.tile_utils
        phase_assets_ms = float(prepare_ctx.phase_assets_ms or 0.0)

        select_ctx = self._phase_select_tiles(scene, props, tile_utils, force_empty_once)
        self._flush_ui_reports(getattr(select_ctx, "ui_reports", ()))
        if getattr(select_ctx, "response", None) is not None:
            return select_ctx.response
        tiles = list(select_ctx.tiles or ())
        full_source_tiles = list(select_ctx.full_source_tiles or ())
        texture_quality_mode = str(select_ctx.texture_quality_mode or "PREVIEW")
        nav_latitude_deg = float(select_ctx.nav_latitude_deg or 0.0)
        nav_longitude_deg = float(select_ctx.nav_longitude_deg or 0.0)
        nav_altitude_km = float(select_ctx.nav_altitude_km or 0.0)
        phase_tile_select_ms = float(select_ctx.phase_tile_select_ms or 0.0)


        early_result = self._phase_handle_panorama_or_defer(
            context,
            scene,
            props,
            tiles,
            full_source_tiles,
            texture_quality_mode,
            normalized,
        )
        self._flush_ui_reports(getattr(early_result, "ui_reports", ()))
        if getattr(early_result, "response", None) is not None:
            return early_result.response

        streaming_feature = "panorama" if _scene_uses_equirectangular_panorama(scene) else ""
        explicit_feature = str(getattr(self, "streaming_feature", "") or "").strip().lower()
        if explicit_feature:
            streaming_feature = explicit_feature
        stream_ctx = self._phase_prepare_streaming(
            scene,
            tiles,
            normalized,
            texture_quality_mode,
            nav_latitude_deg,
            nav_longitude_deg,
            nav_altitude_km,
            capture_download_progress=bool(getattr(self, "capture_download_progress", True)),
            feature=streaming_feature,
        )
        self._flush_ui_reports(getattr(stream_ctx, "ui_reports", ()))
        if getattr(stream_ctx, "response", None) is not None:
            return stream_ctx.response
        resolved_paths = dict(stream_ctx.resolved_paths or {})
        resolved_tiles_override = stream_ctx.resolved_tiles_override
        ocean_tiles_override = stream_ctx.ocean_tiles_override
        full_quality_cost_bytes = int(stream_ctx.full_quality_cost_bytes or 0)
        download_capture = dict(stream_ctx.download_capture or {})
        phase_stream_ms = float(stream_ctx.phase_stream_ms or 0.0)

        build_ctx = self._phase_build_surface(
            scene,
            earth_surface,
            target_surface_name,
            tiles,
            resolved_paths,
            resolved_tiles_override,
            ocean_tiles_override,
        )
        self._flush_ui_reports(getattr(build_ctx, "ui_reports", ()))
        if getattr(build_ctx, "response", None) is not None:
            return build_ctx.response
        new_obj = build_ctx.new_obj
        shader_result = dict(build_ctx.shader_result or {})
        old_surface_viewport_hidden = bool(build_ctx.old_surface_viewport_hidden)
        old_surface_render_hidden = bool(build_ctx.old_surface_render_hidden)
        phase_mesh_ms = float(build_ctx.phase_mesh_ms or 0.0)
        phase_shader_ms = float(build_ctx.phase_shader_ms or 0.0)
        target_surface_name = str(build_ctx.target_surface_name or target_surface_name)

        finalize_ctx = self._phase_finalize_surface(
            scene=scene,
            props=props,
            new_obj=new_obj,
            target_surface_name=target_surface_name,
            old_surface_viewport_hidden=old_surface_viewport_hidden,
            old_surface_render_hidden=old_surface_render_hidden,
            resolved_paths=resolved_paths,
            force_empty_once=force_empty_once,
            tiles=tiles,
            ui_reports=ui_reports,
            texture_quality_mode=texture_quality_mode,
        )
        phase_post_ms = float(finalize_ctx.phase_post_ms or 0.0)
        phase_post_delete_ms = float(finalize_ctx.phase_post_delete_ms or 0.0)
        phase_post_mark_ms = float(finalize_ctx.phase_post_mark_ms or 0.0)
        phase_post_preview_ms = float(finalize_ctx.phase_post_preview_ms or 0.0)
        phase_cloud_optimize_ms = float(finalize_ctx.phase_cloud_optimize_ms or 0.0)
        missing_node_images = int(finalize_ctx.missing_node_images or 0)

        if not (force_empty_once and len(tiles) == 0):
            ui_reports.append(self._ui_report("INFO", f"Planetka resolved ({len(tiles)} tiles)"))
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
                "cloud_optimize_ms": phase_cloud_optimize_ms,
                "cloud_optimize_optimized": int(finalize_ctx.cloud_optimize_optimized or 0),
                "cloud_optimize_failed": int(finalize_ctx.cloud_optimize_failed or 0),
                "unaccounted_ms": phase_unaccounted_ms,
                "required_mpp_m": required_mpp,
                "resolution_safety": resolution_safety,
                "loaded_textures_mb": loaded_textures_mb,
                "download_ms": downloaded_ms,
                "download_thread_ms": downloaded_thread_ms,
                "downloaded_mb": downloaded_mb,
                "full_quality_cost_bytes": int(max(0, int(full_quality_cost_bytes or 0))),
            },
        )
        if manual_summary_requested:
            self._store_manual_resolve_summary(
                scene=scene,
                tiles=tiles,
                normalized=normalized,
                texture_quality_mode=texture_quality_mode,
                resolve_total_ms=resolve_total_ms,
                downloaded_bytes=downloaded_bytes,
            )

        if int(missing_node_images) > 0:
            logger.debug(
                "Planetka: detected %d texture node(s) without image assignment after resolve.",
                int(missing_node_images),
            )
        shader_missing_texture_count = 0
        if isinstance(shader_result, dict):
            try:
                shader_missing_texture_count = int(shader_result.get("missing_texture_count", 0) or 0)
            except (TypeError, ValueError):
                shader_missing_texture_count = 0
        if int(shader_missing_texture_count) > 0:
            logger.debug(
                "Planetka: detected %d missing tile texture assignment(s) after resolve.",
                int(shader_missing_texture_count),
            )
        if int(shader_missing_texture_count) > 0:
            # Missing texture assignments here usually mean fallback textures were applied
            # (expected when EL/WT/PO assets are unavailable for a tile).
            logger.debug(
                "Planetka: resolve used fallback textures (missing_texture_assignments=%d).",
                int(shader_missing_texture_count),
            )
        integrity_issues = _validate_resolve_completion_integrity(
            scene=scene,
            earth_surface=new_obj,
            requested_tiles=tiles,
            shader_result=shader_result,
            missing_node_images=missing_node_images,
        )
        if integrity_issues:
            for issue in integrity_issues:
                logger.error("Planetka resolve integrity detail: %s", str(issue))
            integrity_message = (
                "Planetka resolve integrity check failed: "
                f"{str(integrity_issues[0] or '').strip() or 'Unknown integrity issue.'}"
            )
            coded_integrity_message = with_error_code(ErrorCode.RESOLVE_REFRESH_FAILED, integrity_message)
            _store_last_resolve_error(
                scene,
                coded_integrity_message,
                "failed storing integrity resolve error on scene",
            )
            _set_resolve_failure_notice(scene, integrity_message)
            user_message = "Resolve failed. Please click Resolve Planetka"
            self._flush_ui_reports(ui_reports)
            return fail(
                self,
                user_message,
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )

        try:
            if "planetka_last_resolve_error" in scene:
                del scene["planetka_last_resolve_error"]
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed clearing resolve error marker after successful resolve", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed clearing resolve error marker after successful resolve", exc_info=True)
        _clear_resolve_failure_notice(scene)
        _clear_camera_inside_earth_warning(scene)
        try:
            resolved_quality_mode = _normalize_texture_quality_mode(texture_quality_mode)
            scene[LAST_RESOLVE_TEXTURE_QUALITY_MODE_KEY] = resolved_quality_mode
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed storing last resolved texture quality state", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed storing last resolved texture quality state", exc_info=True)
        mark_resolve_clean_after_resolve(scene)

        self._flush_ui_reports(ui_reports)
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
