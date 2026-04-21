#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
if str(PROJECT_ROOT) not in __import__('sys').path:
    __import__('sys').path.insert(0, str(PROJECT_ROOT))

import tools.s2_clamp_rebuild as base

ROOT = Path('/Volumes/SSDA/Planetka Assets/S2')
OCEAN = '/Volumes/SSDA/Planetka Assets Extra/FB/ocean_pixel_final_20.exr'
WHITE = '/Volumes/SSDA/Planetka Assets Extra/FB/white_pixel_20.exr'
STATE_PATH = Path('/private/tmp/s2_resume_worker1_state.json')
DEFAULT_MARKER = (-1, -1)  # (y, x) => start full higher-z/higher-d rebuild
MAX_WORKERS = max(1, min(int(os.environ.get('PKA_WORKERS', '4')), 8))
PARALLEL_CHUNK_SIZE = max(50, int(os.environ.get('PKA_CHUNK_SIZE', '200')))


def _now() -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S')


def load_state() -> dict | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return None


def save_state(state: dict) -> None:
    state['updated_at'] = _now()
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding='utf-8')
    tmp.replace(STATE_PATH)


def build_stages(marker: tuple[int, int]) -> list[tuple[str, list, callable, int]]:
    clamp_paths, z_base_list, d_tasks_by_z = base._collect_manifest(ROOT)
    base._D_LEVELS_BY_Z = base._build_d_levels_by_z(z_base_list, d_tasks_by_z)
    print(
        f"[{_now()}] manifest z001_d001={len(clamp_paths)} "
        f"z_bases={sum(len(v) for v in z_base_list.values())} "
        f"d_targets={sum(len(v) for v in d_tasks_by_z.values())}"
    )

    stages: list[tuple[str, list, callable, int]] = []

    z2_coords = z_base_list.get(2, [])
    z2_resume = [(x, y, 2) for (x, y) in z2_coords if (y, x) > marker]
    stages.append((f"resume-z002-after-y{marker[0]:03d}-x{marker[1]:03d}", z2_resume, base._build_z_base, 25))

    for z in base.Z_BUILD_ORDER:
        if z == 2:
            continue
        coords = z_base_list.get(z, [])
        tasks = [(x, y, z) for (x, y) in coords]
        stages.append((f"rebuild-z{z:03d}", tasks, base._build_z_base, 25))

    for z in sorted(d_tasks_by_z.keys()):
        for d_effective, tasks in base._group_d_tasks_by_effective(d_tasks_by_z[z]):
            stages.append(
                (
                    f"rebuild-d-z{z:03d}-d{base._encode_d_for_name(d_effective):03d}",
                    tasks,
                    base._rebuild_d_variant,
                    100,
                )
            )

    return stages


def run() -> int:
    started = time.perf_counter()
    base.ROOT_DIR = str(ROOT)
    base.OCEAN_FALLBACK_PATH = OCEAN
    base.WHITE_FALLBACK_PATH = WHITE

    if not ROOT.is_dir():
        print(f"[{_now()}] root missing: {ROOT}")
        return 2

    state = load_state()
    if state is None:
        marker = DEFAULT_MARKER
        state = {
            'version': 1,
            'created_at': _now(),
            'marker': {'y': int(marker[0]), 'x': int(marker[1])},
            'stage_index': 0,
            'stage_offset': 0,
            'total_failures': 0,
            'completed': False,
        }
        save_state(state)
        print(f"[{_now()}] new state created marker y={marker[0]} x={marker[1]}")
    else:
        marker = (int(state.get('marker', {}).get('y', DEFAULT_MARKER[0])), int(state.get('marker', {}).get('x', DEFAULT_MARKER[1])))
        print(f"[{_now()}] loaded state marker y={marker[0]} x={marker[1]} stage_index={state.get('stage_index')} offset={state.get('stage_offset')}")
    print(f"[{_now()}] worker config max_workers={MAX_WORKERS} chunk_size={PARALLEL_CHUNK_SIZE}")

    stages = build_stages(marker)
    stage_index = int(state.get('stage_index', 0))
    stage_offset = int(state.get('stage_offset', 0))

    if stage_index >= len(stages):
        state['completed'] = True
        save_state(state)
        print(f"[{_now()}] nothing left to do")
        return 0

    for sidx in range(stage_index, len(stages)):
        label, tasks, fn, progress_every = stages[sidx]
        offset = stage_offset if sidx == stage_index else 0
        total = len(tasks)
        failed = 0
        t0 = time.perf_counter()
        print(f"[{_now()}] [{label}] start total={total} from={offset}")

        if total == 0:
            state['stage_index'] = sidx + 1
            state['stage_offset'] = 0
            save_state(state)
            print(f"[{_now()}] [{label}] no tasks")
            continue

        done = offset
        if MAX_WORKERS <= 1:
            for i in range(offset, total):
                ok, err = fn(tasks[i])
                done += 1
                if not ok:
                    failed += 1
                    state['total_failures'] = int(state.get('total_failures', 0)) + 1
                    print(f"[{_now()}] [{label}] FAIL {err}")
                if done % progress_every == 0 or done == total:
                    elapsed = time.perf_counter() - t0
                    print(f"[{_now()}] [{label}] progress {done}/{total} failed={failed} elapsed={elapsed:.1f}s")

                state['stage_index'] = sidx
                state['stage_offset'] = done
                # Persist very frequently so abrupt kill can resume almost exactly.
                if (done % 5) == 0 or (not ok) or done == total:
                    save_state(state)
        else:
            for chunk_start in range(offset, total, PARALLEL_CHUNK_SIZE):
                chunk_end = min(total, chunk_start + PARALLEL_CHUNK_SIZE)
                chunk_tasks = tasks[chunk_start:chunk_end]
                chunk_label = f"{label}-chunk-{chunk_start + 1}-{chunk_end}"
                _, chunk_failed = base._run_stage(
                    chunk_label,
                    chunk_tasks,
                    MAX_WORKERS,
                    fn,
                    progress_every=progress_every,
                )
                done = chunk_end
                failed += chunk_failed
                state['total_failures'] = int(state.get('total_failures', 0)) + int(chunk_failed)
                state['stage_index'] = sidx
                state['stage_offset'] = done
                save_state(state)
                elapsed = time.perf_counter() - t0
                print(f"[{_now()}] [{label}] progress {done}/{total} failed={failed} elapsed={elapsed:.1f}s")

        elapsed = time.perf_counter() - t0
        print(f"[{_now()}] [{label}] done total={total} failed={failed} elapsed={elapsed:.1f}s")
        state['stage_index'] = sidx + 1
        state['stage_offset'] = 0
        save_state(state)

    total_elapsed = time.perf_counter() - started
    state['completed'] = True
    save_state(state)
    print(f"[{_now()}] all done failures={state.get('total_failures',0)} elapsed={total_elapsed:.1f}s")
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
