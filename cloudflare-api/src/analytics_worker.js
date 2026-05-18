import {
  corsHeaders,
  html,
  json,
  jsonWithHeaders,
  publicErrorCode,
} from "./worker/responses.js";
import {
  parseBooleanFlag,
  parseNonNegativeInteger,
  parsePositiveNumber,
} from "./worker/env.js";
import {
  PLAN_CODE_FREE,
  isBlockedStatus,
  isDeviceLimitExemptEmail,
  isQualityModeAllowedForPlan,
  normalizePlanCode,
  normalizeQualityMode,
  normalizeRequestedPlan,
  parseCsvEmailSet,
  planAccessSummary,
  planDisplayName,
  qualityModeNotAllowedMessage,
  resolvePlanCode,
  resolvePolicyPlanCode,
} from "./worker/entitlements.js";
import {
  handleApiKeyActivatePage,
  handleApiKeyPage,
} from "./worker/api_key_page_handlers.js";
import {
  createAuthApiKeyHandlers,
} from "./worker/auth_api_key_handlers.js";
import {
  createAuthCore,
} from "./worker/auth_core.js";
import {
  readBearerUser as readBearerUserRoute,
  requireAuthenticatedUserContext as requireAuthenticatedUserContextRoute,
} from "./worker/auth_session.js";
import {
  createAuthSessionRouteHandlers,
} from "./worker/auth_session_route_handlers.js";
import {
  handleAddonUpdateManifest,
  handleLegalDocumentRequest,
} from "./worker/public_misc_handlers.js";
import {
  dispatchAdminRoute,
  isAdminRoutePath,
} from "./worker/admin_routes.js";
import {
  buildAdminSessionClearCookie,
  buildAdminSessionCookie,
  requireAnalyticsAdmin as requireAnalyticsAdminRoute,
} from "./worker/auth_session.js";
import {
  handleAdminAnalyticsData as handleAdminAnalyticsDataRoute,
  handleAdminAnalyticsPage as handleAdminAnalyticsPageRoute,
  handleAdminAnalyticsProductsPage as handleAdminAnalyticsProductsPageRoute,
  handleAdminAnalyticsTileMapImage as handleAdminAnalyticsTileMapImageRoute,
  handleAdminAnalyticsUserPage as handleAdminAnalyticsUserPageRoute,
  handleAdminAnalyticsUsersPage as handleAdminAnalyticsUsersPageRoute,
  handleAdminSetPricingSettings as handleAdminSetPricingSettingsRoute,
  handleAdminSetProductDiscount as handleAdminSetProductDiscountRoute,
} from "./worker/admin_analytics_handlers.js";
import {
  collectAnalyticsSnapshot as collectAnalyticsSnapshotQuery,
  collectQuoteQueueHealth as collectQuoteQueueHealthQuery,
  listAnalyticsUsers as listAnalyticsUsersQuery,
  parseAnalyticsUsersSort as parseAnalyticsUsersSortQuery,
  parseAnalyticsUsersSortDirection as parseAnalyticsUsersSortDirectionQuery,
  parseHeavyUserPlanFilter as parseHeavyUserPlanFilterQuery,
  sanitizeAnalyticsMinutes as sanitizeAnalyticsMinutesQuery,
  sanitizeLiveTileMapMinutes as sanitizeLiveTileMapMinutesQuery,
} from "./worker/admin_analytics_queries.js";
import {
  buildAnalyticsSnapshotMatrix,
  buildAnalyticsUsersSnapshot,
  invalidateAnalyticsSnapshots,
  isAnalyticsSnapshotStale,
  loadAnalyticsSnapshot,
  loadAnalyticsUsersSnapshot,
  storeAnalyticsSnapshot,
} from "./worker/admin_analytics_snapshots.js";
import {
  handleAdminLoginPage as handleAdminLoginPageRoute,
  handleAdminPasswordLogin as handleAdminPasswordLoginRoute,
  handleAdminSessionLogout as handleAdminSessionLogoutRoute,
  handleAdminSessionStart as handleAdminSessionStartRoute,
  handleAdminSessionStartPage as handleAdminSessionStartPageRoute,
} from "./worker/admin_session_handlers.js";
import {
  handleAdminQaAuthReset as handleAdminQaAuthResetRoute,
  handleAdminUserBlock as handleAdminUserBlockRoute,
  handleAdminUserHardBlock as handleAdminUserHardBlockRoute,
  handleAdminUserReleasePreviewHold as handleAdminUserReleasePreviewHoldRoute,
  handleAdminUserSetPlan as handleAdminUserSetPlanRoute,
  handleAdminUserSetPreviewHold as handleAdminUserSetPreviewHoldRoute,
  handleAdminUserUnblock as handleAdminUserUnblockRoute,
} from "./worker/admin_user_handlers.js";
import {
  getRuntimePricingSettings,
  listRegionProductPricingRows,
  setRegionProductDiscountOverride,
  setRuntimePricingSettings,
} from "./worker/credit_routes.js";
import {
  runScheduledMaintenanceJobs,
} from "./worker/maintenance_jobs.js";
import {
  handleTileEventQueueBatch,
} from "./worker/tile_event_queue.js";
import {
  collectWorkerOverloadHealth,
  runWorkerOverloadMonitor,
} from "./worker/worker_overload_monitor.js";
import {
  collectMapServiceBusyHealth,
} from "./worker/map_service_busy_monitor.js";

const encoder = new TextEncoder();
const ADDON_ID = "planetka";
const DEFAULT_UPGRADE_URL = "https://www.planetka.io/blender/pricing";
const DEFAULT_CONTACT_URL = "https://www.planetka.io/contact-me";
const DEFAULT_TERMS_URL = "https://api.planetka.io/legal/terms-of-service.pdf";
const DEFAULT_PRIVACY_URL = "https://api.planetka.io/legal/privacy-policy.pdf";
const DEFAULT_LEGAL_VERSION = "2026-05-12";
const DEFAULT_ADDON_UPDATE_MANIFEST_VERSION = "0.2.0";
const DEFAULT_ADDON_UPDATE_CHANNEL = "stable";
const DEFAULT_ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS = 300;
const DEFAULT_ADDON_UPDATE_RELEASE_NOTES_URL = "https://www.planetka.io/blender/documentation/";
const DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT = 20;
const DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT = 6;
const DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS = 900;
const DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_LIMIT = 30;
const DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_LIMIT = 60;
const DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS = 60;
const DEFAULT_AUTH_CONTEXT_CACHE_TTL_SECONDS = 60;
const DEFAULT_AUTH_CONTEXT_CACHE_MAX_ENTRIES = 4096;
const DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS = 3600;
const DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS = 900;
const DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS = 2;
const DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT = 20;
const DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS = 300;
const DEFAULT_REFRESH_SESSION_CLEANUP_RETENTION_DAYS = 30;
const DEFAULT_AUTH_REFRESH_EVENT_RETENTION_DAYS = 30;
const DEFAULT_TILE_EVENT_RETENTION_DAYS = 30;
const DEFAULT_TILE_ROLLUP_RETENTION_DAYS = 365;
const DEFAULT_ALERT_PROD_403_THRESHOLD = 25;
const DEFAULT_ALERT_PROD_403_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_429_THRESHOLD = 25;
const DEFAULT_ALERT_PROD_429_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_TILE_MISS_THRESHOLD = 25;
const DEFAULT_ALERT_PROD_TILE_MISS_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_TILE_ERROR_THRESHOLD = 10;
const DEFAULT_ALERT_PROD_TILE_ERROR_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_COOLDOWN_SECONDS = 300;
const DEFAULT_MONTHLY_COST_ALERT_BASE_USD = 50;
const DEFAULT_MONTHLY_COST_ALERT_STEP_USD = 10;
const DEFAULT_R2_ESTIMATED_STORAGE_GB = 2600;
const DEFAULT_R2_STORAGE_PRICE_PER_GB_MONTH_USD = 0.015;
const DEFAULT_R2_STORAGE_FREE_GB_MONTH = 10;
const DEFAULT_R2_CLASS_A_PRICE_PER_MILLION_USD = 4.5;
const DEFAULT_R2_CLASS_B_PRICE_PER_MILLION_USD = 0.36;
const DEFAULT_R2_CLASS_A_FREE_OPS_PER_MONTH = 1000000;
const DEFAULT_R2_CLASS_B_FREE_OPS_PER_MONTH = 10000000;
const DEFAULT_CLOUDFLARE_BILLABLE_CACHE_TTL_SECONDS = 120;
const DEFAULT_ANALYTICS_WINDOW_MINUTES = 60;
const MAX_ANALYTICS_WINDOW_MINUTES = 10080;
const DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES = 1;
const ALLOWED_LIVE_TILE_MAP_WINDOW_MINUTES = new Set([1, 3, 10]);
const DEFAULT_AUTH_REFRESH_HEALTH_WINDOW_SECONDS = 7 * 86400;
const INTERNAL_TEST_ANALYTICS_EMAIL_PATTERNS = "%@planetka.io,tom.griger@gmail.com,tom.griger@yahoo.com";
const DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS = `stressfree%,${INTERNAL_TEST_ANALYTICS_EMAIL_PATTERNS}`;
const DEFAULT_ANALYTICS_REVENUE_EXCLUDED_EMAIL_PATTERNS = INTERNAL_TEST_ANALYTICS_EMAIL_PATTERNS;
const DEFAULT_ANALYTICS_ADMIN_EMAILS = "info@planetka.io,tom.griger@gmail.com";
const DEFAULT_ADMIN_LOGIN_EMAIL = "tom.griger@gmail.com";
const DEFAULT_ADMIN_ANALYTICS_TILE_MAP_KEY = "planetka-assets/Admin/world_map_720x360.jpg";
const DEFAULT_ADMIN_SUPPORT_MISSING_MANIFEST_KEY = "planetka-assets/Admin/support_missing_manifest.json";
const RATE_LIMIT_PRUNE_INTERVAL_SECONDS = 300;
const RATE_LIMIT_ENTRY_TTL_SECONDS = 172800;

const FIXED_INTERNAL_TEST_PLAN_BY_EMAIL = Object.freeze({
  "free@planetka.io": PLAN_CODE_FREE,
});

