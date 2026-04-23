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
  } = context || {};

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
    select, button { background:#111827; color:#e5e7eb; border:1px solid #374151; border-radius:8px; padding:7px 10px; }
    .action-btn { font-size: 12px; padding: 4px 8px; margin-right: 6px; margin-bottom: 4px; cursor: pointer; }
    .action-btn.warn { border-color: #9a3412; color: #fed7aa; }
    .action-btn.danger { border-color: #991b1b; color: #fecaca; }
    .action-wrap { white-space: nowrap; }
    table { width:100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }
    th, td { border-bottom: 1px solid #1f2937; padding: 8px 6px; text-align:left; }
    th { color:#93c5fd; font-weight:600; }
    .section { margin-top: 20px; }
    .error { color: #fca5a5; }
    .tier-free { color: #ffffff; font-weight: 600; }
    .tier-personal { color: #22c55e; font-weight: 600; }
    .tier-pro { color: #ff9f80; font-weight: 600; }
    .user-filter-active { outline: 1px solid #60a5fa; outline-offset: -1px; }
  </style>
</head>
<body>
  <h1>Planetka Analytics</h1>
  <div class="muted">Signed in as ${escapeHtml(String(user.email || ""))}. Session source: ${escapeHtml(String(tokenSource || "unknown"))}. Auto-refresh every 15 seconds. Build: ${escapeHtml(buildStamp)}</div>
  <div class="controls">
    <a href="/admin/analytics/users" style="color:#93c5fd; text-decoration:none;">All users</a>
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
    <label for="planFilter">User type:</label>
    <select id="planFilter">
      <option value="all" selected>All</option>
      <option value="lite">Personal</option>
      <option value="pro">Pro</option>
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
  <div class="controls">
    <label for="userAdminEmail">Manage user:</label>
    <input id="userAdminEmail" type="email" placeholder="user@example.com" style="min-width: 280px; background:#111827; color:#e5e7eb; border:1px solid #374151; border-radius:8px; padding:7px 10px;" />
    <button id="setLiteBtn" class="action-btn">Set Personal</button>
    <button id="setProBtn" class="action-btn">Set Pro</button>
    <button id="throttleBtn" class="action-btn warn">Throttle 24h</button>
    <button id="unthrottleBtn" class="action-btn">Unthrottle</button>
    <button id="blockBtn" class="action-btn danger">Block</button>
    <button id="unblockBtn" class="action-btn warn">Unblock</button>
  </div>

  <div class="grid">
    <div class="card"><div class="label">Active users (5m)</div><div id="active5" class="value">${escapeHtml(fmtIntLocal(snapshotActive.users_5m))}</div></div>
    <div class="card"><div class="label">Active users (15m)</div><div id="active15" class="value">${escapeHtml(fmtIntLocal(snapshotActive.users_15m))}</div></div>
    <div class="card"><div class="label">Active users (60m)</div><div id="active60" class="value">${escapeHtml(fmtIntLocal(snapshotActive.users_60m))}</div></div>
    <div class="card"><div class="label">Live tile events (10s)</div><div id="live10s" class="value">${escapeHtml(fmtIntLocal(snapshotActive.tile_events_10s))}</div></div>
    <div class="card"><div class="label">Tile requests (window)</div><div id="reqCount" class="value">${escapeHtml(fmtIntLocal(snapshotSummary.request_count))}</div></div>
    <div class="card"><div class="label">Bytes served (window)</div><div id="bytesServed" class="value">${escapeHtml(fmtGbLocal(snapshotSummary.bytes_served))} GB</div></div>
    <div class="card"><div class="label">Errors (window)</div><div id="errors" class="value">${escapeHtml(fmtIntLocal(snapshotSummary.error_count))}</div></div>
    <div class="card"><div class="label">Cache hit ratio</div><div id="hitRatio" class="value">${escapeHtml((Number(snapshotSummary.request_count || 0) > 0 ? (100 * Number(snapshotSummary.cache_hit_count || 0) / Number(snapshotSummary.request_count || 1)) : 0).toFixed(2))}%</div></div>
    <div class="card"><div class="label">Tagged resolves</div><div id="resolveCount" class="value">${escapeHtml(fmtIntLocal(snapshotSummary.tagged_resolve_count))}</div></div>
    <div class="card"><div class="label" id="authRefreshAttemptsLabel">Refresh Attempts (7d)</div><div id="authRefreshTotal" class="value">-</div></div>
    <div class="card"><div class="label" id="authRefreshFailuresLabel">Refresh Failures (7d)</div><div id="authRefreshFailures" class="value">-</div></div>
    <div class="card"><div class="label">Refresh Failure Rate</div><div id="authRefreshFailureRate" class="value">-</div></div>
  </div>

  <div class="section">
    <h3>Active Users (Last 10 min)</h3>
    <table id="activeUsersTable"><thead><tr><th>Email</th><th>Plan</th><th>Requests</th><th>Resolves</th><th>GB</th><th>Last seen</th></tr></thead><tbody>${serverActiveUsersRowsHtml}</tbody></table>
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
    <table id="tileMapUsersTable" style="max-width: 980px;"><thead><tr><th>User</th><th>Tier</th><th>Color</th><th>Tiles (window)</th><th>Requests (window)</th><th>GB (window)</th><th>Map</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Top Tiles</h3>
    <table id="tilesTable"><thead><tr><th>Tile key</th><th>Requests</th><th>GB</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3 id="authRefreshHeading">Auth Refresh Health (7d)</h3>
    <table id="authRefreshUsersTable"><thead><tr><th>User</th><th>Failure Count</th><th>Last Failure</th></tr></thead><tbody></tbody></table>
    <table id="authRefreshErrorsTable"><thead><tr><th>Error</th><th>Count</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Recent Failures</h3>
    <table id="failsTable"><thead><tr><th>Time</th><th>User</th><th>Status</th><th>Error</th><th>Tile</th><th>Cache</th><th>ms</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Heavy Users (Top 20 by Month GB)</h3>
    <table id="heavyTable"><thead><tr><th>Email</th><th>Plan</th><th>Resolves</th><th>Month GB</th><th>Month Requests</th><th>Last Seen</th></tr></thead><tbody>${serverHeavyRowsHtml}</tbody></table>
  </div>
  <div class="section">
    <h3>Cloudflare Billable Usage (R2)</h3>
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
    const planFilterEl = document.getElementById("planFilter");
    const tileMapWindowEl = document.getElementById("tileMapWindow");
    const refreshBtn = document.getElementById("refresh");
    const userAdminEmailEl = document.getElementById("userAdminEmail");
    const setLiteBtn = document.getElementById("setLiteBtn");
    const setProBtn = document.getElementById("setProBtn");
    const throttleBtn = document.getElementById("throttleBtn");
    const unthrottleBtn = document.getElementById("unthrottleBtn");
    const blockBtn = document.getElementById("blockBtn");
    const unblockBtn = document.getElementById("unblockBtn");
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
    const fmtFixed = (v, digits = 2) => {
      const numeric = Number(v);
      return Number.isFinite(numeric) ? numeric.toFixed(digits) : "0.00";
    };
    const decodeDataValue = (v) => {
      try {
        return decodeURIComponent(String(v || ""));
      } catch (_error) {
        return String(v || "");
      }
    };
    const encodeDataValue = (v) => encodeURIComponent(String(v || ""));
    const tierClass = (planCode) => {
      const tier = normalizePlanCode(planCode);
      if (tier === "pro") return "tier-pro";
      if (tier === "personal") return "tier-personal";
      return "tier-free";
    };
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
    function renderCloudflareBillableUsage(payload) {
      const data = payload && typeof payload === "object" ? payload : {};
      const available = Boolean(data.available);
      const bucket = String(data.bucket_filter || "").trim();
      const metaText = available
        ? (data && data.estimated
          ? ("Estimated billable usage from telemetry. Source: "
            + String(data.source || "telemetry_estimate")
            + ". Period: " + String(data.period_start || "-")
            + " -> " + String(data.period_end || "-"))
          : ("Cloudflare GraphQL live data. Source: "
            + String(data.source || "cloudflare_graphql")
            + ". Bucket: " + (bucket || "all buckets")
            + ". Period: " + String(data.period_start || "-")
            + " -> " + String(data.period_end || "-")))
        : ("Cloudflare billable usage unavailable. "
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
    const TILE_COLOR_FREE = "#ffffff";
    const TILE_COLOR_PERSONAL = "#22c55e";
    const TILE_COLOR_PRO = "#ff9f80";
    const TILE_MAP_BASEMAP_URL = "/admin/analytics/world-map.jpg";
    let tileMapBaseImage = null;
    let tileMapBaseImageState = "idle";
    let tileMapLastPayload = null;
    let tileMapSelectedUserKey = "";
    function normalizePlanCode(planCode) {
      const normalized = String(planCode || "").trim().toLowerCase();
      if (normalized === "planetka_pro" || normalized === "pro" || normalized === "planetka_studio" || normalized === "studio") {
        return "pro";
      }
      if (normalized === "planetka" || normalized === "personal" || normalized === "basic" || normalized === "lite" || normalized === "indie") {
        return "personal";
      }
      if (normalized === "free" || normalized === "trial" || normalized === "planetka_free") {
        return "free";
      }
      return "personal";
    }
    function planLabel(planCode) {
      const tier = normalizePlanCode(planCode);
      if (tier === "pro") return "Pro";
      if (tier === "personal") return "Personal";
      return "Free";
    }
    function planColor(planCode) {
      const tier = normalizePlanCode(planCode);
      if (tier === "pro") return TILE_COLOR_PRO;
      if (tier === "personal") return TILE_COLOR_PERSONAL;
      return TILE_COLOR_FREE;
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
        const userStatus = String(row && row.user_status || "planetka").trim().toLowerCase();
        const userColor = planColor(userStatus);
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
            plan: planLabel(userStatus),
            color: userColor,
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
        html: \`<td class="\${tierClass(row.plan)}">\${row.email || ""}</td>
        <td class="\${tierClass(row.plan)}">\${row.plan || "Personal"}</td>
        <td><span style="display:inline-block;width:14px;height:14px;border-radius:3px;background:\${row.color};border:1px solid #111827;"></span> \${row.color || ""}</td>
        <td>\${fmtInt(row.tileCount)}</td>
        <td>\${fmtInt(row.requestCount)}</td>
        <td>\${fmtGb(row.bytesServed)}</td>
        <td><button class="action-btn" data-action="map-filter-user" data-user-key="\${encodeDataValue(row.userKey || "")}">\${tileMapSelectedUserKey && tileMapSelectedUserKey === row.userKey ? "Show All" : "Show"}</button></td>\`,
        rowClass: tileMapSelectedUserKey && tileMapSelectedUserKey === row.userKey ? "user-filter-active" : "",
      }));
    }
    async function performUserAction(action, userId, userEmail, planCode) {
      const safeAction = String(action || "").trim();
      const safeUserId = String(userId || "").trim();
      const safeUserEmail = String(userEmail || "").trim();
      const safePlanCode = String(planCode || "").trim().toLowerCase();
      if (!safeAction || (!safeUserId && !safeUserEmail)) {
        statusEl.textContent = "Action failed: missing user id/email.";
        statusEl.className = "error";
        return;
      }
      const endpointByAction = {
        unthrottle: "/admin/users/unthrottle",
        throttle: "/admin/users/throttle",
        block: "/admin/users/block",
        unblock: "/admin/users/unblock",
        "hard-block": "/admin/users/hard-block",
        "set-lite": "/admin/users/set-plan",
        "set-pro": "/admin/users/set-plan",
      };
      const endpoint = endpointByAction[safeAction];
      if (!endpoint) {
        statusEl.textContent = "Action failed: unknown action.";
        statusEl.className = "error";
        return;
      }
      const confirmation = {
        unthrottle: "Unthrottle this account now?",
        throttle: "Throttle this account now for 24 hours?",
        block: "Block this user account now?",
        unblock: "Unblock this user account now?",
        "hard-block": "Hard block this user and block same-computer attempts?",
        "set-lite": "Downgrade this account to Personal?",
        "set-pro": "Upgrade this account to Pro?",
      };
      if (!window.confirm(confirmation[safeAction] || "Confirm action?")) {
        return;
      }
      const payload = { email: safeUserEmail };
      if (safeUserId) {
        payload.user_id = safeUserId;
      }
      if (safeAction === "throttle") {
        payload.duration_minutes = 1440;
      }
      if (safeAction === "unblock") {
        payload.plan_code = (!safePlanCode || safePlanCode === "blocked") ? "lite" : safePlanCode;
      }
      if (safeAction === "set-lite") {
        payload.plan_code = "lite";
      }
      if (safeAction === "set-pro") {
        payload.plan_code = "pro";
      }
      statusEl.textContent = "Applying action...";
      statusEl.className = "muted";
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error((data && data.error) || ("HTTP " + res.status));
        }
        statusEl.textContent = "Action applied: " + safeAction + " (" + safeUserEmail + ")";
        statusEl.className = "muted";
        await loadAnalytics();
      } catch (error) {
        statusEl.textContent = "Action failed: " + String(error && error.message || error);
        statusEl.className = "error";
      }
    }
    async function loadAnalytics() {
      try {
        const minutes = String((windowEl && windowEl.value) || "60");
        const planFilter = String((planFilterEl && planFilterEl.value) || "all");
        const tileMapMinutes = String((tileMapWindowEl && tileMapWindowEl.value) || "1");
        if (statusEl) {
          statusEl.textContent = "Loading...";
        }
        const res = await fetch(
          "/admin/analytics/data?minutes=" + encodeURIComponent(minutes) +
          "&plan_filter=" + encodeURIComponent(planFilter) +
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
        setText("active5", fmtInt(a.users_5m));
        setText("active15", fmtInt(a.users_15m));
        setText("active60", fmtInt(a.users_60m));
        setText("live10s", fmtInt(a.tile_events_10s));
        setText("reqCount", fmtInt(s.request_count));
        setText("bytesServed", fmtBytes(s.bytes_served));
        setText("errors", fmtInt(s.error_count));
        const hitRatio = Number(s.request_count || 0) > 0 ? (100 * Number(s.cache_hit_count || 0) / Number(s.request_count || 1)) : 0;
        setText("hitRatio", hitRatio.toFixed(2) + "%");
        setText("resolveCount", fmtInt(s.tagged_resolve_count));
        const refreshHealth = data.auth_refresh_health || {};
        const refreshTotal = Number(refreshHealth.total_count || 0);
        const refreshFailures = Number(refreshHealth.failure_count || 0);
        const refreshFailureRate = refreshTotal > 0 ? (100 * refreshFailures / refreshTotal) : 0;
        setText("authRefreshTotal", fmtInt(refreshTotal));
        setText("authRefreshFailures", fmtInt(refreshFailures));
        setText("authRefreshFailureRate", refreshFailureRate.toFixed(2) + "%");
        renderCloudflareBillableUsage(data.cloudflare_billable_usage || {});
        renderRows("activeUsersTable", data.active_users_10m, (row) => {
          const normalizedPlan = normalizePlanCode(row && row.user_status);
          const tier = normalizedPlan === "pro" ? "Pro" : (normalizedPlan === "personal" ? "Personal" : "Free");
          const tierCss = tierClass(normalizedPlan);
          return \`<td class="\${tierCss}">\${row.user_email || ""}</td><td class="\${tierCss}">\${tier}</td><td>\${fmtInt(row.request_count)}</td><td>\${fmtInt(row.resolve_count)}</td><td>\${fmtGb(row.bytes_served)}</td><td>\${row.last_seen_at || ""}</td>\`;
        });
        renderRows("heavyTable", data.heavy_users_30d || [], (row) => {
          const rawPlanCode = String(row.user_status || "planetka").trim().toLowerCase();
          const normalizedPlan = normalizePlanCode(rawPlanCode);
          const planLabelText = normalizedPlan === "pro" ? "Pro" : (normalizedPlan === "personal" ? "Personal" : "Free");
          const tierCss = tierClass(normalizedPlan);
          const lastSeen = Number.isFinite(Number(row.last_event_unix))
            ? new Date(Number(row.last_event_unix) * 1000).toISOString()
            : "";
          const monthBytes = (row && (row.month_bytes ?? row.bytes_served_30d));
          const monthRequests = (row && (row.request_count_month ?? row.request_count_30d));
          return \`<td class="\${tierCss}">\${row.user_email || ""}</td><td class="\${tierCss}">\${planLabelText}</td><td>\${fmtInt(row.resolve_count)}</td><td>\${fmtGb(monthBytes)}</td><td>\${fmtInt(monthRequests)}</td><td>\${lastSeen}</td>\`;
        });
        renderLiveTileMap(data.live_tile_map || {});
        renderRows("tilesTable", data.top_tiles, (row) => \`<td>\${row.tile_key || ""}</td><td>\${fmtInt(row.request_count)}</td><td>\${fmtGb(row.bytes_served)}</td>\`);
        renderRows("authRefreshUsersTable", refreshHealth.top_failure_users || [], (row) => \`<td>\${row.user_email || row.user_id || ""}</td><td>\${fmtInt(row.failure_count)}</td><td>\${row.last_failure_at || ""}</td>\`);
        renderRows("authRefreshErrorsTable", refreshHealth.error_breakdown || [], (row) => \`<td>\${row.error_code || ""}</td><td>\${fmtInt(row.count)}</td>\`);
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
    const runManualUserAction = (actionName) => {
      const email = String((userAdminEmailEl && userAdminEmailEl.value) || "").trim();
      if (!email || !email.includes("@")) {
        statusEl.textContent = "Enter a valid user email first.";
        statusEl.className = "error";
        return;
      }
      performUserAction(actionName, "", email, "");
    };
    if (setLiteBtn) setLiteBtn.addEventListener("click", () => runManualUserAction("set-lite"));
    if (setProBtn) setProBtn.addEventListener("click", () => runManualUserAction("set-pro"));
    if (throttleBtn) throttleBtn.addEventListener("click", () => runManualUserAction("throttle"));
    if (unthrottleBtn) unthrottleBtn.addEventListener("click", () => runManualUserAction("unthrottle"));
    if (blockBtn) blockBtn.addEventListener("click", () => runManualUserAction("block"));
    if (unblockBtn) unblockBtn.addEventListener("click", () => runManualUserAction("unblock"));
    if (windowEl) windowEl.addEventListener("change", loadAnalytics);
    if (planFilterEl) planFilterEl.addEventListener("change", loadAnalytics);
    if (tileMapWindowEl) tileMapWindowEl.addEventListener("change", loadAnalytics);
    document.addEventListener("click", (event) => {
      const button = event.target && event.target.closest ? event.target.closest("button.action-btn") : null;
      if (!button) {
        return;
      }
      const action = String(button.getAttribute("data-action") || "").trim();
      if (action === "map-filter-user") {
        const selected = decodeDataValue(button.getAttribute("data-user-key"));
        setTileMapUserFilter(selected);
        return;
      }
      const userId = decodeDataValue(button.getAttribute("data-user-id"));
      const userEmail = decodeDataValue(button.getAttribute("data-user-email"));
      const planCode = decodeDataValue(button.getAttribute("data-plan-code"));
      performUserAction(action, userId, userEmail, planCode);
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
