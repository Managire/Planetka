import { buildAdminAnalyticsPageHtml } from "../admin_analytics_page.js";

function fmtIntLocal(value, parseNonNegativeInteger) {
  return Number(parseNonNegativeInteger(value, 0)).toLocaleString();
}

function fmtGbLocal(value, parseNonNegativeInteger, bytesPerGb) {
  return (Number(parseNonNegativeInteger(value, 0)) / bytesPerGb).toFixed(3);
}

function analyticsTierCodeFromStatus(statusValue, deps) {
  const normalized = deps.normalizePlanCode(statusValue);
  if (normalized === deps.PLAN_CODE_COMMERCIAL) return "commercial";
  if (normalized === deps.PLAN_CODE_PERSONAL) return "personal";
  return "free";
}

function analyticsTierLabelFromStatus(statusValue, deps) {
  const tierCode = analyticsTierCodeFromStatus(statusValue, deps);
  if (tierCode === "commercial") return "Commercial";
  if (tierCode === "personal") return "Personal";
  return "Free";
}

function analyticsTierClassFromStatus(statusValue, deps) {
  const tierCode = analyticsTierCodeFromStatus(statusValue, deps);
  if (tierCode === "commercial") return "tier-commercial";
  if (tierCode === "personal") return "tier-personal";
  return "tier-free";
}

function analyticsTierColorFromStatus(statusValue, deps) {
  const tierCode = analyticsTierCodeFromStatus(statusValue, deps);
  if (tierCode === "commercial") return "#ef4444";
  if (tierCode === "personal") return "#22c55e";
  return "#ffffff";
}

function qualityOverrideModeFromValue(value) {
  if (value === null || value === undefined || String(value).trim() === "") {
    return "inherit";
  }
  const text = String(value).trim().toLowerCase();
  if (text === "1" || text === "true" || text === "on") {
    return "on";
  }
  if (text === "0" || text === "false" || text === "off") {
    return "off";
  }
  return "inherit";
}

function qualityOverrideLabel(mode) {
  const safeMode = String(mode || "").trim().toLowerCase();
  if (safeMode === "on") return "On";
  if (safeMode === "off") return "Off";
  return "Inherit";
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

function filterAnalyticsUsersRows(rows, query) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) {
    return safeRows.slice();
  }
  return safeRows.filter((row) => String(row && row.user_email || "").trim().toLowerCase().includes(needle));
}

function analyticsUsersSortValue(row, sortBy) {
  if (sortBy === "resolves") return Number(row && row.resolve_count || 0);
  if (sortBy === "lifetime") return Number(row && row.lifetime_bytes || 0);
  if (sortBy === "month") return Number(row && row.month_bytes || 0);
  if (sortBy === "week") return Number(row && row.week_bytes || 0);
  if (sortBy === "day") return Number(row && row.day_bytes || 0);
  if (sortBy === "hour") return Number(row && row.hour_bytes || 0);
  if (sortBy === "last_seen") return Date.parse(String(row && row.last_seen_at || "")) || 0;
  return Number(row && row.month_bytes || 0);
}

