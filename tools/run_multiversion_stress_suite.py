#!/usr/bin/env python3
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path("/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka")
CASE_SCRIPT = ROOT_DIR / "tools" / "planetka_multiversion_stress_case.py"
RENDER_DIR = Path("/Volumes/SSDA/Renders")
LOG_DIR = RENDER_DIR / "stress_logs"
API_KEY_FILE = Path("/tmp/planetka_api_key.txt")

BLENDER_BIN = {
    "4_5": "/Applications/Blender4.5.app/Contents/MacOS/Blender",
    "5_0": "/Applications/Blender5.0.app/Contents/MacOS/Blender",
    "5_1": "/Applications/Blender5.1.app/Contents/MacOS/Blender",
    "5_2": "/Applications/Blender5.2.app/Contents/MacOS/Blender",
}

VERSIONS = ("4_5", "5_0", "5_1", "5_2")
ENGINES = ("EEVEE", "CYCLES")
RADII = ("2", "6000")
RANDOM_PLACE_COUNT = 100
BASE_SEED = 20260408
AUTH_DEVICE_ID = "1de81a60-831d-4aac-9e66-e86af91a900b"


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def _log(fp, message):
    line = f"[SUITE] {_now()} {message}"
    print(line, flush=True)
    fp.write(line + "\n")
    fp.flush()


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    suite_log_path = LOG_DIR / f"planetka_multiversion_suite_{ts}.log"
    suite_status_path = LOG_DIR / f"planetka_multiversion_suite_{ts}.tsv"

    api_key = ""
    if API_KEY_FILE.exists():
        api_key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not api_key:
        print(f"Missing/empty API key file: {API_KEY_FILE}", file=sys.stderr)
        return 1

    with suite_log_path.open("w", encoding="utf-8") as slog, suite_status_path.open("w", encoding="utf-8") as ssv:
        ssv.write("run_tag\tblender\tengine\tradius\tstatus\treport\tlog\n")
        ssv.flush()
        _log(slog, f"started, status={suite_status_path}")

        run_index = 0
        for version in VERSIONS:
            blender_bin = BLENDER_BIN.get(version, "")
            if not blender_bin or not os.path.isfile(blender_bin):
                _log(slog, f"missing blender binary version={version} path={blender_bin}")
                continue
            for radius in RADII:
                for engine in ENGINES:
                    run_index += 1
                    seed = BASE_SEED + run_index
                    run_tag = f"b{version}_r{radius}_{engine.lower()}_{ts}"
                    run_log = LOG_DIR / f"{run_tag}.log"
                    report_path = RENDER_DIR / f"planetka_multiversion_stress_report_{run_tag}.json"
                    _log(
                        slog,
                        f"run={run_index} tag={run_tag} version={version} engine={engine} radius={radius} seed={seed}",
                    )

                    env = os.environ.copy()
                    env.update(
                        {
                            "PLANETKA_AUTH_API_KEY": api_key,
                            "PLANETKA_AUTH_DEVICE_ID": AUTH_DEVICE_ID,
                            "PLANETKA_FORCE_LOCAL": "1",
                            "PLANETKA_MODULE": "Planetka",
                            "PLANETKA_RENDER_DIR": str(RENDER_DIR),
                            "PLANETKA_RANDOM_PLACE_COUNT": str(RANDOM_PLACE_COUNT),
                            "PLANETKA_STRESS_SEED": str(seed),
                            "PLANETKA_RENDER_ENGINE": engine,
                            "PLANETKA_EARTH_RADIUS_BU": str(radius),
                            "PLANETKA_RUN_TAG": run_tag,
                            "PLANETKA_TEXTURE_BASE_PATH": "planetka-remote",
                        }
                    )
                    cmd = [
                        blender_bin,
                        "--background",
                        "--factory-startup",
                        "--python",
                        str(CASE_SCRIPT),
                    ]
                    with run_log.open("w", encoding="utf-8") as rlog:
                        proc = subprocess.run(
                            cmd,
                            cwd=str(ROOT_DIR),
                            env=env,
                            stdout=rlog,
                            stderr=subprocess.STDOUT,
                            text=True,
                            check=False,
                        )
                    status = "PASS" if proc.returncode == 0 else f"FAIL({proc.returncode})"
                    ssv.write(
                        f"{run_tag}\t{version}\t{engine}\t{radius}\t{status}\t{report_path}\t{run_log}\n"
                    )
                    ssv.flush()
                    _log(slog, f"done tag={run_tag} status={status}")

        _log(slog, "finished")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
