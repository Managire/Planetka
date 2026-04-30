#!/usr/bin/env python3
"""Planetka hermetic core user-flow gate.

Purpose:
- validate common user flow end-to-end with local fallback textures
- assert real outcomes (camera/light/material state and render sanity), not only operator return flags
- verify account-tier quality gating using synthetic auth payloads (no network)

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --debug-python \
    --python tools/planetka_core_user_flow_gate.py
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bpy

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from planetka_e2e_common import (
    E2EError,
    analyze_render_image,
    configure_eevee,
    configure_png_output,
    create_earth_and_wait,
    enable_module,
    ensure_camera,
    ensure_standard_world,
    import_submodule,
    purge_planetka_data,
    resolve_textures,
    search_place,
    wait_for_geonames_ready,
    write_json,
)

TAG = "[Planetka Core User Flow Gate]"
REPORT_PATH = Path(tempfile.gettempdir()) / "planetka_core_user_flow_gate_report.json"
FALLBACK_DIR = Path(_REPO_ROOT) / "Resources" / "Fallback Images"


def _log(message):
    print(f"{TAG} {message}", flush=True)


def _assert(condition, message):
    if not condition:
        raise E2EError(str(message))


def _camera_signature(camera):
    if camera is None:
        return None
    try:
        loc = tuple(round(float(v), 8) for v in camera.matrix_world.to_translation())
        rot = tuple(round(float(v), 8) for v in camera.matrix_world.to_euler())
        return loc + rot
    except Exception:
        return None


def _wait_for_camera_change(scene, previous_signature, timeout_sec=3.0):
    deadline = time.time() + float(max(0.2, timeout_sec))
    while time.time() < deadline:
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        current = _camera_signature(getattr(scene, "camera", None))
        if current is not None and previous_signature is not None and current != previous_signature:
            return current, True
        time.sleep(0.05)
    current = _camera_signature(getattr(scene, "camera", None))
    return current, bool(current is not None and current != previous_signature)


def _make_texture_source_tree(base_dir):
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    rules = (
        ("S2", "S2_", "ocean_pixel_final_20.exr"),
        ("EL", "EL_", "black_pixel_20.exr"),
        ("WT", "WT_", "blue_pixel_20.exr"),
    )
    for folder_name, prefix, source_name in rules:
        source = FALLBACK_DIR / source_name
        _assert(source.is_file(), f"Missing fallback texture sample: {source}")
        folder = base / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, folder / f"{prefix}x000_y000_z360_d360.exr")
        shutil.copyfile(source, folder / f"{prefix}x180_y000_z180_d180.exr")
    (base / "PO").mkdir(parents=True, exist_ok=True)


def _get_material_displacement_mode(material):
    if material is None:
        return ""
    try:
        cycles_settings = getattr(material, "cycles", None)
        if cycles_settings is not None and hasattr(cycles_settings, "displacement_method"):
            mode = str(getattr(cycles_settings, "displacement_method", "") or "").strip().upper()
            if mode:
                return mode
    except Exception:
        pass
    try:
        if hasattr(material, "displacement_method"):
            return str(getattr(material, "displacement_method", "") or "").strip().upper()
    except Exception:
        pass
    return ""


def _apply_tier_payload(auth_module, prefs, tier):
    tier_token = str(tier or "").strip().lower()
    _assert(tier_token in {"free", "personal", "commercial"}, f"Invalid tier token: {tier}")
    payload = {
        "email": f"{tier_token}@planetka.test",
        "access_token": f"test-access-{tier_token}",
        "refresh_token": f"test-refresh-{tier_token}",
        "plan_code": tier_token,
        "account_tier": tier_token,
        "stored_plan_code": tier_token,
        "stored_account_tier": tier_token,
        "quality_access_plan_code": tier_token,
        "commercial_use_allowed": bool(tier_token == "commercial"),
        "unrestricted_quality_access": False,
    }
    auth_module.clear_auth_session(prefs=prefs, state="logged_out", status_message="")
    auth_module._apply_auth_payload(prefs, payload, login_state="authenticated", status_message="")
    resolved_tier = str(auth_module.get_account_tier(prefs) or "").strip().lower()
    _assert(resolved_tier == tier_token, f"Tier payload apply mismatch: expected={tier_token} got={resolved_tier}")


def _operator_ok(result):
    try:
        return "FINISHED" in result
    except Exception:
        return False


def _operator_cancelled(result):
    try:
        return "CANCELLED" in result
    except Exception:
        return False


def _set_quality_and_expect(mode, expected_ok, report_entry):
    try:
        result = bpy.ops.planetka.set_texture_quality_and_resolve(texture_quality_mode=str(mode))
    except RuntimeError as exc:
        error_text = str(exc or "")
        report_entry["exception"] = error_text
        if bool(expected_ok):
            raise
        denied_markers = (
            "PKA-RES-003",
            "requires Personal or Commercial",
            "requires Commercial",
            "not available for this account tier",
        )
        _assert(
            any(marker in error_text for marker in denied_markers),
            f"Unexpected error for denied {mode}: {error_text}",
        )
        report_entry["result"] = ["CANCELLED"]
        report_entry["ok"] = False
        report_entry["cancelled"] = True
        return
    ok = _operator_ok(result)
    cancelled = _operator_cancelled(result)
    report_entry["result"] = list(result)
    report_entry["ok"] = bool(ok)
    report_entry["cancelled"] = bool(cancelled)
    if bool(expected_ok):
        _assert(ok, f"Expected {mode} to succeed, got {result}")
    else:
        _assert(cancelled and not ok, f"Expected {mode} to be rejected, got {result}")


def _render_checkpoint(scene, output_dir, label):
    output = Path(output_dir) / f"{label}.png"
    configure_png_output(
        scene,
        output_prefix=output,
        resolution_x=960,
        resolution_y=540,
        resolution_percentage=100,
    )
    render_result = bpy.ops.render.render(write_still=True, use_viewport=False)
    _assert(_operator_ok(render_result), f"Render failed for {label}: {render_result}")
    analysis = analyze_render_image(output)
    _assert(not bool(analysis.get("mostly_black", False)), f"Render is mostly black for {label}")
    _assert(not bool(analysis.get("pink_corrupt", False)), f"Render has pink corruption for {label}")
    return {
        "path": str(output),
        "analysis": analysis,
    }


def main():
    started = time.time()
    temp_dirs = []
    report = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "steps": [],
        "tier_matrix": [],
        "renders": [],
    }

    def record_step(name, **data):
        payload = {"step": str(name), "ok": True}
        payload.update(data)
        report["steps"].append(payload)
        _log(f"Step OK: {name}")

    try:
        base_module = enable_module(required_planetka_attr="add_earth")
        extension_prefs = import_submodule(base_module, "extension_prefs")
        geonames = import_submodule(base_module, "geonames_db")
        state = import_submodule(base_module, "state")
        auth = import_submodule(base_module, "auth")

        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")

        source_root = tempfile.mkdtemp(prefix="planetka_core_flow_source_")
        temp_dirs.append(source_root)
        _make_texture_source_tree(source_root)
        prefs.texture_base_path = source_root

        output_dir = tempfile.mkdtemp(prefix="planetka_core_flow_renders_")
        temp_dirs.append(output_dir)

        purge_planetka_data()
        scene = bpy.context.scene
        ensure_camera(scene, name="Planetka Core Flow Camera")
        ensure_standard_world(scene)
        configure_eevee(scene)

        props = getattr(scene, "planetka", None)
        _assert(props is not None, "scene.planetka is unavailable.")
        props.auto_resolve = True
        props.show_earth_preview = False

        create_earth_and_wait(state, scene)
        surface = bpy.data.objects.get("Planetka Earth Surface")
        sunlight = bpy.data.objects.get("Planetka Sunlight")
        _assert(surface is not None, "Planetka Earth Surface missing after Create Earth.")
        _assert(sunlight is not None, "Planetka Sunlight missing after Create Earth.")
        _assert(str(getattr(sunlight, "type", "")) == "LIGHT", "Planetka Sunlight is not a light object.")
        _assert(str(getattr(getattr(sunlight, "data", None), "type", "")) == "SUN", "Planetka Sunlight data type is not SUN.")

        material = bpy.data.materials.get("Planetka Earth Material")
        _assert(material is not None, "Planetka Earth Material missing.")
        displacement_mode = _get_material_displacement_mode(material)
        _assert(
            displacement_mode in {"BOTH", "DISPLACEMENT_AND_BUMP", "DISPLACEMENT", "DISPLACEMENT_ONLY"},
            f"Material displacement mode invalid: {displacement_mode}",
        )
        record_step("create_earth_core_assets", displacement_mode=displacement_mode)

        # Sunlight callbacks: assert transform + strength updates reach the actual sun object.
        sun_rot_before = tuple(float(v) for v in getattr(sunlight, "rotation_euler", (0.0, 0.0, 0.0)))
        props.sunlight_longitude_deg = float(getattr(props, "sunlight_longitude_deg", 0.0)) + 25.0
        props.sunlight_seasonal_tilt_deg = float(getattr(props, "sunlight_seasonal_tilt_deg", 0.0)) + 5.0
        state.update_sunlight_controls(props, bpy.context)
        sun_rot_after = tuple(float(v) for v in getattr(sunlight, "rotation_euler", (0.0, 0.0, 0.0)))
        _assert(sun_rot_before != sun_rot_after, "Sunlight rotation did not update from props callback.")

        props.sunlight_strength = 23.0
        state.update_sunlight_strength(props, bpy.context)
        light_data = getattr(sunlight, "data", None)
        energy = float(getattr(light_data, "energy", 0.0) or 0.0)
        _assert(abs(energy - 23.0) <= 1e-4, f"Sunlight strength did not apply to light data: {energy}")

        sun_preset_result = bpy.ops.planetka.sunlight_preset(preset="MID_MORNING")
        _assert(_operator_ok(sun_preset_result), f"Sunlight preset failed: {sun_preset_result}")
        _assert(str(getattr(props, "sunlight_last_preset", "") or "") == "MID_MORNING", "Sunlight preset did not persist on props.")
        record_step("sunlight_controls", applied_energy=energy, preset_result=list(sun_preset_result))

        # Place Search must move camera without manual lon/lat nudge.
        wait_for_geonames_ready(geonames, timeout_sec=240.0)
        cam_before = _camera_signature(getattr(scene, "camera", None))
        selected_name = search_place(props, state, geonames, "Bratislava", country_hint="SK", wait_sec=6.0)
        cam_after, moved = _wait_for_camera_change(scene, cam_before, timeout_sec=3.0)
        _assert(str(selected_name or "").strip(), "Place Search returned empty selection.")
        _assert(moved, "Place Search did not move camera automatically.")
        record_step(
            "place_search_moves_camera",
            selected_place=str(selected_name),
            camera_before=cam_before,
            camera_after=cam_after,
        )

        # Full Globe preset must apply and move camera.
        cam_before_full = _camera_signature(getattr(scene, "camera", None))
        preset_result = bpy.ops.planetka.navigation_preset(preset="HIGH_ORBIT")
        _assert(_operator_ok(preset_result), f"Navigation preset HIGH_ORBIT failed: {preset_result}")
        cam_after_full, moved_full = _wait_for_camera_change(scene, cam_before_full, timeout_sec=2.0)
        _assert(moved_full, "Full Globe preset did not move camera.")
        _assert(float(getattr(props, "nav_altitude_km", 0.0) or 0.0) > 0.0, "Full Globe preset produced non-positive altitude.")
        record_step(
            "full_globe_preset",
            result=list(preset_result),
            nav_altitude_km=float(getattr(props, "nav_altitude_km", 0.0) or 0.0),
            camera_before=cam_before_full,
            camera_after=cam_after_full,
        )

        # Earth radius change must keep scene operational (resolve + render valid).
        props.earth_radius_bu = 3.5
        apply_radius = bpy.ops.planetka.navigation_apply_shot()
        _assert(_operator_ok(apply_radius) or _operator_cancelled(apply_radius), f"navigation_apply_shot failed after radius change: {apply_radius}")
        resolve_textures(state, scene, texture_quality_mode="PREVIEW")
        report["renders"].append(_render_checkpoint(scene, output_dir, "after_radius_change"))
        record_step("earth_radius_change", earth_radius_bu=float(getattr(props, "earth_radius_bu", 0.0) or 0.0), apply_result=list(apply_radius))

        # Tier quality gating matrix (synthetic auth payload, hermetic).
        matrix = (
            ("free", {"PREVIEW": True, "BALANCED": False, "FULL": False}),
            ("personal", {"PREVIEW": True, "BALANCED": True, "FULL": False}),
            ("commercial", {"PREVIEW": True, "BALANCED": True, "FULL": True}),
        )
        for tier_name, expectations in matrix:
            _apply_tier_payload(auth, prefs, tier_name)
            for mode in ("PREVIEW", "BALANCED", "FULL"):
                entry = {
                    "tier": tier_name,
                    "mode": mode,
                    "expected_ok": bool(expectations[mode]),
                }
                _set_quality_and_expect(mode, bool(expectations[mode]), entry)
                report["tier_matrix"].append(entry)

        # Final sanity render at commercial/full.
        report["renders"].append(_render_checkpoint(scene, output_dir, "commercial_full_sanity"))
        record_step("tier_quality_matrix")

        report["status"] = "ok"
        report["elapsed_sec"] = round(time.time() - started, 3)
        report["output_dir"] = str(output_dir)
        write_json(REPORT_PATH, report)
        _log(f"PASS: report={REPORT_PATH}")
        return 0

    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        report["elapsed_sec"] = round(time.time() - started, 3)
        write_json(REPORT_PATH, report)
        _log(f"FAIL: {exc}")
        traceback.print_exc()
        return 1
    finally:
        for path in temp_dirs:
            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
