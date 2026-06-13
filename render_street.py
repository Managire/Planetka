import ftplib
import importlib
import json
import os
import subprocess
import tempfile
import threading
import time

import bpy

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from .extension_prefs import get_prefs
from .operator_utils import fail
from .state import logger

RENDER_STREET_HOST = "eu3.render.st"
RENDER_STREET_PORT = 51225
RENDER_STREET_DEFAULT_FRAMES = 24
RENDER_STREET_DEFAULT_TIME_LIMIT_MINUTES = 14.0
RENDER_STREET_JOB_TIMEOUT_SECONDS = 180.0
RENDER_STREET_PREF_EXCEPTIONS = (*PLANETKA_RECOVERABLE_EXCEPTIONS, AttributeError, TypeError, ValueError)
RENDER_STREET_IMPORT_EXCEPTIONS = (*PLANETKA_RECOVERABLE_EXCEPTIONS, ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError)
RENDER_STREET_EXPORT_EXCEPTIONS = (*PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, OSError)
RENDER_STREET_JOB_EXCEPTIONS = (*PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError)


def _safe_scene_name():
    source_path = str(getattr(bpy.data, "filepath", "") or "").strip()
    if source_path:
        name = os.path.splitext(os.path.basename(source_path))[0]
    else:
        name = "PlanetkaScene"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(name or "PlanetkaScene"))
    return safe.strip("_") or "PlanetkaScene"


def _render_street_output_path():
    source_path = str(getattr(bpy.data, "filepath", "") or "").strip()
    if source_path:
        folder = os.path.dirname(os.path.abspath(source_path))
    else:
        folder = tempfile.gettempdir()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(folder, f"{_safe_scene_name()}_render_street_{stamp}.blend")


def _remote_upload_folder_name(output_path):
    stem = os.path.splitext(os.path.basename(str(output_path or "PlanetkaScene")))[0]
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)
    return safe.strip("_") or "PlanetkaScene"


def _read_credentials(scene, props):
    _ = scene
    prefs = get_prefs()
    save_login = bool(getattr(props, "render_street_save_login", False)) or (
        bool(getattr(prefs, "render_street_save_login", False)) if prefs is not None else False
    )
    typed_username = str(getattr(props, "render_street_username", "") or "").strip()
    typed_password = str(getattr(props, "render_street_password", "") or "")
    saved_username = str(getattr(prefs, "render_street_username", "") or "").strip() if prefs is not None else ""
    saved_password = str(getattr(prefs, "render_street_password", "") or "") if prefs is not None else ""
    username = typed_username or saved_username
    password = typed_password or saved_password
    return username, password, save_login, prefs


def _write_saved_credentials(prefs, username, password, save_login):
    if prefs is None:
        return
    try:
        prefs.render_street_save_login = bool(save_login)
        if bool(save_login):
            prefs.render_street_username = str(username or "")
            prefs.render_street_password = str(password or "")
        else:
            prefs.render_street_username = ""
            prefs.render_street_password = ""
    except RENDER_STREET_PREF_EXCEPTIONS:
        logger.debug("Planetka Render Street: failed saving login preferences", exc_info=True)
        return
    try:
        bpy.ops.wm.save_userpref()
    except RENDER_STREET_PREF_EXCEPTIONS:
        logger.debug("Planetka Render Street: failed persisting login preferences", exc_info=True)


def _resolve_renderstreet_api_module():
    candidate_packages = [
        "bl_ext.user_default.RenderStreet",
        "bl_ext.user_default.renderstreet",
        "RenderStreet",
        "renderstreet",
    ]
    try:
        addons = getattr(bpy.context.preferences, "addons", {})
        for addon_name in addons.keys():
            if "renderstreet" in str(addon_name).casefold():
                candidate_packages.append(str(addon_name))
    except RENDER_STREET_PREF_EXCEPTIONS:
        pass

    last_error = None
    for package_name in dict.fromkeys(candidate_packages):
        try:
            try:
                import addon_utils
                _default, loaded = addon_utils.check(package_name)
                if not loaded:
                    addon_utils.enable(package_name, default_set=False, persistent=False)
            except RENDER_STREET_IMPORT_EXCEPTIONS:
                pass
            return importlib.import_module(f"{package_name}.l11l1l1l_KEW_")
        except RENDER_STREET_IMPORT_EXCEPTIONS as exc:
            last_error = exc
    raise RuntimeError(f"RenderStreet add-on API not available: {last_error}")


