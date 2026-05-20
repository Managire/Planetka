import bpy
import importlib
import logging
import math
from types import SimpleNamespace
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from mathutils import Vector

from .extension_prefs import get_earth_object, get_prefs, read_saved_locations
from .geonames_db import get_cached_place_by_display, get_place_by_display, search_places
from .state import (
    is_navigation_or_camera_sync_suspended,
    request_next_navigation_apply_behavior,
    resume_navigation_camera_control_sync,
    resume_navigation_shot_updates,
    suspend_navigation_camera_control_sync,
    suspend_navigation_shot_updates,
    update_atmosphere_enabled,
    update_auto_resolve,
    update_debug_logging,
    update_navigation_shot,
    update_navigation_focal_length,
    update_show_earth_preview,
    update_sunlight_controls,
    update_sunlight_strength,
)
try:
    from .clouds_local import (
        _local_cloud_texture_items,
        update_enable_local_clouds,
        update_view_cloud_subdivision,
    )
    from .clouds_global import update_enable_global_clouds
    from .clouds_vdb import update_enable_vdb_clouds
except (ImportError, ModuleNotFoundError):
    def _local_cloud_texture_items(_self=None, _context=None):
        return (
            ("UNAVAILABLE", "Unavailable", "Cloud runtime is not included in this build"),
        )


    def update_enable_local_clouds(_self=None, _context=None):
        return None


    def update_view_cloud_subdivision(_self=None, _context=None):
        return None


    def update_enable_global_clouds(_self=None, _context=None):
        return None


    def update_enable_vdb_clouds(_self=None, _context=None):
        return None

NAV_DEFAULT_ALTITUDE_KM = 400.0
NAV_DEFAULT_AZIMUTH_DEG = 0.0
NAV_DEFAULT_TILT_DEG = 25.0
NAV_DEFAULT_ROLL_DEG = 0.0
PLACE_SEARCH_DEFAULT_ALTITUDE_KM = 60.0
PLACE_SEARCH_DEFAULT_TILT_DEG = 45.0
SEASONAL_TILT_PRESET_LIMIT_DEG = 23.44
logger = logging.getLogger(__name__)
_ANIM_PREVIEW_UPDATE_GUARD = False


def _safe_bpy_context():
    try:
        return getattr(bpy, "context", None)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None


def _safe_context_scene():
    context = _safe_bpy_context()
    if context is None:
        return None
    try:
        return getattr(context, "scene", None)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return None


def update_texture_quality_mode(self, context):
    scene = getattr(context, "scene", None) if context is not None else _safe_context_scene()
    try:
        if scene is not None and bool(scene.get("planetka_suppress_texture_quality_update_auto_resolve", False)):
            return
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    update_auto_resolve(self, context)


def _request_resolve_kill_switch():
    state_module_name = f"{__package__}.state" if __package__ else "state"
    try:
        state_module = importlib.import_module(state_module_name)
        stop_fn = getattr(state_module, "stop_auto_resolve_service", None)
        if callable(stop_fn):
            stop_fn()
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed stopping auto-resolve service from Hold kill switch", exc_info=True)

    r2_module_name = f"{__package__}.r2_source" if __package__ else "r2_source"
    try:
        r2_module = importlib.import_module(r2_module_name)
        cancel_fn = getattr(r2_module, "request_global_resolve_cancel", None)
        if callable(cancel_fn):
            cancel_fn()
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed signaling global resolve cancel from Hold kill switch", exc_info=True)


def _clear_resolve_kill_switch():
    r2_module_name = f"{__package__}.r2_source" if __package__ else "r2_source"
    try:
        r2_module = importlib.import_module(r2_module_name)
        clear_fn = getattr(r2_module, "clear_global_resolve_cancel", None)
        if callable(clear_fn):
            clear_fn()
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed clearing global resolve cancel state", exc_info=True)


def _get_hold_resolve(self):
    try:
        return not bool(getattr(self, "auto_resolve", True))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _set_hold_resolve(self, value):
    hold_enabled = bool(value)
    if hold_enabled:
        _request_resolve_kill_switch()
    else:
        _clear_resolve_kill_switch()

    target_auto_resolve = not hold_enabled
    try:
        current_auto_resolve = bool(getattr(self, "auto_resolve", True))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        current_auto_resolve = True
    if current_auto_resolve == target_auto_resolve:
        return

    try:
        # Route through the existing property so update callbacks and runtime sync stay intact.
        self.auto_resolve = target_auto_resolve
    except (RuntimeError, TypeError, ValueError, AttributeError):
        try:
            self["auto_resolve"] = bool(target_auto_resolve)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return
        update_auto_resolve(self, getattr(bpy, "context", None))


