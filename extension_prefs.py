import bpy
import json
import logging
from bpy.types import AddonPreferences
from bpy.props import BoolProperty, IntProperty, StringProperty

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

EARTH_OBJECT_DEFAULT_NAME = "Planetka Earth Surface"
EARTH_ROLE_KEY = "planetka_role"
EARTH_ROLE_VALUE = "earth_preview"
FALLBACK_TEXTURE_BASE_PATH_KEY = "planetka_texture_base_path"
FALLBACK_SAVED_LOCATIONS_KEY = "planetka_saved_locations_json"
FALLBACK_CLOUD_INSTALL_ID_KEY = "planetka_cloud_install_id"
FALLBACK_CLOUD_SESSION_ACCESS_TOKEN_KEY = "planetka_cloud_session_access_token"
FALLBACK_CLOUD_SESSION_REFRESH_TOKEN_KEY = "planetka_cloud_session_refresh_token"
FALLBACK_CLOUD_SESSION_STATUS_MESSAGE_KEY = "planetka_cloud_session_status_message"
FALLBACK_STARTUP_SETUP_PROFILE_JSON_KEY = "planetka_startup_setup_profile_json"
FALLBACK_CREATE_EARTH_PREFLIGHT_SEEN_VERSION_KEY = "planetka_create_earth_preflight_seen_version"
REMOTE_TEXTURE_BASE_DEFAULT = "remote"

logger = logging.getLogger(__name__)

class PlanetkaExtensionPreferences(AddonPreferences):
    __slots__ = ()

    bl_idname = __package__ or __name__

    # Base directory for textures
    texture_base_path: StringProperty(
        name="Texture Source",
        subtype='DIR_PATH',
        description="Internal Planetka source marker (Cloud only)",
        default=REMOTE_TEXTURE_BASE_DEFAULT,
    )

    saved_locations_json: StringProperty(
        name="Saved Locations",
        default="[]",
        options={'HIDDEN'},
    )

    cloud_install_id: StringProperty(name="Cloud Install ID", default="", options={'HIDDEN'})
    cloud_session_access_token: StringProperty(name="Cloud Session Access Token", default="", options={'HIDDEN'})
    cloud_session_refresh_token: StringProperty(name="Cloud Session Refresh Token", default="", options={'HIDDEN'})
    cloud_session_status_message: StringProperty(name="Cloud Session Status Message", default="", options={'HIDDEN'})
    startup_setup_profile_json: StringProperty(
        name="Startup Setup Profile",
        default="",
        options={'HIDDEN'},
    )
    create_earth_preflight_seen_version: StringProperty(
        name="Create Earth Preflight Seen Version",
        default="",
        options={'HIDDEN'},
    )

    # File format preference
    def draw(self, context):
        layout = self.layout
        layout.label(text="Planetka Preferences", icon='WORLD')
        layout.label(text="Planetka connects to Planetka Cloud automatically.", icon="INFO")


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

    # Strict identity rule:
    # Only an object with the canonical name is considered the active Earth surface.
    # If the user renames it, Planetka treats the surface as missing.
    by_name = objects.get(EARTH_OBJECT_DEFAULT_NAME)
    if by_name and getattr(by_name, "type", None) == 'MESH':
        return [by_name]
    return []


def get_earth_object():
    candidates = get_earth_surface_candidates()
    return candidates[0] if candidates else None

def get_prefs():
    class _FallbackPrefs:
        __slots__ = ("_owner",)

        def __init__(self, owner):
            self._owner = owner

        @property
        def texture_base_path(self):
            try:
                return str(self._owner.get(FALLBACK_TEXTURE_BASE_PATH_KEY, REMOTE_TEXTURE_BASE_DEFAULT) or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return REMOTE_TEXTURE_BASE_DEFAULT

        @texture_base_path.setter
        def texture_base_path(self, value):
            try:
                self._owner[FALLBACK_TEXTURE_BASE_PATH_KEY] = str(value or "")
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

        cloud_install_id = property(
            lambda self: self._get_value(FALLBACK_CLOUD_INSTALL_ID_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_CLOUD_INSTALL_ID_KEY, value),
        )
        cloud_session_access_token = property(
            lambda self: self._get_value(FALLBACK_CLOUD_SESSION_ACCESS_TOKEN_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_CLOUD_SESSION_ACCESS_TOKEN_KEY, value),
        )
        cloud_session_refresh_token = property(
            lambda self: self._get_value(FALLBACK_CLOUD_SESSION_REFRESH_TOKEN_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_CLOUD_SESSION_REFRESH_TOKEN_KEY, value),
        )
        cloud_session_status_message = property(
            lambda self: self._get_value(FALLBACK_CLOUD_SESSION_STATUS_MESSAGE_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_CLOUD_SESSION_STATUS_MESSAGE_KEY, value),
        )
        startup_setup_profile_json = property(
            lambda self: self._get_value(FALLBACK_STARTUP_SETUP_PROFILE_JSON_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_STARTUP_SETUP_PROFILE_JSON_KEY, value),
        )
        create_earth_preflight_seen_version = property(
            lambda self: self._get_value(FALLBACK_CREATE_EARTH_PREFLIGHT_SEEN_VERSION_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_CREATE_EARTH_PREFLIGHT_SEEN_VERSION_KEY, value),
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
