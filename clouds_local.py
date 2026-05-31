import importlib
import hashlib
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import bpy
import bpy.utils.previews
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from mathutils import Vector

from .asset_builder import ensure_planetka_root
from .auth import get_api_base_url, is_authenticated
from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_earth_object, get_prefs
from .r2_source import get_remote_cache_folder


logger = logging.getLogger(__name__)
_RECOVERABLE_LOG_COUNTS = {}


def _log_recoverable_once(code, message):
    count = int(_RECOVERABLE_LOG_COUNTS.get(code, 0))
    if count < 3:
        logger.debug("[%s] %s", code, message, exc_info=True)
    elif count == 3:
        logger.debug("[%s] %s (further occurrences suppressed)", code, message)
    _RECOVERABLE_LOG_COUNTS[code] = count + 1

COMMERCIAL_REFERENCE_BLEND_PATH = os.path.abspath(
    os.getenv(
        "PLANETKA_CLOUDS_REFERENCE_BLEND_PATH",
        "/Volumes/SSDA/Projects/planetka_commercial/Planetka.blend",
    ),
)
GLOBAL_CLOUD_REFERENCE_BLEND_PATH = os.path.join(
    os.path.dirname(__file__),
    "Resources",
    "planetka_global_cloud_layer_min.blend",
)
LOCAL_CLOUD_REFERENCE_BLEND_PATH = os.path.join(
    os.path.dirname(__file__),
    "Resources",
    "planetka_local_cloud_material.blend",
)
VDB_CLOUD_REFERENCE_BLEND_PATH = os.path.join(
    os.path.dirname(__file__),
    "Resources",
    "planetka_vdb_cloud_template.blend",
)
REMOTE_GLOBAL_CLOUDS_FOLDER = "clouds_global"
REMOTE_GLOBAL_CLOUD_TEXTURE_FILE = "Clouds_16K.exr"
REMOTE_LOCAL_CLOUDS_FOLDER = "clouds_local"
LOCAL_CLOUD_GPU_TEXTURES_FOLDER = "clouds_local_gpu"
LOCAL_CLOUD_ADAPTIVE_TEXTURES_FOLDER = "clouds_local_adaptive"
REMOTE_LOCAL_CLOUD_THUMBNAILS_FOLDER = "clouds_local_thumbnails_v3"
REMOTE_VDB_CLOUDS_FOLDER = "clouds_vdb"
REMOTE_VDB_CLOUD_THUMBNAILS_FOLDER = "clouds_vdb_thumbnails_v1"
REMOTE_LOCAL_CLOUD_FILES = (
    "Planetka Cloud 001 18000x12500.exr",
    "Planetka Cloud 002 23300x16900.exr",
    "Planetka Cloud 003 18100x13800.exr",
    "Planetka Cloud 004 28100x16700.exr",
    "Planetka Cloud 005 4700x4400.exr",
    "Planetka Cloud 006 6300x6700.exr",
    "Planetka Cloud 007 16600x11900.exr",
    "Planetka Cloud 008 14900x8200.exr",
    "Planetka Cloud 009 15000x10000.exr",
    "Planetka Cloud 010 19000x8900.exr",
    "Planetka Cloud 011 14700x8900.exr",
    "Planetka Cloud 012 7600x5500.exr",
    "Planetka Cloud 013 25000x11000.exr",
    "Planetka Cloud 014 16800x12100.exr",
    "Planetka Cloud 015 11500x9500.exr",
    "Planetka Cloud 016 21600x9900.exr",
    "Planetka Cloud 017 16400x9200.exr",
    "Planetka Cloud 018 10100x12300.exr",
    "Planetka Cloud 019 14600x14600.exr",
    "Planetka Cloud 020 11400x10500.exr",
    "Planetka Cloud 021 10600x10200.exr",
    "Planetka Cloud 022 13400x10700.exr",
    "Planetka Cloud 023 8000x6200.exr",
)
REMOTE_VDB_CLOUD_FILES = (
    "cloud001_vox063_60.vdb",
    "cloud001_vox063_90.vdb",
    "cloud001_vox063_120.vdb",
    "cloud001_vox063_150.vdb",
    "cloud002_vox063_60.vdb",
    "cloud002_vox063_90.vdb",
    "cloud002_vox063_120.vdb",
    "cloud002_vox063_150.vdb",
    "cloud003_vox063_60.vdb",
    "cloud003_vox063_90.vdb",
    "cloud003_vox063_120.vdb",
    "cloud003_vox063_150.vdb",
    "cloud004_vox063_60.vdb",
    "cloud004_vox063_90.vdb",
    "cloud004_vox063_120.vdb",
    "cloud004_vox063_150.vdb",
    "cloud005_vox063_60.vdb",
    "cloud005_vox063_90.vdb",
    "cloud005_vox063_120.vdb",
)
CLOUDS_ROOT_COLLECTION_NAME = "Clouds"
GLOBAL_CLOUDS_COLLECTION_NAME = "Global Clouds"
LOCAL_CLOUDS_COLLECTION_NAME = "Texture-Based Clouds"
VDB_CLOUDS_COLLECTION_NAME = "VDB Clouds"

GLOBAL_CLOUD_LAYER_NAME = "Planetka Global Cloud Layer"
GLOBAL_CLOUD_MATERIAL_NAME = "Planetka Global Clouds Shader"
GLOBAL_CLOUD_IMAGE_NODE_NAME = "Global Clouds Texture"
GLOBAL_CLOUD_RELATIVE_SCALE = 1.00157
LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME = "Planetka Local Clouds Shader"
VDB_CLOUD_TEMPLATE_OBJECT_NAME = "Planetka Cloud VDB"
VDB_CLOUD_MATERIAL_TEMPLATE_NAME = "Planetka VDB Cloud Shader"

CLOUD_MATERIAL_GROUP_NAME = "Planetka Cloud Material"
LEGACY_LOCAL_CLOUD_SHADER_GROUP_NAME = "Planetka Local Clouds Shader Group"
GLOBAL_CLOUD_SHADER_GROUP_NAME = "Planetka Global Clouds Shader Group"
CLOUD_PREVIEW_SWITCH_GROUP_NAME = "Cloud Preview Switch"
LOCAL_CLOUD_PREVIEW_VALUE_NODE_NAME = "Preview_On_Off"
LOCAL_CLOUD_PREVIEW_INPUT_NAMES = ("Preview_On_Off", "Preview On Off")

LOCAL_CLOUD_LON_NODE_NAMES = ("Target Longitude -90 (deg)", "Target Longitude (deg)")
LOCAL_CLOUD_LAT_NODE_NAMES = ("Target Latitude +90 (deg)", "Target Latitude (deg)")
LOCAL_CLOUD_SIZE_NODE_NAMES = ("Local Cloud Size (deg)", "Local Cloud Size")
LOCAL_CLOUD_ROT_NODE_NAMES = ("Local Cloud Rotation (deg)", "Local Cloud Rotation")

LOCAL_CLOUD_NUMBERED_PREFIX = "Texture-Based Cloud No "
VDB_CLOUD_NUMBERED_PREFIX = "VDB Cloud No "
LOCAL_CLOUD_CAP_MESH_PREFIX = "Planetka Texture-Based Cloud Cap Mesh"

CLOUD_ROLE_KEY = "planetka_cloud_role"
GLOBAL_CLOUD_ROLE = "global_cloud"
LOCAL_CLOUD_ROLE = "local_cloud"
VDB_CLOUD_ROLE = "vdb_cloud"
GLOBAL_CLOUD_TEMPLATE_ROLE = "global_cloud_template"
VDB_CLOUD_TEMPLATE_ROLE = "vdb_cloud_template"

LOCAL_CLOUD_PROP_LONGITUDE = "planetka_local_cloud_longitude"
LOCAL_CLOUD_PROP_LATITUDE = "planetka_local_cloud_latitude"
LOCAL_CLOUD_PROP_ALTITUDE_M = "planetka_local_cloud_altitude_m"
LOCAL_CLOUD_PROP_SIZE_COEF = "planetka_local_cloud_size_coef"
LOCAL_CLOUD_PROP_ROTATION_DEG = "planetka_local_cloud_rotation_deg"
LOCAL_CLOUD_PROP_THICKNESS_M = "planetka_local_cloud_thickness_m"
LOCAL_CLOUD_PROP_CLOUD_COLOR = "planetka_local_cloud_color"
LOCAL_CLOUD_PROP_DENSITY = "planetka_local_cloud_density"
LOCAL_CLOUD_PROP_DENSITY_GAMMA = "planetka_local_cloud_density_gamma"
LOCAL_CLOUD_PROP_CONTRAST = "planetka_local_cloud_contrast"
LOCAL_CLOUD_PROP_HORIZON_TRANSPARENCY = "planetka_local_cloud_horizon_transparency"
LOCAL_CLOUD_PROP_SUBSURFACE_SCALE = "planetka_local_cloud_subsurface_scale"
LOCAL_CLOUD_PROP_IOR = "planetka_local_cloud_ior"
LOCAL_CLOUD_PROP_ROUGHNESS = "planetka_local_cloud_roughness"
LOCAL_CLOUD_PROP_ANISOTROPY = "planetka_local_cloud_anisotropy"
LOCAL_CLOUD_PROP_DISPLACEMENT_SCALE = "planetka_local_cloud_displacement_scale"
LOCAL_CLOUD_PROP_BASE_SCALE = "planetka_local_cloud_base_scale"
LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG = "planetka_local_cloud_cap_half_angle_deg"
LOCAL_CLOUD_OBJ_TEXTURE_PROP = "planetka_local_cloud_texture"
LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP = "planetka_local_cloud_texture_path"

VDB_CLOUD_PROP_LONGITUDE = "planetka_vdb_cloud_longitude"
VDB_CLOUD_PROP_LATITUDE = "planetka_vdb_cloud_latitude"
VDB_CLOUD_PROP_ALTITUDE_M = "planetka_vdb_cloud_altitude_m"
VDB_CLOUD_PROP_SIZE_COEF = "planetka_vdb_cloud_size_coef"
VDB_CLOUD_PROP_ROTATION_DEG = "planetka_vdb_cloud_rotation_deg"
VDB_CLOUD_PROP_DENSITY = "planetka_vdb_cloud_density"
VDB_CLOUD_PROP_BASE_SCALE_X = "planetka_vdb_cloud_base_scale_x"
VDB_CLOUD_PROP_BASE_SCALE_Y = "planetka_vdb_cloud_base_scale_y"
VDB_CLOUD_PROP_BASE_SCALE_Z = "planetka_vdb_cloud_base_scale_z"
VDB_CLOUD_PROP_BASE_RADIUS = "planetka_vdb_cloud_base_radius"
VDB_CLOUD_OBJ_FILE_PROP = "planetka_vdb_cloud_file"
VDB_CLOUD_OBJ_SOURCE_FILE_PROP = "planetka_vdb_cloud_source_file"
VDB_CLOUD_LOADED_FILE_PROP = "planetka_vdb_cloud_loaded_file"
VDB_CLOUD_D_LEVEL_PROP = "planetka_vdb_cloud_d_level"
VDB_CLOUD_FINAL_FILE_PROP = "planetka_vdb_cloud_final_file"
VDB_CLOUD_BALANCED_FILE_PROP = "planetka_vdb_cloud_balanced_file"
VDB_CLOUD_PREVIEW_FILE_PROP = "planetka_vdb_cloud_preview_file"
VDB_CLOUD_FINAL_D_LEVEL_PROP = "planetka_vdb_cloud_final_d_level"
VDB_CLOUD_BALANCED_D_LEVEL_PROP = "planetka_vdb_cloud_balanced_d_level"
VDB_CLOUD_PREVIEW_D_LEVEL_PROP = "planetka_vdb_cloud_preview_d_level"
VDB_CLOUD_PROJECTED_PIXELS_PROP = "planetka_vdb_cloud_projected_pixels"
VDB_CLOUD_DENSITY_NODE_NAME = "VDB Density"
DEFAULT_CLOUD_ALTITUDE_M = 2000.0
DEFAULT_VDB_CLOUD_DENSITY = 1.0
VDB_CLOUD_REFERENCE_EARTH_RADIUS_BU = 2.0
VDB_CLOUD_DEFAULT_SCALE_FACTOR = 5e-6
VDB_CLOUD_SCALE_CALIBRATED_PROP = "planetka_vdb_cloud_scale_calibrated"
VDB_CLOUD_ADAPTIVE_D_LEVELS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 360)
VDB_CLOUD_ADAPTIVE_OVERSAMPLE = 1.15
_VDB_CLOUD_FULL_LOD_LEVELS = tuple(level for level in VDB_CLOUD_ADAPTIVE_D_LEVELS if int(level) > 1)
LOCAL_CLOUD_GPU_TEXTURE_MAX_SIZE_FALLBACK = 16384
LOCAL_CLOUD_GPU_TEXTURE_MAX_SIZE_MIN = 1024
LOCAL_CLOUD_BASE_HALF_ANGLE_DEG = 0.08
LOCAL_CLOUD_SIZE_REMOTE_SCALE = 0.01
LOCAL_CLOUD_ADAPTIVE_D_LEVELS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 360)
LOCAL_CLOUD_ADAPTIVE_OVERSAMPLE = 1.15
LOCAL_CLOUD_ANISOTROPY_DEFAULT = 0.98
LOCAL_CLOUD_DISPLACEMENT_SCALE_DEFAULT = 0.02
LOCAL_CLOUD_D_LEVEL_PROP = "planetka_texture_based_cloud_d_level"
LOCAL_CLOUD_PROJECTED_PIXELS_PROP = "planetka_texture_based_cloud_projected_pixels"
LOCAL_CLOUD_LOADED_TEXTURE_PROP = "planetka_texture_based_cloud_loaded_texture"
LOCAL_CLOUD_FINAL_TEXTURE_PROP = "planetka_texture_based_cloud_final_texture"
LOCAL_CLOUD_BALANCED_TEXTURE_PROP = "planetka_texture_based_cloud_balanced_texture"
LOCAL_CLOUD_PREVIEW_TEXTURE_PROP = "planetka_texture_based_cloud_preview_texture"
LOCAL_CLOUD_FINAL_D_LEVEL_PROP = "planetka_texture_based_cloud_final_d_level"
LOCAL_CLOUD_BALANCED_D_LEVEL_PROP = "planetka_texture_based_cloud_balanced_d_level"
LOCAL_CLOUD_PREVIEW_D_LEVEL_PROP = "planetka_texture_based_cloud_preview_d_level"
LOCAL_CLOUD_GPU_LIMIT_PROP = "planetka_texture_based_cloud_gpu_limit_px"
LOCAL_CLOUD_DOWNSCALE_WARNING_PROP = "planetka_texture_based_cloud_downscale_warning"

_local_cloud_preview_collection = None
_local_cloud_preview_signature = None
_local_cloud_enum_items = []
_vdb_cloud_preview_collection = None
_vdb_cloud_preview_signature = None
_vdb_cloud_enum_items = []
_cloud_update_suspend_count = 0
_local_cloud_asset_paths = {}
_local_cloud_thumbnail_paths = {}
_vdb_cloud_asset_paths = {}
_vdb_cloud_thumbnail_paths = {}


def _normalize_cloud_quality_mode(value):
    token = str(value or "").strip().upper()
    if token in {"FULL", "BALANCED", "PREVIEW"}:
        return token
    return "PREVIEW"


def _cloud_quality_d_multiplier(value):
    mode = _normalize_cloud_quality_mode(value)
    if mode == "FULL":
        return 1
    if mode == "BALANCED":
        return 2
    return 4
_cloud_download_progress = {
    "active": False,
    "label": "",
    "file_name": "",
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "error": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}
_cloud_download_progress_lock = threading.Lock()
_cloud_optimize_progress = {
    "active": False,
    "label": "",
    "current": 0,
    "total": 0,
    "optimized": 0,
    "failed": 0,
    "error": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}
_cloud_optimize_progress_lock = threading.Lock()


def _is_cloud_updates_suspended():
    return _cloud_update_suspend_count > 0


def _begin_cloud_update_suspend():
    global _cloud_update_suspend_count
    _cloud_update_suspend_count += 1


def _end_cloud_update_suspend():
    global _cloud_update_suspend_count
    _cloud_update_suspend_count = max(0, _cloud_update_suspend_count - 1)


def _sync_scene_idprops(scene, prop_names=None):
    if scene is None:
        return
    module_name = f"{__package__}.state" if __package__ else "state"
    try:
        state_module = importlib.import_module(module_name)
    except ImportError:
        return
    sync_fn = getattr(state_module, "_sync_idprops_from_props", None)
    if callable(sync_fn):
        try:
            sync_fn(scene, prop_names=prop_names)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed syncing idprops", exc_info=True)


def _get_clouds_global_module():
    module_name = f"{__package__}.clouds_global" if __package__ else "clouds_global"
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


def _local_clouds_dir():
    return get_remote_cache_folder(REMOTE_LOCAL_CLOUDS_FOLDER)


def _local_cloud_thumbnails_dir():
    return get_remote_cache_folder(REMOTE_LOCAL_CLOUD_THUMBNAILS_FOLDER)


def _vdb_clouds_dir():
    return get_remote_cache_folder(REMOTE_VDB_CLOUDS_FOLDER)


def _vdb_cloud_thumbnails_dir():
    return get_remote_cache_folder(REMOTE_VDB_CLOUD_THUMBNAILS_FOLDER)


def _local_cloud_gpu_textures_dir():
    return get_remote_cache_folder(LOCAL_CLOUD_GPU_TEXTURES_FOLDER)


def _local_cloud_adaptive_textures_dir():
    return get_remote_cache_folder(LOCAL_CLOUD_ADAPTIVE_TEXTURES_FOLDER)


def _set_cloud_download_progress(**updates):
    with _cloud_download_progress_lock:
        _cloud_download_progress.update(updates)


def get_cloud_download_progress():
    with _cloud_download_progress_lock:
        return dict(_cloud_download_progress)


def _set_cloud_optimize_progress(**updates):
    with _cloud_optimize_progress_lock:
        _cloud_optimize_progress.update(updates)


def get_cloud_optimize_progress():
    with _cloud_optimize_progress_lock:
        return dict(_cloud_optimize_progress)


def _download_public_cloud_asset(folder, file_name, progress_label=""):
    safe_folder = str(folder or "").strip().strip("/").replace("\\", "/")
    safe_name = os.path.basename(str(file_name or ""))
    if not safe_folder or not safe_name:
        return ""

    cache_dir = get_remote_cache_folder(safe_folder)
    if not cache_dir:
        return ""
    destination = os.path.join(cache_dir, safe_name)
    if os.path.isfile(destination) and os.path.getsize(destination) > 0:
        if progress_label:
            _set_cloud_download_progress(active=False, label=str(progress_label), error="", file_name=safe_name)
        return destination

    base_url = get_api_base_url().rstrip("/")
    url = f"{base_url}/tiles/{urllib.parse.quote(safe_folder, safe='')}/{urllib.parse.quote(safe_name, safe='')}"
    temp_path = f"{destination}.part.{os.getpid()}"
    try:
        os.makedirs(cache_dir, exist_ok=True)
        if progress_label:
            _set_cloud_download_progress(
                active=True,
                label=str(progress_label),
                file_name=safe_name,
                downloaded_bytes=0,
                total_bytes=0,
                error="",
                started_at=time.time(),
                finished_at=0.0,
            )
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "Planetka-Blender"})
        with urllib.request.urlopen(request, timeout=120) as response, open(temp_path, "wb") as handle:
            total_bytes = 0
            try:
                total_bytes = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total_bytes = 0
            if progress_label:
                _set_cloud_download_progress(
                    active=True,
                    label=str(progress_label),
                    file_name=safe_name,
                    downloaded_bytes=0,
                    total_bytes=max(0, total_bytes),
                    error="",
                    started_at=time.time(),
                    finished_at=0.0,
                )
            downloaded_bytes = 0
            while True:
                chunk = response.read(4 * 1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded_bytes += len(chunk)
                if progress_label:
                    _set_cloud_download_progress(downloaded_bytes=downloaded_bytes, total_bytes=max(total_bytes, downloaded_bytes))
        os.replace(temp_path, destination)
        if progress_label:
            final_size = os.path.getsize(destination) if os.path.isfile(destination) else 0
            _set_cloud_download_progress(
                active=False,
                downloaded_bytes=final_size,
                total_bytes=final_size,
                finished_at=time.time(),
            )
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError, ValueError):
        logger.debug("Planetka clouds: failed downloading public cloud asset", exc_info=True)
        if progress_label:
            _set_cloud_download_progress(
                active=False,
                label=str(progress_label),
                file_name=safe_name,
                error=f"Failed downloading {safe_name}",
                finished_at=time.time(),
            )
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return ""
    return destination if os.path.isfile(destination) and os.path.getsize(destination) > 0 else ""


def _clear_cloud_download_progress_error(progress_label="", file_name=""):
    if progress_label:
        _set_cloud_download_progress(
            active=False,
            label=str(progress_label),
            file_name=os.path.basename(str(file_name or "")),
            error="",
            finished_at=time.time(),
        )


def _refresh_remote_local_cloud_assets(force=False):
    global _local_cloud_asset_paths

    if _local_cloud_asset_paths:
        return dict(_local_cloud_asset_paths)

    resolved = {}
    cache_dir = _local_clouds_dir()
    for file_name in REMOTE_LOCAL_CLOUD_FILES:
        path = ""
        if cache_dir:
            candidate = os.path.join(cache_dir, file_name)
            if os.path.isfile(candidate):
                path = candidate
        if path and os.path.isfile(path):
            resolved[file_name] = path
    _local_cloud_asset_paths = resolved
    return dict(_local_cloud_asset_paths)


def _resolve_remote_local_cloud_asset(file_name, progress_label=""):
    global _local_cloud_asset_paths

    safe_name = os.path.basename(str(file_name or ""))
    if safe_name not in REMOTE_LOCAL_CLOUD_FILES:
        return ""

    cached = _refresh_remote_local_cloud_assets(force=False).get(safe_name, "")
    if cached and os.path.isfile(cached):
        if progress_label:
            _set_cloud_download_progress(active=False, error="", file_name=safe_name)
        return cached

    try:
        resolved = _download_public_cloud_asset(REMOTE_LOCAL_CLOUDS_FOLDER, safe_name, progress_label=progress_label)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed resolving selected local cloud texture asset", exc_info=True)
        resolved = ""
    if resolved and os.path.isfile(resolved):
        _local_cloud_asset_paths[safe_name] = resolved
        return resolved
    return ""


def _local_cloud_thumbnail_file_name(file_name):
    safe_name = os.path.basename(str(file_name or ""))
    stem, _ext = os.path.splitext(safe_name)
    return f"{stem}.png" if stem else ""


