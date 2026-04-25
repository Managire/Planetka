import bpy
import importlib
import json
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
from .asset_builder import (
    EARTH_MATERIAL_NAME,
    PLANETKA_ROOT_OBJECT_NAME,
    SURFACE_GRADING_GROUP_NAME,
    ensure_earth_surface_parent,
    ensure_planetka_assets,
    ensure_planetka_root,
)
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import (
    get_earth_object,
    get_prefs,
    mark_earth_object,
    read_saved_locations,
    write_saved_locations,
)
from .operator_utils import ErrorCode, fail, require_planetka_props, require_scene
from .sanity_utils import (
    _normalize_texture_source_path,
    invalidate_texture_source_health_cache,
    validate_known_good_texture_source,
)
from .r2_source import (
    get_download_progress,
    is_download_active,
    is_remote_source_configured,
    texture_file_exists,
)
from .state import (
    ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY,
    _apply_sunlight_from_props,
    _apply_sunlight_strength_from_props,
    _is_render_job_active,
    cleanup_planetka_unused_data,
    _initialize_props_from_imported_planetka,
    _sync_idprops_from_props,
    delete_temp_meshes,
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
_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY = "planetka_skip_camera_changes_on_create_earth"
_DEFAULT_SCENE_REMOVED_KEY = "planetka_default_scene_removed"
_PLANETKA_CREATE_CAMERA_NAME = "Planetka Camera"
_PLANETKA_RUNTIME_NAME_PREFIX = "Planetka"
_PLANETKA_STANDALONE_NAME_PREFIX = "PlanetkaStandalone"
_STARTUP_SETUP_PROFILE_VERSION = 1
_STARTUP_PROFILE_PROP_NAMES = (
    "nav_longitude_deg",
    "nav_latitude_deg",
    "nav_altitude_km",
    "nav_azimuth_deg",
    "nav_tilt_deg",
    "nav_roll_deg",
    "nav_focal_length_mm",
    "nav_custom_preset_altitude_km",
    "sunlight_longitude_deg",
    "sunlight_strength",
    "sunlight_seasonal_tilt_deg",
    "earth_radius_bu",
    "show_earth_preview",
    "auto_resolve",
    "auto_resolve_idle_sec",
    "auto_adjust_clipping_values",
    "auto_black_background_new_files",
    "viewport_opt_suspend_subdivision",
    "viewport_opt_subdivision_restore_delay_sec",
    "texture_quality_mode",
    "anim_camera_preset",
    "anim_frame_start",
    "anim_frame_end",
    "anim_motion_curve",
    "anim_start_altitude_km",
    "anim_end_altitude_km",
    "anim_orbit_degrees",
    "anim_circle_direction",
    "anim_flyby_degrees",
    "anim_flyby_camera_heading_deg",
    "anim_zoom_rotate_degrees",
    "anim_ab_a_location",
    "anim_ab_a_rotation",
    "anim_ab_a_valid",
    "anim_ab_a_capture_frame",
    "anim_ab_a_capture_timecode",
    "anim_ab_b_location",
    "anim_ab_b_rotation",
    "anim_ab_b_valid",
    "anim_ab_b_capture_frame",
    "anim_ab_b_capture_timecode",
)
_STARTUP_PROFILE_FACTORY_PROP_VALUES = {
    # Create Earth baseline defaults (pre-startup-profile behavior).
    "nav_longitude_deg": 15.0,
    "nav_latitude_deg": 46.0,
    "nav_altitude_km": 6000.0,
    "nav_azimuth_deg": 0.0,
    "nav_tilt_deg": 25.0,
    "nav_roll_deg": 0.0,
    "nav_focal_length_mm": 50.0,
    "nav_custom_preset_altitude_km": 6000.0,
    # Mid-morning at default Create Earth location (lat=46, lon=15).
    "sunlight_longitude_deg": 70.21390025528626,
    "sunlight_strength": 10.0,
    "sunlight_seasonal_tilt_deg": 23.44,
    "earth_radius_bu": 2.0,
    "show_earth_preview": True,
    "auto_resolve": True,
    "auto_resolve_idle_sec": 0.5,
    "auto_adjust_clipping_values": True,
    "auto_black_background_new_files": True,
    "viewport_opt_suspend_subdivision": True,
    "viewport_opt_subdivision_restore_delay_sec": 0.5,
    "texture_quality_mode": "PREVIEW",
    "anim_camera_preset": "NONE",
    "anim_frame_start": 1,
    "anim_frame_end": 250,
    "anim_motion_curve": "LINEAR",
    "anim_start_altitude_km": 100.0,
    "anim_end_altitude_km": 400.0,
    "anim_orbit_degrees": 120.0,
    "anim_circle_direction": "CLOCKWISE",
    "anim_flyby_degrees": 1.0,
    "anim_flyby_camera_heading_deg": 0.0,
    "anim_zoom_rotate_degrees": 20.0,
    "anim_ab_a_location": [0.0, 0.0, 0.0],
    "anim_ab_a_rotation": [0.0, 0.0, 0.0],
    "anim_ab_a_valid": False,
    "anim_ab_a_capture_frame": 0,
    "anim_ab_a_capture_timecode": "",
    "anim_ab_b_location": [0.0, 0.0, 0.0],
    "anim_ab_b_rotation": [0.0, 0.0, 0.0],
    "anim_ab_b_valid": False,
    "anim_ab_b_capture_frame": 0,
    "anim_ab_b_capture_timecode": "",
}
_SURFACE_GRADING_FACTORY_VALUES = {
    # Canonical Create Earth defaults from Planetka Earth Material node defaults.
    # Keep this static and explicit for predictable reset behavior.
    "Surface Brightness": 2.0,
    "Surface Saturation": 1.0,
    "Roughness": 0.4,
    "IOR": 1.333,
    "Hue": 0.5,
    "Saturation": 1.0,
    "Brightness": 0.5,
    "Coefficient": 1.0,
    "Water Texture Strength": 0.5,
    "Intensity": 1.0,
    "Color Temperature": 4500.0,
    "Night Terminator Shift": 0.0,
    "Water Waves On/Off": 0.0,
    "Snow On/Off": 0.0,
    "Snow Line (m)": 3000.0,
    "Waves Density Coefficient": 2.0,
    "Waves Height Coefficient": 0.75,
}

_SURFACE_GRADING_SECTION_SOCKET_NAMES = {
    "GLOBAL": {
        "surface brightness",
        "surface saturation",
    },
    "WATER": {
        "roughness",
        "ior",
        "hue",
        "saturation",
        "brightness",
    },
    "ELEVATION": {
        "coefficient",
    },
    "NIGHT": {
        "intensity",
        "color temperature",
        "night terminator shift",
    },
}

try:
    _PLANETKA_RECOVERABLE_TUPLE = tuple(PLANETKA_RECOVERABLE_EXCEPTIONS)
except TypeError:
    _PLANETKA_RECOVERABLE_TUPLE = (PLANETKA_RECOVERABLE_EXCEPTIONS,)

_REBUILD_EXCEPTIONS = _PLANETKA_RECOVERABLE_TUPLE + (
    RuntimeError,
    TypeError,
    ValueError,
    AttributeError,
    OSError,
)


def _profile_value_to_json(value):
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_profile_value_to_json(v) for v in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _property_default_value(owner, prop_name):
    if owner is None or not hasattr(owner, "bl_rna"):
        return None
    try:
        prop = owner.bl_rna.properties.get(prop_name)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        prop = None
    if prop is None:
        return None
    try:
        if hasattr(prop, "default_array"):
            arr = tuple(float(v) for v in prop.default_array)
            if arr:
                return arr
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        return prop.default
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _normalize_startup_texture_quality_mode(value):
    token = str(value or "").strip().upper()
    if token not in {"PREVIEW", "BALANCED", "FULL"}:
        token = "PREVIEW"
    return token


def _iter_surface_grading_nodes():
    material = bpy.data.materials.get(str(EARTH_MATERIAL_NAME or "Planetka Earth Material"))
    if material is None or getattr(material, "node_tree", None) is None:
        return ()
    nodes = getattr(material.node_tree, "nodes", None)
    if nodes is None:
        return ()
    out = []
    for node in nodes:
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        node_group = getattr(node, "node_tree", None)
        if str(getattr(node_group, "name", "")) == str(SURFACE_GRADING_GROUP_NAME or "Planetka Surface Grading Group"):
            out.append(node)
    return tuple(out)


def _iter_surface_grading_input_sockets(node):
    for socket in getattr(node, "inputs", ()):
        if bool(getattr(socket, "is_linked", False)):
            continue
        if not hasattr(socket, "default_value"):
            continue
        socket_type = str(getattr(socket, "bl_socket_idname", "")).strip()
        if socket_type in {"NodeSocketShader", "NodeSocketVirtual"}:
            continue
        yield socket


def _serialize_surface_grading_values():
    for node in _iter_surface_grading_nodes():
        values = {}
        for socket in _iter_surface_grading_input_sockets(node):
            key = str(getattr(socket, "name", "")).strip()
            if not key:
                continue
            try:
                value = getattr(socket, "default_value")
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                continue
            encoded = _profile_value_to_json(value)
            if encoded is None:
                continue
            values[key] = encoded
        if values:
            return values
    return {}


def _surface_grading_factory_values():
    # Use only explicit canonical defaults; no runtime graph/interface probing.
    defaults = {
        str(name): _profile_value_to_json(value)
        for name, value in _SURFACE_GRADING_FACTORY_VALUES.items()
    }
    defaults = {k: v for k, v in defaults.items() if v is not None}
    return defaults


def _apply_surface_grading_values(values):
    if not isinstance(values, dict) or not values:
        return
    for node in _iter_surface_grading_nodes():
        for socket in _iter_surface_grading_input_sockets(node):
            socket_name = str(getattr(socket, "name", "")).strip()
            if not socket_name or socket_name not in values:
                continue
            raw_value = values.get(socket_name)
            try:
                if isinstance(raw_value, (list, tuple)):
                    socket.default_value = tuple(raw_value)
                else:
                    socket.default_value = raw_value
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed applying surface grading default for '%s'", socket_name, exc_info=True)


def _build_factory_startup_setup_profile(scene, props):
    profile_props = {}
    for prop_name in _STARTUP_PROFILE_PROP_NAMES:
        if prop_name in _STARTUP_PROFILE_FACTORY_PROP_VALUES:
            default_value = _STARTUP_PROFILE_FACTORY_PROP_VALUES[prop_name]
        else:
            default_value = _property_default_value(props, prop_name)
        encoded = _profile_value_to_json(default_value)
        if encoded is None:
            continue
        profile_props[prop_name] = encoded
    # Keep Texture Quality explicitly pinned in the startup profile payload.
    profile_props["texture_quality_mode"] = _normalize_startup_texture_quality_mode(
        profile_props.get("texture_quality_mode", "PREVIEW")
    )

    return {
        "version": int(_STARTUP_SETUP_PROFILE_VERSION),
        "props": profile_props,
        "root": {
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
        },
        "surface_grading": _surface_grading_factory_values(),
    }


def _serialize_current_startup_setup_profile(scene, props):
    profile_props = {}
    for prop_name in _STARTUP_PROFILE_PROP_NAMES:
        if not hasattr(props, prop_name):
            continue
        try:
            raw_value = getattr(props, prop_name)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            continue
        encoded = _profile_value_to_json(raw_value)
        if encoded is None:
            continue
        profile_props[prop_name] = encoded
    # Texture Quality must be part of saved startup setup.
    if hasattr(props, "texture_quality_mode"):
        try:
            profile_props["texture_quality_mode"] = _normalize_startup_texture_quality_mode(
                getattr(props, "texture_quality_mode", "PREVIEW")
            )
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            profile_props["texture_quality_mode"] = "PREVIEW"

    root_data = {
        "location": [0.0, 0.0, 0.0],
        "rotation_euler": [0.0, 0.0, 0.0],
    }
    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    if root is not None:
        try:
            root_data["location"] = [float(root.location.x), float(root.location.y), float(root.location.z)]
            root_data["rotation_euler"] = [
                float(root.rotation_euler.x),
                float(root.rotation_euler.y),
                float(root.rotation_euler.z),
            ]
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed serializing Planetka Root transform", exc_info=True)

    return {
        "version": int(_STARTUP_SETUP_PROFILE_VERSION),
        "props": profile_props,
        "root": root_data,
        "surface_grading": _serialize_surface_grading_values(),
    }


def _load_saved_startup_setup_profile(prefs):
    if prefs is None:
        return None
    raw = str(getattr(prefs, "startup_setup_profile_json", "") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _store_startup_setup_profile(prefs, profile):
    if prefs is None:
        return False
    if not profile:
        try:
            prefs.startup_setup_profile_json = ""
            return True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            return False
    try:
        prefs.startup_setup_profile_json = json.dumps(profile, separators=(",", ":"))
        return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _apply_startup_setup_profile(scene, props, profile, apply_navigation_shot=True):
    if scene is None or props is None or not isinstance(profile, dict):
        return False

    prop_values = profile.get("props")
    if isinstance(prop_values, dict):
        nav_suspended = False
        try:
            suspend_navigation_shot_updates()
            nav_suspended = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            nav_suspended = False

        for prop_name in _STARTUP_PROFILE_PROP_NAMES:
            if prop_name not in prop_values or not hasattr(props, prop_name):
                continue
            raw_value = prop_values.get(prop_name)
            try:
                if isinstance(raw_value, list):
                    setattr(props, prop_name, tuple(raw_value))
                else:
                    setattr(props, prop_name, raw_value)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed applying startup setup prop '%s'", prop_name, exc_info=True)

        # Apply Texture Quality again after bulk assignment to avoid callback/order side effects.
        if hasattr(props, "texture_quality_mode"):
            try:
                desired_mode = _normalize_startup_texture_quality_mode(
                    prop_values.get("texture_quality_mode", "PREVIEW")
                )
                props.texture_quality_mode = desired_mode
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed applying startup setup texture quality mode", exc_info=True)

        if nav_suspended:
            try:
                resume_navigation_shot_updates()
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed resuming navigation shot updates", exc_info=True)

        # Apply navigation shot once after bulk prop assignment so camera/anchor reflect
        # saved startup values before Resolve runs.
        scene_camera = getattr(scene, "camera", None) if scene is not None else None
        if (
            bool(apply_navigation_shot)
            and get_earth_object() is not None
            and scene_camera is not None
            and getattr(scene_camera, "type", "") == 'CAMERA'
        ):
            try:
                nav_result = bpy.ops.planetka.navigation_apply_shot(
                    silent=True,
                    force_camera_view=False,
                )
                if 'FINISHED' not in set(nav_result):
                    logger.debug("Planetka: startup navigation_apply_shot returned %s", nav_result)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed applying startup navigation shot", exc_info=True)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed applying startup navigation shot", exc_info=True)

        # Sunlight values are profile-critical for first Resolve preview; apply explicitly
        # in case property update callbacks were skipped while applying startup values.
        try:
            _apply_sunlight_from_props(scene)
            _apply_sunlight_strength_from_props(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed applying startup sunlight", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed applying startup sunlight", exc_info=True)

    root_values = profile.get("root")
    if isinstance(root_values, dict):
        root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
        if root is not None:
            location = root_values.get("location")
            rotation = root_values.get("rotation_euler")
            try:
                if isinstance(location, (list, tuple)) and len(location) >= 3:
                    root.location = (float(location[0]), float(location[1]), float(location[2]))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed applying startup root location", exc_info=True)
            try:
                if isinstance(rotation, (list, tuple)) and len(rotation) >= 3:
                    root.rotation_euler = (float(rotation[0]), float(rotation[1]), float(rotation[2]))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed applying startup root rotation", exc_info=True)

    grading_values = profile.get("surface_grading")
    if isinstance(grading_values, dict):
        _apply_surface_grading_values(grading_values)

    try:
        _sync_idprops_from_props(scene)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed syncing startup setup idprops", exc_info=True)

    return True


def _apply_startup_setup_for_create_earth(scene, props):
    prefs = get_prefs()
    profile = _load_saved_startup_setup_profile(prefs)
    apply_navigation_shot = False
    if profile is None:
        profile = _build_factory_startup_setup_profile(scene, props)
    try:
        if bool(scene.get(_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY, False)):
            apply_navigation_shot = False
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed reading create-earth camera-skip flag", exc_info=True)

    applied = _apply_startup_setup_profile(
        scene,
        props,
        profile,
        apply_navigation_shot=apply_navigation_shot,
    )
    # Create Earth must always start with no animation preset selected.
    # Do not inherit a previously saved preset (for example "Circle").
    try:
        if hasattr(props, "anim_camera_preset"):
            props.anim_camera_preset = "NONE"
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed forcing animation preset to Select Preset on Create Earth", exc_info=True)
    return applied


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


def _validate_create_earth_texture_source(base_path):
    normalized = _normalize_texture_source_path(base_path)
    if is_remote_source_configured(normalized):
        return normalized, ""
    details = validate_known_good_texture_source(normalized)
    normalized = str(details.get("normalized_path", "") or normalized)
    issues = list(details.get("issues", ()) or ())
    for level, _code, message in issues:
        if str(level).upper() == "ERROR":
            return "", str(message or "Unsupported local data path is invalid.")
    return normalized, ""


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


def _is_default_world_shader(scene):
    if scene is None:
        return False
    world = getattr(scene, "world", None)
    if world is None:
        return False
    if str(getattr(world, "name", "") or "") != "World":
        return False
    node_tree = getattr(world, "node_tree", None)
    if node_tree is None:
        return False
    nodes = getattr(node_tree, "nodes", None)
    links = getattr(node_tree, "links", None)
    if nodes is None or links is None:
        return False

    background = nodes.get("Background")
    output = nodes.get("World Output")
    if background is None or output is None:
        return False
    if str(getattr(background, "bl_idname", "")) != "ShaderNodeBackground":
        return False
    if str(getattr(output, "bl_idname", "")) != "ShaderNodeOutputWorld":
        return False
    if len(tuple(nodes)) != 2:
        return False
    if len(tuple(links)) != 1:
        return False

    surface_input = output.inputs.get("Surface")
    color_socket = background.inputs[0] if len(background.inputs) > 0 else None
    strength_socket = background.inputs[1] if len(background.inputs) > 1 else None
    if surface_input is None or color_socket is None or strength_socket is None:
        return False
    if not bool(getattr(surface_input, "is_linked", False)):
        return False

    color = getattr(color_socket, "default_value", None)
    if color is None or len(color) < 4:
        return False
    default_gray = 0.050876
    return bool(
        _float_close(color[0], default_gray)
        and _float_close(color[1], default_gray)
        and _float_close(color[2], default_gray)
        and _float_close(color[3], 1.0)
        and _float_close(getattr(strength_socket, "default_value", 1.0), 1.0)
    )


def _is_pristine_default_scene(scene):
    if scene is None:
        return False
    try:
        scene_objects = tuple(getattr(scene, "objects", ()))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        return False
    if len(scene_objects) != 3:
        return False
    required = {
        "Cube": "MESH",
        "Camera": "CAMERA",
        "Light": "LIGHT",
    }
    scene_names = {str(getattr(obj, "name", "")) for obj in scene_objects}
    if scene_names != set(required.keys()):
        return False
    for name, expected_type in required.items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj not in scene_objects:
            return False
        if str(getattr(obj, "type", "")) != expected_type:
            return False

    root_collection = getattr(scene, "collection", None)
    if root_collection is None:
        return False
    children = tuple(getattr(root_collection, "children", ()))
    if len(children) != 1:
        return False
    child = children[0]
    if str(getattr(child, "name", "")) != "Collection":
        return False
    child_names = {str(getattr(obj, "name", "")) for obj in tuple(getattr(child, "objects", ()))}
    if child_names != set(required.keys()):
        return False
    if not _is_default_world_shader(scene):
        return False
    return True


def _cleanup_pristine_default_scene(scene):
    if not _is_pristine_default_scene(scene):
        return False

    removed_any = False
    for object_name in ("Cube", "Camera", "Light"):
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_any = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-OPS-027", f"Failed removing default object '{object_name}'")

    default_collection = bpy.data.collections.get("Collection")
    root_collection = getattr(scene, "collection", None)
    if default_collection is not None and root_collection is not None:
        try:
            if (
                default_collection in tuple(getattr(root_collection, "children", ()))
                and len(tuple(getattr(default_collection, "objects", ()))) == 0
                and len(tuple(getattr(default_collection, "children", ()))) == 0
            ):
                root_collection.children.unlink(default_collection)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-OPS-028", "Failed unlinking default collection from scene root")
        try:
            if (
                len(tuple(getattr(default_collection, "users_scene", ()))) == 0
                and len(tuple(getattr(default_collection, "users_collection", ()))) == 0
            ):
                bpy.data.collections.remove(default_collection)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-OPS-029", "Failed deleting empty default collection")

    world = getattr(scene, "world", None)
    if world is not None and _is_default_world_shader(scene):
        try:
            scene.world = None
            removed_any = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-OPS-062", "Failed unlinking default World shader from scene")
        try:
            if int(getattr(world, "users", 0) or 0) == 0:
                bpy.data.worlds.remove(world)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once("PKA-OPS-063", "Failed removing default World datablock")

    return removed_any


def _pick_scene_camera(scene, context=None):
    if scene is None:
        return None

    camera = getattr(scene, "camera", None)
    if camera is not None and getattr(camera, "type", None) == 'CAMERA':
        return camera

    active_obj = None
    try:
        view_layer = getattr(context, "view_layer", None) if context is not None else None
        active_obj = getattr(view_layer.objects, "active", None) if view_layer is not None else None
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        active_obj = None
    if active_obj is not None and getattr(active_obj, "type", None) == 'CAMERA':
        try:
            if active_obj in tuple(getattr(scene, "objects", ())):
                scene.camera = active_obj
                return active_obj
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass

    for obj in tuple(getattr(scene, "objects", ())):
        if getattr(obj, "type", None) == 'CAMERA':
            try:
                scene.camera = obj
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                pass
            return obj

    return None


def _is_planetka_create_camera(obj):
    if obj is None or str(getattr(obj, "type", "")) != "CAMERA":
        return False
    try:
        if str(getattr(obj, "name", "") or "").startswith(_PLANETKA_CREATE_CAMERA_NAME):
            return True
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        return str(obj.get("planetka_role", "") or "").strip().lower() == "camera"
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _ensure_planetka_create_camera(scene):
    if scene is None:
        return None

    camera_obj = None
    named = bpy.data.objects.get(_PLANETKA_CREATE_CAMERA_NAME)
    if named is not None and str(getattr(named, "type", "")) == "CAMERA":
        camera_obj = named

    if camera_obj is None:
        for obj in tuple(getattr(scene, "objects", ())):
            if _is_planetka_create_camera(obj):
                camera_obj = obj
                break

    if camera_obj is None:
        camera_data = bpy.data.cameras.new(f"{_PLANETKA_CREATE_CAMERA_NAME} Data")
        camera_obj = bpy.data.objects.new(_PLANETKA_CREATE_CAMERA_NAME, camera_data)
        scene.collection.objects.link(camera_obj)

    if camera_obj not in tuple(getattr(scene, "objects", ())):
        scene.collection.objects.link(camera_obj)

    try:
        camera_obj["planetka_role"] = "camera"
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed tagging Planetka Camera role", exc_info=True)

    try:
        root = ensure_planetka_root(scene)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        root = None
    if root is not None:
        try:
            world_matrix = camera_obj.matrix_world.copy()
            if getattr(camera_obj, "parent", None) is not root:
                camera_obj.parent = root
                camera_obj.matrix_parent_inverse = root.matrix_world.inverted()
                camera_obj.matrix_world = world_matrix
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed parenting Planetka Camera to Planetka Root", exc_info=True)

    return camera_obj


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


def _ensure_close_clip_limits(scene, min_clip=0.001):
    # Intentionally no-op: Planetka must not modify Camera/Viewport clipping.
    # Users control clip ranges manually.
    _ = scene
    _ = min_clip
    return False, False


def _is_planetka_runtime_name(name):
    try:
        text = str(name or "")
    except (TypeError, ValueError):
        return False
    if not text.startswith(_PLANETKA_RUNTIME_NAME_PREFIX):
        return False
    return not text.startswith(_PLANETKA_STANDALONE_NAME_PREFIX)


def _is_planetka_managed_object(obj):
    if obj is None:
        return False
    try:
        name = str(getattr(obj, "name", "") or "")
    except (TypeError, ValueError):
        name = ""
    if _is_planetka_runtime_name(name):
        return True
    if name in {"Atmosphere - EEVEE supplement", "Atmosphere - Volumetric"}:
        return True
    try:
        role_value = str(obj.get("planetka_role", "") or "").strip()
        if role_value:
            return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    try:
        for key in tuple(obj.keys()):
            if str(key).startswith("planetka_"):
                return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    return False


def _is_planetka_managed_collection(collection):
    if collection is None:
        return False
    try:
        name = str(getattr(collection, "name", "") or "")
    except (TypeError, ValueError):
        name = ""
    if not name:
        return False
    if _is_planetka_runtime_name(name):
        return True
    return name == "Collection Planetka"


def _is_planetka_managed_image(image):
    if image is None:
        return False
    try:
        name = str(getattr(image, "name", "") or "")
        filepath = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").lower()
    except (TypeError, ValueError):
        return False
    if name.startswith(("S2_", "EL_", "WT_", "PO_")):
        return True
    if _is_planetka_runtime_name(name):
        return True
    return (
        "/planetka_cache/" in filepath
        or "\\planetka_cache\\" in filepath
        or "fallback images" in filepath
    )


def _detach_cameras_from_planetka_parents(scene):
    if scene is None:
        return 0
    detached = 0
    for obj in tuple(getattr(scene, "objects", ())):
        if str(getattr(obj, "type", "")) != "CAMERA":
            continue
        parent = getattr(obj, "parent", None)
        if parent is None or not _is_planetka_managed_object(parent):
            continue
        try:
            world_matrix = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = world_matrix
            detached += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed detaching camera from Planetka parent during rebuild", exc_info=True)
    return int(detached)


def _remove_planetka_objects_preserving_cameras():
    removed = 0
    for obj in list(getattr(bpy.data, "objects", ())):
        if str(getattr(obj, "type", "")) == "CAMERA":
            continue
        name = str(getattr(obj, "name", "") or "")
        if not (
            _is_planetka_managed_object(obj)
            or _is_planetka_runtime_name(name)
            or name.startswith("Earth Surface")
        ):
            continue
        try:
            remove_object_and_unused_mesh(obj)
            removed += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed removing object during rebuild", exc_info=True)
    return int(removed)


def _unlink_and_remove_planetka_collections():
    removed = 0
    target_collections = [
        collection
        for collection in list(getattr(bpy.data, "collections", ()))
        if _is_planetka_managed_collection(collection)
    ]
    if not target_collections:
        return 0
    # Remove deeper children first.
    target_collections.sort(key=lambda c: len(tuple(getattr(c, "children_recursive", ()) or ())), reverse=True)

    for collection in target_collections:
        for scene in tuple(getattr(bpy.data, "scenes", ())):
            root = getattr(scene, "collection", None)
            children = getattr(root, "children", None) if root is not None else None
            if children is None:
                continue
            try:
                if str(getattr(collection, "name", "") or "") in children:
                    children.unlink(collection)
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed unlinking Planetka collection from scene root", exc_info=True)

        for parent in tuple(getattr(bpy.data, "collections", ())):
            children = getattr(parent, "children", None)
            if children is None:
                continue
            try:
                if str(getattr(collection, "name", "") or "") in children:
                    children.unlink(collection)
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed unlinking nested Planetka collection", exc_info=True)

        try:
            if int(getattr(collection, "users", 0) or 0) == 0:
                bpy.data.collections.remove(collection)
                removed += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed removing Planetka collection during rebuild", exc_info=True)
    return int(removed)


def _remove_unused_planetka_datablocks():
    counts = {
        "meshes": 0,
        "images": 0,
        "materials": 0,
        "node_groups": 0,
        "lights": 0,
    }

    for mesh_data in list(getattr(bpy.data, "meshes", ())):
        name = str(getattr(mesh_data, "name", "") or "")
        if not (_is_planetka_runtime_name(name) or name.startswith("Earth Surface")):
            continue
        try:
            mesh_data.use_fake_user = False
        except _REBUILD_EXCEPTIONS:
            pass
        try:
            if int(getattr(mesh_data, "users", 0) or 0) == 0:
                bpy.data.meshes.remove(mesh_data)
                counts["meshes"] += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed removing mesh datablock during rebuild", exc_info=True)

    for image in list(getattr(bpy.data, "images", ())):
        if not _is_planetka_managed_image(image):
            continue
        try:
            image.use_fake_user = False
        except _REBUILD_EXCEPTIONS:
            pass
        try:
            if int(getattr(image, "users", 0) or 0) == 0:
                bpy.data.images.remove(image)
                counts["images"] += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed removing image datablock during rebuild", exc_info=True)

    for material in list(getattr(bpy.data, "materials", ())):
        name = str(getattr(material, "name", "") or "")
        if not _is_planetka_runtime_name(name):
            continue
        try:
            material.use_fake_user = False
        except _REBUILD_EXCEPTIONS:
            pass
        try:
            if int(getattr(material, "users", 0) or 0) == 0:
                bpy.data.materials.remove(material)
                counts["materials"] += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed removing material datablock during rebuild", exc_info=True)

    for node_group in list(getattr(bpy.data, "node_groups", ())):
        name = str(getattr(node_group, "name", "") or "")
        if not _is_planetka_runtime_name(name):
            continue
        try:
            node_group.use_fake_user = False
        except _REBUILD_EXCEPTIONS:
            pass
        try:
            if int(getattr(node_group, "users", 0) or 0) == 0:
                bpy.data.node_groups.remove(node_group)
                counts["node_groups"] += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed removing node-group datablock during rebuild", exc_info=True)

    for light_data in list(getattr(bpy.data, "lights", ())):
        name = str(getattr(light_data, "name", "") or "")
        if not _is_planetka_runtime_name(name):
            continue
        try:
            light_data.use_fake_user = False
        except _REBUILD_EXCEPTIONS:
            pass
        try:
            if int(getattr(light_data, "users", 0) or 0) == 0:
                bpy.data.lights.remove(light_data)
                counts["lights"] += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed removing light datablock during rebuild", exc_info=True)

    return counts


def _clear_scene_planetka_runtime_idprops(scene):
    if scene is None:
        return 0
    cleared = 0
    for key in list(getattr(scene, "keys", lambda: ())()):
        if not str(key).startswith("planetka_"):
            continue
        try:
            del scene[key]
            cleared += 1
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed clearing scene Planetka runtime key during rebuild", exc_info=True)
    return int(cleared)


def _snapshot_camera_state_for_rebuild(scene, camera):
    snapshot = {
        "camera_name": "",
        "frame_current": 1,
        "matrix_world": None,
        "collection_names": (),
        "baked_samples": (),
        "had_animation": False,
    }
    if scene is not None:
        try:
            snapshot["frame_current"] = int(getattr(scene, "frame_current", 1) or 1)
        except _REBUILD_EXCEPTIONS:
            snapshot["frame_current"] = 1
    if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
        return snapshot

    snapshot["camera_name"] = str(getattr(camera, "name", "") or "")
    try:
        snapshot["collection_names"] = tuple(
            str(getattr(collection, "name", "") or "")
            for collection in tuple(getattr(camera, "users_collection", ()) or ())
            if str(getattr(collection, "name", "") or "").strip()
        )
    except _REBUILD_EXCEPTIONS:
        snapshot["collection_names"] = ()
    try:
        snapshot["matrix_world"] = camera.matrix_world.copy()
    except _REBUILD_EXCEPTIONS:
        snapshot["matrix_world"] = None

    object_has_animation = bool(
        getattr(getattr(camera, "animation_data", None), "action", None) is not None
    )
    camera_data = getattr(camera, "data", None)
    data_has_animation = bool(
        getattr(getattr(camera_data, "animation_data", None), "action", None) is not None
    )
    snapshot["had_animation"] = bool(object_has_animation or data_has_animation)

    if scene is not None and snapshot["had_animation"]:
        try:
            sample_frame_start = int(getattr(scene, "frame_start", 1) or 1)
            sample_frame_end = int(getattr(scene, "frame_end", sample_frame_start) or sample_frame_start)
        except _REBUILD_EXCEPTIONS:
            sample_frame_start = 1
            sample_frame_end = 1
        if sample_frame_end < sample_frame_start:
            sample_frame_start, sample_frame_end = sample_frame_end, sample_frame_start
        frame_count = int(sample_frame_end - sample_frame_start + 1)
        if frame_count <= 2000:
            samples = []
            stored_frame = int(snapshot.get("frame_current", 1) or 1)
            for frame in range(sample_frame_start, sample_frame_end + 1):
                try:
                    scene.frame_set(int(frame))
                    sample = {
                        "frame": int(frame),
                        "location": tuple(float(v) for v in tuple(getattr(camera, "location", (0.0, 0.0, 0.0)))),
                        "rotation_mode": str(getattr(camera, "rotation_mode", "XYZ") or "XYZ"),
                        "rotation_euler": tuple(float(v) for v in tuple(getattr(camera, "rotation_euler", (0.0, 0.0, 0.0)))),
                        "rotation_quaternion": tuple(
                            float(v) for v in tuple(getattr(camera, "rotation_quaternion", (1.0, 0.0, 0.0, 0.0)))
                        ),
                        "scale": tuple(float(v) for v in tuple(getattr(camera, "scale", (1.0, 1.0, 1.0)))),
                    }
                    if camera_data is not None:
                        sample["lens"] = float(getattr(camera_data, "lens", 50.0) or 50.0)
                    samples.append(sample)
                except _REBUILD_EXCEPTIONS:
                    logger.debug("Planetka: failed baking camera sample during rebuild snapshot", exc_info=True)
            try:
                scene.frame_set(stored_frame)
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed restoring frame after camera snapshot bake", exc_info=True)
            snapshot["baked_samples"] = tuple(samples)
        else:
            logger.warning(
                "Planetka rebuild: camera animation range too large for bake-preserve (%d frames). "
                "Falling back to current-frame transform restore.",
                int(frame_count),
            )
    return snapshot


def _snapshot_earth_settings_for_rebuild(scene, props):
    snapshot = {
        "earth_radius_bu": None,
        "root_location": None,
        "root_rotation_euler": None,
        "surface_grading": {},
    }

    if props is not None and hasattr(props, "earth_radius_bu"):
        try:
            snapshot["earth_radius_bu"] = max(1e-6, float(getattr(props, "earth_radius_bu", 2.0)))
        except _REBUILD_EXCEPTIONS:
            snapshot["earth_radius_bu"] = None

    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    if root is not None:
        try:
            snapshot["root_location"] = (
                float(root.location.x),
                float(root.location.y),
                float(root.location.z),
            )
        except _REBUILD_EXCEPTIONS:
            snapshot["root_location"] = None
        try:
            snapshot["root_rotation_euler"] = (
                float(root.rotation_euler.x),
                float(root.rotation_euler.y),
                float(root.rotation_euler.z),
            )
        except _REBUILD_EXCEPTIONS:
            snapshot["root_rotation_euler"] = None

    try:
        grading_values = _serialize_surface_grading_values()
        if isinstance(grading_values, dict):
            snapshot["surface_grading"] = dict(grading_values)
    except _REBUILD_EXCEPTIONS:
        logger.debug("Planetka: failed snapshotting surface grading for rebuild", exc_info=True)

    return snapshot


def _restore_earth_settings_after_rebuild(scene, props, snapshot):
    if not isinstance(snapshot, dict):
        return False

    restored_any = False
    target_radius = snapshot.get("earth_radius_bu", None)
    if target_radius is not None and props is not None and hasattr(props, "earth_radius_bu"):
        try:
            props.earth_radius_bu = max(1e-6, float(target_radius))
            restored_any = True
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed restoring Earth radius after rebuild", exc_info=True)

    root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
    if root is not None:
        root_location = snapshot.get("root_location", None)
        if isinstance(root_location, (tuple, list)) and len(root_location) >= 3:
            try:
                root.location = (
                    float(root_location[0]),
                    float(root_location[1]),
                    float(root_location[2]),
                )
                restored_any = True
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed restoring Planetka Root location after rebuild", exc_info=True)
        root_rotation = snapshot.get("root_rotation_euler", None)
        if isinstance(root_rotation, (tuple, list)) and len(root_rotation) >= 3:
            try:
                root.rotation_euler = (
                    float(root_rotation[0]),
                    float(root_rotation[1]),
                    float(root_rotation[2]),
                )
                restored_any = True
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed restoring Planetka Root rotation after rebuild", exc_info=True)

    grading_values = snapshot.get("surface_grading", {})
    if isinstance(grading_values, dict) and grading_values:
        try:
            _apply_surface_grading_values(grading_values)
            restored_any = True
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed restoring surface grading after rebuild", exc_info=True)

    try:
        _sync_idprops_from_props(scene)
    except _REBUILD_EXCEPTIONS:
        logger.debug("Planetka: failed syncing props after restore in rebuild", exc_info=True)

    return restored_any


def _restore_camera_state_after_rebuild(scene, snapshot):
    if not isinstance(snapshot, dict):
        return False
    camera_name = str(snapshot.get("camera_name", "") or "").strip()
    if not camera_name:
        return False
    camera = bpy.data.objects.get(camera_name)
    if camera is None or str(getattr(camera, "type", "")) != "CAMERA":
        return False

    linked = bool(tuple(getattr(camera, "users_collection", ()) or ()))
    collection_names = tuple(str(name or "").strip() for name in snapshot.get("collection_names", ()) if str(name or "").strip())
    for collection_name in collection_names:
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            continue
        try:
            if str(getattr(camera, "name", "") or "") not in collection.objects:
                collection.objects.link(camera)
            linked = True
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed linking camera back into original collection", exc_info=True)

    if not linked and scene is not None:
        try:
            scene.collection.objects.link(camera)
            linked = True
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed linking camera back into scene root", exc_info=True)
    if not linked:
        return False

    try:
        if scene is not None and getattr(scene, "camera", None) is not camera:
            scene.camera = camera
    except _REBUILD_EXCEPTIONS:
        logger.debug("Planetka: failed restoring active scene camera after rebuild", exc_info=True)

    try:
        matrix_world = snapshot.get("matrix_world", None)
        if matrix_world is not None:
            camera.matrix_world = matrix_world
    except _REBUILD_EXCEPTIONS:
        logger.debug("Planetka: failed restoring camera world matrix after rebuild", exc_info=True)

    baked_samples = tuple(snapshot.get("baked_samples", ()) or ())
    if baked_samples:
        camera_data = getattr(camera, "data", None)
        try:
            if getattr(camera, "animation_data", None) is not None:
                camera.animation_data_clear()
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed clearing camera animation data before restore bake", exc_info=True)
        if camera_data is not None:
            try:
                if getattr(camera_data, "animation_data", None) is not None:
                    camera_data.animation_data_clear()
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed clearing camera data animation before restore bake", exc_info=True)

        for sample in baked_samples:
            try:
                frame = int(sample.get("frame", 1) or 1)
                if scene is not None:
                    scene.frame_set(frame)
                camera.location = tuple(sample.get("location", (0.0, 0.0, 0.0)))
                camera.scale = tuple(sample.get("scale", (1.0, 1.0, 1.0)))
                rotation_mode = str(sample.get("rotation_mode", "XYZ") or "XYZ")
                try:
                    camera.rotation_mode = rotation_mode
                except _REBUILD_EXCEPTIONS:
                    camera.rotation_mode = "XYZ"
                if str(getattr(camera, "rotation_mode", "XYZ")).startswith("QUAT"):
                    camera.rotation_quaternion = tuple(sample.get("rotation_quaternion", (1.0, 0.0, 0.0, 0.0)))
                    camera.keyframe_insert(data_path="rotation_quaternion", frame=frame)
                else:
                    camera.rotation_euler = tuple(sample.get("rotation_euler", (0.0, 0.0, 0.0)))
                    camera.keyframe_insert(data_path="rotation_euler", frame=frame)
                camera.keyframe_insert(data_path="location", frame=frame)
                camera.keyframe_insert(data_path="scale", frame=frame)
                if camera_data is not None and "lens" in sample:
                    camera_data.lens = float(sample.get("lens", 50.0) or 50.0)
                    camera_data.keyframe_insert(data_path="lens", frame=frame)
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed restoring baked camera frame during rebuild", exc_info=True)

    try:
        frame_current = int(snapshot.get("frame_current", 1) or 1)
        if scene is not None:
            scene.frame_set(frame_current)
    except _REBUILD_EXCEPTIONS:
        logger.debug("Planetka: failed restoring frame after rebuild camera restore", exc_info=True)
    return True


def _earth_graph_rebind(scene, earth_surface):
    if scene is None or earth_surface is None:
        return False
    try:
        ensure_planetka_root(scene)
        ensure_earth_surface_parent(scene=scene, earth_surface=earth_surface)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed binding Earth surface to Planetka Root", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka: failed binding Earth surface to Planetka Root", exc_info=True)
    return False


