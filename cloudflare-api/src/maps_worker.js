import { corsHeaders, json } from "./worker/responses.js";
import { parseNonNegativeInteger } from "./worker/env.js";
import { normalizeQualityMode } from "./worker/entitlements.js";
import {
  handleCreditRegionPackMapLevelChunk as handleRegionPackMapLevelChunk,
  handleCreditRegionPackMiniMap as handleRegionPackMiniMap,
  handleCreditRegionPackMapStateShard as handleRegionPackMapStateShard,
  handleCreditRegionPackMapAsset as handleRegionPackMapAsset,
  handleCreditRegionPackMapOutlines as handleRegionPackMapOutlines,
  handleCreditRegionPackMapBackground as handleRegionPackMapBackground,
  handleCreditAccountCountryBorders as handleAccountCountryBorders,
  handleCreditRegionPackPageAsset as handleRegionPackPageAsset,
  getRuntimePricingSettings,
  processUserProductQuoteJobs,
} from "./worker/credit_routes.js";
import {
  recordMapServiceBusy,
  resolveMapServiceBusyIfQuiet,
} from "./worker/map_service_busy_monitor.js";

const encoder = new TextEncoder();
const MAP_QUEUE_KICK_PATH = "/maps/internal/product-map-queue-kick";
const MAP_QUEUE_INTERNAL_SECRET_HEADER = "x-planetka-internal-secret";
const MAP_QUEUE_INTERNAL_MAX_JOBS = 6;
const MAP_QUEUE_INTERNAL_MAX_MS = 7000;
const MAP_QUEUE_INTERNAL_MAX_HEAVY_MAP_JOBS = 1;
const MAP_QUEUE_SCHEDULED_MAX_JOBS = 8;
const MAP_QUEUE_SCHEDULED_MAX_MS = 9000;
const MAP_QUEUE_SCHEDULED_MAX_HEAVY_MAP_JOBS = 1;
const MAP_QUEUE_FOLLOWUP_CHAIN_LIMIT = 40;
const MAP_QUEUE_FOLLOWUP_DELAY_MS = 1500;
let runtimePricingRefreshPromise = null;
let runtimePricingRefreshAt = 0;

function nowIso() {
  return new Date().toISOString();
}

function clampNonNegativeInt(value) {
  return Math.max(0, parseNonNegativeInteger(value, 0));
}

function requireDb(env) {
  if (!env.DB) {
    throw new Error("missing_db_binding");
  }
  return env.DB;
}

function requireSecret(env, name) {
  const value = String(env[name] || "").trim();
  if (!value) {
    throw new Error(`missing_secret_${name}`);
  }
  return value;
}

async function parseJson(request) {
  try {
    return await request.json();
  } catch (_error) {
    return {};
  }
}

async function dbGet(db, sql, bindings = []) {
  const result = await db.prepare(sql).bind(...bindings).first();
  return result || null;
}

async function dbRun(db, sql, bindings = []) {
  return db.prepare(sql).bind(...bindings).run();
}

async function dbAll(db, sql, bindings = []) {
  const result = await db.prepare(sql).bind(...bindings).all();
  return Array.isArray(result && result.results) ? result.results : [];
}

function dbMetaChanges(result) {
  return clampNonNegativeInt(result && result.meta && result.meta.changes);
}

function randomToken(byteLength = 32) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(String(value || "")));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function requestClientIp(request) {
  return String(request.headers.get("CF-Connecting-IP") || "").trim();
}

function requestCountry(request) {
  return String(request.headers.get("CF-IPCountry") || "").trim().toUpperCase();
}

async function ensureCreditTables(_db) {
  // Map worker is intentionally not a schema owner. Required tables are owned
  // by commerce/auth migrations; map routes must stay read-mostly and bounded.
}

async function invalidateAnalyticsSnapshots(_env) {
  // Maps do not own analytics snapshots.
}

async function getPreviewFairUsageHoldForUser(_db, _userId) {
  return { held: false };
}

async function requireAuthenticatedUserContext() {
  return { error: "map_worker_auth_not_available", status: 503 };
}

const MAP_ROUTE_DEPS = {
  clampNonNegativeInt,
  dbAll,
  dbGet,
  dbMetaChanges,
  dbRun,
  ensureCreditTables,
  getPreviewFairUsageHoldForUser,
  invalidateAnalyticsSnapshots,
  json,
  normalizeEmail,
  normalizeQualityMode,
  nowIso,
  parseJson,
  randomToken,
  requireAuthenticatedUserContext,
  requireDb,
  requireSecret,
  requestClientIp,
  requestCountry,
  sha256Hex,
};