def _remote_local_cloud_adaptive_file_name(file_name, d_level):
    safe_name = os.path.basename(str(file_name or ""))
    stem, _ext = os.path.splitext(safe_name)
    if not stem:
        return ""
    try:
        level = max(1, int(d_level))
    except (TypeError, ValueError):
        level = 1
    return f"{stem}_d{level:03d}.exr"


def _remote_local_cloud_source_dimensions(file_name):
    safe_name = os.path.basename(str(file_name or ""))
    match = re.search(r"(\d+)x(\d+)", safe_name)
    if not match:
        return None
    try:
        width = int(match.group(1))
        height = int(match.group(2))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _magick_binary():
    return shutil.which("magick") or shutil.which("convert")


def _identify_image_dimensions(path):
    source = os.path.abspath(str(path or ""))
    if not source or not os.path.isfile(source):
        return None
    try:
        import OpenImageIO as oiio
        image_input = oiio.ImageInput.open(source)
        if image_input:
            try:
                spec = image_input.spec()
                width = int(getattr(spec, "width", 0) or 0)
                height = int(getattr(spec, "height", 0) or 0)
                if width > 0 and height > 0:
                    return width, height
            finally:
                image_input.close()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka clouds: OpenImageIO failed identifying local cloud texture dimensions", exc_info=True)

    magick = _magick_binary()
    if not magick:
        return None
    try:
        output = subprocess.check_output(
            [magick, "identify", "-format", "%w %h", source],
            stderr=subprocess.DEVNULL,
            timeout=30,
            text=True,
        )
        parts = str(output or "").strip().split()
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except (OSError, subprocess.SubprocessError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka clouds: failed identifying local cloud texture dimensions", exc_info=True)
    return None


def _write_resized_local_cloud_exr_proxy(source_path, target_path, edge):
    source = os.path.abspath(str(source_path or ""))
    target = os.path.abspath(str(target_path or ""))
    if not source or not target or not os.path.isfile(source):
        return False
    try:
        import OpenImageIO as oiio
        source_buf = oiio.ImageBuf(source)
        source_spec = source_buf.spec()
        source_width = max(1, int(getattr(source_spec, "width", 0) or 0))
        source_height = max(1, int(getattr(source_spec, "height", 0) or 0))
        channels = max(1, int(getattr(source_spec, "nchannels", 0) or 0))
        if source_width <= 0 or source_height <= 0:
            return False
        scale = min(1.0, float(max(1, int(edge))) / float(max(source_width, source_height)))
        target_width = max(1, int(round(source_width * scale)))
        target_height = max(1, int(round(source_height * scale)))
        target_spec = oiio.ImageSpec(target_width, target_height, channels, oiio.HALF)
        target_buf = oiio.ImageBuf(target_spec)
        if not oiio.ImageBufAlgo.resize(target_buf, source_buf, "lanczos3"):
            logger.debug("Planetka clouds: OpenImageIO resize failed: %s %s", source_buf.geterror(), target_buf.geterror())
            return False
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not target_buf.write(target):
            logger.debug("Planetka clouds: OpenImageIO write failed: %s", target_buf.geterror())
            return False
        return os.path.isfile(target) and os.path.getsize(target) > 0
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka clouds: failed creating OpenImageIO local cloud EXR proxy", exc_info=True)
    return False


def _set_cloud_mask_image_colorspace(image):
    if image is None:
        return
    settings = getattr(image, "colorspace_settings", None)
    if settings is None or not hasattr(settings, "name"):
        return
    candidates = ("Non-Color", "Raw", "Linear Rec.709", "Linear")
    available = set()
    try:
        prop = settings.bl_rna.properties.get("name")
        if prop and hasattr(prop, "enum_items"):
            available = {item.identifier for item in prop.enum_items}
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        available = set()
    for candidate in candidates:
        if available and candidate not in available:
            continue
        try:
            settings.name = candidate
            return
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue


def _local_cloud_prepared_texture_needs_refresh(texture_path):
    path = os.path.normcase(os.path.normpath(str(texture_path or "")))
    if not path:
        return False
    _, ext = os.path.splitext(path)
    if ext.lower() != ".png":
        return False
    cache_markers = (
        os.path.normcase(os.path.normpath(LOCAL_CLOUD_GPU_TEXTURES_FOLDER)),
        os.path.normcase(os.path.normpath(LOCAL_CLOUD_ADAPTIVE_TEXTURES_FOLDER)),
        os.path.normcase(os.path.normpath(REMOTE_LOCAL_CLOUD_THUMBNAILS_FOLDER)),
    )
    return any(marker and marker in path for marker in cache_markers)



def _queried_gpu_texture_max_size():
    try:
        import gpu
        max_size = int(gpu.capabilities.max_texture_size_get())
        if max_size > 0:
            return max_size
    except (ImportError, AttributeError, RuntimeError, SystemError, TypeError, ValueError):
        pass
    return 0


def _effective_local_cloud_gpu_texture_max_size():
    """Return the maximum safe 2D texture edge for this Blender GPU backend."""
    env_value = str(os.getenv("PLANETKA_CLOUD_MAX_TEXTURE_SIZE", "") or "").strip()
    if env_value:
        try:
            override = int(float(env_value))
            if override > 0:
                return max(int(LOCAL_CLOUD_GPU_TEXTURE_MAX_SIZE_MIN), override)
        except (TypeError, ValueError):
            pass
    queried = _queried_gpu_texture_max_size()
    if queried > 0:
        return max(int(LOCAL_CLOUD_GPU_TEXTURE_MAX_SIZE_MIN), queried)
    return int(LOCAL_CLOUD_GPU_TEXTURE_MAX_SIZE_FALLBACK)


def _local_cloud_proxy_path(source_path, max_texture_size=None):
    source = os.path.abspath(str(source_path or ""))
    cache_dir = _local_cloud_gpu_textures_dir()
    if not source or not cache_dir:
        return ""
    stem, _ext = os.path.splitext(os.path.basename(source))
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:12]
    limit = int(max_texture_size or _effective_local_cloud_gpu_texture_max_size())
    return os.path.join(cache_dir, f"{stem}_{digest}_gpu{limit}.exr")


def _local_cloud_adaptive_proxy_path(source_path, d_level, max_texture_size=None):
    source = os.path.abspath(str(source_path or ""))
    cache_dir = _local_cloud_adaptive_textures_dir()
    if not source or not cache_dir:
        return ""
    stem, _ext = os.path.splitext(os.path.basename(source))
    try:
        stat = os.stat(source)
        signature = f"{source}|{int(stat.st_mtime_ns)}|{int(stat.st_size)}"
    except OSError:
        signature = source
    digest = hashlib.sha1(signature.encode("utf-8", errors="ignore")).hexdigest()[:12]
    limit = int(max_texture_size or _effective_local_cloud_gpu_texture_max_size())
    return os.path.join(cache_dir, f"{stem}_{digest}_d{int(d_level):03d}_max{limit}.exr")


def _local_cloud_thumbnail_proxy(filename):
    safe_name = os.path.basename(str(filename or ""))
    if not safe_name:
        return ""
    thumb_name = _local_cloud_thumbnail_file_name(safe_name)
    if not thumb_name:
        return ""
    candidate = os.path.join(_local_cloud_thumbnails_dir(), thumb_name)
    if os.path.isfile(candidate):
        return candidate
    try:
        return _download_public_cloud_asset(REMOTE_LOCAL_CLOUD_THUMBNAILS_FOLDER, thumb_name)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed resolving local cloud thumbnail fallback", exc_info=True)
    return ""


def _gpu_safe_local_cloud_texture_path(source_path, filename="", max_texture_size=None):
    source = os.path.abspath(str(source_path or ""))
    if not source or not os.path.isfile(source):
        return ""

    max_size = int(max_texture_size or _effective_local_cloud_gpu_texture_max_size())
    dimensions = _identify_image_dimensions(source)
    if dimensions is not None:
        width, height = dimensions
        if max(width, height) <= max_size:
            return source

    magick = _magick_binary()
    target = _local_cloud_proxy_path(source, max_texture_size=max_size)
    temp_target = f"{target}.part.{os.getpid()}.exr" if target else ""
    if target:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if (
                os.path.isfile(target)
                and os.path.getmtime(target) >= os.path.getmtime(source)
                and os.path.getsize(target) > 0
            ):
                return target
            if _write_resized_local_cloud_exr_proxy(source, temp_target, max_size):
                os.replace(temp_target, target)
                if os.path.isfile(target) and os.path.getsize(target) > 0:
                    return target
        except OSError:
            logger.debug("Planetka clouds: failed creating OpenImageIO GPU-safe local cloud texture proxy", exc_info=True)
            try:
                if temp_target and os.path.exists(temp_target):
                    os.remove(temp_target)
            except OSError:
                pass
    if magick and target:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if (
                os.path.isfile(target)
                and os.path.getmtime(target) >= os.path.getmtime(source)
                and os.path.getsize(target) > 0
            ):
                return target
            resize_limit = f"{max_size}x{max_size}>"
            subprocess.check_call(
                [
                    magick,
                    source,
                    "-auto-orient",
                    "-resize",
                    resize_limit,
                    "-depth",
                    "8",
                    temp_target,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )
            os.replace(temp_target, target)
            if os.path.isfile(target) and os.path.getsize(target) > 0:
                return target
        except (OSError, subprocess.SubprocessError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka clouds: failed creating GPU-safe local cloud texture proxy", exc_info=True)
            try:
                if temp_target and os.path.exists(temp_target):
                    os.remove(temp_target)
            except OSError:
                pass

    if dimensions is not None:
        width, height = dimensions
        if max(width, height) > max_size:
            return ""
    return source


def _render_resolution_pixels(scene):
    render = getattr(scene, "render", None) if scene else None
    try:
        percentage = float(getattr(render, "resolution_percentage", 100.0) or 100.0) / 100.0
        width = int(float(getattr(render, "resolution_x", 1920) or 1920) * percentage)
        height = int(float(getattr(render, "resolution_y", 1080) or 1080) * percentage)
    except (TypeError, ValueError, AttributeError):
        width, height = 1920, 1080
    return max(1, width), max(1, height)


def _camera_world_location(scene):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None:
        return None
    try:
        return camera.matrix_world.translation.copy()
    except (AttributeError, TypeError, RuntimeError):
        return None


def _estimate_local_cloud_projected_pixels(obj, scene, source_dimensions):
    if obj is None or scene is None or not source_dimensions:
        return 0.0
    camera = getattr(scene, "camera", None)
    camera_location = _camera_world_location(scene)
    if camera is None or camera_location is None:
        return 0.0

    try:
        lon = math.radians(float(getattr(obj, LOCAL_CLOUD_PROP_LONGITUDE, 0.0)))
        lat = math.radians(float(getattr(obj, LOCAL_CLOUD_PROP_LATITUDE, 0.0)))
        altitude_m = float(getattr(obj, LOCAL_CLOUD_PROP_ALTITUDE_M, DEFAULT_CLOUD_ALTITUDE_M))
        earth_radius = max(1e-6, float(_earth_radius_blender_units(get_earth_object())))
        radius = earth_radius * max(0.001, (1.0 + (altitude_m / 6371000.0)))
        normal = Vector((math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)))
        if normal.length <= 1e-9:
            normal = Vector((0.0, 0.0, 1.0))
        else:
            normal.normalize()
        center = normal * radius
        half_angle = math.radians(abs(float(_local_cloud_half_angle_deg(getattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0)))))
        world_diameter = 2.0 * radius * abs(math.sin(half_angle))
        distance = max(1e-6, float((camera_location - center).length))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return 0.0
    if world_diameter <= 0.0:
        return 0.0

    width, height = _render_resolution_pixels(scene)
    data = getattr(camera, "data", None)
    camera_type = str(getattr(data, "type", "PERSP") or "PERSP").upper()
    try:
        if camera_type == "ORTHO":
            ortho_scale = max(1e-6, float(getattr(data, "ortho_scale", 1.0) or 1.0))
            pixels_per_unit = max(width, height) / ortho_scale
            return max(0.0, world_diameter * pixels_per_unit)
        angle = max(1e-6, float(getattr(data, "angle", math.radians(50.0)) or math.radians(50.0)))
        focal_pixels = max(width, height) / (2.0 * math.tan(angle * 0.5))
        return max(0.0, (world_diameter / distance) * focal_pixels)
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return 0.0


def _coarser_local_cloud_d_level(d_level, multiplier=1):
    levels = tuple(int(level) for level in LOCAL_CLOUD_ADAPTIVE_D_LEVELS if int(level) > 0)
    if not levels:
        return max(1, int(d_level or 1))
    try:
        target = max(1, int(d_level or 1) * max(1, int(multiplier or 1)))
    except (TypeError, ValueError):
        target = 1
    candidates = [level for level in levels if level >= target]
    return int(min(candidates) if candidates else max(levels))


def _coarser_vdb_cloud_d_level(d_level, multiplier=1):
    levels = tuple(int(level) for level in VDB_CLOUD_ADAPTIVE_D_LEVELS if int(level) > 0)
    if not levels:
        return max(1, int(d_level or 1))
    try:
        target = max(1, int(d_level or 1) * max(1, int(multiplier or 1)))
    except (TypeError, ValueError):
        target = 1
    candidates = [level for level in levels if level >= target]
    return int(min(candidates) if candidates else max(levels))


def _select_local_cloud_adaptive_resolution(
    source_dimensions,
    projected_pixels,
    max_texture_size=None,
    d_level_multiplier=1,
    allow_d001_gpu_proxy=True,
):
    if not source_dimensions:
        return {
            "d_level": 1,
            "ideal_d_level": 1,
            "gpu_limit": int(max_texture_size or _effective_local_cloud_gpu_texture_max_size()),
            "warning": "",
        }
    source_edge = max(1, int(max(source_dimensions)))
    gpu_limit = max(1, int(max_texture_size or _effective_local_cloud_gpu_texture_max_size()))
    levels = tuple(int(level) for level in LOCAL_CLOUD_ADAPTIVE_D_LEVELS if int(level) > 0)
    if not levels:
        levels = (1,)
    gpu_safe_levels = [level for level in levels if math.ceil(source_edge / float(level)) <= gpu_limit]
    if not gpu_safe_levels:
        gpu_safe_levels = [max(levels)]
    # Local user files can use a d001 GPU-safe proxy. Published Planetka Cloud
    # d-levels are immutable assets, so remote d001 is only safe when the GPU
    # can actually load that edge size.
    if allow_d001_gpu_proxy and 1 in levels and 1 not in gpu_safe_levels:
        gpu_safe_levels = [1, *gpu_safe_levels]
    min_gpu_safe_level = min(gpu_safe_levels)

    try:
        required_edge = float(projected_pixels) * float(LOCAL_CLOUD_ADAPTIVE_OVERSAMPLE)
    except (TypeError, ValueError):
        required_edge = 0.0

    if required_edge <= 1.0:
        ideal_d_level = max(levels)
    else:
        candidates = [level for level in levels if (source_edge / float(level)) >= required_edge]
        ideal_d_level = max(candidates) if candidates else min(levels)

    d_level = max(int(ideal_d_level), int(min_gpu_safe_level))
    if d_level not in gpu_safe_levels:
        coarser = [level for level in gpu_safe_levels if level >= d_level]
        d_level = min(coarser) if coarser else max(gpu_safe_levels)

    requested_d_level = int(d_level)
    d_level = _coarser_local_cloud_d_level(d_level, multiplier=d_level_multiplier)

    warning = ""
    if int(d_level) > int(ideal_d_level) or (int(d_level) == 1 and source_edge > gpu_limit):
        warning = (
            f"Cloud texture scaled down to {gpu_limit:,} px to fit this GPU texture-size limit."
        )
    return {
        "d_level": int(d_level),
        "ideal_d_level": int(ideal_d_level),
        "requested_d_level": int(requested_d_level),
        "gpu_limit": int(gpu_limit),
        "warning": warning,
    }


def _select_local_cloud_adaptive_d_level(source_dimensions, projected_pixels):
    return int(_select_local_cloud_adaptive_resolution(source_dimensions, projected_pixels).get("d_level", 1))