def _earth_graph_create_bootstrap_surface(scene):
    surface_collection = ensure_planetka_temp_collection()
    new_obj = _create_placeholder_surface_object(scene)
    if not new_obj:
        raise RuntimeError("Failed to create bootstrap Earth surface mesh")
    if surface_collection is not None:
        for collection in list(new_obj.users_collection):
            if collection is surface_collection:
                continue
            collection.objects.unlink(new_obj)
        if new_obj.name not in surface_collection.objects:
            surface_collection.objects.link(new_obj)
    delete_temp_meshes(keep_obj=new_obj)
    try:
        new_obj.name = "Planetka Earth Surface"
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    mark_earth_object(new_obj)
    _earth_graph_rebind(scene=scene, earth_surface=new_obj)
    return new_obj


def _earth_graph_cleanup_for_rebuild(scene):
    detached_cameras = 0
    try:
        detached_cameras = _detach_cameras_from_planetka_parents(scene)
    except _REBUILD_EXCEPTIONS:
        detached_cameras = 0
        logger.debug("Planetka: failed detaching cameras during rebuild", exc_info=True)

    try:
        delete_temp_meshes(keep_obj=None)
    except _REBUILD_EXCEPTIONS:
        logger.debug("Planetka: failed clearing temporary meshes during rebuild", exc_info=True)

    removed_objects = _remove_planetka_objects_preserving_cameras()
    removed_collections = _unlink_and_remove_planetka_collections()
    removed_data = _remove_unused_planetka_datablocks()
    scene_keys_cleared = _clear_scene_planetka_runtime_idprops(scene)
    try:
        cleanup_counts = cleanup_planetka_unused_data()
    except _REBUILD_EXCEPTIONS:
        cleanup_counts = {}
        logger.debug("Planetka: failed cleanup pass during rebuild", exc_info=True)

    return {
        "detached_cameras": int(detached_cameras),
        "removed_objects": int(removed_objects),
        "removed_collections": int(removed_collections),
        "removed_data": dict(removed_data or {}),
        "scene_keys_cleared": int(scene_keys_cleared),
        "cleanup_counts": dict(cleanup_counts or {}),
    }


