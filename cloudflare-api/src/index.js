import { buildAdminAnalyticsPageHtml } from "./admin_analytics_page.js";
const encoder = new TextEncoder();
const ADDON_ID = "planetka";
const BYTES_PER_GB = 1024 * 1024 * 1024;
const PLAN_CODE_PLANETKA_FREE = "free";
const PLAN_CODE_PLANETKA = "lite";
const PLAN_CODE_PLANETKA_PRO = "pro";
// Legacy aliases kept for backward compatibility in persisted data/webhook payloads.
const PLAN_CODE_PLANETKA_INDIE = PLAN_CODE_PLANETKA;
const PLAN_CODE_PLANETKA_STUDIO = PLAN_CODE_PLANETKA_PRO;
const DEFAULT_BETA_FORCE_PRO_TIER = false;
const DEFAULT_HOSTED_ACCESS_DURATION_DAYS = 365;
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
const DEFAULT_RATE_LIMIT_DEVICE_POLL_IP_LIMIT = 300;
const DEFAULT_RATE_LIMIT_DEVICE_POLL_IP_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_DEVICE_POLL_CODE_LIMIT = 120;
const DEFAULT_RATE_LIMIT_DEVICE_POLL_CODE_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT = 20;
const DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS = 300;
const DEFAULT_REFRESH_SESSION_CLEANUP_RETENTION_DAYS = 30;
const DEFAULT_ALERT_AUTH_429_THRESHOLD = 10;
const DEFAULT_ALERT_AUTH_429_WINDOW_SECONDS = 60;
const DEFAULT_ALERT_DEVICE_POLL_429_THRESHOLD = 30;
const DEFAULT_ALERT_DEVICE_POLL_429_WINDOW_SECONDS = 60;
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
const DEFAULT_ALERT_PROD_CLAIM_REJECTION_THRESHOLD = 5;
const DEFAULT_ALERT_PROD_CLAIM_REJECTION_WINDOW_SECONDS = 3600;
const DEFAULT_ALERT_PROD_COOLDOWN_SECONDS = 300;
const DEFAULT_TILE_FARM_ALERT_WINDOW_SECONDS = 300;
const DEFAULT_TILE_FARM_ALERT_USER_REQUEST_THRESHOLD = 300;
const DEFAULT_TILE_FARM_ALERT_IP_REQUEST_THRESHOLD = 500;
const DEFAULT_TILE_FARM_ALERT_UNIQUE_TILE_THRESHOLD = 200;
const DEFAULT_TILE_FARM_ALERT_UNTAGGED_MIN_REQUESTS = 120;
const DEFAULT_TILE_FARM_ALERT_UNTAGGED_PERCENT = 90;
const DEFAULT_TILE_FARM_ALERT_EMAIL_COOLDOWN_SECONDS = 300;
const DEFAULT_DOWNLOAD_MARK_STEP_GB = 100;
const DEFAULT_DOWNLOAD_THROTTLE_FREE_DAILY_GB = 0;
const DEFAULT_DOWNLOAD_THROTTLE_PRO_DAILY_GB = 0;
const DEFAULT_DOWNLOAD_THROTTLE_DURATION_MINUTES = 1440;
const DEFAULT_DOWNLOAD_THROTTLED_REQUESTS_PER_MINUTE = 0;
const DEFAULT_DOWNLOAD_THROTTLED_DELAY_MS = 30000;
const DEFAULT_TILE_SESSION_THROTTLE_CHECK_TTL_SECONDS = 1800;
const DEFAULT_TILE_SESSION_THROTTLE_CACHE_MAX_ENTRIES = 4096;
const DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS = 3600;
const DEFAULT_AUTH_CONTEXT_CACHE_TTL_SECONDS = 60;
const DEFAULT_AUTH_CONTEXT_CACHE_MAX_ENTRIES = 4096;
const DEFAULT_DOWNLOAD_ALERT_EMAIL_COOLDOWN_SECONDS = 300;
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
const DEFAULT_PERMANENT_PRO_EMAILS = "";
const DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS = "tom.griger@gmail.com";
const DEFAULT_TILE_EVENT_RETENTION_DAYS = 30;
const DEFAULT_AUTH_REFRESH_EVENT_RETENTION_DAYS = 30;
const DEFAULT_TILE_ROLLUP_RETENTION_DAYS = 365;
const BUG_REPORT_IMAGE_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_TILE_BROWSER_MAX_AGE_SECONDS = 86400;
const DEFAULT_TILE_EDGE_MAX_AGE_SECONDS = 604800;
const MAX_TILE_MAX_AGE_SECONDS = 31536000;
const DEFAULT_ENABLE_MAGIC_LINK_AUTH = false;
const DEFAULT_PRO_GRACE_HOURS = 24;
const DEFAULT_PENDING_CLAIM_COOLDOWN_DAYS = 7;
const DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS = 900;
const DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS = 2;
const DEFAULT_REJECTED_CLAIM_ALERT_THRESHOLD = 3;
const DEFAULT_REJECTED_CLAIM_ALERT_WINDOW_SECONDS = 86400;
const DEFAULT_PAID_CLAIM_RETENTION_DAYS = 180;
const RATE_LIMIT_PRUNE_INTERVAL_SECONDS = 300;
const RATE_LIMIT_ENTRY_TTL_SECONDS = 172800;
const API_KEY_REQUEST_TYPE_FREE = "free";
const API_KEY_REQUEST_TYPE_PAID_CLAIM = "paid_claim";
const CLAIM_REVIEW_PENDING = "pending";
const CLAIM_REVIEW_APPROVED = "approved";
const CLAIM_REVIEW_REJECTED = "rejected";
let userConsentColumnsReady = false;
let magicLinksTokenIndexReady = false;
let stripeWebhookEventsTableReady = false;
let rateLimitsTableReady = false;
let tileRequestEventsTableReady = false;
let authRefreshEventsTableReady = false;
let apiKeyTablesReady = false;
let userProvisionalColumnsReady = false;
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
let tileSessionThrottleGateCache = new Map();

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.APP_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Planetka-Device-Id, X-Planetka-Addon-Version, X-Planetka-Resolve-Id, X-Planetka-Quality-Mode, X-Planetka-Tile-Token",
  };
}

function json(data, status = 200, env = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(env),
    },
  });
}

function html(markup, status = 200, env = {}) {
  return new Response(markup, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
      Pragma: "no-cache",
      ...corsHeaders(env),
    },
  });
}

function jsonWithHeaders(data, status = 200, env = {}, extraHeaders = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(env),
      ...extraHeaders,
    },
  });
}

function publicErrorCode(error, fallbackCode, allowedCodes = null) {
  const code = String(error && error.message || fallbackCode).trim() || String(fallbackCode || "").trim() || "internal_error";
  if (allowedCodes instanceof Set && allowedCodes.size > 0) {
    return allowedCodes.has(code) ? code : String(fallbackCode || "internal_error");
  }
  return String(fallbackCode || "internal_error");
}

function publicErrorMessage(fallbackMessage) {
  return String(fallbackMessage || "Request failed. Please try again.");
}

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

function normalizeUserStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (
    normalized === PLAN_CODE_PLANETKA_PRO
    || normalized === "pro"
    || normalized === "planetka_pro"
    || normalized === "planetka_studio"
    || normalized === "studio"
  ) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (normalized === PLAN_CODE_PLANETKA_INDIE || normalized === "indie") {
    return PLAN_CODE_PLANETKA;
  }
  if (
    normalized === PLAN_CODE_PLANETKA
    || normalized === "planetka"
    || normalized === "personal"
    || normalized === "basic"
    || normalized === "lite"
  ) {
    return PLAN_CODE_PLANETKA;
  }
  if (normalized === PLAN_CODE_PLANETKA_FREE || normalized === "free" || normalized === "trial") {
    return PLAN_CODE_PLANETKA_FREE;
  }
  return normalized;
}

function normalizePlanCode(value) {
  return normalizeUserStatus(value);
}

function parseCsvEmailSet(value, fallback = "") {
  const set = new Set();
  const source = String(value || fallback || "").trim();
  if (!source) {
    return set;
  }
  for (const token of source.split(",")) {
    const email = normalizeEmail(token);
    if (email && email.includes("@")) {
      set.add(email);
    }
  }
  return set;
}

function isPermanentProEmail(email, env) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return false;
  }
  const set = parseCsvEmailSet(env.PERMANENT_PRO_EMAILS, DEFAULT_PERMANENT_PRO_EMAILS);
  return set.has(normalizedEmail);
}

function isDeviceLimitExemptEmail(email, env) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return false;
  }
  const set = parseCsvEmailSet(env.DEVICE_LIMIT_EXEMPT_EMAILS, DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS);
  return set.has(normalizedEmail);
}

function isBetaForceProTierEnabled(env = {}) {
  const raw = env.BETA_FORCE_PRO_TIER;
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    return DEFAULT_BETA_FORCE_PRO_TIER;
  }
  return parseBooleanFlag(raw);
}

function resolveEntitlementState(user, env = {}) {
  const status = normalizeUserStatus(user && user.status);
  const email = normalizeEmail(user && user.email);
  const confirmedAt = String(user && user.pro_confirmed_at || "").trim();
  const hostedAccessExpiresAt = String(user && user.pro_access_expires_at || "").trim();
  const hostedAccessExpiresAtMs = Date.parse(hostedAccessExpiresAt);
  const basePlanCode = (
    status === PLAN_CODE_PLANETKA_PRO
    || status === PLAN_CODE_PLANETKA
    || status === PLAN_CODE_PLANETKA_FREE
  )
    ? status
    : PLAN_CODE_PLANETKA_FREE;
  const isStatusPaid = status === PLAN_CODE_PLANETKA_PRO;
  const hasPaidSignal = Boolean(confirmedAt || isStatusPaid || hostedAccessExpiresAt);
  const hasFutureHostedAccessExpiry = Number.isFinite(hostedAccessExpiresAtMs) && hostedAccessExpiresAtMs > Date.now();
  const hasExpiredHostedAccess = Number.isFinite(hostedAccessExpiresAtMs) && hostedAccessExpiresAtMs <= Date.now();
  const defaultResult = {
    state: "trial",
    plan_code: basePlanCode,
    commercial_use_allowed: basePlanCode === PLAN_CODE_PLANETKA_PRO,
    subscription_status: "inactive",
    is_permanent_paid: false,
    is_provisional_paid: false,
    is_expired_provisional: false,
    source: "trial",
    email,
    hosted_streaming_access_expires_at: "",
  };
  if (user && isBlockedStatus(user.status)) {
    return {
      ...defaultResult,
      state: "blocked",
      plan_code: "blocked",
      source: "blocked",
    };
  }
  if (isBetaForceProTierEnabled(env)) {
    return {
      ...defaultResult,
      state: "permanent_paid",
      plan_code: PLAN_CODE_PLANETKA_PRO,
      commercial_use_allowed: true,
      subscription_status: "active",
      is_permanent_paid: true,
      source: "beta_force_pro",
      hosted_streaming_access_expires_at: "",
    };
  }
  if (isPermanentProEmail(email, env)) {
    return {
      ...defaultResult,
      state: "permanent_paid",
      plan_code: PLAN_CODE_PLANETKA_PRO,
      commercial_use_allowed: true,
      subscription_status: "active",
      is_permanent_paid: true,
      source: "allowlist",
      hosted_streaming_access_expires_at: "",
    };
  }
  if (hasPaidSignal && hasExpiredHostedAccess) {
    return {
      ...defaultResult,
      state: "expired_paid",
      source: "expired",
      hosted_streaming_access_expires_at: hostedAccessExpiresAt,
    };
  }
  if (hasFutureHostedAccessExpiry) {
    return {
      ...defaultResult,
      state: "permanent_paid",
      plan_code: PLAN_CODE_PLANETKA_PRO,
      commercial_use_allowed: true,
      subscription_status: "active",
      is_permanent_paid: true,
      source: confirmedAt ? "confirmed" : "expiry",
      hosted_streaming_access_expires_at: hostedAccessExpiresAt,
    };
  }
  if (hasPaidSignal) {
    return {
      ...defaultResult,
      state: "trial",
      source: "paid_signal_without_active_access",
      hosted_streaming_access_expires_at: hostedAccessExpiresAt,
    };
  }
  return defaultResult;
}

function subscriptionStatusForUser(user, env = {}) {
  void env;
  if (user && isBlockedStatus(user.status)) {
    return "inactive";
  }
  return "active";
}

function resolvePolicyPlanCode(user, subscription, env = {}) {
  void subscription;
  if (user && isBlockedStatus(user.status)) {
    return "blocked";
  }
  if (isBetaForceProTierEnabled(env)) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  const entitlement = resolveEntitlementState(user, env);
  const entitlementPlan = normalizeRequestedPlan(entitlement && entitlement.plan_code);
  if (entitlementPlan === PLAN_CODE_PLANETKA_PRO) {
    return entitlementPlan;
  }
  if (
    entitlementPlan === PLAN_CODE_PLANETKA
    || entitlementPlan === PLAN_CODE_PLANETKA_FREE
  ) {
    return entitlementPlan;
  }
  const currentStatus = normalizeUserStatus(user && user.status);
  if (currentStatus === PLAN_CODE_PLANETKA_PRO) {
    return currentStatus;
  }
  if (
    currentStatus === PLAN_CODE_PLANETKA
    || currentStatus === PLAN_CODE_PLANETKA_FREE
  ) {
    return currentStatus;
  }
  return PLAN_CODE_PLANETKA_FREE;
}

function parseBooleanFlag(value) {
  if (typeof value === "boolean") {
    return value;
  }
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function isTileHotPathMonitoringEnabled(env = {}) {
  const raw = env.ENABLE_TILE_HOT_PATH_MONITORING;
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    // Default off: keep tile request path focused on serving data.
    return false;
  }
  return parseBooleanFlag(raw);
}

function isMagicLinkAuthEnabled(env = {}) {
  const raw = env.ENABLE_MAGIC_LINK_AUTH;
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    return DEFAULT_ENABLE_MAGIC_LINK_AUTH;
  }
  return parseBooleanFlag(raw);
}