def _renderstreet_login_token(username, password):
    api_mod = _resolve_renderstreet_api_module()
    api = api_mod.l111l1ll_KEW_()
    response = api.l11l1lll_KEW_(username, password)
    if not isinstance(response, dict) or str(response.get("status", "")).casefold() != "success":
        message = response.get("message") if isinstance(response, dict) else ""
        raise RuntimeError(str(message or "RenderStreet login failed."))
    data = response.get("data", {})
    token = str(data.get("token", "") if isinstance(data, dict) else "").strip()
    if len(token) != 32:
        raise RuntimeError("RenderStreet login did not return a valid token.")
    return api_mod, api, token


def _create_renderstreet_job(username, password, remote_dir, remote_file, frames, scene=None, job_name=""):
    api_mod, api, token = _renderstreet_login_token(username, password)
    _ = api_mod
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        raise RuntimeError("No active scene for RenderStreet job settings.")
    try:
        frame_end = max(1, int(frames or RENDER_STREET_DEFAULT_FRAMES))
    except (TypeError, ValueError):
        frame_end = RENDER_STREET_DEFAULT_FRAMES
    render = getattr(scene, "render", None)
    image_settings = getattr(render, "image_settings", None) if render is not None else None
    output_format = str(getattr(image_settings, "file_format", "") or "PNG")
    resolution_percentage = int(getattr(render, "resolution_percentage", 100) or 100) if render is not None else 100
    blender_version = f"{bpy.app.version[0]}{bpy.app.version[1]}{bpy.app.version[2]}"
    job_label = str(job_name or os.path.splitext(os.path.basename(str(remote_file or "")))[0] or "Planetka Render Street").strip()
    waiter = threading.Event()
    result = {}

    def _success(payload):
        result["payload"] = payload
        waiter.set()

    def _error():
        result["error"] = True
        waiter.set()

    api.l111l111_KEW_(
        token,
        str(remote_dir or ""),
        str(remote_file or ""),
        1,
        frame_end,
        "CYCLES",
        blender_version,
        output_format,
        resolution_percentage,
        job_label,
        "CPU",
        "ONE",
        "0",
        callback=_success,
        err_callback=_error,
    )

    if not waiter.wait(timeout=RENDER_STREET_JOB_TIMEOUT_SECONDS):
        raise RuntimeError("RenderStreet job creation timed out.")
    if result.get("error"):
        raise RuntimeError("RenderStreet job creation failed.")
    payload = result.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("RenderStreet job creation returned an invalid response.")
    if str(payload.get("status", "")).casefold() == "error":
        raise RuntimeError(str(payload.get("message") or "RenderStreet job creation failed."))
    job_id = None
    try:
        data = payload.get("data", {})
        if isinstance(data, dict):
            job_id = int(data.get("JobId"))
    except (TypeError, ValueError):
        job_id = None
    return job_id, payload