function mapPathToCreditPath(path) {
  const safePath = String(path || "");
  if (!safePath.startsWith("/maps/")) {
    return safePath;
  }
  return `/credits/${safePath.slice("/maps/".length)}`;
}

async function maybeRefreshPricingSettings(env) {
  const now = Date.now();
  if (runtimePricingRefreshPromise && now - runtimePricingRefreshAt < 60_000) {
    return runtimePricingRefreshPromise;
  }
  runtimePricingRefreshAt = now;
  runtimePricingRefreshPromise = getRuntimePricingSettings(env, MAP_ROUTE_DEPS, { force: false })
    .catch((error) => {
      console.warn("maps.runtime_pricing_refresh_failed", JSON.stringify({ error: String(error && error.message || error) }));
      return null;
    });
  return runtimePricingRefreshPromise;
}

async function dispatchMapsRoute(request, env, path) {
  await maybeRefreshPricingSettings(env);
  switch (path) {
    case "/credits/region-pack-map-level-chunk":
      if (request.method === "GET" || request.method === "HEAD") return await handleRegionPackMapLevelChunk(request, env, MAP_ROUTE_DEPS);
      return null;
    case "/credits/region-pack-mini-map":
      if (request.method === "GET" || request.method === "HEAD") return await handleRegionPackMiniMap(request, env, MAP_ROUTE_DEPS);
      return null;
    case "/credits/region-pack-map-state-shard":
      if (request.method === "GET" || request.method === "HEAD") return await handleRegionPackMapStateShard(request, env, MAP_ROUTE_DEPS);
      return null;
    case "/credits/region-pack-map-asset":
      if (request.method === "GET" || request.method === "HEAD") return await handleRegionPackMapAsset(request, env, MAP_ROUTE_DEPS);
      return null;
    case "/credits/region-pack-map-outlines":
      if (request.method === "GET" || request.method === "HEAD") return await handleRegionPackMapOutlines(request, env, MAP_ROUTE_DEPS);
      return null;
    case "/credits/region-pack-map-background.jpg":
      if (request.method === "GET" || request.method === "HEAD") return await handleRegionPackMapBackground(request, env, MAP_ROUTE_DEPS);
      return null;
    case "/credits/account-country-borders.json":
      if (request.method === "GET" || request.method === "HEAD") return await handleAccountCountryBorders(request, env, MAP_ROUTE_DEPS);
      return null;
    case "/credits/page-assets/region-pack-map.css":
    case "/credits/page-assets/region-pack-map.js":
    case "/credits/page-assets/region-pack-dynamic-map.css":
    case "/credits/page-assets/region-pack-dynamic-map.js":
      if (request.method === "GET" || request.method === "HEAD") return await handleRegionPackPageAsset(request, env, MAP_ROUTE_DEPS);
      return null;
    default:
      return null;
  }
}

function isPrimaryMapDataPath(path) {
  const safePath = String(path || "");
  return safePath === "/maps/region-pack-map-level-chunk"
    || safePath === "/maps/region-pack-map-state-shard";
}

function shouldRecordMapBusy(path, response) {
  if (!response) return true;
  if (Number(response.status || 0) >= 500) return true;
  return isPrimaryMapDataPath(path) && Number(response.status || 0) >= 400;
}

function mapBusyEventFromRequest(request, response, error) {
  const url = new URL(request.url);
  return {
    path: url.pathname,
    product_id: url.searchParams.get("region_pack_id")
      || url.searchParams.get("product_id")
      || url.searchParams.get("id")
      || "",
    level: url.searchParams.get("level")
      || url.searchParams.get("map_level")
      || "",
    status: response ? `http_${response.status}` : "",
    error: error ? String(error && error.message || error) : "",
  };
}

function recordMapBusyBestEffort(ctx, env, request, response, error) {
  if (!env || !env.DB || !ctx || typeof ctx.waitUntil !== "function") {
    return;
  }
  ctx.waitUntil((async () => {
    try {
      await recordMapServiceBusy(env.DB, MAP_ROUTE_DEPS, mapBusyEventFromRequest(request, response, error));
    } catch (recordError) {
      console.warn("maps.busy_monitor.record_failed", JSON.stringify({ error: String(recordError && recordError.message || recordError) }));
    }
  })());
}

function resolveMapBusyBestEffort(ctx, env) {
  if (!env || !env.DB || !ctx || typeof ctx.waitUntil !== "function") {
    return;
  }
  ctx.waitUntil((async () => {
    try {
      await resolveMapServiceBusyIfQuiet(env.DB, MAP_ROUTE_DEPS);
    } catch (resolveError) {
      console.warn("maps.busy_monitor.resolve_failed", JSON.stringify({ error: String(resolveError && resolveError.message || resolveError) }));
    }
  })());
}