def _earth_graph_restore_after_rebuild(scene, props, earth_settings_snapshot, camera_snapshot):
    _restore_earth_settings_after_rebuild(scene, props, earth_settings_snapshot)
    _restore_camera_state_after_rebuild(scene, camera_snapshot)


def _scene_allows_automatic_clipping(scene):
    if scene is None:
        return False
    allowed_default_names = {"Cube", "Camera", "Light"}
    try:
        scene_objects = tuple(getattr(scene, "objects", ()))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        return False
    for obj in scene_objects:
        try:
            name = str(getattr(obj, "name", "") or "")
        except (TypeError, ValueError):
            name = ""
        if name in allowed_default_names:
            continue
        if _is_planetka_managed_object(obj):
            continue
        return False
    return True


def _clip_limits_for_radius_steps(earth_radius_bu):
    """Map Earth radius to stable clipping ranges using decade steps."""
    try:
        safe_radius = max(1e-9, float(earth_radius_bu))
    except (TypeError, ValueError):
        safe_radius = 1.0
    exponent = math.floor(math.log10(safe_radius))
    scale = math.pow(10.0, exponent)
    clip_start = 0.001 * scale
    clip_end = 1000.0 * scale
    return float(clip_start), float(clip_end)


def _apply_clipping_limits(scene, clip_start, clip_end, notice_text=None):
    if scene is None:
        return False
    if not _scene_allows_automatic_clipping(scene):
        return False
    try:
        new_start = max(1e-9, float(clip_start))
        new_end = max(new_start * 1.000001, float(clip_end))
    except (TypeError, ValueError):
        return False

    changed = False
    camera = getattr(scene, "camera", None)
    camera_data = getattr(camera, "data", None) if camera is not None else None
    if camera_data is not None and str(getattr(camera, "type", "")) == "CAMERA":
        try:
            old_start = float(getattr(camera_data, "clip_start", 0.0))
            old_end = float(getattr(camera_data, "clip_end", 0.0))
            if (not _float_close(old_start, new_start, tol=1e-9)) or (not _float_close(old_end, new_end, tol=1e-9)):
                camera_data.clip_start = float(new_start)
                camera_data.clip_end = float(new_end)
                changed = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass

    try:
        wm = getattr(bpy.context, "window_manager", None)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        wm = None
    if wm is not None:
        for window in tuple(getattr(wm, "windows", ())):
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in tuple(getattr(screen, "areas", ())):
                if str(getattr(area, "type", "")) != "VIEW_3D":
                    continue
                for space in tuple(getattr(area, "spaces", ())):
                    if str(getattr(space, "type", "")) != "VIEW_3D":
                        continue
                    try:
                        old_start = float(getattr(space, "clip_start", 0.0))
                        old_end = float(getattr(space, "clip_end", 0.0))
                        if (not _float_close(old_start, new_start, tol=1e-9)) or (not _float_close(old_end, new_end, tol=1e-9)):
                            space.clip_start = float(new_start)
                            space.clip_end = float(new_end)
                            changed = True
                    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                        continue

    if changed and notice_text:
        try:
            scene["planetka_status_clip_auto_notice"] = str(notice_text)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass
    return bool(changed)


def _format_clip_notice_value(value):
    try:
        val = float(value)
    except (TypeError, ValueError):
        return str(value)
    if _float_close(val, round(val), tol=1e-9):
        ival = int(round(val))
        if abs(ival) >= 1000:
            return f"{ival:,}"
        return str(ival)
    return f"{val:.6g}"


def _clip_notice_text(clip_start, clip_end):
    return (
        "Clipping values adjusted: "
        f"{_format_clip_notice_value(clip_start)} - {_format_clip_notice_value(clip_end)}"
    )


def _apply_create_earth_clipping_defaults(scene):
    changed = _apply_clipping_limits(
        scene,
        0.001,
        1000.0,
        notice_text=None,
    )
    # Create Earth should not surface clipping-adjustment notices.
    try:
        if scene is not None and "planetka_status_clip_auto_notice" in scene:
            del scene["planetka_status_clip_auto_notice"]
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass
    return bool(changed)


def _apply_radius_based_clipping(scene, earth_radius_bu):
    clip_start, clip_end = _clip_limits_for_radius_steps(earth_radius_bu)
    return _apply_clipping_limits(
        scene,
        clip_start,
        clip_end,
        notice_text=_clip_notice_text(clip_start, clip_end),
    )


def _switch_solid_viewports_to_rendered(context):
    switched = False
    wm = getattr(context, "window_manager", None) if context else None
    if wm is None:
        return switched

    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type != 'VIEW_3D':
                    continue
                shading = getattr(space, "shading", None)
                if shading is None:
                    continue
                try:
                    if str(getattr(shading, "type", "")) != "RENDERED":
                        shading.type = 'RENDERED'
                        switched = True
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                    continue
    return switched


def _float_close(value, target, tol=1e-4):
    try:
        return abs(float(value) - float(target)) <= float(tol)
    except (TypeError, ValueError):
        return False


def _set_default_world_background_to_black(scene):
    world = getattr(scene, "world", None) if scene else None
    if world is None:
        return False

    default_gray = 0.050876
    changed = False

    if getattr(world, "node_tree", None) is not None:
        node_tree = getattr(world, "node_tree", None)
        nodes = getattr(node_tree, "nodes", None) if node_tree else None
        background = nodes.get("Background") if nodes else None
        if background is None:
            return False
        color_socket = background.inputs[0] if len(background.inputs) > 0 else None
        strength_socket = background.inputs[1] if len(background.inputs) > 1 else None
        if color_socket is None or strength_socket is None:
            return False

        color = getattr(color_socket, "default_value", None)
        if color is None or len(color) < 4:
            return False
        is_default = (
            _float_close(color[0], default_gray)
            and _float_close(color[1], default_gray)
            and _float_close(color[2], default_gray)
            and _float_close(color[3], 1.0)
            and _float_close(getattr(strength_socket, "default_value", 1.0), 1.0)
        )
        if not is_default:
            return False

        try:
            color_socket.default_value = (0.0, 0.0, 0.0, 1.0)
            changed = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            changed = False
        return changed

    world_color = getattr(world, "color", None)
    if world_color is None or len(world_color) < 3:
        return False
    is_default = (
        _float_close(world_color[0], default_gray)
        and _float_close(world_color[1], default_gray)
        and _float_close(world_color[2], default_gray)
    )
    if not is_default:
        return False
    try:
        world.color = (0.0, 0.0, 0.0)
        changed = True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
        changed = False
    return changed


def _snapshot_view_selection(context):
    view_layer = getattr(context, "view_layer", None) if context is not None else None
    selected_names = []
    active_name = ""
    if view_layer is None:
        return tuple(selected_names), active_name
    try:
        selected_names = [
            str(obj.name)
            for obj in tuple(getattr(context, "selected_objects", ()))
            if getattr(obj, "name", None)
        ]
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        selected_names = []
    try:
        active_obj = getattr(view_layer.objects, "active", None)
        active_name = str(getattr(active_obj, "name", "") or "")
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        active_name = ""
    return tuple(selected_names), active_name


def _restore_view_selection(context, scene, selected_names, active_name):
    view_layer = getattr(context, "view_layer", None) if context is not None else None
    if view_layer is None:
        return

    # Clear current selection first (Planetka setup may have selected helper objects).
    try:
        for obj in tuple(getattr(context, "selected_objects", ())):
            try:
                obj.select_set(False)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                continue
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass

    selected_objs = []
    for name in tuple(selected_names or ()):
        obj = None
        try:
            obj = getattr(scene, "objects", None).get(name) if scene is not None and getattr(scene, "objects", None) is not None else None
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            obj = None
        if obj is None:
            obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            obj.select_set(True)
            selected_objs.append(obj)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            continue

    active_obj = None
    if active_name:
        try:
            active_obj = getattr(scene, "objects", None).get(active_name) if scene is not None and getattr(scene, "objects", None) is not None else None
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            active_obj = None
        if active_obj is None:
            active_obj = bpy.data.objects.get(active_name)
    if active_obj is None and selected_objs:
        active_obj = selected_objs[0]

    try:
        view_layer.objects.active = active_obj
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        pass


