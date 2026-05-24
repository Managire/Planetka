import importlib
import json
import time
import webbrowser

import bpy
from bpy.props import BoolProperty, StringProperty

from ..auth import (
    AuthApiError,
    CLOUD_OVERLOADED_MESSAGE,
    check_scene_full_quality_purchase,
    clear_auth_session,
    connect_with_prefs_api_key,
    create_pro_upgrade_checkout,
    create_scene_full_quality_checkout,
    describe_auth_error,
    get_account_tier,
    get_contact_url,
    get_api_key_request_url,
    list_scene_full_quality_purchases,
    logout_remote_session,
    request_scene_licence_restore_link,
    restore_pro_with_license_key,
)
from ..scene_licensing import scene_license_payload
from ..error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS
from ..extension_prefs import get_prefs
from ..operator_utils import ErrorCode, fail
from ..r2_source import is_download_active
from ..state import ACCOUNT_PANEL_DEFAULT_COLLAPSED_KEY, _is_render_job_active, logger
from ..updater import kickoff_background_update_check, kickoff_background_update_install


_LOGOUT_RECOVERABLE_EXCEPTIONS = (AuthApiError,) + PLANETKA_RECOVERABLE_EXCEPTIONS
_SCENE_PURCHASE_POLL_UNTIL = 0.0
_SCENE_PURCHASE_POLL_ACTIVE = False


def _compute_current_scene_licence_payload(scene, props):
    module_name = f"{__package__.rsplit('.', 1)[0]}.tile_utils" if __package__ else "tile_utils"
    tile_utils = importlib.import_module(module_name)
    full_tiles = tile_utils.main(scope_mode="CAMERA")
    return scene_license_payload(scene=scene, props=props, full_quality_tiles=full_tiles)


def _start_full_quality_resolve_for_scene(scene, props, scene_id):
    if scene is not None and scene_id:
        scene["planetka_current_scene_licence_id"] = str(scene_id)
    if props is not None:
        try:
            props.texture_quality_mode = "FULL"
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed switching to Full Quality after scene purchase", exc_info=True)
    try:
        bpy.ops.planetka.load_textures(
            scope_mode="CAMERA",
            defer_download=True,
            texture_quality_mode_override="FULL",
        )
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed starting Full Quality scene resolve after purchase", exc_info=True)


def _schedule_scene_purchase_poll(scene, props, scene_id, seconds=600.0):
    global _SCENE_PURCHASE_POLL_ACTIVE, _SCENE_PURCHASE_POLL_UNTIL
    safe_scene_id = str(scene_id or "").strip()
    if not safe_scene_id:
        return
    _SCENE_PURCHASE_POLL_UNTIL = max(_SCENE_PURCHASE_POLL_UNTIL, time.monotonic() + max(30.0, float(seconds or 600.0)))
    if _SCENE_PURCHASE_POLL_ACTIVE:
        return
    _SCENE_PURCHASE_POLL_ACTIVE = True

    def _poll():
        global _SCENE_PURCHASE_POLL_ACTIVE
        try:
            result = check_scene_full_quality_purchase(safe_scene_id)
            if bool(result.get("purchased")):
                _SCENE_PURCHASE_POLL_ACTIVE = False
                _start_full_quality_resolve_for_scene(scene, props, safe_scene_id)
                return None
        except (AuthApiError, PLANETKA_RECOVERABLE_EXCEPTIONS, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: scene purchase refresh poll failed", exc_info=True)
        if time.monotonic() >= _SCENE_PURCHASE_POLL_UNTIL:
            _SCENE_PURCHASE_POLL_ACTIVE = False
            return None
        return 5.0

    try:
        bpy.app.timers.register(_poll, first_interval=5.0)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed registering scene purchase poll", exc_info=True)
        _SCENE_PURCHASE_POLL_ACTIVE = False


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
    bl_description = "Download and install the available Planetka update. Restart Blender afterwards to load all changes."

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


class PLANETKA_OT_AccountUpgrade(bpy.types.Operator):
    bl_idname = "planetka.account_upgrade"
    bl_label = "Upgrade to Pro"
    bl_description = "Open Planetka Pro checkout"

    def execute(self, context):
        _ = context
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )
        try:
            checkout = create_pro_upgrade_checkout(prefs)
        except AuthApiError as exc:
            return fail(self, describe_auth_error(exc), logger=logger, exc=exc)
        if bool(checkout.get("already_pro")):
            self.report({'INFO'}, "Planetka Pro is already active.")
            return {'FINISHED'}
        checkout_url = str(checkout.get("checkout_url", "") or "").strip()
        if not checkout_url:
            return fail(self, "Planetka checkout URL is not available.", logger=logger)
        if not _open_account_url(checkout_url):
            return fail(self, "Could not open Planetka checkout.", logger=logger)
        self.report({'INFO'}, "Planetka checkout opened in browser.")
        return {'FINISHED'}