let rateLimitsTableReady = false;
let adminHardBlocksTableReady = false;
let apiKeyTablesReady = false;
let refreshSessionColumnsReady = false;
let userConsentColumnsReady = false;
let userQualityAccessColumnsReady = false;
let newsletterContactsTableReady = false;
let authRefreshEventsTableReady = false;
let creditAccountTableReady = false;
let rateLimitsLastPruneAt = 0;
const authContextCache = new Map();

function nowIso() {
  return new Date().toISOString();
}

function addMinutesIso(minutes) {
  return new Date(Date.now() + (Number(minutes) * 60 * 1000)).toISOString();
}

function addDaysIso(days) {
  return new Date(Date.now() + (Number(days) * 24 * 60 * 60 * 1000)).toISOString();
}

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function normalizeContactUrl(value) {
  const fallback = DEFAULT_CONTACT_URL;
  const raw = String(value || "").trim();
  if (!raw) {
    return fallback;
  }
  const trimmed = raw.replace(/\/+$/, "");
  if (trimmed === "https://www.planetka.io/contact") {
    return fallback;
  }
  return raw;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
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
  return Math.max(0, parseNonNegativeInteger(result && result.meta && result.meta.changes, 0));
}

function parseRateLimitInteger(value, fallback) {
  return Math.max(0, parseNonNegativeInteger(value, fallback));
}

function requestClientIp(request) {
  const direct = String(request.headers.get("CF-Connecting-IP") || request.headers.get("True-Client-IP") || "").trim();
  if (direct) {
    return direct;
  }
  const forwarded = String(request.headers.get("X-Forwarded-For") || "").trim();
  if (forwarded) {
    const first = forwarded.split(",")[0];
    return String(first || "").trim() || "unknown";
  }
  return "unknown";
}

function requestCountry(request) {
  const country = String(request.headers.get("CF-IPCountry") || request.cf && request.cf.country || "").trim().toUpperCase();
  if (!country || country === "XX" || country === "T1") {
    return "UNKNOWN";
  }
  return country;
}

function blockedAccountResponse(env, message = "Planetka account is blocked. Contact info@planetka.io.") {
  return json({ ok: false, error: "account_blocked", message }, 403, env);
}

function rateLimitedResponse(env, code, message, retryAfterSeconds) {
  const retryAfter = Math.max(1, parseNonNegativeInteger(retryAfterSeconds, 1));
  return jsonWithHeaders(
    {
      ok: false,
      error: code,
      message,
      retry_after_seconds: retryAfter,
    },
    429,
    env,
    { "Retry-After": String(retryAfter) },
  );
}

function base64UrlEncode(bytes) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlEncodeString(value) {
  return base64UrlEncode(encoder.encode(String(value || "")));
}

function base64UrlDecodeToString(value) {
  let normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  while (normalized.length % 4 !== 0) {
    normalized += "=";
  }
  return atob(normalized);
}

function base64UrlDecodeToBytes(value) {
  const binary = base64UrlDecodeToString(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function randomToken(byteLength = 32) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(String(value || "")));
  const bytes = new Uint8Array(digest);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function hmacSha256(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(value));
  return new Uint8Array(signature);
}

async function signJwt(payload, secret) {
  const header = { alg: "HS256", typ: "JWT" };
  const encodedHeader = base64UrlEncodeString(JSON.stringify(header));
  const encodedPayload = base64UrlEncodeString(JSON.stringify(payload));
  const signingInput = `${encodedHeader}.${encodedPayload}`;
  const signature = await hmacSha256(secret, signingInput);
  return `${signingInput}.${base64UrlEncode(signature)}`;
}

async function verifyJwt(token, secret) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) {
    throw new Error("invalid_token_format");
  }
  const [encodedHeader, encodedPayload, encodedSignature] = parts;
  void encodedHeader;
  const signingInput = `${encodedHeader}.${encodedPayload}`;
  const expected = await hmacSha256(secret, signingInput);
  const actual = base64UrlDecodeToBytes(encodedSignature);
  if (actual.length !== expected.length) {
    throw new Error("invalid_token_signature");
  }
  let mismatch = 0;
  for (let index = 0; index < actual.length; index += 1) {
    mismatch |= actual[index] ^ expected[index];
  }
  if (mismatch !== 0) {
    throw new Error("invalid_token_signature");
  }
  const payload = JSON.parse(base64UrlDecodeToString(encodedPayload));
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (payload.exp && Number(payload.exp) < nowSeconds) {
    throw new Error("token_expired");
  }
  return payload;
}

function isValidApiKey(value) {
  return /^pka_[A-Za-z0-9_-]{24,128}$/.test(String(value || "").trim());
}

function maskApiKey(value) {
  const key = String(value || "").trim();
  if (!key) {
    return "";
  }
  if (key.length <= 12) {
    return `${key.slice(0, 4)}***`;
  }
  return `${key.slice(0, 8)}...${key.slice(-4)}`;
}

function normalizeDeviceId(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  return raw.replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 128);
}

function normalizeTierCodeStrict(value) {
  const normalized = normalizePlanCode(value);
  if (normalized === PLAN_CODE_FREE) {
    return normalized;
  }
  return "";
}

function computeApiKeyExpiryIso(planCode, env) {
  void planCode;
  void env;
  return "";
}

async function maybePruneRateLimits(db, nowSeconds) {
  if ((nowSeconds - rateLimitsLastPruneAt) < RATE_LIMIT_PRUNE_INTERVAL_SECONDS) {
    return;
  }
  rateLimitsLastPruneAt = nowSeconds;
  try {
    await dbRun(db, `DELETE FROM rate_limits WHERE updated_at < ?`, [Math.max(0, nowSeconds - RATE_LIMIT_ENTRY_TTL_SECONDS)]);
  } catch (error) {
    console.debug("auth_worker.rate_limits.prune_failed", String(error && error.message || "rate_limit_prune_failed"));
  }
}

async function consumeRateLimitWindow(db, scope, rawKey, limit, windowSeconds) {
  if (limit <= 0 || windowSeconds <= 0) {
    return { allowed: true, count: 0, limit, retryAfterSeconds: 0 };
  }
  const nowSeconds = Math.floor(Date.now() / 1000);
  await maybePruneRateLimits(db, nowSeconds);
  const bucketStart = nowSeconds - (nowSeconds % windowSeconds);
  const normalizedRawKey = String(rawKey || "").trim() || "unknown";
  const hashedKey = await sha256Hex(`${scope}:${normalizedRawKey}`);
  const storageKey = `${scope}:${hashedKey}`;
  const row = await dbGet(
    db,
    `
      INSERT INTO rate_limits (key, window_start, count, updated_at)
      VALUES (?, ?, 1, ?)
      ON CONFLICT(key) DO UPDATE SET
        window_start = CASE WHEN rate_limits.window_start = excluded.window_start THEN rate_limits.window_start ELSE excluded.window_start END,
        count = CASE WHEN rate_limits.window_start = excluded.window_start THEN rate_limits.count + 1 ELSE 1 END,
        updated_at = excluded.updated_at
      RETURNING count, window_start
    `,
    [storageKey, bucketStart, nowSeconds],
  );
  const count = parseNonNegativeInteger(row && row.count, 0);
  const effectiveWindowStart = parseNonNegativeInteger(row && row.window_start, bucketStart);
  return {
    allowed: count <= limit,
    count,
    limit,
    retryAfterSeconds: Math.max(1, (effectiveWindowStart + windowSeconds) - nowSeconds),
  };
}

async function ensureRateLimitsTable(db) {
  if (rateLimitsTableReady) {
    return;
  }
  await dbRun(db, `CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, window_start INTEGER NOT NULL, count INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_rate_limits_updated_at ON rate_limits(updated_at DESC)`);
  rateLimitsTableReady = true;
}

async function ensureAdminHardBlocksTable(db) {
  if (adminHardBlocksTableReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS admin_hard_blocks (
        id TEXT PRIMARY KEY,
        blocked_email TEXT,
        blocked_device_id TEXT,
        blocked_ip TEXT,
        source_user_id TEXT,
        source_user_email TEXT,
        reason TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
      )
    `,
  );
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_admin_hard_blocks_active_email ON admin_hard_blocks(active, blocked_email)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_admin_hard_blocks_active_device ON admin_hard_blocks(active, blocked_device_id)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_admin_hard_blocks_active_ip ON admin_hard_blocks(active, blocked_ip)`);
  adminHardBlocksTableReady = true;
}

async function findActiveHardBlock(db, identifiers = {}) {
  await ensureAdminHardBlocksTable(db);
  const email = normalizeEmail(identifiers.email || "");
  const deviceId = normalizeDeviceId(identifiers.device_id || identifiers.deviceId || "");
  const ip = String(identifiers.ip || "").trim();
  const whereParts = [];
  const bindings = [];
  if (email) {
    whereParts.push(`LOWER(COALESCE(blocked_email, '')) = ?`);
    bindings.push(email);
  }
  if (deviceId) {
    whereParts.push(`LOWER(COALESCE(blocked_device_id, '')) = ?`);
    bindings.push(deviceId);
  }
  if (ip) {
    whereParts.push(`COALESCE(blocked_ip, '') = ?`);
    bindings.push(ip);
  }
  if (!whereParts.length) {
    return null;
  }
  return dbGet(
    db,
    `
      SELECT id, blocked_email, blocked_device_id, blocked_ip, source_user_id, source_user_email, reason, created_by, created_at
      FROM admin_hard_blocks
      WHERE active = 1 AND (${whereParts.join(" OR ")})
      ORDER BY created_at DESC
      LIMIT 1
    `,
    bindings,
  );
}

async function ensureAuthRefreshEventsTable(db) {
  if (authRefreshEventsTableReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS auth_refresh_events (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        created_at_unix INTEGER NOT NULL,
        user_id TEXT,
        user_email TEXT,
        auth_method TEXT,
        api_key_id TEXT,
        device_id TEXT,
        client_ip TEXT,
        cf_country TEXT,
        cf_ray TEXT,
        outcome TEXT NOT NULL,
        error_code TEXT,
        http_status INTEGER NOT NULL DEFAULT 0,
        details_json TEXT
      )
    `,
  );
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_created_unix ON auth_refresh_events(created_at_unix DESC)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_outcome_created_unix ON auth_refresh_events(outcome, created_at_unix DESC)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_user_created_unix ON auth_refresh_events(user_id, created_at_unix DESC)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_email_created_unix ON auth_refresh_events(user_email, created_at_unix DESC)`);
  authRefreshEventsTableReady = true;
}

