"""Typed context objects for the auto-resolve runtime.

``state.py`` owns the singleton instances and installs them into
``auto_resolve_pipeline`` so the pipeline can stay import-stable while using
explicit dependency and state objects instead of facade globals.
"""

from dataclasses import dataclass, field
import threading
from typing import Any


@dataclass(slots=True)
class AutoResolveSettings:
    retry_delay_sec: float
    min_interval_sec_default: float
    idle_sec_default: float
    download_pump_interval_sec: float
    download_scene_wait_sec: float
    download_completed_max_age_sec: float
    noncritical_interval_sec: float


@dataclass(slots=True)
class AutoResolveSharedState:
    in_flight: bool = False
    timer_running: bool = False

    download_timer_running: bool = False
    download_thread: Any = None
    download_active_job: Any = None
    download_pending_job: Any = None
    download_completed: Any = None
    download_request_counter: int = 0
    download_epoch: int = 0
    download_lock: Any = field(default_factory=threading.Lock)

    next_due_time: dict = field(default_factory=dict)
    last_camera_signature: dict = field(default_factory=dict)
    last_output_signature: dict = field(default_factory=dict)
    last_change_time: dict = field(default_factory=dict)
    last_resolve_time: dict = field(default_factory=dict)
    last_processed_signature: dict = field(default_factory=dict)
    pending_output_change: dict = field(default_factory=dict)
    trigger_last_signature: dict = field(default_factory=dict)

    noncritical_timer_running: bool = False
    noncritical_pending: dict = field(default_factory=dict)
    size_estimate_last_signature: dict = field(default_factory=dict)


@dataclass(slots=True)
class AutoResolveDownloadDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    resolve_trace: Any
    get_prefs: Any
    get_streaming_utils: Any
    clear_status_notices: Any
    scene_key: Any
    scene_from_key: Any
    read_scene_auto_resolve_state: Any
    write_scene_auto_resolve_state: Any
    build_auto_resolve_download_job: Any
    is_auto_resolve_download_job: Any
    job_field: Any
    job_set_field: Any
    normalize_texture_quality_mode: Any
    enforce_texture_quality_mode_for_account: Any
    camera_signature: Any
    output_resolution_signature: Any
    canonical_tiles: Any
    is_render_job_active: Any
    is_animation_playing: Any
    mark_manual_queued_resolve_error: Any
    read_scene_last_resolve_error: Any
    last_resolved_tiles: Any
    request_auto_resolve: Any
    estimate_download_bytes_for_visible_tiles: Any
    update_realtime_telemetry: Any
    tag_view3d_redraw: Any
    last_resolve_tile_count_key: str
    last_resolve_downloaded_mb_key: str
    last_resolve_downloaded_gb_key: str
    last_resolve_total_seconds_key: str
    viewport_scope_last_resolve_time: Any


@dataclass(slots=True)
class AutoResolveDecisionDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    resolve_trace: Any
    get_navigation_user_edit_last_touch: Any
    nav_camera_control_sync_grace_sec: float
    iter_scenes: Any
    scene_key: Any
    read_scene_auto_resolve_state: Any
    write_scene_auto_resolve_state: Any
    make_depsgraph_trigger_signature: Any
    depsgraph_trigger_output_signature: Any
    camera_signature: Any
    output_resolution_signature: Any
    current_view_scope: Any
    auto_resolve_scope_mode: Any
    resolve_scope_altitude_info: Any
    set_camera_inside_earth_warning: Any
    clear_camera_inside_earth_warning: Any
    active_view_signature: Any
    last_resolved_tiles: Any
    get_earth_object: Any
    get_tile_utils: Any
    canonical_tiles: Any
    is_render_job_active: Any
    is_animation_playing: Any
    is_navigation_user_edit_active: Any
    stop_auto_resolve_download_pipeline: Any
    schedule_auto_resolve_download: Any
    arm_auto_resolve_timer: Any
    enqueue_size_estimation: Any
    update_realtime_telemetry: Any
    handle_viewport_motion_optimization: Any
    handle_timeline_motion_optimization: Any
    handle_sunlight_motion_optimization: Any
    handle_view_scope_quality_transition: Any
    keyed_runtime_signature: Any
    timeline_signature: Any
    sunlight_signature: Any
    sync_idprops_from_props: Any
    force_restore_navigation_adaptive_state: Any
    viewport_opt_last_signature: Any
    sunlight_last_signature: Any
    viewport_scope_last: Any
    viewport_scope_last_resolve_time: Any
    last_realtime_telemetry: Any
    timeline_last_signature: Any
    frame_keyed_runtime_last_signature: Any
    nav_camera_control_last_signature: Any
    sunlight_object_name_cache: Any


@dataclass(slots=True)
class AutoResolveNonCriticalDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    get_prefs: Any
    normalize_texture_quality_mode: Any
    scene_key: Any
    scene_from_key: Any
    update_resolve_size_estimates: Any


@dataclass(slots=True)
class AutoResolveStateDeps:
    bpy: Any
    recoverable_exceptions: Any
    iter_scenes: Any
    normalize_texture_quality_mode: Any
    camera_signature: Any
    auto_resolve_scope_mode: Any
    active_view_signature: Any
    output_resolution_signature: Any
    request_auto_resolve: Any
    get_r2_source: Any


@dataclass(slots=True)
class AutoResolveDownloadContext:
    deps: AutoResolveDownloadDeps
    state: AutoResolveSharedState
    settings: AutoResolveSettings


@dataclass(slots=True)
class AutoResolveDecisionContext:
    deps: AutoResolveDecisionDeps
    state: AutoResolveSharedState
    settings: AutoResolveSettings


@dataclass(slots=True)
class AutoResolveNonCriticalContext:
    deps: AutoResolveNonCriticalDeps
    state: AutoResolveSharedState
    settings: AutoResolveSettings


@dataclass(slots=True)
class AutoResolveStateContext:
    deps: AutoResolveStateDeps
    state: AutoResolveSharedState
