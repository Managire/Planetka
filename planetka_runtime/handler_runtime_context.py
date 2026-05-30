"""Typed context objects for the handler runtime.

``state.py`` owns the singleton context and installs it into
``handler_runtime`` so Blender handler callbacks can stop depending on facade
``globals()`` directly.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HandlerRuntimeDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    import_recoverable_exceptions: Any
    clear_auto_resolve_in_flight: Any
    reset_navigation_shot_runtime_state: Any
    reset_navigation_camera_control_runtime_state: Any
    force_restore_navigation_adaptive_state: Any
    mark_auto_resolve_dirty: Any
    request_auto_resolve: Any
    self_heal_missing_cache_images_for_render: Any
    iter_scenes: Any
    set_planetka_logging: Any
    migrate_scene_schema: Any
    legacy_scene_idprops: Any
    sync_idprops_from_props: Any
    is_navigation_user_edit_active: Any
    scene_has_keyed_runtime_path: Any
    keyed_runtime_all_prop_paths: Any
    keyed_runtime_nav_prop_paths: Any
    keyed_runtime_focal_prop_paths: Any
    keyed_runtime_sun_prop_paths: Any
    is_render_job_active: Any
    is_animation_playing: Any
    get_earth_object: Any
    sync_navigation_controls_from_scene_camera: Any
    can_auto_resolve_run: Any
    ensure_auto_resolve_service_running: Any
    update_realtime_telemetry: Any
    is_resolve_pipeline_busy: Any
    make_depsgraph_trigger_signature: Any
    handle_timeline_motion_optimization: Any
    handle_viewport_motion_optimization: Any
    camera_signature: Any
    handle_sunlight_motion_optimization: Any
    mark_auto_resolve_from_depsgraph_trigger: Any
    keyed_runtime_signature: Any
    scene_key: Any
    recover_missing_cache_image_paths_to_fallback: Any
    schedule_load_recovery_resolve: Any
    import_module: Any
    get_prefs: Any
    auth_is_authenticated_attr: str
    package_name: str
    account_panel_default_collapsed_key: str


@dataclass(slots=True)
class HandlerRuntimeState:
    render_job_active: bool = False
    render_job_epoch: int = 0
    render_job_last_ended_epoch: int = 0
    render_job_last_ended_at: float = 0.0
    render_job_last_cancelled_epoch: int = 0
    render_job_last_progress_at: float = 0.0
    render_job_last_frame_written_at: float = 0.0
    render_job_last_frame_written: int = -1
    logging_syncing: bool = False
    frame_keyed_runtime_last_signature: dict = field(default_factory=dict)


@dataclass(slots=True)
class HandlerRuntimeContext:
    deps: HandlerRuntimeDeps
    state: HandlerRuntimeState