async function countQueuedMapJobs(db) {
  const now = nowIso();
  const row = await dbGet(
    db,
    `
      SELECT
        COUNT(*) AS queued_count,
        SUM(CASE WHEN available_at <= ? THEN 1 ELSE 0 END) AS available_count
      FROM user_product_quote_jobs
      WHERE status = 'queued'
        AND (
          INSTR(LOWER(COALESCE(trigger_type, '')), 'map_state') > 0
          OR INSTR(LOWER(COALESCE(stale_reason, '')), 'map_state') > 0
        )
    `,
    [now],
  );
  return {
    queued: Math.max(0, Number.parseInt(row && row.queued_count || 0, 10) || 0),
    available: Math.max(0, Number.parseInt(row && row.available_count || 0, 10) || 0),
  };
}

function mapQueueBatchLimits(path) {
  if (String(path || "") === "scheduled") {
    return {
      maxJobs: MAP_QUEUE_SCHEDULED_MAX_JOBS,
      maxMs: MAP_QUEUE_SCHEDULED_MAX_MS,
      maxHeavyMapJobs: MAP_QUEUE_SCHEDULED_MAX_HEAVY_MAP_JOBS,
    };
  }
  return {
    maxJobs: MAP_QUEUE_INTERNAL_MAX_JOBS,
    maxMs: MAP_QUEUE_INTERNAL_MAX_MS,
    maxHeavyMapJobs: MAP_QUEUE_INTERNAL_MAX_HEAVY_MAP_JOBS,
  };
}

async function runProductMapQueueBatch(env, path) {
  const db = requireDb(env);
  const limits = mapQueueBatchLimits(path);
  const summary = await processUserProductQuoteJobs(
    db,
    env,
    MAP_ROUTE_DEPS,
    {
      maxJobs: limits.maxJobs,
      maxMs: limits.maxMs,
      maxMapJobs: limits.maxJobs,
      maxHeavyMapJobs: limits.maxHeavyMapJobs,
      jobMode: "map",
    },
  );
  const remaining = await countQueuedMapJobs(db);
  if (summary && (summary.processed > 0 || summary.requeued > 0 || summary.failed > 0 || summary.cancelled > 0 || summary.map_processed > 0 || summary.map_deferred > 0)) {
    console.log(
      "maps.product_map_queue.completed",
      JSON.stringify({
        path,
        processed: Number(summary.processed || 0),
        requeued: Number(summary.requeued || 0),
        failed: Number(summary.failed || 0),
        cancelled: Number(summary.cancelled || 0),
        map_processed: Number(summary.map_processed || 0),
        heavy_map_processed: Number(summary.heavy_map_processed || 0),
        map_deferred: Number(summary.map_deferred || 0),
        max_jobs: limits.maxJobs,
        max_ms: limits.maxMs,
        max_heavy_map_jobs: limits.maxHeavyMapJobs,
        elapsed_ms: Number(summary.elapsed_ms || 0),
        queued_remaining: remaining.queued,
        available_remaining: remaining.available,
      }),
    );
  }
  return { summary, remaining };
}

function scheduleProductMapQueueFollowup(ctx, requestUrl, env, remainingChain) {
  if (!ctx || typeof ctx.waitUntil !== "function") {
    return;
  }
  const chainLeft = Math.max(0, Math.min(MAP_QUEUE_FOLLOWUP_CHAIN_LIMIT, Number.parseInt(remainingChain || 0, 10) || 0));
  const secret = String(env && env.JWT_SIGNING_SECRET || "").trim();
  if (!chainLeft || !secret) {
    return;
  }
  const url = new URL(MAP_QUEUE_KICK_PATH, requestUrl || "https://api.planetka.io/");
  url.searchParams.set("remaining", String(chainLeft));
  ctx.waitUntil((async () => {
    try {
      await new Promise((resolve) => setTimeout(resolve, MAP_QUEUE_FOLLOWUP_DELAY_MS));
      await fetch(url.toString(), {
        method: "POST",
        headers: {
          [MAP_QUEUE_INTERNAL_SECRET_HEADER]: secret,
        },
      });
    } catch (error) {
      console.warn(
        "maps.product_map_queue.followup_failed",
        JSON.stringify({ error: String(error && error.message || "map_queue_followup_failed") }),
      );
    }
  })());
}