function isBlockedStatus(statusValue) {
  return String(statusValue || "").trim().toLowerCase() === "blocked";
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

function parsePositiveNumber(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

function parseNonNegativeInteger(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(0, Math.floor(parsed));
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

function normalizeRequestedPlan(value) {
  const normalized = normalizePlanCode(value);
  if (normalized === PLAN_CODE_PLANETKA_PRO) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (normalized === PLAN_CODE_PLANETKA) {
    return PLAN_CODE_PLANETKA;
  }
  if (normalized === PLAN_CODE_PLANETKA_STUDIO) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (normalized === PLAN_CODE_PLANETKA_FREE) {
    return PLAN_CODE_PLANETKA_FREE;
  }
  return PLAN_CODE_PLANETKA_FREE;
}

function normalizeQualityMode(value) {
  const safe = String(value || "").trim().toLowerCase();
  if (safe === "full") return "full";
  if (safe === "balanced") return "balanced";
  return "preview";
}

function isQualityModeAllowedForPlan(planCode, qualityMode) {
  const safePlanCode = normalizeRequestedPlan(planCode);
  const safeMode = normalizeQualityMode(qualityMode);
  if (safeMode === "preview") {
    return true;
  }
  if (safeMode === "balanced") {
    return safePlanCode === PLAN_CODE_PLANETKA || safePlanCode === PLAN_CODE_PLANETKA_PRO;
  }
  if (safeMode === "full") {
    return safePlanCode === PLAN_CODE_PLANETKA_PRO;
  }
  return false;
}

function qualityModeNotAllowedMessage(planCode, qualityMode) {
  const safePlanCode = normalizeRequestedPlan(planCode);
  const safeMode = normalizeQualityMode(qualityMode);
  if (safePlanCode === PLAN_CODE_PLANETKA_FREE) {
    return "Free tier supports Preview only. Upgrade Licence for Balanced or Full Quality.";
  }
  if (safePlanCode === PLAN_CODE_PLANETKA && safeMode === "full") {
    return "Personal tier supports Preview and Balanced. Upgrade Licence for Full Quality.";
  }
  return "Selected texture quality is not available for this account tier.";
}

function isPaidRequestedPlan(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  return normalized === PLAN_CODE_PLANETKA_PRO;
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

function computePendingClaimCooldownIso(env) {
  return addDaysIso(parseClaimCooldownDays(env));
}

function thresholdHit(count, threshold) {
  if (threshold <= 0) {
    return false;
  }
  return count === threshold || (count > threshold && (count % threshold) === 0);
}

function normalizeClaimReviewStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === CLAIM_REVIEW_APPROVED) {
    return CLAIM_REVIEW_APPROVED;
  }
  if (normalized === CLAIM_REVIEW_REJECTED) {
    return CLAIM_REVIEW_REJECTED;
  }
  return CLAIM_REVIEW_PENDING;
}

function isUnconfirmedProvisionalActive(user) {
  const entitlement = resolveEntitlementState(user);
  return entitlement.state === "provisional_paid";
}

function isUnconfirmedProvisionalExpired(user) {
  const entitlement = resolveEntitlementState(user);
  return entitlement.state === "expired_provisional";
}

function computeApiKeyExpiryIso(planCode, env) {
  void planCode;
  void env;
  // API keys are non-expiring for this release.
  return "";
}

function computeHostedStreamingAccessExpiryIso(env, startMs = Date.now()) {
  const durationDays = Math.max(
    1,
    Math.floor(parsePositiveNumber(env.HOSTED_ACCESS_DURATION_DAYS, DEFAULT_HOSTED_ACCESS_DURATION_DAYS)),
  );
  const safeStartMs = Number.isFinite(Number(startMs))
    ? Math.max(0, Math.floor(Number(startMs)))
    : Date.now();
  return new Date(safeStartMs + (durationDays * 24 * 60 * 60 * 1000)).toISOString();
}

function computeProvisionalExpiryIso(env) {
  const graceHours = Math.max(
    1,
    Math.floor(parsePositiveNumber(env.PRO_LICENSE_GRACE_HOURS, DEFAULT_PRO_GRACE_HOURS)),
  );
  return new Date(Date.now() + (graceHours * 60 * 60 * 1000)).toISOString();
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

function tileSessionThrottleCheckCacheTtlMs(env = {}) {
  const ttlSeconds = Math.min(
    3600,
    Math.max(
      60,
      parseRateLimitInteger(
        env.TILE_SESSION_THROTTLE_CHECK_TTL_SECONDS,
        DEFAULT_TILE_SESSION_THROTTLE_CHECK_TTL_SECONDS,
      ),
    ),
  );
  return ttlSeconds * 1000;
}

function tileSessionThrottleCacheMaxEntries(env = {}) {
  return Math.min(
    20000,
    Math.max(
      64,
      parseRateLimitInteger(
        env.TILE_SESSION_THROTTLE_CACHE_MAX_ENTRIES,
        DEFAULT_TILE_SESSION_THROTTLE_CACHE_MAX_ENTRIES,
      ),
    ),
  );
}

function tileSessionThrottleGateCacheGet(key) {
  const safeKey = String(key || "").trim();
  if (!safeKey) {
    return null;
  }
  const entry = tileSessionThrottleGateCache.get(safeKey);
  if (!entry) {
    return null;
  }
  if (!Number.isFinite(entry.expiresAtMs) || entry.expiresAtMs <= Date.now()) {
    tileSessionThrottleGateCache.delete(safeKey);
    return null;
  }
  return entry.value;
}

function tileSessionThrottleGateCacheSet(key, value, env = {}, ttlMsOverride = 0) {
  const safeKey = String(key || "").trim();
  if (!safeKey) {
    return;
  }
  const baseTtlMs = tileSessionThrottleCheckCacheTtlMs(env);
  let ttlMs = Number.isFinite(Number(ttlMsOverride)) && Number(ttlMsOverride) > 0
    ? Number(ttlMsOverride)
    : baseTtlMs;
  ttlMs = Math.max(1000, Math.min(baseTtlMs, ttlMs));

  const maxEntries = tileSessionThrottleCacheMaxEntries(env);
  if (tileSessionThrottleGateCache.size >= maxEntries) {
    const nowMs = Date.now();
    for (const [entryKey, entryValue] of tileSessionThrottleGateCache.entries()) {
      if (!entryValue || !Number.isFinite(entryValue.expiresAtMs) || entryValue.expiresAtMs <= nowMs) {
        tileSessionThrottleGateCache.delete(entryKey);
      }
    }
  }
  while (tileSessionThrottleGateCache.size >= maxEntries) {
    const oldestKey = tileSessionThrottleGateCache.keys().next().value;
    if (!oldestKey) {
      break;
    }
    tileSessionThrottleGateCache.delete(oldestKey);
  }
  tileSessionThrottleGateCache.set(safeKey, {
    expiresAtMs: Date.now() + ttlMs,
    value,
  });
}

function resolveDownloadThrottleRetryAfterSeconds(gate) {
  const direct = clampNonNegativeInt(gate && gate.retryAfterSeconds);
  if (direct > 0) {
    return direct;
  }
  const throttledUntilMs = Date.parse(String(gate && gate.throttledUntil || ""));
  if (Number.isFinite(throttledUntilMs)) {
    return Math.max(1, Math.ceil((throttledUntilMs - Date.now()) / 1000));
  }
  return 60;
}

async function enforceTileSessionThrottleGateCached(db, env, user, requestDeviceId = "", requestIp = "") {
  const userId = String(user && user.id || "").trim();
  if (!userId) {
    return null;
  }
  const cacheKey = `tile_session_gate:${userId}`;
  const cached = tileSessionThrottleGateCacheGet(cacheKey);
  if (cached) {
    return cached.throttleGate;
  }
  const throttleGate = await enforceDownloadThrottleGate(db, env, user, requestDeviceId, requestIp);
  if (throttleGate && (throttleGate.blocked || throttleGate.isThrottled)) {
    const retryAfterSeconds = resolveDownloadThrottleRetryAfterSeconds(throttleGate);
    const ttlMs = Math.min(60000, Math.max(5000, retryAfterSeconds * 1000));
    tileSessionThrottleGateCacheSet(
      cacheKey,
      {
        throttleGate,
      },
      env,
      ttlMs,
    );
    return throttleGate;
  }
  tileSessionThrottleGateCacheSet(
    cacheKey,
    {
      throttleGate: null,
    },
    env,
  );
  return null;
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

function parseDownloadAlertWhitelistSet(env) {
  const explicit = parseCsvEmailSet(env.DOWNLOAD_ALERT_WHITELIST_EMAILS, "");
  const adminSet = parseAdminEmailSet(env);
  const permanentSet = parseCsvEmailSet(env.PERMANENT_PRO_EMAILS, DEFAULT_PERMANENT_PRO_EMAILS);
  for (const email of adminSet) {
    explicit.add(email);
  }
  for (const email of permanentSet) {
    explicit.add(email);
  }
  return explicit;
}

function isDownloadAlertWhitelisted(email, env) {
  const normalized = normalizeEmail(email);
  if (!normalized) {
    return false;
  }
  const whitelist = parseDownloadAlertWhitelistSet(env);
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

async function ensureUserDownloadCountersTable(db) {
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_download_counters (
        user_id TEXT PRIMARY KEY,
        user_email TEXT NOT NULL,
        plan_code TEXT NOT NULL DEFAULT 'planetka',
        lifetime_bytes INTEGER NOT NULL DEFAULT 0,
        hour_bucket_start_unix INTEGER NOT NULL DEFAULT 0,
        hour_bytes INTEGER NOT NULL DEFAULT 0,
        day_bucket_start_unix INTEGER NOT NULL DEFAULT 0,
        day_bytes INTEGER NOT NULL DEFAULT 0,
        week_bucket_start_unix INTEGER NOT NULL DEFAULT 0,
        week_bytes INTEGER NOT NULL DEFAULT 0,
        month_bucket_start TEXT NOT NULL DEFAULT '',
        month_bytes INTEGER NOT NULL DEFAULT 0,
        last_notified_lifetime_mark INTEGER NOT NULL DEFAULT 0,
        last_notified_hour_mark INTEGER NOT NULL DEFAULT 0,
        last_notified_day_mark INTEGER NOT NULL DEFAULT 0,
        last_notified_week_mark INTEGER NOT NULL DEFAULT 0,
        last_notified_month_mark INTEGER NOT NULL DEFAULT 0,
        throttled_until TEXT,
        throttle_reason TEXT,
        last_request_at TEXT,
        last_ip TEXT,
        last_device_id TEXT,
        last_country TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_user_download_counters_plan ON user_download_counters(plan_code, lifetime_bytes DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_user_download_counters_updated ON user_download_counters(updated_at DESC)`,
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

async function findUserDownloadCounter(db, userId) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  await ensureUserDownloadCountersTable(db);
  return dbGet(
    db,
    `
      SELECT
        user_id,
        user_email,
        plan_code,
        lifetime_bytes,
        hour_bucket_start_unix,
        hour_bytes,
        day_bucket_start_unix,
        day_bytes,
        week_bucket_start_unix,
        week_bytes,
        month_bucket_start,
        month_bytes,
        last_notified_lifetime_mark,
        last_notified_hour_mark,
        last_notified_day_mark,
        last_notified_week_mark,
        last_notified_month_mark,
        throttled_until,
        throttle_reason,
        last_request_at,
        last_ip,
        last_device_id,
        last_country,
        created_at,
        updated_at
      FROM user_download_counters
      WHERE user_id = ?
      LIMIT 1
    `,
    [safeUserId],
  );
}

async function findUserDownloadCounterByEmail(db, email) {
  const safeEmail = normalizeEmail(email);
  if (!safeEmail) {
    return null;
  }
  await ensureUserDownloadCountersTable(db);
  return dbGet(
    db,
    `
      SELECT
        user_id,
        user_email,
        plan_code,
        lifetime_bytes,
        hour_bucket_start_unix,
        hour_bytes,
        day_bucket_start_unix,
        day_bytes,
        week_bucket_start_unix,
        week_bytes,
        month_bucket_start,
        month_bytes,
        last_notified_lifetime_mark,
        last_notified_hour_mark,
        last_notified_day_mark,
        last_notified_week_mark,
        last_notified_month_mark,
        throttled_until,
        throttle_reason,
        last_request_at,
        last_ip,
        last_device_id,
        last_country,
        created_at,
        updated_at
      FROM user_download_counters
      WHERE user_email = ?
      ORDER BY updated_at DESC
      LIMIT 1
    `,
    [safeEmail],
  );
}

async function clearUserDownloadThrottle(db, userId, options = {}) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  const resetHour = options.resetHour !== false;
  const now = nowIso();
  const nowUnix = Math.floor(Date.now() / 1000);
  const currentHourStart = startOfHourUnix(nowUnix);
  await ensureUserDownloadCountersTable(db);
  await dbRun(
    db,
    `
      UPDATE user_download_counters
      SET
        throttled_until = NULL,
        throttle_reason = 'manual_unthrottle',
        hour_bucket_start_unix = CASE WHEN ? = 1 THEN ? ELSE hour_bucket_start_unix END,
        hour_bytes = CASE WHEN ? = 1 THEN 0 ELSE hour_bytes END,
        updated_at = ?
      WHERE user_id = ?
    `,
    [resetHour ? 1 : 0, currentHourStart, resetHour ? 1 : 0, now, safeUserId],
  );
  return findUserDownloadCounter(db, safeUserId);
}

async function setUserDownloadThrottle(db, userId, options = {}) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  const now = nowIso();
  const durationMinutes = Math.max(
    1,
    parseNonNegativeInteger(options.durationMinutes, DEFAULT_DOWNLOAD_THROTTLE_DURATION_MINUTES),
  );
  const nowUnix = Math.floor(Date.now() / 1000);
  const resetHour = options.resetHour === true;
  const currentHourStart = startOfHourUnix(nowUnix);
  const throttledUntil = new Date((nowUnix + (durationMinutes * 60)) * 1000).toISOString();
  await ensureUserDownloadCountersTable(db);
  await dbRun(
    db,
    `
      UPDATE user_download_counters
      SET
        throttled_until = ?,
        throttle_reason = 'manual_admin_throttle',
        hour_bucket_start_unix = CASE WHEN ? = 1 THEN ? ELSE hour_bucket_start_unix END,
        hour_bytes = CASE WHEN ? = 1 THEN 0 ELSE hour_bytes END,
        updated_at = ?
      WHERE user_id = ?
    `,
    [throttledUntil, resetHour ? 1 : 0, currentHourStart, resetHour ? 1 : 0, now, safeUserId],
  );
  return findUserDownloadCounter(db, safeUserId);
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

function yearBucketKey(epochSeconds) {
  const safe = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  return String(new Date(safe * 1000).getUTCFullYear());
}

function weekBucketKey(epochSeconds) {
  return String(startOfWeekUnix(epochSeconds));
}

function monthEndIso(epochSeconds) {
  const safe = Math.max(0, parseNonNegativeInteger(epochSeconds, Math.floor(Date.now() / 1000)));
  const date = new Date(safe * 1000);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  const nextMonthStartMs = Date.UTC(year, month + 1, 1, 0, 0, 0, 0);
  return new Date(nextMonthStartMs - 1000).toISOString();
}

function resolveDailyThrottleThresholdGbForPlan(planCode, env = {}) {
  const safePlanCode = normalizeRequestedPlan(planCode || PLAN_CODE_PLANETKA);
  if (safePlanCode === PLAN_CODE_PLANETKA) {
    const trialConfigured = Number(env.DOWNLOAD_THROTTLE_FREE_DAILY_GB);
    if (Number.isFinite(trialConfigured) && trialConfigured > 0) {
      return trialConfigured;
    }
    return DEFAULT_DOWNLOAD_THROTTLE_FREE_DAILY_GB;
  }
  const activeConfigured = Number(env.DOWNLOAD_THROTTLE_PRO_DAILY_GB);
  if (Number.isFinite(activeConfigured) && activeConfigured >= 0) {
    return activeConfigured;
  }
  return DEFAULT_DOWNLOAD_THROTTLE_PRO_DAILY_GB;
}

function resolveDailyThrottleThresholdBytesForPlan(planCode, env = {}) {
  const thresholdGb = resolveDailyThrottleThresholdGbForPlan(planCode, env);
  if (!Number.isFinite(thresholdGb) || thresholdGb <= 0) {
    return 0;
  }
  return Math.max(1, toBytesFromGb(thresholdGb));
}

async function getRolling24hBytesForUser(db, userId, nowUnix) {
  await ensureTileRequestRollupTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return 0;
  }
  const safeNowUnix = Math.max(0, parseNonNegativeInteger(nowUnix, Math.floor(Date.now() / 1000)));
  const windowStartUnix = Math.max(0, safeNowUnix - (24 * 60 * 60));
  const row = await dbGet(
    db,
    `
      SELECT COALESCE(SUM(bytes_served), 0) AS bytes_served
      FROM tile_request_rollup_hourly_account
      WHERE user_id = ?
        AND bucket_start_unix >= ?
    `,
    [safeUserId, windowStartUnix],
  );
  return clampNonNegativeInt(row && row.bytes_served);
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
  await ensureUserDownloadCountersTable(db);
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
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), COALESCE(NULLIF(TRIM(LOWER(c.plan_code)), ''), ?)) AS plan_norm
        FROM tile_request_rollup_daily_account r
        LEFT JOIN users u ON u.id = r.user_id
        LEFT JOIN user_download_counters c ON c.user_id = r.user_id
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
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), COALESCE(NULLIF(TRIM(LOWER(c.plan_code)), ''), ?)) AS plan_norm
        FROM tile_request_events e
        LEFT JOIN users u ON u.id = e.user_id
        LEFT JOIN user_download_counters c ON c.user_id = e.user_id
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
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), COALESCE(NULLIF(TRIM(LOWER(c.plan_code)), ''), ?)) AS plan_norm
      FROM tile_request_events e
      LEFT JOIN users u ON u.id = e.user_id
      LEFT JOIN user_download_counters c ON c.user_id = e.user_id
      WHERE
        e.created_at_unix >= ?
        AND e.user_id IS NOT NULL
        AND e.user_id != ''
        ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      GROUP BY
        e.user_id,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), COALESCE(NULLIF(TRIM(LOWER(c.plan_code)), ''), ?))
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
          COALESCE(NULLIF(TRIM(e.user_email), ''), COALESCE(NULLIF(TRIM(u.email), ''), COALESCE(NULLIF(TRIM(c.user_email), ''), ''))) AS user_email,
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), COALESCE(NULLIF(TRIM(LOWER(c.plan_code)), ''), ?)) AS user_status,
          COUNT(*) AS request_count,
          COALESCE(COUNT(DISTINCT CASE WHEN e.resolve_id IS NOT NULL AND e.resolve_id != '' THEN e.resolve_id END), 0) AS resolve_count,
          COALESCE(SUM(e.bytes_served), 0) AS bytes_served,
          MAX(e.created_at) AS last_seen_at
        FROM tile_request_events e
        LEFT JOIN users u ON u.id = e.user_id
        LEFT JOIN user_download_counters c ON c.user_id = e.user_id
        WHERE
          e.created_at_unix >= ?
          AND e.status_code < 400
          ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
        GROUP BY
          e.user_id,
          COALESCE(NULLIF(TRIM(e.user_email), ''), COALESCE(NULLIF(TRIM(u.email), ''), COALESCE(NULLIF(TRIM(c.user_email), ''), ''))),
          COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), COALESCE(NULLIF(TRIM(LOWER(c.plan_code)), ''), ?))
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

  const heavyFilter = buildHeavyUserFilterSql(safePlanFilter);
  const heavyWhereParts = [];
  const heavyBindings = [];
  if (heavyFilter.clause) {
    heavyWhereParts.push(String(heavyFilter.clause).replace(/^WHERE\\s+/i, "").trim());
    heavyBindings.push(...heavyFilter.bindings);
  }
  if (heavyEmailFilter.condition) {
    heavyWhereParts.push(heavyEmailFilter.condition);
    heavyBindings.push(...heavyEmailFilter.bindings);
  }
  const heavyWhereSql = heavyWhereParts.length ? `WHERE ${heavyWhereParts.join(" AND ")}` : "";
  const heavyBaseSql = `
      SELECT
        c.user_id,
        c.user_email,
        c.plan_code,
        COALESCE(u.status, c.plan_code) AS user_status,
        c.lifetime_bytes,
        c.month_bytes,
        c.week_bytes,
        c.day_bytes,
        c.hour_bytes,
        c.throttled_until,
        c.last_request_at,
        c.last_ip,
        c.last_device_id,
        c.last_country
      FROM user_download_counters c
      LEFT JOIN users u ON u.id = c.user_id
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
  // Keep main-page Heavy Users consistent with All Users page:
  // both must use user_download_counters.month_bytes.
  let heavyUsers30d = (Array.isArray(topHeavyMonth) ? topHeavyMonth : [])
    .map((row) => {
      const lastRequestAt = String(row && row.last_request_at || "").trim();
      const parsedLastRequestUnix = Date.parse(lastRequestAt);
      return {
        user_id: String(row && row.user_id || "").trim(),
        user_email: normalizeEmail(row && row.user_email || ""),
        user_status: String(row && (row.user_status || row.plan_code) || PLAN_CODE_PLANETKA).trim().toLowerCase() || PLAN_CODE_PLANETKA,
        throttled_until: String(row && row.throttled_until || "").trim(),
        month_bytes: clampNonNegativeInt(row && row.month_bytes),
        request_count_month: 0,
        last_event_unix: Number.isFinite(parsedLastRequestUnix) ? Math.max(0, Math.floor(parsedLastRequestUnix / 1000)) : 0,
      };
    });
  const heavyMonthUserIds = Array.from(new Set(heavyUsers30d.map((row) => row.user_id).filter(Boolean)));
  if (heavyMonthUserIds.length > 0) {
    try {
      const placeholders = heavyMonthUserIds.map(() => "?").join(",");
      const monthRequestRows = await dbAll(
        db,
        `
          SELECT
            user_id,
            COALESCE(SUM(request_count), 0) AS request_count_month,
            MAX(last_event_unix) AS last_event_unix
          FROM tile_request_rollup_daily_account
          WHERE
            day_start_unix >= ?
            AND user_id IN (${placeholders})
          GROUP BY user_id
        `,
        [monthStartUnix(nowUnix), ...heavyMonthUserIds],
      );
      const monthRequestsByUserId = new Map();
      for (const row of (Array.isArray(monthRequestRows) ? monthRequestRows : [])) {
        const userId = String(row && row.user_id || "").trim();
        if (!userId) continue;
        monthRequestsByUserId.set(userId, {
          request_count_month: clampNonNegativeInt(row && row.request_count_month),
          last_event_unix: clampNonNegativeInt(row && row.last_event_unix),
        });
      }
      heavyUsers30d = heavyUsers30d.map((row) => {
        const monthMeta = monthRequestsByUserId.get(String(row.user_id || "").trim()) || null;
        const requestCountMonth = clampNonNegativeInt(monthMeta && monthMeta.request_count_month);
        const lastEventUnix = Math.max(
          clampNonNegativeInt(row && row.last_event_unix),
          clampNonNegativeInt(monthMeta && monthMeta.last_event_unix),
        );
        const monthBytes = clampNonNegativeInt(row && row.month_bytes);
        return {
          ...row,
          request_count_month: requestCountMonth,
          last_event_unix: lastEventUnix,
          // Keep legacy keys for compatibility with current UI/client payload shape.
          request_count_30d: requestCountMonth,
          bytes_served_30d: monthBytes,
        };
      });
    } catch (error) {
      console.warn(
        "planetka.analytics.heavy_users_month_requests_query_failed",
        JSON.stringify({
          error: String(error && error.message || "heavy_users_month_requests_query_failed"),
        }),
      );
    }
  }
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
  if (userEmail && isDownloadAlertWhitelisted(userEmail, env)) {
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
  await ensureUserDownloadCountersTable(db);
  const sortBy = parseAnalyticsUsersSort(options.sort_by);
  const sortDir = parseAnalyticsUsersSortDirection(options.sort_dir);
  const query = String(options.query || "").trim().toLowerCase();
  const limit = Math.max(1, Math.min(5000, parseNonNegativeInteger(options.limit, 5000)));
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
  const bindings = [PLAN_CODE_PLANETKA, PLAN_CODE_PLANETKA];
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
      )
      SELECT
        u.id AS user_id,
        u.email AS user_email,
        COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?) AS user_status,
        COALESCE(NULLIF(TRIM(LOWER(c.plan_code)), ''), COALESCE(NULLIF(TRIM(LOWER(u.status)), ''), ?)) AS plan_code,
        COALESCE(rc.resolve_count, 0) AS resolve_count,
        COALESCE(c.lifetime_bytes, 0) AS lifetime_bytes,
        COALESCE(c.month_bytes, 0) AS month_bytes,
        COALESCE(c.week_bytes, 0) AS week_bytes,
        COALESCE(c.day_bytes, 0) AS day_bytes,
        COALESCE(c.hour_bytes, 0) AS hour_bytes,
        COALESCE(NULLIF(TRIM(c.throttled_until), ''), '') AS throttled_until,
        COALESCE(NULLIF(TRIM(c.last_request_at), ''), COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), ''))) AS last_seen_at,
        COALESCE(strftime('%s', COALESCE(NULLIF(TRIM(c.last_request_at), ''), COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), '')))), 0) AS last_seen_unix
      FROM users u
      LEFT JOIN user_download_counters c ON c.user_id = u.id
      LEFT JOIN resolve_counts rc ON rc.user_id = u.id
      ${whereSql}
      ORDER BY ${orderSql} ${sortDir.toUpperCase()}, LOWER(COALESCE(u.email, '')) ASC
      LIMIT ${limit}
    `,
    bindings,
  );
}

async function sendUserThrottledEmail(env, email, details = {}) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return;
  }
  const apiKey = requireSecret(env, "EMAIL_API_KEY");
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const contactUrl = normalizeContactUrl(env.PLANETKA_CONTACT_URL || DEFAULT_CONTACT_URL);
  const recentWindowGb = Number(details.recentWindowGb || 0).toFixed(2);
  const thresholdGb = Number(details.thresholdGb || 0).toFixed(2);
  const windowLabel = String(details.windowLabel || "24h").trim() || "24h";
  const throttledUntil = String(details.throttledUntil || "").trim() || "soon";
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [normalizedEmail],
      subject: "Planetka account temporarily throttled",
      text: [
        "Your Planetka account has been temporarily throttled due to unusually high data volume.",
        "",
        `Recent ${windowLabel} volume: ${recentWindowGb} GB`,
        `Throttle threshold: ${thresholdGb} GB/${windowLabel}`,
        `Throttle active until: ${throttledUntil}`,
        "",
        "If this is expected usage, contact us so we can review and assist:",
        contactUrl,
      ].join("\n"),
      html: `
        <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
          <h2 style="margin-bottom: 12px;">Planetka account temporarily throttled</h2>
          <p>Your Planetka account was temporarily throttled due to unusually high data volume.</p>
          <ul>
            <li><strong>Recent ${escapeHtml(windowLabel)} volume:</strong> ${escapeHtml(recentWindowGb)} GB</li>
            <li><strong>Throttle threshold:</strong> ${escapeHtml(thresholdGb)} GB/${escapeHtml(windowLabel)}</li>
            <li><strong>Throttle active until:</strong> ${escapeHtml(throttledUntil)}</li>
          </ul>
          <p>If this usage is expected, please contact us so we can review and assist:</p>
          <p><a href="${escapeHtml(contactUrl)}">${escapeHtml(contactUrl)}</a></p>
        </div>
      `,
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`resend_error_${response.status}_${body}`);
  }
}

async function maybeProcessDownloadMonitoring(db, env, details = {}) {
  if (!db) {
    return;
  }
  const userId = String(details.userId || "").trim();
  const userEmail = normalizeEmail(details.userEmail || "");
  if (!userId || !userEmail) {
    return;
  }
  const bytesUsed = clampNonNegativeInt(details.bytesUsed);
  if (bytesUsed <= 0) {
    return;
  }

  await ensureUserDownloadCountersTable(db);
  await ensureRateLimitsTable(db);
  const nowUnix = parseNonNegativeInteger(details.createdAtUnix, Math.floor(Date.now() / 1000));
  const now = new Date(nowUnix * 1000).toISOString();
  const safePlanCode = normalizeRequestedPlan(details.planCode || PLAN_CODE_PLANETKA);
  const ip = String(details.ip || "").trim();
  const deviceId = normalizeDeviceId(details.deviceId || "");
  const country = String(details.country || "").trim().toUpperCase();
  const whitelisted = isDownloadAlertWhitelisted(userEmail, env);

  const hourBucket = startOfHourUnix(nowUnix);
  const dayBucket = startOfDayUnix(nowUnix);
  const weekBucket = startOfWeekUnix(nowUnix);
  const monthBucket = monthBucketKey(nowUnix);
  const existing = await findUserDownloadCounter(db, userId);

  const lifetimeBytes = clampNonNegativeInt(existing && existing.lifetime_bytes) + bytesUsed;
  const hourBytes = (
    parseNonNegativeInteger(existing && existing.hour_bucket_start_unix, hourBucket) === hourBucket
      ? clampNonNegativeInt(existing && existing.hour_bytes)
      : 0
  ) + bytesUsed;
  const dayBytes = (
    parseNonNegativeInteger(existing && existing.day_bucket_start_unix, dayBucket) === dayBucket
      ? clampNonNegativeInt(existing && existing.day_bytes)
      : 0
  ) + bytesUsed;
  const weekBytes = (
    parseNonNegativeInteger(existing && existing.week_bucket_start_unix, weekBucket) === weekBucket
      ? clampNonNegativeInt(existing && existing.week_bytes)
      : 0
  ) + bytesUsed;
  const monthBytes = (
    String(existing && existing.month_bucket_start || "") === monthBucket
      ? clampNonNegativeInt(existing && existing.month_bytes)
      : 0
  ) + bytesUsed;

  const rolling24hBytes = await getRolling24hBytesForUser(db, userId, nowUnix);
  const thresholdBytes = resolveDailyThrottleThresholdBytesForPlan(safePlanCode, env);
  const throttleDurationMinutes = Math.max(
    5,
    parseRateLimitInteger(env.DOWNLOAD_THROTTLE_DURATION_MINUTES, DEFAULT_DOWNLOAD_THROTTLE_DURATION_MINUTES),
  );
  const currentThrottleUntil = String(existing && existing.throttled_until || "").trim();
  const currentThrottleUntilMs = Date.parse(currentThrottleUntil);
  const throttleShouldActivate = !whitelisted && thresholdBytes > 0 && rolling24hBytes >= thresholdBytes;
  const nextThrottleUntilMs = throttleShouldActivate
    ? Math.max(
      Number.isFinite(currentThrottleUntilMs) ? currentThrottleUntilMs : 0,
      (nowUnix + (throttleDurationMinutes * 60)) * 1000,
    )
    : (Number.isFinite(currentThrottleUntilMs) ? currentThrottleUntilMs : 0);
  const throttledUntil = nextThrottleUntilMs > (nowUnix * 1000)
    ? new Date(nextThrottleUntilMs).toISOString()
    : "";

  await dbRun(
    db,
    `
      INSERT INTO user_download_counters (
        user_id,
        user_email,
        plan_code,
        lifetime_bytes,
        hour_bucket_start_unix,
        hour_bytes,
        day_bucket_start_unix,
        day_bytes,
        week_bucket_start_unix,
        week_bytes,
        month_bucket_start,
        month_bytes,
        last_notified_lifetime_mark,
        last_notified_hour_mark,
        last_notified_day_mark,
        last_notified_week_mark,
        last_notified_month_mark,
        throttled_until,
        throttle_reason,
        last_request_at,
        last_ip,
        last_device_id,
        last_country,
        created_at,
        updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(user_id) DO UPDATE SET
        user_email = excluded.user_email,
        plan_code = excluded.plan_code,
        lifetime_bytes = excluded.lifetime_bytes,
        hour_bucket_start_unix = excluded.hour_bucket_start_unix,
        hour_bytes = excluded.hour_bytes,
        day_bucket_start_unix = excluded.day_bucket_start_unix,
        day_bytes = excluded.day_bytes,
        week_bucket_start_unix = excluded.week_bucket_start_unix,
        week_bytes = excluded.week_bytes,
        month_bucket_start = excluded.month_bucket_start,
        month_bytes = excluded.month_bytes,
        throttled_until = excluded.throttled_until,
        throttle_reason = excluded.throttle_reason,
        last_request_at = excluded.last_request_at,
        last_ip = excluded.last_ip,
        last_device_id = excluded.last_device_id,
        last_country = excluded.last_country,
        updated_at = excluded.updated_at
    `,
    [
      userId,
      userEmail,
      safePlanCode,
      lifetimeBytes,
      hourBucket,
      hourBytes,
      dayBucket,
      dayBytes,
      weekBucket,
      weekBytes,
      monthBucket,
      monthBytes,
      clampNonNegativeInt(existing && existing.last_notified_lifetime_mark),
      clampNonNegativeInt(existing && existing.last_notified_hour_mark),
      clampNonNegativeInt(existing && existing.last_notified_day_mark),
      clampNonNegativeInt(existing && existing.last_notified_week_mark),
      clampNonNegativeInt(existing && existing.last_notified_month_mark),
      throttledUntil || null,
      throttleShouldActivate ? "high_daily_download_24h" : String(existing && existing.throttle_reason || ""),
      now,
      ip || null,
      deviceId || null,
      country || null,
      String(existing && existing.created_at || now),
      now,
    ],
  );

  const markStepBytes = Math.max(
    1,
    toBytesFromGb(parsePositiveNumber(env.DOWNLOAD_MARK_STEP_GB, DEFAULT_DOWNLOAD_MARK_STEP_GB)),
  );
  const marksNow = {
    lifetime: Math.floor(lifetimeBytes / markStepBytes),
    hour: Math.floor(hourBytes / markStepBytes),
    day: Math.floor(dayBytes / markStepBytes),
    week: Math.floor(weekBytes / markStepBytes),
    month: Math.floor(monthBytes / markStepBytes),
  };
  const marksPrev = {
    lifetime: clampNonNegativeInt(existing && existing.last_notified_lifetime_mark),
    hour: clampNonNegativeInt(existing && existing.last_notified_hour_mark),
    day: clampNonNegativeInt(existing && existing.last_notified_day_mark),
    week: clampNonNegativeInt(existing && existing.last_notified_week_mark),
    month: clampNonNegativeInt(existing && existing.last_notified_month_mark),
  };
  const crossed = {
    lifetime: marksNow.lifetime > marksPrev.lifetime,
    hour: marksNow.hour > marksPrev.hour,
    day: marksNow.day > marksPrev.day,
    week: marksNow.week > marksPrev.week,
    month: marksNow.month > marksPrev.month,
  };
  const crossedAny = Object.values(crossed).some((value) => Boolean(value));

  if (crossedAny && !whitelisted) {
    const opsCooldownSeconds = Math.max(
      30,
      parseRateLimitInteger(
        env.DOWNLOAD_ALERT_EMAIL_COOLDOWN_SECONDS,
        DEFAULT_DOWNLOAD_ALERT_EMAIL_COOLDOWN_SECONDS,
      ),
    );
    const markGate = await consumeRateLimitWindow(
      db,
      "download_mark_ops_mail",
      userId,
      1,
      opsCooldownSeconds,
    );
    if (markGate.allowed) {
      try {
        await sendOpsAlertEmail(
          env,
          "Planetka high-volume download milestone reached",
          [
            "User crossed download milestone marks.",
            `email=${userEmail}`,
            `plan=${safePlanCode}`,
            `lifetime_gb=${(lifetimeBytes / BYTES_PER_GB).toFixed(2)}`,
            `month_gb=${(monthBytes / BYTES_PER_GB).toFixed(2)}`,
            `week_gb=${(weekBytes / BYTES_PER_GB).toFixed(2)}`,
            `day_gb=${(dayBytes / BYTES_PER_GB).toFixed(2)}`,
            `hour_gb=${(hourBytes / BYTES_PER_GB).toFixed(2)}`,
            `marks_crossed=${JSON.stringify(crossed)}`,
            `ip=${ip}`,
            `device_id=${deviceId}`,
          ],
        );
        await dbRun(
          db,
          `
            UPDATE user_download_counters
            SET
              last_notified_lifetime_mark = ?,
              last_notified_hour_mark = ?,
              last_notified_day_mark = ?,
              last_notified_week_mark = ?,
              last_notified_month_mark = ?,
              updated_at = ?
            WHERE user_id = ?
          `,
          [marksNow.lifetime, marksNow.hour, marksNow.day, marksNow.week, marksNow.month, nowIso(), userId],
        );
      } catch (error) {
        console.warn(
          "worker.download_milestone_alert_email_failed",
          JSON.stringify({
            user_id: userId,
            email: userEmail,
            error: String(error && error.message || "download_milestone_alert_email_failed"),
          }),
        );
      }
    }
  }

  if (throttleShouldActivate && !whitelisted) {
    const opsCooldownSeconds = Math.max(
      30,
      parseRateLimitInteger(
        env.DOWNLOAD_ALERT_EMAIL_COOLDOWN_SECONDS,
        DEFAULT_DOWNLOAD_ALERT_EMAIL_COOLDOWN_SECONDS,
      ),
    );
    const throttleOpsGate = await consumeRateLimitWindow(
      db,
      "download_throttle_ops_mail",
      userId,
      1,
      opsCooldownSeconds,
    );
    if (throttleOpsGate.allowed) {
      try {
        await sendOpsAlertEmail(
          env,
          "Planetka user automatically throttled",
          [
            "User exceeded rolling 24-hour download threshold and was throttled.",
            `email=${userEmail}`,
            `plan=${safePlanCode}`,
            `rolling_24h_gb=${(rolling24hBytes / BYTES_PER_GB).toFixed(2)}`,
            `threshold_gb=${(thresholdBytes / BYTES_PER_GB).toFixed(2)}`,
            `throttled_until=${throttledUntil}`,
            `ip=${ip}`,
            `device_id=${deviceId}`,
          ],
        );
      } catch (error) {
        console.warn(
          "worker.download_throttle_ops_email_failed",
          JSON.stringify({
            user_id: userId,
            email: userEmail,
            error: String(error && error.message || "download_throttle_ops_email_failed"),
          }),
        );
      }
    }

    const throttleUserGate = await consumeRateLimitWindow(
      db,
      "download_throttle_user_mail",
      userId,
      1,
      opsCooldownSeconds,
    );
    if (throttleUserGate.allowed) {
      try {
        await sendUserThrottledEmail(env, userEmail, {
          recentWindowGb: rolling24hBytes / BYTES_PER_GB,
          thresholdGb: thresholdBytes / BYTES_PER_GB,
          windowLabel: "24h",
          throttledUntil,
        });
      } catch (error) {
        console.warn(
          "worker.download_throttle_user_email_failed",
          JSON.stringify({
            user_id: userId,
            email: userEmail,
            error: String(error && error.message || "download_throttle_user_email_failed"),
          }),
        );
      }
    }
  }
}

async function enforceDownloadThrottleGate(db, env, user, requestDeviceId = "", requestIp = "") {
  if (!db || !user || !user.id) {
    return null;
  }
  const userEmail = normalizeEmail(user.email || "");
  if (isDownloadAlertWhitelisted(userEmail, env)) {
    return null;
  }
  const counter = await findUserDownloadCounter(db, String(user.id || "").trim());
  if (!counter) {
    return null;
  }
  const throttledUntil = String(counter.throttled_until || "").trim();
  const throttledUntilMs = Date.parse(throttledUntil);
  if (!Number.isFinite(throttledUntilMs) || throttledUntilMs <= Date.now()) {
    return null;
  }
  const perMinuteLimit = parseRateLimitInteger(
    env.DOWNLOAD_THROTTLED_REQUESTS_PER_MINUTE,
    DEFAULT_DOWNLOAD_THROTTLED_REQUESTS_PER_MINUTE,
  );
  if (perMinuteLimit <= 0) {
    return {
      isThrottled: true,
      blocked: false,
      retryAfterSeconds: 0,
      throttledUntil,
      userEmail,
      requestDeviceId: normalizeDeviceId(requestDeviceId),
      requestIp: String(requestIp || "").trim(),
    };
  }
  const rate = await consumeRateLimitWindow(
    db,
    "download_throttled_req_minute",
    String(user.id || "").trim(),
    perMinuteLimit,
    60,
  );
  if (rate.allowed) {
    return {
      isThrottled: true,
      blocked: false,
      retryAfterSeconds: 0,
      throttledUntil,
      userEmail,
      requestDeviceId: normalizeDeviceId(requestDeviceId),
      requestIp: String(requestIp || "").trim(),
    };
  }
  return {
    isThrottled: true,
    blocked: true,
    code: "download_throttled",
    retryAfterSeconds: clampNonNegativeInt(rate.retryAfterSeconds) || 1,
    message: "High-volume data use detected. Download speed is temporarily throttled. Contact Planetka support if needed.",
    throttledUntil,
    userEmail,
    requestDeviceId: normalizeDeviceId(requestDeviceId),
    requestIp: String(requestIp || "").trim(),
  };
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
    magic_links_deleted: 0,
    refresh_sessions_deleted: 0,
    device_sessions_deleted: 0,
    api_key_requests_deleted: 0,
    api_key_device_activity_deleted: 0,
    provisional_claim_audit_deleted: 0,
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
  const paidClaimRetentionCutoff = addDaysFromIso(
    nowTimestamp,
    -Math.max(30, parseNonNegativeInteger(env.PAID_CLAIM_RETENTION_DAYS, DEFAULT_PAID_CLAIM_RETENTION_DAYS)),
  );
  const tileEventsCutoffUnix = Math.max(0, nowUnix - (summary.tile_event_retention_days * 86400));
  const authRefreshEventsCutoffUnix = Math.max(
    0,
    nowUnix - (summary.auth_refresh_event_retention_days * 86400),
  );
  const tileRollupCutoffUnix = Math.max(0, nowUnix - (summary.tile_rollup_retention_days * 86400));

  if (await dbTableExists(db, "magic_links")) {
    const magicLinksResult = await dbRun(
      db,
      `
        DELETE FROM magic_links
        WHERE expires_at < ?
      `,
      [nowTimestamp],
    );
    summary.magic_links_deleted = dbMetaChanges(magicLinksResult);
  }

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

  if (await dbTableExists(db, "device_sessions")) {
    const deviceSessionsResult = await dbRun(
      db,
      `
        DELETE FROM device_sessions
        WHERE expires_at < ?
      `,
      [nowTimestamp],
    );
    summary.device_sessions_deleted = dbMetaChanges(deviceSessionsResult);
  }

  if (await dbTableExists(db, "api_key_requests")) {
    await ensureApiKeyTables(db);
    const apiKeyRequestsResult = await dbRun(
      db,
      `
        DELETE FROM api_key_requests
        WHERE
          (
            (request_type IS NULL OR request_type = '' OR request_type = ?)
            AND (
              expires_at < ?
              OR (used_at IS NOT NULL AND used_at != '' AND used_at < ?)
            )
          )
          OR (
            request_type = ?
            AND used_at IS NULL
            AND expires_at < ?
          )
          OR (
            request_type = ?
            AND review_status != ?
            AND COALESCE(reviewed_at, created_at) < ?
          )
      `,
      [
        API_KEY_REQUEST_TYPE_FREE,
        nowTimestamp,
        refreshSessionCutoff,
        API_KEY_REQUEST_TYPE_PAID_CLAIM,
        nowTimestamp,
        API_KEY_REQUEST_TYPE_PAID_CLAIM,
        CLAIM_REVIEW_PENDING,
        paidClaimRetentionCutoff,
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

  if (await dbTableExists(db, "provisional_claim_audit")) {
    const claimAuditResult = await dbRun(
      db,
      `
        DELETE FROM provisional_claim_audit
        WHERE created_at < ?
      `,
      [paidClaimRetentionCutoff],
    );
    summary.provisional_claim_audit_deleted = dbMetaChanges(claimAuditResult);
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
  const hasClaimAudit = await dbTableExists(db, "provisional_claim_audit");
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
    {
      key: "claim_rejection_burst",
      label: "Claim rejection burst",
      threshold: parseRateLimitInteger(
        env.PROD_ALERT_CLAIM_REJECTION_THRESHOLD,
        DEFAULT_ALERT_PROD_CLAIM_REJECTION_THRESHOLD,
      ),
      windowSeconds: parseRateLimitInteger(
        env.PROD_ALERT_CLAIM_REJECTION_WINDOW_SECONDS,
        DEFAULT_ALERT_PROD_CLAIM_REJECTION_WINDOW_SECONDS,
      ),
      tableAvailable: hasClaimAudit,
      countSql: `
        SELECT COUNT(*) AS count
        FROM provisional_claim_audit
        WHERE created_at >= ?
          AND event_type IN ('claim_rejected_signal', 'claim_review_rejected', 'claim_auto_fallback_to_free')
      `,
      countBindings: (windowStartUnix) => [new Date(windowStartUnix * 1000).toISOString()],
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

function resolvePlanCode(user, subscription, env = {}) {
  void subscription;
  const entitlement = resolveEntitlementState(user, env);
  if (entitlement && entitlement.plan_code === "blocked") {
    return "blocked";
  }
  return normalizeRequestedPlan(
    entitlement && entitlement.plan_code
      ? entitlement.plan_code
      : (user && user.status) || PLAN_CODE_PLANETKA,
  );
}

function commercialUseAllowed(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  return normalized === PLAN_CODE_PLANETKA_PRO;
}

function accountTierForPlanCode(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) return "pro";
  if (normalized === PLAN_CODE_PLANETKA) return "lite";
  return "free";
}

function planDisplayName(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) return "Planetka Commercial";
  if (normalized === PLAN_CODE_PLANETKA) return "Planetka Personal";
  return "Planetka Free";
}

function planAccessSummary(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) {
    return "Commercial includes unlimited global Preview, Balanced, Full Quality, and animation rendering.";
  }
  if (normalized === PLAN_CODE_PLANETKA) {
    return "Personal includes Preview and Balanced texture quality.";
  }
  return "Free includes Preview texture quality only.";
}

async function buildAccountState(db, user, subscription, env) {
  const planCode = resolvePlanCode(user, subscription, env);
  const userId = String(user && user.id || "").trim();
  const counter = userId ? await findUserDownloadCounter(db, userId) : null;
  const throttledUntilRaw = String(counter && counter.throttled_until || "").trim();
  const throttledUntilMs = Date.parse(throttledUntilRaw);
  const throttledUntil = Number.isFinite(throttledUntilMs) && throttledUntilMs > Date.now()
    ? throttledUntilRaw
    : "";
  const throttleReason = throttledUntil
    ? String(counter && counter.throttle_reason || "").trim()
    : "";

  return {
    planCode,
    commercialUseAllowed: commercialUseAllowed(planCode),
    upgradeUrl: String(env.UPGRADE_URL || DEFAULT_UPGRADE_URL).trim() || DEFAULT_UPGRADE_URL,
    contactUrl: normalizeContactUrl(env.PLANETKA_CONTACT_URL || DEFAULT_CONTACT_URL),
    throttledUntil,
    throttleReason,
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
    throttled_until: String(safeState.throttledUntil || "").trim(),
    throttle_reason: String(safeState.throttleReason || "").trim(),
    is_throttled: Boolean(safeState.throttledUntil),
  };
}

async function findUserByEmail(db, email) {
  await ensureUserProvisionalColumns(db);
  return dbGet(
    db,
    `
      SELECT
        u.id,
        u.email,
        u.status,
        u.provisional_plan_code,
        u.provisional_expires_at,
        u.pro_confirmed_at,
        u.pro_access_expires_at,
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
  await ensureUserProvisionalColumns(db);
  return dbGet(
    db,
    `
      SELECT
        u.id,
        u.email,
        u.status,
        u.provisional_plan_code,
        u.provisional_expires_at,
        u.pro_confirmed_at,
        u.pro_access_expires_at,
        u.created_at,
        u.last_login_at
      FROM users u
      WHERE u.id = ?
      LIMIT 1
    `,
    [userId],
  );
}

async function ensureDeviceSessionsTable(db) {
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS device_sessions (
        id TEXT PRIMARY KEY,
        device_code TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'pending',
        email TEXT,
        access_token TEXT,
        refresh_token TEXT,
        subscription_status TEXT,
        renews_at TEXT,
        trial_ends_at TEXT,
        expires_at TEXT NOT NULL,
        completed_at TEXT,
        claimed_at TEXT,
        created_at TEXT NOT NULL
      )
    `,
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

async function ensureMagicLinksTokenIndex(db) {
  if (magicLinksTokenIndexReady) {
    return;
  }
  await dbRun(
    db,
    `CREATE UNIQUE INDEX IF NOT EXISTS idx_magic_links_token_hash ON magic_links(token_hash)`,
  );
  magicLinksTokenIndexReady = true;
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

async function ensureUserProvisionalColumns(db) {
  if (userProvisionalColumnsReady) {
    return;
  }
  const pragma = await db.prepare(`PRAGMA table_info(users)`).all();
  const rows = Array.isArray(pragma && pragma.results) ? pragma.results : [];
  if (!rows.length) {
    return;
  }
  const names = new Set(rows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  const statements = [];
  if (!names.has("provisional_plan_code")) {
    statements.push(`ALTER TABLE users ADD COLUMN provisional_plan_code TEXT`);
  }
  if (!names.has("provisional_expires_at")) {
    statements.push(`ALTER TABLE users ADD COLUMN provisional_expires_at TEXT`);
  }
  if (!names.has("pro_confirmed_at")) {
    statements.push(`ALTER TABLE users ADD COLUMN pro_confirmed_at TEXT`);
  }
  if (!names.has("pro_access_expires_at")) {
    statements.push(`ALTER TABLE users ADD COLUMN pro_access_expires_at TEXT`);
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
  userProvisionalColumnsReady = true;
}

async function ensureApiKeyTables(db) {
  if (apiKeyTablesReady) {
    return;
  }
  await ensureUserProvisionalColumns(db);
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS api_key_requests (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        requested_plan TEXT NOT NULL DEFAULT 'planetka',
        request_type TEXT NOT NULL DEFAULT 'free',
        claimed_plan_code TEXT,
        order_id TEXT,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        review_status TEXT NOT NULL DEFAULT 'pending',
        reviewed_at TEXT,
        reviewed_by TEXT,
        review_note TEXT,
        cooldown_until TEXT,
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
  if (!apiKeyRequestNames.has("request_type")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN request_type TEXT NOT NULL DEFAULT 'free'`);
  }
  if (!apiKeyRequestNames.has("claimed_plan_code")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN claimed_plan_code TEXT`);
  }
  if (!apiKeyRequestNames.has("order_id")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN order_id TEXT`);
  }
  if (!apiKeyRequestNames.has("request_ip")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN request_ip TEXT`);
  }
  if (!apiKeyRequestNames.has("review_status")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'`);
  }
  if (!apiKeyRequestNames.has("reviewed_at")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN reviewed_at TEXT`);
  }
  if (!apiKeyRequestNames.has("reviewed_by")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN reviewed_by TEXT`);
  }
  if (!apiKeyRequestNames.has("review_note")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN review_note TEXT`);
  }
  if (!apiKeyRequestNames.has("cooldown_until")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN cooldown_until TEXT`);
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
          NULLIF(reviewed_at, ''),
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
    `CREATE INDEX IF NOT EXISTS idx_api_key_requests_claim_state ON api_key_requests(email, request_type, review_status, created_at DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_api_key_requests_claim_cooldown ON api_key_requests(email, request_type, cooldown_until DESC)`,
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
        provisional INTEGER NOT NULL DEFAULT 0,
        provisional_expires_at TEXT,
        confirmed_at TEXT,
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
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS provisional_claim_audit (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        event_type TEXT NOT NULL,
        email TEXT,
        user_id TEXT,
        claim_id TEXT,
        order_id TEXT,
        plan_code TEXT,
        ip TEXT,
        device_id TEXT,
        details_json TEXT
      )
    `,
  );
  const claimAuditPragma = await db.prepare(`PRAGMA table_info(provisional_claim_audit)`).all();
  const claimAuditRows = Array.isArray(claimAuditPragma && claimAuditPragma.results)
    ? claimAuditPragma.results
    : [];
  const claimAuditNames = new Set(
    claimAuditRows.map((row) => String(row && row.name || "").trim().toLowerCase()),
  );
  const claimAuditStatements = [];
  if (!claimAuditNames.has("created_at")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN created_at TEXT`);
  }
  if (!claimAuditNames.has("event_type")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN event_type TEXT`);
  }
  if (!claimAuditNames.has("email")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN email TEXT`);
  }
  if (!claimAuditNames.has("user_id")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN user_id TEXT`);
  }
  if (!claimAuditNames.has("claim_id")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN claim_id TEXT`);
  }
  if (!claimAuditNames.has("order_id")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN order_id TEXT`);
  }
  if (!claimAuditNames.has("plan_code")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN plan_code TEXT`);
  }
  if (!claimAuditNames.has("ip")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN ip TEXT`);
  }
  if (!claimAuditNames.has("device_id")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN device_id TEXT`);
  }
  if (!claimAuditNames.has("details_json")) {
    claimAuditStatements.push(`ALTER TABLE provisional_claim_audit ADD COLUMN details_json TEXT`);
  }
  for (const statement of claimAuditStatements) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  if (!claimAuditNames.has("created_at")) {
    await dbRun(
      db,
      `
        UPDATE provisional_claim_audit
        SET created_at = COALESCE(NULLIF(created_at, ''), ?)
        WHERE created_at IS NULL OR created_at = ''
      `,
      [nowIso()],
    );
  }
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_provisional_claim_audit_created ON provisional_claim_audit(created_at DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_provisional_claim_audit_email_created ON provisional_claim_audit(email, created_at DESC)`,
  );
  apiKeyTablesReady = true;
}

async function appendProvisionalClaimAudit(db, eventType, payload = {}) {
  if (!db || !eventType) {
    return;
  }
  await ensureApiKeyTables(db);
  const detailsJson = (() => {
    try {
      return JSON.stringify(payload && payload.details ? payload.details : {});
    } catch (_error) {
      return "{}";
    }
  })();
  await dbRun(
    db,
    `
      INSERT INTO provisional_claim_audit (
        id,
        created_at,
        event_type,
        email,
        user_id,
        claim_id,
        order_id,
        plan_code,
        ip,
        device_id,
        details_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      crypto.randomUUID(),
      nowIso(),
      String(eventType || "").trim().slice(0, 96),
      normalizeEmail(payload.email || "") || null,
      String(payload.userId || "").trim() || null,
      String(payload.claimId || "").trim() || null,
      normalizeOrderId(payload.orderId || "") || null,
      normalizeRequestedPlan(payload.planCode || PLAN_CODE_PLANETKA),
      String(payload.ip || "").trim() || null,
      normalizeDeviceId(payload.deviceId || "") || null,
      detailsJson,
    ],
  );
}

