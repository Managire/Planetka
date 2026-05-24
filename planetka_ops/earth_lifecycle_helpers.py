import math

import bpy

from ..auth import (
    AuthApiError,
    describe_auth_error,
    get_cloud_connection_status,
    ensure_authenticated_session,
    is_authenticated,
    recover_from_terminal_auth_error,
    sync_account_profile,
)
from ..asset_builder import PLANETKA_ROOT_OBJECT_NAME, ensure_earth_surface_parent, ensure_planetka_root
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import mark_earth_object
from ..operator_utils import ErrorCode, fail
from ..r2_source import is_remote_source_configured
from ..sanity_utils import _normalize_texture_source_path, validate_known_good_texture_source
from ..state import (
    _sync_idprops_from_props,
    cleanup_planetka_unused_data,
    delete_temp_meshes,
    ensure_planetka_temp_collection,
    logger,
    remove_object_and_unused_mesh,
)
from .startup_profile_ops import (
    _SKIP_CAMERA_CHANGES_ON_CREATE_EARTH_KEY,
    _apply_surface_grading_values,
    _serialize_surface_grading_values,
)

_DEFAULT_SCENE_REMOVED_KEY = "planetka_default_scene_removed"
_PLANETKA_CREATE_CAMERA_NAME = "Planetka Camera"
_PLANETKA_RUNTIME_NAME_PREFIX = "Planetka"
_PLANETKA_STANDALONE_NAME_PREFIX = "PlanetkaStandalone"
_SURFACE_COLLECTION_NAME = "Planetka - Earth Surface Collection"
_REBUILD_EXCEPTIONS = (
    PLANETKA_RECOVERABLE_EXCEPTIONS,
    RuntimeError,
    TypeError,
    ValueError,
    AttributeError,
)


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


def _require_authenticated_account(operator, prefs):
    if not is_authenticated(prefs):
        try:
            ensure_authenticated_session(prefs)
        except AuthApiError as exc:
            fail(
                operator,
                describe_auth_error(exc),
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
    try:
        sync_account_profile(prefs)
    except AuthApiError as exc:
        recover_from_terminal_auth_error(exc, prefs=prefs, source="create_earth_account_profile")
        fail(
            operator,
            describe_auth_error(exc),
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )
        return False
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
        fail(
            operator,
            "Planetka account status could not be verified. Check your connection and try again.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
            exc=exc,
            log_message="Planetka Create Earth account verification failed",
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

    try:
        root = ensure_planetka_root(scene)
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        root = None
    if root is not None:
        try:
            world_matrix = camera_obj.matrix_world.copy()
            if getattr(camera_obj, "parent", None) is not root:
                camera_obj.parent = root
                camera_obj.matrix_parent_inverse = root.matrix_world.inverted()
                camera_obj.matrix_world = world_matrix
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed parenting Planetka Camera to Planetka Root", exc_info=True)

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

    if _is_planetka_create_camera(camera):
        if not _ensure_planetka_camera_in_surface_collection(scene, camera):
            return False
    else:
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
