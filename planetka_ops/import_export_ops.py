import os
import subprocess
import tempfile

import bpy
from bpy.props import FloatProperty, IntProperty, StringProperty

from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..operator_utils import ErrorCode, fail
from ..state import logger


class PLANETKA_OT_ImportNewData(bpy.types.Operator):
    bl_idname = "planetka.import_new_data"
    bl_label = "Import New Data"
    bl_description = "Disabled: Planetka uses Cloud source only"

    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        del context
        return fail(
            self,
            "Local texture import is disabled. Planetka uses Cloud source only.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )

    def invoke(self, context, event):
        del context, event
        return fail(
            self,
            "Local texture import is disabled. Planetka uses Cloud source only.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )


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

    def invoke(self, context, event):
        del context, event
        return fail(
            self,
            "Local texture import is disabled. Planetka uses Cloud source only.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )

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
        del context
        return fail(
            self,
            "Local texture import is disabled. Planetka uses Cloud source only.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )


class PLANETKA_OT_SelectTextureSource(bpy.types.Operator):
    bl_idname = "planetka.select_texture_source"
    bl_label = "Set Texture Source"
    bl_description = "Disabled: Planetka uses Cloud source only"

    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        del context
        return fail(
            self,
            "Local texture directories are disabled. Planetka uses Cloud source only.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )

    def invoke(self, context, event):
        del context, event
        return fail(
            self,
            "Local texture directories are disabled. Planetka uses Cloud source only.",
            code=ErrorCode.RESOLVE_PRECHECK_FAILED,
            logger=logger,
        )


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