async function findLatestPaidClaimByEmail(db, email) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return null;
  }
  return dbGet(
    db,
    `
      SELECT
        id,
        email,
        requested_plan,
        claimed_plan_code,
        request_type,
        order_id,
        review_status,
        reviewed_at,
        reviewed_by,
        review_note,
        cooldown_until,
        used_at,
        request_ip,
        request_device_id,
        created_at
      FROM api_key_requests
      WHERE email = ?
        AND request_type = ?
      ORDER BY created_at DESC
      LIMIT 1
    `,
    [normalizedEmail, API_KEY_REQUEST_TYPE_PAID_CLAIM],
  );
}

async function markPaidClaimReviewed(db, claimId, reviewStatus, options = {}) {
  const normalizedClaimId = String(claimId || "").trim();
  if (!normalizedClaimId) {
    return;
  }
  const safeStatus = normalizeClaimReviewStatus(reviewStatus) || CLAIM_REVIEW_REJECTED;
  const reviewedAt = String(options.reviewedAt || nowIso()).trim();
  const reviewedBy = String(options.reviewedBy || "").trim();
  const reviewNote = String(options.reviewNote || "").trim();
  const cooldownUntil = String(options.cooldownUntil || "").trim();
  const clearCooldown = parseBooleanFlag(options.clearCooldown);
  await dbRun(
    db,
    `
      UPDATE api_key_requests
      SET
        review_status = ?,
        reviewed_at = ?,
        reviewed_by = CASE WHEN ? != '' THEN ? ELSE reviewed_by END,
        review_note = CASE WHEN ? != '' THEN ? ELSE review_note END,
        cooldown_until = CASE
          WHEN ? = 1 THEN NULL
          WHEN ? != '' THEN ?
          ELSE cooldown_until
        END
      WHERE id = ?
    `,
    [
      safeStatus,
      reviewedAt,
      reviewedBy,
      reviewedBy,
      reviewNote,
      reviewNote,
      clearCooldown ? 1 : 0,
      cooldownUntil,
      cooldownUntil,
      normalizedClaimId,
    ],
  );
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
  await ensureUserProvisionalColumns(db);
  const requestedStatus = normalizePlanCode(status) || PLAN_CODE_PLANETKA_FREE;
  const provisionalPlanCode = normalizeRequestedPlan(options.provisionalPlanCode || "");
  const provisionalExpiresAt = String(options.provisionalExpiresAt || "").trim();
  const proConfirmedAt = String(options.proConfirmedAt || "").trim();
  const proAccessExpiresAt = String(options.proAccessExpiresAt || "").trim();
  const requestedPaidStatus = requestedStatus === PLAN_CODE_PLANETKA_PRO;
  const hasServerEntitlementSignal = Boolean(
    proConfirmedAt
    || proAccessExpiresAt
    || (isPaidRequestedPlan(provisionalPlanCode) && provisionalExpiresAt)
    || isPermanentProEmail(normalizedEmail, env),
  );
  const forceProByBeta = isBetaForceProTierEnabled(env);
  const gatedRequestedStatus = (requestedPaidStatus && !hasServerEntitlementSignal)
    ? PLAN_CODE_PLANETKA_FREE
    : requestedStatus;
  const forceProByEmail = isPermanentProEmail(normalizedEmail, env);
  const finalRequestedStatus = forceProByBeta
    ? PLAN_CODE_PLANETKA_PRO
    : (forceProByEmail ? PLAN_CODE_PLANETKA_PRO : gatedRequestedStatus);
  let user = await findUserByEmail(db, normalizedEmail);
  if (user) {
    const currentStatus = String(user.status || "").trim().toLowerCase();
    const nextStatus = String(finalRequestedStatus || "").trim().toLowerCase() || PLAN_CODE_PLANETKA_FREE;
    const currentEntitlement = resolveEntitlementState(user, env);
    // Keep currently entitled paid status when this helper is called with free status by non-entitlement flows.
    const protectedStatus = (
      Boolean(currentEntitlement && currentEntitlement.commercial_use_allowed)
      && currentStatus === PLAN_CODE_PLANETKA_PRO
      && (
        nextStatus === PLAN_CODE_PLANETKA_FREE
        || nextStatus === PLAN_CODE_PLANETKA
      )
    )
      ? currentStatus
      : nextStatus;
    await dbRun(
      db,
      `
        UPDATE users
        SET
          status = ?,
          provisional_plan_code = CASE WHEN ? != '' THEN ? ELSE provisional_plan_code END,
          provisional_expires_at = CASE WHEN ? != '' THEN ? ELSE provisional_expires_at END,
          pro_confirmed_at = CASE WHEN ? != '' THEN ? ELSE pro_confirmed_at END,
          pro_access_expires_at = CASE WHEN ? != '' THEN ? ELSE pro_access_expires_at END
        WHERE id = ?
      `,
      [
        protectedStatus,
        provisionalPlanCode,
        provisionalPlanCode,
        provisionalExpiresAt,
        provisionalExpiresAt,
        proConfirmedAt,
        proConfirmedAt,
        proAccessExpiresAt,
        proAccessExpiresAt,
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
        privacy_version,
        provisional_plan_code,
        provisional_expires_at,
        pro_confirmed_at,
        pro_access_expires_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      id,
      normalizedEmail,
      finalRequestedStatus,
      createdAt,
      termsAcceptedAt,
      privacyAcceptedAt,
      termsVersion,
      privacyVersion,
      provisionalPlanCode || null,
      provisionalExpiresAt || null,
      proConfirmedAt || null,
      proAccessExpiresAt || null,
    ],
  );
  if (!parseBooleanFlag(options.suppressNewUserAlert)) {
    try {
      await sendNewUserLoginAlert(env, {
        email: normalizedEmail,
        source: String(options.signupSource || options.source || "unknown").trim() || "unknown",
        planCode: finalRequestedStatus,
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

async function applyExpiredProvisionalFallback(db, user, env = {}) {
  if (!user || !user.id || !isUnconfirmedProvisionalExpired(user)) {
    return;
  }
  const now = nowIso();
  const cooldownUntil = computePendingClaimCooldownIso(env);
  const latestClaim = await findLatestPaidClaimByEmail(db, user.email);
  if (latestClaim && String(latestClaim.review_status || "").trim().toLowerCase() === CLAIM_REVIEW_PENDING) {
    await markPaidClaimReviewed(
      db,
      latestClaim.id,
      CLAIM_REVIEW_REJECTED,
      {
        reviewedAt: now,
        reviewedBy: "system_timeout",
        reviewNote: "auto_fallback_to_free_after_provisional_expiry",
        cooldownUntil,
      },
    );
    await appendProvisionalClaimAudit(
      db,
      "claim_auto_fallback_to_free",
      {
        email: user.email,
        userId: user.id,
        claimId: String(latestClaim.id || "").trim(),
        orderId: String(latestClaim.order_id || "").trim(),
        planCode: latestClaim.claimed_plan_code || latestClaim.requested_plan || PLAN_CODE_PLANETKA,
        ip: String(latestClaim.request_ip || "").trim(),
        deviceId: String(latestClaim.request_device_id || "").trim(),
        details: {
          cooldown_until: cooldownUntil,
        },
      },
    );
    await signalRejectedClaimAttempt(
      db,
      env,
      {
        email: user.email,
        ip: String(latestClaim.request_ip || "").trim(),
        deviceId: String(latestClaim.request_device_id || "").trim(),
        orderId: String(latestClaim.order_id || "").trim(),
        requestedPlan: latestClaim.claimed_plan_code || latestClaim.requested_plan || PLAN_CODE_PLANETKA,
        claimId: String(latestClaim.id || "").trim(),
        reason: "claim_expired_no_manual_decision",
      },
    );
    try {
      await sendOpsAlertEmail(
        env,
        "Planetka provisional paid access auto-fallback",
        [
          "Provisional paid access expired without manual confirmation.",
          `email=${normalizeEmail(user.email || "")}`,
          `claim_id=${String(latestClaim.id || "").trim()}`,
          `order_id=${normalizeOrderId(latestClaim.order_id || "")}`,
          `requested_plan=${normalizeRequestedPlan(latestClaim.claimed_plan_code || latestClaim.requested_plan || PLAN_CODE_PLANETKA)}`,
          `request_ip=${String(latestClaim.request_ip || "").trim()}`,
          `request_device_id=${normalizeDeviceId(latestClaim.request_device_id || "")}`,
          `cooldown_until=${cooldownUntil}`,
        ],
      );
    } catch (error) {
      console.warn(
        "worker.claim_auto_fallback_alert_email_failed",
        JSON.stringify({
          email: normalizeEmail(user.email || ""),
          error: String(error && error.message || "claim_auto_fallback_alert_email_failed"),
        }),
      );
    }
  }
  await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        provisional = 0,
        provisional_expires_at = NULL,
        plan_code = ?,
        confirmed_at = NULL
      WHERE user_id = ?
        AND status = 'active'
        AND provisional = 1
    `,
    [PLAN_CODE_PLANETKA, user.id],
  );
}

async function enforceUserPlanPolicy(db, user, subscription = null, env = {}) {
  if (!user || !user.id || isBlockedStatus(user.status)) {
    return user;
  }
  if (isUnconfirmedProvisionalExpired(user)) {
    await applyExpiredProvisionalFallback(db, user, env);
    user = await findUserById(db, user.id);
    if (!user) {
      return null;
    }
  }
  if (String(user.pro_confirmed_at || "").trim()) {
    const latestClaim = await findLatestPaidClaimByEmail(db, user.email);
    if (latestClaim && String(latestClaim.review_status || "").trim().toLowerCase() === CLAIM_REVIEW_PENDING) {
      await markPaidClaimReviewed(
        db,
        latestClaim.id,
        CLAIM_REVIEW_APPROVED,
        {
          reviewedBy: "system_confirmed",
          reviewNote: "user_confirmed_paid_claim",
          clearCooldown: true,
        },
      );
      await appendProvisionalClaimAudit(
        db,
        "claim_marked_approved_after_confirmation",
        {
          email: user.email,
          userId: user.id,
          claimId: String(latestClaim.id || "").trim(),
          orderId: String(latestClaim.order_id || "").trim(),
          planCode: latestClaim.claimed_plan_code || latestClaim.requested_plan || PLAN_CODE_PLANETKA,
          ip: String(latestClaim.request_ip || "").trim(),
          deviceId: String(latestClaim.request_device_id || "").trim(),
        },
      );
    }
  }
  const targetPlan = resolvePolicyPlanCode(user, subscription, env);
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
  if (
    targetPlan === PLAN_CODE_PLANETKA_FREE
    || targetPlan === PLAN_CODE_PLANETKA
  ) {
    await dbRun(
      db,
      `
        UPDATE users
        SET
          status = ?,
          provisional_plan_code = NULL,
          provisional_expires_at = NULL
        WHERE id = ?
      `,
      [targetPlan, user.id],
    );
    await dbRun(
      db,
      `
        UPDATE api_keys
        SET
          plan_code = ?,
          expires_at = NULL,
          provisional = 0,
          provisional_expires_at = NULL,
          confirmed_at = NULL
        WHERE user_id = ?
          AND status = 'active'
      `,
      [targetPlan, user.id],
    );
    return {
      ...user,
      status: targetPlan,
      provisional_plan_code: "",
      provisional_expires_at: "",
    };
  }
  await dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetPlan, user.id]);
  await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        expires_at = NULL,
        provisional = 0,
        provisional_expires_at = NULL,
        confirmed_at = CASE WHEN ? != '' THEN ? ELSE confirmed_at END
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetPlan, String(user && user.pro_confirmed_at || "").trim(), String(user && user.pro_confirmed_at || "").trim(), user.id],
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

async function sendMagicLinkEmail(env, email, token, magicUrlOverride = "") {
  const apiKey = requireSecret(env, "EMAIL_API_KEY");
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const loginUrl = String(env.LOGIN_URL || "https://www.planetka.io/login").trim();
  const magicUrl = String(magicUrlOverride || `${loginUrl}?token=${encodeURIComponent(token)}`).trim();

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [email],
      subject: "Your Planetka login link",
      text: [
        "Use this secure Planetka login link:",
        magicUrl,
        "",
        "This link expires in 15 minutes and can only be used once.",
      ].join("\n"),
      html: `
        <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
          <h2 style="margin-bottom: 16px;">Log in to Planetka</h2>
          <p>Use the button below to log in to Planetka for Blender.</p>
          <p style="margin: 24px 0;">
            <a href="${magicUrl}" style="background:#111827;color:#ffffff;padding:12px 18px;text-decoration:none;border-radius:8px;display:inline-block;">
              Log In to Planetka
            </a>
          </p>
          <p>If the button does not work, open this link:</p>
          <p><a href="${magicUrl}">${magicUrl}</a></p>
          <p>This link expires in 15 minutes and can only be used once.</p>
        </div>
      `,
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`resend_error_${response.status}_${body}`);
  }
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
  const provisional = parseBooleanFlag(options.provisional) ? 1 : 0;
  const provisionalExpiresAt = String(options.provisionalExpiresAt || "").trim();
  const confirmedAt = String(options.confirmedAt || "").trim();
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
        provisional,
        provisional_expires_at,
        confirmed_at,
        issued_at
      ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
    `,
    [
      keyId,
      user.id,
      keyHash,
      keyPrefix,
      safePlan,
      expiresAt || null,
      provisional,
      provisionalExpiresAt || null,
      confirmedAt || null,
      issuedAt,
    ],
  );
  if (safePlan === PLAN_CODE_PLANETKA) {
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
        ak.provisional AS api_key_provisional,
        ak.provisional_expires_at AS api_key_provisional_expires_at,
        ak.confirmed_at AS api_key_confirmed_at,
        ak.key_prefix,
        u.id,
        u.email,
        u.status,
        u.provisional_plan_code,
        u.provisional_expires_at,
        u.pro_confirmed_at,
        u.pro_access_expires_at
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
      provisionalRestricted: false,
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
    provisionalRestricted: false,
  };
}

async function createAccessToken(env, user, subscription, extraClaims = {}) {
  void subscription;
  const secret = requireSecret(env, "JWT_SIGNING_SECRET");
  const exp = Math.floor(Date.now() / 1000) + (60 * 60);
  const entitlement = resolveEntitlementState(user, env);
  const effectivePlanCode = normalizeRequestedPlan(
    resolvePolicyPlanCode(user, subscription, env),
  ) || PLAN_CODE_PLANETKA_FREE;
  const hostedStreamingAccessStatus = String(entitlement.subscription_status || "inactive");
  const basePayload = {
    type: "access",
    sub: user.id,
    email: user.email,
    plan_code: effectivePlanCode,
    user_status: effectivePlanCode,
    subscription_status: hostedStreamingAccessStatus,
    hosted_streaming_access_status: hostedStreamingAccessStatus,
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

function stripeSignatureHeaderParts(header) {
  const parts = String(header || "").split(",");
  const values = {};
  for (const part of parts) {
    const [key, value] = part.split("=", 2);
    if (key && value) {
      const normalizedKey = key.trim();
      const normalizedValue = value.trim();
      if (!values[normalizedKey]) {
        values[normalizedKey] = [];
      }
      values[normalizedKey].push(normalizedValue);
    }
  }
  return values;
}

async function verifyStripeWebhook(request, env, rawBody) {
  const secret = requireSecret(env, "STRIPE_WEBHOOK_SECRET");
  const signatureHeader = request.headers.get("Stripe-Signature");
  if (!signatureHeader) {
    throw new Error("missing_stripe_signature");
  }

  const parts = stripeSignatureHeaderParts(signatureHeader);
  const timestamp = String((parts.t && parts.t[0]) || "");
  const expectedSignatures = Array.isArray(parts.v1)
    ? parts.v1.filter((value) => String(value || "").trim())
    : [];
  if (!timestamp || expectedSignatures.length === 0) {
    throw new Error("invalid_stripe_signature_header");
  }
  const parsedTimestamp = Number.parseInt(timestamp, 10);
  if (!Number.isFinite(parsedTimestamp)) {
    throw new Error("invalid_stripe_signature_header");
  }
  const toleranceSeconds = Math.max(
    1,
    Math.floor(parsePositiveNumber(env.STRIPE_WEBHOOK_TOLERANCE_SECONDS, 300)),
  );
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSeconds - parsedTimestamp) > toleranceSeconds) {
    throw new Error("stripe_signature_tolerance_exceeded");
  }

  const signedPayload = `${timestamp}.${rawBody}`;
  const computed = await hmacSha256Hex(secret, signedPayload);
  if (!expectedSignatures.includes(computed)) {
    throw new Error("invalid_stripe_signature");
  }

  return JSON.parse(rawBody);
}

async function claimStripeWebhookEvent(db, event) {
  const eventId = String(event && event.id || "").trim();
  if (!eventId) {
    return { inserted: false, eventId: "" };
  }
  const eventType = String(event && event.type || "").trim() || "unknown";
  const stripeCreatedRaw = Number(event && event.created);
  const stripeCreated = Number.isFinite(stripeCreatedRaw)
    ? Math.floor(stripeCreatedRaw)
    : null;
  const result = await dbRun(
    db,
    `
      INSERT INTO stripe_webhook_events (
        id,
        event_id,
        event_type,
        stripe_created,
        received_at
      ) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(event_id) DO NOTHING
    `,
    [crypto.randomUUID(), eventId, eventType, stripeCreated, nowIso()],
  );
  const inserted = Number(result && result.meta && result.meta.changes) > 0;
  return { inserted, eventId, eventType };
}

function parseStripePlanMap(value) {
  const map = new Map();
  const source = String(value || "").trim();
  if (!source) {
    return map;
  }
  for (const token of source.split(",")) {
    const pair = String(token || "").trim();
    if (!pair) {
      continue;
    }
    const [idRaw, planRaw] = pair.split(":", 2);
    const id = String(idRaw || "").trim();
    const planCode = normalizeRequestedPlan(String(planRaw || "").trim());
    if (!id || !planCode) {
      continue;
    }
    map.set(id, planCode);
  }
  return map;
}

function collectStripeLineItemEntitlements(lineItems) {
  const priceIds = new Set();
  const productIds = new Set();
  for (const item of Array.isArray(lineItems) ? lineItems : []) {
    const price = item && typeof item === "object" ? item.price : null;
    if (!price || typeof price !== "object") {
      continue;
    }
    const priceId = String(price.id || "").trim();
    if (priceId) {
      priceIds.add(priceId);
    }
    const productId = String(price.product || "").trim();
    if (productId) {
      productIds.add(productId);
    }
  }
  return {
    priceIds: Array.from(priceIds),
    productIds: Array.from(productIds),
  };
}

function collectStripeLineItemsWithQuantity(lineItems) {
  const rows = [];
  for (const item of Array.isArray(lineItems) ? lineItems : []) {
    const price = item && typeof item === "object" ? item.price : null;
    if (!price || typeof price !== "object") {
      continue;
    }
    const priceId = String(price.id || "").trim();
    const productId = String(price.product || "").trim();
    const quantityRaw = Number(item && item.quantity);
    const quantity = Number.isFinite(quantityRaw) && quantityRaw > 0 ? Math.floor(quantityRaw) : 1;
    rows.push({
      priceId,
      productId,
      quantity,
    });
  }
  return rows;
}

function resolvePlanPriority(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) {
    return 2;
  }
  if (normalized === PLAN_CODE_PLANETKA) {
    return 1;
  }
  return 0;
}

function evaluateStripePlanPurchaseGuard(existingPlanCode, requestedPlanCode) {
  const existing = normalizeRequestedPlan(existingPlanCode);
  const requested = normalizeRequestedPlan(requestedPlanCode);
  const existingPriority = resolvePlanPriority(existing);
  const requestedPriority = resolvePlanPriority(requested);
  if (existingPriority <= 0 || requestedPriority <= 0) {
    return {
      blocked: false,
      reason: "",
      existingPlanCode: existing,
      requestedPlanCode: requested,
    };
  }
  if (existingPriority < requestedPriority) {
    return {
      blocked: false,
      reason: "",
      existingPlanCode: existing,
      requestedPlanCode: requested,
    };
  }
  const reason = existingPriority === requestedPriority
    ? "already_has_licence"
    : "higher_tier_already_active";
  return {
    blocked: true,
    reason,
    existingPlanCode: existing,
    requestedPlanCode: requested,
  };
}

function resolveStripePlanEntitlement(lineItems, env) {
  const byPrice = parseStripePlanMap(env.STRIPE_PLAN_PRICE_CODE_MAP);
  const byProduct = parseStripePlanMap(env.STRIPE_PLAN_PRODUCT_CODE_MAP);
  let resolvedPlan = "";
  const matched = [];
  for (const item of collectStripeLineItemsWithQuantity(lineItems)) {
    let planCode = "";
    if (item.priceId && byPrice.has(item.priceId)) {
      planCode = normalizeRequestedPlan(byPrice.get(item.priceId));
    } else if (item.productId && byProduct.has(item.productId)) {
      planCode = normalizeRequestedPlan(byProduct.get(item.productId));
    }
    if (!planCode) {
      continue;
    }
    matched.push({
      price_id: item.priceId,
      product_id: item.productId,
      quantity: item.quantity,
      plan_code: planCode,
    });
    if (resolvePlanPriority(planCode) > resolvePlanPriority(resolvedPlan)) {
      resolvedPlan = planCode;
    }
  }
  return {
    planCode: normalizeRequestedPlan(resolvedPlan || ""),
    matched,
  };
}

async function fetchStripeCheckoutSessionLineItems(env, sessionId) {
  const secretKey = requireSecret(env, "STRIPE_SECRET_KEY");
  const baseUrl = `https://api.stripe.com/v1/checkout/sessions/${encodeURIComponent(sessionId)}/line_items`;
  let nextUrl = `${baseUrl}?limit=100`;
  const lineItems = [];

  while (nextUrl) {
    const response = await fetch(nextUrl, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${secretKey}`,
      },
    });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`stripe_line_items_fetch_failed_${response.status}_${body}`);
    }
    const payload = await response.json();
    const pageItems = Array.isArray(payload && payload.data) ? payload.data : [];
    lineItems.push(...pageItems);

    if (!Boolean(payload && payload.has_more) || pageItems.length === 0) {
      break;
    }
    const lastItem = pageItems[pageItems.length - 1];
    const lastId = String(lastItem && lastItem.id || "").trim();
    if (!lastId) {
      break;
    }
    nextUrl = `${baseUrl}?limit=100&starting_after=${encodeURIComponent(lastId)}`;
  }

  return lineItems;
}

async function fetchStripeSubscription(env, subscriptionId) {
  const safeSubscriptionId = String(subscriptionId || "").trim();
  if (!safeSubscriptionId) {
    return null;
  }
  const secretKey = requireSecret(env, "STRIPE_SECRET_KEY");
  const response = await fetch(
    `https://api.stripe.com/v1/subscriptions/${encodeURIComponent(safeSubscriptionId)}`,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${secretKey}`,
      },
    },
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`stripe_subscription_fetch_failed_${response.status}_${body}`);
  }
  return response.json();
}

async function fetchStripeCustomerEmail(env, customerId) {
  const safeCustomerId = String(customerId || "").trim();
  if (!safeCustomerId) {
    return "";
  }
  const secretKey = requireSecret(env, "STRIPE_SECRET_KEY");
  const response = await fetch(
    `https://api.stripe.com/v1/customers/${encodeURIComponent(safeCustomerId)}`,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${secretKey}`,
      },
    },
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`stripe_customer_fetch_failed_${response.status}_${body}`);
  }
  const payload = await response.json();
  return normalizeEmail(payload && payload.email);
}

async function createStripeRefundForCheckoutSession(env, session, details = {}) {
  const paymentIntentId = String(session && session.payment_intent || "").trim();
  const chargeId = String(session && session.charge || "").trim();
  if (!paymentIntentId && !chargeId) {
    return {
      attempted: false,
      refunded: false,
      reason: "missing_payment_reference",
      refundId: "",
      status: "skipped",
      error: "",
    };
  }
  const secretKey = requireSecret(env, "STRIPE_SECRET_KEY");
  const body = new URLSearchParams();
  if (paymentIntentId) {
    body.set("payment_intent", paymentIntentId);
  } else {
    body.set("charge", chargeId);
  }
  body.set("reason", "requested_by_customer");
  const reason = String(details.reason || "").trim();
  const existingPlanCode = normalizeRequestedPlan(details.existingPlanCode || "");
  const requestedPlanCode = normalizeRequestedPlan(details.requestedPlanCode || "");
  if (reason) {
    body.set("metadata[planetka_reason]", reason);
  }
  if (existingPlanCode) {
    body.set("metadata[planetka_existing_plan]", existingPlanCode);
  }
  if (requestedPlanCode) {
    body.set("metadata[planetka_requested_plan]", requestedPlanCode);
  }
  const response = await fetch("https://api.stripe.com/v1/refunds", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${secretKey}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });
  if (!response.ok) {
    const bodyText = await response.text();
    return {
      attempted: true,
      refunded: false,
      reason,
      refundId: "",
      status: "failed",
      error: `stripe_refund_failed_${response.status}:${String(bodyText || "").slice(0, 500)}`,
    };
  }
  const payload = await response.json();
  return {
    attempted: true,
    refunded: Boolean(payload && payload.id),
    reason,
    refundId: String(payload && payload.id || "").trim(),
    status: String(payload && payload.status || "").trim() || "unknown",
    error: "",
  };
}

function readBearerToken(request) {
  const header = String(request.headers.get("Authorization") || "");
  if (!header.startsWith("Bearer ")) {
    return "";
  }
  const token = header.slice("Bearer ".length).trim();
  if (!token) {
    return "";
  }
  return token;
}

async function readBearerUser(request, env) {
  const token = readBearerToken(request);
  if (!token) {
    return null;
  }
  const secret = requireSecret(env, "JWT_SIGNING_SECRET");
  const payload = await verifyJwt(token, secret);
  if (payload.type !== "access" || !payload.sub) {
    throw new Error("invalid_access_token");
  }
  return payload;
}

function genericAuthStartResponse(env) {
  return json(
    {
      ok: true,
      message: "If the email is valid, a Planetka login link has been sent.",
    },
    200,
    env,
  );
}

function buildMagicLinkUrl(env, token, deviceCode = "") {
  const apiBaseUrl = String(env.API_BASE_URL || "https://api.planetka.io").trim().replace(/\/+$/, "");
  const loginUrl = String(env.LOGIN_URL || "https://www.planetka.io/login").trim();
  if (deviceCode) {
    return `${apiBaseUrl}/device/login?device_code=${encodeURIComponent(deviceCode)}&token=${encodeURIComponent(token)}`;
  }
  return `${loginUrl}?token=${encodeURIComponent(token)}`;
}

function renderApiKeyRequestPage(env, message = "", requestedPlan = PLAN_CODE_PLANETKA_FREE) {
  const termsUrl = String(env.TERMS_URL || DEFAULT_TERMS_URL).trim() || DEFAULT_TERMS_URL;
  const privacyUrl = String(env.PRIVACY_URL || DEFAULT_PRIVACY_URL).trim() || DEFAULT_PRIVACY_URL;
  const contactUrl = normalizeContactUrl(env.CONTACT_URL || DEFAULT_CONTACT_URL);
  const safeMessage = String(message || "").trim();
  const messageMarkup = safeMessage
    ? `<p id="status" style="margin-top:14px;color:#86efac;">${escapeHtml(safeMessage)}</p>`
    : `<p id="status" style="margin-top:14px;color:#cbd5e1;"></p>`;
  void requestedPlan;
  const safePlan = PLAN_CODE_PLANETKA_FREE;
  const subTitle = "Request an API key to connect Blender and start rendering with Planetka Free.";
  return html(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Free Access</title>
    <style>
      :root { color-scheme: dark; }
      body { margin:0; min-height:100vh; display:grid; place-items:center; background:linear-gradient(180deg,#07111f 0%, #0b1424 100%); font-family: Inter, system-ui, sans-serif; color:#e5edf7; }
      .card { width:min(92vw,520px); padding:28px; border-radius:18px; background:rgba(8,15,29,.82); border:1px solid rgba(148,163,184,.2); box-shadow:0 20px 60px rgba(0,0,0,.35); }
      h1 { margin:0 0 10px; font-size:30px; }
      p { margin:0 0 16px; color:#cbd5e1; line-height:1.5; }
      label { display:block; margin:0 0 8px; color:#cbd5e1; font-size:14px; }
      input[type="email"], input[type="text"] { width:100%; box-sizing:border-box; padding:14px 16px; border-radius:10px; border:1px solid rgba(148,163,184,.35); background:rgba(15,23,42,.85); color:#f8fafc; font-size:16px; margin-bottom:14px; }
      .checkbox { display:flex; gap:8px; align-items:flex-start; margin:10px 0; font-size:14px; color:#cbd5e1; }
      .checkbox input { margin-top:3px; }
      .checkbox a { color:#93c5fd; text-decoration:underline; }
      button { margin-top:14px; width:100%; border:none; border-radius:12px; padding:13px 16px; background:#1d4ed8; color:#fff; font-size:16px; font-weight:600; cursor:pointer; }
      button:disabled { opacity:.6; cursor:wait; }
      .help { margin-top:12px; font-size:13px; color:#94a3b8; }
      .help a { color:#93c5fd; }
      .hidden { display:none !important; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Request API Key</h1>
      <p>${escapeHtml(subTitle)}</p>
      <form id="form">
        <label for="email">Email</label>
        <input id="email" type="email" placeholder="you@example.com" required />
        <div class="checkbox">
          <input id="terms" type="checkbox" required />
          <label for="terms">I agree to the <a href="${termsUrl}" target="_blank" rel="noopener noreferrer">Terms and Conditions</a> and <a href="${privacyUrl}" target="_blank" rel="noopener noreferrer">Privacy Policy</a>.</label>
        </div>
        <div class="checkbox">
          <input id="news" type="checkbox" />
          <label for="news">Opt in for quarterly Planetka updates by email. Email addresses are not shared with third parties.</label>
        </div>
        <input id="website" class="hidden" type="text" autocomplete="off" tabindex="-1" />
        <button id="submit" type="submit">Request API Key</button>
      </form>
      ${messageMarkup}
      <p class="help">Problem connecting? <a href="${contactUrl}" target="_blank" rel="noopener noreferrer">Contact Me</a></p>
    </main>
    <script>
      const startedAt = Date.now();
      const form = document.getElementById("form");
      const status = document.getElementById("status");
      const submit = document.getElementById("submit");
      function errorMessageFromCode(code, fallbackMessage) {
        const normalized = String(code || "").trim().toLowerCase();
        if (normalized === "invalid_email") {
          return "Invalid email address. Please check the format (for example: name@example.com).";
        }
        if (normalized === "terms_consent_required") {
          return "Please accept Terms and Privacy to continue.";
        }
        if (normalized === "api_key_request_ip_rate_limited") {
          return "Too many requests from this network. Please try again shortly.";
        }
        if (normalized === "api_key_request_email_rate_limited") {
          return "Too many requests for this email. Please try again later.";
        }
        if (normalized === "device_limit_exceeded") {
          return String(fallbackMessage || "This account is already active on another computer.");
        }
        if (normalized === "blocked_account") {
          return String(fallbackMessage || "This account is blocked. Contact support.");
        }
        return String(fallbackMessage || "Request failed. Please try again.");
      }
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        status.style.color = "#cbd5e1";
        status.textContent = "Sending...";
        try {
          const payload = {
            email: String(document.getElementById("email").value || "").trim(),
            accept_terms: document.getElementById("terms").checked,
            accept_privacy: document.getElementById("terms").checked,
            opt_in_news: document.getElementById("news").checked,
            website: String(document.getElementById("website").value || ""),
            submitted_at_ms: Date.now() - startedAt,
            requested_plan: "${safePlan}",
          };
          const response = await fetch("/auth/api-key/request", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await response.json();
          if (!response.ok || !data.ok) {
            const errorCode = String((data && data.error) || ("http_" + response.status));
            const errorMessage = errorMessageFromCode(errorCode, data && data.message);
            throw new Error(String(errorMessage || "Request failed."));
          }
          status.style.color = "#86efac";
          status.textContent = "Check your email for the activation link.";
        } catch (error) {
          status.style.color = "#fca5a5";
          status.textContent = String(error && error.message || "Request failed. Please try again.");
          console.error("planetka api-key request failed", error);
        } finally {
          submit.disabled = false;
        }
      });
    </script>
  </body>
</html>`, 200, env);
}

function renderApiKeyActivatedPage(env, data = {}) {
  const contactUrl = normalizeContactUrl(env.CONTACT_URL || DEFAULT_CONTACT_URL);
  const key = String(data.apiKey || "").trim();
  const keyMask = key ? maskApiKey(key) : "";
  const email = String(data.email || "").trim();
  const planCode = normalizeRequestedPlan(data.planCode || PLAN_CODE_PLANETKA);
  const planLabel = planDisplayName(planCode);
  const accessSummary = planAccessSummary(planCode);
  return html(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka API Key Ready</title>
    <style>
      :root { color-scheme: dark; }
      body { margin:0; min-height:100vh; display:grid; place-items:center; background:linear-gradient(180deg,#07111f 0%, #0b1424 100%); font-family: Inter, system-ui, sans-serif; color:#e5edf7; }
      .card { width:min(92vw,560px); padding:28px; border-radius:18px; background:rgba(8,15,29,.82); border:1px solid rgba(148,163,184,.2); box-shadow:0 20px 60px rgba(0,0,0,.35); }
      h1 { margin:0 0 12px; font-size:30px; }
      p { margin:0 0 12px; color:#cbd5e1; line-height:1.5; }
      pre { margin:10px 0 12px; padding:12px; border-radius:10px; background:#0f172a; border:1px solid rgba(148,163,184,.28); color:#f8fafc; overflow:auto; }
      button { border:none; border-radius:10px; background:#1d4ed8; color:#fff; padding:10px 14px; cursor:pointer; font-weight:600; }
      a { color:#93c5fd; }
      .muted { color:#94a3b8; font-size:13px; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>API key generated</h1>
      <p>Email: <strong>${escapeHtml(email || "unknown")}</strong></p>
      <p>Access: <strong>${escapeHtml(planLabel)}</strong></p>
      <p>${escapeHtml(accessSummary)}</p>
      <pre id="apiKey">${escapeHtml(key)}</pre>
      <button id="copyBtn" type="button">Copy API key</button>
      <p class="muted" id="copyStatus">Key mask: ${escapeHtml(keyMask)}</p>
      <p>Paste this key in Blender: Planetka &rarr; Account.</p>
      <p>Problem connecting? <a href="${contactUrl}" target="_blank" rel="noopener noreferrer">Contact Me</a></p>
    </main>
    <script>
      const btn = document.getElementById("copyBtn");
      const status = document.getElementById("copyStatus");
      btn.addEventListener("click", async () => {
        const text = document.getElementById("apiKey").textContent || "";
        try {
          await navigator.clipboard.writeText(text);
          status.textContent = "Copied to clipboard.";
          status.style.color = "#86efac";
        } catch (error) {
          status.textContent = "Copy failed. Select and copy manually.";
          status.style.color = "#fca5a5";
        }
      });
    </script>
  </body>
</html>`, 200, env);
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

async function sendProvisionalPlanAlert(env, details = {}) {
  try {
    await sendOpsAlertEmail(
      env,
      "Planetka provisional paid access request",
      [
        "A user requested provisional paid access.",
        `email=${normalizeEmail(details.email || "")}`,
        `requested_plan=${normalizeRequestedPlan(details.requestedPlan || PLAN_CODE_PLANETKA)}`,
        `order_id=${normalizeOrderId(details.orderId || "")}`,
        `request_ip=${String(details.ip || "").trim()}`,
        `request_device_id=${normalizeDeviceId(details.deviceId || "")}`,
        `claim_id=${String(details.claimId || "").trim()}`,
        `provisional_expires_at=${String(details.provisionalExpiresAt || "").trim()}`,
        "",
        "If payment is confirmed, mark the user as confirmed in D1 before expiry.",
      ],
    );
  } catch (error) {
    console.warn(
      "worker.provisional_alert_email_failed",
      JSON.stringify({
        email: normalizeEmail(details.email || ""),
        error: String(error && error.message || "alert_email_failed"),
      }),
    );
  }
}

async function signalRejectedClaimAttempt(db, env, details = {}) {
  await ensureRateLimitsTable(db);
  const normalizedEmail = normalizeEmail(details.email || "");
  const ip = String(details.ip || "").trim();
  const deviceId = normalizeDeviceId(details.deviceId || "");
  const threshold = parseRateLimitInteger(
    env.REJECTED_CLAIM_ALERT_THRESHOLD,
    DEFAULT_REJECTED_CLAIM_ALERT_THRESHOLD,
  );
  const windowSeconds = parseRateLimitInteger(
    env.REJECTED_CLAIM_ALERT_WINDOW_SECONDS,
    DEFAULT_REJECTED_CLAIM_ALERT_WINDOW_SECONDS,
  );
  if (threshold <= 0 || windowSeconds <= 0) {
    return;
  }
  const signals = [];
  if (normalizedEmail) {
    signals.push({ keyType: "email", keyValue: normalizedEmail });
  }
  if (ip) {
    signals.push({ keyType: "ip", keyValue: ip });
  }
  if (deviceId) {
    signals.push({ keyType: "device", keyValue: deviceId });
  }
  if (!signals.length) {
    return;
  }
  const triggered = [];
  for (const signal of signals) {
    const rate = await consumeRateLimitWindow(
      db,
      `claim_reject_${signal.keyType}`,
      signal.keyValue,
      2147483647,
      windowSeconds,
    );
    if (thresholdHit(clampNonNegativeInt(rate && rate.count), threshold)) {
      triggered.push({
        keyType: signal.keyType,
        keyValue: signal.keyValue,
        count: clampNonNegativeInt(rate && rate.count),
      });
    }
  }
  await appendProvisionalClaimAudit(
    db,
    "claim_rejected_signal",
    {
      email: normalizedEmail,
      orderId: details.orderId || "",
      planCode: details.requestedPlan || PLAN_CODE_PLANETKA,
      ip,
      deviceId,
      details: {
        reason: String(details.reason || "").trim(),
        claim_id: String(details.claimId || "").trim(),
        triggered,
      },
    },
  );
  if (!triggered.length) {
    return;
  }
  try {
    await sendOpsAlertEmail(
      env,
      "Planetka repeated rejected paid-claim activity",
      [
        "Repeated rejected paid-claim activity detected.",
        `email=${normalizedEmail}`,
        `ip=${ip}`,
        `device_id=${deviceId}`,
        `order_id=${normalizeOrderId(details.orderId || "")}`,
        `requested_plan=${normalizeRequestedPlan(details.requestedPlan || PLAN_CODE_PLANETKA)}`,
        `reason=${String(details.reason || "").trim()}`,
        `claim_id=${String(details.claimId || "").trim()}`,
        `triggered=${JSON.stringify(triggered)}`,
      ],
    );
  } catch (error) {
    console.warn(
      "worker.rejected_claim_alert_email_failed",
      JSON.stringify({
        email: normalizedEmail,
        error: String(error && error.message || "rejected_claim_alert_email_failed"),
      }),
    );
  }
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
  const requestType = API_KEY_REQUEST_TYPE_FREE;
  const reviewStatus = CLAIM_REVIEW_APPROVED;
  const claimPlanCode = requestedPlan;
  const claimId = crypto.randomUUID();
  await dbRun(
    db,
    `
      INSERT INTO api_key_requests (
        id,
        email,
        requested_plan,
        request_type,
        claimed_plan_code,
        order_id,
        token_hash,
        expires_at,
        review_status,
        accept_terms,
        accept_privacy,
        opt_in_news,
        submitted_at_ms,
        request_ip,
        request_device_id,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      claimId,
      email,
      claimPlanCode,
      requestType,
      claimPlanCode,
      null,
      tokenHash,
      addMinutesIso(30),
      reviewStatus,
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
        AND (
          request_type IS NULL
          OR request_type = ''
          OR request_type = ?
          OR (request_type = ? AND review_status = ?)
        )
      RETURNING
        id,
        email,
        requested_plan,
        claimed_plan_code,
        request_type,
        order_id,
        request_ip,
        request_device_id,
        review_status,
        opt_in_news
    `,
    [
      now,
      tokenHash,
      now,
      API_KEY_REQUEST_TYPE_FREE,
      API_KEY_REQUEST_TYPE_PAID_CLAIM,
      CLAIM_REVIEW_APPROVED,
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

async function handleApiKeyActivatePage(request, env) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return renderApiKeyRequestPage(env, "Missing activation token.");
  }
  const db = requireDb(env);
  try {
    const activated = await activateApiKeyFromToken(db, env, token);
    return renderApiKeyActivatedPage(env, activated);
  } catch (_error) {
    return renderApiKeyRequestPage(env, "Activation link is invalid or expired. Request a new key.");
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
    provisional_plan_code: record.provisional_plan_code || "",
    provisional_expires_at: record.provisional_expires_at || "",
    pro_confirmed_at: record.pro_confirmed_at || "",
    pro_access_expires_at: record.pro_access_expires_at || "",
  };
  user = await enforceUserPlanPolicy(db, user, null, env);
  const effectivePlanCode = resolvePlanCode(user, null, env);
  if (effectivePlanCode === PLAN_CODE_PLANETKA) {
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
  const provisionalRestricted = (
    clampNonNegativeInt(record.api_key_provisional) === 1
    && !String(record.api_key_confirmed_at || "").trim()
    && !String(record.pro_confirmed_at || "").trim()
  );
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
        message: provisionalRestricted
          ? "This Planetka account can be active on one computer at a time."
          : "This Planetka account can be active on one computer at a time.",
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
      subscription_status: subscriptionStatusForUser(user, env),
      hosted_streaming_access_status: subscriptionStatusForUser(user, env),
      renews_at: "",
      trial_ends_at: "",
      api_key_mask: maskApiKey(apiKey),
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

async function handleAuthStart(request, env) {
  if (!isMagicLinkAuthEnabled(env)) {
    return json({ ok: false, error: "magic_link_auth_disabled" }, 404, env);
  }
  const db = requireDb(env);
  await ensureUserConsentColumns(db);
  await ensureMagicLinksTokenIndex(db);
  await ensureRateLimitsTable(db);
  const body = await parseJson(request);
  const email = normalizeEmail(body.email);
  const clientIp = requestClientIp(request);
  const authStartIpWindowSeconds = parseRateLimitInteger(
    env.RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS,
  );
  const authStartIpLimit = parseRateLimitInteger(
    env.RATE_LIMIT_AUTH_START_IP_LIMIT,
    DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT,
  );
  const authStartIpRate = await consumeRateLimitWindow(
    db,
    "auth_start_ip",
    clientIp,
    authStartIpLimit,
    authStartIpWindowSeconds,
  );
  if (!authStartIpRate.allowed) {
    await trackThresholdAlertDb(
      db,
      "auth_429_spike",
      parseRateLimitInteger(env.LOG_ALERT_AUTH_429_THRESHOLD, DEFAULT_ALERT_AUTH_429_THRESHOLD),
      parseRateLimitInteger(env.LOG_ALERT_AUTH_429_WINDOW_SECONDS, DEFAULT_ALERT_AUTH_429_WINDOW_SECONDS),
      { route: "/auth/start", scope: "ip", code: "auth_start_ip_rate_limited" },
    );
    return rateLimitedResponse(
      env,
      "auth_start_ip_rate_limited",
      "Too many login requests. Please try again shortly.",
      authStartIpRate.retryAfterSeconds,
    );
  }
  const authStartEmailWindowSeconds = parseRateLimitInteger(
    env.RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS,
  );
  const authStartEmailLimit = parseRateLimitInteger(
    env.RATE_LIMIT_AUTH_START_EMAIL_LIMIT,
    DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT,
  );
  const authStartEmailRate = await consumeRateLimitWindow(
    db,
    "auth_start_email",
    email || "unknown",
    authStartEmailLimit,
    authStartEmailWindowSeconds,
  );
  if (!authStartEmailRate.allowed) {
    await trackThresholdAlertDb(
      db,
      "auth_429_spike",
      parseRateLimitInteger(env.LOG_ALERT_AUTH_429_THRESHOLD, DEFAULT_ALERT_AUTH_429_THRESHOLD),
      parseRateLimitInteger(env.LOG_ALERT_AUTH_429_WINDOW_SECONDS, DEFAULT_ALERT_AUTH_429_WINDOW_SECONDS),
      { route: "/auth/start", scope: "email", code: "auth_start_email_rate_limited" },
    );
    return rateLimitedResponse(
      env,
      "auth_start_email_rate_limited",
      "Too many login requests for this email. Please try again later.",
      authStartEmailRate.retryAfterSeconds,
    );
  }
  const deviceCode = String(body.device_code || "").trim();
  const acceptTerms = parseBooleanFlag(body.accept_terms);
  const acceptPrivacy = parseBooleanFlag(body.accept_privacy);
  const optInNews = parseBooleanFlag(body.opt_in_news);
  const legalVersion = String(env.TERMS_VERSION || env.LEGAL_VERSION || DEFAULT_LEGAL_VERSION).trim() || DEFAULT_LEGAL_VERSION;
  const privacyVersion = String(env.PRIVACY_VERSION || env.LEGAL_VERSION || DEFAULT_LEGAL_VERSION).trim() || DEFAULT_LEGAL_VERSION;
  if (!email || !email.includes("@")) {
    return json({ ok: false, error: "invalid_email" }, 400, env);
  }

  if (deviceCode) {
    if (!isValidDeviceCode(deviceCode)) {
      return json({ ok: false, error: "device_session_invalid" }, 400, env);
    }
    await ensureDeviceSessionsTable(db);
    const deviceSession = await dbGet(
      db,
      `
        SELECT id, expires_at, claimed_at
        FROM device_sessions
        WHERE device_code = ?
        LIMIT 1
      `,
      [deviceCode],
    );
    if (!deviceSession || deviceSession.claimed_at || Date.parse(deviceSession.expires_at) < Date.now()) {
      return json({ ok: false, error: "device_session_invalid" }, 400, env);
    }
  }

  let user = await findUserByEmail(db, email);
  if (!user) {
    if (!acceptTerms || !acceptPrivacy) {
      return json({ ok: false, error: "terms_consent_required" }, 400, env);
    }
    const acceptedAt = nowIso();
    user = await upsertUserByEmail(db, email, PLAN_CODE_PLANETKA_FREE, {
      termsAcceptedAt: acceptedAt,
      privacyAcceptedAt: acceptedAt,
      termsVersion: legalVersion,
      privacyVersion,
      signupSource: deviceCode ? "device_login" : "magic_link_auth_start",
    }, env);
  } else if (isBlockedStatus(user.status)) {
    return genericAuthStartResponse(env);
  } else if (acceptTerms && acceptPrivacy) {
    const acceptedAt = nowIso();
    await dbRun(
      db,
      `
        UPDATE users
        SET
          terms_accepted_at = COALESCE(terms_accepted_at, ?),
          privacy_accepted_at = COALESCE(privacy_accepted_at, ?),
          terms_version = COALESCE(terms_version, ?),
          privacy_version = COALESCE(privacy_version, ?)
        WHERE id = ?
      `,
      [acceptedAt, acceptedAt, legalVersion, privacyVersion, user.id],
    );
  }
  if (user && !isBlockedStatus(user.status)) {
    user = await enforceUserPlanPolicy(db, user, null, env);
  }

  if (optInNews) {
    const source = deviceCode ? "device_login_page" : "auth_start";
    await recordNewsletterOptIn(db, email, source);
  }

  const token = randomToken(32);
  const tokenHash = await sha256Hex(token);
  const magicLinkId = crypto.randomUUID();
  await dbRun(
    db,
    `
      INSERT INTO magic_links (
        id,
        user_id,
        token_hash,
        expires_at,
        created_at
      ) VALUES (?, ?, ?, ?, ?)
    `,
    [magicLinkId, user.id, tokenHash, addMinutesIso(15), nowIso()],
  );

  await sendMagicLinkEmail(env, email, token, buildMagicLinkUrl(env, token, deviceCode));
  return genericAuthStartResponse(env);
}

async function handleAuthVerify(request, env) {
  if (!isMagicLinkAuthEnabled(env)) {
    return json({ ok: false, error: "magic_link_auth_disabled" }, 404, env);
  }
  const db = requireDb(env);
  await ensureUserProvisionalColumns(db);
  await ensureMagicLinksTokenIndex(db);
  const body = await parseJson(request);
  const token = String(body.token || "").trim();
  const deviceCode = String(body.device_code || "").trim();
  if (!token) {
    return json({ ok: false, error: "missing_token" }, 400, env);
  }

  const tokenHash = await sha256Hex(token);
  const usedAt = nowIso();
  const claimedMagicLink = await dbGet(
    db,
    `
      UPDATE magic_links
      SET used_at = ?
      WHERE token_hash = ?
        AND used_at IS NULL
        AND expires_at >= ?
        AND user_id IN (
          SELECT id
          FROM users
          WHERE LOWER(COALESCE(status, '')) != 'blocked'
        )
      RETURNING id, user_id
    `,
    [usedAt, tokenHash, usedAt],
  );

  let magicLink = null;
  if (!claimedMagicLink) {
    magicLink = await dbGet(
      db,
      `
      SELECT
        ml.id,
        ml.user_id,
        ml.expires_at,
        ml.used_at,
        u.email,
        u.status AS user_status
      FROM magic_links ml
      JOIN users u ON u.id = ml.user_id
      WHERE ml.token_hash = ?
      LIMIT 1
    `,
      [tokenHash],
    );
    if (!magicLink) {
      return json({ ok: false, error: "invalid_token" }, 400, env);
    }
    if (isBlockedStatus(magicLink.user_status)) {
      return blockedAccountResponse(env);
    }
    if (magicLink.used_at) {
      return json({ ok: false, error: "token_already_used" }, 400, env);
    }
    if (Date.parse(magicLink.expires_at) < Date.now()) {
      return json({ ok: false, error: "token_expired" }, 400, env);
    }
    return json({ ok: false, error: "invalid_token" }, 400, env);
  }

  const userRecord = await dbGet(
    db,
    `
      SELECT
        u.id,
        u.email,
        u.status AS user_status,
        u.provisional_plan_code,
        u.provisional_expires_at,
        u.pro_confirmed_at,
        u.pro_access_expires_at
      FROM users u
      WHERE u.id = ?
      LIMIT 1
    `,
    [claimedMagicLink.user_id],
  );
  if (!userRecord) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }
  if (isBlockedStatus(userRecord.user_status)) {
    return blockedAccountResponse(env);
  }
  await dbRun(
    db,
    `UPDATE users SET last_login_at = ? WHERE id = ?`,
    [usedAt, userRecord.id],
  );

  let user = {
    id: userRecord.id,
    email: userRecord.email,
    status: userRecord.user_status || PLAN_CODE_PLANETKA,
    provisional_plan_code: userRecord.provisional_plan_code || "",
    provisional_expires_at: userRecord.provisional_expires_at || "",
    pro_confirmed_at: userRecord.pro_confirmed_at || "",
    pro_access_expires_at: userRecord.pro_access_expires_at || "",
  };
  user = await enforceUserPlanPolicy(db, user, null, env);
  const subscriptionStatus = subscriptionStatusForUser(user, env);
  const accessToken = await createAccessToken(env, user, null);
  const refreshToken = await createRefreshSession(db, userRecord.id);
  const accountState = await buildAccountState(db, user, null, env);

  if (deviceCode) {
    await ensureDeviceSessionsTable(db);
    const deviceSession = await dbGet(
      db,
      `
        SELECT id, expires_at, claimed_at
        FROM device_sessions
        WHERE device_code = ?
        LIMIT 1
      `,
      [deviceCode],
    );
    if (deviceSession && !deviceSession.claimed_at && Date.parse(deviceSession.expires_at) >= Date.now()) {
      await dbRun(
        db,
        `
          UPDATE device_sessions
          SET
            status = 'completed',
            email = ?,
            access_token = ?,
            refresh_token = ?,
            subscription_status = ?,
            renews_at = ?,
            trial_ends_at = ?,
            completed_at = ?
          WHERE id = ?
        `,
        [
          user.email,
          accessToken,
          refreshToken,
          subscriptionStatus,
          null,
          null,
          usedAt,
          deviceSession.id,
        ],
      );
    }
  }

  return json(
    {
      ok: true,
      access_token: accessToken,
      refresh_token: refreshToken,
      email: user.email,
      subscription_status: subscriptionStatus,
      hosted_streaming_access_status: subscriptionStatus,
      renews_at: null,
      trial_ends_at: null,
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

async function handleAuthRefresh(request, env) {
  const db = requireDb(env);
  await ensureUserProvisionalColumns(db);
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
        u.status,
        u.provisional_plan_code,
        u.provisional_expires_at,
        u.pro_confirmed_at,
        u.pro_access_expires_at
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
    provisional_plan_code: session.provisional_plan_code || "",
    provisional_expires_at: session.provisional_expires_at || "",
    pro_confirmed_at: session.pro_confirmed_at || "",
    pro_access_expires_at: session.pro_access_expires_at || "",
  };
  user = await enforceUserPlanPolicy(db, user, null, env);
  const subscriptionStatus = subscriptionStatusForUser(user, env);

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
      subscription_status: subscriptionStatus,
      hosted_streaming_access_status: subscriptionStatus,
      renews_at: null,
      trial_ends_at: null,
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
  );
  if (auth.error) {
    return auth.error;
  }
  const { db, user } = auth;
  const effectiveUserStatus = resolvePolicyPlanCode(user, null, env);
  const accountState = await buildAccountState(db, user, null, env);
  const subscriptionStatus = subscriptionStatusForUser(user, env);

  return json(
    {
      ok: true,
      email: user.email,
      user_status: effectiveUserStatus,
      subscription_status: subscriptionStatus,
      hosted_streaming_access_status: subscriptionStatus,
      trial_ends_at: null,
      renews_at: null,
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

async function handleDeviceStart(request, env) {
  if (!isMagicLinkAuthEnabled(env)) {
    return json({ ok: false, error: "magic_link_auth_disabled" }, 404, env);
  }
  const db = requireDb(env);
  await ensureDeviceSessionsTable(db);
  const deviceCode = randomToken(24);
  const createdAt = nowIso();
  const expiresAt = addMinutesIso(15);
  const expiresAtTs = Math.floor(Date.parse(expiresAt) / 1000);
  const verificationUrl = `${String(env.API_BASE_URL || "https://api.planetka.io").trim().replace(/\/+$/, "")}/device/login?device_code=${encodeURIComponent(deviceCode)}`;

  await dbRun(
    db,
    `
      INSERT INTO device_sessions (
        id,
        device_code,
        status,
        expires_at,
        created_at
      ) VALUES (?, ?, 'pending', ?, ?)
    `,
    [crypto.randomUUID(), deviceCode, expiresAt, createdAt],
  );

  return json(
    {
      ok: true,
      status: "pending",
      device_code: deviceCode,
      verification_url: verificationUrl,
      interval_seconds: 2,
      expires_at: expiresAt,
      expires_at_ts: expiresAtTs,
    },
    200,
    env,
  );
}

async function handleDevicePoll(request, env) {
  if (!isMagicLinkAuthEnabled(env)) {
    return json({ ok: false, error: "magic_link_auth_disabled" }, 404, env);
  }
  const db = requireDb(env);
  await ensureDeviceSessionsTable(db);
  await ensureRateLimitsTable(db);
  const body = await parseJson(request);
  const deviceCode = String(body.device_code || "").trim();
  const clientIp = requestClientIp(request);
  const devicePollIpWindowSeconds = parseRateLimitInteger(
    env.RATE_LIMIT_DEVICE_POLL_IP_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT_DEVICE_POLL_IP_WINDOW_SECONDS,
  );
  const devicePollIpLimit = parseRateLimitInteger(
    env.RATE_LIMIT_DEVICE_POLL_IP_LIMIT,
    DEFAULT_RATE_LIMIT_DEVICE_POLL_IP_LIMIT,
  );
  const devicePollIpRate = await consumeRateLimitWindow(
    db,
    "device_poll_ip",
    clientIp,
    devicePollIpLimit,
    devicePollIpWindowSeconds,
  );
  if (!devicePollIpRate.allowed) {
    await trackThresholdAlertDb(
      db,
      "device_poll_429_spike",
      parseRateLimitInteger(env.LOG_ALERT_DEVICE_POLL_429_THRESHOLD, DEFAULT_ALERT_DEVICE_POLL_429_THRESHOLD),
      parseRateLimitInteger(env.LOG_ALERT_DEVICE_POLL_429_WINDOW_SECONDS, DEFAULT_ALERT_DEVICE_POLL_429_WINDOW_SECONDS),
      { route: "/device/poll", scope: "ip", code: "device_poll_ip_rate_limited" },
    );
    return rateLimitedResponse(
      env,
      "device_poll_ip_rate_limited",
      "Too many polling requests. Please slow down and try again shortly.",
      devicePollIpRate.retryAfterSeconds,
    );
  }
  if (!deviceCode) {
    return json({ ok: false, error: "missing_device_code" }, 400, env);
  }
  if (!isValidDeviceCode(deviceCode)) {
    return json({ ok: false, error: "invalid_device_code" }, 400, env);
  }

  const session = await dbGet(
    db,
    `
      SELECT
        id,
        status,
        email,
        access_token,
        refresh_token,
        subscription_status,
        renews_at,
        trial_ends_at,
        expires_at,
        claimed_at
      FROM device_sessions
      WHERE device_code = ?
      LIMIT 1
    `,
    [deviceCode],
  );

  if (!session) {
    return json({ ok: false, error: "device_session_not_found" }, 404, env);
  }

  const devicePollCodeWindowSeconds = parseRateLimitInteger(
    env.RATE_LIMIT_DEVICE_POLL_CODE_WINDOW_SECONDS,
    DEFAULT_RATE_LIMIT_DEVICE_POLL_CODE_WINDOW_SECONDS,
  );
  const devicePollCodeLimit = parseRateLimitInteger(
    env.RATE_LIMIT_DEVICE_POLL_CODE_LIMIT,
    DEFAULT_RATE_LIMIT_DEVICE_POLL_CODE_LIMIT,
  );
  const devicePollCodeRate = await consumeRateLimitWindow(
    db,
    "device_poll_code",
    session.id,
    devicePollCodeLimit,
    devicePollCodeWindowSeconds,
  );
  if (!devicePollCodeRate.allowed) {
    await trackThresholdAlertDb(
      db,
      "device_poll_429_spike",
      parseRateLimitInteger(env.LOG_ALERT_DEVICE_POLL_429_THRESHOLD, DEFAULT_ALERT_DEVICE_POLL_429_THRESHOLD),
      parseRateLimitInteger(env.LOG_ALERT_DEVICE_POLL_429_WINDOW_SECONDS, DEFAULT_ALERT_DEVICE_POLL_429_WINDOW_SECONDS),
      { route: "/device/poll", scope: "device_session", code: "device_poll_code_rate_limited" },
    );
    return rateLimitedResponse(
      env,
      "device_poll_code_rate_limited",
      "Too many polling requests for this device session. Please slow down and try again shortly.",
      devicePollCodeRate.retryAfterSeconds,
    );
  }

  if (session.claimed_at) {
    return json({ ok: false, error: "device_session_claimed" }, 410, env);
  }
  if (Date.parse(session.expires_at) < Date.now()) {
    return json({ ok: false, error: "device_session_expired" }, 408, env);
  }
  if (String(session.status || "") !== "completed") {
    return json({ ok: true, status: "pending" }, 200, env);
  }

  await dbRun(
    db,
    `UPDATE device_sessions SET claimed_at = ? WHERE id = ?`,
    [nowIso(), session.id],
  );

  let accountPayload = {};
  try {
    let user = await findUserByEmail(db, normalizeEmail(session.email));
    if (user) {
      user = await enforceUserPlanPolicy(db, user, null, env);
      const accountState = await buildAccountState(db, user, null, env);
      accountPayload = serializeAccountState(accountState);
    }
  } catch (error) {
    console.warn(
      "worker.device_poll.account_payload_failed",
      JSON.stringify({
        session_id: String(session.id || ""),
        error: String(error && error.message || "account_payload_failed"),
      }),
    );
    accountPayload = {};
  }

  return json(
    {
      ok: true,
      status: "completed",
      email: session.email,
      access_token: session.access_token,
      refresh_token: session.refresh_token,
      subscription_status: session.subscription_status,
      hosted_streaming_access_status: session.subscription_status,
      renews_at: session.renews_at,
      trial_ends_at: session.trial_ends_at,
      ...accountPayload,
    },
    200,
    env,
  );
}

function renderDeviceLoginPage(env, deviceCode = "", verifyMode = false) {
  const termsUrl = String(env.TERMS_URL || DEFAULT_TERMS_URL).trim() || DEFAULT_TERMS_URL;
  const privacyUrl = String(env.PRIVACY_URL || DEFAULT_PRIVACY_URL).trim() || DEFAULT_PRIVACY_URL;
  const contactUrl = normalizeContactUrl(env.CONTACT_URL || DEFAULT_CONTACT_URL);
  const loginSectionStyle = verifyMode ? "display:none;" : "";
  const verifySectionStyle = verifyMode ? "" : "display:none;";
  const verifyEmailInitial = verifyMode ? "Verifying email address..." : "";
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Device Login</title>
    <style>
      :root { color-scheme: dark; }
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background:
          radial-gradient(circle at top, rgba(62,102,178,0.28), transparent 36%),
          linear-gradient(180deg, #07111f 0%, #0b1424 100%);
        font-family: Inter, system-ui, sans-serif;
        color: #e5edf7;
      }
      .card {
        width: min(92vw, 520px);
        padding: 28px;
        border-radius: 18px;
        background: rgba(8, 15, 29, 0.78);
        border: 1px solid rgba(148, 163, 184, 0.2);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
      }
      h1 { margin: 0 0 10px; font-size: 32px; }
      p { margin: 0 0 18px; color: #cbd5e1; line-height: 1.5; }
      label { display: block; margin-bottom: 10px; font-size: 14px; color: #cbd5e1; }
      input {
        width: 100%;
        box-sizing: border-box;
        padding: 14px 16px;
        border-radius: 12px;
        border: 1px solid rgba(148, 163, 184, 0.25);
        background: #0f172a;
        color: #fff;
        font-size: 16px;
        outline: none;
      }
      .consent {
        margin-top: 14px;
      }
      .consent label {
        display: flex;
        gap: 10px;
        align-items: flex-start;
        margin: 0;
        font-size: 13px;
        line-height: 1.4;
      }
      .consent input[type="checkbox"] {
        width: 16px;
        height: 16px;
        margin-top: 2px;
        flex: 0 0 auto;
      }
      .consent a { color: #e5edf7; }
      button {
        margin-top: 14px;
        width: 100%;
        padding: 14px 16px;
        border: 0;
        border-radius: 12px;
        background: #f8fafc;
        color: #0f172a;
        font-size: 16px;
        font-weight: 700;
        cursor: pointer;
      }
      .status {
        display: none;
        margin-top: 14px;
        padding: 12px 14px;
        border-radius: 10px;
        font-size: 14px;
        line-height: 1.5;
      }
      .verify-email {
        margin: 0 0 10px;
        color: #e2e8f0;
      }
      .contact-help {
        margin-top: 16px;
        font-size: 14px;
        color: #cbd5e1;
      }
      .contact-help a {
        color: #e5edf7;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <div id="planetka-login-section" style="${loginSectionStyle}">
        <h1>Log In to Planetka</h1>
        <p>For free access, enter your email address and Blender will connect automatically after you confirm the login email.</p>
        <label for="planetka-email">Email</label>
        <input id="planetka-email" type="email" placeholder="you@example.com" />
        <div class="consent">
          <label for="planetka-consent">
            <input id="planetka-consent" type="checkbox" />
            <span>I agree to the <a href="${termsUrl}" target="_blank" rel="noopener noreferrer">Terms and Conditions</a> and <a href="${privacyUrl}" target="_blank" rel="noopener noreferrer">Privacy Policy</a>.</span>
          </label>
        </div>
        <div class="consent">
          <label for="planetka-news-optin">
            <input id="planetka-news-optin" type="checkbox" />
            <span>Opt in for quarterly Planetka updates by email. Email addresses are not shared with third parties.</span>
          </label>
        </div>
        <button id="planetka-send-link">Send Login Link</button>
        <div id="planetka-status" class="status"></div>
      </div>
      <div id="planetka-verify-section" style="${verifySectionStyle}">
        <h1>Email Verified</h1>
        <p id="planetka-verify-email" class="verify-email">${verifyEmailInitial}</p>
        <div id="planetka-verify-status" class="status"></div>
        <p class="contact-help">Problem connecting? <a href="${contactUrl}" target="_blank" rel="noopener noreferrer">Contact Me</a></p>
      </div>
    </div>
    <script>
      (() => {
        const API = "${String(env.API_BASE_URL || "https://api.planetka.io").trim()}";
        const DEVICE_CODE = ${JSON.stringify(deviceCode)};
        const loginSection = document.getElementById("planetka-login-section");
        const verifySection = document.getElementById("planetka-verify-section");
        const email = document.getElementById("planetka-email");
        const consent = document.getElementById("planetka-consent");
        const newsOptIn = document.getElementById("planetka-news-optin");
        const button = document.getElementById("planetka-send-link");
        const status = document.getElementById("planetka-status");
        const verifyEmail = document.getElementById("planetka-verify-email");
        const verifyStatus = document.getElementById("planetka-verify-status");
        let busy = false;

        function showStatus(target, message, type = "info") {
          if (!target) return;
          target.textContent = message || "";
          target.style.display = message ? "block" : "none";
          if (type === "error") {
            target.style.background = "rgba(127,29,29,.18)";
            target.style.border = "1px solid rgba(248,113,113,.35)";
            target.style.color = "#fecaca";
            return;
          }
          if (type === "success") {
            target.style.background = "rgba(20,83,45,.18)";
            target.style.border = "1px solid rgba(74,222,128,.35)";
            target.style.color = "#bbf7d0";
            return;
          }
          target.style.background = "rgba(30,41,59,.35)";
          target.style.border = "1px solid rgba(148,163,184,.25)";
          target.style.color = "#e2e8f0";
        }

        function show(message, type = "info") {
          showStatus(status, message, type);
        }

        function validEmail(value) {
          return /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(String(value || "").trim());
        }

        async function post(path, body) {
          const response = await fetch(API + path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(data.error || String(response.status));
          return data;
        }

        async function sendLink() {
          if (busy) return;
          const value = String(email.value || "").trim().toLowerCase();
          if (!validEmail(value)) {
            show("Enter a valid email address.", "error");
            return;
          }
          if (!consent.checked) {
            show("Please accept Terms and Privacy to continue.", "error");
            return;
          }
          busy = true;
          button.disabled = true;
          button.textContent = "Sending...";
          show("");
          try {
            await post("/auth/start", {
              email: value,
              device_code: DEVICE_CODE,
              accept_terms: true,
              accept_privacy: true,
              opt_in_news: Boolean(newsOptIn && newsOptIn.checked),
            });
            show("Check your inbox. We sent you a secure login link.", "success");
          } catch (error) {
            console.error("planetka auth/start failed", error);
            if (String(error && error.message || "") === "terms_consent_required") {
              show("Please accept Terms and Privacy to continue.", "error");
              return;
            }
            show("Login request failed. Please try again.", "error");
          } finally {
            busy = false;
            button.disabled = false;
            button.textContent = "Send Login Link";
          }
        }

        async function verifyToken() {
          const token = new URLSearchParams(window.location.search).get("token");
          if (!token) return;
          loginSection.style.display = "none";
          verifySection.style.display = "block";
          verifyEmail.textContent = "Verifying email address...";
          showStatus(verifyStatus, "Verifying login...", "info");
          busy = true;
          try {
            const data = await post("/auth/verify", { token, device_code: DEVICE_CODE });
            const verifiedEmail = String((data && data.email) || "").trim();
            if (verifiedEmail) {
              verifyEmail.textContent = "Email address " + verifiedEmail + " has been verified.";
            } else {
              verifyEmail.textContent = "Your email address has been verified.";
            }
            showStatus(verifyStatus, "Blender is now connected. You can return to Blender.", "success");
          } catch (error) {
            console.error("planetka auth/verify failed", error);
            verifyEmail.textContent = "Verification failed.";
            showStatus(verifyStatus, "This login link is invalid or expired. Please request a new one.", "error");
          } finally {
            busy = false;
          }
        }

        button.addEventListener("click", (event) => {
          event.preventDefault();
          sendLink();
        });

        email.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            sendLink();
          }
        });

        verifyToken();
      })();
    </script>
  </body>
</html>`;
}

async function handleDeviceLoginPage(request, env) {
  if (!isMagicLinkAuthEnabled(env)) {
    return json({ ok: false, error: "magic_link_auth_disabled" }, 404, env);
  }
  const db = requireDb(env);
  await ensureDeviceSessionsTable(db);
  const url = new URL(request.url);
  const deviceCode = String(url.searchParams.get("device_code") || "").trim();
  const token = String(url.searchParams.get("token") || "").trim();
  const verifyMode = Boolean(token);
  if (!deviceCode) {
    return html(renderDeviceLoginPage(env, "", verifyMode), 200, env);
  }

  const session = await dbGet(
    db,
    `
      SELECT id, expires_at, claimed_at
      FROM device_sessions
      WHERE device_code = ?
      LIMIT 1
    `,
    [deviceCode],
  );
  if (!session || session.claimed_at || Date.parse(session.expires_at) < Date.now()) {
    return html(renderDeviceLoginPage(env, "", verifyMode), 410, env);
  }

  return html(renderDeviceLoginPage(env, deviceCode, verifyMode), 200, env);
}

function resolveLegalDocumentConfig(path, env) {
  const normalized = String(path || "").trim().toLowerCase();
  if (normalized === "/legal/terms-of-service.pdf") {
    return {
      key: String(env.LEGAL_TERMS_KEY || "legal/terms-of-service.pdf").trim() || "legal/terms-of-service.pdf",
      fileName: "Planetka-Terms-of-Service.pdf",
    };
  }
  if (normalized === "/legal/privacy-policy.pdf") {
    return {
      key: String(env.LEGAL_PRIVACY_KEY || "legal/privacy-policy.pdf").trim() || "legal/privacy-policy.pdf",
      fileName: "Planetka-Privacy-Policy.pdf",
    };
  }
  return null;
}

async function handleLegalDocumentRequest(request, env, path) {
  if (!env.PLANETKA_DATA) {
    return json({ ok: false, error: "missing_r2_binding" }, 500, env);
  }
  const doc = resolveLegalDocumentConfig(path, env);
  if (!doc) {
    return json({ ok: false, error: "not_found" }, 404, env);
  }
  const object = await env.PLANETKA_DATA.get(doc.key);
  if (!object) {
    return json({ ok: false, error: "legal_document_not_found" }, 404, env);
  }
  const headers = new Headers({
    ...corsHeaders(env),
    "Content-Type": "application/pdf",
    "Content-Disposition": `inline; filename="${doc.fileName}"`,
    "Cache-Control": "public, max-age=300, s-maxage=86400",
  });
  if (Number.isFinite(Number(object.size))) {
    headers.set("Content-Length", String(Math.max(0, Number(object.size))));
  }
  if (object.httpEtag) {
    headers.set("ETag", String(object.httpEtag));
  }
  if (request.method === "HEAD") {
    return new Response(null, { status: 200, headers });
  }
  return new Response(object.body, { status: 200, headers });
}

function guessContentType(fileName) {
  const lower = String(fileName || "").toLowerCase();
  if (lower.endsWith(".exr")) return "image/x-exr";
  if (lower.endsWith(".tif") || lower.endsWith(".tiff")) return "image/tiff";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  return "application/octet-stream";
}

function buildTileEdgeCacheKey(request, key) {
  const cacheUrl = new URL(request.url);
  cacheUrl.search = "";
  cacheUrl.searchParams.set("__planetka_r2_key", key);
  return new Request(cacheUrl.toString(), { method: "GET" });
}

function buildTileResponseHeaders(env, fileName, sizeBytes, etag) {
  const headers = new Headers({
    ...corsHeaders(env),
    "Content-Type": guessContentType(fileName),
    "Content-Length": String(clampNonNegativeInt(sizeBytes)),
    "Cache-Control": resolveTileCacheControl(env),
  });
  if (etag) {
    headers.set("ETag", String(etag));
  }
  return headers;
}

async function handleTileSessionStart(request, env) {
  const auth = await requireAuthenticatedUserContext(
    request,
    env,
    { enforceApiKeyDevicePolicy: false, lightweightAccessClaims: true },
  );
  if (auth.error) {
    return auth.error;
  }
  const db = requireDb(env);
  const requestDeviceId = normalizeDeviceId(
    auth.deviceId || request.headers.get("X-Planetka-Device-Id") || "",
  );
  const throttleGate = await enforceTileSessionThrottleGateCached(
    db,
    env,
    auth.user,
    requestDeviceId,
    requestClientIp(request),
  );
  if (throttleGate && throttleGate.blocked) {
    return rateLimitedResponse(
      env,
      String(throttleGate.code || "download_throttled"),
      String(
        throttleGate.message
        || "High-volume data use detected. Download speed is temporarily throttled. Contact Planetka support if needed.",
      ),
      resolveDownloadThrottleRetryAfterSeconds(throttleGate),
    );
  }
  const body = await parseJson(request);
  const requestedQualityMode = String(
    body && body.quality_mode ? body.quality_mode : request.headers.get("X-Planetka-Quality-Mode") || "",
  ).trim();
  const requestedResolveId = String(
    body && body.resolve_id ? body.resolve_id : request.headers.get("X-Planetka-Resolve-Id") || "",
  ).trim();
  const issued = await issueTileSessionToken(
    env,
    auth,
    requestedQualityMode,
    requestedResolveId,
  );
  if (issued && issued.error) {
    return issued.error;
  }
  return json(
    {
      ok: true,
      resolve_id: issued.resolveId,
      quality_mode: issued.qualityMode,
      tile_token: issued.token,
      expires_in_seconds: issued.expiresInSeconds,
      expires_at: issued.expiresAt,
      plan_code: normalizeRequestedPlan(auth && auth.planCode),
    },
    200,
    env,
  );
}

async function handleTileRequest(request, env, path, ctx) {
  if (!env.PLANETKA_DATA) {
    return json({ ok: false, error: "missing_r2_binding" }, 500, env);
  }

  const db = requireDb(env);
  let user = { id: "", email: "" };
  let planCode = PLAN_CODE_PLANETKA_FREE;
  let deviceId = "";
  let tokenQualityMode = "";
  let tokenResolveId = "";
  const tileSessionAuth = await readTileSessionClaims(request, env);
  if (tileSessionAuth && tileSessionAuth.error) {
    return tileSessionAuth.error;
  }
  if (tileSessionAuth && tileSessionAuth.claims) {
    user = {
      id: String(tileSessionAuth.claims.userId || "").trim(),
      email: String(tileSessionAuth.claims.userEmail || "").trim(),
    };
    planCode = normalizeRequestedPlan(tileSessionAuth.claims.planCode);
    deviceId = normalizeDeviceId(tileSessionAuth.claims.deviceId || request.headers.get("X-Planetka-Device-Id") || "");
    tokenQualityMode = normalizeQualityMode(tileSessionAuth.claims.qualityMode || "");
    tokenResolveId = normalizeResolveId(tileSessionAuth.claims.resolveId || "");
  } else {
    const auth = await requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: false, lightweightAccessClaims: true },
    );
    if (auth.error) {
      return auth.error;
    }
    user = auth.user;
    planCode = normalizeRequestedPlan(auth.planCode);
    deviceId = normalizeDeviceId(auth.deviceId || request.headers.get("X-Planetka-Device-Id") || "");
  }

  const requestStartedAtMs = Date.now();
  const clientIp = requestClientIp(request);
  const cfCountry = requestCountry(request);
  const cfRay = String(request.headers.get("CF-Ray") || "").trim();
  const resolveIdHeader = normalizeResolveId(request.headers.get("X-Planetka-Resolve-Id") || "");
  if (tokenResolveId && resolveIdHeader && tokenResolveId !== resolveIdHeader) {
    return json({ ok: false, error: "tile_session_resolve_mismatch" }, 403, env);
  }
  const resolveId = tokenResolveId || resolveIdHeader;
  let eventStatusCode = 0;
  let eventBytesServed = 0;
  let eventCacheStatus = "";
  let eventErrorCode = "";
  let eventFolder = "";
  let eventFileName = "";
  let eventTileKey = "";

  try {
    const parts = path.replace(/^\/tiles\//, "").split("/");
    if (parts.length !== 2 || !parts[0] || !parts[1]) {
      eventStatusCode = 400;
      eventErrorCode = "invalid_tile_path";
      return json({ ok: false, error: "invalid_tile_path" }, 400, env);
    }

    const folder = decodeURIComponent(parts[0]);
    let fileName = decodeURIComponent(parts[1]);
    eventFolder = folder;
    eventFileName = fileName;
    if (
      folder.includes("/") ||
      fileName.includes("/") ||
      folder.includes("..") ||
      fileName.includes("..")
    ) {
      eventStatusCode = 400;
      eventErrorCode = "invalid_tile_path";
      return json({ ok: false, error: "invalid_tile_path" }, 400, env);
    }

    const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
    let key = prefix ? `${prefix}/${folder}/${fileName}` : `${folder}/${fileName}`;
    eventTileKey = key;
    const qualityModeRaw = String(request.headers.get("X-Planetka-Quality-Mode") || "").trim().toLowerCase();
    const requestedQualityMode = normalizeQualityMode(qualityModeRaw);
    if (tokenQualityMode && qualityModeRaw && requestedQualityMode !== tokenQualityMode) {
      eventStatusCode = 403;
      eventErrorCode = "tile_session_quality_mismatch";
      return json({ ok: false, error: "tile_session_quality_mismatch" }, 403, env);
    }
    const effectiveQualityMode = tokenQualityMode || requestedQualityMode;
    if ((request.method === "GET" || request.method === "HEAD")
      && !isQualityModeAllowedForPlan(planCode, effectiveQualityMode)) {
      eventStatusCode = 403;
      eventErrorCode = "quality_mode_not_allowed_for_tier";
      return json(
        {
          ok: false,
          error: "quality_mode_not_allowed_for_tier",
          message: qualityModeNotAllowedMessage(planCode, effectiveQualityMode),
          requested_quality_mode: effectiveQualityMode,
        },
        403,
        env,
      );
    }
    const tileRequiredQualityMode = minimumPlanQualityForTile(fileName);
    if ((request.method === "GET" || request.method === "HEAD")
      && !isQualityModeAllowedForPlan(planCode, tileRequiredQualityMode)) {
      eventStatusCode = 403;
      eventErrorCode = "tile_quality_not_allowed_for_tier";
      return json(
        {
          ok: false,
          error: "tile_quality_not_allowed_for_tier",
          message: qualityModeNotAllowedMessage(planCode, tileRequiredQualityMode),
          requested_quality_mode: effectiveQualityMode,
          required_quality_mode: tileRequiredQualityMode,
          file_name: fileName,
        },
        403,
        env,
      );
    }

    if (request.method === "HEAD") {
      const objectHead = await env.PLANETKA_DATA.head(key);
      if (!objectHead) {
        eventStatusCode = 404;
        eventErrorCode = "tile_not_found";
        return new Response(null, { status: 404, headers: corsHeaders(env) });
      }
      eventStatusCode = 200;
      eventBytesServed = clampNonNegativeInt(objectHead.size);
      return new Response(null, {
        status: 200,
        headers: {
          ...corsHeaders(env),
          "Content-Length": String(objectHead.size || 0),
          "Content-Type": guessContentType(fileName),
        },
      });
    }

    const cache = caches.default;
    const cacheKeyRequest = buildTileEdgeCacheKey(request, key);
    const cached = await cache.match(cacheKeyRequest);
    let objectSize = 0;
    let contentType = guessContentType(fileName);
    let etag = "";
    let responseBody = null;
    let cacheStatus = "MISS";

    if (cached) {
      cacheStatus = "HIT";
      objectSize = clampNonNegativeInt(cached.headers.get("Content-Length"));
      contentType = String(cached.headers.get("Content-Type") || contentType);
      etag = String(cached.headers.get("ETag") || "");
      responseBody = cached.body;
    } else {
      const object = await env.PLANETKA_DATA.get(key);
      if (!object) {
        eventStatusCode = 404;
        eventErrorCode = "tile_not_found";
        return new Response("Not Found", { status: 404, headers: corsHeaders(env) });
      }
      objectSize = clampNonNegativeInt(object.size);
      etag = String(object.httpEtag || "");
      const cacheableHeaders = buildTileResponseHeaders(env, fileName, objectSize, etag);
      const cacheableResponse = new Response(object.body, { status: 200, headers: cacheableHeaders });
      if (ctx && typeof ctx.waitUntil === "function") {
        ctx.waitUntil(cache.put(cacheKeyRequest, cacheableResponse.clone()));
      } else {
        await cache.put(cacheKeyRequest, cacheableResponse.clone());
      }
      responseBody = cacheableResponse.body;
    }

    const responseHeaders = new Headers({
      ...corsHeaders(env),
      "Content-Type": contentType,
      "Content-Length": String(objectSize),
      "Cache-Control": resolveTileCacheControl(env),
      "X-Planetka-Cache": cacheStatus,
      "X-Planetka-Quality-Mode": effectiveQualityMode,
    });
    if (etag) {
      responseHeaders.set("ETag", etag);
    }

    eventStatusCode = 200;
    eventBytesServed = objectSize;
    eventCacheStatus = cacheStatus;
    return new Response(responseBody, {
      status: 200,
      headers: responseHeaders,
    });
  } finally {
    const durationMs = Math.max(0, Date.now() - requestStartedAtMs);
    const statusCode = eventStatusCode > 0 ? eventStatusCode : 500;
    const errorCode = String(eventErrorCode || (statusCode >= 400 ? "internal_error" : ""));
    const monitoringEnabled = isTileHotPathMonitoringEnabled(env);
    const telemetryWrite = recordTileRequestEvent(db, {
      created_at: nowIso(),
      created_at_unix: Math.floor(Date.now() / 1000),
      user_id: String(user.id || ""),
      user_email: String(user.email || ""),
      resolve_id: resolveId,
      method: String(request.method || "GET"),
      path,
      folder: eventFolder,
      file_name: eventFileName,
      tile_key: eventTileKey,
      status_code: statusCode,
      bytes_served: eventBytesServed,
      cache_status: eventCacheStatus,
      duration_ms: durationMs,
      cf_ray: cfRay,
      cf_country: cfCountry,
      client_ip: clientIp,
      error_code: errorCode,
    });
    const processSignals = async () => {
      await telemetryWrite;
      if (!monitoringEnabled) {
        return;
      }
      const downloadMonitoringPipeline = async () => {
        if (!(statusCode === 200 && eventBytesServed > 0)) {
          return;
        }
        const monitoringPayload = {
          userId: String(user.id || ""),
          userEmail: String(user.email || ""),
          planCode,
          bytesUsed: eventBytesServed,
          createdAtUnix: Math.floor(Date.now() / 1000),
          ip: clientIp,
          deviceId: String(deviceId || ""),
          country: cfCountry,
        };
        await maybeProcessDownloadMonitoring(db, env, monitoringPayload);
      };
      await Promise.all([
        maybeSignalTileFarmingActivity(db, env, {
          userId: String(user.id || ""),
          userEmail: String(user.email || ""),
          ip: clientIp,
          deviceId: String(deviceId || ""),
          resolveId,
          tileKey: eventTileKey,
          method: String(request.method || "GET"),
          path,
          statusCode,
        }),
        downloadMonitoringPipeline(),
      ]);
    };
    if (ctx && typeof ctx.waitUntil === "function") {
      ctx.waitUntil(processSignals());
    } else {
      await processSignals();
    }
  }
}

function readCookieValue(request, cookieName) {
  const safeName = String(cookieName || "").trim();
  if (!safeName) {
    return "";
  }
  const cookieHeader = String(request.headers.get("Cookie") || "");
  if (!cookieHeader) {
    return "";
  }
  const parts = cookieHeader.split(";");
  for (const part of parts) {
    const [nameRaw, ...rest] = String(part || "").split("=");
    const name = String(nameRaw || "").trim();
    if (name !== safeName) {
      continue;
    }
    return decodeURIComponent(String(rest.join("=") || "").trim());
  }
  return "";
}

function buildAdminSessionCookie(token) {
  const safe = encodeURIComponent(String(token || "").trim());
  return `planetka_admin_token=${safe}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=3600`;
}

function buildAdminSessionClearCookie() {
  return "planetka_admin_token=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0";
}

async function requireAuthenticatedUserContext(request, env, options = {}) {
  const db = requireDb(env);
  const allowCookieToken = parseBooleanFlag(options.allowCookieToken);
  const requireAdmin = parseBooleanFlag(options.requireAdmin);
  const enforceApiKeyDevicePolicy = options.enforceApiKeyDevicePolicy !== false;
  const lightweightAccessClaims = parseBooleanFlag(options.lightweightAccessClaims);
  const canUseLightweightAuthCache = (
    lightweightAccessClaims
    && !requireAdmin
    && !allowCookieToken
    && !enforceApiKeyDevicePolicy
  );
  const bearerToken = readBearerToken(request);
  const authCacheKey = canUseLightweightAuthCache && bearerToken
    ? `lightweight_auth:${bearerToken}`
    : "";

  let access = null;
  let tokenSource = "";
  let bearerError = "";
  const cachedAuth = authCacheKey ? authContextCacheGet(authCacheKey, env) : null;
  if (cachedAuth) {
    access = cachedAuth.access;
    tokenSource = "bearer_cache";
  }
  try {
    if (!access) {
      access = await readBearerUser(request, env);
      if (access) {
        tokenSource = "bearer";
      }
    }
  } catch (error) {
    bearerError = String(error && error.message || "invalid_access_token");
  }
  if (!access && allowCookieToken) {
    const cookieToken = String(readCookieValue(request, "planetka_admin_token") || "").trim();
    if (cookieToken) {
      try {
        const secret = requireSecret(env, "JWT_SIGNING_SECRET");
        const payload = await verifyJwt(cookieToken, secret);
        if (payload.type === "access" && payload.sub) {
          access = payload;
          tokenSource = "admin_cookie";
        } else {
          bearerError = "invalid_access_token";
        }
      } catch (error) {
        bearerError = String(error && error.message || "invalid_access_token");
      }
    }
  }
  if (!access) {
    if (bearerError) {
      return { error: json({ ok: false, error: bearerError }, 401, env) };
    }
    return { error: json({ ok: false, error: "missing_bearer_token" }, 401, env) };
  }

  const authMethod = String(access.auth_method || "").trim().toLowerCase();
  const apiKeyId = String(access.api_key_id || "").trim();
  const deviceId = normalizeDeviceId(
    access.device_id || request.headers.get("X-Planetka-Device-Id") || "",
  );
  const tokenPlanRaw = String(
    access.plan_code || access.user_status || access.plan || access.planCode || access.userStatus || "",
  ).trim();
  const tokenPlanCode = tokenPlanRaw ? normalizeRequestedPlan(tokenPlanRaw) : "";
  if (
    lightweightAccessClaims
    && !requireAdmin
    && tokenPlanCode
  ) {
    if (authCacheKey && tokenSource !== "bearer_cache") {
      authContextCacheSet(
        authCacheKey,
        {
          access,
        },
        env,
      );
    }
    return {
      db,
      user: {
        id: String(access.sub || "").trim(),
        email: String(access.email || "").trim(),
        status: tokenPlanCode,
      },
      access,
      planCode: tokenPlanCode,
      authMethod,
      apiKeyId,
      deviceId,
      devicePolicy: null,
      tokenSource,
    };
  }

  let user = await findUserById(db, access.sub);
  if (!user) {
    return { error: json({ ok: false, error: "user_not_found" }, 404, env) };
  }
  if (isBlockedStatus(user.status)) {
    return { error: blockedAccountResponse(env) };
  }
  user = await enforceUserPlanPolicy(db, user, null, env);
  if (!user) {
    return { error: json({ ok: false, error: "user_not_found" }, 404, env) };
  }
  const planCode = resolvePlanCode(user, null, env);
  let devicePolicy = null;
  if (enforceApiKeyDevicePolicy && authMethod === "api_key" && apiKeyId) {
    const keyUsable = await isApiKeyUsableById(db, apiKeyId, String(user.id || ""));
    if (!keyUsable) {
      return { error: json({ ok: false, error: "api_key_revoked", message: "API key is no longer active." }, 401, env) };
    }
    const provisionalRestricted = isUnconfirmedProvisionalActive(user);
    try {
      devicePolicy = await enforceApiKeyDeviceLimit(
        db,
        apiKeyId,
        String(user.id || ""),
        String(user.email || ""),
        planCode,
        deviceId,
        request,
        env,
      );
    } catch (error) {
      const code = String(error && error.message || "device_limit_exceeded");
      const statusCode = code === "missing_device_id" ? 400 : 429;
      const message = code === "missing_device_id"
        ? "Missing device identifier for API key session."
        : (provisionalRestricted
          ? "This Planetka account can be active on one computer at a time."
          : "This Planetka account can be active on one computer at a time.");
      return { error: json({ ok: false, error: code, message }, statusCode, env) };
    }
  }
  if (requireAdmin && !isAnalyticsAdmin(user, env)) {
    return { error: json({ ok: false, error: "admin_access_required" }, 403, env) };
  }
  return {
    db,
    user,
    access,
    planCode,
    authMethod,
    apiKeyId,
    deviceId,
    devicePolicy,
    tokenSource,
  };
}

async function requireAnalyticsAdmin(request, env) {
  const auth = await requireAuthenticatedUserContext(
    request,
    env,
    { requireAdmin: true, allowCookieToken: true, enforceApiKeyDevicePolicy: false },
  );
  if (auth && auth.error) {
    return auth;
  }
  if (!isPrimaryAnalyticsAdmin(auth && auth.user, env)) {
    return { error: json({ ok: false, error: "primary_admin_required" }, 403, env) };
  }
  return auth;
}

async function handleAdminAnalyticsData(request, env) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user } = auth;
  const windowMinutes = sanitizeAnalyticsMinutes(url.searchParams.get("minutes"), DEFAULT_ANALYTICS_WINDOW_MINUTES);
  const tileMapMinutes = sanitizeLiveTileMapMinutes(
    url.searchParams.get("tile_map_minutes"),
    DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
  );
  const planFilter = parseHeavyUserPlanFilter(url.searchParams.get("plan_filter"));
  try {
    const snapshot = await collectAnalyticsSnapshot(db, windowMinutes, planFilter, tileMapMinutes, env);
    return json(
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
    return json(
      {
        ok: false,
        error: "analytics_data_failed",
        message: publicErrorMessage("Analytics data is temporarily unavailable."),
      },
      500,
      env,
    );
  }
}

async function handleAdminAnalyticsTileMapImage(request, env) {
  const key = String(env.ADMIN_ANALYTICS_TILE_MAP_KEY || DEFAULT_ADMIN_ANALYTICS_TILE_MAP_KEY).trim();
  if (!key) {
    return json({ ok: false, error: "tile_map_key_not_configured" }, 500, env);
  }
  const bucket = env.PLANETKA_DATA;
  if (!bucket) {
    return json({ ok: false, error: "r2_not_bound" }, 500, env);
  }
  const object = await bucket.get(key);
  if (!object || !object.body) {
    return json({ ok: false, error: "tile_map_image_not_found" }, 404, env);
  }
  const headers = {
    ...corsHeaders(env),
    "Content-Type": String(object.httpMetadata && object.httpMetadata.contentType || "image/jpeg"),
    "Cache-Control": "public, max-age=3600",
  };
  return new Response(object.body, { status: 200, headers });
}

async function handleAdminAnalyticsPage(request, env) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { user, tokenSource } = auth;
  let initialSnapshot = null;
  try {
    initialSnapshot = await collectAnalyticsSnapshot(
      auth.db,
      10080,
      "all",
      10,
      env,
    );
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
  const fmtIntLocal = (value) => Number(parseNonNegativeInteger(value, 0)).toLocaleString();
  const fmtGbLocal = (value) => (Number(parseNonNegativeInteger(value, 0)) / BYTES_PER_GB).toFixed(3);
  const fmtFloatLocal = (value, digits = 2) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toFixed(digits) : "0.00";
  };
  const tierCodeFromStatus = (statusValue) => {
    const normalized = normalizePlanCode(statusValue);
    if (normalized === PLAN_CODE_PLANETKA_PRO) return "pro";
    if (normalized === PLAN_CODE_PLANETKA) return "personal";
    return "free";
  };
  const tierLabelFromStatus = (statusValue) => {
    const tierCode = tierCodeFromStatus(statusValue);
    if (tierCode === "pro") return "Commercial";
    if (tierCode === "personal") return "Personal";
    return "Free";
  };
  const tierClassFromStatus = (statusValue) => {
    const tierCode = tierCodeFromStatus(statusValue);
    if (tierCode === "pro") return "tier-pro";
    if (tierCode === "personal") return "tier-personal";
    return "tier-free";
  };
  const tierColorFromStatus = (statusValue) => {
    const tierCode = tierCodeFromStatus(statusValue);
    if (tierCode === "pro") return "#ef4444";
    if (tierCode === "personal") return "#22c55e";
    return "#ffffff";
  };
  const serverActiveUsersRowsHtml = snapshotActiveUsers10m.map((row) => {
    const email = escapeHtml(String(row && row.user_email || ""));
    const tier = tierLabelFromStatus(row && row.user_status);
    const tierClass = tierClassFromStatus(row && row.user_status);
    return `<tr><td class="${tierClass}">${email}</td><td class="${tierClass}">${tier}</td><td>${fmtIntLocal(row && row.request_count)}</td><td>${fmtIntLocal(row && row.resolve_count)}</td><td>${fmtGbLocal(row && row.bytes_served)}</td><td>${escapeHtml(String(row && row.last_seen_at || ""))}</td></tr>`;
  }).join("");
  const serverHeavyRowsHtml = snapshotHeavyUsers.slice(0, 20).map((row) => {
    const email = escapeHtml(String(row && row.user_email || ""));
    const tier = tierLabelFromStatus(row && row.user_status);
    const tierClass = tierClassFromStatus(row && row.user_status);
    const lastSeen = Number.isFinite(Number(row && row.last_event_unix))
      ? new Date(Number(row.last_event_unix) * 1000).toISOString()
      : "";
    const monthBytes = (row && (row.month_bytes ?? row.bytes_served_30d));
    const monthRequests = (row && (row.request_count_month ?? row.request_count_30d));
    return `<tr><td class="${tierClass}">${email}</td><td class="${tierClass}">${tier}</td><td>${fmtIntLocal(row && row.resolve_count)}</td><td>${fmtGbLocal(monthBytes)}</td><td>${fmtIntLocal(monthRequests)}</td><td>${escapeHtml(lastSeen)}</td></tr>`;
  }).join("");
  const billableAvailable = Boolean(snapshotBillable && snapshotBillable.available);
  const billableSource = escapeHtml(
    String(snapshotBillable && snapshotBillable.source || "cloudflare_graphql").replace(/cloudflare/gi, "cloud"),
  );
  const billablePeriodStart = escapeHtml(String(snapshotBillable && snapshotBillable.period_start || ""));
  const billablePeriodEnd = escapeHtml(String(snapshotBillable && snapshotBillable.period_end || ""));
  const billableBucket = escapeHtml(String(snapshotBillable && snapshotBillable.bucket_filter || ""));
  const billableStorageGb = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.storage && snapshotBillable.storage.gb, 3) : "-";
  const billableStorageGbBillable = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.storage && snapshotBillable.storage.billable_gb_rounded, 0) : "-";
  const billableClassAOps = billableAvailable ? fmtIntLocal(snapshotBillable && snapshotBillable.class_a && snapshotBillable.class_a.operations) : "-";
  const billableClassAOpsBillable = billableAvailable ? fmtIntLocal(snapshotBillable && snapshotBillable.class_a && snapshotBillable.class_a.billable_operations) : "-";
  const billableClassBOps = billableAvailable ? fmtIntLocal(snapshotBillable && snapshotBillable.class_b && snapshotBillable.class_b.operations) : "-";
  const billableClassBOpsBillable = billableAvailable ? fmtIntLocal(snapshotBillable && snapshotBillable.class_b && snapshotBillable.class_b.billable_operations) : "-";
  const billableUnknownOps = billableAvailable ? fmtIntLocal(snapshotBillable && snapshotBillable.unknown_operations) : "-";
  const billableCostStorage = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.storage, 2) : "-";
  const billableCostClassA = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.class_a, 2) : "-";
  const billableCostClassB = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.class_b, 2) : "-";
  const billableCostTotal = billableAvailable ? fmtFloatLocal(snapshotBillable && snapshotBillable.estimated_cost_usd && snapshotBillable.estimated_cost_usd.total, 2) : "-";
  const billableStatusText = billableAvailable
    ? (snapshotBillable && snapshotBillable.estimated
      ? `Estimated billable usage from telemetry. Source: ${billableSource}. Period: ${billablePeriodStart} -> ${billablePeriodEnd}`
      : `Cloud GraphQL live data. Source: ${billableSource}. Bucket: ${billableBucket || "all buckets"}. Period: ${billablePeriodStart} -> ${billablePeriodEnd}`)
    : `Cloud billable usage unavailable. ${escapeHtml(String(snapshotBillable && snapshotBillable.message || snapshotBillable && snapshotBillable.reason || "Not configured."))}`;
  const parseLiveMapTile = (tileKey) => {
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
  };
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
      const color = tierColorFromStatus(row && row.user_status);
      const rawD = Number(parsed.d || 1);
      const alpha = Math.max(0.05, Math.min(1, 1 / Math.max(1, rawD)));
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" fill="${color}" fill-opacity="${alpha.toFixed(3)}" stroke="${color}" stroke-width="0.5" stroke-opacity="0.95"></rect>`;
    })
    .filter(Boolean)
    .join("");
  const snapshotGeneratedAt = escapeHtml(String(initialSnapshot && initialSnapshot.generated_at || nowIso()));
  const buildStamp = nowIso();
  const htmlContent = buildAdminAnalyticsPageHtml({
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
            ...corsHeaders(env),
            "Set-Cookie": buildAdminSessionCookie(token),
          },
        });
      }
    }
  }
  return html(htmlContent, 200, env);
}