def _standalone_render_street_script(frames, time_limit_minutes):
    frames = max(1, int(frames or RENDER_STREET_DEFAULT_FRAMES))
    seconds = max(0.0, float(time_limit_minutes or 0.0) * 60.0)
    return f"""
import bpy
import os
import json
import shutil
import sys
try:
    import addon_utils
except ImportError:
    addon_utils = None

FRAMES = {frames:d}
TIME_LIMIT_SECONDS = {seconds:.12g}


def _output_path():
    argv = sys.argv
    if '--' not in argv:
        return ''
    idx = argv.index('--')
    if idx + 1 >= len(argv):
        return ''
    return str(argv[idx + 1] or '').strip()


def _manifest_path(path):
    return f'{{path}}.planetka_render_street_files.json'


def _idprop_keys(id_block):
    try:
        return list(id_block.keys())
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return []


def _has_planetka_runtime_key(id_block):
    for key in _idprop_keys(id_block):
        if str(key).startswith('planetka_'):
            return True
    return False


def _strip_planetka_runtime_keys(id_block):
    for key in _idprop_keys(id_block):
        if str(key).startswith('planetka_'):
            try:
                del id_block[key]
            except (RuntimeError, TypeError, ValueError, AttributeError, KeyError):
                pass


def _standalone_name(name):
    text = str(name or '').strip()
    if not text:
        return 'PlanetkaStandalone'
    if text.startswith('PlanetkaStandalone'):
        return text
    if 'Planetka' in text:
        return text.replace('Planetka', 'PlanetkaStandalone', 1)
    return f'PlanetkaStandalone {{text}}'


def _rename_datablock(id_block, force_prefix=False):
    if id_block is None:
        return
    try:
        current_name = str(getattr(id_block, 'name', '') or '')
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return
    if not current_name:
        return
    if (not force_prefix) and ('Planetka' not in current_name):
        return
    new_name = _standalone_name(current_name)
    if new_name == current_name:
        return
    try:
        id_block.name = new_name
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass


def _rename_and_strip(id_collection, force_predicate=None):
    for datablock in list(id_collection):
        force_prefix = False
        try:
            force_prefix = bool(force_predicate(datablock)) if callable(force_predicate) else False
        except (RuntimeError, TypeError, ValueError, AttributeError):
            force_prefix = False
        if _has_planetka_runtime_key(datablock):
            force_prefix = True
        _rename_datablock(datablock, force_prefix=force_prefix)
        _strip_planetka_runtime_keys(datablock)


def _is_standalone_name(name):
    return str(name or '').strip().startswith('PlanetkaStandalone')


def _object_force_prefix(obj):
    try:
        role = str(obj.get('planetka_role', '') or '').strip()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        role = ''
    if role:
        return True
    name = str(getattr(obj, 'name', '') or '')
    if 'Planetka' in name:
        return True
    if name in {{'Planetka Atmosphere - Volumetric', 'Planetka Atmosphere - EEVEE Supplement'}}:
        return True
    return False


def _rename_object_bound_data():
    for obj in list(bpy.data.objects):
        obj_name = str(getattr(obj, 'name', '') or '')
        if not _is_standalone_name(obj_name):
            continue
        _rename_datablock(getattr(obj, 'data', None), force_prefix=True)
        for slot in tuple(getattr(obj, 'material_slots', ())):
            _rename_datablock(getattr(slot, 'material', None), force_prefix=True)


def _detach_planetka_identity():
    _rename_and_strip(bpy.data.objects, force_predicate=_object_force_prefix)
    _rename_object_bound_data()
    for attr_name in (
        'collections', 'meshes', 'materials', 'node_groups', 'images', 'cameras', 'lights',
        'worlds', 'textures', 'actions', 'curves', 'armatures', 'volumes',
    ):
        id_collection = getattr(bpy.data, attr_name, None)
        if id_collection is None:
            continue
        _rename_and_strip(id_collection)
    for scene in list(bpy.data.scenes):
        _strip_planetka_runtime_keys(scene)


def _set_sampling_pattern(cycles):
    for value in ('AUTOMATIC', 'AUTO', 'TABULATED_SOBOL'):
        try:
            cycles.sampling_pattern = value
            return
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass


def _prepare_render_street_settings():
    if addon_utils is not None:
        try:
            addon_utils.enable('cycles', default_set=False, persistent=False)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
    for scene in list(bpy.data.scenes):
        try:
            scene.frame_start = 1
            scene.frame_end = int(FRAMES)
            scene.frame_current = 1
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
        try:
            scene.render.engine = 'CYCLES'
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
        cycles = getattr(scene, 'cycles', None)
        if cycles is None:
            continue
        for attr, value in (
            ('device', 'CPU'),
            ('time_limit', float(TIME_LIMIT_SECONDS)),
            ('use_adaptive_sampling', False),
            ('adaptive_threshold', 0.0),
            ('use_denoising', False),
            ('seed', 8),
            ('use_animated_seed', True),
            ('volume_biased', False),
            ('tile_size', 10000),
        ):
            try:
                setattr(cycles, attr, value)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
        _set_sampling_pattern(cycles)


def _driver_depends_on_planetka(driver):
    try:
        variables = list(getattr(driver, 'variables', ()))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False
    for variable in variables:
        for target in list(getattr(variable, 'targets', ())):
            data_path = str(getattr(target, 'data_path', '') or '')
            if data_path.startswith('planetka') or '.planetka' in data_path:
                return True
    return False


def _resolved_property_value(id_block, data_path, array_index):
    try:
        resolved = id_block.path_resolve(data_path, False)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None
    try:
        if array_index >= 0 and hasattr(resolved, '__getitem__') and not isinstance(resolved, (str, bytes)):
            return resolved[int(array_index)]
    except (RuntimeError, TypeError, ValueError, AttributeError, IndexError):
        pass
    try:
        return float(resolved)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return resolved


def _assign_resolved_property_value(id_block, data_path, array_index, value):
    try:
        resolved = id_block.path_resolve(data_path, False)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False
    try:
        if array_index >= 0 and hasattr(resolved, '__setitem__') and not isinstance(resolved, (str, bytes)):
            resolved[int(array_index)] = value
            return True
    except (RuntimeError, TypeError, ValueError, AttributeError, IndexError):
        pass
    try:
        owner_path, prop_name = data_path.rsplit('.', 1)
        owner = id_block.path_resolve(owner_path, False)
        setattr(owner, prop_name, value)
        return True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _iter_animatable_id_blocks():
    for attr_name in dir(bpy.data):
        if attr_name.startswith('_'):
            continue
        try:
            collection = getattr(bpy.data, attr_name)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if not hasattr(collection, '__iter__'):
            continue
        try:
            iterator = iter(collection)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        for id_block in iterator:
            if isinstance(id_block, bpy.types.ID):
                yield id_block


def _bake_planetka_dependent_drivers():
    for id_block in list(_iter_animatable_id_blocks()):
        anim = getattr(id_block, 'animation_data', None)
        drivers = getattr(anim, 'drivers', None) if anim else None
        if not drivers:
            continue
        for fcurve in list(drivers):
            driver = getattr(fcurve, 'driver', None)
            if driver is None or not _driver_depends_on_planetka(driver):
                continue
            data_path = str(getattr(fcurve, 'data_path', '') or '')
            array_index = int(getattr(fcurve, 'array_index', -1))
            value = _resolved_property_value(id_block, data_path, array_index)
            try:
                id_block.driver_remove(data_path, array_index)
            except (RuntimeError, TypeError, ValueError, AttributeError):
                try:
                    drivers.remove(fcurve)
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    pass
            if value is not None:
                _assign_resolved_property_value(id_block, data_path, array_index, value)


def _safe_dependency_name(name, used_names):
    stem, ext = os.path.splitext(str(name or '').strip())
    stem = ''.join(ch if ch.isalnum() or ch in {{'-', '_'}} else '_' for ch in stem).strip('_') or 'planetka_vdb'
    ext = ext or '.vdb'
    candidate = f'{{stem}}{{ext}}'
    index = 2
    while candidate.casefold() in used_names:
        candidate = f'{{stem}}_{{index:03d}}{{ext}}'
        index += 1
    used_names.add(candidate.casefold())
    return candidate


def _prepare_external_vdb_files(path):
    out_dir = os.path.dirname(path)
    used_names = set()
    files = []
    prepared = []
    for volume in list(getattr(bpy.data, 'volumes', ())):
        raw = str(getattr(volume, 'filepath', '') or '').strip()
        if not raw:
            continue
        try:
            abs_path = bpy.path.abspath(raw)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            abs_path = raw
        abs_path = os.path.abspath(os.path.expanduser(str(abs_path or '').strip()))
        if not abs_path or abs_path in {{os.path.abspath(os.sep), os.path.abspath('.')}}:
            continue
        if os.path.isdir(abs_path):
            continue
        if os.path.splitext(abs_path)[1].casefold() != '.vdb':
            continue
        if not os.path.isfile(abs_path):
            raise RuntimeError(f'OpenVDB file not found: {{raw}}')
        target_name = _safe_dependency_name(os.path.basename(abs_path), used_names)
        target_path = os.path.join(out_dir, target_name)
        if os.path.abspath(abs_path) != os.path.abspath(target_path):
            shutil.copy2(abs_path, target_path)
        try:
            volume.filepath = target_path
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
        files.append(target_path)
        prepared.append((volume, target_name))
    with open(_manifest_path(path), 'w', encoding='utf-8') as manifest:
        json.dump(files, manifest)
    return prepared


def _make_external_vdb_paths_relative(prepared):
    for volume, target_name in list(prepared or []):
        try:
            volume.filepath = f'//{{target_name}}'
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass


def _run(path):
    if not path:
        raise RuntimeError('Missing Render Street output path.')
    path = os.path.abspath(os.path.expanduser(path))
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    _prepare_render_street_settings()
    _bake_planetka_dependent_drivers()
    _detach_planetka_identity()
    try:
        bpy.ops.file.make_paths_absolute()
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass
    prepared_vdb_files = _prepare_external_vdb_files(path)
    try:
        bpy.ops.file.pack_all()
    except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError(f'pack_all failed: {{exc}}')
    result = bpy.ops.wm.save_as_mainfile(filepath=path, copy=False)
    if 'FINISHED' not in result:
        raise RuntimeError('save_as_mainfile failed.')
    _make_external_vdb_paths_relative(prepared_vdb_files)
    result = bpy.ops.wm.save_as_mainfile(filepath=path, copy=False)
    if 'FINISHED' not in result:
        raise RuntimeError('save_as_mainfile failed.')


if __name__ == '__main__':
    _run(_output_path())
"""