def _build_local_cloud_adaptive_texture(source_path, d_level, source_dimensions, max_texture_size=None):
    source = os.path.abspath(str(source_path or ""))
    if not source or not os.path.isfile(source):
        return ""
    d_level = max(1, int(d_level))
    max_size = int(max_texture_size or _effective_local_cloud_gpu_texture_max_size())
    if d_level <= 1 and source_dimensions and max(source_dimensions) <= max_size:
        return source

    target = _local_cloud_adaptive_proxy_path(source, d_level, max_texture_size=max_size)
    if not target:
        return _gpu_safe_local_cloud_texture_path(source, max_texture_size=max_size)
    try:
        if (
            os.path.isfile(target)
            and os.path.getsize(target) > 0
            and os.path.getmtime(target) >= os.path.getmtime(source)
        ):
            return target
    except OSError:
        pass

    magick = _magick_binary()
    temp_target = f"{target}.part.{os.getpid()}.exr"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if source_dimensions:
            source_edge = max(1, int(max(source_dimensions)))
        else:
            source_edge = max_size * d_level
        edge = max(1, min(max_size, int(math.ceil(source_edge / float(d_level)))))
        if _write_resized_local_cloud_exr_proxy(source, temp_target, edge):
            os.replace(temp_target, target)
            if os.path.isfile(target) and os.path.getsize(target) > 0:
                return target
    except OSError:
        logger.debug("Planetka clouds: failed creating adaptive texture-based cloud EXR proxy", exc_info=True)
        try:
            if temp_target and os.path.exists(temp_target):
                os.remove(temp_target)
        except OSError:
            pass
    if not magick:
        return _gpu_safe_local_cloud_texture_path(source, max_texture_size=max_size)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if source_dimensions:
            source_edge = max(1, int(max(source_dimensions)))
        else:
            source_edge = max_size * d_level
        edge = max(1, min(max_size, int(math.ceil(source_edge / float(d_level)))))
        subprocess.check_call(
            [
                magick,
                source,
                "-auto-orient",
                "-resize",
                f"{edge}x{edge}>",
                "-depth",
                "8",
                temp_target,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=240,
        )
        os.replace(temp_target, target)
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
    except (OSError, subprocess.SubprocessError, RuntimeError, TypeError, ValueError):
        logger.debug("Planetka clouds: failed creating adaptive texture-based cloud proxy", exc_info=True)
        try:
            if temp_target and os.path.exists(temp_target):
                os.remove(temp_target)
        except OSError:
            pass
    return _gpu_safe_local_cloud_texture_path(source, max_texture_size=max_size)


def _local_cloud_adaptive_texture_variant(source_path, obj, scene=None, filename="", d_level_multiplier=1):
    source = os.path.abspath(str(source_path or ""))
    if not source or not os.path.isfile(source):
        return {}
    max_size = _effective_local_cloud_gpu_texture_max_size()
    dimensions = _identify_image_dimensions(source)
    if dimensions is None:
        texture_path = _gpu_safe_local_cloud_texture_path(source, filename=filename, max_texture_size=max_size)
        return {
            "path": os.path.abspath(texture_path) if texture_path else "",
            "d_level": 1,
            "projected_pixels": 0.0,
            "gpu_limit": int(max_size),
            "warning": "",
        }
    projected_pixels = _estimate_local_cloud_projected_pixels(obj, scene, dimensions)
    selection = _select_local_cloud_adaptive_resolution(
        dimensions,
        projected_pixels,
        max_texture_size=max_size,
        d_level_multiplier=d_level_multiplier,
    )
    d_level = int(selection.get("d_level", 1) or 1)
    texture_path = _build_local_cloud_adaptive_texture(source, d_level, dimensions, max_texture_size=max_size)
    return {
        "path": os.path.abspath(texture_path) if texture_path else "",
        "d_level": int(d_level),
        "projected_pixels": float(projected_pixels),
        "gpu_limit": int(max_size),
        "warning": str(selection.get("warning", "") or ""),
    }


def _remote_local_cloud_adaptive_texture_variant(file_name, obj, scene=None, d_level_multiplier=1, allow_download=True):
    safe_name = os.path.basename(str(file_name or ""))
    if safe_name not in REMOTE_LOCAL_CLOUD_FILES:
        return {}
    dimensions = _remote_local_cloud_source_dimensions(safe_name)
    if dimensions is None:
        return {}
    max_size = _effective_local_cloud_gpu_texture_max_size()
    projected_pixels = _estimate_local_cloud_projected_pixels(obj, scene, dimensions)
    selection = _select_local_cloud_adaptive_resolution(
        dimensions,
        projected_pixels,
        max_texture_size=max_size,
        d_level_multiplier=d_level_multiplier,
        allow_d001_gpu_proxy=False,
    )
    d_level = int(selection.get("d_level", 1) or 1)
    remote_file = _remote_local_cloud_adaptive_file_name(safe_name, d_level)
    texture_path = ""
    if allow_download and remote_file:
        texture_path = _download_public_cloud_asset(
            LOCAL_CLOUD_ADAPTIVE_TEXTURES_FOLDER,
            remote_file,
            progress_label="Downloading Texture-Based Cloud",
        )
    elif remote_file:
        candidate = os.path.join(_local_cloud_adaptive_textures_dir(), remote_file)
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            texture_path = candidate
    return {
        "path": os.path.abspath(texture_path) if texture_path else "",
        "d_level": int(d_level),
        "projected_pixels": float(projected_pixels),
        "gpu_limit": int(max_size),
        "warning": str(selection.get("warning", "") or ""),
    }


def _adaptive_local_cloud_texture_path(source_path, obj, scene=None, filename="", d_level_multiplier=1):
    variant = _local_cloud_adaptive_texture_variant(
        source_path,
        obj,
        scene=scene,
        filename=filename,
        d_level_multiplier=d_level_multiplier,
    )
    texture_path = str(variant.get("path", "") or "")
    if not texture_path:
        return ""
    try:
        obj[LOCAL_CLOUD_D_LEVEL_PROP] = int(variant.get("d_level", 1) or 1)
        obj[LOCAL_CLOUD_PROJECTED_PIXELS_PROP] = float(variant.get("projected_pixels", 0.0) or 0.0)
        obj[LOCAL_CLOUD_LOADED_TEXTURE_PROP] = os.path.abspath(texture_path)
        obj[LOCAL_CLOUD_GPU_LIMIT_PROP] = int(variant.get("gpu_limit", _effective_local_cloud_gpu_texture_max_size()) or _effective_local_cloud_gpu_texture_max_size())
        obj[LOCAL_CLOUD_DOWNSCALE_WARNING_PROP] = str(variant.get("warning", "") or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    return texture_path


def _resolve_local_cloud_source_path(obj, allow_download=True):
    if not _is_local_cloud_object(obj):
        return ""
    source_path = str(obj.get(LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP, "") or "")
    if source_path:
        source_path = bpy.path.abspath(source_path)
    if not source_path or not os.path.isfile(source_path):
        texture_name = str(getattr(obj, LOCAL_CLOUD_OBJ_TEXTURE_PROP, "") or "")
        if texture_name in REMOTE_LOCAL_CLOUD_FILES:
            return ""
        loaded_path = str(obj.get(LOCAL_CLOUD_LOADED_TEXTURE_PROP, "") or "")
        if loaded_path:
            loaded_path = bpy.path.abspath(loaded_path)
        if loaded_path and os.path.isfile(loaded_path):
            # Existing scenes may only retain the GPU-safe proxy because the
            # original EXR lived in a temporary cache. It is still a valid
            # source for creating a lower-resolution display proxy.
            source_path = loaded_path
        elif allow_download and texture_name and texture_name in REMOTE_LOCAL_CLOUD_FILES:
            source_path = _resolve_remote_local_cloud_asset(
                texture_name,
                progress_label="Downloading Texture-Based Cloud",
            )
            if source_path and os.path.isfile(source_path):
                try:
                    obj[LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP] = os.path.abspath(source_path)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    pass
        if not source_path or not os.path.isfile(source_path):
            return ""
    return source_path


def _local_cloud_quality_props(quality_mode):
    mode = _normalize_cloud_quality_mode(quality_mode)
    if mode == "FULL":
        return LOCAL_CLOUD_FINAL_TEXTURE_PROP, LOCAL_CLOUD_FINAL_D_LEVEL_PROP
    if mode == "BALANCED":
        return LOCAL_CLOUD_BALANCED_TEXTURE_PROP, LOCAL_CLOUD_BALANCED_D_LEVEL_PROP
    return LOCAL_CLOUD_PREVIEW_TEXTURE_PROP, LOCAL_CLOUD_PREVIEW_D_LEVEL_PROP


def _store_local_cloud_prepared_variant(obj, variant, quality_mode="FULL"):
    texture_path = str((variant or {}).get("path", "") or "")
    if not texture_path:
        return False
    path_prop, d_prop = _local_cloud_quality_props(quality_mode)
    try:
        obj[path_prop] = os.path.abspath(texture_path)
        obj[d_prop] = int((variant or {}).get("d_level", 1) or 1)
        obj[LOCAL_CLOUD_PROJECTED_PIXELS_PROP] = float((variant or {}).get("projected_pixels", 0.0) or 0.0)
        obj[LOCAL_CLOUD_GPU_LIMIT_PROP] = int((variant or {}).get("gpu_limit", _effective_local_cloud_gpu_texture_max_size()) or _effective_local_cloud_gpu_texture_max_size())
        obj[LOCAL_CLOUD_DOWNSCALE_WARNING_PROP] = str((variant or {}).get("warning", "") or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed storing prepared texture-based cloud variant", exc_info=True)
    return True


def _prepare_local_cloud_texture_variants(obj, scene=None, allow_download=True):
    if not _is_local_cloud_object(obj):
        return False
    texture_name = str(getattr(obj, LOCAL_CLOUD_OBJ_TEXTURE_PROP, "") or "")
    if texture_name in REMOTE_LOCAL_CLOUD_FILES:
        final_variant = _remote_local_cloud_adaptive_texture_variant(
            texture_name,
            obj,
            scene=scene,
            d_level_multiplier=1,
            allow_download=allow_download,
        )
        balanced_variant = _remote_local_cloud_adaptive_texture_variant(
            texture_name,
            obj,
            scene=scene,
            d_level_multiplier=2,
            allow_download=allow_download,
        )
        preview_variant = _remote_local_cloud_adaptive_texture_variant(
            texture_name,
            obj,
            scene=scene,
            d_level_multiplier=4,
            allow_download=allow_download,
        )
        final_ok = _store_local_cloud_prepared_variant(obj, final_variant, quality_mode="FULL")
        balanced_ok = _store_local_cloud_prepared_variant(obj, balanced_variant, quality_mode="BALANCED")
        preview_ok = _store_local_cloud_prepared_variant(obj, preview_variant, quality_mode="PREVIEW")
        return bool(final_ok and balanced_ok and preview_ok)

    source_path = _resolve_local_cloud_source_path(obj, allow_download=allow_download)
    if not source_path:
        return False
    final_variant = _local_cloud_adaptive_texture_variant(
        source_path,
        obj,
        scene=scene,
        filename=texture_name,
        d_level_multiplier=1,
    )
    balanced_variant = _local_cloud_adaptive_texture_variant(
        source_path,
        obj,
        scene=scene,
        filename=texture_name,
        d_level_multiplier=2,
    )
    preview_variant = _local_cloud_adaptive_texture_variant(
        source_path,
        obj,
        scene=scene,
        filename=texture_name,
        d_level_multiplier=4,
    )
    final_ok = _store_local_cloud_prepared_variant(obj, final_variant, quality_mode="FULL")
    balanced_ok = _store_local_cloud_prepared_variant(obj, balanced_variant, quality_mode="BALANCED")
    preview_ok = _store_local_cloud_prepared_variant(obj, preview_variant, quality_mode="PREVIEW")
    return bool(final_ok and balanced_ok and preview_ok)


def _apply_prepared_local_cloud_texture(obj, preview=False, scene=None, allow_prepare_missing=True, quality_mode=None):
    if not _is_local_cloud_object(obj):
        return False
    material = _resolve_object_material(obj)
    image_node = _find_image_texture_node(material)
    if image_node is None:
        return False

    if quality_mode is None:
        quality_mode = "PREVIEW" if preview else "FULL"
    path_prop, d_prop = _local_cloud_quality_props(quality_mode)
    texture_path = str(obj.get(path_prop, "") or "")
    if texture_path:
        texture_path = bpy.path.abspath(texture_path)
    if _local_cloud_prepared_texture_needs_refresh(texture_path):
        texture_path = ""
    if (not texture_path or not os.path.isfile(texture_path)) and allow_prepare_missing:
        if not _prepare_local_cloud_texture_variants(obj, scene=scene, allow_download=True):
            return False
        texture_path = str(obj.get(path_prop, "") or "")
        if texture_path:
            texture_path = bpy.path.abspath(texture_path)
    if not texture_path or not os.path.isfile(texture_path):
        return False

    material = _resolve_object_material(obj)
    image_node = _find_image_texture_node(material)
    if image_node is None:
        return False
    current_image = getattr(image_node, "image", None)
    current_path = bpy.path.abspath(str(getattr(current_image, "filepath", "") or "")) if current_image else ""
    if os.path.abspath(current_path) != os.path.abspath(texture_path):
        try:
            image = bpy.data.images.load(texture_path, check_existing=True)
            _set_cloud_mask_image_colorspace(image)
            image_node.image = image
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed loading prepared texture-based cloud texture", exc_info=True)
            return False
    else:
        _set_cloud_mask_image_colorspace(current_image)
    try:
        obj[LOCAL_CLOUD_LOADED_TEXTURE_PROP] = os.path.abspath(texture_path)
        obj[LOCAL_CLOUD_D_LEVEL_PROP] = int(obj.get(d_prop, 1) or 1)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    return True


def _update_local_cloud_adaptive_texture(obj, scene=None, preview=False, quality_mode=None):
    if not _is_local_cloud_object(obj):
        return False
    if not _prepare_local_cloud_texture_variants(obj, scene=scene, allow_download=True):
        logger.error("Planetka clouds: texture-based cloud texture variants could not be prepared")
        return False
    return _apply_prepared_local_cloud_texture(
        obj,
        preview=preview,
        scene=scene,
        allow_prepare_missing=False,
        quality_mode=quality_mode,
    )


def _refresh_remote_local_cloud_thumbnails(force=False):
    global _local_cloud_thumbnail_paths

    if (
        _local_cloud_thumbnail_paths
        and not force
        and all(
            os.path.isfile(_local_cloud_thumbnail_paths.get(file_name, ""))
            and os.path.getsize(_local_cloud_thumbnail_paths.get(file_name, "")) > 0
            for file_name in REMOTE_LOCAL_CLOUD_FILES
        )
    ):
        return dict(_local_cloud_thumbnail_paths)

    resolved = dict(_local_cloud_thumbnail_paths) if not force else {}
    cache_dir = _local_cloud_thumbnails_dir()
    for file_name in REMOTE_LOCAL_CLOUD_FILES:
        thumb_name = _local_cloud_thumbnail_file_name(file_name)
        path = ""
        if cache_dir and thumb_name:
            candidate = os.path.join(cache_dir, thumb_name)
            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                path = candidate
        if not path and thumb_name:
            try:
                path = _download_public_cloud_asset(REMOTE_LOCAL_CLOUD_THUMBNAILS_FOLDER, thumb_name)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed resolving local cloud thumbnail asset", exc_info=True)
                path = ""
        if path and os.path.isfile(path):
            resolved[file_name] = path
    _local_cloud_thumbnail_paths = resolved
    return dict(_local_cloud_thumbnail_paths)


def _refresh_remote_vdb_cloud_assets(force=False):
    global _vdb_cloud_asset_paths

    if _vdb_cloud_asset_paths:
        return dict(_vdb_cloud_asset_paths)

    resolved = {}
    cache_dir = _vdb_clouds_dir()
    for file_name in REMOTE_VDB_CLOUD_FILES:
        path = ""
        if cache_dir:
            candidate = os.path.join(cache_dir, file_name)
            if os.path.isfile(candidate):
                path = candidate
        if path and os.path.isfile(path):
            resolved[file_name] = path
    _vdb_cloud_asset_paths = resolved
    return dict(_vdb_cloud_asset_paths)


def _split_vdb_lod_filename(file_name):
    safe_name = os.path.basename(str(file_name or ""))
    stem, ext = os.path.splitext(safe_name)
    if ext.lower() != ".vdb" or not stem:
        return safe_name, 1
    match = re.match(r"^(?P<base>.+)_d(?P<level>\d{3})$", stem, flags=re.IGNORECASE)
    if not match:
        return safe_name, 1
    try:
        level = max(1, int(match.group("level")))
    except (TypeError, ValueError):
        level = 1
    return f"{match.group('base')}{ext}", level


def _vdb_lod_filename(base_file_name, d_level):
    base_name, _current_level = _split_vdb_lod_filename(base_file_name)
    stem, ext = os.path.splitext(os.path.basename(base_name))
    if not stem or ext.lower() != ".vdb":
        return ""
    try:
        level = max(1, int(d_level))
    except (TypeError, ValueError):
        level = 1
    if level <= 1:
        return f"{stem}{ext}"
    return f"{stem}_d{level:03d}{ext}"


def _is_known_remote_vdb_cloud_file(file_name):
    base_name, _level = _split_vdb_lod_filename(file_name)
    return bool(base_name in REMOTE_VDB_CLOUD_FILES)


def _published_vdb_cloud_lod_levels(file_name):
    base_name, _level = _split_vdb_lod_filename(file_name)
    if base_name not in REMOTE_VDB_CLOUD_FILES:
        return tuple()
    return _VDB_CLOUD_FULL_LOD_LEVELS


def _nearest_published_vdb_lod_levels(file_name, requested_level):
    levels = _published_vdb_cloud_lod_levels(file_name)
    if not levels:
        return tuple()
    try:
        requested = max(1, int(requested_level))
    except (TypeError, ValueError):
        requested = 1
    coarser_or_equal = [level for level in levels if level >= requested]
    finer = [level for level in levels if level < requested]
    return tuple(sorted(coarser_or_equal) + sorted(finer, reverse=True))


def _candidate_local_vdb_lod_path(source_path, d_level):
    source = bpy.path.abspath(str(source_path or ""))
    if not source:
        return ""
    source_dir = os.path.dirname(source)
    candidate_name = _vdb_lod_filename(os.path.basename(source), d_level)
    if not source_dir or not candidate_name:
        return ""
    candidate = os.path.join(source_dir, candidate_name)
    return os.path.abspath(candidate) if os.path.isfile(candidate) else ""


def _resolve_remote_vdb_cloud_asset(file_name, progress_label=""):
    global _vdb_cloud_asset_paths

    safe_name = os.path.basename(str(file_name or ""))
    if not _is_known_remote_vdb_cloud_file(safe_name):
        return ""

    requested_base, requested_level = _split_vdb_lod_filename(safe_name)
    candidate_names = []
    for level in _nearest_published_vdb_lod_levels(requested_base, requested_level):
        candidate = _vdb_lod_filename(requested_base, level)
        if candidate and candidate not in candidate_names:
            candidate_names.append(candidate)
    if int(requested_level) <= 1 and safe_name not in candidate_names:
        candidate_names.insert(0, safe_name)
    if not candidate_names:
        return ""

    assets = _refresh_remote_vdb_cloud_assets(force=False)
    for candidate_name in candidate_names:
        cached = assets.get(candidate_name, "")
        if cached and os.path.isfile(cached):
            if progress_label:
                _set_cloud_download_progress(active=False, error="", file_name=candidate_name)
            return cached

    for candidate_name in candidate_names:
        try:
            resolved = _download_public_cloud_asset(REMOTE_VDB_CLOUDS_FOLDER, candidate_name, progress_label=progress_label)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed resolving selected VDB cloud asset", exc_info=True)
            resolved = ""
        if resolved and os.path.isfile(resolved):
            _vdb_cloud_asset_paths[candidate_name] = resolved
            return resolved
    return ""


def _vdb_cloud_thumbnail_file_name(file_name):
    safe_name = os.path.basename(str(file_name or ""))
    stem, _ext = os.path.splitext(safe_name)
    return f"{stem}.png" if stem else ""


def _refresh_remote_vdb_cloud_thumbnails(force=False):
    global _vdb_cloud_thumbnail_paths

    if (
        _vdb_cloud_thumbnail_paths
        and not force
        and all(
            os.path.isfile(_vdb_cloud_thumbnail_paths.get(file_name, ""))
            and os.path.getsize(_vdb_cloud_thumbnail_paths.get(file_name, "")) > 0
            for file_name in REMOTE_VDB_CLOUD_FILES
        )
    ):
        return dict(_vdb_cloud_thumbnail_paths)

    resolved = dict(_vdb_cloud_thumbnail_paths) if not force else {}
    cache_dir = _vdb_cloud_thumbnails_dir()
    for file_name in REMOTE_VDB_CLOUD_FILES:
        thumb_name = _vdb_cloud_thumbnail_file_name(file_name)
        path = ""
        if cache_dir and thumb_name:
            candidate = os.path.join(cache_dir, thumb_name)
            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                path = candidate
        if not path and thumb_name:
            try:
                path = _download_public_cloud_asset(REMOTE_VDB_CLOUD_THUMBNAILS_FOLDER, thumb_name)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed resolving VDB cloud thumbnail asset", exc_info=True)
                path = ""
        if path and os.path.isfile(path):
            resolved[file_name] = path
    _vdb_cloud_thumbnail_paths = resolved
    return dict(_vdb_cloud_thumbnail_paths)


def _vdb_cloud_preset_items(_self=None, _context=None):
    items = _ensure_vdb_cloud_previews()
    if items:
        return items
    return [("NONE", "No VDB Cloud Presets Found", _vdb_clouds_dir(), 0, 0)]


def _build_local_cloud_signature(thumbnail_paths):
    entries = []
    for name in REMOTE_LOCAL_CLOUD_FILES:
        path = thumbnail_paths.get(name, "")
        try:
            mtime_ns = os.stat(path).st_mtime_ns if path else 0
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            mtime_ns = 0
        entries.append((name, mtime_ns))
    return (
        os.path.normcase(os.path.normpath(_local_cloud_thumbnails_dir() or "")),
        tuple(entries),
    )


def _build_vdb_cloud_signature(thumbnail_paths):
    entries = []
    for name in REMOTE_VDB_CLOUD_FILES:
        path = thumbnail_paths.get(name, "")
        try:
            mtime_ns = os.stat(path).st_mtime_ns if path else 0
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            mtime_ns = 0
        entries.append((name, mtime_ns))
    return (
        os.path.normcase(os.path.normpath(_vdb_cloud_thumbnails_dir() or "")),
        tuple(entries),
    )


def _preview_items_have_icons(items, expected_count):
    if not items or len(items) < int(expected_count):
        return False
    for item in items:
        try:
            if int(item[3]) <= 0:
                return False
        except (TypeError, ValueError, IndexError):
            return False
    return True


def _replace_preview_collection(collection):
    if collection is not None:
        try:
            bpy.utils.previews.remove(collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed replacing preview collection", exc_info=True)
    return bpy.utils.previews.new()


def _ensure_local_cloud_previews(force=False):
    global _local_cloud_preview_collection
    global _local_cloud_preview_signature
    global _local_cloud_enum_items

    thumbnail_paths = _refresh_remote_local_cloud_thumbnails(force=force)
    signature = _build_local_cloud_signature(thumbnail_paths)

    if (
        not force
        and _local_cloud_preview_collection is not None
        and signature == _local_cloud_preview_signature
        and _preview_items_have_icons(_local_cloud_enum_items, len(REMOTE_LOCAL_CLOUD_FILES))
    ):
        return _local_cloud_enum_items

    _local_cloud_preview_collection = _replace_preview_collection(_local_cloud_preview_collection)

    items = []
    _local_cloud_preview_signature = signature

    _folder_key, file_entries = signature
    for idx, (filename, _mtime_ns) in enumerate(file_entries):
        path = thumbnail_paths.get(filename, "")
        icon_id = 0
        key = f"local_cloud_{filename}"
        if path:
            try:
                thumb = _local_cloud_preview_collection.load(key, path, 'IMAGE')
                icon_id = thumb.icon_id
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                icon_id = 0
        label = os.path.splitext(filename)[0]
        description = f"Planetka Cloud mask: {filename}"
        items.append((filename, label, description, icon_id, idx))
    _local_cloud_enum_items = items
    return _local_cloud_enum_items


def _ensure_vdb_cloud_previews(force=False):
    global _vdb_cloud_preview_collection
    global _vdb_cloud_preview_signature
    global _vdb_cloud_enum_items

    thumbnail_paths = _refresh_remote_vdb_cloud_thumbnails(force=force)
    signature = _build_vdb_cloud_signature(thumbnail_paths)

    if (
        not force
        and _vdb_cloud_preview_collection is not None
        and signature == _vdb_cloud_preview_signature
        and _preview_items_have_icons(_vdb_cloud_enum_items, len(REMOTE_VDB_CLOUD_FILES))
    ):
        return _vdb_cloud_enum_items

    _vdb_cloud_preview_collection = _replace_preview_collection(_vdb_cloud_preview_collection)

    items = []
    _vdb_cloud_preview_signature = signature

    _folder_key, file_entries = signature
    for idx, (filename, _mtime_ns) in enumerate(file_entries):
        path = thumbnail_paths.get(filename, "")
        icon_id = 0
        key = f"vdb_cloud_{filename}"
        if path:
            try:
                thumb = _vdb_cloud_preview_collection.load(key, path, 'IMAGE')
                icon_id = thumb.icon_id
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                icon_id = 0
        label = os.path.splitext(filename)[0]
        description = f"Planetka Cloud VDB preset: {filename}"
        items.append((filename, label, description, icon_id, idx))
    _vdb_cloud_enum_items = items
    return _vdb_cloud_enum_items


def _local_cloud_texture_items(_self, _context):
    items = _ensure_local_cloud_previews()
    if items:
        return items
    return [("NONE", "No Texture-Based Cloud Textures Found", _local_clouds_dir(), 0, 0)]


def _free_local_cloud_previews():
    global _local_cloud_preview_collection
    global _local_cloud_preview_signature
    global _local_cloud_enum_items

    if _local_cloud_preview_collection is not None:
        try:
            bpy.utils.previews.remove(_local_cloud_preview_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-001", "Failed removing local cloud preview collection")
        _local_cloud_preview_collection = None
    _local_cloud_preview_signature = None
    _local_cloud_enum_items = []


def _free_vdb_cloud_previews():
    global _vdb_cloud_preview_collection
    global _vdb_cloud_preview_signature
    global _vdb_cloud_enum_items

    if _vdb_cloud_preview_collection is not None:
        try:
            bpy.utils.previews.remove(_vdb_cloud_preview_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-024", "Failed removing VDB cloud preview collection")
        _vdb_cloud_preview_collection = None
    _vdb_cloud_preview_signature = None
    _vdb_cloud_enum_items = []


def _find_layer_collection_recursive(layer_collection, target_name):
    if layer_collection is None:
        return None
    if str(getattr(getattr(layer_collection, "collection", None), "name", "")) == str(target_name):
        return layer_collection
    for child in getattr(layer_collection, "children", ()): 
        found = _find_layer_collection_recursive(child, target_name)
        if found is not None:
            return found
    return None


def _set_collection_enabled(scene, collection_name, enabled):
    collection = bpy.data.collections.get(collection_name)
    if collection is not None:
        hidden = not bool(enabled)
        try:
            collection.hide_viewport = hidden
            collection.hide_render = hidden
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating collection hide flags", exc_info=True)

    if scene is None:
        return

    for view_layer in getattr(scene, "view_layers", ()): 
        layer_collection = _find_layer_collection_recursive(getattr(view_layer, "layer_collection", None), collection_name)
        if layer_collection is None:
            continue
        try:
            layer_collection.exclude = not bool(enabled)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating collection exclusion", exc_info=True)


def _ensure_child_collection(parent_collection, name):
    if parent_collection is None:
        return None
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    try:
        if collection.name not in parent_collection.children:
            parent_collection.children.link(collection)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed linking collection", exc_info=True)
    return collection


def _ensure_cloud_collections(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    root = getattr(scene, "collection", None) if scene else None
    if root is None:
        return None, None, None, None

    clouds = _ensure_child_collection(root, CLOUDS_ROOT_COLLECTION_NAME)
    global_clouds = _ensure_child_collection(clouds, GLOBAL_CLOUDS_COLLECTION_NAME)
    local_clouds = _ensure_child_collection(clouds, LOCAL_CLOUDS_COLLECTION_NAME)
    vdb_clouds = _ensure_child_collection(clouds, VDB_CLOUDS_COLLECTION_NAME)
    return clouds, global_clouds, local_clouds, vdb_clouds


def _sync_cloud_collection_visibility(scene, props):
    _ensure_cloud_collections(scene)
    enable_global = bool(getattr(props, "enable_global_clouds", False)) if props else False
    enable_local = bool(getattr(props, "enable_local_clouds", False)) if props else False
    enable_vdb = bool(getattr(props, "enable_vdb_clouds", False)) if props else False

    _set_collection_enabled(scene, CLOUDS_ROOT_COLLECTION_NAME, enable_global or enable_local or enable_vdb)
    _set_collection_enabled(scene, GLOBAL_CLOUDS_COLLECTION_NAME, enable_global)
    _set_collection_enabled(scene, LOCAL_CLOUDS_COLLECTION_NAME, enable_local)
    _set_collection_enabled(scene, VDB_CLOUDS_COLLECTION_NAME, enable_vdb)


def _set_object_collections(obj, collections):
    if obj is None:
        return
    desired = [col for col in collections if col]
    desired_ids = {id(col) for col in desired}

    for col in list(getattr(obj, "users_collection", ())):
        if id(col) in desired_ids:
            continue
        try:
            col.objects.unlink(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed unlinking object from collection", exc_info=True)

    for col in desired:
        try:
            if obj.name not in col.objects:
                col.objects.link(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed linking object to collection", exc_info=True)


def _ensure_cloud_parented_to_root(obj, scene=None):
    if obj is None:
        return None
    scene = scene or getattr(bpy.context, "scene", None)
    root = ensure_planetka_root(scene) if scene is not None else None
    if root is None:
        return None
    try:
        if getattr(obj, "parent", None) is not root:
            obj.parent = root
            obj.matrix_parent_inverse = root.matrix_world.inverted()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed parenting cloud object to Planetka Root", exc_info=True)
    return root


def _is_cloud_cull_modifier(modifier):
    if modifier is None:
        return False

    name = str(getattr(modifier, "name", "") or "").lower()
    if any(token in name for token in ("cull", "frustum", "camera cull")):
        return True

    mod_type = str(getattr(modifier, "type", "") or "")
    if mod_type == "NODES":
        node_group = getattr(modifier, "node_group", None)
        group_name = str(getattr(node_group, "name", "") or "").lower()
        if any(token in group_name for token in ("cull", "frustum", "camera cull")):
            return True
    return False


def _remove_cloud_cull_modifiers(obj):
    if obj is None:
        return 0
    removed = 0
    modifiers = getattr(obj, "modifiers", None)
    if modifiers is None:
        return 0
    for modifier in list(modifiers):
        if not _is_cloud_cull_modifier(modifier):
            continue
        try:
            modifiers.remove(modifier)
            removed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed removing cloud cull modifier on '%s'", obj.name, exc_info=True)
    return removed


def _clear_drivers_on_id_data(id_data):
    if id_data is None:
        return
    anim = getattr(id_data, "animation_data", None)
    drivers = getattr(anim, "drivers", None) if anim else None
    if not drivers:
        return
    for fcurve in list(drivers):
        try:
            drivers.remove(fcurve)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed removing driver", exc_info=True)


def _clear_drivers_on_node_tree(node_tree, visited=None):
    if node_tree is None:
        return
    if visited is None:
        visited = set()
    try:
        ptr = int(node_tree.as_pointer())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        ptr = id(node_tree)
    if ptr in visited:
        return
    visited.add(ptr)

    _clear_drivers_on_id_data(node_tree)
    for node in getattr(node_tree, "nodes", ()): 
        child = getattr(node, "node_tree", None)
        if child is not None:
            _clear_drivers_on_node_tree(child, visited=visited)


def _clear_cloud_drivers(obj):
    if obj is None:
        return
    try:
        obj.animation_data_clear()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed clearing object animation data", exc_info=True)

    data_block = getattr(obj, "data", None)
    _clear_drivers_on_id_data(data_block)

    materials = []
    if data_block is not None and hasattr(data_block, "materials"):
        materials.extend(mat for mat in data_block.materials if mat)
    active = getattr(obj, "active_material", None)
    if active is not None:
        materials.append(active)

    seen = set()
    for mat in materials:
        if mat is None:
            continue
        try:
            key = int(mat.as_pointer())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            key = id(mat)
        if key in seen:
            continue
        seen.add(key)
        _clear_drivers_on_id_data(mat)
        _clear_drivers_on_node_tree(getattr(mat, "node_tree", None))


def _append_from_reference(object_names=(), material_names=(), blend_path=None):
    blend_path = os.path.abspath(blend_path or COMMERCIAL_REFERENCE_BLEND_PATH)
    if not os.path.isfile(blend_path):
        raise RuntimeError(f"Planetka clouds reference blend missing: {blend_path}")

    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        available_objects = set(data_from.objects)
        available_materials = set(data_from.materials)

        object_targets = [name for name in object_names if name in available_objects]
        material_targets = [name for name in material_names if name in available_materials]

        if object_names and not object_targets:
            raise RuntimeError(
                "Planetka clouds reference object missing: " + ", ".join(object_names)
            )
        if material_names and not material_targets:
            raise RuntimeError(
                "Planetka clouds reference material missing: " + ", ".join(material_names)
            )

        data_to.objects = object_targets
        data_to.materials = material_targets


def _unlink_object_from_all_collections(obj):
    if obj is None:
        return
    for collection in tuple(getattr(obj, "users_collection", ()) or ()):
        try:
            collection.objects.unlink(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed unlinking reference object from collection", exc_info=True)


def _is_local_cloud_object(obj):
    if obj is None or str(getattr(obj, "type", "")) != "MESH":
        return False
    if not tuple(getattr(obj, "users_collection", ()) or ()):
        return False
    try:
        if str(obj.get(CLOUD_ROLE_KEY, "")) == LOCAL_CLOUD_ROLE:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDL-002", "Failed reading local-cloud role custom property")
    if str(getattr(obj, "name", "")).startswith(LOCAL_CLOUD_NUMBERED_PREFIX):
        return True
    coll = bpy.data.collections.get(LOCAL_CLOUDS_COLLECTION_NAME)
    if coll is None:
        return False
    return any(member == obj for member in coll.all_objects)


def _is_vdb_cloud_object(obj):
    if obj is None:
        return False
    if not tuple(getattr(obj, "users_collection", ()) or ()):
        return False
    try:
        if str(obj.get(CLOUD_ROLE_KEY, "")) == VDB_CLOUD_TEMPLATE_ROLE:
            return False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDL-025", "Failed reading VDB-template role custom property")
    if str(getattr(obj, "name", "")) == VDB_CLOUD_TEMPLATE_OBJECT_NAME:
        return False
    try:
        if str(obj.get(CLOUD_ROLE_KEY, "")) == VDB_CLOUD_ROLE:
            return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDL-003", "Failed reading VDB-cloud role custom property")
    if str(getattr(obj, "name", "")).startswith(VDB_CLOUD_NUMBERED_PREFIX):
        return True
    coll = bpy.data.collections.get(VDB_CLOUDS_COLLECTION_NAME)
    if coll is None:
        return False
    return any(member == obj for member in coll.all_objects)


def _iter_local_cloud_objects():
    seen = set()
    coll = bpy.data.collections.get(LOCAL_CLOUDS_COLLECTION_NAME)
    if coll:
        for obj in coll.all_objects:
            if not _is_local_cloud_object(obj):
                continue
            ptr = int(obj.as_pointer())
            if ptr in seen:
                continue
            seen.add(ptr)
            yield obj
    for obj in getattr(bpy.data, "objects", ()): 
        if not _is_local_cloud_object(obj):
            continue
        ptr = int(obj.as_pointer())
        if ptr in seen:
            continue
        seen.add(ptr)
        yield obj


def _iter_vdb_cloud_objects():
    seen = set()
    coll = bpy.data.collections.get(VDB_CLOUDS_COLLECTION_NAME)
    if coll:
        for obj in coll.all_objects:
            if not _is_vdb_cloud_object(obj):
                continue
            ptr = int(obj.as_pointer())
            if ptr in seen:
                continue
            seen.add(ptr)
            yield obj
    for obj in getattr(bpy.data, "objects", ()): 
        if not _is_vdb_cloud_object(obj):
            continue
        ptr = int(obj.as_pointer())
        if ptr in seen:
            continue
        seen.add(ptr)
        yield obj


def _sort_cloud_objects_by_suffix(objects):
    number_re = re.compile(r"(\d+)$")

    def _sort_key(obj):
        name = str(getattr(obj, "name", "") or "")
        match = number_re.search(name)
        if match:
            try:
                return (0, int(match.group(1)), name)
            except (TypeError, ValueError):
                pass
        return (1, name)

    return sorted(objects, key=_sort_key)


def _next_local_cloud_name():
    pattern = re.compile(rf"^{re.escape(LOCAL_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$")
    max_num = 0
    for obj in getattr(bpy.data, "objects", ()): 
        match = pattern.match(str(getattr(obj, "name", "")))
        if match:
            try:
                max_num = max(max_num, int(match.group(1)))
            except (TypeError, ValueError):
                continue
    return f"{LOCAL_CLOUD_NUMBERED_PREFIX}{max_num + 1:03d}"


def _next_vdb_cloud_name():
    pattern = re.compile(rf"^{re.escape(VDB_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$")
    max_num = 0
    for obj in getattr(bpy.data, "objects", ()): 
        match = pattern.match(str(getattr(obj, "name", "")))
        if match:
            try:
                max_num = max(max_num, int(match.group(1)))
            except (TypeError, ValueError):
                continue
    return f"{VDB_CLOUD_NUMBERED_PREFIX}{max_num + 1:03d}"


def _local_cloud_material_name_for_object(object_name):
    match = re.match(rf"^{re.escape(LOCAL_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$", str(object_name or ""))
    if match:
        return f"Planetka Texture-Based Cloud Shader No {match.group(1)}"
    return "Planetka Texture-Based Cloud Shader"


def _vdb_cloud_material_name_for_object(object_name):
    match = re.match(rf"^{re.escape(VDB_CLOUD_NUMBERED_PREFIX)}(\d{{3}})$", str(object_name or ""))
    if match:
        return f"Planetka VDB Cloud Shader No {match.group(1)}"
    return "Planetka VDB Cloud Shader"


def _find_image_texture_node(material):
    if material is None or not getattr(material, "node_tree", None):
        return None
    node_tree = material.node_tree
    node = node_tree.nodes.get("Image Texture")
    if node is not None and str(getattr(node, "type", "")) == "TEX_IMAGE":
        return node
    for candidate in node_tree.nodes:
        if str(getattr(candidate, "type", "")) == "TEX_IMAGE":
            return candidate
    return None


def _find_material_output_node(material):
    node_tree = getattr(material, "node_tree", None) if material is not None else None
    if node_tree is None:
        return None
    node = node_tree.nodes.get("Material Output") or node_tree.nodes.get("Material Output.001")
    if node is not None and str(getattr(node, "type", "")) == "OUTPUT_MATERIAL":
        return node
    for candidate in node_tree.nodes:
        if str(getattr(candidate, "type", "")) == "OUTPUT_MATERIAL":
            return candidate
    return None


def _is_named_blender_id(name, base_name):
    text = str(name or "")
    base = str(base_name or "")
    if not text or not base:
        return False
    return bool(re.fullmatch(re.escape(base) + r"\.\d{3}", text))


def _is_suffixed_cloud_material_group_name(name):
    return _is_named_blender_id(name, CLOUD_MATERIAL_GROUP_NAME)


def _canonicalize_cloud_material_group(group):
    if group is None:
        return None
    name = str(getattr(group, "name", "") or "")
    if name == CLOUD_MATERIAL_GROUP_NAME:
        return group
    if not _is_suffixed_cloud_material_group_name(name):
        return group
    canonical = bpy.data.node_groups.get(CLOUD_MATERIAL_GROUP_NAME)
    if canonical is not None and canonical != group:
        return canonical
    try:
        group.name = CLOUD_MATERIAL_GROUP_NAME
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed canonicalizing Planetka Cloud Material group name", exc_info=True)
    return bpy.data.node_groups.get(CLOUD_MATERIAL_GROUP_NAME) or group


def _remove_unused_suffixed_cloud_material_groups():
    for group in tuple(getattr(bpy.data, "node_groups", ())):
        if not _is_suffixed_cloud_material_group_name(str(getattr(group, "name", "") or "")):
            continue
        try:
            if int(getattr(group, "users", 0) or 0) == 0:
                bpy.data.node_groups.remove(group)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed removing unused suffixed Planetka Cloud Material group", exc_info=True)


def _socket_default_values(node):
    values = {}
    for socket in tuple(getattr(node, "inputs", ())):
        name = str(getattr(socket, "name", "") or "")
        if not name or not hasattr(socket, "default_value"):
            continue
        try:
            values[name] = socket.default_value
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed reading cloud material socket default", exc_info=True)
    return values


def _restore_socket_default_values(node, values):
    if node is None or not isinstance(values, dict):
        return
    for name, value in values.items():
        socket = node.inputs.get(name)
        if socket is None or not hasattr(socket, "default_value"):
            continue
        try:
            socket.default_value = value
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed restoring cloud material socket default", exc_info=True)


def _ensure_planetka_cloud_material_group():
    group = bpy.data.node_groups.get(CLOUD_MATERIAL_GROUP_NAME)
    if group is not None:
        return group
    for candidate in tuple(getattr(bpy.data, "node_groups", ())):
        if _is_suffixed_cloud_material_group_name(str(getattr(candidate, "name", "") or "")):
            return _canonicalize_cloud_material_group(candidate)
    try:
        _append_from_reference(
            material_names=(GLOBAL_CLOUD_MATERIAL_NAME,),
            blend_path=GLOBAL_CLOUD_REFERENCE_BLEND_PATH,
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed appending Planetka Cloud Material group", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed appending Planetka Cloud Material group", exc_info=True)
    group = bpy.data.node_groups.get(CLOUD_MATERIAL_GROUP_NAME)
    if group is not None:
        return group
    for candidate in tuple(getattr(bpy.data, "node_groups", ())):
        if _is_suffixed_cloud_material_group_name(str(getattr(candidate, "name", "") or "")):
            return _canonicalize_cloud_material_group(candidate)
    return None


def _remove_socket_links(node_tree, socket):
    if node_tree is None or socket is None:
        return
    try:
        for link in list(getattr(socket, "links", ())):
            node_tree.links.remove(link)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed removing socket links", exc_info=True)


def _link_sockets(node_tree, from_socket, to_socket):
    if node_tree is None or from_socket is None or to_socket is None:
        return False
    try:
        _remove_socket_links(node_tree, to_socket)
        node_tree.links.new(from_socket, to_socket)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed linking material sockets", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed linking material sockets", exc_info=True)
    return False


def _cleanup_unused_legacy_local_cloud_group():
    legacy = bpy.data.node_groups.get(LEGACY_LOCAL_CLOUD_SHADER_GROUP_NAME)
    if legacy is None:
        return
    try:
        if int(getattr(legacy, "users", 0) or 0) == 0:
            bpy.data.node_groups.remove(legacy)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed removing unused legacy local cloud shader group", exc_info=True)


def _ensure_local_cloud_material_uses_cloud_material(material):
    node_tree = getattr(material, "node_tree", None) if material is not None else None
    if node_tree is None:
        return False
    cloud_group = _ensure_planetka_cloud_material_group()
    if cloud_group is None:
        return False

    nodes = node_tree.nodes
    group_node = None
    duplicate_cloud_nodes = []
    legacy_nodes = []
    for node in tuple(nodes):
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        child_name = str(getattr(getattr(node, "node_tree", None), "name", "") or "")
        if child_name == CLOUD_MATERIAL_GROUP_NAME and group_node is None:
            group_node = node
        elif child_name == CLOUD_MATERIAL_GROUP_NAME:
            duplicate_cloud_nodes.append(node)
        elif _is_suffixed_cloud_material_group_name(child_name) and group_node is None:
            group_node = node
            values = _socket_default_values(group_node)
            try:
                group_node.node_tree = cloud_group
                group_node.name = CLOUD_MATERIAL_GROUP_NAME
                group_node.label = CLOUD_MATERIAL_GROUP_NAME
                _restore_socket_default_values(group_node, values)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed canonicalizing suffixed local cloud shader group node", exc_info=True)
                return False
        elif _is_suffixed_cloud_material_group_name(child_name):
            duplicate_cloud_nodes.append(node)
        elif child_name == LEGACY_LOCAL_CLOUD_SHADER_GROUP_NAME:
            legacy_nodes.append(node)

    if group_node is None and legacy_nodes:
        group_node = legacy_nodes.pop(0)
        try:
            group_node.node_tree = cloud_group
            group_node.name = CLOUD_MATERIAL_GROUP_NAME
            group_node.label = CLOUD_MATERIAL_GROUP_NAME
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed replacing legacy local cloud shader group node", exc_info=True)
            return False

    if group_node is None:
        try:
            group_node = nodes.new("ShaderNodeGroup")
            group_node.node_tree = cloud_group
            group_node.name = CLOUD_MATERIAL_GROUP_NAME
            group_node.label = CLOUD_MATERIAL_GROUP_NAME
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating Planetka Cloud Material group node", exc_info=True)
            return False

    for legacy_node in legacy_nodes:
        try:
            nodes.remove(legacy_node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed removing duplicate legacy local cloud shader group node", exc_info=True)
    for duplicate_node in duplicate_cloud_nodes:
        try:
            nodes.remove(duplicate_node)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed removing duplicate Planetka Cloud Material group node", exc_info=True)

    image_node = _find_image_texture_node(material)
    output_node = _find_material_output_node(material)
    if image_node is None or output_node is None:
        return False

    source_input = group_node.inputs.get("Source Texture")
    shader_output = group_node.outputs.get("Shader")
    displacement_output = group_node.outputs.get("Displacement")
    surface_input = output_node.inputs.get("Surface")
    volume_input = output_node.inputs.get("Volume")
    displacement_input = output_node.inputs.get("Displacement")

    _link_sockets(node_tree, image_node.outputs.get("Color"), source_input)
    _link_sockets(node_tree, shader_output, surface_input)
    _remove_socket_links(node_tree, volume_input)
    _link_sockets(node_tree, displacement_output, displacement_input)
    _cleanup_unused_legacy_local_cloud_group()
    _remove_unused_suffixed_cloud_material_groups()
    return True


def _cloud_material_group_node(material):
    node_tree = getattr(material, "node_tree", None) if material is not None else None
    if node_tree is None:
        return None
    for node in tuple(getattr(node_tree, "nodes", ())):
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        if str(getattr(getattr(node, "node_tree", None), "name", "") or "") == CLOUD_MATERIAL_GROUP_NAME:
            return node
    return None


def _ensure_global_cloud_material_template():
    material = bpy.data.materials.get(GLOBAL_CLOUD_MATERIAL_NAME)
    if material is not None:
        return material
    try:
        _append_from_reference(
            material_names=(GLOBAL_CLOUD_MATERIAL_NAME,),
            blend_path=GLOBAL_CLOUD_REFERENCE_BLEND_PATH,
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed appending Global Clouds material template", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed appending Global Clouds material template", exc_info=True)
    return bpy.data.materials.get(GLOBAL_CLOUD_MATERIAL_NAME)


def _copy_global_cloud_material_input_defaults(material, source_material=None):
    target_node = _cloud_material_group_node(material)
    if target_node is None:
        return False
    source_material = source_material or _ensure_global_cloud_material_template()
    source_node = _cloud_material_group_node(source_material)
    if source_node is None or source_node == target_node:
        return False

    changed = False
    for socket in tuple(getattr(source_node, "inputs", ())):
        name = str(getattr(socket, "name", "") or "")
        if not name or name == "Source Texture":
            continue
        target_socket = target_node.inputs.get(name)
        if target_socket is None or not hasattr(target_socket, "default_value") or not hasattr(socket, "default_value"):
            continue
        try:
            target_socket.default_value = socket.default_value
            changed = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed copying Global Clouds material default", exc_info=True)
        except (TypeError, ValueError, AttributeError):
            logger.debug("Planetka clouds: failed copying Global Clouds material default", exc_info=True)
    return changed


def _global_cloud_material_input_default(socket_name, fallback):
    return _cloud_material_input_default(_ensure_global_cloud_material_template(), socket_name, fallback)


def _local_cloud_material_input_default(socket_name, fallback):
    source_material = bpy.data.materials.get(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME)
    if source_material is None:
        try:
            _append_from_reference(
                material_names=(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME,),
                blend_path=LOCAL_CLOUD_REFERENCE_BLEND_PATH,
            )
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed appending Local Clouds material template", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka clouds: failed appending Local Clouds material template", exc_info=True)
        source_material = bpy.data.materials.get(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME)
    return _cloud_material_input_default(source_material, socket_name, fallback)


def _cloud_material_input_default(source_material, socket_name, fallback):
    source_node = _cloud_material_group_node(source_material)
    socket = source_node.inputs.get(socket_name) if source_node is not None else None
    if socket is None or not hasattr(socket, "default_value"):
        return fallback
    try:
        return socket.default_value
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return fallback


def _resolve_object_material(obj):
    material = getattr(obj, "active_material", None)
    if material is not None:
        return material
    data = getattr(obj, "data", None)
    materials = getattr(data, "materials", None) if data is not None else None
    if materials:
        return materials[0]
    return None


def _set_local_cloud_texture_by_filename(obj, filename):
    if not _is_local_cloud_object(obj):
        return False
    if not filename or filename == "NONE":
        return False
    if str(filename) in REMOTE_LOCAL_CLOUD_FILES:
        material = _resolve_object_material(obj)
        image_node = _find_image_texture_node(material)
        if image_node is None:
            return False
        try:
            obj[LOCAL_CLOUD_OBJ_TEXTURE_PROP] = str(filename)
            obj[LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP] = ""
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass

        scene = getattr(bpy.context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        quality_mode = _normalize_cloud_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW") if props else "PREVIEW")
        if not _prepare_local_cloud_texture_variants(obj, scene=scene, allow_download=True):
            logger.error("Planetka clouds: remote texture-based cloud variants could not be prepared: %s", filename)
            return False
        return _apply_prepared_local_cloud_texture(
            obj,
            scene=scene,
            allow_prepare_missing=False,
            quality_mode=quality_mode,
        )

    if os.path.isfile(str(filename)):
        texture_path = os.path.abspath(str(filename))
    else:
        texture_path = ""
    if not texture_path:
        existing_path = str(obj.get(LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP, "") or "")
        if existing_path:
            existing_path = bpy.path.abspath(existing_path)
            if os.path.isfile(existing_path):
                texture_path = os.path.abspath(existing_path)
    assets = _refresh_remote_local_cloud_assets(force=False)
    if not texture_path and str(filename) not in assets:
        path = _resolve_remote_local_cloud_asset(str(filename))
        if path:
            assets = {**assets, str(filename): path}
    if not texture_path:
        texture_path = assets.get(str(filename), "")
    if not os.path.isfile(texture_path):
        return False

    material = _resolve_object_material(obj)
    image_node = _find_image_texture_node(material)
    if image_node is None:
        return False

    try:
        obj[LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP] = os.path.abspath(texture_path)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass

    scene = getattr(bpy.context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    quality_mode = _normalize_cloud_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW") if props else "PREVIEW")
    if not _prepare_local_cloud_texture_variants(obj, scene=scene, allow_download=False):
        logger.error("Planetka clouds: local cloud texture variants could not be prepared: %s", texture_path)
        return False
    return _apply_prepared_local_cloud_texture(
        obj,
        scene=scene,
        allow_prepare_missing=False,
        quality_mode=quality_mode,
    )


def _is_named_value_node(node, node_name):
    if node is None or str(getattr(node, "type", "")) != "VALUE":
        return False
    target = str(node_name or "").strip()
    if not target:
        return False
    name = str(getattr(node, "name", "") or "")
    label = str(getattr(node, "label", "") or "")
    if name == target or label == target:
        return True
    # Be tolerant to Blender's auto-suffixed duplicates (e.g. ".001").
    return name.startswith(f"{target}.") or label.startswith(f"{target}.")


def _iter_named_value_nodes_recursive(node_tree, node_name, visited=None):
    if node_tree is None:
        return []
    if visited is None:
        visited = set()
    try:
        ptr = int(node_tree.as_pointer())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        ptr = id(node_tree)
    if ptr in visited:
        return []
    visited.add(ptr)

    found = []
    for node in node_tree.nodes:
        if _is_named_value_node(node, node_name):
            found.append((node_tree, node))
    for node in node_tree.nodes:
        child = getattr(node, "node_tree", None)
        if child is not None:
            found.extend(_iter_named_value_nodes_recursive(child, node_name, visited=visited))
    return found


def _set_named_value_nodes_recursive(node_tree, node_names, value):
    changed = False
    for node_name in node_names:
        for _tree, node in _iter_named_value_nodes_recursive(node_tree, node_name):
            try:
                node.outputs[0].default_value = float(value)
                changed = True
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed updating value node", exc_info=True)
    return changed


def _find_first_value_node(nodes, candidate_names):
    if nodes is None:
        return None
    for candidate in candidate_names:
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            continue
        node = nodes.get(candidate_text)
        if node is not None and str(getattr(node, "type", "")) == "VALUE":
            return node
        dotted_prefix = f"{candidate_text}."
        for iter_node in nodes:
            if str(getattr(iter_node, "type", "")) != "VALUE":
                continue
            name = str(getattr(iter_node, "name", "") or "")
            label = str(getattr(iter_node, "label", "") or "")
            if name.startswith(dotted_prefix) or label.startswith(dotted_prefix):
                return iter_node
    return None


def _set_value_node_output(node, value):
    if node is None:
        return False
    try:
        node.outputs[0].default_value = float(value)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed writing value node output", exc_info=True)
    except (AttributeError, RuntimeError, TypeError, ValueError, IndexError):
        logger.debug("Planetka clouds: failed writing value node output", exc_info=True)
    return False


def _mesh_local_radius(obj):
    if obj is None:
        return 0.0
    mesh = getattr(obj, "data", None)
    vertices = getattr(mesh, "vertices", None) if mesh is not None else None
    if not vertices:
        return 0.0
    try:
        return max(float(v.co.length) for v in vertices)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0.0


def _derived_local_cloud_base_scale(obj):
    earth = get_earth_object()
    earth_radius = _earth_radius_blender_units(earth)
    mesh_radius = _mesh_local_radius(obj)
    if earth_radius <= 1e-9 or mesh_radius <= 1e-9:
        return max(
            abs(float(getattr(obj, "scale", (1.0, 1.0, 1.0))[0])),
            abs(float(getattr(obj, "scale", (1.0, 1.0, 1.0))[1])),
            abs(float(getattr(obj, "scale", (1.0, 1.0, 1.0))[2])),
            1.0,
        )
    return float(earth_radius) / float(mesh_radius)


def _iter_group_nodes_recursive(node_tree, group_name, visited=None):
    if node_tree is None:
        return []
    if visited is None:
        visited = set()
    try:
        ptr = int(node_tree.as_pointer())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        ptr = id(node_tree)
    if ptr in visited:
        return []
    visited.add(ptr)

    found = []
    for node in node_tree.nodes:
        child_tree = getattr(node, "node_tree", None)
        if child_tree is None:
            continue
        child_name = str(getattr(child_tree, "name", ""))
        node_name = str(getattr(node, "name", ""))
        matches_group = node_name == group_name or child_name == group_name
        if matches_group:
            found.append(node)
        found.extend(_iter_group_nodes_recursive(child_tree, group_name, visited=visited))
    return found


def _set_group_input_if_present(group_node, input_names, value):
    if group_node is None:
        return False
    for input_name in input_names:
        if input_name not in group_node.inputs:
            continue
        try:
            socket = group_node.inputs[input_name]
            current = getattr(socket, "default_value", None)
            if hasattr(current, "__len__") and not isinstance(current, str):
                socket.default_value = value
            else:
                socket.default_value = float(value)
            return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating group input '%s'", input_name, exc_info=True)
        except (TypeError, ValueError, AttributeError):
            logger.debug("Planetka clouds: failed updating group input '%s'", input_name, exc_info=True)
    return False


def _local_cloud_half_angle_deg(size_coef):
    try:
        raw_size = float(size_coef)
    except (TypeError, ValueError):
        raw_size = 1.0
    return float(LOCAL_CLOUD_BASE_HALF_ANGLE_DEG) * max(1e-6, raw_size)


def _build_local_cloud_cap_mesh(mesh, half_angle_deg, segments=96, rings=24, inner_ratio=0.992):
    if mesh is None:
        return

    half_angle_rad = math.radians(float(half_angle_deg))
    segments = max(1, int(segments))
    rings = max(1, int(rings))
    _ = inner_ratio

    half_extent = max(1e-12, abs(math.sin(half_angle_rad)))

    verts = []
    uvs = []
    faces = []

    for y_index in range(rings + 1):
        y_factor = float(y_index) / float(rings)
        y = -half_extent + (2.0 * half_extent * y_factor)
        for x_index in range(segments + 1):
            x_factor = float(x_index) / float(segments)
            x = -half_extent + (2.0 * half_extent * x_factor)
            verts.append((float(x), float(y), 1.0))
            uvs.append((x_factor, y_factor))

    stride = segments + 1
    for y_index in range(rings):
        for x_index in range(segments):
            a = y_index * stride + x_index
            b = a + 1
            c = a + stride + 1
            d = a + stride
            faces.append((a, b, c, d))

    try:
        mesh.clear_geometry()
        mesh.from_pydata(verts, [], faces)
        mesh.update(calc_edges=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed rebuilding local cloud plane mesh", exc_info=True)
        return
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Planetka clouds: failed rebuilding local cloud plane mesh", exc_info=True)
        return

    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        try:
            uv_layer = mesh.uv_layers.new(name="UVMap")
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            uv_layer = None

    if uv_layer is not None:
        for poly in mesh.polygons:
            for loop_index in poly.loop_indices:
                vert_index = mesh.loops[loop_index].vertex_index
                try:
                    uv_layer.data[loop_index].uv = uvs[vert_index]
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka clouds: failed assigning UV to local cloud plane", exc_info=True)
                except (TypeError, ValueError, IndexError):
                    logger.debug("Planetka clouds: failed assigning UV to local cloud plane", exc_info=True)

    for polygon in mesh.polygons:
        polygon.use_smooth = True


def _ensure_local_cloud_subdivision_modifier(obj):
    if obj is None:
        return None
    modifier = None
    for candidate in getattr(obj, "modifiers", ()):
        if str(getattr(candidate, "type", "")) == "SUBSURF":
            modifier = candidate
            break
    if modifier is None:
        try:
            modifier = obj.modifiers.new(name="Subdivision", type='SUBSURF')
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating local cloud subdivision modifier", exc_info=True)
            return None
    try:
        modifier.levels = max(0, int(getattr(modifier, "levels", 1)))
        modifier.render_levels = max(1, int(getattr(modifier, "render_levels", 2)))
        if hasattr(modifier, "use_adaptive_subdivision"):
            modifier.use_adaptive_subdivision = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed configuring local cloud subdivision modifier", exc_info=True)
    return modifier


def _ensure_local_cloud_cap_geometry(obj):
    if obj is None:
        return
    half_angle = _local_cloud_half_angle_deg(getattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0))
    stored_angle = float(getattr(obj, LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG, -1.0))

    mesh = getattr(obj, "data", None)
    if mesh is None or str(getattr(obj, "type", "")) != "MESH":
        mesh_name = f"{LOCAL_CLOUD_CAP_MESH_PREFIX} {obj.name}"
        mesh = bpy.data.meshes.new(mesh_name)
        obj.data = mesh

    is_plane_mesh = False
    try:
        is_plane_mesh = bool(getattr(mesh, "vertices", ())) and all(
            abs(float(vertex.co.z) - 1.0) <= 1e-6
            for vertex in getattr(mesh, "vertices", ())
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        is_plane_mesh = False

    needs_rebuild = (
        len(getattr(mesh, "vertices", ())) == 0
        or not is_plane_mesh
        or abs(stored_angle - float(half_angle)) > 1e-3
    )
    if not needs_rebuild:
        return

    _build_local_cloud_cap_mesh(mesh, half_angle_deg=half_angle)
    _begin_cloud_update_suspend()
    try:
        setattr(obj, LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG, float(half_angle))
    finally:
        _end_cloud_update_suspend()


def _configure_local_cloud_material_for_cap(material):
    if material is None or getattr(material, "node_tree", None) is None:
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return

    nodes = node_tree.nodes
    links = node_tree.links

    image_node = _find_image_texture_node(material)
    if image_node is None:
        return

    rotate_node = nodes.get("Local Cloud UV Rotate")
    if rotate_node is None or str(getattr(rotate_node, "type", "")) != "VECTOR_ROTATE":
        rotate_node = next((node for node in nodes if str(getattr(node, "type", "")) == "VECTOR_ROTATE"), None)
    if rotate_node is None:
        try:
            rotate_node = nodes.new("ShaderNodeVectorRotate")
            rotate_node.name = "Local Cloud UV Rotate"
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating UV rotate node", exc_info=True)
            return

    tex_coord = nodes.get("Local Cloud Texture Coordinate")
    if tex_coord is None or str(getattr(tex_coord, "type", "")) != "TEX_COORD":
        tex_coord = next((node for node in nodes if str(getattr(node, "type", "")) == "TEX_COORD"), None)
    if tex_coord is None:
        try:
            tex_coord = nodes.new("ShaderNodeTexCoord")
            tex_coord.name = "Local Cloud Texture Coordinate"
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed creating texture coordinate node", exc_info=True)
            return

    try:
        rotate_node.rotation_type = 'AXIS_ANGLE'
        rotate_node.inputs["Center"].default_value = (0.5, 0.5, 0.0)
        rotate_node.inputs["Axis"].default_value = (0.0, 0.0, 1.0)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed configuring UV rotate node", exc_info=True)

    try:
        for link in list(rotate_node.inputs["Vector"].links):
            links.remove(link)
        for link in list(image_node.inputs["Vector"].links):
            links.remove(link)
        links.new(tex_coord.outputs["UV"], rotate_node.inputs["Vector"])
        links.new(rotate_node.outputs["Vector"], image_node.inputs["Vector"])
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed wiring UV mapping nodes", exc_info=True)


def _iter_cloud_subdivision_modifiers(cloud_obj):
    if cloud_obj is None:
        return []
    out = []
    seen = set()
    for mod in getattr(cloud_obj, "modifiers", ()): 
        if str(getattr(mod, "type", "")) in {"SUBSURF", "MULTIRES"}:
            ptr = int(mod.as_pointer())
            if ptr not in seen:
                out.append(mod)
                seen.add(ptr)
                continue
        if "subdiv" in str(getattr(mod, "name", "")).lower():
            ptr = int(mod.as_pointer())
            if ptr not in seen:
                out.append(mod)
                seen.add(ptr)
    return out


def _cloud_view_final_look_enabled(props):
    try:
        return str(getattr(props, "cloud_view_mode", "PREVIEW") or "PREVIEW").strip().upper() == "FINAL"
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _set_cloud_subdivision_viewport_state(cloud_obj, final_look):
    changed = 0
    for mod in _iter_cloud_subdivision_modifiers(cloud_obj):
        try:
            mod.show_viewport = bool(final_look)
            changed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating subdivision modifier state", exc_info=True)
    return changed


def apply_cloud_view_mode(scene=None, context=None):
    scene = scene or (getattr(context, "scene", None) if context else getattr(bpy.context, "scene", None))
    props = getattr(scene, "planetka", None) if scene else None
    final_look = _cloud_view_final_look_enabled(props)

    clouds_global = _get_clouds_global_module()
    apply_global_fn = getattr(clouds_global, "apply_global_cloud_subdivision_viewport_state", None) if clouds_global else None
    if callable(apply_global_fn):
        try:
            apply_global_fn(scene=scene, final_look=final_look)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed applying global cloud viewport subdivision state", exc_info=True)

    for cloud_obj in list(_iter_local_cloud_objects()):
        _set_cloud_subdivision_viewport_state(cloud_obj, final_look)

    try:
        view_layer = getattr(context, "view_layer", None) if context is not None else getattr(getattr(bpy, "context", None), "view_layer", None)
        if view_layer is not None:
            view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating view layer after cloud view mode change", exc_info=True)


def _set_universal_cloud_preview_value(preview_value):
    changed = False
    roots = (
        bpy.data.node_groups.get(CLOUD_PREVIEW_SWITCH_GROUP_NAME),
        bpy.data.node_groups.get(GLOBAL_CLOUD_SHADER_GROUP_NAME),
    )
    for root in roots:
        if root is None:
            continue
        if _set_named_value_nodes_recursive(root, (LOCAL_CLOUD_PREVIEW_VALUE_NODE_NAME,), preview_value):
            changed = True
    return changed


def _apply_universal_cloud_preview_state(props, context=None):
    quality_mode = _normalize_cloud_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW") if props else "PREVIEW")
    final_look = _cloud_view_final_look_enabled(props)
    # Keep the diffuse preview surface visible in the viewport. The volumetric
    # branch can look invisible until render settings/view mode are configured,
    # so Final Look currently means higher cloud geometry, not hidden clouds.
    preview_value = 1.0
    _set_universal_cloud_preview_value(preview_value)

    for cloud_obj in list(_iter_local_cloud_objects()):
        _apply_prepared_local_cloud_texture(
            cloud_obj,
            scene=getattr(context, "scene", None) if context else getattr(bpy.context, "scene", None),
            allow_prepare_missing=True,
            quality_mode=quality_mode,
        )
        _set_cloud_subdivision_viewport_state(cloud_obj, final_look)

    for cloud_obj in list(_iter_vdb_cloud_objects()):
        _apply_prepared_vdb_cloud_file(
            cloud_obj,
            scene=getattr(context, "scene", None) if context else getattr(bpy.context, "scene", None),
            allow_prepare_missing=True,
            quality_mode=quality_mode,
        )

    try:
        if context is not None and getattr(context, "view_layer", None):
            context.view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating view layer", exc_info=True)


def _earth_radius_blender_units(earth_obj):
    if earth_obj is None:
        return 1.0
    try:
        stored_local_radius = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stored_local_radius = 0.0

    if stored_local_radius > 1e-9:
        scale = earth_obj.matrix_world.to_scale()
        max_scale = max(abs(scale.x), abs(scale.y), abs(scale.z), 1e-9)
        return stored_local_radius * float(max_scale)

    vertices = getattr(getattr(earth_obj, "data", None), "vertices", None)
    if vertices:
        try:
            local_radius = max(v.co.length for v in vertices)
            if local_radius > 1e-9:
                scale = earth_obj.matrix_world.to_scale()
                max_scale = max(abs(scale.x), abs(scale.y), abs(scale.z), 1e-9)
                return float(local_radius) * float(max_scale)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    scale = earth_obj.matrix_world.to_scale()
    return max(abs(scale.x), abs(scale.y), abs(scale.z), 1.0)


def _scene_target_lon_lat_alt(scene):
    props = getattr(scene, "planetka", None) if scene else None

    lon = 0.0
    lat = 0.0
    alt_km = 0.0

    if props is not None:
        try:
            lon = float(getattr(props, "nav_longitude_deg", 0.0))
            lat = float(getattr(props, "nav_latitude_deg", 0.0))
            alt_km = float(getattr(props, "nav_altitude_km", 0.0))
        except (AttributeError, TypeError, ValueError):
            pass

    if scene is not None:
        try:
            lon = float(scene.get("planetka_nav_longitude_deg", lon))
            lat = float(scene.get("planetka_nav_latitude_deg", lat))
            alt_km = float(scene.get("planetka_nav_altitude_km", alt_km))
        except (TypeError, ValueError):
            pass

    return lon, lat, alt_km


def _ensure_vdb_cloud_template(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    source_obj = bpy.data.objects.get(VDB_CLOUD_TEMPLATE_OBJECT_NAME)

    if source_obj is None:
        _append_from_reference(
            object_names=(VDB_CLOUD_TEMPLATE_OBJECT_NAME,),
            material_names=(VDB_CLOUD_MATERIAL_TEMPLATE_NAME,),
            blend_path=VDB_CLOUD_REFERENCE_BLEND_PATH,
        )
        source_obj = bpy.data.objects.get(VDB_CLOUD_TEMPLATE_OBJECT_NAME)

    if source_obj is None:
        raise RuntimeError(f"VDB cloud template object '{VDB_CLOUD_TEMPLATE_OBJECT_NAME}' not found in reference blend.")

    _clear_cloud_drivers(source_obj)
    _remove_cloud_cull_modifiers(source_obj)

    # Keep the template as data-only. Linking it into the scene makes it appear
    # as an existing user cloud when the VDB Clouds collection is enabled.
    _unlink_object_from_all_collections(source_obj)
    try:
        source_obj.parent = None
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed clearing VDB template parent", exc_info=True)

    try:
        source_obj[CLOUD_ROLE_KEY] = VDB_CLOUD_TEMPLATE_ROLE
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        _log_recoverable_once("PKA-CLOUDL-004", "Failed tagging VDB template with cloud role")

    try:
        source_obj.hide_viewport = True
        source_obj.hide_render = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed hiding VDB cloud template", exc_info=True)

    mat = bpy.data.materials.get(VDB_CLOUD_MATERIAL_TEMPLATE_NAME)
    if mat is None:
        _append_from_reference(
            material_names=(VDB_CLOUD_MATERIAL_TEMPLATE_NAME,),
            blend_path=VDB_CLOUD_REFERENCE_BLEND_PATH,
        )
        mat = bpy.data.materials.get(VDB_CLOUD_MATERIAL_TEMPLATE_NAME)
    if mat is not None:
        _clear_drivers_on_id_data(mat)
        _clear_drivers_on_node_tree(getattr(mat, "node_tree", None))

    return source_obj


def _apply_local_cloud_material_controls(obj, material, final_look=False):
    if material is None or getattr(material, "node_tree", None) is None:
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return

    rot = float(getattr(obj, LOCAL_CLOUD_PROP_ROTATION_DEG, 0.0))
    density_default = float(_local_cloud_material_input_default("Density", 1.0))
    gamma_default = float(_local_cloud_material_input_default("Density Gamma", 1.0))
    contrast_default = float(_local_cloud_material_input_default("Contrast", 0.5))
    horizon_default = float(_local_cloud_material_input_default("Clouds on Horizon Transparency", 1.0))
    subsurface_default = float(_local_cloud_material_input_default("Subsurface Scattering Scale Coefficient", 1.0))
    ior_default = float(_local_cloud_material_input_default("IOR", 1.33))
    roughness_default = float(_local_cloud_material_input_default("Roughness", 0.8))
    anisotropy_default = float(_local_cloud_material_input_default("Anisotropy", LOCAL_CLOUD_ANISOTROPY_DEFAULT))
    displacement_default = float(_local_cloud_material_input_default("Displacement (Bump) Scale Coefficient", LOCAL_CLOUD_DISPLACEMENT_SCALE_DEFAULT))
    color_default = _local_cloud_material_input_default("Cloud Color", (1.0, 1.0, 1.0, 1.0))
    density = max(0.0, float(getattr(obj, LOCAL_CLOUD_PROP_DENSITY, density_default)))
    gamma = max(0.0, float(getattr(obj, LOCAL_CLOUD_PROP_DENSITY_GAMMA, gamma_default)))
    contrast = float(getattr(obj, LOCAL_CLOUD_PROP_CONTRAST, contrast_default))
    horizon = float(getattr(obj, LOCAL_CLOUD_PROP_HORIZON_TRANSPARENCY, horizon_default))
    subsurface = float(getattr(obj, LOCAL_CLOUD_PROP_SUBSURFACE_SCALE, subsurface_default))
    ior = float(getattr(obj, LOCAL_CLOUD_PROP_IOR, ior_default))
    roughness = float(getattr(obj, LOCAL_CLOUD_PROP_ROUGHNESS, roughness_default))
    anisotropy = float(getattr(obj, LOCAL_CLOUD_PROP_ANISOTROPY, anisotropy_default))
    displacement = float(getattr(obj, LOCAL_CLOUD_PROP_DISPLACEMENT_SCALE, displacement_default))
    cloud_color = getattr(obj, LOCAL_CLOUD_PROP_CLOUD_COLOR, color_default)
    _ensure_local_cloud_material_uses_cloud_material(material)
    _configure_local_cloud_material_for_cap(material)

    rotate_node = node_tree.nodes.get("Local Cloud UV Rotate")
    if rotate_node is not None and str(getattr(rotate_node, "type", "")) == "VECTOR_ROTATE":
        try:
            rotate_node.inputs["Angle"].default_value = math.radians(rot)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed setting local cloud UV rotation", exc_info=True)

    preview_value = 1.0
    _set_named_value_nodes_recursive(node_tree, (LOCAL_CLOUD_PREVIEW_VALUE_NODE_NAME,), preview_value)

    for shader_node in _iter_group_nodes_recursive(node_tree, CLOUD_MATERIAL_GROUP_NAME):
        _set_group_input_if_present(shader_node, ("Cloud Color",), cloud_color)
        _set_group_input_if_present(shader_node, ("Density", "Cloud Density"), density)
        _set_group_input_if_present(shader_node, ("Density Gamma",), gamma)
        _set_group_input_if_present(shader_node, ("Contrast",), contrast)
        _set_group_input_if_present(shader_node, ("Clouds on Horizon Transparency",), horizon)
        _set_group_input_if_present(shader_node, ("Subsurface Scattering Scale Coefficient",), subsurface)
        _set_group_input_if_present(shader_node, ("IOR",), ior)
        _set_group_input_if_present(shader_node, ("Roughness",), roughness)
        _set_group_input_if_present(shader_node, ("Anisotropy",), anisotropy)
        _set_group_input_if_present(shader_node, ("Displacement (Bump) Scale Coefficient",), displacement)


def _apply_local_cloud_object(obj, scene=None):
    if not _is_local_cloud_object(obj):
        return
    scene = scene or getattr(bpy.context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    _ensure_cloud_parented_to_root(obj, scene=scene)

    lon = float(getattr(obj, LOCAL_CLOUD_PROP_LONGITUDE, 0.0))
    lat = float(getattr(obj, LOCAL_CLOUD_PROP_LATITUDE, 0.0))
    altitude_m = float(getattr(obj, LOCAL_CLOUD_PROP_ALTITUDE_M, DEFAULT_CLOUD_ALTITUDE_M))
    size_coef = max(1e-6, float(getattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0)))

    _ensure_local_cloud_cap_geometry(obj)
    _ensure_local_cloud_subdivision_modifier(obj)

    earth = get_earth_object()
    earth_radius = max(1e-6, float(_earth_radius_blender_units(earth)))
    radius = earth_radius * max(0.001, (1.0 + (altitude_m / 6371000.0)))

    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    normal = Vector((
        math.cos(lat_rad) * math.cos(lon_rad),
        math.cos(lat_rad) * math.sin(lon_rad),
        math.sin(lat_rad),
    ))
    if normal.length <= 1e-9:
        normal = Vector((0.0, 0.0, 1.0))
    else:
        normal.normalize()

    try:
        align_quat = Vector((0.0, 0.0, 1.0)).rotation_difference(normal)
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = align_quat
        obj.location = (0.0, 0.0, 0.0)
        obj.scale = (radius, radius, radius)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating local cloud transform", exc_info=True)

    _begin_cloud_update_suspend()
    try:
        setattr(obj, LOCAL_CLOUD_PROP_BASE_SCALE, float(earth_radius))
        setattr(obj, LOCAL_CLOUD_PROP_SIZE_COEF, float(size_coef))
    finally:
        _end_cloud_update_suspend()

    quality_mode = _normalize_cloud_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW") if props else "PREVIEW")
    material_final_look = quality_mode != "PREVIEW"
    subdivision_final_look = _cloud_view_final_look_enabled(props)

    _set_cloud_subdivision_viewport_state(obj, subdivision_final_look)

    material = _resolve_object_material(obj)
    _apply_local_cloud_material_controls(obj, material, final_look=material_final_look)


def optimize_texture_based_clouds_for_camera(scene=None, quality_mode=None):
    scene = scene or getattr(bpy.context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    if quality_mode is None:
        quality_mode = getattr(props, "texture_quality_mode", "PREVIEW") if props else "PREVIEW"
    quality_mode = _normalize_cloud_quality_mode(quality_mode)
    optimized = 0
    failed = 0
    _update_cloud_lod_view_layer()
    for obj in list(_iter_local_cloud_objects()):
        if (
            _prepare_local_cloud_texture_variants(obj, scene=scene, allow_download=True)
            and _apply_prepared_local_cloud_texture(
                obj,
                scene=scene,
                allow_prepare_missing=False,
                quality_mode=quality_mode,
            )
        ):
            optimized += 1
        else:
            failed += 1
    return optimized, failed


def _vdb_grid_voxel_size_from_volume(volume_data):
    if volume_data is None:
        return 0.0
    grids = getattr(volume_data, "grids", None)
    if grids is None:
        return 0.0
    try:
        if hasattr(grids, "load") and not bool(getattr(grids, "is_loaded", False)):
            grids.load()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed loading VDB grids for voxel-size estimation", exc_info=True)
    try:
        for grid in grids:
            matrix = getattr(grid, "matrix_object", None)
            if matrix is None:
                continue
            x_len = Vector((matrix[0][0], matrix[1][0], matrix[2][0])).length
            y_len = Vector((matrix[0][1], matrix[1][1], matrix[2][1])).length
            z_len = Vector((matrix[0][2], matrix[1][2], matrix[2][2])).length
            voxel_size = max(float(x_len), float(y_len), float(z_len))
            if voxel_size > 1e-12:
                return voxel_size
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed reading VDB grid matrix", exc_info=True)
    except (AttributeError, TypeError, ValueError):
        logger.debug("Planetka clouds: failed reading VDB grid matrix", exc_info=True)
    return 0.0


def _vdb_object_local_max_extent(obj):
    if obj is None:
        return 0.0
    try:
        corners = [Vector(corner) for corner in getattr(obj, "bound_box", [])]
    except (TypeError, ValueError):
        corners = []
    if not corners:
        return 0.0
    min_x = min(float(c.x) for c in corners)
    min_y = min(float(c.y) for c in corners)
    min_z = min(float(c.z) for c in corners)
    max_x = max(float(c.x) for c in corners)
    max_y = max(float(c.y) for c in corners)
    max_z = max(float(c.z) for c in corners)
    return max(max_x - min_x, max_y - min_y, max_z - min_z, 0.0)


def _estimate_vdb_cloud_projected_pixels(obj, scene):
    if obj is None or scene is None:
        return 0.0
    camera = getattr(scene, "camera", None)
    camera_location = _camera_world_location(scene)
    if camera is None or camera_location is None:
        return 0.0
    try:
        world_center = obj.matrix_world.translation.copy()
        world_corners = [obj.matrix_world @ Vector(corner) for corner in getattr(obj, "bound_box", [])]
        if world_corners:
            min_x = min(float(c.x) for c in world_corners)
            min_y = min(float(c.y) for c in world_corners)
            min_z = min(float(c.z) for c in world_corners)
            max_x = max(float(c.x) for c in world_corners)
            max_y = max(float(c.y) for c in world_corners)
            max_z = max(float(c.z) for c in world_corners)
            world_diameter = max(max_x - min_x, max_y - min_y, max_z - min_z)
        else:
            world_diameter = max(float(value) for value in obj.dimensions)
        distance = max(1e-6, float((camera_location - world_center).length))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return 0.0
    if world_diameter <= 0.0:
        return 0.0

    width, height = _render_resolution_pixels(scene)
    data = getattr(camera, "data", None)
    camera_type = str(getattr(data, "type", "PERSP") or "PERSP").upper()
    try:
        if camera_type == "ORTHO":
            ortho_scale = max(1e-6, float(getattr(data, "ortho_scale", 1.0) or 1.0))
            return max(0.0, world_diameter * (max(width, height) / ortho_scale))
        angle = max(1e-6, float(getattr(data, "angle", math.radians(50.0)) or math.radians(50.0)))
        focal_pixels = max(width, height) / (2.0 * math.tan(angle * 0.5))
        return max(0.0, (world_diameter / distance) * focal_pixels)
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return 0.0


def _select_vdb_cloud_adaptive_d_level(obj, scene, d_level_multiplier=1):
    levels = tuple(int(level) for level in VDB_CLOUD_ADAPTIVE_D_LEVELS if int(level) > 0)
    if not levels:
        levels = (1,)
    projected_pixels = _estimate_vdb_cloud_projected_pixels(obj, scene)
    volume_data = getattr(obj, "data", None) if obj is not None else None
    voxel_size = _vdb_grid_voxel_size_from_volume(volume_data)
    current_d = 1
    try:
        current_d = max(1, int(obj.get(VDB_CLOUD_D_LEVEL_PROP, 1) or 1))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        current_d = 1
    local_extent = _vdb_object_local_max_extent(obj)
    if voxel_size <= 1e-12 or local_extent <= 1e-12 or projected_pixels <= 1.0:
        return max(levels), float(projected_pixels)

    current_voxel_count = max(1.0, float(local_extent) / float(voxel_size))
    source_voxel_count = max(1.0, current_voxel_count * float(current_d))
    target_max_d = max(1.0, (source_voxel_count / (float(projected_pixels) * float(VDB_CLOUD_ADAPTIVE_OVERSAMPLE))))
    candidates = [level for level in levels if float(level) <= target_max_d]
    final_d = max(candidates) if candidates else min(levels)
    final_d = _coarser_vdb_cloud_d_level(final_d, multiplier=d_level_multiplier)
    return int(final_d), float(projected_pixels)


def _resolve_vdb_lod_path(source_path, d_level, allow_download=True):
    source = bpy.path.abspath(str(source_path or ""))
    if not source:
        return ""
    source_name = os.path.basename(source)
    try:
        requested_level = max(1, int(d_level))
    except (TypeError, ValueError):
        requested_level = 1
    is_known_remote_source = _is_known_remote_vdb_cloud_file(source_name)
    if is_known_remote_source:
        levels = list(_nearest_published_vdb_lod_levels(source_name, requested_level))
    else:
        levels = sorted(
            {int(level) for level in VDB_CLOUD_ADAPTIVE_D_LEVELS if 0 < int(level) <= requested_level},
            reverse=True,
        )
        if requested_level not in levels:
            levels.insert(0, requested_level)
    for level in levels:
        desired_name = _vdb_lod_filename(source_name, level)
        if not desired_name:
            continue
        if desired_name == source_name and os.path.isfile(source):
            _clear_cloud_download_progress_error("Downloading VDB Cloud", source_name)
            return os.path.abspath(source)
        local_candidate = _candidate_local_vdb_lod_path(source, level)
        if local_candidate:
            _clear_cloud_download_progress_error("Downloading VDB Cloud", os.path.basename(local_candidate))
            return local_candidate
        if allow_download and is_known_remote_source:
            remote_path = _resolve_remote_vdb_cloud_asset(desired_name, progress_label="Downloading VDB Cloud")
            if remote_path and os.path.isfile(remote_path):
                return os.path.abspath(remote_path)

    if os.path.isfile(source):
        if is_known_remote_source and requested_level > 1:
            return ""
        _clear_cloud_download_progress_error("Downloading VDB Cloud", source_name)
        return os.path.abspath(source)
    return ""


def _vdb_cloud_quality_props(quality_mode):
    mode = _normalize_cloud_quality_mode(quality_mode)
    if mode == "FULL":
        return VDB_CLOUD_FINAL_FILE_PROP, VDB_CLOUD_FINAL_D_LEVEL_PROP
    if mode == "BALANCED":
        return VDB_CLOUD_BALANCED_FILE_PROP, VDB_CLOUD_BALANCED_D_LEVEL_PROP
    return VDB_CLOUD_PREVIEW_FILE_PROP, VDB_CLOUD_PREVIEW_D_LEVEL_PROP


def _prepare_vdb_cloud_variants(obj, scene=None, allow_download=True):
    if not _is_vdb_cloud_object(obj):
        return False
    source_path = str(obj.get(VDB_CLOUD_OBJ_SOURCE_FILE_PROP, "") or "")
    if source_path:
        source_path = bpy.path.abspath(source_path)
    if not source_path or not os.path.isfile(source_path):
        source_path = str(getattr(obj, VDB_CLOUD_OBJ_FILE_PROP, "") or "")
        if source_path:
            source_path = bpy.path.abspath(source_path)
    if not source_path or not os.path.isfile(source_path):
        return False

    is_known_remote_source = _is_known_remote_vdb_cloud_file(os.path.basename(source_path))
    final_d, projected_pixels = _select_vdb_cloud_adaptive_d_level(obj, scene, d_level_multiplier=1)
    balanced_d = _coarser_vdb_cloud_d_level(final_d, multiplier=2)
    preview_d = _coarser_vdb_cloud_d_level(final_d, multiplier=4)
    final_path = _resolve_vdb_lod_path(source_path, final_d, allow_download=allow_download)
    balanced_path = _resolve_vdb_lod_path(source_path, balanced_d, allow_download=allow_download)
    preview_path = _resolve_vdb_lod_path(source_path, preview_d, allow_download=allow_download)
    if not final_path or not os.path.isfile(final_path):
        if is_known_remote_source and int(final_d) > 1:
            return False
        final_path = source_path
    _base_name, final_d = _split_vdb_lod_filename(os.path.basename(final_path))
    if not balanced_path or not os.path.isfile(balanced_path):
        if is_known_remote_source and int(balanced_d) > 1:
            return False
        balanced_path = final_path
    _base_name, balanced_d = _split_vdb_lod_filename(os.path.basename(balanced_path))
    if not preview_path or not os.path.isfile(preview_path):
        if is_known_remote_source and int(preview_d) > 1:
            return False
        preview_path = balanced_path
    _base_name, preview_d = _split_vdb_lod_filename(os.path.basename(preview_path))
    try:
        obj[VDB_CLOUD_OBJ_SOURCE_FILE_PROP] = os.path.abspath(source_path)
        obj[VDB_CLOUD_FINAL_FILE_PROP] = os.path.abspath(final_path)
        obj[VDB_CLOUD_BALANCED_FILE_PROP] = os.path.abspath(balanced_path)
        obj[VDB_CLOUD_PREVIEW_FILE_PROP] = os.path.abspath(preview_path)
        obj[VDB_CLOUD_FINAL_D_LEVEL_PROP] = int(final_d)
        obj[VDB_CLOUD_BALANCED_D_LEVEL_PROP] = int(balanced_d)
        obj[VDB_CLOUD_PREVIEW_D_LEVEL_PROP] = int(preview_d)
        obj[VDB_CLOUD_PROJECTED_PIXELS_PROP] = float(projected_pixels)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed storing VDB cloud variants", exc_info=True)
    return True


def _apply_prepared_vdb_cloud_file(obj, preview=False, scene=None, allow_prepare_missing=True, quality_mode=None):
    if not _is_vdb_cloud_object(obj):
        return False
    if quality_mode is None:
        quality_mode = "PREVIEW" if preview else "FULL"
    file_prop, d_prop = _vdb_cloud_quality_props(quality_mode)
    file_path = str(obj.get(file_prop, "") or "")
    if file_path:
        file_path = bpy.path.abspath(file_path)
    if (not file_path or not os.path.isfile(file_path)) and allow_prepare_missing:
        if not _prepare_vdb_cloud_variants(obj, scene=scene, allow_download=True):
            return False
        file_path = str(obj.get(file_prop, "") or "")
        if file_path:
            file_path = bpy.path.abspath(file_path)
    if not file_path or not os.path.isfile(file_path):
        return False
    if not _set_vdb_cloud_filepath(obj, file_path):
        return False
    try:
        setattr(obj, VDB_CLOUD_OBJ_FILE_PROP, os.path.abspath(file_path))
        obj[VDB_CLOUD_LOADED_FILE_PROP] = os.path.abspath(file_path)
        obj[VDB_CLOUD_D_LEVEL_PROP] = int(obj.get(d_prop, 1) or 1)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed recording loaded VDB cloud file", exc_info=True)
    return True


def optimize_vdb_clouds_for_camera(scene=None, quality_mode=None):
    scene = scene or getattr(bpy.context, "scene", None)
    props = getattr(scene, "planetka", None) if scene else None
    if quality_mode is None:
        quality_mode = getattr(props, "texture_quality_mode", "PREVIEW") if props else "PREVIEW"
    quality_mode = _normalize_cloud_quality_mode(quality_mode)
    optimized = 0
    failed = 0
    _update_cloud_lod_view_layer()
    for obj in list(_iter_vdb_cloud_objects()):
        if (
            _prepare_vdb_cloud_variants(obj, scene=scene, allow_download=True)
            and _apply_prepared_vdb_cloud_file(
                obj,
                scene=scene,
                allow_prepare_missing=False,
                quality_mode=quality_mode,
            )
        ):
            optimized += 1
        else:
            failed += 1
    return optimized, failed


def _set_vdb_cloud_filepath(obj, filepath):
    if obj is None or not filepath:
        return False
    volume_data = getattr(obj, "data", None)
    if volume_data is None or not hasattr(volume_data, "filepath"):
        return False
    abs_path = bpy.path.abspath(filepath)
    try:
        volume_data.filepath = abs_path
        if hasattr(volume_data, "is_sequence"):
            volume_data.is_sequence = False
        if hasattr(volume_data, "grids") and hasattr(volume_data.grids, "load"):
            volume_data.grids.load()
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed assigning VDB filepath", exc_info=True)
        return False


def _copy_volume_display_settings(source_volume, target_volume):
    if source_volume is None or target_volume is None:
        return
    for owner_name in ("display", "render"):
        source_owner = getattr(source_volume, owner_name, None)
        target_owner = getattr(target_volume, owner_name, None)
        if source_owner is None or target_owner is None:
            continue
        for attr_name in (
            "density",
            "interpolation_method",
            "slice_axis",
            "slice_depth",
            "use_slice",
            "wireframe_detail",
            "wireframe_type",
            "clipping",
            "precision",
            "space",
            "step_size",
        ):
            if not hasattr(source_owner, attr_name) or not hasattr(target_owner, attr_name):
                continue
            try:
                setattr(target_owner, attr_name, getattr(source_owner, attr_name))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed copying VDB volume display setting", exc_info=True)
            except (AttributeError, TypeError, ValueError):
                logger.debug("Planetka clouds: failed copying VDB volume display setting", exc_info=True)


def _apply_vdb_cloud_material_density(obj):
    material = _resolve_object_material(obj)
    if material is None or getattr(material, "node_tree", None) is None:
        return
    node_tree = getattr(material, "node_tree", None)
    if node_tree is None:
        return
    density = max(0.0, float(getattr(obj, VDB_CLOUD_PROP_DENSITY, DEFAULT_VDB_CLOUD_DENSITY)))
    _set_named_value_nodes_recursive(node_tree, (VDB_CLOUD_DENSITY_NODE_NAME,), density)
    for node in tuple(getattr(node_tree, "nodes", ())):
        if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
            continue
        socket = node.inputs.get("Density")
        if socket is None or not hasattr(socket, "default_value"):
            continue
        try:
            socket.default_value = float(density)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed updating VDB material group Density", exc_info=True)
        except (TypeError, ValueError, AttributeError):
            logger.debug("Planetka clouds: failed updating VDB material group Density", exc_info=True)


def _vdb_parent_scale(obj):
    parent_scale = 1.0
    if getattr(obj, "parent", None) is not None:
        try:
            pscale = obj.parent.scale
            parent_scale = max(abs(float(pscale.x)), abs(float(pscale.y)), abs(float(pscale.z)), 1e-6)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            parent_scale = 1.0
        except (AttributeError, TypeError, ValueError):
            parent_scale = 1.0
    return max(1e-6, float(parent_scale))


def _vdb_current_base_radius_for_parent(obj):
    earth = get_earth_object()
    earth_radius = max(1e-6, float(_earth_radius_blender_units(earth)))
    return earth_radius / _vdb_parent_scale(obj)


def _vdb_reference_base_radius_for_parent(obj):
    return max(1e-6, float(VDB_CLOUD_REFERENCE_EARTH_RADIUS_BU) / _vdb_parent_scale(obj))


def _calibrate_vdb_cloud_base_scale_if_needed(obj):
    if obj is None:
        return
    try:
        if bool(obj.get(VDB_CLOUD_SCALE_CALIBRATED_PROP, False)):
            return
        size = float(getattr(obj, VDB_CLOUD_PROP_SIZE_COEF, 1.0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        size = 1.0
    # If the user already compensated manually with a tiny Size value, do not
    # shrink that cloud a second time.
    if size <= 0.001:
        try:
            obj[VDB_CLOUD_SCALE_CALIBRATED_PROP] = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass
        return
    for prop_name in (VDB_CLOUD_PROP_BASE_SCALE_X, VDB_CLOUD_PROP_BASE_SCALE_Y, VDB_CLOUD_PROP_BASE_SCALE_Z):
        try:
            current = float(getattr(obj, prop_name, 1.0))
            if current > 0.001:
                setattr(obj, prop_name, max(1e-12, current * float(VDB_CLOUD_DEFAULT_SCALE_FACTOR)))
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka clouds: failed calibrating VDB cloud base scale", exc_info=True)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Planetka clouds: failed calibrating VDB cloud base scale", exc_info=True)
    try:
        obj[VDB_CLOUD_SCALE_CALIBRATED_PROP] = True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass


def _apply_vdb_cloud_object(obj, scene=None):
    if not _is_vdb_cloud_object(obj):
        return
    scene = scene or getattr(bpy.context, "scene", None)
    _ensure_cloud_parented_to_root(obj, scene=scene)
    _calibrate_vdb_cloud_base_scale_if_needed(obj)

    lon = float(getattr(obj, VDB_CLOUD_PROP_LONGITUDE, 0.0))
    lat = float(getattr(obj, VDB_CLOUD_PROP_LATITUDE, 0.0))
    alt = float(getattr(obj, VDB_CLOUD_PROP_ALTITUDE_M, 5000.0))
    size = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_SIZE_COEF, 1.0)))
    rot = float(getattr(obj, VDB_CLOUD_PROP_ROTATION_DEG, 0.0))

    base_radius = _vdb_current_base_radius_for_parent(obj)
    radius = base_radius * (1.0 + alt / 6371000.0)

    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    rot_rad = math.radians(rot)

    x = radius * math.cos(lat_rad) * math.cos(lon_rad)
    y = radius * math.cos(lat_rad) * math.sin(lon_rad)
    z = radius * math.sin(lat_rad)

    try:
        obj.location = (x, y, z)
        obj.rotation_mode = 'XYZ'
        obj.rotation_euler = (
            math.atan2(math.cos(rot_rad) * math.cos(lat_rad), math.sin(lat_rad)) + math.radians(90.0),
            math.asin(max(-1.0, min(1.0, -math.sin(rot_rad) * math.cos(lat_rad)))),
            math.atan2(
                math.cos(rot_rad) * math.cos(lon_rad) - math.sin(rot_rad) * math.sin(lat_rad) * math.sin(lon_rad),
                -math.cos(rot_rad) * math.sin(lon_rad) - math.sin(rot_rad) * math.sin(lat_rad) * math.cos(lon_rad),
            ),
        )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating VDB cloud transform", exc_info=True)

    base_x = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_BASE_SCALE_X, abs(obj.scale.x) if obj.scale else 1.0)))
    base_y = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_BASE_SCALE_Y, abs(obj.scale.y) if obj.scale else 1.0)))
    base_z = max(1e-6, float(getattr(obj, VDB_CLOUD_PROP_BASE_SCALE_Z, abs(obj.scale.z) if obj.scale else 1.0)))
    radius_scale = base_radius / _vdb_reference_base_radius_for_parent(obj)

    try:
        obj.scale = (base_x * radius_scale * size, base_y * radius_scale * size, base_z * radius_scale * size)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating VDB cloud scale", exc_info=True)

    file_path = str(getattr(obj, VDB_CLOUD_OBJ_FILE_PROP, "") or "")
    if file_path:
        _set_vdb_cloud_filepath(obj, file_path)

    _apply_vdb_cloud_material_density(obj)


def _resolve_vdb_path(raw_value):
    raw = str(raw_value or "").strip()
    assets = _refresh_remote_vdb_cloud_assets(force=False)
    if not raw:
        first_key = REMOTE_VDB_CLOUD_FILES[0] if REMOTE_VDB_CLOUD_FILES else ""
        return _resolve_remote_vdb_cloud_asset(first_key) if first_key else ""
    if raw in assets:
        return assets.get(raw, "")
    if _is_known_remote_vdb_cloud_file(raw):
        return _resolve_remote_vdb_cloud_asset(raw)
    candidate = bpy.path.abspath(raw)
    if os.path.isdir(candidate):
        first = _first_vdb_in_dir(candidate)
        if first:
            return first
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)

    fallback = assets.get(os.path.basename(raw), "")
    if fallback and os.path.isfile(fallback):
        return os.path.abspath(fallback)

    basename = os.path.basename(raw)
    if _is_known_remote_vdb_cloud_file(basename):
        return _resolve_remote_vdb_cloud_asset(basename)

    return os.path.abspath(candidate)


def _first_vdb_in_dir(folder):
    assets = _refresh_remote_vdb_cloud_assets(force=False)
    if assets:
        first_key = sorted(assets.keys())[0]
        first_path = assets.get(first_key, "")
        if first_path and os.path.isfile(first_path):
            return os.path.abspath(first_path)
    if REMOTE_VDB_CLOUD_FILES:
        remote_path = _resolve_remote_vdb_cloud_asset(REMOTE_VDB_CLOUD_FILES[0])
        if remote_path and os.path.isfile(remote_path):
            return os.path.abspath(remote_path)
    if not folder or not os.path.isdir(folder):
        return ""
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name.lower().endswith(".vdb"):
            return os.path.abspath(path)
    return ""


def _apply_cloud_object_updates_for_scene(scene):
    if scene is None:
        return
    # Explicitly remove cloud culling from all cloud objects.
    clouds_global = _get_clouds_global_module()
    ensure_global_fn = getattr(clouds_global, "ensure_global_cloud_layer", None) if clouds_global else None
    apply_global_fn = getattr(clouds_global, "apply_global_cloud_object", None) if clouds_global else None
    if callable(ensure_global_fn):
        global_obj = ensure_global_fn(scene=scene)
        _remove_cloud_cull_modifiers(global_obj)
        if callable(apply_global_fn):
            apply_global_fn(global_obj, scene=scene)
    for obj in _iter_local_cloud_objects():
        _remove_cloud_cull_modifiers(obj)
        _apply_local_cloud_object(obj, scene=scene)
    for obj in _iter_vdb_cloud_objects():
        _remove_cloud_cull_modifiers(obj)
        _apply_vdb_cloud_object(obj, scene=scene)


def update_enable_local_clouds(self, context):
    scene = getattr(context, "scene", None) if context else None
    _sync_scene_idprops(
        scene,
        (
            "enable_local_clouds",
            "local_cloud_texture_source",
            "local_cloud_local_file",
            "local_cloud_texture",
        ),
    )
    _sync_cloud_collection_visibility(scene, self)
    if bool(getattr(self, "enable_local_clouds", False)):
        _apply_universal_cloud_preview_state(self, context=context)


def update_cloud_view_mode(self, context):
    scene = getattr(context, "scene", None) if context else None
    _sync_scene_idprops(scene, ("cloud_view_mode",))
    apply_cloud_view_mode(scene=scene, context=context)


def update_enable_vdb_clouds(self, context):
    scene = getattr(context, "scene", None) if context else None
    _sync_scene_idprops(scene, ("enable_vdb_clouds", "vdb_cloud_source", "vdb_cloud_preset", "vdb_cloud_file"))
    _sync_cloud_collection_visibility(scene, self)



def update_local_cloud_object_texture(self, context):
    obj = self
    if _is_cloud_updates_suspended() or not _is_local_cloud_object(obj):
        return
    filename = str(getattr(obj, LOCAL_CLOUD_OBJ_TEXTURE_PROP, "") or "")
    _set_local_cloud_texture_by_filename(obj, filename)
    scene = getattr(context, "scene", None) if context else None
    _apply_local_cloud_object(obj, scene=scene)
    _request_cloud_lod_resolve(scene)


def update_local_cloud_object_prop(self, context):
    if _is_cloud_updates_suspended() or not _is_local_cloud_object(self):
        return
    scene = getattr(context, "scene", None) if context else None
    _apply_local_cloud_object(self, scene=scene)
    _request_cloud_lod_resolve(scene)


def update_local_cloud_object_size(self, context):
    if _is_cloud_updates_suspended() or not _is_local_cloud_object(self):
        return
    scene = getattr(context, "scene", None) if context else None
    _apply_local_cloud_object(self, scene=scene)
    _request_cloud_lod_resolve(scene, immediate=True)


def update_vdb_cloud_object_prop(self, context):
    if _is_cloud_updates_suspended() or not _is_vdb_cloud_object(self):
        return
    scene = getattr(context, "scene", None) if context else None
    _apply_vdb_cloud_object(self, scene=scene)
    _request_cloud_lod_resolve(scene)


def update_vdb_cloud_object_size(self, context):
    if _is_cloud_updates_suspended() or not _is_vdb_cloud_object(self):
        return
    scene = getattr(context, "scene", None) if context else None
    _apply_vdb_cloud_object(self, scene=scene)
    _request_cloud_lod_resolve(scene, immediate=True)


def sync_cloud_system_scene(scene):
    props = getattr(scene, "planetka", None) if scene else None
    _sync_cloud_collection_visibility(scene, props)
    if props is not None and bool(getattr(props, "enable_global_clouds", False)):
        clouds_global = _get_clouds_global_module()
        ensure_global_fn = getattr(clouds_global, "ensure_global_cloud_layer", None) if clouds_global else None
        if callable(ensure_global_fn):
            try:
                ensure_global_fn(scene=scene)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed ensuring global cloud layer during sync", exc_info=True)
    _apply_cloud_object_updates_for_scene(scene)
    if props is not None:
        _apply_universal_cloud_preview_state(props, context=None)


def _is_workflow_enabled():
    try:
        return bool(is_authenticated(get_prefs())) and (get_earth_object() is not None)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False


def _request_cloud_lod_resolve(scene, immediate=False):
    if scene is None or _is_cloud_updates_suspended():
        return
    try:
        from . import state as planetka_state
        request_fn = getattr(planetka_state, "request_auto_resolve", None)
        if callable(request_fn):
            request_fn(scene, immediate=bool(immediate), mark_dirty=True)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed requesting cloud LOD resolve", exc_info=True)
    except (ImportError, ModuleNotFoundError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed requesting cloud LOD resolve", exc_info=True)


def _update_cloud_lod_view_layer():
    try:
        view_layer = getattr(getattr(bpy, "context", None), "view_layer", None)
        if view_layer is not None:
            view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka clouds: failed updating view layer before cloud LOD estimation", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka clouds: failed updating view layer before cloud LOD estimation", exc_info=True)


def _cloud_title(name, fallback_index, prefix):
    match = re.search(r"(\d+)$", str(name or ""))
    if match:
        try:
            return f"{prefix} {int(match.group(1)):03d}"
        except (TypeError, ValueError):
            pass
    return f"{prefix} {fallback_index:03d}"


def _vdb_file_label(obj):
    path = str(getattr(obj, VDB_CLOUD_OBJ_FILE_PROP, "") or "")
    if not path:
        data = getattr(obj, "data", None)
        path = str(getattr(data, "filepath", "") or "") if data else ""
    if not path:
        return "No VDB file assigned"
    return os.path.basename(bpy.path.abspath(path))


def _local_cloud_file_label(obj):
    path = ""
    material = _resolve_object_material(obj)
    image_node = _find_image_texture_node(material)
    image = getattr(image_node, "image", None) if image_node is not None else None
    path = str(getattr(image, "filepath", "") or "")
    if path:
        path = bpy.path.abspath(path)
    if not path:
        path = str(obj.get(LOCAL_CLOUD_LOADED_TEXTURE_PROP, "") or "") if obj is not None else ""
        if path:
            path = bpy.path.abspath(path)
    if not path:
        path = str(obj.get(LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP, "") or "") if obj is not None else ""
        if path:
            path = bpy.path.abspath(path)
    if not path:
        return "No cloud mask assigned"
    basename = os.path.basename(path)
    if not basename:
        return "No cloud mask assigned"
    if re.search(r"_d\d{3}(?:\.|_)", basename, flags=re.IGNORECASE):
        return basename
    try:
        d_level = int(obj.get(LOCAL_CLOUD_D_LEVEL_PROP, 0) or 0)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        d_level = 0
    if d_level > 0:
        return f"{basename} (d{d_level:03d})"
    return basename


class PLANETKA_OT_AddLocalCloud(bpy.types.Operator):
    bl_idname = "planetka.add_local_cloud"
    bl_label = "Add Cloud"
    bl_description = "Add a texture-based cloud layer"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _download_thread = None
    _download_done = False
    _download_path = ""
    _download_error = ""
    _download_selected = ""

    def _props(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        return scene, props

    def _selected_remote_cloud(self, props):
        selected = str(getattr(props, "local_cloud_texture", "") or "")
        if not selected or selected == "NONE":
            return ""
        return selected

    def _create_cloud_from_texture(self, context, source, selected, texture_path):
        scene, props = self._props(context)
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}
        is_remote_cloud = source != "LOCAL" and selected in REMOTE_LOCAL_CLOUD_FILES
        if not is_remote_cloud and not os.path.isfile(texture_path):
            self.report({'ERROR'}, f"Selected texture not found: {texture_path}")
            return {'CANCELLED'}

        _clouds, _global_clouds, local_clouds, _vdb_clouds = _ensure_cloud_collections(scene)

        template_mat = bpy.data.materials.get(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME)
        if template_mat is None:
            try:
                _append_from_reference(
                    material_names=(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME,),
                    blend_path=LOCAL_CLOUD_REFERENCE_BLEND_PATH,
                )
            except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
                self.report({'ERROR'}, f"Failed loading texture-based cloud material template: {exc}")
                return {'CANCELLED'}
            template_mat = bpy.data.materials.get(LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME)
        if template_mat is None:
            self.report({'ERROR'}, f"Material '{LOCAL_CLOUD_MATERIAL_TEMPLATE_NAME}' not found.")
            return {'CANCELLED'}
        _ensure_local_cloud_material_uses_cloud_material(template_mat)

        new_name = _next_local_cloud_name()
        mesh_name = f"{LOCAL_CLOUD_CAP_MESH_PREFIX} {new_name}"
        try:
            mesh = bpy.data.meshes.new(mesh_name)
            new_obj = bpy.data.objects.new(new_name, mesh)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed creating texture-based cloud object: {exc}")
            return {'CANCELLED'}

        try:
            local_clouds.objects.link(new_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            try:
                bpy.data.objects.remove(new_obj, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-CLOUDL-005", "Failed cleanup-removing local cloud object after link failure")
            if mesh is not None and int(getattr(mesh, "users", 0)) == 0:
                try:
                    bpy.data.meshes.remove(mesh)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-CLOUDL-006", "Failed cleanup-removing local cloud mesh after link failure")
            self.report({'ERROR'}, f"Failed linking texture-based cloud: {exc}")
            return {'CANCELLED'}

        new_mat = template_mat.copy()
        new_mat.name = _local_cloud_material_name_for_object(new_obj.name)
        _clear_drivers_on_id_data(new_mat)
        _clear_drivers_on_node_tree(getattr(new_mat, "node_tree", None))
        _ensure_local_cloud_material_uses_cloud_material(new_mat)
        _copy_global_cloud_material_input_defaults(new_mat, source_material=template_mat)

        mesh = getattr(new_obj, "data", None)
        if mesh is not None and hasattr(mesh, "materials"):
            try:
                mesh.materials.clear()
                mesh.materials.append(new_mat)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed assigning local cloud material", exc_info=True)

        _ensure_cloud_parented_to_root(new_obj, scene=scene)

        try:
            new_obj[CLOUD_ROLE_KEY] = LOCAL_CLOUD_ROLE
            new_obj.hide_viewport = False
            new_obj.hide_render = False
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-007", "Failed setting local cloud role/visibility flags")

        lon, lat, _alt_km = _scene_target_lon_lat_alt(scene)

        _begin_cloud_update_suspend()
        try:
            setattr(new_obj, LOCAL_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(new_obj, LOCAL_CLOUD_PROP_LATITUDE, float(lat))
            setattr(new_obj, LOCAL_CLOUD_PROP_ALTITUDE_M, float(DEFAULT_CLOUD_ALTITUDE_M))
            setattr(new_obj, LOCAL_CLOUD_PROP_SIZE_COEF, 1.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_ROTATION_DEG, 0.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_THICKNESS_M, 50.0)
            setattr(new_obj, LOCAL_CLOUD_PROP_CLOUD_COLOR, tuple(_local_cloud_material_input_default("Cloud Color", (1.0, 1.0, 1.0, 1.0))))
            setattr(new_obj, LOCAL_CLOUD_PROP_DENSITY, float(_local_cloud_material_input_default("Density", 1.0)))
            setattr(new_obj, LOCAL_CLOUD_PROP_DENSITY_GAMMA, float(_local_cloud_material_input_default("Density Gamma", 1.0)))
            setattr(new_obj, LOCAL_CLOUD_PROP_CONTRAST, float(_local_cloud_material_input_default("Contrast", 0.5)))
            setattr(new_obj, LOCAL_CLOUD_PROP_HORIZON_TRANSPARENCY, float(_local_cloud_material_input_default("Clouds on Horizon Transparency", 1.0)))
            setattr(new_obj, LOCAL_CLOUD_PROP_SUBSURFACE_SCALE, float(_local_cloud_material_input_default("Subsurface Scattering Scale Coefficient", 1.0)))
            setattr(new_obj, LOCAL_CLOUD_PROP_IOR, float(_local_cloud_material_input_default("IOR", 1.33)))
            setattr(new_obj, LOCAL_CLOUD_PROP_ROUGHNESS, float(_local_cloud_material_input_default("Roughness", 0.8)))
            setattr(new_obj, LOCAL_CLOUD_PROP_ANISOTROPY, float(_local_cloud_material_input_default("Anisotropy", LOCAL_CLOUD_ANISOTROPY_DEFAULT)))
            setattr(new_obj, LOCAL_CLOUD_PROP_DISPLACEMENT_SCALE, float(_local_cloud_material_input_default("Displacement (Bump) Scale Coefficient", LOCAL_CLOUD_DISPLACEMENT_SCALE_DEFAULT)))
            setattr(new_obj, LOCAL_CLOUD_PROP_BASE_SCALE, float(max(1e-6, _earth_radius_blender_units(get_earth_object()))))
            setattr(new_obj, LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG, -1.0)
            if source != "LOCAL":
                setattr(new_obj, LOCAL_CLOUD_OBJ_TEXTURE_PROP, selected)
            new_obj[LOCAL_CLOUD_OBJ_TEXTURE_PATH_PROP] = os.path.abspath(texture_path) if texture_path else ""
        finally:
            _end_cloud_update_suspend()

        _set_local_cloud_texture_by_filename(new_obj, selected)
        _apply_local_cloud_object(new_obj, scene=scene)

        try:
            props.enable_local_clouds = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _sync_cloud_collection_visibility(scene, props)

        _apply_universal_cloud_preview_state(props, context=context)

        try:
            context.view_layer.objects.active = new_obj
            new_obj.select_set(True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-008", "Failed selecting newly created local cloud object")

        self.report({'INFO'}, f"Added texture-based cloud: {new_obj.name}")
        return {'FINISHED'}

    def _start_remote_download(self, context, selected):
        self._download_done = False
        self._download_path = ""
        self._download_error = ""
        self._download_selected = selected

        def worker():
            try:
                path = _resolve_remote_local_cloud_asset(selected, progress_label="Downloading Texture-Based Cloud")
                self._download_path = path
                if not path or not os.path.isfile(path):
                    self._download_error = "Selected cloud mask could not be downloaded."
            except Exception as exc:  # Keep the background thread from killing Blender.
                logger.debug("Planetka clouds: local cloud download worker failed", exc_info=True)
                self._download_error = str(exc) or "Selected cloud mask could not be downloaded."
            finally:
                self._download_done = True

        self._download_thread = threading.Thread(target=worker, name="PlanetkaLocalCloudDownload", daemon=True)
        self._download_thread.start()
        wm = getattr(context, "window_manager", None)
        if wm is not None:
            self._timer = wm.event_timer_add(0.2, window=getattr(context, "window", None))
            wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        scene, props = self._props(context)
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}
        source = str(getattr(props, "local_cloud_texture_source", "CLOUD") or "CLOUD").strip().upper()
        if source == "LOCAL":
            return self.execute(context)
        selected = self._selected_remote_cloud(props)
        if not selected:
            self.report({'ERROR'}, "Select a Planetka Cloud mask first.")
            return {'CANCELLED'}
        return self._create_cloud_from_texture(context, "CLOUD", selected, "")

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.tag_redraw()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
        if not self._download_done:
            return {'RUNNING_MODAL'}
        wm = getattr(context, "window_manager", None)
        if wm is not None and self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
            self._timer = None
        if self._download_error:
            self.report({'ERROR'}, self._download_error)
            return {'CANCELLED'}
        return self._create_cloud_from_texture(context, "CLOUD", self._download_selected, self._download_path)

    def execute(self, context):
        scene, props = self._props(context)
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}

        source = str(getattr(props, "local_cloud_texture_source", "CLOUD") or "CLOUD").strip().upper()
        selected = str(getattr(props, "local_cloud_texture", "") or "")
        if source == "LOCAL":
            texture_path = os.path.abspath(os.path.expanduser(str(getattr(props, "local_cloud_local_file", "") or "").strip()))
            if not texture_path or not os.path.isfile(texture_path):
                self.report({'ERROR'}, "Select a valid local EXR cloud mask first.")
                return {'CANCELLED'}
            if not texture_path.lower().endswith(".exr"):
                self.report({'ERROR'}, "Texture-based cloud masks must be EXR files.")
                return {'CANCELLED'}
            selected = texture_path
        else:
            if not selected or selected == "NONE":
                self.report({'ERROR'}, "Select a Planetka Cloud mask first.")
                return {'CANCELLED'}
            texture_path = ""
        return self._create_cloud_from_texture(context, source, selected, texture_path)


class PLANETKA_OT_ResetLocalCloudToCameraView(bpy.types.Operator):
    bl_idname = "planetka.reset_local_cloud_to_camera_view"
    bl_label = "Reset Cloud Position"
    bl_description = "Reset selected texture-based cloud to current Planetka camera target"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_local_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_local_cloud_object(active_obj):
            return active_obj
        return None

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a texture-based cloud object first.")
            return {'CANCELLED'}

        lon, lat, _alt_km = _scene_target_lon_lat_alt(getattr(context, "scene", None))
        _begin_cloud_update_suspend()
        try:
            setattr(obj, LOCAL_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(obj, LOCAL_CLOUD_PROP_LATITUDE, float(lat))
            setattr(obj, LOCAL_CLOUD_PROP_ALTITUDE_M, float(DEFAULT_CLOUD_ALTITUDE_M))
        finally:
            _end_cloud_update_suspend()

        _apply_local_cloud_object(obj, scene=getattr(context, "scene", None))
        self.report({'INFO'}, f"{obj.name}: moved to camera target")
        return {'FINISHED'}


class PLANETKA_OT_DeleteLocalCloud(bpy.types.Operator):
    bl_idname = "planetka.delete_local_cloud"
    bl_label = "Delete Cloud"
    bl_description = "Delete this texture-based cloud"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_local_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_local_cloud_object(active_obj):
            return active_obj
        return None

    def invoke(self, context, event):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a texture-based cloud object first.")
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a texture-based cloud object first.")
            return {'CANCELLED'}

        mesh = getattr(obj, "data", None)
        materials = []
        if mesh is not None and hasattr(mesh, "materials"):
            materials = [mat for mat in mesh.materials if mat]

        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed deleting cloud: {exc}")
            return {'CANCELLED'}

        if mesh is not None and int(getattr(mesh, "users", 0)) == 0:
            try:
                bpy.data.meshes.remove(mesh)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed removing unused local cloud mesh", exc_info=True)

        for mat in materials:
            if mat is not None and int(getattr(mat, "users", 0)) == 0:
                try:
                    bpy.data.materials.remove(mat)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka clouds: failed removing local cloud material", exc_info=True)

        self.report({'INFO'}, "Texture-based cloud deleted")
        return {'FINISHED'}


class PLANETKA_OT_AddVDBCloud(bpy.types.Operator):
    bl_idname = "planetka.add_vdb_cloud"
    bl_label = "Add Cloud"
    bl_description = "Add a VDB cloud from template"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _download_thread = None
    _download_done = False
    _download_path = ""
    _download_error = ""
    _download_selected = ""

    def _props(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        return scene, props

    def _selected_remote_cloud(self, props):
        selected = str(getattr(props, "vdb_cloud_preset", "") or "")
        if not selected or selected == "NONE":
            return ""
        return selected

    def _create_vdb_cloud_from_path(self, context, source, vdb_path):
        scene, props = self._props(context)
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}

        if not vdb_path or not os.path.isfile(vdb_path):
            self.report({'ERROR'}, "Select a valid VDB file first.")
            return {'CANCELLED'}

        if not str(vdb_path).lower().endswith(".vdb"):
            self.report({'ERROR'}, f"Selected file is not a VDB: {vdb_path}")
            return {'CANCELLED'}

        try:
            source_obj = _ensure_vdb_cloud_template(scene)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed preparing VDB cloud template: {exc}")
            return {'CANCELLED'}

        _clouds, _global_clouds, _local_clouds, vdb_clouds = _ensure_cloud_collections(scene)
        new_name = _next_vdb_cloud_name()

        try:
            volume_data = bpy.data.volumes.new(f"{new_name} Volume")
            _copy_volume_display_settings(getattr(source_obj, "data", None), volume_data)
            new_obj = bpy.data.objects.new(new_name, volume_data)
            vdb_clouds.objects.link(new_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed linking VDB cloud: {exc}")
            return {'CANCELLED'}
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            self.report({'ERROR'}, f"Failed creating VDB cloud volume: {exc}")
            return {'CANCELLED'}

        template_mat = _resolve_object_material(source_obj) or bpy.data.materials.get(VDB_CLOUD_MATERIAL_TEMPLATE_NAME)
        if template_mat is None:
            self.report({'ERROR'}, f"Material '{VDB_CLOUD_MATERIAL_TEMPLATE_NAME}' not found.")
            try:
                bpy.data.objects.remove(new_obj, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-CLOUDL-012", "Failed cleanup-removing VDB cloud object after material error")
            return {'CANCELLED'}

        new_mat = template_mat.copy()
        new_mat.name = _vdb_cloud_material_name_for_object(new_obj.name)
        _clear_drivers_on_id_data(new_mat)
        _clear_drivers_on_node_tree(getattr(new_mat, "node_tree", None))

        data = getattr(new_obj, "data", None)
        if data is not None and hasattr(data, "materials"):
            try:
                data.materials.clear()
                data.materials.append(new_mat)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed assigning VDB material", exc_info=True)

        _ensure_cloud_parented_to_root(new_obj, scene=scene)
        if not _set_vdb_cloud_filepath(new_obj, vdb_path):
            self.report({'ERROR'}, f"Failed loading VDB file: {vdb_path}")
            try:
                bpy.data.objects.remove(new_obj, do_unlink=True)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                _log_recoverable_once("PKA-CLOUDL-009", "Failed cleanup-removing VDB cloud object after file load error")
            if int(getattr(volume_data, "users", 0)) == 0:
                try:
                    bpy.data.volumes.remove(volume_data)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    _log_recoverable_once("PKA-CLOUDL-010", "Failed cleanup-removing VDB cloud volume after file load error")
            return {'CANCELLED'}

        try:
            new_obj[CLOUD_ROLE_KEY] = VDB_CLOUD_ROLE
            new_obj.hide_viewport = False
            new_obj.hide_render = False
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-013", "Failed setting VDB cloud role/visibility flags")

        base_radius = _vdb_current_base_radius_for_parent(new_obj)

        lon, lat, _alt_km = _scene_target_lon_lat_alt(scene)
        _begin_cloud_update_suspend()
        try:
            setattr(new_obj, VDB_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(new_obj, VDB_CLOUD_PROP_LATITUDE, float(lat))
            setattr(new_obj, VDB_CLOUD_PROP_ALTITUDE_M, float(DEFAULT_CLOUD_ALTITUDE_M))
            setattr(new_obj, VDB_CLOUD_PROP_SIZE_COEF, 1.0)
            setattr(new_obj, VDB_CLOUD_PROP_ROTATION_DEG, 0.0)
            setattr(new_obj, VDB_CLOUD_PROP_DENSITY, DEFAULT_VDB_CLOUD_DENSITY)
            setattr(new_obj, VDB_CLOUD_PROP_BASE_SCALE_X, abs(float(new_obj.scale.x)) * float(VDB_CLOUD_DEFAULT_SCALE_FACTOR))
            setattr(new_obj, VDB_CLOUD_PROP_BASE_SCALE_Y, abs(float(new_obj.scale.y)) * float(VDB_CLOUD_DEFAULT_SCALE_FACTOR))
            setattr(new_obj, VDB_CLOUD_PROP_BASE_SCALE_Z, abs(float(new_obj.scale.z)) * float(VDB_CLOUD_DEFAULT_SCALE_FACTOR))
            setattr(new_obj, VDB_CLOUD_PROP_BASE_RADIUS, float(base_radius))
            setattr(new_obj, VDB_CLOUD_OBJ_FILE_PROP, os.path.abspath(vdb_path))
            new_obj[VDB_CLOUD_OBJ_SOURCE_FILE_PROP] = os.path.abspath(vdb_path)
            new_obj[VDB_CLOUD_LOADED_FILE_PROP] = os.path.abspath(vdb_path)
            _base_name, source_d = _split_vdb_lod_filename(os.path.basename(vdb_path))
            new_obj[VDB_CLOUD_D_LEVEL_PROP] = int(source_d)
            new_obj[VDB_CLOUD_SCALE_CALIBRATED_PROP] = True
        finally:
            _end_cloud_update_suspend()

        _apply_vdb_cloud_object(new_obj, scene=scene)
        quality_mode = _normalize_cloud_quality_mode(getattr(props, "texture_quality_mode", "PREVIEW") if props else "PREVIEW")
        if _prepare_vdb_cloud_variants(new_obj, scene=scene, allow_download=True):
            _apply_prepared_vdb_cloud_file(
                new_obj,
                scene=scene,
                allow_prepare_missing=False,
                quality_mode=quality_mode,
            )

        if source == "LOCAL":
            props.vdb_cloud_file = os.path.abspath(vdb_path)
        try:
            props.enable_vdb_clouds = True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _sync_cloud_collection_visibility(scene, props)

        try:
            context.view_layer.objects.active = new_obj
            new_obj.select_set(True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            _log_recoverable_once("PKA-CLOUDL-014", "Failed selecting newly created VDB cloud object")

        self.report({'INFO'}, f"Added VDB cloud: {new_obj.name}")
        return {'FINISHED'}

    def _start_remote_download(self, context, selected):
        self._download_done = False
        self._download_path = ""
        self._download_error = ""
        self._download_selected = selected

        def worker():
            try:
                path = _resolve_remote_vdb_cloud_asset(selected, progress_label="Downloading VDB Cloud")
                self._download_path = path
                if not path or not os.path.isfile(path):
                    self._download_error = "Selected VDB cloud could not be downloaded."
            except Exception as exc:  # Keep the background thread from killing Blender.
                logger.debug("Planetka clouds: VDB cloud download worker failed", exc_info=True)
                self._download_error = str(exc) or "Selected VDB cloud could not be downloaded."
            finally:
                self._download_done = True

        self._download_thread = threading.Thread(target=worker, name="PlanetkaVDBCloudDownload", daemon=True)
        self._download_thread.start()
        wm = getattr(context, "window_manager", None)
        if wm is not None:
            self._timer = wm.event_timer_add(0.2, window=getattr(context, "window", None))
            wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        scene, props = self._props(context)
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}
        source = str(getattr(props, "vdb_cloud_source", "CLOUD") or "CLOUD").strip().upper()
        if source == "LOCAL":
            return self.execute(context)
        selected = self._selected_remote_cloud(props)
        if not selected:
            self.report({'ERROR'}, "Select a Planetka Cloud VDB preset first.")
            return {'CANCELLED'}
        cached = _refresh_remote_vdb_cloud_assets(force=False).get(selected, "")
        if cached and os.path.isfile(cached):
            return self._create_vdb_cloud_from_path(context, "CLOUD", cached)
        return self._start_remote_download(context, selected)

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.tag_redraw()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
        if not self._download_done:
            return {'RUNNING_MODAL'}
        wm = getattr(context, "window_manager", None)
        if wm is not None and self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass
            self._timer = None
        if self._download_error:
            self.report({'ERROR'}, self._download_error)
            return {'CANCELLED'}
        return self._create_vdb_cloud_from_path(context, "CLOUD", self._download_path)

    def execute(self, context):
        scene, props = self._props(context)
        if props is None:
            self.report({'ERROR'}, "Planetka settings unavailable.")
            return {'CANCELLED'}

        source = str(getattr(props, "vdb_cloud_source", "CLOUD") or "CLOUD").strip().upper()
        if source == "LOCAL":
            vdb_path = _resolve_vdb_path(getattr(props, "vdb_cloud_file", ""))
        else:
            selected = self._selected_remote_cloud(props)
            if not selected:
                self.report({'ERROR'}, "Select a Planetka Cloud VDB preset first.")
                return {'CANCELLED'}
            vdb_path = _resolve_remote_vdb_cloud_asset(selected, progress_label="Downloading VDB Cloud")
        return self._create_vdb_cloud_from_path(context, source, vdb_path)


class PLANETKA_OT_ResetVDBCloudToCameraView(bpy.types.Operator):
    bl_idname = "planetka.reset_vdb_cloud_to_camera_view"
    bl_label = "Reset Cloud Position"
    bl_description = "Reset selected VDB cloud to current Planetka camera target"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_vdb_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_vdb_cloud_object(active_obj):
            return active_obj
        return None

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a VDB cloud object first.")
            return {'CANCELLED'}

        lon, lat, _alt_km = _scene_target_lon_lat_alt(getattr(context, "scene", None))
        _begin_cloud_update_suspend()
        try:
            setattr(obj, VDB_CLOUD_PROP_LONGITUDE, float(lon))
            setattr(obj, VDB_CLOUD_PROP_LATITUDE, float(lat))
            setattr(obj, VDB_CLOUD_PROP_ALTITUDE_M, float(DEFAULT_CLOUD_ALTITUDE_M))
        finally:
            _end_cloud_update_suspend()

        _apply_vdb_cloud_object(obj, scene=getattr(context, "scene", None))
        self.report({'INFO'}, f"{obj.name}: moved to camera target")
        return {'FINISHED'}


class PLANETKA_OT_DeleteVDBCloud(bpy.types.Operator):
    bl_idname = "planetka.delete_vdb_cloud"
    bl_label = "Delete Cloud"
    bl_description = "Delete this VDB cloud"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(
        name="Cloud Object",
        default="",
        options={'SKIP_SAVE'},
    )

    def _resolve_target(self, context):
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if _is_vdb_cloud_object(obj):
                return obj
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active else None
        if _is_vdb_cloud_object(active_obj):
            return active_obj
        return None

    def invoke(self, context, event):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a VDB cloud object first.")
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = self._resolve_target(context)
        if obj is None:
            self.report({'ERROR'}, "Select a VDB cloud object first.")
            return {'CANCELLED'}

        data_block = getattr(obj, "data", None)
        materials = []
        if data_block is not None and hasattr(data_block, "materials"):
            materials = [mat for mat in data_block.materials if mat]

        obj_type = str(getattr(obj, "type", ""))
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            self.report({'ERROR'}, f"Failed deleting cloud: {exc}")
            return {'CANCELLED'}

        if data_block is not None and int(getattr(data_block, "users", 0)) == 0:
            try:
                if obj_type == "VOLUME" and hasattr(bpy.data, "volumes"):
                    bpy.data.volumes.remove(data_block)
                elif obj_type == "MESH" and hasattr(bpy.data, "meshes"):
                    bpy.data.meshes.remove(data_block)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed removing VDB data block", exc_info=True)

        for mat in materials:
            if mat is not None and int(getattr(mat, "users", 0)) == 0:
                try:
                    bpy.data.materials.remove(mat)
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    logger.debug("Planetka clouds: failed removing VDB material", exc_info=True)

        self.report({'INFO'}, "VDB cloud deleted")
        return {'FINISHED'}


class PLANETKA_PT_LocalCloudsPanel(bpy.types.Panel):
    bl_label = "Texture-Based Clouds"
    bl_idname = "PLANETKA_PT_local_clouds"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 9007

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.use_property_split = False
        row.prop(
            props,
            "enable_local_clouds",
            text="Disable Texture-Based Clouds" if bool(getattr(props, "enable_local_clouds", False)) else "Enable Texture-Based Clouds",
            toggle=True,
            invert_checkbox=True,
        )

        if not bool(getattr(props, "enable_local_clouds", False)):
            return

        items = _ensure_local_cloud_previews()

        box = layout.box()
        box.label(text="Texture Picker", icon="IMAGE_DATA")
        if not items:
            box.label(text="No texture-based cloud textures available.", icon="ERROR")
            cache_dir = _local_clouds_dir()
            if cache_dir:
                box.label(text=cache_dir, icon="FILE_FOLDER")
        else:
            box.template_icon_view(props, "local_cloud_texture", show_labels=True, scale=6.0, scale_popup=6.0)

        row = box.row()
        row.use_property_split = False
        row.operator("planetka.add_local_cloud", text="Add Cloud", icon="ADD")

        clouds = _sort_cloud_objects_by_suffix(list(_iter_local_cloud_objects()))
        if not clouds:
            info = layout.box()
            info.label(text="No texture-based clouds added yet.", icon="INFO")
            return

        for idx, cloud_obj in enumerate(clouds, start=1):
            panel_body = layout.box()
            panel_body.label(text=_cloud_title(cloud_obj.name, idx, "Cloud No"), icon="FORCE_WIND")

            vis_row = panel_body.row()
            vis_row.use_property_split = False
            vis_row.prop(
                cloud_obj,
                "hide_viewport",
                text="Show in Viewport" if bool(getattr(cloud_obj, "hide_viewport", False)) else "Hide in Viewport",
                toggle=True,
                icon="HIDE_OFF",
            )

            panel_body.label(text=_local_cloud_file_label(cloud_obj), icon="IMAGE_DATA")

            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_SIZE_COEF, text="Size Coefficient")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_LATITUDE, text="Latitude")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_LONGITUDE, text="Longitude")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_ROTATION_DEG, text="Rotation (deg)")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_ALTITUDE_M, text="Altitude (m)")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_CLOUD_COLOR, text="Cloud Color")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_DENSITY, text="Density")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_DENSITY_GAMMA, text="Density Gamma")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_CONTRAST, text="Contrast")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_HORIZON_TRANSPARENCY, text="Horizon Transparency")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_SUBSURFACE_SCALE, text="Subsurface Scale")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_IOR, text="IOR")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_ROUGHNESS, text="Roughness")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_ANISOTROPY, text="Anisotropy")
            panel_body.prop(cloud_obj, LOCAL_CLOUD_PROP_DISPLACEMENT_SCALE, text="Displacement Scale")

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.reset_local_cloud_to_camera_view", text="Reset Cloud Position", icon="TRACKING")
            op.object_name = cloud_obj.name

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.delete_local_cloud", text="Delete Cloud", icon="TRASH")
            op.object_name = cloud_obj.name