def _show_earth_preview_description():
    return "Show or hide the lightweight whole-Earth preview used while detailed textures are loading."


def _get_earth_radius_bu(self):
    try:
        stored_radius = float(self.get("earth_radius_bu", 0.0))
        if stored_radius > 1e-6:
            return stored_radius
    except (RuntimeError, TypeError, ValueError, AttributeError):
        stored_radius = 0.0

    earth = get_earth_object()
    if earth is not None:
        module_name = f"{__package__}.operators" if __package__ else "operators"
        try:
            operators = importlib.import_module(module_name)
            radius_fn = getattr(operators, "_earth_radius_blender_units", None)
            if callable(radius_fn):
                radius = float(radius_fn(earth))
                if radius > 1e-6:
                    try:
                        self["earth_radius_bu"] = float(radius)
                    except (RuntimeError, TypeError, ValueError, AttributeError):
                        pass
                    return radius
        except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed reading Earth radius", exc_info=True)

    try:
        return max(1e-6, float(self.get("earth_radius_bu", 2.0)))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return 2.0


def _set_earth_radius_bu(self, value):
    try:
        target = max(1e-6, float(value))
    except (RuntimeError, TypeError, ValueError):
        return

    self["earth_radius_bu"] = float(target)
    module_name = f"{__package__}.operators" if __package__ else "operators"
    try:
        operators = importlib.import_module(module_name)
        set_radius_fn = getattr(operators, "_set_planetka_earth_radius_bu", None)
        if callable(set_radius_fn):
            scene = getattr(self, "id_data", None)
            if scene is None or not isinstance(scene, bpy.types.Scene):
                scene = _safe_context_scene()
            set_radius_fn(scene, float(target))
            apply_clip_fn = getattr(operators, "_apply_radius_based_clipping", None)
            if callable(apply_clip_fn) and bool(getattr(self, "auto_adjust_clipping_values", True)):
                apply_clip_fn(scene, float(target))
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed applying Earth radius change", exc_info=True)


def _compute_max_proximity_altitude_km(scene, props):
    if scene is None or props is None:
        return None
    try:
        from .extension_prefs import get_earth_object
    except (ImportError, ModuleNotFoundError):
        logger.debug("Planetka: failed importing get_earth_object for proximity calculation", exc_info=True)
        return None

    earth_obj = get_earth_object()
    if earth_obj is None:
        return None

    module_name = f"{__package__}.operators" if __package__ else "operators"
    try:
        operators = importlib.import_module(module_name)
    except ImportError:
        return None

    radius_fn = getattr(operators, "_earth_radius_blender_units", None)
    max_prox_fn = getattr(operators, "_max_proximity_altitude_km", None)
    if not callable(radius_fn) or not callable(max_prox_fn):
        return None

    try:
        earth_radius_bu = float(radius_fn(earth_obj))
        lon_deg = float(getattr(props, "nav_longitude_deg", 0.0))
        lat_deg = float(getattr(props, "nav_latitude_deg", 0.0))
        max_km, _note = max_prox_fn(scene, earth_obj, earth_radius_bu, lon_deg, lat_deg)
        if max_km is None:
            return None
        return max(0.0, float(max_km))
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed computing max proximity altitude", exc_info=True)
        return None


def _update_anim_preset_defaults(self, context):
    global _ANIM_PREVIEW_UPDATE_GUARD
    if _ANIM_PREVIEW_UPDATE_GUARD:
        return
    scene = getattr(context, "scene", None) if context else None
    preset = str(getattr(self, "anim_camera_preset", "")).upper()
    if preset in {"PUSH_IN", "PULL_BACK"}:
        preset = "ZOOM"
    elif preset in {"ARC_LEFT", "ARC_RIGHT"}:
        preset = "ARC"
    elif preset == "FLYBY":
        preset = "NONE"
    if preset in {"", "NONE"}:
        return

    max_prox_km = _compute_max_proximity_altitude_km(scene, self)
    if max_prox_km is None or max_prox_km <= 0.0:
        max_prox_km = 100.0

    try:
        _ANIM_PREVIEW_UPDATE_GUARD = True
        if preset == "ZOOM":
            current_alt = max(0.0, float(getattr(self, "nav_altitude_km", 400.0)))
            default_zoom_end = max(current_alt * 2.0, max_prox_km * 4.0)
            self.anim_end_altitude_km = float(default_zoom_end)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed applying animation camera preset defaults", exc_info=True)
        return
    finally:
        _ANIM_PREVIEW_UPDATE_GUARD = False


