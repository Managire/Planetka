import { buildAdminAnalyticsPageHtml } from "../admin_analytics_page.js";

function fmtIntLocal(value, parseNonNegativeInteger) {
  return Number(parseNonNegativeInteger(value, 0)).toLocaleString();
}

function fmtGbLocal(value, parseNonNegativeInteger, bytesPerGb) {
  return (Number(parseNonNegativeInteger(value, 0)) / bytesPerGb).toFixed(3);
}

function fmtMbLocal(value, parseNonNegativeInteger) {
  return (Number(parseNonNegativeInteger(value, 0)) / (1024 * 1024)).toFixed(2);
}

const ANALYTICS_TILE_COLOR = "#60a5fa";

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
  if (sortBy === "paid_eur") return Number(row && row.paid_eur_lifetime || 0);
  if (sortBy === "paid_resolves") return Number(row && row.paid_full_resolve_count || 0);
  if (sortBy === "paid_tiles") return Number(row && row.unlocked_tile_count || 0);
  if (sortBy === "data_downloaded") return Number(row && row.licenced_downloaded_bytes || 0);
  if (sortBy === "preview_lifetime") return Number(row && row.preview_lifetime_bytes || 0);
  if (sortBy === "last_seen") return Date.parse(String(row && row.last_seen_at || "")) || 0;
  return Number(row && row.paid_eur_lifetime || 0);
}

function fmtEurLocal(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `€${numeric.toFixed(2)}` : "€0.00";
}

