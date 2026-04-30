import logging
import os

import bpy

from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


logger = logging.getLogger(__name__)

RECOVERY_FALLBACK_FILES_BY_TYPE = {
    "S2": "ocean_pixel_final_20.exr",
    "EL": "black_pixel_20.exr",
    "WT": "blue_pixel_20.exr",
    "PO": "black_pixel_20.exr",
}


def _infer_planetka_image_type(image):
    candidates = []
    if image is not None:
        candidates.append(str(getattr(image, "name", "") or ""))
        raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "")
        if raw_path:
            candidates.append(os.path.basename(raw_path))
    for candidate in candidates:
        prefix = str(candidate).strip().split("_", 1)[0].upper()
        if prefix in {"S2", "EL", "WT", "PO"}:
            return prefix
    return ""


def _fallback_image_path_for_type(image_type, fallback_files_by_type=RECOVERY_FALLBACK_FILES_BY_TYPE):
    kind = str(image_type or "").strip().upper()
    file_name = fallback_files_by_type.get(kind, "")
    if not file_name:
        return ""
    extension_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fallback_path = os.path.join(extension_dir, "Resources", "Fallback Images", file_name)
    if not os.path.isfile(fallback_path):
        return ""
    return fallback_path


def _normalized_abs_fs_path(path_value):
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    try:
        absolute = bpy.path.abspath(raw)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        absolute = raw
    if not absolute:
        return ""
    try:
        normalized = os.path.normcase(os.path.abspath(str(absolute)))
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        return ""
    return str(normalized)


def _path_is_within_root(path_value, root_value):
    path_norm = _normalized_abs_fs_path(path_value)
    root_norm = _normalized_abs_fs_path(root_value)
    if not path_norm or not root_norm:
        return False
    try:
        return os.path.commonpath((path_norm, root_norm)) == root_norm
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        return False


def _planetka_cache_roots(get_r2_source):
    roots = set()
    r2_source = get_r2_source() if callable(get_r2_source) else None
    if r2_source is not None:
        get_cache_folder = getattr(r2_source, "get_remote_cache_folder", None)
        if callable(get_cache_folder):
            try:
                root = _normalized_abs_fs_path(get_cache_folder(""))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                root = ""
            if root:
                roots.add(root)
    return tuple(sorted(roots))


def _is_planetka_cache_path(path_value, get_r2_source):
    path_norm = _normalized_abs_fs_path(path_value)
    if not path_norm:
        return False
    for cache_root in _planetka_cache_roots(get_r2_source):
        if _path_is_within_root(path_norm, cache_root):
            return True
    return "/planetka_cache/" in str(path_norm).replace("\\", "/").lower()


def _is_missing_planetka_cache_image(image, get_r2_source):
    if image is None:
        return False
    if getattr(image, "packed_file", None) is not None:
        return False
    raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
    if not raw_path:
        return False
    try:
        abs_path = bpy.path.abspath(raw_path)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
    if not abs_path:
        return False
    if not _is_planetka_cache_path(abs_path, get_r2_source):
        return False
    return not os.path.isfile(abs_path)


def _cache_request_from_missing_image(image, get_r2_source):
    if image is None:
        return None
    raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
    if not raw_path:
        return None
    abs_path = _normalized_abs_fs_path(raw_path)
    if not abs_path or not _is_planetka_cache_path(abs_path, get_r2_source):
        return None
    file_name = os.path.basename(abs_path)
    stem, ext = os.path.splitext(file_name)
    if not stem or not ext:
        return None

    prefix, sep, suffix = stem.partition("_")
    prefix = str(prefix or "").strip().upper()
    suffix = str(suffix or "").strip()
    if not sep or not prefix or not suffix:
        return None
    if prefix not in {"S2", "EL", "WT", "PO"}:
        inferred = _infer_planetka_image_type(image)
        inferred = str(inferred or "").strip().upper()
        if inferred in {"S2", "EL", "WT", "PO"} and stem.upper().startswith(f"{inferred}_"):
            prefix = inferred
            suffix = stem[len(inferred) + 1 :]
        else:
            return None

    folder = os.path.basename(os.path.dirname(abs_path)).strip().upper()
    if folder not in {"S2", "EL", "WT", "PO"}:
        folder = prefix
    if folder != prefix:
        folder = prefix

    return (folder, prefix, suffix, ext)


def _rebind_image_to_file(image, file_path):
    target = _normalized_abs_fs_path(file_path)
    if image is None or not target or not os.path.isfile(target):
        return False
    try:
        image.source = "FILE"
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed switching image source to FILE during render self-heal", exc_info=True)
    try:
        image.filepath_raw = target
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed assigning filepath_raw during render self-heal", exc_info=True)
    try:
        image.filepath = target
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed assigning filepath during render self-heal", exc_info=True)
    try:
        image.reload()
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed reloading image during render self-heal", exc_info=True)
        return False


