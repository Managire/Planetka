#!/usr/bin/env python3
"""Build a keyed replay .blend from a Planetka random-render report.

One report case becomes one timeline frame with keyed camera transform/lens.
Optionally marks pink frames if a pink summary JSON is provided.
"""

import argparse
import json
import os
import sys
import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

import bpy
import addon_utils


ADDON = "bl_ext.user_default.Planetka"


def _addon_enable():
    if not addon_utils.check(ADDON)[1]:
        addon_utils.enable(ADDON, default_set=False, persistent=False)


def _import_addon_submodule(submodule_name):
    candidates = [
        f"{ADDON}.{submodule_name}",
        f"Planetka.{submodule_name}",
        f"planetka.{submodule_name}",
    ]
    for mod_name in candidates:
        try:
            return __import__(mod_name, fromlist=["dummy"])
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    return None


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="Build Planetka keyed replay blend")
    parser.add_argument("--report", required=True, help="Path to random run report JSON")
    parser.add_argument("--output", required=True, help="Output .blend path")
    parser.add_argument(
        "--pink-summary",
        default="/tmp/eevee_pink_fast_summary.json",
        help="Optional pink summary JSON with pink_cases list",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional case limit (0 = all cases)",
    )
    parser.add_argument(
        "--apply-sunlight",
        action="store_true",
        help="Apply sunlight preset per frame",
    )
    return parser.parse_args(argv)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _pink_case_set(path):
    if not path:
        return set()
    if not os.path.isfile(path):
        return set()
    try:
        data = _load_json(path)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return set()
    values = data.get("pink_cases", [])
    result = set()
    for item in values:
        try:
            result.add(int(item))
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    return result


def _ensure_earth():
    extension_prefs = _import_addon_submodule("extension_prefs")
    if extension_prefs is not None and hasattr(extension_prefs, "get_earth_object"):
        try:
            earth = extension_prefs.get_earth_object()
            if earth is not None:
                return earth
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass

    earth = bpy.data.objects.get("Planetka Earth")
    if earth is not None:
        return earth

    # Last-resort fallback for completely empty scenes.
    if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
        result = bpy.ops.planetka.add_earth()
        if "FINISHED" in result:
            if extension_prefs is not None and hasattr(extension_prefs, "get_earth_object"):
                try:
                    earth = extension_prefs.get_earth_object()
                    if earth is not None:
                        return earth
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass
            earth = bpy.data.objects.get("Planetka Earth")
            if earth is not None:
                return earth

    raise RuntimeError(
        "No Planetka Earth surface found. Open an existing Planetka scene first, then rerun."
    )


def _set_nav_from_case(props, case):
    props.nav_longitude_deg = float(case.get("lon", 0.0))
    props.nav_latitude_deg = float(case.get("lat", 0.0))
    props.nav_altitude_km = float(case.get("alt_km", 0.0))
    props.nav_azimuth_deg = float(case.get("azimuth_deg", 0.0))
    props.nav_tilt_deg = float(case.get("tilt_deg", 0.0))
    props.nav_roll_deg = float(case.get("roll_deg", 0.0))
    props.nav_focal_length_mm = float(case.get("focal_mm", 50.0))


def _key_nav_properties(props, frame):
    data_paths = (
        "nav_longitude_deg",
        "nav_latitude_deg",
        "nav_altitude_km",
        "nav_azimuth_deg",
        "nav_tilt_deg",
        "nav_roll_deg",
        "nav_focal_length_mm",
    )
    for path in data_paths:
        props.keyframe_insert(data_path=path, frame=frame)


def _key_camera(scene, frame):
    cam_obj = scene.camera
    if cam_obj is None:
        for obj in scene.objects:
            if getattr(obj, "type", None) == "CAMERA":
                scene.camera = obj
                cam_obj = obj
                break
    if cam_obj is None:
        cam_data = bpy.data.cameras.new("Planetka Replay Camera")
        cam_obj = bpy.data.objects.new("Planetka Replay Camera", cam_data)
        scene.collection.objects.link(cam_obj)
        scene.camera = cam_obj
    cam_obj.keyframe_insert(data_path="location", frame=frame)
    cam_obj.keyframe_insert(data_path="rotation_euler", frame=frame)
    if cam_obj.data is not None:
        cam_obj.data.keyframe_insert(data_path="lens", frame=frame)


def _main():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    args = _parse_args(argv)

    _addon_enable()
    state = __import__(f"{ADDON}.state", fromlist=["dummy"])

    report = _load_json(args.report)
    cases = list(report.get("cases", []) or [])
    if args.limit and args.limit > 0:
        cases = cases[: int(args.limit)]
    if not cases:
        raise RuntimeError("No cases found in report JSON")

    pink_cases = _pink_case_set(args.pink_summary)

    _ensure_earth()
    scene = bpy.context.scene
    props = scene.planetka

    # Clean previous timeline markers to avoid duplicates on reruns.
    for marker in list(scene.timeline_markers):
        scene.timeline_markers.remove(marker)

    scene.frame_start = 1
    scene.frame_end = len(cases)
    scene.frame_set(1)

    keyed = 0
    pink_markers = 0
    for idx, case in enumerate(cases, start=1):
        scene.frame_set(idx)
        _set_nav_from_case(props, case)
        state.update_navigation_shot(props, bpy.context)

        if args.apply_sunlight:
            preset = str(case.get("sunlight_preset", "") or "").strip()
            if preset:
                try:
                    bpy.ops.planetka.sunlight_preset(preset=preset)
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass

        _key_nav_properties(props, idx)
        _key_camera(scene, idx)

        case_number = int(case.get("case", idx) or idx)
        if case_number in pink_cases:
            scene.timeline_markers.new(name=f"PINK_{case_number:04d}", frame=idx)
            pink_markers += 1
        keyed += 1

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=output_path, copy=False)
    print(
        json.dumps(
            {
                "ok": True,
                "output": output_path,
                "cases_keyed": keyed,
                "pink_markers": pink_markers,
                "frame_start": int(scene.frame_start),
                "frame_end": int(scene.frame_end),
            }
        )
    )


if __name__ == "__main__":
    _main()
