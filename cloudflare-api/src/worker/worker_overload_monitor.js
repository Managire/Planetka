const DEFAULT_WORKER_OVERLOAD_MONITOR_WORKERS = "planetka-auth,planetka-tiles,planetka-analytics";
const DEFAULT_WORKER_OVERLOAD_LOOKBACK_MINUTES = 15;
const DEFAULT_WORKER_OVERLOAD_RECENT_LIMIT = 20;

function normalizeWorkerName(value) {
  return String(value || "").trim();
}

function normalizeStatus(value) {
  return String(value || "").trim();
}

function workerOverloadNames(env = {}) {
  const raw = String(env.WORKER_OVERLOAD_MONITOR_WORKERS || DEFAULT_WORKER_OVERLOAD_MONITOR_WORKERS).trim();
  return raw.split(",")
    .map(normalizeWorkerName)
    .filter(Boolean)
    .filter((name, index, names) => names.indexOf(name) === index);
}

function isOverloadStatus(status) {
  const normalized = normalizeStatus(status).toLowerCase();
  return normalized === "exceededresources"
    || normalized === "exceeded_resources"
    || normalized === "exceededcpu"
    || normalized === "exceeded_cpu"
    || normalized === "exceededmemory"
    || normalized === "exceeded_memory"
    || normalized.includes("exceeded");
}

function isoFromUnix(seconds) {
  return new Date(Math.max(0, Number(seconds) || 0) * 1000).toISOString();
}

function minuteBucketIso(value) {
  const ms = Date.parse(String(value || ""));
  const safeMs = Number.isFinite(ms) ? ms : Date.now();
  return new Date(Math.floor(safeMs / 60000) * 60000).toISOString();
}

