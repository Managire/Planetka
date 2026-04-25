import {
  corsHeaders,
  html,
  json,
  jsonWithHeaders,
  publicErrorCode,
  publicErrorMessage,
} from "./worker/responses.js";
import {
  isBetaUnrestrictedAccessEnabled,
  parseBooleanFlag,
  parseNonNegativeInteger,
  parsePositiveNumber,
} from "./worker/env.js";
import {
  PLAN_CODE_PLANETKA,
  PLAN_CODE_PLANETKA_FREE,
  PLAN_CODE_PLANETKA_PRO,
  PLAN_CODE_PLANETKA_STUDIO,
  accountTierForPlanCode,
  commercialUseAllowed,
  evaluateStripePlanPurchaseGuard,
  isBlockedStatus,
  isDeviceLimitExemptEmail,
  isPaidRequestedPlan,
  isQualityModeAllowedForPlan,
  normalizePlanCode,
  normalizeQualityMode,
  normalizeRequestedPlan,
  normalizeUserStatus,
  parseCsvEmailSet,
  planAccessSummary,
  planDisplayName,
  qualityModeNotAllowedMessage,
  resolvePlanCode,
  resolvePlanPriority,
  resolvePolicyPlanCode,
} from "./worker/entitlements.js";
import {
  dispatchAdminRoute,
  isAdminRoutePath,
} from "./worker/admin_routes.js";
import {
  buildAdminSessionClearCookie,
  buildAdminSessionCookie,
  readBearerToken,
  requireAnalyticsAdmin,
  requireAuthenticatedUserContext,
} from "./worker/auth_session.js";
import {
  handleAdminAnalyticsData as handleAdminAnalyticsDataRoute,
  handleAdminAnalyticsPage as handleAdminAnalyticsPageRoute,
  handleAdminAnalyticsTileMapImage as handleAdminAnalyticsTileMapImageRoute,
  handleAdminAnalyticsUsersPage as handleAdminAnalyticsUsersPageRoute,
} from "./worker/admin_analytics_handlers.js";
import {
  handleAdminLoginPage as handleAdminLoginPageRoute,
  handleAdminPasswordLogin as handleAdminPasswordLoginRoute,
  handleAdminSessionLogout as handleAdminSessionLogoutRoute,
  handleAdminSessionStart as handleAdminSessionStartRoute,
  handleAdminSessionStartPage as handleAdminSessionStartPageRoute,
} from "./worker/admin_session_handlers.js";
import {
  handleAdminUserBlock as handleAdminUserBlockRoute,
  handleAdminUserHardBlock as handleAdminUserHardBlockRoute,
  handleAdminUserSetPlan as handleAdminUserSetPlanRoute,
  handleAdminUserUnblock as handleAdminUserUnblockRoute,
} from "./worker/admin_user_handlers.js";
import {
  handleStripeWebhook as handleStripeWebhookRoute,
} from "./worker/billing_handlers.js";
import {
  handleAddonUpdateManifest as handleAddonUpdateManifestRoute,
  handleHealth as handleHealthRoute,
  handleLegalDocumentRequest as handleLegalDocumentRequestRoute,
  handleSupportBugReport as handleSupportBugReportRoute,
} from "./worker/public_misc_handlers.js";
import {
  handleApiKeyActivatePage as handleApiKeyActivatePageRoute,
  handleApiKeyPage as handleApiKeyPageRoute,
} from "./worker/api_key_page_handlers.js";
import {
  handleTileRequest as handleTileRequestRoute,
  handleTileSessionStart as handleTileSessionStartRoute,
} from "./worker/tile_routes.js";
const encoder = new TextEncoder();
const ADDON_ID = "planetka";
const BYTES_PER_GB = 1024 * 1024 * 1024;
const DEFAULT_UPGRADE_URL = "https://www.planetka.io/blender/pricing";
const DEFAULT_CONTACT_URL = "https://www.planetka.io/contact-me";
const DEFAULT_ADMIN_ANALYTICS_TILE_MAP_KEY = "planetka-assets/Admin/world_map_720x360.jpg";
const DEFAULT_ADMIN_SUPPORT_MISSING_MANIFEST_KEY = "planetka-assets/Admin/support_missing_manifest.json";
const DEFAULT_TERMS_URL = "https://api.planetka.io/legal/terms-of-service.pdf";
const DEFAULT_PRIVACY_URL = "https://api.planetka.io/legal/privacy-policy.pdf";
const DEFAULT_LEGAL_VERSION = "2026-03-26";
const DEFAULT_ADDON_UPDATE_MANIFEST_VERSION = "0.2.0";
const DEFAULT_ADDON_UPDATE_CHANNEL = "stable";
const DEFAULT_ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS = 300;
const DEFAULT_ADDON_UPDATE_RELEASE_NOTES_URL = "https://www.planetka.io/blender/documentation/";
const DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT = 20;
const DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT = 6;
const DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS = 900;
const DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT = 20;
const DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS = 300;
const DEFAULT_REFRESH_SESSION_CLEANUP_RETENTION_DAYS = 30;
const DEFAULT_ALERT_AUTH_429_THRESHOLD = 10;
const DEFAULT_ALERT_AUTH_429_WINDOW_SECONDS = 60;
const DEFAULT_ALERT_AUTH_ERROR_THRESHOLD = 5;
const DEFAULT_ALERT_AUTH_ERROR_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_403_THRESHOLD = 25;
const DEFAULT_ALERT_PROD_403_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_429_THRESHOLD = 25;
const DEFAULT_ALERT_PROD_429_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_TILE_MISS_THRESHOLD = 25;
const DEFAULT_ALERT_PROD_TILE_MISS_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_TILE_ERROR_THRESHOLD = 10;
const DEFAULT_ALERT_PROD_TILE_ERROR_WINDOW_SECONDS = 300;
const DEFAULT_ALERT_PROD_COOLDOWN_SECONDS = 300;
const DEFAULT_TILE_FARM_ALERT_WINDOW_SECONDS = 300;
const DEFAULT_TILE_FARM_ALERT_USER_REQUEST_THRESHOLD = 300;
const DEFAULT_TILE_FARM_ALERT_IP_REQUEST_THRESHOLD = 500;
const DEFAULT_TILE_FARM_ALERT_UNIQUE_TILE_THRESHOLD = 200;
const DEFAULT_TILE_FARM_ALERT_UNTAGGED_MIN_REQUESTS = 120;
const DEFAULT_TILE_FARM_ALERT_UNTAGGED_PERCENT = 90;
const DEFAULT_TILE_FARM_ALERT_EMAIL_COOLDOWN_SECONDS = 300;
const DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS = 3600;
const DEFAULT_AUTH_CONTEXT_CACHE_TTL_SECONDS = 60;
const DEFAULT_AUTH_CONTEXT_CACHE_MAX_ENTRIES = 4096;
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
const DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS = "stressfree%";
const DEFAULT_ANALYTICS_ADMIN_EMAILS = "info@planetka.io,tom.griger@gmail.com";
const DEFAULT_ADMIN_LOGIN_EMAIL = "tom.griger@gmail.com";
const DEFAULT_TILE_EVENT_RETENTION_DAYS = 30;
const DEFAULT_AUTH_REFRESH_EVENT_RETENTION_DAYS = 30;
const DEFAULT_TILE_ROLLUP_RETENTION_DAYS = 365;
const BUG_REPORT_IMAGE_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_TILE_BROWSER_MAX_AGE_SECONDS = 86400;
const DEFAULT_TILE_EDGE_MAX_AGE_SECONDS = 604800;
const MAX_TILE_MAX_AGE_SECONDS = 31536000;
const DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS = 900;
const DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS = 2;
const RATE_LIMIT_PRUNE_INTERVAL_SECONDS = 300;
const RATE_LIMIT_ENTRY_TTL_SECONDS = 172800;
const API_KEY_REQUEST_TYPE_FREE = "free";
let userConsentColumnsReady = false;
let stripeWebhookEventsTableReady = false;
let rateLimitsTableReady = false;
let tileRequestEventsTableReady = false;
let authRefreshEventsTableReady = false;
let apiKeyTablesReady = false;
let refreshSessionColumnsReady = false;
let adminHardBlocksTableReady = false;
let rateLimitsLastPruneAt = 0;
let supportMissingManifestCache = {
  loadedAtMs: 0,
  expiresAtMs: 0,
  key: "",
  version: "",
  generatedAt: "",
  byLayer: {},
};
let cloudflareR2BillableUsageCache = {
  expiresAtMs: 0,
  cacheKey: "",
  value: null,
};
let authContextCache = new Map();

const AUTH_SESSION_DEPS = {
  authContextCacheGet,
  authContextCacheSet,
  blockedAccountResponse,
  enforceApiKeyDeviceLimit,
  enforceUserPlanPolicy,
  findUserById,
  isAnalyticsAdmin,
  isApiKeyUsableById,
  isBlockedStatus,
  isPrimaryAnalyticsAdmin,
  json,
  normalizeDeviceId,
  normalizeRequestedPlan,
  parseBooleanFlag,
  requireDb,
  requireSecret,
  resolvePlanCode,
  verifyJwt,
};

const ADMIN_ANALYTICS_DEPS = {
  buildAdminSessionCookie,
  collectAnalyticsSnapshot,
  corsHeaders,
  DEFAULT_ADMIN_ANALYTICS_TILE_MAP_KEY,
  DEFAULT_ANALYTICS_WINDOW_MINUTES,
  DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
  escapeHtml,
  html,
  json,
  listAnalyticsUsers,
  normalizePlanCode,
  nowIso,
  parseAnalyticsUsersSort,
  parseAnalyticsUsersSortDirection,
  parseHeavyUserPlanFilter,
  parseNonNegativeInteger,
  PLAN_CODE_PLANETKA,
  PLAN_CODE_PLANETKA_PRO,
  publicErrorMessage,
  requireAnalyticsAdmin: (request, env) => requireAnalyticsAdmin(request, env, AUTH_SESSION_DEPS),
  sanitizeAnalyticsMinutes,
  sanitizeLiveTileMapMinutes,
  BYTES_PER_GB,
};

const ADMIN_SESSION_DEPS = {
  buildAdminSessionClearCookie,
  buildAdminSessionCookie,
  corsHeaders,
  createAccessToken,
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
  PLAN_CODE_PLANETKA_PRO,
  rateLimitedResponse,
  requestClientIp,
  requireAuthenticatedUserContext: (request, env, options) => requireAuthenticatedUserContext(request, env, options, AUTH_SESSION_DEPS),
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
  dbGet,
  dbMetaChanges,
  dbRun,
  ensureAdminHardBlocksTable,
  ensureApiKeyTables,
  ensureRefreshSessionColumns,
  findUserByEmail,
  findUserById,
  json,
  normalizeDeviceId,
  normalizeEmail,
  normalizeRequestedPlan,
  nowIso,
  parseJson,
  PLAN_CODE_PLANETKA,
  requireAnalyticsAdmin: (request, env) => requireAnalyticsAdmin(request, env, AUTH_SESSION_DEPS),
};

const BILLING_DEPS = {
  dbRun,
  ensureStripeWebhookEventsTable,
  enforceUserPlanPolicy,
  evaluateStripePlanPurchaseGuard,
  findUserByEmail,
  hmacSha256Hex,
  isBlockedStatus,
  json,
  normalizeEmail,
  normalizeRequestedPlan,
  normalizeUserStatus,
  nowIso,
  parsePositiveNumber,
  planDisplayName,
  PLAN_CODE_PLANETKA,
  PLAN_CODE_PLANETKA_FREE,
  PLAN_CODE_PLANETKA_PRO,
  requireDb,
  requireSecret,
  resolvePlanCode,
  resolvePlanPriority,
  upsertUserByEmail,
};

const PUBLIC_MISC_DEPS = {
  ADDON_ID,
  BUG_REPORT_IMAGE_MAX_BYTES,
  DEFAULT_ADDON_UPDATE_CHANNEL,
  DEFAULT_ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS,
  DEFAULT_ADDON_UPDATE_MANIFEST_VERSION,
  DEFAULT_ADDON_UPDATE_RELEASE_NOTES_URL,
  base64EncodeBytes,
  base64EncodeString,
  corsHeaders,
  escapeHtml,
  json,
  jsonWithHeaders,
  nowIso,
  parseJson,
  parseNonNegativeInteger,
  requireAuthenticatedUserContext: (request, env, options) => requireAuthenticatedUserContext(request, env, options, AUTH_SESSION_DEPS),
  requireSecret,
};

const API_KEY_PAGE_DEPS = {
  PLAN_CODE_PLANETKA,
  PLAN_CODE_PLANETKA_FREE,
  DEFAULT_CONTACT_URL,
  DEFAULT_PRIVACY_URL,
  DEFAULT_TERMS_URL,
  activateApiKeyFromToken,
  corsHeaders,
  escapeHtml,
  html,
  maskApiKey,
  normalizeContactUrl,
  normalizeRequestedPlan,
  planAccessSummary,
  planDisplayName,
  requireDb,
};

function nowIso() {
  return new Date().toISOString();
}

function addMinutesIso(minutes) {
  return new Date(Date.now() + (minutes * 60 * 1000)).toISOString();
}

function addDaysIso(days) {
  return new Date(Date.now() + (days * 24 * 60 * 60 * 1000)).toISOString();
}

function addDaysFromIso(isoValue, days) {
  const base = Date.parse(String(isoValue || ""));
  if (!Number.isFinite(base)) {
    return addDaysIso(days);
  }
  return new Date(base + (days * 24 * 60 * 60 * 1000)).toISOString();
}

function sleepMs(delayMs) {
  const safeDelay = Math.max(0, parseNonNegativeInteger(delayMs, 0));
  if (safeDelay <= 0) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    setTimeout(resolve, safeDelay);
  });
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

function isTileHotPathMonitoringEnabled(env = {}) {
  const raw = env.ENABLE_TILE_HOT_PATH_MONITORING;
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    // Default off: keep tile request path focused on serving data.
    return false;
  }
  return parseBooleanFlag(raw);
}

function blockedAccountResponse(env, message = "Planetka account is blocked. Contact info@planetka.io.") {
  return json(
    {
      ok: false,
      error: "account_blocked",
      message,
    },
    403,
    env,
  );
}

function toBytesFromGb(gbValue) {
  return Math.max(0, Math.floor(parsePositiveNumber(gbValue, 0) * BYTES_PER_GB));
}

function clampNonNegativeInt(value) {
  return Math.max(0, parseNonNegativeInteger(value, 0));
}

function resolveTileCacheControl(env) {
  const browserMaxAge = Math.min(
    MAX_TILE_MAX_AGE_SECONDS,
    parseNonNegativeInteger(env.TILE_BROWSER_MAX_AGE_SECONDS, DEFAULT_TILE_BROWSER_MAX_AGE_SECONDS),
  );
  const edgeMaxAgeRaw = parseNonNegativeInteger(env.TILE_EDGE_MAX_AGE_SECONDS, DEFAULT_TILE_EDGE_MAX_AGE_SECONDS);
  const edgeMaxAge = Math.min(MAX_TILE_MAX_AGE_SECONDS, Math.max(browserMaxAge, edgeMaxAgeRaw));
  const immutable = String(env.TILE_CACHE_IMMUTABLE ?? "1").trim().toLowerCase();
  const immutableEnabled = !["0", "false", "no", "off"].includes(immutable);
  return immutableEnabled
    ? `public, max-age=${browserMaxAge}, s-maxage=${edgeMaxAge}, immutable`
    : `public, max-age=${browserMaxAge}, s-maxage=${edgeMaxAge}`;
}