async function handleAdminAnalyticsUsersPage(request, env) {
  const url = new URL(request.url);
  if (String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim()) {
    return json({ ok: false, error: "query_token_not_allowed" }, 400, env);
  }
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user } = auth;
  const query = String(url.searchParams.get("q") || "").trim();
  const sortBy = parseAnalyticsUsersSort(url.searchParams.get("sort"));
  const sortDir = parseAnalyticsUsersSortDirection(url.searchParams.get("dir"));
  const rows = await listAnalyticsUsers(db, env, {
    query,
    sort_by: sortBy,
    sort_dir: sortDir,
    limit: 5000,
  });
  const fmtIntLocal = (value) => Number(parseNonNegativeInteger(value, 0)).toLocaleString();
  const fmtGbLocal = (value) => (Number(parseNonNegativeInteger(value, 0)) / BYTES_PER_GB).toFixed(3);
  const tierCodeFromStatus = (statusValue) => {
    const normalized = normalizePlanCode(statusValue);
    if (normalized === PLAN_CODE_PLANETKA_PRO) return "pro";
    if (normalized === PLAN_CODE_PLANETKA) return "personal";
    return "free";
  };
  const tierLabelFromStatus = (statusValue) => {
    const tierCode = tierCodeFromStatus(statusValue);
    if (tierCode === "pro") return "Commercial";
    if (tierCode === "personal") return "Personal";
    return "Free";
  };
  const tierClassFromStatus = (statusValue) => {
    const tierCode = tierCodeFromStatus(statusValue);
    if (tierCode === "pro") return "tier-pro";
    if (tierCode === "personal") return "tier-personal";
    return "tier-free";
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
    const planCodeRaw = String(row && row.plan_code || PLAN_CODE_PLANETKA);
    const userId = escapeHtml(userIdRaw);
    const userEmail = escapeHtml(userEmailRaw);
    const planCode = escapeHtml(planCodeRaw);
    const status = String(row && row.user_status || "").trim().toLowerCase();
    const tierClass = tierClassFromStatus(status || planCode);
    const tierLabel = tierLabelFromStatus(status || planCode);
    const throttledUntilRaw = String(row && row.throttled_until || "").trim();
    const throttledUntilMs = Date.parse(throttledUntilRaw);
    const throttledActive = Number.isFinite(throttledUntilMs) && throttledUntilMs > Date.now();
    let actionButtons = "";
    if (status === "blocked") {
      actionButtons = `<button class="action-btn warn" data-action="unblock" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}" data-plan-code="${encodeURIComponent(planCodeRaw)}">Unblock</button><button class="action-btn" data-action="set-free" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Free</button><button class="action-btn" data-action="set-lite" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Personal</button><button class="action-btn" data-action="set-pro" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Commercial</button><button class="action-btn danger" data-action="hard-block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Hard Block</button>`;
    } else {
      const freeButton = `<button class="action-btn" data-action="set-free" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Free</button>`;
      const planButton = tierCodeFromStatus(status || planCode) === "pro"
        ? `<button class="action-btn" data-action="set-lite" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Personal</button>`
        : `<button class="action-btn" data-action="set-pro" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Set Commercial</button>`;
      const throttleButton = throttledActive
        ? `<button class="action-btn" data-action="unthrottle" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Unthrottle</button>`
        : `<button class="action-btn warn" data-action="throttle" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Throttle 24h</button>`;
      actionButtons = `${freeButton}${planButton}${throttleButton}<button class="action-btn danger" data-action="block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Block</button><button class="action-btn danger" data-action="hard-block" data-user-id="${encodeURIComponent(userIdRaw)}" data-user-email="${encodeURIComponent(userEmailRaw)}">Hard Block</button>`;
    }
    return `<tr>
      <td class="${tierClass}">${userEmail}</td>
      <td class="${tierClass}">${escapeHtml(tierLabel)}</td>
      <td>${fmtIntLocal(row && row.resolve_count)}</td>
      <td>${fmtGbLocal(row && row.lifetime_bytes)}</td>
      <td>${fmtGbLocal(row && row.month_bytes)}</td>
      <td>${fmtGbLocal(row && row.week_bytes)}</td>
      <td>${fmtGbLocal(row && row.day_bytes)}</td>
      <td>${fmtGbLocal(row && row.hour_bytes)}</td>
      <td>${escapeHtml(String(row && row.last_seen_at || ""))}</td>
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
    .action-wrap { white-space: nowrap; min-width: 330px; }
    .tier-free { color: #ffffff; font-weight: 600; }
    .tier-personal { color: #22c55e; font-weight: 600; }
    .tier-pro { color: #ef4444; font-weight: 600; }
    .error { color: #fca5a5; }
  </style>
</head>
<body>
  <h1>All users</h1>
  <div class="muted">Signed in as ${escapeHtml(String(user.email || ""))}</div>
  <div class="controls">
    <a href="/admin/analytics" style="color:#93c5fd; text-decoration:none;">Back to analytics</a>
    <a href="/admin/session/logout" style="color:#fca5a5; text-decoration:none;">Sign Out</a>
  </div>
  <form class="controls" method="GET" action="/admin/analytics/users">
    <label for="q">Search user email:</label>
    <input id="q" name="q" type="text" value="${escapeHtml(query)}" placeholder="user@example.com" />
    <input type="hidden" name="sort" value="${escapeHtml(sortBy)}" />
    <input type="hidden" name="dir" value="${escapeHtml(sortDir)}" />
    <button type="submit">Search</button>
    <span class="muted">${fmtIntLocal(Array.isArray(rows) ? rows.length : 0)} users shown</span>
  </form>
  <div id="status" class="muted">Ready</div>
  <table>
    <thead>
      <tr>
        <th>Email</th>
        <th>Plan</th>
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
        unthrottle: "/admin/users/unthrottle",
        throttle: "/admin/users/throttle",
        block: "/admin/users/block",
        unblock: "/admin/users/unblock",
        "set-free": "/admin/users/set-plan",
        "set-lite": "/admin/users/set-plan",
        "set-pro": "/admin/users/set-plan",
        "hard-block": "/admin/users/hard-block",
      };
      const confirmation = {
        unthrottle: "Unthrottle this account now?",
        throttle: "Throttle this account now for 24 hours?",
        block: "Block this user account now?",
        unblock: "Unblock this user account now?",
        "set-free": "Set this account to Free?",
        "set-lite": "Set this account to Personal?",
        "set-pro": "Set this account to Commercial?",
        "hard-block": "Hard block this user and block same-computer attempts?",
      };
      const endpoint = endpointByAction[safeAction];
      if (!endpoint) return;
      if (!window.confirm(confirmation[safeAction] || "Confirm action?")) return;
      const payload = { email: safeUserEmail };
      if (safeUserId) payload.user_id = safeUserId;
      if (safeAction === "throttle") payload.duration_minutes = 1440;
      if (safeAction === "unblock") {
        payload.plan_code = (!safePlanCode || safePlanCode === "blocked") ? "lite" : safePlanCode;
      }
      if (safeAction === "set-free") payload.plan_code = "free";
      if (safeAction === "set-lite") payload.plan_code = "lite";
      if (safeAction === "set-pro") payload.plan_code = "pro";
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
  return html(htmlContent, 200, env);
}

function renderAdminSessionStartPage(env) {
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Admin Session</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b1020; color: #e5e7eb; }
      .card { width: min(92vw, 640px); padding: 24px; border: 1px solid #1f2937; border-radius: 12px; background: #111827; }
      h1 { margin: 0 0 8px; font-size: 22px; }
      p { margin: 8px 0; color: #cbd5e1; }
      .muted { color: #9ca3af; font-size: 13px; }
      input { width: 100%; box-sizing: border-box; background: #0f172a; color: #e5e7eb; border: 1px solid #374151; border-radius: 8px; padding: 10px; margin-top: 10px; }
      button { margin-top: 10px; background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-weight: 600; }
      button[disabled] { opacity: 0.6; cursor: default; }
      .status { margin-top: 12px; font-size: 14px; }
      .ok { color: #86efac; }
      .err { color: #fca5a5; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Start Admin Session</h1>
      <p>Paste admin bearer token and click <strong>Open Analytics</strong>.</p>
      <p class="muted">Tip: one-click link format:<br><code>/admin/session/start#access_token=YOUR_TOKEN</code></p>
      <input id="token" type="password" autocomplete="off" placeholder="Paste bearer token" />
      <button id="startBtn" type="button">Open Analytics</button>
      <div id="status" class="status muted"></div>
    </main>
    <script>
      (function () {
        const tokenInput = document.getElementById("token");
        const startBtn = document.getElementById("startBtn");
        const statusEl = document.getElementById("status");

        function showStatus(message, type) {
          statusEl.textContent = message;
          statusEl.className = "status " + (type || "muted");
        }

        function parseHashToken() {
          const raw = String(window.location.hash || "").replace(/^#/, "");
          if (!raw) return "";
          const params = new URLSearchParams(raw);
          return String(params.get("access_token") || params.get("token") || "").trim();
        }

        async function startSession() {
          const token = String(tokenInput.value || "").trim();
          if (!token) {
            showStatus("Missing token.", "err");
            return;
          }
          startBtn.disabled = true;
          showStatus("Starting admin session...", "muted");
          try {
            const res = await fetch("/admin/session/start", {
              method: "POST",
              headers: { Authorization: "Bearer " + token },
              credentials: "same-origin",
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok || !payload.ok) {
              throw new Error(String((payload && payload.error) || ("HTTP " + res.status)));
            }
            showStatus("Session started. Redirecting...", "ok");
            window.location.href = "/admin/analytics";
          } catch (error) {
            showStatus("Failed to start session: " + String(error && error.message || error), "err");
            startBtn.disabled = false;
          }
        }

        startBtn.addEventListener("click", function () {
          startSession();
        });
        tokenInput.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            event.preventDefault();
            startSession();
          }
        });

        const hashToken = parseHashToken();
        if (hashToken) {
          tokenInput.value = hashToken;
          window.history.replaceState({}, document.title, "/admin/session/start");
          startSession();
        }
      })();
    </script>
  </body>
</html>`;
}

