import webbrowser

import bpy
from bpy.props import BoolProperty

from ..auth import (
    AuthApiError,
    clear_auth_session,
    connect_with_prefs_api_key,
    describe_auth_error,
    get_contact_url,
    get_api_key_request_url,
    get_upgrade_url,
    logout_remote_session,
    sync_account_profile,
)
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_prefs
from ..operator_utils import ErrorCode, fail
from ..r2_source import is_download_active
from ..state import ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY, _is_render_job_active, logger
from ..updater import kickoff_background_update_check, kickoff_background_update_install


_LOGOUT_RECOVERABLE_EXCEPTIONS = (AuthApiError,) + PLANETKA_RECOVERABLE_EXCEPTIONS


class PLANETKA_OT_AccountLogin(bpy.types.Operator):
    bl_idname = "planetka.account_login"
    bl_label = "Request Account Access"
    bl_description = "Open the Planetka account access page in your browser"

    def execute(self, context):
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        verification_url = str(get_api_key_request_url() or "").strip()
        if not verification_url:
            return fail(self, "Planetka account access page is not configured. Contact Planetka support.", logger=logger)

        opened = False
        try:
            result = bpy.ops.wm.url_open(url=verification_url)
            opened = "FINISHED" in result
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            opened = False

        if not opened:
            try:
                opened = bool(webbrowser.open(verification_url))
            except (RuntimeError, TypeError, ValueError, OSError):
                logger.debug("Planetka: failed opening account access URL in system browser", exc_info=True)
                opened = False

        if not opened:
            return fail(
                self,
                "Planetka could not open the account access page automatically.",
                logger=logger,
            )

        self.report({'INFO'}, "Request account access in your browser, then paste the access key into Blender.")
        return {'FINISHED'}


class PLANETKA_OT_AccountOpenLogin(bpy.types.Operator):
    bl_idname = "planetka.account_open_login"
    bl_label = "Connect Account"
    bl_description = "Connect Planetka using the pasted account access key"

    def execute(self, context):
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        try:
            connect_with_prefs_api_key(prefs)
        except AuthApiError as exc:
            status_text = describe_auth_error(exc)
            try:
                prefs.auth_status_message = str(status_text or "")
                prefs.auth_login_state = "logged_out"
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed storing account access error status", exc_info=True)
            return fail(
                self,
                status_text,
                logger=logger,
                exc=exc,
            )
        try:
            # Refresh canonical stored tier/profile fields immediately after login.
            sync_account_profile(prefs)
        except (AuthApiError, PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: post-login account profile sync failed", exc_info=True)
        try:
            prefs.auth_status_message = ""
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed clearing account access status message", exc_info=True)
        scene = getattr(context, "scene", None) if context is not None else None
        if scene is not None:
            try:
                scene[ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY] = False
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                logger.debug("Planetka: failed opening account panel after login", exc_info=True)
        self.report({'INFO'}, "Planetka account connected.")
        return {'FINISHED'}


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
    bl_description = "Download and install available Planetka update"

    def execute(self, context):
        del context
        started = kickoff_background_update_install(force=True)
        if started:
            self.report({'INFO'}, "Planetka update started.")
        else:
            self.report({'INFO'}, "Planetka update is already running.")
        return {'FINISHED'}


class PLANETKA_OT_AccountLogout(bpy.types.Operator):
    bl_idname = "planetka.account_logout"
    bl_label = "Log Out"
    bl_description = "Remove the local Planetka login session from Blender"
    bl_options = {'REGISTER', 'INTERNAL'}

    _confirm_render_active = False
    _confirm_download_active = False

    def _detect_active_operations(self):
        render_active = False
        download_active = False
        try:
            render_active = bool(_is_render_job_active())
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed checking render activity before logout", exc_info=True)
        try:
            download_active = bool(is_download_active())
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: failed checking download activity before logout", exc_info=True)
        return render_active, download_active

    def invoke(self, context, event):
        render_active, download_active = self._detect_active_operations()
        self._confirm_render_active = bool(render_active)
        self._confirm_download_active = bool(download_active)
        if self._confirm_render_active or self._confirm_download_active:
            wm = getattr(context, "window_manager", None)
            if wm is not None:
                return wm.invoke_confirm(self, event)
        return self.execute(context)

    def draw(self, context):
        del context
        layout = self.layout
        layout.label(text="Planetka activity is running.", icon="INFO")
        if bool(self._confirm_render_active):
            layout.label(text="Render job is active.", icon="RENDER_STILL")
        if bool(self._confirm_download_active):
            layout.label(text="Tile download is active.", icon="IMPORT")
        layout.label(text="Log out anyway?", icon="QUESTION")

    def execute(self, context):
        del context
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        try:
            logout_remote_session(prefs)
        except _LOGOUT_RECOVERABLE_EXCEPTIONS:
            logger.debug("Planetka: remote logout request failed", exc_info=True)
        clear_auth_session(prefs)
        self.report({'INFO'}, "Planetka account disconnected in Blender.")
        return {'FINISHED'}


def _open_account_url(url):
    safe_url = str(url or "").strip()
    if not safe_url:
        return False

    opened = False
    try:
        result = bpy.ops.wm.url_open(url=safe_url)
        opened = "FINISHED" in result
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        opened = False

    if not opened:
        try:
            opened = bool(webbrowser.open(safe_url))
        except (RuntimeError, TypeError, ValueError, OSError):
            logger.debug("Planetka: failed opening account URL in system browser", exc_info=True)
            opened = False

    return bool(opened)


class PLANETKA_OT_AccountUpgrade(bpy.types.Operator):
    bl_idname = "planetka.account_upgrade"
    bl_label = "Upgrade Licence"
    bl_description = "Open Planetka pricing page"

    def execute(self, context):
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        upgrade_url = get_upgrade_url(prefs)
        if not upgrade_url:
            return fail(self, "Planetka pricing URL is not configured.", logger=logger)
        if not _open_account_url(upgrade_url):
            return fail(self, "Could not open Planetka pricing page.", logger=logger)
        self.report({'INFO'}, "Planetka pricing page opened in browser.")
        return {'FINISHED'}


class PLANETKA_OT_AccountContact(bpy.types.Operator):
    bl_idname = "planetka.account_contact"
    bl_label = "Contact Me"
    bl_description = "Open Planetka contact page"

    def execute(self, context):
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )

        contact_url = get_contact_url(prefs)
        if not contact_url:
            return fail(self, "Planetka contact URL is not configured.", logger=logger)
        if not _open_account_url(contact_url):
            return fail(self, "Could not open Planetka contact page.", logger=logger)
        self.report({'INFO'}, "Planetka contact page opened in browser.")
        return {'FINISHED'}
