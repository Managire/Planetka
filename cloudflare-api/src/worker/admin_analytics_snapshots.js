export const ANALYTICS_SNAPSHOT_WINDOWS = [15, 60, 360, 1440, 10080];
export const ANALYTICS_SNAPSHOT_PLAN_FILTERS = ["all", "lite", "pro"];
export const ANALYTICS_SNAPSHOT_TILE_MAP_WINDOWS = [1, 3, 10];
const SNAPSHOT_CACHE_CONTROL = "private, max-age=60";

function r2KeyWithPrefix(env, suffix) {
  const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
  const safeSuffix = String(suffix || "").trim().replace(/^\/+/, "");
  return prefix ? `${prefix}/${safeSuffix}` : safeSuffix;
}

export function analyticsSnapshotKey(env, minutes, planFilter, tileMapMinutes) {
  return r2KeyWithPrefix(
    env,
    `Admin/analytics_snapshots/m${minutes}_${String(planFilter || "all")}_tm${tileMapMinutes}.json`,
  );
}

export function analyticsUsersSnapshotKey(env) {
  return r2KeyWithPrefix(env, "Admin/analytics_snapshots/users.json");
}

async function readJsonSnapshot(env, key) {
  const bucket = env.PLANETKA_DATA;
  if (!bucket || !key) {
    return null;
  }
  const object = await bucket.get(key);
  if (!object || !object.body) {
    return null;
  }
  const raw = await object.text();
  const parsed = JSON.parse(String(raw || "{}"));
  return parsed && typeof parsed === "object" ? parsed : null;
}

async function writeJsonSnapshot(env, key, payload) {
  const bucket = env.PLANETKA_DATA;
  if (!bucket || !key) {
    return;
  }
  await bucket.put(
    key,
    JSON.stringify(payload),
    {
      httpMetadata: {
        contentType: "application/json; charset=utf-8",
        cacheControl: SNAPSHOT_CACHE_CONTROL,
      },
    },
  );
}

export async function loadAnalyticsSnapshot(env, minutes, planFilter, tileMapMinutes) {
  return readJsonSnapshot(env, analyticsSnapshotKey(env, minutes, planFilter, tileMapMinutes));
}

export async function storeAnalyticsSnapshot(env, minutes, planFilter, tileMapMinutes, snapshot) {
  await writeJsonSnapshot(env, analyticsSnapshotKey(env, minutes, planFilter, tileMapMinutes), snapshot);
}

export async function loadAnalyticsUsersSnapshot(env) {
  return readJsonSnapshot(env, analyticsUsersSnapshotKey(env));
}

export async function storeAnalyticsUsersSnapshot(env, snapshot) {
  await writeJsonSnapshot(env, analyticsUsersSnapshotKey(env), snapshot);
}

export async function buildAnalyticsSnapshotMatrix(db, env, deps) {
  const generatedAt = deps.nowIso();
  let stored = 0;
  for (const minutes of ANALYTICS_SNAPSHOT_WINDOWS) {
    for (const planFilter of ANALYTICS_SNAPSHOT_PLAN_FILTERS) {
      for (const tileMapMinutes of ANALYTICS_SNAPSHOT_TILE_MAP_WINDOWS) {
        const snapshot = await deps.collectAnalyticsSnapshot(
          db,
          minutes,
          planFilter,
          tileMapMinutes,
          env,
        );
        await storeAnalyticsSnapshot(
          env,
          minutes,
          planFilter,
          tileMapMinutes,
          {
            ...snapshot,
            generated_at: String(snapshot && snapshot.generated_at || generatedAt),
            snapshot_minutes: minutes,
            snapshot_plan_filter: planFilter,
            snapshot_tile_map_minutes: tileMapMinutes,
            snapshot_source: "scheduled_snapshot",
          },
        );
        stored += 1;
      }
    }
  }
  return {
    generated_at: generatedAt,
    stored_snapshots: stored,
  };
}

export async function buildAnalyticsUsersSnapshot(db, env, deps) {
  const rows = await deps.listAnalyticsUsers(db, env, {
    query: "",
    sort_by: "month",
    sort_dir: "desc",
    limit: 5000,
  });
  const snapshot = {
    generated_at: deps.nowIso(),
    rows: Array.isArray(rows) ? rows : [],
    total_rows: Array.isArray(rows) ? rows.length : 0,
    snapshot_source: "scheduled_snapshot",
  };
  await storeAnalyticsUsersSnapshot(env, snapshot);
  return snapshot;
}