function parseNonNegative(value, deps) {
  if (deps && typeof deps.parseNonNegativeInteger === "function") {
    return deps.parseNonNegativeInteger(value, 0);
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function clampNonNegative(value, deps) {
  if (deps && typeof deps.clampNonNegativeInt === "function") {
    return deps.clampNonNegativeInt(value);
  }
  return Math.max(0, parseNonNegative(value, deps));
}

export async function ensureWorkerOverloadTables(db, deps) {
  await deps.dbRun(db, `CREATE TABLE IF NOT EXISTS worker_overload_events (
    id TEXT PRIMARY KEY,
    detected_at TEXT NOT NULL,
    event_window_start TEXT NOT NULL,
    event_window_end TEXT NOT NULL,
    worker_name TEXT NOT NULL,
    status TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    cpu_time_p50_ms REAL NOT NULL DEFAULT 0,
    cpu_time_p99_ms REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'cloudflare_graphql',
    source_json TEXT,
    alerted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(worker_name, status, event_window_start)
  )`);
  await deps.dbRun(db, `CREATE INDEX IF NOT EXISTS idx_worker_overload_events_created ON worker_overload_events(created_at DESC)`);
  await deps.dbRun(db, `CREATE INDEX IF NOT EXISTS idx_worker_overload_events_worker_created ON worker_overload_events(worker_name, created_at DESC)`);

  await deps.dbRun(db, `CREATE TABLE IF NOT EXISTS worker_overload_monitor_state (
    key TEXT PRIMARY KEY,
    last_checked_at TEXT,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
  )`);
}

async function fetchWorkerInvocationRows(env, workerName, startIso, endIso, deps) {
  const accountTag = String(env.CLOUDFLARE_ACCOUNT_ID || env.CF_ACCOUNT_ID || "").trim();
  const apiToken = String(env.CLOUDFLARE_GRAPHQL_API_TOKEN || env.CLOUDFLARE_API_TOKEN || "").trim();
  if (!accountTag || !apiToken) {
    return { ok: false, error: "missing_cloudflare_graphql_credentials" };
  }
  const query = `
    query PlanetkaWorkerOverloadStatus($accountTag: string, $datetimeStart: string, $datetimeEnd: string, $scriptName: string) {
      viewer {
        accounts(filter: { accountTag: $accountTag }) {
          workersInvocationsAdaptive(limit: 100, filter: {
            scriptName: $scriptName,
            datetime_geq: $datetimeStart,
            datetime_leq: $datetimeEnd
          }) {
            sum { requests errors }
            quantiles { cpuTimeP50 cpuTimeP99 }
            dimensions { datetime scriptName status }
          }
        }
      }
    }
  `;
  const response = await fetch("https://api.cloudflare.com/client/v4/graphql", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      variables: {
        accountTag,
        datetimeStart: startIso,
        datetimeEnd: endIso,
        scriptName: workerName,
      },
    }),
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  const errors = Array.isArray(payload && payload.errors) ? payload.errors : [];
  if (!response.ok || errors.length > 0) {
    const message = errors.length
      ? String(errors[0] && errors[0].message || "graphql_error")
      : `http_${response.status}`;
    return { ok: false, error: message };
  }
  const accounts = (((payload || {}).data || {}).viewer || {}).accounts;
  const account = Array.isArray(accounts) && accounts.length ? accounts[0] : null;
  const rows = Array.isArray(account && account.workersInvocationsAdaptive)
    ? account.workersInvocationsAdaptive
    : [];
  return { ok: true, rows };
}

async function upsertWorkerOverloadEvent(db, event, deps) {
  const now = deps.nowIso();
  const id = `${event.worker_name}:${event.status}:${event.event_window_start}`;
  const result = await deps.dbRun(
    db,
    `
      INSERT INTO worker_overload_events (
        id, detected_at, event_window_start, event_window_end, worker_name, status,
        request_count, error_count, cpu_time_p50_ms, cpu_time_p99_ms, source, source_json,
        alerted_at, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
      ON CONFLICT(worker_name, status, event_window_start) DO UPDATE SET
        detected_at = excluded.detected_at,
        event_window_end = excluded.event_window_end,
        request_count = MAX(worker_overload_events.request_count, excluded.request_count),
        error_count = MAX(worker_overload_events.error_count, excluded.error_count),
        cpu_time_p50_ms = MAX(worker_overload_events.cpu_time_p50_ms, excluded.cpu_time_p50_ms),
        cpu_time_p99_ms = MAX(worker_overload_events.cpu_time_p99_ms, excluded.cpu_time_p99_ms),
        source_json = excluded.source_json,
        updated_at = excluded.updated_at
    `,
    [
      id,
      now,
      event.event_window_start,
      event.event_window_end,
      event.worker_name,
      event.status,
      event.request_count,
      event.error_count,
      event.cpu_time_p50_ms,
      event.cpu_time_p99_ms,
      "cloudflare_graphql",
      JSON.stringify(event.source || {}),
      now,
      now,
    ],
  );
  return Math.max(0, Number(deps.dbMetaChanges ? deps.dbMetaChanges(result) : result && result.meta && result.meta.changes || 0)) > 0;
}

async function markEventsAlerted(db, events, deps) {
  if (!Array.isArray(events) || !events.length) {
    return;
  }
  const now = deps.nowIso();
  for (const event of events) {
    await deps.dbRun(
      db,
      `UPDATE worker_overload_events SET alerted_at = COALESCE(alerted_at, ?), updated_at = ? WHERE worker_name = ? AND status = ? AND event_window_start = ?`,
      [now, now, event.worker_name, event.status, event.event_window_start],
    );
  }
}

async function sendWorkerOverloadEmail(env, events, deps) {
  if (!Array.isArray(events) || !events.length) {
    return { sent: false };
  }
  const apiKey = String(env.EMAIL_API_KEY || "").trim();
  const to = String(env.WORKER_OVERLOAD_ALERT_EMAIL || env.SECURITY_ALERT_EMAIL || "info@planetka.io").trim();
  if (!apiKey || !to) {
    return { sent: false, error: "email_not_configured" };
  }
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const lines = [
    "Cloudflare reported Worker overload/resource-limit events.",
    `event_count=${events.length}`,
    "",
    ...events.map((event) => [
      `worker=${event.worker_name}`,
      `status=${event.status}`,
      `window_start=${event.event_window_start}`,
      `requests=${event.request_count}`,
      `errors=${event.error_count}`,
      `cpu_p99_ms=${event.cpu_time_p99_ms}`,
    ].join(" | ")),
  ];
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject: "Planetka Worker overload detected",
      text: lines.join("\n"),
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`resend_error_${response.status}_${body}`);
  }
  void deps;
  return { sent: true };
}

export async function runWorkerOverloadMonitor(db, env, deps) {
  await ensureWorkerOverloadTables(db, deps);
  const now = deps.nowIso();
  const lookbackMinutes = Math.max(
    2,
    parseNonNegative(env.WORKER_OVERLOAD_LOOKBACK_MINUTES || DEFAULT_WORKER_OVERLOAD_LOOKBACK_MINUTES, deps),
  );
  const nowUnix = Math.floor(Date.parse(now) / 1000) || Math.floor(Date.now() / 1000);
  const endIso = isoFromUnix(nowUnix - 60);
  const startIso = isoFromUnix(nowUnix - (lookbackMinutes * 60));
  const workers = workerOverloadNames(env);
  const insertedEvents = [];
  const workerResults = [];
  let error = "";

  for (const workerName of workers) {
    const result = await fetchWorkerInvocationRows(env, workerName, startIso, endIso, deps);
    if (!result.ok) {
      error = error || result.error || "worker_overload_query_failed";
      workerResults.push({ worker_name: workerName, ok: false, error: result.error || "query_failed" });
      continue;
    }
    let overloadRows = 0;
    for (const row of result.rows || []) {
      const dimensions = row && row.dimensions || {};
      const status = normalizeStatus(dimensions.status || "");
      if (!isOverloadStatus(status)) {
        continue;
      }
      overloadRows += 1;
      const event = {
        worker_name: normalizeWorkerName(dimensions.scriptName || workerName),
        status,
        event_window_start: minuteBucketIso(dimensions.datetime || startIso),
        event_window_end: endIso,
        request_count: clampNonNegative(row && row.sum && row.sum.requests, deps),
        error_count: clampNonNegative(row && row.sum && row.sum.errors, deps),
        cpu_time_p50_ms: Number(row && row.quantiles && row.quantiles.cpuTimeP50 || 0) || 0,
        cpu_time_p99_ms: Number(row && row.quantiles && row.quantiles.cpuTimeP99 || 0) || 0,
        source: row,
      };
      const changed = await upsertWorkerOverloadEvent(db, event, deps);
      const existingAlert = await deps.dbGet(
        db,
        `SELECT alerted_at FROM worker_overload_events WHERE worker_name = ? AND status = ? AND event_window_start = ? LIMIT 1`,
        [event.worker_name, event.status, event.event_window_start],
      );
      if (changed && !String(existingAlert && existingAlert.alerted_at || "").trim()) {
        insertedEvents.push(event);
      }
    }
    workerResults.push({ worker_name: workerName, ok: true, rows: result.rows.length, overload_rows: overloadRows });
  }

  let email = { sent: false };
  if (insertedEvents.length) {
    try {
      email = await sendWorkerOverloadEmail(env, insertedEvents, deps);
      if (email.sent) {
        await markEventsAlerted(db, insertedEvents, deps);
      }
    } catch (emailError) {
      email = { sent: false, error: String(emailError && emailError.message || "worker_overload_alert_email_failed") };
      console.warn("worker_overload_monitor.email_failed", JSON.stringify(email));
    }
  }

  await deps.dbRun(
    db,
    `
      INSERT INTO worker_overload_monitor_state (key, last_checked_at, last_success_at, last_error_at, last_error, updated_at)
      VALUES ('default', ?, ?, ?, ?, ?)
      ON CONFLICT(key) DO UPDATE SET
        last_checked_at = excluded.last_checked_at,
        last_success_at = COALESCE(excluded.last_success_at, worker_overload_monitor_state.last_success_at),
        last_error_at = COALESCE(excluded.last_error_at, worker_overload_monitor_state.last_error_at),
        last_error = excluded.last_error,
        updated_at = excluded.updated_at
    `,
    [now, error ? null : now, error ? now : null, error || "", now],
  );

  return {
    ok: !error,
    generated_at: now,
    window_start: startIso,
    window_end: endIso,
    workers,
    worker_results: workerResults,
    new_overload_events: insertedEvents.length,
    alert_email: email,
    error,
  };
}

export async function collectWorkerOverloadHealth(db, deps) {
  await ensureWorkerOverloadTables(db, deps);
  const now = deps.nowIso();
  const nowUnix = Math.floor(Date.parse(now) / 1000) || Math.floor(Date.now() / 1000);
  const dayStart = isoFromUnix(nowUnix - 86400);
  const weekStart = isoFromUnix(nowUnix - (7 * 86400));
  const counts = await deps.dbGet(
    db,
    `
      SELECT
        SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS count_24h,
        SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS count_7d,
        MAX(created_at) AS latest_created_at
      FROM worker_overload_events
    `,
    [dayStart, weekStart],
  );
  const latest = await deps.dbGet(
    db,
    `
      SELECT worker_name, status, event_window_start, event_window_end, request_count, error_count, cpu_time_p99_ms, alerted_at, created_at
      FROM worker_overload_events
      ORDER BY created_at DESC
      LIMIT 1
    `,
  );
  const state = await deps.dbGet(
    db,
    `SELECT last_checked_at, last_success_at, last_error_at, last_error, updated_at FROM worker_overload_monitor_state WHERE key = 'default' LIMIT 1`,
  );
  const recent = await deps.dbAll(
    db,
    `
      SELECT worker_name, status, event_window_start, event_window_end, request_count, error_count, cpu_time_p99_ms, alerted_at, created_at
      FROM worker_overload_events
      ORDER BY created_at DESC
      LIMIT ?
    `,
    [DEFAULT_WORKER_OVERLOAD_RECENT_LIMIT],
  );
  return {
    available: true,
    generated_at: now,
    count_24h: clampNonNegative(counts && counts.count_24h, deps),
    count_7d: clampNonNegative(counts && counts.count_7d, deps),
    latest_created_at: String(counts && counts.latest_created_at || ""),
    latest: latest || null,
    monitor_state: state || null,
    recent: Array.isArray(recent) ? recent : [],
  };
}
