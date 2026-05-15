#!/usr/bin/env node
/*
 * Planetka quote read-only health gate.
 *
 * Purpose:
 * - prove public catalog, product-page, and checkout routes do not run the
 *   heavy data-pack pricing calculator
 * - verify World and Asia requests enqueue materialized quote jobs when quote
 *   rows are missing instead of calculating inline
 *
 * This is intentionally hermetic. It does not call live Cloudflare services.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  handleCreditCheckout,
  handleCreditRegionPackCatalog,
  handleCreditRegionPackCatalogPage,
  handleCreditRegionPackCheckoutFromToken,
  handleCreditRegionPackMap,
} from "../cloudflare-api/src/worker/credit_routes.js";
import {
  GENERATED_REGION_PACK_CATALOG_VERSION,
} from "../cloudflare-api/src/worker/region_packs.products.generated.js";

const __filename = fileURLToPath(import.meta.url);
const ROOT = path.resolve(path.dirname(__filename), "..");
const CREDIT_ROUTES = path.join(ROOT, "cloudflare-api/src/worker/credit_routes.js");
const REPORT_PATH = path.join("/tmp", "planetka_quote_read_only_health_gate_report.json");

const FORBIDDEN_SQL_PATTERNS = [
  /region_pack_tile_entries/i,
  /user_tile_entitlements/i,
  /purchase_history_tiles/i,
  /pricing_quotes/i,
];
const DEFAULT_PRICING_VERSION = [
  "d1-complete-map-state-v2",
  "5.000000",
  "0",
  "75",
  "0.400000:1.000000|0.200000:0.833333|0.100000:0.666667|0.050000:0.500000|0.025000:0.333333|0.012500:0.166667|0.000000:0.000000",
  "1.50",
  "9.00",
  "",
].join("|");
const DEFAULT_ENTITLEMENT_VERSION = "beta_full_world_access|quote-health@planetka.local|0|2026-05-15T00:00:00.000Z|";
const REGION_PACK_CATALOG_VERSION = GENERATED_REGION_PACK_CATALOG_VERSION || "gadm_regions_v8";

function assert(condition, message) {
  if (!condition) {
    throw new Error(String(message || "assertion failed"));
  }
}

function compactSql(sql) {
  return String(sql || "").replace(/\s+/g, " ").trim();
}

function staticHeavyQuoteCallGuard() {
  const source = fs.readFileSync(CREDIT_ROUTES, "utf8");
  const lines = source.split(/\r?\n/);
  const allowed = [];
  const violations = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.includes("createRegionPackQuote(")) {
      continue;
    }
    const lineNumber = index + 1;
    const previousWindow = lines.slice(Math.max(0, index - 80), index + 6).join("\n");
    if (line.includes("async function createRegionPackQuote")) {
      allowed.push({ line: lineNumber, reason: "definition" });
      continue;
    }
    if (
      line.includes("const quote = await createRegionPackQuote")
      && previousWindow.includes("async function processSingleUserProductQuoteJob")
    ) {
      allowed.push({ line: lineNumber, reason: "background_quote_job_processor" });
      continue;
    }
    violations.push({ line: lineNumber, source: line.trim() });
  }
  return { ok: violations.length === 0, allowed, violations };
}

class GuardedDb {
  constructor(name, options = {}) {
    this.name = String(name || "case");
    this.userId = String(options.userId || "quote_health_user");
    this.email = String(options.email || "quote-health@planetka.local");
    this.token = String(options.token || `${this.name}_token`);
    this.tokenRegionPackId = String(options.tokenRegionPackId || "world");
    this.queries = [];
    this.jobs = [];
    this.quoteRows = new Map();
    for (const row of Array.isArray(options.quoteRows) ? options.quoteRows : []) {
      const productId = String(row && row.product_id || "").trim().toLowerCase();
      if (productId) {
        this.quoteRows.set(productId, { ...row });
      }
    }
  }

  check(kind, sql) {
    const normalized = compactSql(sql);
    this.queries.push({ kind, sql: normalized });
    for (const pattern of FORBIDDEN_SQL_PATTERNS) {
      if (pattern.test(normalized)) {
        throw new Error(`${this.name}: public route touched forbidden heavy pricing SQL: ${normalized}`);
      }
    }
  }

  dbGet(sql, bindings = []) {
    this.check("get", sql);
    const normalized = compactSql(sql).toLowerCase();
    if (normalized.includes("from region_pack_detail_tokens")) {
      return {
        token: this.token,
        user_id: this.userId,
        region_pack_id: this.tokenRegionPackId,
        expires_at: "2099-01-01T00:00:00.000Z",
      };
    }
    if (normalized.includes("from scene_full_quality_detail_tokens")) {
      return null;
    }
    if (normalized.includes("from user_credit_accounts")) {
      return {
        user_id: this.userId,
        user_email: this.email,
        email: this.email,
        account_type: "standard",
        pricing_version: 0,
        updated_at: "2026-05-15T00:00:00.000Z",
        world_full_quality_unlocked_at: "",
      };
    }
    if (normalized.includes("select id, email from users")) {
      return { id: this.userId, email: this.email };
    }
    if (normalized.includes("from users where id")) {
      return { id: this.userId, email: this.email };
    }
    void bindings;
    return null;
  }

  dbAll(sql, bindings = []) {
    this.check("all", sql);
    const normalized = compactSql(sql).toLowerCase();
    if (normalized.includes("from app_settings")) {
      return [];
    }
    if (normalized.includes("from user_product_quotes")) {
      const ids = Array.isArray(bindings) ? bindings.slice(2).map((value) => String(value || "").trim().toLowerCase()) : [];
      return ids.map((id) => this.quoteRows.get(id)).filter(Boolean);
    }
    return [];
  }

  dbRun(sql, bindings = []) {
    this.check("run", sql);
    const normalized = compactSql(sql).toLowerCase();
    if (normalized.includes("insert or ignore into user_product_quote_jobs")) {
      this.jobs.push({
        user_id: String(bindings[2] || ""),
        product_id: String(bindings[3] || ""),
        job_round: Number.parseInt(bindings[8] || 0, 10) || 0,
        priority: Number.parseInt(bindings[9] || 0, 10) || 0,
        trigger_type: String(bindings[10] || ""),
        stale_reason: String(bindings[12] || ""),
      });
      return { meta: { changes: 1 } };
    }
    if (normalized.includes("update user_product_quote_jobs")) {
      return { meta: { changes: 0 } };
    }
    return { meta: { changes: 0 } };
  }
}

function makeDeps(state) {
  return {
    requireDb: () => state,
    ensureCreditTables: async () => {},
    dbGet: async (_db, sql, bindings = []) => state.dbGet(sql, bindings),
    dbAll: async (_db, sql, bindings = []) => state.dbAll(sql, bindings),
    dbRun: async (_db, sql, bindings = []) => state.dbRun(sql, bindings),
    dbMetaChanges: (result) => Math.max(0, Number.parseInt(result && result.meta && result.meta.changes || 0, 10) || 0),
    json: (payload, status = 200) => new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    }),
    parseJson: async (request) => request.json(),
    requireAuthenticatedUserContext: async () => ({ user: { id: state.userId, email: state.email } }),
    normalizeEmail: (value) => String(value || "").trim().toLowerCase(),
    nowIso: () => "2026-05-15T12:00:00.000Z",
    randomToken: (length = 16) => "h".repeat(Math.max(1, Number.parseInt(length, 10) || 16)),
  };
}

function makeEnv(state) {
  return { DB: state };
}

async function responseJson(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (_error) {
    return { __raw: text };
  }
}

function assertNoForbiddenQueries(state) {
  const forbidden = state.queries.filter((entry) => FORBIDDEN_SQL_PATTERNS.some((pattern) => pattern.test(entry.sql)));
  assert(!forbidden.length, `${state.name}: forbidden heavy SQL was executed: ${JSON.stringify(forbidden, null, 2)}`);
}

function readyQuoteRow(productId, options = {}) {
  const finalPriceCents = Number.parseInt(options.finalPriceCents ?? 12345, 10) || 0;
  const fullPriceCents = Number.parseInt(options.fullPriceCents ?? finalPriceCents, 10) || finalPriceCents;
  const discountCents = Math.max(0, fullPriceCents - finalPriceCents);
  const summary = {
    new_tiles: 1,
    charged_tiles: 1,
    total_tiles: 1,
    already_licenced_tiles: 0,
    partial_licence_tiles: 0,
    free_tiles: 0,
    full_price_eur: fullPriceCents / 100,
    full_price_cents: fullPriceCents,
    already_licenced_deduction_eur: 0,
    already_licenced_deduction_cents: 0,
    already_licenced_saving_eur: 0,
    partial_licence_credit_eur: 0,
    partial_licence_credit_cents: 0,
    discount_percent: discountCents > 0 ? 10 : 0,
    discount_eur: discountCents / 100,
    discount_cents: discountCents,
    price_eur: finalPriceCents / 100,
    price_cents: finalPriceCents,
  };
  return {
    user_id: "quote_health_user",
    product_id: String(productId || "").trim().toLowerCase(),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    pricing_version: DEFAULT_PRICING_VERSION,
    entitlement_version: DEFAULT_ENTITLEMENT_VERSION,
    quote_id: `quote_${String(productId || "product")}`,
    status: "ready",
    currency: "eur",
    full_price_cents: fullPriceCents,
    already_licenced_cents: 0,
    partial_licence_credit_cents: 0,
    discount_percent: summary.discount_percent,
    discount_cents: discountCents,
    final_price_cents: finalPriceCents,
    total_tile_count: 1,
    new_tile_count: 1,
    charged_tile_count: 1,
    already_licenced_tile_count: 0,
    partial_licence_tile_count: 0,
    free_tile_count: 0,
    summary_json: JSON.stringify(summary),
    map_state_status: String(options.mapStateStatus || "stale"),
    map_state_json: options.mapStateJson || null,
    map_state_updated_at: null,
    stale_reason: "",
    error_code: "",
    error_message: "",
    requested_at: "2026-05-15T12:00:00.000Z",
    calculated_at: "2026-05-15T12:00:00.000Z",
    created_at: "2026-05-15T12:00:00.000Z",
    updated_at: "2026-05-15T12:00:00.000Z",
  };
}

async function runHandlerCase({ name, handler, request, expectStatus, expectJobProduct = "", tokenRegionPackId = "world" }) {
  const state = new GuardedDb(name, { token: `${name}_token`, tokenRegionPackId });
  const response = await handler(request(state), makeEnv(state), makeDeps(state));
  assert(response && typeof response.status === "number", `${name}: handler did not return a Response`);
  if (expectStatus !== undefined) {
    assert(response.status === expectStatus, `${name}: expected HTTP ${expectStatus}, got ${response.status}`);
  }
  assertNoForbiddenQueries(state);
  if (expectJobProduct) {
    assert(
      state.jobs.some((job) => String(job.product_id || "").toLowerCase() === String(expectJobProduct).toLowerCase()),
      `${name}: expected queued quote job for ${expectJobProduct}, got ${JSON.stringify(state.jobs)}`,
    );
  }
  return { state, response };
}

async function main() {
  const started = Date.now();
  const report = {
    status: "running",
    started_at: new Date().toISOString(),
    steps: [],
  };

  const staticGuard = staticHeavyQuoteCallGuard();
  assert(staticGuard.ok, `Public routes still contain direct createRegionPackQuote calls: ${JSON.stringify(staticGuard.violations, null, 2)}`);
  report.steps.push({
    name: "static_heavy_quote_call_guard",
    ok: true,
    allowed_create_region_pack_quote_calls: staticGuard.allowed,
  });

  const catalogShell = await runHandlerCase({
    name: "catalog_shell",
    handler: handleCreditRegionPackCatalog,
    expectStatus: 200,
    request: (state) => new Request(`https://api.planetka.io/credits/region-pack-catalog?token=${state.token}`),
  });
  const catalogShellText = await catalogShell.response.text();
  assert(catalogShellText.includes("All Full Quality Data Packs"), "catalog_shell: missing catalog shell title");
  assert(catalogShell.state.jobs.length === 0, "catalog_shell: shell request should not enqueue pricing jobs");
  report.steps.push({
    name: "catalog_shell_read_only",
    ok: true,
    query_count: catalogShell.state.queries.length,
    queued_jobs: catalogShell.state.jobs.length,
  });

  const catalogPage = await runHandlerCase({
    name: "catalog_page",
    handler: handleCreditRegionPackCatalogPage,
    expectStatus: 200,
    request: (state) => new Request(`https://api.planetka.io/credits/region-pack-catalog-page?token=${state.token}&offset=0&limit=20`),
  });
  const catalogPayload = await responseJson(catalogPage.response);
  assert(catalogPayload.ok === true, "catalog_page: payload not ok");
  assert(catalogPayload.quote_rows_read_only === true, "catalog_page: quote_rows_read_only flag missing");
  assert(Array.isArray(catalogPayload.rows) && catalogPayload.rows.length > 0, "catalog_page: no rows returned");
  assert(catalogPage.state.jobs.length === catalogPayload.rows.length, "catalog_page: each missing row should enqueue exactly one quote job");
  report.steps.push({
    name: "catalog_page_queues_only",
    ok: true,
    rows: catalogPayload.rows.length,
    query_count: catalogPage.state.queries.length,
    queued_jobs: catalogPage.state.jobs.length,
  });

  const readyQuoteMap = await runHandlerCase({
    name: "asia_map_ready_quote_stale_map",
    handler: handleCreditRegionPackMap,
    expectStatus: 200,
    expectJobProduct: "asia",
    tokenRegionPackId: "asia",
    request: (state) => {
      state.quoteRows.set("asia", readyQuoteRow("asia", { mapStateStatus: "stale" }));
      return new Request(`https://api.planetka.io/credits/region-pack-map?token=${state.token}&region_pack_id=asia`);
    },
  });
  const readyQuoteMapHtml = await readyQuoteMap.response.text();
  assert(readyQuoteMapHtml.includes('"price_pending":false'), "asia_map_ready_quote_stale_map: price should be ready");
  assert(readyQuoteMapHtml.includes('"map_pending":true'), "asia_map_ready_quote_stale_map: stale map should be pending");
  assert(
    readyQuoteMap.state.jobs.some((job) => job.trigger_type === "product_page_map_state_requested"),
    `asia_map_ready_quote_stale_map: expected a map-state job, got ${JSON.stringify(readyQuoteMap.state.jobs)}`,
  );
  report.steps.push({
    name: "ready_quote_stale_map_fast_tracks_map_state_only",
    ok: true,
    query_count: readyQuoteMap.state.queries.length,
    queued_jobs: readyQuoteMap.state.jobs,
  });

  const readyQuoteCheckout = await runHandlerCase({
    name: "asia_checkout_ready_quote",
    handler: handleCreditRegionPackCheckoutFromToken,
    expectStatus: 400,
    tokenRegionPackId: "asia",
    request: (state) => {
      state.quoteRows.set("asia", readyQuoteRow("asia", { finalPriceCents: 40, fullPriceCents: 40, mapStateStatus: "stale" }));
      return new Request(`https://api.planetka.io/credits/region-pack-checkout?token=${state.token}&region_pack_id=asia`);
    },
  });
  const readyQuoteCheckoutHtml = await readyQuoteCheckout.response.text();
  assert(readyQuoteCheckoutHtml.includes("Payment gateway unavailable below"), "asia_checkout_ready_quote: checkout did not use the ready quote row");
  assert(readyQuoteCheckout.state.jobs.length === 0, "asia_checkout_ready_quote: checkout should not enqueue when quote row is ready");
  report.steps.push({
    name: "checkout_ready_quote_reads_materialized_row_only",
    ok: true,
    query_count: readyQuoteCheckout.state.queries.length,
    queued_jobs: readyQuoteCheckout.state.jobs.length,
  });

  for (const productId of ["world", "asia"]) {
    const mapCase = await runHandlerCase({
      name: `${productId}_map`,
      handler: handleCreditRegionPackMap,
      expectStatus: 200,
      expectJobProduct: productId,
      tokenRegionPackId: productId,
      request: (state) => new Request(`https://api.planetka.io/credits/region-pack-map?token=${state.token}&region_pack_id=${productId}`),
    });
    const mapHtml = await mapCase.response.text();
    assert(mapHtml.includes('"price_pending":true'), `${productId}_map: page did not mark price pending`);
    assert(mapHtml.includes('"map_pending":true'), `${productId}_map: page did not mark map pending`);
    assert(
      mapCase.state.jobs.some((job) => job.trigger_type === "product_page_quote_map_state_requested"),
      `${productId}_map: expected a combined quote+map fast-track job, got ${JSON.stringify(mapCase.state.jobs)}`,
    );
    report.steps.push({
      name: `${productId}_map_read_only_fast_track_quote_and_map`,
      ok: true,
      query_count: mapCase.state.queries.length,
      queued_jobs: mapCase.state.jobs,
    });

    const checkoutCase = await runHandlerCase({
      name: `${productId}_checkout`,
      handler: handleCreditRegionPackCheckoutFromToken,
      expectStatus: 409,
      expectJobProduct: productId,
      tokenRegionPackId: productId,
      request: (state) => new Request(`https://api.planetka.io/credits/region-pack-checkout?token=${state.token}&region_pack_id=${productId}`),
    });
    const checkoutHtml = await checkoutCase.response.text();
    assert(checkoutHtml.includes("Data pack price is updating"), `${productId}_checkout: missing updating message`);
    report.steps.push({
      name: `${productId}_checkout_queues_only`,
      ok: true,
      query_count: checkoutCase.state.queries.length,
      queued_jobs: checkoutCase.state.jobs,
    });
  }

  const uiCheckout = await runHandlerCase({
    name: "ui_checkout_asia",
    handler: handleCreditCheckout,
    expectStatus: 409,
    expectJobProduct: "asia",
    request: () => new Request("https://api.planetka.io/credits/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ option: "region_pack", region_pack_id: "asia" }),
    }),
  });
  const uiPayload = await responseJson(uiCheckout.response);
  assert(uiPayload.error === "data_pack_price_updating", `ui_checkout_asia: unexpected error payload ${JSON.stringify(uiPayload)}`);
  report.steps.push({
    name: "ui_checkout_asia_queues_only",
    ok: true,
    query_count: uiCheckout.state.queries.length,
    queued_jobs: uiCheckout.state.jobs,
  });

  report.status = "ok";
  report.elapsed_ms = Date.now() - started;
  fs.writeFileSync(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(`PLANETKA_QUOTE_READ_ONLY_HEALTH_GATE_RESULT ${JSON.stringify({ status: "ok", report: REPORT_PATH })}`);
}

main().catch((error) => {
  const report = {
    status: "failed",
    error: String(error && error.message || error),
    stack: String(error && error.stack || ""),
    finished_at: new Date().toISOString(),
  };
  fs.writeFileSync(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.error(`PLANETKA_QUOTE_READ_ONLY_HEALTH_GATE_RESULT ${JSON.stringify({ status: "failed", error: report.error, report: REPORT_PATH })}`);
  process.exit(1);
});