async function handleAdminSessionStartPage(request, env) {
  return html(renderAdminSessionStartPage(env), 200, env);
}

async function handleAdminSessionStart(request, env) {
  const authHeader = String(request.headers.get("Authorization") || "");
  if (!authHeader.startsWith("Bearer ")) {
    return json({ ok: false, error: "missing_bearer_token" }, 401, env);
  }
  const token = authHeader.slice("Bearer ".length).trim();
  if (!token) {
    return json({ ok: false, error: "missing_bearer_token" }, 401, env);
  }
  const auth = await requireAuthenticatedUserContext(
    request,
    env,
    { requireAdmin: true, allowCookieToken: false, enforceApiKeyDevicePolicy: true },
  );
  if (auth.error) {
    return auth.error;
  }
  return jsonWithHeaders(
    {
      ok: true,
      redirect: "/admin/analytics",
    },
    200,
    env,
    {
      "Set-Cookie": buildAdminSessionCookie(token),
    },
  );
}

async function handleAdminSessionLogout(request, env) {
  void request;
  return new Response(null, {
    status: 302,
    headers: {
      Location: "/admin/login",
      "Set-Cookie": buildAdminSessionClearCookie(),
      ...corsHeaders(env),
    },
  });
}

function renderAdminPasswordLoginPage() {
  const defaultEmail = escapeHtml(DEFAULT_ADMIN_LOGIN_EMAIL);
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Admin Login</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b1020; color: #e5e7eb; }
      .card { width: min(92vw, 520px); padding: 24px; border: 1px solid #1f2937; border-radius: 12px; background: #111827; }
      h1 { margin: 0 0 8px; font-size: 22px; }
      p { margin: 8px 0; color: #cbd5e1; }
      input { width: 100%; box-sizing: border-box; background: #0f172a; color: #e5e7eb; border: 1px solid #374151; border-radius: 8px; padding: 10px; margin-top: 10px; }
      button { margin-top: 10px; background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-weight: 600; }
      button[disabled] { opacity: 0.6; cursor: default; }
      .status { margin-top: 12px; font-size: 14px; color: #9ca3af; }
      .ok { color: #86efac; }
      .err { color: #fca5a5; }
      .muted { color: #9ca3af; font-size: 13px; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Admin Login</h1>
      <p>Enter password to open Planetka analytics dashboard.</p>
      <input id="adminEmail" type="email" autocomplete="username" value="${defaultEmail}" placeholder="Admin email" />
      <input id="password" type="password" autocomplete="current-password" placeholder="Password" />
      <button id="loginBtn" type="button">Open Analytics</button>
      <div id="status" class="status"></div>
      <p class="muted">Session stays active for about 1 hour on this browser.</p>
    </main>
    <script>
      (function () {
        const adminEmailInput = document.getElementById("adminEmail");
        const passwordInput = document.getElementById("password");
        const loginBtn = document.getElementById("loginBtn");
        const statusEl = document.getElementById("status");
        function showStatus(message, type) {
          statusEl.textContent = message;
          statusEl.className = "status " + (type || "");
        }
        async function login() {
          const adminEmail = String((adminEmailInput && adminEmailInput.value) || "").trim();
          const password = String(passwordInput.value || "");
          if (!password) {
            showStatus("Missing password.", "err");
            return;
          }
          loginBtn.disabled = true;
          showStatus("Signing in...");
          try {
            const res = await fetch("/admin/login", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "same-origin",
              body: JSON.stringify({ password, admin_email: adminEmail }),
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok || !payload.ok) {
              throw new Error(String((payload && payload.error) || ("HTTP " + res.status)));
            }
            showStatus("Success. Redirecting...", "ok");
            window.location.href = "/admin/analytics";
          } catch (error) {
            showStatus("Login failed: " + String(error && error.message || error), "err");
            loginBtn.disabled = false;
          }
        }
        loginBtn.addEventListener("click", function () { login(); });
        passwordInput.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            event.preventDefault();
            login();
          }
        });
      })();
    </script>
  </body>
</html>`;
}

async function handleAdminLoginPage(request, env) {
  void request;
  return html(renderAdminPasswordLoginPage(), 200, env);
}

async function handleAdminPasswordLogin(request, env) {
  const db = requireDb(env);
  await ensureRateLimitsTable(db);
  const clientIp = requestClientIp(request);
  const rate = await consumeRateLimitWindow(
    db,
    "admin_login_ip",
    clientIp,
    parseRateLimitInteger(env.RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT, DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT),
    parseRateLimitInteger(
      env.RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS,
      DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS,
    ),
  );
  if (!rate.allowed) {
    return rateLimitedResponse(
      env,
      "admin_login_rate_limited",
      "Too many admin login attempts. Please try again later.",
      rate.retryAfterSeconds,
    );
  }

  const body = await parseJson(request);
  const requestedAdminEmail = normalizeEmail(body.admin_email || "");
  const password = String(body.password || "");
  if (!password) {
    return json({ ok: false, error: "missing_password" }, 400, env);
  }
  let valid = false;
  try {
    valid = await verifyAdminDashboardPassword(env, password);
  } catch (error) {
    console.error(
      "planetka.admin.login.verify_failed",
      JSON.stringify({
        error: String(error && error.message || "admin_login_misconfigured"),
      }),
    );
    return json({ ok: false, error: "admin_login_misconfigured" }, 500, env);
  }
  if (!valid) {
    await trackThresholdAlertDb(
      db,
      "admin_login_invalid_spike",
      5,
      300,
      { scope: "ip", ip: clientIp },
    );
    return json({ ok: false, error: "invalid_admin_password" }, 401, env);
  }

  const adminEmail = resolveAdminLoginEmailFromBody(env, requestedAdminEmail);
  if (!adminEmail) {
    return json({ ok: false, error: "admin_login_email_misconfigured" }, 500, env);
  }

  let user = await upsertUserByEmail(
    db,
    adminEmail,
    PLAN_CODE_PLANETKA_PRO,
    { proConfirmedAt: nowIso() },
    env,
  );
  user = await enforceUserPlanPolicy(db, user, null, env);
  if (!user || !isAnalyticsAdmin(user, env)) {
    return json({ ok: false, error: "admin_access_required" }, 403, env);
  }
  const accessToken = await createAccessToken(
    env,
    user,
    null,
    {
      auth_method: "admin_password",
      admin_login: 1,
    },
  );
  return jsonWithHeaders(
    {
      ok: true,
      email: String(user.email || ""),
      redirect: "/admin/analytics",
    },
    200,
    env,
    {
      "Set-Cookie": buildAdminSessionCookie(accessToken),
    },
  );
}

async function resolveDownloadCounterTarget(db, userId, email) {
  const requestedUserId = String(userId || "").trim();
  const requestedEmail = normalizeEmail(email || "");
  if (!requestedUserId && !requestedEmail) {
    return null;
  }
  let counter = requestedUserId ? await findUserDownloadCounter(db, requestedUserId) : null;
  if (!counter && requestedEmail) {
    counter = await findUserDownloadCounterByEmail(db, requestedEmail);
  }
  return counter;
}

async function handleAdminUserUnthrottle(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db } = auth;
  await ensureUserDownloadCountersTable(db);
  const body = await parseJson(request);
  const hasResetHourFlag = Object.prototype.hasOwnProperty.call(body, "reset_hour");
  const resetHour = hasResetHourFlag ? parseBooleanFlag(body.reset_hour) : true;
  const counter = await resolveDownloadCounterTarget(db, body.user_id, body.email);
  if (!counter) {
    return json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  const previousThrottledUntil = String(counter.throttled_until || "").trim();
  const updated = await clearUserDownloadThrottle(db, String(counter.user_id || "").trim(), { resetHour });
  if (!updated) {
    return json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  return json(
    {
      ok: true,
      action: "unthrottle",
      user_id: String(updated.user_id || ""),
      user_email: String(updated.user_email || ""),
      reset_hour: resetHour,
      previous_throttled_until: previousThrottledUntil || null,
      throttled_until: String(updated.throttled_until || "").trim() || null,
      hour_bytes: clampNonNegativeInt(updated.hour_bytes),
      hour_bucket_start_unix: clampNonNegativeInt(updated.hour_bucket_start_unix),
      updated_at: String(updated.updated_at || nowIso()),
    },
    200,
    env,
  );
}

async function handleAdminUserThrottle(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db } = auth;
  await ensureUserDownloadCountersTable(db);
  const body = await parseJson(request);
  const hasResetHourFlag = Object.prototype.hasOwnProperty.call(body, "reset_hour");
  const resetHour = hasResetHourFlag ? parseBooleanFlag(body.reset_hour) : false;
  const durationMinutes = Math.max(
    1,
    parseNonNegativeInteger(body.duration_minutes, DEFAULT_DOWNLOAD_THROTTLE_DURATION_MINUTES),
  );
  const counter = await resolveDownloadCounterTarget(db, body.user_id, body.email);
  if (!counter) {
    return json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  const updated = await setUserDownloadThrottle(
    db,
    String(counter.user_id || "").trim(),
    { durationMinutes, resetHour },
  );
  if (!updated) {
    return json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  return json(
    {
      ok: true,
      action: "throttle",
      user_id: String(updated.user_id || ""),
      user_email: String(updated.user_email || ""),
      duration_minutes: durationMinutes,
      reset_hour: resetHour,
      throttled_until: String(updated.throttled_until || "").trim() || null,
      hour_bytes: clampNonNegativeInt(updated.hour_bytes),
      hour_bucket_start_unix: clampNonNegativeInt(updated.hour_bucket_start_unix),
      updated_at: String(updated.updated_at || nowIso()),
    },
    200,
    env,
  );
}

async function handleAdminUserBlock(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await ensureApiKeyTables(db);
  await ensureRefreshSessionColumns(db);
  await ensureUserProvisionalColumns(db);
  await ensureUserDownloadCountersTable(db);
  const body = await parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }
  let targetUser = requestedUserId ? await findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }
  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = normalizeEmail(targetUser.email || "");
  const now = nowIso();
  await dbRun(
    db,
    `
      UPDATE users
      SET
        status = 'blocked',
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = NULL
      WHERE id = ?
    `,
    [targetUserId],
  );
  const revokedKeysResult = await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        status = 'revoked',
        revoked_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [now, targetUserId],
  );
  const revokedSessionsResult = await dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [now, targetUserId],
  );
  const updatedCounter = await clearUserDownloadThrottle(db, targetUserId, { resetHour: true });
  try {
    console.log(
      "admin.user_blocked",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        admin_email: normalizeEmail(adminUser && adminUser.email || ""),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
  return json(
    {
      ok: true,
      action: "block_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: "blocked",
      revoked_api_keys: dbMetaChanges(revokedKeysResult),
      revoked_sessions: dbMetaChanges(revokedSessionsResult),
      throttled_until: String(updatedCounter && updatedCounter.throttled_until || "").trim() || null,
      updated_at: String(updatedCounter && updatedCounter.updated_at || now),
    },
    200,
    env,
  );
}

async function handleAdminUserUnblock(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await ensureApiKeyTables(db);
  await ensureRefreshSessionColumns(db);
  await ensureUserProvisionalColumns(db);
  await ensureUserDownloadCountersTable(db);
  await ensureAdminHardBlocksTable(db);
  const body = await parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }
  let targetUser = requestedUserId ? await findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }
  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = normalizeEmail(targetUser.email || "");
  const targetPlan = normalizeRequestedPlan(body.plan_code || PLAN_CODE_PLANETKA);
  const now = nowIso();
  const proConfirmedAt = isPaidRequestedPlan(targetPlan) ? now : null;
  await dbRun(
    db,
    `
      UPDATE users
      SET
        status = ?,
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = ?
      WHERE id = ?
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  const apiKeysResult = await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        provisional = 0,
        provisional_expires_at = NULL,
        confirmed_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  await dbRun(
    db,
    `
      UPDATE user_download_counters
      SET plan_code = ?, updated_at = ?
      WHERE user_id = ?
    `,
    [targetPlan, now, targetUserId],
  );
  const hardBlocksClearedResult = await dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET
        active = 0
      WHERE
        active = 1
        AND (
          source_user_id = ?
          OR LOWER(COALESCE(source_user_email, '')) = ?
          OR LOWER(COALESCE(blocked_email, '')) = ?
        )
    `,
    [targetUserId, targetEmail, targetEmail],
  );
  const updatedCounter = await clearUserDownloadThrottle(db, targetUserId, { resetHour: true });
  try {
    console.log(
      "admin.user_unblocked",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        plan_code: targetPlan,
        admin_email: normalizeEmail(adminUser && adminUser.email || ""),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
  return json(
    {
      ok: true,
      action: "unblock_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: targetPlan,
      updated_active_api_keys: dbMetaChanges(apiKeysResult),
      hard_blocks_cleared: dbMetaChanges(hardBlocksClearedResult),
      throttled_until: String(updatedCounter && updatedCounter.throttled_until || "").trim() || null,
      updated_at: String(updatedCounter && updatedCounter.updated_at || now),
    },
    200,
    env,
  );
}

async function handleAdminUserHardBlock(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await ensureApiKeyTables(db);
  await ensureRefreshSessionColumns(db);
  await ensureUserProvisionalColumns(db);
  await ensureUserDownloadCountersTable(db);
  await ensureAdminHardBlocksTable(db);

  const body = await parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }

  let targetUser = requestedUserId ? await findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }

  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = normalizeEmail(targetUser.email || "");
  const now = nowIso();

  // Block the account itself (same behavior as manual block).
  await dbRun(
    db,
    `
      UPDATE users
      SET
        status = 'blocked',
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = NULL
      WHERE id = ?
    `,
    [targetUserId],
  );
  const revokedKeysResult = await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        status = 'revoked',
        revoked_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [now, targetUserId],
  );
  const revokedSessionsResult = await dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [now, targetUserId],
  );

  const counter = await findUserDownloadCounter(db, targetUserId);
  const fallbackRequest = await dbGet(
    db,
    `
      SELECT request_device_id, request_ip
      FROM api_key_requests
      WHERE LOWER(email) = ?
      ORDER BY created_at DESC
      LIMIT 1
    `,
    [targetEmail],
  );
  const blockedDeviceId = normalizeDeviceId(
    String(counter && counter.last_device_id || "") || String(fallbackRequest && fallbackRequest.request_device_id || ""),
  );
  const blockedIp = String(counter && counter.last_ip || "").trim() || String(fallbackRequest && fallbackRequest.request_ip || "").trim();
  const reason = String(body.reason || "manual_admin_hard_block").trim().slice(0, 160) || "manual_admin_hard_block";
  await dbRun(
    db,
    `
      INSERT INTO admin_hard_blocks (
        id,
        blocked_email,
        blocked_device_id,
        blocked_ip,
        source_user_id,
        source_user_email,
        reason,
        created_by,
        created_at,
        active
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    `,
    [
      crypto.randomUUID(),
      targetEmail || null,
      blockedDeviceId || null,
      blockedIp || null,
      targetUserId || null,
      targetEmail || null,
      reason,
      normalizeEmail(adminUser && adminUser.email || "") || null,
      now,
    ],
  );
  const updatedCounter = await clearUserDownloadThrottle(db, targetUserId, { resetHour: true });
  return json(
    {
      ok: true,
      action: "hard_block_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: "blocked",
      blocked_device_id: blockedDeviceId || null,
      blocked_ip: blockedIp || null,
      revoked_api_keys: dbMetaChanges(revokedKeysResult),
      revoked_sessions: dbMetaChanges(revokedSessionsResult),
      throttled_until: String(updatedCounter && updatedCounter.throttled_until || "").trim() || null,
      updated_at: String(updatedCounter && updatedCounter.updated_at || now),
    },
    200,
    env,
  );
}

async function handleAdminUserSetPlan(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await ensureApiKeyTables(db);
  await ensureRefreshSessionColumns(db);
  await ensureUserProvisionalColumns(db);
  await ensureUserDownloadCountersTable(db);

  const body = await parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }

  let targetUser = requestedUserId ? await findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }

  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = normalizeEmail(targetUser.email || "");
  const targetPlan = normalizeRequestedPlan(body.plan_code || PLAN_CODE_PLANETKA);
  const now = nowIso();
  const proConfirmedAt = isPaidRequestedPlan(targetPlan) ? now : null;

  await dbRun(
    db,
    `
      UPDATE users
      SET
        status = ?,
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = ?
      WHERE id = ?
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  const apiKeysResult = await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        provisional = 0,
        provisional_expires_at = NULL,
        confirmed_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  await dbRun(
    db,
    `
      UPDATE user_download_counters
      SET plan_code = ?, updated_at = ?
      WHERE user_id = ?
    `,
    [targetPlan, now, targetUserId],
  );

  try {
    console.log(
      "admin.user_set_plan",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        plan_code: targetPlan,
        admin_email: normalizeEmail(adminUser && adminUser.email || ""),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }

  return json(
    {
      ok: true,
      action: "set_plan",
      user_id: targetUserId,
      user_email: targetEmail,
      plan_code: targetPlan,
      updated_active_api_keys: dbMetaChanges(apiKeysResult),
      updated_at: now,
    },
    200,
    env,
  );
}

function sanitizeAttachmentFileName(value, fallback = "planetka_bug_report.json") {
  const raw = String(value || "").trim();
  const safe = raw.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
  if (!safe) {
    return fallback;
  }
  return safe.toLowerCase().endsWith(".json") ? safe : `${safe}.json`;
}

function sanitizeImageAttachmentFileName(value, fallback = "planetka_bug_screenshot.png") {
  const raw = String(value || "").trim();
  const safe = raw.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
  const candidate = safe || fallback;
  const lower = candidate.toLowerCase();
  if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".webp")) {
    return candidate;
  }
  return fallback;
}

function normalizeBugReportImageMime(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "image/png" || normalized === "image/jpeg" || normalized === "image/webp") {
    return normalized;
  }
  return "";
}

function base64DecodeToBytes(value) {
  const compact = String(value || "").replace(/\s+/g, "");
  if (!compact) {
    return new Uint8Array();
  }
  const binary = atob(compact);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index) & 0xff;
  }
  return bytes;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function handleSupportBugReport(request, env) {
  const auth = await requireAuthenticatedUserContext(
    request,
    env,
    { enforceApiKeyDevicePolicy: true },
  );
  if (auth.error) {
    return auth.error;
  }
  const { db, user } = auth;

  const body = await parseJson(request);
  const reportJson = String(body.report_json || "").trim();
  if (!reportJson) {
    return json({ ok: false, error: "missing_report_json" }, 400, env);
  }
  if (reportJson.length > 500000) {
    return json({ ok: false, error: "report_json_too_large" }, 413, env);
  }
  try {
    JSON.parse(reportJson);
  } catch (_error) {
    return json({ ok: false, error: "invalid_report_json" }, 400, env);
  }

  const reportFileName = sanitizeAttachmentFileName(body.report_filename, "planetka_bug_report.json");
  const issueWhat = String(body.issue_what_happened || "").trim();
  const issueSteps = String(body.issue_steps_to_reproduce || "").trim();
  const issueExpected = String(body.issue_expected_behavior || "").trim();
  const sourcePath = String(body.report_path || "").trim();
  const attachmentBase64 = String(body.attachment_base64 || "").trim();
  let imageAttachment = null;
  if (attachmentBase64) {
    const mime = normalizeBugReportImageMime(body.attachment_mime);
    if (!mime) {
      return json({ ok: false, error: "invalid_attachment_mime" }, 400, env);
    }
    let imageBytes;
    try {
      imageBytes = base64DecodeToBytes(attachmentBase64);
    } catch (_error) {
      return json({ ok: false, error: "invalid_attachment_base64" }, 400, env);
    }
    if (!imageBytes || imageBytes.length <= 0) {
      return json({ ok: false, error: "empty_attachment" }, 400, env);
    }
    if (imageBytes.length > BUG_REPORT_IMAGE_MAX_BYTES) {
      return json({ ok: false, error: "attachment_too_large" }, 413, env);
    }
    imageAttachment = {
      filename: sanitizeImageAttachmentFileName(body.attachment_filename, "planetka_bug_screenshot.png"),
      contentType: mime,
      content: base64EncodeBytes(imageBytes),
      sizeBytes: imageBytes.length,
    };
  }

  const apiKey = requireSecret(env, "EMAIL_API_KEY");
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const to = String(env.BUG_REPORT_EMAIL || env.SECURITY_ALERT_EMAIL || "info@planetka.io").trim() || "info@planetka.io";
  const sentAt = nowIso();
  const reporterEmail = String(user.email || "").trim();

  const textBody = [
    "Planetka bug report submitted from Blender.",
    "",
    `reported_at_utc=${sentAt}`,
    `reporter_email=${reporterEmail || "unknown"}`,
    `reporter_user_id=${String(user.id || "")}`,
    `report_file_name=${reportFileName}`,
    `local_report_path=${sourcePath || "n/a"}`,
    "",
    "Issue description:",
    `- What happened: ${issueWhat || "(not provided)"}`,
    `- Steps to reproduce: ${issueSteps || "(not provided)"}`,
    `- Expected behavior: ${issueExpected || "(not provided)"}`,
    `- Screenshot attached: ${imageAttachment ? "yes" : "no"}`,
    ...(imageAttachment ? [`- Screenshot file: ${imageAttachment.filename} (${imageAttachment.sizeBytes} bytes)`] : []),
    "",
    "Attached: JSON debug report",
    ...(imageAttachment ? ["Attached: Screenshot/image"] : []),
  ].join("\n");

  const htmlBody = `
    <div style="font-family:Arial,sans-serif;line-height:1.5;color:#111827;">
      <h2 style="margin:0 0 12px 0;">Planetka Bug Report</h2>
      <p><strong>Reported at (UTC):</strong> ${escapeHtml(sentAt)}<br/>
      <strong>Reporter email:</strong> ${escapeHtml(reporterEmail || "unknown")}<br/>
      <strong>User ID:</strong> ${escapeHtml(String(user.id || ""))}<br/>
      <strong>Report file:</strong> ${escapeHtml(reportFileName)}<br/>
      <strong>Local report path:</strong> ${escapeHtml(sourcePath || "n/a")}</p>
      <h3 style="margin:16px 0 8px 0;">Issue Description</h3>
      <p><strong>What happened:</strong> ${escapeHtml(issueWhat || "(not provided)")}<br/>
      <strong>Steps to reproduce:</strong> ${escapeHtml(issueSteps || "(not provided)")}<br/>
      <strong>Expected behavior:</strong> ${escapeHtml(issueExpected || "(not provided)")}<br/>
      <strong>Screenshot attached:</strong> ${imageAttachment ? "yes" : "no"}${imageAttachment ? `<br/><strong>Screenshot file:</strong> ${escapeHtml(imageAttachment.filename)} (${imageAttachment.sizeBytes} bytes)` : ""}</p>
      <p>Attached: JSON debug report</p>
      ${imageAttachment ? "<p>Attached: Screenshot/image</p>" : ""}
    </div>
  `;

  const attachments = [
    {
      filename: reportFileName,
      content: base64EncodeString(reportJson),
    },
  ];
  if (imageAttachment) {
    attachments.push({
      filename: imageAttachment.filename,
      content: imageAttachment.content,
      contentType: imageAttachment.contentType,
    });
  }

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject: `Planetka Bug Report - ${reporterEmail || "unknown"}`,
      text: textBody,
      html: htmlBody,
      attachments,
    }),
  });

  if (!response.ok) {
    const resendBody = await response.text();
    return json(
      {
        ok: false,
        error: `bug_report_email_failed_${response.status}`,
        detail: String(resendBody || "").slice(0, 500),
      },
      502,
      env,
    );
  }

  return json(
    {
      ok: true,
      sent: true,
      reporter_email: reporterEmail,
      report_file_name: reportFileName,
      image_attachment: Boolean(imageAttachment),
    },
    200,
    env,
  );
}

