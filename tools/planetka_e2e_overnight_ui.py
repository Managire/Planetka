"""Broad Planetka overnight UI-mode end-to-end test.

Recommended usage:
  Reuse current authenticated Blender profile:
    /Applications/Blender5.0.app/Contents/MacOS/Blender \
      --python tools/planetka_e2e_overnight_ui.py

  Clean session with API key bootstrap:
    PLANETKA_AUTH_DEVICE_ID=1de81a60-831d-4aac-9e66-e86af91a900b \
    PLANETKA_API_KEY_PATH=/absolute/path/to/api_key.json \
    /Applications/Blender5.0.app/Contents/MacOS/Blender --factory-startup \
      --python tools/planetka_e2e_overnight_ui.py

Quick validation mode:
  PLANETKA_E2E_SMOKE=1 PLANETKA_AUTH_DEVICE_ID=1de81a60-831d-4aac-9e66-e86af91a900b \
    PLANETKA_API_KEY_PATH=/absolute/path/to/api_key.json \
    /Applications/Blender5.0.app/Contents/MacOS/Blender --factory-startup \
      --python tools/planetka_e2e_overnight_ui.py

The script writes all visual outputs and a structured JSON report into /Volumes/SSDA/Renders.
It covers:
- current supported in-Blender operators and user-facing settings sweeps
- still renders across quality levels and engines
- Quick Preview animation renders
- real Final Animation Render modal operator in Blender UI mode
- rogue-user tamper phase: destructive local scene edits + cache-file breakage
- backend abuse simulation via tools/worker_abuse_simulation.py
- smoke mode via PLANETKA_E2E_SMOKE=1 (reduces case counts for script validation only)

Intentionally skipped from automation because they have external side effects:
- account_login / account_upgrade / account_contact (browser opening)
- account_logout (destroys session)
- update_now (mutates installed addon)
- report_bug (sends support payload / opens mail)
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_RECOVERABLE_EXCEPTIONS

import bpy
from mathutils import Quaternion

from planetka_e2e_common import (
    COUNTRY_HINT_BY_CITY,
    DEFAULT_PLACE_QUERIES,
    E2EError,
    analyze_render_image,
    analyze_png_directory,
    configure_cycles,
    configure_eevee,
    configure_png_output,
    create_earth_and_wait,
    drain_queued_resolve,
    enable_module,
    ensure_authenticated,
    ensure_camera,
    ensure_standard_world,
    find_view3d_override,
    import_submodule,
    list_pngs,
    log,
    output_session,
    purge_planetka_data,
    render_animation,
    render_still,
    resolve_textures,
    scene_health_operator_available,
    search_place,
    set_navigation,
    timestamp_slug,
    wait_for_geonames_ready,
    write_json,
)

TAG = "[Planetka Overnight E2E]"
DEFAULT_SEED = 20260425
FINAL_RENDER_TIMEOUT_SEC = 1800.0
SHORT_WAIT_SEC = 0.25
BLENDER_BIN_CANDIDATES = (
    os.environ.get("PLANETKA_RELEASE_GATE_BLENDER_BIN"),
    os.environ.get("BLENDER_BIN"),
    "/Applications/Blender5.0.app/Contents/MacOS/Blender",
    "/Applications/Blender.app/Contents/MacOS/Blender",
)


def _wrap_tile_x(x):
    return int(x) % 360


def _clamp_tile_y(y):
    return int(max(0, min(179, int(y))))


def _s2_tile_name(x, y, z=1, d=1):
    return f"x{_wrap_tile_x(x):03d}_y{_clamp_tile_y(y):03d}_z{int(z):03d}_d{int(d):03d}"


def _s2_tile_block(x0, y0, width, height, z=1, d=1):
    tiles = []
    for dy in range(int(height)):
        for dx in range(int(width)):
            tiles.append(_s2_tile_name(int(x0) + dx, int(y0) + dy, z=z, d=d))
    return tiles


def _tile_block_nav(x0, y0, width, height, *, altitude_km, azimuth_deg=28.0, tilt_deg=42.0, roll_deg=0.0):
    center_lon = float(int(x0) + (float(width) / 2.0) - 180.0)
    center_lat = float(int(y0) + (float(height) / 2.0) - 90.0)
    return {
        "nav_longitude_deg": center_lon,
        "nav_latitude_deg": center_lat,
        "nav_altitude_km": float(altitude_km),
        "nav_azimuth_deg": float(azimuth_deg),
        "nav_tilt_deg": float(tilt_deg),
        "nav_roll_deg": float(roll_deg),
    }

EXTERNAL_SKIPS = {
    "planetka.account_login": "Opens browser",
    "planetka.account_open_login": "Re-authenticates live account",
    "planetka.account_logout": "Destroys current session",
    "planetka.account_upgrade": "Opens browser",
    "planetka.account_contact": "Opens browser",
    "planetka.update_now": "Mutates installed addon",
    "planetka.report_bug": "Sends support payload / mail draft",
}

BOOL_SWEEPS = {
    "viewport_opt_suspend_subdivision": [False, True],
    "viewport_opt_active_view_coarse_textures": [False, True],
    "show_earth_preview": [False, True],
    "auto_resolve": [False, True],
    "auto_adjust_clipping_values": [False, True],
    "lock_resolve_during_animation": [False, True],
    "debug_logging": [False, True],
    "anim_render_persistent_data": [False, True],
}

NUMERIC_SWEEPS = {
    "viewport_opt_subdivision_restore_delay_sec": [0.1, 0.5, 2.0],
    "auto_resolve_idle_sec": [0.1, 0.5, 3.0],
    "nav_altitude_km": [30.0, 120.0, 1200.0],
    "nav_azimuth_deg": [0.0, 45.0, 180.0],
    "nav_tilt_deg": [15.0, 45.0, 75.0],
    "nav_roll_deg": [-15.0, 0.0, 15.0],
    "nav_focal_length_mm": [24.0, 50.0, 135.0],
    "earth_radius_bu": [1.0, 2.0, 4.0],
    "sunlight_longitude_deg": [-135.0, 0.0, 135.0],
    "sunlight_strength": [2.0, 10.0, 30.0],
    "sunlight_seasonal_tilt_deg": [-23.0, 0.0, 23.0],
    "anim_end_altitude_km": [30.0, 150.0, 800.0],
    "anim_orbit_degrees": [20.0, 60.0, 160.0],
    "anim_zoom_rotate_degrees": [-30.0, 0.0, 30.0],
    "anim_prepare_max_segments": [4, 8, 16],
    "anim_prepare_max_textures_mb": [256.0, 1024.0, 4096.0],
    "resolution_bias": [-1.0, 0.0, 1.0],
}

ENUM_SWEEPS = (
    "texture_quality_mode",
    "anim_camera_preset",
    "anim_motion_curve",
    "anim_circle_direction",
    "anim_render_preset",
)

STILL_CASES = (
    {
        "id": "still_preview_eevee_reykjavik",
        "engine": "EEVEE",
        "quality": "PREVIEW",
        "query": "Reykjavik",
        "country_hint": "IS",
        "sunlight_preset": "MID_MORNING",
        "resolution": (1280, 720),
        "nav": {"nav_altitude_km": 80.0, "nav_azimuth_deg": 22.0, "nav_tilt_deg": 50.0, "nav_roll_deg": 0.0},
        "earth_radius_bu": 2.0,
        "resolution_bias": 0.0,
    },
    {
        "id": "still_preview_eevee_singapore",
        "engine": "EEVEE",
        "quality": "PREVIEW",
        "query": "Singapore",
        "country_hint": "SG",
        "sunlight_preset": "MID_AFTERNOON",
        "resolution": (1280, 720),
        "nav": {"nav_altitude_km": 80.0, "nav_azimuth_deg": 35.0, "nav_tilt_deg": 45.0, "nav_roll_deg": 0.0},
        "earth_radius_bu": 2.0,
        "resolution_bias": 0.0,
    },
    {
        "id": "still_full_eevee_pinkrisk_3tiles",
        "engine": "EEVEE",
        "quality": "FULL",
        "selected_label": "Explicit 3-tile override",
        "sunlight_preset": "MID_AFTERNOON",
        "resolution": (1280, 720),
        "nav": _tile_block_nav(179, 90, 3, 1, altitude_km=320.0, azimuth_deg=18.0, tilt_deg=44.0),
        "tiles_override": _s2_tile_block(179, 90, 3, 1),
        "earth_radius_bu": 2.0,
        "resolution_bias": 0.25,
        "risk_category": "pink_texture_large_resolve",
    },
    {
        "id": "still_full_eevee_pinkrisk_4tiles",
        "engine": "EEVEE",
        "quality": "FULL",
        "selected_label": "Explicit 4-tile override",
        "sunlight_preset": "MID_AFTERNOON",
        "resolution": (1280, 720),
        "nav": _tile_block_nav(179, 89, 2, 2, altitude_km=420.0, azimuth_deg=22.0, tilt_deg=40.0),
        "tiles_override": _s2_tile_block(179, 89, 2, 2),
        "earth_radius_bu": 2.0,
        "resolution_bias": 0.4,
        "risk_category": "pink_texture_large_resolve",
    },
    {
        "id": "still_full_eevee_pinkrisk_12tiles",
        "engine": "EEVEE",
        "quality": "FULL",
        "selected_label": "Explicit 12-tile override",
        "sunlight_preset": "MID_AFTERNOON",
        "resolution": (1280, 720),
        "nav": _tile_block_nav(178, 88, 4, 3, altitude_km=880.0, azimuth_deg=24.0, tilt_deg=34.0),
        "tiles_override": _s2_tile_block(178, 88, 4, 3),
        "earth_radius_bu": 2.0,
        "resolution_bias": 0.75,
        "risk_category": "pink_texture_large_resolve",
    },
    {
        "id": "still_full_eevee_cape_town",
        "engine": "EEVEE",
        "quality": "FULL",
        "query": "Cape Town",
        "country_hint": "ZA",
        "sunlight_preset": "SUNSET",
        "resolution": (1280, 720),
        "nav": {"nav_altitude_km": 120.0, "nav_azimuth_deg": 48.0, "nav_tilt_deg": 40.0, "nav_roll_deg": -4.0},
        "earth_radius_bu": 2.6,
        "resolution_bias": 0.5,
    },
    {
        "id": "still_preview_cycles_lima",
        "engine": "CYCLES",
        "quality": "PREVIEW",
        "query": "Lima",
        "country_hint": "PE",
        "sunlight_preset": "NOON",
        "resolution": (960, 540),
        "nav": {"nav_altitude_km": 150.0, "nav_azimuth_deg": 10.0, "nav_tilt_deg": 38.0, "nav_roll_deg": 0.0},
        "earth_radius_bu": 2.0,
        "resolution_bias": -0.25,
    },
    {
        "id": "still_full_cycles_wellington",
        "engine": "CYCLES",
        "quality": "FULL",
        "query": "Wellington",
        "country_hint": "NZ",
        "sunlight_preset": "LATE_AFTERNOON",
        "resolution": (960, 540),
        "nav": {"nav_altitude_km": 200.0, "nav_azimuth_deg": 28.0, "nav_tilt_deg": 42.0, "nav_roll_deg": 3.0},
        "earth_radius_bu": 2.2,
        "resolution_bias": 0.75,
    },
)

QUICK_PREVIEW_CASES = (
    {
        "id": "quickpreview_orbit_eevee",
        "preset": "ORBIT",
        "engine": "EEVEE",
        "query": "Bratislava",
        "country_hint": "SK",
        "frames": 6,
        "motion_curve": "EASE_IN_OUT",
        "orbit_degrees": 55.0,
        "circle_direction": "CLOCKWISE",
        "nav": {"nav_altitude_km": 100.0, "nav_azimuth_deg": 20.0, "nav_tilt_deg": 45.0, "nav_roll_deg": 0.0},
    },
    {
        "id": "quickpreview_zoom_eevee",
        "preset": "ZOOM",
        "engine": "EEVEE",
        "query": "Auckland",
        "country_hint": "NZ",
        "frames": 6,
        "motion_curve": "EASE_OUT",
        "end_altitude_km": 35.0,
        "zoom_rotate_degrees": 18.0,
        "nav": {"nav_altitude_km": 250.0, "nav_azimuth_deg": 12.0, "nav_tilt_deg": 50.0, "nav_roll_deg": 0.0},
    },
    {
        "id": "quickpreview_arc_eevee",
        "preset": "ARC",
        "engine": "EEVEE",
        "query": "Lima",
        "country_hint": "PE",
        "frames": 6,
        "motion_curve": "LINEAR",
        "orbit_degrees": 35.0,
        "nav": {"nav_altitude_km": 180.0, "nav_azimuth_deg": 40.0, "nav_tilt_deg": 38.0, "nav_roll_deg": -4.0},
    },
    {
        "id": "quickpreview_a_to_b_eevee",
        "preset": "A_TO_B",
        "engine": "EEVEE",
        "frames": 6,
        "motion_curve": "EASE_IN",
        "view_a": {"query": "Reykjavik", "country_hint": "IS", "nav": {"nav_altitude_km": 120.0, "nav_azimuth_deg": 20.0, "nav_tilt_deg": 50.0, "nav_roll_deg": 0.0}},
        "view_b": {"query": "Cape Town", "country_hint": "ZA", "nav": {"nav_altitude_km": 120.0, "nav_azimuth_deg": 65.0, "nav_tilt_deg": 42.0, "nav_roll_deg": 0.0}},
    },
)

FINAL_ANIMATION_CASES = (
    {
        "id": "final_orbit_eevee_speed",
        "preset": "ORBIT",
        "engine": "EEVEE",
        "frames": 6,
        "query": "Singapore",
        "country_hint": "SG",
        "motion_curve": "EASE_IN_OUT",
        "orbit_degrees": 45.0,
        "circle_direction": "COUNTERCLOCKWISE",
        "render_preset": "SPEED",
        "nav": {"nav_altitude_km": 120.0, "nav_azimuth_deg": 30.0, "nav_tilt_deg": 45.0, "nav_roll_deg": 0.0},
    },
    {
        "id": "final_zoom_eevee_memory",
        "preset": "ZOOM",
        "engine": "EEVEE",
        "frames": 6,
        "query": "Wellington",
        "country_hint": "NZ",
        "motion_curve": "EASE_OUT",
        "end_altitude_km": 45.0,
        "zoom_rotate_degrees": 22.0,
        "render_preset": "MEMORY",
        "nav": {"nav_altitude_km": 220.0, "nav_azimuth_deg": 18.0, "nav_tilt_deg": 48.0, "nav_roll_deg": 0.0},
    },
    {
        "id": "final_a_to_b_cycles_speed",
        "preset": "A_TO_B",
        "engine": "CYCLES",
        "frames": 4,
        "motion_curve": "EASE_IN_OUT",
        "render_preset": "SPEED",
        "view_a": {"query": "Auckland", "country_hint": "NZ", "nav": {"nav_altitude_km": 140.0, "nav_azimuth_deg": 10.0, "nav_tilt_deg": 50.0, "nav_roll_deg": 0.0}},
        "view_b": {"query": "Cape Town", "country_hint": "ZA", "nav": {"nav_altitude_km": 160.0, "nav_azimuth_deg": 70.0, "nav_tilt_deg": 42.0, "nav_roll_deg": 2.0}},
    },
)


class OvernightRunner:
    def __init__(self):
        self.smoke_mode = str(os.environ.get("PLANETKA_E2E_SMOKE") or "").strip().lower() in {"1", "true", "yes", "on"}
        self.seed = int(os.environ.get("PLANETKA_E2E_SEED") or DEFAULT_SEED)
        self.random = random.Random(self.seed)
        self.session_dir = output_session("planetka_e2e_overnight")
        self.report_path = self.session_dir / "planetka_e2e_overnight_report.json"
        self.report = {
            "status": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session_dir": str(self.session_dir),
            "seed": self.seed,
            "smoke_mode": bool(self.smoke_mode),
            "account": {},
            "skipped_external_ops": dict(EXTERNAL_SKIPS),
            "operator_results": [],
            "property_sweeps": [],
            "still_cases": [],
            "quick_preview_cases": [],
            "final_animation_cases": [],
            "rogue_phase": {},
            "notes": [],
        }
        self.base_module = ""
        self.auth = None
        self.extension_prefs = None
        self.geonames = None
        self.state = None
        self.validation = None
        self.operators = None
        self.prefs = None
        self.scene = None
        self.props = None
        self.available_engines = set()
        self.active_final_case = None
        self.still_cases = self._select_cases(STILL_CASES, smoke_count=5)
        self.quick_preview_cases = self._select_cases(QUICK_PREVIEW_CASES, smoke_count=2)
        self.final_animation_cases = self._select_cases(FINAL_ANIMATION_CASES, smoke_count=1)
        self.pending_final_cases = [dict(case) for case in self.final_animation_cases]
        self.final_phase_rebased = False
        self.active_final_case_deadline = 0.0
        self.active_final_case_started_at = 0.0
        self.active_final_case_seen_running = False
        self.active_final_case_last_frame_count = 0
        self.active_final_case_runtime_quiesced = False
        self.phase_methods = [
            self._setup_environment,
            self._run_preflight,
            self._run_property_sweeps,
            self._run_functional_ops,
            self._run_still_cases,
            self._run_quick_preview_cases,
            self._run_rogue_phase,
            self._run_backend_abuse_phase,
            self._run_final_animation_cases,
            self._finalize_success,
        ]
        self.phase_index = 0
        if self.smoke_mode:
            self.report["notes"].append("PLANETKA_E2E_SMOKE enabled: reduced overnight case counts for validation.")

    def _write_report(self):
        write_json(self.report_path, self.report)

    def _select_cases(self, cases, smoke_count=1):
        selected = [dict(case) for case in (cases or ())]
        if self.smoke_mode:
            return selected[: max(1, int(smoke_count))]
        return selected

    def _record_operator(self, name, result=None, error="", details=None):
        entry = {
            "operator": str(name),
            "result": list(result or []),
            "error": str(error or ""),
            "details": details or {},
        }
        self.report["operator_results"].append(entry)
        return entry

    def _call_operator(self, name, **kwargs):
        op = getattr(bpy.ops.planetka, name)
        try:
            result = op(**kwargs)
        except Exception as exc:
            self._record_operator(f"planetka.{name}", error=str(exc), details={"kwargs": kwargs})
            raise
        self._record_operator(f"planetka.{name}", result=result, details={"kwargs": kwargs})
        return result

    def _record_prop(self, name, value, stored_value=None):
        self.report["property_sweeps"].append(
            {
                "property": str(name),
                "input": value,
                "stored": stored_value if stored_value is not None else getattr(self.props, name, None),
            }
        )

    def _scene_health_summary(self):
        payload = self.validation.collect_scene_health_data(bpy.context)
        return {
            "errors": list(payload.get("errors", ()) or ()),
            "warnings": list(payload.get("warnings", ()) or ()),
            "info": list(payload.get("info", ()) or ()),
            "check_count": int(len(list(payload.get("checks", ()) or ()))),
        }

    def _configure_engine(self, engine_name):
        if str(engine_name).upper() == "CYCLES":
            return configure_cycles(self.scene)
        return {"engine": configure_eevee(self.scene)}

    def _refresh_available_engines(self):
        available = set()
        try:
            available = {
                str(key).upper()
                for key in self.scene.render.bl_rna.properties["engine"].enum_items.keys()
            }
        except Exception:
            available = set()
        self.available_engines = available
        self.report["notes"].append(f"Available render engines: {sorted(self.available_engines)}")

    def _engine_available(self, engine_name):
        requested = str(engine_name or "EEVEE").strip().upper()
        if requested == "CYCLES":
            return "CYCLES" in self.available_engines
        return bool({"BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "EEVEE"} & set(self.available_engines))

    def _skip_engine_case(self, bucket, case, reason):
        entry = {
            "id": str(case.get("id", "") or ""),
            "status": "skipped",
            "engine": str(case.get("engine", "") or ""),
            "reason": str(reason or ""),
        }
        self.report[str(bucket)].append(entry)
        self.report["notes"].append(f"Skipped {entry['id']}: {entry['reason']}")
        return entry

    def _search_and_frame(self, query, country_hint=None, nav=None, sunlight_preset="NOON"):
        ensure_camera(self.scene, name="Planetka Overnight Camera")
        selected = ""
        if str(query or "").strip():
            selected = search_place(
                self.props,
                self.state,
                self.geonames,
                query,
                country_hint=country_hint,
            )
        if nav:
            set_navigation(self.props, self.state, **dict(nav))
            apply_result = self._call_operator("navigation_apply_shot")
            if "FINISHED" not in apply_result:
                raise E2EError(f"navigation_apply_shot failed after search/frame setup: {apply_result}")
            clip_result = self._call_operator("auto_adjust_clipping")
            if "FINISHED" not in clip_result and "CANCELLED" not in clip_result:
                raise E2EError(f"auto_adjust_clipping failed after search/frame setup: {clip_result}")
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        self._call_operator("sunlight_preset", preset=str(sunlight_preset or "NOON"))
        for _ in range(3):
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass
            time.sleep(0.05)
        return selected or str(query or "").strip()

    def _prepare_animation_case(self, case):
        frames = int(case.get("frames", 6))
        try:
            self.scene.use_preview_range = False
            self.scene.frame_start = 1
            self.scene.frame_end = max(1, int(frames))
            self.scene.frame_set(1)
            bpy.context.view_layer.update()
        except Exception:
            pass
        self.props.anim_frame_start = 1
        self.props.anim_frame_end = frames
        self.props.anim_motion_curve = str(case.get("motion_curve", "EASE_IN_OUT"))
        self.props.anim_render_preset = str(case.get("render_preset", "SPEED"))
        if case.get("preset") == "A_TO_B":
            self.props.anim_camera_preset = "A_TO_B"
            view_a = dict(case.get("view_a") or {})
            view_b = dict(case.get("view_b") or {})
            self._search_and_frame(
                view_a.get("query", DEFAULT_PLACE_QUERIES[0]),
                country_hint=view_a.get("country_hint"),
                nav=view_a.get("nav"),
                sunlight_preset=view_a.get("sunlight_preset", "NOON"),
            )
            self._call_operator("animation_save_view", slot="A")
            self._search_and_frame(
                view_b.get("query", DEFAULT_PLACE_QUERIES[1]),
                country_hint=view_b.get("country_hint"),
                nav=view_b.get("nav"),
                sunlight_preset=view_b.get("sunlight_preset", "SUNSET"),
            )
            self._call_operator("animation_save_view", slot="B")
        else:
            self.props.anim_camera_preset = str(case.get("preset", "ORBIT"))
            selected = self._search_and_frame(
                case.get("query", DEFAULT_PLACE_QUERIES[0]),
                country_hint=case.get("country_hint"),
                nav=case.get("nav"),
                sunlight_preset=case.get("sunlight_preset", "MID_AFTERNOON"),
            )
            if self.props.anim_camera_preset == "ORBIT":
                self.props.anim_orbit_degrees = float(case.get("orbit_degrees", 45.0))
                self.props.anim_circle_direction = str(case.get("circle_direction", "CLOCKWISE"))
            if self.props.anim_camera_preset == "ZOOM":
                self.props.anim_end_altitude_km = float(case.get("end_altitude_km", 40.0))
                self.props.anim_zoom_rotate_degrees = float(case.get("zoom_rotate_degrees", 0.0))
            return selected
        return ""

    def _set_view3d_non_camera_pose(self):
        override = find_view3d_override(bpy.context)
        if not override:
            return False
        region_data = override.get("region_data")
        if region_data is None:
            return False
        try:
            region_data.view_perspective = 'PERSP'
            region_data.view_distance = 6.0
            region_data.view_location = (0.0, 0.0, 0.0)
            region_data.view_rotation = Quaternion((0.9238795, 0.0, 0.3826834, 0.0))
        except Exception:
            return False
        return override

    def _run_surface_grading_reset_flow(self):
        factory_values = dict(getattr(self.operators, "_surface_grading_factory_values")() or {})
        section_socket_names = dict(getattr(self.operators, "_SURFACE_GRADING_SECTION_SOCKET_NAMES", {}) or {})
        nodes = tuple(getattr(self.operators, "_iter_surface_grading_nodes")() or ())
        if not nodes:
            self.report["notes"].append("Surface grading reset flow skipped: grading nodes missing.")
            return
        for section, allowed_names in section_socket_names.items():
            target_socket = None
            for node in nodes:
                for socket in getattr(self.operators, "_iter_surface_grading_input_sockets")(node):
                    socket_name = str(getattr(socket, "name", "") or "").strip().lower()
                    if socket_name in allowed_names:
                        target_socket = socket
                        break
                if target_socket is not None:
                    break
            if target_socket is None:
                continue
            socket_name = str(getattr(target_socket, "name", "") or "").strip().lower()
            factory_value = factory_values.get(socket_name)
            if factory_value is None:
                continue
            try:
                original = getattr(target_socket, "default_value")
                if isinstance(factory_value, (list, tuple)):
                    mutated = list(factory_value)
                    mutated[0] = float(mutated[0]) * 0.5 if mutated else 0.0
                    target_socket.default_value = tuple(mutated)
                else:
                    target_socket.default_value = float(factory_value) + 0.25
            except Exception:
                continue
            self._call_operator("reset_surface_grading_section", section=str(section))
            try:
                current = getattr(target_socket, "default_value")
            except Exception:
                current = None
            self.report["notes"].append(f"Surface grading reset validated for {section}: {socket_name}")
            _ = original, current

    def _run_startup_profile_flow(self):
        expected = {
            "nav_altitude_km": 234.0,
            "nav_azimuth_deg": 57.0,
            "nav_tilt_deg": 39.0,
            "sunlight_longitude_deg": 77.0,
            "sunlight_strength": 17.0,
            "sunlight_seasonal_tilt_deg": 12.0,
            "earth_radius_bu": 3.5,
            "texture_quality_mode": "PREVIEW",
            "auto_resolve": False,
            "show_earth_preview": False,
            "anim_camera_preset": "ZOOM",
        }
        set_navigation(self.props, self.state, nav_altitude_km=expected["nav_altitude_km"], nav_azimuth_deg=expected["nav_azimuth_deg"], nav_tilt_deg=expected["nav_tilt_deg"], nav_roll_deg=0.0)
        self.props.sunlight_longitude_deg = expected["sunlight_longitude_deg"]
        self.props.sunlight_strength = expected["sunlight_strength"]
        self.props.sunlight_seasonal_tilt_deg = expected["sunlight_seasonal_tilt_deg"]
        self.props.earth_radius_bu = expected["earth_radius_bu"]
        self.props.texture_quality_mode = expected["texture_quality_mode"]
        self.props.auto_resolve = expected["auto_resolve"]
        self.props.show_earth_preview = expected["show_earth_preview"]
        self.props.anim_camera_preset = expected["anim_camera_preset"]
        self._call_operator("save_startup_setup")

        purge_planetka_data()
        ensure_camera(self.scene, name="Planetka Overnight Camera")
        # Deliberately clobber props before Create Earth to confirm saved setup is restored.
        self.props.nav_altitude_km = 50.0
        self.props.texture_quality_mode = "PREVIEW"
        self.props.anim_camera_preset = "NONE"
        create_earth_and_wait(self.state, self.scene)
        restored = {
            key: getattr(self.props, key)
            for key in expected.keys()
            if hasattr(self.props, key)
        }
        self.report["notes"].append(f"Startup profile restored values: {restored}")
        self._call_operator("reset_startup_setup_factory")

    def _pick_runtime_cache_image(self):
        for image in bpy.data.images:
            raw_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "").strip()
            if not raw_path:
                continue
            abs_path = os.path.abspath(bpy.path.abspath(raw_path))
            if not os.path.isfile(abs_path):
                continue
            if "planetka_cache" not in abs_path.replace("\\", "/").lower():
                continue
            return image, Path(abs_path)
        return None, None

    def _run_cache_self_heal_case(self):
        self._search_and_frame("Singapore", country_hint="SG", nav={"nav_altitude_km": 120.0, "nav_azimuth_deg": 20.0, "nav_tilt_deg": 45.0, "nav_roll_deg": 0.0}, sunlight_preset="MID_AFTERNOON")
        resolve_textures(self.state, self.scene, texture_quality_mode="FULL")
        image, original_path = self._pick_runtime_cache_image()
        if image is None or original_path is None:
            self.report["rogue_phase"]["cache_self_heal"] = {"status": "skipped", "reason": "No runtime cache image found."}
            return
        tampered_path = original_path.with_suffix(original_path.suffix + ".bak")
        if tampered_path.exists():
            tampered_path.unlink()
        os.rename(original_path, tampered_path)
        try:
            missing_count, healed_count, failed_count = self.state.self_heal_missing_cache_images_for_render(self.scene)
            out_path = self.session_dir / "rogue_cache_self_heal.png"
            configure_eevee(self.scene)
            configure_png_output(self.scene, output_prefix=out_path, resolution_x=960, resolution_y=540, resolution_percentage=100)
            render_still(self.scene, out_path)
            image_analysis = analyze_render_image(out_path)
            analysis = {
                "samples": [image_analysis],
                "has_mostly_black": bool(image_analysis.get("mostly_black")),
                "has_pink_corrupt": bool(image_analysis.get("pink_corrupt")),
            }
            self.report["rogue_phase"]["cache_self_heal"] = {
                "status": "ok",
                "missing_count": int(missing_count),
                "healed_count": int(healed_count),
                "failed_count": int(failed_count),
                "render": analysis,
            }
        finally:
            if tampered_path.exists() and not original_path.exists():
                os.rename(tampered_path, original_path)
            elif tampered_path.exists():
                tampered_path.unlink(missing_ok=True)

    def _run_object_rename_rebuild_case(self):
        root = bpy.data.objects.get("Planetka Root")
        surface = bpy.data.objects.get("Planetka Earth Surface")
        if root is None or surface is None:
            self.report["rogue_phase"]["object_rename_rebuild"] = {
                "status": "skipped",
                "reason": "Planetka Root or Earth Surface missing before tamper.",
            }
            return
        original_root_name = str(root.name)
        original_surface_name = str(surface.name)
        health_before = self._scene_health_summary()
        root.name = "Rogue Renamed Root"
        surface.name = "Rogue Renamed Surface"
        health_after_rename = self._scene_health_summary()
        rebuild_result = self._call_operator("rebuild_earth")
        if "FINISHED" not in rebuild_result:
            raise E2EError(f"Rebuild Earth failed after object rename tamper: {rebuild_result}")
        drain_queued_resolve(self.state, self.scene, timeout_sec=120.0)
        resolve_textures(self.state, self.scene, texture_quality_mode="PREVIEW")
        repaired_health = self._scene_health_summary()
        out_path = self.session_dir / "rogue_object_rename_rebuild.png"
        configure_eevee(self.scene)
        configure_png_output(self.scene, output_prefix=out_path, resolution_x=960, resolution_y=540, resolution_percentage=100)
        render_still(self.scene, out_path)
        image_analysis = analyze_render_image(out_path)
        analysis = {
            "samples": [image_analysis],
            "has_mostly_black": bool(image_analysis.get("mostly_black")),
            "has_pink_corrupt": bool(image_analysis.get("pink_corrupt")),
        }
        self.report["rogue_phase"]["object_rename_rebuild"] = {
            "status": "ok",
            "renamed_from": {
                "root": original_root_name,
                "surface": original_surface_name,
            },
            "health_before": health_before,
            "health_after_rename": health_after_rename,
            "health_after_rebuild": repaired_health,
            "render": analysis,
        }

    def _run_surface_delete_rebuild_case(self):
        surface = bpy.data.objects.get("Planetka Earth Surface")
        if surface is None:
            self.report["rogue_phase"]["surface_delete_rebuild"] = {
                "status": "skipped",
                "reason": "Planetka Earth Surface missing before tamper.",
            }
            return
        health_before = self._scene_health_summary()
        bpy.data.objects.remove(surface, do_unlink=True)
        health_after_delete = self._scene_health_summary()
        rebuild_result = self._call_operator("rebuild_earth")
        if "FINISHED" not in rebuild_result:
            raise E2EError(f"Rebuild Earth failed after surface delete tamper: {rebuild_result}")
        drain_queued_resolve(self.state, self.scene, timeout_sec=120.0)
        resolve_textures(self.state, self.scene, texture_quality_mode="PREVIEW")
        repaired_health = self._scene_health_summary()
        out_path = self.session_dir / "rogue_surface_delete_rebuild.png"
        configure_eevee(self.scene)
        configure_png_output(self.scene, output_prefix=out_path, resolution_x=960, resolution_y=540, resolution_percentage=100)
        render_still(self.scene, out_path)
        image_analysis = analyze_render_image(out_path)
        analysis = {
            "samples": [image_analysis],
            "has_mostly_black": bool(image_analysis.get("mostly_black")),
            "has_pink_corrupt": bool(image_analysis.get("pink_corrupt")),
        }
        self.report["rogue_phase"]["surface_delete_rebuild"] = {
            "status": "ok",
            "health_before": health_before,
            "health_after_delete": health_after_delete,
            "health_after_rebuild": repaired_health,
            "render": analysis,
        }

    def _run_material_delete_rebuild_case(self):
        material = bpy.data.materials.get("Planetka Earth Material")
        if material is None:
            self.report["rogue_phase"]["material_delete_rebuild"] = {
                "status": "skipped",
                "reason": "Planetka Earth Material missing before tamper.",
            }
            return
        health_before = self._scene_health_summary()
        bpy.data.materials.remove(material, do_unlink=True)
        health_after_delete = self._scene_health_summary()
        rebuild_result = self._call_operator("rebuild_earth")
        if "FINISHED" not in rebuild_result:
            raise E2EError(f"Rebuild Earth failed after material delete tamper: {rebuild_result}")
        drain_queued_resolve(self.state, self.scene, timeout_sec=120.0)
        resolve_textures(self.state, self.scene, texture_quality_mode="PREVIEW")
        repaired_health = self._scene_health_summary()
        out_path = self.session_dir / "rogue_material_delete_rebuild.png"
        configure_eevee(self.scene)
        configure_png_output(self.scene, output_prefix=out_path, resolution_x=960, resolution_y=540, resolution_percentage=100)
        render_still(self.scene, out_path)
        image_analysis = analyze_render_image(out_path)
        analysis = {
            "samples": [image_analysis],
            "has_mostly_black": bool(image_analysis.get("mostly_black")),
            "has_pink_corrupt": bool(image_analysis.get("pink_corrupt")),
        }
        self.report["rogue_phase"]["material_delete_rebuild"] = {
            "status": "ok",
            "health_before": health_before,
            "health_after_delete": health_after_delete,
            "health_after_rebuild": repaired_health,
            "render": analysis,
        }

    def _run_shader_tamper_rebuild_case(self):
        material = bpy.data.materials.get("Planetka Earth Material")
        health_before = self._scene_health_summary()
        tampered = False
        if material is not None and getattr(material, "node_tree", None) is not None:
            for node in list(material.node_tree.nodes):
                node_tree = getattr(node, "node_tree", None)
                node_tree_name = str(getattr(node_tree, "name", "") or "")
                if "Textures Loading" in node_tree_name:
                    material.node_tree.nodes.remove(node)
                    tampered = True
                    break
        if not tampered:
            self.report["rogue_phase"]["shader_tamper_rebuild"] = {"status": "skipped", "reason": "Loading node not found."}
            return
        health_after_tamper = self._scene_health_summary()
        rebuild_result = self._call_operator("rebuild_earth")
        if "FINISHED" not in rebuild_result:
            raise E2EError(f"Rebuild Earth failed after shader tamper: {rebuild_result}")
        drain_queued_resolve(self.state, self.scene, timeout_sec=120.0)
        resolve_textures(self.state, self.scene, texture_quality_mode="PREVIEW")
        repaired_health = self._scene_health_summary()
        out_path = self.session_dir / "rogue_shader_rebuild.png"
        configure_eevee(self.scene)
        configure_png_output(self.scene, output_prefix=out_path, resolution_x=960, resolution_y=540, resolution_percentage=100)
        render_still(self.scene, out_path)
        image_analysis = analyze_render_image(out_path)
        analysis = {
            "samples": [image_analysis],
            "has_mostly_black": bool(image_analysis.get("mostly_black")),
            "has_pink_corrupt": bool(image_analysis.get("pink_corrupt")),
        }
        self.report["rogue_phase"]["shader_tamper_rebuild"] = {
            "status": "ok",
            "health_before": health_before,
            "health_after_tamper": health_after_tamper,
            "health_after_rebuild": repaired_health,
            "render": analysis,
        }

    def _run_inside_earth_warning_case(self):
        earth = self.extension_prefs.get_earth_object()
        camera = getattr(self.scene, "camera", None)
        if earth is None or camera is None:
            self.report["rogue_phase"]["inside_earth_warning"] = {"status": "skipped", "reason": "Earth or camera missing."}
            return
        original_location = tuple(camera.location)
        try:
            camera.location = tuple(earth.matrix_world.translation)
            try:
                resolve_textures(self.state, self.scene, texture_quality_mode="PREVIEW")
            except Exception:
                pass
            warning = str(self.state.get_camera_inside_earth_warning(self.scene) or "").strip()
            self.report["rogue_phase"]["inside_earth_warning"] = {
                "status": "ok" if warning else "missing_warning",
                "warning": warning,
            }
        finally:
            camera.location = original_location
            self.state.update_navigation_shot(self.props, bpy.context)

    def _run_backend_abuse_subprocess(self):
        access_token = str(self.auth.get_access_token(self.prefs) or "").strip()
        script_path = Path(_TOOLS_DIR) / "worker_abuse_simulation.py"
        tile_requests = "30" if self.smoke_mode else "120"
        cmd = [
            shutil.which("python3") or sys.executable,
            str(script_path),
            "--base-url",
            str(self.auth.get_api_base_url()),
            "--tile-requests",
            tile_requests,
        ]
        if access_token:
            cmd.extend(["--bearer-token", access_token])
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.report["rogue_phase"]["backend_abuse_simulation"] = {
            "status": "ok" if proc.returncode == 0 else "failed",
            "returncode": int(proc.returncode),
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-4000:],
            "command": cmd,
        }

    def _run_still_case(self, case):
        if not self._engine_available(case.get("engine", "EEVEE")):
            self._skip_engine_case(
                "still_cases",
                case,
                f"Render engine unavailable in this Blender build: {case.get('engine', 'EEVEE')}",
            )
            return
        self._restore_visual_phase_defaults()
        engine_info = self._configure_engine(case.get("engine", "EEVEE"))
        query = str(case.get("query", "") or "").strip()
        if query:
            selected = self._search_and_frame(
                query,
                country_hint=case.get("country_hint"),
                nav=case.get("nav"),
                sunlight_preset=case.get("sunlight_preset", "NOON"),
            )
        else:
            selected = self._search_and_frame(
                "",
                nav=case.get("nav"),
                sunlight_preset=case.get("sunlight_preset", "NOON"),
            ) or str(case.get("selected_label", "") or case["id"])
        self.props.earth_radius_bu = float(case.get("earth_radius_bu", 2.0))
        self.props.resolution_bias = float(case.get("resolution_bias", 0.0))
        apply_result = self._call_operator("navigation_apply_shot")
        if "FINISHED" not in apply_result:
            raise E2EError(f"navigation_apply_shot failed after radius update for {case['id']}: {apply_result}")
        clip_result = self._call_operator("auto_adjust_clipping")
        if "FINISHED" not in clip_result and "CANCELLED" not in clip_result:
            raise E2EError(f"auto_adjust_clipping failed after radius update for {case['id']}: {clip_result}")
        quality_mode = str(case.get("quality", "PREVIEW"))
        self.props.texture_quality_mode = quality_mode
        requested_tiles = list(case.get("tiles_override", ()) or ())
        resolve_textures(
            self.state,
            self.scene,
            texture_quality_mode=quality_mode,
            tiles_override_json=(json.dumps(requested_tiles) if requested_tiles else ""),
        )
        resolved_tiles = list(self.scene.get("planetka_last_resolved_tiles", ()) or ())
        diag = self.diagnostics.read_diagnostics(self.scene) if getattr(self, "diagnostics", None) is not None else {}
        resolved_tile_count = int(diag.get("last_tile_count", 0) or 0)
        if resolved_tile_count <= 0 and resolved_tiles:
            resolved_tile_count = int(len(resolved_tiles))
        if requested_tiles and resolved_tile_count != len(requested_tiles):
            raise E2EError(
                f"Still-case override tile count mismatch for {case['id']}: "
                f"requested={len(requested_tiles)} resolved={resolved_tile_count}"
            )
        output_path = self.session_dir / f"{case['id']}.png"
        resolution_x, resolution_y = tuple(case.get("resolution", (1280, 720)))
        configure_png_output(self.scene, output_prefix=output_path, resolution_x=resolution_x, resolution_y=resolution_y, resolution_percentage=100)
        render_still(self.scene, output_path)
        image_analysis = analyze_render_image(output_path)
        analysis = {
            "samples": [image_analysis],
            "has_mostly_black": bool(image_analysis.get("mostly_black")),
            "has_pink_corrupt": bool(image_analysis.get("pink_corrupt")),
        }
        entry = {
            "id": case["id"],
            "status": "ok",
            "selected_place": selected,
            "engine": engine_info,
            "quality": quality_mode,
            "requested_tile_count": int(len(requested_tiles)),
            "resolved_tile_count": int(resolved_tile_count),
            "resolved_tiles": list(resolved_tiles),
            "risk_category": str(case.get("risk_category", "") or ""),
            "render": analysis,
            "output": str(output_path),
        }
        self.report["still_cases"].append(entry)
        if analysis.get("has_mostly_black") or analysis.get("has_pink_corrupt"):
            raise E2EError(f"Visual validation failed for still case {case['id']}")

    def _run_quick_preview_case(self, case):
        if not self._engine_available(case.get("engine", "EEVEE")):
            self._skip_engine_case(
                "quick_preview_cases",
                case,
                f"Render engine unavailable in this Blender build: {case.get('engine', 'EEVEE')}",
            )
            return
        self._restore_visual_phase_defaults()
        engine_info = self._configure_engine(case.get("engine", "EEVEE"))
        selected = self._prepare_animation_case(case)
        self.props.anim_prepare_max_segments = 12
        self.props.anim_prepare_max_textures_mb = 2048.0
        make_ready_result = self._call_operator("animation_make_ready")
        if "FINISHED" not in make_ready_result:
            raise E2EError(f"Quick Preview make ready failed: {case['id']}")
        output_dir = self.session_dir / case["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        configure_png_output(
            self.scene,
            output_prefix=output_dir / "frame_",
            resolution_x=960,
            resolution_y=540,
            resolution_percentage=100,
        )
        render_animation(self.scene, output_prefix=output_dir / "frame_", frame_start=1, frame_end=int(case.get("frames", 6)))
        analysis = analyze_png_directory(output_dir, max_samples=6)
        clear_result = self._call_operator("animation_clear_prepared")
        if "FINISHED" not in clear_result:
            raise E2EError(f"Quick Preview clear failed: {case['id']}")
        entry = {
            "id": case["id"],
            "status": "ok",
            "selected_place": selected,
            "engine": engine_info,
            "preset": case.get("preset"),
            "render": analysis,
            "output_dir": str(output_dir),
        }
        self.report["quick_preview_cases"].append(entry)
        if analysis.get("has_mostly_black") or analysis.get("has_pink_corrupt"):
            raise E2EError(f"Visual validation failed for quick preview case {case['id']}")

    def _quiesce_runtime_for_final_animation(self):
        stop_service = getattr(self.state, "stop_auto_resolve_service", None)
        if callable(stop_service):
            stop_service()
        stop_pipeline = getattr(self.state, "stop_auto_resolve_download_pipeline", None)
        if callable(stop_pipeline):
            stop_pipeline()
        flush_navigation = getattr(self.state, "_navigation_shot_update_timer", None)
        if callable(flush_navigation):
            try:
                flush_navigation()
            except Exception:
                pass
        force_restore_navigation = getattr(self.state, "_force_restore_navigation_adaptive_state", None)
        if callable(force_restore_navigation):
            try:
                force_restore_navigation()
            except Exception:
                pass
        suspend_navigation_updates = getattr(self.state, "suspend_navigation_shot_updates", None)
        if callable(suspend_navigation_updates):
            suspend_navigation_updates()
        suspend_camera_sync = getattr(self.state, "suspend_navigation_camera_control_sync", None)
        if callable(suspend_camera_sync):
            suspend_camera_sync()
        self.active_final_case_runtime_quiesced = True
        for _ in range(2):
            try:
                bpy.context.view_layer.update()
            except Exception:
                pass
            time.sleep(0.05)

    def _release_runtime_after_final_animation(self):
        if not bool(self.active_final_case_runtime_quiesced):
            return
        resume_camera_sync = getattr(self.state, "resume_navigation_camera_control_sync", None)
        if callable(resume_camera_sync):
            try:
                resume_camera_sync()
            except Exception:
                pass
        resume_navigation_updates = getattr(self.state, "resume_navigation_shot_updates", None)
        if callable(resume_navigation_updates):
            try:
                resume_navigation_updates()
            except Exception:
                pass
        self.active_final_case_runtime_quiesced = False

    def _resolve_blender_bin(self):
        for candidate in BLENDER_BIN_CANDIDATES:
            path = str(candidate or "").strip()
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        raise E2EError("Blender binary not found for isolated final animation subprocess.")

    def _write_subprocess_auth_payload(self):
        access_token = str(self.auth.get_access_token(self.prefs, allow_refresh=True) or "").strip()
        refresh_token = str(getattr(self.prefs, "auth_refresh_token", "") or "").strip()
        if not access_token or not refresh_token:
            raise E2EError("Current Planetka auth session is incomplete for final animation subprocess.")
        payload = {
            "email": str(self.auth.get_connected_email(self.prefs) or getattr(self.prefs, "auth_email", "") or "").strip(),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "api_key_mask": str(getattr(self.prefs, "auth_api_key_mask", "") or "").strip(),
            "plan_code": str(getattr(self.prefs, "auth_plan_code", "") or "").strip(),
            "plan_name": str(getattr(self.prefs, "auth_plan_name", "") or "").strip(),
            "account_tier": str(self.auth.get_account_tier(self.prefs) or getattr(self.prefs, "auth_account_tier", "") or "").strip(),
            "commercial_use_allowed": bool(self.auth.get_commercial_use_allowed(self.prefs)),
            "contact_url": str(getattr(self.prefs, "auth_contact_url", "") or "").strip(),
            "upgrade_url": str(getattr(self.prefs, "auth_upgrade_url", "") or "").strip(),
        }
        target = self.session_dir / "final_animation_auth_payload.json"
        write_json(target, payload)
        return target

    def _run_final_animation_subprocess_case(self, case):
        if not self._engine_available(case.get("engine", "EEVEE")):
            self._skip_engine_case(
                "final_animation_cases",
                case,
                f"Render engine unavailable in this Blender build: {case.get('engine', 'EEVEE')}",
            )
            return
        blender_bin = self._resolve_blender_bin()
        auth_payload_path = self._write_subprocess_auth_payload()
        case_id = str(case.get("id", "final_animation_case") or "final_animation_case")
        output_dir = self.session_dir / case_id
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.session_dir / f"{case_id}_report.json"
        env = dict(os.environ)
        env["PLANETKA_AUTH_PAYLOAD"] = str(auth_payload_path)
        device_id = str(getattr(self.prefs, "auth_device_id", "") or "").strip()
        if device_id:
            env["PLANETKA_AUTH_DEVICE_ID"] = device_id
        env["PLANETKA_E2E_FINAL_CASE_JSON"] = json.dumps(case, separators=(",", ":"))
        env["PLANETKA_E2E_FINAL_OUTPUT_DIR"] = str(output_dir)
        env["PLANETKA_E2E_FINAL_REPORT_PATH"] = str(report_path)
        env["PLANETKA_E2E_FINAL_TIMEOUT_SEC"] = str(int(FINAL_RENDER_TIMEOUT_SEC))
        cmd = [
            blender_bin,
            "--factory-startup",
            "--python",
            str(Path(_TOOLS_DIR) / "planetka_e2e_final_animation_ui.py"),
        ]
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=float(FINAL_RENDER_TIMEOUT_SEC + 300.0),
        )
        if not report_path.is_file():
            raise E2EError(
                f"Final animation subprocess produced no report for {case_id} (returncode={proc.returncode}). "
                f"stdout_tail={(proc.stdout or '')[-1000:]} stderr_tail={(proc.stderr or '')[-1000:]}"
            )
        with open(report_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        entry = {
            "id": case_id,
            "status": "ok",
            "preset": case.get("preset"),
            "engine": payload.get("engine"),
            "selected_place": payload.get("selected_place", ""),
            "render": payload.get("render", {}),
            "output_dir": str(output_dir),
            "invoke_result": payload.get("invoke_result", []),
            "subprocess_report": str(report_path),
            "subprocess_returncode": int(proc.returncode),
            "subprocess_stdout_tail": (proc.stdout or "")[-4000:],
            "subprocess_stderr_tail": (proc.stderr or "")[-4000:],
        }
        self.report["final_animation_cases"].append(entry)
        if proc.returncode != 0 or str(payload.get("status", "")) != "ok":
            raise E2EError(
                f"Final animation subprocess failed for {case_id}: "
                f"status={payload.get('status')} returncode={proc.returncode} error={payload.get('error', '')}"
            )
        analysis = entry.get("render", {}) or {}
        if analysis.get("has_mostly_black") or analysis.get("has_pink_corrupt"):
            raise E2EError(f"Visual validation failed for final animation case {case_id}")

    def _start_final_animation_case(self, case):
        self._restore_visual_phase_defaults()
        engine_info = self._configure_engine(case.get("engine", "EEVEE"))
        selected = self._prepare_animation_case(case)
        self.props.anim_render_preset = str(case.get("render_preset", "SPEED"))
        self.props.anim_render_persistent_data = bool(case.get("render_persistent_data", True))
        self._quiesce_runtime_for_final_animation()
        output_dir = self.session_dir / case["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        configure_png_output(
            self.scene,
            output_prefix=output_dir / "frame_",
            resolution_x=960,
            resolution_y=540,
            resolution_percentage=100,
        )
        try:
            result = bpy.ops.planetka.animation_render('INVOKE_DEFAULT', confirmed=True)
        except Exception:
            self._release_runtime_after_final_animation()
            raise
        if "RUNNING_MODAL" not in result and "FINISHED" not in result:
            self._release_runtime_after_final_animation()
            raise E2EError(f"Final Animation Render did not start for {case['id']}: {result}")
        self.active_final_case = {
            "case": case,
            "engine": engine_info,
            "selected_place": selected,
            "output_dir": str(output_dir),
            "expected_frames": int(case.get("frames", 6)),
            "invoke_result": list(result),
        }
        self.active_final_case_started_at = time.time()
        self.active_final_case_deadline = self.active_final_case_started_at + float(case.get("timeout_sec", FINAL_RENDER_TIMEOUT_SEC))
        self.active_final_case_seen_running = False
        self.active_final_case_last_frame_count = 0
        return SHORT_WAIT_SEC

    def _poll_final_animation_case(self):
        case_info = dict(self.active_final_case or {})
        output_dir = Path(case_info.get("output_dir", ""))
        expected_frames = int(case_info.get("expected_frames", 0) or 0)
        frame_count = len(list_pngs(output_dir)) if output_dir.exists() else 0
        self.active_final_case_last_frame_count = frame_count
        running = False
        try:
            is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
            if callable(is_job_running):
                running = bool(is_job_running("RENDER"))
        except Exception:
            running = False
        if running:
            self.active_final_case_seen_running = True
            return 0.5
        now = time.time()
        if not self.active_final_case_seen_running and now < (self.active_final_case_started_at + 15.0):
            return 0.25
        if frame_count >= expected_frames > 0:
            self._release_runtime_after_final_animation()
            analysis = analyze_png_directory(output_dir, max_samples=min(6, expected_frames))
            entry = {
                "id": case_info["case"]["id"],
                "preset": case_info["case"].get("preset"),
                "engine": case_info.get("engine"),
                "selected_place": case_info.get("selected_place"),
                "render": analysis,
                "output_dir": str(output_dir),
                "invoke_result": case_info.get("invoke_result"),
            }
            self.report["final_animation_cases"].append(entry)
            self.active_final_case = None
            if analysis.get("has_mostly_black") or analysis.get("has_pink_corrupt"):
                raise E2EError(f"Visual validation failed for final animation case {entry['id']}")
            return SHORT_WAIT_SEC
        if now > self.active_final_case_deadline:
            self._release_runtime_after_final_animation()
            raise E2EError(
                f"Final Animation Render timed out for {case_info['case']['id']} ({frame_count}/{expected_frames} frames)."
            )
        return 0.5

    def _setup_environment(self):
        self.base_module = enable_module(required_planetka_attr="add_earth")
        self.auth = import_submodule(self.base_module, "auth")
        self.extension_prefs = import_submodule(self.base_module, "extension_prefs")
        self.geonames = import_submodule(self.base_module, "geonames_db")
        self.state = import_submodule(self.base_module, "state")
        self.diagnostics = import_submodule(self.base_module, "diagnostics")
        self.validation = import_submodule(self.base_module, "validation")
        self.operators = import_submodule(self.base_module, "operators")
        self.prefs = self.extension_prefs.get_prefs()
        self.scene = bpy.context.scene
        self.props = getattr(self.scene, "planetka", None)
        self._refresh_available_engines()
        if self.props is None:
            raise E2EError("scene.planetka is unavailable.")
        self.report["account"] = ensure_authenticated(
            self.auth,
            self.prefs,
            payload_path=str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip(),
            api_key=str(os.environ.get("PLANETKA_API_KEY") or "").strip(),
            api_key_path=str(os.environ.get("PLANETKA_API_KEY_PATH") or "").strip(),
        )
        wait_for_geonames_ready(self.geonames)
        return SHORT_WAIT_SEC

    def _run_preflight(self):
        purge_planetka_data()
        if hasattr(bpy.ops.planetka, "remove_default_scene") and bpy.ops.planetka.remove_default_scene.poll():
            self._call_operator("remove_default_scene")
        else:
            self.report["notes"].append("remove_default_scene skipped; scene was not pristine factory startup.")
        ensure_camera(self.scene, name="Planetka Overnight Camera")
        ensure_standard_world(self.scene)
        self._call_operator("set_background_black")
        self.prefs.texture_base_path = "planetka-remote"
        create_earth_and_wait(self.state, self.scene)
        if scene_health_operator_available():
            self._call_operator("scene_health_check")
        if hasattr(bpy.ops.planetka, "check_updates"):
            self._call_operator("check_updates", force=False)
        if hasattr(bpy.ops.planetka, "animation_render_info"):
            self._call_operator("animation_render_info")
        self.report["notes"].append(f"Initial scene health: {self._scene_health_summary()}")
        return SHORT_WAIT_SEC

    def _run_property_sweeps(self):
        for name, values in BOOL_SWEEPS.items():
            if not hasattr(self.props, name):
                continue
            for value in values:
                setattr(self.props, name, bool(value))
                self._record_prop(name, bool(value), getattr(self.props, name))
        for name, values in NUMERIC_SWEEPS.items():
            if not hasattr(self.props, name):
                continue
            for value in values:
                setattr(self.props, name, value)
                self._record_prop(name, value, getattr(self.props, name))
        for name in ENUM_SWEEPS:
            if not hasattr(self.props, name):
                continue
            rna = self.props.bl_rna.properties.get(name)
            if rna is None:
                continue
            for item in rna.enum_items:
                setattr(self.props, name, item.identifier)
                self._record_prop(name, item.identifier, getattr(self.props, name))
        # restore stable defaults for subsequent renders
        self.props.texture_quality_mode = "PREVIEW"
        self.props.anim_camera_preset = "NONE"
        self.props.anim_motion_curve = "EASE_IN_OUT"
        self.props.anim_circle_direction = "CLOCKWISE"
        self.props.anim_render_preset = "SPEED"
        self.props.auto_resolve = True
        self.props.show_earth_preview = False
        self.props.debug_logging = False
        self.props.earth_radius_bu = 2.0
        self.props.resolution_bias = 0.0
        return SHORT_WAIT_SEC

    def _restore_visual_phase_defaults(self):
        self.props.texture_quality_mode = "PREVIEW"
        self.props.anim_camera_preset = "NONE"
        self.props.anim_motion_curve = "EASE_IN_OUT"
        self.props.anim_circle_direction = "CLOCKWISE"
        self.props.anim_render_preset = "SPEED"
        self.props.auto_resolve = True
        self.props.show_earth_preview = False
        self.props.debug_logging = False
        self.props.earth_radius_bu = 2.0
        self.props.resolution_bias = 0.0
        self.props.sunlight_strength = 10.0
        self.props.sunlight_seasonal_tilt_deg = 0.0

    def _run_functional_ops(self):
        # saved locations
        self._search_and_frame("Bratislava", country_hint="SK", nav={"nav_altitude_km": 120.0, "nav_azimuth_deg": 18.0, "nav_tilt_deg": 42.0, "nav_roll_deg": 0.0}, sunlight_preset="NOON")
        self.props.nav_saved_location_name = "Overnight Bratislava"
        self._call_operator("save_location")
        self._search_and_frame("Auckland", country_hint="NZ", nav={"nav_altitude_km": 140.0, "nav_azimuth_deg": 38.0, "nav_tilt_deg": 46.0, "nav_roll_deg": 0.0}, sunlight_preset="SUNSET")
        self.props.nav_saved_location_name = "Overnight Auckland"
        self._call_operator("save_location")
        self.props.nav_saved_location_id = "Overnight Bratislava"
        self._call_operator("load_saved_location")
        self.props.nav_saved_location_id = "Overnight Auckland"
        self._call_operator("delete_saved_location")

        for preset in ("MAX_PROXIMITY", "ISS_ORBIT", "SENTINEL2", "HIGH_ORBIT"):
            self._call_operator("navigation_preset", preset=preset)
        for preset in (
            "DAWN",
            "SUNRISE",
            "EARLY_MORNING",
            "MID_MORNING",
            "NOON",
            "MID_AFTERNOON",
            "LATE_AFTERNOON",
            "SUNSET",
            "DUSK",
            "NIGHT",
        ):
            self._call_operator("sunlight_preset", preset=preset)

        override = self._set_view3d_non_camera_pose()
        if override:
            with bpy.context.temp_override(**override):
                self._call_operator("navigation_use_current_view")
        else:
            self.report["notes"].append("navigation_use_current_view skipped: no VIEW_3D context available.")
        self._search_and_frame(
            "Bratislava",
            country_hint="SK",
            nav={"nav_altitude_km": 120.0, "nav_azimuth_deg": 18.0, "nav_tilt_deg": 42.0, "nav_roll_deg": 0.0},
            sunlight_preset="NOON",
        )

        self._call_operator("auto_adjust_clipping")
        root = bpy.data.objects.get("Planetka Root")
        if root is not None:
            root.location = (1.5, -2.0, 0.75)
            root.rotation_euler = (0.0, 0.0, math.radians(15.0))
        self._call_operator("reset_earth_transform")
        self._run_surface_grading_reset_flow()
        self._run_startup_profile_flow()
        self._restore_visual_phase_defaults()
        self._search_and_frame(
            "Bratislava",
            country_hint="SK",
            nav={"nav_altitude_km": 120.0, "nav_azimuth_deg": 18.0, "nav_tilt_deg": 42.0, "nav_roll_deg": 0.0},
            sunlight_preset="NOON",
        )

        standalone_path = self.session_dir / "planetka_standalone_test.blend"
        self._call_operator("create_standalone_file", filepath=str(standalone_path))
        self.report["notes"].append(f"Standalone export exists={standalone_path.exists()} path={standalone_path}")

        self._call_operator("rebuild_earth")
        drain_queued_resolve(self.state, self.scene, timeout_sec=120.0)
        stop_service = getattr(self.state, "stop_auto_resolve_service", None)
        if callable(stop_service):
            stop_service()
        stop_pipeline = getattr(self.state, "stop_auto_resolve_download_pipeline", None)
        if callable(stop_pipeline):
            stop_pipeline()
        purge_planetka_data()
        ensure_camera(self.scene, name="Planetka Overnight Camera")
        ensure_standard_world(self.scene)
        self._call_operator("set_background_black")
        self.prefs.texture_base_path = "planetka-remote"
        self._restore_visual_phase_defaults()
        create_earth_and_wait(self.state, self.scene)
        stop_service = getattr(self.state, "stop_auto_resolve_service", None)
        if callable(stop_service):
            stop_service()
        stop_pipeline = getattr(self.state, "stop_auto_resolve_download_pipeline", None)
        if callable(stop_pipeline):
            stop_pipeline()
        self.report["notes"].append("Post-functional phase baseline reset completed.")
        return SHORT_WAIT_SEC

    def _run_still_cases(self):
        for case in self.still_cases:
            self._run_still_case(case)
        return SHORT_WAIT_SEC

    def _run_quick_preview_cases(self):
        for case in self.quick_preview_cases:
            self._run_quick_preview_case(case)
        return SHORT_WAIT_SEC

    def _run_rogue_phase(self):
        self._run_cache_self_heal_case()
        self._run_object_rename_rebuild_case()
        self._run_surface_delete_rebuild_case()
        self._run_material_delete_rebuild_case()
        self._run_shader_tamper_rebuild_case()
        self._run_inside_earth_warning_case()
        return SHORT_WAIT_SEC

    def _run_backend_abuse_phase(self):
        self._run_backend_abuse_subprocess()
        return SHORT_WAIT_SEC

    def _run_final_animation_cases(self):
        for case in list(self.final_animation_cases or ()):
            self._run_final_animation_subprocess_case(dict(case))
        self.report["notes"].append("Final animation cases ran in fresh Blender UI subprocesses.")
        return SHORT_WAIT_SEC

    def _finalize_success(self):
        self.report["status"] = "ok"
        self.report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._write_report()
        log(TAG, f"PASS: report={self.report_path}")
        bpy.ops.wm.quit_blender()
        return None

    def _fail(self, exc):
        self.report["status"] = "error"
        self.report["error"] = str(exc)
        self.report["traceback"] = traceback.format_exc()
        self.report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._write_report()
        log(TAG, f"FAIL: {exc}")
        try:
            bpy.ops.wm.quit_blender()
        except Exception:
            pass
        return None

    def tick(self):
        try:
            while True:
                if self.active_final_case is not None:
                    return self._poll_final_animation_case()
                if self.phase_index >= len(self.phase_methods):
                    return None
                method = self.phase_methods[self.phase_index]
                self.phase_index += 1
                delay = method()
                if self.active_final_case is not None:
                    return delay
                if delay is None:
                    return None
                if method in {self._run_final_animation_cases, self._finalize_success}:
                    return delay
        except Exception as exc:
            return self._fail(exc)


RUNNER = OvernightRunner()


def _timer_main():
    return RUNNER.tick()


bpy.app.timers.register(_timer_main, first_interval=0.5)
