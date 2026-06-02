import bpy
from bpy.props import BoolProperty

from ..updater import kickoff_background_update_check, kickoff_background_update_install


class PLANETKA_OT_CheckUpdates(bpy.types.Operator):
    bl_idname = "planetka.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Check for a newer Planetka add-on version"

    force: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        del context
        started = kickoff_background_update_check(force=bool(getattr(self, "force", True)))
        if started:
            self.report({'INFO'}, "Planetka update check started.")
        else:
            self.report({'INFO'}, "Planetka update check is already running or recently completed.")
        return {'FINISHED'}


class PLANETKA_OT_UpdateNow(bpy.types.Operator):
    bl_idname = "planetka.update_now"
    bl_label = "Update Now"
    bl_description = "Download and install the available Planetka update. Restart Blender afterwards to load all changes."

    def execute(self, context):
        del context
        started = kickoff_background_update_install(force=True)
        if started:
            self.report({'INFO'}, "Planetka update started.")
        else:
            self.report({'INFO'}, "Planetka update is already running.")
        return {'FINISHED'}
