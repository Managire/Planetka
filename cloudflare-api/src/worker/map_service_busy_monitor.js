const MAP_SERVICE_BUSY_KEY = "planetka-maps";
const MAP_SERVICE_BUSY_WARNING_SECONDS = 60;
const MAP_SERVICE_BUSY_PERIOD_GAP_SECONDS = 90;
const MAP_SERVICE_BUSY_RESOLVE_QUIET_SECONDS = 60;
const MAP_SERVICE_BUSY_RECENT_LIMIT = 30;

function nowIsoFromDeps(deps) {
  return deps && typeof deps.nowIso === "function" ? deps.nowIso() : new Date().toISOString();
}

function parseIsoMs(value) {
  const ms = Date.parse(String(value || ""));
  return Number.isFinite(ms) ? ms : 0;
}

function clampNonNegative(value) {
  const numeric = Number.parseInt(value, 10);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function durationSeconds(startIso, endIso) {
  const startMs = parseIsoMs(startIso);
  const endMs = parseIsoMs(endIso);
  if (!startMs || !endMs || endMs <= startMs) return 0;
  return Math.floor((endMs - startMs) / 1000);
}

function randomSuffix() {
  if (typeof crypto !== "undefined" && crypto && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

function normalizeText(value, maxLength = 240) {
  return String(value || "").trim().slice(0, maxLength);
}

function normalizeLevel(value) {
  const numeric = Number.parseInt(value, 10);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

function mapBusyEventId(nowIso) {
  return `map_busy_${Date.parse(nowIso) || Date.now()}_${randomSuffix()}`;
}

export async function ensureMapServiceBusyTables(db, deps) {
  await deps.dbRun(db, `CREATE TABLE IF NOT EXISTS map_service_busy_events (
    id TEXT PRIMARY KEY,
    period_key TEXT NOT NULL UNIQUE,
    service_name TEXT NOT NULL DEFAULT 'planetka-maps',
    status TEXT NOT NULL DEFAULT 'active',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved_at TEXT,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    event_count INTEGER NOT NULL DEFAULT 0,
    warning_threshold_seconds INTEGER NOT NULL DEFAULT 60,
    last_path TEXT,
    last_product_id TEXT,
    last_level INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )`);
  await deps.dbRun(db, `CREATE INDEX IF NOT EXISTS idx_map_service_busy_events_recent ON map_service_busy_events(last_seen_at DESC)`);
  await deps.dbRun(db, `CREATE INDEX IF NOT EXISTS idx_map_service_busy_events_status ON map_service_busy_events(status, last_seen_at DESC)`);

  await deps.dbRun(db, `CREATE TABLE IF NOT EXISTS map_service_busy_state (
    key TEXT PRIMARY KEY,
    active_period_key TEXT,
    active_since TEXT,
    last_seen_at TEXT,
    event_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
  )`);
}

export async function recordMapServiceBusy(db, deps, event = {}) {
  await ensureMapServiceBusyTables(db, deps);
  const now = normalizeText(event.now || nowIsoFromDeps(deps), 64) || new Date().toISOString();
  const state = await deps.dbGet(
    db,
    `SELECT active_period_key, active_since, last_seen_at, event_count FROM map_service_busy_state WHERE key = ? LIMIT 1`,
    [MAP_SERVICE_BUSY_KEY],
  );
  const lastSeenMs = parseIsoMs(state && state.last_seen_at);
  const nowMs = parseIsoMs(now) || Date.now();
  const gapSeconds = lastSeenMs ? Math.floor((nowMs - lastSeenMs) / 1000) : Number.POSITIVE_INFINITY;
  const shouldStartNew = !state || !state.active_period_key || gapSeconds > MAP_SERVICE_BUSY_PERIOD_GAP_SECONDS;
  const periodKey = shouldStartNew ? mapBusyEventId(now) : String(state.active_period_key || mapBusyEventId(now));
  const firstSeen = shouldStartNew ? now : String(state.active_since || now);
  const nextEventCount = shouldStartNew ? 1 : clampNonNegative(state && state.event_count) + 1;
  const lastPath = normalizeText(event.path || event.pathname || "");
  const lastProductId = normalizeText(event.product_id || event.productId || "", 120);
  const lastLevel = normalizeLevel(event.level);
  const lastError = normalizeText(event.error || event.status || "map_service_busy");
  const duration = durationSeconds(firstSeen, now);

  await deps.dbRun(
    db,
    `INSERT INTO map_service_busy_events (
      id, period_key, service_name, status, first_seen_at, last_seen_at, duration_seconds, event_count,
      warning_threshold_seconds, last_path, last_product_id, last_level, last_error, created_at, updated_at
    ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(period_key) DO UPDATE SET
      status = 'active',
      last_seen_at = excluded.last_seen_at,
      duration_seconds = excluded.duration_seconds,
      event_count = excluded.event_count,
      warning_threshold_seconds = excluded.warning_threshold_seconds,
      last_path = excluded.last_path,
      last_product_id = excluded.last_product_id,
      last_level = excluded.last_level,
      last_error = excluded.last_error,
      updated_at = excluded.updated_at`,
    [
      periodKey,
      periodKey,
      MAP_SERVICE_BUSY_KEY,
      firstSeen,
      now,
      duration,
      nextEventCount,
      MAP_SERVICE_BUSY_WARNING_SECONDS,
      lastPath,
      lastProductId,
      lastLevel,
      lastError,
      now,
      now,
    ],
  );

  await deps.dbRun(
    db,
    `INSERT INTO map_service_busy_state (key, active_period_key, active_since, last_seen_at, event_count, updated_at)
     VALUES (?, ?, ?, ?, ?, ?)
     ON CONFLICT(key) DO UPDATE SET
       active_period_key = excluded.active_period_key,
       active_since = excluded.active_since,
       last_seen_at = excluded.last_seen_at,
       event_count = excluded.event_count,
       updated_at = excluded.updated_at`,
    [MAP_SERVICE_BUSY_KEY, periodKey, firstSeen, now, nextEventCount, now],
  );

  return { ok: true, period_key: periodKey, duration_seconds: duration, event_count: nextEventCount };
}

export async function resolveMapServiceBusyIfQuiet(db, deps, options = {}) {
  await ensureMapServiceBusyTables(db, deps);
  const now = normalizeText(options.now || nowIsoFromDeps(deps), 64) || new Date().toISOString();
  const quietSeconds = clampNonNegative(options.quiet_seconds) || MAP_SERVICE_BUSY_RESOLVE_QUIET_SECONDS;
  const state = await deps.dbGet(
    db,
    `SELECT active_period_key, active_since, last_seen_at FROM map_service_busy_state WHERE key = ? LIMIT 1`,
    [MAP_SERVICE_BUSY_KEY],
  );
  if (!state || !state.active_period_key || !state.last_seen_at) {
    return { ok: true, resolved: false };
  }
  const silenceSeconds = durationSeconds(String(state.last_seen_at), now);
  if (silenceSeconds < quietSeconds) {
    return { ok: true, resolved: false, silence_seconds: silenceSeconds };
  }
  const activeSince = String(state.active_since || state.last_seen_at || now);
  const lastSeen = String(state.last_seen_at || now);
  await deps.dbRun(
    db,
    `UPDATE map_service_busy_events
     SET status = 'resolved', resolved_at = ?, duration_seconds = ?, updated_at = ?
     WHERE period_key = ? AND status = 'active'`,
    [lastSeen, durationSeconds(activeSince, lastSeen), now, String(state.active_period_key)],
  );
  await deps.dbRun(
    db,
    `UPDATE map_service_busy_state
     SET active_period_key = NULL, active_since = NULL, last_seen_at = NULL, event_count = 0, updated_at = ?
     WHERE key = ?`,
    [now, MAP_SERVICE_BUSY_KEY],
  );
  return { ok: true, resolved: true, period_key: String(state.active_period_key) };
}

export async function collectMapServiceBusyHealth(db, deps, options = {}) {
  await resolveMapServiceBusyIfQuiet(db, deps, options);
  const now = normalizeText(options.now || nowIsoFromDeps(deps), 64) || new Date().toISOString();
  const limit = Math.max(1, Math.min(100, clampNonNegative(options.limit) || MAP_SERVICE_BUSY_RECENT_LIMIT));
  const active = await deps.dbGet(
    db,
    `SELECT * FROM map_service_busy_events WHERE status = 'active' ORDER BY last_seen_at DESC LIMIT 1`,
    [],
  );
  const warningRows = await deps.dbAll(
    db,
    `SELECT * FROM map_service_busy_events
     WHERE duration_seconds >= ?
        OR (status = 'active' AND (strftime('%s', ?) - strftime('%s', first_seen_at)) >= ?)
     ORDER BY last_seen_at DESC
     LIMIT ?`,
    [MAP_SERVICE_BUSY_WARNING_SECONDS, now, MAP_SERVICE_BUSY_WARNING_SECONDS, limit],
  );
  const recentRows = await deps.dbAll(
    db,
    `SELECT * FROM map_service_busy_events ORDER BY last_seen_at DESC LIMIT ?`,
    [limit],
  );
  const activeDuration = active ? durationSeconds(String(active.first_seen_at || now), now) : 0;
  return {
    available: true,
    service_name: MAP_SERVICE_BUSY_KEY,
    warning_threshold_seconds: MAP_SERVICE_BUSY_WARNING_SECONDS,
    active: active ? { ...active, current_duration_seconds: activeDuration } : null,
    warning_count: Array.isArray(warningRows) ? warningRows.length : 0,
    warnings: Array.isArray(warningRows) ? warningRows.map((row) => ({
      ...row,
      current_duration_seconds: String(row && row.status || "") === "active"
        ? durationSeconds(String(row && row.first_seen_at || now), now)
        : clampNonNegative(row && row.duration_seconds),
    })) : [],
    recent: Array.isArray(recentRows) ? recentRows.map((row) => ({
      ...row,
      current_duration_seconds: String(row && row.status || "") === "active"
        ? durationSeconds(String(row && row.first_seen_at || now), now)
        : clampNonNegative(row && row.duration_seconds),
    })) : [],
  };
}
