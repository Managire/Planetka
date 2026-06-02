import { buildAdminAnalyticsPageHtml } from "../admin_analytics_page.js";

function fmtIntLocal(value, parseNonNegativeInteger) {
  return Number(parseNonNegativeInteger(value, 0)).toLocaleString();
}

function fmtGbLocal(value, parseNonNegativeInteger, bytesPerGb) {
  return (Number(parseNonNegativeInteger(value, 0)) / bytesPerGb).toLocaleString("en-US", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  });
}

function fmtMbLocal(value, parseNonNegativeInteger) {
  return (Number(parseNonNegativeInteger(value, 0)) / (1024 * 1024)).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const ANALYTICS_TILE_COLOR = "#60a5fa";

function snapshotHasTopLineTotals(snapshot) {
  const topLine = snapshot && snapshot.top_line && typeof snapshot.top_line === "object" ? snapshot.top_line : {};
  return ["installs", "resolves", "tile_requests", "gb_served"].every((key) => {
    const section = topLine[key] && typeof topLine[key] === "object" ? topLine[key] : {};
    return Object.prototype.hasOwnProperty.call(section, "total");
  });
}

function parseLiveMapTile(tileKey) {
  const text = String(tileKey || "").trim();
  const match = /_x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})\.(?:exr|tif|tiff|png|jpe?g)$/i.exec(text);
  if (!match) return null;
  const x = Number.parseInt(match[1], 10);
  const y = Number.parseInt(match[2], 10);
  const z = Number.parseInt(match[3], 10);
  const d = Number.parseInt(match[4], 10);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z) || !Number.isFinite(d)) return null;
  if (x < 0 || x > 359 || y < 0 || y > 179 || z <= 0 || z > 360) return null;
  return { x, y, z, d };
}

function filterAnalyticsInstallsRows(rows, query) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) {
    return safeRows.slice();
  }
  return safeRows.filter((row) => {
    const email = String(row && row.install_email || "").trim().toLowerCase();
    const installId = String(row && row.install_id || "").trim().toLowerCase();
    return email.includes(needle) || installId.includes(needle);
  });
}

function analyticsInstallsSortValue(row, sortBy) {
  if (sortBy === "total_resolves") return Number(row && row.total_resolve_count || row && row.resolve_count || 0);
  if (sortBy === "data_downloaded") return Number(row && row.data_downloaded_bytes || 0);
  if (sortBy === "last_seen") return Date.parse(String(row && row.last_seen_at || "")) || 0;
  return Number(row && row.data_downloaded_bytes || 0);
}

function sortAnalyticsInstallsRows(rows, sortBy, sortDir) {
  const safeRows = Array.isArray(rows) ? rows.slice() : [];
  const direction = String(sortDir || "desc").trim().toLowerCase() === "asc" ? 1 : -1;
  safeRows.sort((left, right) => {
    const primary = analyticsInstallsSortValue(left, sortBy) - analyticsInstallsSortValue(right, sortBy);
    if (primary !== 0) {
      return primary * direction;
    }
    return String(left && left.install_email || "").localeCompare(String(right && right.install_email || "")) * direction;
  });
  return safeRows;
}

export async function handleAdminAnalyticsData(request, env, deps) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return deps.json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, install } = auth;
  const windowMinutes = deps.sanitizeAnalyticsMinutes(url.searchParams.get("minutes"), deps.DEFAULT_ANALYTICS_WINDOW_MINUTES);
  const tileMapMinutes = deps.sanitizeLiveTileMapMinutes(
    url.searchParams.get("tile_map_minutes"),
    deps.DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
  );
  const access_statusFilter = "all";
  try {
    let snapshot = await deps.loadAnalyticsSnapshot(env, windowMinutes, access_statusFilter, tileMapMinutes);
    if (!snapshot || deps.isAnalyticsSnapshotStale(snapshot) || !snapshotHasTopLineTotals(snapshot)) {
      snapshot = await deps.collectAnalyticsSnapshot(db, windowMinutes, access_statusFilter, tileMapMinutes, env);
      snapshot = {
        ...snapshot,
        snapshot_minutes: windowMinutes,
        snapshot_access_status_filter: access_statusFilter,
        snapshot_tile_map_minutes: tileMapMinutes,
        snapshot_source: "live_rebuild",
      };
      await deps.storeAnalyticsSnapshot(env, windowMinutes, access_statusFilter, tileMapMinutes, snapshot);
    }
    return deps.json(
      {
        ok: true,
        admin_email: String(install.email || ""),
        ...snapshot,
      },
      200,
      env,
    );
  } catch (error) {
    const message = String(error && error.message || "analytics_data_failed");
    console.error(
      "planetka.admin.analytics.data_failed",
      JSON.stringify({
        error: message,
        install_id: String(install && install.id || ""),
        install_email: String(install && install.email || ""),
        access_status_filter: "all",
        window_minutes: windowMinutes,
        tile_map_minutes: tileMapMinutes,
      }),
    );
    return deps.json(
      {
        ok: false,
        error: "analytics_data_failed",
        message: deps.publicErrorMessage("Analytics data is temporarily unavailable."),
      },
      500,
      env,
    );
  }
}