class PLANETKA_PT_VDBCloudsPanel(bpy.types.Panel):
    bl_label = "VDB Clouds (Cycles only)"
    bl_idname = "PLANETKA_PT_vdb_clouds"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Planetka"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 9008

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        layout = self.layout
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene else None
        if props is None:
            layout.label(text="Planetka settings unavailable.", icon="ERROR")
            return

        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.use_property_split = False
        row.prop(
            props,
            "enable_vdb_clouds",
            text="Disable VDB Clouds (Cycles only)" if bool(getattr(props, "enable_vdb_clouds", False)) else "Enable VDB Clouds (Cycles only)",
            toggle=True,
            invert_checkbox=True,
        )

        if not bool(getattr(props, "enable_vdb_clouds", False)):
            return

        box = layout.box()
        box.label(text="VDB File", icon="VOLUME_DATA")
        box.prop(props, "vdb_cloud_file", text="")
        box.label(text=f"Default folder: {_vdb_clouds_dir()}", icon="FILE_FOLDER")

        row = box.row()
        row.use_property_split = False
        row.operator("planetka.add_vdb_cloud", text="Add VDB Cloud", icon="ADD")

        clouds = _sort_cloud_objects_by_suffix(list(_iter_vdb_cloud_objects()))
        if not clouds:
            info = layout.box()
            info.label(text="No VDB clouds added yet.", icon="INFO")
            return

        for idx, cloud_obj in enumerate(clouds, start=1):
            panel_body = layout.box()
            panel_body.label(text=_cloud_title(cloud_obj.name, idx, "VDB Cloud No"), icon="VOLUME_DATA")

            vis_row = panel_body.row()
            vis_row.use_property_split = False
            vis_row.prop(
                cloud_obj,
                "hide_viewport",
                text="Show in Viewport" if bool(getattr(cloud_obj, "hide_viewport", False)) else "Hide in Viewport",
                toggle=True,
                icon="HIDE_OFF",
            )

            panel_body.label(text=_vdb_file_label(cloud_obj), icon="FILE")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_SIZE_COEF, text="Size Coefficient")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_LATITUDE, text="Latitude")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_LONGITUDE, text="Longitude")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_ROTATION_DEG, text="Rotation (deg)")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_ALTITUDE_M, text="Altitude (m)")
            panel_body.prop(cloud_obj, VDB_CLOUD_PROP_DENSITY, text="Density")

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.reset_vdb_cloud_to_camera_view", text="Reset Cloud Position", icon="TRACKING")
            op.object_name = cloud_obj.name

            row = panel_body.row()
            row.use_property_split = False
            op = row.operator("planetka.delete_vdb_cloud", text="Delete Cloud", icon="TRASH")
            op.object_name = cloud_obj.name