def _create_placeholder_surface_object(scene):
    placeholder_mesh = bpy.data.meshes.new("Planetka Earth Surface Placeholder Mesh")
    obj = bpy.data.objects.new("Planetka Earth Surface", placeholder_mesh)
    scene.collection.objects.link(obj)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj["planetka_surface_local_radius"] = 2.0
    # Keep bootstrap surface valid for strict resolve precheck.
    planetka_surface = bpy.data.materials.get("Planetka Earth Material")
    if planetka_surface is not None:
        try:
            obj.data.materials.clear()
            obj.data.materials.append(planetka_surface)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed assigning Earth material to bootstrap surface", exc_info=True)
    return obj


REAL_EARTH_RADIUS_M = 6371000.0
MAX_TERRAIN_HEIGHT_M = 9000.0
MAX_PROXIMITY_TARGET_SAFETY_RATIO = 1.08
DATASET_MPP_BASE_D1 = 10.0
FULL_GLOBE_EXTRA_MARGIN = 1.3
SHOT_ANCHOR_OBJECT_NAME = "Planetka Shot Anchor"
NAV_LAST_APPLIED_KEYS = {
    "lon": "planetka_nav_last_lon_deg",
    "lat": "planetka_nav_last_lat_deg",
    "alt": "planetka_nav_last_altitude_km",
    "heading": "planetka_nav_last_heading_deg",
    "tilt": "planetka_nav_last_tilt_deg",
    "roll": "planetka_nav_last_roll_deg",
}
NAV_CHANGE_EPS = 1e-6
NAV_UI_DECIMALS = 2
NAV_UI_ZERO_EPS = 0.005
NAV_D_LEVELS_BY_Z = {
    1: [1, 2, 4, 8, 15, 30, 60],
    2: [2, 4, 8, 15, 30, 60],
    4: [4, 8, 15, 30, 60],
    8: [8, 15, 30, 60],
    15: [15, 30, 60],
    30: [30, 60, 90, 180, 360],
    60: [60, 90, 180, 360],
    90: [90, 180, 360],
    180: [180, 360, 720],
    360: [360, 720, 1440],
}
_COVERAGE_MAP = None


def _read_last_navigation_values(scene):
    if scene is None:
        return None
    try:
        values = {
            "lon": float(scene.get(NAV_LAST_APPLIED_KEYS["lon"])),
            "lat": float(scene.get(NAV_LAST_APPLIED_KEYS["lat"])),
            "alt": float(scene.get(NAV_LAST_APPLIED_KEYS["alt"])),
            "heading": float(scene.get(NAV_LAST_APPLIED_KEYS["heading"])),
            "tilt": float(scene.get(NAV_LAST_APPLIED_KEYS["tilt"])),
            "roll": float(scene.get(NAV_LAST_APPLIED_KEYS["roll"])),
        }
        return values
    except (TypeError, ValueError, AttributeError):
        return None


def _store_last_navigation_values(scene, lon_deg, lat_deg, altitude_km, heading_deg, tilt_deg, roll_deg):
    if scene is None:
        return
    try:
        scene[NAV_LAST_APPLIED_KEYS["lon"]] = float(lon_deg)
        scene[NAV_LAST_APPLIED_KEYS["lat"]] = float(lat_deg)
        scene[NAV_LAST_APPLIED_KEYS["alt"]] = float(altitude_km)
        scene[NAV_LAST_APPLIED_KEYS["heading"]] = float(heading_deg)
        scene[NAV_LAST_APPLIED_KEYS["tilt"]] = float(tilt_deg)
        scene[NAV_LAST_APPLIED_KEYS["roll"]] = float(roll_deg)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-003", "Failed storing last navigation values to scene idprops")
    except (TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-004", "Failed storing last navigation values to scene idprops")


def _quantize_navigation_ui_value(value, minimum=None):
    try:
        normalized = float(value)
    except (TypeError, ValueError, AttributeError):
        normalized = 0.0
    if minimum is not None:
        try:
            min_value = float(minimum)
            if normalized < min_value:
                normalized = min_value
        except (TypeError, ValueError, AttributeError):
            pass
    quantized = round(float(normalized), int(NAV_UI_DECIMALS))
    if abs(float(quantized)) < float(NAV_UI_ZERO_EPS):
        quantized = 0.0
    return float(quantized)


def _quantize_navigation_ui_payload(
    *,
    lat_deg,
    lon_deg,
    altitude_km,
    heading_deg,
    tilt_deg,
    roll_deg,
    focal_length_mm,
):
    return {
        "lat_deg": _quantize_navigation_ui_value(lat_deg),
        "lon_deg": _quantize_navigation_ui_value(lon_deg),
        "altitude_km": _quantize_navigation_ui_value(altitude_km, minimum=0.0),
        "heading_deg": _quantize_navigation_ui_value(heading_deg),
        "tilt_deg": _quantize_navigation_ui_value(tilt_deg),
        "roll_deg": _quantize_navigation_ui_value(roll_deg),
        "focal_length_mm": _quantize_navigation_ui_value(focal_length_mm, minimum=1.0),
    }


def _get_coverage_map():
    global _COVERAGE_MAP
    if _COVERAGE_MAP is None:
        module_name = f"{__package__}.coverage" if __package__ else "coverage"
        module = importlib.import_module(module_name)
        _COVERAGE_MAP = getattr(module, "COVERAGE", {})
    return _COVERAGE_MAP


def _earth_radius_blender_units(earth_obj):
    if not earth_obj:
        return 1.0

    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0

    if stored_local_radius > 1e-9:
        world_scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
        return stored_local_radius * float(max_scale)

    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    if vertices:
        try:
            local_radius = max(v.co.length for v in vertices)
            if local_radius > 1e-9:
                world_scale = earth_obj.matrix_world.to_scale()
                max_scale = max(abs(world_scale.x), abs(world_scale.y), abs(world_scale.z), 1e-9)
                return float(local_radius) * float(max_scale)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    scale = earth_obj.matrix_world.to_scale()
    return max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)


def _set_planetka_earth_radius_bu(scene, target_radius_bu):
    earth_obj = get_earth_object()
    if earth_obj is None or str(getattr(earth_obj, "type", "")) != "MESH":
        return False

    mesh_data = getattr(earth_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    can_resize_mesh = bool(mesh_data is not None and vertices)

    target_radius = max(1e-6, float(target_radius_bu))

    changed = False
    try:
        sx, sy, sz = (float(v) for v in tuple(getattr(earth_obj, "scale", (1.0, 1.0, 1.0))))
    except (TypeError, ValueError, AttributeError):
        sx, sy, sz = 1.0, 1.0, 1.0
    if not math.isfinite(sx):
        sx = 1.0
    if not math.isfinite(sy):
        sy = 1.0
    if not math.isfinite(sz):
        sz = 1.0

    if can_resize_mesh:
        # Keep object scale neutral and encode size directly in mesh radius.
        if abs(sx - 1.0) > 1e-9 or abs(sy - 1.0) > 1e-9 or abs(sz - 1.0) > 1e-9:
            # Prevent accidental mesh collapse when an axis scale is (near) zero.
            bake_sx = sx if abs(sx) > 1e-6 else 1.0
            bake_sy = sy if abs(sy) > 1e-6 else 1.0
            bake_sz = sz if abs(sz) > 1e-6 else 1.0
            try:
                mesh_data.transform(Matrix.Diagonal((bake_sx, bake_sy, bake_sz, 1.0)))
                earth_obj.scale = (1.0, 1.0, 1.0)
                changed = True
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-OPS-036", "Failed normalizing Earth object scale while applying radius")

        try:
            current_local_radius = max(float(v.co.length) for v in vertices)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            current_local_radius = 0.0

        if current_local_radius <= 1e-9:
            current_local_radius = 1.0

        ratio = float(target_radius) / float(current_local_radius)
        if abs(ratio - 1.0) > 1e-9:
            try:
                mesh_data.transform(Matrix.Scale(float(ratio), 4))
                changed = True
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                _log_recoverable_once("PKA-OPS-037", "Failed scaling Earth mesh to requested radius")

        try:
            mesh_data.update()
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass

    try:
        earth_obj["planetka_surface_local_radius"] = float(target_radius)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-038", "Failed storing Earth local radius metadata")

    try:
        props = getattr(scene, "planetka", None) if scene is not None else None
        preview_exists = bpy.data.objects.get("Planetka Preview Object") is not None
        if preview_exists or bool(getattr(props, "show_earth_preview", False)):
            ensure_preview_object(earth_obj)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-039", "Failed syncing preview radius after Earth radius change")

    # Keep Planetka camera in the same relative navigation shot immediately
    # after radius change (without requiring a manual UI nudge), regardless
    # of which scene camera is currently active.
    try:
        scene_for_camera = scene if isinstance(scene, bpy.types.Scene) else getattr(bpy.context, "scene", None)
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        scene_for_camera = None
    if scene_for_camera is not None:
        previous_scene_camera = None
        camera_swapped = False
        try:
            props = getattr(scene_for_camera, "planetka", None)
            previous_scene_camera = getattr(scene_for_camera, "camera", None)
            planetka_camera = None
            if (
                previous_scene_camera is not None
                and str(getattr(previous_scene_camera, "type", "")) == "CAMERA"
                and _is_planetka_create_camera(previous_scene_camera)
            ):
                planetka_camera = previous_scene_camera
            if planetka_camera is None:
                for obj in tuple(getattr(scene_for_camera, "objects", ())):
                    if (
                        obj is not None
                        and str(getattr(obj, "type", "")) == "CAMERA"
                        and _is_planetka_create_camera(obj)
                    ):
                        planetka_camera = obj
                        break
            if props is not None and planetka_camera is not None:
                if getattr(scene_for_camera, "camera", None) is not planetka_camera:
                    scene_for_camera.camera = planetka_camera
                    camera_swapped = True
                _apply_navigation_shot(
                    bpy.context,
                    scene_for_camera,
                    props,
                    switch_viewport_to_camera=False,
                    sync_active_view_when_not_camera=False,
                )
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            _log_recoverable_once(
                "PKA-OPS-064",
                "Failed reapplying Planetka camera shot after Earth radius change",
            )
        finally:
            if camera_swapped:
                try:
                    scene_for_camera.camera = previous_scene_camera
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                    _log_recoverable_once(
                        "PKA-OPS-065",
                        "Failed restoring active scene camera after Planetka camera radius sync",
                    )

    return bool(changed)


def _meters_per_blender_unit(earth_radius_bu):
    safe_radius = max(float(earth_radius_bu), 1e-9)
    return REAL_EARTH_RADIUS_M / safe_radius


def _km_to_bu(km_value, earth_radius_bu):
    return (float(km_value) * 1000.0) / _meters_per_blender_unit(earth_radius_bu)


def _bu_to_km(distance_bu, earth_radius_bu):
    return (float(distance_bu) * _meters_per_blender_unit(earth_radius_bu)) / 1000.0


def _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad):
    radius = float(max(1e-9, earth_radius_bu))
    safe_altitude_bu = max(0.0, float(altitude_bu))
    tilt_cos = math.cos(float(tilt_rad))

    root_term = max(
        0.0,
        (radius * radius * tilt_cos * tilt_cos) + (2.0 * radius * safe_altitude_bu) + (safe_altitude_bu * safe_altitude_bu),
    )
    anchor_distance = (-radius * tilt_cos) + math.sqrt(root_term)
    return max(1e-6, float(anchor_distance))


def _lon_lat_normal_local(lon_deg, lat_deg):
    lon = math.radians(float(lon_deg))
    lat = math.radians(float(lat_deg))
    cos_lat = math.cos(lat)
    return Vector((
        cos_lat * math.cos(lon),
        cos_lat * math.sin(lon),
        math.sin(lat),
    ))


def _camera_projection_info(scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    camera_data = getattr(camera, "data", None)
    if camera_data is None:
        return None

    render = scene.render
    scale = float(render.resolution_percentage) / 100.0
    res_x = max(1.0, float(render.resolution_x) * scale)
    res_y = max(1.0, float(render.resolution_y) * scale)

    camera_type = str(getattr(camera_data, "type", "PERSP"))
    if camera_type == "ORTHO":
        aspect = max(1e-9, res_x / max(1.0, res_y))
        return {
            "camera_type": camera_type,
            "h_fov": math.radians(50.0),
            "v_fov": math.radians(35.0),
            "ortho_scale": float(getattr(camera_data, "ortho_scale", 1.0)),
            "res_x": res_x,
            "res_y": res_y,
            "aspect": aspect,
        }

    return {
        "camera_type": camera_type,
        "h_fov": float(getattr(camera_data, "angle_x", math.radians(50.0))),
        "v_fov": float(getattr(camera_data, "angle_y", math.radians(35.0))),
        "ortho_scale": float(getattr(camera_data, "ortho_scale", 1.0)),
        "res_x": res_x,
        "res_y": res_y,
        "aspect": max(1e-9, res_x / max(1.0, res_y)),
    }


def _find_active_view3d_context_details():
    context = bpy.context
    window = getattr(context, "window", None)
    screen = getattr(window, "screen", None) if window else None
    area = getattr(context, "area", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(context, "region_data", None)
    region = getattr(context, "region", None)
    if (
        area is not None
        and area.type == 'VIEW_3D'
        and space is not None
        and space.type == 'VIEW_3D'
        and rv3d is not None
    ):
        if region is None or getattr(region, "type", "") != 'WINDOW':
            region = next((candidate for candidate in area.regions if candidate.type == 'WINDOW'), None)
        return {
            "window": window,
            "screen": screen,
            "area": area,
            "space": space,
            "region": region,
            "rv3d": rv3d,
        }

    wm = getattr(context, "window_manager", None)
    if not wm:
        return None
    for candidate_window in wm.windows:
        candidate_screen = getattr(candidate_window, "screen", None)
        if not candidate_screen:
            continue
        for candidate_area in candidate_screen.areas:
            if candidate_area.type != 'VIEW_3D':
                continue
            candidate_space = getattr(candidate_area.spaces, "active", None)
            if not candidate_space or candidate_space.type != 'VIEW_3D':
                continue
            candidate_rv3d = getattr(candidate_space, "region_3d", None)
            if candidate_rv3d is None:
                continue
            candidate_region = next(
                (candidate for candidate in candidate_area.regions if candidate.type == 'WINDOW'),
                None,
            )
            return {
                "window": candidate_window,
                "screen": candidate_screen,
                "area": candidate_area,
                "space": candidate_space,
                "region": candidate_region,
                "rv3d": candidate_rv3d,
            }
    return None


def _find_active_view3d_context():
    details = _find_active_view3d_context_details()
    if details is None:
        return None
    return details["area"], details["space"], details["rv3d"]


def _switch_viewport_to_camera_view(context, scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return False

    switched = False
    area = getattr(context, "area", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(context, "region_data", None)
    if (
        area is not None
        and area.type == 'VIEW_3D'
        and space is not None
        and space.type == 'VIEW_3D'
        and rv3d is not None
    ):
        try:
            if scene.camera is not camera:
                scene.camera = camera
            rv3d.view_perspective = 'CAMERA'
            switched = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            _log_recoverable_once("PKA-OPS-016", "Failed switching active viewport to camera perspective")

    wm = getattr(context, "window_manager", None)
    if wm:
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if not screen:
                continue
            for candidate_area in screen.areas:
                if candidate_area.type != 'VIEW_3D':
                    continue
                candidate_space = getattr(candidate_area.spaces, "active", None)
                candidate_rv3d = getattr(candidate_space, "region_3d", None) if candidate_space else None
                if candidate_rv3d is None:
                    continue
                try:
                    if scene.camera is not camera:
                        scene.camera = camera
                    candidate_rv3d.view_perspective = 'CAMERA'
                    switched = True
                except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
                    continue
    return switched


def _sync_active_view_to_scene_camera(scene):
    if scene is None:
        return False
    camera = getattr(scene, "camera", None)
    if camera is None:
        return False

    details = _find_active_view3d_context_details()
    if details is None:
        return False
    window = details.get("window")
    screen = details.get("screen")
    area = details.get("area")
    region = details.get("region")
    space = details.get("space")
    rv3d = details.get("rv3d")
    if window is None or screen is None or area is None or region is None or space is None or rv3d is None:
        return False

    original_perspective = str(getattr(rv3d, "view_perspective", "") or "")
    if original_perspective == "CAMERA":
        return False

    try:
        if getattr(scene, "camera", None) is not camera:
            scene.camera = camera
        with bpy.context.temp_override(
            window=window,
            screen=screen,
            area=area,
            region=region,
            space_data=space,
            region_data=rv3d,
            scene=scene,
        ):
            result = bpy.ops.view3d.view_camera()
        if "FINISHED" not in set(result):
            return False
        if original_perspective in {"PERSP", "ORTHO"}:
            rv3d.view_perspective = original_perspective
        else:
            rv3d.view_perspective = "PERSP"
        return True
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
        _log_recoverable_once("PKA-OPS-061", "Failed syncing active viewport to camera pose")
        return False


def _ray_sphere_hit_nearest(origin, direction, radius):
    a = float(direction.dot(direction))
    if a <= 1e-12:
        return None
    b = 2.0 * float(origin.dot(direction))
    c = float(origin.dot(origin)) - float(radius) * float(radius)
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    sqrt_disc = math.sqrt(disc)
    inv = 0.5 / a
    t0 = (-b - sqrt_disc) * inv
    t1 = (-b + sqrt_disc) * inv
    for t in (t0, t1):
        if t > 1e-6:
            return origin + direction * t
    return None


def _compute_current_view_navigation_values(scene):
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None

    active_view = _find_active_view3d_context()
    if active_view is not None:
        _area, _space, rv3d = active_view
        view_matrix = rv3d.view_matrix.inverted()
        cam_pos_world = view_matrix.translation.copy()
        cam_forward_world = (-view_matrix.col[2].xyz).normalized()
    else:
        camera = getattr(scene, "camera", None)
        if camera is None:
            return None
        matrix = camera.matrix_world
        cam_pos_world = matrix.translation.copy()
        cam_forward_world = (-matrix.col[2].xyz).normalized()

    center, rotation, _scale = earth_obj.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        return None
    cam_forward_local.normalize()

    earth_radius = _earth_radius_blender_units(earth_obj)
    hit_local = _ray_sphere_hit_nearest(cam_pos_local, cam_forward_local, earth_radius)
    if hit_local is None:
        return None

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    altitude_bu = max(0.0, float(cam_pos_local.length) - float(earth_radius))
    altitude_km = _bu_to_km(altitude_bu, earth_radius)
    return lat, lon, altitude_km


def _compute_scene_camera_navigation_values(scene):
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None

    cam_matrix = camera.matrix_world
    cam_pos_world = cam_matrix.translation.copy()
    cam_forward_world = (-cam_matrix.col[2].xyz).normalized()

    center, rotation, _scale = earth_obj.matrix_world.decompose()
    rotation_inv = rotation.inverted()
    cam_pos_local = rotation_inv @ (cam_pos_world - center)
    cam_forward_local = rotation_inv @ cam_forward_world
    if cam_forward_local.length_squared <= 1e-12:
        return None
    cam_forward_local.normalize()

    earth_radius = _earth_radius_blender_units(earth_obj)
    hit_local = _ray_sphere_hit_nearest(cam_pos_local, cam_forward_local, earth_radius)
    if hit_local is None:
        cam_len = float(cam_pos_local.length)
        if cam_len <= 1e-9:
            return None
        hit_local = (cam_pos_local / cam_len) * float(earth_radius)

    hit_len = max(1e-9, float(hit_local.length))
    lon = math.degrees(math.atan2(float(hit_local.y), float(hit_local.x)))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, float(hit_local.z) / hit_len))))
    altitude_bu = max(0.0, float(cam_pos_local.length) - float(earth_radius))
    altitude_km = _bu_to_km(altitude_bu, earth_radius)
    return lat, lon, altitude_km


