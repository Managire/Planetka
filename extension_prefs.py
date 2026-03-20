import bpy
import json
from bpy.types import AddonPreferences
from bpy.props import EnumProperty, IntProperty, StringProperty

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

EARTH_OBJECT_DEFAULT_NAME = "Planetka Earth Surface"
EARTH_ROLE_KEY = "planetka_role"
EARTH_ROLE_VALUE = "earth_preview"
FALLBACK_TEXTURE_BASE_PATH_KEY = "planetka_texture_base_path"
FALLBACK_TEXTURE_SOURCE_MODE_KEY = "planetka_texture_source_mode"
FALLBACK_SAVED_LOCATIONS_KEY = "planetka_saved_locations_json"
FALLBACK_AUTH_EMAIL_KEY = "planetka_auth_email"
FALLBACK_AUTH_ACCESS_TOKEN_KEY = "planetka_auth_access_token"
FALLBACK_AUTH_REFRESH_TOKEN_KEY = "planetka_auth_refresh_token"
FALLBACK_AUTH_SUBSCRIPTION_STATUS_KEY = "planetka_auth_subscription_status"
FALLBACK_AUTH_RENEWS_AT_KEY = "planetka_auth_renews_at"
FALLBACK_AUTH_TRIAL_ENDS_AT_KEY = "planetka_auth_trial_ends_at"
FALLBACK_AUTH_LOGIN_STATE_KEY = "planetka_auth_login_state"
FALLBACK_AUTH_STATUS_MESSAGE_KEY = "planetka_auth_status_message"
FALLBACK_AUTH_DEVICE_CODE_KEY = "planetka_auth_device_code"
FALLBACK_AUTH_DEVICE_VERIFICATION_URL_KEY = "planetka_auth_device_verification_url"
FALLBACK_AUTH_DEVICE_EXPIRES_AT_KEY = "planetka_auth_device_expires_at"
FALLBACK_AUTH_POLL_INTERVAL_SECONDS_KEY = "planetka_auth_poll_interval_seconds"
TEXTURE_SOURCE_MODE_DEFAULT = "CLOUDFLARE"
LOCAL_TEXTURE_BASE_DEFAULT = "/Volumes/SSDA/Planetka Assets/"


class PlanetkaExtensionPreferences(AddonPreferences):
    __slots__ = ()

    bl_idname = __package__ or __name__

    # Base directory for textures
    texture_base_path: StringProperty(
        name="Texture Files Source Directory",
        subtype='DIR_PATH',
        description="Base folder containing Planetka tile datasets (expects S2, EL, WT, and PO subfolders)",
        default=LOCAL_TEXTURE_BASE_DEFAULT,
    )

    texture_source_mode: EnumProperty(
        name="Texture Source",
        description="Planetka pre-release streams tile textures from Cloudflare",
        items=(
            ("CLOUDFLARE", "Cloudflare", "Stream tiles from Planetka Cloudflare storage"),
        ),
        default=TEXTURE_SOURCE_MODE_DEFAULT,
    )

    saved_locations_json: StringProperty(
        name="Saved Locations",
        default="[]",
        options={'HIDDEN'},
    )

    auth_email: StringProperty(name="Auth Email", default="", options={'HIDDEN'})
    auth_access_token: StringProperty(name="Auth Access Token", default="", options={'HIDDEN'})
    auth_refresh_token: StringProperty(name="Auth Refresh Token", default="", options={'HIDDEN'})
    auth_subscription_status: StringProperty(name="Auth Subscription Status", default="", options={'HIDDEN'})
    auth_renews_at: StringProperty(name="Auth Renews At", default="", options={'HIDDEN'})
    auth_trial_ends_at: StringProperty(name="Auth Trial Ends At", default="", options={'HIDDEN'})
    auth_login_state: StringProperty(name="Auth Login State", default="logged_out", options={'HIDDEN'})
    auth_status_message: StringProperty(name="Auth Status Message", default="", options={'HIDDEN'})
    auth_device_code: StringProperty(name="Auth Device Code", default="", options={'HIDDEN'})
    auth_device_verification_url: StringProperty(
        name="Auth Device Verification URL",
        default="",
        options={'HIDDEN'},
    )
    auth_device_expires_at: StringProperty(name="Auth Device Expires At", default="", options={'HIDDEN'})
    auth_poll_interval_seconds: IntProperty(
        name="Auth Poll Interval Seconds",
        default=2,
        options={'HIDDEN'},
    )

    # File format preference
    def draw(self, context):
        layout = self.layout
        layout.label(text="Planetka Preferences", icon='WORLD')
        layout.label(text="Account is managed in the Planetka sidebar.", icon="INFO")