async function logAuthRefreshEvent(db, event = {}) {
  try {
    await ensureAuthRefreshEventsTable(db);
    const createdAt = nowIso();
    const createdAtUnix = Math.floor(Date.parse(createdAt) / 1000) || Math.floor(Date.now() / 1000);
    await dbRun(
      db,
      `
        INSERT INTO auth_refresh_events (
          id, created_at, created_at_unix, user_id, user_email, auth_method, api_key_id, device_id,
          client_ip, cf_country, cf_ray, outcome, error_code, http_status, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        crypto.randomUUID(),
        createdAt,
        createdAtUnix,
        String(event.user_id || "").trim() || null,
        normalizeEmail(event.user_email || "") || null,
        String(event.auth_method || "").trim().toLowerCase() || null,
        String(event.api_key_id || "").trim() || null,
        normalizeDeviceId(event.device_id || "") || null,
        String(event.client_ip || "").trim() || null,
        String(event.cf_country || "").trim().toUpperCase() || null,
        String(event.cf_ray || "").trim() || null,
        String(event.outcome || "error").trim().toLowerCase() || "error",
        String(event.error_code || "").trim().slice(0, 128) || null,
        parseNonNegativeInteger(event.http_status, 0),
        event.details && typeof event.details === "object" ? JSON.stringify(event.details) : null,
      ],
    );
  } catch (error) {
    console.warn("auth_worker.auth_refresh_event_log_failed", String(error && error.message || "auth_refresh_event_log_failed"));
  }
}

async function ensureUserConsentColumns(db) {
  if (userConsentColumnsReady) {
    return;
  }
  const pragma = await db.prepare(`PRAGMA table_info(users)`).all();
  const rows = Array.isArray(pragma && pragma.results) ? pragma.results : [];
  if (!rows.length) {
    return;
  }
  const names = new Set(rows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  for (const statement of [
    !names.has("terms_accepted_at") ? `ALTER TABLE users ADD COLUMN terms_accepted_at TEXT` : "",
    !names.has("privacy_accepted_at") ? `ALTER TABLE users ADD COLUMN privacy_accepted_at TEXT` : "",
    !names.has("terms_version") ? `ALTER TABLE users ADD COLUMN terms_version TEXT` : "",
    !names.has("privacy_version") ? `ALTER TABLE users ADD COLUMN privacy_version TEXT` : "",
  ].filter(Boolean)) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      if (!String(error && error.message || "").toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  userConsentColumnsReady = true;
}

async function ensureUserQualityAccessColumns(db) {
  if (userQualityAccessColumnsReady) {
    return;
  }
  const pragma = await db.prepare(`PRAGMA table_info(users)`).all();
  const rows = Array.isArray(pragma && pragma.results) ? pragma.results : [];
  if (!rows.length) {
    return;
  }
  const names = new Set(rows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  for (const statement of [
    !names.has("preview_fair_usage_hold_at") ? `ALTER TABLE users ADD COLUMN preview_fair_usage_hold_at TEXT` : "",
    !names.has("preview_fair_usage_hold_reason") ? `ALTER TABLE users ADD COLUMN preview_fair_usage_hold_reason TEXT` : "",
    !names.has("preview_fair_usage_hold_details_json") ? `ALTER TABLE users ADD COLUMN preview_fair_usage_hold_details_json TEXT` : "",
  ].filter(Boolean)) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      if (!String(error && error.message || "").toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  userQualityAccessColumnsReady = true;
}

async function ensureMinimalCreditAccountTable(db) {
  if (creditAccountTableReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_credit_accounts (
        user_id TEXT PRIMARY KEY,
        account_type TEXT NOT NULL DEFAULT 'account',
        world_full_quality_unlocked_at TEXT,
        world_full_quality_checkout_session_id TEXT,
        world_full_quality_paid_eur REAL NOT NULL DEFAULT 0,
        pricing_version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `,
  );
  creditAccountTableReady = true;
}

async function ensureCreditAccountForUser(db, userId) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return;
  }
  await ensureMinimalCreditAccountTable(db);
  const now = nowIso();
  await dbRun(
    db,
    `
      INSERT OR IGNORE INTO user_credit_accounts (user_id, account_type, created_at, updated_at)
      VALUES (?, 'account', ?, ?)
    `,
    [safeUserId, now, now],
  );
}

async function ensureNewsletterContactsTable(db) {
  if (newsletterContactsTableReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS newsletter_contacts (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL DEFAULT 'unknown',
        consent_text TEXT,
        consent_version TEXT,
        opted_in_at TEXT NOT NULL,
        last_opt_in_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_newsletter_contacts_last_opt_in ON newsletter_contacts(last_opt_in_at DESC)`);
  newsletterContactsTableReady = true;
}

async function recordNewsletterOptIn(db, email, source = "unknown", options = {}) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail || !normalizedEmail.includes("@")) {
    return;
  }
  await ensureNewsletterContactsTable(db);
  const now = nowIso();
  await dbRun(
    db,
    `
      INSERT INTO newsletter_contacts (id, email, source, consent_text, consent_version, opted_in_at, last_opt_in_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(email) DO UPDATE SET
        source = excluded.source,
        consent_text = excluded.consent_text,
        consent_version = excluded.consent_version,
        last_opt_in_at = excluded.last_opt_in_at
    `,
    [
      crypto.randomUUID(),
      normalizedEmail,
      String(source || "unknown"),
      String(options && options.consentText || "").trim() || null,
      String(options && options.consentVersion || "").trim() || null,
      now,
      now,
    ],
  );
}

async function ensureApiKeyTables(db) {
  if (apiKeyTablesReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS api_key_requests (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        requested_plan TEXT NOT NULL DEFAULT 'free',
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        accept_terms INTEGER NOT NULL DEFAULT 0,
        accept_privacy INTEGER NOT NULL DEFAULT 0,
        opt_in_news INTEGER NOT NULL DEFAULT 0,
        submitted_at_ms INTEGER NOT NULL DEFAULT 0,
        request_ip TEXT,
        request_device_id TEXT,
        created_at TEXT NOT NULL
      )
    `,
  );
  const requestPragma = await db.prepare(`PRAGMA table_info(api_key_requests)`).all();
  const requestRows = Array.isArray(requestPragma && requestPragma.results) ? requestPragma.results : [];
  const requestNames = new Set(requestRows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  for (const statement of [
    !requestNames.has("request_ip") ? `ALTER TABLE api_key_requests ADD COLUMN request_ip TEXT` : "",
    !requestNames.has("accept_terms") ? `ALTER TABLE api_key_requests ADD COLUMN accept_terms INTEGER NOT NULL DEFAULT 0` : "",
    !requestNames.has("accept_privacy") ? `ALTER TABLE api_key_requests ADD COLUMN accept_privacy INTEGER NOT NULL DEFAULT 0` : "",
    !requestNames.has("opt_in_news") ? `ALTER TABLE api_key_requests ADD COLUMN opt_in_news INTEGER NOT NULL DEFAULT 0` : "",
    !requestNames.has("submitted_at_ms") ? `ALTER TABLE api_key_requests ADD COLUMN submitted_at_ms INTEGER NOT NULL DEFAULT 0` : "",
    !requestNames.has("request_device_id") ? `ALTER TABLE api_key_requests ADD COLUMN request_device_id TEXT` : "",
    !requestNames.has("created_at") ? `ALTER TABLE api_key_requests ADD COLUMN created_at TEXT` : "",
  ].filter(Boolean)) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      if (!String(error && error.message || "").toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_api_key_requests_email_created ON api_key_requests(email, created_at DESC)`);
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        key_hash TEXT NOT NULL UNIQUE,
        key_prefix TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        plan_code TEXT NOT NULL DEFAULT 'free',
        expires_at TEXT,
        issued_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT
      )
    `,
  );
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_api_keys_user_status ON api_keys(user_id, status, issued_at DESC)`);
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS api_key_device_activity (
        id TEXT PRIMARY KEY,
        api_key_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        last_seen_unix INTEGER NOT NULL,
        last_ip TEXT,
        last_country TEXT
      )
    `,
  );
  await dbRun(db, `CREATE UNIQUE INDEX IF NOT EXISTS idx_api_key_device_activity_unique ON api_key_device_activity(api_key_id, device_id)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_api_key_device_activity_user_seen ON api_key_device_activity(user_id, last_seen_unix DESC)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_api_key_device_activity_user_device ON api_key_device_activity(user_id, device_id)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_api_key_device_activity_seen ON api_key_device_activity(last_seen_unix DESC)`);
  apiKeyTablesReady = true;
}

async function ensureRefreshSessionColumns(db) {
  if (refreshSessionColumnsReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS refresh_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        refresh_token_hash TEXT NOT NULL UNIQUE,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        created_at TEXT NOT NULL,
        auth_method TEXT,
        api_key_id TEXT,
        device_id TEXT
      )
    `,
  );
  const pragma = await db.prepare(`PRAGMA table_info(refresh_sessions)`).all();
  const rows = Array.isArray(pragma && pragma.results) ? pragma.results : [];
  const names = new Set(rows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  for (const statement of [
    !names.has("auth_method") ? `ALTER TABLE refresh_sessions ADD COLUMN auth_method TEXT` : "",
    !names.has("api_key_id") ? `ALTER TABLE refresh_sessions ADD COLUMN api_key_id TEXT` : "",
    !names.has("device_id") ? `ALTER TABLE refresh_sessions ADD COLUMN device_id TEXT` : "",
  ].filter(Boolean)) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      if (!String(error && error.message || "").toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  refreshSessionColumnsReady = true;
}

function fixedInternalPlanForEmail(email) {
  return FIXED_INTERNAL_TEST_PLAN_BY_EMAIL[normalizeEmail(email)] || "";
}

function resolveFixedInternalPlanForEmail(email, requestedPlan = PLAN_CODE_FREE) {
  const fixedPlan = fixedInternalPlanForEmail(email);
  if (fixedPlan) {
    return fixedPlan;
  }
  return normalizeTierCodeStrict(requestedPlan);
}

async function findUserByEmail(db, email) {
  await ensureUserQualityAccessColumns(db);
  return dbGet(
    db,
    `
      SELECT id, email, status, preview_fair_usage_hold_at, preview_fair_usage_hold_reason,
             preview_fair_usage_hold_details_json, created_at, last_login_at
      FROM users
      WHERE email = ?
      LIMIT 1
    `,
    [normalizeEmail(email)],
  );
}

async function findUserById(db, userId) {
  await ensureUserQualityAccessColumns(db);
  return dbGet(
    db,
    `
      SELECT id, email, status, preview_fair_usage_hold_at, preview_fair_usage_hold_reason,
             preview_fair_usage_hold_details_json, created_at, last_login_at
      FROM users
      WHERE id = ?
      LIMIT 1
    `,
    [String(userId || "").trim()],
  );
}

async function sendNewUserLoginAlert(env, details = {}) {
  const to = String(env.SECURITY_ALERT_EMAIL || "").trim();
  const apiKey = String(env.EMAIL_API_KEY || "").trim();
  if (!to || !apiKey) {
    return;
  }
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const email = normalizeEmail(details.email || "");
  const source = String(details.source || "unknown").trim() || "unknown";
  const createdAt = String(details.createdAt || nowIso()).trim();
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject: `New Planetka account access: ${email || "unknown"}`,
      text: [`email=${email || "unknown"}`, `source=${source}`, `created_at=${createdAt}`].join("\n"),
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`resend_error_${response.status}_${body}`);
  }
}

async function upsertUserByEmail(db, email, status = PLAN_CODE_FREE, options = {}, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  await ensureUserConsentColumns(db);
  await ensureUserQualityAccessColumns(db);
  const requestedStatus = resolveFixedInternalPlanForEmail(normalizedEmail, status);
  if (!requestedStatus) {
    throw new Error("invalid_plan_code");
  }
  let user = await findUserByEmail(db, normalizedEmail);
  if (user) {
    const currentStatus = String(user.status || "").trim().toLowerCase();
    if (!isBlockedStatus(currentStatus) && !normalizeTierCodeStrict(currentStatus)) {
      throw new Error("invalid_user_status");
    }
    const termsAcceptedAt = String(options.termsAcceptedAt || "").trim();
    const privacyAcceptedAt = String(options.privacyAcceptedAt || "").trim();
    const termsVersion = String(options.termsVersion || "").trim();
    const privacyVersion = String(options.privacyVersion || "").trim();
    await dbRun(
      db,
      `
        UPDATE users
        SET
          terms_accepted_at = CASE WHEN ? != '' THEN ? ELSE terms_accepted_at END,
          privacy_accepted_at = CASE WHEN ? != '' THEN ? ELSE privacy_accepted_at END,
          terms_version = CASE WHEN ? != '' THEN ? ELSE terms_version END,
          privacy_version = CASE WHEN ? != '' THEN ? ELSE privacy_version END
        WHERE id = ?
      `,
      [termsAcceptedAt, termsAcceptedAt, privacyAcceptedAt, privacyAcceptedAt, termsVersion, termsVersion, privacyVersion, privacyVersion, user.id],
    );
    await ensureCreditAccountForUser(db, user.id);
    return await findUserById(db, user.id) || user;
  }

  const id = crypto.randomUUID();
  const createdAt = nowIso();
  await dbRun(
    db,
    `
      INSERT INTO users (id, email, status, created_at, terms_accepted_at, privacy_accepted_at, terms_version, privacy_version)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      id,
      normalizedEmail,
      requestedStatus,
      createdAt,
      options.termsAcceptedAt ? String(options.termsAcceptedAt) : null,
      options.privacyAcceptedAt ? String(options.privacyAcceptedAt) : null,
      options.termsVersion ? String(options.termsVersion) : null,
      options.privacyVersion ? String(options.privacyVersion) : null,
    ],
  );
  await ensureCreditAccountForUser(db, id);
  if (!parseBooleanFlag(options.suppressNewUserAlert)) {
    try {
      await sendNewUserLoginAlert(env, {
        email: normalizedEmail,
        source: String(options.signupSource || options.source || "unknown").trim() || "unknown",
        planCode: requestedStatus,
        createdAt,
      });
    } catch (error) {
      console.warn("auth_worker.new_user_alert_email_failed", String(error && error.message || "new_user_alert_email_failed"));
    }
  }
  return findUserByEmail(db, normalizedEmail);
}