async function applyHostedStreamingAccessEntitlement(db, env, details = {}) {
  const email = normalizeEmail(details.email || "");
  if (!email) {
    throw new Error("missing_customer_email");
  }
  const now = nowIso();
  const existingUser = await findUserByEmail(db, email);
  const existingExpiryMs = Date.parse(String(existingUser && existingUser.pro_access_expires_at || "").trim());
  const entitlementStartMs = Number.isFinite(existingExpiryMs) && existingExpiryMs > Date.now()
    ? existingExpiryMs
    : Date.now();
  const requestedPlan = normalizeRequestedPlan(details.planCode || PLAN_CODE_PLANETKA_PRO);
  void requestedPlan;
  const planCode = PLAN_CODE_PLANETKA_PRO;
  const accessExpiresAt = computeHostedStreamingAccessExpiryIso(env, entitlementStartMs);
  let user = await upsertUserByEmail(
    db,
    email,
    planCode,
    {
      proConfirmedAt: now,
      proAccessExpiresAt: accessExpiresAt,
      provisionalPlanCode: "",
      provisionalExpiresAt: "",
    },
    env,
  );
  user = await enforceUserPlanPolicy(db, user, null, env);
  await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        expires_at = NULL,
        provisional = 0,
        provisional_expires_at = NULL,
        confirmed_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [planCode, now, String(user && user.id || "").trim()],
  );
  return {
    user,
    planCode,
    accessExpiresAt,
  };
}