function sortAnalyticsUsersRows(rows, sortBy, sortDir) {
  const safeRows = Array.isArray(rows) ? rows.slice() : [];
  const direction = String(sortDir || "desc").trim().toLowerCase() === "asc" ? 1 : -1;
  safeRows.sort((left, right) => {
    const primary = analyticsUsersSortValue(left, sortBy) - analyticsUsersSortValue(right, sortBy);
    if (primary !== 0) {
      return primary * direction;
    }
    return String(left && left.user_email || "").localeCompare(String(right && right.user_email || "")) * direction;
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
  const { db, user } = auth;
  const windowMinutes = deps.sanitizeAnalyticsMinutes(url.searchParams.get("minutes"), deps.DEFAULT_ANALYTICS_WINDOW_MINUTES);
  const tileMapMinutes = deps.sanitizeLiveTileMapMinutes(
    url.searchParams.get("tile_map_minutes"),
    deps.DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
  );
  const planFilter = deps.parseHeavyUserPlanFilter(url.searchParams.get("plan_filter"));
  try {
    let snapshot = await deps.loadAnalyticsSnapshot(env, windowMinutes, planFilter, tileMapMinutes);
    if (!snapshot || deps.isAnalyticsSnapshotStale(snapshot)) {
      snapshot = await deps.collectAnalyticsSnapshot(db, windowMinutes, planFilter, tileMapMinutes, env);
      snapshot = {
        ...snapshot,
        snapshot_minutes: windowMinutes,
        snapshot_plan_filter: planFilter,
        snapshot_tile_map_minutes: tileMapMinutes,
        snapshot_source: "live_rebuild",
      };
      await deps.storeAnalyticsSnapshot(env, windowMinutes, planFilter, tileMapMinutes, snapshot);
    }
    return deps.json(
      {
        ok: true,
        admin_email: String(user.email || ""),
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
        user_id: String(user && user.id || ""),
        user_email: String(user && user.email || ""),
        plan_filter: planFilter,
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
  const { user, tokenSource } = auth;
  const globalUnrestrictedQualityEnabled = await deps.readGlobalUnrestrictedQualityEnabled(auth.db, env);
  let initialSnapshot = null;
  try {
    initialSnapshot = await deps.loadAnalyticsSnapshot(env, 10080, "all", 10);
    if (!initialSnapshot || deps.isAnalyticsSnapshotStale(initialSnapshot)) {
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
        snapshot_plan_filter: "all",
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
        user_id: String(user && user.id || ""),
        user_email: String(user && user.email || ""),
      }),
    );
  }
  const snapshotTopLine = initialSnapshot && initialSnapshot.top_line ? initialSnapshot.top_line : {};
  const snapshotSummary = initialSnapshot && initialSnapshot.summary ? initialSnapshot.summary : {};
  const snapshotActive = initialSnapshot && initialSnapshot.active ? initialSnapshot.active : {};
  const snapshotLiveMap = initialSnapshot && initialSnapshot.live_tile_map ? initialSnapshot.live_tile_map : {};
  const snapshotLiveRows = Array.isArray(snapshotLiveMap && snapshotLiveMap.rows) ? snapshotLiveMap.rows : [];
  const snapshotActiveUsers10m = Array.isArray(initialSnapshot && initialSnapshot.active_users_10m)
    ? initialSnapshot.active_users_10m
    : [];
  const snapshotHeavyUsers = Array.isArray(initialSnapshot && initialSnapshot.heavy_users_30d)
    ? initialSnapshot.heavy_users_30d
    : [];
  const snapshotBillable = initialSnapshot && initialSnapshot.cloudflare_billable_usage
    ? initialSnapshot.cloudflare_billable_usage
    : {};
  const fmtInt = (value) => fmtIntLocal(value, deps.parseNonNegativeInteger);
  const fmtGb = (value) => fmtGbLocal(value, deps.parseNonNegativeInteger, deps.BYTES_PER_GB);
  const fmtFloatLocal = (value, digits = 2) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toFixed(digits) : "0.00";
  };
  const serverActiveUsersRowsHtml = snapshotActiveUsers10m.map((row) => {
    const email = deps.escapeHtml(String(row && row.user_email || ""));
    const tier = analyticsTierLabelFromStatus(row && row.user_status, deps);
    const tierClass = analyticsTierClassFromStatus(row && row.user_status, deps);
    return `<tr><td class="${tierClass}">${email}</td><td class="${tierClass}">${tier}</td><td>${fmtInt(row && row.request_count)}</td><td>${fmtInt(row && row.resolve_count)}</td><td>${fmtGb(row && row.bytes_served)}</td><td>${deps.escapeHtml(String(row && row.last_seen_at || ""))}</td></tr>`;
  }).join("");
  const serverHeavyRowsHtml = snapshotHeavyUsers.slice(0, 20).map((row) => {
    const email = deps.escapeHtml(String(row && row.user_email || ""));
    const tier = analyticsTierLabelFromStatus(row && row.user_status, deps);
    const tierClass = analyticsTierClassFromStatus(row && row.user_status, deps);
    const lastSeen = Number.isFinite(Number(row && row.last_event_unix))
      ? new Date(Number(row.last_event_unix) * 1000).toISOString()
      : "";
    const monthBytes = (row && (row.month_bytes ?? row.bytes_served_30d));
    const monthRequests = (row && (row.request_count_month ?? row.request_count_30d));
    return `<tr><td class="${tierClass}">${email}</td><td class="${tierClass}">${tier}</td><td>${fmtInt(row && row.resolve_count)}</td><td>${fmtGb(monthBytes)}</td><td>${fmtInt(monthRequests)}</td><td>${deps.escapeHtml(lastSeen)}</td></tr>`;
  }).join("");
  const billableAvailable = Boolean(snapshotBillable && snapshotBillable.available);
  const billableSource = deps.escapeHtml(
    String(snapshotBillable && snapshotBillable.source || "cloud_live").replace(/cloudflare/gi, "cloud"),
  );
  const billablePeriodStart = deps.escapeHtml(String(snapshotBillable && snapshotBillable.period_start || ""));
  const billablePeriodEnd = deps.escapeHtml(String(snapshotBillable && snapshotBillable.period_end || ""));
  const billableBucket = deps.escapeHtml(String(snapshotBillable && snapshotBillable.bucket_filter || ""));
  const billableStorageGb = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.storage && snapshotBillable.storage.gb, 3) : "-";
  const billableStorageGbBillable = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.storage && snapshotBillable.storage.billable_gb_rounded, 0) : "-";
  const billableClassAOps = billableAvailable ? fmtInt(snapshotBillable && snapshotBillable.class_a && snapshotBillable.class_a.operations) : "-";
  const billableClassAOpsBillable = billableAvailable ? fmtInt(snapshotBillable && snapshotBillable.class_a && snapshotBillable.class_a.billable_operations) : "-";
  const billableClassBOps = billableAvailable ? fmtInt(snapshotBillable && snapshotBillable.class_b && snapshotBillable.class_b.operations) : "-";
  const billableClassBOpsBillable = billableAvailable ? fmtInt(snapshotBillable && snapshotBillable.class_b && snapshotBillable.class_b.billable_operations) : "-";
  const billableUnknownOps = billableAvailable ? fmtInt(snapshotBillable && snapshotBillable.unknown_operations) : "-";
  const billableCostStorage = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.storage, 2) : "-";
  const billableCostClassA = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.class_a, 2) : "-";
  const billableCostClassB = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.class_b, 2) : "-";
  const billableCostTotal = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.total, 2) : "-";
  const billableStatusText = billableAvailable
    ? (snapshotBillable && snapshotBillable.estimated
      ? `Estimated billable usage from telemetry. Source: ${billableSource}. Period: ${billablePeriodStart} -> ${billablePeriodEnd}`
      : `Cloud live data. Source: ${billableSource}. Bucket: ${billableBucket || "all buckets"}. Period: ${billablePeriodStart} -> ${billablePeriodEnd}`)
    : `Cloud billable usage unavailable. ${deps.escapeHtml(String(snapshotBillable && snapshotBillable.message || snapshotBillable && snapshotBillable.reason || "Not configured."))}`;
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
      const color = analyticsTierColorFromStatus(row && row.user_status, deps);
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
    user,
    tokenSource,
    buildStamp,
    snapshotGeneratedAt,
    fmtIntLocal: fmtInt,
    fmtGbLocal: fmtGb,
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
    globalUnrestrictedQualityEnabled,
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