async function enforceUserPlanPolicy(db, user, env = {}) {
  void db;
  void env;
  if (!user || !user.id || isBlockedStatus(user.status)) {
    return user;
  }
  const currentStatus = normalizeTierCodeStrict(user.status);
  if (!currentStatus) {
    throw new Error("invalid_user_status");
  }
  return { ...user, status: currentStatus };
}

async function resolveUserQualityAccessState(db, user, env = {}) {
  void db;
  void env;
  const storedPlanCode = normalizeTierCodeStrict(user && user.status);
  if (!user || !user.id) {
    return { storedPlanCode: PLAN_CODE_FREE, qualityAccessPlanCode: PLAN_CODE_FREE };
  }
  if (!storedPlanCode && !isBlockedStatus(user && user.status)) {
    throw new Error("invalid_user_status");
  }
  return { storedPlanCode: storedPlanCode || "", qualityAccessPlanCode: storedPlanCode || "" };
}

function getPreviewFairUsageHoldForUserFromRow(user) {
  if (!user || !user.preview_fair_usage_hold_at) {
    return { held: false };
  }
  let details = null;
  const detailsRaw = String(user.preview_fair_usage_hold_details_json || "").trim();
  if (detailsRaw) {
    try {
      details = JSON.parse(detailsRaw);
    } catch (_error) {
      details = null;
    }
  }
  return {
    held: true,
    held_at: String(user.preview_fair_usage_hold_at || ""),
    reason: String(user.preview_fair_usage_hold_reason || ""),
    details,
  };
}

async function buildAccountState(db, user, env) {
  const qualityAccess = await resolveUserQualityAccessState(db, user, env);
  const storedPlanCode = normalizeTierCodeStrict(qualityAccess.storedPlanCode);
  if (!storedPlanCode) {
    throw new Error("invalid_user_status");
  }
  return {
    planCode: storedPlanCode,
    storedPlanCode,
    accountTier: storedPlanCode,
    storedAccountTier: storedPlanCode,
    qualityAccessPlanCode: qualityAccess.qualityAccessPlanCode,
    upgradeUrl: String(env.UPGRADE_URL || DEFAULT_UPGRADE_URL).trim() || DEFAULT_UPGRADE_URL,
    contactUrl: normalizeContactUrl(env.PLANETKA_CONTACT_URL || DEFAULT_CONTACT_URL),
    previewFairUsageHold: getPreviewFairUsageHoldForUserFromRow(user),
  };
}

function serializeAccountState(state) {
  const safeState = state || {};
  const planCode = normalizeTierCodeStrict(safeState.planCode);
  const storedPlanCode = normalizeTierCodeStrict(safeState.storedPlanCode);
  const storedTier = normalizeTierCodeStrict(safeState.storedAccountTier || storedPlanCode);
  const tier = normalizeTierCodeStrict(safeState.accountTier || planCode || storedPlanCode);
  const qualityAccessPlanCode = normalizeTierCodeStrict(safeState.qualityAccessPlanCode);
  return {
    plan: { code: planCode || "" },
    plan_code: planCode || "",
    account_tier: tier || "",
    stored_plan_code: storedPlanCode || "",
    stored_account_tier: storedTier || "",
    quality_access_plan_code: qualityAccessPlanCode || "",
    upgrade_url: safeState.upgradeUrl,
    contact_url: safeState.contactUrl,
    preview_fair_usage_hold: safeState.previewFairUsageHold || { held: false },
    previewFairUsageHold: safeState.previewFairUsageHold || { held: false },
  };
}

async function sendApiKeyActivationEmail(env, email, token) {
  const apiKey = requireSecret(env, "EMAIL_API_KEY");
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const apiBaseUrl = String(env.API_BASE_URL || "https://api.planetka.io").trim().replace(/\/+$/, "");
  const activationUrl = `${apiBaseUrl}/api-key/activate?token=${encodeURIComponent(token)}`;
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [email],
      subject: "Your Planetka account access link",
      text: [
        "Planetka account access request received.",
        "",
        "Open this activation link to generate your access key:",
        activationUrl,
        "",
        "The link expires in 30 minutes.",
      ].join("\n"),
      html: `
        <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
          <h2 style="margin-bottom: 16px;">Activate your Planetka account access</h2>
          <p>Use the button below to generate your access key for Blender.</p>
          <p style="margin: 24px 0;">
            <a href="${activationUrl}" style="background:#111827;color:#ffffff;padding:12px 18px;text-decoration:none;border-radius:8px;display:inline-block;">
              Activate Account Access
            </a>
          </p>
          <p>If the button does not work, open this link:</p>
          <p><a href="${activationUrl}">${activationUrl}</a></p>
          <p>This link expires in 30 minutes.</p>
        </div>
      `,
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`resend_error_${response.status}_${body}`);
  }
}

async function sendApiKeyIssuedEmail(env, email, apiKeyValue, planCode, expiresAt = "") {
  const apiKey = requireSecret(env, "EMAIL_API_KEY");
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const safePlan = normalizeRequestedPlan(planCode);
  const displayPlan = planDisplayName(safePlan);
  const accessSummary = planAccessSummary(safePlan);
  void expiresAt;
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [email],
      subject: "Your Planetka account access key",
      text: [
        "Your Planetka account access key is ready.",
        "",
        `Access: ${displayPlan}`,
        accessSummary,
        "",
        "Access key:",
        apiKeyValue,
        "",
        "Paste this key in Blender > Planetka > Account.",
      ].join("\n"),
      html: `
        <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
          <h2 style="margin-bottom: 16px;">Your Planetka account access key</h2>
          <p><strong>Access:</strong> ${escapeHtml(displayPlan)}</p>
          <p>${escapeHtml(accessSummary)}</p>
          <p style="margin: 16px 0;">Paste this access key in Blender &rarr; Planetka &rarr; Account:</p>
          <pre style="padding:12px;border-radius:8px;background:#111827;color:#e5e7eb;overflow:auto;">${escapeHtml(apiKeyValue)}</pre>
        </div>
      `,
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`resend_error_${response.status}_${body}`);
  }
}