def mark_earth_object(obj):
    if not obj:
        return
    try:
        obj[EARTH_ROLE_KEY] = EARTH_ROLE_VALUE
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        pass


def _deduplicate_objects(objects):
    unique = []
    seen_ids = set()
    for obj in objects:
        if not obj:
            continue
        obj_id = id(obj)
        if obj_id in seen_ids:
            continue
        seen_ids.add(obj_id)
        unique.append(obj)
    return unique


def get_earth_surface_candidates():
    data = getattr(bpy, "data", None)
    objects = getattr(data, "objects", None) if data is not None else None
    if objects is None:
        return []

    candidates = []
    by_name = objects.get(EARTH_OBJECT_DEFAULT_NAME)
    if by_name and getattr(by_name, "type", None) == 'MESH':
        candidates.append(by_name)

    for obj in objects:
        if getattr(obj, "type", None) != 'MESH':
            continue
        try:
            if obj.get(EARTH_ROLE_KEY) == EARTH_ROLE_VALUE:
                candidates.append(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue

    for obj in objects:
        if getattr(obj, "type", None) != 'MESH':
            continue
        mats = getattr(getattr(obj, "data", None), "materials", None)
        if not mats:
            continue
        for mat in mats:
            if mat and mat.name == "Planetka Earth Material":
                candidates.append(obj)
                break

    return _deduplicate_objects(candidates)


def get_earth_object():
    candidates = get_earth_surface_candidates()
    if not candidates:
        return None

    if len(candidates) == 1:
        mark_earth_object(candidates[0])
        return candidates[0]

    for obj in candidates:
        if obj.name == EARTH_OBJECT_DEFAULT_NAME and getattr(obj, "type", None) == 'MESH':
            mark_earth_object(obj)
            return obj

    role_candidates = []
    for obj in candidates:
        try:
            if obj.get(EARTH_ROLE_KEY) == EARTH_ROLE_VALUE:
                role_candidates.append(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue

    if len(role_candidates) == 1:
        mark_earth_object(role_candidates[0])
        return role_candidates[0]

    return None

def get_prefs():
    class _FallbackPrefs:
        __slots__ = ("_owner",)

        def __init__(self, owner):
            self._owner = owner

        @property
        def texture_base_path(self):
            try:
                return str(self._owner.get(FALLBACK_TEXTURE_BASE_PATH_KEY, LOCAL_TEXTURE_BASE_DEFAULT) or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return LOCAL_TEXTURE_BASE_DEFAULT

        @texture_base_path.setter
        def texture_base_path(self, value):
            try:
                self._owner[FALLBACK_TEXTURE_BASE_PATH_KEY] = str(value or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass

        @property
        def texture_source_mode(self):
            try:
                value = str(self._owner.get(FALLBACK_TEXTURE_SOURCE_MODE_KEY, TEXTURE_SOURCE_MODE_DEFAULT) or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                value = TEXTURE_SOURCE_MODE_DEFAULT
            value = value.strip().upper()
            if value != "CLOUDFLARE":
                return TEXTURE_SOURCE_MODE_DEFAULT
            return value

        @texture_source_mode.setter
        def texture_source_mode(self, value):
            safe = str(value or "").strip().upper()
            if safe != "CLOUDFLARE":
                safe = TEXTURE_SOURCE_MODE_DEFAULT
            try:
                self._owner[FALLBACK_TEXTURE_SOURCE_MODE_KEY] = safe
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass

        @property
        def saved_locations_json(self):
            try:
                return str(self._owner.get(FALLBACK_SAVED_LOCATIONS_KEY, "[]") or "[]")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return "[]"

        @saved_locations_json.setter
        def saved_locations_json(self, value):
            try:
                self._owner[FALLBACK_SAVED_LOCATIONS_KEY] = str(value or "[]")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass

        def _get_value(self, key, default=""):
            try:
                return str(self._owner.get(key, default) or default)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return str(default)

        def _set_value(self, key, value):
            try:
                self._owner[key] = str(value or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass

        auth_email = property(
            lambda self: self._get_value(FALLBACK_AUTH_EMAIL_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_EMAIL_KEY, value),
        )
        auth_access_token = property(
            lambda self: self._get_value(FALLBACK_AUTH_ACCESS_TOKEN_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ACCESS_TOKEN_KEY, value),
        )
        auth_refresh_token = property(
            lambda self: self._get_value(FALLBACK_AUTH_REFRESH_TOKEN_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_REFRESH_TOKEN_KEY, value),
        )
        auth_subscription_status = property(
            lambda self: self._get_value(FALLBACK_AUTH_SUBSCRIPTION_STATUS_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_SUBSCRIPTION_STATUS_KEY, value),
        )
        auth_renews_at = property(
            lambda self: self._get_value(FALLBACK_AUTH_RENEWS_AT_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_RENEWS_AT_KEY, value),
        )
        auth_trial_ends_at = property(
            lambda self: self._get_value(FALLBACK_AUTH_TRIAL_ENDS_AT_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_TRIAL_ENDS_AT_KEY, value),
        )
        auth_login_state = property(
            lambda self: self._get_value(FALLBACK_AUTH_LOGIN_STATE_KEY, "logged_out"),
            lambda self, value: self._set_value(FALLBACK_AUTH_LOGIN_STATE_KEY, value or "logged_out"),
        )
        auth_status_message = property(
            lambda self: self._get_value(FALLBACK_AUTH_STATUS_MESSAGE_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_STATUS_MESSAGE_KEY, value),
        )
        auth_device_code = property(
            lambda self: self._get_value(FALLBACK_AUTH_DEVICE_CODE_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_DEVICE_CODE_KEY, value),
        )
        auth_device_verification_url = property(
            lambda self: self._get_value(FALLBACK_AUTH_DEVICE_VERIFICATION_URL_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_DEVICE_VERIFICATION_URL_KEY, value),
        )
        auth_device_expires_at = property(
            lambda self: self._get_value(FALLBACK_AUTH_DEVICE_EXPIRES_AT_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_DEVICE_EXPIRES_AT_KEY, value),
        )
        auth_poll_interval_seconds = property(
            lambda self: self._get_value(FALLBACK_AUTH_POLL_INTERVAL_SECONDS_KEY, "2"),
            lambda self, value: self._set_value(FALLBACK_AUTH_POLL_INTERVAL_SECONDS_KEY, value or "2"),
        )

    def _addon_pref_by_name(addons, key):
        if key in addons:
            return addons[key].preferences
        key_cf = key.casefold()
        for addon_key, addon in addons.items():
            if addon_key.casefold() == key_cf:
                return addon.preferences
        return None

    def _fallback_owner():
        context = getattr(bpy, "context", None)
        if context is not None:
            owner = getattr(context, "window_manager", None)
            if owner is not None:
                return owner
            owner = getattr(context, "scene", None)
            if owner is not None:
                return owner
        data = getattr(bpy, "data", None)
        scenes = getattr(data, "scenes", None) if data is not None else None
        if scenes:
            try:
                return scenes[0]
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return None
        return None

    extension_name = __package__ or __name__
    preferences = getattr(getattr(bpy, "context", None), "preferences", None)
    addons = getattr(preferences, "addons", None) if preferences is not None else None
    if addons:
        found = _addon_pref_by_name(addons, extension_name)
        if found is not None:
            return found
        short_name = extension_name.split(".")[-1]
        found = _addon_pref_by_name(addons, short_name)
        if found is not None:
            return found
    owner = _fallback_owner()
    if owner is None:
        return None
    return _FallbackPrefs(owner)


def read_saved_locations(prefs):
    if prefs is None:
        return []
    raw = str(getattr(prefs, "saved_locations_json", "[]") or "[]")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        parsed = []
    if not isinstance(parsed, list):
        return []

    normalized = []
    seen_names = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name in seen_names:
            continue
        try:
            lon = float(item.get("lon", 0.0))
            lat = float(item.get("lat", 0.0))
            alt_km = float(item.get("alt_km", 0.0))
        except (TypeError, ValueError):
            continue
        lon = max(-180.0, min(180.0, lon))
        lat = max(-90.0, min(90.0, lat))
        alt_km = max(0.0, alt_km)
        normalized.append({
            "name": name,
            "lon": lon,
            "lat": lat,
            "alt_km": alt_km,
        })
        seen_names.add(name)
    return normalized


def write_saved_locations(prefs, locations):
    if prefs is None:
        return False
    safe_locations = []
    for loc in locations or ():
        if not isinstance(loc, dict):
            continue
        name = str(loc.get("name", "")).strip()
        if not name:
            continue
        try:
            lon = float(loc.get("lon", 0.0))
            lat = float(loc.get("lat", 0.0))
            alt_km = float(loc.get("alt_km", 0.0))
        except (TypeError, ValueError):
            continue
        safe_locations.append({
            "name": name,
            "lon": max(-180.0, min(180.0, lon)),
            "lat": max(-90.0, min(90.0, lat)),
            "alt_km": max(0.0, alt_km),
        })
    try:
        prefs.saved_locations_json = json.dumps(safe_locations, separators=(",", ":"))
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False