export async function handleAdminAnalyticsTileMapImage(request, env, deps) {
  void request;
  const key = String(env.ADMIN_ANALYTICS_TILE_MAP_KEY || deps.DEFAULT_ADMIN_ANALYTICS_TILE_MAP_KEY).trim();
  if (!key) {
    return deps.json({ ok: false, error: "tile_map_key_not_configured" }, 500, env);
  }
  const bucket = env.PLANETKA_DATA;
  if (!bucket) {
    return deps.json({ ok: false, error: "r2_not_bound" }, 500, env);
  }
  const object = await bucket.get(key);
  if (!object || !object.body) {
    return deps.json({ ok: false, error: "tile_map_image_not_found" }, 404, env);
  }
  const headers = {
    ...deps.corsHeaders(env),
    "Content-Type": String(object.httpMetadata && object.httpMetadata.contentType || "image/jpeg"),
    "Cache-Control": "public, max-age=3600",
  };
  return new Response(object.body, { status: 200, headers });
}

export async function handleAdminAnalyticsPage(request, env, deps) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return deps.json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { install, tokenSource } = auth;
  let initialSnapshot = null;
  try {
    initialSnapshot = await deps.loadAnalyticsSnapshot(env, 10080, "all", 10);
    if (!initialSnapshot || deps.isAnalyticsSnapshotStale(initialSnapshot) || !snapshotHasTopLineTotals(initialSnapshot)) {
      initialSnapshot = await deps.collectAnalyticsSnapshot(
        auth.db,
        10080,
        "all",
        10,
        env,
      );
      initialSnapshot = {
        ...initialSnapshot,
        snapshot_minutes: 10080,
        snapshot_access_status_filter: "all",
        snapshot_tile_map_minutes: 10,
        snapshot_source: "live_rebuild",
      };
      await deps.storeAnalyticsSnapshot(env, 10080, "all", 10, initialSnapshot);
    }
  } catch (error) {
    console.error(
      "planetka.admin.analytics.page_snapshot_failed",
      JSON.stringify({
        error: String(error && error.message || "analytics_page_snapshot_failed"),
        install_id: String(install && install.id || ""),
        install_email: String(install && install.email || ""),
      }),
    );
  }
  const snapshotTopLine = initialSnapshot && initialSnapshot.top_line ? initialSnapshot.top_line : {};
  const snapshotSummary = initialSnapshot && initialSnapshot.summary ? initialSnapshot.summary : {};
  const snapshotLiveMap = initialSnapshot && initialSnapshot.live_tile_map ? initialSnapshot.live_tile_map : {};
  const snapshotLiveRows = Array.isArray(snapshotLiveMap && snapshotLiveMap.rows) ? snapshotLiveMap.rows : [];
  const snapshotActiveInstalls10m = Array.isArray(initialSnapshot && initialSnapshot.active_installs_10m)
    ? initialSnapshot.active_installs_10m
    : [];
  const snapshotHeavyInstalls = Array.isArray(initialSnapshot && initialSnapshot.heavy_installs_30d)
    ? initialSnapshot.heavy_installs_30d
    : [];
  const fmtInt = (value) => fmtIntLocal(value, deps.parseNonNegativeInteger);
  const fmtGb = (value) => fmtGbLocal(value, deps.parseNonNegativeInteger, deps.BYTES_PER_GB);
  const serverActiveInstallsRowsHtml = snapshotActiveInstalls10m.map((row) => {
    const email = deps.escapeHtml(String(row && row.install_email || ""));
    return `<tr><td>${email}</td><td>${fmtInt(row && row.request_count)}</td><td>${fmtInt(row && row.resolve_count)}</td><td>${fmtGb(row && row.bytes_served)}</td><td>${deps.escapeHtml(String(row && row.last_seen_at || ""))}</td></tr>`;
  }).join("");
  const serverHeavyRowsHtml = snapshotHeavyInstalls.slice(0, 20).map((row) => {
    const email = deps.escapeHtml(String(row && row.install_email || ""));
    const lastSeen = Number.isFinite(Number(row && row.last_event_unix))
      ? new Date(Number(row.last_event_unix) * 1000).toISOString()
      : "";
    const lifetimeBytes = row && (row.lifetime_bytes ?? row.bytes_served_lifetime ?? row.month_bytes ?? row.bytes_served_30d);
    return `<tr><td>${email}</td><td>${fmtInt(row && row.resolve_count)}</td><td>${fmtGb(lifetimeBytes)}</td><td>${deps.escapeHtml(lastSeen)}</td></tr>`;
  }).join("");
  const serverMapRectsSvg = snapshotLiveRows
    .map((row) => {
      const parsed = parseLiveMapTile(row && row.tile_key);
      if (!parsed) return "";
      if (parsed.z === 90 || parsed.z === 180 || parsed.z === 360) return "";
      const x = parsed.x * 2;
      const y = (180 - (parsed.y + parsed.z)) * 2;
      const w = parsed.z * 2;
      const h = parsed.z * 2;
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(w) || !Number.isFinite(h)) return "";
      if ((x + w) <= 0 || (y + h) <= 0 || x >= 720 || y >= 360) return "";
      const color = ANALYTICS_TILE_COLOR;
      const rawD = Number(parsed.d || 1);
      const alpha = Math.max(0.05, Math.min(1, 1 / Math.max(1, rawD)));
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" fill="${color}" fill-opacity="${alpha.toFixed(3)}" stroke="${color}" stroke-width="0.5" stroke-opacity="0.95"></rect>`;
    })
    .filter(Boolean)
    .join("");
  const snapshotGeneratedAt = deps.escapeHtml(String(initialSnapshot && initialSnapshot.generated_at || deps.nowIso()));
  const buildStamp = deps.nowIso();
  const htmlContent = buildAdminAnalyticsPageHtml({
    escapeHtml: deps.escapeHtml,
    encodeURIComponent,
    install,
    tokenSource,
    buildStamp,
    snapshotGeneratedAt,
    fmtIntLocal: fmtInt,
    fmtGbLocal: fmtGb,
    snapshotTopLine,
    snapshotSummary,
    snapshotLiveMap,
    serverActiveInstallsRowsHtml,
    serverMapRectsSvg,
    serverHeavyRowsHtml,
  });
  if (tokenSource === "bearer") {
    const authHeader = String(request.headers.get("Authorization") || "");
    if (authHeader.startsWith("Bearer ")) {
      const token = authHeader.slice("Bearer ".length).trim();
      if (token) {
        return new Response(htmlContent, {
          status: 200,
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            ...deps.corsHeaders(env),
            "Set-Cookie": deps.buildAdminSessionCookie(token),
          },
        });
      }
    }
  }
  return deps.html(htmlContent, 200, env);
}