async function applyPermanentLicenseEntitlement(db, env, details = {}) {
  const email = normalizeEmail(details.email || "");
  if (!email) {
    throw new Error("missing_customer_email");
  }
  const requestedPlan = normalizeRequestedPlan(details.planCode || PLAN_CODE_PLANETKA);
  if (!requestedPlan) {
    throw new Error("missing_plan_code");
  }
  const now = nowIso();
  const existingUser = await findUserByEmail(db, email);
  const existingStatus = normalizeUserStatus(existingUser && existingUser.status);
  const finalPlan = (
    requestedPlan === PLAN_CODE_PLANETKA
    && existingStatus === PLAN_CODE_PLANETKA_PRO
  )
    ? PLAN_CODE_PLANETKA_PRO
    : requestedPlan;
  const proConfirmedAt = finalPlan === PLAN_CODE_PLANETKA_PRO ? now : "";

  let user = await upsertUserByEmail(
    db,
    email,
    finalPlan,
    {
      proConfirmedAt,
      proAccessExpiresAt: "",
      provisionalPlanCode: "",
      provisionalExpiresAt: "",
    },
    env,
  );
  user = await enforceUserPlanPolicy(db, user, null, env);
  if (!user || !user.id) {
    throw new Error("user_upsert_failed");
  }

  await dbRun(
    db,
    `
      UPDATE users
      SET
        pro_access_expires_at = NULL,
        pro_confirmed_at = CASE WHEN ? != '' THEN ? ELSE pro_confirmed_at END
      WHERE id = ?
    `,
    [proConfirmedAt, proConfirmedAt, String(user.id || "").trim()],
  );
  await dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        expires_at = NULL,
        provisional = 0,
        provisional_expires_at = NULL,
        confirmed_at = CASE WHEN ? != '' THEN ? ELSE confirmed_at END
      WHERE user_id = ?
        AND status = 'active'
    `,
    [finalPlan, proConfirmedAt, proConfirmedAt, String(user.id || "").trim()],
  );
  await dbRun(
    db,
    `
      UPDATE user_download_counters
      SET plan_code = ?, updated_at = ?
      WHERE user_id = ?
    `,
    [finalPlan, now, String(user.id || "").trim()],
  );

  return {
    user,
    planCode: finalPlan,
  };
}

async function handleStripeWebhook(request, env) {
  const db = requireDb(env);
  await ensureStripeWebhookEventsTable(db);
  const rawBody = await request.text();
  const event = await verifyStripeWebhook(request, env, rawBody);
  const claimedEvent = await claimStripeWebhookEvent(db, event);
  const eventType = String(event.type || "");
  const eventId = String(claimedEvent.eventId || "").trim();
  if (!eventId) {
    return json({ ok: false, error: "missing_stripe_event_id" }, 400, env);
  }
  if (!claimedEvent.inserted) {
    console.log("stripe.webhook.duplicate", JSON.stringify({ event_type: eventType, event_id: eventId }));
    return json(
      {
        ok: true,
        ignored: true,
        reason: "duplicate_event",
        event_type: eventType,
        event_id: eventId,
      },
      200,
      env,
    );
  }
  console.log("stripe.webhook.received", JSON.stringify({ event_type: eventType, event_id: eventId }));

  if (eventType !== "checkout.session.completed") {
    console.log("stripe.webhook.ignored", JSON.stringify({ event_type: eventType }));
    return json({ ok: true, ignored: true, event_type: eventType }, 200, env);
  }

  const session = event.data && event.data.object ? event.data.object : null;
  if (!session) {
    return json({ ok: false, error: "missing_checkout_session" }, 400, env);
  }
  const sessionId = String(session.id || "").trim();
  if (!sessionId) {
    return json({ ok: false, error: "missing_checkout_session_id" }, 400, env);
  }
  const email = normalizeEmail(
    session.customer_details && session.customer_details.email
      ? session.customer_details.email
      : session.customer_email,
  );
  if (!email) {
    console.error("stripe.webhook.missing_email", JSON.stringify({ event_type: eventType }));
    return json({ ok: false, error: "missing_customer_email" }, 400, env);
  }
  const paymentStatus = String(session.payment_status || "").trim().toLowerCase();
  const paidCheckout = paymentStatus === "paid" || paymentStatus === "no_payment_required";
  if (!paidCheckout) {
    console.log(
      "stripe.webhook.ignored_unpaid_checkout",
      JSON.stringify({ event_type: eventType, email, payment_status: paymentStatus }),
    );
    return json(
      {
        ok: true,
        ignored: true,
        reason: "unpaid_checkout_session",
        event_type: eventType,
        email,
        payment_status: paymentStatus,
      },
      200,
      env,
    );
  }

  const lineItems = await fetchStripeCheckoutSessionLineItems(env, sessionId);
  const planEntitlement = resolveStripePlanEntitlement(lineItems, env);
  if (planEntitlement.planCode) {
    let existingPlanCode = PLAN_CODE_PLANETKA_FREE;
    const existingUser = await findUserByEmail(db, email);
    if (existingUser && !isBlockedStatus(existingUser.status)) {
      const enforcedUser = await enforceUserPlanPolicy(db, existingUser, null, env);
      existingPlanCode = normalizeRequestedPlan(resolvePlanCode(enforcedUser, null, env));
    }
    const purchaseGuard = evaluateStripePlanPurchaseGuard(existingPlanCode, planEntitlement.planCode);
    if (purchaseGuard.blocked) {
      const refund = await createStripeRefundForCheckoutSession(
        env,
        session,
        {
          reason: purchaseGuard.reason,
          existingPlanCode: purchaseGuard.existingPlanCode,
          requestedPlanCode: purchaseGuard.requestedPlanCode,
        },
      );
      console.log(
        "stripe.webhook.ignored_existing_licence",
        JSON.stringify({
          event_type: eventType,
          email,
          session_id: sessionId,
          reason: purchaseGuard.reason,
          existing_plan: purchaseGuard.existingPlanCode,
          requested_plan: purchaseGuard.requestedPlanCode,
          refund_attempted: refund.attempted,
          refund_status: refund.status,
          refund_id: refund.refundId,
          refund_error: refund.error || "",
          matched: planEntitlement.matched.slice(0, 50),
        }),
      );
      return json(
        {
          ok: true,
          ignored: true,
          reason: purchaseGuard.reason,
          event_type: eventType,
          email,
          existing_plan_code: purchaseGuard.existingPlanCode,
          requested_plan_code: purchaseGuard.requestedPlanCode,
          message: `This email already has ${planDisplayName(purchaseGuard.existingPlanCode)}.`,
          refund_attempted: refund.attempted,
          refund_status: refund.status,
          refund_id: refund.refundId,
        },
        200,
        env,
      );
    }
    const applied = await applyPermanentLicenseEntitlement(
      db,
      env,
      {
        email,
        planCode: planEntitlement.planCode,
      },
    );
    console.log(
      "stripe.webhook.plan_entitlement_processed",
      JSON.stringify({
        event_type: eventType,
        email,
        session_id: sessionId,
        requested_plan: planEntitlement.planCode,
        applied_plan: applied.planCode,
        matched: planEntitlement.matched.slice(0, 50),
      }),
    );
    return json(
      {
        ok: true,
        processed: true,
        event_type: eventType,
        email,
        plan_code: applied.planCode,
      },
      200,
      env,
    );
  }
  console.log(
    "stripe.webhook.ignored_no_plan_mapping",
    JSON.stringify({
      event_type: eventType,
      email,
      session_id: sessionId,
    }),
  );
  return json(
    {
      ok: true,
      ignored: true,
      reason: "no_plan_mapping",
      event_type: eventType,
      email,
    },
    200,
    env,
  );
}

function normalizeAddonUpdateVersion(value, fallback = DEFAULT_ADDON_UPDATE_MANIFEST_VERSION) {
  const text = String(value || "").trim();
  if (!text) {
    return String(fallback || "").trim() || DEFAULT_ADDON_UPDATE_MANIFEST_VERSION;
  }
  return text;
}

function parseAddonUpdateSha256(value) {
  const token = String(value || "").trim().toLowerCase();
  if (!token) {
    return "";
  }
  if (/^[a-f0-9]{64}$/.test(token)) {
    return token;
  }
  return "";
}

async function handleAddonUpdateManifest(request, env) {
  const localVersion = normalizeAddonUpdateVersion(
    env.ADDON_UPDATE_VERSION || env.EXTENSION_VERSION || env.ADDON_VERSION,
    DEFAULT_ADDON_UPDATE_MANIFEST_VERSION,
  );
  const channel = String(env.ADDON_UPDATE_CHANNEL || DEFAULT_ADDON_UPDATE_CHANNEL).trim().toLowerCase() || DEFAULT_ADDON_UPDATE_CHANNEL;
  const downloadUrl = String(env.ADDON_UPDATE_DOWNLOAD_URL || "").trim();
  const sha256 = parseAddonUpdateSha256(env.ADDON_UPDATE_SHA256);
  const releaseNotesUrl = String(env.ADDON_UPDATE_RELEASE_NOTES_URL || DEFAULT_ADDON_UPDATE_RELEASE_NOTES_URL).trim();
  const minBlenderVersion = String(env.ADDON_UPDATE_MIN_BLENDER || "4.5.7").trim();
  const publishedAt = String(env.ADDON_UPDATE_PUBLISHED_AT || "").trim() || nowIso();
  const mandatory = String(env.ADDON_UPDATE_MANDATORY || "").trim().toLowerCase() === "true";
  const maxAge = Math.max(
    30,
    parseNonNegativeInteger(env.ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS, DEFAULT_ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS),
  );

  const payload = {
    ok: true,
    addon_id: ADDON_ID,
    channel,
    version: localVersion,
    download_url: downloadUrl,
    sha256,
    release_notes_url: releaseNotesUrl,
    min_blender_version: minBlenderVersion,
    mandatory,
    published_at: publishedAt,
    available: Boolean(downloadUrl),
  };

  if (request.method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: {
        ...corsHeaders(env),
        "Cache-Control": `public, max-age=${maxAge}`,
      },
    });
  }

  return jsonWithHeaders(payload, 200, env, {
    "Cache-Control": `public, max-age=${maxAge}`,
  });
}

function magicLinkAuthDisabledResponse(env) {
  return json({ ok: false, error: "magic_link_auth_disabled" }, 404, env);
}

async function routeHealth(env) {
  const magicLinkEnabled = isMagicLinkAuthEnabled(env);
  return json(
    {
      ok: true,
      service: "planetka-api",
      api_base_url: env.API_BASE_URL || "https://api.planetka.io",
      login_url: env.LOGIN_URL || "https://www.planetka.io/login",
      device_login_url: magicLinkEnabled
        ? `${env.API_BASE_URL || "https://api.planetka.io"}/device/login`
        : "",
      magic_link_auth_enabled: magicLinkEnabled,
      db_bound: Boolean(env.DB),
      r2_bound: Boolean(env.PLANETKA_DATA),
    },
    200,
    env,
  );
}

function routeApiKeyPage(request, env) {
  if (request.method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: {
        ...corsHeaders(env),
        "Content-Type": "text/html; charset=utf-8",
      },
    });
  }
  return renderApiKeyRequestPage(env, "", PLAN_CODE_PLANETKA);
}

async function dispatchExactRoute(request, env, path) {
  switch (path) {
    case "/health":
      if (request.method === "GET") {
        return routeHealth(env);
      }
      return null;
    case "/addon/update-manifest":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleAddonUpdateManifest(request, env);
      }
      return null;
    case "/api-key":
      if (request.method === "GET" || request.method === "HEAD") {
        return routeApiKeyPage(request, env);
      }
      return null;
    case "/api-key/activate":
      if (request.method === "GET") {
        return await handleApiKeyActivatePage(request, env);
      }
      return null;
    case "/auth/start":
      if (request.method === "POST") {
        if (!isMagicLinkAuthEnabled(env)) {
          return magicLinkAuthDisabledResponse(env);
        }
        return await handleAuthStart(request, env);
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
    case "/auth/verify":
      if (request.method === "POST") {
        if (!isMagicLinkAuthEnabled(env)) {
          return magicLinkAuthDisabledResponse(env);
        }
        return await handleAuthVerify(request, env);
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
        return await handleTileSessionStart(request, env);
      }
      return null;
    case "/device/start":
      if (request.method === "POST") {
        if (!isMagicLinkAuthEnabled(env)) {
          return magicLinkAuthDisabledResponse(env);
        }
        return await handleDeviceStart(request, env);
      }
      return null;
    case "/device/poll":
      if (request.method === "POST") {
        if (!isMagicLinkAuthEnabled(env)) {
          return magicLinkAuthDisabledResponse(env);
        }
        return await handleDevicePoll(request, env);
      }
      return null;
    case "/device/login":
      if (request.method === "GET") {
        if (!isMagicLinkAuthEnabled(env)) {
          return magicLinkAuthDisabledResponse(env);
        }
        return await handleDeviceLoginPage(request, env);
      }
      return null;
    case "/support/bug-report":
      if (request.method === "POST") {
        return await handleSupportBugReport(request, env);
      }
      return null;
    case "/admin/analytics":
      if (request.method === "GET") {
        return await handleAdminAnalyticsPage(request, env);
      }
      return null;
    case "/admin/analytics/users":
      if (request.method === "GET") {
        return await handleAdminAnalyticsUsersPage(request, env);
      }
      return null;
    case "/admin/analytics/data":
      if (request.method === "GET") {
        return await handleAdminAnalyticsData(request, env);
      }
      return null;
    case "/admin/analytics/world-map.jpg":
      if (request.method === "GET") {
        return await handleAdminAnalyticsTileMapImage(request, env);
      }
      return null;
    case "/admin/login":
      if (request.method === "GET") {
        return await handleAdminLoginPage(request, env);
      }
      if (request.method === "POST") {
        return await handleAdminPasswordLogin(request, env);
      }
      return null;
    case "/admin/session/start":
      if (request.method === "GET") {
        return await handleAdminSessionStartPage(request, env);
      }
      if (request.method === "POST") {
        return await handleAdminSessionStart(request, env);
      }
      return null;
    case "/admin/session/logout":
      if (request.method === "GET") {
        return await handleAdminSessionLogout(request, env);
      }
      return null;
    case "/admin/users/unthrottle":
      if (request.method === "POST") {
        return await handleAdminUserUnthrottle(request, env);
      }
      return null;
    case "/admin/users/throttle":
      if (request.method === "POST") {
        return await handleAdminUserThrottle(request, env);
      }
      return null;
    case "/admin/users/block":
      if (request.method === "POST") {
        return await handleAdminUserBlock(request, env);
      }
      return null;
    case "/admin/users/unblock":
      if (request.method === "POST") {
        return await handleAdminUserUnblock(request, env);
      }
      return null;
    case "/admin/users/hard-block":
      if (request.method === "POST") {
        return await handleAdminUserHardBlock(request, env);
      }
      return null;
    case "/admin/users/set-plan":
      if (request.method === "POST") {
        return await handleAdminUserSetPlan(request, env);
      }
      return null;
    case "/stripe/webhook":
      if (request.method === "POST") {
        return await handleStripeWebhook(request, env);
      }
      return null;
    default:
      return null;
  }
}

async function dispatchPrefixRoute(request, env, path, ctx) {
  if ((request.method === "GET" || request.method === "HEAD") && path.startsWith("/legal/")) {
    return await handleLegalDocumentRequest(request, env, path);
  }
  if ((request.method === "GET" || request.method === "HEAD") && path.startsWith("/tiles/")) {
    return await handleTileRequest(request, env, path, ctx);
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
      if (path.startsWith("/admin/") && queryToken) {
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