def _update_anim_preview_keyframes(self, context):
    global _ANIM_PREVIEW_UPDATE_GUARD
    if _ANIM_PREVIEW_UPDATE_GUARD:
        return
    if is_navigation_or_camera_sync_suspended():
        return

    preset = str(getattr(self, "anim_camera_preset", "NONE") or "NONE").strip().upper()
    if preset in {"PUSH_IN", "PULL_BACK"}:
        preset = "ZOOM"
    elif preset in {"ARC_LEFT", "ARC_RIGHT"}:
        preset = "ARC"
    elif preset == "FLYBY":
        preset = "NONE"
    if preset in {"", "NONE"}:
        return

    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        scene = getattr(self, "id_data", None)
    if scene is None:
        return
    scene_props = getattr(scene, "planetka", None)
    if scene_props is None:
        return
    try:
        self_ptr = int(self.as_pointer())
        scene_ptr = int(scene_props.as_pointer())
        if self_ptr != scene_ptr:
            return
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # Fallback: continue when pointer comparison is not available.
        pass

    try:
        is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
        if callable(is_job_running) and bool(is_job_running("RENDER")):
            return
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return

    module_name = f"{__package__}.animation_tools" if __package__ else "animation_tools"
    try:
        animation_tools = importlib.import_module(module_name)
        apply_preview = getattr(animation_tools, "apply_cinematic_preview", None)
        if not callable(apply_preview):
            return
        _ANIM_PREVIEW_UPDATE_GUARD = True
        apply_preview(scene, self)
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed auto-updating cinematic keyframes from property change", exc_info=True)
    finally:
        _ANIM_PREVIEW_UPDATE_GUARD = False


def _update_navigation_shot_and_anim_preview(self, context):
    update_navigation_shot(self, context)


def _update_navigation_focal_and_anim_preview(self, context):
    update_navigation_focal_length(self, context)


def _update_anim_render_preset_defaults(self, _context):
    preset = str(getattr(self, "anim_render_preset", "") or "").upper()
    try:
        self.anim_render_dicing_rate = 1.0
        if preset == "MEMORY":
            self.anim_render_offscreen_scale = 8.0
            self.anim_render_persistent_data = False
        else:
            self.anim_render_offscreen_scale = 2.0
            self.anim_render_persistent_data = True
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed applying animation render preset defaults", exc_info=True)
        return


def _saved_locations_items(_self, _context):
    prefs = get_prefs()
    locations = read_saved_locations(prefs)
    if not locations:
        return [("__NONE__", "No Saved Locations", "Save a location first")]
    return [
        (
            loc["name"],
            loc["name"],
            f"Lat {loc['lat']:.4f}°, Lon {loc['lon']:.4f}°, Alt {loc['alt_km']:.2f} km",
        )
        for loc in locations
    ]


def _search_city_names(_self, _context, text):
    return search_places(text, max_results=20)


def _get_nav_city_search(self):
    return str(self.get("nav_city_search", ""))


def _sunlight_mid_morning_for_location(lon_deg, lat_deg):
    try:
        lon = math.radians(float(lon_deg))
        lat = math.radians(float(lat_deg))
        up = Vector(
            (
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            )
        )
        if up.length < 1e-9:
            return None
        up.normalize()
        east = Vector((-math.sin(lon), math.cos(lon), 0.0))
        if east.length < 1e-9:
            east = Vector((0.0, 1.0, 0.0))
        east.normalize()

        elev = math.radians(45.0)  # matches MID_MORNING preset
        sun_dir = (east * math.cos(elev)) + (up * math.sin(elev))
        if sun_dir.length < 1e-9:
            sun_dir = up
        sun_dir.normalize()

        sun_lon = math.degrees(math.atan2(float(sun_dir.y), float(sun_dir.x)))
        sun_lat = math.degrees(math.asin(max(-1.0, min(1.0, float(sun_dir.z)))))
        sun_lat = max(-SEASONAL_TILT_PRESET_LIMIT_DEG, min(SEASONAL_TILT_PRESET_LIMIT_DEG, float(sun_lat)))
        return float(sun_lon), float(sun_lat)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        logger.debug("Planetka: failed deriving mid-morning sunlight vector", exc_info=True)
        return None


