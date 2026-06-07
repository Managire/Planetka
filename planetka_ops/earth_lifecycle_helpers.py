import math

import bpy

from ..auth import (
    AuthApiError,
    describe_cloud_session_error,
    get_cloud_connection_status,
    ensure_authenticated_session,
    is_authenticated,
)
from ..asset_builder import PLANETKA_ROOT_OBJECT_NAME, ensure_earth_surface_parent, ensure_planetka_root
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import mark_earth_object
from ..operator_utils import ErrorCode, fail
from ..r2_source import is_remote_source_configured
from ..sanity_utils import _normalize_texture_source_path, validate_known_good_texture_source
from ..state import (
    delete_temp_meshes,
    ensure_planetka_temp_collection,
    logger,
    remove_object_and_unused_mesh,
)

_DEFAULT_SCENE_REMOVED_KEY = "planetka_default_scene_removed"
_PLANETKA_CREATE_CAMERA_NAME = "Planetka Camera"
_PLANETKA_RUNTIME_NAME_PREFIX = "Planetka"
_PLANETKA_STANDALONE_NAME_PREFIX = "PlanetkaStandalone"
_SURFACE_COLLECTION_NAME = "Planetka - Earth Surface Collection"


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


def _require_planetka_cloud_session(operator, prefs):
    if not is_authenticated(prefs):
        try:
            ensure_authenticated_session(prefs)
        except AuthApiError as exc:
            fail(
                operator,
                describe_cloud_session_error(exc),
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
            )
            return False
        except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
            fail(
                operator,
                "Planetka session could not be started. Check your connection and try again.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
                exc=exc,
            )
            return False
    status = get_cloud_connection_status(prefs=prefs, force=True, timeout=4.0)
    if not bool(status.get("online", False)):
        message = str(status.get("message", "") or "").strip()
        fail(
            operator,
            message or "Planetka Cloud is not reachable. Check your internet connection or try again later.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )
        return False
    return True


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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        active_obj = None
    if active_obj is not None and getattr(active_obj, "type", None) == 'CAMERA':
        try:
            if active_obj in tuple(getattr(scene, "objects", ())):
                scene.camera = active_obj
                return active_obj
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass

    for obj in tuple(getattr(scene, "objects", ())):
        if getattr(obj, "type", None) == 'CAMERA':
            try:
                scene.camera = obj
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False


def detach_planetka_camera_from_root(scene=None):
    """Detach Planetka Camera while preserving its world transform.

    Earth Location/Rotation are edits to Planetka Root. Planetka Camera must not
    inherit those transforms, otherwise moving/rotating Earth also moves the
    rendered camera.
    """
    try:
        view_layer = getattr(getattr(bpy, "context", None), "view_layer", None)
        if view_layer is not None:
            view_layer.update()
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed updating view layer before camera detachment", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed updating view layer before camera detachment", exc_info=True)

    cameras = []
    named = bpy.data.objects.get(_PLANETKA_CREATE_CAMERA_NAME)
    if _is_planetka_create_camera(named):
        cameras.append(named)
    if scene is not None:
        try:
            for obj in tuple(getattr(scene, "objects", ())):
                if _is_planetka_create_camera(obj) and obj not in cameras:
                    cameras.append(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed scanning scene cameras for root detachment", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed scanning scene cameras for root detachment", exc_info=True)

    changed = 0
    for camera_obj in cameras:
        if getattr(camera_obj, "parent", None) is None:
            continue
        try:
            world_matrix = camera_obj.matrix_world.copy()
            camera_obj.parent = None
            camera_obj.matrix_parent_inverse.identity()
            camera_obj.matrix_world = world_matrix
            changed += 1
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed detaching Planetka Camera from parent", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed detaching Planetka Camera from parent", exc_info=True)
    return int(changed)


def _ensure_planetka_camera_in_surface_collection(scene, camera_obj):
    if scene is None or camera_obj is None:
        return False
    if str(getattr(camera_obj, "type", "")) != "CAMERA":
        return False

    scene_root_collection = getattr(scene, "collection", None)
    if scene_root_collection is None:
        return False

    try:
        surface_collection = bpy.data.collections.get(_SURFACE_COLLECTION_NAME)
        if surface_collection is None:
            surface_collection = bpy.data.collections.new(_SURFACE_COLLECTION_NAME)
        if _SURFACE_COLLECTION_NAME not in scene_root_collection.children:
            scene_root_collection.children.link(surface_collection)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed ensuring surface collection for Planetka Camera", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed ensuring surface collection for Planetka Camera", exc_info=True)
        return False

    for collection in tuple(getattr(camera_obj, "users_collection", ()) or ()):
        if collection == surface_collection:
            continue
        try:
            collection.objects.unlink(camera_obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed unlinking Planetka Camera from non-surface collection", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed unlinking Planetka Camera from non-surface collection", exc_info=True)

    try:
        if camera_obj.name not in surface_collection.objects:
            surface_collection.objects.link(camera_obj)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed linking Planetka Camera to surface collection", exc_info=True)
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed linking Planetka Camera to surface collection", exc_info=True)
        return False

    return True


