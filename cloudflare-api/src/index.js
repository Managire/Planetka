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
  PLAN_CODE_PERSONAL,
  PLAN_CODE_FREE,
  PLAN_CODE_COMMERCIAL,
  commercialUseAllowed,
  isBlockedStatus,
  isDeviceLimitExemptEmail,
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
  readBearerUser,
  readBearerToken,
  requireAnalyticsAdmin,
  requireAuthenticatedUserContext,
} from "./worker/auth_session.js";
import {
  handleAdminAnalyticsData as handleAdminAnalyticsDataRoute,
  handleAdminAnalyticsPage as handleAdminAnalyticsPageRoute,
  handleAdminAnalyticsProductsPage as handleAdminAnalyticsProductsPageRoute,
  handleAdminSetPricingSettings as handleAdminSetPricingSettingsRoute,
  handleAdminSetProductDiscount as handleAdminSetProductDiscountRoute,
  handleAdminAnalyticsTileMapImage as handleAdminAnalyticsTileMapImageRoute,
  handleAdminAnalyticsUserPage as handleAdminAnalyticsUserPageRoute,
  handleAdminAnalyticsUsersPage as handleAdminAnalyticsUsersPageRoute,
} from "./worker/admin_analytics_handlers.js";
import {
  collectAnalyticsSnapshot as collectAnalyticsSnapshotQuery,
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
  handleAdminUserBlock as handleAdminUserBlockRoute,
  handleAdminSetGlobalUnrestrictedQuality as handleAdminSetGlobalUnrestrictedQualityRoute,
  handleAdminUserHardBlock as handleAdminUserHardBlockRoute,
  handleAdminUserReleasePreviewHold as handleAdminUserReleasePreviewHoldRoute,
  handleAdminUserSetPreviewHold as handleAdminUserSetPreviewHoldRoute,
  handleAdminQaAuthReset as handleAdminQaAuthResetRoute,
  handleAdminUserSetPlan as handleAdminUserSetPlanRoute,
  handleAdminUserSetUnrestrictedQuality as handleAdminUserSetUnrestrictedQualityRoute,
  handleAdminUserUnblock as handleAdminUserUnblockRoute,
} from "./worker/admin_user_handlers.js";
import {
  handleCreditCheckout as handleCreditCheckoutRoute,
  handleCreditEstimate as handleCreditEstimateRoute,
  handleCreditMe as handleCreditMeRoute,
  handleCreditPaymentCancelled as handleCreditPaymentCancelledRoute,
  handleCreditPaymentSuccess as handleCreditPaymentSuccessRoute,
  handleCreditPurchaseHistory as handleCreditPurchaseHistoryRoute,
  handleCreditLicencedDownloadReport as handleCreditLicencedDownloadReportRoute,
  handleCreditSceneDetailLink as handleCreditSceneDetailLinkRoute,
  handleCreditSceneMap as handleCreditSceneMapRoute,
  handleCreditRegionPackDetailLink as handleCreditRegionPackDetailLinkRoute,
  handleCreditRegionPackCatalogAsset as handleCreditRegionPackCatalogAssetRoute,
  handleCreditRegionPackCatalog as handleCreditRegionPackCatalogRoute,
  handleCreditRegionPackCheckoutFromToken as handleCreditRegionPackCheckoutFromTokenRoute,
  handleCreditRegionPackMap as handleCreditRegionPackMapRoute,
  handleCreditRegionPackMapAsset as handleCreditRegionPackMapAssetRoute,
  handleCreditRegionPackMapBackground as handleCreditRegionPackMapBackgroundRoute,
  handleCreditRegionPackPageAsset as handleCreditRegionPackPageAssetRoute,
  handleCreditRegionOffers as handleCreditRegionOffersRoute,
  handleCreditRegionPackRelatedOffers as handleCreditRegionPackRelatedOffersRoute,
  handleCreditUnlocked as handleCreditUnlockedRoute,
  getRuntimePricingSettings,
  listRegionProductPricingRows,
  setRegionProductDiscountOverride,
  setRuntimePricingSettings,
} from "./worker/credit_routes.js";
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
  createAuthCore,
} from "./worker/auth_core.js";
import {
  createAuthApiKeyHandlers,
} from "./worker/auth_api_key_handlers.js";
import {
  createAuthSessionRouteHandlers,
} from "./worker/auth_session_route_handlers.js";
import {
  runScheduledMaintenanceJobs,
} from "./worker/maintenance_jobs.js";
import {
  handleTileRequest as handleTileRequestRoute,
  handleTileSessionStart as handleTileSessionStartRoute,
} from "./worker/tile_routes.js";
import {
  handleTileEventQueueBatch,
} from "./worker/tile_event_queue.js";
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
const DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_LIMIT = 30;
const DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_LIMIT = 60;
const DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS = 60;
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
const DEFAULT_PREVIEW_FAIR_USAGE_ALERT_GB = 15;
const DEFAULT_PREVIEW_FAIR_USAGE_STRICT_FACTOR = 0.5;
const DEFAULT_PREVIEW_FAIR_USAGE_NEW_USER_DAYS = 7;
const DEFAULT_PREVIEW_D004_UNIQUE_ALERT_THRESHOLD = 100;
const DEFAULT_PREVIEW_D004_UNIQUE_ALERT_WINDOW_SECONDS = 300;
const DEFAULT_PREVIEW_FAIR_USAGE_ALERT_EMAIL_COOLDOWN_SECONDS = 3600;
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
const DEFAULT_ANALYTICS_REVENUE_EXCLUDED_EMAIL_PATTERNS = "tom.griger@gmail.com,info@planetka.io,free@planetka.io,personal@planetka.io,commercial@planetka.io,credits@planetka.io";
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
let userQualityAccessColumnsReady = false;
let adminFeatureFlagsTableReady = false;
const FIXED_INTERNAL_TEST_PLAN_BY_EMAIL = Object.freeze({
  "free@planetka.io": PLAN_CODE_FREE,
  "personal@planetka.io": PLAN_CODE_PERSONAL,
  "commercial@planetka.io": PLAN_CODE_COMMERCIAL,
});
let adminHardBlocksTableReady = false;
let newsletterContactsTableReady = false;
let creditTablesReady = false;
let rateLimitsLastPruneAt = 0;
let authContextCache = new Map();

const ANALYTICS_QUERY_DEPS = {
  ALLOWED_LIVE_TILE_MAP_WINDOW_MINUTES,
  BYTES_PER_GB,
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
  MAX_ANALYTICS_WINDOW_MINUTES,
  PLAN_CODE_PERSONAL,
  PLAN_CODE_FREE,
  PLAN_CODE_COMMERCIAL,
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
  publicErrorMessage,
  startOfDayUnix,
  startOfHourUnix,
  startOfWeekUnix,
};

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
  normalizeTierCodeStrict,
  normalizeRequestedPlan,
  parseBooleanFlag,
  requireDb,
  requireSecret,
  resolvePlanCode,
  resolveUserQualityAccessState,
  verifyJwt,
};

