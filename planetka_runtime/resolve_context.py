"""Typed context objects for Planetka's manual resolve download pipeline."""

from dataclasses import dataclass, field
import threading
from typing import Any


@dataclass(slots=True)
class ResolveSettings:
    download_pump_interval_sec: float
    download_scene_wait_sec: float
    download_completed_max_age_sec: float


@dataclass(slots=True)
class ResolveSharedState:
    in_flight: bool = False
    download_timer_running: bool = False
    download_thread: Any = None
    download_active_job: Any = None
    download_completed: Any = None
    download_request_counter: int = 0
    download_epoch: int = 0
    download_lock: Any = field(default_factory=threading.Lock)


@dataclass(slots=True)
class ResolveDownloadDeps:
    bpy: Any
    logger: Any
    recoverable_exceptions: Any
    resolve_trace: Any
    get_prefs: Any
    get_authorized_headers: Any
    get_streaming_utils: Any
    clear_status_notices: Any
    scene_key: Any
    scene_from_key: Any
    build_resolve_download_job: Any
    is_resolve_download_job: Any
    job_field: Any
    job_set_field: Any
    normalize_texture_quality_mode: Any
    camera_signature: Any
    output_resolution_signature: Any
    canonical_tiles: Any
    is_render_job_active: Any
    is_animation_playing: Any
    estimate_download_bytes_for_visible_tiles: Any
    tag_view3d_redraw: Any
    last_resolve_tile_count_key: str
    last_resolve_downloaded_mb_key: str
    last_resolve_total_seconds_key: str


@dataclass(slots=True)
class ResolveStateDeps:
    bpy: Any
    recoverable_exceptions: Any
    iter_scenes: Any
    normalize_texture_quality_mode: Any
    get_r2_source: Any
    is_render_job_active: Any


@dataclass(slots=True)
class ResolveDownloadContext:
    deps: ResolveDownloadDeps
    state: ResolveSharedState
    settings: ResolveSettings


@dataclass(slots=True)
class ResolveStateContext:
    deps: ResolveStateDeps
    state: ResolveSharedState