def _set_nav_city_search(self, value):
    global _ANIM_PREVIEW_UPDATE_GUARD
    text = str(value or "")
    self["nav_city_search"] = text
    if not text:
        self["nav_city_selected_name"] = ""
        return

    place = get_cached_place_by_display(text)
    if not place:
        place = get_place_by_display(text)
    if not place:
        self["nav_city_selected_name"] = ""
        return

    scene_for_updates = getattr(self, "id_data", None)
    if scene_for_updates is None or not isinstance(scene_for_updates, bpy.types.Scene):
        scene_for_updates = _safe_context_scene()
    if scene_for_updates is not None:
        context_for_updates = SimpleNamespace(scene=scene_for_updates)
    else:
        context_for_updates = _safe_bpy_context()

    nav_suspended = False
    camera_sync_suspended = False
    try:
        _ANIM_PREVIEW_UPDATE_GUARD = True
        suspend_navigation_shot_updates()
        nav_suspended = True
        suspend_navigation_camera_control_sync()
        camera_sync_suspended = True
        self.nav_latitude_deg = float(place.get("latitude", 0.0))
        self.nav_longitude_deg = float(place.get("longitude", 0.0))
        self.nav_altitude_km = PLACE_SEARCH_DEFAULT_ALTITUDE_KM
        self.nav_azimuth_deg = NAV_DEFAULT_AZIMUTH_DEG
        self.nav_tilt_deg = PLACE_SEARCH_DEFAULT_TILT_DEG
        self.nav_roll_deg = NAV_DEFAULT_ROLL_DEG
        self["nav_city_selected_name"] = str(place.get("display_name", text))
        self["nav_city_search"] = str(place.get("display_name", text))
        if scene_for_updates is not None:
            request_next_navigation_apply_behavior(
                scene_for_updates,
                force_camera_view=True,
                sync_active_view_when_not_camera=False,
            )
        # Bulk updates are complete; release guards before single consolidated apply.
        _ANIM_PREVIEW_UPDATE_GUARD = False
        if nav_suspended:
            resume_navigation_shot_updates()
            nav_suspended = False
        update_navigation_shot(self, context_for_updates)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        return
    finally:
        if camera_sync_suspended:
            resume_navigation_camera_control_sync()
        if nav_suspended:
            resume_navigation_shot_updates()
        _ANIM_PREVIEW_UPDATE_GUARD = False

    # Always avoid new locations appearing at night: switch to "Mid-morning" sun.
    sun = _sunlight_mid_morning_for_location(self.nav_longitude_deg, self.nav_latitude_deg)
    if not sun:
        return
    try:
        # Set both values first, then run a single sunlight update.
        self["sunlight_longitude_deg"] = float(sun[0])
        self["sunlight_seasonal_tilt_deg"] = float(sun[1])
        update_sunlight_controls(self, context_for_updates)
    except (TypeError, ValueError, AttributeError):
        return


def _get_nav_city_selected_name(self):
    return str(self.get("nav_city_selected_name", ""))


def _get_waypoint_city_search(self):
    return str(self.get("city_search", ""))


def _set_waypoint_city_search(self, value):
    text = str(value or "")
    self["city_search"] = text
    if not text:
        self["city_selected_name"] = ""
        return

    place = get_cached_place_by_display(text)
    if not place:
        place = get_place_by_display(text)
    if not place:
        self["city_selected_name"] = ""
        return

    try:
        self.latitude_deg = float(place.get("latitude", 0.0))
        self.longitude_deg = float(place.get("longitude", 0.0))
        self.altitude_km = PLACE_SEARCH_DEFAULT_ALTITUDE_KM
        self.heading_deg = NAV_DEFAULT_AZIMUTH_DEG
        self.tilt_deg = PLACE_SEARCH_DEFAULT_TILT_DEG
        self.roll_deg = NAV_DEFAULT_ROLL_DEG
        selected = str(place.get("display_name", text))
        self["city_selected_name"] = selected
        self["city_search"] = selected
    except (TypeError, ValueError, AttributeError):
        return


def _get_waypoint_city_selected_name(self):
    return str(self.get("city_selected_name", ""))


