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
FALLBACK_AUTH_API_KEY_KEY = "planetka_auth_api_key"
FALLBACK_AUTH_API_KEY_INPUT_KEY = "planetka_auth_api_key_input"
FALLBACK_AUTH_API_KEY_MASK_KEY = "planetka_auth_api_key_mask"
FALLBACK_AUTH_DEVICE_ID_KEY = "planetka_auth_device_id"
FALLBACK_AUTH_ACCESS_TOKEN_KEY = "planetka_auth_access_token"
FALLBACK_AUTH_REFRESH_TOKEN_KEY = "planetka_auth_refresh_token"
FALLBACK_AUTH_ACCOUNT_TIER_KEY = "planetka_auth_account_tier"
FALLBACK_AUTH_COMMERCIAL_USE_ALLOWED_KEY = "planetka_auth_commercial_use_allowed"
FALLBACK_AUTH_PLAN_CODE_KEY = "planetka_auth_plan_code"
FALLBACK_AUTH_PLAN_NAME_KEY = "planetka_auth_plan_name"
FALLBACK_AUTH_BILLING_PERIOD_END_KEY = "planetka_auth_billing_period_end"
FALLBACK_AUTH_CONTACT_URL_KEY = "planetka_auth_contact_url"
FALLBACK_AUTH_UPGRADE_URL_KEY = "planetka_auth_upgrade_url"
FALLBACK_AUTH_TOPUP_URL_KEY = "planetka_auth_topup_url"
FALLBACK_AUTH_MANAGE_SUBSCRIPTION_URL_KEY = "planetka_auth_manage_subscription_url"
FALLBACK_AUTH_TILE_QUOTA_USED_KEY = "planetka_auth_tile_quota_used"
FALLBACK_AUTH_TILE_QUOTA_LIMIT_KEY = "planetka_auth_tile_quota_limit"
FALLBACK_AUTH_TILE_QUOTA_RESET_AT_KEY = "planetka_auth_tile_quota_reset_at"
FALLBACK_AUTH_TILE_QUOTA_PERIOD_KEY = "planetka_auth_tile_quota_period"
FALLBACK_AUTH_TILE_QUOTA_RULE_KEY = "planetka_auth_tile_quota_rule"
FALLBACK_AUTH_ALLOWANCE_INCLUDED_LIMIT_BYTES_KEY = "planetka_auth_allowance_included_limit_bytes"
FALLBACK_AUTH_ALLOWANCE_INCLUDED_REMAINING_BYTES_KEY = "planetka_auth_allowance_included_remaining_bytes"
FALLBACK_AUTH_ALLOWANCE_TOPUP_REMAINING_BYTES_KEY = "planetka_auth_allowance_topup_remaining_bytes"
FALLBACK_AUTH_ALLOWANCE_TOTAL_REMAINING_BYTES_KEY = "planetka_auth_allowance_total_remaining_bytes"
FALLBACK_AUTH_ALLOWANCE_PERIOD_END_KEY = "planetka_auth_allowance_period_end"
FALLBACK_AUTH_ALLOWANCE_PERIOD_KEY = "planetka_auth_allowance_period"
FALLBACK_AUTH_ALLOWANCE_COUNTING_RULE_KEY = "planetka_auth_allowance_counting_rule"
FALLBACK_AUTH_ALLOWANCE_WARNING_STATE_KEY = "planetka_auth_allowance_warning_state"
FALLBACK_AUTH_ALLOWANCE_EXHAUSTED_KEY = "planetka_auth_allowance_exhausted"
FALLBACK_AUTH_ALLOWANCE_DOWNLOADED_PERIOD_BYTES_KEY = "planetka_auth_allowance_downloaded_period_bytes"
FALLBACK_AUTH_LOGIN_STATE_KEY = "planetka_auth_login_state"
FALLBACK_AUTH_STATUS_MESSAGE_KEY = "planetka_auth_status_message"
FALLBACK_AUTH_DEVICE_CODE_KEY = "planetka_auth_device_code"
FALLBACK_AUTH_DEVICE_VERIFICATION_URL_KEY = "planetka_auth_device_verification_url"
FALLBACK_AUTH_DEVICE_EXPIRES_AT_KEY = "planetka_auth_device_expires_at"
FALLBACK_AUTH_POLL_INTERVAL_SECONDS_KEY = "planetka_auth_poll_interval_seconds"
FALLBACK_STARTUP_SETUP_PROFILE_JSON_KEY = "planetka_startup_setup_profile_json"
TEXTURE_SOURCE_MODE_DEFAULT = "CLOUDFLARE"
REMOTE_TEXTURE_BASE_DEFAULT = "remote"