function base64UrlEncode(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64EncodeBytes(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64UrlEncodeString(value) {
  return base64UrlEncode(encoder.encode(value));
}

function base64EncodeString(value) {
  return base64EncodeBytes(encoder.encode(String(value || "")));
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
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function randomToken(byteLength = 32) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

function isValidDeviceCode(value) {
  return /^[A-Za-z0-9_-]{32}$/.test(String(value || "").trim());
}

function isValidApiKey(value) {
  return /^pka_[A-Za-z0-9_-]{24,128}$/.test(String(value || "").trim());
}

function normalizeOrderId(value) {
  return String(value || "").trim().replace(/\s+/g, " ").slice(0, 128);
}

function parseClaimCooldownDays(env) {
  return Math.max(
    1,
    Math.floor(parsePositiveNumber(env.PENDING_CLAIM_COOLDOWN_DAYS, DEFAULT_PENDING_CLAIM_COOLDOWN_DAYS)),
  );
}

function thresholdHit(count, threshold) {
  if (threshold <= 0) {
    return false;
  }
  return count === threshold || (count > threshold && (count % threshold) === 0);
}

function computeApiKeyExpiryIso(planCode, env) {
  void planCode;
  void env;
  // API keys are non-expiring for this release.
  return "";
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
  const safe = raw.replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 128);
  return safe;
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

async function hmacSha256Hex(secret, value) {
  const signature = await hmacSha256(secret, value);
  return Array.from(signature, (byte) => byte.toString(16).padStart(2, "0")).join("");
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
  const signingInput = `${encodedHeader}.${encodedPayload}`;
  const expected = await hmacSha256(secret, signingInput);
  const actual = base64UrlDecodeToBytes(encodedSignature);
  const expectedBytes = expected instanceof Uint8Array ? expected : new Uint8Array(expected);
  if (actual.length !== expectedBytes.length) {
    throw new Error("invalid_token_signature");
  }
  let mismatch = 0;
  for (let i = 0; i < actual.length; i += 1) {
    mismatch |= actual[i] ^ expectedBytes[i];
  }
  if (mismatch !== 0) {
    throw new Error("invalid_token_signature");
  }

  const payloadJson = base64UrlDecodeToString(encodedPayload);
  const payload = JSON.parse(payloadJson);
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (payload.exp && Number(payload.exp) < nowSeconds) {
    throw new Error("token_expired");
  }
  return payload;
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
  } catch (error) {
    console.debug(
      "worker.request.invalid_json",
      JSON.stringify({
        method: request.method,
        url: request.url,
        error: String(error && error.message || "invalid_json"),
      }),
    );
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

async function dbTableExists(db, tableName) {
  const row = await dbGet(
    db,
    `
      SELECT name
      FROM sqlite_master
      WHERE type = 'table' AND name = ?
      LIMIT 1
    `,
    [String(tableName || "").trim()],
  );
  return Boolean(row && row.name);
}

function parseRateLimitInteger(value, fallback) {
  return Math.max(0, parseNonNegativeInteger(value, fallback));
}

function authContextCacheTtlMs(env = {}) {
  const ttlSeconds = Math.min(
    3600,
    Math.max(
      0,
      parseRateLimitInteger(
        env.AUTH_CONTEXT_CACHE_TTL_SECONDS,
        DEFAULT_AUTH_CONTEXT_CACHE_TTL_SECONDS,
      ),
    ),
  );
  return ttlSeconds * 1000;
}

function authContextCacheMaxEntries(env = {}) {
  return Math.min(
    20000,
    Math.max(
      64,
      parseRateLimitInteger(
        env.AUTH_CONTEXT_CACHE_MAX_ENTRIES,
        DEFAULT_AUTH_CONTEXT_CACHE_MAX_ENTRIES,
      ),
    ),
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
  if (!entry) {
    return null;
  }
  if (!Number.isFinite(entry.expiresAtMs) || entry.expiresAtMs <= Date.now()) {
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
  if (authContextCache.size >= maxEntries) {
    const nowMs = Date.now();
    for (const [entryKey, entryValue] of authContextCache.entries()) {
      if (!entryValue || !Number.isFinite(entryValue.expiresAtMs) || entryValue.expiresAtMs <= nowMs) {
        authContextCache.delete(entryKey);
      }
    }
  }
  while (authContextCache.size >= maxEntries) {
    const oldestKey = authContextCache.keys().next().value;
    if (!oldestKey) {
      break;
    }
    authContextCache.delete(oldestKey);
  }
  authContextCache.set(safeKey, {
    expiresAtMs: Date.now() + ttlMs,
    value,
  });
}

async function trackThresholdAlertDb(db, eventName, threshold, windowSeconds, payload = {}) {
  if (!db || !eventName || threshold <= 0 || windowSeconds <= 0) {
    return;
  }
  await ensureRateLimitsTable(db);
  const counter = await consumeRateLimitWindow(
    db,
    "alert_counter",
    String(eventName || ""),
    2147483647,
    windowSeconds,
  );
  const count = clampNonNegativeInt(counter && counter.count);
  const shouldLog = count === threshold || (count > threshold && (count % threshold) === 0);
  if (!shouldLog) {
    return;
  }
  console.warn(
    "worker.alert.threshold_exceeded",
    JSON.stringify({
      event: eventName,
      threshold,
      window_seconds: windowSeconds,
      count,
      ...payload,
    }),
  );
}

function isAuthOrDevicePath(path) {
  const normalized = String(path || "").trim();
  return normalized.startsWith("/auth/") || normalized.startsWith("/device/") || normalized.startsWith("/api-key");
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
  const country = String(request.headers.get("CF-IPCountry") || "").trim().toUpperCase();
  if (!country || country === "XX" || country === "T1") {
    return "UNKNOWN";
  }
  return country;
}

function parseAdminEmailSet(env) {
  const raw = String(env.ANALYTICS_ADMIN_EMAILS || DEFAULT_ANALYTICS_ADMIN_EMAILS).trim();
  const set = new Set();
  for (const part of raw.split(",")) {
    const email = normalizeEmail(part);
    if (email && email.includes("@")) {
      set.add(email);
    }
  }
  return set;
}

function parseAbuseAlertWhitelistSet(env) {
  const explicit = parseCsvEmailSet(env.ABUSE_ALERT_WHITELIST_EMAILS, "");
  const adminSet = parseAdminEmailSet(env);
  for (const email of adminSet) {
    explicit.add(email);
  }
  return explicit;
}

function isAbuseAlertWhitelisted(email, env) {
  const normalized = normalizeEmail(email);
  if (!normalized) {
    return false;
  }
  const whitelist = parseAbuseAlertWhitelistSet(env);
  return whitelist.has(normalized);
}

function resolveAdminLoginEmail(env) {
  const configured = normalizeEmail(env.ADMIN_LOGIN_EMAIL || DEFAULT_ADMIN_LOGIN_EMAIL);
  const adminSet = parseAdminEmailSet(env);
  if (configured && configured.includes("@")) {
    if (adminSet.has(configured)) {
      return configured;
    }
    // Enforce that login email is also an analytics admin.
    return "";
  }
  for (const email of adminSet) {
    if (email && email.includes("@")) {
      return email;
    }
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
    diff |= (leftByte ^ rightByte);
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
  if (!user || !user.email) {
    return false;
  }
  return parseAdminEmailSet(env).has(normalizeEmail(user.email));
}

function resolvePrimaryAnalyticsAdminEmail(env) {
  return normalizeEmail(env.ANALYTICS_PRIMARY_ADMIN_EMAIL || DEFAULT_ADMIN_LOGIN_EMAIL);
}

function isPrimaryAnalyticsAdmin(user, env) {
  const primary = resolvePrimaryAnalyticsAdminEmail(env);
  if (!primary || !user || !user.email) {
    return false;
  }
  return normalizeEmail(user.email) === primary;
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
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_admin_hard_blocks_active_email ON admin_hard_blocks(active, blocked_email)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_admin_hard_blocks_active_device ON admin_hard_blocks(active, blocked_device_id)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_admin_hard_blocks_active_ip ON admin_hard_blocks(active, blocked_ip)`,
  );
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
      SELECT
        id,
        blocked_email,
        blocked_device_id,
        blocked_ip,
        source_user_id,
        source_user_email,
        reason,
        created_by,
        created_at
      FROM admin_hard_blocks
      WHERE active = 1
        AND (${whereParts.join(" OR ")})
      ORDER BY created_at DESC
      LIMIT 1
    `,
    bindings,
  );
}

async function ensureRateLimitsTable(db) {
  if (rateLimitsTableReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS rate_limits (
        key TEXT PRIMARY KEY,
        window_start INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_rate_limits_updated_at ON rate_limits(updated_at DESC)`,
  );
  rateLimitsTableReady = true;
}

async function ensureTileRequestEventsTable(db) {
  if (tileRequestEventsTableReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS tile_request_events (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        created_at_unix INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        resolve_id TEXT,
        method TEXT NOT NULL,
        path TEXT NOT NULL,
        folder TEXT,
        file_name TEXT,
        tile_key TEXT,
        status_code INTEGER NOT NULL,
        bytes_served INTEGER NOT NULL DEFAULT 0,
        cache_status TEXT,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        cf_ray TEXT,
        cf_country TEXT,
        client_ip TEXT,
        error_code TEXT
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_request_events_created_unix ON tile_request_events(created_at_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_request_events_user_created_unix ON tile_request_events(user_id, created_at_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_request_events_resolve_id ON tile_request_events(resolve_id)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_request_events_status_code ON tile_request_events(status_code)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_request_events_created_at ON tile_request_events(created_at DESC)`,
  );
  await ensureTileRequestRollupTables(db);
  tileRequestEventsTableReady = true;
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
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_created_unix ON auth_refresh_events(created_at_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_outcome_created_unix ON auth_refresh_events(outcome, created_at_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_user_created_unix ON auth_refresh_events(user_id, created_at_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_auth_refresh_events_email_created_unix ON auth_refresh_events(user_email, created_at_unix DESC)`,
  );
  authRefreshEventsTableReady = true;
}

async function logAuthRefreshEvent(db, event = {}) {
  try {
    await ensureAuthRefreshEventsTable(db);
    const createdAt = nowIso();
    const createdAtUnix = Math.floor(Date.parse(createdAt) / 1000) || Math.floor(Date.now() / 1000);
    const outcome = String(event.outcome || "error").trim().toLowerCase() || "error";
    const errorCode = String(event.error_code || "").trim().slice(0, 128);
    const detailsJson = event.details && typeof event.details === "object"
      ? JSON.stringify(event.details)
      : "";
    await dbRun(
      db,
      `
        INSERT INTO auth_refresh_events (
          id,
          created_at,
          created_at_unix,
          user_id,
          user_email,
          auth_method,
          api_key_id,
          device_id,
          client_ip,
          cf_country,
          cf_ray,
          outcome,
          error_code,
          http_status,
          details_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        outcome,
        errorCode || null,
        clampNonNegativeInt(event.http_status),
        detailsJson || null,
      ],
    );
  } catch (error) {
    console.warn(
      "worker.auth_refresh_event_log_failed",
      JSON.stringify({
        error: String(error && error.message || "auth_refresh_event_log_failed"),
        outcome: String(event && event.outcome || "unknown"),
        error_code: String(event && event.error_code || ""),
      }),
    );
  }
}

async function ensureTileRequestRollupTables(db) {
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS tile_request_rollup_hourly_account (
        bucket_start_unix INTEGER NOT NULL,
        bucket_start TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        bytes_served INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        cache_hit_count INTEGER NOT NULL DEFAULT 0,
        tagged_request_count INTEGER NOT NULL DEFAULT 0,
        last_event_unix INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (bucket_start_unix, user_id)
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_rollup_hourly_account_bucket ON tile_request_rollup_hourly_account(bucket_start_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_rollup_hourly_account_user ON tile_request_rollup_hourly_account(user_id, bucket_start_unix DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS tile_request_rollup_daily_account (
        day_start_unix INTEGER NOT NULL,
        day_start TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        bytes_served INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        cache_hit_count INTEGER NOT NULL DEFAULT 0,
        tagged_request_count INTEGER NOT NULL DEFAULT 0,
        last_event_unix INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day_start_unix, user_id)
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_rollup_daily_account_day ON tile_request_rollup_daily_account(day_start_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_rollup_daily_account_user ON tile_request_rollup_daily_account(user_id, day_start_unix DESC)`,
  );
}

async function ensureMonthlyCostAlertStateTable(db) {
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS monthly_cost_alert_state (
        month_key TEXT PRIMARY KEY,
        last_notified_mark_usd INTEGER NOT NULL DEFAULT 0,
        last_estimated_usd REAL NOT NULL DEFAULT 0,
        last_alert_at TEXT,
        updated_at TEXT NOT NULL,
        created_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_monthly_cost_alert_state_updated ON monthly_cost_alert_state(updated_at DESC)`,
  );
}

function startOfHourUnix(epochSeconds) {
  const safe = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  return safe - (safe % 3600);
}

function startOfDayUnix(epochSeconds) {
  const safe = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  return safe - (safe % 86400);
}

function startOfWeekUnix(epochSeconds) {
  const safe = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  const date = new Date(safe * 1000);
  date.setUTCHours(0, 0, 0, 0);
  const mondayOffsetDays = (date.getUTCDay() + 6) % 7;
  const mondayStartMs = date.getTime() - (mondayOffsetDays * 86400 * 1000);
  return Math.max(0, Math.floor(mondayStartMs / 1000));
}

function monthBucketKey(epochSeconds) {
  const safe = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  const date = new Date(safe * 1000);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function weekBucketKey(epochSeconds) {
  return String(startOfWeekUnix(epochSeconds));
}

async function recordTileRequestRollups(db, payload) {
  await ensureTileRequestRollupTables(db);
  const createdAtUnix = parseNonNegativeInteger(payload.created_at_unix, Math.floor(Date.now() / 1000));
  const bucketHour = startOfHourUnix(createdAtUnix);
  const bucketDay = startOfDayUnix(createdAtUnix);
  const bucketHourIso = new Date(bucketHour * 1000).toISOString();
  const bucketDayIso = new Date(bucketDay * 1000).toISOString();
  const userId = String(payload.user_id || "").trim();
  const userEmail = normalizeEmail(payload.user_email || "");
  const statusCode = parseNonNegativeInteger(payload.status_code, 0);
  const bytesServed = clampNonNegativeInt(payload.bytes_served);
  const cacheStatus = String(payload.cache_status || "").trim().toUpperCase();
  const taggedRequest = String(payload.resolve_id || "").trim() ? 1 : 0;
  const errorCount = statusCode >= 400 ? 1 : 0;
  const cacheHitCount = cacheStatus === "HIT" ? 1 : 0;

  await dbRun(
    db,
    `
      INSERT INTO tile_request_rollup_hourly_account (
        bucket_start_unix,
        bucket_start,
        user_id,
        user_email,
        request_count,
        bytes_served,
        error_count,
        cache_hit_count,
        tagged_request_count,
        last_event_unix
      ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
      ON CONFLICT(bucket_start_unix, user_id) DO UPDATE SET
        user_email = excluded.user_email,
        request_count = tile_request_rollup_hourly_account.request_count + 1,
        bytes_served = tile_request_rollup_hourly_account.bytes_served + excluded.bytes_served,
        error_count = tile_request_rollup_hourly_account.error_count + excluded.error_count,
        cache_hit_count = tile_request_rollup_hourly_account.cache_hit_count + excluded.cache_hit_count,
        tagged_request_count = tile_request_rollup_hourly_account.tagged_request_count + excluded.tagged_request_count,
        last_event_unix = CASE
          WHEN excluded.last_event_unix > tile_request_rollup_hourly_account.last_event_unix
            THEN excluded.last_event_unix
          ELSE tile_request_rollup_hourly_account.last_event_unix
        END
    `,
    [bucketHour, bucketHourIso, userId, userEmail, bytesServed, errorCount, cacheHitCount, taggedRequest, createdAtUnix],
  );

  await dbRun(
    db,
    `
      INSERT INTO tile_request_rollup_daily_account (
        day_start_unix,
        day_start,
        user_id,
        user_email,
        request_count,
        bytes_served,
        error_count,
        cache_hit_count,
        tagged_request_count,
        last_event_unix
      ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
      ON CONFLICT(day_start_unix, user_id) DO UPDATE SET
        user_email = excluded.user_email,
        request_count = tile_request_rollup_daily_account.request_count + 1,
        bytes_served = tile_request_rollup_daily_account.bytes_served + excluded.bytes_served,
        error_count = tile_request_rollup_daily_account.error_count + excluded.error_count,
        cache_hit_count = tile_request_rollup_daily_account.cache_hit_count + excluded.cache_hit_count,
        tagged_request_count = tile_request_rollup_daily_account.tagged_request_count + excluded.tagged_request_count,
        last_event_unix = CASE
          WHEN excluded.last_event_unix > tile_request_rollup_daily_account.last_event_unix
            THEN excluded.last_event_unix
          ELSE tile_request_rollup_daily_account.last_event_unix
        END
    `,
    [bucketDay, bucketDayIso, userId, userEmail, bytesServed, errorCount, cacheHitCount, taggedRequest, createdAtUnix],
  );
}

async function recordTileRequestEvent(db, payload) {
  try {
    await ensureTileRequestEventsTable(db);
    const createdAt = String(payload.created_at || nowIso());
    const createdAtUnix = parseNonNegativeInteger(payload.created_at_unix, Math.floor(Date.now() / 1000));
    await dbRun(
      db,
      `
        INSERT INTO tile_request_events (
          id,
          created_at,
          created_at_unix,
          user_id,
          user_email,
          resolve_id,
          method,
          path,
          folder,
          file_name,
          tile_key,
          status_code,
          bytes_served,
          cache_status,
          duration_ms,
          cf_ray,
          cf_country,
          client_ip,
          error_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
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
        parseNonNegativeInteger(payload.status_code, 0),
        clampNonNegativeInt(payload.bytes_served),
        String(payload.cache_status || ""),
        clampNonNegativeInt(payload.duration_ms),
        String(payload.cf_ray || ""),
        String(payload.cf_country || ""),
        String(payload.client_ip || ""),
        String(payload.error_code || ""),
      ],
    );
    await recordTileRequestRollups(db, {
      created_at_unix: createdAtUnix,
      user_id: String(payload.user_id || ""),
      user_email: normalizeEmail(payload.user_email || ""),
      resolve_id: String(payload.resolve_id || ""),
      status_code: parseNonNegativeInteger(payload.status_code, 0),
      bytes_served: clampNonNegativeInt(payload.bytes_served),
      cache_status: String(payload.cache_status || ""),
    });
  } catch (error) {
    console.debug(
      "worker.analytics.tile_request_write_failed",
      JSON.stringify({
        error: String(error && error.message || "tile_request_write_failed"),
      }),
    );
  }
}

function sanitizeAnalyticsMinutes(value, fallback = DEFAULT_ANALYTICS_WINDOW_MINUTES) {
  const parsed = parseNonNegativeInteger(value, fallback);
  if (parsed <= 0) {
    return fallback;
  }
  return Math.min(MAX_ANALYTICS_WINDOW_MINUTES, parsed);
}

function sanitizeLiveTileMapMinutes(value, fallback = DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES) {
  const parsed = parseNonNegativeInteger(value, fallback);
  if (!ALLOWED_LIVE_TILE_MAP_WINDOW_MINUTES.has(parsed)) {
    return fallback;
  }
  return parsed;
}

function _normalizeErrorCode(value) {
  return String(value || "").trim().toLowerCase();
}

function _isTileNotFoundRow(row) {
  const statusCode = parseNonNegativeInteger(row && row.status_code, 0);
  if (statusCode !== 404) {
    return false;
  }
  const errorCode = _normalizeErrorCode(row && row.error_code);
  return !errorCode || errorCode === "tile_not_found";
}

async function loadSupportMissingManifest(env) {
  const manifestKey = String(
    env.ADMIN_SUPPORT_MISSING_MANIFEST_KEY || DEFAULT_ADMIN_SUPPORT_MISSING_MANIFEST_KEY,
  ).trim();
  const nowMs = Date.now();
  if (
    supportMissingManifestCache.key === manifestKey
    && nowMs < supportMissingManifestCache.expiresAtMs
    && supportMissingManifestCache.byLayer
  ) {
    return supportMissingManifestCache;
  }
  const bucket = env.PLANETKA_DATA;
  if (!bucket || !manifestKey) {
    supportMissingManifestCache = {
      loadedAtMs: nowMs,
      expiresAtMs: nowMs + (5 * 60 * 1000),
      key: manifestKey,
      version: "",
      generatedAt: "",
      byLayer: {},
    };
    return supportMissingManifestCache;
  }
  try {
    const object = await bucket.get(manifestKey);
    if (!object || !object.body) {
      supportMissingManifestCache = {
        loadedAtMs: nowMs,
        expiresAtMs: nowMs + (5 * 60 * 1000),
        key: manifestKey,
        version: "",
        generatedAt: "",
        byLayer: {},
      };
      return supportMissingManifestCache;
    }
    const raw = await object.text();
    const parsed = JSON.parse(String(raw || "{}"));
    const expected = parsed && parsed.expected_missing && typeof parsed.expected_missing === "object"
      ? parsed.expected_missing
      : {};
    const byLayer = {};
    for (const layer of ["PO", "EL", "WT"]) {
      const entries = Array.isArray(expected[layer]) ? expected[layer] : [];
      byLayer[layer] = new Set(entries.map((item) => String(item || "").trim()).filter(Boolean));
    }
    supportMissingManifestCache = {
      loadedAtMs: nowMs,
      expiresAtMs: nowMs + (10 * 60 * 1000),
      key: manifestKey,
      version: String(parsed && parsed.version || ""),
      generatedAt: String(parsed && parsed.generated_at || ""),
      byLayer,
    };
    return supportMissingManifestCache;
  } catch (_error) {
    supportMissingManifestCache = {
      loadedAtMs: nowMs,
      expiresAtMs: nowMs + (5 * 60 * 1000),
      key: manifestKey,
      version: "",
      generatedAt: "",
      byLayer: {},
    };
    return supportMissingManifestCache;
  }
}

function isExpectedSupportFallbackMiss(row, supportMissingManifest) {
  if (!_isTileNotFoundRow(row)) {
    return false;
  }
  const folder = String(row && row.folder || "").trim().toUpperCase();
  if (!["PO", "EL", "WT"].includes(folder)) {
    return false;
  }
  const fileName = String(row && row.file_name || "").trim();
  if (!fileName) {
    return true;
  }
  const byLayer = supportMissingManifest && supportMissingManifest.byLayer
    ? supportMissingManifest.byLayer
    : {};
  const layerSet = byLayer[folder];
  if (!(layerSet instanceof Set) || layerSet.size <= 0) {
    // No manifest loaded: default to support-layer fallback behavior.
    return true;
  }
  return layerSet.has(fileName);
}

async function collectAnalyticsSnapshot(
  db,
  minutes,
  planFilter = "all",
  liveTileMapWindowMinutes = DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
  env = {},
) {
  await ensureTileRequestEventsTable(db);
  await ensureTileRequestRollupTables(db);
  await ensureAuthRefreshEventsTable(db);
  const nowUnix = Math.floor(Date.now() / 1000);
  const windowMinutes = sanitizeAnalyticsMinutes(minutes, DEFAULT_ANALYTICS_WINDOW_MINUTES);
  const windowStartUnix = Math.max(0, nowUnix - (windowMinutes * 60));
  const rollupStart30d = Math.max(0, nowUnix - (30 * 86400));
  const safePlanFilter = parseHeavyUserPlanFilter(planFilter);
  const authRefreshWindowSeconds = Math.max(
    3600,
    parseNonNegativeInteger(env.AUTH_REFRESH_HEALTH_WINDOW_SECONDS, DEFAULT_AUTH_REFRESH_HEALTH_WINDOW_SECONDS),
  );
  const authRefreshWindowStartUnix = Math.max(0, nowUnix - authRefreshWindowSeconds);
  const eventEmailFilter = buildAnalyticsExcludedEmailFilter("user_email", env);
  const eventEmailFilterAliasE = buildAnalyticsExcludedEmailFilter("e.user_email", env);
  const userEmailFilter = buildAnalyticsExcludedEmailFilter("email", env);
  const rollupEmailFilter = buildAnalyticsExcludedEmailFilter("user_email", env);
  const rollupEmailFilterAliasR = buildAnalyticsExcludedEmailFilter("r.user_email", env);
  const heavyEmailFilter = buildAnalyticsExcludedEmailFilter("c.user_email", env);
  const authRefreshEmailFilter = buildAnalyticsExcludedEmailFilter("user_email", env);

  const summary = await dbGet(
    db,
    `
      SELECT
        COUNT(*) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END), 0) AS error_count,
        COALESCE(SUM(CASE WHEN UPPER(COALESCE(cache_status, '')) = 'HIT' THEN 1 ELSE 0 END), 0) AS cache_hit_count,
        COALESCE(SUM(CASE WHEN resolve_id IS NOT NULL AND resolve_id != '' THEN 1 ELSE 0 END), 0) AS tagged_request_count,
        COALESCE(COUNT(DISTINCT CASE WHEN resolve_id IS NOT NULL AND resolve_id != '' THEN resolve_id END), 0) AS tagged_resolve_count
      FROM tile_request_events
      WHERE created_at_unix >= ?
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
    `,
    [windowStartUnix, ...eventEmailFilter.bindings],
  );

  const topLineUsers = await dbGet(
    db,
    `
      WITH users_normalized AS (
        SELECT
          CASE
            WHEN LOWER(COALESCE(status, '')) IN ('pro', 'planetka_pro', 'planetka_studio', 'studio') THEN 'commercial'
            WHEN LOWER(COALESCE(status, '')) IN ('lite', 'planetka', 'personal', 'basic', 'indie') THEN 'personal'
            ELSE 'free'
          END AS tier_code
        FROM users
        WHERE 1 = 1
        ${userEmailFilter.condition ? `AND ${userEmailFilter.condition}` : ""}
      )
      SELECT
        COALESCE(SUM(CASE WHEN tier_code = 'free' THEN 1 ELSE 0 END), 0) AS free_users,
        COALESCE(SUM(CASE WHEN tier_code = 'personal' THEN 1 ELSE 0 END), 0) AS personal_users,
        COALESCE(SUM(CASE WHEN tier_code = 'commercial' THEN 1 ELSE 0 END), 0) AS commercial_users,
        COUNT(*) AS total_users
      FROM users_normalized
    `,
    [...userEmailFilter.bindings],
  );

  const topLineTraffic = await dbGet(
    db,
    `
      WITH traffic AS (
        SELECT
          r.request_count,
          r.bytes_served,
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS plan_norm
        FROM tile_request_rollup_daily_account r
        LEFT JOIN users u ON u.id = r.user_id
        WHERE 1 = 1
        ${rollupEmailFilterAliasR.condition ? `AND ${rollupEmailFilterAliasR.condition}` : ""}
      )
      SELECT
        COALESCE(SUM(CASE WHEN plan_norm IN ('free', 'planetka_free', 'trial') THEN request_count ELSE 0 END), 0) AS free_requests,
        COALESCE(SUM(CASE WHEN plan_norm IN ('lite', 'planetka', 'personal', 'basic', 'indie') THEN request_count ELSE 0 END), 0) AS personal_requests,
        COALESCE(SUM(CASE WHEN plan_norm IN ('pro', 'planetka_pro', 'planetka_studio', 'studio') THEN request_count ELSE 0 END), 0) AS commercial_requests,
        COALESCE(SUM(request_count), 0) AS total_requests,
        COALESCE(SUM(CASE WHEN plan_norm IN ('free', 'planetka_free', 'trial') THEN bytes_served ELSE 0 END), 0) AS free_bytes,
        COALESCE(SUM(CASE WHEN plan_norm IN ('lite', 'planetka', 'personal', 'basic', 'indie') THEN bytes_served ELSE 0 END), 0) AS personal_bytes,
        COALESCE(SUM(CASE WHEN plan_norm IN ('pro', 'planetka_pro', 'planetka_studio', 'studio') THEN bytes_served ELSE 0 END), 0) AS commercial_bytes,
        COALESCE(SUM(bytes_served), 0) AS total_bytes
      FROM traffic
    `,
    [PLAN_CODE_PLANETKA_FREE, ...rollupEmailFilterAliasR.bindings],
  );

  const topLineResolves = await dbGet(
    db,
    `
      WITH tagged_resolves AS (
        SELECT DISTINCT
          e.user_id,
          e.resolve_id,
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS plan_norm
        FROM tile_request_events e
        LEFT JOIN users u ON u.id = e.user_id
        WHERE
          e.resolve_id IS NOT NULL
          AND e.resolve_id != ''
          ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      )
      SELECT
        COALESCE(SUM(CASE WHEN plan_norm IN ('free', 'planetka_free', 'trial') THEN 1 ELSE 0 END), 0) AS free_resolves,
        COALESCE(SUM(CASE WHEN plan_norm IN ('lite', 'planetka', 'personal', 'basic', 'indie') THEN 1 ELSE 0 END), 0) AS personal_resolves,
        COALESCE(SUM(CASE WHEN plan_norm IN ('pro', 'planetka_pro', 'planetka_studio', 'studio') THEN 1 ELSE 0 END), 0) AS commercial_resolves,
        COUNT(*) AS total_resolves
      FROM tagged_resolves
    `,
    [PLAN_CODE_PLANETKA_FREE, ...eventEmailFilterAliasE.bindings],
  );

  const activeWindow6mStartUnix = Math.max(0, nowUnix - (180 * 86400));
  const activeWindow3mStartUnix = Math.max(0, nowUnix - (90 * 86400));
  const activeWindow1mStartUnix = Math.max(0, nowUnix - (30 * 86400));
  const activeWindow1wStartUnix = Math.max(0, nowUnix - (7 * 86400));
  const activeWindow1dStartUnix = Math.max(0, nowUnix - 86400);
  const activeWindow1hStartUnix = Math.max(0, nowUnix - 3600);
  const activeUserRows = await dbAll(
    db,
    `
      SELECT
        e.user_id,
        MAX(e.created_at_unix) AS last_seen_unix,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS plan_norm
      FROM tile_request_events e
      LEFT JOIN users u ON u.id = e.user_id
      WHERE
        e.created_at_unix >= ?
        AND e.user_id IS NOT NULL
        AND e.user_id != ''
        ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      GROUP BY
        e.user_id,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?)
    `,
    [
      PLAN_CODE_PLANETKA_FREE,
      activeWindow6mStartUnix,
      ...eventEmailFilterAliasE.bindings,
      PLAN_CODE_PLANETKA_FREE,
    ],
  );
  const makeActiveSplit = () => ({
    free: 0,
    personal: 0,
    commercial: 0,
    total: 0,
  });
  const activeWindows = {
    users_6m: makeActiveSplit(),
    users_3m: makeActiveSplit(),
    users_1m: makeActiveSplit(),
    users_1w: makeActiveSplit(),
    users_1d: makeActiveSplit(),
    users_1h: makeActiveSplit(),
  };
  const activeThresholds = [
    ["users_6m", activeWindow6mStartUnix],
    ["users_3m", activeWindow3mStartUnix],
    ["users_1m", activeWindow1mStartUnix],
    ["users_1w", activeWindow1wStartUnix],
    ["users_1d", activeWindow1dStartUnix],
    ["users_1h", activeWindow1hStartUnix],
  ];
  const resolveAnalyticsTierCode = (planValue) => {
    const normalized = normalizePlanCode(planValue);
    if (normalized === PLAN_CODE_PLANETKA_PRO) return "commercial";
    if (normalized === PLAN_CODE_PLANETKA) return "personal";
    return "free";
  };
  for (const row of (Array.isArray(activeUserRows) ? activeUserRows : [])) {
    const lastSeenUnix = clampNonNegativeInt(row && row.last_seen_unix);
    if (lastSeenUnix <= 0) {
      continue;
    }
    const tierCode = resolveAnalyticsTierCode(row && row.plan_norm);
    for (const [windowKey, thresholdUnix] of activeThresholds) {
      if (lastSeenUnix < thresholdUnix) {
        continue;
      }
      const windowCounts = activeWindows[windowKey];
      if (!windowCounts) {
        continue;
      }
      windowCounts.total += 1;
      if (tierCode === "commercial") {
        windowCounts.commercial += 1;
      } else if (tierCode === "personal") {
        windowCounts.personal += 1;
      } else {
        windowCounts.free += 1;
      }
    }
  }
  let activeUsers10m = [];
  try {
    activeUsers10m = await dbAll(
      db,
      `
        SELECT
          e.user_id,
          COALESCE(NULLIF(TRIM(e.user_email), ''), COALESCE(NULLIF(TRIM(u.email), ''), '')) AS user_email,
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS user_status,
          COUNT(*) AS request_count,
          COALESCE(COUNT(DISTINCT CASE WHEN e.resolve_id IS NOT NULL AND e.resolve_id != '' THEN e.resolve_id END), 0) AS resolve_count,
          COALESCE(SUM(e.bytes_served), 0) AS bytes_served,
          MAX(e.created_at) AS last_seen_at
        FROM tile_request_events e
        LEFT JOIN users u ON u.id = e.user_id
        WHERE
          e.created_at_unix >= ?
          AND e.status_code < 400
          ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
        GROUP BY
          e.user_id,
          COALESCE(NULLIF(TRIM(e.user_email), ''), COALESCE(NULLIF(TRIM(u.email), ''), '')),
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?)
        ORDER BY MAX(e.created_at_unix) DESC, bytes_served DESC
      `,
      [
        PLAN_CODE_PLANETKA,
        Math.max(0, nowUnix - 600),
        ...eventEmailFilterAliasE.bindings,
        PLAN_CODE_PLANETKA,
      ],
    );
  } catch (error) {
    console.warn(
      "planetka.analytics.active_users_10m_query_failed",
      JSON.stringify({
        error: String(error && error.message || "active_users_10m_query_failed"),
      }),
    );
    activeUsers10m = [];
  }
  const activeNow = await dbGet(
    db,
    `
      SELECT COUNT(*) AS active_download_rows
      FROM tile_request_events
      WHERE created_at_unix >= ?
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
    `,
    [Math.max(0, nowUnix - 10), ...eventEmailFilter.bindings],
  );

  const topUsers = await dbAll(
    db,
    `
      SELECT
        e.user_id,
        e.user_email,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS user_status,
        COUNT(*) AS request_count,
        COALESCE(COUNT(DISTINCT CASE WHEN e.resolve_id IS NOT NULL AND e.resolve_id != '' THEN e.resolve_id END), 0) AS resolve_count,
        COALESCE(SUM(e.bytes_served), 0) AS bytes_served,
        COALESCE(SUM(CASE WHEN e.status_code >= 400 THEN 1 ELSE 0 END), 0) AS error_count,
        MAX(e.created_at) AS last_seen_at
      FROM tile_request_events e
      LEFT JOIN users u ON u.id = e.user_id
      WHERE e.created_at_unix >= ?
      ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      GROUP BY e.user_id, e.user_email, COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?)
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [PLAN_CODE_PLANETKA, windowStartUnix, ...eventEmailFilterAliasE.bindings, PLAN_CODE_PLANETKA],
  );

  const topTiles = await dbAll(
    db,
    `
      SELECT
        tile_key,
        COUNT(*) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served
      FROM tile_request_events
      WHERE created_at_unix >= ? AND tile_key IS NOT NULL AND tile_key != ''
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
      GROUP BY tile_key
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [windowStartUnix, ...eventEmailFilter.bindings],
  );

  const tileMapWindowSeconds = Math.max(
    60,
    sanitizeLiveTileMapMinutes(liveTileMapWindowMinutes, DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES) * 60,
  );
  const tileMapStartUnix = Math.max(0, nowUnix - tileMapWindowSeconds);
  const tileMapRowLimit = 2500;
  const tileActivityFilter = buildTileActivityPlanFilterSql(safePlanFilter);
  const tileMapRows = await dbAll(
    db,
    `
      SELECT
        e.user_id,
        e.user_email,
        e.tile_key,
        MAX(e.created_at_unix) AS last_seen_unix,
        COUNT(*) AS request_count,
        COALESCE(SUM(e.bytes_served), 0) AS bytes_served,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS user_status
      FROM tile_request_events e
      LEFT JOIN users u ON u.id = e.user_id
      WHERE
        e.created_at_unix >= ?
        AND e.status_code < 400
        AND e.tile_key IS NOT NULL
        AND e.tile_key != ''
        ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
        ${tileActivityFilter.clause}
      GROUP BY
        e.user_id,
        e.user_email,
        e.tile_key,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?)
      ORDER BY last_seen_unix DESC
      LIMIT ${tileMapRowLimit}
    `,
    [
      PLAN_CODE_PLANETKA,
      tileMapStartUnix,
      ...eventEmailFilterAliasE.bindings,
      ...tileActivityFilter.bindings,
      PLAN_CODE_PLANETKA,
    ],
  );
  const activeTileUsersSet = new Set();
  const activeTileKeysSet = new Set();
  const normalizedTileMapRows = Array.isArray(tileMapRows) ? tileMapRows.map((row) => {
    const userId = String(row && row.user_id || "").trim();
    const userEmail = normalizeEmail(row && row.user_email || "");
    const userKey = userId || userEmail;
    if (userKey) {
      activeTileUsersSet.add(userKey);
    }
    const tileKey = String(row && row.tile_key || "").trim();
    if (tileKey) {
      activeTileKeysSet.add(tileKey);
    }
    return {
      user_id: userId,
      user_email: userEmail,
      user_status: String(row && row.user_status || PLAN_CODE_PLANETKA).trim().toLowerCase() || PLAN_CODE_PLANETKA,
      tile_key: tileKey,
      last_seen_unix: clampNonNegativeInt(row && row.last_seen_unix),
      request_count: clampNonNegativeInt(row && row.request_count),
      bytes_served: clampNonNegativeInt(row && row.bytes_served),
    };
  }) : [];

  const supportMissingManifest = await loadSupportMissingManifest(env);
  const recentFailuresRaw = await dbAll(
    db,
    `
      SELECT
        created_at,
        user_email,
        folder,
        file_name,
        tile_key,
        status_code,
        error_code,
        cache_status,
        duration_ms
      FROM tile_request_events
      WHERE status_code >= 400
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
      ORDER BY created_at_unix DESC
      LIMIT 50
    `,
    [...eventEmailFilter.bindings],
  );
  const recentFailures = [];
  for (const row of (Array.isArray(recentFailuresRaw) ? recentFailuresRaw : [])) {
    if (isExpectedSupportFallbackMiss(row, supportMissingManifest)) {
      continue;
    }
    recentFailures.push(row);
  }

  const authRefreshSummary = await dbGet(
    db,
    `
      SELECT
        COUNT(*) AS total_count,
        COALESCE(SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END), 0) AS success_count,
        COALESCE(SUM(CASE WHEN outcome != 'success' THEN 1 ELSE 0 END), 0) AS failure_count,
        COALESCE(COUNT(DISTINCT CASE WHEN outcome != 'success' AND user_id IS NOT NULL AND user_id != '' THEN user_id END), 0) AS failed_user_count
      FROM auth_refresh_events
      WHERE created_at_unix >= ?
      ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );
  const authRefreshTopFailureUsers = await dbAll(
    db,
    `
      SELECT
        user_id,
        user_email,
        COUNT(*) AS failure_count,
        MAX(created_at) AS last_failure_at
      FROM auth_refresh_events
      WHERE
        created_at_unix >= ?
        AND outcome != 'success'
        ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
      GROUP BY user_id, user_email
      ORDER BY failure_count DESC
      LIMIT 20
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );
  const authRefreshErrorBreakdown = await dbAll(
    db,
    `
      SELECT
        COALESCE(NULLIF(TRIM(error_code), ''), 'unknown_error') AS error_code,
        COUNT(*) AS count
      FROM auth_refresh_events
      WHERE
        created_at_unix >= ?
        AND outcome != 'success'
        ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
      GROUP BY COALESCE(NULLIF(TRIM(error_code), ''), 'unknown_error')
      ORDER BY count DESC
      LIMIT 20
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );

  const rollup30d = await dbGet(
    db,
    `
      SELECT
        COALESCE(SUM(request_count), 0) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(error_count), 0) AS error_count,
        COALESCE(SUM(cache_hit_count), 0) AS cache_hit_count,
        COALESCE(SUM(tagged_request_count), 0) AS tagged_request_count,
        COUNT(DISTINCT user_id) AS active_users
      FROM tile_request_rollup_daily_account
      WHERE day_start_unix >= ?
      ${rollupEmailFilter.condition ? `AND ${rollupEmailFilter.condition}` : ""}
    `,
    [rollupStart30d, ...rollupEmailFilter.bindings],
  );

  const topAccounts30d = await dbAll(
    db,
    `
      SELECT
        user_id,
        user_email,
        COALESCE(SUM(request_count), 0) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(error_count), 0) AS error_count,
        MAX(last_event_unix) AS last_event_unix
      FROM tile_request_rollup_daily_account
      WHERE day_start_unix >= ?
      ${rollupEmailFilter.condition ? `AND ${rollupEmailFilter.condition}` : ""}
      GROUP BY user_id, user_email
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [rollupStart30d, ...rollupEmailFilter.bindings],
  );

  const heavyWhereParts = [];
  const heavyBindings = [
    PLAN_CODE_PLANETKA_FREE,
    monthStartUnix(nowUnix),
    startOfWeekUnix(nowUnix),
    startOfDayUnix(nowUnix),
    monthStartUnix(nowUnix),
    startOfHourUnix(nowUnix),
  ];
  if (safePlanFilter === "lite") {
    heavyWhereParts.push(`agg.user_status = ?`);
    heavyBindings.push(PLAN_CODE_PLANETKA);
  } else if (safePlanFilter === "pro") {
    heavyWhereParts.push(`agg.user_status IN (?, ?)`);
    heavyBindings.push(PLAN_CODE_PLANETKA_PRO, PLAN_CODE_PLANETKA_STUDIO);
  }
  if (heavyEmailFilter.condition) {
    heavyWhereParts.push(String(heavyEmailFilter.condition).replace(/user_email/g, "agg.user_email"));
    heavyBindings.push(...heavyEmailFilter.bindings);
  }
  const heavyWhereSql = heavyWhereParts.length ? `WHERE ${heavyWhereParts.join(" AND ")}` : "";
  const heavyBaseSql = `
      WITH user_rollups AS (
        SELECT
          r.user_id,
          COALESCE(NULLIF(TRIM(u.email), ''), COALESCE(NULLIF(TRIM(r.user_email), ''), '')) AS user_email,
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS user_status,
          COALESCE(SUM(r.bytes_served), 0) AS lifetime_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS month_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS week_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS day_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.request_count ELSE 0 END), 0) AS request_count_month,
          COALESCE(MAX(r.last_event_unix), 0) AS last_event_unix
        FROM tile_request_rollup_daily_account r
        LEFT JOIN users u ON u.id = r.user_id
        GROUP BY
          r.user_id,
          COALESCE(NULLIF(TRIM(u.email), ''), COALESCE(NULLIF(TRIM(r.user_email), ''), '')),
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?)
      ),
      hour_rollups AS (
        SELECT
          user_id,
          COALESCE(SUM(bytes_served), 0) AS hour_bytes
        FROM tile_request_rollup_hourly_account
        WHERE bucket_start_unix >= ?
        GROUP BY user_id
      )
      SELECT
        agg.user_id,
        agg.user_email,
        agg.user_status,
        agg.lifetime_bytes,
        agg.month_bytes,
        agg.week_bytes,
        agg.day_bytes,
        COALESCE(hr.hour_bytes, 0) AS hour_bytes,
        agg.request_count_month,
        agg.last_event_unix
      FROM user_rollups agg
      LEFT JOIN hour_rollups hr ON hr.user_id = agg.user_id
      ${heavyWhereSql}
    `;
  const topHeavyLifetime = await dbAll(
    db,
    `${heavyBaseSql} ORDER BY lifetime_bytes DESC LIMIT 50`,
    heavyBindings,
  );
  const topHeavyMonth = await dbAll(
    db,
    `${heavyBaseSql} ORDER BY month_bytes DESC LIMIT 50`,
    heavyBindings,
  );
  const topHeavyWeek = await dbAll(
    db,
    `${heavyBaseSql} ORDER BY week_bytes DESC LIMIT 50`,
    heavyBindings,
  );
  const topHeavyDay = await dbAll(
    db,
    `${heavyBaseSql} ORDER BY day_bytes DESC LIMIT 50`,
    heavyBindings,
  );
  const topHeavyHour = await dbAll(
    db,
    `${heavyBaseSql} ORDER BY hour_bytes DESC LIMIT 50`,
    heavyBindings,
  );
  let heavyUsers30d = (Array.isArray(topHeavyMonth) ? topHeavyMonth : [])
    .map((row) => {
      return {
        user_id: String(row && row.user_id || "").trim(),
        user_email: normalizeEmail(row && row.user_email || ""),
        user_status: String(row && row.user_status || PLAN_CODE_PLANETKA).trim().toLowerCase() || PLAN_CODE_PLANETKA,
        month_bytes: clampNonNegativeInt(row && row.month_bytes),
        request_count_month: clampNonNegativeInt(row && row.request_count_month),
        last_event_unix: clampNonNegativeInt(row && row.last_event_unix),
      };
    });
  heavyUsers30d = heavyUsers30d.map((row) => ({
    ...row,
    request_count_30d: clampNonNegativeInt(row && row.request_count_month),
    bytes_served_30d: clampNonNegativeInt(row && row.month_bytes),
  }));
  heavyUsers30d = heavyUsers30d
    .sort((a, b) => clampNonNegativeInt(b && b.month_bytes) - clampNonNegativeInt(a && a.month_bytes))
    .slice(0, 20);
  const heavyResolveCountByUserId = new Map();
  const heavyUserIds = Array.from(
    new Set(
      [
        ...(Array.isArray(topHeavyLifetime) ? topHeavyLifetime : []),
        ...(Array.isArray(topHeavyMonth) ? topHeavyMonth : []),
        ...(Array.isArray(topHeavyWeek) ? topHeavyWeek : []),
        ...(Array.isArray(topHeavyDay) ? topHeavyDay : []),
        ...(Array.isArray(topHeavyHour) ? topHeavyHour : []),
        ...(Array.isArray(heavyUsers30d) ? heavyUsers30d : []),
      ].map((row) => String(row && row.user_id || "").trim()).filter(Boolean),
    ),
  );
  if (heavyUserIds.length > 0) {
    const placeholders = heavyUserIds.map(() => "?").join(",");
    const heavyResolveRows = await dbAll(
      db,
      `
        SELECT
          user_id,
          COUNT(DISTINCT resolve_id) AS resolve_count
        FROM tile_request_events
        WHERE
          user_id IN (${placeholders})
          AND resolve_id IS NOT NULL
          AND resolve_id != ''
        GROUP BY user_id
      `,
      heavyUserIds,
    );
    for (const row of heavyResolveRows || []) {
      const userId = String(row && row.user_id || "").trim();
      if (!userId) continue;
      heavyResolveCountByUserId.set(userId, clampNonNegativeInt(row && row.resolve_count));
    }
  }
  const attachHeavyResolveCounts = (rows) =>
    (Array.isArray(rows) ? rows : []).map((row) => {
      const userId = String(row && row.user_id || "").trim();
      return {
        ...row,
        resolve_count: clampNonNegativeInt(heavyResolveCountByUserId.get(userId) || 0),
      };
    });
  const normalizedActiveUsers10m = (Array.isArray(activeUsers10m) ? activeUsers10m : []).map((row) => ({
    user_id: String(row && row.user_id || "").trim(),
    user_email: normalizeEmail(row && row.user_email || ""),
    user_status: String(row && row.user_status || PLAN_CODE_PLANETKA).trim().toLowerCase() || PLAN_CODE_PLANETKA,
    request_count: clampNonNegativeInt(row && row.request_count),
    resolve_count: clampNonNegativeInt(row && row.resolve_count),
    bytes_served: clampNonNegativeInt(row && row.bytes_served),
    last_seen_at: String(row && row.last_seen_at || ""),
  }));
  const cloudflareBillableUsage = await fetchCloudflareR2BillableUsage(env, db);

  return {
    generated_at: nowIso(),
    window_minutes: windowMinutes,
    window_start_unix: windowStartUnix,
    top_line: {
      users: {
        free: clampNonNegativeInt(topLineUsers && topLineUsers.free_users),
        personal: clampNonNegativeInt(topLineUsers && topLineUsers.personal_users),
        commercial: clampNonNegativeInt(topLineUsers && topLineUsers.commercial_users),
        total: clampNonNegativeInt(topLineUsers && topLineUsers.total_users),
      },
      resolves: {
        free: clampNonNegativeInt(topLineResolves && topLineResolves.free_resolves),
        personal: clampNonNegativeInt(topLineResolves && topLineResolves.personal_resolves),
        commercial: clampNonNegativeInt(topLineResolves && topLineResolves.commercial_resolves),
        total: clampNonNegativeInt(topLineResolves && topLineResolves.total_resolves),
      },
      tile_requests: {
        free: clampNonNegativeInt(topLineTraffic && topLineTraffic.free_requests),
        personal: clampNonNegativeInt(topLineTraffic && topLineTraffic.personal_requests),
        commercial: clampNonNegativeInt(topLineTraffic && topLineTraffic.commercial_requests),
        total: clampNonNegativeInt(topLineTraffic && topLineTraffic.total_requests),
      },
      gb_served: {
        free: clampNonNegativeInt(topLineTraffic && topLineTraffic.free_bytes),
        personal: clampNonNegativeInt(topLineTraffic && topLineTraffic.personal_bytes),
        commercial: clampNonNegativeInt(topLineTraffic && topLineTraffic.commercial_bytes),
        total: clampNonNegativeInt(topLineTraffic && topLineTraffic.total_bytes),
      },
    },
    summary: {
      request_count: clampNonNegativeInt(summary && summary.request_count),
      bytes_served: clampNonNegativeInt(summary && summary.bytes_served),
      error_count: clampNonNegativeInt(summary && summary.error_count),
      cache_hit_count: clampNonNegativeInt(summary && summary.cache_hit_count),
      tagged_request_count: clampNonNegativeInt(summary && summary.tagged_request_count),
      tagged_resolve_count: clampNonNegativeInt(summary && summary.tagged_resolve_count),
    },
    active: {
      users_total: clampNonNegativeInt(topLineUsers && topLineUsers.total_users),
      users_6m: clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.total),
      users_3m: clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.total),
      users_1m: clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.total),
      users_1w: clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.total),
      users_1d: clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.total),
      users_1h: clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.total),
      windows: {
        "6m": {
          free: clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.free),
          personal: clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.personal),
          commercial: clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.commercial),
          total: clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.total),
        },
        "3m": {
          free: clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.free),
          personal: clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.personal),
          commercial: clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.commercial),
          total: clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.total),
        },
        "1m": {
          free: clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.free),
          personal: clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.personal),
          commercial: clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.commercial),
          total: clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.total),
        },
        "1w": {
          free: clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.free),
          personal: clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.personal),
          commercial: clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.commercial),
          total: clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.total),
        },
        "1d": {
          free: clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.free),
          personal: clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.personal),
          commercial: clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.commercial),
          total: clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.total),
        },
        "1h": {
          free: clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.free),
          personal: clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.personal),
          commercial: clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.commercial),
          total: clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.total),
        },
      },
      tile_events_10s: clampNonNegativeInt(activeNow && activeNow.active_download_rows),
    },
    active_users_10m: normalizedActiveUsers10m,
    top_users: Array.isArray(topUsers) ? topUsers : [],
    top_tiles: Array.isArray(topTiles) ? topTiles : [],
    recent_failures: Array.isArray(recentFailures) ? recentFailures : [],
    auth_refresh_health: {
      window_seconds: authRefreshWindowSeconds,
      window_start_unix: authRefreshWindowStartUnix,
      total_count: clampNonNegativeInt(authRefreshSummary && authRefreshSummary.total_count),
      success_count: clampNonNegativeInt(authRefreshSummary && authRefreshSummary.success_count),
      failure_count: clampNonNegativeInt(authRefreshSummary && authRefreshSummary.failure_count),
      failed_user_count: clampNonNegativeInt(authRefreshSummary && authRefreshSummary.failed_user_count),
      top_failure_users: Array.isArray(authRefreshTopFailureUsers) ? authRefreshTopFailureUsers : [],
      error_breakdown: Array.isArray(authRefreshErrorBreakdown) ? authRefreshErrorBreakdown : [],
    },
    rollup_30d: {
      window_days: 30,
      request_count: clampNonNegativeInt(rollup30d && rollup30d.request_count),
      bytes_served: clampNonNegativeInt(rollup30d && rollup30d.bytes_served),
      error_count: clampNonNegativeInt(rollup30d && rollup30d.error_count),
      cache_hit_count: clampNonNegativeInt(rollup30d && rollup30d.cache_hit_count),
      tagged_request_count: clampNonNegativeInt(rollup30d && rollup30d.tagged_request_count),
      active_users: clampNonNegativeInt(rollup30d && rollup30d.active_users),
      top_accounts: Array.isArray(topAccounts30d)
        ? topAccounts30d.map((row) => ({
          ...row,
          last_seen_at: Number.isFinite(Number(row && row.last_event_unix))
            ? new Date(Number(row.last_event_unix) * 1000).toISOString()
            : "",
        }))
        : [],
    },
    heavy_users: {
      plan_filter: safePlanFilter,
      top_lifetime: attachHeavyResolveCounts(topHeavyLifetime),
      top_month: attachHeavyResolveCounts(topHeavyMonth),
      top_week: attachHeavyResolveCounts(topHeavyWeek),
      top_day: attachHeavyResolveCounts(topHeavyDay),
      top_hour: attachHeavyResolveCounts(topHeavyHour),
    },
    heavy_users_30d: attachHeavyResolveCounts(heavyUsers30d),
    cloudflare_billable_usage: cloudflareBillableUsage,
    live_tile_map: {
      generated_at: nowIso(),
      window_seconds: tileMapWindowSeconds,
      plan_filter: safePlanFilter,
      users_active: activeTileUsersSet.size,
      tiles_active: activeTileKeysSet.size,
      row_limit: tileMapRowLimit,
      rows: normalizedTileMapRows,
    },
  };
}

async function maybePruneRateLimits(db, nowSeconds) {
  if ((nowSeconds - rateLimitsLastPruneAt) < RATE_LIMIT_PRUNE_INTERVAL_SECONDS) {
    return;
  }
  rateLimitsLastPruneAt = nowSeconds;
  try {
    await dbRun(
      db,
      `DELETE FROM rate_limits WHERE updated_at < ?`,
      [Math.max(0, nowSeconds - RATE_LIMIT_ENTRY_TTL_SECONDS)],
    );
  } catch (error) {
    // Prune is best-effort and must never block request handling.
    console.debug(
      "worker.rate_limits.prune_failed",
      JSON.stringify({
        error: String(error && error.message || "rate_limit_prune_failed"),
      }),
    );
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
      INSERT INTO rate_limits (
        key,
        window_start,
        count,
        updated_at
      ) VALUES (?, ?, 1, ?)
      ON CONFLICT(key) DO UPDATE SET
        window_start = CASE
          WHEN rate_limits.window_start = excluded.window_start THEN rate_limits.window_start
          ELSE excluded.window_start
        END,
        count = CASE
          WHEN rate_limits.window_start = excluded.window_start THEN rate_limits.count + 1
          ELSE 1
        END,
        updated_at = excluded.updated_at
      RETURNING count, window_start
    `,
    [storageKey, bucketStart, nowSeconds],
  );
  const count = clampNonNegativeInt(row && row.count);
  const effectiveWindowStart = parseNonNegativeInteger(row && row.window_start, bucketStart);
  const retryAfterSeconds = Math.max(1, (effectiveWindowStart + windowSeconds) - nowSeconds);
  return {
    allowed: count <= limit,
    count,
    limit,
    retryAfterSeconds,
  };
}

function rateLimitedResponse(env, code, message, retryAfterSeconds) {
  const retryAfter = Math.max(1, clampNonNegativeInt(retryAfterSeconds));
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

async function maybeSignalTileFarmingActivity(db, env, details = {}) {
  if (!db) {
    return;
  }
  await ensureRateLimitsTable(db);
  const statusCode = parseNonNegativeInteger(details.statusCode, 0);
  if (statusCode <= 0) {
    return;
  }

  const userId = String(details.userId || "").trim();
  const userEmail = normalizeEmail(details.userEmail || "");
  if (userEmail && isAbuseAlertWhitelisted(userEmail, env)) {
    return;
  }
  const userKey = userId || userEmail || "unknown";
  const ip = String(details.ip || "").trim() || "unknown";
  const deviceId = normalizeDeviceId(details.deviceId || "");
  const tileKey = String(details.tileKey || "").trim();
  const resolveId = String(details.resolveId || "").trim();
  const method = String(details.method || "GET").toUpperCase();
  const path = String(details.path || "").trim();

  const windowSeconds = Math.max(
    30,
    parseRateLimitInteger(env.TILE_FARM_ALERT_WINDOW_SECONDS, DEFAULT_TILE_FARM_ALERT_WINDOW_SECONDS),
  );
  const userRequestThreshold = Math.max(
    0,
    parseRateLimitInteger(env.TILE_FARM_ALERT_USER_REQUEST_THRESHOLD, DEFAULT_TILE_FARM_ALERT_USER_REQUEST_THRESHOLD),
  );
  const ipRequestThreshold = Math.max(
    0,
    parseRateLimitInteger(env.TILE_FARM_ALERT_IP_REQUEST_THRESHOLD, DEFAULT_TILE_FARM_ALERT_IP_REQUEST_THRESHOLD),
  );
  const uniqueTileThreshold = Math.max(
    0,
    parseRateLimitInteger(env.TILE_FARM_ALERT_UNIQUE_TILE_THRESHOLD, DEFAULT_TILE_FARM_ALERT_UNIQUE_TILE_THRESHOLD),
  );
  const untaggedMinRequests = Math.max(
    0,
    parseRateLimitInteger(env.TILE_FARM_ALERT_UNTAGGED_MIN_REQUESTS, DEFAULT_TILE_FARM_ALERT_UNTAGGED_MIN_REQUESTS),
  );
  const untaggedPercentThreshold = Math.min(
    100,
    Math.max(1, parseRateLimitInteger(env.TILE_FARM_ALERT_UNTAGGED_PERCENT, DEFAULT_TILE_FARM_ALERT_UNTAGGED_PERCENT)),
  );
  const emailCooldownSeconds = Math.max(
    30,
    parseRateLimitInteger(
      env.TILE_FARM_ALERT_EMAIL_COOLDOWN_SECONDS,
      DEFAULT_TILE_FARM_ALERT_EMAIL_COOLDOWN_SECONDS,
    ),
  );

  const userRate = await consumeRateLimitWindow(db, "tile_farm_user_req", userKey, 2147483647, windowSeconds);
  const userCount = clampNonNegativeInt(userRate && userRate.count);
  const ipRate = await consumeRateLimitWindow(db, "tile_farm_ip_req", ip, 2147483647, windowSeconds);
  const ipCount = clampNonNegativeInt(ipRate && ipRate.count);

  let uniqueTileCount = 0;
  if (tileKey) {
    const tileSeen = await consumeRateLimitWindow(
      db,
      "tile_farm_user_tile_seen",
      `${userKey}:${tileKey}`,
      2147483647,
      windowSeconds,
    );
    if (clampNonNegativeInt(tileSeen && tileSeen.count) === 1) {
      const uniqueRate = await consumeRateLimitWindow(
        db,
        "tile_farm_user_unique",
        userKey,
        2147483647,
        windowSeconds,
      );
      uniqueTileCount = clampNonNegativeInt(uniqueRate && uniqueRate.count);
    }
  }

  let untaggedCount = 0;
  if (!resolveId) {
    const untaggedRate = await consumeRateLimitWindow(
      db,
      "tile_farm_user_untagged",
      userKey,
      2147483647,
      windowSeconds,
    );
    untaggedCount = clampNonNegativeInt(untaggedRate && untaggedRate.count);
  }

  const reasons = [];
  if (userRequestThreshold > 0 && thresholdHit(userCount, userRequestThreshold)) {
    reasons.push(`user_request_rate:${userCount}/${userRequestThreshold}`);
  }
  if (ipRequestThreshold > 0 && thresholdHit(ipCount, ipRequestThreshold)) {
    reasons.push(`ip_request_rate:${ipCount}/${ipRequestThreshold}`);
  }
  if (uniqueTileThreshold > 0 && uniqueTileCount > 0 && thresholdHit(uniqueTileCount, uniqueTileThreshold)) {
    reasons.push(`unique_tiles:${uniqueTileCount}/${uniqueTileThreshold}`);
  }
  if (
    untaggedCount > 0
    && userCount >= untaggedMinRequests
    && ((untaggedCount * 100) / Math.max(1, userCount)) >= untaggedPercentThreshold
  ) {
    reasons.push(`untagged_ratio:${untaggedCount}/${userCount}>=${untaggedPercentThreshold}%`);
  }
  if (!reasons.length) {
    return;
  }

  const alertGate = await consumeRateLimitWindow(
    db,
    "tile_farm_alert_mail",
    `${userKey}:${ip}`,
    1,
    emailCooldownSeconds,
  );
  if (!alertGate.allowed) {
    return;
  }

  try {
    await sendOpsAlertEmail(
      env,
      "Planetka suspected tile farming activity",
      [
        "Potential tile farming pattern detected (real-time).",
        `reasons=${reasons.join(",")}`,
        `user_id=${userId}`,
        `email=${userEmail}`,
        `ip=${ip}`,
        `device_id=${deviceId}`,
        `status_code=${statusCode}`,
        `method=${method}`,
        `path=${path}`,
        `tile_key=${tileKey}`,
        `resolve_id=${resolveId}`,
        `window_seconds=${windowSeconds}`,
        `user_count=${userCount}`,
        `ip_count=${ipCount}`,
        `unique_tile_count=${uniqueTileCount}`,
        `untagged_count=${untaggedCount}`,
      ],
    );
  } catch (error) {
    console.warn(
      "worker.tile_farm_alert_email_failed",
      JSON.stringify({
        user_id: userId,
        email: userEmail,
        ip,
        error: String(error && error.message || "tile_farm_alert_email_failed"),
      }),
    );
  }
}

function parseHeavyUserPlanFilter(value) {
  const normalized = String(value || "all").trim().toLowerCase();
  if (
    normalized === "trial"
    || normalized === "free"
    || normalized === "lite"
    || normalized === PLAN_CODE_PLANETKA
  ) {
    return "lite";
  }
  if (
    normalized === "active"
    || normalized === "paid"
    || normalized === "pro"
    || normalized === PLAN_CODE_PLANETKA_PRO
    || normalized === PLAN_CODE_PLANETKA_STUDIO
    || normalized === "studio"
  ) {
    return "pro";
  }
  return "all";
}

function parseAnalyticsExcludedEmailPatterns(env = {}) {
  const source = String(
    env.ANALYTICS_EXCLUDED_EMAIL_PATTERNS || DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS,
  ).trim();
  if (!source) {
    return [];
  }
  const unique = new Set();
  for (const token of source.split(",")) {
    const pattern = String(token || "").trim().toLowerCase();
    if (!pattern) continue;
    unique.add(pattern);
  }
  return Array.from(unique);
}

function buildAnalyticsExcludedEmailFilter(emailColumnSql, env = {}) {
  const patterns = parseAnalyticsExcludedEmailPatterns(env);
  if (!patterns.length) {
    return { condition: "", bindings: [] };
  }
  const safeColumn = String(emailColumnSql || "").trim() || "user_email";
  const condition = patterns
    .map(() => `LOWER(COALESCE(${safeColumn}, '')) NOT LIKE ?`)
    .join(" AND ");
  return { condition, bindings: patterns };
}

function buildHeavyUserFilterSql(planFilter) {
  if (planFilter === "lite") {
    return { clause: "WHERE c.plan_code = ?", bindings: [PLAN_CODE_PLANETKA] };
  }
  if (planFilter === "pro") {
    return {
      clause: "WHERE c.plan_code IN (?, ?)",
      bindings: [PLAN_CODE_PLANETKA_PRO, PLAN_CODE_PLANETKA_STUDIO],
    };
  }
  return { clause: "", bindings: [] };
}

function buildTileActivityPlanFilterSql(planFilter) {
  if (planFilter === "lite") {
    return {
      clause: `
        AND COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) = ?
      `,
      bindings: [PLAN_CODE_PLANETKA, PLAN_CODE_PLANETKA],
    };
  }
  if (planFilter === "pro") {
    return {
      clause: `
        AND COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) IN (?, ?)
      `,
      bindings: [PLAN_CODE_PLANETKA, PLAN_CODE_PLANETKA_PRO, PLAN_CODE_PLANETKA_STUDIO],
    };
  }
  return { clause: "", bindings: [] };
}

function parseAnalyticsUsersSort(value) {
  const normalized = String(value || "").trim().toLowerCase();
  const allowed = new Set(["resolves", "lifetime", "month", "week", "day", "hour", "last_seen"]);
  return allowed.has(normalized) ? normalized : "month";
}

function parseAnalyticsUsersSortDirection(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "asc" ? "asc" : "desc";
}

async function listAnalyticsUsers(db, env, options = {}) {
  await ensureTileRequestEventsTable(db);
  const sortBy = parseAnalyticsUsersSort(options.sort_by);
  const sortDir = parseAnalyticsUsersSortDirection(options.sort_dir);
  const query = String(options.query || "").trim().toLowerCase();
  const limit = Math.max(1, Math.min(5000, parseNonNegativeInteger(options.limit, 5000)));
  const nowUnix = Math.floor(Date.now() / 1000);
  const orderSqlByKey = {
    resolves: "resolve_count",
    lifetime: "lifetime_bytes",
    month: "month_bytes",
    week: "week_bytes",
    day: "day_bytes",
    hour: "hour_bytes",
    last_seen: "last_seen_unix",
  };
  const orderSql = orderSqlByKey[sortBy] || orderSqlByKey.month;
  const emailFilter = buildAnalyticsExcludedEmailFilter("u.email", env);
  const whereParts = [];
  const bindings = [
    PLAN_CODE_PLANETKA_FREE,
    monthStartUnix(nowUnix),
    startOfWeekUnix(nowUnix),
    startOfDayUnix(nowUnix),
    startOfHourUnix(nowUnix),
    PLAN_CODE_PLANETKA_FREE,
    PLAN_CODE_PLANETKA_FREE,
  ];
  if (emailFilter.condition) {
    whereParts.push(emailFilter.condition);
    bindings.push(...emailFilter.bindings);
  }
  if (query) {
    whereParts.push(`LOWER(COALESCE(u.email, '')) LIKE ?`);
    bindings.push(`%${query}%`);
  }
  const whereSql = whereParts.length ? `WHERE ${whereParts.join(" AND ")}` : "";
  return dbAll(
    db,
    `
      WITH resolve_counts AS (
        SELECT
          user_id,
          COUNT(DISTINCT resolve_id) AS resolve_count
        FROM tile_request_events
        WHERE resolve_id IS NOT NULL AND resolve_id != ''
        GROUP BY user_id
      ),
      daily_usage AS (
        SELECT
          r.user_id,
          COALESCE(SUM(r.bytes_served), 0) AS lifetime_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS month_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS week_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS day_bytes,
          COALESCE(MAX(r.last_event_unix), 0) AS last_seen_unix
        FROM tile_request_rollup_daily_account r
        GROUP BY r.user_id
      ),
      hourly_usage AS (
        SELECT
          r.user_id,
          COALESCE(SUM(r.bytes_served), 0) AS hour_bytes
        FROM tile_request_rollup_hourly_account r
        WHERE r.bucket_start_unix >= ?
        GROUP BY r.user_id
      )
      SELECT
        u.id AS user_id,
        u.email AS user_email,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS user_status,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS plan_code,
        COALESCE(rc.resolve_count, 0) AS resolve_count,
        COALESCE(du.lifetime_bytes, 0) AS lifetime_bytes,
        COALESCE(du.month_bytes, 0) AS month_bytes,
        COALESCE(du.week_bytes, 0) AS week_bytes,
        COALESCE(du.day_bytes, 0) AS day_bytes,
        COALESCE(hu.hour_bytes, 0) AS hour_bytes,
        COALESCE(
          NULLIF(TRIM(datetime(du.last_seen_unix, 'unixepoch')), ''),
          COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), ''))
        ) AS last_seen_at,
        COALESCE(du.last_seen_unix, strftime('%s', COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), ''))), 0) AS last_seen_unix
      FROM users u
      LEFT JOIN daily_usage du ON du.user_id = u.id
      LEFT JOIN hourly_usage hu ON hu.user_id = u.id
      LEFT JOIN resolve_counts rc ON rc.user_id = u.id
      ${whereSql}
      ORDER BY ${orderSql} ${sortDir.toUpperCase()}, LOWER(COALESCE(u.email, '')) ASC
      LIMIT ${limit}
    `,
    bindings,
  );
}

async function cleanupAuthTables(db, env, nowTimestamp) {
  const nowUnix = Math.floor(Date.parse(nowTimestamp) / 1000) || Math.floor(Date.now() / 1000);
  const summary = {
    started_at: nowTimestamp,
    refresh_session_retention_days: Math.max(
      0,
      parseNonNegativeInteger(
        env.CLEANUP_REFRESH_SESSION_RETENTION_DAYS,
        DEFAULT_REFRESH_SESSION_CLEANUP_RETENTION_DAYS,
      ),
    ),
    refresh_sessions_deleted: 0,
    api_key_requests_deleted: 0,
    api_key_device_activity_deleted: 0,
    auth_refresh_event_retention_days: Math.max(
      7,
      parseNonNegativeInteger(
        env.CLEANUP_AUTH_REFRESH_EVENT_RETENTION_DAYS,
        DEFAULT_AUTH_REFRESH_EVENT_RETENTION_DAYS,
      ),
    ),
    tile_event_retention_days: Math.max(
      14,
      parseNonNegativeInteger(env.CLEANUP_TILE_EVENT_RETENTION_DAYS, DEFAULT_TILE_EVENT_RETENTION_DAYS),
    ),
    tile_rollup_retention_days: Math.max(
      60,
      parseNonNegativeInteger(env.CLEANUP_TILE_ROLLUP_RETENTION_DAYS, DEFAULT_TILE_ROLLUP_RETENTION_DAYS),
    ),
    tile_request_events_deleted: 0,
    tile_rollup_hourly_deleted: 0,
    tile_rollup_daily_deleted: 0,
    monthly_cost_alert_state_deleted: 0,
    auth_refresh_events_deleted: 0,
  };
  const refreshSessionCutoff = addDaysFromIso(
    nowTimestamp,
    -summary.refresh_session_retention_days,
  );
  const tileEventsCutoffUnix = Math.max(0, nowUnix - (summary.tile_event_retention_days * 86400));
  const authRefreshEventsCutoffUnix = Math.max(
    0,
    nowUnix - (summary.auth_refresh_event_retention_days * 86400),
  );
  const tileRollupCutoffUnix = Math.max(0, nowUnix - (summary.tile_rollup_retention_days * 86400));

  if (await dbTableExists(db, "refresh_sessions")) {
    const refreshSessionsResult = await dbRun(
      db,
      `
        DELETE FROM refresh_sessions
        WHERE
          (expires_at IS NOT NULL AND expires_at != '' AND expires_at < ?)
          OR
          (revoked_at IS NOT NULL AND revoked_at != '' AND revoked_at < ?)
      `,
      [refreshSessionCutoff, refreshSessionCutoff],
    );
    summary.refresh_sessions_deleted = dbMetaChanges(refreshSessionsResult);
  }

  if (await dbTableExists(db, "api_key_requests")) {
    await ensureApiKeyTables(db);
    const apiKeyRequestsResult = await dbRun(
      db,
      `
        DELETE FROM api_key_requests
        WHERE
          expires_at < ?
          OR (used_at IS NOT NULL AND used_at != '' AND used_at < ?)
      `,
      [
        nowTimestamp,
        refreshSessionCutoff,
      ],
    );
    summary.api_key_requests_deleted = dbMetaChanges(apiKeyRequestsResult);
  }

  if (await dbTableExists(db, "api_key_device_activity")) {
    const activeWindowSeconds = Math.max(
      60,
      Math.floor(parsePositiveNumber(env.API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS, DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS)),
    );
    const nowUnix = Math.floor(Date.parse(nowTimestamp) / 1000) || Math.floor(Date.now() / 1000);
    const cutoffUnix = Math.max(0, nowUnix - (activeWindowSeconds * 4));
    const deviceActivityResult = await dbRun(
      db,
      `
        DELETE FROM api_key_device_activity
        WHERE last_seen_unix < ?
      `,
      [cutoffUnix],
    );
    summary.api_key_device_activity_deleted = dbMetaChanges(deviceActivityResult);
  }

  if (await dbTableExists(db, "auth_refresh_events")) {
    const authRefreshEventsResult = await dbRun(
      db,
      `
        DELETE FROM auth_refresh_events
        WHERE created_at_unix < ?
      `,
      [authRefreshEventsCutoffUnix],
    );
    summary.auth_refresh_events_deleted = dbMetaChanges(authRefreshEventsResult);
  }

  if (await dbTableExists(db, "tile_request_events")) {
    const tileEventsResult = await dbRun(
      db,
      `
        DELETE FROM tile_request_events
        WHERE created_at_unix < ?
      `,
      [tileEventsCutoffUnix],
    );
    summary.tile_request_events_deleted = dbMetaChanges(tileEventsResult);
  }

  if (await dbTableExists(db, "tile_request_rollup_hourly_account")) {
    const hourlyRollupResult = await dbRun(
      db,
      `
        DELETE FROM tile_request_rollup_hourly_account
        WHERE bucket_start_unix < ?
      `,
      [tileRollupCutoffUnix],
    );
    summary.tile_rollup_hourly_deleted = dbMetaChanges(hourlyRollupResult);
  }

  if (await dbTableExists(db, "tile_request_rollup_daily_account")) {
    const dailyRollupResult = await dbRun(
      db,
      `
        DELETE FROM tile_request_rollup_daily_account
        WHERE day_start_unix < ?
      `,
      [tileRollupCutoffUnix],
    );
    summary.tile_rollup_daily_deleted = dbMetaChanges(dailyRollupResult);
  }

  if (await dbTableExists(db, "monthly_cost_alert_state")) {
    const monthlyStateCutoff = new Date(Date.parse(nowTimestamp) - (730 * 86400 * 1000)).toISOString().slice(0, 7);
    const monthlyStateResult = await dbRun(
      db,
      `
        DELETE FROM monthly_cost_alert_state
        WHERE month_key < ?
      `,
      [monthlyStateCutoff],
    );
    summary.monthly_cost_alert_state_deleted = dbMetaChanges(monthlyStateResult);
  }

  return summary;
}

async function countRowsFromQuery(db, sql, bindings = []) {
  const row = await dbGet(db, sql, bindings);
  return clampNonNegativeInt(row && (row.count ?? row.total ?? 0));
}

async function runProductionAlertChecks(db, env, nowTimestamp) {
  const nowUnix = Math.floor(Date.parse(nowTimestamp) / 1000) || Math.floor(Date.now() / 1000);
  const nowIsoValue = String(nowTimestamp || nowIso());
  const cooldownSeconds = Math.max(
    60,
    parseRateLimitInteger(env.PROD_ALERT_COOLDOWN_SECONDS, DEFAULT_ALERT_PROD_COOLDOWN_SECONDS),
  );
  const summary = {
    started_at: nowIsoValue,
    cooldown_seconds: cooldownSeconds,
    metrics: [],
  };

  const hasTileEvents = await dbTableExists(db, "tile_request_events");
  const metricSpecs = [
    {
      key: "http_403_spike",
      label: "HTTP 403 spike",
      threshold: parseRateLimitInteger(env.PROD_ALERT_403_THRESHOLD, DEFAULT_ALERT_PROD_403_THRESHOLD),
      windowSeconds: parseRateLimitInteger(env.PROD_ALERT_403_WINDOW_SECONDS, DEFAULT_ALERT_PROD_403_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `SELECT COUNT(*) AS count FROM tile_request_events WHERE created_at_unix >= ? AND status_code = 403`,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
    {
      key: "http_429_spike",
      label: "HTTP 429 spike",
      threshold: parseRateLimitInteger(env.PROD_ALERT_429_THRESHOLD, DEFAULT_ALERT_PROD_429_THRESHOLD),
      windowSeconds: parseRateLimitInteger(env.PROD_ALERT_429_WINDOW_SECONDS, DEFAULT_ALERT_PROD_429_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `SELECT COUNT(*) AS count FROM tile_request_events WHERE created_at_unix >= ? AND status_code = 429`,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
    {
      key: "tile_miss_burst",
      label: "S2 tile miss burst",
      threshold: parseRateLimitInteger(env.PROD_ALERT_TILE_MISS_THRESHOLD, DEFAULT_ALERT_PROD_TILE_MISS_THRESHOLD),
      windowSeconds: parseRateLimitInteger(env.PROD_ALERT_TILE_MISS_WINDOW_SECONDS, DEFAULT_ALERT_PROD_TILE_MISS_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `
        SELECT COUNT(*) AS count
        FROM tile_request_events
        WHERE created_at_unix >= ?
          AND tile_key LIKE '%/S2/%'
          AND (
            error_code = 'tile_not_found'
            OR (status_code = 404 AND (error_code IS NULL OR error_code = '' OR error_code = 'tile_not_found'))
          )
      `,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
    {
      key: "tile_error_burst",
      label: "Tile error burst",
      threshold: parseRateLimitInteger(env.PROD_ALERT_TILE_ERROR_THRESHOLD, DEFAULT_ALERT_PROD_TILE_ERROR_THRESHOLD),
      windowSeconds: parseRateLimitInteger(env.PROD_ALERT_TILE_ERROR_WINDOW_SECONDS, DEFAULT_ALERT_PROD_TILE_ERROR_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `
        SELECT COUNT(*) AS count
        FROM tile_request_events
        WHERE created_at_unix >= ?
          AND (
            status_code >= 500
            OR error_code = 'internal_error'
          )
      `,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
  ];

  for (const metric of metricSpecs) {
    const metricSummary = {
      key: metric.key,
      label: metric.label,
      threshold: clampNonNegativeInt(metric.threshold),
      window_seconds: clampNonNegativeInt(metric.windowSeconds),
      count: 0,
      triggered: false,
      suppressed_by_cooldown: false,
      disabled: false,
      unavailable: false,
      error: "",
    };
    try {
      if (!metric.tableAvailable) {
        metricSummary.unavailable = true;
        summary.metrics.push(metricSummary);
        continue;
      }
      if (metricSummary.threshold <= 0 || metricSummary.window_seconds <= 0) {
        metricSummary.disabled = true;
        summary.metrics.push(metricSummary);
        continue;
      }
      const windowStartUnix = Math.max(0, nowUnix - metricSummary.window_seconds);
      metricSummary.count = await countRowsFromQuery(
        db,
        metric.countSql,
        metric.countBindings(windowStartUnix),
      );
      if (metricSummary.count < metricSummary.threshold) {
        summary.metrics.push(metricSummary);
        continue;
      }

      await ensureRateLimitsTable(db);
      const alertRate = await consumeRateLimitWindow(
        db,
        "prod_alert_mail",
        metric.key,
        1,
        cooldownSeconds,
      );
      if (!alertRate.allowed || clampNonNegativeInt(alertRate.count) > 1) {
        metricSummary.suppressed_by_cooldown = true;
        summary.metrics.push(metricSummary);
        continue;
      }

      metricSummary.triggered = true;
      const metricWindowStart = new Date(Math.max(0, nowUnix - metricSummary.window_seconds) * 1000).toISOString();
      await sendOpsAlertEmail(
        env,
        `Planetka production alert: ${metric.label}`,
        [
          `metric=${metric.key}`,
          `count=${metricSummary.count}`,
          `threshold=${metricSummary.threshold}`,
          `window_seconds=${metricSummary.window_seconds}`,
          `window_start_utc=${metricWindowStart}`,
          `window_end_utc=${nowIsoValue}`,
          `cooldown_seconds=${cooldownSeconds}`,
        ],
      );
    } catch (error) {
      metricSummary.error = String(error && error.message || "metric_alert_failed");
      console.warn(
        "worker.production_alert.metric_failed",
        JSON.stringify({
          metric: metric.key,
          error: metricSummary.error,
        }),
      );
    }
    summary.metrics.push(metricSummary);
  }
  return summary;
}

function monthKeyFromUnix(epochSeconds) {
  const safeUnix = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  return new Date(safeUnix * 1000).toISOString().slice(0, 7);
}

function monthStartUnix(epochSeconds) {
  const safeUnix = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  const date = new Date(safeUnix * 1000);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  return Math.floor(Date.UTC(year, month, 1, 0, 0, 0) / 1000);
}

function monthStartIso(epochSeconds) {
  return new Date(monthStartUnix(epochSeconds) * 1000).toISOString();
}

const R2_CLASS_A_ACTION_TYPES = new Set([
  "listbuckets",
  "putbucket",
  "listobjects",
  "putobject",
  "copyobject",
  "completemultipartupload",
  "createmultipartupload",
  "lifecyclestoragetiertransition",
  "listmultipartuploads",
  "uploadpart",
  "uploadpartcopy",
  "listparts",
  "putbucketencryption",
  "putbucketcors",
  "putbucketlifecycleconfiguration",
]);

const R2_CLASS_B_ACTION_TYPES = new Set([
  "headbucket",
  "headobject",
  "getobject",
  "usagesummary",
  "getbucketencryption",
  "getbucketlocation",
  "getbucketcors",
  "getbucketlifecycleconfiguration",
]);

async function buildFallbackBillableUsageFromTelemetry(env, db, reason = "fallback_estimate") {
  const nowUnix = Math.floor(Date.now() / 1000);
  const startDate = monthStartIso(nowUnix);
  const endDate = new Date(nowUnix * 1000).toISOString();
  let monthClassBOps = 0;
  if (db) {
    monthClassBOps = await countRowsFromQuery(
      db,
      `
        SELECT COUNT(*) AS count
        FROM tile_request_events
        WHERE created_at_unix >= ?
      `,
      [monthStartUnix(nowUnix)],
    );
  }
  const estimate = estimateR2MonthlyCostUsd(env, monthClassBOps);
  return {
    available: true,
    estimated: true,
    source: "telemetry_estimate",
    reason,
    period_start: startDate,
    period_end: endDate,
    bucket_filter: "",
    generated_at: nowIso(),
    storage: {
      bytes: Math.max(0, Math.floor(Number(estimate.storage_gb_estimate || 0) * BYTES_PER_GB)),
      gb: Number(Number(estimate.storage_gb_estimate || 0).toFixed(3)),
      object_count: 0,
      upload_count: 0,
      sample_datetime: "",
      free_gb: clampNonNegativeInt(estimate.storage_gb_free),
      billable_gb_rounded: clampNonNegativeInt(estimate.storage_gb_billable_rounded),
    },
    class_a: {
      operations: clampNonNegativeInt(estimate.class_a_ops_estimate),
      free_operations: clampNonNegativeInt(estimate.class_a_ops_free),
      billable_operations: clampNonNegativeInt(estimate.class_a_ops_billable),
      billable_million_rounded: clampNonNegativeInt(estimate.class_a_million_billable_rounded),
    },
    class_b: {
      operations: clampNonNegativeInt(estimate.class_b_ops_month),
      free_operations: clampNonNegativeInt(estimate.class_b_ops_free),
      billable_operations: clampNonNegativeInt(estimate.class_b_ops_billable),
      billable_million_rounded: clampNonNegativeInt(estimate.class_b_million_billable_rounded),
    },
    unknown_operations: 0,
    estimated_cost_usd: {
      storage: Number(Number(estimate.storage_cost_usd || 0).toFixed(2)),
      class_a: Number(Number(estimate.class_a_cost_usd || 0).toFixed(2)),
      class_b: Number(Number(estimate.class_b_cost_usd || 0).toFixed(2)),
      total: Number(Number(estimate.total_cost_usd || 0).toFixed(2)),
    },
  };
}

async function fetchCloudflareR2BillableUsage(env, db = null) {
  const accountTag = String(
    env.CLOUDFLARE_ACCOUNT_ID
    || env.CF_ACCOUNT_ID
    || "",
  ).trim();
  const apiToken = String(
    env.CLOUDFLARE_GRAPHQL_API_TOKEN
    || env.CLOUDFLARE_API_TOKEN
    || "",
  ).trim();
  if (!accountTag || !apiToken) {
    try {
      return await buildFallbackBillableUsageFromTelemetry(env, db, "missing_graphql_credentials");
    } catch (_error) {
      return {
        available: false,
        source: "cloudflare_graphql",
        reason: "not_configured",
        message: "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_GRAPHQL_API_TOKEN to display billable usage.",
      };
    }
  }
  const nowUnix = Math.floor(Date.now() / 1000);
  const startDate = monthStartIso(nowUnix);
  const endDate = new Date(nowUnix * 1000).toISOString();
  const bucketName = String(
    env.CLOUDFLARE_R2_BILLING_BUCKET
    || env.R2_BILLING_BUCKET
    || "",
  ).trim();
  const ttlSeconds = Math.max(
    30,
    parseNonNegativeInteger(
      env.CLOUDFLARE_BILLABLE_CACHE_TTL_SECONDS,
      DEFAULT_CLOUDFLARE_BILLABLE_CACHE_TTL_SECONDS,
    ),
  );
  const cacheKey = [accountTag, bucketName || "*", startDate.slice(0, 7)].join("::");
  const nowMs = Date.now();
  if (
    cloudflareR2BillableUsageCache.cacheKey === cacheKey
    && cloudflareR2BillableUsageCache.value
    && nowMs < cloudflareR2BillableUsageCache.expiresAtMs
  ) {
    return cloudflareR2BillableUsageCache.value;
  }

  const hasBucketFilter = Boolean(bucketName);
  const query = `
    query PlanetkaR2BillableUsage($accountTag: string!, $startDate: Time!, $endDate: Time!${hasBucketFilter ? ", $bucketName: string!" : ""}) {
      viewer {
        accounts(filter: { accountTag: $accountTag }) {
          r2OperationsAdaptiveGroups(
            limit: 10000
            filter: {
              datetime_geq: $startDate
              datetime_leq: $endDate
              ${hasBucketFilter ? "bucketName: $bucketName" : ""}
            }
          ) {
            sum {
              requests
            }
            dimensions {
              actionType
            }
          }
          r2StorageAdaptiveGroups(
            limit: 1
            filter: {
              datetime_leq: $endDate
              ${hasBucketFilter ? "bucketName: $bucketName" : ""}
            }
            orderBy: [datetime_DESC]
          ) {
            max {
              objectCount
              uploadCount
              payloadSize
              metadataSize
            }
            dimensions {
              datetime
              bucketName
            }
          }
        }
      }
    }
  `;
  const variables = {
    accountTag,
    startDate,
    endDate,
    ...(hasBucketFilter ? { bucketName } : {}),
  };

  try {
    const response = await fetch(
      "https://api.cloudflare.com/client/v4/graphql",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query, variables }),
      },
    );
    const payload = await response.json();
    const errors = Array.isArray(payload && payload.errors) ? payload.errors : [];
    if (!response.ok || errors.length > 0) {
      const errorMessage = errors.length > 0
        ? String(errors[0] && errors[0].message || "graphql_error")
        : String(payload && payload.errors || `http_${response.status}`);
      try {
        const fallback = await buildFallbackBillableUsageFromTelemetry(env, db, "graphql_query_failed");
        fallback.message = publicErrorMessage("Usage data is temporarily unavailable.");
        return fallback;
      } catch (_error) {
        return {
          available: false,
          source: "cloudflare_graphql",
          reason: "query_failed",
          message: errorMessage,
        };
      }
    }

    const accounts = (((payload || {}).data || {}).viewer || {}).accounts;
    const account = Array.isArray(accounts) && accounts.length > 0 ? accounts[0] : null;
    const opRows = Array.isArray(account && account.r2OperationsAdaptiveGroups)
      ? account.r2OperationsAdaptiveGroups
      : [];
    const storageRows = Array.isArray(account && account.r2StorageAdaptiveGroups)
      ? account.r2StorageAdaptiveGroups
      : [];

    let classAOps = 0;
    let classBOps = 0;
    let unknownOps = 0;
    for (const row of opRows) {
      const actionType = String(((row || {}).dimensions || {}).actionType || "").trim().toLowerCase();
      const requests = clampNonNegativeInt(((row || {}).sum || {}).requests);
      if (!actionType) {
        unknownOps += requests;
        continue;
      }
      if (R2_CLASS_A_ACTION_TYPES.has(actionType)) {
        classAOps += requests;
      } else if (R2_CLASS_B_ACTION_TYPES.has(actionType)) {
        classBOps += requests;
      } else {
        unknownOps += requests;
      }
    }

    const storageRow = storageRows.length > 0 ? storageRows[0] : null;
    const storageMax = (storageRow && storageRow.max) || {};
    const payloadBytes = clampNonNegativeInt(storageMax.payloadSize);
    const metadataBytes = clampNonNegativeInt(storageMax.metadataSize);
    const totalStorageBytes = payloadBytes + metadataBytes;
    const storageGb = totalStorageBytes / BYTES_PER_GB;
    const classAFreeOps = parseNonNegativeInteger(env.R2_CLASS_A_FREE_OPS_PER_MONTH, DEFAULT_R2_CLASS_A_FREE_OPS_PER_MONTH);
    const classBFreeOps = parseNonNegativeInteger(env.R2_CLASS_B_FREE_OPS_PER_MONTH, DEFAULT_R2_CLASS_B_FREE_OPS_PER_MONTH);
    const storageFreeGb = parseNonNegativeInteger(env.R2_STORAGE_FREE_GB_MONTH, DEFAULT_R2_STORAGE_FREE_GB_MONTH);
    const classAPricePerMillion = parsePositiveNumber(
      env.R2_CLASS_A_PRICE_PER_MILLION_USD,
      DEFAULT_R2_CLASS_A_PRICE_PER_MILLION_USD,
    );
    const classBPricePerMillion = parsePositiveNumber(
      env.R2_CLASS_B_PRICE_PER_MILLION_USD,
      DEFAULT_R2_CLASS_B_PRICE_PER_MILLION_USD,
    );
    const storagePricePerGbMonth = parsePositiveNumber(
      env.R2_STORAGE_PRICE_PER_GB_MONTH_USD,
      DEFAULT_R2_STORAGE_PRICE_PER_GB_MONTH_USD,
    );

    const classABillableOps = Math.max(0, classAOps - classAFreeOps);
    const classBBillableOps = Math.max(0, classBOps - classBFreeOps);
    const classABillableMillionRounded = classABillableOps > 0 ? Math.ceil(classABillableOps / 1000000) : 0;
    const classBBillableMillionRounded = classBBillableOps > 0 ? Math.ceil(classBBillableOps / 1000000) : 0;
    const storageBillableGbRounded = Math.max(0, Math.ceil(storageGb - storageFreeGb));
    const storageCostUsd = storageBillableGbRounded * storagePricePerGbMonth;
    const classACostUsd = classABillableMillionRounded * classAPricePerMillion;
    const classBCostUsd = classBBillableMillionRounded * classBPricePerMillion;
    const totalEstimatedUsd = storageCostUsd + classACostUsd + classBCostUsd;

    const result = {
      available: true,
      source: "cloudflare_graphql",
      period_start: startDate,
      period_end: endDate,
      bucket_filter: bucketName || "",
      generated_at: nowIso(),
      storage: {
        bytes: totalStorageBytes,
        gb: Number(storageGb.toFixed(3)),
        object_count: clampNonNegativeInt(storageMax.objectCount),
        upload_count: clampNonNegativeInt(storageMax.uploadCount),
        sample_datetime: String(((storageRow || {}).dimensions || {}).datetime || ""),
        free_gb: storageFreeGb,
        billable_gb_rounded: storageBillableGbRounded,
      },
      class_a: {
        operations: classAOps,
        free_operations: classAFreeOps,
        billable_operations: classABillableOps,
        billable_million_rounded: classABillableMillionRounded,
      },
      class_b: {
        operations: classBOps,
        free_operations: classBFreeOps,
        billable_operations: classBBillableOps,
        billable_million_rounded: classBBillableMillionRounded,
      },
      unknown_operations: unknownOps,
      estimated_cost_usd: {
        storage: Number(storageCostUsd.toFixed(2)),
        class_a: Number(classACostUsd.toFixed(2)),
        class_b: Number(classBCostUsd.toFixed(2)),
        total: Number(totalEstimatedUsd.toFixed(2)),
      },
    };
    cloudflareR2BillableUsageCache = {
      cacheKey,
      value: result,
      expiresAtMs: nowMs + (ttlSeconds * 1000),
    };
    return result;
  } catch (error) {
    try {
      const fallback = await buildFallbackBillableUsageFromTelemetry(env, db, "graphql_request_failed");
      fallback.message = publicErrorMessage("Usage data is temporarily unavailable.");
      return fallback;
    } catch (_error) {
      return {
        available: false,
        source: "cloudflare_graphql",
        reason: "request_failed",
        message: publicErrorMessage("Usage data is temporarily unavailable."),
      };
    }
  }
}

function estimateR2MonthlyCostUsd(env, monthlyClassBOps) {
  const storageGb = parsePositiveNumber(env.R2_ESTIMATED_STORAGE_GB, DEFAULT_R2_ESTIMATED_STORAGE_GB);
  const storagePricePerGbMonth = parsePositiveNumber(
    env.R2_STORAGE_PRICE_PER_GB_MONTH_USD,
    DEFAULT_R2_STORAGE_PRICE_PER_GB_MONTH_USD,
  );
  const storageFreeGb = parseNonNegativeInteger(env.R2_STORAGE_FREE_GB_MONTH, DEFAULT_R2_STORAGE_FREE_GB_MONTH);
  const classAPricePerMillion = parsePositiveNumber(
    env.R2_CLASS_A_PRICE_PER_MILLION_USD,
    DEFAULT_R2_CLASS_A_PRICE_PER_MILLION_USD,
  );
  const classBPricePerMillion = parsePositiveNumber(
    env.R2_CLASS_B_PRICE_PER_MILLION_USD,
    DEFAULT_R2_CLASS_B_PRICE_PER_MILLION_USD,
  );
  const classAFreeOps = parseNonNegativeInteger(env.R2_CLASS_A_FREE_OPS_PER_MONTH, DEFAULT_R2_CLASS_A_FREE_OPS_PER_MONTH);
  const classBFreeOps = parseNonNegativeInteger(env.R2_CLASS_B_FREE_OPS_PER_MONTH, DEFAULT_R2_CLASS_B_FREE_OPS_PER_MONTH);
  const estimatedClassAOps = parseNonNegativeInteger(env.R2_ESTIMATED_CLASS_A_OPS_MONTH, 0);
  const classBOps = Math.max(0, clampNonNegativeInt(monthlyClassBOps));

  const billableStorageGb = Math.max(0, Math.ceil(storageGb - storageFreeGb));
  const billableClassAOps = Math.max(0, estimatedClassAOps - classAFreeOps);
  const billableClassBOps = Math.max(0, classBOps - classBFreeOps);
  const billableClassAMillion = billableClassAOps > 0 ? Math.ceil(billableClassAOps / 1000000) : 0;
  const billableClassBMillion = billableClassBOps > 0 ? Math.ceil(billableClassBOps / 1000000) : 0;

  const storageCostUsd = billableStorageGb * storagePricePerGbMonth;
  const classACostUsd = billableClassAMillion * classAPricePerMillion;
  const classBCostUsd = billableClassBMillion * classBPricePerMillion;
  const totalCostUsd = storageCostUsd + classACostUsd + classBCostUsd;

  return {
    storage_gb_estimate: storageGb,
    storage_gb_free: storageFreeGb,
    storage_gb_billable_rounded: billableStorageGb,
    storage_cost_usd: storageCostUsd,
    class_a_ops_estimate: estimatedClassAOps,
    class_a_ops_free: classAFreeOps,
    class_a_ops_billable: billableClassAOps,
    class_a_million_billable_rounded: billableClassAMillion,
    class_a_cost_usd: classACostUsd,
    class_b_ops_month: classBOps,
    class_b_ops_free: classBFreeOps,
    class_b_ops_billable: billableClassBOps,
    class_b_million_billable_rounded: billableClassBMillion,
    class_b_cost_usd: classBCostUsd,
    total_cost_usd: totalCostUsd,
  };
}

async function runMonthlyCostEstimateAlerts(db, env, nowTimestamp) {
  await ensureRateLimitsTable(db);
  await ensureMonthlyCostAlertStateTable(db);
  await ensureTileRequestEventsTable(db);
  const nowUnix = Math.floor(Date.parse(String(nowTimestamp || nowIso())) / 1000) || Math.floor(Date.now() / 1000);
  const nowIsoValue = String(nowTimestamp || nowIso());
  const monthStart = monthStartUnix(nowUnix);
  const monthKey = monthKeyFromUnix(nowUnix);
  const monthClassBOps = await countRowsFromQuery(
    db,
    `
      SELECT COUNT(*) AS count
      FROM tile_request_events
      WHERE created_at_unix >= ?
        AND path LIKE '/tiles/%'
    `,
    [monthStart],
  );
  const estimate = estimateR2MonthlyCostUsd(env, monthClassBOps);

  const baseUsd = Math.max(0, parseNonNegativeInteger(env.MONTHLY_COST_ALERT_BASE_USD, DEFAULT_MONTHLY_COST_ALERT_BASE_USD));
  const stepUsd = Math.max(1, parseNonNegativeInteger(env.MONTHLY_COST_ALERT_STEP_USD, DEFAULT_MONTHLY_COST_ALERT_STEP_USD));
  const state = await dbGet(
    db,
    `
      SELECT
        month_key,
        last_notified_mark_usd,
        last_estimated_usd,
        last_alert_at,
        updated_at
      FROM monthly_cost_alert_state
      WHERE month_key = ?
      LIMIT 1
    `,
    [monthKey],
  );
  const lastNotifiedMark = clampNonNegativeInt(state && state.last_notified_mark_usd);
  const totalCostRounded = Number(estimate.total_cost_usd.toFixed(2));
  let highestCrossedMark = 0;
  if (totalCostRounded >= (baseUsd + stepUsd)) {
    const markIndex = Math.floor((totalCostRounded - baseUsd) / stepUsd);
    highestCrossedMark = baseUsd + (markIndex * stepUsd);
  }

  let notifiedMarkUsd = lastNotifiedMark;
  if (highestCrossedMark > lastNotifiedMark) {
    await sendOpsAlertEmail(
      env,
      "Planetka estimated monthly Cloud cost crossed threshold",
      [
        `month=${monthKey}`,
        `estimated_total_usd=${totalCostRounded.toFixed(2)}`,
        `threshold_crossed_usd=${highestCrossedMark}`,
        `base_usd=${baseUsd}`,
        `step_usd=${stepUsd}`,
        `r2_storage_gb_estimate=${estimate.storage_gb_estimate}`,
        `r2_storage_gb_billable_rounded=${estimate.storage_gb_billable_rounded}`,
        `r2_storage_cost_usd=${estimate.storage_cost_usd.toFixed(2)}`,
        `r2_class_a_ops_estimate=${estimate.class_a_ops_estimate}`,
        `r2_class_a_million_billable_rounded=${estimate.class_a_million_billable_rounded}`,
        `r2_class_a_cost_usd=${estimate.class_a_cost_usd.toFixed(2)}`,
        `r2_class_b_ops_month=${estimate.class_b_ops_month}`,
        `r2_class_b_million_billable_rounded=${estimate.class_b_million_billable_rounded}`,
        `r2_class_b_cost_usd=${estimate.class_b_cost_usd.toFixed(2)}`,
        "note=Estimate based on configured R2 storage GB and monthly tile operation telemetry.",
      ],
    );
    notifiedMarkUsd = highestCrossedMark;
  }

  const updatedAt = nowIso();
  await dbRun(
    db,
    `
      INSERT INTO monthly_cost_alert_state (
        month_key,
        last_notified_mark_usd,
        last_estimated_usd,
        last_alert_at,
        updated_at,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(month_key) DO UPDATE SET
        last_notified_mark_usd = excluded.last_notified_mark_usd,
        last_estimated_usd = excluded.last_estimated_usd,
        last_alert_at = excluded.last_alert_at,
        updated_at = excluded.updated_at
    `,
    [
      monthKey,
      notifiedMarkUsd,
      totalCostRounded,
      highestCrossedMark > lastNotifiedMark ? updatedAt : String(state && state.last_alert_at || ""),
      updatedAt,
      updatedAt,
    ],
  );

  return {
    month: monthKey,
    base_usd: baseUsd,
    step_usd: stepUsd,
    estimated_total_usd: totalCostRounded,
    last_notified_mark_usd: notifiedMarkUsd,
    threshold_crossed_usd: highestCrossedMark > lastNotifiedMark ? highestCrossedMark : 0,
    storage_cost_usd: Number(estimate.storage_cost_usd.toFixed(2)),
    class_a_cost_usd: Number(estimate.class_a_cost_usd.toFixed(2)),
    class_b_cost_usd: Number(estimate.class_b_cost_usd.toFixed(2)),
    class_b_ops_month: estimate.class_b_ops_month,
  };
}

async function buildAccountState(db, user, subscription, env) {
  void db;
  const planCode = resolvePlanCode(user, subscription, env);
  return {
    planCode,
    commercialUseAllowed: commercialUseAllowed(planCode),
    upgradeUrl: String(env.UPGRADE_URL || DEFAULT_UPGRADE_URL).trim() || DEFAULT_UPGRADE_URL,
    contactUrl: normalizeContactUrl(env.PLANETKA_CONTACT_URL || DEFAULT_CONTACT_URL),
  };
}

function serializeAccountState(state) {
  const safeState = state || {};
  const tier = accountTierForPlanCode(safeState.planCode);
  return {
    plan: {
      code: safeState.planCode,
    },
    plan_code: safeState.planCode,
    account_tier: tier,
    commercial_use_allowed: Boolean(safeState.commercialUseAllowed),
    upgrade_url: safeState.upgradeUrl,
    contact_url: safeState.contactUrl,
  };
}

async function findUserByEmail(db, email) {
  return dbGet(
    db,
    `
      SELECT
        u.id,
        u.email,
        u.status,
        u.created_at,
        u.last_login_at
      FROM users u
      WHERE u.email = ?
      LIMIT 1
    `,
    [email],
  );
}

async function findUserById(db, userId) {
  return dbGet(
    db,
    `
      SELECT
        u.id,
        u.email,
        u.status,
        u.created_at,
        u.last_login_at
      FROM users u
      WHERE u.id = ?
      LIMIT 1
    `,
    [userId],
  );
}

async function ensureNewsletterSubscribersTable(db) {
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS newsletter_subscribers (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL DEFAULT 'unknown',
        opted_in_at TEXT NOT NULL,
        last_opt_in_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_newsletter_subscribers_last_opt_in ON newsletter_subscribers(last_opt_in_at DESC)`,
  );
}

async function ensureStripeWebhookEventsTable(db) {
  if (stripeWebhookEventsTableReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS stripe_webhook_events (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        stripe_created INTEGER,
        received_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_stripe_webhook_events_received_at ON stripe_webhook_events(received_at DESC)`,
  );
  stripeWebhookEventsTableReady = true;
}

async function recordNewsletterOptIn(db, email, source = "unknown") {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail || !normalizedEmail.includes("@")) {
    return;
  }
  await ensureNewsletterSubscribersTable(db);
  const now = nowIso();
  await dbRun(
    db,
    `
      INSERT INTO newsletter_subscribers (
        id,
        email,
        source,
        opted_in_at,
        last_opt_in_at
      ) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(email) DO UPDATE SET
        source = excluded.source,
        last_opt_in_at = excluded.last_opt_in_at
    `,
    [crypto.randomUUID(), normalizedEmail, String(source || "unknown"), now, now],
  );
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
  const statements = [];
  if (!names.has("terms_accepted_at")) {
    statements.push(`ALTER TABLE users ADD COLUMN terms_accepted_at TEXT`);
  }
  if (!names.has("privacy_accepted_at")) {
    statements.push(`ALTER TABLE users ADD COLUMN privacy_accepted_at TEXT`);
  }
  if (!names.has("terms_version")) {
    statements.push(`ALTER TABLE users ADD COLUMN terms_version TEXT`);
  }
  if (!names.has("privacy_version")) {
    statements.push(`ALTER TABLE users ADD COLUMN privacy_version TEXT`);
  }
  for (const statement of statements) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  userConsentColumnsReady = true;
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
  const apiKeyRequestPragma = await db.prepare(`PRAGMA table_info(api_key_requests)`).all();
  const apiKeyRequestRows = Array.isArray(apiKeyRequestPragma && apiKeyRequestPragma.results)
    ? apiKeyRequestPragma.results
    : [];
  const apiKeyRequestNames = new Set(
    apiKeyRequestRows.map((row) => String(row && row.name || "").trim().toLowerCase()),
  );
  const apiKeyRequestStatements = [];
  if (!apiKeyRequestNames.has("request_ip")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN request_ip TEXT`);
  }
  if (!apiKeyRequestNames.has("accept_terms")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN accept_terms INTEGER NOT NULL DEFAULT 0`);
  }
  if (!apiKeyRequestNames.has("accept_privacy")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN accept_privacy INTEGER NOT NULL DEFAULT 0`);
  }
  if (!apiKeyRequestNames.has("opt_in_news")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN opt_in_news INTEGER NOT NULL DEFAULT 0`);
  }
  if (!apiKeyRequestNames.has("submitted_at_ms")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN submitted_at_ms INTEGER NOT NULL DEFAULT 0`);
  }
  if (!apiKeyRequestNames.has("request_device_id")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN request_device_id TEXT`);
  }
  if (!apiKeyRequestNames.has("created_at")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN created_at TEXT`);
  }
  for (const statement of apiKeyRequestStatements) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  if (!apiKeyRequestNames.has("created_at")) {
    await dbRun(
      db,
      `
        UPDATE api_key_requests
        SET created_at = COALESCE(
          NULLIF(created_at, ''),
          NULLIF(used_at, ''),
          NULLIF(expires_at, ''),
          ?
        )
        WHERE created_at IS NULL OR created_at = ''
      `,
      [nowIso()],
    );
  }
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_api_key_requests_email_created ON api_key_requests(email, created_at DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        key_hash TEXT NOT NULL UNIQUE,
        key_prefix TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        plan_code TEXT NOT NULL DEFAULT 'planetka',
        expires_at TEXT,
        issued_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_api_keys_user_status ON api_keys(user_id, status, issued_at DESC)`,
  );
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
  await dbRun(
    db,
    `CREATE UNIQUE INDEX IF NOT EXISTS idx_api_key_device_activity_unique ON api_key_device_activity(api_key_id, device_id)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_api_key_device_activity_user_seen ON api_key_device_activity(user_id, last_seen_unix DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_api_key_device_activity_user_device ON api_key_device_activity(user_id, device_id)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_api_key_device_activity_seen ON api_key_device_activity(last_seen_unix DESC)`,
  );
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
  const statements = [];
  if (!names.has("auth_method")) {
    statements.push(`ALTER TABLE refresh_sessions ADD COLUMN auth_method TEXT`);
  }
  if (!names.has("api_key_id")) {
    statements.push(`ALTER TABLE refresh_sessions ADD COLUMN api_key_id TEXT`);
  }
  if (!names.has("device_id")) {
    statements.push(`ALTER TABLE refresh_sessions ADD COLUMN device_id TEXT`);
  }
  for (const statement of statements) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  refreshSessionColumnsReady = true;
}

async function upsertUserByEmail(db, email, status = PLAN_CODE_PLANETKA_FREE, options = {}, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  await ensureUserConsentColumns(db);
  const requestedStatus = normalizePlanCode(status) || PLAN_CODE_PLANETKA_FREE;
  void env;
  let user = await findUserByEmail(db, normalizedEmail);
  if (user) {
    const currentStatus = String(user.status || "").trim().toLowerCase();
    const nextStatus = String(requestedStatus || "").trim().toLowerCase() || PLAN_CODE_PLANETKA_FREE;
    const protectedStatus = currentStatus === "blocked"
      ? currentStatus
      : (
        resolvePlanPriority(currentStatus) > resolvePlanPriority(nextStatus)
          ? currentStatus
          : nextStatus
      );
    const termsAcceptedAt = String(options.termsAcceptedAt || "").trim();
    const privacyAcceptedAt = String(options.privacyAcceptedAt || "").trim();
    const termsVersion = String(options.termsVersion || "").trim();
    const privacyVersion = String(options.privacyVersion || "").trim();
    await dbRun(
      db,
      `
        UPDATE users
        SET
          status = ?,
          terms_accepted_at = CASE WHEN ? != '' THEN ? ELSE terms_accepted_at END,
          privacy_accepted_at = CASE WHEN ? != '' THEN ? ELSE privacy_accepted_at END,
          terms_version = CASE WHEN ? != '' THEN ? ELSE terms_version END,
          privacy_version = CASE WHEN ? != '' THEN ? ELSE privacy_version END
        WHERE id = ?
      `,
      [
        protectedStatus,
        termsAcceptedAt,
        termsAcceptedAt,
        privacyAcceptedAt,
        privacyAcceptedAt,
        termsVersion,
        termsVersion,
        privacyVersion,
        privacyVersion,
        user.id,
      ],
    );
    const refreshedUser = await findUserById(db, user.id);
    if (refreshedUser) {
      return refreshedUser;
    }
    return { ...user, status: protectedStatus };
  }

	  const id = crypto.randomUUID();
  const createdAt = nowIso();
  const termsAcceptedAt = options.termsAcceptedAt ? String(options.termsAcceptedAt) : null;
  const privacyAcceptedAt = options.privacyAcceptedAt ? String(options.privacyAcceptedAt) : null;
  const termsVersion = options.termsVersion ? String(options.termsVersion) : null;
  const privacyVersion = options.privacyVersion ? String(options.privacyVersion) : null;
  await dbRun(
    db,
    `
      INSERT INTO users (
        id,
        email,
        status,
        created_at,
        terms_accepted_at,
        privacy_accepted_at,
        terms_version,
        privacy_version
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      id,
      normalizedEmail,
      requestedStatus,
      createdAt,
      termsAcceptedAt,
      privacyAcceptedAt,
      termsVersion,
      privacyVersion,
    ],
  );
  if (!parseBooleanFlag(options.suppressNewUserAlert)) {
    try {
      await sendNewUserLoginAlert(env, {
        email: normalizedEmail,
        source: String(options.signupSource || options.source || "unknown").trim() || "unknown",
        planCode: requestedStatus,
        createdAt,
      });
    } catch (error) {
      console.warn(
        "worker.new_user_alert_email_failed",
        JSON.stringify({
          email: normalizedEmail,
          source: String(options.signupSource || options.source || "unknown").trim() || "unknown",
          error: String(error && error.message || "new_user_alert_email_failed"),
        }),
      );
    }
  }
  user = await findUserByEmail(db, normalizedEmail);
  return user;
}

async function enforceUserPlanPolicy(db, user, subscription = null, env = {}) {
  void subscription;
  void env;
  if (!user || !user.id || isBlockedStatus(user.status)) {
    return user;
  }
  const targetPlan = normalizeRequestedPlan(user.status);
  if (
    targetPlan !== PLAN_CODE_PLANETKA_FREE
    && targetPlan !== PLAN_CODE_PLANETKA
    && targetPlan !== PLAN_CODE_PLANETKA_PRO
  ) {
    return user;
  }
  const currentStatus = normalizeUserStatus(user.status);
  if (currentStatus === targetPlan) {
    return { ...user, status: targetPlan };
  }
  await dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetPlan, user.id]);
  await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        expires_at = NULL
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetPlan, user.id],
  );
  return { ...user, status: targetPlan };
}

function parseTileQualityFromFileName(fileName) {
  const match = /^([A-Za-z0-9]+)_x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})\.(exr|tif|tiff|png|jpe?g)$/i.exec(
    String(fileName || "").trim(),
  );
  if (!match) {
    return null;
  }
  const z = Number.parseInt(match[4], 10);
  const rawD = Number.parseInt(match[5], 10);
  if (!Number.isFinite(z) || !Number.isFinite(rawD)) {
    return null;
  }
  const d = rawD === 0 ? 1440 : rawD;
  return { z, d, textureType: String(match[1] || "").toUpperCase() };
}

function minimumPlanQualityForTile(fileName) {
  const parsed = parseTileQualityFromFileName(fileName);
  if (!parsed || !Number.isFinite(Number(parsed.d))) {
    return "preview";
  }
  const d = Math.max(1, Number(parsed.d));
  // d001 => Full-only, d002/d003 => Balanced+, d004+ => Preview+
  if (d <= 1) return "full";
  if (d <= 3) return "balanced";
  return "preview";
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
      subject: "Your Planetka API key activation link",
      text: [
        "Planetka free access request received.",
        "",
        "Open this activation link to generate your key:",
        activationUrl,
        "",
        "The link expires in 30 minutes.",
      ].join("\n"),
      html: `
        <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
          <h2 style="margin-bottom: 16px;">Activate your Planetka API key</h2>
          <p>Use the button below to generate your API key for Blender.</p>
          <p style="margin: 24px 0;">
            <a href="${activationUrl}" style="background:#111827;color:#ffffff;padding:12px 18px;text-decoration:none;border-radius:8px;display:inline-block;">
              Activate API Key
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
      subject: "Your Planetka API key",
      text: [
        "Your Planetka API key is ready.",
        "",
        `Access: ${displayPlan}`,
        accessSummary,
        "",
        "API key:",
        apiKeyValue,
        "",
        "Paste this key in Blender > Planetka > Account.",
      ].join("\n"),
      html: `
        <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
          <h2 style="margin-bottom: 16px;">Your Planetka API key</h2>
          <p><strong>Access:</strong> ${displayPlan}</p>
          <p>${escapeHtml(accessSummary)}</p>
          <p style="margin: 16px 0;">Paste this key in Blender &rarr; Planetka &rarr; Account:</p>
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
  const activeRows = await dbAll(
    db,
    `
      SELECT id
      FROM api_keys
      WHERE user_id = ?
        AND status = 'active'
    `,
    [safeUserId],
  );
  const idsToRevoke = activeRows
    .map((row) => String(row && row.id || "").trim())
    .filter((id) => Boolean(id) && id !== safeKeepApiKeyId);
  if (idsToRevoke.length === 0) {
    return 0;
  }
  const revokedAt = nowIso();
  for (const apiKeyId of idsToRevoke) {
    await dbRun(
      db,
      `
        UPDATE api_keys
        SET
          status = 'revoked',
          revoked_at = ?
        WHERE id = ?
      `,
      [revokedAt, apiKeyId],
    );
    await dbRun(
      db,
      `
        UPDATE refresh_sessions
        SET revoked_at = ?
        WHERE api_key_id = ?
          AND (revoked_at IS NULL OR revoked_at = '')
      `,
      [revokedAt, apiKeyId],
    );
  }
  try {
    console.log(
      "api_key.revoke_other_active",
      JSON.stringify({
        user_id: safeUserId,
        keep_api_key_id: safeKeepApiKeyId,
        revoked_count: idsToRevoke.length,
        reason: String(reason || "").trim() || "superseded",
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
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
    `
      SELECT id
      FROM api_keys
      WHERE user_id = ?
        AND status = 'active'
      ORDER BY issued_at DESC, id DESC
    `,
    [safeUserId],
  );
  if (!Array.isArray(activeRows) || activeRows.length === 0) {
    return { allowed: true, keepApiKeyId: "", revokedCount: 0 };
  }
  const keepApiKeyId = String(activeRows[0] && activeRows[0].id || "").trim();
  if (!keepApiKeyId) {
    return { allowed: true, keepApiKeyId: "", revokedCount: 0 };
  }
  const revokedCount = await revokeOtherActiveApiKeysForUser(
    db,
    safeUserId,
    keepApiKeyId,
    "single_active_free_key_reconciliation",
  );
  const allowed = !safePreferredApiKeyId || safePreferredApiKeyId === keepApiKeyId;
  return {
    allowed,
    keepApiKeyId,
    revokedCount,
  };
}

async function isApiKeyUsableById(db, apiKeyId, expectedUserId = "") {
  await ensureApiKeyTables(db);
  const safeApiKeyId = String(apiKeyId || "").trim();
  if (!safeApiKeyId) {
    return false;
  }
  const row = await dbGet(
    db,
    `
      SELECT id, user_id, status, expires_at
      FROM api_keys
      WHERE id = ?
      LIMIT 1
    `,
    [safeApiKeyId],
  );
  if (!row || !row.id) {
    return false;
  }
  if (String(row.status || "").trim().toLowerCase() !== "active") {
    return false;
  }
  const safeExpectedUserId = String(expectedUserId || "").trim();
  if (safeExpectedUserId && String(row.user_id || "").trim() !== safeExpectedUserId) {
    return false;
  }
  return true;
}

async function issueApiKeyForUser(db, env, user, planCode, options = {}) {
  await ensureApiKeyTables(db);
  const safePlan = normalizeRequestedPlan(planCode || user.status || PLAN_CODE_PLANETKA);
  const token = `pka_${randomToken(36)}`;
  const keyHash = await sha256Hex(token);
  const keyPrefix = String(token.slice(0, 16));
  const keyId = crypto.randomUUID();
  const issuedAt = nowIso();
  void options;
  const expiresAt = String(options.expiresAt || computeApiKeyExpiryIso(safePlan, env) || "").trim();
  await dbRun(
    db,
    `
      INSERT INTO api_keys (
        id,
        user_id,
        key_hash,
        key_prefix,
        status,
        plan_code,
        expires_at,
        issued_at
      ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
    `,
    [
      keyId,
      user.id,
      keyHash,
      keyPrefix,
      safePlan,
      expiresAt || null,
      issuedAt,
    ],
  );
  if (safePlan === PLAN_CODE_PLANETKA_FREE) {
    await enforceSingleActiveFreeApiKey(
      db,
      String(user && user.id || "").trim(),
      keyId,
    );
  }

  return {
    apiKey: token,
    apiKeyId: keyId,
    keyPrefix,
    planCode: safePlan,
    expiresAt,
  };
}

async function findActiveApiKeyRecord(db, apiKeyValue) {
  await ensureApiKeyTables(db);
  const keyHash = await sha256Hex(apiKeyValue);
  return dbGet(
    db,
    `
      SELECT
        ak.id AS api_key_id,
        ak.user_id,
        ak.status AS api_key_status,
        ak.plan_code AS api_key_plan_code,
        ak.expires_at AS api_key_expires_at,
        ak.key_prefix,
        u.id,
        u.email,
        u.status,
        u.created_at,
        u.last_login_at
      FROM api_keys ak
      JOIN users u ON u.id = ak.user_id
      WHERE ak.key_hash = ?
      LIMIT 1
    `,
    [keyHash],
  );
}

function maxDevicesForPlan(planCode) {
  void normalizeRequestedPlan(planCode);
  return 1;
}

async function listActiveApiKeyDevicesForUser(db, userId, env) {
  await ensureApiKeyTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return new Set();
  }
  const nowUnix = Math.floor(Date.now() / 1000);
  const activeWindowSeconds = Math.max(
    60,
    Math.floor(parsePositiveNumber(env.API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS, DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS)),
  );
  const windowStart = Math.max(0, nowUnix - activeWindowSeconds);

  await dbRun(
    db,
    `
      DELETE FROM api_key_device_activity
      WHERE last_seen_unix < ?
    `,
    [Math.max(0, nowUnix - (activeWindowSeconds * 4))],
  );

  const rows = await dbAll(
    db,
    `
      SELECT DISTINCT device_id
      FROM api_key_device_activity
      WHERE user_id = ?
        AND last_seen_unix >= ?
    `,
    [safeUserId, windowStart],
  );
  return new Set(
    rows.map((row) => normalizeDeviceId(row && row.device_id)).filter((value) => Boolean(value)),
  );
}

async function enforceApiKeyIssueDeviceLimit(db, userId, userEmail, planCode, deviceId, env) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return { activeDeviceCount: 0, maxDevices: maxDevicesForPlan(planCode), matchedDevice: false };
  }
  if (isDeviceLimitExemptEmail(userEmail, env)) {
    return { activeDeviceCount: 0, maxDevices: Number.MAX_SAFE_INTEGER, matchedDevice: true, exempted: true };
  }
  const safeDeviceId = normalizeDeviceId(deviceId);
  const activeDeviceIds = await listActiveApiKeyDevicesForUser(db, safeUserId, env);
  const maxDevices = maxDevicesForPlan(planCode);
  const matchedDevice = Boolean(safeDeviceId && activeDeviceIds.has(safeDeviceId));
  if (activeDeviceIds.size >= maxDevices && !matchedDevice) {
    throw new Error("device_limit_exceeded");
  }
  return {
    activeDeviceCount: activeDeviceIds.size,
    maxDevices,
    matchedDevice,
  };
}

async function touchApiKeyDeviceActivity(db, apiKeyId, userId, deviceId, request, env) {
  await ensureApiKeyTables(db);
  const safeUserId = String(userId || "").trim();
  const safeDeviceId = normalizeDeviceId(deviceId);
  if (!safeUserId || !safeDeviceId) {
    throw new Error("missing_device_id");
  }
  const nowUnix = Math.floor(Date.now() / 1000);
  const now = nowIso();
  const ip = requestClientIp(request);
  const country = requestCountry(request);
  const existingRows = await dbAll(
    db,
    `
      SELECT id
      FROM api_key_device_activity
      WHERE user_id = ? AND device_id = ?
      ORDER BY last_seen_unix DESC
    `,
    [safeUserId, safeDeviceId],
  );
  const primaryExisting = Array.isArray(existingRows) && existingRows.length > 0 ? existingRows[0] : null;
  if (primaryExisting && primaryExisting.id) {
    await dbRun(
      db,
      `
        UPDATE api_key_device_activity
        SET
          api_key_id = ?,
          last_seen_at = ?,
          last_seen_unix = ?,
          last_ip = ?,
          last_country = ?
        WHERE id = ?
      `,
      [apiKeyId, now, nowUnix, ip, country, primaryExisting.id],
    );
    if (existingRows.length > 1) {
      await dbRun(
        db,
        `
          DELETE FROM api_key_device_activity
          WHERE user_id = ?
            AND device_id = ?
            AND id != ?
        `,
        [safeUserId, safeDeviceId, primaryExisting.id],
      );
    }
    return primaryExisting.id;
  }
  await dbRun(
    db,
    `
      INSERT INTO api_key_device_activity (
        id,
        api_key_id,
        user_id,
        device_id,
        first_seen_at,
        last_seen_at,
        last_seen_unix,
        last_ip,
        last_country
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [crypto.randomUUID(), apiKeyId, safeUserId, safeDeviceId, now, now, nowUnix, ip, country],
  );
  return "";
}

async function enforceApiKeyDeviceLimit(db, apiKeyId, userId, userEmail, planCode, deviceId, request, env) {
  await ensureApiKeyTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    throw new Error("user_not_found");
  }
  const safeDeviceId = normalizeDeviceId(deviceId);
  if (!safeDeviceId) {
    throw new Error("missing_device_id");
  }
  const activeDeviceIds = await listActiveApiKeyDevicesForUser(db, safeUserId, env);
  if (isDeviceLimitExemptEmail(userEmail, env)) {
    await touchApiKeyDeviceActivity(db, apiKeyId, safeUserId, safeDeviceId, request, env);
    return {
      activeDeviceCount: activeDeviceIds.has(safeDeviceId) ? activeDeviceIds.size : (activeDeviceIds.size + 1),
      maxDevices: Number.MAX_SAFE_INTEGER,
      exempted: true,
    };
  }
  const alreadyActive = activeDeviceIds.has(safeDeviceId);
  const maxDevices = maxDevicesForPlan(planCode);
  if (!alreadyActive && activeDeviceIds.size >= maxDevices) {
    throw new Error("device_limit_exceeded");
  }

  await touchApiKeyDeviceActivity(db, apiKeyId, safeUserId, safeDeviceId, request, env);
  return {
    activeDeviceCount: activeDeviceIds.has(safeDeviceId) ? activeDeviceIds.size : (activeDeviceIds.size + 1),
    maxDevices,
  };
}

async function createAccessToken(env, user, subscription, extraClaims = {}) {
  void subscription;
  const secret = requireSecret(env, "JWT_SIGNING_SECRET");
  const exp = Math.floor(Date.now() / 1000) + (60 * 60);
  const effectivePlanCode = normalizeRequestedPlan(
    resolvePolicyPlanCode(user, subscription, env),
  ) || PLAN_CODE_PLANETKA_FREE;
  const basePayload = {
    type: "access",
    sub: user.id,
    email: user.email,
    plan_code: effectivePlanCode,
    user_status: effectivePlanCode,
    exp,
  };
  const payload = { ...basePayload };
  if (extraClaims && typeof extraClaims === "object") {
    for (const [key, value] of Object.entries(extraClaims)) {
      if (value === undefined || value === null || key === "sub" || key === "email" || key === "exp") {
        continue;
      }
      payload[key] = value;
    }
  }
  return signJwt(
    payload,
    secret,
  );
}

function resolveTileSessionTokenTtlSeconds(env = {}) {
  return Math.min(
    3600,
    Math.max(
      60,
      parseRateLimitInteger(
        env.TILE_SESSION_TOKEN_TTL_SECONDS,
        DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS,
      ),
    ),
  );
}

function normalizeResolveId(value) {
  return String(value || "").trim().slice(0, 128);
}

async function issueTileSessionToken(env, auth, requestedQualityMode, requestedResolveId = "") {
  const safeQualityMode = normalizeQualityMode(requestedQualityMode);
  const safePlanCode = normalizeRequestedPlan(auth && auth.planCode);
  if (!isQualityModeAllowedForPlan(safePlanCode, safeQualityMode)) {
    return {
      error: json(
        {
          ok: false,
          error: "quality_mode_not_allowed_for_tier",
          message: qualityModeNotAllowedMessage(safePlanCode, safeQualityMode),
          requested_quality_mode: safeQualityMode,
        },
        403,
        env,
      ),
    };
  }
  const safeResolveId = normalizeResolveId(requestedResolveId) || crypto.randomUUID();
  const ttlSeconds = resolveTileSessionTokenTtlSeconds(env);
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const payload = {
    type: "tile_session",
    sub: String(auth && auth.user && auth.user.id || "").trim(),
    email: String(auth && auth.user && auth.user.email || "").trim(),
    plan_code: safePlanCode,
    quality_mode: safeQualityMode,
    resolve_id: safeResolveId,
    auth_method: String(auth && auth.authMethod || "").trim(),
    device_id: String(auth && auth.deviceId || "").trim(),
    exp,
  };
  const secret = requireSecret(env, "JWT_SIGNING_SECRET");
  const tileToken = await signJwt(payload, secret);
  return {
    token: tileToken,
    resolveId: safeResolveId,
    qualityMode: safeQualityMode,
    expiresInSeconds: ttlSeconds,
    expiresAt: new Date(exp * 1000).toISOString(),
    exp,
  };
}

async function readTileSessionClaims(request, env) {
  const rawToken = String(request.headers.get("X-Planetka-Tile-Token") || "").trim();
  if (!rawToken) {
    return { claims: null };
  }
  const cacheKey = `tile_session:${rawToken}`;
  const cached = authContextCacheGet(cacheKey, env);
  if (cached && cached.tileSessionClaims) {
    return { claims: cached.tileSessionClaims };
  }
  let payload;
  try {
    const secret = requireSecret(env, "JWT_SIGNING_SECRET");
    payload = await verifyJwt(rawToken, secret);
  } catch (error) {
    const code = String(error && error.message || "invalid_tile_token");
    const normalized = code === "token_expired" ? "tile_session_token_expired" : "invalid_tile_session_token";
    return {
      error: json(
        {
          ok: false,
          error: normalized,
        },
        401,
        env,
      ),
    };
  }

  if (String(payload && payload.type || "").trim() !== "tile_session") {
    return { error: json({ ok: false, error: "invalid_tile_session_token" }, 401, env) };
  }
  const userId = String(payload && payload.sub || "").trim();
  if (!userId) {
    return { error: json({ ok: false, error: "invalid_tile_session_token" }, 401, env) };
  }
  const planCode = normalizeRequestedPlan(payload && (payload.plan_code || payload.user_status) || "");
  const qualityMode = normalizeQualityMode(payload && payload.quality_mode || "");
  const resolveId = normalizeResolveId(payload && payload.resolve_id || "");
  const claims = {
    userId,
    userEmail: String(payload && payload.email || "").trim(),
    planCode,
    qualityMode,
    resolveId,
    authMethod: String(payload && payload.auth_method || "").trim(),
    deviceId: normalizeDeviceId(payload && payload.device_id || ""),
  };
  authContextCacheSet(
    cacheKey,
    {
      access: { exp: Number(payload && payload.exp || 0) || 0 },
      tileSessionClaims: claims,
    },
    env,
  );
  return { claims };
}

async function createRefreshSession(db, userId, expiresAtOverride = "", metadata = {}) {
  await ensureRefreshSessionColumns(db);
  const refreshToken = randomToken(48);
  const refreshHash = await sha256Hex(refreshToken);
  const refreshSessionId = crypto.randomUUID();
  const createdAt = nowIso();
  const expiresAt = String(expiresAtOverride || "").trim() || addDaysIso(30);
  const authMethod = String(metadata.auth_method || metadata.authMethod || "").trim();
  const apiKeyId = String(metadata.api_key_id || metadata.apiKeyId || "").trim();
  const deviceId = normalizeDeviceId(metadata.device_id || metadata.deviceId || "");
  await dbRun(
    db,
    `
      INSERT INTO refresh_sessions (
        id,
        user_id,
        refresh_token_hash,
        expires_at,
        created_at,
        auth_method,
        api_key_id,
        device_id
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [refreshSessionId, userId, refreshHash, expiresAt, createdAt, authMethod || null, apiKeyId || null, deviceId || null],
  );
  return refreshToken;
}

function genericAuthStartResponse(env) {
  return json(
    {
      ok: true,
      message: "If the email is valid, a Planetka API key activation link has been sent.",
    },
    200,
    env,
  );
}

async function sendOpsAlertEmail(env, subject, lines = []) {
  const apiKey = requireSecret(env, "EMAIL_API_KEY");
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const to = String(env.SECURITY_ALERT_EMAIL || "info@planetka.io").trim() || "info@planetka.io";
  await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject: String(subject || "Planetka security alert").trim(),
      text: Array.isArray(lines) ? lines.join("\n") : String(lines || ""),
    }),
  });
}

async function sendNewUserLoginAlert(env, details = {}) {
  const email = normalizeEmail(details.email || "");
  if (!email) {
    return;
  }
  const source = String(details.source || "unknown").trim() || "unknown";
  const createdAt = String(details.createdAt || nowIso()).trim() || nowIso();
  const planCode = normalizePlanCode(details.planCode || PLAN_CODE_PLANETKA) || PLAN_CODE_PLANETKA;
  await sendOpsAlertEmail(
    env,
    "New Planetka user signup/login",
    [
      "A new Planetka user account was created.",
      `email=${email}`,
      `source=${source}`,
      `plan_code=${planCode}`,
      `created_at=${createdAt}`,
    ],
  );
}

async function handleApiKeyRequest(request, env) {
  const db = requireDb(env);
  await ensureApiKeyTables(db);
  await ensureRateLimitsTable(db);
  const body = await parseJson(request);
  const email = normalizeEmail(body.email);
  const requestDeviceId = normalizeDeviceId(body.device_id || "");
  const acceptTerms = parseBooleanFlag(body.accept_terms);
  const acceptPrivacy = parseBooleanFlag(body.accept_privacy);
  const optInNews = parseBooleanFlag(body.opt_in_news);
  // Public API-key request flow always issues base access.
  const requestedPlan = PLAN_CODE_PLANETKA_FREE;
  const honeypot = String(body.website || "").trim();
  const submittedAtMs = parseNonNegativeInteger(body.submitted_at_ms, 0);
  const minFormAgeMs = Math.max(
    0,
    Math.floor(parsePositiveNumber(env.API_KEY_REQUEST_MIN_AGE_SECONDS, DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS) * 1000),
  );
  if (honeypot) {
    return genericAuthStartResponse(env);
  }
  if (submittedAtMs > 0 && submittedAtMs < minFormAgeMs) {
    return genericAuthStartResponse(env);
  }
  if (!email || !email.includes("@")) {
    return json({ ok: false, error: "invalid_email" }, 400, env);
  }
  if (!acceptTerms || !acceptPrivacy) {
    return json({ ok: false, error: "terms_consent_required" }, 400, env);
  }

  const clientIp = requestClientIp(request);
  const hardBlockedByRequest = await findActiveHardBlock(
    db,
    {
      email,
      device_id: requestDeviceId,
      ip: clientIp,
    },
  );
  if (hardBlockedByRequest) {
    return blockedAccountResponse(env, "This Planetka account is blocked. Contact info@planetka.io.");
  }
  const authStartIpRate = await consumeRateLimitWindow(
    db,
    "api_key_request_ip",
    clientIp,
    parseRateLimitInteger(env.RATE_LIMIT_AUTH_START_IP_LIMIT, DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT),
    parseRateLimitInteger(env.RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS, DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS),
  );
  if (!authStartIpRate.allowed) {
    return rateLimitedResponse(
      env,
      "api_key_request_ip_rate_limited",
      "Too many requests. Please try again shortly.",
      authStartIpRate.retryAfterSeconds,
    );
  }
  const authStartEmailRate = await consumeRateLimitWindow(
    db,
    "api_key_request_email",
    email,
    parseRateLimitInteger(env.RATE_LIMIT_AUTH_START_EMAIL_LIMIT, DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT),
    parseRateLimitInteger(env.RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS, DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS),
  );
  if (!authStartEmailRate.allowed) {
    return rateLimitedResponse(
      env,
      "api_key_request_email_rate_limited",
      "Too many requests for this email. Please try again later.",
      authStartEmailRate.retryAfterSeconds,
    );
  }

  let existingUser = await findUserByEmail(db, email);
  if (existingUser && !isBlockedStatus(existingUser.status)) {
    existingUser = await enforceUserPlanPolicy(db, existingUser, null, env);
    try {
      await enforceApiKeyIssueDeviceLimit(
        db,
        String(existingUser.id || "").trim(),
        String(existingUser.email || "").trim(),
        resolvePlanCode(existingUser, null, env),
        requestDeviceId,
        env,
      );
    } catch (error) {
      const code = String(error && error.message || "device_limit_exceeded");
      if (code === "device_limit_exceeded") {
        return json(
          {
            ok: false,
            error: "device_limit_exceeded",
            message: "This Planetka account can be active on one computer at a time.",
          },
          429,
          env,
        );
      }
      throw error;
    }
  }

  const legalVersion = String(env.TERMS_VERSION || env.LEGAL_VERSION || DEFAULT_LEGAL_VERSION).trim() || DEFAULT_LEGAL_VERSION;
  const privacyVersion = String(env.PRIVACY_VERSION || env.LEGAL_VERSION || DEFAULT_LEGAL_VERSION).trim() || DEFAULT_LEGAL_VERSION;
  const acceptedAt = nowIso();
  await upsertUserByEmail(
    db,
    email,
    requestedPlan,
    {
      termsAcceptedAt: acceptedAt,
      privacyAcceptedAt: acceptedAt,
      termsVersion: legalVersion,
      privacyVersion,
      signupSource: "api_key_request",
    },
    env,
  );
  if (optInNews) {
    await recordNewsletterOptIn(db, email, "api_key_request");
  }

  const token = randomToken(36);
  const tokenHash = await sha256Hex(token);
  await dbRun(
    db,
    `
      INSERT INTO api_key_requests (
        id,
        email,
        requested_plan,
        token_hash,
        expires_at,
        accept_terms,
        accept_privacy,
        opt_in_news,
        submitted_at_ms,
        request_ip,
        request_device_id,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      crypto.randomUUID(),
      email,
      requestedPlan,
      tokenHash,
      addMinutesIso(30),
      acceptTerms ? 1 : 0,
      acceptPrivacy ? 1 : 0,
      optInNews ? 1 : 0,
      submittedAtMs,
      clientIp,
      requestDeviceId || null,
      nowIso(),
    ],
  );
  await sendApiKeyActivationEmail(env, email, token);
  return json(
    {
      ok: true,
      message: "If the email is valid, a Planetka API key activation link has been sent.",
    },
    200,
    env,
  );
}

async function activateApiKeyFromToken(db, env, rawToken) {
  await ensureApiKeyTables(db);
  const token = String(rawToken || "").trim();
  if (!token) {
    throw new Error("missing_token");
  }
  const tokenHash = await sha256Hex(token);
  const now = nowIso();
  const requestRow = await dbGet(
    db,
    `
      UPDATE api_key_requests
      SET used_at = ?
      WHERE token_hash = ?
        AND used_at IS NULL
        AND expires_at >= ?
      RETURNING
        id,
        email,
        requested_plan,
        request_ip,
        request_device_id,
        opt_in_news
    `,
    [
      now,
      tokenHash,
      now,
    ],
  );
  if (!requestRow) {
    throw new Error("invalid_or_expired_token");
  }

  const email = normalizeEmail(requestRow.email);
  let user = await upsertUserByEmail(
    db,
    email,
    PLAN_CODE_PLANETKA_FREE,
    {},
    env,
  );
  user = await enforceUserPlanPolicy(db, user, null, env);
  const effectivePlanCode = resolvePlanCode(user, null, env);

  const issued = await issueApiKeyForUser(
    db,
    env,
    user,
    effectivePlanCode,
    {},
  );

  await sendApiKeyIssuedEmail(env, email, issued.apiKey, issued.planCode, issued.expiresAt);
  return {
    email,
    apiKey: issued.apiKey,
    planCode: issued.planCode,
    expiresAt: issued.expiresAt,
  };
}

async function handleApiKeyActivate(request, env) {
  const db = requireDb(env);
  const body = await parseJson(request);
  try {
    const activated = await activateApiKeyFromToken(db, env, body.token);
    return json(
      {
        ok: true,
        email: activated.email,
        api_key: activated.apiKey,
        plan_code: activated.planCode,
        expires_at: activated.expiresAt,
      },
      200,
      env,
    );
  } catch (error) {
    const publicCode = publicErrorCode(
      error,
      "activation_failed",
      new Set(["missing_token", "invalid_or_expired_token"]),
    );
    return json(
      { ok: false, error: publicCode },
      publicCode === "activation_failed" ? 500 : 400,
      env,
    );
  }
}

async function handleApiKeyExchange(request, env) {
  const db = requireDb(env);
  const body = await parseJson(request);
  const apiKey = String(body.api_key || "").trim();
  const deviceId = normalizeDeviceId(body.device_id || "");
  const clientIp = requestClientIp(request);
  if (!isValidApiKey(apiKey)) {
    return json({ ok: false, error: "invalid_api_key" }, 400, env);
  }
  if (!deviceId) {
    return json({ ok: false, error: "missing_device_id" }, 400, env);
  }

  let record = await findActiveApiKeyRecord(db, apiKey);
  if (!record) {
    return json({ ok: false, error: "invalid_api_key" }, 401, env);
  }
  if (String(record.api_key_status || "").trim().toLowerCase() !== "active") {
    return json({ ok: false, error: "api_key_revoked" }, 401, env);
  }
  if (isBlockedStatus(record.status)) {
    return blockedAccountResponse(env);
  }
  const hardBlockedByExchange = await findActiveHardBlock(
    db,
    {
      email: String(record && record.email || ""),
      device_id: deviceId,
      ip: clientIp,
    },
  );
  if (hardBlockedByExchange) {
    return blockedAccountResponse(env, "This Planetka account is blocked. Contact info@planetka.io.");
  }

  let user = {
    id: record.id,
    email: record.email,
    status: record.status || PLAN_CODE_PLANETKA,
  };
  user = await enforceUserPlanPolicy(db, user, null, env);
  const effectivePlanCode = resolvePlanCode(user, null, env);
  if (effectivePlanCode === PLAN_CODE_PLANETKA_FREE) {
    const freePolicy = await enforceSingleActiveFreeApiKey(
      db,
      String(user.id || ""),
      String(record.api_key_id || ""),
    );
    if (!freePolicy.allowed) {
      return json(
        {
          ok: false,
          error: "api_key_revoked",
          message: "This API key has been replaced. Request a new API key.",
        },
        401,
        env,
      );
    }
  }
  try {
    await enforceApiKeyDeviceLimit(
      db,
      String(record.api_key_id || ""),
      String(user.id || ""),
      String(user.email || ""),
      effectivePlanCode,
      deviceId,
      request,
      env,
    );
  } catch (error) {
    const code = String(error && error.message || "device_limit_exceeded");
    if (code === "missing_device_id") {
      return json({ ok: false, error: "missing_device_id" }, 400, env);
    }
    return json(
      {
        ok: false,
        error: "device_limit_exceeded",
        message: "This Planetka account can be active on one computer at a time.",
      },
      429,
      env,
    );
  }

  const now = nowIso();
  await dbRun(db, `UPDATE users SET last_login_at = ? WHERE id = ?`, [now, user.id]);
  await dbRun(db, `UPDATE api_keys SET last_used_at = ? WHERE id = ?`, [now, record.api_key_id]);

  const refreshExpiresAt = addDaysIso(7);

  const accessToken = await createAccessToken(
    env,
    user,
    null,
    {
      api_key_id: String(record.api_key_id || ""),
      device_id: deviceId,
      auth_method: "api_key",
    },
  );
  const refreshToken = await createRefreshSession(
    db,
    user.id,
    refreshExpiresAt,
    {
      auth_method: "api_key",
      api_key_id: String(record.api_key_id || ""),
      device_id: deviceId,
    },
  );
  const accountState = await buildAccountState(db, user, null, env);

  return json(
    {
      ok: true,
      email: user.email,
      access_token: accessToken,
      refresh_token: refreshToken,
      api_key_mask: maskApiKey(apiKey),
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

async function handleAuthRefresh(request, env) {
  const db = requireDb(env);
  const refreshEventBase = {
    client_ip: requestClientIp(request),
    cf_country: requestCountry(request),
    cf_ray: String(request.headers.get("CF-Ray") || "").trim(),
  };
  const recordRefreshEvent = async ({
    outcome = "error",
    errorCode = "",
    httpStatus = 0,
    userId = "",
    userEmail = "",
    sessionRow = null,
    details = null,
  } = {}) => {
    await logAuthRefreshEvent(db, {
      ...refreshEventBase,
      user_id: userId,
      user_email: userEmail,
      auth_method: sessionRow ? String(sessionRow.auth_method || "").trim() : "",
      api_key_id: sessionRow ? String(sessionRow.api_key_id || "").trim() : "",
      device_id: sessionRow ? String(sessionRow.device_id || "").trim() : "",
      outcome,
      error_code: errorCode,
      http_status: httpStatus,
      details,
    });
  };
  const errorResponse = async (errorCode, httpStatus, sessionRow = null, details = null) => {
    await recordRefreshEvent({
      outcome: "error",
      errorCode,
      httpStatus,
      userId: sessionRow ? String(sessionRow.user_id || "").trim() : "",
      userEmail: sessionRow ? normalizeEmail(sessionRow.email || "") : "",
      sessionRow,
      details,
    });
    return json({ ok: false, error: errorCode }, httpStatus, env);
  };
  const body = await parseJson(request);
  const refreshToken = String(body.refresh_token || "").trim();
  if (!refreshToken) {
    return errorResponse("missing_refresh_token", 400, null, { has_body: Boolean(body && Object.keys(body).length) });
  }

  const refreshHash = await sha256Hex(refreshToken);
  const session = await dbGet(
    db,
    `
      SELECT
        rs.id,
        rs.user_id,
        rs.expires_at,
        rs.revoked_at,
        rs.auth_method,
        rs.api_key_id,
        rs.device_id,
        u.email,
        u.status
      FROM refresh_sessions rs
      JOIN users u ON u.id = rs.user_id
      WHERE rs.refresh_token_hash = ?
      LIMIT 1
    `,
    [refreshHash],
  );
  if (!session) {
    return errorResponse("invalid_refresh_token", 400);
  }
  if (isBlockedStatus(session.status)) {
    await recordRefreshEvent({
      outcome: "error",
      errorCode: "account_blocked",
      httpStatus: 403,
      userId: String(session.user_id || "").trim(),
      userEmail: normalizeEmail(session.email || ""),
      sessionRow: session,
    });
    return blockedAccountResponse(env);
  }
  if (session.revoked_at) {
    return errorResponse("refresh_token_revoked", 400, session);
  }
  if (Date.parse(session.expires_at) < Date.now()) {
    return errorResponse("refresh_token_expired", 400, session);
  }
  if (
    String(session.auth_method || "").trim().toLowerCase() === "api_key"
    && String(session.api_key_id || "").trim()
  ) {
    const keyUsable = await isApiKeyUsableById(db, session.api_key_id, session.user_id);
    if (!keyUsable) {
      return errorResponse("api_key_revoked", 401, session);
    }
  }

  let user = {
    id: session.user_id,
    email: session.email,
    status: session.status || PLAN_CODE_PLANETKA,
  };
  user = await enforceUserPlanPolicy(db, user, null, env);

  await dbRun(
    db,
    `UPDATE refresh_sessions SET revoked_at = ? WHERE id = ?`,
    [nowIso(), session.id],
  );
  const accessToken = await createAccessToken(
    env,
    user,
    null,
    {
      auth_method: String(session.auth_method || "").trim(),
      api_key_id: String(session.api_key_id || "").trim(),
      device_id: String(session.device_id || "").trim(),
    },
  );
  const nextRefreshToken = await createRefreshSession(
    db,
    session.user_id,
    "",
    {
      auth_method: String(session.auth_method || "").trim(),
      api_key_id: String(session.api_key_id || "").trim(),
      device_id: String(session.device_id || "").trim(),
    },
  );
  const accountState = await buildAccountState(db, user, null, env);
  await recordRefreshEvent({
    outcome: "success",
    errorCode: "",
    httpStatus: 200,
    userId: String(user.id || "").trim(),
    userEmail: normalizeEmail(user.email || ""),
    sessionRow: session,
  });

  return json(
    {
      ok: true,
      access_token: accessToken,
      refresh_token: nextRefreshToken,
      email: user.email,
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

async function handleAuthLogout(request, env) {
  const db = requireDb(env);
  await ensureRefreshSessionColumns(db);
  await ensureApiKeyTables(db);
  const body = await parseJson(request);

  const refreshToken = String(body.refresh_token || "").trim();
  let deviceId = normalizeDeviceId(
    body.device_id || request.headers.get("X-Planetka-Device-Id") || "",
  );
  let userId = "";
  let revokedSessions = 0;
  let clearedDeviceActivity = 0;

  if (refreshToken) {
    const refreshHash = await sha256Hex(refreshToken);
    const session = await dbGet(
      db,
      `
        SELECT id, user_id, device_id
        FROM refresh_sessions
        WHERE refresh_token_hash = ?
        LIMIT 1
      `,
      [refreshHash],
    );
    if (session) {
      userId = String(session.user_id || "").trim();
      if (!deviceId) {
        deviceId = normalizeDeviceId(session.device_id || "");
      }
    }
  }

  if (!userId) {
    try {
      const access = await readBearerUser(request, env);
      if (access && access.sub) {
        userId = String(access.sub || "").trim();
      }
      if (!deviceId && access) {
        deviceId = normalizeDeviceId(access.device_id || "");
      }
    } catch (_error) {
      // Best-effort logout: silently allow local logout even when token is missing/expired.
    }
  }

  if (userId) {
    const revokedAt = nowIso();
    let revokeSql = `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `;
    const revokeBindings = [revokedAt, userId];
    if (deviceId) {
      revokeSql += " AND device_id = ?";
      revokeBindings.push(deviceId);
    }
    const revokeResult = await dbRun(db, revokeSql, revokeBindings);
    revokedSessions = dbMetaChanges(revokeResult);
  }

  if (userId && deviceId) {
    const clearResult = await dbRun(
      db,
      `
        DELETE FROM api_key_device_activity
        WHERE user_id = ?
          AND device_id = ?
      `,
      [userId, deviceId],
    );
    clearedDeviceActivity = dbMetaChanges(clearResult);
  }

  return json(
    {
      ok: true,
      revoked_sessions: revokedSessions,
      cleared_device_activity: clearedDeviceActivity,
    },
    200,
    env,
  );
}

async function handleMe(request, env) {
  const auth = await requireAuthenticatedUserContext(
    request,
    env,
    { enforceApiKeyDevicePolicy: true },
    AUTH_SESSION_DEPS,
  );
  if (auth.error) {
    return auth.error;
  }
  const { db, user } = auth;
  const effectiveUserStatus = resolvePolicyPlanCode(user, null, env);
  const accountState = await buildAccountState(db, user, null, env);

  return json(
    {
      ok: true,
      email: user.email,
      user_status: effectiveUserStatus,
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

const TILE_ROUTE_DEPS = {
  PLAN_CODE_PLANETKA_FREE,
  clampNonNegativeInt,
  isQualityModeAllowedForPlan,
  isTileHotPathMonitoringEnabled,
  issueTileSessionToken,
  maybeSignalTileFarmingActivity,
  minimumPlanQualityForTile,
  normalizeDeviceId,
  normalizeQualityMode,
  normalizeRequestedPlan,
  normalizeResolveId,
  nowIso,
  parseJson,
  qualityModeNotAllowedMessage,
  rateLimitedResponse,
  readTileSessionClaims,
  recordTileRequestEvent,
  requestClientIp,
  requestCountry,
  requireAuthenticatedUserContext: (request, env, options) => requireAuthenticatedUserContext(request, env, options, AUTH_SESSION_DEPS),
  requireDb,
  resolveTileCacheControl,
};

const ADMIN_ROUTE_DEPS = {
  handleAdminAnalyticsData: (request, env) => handleAdminAnalyticsDataRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsPage: (request, env) => handleAdminAnalyticsPageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsTileMapImage: (request, env) => handleAdminAnalyticsTileMapImageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminAnalyticsUsersPage: (request, env) => handleAdminAnalyticsUsersPageRoute(request, env, ADMIN_ANALYTICS_DEPS),
  handleAdminLoginPage: (request, env) => handleAdminLoginPageRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminPasswordLogin: (request, env) => handleAdminPasswordLoginRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminSessionLogout: (request, env) => handleAdminSessionLogoutRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminSessionStart: (request, env) => handleAdminSessionStartRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminSessionStartPage: (request, env) => handleAdminSessionStartPageRoute(request, env, ADMIN_SESSION_DEPS),
  handleAdminUserBlock: (request, env) => handleAdminUserBlockRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserHardBlock: (request, env) => handleAdminUserHardBlockRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserSetPlan: (request, env) => handleAdminUserSetPlanRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserUnblock: (request, env) => handleAdminUserUnblockRoute(request, env, ADMIN_USER_DEPS),
};

async function dispatchExactRoute(request, env, path) {
  const adminMatch = await dispatchAdminRoute(request, env, path, ADMIN_ROUTE_DEPS);
  if (adminMatch) {
    return adminMatch;
  }
  switch (path) {
    case "/health":
      if (request.method === "GET") {
        return handleHealthRoute(env, PUBLIC_MISC_DEPS);
      }
      return null;
    case "/addon/update-manifest":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleAddonUpdateManifestRoute(request, env, PUBLIC_MISC_DEPS);
      }
      return null;
    case "/api-key":
      if (request.method === "GET" || request.method === "HEAD") {
        return handleApiKeyPageRoute(request, env, API_KEY_PAGE_DEPS);
      }
      return null;
    case "/api-key/activate":
      if (request.method === "GET") {
        return await handleApiKeyActivatePageRoute(request, env, API_KEY_PAGE_DEPS);
      }
      return null;
    case "/auth/api-key/request":
      if (request.method === "POST") {
        return await handleApiKeyRequest(request, env);
      }
      return null;
    case "/auth/api-key/activate":
      if (request.method === "POST") {
        return await handleApiKeyActivate(request, env);
      }
      return null;
    case "/auth/api-key/exchange":
      if (request.method === "POST") {
        return await handleApiKeyExchange(request, env);
      }
      return null;
    case "/auth/refresh":
      if (request.method === "POST") {
        return await handleAuthRefresh(request, env);
      }
      return null;
    case "/auth/logout":
      if (request.method === "POST") {
        return await handleAuthLogout(request, env);
      }
      return null;
    case "/me":
      if (request.method === "GET") {
        return await handleMe(request, env);
      }
      return null;
    case "/tiles/session":
      if (request.method === "POST") {
        return await handleTileSessionStartRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/support/bug-report":
      if (request.method === "POST") {
        return await handleSupportBugReportRoute(request, env, PUBLIC_MISC_DEPS);
      }
      return null;
    case "/stripe/webhook":
      if (request.method === "POST") {
        return await handleStripeWebhookRoute(request, env, BILLING_DEPS);
      }
      return null;
    default:
      return null;
  }
}

async function dispatchPrefixRoute(request, env, path, ctx) {
  if ((request.method === "GET" || request.method === "HEAD") && path.startsWith("/legal/")) {
    return await handleLegalDocumentRequestRoute(request, env, path, PUBLIC_MISC_DEPS);
  }
  if ((request.method === "GET" || request.method === "HEAD") && path.startsWith("/tiles/")) {
    return await handleTileRequestRoute(request, env, path, ctx, TILE_ROUTE_DEPS);
  }
  return null;
}

async function dispatchRequest(request, env, path, ctx) {
  const exactMatch = await dispatchExactRoute(request, env, path);
  if (exactMatch) {
    return exactMatch;
  }
  const prefixMatch = await dispatchPrefixRoute(request, env, path, ctx);
  if (prefixMatch) {
    return prefixMatch;
  }
  return json(
    {
      ok: false,
      error: "not_found",
      path,
    },
    404,
    env,
  );
}

async function trackAuthEndpointError(path, method, env, error) {
  if (!isAuthOrDevicePath(path)) {
    return;
  }
  try {
    const db = requireDb(env);
    await trackThresholdAlertDb(
      db,
      "auth_endpoint_error_spike",
      parseRateLimitInteger(env.LOG_ALERT_AUTH_ERROR_THRESHOLD, DEFAULT_ALERT_AUTH_ERROR_THRESHOLD),
      parseRateLimitInteger(env.LOG_ALERT_AUTH_ERROR_WINDOW_SECONDS, DEFAULT_ALERT_AUTH_ERROR_WINDOW_SECONDS),
      {
        route: path,
        method,
        error: String(error && error.message || "internal_error"),
      },
    );
  } catch (alertError) {
    // Alert tracking is best-effort and must never alter API error responses.
    console.debug(
      "worker.alert.tracking_failed",
      JSON.stringify({
        route: path,
        method,
        error: String(alertError && alertError.message || "alert_tracking_failed"),
      }),
    );
  }
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders(env),
      });
    }

    const url = new URL(request.url);
    const path = url.pathname;
    const queryToken = String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim();

    try {
      if (isAdminRoutePath(path) && queryToken) {
        return json({ ok: false, error: "query_token_not_allowed" }, 400, env);
      }
      return await dispatchRequest(request, env, path, ctx);
    } catch (error) {
      await trackAuthEndpointError(path, request.method, env, error);
      console.error(
        "worker.request.error",
        JSON.stringify({
          path,
          method: request.method,
          error: String(error.message || "internal_error"),
        }),
      );
      return json(
        {
          ok: false,
          error: "internal_error",
        },
        500,
        env,
      );
    }
  },
  async scheduled(controller, env, ctx) {
    const runStartedAt = nowIso();
    const scheduledAt = new Date(controller.scheduledTime || Date.now()).toISOString();
    ctx.waitUntil((async () => {
      try {
        const db = requireDb(env);
        const summary = await cleanupAuthTables(db, env, runStartedAt);
        const alertSummary = await runProductionAlertChecks(db, env, runStartedAt);
        const monthlyCostSummary = await runMonthlyCostEstimateAlerts(db, env, runStartedAt);
        console.log(
          "worker.db_cleanup.completed",
          JSON.stringify({
            scheduled_at: scheduledAt,
            ...summary,
            production_alert_summary: alertSummary,
            monthly_cost_summary: monthlyCostSummary,
          }),
        );
      } catch (error) {
        console.error(
          "worker.db_cleanup.error",
          JSON.stringify({
            scheduled_at: scheduledAt,
            error: String(error && error.message || "cleanup_failed"),
          }),
        );
      }
    })());
  },
};