def register_object_properties():
    object_props = bpy.types.Object

    if not hasattr(object_props, LOCAL_CLOUD_OBJ_TEXTURE_PROP):
        setattr(
            object_props,
            LOCAL_CLOUD_OBJ_TEXTURE_PROP,
            EnumProperty(
                name="Texture-Based Cloud Texture",
                description="Select a texture-based cloud texture",
                items=_local_cloud_texture_items,
                update=update_local_cloud_object_texture,
            ),
        )

    if not hasattr(object_props, LOCAL_CLOUD_PROP_CLOUD_COLOR):
        setattr(
            object_props,
            LOCAL_CLOUD_PROP_CLOUD_COLOR,
            FloatVectorProperty(
                name="Texture-Based Cloud Color",
                description="Cloud scattering color",
                subtype='COLOR',
                size=4,
                min=0.0,
                max=1.0,
                default=(1.0, 1.0, 1.0, 1.0),
                update=update_local_cloud_object_prop,
            ),
        )

    for name, kwargs in (
        (
            LOCAL_CLOUD_PROP_LONGITUDE,
            dict(name="Texture-Based Cloud Longitude", default=0.0, min=-360.0, max=360.0, precision=3, step=0.1, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_LATITUDE,
            dict(name="Texture-Based Cloud Latitude", default=0.0, min=-90.0, max=90.0, precision=3, step=0.1, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_ALTITUDE_M,
            dict(name="Texture-Based Cloud Altitude (m)", default=5000.0, min=-100000.0, max=200000000.0, precision=2, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_SIZE_COEF,
            dict(name="Texture-Based Cloud Size Coef", default=1.0, min=1e-6, precision=3, update=update_local_cloud_object_size),
        ),
        (
            LOCAL_CLOUD_PROP_ROTATION_DEG,
            dict(name="Texture-Based Cloud Rotation (deg)", default=0.0, min=-360.0, max=360.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_THICKNESS_M,
            dict(name="Texture-Based Cloud Thickness (m)", default=50.0, min=0.0, max=1000000.0, precision=2, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_DENSITY,
            dict(name="Texture-Based Cloud Density", default=1.2, min=0.0, max=1000.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_DENSITY_GAMMA,
            dict(name="Texture-Based Cloud Density Gamma", default=1.0, min=0.0, max=1000.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_CONTRAST,
            dict(name="Texture-Based Cloud Contrast", default=0.5, min=-100.0, max=100.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_HORIZON_TRANSPARENCY,
            dict(name="Texture-Based Cloud Horizon Transparency", default=1.0, min=0.0, max=100.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_SUBSURFACE_SCALE,
            dict(name="Texture-Based Cloud Subsurface Scale", default=1.0, min=0.0, max=1000.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_IOR,
            dict(name="Texture-Based Cloud IOR", default=1.33, min=1.0, max=4.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_ROUGHNESS,
            dict(name="Texture-Based Cloud Roughness", default=0.8, min=0.0, max=1.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_ANISOTROPY,
            dict(name="Texture-Based Cloud Anisotropy", default=float(LOCAL_CLOUD_ANISOTROPY_DEFAULT), min=-1.0, max=1.0, precision=3, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_DISPLACEMENT_SCALE,
            dict(name="Texture-Based Cloud Displacement Scale", default=float(LOCAL_CLOUD_DISPLACEMENT_SCALE_DEFAULT), min=0.0, max=1000.0, precision=4, update=update_local_cloud_object_prop),
        ),
        (
            LOCAL_CLOUD_PROP_BASE_SCALE,
            dict(name="Texture-Based Cloud Base Scale", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG,
            dict(name="Texture-Based Cloud Cap Half Angle", default=-1.0, min=-1.0, max=180.0, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_LONGITUDE,
            dict(name="VDB Cloud Longitude", default=0.0, min=-360.0, max=360.0, precision=3, step=0.1, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_LATITUDE,
            dict(name="VDB Cloud Latitude", default=0.0, min=-90.0, max=90.0, precision=3, step=0.1, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_ALTITUDE_M,
            dict(name="VDB Cloud Altitude (m)", default=float(DEFAULT_CLOUD_ALTITUDE_M), min=-100000.0, max=200000000.0, precision=2, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_SIZE_COEF,
            dict(name="VDB Cloud Size Coef", default=1.0, min=1e-6, precision=3, update=update_vdb_cloud_object_size),
        ),
        (
            VDB_CLOUD_PROP_ROTATION_DEG,
            dict(name="VDB Cloud Rotation", default=0.0, min=-360.0, max=360.0, precision=3, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_DENSITY,
            dict(name="VDB Cloud Density", default=float(DEFAULT_VDB_CLOUD_DENSITY), min=0.0, max=1000.0, precision=3, update=update_vdb_cloud_object_prop),
        ),
        (
            VDB_CLOUD_PROP_BASE_SCALE_X,
            dict(name="VDB Cloud Base Scale X", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_BASE_SCALE_Y,
            dict(name="VDB Cloud Base Scale Y", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_BASE_SCALE_Z,
            dict(name="VDB Cloud Base Scale Z", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_PROP_BASE_RADIUS,
            dict(name="VDB Cloud Base Radius", default=1.0, min=1e-6, options={'HIDDEN'}),
        ),
        (
            VDB_CLOUD_OBJ_FILE_PROP,
            dict(name="VDB Cloud File", default="", subtype='FILE_PATH', update=update_vdb_cloud_object_prop),
        ),
    ):
        if hasattr(object_props, name):
            continue
        prop_factory = FloatProperty
        if name in {VDB_CLOUD_OBJ_FILE_PROP}:
            prop_factory = StringProperty
        kwargs = dict(kwargs)
        setattr(object_props, name, prop_factory(**kwargs))


def unregister_object_properties():
    object_props = bpy.types.Object
    names = (
        LOCAL_CLOUD_OBJ_TEXTURE_PROP,
        LOCAL_CLOUD_PROP_LONGITUDE,
        LOCAL_CLOUD_PROP_LATITUDE,
        LOCAL_CLOUD_PROP_ALTITUDE_M,
        LOCAL_CLOUD_PROP_SIZE_COEF,
        LOCAL_CLOUD_PROP_ROTATION_DEG,
        LOCAL_CLOUD_PROP_THICKNESS_M,
        LOCAL_CLOUD_PROP_CLOUD_COLOR,
        LOCAL_CLOUD_PROP_DENSITY,
        LOCAL_CLOUD_PROP_DENSITY_GAMMA,
        LOCAL_CLOUD_PROP_CONTRAST,
        LOCAL_CLOUD_PROP_HORIZON_TRANSPARENCY,
        LOCAL_CLOUD_PROP_SUBSURFACE_SCALE,
        LOCAL_CLOUD_PROP_IOR,
        LOCAL_CLOUD_PROP_ROUGHNESS,
        LOCAL_CLOUD_PROP_ANISOTROPY,
        LOCAL_CLOUD_PROP_DISPLACEMENT_SCALE,
        LOCAL_CLOUD_PROP_BASE_SCALE,
        LOCAL_CLOUD_PROP_CAP_HALF_ANGLE_DEG,
        VDB_CLOUD_PROP_LONGITUDE,
        VDB_CLOUD_PROP_LATITUDE,
        VDB_CLOUD_PROP_ALTITUDE_M,
        VDB_CLOUD_PROP_SIZE_COEF,
        VDB_CLOUD_PROP_ROTATION_DEG,
        VDB_CLOUD_PROP_DENSITY,
        VDB_CLOUD_PROP_BASE_SCALE_X,
        VDB_CLOUD_PROP_BASE_SCALE_Y,
        VDB_CLOUD_PROP_BASE_SCALE_Z,
        VDB_CLOUD_PROP_BASE_RADIUS,
        VDB_CLOUD_OBJ_FILE_PROP,
    )
    for name in names:
        if hasattr(object_props, name):
            try:
                delattr(object_props, name)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka clouds: failed unregistering object property %s", name, exc_info=True)

    _free_local_cloud_previews()
    _free_vdb_cloud_previews()