def _ensure_planetka_create_camera(scene):
    if scene is None:
        return None

    surface_collection = None
    scene_root_collection = getattr(scene, "collection", None)
    if scene_root_collection is not None:
        try:
            surface_collection = bpy.data.collections.get(_SURFACE_COLLECTION_NAME)
            if surface_collection is None:
                surface_collection = bpy.data.collections.new(_SURFACE_COLLECTION_NAME)
            if _SURFACE_COLLECTION_NAME not in scene_root_collection.children:
                scene_root_collection.children.link(surface_collection)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed ensuring surface collection for Planetka Camera", exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed ensuring surface collection for Planetka Camera", exc_info=True)

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
        if surface_collection is not None:
            surface_collection.objects.link(camera_obj)
        elif scene_root_collection is not None:
            scene_root_collection.objects.link(camera_obj)

    if not _ensure_planetka_camera_in_surface_collection(scene, camera_obj) and camera_obj not in tuple(getattr(scene, "objects", ())):
        scene.collection.objects.link(camera_obj)

    try:
        camera_obj["planetka_role"] = "camera"
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        logger.debug("Planetka: failed tagging Planetka Camera role", exc_info=True)

    detach_planetka_camera_from_root(scene)

    return camera_obj


def _position_planetka_create_camera(scene, props, camera_obj, activate=False):
    if scene is None or props is None or camera_obj is None:
        return False
    if str(getattr(camera_obj, "type", "")) != "CAMERA":
        return False

    from .navigation_helpers import _apply_navigation_shot

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
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed activating Planetka Camera", exc_info=True)
        else:
            try:
                scene.camera = previous_camera
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    try:
        for key in tuple(obj.keys()):
            if str(key).startswith("planetka_"):
                return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
    return False


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


def _create_placeholder_surface_object(scene):
    placeholder_mesh = bpy.data.meshes.new("Planetka Earth Surface Placeholder Mesh")
    obj = bpy.data.objects.new("Planetka Earth Surface", placeholder_mesh)
    scene.collection.objects.link(obj)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj["planetka_surface_local_radius"] = 2.0
    planetka_surface = bpy.data.materials.get("Planetka Earth Material")
    if planetka_surface is not None:
        try:
            obj.data.materials.clear()
            obj.data.materials.append(planetka_surface)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed assigning Earth material to bootstrap surface", exc_info=True)
    return obj


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


def _scene_allows_automatic_clipping(scene):
    if scene is None:
        return False
    allowed_default_names = {"Cube", "Camera", "Light"}
    try:
        scene_objects = tuple(getattr(scene, "objects", ()))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
    try:
        safe_radius = max(1e-9, float(earth_radius_bu))
    except (TypeError, ValueError):
        safe_radius = 1.0
    exponent = math.floor(math.log10(safe_radius))
    scale = math.pow(10.0, exponent)
    clip_start = 0.001 * scale
    clip_end = 1000.0 * scale
    return float(clip_start), float(clip_end)


def _float_close(value, target, tol=1e-4):
    try:
        return abs(float(value) - float(target)) <= float(tol)
    except (TypeError, ValueError):
        return False


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
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            pass

    wm = getattr(bpy.context, "window_manager", None)
    if wm is not None:
        for window in tuple(getattr(wm, "windows", ())):
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in tuple(getattr(screen, "areas", ())):
                if getattr(area, "type", "") != "VIEW_3D":
                    continue
                for space in tuple(getattr(area, "spaces", ())):
                    if getattr(space, "type", "") != "VIEW_3D":
                        continue
                    try:
                        old_start = float(getattr(space, "clip_start", 0.0))
                        old_end = float(getattr(space, "clip_end", 0.0))
                        if (not _float_close(old_start, new_start, tol=1e-9)) or (not _float_close(old_end, new_end, tol=1e-9)):
                            space.clip_start = float(new_start)
                            space.clip_end = float(new_end)
                            changed = True
                    except PLANETKA_RECOVERABLE_EXCEPTIONS:
                        continue

    if changed and notice_text:
        try:
            scene["planetka_status_clip_auto_notice"] = str(notice_text)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
    try:
        if scene is not None and "planetka_status_clip_auto_notice" in scene:
            del scene["planetka_status_clip_auto_notice"]
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
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
                except PLANETKA_RECOVERABLE_EXCEPTIONS:
                    continue
    return switched


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
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        selected_names = []
    try:
        active_obj = getattr(view_layer.objects, "active", None)
        active_name = str(getattr(active_obj, "name", "") or "")
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        active_name = ""
    return tuple(selected_names), active_name


def _restore_view_selection(context, scene, selected_names, active_name):
    view_layer = getattr(context, "view_layer", None) if context is not None else None
    if view_layer is None:
        return

    try:
        for obj in tuple(getattr(context, "selected_objects", ())):
            try:
                obj.select_set(False)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                continue
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass

    selected_objs = []
    for name in tuple(selected_names or ()):
        obj = None
        try:
            obj = getattr(scene, "objects", None).get(name) if scene is not None and getattr(scene, "objects", None) is not None else None
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            obj = None
        if obj is None:
            obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            obj.select_set(True)
            selected_objs.append(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue

    active_obj = None
    if active_name:
        try:
            active_obj = getattr(scene, "objects", None).get(active_name) if scene is not None and getattr(scene, "objects", None) is not None else None
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            active_obj = None
        if active_obj is None:
            active_obj = bpy.data.objects.get(active_name)
    if active_obj is None and selected_objs:
        active_obj = selected_objs[0]

    try:
        view_layer.objects.active = active_obj
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass
