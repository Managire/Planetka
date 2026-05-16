export function buildAdminAnalyticsPageHtml(context = {}) {
  const {
    escapeHtml,
    encodeURIComponent,
    user,
    tokenSource,
    buildStamp,
    snapshotGeneratedAt,
    fmtIntLocal,
    fmtGbLocal,
    snapshotTopLine,
    snapshotActive,
    snapshotSummary,
    snapshotLiveMap,
    serverActiveUsersRowsHtml,
    serverMapRectsSvg,
    serverHeavyRowsHtml,
    billableStatusText,
    billableStorageGb,
    billableStorageGbBillable,
    billableCostStorage,
    billableClassAOps,
    billableClassAOpsBillable,
    billableCostClassA,
    billableClassBOps,
    billableClassBOpsBillable,
    billableCostClassB,
    billableUnknownOps,
    billableCostTotal,
    quoteQueueHealth,
  } = context || {};

  const safeTopLine = snapshotTopLine && typeof snapshotTopLine === "object" ? snapshotTopLine : {};
  const safeActive = snapshotActive && typeof snapshotActive === "object" ? snapshotActive : {};
  const topLineUsers = safeTopLine.users && typeof safeTopLine.users === "object" ? safeTopLine.users : {};
  const topLineResolves = safeTopLine.resolves && typeof safeTopLine.resolves === "object" ? safeTopLine.resolves : {};
  const topLineTileRequests = safeTopLine.tile_requests && typeof safeTopLine.tile_requests === "object" ? safeTopLine.tile_requests : {};
  const topLineGbServed = safeTopLine.gb_served && typeof safeTopLine.gb_served === "object" ? safeTopLine.gb_served : {};
  const topLineEarnedEur = safeTopLine.earned_eur && typeof safeTopLine.earned_eur === "object" ? safeTopLine.earned_eur : {};
  const topLinePaidResolves = safeTopLine.paid_resolves && typeof safeTopLine.paid_resolves === "object" ? safeTopLine.paid_resolves : {};

  const renderTotalValue = (values = {}, valueFormatter, fallbackTotal = 0) => {
    const safeValues = values && typeof values === "object" ? values : {};
    const total = Number(safeValues.total || fallbackTotal || 0);
    return escapeHtml(String(valueFormatter(total)));
  };
  const fmtEurLocal = (value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? `€${numeric.toFixed(2)}` : "€0.00";
  };

  const topUsersSplitHtml = renderTotalValue(topLineUsers, (value) => fmtIntLocal(value), topLineUsers.total);
  const topResolvesSplitHtml = renderTotalValue(topLineResolves, (value) => fmtIntLocal(value), topLineResolves.total);
  const topTileRequestsSplitHtml = renderTotalValue(topLineTileRequests, (value) => fmtIntLocal(value), topLineTileRequests.total);
  const topGbServedSplitHtml = renderTotalValue(topLineGbServed, (value) => `${fmtGbLocal(value)} GB`, topLineGbServed.total);
  const topEarnedEurHtml = renderTotalValue(topLineEarnedEur, (value) => fmtEurLocal(value), topLineEarnedEur.total);
  const topPaidResolvesHtml = renderTotalValue(topLinePaidResolves, (value) => fmtIntLocal(value), topLinePaidResolves.total);
  const safeQuoteQueueHealth = quoteQueueHealth && typeof quoteQueueHealth === "object" ? quoteQueueHealth : {};
  const safeQuoteQueueLock = safeQuoteQueueHealth.active_lock && typeof safeQuoteQueueHealth.active_lock === "object"
    ? safeQuoteQueueHealth.active_lock
    : null;
  const safeQuoteQueueBatch = safeQuoteQueueHealth.last_processed_batch && typeof safeQuoteQueueHealth.last_processed_batch === "object"
    ? safeQuoteQueueHealth.last_processed_batch
    : null;
  const fmtDuration = (ms) => {
    const numeric = Number(ms);
    if (!Number.isFinite(numeric) || numeric <= 0) return "-";
    if (numeric < 1000) return `${Math.round(numeric)} ms`;
    return `${(numeric / 1000).toFixed(2)} s`;
  };
  const fmtAge = (seconds) => {
    const numeric = Math.max(0, Math.floor(Number(seconds) || 0));
    if (numeric <= 0) return "-";
    if (numeric < 60) return `${numeric}s`;
    if (numeric < 3600) return `${Math.floor(numeric / 60)}m ${numeric % 60}s`;
    return `${Math.floor(numeric / 3600)}h ${Math.floor((numeric % 3600) / 60)}m`;
  };
  const quoteQueueLockHtml = safeQuoteQueueLock
    ? `${escapeHtml(String(safeQuoteQueueLock.current_job_id || "active"))}<br><span class="muted">${escapeHtml(fmtAge(safeQuoteQueueLock.age_seconds))}</span>`
    : "None";
  const quoteQueueBatchHtml = safeQuoteQueueBatch
    ? `${escapeHtml(String(safeQuoteQueueBatch.status || "-"))}<br><span class="muted">${escapeHtml(fmtDuration(safeQuoteQueueBatch.duration_ms))}</span>`
    : "-";
  return `
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="300" />
  <title>Planetka Analytics</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 20px; background: #0b1020; color: #e5e7eb; }
    h1 { margin: 0 0 8px; font-size: 24px; }
    .muted { color: #9ca3af; font-size: 13px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 16px 0 20px; }
    .card { background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 12px; }
    .label { color: #93c5fd; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
    .value { font-size: 22px; margin-top: 6px; font-weight: 600; }
    .controls { display:flex; gap:10px; align-items:center; margin: 8px 0 16px; }
    .map-shell { position: relative; width: 100%; max-width: 980px; aspect-ratio: 2 / 1; margin-top: 8px; border: 1px solid #1f2937; border-radius: 8px; overflow: hidden; background: #0a1628; }
    .map-bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
    .map-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
    .map-canvas { position: absolute; inset: 0; width: 100%; height: 100%; background: transparent; }
    select, button, input { background:#111827; color:#e5e7eb; border:1px solid #374151; border-radius:8px; padding:7px 10px; }
    input[type=number] { width: 90px; }
    .action-btn { font-size: 12px; padding: 4px 8px; margin-right: 6px; margin-bottom: 4px; cursor: pointer; }
    .action-btn.warn { border-color: #9a3412; color: #fed7aa; }
    .action-btn.danger { border-color: #991b1b; color: #fecaca; }
    .action-wrap { white-space: nowrap; }
    table { width:100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }
    th, td { border-bottom: 1px solid #1f2937; padding: 8px 6px; text-align:left; }
    th { color:#93c5fd; font-weight:600; }
    .section { margin-top: 20px; }
    .error { color: #fca5a5; }
    .user-filter-active { outline: 1px solid #60a5fa; outline-offset: -1px; }
    .subvalue { color:#9ca3af; font-size:12px; line-height:1.35; margin-top:4px; }
  </style>
</head>
<body>
  <h1>Planetka Analytics</h1>
  <div class="muted">Signed in as ${escapeHtml(String(user.email || ""))}. Session source: ${escapeHtml(String(tokenSource || "unknown"))}. Auto-refresh every 15 seconds. Build: ${escapeHtml(buildStamp)}</div>
  <div class="controls">
    <a href="/admin/analytics/users" style="color:#93c5fd; text-decoration:none;">All users</a>
    <a href="/admin/analytics/products" style="color:#93c5fd; text-decoration:none;">Product pricing</a>
    <a href="/admin/session/logout" style="color:#fca5a5; text-decoration:none;">Sign Out</a>
  </div>
	  <div class="controls">
	    <label for="window">Window:</label>
    <select id="window">
      <option value="15">15 min</option>
      <option value="60">60 min</option>
      <option value="360">6 hours</option>
      <option value="1440">24 hours</option>
      <option value="10080" selected>7 days</option>
    </select>
    <label for="tileMapWindow">Live map:</label>
    <select id="tileMapWindow">
      <option value="1">1 min</option>
      <option value="3">3 min</option>
      <option value="10" selected>10 min</option>
    </select>
    <a id="refresh" href="/admin/analytics?refresh=${encodeURIComponent(buildStamp)}" style="display:inline-block;background:#111827;color:#e5e7eb;border:1px solid #374151;border-radius:8px;padding:7px 10px;text-decoration:none;">Refresh now</a>
	    <span id="status" class="muted">Snapshot updated: ${snapshotGeneratedAt} UTC</span>
	  </div>
	  <div class="grid">
    <div class="card"><div class="label">Total Earned</div><div id="topEarnedEur" class="value">${topEarnedEurHtml}</div></div>
    <div class="card"><div class="label">Total Paid Resolves</div><div id="topPaidResolves" class="value">${topPaidResolvesHtml}</div></div>
    <div class="card"><div class="label">Total Users</div><div id="topUsersSplit" class="value">${topUsersSplitHtml}</div></div>
    <div class="card"><div class="label">Total Resolves</div><div id="topResolvesSplit" class="value">${topResolvesSplitHtml}</div></div>
    <div class="card"><div class="label">Tile Requests</div><div id="topRequestsSplit" class="value">${topTileRequestsSplitHtml}</div></div>
    <div class="card"><div class="label">GB Served</div><div id="topGbSplit" class="value">${topGbServedSplitHtml}</div></div>
    <div class="card"><div class="label">Live tile events (10s)</div><div id="live10s" class="value">${escapeHtml(fmtIntLocal(snapshotActive.tile_events_10s))}</div></div>
    <div class="card"><div class="label">Tile requests (window)</div><div id="reqCount" class="value">${escapeHtml(fmtIntLocal(snapshotSummary.request_count))}</div></div>
    <div class="card"><div class="label">Bytes served (window)</div><div id="bytesServed" class="value">${escapeHtml(fmtGbLocal(snapshotSummary.bytes_served))} GB</div></div>
    <div class="card"><div class="label">Errors (window)</div><div id="errors" class="value">${escapeHtml(fmtIntLocal(snapshotSummary.error_count))}</div></div>
    <div class="card"><div class="label">Cache hit ratio</div><div id="hitRatio" class="value">${escapeHtml((Number(snapshotSummary.request_count || 0) > 0 ? (100 * Number(snapshotSummary.cache_hit_count || 0) / Number(snapshotSummary.request_count || 1)) : 0).toFixed(2))}%</div></div>
    <div class="card"><div class="label">Tagged resolves</div><div id="resolveCount" class="value">${escapeHtml(fmtIntLocal(snapshotSummary.tagged_resolve_count))}</div></div>
    <div class="card"><div class="label" id="authRefreshAttemptsLabel">Refresh Attempts (7d)</div><div id="authRefreshTotal" class="value">-</div></div>
    <div class="card"><div class="label" id="authRefreshFailuresLabel">Refresh Failures (7d)</div><div id="authRefreshFailures" class="value">-</div></div>
    <div class="card"><div class="label">Refresh Failure Rate</div><div id="authRefreshFailureRate" class="value">-</div></div>
    <div class="card"><div class="label">Critical Disconnects (7d)</div><div id="authRefreshCriticalFailures" class="value">-</div></div>
    <div class="card"><div class="label">Critical Affected Users (7d)</div><div id="authRefreshCriticalUsers" class="value">-</div></div>
  </div>

  <div class="section">
    <h3>Quote Queue Health</h3>
    <div class="grid">
      <div class="card"><div class="label">Queued Jobs</div><div id="quoteQueueQueued" class="value">${escapeHtml(fmtIntLocal(safeQuoteQueueHealth.queued_count))}</div></div>
      <div class="card"><div class="label">Failed Jobs</div><div id="quoteQueueFailed" class="value">${escapeHtml(fmtIntLocal(safeQuoteQueueHealth.failed_count))}</div></div>
      <div class="card"><div class="label">Oldest Queued Job</div><div id="quoteQueueOldestAge" class="value">${escapeHtml(fmtAge(safeQuoteQueueHealth.oldest_queued_age_seconds))}</div><div id="quoteQueueOldestAt" class="subvalue">${escapeHtml(String(safeQuoteQueueHealth.oldest_queued_at || ""))}</div></div>
      <div class="card"><div class="label">Active Lock</div><div id="quoteQueueLock" class="value">${quoteQueueLockHtml}</div><div id="quoteQueueLockMeta" class="subvalue">${escapeHtml(safeQuoteQueueLock ? String(safeQuoteQueueLock.worker_id || "") : "")}</div></div>
      <div class="card"><div class="label">Last Batch Timing</div><div id="quoteQueueBatchTiming" class="value">${quoteQueueBatchHtml}</div><div id="quoteQueueBatchMeta" class="subvalue">${escapeHtml(safeQuoteQueueBatch ? `${fmtIntLocal(safeQuoteQueueBatch.completed_job_count)} done · ${fmtIntLocal(safeQuoteQueueBatch.failed_job_count)} failed` : "")}</div></div>
    </div>
  </div>

  <div class="section">
    <h3>Active Users (Last 10 min)</h3>
    <table id="activeUsersTable"><thead><tr><th>Email</th><th>Requests</th><th>Resolves</th><th>GB</th><th>Last seen</th></tr></thead><tbody>${serverActiveUsersRowsHtml}</tbody></table>
  </div>
  <div class="section">
    <h3>Live Tile Activity Map</h3>
    <div class="muted" id="tileMapMeta">Window: ${escapeHtml(String(snapshotLiveMap.window_seconds || 60))}s | Active users: ${escapeHtml(fmtIntLocal(snapshotLiveMap.users_active))} | Active tiles: ${escapeHtml(fmtIntLocal(snapshotLiveMap.tiles_active))}</div>
    <div class="muted" id="tileMapFilterState">Showing all active users.</div>
    <div class="map-shell">
      <img class="map-bg" src="/admin/analytics/world-map.jpg" alt="World map"/>
      <svg class="map-svg" viewBox="0 0 720 360" preserveAspectRatio="none" aria-hidden="true">${serverMapRectsSvg}</svg>
      <canvas id="tileMapCanvas" class="map-canvas" width="720" height="360"></canvas>
    </div>
    <table id="tileMapUsersTable" style="max-width: 980px;"><thead><tr><th>User</th><th>Tiles (window)</th><th>Requests (window)</th><th>GB (window)</th><th>Map</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Top Tiles</h3>
    <table id="tilesTable"><thead><tr><th>Tile key</th><th>Requests</th><th>GB</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3 id="authRefreshHeading">Auth Refresh Health (7d)</h3>
    <table id="authRefreshUsersTable"><thead><tr><th>User</th><th>Failure Count</th><th>Last Failure</th></tr></thead><tbody></tbody></table>
    <table id="authRefreshErrorsTable"><thead><tr><th>Error</th><th>Count</th></tr></thead><tbody></tbody></table>
    <h3 style="margin-top: 14px;">Critical Disconnects (7d)</h3>
    <table id="authRefreshCriticalUsersTable"><thead><tr><th>User</th><th>Critical Count</th><th>Last Critical</th></tr></thead><tbody></tbody></table>
    <table id="authRefreshCriticalErrorsTable"><thead><tr><th>Critical Error</th><th>Count</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Recent Failures</h3>
    <table id="failsTable"><thead><tr><th>Time</th><th>User</th><th>Status</th><th>Error</th><th>Tile</th><th>Cache</th><th>ms</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Heavy Users (Top 20 by Lifetime GB)</h3>
    <table id="heavyTable"><thead><tr><th>Email</th><th>Resolves</th><th>Lifetime GB</th><th>Last Seen</th></tr></thead><tbody>${serverHeavyRowsHtml}</tbody></table>
  </div>
  <div class="section">
    <h3>Cloud Billable Usage (R2)</h3>
    <div class="muted" id="billableMeta">${billableStatusText}</div>
    <table id="billableTable">
      <thead><tr><th>Metric</th><th>Usage</th><th>Billable</th><th>Estimated Cost (USD)</th></tr></thead>
      <tbody>
        <tr><td>R2 Data Storage</td><td id="billableStorageUsage">${billableStorageGb} GB</td><td id="billableStorageBillable">${billableStorageGbBillable} GB</td><td id="billableStorageCost">${billableCostStorage}</td></tr>
        <tr><td>Class A Operations</td><td id="billableClassAUsage">${billableClassAOps}</td><td id="billableClassABillable">${billableClassAOpsBillable}</td><td id="billableClassACost">${billableCostClassA}</td></tr>
        <tr><td>Class B Operations</td><td id="billableClassBUsage">${billableClassBOps}</td><td id="billableClassBBillable">${billableClassBOpsBillable}</td><td id="billableClassBCost">${billableCostClassB}</td></tr>
        <tr><td>Unknown Operations</td><td id="billableUnknownUsage">${billableUnknownOps}</td><td>-</td><td>-</td></tr>
        <tr><td><strong>Total</strong></td><td>-</td><td>-</td><td id="billableTotalCost"><strong>${billableCostTotal}</strong></td></tr>
      </tbody>
    </table>
  </div>

  <script>
    const statusEl = document.getElementById("status");
    if (statusEl) {
      statusEl.textContent = "Booting analytics...";
      statusEl.className = "muted";
    }
	    const windowEl = document.getElementById("window");
	    const tileMapWindowEl = document.getElementById("tileMapWindow");
	    const refreshBtn = document.getElementById("refresh");
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    window.addEventListener("error", (event) => {
      const message = "Runtime error: " + String(event && event.message || "unknown_error");
      if (statusEl) {
        statusEl.textContent = message;
        statusEl.className = "error";
      }
      const tileMapMetaEl = document.getElementById("tileMapMeta");
      if (tileMapMetaEl) {
        tileMapMetaEl.textContent = message;
      }
    });
    const fmtInt = (v) => Number(v || 0).toLocaleString();
    const fmtBytes = (v) => {
      let n = Number(v || 0);
      const units = ["B","KB","MB","GB","TB"];
      let i = 0;
      while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
      return n.toFixed(i === 0 ? 0 : 2) + " " + units[i];
    };
    const fmtGb = (v) => (Number(v || 0) / (1024 * 1024 * 1024)).toFixed(3);
    const fmtEur = (v) => {
      const numeric = Number(v);
      return Number.isFinite(numeric) ? "€" + numeric.toFixed(2) : "€0.00";
    };
    const fmtFixed = (v, digits = 2) => {
      const numeric = Number(v);
      return Number.isFinite(numeric) ? numeric.toFixed(digits) : "0.00";
    };
    const fmtDuration = (ms) => {
      const numeric = Number(ms);
      if (!Number.isFinite(numeric) || numeric <= 0) return "-";
      if (numeric < 1000) return Math.round(numeric) + " ms";
      return (numeric / 1000).toFixed(2) + " s";
    };
    const fmtAge = (seconds) => {
      const numeric = Math.max(0, Math.floor(Number(seconds) || 0));
      if (numeric <= 0) return "-";
      if (numeric < 60) return numeric + "s";
      if (numeric < 3600) return Math.floor(numeric / 60) + "m " + (numeric % 60) + "s";
      return Math.floor(numeric / 3600) + "h " + Math.floor((numeric % 3600) / 60) + "m";
    };
    const renderTotalMetric = (id, values, asGb = false, fallbackTotal = 0) => {
      const target = document.getElementById(id);
      if (!target) return;
      const fmtValue = (value) => {
        if (asGb) return fmtGb(value) + " GB";
        return fmtInt(value);
      };
      const safeValues = values && typeof values === "object" ? values : {};
      target.textContent = fmtValue(Number(safeValues.total || fallbackTotal || 0));
    };
    const decodeDataValue = (v) => {
      try {
        return decodeURIComponent(String(v || ""));
      } catch (_error) {
        return String(v || "");
      }
    };
    const encodeDataValue = (v) => encodeURIComponent(String(v || ""));
    function renderRows(tableId, rows, rowBuilder) {
      const tbody = document.querySelector("#" + tableId + " tbody");
      if (!tbody) return;
      tbody.innerHTML = "";
      const rowsSafe = Array.isArray(rows) ? rows : [];
      for (const row of rowsSafe) {
        const tr = document.createElement("tr");
        const built = rowBuilder(row);
        if (built && typeof built === "object") {
          tr.innerHTML = String(built.html || "");
          if (built.rowClass) {
            tr.className = String(built.rowClass);
          }
          if (built.dataset && typeof built.dataset === "object") {
            for (const [key, value] of Object.entries(built.dataset)) {
              tr.dataset[key] = String((value === null || value === undefined) ? "" : value);
            }
          }
        } else {
          tr.innerHTML = String(built || "");
        }
        tbody.appendChild(tr);
      }
    }
    function renderCloudBillableUsage(payload) {
      const data = payload && typeof payload === "object" ? payload : {};
      const available = Boolean(data.available);
      const bucket = String(data.bucket_filter || "").trim();
      const metaText = available
        ? (data && data.estimated
          ? ("Estimated billable usage from telemetry. Source: "
            + String(data.source || "telemetry_estimate").replace(/cloudflare/gi, "cloud")
            + ". Period: " + String(data.period_start || "-")
            + " -> " + String(data.period_end || "-"))
          : ("Cloud live data. Source: "
            + String(data.source || "cloud_live").replace(/cloudflare/gi, "cloud")
            + ". Bucket: " + (bucket || "all buckets")
            + ". Period: " + String(data.period_start || "-")
            + " -> " + String(data.period_end || "-")))
        : ("Cloud billable usage unavailable. "
          + String(data.message || data.reason || "Not configured."));
      setText("billableMeta", metaText);
      if (!available) {
        setText("billableStorageUsage", "-");
        setText("billableStorageBillable", "-");
        setText("billableStorageCost", "-");
        setText("billableClassAUsage", "-");
        setText("billableClassABillable", "-");
        setText("billableClassACost", "-");
        setText("billableClassBUsage", "-");
        setText("billableClassBBillable", "-");
        setText("billableClassBCost", "-");
        setText("billableUnknownUsage", "-");
        setText("billableTotalCost", "-");
        return;
      }
      setText("billableStorageUsage", fmtFixed(data && data.storage && data.storage.gb, 3) + " GB");
      setText("billableStorageBillable", fmtFixed(data && data.storage && data.storage.billable_gb_rounded, 0) + " GB");
      setText("billableStorageCost", fmtFixed(data && data.estimated_cost_usd && data.estimated_cost_usd.storage, 2));
      setText("billableClassAUsage", fmtInt(data && data.class_a && data.class_a.operations));
      setText("billableClassABillable", fmtInt(data && data.class_a && data.class_a.billable_operations));
      setText("billableClassACost", fmtFixed(data && data.estimated_cost_usd && data.estimated_cost_usd.class_a, 2));
      setText("billableClassBUsage", fmtInt(data && data.class_b && data.class_b.operations));
      setText("billableClassBBillable", fmtInt(data && data.class_b && data.class_b.billable_operations));
      setText("billableClassBCost", fmtFixed(data && data.estimated_cost_usd && data.estimated_cost_usd.class_b, 2));
      setText("billableUnknownUsage", fmtInt(data && data.unknown_operations));
      setText("billableTotalCost", fmtFixed(data && data.estimated_cost_usd && data.estimated_cost_usd.total, 2));
    }
    function renderQuoteQueueHealth(payload) {
      const data = payload && typeof payload === "object" ? payload : {};
      const lock = data.active_lock && typeof data.active_lock === "object" ? data.active_lock : null;
      const batch = data.last_processed_batch && typeof data.last_processed_batch === "object" ? data.last_processed_batch : null;
      setText("quoteQueueQueued", fmtInt(data.queued_count));
      setText("quoteQueueFailed", fmtInt(data.failed_count));
      setText("quoteQueueOldestAge", fmtAge(data.oldest_queued_age_seconds));
      setText("quoteQueueOldestAt", data.oldest_queued_at || "");
      if (lock) {
        setText("quoteQueueLock", String(lock.current_job_id || "active"));
        setText("quoteQueueLockMeta", fmtAge(lock.age_seconds) + " · " + String(lock.worker_id || ""));
      } else {
        setText("quoteQueueLock", "None");
        setText("quoteQueueLockMeta", "");
      }
      if (batch) {
        setText("quoteQueueBatchTiming", String(batch.status || "-"));
        setText(
          "quoteQueueBatchMeta",
          fmtDuration(batch.duration_ms) + " · " + fmtInt(batch.completed_job_count) + " done · " + fmtInt(batch.failed_job_count) + " failed",
        );
      } else {
        setText("quoteQueueBatchTiming", "-");
        setText("quoteQueueBatchMeta", "");
      }
    }
    const TILE_COLOR_ACTIVE = "#60a5fa";
    const TILE_MAP_BASEMAP_URL = "/admin/analytics/world-map.jpg";
    let tileMapBaseImage = null;
    let tileMapBaseImageState = "idle";
    let tileMapLastPayload = null;
    let tileMapSelectedUserKey = "";
    function activeUserColor() {
      return TILE_COLOR_ACTIVE;
    }
    function userKeyForRow(row) {
      return String((row && row.user_id) || (row && row.user_email) || "").trim();
    }
    function setTileMapUserFilter(selectedUserKey) {
      const normalized = String(selectedUserKey || "").trim();
      tileMapSelectedUserKey = (tileMapSelectedUserKey && tileMapSelectedUserKey === normalized) ? "" : normalized;
      if (tileMapLastPayload) {
        renderLiveTileMap(tileMapLastPayload);
      }
    }
    function parseTileKey(tileKey) {
      const text = String(tileKey || "").trim();
      const match = /_x(\\d{3})_y(\\d{3})_z(\\d{3})_d(\\d{3})\\.(?:exr|tif|tiff|png|jpe?g)$/i.exec(text);
      if (!match) return null;
      const x = Number.parseInt(match[1], 10);
      const y = Number.parseInt(match[2], 10);
      const z = Number.parseInt(match[3], 10);
      const d = Number.parseInt(match[4], 10);
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z) || !Number.isFinite(d)) return null;
      if (x < 0 || x > 359 || y < 0 || y > 179 || z <= 0 || z > 360) return null;
      return { x, y, z, d };
    }
    function shouldExcludeTileFromMap(parsed) {
      if (!parsed) return true;
      const z = Number(parsed.z || 0);
      return z === 90 || z === 180 || z === 360;
    }
    function hexToRgb(hex) {
      const raw = String(hex || "").trim().replace("#", "");
      if (!raw) return null;
      const normalized = raw.length === 3
        ? raw.split("").map((ch) => ch + ch).join("")
        : raw;
      if (!/^[0-9a-fA-F]{6}$/.test(normalized)) return null;
      return {
        r: Number.parseInt(normalized.slice(0, 2), 16),
        g: Number.parseInt(normalized.slice(2, 4), 16),
        b: Number.parseInt(normalized.slice(4, 6), 16),
      };
    }
    function scaledColor(hex, brightness, alpha) {
      const rgb = hexToRgb(hex) || { r: 255, g: 255, b: 255 };
      const level = Math.max(0, Math.min(1, Number(brightness || 0)));
      const a = Math.max(0, Math.min(1, Number(alpha || 1)));
      const r = Math.max(0, Math.min(255, Math.round(rgb.r * level)));
      const g = Math.max(0, Math.min(255, Math.round(rgb.g * level)));
      const b = Math.max(0, Math.min(255, Math.round(rgb.b * level)));
      return "rgba(" + r + "," + g + "," + b + "," + a + ")";
    }
    function tileAlphaByD(parsed) {
      if (!parsed) return 0;
      const rawD = Number(parsed.d || 0);
      const d = rawD > 0 ? rawD : 1;
      return Math.max(0, Math.min(1, 1 / Math.max(1, d)));
    }
    function ensureTileMapBasemapLoaded() {
      if (tileMapBaseImageState === "ready" || tileMapBaseImageState === "loading") {
        return;
      }
      tileMapBaseImageState = "loading";
      const image = new Image();
      image.decoding = "async";
      image.onload = () => {
        tileMapBaseImage = image;
        tileMapBaseImageState = "ready";
        if (tileMapLastPayload) {
          renderLiveTileMap(tileMapLastPayload);
        }
      };
      image.onerror = () => {
        tileMapBaseImage = null;
        tileMapBaseImageState = "error";
      };
      image.src = TILE_MAP_BASEMAP_URL;
    }
    function drawTileMapBackground(ctx, width, height) {
      ctx.clearRect(0, 0, width, height);
      if (tileMapBaseImageState === "ready" && tileMapBaseImage) {
        ctx.filter = "brightness(2500%)";
        ctx.globalAlpha = 1;
        ctx.drawImage(tileMapBaseImage, 0, 0, width, height);
        ctx.filter = "none";
        ctx.globalAlpha = 1;
      } else {
        const gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, "#0b1f35");
        gradient.addColorStop(0.5, "#102642");
        gradient.addColorStop(1, "#0a1a2d");
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
      ctx.lineWidth = 0.5;
      ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
    }
    function renderLiveTileMap(tileMapData) {
      tileMapLastPayload = tileMapData || {};
      ensureTileMapBasemapLoaded();
      const canvas = document.getElementById("tileMapCanvas");
      const metaEl = document.getElementById("tileMapMeta");
      if (!canvas || !metaEl) {
        return;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        return;
      }
      const width = canvas.width;
      const height = canvas.height;
      drawTileMapBackground(ctx, width, height);

      const rows = Array.isArray(tileMapData && tileMapData.rows) ? tileMapData.rows : [];
      const scaleX = width / 360.0;
      const scaleY = height / 180.0;
      const userStats = new Map();
      let plotted = 0;
      const seenByUserTile = new Set();
      const preparedRows = [];
      for (const row of rows) {
        const parsed = parseTileKey(row && row.tile_key);
        if (!parsed) continue;
        if (shouldExcludeTileFromMap(parsed)) continue;
        const userId = String(row && row.user_id || "").trim();
        const userEmail = String(row && row.user_email || "").trim();
        const userKey = userId || userEmail || "unknown";
        if (tileMapSelectedUserKey && userKey !== tileMapSelectedUserKey) {
          continue;
        }
        preparedRows.push({ row, parsed, userKey });
      }
      // Draw larger/coarser tiles first, then finer tiles on top.
      preparedRows.sort((left, right) => {
        const zDiff = Number(right.parsed.z || 0) - Number(left.parsed.z || 0);
        if (zDiff !== 0) return zDiff;
        return Number(right.row && right.row.last_seen_unix || 0) - Number(left.row && left.row.last_seen_unix || 0);
      });

      for (const item of preparedRows) {
        const row = item.row;
        const parsed = item.parsed;
        const userId = String(row && row.user_id || "").trim();
        const userEmail = String(row && row.user_email || "").trim();
        const userKey = String(item.userKey || userId || userEmail || "unknown");
        const userColor = activeUserColor();
        const alpha = tileAlphaByD(parsed);
        const x = parsed.x * scaleX;
        const y = (180 - (parsed.y + parsed.z)) * scaleY;
        const w = parsed.z * scaleX;
        const h = parsed.z * scaleY;
        if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(w) || !Number.isFinite(h)) {
          continue;
        }
        if ((x + w) <= 0 || (y + h) <= 0 || x >= width || y >= height) {
          continue;
        }
        ctx.fillStyle = scaledColor(userColor, 1, alpha);
        ctx.strokeStyle = scaledColor(userColor, 1, 1);
        ctx.lineWidth = 0.5;
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
        plotted += 1;

        const dedupeKey = userKey + "::" + parsed.x + ":" + parsed.y + ":" + parsed.z;
        let stat = userStats.get(userKey);
        if (!stat) {
          stat = {
            userKey,
            email: userEmail || userKey,
            tileCount: 0,
            requestCount: 0,
            bytesServed: 0,
          };
          userStats.set(userKey, stat);
        }
        if (!seenByUserTile.has(dedupeKey)) {
          seenByUserTile.add(dedupeKey);
          stat.tileCount += 1;
        }
        stat.requestCount += Number(row && row.request_count || 0);
        stat.bytesServed += Number(row && row.bytes_served || 0);
      }

      const windowSeconds = Number(tileMapData && tileMapData.window_seconds || 60);
      const usersActive = Number(tileMapData && tileMapData.users_active || userStats.size || 0);
      const tilesActive = Number(tileMapData && tileMapData.tiles_active || 0);
      const generatedAt = String(tileMapData && tileMapData.generated_at || "");
      const generatedLabel = generatedAt ? new Date(generatedAt).toLocaleTimeString() : "-";
      const filterStateEl = document.getElementById("tileMapFilterState");
      if (filterStateEl) {
        filterStateEl.textContent = tileMapSelectedUserKey
          ? ("Filtered user: " + tileMapSelectedUserKey)
          : "Showing all active users.";
      }
      metaEl.textContent =
        "Window: " + windowSeconds + "s | " +
        "Active users: " + fmtInt(usersActive) + " | " +
        "Active tiles: " + fmtInt(tilesActive) + " | " +
        "Plotted rectangles: " + fmtInt(plotted) + " | " +
        "Updated: " + generatedLabel;

      const userRows = Array.from(userStats.values())
        .sort((a, b) => (b.bytesServed - a.bytesServed) || (b.requestCount - a.requestCount))
        .slice(0, 50);
      renderRows("tileMapUsersTable", userRows, (row) => ({
        html: \`<td>\${row.email || ""}</td>
        <td>\${fmtInt(row.tileCount)}</td>
        <td>\${fmtInt(row.requestCount)}</td>
        <td>\${fmtGb(row.bytesServed)}</td>
        <td><button class="action-btn" data-action="map-filter-user" data-user-key="\${encodeDataValue(row.userKey || "")}">\${tileMapSelectedUserKey && tileMapSelectedUserKey === row.userKey ? "Show All" : "Show"}</button></td>\`,
        rowClass: tileMapSelectedUserKey && tileMapSelectedUserKey === row.userKey ? "user-filter-active" : "",
      }));
    }
    async function loadAnalytics() {
      try {
        const minutes = String((windowEl && windowEl.value) || "60");
        const tileMapMinutes = String((tileMapWindowEl && tileMapWindowEl.value) || "1");
        if (statusEl) {
          statusEl.textContent = "Loading...";
        }
        const res = await fetch(
          "/admin/analytics/data?minutes=" + encodeURIComponent(minutes) +
          "&tile_map_minutes=" + encodeURIComponent(tileMapMinutes),
          { credentials: "same-origin" },
        );
        const data = await res.json();
        if (!res.ok || !data.ok) {
          const serverMessage = String(data && (data.message || data.error) || "").trim();
          throw new Error(serverMessage || ("HTTP " + res.status));
        }
        const s = data.summary || {};
        const a = data.active || {};
        const topLine = data.top_line || {};
        setText("topEarnedEur", fmtEur(topLine && topLine.earned_eur && topLine.earned_eur.total));
        renderTotalMetric("topPaidResolves", topLine.paid_resolves || {}, false, Number(topLine && topLine.paid_resolves && topLine.paid_resolves.total || 0));
        renderTotalMetric("topUsersSplit", topLine.users || {}, false, Number(topLine && topLine.users && topLine.users.total || 0));
        renderTotalMetric("topResolvesSplit", topLine.resolves || {}, false, Number(topLine && topLine.resolves && topLine.resolves.total || 0));
        renderTotalMetric("topRequestsSplit", topLine.tile_requests || {}, false, Number(topLine && topLine.tile_requests && topLine.tile_requests.total || 0));
        renderTotalMetric("topGbSplit", topLine.gb_served || {}, true, Number(topLine && topLine.gb_served && topLine.gb_served.total || 0));
        setText("live10s", fmtInt(a.tile_events_10s));
        setText("reqCount", fmtInt(s.request_count));
        setText("bytesServed", fmtBytes(s.bytes_served));
        setText("errors", fmtInt(s.error_count));
        const hitRatio = Number(s.request_count || 0) > 0 ? (100 * Number(s.cache_hit_count || 0) / Number(s.request_count || 1)) : 0;
        setText("hitRatio", hitRatio.toFixed(2) + "%");
        setText("resolveCount", fmtInt(s.tagged_resolve_count));
        renderQuoteQueueHealth(data.quote_queue_health || {});
        const refreshHealth = data.auth_refresh_health || {};
        const refreshTotal = Number(refreshHealth.total_count || 0);
        const refreshFailures = Number(refreshHealth.failure_count || 0);
        const refreshCriticalFailures = Number(refreshHealth.critical_failure_count || 0);
        const refreshCriticalUsers = Number(refreshHealth.critical_failed_user_count || 0);
        const refreshFailureRate = refreshTotal > 0 ? (100 * refreshFailures / refreshTotal) : 0;
        setText("authRefreshTotal", fmtInt(refreshTotal));
        setText("authRefreshFailures", fmtInt(refreshFailures));
        setText("authRefreshFailureRate", refreshFailureRate.toFixed(2) + "%");
        setText("authRefreshCriticalFailures", fmtInt(refreshCriticalFailures));
        setText("authRefreshCriticalUsers", fmtInt(refreshCriticalUsers));
        renderCloudBillableUsage(data.cloudflare_billable_usage || {});
        renderRows("activeUsersTable", data.active_users_10m, (row) => {
          return \`<td>\${row.user_email || ""}</td><td>\${fmtInt(row.request_count)}</td><td>\${fmtInt(row.resolve_count)}</td><td>\${fmtGb(row.bytes_served)}</td><td>\${row.last_seen_at || ""}</td>\`;
        });
        renderRows("heavyTable", data.heavy_users_30d || [], (row) => {
          const lastSeen = Number.isFinite(Number(row.last_event_unix))
            ? new Date(Number(row.last_event_unix) * 1000).toISOString()
            : "";
          const lifetimeBytes = (row && (row.lifetime_bytes ?? row.bytes_served_lifetime ?? row.bytes_served_30d ?? row.month_bytes));
          return \`<td>\${row.user_email || ""}</td><td>\${fmtInt(row.resolve_count)}</td><td>\${fmtGb(lifetimeBytes)}</td><td>\${lastSeen}</td>\`;
        });
        renderLiveTileMap(data.live_tile_map || {});
        renderRows("tilesTable", data.top_tiles, (row) => \`<td>\${row.tile_key || ""}</td><td>\${fmtInt(row.request_count)}</td><td>\${fmtGb(row.bytes_served)}</td>\`);
        renderRows("authRefreshUsersTable", refreshHealth.top_failure_users || [], (row) => \`<td>\${row.user_email || row.user_id || ""}</td><td>\${fmtInt(row.failure_count)}</td><td>\${row.last_failure_at || ""}</td>\`);
        renderRows("authRefreshErrorsTable", refreshHealth.error_breakdown || [], (row) => \`<td>\${row.error_code || ""}</td><td>\${fmtInt(row.count)}</td>\`);
        renderRows("authRefreshCriticalUsersTable", refreshHealth.top_critical_failure_users || [], (row) => \`<td>\${row.user_email || row.user_id || ""}</td><td>\${fmtInt(row.failure_count)}</td><td>\${row.last_failure_at || ""}</td>\`);
        renderRows("authRefreshCriticalErrorsTable", refreshHealth.critical_error_breakdown || [], (row) => \`<td>\${row.error_code || ""}</td><td>\${fmtInt(row.count)}</td>\`);
        renderRows("failsTable", data.recent_failures, (row) => \`<td>\${row.created_at || ""}</td><td>\${row.user_email || ""}</td><td>\${row.status_code || ""}</td><td>\${row.error_code || ""}</td><td>\${row.tile_key || ""}</td><td>\${row.cache_status || ""}</td><td>\${row.duration_ms || ""}</td>\`);
        if (statusEl) {
          statusEl.textContent = "Updated " + new Date().toLocaleTimeString();
          statusEl.className = "muted";
        }
      } catch (error) {
        if (statusEl) {
          statusEl.textContent = "Error: " + String(error && error.message || error);
          statusEl.className = "error";
        }
        const tileMapMetaEl = document.getElementById("tileMapMeta");
        if (tileMapMetaEl) {
          tileMapMetaEl.textContent = "Map load failed.";
        }
      }
    }
	    if (refreshBtn) {
	      refreshBtn.addEventListener("click", (event) => {
        if (event && typeof event.preventDefault === "function") {
          event.preventDefault();
        }
        loadAnalytics();
      });
	    }
	    if (windowEl) windowEl.addEventListener("change", loadAnalytics);
    if (tileMapWindowEl) tileMapWindowEl.addEventListener("change", loadAnalytics);
    document.addEventListener("click", (event) => {
      const button = event.target && event.target.closest ? event.target.closest("button.action-btn") : null;
      if (!button) {
        return;
      }
      const action = String(button.getAttribute("data-action") || "").trim();
      if (!action) {
        return;
      }
      if (action === "map-filter-user") {
        const selected = decodeDataValue(button.getAttribute("data-user-key"));
        setTileMapUserFilter(selected);
        return;
      }
    });
    try {
      loadAnalytics();
      setInterval(loadAnalytics, 15000);
    } catch (error) {
      const message = "Analytics UI error: " + String(error && error.message || error);
      if (statusEl) {
        statusEl.textContent = message;
        statusEl.className = "error";
      }
      const tileMapMetaEl = document.getElementById("tileMapMeta");
      if (tileMapMetaEl) {
        tileMapMetaEl.textContent = message;
      }
      console.error("planetka.admin.analytics.ui_boot_failed", error);
    }
  </script>
</body>
</html>
`
}
