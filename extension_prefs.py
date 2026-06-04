import json
import logging
import bpy
from bpy.types import AddonPreferences
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

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
FALLBACK_CLOUD_SESSION_EDITION_KEY = "planetka_cloud_session_edition"
FALLBACK_OPTIMIZE_REMOVE_DEFAULT_SCENE_KEY = "planetka_optimize_remove_default_scene"
FALLBACK_OPTIMIZE_BACKGROUND_BLACK_KEY = "planetka_optimize_background_black"
FALLBACK_OPTIMIZE_EEVEE_VOLUME_RESOLUTION_KEY = "planetka_optimize_eevee_volume_resolution"
FALLBACK_OPTIMIZE_CYCLES_VOLUME_BOUNCES_KEY = "planetka_optimize_cycles_volume_bounces"
FALLBACK_OPTIMIZE_CYCLES_VOLUME_BIASED_KEY = "planetka_optimize_cycles_volume_biased"
FALLBACK_OPTIMIZE_CYCLES_VOLUME_MAX_STEPS_KEY = "planetka_optimize_cycles_volume_max_steps"
FALLBACK_OPTIMIZE_CYCLES_DICING_RATE_RENDER_KEY = "planetka_optimize_cycles_dicing_rate_render"
FALLBACK_OPTIMIZE_CYCLES_DICING_RATE_VIEWPORT_KEY = "planetka_optimize_cycles_dicing_rate_viewport"
FALLBACK_OPTIMIZE_CYCLES_OFFSCREEN_SCALE_KEY = "planetka_optimize_cycles_offscreen_scale"
FALLBACK_OPTIMIZE_CYCLES_MAX_SUBDIVISIONS_KEY = "planetka_optimize_cycles_max_subdivisions"
FALLBACK_OPTIMIZE_PERSISTENT_DATA_KEY = "planetka_optimize_persistent_data"
REMOTE_TEXTURE_BASE_DEFAULT = "remote"

logger = logging.getLogger(__name__)