class PLANETKA_OT_AccountRestorePro(bpy.types.Operator):
    bl_idname = "planetka.account_restore_pro"
    bl_label = "Restore Pro"
    bl_description = "Restore Planetka Pro with a Planetka licence key"

    def execute(self, context):
        _ = context
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )
        license_key = str(getattr(prefs, "pro_restore_license_key_input", "") or "").strip()
        if not license_key:
            return fail(self, "Enter a Planetka licence key first.", logger=logger)
        try:
            restore_pro_with_license_key(license_key, prefs=prefs)
            prefs.pro_restore_license_key_input = ""
        except AuthApiError as exc:
            return fail(self, describe_auth_error(exc), logger=logger, exc=exc)
        self.report({'INFO'}, "Planetka Pro restored.")
        return {'FINISHED'}


class PLANETKA_OT_SceneFullQualityPurchase(bpy.types.Operator):
    bl_idname = "planetka.scene_full_quality_purchase"
    bl_label = "Purchase Full Quality + Commercial Licence for This Scene"
    bl_description = "Purchase Full Quality texture access and a commercial licence for the current scene"

    def execute(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene is not None else None
        if scene is None or props is None:
            return fail(
                self,
                "Planetka scene is not available.",
                code=ErrorCode.RESOLVE_PRECHECK_FAILED,
                logger=logger,
            )
        try:
            payload = _compute_current_scene_licence_payload(scene, props)
        except PLANETKA_RECOVERABLE_EXCEPTIONS as exc:
            return fail(self, f"Could not prepare scene licence: {exc}", logger=logger, exc=exc)
        except (RuntimeError, TypeError, ValueError, AttributeError, ImportError) as exc:
            return fail(self, f"Could not prepare scene licence: {exc}", logger=logger)
        scene_id = str(payload.get("scene_id", "") or "").strip()
        if not scene_id or not payload.get("tiles"):
            return fail(self, "This scene has no Full Quality texture tiles to purchase.", logger=logger)
        try:
            checkout = create_scene_full_quality_checkout(
                {
                    "scene_id": scene_id,
                    "camera": payload.get("camera", {}),
                    "tiles": payload.get("tiles", []),
                    "tile_hash": payload.get("tile_hash", ""),
                }
            )
        except AuthApiError as exc:
            return fail(self, describe_auth_error(exc), logger=logger, exc=exc)
        if bool(checkout.get("already_purchased")):
            _start_full_quality_resolve_for_scene(scene, props, scene_id)
            self.report({'INFO'}, "Full Quality scene licence is already active.")
            return {'FINISHED'}
        checkout_url = str(checkout.get("checkout_url", "") or "").strip()
        if not checkout_url:
            return fail(self, "Planetka scene checkout URL is not available.", logger=logger)
        if not _open_account_url(checkout_url):
            return fail(self, "Could not open Planetka scene checkout.", logger=logger)
        scene["planetka_pending_scene_licence_id"] = scene_id
        _schedule_scene_purchase_poll(scene, props, scene_id)
        self.report({'INFO'}, "Planetka scene checkout opened in browser.")
        return {'FINISHED'}


class PLANETKA_OT_ScenePurchasesRefresh(bpy.types.Operator):
    bl_idname = "planetka.scene_purchases_refresh"
    bl_label = "Refresh Scene Licences"
    bl_description = "Refresh the list of purchased Planetka scene licences"

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return fail(self, "Planetka scene is not available.", logger=logger)
        try:
            payload = list_scene_full_quality_purchases(limit=50)
        except AuthApiError as exc:
            return fail(self, describe_auth_error(exc), logger=logger, exc=exc)
        purchases = payload.get("purchases", []) if isinstance(payload, dict) else payload
        if not isinstance(purchases, list):
            purchases = []
        try:
            scene["planetka_scene_purchase_history_json"] = json.dumps(purchases, ensure_ascii=True)
        except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
            return fail(self, "Could not store Planetka scene licence history.", logger=logger, exc=exc)
        self.report({'INFO'}, f"Scene licences refreshed ({len(purchases)}).")
        return {'FINISHED'}


class PLANETKA_OT_SceneLicencesSendAccessLink(bpy.types.Operator):
    bl_idname = "planetka.scene_licences_send_access_link"
    bl_label = "Send Access Link"
    bl_description = "Send a Planetka scene licence access link to this email address"

    def execute(self, context):
        _ = context
        prefs = get_prefs()
        if not prefs:
            return fail(
                self,
                "Planetka preferences not available.",
                code=ErrorCode.RESOLVE_PREFS_MISSING,
                logger=logger,
            )
        email = str(getattr(prefs, "scene_licence_restore_email", "") or "").strip()
        if not email or "@" not in email:
            return fail(self, "Enter the email address used for Planetka scene licence purchases.", logger=logger)
        try:
            request_scene_licence_restore_link(email, prefs=prefs)
        except AuthApiError as exc:
            return fail(self, describe_auth_error(exc), logger=logger, exc=exc)
        self.report({'INFO'}, "Scene licence access link sent.")
        return {'FINISHED'}


class PLANETKA_OT_ScenePurchaseRestore(bpy.types.Operator):
    bl_idname = "planetka.scene_purchase_restore"
    bl_label = "Restore Scene"
    bl_description = "Restore this purchased scene and load its Full Quality data"

    scene_id: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        scene = getattr(context, "scene", None)
        props = getattr(scene, "planetka", None) if scene is not None else None
        if scene is None or props is None:
            return fail(self, "Planetka scene is not available.", logger=logger)
        target_scene_id = str(getattr(self, "scene_id", "") or "").strip()
        try:
            purchases = json.loads(str(scene.get("planetka_scene_purchase_history_json", "[]") or "[]"))
        except (RuntimeError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
            purchases = []
        purchase = next((item for item in purchases if str(item.get("scene_id", "") or "") == target_scene_id), None)
        if not isinstance(purchase, dict):
            return fail(self, "Scene licence was not found. Refresh scene licences and retry.", logger=logger)
        camera_payload = purchase.get("camera", {}) if isinstance(purchase.get("camera", {}), dict) else {}
        tiles = purchase.get("tiles", []) if isinstance(purchase.get("tiles", []), list) else []
        camera = getattr(scene, "camera", None)
        matrix_rows = camera_payload.get("camera_matrix_world", [])
        if camera is not None and isinstance(matrix_rows, list) and len(matrix_rows) == 4:
            try:
                from mathutils import Matrix
                camera.matrix_world = Matrix([[float(value) for value in row] for row in matrix_rows])
            except (RuntimeError, TypeError, ValueError, AttributeError, ImportError):
                logger.debug("Planetka: failed restoring purchased scene camera matrix", exc_info=True)
        for payload_key, prop_key in (
            ("nav_latitude_deg", "nav_latitude_deg"),
            ("nav_longitude_deg", "nav_longitude_deg"),
            ("nav_altitude_km", "nav_altitude_km"),
            ("earth_radius_bu", "earth_radius_bu"),
        ):
            if payload_key in camera_payload:
                try:
                    setattr(props, prop_key, float(camera_payload.get(payload_key)))
                except (RuntimeError, TypeError, ValueError, AttributeError):
                    logger.debug("Planetka: failed restoring purchased scene navigation value", exc_info=True)
        try:
            scene["planetka_current_scene_licence_id"] = target_scene_id
            props.texture_quality_mode = "FULL"
            result = bpy.ops.planetka.load_textures(
                scope_mode="CAMERA",
                defer_download=False,
                tiles_override_json=json.dumps([str(tile) for tile in tiles if str(tile or "").strip()], ensure_ascii=True),
                texture_quality_mode_override="FULL",
            )
        except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
            return fail(self, "Could not restore purchased scene.", logger=logger, exc=exc)
        if "FINISHED" not in result:
            return fail(self, "Could not restore purchased scene.", logger=logger)
        self.report({'INFO'}, "Purchased scene restored.")
        return {'FINISHED'}