const ADMIN_ANALYTICS_DEPS = {
  buildAdminSessionCookie,
  buildAnalyticsUsersSnapshot: (db, env) => buildAnalyticsUsersSnapshot(db, env, ADMIN_ANALYTICS_DEPS),
  collectAnalyticsSnapshot: (db, minutes, planFilter, liveTileMapWindowMinutes, env) =>
    collectAnalyticsSnapshotQuery(db, minutes, planFilter, liveTileMapWindowMinutes, env, ANALYTICS_QUERY_DEPS),
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
  PLAN_CODE_PERSONAL,
  PLAN_CODE_FREE,
  PLAN_CODE_COMMERCIAL,
  publicErrorMessage,
  requireAnalyticsAdmin: (request, env) => requireAnalyticsAdmin(request, env, AUTH_SESSION_DEPS),
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
  ensureCreditTables,
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
  PLAN_CODE_COMMERCIAL,
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
  issueApiKeyForUser,
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
  resolveUserQualityAccessState,
  resolveFixedInternalPlanForEmail,
  setGlobalUnrestrictedQualityEnabled,
  requireAnalyticsAdmin: (request, env) => requireAnalyticsAdmin(request, env, AUTH_SESSION_DEPS),
  sha256Hex,
  upsertUserByEmail,
};