def _create_render_street_standalone(output_path, frames, time_limit_minutes):
    source_path = str(getattr(bpy.data, "filepath", "") or "").strip()
    source_abs = os.path.abspath(source_path) if source_path else ""
    blender_binary = str(getattr(bpy.app, "binary_path", "") or "").strip()
    if not blender_binary or not os.path.isfile(blender_binary):
        raise RuntimeError("Could not locate Blender executable for Render Street export.")

    script_path = ""
    temp_source_path = ""
    try:
        source_for_export = source_abs
        if (not source_for_export) or (not os.path.isfile(source_for_export)) or bool(getattr(bpy.data, "is_dirty", False)):
            fd, temp_source_path = tempfile.mkstemp(suffix="_planetka_render_street_source.blend")
            os.close(fd)
            result = bpy.ops.wm.save_as_mainfile(filepath=temp_source_path, copy=True)
            if "FINISHED" not in result:
                raise RuntimeError("Could not prepare Render Street source copy.")
            source_for_export = temp_source_path

        with tempfile.NamedTemporaryFile(mode="w", suffix="_planetka_render_street_pack.py", delete=False, encoding="utf-8") as script_file:
            script_path = script_file.name
            script_file.write(_standalone_render_street_script(frames, time_limit_minutes))

        completed = subprocess.run(
            [blender_binary, "-b", source_for_export, "--python", script_path, "--", output_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if completed.returncode != 0 or not os.path.isfile(output_path):
            lines = str(completed.stdout or "").splitlines()
            tail = " | ".join(lines[-8:]) if lines else ""
            raise RuntimeError(f"Render Street standalone export failed. {tail}".strip())
        dependencies = []
        manifest_path = f"{output_path}.planetka_render_street_files.json"
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as manifest:
                    payload = json.load(manifest)
                if isinstance(payload, list):
                    dependencies = [str(path) for path in payload if path and os.path.isfile(str(path))]
            finally:
                try:
                    os.remove(manifest_path)
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass
        return [output_path, *dependencies]
    finally:
        for path in (script_path, temp_source_path):
            if path:
                try:
                    os.remove(path)
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass


def _upload_ftps(paths, username, password, remote_dir=""):
    file_paths = [str(path) for path in (paths or []) if path and os.path.isfile(str(path))]
    if not file_paths:
        raise RuntimeError("No Render Street files to upload.")
    remote_dir = str(remote_dir or "").strip().strip("/\\")
    file_size = sum(os.path.getsize(path) for path in file_paths)
    uploaded = 0
    with ftplib.FTP_TLS(timeout=60) as ftp:
        ftp.connect(RENDER_STREET_HOST, RENDER_STREET_PORT)
        ftp.login(username, password)
        ftp.prot_p()
        try:
            ftp.set_pasv(True)
        except (ftplib.Error, OSError):
            pass
        if remote_dir:
            try:
                ftp.mkd(remote_dir)
            except ftplib.error_perm as exc:
                if "exist" not in str(exc).casefold():
                    raise
            ftp.cwd(remote_dir)

        def _callback(chunk):
            nonlocal uploaded
            uploaded += len(chunk)

        for path in file_paths:
            with open(path, "rb") as handle:
                ftp.storbinary(f"STOR {os.path.basename(path)}", handle, blocksize=1024 * 1024, callback=_callback)
        try:
            ftp.quit()
        except (ftplib.Error, OSError):
            pass
    return uploaded, file_size, remote_dir, os.path.basename(file_paths[0])


class PLANETKA_OT_RenderStreetUpload(bpy.types.Operator):
    bl_idname = "planetka.render_street_upload"
    bl_label = "Upload"
    bl_description = "Create a packed standalone Planetka file and upload it to Render Street over FTPS"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene is not None else None
        if props is None:
            return fail(self, "Planetka settings unavailable.", logger=logger)

        try:
            frames = max(1, int(getattr(props, "render_street_frames", RENDER_STREET_DEFAULT_FRAMES) or RENDER_STREET_DEFAULT_FRAMES))
        except (TypeError, ValueError):
            frames = RENDER_STREET_DEFAULT_FRAMES
        try:
            time_limit = max(0.0, float(getattr(props, "render_street_time_limit_minutes", RENDER_STREET_DEFAULT_TIME_LIMIT_MINUTES) or 0.0))
        except (TypeError, ValueError):
            time_limit = RENDER_STREET_DEFAULT_TIME_LIMIT_MINUTES

        username, password, save_login, prefs = _read_credentials(scene, props)
        if not username or not password:
            return fail(self, "Enter Render Street username and password.", logger=logger)
        _write_saved_credentials(prefs, username, password, save_login)

        output_path = _render_street_output_path()
        try:
            props.render_street_status = "Creating standalone file"
        except RENDER_STREET_PREF_EXCEPTIONS:
            pass
        try:
            upload_paths = _create_render_street_standalone(output_path, frames, time_limit)
        except RENDER_STREET_EXPORT_EXCEPTIONS as exc:
            try:
                props.render_street_status = "Export failed"
            except RENDER_STREET_PREF_EXCEPTIONS:
                pass
            return fail(self, f"Render Street export failed: {exc}", logger=logger)

        try:
            props.render_street_status = "Uploading"
        except RENDER_STREET_PREF_EXCEPTIONS:
            pass
        try:
            remote_dir = _remote_upload_folder_name(output_path)
            uploaded, total, remote_dir, remote_file = _upload_ftps(upload_paths, username, password, remote_dir=remote_dir)
        except (ftplib.Error, OSError, RuntimeError, TypeError, ValueError) as exc:
            try:
                props.render_street_status = "Upload failed"
            except RENDER_STREET_PREF_EXCEPTIONS:
                pass
            return fail(self, f"Render Street upload failed: {exc}", logger=logger)

        launch_job = bool(getattr(props, "render_street_launch_job", True))
        if launch_job:
            try:
                props.render_street_status = "Creating Render Street job"
            except RENDER_STREET_PREF_EXCEPTIONS:
                pass
            try:
                job_id, _payload = _create_renderstreet_job(
                    username,
                    password,
                    remote_dir,
                    remote_file,
                    frames,
                    scene=scene,
                    job_name=os.path.splitext(os.path.basename(output_path))[0],
                )
            except RENDER_STREET_JOB_EXCEPTIONS as exc:
                try:
                    props.render_street_status = f"Uploaded; job launch failed: {exc}"
                except RENDER_STREET_PREF_EXCEPTIONS:
                    pass
                self.report({'WARNING'}, f"Render Street upload complete, but job launch failed: {exc}")
                return {'FINISHED'}
            try:
                props.render_street_status = f"Uploaded and launched job {job_id or 'unknown'}"
            except RENDER_STREET_PREF_EXCEPTIONS:
                pass
            self.report({'INFO'}, f"Render Street upload complete; job {job_id or 'unknown'} created.")
            return {'FINISHED'}

        try:
            props.render_street_status = f"Uploaded {os.path.basename(output_path)}"
        except RENDER_STREET_PREF_EXCEPTIONS:
            pass
        self.report({'INFO'}, f"Render Street upload complete: {uploaded}/{total} bytes")
        return {'FINISHED'}


__all__ = ["PLANETKA_OT_RenderStreetUpload"]