async function revokeOtherActiveApiKeysForUser(db, userId, keepApiKeyId = "", reason = "superseded") {
  await ensureApiKeyTables(db);
  await ensureRefreshSessionColumns(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return 0;
  }
  const safeKeepApiKeyId = String(keepApiKeyId || "").trim();
  const activeRows = await dbAll(db, `SELECT id FROM api_keys WHERE user_id = ? AND status = 'active'`, [safeUserId]);
  const idsToRevoke = activeRows
    .map((row) => String(row && row.id || "").trim())
    .filter((id) => Boolean(id) && id !== safeKeepApiKeyId);
  if (!idsToRevoke.length) {
    return 0;
  }
  const revokedAt = nowIso();
  for (const apiKeyId of idsToRevoke) {
    await dbRun(db, `UPDATE api_keys SET status = 'revoked', revoked_at = ? WHERE id = ?`, [revokedAt, apiKeyId]);
    await dbRun(db, `UPDATE refresh_sessions SET revoked_at = ? WHERE api_key_id = ? AND (revoked_at IS NULL OR revoked_at = '')`, [revokedAt, apiKeyId]);
  }
  console.log("auth_worker.api_key.revoke_other_active", JSON.stringify({ user_id: safeUserId, keep_api_key_id: safeKeepApiKeyId, revoked_count: idsToRevoke.length, reason }));
  return idsToRevoke.length;
}

async function enforceSingleActiveFreeApiKey(db, userId, preferredApiKeyId = "") {
  await ensureApiKeyTables(db);
  const safeUserId = String(userId || "").trim();
  const safePreferredApiKeyId = String(preferredApiKeyId || "").trim();
  if (!safeUserId) {
    return { allowed: true, keepApiKeyId: "", revokedCount: 0 };
  }
  const activeRows = await dbAll(
    db,
    `SELECT id FROM api_keys WHERE user_id = ? AND status = 'active' ORDER BY issued_at DESC, id DESC`,
    [safeUserId],
  );
  if (!Array.isArray(activeRows) || activeRows.length === 0) {
    return { allowed: true, keepApiKeyId: "", revokedCount: 0 };
  }
  const keepApiKeyId = String(activeRows[0] && activeRows[0].id || "").trim();
  if (!keepApiKeyId) {
    return { allowed: true, keepApiKeyId: "", revokedCount: 0 };
  }
  const revokedCount = await revokeOtherActiveApiKeysForUser(db, safeUserId, keepApiKeyId, "single_active_free_key_reconciliation");
  return {
    allowed: !safePreferredApiKeyId || safePreferredApiKeyId === keepApiKeyId,
    keepApiKeyId,
    revokedCount,
  };
}

function authContextCacheTtlMs(env = {}) {
  return Math.min(
    3600,
    Math.max(0, parseRateLimitInteger(env.AUTH_CONTEXT_CACHE_TTL_SECONDS, DEFAULT_AUTH_CONTEXT_CACHE_TTL_SECONDS)),
  ) * 1000;
}

function authContextCacheMaxEntries(env = {}) {
  return Math.min(
    20000,
    Math.max(64, parseRateLimitInteger(env.AUTH_CONTEXT_CACHE_MAX_ENTRIES, DEFAULT_AUTH_CONTEXT_CACHE_MAX_ENTRIES)),
  );
}

function authContextCacheGet(key, env = {}) {
  const safeKey = String(key || "").trim();
  if (!safeKey) {
    return null;
  }
  const ttlMs = authContextCacheTtlMs(env);
  if (ttlMs <= 0) {
    return null;
  }
  const entry = authContextCache.get(safeKey);
  if (!entry || !Number.isFinite(entry.expiresAtMs) || entry.expiresAtMs <= Date.now()) {
    authContextCache.delete(safeKey);
    return null;
  }
  const accessExp = Number(entry && entry.value && entry.value.access && entry.value.access.exp);
  if (Number.isFinite(accessExp) && accessExp <= Math.floor(Date.now() / 1000)) {
    authContextCache.delete(safeKey);
    return null;
  }
  return entry.value;
}

function authContextCacheSet(key, value, env = {}) {
  const safeKey = String(key || "").trim();
  if (!safeKey) {
    return;
  }
  const ttlMs = authContextCacheTtlMs(env);
  if (ttlMs <= 0) {
    return;
  }
  const maxEntries = authContextCacheMaxEntries(env);
  while (authContextCache.size >= maxEntries) {
    const oldestKey = authContextCache.keys().next().value;
    if (!oldestKey) {
      break;
    }
    authContextCache.delete(oldestKey);
  }
  authContextCache.set(safeKey, { expiresAtMs: Date.now() + ttlMs, value });
}


function parseAdminEmailSet(env) {
  return parseCsvEmailSet(env.ANALYTICS_ADMIN_EMAILS, DEFAULT_ANALYTICS_ADMIN_EMAILS);
}

function resolveAdminLoginEmail(env) {
  const configured = normalizeEmail(env.ADMIN_LOGIN_EMAIL || DEFAULT_ADMIN_LOGIN_EMAIL);
  const adminSet = parseAdminEmailSet(env);
  if (configured && configured.includes("@")) {
    return adminSet.has(configured) ? configured : "";
  }
  for (const email of adminSet) {
    if (email && email.includes("@")) return email;
  }
  return "";
}

function resolveAdminLoginEmailFromBody(env, requestedEmail) {
  const adminSet = parseAdminEmailSet(env);
  const preferred = normalizeEmail(requestedEmail || "");
  if (preferred && preferred.includes("@") && adminSet.has(preferred)) {
    return preferred;
  }
  return resolveAdminLoginEmail(env);
}

function secureStringEquals(leftValue, rightValue) {
  const left = encoder.encode(String(leftValue || ""));
  const right = encoder.encode(String(rightValue || ""));
  const maxLength = Math.max(left.length, right.length);
  let diff = left.length ^ right.length;
  for (let index = 0; index < maxLength; index += 1) {
    const leftByte = index < left.length ? left[index] : 0;
    const rightByte = index < right.length ? right[index] : 0;
    diff |= leftByte ^ rightByte;
  }
  return diff === 0;
}

async function verifyAdminDashboardPassword(env, submittedPassword) {
  const provided = String(submittedPassword || "");
  const expectedHash = String(env.ADMIN_DASHBOARD_PASSWORD_HASH || "").trim().toLowerCase();
  const expectedPlain = String(env.ADMIN_DASHBOARD_PASSWORD || "");
  if (expectedHash) {
    const submittedHash = (await sha256Hex(provided)).toLowerCase();
    return secureStringEquals(submittedHash, expectedHash);
  }
  if (expectedPlain) {
    return secureStringEquals(provided, expectedPlain);
  }
  throw new Error("missing_admin_dashboard_password");
}

function isAnalyticsAdmin(user, env) {
  return Boolean(user && user.email && parseAdminEmailSet(env).has(normalizeEmail(user.email)));
}

function isPrimaryAnalyticsAdmin(user, env) {
  const primary = normalizeEmail(env.ANALYTICS_PRIMARY_ADMIN_EMAIL || DEFAULT_ADMIN_LOGIN_EMAIL);
  return Boolean(primary && user && normalizeEmail(user.email) === primary);
}

const authSessionDepsBase = {
  requireDb,
  parseBooleanFlag,
  authContextCacheGet,
  authContextCacheSet,
  verifyJwt,
  requireSecret,
  normalizeDeviceId,
  normalizeTierCodeStrict,
  findUserById,
  isBlockedStatus,
  blockedAccountResponse,
  enforceUserPlanPolicy,
  resolveUserQualityAccessState,
  isAnalyticsAdmin,
  isPrimaryAnalyticsAdmin,
  json,
};

const readBearerUser = (request, env) => readBearerUserRoute(request, env, authSessionDeps);
const requireAuthenticatedUserContext = (request, env, options = {}) => requireAuthenticatedUserContextRoute(request, env, options, authSessionDeps);

const authCoreDeps = {
  PLAN_CODE_FREE,
  DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS,
  DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS,
  requireSecret,
  dbAll,
  dbGet,
  dbRun,
  ensureApiKeyTables,
  ensureRefreshSessionColumns,
  normalizeRequestedPlan,
  resolvePolicyPlanCode,
  normalizeDeviceId,
  parsePositiveNumber,
  parseRateLimitInteger,
  isDeviceLimitExemptEmail,
  requestClientIp,
  requestCountry,
  nowIso,
  addDaysIso,
  randomToken,
  sha256Hex,
  signJwt,
  verifyJwt,
  normalizeQualityMode,
  isQualityModeAllowedForPlan,
  qualityModeNotAllowedMessage,
  json,
  authContextCacheGet,
  authContextCacheSet,
  enforceSingleActiveFreeApiKey,
  computeApiKeyExpiryIso,
};

const authCore = createAuthCore(authCoreDeps);

const authSessionDeps = {
  ...authSessionDepsBase,
  isApiKeyUsableById: authCore.isApiKeyUsableById,
  enforceApiKeyDeviceLimit: authCore.enforceApiKeyDeviceLimit,
};

