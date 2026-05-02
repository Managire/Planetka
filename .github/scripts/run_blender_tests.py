#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


FATAL_OUTPUT_PATTERNS = (
    "Error in bpy.app.handlers",
    "Traceback (most recent call last):",
)
UI_MODE_SCRIPTS = {
    "tools/planetka_final_animation_gate.py",
}
SCRIPT_TIMEOUTS_SEC = {
    "tools/planetka_final_animation_gate.py": 900,
}


def _run(blender_bin, repo_root, script_rel):
    script_path = Path(repo_root) / script_rel
    if not script_path.is_file():
        raise FileNotFoundError(f"Test script not found: {script_path}")
    ui_mode = str(script_rel) in UI_MODE_SCRIPTS
    cmd = [str(blender_bin)]
    if not ui_mode:
        cmd.append("--background")
    cmd.extend(["--debug-python", "--python", str(script_rel)])
    if ui_mode and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        xvfb_run = shutil.which("xvfb-run")
        if not xvfb_run:
            print(
                f"[run_blender_tests] FAIL: {script_rel} requires UI mode; install xvfb-run or provide DISPLAY",
                file=sys.stderr,
            )
            return 1
        cmd = [xvfb_run, "-a", *cmd]
    print(f"[run_blender_tests] Running: {' '.join(cmd)}")
    env = os.environ.copy()
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "__PYVENV_LAUNCHER__",
    ):
        env.pop(key, None)

    try:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=SCRIPT_TIMEOUTS_SEC.get(str(script_rel)),
        )
    except subprocess.TimeoutExpired as exc:
        output = str(getattr(exc, "stdout", "") or "")
        tail = output[-12000:]
        print(f"[run_blender_tests] Output tail for {script_rel}:\n{tail}")
        print(
            f"[run_blender_tests] FAIL: {script_rel} timed out",
            file=sys.stderr,
        )
        return 1
    output = str(result.stdout or "")
    output_lower = output.lower()
    has_fatal_output = any(pattern.lower() in output_lower for pattern in FATAL_OUTPUT_PATTERNS)

    if result.returncode != 0 or has_fatal_output:
        tail = output[-12000:]
        print(f"[run_blender_tests] Output tail for {script_rel}:\n{tail}")
    elif output.strip():
        # Keep passing CI logs compact while still exposing recent context.
        print(f"[run_blender_tests] Output tail for {script_rel}:\n{output[-1500:]}")

    if has_fatal_output and result.returncode == 0:
        print(
            f"[run_blender_tests] FAIL: {script_rel} produced Blender handler traceback output",
            file=sys.stderr,
        )
        return 1
    return int(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Run Planetka Blender integration tests.")
    parser.add_argument(
        "--blender-bin",
        default=os.environ.get("BLENDER_BIN", ""),
        help="Path to Blender executable (or set BLENDER_BIN)",
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("GITHUB_WORKSPACE", os.getcwd()),
        help="Repository root directory",
    )
    args = parser.parse_args()

    if not args.blender_bin:
        raise RuntimeError("Blender binary path is required via --blender-bin or BLENDER_BIN.")

    blender_bin = Path(args.blender_bin)
    if not blender_bin.exists():
        raise FileNotFoundError(f"Blender binary not found: {blender_bin}")

    repo_root = Path(args.repo_root)
    if not repo_root.exists():
        raise FileNotFoundError(f"Repo root not found: {repo_root}")

    scripts = [
        "tools/planetka_smoke_test.py",
        "tools/planetka_schema_migration_test.py",
        "tools/planetka_regression_test.py",
        "tools/planetka_core_user_flow_gate.py",
        "tools/planetka_final_animation_gate.py",
        "tools/planetka_render_open_recovery_regression_test.py",
    ]
    for script in scripts:
        rc = _run(blender_bin, repo_root, script)
        if rc != 0:
            print(f"[run_blender_tests] FAIL: {script} exited with {rc}", file=sys.stderr)
            return rc

    print(
        "[run_blender_tests] PASS: smoke, schema migration, regression, core user-flow, "
        "final-animation gate, and render-open recovery tests passed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