async function handleInternalProductMapQueueKick(request, env, ctx) {
  if (request.method !== "POST") {
    return json({ ok: false, error: "method_not_allowed" }, 405, env);
  }
  const expectedSecret = String(env && env.JWT_SIGNING_SECRET || "").trim();
  const suppliedSecret = String(request.headers.get(MAP_QUEUE_INTERNAL_SECRET_HEADER) || "").trim();
  if (!expectedSecret || suppliedSecret !== expectedSecret) {
    return json({ ok: false, error: "not_found" }, 404, env);
  }
  const url = new URL(request.url);
  const remainingChain = Math.max(0, Math.min(MAP_QUEUE_FOLLOWUP_CHAIN_LIMIT, Number.parseInt(url.searchParams.get("remaining") || "0", 10) || 0));
  const result = await runProductMapQueueBatch(env, MAP_QUEUE_KICK_PATH);
  if (result.summary && result.summary.lock_acquired !== false && result.remaining.available > 0 && remainingChain > 0) {
    scheduleProductMapQueueFollowup(ctx, request.url, env, remainingChain - 1);
  }
  return json(
    {
      ok: true,
      processed: Number(result.summary && result.summary.processed || 0),
      requeued: Number(result.summary && result.summary.requeued || 0),
      failed: Number(result.summary && result.summary.failed || 0),
      cancelled: Number(result.summary && result.summary.cancelled || 0),
      map_processed: Number(result.summary && result.summary.map_processed || 0),
      heavy_map_processed: Number(result.summary && result.summary.heavy_map_processed || 0),
      elapsed_ms: Number(result.summary && result.summary.elapsed_ms || 0),
      queued_remaining: result.remaining.queued,
      available_remaining: result.remaining.available,
      followup_scheduled: result.summary && result.summary.lock_acquired !== false && result.remaining.available > 0 && remainingChain > 0,
    },
    200,
    env,
  );
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }
    const url = new URL(request.url);
    if (url.pathname === MAP_QUEUE_KICK_PATH) {
      try {
        return await handleInternalProductMapQueueKick(request, env, ctx);
      } catch (error) {
        console.error("maps.internal_queue.error", JSON.stringify({ error: String(error && error.message || "map_queue_failed") }));
        return json({ ok: false, error: "map_queue_failed" }, 500, env);
      }
    }
    const creditPath = mapPathToCreditPath(url.pathname);
    const mappedUrl = new URL(request.url);
    mappedUrl.pathname = creditPath;
    const mappedRequest = new Request(mappedUrl.toString(), request);
    try {
      const response = await dispatchMapsRoute(mappedRequest, env, creditPath);
      if (response) {
        if (shouldRecordMapBusy(url.pathname, response)) {
          recordMapBusyBestEffort(ctx, env, request, response, null);
        } else if (isPrimaryMapDataPath(url.pathname) && response.ok) {
          resolveMapBusyBestEffort(ctx, env);
        }
        return response;
      }
      recordMapBusyBestEffort(ctx, env, request, null, new Error("map_route_not_found"));
      return json({ ok: false, error: "map_route_not_found" }, 404, env);
    } catch (error) {
      console.error("maps.unhandled_error", JSON.stringify({ path: url.pathname, error: String(error && error.message || error) }));
      recordMapBusyBestEffort(ctx, env, request, null, error);
      return json({ ok: false, error: "map_worker_unavailable", message: "Map service is temporarily busy. Please try loading the map again in a few moments." }, 503, env);
    }
  },

  async scheduled(controller, env, ctx) {
    const scheduledAt = new Date(controller.scheduledTime || Date.now()).toISOString();
    ctx.waitUntil((async () => {
      try {
        const result = await runProductMapQueueBatch(env, "scheduled");
        if (result.summary && result.summary.lock_acquired !== false && result.remaining.available > 0) {
          scheduleProductMapQueueFollowup(ctx, "https://api.planetka.io/maps/", env, MAP_QUEUE_FOLLOWUP_CHAIN_LIMIT);
        }
        console.log("maps.product_map_queue.scheduled_completed", JSON.stringify({ scheduled_at: scheduledAt, result }));
      } catch (error) {
        console.error("maps.product_map_queue.scheduled_error", JSON.stringify({ scheduled_at: scheduledAt, error: String(error && error.message || "map_queue_failed") }));
      }
      try {
        await resolveMapServiceBusyIfQuiet(requireDb(env), MAP_ROUTE_DEPS);
      } catch (error) {
        console.warn("maps.busy_monitor.scheduled_resolve_failed", JSON.stringify({ scheduled_at: scheduledAt, error: String(error && error.message || "map_busy_resolve_failed") }));
      }
    })());
  },
};