const authApiKeyDeps = {
  PLAN_CODE_FREE,
  DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS,
  DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS,
  DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS,
  DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_WINDOW_SECONDS,
  DEFAULT_LEGAL_VERSION,
  genericAuthStartResponse: (env) => authCore.genericAuthStartResponse(env),
  requireDb,
  ensureApiKeyTables,
  ensureRateLimitsTable,
  parseJson,
  normalizeEmail,
  normalizeDeviceId,
  normalizeTierCodeStrict,
  normalizeRequestedPlan,
  parseBooleanFlag,
  parseNonNegativeInteger,
  parsePositiveNumber,
  parseRateLimitInteger,
  requestClientIp,
  findActiveHardBlock,
  blockedAccountResponse,
  consumeRateLimitWindow,
  rateLimitedResponse,
  findUserByEmail,
  resolvePlanCode,
  isBlockedStatus,
  enforceUserPlanPolicy,
  enforceApiKeyIssueDeviceLimit: authCore.enforceApiKeyIssueDeviceLimit,
  json,
  upsertUserByEmail,
  recordNewsletterOptIn,
  randomToken,
  sha256Hex,
  dbRun,
  dbGet,
  nowIso,
  addMinutesIso,
  addDaysIso,
  sendApiKeyActivationEmail,
  issueApiKeyForUser: authCore.issueApiKeyForUser,
  sendApiKeyIssuedEmail,
  publicErrorCode,
  isValidApiKey,
  findActiveApiKeyRecord: authCore.findActiveApiKeyRecord,
  enforceSingleActiveFreeApiKey,
  enforceApiKeyDeviceLimit: authCore.enforceApiKeyDeviceLimit,
  buildAccountState,
  createAccessToken: authCore.createAccessToken,
  createRefreshSession: authCore.createRefreshSession,
  maskApiKey,
  serializeAccountState,
};

const authApiKeyHandlers = createAuthApiKeyHandlers(authApiKeyDeps);

const authSessionRouteDeps = {
  DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS,
  requireDb,
  ensureRateLimitsTable,
  requestClientIp,
  requestCountry,
  consumeRateLimitWindow,
  parseRateLimitInteger,
  rateLimitedResponse,
  logAuthRefreshEvent,
  parseJson,
  sha256Hex,
  dbGet,
  dbRun,
  dbMetaChanges,
  isBlockedStatus,
  blockedAccountResponse,
  isApiKeyUsableById: authCore.isApiKeyUsableById,
  normalizeTierCodeStrict,
  enforceUserPlanPolicy,
  nowIso,
  buildAccountState,
  createAccessToken: authCore.createAccessToken,
  createRefreshSession: authCore.createRefreshSession,
  normalizeEmail,
  json,
  serializeAccountState,
  ensureRefreshSessionColumns,
  ensureApiKeyTables,
  normalizeDeviceId,
  readBearerUser,
  requireAuthenticatedUserContext,
};

const authSessionRouteHandlers = createAuthSessionRouteHandlers(authSessionRouteDeps);

const apiKeyPageDeps = {
  PLAN_CODE_FREE,
  DEFAULT_CONTACT_URL,
  DEFAULT_PRIVACY_URL,
  DEFAULT_TERMS_URL,
  activateApiKeyFromToken: authApiKeyHandlers.activateApiKeyFromToken,
  corsHeaders,
  escapeHtml,
  html,
  maskApiKey,
  normalizeContactUrl,
  normalizeRequestedPlan,
  parseCsvEmailSet,
  planAccessSummary,
  planDisplayName,
  requireDb,
};

const updateManifestDeps = {
  ADDON_ID,
  DEFAULT_ADDON_UPDATE_MANIFEST_VERSION,
  DEFAULT_ADDON_UPDATE_CHANNEL,
  DEFAULT_ADDON_UPDATE_RELEASE_NOTES_URL,
  DEFAULT_ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS,
  corsHeaders,
  json,
  jsonWithHeaders,
  parseNonNegativeInteger,
  nowIso,
};

function authWorkerHealth(env) {
  return json(
    {
      ok: true,
      service: "planetka-auth",
      api_base_url: env.API_BASE_URL || "https://api.planetka.io",
      db_bound: Boolean(env.DB),
      pricing_isolated: true,
    },
    200,
    env,
  );
}

function optionsResponse(env) {
  return new Response(null, { status: 204, headers: corsHeaders(env) });
}

function notFound(env) {
  return json({ ok: false, error: "not_found" }, 404, env);
}

function methodNotAllowed(env) {
  return json({ ok: false, error: "method_not_allowed" }, 405, env);
}

async function handleAddonReleaseDownload(request, env, path) {
  if (!env || !env.PLANETKA_DATA || typeof env.PLANETKA_DATA.get !== "function") {
    return json({ ok: false, error: "release_storage_unavailable" }, 503, env);
  }
  const fileName = decodeURIComponent(String(path || "").replace(/^\/addon\/releases\//, "")).trim();
  if (!/^Planetka_update_\d+\.\d+\.\d+\.zip$/.test(fileName)) {
    return notFound(env);
  }
  const key = `releases/${fileName}`;
  const object = request.method === "HEAD"
    ? await env.PLANETKA_DATA.head(key)
    : await env.PLANETKA_DATA.get(key);
  if (!object) {
    return notFound(env);
  }
  const headers = new Headers(corsHeaders(env));
  headers.set("Content-Type", "application/zip");
  headers.set("Cache-Control", "public, max-age=300");
  headers.set("Content-Disposition", `attachment; filename="${fileName}"`);
  if (object.size !== undefined && object.size !== null) {
    headers.set("Content-Length", String(object.size));
  }
  if (object.httpEtag) {
    headers.set("ETag", object.httpEtag);
  }
  return new Response(request.method === "HEAD" ? null : object.body, {
    status: 200,
    headers,
  });
}

async function dispatchAuthRequest(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (request.method === "OPTIONS") {
    return optionsResponse(env);
  }
  if (path === "/health") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(env);
    }
    if (request.method === "HEAD") {
      return new Response(null, { status: 200, headers: corsHeaders(env) });
    }
    return authWorkerHealth(env);
  }
  if (path === "/addon/update-manifest") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(env);
    }
    return handleAddonUpdateManifest(request, env, updateManifestDeps);
  }
  if (path.startsWith("/addon/releases/")) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(env);
    }
    return handleAddonReleaseDownload(request, env, path);
  }
  if (path.startsWith("/legal/")) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(env);
    }
    return handleLegalDocumentRequest(request, env, path, updateManifestDeps);
  }
  if (path === "/api-key") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(env);
    }
    return handleApiKeyPage(request, env, apiKeyPageDeps);
  }
  if (path === "/api-key/activate") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(env);
    }
    return handleApiKeyActivatePage(request, env, apiKeyPageDeps);
  }
  if (path === "/auth/api-key/request") {
    if (request.method !== "POST") {
      return methodNotAllowed(env);
    }
    return authApiKeyHandlers.handleApiKeyRequest(request, env);
  }
  if (path === "/auth/api-key/activate") {
    if (request.method !== "POST") {
      return methodNotAllowed(env);
    }
    return authApiKeyHandlers.handleApiKeyActivate(request, env);
  }
  if (path === "/auth/api-key/exchange") {
    if (request.method !== "POST") {
      return methodNotAllowed(env);
    }
    return authApiKeyHandlers.handleApiKeyExchange(request, env);
  }
  if (path === "/auth/refresh") {
    if (request.method !== "POST") {
      return methodNotAllowed(env);
    }
    return authSessionRouteHandlers.handleAuthRefresh(request, env);
  }
  if (path === "/auth/logout") {
    if (request.method !== "POST") {
      return methodNotAllowed(env);
    }
    return authSessionRouteHandlers.handleAuthLogout(request, env);
  }
  if (path === "/me") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(env);
    }
    if (request.method === "HEAD") {
      return new Response(null, { status: 200, headers: corsHeaders(env) });
    }
    return authSessionRouteHandlers.handleMe(request, env);
  }
  return notFound(env);
}

function clampNonNegativeInt(value) {
  return Math.max(0, parseNonNegativeInteger(value, 0));
}

function startOfHourUnix(epochSeconds) {
  const seconds = clampNonNegativeInt(epochSeconds);
  return seconds - (seconds % 3600);
}

function startOfDayUnix(epochSeconds) {
  const seconds = clampNonNegativeInt(epochSeconds);
  return seconds - (seconds % 86400);
}

function startOfWeekUnix(epochSeconds) {
  const seconds = clampNonNegativeInt(epochSeconds);
  const day = Math.floor(seconds / 86400);
  const daysSinceMonday = (day + 3) % 7;
  return (day - daysSinceMonday) * 86400;
}

function monthStartUnix(epochSeconds) {
  const date = new Date(clampNonNegativeInt(epochSeconds) * 1000);
  return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1) / 1000);
}

function monthStartIso(epochSeconds) {
  return new Date(monthStartUnix(epochSeconds) * 1000).toISOString();
}