class PlanetkaAnimationWaypoint(bpy.types.PropertyGroup):
    __slots__ = ()

    expanded: BoolProperty(
        name="Expanded",
        default=True,
        description="Show or hide waypoint details",
    )

    city_search: StringProperty(
        name="Place Search",
        description="Search for a city or place and apply it to this waypoint",
        search=_search_city_names,
        get=_get_waypoint_city_search,
        set=_set_waypoint_city_search,
    )

    city_selected_name: StringProperty(
        name="Selected Place",
        description="Display name of the place selected for this waypoint",
        get=_get_waypoint_city_selected_name,
    )

    latitude_deg: FloatProperty(
        name="Latitude",
        default=0.0,
        min=-1000000.0,
        max=1000000.0,
        soft_min=-90.0,
        soft_max=90.0,
        precision=2,
        description="Waypoint latitude in degrees",
    )

    longitude_deg: FloatProperty(
        name="Longitude",
        default=0.0,
        min=-1000000.0,
        max=1000000.0,
        soft_min=-180.0,
        soft_max=180.0,
        precision=2,
        description="Waypoint longitude in degrees",
    )

    altitude_km: FloatProperty(
        name="Altitude (km)",
        default=NAV_DEFAULT_ALTITUDE_KM,
        min=0.0,
        precision=2,
        description="Waypoint camera altitude above Earth in kilometers",
    )

    heading_deg: FloatProperty(
        name="Heading (°)",
        default=NAV_DEFAULT_AZIMUTH_DEG,
        precision=2,
        description="Waypoint camera heading around selected location",
    )

    tilt_deg: FloatProperty(
        name="Tilt (°)",
        default=NAV_DEFAULT_TILT_DEG,
        min=-90.0,
        max=90.0,
        precision=2,
        description="Waypoint camera tilt",
    )

    roll_deg: FloatProperty(
        name="Roll (°)",
        default=NAV_DEFAULT_ROLL_DEG,
        precision=2,
        description="Waypoint camera roll",
    )


