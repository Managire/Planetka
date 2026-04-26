#!/usr/bin/env python3
"""Planetka core UI acceptance test for real beta accounts.

Runs a single account scenario in Blender UI mode (no background mode).

Environment:
  PLANETKA_ACCOUNT_EMAIL       required: free@planetka.io | personal@planetka.io | commercial@planetka.io
  PLANETKA_TEST_KEYS_FILE      optional: default /tmp/planetka_public_beta_20260424/internal_accounts.json
  PLANETKA_OUTPUT_DIR          optional: default /Volumes/SSDA/renders/planetka_test
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import bpy

from planetka_e2e_common import (
    E2EError,
    analyze_png_directory,
    configure_eevee,
    configure_png_output,
    create_earth_and_wait,
    enable_module,
    ensure_camera,
    ensure_standard_world,
    import_submodule,
    list_pngs,
    log,
    purge_planetka_data,
    resolve_textures,
    search_place,
    set_navigation,
    wait_for_geonames_ready,
    write_json,
)

TAG = "[Planetka Core UI Test]"
STILL_RES_X = 3840
STILL_RES_Y = 2160
ANIM_RES_X = 1920
ANIM_RES_Y = 1080
SCENE_KEY_LAST_RESOLVE_TILE_COUNT = "planetka_last_manual_resolve_tile_count"
SCENE_KEY_LAST_RESOLVE_DOWNLOADED_MB = "planetka_last_manual_resolve_downloaded_mb"
SCENE_KEY_LAST_RESOLVE_DOWNLOADED_GB = "planetka_last_manual_resolve_downloaded_gb"
SCENE_KEY_LAST_RESOLVE_TOTAL_SECONDS = "planetka_last_manual_resolve_total_seconds"
DEFAULT_KEYS_FILE = "/tmp/planetka_public_beta_20260424/internal_accounts.json"
DEFAULT_OUTPUT_ROOT = "/Volumes/SSDA/renders/planetka_test"


class Runner:
    def __init__(self):
        account_email = str(os.environ.get("PLANETKA_ACCOUNT_EMAIL", "") or "").strip().lower()
        if account_email not in {"free@planetka.io", "personal@planetka.io", "commercial@planetka.io"}:
            raise E2EError(
                "PLANETKA_ACCOUNT_EMAIL must be one of: "
                "free@planetka.io, personal@planetka.io, commercial@planetka.io"
            )
        self.account_email = account_email
        self.expected_tier = account_email.split("@", 1)[0]
        self.keys_file = Path(str(os.environ.get("PLANETKA_TEST_KEYS_FILE") or DEFAULT_KEYS_FILE).strip()).expanduser()
        self.output_root = Path(str(os.environ.get("PLANETKA_OUTPUT_DIR") or DEFAULT_OUTPUT_ROOT).strip()).expanduser()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.output_dir = self.output_root / f"{self.expected_tier}_{stamp}"
        self.report_path = self.output_dir / "report.json"
        self.deadline = time.time() + float(3 * 3600)

        self.base_module = None
        self.auth = None
        self.extension_prefs = None
        self.geonames = None
        self.state_module = None
        self.animation_tools = None
        self.diagnostics = None
        self.prefs = None
        self.scene = None
        self.props = None
        self.api_key = ""
        self.full_quality_runs = []

        self.steps = []
        self.waiting_final = None
        self.started = False
        self.finished = False

        self.report = {
            "status": "running",
            "account_email": self.account_email,
            "expected_tier": self.expected_tier,
            "started_at": stamp,
            "output_dir": str(self.output_dir),
            "keys_file": str(self.keys_file),
            "steps": [],
            "resolve_runs": [],
            "resolve_validations": [],
            "oddities": [],
            "errors": [],
        }

    def _record_step(self, name, status, **data):
        entry = {"name": str(name), "status": str(status)}
        entry.update(data)
        self.report["steps"].append(entry)

    def _fail(self, message):
        self.report["status"] = "error"
        self.report["errors"].append(str(message))
        self.report["traceback"] = traceback.format_exc()
        self._write_report()
        log(TAG, f"FAIL ({self.account_email}): {message}")
        try:
            bpy.ops.wm.quit_blender()
        except Exception:
            pass
        return None

    def _write_report(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.report_path, self.report)

    def _load_api_key(self):
        if not self.keys_file.is_file():
            raise E2EError(f"Keys file not found: {self.keys_file}")
        with open(self.keys_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        account = payload.get(self.account_email, {}) if isinstance(payload, dict) else {}
        if not isinstance(account, dict):
            raise E2EError(f"Invalid account payload in keys file for {self.account_email}")
        expected = self.expected_tier
        plan = str(account.get("plan", "") or "").strip().lower()
        if plan != expected:
            raise E2EError(
                f"Keys file plan mismatch for {self.account_email}: expected={expected} got={plan}"
            )
        token = str(account.get("api_key", "") or "").strip()
        if not token:
            raise E2EError(f"API key missing for {self.account_email}")
        self.api_key = token

    def _connect_account(self):
        self.auth.clear_auth_session(prefs=self.prefs, state="logged_out", status_message="")
        self.auth.connect_with_api_key(self.api_key, prefs=self.prefs)
        self.auth.sync_account_profile(self.prefs)
        connected_email = str(self.auth.get_connected_email(self.prefs) or "").strip().lower()
        if connected_email != self.account_email:
            raise E2EError(
                f"Connected email mismatch: expected={self.account_email} got={connected_email}"
            )
        tier = str(self.auth.get_account_tier(self.prefs) or "").strip().lower()
        if tier != self.expected_tier:
            raise E2EError(
                f"Connected tier mismatch: expected={self.expected_tier} got={tier}"
            )
        unrestricted = bool(self.auth.has_unrestricted_quality_access(self.prefs))
        self._record_step(
            "connect_account",
            "ok",
            connected_email=connected_email,
            connected_tier=tier,
            unrestricted_quality=unrestricted,
        )

    def _prepare_scene(self):
        self.scene = bpy.context.scene
        self.props = getattr(self.scene, "planetka", None)
        if self.props is None:
            raise E2EError("scene.planetka is unavailable.")

        purge_planetka_data()
        if hasattr(bpy.ops.planetka, "remove_default_scene") and bpy.ops.planetka.remove_default_scene.poll():
            bpy.ops.planetka.remove_default_scene()

        ensure_camera(self.scene, name=f"Planetka {self.expected_tier.title()} Test Camera")
        ensure_standard_world(self.scene)
        try:
            bpy.ops.planetka.set_background_black()
        except Exception:
            pass

        configure_eevee(self.scene)
        self.scene.render.resolution_x = STILL_RES_X
        self.scene.render.resolution_y = STILL_RES_Y
        self.scene.render.resolution_percentage = 100
        self.scene.render.image_settings.file_format = "PNG"
        self.scene.render.image_settings.color_mode = "RGB"
        self.scene.render.image_settings.color_depth = "8"

        self.props.show_earth_preview = True
        self.props.auto_resolve = False
        self.props.anim_frame_start = 1
        self.props.anim_frame_end = 3
        self.props.anim_motion_curve = "EASE_IN"
        self.props.anim_camera_preset = "ZOOM"

        create_earth_and_wait(self.state_module, self.scene)
        self._record_step("create_earth", "ok")

    def _record_oddity(self, *, scope, message, severity="warning", **data):
        entry = {
            "scope": str(scope),
            "severity": str(severity),
            "message": str(message),
        }
        if data:
            entry.update(data)
        self.report.setdefault("oddities", []).append(entry)

    def _capture_resolve_telemetry(self, *, label, quality, query, selected_place):
        resolved_tiles = sorted(str(t) for t in (self.scene.get("planetka_last_resolved_tiles", ()) or ()) if t)
        resolved_tile_count_scene = int(len(resolved_tiles))

        diag = {}
        try:
            if self.diagnostics is not None and hasattr(self.diagnostics, "read_diagnostics"):
                payload = self.diagnostics.read_diagnostics(self.scene) or {}
                if isinstance(payload, dict):
                    diag = dict(payload)
        except Exception:
            diag = {}

        def _to_int(value, default=0):
            try:
                return int(value)
            except Exception:
                return int(default)

        def _to_float(value, default=0.0):
            try:
                return float(value)
            except Exception:
                return float(default)

        resolved_tile_count_diag = _to_int(diag.get("last_tile_count", 0), 0)
        resolved_tile_count = resolved_tile_count_diag if resolved_tile_count_diag > 0 else resolved_tile_count_scene
        summary_tile_count = _to_int(self.scene.get(SCENE_KEY_LAST_RESOLVE_TILE_COUNT, 0), 0)

        entry = {
            "label": str(label),
            "quality": str(quality).upper(),
            "query": str(query),
            "selected_place": str(selected_place),
            "resolved_tile_count": int(resolved_tile_count),
            "resolved_tile_count_diag": int(resolved_tile_count_diag),
            "resolved_tile_count_scene": int(resolved_tile_count_scene),
            "resolved_tiles": list(resolved_tiles),
            "resolve_total_ms": _to_float(diag.get("last_resolve_ms", 0.0), 0.0),
            "resolve_download_ms": _to_float(diag.get("resolve_download_ms", 0.0), 0.0),
            "resolve_downloaded_mb": _to_float(diag.get("resolve_downloaded_mb", 0.0), 0.0),
            "resolve_fallback_count": _to_int(diag.get("last_fallback_count", 0), 0),
            "summary_tile_count": int(summary_tile_count),
            "summary_downloaded_mb": _to_float(self.scene.get(SCENE_KEY_LAST_RESOLVE_DOWNLOADED_MB, 0.0), 0.0),
            "summary_downloaded_gb": _to_float(self.scene.get(SCENE_KEY_LAST_RESOLVE_DOWNLOADED_GB, 0.0), 0.0),
            "summary_total_seconds": _to_float(self.scene.get(SCENE_KEY_LAST_RESOLVE_TOTAL_SECONDS, 0.0), 0.0),
        }
        self.report.setdefault("resolve_runs", []).append(entry)

        if entry["resolved_tile_count"] <= 0:
            self._record_oddity(
                scope=label,
                severity="critical",
                message="Resolve returned zero tiles.",
                quality=str(quality).upper(),
            )
        if summary_tile_count > 0 and entry["resolved_tile_count"] > 0 and summary_tile_count != entry["resolved_tile_count"]:
            self._record_oddity(
                scope=label,
                message="Summary tile count differs from resolved tile count.",
                summary_tile_count=int(summary_tile_count),
                resolved_tile_count=int(entry["resolved_tile_count"]),
            )
        if entry["resolve_fallback_count"] > 0:
            self._record_oddity(
                scope=label,
                message="Resolve used fallback tiles/textures.",
                fallback_count=int(entry["resolve_fallback_count"]),
            )

        if str(quality).upper() == "FULL":
            self.full_quality_runs.append(entry)

        return entry

    def _validate_full_quality_tile_consistency(self):
        full_runs = list(self.full_quality_runs or ())
        if len(full_runs) < 3:
            raise E2EError(
                f"Full-quality consistency check expected at least 3 runs, got {len(full_runs)}."
            )

        base = full_runs[0]
        base_tiles = tuple(base.get("resolved_tiles", ()) or ())
        mismatches = []
        for candidate in full_runs[1:]:
            candidate_tiles = tuple(candidate.get("resolved_tiles", ()) or ())
            if candidate_tiles != base_tiles:
                mismatches.append(
                    {
                        "label": str(candidate.get("label", "")),
                        "tile_count": int(len(candidate_tiles)),
                        "base_tile_count": int(len(base_tiles)),
                    }
                )

        validation = {
            "name": "commercial_full_quality_tile_consistency",
            "status": "ok" if not mismatches else "error",
            "run_labels": [str(run.get("label", "")) for run in full_runs],
            "tile_count": int(len(base_tiles)),
            "mismatches": mismatches,
        }
        self.report.setdefault("resolve_validations", []).append(validation)

        if mismatches:
            raise E2EError(
                "Full-quality tile mismatch across commercial still tests; "
                f"base={validation['run_labels'][0]} mismatches={mismatches}"
            )

        self._record_step(
            "validate_full_quality_tile_consistency",
            "ok",
            compared_runs=int(len(full_runs)),
            tile_count=int(len(base_tiles)),
        )

    def _resolve_and_render_still(self, *, label, query, country_hint, quality):
        quality_token = str(quality or "PREVIEW").strip().upper()
        self.props.texture_quality_mode = quality_token
        selected = search_place(
            self.props,
            self.state_module,
            self.geonames,
            str(query),
            country_hint=str(country_hint or "").strip() or None,
        )
        resolve_textures(
            self.state_module,
            self.scene,
            texture_quality_mode=quality_token,
        )
        telemetry = self._capture_resolve_telemetry(
            label=label,
            quality=quality_token,
            query=str(query),
            selected_place=str(selected),
        )
        output_path = self.output_dir / f"{label}.png"
        configure_png_output(
            self.scene,
            output_prefix=output_path,
            resolution_x=STILL_RES_X,
            resolution_y=STILL_RES_Y,
            resolution_percentage=100,
        )
        result = bpy.ops.render.render(write_still=True, use_viewport=False)
        if "FINISHED" not in result:
            raise E2EError(f"Still render failed for {label}: {result}")
        self._record_step(
            f"still_{label}",
            "ok",
            query=str(query),
            selected_place=str(selected),
            quality=quality_token,
            output=str(output_path),
            resolved_tile_count=int(telemetry.get("resolved_tile_count", 0)),
            resolve_downloaded_mb=float(telemetry.get("resolve_downloaded_mb", 0.0)),
            resolve_download_ms=float(telemetry.get("resolve_download_ms", 0.0)),
            resolve_total_ms=float(telemetry.get("resolve_total_ms", 0.0)),
        )

    def _run_preview_zoom_check(self, *, label, frames=3):
        frames_int = int(max(2, frames))
        self.props.anim_camera_preset = "ZOOM"
        self.props.anim_frame_start = 1
        self.props.anim_frame_end = frames_int
        self.scene.use_preview_range = False
        self.scene.frame_start = 1
        self.scene.frame_end = frames_int
        start_frame, end_frame = self.animation_tools.apply_cinematic_preview(self.scene, self.props)
        camera = getattr(self.scene, "camera", None)
        if camera is None:
            raise E2EError("Active camera missing during preview check.")

        self.scene.frame_set(int(start_frame))
        bpy.context.view_layer.update()
        loc_start = tuple(float(v) for v in camera.matrix_world.to_translation())
        rot_start = tuple(float(v) for v in camera.matrix_world.to_euler())

        self.scene.frame_set(int(end_frame))
        bpy.context.view_layer.update()
        loc_end = tuple(float(v) for v in camera.matrix_world.to_translation())
        rot_end = tuple(float(v) for v in camera.matrix_world.to_euler())

        loc_delta = math.sqrt(sum((a - b) ** 2 for a, b in zip(loc_start, loc_end)))
        rot_delta = math.sqrt(sum((a - b) ** 2 for a, b in zip(rot_start, rot_end)))
        moved = bool((loc_delta > 1e-7) or (rot_delta > 1e-7))
        if not moved:
            raise E2EError(
                f"Preview zoom did not move camera for {label} (loc_delta={loc_delta}, rot_delta={rot_delta})."
            )
        self._record_step(
            f"preview_zoom_{label}",
            "ok",
            frame_start=int(start_frame),
            frame_end=int(end_frame),
            location_delta=loc_delta,
            rotation_delta=rot_delta,
        )

    def _set_navigation_altitude_tilt(self, altitude_km, tilt_deg):
        set_navigation(
            self.props,
            self.state_module,
            nav_altitude_km=float(altitude_km),
            nav_tilt_deg=float(tilt_deg),
        )
        apply_result = bpy.ops.planetka.navigation_apply_shot()
        if "FINISHED" not in apply_result:
            raise E2EError(f"navigation_apply_shot failed: {apply_result}")
        clip_result = bpy.ops.planetka.auto_adjust_clipping()
        if "FINISHED" not in clip_result and "CANCELLED" not in clip_result:
            raise E2EError(f"auto_adjust_clipping failed: {clip_result}")
        self._record_step(
            "set_camera_altitude_tilt",
            "ok",
            altitude_km=float(altitude_km),
            tilt_deg=float(tilt_deg),
        )

    def _set_earth_radius(self, radius_bu):
        self.props.earth_radius_bu = float(radius_bu)
        apply_result = bpy.ops.planetka.navigation_apply_shot()
        if "FINISHED" not in apply_result and "CANCELLED" not in apply_result:
            raise E2EError(f"navigation_apply_shot after radius change failed: {apply_result}")
        clip_result = bpy.ops.planetka.auto_adjust_clipping()
        if "FINISHED" not in clip_result and "CANCELLED" not in clip_result:
            raise E2EError(f"auto_adjust_clipping after radius change failed: {clip_result}")
        self._record_step("set_earth_radius", "ok", earth_radius_bu=float(radius_bu))

    def _set_elevation_coefficient(self, value):
        material = bpy.data.materials.get("Planetka Earth Material")
        if material is None or getattr(material, "node_tree", None) is None:
            raise E2EError("Planetka Earth Material not found for elevation coefficient update.")
        updated = 0
        for node in tuple(getattr(material.node_tree, "nodes", ()) or ()):
            if str(getattr(node, "bl_idname", "")) != "ShaderNodeGroup":
                continue
            node_group = getattr(node, "node_tree", None)
            if str(getattr(node_group, "name", "")) != "Planetka Surface Grading Group":
                continue
            socket = getattr(node, "inputs", {}).get("Coefficient")
            if socket is None or not hasattr(socket, "default_value"):
                continue
            socket.default_value = float(value)
            updated += 1
        if updated <= 0:
            raise E2EError("Could not find Surface Grading 'Coefficient' socket.")
        self._record_step("set_elevation_coefficient", "ok", coefficient=float(value), nodes_updated=int(updated))

    def _start_final_animation(self, *, label, frames, end_altitude_km):
        frames_int = int(max(2, frames))
        self.props.anim_camera_preset = "ZOOM"
        self.props.anim_frame_start = 1
        self.props.anim_frame_end = frames_int
        self.props.anim_end_altitude_km = float(end_altitude_km)
        self.scene.use_preview_range = False
        self.scene.frame_start = 1
        self.scene.frame_end = frames_int
        output_dir = self.output_dir / label
        output_dir.mkdir(parents=True, exist_ok=True)
        configure_png_output(
            self.scene,
            output_prefix=output_dir / "frame_",
            resolution_x=ANIM_RES_X,
            resolution_y=ANIM_RES_Y,
            resolution_percentage=100,
        )
        result = bpy.ops.planetka.animation_render_headless('INVOKE_DEFAULT')
        if "RUNNING_MODAL" not in result and "FINISHED" not in result:
            raise E2EError(f"Final Animation Render did not start for {label}: {result}")
        self.waiting_final = {
            "label": str(label),
            "output_dir": output_dir,
            "expected_frames": frames_int,
            "started_at": time.time(),
            "deadline": time.time() + float(max(1800, frames_int * 60)),
            "seen_running": False,
            "invoke_result": list(result),
        }
        self._record_step(
            f"final_animation_{label}_started",
            "ok",
            output_dir=str(output_dir),
            expected_frames=frames_int,
            end_altitude_km=float(end_altitude_km),
            invoke_result=list(result),
        )

    def _poll_final_animation(self):
        wait = dict(self.waiting_final or {})
        if not wait:
            return True
        output_dir = Path(wait["output_dir"])
        expected_frames = int(wait["expected_frames"])
        frame_count = len(list_pngs(output_dir)) if output_dir.exists() else 0
        running = False
        try:
            is_job_running = getattr(getattr(bpy, "app", None), "is_job_running", None)
            if callable(is_job_running):
                running = bool(is_job_running("RENDER"))
        except Exception:
            running = False
        if running:
            self.waiting_final["seen_running"] = True
            return False
        if not bool(wait.get("seen_running")) and time.time() < (float(wait["started_at"]) + 20.0):
            return False
        if frame_count >= expected_frames > 0:
            analysis = analyze_png_directory(output_dir, max_samples=min(6, expected_frames))
            self._record_step(
                f"final_animation_{wait['label']}_done",
                "ok",
                output_dir=str(output_dir),
                frame_count=int(analysis.get("frame_count", frame_count)),
                first_frame=str(analysis.get("first_frame", "")),
                last_frame=str(analysis.get("last_frame", "")),
                has_mostly_black=bool(analysis.get("has_mostly_black", False)),
                has_pink_corrupt=bool(analysis.get("has_pink_corrupt", False)),
            )
            self.waiting_final = None
            return True
        if time.time() > float(wait["deadline"]):
            raise E2EError(
                f"Final animation timed out for {wait['label']} ({frame_count}/{expected_frames} frames)."
            )
        return False

    def _queue_step(self, name, fn):
        self.steps.append((str(name), fn))

    def _build_step_plan(self):
        account = self.expected_tier
        if account == "free":
            self._queue_step(
                "free_preview_manila_still",
                lambda: self._resolve_and_render_still(
                    label="free_manila_preview",
                    query="Manila",
                    country_hint="PH",
                    quality="PREVIEW",
                ),
            )
            self._queue_step("free_preview_zoom_3f", lambda: self._run_preview_zoom_check(label="free", frames=3))
            return

        if account == "personal":
            self._queue_step(
                "personal_preview_paris_still",
                lambda: self._resolve_and_render_still(
                    label="personal_paris_preview",
                    query="Paris",
                    country_hint="FR",
                    quality="PREVIEW",
                ),
            )
            self._queue_step(
                "personal_balanced_paris_still",
                lambda: self._resolve_and_render_still(
                    label="personal_paris_balanced",
                    query="Paris",
                    country_hint="FR",
                    quality="BALANCED",
                ),
            )
            self._queue_step("personal_preview_zoom_3f", lambda: self._run_preview_zoom_check(label="personal", frames=3))
            return

        # Commercial sequence:
        self._queue_step(
            "commercial_preview_chicago_still",
            lambda: self._resolve_and_render_still(
                label="commercial_chicago_preview",
                query="Chicago",
                country_hint="US",
                quality="PREVIEW",
            ),
        )
        self._queue_step(
            "commercial_balanced_chicago_still",
            lambda: self._resolve_and_render_still(
                label="commercial_chicago_balanced",
                query="Chicago",
                country_hint="US",
                quality="BALANCED",
            ),
        )
        self._queue_step(
            "commercial_full_chicago_still",
            lambda: self._resolve_and_render_still(
                label="commercial_chicago_full",
                query="Chicago",
                country_hint="US",
                quality="FULL",
            ),
        )
        self._queue_step("commercial_set_radius_6000", lambda: self._set_earth_radius(6000.0))
        self._queue_step(
            "commercial_full_chicago_radius6000_still",
            lambda: self._resolve_and_render_still(
                label="commercial_chicago_full_radius6000",
                query="Chicago",
                country_hint="US",
                quality="FULL",
            ),
        )
        self._queue_step("commercial_set_elevation_coef_2", lambda: self._set_elevation_coefficient(2.0))
        self._queue_step(
            "commercial_full_chicago_radius6000_elev2_still",
            lambda: self._resolve_and_render_still(
                label="commercial_chicago_full_radius6000_elev2",
                query="Chicago",
                country_hint="US",
                quality="FULL",
            ),
        )
        self._queue_step(
            "commercial_validate_full_quality_tiles",
            self._validate_full_quality_tile_consistency,
        )
        self._queue_step("commercial_set_nav_30km_65deg", lambda: self._set_navigation_altitude_tilt(30.0, 65.0))
        self._queue_step(
            "commercial_final_default",
            lambda: self._start_final_animation(
                label="commercial_final_default_radius2_elev1",
                frames=60,
                end_altitude_km=2000.0,
            ),
        )

    def _setup(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._load_api_key()

        self.base_module = enable_module(required_planetka_attr="add_earth")
        self.auth = import_submodule(self.base_module, "auth")
        self.extension_prefs = import_submodule(self.base_module, "extension_prefs")
        self.geonames = import_submodule(self.base_module, "geonames_db")
        self.state_module = import_submodule(self.base_module, "state")
        self.animation_tools = import_submodule(self.base_module, "animation_tools")
        self.diagnostics = import_submodule(self.base_module, "diagnostics")

        self.prefs = self.extension_prefs.get_prefs()
        if self.prefs is None:
            raise E2EError("Planetka prefs unavailable.")

        wait_for_geonames_ready(self.geonames)
        self._connect_account()
        self._prepare_scene()
        self._build_step_plan()
        self._write_report()
        self.started = True

    def tick(self):
        try:
            if self.finished:
                return None
            if time.time() > self.deadline:
                raise E2EError("Test deadline exceeded.")

            if not self.started:
                log(TAG, f"Starting account scenario: {self.account_email}")
                self._setup()
                return 0.25

            if self.waiting_final is not None:
                if self._poll_final_animation():
                    return 0.2
                return 0.5

            if not self.steps:
                self.report["status"] = "ok"
                self.report["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._write_report()
                log(TAG, f"PASS ({self.account_email}): report={self.report_path}")
                self.finished = True
                bpy.ops.wm.quit_blender()
                return None

            step_name, step_fn = self.steps.pop(0)
            log(TAG, f"Step ({self.account_email}): {step_name}")
            started = time.time()
            step_fn()
            self._record_step(
                f"{step_name}_timing",
                "ok",
                duration_sec=round(time.time() - started, 3),
            )
            self._write_report()
            return 0.1
        except Exception as exc:
            return self._fail(exc)


RUNNER = Runner()
bpy.app.timers.register(RUNNER.tick, first_interval=0.5)
