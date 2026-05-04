"""Typed context objects for the view telemetry runtime.

``state.py`` owns the singleton context and installs it into
``view_telemetry`` so low-level telemetry helpers can stop depending on the
facade's ``globals()`` dictionary.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ViewTelemetryDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    import_recoverable_exceptions: Any
    get_prefs: Any
    write_realtime_view_diagnostics: Any
    camera_inside_earth_warning_key: str
    scene_key: Any
    suspend_adaptive_viewport_during_navigation: Any
    is_render_job_active: Any
    is_animation_playing: Any
    get_earth_object: Any
    get_tile_utils: Any
    get_streaming_utils: Any
    get_coverage_map: Any
    normalize_texture_quality_mode: Any
    request_auto_resolve: Any
    get_auto_resolve_in_flight: Any
    sunlight_object_name: str
    monotonic: Any
    real_earth_radius_m: float
    max_terrain_height_m: float
    dataset_mpp_base_d1: float
    live_safety_caution_ratio: float
    live_fallback_mpp_m: float
    live_z_levels: tuple[int, ...]
    resolve_estimate_full_bytes_key: str
    resolve_estimate_balanced_bytes_key: str
    resolve_estimate_preview_bytes_key: str
    resolve_estimate_full_credits_key: str
    resolve_estimate_balanced_credits_key: str
    resolve_estimate_preview_credits_key: str


@dataclass(slots=True)
class ViewTelemetryState:
    viewport_opt_last_signature: dict = field(default_factory=dict)
    sunlight_last_signature: dict = field(default_factory=dict)
    sunlight_object_name_cache: dict = field(default_factory=dict)
    viewport_scope_last: dict = field(default_factory=dict)
    viewport_scope_last_resolve_time: dict = field(default_factory=dict)
    last_realtime_telemetry: dict = field(default_factory=dict)
    timeline_last_signature: dict = field(default_factory=dict)


@dataclass(slots=True)
class ViewTelemetryContext:
    deps: ViewTelemetryDeps
    state: ViewTelemetryState