class PlanetkaProperties(bpy.types.PropertyGroup):
    __slots__ = ()

    viewport_opt_suspend_subdivision: BoolProperty(
        name="Suspend Adaptive Subdivision While Navigating",
        default=True,
        description=(
            "Temporarily disables Adaptive Subdivision while the viewport/camera is moving, "
            "then restores it after motion stops"
        ),
        update=update_auto_resolve,
    )

    viewport_opt_subdivision_restore_delay_sec: FloatProperty(
        name="Subdivision Restore Delay (s)",
        default=0.5,
        min=0.1,
        max=2.0,
        precision=2,
        description="Wait time after motion stops before Adaptive Subdivision is restored in the viewport",
        update=update_auto_resolve,
    )

    show_earth_preview: BoolProperty(
        name="Show Earth Preview",
        default=True,
        description=_show_earth_preview_description(),
        update=update_show_earth_preview,
    )

    atmosphere_enabled: BoolProperty(
        name="Enable Atmosphere",
        default=False,
        description="Show or hide Planetka atmosphere effects",
        update=update_atmosphere_enabled,
    )

    enable_global_clouds: BoolProperty(
        name="Enable Global Clouds",
        default=False,
        description="Show or hide global cloud coverage in the viewport and render",
        update=update_enable_global_clouds,
    )

    enable_local_clouds: BoolProperty(
        name="Enable Local Clouds",
        default=False,
        description="Show or hide local cloud objects in the viewport and render",
        update=update_enable_local_clouds,
    )

    enable_vdb_clouds: BoolProperty(
        name="Enable VDB Clouds",
        default=False,
        description="Show or hide VDB cloud objects in the viewport and render",
        update=update_enable_vdb_clouds,
    )

    view_cloud_subdivision: BoolProperty(
        name="Cloud Final Look",
        default=False,
        description="Universal cloud mode: Final Look (on) or Preview (off) for Local and VDB clouds",
        update=update_view_cloud_subdivision,
    )

    local_cloud_texture: EnumProperty(
        name="Local Cloud Texture",
        description="Select a local cloud texture",
        items=_local_cloud_texture_items,
    )

    vdb_cloud_file: StringProperty(
        name="VDB Cloud File",
        subtype='FILE_PATH',
        description="VDB file used when adding a new VDB cloud",
        default="",
    )

    auto_resolve: BoolProperty(
        name="Auto Resolve",
        default=True,
        description="Automatically runs Resolve after camera movement when the visible tile set changes",
        update=update_auto_resolve,
    )

    hold_resolve: BoolProperty(
        name="Pause",
        description="Temporarily pause automatic resolve and download updates",
        default=False,
        get=_get_hold_resolve,
        set=_set_hold_resolve,
    )

    auto_resolve_idle_sec: FloatProperty(
        name="Auto Resolve Idle Delay (s)",
        default=0.5,
        min=0.1,
        max=3.0,
        precision=2,
        description="Time the camera must stay still before Auto Resolve triggers",
        update=update_auto_resolve,
    )

    auto_adjust_clipping_values: BoolProperty(
        name="Auto-adjust clipping",
        default=True,
        description="Automatically apply recommended Camera and viewport clipping values during Create Earth and Earth Radius changes",
    )

    nav_longitude_deg: FloatProperty(
        name="Longitude",
        default=0.0,
        min=-1000000.0,
        max=1000000.0,
        soft_min=-180.0,
        soft_max=180.0,
        step=1,
        precision=2,
        description="Navigation target longitude in degrees (soft range: -180 to 180)",
        update=_update_navigation_shot_and_anim_preview,
    )

    nav_latitude_deg: FloatProperty(
        name="Latitude",
        default=0.0,
        min=-1000000.0,
        max=1000000.0,
        soft_min=-90.0,
        soft_max=90.0,
        step=1,
        precision=2,
        description="Navigation target latitude in degrees (soft range: -90 to 90)",
        update=_update_navigation_shot_and_anim_preview,
    )

    nav_altitude_km: FloatProperty(
        name="Altitude (km)",
        default=NAV_DEFAULT_ALTITUDE_KM,
        min=0.0,
        precision=2,
        step=1,
        description="Navigation camera altitude above Earth surface in kilometers",
        update=_update_navigation_shot_and_anim_preview,
    )

    nav_azimuth_deg: FloatProperty(
        name="Heading",
        default=NAV_DEFAULT_AZIMUTH_DEG,
        step=1,
        precision=2,
        description="Navigation heading around selected location (0° = north, 90° = east)",
        update=_update_navigation_shot_and_anim_preview,
    )

    nav_tilt_deg: FloatProperty(
        name="Tilt",
        default=NAV_DEFAULT_TILT_DEG,
        min=-90.0,
        max=90.0,
        step=1,
        precision=2,
        description="Navigation tilt from top-down (0°) toward horizon while looking at the anchor",
        update=_update_navigation_shot_and_anim_preview,
    )

    nav_roll_deg: FloatProperty(
        name="Roll",
        default=NAV_DEFAULT_ROLL_DEG,
        step=1,
        precision=2,
        description="Navigation camera roll angle around the viewing axis",
        update=_update_navigation_shot_and_anim_preview,
    )

    nav_focal_length_mm: FloatProperty(
        name="Focal Length (mm)",
        default=50.0,
        min=1.0,
        max=5000.0,
        step=1,
        precision=2,
        description="Camera focal length in millimeters",
        update=_update_navigation_focal_and_anim_preview,
    )

    nav_custom_preset_altitude_km: FloatProperty(
        name="Custom Preset Altitude (km)",
        default=6000.0,
        min=0.0,
        precision=2,
        step=1,
        description="Altitude in kilometers used by the Custom entry in Altitude Presets",
    )

    earth_radius_bu: FloatProperty(
        name="Earth Radius",
        default=2.0,
        min=1e-6,
        soft_min=0.1,
        precision=4,
        description="Planetka Earth radius in Blender units",
        get=_get_earth_radius_bu,
        set=_set_earth_radius_bu,
    )

    nav_city_search: StringProperty(
        name="Place Search",
        description="Search for a city or place and move the camera there",
        search=_search_city_names,
        get=_get_nav_city_search,
        set=_set_nav_city_search,
    )

    nav_city_selected_name: StringProperty(
        name="Selected Place",
        description="Display name of the place selected from Place Search",
        get=_get_nav_city_selected_name,
    )

    nav_saved_location_name: StringProperty(
        name="Location Name",
        default="",
        description="Name used when saving the current Navigation location",
    )

    nav_saved_location_id: EnumProperty(
        name="Saved Locations",
        description="Saved Navigation locations",
        items=_saved_locations_items,
    )

    sunlight_longitude_deg: FloatProperty(
        name="Sun Longitude (°)",
        default=0.0,
        precision=2,
        description="Subsolar longitude in degrees; rotates the day/night terminator around Earth",
        update=update_sunlight_controls,
    )

    sunlight_strength: FloatProperty(
        name="Sun Strength",
        default=10.0,
        min=0.0,
        max=100000.0,
        precision=3,
        description="Light strength of Planetka Sunlight.",
        update=update_sunlight_strength,
    )

    sunlight_seasonal_tilt_deg: FloatProperty(
        name="Seasonal Tilt (°)",
        default=0.0,
        min=-23.44,
        max=23.44,
        soft_min=-23.44,
        soft_max=23.44,
        precision=2,
        description=(
            "Subsolar latitude (solar declination) in degrees. "
            "Range is limited to Earth's axial tilt (±23.44°)."
        ),
        update=update_sunlight_controls,
    )

    sunlight_last_preset: StringProperty(
        name="Last Sunlight Preset",
        default="",
        description="Internal: most recently applied sunlight preset",
        options={'HIDDEN'},
    )

    anim_camera_preset: EnumProperty(
        name="Cinematic Preset",
        items=(
            ("NONE", "Select Preset", "No animation preset selected"),
            ("ORBIT", "Circle", "Circle around current location"),
            ("ZOOM", "Zoom", "Animate from current camera altitude toward End Altitude"),
            ("ARC", "Arc", "Curved move around the target"),
            ("A_TO_B", "A to B", "Interpolate between saved camera views A and B"),
        ),
        default="NONE",
        description="Choose the camera movement used for preview and animation keyframes",
        update=_update_anim_preset_defaults,
    )

    anim_frame_start: IntProperty(
        name="Start Frame",
        default=1,
        min=0,
        description="Start frame used for cinematic preview and animation render workflows",
    )

    anim_frame_end: IntProperty(
        name="End Frame",
        default=250,
        min=1,
        description="End frame used for cinematic preview and animation render workflows",
    )

    anim_camera_strength: FloatProperty(
        name="Preset Strength",
        default=1.0,
        min=0.1,
        max=5.0,
        precision=2,
        description="Global multiplier for cinematic movement intensity",
    )

    anim_motion_curve: EnumProperty(
        name="Motion Curve",
        items=(
            ("LINEAR", "Linear", "Constant speed camera interpolation"),
            ("EASE_IN", "Ease In", "Starts slowly and accelerates"),
            ("EASE_OUT", "Ease Out", "Starts fast and slows near the end"),
            ("EASE_IN_OUT", "Ease In-Out", "Smooth acceleration and deceleration"),
        ),
        default="EASE_IN_OUT",
        description="Interpolation style used for cinematic preview keyframes",
    )

    anim_start_altitude_km: FloatProperty(
        name="Start Altitude (km)",
        default=100.0,
        min=0.0,
        max=50000.0,
        precision=2,
        description="Legacy start altitude value kept for compatibility with older animation files",
    )

    anim_end_altitude_km: FloatProperty(
        name="End Altitude (km)",
        default=400.0,
        min=0.0,
        max=50000.0,
        precision=2,
        description="End altitude for the Zoom cinematic preset",
    )

    anim_orbit_degrees: FloatProperty(
        name="Orbit Degrees",
        default=120.0,
        min=1.0,
        max=360.0,
        precision=2,
        description="Total heading rotation in degrees for Circle/Orbit-style movement",
    )

    anim_circle_direction: EnumProperty(
        name="Circle Direction",
        items=(
            ("CLOCKWISE", "Clockwise", "Rotate heading clockwise around the anchor"),
            ("COUNTERCLOCKWISE", "Counterclockwise", "Rotate heading counterclockwise around the anchor"),
        ),
        default="CLOCKWISE",
        description="Direction used by the Circle cinematic preset",
    )

    anim_flyby_degrees: FloatProperty(
        name="Arc Travel Degrees",
        default=1.0,
        min=0.1,
        max=120.0,
        precision=2,
        description="Legacy angular travel distance value kept for compatibility with older animation files",
    )

    anim_flyby_camera_heading_deg: FloatProperty(
        name="Legacy Camera Heading (°)",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        precision=2,
        description="Legacy camera heading offset kept for compatibility with older animation files",
    )

    anim_zoom_rotate_degrees: FloatProperty(
        name="Zoom Rotate (°)",
        default=20.0,
        min=-360.0,
        max=360.0,
        precision=2,
        description="Additional camera roll (twist) applied over Zoom movement",
    )

    anim_prepare_max_segments: IntProperty(
        name="Max Segments",
        default=99,
        min=1,
        max=99,
        description="Maximum number of prepared segment meshes allowed in Make Ready mode",
    )

    anim_prepare_max_textures_mb: FloatProperty(
        name="Max Textures (MB)",
        default=4096.0,
        min=0.0,
        max=262144.0,
        precision=1,
        description="Maximum total texture footprint for prepared animation assets in MB (0 = unlimited)",
    )

    anim_render_preset: EnumProperty(
        name="Animation Render Preset",
        items=(
            ("SPEED", "Speed Optimized", "Keeps caches for faster segment rendering (uses more memory)"),
            ("MEMORY", "Memory Optimized", "More aggressive offloading between segments (slower, lower peak memory)"),
        ),
        default="SPEED",
        description="Preset that balances segmented animation render speed versus memory use",
        update=_update_anim_render_preset_defaults,
    )

    anim_render_dicing_rate: FloatProperty(
        name="Dicing Rate Render",
        default=1.0,
        min=0.1,
        max=64.0,
        precision=2,
        description="Cycles render-time dicing rate for segmented animation (lower = finer subdivision)",
    )

    anim_render_offscreen_scale: FloatProperty(
        name="Offscreen Scale",
        default=2.0,
        min=0.1,
        max=64.0,
        precision=2,
        description="Cycles offscreen dicing scale for segmented animation (lower = finer subdivision)",
    )

    anim_render_persistent_data: BoolProperty(
        name="Persistent Data",
        default=True,
        description="Reuse render data between frames for speed (can increase memory usage)",
    )

    anim_ab_a_location: FloatVectorProperty(
        name="View A Location",
        size=3,
        default=(0.0, 0.0, 0.0),
        options={'HIDDEN'},
    )

    anim_ab_a_rotation: FloatVectorProperty(
        name="View A Rotation",
        size=3,
        default=(0.0, 0.0, 0.0),
        options={'HIDDEN'},
    )

    anim_ab_a_valid: BoolProperty(
        name="View A Valid",
        default=False,
        options={'HIDDEN'},
    )

    anim_ab_a_capture_frame: IntProperty(
        name="View A Capture Frame",
        default=0,
        min=0,
        options={'HIDDEN'},
    )

    anim_ab_a_capture_timecode: StringProperty(
        name="View A Capture Timecode",
        default="",
        options={'HIDDEN'},
    )

    anim_ab_b_location: FloatVectorProperty(
        name="View B Location",
        size=3,
        default=(0.0, 0.0, 0.0),
        options={'HIDDEN'},
    )

    anim_ab_b_rotation: FloatVectorProperty(
        name="View B Rotation",
        size=3,
        default=(0.0, 0.0, 0.0),
        options={'HIDDEN'},
    )

    anim_ab_b_valid: BoolProperty(
        name="View B Valid",
        default=False,
        options={'HIDDEN'},
    )

    anim_ab_b_capture_frame: IntProperty(
        name="View B Capture Frame",
        default=0,
        min=0,
        options={'HIDDEN'},
    )

    anim_ab_b_capture_timecode: StringProperty(
        name="View B Capture Timecode",
        default="",
        options={'HIDDEN'},
    )

    anim_waypoints: CollectionProperty(
        name="Waypoints",
        type=PlanetkaAnimationWaypoint,
        description="Legacy waypoint data kept for compatibility with older animation files",
    )

    anim_waypoint_active_index: IntProperty(
        name="Active Waypoint",
        default=0,
        min=0,
        description="Active waypoint index for editing operations",
    )

    texture_quality_mode: EnumProperty(
        name="Texture Quality",
        items=(
            (
                "PREVIEW",
                "Preview",
                "Fast lower-resolution streaming textures for preview work",
            ),
            (
                "BALANCED",
                "Balanced",
                "Medium-resolution streaming textures for normal work",
            ),
            (
                "FULL",
                "Full Quality",
                "Highest quality streaming textures",
            ),
        ),
        default="PREVIEW",
        description="Choose streaming texture quality",
        update=update_texture_quality_mode,
    )

    resolution_bias: FloatProperty(
        name="Resolution Bias",
        default=0.0,
        min=-2.0,
        max=2.0,
        precision=2,
        description="Bias Resolve tile detail selection (higher = finer detail, higher memory use)",
        update=update_auto_resolve,
    )

    lock_resolve_during_animation: BoolProperty(
        name="Lock Resolve During Animation",
        default=True,
        description="Prevent Resolve updates while timeline playback is running",
        update=update_auto_resolve,
    )

    debug_logging: BoolProperty(
        name="Debug Logging",
        default=False,
        description="Enable verbose Planetka diagnostic logging in Blender's system console",
        update=update_debug_logging,
    )