function monthKeyFromUnix(epochSeconds) {
  const date = new Date(clampNonNegativeInt(epochSeconds) * 1000);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

async function countRowsFromQuery(db, sql, bindings = []) {
  const row = await dbGet(db, `SELECT COUNT(*) AS count FROM (${sql})`, bindings);
  return clampNonNegativeInt(row && row.count);
}

function estimateR2MonthlyCostUsd(env, monthlyClassBOps) {
  const storageGb = parsePositiveNumber(env.R2_ESTIMATED_STORAGE_GB, DEFAULT_R2_ESTIMATED_STORAGE_GB);
  const storagePrice = parsePositiveNumber(env.R2_STORAGE_PRICE_PER_GB_MONTH_USD, DEFAULT_R2_STORAGE_PRICE_PER_GB_MONTH_USD);
  const freeStorage = parseNonNegativeInteger(env.R2_STORAGE_FREE_GB_MONTH, DEFAULT_R2_STORAGE_FREE_GB_MONTH);
  const classBOps = clampNonNegativeInt(monthlyClassBOps);
  const freeClassB = parseNonNegativeInteger(env.R2_CLASS_B_FREE_OPS_PER_MONTH, DEFAULT_R2_CLASS_B_FREE_OPS_PER_MONTH);
  const classBPrice = parsePositiveNumber(env.R2_CLASS_B_PRICE_PER_MILLION_USD, DEFAULT_R2_CLASS_B_PRICE_PER_MILLION_USD);
  const storageCost = Math.max(0, storageGb - freeStorage) * storagePrice;
  const classBCost = Math.max(0, classBOps - freeClassB) * classBPrice / 1000000;
  return {
    storage_usd: storageCost,
    class_b_usd: classBCost,
    estimated_total_usd: storageCost + classBCost,
    monthly_class_b_ops: classBOps,
  };
}

async function ensureCreditTables(db) {
  await ensureMinimalCreditAccountTable(db);
  await dbRun(db, `CREATE TABLE IF NOT EXISTS user_tile_entitlements (
    user_id TEXT NOT NULL,
    tile_key TEXT NOT NULL,
    quality_mode TEXT NOT NULL DEFAULT 'full',
    credits_spent REAL NOT NULL DEFAULT 0,
    land_km2 REAL NOT NULL DEFAULT 0,
    billable_land_km2 REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'client_pricing',
    unlocked_at TEXT NOT NULL,
    PRIMARY KEY (user_id, tile_key)
  )`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_user_tile_entitlements_user ON user_tile_entitlements(user_id)`);
  await dbRun(db, `CREATE TABLE IF NOT EXISTS user_credit_purchases (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    purchase_type TEXT NOT NULL,
    amount_paid_eur REAL NOT NULL DEFAULT 0,
    gross_eur REAL NOT NULL DEFAULT 0,
    metadata_json TEXT,
    stripe_session_id TEXT,
    created_at TEXT NOT NULL
  )`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_user_credit_purchases_user_created ON user_credit_purchases(user_id, created_at DESC)`);
}

async function ensureTileRequestEventsTable(db) {
  await dbRun(db, `CREATE TABLE IF NOT EXISTS tile_request_events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_at_unix INTEGER NOT NULL,
    user_id TEXT,
    user_email TEXT,
    resolve_id TEXT,
    method TEXT,
    path TEXT,
    folder TEXT,
    file_name TEXT,
    tile_key TEXT,
    quality_mode TEXT,
    status_code INTEGER NOT NULL DEFAULT 0,
    bytes_served INTEGER NOT NULL DEFAULT 0,
    cache_status TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    cf_ray TEXT,
    cf_country TEXT,
    client_ip TEXT,
    error_code TEXT
  )`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_tile_request_events_created_unix ON tile_request_events(created_at_unix DESC)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_tile_request_events_user_created ON tile_request_events(user_id, created_at_unix DESC)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_tile_request_events_quality_created ON tile_request_events(quality_mode, created_at_unix DESC)`);
}

async function ensureTileRequestRollupTables(db) {
  await dbRun(db, `CREATE TABLE IF NOT EXISTS tile_request_rollup_hourly_account (
    bucket_start_unix INTEGER NOT NULL,
    bucket_start TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_email TEXT,
    request_count INTEGER NOT NULL DEFAULT 0,
    bytes_served INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    cache_hit_count INTEGER NOT NULL DEFAULT 0,
    tagged_request_count INTEGER NOT NULL DEFAULT 0,
    last_event_unix INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_start_unix, user_id)
  )`);
  await dbRun(db, `CREATE TABLE IF NOT EXISTS tile_request_rollup_daily_account (
    day_start_unix INTEGER NOT NULL,
    day_start TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_email TEXT,
    request_count INTEGER NOT NULL DEFAULT 0,
    bytes_served INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    cache_hit_count INTEGER NOT NULL DEFAULT 0,
    tagged_request_count INTEGER NOT NULL DEFAULT 0,
    last_event_unix INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day_start_unix, user_id)
  )`);
}

async function ensureMonthlyCostAlertStateTable(db) {
  await dbRun(db, `CREATE TABLE IF NOT EXISTS monthly_cost_alert_state (
    month_key TEXT PRIMARY KEY,
    last_alert_level_usd INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
  )`);
}

async function recordTileRequestEvent(db, payload) {
  await ensureTileRequestEventsTable(db);
  const createdAt = String(payload.created_at || nowIso());
  const createdAtUnix = parseNonNegativeInteger(payload.created_at_unix, Math.floor(Date.now() / 1000));
  await dbRun(db, `INSERT INTO tile_request_events (
    id, created_at, created_at_unix, user_id, user_email, resolve_id, method, path, folder, file_name,
    tile_key, quality_mode, status_code, bytes_served, cache_status, duration_ms, cf_ray, cf_country, client_ip, error_code
  ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, [
    crypto.randomUUID(),
    createdAt,
    createdAtUnix,
    String(payload.user_id || ""),
    normalizeEmail(payload.user_email || ""),
    String(payload.resolve_id || ""),
    String(payload.method || "GET").toUpperCase(),
    String(payload.path || ""),
    String(payload.folder || ""),
    String(payload.file_name || ""),
    String(payload.tile_key || ""),
    normalizeQualityMode(payload.quality_mode || payload.qualityMode || ""),
    parseNonNegativeInteger(payload.status_code, 0),
    clampNonNegativeInt(payload.bytes_served),
    String(payload.cache_status || ""),
    clampNonNegativeInt(payload.duration_ms),
    String(payload.cf_ray || ""),
    String(payload.cf_country || ""),
    String(payload.client_ip || ""),
    String(payload.error_code || ""),
  ]);
}

async function recordPreviewUsageAndMaybeAlert(_db, _env, _payload = {}) {
  // Analytics worker records the raw tile event above. Fair-use action remains disabled here by design.
}

function isTileHotPathMonitoringEnabled(_env = {}) {
  return false;
}

async function maybeSignalTileFarmingActivity(_db, _env, _details = {}) {
  // Tile hot-path enforcement is intentionally not part of the analytics dashboard entrypoint.
}

async function sendOpsAlertEmail(env, subject, lines = []) {
  const apiKey = String(env.EMAIL_API_KEY || "").trim();
  const to = String(env.SECURITY_ALERT_EMAIL || "").trim();
  if (!apiKey || !to) return;
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [to], subject: String(subject || "Planetka alert"), text: Array.isArray(lines) ? lines.join("\n") : String(lines || "") }),
  });
}

async function trackThresholdAlertDb(_db, _eventName, _threshold, _windowSeconds, _payload = {}) {
  return { alerted: false };
}

const ANALYTICS_QUERY_DEPS = {
  ALLOWED_LIVE_TILE_MAP_WINDOW_MINUTES,
  BYTES_PER_GB: 1024 * 1024 * 1024,
  DEFAULT_ADMIN_SUPPORT_MISSING_MANIFEST_KEY,
  DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS,
  DEFAULT_ANALYTICS_REVENUE_EXCLUDED_EMAIL_PATTERNS,
  DEFAULT_ANALYTICS_WINDOW_MINUTES,
  DEFAULT_AUTH_REFRESH_HEALTH_WINDOW_SECONDS,
  DEFAULT_CLOUDFLARE_BILLABLE_CACHE_TTL_SECONDS,
  DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
  DEFAULT_R2_CLASS_A_FREE_OPS_PER_MONTH,
  DEFAULT_R2_CLASS_A_PRICE_PER_MILLION_USD,
  DEFAULT_R2_CLASS_B_FREE_OPS_PER_MONTH,
  DEFAULT_R2_CLASS_B_PRICE_PER_MILLION_USD,
  DEFAULT_R2_ESTIMATED_STORAGE_GB,
  DEFAULT_R2_STORAGE_FREE_GB_MONTH,
  DEFAULT_R2_STORAGE_PRICE_PER_GB_MONTH_USD,
  INTERNAL_TEST_ANALYTICS_EMAIL_PATTERNS,
  MAX_ANALYTICS_WINDOW_MINUTES,
  PLAN_CODE_FREE,
  clampNonNegativeInt,
  countRowsFromQuery,
  dbAll,
  dbGet,
  dbRun,
  ensureCreditTables,
  ensureUserQualityAccessColumns,
  ensureAuthRefreshEventsTable,
  ensureTileRequestEventsTable,
  ensureTileRequestRollupTables,
  estimateR2MonthlyCostUsd,
  monthStartIso,
  monthStartUnix,
  normalizeEmail,
  normalizePlanCode,
  nowIso,
  parseNonNegativeInteger,
  parsePositiveNumber,
  publicErrorMessage: () => "Analytics data is temporarily unavailable.",
  startOfDayUnix,
  startOfHourUnix,
  startOfWeekUnix,
};

const AUTH_SESSION_DEPS = {
  ...authSessionDeps,
  isAnalyticsAdmin,
  isPrimaryAnalyticsAdmin,
};

const requireAnalyticsAdmin = (request, env) => requireAnalyticsAdminRoute(request, env, AUTH_SESSION_DEPS);

const ADMIN_ANALYTICS_DEPS = {
  buildAdminSessionCookie,
  buildAnalyticsUsersSnapshot: (db, env) => buildAnalyticsUsersSnapshot(db, env, ADMIN_ANALYTICS_DEPS),
  collectAnalyticsSnapshot: (db, minutes, planFilter, liveTileMapWindowMinutes, env) =>
    collectAnalyticsSnapshotQuery(db, minutes, planFilter, liveTileMapWindowMinutes, env, ANALYTICS_QUERY_DEPS),
  collectMapServiceBusyHealth: (db) => collectMapServiceBusyHealth(db, WORKER_OVERLOAD_MONITOR_DEPS),
  collectQuoteQueueHealth: (db) => collectQuoteQueueHealthQuery(db, ANALYTICS_QUERY_DEPS),
  collectWorkerOverloadHealth: (db) => collectWorkerOverloadHealth(db, WORKER_OVERLOAD_MONITOR_DEPS),
  corsHeaders,
  DEFAULT_ADMIN_ANALYTICS_TILE_MAP_KEY,
  DEFAULT_ANALYTICS_WINDOW_MINUTES,
  DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
  escapeHtml,
  findUserByEmail,
  findUserById,
  html,
  isAnalyticsSnapshotStale,
  json,
  listRegionProductPricingRows,
  listAnalyticsUsers: (db, env, options = {}) => listAnalyticsUsersQuery(db, env, options, ANALYTICS_QUERY_DEPS),
  loadAnalyticsSnapshot,
  loadAnalyticsUsersSnapshot,
  getRuntimePricingSettings,
  normalizePlanCode,
  nowIso,
  parseAnalyticsUsersSort: (value) => parseAnalyticsUsersSortQuery(value),
  parseAnalyticsUsersSortDirection: (value) => parseAnalyticsUsersSortDirectionQuery(value),
  parseHeavyUserPlanFilter: (value) => parseHeavyUserPlanFilterQuery(value, ANALYTICS_QUERY_DEPS),
  parseNonNegativeInteger,
  PLAN_CODE_FREE,
  publicErrorMessage: (message) => message,
  requireAnalyticsAdmin,
  sanitizeAnalyticsMinutes: (value, fallback = DEFAULT_ANALYTICS_WINDOW_MINUTES) =>
    sanitizeAnalyticsMinutesQuery(value, fallback, ANALYTICS_QUERY_DEPS),
  sanitizeLiveTileMapMinutes: (value, fallback = DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES) =>
    sanitizeLiveTileMapMinutesQuery(value, fallback, ANALYTICS_QUERY_DEPS),
  setRegionProductDiscountOverride,
  setRuntimePricingSettings,
  storeAnalyticsSnapshot,
  dbAll,
  dbGet,
  dbRun,
  requireDb,
  ensureCreditTables,
  BYTES_PER_GB: 1024 * 1024 * 1024,
};

