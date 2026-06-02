"""Typed context objects for the handler runtime.

``state.py`` owns the singleton context and installs it into
``handler_runtime`` so Blender handler callbacks can stop depending on facade
``globals()`` directly.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class HandlerRuntimeDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    import_recoverable_exceptions: Any
    clear_resolve_in_flight: Any
    reset_navigation_shot_runtime_state: Any
    reset_navigation_camera_control_runtime_state: Any
    iter_scenes: Any
    set_planetka_logging: Any
    sync_idprops_from_props: Any
    get_earth_object: Any
    ensure_atmosphere_for_mode: Any


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


@dataclass(slots=True)
class HandlerRuntimeContext:
    deps: HandlerRuntimeDeps
    state: HandlerRuntimeState