const BILLING_DEPS = {
  dbRun,
  ensureCreditTables,
  ensureStripeWebhookEventsTable,
  findUserById,
  findUserByEmail,
  hmacSha256Hex,
  invalidateAnalyticsSnapshots,
  json,
  normalizeEmail,
  normalizeQualityMode,
  nowIso,
  parsePositiveNumber,
  requireDb,
  requireSecret,
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
  PLAN_CODE_PERSONAL,
  PLAN_CODE_FREE,
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
  addDaysFromIso,
  consumeRateLimitWindow,
  countRowsFromQuery,
  dbGet,
  dbMetaChanges,
  dbRun,
  dbTableExists,
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

function isTileEventQueueProducerEnabled(env = {}) {
  const raw = env.ENABLE_TILE_EVENT_QUEUE_PRODUCER;
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    // Default off: direct D1 telemetry path remains active without Queue billable ops.
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

function previewFairUsageBlockedResponse(env, message = "Preview streaming is temporarily paused for this account while usage is reviewed.") {
  return json(
    {
      ok: false,
      error: "preview_fair_usage_hold",
      message,
    },
    403,
    env,
  );
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
        quality_mode TEXT,
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
  const eventPragma = await db.prepare(`PRAGMA table_info(tile_request_events)`).all();
  const eventRows = Array.isArray(eventPragma && eventPragma.results) ? eventPragma.results : [];
  const eventColumnNames = new Set(eventRows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  if (!eventColumnNames.has("quality_mode")) {
    try {
      await dbRun(db, `ALTER TABLE tile_request_events ADD COLUMN quality_mode TEXT`);
    } catch (error) {
      const message = String(error && error.message || "").toLowerCase();
      if (!message.includes("duplicate column")) {
        throw error;
      }
    }
  }
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
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_request_events_user_quality_created ON tile_request_events(user_id, quality_mode, created_at_unix DESC)`,
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
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS tile_request_rollup_hourly_account_quality (
        bucket_start_unix INTEGER NOT NULL,
        bucket_start TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        quality_mode TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        bytes_served INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        cache_hit_count INTEGER NOT NULL DEFAULT 0,
        tagged_request_count INTEGER NOT NULL DEFAULT 0,
        last_event_unix INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (bucket_start_unix, user_id, quality_mode)
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_rollup_hourly_quality_user ON tile_request_rollup_hourly_account_quality(user_id, quality_mode, bucket_start_unix DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS tile_request_rollup_daily_account_quality (
        day_start_unix INTEGER NOT NULL,
        day_start TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        quality_mode TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        bytes_served INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        cache_hit_count INTEGER NOT NULL DEFAULT 0,
        tagged_request_count INTEGER NOT NULL DEFAULT 0,
        last_event_unix INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day_start_unix, user_id, quality_mode)
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_rollup_daily_quality_user ON tile_request_rollup_daily_account_quality(user_id, quality_mode, day_start_unix DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS preview_usage_hourly_account (
        bucket_start_unix INTEGER NOT NULL,
        bucket_start TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        bytes_served INTEGER NOT NULL DEFAULT 0,
        d004_unique_count INTEGER NOT NULL DEFAULT 0,
        alert_sent_at TEXT,
        last_event_unix INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (bucket_start_unix, user_id)
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_preview_usage_hourly_user ON preview_usage_hourly_account(user_id, bucket_start_unix DESC)`,
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
  const qualityMode = normalizeQualityMode(payload.quality_mode || payload.qualityMode || "");

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

  await dbRun(
    db,
    `
      INSERT INTO tile_request_rollup_hourly_account_quality (
        bucket_start_unix,
        bucket_start,
        user_id,
        user_email,
        quality_mode,
        request_count,
        bytes_served,
        error_count,
        cache_hit_count,
        tagged_request_count,
        last_event_unix
      ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
      ON CONFLICT(bucket_start_unix, user_id, quality_mode) DO UPDATE SET
        user_email = excluded.user_email,
        request_count = tile_request_rollup_hourly_account_quality.request_count + 1,
        bytes_served = tile_request_rollup_hourly_account_quality.bytes_served + excluded.bytes_served,
        error_count = tile_request_rollup_hourly_account_quality.error_count + excluded.error_count,
        cache_hit_count = tile_request_rollup_hourly_account_quality.cache_hit_count + excluded.cache_hit_count,
        tagged_request_count = tile_request_rollup_hourly_account_quality.tagged_request_count + excluded.tagged_request_count,
        last_event_unix = CASE
          WHEN excluded.last_event_unix > tile_request_rollup_hourly_account_quality.last_event_unix
            THEN excluded.last_event_unix
          ELSE tile_request_rollup_hourly_account_quality.last_event_unix
        END
    `,
    [bucketHour, bucketHourIso, userId, userEmail, qualityMode, bytesServed, errorCount, cacheHitCount, taggedRequest, createdAtUnix],
  );

  await dbRun(
    db,
    `
      INSERT INTO tile_request_rollup_daily_account_quality (
        day_start_unix,
        day_start,
        user_id,
        user_email,
        quality_mode,
        request_count,
        bytes_served,
        error_count,
        cache_hit_count,
        tagged_request_count,
        last_event_unix
      ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
      ON CONFLICT(day_start_unix, user_id, quality_mode) DO UPDATE SET
        user_email = excluded.user_email,
        request_count = tile_request_rollup_daily_account_quality.request_count + 1,
        bytes_served = tile_request_rollup_daily_account_quality.bytes_served + excluded.bytes_served,
        error_count = tile_request_rollup_daily_account_quality.error_count + excluded.error_count,
        cache_hit_count = tile_request_rollup_daily_account_quality.cache_hit_count + excluded.cache_hit_count,
        tagged_request_count = tile_request_rollup_daily_account_quality.tagged_request_count + excluded.tagged_request_count,
        last_event_unix = CASE
          WHEN excluded.last_event_unix > tile_request_rollup_daily_account_quality.last_event_unix
            THEN excluded.last_event_unix
          ELSE tile_request_rollup_daily_account_quality.last_event_unix
        END
    `,
    [bucketDay, bucketDayIso, userId, userEmail, qualityMode, bytesServed, errorCount, cacheHitCount, taggedRequest, createdAtUnix],
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
          quality_mode,
          status_code,
          bytes_served,
          cache_status,
          duration_ms,
          cf_ray,
          cf_country,
          client_ip,
          error_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        normalizeQualityMode(payload.quality_mode || payload.qualityMode || ""),
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
      quality_mode: normalizeQualityMode(payload.quality_mode || payload.qualityMode || ""),
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

function previewFairUsageUserMessage() {
  return "Preview streaming is temporarily paused for this account while usage is reviewed. Full Quality licenced data and account access remain available.";
}

function previewFairUsageIsHeld(user) {
  return Boolean(String(user && user.preview_fair_usage_hold_at || "").trim());
}

async function getPreviewFairUsageHoldForUser(db, userId) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return {
      held: false,
      hold_at: "",
      reason: "",
      message: previewFairUsageUserMessage(),
    };
  }
  const user = await findUserById(db, safeUserId);
  const holdAt = String(user && user.preview_fair_usage_hold_at || "").trim();
  return {
    held: Boolean(holdAt),
    hold_at: holdAt,
    reason: String(user && user.preview_fair_usage_hold_reason || "").trim(),
    details_json: String(user && user.preview_fair_usage_hold_details_json || "").trim(),
    message: previewFairUsageUserMessage(),
  };
}

function previewStrictFactor(env = {}) {
  const factor = parsePositiveNumber(
    env.PREVIEW_FAIR_USAGE_STRICT_FACTOR,
    DEFAULT_PREVIEW_FAIR_USAGE_STRICT_FACTOR,
  );
  return Math.min(1, Math.max(0.05, factor));
}

function parseDFromTileKey(value) {
  const match = /_d(\d{3})/i.exec(String(value || ""));
  if (!match) {
    return 0;
  }
  return parseNonNegativeInteger(match[1], 0);
}

function userAgeDays(user) {
  const createdAt = Date.parse(String(user && user.created_at || ""));
  if (!Number.isFinite(createdAt) || createdAt <= 0) {
    return Number.POSITIVE_INFINITY;
  }
  return Math.max(0, (Date.now() - createdAt) / 86400000);
}

async function userHasStripePaidActivity(db, userId) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return false;
  }
  await ensureCreditTables(db);
  const row = await dbGet(
    db,
    `
      SELECT COUNT(*) AS count
      FROM credit_ledger
      WHERE user_id = ?
        AND LOWER(COALESCE(reason, '')) IN ('stripe_scene_purchase', 'stripe_region_pack_purchase')
    `,
    [safeUserId],
  );
  return clampNonNegativeInt(row && row.count) > 0;
}

async function previewFairUsageThresholdsForUser(db, env, userId) {
  const safeUserId = String(userId || "").trim();
  const baseGb = parsePositiveNumber(
    env.PREVIEW_FAIR_USAGE_ALERT_GB || env.PREVIEW_FAIR_USAGE_HOLD_GB,
    DEFAULT_PREVIEW_FAIR_USAGE_ALERT_GB,
  );
  const baseD004 = parseRateLimitInteger(
    env.PREVIEW_D004_UNIQUE_ALERT_THRESHOLD || env.PREVIEW_D004_UNIQUE_HOLD_THRESHOLD,
    DEFAULT_PREVIEW_D004_UNIQUE_ALERT_THRESHOLD,
  );
  const newUserDays = parsePositiveNumber(
    env.PREVIEW_FAIR_USAGE_NEW_USER_DAYS,
    DEFAULT_PREVIEW_FAIR_USAGE_NEW_USER_DAYS,
  );
  const user = safeUserId ? await findUserById(db, safeUserId) : null;
  const hasPaid = await userHasStripePaidActivity(db, safeUserId);
  const isNew = user ? userAgeDays(user) < newUserDays : true;
  const strict = Boolean(!hasPaid || isNew);
  const factor = strict ? previewStrictFactor(env) : 1;
  return {
    strict,
    has_paid: Boolean(hasPaid),
    is_new: Boolean(isNew),
    hourly_bytes: toBytesFromGb(baseGb * factor),
    hourly_gb: baseGb * factor,
    d004_unique_threshold: Math.max(1, Math.floor(baseD004 * factor)),
    d004_window_seconds: Math.max(
      60,
      parseRateLimitInteger(
        env.PREVIEW_D004_UNIQUE_ALERT_WINDOW_SECONDS || env.PREVIEW_D004_UNIQUE_HOLD_WINDOW_SECONDS,
        DEFAULT_PREVIEW_D004_UNIQUE_ALERT_WINDOW_SECONDS,
      ),
    ),
  };
}

async function sendPreviewFairUsageThresholdAlert(db, env, details = {}) {
  const userId = String(details.user_id || details.userId || "").trim();
  const userEmail = normalizeEmail(details.user_email || details.userEmail || "");
  const reason = String(details.reason || "preview_fair_usage_threshold").trim().slice(0, 160) || "preview_fair_usage_threshold";
  const cooldownSeconds = Math.max(
    60,
    parseRateLimitInteger(
      env.PREVIEW_FAIR_USAGE_ALERT_EMAIL_COOLDOWN_SECONDS,
      DEFAULT_PREVIEW_FAIR_USAGE_ALERT_EMAIL_COOLDOWN_SECONDS,
    ),
  );
  await ensureRateLimitsTable(db);
  const alertGate = await consumeRateLimitWindow(
    db,
    "preview_fair_usage_alert_mail",
    `${userId || userEmail || "unknown"}:${reason}`,
    1,
    cooldownSeconds,
  );
  if (!alertGate.allowed) {
    return { alerted: false, cooldown: true };
  }
  try {
    await sendOpsAlertEmail(
      env,
      "Planetka Preview fair usage threshold reached",
      [
        "Preview usage crossed a monitoring threshold. User access was not changed.",
        `reason=${reason}`,
        `user_id=${userId}`,
        `email=${userEmail}`,
        `bytes_this_hour=${clampNonNegativeInt(details.bytes_this_hour)}`,
        `hourly_threshold_bytes=${clampNonNegativeInt(details.hourly_threshold_bytes)}`,
        `hourly_threshold_gb=${Number(details.hourly_threshold_gb || 0)}`,
        `d004_unique_count=${clampNonNegativeInt(details.d004_unique_count)}`,
        `d004_unique_threshold=${clampNonNegativeInt(details.d004_unique_threshold)}`,
        `d004_window_seconds=${clampNonNegativeInt(details.d004_window_seconds)}`,
        `strict_threshold=${Boolean(details.strict_threshold)}`,
        `has_paid=${Boolean(details.has_paid)}`,
        `is_new=${Boolean(details.is_new)}`,
      ],
    );
    return { alerted: true, cooldown: false };
  } catch (error) {
    console.warn(
      "worker.preview_fair_usage_alert_email_failed",
      JSON.stringify({
        user_id: userId,
        email: userEmail,
        reason,
        error: String(error && error.message || "preview_fair_usage_alert_email_failed"),
      }),
    );
    return { alerted: false, error: String(error && error.message || "preview_fair_usage_alert_email_failed") };
  }
}

async function recordPreviewUsageAndMaybeAlert(db, env, payload = {}) {
  const qualityMode = normalizeQualityMode(payload.quality_mode || payload.qualityMode || "");
  const method = String(payload.method || "GET").trim().toUpperCase();
  const statusCode = parseNonNegativeInteger(payload.status_code, 0);
  const userId = String(payload.user_id || "").trim();
  const userEmail = normalizeEmail(payload.user_email || "");
  const bytesServed = clampNonNegativeInt(payload.bytes_served);
  if (qualityMode !== "preview" || method !== "GET" || statusCode !== 200 || !userId || bytesServed <= 0) {
    return { alerted: false };
  }

  await ensureTileRequestRollupTables(db);
  await ensureUserQualityAccessColumns(db);
  const createdAtUnix = parseNonNegativeInteger(payload.created_at_unix, Math.floor(Date.now() / 1000));
  const bucketHour = startOfHourUnix(createdAtUnix);
  const bucketHourIso = new Date(bucketHour * 1000).toISOString();
  const tileKey = String(payload.tile_key || "").trim();
  const dValue = parseDFromTileKey(tileKey);
  let d004UniqueCount = 0;
  const thresholds = await previewFairUsageThresholdsForUser(db, env, userId);
  if (dValue === 4) {
    const seen = await consumeRateLimitWindow(
      db,
      "preview_d004_tile_seen",
      `${userId}:${tileKey}`,
      2147483647,
      thresholds.d004_window_seconds,
    );
    if (clampNonNegativeInt(seen && seen.count) === 1) {
      const unique = await consumeRateLimitWindow(
        db,
        "preview_d004_unique",
        userId,
        2147483647,
        thresholds.d004_window_seconds,
      );
      d004UniqueCount = clampNonNegativeInt(unique && unique.count);
    }
  }

  const usageRow = await dbGet(
    db,
    `
      INSERT INTO preview_usage_hourly_account (
        bucket_start_unix,
        bucket_start,
        user_id,
        user_email,
        request_count,
        bytes_served,
        d004_unique_count,
        last_event_unix
      ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
      ON CONFLICT(bucket_start_unix, user_id) DO UPDATE SET
        user_email = excluded.user_email,
        request_count = preview_usage_hourly_account.request_count + 1,
        bytes_served = preview_usage_hourly_account.bytes_served + excluded.bytes_served,
        d004_unique_count = CASE
          WHEN excluded.d004_unique_count > preview_usage_hourly_account.d004_unique_count
            THEN excluded.d004_unique_count
          ELSE preview_usage_hourly_account.d004_unique_count
        END,
        last_event_unix = CASE
          WHEN excluded.last_event_unix > preview_usage_hourly_account.last_event_unix
            THEN excluded.last_event_unix
          ELSE preview_usage_hourly_account.last_event_unix
        END
      RETURNING bytes_served, d004_unique_count
    `,
    [bucketHour, bucketHourIso, userId, userEmail, bytesServed, d004UniqueCount, createdAtUnix],
  );
  const hourBytes = clampNonNegativeInt(usageRow && usageRow.bytes_served);
  const hourD004Unique = Math.max(d004UniqueCount, clampNonNegativeInt(usageRow && usageRow.d004_unique_count));

  if (hourBytes > thresholds.hourly_bytes) {
    return await sendPreviewFairUsageThresholdAlert(db, env, {
      reason: "preview_hourly_bytes_limit",
      user_id: userId,
      user_email: userEmail,
      bytes_this_hour: hourBytes,
      hourly_threshold_bytes: thresholds.hourly_bytes,
      hourly_threshold_gb: thresholds.hourly_gb,
      strict_threshold: thresholds.strict,
      has_paid: thresholds.has_paid,
      is_new: thresholds.is_new,
    });
  }
  if (hourD004Unique > thresholds.d004_unique_threshold) {
    return await sendPreviewFairUsageThresholdAlert(db, env, {
      reason: "preview_d004_unique_tile_limit",
      user_id: userId,
      user_email: userEmail,
      d004_unique_count: hourD004Unique,
      d004_unique_threshold: thresholds.d004_unique_threshold,
      d004_window_seconds: thresholds.d004_window_seconds,
      strict_threshold: thresholds.strict,
      has_paid: thresholds.has_paid,
      is_new: thresholds.is_new,
    });
  }
  return { alerted: false };
}

async function countRowsFromQuery(db, sql, bindings = []) {
  const row = await dbGet(db, sql, bindings);
  return clampNonNegativeInt(row && (row.count ?? row.total ?? 0));
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

async function buildAccountState(db, user, env) {
  const qualityAccess = await resolveUserQualityAccessState(db, user, env);
  const previewFairUsageHold = await getPreviewFairUsageHoldForUser(db, user && user.id);
  const storedPlanCode = normalizeTierCodeStrict(qualityAccess.storedPlanCode);
  if (!storedPlanCode) {
    throw new Error("invalid_user_status");
  }
  const storedAccountTier = storedPlanCode;
  return {
    planCode: storedPlanCode,
    storedPlanCode,
    accountTier: storedAccountTier,
    storedAccountTier,
    qualityAccessPlanCode: qualityAccess.qualityAccessPlanCode,
    unrestrictedQualityAccess: Boolean(qualityAccess.unrestrictedQualityAccess),
    unrestrictedQualityOverride: String(qualityAccess.overrideMode || "normal"),
    commercialUseAllowed: commercialUseAllowed(storedPlanCode),
    upgradeUrl: String(env.UPGRADE_URL || DEFAULT_UPGRADE_URL).trim() || DEFAULT_UPGRADE_URL,
    contactUrl: normalizeContactUrl(env.PLANETKA_CONTACT_URL || DEFAULT_CONTACT_URL),
    previewFairUsageHold,
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
    plan: {
      code: planCode || "",
    },
    plan_code: planCode || "",
    account_tier: tier || "",
    stored_plan_code: storedPlanCode || "",
    stored_account_tier: storedTier || "",
    quality_access_plan_code: qualityAccessPlanCode || "",
    unrestricted_quality_access: Boolean(safeState.unrestrictedQualityAccess),
    unrestricted_quality_override: String(safeState.unrestrictedQualityOverride || "normal"),
    commercial_use_allowed: Boolean(safeState.commercialUseAllowed),
    upgrade_url: safeState.upgradeUrl,
    contact_url: safeState.contactUrl,
    preview_fair_usage_hold: safeState.previewFairUsageHold || { held: false },
    previewFairUsageHold: safeState.previewFairUsageHold || { held: false },
  };
}

async function findUserByEmail(db, email) {
  await ensureUserQualityAccessColumns(db);
  return dbGet(
    db,
    `
      SELECT
        u.id,
        u.email,
        u.status,
        u.unrestricted_quality_override,
        u.preview_fair_usage_hold_at,
        u.preview_fair_usage_hold_reason,
        u.preview_fair_usage_hold_details_json,
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
  await ensureUserQualityAccessColumns(db);
  return dbGet(
    db,
    `
      SELECT
        u.id,
        u.email,
        u.status,
        u.unrestricted_quality_override,
        u.preview_fair_usage_hold_at,
        u.preview_fair_usage_hold_reason,
        u.preview_fair_usage_hold_details_json,
        u.created_at,
        u.last_login_at
      FROM users u
      WHERE u.id = ?
      LIMIT 1
    `,
    [userId],
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
        opted_in_at TEXT NOT NULL,
        last_opt_in_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_newsletter_contacts_last_opt_in ON newsletter_contacts(last_opt_in_at DESC)`,
  );
  newsletterContactsTableReady = true;
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
        received_at TEXT NOT NULL,
        processing_status TEXT NOT NULL DEFAULT 'processing',
        processed_at TEXT,
        last_attempt_at TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT
      )
    `,
  );
  for (const statement of [
    `ALTER TABLE stripe_webhook_events ADD COLUMN processing_status TEXT NOT NULL DEFAULT 'processing'`,
    `ALTER TABLE stripe_webhook_events ADD COLUMN processed_at TEXT`,
    `ALTER TABLE stripe_webhook_events ADD COLUMN last_attempt_at TEXT`,
    `ALTER TABLE stripe_webhook_events ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0`,
    `ALTER TABLE stripe_webhook_events ADD COLUMN error_message TEXT`,
  ]) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      const message = String(error && error.message || "").toLowerCase();
      if (!message.includes("duplicate column")) {
        throw error;
      }
    }
  }
  await dbRun(
    db,
    `
      UPDATE stripe_webhook_events
      SET
        processing_status = 'processed',
        processed_at = COALESCE(processed_at, received_at),
        last_attempt_at = COALESCE(last_attempt_at, received_at),
        attempt_count = CASE
          WHEN COALESCE(attempt_count, 0) <= 0 THEN 1
          ELSE attempt_count
        END
      WHERE processing_status IS NULL OR TRIM(processing_status) = ''
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_stripe_webhook_events_received_at ON stripe_webhook_events(received_at DESC)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_stripe_webhook_events_status ON stripe_webhook_events(processing_status, received_at DESC)`,
  );
  stripeWebhookEventsTableReady = true;
}

async function recordNewsletterOptIn(db, email, source = "unknown") {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail || !normalizedEmail.includes("@")) {
    return;
  }
  await ensureNewsletterContactsTable(db);
  const now = nowIso();
  await dbRun(
    db,
    `
      INSERT INTO newsletter_contacts (
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
        plan_code TEXT NOT NULL DEFAULT 'free',
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

async function ensureCreditTables(db) {
  if (creditTablesReady) {
    return;
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_credit_accounts (
        user_id TEXT PRIMARY KEY,
        account_type TEXT NOT NULL DEFAULT 'standard',
        world_full_quality_unlocked_at TEXT,
        world_full_quality_checkout_session_id TEXT,
        world_full_quality_paid_eur REAL NOT NULL DEFAULT 0,
        pricing_version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `,
  );
  try {
    await dbRun(db, `ALTER TABLE user_credit_accounts ADD COLUMN account_type TEXT NOT NULL DEFAULT 'standard'`);
  } catch (error) {
    const message = String(error && error.message || "").toLowerCase();
    if (!message.includes("duplicate column")) {
      throw error;
    }
  }
  for (const statement of [
    `ALTER TABLE user_credit_accounts ADD COLUMN world_full_quality_unlocked_at TEXT`,
    `ALTER TABLE user_credit_accounts ADD COLUMN world_full_quality_checkout_session_id TEXT`,
    `ALTER TABLE user_credit_accounts ADD COLUMN world_full_quality_paid_eur REAL NOT NULL DEFAULT 0`,
    `ALTER TABLE user_credit_accounts ADD COLUMN pricing_version INTEGER NOT NULL DEFAULT 0`,
  ]) {
    try {
      await dbRun(db, statement);
    } catch (error) {
      const message = String(error && error.message || "").toLowerCase();
      if (!message.includes("duplicate column")) {
        throw error;
      }
    }
  }
  await dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET account_type = 'standard'
      WHERE account_type IS NULL OR TRIM(account_type) = ''
    `,
  );
  try {
    await dbRun(
      db,
      `
        INSERT OR IGNORE INTO user_credit_accounts (
          user_id, account_type, created_at, updated_at
        )
        SELECT id, 'standard', ?, ?
        FROM users
        WHERE id IS NOT NULL AND TRIM(id) != ''
      `,
      [nowIso(), nowIso()],
    );
  } catch (error) {
    const message = String(error && error.message || "").toLowerCase();
    if (!message.includes("no such table")) {
      throw error;
    }
  }
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_tile_entitlements (
        user_id TEXT NOT NULL,
        tile_key TEXT NOT NULL,
        quality_mode TEXT NOT NULL DEFAULT 'full',
        credits_spent REAL NOT NULL DEFAULT 0,
        land_km2 REAL NOT NULL DEFAULT 0,
        billable_land_km2 REAL NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'client_pricing',
        unlocked_at TEXT NOT NULL,
        PRIMARY KEY (user_id, tile_key)
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_user_tile_entitlements_user_unlocked ON user_tile_entitlements(user_id, unlocked_at DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_entitlement_summaries (
        user_id TEXT PRIMARY KEY,
        version TEXT NOT NULL,
        rows_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS credit_ledger (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        amount_eur REAL NOT NULL DEFAULT 0,
        reason TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_created ON credit_ledger(user_id, created_at DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS purchase_history (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        user_email TEXT,
        purchase_type TEXT NOT NULL,
        stripe_session_id TEXT,
        stripe_payment_intent_id TEXT,
        currency TEXT NOT NULL DEFAULT 'eur',
        amount_paid_eur REAL NOT NULL DEFAULT 0,
        nominal_eur REAL NOT NULL DEFAULT 0,
        gross_eur REAL NOT NULL DEFAULT 0,
        discount_eur REAL NOT NULL DEFAULT 0,
        discount_percent INTEGER NOT NULL DEFAULT 0,
        quality_mode TEXT,
        region_pack_id TEXT,
        region_pack_name TEXT,
        region_pack_type TEXT,
        catalog_version TEXT,
        tile_count_total INTEGER NOT NULL DEFAULT 0,
        tile_count_new INTEGER NOT NULL DEFAULT 0,
        tile_count_already_licenced INTEGER NOT NULL DEFAULT 0,
        metadata_json TEXT,
        created_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_history_stripe_session ON purchase_history(stripe_session_id) WHERE stripe_session_id IS NOT NULL AND stripe_session_id != ''`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_purchase_history_user_created ON purchase_history(user_id, created_at DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS purchase_history_tiles (
        purchase_id TEXT NOT NULL,
        tile_key TEXT NOT NULL,
        tile_status TEXT NOT NULL DEFAULT 'new',
        price_eur REAL NOT NULL DEFAULT 0,
        gross_price_eur REAL NOT NULL DEFAULT 0,
        land_km2 REAL NOT NULL DEFAULT 0,
        billable_land_km2 REAL NOT NULL DEFAULT 0,
        quality_mode TEXT NOT NULL DEFAULT 'full',
        created_at TEXT NOT NULL,
        PRIMARY KEY (purchase_id, tile_key)
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_purchase_history_tiles_tile ON purchase_history_tiles(tile_key)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_licenced_download_stats (
        user_id TEXT PRIMARY KEY,
        total_downloaded_bytes INTEGER NOT NULL DEFAULT 0,
        total_downloaded_tiles INTEGER NOT NULL DEFAULT 0,
        total_downloaded_files INTEGER NOT NULL DEFAULT 0,
        last_downloaded_at TEXT
      )
    `,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_licenced_download_events (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        downloaded_bytes INTEGER NOT NULL DEFAULT 0,
        downloaded_tiles INTEGER NOT NULL DEFAULT 0,
        downloaded_files INTEGER NOT NULL DEFAULT 0,
        skipped_existing_files INTEGER NOT NULL DEFAULT 0,
        missing_files INTEGER NOT NULL DEFAULT 0,
        period TEXT,
        status TEXT,
        source TEXT,
        created_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_user_licenced_download_events_user_created ON user_licenced_download_events(user_id, created_at DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS region_pack_detail_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        region_pack_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_region_pack_detail_tokens_expires ON region_pack_detail_tokens(expires_at)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS scene_full_quality_detail_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        tile_keys_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_scene_full_quality_detail_tokens_expires ON scene_full_quality_detail_tokens(expires_at)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS tile_land_stats (
        tile_key TEXT PRIMARY KEY,
        x INTEGER NOT NULL,
        y INTEGER NOT NULL,
        z INTEGER NOT NULL,
        d INTEGER NOT NULL,
        land_km2 REAL NOT NULL DEFAULT 0,
        billable_land_km2 REAL NOT NULL DEFAULT 0,
        free_reason TEXT,
        updated_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS pricing_integrity_events (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        quality_mode TEXT,
        issue_code TEXT NOT NULL,
        missing_tile_count INTEGER NOT NULL DEFAULT 0,
        tile_keys_json TEXT,
        created_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_pricing_integrity_events_created ON pricing_integrity_events(created_at DESC)`,
  );
  creditTablesReady = true;
}

async function ensureCreditAccountForUser(db, userId) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return;
  }
  await ensureCreditTables(db);
  const now = nowIso();
  await dbRun(
    db,
    `
      INSERT OR IGNORE INTO user_credit_accounts (
        user_id, account_type, created_at, updated_at
      )
      VALUES (?, 'standard', ?, ?)
    `,
    [safeUserId, now, now],
  );
  await dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET account_type = 'standard',
          updated_at = ?
      WHERE user_id = ?
        AND (
          account_type IS NULL
          OR TRIM(account_type) = ''
          OR LOWER(TRIM(account_type)) = 'unlimited'
        )
    `,
    [now, safeUserId],
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

function normalizeTierCodeStrict(value) {
  const normalized = normalizePlanCode(value);
  if (
    normalized === PLAN_CODE_FREE
    || normalized === PLAN_CODE_PERSONAL
    || normalized === PLAN_CODE_COMMERCIAL
  ) {
    return normalized;
  }
  return "";
}

async function upsertUserByEmail(db, email, status = PLAN_CODE_FREE, options = {}, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  await ensureUserConsentColumns(db);
  await ensureUserQualityAccessColumns(db);
  const requestedStatus = resolveFixedInternalPlanForEmail(normalizedEmail, status);
  if (!requestedStatus) {
    throw new Error("invalid_plan_code");
  }
  const grantBetaUnrestrictedToNewUser = isBetaUnrestrictedAccessEnabled(env);
  let user = await findUserByEmail(db, normalizedEmail);
  if (user) {
    const currentStatus = String(user.status || "").trim().toLowerCase();
    if (!isBlockedStatus(currentStatus) && !normalizeTierCodeStrict(currentStatus)) {
      throw new Error("invalid_user_status");
    }
    const fixedPlan = fixedInternalPlanForEmail(normalizedEmail);
    if (fixedPlan && currentStatus !== "blocked" && currentStatus && fixedPlan !== currentStatus) {
      console.warn(
        "worker.fixed_internal_plan_mismatch",
        JSON.stringify({
          email: normalizedEmail,
          status: currentStatus,
          expected: fixedPlan,
        }),
      );
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
      [
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
    await ensureCreditAccountForUser(db, user.id);
    const refreshedUser = await findUserById(db, user.id);
    if (refreshedUser) {
      return refreshedUser;
    }
    return user;
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
        unrestricted_quality_override,
        created_at,
        terms_accepted_at,
        privacy_accepted_at,
        terms_version,
        privacy_version
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      id,
      normalizedEmail,
      requestedStatus,
      grantBetaUnrestrictedToNewUser ? 1 : null,
      createdAt,
      termsAcceptedAt,
      privacyAcceptedAt,
      termsVersion,
      privacyVersion,
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

async function enforceUserPlanPolicy(db, user, env = {}) {
  void env;
  if (!user || !user.id || isBlockedStatus(user.status)) {
    return user;
  }
  const currentStatus = normalizeTierCodeStrict(user.status);
  if (!currentStatus) {
    throw new Error("invalid_user_status");
  }
  const fixedPlan = fixedInternalPlanForEmail(user.email);
  if (fixedPlan && fixedPlan !== currentStatus) {
    console.warn(
      "worker.fixed_internal_plan_mismatch",
      JSON.stringify({
        email: normalizeEmail(user.email || ""),
        user_id: String(user.id || "").trim(),
        status: currentStatus,
        expected: fixedPlan,
      }),
    );
  }
  return { ...user, status: currentStatus };
}

function fixedInternalPlanForEmail(email) {
  const normalizedEmail = normalizeEmail(email);
  return FIXED_INTERNAL_TEST_PLAN_BY_EMAIL[normalizedEmail] || "";
}

function resolveFixedInternalPlanForEmail(email, requestedPlan = PLAN_CODE_FREE) {
  const fixedPlan = fixedInternalPlanForEmail(email);
  if (fixedPlan) {
    return fixedPlan;
  }
  return normalizeTierCodeStrict(requestedPlan);
}

function normalizeUserQualityAccessOverride(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const text = String(value).trim().toLowerCase();
  if (!text) {
    return null;
  }
  if (text === "1" || text === "true" || text === "yes" || text === "unrestricted") {
    return true;
  }
  if (
    text === "0"
    || text === "false"
    || text === "no"
    || text === "normal"
  ) {
    return null;
  }
  return null;
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
  if (!names.has("unrestricted_quality_override")) {
    try {
      await dbRun(db, `ALTER TABLE users ADD COLUMN unrestricted_quality_override INTEGER`);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  if (!names.has("preview_fair_usage_hold_at")) {
    try {
      await dbRun(db, `ALTER TABLE users ADD COLUMN preview_fair_usage_hold_at TEXT`);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  if (!names.has("preview_fair_usage_hold_reason")) {
    try {
      await dbRun(db, `ALTER TABLE users ADD COLUMN preview_fair_usage_hold_reason TEXT`);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  if (!names.has("preview_fair_usage_hold_details_json")) {
    try {
      await dbRun(db, `ALTER TABLE users ADD COLUMN preview_fair_usage_hold_details_json TEXT`);
    } catch (error) {
      const message = String(error && error.message || "");
      if (!message.toLowerCase().includes("duplicate column")) {
        throw error;
      }
    }
  }
  userQualityAccessColumnsReady = true;
}

async function setGlobalUnrestrictedQualityEnabled(db, enabled) {
  await ensureUserQualityAccessColumns(db);
  const now = nowIso();
  const overrideValue = enabled ? 1 : null;
  const result = await dbRun(
    db,
    `
      UPDATE users
      SET unrestricted_quality_override = ?
    `,
    [overrideValue],
  );
  return {
    enabled: Boolean(enabled),
    updatedAt: now,
    affectedCount: dbMetaChanges(result),
  };
}

async function resolveUserQualityAccessState(db, user, env = {}) {
  let effectiveUser = user || null;
  if (
    effectiveUser
    && effectiveUser.id
    && effectiveUser.unrestricted_quality_override === undefined
  ) {
    const hydratedUser = await findUserById(db, effectiveUser.id);
    if (hydratedUser) {
      effectiveUser = hydratedUser;
    }
  }
  const storedPlanCode = normalizeTierCodeStrict(effectiveUser && effectiveUser.status);
  if (!effectiveUser || !effectiveUser.id) {
    return {
      storedPlanCode: PLAN_CODE_FREE,
      unrestrictedQualityAccess: false,
      qualityAccessPlanCode: PLAN_CODE_FREE,
      overrideMode: "normal",
      globalEnabled: false,
    };
  }
  if (!storedPlanCode && !isBlockedStatus(effectiveUser && effectiveUser.status)) {
    throw new Error("invalid_user_status");
  }
  await ensureUserQualityAccessColumns(db);
  const overrideValue = normalizeUserQualityAccessOverride(effectiveUser && effectiveUser.unrestricted_quality_override);
  const unrestrictedQualityAccess = Boolean(storedPlanCode === PLAN_CODE_COMMERCIAL || overrideValue === true);
  return {
    storedPlanCode: storedPlanCode || "",
    unrestrictedQualityAccess,
    qualityAccessPlanCode: unrestrictedQualityAccess ? PLAN_CODE_COMMERCIAL : (storedPlanCode || ""),
    overrideMode: overrideValue === true ? "unrestricted" : "normal",
    globalEnabled: false,
  };
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
  const z = Math.max(1, Number(parsed.z));
  const textureType = String(parsed.textureType || "").toUpperCase();

  // Dataset alias:
  // Some legacy clients may request EL z001 d002, but the actual stored file is
  // EL z001 d001 (see streaming_utils.py replacement). Do not classify this
  // compatibility alias as Full-only.
  if (textureType === "EL" && z === 1 && d === 1) {
    return "balanced";
  }

  // d001 => Full-only, d002/d003 => legacy paid-quality compatibility, d004+ => Preview+
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
        "Planetka API key request received.",
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

const AUTH_CORE_DEPS = {
  PLAN_CODE_PERSONAL,
  PLAN_CODE_FREE,
  DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS,
  DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS,
  addDaysIso,
  authContextCacheGet,
  authContextCacheSet,
  computeApiKeyExpiryIso,
  dbAll,
  dbGet,
  dbRun,
  ensureApiKeyTables,
  ensureRefreshSessionColumns,
  enforceSingleActiveFreeApiKey,
  isDeviceLimitExemptEmail,
  isQualityModeAllowedForPlan,
  json,
  normalizeDeviceId,
  normalizeQualityMode,
  normalizeRequestedPlan,
  nowIso,
  parsePositiveNumber,
  parseRateLimitInteger,
  qualityModeNotAllowedMessage,
  randomToken,
  requestClientIp,
  requestCountry,
  requireSecret,
  resolvePolicyPlanCode,
  sha256Hex,
  signJwt,
  verifyJwt,
};

let authCore = null;
let authApiKeyHandlers = null;
let authSessionRouteHandlers = null;

function getAuthCore() {
  if (!authCore) {
    authCore = createAuthCore(AUTH_CORE_DEPS);
  }
  return authCore;
}

const AUTH_API_KEY_DEPS = {
  DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS,
  DEFAULT_LEGAL_VERSION,
  DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_WINDOW_SECONDS,
  DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS,
  DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS,
  PLAN_CODE_PERSONAL,
  PLAN_CODE_FREE,
  addDaysIso,
  addMinutesIso,
  blockedAccountResponse,
  buildAccountState,
  consumeRateLimitWindow,
  createAccessToken,
  createRefreshSession,
  dbGet,
  dbRun,
  enforceApiKeyDeviceLimit,
  enforceApiKeyIssueDeviceLimit,
  enforceSingleActiveFreeApiKey,
  enforceUserPlanPolicy,
  ensureApiKeyTables,
  ensureRateLimitsTable,
  findActiveApiKeyRecord,
  findActiveHardBlock,
  findUserByEmail,
  genericAuthStartResponse,
  isBlockedStatus,
  isValidApiKey,
  issueApiKeyForUser,
  json,
  maskApiKey,
  normalizeDeviceId,
  normalizeEmail,
  normalizeTierCodeStrict,
  normalizeRequestedPlan,
  nowIso,
  parseBooleanFlag,
  parseJson,
  parseNonNegativeInteger,
  parsePositiveNumber,
  parseRateLimitInteger,
  publicErrorCode,
  randomToken,
  rateLimitedResponse,
  recordNewsletterOptIn,
  requestClientIp,
  requireDb,
  resolvePlanCode,
  sendApiKeyActivationEmail,
  sendApiKeyIssuedEmail,
  serializeAccountState,
  sha256Hex,
  upsertUserByEmail,
};

function getAuthApiKeyHandlers() {
  if (!authApiKeyHandlers) {
    authApiKeyHandlers = createAuthApiKeyHandlers(AUTH_API_KEY_DEPS);
  }
  return authApiKeyHandlers;
}

const AUTH_SESSION_ROUTE_DEPS = {
  DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS,
  PLAN_CODE_PERSONAL,
  blockedAccountResponse,
  buildAccountState,
  createAccessToken,
  createRefreshSession,
  dbGet,
  dbMetaChanges,
  dbRun,
  enforceUserPlanPolicy,
  ensureApiKeyTables,
  ensureRateLimitsTable,
  ensureRefreshSessionColumns,
  isApiKeyUsableById,
  isBlockedStatus,
  json,
  logAuthRefreshEvent,
  normalizeDeviceId,
  normalizeEmail,
  normalizeTierCodeStrict,
  nowIso,
  parseJson,
  parseRateLimitInteger,
  rateLimitedResponse,
  readBearerUser: (request, env) => readBearerUser(request, env, AUTH_SESSION_DEPS),
  requestClientIp,
  requestCountry,
  requireAuthenticatedUserContext: (request, env, options) =>
    requireAuthenticatedUserContext(request, env, options, AUTH_SESSION_DEPS),
  requireDb,
  resolvePolicyPlanCode,
  serializeAccountState,
  sha256Hex,
  consumeRateLimitWindow,
};

function getAuthSessionRouteHandlers() {
  if (!authSessionRouteHandlers) {
    authSessionRouteHandlers = createAuthSessionRouteHandlers(AUTH_SESSION_ROUTE_DEPS);
  }
  return authSessionRouteHandlers;
}

async function isApiKeyUsableById(db, apiKeyId, expectedUserId = "") {
  return getAuthCore().isApiKeyUsableById(db, apiKeyId, expectedUserId);
}

async function issueApiKeyForUser(db, env, user, planCode, options = {}) {
  return getAuthCore().issueApiKeyForUser(db, env, user, planCode, options);
}

async function findActiveApiKeyRecord(db, apiKeyValue) {
  return getAuthCore().findActiveApiKeyRecord(db, apiKeyValue);
}

async function enforceApiKeyIssueDeviceLimit(db, userId, userEmail, planCode, deviceId, env) {
  return getAuthCore().enforceApiKeyIssueDeviceLimit(db, userId, userEmail, planCode, deviceId, env);
}

async function enforceApiKeyDeviceLimit(db, apiKeyId, userId, userEmail, planCode, deviceId, request, env) {
  return getAuthCore().enforceApiKeyDeviceLimit(db, apiKeyId, userId, userEmail, planCode, deviceId, request, env);
}

async function createAccessToken(env, user, extraClaims = {}) {
  return getAuthCore().createAccessToken(env, user, extraClaims);
}

function normalizeResolveId(value) {
  return getAuthCore().normalizeResolveId(value);
}

async function issueTileSessionToken(env, auth, requestedQualityMode, requestedResolveId = "", options = {}) {
  return getAuthCore().issueTileSessionToken(env, auth, requestedQualityMode, requestedResolveId, options);
}

async function readTileSessionClaims(request, env) {
  return getAuthCore().readTileSessionClaims(request, env);
}

async function createRefreshSession(db, userId, expiresAtOverride = "", metadata = {}) {
  return getAuthCore().createRefreshSession(db, userId, expiresAtOverride, metadata);
}

function genericAuthStartResponse(env) {
  return getAuthCore().genericAuthStartResponse(env);
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
  const planCode = normalizeRequestedPlan(details.planCode || PLAN_CODE_FREE) || PLAN_CODE_FREE;
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
  return getAuthApiKeyHandlers().handleApiKeyRequest(request, env);
}

async function activateApiKeyFromToken(db, env, rawToken) {
  return getAuthApiKeyHandlers().activateApiKeyFromToken(db, env, rawToken);
}

async function handleApiKeyActivate(request, env) {
  return getAuthApiKeyHandlers().handleApiKeyActivate(request, env);
}

async function handleApiKeyExchange(request, env) {
  return getAuthApiKeyHandlers().handleApiKeyExchange(request, env);
}

async function handleAuthRefresh(request, env) {
  return getAuthSessionRouteHandlers().handleAuthRefresh(request, env);
}

async function handleAuthLogout(request, env) {
  return getAuthSessionRouteHandlers().handleAuthLogout(request, env);
}

async function handleMe(request, env) {
  return getAuthSessionRouteHandlers().handleMe(request, env);
}

const TILE_ROUTE_DEPS = {
  PLAN_CODE_FREE,
  clampNonNegativeInt,
  dbAll,
  dbGet,
  dbMetaChanges,
  dbRun,
  ensureCreditTables,
  isQualityModeAllowedForPlan,
  isTileEventQueueProducerEnabled,
  isTileHotPathMonitoringEnabled,
  issueTileSessionToken,
  maybeSignalTileFarmingActivity,
  minimumPlanQualityForTile,
  normalizeDeviceId,
  normalizeEmail,
  normalizeQualityMode,
  normalizeRequestedPlan,
  normalizeResolveId,
  nowIso,
  parseJson,
  qualityModeNotAllowedMessage,
  randomToken,
  rateLimitedResponse,
  readTileSessionClaims,
  recordTileRequestEvent,
  recordPreviewUsageAndMaybeAlert,
  invalidateAnalyticsSnapshots,
  requestClientIp,
  requestCountry,
  requireAuthenticatedUserContext: (request, env, options) => requireAuthenticatedUserContext(request, env, options, AUTH_SESSION_DEPS),
  requireDb,
  requireSecret,
  resolveTileCacheControl,
  getPreviewFairUsageHoldForUser,
  previewFairUsageBlockedResponse,
  json,
};

const TILE_EVENT_QUEUE_DEPS = {
  clampNonNegativeInt,
  isTileHotPathMonitoringEnabled,
  maybeSignalTileFarmingActivity,
  nowIso,
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
  handleAdminSetGlobalUnrestrictedQuality: (request, env) => handleAdminSetGlobalUnrestrictedQualityRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserBlock: (request, env) => handleAdminUserBlockRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserHardBlock: (request, env) => handleAdminUserHardBlockRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserReleasePreviewHold: (request, env) => handleAdminUserReleasePreviewHoldRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserSetPreviewHold: (request, env) => handleAdminUserSetPreviewHoldRoute(request, env, ADMIN_USER_DEPS),
  handleAdminQaAuthReset: (request, env) => handleAdminQaAuthResetRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserSetPlan: (request, env) => handleAdminUserSetPlanRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserSetUnrestrictedQuality: (request, env) => handleAdminUserSetUnrestrictedQualityRoute(request, env, ADMIN_USER_DEPS),
  handleAdminUserUnblock: (request, env) => handleAdminUserUnblockRoute(request, env, ADMIN_USER_DEPS),
};

async function dispatchExactRoute(request, env, path) {
  const adminMatch = await dispatchAdminRoute(request, env, path, ADMIN_ROUTE_DEPS);
  if (adminMatch) {
    return adminMatch;
  }
  if (String(path || "").startsWith("/credits/") || String(path || "") === "/tiles/session") {
    await getRuntimePricingSettings(env, TILE_ROUTE_DEPS);
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
    case "/credits/me":
      if (request.method === "GET") {
        return await handleCreditMeRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/estimate":
      if (request.method === "POST") {
        return await handleCreditEstimateRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/checkout":
      if (request.method === "POST") {
        return await handleCreditCheckoutRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-offers":
      if (request.method === "POST") {
        return await handleCreditRegionOffersRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-related-offers":
      if (request.method === "POST") {
        return await handleCreditRegionPackRelatedOffersRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-detail-link":
      if (request.method === "POST") {
        return await handleCreditRegionPackDetailLinkRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/scene-detail-link":
      if (request.method === "POST") {
        return await handleCreditSceneDetailLinkRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/scene-map":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditSceneMapRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-map":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditRegionPackMapRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-map-asset":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditRegionPackMapAssetRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-map-background.jpg":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditRegionPackMapBackgroundRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/page-assets/region-pack-map.css":
    case "/credits/page-assets/region-pack-map.js":
    case "/credits/page-assets/region-pack-dynamic-map.css":
    case "/credits/page-assets/region-pack-dynamic-map.js":
    case "/credits/page-assets/region-pack-catalog.css":
    case "/credits/page-assets/region-pack-catalog.js":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditRegionPackPageAssetRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-catalog":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditRegionPackCatalogRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-catalog-asset":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditRegionPackCatalogAssetRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/region-pack-checkout":
      if (request.method === "GET" || request.method === "HEAD" || request.method === "POST") {
        return await handleCreditRegionPackCheckoutFromTokenRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/payment-success":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditPaymentSuccessRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/payment-cancelled":
      if (request.method === "GET" || request.method === "HEAD") {
        return await handleCreditPaymentCancelledRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/purchase-history":
      if (request.method === "GET") {
        return await handleCreditPurchaseHistoryRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/licenced-download-report":
      if (request.method === "POST") {
        return await handleCreditLicencedDownloadReportRoute(request, env, TILE_ROUTE_DEPS);
      }
      return null;
    case "/credits/unlocked":
      if (request.method === "GET") {
        return await handleCreditUnlockedRoute(request, env, TILE_ROUTE_DEPS);
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
        await getRuntimePricingSettings(env, TILE_ROUTE_DEPS);
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
        const maintenance = await runScheduledMaintenanceJobs(
          db,
          env,
          runStartedAt,
          MAINTENANCE_JOB_DEPS,
        );
        const analyticsSnapshotSummary = await buildAnalyticsSnapshotMatrix(
          db,
          env,
          ADMIN_ANALYTICS_DEPS,
        );
        const analyticsUsersSnapshot = await buildAnalyticsUsersSnapshot(
          db,
          env,
          ADMIN_ANALYTICS_DEPS,
        );
        console.log(
          "worker.db_cleanup.completed",
          JSON.stringify({
            scheduled_at: scheduledAt,
            ...maintenance.summary,
            production_alert_summary: maintenance.alertSummary,
            monthly_cost_summary: maintenance.monthlyCostSummary,
            analytics_snapshot_summary: analyticsSnapshotSummary,
            analytics_users_snapshot_rows: Number(analyticsUsersSnapshot && analyticsUsersSnapshot.total_rows || 0),
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
  async queue(batch, env, ctx) {
    void ctx;
    if (String(batch && batch.queue || "") !== "planetka-tile-events") {
      return;
    }
    await handleTileEventQueueBatch(batch, env, TILE_EVENT_QUEUE_DEPS);
  },
};