def _scene_camera_altitude_bu(scene):
    """Return camera altitude above Earth surface in Blender units (can be negative)."""
    earth_obj = get_earth_object()
    if earth_obj is None:
        return None
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or getattr(camera, "type", None) != "CAMERA":
        return None
    try:
        center = earth_obj.matrix_world.translation.copy()
        cam_pos = camera.matrix_world.translation.copy()
        radius = float(_earth_radius_blender_units(earth_obj))
        return float((cam_pos - center).length) - radius
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _is_scene_camera_below_surface(scene, tolerance_bu=1e-6):
    altitude_bu = _scene_camera_altitude_bu(scene)
    if altitude_bu is None:
        return False
    return float(altitude_bu) <= float(tolerance_bu)


def _tile_xy_for_lon_lat(lon_deg, lat_deg, z):
    lon_shift = (float(lon_deg) + 180.0) % 360.0
    lat_shift = max(0.0, min(179.999999, float(lat_deg) + 90.0))
    zf = float(z)
    x = int(lon_shift // zf) * int(zf)
    y = int(lat_shift // zf) * int(zf)
    return x % 360, max(0, min(179, y))


def _best_available_d_for_tile(base_path, x, y, z):
    normalized = _normalize_texture_source_path(base_path)
    if not normalized and not is_remote_source_configured(base_path):
        return None

    d_candidates = sorted(set(NAV_D_LEVELS_BY_Z.get(int(z), [int(z)])))
    for d in d_candidates:
        d_code = 0 if int(d) == 1440 else int(d)
        file_name = f"S2_x{x:03d}_y{y:03d}_z{int(z):03d}_d{int(d_code):03d}.exr"
        try:
            if texture_file_exists(normalized or base_path, "S2", file_name):
                return int(d)
        except RuntimeError:
            logger.debug("Planetka: failed checking available S2 detail level for navigation", exc_info=True)
            return None
    return None


def _finest_available_d_for_location(lon_deg, lat_deg, base_path):
    coverage = _get_coverage_map()
    for z in sorted(NAV_D_LEVELS_BY_Z.keys()):
        tiles = coverage.get(int(z), set())
        if not tiles:
            continue
        x, y = _tile_xy_for_lon_lat(lon_deg, lat_deg, z)
        if (x, y) not in tiles:
            continue
        exact_d = _best_available_d_for_tile(base_path, x, y, z)
        if exact_d is not None:
            return max(1, int(exact_d))
        return max(1, int(z))
    return 360


def _max_proximity_altitude_km(scene, earth_obj, earth_radius_bu, lon_deg, lat_deg):
    projection = _camera_projection_info(scene)
    if projection is None:
        return None, "Scene camera is required for navigation."

    if projection["camera_type"] == "ORTHO":
        center = earth_obj.matrix_world.translation
        cam_loc = scene.camera.matrix_world.translation
        altitude_bu = max(0.0, float((cam_loc - center).length) - float(earth_radius_bu))
        return _bu_to_km(altitude_bu, earth_radius_bu), (
            "Orthographic camera detected: altitude does not control detail; keeping current altitude."
        )

    prefs = get_prefs()
    base_path = getattr(prefs, "texture_base_path", "") if prefs else ""
    best_d = _finest_available_d_for_location(lon_deg, lat_deg, base_path)

    required_mpp_limit = (
        float(best_d)
        * DATASET_MPP_BASE_D1
        / max(1e-6, float(MAX_PROXIMITY_TARGET_SAFETY_RATIO))
    )
    px_angle = max(
        float(projection["h_fov"]) / max(1.0, float(projection["res_x"])),
        float(projection["v_fov"]) / max(1.0, float(projection["res_y"])),
    )
    px_angle = max(1e-9, float(px_angle))

    meters_per_bu = _meters_per_blender_unit(earth_radius_bu)
    effective_distance_bu = (required_mpp_limit / meters_per_bu) / (2.0 * math.tan(px_angle * 0.5))
    terrain_offset_bu = MAX_TERRAIN_HEIGHT_M / meters_per_bu
    altitude_bu = max(0.0, effective_distance_bu + terrain_offset_bu)
    return _bu_to_km(altitude_bu, earth_radius_bu), None


def _full_globe_altitude_km(scene, earth_radius_bu):
    projection = _camera_projection_info(scene)
    if projection is None:
        return None

    if projection["camera_type"] == "ORTHO":
        return None

    half_fov = min(float(projection["h_fov"]), float(projection["v_fov"])) * 0.5
    half_fov = max(1e-6, half_fov)
    center_distance_bu = (float(earth_radius_bu) * FULL_GLOBE_EXTRA_MARGIN) / math.sin(half_fov)
    altitude_bu = max(0.0, center_distance_bu - float(earth_radius_bu))
    return _bu_to_km(altitude_bu, earth_radius_bu)


def _ensure_ortho_full_globe_if_needed(scene, earth_radius_bu):
    camera = getattr(scene, "camera", None) if scene else None
    camera_data = getattr(camera, "data", None) if camera else None
    if not camera_data or str(getattr(camera_data, "type", "")) != "ORTHO":
        return False

    projection = _camera_projection_info(scene)
    if projection is None:
        return False

    aspect = max(1e-9, float(projection["aspect"]))
    margin_radius = float(earth_radius_bu) * FULL_GLOBE_EXTRA_MARGIN
    if aspect >= 1.0:
        needed_scale = 2.0 * margin_radius * aspect
    else:
        needed_scale = 2.0 * margin_radius / aspect

    try:
        if float(getattr(camera_data, "ortho_scale", 1.0)) < float(needed_scale):
            camera_data.ortho_scale = float(needed_scale)
            return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return False


def _navigate_camera_internal(scene, lon_deg, lat_deg, altitude_km, look_at_center=False):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    earth_center, earth_rot, _scale = earth_obj.matrix_world.decompose()
    earth_radius_bu = _earth_radius_blender_units(earth_obj)

    altitude_bu = _km_to_bu(max(0.0, float(altitude_km)), earth_radius_bu)
    normal_local = _lon_lat_normal_local(lon_deg, lat_deg)
    if normal_local.length_squared <= 1e-12:
        normal_local = Vector((1.0, 0.0, 0.0))
    normal_local.normalize()
    normal_world = (earth_rot @ normal_local).normalized()

    if look_at_center:
        target_point = earth_center.copy()
    else:
        target_point = earth_center + normal_world * float(earth_radius_bu)
    camera_position = earth_center + normal_world * (float(earth_radius_bu) + altitude_bu)
    look_direction = (target_point - camera_position)
    if look_direction.length_squared <= 1e-12:
        look_direction = -normal_world
    look_direction.normalize()

    try:
        _loc, _rot, cam_scale = camera.matrix_world.decompose()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        cam_scale = Vector((1.0, 1.0, 1.0))

    cam_rotation = look_direction.to_track_quat('-Z', 'Y')
    camera.matrix_world = Matrix.LocRotScale(camera_position, cam_rotation, cam_scale)
    return earth_obj, earth_radius_bu


def _anchor_frame_world(earth_obj, lon_deg, lat_deg):
    earth_center, earth_rot, _scale = earth_obj.matrix_world.decompose()
    earth_radius_bu = _earth_radius_blender_units(earth_obj)
    lon_rad = math.radians(float(lon_deg))
    up_local = _lon_lat_normal_local(lon_deg, lat_deg)
    if up_local.length_squared <= 1e-12:
        up_local = Vector((1.0, 0.0, 0.0))
    up_local.normalize()

    east_local = Vector((-math.sin(lon_rad), math.cos(lon_rad), 0.0))
    if east_local.length_squared <= 1e-12:
        east_local = Vector((0.0, 1.0, 0.0))
    east_local.normalize()

    north_local = up_local.cross(east_local)
    if north_local.length_squared <= 1e-12:
        north_local = Vector((0.0, 0.0, 1.0))
    north_local.normalize()

    up_world = (earth_rot @ up_local).normalized()
    east_world = (earth_rot @ east_local).normalized()
    north_world = (earth_rot @ north_local).normalized()
    anchor_world = earth_center + up_world * float(earth_radius_bu)
    return anchor_world, east_world, north_world, up_world, earth_radius_bu


def _look_rotation_quaternion(camera_location, target_point, up_hint):
    forward = (target_point - camera_location)
    if forward.length_squared <= 1e-12:
        raise RuntimeError("Camera is at the target location; cannot orient.")
    forward.normalize()

    if up_hint is None or up_hint.length_squared <= 1e-12:
        up_hint = Vector((0.0, 0.0, 1.0))
    else:
        up_hint = up_hint.normalized()

    right = forward.cross(up_hint)
    if right.length_squared <= 1e-12:
        fallback = Vector((0.0, 1.0, 0.0))
        right = forward.cross(fallback)
        if right.length_squared <= 1e-12:
            fallback = Vector((1.0, 0.0, 0.0))
            right = forward.cross(fallback)
    right.normalize()
    true_up = right.cross(forward)
    if true_up.length_squared <= 1e-12:
        true_up = Vector((0.0, 0.0, 1.0))
    true_up.normalize()

    rotation_matrix = Matrix((right, true_up, -forward)).transposed()
    return rotation_matrix.to_quaternion(), forward


def _ensure_shot_anchor_object(scene):
    anchor_obj = bpy.data.objects.get(SHOT_ANCHOR_OBJECT_NAME)
    if anchor_obj is not None and getattr(anchor_obj, "type", None) != 'EMPTY':
        try:
            bpy.data.objects.remove(anchor_obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            anchor_obj = None
    if anchor_obj is None:
        anchor_obj = bpy.data.objects.new(SHOT_ANCHOR_OBJECT_NAME, None)
        try:
            anchor_obj.empty_display_type = 'ARROWS'
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            anchor_obj.empty_display_size = 0.1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    target_collection = ensure_planetka_temp_collection() or getattr(scene, "collection", None)
    if target_collection is not None:
        for collection in tuple(getattr(anchor_obj, "users_collection", ())):
            if collection is target_collection:
                continue
            try:
                collection.objects.unlink(anchor_obj)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-OPS-005", "Failed unlinking shot anchor from non-target collection")
        try:
            if anchor_obj.name not in target_collection.objects:
                target_collection.objects.link(anchor_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-OPS-006", "Failed linking shot anchor to target collection")
    try:
        anchor_obj.hide_viewport = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-007", "Failed hiding shot anchor in viewport")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-008", "Failed hiding shot anchor in viewport")
    try:
        anchor_obj.hide_set(True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-009", "Failed hide_set on shot anchor")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-010", "Failed hide_set on shot anchor")
    try:
        root = ensure_planetka_root(scene)
        if root is not None and getattr(anchor_obj, "parent", None) is not root:
            anchor_obj.parent = root
            anchor_obj.matrix_parent_inverse = root.matrix_world.inverted()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-036", "Failed parenting shot anchor to Planetka Root")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-037", "Failed parenting shot anchor to Planetka Root")
    return anchor_obj


def _hide_shot_anchor_in_viewport():
    anchor_obj = bpy.data.objects.get(SHOT_ANCHOR_OBJECT_NAME)
    if anchor_obj is None:
        return
    try:
        anchor_obj.hide_viewport = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-011", "Failed hiding existing shot anchor in viewport")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-012", "Failed hiding existing shot anchor in viewport")
    try:
        anchor_obj.hide_set(True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-013", "Failed hide_set on existing shot anchor")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _log_recoverable_once("PKA-OPS-014", "Failed hide_set on existing shot anchor")


def _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world):
    anchor_obj = _ensure_shot_anchor_object(scene)
    if anchor_obj is None:
        return
    frame_rotation = Matrix((east_world, north_world, up_world)).transposed().to_quaternion()
    try:
        anchor_obj.matrix_world = Matrix.LocRotScale(anchor_world, frame_rotation, Vector((1.0, 1.0, 1.0)))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-OPS-015", "Failed updating shot anchor transform")


def _signed_angle_around_axis(from_vec, to_vec, axis):
    if (
        from_vec is None
        or to_vec is None
        or axis is None
        or from_vec.length_squared <= 1e-12
        or to_vec.length_squared <= 1e-12
        or axis.length_squared <= 1e-12
    ):
        return 0.0
    from_n = from_vec.normalized()
    to_n = to_vec.normalized()
    axis_n = axis.normalized()
    cross = from_n.cross(to_n)
    sin_v = axis_n.dot(cross)
    cos_v = max(-1.0, min(1.0, float(from_n.dot(to_n))))
    return math.atan2(float(sin_v), float(cos_v))


def _camera_to_current_view(scene):
    context_details = _find_active_view3d_context_details()
    if context_details is None:
        raise RuntimeError("No active 3D viewport found.")
    window = context_details.get("window")
    screen = context_details.get("screen")
    area = context_details.get("area")
    region = context_details.get("region")
    space = context_details.get("space")
    rv3d = context_details.get("rv3d")

    if window is None or screen is None or area is None or region is None or space is None or rv3d is None:
        raise RuntimeError("Current viewport context is incomplete.")

    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    if str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
        return False

    try:
        with bpy.context.temp_override(
            window=window,
            screen=screen,
            area=area,
            region=region,
            space_data=space,
            region_data=rv3d,
            scene=scene,
        ):
            result = bpy.ops.view3d.camera_to_view()
    except RuntimeError as exc:
        message = str(exc)
        if "context is incorrect" in message and str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
            return False
        raise

    if "FINISHED" in result:
        return True
    if str(getattr(rv3d, "view_perspective", "")) == "CAMERA":
        return False
    raise RuntimeError("Failed to move camera to current view.")


def _derive_navigation_shot_from_camera(scene, lon_deg, lat_deg):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    anchor_world, east_world, north_world, up_world, earth_radius_bu = _anchor_frame_world(
        earth_obj,
        lon_deg,
        lat_deg,
    )
    earth_center = earth_obj.matrix_world.translation.copy()

    camera_matrix = camera.matrix_world
    camera_position = camera_matrix.translation.copy()
    camera_forward = (-camera_matrix.col[2].xyz).normalized()
    camera_up = camera_matrix.col[1].xyz.normalized()

    anchor_to_camera = camera_position - anchor_world
    anchor_distance = max(1e-9, float(anchor_to_camera.length))
    anchor_to_camera_dir = anchor_to_camera / anchor_distance

    up_component = max(-1.0, min(1.0, float(anchor_to_camera_dir.dot(up_world))))
    horizontal_vec = anchor_to_camera_dir - (up_world * up_component)
    horizontal_len = float(horizontal_vec.length)

    if horizontal_len <= 1e-9:
        heading_rad = 0.0
    else:
        horizontal_dir = horizontal_vec / horizontal_len
        look_horizontal_dir = -horizontal_dir
        heading_rad = math.atan2(
            float(look_horizontal_dir.dot(east_world)),
            float(look_horizontal_dir.dot(north_world)),
        )
    look_tangent = (north_world * math.cos(heading_rad)) + (east_world * math.sin(heading_rad))
    if look_tangent.length_squared <= 1e-12:
        look_tangent = north_world.copy()
    look_tangent.normalize()
    position_tangent = -look_tangent

    tilt_abs_rad = math.atan2(horizontal_len, up_component)
    sin_component = float(anchor_to_camera_dir.dot(position_tangent))
    if abs(sin_component) <= 1e-9:
        tilt_rad = tilt_abs_rad
    else:
        tilt_rad = math.copysign(tilt_abs_rad, sin_component)

    center_to_camera = camera_position - earth_center
    center_to_camera_len = max(1e-9, float(center_to_camera.length))
    altitude_bu = max(0.0, center_to_camera_len - float(earth_radius_bu))

    base_rotation, _forward = _look_rotation_quaternion(camera_position, anchor_world, look_tangent)
    base_up = (base_rotation @ Vector((0.0, 1.0, 0.0))).normalized()
    roll_rad = _signed_angle_around_axis(base_up, camera_up, camera_forward)

    return {
        "altitude_km": _bu_to_km(altitude_bu, earth_radius_bu),
        "azimuth_deg": math.degrees(heading_rad),
        "tilt_deg": math.degrees(tilt_rad),
        "roll_deg": math.degrees(roll_rad),
    }


def _apply_navigation_shot(
    context,
    scene,
    props,
    switch_viewport_to_camera=True,
    sync_active_view_when_not_camera=False,
):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise RuntimeError("Scene camera is missing. Set an active camera and retry.")

    earth_obj = get_earth_object()
    if earth_obj is None:
        raise RuntimeError("Create Earth first, then use Navigation.")

    lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
    lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
    altitude_km = max(0.0, float(getattr(props, "nav_altitude_km", 0.0)))
    heading_deg = float(getattr(props, "nav_azimuth_deg", 0.0))
    tilt_deg = float(getattr(props, "nav_tilt_deg", 0.0))
    roll_deg = float(getattr(props, "nav_roll_deg", 0.0))

    anchor_world, east_world, north_world, up_world, earth_radius_bu = _anchor_frame_world(
        earth_obj, lon_deg, lat_deg
    )
    earth_center = earth_obj.matrix_world.translation.copy()
    _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)

    altitude_bu = _km_to_bu(altitude_km, earth_radius_bu)
    heading_rad = math.radians(float(heading_deg))
    tilt_rad = math.radians(float(tilt_deg))
    roll_rad = math.radians(float(roll_deg))

    look_tangent = (north_world * math.cos(heading_rad)) + (east_world * math.sin(heading_rad))
    if look_tangent.length_squared <= 1e-12:
        look_tangent = north_world.copy()
    look_tangent.normalize()

    position_tangent = -look_tangent
    offset_direction = (up_world * math.cos(tilt_rad)) + (position_tangent * math.sin(tilt_rad))
    if offset_direction.length_squared <= 1e-12:
        offset_direction = up_world.copy()
    offset_direction.normalize()

    current_camera_position = camera.matrix_world.translation.copy()
    current_center_distance = max(1e-9, float((current_camera_position - earth_center).length))
    current_altitude_bu = max(0.0, current_center_distance - float(earth_radius_bu))
    current_altitude_km = _bu_to_km(current_altitude_bu, earth_radius_bu)

    last_values = _read_last_navigation_values(scene)
    lon_changed = False
    lat_changed = False
    altitude_prop_changed = False
    heading_changed = False
    tilt_changed = False
    roll_changed = False
    if last_values is not None:
        lon_changed = abs(float(lon_deg) - float(last_values["lon"])) > NAV_CHANGE_EPS
        lat_changed = abs(float(lat_deg) - float(last_values["lat"])) > NAV_CHANGE_EPS
        altitude_prop_changed = abs(float(altitude_km) - float(last_values["alt"])) > NAV_CHANGE_EPS
        heading_changed = abs(float(heading_deg) - float(last_values["heading"])) > NAV_CHANGE_EPS
        tilt_changed = abs(float(tilt_deg) - float(last_values["tilt"])) > NAV_CHANGE_EPS
        roll_changed = abs(float(roll_deg) - float(last_values["roll"])) > NAV_CHANGE_EPS
    else:
        altitude_prop_changed = abs(float(altitude_km) - float(current_altitude_km)) > 1e-4

    tilt_only_change = (
        tilt_changed
        and not lon_changed
        and not lat_changed
        and not altitude_prop_changed
        and not heading_changed
        and not roll_changed
    )

    if tilt_only_change:
        anchor_distance = float((current_camera_position - anchor_world).length)
        if anchor_distance <= 1e-9:
            anchor_distance = _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad)
    else:
        anchor_distance = _anchor_distance_from_altitude_and_tilt(earth_radius_bu, altitude_bu, tilt_rad)

    camera_position = anchor_world + (offset_direction * anchor_distance)
    # Keep the UI altitude value under direct user control while dragging.
    # Writing nav_altitude_km back from derived camera math here can interrupt
    # Blender's live numeric drag interaction.

    look_target = anchor_world.copy()
    if (look_target - camera_position).length_squared <= 1e-12:
        look_target = camera_position - up_world

    _loc, _existing_rotation, camera_scale = camera.matrix_world.decompose()
    base_rotation, forward = _look_rotation_quaternion(camera_position, look_target, look_tangent)
    if abs(roll_rad) > 1e-9:
        roll_quaternion = Quaternion(forward, roll_rad)
        final_rotation = roll_quaternion @ base_rotation
    else:
        final_rotation = base_rotation

    camera.matrix_world = Matrix.LocRotScale(camera_position, final_rotation, camera_scale)
    _ensure_close_clip_limits(scene, min_clip=0.001)
    if bool(switch_viewport_to_camera):
        _switch_viewport_to_camera_view(context, scene)
    elif bool(sync_active_view_when_not_camera):
        _sync_active_view_to_scene_camera(scene)
    _store_last_navigation_values(
        scene,
        lon_deg=lon_deg,
        lat_deg=lat_deg,
        altitude_km=float(altitude_km),
        heading_deg=heading_deg,
        tilt_deg=tilt_deg,
        roll_deg=roll_deg,
    )
    return earth_obj, earth_radius_bu


