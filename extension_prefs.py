import logging
import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

EARTH_OBJECT_DEFAULT_NAME = "Planetka Earth Surface"
EARTH_ROLE_KEY = "planetka_role"
EARTH_ROLE_VALUE = "earth_preview"

logger = logging.getLogger(__name__)

class PlanetkaExtensionPreferences(AddonPreferences):
    __slots__ = ()

    bl_idname = __package__ or __name__

    cloud_install_id: StringProperty(name="Cloud Install ID", default="", options={'HIDDEN'})
    cloud_session_access_token: StringProperty(name="Cloud Session Access Token", default="", options={'HIDDEN'})
    cloud_session_refresh_token: StringProperty(name="Cloud Session Refresh Token", default="", options={'HIDDEN'})
    cloud_session_status_message: StringProperty(name="Cloud Session Status Message", default="", options={'HIDDEN'})
    cloud_session_edition: StringProperty(name="Cloud Session Edition", default="pro", options={'HIDDEN'})
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
    def _addon_pref_by_name(addons, key):
        if key in addons:
            return addons[key].preferences
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
    return None