export async function handleAdminAnalyticsUsersPage(request, env, deps) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return deps.json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user } = auth;
  const query = String(url.searchParams.get("q") || "").trim();
  const sortBy = deps.parseAnalyticsUsersSort(url.searchParams.get("sort"));
  const sortDir = deps.parseAnalyticsUsersSortDirection(url.searchParams.get("dir"));
  let usersSnapshot = await deps.loadAnalyticsUsersSnapshot(env);
  if (!usersSnapshot || deps.isAnalyticsSnapshotStale(usersSnapshot)) {
    usersSnapshot = await deps.buildAnalyticsUsersSnapshot(db, env);
  }
  const rows = sortAnalyticsUsersRows(
    filterAnalyticsUsersRows(usersSnapshot && usersSnapshot.rows, query),
    sortBy,
    sortDir,
  );
  const fmtInt = (value) => fmtIntLocal(value, deps.parseNonNegativeInteger);
  const fmtGb = (value) => fmtGbLocal(value, deps.parseNonNegativeInteger, deps.BYTES_PER_GB);
  const buildSortHref = (key) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    params.set("sort", key);
    const nextDir = (sortBy === key && sortDir === "desc") ? "asc" : "desc";
    params.set("dir", nextDir);
    return `/admin/analytics/users?${params.toString()}`;
  };
  const sortMarker = (key) => (sortBy === key ? (sortDir === "desc" ? " ▼" : " ▲") : "");
  const rowsHtml = (Array.isArray(rows) ? rows : []).map((row) => {
    const userIdRaw = String(row && row.user_id || "");
    const userEmailRaw = String(row && row.user_email || "");
    const planCodeRaw = String(row && row.plan_code || deps.PLAN_CODE_FREE);
    const userEmail = deps.escapeHtml(userEmailRaw);
    const status = String(row && row.user_status || "").trim().toLowerCase();
    const tierClass = analyticsTierClassFromStatus(status || planCodeRaw, deps);
    const tierLabel = analyticsTierLabelFromStatus(status || planCodeRaw, deps);
    const qualityOverrideMode = qualityOverrideModeFromValue(row && row.unrestricted_quality_override);
    let actionButtons = "";
    if (status === "blocked") {
      actionButtons = `<button class="action-btn warn" data-action="unblock" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}" data-plan-code="${encodeURIComponent(planCodeRaw)}">Unblock</button><button class="action-btn" data-action="set-free" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Free</button><button class="action-btn" data-action="set-personal" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Personal</button><button class="action-btn" data-action="set-commercial" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Commercial</button><button class="action-btn" data-action="quality-inherit" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Quality Inherit</button><button class="action-btn" data-action="quality-on" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Quality On</button><button class="action-btn" data-action="quality-off" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Quality Off</button><button class="action-btn danger" data-action="hard-block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Hard Block</button>`;
    } else {
      const freeButton = `<button class="action-btn" data-action="set-free" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Free</button>`;
      const planButton = analyticsTierCodeFromStatus(status || planCodeRaw, deps) === "commercial"
        ? `<button class="action-btn" data-action="set-personal" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Personal</button>`
        : `<button class="action-btn" data-action="set-commercial" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Commercial</button>`;
      actionButtons = `${freeButton}${planButton}<button class="action-btn" data-action="quality-inherit" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Quality Inherit</button><button class="action-btn" data-action="quality-on" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Quality On</button><button class="action-btn" data-action="quality-off" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Quality Off</button><button class="action-btn danger" data-action="block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Block</button><button class="action-btn danger" data-action="hard-block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Hard Block</button>`;
    }
    return `<tr>
      <td class="${tierClass}">${userEmail}</td>
      <td class="${tierClass}">${deps.escapeHtml(tierLabel)}</td>
      <td>${deps.escapeHtml(qualityOverrideLabel(qualityOverrideMode))}</td>
      <td>${fmtInt(row && row.resolve_count)}</td>
      <td>${fmtGb(row && row.lifetime_bytes)}</td>
      <td>${fmtGb(row && row.month_bytes)}</td>
      <td>${fmtGb(row && row.week_bytes)}</td>
      <td>${fmtGb(row && row.day_bytes)}</td>
      <td>${fmtGb(row && row.hour_bytes)}</td>
      <td>${deps.escapeHtml(String(row && row.last_seen_at || ""))}</td>
      <td class="action-wrap">${actionButtons}</td>
    </tr>`;
  }).join("");

  const htmlContent = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planetka Analytics - All users</title>
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
    .action-wrap { white-space: normal; min-width: 520px; }
    .tier-free { color: #ffffff; font-weight: 600; }
    .tier-personal { color: #22c55e; font-weight: 600; }
    .tier-commercial { color: #ef4444; font-weight: 600; }
    .error { color: #fca5a5; }
  </style>
</head>
<body>
  <h1>All users</h1>
  <div class="muted">Signed in as ${deps.escapeHtml(String(user.email || ""))}</div>
  <div class="controls">
    <a href="/admin/analytics" style="color:#93c5fd; text-decoration:none;">Back to analytics</a>
    <a href="/admin/session/logout" style="color:#fca5a5; text-decoration:none;">Sign Out</a>
  </div>
  <form class="controls" method="GET" action="/admin/analytics/users">
    <label for="q">Search user email:</label>
    <input id="q" name="q" type="text" value="${deps.escapeHtml(query)}" placeholder="user@example.com" />
    <input type="hidden" name="sort" value="${deps.escapeHtml(sortBy)}" />
    <input type="hidden" name="dir" value="${deps.escapeHtml(sortDir)}" />
    <button type="submit">Search</button>
    <span class="muted">${fmtInt(Array.isArray(rows) ? rows.length : 0)} users shown</span>
  </form>
  <div id="status" class="muted">Ready</div>
  <table>
    <thead>
      <tr>
        <th>Email</th>
        <th>Plan</th>
        <th>Quality Override</th>
        <th><a href="${buildSortHref("resolves")}">Resolves${sortMarker("resolves")}</a></th>
        <th><a href="${buildSortHref("lifetime")}">Lifetime GB${sortMarker("lifetime")}</a></th>
        <th><a href="${buildSortHref("month")}">Month GB${sortMarker("month")}</a></th>
        <th><a href="${buildSortHref("week")}">Week GB${sortMarker("week")}</a></th>
        <th><a href="${buildSortHref("day")}">Day GB${sortMarker("day")}</a></th>
        <th><a href="${buildSortHref("hour")}">Hour GB${sortMarker("hour")}</a></th>
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
    async function performUserAction(action, userId, userEmail, planCode) {
      const safeAction = String(action || "").trim();
      const safeUserId = String(userId || "").trim();
      const safeUserEmail = String(userEmail || "").trim();
      const safePlanCode = String(planCode || "").trim().toLowerCase();
      const endpointByAction = {
        block: "/admin/users/block",
        unblock: "/admin/users/unblock",
        "set-free": "/admin/users/set-plan",
        "set-personal": "/admin/users/set-plan",
        "set-commercial": "/admin/users/set-plan",
        "quality-inherit": "/admin/users/set-unrestricted-quality",
        "quality-on": "/admin/users/set-unrestricted-quality",
        "quality-off": "/admin/users/set-unrestricted-quality",
        "hard-block": "/admin/users/hard-block",
      };
      const confirmation = {
        block: "Block this user account now?",
        unblock: "Unblock this user account now?",
        "set-free": "Set this account to Free?",
        "set-personal": "Set this account to Personal?",
        "set-commercial": "Set this account to Commercial?",
        "quality-inherit": "Return this account to the global unrestricted-quality setting?",
        "quality-on": "Force unrestricted quality ON for this account?",
        "quality-off": "Force unrestricted quality OFF for this account?",
        "hard-block": "Hard block this user and block same-computer attempts?",
      };
      const endpoint = endpointByAction[safeAction];
      if (!endpoint) return;
      if (!window.confirm(confirmation[safeAction] || "Confirm action?")) return;
      const payload = { email: safeUserEmail };
      if (safeUserId) payload.user_id = safeUserId;
      if (safeAction === "unblock") {
        payload.plan_code = (!safePlanCode || safePlanCode === "blocked") ? "personal" : safePlanCode;
      }
      if (safeAction === "set-free") payload.plan_code = "free";
      if (safeAction === "set-personal") payload.plan_code = "personal";
      if (safeAction === "set-commercial") payload.plan_code = "commercial";
      if (safeAction === "quality-inherit") payload.mode = "inherit";
      if (safeAction === "quality-on") payload.mode = "on";
      if (safeAction === "quality-off") payload.mode = "off";
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
        statusEl.textContent = "Action applied: " + safeAction + " (" + safeUserEmail + ")";
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
      const userId = decodeDataValue(button.getAttribute("data-user-id"));
      const userEmail = decodeDataValue(button.getAttribute("data-user-email"));
      const planCode = decodeDataValue(button.getAttribute("data-plan-code"));
      performUserAction(action, userId, userEmail, planCode);
    });
  </script>
</body>
</html>`;
  return deps.html(htmlContent, 200, env);
}