const WORKER_OVERLOAD_MONITOR_DEPS = {
  clampNonNegativeInt,
  dbAll,
  dbGet,
  dbMetaChanges,
  dbRun,
  nowIso,
  parseNonNegativeInteger,
  sendOpsAlertEmail,
};

const ADMIN_SESSION_DEPS = {
  buildAdminSessionClearCookie,
  buildAdminSessionCookie,
  corsHeaders,
  createAccessToken: authCore.createAccessToken,
  DEFAULT_ADMIN_LOGIN_EMAIL,
  enforceUserPlanPolicy,
  ensureRateLimitsTable,
  escapeHtml,
  html,
  isAnalyticsAdmin,
  json,
  jsonWithHeaders,
  normalizeEmail,
  nowIso,
  parseJson,
  parseRateLimitInteger,
  PLAN_CODE_FREE,
  rateLimitedResponse,
  requestClientIp,
  requireAuthenticatedUserContext,
  requireDb,
  resolveAdminLoginEmailFromBody,
  trackThresholdAlertDb,
  upsertUserByEmail,
  verifyAdminDashboardPassword,
  consumeRateLimitWindow,
  DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT,
  DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS,
};

const ADMIN_USER_DEPS = {
  dbAll,
  dbGet,
  dbMetaChanges,
  dbRun,
  ensureAdminHardBlocksTable,
  ensureApiKeyTables,
  ensureCreditTables,
  ensureUserQualityAccessColumns,
  ensureRateLimitsTable,
  ensureRefreshSessionColumns,
  findUserByEmail,
  findUserById,
  invalidateAnalyticsSnapshots,
  issueApiKeyForUser: authCore.issueApiKeyForUser,
  json,
  normalizeDeviceId,
  normalizeEmail,
  normalizePlanCode,
  normalizeRequestedPlan,
  nowIso,
  parseJson,
  parseCsvEmailSet,
  parseBooleanFlag,
  randomToken,
  requestClientIp,
  activateApiKeyFromToken: authApiKeyHandlers.activateApiKeyFromToken,
  corsHeaders,
  escapeHtml,
  html,
  maskApiKey,
  normalizeContactUrl,
  planAccessSummary,
  planDisplayName,
  requireDb,
  requireAnalyticsAdmin,
  sha256Hex,
  upsertUserByEmail,
};

const MAINTENANCE_JOB_DEPS = {
  DEFAULT_ALERT_PROD_403_THRESHOLD,
  DEFAULT_ALERT_PROD_403_WINDOW_SECONDS,
  DEFAULT_ALERT_PROD_429_THRESHOLD,
  DEFAULT_ALERT_PROD_429_WINDOW_SECONDS,
  DEFAULT_ALERT_PROD_COOLDOWN_SECONDS,
  DEFAULT_ALERT_PROD_TILE_ERROR_THRESHOLD,
  DEFAULT_ALERT_PROD_TILE_ERROR_WINDOW_SECONDS,
  DEFAULT_ALERT_PROD_TILE_MISS_THRESHOLD,
  DEFAULT_ALERT_PROD_TILE_MISS_WINDOW_SECONDS,
  DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS,
  DEFAULT_AUTH_REFRESH_EVENT_RETENTION_DAYS,
  DEFAULT_MONTHLY_COST_ALERT_BASE_USD,
  DEFAULT_MONTHLY_COST_ALERT_STEP_USD,
  DEFAULT_REFRESH_SESSION_CLEANUP_RETENTION_DAYS,
  DEFAULT_TILE_EVENT_RETENTION_DAYS,
  DEFAULT_TILE_ROLLUP_RETENTION_DAYS,
  addDaysFromIso: (isoValue, days) => {
    const base = Date.parse(String(isoValue || ""));
    return new Date((Number.isFinite(base) ? base : Date.now()) + (Number(days) * 86400000)).toISOString();
  },
  consumeRateLimitWindow,
  countRowsFromQuery,
  dbGet,
  dbMetaChanges,
  dbRun,
  dbTableExists: async (db, tableName) => Boolean(await dbGet(db, `SELECT name FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1`, [String(tableName || "").trim()])),
  ensureApiKeyTables,
  ensureMonthlyCostAlertStateTable,
  ensureRateLimitsTable,
  ensureTileRequestEventsTable,
  estimateR2MonthlyCostUsd,
  monthKeyFromUnix,
  monthStartUnix,
  nowIso,
  parseNonNegativeInteger,
  parsePositiveNumber,
  parseRateLimitInteger,
  sendOpsAlertEmail,
};

const TILE_EVENT_QUEUE_DEPS = {
  clampNonNegativeInt,
  isTileHotPathMonitoringEnabled,
  maybeSignalTileFarmingActivity,
  nowIso,
  recordPreviewUsageAndMaybeAlert,
  recordTileRequestEvent,
  requireDb,
};

const ADMIN_ROUTE_DEPS = {
  handleAdminAnalyticsData: (request, env) => handleAdminAnalyticsDataRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsPage: (request, env) => handleAdminAnalyticsPageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsProductsPage: (request, env) => handleAdminAnalyticsProductsPageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsTileMapImage: (request, env) => handleAdminAnalyticsTileMapImageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsUserPage: (request, env) => handleAdminAnalyticsUserPageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsUsersPage: (request, env) => handleAdminAnalyticsUsersPageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminSetProductDiscount: (request, env) => handleAdminSetProductDiscountRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminSetPricingSettings: (request, env) => handleAdminSetPricingSettingsRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminLoginPage: (request, env) => handleAdminLoginPageRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminPasswordLogin: (request, env) => handleAdminPasswordLoginRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminSessionLogout: (request, env) => handleAdminSessionLogoutRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminSessionStart: (request, env) => handleAdminSessionStartRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminSessionStartPage: (request, env) => handleAdminSessionStartPageRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminUserBlock: (request, env) => handleAdminUserBlockRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserHardBlock: (request, env) => handleAdminUserHardBlockRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserReleasePreviewHold: (request, env) => handleAdminUserReleasePreviewHoldRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserSetPreviewHold: (request, env) => handleAdminUserSetPreviewHoldRoute(request, env, ADMIN_USER_DEPS),
  handleAdminQaAuthReset: (request, env) => handleAdminQaAuthResetRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserSetPlan: (request, env) => handleAdminUserSetPlanRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserUnblock: (request, env) => handleAdminUserUnblockRoute(request, env, ADMIN_USER_DEPS),
};

function analyticsWorkerHealth(env) {
  return json({ ok: true, service: "planetka-analytics", commerce_dispatcher: false, db_bound: Boolean(env.DB) }, 200, env);
}

async function dispatchAnalyticsRequest(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (request.method === "OPTIONS") {
    return optionsResponse(env);
  }
  if (path === "/health") {
    if (request.method === "HEAD") return new Response(null, { status: 200, headers: corsHeaders(env) });
    return analyticsWorkerHealth(env);
  }
  if (isAdminRoutePath(path)) {
    if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
      return json({ ok: false, error: "query_token_not_allowed" }, 400, env);
    }
    const response = await dispatchAdminRoute(request, env, path, ADMIN_ROUTE_DEPS);
    return response || notFound(env);
  }
  return notFound(env);
}

export default {
  async fetch(request, env) {
    try {
      return await dispatchAnalyticsRequest(request, env);
    } catch (error) {
      console.error("analytics_worker.unhandled", String(error && error.message || "analytics_worker_error"));
      return json({ ok: false, error: "analytics_worker_error" }, 500, env);
    }
  },
  async scheduled(controller, env, ctx) {
    const runStartedAt = nowIso();
    ctx.waitUntil((async () => {
      const db = requireDb(env);
      const cron = String(controller && controller.cron || "").trim();
      const overloadMonitor = await runWorkerOverloadMonitor(db, env, WORKER_OVERLOAD_MONITOR_DEPS);
      let maintenance = null;
      let analyticsSnapshotSummary = null;
      let analyticsUsersSnapshot = null;
      const scheduledTime = Number(controller && controller.scheduledTime || Date.now());
      const scheduledDate = new Date(Number.isFinite(scheduledTime) ? scheduledTime : Date.now());
      if (scheduledDate.getUTCMinutes() === 0) {
        maintenance = await runScheduledMaintenanceJobs(db, env, runStartedAt, MAINTENANCE_JOB_DEPS);
        analyticsSnapshotSummary = await buildAnalyticsSnapshotMatrix(db, env, ADMIN_ANALYTICS_DEPS);
        analyticsUsersSnapshot = await buildAnalyticsUsersSnapshot(db, env, ADMIN_ANALYTICS_DEPS);
      }
      console.log("analytics_worker.scheduled.complete", JSON.stringify({
        scheduled_at: scheduledDate.toISOString(),
        cron,
        overload_monitor: overloadMonitor,
        maintenance,
        analytics_snapshot_summary: analyticsSnapshotSummary,
        analytics_users_snapshot: analyticsUsersSnapshot,
      }));
    })());
  },
  async queue(batch, env, ctx) {
    void ctx;
    if (String(batch && batch.queue || "") !== "planetka-tile-events") return;
    await handleTileEventQueueBatch(batch, env, TILE_EVENT_QUEUE_DEPS);
  },
};