def _populate_navigation_from_scene_camera(scene, props):
    if scene is None or props is None:
        return False
    # When camera is inside/at surface (common right after large Earth radius changes),
    # deriving heading/roll from camera matrix is unstable and can overwrite user controls.
    if _is_scene_camera_below_surface(scene):
        return False
    nav_values = _compute_scene_camera_navigation_values(scene)
    if nav_values is None:
        return False
    lat, lon, _alt_km = nav_values
    derived = _derive_navigation_shot_from_camera(scene, lon, lat)
    try:
        camera = getattr(scene, "camera", None)
        camera_data = getattr(camera, "data", None) if camera is not None else None
        quantized = _quantize_navigation_ui_payload(
            lat_deg=float(lat),
            lon_deg=float(lon),
            altitude_km=float(derived.get("altitude_km", 0.0)),
            heading_deg=float(derived.get("azimuth_deg", 0.0)),
            tilt_deg=float(derived.get("tilt_deg", 0.0)),
            roll_deg=float(derived.get("roll_deg", 0.0)),
            focal_length_mm=float(getattr(camera_data, "lens", 50.0)) if camera_data is not None else float(getattr(props, "nav_focal_length_mm", 50.0)),
        )
        props.nav_latitude_deg = float(quantized["lat_deg"])
        props.nav_longitude_deg = float(quantized["lon_deg"])
        props.nav_altitude_km = float(quantized["altitude_km"])
        props.nav_azimuth_deg = float(quantized["heading_deg"])
        props.nav_tilt_deg = float(quantized["tilt_deg"])
        props.nav_roll_deg = float(quantized["roll_deg"])
        if camera_data is not None:
            props.nav_focal_length_mm = float(quantized["focal_length_mm"])
        _store_last_navigation_values(
            scene,
            lon_deg=float(props.nav_longitude_deg),
            lat_deg=float(props.nav_latitude_deg),
            altitude_km=float(props.nav_altitude_km),
            heading_deg=float(props.nav_azimuth_deg),
            tilt_deg=float(props.nav_tilt_deg),
            roll_deg=float(props.nav_roll_deg),
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return True


class PLANETKA_OT_ImportNewData(bpy.types.Operator):
    bl_idname = "planetka.import_new_data"
    bl_label = "Import New Data"
    bl_description = "Disabled: Planetka uses Cloud source only"

    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        self.report({'ERROR'}, "Local texture import is disabled. Planetka uses Cloud source only.")
        return {'CANCELLED'}

    def invoke(self, context, event):
        self.report({'ERROR'}, "Local texture import is disabled. Planetka uses Cloud source only.")
        return {'CANCELLED'}


class PLANETKA_OT_ConfirmImportNewData(bpy.types.Operator):
    bl_idname = "planetka.confirm_import_new_data"
    bl_label = "Confirm Data Import"
    bl_description = "Disabled: Planetka uses Cloud source only"

    source_directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN'})
    destination_directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN'})
    new_file_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    update_file_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    added_size_mb: FloatProperty(default=0.0, min=0.0, options={'HIDDEN', 'SKIP_SAVE'})
    total_file_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})
    duplicate_count: IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})

    def _refresh_preview(self):
        source_directory = _normalize_texture_source_path(self.source_directory)
        destination_directory = _normalize_texture_source_path(self.destination_directory)
        if not source_directory or not os.path.isdir(source_directory):
            return None, "Selected source folder is no longer available."
        if not destination_directory or not os.path.isdir(destination_directory):
            return None, "Texture source directory is no longer available."

        plan = _build_texture_import_plan(source_directory, destination_directory)
        self.new_file_count = int(plan.get("new_file_count", 0))
        self.update_file_count = int(plan.get("update_file_count", 0))
        self.total_file_count = int(len(plan.get("jobs", ())))
        self.duplicate_count = int(plan.get("duplicates_skipped", 0))
        self.added_size_mb = _bytes_to_mb(plan.get("added_size_bytes", 0))
        return plan, ""

    def invoke(self, context, event):
        self.report({'ERROR'}, "Local texture import is disabled. Planetka uses Cloud source only.")
        return {'CANCELLED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text=f"Source: {self.source_directory}")
        col.label(text=f"Destination: {self.destination_directory}")
        col.label(text="The following changes will be applied:")
        col.label(text=f"Total files to copy: {int(self.total_file_count)}")
        col.label(text=f"New files to import: {int(self.new_file_count)}")
        col.label(text=f"Existing files to update: {int(self.update_file_count)}")
        col.label(text=f"New data added: {float(self.added_size_mb):.0f} MB")
        if int(self.duplicate_count) > 0:
            col.label(text=f"Duplicate source tiles detected: {int(self.duplicate_count)} (newest file kept)")

    def execute(self, context):
        self.report({'ERROR'}, "Local texture import is disabled. Planetka uses Cloud source only.")
        return {'CANCELLED'}


class PLANETKA_OT_SelectTextureSource(bpy.types.Operator):
    bl_idname = "planetka.select_texture_source"
    bl_label = "Set Texture Source"
    bl_description = "Disabled: Planetka uses Cloud source only"

    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        self.report({'ERROR'}, "Local texture directories are disabled. Planetka uses Cloud source only.")
        return {'CANCELLED'}

    def invoke(self, context, event):
        self.report({'ERROR'}, "Local texture directories are disabled. Planetka uses Cloud source only.")
        return {'CANCELLED'}


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


class PLANETKA_OT_SetBackgroundBlack(bpy.types.Operator):
    bl_idname = "planetka.set_background_black"
    bl_label = "Change Background to Black"
    bl_description = "Set World background color to black"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        world = getattr(scene, "world", None)
        if world is None:
            self.report({'WARNING'}, "No World assigned to the scene.")
            return {'CANCELLED'}

        changed = False
        node_tree = getattr(world, "node_tree", None)
        nodes = getattr(node_tree, "nodes", None) if node_tree is not None else None
        background = nodes.get("Background") if nodes is not None else None
        if background is None and nodes is not None:
            for node in nodes:
                if str(getattr(node, "bl_idname", "")) == "ShaderNodeBackground":
                    background = node
                    break
        if background is not None:
            color_socket = background.inputs[0] if len(background.inputs) > 0 else None
            if color_socket is not None and not bool(getattr(color_socket, "is_linked", False)):
                try:
                    color_socket.default_value = (0.0, 0.0, 0.0, 1.0)
                    changed = True
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
        elif node_tree is None:
            try:
                world.color = (0.0, 0.0, 0.0)
                changed = True
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

        if not changed:
            self.report({'WARNING'}, "World background color could not be changed automatically.")
            return {'CANCELLED'}

        return {'FINISHED'}


class PLANETKA_OT_RemoveDefaultScene(bpy.types.Operator):
    bl_idname = "planetka.remove_default_scene"
    bl_label = "Remove Default Cube Scene"
    bl_description = (
        "Remove default Collection/Cube/Camera/Light and default World shader "
        "when the scene is still pristine Blender startup state"
    )

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return False
        if get_earth_object() is not None:
            return False
        return _is_pristine_default_scene(scene)

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        if not _is_pristine_default_scene(scene):
            return fail(
                self,
                "Remove Default Cube Scene is available only for untouched Blender default startup scene.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )

        removed = bool(_cleanup_pristine_default_scene(scene))
        if not removed:
            return fail(
                self,
                "Unable to remove default scene items.",
                code=ErrorCode.RESOLVE_REFRESH_FAILED,
                logger=logger,
            )

        try:
            scene[_DEFAULT_SCENE_REMOVED_KEY] = True
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed tagging scene as default-cleaned", exc_info=True)

        self.report({'INFO'}, "Default startup scene removed.")
        return {'FINISHED'}


class PLANETKA_OT_RebuildEarth(bpy.types.Operator):
    bl_idname = "planetka.rebuild_earth"
    bl_label = "Rebuild Earth"
    bl_description = (
        "Emergency rebuild: remove Planetka objects/shaders/runtime data from memory, "
        "preserve camera transform and keyframes, then run Create Earth"
    )

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        selected_names_before, active_name_before = _snapshot_view_selection(context)

        def _return_with_selection(result):
            _restore_view_selection(context, scene, selected_names_before, active_name_before)
            return result

        camera = _pick_scene_camera(scene, context=context)
        camera_snapshot = _snapshot_camera_state_for_rebuild(scene, camera)
        earth_settings_snapshot = _snapshot_earth_settings_for_rebuild(scene, props)
        temp_camera_obj = None
        temp_camera_data = None

        cleanup_stats = _earth_graph_cleanup_for_rebuild(scene)
        detached_cameras = int(cleanup_stats.get("detached_cameras", 0))
        removed_objects = int(cleanup_stats.get("removed_objects", 0))
        removed_collections = int(cleanup_stats.get("removed_collections", 0))
        removed_data = dict(cleanup_stats.get("removed_data", {}) or {})
        scene_keys_cleared = int(cleanup_stats.get("scene_keys_cleared", 0))
        cleanup_counts = dict(cleanup_stats.get("cleanup_counts", {}) or {})

        if camera is not None and str(getattr(camera, "type", "")) == "CAMERA":
            for collection in tuple(getattr(camera, "users_collection", ()) or ()):
                try:
                    collection.objects.unlink(camera)
                except _REBUILD_EXCEPTIONS:
                    logger.debug("Planetka: failed unlinking preserved camera during rebuild isolation", exc_info=True)

        try:
            temp_camera_data = bpy.data.cameras.new("Planetka Rebuild Temp Camera Data")
            temp_camera_obj = bpy.data.objects.new("Planetka Rebuild Temp Camera", temp_camera_data)
            scene.collection.objects.link(temp_camera_obj)
            matrix_world = camera_snapshot.get("matrix_world", None)
            if matrix_world is not None:
                temp_camera_obj.matrix_world = matrix_world
            scene.camera = temp_camera_obj
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed creating temporary rebuild camera", exc_info=True)
            temp_camera_obj = None
            temp_camera_data = None

        try:
            scene[_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY] = True
        except _REBUILD_EXCEPTIONS:
            logger.debug("Planetka: failed setting create-earth camera-skip flag for rebuild", exc_info=True)
        try:
            rebuild_result = bpy.ops.planetka.add_earth()
        finally:
            try:
                if _SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY in scene:
                    del scene[_SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY]
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed clearing create-earth camera-skip flag after rebuild", exc_info=True)

        if temp_camera_obj is not None:
            try:
                bpy.data.objects.remove(temp_camera_obj, do_unlink=True)
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed removing temporary rebuild camera object", exc_info=True)
        if temp_camera_data is not None:
            try:
                if int(getattr(temp_camera_data, "users", 0) or 0) == 0:
                    bpy.data.cameras.remove(temp_camera_data)
            except _REBUILD_EXCEPTIONS:
                logger.debug("Planetka: failed removing temporary rebuild camera data", exc_info=True)

        _earth_graph_restore_after_rebuild(scene, props, earth_settings_snapshot, camera_snapshot)

        if "FINISHED" not in rebuild_result:
            return _return_with_selection(fail(
                self,
                "Rebuild cleanup completed, but Create Earth failed. Resolve integrity may remain invalid.",
                code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
                logger=logger,
            ))

        logger.info(
            "Planetka rebuild completed (detached_cameras=%d, removed_objects=%d, "
            "removed_collections=%d, removed_meshes=%d, removed_images=%d, "
            "removed_materials=%d, removed_node_groups=%d, removed_lights=%d, "
            "scene_keys_cleared=%d, cleanup_objects=%d, cleanup_meshes=%d, cleanup_images=%d, "
            "cleanup_materials=%d, cleanup_node_groups=%d).",
            int(detached_cameras),
            int(removed_objects),
            int(removed_collections),
            int(removed_data.get("meshes", 0)),
            int(removed_data.get("images", 0)),
            int(removed_data.get("materials", 0)),
            int(removed_data.get("node_groups", 0)),
            int(removed_data.get("lights", 0)),
            int(scene_keys_cleared),
            int(cleanup_counts.get("objects", 0) or 0),
            int(cleanup_counts.get("meshes", 0) or 0),
            int(cleanup_counts.get("images", 0) or 0),
            int(cleanup_counts.get("materials", 0) or 0),
            int(cleanup_counts.get("node_groups", 0) or 0),
        )
        self.report({'INFO'}, "Planetka Earth rebuilt successfully.")
        return _return_with_selection({'FINISHED'})


class PLANETKA_OT_AddEarth(bpy.types.Operator):
    bl_idname = "planetka.add_earth"
    bl_label = "Create Earth"
    bl_description = "Create Planetka Earth assets and run an initial Resolve"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        selected_names_before, active_name_before = _snapshot_view_selection(context)
        preexisting_active_camera = getattr(scene, "camera", None)
        preexisting_cameras = [
            obj for obj in tuple(getattr(scene, "objects", ()))
            if str(getattr(obj, "type", "")) == "CAMERA"
        ]
        preexisting_non_planetka_cameras = [
            obj for obj in preexisting_cameras
            if not _is_planetka_create_camera(obj)
        ]
        activate_planetka_camera = not bool(preexisting_non_planetka_cameras)

        def _return_with_selection(result):
            _restore_view_selection(context, scene, selected_names_before, active_name_before)
            return result

        prefs = get_prefs()
        if not prefs:
            return _return_with_selection(fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            ))
        try:
            kickoff_background_update_check(force=True)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: updater check kickoff failed", exc_info=True)
        normalized, path_issue = _validate_create_earth_texture_source(getattr(prefs, "texture_base_path", ""))
        if path_issue:
            self.report(
                {'ERROR'},
                "Create Earth data configuration is invalid.",
            )
            self.report({'ERROR'}, path_issue)
            return _return_with_selection({'CANCELLED'})
        if is_remote_source_configured(normalized) and not _require_authenticated_account(self, prefs):
            return _return_with_selection({'CANCELLED'})
        prefs.texture_base_path = normalized
        invalidate_texture_source_health_cache(normalized)

        try:
            ensure_planetka_assets(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return _return_with_selection(fail(
                self,
                f"Create Earth failed while creating Planetka assets: {exc}",
                code=ErrorCode.ADD_EARTH_IMPORT_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka add_earth asset build failed",
            ))

        _initialize_props_from_imported_planetka(scene)
        _sync_idprops_from_props(scene)
        try:
            ensure_planetka_root(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed ensuring Planetka Root before Create Earth", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed ensuring Planetka Root before Create Earth", exc_info=True)

        try:
            props.texture_quality_mode = "PREVIEW"
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed setting default texture quality to Preview", exc_info=True)
        warm_base_sphere_mesh_cache()

        new_obj = None
        try:
            new_obj = _earth_graph_create_bootstrap_surface(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            if new_obj:
                remove_object_and_unused_mesh(new_obj)
            return _return_with_selection(fail(
                self,
                f"Create Earth failed while creating bootstrap Earth surface: {exc}",
                code=ErrorCode.ADD_EARTH_SHORTCUT_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka add_earth bootstrap build failed",
            ))

        try:
            _apply_startup_setup_for_create_earth(scene, props)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed applying startup setup profile", exc_info=True)
        planetka_camera = _ensure_planetka_create_camera(scene)
        if planetka_camera is None:
            logger.debug("Planetka: failed creating Planetka Camera", exc_info=True)
        else:
            try:
                _position_planetka_create_camera(
                    scene,
                    props,
                    planetka_camera,
                    activate=bool(activate_planetka_camera),
                )
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed positioning Planetka Camera on Create Earth", exc_info=True)
        # Create Earth default must remain Preview even if a saved startup profile
        # contains a different texture quality mode.
        try:
            props.texture_quality_mode = "PREVIEW"
            _sync_idprops_from_props(scene, ("texture_quality_mode",))
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed enforcing Create Earth default texture quality mode", exc_info=True)
        if bool(getattr(props, "auto_black_background_new_files", True)):
            try:
                _set_default_world_background_to_black(scene)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed applying default world background override", exc_info=True)
        if bool(getattr(props, "auto_adjust_clipping_values", True)):
            try:
                camera_before_clip = getattr(scene, "camera", None)
                try:
                    if planetka_camera is not None and str(getattr(planetka_camera, "type", "")) == "CAMERA":
                        scene.camera = planetka_camera
                    _apply_create_earth_clipping_defaults(scene)
                finally:
                    if (
                        not bool(activate_planetka_camera)
                        and preexisting_active_camera is not None
                        and str(getattr(preexisting_active_camera, "type", "")) == "CAMERA"
                    ):
                        scene.camera = preexisting_active_camera
                    elif (
                        not bool(activate_planetka_camera)
                        and preexisting_active_camera is None
                    ):
                        scene.camera = camera_before_clip
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
                logger.debug("Planetka: failed applying create-earth clipping defaults", exc_info=True)
        try:
            # Preserve Create Earth informational notices through the initial queued resolve.
            scene["planetka_status_notice_clear_skip_count"] = 1
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            pass

        # Queue initial resolve download in background so Create Earth stays responsive.
        resolve_result = bpy.ops.planetka.load_textures(
            skip_render_compatibility=True,
            defer_download=True,
        )
        final_surface = get_earth_object() or new_obj
        if final_surface and bool(getattr(props, "show_earth_preview", False)):
            try:
                ensure_preview_object(final_surface)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed creating preview object", exc_info=True)
                self.report({'WARNING'}, "Planetka preview object refresh failed.")
            except (RuntimeError, TypeError, ValueError):
                logger.debug("Planetka: failed creating preview object", exc_info=True)
                self.report({'WARNING'}, "Planetka preview object refresh failed.")

        if "FINISHED" not in resolve_result:
            self.report({'WARNING'}, "Planetka Earth created, but initial Resolve failed.")
            return _return_with_selection({'CANCELLED'})

        # Re-apply startup setup after the first successful resolve so scene/UI state
        # reflects the saved startup profile even if intermediate import/sync stages
        # touched navigation/sunlight values.
        try:
            _apply_startup_setup_for_create_earth(scene, props)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: post-resolve startup setup re-apply failed", exc_info=True)
        # Keep Create Earth default texture quality at Preview even after
        # post-resolve startup setup re-apply.
        try:
            props.texture_quality_mode = "PREVIEW"
            _sync_idprops_from_props(scene, ("texture_quality_mode",))
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed enforcing post-resolve Create Earth texture quality mode", exc_info=True)

        _earth_graph_rebind(scene=scene, earth_surface=get_earth_object() or new_obj)

        # Atmosphere and cloud runtime loading is intentionally disabled for now.
        # Keep implementation code in-place for future re-enable.

        _hide_shot_anchor_in_viewport()
        try:
            if _DEFAULT_SCENE_REMOVED_KEY in scene:
                del scene[_DEFAULT_SCENE_REMOVED_KEY]
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed clearing default-scene removal marker", exc_info=True)

        self.report({'INFO'}, "Planetka Earth created successfully.")
        return _return_with_selection({'FINISHED'})


class PLANETKA_OT_CreateStandaloneFile(bpy.types.Operator):
    bl_idname = "planetka.create_standalone_file"
    bl_label = "Create Standalone File"
    bl_description = (
        "Create a portable .blend copy with packed resources for use on machines "
        "without Planetka addon or on render farms"
    )

    filename_ext = ".blend"

    filter_glob: StringProperty(
        default="*.blend",
        options={'HIDDEN'},
    )
    filepath: StringProperty(
        subtype='FILE_PATH',
    )

    def invoke(self, context, event):
        del event
        source_path = str(getattr(bpy.data, "filepath", "") or "").strip()
        if source_path:
            source_abs = os.path.abspath(source_path)
            source_dir = os.path.dirname(source_abs)
            source_name = os.path.splitext(os.path.basename(source_abs))[0] or "PlanetkaScene"
        else:
            source_dir = os.path.expanduser("~")
            source_name = "PlanetkaScene"
        self.filepath = os.path.join(source_dir, f"{source_name}_standalone.blend")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        del context
        source_path = str(getattr(bpy.data, "filepath", "") or "").strip()
        source_abs = os.path.abspath(source_path) if source_path else ""
        output_path = os.path.abspath(os.path.expanduser(str(getattr(self, "filepath", "") or "").strip()))
        if not output_path:
            return fail(self, "Pick output .blend path for standalone file.", logger=logger)
        if not output_path.lower().endswith(".blend"):
            output_path = f"{output_path}.blend"
        if source_abs and os.path.normcase(output_path) == os.path.normcase(source_abs):
            return fail(self, "Standalone file path must be different from current .blend.", logger=logger)

        output_dir = os.path.dirname(output_path)
        if not output_dir:
            return fail(self, "Output folder is invalid.", logger=logger)
        try:
            os.makedirs(output_dir, exist_ok=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            return fail(self, f"Cannot create output folder: {output_dir}", logger=logger)

        blender_binary = str(getattr(bpy.app, "binary_path", "") or "").strip()
        if not blender_binary or not os.path.isfile(blender_binary):
            return fail(self, "Could not locate Blender executable for standalone export.", logger=logger)

        script_path = ""
        temp_source_path = ""
        try:
            source_for_export = source_abs
            source_missing = not source_for_export or not os.path.isfile(source_for_export)
            if source_missing or bool(getattr(bpy.data, "is_dirty", False)):
                fd, temp_source_path = tempfile.mkstemp(suffix="_planetka_standalone_source.blend")
                os.close(fd)
                save_copy_result = bpy.ops.wm.save_as_mainfile(filepath=temp_source_path, copy=True)
                if "FINISHED" not in save_copy_result:
                    return fail(self, "Could not prepare standalone export source copy.", logger=logger)
                source_for_export = temp_source_path

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix="_planetka_standalone_pack.py",
                delete=False,
                encoding="utf-8",
            ) as script_file:
                script_path = script_file.name
                script_content = (
                    "import bpy\n"
                    "import os\n"
                    "import sys\n"
                    "\n"
                    "def _output_path():\n"
                    "    argv = sys.argv\n"
                    "    if '--' not in argv:\n"
                    "        return ''\n"
                    "    idx = argv.index('--')\n"
                    "    if idx + 1 >= len(argv):\n"
                    "        return ''\n"
                    "    return str(argv[idx + 1] or '').strip()\n"
                    "\n"
                    "def _idprop_keys(id_block):\n"
                    "    try:\n"
                    "        return list(id_block.keys())\n"
                    "    except (RuntimeError, TypeError, ValueError, AttributeError):\n"
                    "        return []\n"
                    "\n"
                    "def _has_planetka_runtime_key(id_block):\n"
                    "    for key in _idprop_keys(id_block):\n"
                    "        if str(key).startswith('planetka_'):\n"
                    "            return True\n"
                    "    return False\n"
                    "\n"
                    "def _strip_planetka_runtime_keys(id_block):\n"
                    "    for key in _idprop_keys(id_block):\n"
                    "        if str(key).startswith('planetka_'):\n"
                    "            try:\n"
                    "                del id_block[key]\n"
                    "            except (RuntimeError, TypeError, ValueError, AttributeError, KeyError):\n"
                    "                pass\n"
                    "\n"
                    "def _standalone_name(name):\n"
                    "    text = str(name or '').strip()\n"
                    "    if not text:\n"
                    "        return 'PlanetkaStandalone'\n"
                    "    if text.startswith('PlanetkaStandalone'):\n"
                    "        return text\n"
                    "    if 'Planetka' in text:\n"
                    "        return text.replace('Planetka', 'PlanetkaStandalone', 1)\n"
                    "    return f'PlanetkaStandalone {text}'\n"
                    "\n"
                    "def _rename_datablock(id_block, force_prefix=False):\n"
                    "    if id_block is None:\n"
                    "        return\n"
                    "    try:\n"
                    "        current_name = str(getattr(id_block, 'name', '') or '')\n"
                    "    except (RuntimeError, TypeError, ValueError, AttributeError):\n"
                    "        return\n"
                    "    if not current_name:\n"
                    "        return\n"
                    "    if (not force_prefix) and ('Planetka' not in current_name):\n"
                    "        return\n"
                    "    new_name = _standalone_name(current_name)\n"
                    "    if new_name == current_name:\n"
                    "        return\n"
                    "    try:\n"
                    "        id_block.name = new_name\n"
                    "    except (RuntimeError, TypeError, ValueError, AttributeError):\n"
                    "        pass\n"
                    "\n"
                    "def _rename_and_strip(id_collection, force_predicate=None):\n"
                    "    for datablock in list(id_collection):\n"
                    "        force_prefix = False\n"
                    "        try:\n"
                    "            force_prefix = bool(force_predicate(datablock)) if callable(force_predicate) else False\n"
                    "        except (RuntimeError, TypeError, ValueError, AttributeError):\n"
                    "            force_prefix = False\n"
                    "        if _has_planetka_runtime_key(datablock):\n"
                    "            force_prefix = True\n"
                    "        _rename_datablock(datablock, force_prefix=force_prefix)\n"
                    "        _strip_planetka_runtime_keys(datablock)\n"
                    "\n"
                    "def _is_standalone_name(name):\n"
                    "    text = str(name or '').strip()\n"
                    "    return text.startswith('PlanetkaStandalone')\n"
                    "\n"
                    "def _object_force_prefix(obj):\n"
                    "    try:\n"
                    "        role = str(obj.get('planetka_role', '') or '').strip()\n"
                    "    except (RuntimeError, TypeError, ValueError, AttributeError):\n"
                    "        role = ''\n"
                    "    if role:\n"
                    "        return True\n"
                    "    name = str(getattr(obj, 'name', '') or '')\n"
                    "    if 'Planetka' in name:\n"
                    "        return True\n"
                    "    if name in {'Atmosphere - Volumetric', 'Atmosphere - EEVEE supplement'}:\n"
                    "        return True\n"
                    "    return False\n"
                    "\n"
                    "def _rename_object_bound_data():\n"
                    "    for obj in list(bpy.data.objects):\n"
                    "        obj_name = str(getattr(obj, 'name', '') or '')\n"
                    "        if not _is_standalone_name(obj_name):\n"
                    "            continue\n"
                    "        _rename_datablock(getattr(obj, 'data', None), force_prefix=True)\n"
                    "        for slot in tuple(getattr(obj, 'material_slots', ())):\n"
                    "            _rename_datablock(getattr(slot, 'material', None), force_prefix=True)\n"
                    "\n"
                    "def _detach_planetka_identity():\n"
                    "    _rename_and_strip(bpy.data.objects, force_predicate=_object_force_prefix)\n"
                    "    _rename_object_bound_data()\n"
                    "    for attr_name in (\n"
                    "        'collections',\n"
                    "        'meshes',\n"
                    "        'materials',\n"
                    "        'node_groups',\n"
                    "        'images',\n"
                    "        'cameras',\n"
                    "        'lights',\n"
                    "        'worlds',\n"
                    "        'textures',\n"
                    "        'actions',\n"
                    "        'curves',\n"
                    "        'armatures',\n"
                    "        'volumes',\n"
                    "    ):\n"
                    "        id_collection = getattr(bpy.data, attr_name, None)\n"
                    "        if id_collection is None:\n"
                    "            continue\n"
                    "        _rename_and_strip(id_collection)\n"
                    "    for scene in list(bpy.data.scenes):\n"
                    "        _strip_planetka_runtime_keys(scene)\n"
                    "\n"
                    "def _run(path):\n"
                    "    if not path:\n"
                    "        raise RuntimeError('Missing standalone output path.')\n"
                    "    path = os.path.abspath(os.path.expanduser(path))\n"
                    "    out_dir = os.path.dirname(path)\n"
                    "    if out_dir:\n"
                    "        os.makedirs(out_dir, exist_ok=True)\n"
                    "    _detach_planetka_identity()\n"
                    "    try:\n"
                    "        bpy.ops.file.make_paths_absolute()\n"
                    "    except (RuntimeError, TypeError, ValueError, AttributeError):\n"
                    "        pass\n"
                    "    try:\n"
                    "        bpy.ops.file.pack_all()\n"
                    "    except (RuntimeError, TypeError, ValueError, AttributeError) as exc:\n"
                    "        raise RuntimeError(f'pack_all failed: {exc}')\n"
                    "    result = bpy.ops.wm.save_as_mainfile(filepath=path, copy=False)\n"
                    "    if 'FINISHED' not in result:\n"
                    "        raise RuntimeError('save_as_mainfile failed.')\n"
                    "\n"
                    "if __name__ == '__main__':\n"
                    "    _run(_output_path())\n"
                )
                script_file.write(script_content)

            cmd = [
                blender_binary,
                "-b",
                source_for_export,
                "--python",
                script_path,
                "--",
                output_path,
            ]
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if completed.returncode != 0 or not os.path.isfile(output_path):
                log_tail = ""
                try:
                    lines = str(completed.stdout or "").splitlines()
                    if lines:
                        log_tail = " | ".join(lines[-6:])
                except (RuntimeError, TypeError, ValueError):
                    log_tail = ""
                message = "Standalone export failed."
                if log_tail:
                    message = f"{message} {log_tail}"
                return fail(self, message, logger=logger)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(self, f"Standalone export failed: {exc}", logger=logger)
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            return fail(self, f"Standalone export failed: {exc}", logger=logger)
        finally:
            if script_path:
                try:
                    os.remove(script_path)
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass
            if temp_source_path:
                try:
                    os.remove(temp_source_path)
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass

        self.report({'INFO'}, f"Standalone file created: {output_path}")
        return {'FINISHED'}


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
        _apply_startup_setup_profile(scene, props, factory_profile)
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
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}
        try:
            _apply_navigation_shot(
                context,
                scene,
                props,
                switch_viewport_to_camera=bool(getattr(self, "force_camera_view", True)),
                sync_active_view_when_not_camera=bool(
                    getattr(self, "sync_active_view_when_not_camera", False)
                ),
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Apply Shot failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka apply-shot failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Apply Shot failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        if not bool(getattr(self, "silent", False)):
            self.report({'INFO'}, "Shot updated.")
        return {'FINISHED'}


class PLANETKA_OT_UseCurrentViewNavigation(bpy.types.Operator):
    bl_idname = "planetka.navigation_use_current_view"
    bl_label = "Bring Camera to View"
    bl_description = "Move active camera to current viewport view and sync Navigation values"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        camera = _pick_scene_camera(scene, context=context)
        if camera is None or getattr(camera, "type", None) != 'CAMERA':
            return fail(
                self,
                "No active camera found. Select a camera (or add one) and retry.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        try:
            moved_camera = bool(_camera_to_current_view(scene))
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Bring Camera to View failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka bring_camera_to_view failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Bring Camera to View failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        props = getattr(scene, "planetka", None)
        if props is None:
            if moved_camera:
                self.report({'INFO'}, "Camera brought to current view.")
            else:
                self.report({'INFO'}, "Camera is already in current view.")
            return {'FINISHED'}

        computed = _compute_current_view_navigation_values(scene)
        if computed is None:
            self.report(
                {'WARNING'},
                "Camera updated, but Planetka controls were not synced (Earth is not visible in current view).",
            )
            return {'FINISHED'}
        lat, lon, _alt_km = computed

        try:
            derived = _derive_navigation_shot_from_camera(scene, lon, lat)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'WARNING'}, f"Camera updated, but Planetka controls were not synced: {exc}")
            return {'FINISHED'}
        except (RuntimeError, TypeError, ValueError) as exc:
            self.report({'WARNING'}, f"Camera updated, but Planetka controls were not synced: {exc}")
            return {'FINISHED'}

        try:
            camera_data = getattr(camera, "data", None)
            quantized = _quantize_navigation_ui_payload(
                lat_deg=float(lat),
                lon_deg=float(lon),
                altitude_km=float(derived.get("altitude_km", 0.0)),
                heading_deg=float(derived.get("azimuth_deg", 0.0)),
                tilt_deg=float(derived.get("tilt_deg", 0.0)),
                roll_deg=float(derived.get("roll_deg", 0.0)),
                focal_length_mm=float(getattr(camera_data, "lens", 50.0)) if camera_data is not None else float(getattr(props, "nav_focal_length_mm", 50.0)),
            )
            props.nav_latitude_deg = float(quantized["lat_deg"])
            props.nav_longitude_deg = float(quantized["lon_deg"])
            props.nav_altitude_km = float(quantized["altitude_km"])
            props.nav_azimuth_deg = float(quantized["heading_deg"])
            props.nav_tilt_deg = float(quantized["tilt_deg"])
            props.nav_roll_deg = float(quantized["roll_deg"])
            if camera_data is not None:
                props.nav_focal_length_mm = float(quantized["focal_length_mm"])
            _store_last_navigation_values(
                scene,
                lon_deg=float(props.nav_longitude_deg),
                lat_deg=float(props.nav_latitude_deg),
                altitude_km=float(props.nav_altitude_km),
                heading_deg=float(props.nav_azimuth_deg),
                tilt_deg=float(props.nav_tilt_deg),
                roll_deg=float(props.nav_roll_deg),
            )
        except (AttributeError, TypeError, ValueError):
            self.report({'WARNING'}, "Camera updated, but Planetka controls failed to update.")
            return {'FINISHED'}

        if moved_camera:
            self.report({'INFO'}, "Camera and Navigation fields updated from current view.")
        else:
            self.report({'INFO'}, "Camera is already in current view. Navigation fields synced.")
        return {'FINISHED'}


class PLANETKA_OT_AutoAdjustClipping(bpy.types.Operator):
    bl_idname = "planetka.auto_adjust_clipping"
    bl_label = "Change Clipping Automatically"
    bl_description = (
        "Automatically adjust Camera/Viewport clipping based on current Earth size and camera proximity"
    )

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        earth_obj = get_earth_object()
        if earth_obj is None:
            self.report({'WARNING'}, "Create Earth first, then adjust clipping.")
            return {'CANCELLED'}

        try:
            earth_center = earth_obj.matrix_world.translation.copy()
            earth_radius = float(_earth_radius_blender_units(earth_obj))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self.report({'WARNING'}, "Unable to evaluate Earth radius for clipping adjustment.")
            return {'CANCELLED'}

        if earth_radius <= 0.0:
            self.report({'WARNING'}, "Earth radius is invalid for clipping adjustment.")
            return {'CANCELLED'}

        mode = "CAMERA"
        clip_owner = None
        probe_pos = None

        space = getattr(context, "space_data", None)
        rv3d = getattr(space, "region_3d", None) if space is not None else None
        is_view3d = bool(space is not None and str(getattr(space, "type", "")) == "VIEW_3D")
        in_camera_view = bool(rv3d is not None and str(getattr(rv3d, "view_perspective", "")) == "CAMERA")

        if is_view3d and not in_camera_view and rv3d is not None:
            try:
                view_matrix = rv3d.view_matrix.inverted()
                probe_pos = view_matrix.translation.copy()
                clip_owner = space
                mode = "VIEWPORT"
            except (AttributeError, RuntimeError, TypeError, ValueError):
                clip_owner = None
                probe_pos = None

        if clip_owner is None or probe_pos is None:
            camera = getattr(scene, "camera", None)
            camera_data = getattr(camera, "data", None) if camera is not None else None
            if camera is None or str(getattr(camera, "type", "")) != "CAMERA" or camera_data is None:
                self.report({'WARNING'}, "Active camera not found for clipping adjustment.")
                return {'CANCELLED'}
            try:
                probe_pos = camera.matrix_world.translation.copy()
                clip_owner = camera_data
                mode = "CAMERA"
            except (AttributeError, RuntimeError, TypeError, ValueError):
                self.report({'WARNING'}, "Unable to read camera clipping values.")
                return {'CANCELLED'}

        try:
            clip_start = float(getattr(clip_owner, "clip_start", 0.0))
            clip_end = float(getattr(clip_owner, "clip_end", 0.0))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self.report({'WARNING'}, "Unable to read clipping values.")
            return {'CANCELLED'}

        if clip_start <= 0.0 or clip_end <= 0.0:
            self.report({'WARNING'}, "Clipping values must be positive.")
            return {'CANCELLED'}

        try:
            proximity_bu = float((probe_pos - earth_center).length) - float(earth_radius)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self.report({'WARNING'}, "Unable to evaluate camera proximity for clipping adjustment.")
            return {'CANCELLED'}

        breach_min = bool(proximity_bu < clip_start)
        breach_max = bool(proximity_bu > clip_end)
        if not breach_min and not breach_max:
            self.report({'INFO'}, "Clipping is already within range.")
            return {'CANCELLED'}

        new_start = float(clip_start)
        new_end = float(clip_end)

        if breach_min:
            new_start = max(1e-9, float(clip_start) / 10.0)
        if breach_max:
            new_end = max(new_start * 1.000001, float(clip_end) * 10.0)

        if new_end <= new_start:
            new_end = max(new_start * 10.0, new_start + 1e-9)

        max_ratio = 10_000_000.0
        ratio = float(new_end) / max(float(new_start), 1e-9)
        if ratio > max_ratio:
            if breach_max and not breach_min:
                new_start = max(1e-9, float(new_end) / max_ratio)
            else:
                new_end = float(new_start) * max_ratio

        try:
            clip_owner.clip_start = float(new_start)
            clip_owner.clip_end = float(new_end)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self.report({'WARNING'}, "Failed applying clipping changes.")
            return {'CANCELLED'}

        target_label = "Viewport" if mode == "VIEWPORT" else "Camera"
        self.report(
            {'INFO'},
            f"{target_label} clipping adjusted (start={new_start:.6g}, end={new_end:.6g}).",
        )
        return {'FINISHED'}


class PLANETKA_OT_ResetEarthTransform(bpy.types.Operator):
    bl_idname = "planetka.reset_earth_transform"
    bl_label = "Reset Transform"
    bl_description = "Reset Planetka Root Location and Rotation to defaults (0, 0, 0)"

    def execute(self, context):
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}

        root = bpy.data.objects.get(PLANETKA_ROOT_OBJECT_NAME)
        if root is None:
            return fail(
                self,
                "Planetka Root not found. Create Earth first.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
        if str(getattr(root, "type", "")) != "EMPTY":
            return fail(
                self,
                "Planetka Root has invalid type.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
        if root not in tuple(getattr(scene, "objects", ())):
            return fail(
                self,
                "Planetka Root is not in active scene.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        try:
            root.location = (0.0, 0.0, 0.0)
            root.rotation_euler = (0.0, 0.0, 0.0)
        except (PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            return fail(
                self,
                "Failed to reset Planetka Root transform.",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        self.report({'INFO'}, "Planetka Root transform reset.")
        return {'FINISHED'}


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
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        earth_obj = get_earth_object()
        if earth_obj is None:
            return fail(
                self,
                "Create Earth first, then use Navigation presets.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )
        if getattr(scene, "camera", None) is None:
            return fail(
                self,
                "Scene camera is missing. Set an active camera and retry.",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        earth_radius_bu = _earth_radius_blender_units(earth_obj)
        preset = str(getattr(self, "preset", "ISS_ORBIT"))
        if preset == "ISS_ORBIT":
            props.nav_altitude_km = 400.0
        elif preset == "SENTINEL2":
            # ESA Sentinel-2 nominal sun-synchronous orbit altitude.
            props.nav_altitude_km = 786.0
        elif preset == "HIGH_ORBIT":
            full_globe_km = _full_globe_altitude_km(scene, earth_radius_bu)
            if full_globe_km is not None:
                props.nav_altitude_km = max(0.0, float(full_globe_km))
            ortho_adjusted = _ensure_ortho_full_globe_if_needed(scene, earth_radius_bu)
            if ortho_adjusted:
                self.report({'INFO'}, "Orthographic scale expanded to fit full globe with margin.")
        elif preset == "MAX_PROXIMITY":
            lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
            lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
            max_km, note = _max_proximity_altitude_km(scene, earth_obj, earth_radius_bu, lon_deg, lat_deg)
            if max_km is None:
                return fail(
                    self,
                    "Unable to compute Max Proximity for current camera.",
                    code=ErrorCode.NAV_PRECHECK_FAILED,
                    logger=logger,
                )
            props.nav_altitude_km = max(0.0, float(max_km))
            if note:
                self.report({'INFO'}, note)
        else:
            return fail(
                self,
                f"Unknown navigation preset: {preset}",
                code=ErrorCode.NAV_PRECHECK_FAILED,
                logger=logger,
            )

        try:
            if preset == "HIGH_ORBIT":
                lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
                lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
                altitude_km = float(getattr(props, "nav_altitude_km", 0.0))
                _navigate_camera_internal(
                    scene,
                    lon_deg,
                    lat_deg,
                    altitude_km,
                    look_at_center=True,
                )
                earth_obj = get_earth_object()
                if earth_obj is not None:
                    anchor_world, east_world, north_world, up_world, _radius = _anchor_frame_world(
                        earth_obj,
                        lon_deg,
                        lat_deg,
                    )
                    _update_shot_anchor_object(scene, anchor_world, east_world, north_world, up_world)
                _ensure_close_clip_limits(scene, min_clip=0.001)
                _switch_viewport_to_camera_view(context, scene)
            else:
                _apply_navigation_shot(context, scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(
                self,
                f"Navigation preset apply failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
                exc=exc,
                log_message="Planetka navigation preset apply failed",
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            return fail(
                self,
                f"Navigation preset apply failed: {exc}",
                code=ErrorCode.NAV_APPLY_FAILED,
                logger=logger,
            )

        if preset == "HIGH_ORBIT":
            preset_label = "Full Globe"
        elif preset == "SENTINEL2":
            preset_label = "ESA Sentinel-2"
        elif preset == "ISS_ORBIT":
            preset_label = "ISS Orbit"
        elif preset == "MAX_PROXIMITY":
            preset_label = "Max Proximity"
        else:
            preset_label = preset.replace('_', ' ').title()
        self.report({'INFO'}, f"Navigation preset applied: {preset_label}.")
        return {'FINISHED'}


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
        scene = require_scene(self, context, logger=logger)
        if scene is None:
            return {'CANCELLED'}
        props = require_planetka_props(self, context, logger=logger)
        if props is None:
            return {'CANCELLED'}

        try:
            lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
            lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
        except (TypeError, ValueError):
            lon_deg = 0.0
            lat_deg = 0.0

        lon = math.radians(lon_deg)
        lat = math.radians(lat_deg)

        up = Vector(
            (
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            )
        )
        if up.length < 1e-9:
            return {'CANCELLED'}
        up.normalize()
        east = Vector((-math.sin(lon), math.cos(lon), 0.0))
        if east.length < 1e-9:
            east = Vector((0.0, 1.0, 0.0))
        east.normalize()
        west = -east

        preset = str(getattr(self, "preset", "NOON") or "NOON").upper()
        if preset == "NOON":
            sun_dir = up
        elif preset == "NIGHT":
            sun_dir = -up
        else:
            if preset in {"DAWN", "DUSK"}:
                elev_deg = 0.5
            elif preset in {"SUNRISE", "SUNSET"}:
                elev_deg = 6.0
            elif preset in {"EARLY_MORNING", "LATE_AFTERNOON"}:
                elev_deg = 25.0
            else:
                elev_deg = 45.0

            horiz = east if preset in {"DAWN", "SUNRISE", "EARLY_MORNING", "MID_MORNING"} else west
            elev = math.radians(elev_deg)
            sun_dir = (horiz * math.cos(elev)) + (up * math.sin(elev))
            if sun_dir.length < 1e-9:
                sun_dir = up
            sun_dir.normalize()

        try:
            sun_lon = math.degrees(math.atan2(float(sun_dir.y), float(sun_dir.x)))
            sun_lat = math.degrees(math.asin(max(-1.0, min(1.0, float(sun_dir.z)))))
            sun_lat = max(-23.5, min(23.5, float(sun_lat)))
            props.sunlight_longitude_deg = float(sun_lon)
            props.sunlight_seasonal_tilt_deg = float(sun_lat)
            props.sunlight_last_preset = preset
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed setting sunlight preset properties", exc_info=True)
        except (RuntimeError, TypeError, ValueError):
            logger.debug("Planetka: failed setting sunlight preset properties", exc_info=True)

        self.report({'INFO'}, f"Sunlight preset applied: {preset.replace('_', ' ').title()}.")
        return {'FINISHED'}
