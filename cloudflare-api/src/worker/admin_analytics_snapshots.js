export const ANALYTICS_SNAPSHOT_WINDOWS = [15, 60, 360, 1440, 10080];
export const ANALYTICS_SNAPSHOT_FILTERS = ["all"];
export const ANALYTICS_SNAPSHOT_TILE_MAP_WINDOWS = [1, 3, 10];
const SNAPSHOT_CACHE_CONTROL = "private, max-age=60";
const DEFAULT_ANALYTICS_SNAPSHOT_MAX_AGE_SECONDS = 300;

function r2KeyWithPrefix(env, suffix) {
  const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
  const safeSuffix = String(suffix || "").trim().replace(/^\/+/, "");
  return prefix ? `${prefix}/${safeSuffix}` : safeSuffix;
}

export function analyticsSnapshotKey(env, minutes, access_statusFilter, tileMapMinutes) {
  return r2KeyWithPrefix(
    env,
    `Admin/analytics_snapshots/m${minutes}_${String(access_statusFilter || "all")}_tm${tileMapMinutes}.json`,
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

async function deleteJsonSnapshot(env, key) {
  const bucket = env.PLANETKA_DATA;
  if (!bucket || !key) {
    return;
  }
  await bucket.delete(key);
}

function parseSnapshotGeneratedAtUnix(snapshot) {
  const generatedAt = String(snapshot && snapshot.generated_at || "").trim();
  if (!generatedAt) {
    return 0;
  }
  const parsed = Date.parse(generatedAt);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.floor(parsed / 1000);
}

export function isAnalyticsSnapshotStale(snapshot, maxAgeSeconds = DEFAULT_ANALYTICS_SNAPSHOT_MAX_AGE_SECONDS) {
  const safeMaxAge = Math.max(1, Math.floor(Number(maxAgeSeconds) || DEFAULT_ANALYTICS_SNAPSHOT_MAX_AGE_SECONDS));
  const generatedAtUnix = parseSnapshotGeneratedAtUnix(snapshot);
  if (generatedAtUnix <= 0) {
    return true;
  }
  const ageSeconds = Math.max(0, Math.floor(Date.now() / 1000) - generatedAtUnix);
  return ageSeconds > safeMaxAge;
}

export async function loadAnalyticsSnapshot(env, minutes, access_statusFilter, tileMapMinutes) {
  return readJsonSnapshot(env, analyticsSnapshotKey(env, minutes, access_statusFilter, tileMapMinutes));
}

export async function storeAnalyticsSnapshot(env, minutes, access_statusFilter, tileMapMinutes, snapshot) {
  await writeJsonSnapshot(env, analyticsSnapshotKey(env, minutes, access_statusFilter, tileMapMinutes), snapshot);
}

export async function loadAnalyticsUsersSnapshot(env) {
  return readJsonSnapshot(env, analyticsUsersSnapshotKey(env));
}

export async function storeAnalyticsUsersSnapshot(env, snapshot) {
  await writeJsonSnapshot(env, analyticsUsersSnapshotKey(env), snapshot);
}

export async function invalidateAnalyticsSnapshots(env) {
  for (const minutes of ANALYTICS_SNAPSHOT_WINDOWS) {
    for (const access_statusFilter of ANALYTICS_SNAPSHOT_FILTERS) {
      for (const tileMapMinutes of ANALYTICS_SNAPSHOT_TILE_MAP_WINDOWS) {
        await deleteJsonSnapshot(env, analyticsSnapshotKey(env, minutes, access_statusFilter, tileMapMinutes));
      }
    }
  }
  await deleteJsonSnapshot(env, analyticsUsersSnapshotKey(env));
}

export async function buildAnalyticsSnapshotMatrix(db, env, deps) {
  const generatedAt = deps.nowIso();
  let attempted = 0;
  let stored = 0;
  let failed = 0;
  const failures = [];
  for (const minutes of ANALYTICS_SNAPSHOT_WINDOWS) {
    for (const access_statusFilter of ANALYTICS_SNAPSHOT_FILTERS) {
      for (const tileMapMinutes of ANALYTICS_SNAPSHOT_TILE_MAP_WINDOWS) {
        attempted += 1;
        try {
          const snapshot = await deps.collectAnalyticsSnapshot(
            db,
            minutes,
            access_statusFilter,
            tileMapMinutes,
            env,
          );
          await storeAnalyticsSnapshot(
            env,
            minutes,
            access_statusFilter,
            tileMapMinutes,
            {
              ...snapshot,
              generated_at: String(snapshot && snapshot.generated_at || generatedAt),
              snapshot_minutes: minutes,
              snapshot_access_status_filter: access_statusFilter,
              snapshot_tile_map_minutes: tileMapMinutes,
              snapshot_source: "scheduled_snapshot",
            },
          );
          stored += 1;
        } catch (error) {
          failed += 1;
          const failure = {
            minutes,
            access_status_filter: access_statusFilter,
            tile_map_minutes: tileMapMinutes,
            error: String(error && error.message || "analytics_snapshot_failed"),
          };
          if (failures.length < 10) {
            failures.push(failure);
          }
          console.warn(
            "planetka.analytics.snapshot_window_failed",
            JSON.stringify(failure),
          );
        }
      }
    }
  }
  return {
    generated_at: generatedAt,
    attempted_snapshots: attempted,
    stored_snapshots: stored,
    failed_snapshots: failed,
    failures,
  };
}

export async function buildAnalyticsUsersSnapshot(db, env, deps) {
  const rows = await deps.listAnalyticsUsers(db, env, {
    query: "",
    sort_by: "data_downloaded",
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