export async function handleAdminAnalyticsInstallsPage(request, env, deps) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return deps.json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, install } = auth;
  const query = String(url.searchParams.get("q") || "").trim();
  const sortBy = deps.parseAnalyticsInstallsSort(url.searchParams.get("sort"));
  const sortDir = deps.parseAnalyticsInstallsSortDirection(url.searchParams.get("dir"));
  let installsSnapshot = await deps.loadAnalyticsInstallsSnapshot(env);
  if (!installsSnapshot || deps.isAnalyticsSnapshotStale(installsSnapshot)) {
    installsSnapshot = await deps.buildAnalyticsInstallsSnapshot(db, env);
  }
  const rows = sortAnalyticsInstallsRows(
    filterAnalyticsInstallsRows(installsSnapshot && installsSnapshot.rows, query),
    sortBy,
    sortDir,
  );
  const fmtInt = (value) => fmtIntLocal(value, deps.parseNonNegativeInteger);
  const fmtMb = (value) => fmtMbLocal(value, deps.parseNonNegativeInteger);
  const buildSortHref = (key) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    params.set("sort", key);
    const nextDir = (sortBy === key && sortDir === "desc") ? "asc" : "desc";
    params.set("dir", nextDir);
    return `/admin/analytics/installs?${params.toString()}`;
  };
  const sortMarker = (key) => (sortBy === key ? (sortDir === "desc" ? " ▼" : " ▲") : "");
  const rowsHtml = (Array.isArray(rows) ? rows : []).map((row) => {
    const installIdRaw = String(row && row.install_id || "");
    const installEmailRaw = String(row && row.install_email || "");
    const installEmail = deps.escapeHtml(installEmailRaw);
    const status = String(row && row.install_status || "").trim().toLowerCase();
    const installState = status === "blocked" ? "blocked" : "active";
    const installStateLabel = installState === "blocked" ? "Blocked" : "Active";
    let actionButtons = "";
    if (status === "blocked") {
      actionButtons = `<button class="action-btn warn" data-action="unblock" data-install-id="${encodeURIComponent(installIdRaw)}" data-install-email="${encodeURIComponent(installEmailRaw)}">Unblock</button><button class="action-btn danger" data-action="hard-block" data-install-id="${encodeURIComponent(installIdRaw)}" data-install-email="${encodeURIComponent(installEmailRaw)}">Hard Block</button>`;
    } else {
      actionButtons = `<button class="action-btn danger" data-action="block" data-install-id="${encodeURIComponent(installIdRaw)}" data-install-email="${encodeURIComponent(installEmailRaw)}">Block</button><button class="action-btn danger" data-action="hard-block" data-install-id="${encodeURIComponent(installIdRaw)}" data-install-email="${encodeURIComponent(installEmailRaw)}">Hard Block</button>`;
    }
    return `<tr>
      <td><code>${deps.escapeHtml(installIdRaw)}</code></td>
      <td>${installEmail || '<span class="muted">Anonymous install</span>'}</td>
      <td><span class="access_status-pill ${deps.escapeHtml(installState)}">${deps.escapeHtml(installStateLabel)}</span></td>
      <td>${fmtInt(row && (row.total_resolve_count ?? row.resolve_count))}</td>
      <td>${fmtMb(row && row.data_downloaded_bytes)} MB</td>
      <td>${deps.escapeHtml(String(row && row.last_seen_at || ""))}</td>
      <td class="action-wrap">${actionButtons}</td>
    </tr>`;
  }).join("");

  const htmlContent = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planetka Analytics - All Installs</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 20px; background: #0b1020; color: #e5e7eb; }
    h1 { margin: 0 0 8px; font-size: 24px; }
    .muted { color: #9ca3af; font-size: 13px; }
    .controls { display:flex; gap:10px; align-items:center; flex-wrap: wrap; margin: 8px 0 16px; }
    input, button, select { background:#111827; color:#e5e7eb; border:1px solid #374151; border-radius:8px; padding:7px 10px; }
    table { width:100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }
    th, td { border-bottom: 1px solid #1f2937; padding: 8px 6px; text-align:left; vertical-align: top; }
    th { color:#93c5fd; font-weight:600; white-space: nowrap; }
    th a { color:#93c5fd; text-decoration:none; }
    .action-btn { font-size: 12px; padding: 4px 8px; margin-right: 6px; margin-bottom: 4px; cursor: pointer; }
    .action-btn.warn { border-color: #9a3412; color: #fed7aa; }
    .action-btn.danger { border-color: #991b1b; color: #fecaca; }
    .action-wrap { white-space: normal; min-width: 300px; }
    .access_status-pill { display:inline-block; min-width:84px; text-align:center; border-radius:999px; padding:3px 8px; border:1px solid #374151; font-size:12px; }
    .access_status-pill.active { color:#bbf7d0; border-color:#166534; background:rgba(22,101,52,.20); }
    .error { color: #fca5a5; }
  </style>
</head>
<body>
  <h1>All Installs</h1>
  <div class="muted">Signed in as ${deps.escapeHtml(String(install.email || ""))}</div>
  <div class="controls">
    <a href="/admin/analytics" style="color:#93c5fd; text-decoration:none;">Back to analytics</a>
    <a href="/admin/session/logout" style="color:#fca5a5; text-decoration:none;">Sign Out</a>
  </div>
  <form class="controls" method="GET" action="/admin/analytics/installs">
    <label for="q">Search install:</label>
    <input id="q" name="q" type="text" value="${deps.escapeHtml(query)}" placeholder="email or Planetka install id" />
    <input type="hidden" name="sort" value="${deps.escapeHtml(sortBy)}" />
    <input type="hidden" name="dir" value="${deps.escapeHtml(sortDir)}" />
    <button type="submit">Search</button>
    <span class="muted">${fmtInt(Array.isArray(rows) ? rows.length : 0)} installs shown</span>
  </form>
  <div id="status" class="muted">Ready</div>
  <table>
    <thead>
      <tr>
        <th>Email</th>
        <th>Planetka Install ID</th>
        <th>Status</th>
        <th><a href="${buildSortHref("total_resolves")}">Total Resolves${sortMarker("total_resolves")}</a></th>
        <th><a href="${buildSortHref("data_downloaded")}">Data Downloaded${sortMarker("data_downloaded")}</a></th>
        <th><a href="${buildSortHref("last_seen")}">Last Seen${sortMarker("last_seen")}</a></th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>${rowsHtml}</tbody>
  </table>
  <script>
    const statusEl = document.getElementById("status");

    const decodeDataValue = (v) => {
      try { return decodeURIComponent(String(v || "")); } catch (_e) { return String(v || ""); }
    };
    function renderRows(tableId, rows, rowBuilder) {
      const tbody = document.querySelector("#" + tableId + " tbody");
      if (!tbody) return;
      tbody.innerHTML = "";
      const rowsSafe = Array.isArray(rows) ? rows : [];
      for (const row of rowsSafe) {
        const tr = document.createElement("tr");
        tr.innerHTML = String(rowBuilder(row) || "");
        tbody.appendChild(tr);
      }
    }
    async function performInstallAction(action, installId, installEmail) {
      const safeAction = String(action || "").trim();
      const safeInstallId = String(installId || "").trim();
      const safeInstallEmail = String(installEmail || "").trim();
      const endpointByAction = {
        block: "/admin/installs/block",
        unblock: "/admin/installs/unblock",
        "hard-block": "/admin/installs/hard-block",
      };
      const confirmation = {
        block: "Block this install now?",
        unblock: "Unblock this install now?",
        "hard-block": "Hard block this install and block same-computer attempts?",
      };
      const endpoint = endpointByAction[safeAction];
      if (!endpoint) return;
      if (!window.confirm(confirmation[safeAction] || "Confirm action?")) return;
      const payload = { email: safeInstallEmail };
      if (safeInstallId) payload.install_id = safeInstallId;
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
          throw new Error((data && (data.message || data.error)) || ("HTTP " + res.status));
        }
        statusEl.textContent = "Action applied: " + safeAction + " (" + safeInstallEmail + ")";
        statusEl.className = "muted";
        window.location.reload();
      } catch (error) {
        statusEl.textContent = "Action failed: " + String(error && error.message || error);
        statusEl.className = "error";
      }
    }
    document.addEventListener("click", (event) => {
      const button = event.target && event.target.closest ? event.target.closest("button.action-btn") : null;
      if (!button) return;
      const action = String(button.getAttribute("data-action") || "").trim();
      if (!action) return;
      const installId = decodeDataValue(button.getAttribute("data-install-id"));
      const installEmail = decodeDataValue(button.getAttribute("data-install-email"));
      performInstallAction(action, installId, installEmail);
    });
  </script>
</body>
</html>`;
  return deps.html(htmlContent, 200, env);
}