function parseMetadataJson(value) {
  try {
    return JSON.parse(String(value || "{}"));
  } catch (_error) {
    return {};
  }
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
  const planFilter = "all";
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
        plan_filter: "all",
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

export async function handleAdminSetPricingSettings(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  if (String(request.method || "GET").trim().toUpperCase() !== "POST") {
    return deps.json({ ok: false, error: "method_not_allowed" }, 405, env);
  }
  let payload = {};
  try {
    const contentType = String(request.headers.get("Content-Type") || "").toLowerCase();
    if (contentType.includes("application/json")) {
      payload = await request.json();
    } else {
      const form = await request.formData();
      payload = Object.fromEntries(form.entries());
    }
  } catch (_error) {
    payload = {};
  }
  try {
    const settings = await deps.setRuntimePricingSettings(
      auth.db,
      {
        full_quality_price_coefficient: payload.full_quality_price_coefficient,
        region_pack_discount_min_percent: payload.region_pack_discount_min_percent,
        region_pack_discount_max_percent: payload.region_pack_discount_max_percent,
      },
      auth.user && auth.user.id || "",
      deps,
    );
    return deps.json({ ok: true, pricing_settings: settings }, 200, env);
  } catch (error) {
    return deps.json(
      {
        ok: false,
        error: "pricing_settings_update_failed",
        message: String(error && error.message || "Pricing settings could not be saved."),
      },
      500,
      env,
    );
  }
}

export async function handleAdminSetProductDiscount(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  if (String(request.method || "GET").trim().toUpperCase() !== "POST") {
    return deps.json({ ok: false, error: "method_not_allowed" }, 405, env);
  }
  let payload = {};
  try {
    const contentType = String(request.headers.get("Content-Type") || "").toLowerCase();
    if (contentType.includes("application/json")) {
      payload = await request.json();
    } else {
      const form = await request.formData();
      payload = Object.fromEntries(form.entries());
    }
  } catch (_error) {
    payload = {};
  }
  const regionPackId = String(payload.region_pack_id || payload.product_id || "").trim();
  const resetRequested = payload.reset === true || payload.reset === 1 || String(payload.reset || "").trim().toLowerCase() === "true";
  const rawDiscount = resetRequested ? null : payload.discount_percent;
  const discountPercent = rawDiscount === null || rawDiscount === undefined || String(rawDiscount).trim() === ""
    ? null
    : rawDiscount;
  try {
    const settings = await deps.setRegionProductDiscountOverride(
      auth.db,
      env,
      regionPackId,
      discountPercent,
      auth.user && auth.user.id || "",
      deps,
    );
    return deps.json({ ok: true, pricing_settings: settings }, 200, env);
  } catch (error) {
    return deps.json(
      {
        ok: false,
        error: "product_discount_update_failed",
        message: String(error && error.message || "Product discount could not be saved."),
      },
      400,
      env,
    );
  }
}

export async function handleAdminAnalyticsProductsPage(request, env, deps) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return deps.json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { user } = auth;
  const fmtEur = (value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? `€${numeric.toFixed(2)}` : "€0.00";
  };
  const fmtPercent = (value) => `${Math.max(0, Math.min(100, Math.round(Number(value || 0) || 0)))}%`;
  const fmtInt = (value) => Number(deps.parseNonNegativeInteger(value, 0)).toLocaleString();
  const productData = await deps.listRegionProductPricingRows(env, deps);
  const rows = Array.isArray(productData && productData.rows) ? productData.rows : [];
  const settings = productData && productData.pricing_settings || {};
  const coefficient = Number.isFinite(Number(settings.full_quality_price_coefficient))
    ? Number(settings.full_quality_price_coefficient).toFixed(2)
    : "1.00";
  const minDiscount = Number.isFinite(Number(settings.region_pack_discount_min_percent))
    ? String(Math.round(Number(settings.region_pack_discount_min_percent)))
    : "0";
  const maxDiscount = Number.isFinite(Number(settings.region_pack_discount_max_percent))
    ? String(Math.round(Number(settings.region_pack_discount_max_percent)))
    : "75";
  const rowsHtml = rows.map((row) => {
    const id = String(row && row.id || "");
    const name = String(row && row.name || "");
    const type = String(row && row.type || "");
    const hasOverride = Boolean(row && row.has_override);
    const overrideValue = hasOverride ? String(Math.round(Number(row.override_discount_percent || 0))) : "";
    const overrideLabel = hasOverride ? fmtPercent(row.override_discount_percent) : "default";
    const finalClass = Number(row && row.final_price_eur || 0) <= 0 ? " free-price" : "";
    return `<tr data-pack-id="${deps.escapeHtml(id)}" data-name="${deps.escapeHtml(name.toLowerCase())}" data-type="${deps.escapeHtml(type.toLowerCase())}"${hasOverride ? ` class="override-row"` : ""}>
      <td><strong>${deps.escapeHtml(name)}</strong><br><span class="muted">${deps.escapeHtml(id)}</span></td>
      <td>${deps.escapeHtml(type || "-")}</td>
      <td>${fmtInt(row && row.tile_count)}<br><span class="muted">${fmtInt(row && row.paid_tile_count)} paid / ${fmtInt(row && row.free_tile_count)} free</span></td>
      <td>${deps.escapeHtml(fmtEur(row && row.gross_base_eur))}</td>
      <td>${deps.escapeHtml(fmtEur(row && row.full_price_eur))}</td>
      <td>${deps.escapeHtml(fmtPercent(row && row.default_discount_percent))}</td>
      <td>${deps.escapeHtml(overrideLabel)}</td>
      <td>${deps.escapeHtml(fmtEur(row && row.discount_eur))}</td>
      <td class="price${finalClass}">${deps.escapeHtml(fmtEur(row && row.final_price_eur))}</td>
      <td>
        <form class="product-discount-form" data-region-pack-id="${deps.escapeHtml(id)}">
          <input name="discount_percent" type="number" min="0" max="100" step="1" value="${deps.escapeHtml(overrideValue)}" placeholder="default" />
          <button type="submit">Save</button>
          <button type="button" class="reset-discount">Reset</button>
        </form>
      </td>
    </tr>`;
  }).join("");
  const htmlContent = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planetka Analytics - Product Pricing</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 20px; background: #0b1020; color: #e5e7eb; }
    h1 { margin: 0 0 8px; font-size: 24px; }
    .muted { color: #9ca3af; font-size: 13px; }
    .controls { display:flex; gap:10px; align-items:center; flex-wrap: wrap; margin: 8px 0 16px; }
    .card { background:#111827; border:1px solid #1f2937; border-radius:10px; padding:12px; margin: 12px 0; }
    input, button, select { background:#111827; color:#e5e7eb; border:1px solid #374151; border-radius:8px; padding:7px 10px; }
    input[type=number] { width: 92px; }
    table { width:100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }
    th, td { border-bottom: 1px solid #1f2937; padding: 8px 6px; text-align:left; vertical-align: top; }
    th { color:#93c5fd; font-weight:600; white-space: nowrap; position: sticky; top: 0; background: #0b1020; z-index: 1; }
    .price { font-weight: 700; color: #f4d28d; white-space: nowrap; }
    .free-price { color: #86efac; }
    .override-row td { background: rgba(217, 164, 65, 0.08); }
    .product-discount-form { display:flex; gap:6px; align-items:center; flex-wrap: nowrap; }
    .error { color:#fca5a5; }
  </style>
</head>
<body>
  <h1>Product Pricing</h1>
  <div class="muted">Signed in as ${deps.escapeHtml(String(user.email || ""))}. Catalog: ${deps.escapeHtml(String(productData && productData.catalog_version || ""))}</div>
  <div class="controls">
    <a href="/admin/analytics" style="color:#93c5fd; text-decoration:none;">Back to analytics</a>
    <a href="/admin/analytics/users" style="color:#93c5fd; text-decoration:none;">All users</a>
    <a href="/admin/session/logout" style="color:#fca5a5; text-decoration:none;">Sign Out</a>
  </div>
  <section class="card">
    <div class="controls" style="margin-bottom:6px;">
      <span>Current coefficient: <strong>${deps.escapeHtml(coefficient)}</strong></span>
      <span>Default pack discount range: <strong>${deps.escapeHtml(minDiscount)}%-${deps.escapeHtml(maxDiscount)}%</strong></span>
      <span id="status" class="muted">Product overrides are applied live to Blender, web pages, and checkout.</span>
    </div>
    <div class="controls">
      <label for="filter">Filter products:</label>
      <input id="filter" type="text" placeholder="country, region, id, type" style="min-width:280px;" />
      <label><input id="overridesOnly" type="checkbox" /> Overrides only</label>
      <span class="muted" id="visibleCount">${fmtInt(rows.length)} products</span>
    </div>
  </section>
  <table id="productsTable">
    <thead>
      <tr>
        <th>Product</th>
        <th>Type</th>
        <th>Tiles</th>
        <th>Gross Base<br><span class="muted">coefficient 1.0</span></th>
        <th>Full Price<br><span class="muted">current coefficient</span></th>
        <th>Default Discount</th>
        <th>Override</th>
        <th>Discount EUR</th>
        <th>Final Price</th>
        <th>Set Product Discount</th>
      </tr>
    </thead>
    <tbody>${rowsHtml}</tbody>
  </table>
  <script>
    const statusEl = document.getElementById("status");
    const filterEl = document.getElementById("filter");
    const overridesOnlyEl = document.getElementById("overridesOnly");
    const visibleCountEl = document.getElementById("visibleCount");
    const table = document.getElementById("productsTable");
    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.className = isError ? "error" : "muted";
    }
    function applyFilter() {
      const needle = String(filterEl.value || "").trim().toLowerCase();
      const overridesOnly = Boolean(overridesOnlyEl.checked);
      let visible = 0;
      for (const row of table.querySelectorAll("tbody tr")) {
        const text = [row.getAttribute("data-pack-id"), row.getAttribute("data-name"), row.getAttribute("data-type")].join(" ");
        const matchesText = !needle || text.includes(needle);
        const matchesOverride = !overridesOnly || row.classList.contains("override-row");
        const show = matchesText && matchesOverride;
        row.style.display = show ? "" : "none";
        if (show) visible += 1;
      }
      visibleCountEl.textContent = visible.toLocaleString() + " products";
    }
    async function saveProductDiscount(regionPackId, discountPercent) {
      setStatus("Saving product discount...");
      const res = await fetch("/admin/settings/product-discount", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ region_pack_id: regionPackId, discount_percent: discountPercent }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error((data && (data.message || data.error)) || ("HTTP " + res.status));
      }
      setStatus("Saved. Reloading prices...");
      window.location.reload();
    }
    document.addEventListener("submit", (event) => {
      const form = event.target && event.target.closest ? event.target.closest(".product-discount-form") : null;
      if (!form) return;
      event.preventDefault();
      const regionPackId = form.getAttribute("data-region-pack-id") || "";
      const input = form.querySelector("input[name=discount_percent]");
      const value = input ? String(input.value || "").trim() : "";
      saveProductDiscount(regionPackId, value).catch((error) => setStatus("Save failed: " + String(error && error.message || error), true));
    });
    document.addEventListener("click", (event) => {
      const button = event.target && event.target.closest ? event.target.closest(".reset-discount") : null;
      if (!button) return;
      const form = button.closest(".product-discount-form");
      const regionPackId = form ? form.getAttribute("data-region-pack-id") || "" : "";
      saveProductDiscount(regionPackId, null).catch((error) => setStatus("Reset failed: " + String(error && error.message || error), true));
    });
    filterEl.addEventListener("input", applyFilter);
    overridesOnlyEl.addEventListener("change", applyFilter);
  </script>
</body>
</html>`;
  return deps.html(htmlContent, 200, env);
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
    return `<tr><td>${email}</td><td>${fmtInt(row && row.request_count)}</td><td>${fmtInt(row && row.resolve_count)}</td><td>${fmtGb(row && row.bytes_served)}</td><td>${deps.escapeHtml(String(row && row.last_seen_at || ""))}</td></tr>`;
  }).join("");
  const serverHeavyRowsHtml = snapshotHeavyUsers.slice(0, 20).map((row) => {
    const email = deps.escapeHtml(String(row && row.user_email || ""));
    const lastSeen = Number.isFinite(Number(row && row.last_event_unix))
      ? new Date(Number(row.last_event_unix) * 1000).toISOString()
      : "";
    const lifetimeBytes = row && (row.lifetime_bytes ?? row.bytes_served_lifetime ?? row.month_bytes ?? row.bytes_served_30d);
    return `<tr><td>${email}</td><td>${fmtInt(row && row.resolve_count)}</td><td>${fmtGb(lifetimeBytes)}</td><td>${deps.escapeHtml(lastSeen)}</td></tr>`;
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
      const color = ANALYTICS_TILE_COLOR;
      const rawD = Number(parsed.d || 1);
      const alpha = Math.max(0.05, Math.min(1, 1 / Math.max(1, rawD)));
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" fill="${color}" fill-opacity="${alpha.toFixed(3)}" stroke="${color}" stroke-width="0.5" stroke-opacity="0.95"></rect>`;
    })
    .filter(Boolean)
    .join("");
  const snapshotGeneratedAt = deps.escapeHtml(String(initialSnapshot && initialSnapshot.generated_at || deps.nowIso()));
  const buildStamp = deps.nowIso();
  const pricingSettings = deps.getRuntimePricingSettings
    ? await deps.getRuntimePricingSettings(env, deps, { force: false })
    : {};
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
    pricingSettings,
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

export async function handleAdminAnalyticsUserPage(request, env, deps) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return deps.json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await deps.ensureCreditTables(db);
  const requestedUserId = String(url.searchParams.get("user_id") || "").trim();
  const requestedEmail = String(url.searchParams.get("email") || "").trim().toLowerCase();
  const targetUser = requestedUserId
    ? await deps.findUserById(db, requestedUserId)
    : (requestedEmail ? await deps.findUserByEmail(db, requestedEmail) : null);
  if (!targetUser || !targetUser.id) {
    return deps.html(
      `<!doctype html><title>Planetka User History</title><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#0b1020;color:#e5e7eb;margin:20px"><h1>User not found</h1><p><a style="color:#93c5fd" href="/admin/analytics/users">Back to users</a></p></body>`,
      404,
      env,
    );
  }
  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = String(targetUser.email || "").trim().toLowerCase();
  const account = await deps.dbGet(
    db,
    `SELECT * FROM user_credit_accounts WHERE user_id = ? LIMIT 1`,
    [targetUserId],
  );
  const purchases = await deps.dbAll(
    db,
    `
      SELECT *
      FROM purchase_history
      WHERE user_id = ?
      ORDER BY created_at DESC
      LIMIT 250
    `,
    [targetUserId],
  );
  const purchaseIds = (purchases || []).map((row) => String(row && row.id || "").trim()).filter(Boolean);
  const tileRows = purchaseIds.length
    ? await deps.dbAll(
      db,
      `
        SELECT *
        FROM purchase_history_tiles
        WHERE purchase_id IN (${purchaseIds.map(() => "?").join(",")})
        ORDER BY purchase_id ASC, tile_key ASC
      `,
      purchaseIds,
    )
    : [];
  const tilesByPurchase = new Map();
  for (const tile of tileRows || []) {
    const purchaseId = String(tile && tile.purchase_id || "").trim();
    if (!tilesByPurchase.has(purchaseId)) {
      tilesByPurchase.set(purchaseId, []);
    }
    tilesByPurchase.get(purchaseId).push(tile);
  }
  const licencedSummary = await deps.dbGet(
    db,
    `
      SELECT
        COUNT(*) AS tile_count,
        COALESCE(ROUND(SUM(credits_spent) * 100.0) / 100.0, 0) AS nominal_eur
      FROM user_tile_entitlements
      WHERE user_id = ?
    `,
    [targetUserId],
  );
  const paidSummary = await deps.dbGet(
    db,
    `
      SELECT COALESCE(ROUND(SUM(amount_paid_eur) * 100.0) / 100.0, 0) AS paid_eur
      FROM purchase_history
      WHERE user_id = ?
    `,
    [targetUserId],
  );
  const purchaseRowsHtml = (purchases || []).map((row) => {
    const purchaseId = String(row && row.id || "");
    const metadata = parseMetadataJson(row && row.metadata_json);
    const tiles = tilesByPurchase.get(purchaseId) || [];
    const packName = String(row && row.region_pack_name || row && row.region_pack_id || "");
    const purchaseType = String(row && row.purchase_type || "");
    const typeLabel = purchaseType === "region_pack"
      ? `Region Pack${packName ? `: ${deps.escapeHtml(packName)}` : ""}`
      : (purchaseType === "scene_tiles"
        ? "Scene Full Quality"
        : "Retired Product");
    const tileDetails = tiles.length
      ? `<details><summary>${tiles.length} purchased tile(s)</summary><table class="inner"><thead><tr><th>Tile</th><th>Status</th><th>Price</th><th>Gross</th><th>Land km²</th></tr></thead><tbody>${tiles.map((tile) => `<tr><td>${deps.escapeHtml(String(tile && tile.tile_key || ""))}</td><td>${deps.escapeHtml(String(tile && tile.tile_status || ""))}</td><td>${deps.escapeHtml(fmtEurLocal(tile && tile.price_eur))}</td><td>${deps.escapeHtml(fmtEurLocal(tile && tile.gross_price_eur))}</td><td>${Number(tile && tile.billable_land_km2 || 0).toFixed(2)}</td></tr>`).join("")}</tbody></table></details>`
      : "";
    const metadataLine = purchaseType === "region_pack"
      ? `Catalog: ${deps.escapeHtml(String(row && row.catalog_version || ""))} · Discount: ${Number(row && row.discount_percent || 0)}% (${deps.escapeHtml(fmtEurLocal(row && row.discount_eur))})`
      : (metadata && metadata.purchased_tile_keys
        ? `Tile keys: ${deps.escapeHtml((metadata.purchased_tile_keys || []).join(", "))}`
        : "");
    return `<tr>
      <td>${deps.escapeHtml(String(row && row.created_at || ""))}</td>
      <td>${typeLabel}</td>
      <td>${deps.escapeHtml(fmtEurLocal(row && row.amount_paid_eur))}</td>
      <td>${deps.escapeHtml(fmtEurLocal(row && row.gross_eur))}</td>
      <td>${Number(row && row.tile_count_new || 0).toLocaleString()} new / ${Number(row && row.tile_count_total || 0).toLocaleString()} total</td>
      <td>${deps.escapeHtml(String(row && row.stripe_session_id || ""))}</td>
      <td>${metadataLine}${tileDetails}</td>
    </tr>`;
  }).join("");
  const htmlContent = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planetka Analytics - User Purchase History</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 20px; background: #0b1020; color: #e5e7eb; }
    h1 { margin: 0 0 8px; font-size: 24px; }
    .muted { color: #9ca3af; font-size: 13px; }
    .cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap:10px; margin:16px 0; }
    .card { background:#111827; border:1px solid #1f2937; border-radius:10px; padding:12px; }
    .card b { display:block; font-size:20px; margin-top:4px; }
    a { color:#93c5fd; text-decoration:none; }
    table { width:100%; border-collapse: collapse; margin: 14px 0 16px; font-size: 13px; }
    th, td { border-bottom: 1px solid #1f2937; padding: 8px 6px; text-align:left; vertical-align: top; }
    th { color:#93c5fd; font-weight:600; white-space: nowrap; }
    .inner { margin: 8px 0 0; font-size:12px; }
    summary { cursor:pointer; color:#bfdbfe; margin-top:6px; }
    code { color:#fef3c7; }
  </style>
</head>
<body>
  <h1>${deps.escapeHtml(targetEmail || targetUserId)}</h1>
  <div class="muted">Signed in as ${deps.escapeHtml(String(adminUser.email || ""))}</div>
  <p><a href="/admin/analytics/users">Back to users</a> · <a href="/admin/analytics">Back to analytics</a></p>
  <section class="cards">
    <div class="card"><span>Paid EUR</span><b>${deps.escapeHtml(fmtEurLocal(paidSummary && paidSummary.paid_eur))}</b></div>
    <div class="card"><span>Licenced Tiles</span><b>${Number(licencedSummary && licencedSummary.tile_count || 0).toLocaleString()}</b></div>
    <div class="card"><span>Nominal Tile Value</span><b>${deps.escapeHtml(fmtEurLocal(licencedSummary && licencedSummary.nominal_eur))}</b></div>
  </section>
  <h2>Purchase History</h2>
  <table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Transaction</th>
        <th>Paid</th>
        <th>Full Price</th>
        <th>Tiles</th>
        <th>Stripe Session</th>
        <th>Details</th>
      </tr>
    </thead>
    <tbody>${purchaseRowsHtml || `<tr><td colspan="7" class="muted">No purchase history recorded yet.</td></tr>`}</tbody>
  </table>
</body>
</html>`;
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
  const fmtMb = (value) => fmtMbLocal(value, deps.parseNonNegativeInteger);
  const fmtEur = (value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? `€${numeric.toFixed(2)}` : "€0.00";
  };
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
    const userEmail = deps.escapeHtml(userEmailRaw);
    const userHref = userIdRaw
      ? `/admin/analytics/user?user_id=${encodeURIComponent(userIdRaw)}`
      : `/admin/analytics/user?email=${encodeURIComponent(userEmailRaw)}`;
    const status = String(row && row.user_status || "").trim().toLowerCase();
    const previewHeld = Boolean(String(row && row.preview_fair_usage_hold_at || "").trim());
    const previewHoldButton = previewHeld
      ? `<button class="action-btn warn" data-action="release-preview-hold" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Release Preview Hold</button>`
      : `<button class="action-btn warn" data-action="set-preview-hold" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Pause Preview</button>`;
    let actionButtons = "";
    if (status === "blocked") {
      actionButtons = `${previewHoldButton}<button class="action-btn warn" data-action="unblock" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Unblock</button><button class="action-btn danger" data-action="hard-block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Hard Block</button>`;
    } else {
      actionButtons = `${previewHoldButton}<button class="action-btn danger" data-action="block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Block</button><button class="action-btn danger" data-action="hard-block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Hard Block</button>`;
    }
    return `<tr${previewHeld ? ` class="preview-held"` : ""}>
      <td><a href="${deps.escapeHtml(userHref)}">${userEmail}</a></td>
      <td>${deps.escapeHtml(fmtEur(row && row.paid_eur_lifetime))}</td>
      <td>${fmtInt(row && row.paid_full_resolve_count)}</td>
      <td>${fmtInt(row && row.unlocked_tile_count)}</td>
      <td>${fmtMb(row && row.licenced_downloaded_bytes)} MB<br><span class="muted">${fmtInt(row && row.licenced_downloaded_tiles)} tiles</span></td>
      <td>${fmtGb(row && row.preview_lifetime_bytes)}</td>
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
    .action-wrap { white-space: normal; min-width: 380px; }
    .preview-held td { background: rgba(154, 52, 18, 0.12); }
    .error { color: #fca5a5; }
  </style>
</head>
<body>
  <h1>All users</h1>
  <div class="muted">Signed in as ${deps.escapeHtml(String(user.email || ""))}</div>
  <div class="controls">
    <a href="/admin/analytics" style="color:#93c5fd; text-decoration:none;">Back to analytics</a>
    <a href="/admin/analytics/products" style="color:#93c5fd; text-decoration:none;">Product pricing</a>
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
        <th><a href="${buildSortHref("paid_eur")}">Paid EUR${sortMarker("paid_eur")}</a></th>
        <th><a href="${buildSortHref("paid_resolves")}">Paid Resolves${sortMarker("paid_resolves")}</a></th>
        <th><a href="${buildSortHref("paid_tiles")}">Paid Tiles${sortMarker("paid_tiles")}</a></th>
        <th><a href="${buildSortHref("data_downloaded")}">Data Downloaded${sortMarker("data_downloaded")}</a></th>
        <th><a href="${buildSortHref("preview_lifetime")}">Preview GB Lifetime${sortMarker("preview_lifetime")}</a></th>
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
      void planCode;
      const endpointByAction = {
        block: "/admin/users/block",
        unblock: "/admin/users/unblock",
        "hard-block": "/admin/users/hard-block",
        "set-preview-hold": "/admin/users/set-preview-hold",
        "release-preview-hold": "/admin/users/release-preview-hold",
      };
      const confirmation = {
        block: "Block this user account now?",
        unblock: "Unblock this user account now?",
        "hard-block": "Hard block this user and block same-computer attempts?",
        "set-preview-hold": "Pause Preview streaming for this user? Full Quality remains available.",
        "release-preview-hold": "Release this user's Preview fair-usage hold?",
      };
      const endpoint = endpointByAction[safeAction];
      if (!endpoint) return;
      if (!window.confirm(confirmation[safeAction] || "Confirm action?")) return;
      const payload = { email: safeUserEmail };
      if (safeUserId) payload.user_id = safeUserId;
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