class PlanetkaExtensionPreferences(AddonPreferences):
    __slots__ = ()

    bl_idname = __package__ or __name__

    # Base directory for textures
    texture_base_path: StringProperty(
        name="Texture Source",
        subtype='DIR_PATH',
        description="Internal Planetka source marker (Cloudflare only)",
        default=REMOTE_TEXTURE_BASE_DEFAULT,
    )

    texture_source_mode: EnumProperty(
        name="Texture Source",
        description="Planetka resolves tile textures from Cloudflare",
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
    auth_api_key: StringProperty(name="Auth API Key", default="", options={'HIDDEN'})
    auth_api_key_input: StringProperty(name="Auth API Key Input", default="", options={'HIDDEN'})
    auth_api_key_mask: StringProperty(name="Auth API Key Mask", default="", options={'HIDDEN'})
    auth_device_id: StringProperty(name="Auth Device ID", default="", options={'HIDDEN'})
    auth_access_token: StringProperty(name="Auth Access Token", default="", options={'HIDDEN'})
    auth_refresh_token: StringProperty(name="Auth Refresh Token", default="", options={'HIDDEN'})
    auth_account_tier: StringProperty(name="Auth Account Tier", default="", options={'HIDDEN'})
    auth_commercial_use_allowed: StringProperty(name="Auth Commercial Use Allowed", default="", options={'HIDDEN'})
    auth_plan_code: StringProperty(name="Auth Plan Code", default="", options={'HIDDEN'})
    auth_plan_name: StringProperty(name="Auth Plan Name", default="", options={'HIDDEN'})
    auth_billing_period_end: StringProperty(name="Auth Billing Period End", default="", options={'HIDDEN'})
    auth_contact_url: StringProperty(name="Auth Contact URL", default="", options={'HIDDEN'})
    auth_upgrade_url: StringProperty(name="Auth Upgrade URL", default="", options={'HIDDEN'})
    auth_topup_url: StringProperty(name="Auth Top-Up URL", default="", options={'HIDDEN'})
    auth_manage_subscription_url: StringProperty(name="Auth Manage Subscription URL", default="", options={'HIDDEN'})
    auth_tile_quota_used: StringProperty(name="Auth Tile Quota Used", default="", options={'HIDDEN'})
    auth_tile_quota_limit: StringProperty(name="Auth Tile Quota Limit", default="", options={'HIDDEN'})
    auth_tile_quota_reset_at: StringProperty(name="Auth Tile Quota Reset At", default="", options={'HIDDEN'})
    auth_tile_quota_period: StringProperty(name="Auth Tile Quota Period", default="", options={'HIDDEN'})
    auth_tile_quota_rule: StringProperty(name="Auth Tile Quota Rule", default="", options={'HIDDEN'})
    auth_allowance_included_limit_bytes: StringProperty(name="Auth Included Limit Bytes", default="", options={'HIDDEN'})
    auth_allowance_included_remaining_bytes: StringProperty(name="Auth Included Remaining Bytes", default="", options={'HIDDEN'})
    auth_allowance_topup_remaining_bytes: StringProperty(name="Auth Topup Remaining Bytes", default="", options={'HIDDEN'})
    auth_allowance_total_remaining_bytes: StringProperty(name="Auth Total Remaining Bytes", default="", options={'HIDDEN'})
    auth_allowance_period_end: StringProperty(name="Auth Allowance Period End", default="", options={'HIDDEN'})
    auth_allowance_period: StringProperty(name="Auth Allowance Period", default="", options={'HIDDEN'})
    auth_allowance_counting_rule: StringProperty(name="Auth Allowance Counting Rule", default="", options={'HIDDEN'})
    auth_allowance_warning_state: StringProperty(name="Auth Allowance Warning State", default="", options={'HIDDEN'})
    auth_allowance_exhausted: StringProperty(name="Auth Allowance Exhausted", default="", options={'HIDDEN'})
    auth_allowance_downloaded_period_bytes: StringProperty(name="Auth Allowance Downloaded Period Bytes", default="", options={'HIDDEN'})
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
    startup_setup_profile_json: StringProperty(
        name="Startup Setup Profile",
        default="",
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
        return candidates[0]

    for obj in candidates:
        if obj.name == EARTH_OBJECT_DEFAULT_NAME and getattr(obj, "type", None) == 'MESH':
            return obj

    role_candidates = []
    for obj in candidates:
        try:
            if obj.get(EARTH_ROLE_KEY) == EARTH_ROLE_VALUE:
                role_candidates.append(obj)
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue

    if len(role_candidates) == 1:
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
        def texture_source_mode(self):
            try:
                value = str(self._owner.get(FALLBACK_TEXTURE_SOURCE_MODE_KEY, TEXTURE_SOURCE_MODE_DEFAULT) or "")
            except PLANETKA_RECOVERABLE_EXCEPTIONS:
                value = TEXTURE_SOURCE_MODE_DEFAULT
            value = value.strip().upper()
            if value != "CLOUDFLARE":
                return TEXTURE_SOURCE_MODE_DEFAULT
            return "CLOUDFLARE"

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
        auth_api_key = property(
            lambda self: self._get_value(FALLBACK_AUTH_API_KEY_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_API_KEY_KEY, value),
        )
        auth_api_key_input = property(
            lambda self: self._get_value(FALLBACK_AUTH_API_KEY_INPUT_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_API_KEY_INPUT_KEY, value),
        )
        auth_api_key_mask = property(
            lambda self: self._get_value(FALLBACK_AUTH_API_KEY_MASK_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_API_KEY_MASK_KEY, value),
        )
        auth_device_id = property(
            lambda self: self._get_value(FALLBACK_AUTH_DEVICE_ID_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_DEVICE_ID_KEY, value),
        )
        auth_access_token = property(
            lambda self: self._get_value(FALLBACK_AUTH_ACCESS_TOKEN_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ACCESS_TOKEN_KEY, value),
        )
        auth_refresh_token = property(
            lambda self: self._get_value(FALLBACK_AUTH_REFRESH_TOKEN_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_REFRESH_TOKEN_KEY, value),
        )
        auth_account_tier = property(
            lambda self: self._get_value(FALLBACK_AUTH_ACCOUNT_TIER_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ACCOUNT_TIER_KEY, value),
        )
        auth_commercial_use_allowed = property(
            lambda self: self._get_value(FALLBACK_AUTH_COMMERCIAL_USE_ALLOWED_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_COMMERCIAL_USE_ALLOWED_KEY, value),
        )
        auth_plan_code = property(
            lambda self: self._get_value(FALLBACK_AUTH_PLAN_CODE_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_PLAN_CODE_KEY, value),
        )
        auth_plan_name = property(
            lambda self: self._get_value(FALLBACK_AUTH_PLAN_NAME_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_PLAN_NAME_KEY, value),
        )
        auth_billing_period_end = property(
            lambda self: self._get_value(FALLBACK_AUTH_BILLING_PERIOD_END_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_BILLING_PERIOD_END_KEY, value),
        )
        auth_contact_url = property(
            lambda self: self._get_value(FALLBACK_AUTH_CONTACT_URL_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_CONTACT_URL_KEY, value),
        )
        auth_upgrade_url = property(
            lambda self: self._get_value(FALLBACK_AUTH_UPGRADE_URL_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_UPGRADE_URL_KEY, value),
        )
        auth_topup_url = property(
            lambda self: self._get_value(FALLBACK_AUTH_TOPUP_URL_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_TOPUP_URL_KEY, value),
        )
        auth_manage_subscription_url = property(
            lambda self: self._get_value(FALLBACK_AUTH_MANAGE_SUBSCRIPTION_URL_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_MANAGE_SUBSCRIPTION_URL_KEY, value),
        )
        auth_tile_quota_used = property(
            lambda self: self._get_value(FALLBACK_AUTH_TILE_QUOTA_USED_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_TILE_QUOTA_USED_KEY, value),
        )
        auth_tile_quota_limit = property(
            lambda self: self._get_value(FALLBACK_AUTH_TILE_QUOTA_LIMIT_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_TILE_QUOTA_LIMIT_KEY, value),
        )
        auth_tile_quota_reset_at = property(
            lambda self: self._get_value(FALLBACK_AUTH_TILE_QUOTA_RESET_AT_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_TILE_QUOTA_RESET_AT_KEY, value),
        )
        auth_tile_quota_period = property(
            lambda self: self._get_value(FALLBACK_AUTH_TILE_QUOTA_PERIOD_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_TILE_QUOTA_PERIOD_KEY, value),
        )
        auth_tile_quota_rule = property(
            lambda self: self._get_value(FALLBACK_AUTH_TILE_QUOTA_RULE_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_TILE_QUOTA_RULE_KEY, value),
        )
        auth_allowance_included_limit_bytes = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_INCLUDED_LIMIT_BYTES_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_INCLUDED_LIMIT_BYTES_KEY, value),
        )
        auth_allowance_included_remaining_bytes = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_INCLUDED_REMAINING_BYTES_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_INCLUDED_REMAINING_BYTES_KEY, value),
        )
        auth_allowance_topup_remaining_bytes = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_TOPUP_REMAINING_BYTES_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_TOPUP_REMAINING_BYTES_KEY, value),
        )
        auth_allowance_total_remaining_bytes = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_TOTAL_REMAINING_BYTES_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_TOTAL_REMAINING_BYTES_KEY, value),
        )
        auth_allowance_period_end = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_PERIOD_END_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_PERIOD_END_KEY, value),
        )
        auth_allowance_period = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_PERIOD_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_PERIOD_KEY, value),
        )
        auth_allowance_counting_rule = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_COUNTING_RULE_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_COUNTING_RULE_KEY, value),
        )
        auth_allowance_warning_state = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_WARNING_STATE_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_WARNING_STATE_KEY, value),
        )
        auth_allowance_exhausted = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_EXHAUSTED_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_EXHAUSTED_KEY, value),
        )
        auth_allowance_downloaded_period_bytes = property(
            lambda self: self._get_value(FALLBACK_AUTH_ALLOWANCE_DOWNLOADED_PERIOD_BYTES_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_AUTH_ALLOWANCE_DOWNLOADED_PERIOD_BYTES_KEY, value),
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
        startup_setup_profile_json = property(
            lambda self: self._get_value(FALLBACK_STARTUP_SETUP_PROFILE_JSON_KEY, ""),
            lambda self, value: self._set_value(FALLBACK_STARTUP_SETUP_PROFILE_JSON_KEY, value),
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