def _attempt_render_self_heal_for_image(image, base_path, request_cache, get_r2_source):
    request = _cache_request_from_missing_image(image, get_r2_source)
    if request is None:
        return False
    folder, prefix, suffix, ext = request
    cache_key = (str(base_path or ""), folder, prefix, suffix, ext.lower())

    healed_path = str(request_cache.get(cache_key, "") or "").strip()
    if not healed_path:
        r2_source = get_r2_source() if callable(get_r2_source) else None
        if r2_source is None:
            return False
        resolve_texture_file = getattr(r2_source, "resolve_texture_file", None)
        resolve_remote_asset = getattr(r2_source, "resolve_remote_asset", None)
        if callable(resolve_texture_file):
            try:
                healed_path = str(
                    resolve_texture_file(
                        base_path,
                        folder,
                        prefix,
                        suffix,
                        (ext,),
                    )
                    or ""
                ).strip()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: resolve_texture_file failed during render self-heal", exc_info=True)
                healed_path = ""
        if not healed_path and callable(resolve_remote_asset):
            try:
                healed_path = str(
                    resolve_remote_asset(folder, f"{prefix}_{suffix}{ext}") or ""
                ).strip()
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: resolve_remote_asset failed during render self-heal", exc_info=True)
                healed_path = ""
        request_cache[cache_key] = healed_path

    if not healed_path:
        return False
    return bool(_rebind_image_to_file(image, healed_path))


def self_heal_missing_cache_images_for_render(scene=None, *, get_prefs, get_r2_source):
    _ = scene
    missing_count = 0
    healed_count = 0
    failed_count = 0
    request_cache = {}

    prefs = get_prefs() if callable(get_prefs) else None
    base_path = str(getattr(prefs, "texture_base_path", "") or "").strip() if prefs is not None else ""

    for image in list(getattr(bpy.data, "images", ())):
        if not _is_missing_planetka_cache_image(image, get_r2_source):
            continue
        missing_count += 1
        if _attempt_render_self_heal_for_image(image, base_path, request_cache, get_r2_source):
            healed_count += 1
        else:
            failed_count += 1

    if healed_count > 0:
        logger.warning(
            "Planetka: render self-heal restored %d/%d missing cached tile image(s)%s.",
            int(healed_count),
            int(missing_count),
            f" ({int(failed_count)} failed)" if int(failed_count) > 0 else "",
        )
    elif missing_count > 0:
        logger.warning(
            "Planetka: render self-heal detected %d missing cached tile image(s), none restored.",
            int(missing_count),
        )
    return int(missing_count), int(healed_count), int(failed_count)


def recover_missing_cache_image_paths_to_fallback(get_r2_source):
    missing_count = 0
    recovered_count = 0
    for image in list(getattr(bpy.data, "images", ())):
        if not _is_missing_planetka_cache_image(image, get_r2_source):
            continue
        missing_count += 1
        image_type = _infer_planetka_image_type(image)
        fallback_path = _fallback_image_path_for_type(image_type)
        if not fallback_path:
            continue
        try:
            image.source = "FILE"
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed switching image source to FILE during load recovery", exc_info=True)
        try:
            image.filepath_raw = fallback_path
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed assigning fallback filepath_raw during load recovery", exc_info=True)
        try:
            image.filepath = fallback_path
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed assigning fallback filepath during load recovery", exc_info=True)
        try:
            image.reload()
            recovered_count += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed reloading fallback image during load recovery", exc_info=True)
    return int(missing_count), int(recovered_count)


def queue_manual_resolve_download_for_scene(scene, *, get_earth_object, is_render_job_active=None):
    if scene is None:
        return False
    props = getattr(scene, "planetka", None)
    if props is None:
        return False
    if get_earth_object() is None:
        return False
    try:
        if callable(is_render_job_active) and bool(is_render_job_active()):
            logger.info("Planetka: skipping load-time queued recovery resolve during active final animation render.")
            return False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed checking final animation render state for load-time recovery queue", exc_info=True)
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
        if wm is not None and bool(getattr(wm, "is_interface_locked", False)):
            logger.debug("Planetka: delaying load-time recovery queue while interface is locked.")
            return False
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed checking interface lock state for load-time recovery queue", exc_info=True)

    wm = getattr(getattr(bpy, "context", None), "window_manager", None)
    windows = list(getattr(wm, "windows", ()) or ())
    if not windows:
        return False
    window = windows[0]
    override = None
    try:
        override = bpy.context.copy()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        override = {}
    if override is None:
        override = {}
    override["window"] = window
    override["screen"] = getattr(window, "screen", None)
    override["scene"] = scene
    override["view_layer"] = scene.view_layers[0] if getattr(scene, "view_layers", None) else None

    try:
        with bpy.context.temp_override(**override):
            try:
                result = bpy.ops.planetka.load_textures(
                    'EXEC_DEFAULT',
                    scope_mode='CAMERA',
                    skip_render_compatibility=True,
                    defer_download=True,
                )
            except TypeError:
                result = bpy.ops.planetka.load_textures(
                    scope_mode='CAMERA',
                    skip_render_compatibility=True,
                    defer_download=True,
                )
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed queueing load-time recovery resolve", exc_info=True)
        return False
    return bool("FINISHED" in result or "RUNNING_MODAL" in result)


def schedule_load_recovery_resolve(scene, *, queue_manual_resolve_download_for_scene):
    target_scene_name = str(getattr(scene, "name", "") or "").strip()
    if not target_scene_name:
        return
    attempts_remaining = {"count": 25}

    def _attempt_recovery():
        scene_ref = bpy.data.scenes.get(target_scene_name)
        if scene_ref is None:
            return None
        if queue_manual_resolve_download_for_scene(scene_ref):
            logger.info("Planetka: queued recovery resolve after opening scene '%s'.", target_scene_name)
            return None
        attempts_remaining["count"] = int(attempts_remaining.get("count", 0)) - 1
        if attempts_remaining["count"] <= 0:
            logger.warning("Planetka: could not queue recovery resolve for scene '%s'.", target_scene_name)
            return None
        return 0.25

    try:
        bpy.app.timers.register(_attempt_recovery, first_interval=0.15, persistent=False)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed scheduling load-time recovery resolve", exc_info=True)
