import bpy
import json
from bpy.types import AddonPreferences
from bpy.props import StringProperty

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

EARTH_OBJECT_DEFAULT_NAME = "Planetka Earth Surface"
EARTH_ROLE_KEY = "planetka_role"
EARTH_ROLE_VALUE = "earth_preview"
FALLBACK_TEXTURE_BASE_PATH_KEY = "planetka_texture_base_path"
FALLBACK_SAVED_LOCATIONS_KEY = "planetka_saved_locations_json"


class PlanetkaExtensionPreferences(AddonPreferences):
    __slots__ = ()

    bl_idname = __package__ or __name__

    # Base directory for textures
    texture_base_path: StringProperty(
        name="Texture Files Source Directory",
        subtype='DIR_PATH',
        description="Base folder containing Planetka tile datasets (expects S2, EL, WT, and PO subfolders)",
    )

    saved_locations_json: StringProperty(
        name="Saved Locations",
        default="[]",
        options={'HIDDEN'},
    )

    # File format preference
    def draw(self, context):
        layout = self.layout
        layout.label(text="Planetka Preferences", icon='WORLD')
        layout.prop(self, "texture_base_path")


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
                return str(self._owner.get(FALLBACK_TEXTURE_BASE_PATH_KEY, "") or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                return ""

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