_EEVEE_VOLUME_RESOLUTION_ITEMS = (
    ("1", "1:1", "Full resolution"),
    ("2", "1:2", "Render volumes at 50% render resolution"),
    ("4", "1:4", "Render volumes at 25% render resolution"),
    ("8", "1:8", "Render volumes at 12.5% render resolution"),
    ("16", "1:16", "Render volumes at 6.25% render resolution"),
)

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
    cloud_session_edition: StringProperty(name="Cloud Session Edition", default="pro", options={'HIDDEN'})
    optimize_remove_default_scene: BoolProperty(
        name="Remove Default Cube Scene",
        description="Remove Blender's untouched default Cube/Camera/Light scene before Create Earth",
        default=True,
    )
    optimize_background_black: BoolProperty(
        name="Set Background to Black",
        description="Set the World background color to black before Create Earth",
        default=True,
    )
    optimize_eevee_volume_resolution: EnumProperty(
        name="Resolution",
        description="Set EEVEE volume render resolution",
        items=_EEVEE_VOLUME_RESOLUTION_ITEMS,
        default="2",
    )
    optimize_cycles_volume_bounces: IntProperty(
        name="Volume",
        description="Set Cycles volume max bounces",
        default=16,
        min=0,
    )
    optimize_cycles_volume_biased: BoolProperty(
        name="Biased",
        description="Enable Cycles biased volume rendering",
        default=True,
    )
    optimize_cycles_volume_max_steps: IntProperty(
        name="Max Steps",
        description="Set Cycles biased volume max steps",
        default=16,
        min=1,
    )
    optimize_cycles_dicing_rate_render: FloatProperty(
        name="Dicing Rate Render",
        description="Set Cycles render dicing rate",
        default=1.5,
        min=0.001,
        precision=3,
    )
    optimize_cycles_dicing_rate_viewport: FloatProperty(
        name="Viewport",
        description="Set Cycles viewport dicing rate",
        default=2.0,
        min=0.001,
        precision=3,
    )
    optimize_cycles_offscreen_scale: FloatProperty(
        name="Offscreen Scale",
        description="Set Cycles offscreen dicing scale",
        default=1.5,
        min=0.001,
        precision=3,
    )
    optimize_cycles_max_subdivisions: IntProperty(
        name="Max Subdivisions",
        description="Set Cycles maximum adaptive subdivisions",
        default=16,
        min=0,
    )
    optimize_persistent_data: BoolProperty(
        name="Persistent Data",
        description="Enable persistent data for final renders",
        default=True,
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

        def _get_bool(self, key, default=False):
            try:
                value = self._owner.get(key, bool(default))
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return bool(default)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)

        def _set_bool(self, key, value):
            try:
                self._owner[key] = bool(value)
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                pass

        def _get_int(self, key, default=0):
            try:
                return int(self._owner.get(key, int(default)))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
                return int(default)

        def _set_int(self, key, value):
            try:
                self._owner[key] = int(value)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
                pass

        def _get_float(self, key, default=0.0):
            try:
                return float(self._owner.get(key, float(default)))
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
                return float(default)

        def _set_float(self, key, value):
            try:
                self._owner[key] = float(value)
            except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
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
        cloud_session_edition = property(
            lambda self: self._get_value(FALLBACK_CLOUD_SESSION_EDITION_KEY, "pro"),
            lambda self, value: self._set_value(FALLBACK_CLOUD_SESSION_EDITION_KEY, value),
        )
        optimize_remove_default_scene = property(
            lambda self: self._get_bool(FALLBACK_OPTIMIZE_REMOVE_DEFAULT_SCENE_KEY, True),
            lambda self, value: self._set_bool(FALLBACK_OPTIMIZE_REMOVE_DEFAULT_SCENE_KEY, value),
        )
        optimize_background_black = property(
            lambda self: self._get_bool(FALLBACK_OPTIMIZE_BACKGROUND_BLACK_KEY, True),
            lambda self, value: self._set_bool(FALLBACK_OPTIMIZE_BACKGROUND_BLACK_KEY, value),
        )
        optimize_eevee_volume_resolution = property(
            lambda self: self._get_value(FALLBACK_OPTIMIZE_EEVEE_VOLUME_RESOLUTION_KEY, "2"),
            lambda self, value: self._set_value(FALLBACK_OPTIMIZE_EEVEE_VOLUME_RESOLUTION_KEY, value),
        )
        optimize_cycles_volume_bounces = property(
            lambda self: self._get_int(FALLBACK_OPTIMIZE_CYCLES_VOLUME_BOUNCES_KEY, 16),
            lambda self, value: self._set_int(FALLBACK_OPTIMIZE_CYCLES_VOLUME_BOUNCES_KEY, value),
        )
        optimize_cycles_volume_biased = property(
            lambda self: self._get_bool(FALLBACK_OPTIMIZE_CYCLES_VOLUME_BIASED_KEY, True),
            lambda self, value: self._set_bool(FALLBACK_OPTIMIZE_CYCLES_VOLUME_BIASED_KEY, value),
        )
        optimize_cycles_volume_max_steps = property(
            lambda self: self._get_int(FALLBACK_OPTIMIZE_CYCLES_VOLUME_MAX_STEPS_KEY, 16),
            lambda self, value: self._set_int(FALLBACK_OPTIMIZE_CYCLES_VOLUME_MAX_STEPS_KEY, value),
        )
        optimize_cycles_dicing_rate_render = property(
            lambda self: self._get_float(FALLBACK_OPTIMIZE_CYCLES_DICING_RATE_RENDER_KEY, 1.5),
            lambda self, value: self._set_float(FALLBACK_OPTIMIZE_CYCLES_DICING_RATE_RENDER_KEY, value),
        )
        optimize_cycles_dicing_rate_viewport = property(
            lambda self: self._get_float(FALLBACK_OPTIMIZE_CYCLES_DICING_RATE_VIEWPORT_KEY, 2.0),
            lambda self, value: self._set_float(FALLBACK_OPTIMIZE_CYCLES_DICING_RATE_VIEWPORT_KEY, value),
        )
        optimize_cycles_offscreen_scale = property(
            lambda self: self._get_float(FALLBACK_OPTIMIZE_CYCLES_OFFSCREEN_SCALE_KEY, 1.5),
            lambda self, value: self._set_float(FALLBACK_OPTIMIZE_CYCLES_OFFSCREEN_SCALE_KEY, value),
        )
        optimize_cycles_max_subdivisions = property(
            lambda self: self._get_int(FALLBACK_OPTIMIZE_CYCLES_MAX_SUBDIVISIONS_KEY, 16),
            lambda self, value: self._set_int(FALLBACK_OPTIMIZE_CYCLES_MAX_SUBDIVISIONS_KEY, value),
        )
        optimize_persistent_data = property(
            lambda self: self._get_bool(FALLBACK_OPTIMIZE_PERSISTENT_DATA_KEY, True),
            lambda self, value: self._set_bool(FALLBACK_OPTIMIZE_PERSISTENT_DATA_KEY, value),
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
