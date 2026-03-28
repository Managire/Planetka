const encoder = new TextEncoder();
const BYTES_PER_GB = 1024 * 1024 * 1024;
const PLAN_CODE_PLANETKA = "planetka";
const PLAN_CODE_PLANETKA_PRO = "planetka_pro";
const PLAN_CODE_PLANETKA_STUDIO = "planetka_studio";
const DEFAULT_ALLOWANCE_COUNTING_RULE =
  "Only newly downloaded data counts. Reused local cache does not consume allowance.";
const DEFAULT_PERIOD_DAYS = 30;
const DEFAULT_FREE_INCLUDED_GB = 100;
const DEFAULT_PRO_INCLUDED_GB = 1000;
const DEFAULT_PRO_ROLLOVER_CAP_GB = 3000;
const DEFAULT_STUDIO_INCLUDED_GB = 10000;
const DEFAULT_LOW_WARNING_GB = 10;
const DEFAULT_LOW_WARNING_RATIO = 0.1;
const UNLIMITED_ALLOWANCE_BYTES = Number.MAX_SAFE_INTEGER;
const DEFAULT_UPGRADE_URL = "https://www.planetka.io/signup";
const DEFAULT_CONTACT_URL = "https://www.planetka.io/contact";
const DEFAULT_TERMS_URL = "https://api.planetka.io/legal/terms-of-service.pdf";
const DEFAULT_PRIVACY_URL = "https://api.planetka.io/legal/privacy-policy.pdf";
const DEFAULT_LEGAL_VERSION = "2026-03-26";
const DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT = 20;
const DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT = 6;
const DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS = 900;
const DEFAULT_RATE_LIMIT_DEVICE_POLL_IP_LIMIT = 300;
const DEFAULT_RATE_LIMIT_DEVICE_POLL_IP_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_DEVICE_POLL_CODE_LIMIT = 120;
const DEFAULT_RATE_LIMIT_DEVICE_POLL_CODE_WINDOW_SECONDS = 60;
const DEFAULT_REFRESH_SESSION_CLEANUP_RETENTION_DAYS = 30;
const DEFAULT_ALERT_AUTH_429_THRESHOLD = 10;
const DEFAULT_ALERT_AUTH_429_WINDOW_SECONDS = 60;
const DEFAULT_ALERT_DEVICE_POLL_429_THRESHOLD = 30;
const DEFAULT_ALERT_DEVICE_POLL_429_WINDOW_SECONDS = 60;
const DEFAULT_ALERT_AUTH_ERROR_THRESHOLD = 5;
const DEFAULT_ALERT_AUTH_ERROR_WINDOW_SECONDS = 300;
const DEFAULT_ANALYTICS_WINDOW_MINUTES = 60;
const MAX_ANALYTICS_WINDOW_MINUTES = 10080;
const DEFAULT_ANALYTICS_ADMIN_EMAILS = "info@planetka.io,tom.griger@gmail.com";
const DEFAULT_PERMANENT_PRO_EMAILS = "tom.griger@gmail.com";
const DEFAULT_TILE_BROWSER_MAX_AGE_SECONDS = 86400;
const DEFAULT_TILE_EDGE_MAX_AGE_SECONDS = 604800;
const MAX_TILE_MAX_AGE_SECONDS = 31536000;
const DEFAULT_FREE_API_KEY_VALID_DAYS = 30;
const DEFAULT_PRO_GRACE_HOURS = 24;
const DEFAULT_PENDING_CLAIM_COOLDOWN_DAYS = 7;
const DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS = 900;
const DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS = 2;
const DEFAULT_RATE_LIMIT_PAID_CLAIM_IP_DAILY_LIMIT = 20;
const DEFAULT_RATE_LIMIT_PAID_CLAIM_IP_DAILY_WINDOW_SECONDS = 86400;
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
let manualCreditModeCache = "";
let userConsentColumnsReady = false;
let magicLinksTokenIndexReady = false;
let stripeWebhookEventsTableReady = false;
let rateLimitsTableReady = false;
let tileRequestEventsTableReady = false;
let apiKeyTablesReady = false;
let userProvisionalColumnsReady = false;
let refreshSessionColumnsReady = false;
let rateLimitsLastPruneAt = 0;

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.APP_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Planetka-Device-Id",
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

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function normalizeUserStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === PLAN_CODE_PLANETKA_PRO || normalized === "pro") {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (normalized === PLAN_CODE_PLANETKA_STUDIO || normalized === "studio") {
    return PLAN_CODE_PLANETKA_STUDIO;
  }
  if (normalized === PLAN_CODE_PLANETKA || normalized === "free" || normalized === "personal") {
    return PLAN_CODE_PLANETKA;
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

function resolveEntitlementState(user, env = {}) {
  const status = normalizeUserStatus(user && user.status);
  const email = normalizeEmail(user && user.email);
  const provisionalPlanCode = normalizeRequestedPlan(
    String(user && user.provisional_plan_code || status || PLAN_CODE_PLANETKA),
  );
  const provisionalExpiresAt = String(user && user.provisional_expires_at || "").trim();
  const confirmedAt = String(user && user.pro_confirmed_at || "").trim();
  const provisionalExpiresAtMs = Date.parse(provisionalExpiresAt);
  const provisionalHasTimestamp = Number.isFinite(provisionalExpiresAtMs);
  const isStatusPaid = status === PLAN_CODE_PLANETKA_PRO || status === PLAN_CODE_PLANETKA_STUDIO;
  const isProvisionalPaidPlan = isPaidRequestedPlan(provisionalPlanCode);
  const defaultResult = {
    state: "free",
    plan_code: PLAN_CODE_PLANETKA,
    commercial_use_allowed: false,
    subscription_status: "inactive",
    is_permanent_paid: false,
    is_provisional_paid: false,
    is_expired_provisional: false,
    source: "free",
    email,
  };
  if (user && isBlockedStatus(user.status)) {
    return {
      ...defaultResult,
      state: "blocked",
      plan_code: "blocked",
      source: "blocked",
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
    };
  }
  if (confirmedAt && (isStatusPaid || isProvisionalPaidPlan)) {
    const confirmedPlanCode = status === PLAN_CODE_PLANETKA_STUDIO
      ? PLAN_CODE_PLANETKA_STUDIO
      : (isProvisionalPaidPlan ? provisionalPlanCode : PLAN_CODE_PLANETKA_PRO);
    return {
      ...defaultResult,
      state: "permanent_paid",
      plan_code: confirmedPlanCode,
      commercial_use_allowed: true,
      subscription_status: "active",
      is_permanent_paid: true,
      source: "confirmed",
    };
  }
  if (isProvisionalPaidPlan && provisionalHasTimestamp) {
    if (provisionalExpiresAtMs >= Date.now()) {
      return {
        ...defaultResult,
        state: "provisional_paid",
        plan_code: provisionalPlanCode,
        commercial_use_allowed: true,
        subscription_status: "active",
        is_provisional_paid: true,
        source: "provisional",
      };
    }
    return {
      ...defaultResult,
      state: "expired_provisional",
      is_expired_provisional: true,
      source: "expired_provisional",
    };
  }
  return defaultResult;
}

function subscriptionStatusForUser(user, env = {}) {
  const entitlement = resolveEntitlementState(user, env);
  return String(entitlement.subscription_status || "inactive");
}

function resolvePolicyPlanCode(user, subscription, env = {}) {
  void subscription;
  const entitlement = resolveEntitlementState(user, env);
  if (entitlement.state === "blocked") {
    return "blocked";
  }
  return normalizeRequestedPlan(entitlement.plan_code || PLAN_CODE_PLANETKA);
}

function parseBooleanFlag(value) {
  if (typeof value === "boolean") {
    return value;
  }
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
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
  if (normalized === PLAN_CODE_PLANETKA_STUDIO) {
    return PLAN_CODE_PLANETKA_STUDIO;
  }
  return PLAN_CODE_PLANETKA;
}

function isPaidRequestedPlan(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  return normalized === PLAN_CODE_PLANETKA_PRO || normalized === PLAN_CODE_PLANETKA_STUDIO;
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

function isUnconfirmedProvisionalActive(user) {
  const entitlement = resolveEntitlementState(user);
  return entitlement.state === "provisional_paid";
}

function isUnconfirmedProvisionalExpired(user) {
  const entitlement = resolveEntitlementState(user);
  return entitlement.state === "expired_provisional";
}

function computeApiKeyExpiryIso(planCode, env) {
  const safePlan = normalizeRequestedPlan(planCode);
  if (safePlan === PLAN_CODE_PLANETKA_PRO || safePlan === PLAN_CODE_PLANETKA_STUDIO) {
    return "";
  }
  const validityDays = Math.max(
    1,
    Math.floor(parsePositiveNumber(env.FREE_API_KEY_VALID_DAYS, DEFAULT_FREE_API_KEY_VALID_DAYS)),
  );
  return addDaysIso(validityDays);
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

function isAnalyticsAdmin(user, env) {
  if (!user || !user.email) {
    return false;
  }
  return parseAdminEmailSet(env).has(normalizeEmail(user.email));
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
  tileRequestEventsTableReady = true;
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

async function collectAnalyticsSnapshot(db, minutes) {
  await ensureTileRequestEventsTable(db);
  const nowUnix = Math.floor(Date.now() / 1000);
  const windowMinutes = sanitizeAnalyticsMinutes(minutes, DEFAULT_ANALYTICS_WINDOW_MINUTES);
  const windowStartUnix = Math.max(0, nowUnix - (windowMinutes * 60));

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
    `,
    [windowStartUnix],
  );

  const active5m = await dbGet(
    db,
    `SELECT COUNT(DISTINCT user_id) AS active_users FROM tile_request_events WHERE created_at_unix >= ?`,
    [Math.max(0, nowUnix - 300)],
  );
  const active15m = await dbGet(
    db,
    `SELECT COUNT(DISTINCT user_id) AS active_users FROM tile_request_events WHERE created_at_unix >= ?`,
    [Math.max(0, nowUnix - 900)],
  );
  const active60m = await dbGet(
    db,
    `SELECT COUNT(DISTINCT user_id) AS active_users FROM tile_request_events WHERE created_at_unix >= ?`,
    [Math.max(0, nowUnix - 3600)],
  );
  const activeNow = await dbGet(
    db,
    `SELECT COUNT(*) AS active_download_rows FROM tile_request_events WHERE created_at_unix >= ?`,
    [Math.max(0, nowUnix - 10)],
  );

  const topUsers = await dbAll(
    db,
    `
      SELECT
        user_id,
        user_email,
        COUNT(*) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END), 0) AS error_count,
        MAX(created_at) AS last_seen_at
      FROM tile_request_events
      WHERE created_at_unix >= ?
      GROUP BY user_id, user_email
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [windowStartUnix],
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
      GROUP BY tile_key
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [windowStartUnix],
  );

  const recentFailures = await dbAll(
    db,
    `
      SELECT
        created_at,
        user_email,
        tile_key,
        status_code,
        error_code,
        cache_status,
        duration_ms
      FROM tile_request_events
      WHERE status_code >= 400
      ORDER BY created_at_unix DESC
      LIMIT 50
    `,
    [],
  );

  return {
    generated_at: nowIso(),
    window_minutes: windowMinutes,
    window_start_unix: windowStartUnix,
    summary: {
      request_count: clampNonNegativeInt(summary && summary.request_count),
      bytes_served: clampNonNegativeInt(summary && summary.bytes_served),
      error_count: clampNonNegativeInt(summary && summary.error_count),
      cache_hit_count: clampNonNegativeInt(summary && summary.cache_hit_count),
      tagged_request_count: clampNonNegativeInt(summary && summary.tagged_request_count),
      tagged_resolve_count: clampNonNegativeInt(summary && summary.tagged_resolve_count),
    },
    active: {
      users_5m: clampNonNegativeInt(active5m && active5m.active_users),
      users_15m: clampNonNegativeInt(active15m && active15m.active_users),
      users_60m: clampNonNegativeInt(active60m && active60m.active_users),
      tile_events_10s: clampNonNegativeInt(activeNow && activeNow.active_download_rows),
    },
    top_users: Array.isArray(topUsers) ? topUsers : [],
    top_tiles: Array.isArray(topTiles) ? topTiles : [],
    recent_failures: Array.isArray(recentFailures) ? recentFailures : [],
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

async function cleanupAuthTables(db, env, nowTimestamp) {
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
  };
  const refreshSessionCutoff = addDaysFromIso(
    nowTimestamp,
    -summary.refresh_session_retention_days,
  );
  const paidClaimRetentionCutoff = addDaysFromIso(
    nowTimestamp,
    -Math.max(30, parseNonNegativeInteger(env.PAID_CLAIM_RETENTION_DAYS, DEFAULT_PAID_CLAIM_RETENTION_DAYS)),
  );

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

  return summary;
}

async function ensureAllowanceTables(db) {
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS usage_periods (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        plan_code TEXT NOT NULL,
        period TEXT NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        included_limit_bytes INTEGER NOT NULL DEFAULT 0,
        included_consumed_bytes INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_usage_periods_user_start ON usage_periods(user_id, period_start DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS usage_charges (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        period_id TEXT NOT NULL,
        bytes_used INTEGER NOT NULL,
        created_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_usage_charges_user_time ON usage_charges(user_id, created_at DESC)`,
  );
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS manual_allowance_credits (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        bytes_total INTEGER NOT NULL,
        bytes_consumed INTEGER NOT NULL DEFAULT 0,
        expires_at TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_manual_allowance_credits_user_expiry ON manual_allowance_credits(user_id, expires_at)`,
  );
}

function buildPlanConfig(env) {
  const periodDays = Math.max(1, Math.floor(parsePositiveNumber(env.ALLOWANCE_PERIOD_DAYS, DEFAULT_PERIOD_DAYS)));
  const freeIncludedBytes = toBytesFromGb(parsePositiveNumber(env.ALLOWANCE_FREE_INCLUDED_GB, DEFAULT_FREE_INCLUDED_GB));
  const proIncludedBytes = toBytesFromGb(parsePositiveNumber(env.ALLOWANCE_PRO_INCLUDED_GB, DEFAULT_PRO_INCLUDED_GB));
  const proRolloverCapBytes = toBytesFromGb(parsePositiveNumber(env.ALLOWANCE_PRO_ROLLOVER_CAP_GB, DEFAULT_PRO_ROLLOVER_CAP_GB));
  const studioIncludedBytes = toBytesFromGb(parsePositiveNumber(env.ALLOWANCE_STUDIO_INCLUDED_GB, DEFAULT_STUDIO_INCLUDED_GB));
  const lowWarningBytes = toBytesFromGb(parsePositiveNumber(env.ALLOWANCE_LOW_WARNING_GB, DEFAULT_LOW_WARNING_GB));
  const lowWarningRatio = parsePositiveNumber(env.ALLOWANCE_LOW_WARNING_RATIO, DEFAULT_LOW_WARNING_RATIO);
  const countingRule = String(env.ALLOWANCE_COUNTING_RULE || DEFAULT_ALLOWANCE_COUNTING_RULE).trim();
  const upgradeUrl = String(env.UPGRADE_URL || DEFAULT_UPGRADE_URL).trim();
  const manageSubscriptionUrl = String(env.MANAGE_SUBSCRIPTION_URL || "").trim();
  const contactUrl = String(env.PLANETKA_CONTACT_URL || env.ALLOWANCE_SUPPORT_URL || DEFAULT_CONTACT_URL).trim();
  return {
    periodDays,
    freeIncludedBytes,
    proIncludedBytes,
    proRolloverCapBytes,
    studioIncludedBytes,
    lowWarningBytes,
    lowWarningRatio,
    countingRule,
    upgradeUrl,
    manageSubscriptionUrl,
    contactUrl,
  };
}

function resolvePlanCode(user, subscription, env = {}) {
  void subscription;
  const entitlement = resolveEntitlementState(user, env);
  const policyPlan = normalizeRequestedPlan(entitlement.plan_code || PLAN_CODE_PLANETKA);
  if (policyPlan === PLAN_CODE_PLANETKA_PRO || policyPlan === PLAN_CODE_PLANETKA_STUDIO) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  return PLAN_CODE_PLANETKA;
}

function commercialUseAllowed(planCode) {
  return planCode === PLAN_CODE_PLANETKA_PRO || planCode === PLAN_CODE_PLANETKA_STUDIO;
}

function includedLimitForPlan(planCode, cfg, previousPeriod) {
  if (planCode === PLAN_CODE_PLANETKA_STUDIO) {
    return cfg.studioIncludedBytes;
  }
  if (planCode === PLAN_CODE_PLANETKA_PRO) {
    const previousLimit = clampNonNegativeInt(previousPeriod && previousPeriod.included_limit_bytes);
    const previousConsumed = clampNonNegativeInt(previousPeriod && previousPeriod.included_consumed_bytes);
    const previousUnused = Math.max(0, previousLimit - previousConsumed);
    return Math.min(cfg.proRolloverCapBytes, cfg.proIncludedBytes + previousUnused);
  }
  return cfg.freeIncludedBytes;
}

async function findLatestUsagePeriod(db, userId) {
  return dbGet(
    db,
    `
      SELECT
        id,
        user_id,
        plan_code,
        period,
        period_start,
        period_end,
        included_limit_bytes,
        included_consumed_bytes
      FROM usage_periods
      WHERE user_id = ?
      ORDER BY period_start DESC
      LIMIT 1
    `,
    [userId],
  );
}

async function ensureCurrentUsagePeriod(db, userId, planCode, cfg) {
  await ensureAllowanceTables(db);
  const now = Date.now();
  let latest = await findLatestUsagePeriod(db, userId);
  if (latest && Date.parse(String(latest.period_end || "")) > now) {
    return latest;
  }

  const periodStart = latest ? String(latest.period_end || nowIso()) : nowIso();
  const periodEnd = addDaysFromIso(periodStart, cfg.periodDays);
  const includedLimitBytes = includedLimitForPlan(planCode, cfg, latest);
  const createdAt = nowIso();
  const periodId = crypto.randomUUID();
  await dbRun(
    db,
    `
      INSERT INTO usage_periods (
        id,
        user_id,
        plan_code,
        period,
        period_start,
        period_end,
        included_limit_bytes,
        included_consumed_bytes,
        created_at,
        updated_at
      ) VALUES (?, ?, ?, 'monthly', ?, ?, ?, 0, ?, ?)
    `,
    [periodId, userId, planCode, periodStart, periodEnd, includedLimitBytes, createdAt, createdAt],
  );

  latest = await findLatestUsagePeriod(db, userId);
  return latest;
}

async function getManualCreditRemaining(db, userId, nowTimestamp) {
  const mode = await detectManualCreditMode(db);
  if (mode === "remaining") {
    const row = await dbGet(
      db,
      `
        SELECT COALESCE(SUM(CASE WHEN bytes_remaining > 0 THEN bytes_remaining ELSE 0 END), 0) AS remaining
        FROM manual_allowance_credits
        WHERE user_id = ?
          AND (expires_at IS NULL OR expires_at = '' OR expires_at >= ?)
      `,
      [userId, nowTimestamp],
    );
    return clampNonNegativeInt(row && row.remaining);
  }

  const row = await dbGet(
    db,
    `
      SELECT
        COALESCE(
          SUM(
            CASE
              WHEN bytes_total > bytes_consumed THEN bytes_total - bytes_consumed
              ELSE 0
            END
          ),
          0
        ) AS remaining
      FROM manual_allowance_credits
      WHERE user_id = ?
        AND (expires_at IS NULL OR expires_at = '' OR expires_at >= ?)
    `,
    [userId, nowTimestamp],
  );
  return clampNonNegativeInt(row && row.remaining);
}

async function detectManualCreditMode(db) {
  if (manualCreditModeCache) {
    return manualCreditModeCache;
  }
  const pragma = await db.prepare(`PRAGMA table_info(manual_allowance_credits)`).all();
  const rows = Array.isArray(pragma && pragma.results) ? pragma.results : [];
  const names = new Set(rows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  if (names.has("bytes_remaining")) {
    manualCreditModeCache = "remaining";
  } else {
    manualCreditModeCache = "consumed";
  }
  return manualCreditModeCache;
}

async function getDownloadedPeriodBytes(db, userId, periodStart, periodEnd) {
  const row = await dbGet(
    db,
    `
      SELECT COALESCE(SUM(bytes_used), 0) AS downloaded
      FROM usage_charges
      WHERE user_id = ?
        AND created_at >= ?
        AND created_at < ?
    `,
    [userId, periodStart, periodEnd],
  );
  return clampNonNegativeInt(row && row.downloaded);
}

function computeWarningState(totalRemainingBytes, includedLimitBytes, cfg) {
  if (totalRemainingBytes <= 0) {
    return "exhausted";
  }
  const threshold = Math.max(
    cfg.lowWarningBytes,
    Math.floor(clampNonNegativeInt(includedLimitBytes) * cfg.lowWarningRatio),
  );
  if (totalRemainingBytes <= Math.max(1, threshold)) {
    return "low";
  }
  return "ok";
}

async function buildAllowanceState(db, user, subscription, env) {
  void db;
  const cfg = buildPlanConfig(env);
  const planCode = resolvePlanCode(user, subscription, env);
  const includedLimitBytes = UNLIMITED_ALLOWANCE_BYTES;
  const includedRemainingBytes = UNLIMITED_ALLOWANCE_BYTES;
  const totalRemainingBytes = UNLIMITED_ALLOWANCE_BYTES;
  const downloadedPeriodBytes = 0;
  const warningState = "ok";
  const exhausted = false;

  return {
    planCode,
    commercialUseAllowed: commercialUseAllowed(planCode),
    upgradeUrl: cfg.upgradeUrl,
    manageSubscriptionUrl: cfg.manageSubscriptionUrl,
    contactUrl: cfg.contactUrl,
    dataAllowance: {
      included_limit_bytes: includedLimitBytes,
      included_remaining_bytes: includedRemainingBytes,
      topup_remaining_bytes: 0,
      total_remaining_bytes: totalRemainingBytes,
      downloaded_period_bytes: downloadedPeriodBytes,
      period: "lifetime",
      period_end: "",
      warning_state: warningState,
      exhausted,
      counting_rule: "Unlimited access for this release; no periodic allowance is applied.",
    },
    includedRemainingBytesBase: includedRemainingBytes,
    periodId: "",
  };
}

function serializeAccountState(state) {
  return {
    plan: {
      code: state.planCode,
    },
    plan_code: state.planCode,
    commercial_use_allowed: Boolean(state.commercialUseAllowed),
    upgrade_url: state.upgradeUrl,
    manage_subscription_url: state.manageSubscriptionUrl,
    contact_url: state.contactUrl,
    billing_period_end: state.dataAllowance.period_end,
    data_allowance: state.dataAllowance,
  };
}

async function consumeManualCredits(db, userId, bytesToConsume, nowTimestamp) {
  let remainingToConsume = clampNonNegativeInt(bytesToConsume);
  if (remainingToConsume <= 0) {
    return 0;
  }
  const mode = await detectManualCreditMode(db);

  const creditsSql = mode === "remaining"
    ? `
      SELECT id, bytes_total, bytes_remaining
      FROM manual_allowance_credits
      WHERE user_id = ?
        AND (expires_at IS NULL OR expires_at = '' OR expires_at >= ?)
        AND bytes_remaining > 0
      ORDER BY
        CASE WHEN expires_at IS NULL OR expires_at = '' THEN 1 ELSE 0 END ASC,
        expires_at ASC,
        created_at ASC
    `
    : `
      SELECT id, bytes_total, bytes_consumed
      FROM manual_allowance_credits
      WHERE user_id = ?
        AND (expires_at IS NULL OR expires_at = '' OR expires_at >= ?)
        AND bytes_total > bytes_consumed
      ORDER BY
        CASE WHEN expires_at IS NULL OR expires_at = '' THEN 1 ELSE 0 END ASC,
        expires_at ASC,
        created_at ASC
    `;
  const credits = await db.prepare(creditsSql).bind(userId, nowTimestamp).all();
  const rows = Array.isArray(credits && credits.results) ? credits.results : [];
  let consumed = 0;
  for (const credit of rows) {
    if (remainingToConsume <= 0) {
      break;
    }
    const available = mode === "remaining"
      ? clampNonNegativeInt(credit.bytes_remaining)
      : Math.max(0, clampNonNegativeInt(credit.bytes_total) - clampNonNegativeInt(credit.bytes_consumed));
    if (available <= 0) {
      continue;
    }
    const useNow = Math.min(available, remainingToConsume);
    if (mode === "remaining") {
      await dbRun(
        db,
        `
          UPDATE manual_allowance_credits
          SET
            bytes_remaining = CASE WHEN bytes_remaining > ? THEN bytes_remaining - ? ELSE 0 END,
            updated_at = ?
          WHERE id = ?
        `,
        [useNow, useNow, nowTimestamp, credit.id],
      );
    } else {
      await dbRun(
        db,
        `
          UPDATE manual_allowance_credits
          SET
            bytes_consumed = bytes_consumed + ?,
            updated_at = ?
          WHERE id = ?
        `,
        [useNow, nowTimestamp, credit.id],
      );
    }
    consumed += useNow;
    remainingToConsume -= useNow;
  }
  return consumed;
}

async function consumeAllowanceBytes(db, user, subscription, env, bytesUsed) {
  void bytesUsed;
  return buildAllowanceState(db, user, subscription, env);
}

async function findUserByEmail(db, email) {
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
        u.provisional_plan_code,
        u.provisional_expires_at,
        u.pro_confirmed_at,
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
  if (!apiKeyRequestNames.has("request_device_id")) {
    apiKeyRequestStatements.push(`ALTER TABLE api_key_requests ADD COLUMN request_device_id TEXT`);
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

async function findPendingPaidClaimByEmail(db, email) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return null;
  }
  const now = nowIso();
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
        cooldown_until,
        used_at,
        request_ip,
        request_device_id,
        created_at
      FROM api_key_requests
      WHERE email = ?
        AND request_type = ?
        AND review_status = ?
        AND (used_at IS NOT NULL OR expires_at >= ?)
      ORDER BY created_at DESC
      LIMIT 1
    `,
    [normalizedEmail, API_KEY_REQUEST_TYPE_PAID_CLAIM, CLAIM_REVIEW_PENDING, now],
  );
}

async function markPaidClaimReviewed(db, claimId, reviewStatus, options = {}) {
  const normalizedClaimId = String(claimId || "").trim();
  if (!normalizedClaimId) {
    return;
  }
  const safeStatus = String(reviewStatus || "").trim().toLowerCase() || CLAIM_REVIEW_REJECTED;
  const reviewedAt = String(options.reviewedAt || nowIso()).trim();
  const reviewedBy = String(options.reviewedBy || "").trim();
  const reviewNote = String(options.reviewNote || "").trim();
  const cooldownUntil = String(options.cooldownUntil || "").trim();
  await dbRun(
    db,
    `
      UPDATE api_key_requests
      SET
        review_status = ?,
        reviewed_at = ?,
        reviewed_by = CASE WHEN ? != '' THEN ? ELSE reviewed_by END,
        review_note = CASE WHEN ? != '' THEN ? ELSE review_note END,
        cooldown_until = CASE WHEN ? != '' THEN ? ELSE cooldown_until END
      WHERE id = ?
    `,
    [
      safeStatus,
      reviewedAt,
      reviewedBy,
      reviewedBy,
      reviewNote,
      reviewNote,
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

async function upsertUserByEmail(db, email, status = PLAN_CODE_PLANETKA, options = {}, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  await ensureUserConsentColumns(db);
  await ensureUserProvisionalColumns(db);
  const requestedStatus = normalizePlanCode(status) || PLAN_CODE_PLANETKA;
  const provisionalPlanCode = normalizeRequestedPlan(options.provisionalPlanCode || "");
  const provisionalExpiresAt = String(options.provisionalExpiresAt || "").trim();
  const proConfirmedAt = String(options.proConfirmedAt || "").trim();
  const requestedPaidStatus = requestedStatus === PLAN_CODE_PLANETKA_PRO || requestedStatus === PLAN_CODE_PLANETKA_STUDIO;
  const hasServerEntitlementSignal = Boolean(
    proConfirmedAt
    || (isPaidRequestedPlan(provisionalPlanCode) && provisionalExpiresAt)
    || isPermanentProEmail(normalizedEmail, env),
  );
  const gatedRequestedStatus = (requestedPaidStatus && !hasServerEntitlementSignal)
    ? PLAN_CODE_PLANETKA
    : requestedStatus;
  const forceProByEmail = isPermanentProEmail(normalizedEmail, env);
  const finalRequestedStatus = forceProByEmail ? PLAN_CODE_PLANETKA_PRO : gatedRequestedStatus;
  let user = await findUserByEmail(db, normalizedEmail);
  if (user) {
    const currentStatus = String(user.status || "").trim().toLowerCase();
    const nextStatus = String(finalRequestedStatus || "").trim().toLowerCase() || PLAN_CODE_PLANETKA;
    const currentEntitlement = resolveEntitlementState(user, env);
    // Keep currently entitled paid status when this helper is called with free status by non-entitlement flows.
    const protectedStatus = (
      Boolean(currentEntitlement && currentEntitlement.commercial_use_allowed)
      && (currentStatus === PLAN_CODE_PLANETKA_PRO || currentStatus === PLAN_CODE_PLANETKA_STUDIO)
      && nextStatus === PLAN_CODE_PLANETKA
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
          pro_confirmed_at = CASE WHEN ? != '' THEN ? ELSE pro_confirmed_at END
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
        user.id,
      ],
    );
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
        pro_confirmed_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ],
  );
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
    targetPlan !== PLAN_CODE_PLANETKA
    && targetPlan !== PLAN_CODE_PLANETKA_PRO
    && targetPlan !== PLAN_CODE_PLANETKA_STUDIO
  ) {
    return user;
  }
  const currentStatus = normalizeUserStatus(user.status);
  if (currentStatus === targetPlan) {
    return { ...user, status: targetPlan };
  }
  if (targetPlan === PLAN_CODE_PLANETKA) {
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
    return {
      ...user,
      status: targetPlan,
      provisional_plan_code: "",
      provisional_expires_at: "",
    };
  }
  await dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetPlan, user.id]);
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
  const displayPlan = safePlan === PLAN_CODE_PLANETKA ? "Free" : (safePlan === PLAN_CODE_PLANETKA_STUDIO ? "Studio" : "Pro");
  const expiryText = String(expiresAt || "").trim()
    ? `Expires at: ${String(expiresAt || "").trim()}`
    : "Expires at: never";
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
        `Plan: ${displayPlan}`,
        expiryText,
        "",
        "API key:",
        apiKeyValue,
        "",
        "Paste this key in Blender > Planetka > Account.",
      ].join("\n"),
      html: `
        <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
          <h2 style="margin-bottom: 16px;">Your Planetka API key</h2>
          <p><strong>Plan:</strong> ${displayPlan}<br/>
          <strong>${escapeHtml(expiryText)}</strong></p>
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

async function issueApiKeyForUser(db, env, user, planCode, options = {}) {
  await ensureApiKeyTables(db);
  const safePlan = normalizeRequestedPlan(planCode || user.status || PLAN_CODE_PLANETKA);
  const token = `pka_${randomToken(36)}`;
  const keyHash = await sha256Hex(token);
  const keyPrefix = String(token.slice(0, 16));
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
      crypto.randomUUID(),
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

  return {
    apiKey: token,
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
        u.pro_confirmed_at
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

async function enforceApiKeyIssueDeviceLimit(db, userId, planCode, deviceId, env) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return { activeDeviceCount: 0, maxDevices: maxDevicesForPlan(planCode), matchedDevice: false };
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

async function enforceApiKeyDeviceLimit(db, apiKeyId, userId, planCode, deviceId, request, env) {
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
  const basePayload = {
    type: "access",
    sub: user.id,
    email: user.email,
    subscription_status: subscriptionStatusForUser(user, env),
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

function parseCsvSet(value) {
  const set = new Set();
  for (const token of String(value || "").split(",")) {
    const normalized = String(token || "").trim();
    if (normalized) {
      set.add(normalized);
    }
  }
  return set;
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

async function readBearerUser(request, env) {
  const header = String(request.headers.get("Authorization") || "");
  if (!header.startsWith("Bearer ")) {
    return null;
  }
  const token = header.slice("Bearer ".length).trim();
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

function renderApiKeyRequestPage(env, message = "", requestedPlan = PLAN_CODE_PLANETKA) {
  const termsUrl = String(env.TERMS_URL || DEFAULT_TERMS_URL).trim() || DEFAULT_TERMS_URL;
  const privacyUrl = String(env.PRIVACY_URL || DEFAULT_PRIVACY_URL).trim() || DEFAULT_PRIVACY_URL;
  const contactUrl = String(env.CONTACT_URL || DEFAULT_CONTACT_URL).trim() || DEFAULT_CONTACT_URL;
  const safeMessage = String(message || "").trim();
  const messageMarkup = safeMessage
    ? `<p id="status" style="margin-top:14px;color:#86efac;">${escapeHtml(safeMessage)}</p>`
    : `<p id="status" style="margin-top:14px;color:#cbd5e1;"></p>`;
  const safePlan = normalizeRequestedPlan(requestedPlan || PLAN_CODE_PLANETKA);
  const isPaidPlan = safePlan === PLAN_CODE_PLANETKA_PRO || safePlan === PLAN_CODE_PLANETKA_STUDIO;
  const subTitle = isPaidPlan
    ? "Enter your purchase email and order ID to receive your API key."
    : "Enter your email address and we will send you a one-click activation link.";
  const orderFieldMarkup = isPaidPlan
    ? `
        <label for="orderId">Order ID</label>
        <input id="orderId" type="text" placeholder="Enter your order ID" required />
      `
    : ``;
  return html(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka API Key</title>
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
      <h1>Request Planetka API Key</h1>
      <p>${escapeHtml(subTitle)}</p>
      <form id="form">
        <label for="email">Email</label>
        <input id="email" type="email" placeholder="you@example.com" required />
        ${orderFieldMarkup}
        <div class="checkbox">
          <input id="terms" type="checkbox" required />
          <label for="terms">I agree to the <a href="${termsUrl}" target="_blank" rel="noopener noreferrer">Terms and Conditions</a> and <a href="${privacyUrl}" target="_blank" rel="noopener noreferrer">Privacy Policy</a>.</label>
        </div>
        <div class="checkbox">
          <input id="news" type="checkbox" />
          <label for="news">Opt in to receive news about Planetka by email.</label>
        </div>
        <input id="website" class="hidden" type="text" autocomplete="off" tabindex="-1" />
        <button id="submit" type="submit">Send API Key Link</button>
      </form>
      ${messageMarkup}
      <p class="help">Problem connecting? <a href="${contactUrl}" target="_blank" rel="noopener noreferrer">Contact Me</a></p>
    </main>
    <script>
      const startedAt = Date.now();
      const form = document.getElementById("form");
      const status = document.getElementById("status");
      const submit = document.getElementById("submit");
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
            order_id: String((document.getElementById("orderId") || {}).value || "").trim(),
          };
          const response = await fetch("/auth/api-key/request", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await response.json();
          if (!response.ok || !data.ok) {
            throw new Error(String((data && data.error) || ("http_" + response.status)));
          }
          status.style.color = "#86efac";
          status.textContent = "Check your email for the activation link.";
        } catch (error) {
          status.style.color = "#fca5a5";
          status.textContent = "Request failed. Please try again.";
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
  const contactUrl = String(env.CONTACT_URL || DEFAULT_CONTACT_URL).trim() || DEFAULT_CONTACT_URL;
  const key = String(data.apiKey || "").trim();
  const keyMask = key ? maskApiKey(key) : "";
  const email = String(data.email || "").trim();
  const planCode = normalizeRequestedPlan(data.planCode || PLAN_CODE_PLANETKA);
  const planLabel = planCode === PLAN_CODE_PLANETKA ? "Free" : (planCode === PLAN_CODE_PLANETKA_STUDIO ? "Studio" : "Pro");
  const expiry = String(data.expiresAt || "").trim() || "never";
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
      <p>Plan: <strong>${escapeHtml(planLabel)}</strong></p>
      <p>Expires: <strong>${escapeHtml(expiry)}</strong></p>
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
  const requestedPlan = normalizeRequestedPlan(body.requested_plan || PLAN_CODE_PLANETKA);
  const isPaidClaim = isPaidRequestedPlan(requestedPlan);
  const orderId = normalizeOrderId(body.order_id || "");
  const requestDeviceId = normalizeDeviceId(body.device_id || "");
  const acceptTerms = parseBooleanFlag(body.accept_terms);
  const acceptPrivacy = parseBooleanFlag(body.accept_privacy);
  const optInNews = parseBooleanFlag(body.opt_in_news);
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
  if (isPaidClaim && !orderId) {
    return json({ ok: false, error: "paid_claim_order_id_required" }, 400, env);
  }

  const clientIp = requestClientIp(request);
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
  if (isPaidClaim) {
    const paidClaimIpDailyRate = await consumeRateLimitWindow(
      db,
      "paid_claim_request_ip_day",
      clientIp,
      parseRateLimitInteger(
        env.RATE_LIMIT_PAID_CLAIM_IP_DAILY_LIMIT,
        DEFAULT_RATE_LIMIT_PAID_CLAIM_IP_DAILY_LIMIT,
      ),
      parseRateLimitInteger(
        env.RATE_LIMIT_PAID_CLAIM_IP_DAILY_WINDOW_SECONDS,
        DEFAULT_RATE_LIMIT_PAID_CLAIM_IP_DAILY_WINDOW_SECONDS,
      ),
    );
    if (!paidClaimIpDailyRate.allowed) {
      await signalRejectedClaimAttempt(
        db,
        env,
        {
          email,
          ip: clientIp,
          deviceId: requestDeviceId,
          orderId,
          requestedPlan,
          reason: "paid_claim_ip_daily_rate_limited",
        },
      );
      return rateLimitedResponse(
        env,
        "paid_claim_ip_daily_rate_limited",
        "Too many paid-claim attempts from this IP. Please try again later.",
        paidClaimIpDailyRate.retryAfterSeconds,
      );
    }
  }

  let existingUser = await findUserByEmail(db, email);
  if (existingUser && !isBlockedStatus(existingUser.status)) {
    existingUser = await enforceUserPlanPolicy(db, existingUser, null, env);
    try {
      await enforceApiKeyIssueDeviceLimit(
        db,
        String(existingUser.id || "").trim(),
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
  if (isPaidClaim) {
    const latestPaidClaim = await findLatestPaidClaimByEmail(db, email);
    if (latestPaidClaim) {
      const cooldownUntil = String(latestPaidClaim.cooldown_until || "").trim();
      const cooldownMs = Date.parse(cooldownUntil);
      if (Number.isFinite(cooldownMs) && cooldownMs > Date.now()) {
        await signalRejectedClaimAttempt(
          db,
          env,
          {
            email,
            ip: clientIp,
            deviceId: requestDeviceId,
            orderId,
            requestedPlan,
            claimId: String(latestPaidClaim.id || "").trim(),
            reason: "paid_claim_cooldown_active",
          },
        );
        const retryAfterSeconds = Math.max(1, Math.ceil((cooldownMs - Date.now()) / 1000));
        return rateLimitedResponse(
          env,
          "paid_claim_cooldown_active",
          "Paid claim is in cooldown. Try again after cooldown ends.",
          retryAfterSeconds,
        );
      }
    }
    const pendingPaidClaim = await findPendingPaidClaimByEmail(db, email);
    if (pendingPaidClaim) {
      await signalRejectedClaimAttempt(
        db,
        env,
        {
          email,
          ip: clientIp,
          deviceId: requestDeviceId,
          orderId,
          requestedPlan,
          claimId: String(pendingPaidClaim.id || "").trim(),
          reason: "paid_claim_pending_review",
        },
      );
      return json(
        {
          ok: false,
          error: "paid_claim_pending_review",
          message: "A paid claim is already pending review for this account.",
        },
        409,
        env,
      );
    }
  }

  const legalVersion = String(env.TERMS_VERSION || env.LEGAL_VERSION || DEFAULT_LEGAL_VERSION).trim() || DEFAULT_LEGAL_VERSION;
  const privacyVersion = String(env.PRIVACY_VERSION || env.LEGAL_VERSION || DEFAULT_LEGAL_VERSION).trim() || DEFAULT_LEGAL_VERSION;
  const acceptedAt = nowIso();
  await upsertUserByEmail(
    db,
    email,
    PLAN_CODE_PLANETKA,
    {
      termsAcceptedAt: acceptedAt,
      privacyAcceptedAt: acceptedAt,
      termsVersion: legalVersion,
      privacyVersion,
    },
    env,
  );
  if (optInNews) {
    await recordNewsletterOptIn(db, email, "api_key_request");
  }

  const token = randomToken(36);
  const tokenHash = await sha256Hex(token);
  const requestType = isPaidClaim ? API_KEY_REQUEST_TYPE_PAID_CLAIM : API_KEY_REQUEST_TYPE_FREE;
  const reviewStatus = isPaidClaim ? CLAIM_REVIEW_PENDING : CLAIM_REVIEW_APPROVED;
  const claimPlanCode = isPaidClaim ? requestedPlan : PLAN_CODE_PLANETKA;
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
      orderId || null,
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
  if (isPaidClaim) {
    await appendProvisionalClaimAudit(
      db,
      "claim_requested",
      {
        email,
        claimId,
        orderId,
        planCode: requestedPlan,
        ip: clientIp,
        deviceId: requestDeviceId,
        details: {
          review_status: reviewStatus,
        },
      },
    );
  }
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
      CLAIM_REVIEW_PENDING,
    ],
  );
  if (!requestRow) {
    throw new Error("invalid_or_expired_token");
  }

  const requestType = String(requestRow.request_type || API_KEY_REQUEST_TYPE_FREE).trim().toLowerCase();
  const requestedPlan = requestType === API_KEY_REQUEST_TYPE_PAID_CLAIM
    ? normalizeRequestedPlan(requestRow.claimed_plan_code || requestRow.requested_plan || PLAN_CODE_PLANETKA)
    : PLAN_CODE_PLANETKA;
  const email = normalizeEmail(requestRow.email);
  const orderId = normalizeOrderId(requestRow.order_id || "");
  const claimId = String(requestRow.id || "").trim();
  let provisionalPlanCode = "";
  let provisionalExpiresAt = "";
  let proConfirmedAt = "";
  let statusToSet = PLAN_CODE_PLANETKA;

  if (isPaidRequestedPlan(requestedPlan)) {
    statusToSet = requestedPlan;
    if (!isPermanentProEmail(email, env)) {
      provisionalPlanCode = requestedPlan;
      provisionalExpiresAt = computeProvisionalExpiryIso(env);
    } else {
      proConfirmedAt = nowIso();
    }
  }

  let user = await upsertUserByEmail(
    db,
    email,
    statusToSet,
    {
      provisionalPlanCode,
      provisionalExpiresAt,
      proConfirmedAt,
    },
    env,
  );
  user = await enforceUserPlanPolicy(db, user, null, env);
  const effectivePlanCode = resolvePlanCode(user, null, env);

  const issued = await issueApiKeyForUser(
    db,
    env,
    user,
    effectivePlanCode,
    {
      provisional: Boolean(provisionalPlanCode),
      provisionalExpiresAt,
      confirmedAt: proConfirmedAt,
    },
  );

  await sendApiKeyIssuedEmail(env, email, issued.apiKey, issued.planCode, issued.expiresAt);
  if (requestType === API_KEY_REQUEST_TYPE_PAID_CLAIM) {
    if (!provisionalPlanCode || !provisionalExpiresAt) {
      await markPaidClaimReviewed(
        db,
        claimId,
        CLAIM_REVIEW_APPROVED,
        {
          reviewedBy: "system_auto_confirmed",
          reviewNote: "auto_confirmed_permanent_pro",
        },
      );
    }
    await appendProvisionalClaimAudit(
      db,
      provisionalPlanCode && provisionalExpiresAt ? "claim_activated_provisional" : "claim_activated_confirmed",
      {
        email,
        userId: String(user && user.id || "").trim(),
        claimId,
        orderId,
        planCode: requestedPlan,
        ip: String(requestRow.request_ip || "").trim(),
        deviceId: String(requestRow.request_device_id || "").trim(),
        details: {
          issued_plan_code: issued.planCode,
          provisional_expires_at: provisionalExpiresAt,
        },
      },
    );
  }
  if (provisionalPlanCode && provisionalExpiresAt) {
    await sendProvisionalPlanAlert(
      env,
      {
        email,
        requestedPlan,
        provisionalExpiresAt,
        orderId,
        ip: String(requestRow.request_ip || "").trim(),
        deviceId: String(requestRow.request_device_id || "").trim(),
        claimId,
      },
    );
  }
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
    return json({ ok: false, error: String(error && error.message || "activation_failed") }, 400, env);
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
  const keyExpiresAt = String(record.api_key_expires_at || "").trim();
  if (keyExpiresAt && Date.parse(keyExpiresAt) < Date.now()) {
    return json({ ok: false, error: "api_key_expired" }, 401, env);
  }
  if (isBlockedStatus(record.status)) {
    return blockedAccountResponse(env);
  }

  let user = {
    id: record.id,
    email: record.email,
    status: record.status || PLAN_CODE_PLANETKA,
    provisional_plan_code: record.provisional_plan_code || "",
    provisional_expires_at: record.provisional_expires_at || "",
    pro_confirmed_at: record.pro_confirmed_at || "",
  };
  user = await enforceUserPlanPolicy(db, user, null, env);
  const effectivePlanCode = resolvePlanCode(user, null, env);
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

  let refreshExpiresAt = addDaysIso(7);
  if (keyExpiresAt) {
    const keyExpMs = Date.parse(keyExpiresAt);
    const refreshExpMs = Date.parse(refreshExpiresAt);
    if (Number.isFinite(keyExpMs) && Number.isFinite(refreshExpMs) && keyExpMs < refreshExpMs) {
      refreshExpiresAt = new Date(keyExpMs).toISOString();
    }
  }

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
  const accountState = await buildAllowanceState(db, user, null, env);

  return json(
    {
      ok: true,
      email: user.email,
      access_token: accessToken,
      refresh_token: refreshToken,
      subscription_status: subscriptionStatusForUser(user, env),
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
    user = await upsertUserByEmail(db, email, PLAN_CODE_PLANETKA, {
      termsAcceptedAt: acceptedAt,
      privacyAcceptedAt: acceptedAt,
      termsVersion: legalVersion,
      privacyVersion,
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
  const db = requireDb(env);
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
        u.pro_confirmed_at
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
  };
  user = await enforceUserPlanPolicy(db, user, null, env);
  const subscriptionStatus = subscriptionStatusForUser(user, env);
  const accessToken = await createAccessToken(env, user, null);
  const refreshToken = await createRefreshSession(db, userRecord.id);
  const accountState = await buildAllowanceState(db, user, null, env);

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
  const body = await parseJson(request);
  const refreshToken = String(body.refresh_token || "").trim();
  if (!refreshToken) {
    return json({ ok: false, error: "missing_refresh_token" }, 400, env);
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
        u.pro_confirmed_at
      FROM refresh_sessions rs
      JOIN users u ON u.id = rs.user_id
      WHERE rs.refresh_token_hash = ?
      LIMIT 1
    `,
    [refreshHash],
  );
  if (!session) {
    return json({ ok: false, error: "invalid_refresh_token" }, 400, env);
  }
  if (isBlockedStatus(session.status)) {
    return blockedAccountResponse(env);
  }
  if (session.revoked_at) {
    return json({ ok: false, error: "refresh_token_revoked" }, 400, env);
  }
  if (Date.parse(session.expires_at) < Date.now()) {
    return json({ ok: false, error: "refresh_token_expired" }, 400, env);
  }

  let user = {
    id: session.user_id,
    email: session.email,
    status: session.status || PLAN_CODE_PLANETKA,
    provisional_plan_code: session.provisional_plan_code || "",
    provisional_expires_at: session.provisional_expires_at || "",
    pro_confirmed_at: session.pro_confirmed_at || "",
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
  const accountState = await buildAllowanceState(db, user, null, env);

  return json(
    {
      ok: true,
      access_token: accessToken,
      refresh_token: nextRefreshToken,
      email: user.email,
      subscription_status: subscriptionStatus,
      renews_at: null,
      trial_ends_at: null,
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

async function handleMe(request, env) {
  const db = requireDb(env);
  let access;
  try {
    access = await readBearerUser(request, env);
  } catch (error) {
    return json({ ok: false, error: String(error.message || "invalid_access_token") }, 401, env);
  }
  if (!access) {
    return json({ ok: false, error: "missing_bearer_token" }, 401, env);
  }

  let user = await dbGet(
    db,
    `
      SELECT
        id,
        email,
        status,
        provisional_plan_code,
        provisional_expires_at,
        pro_confirmed_at,
        created_at,
        last_login_at
      FROM users
      WHERE id = ?
      LIMIT 1
    `,
    [access.sub],
  );
  if (!user) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }
  if (isBlockedStatus(user.status)) {
    return blockedAccountResponse(env);
  }
  user = await enforceUserPlanPolicy(db, user, null, env);
  const effectiveUserStatus = resolvePolicyPlanCode(user, null, env);
  const accountState = await buildAllowanceState(db, user, null, env);
  const subscriptionStatus = subscriptionStatusForUser(user, env);

  return json(
    {
      ok: true,
      email: user.email,
      user_status: effectiveUserStatus,
      subscription_status: subscriptionStatus,
      trial_ends_at: null,
      renews_at: null,
      ...serializeAccountState(accountState),
    },
    200,
    env,
  );
}

async function handleDeviceStart(request, env) {
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
      const accountState = await buildAllowanceState(db, user, null, env);
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
  const contactUrl = String(env.CONTACT_URL || DEFAULT_CONTACT_URL).trim() || DEFAULT_CONTACT_URL;
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
            <span>Opt in to receive news about Planetka by email.</span>
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

async function handleTileRequest(request, env, path, ctx) {
  if (!env.PLANETKA_DATA) {
    return json({ ok: false, error: "missing_r2_binding" }, 500, env);
  }

  let access;
  try {
    access = await readBearerUser(request, env);
  } catch (error) {
    return json({ ok: false, error: String(error.message || "invalid_access_token") }, 401, env);
  }
  if (!access) {
    return json({ ok: false, error: "missing_bearer_token" }, 401, env);
  }

  const db = requireDb(env);
  let user = await findUserById(db, access.sub);
  if (!user) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }
  if (isBlockedStatus(user.status)) {
    return blockedAccountResponse(env);
  }
  user = await enforceUserPlanPolicy(db, user, null, env);
  const planCode = resolvePlanCode(user, null, env);
  const provisionalRestricted = isUnconfirmedProvisionalActive(user);
  const authMethod = String(access.auth_method || "").trim().toLowerCase();
  const tokenApiKeyId = String(access.api_key_id || "").trim();
  const tokenDeviceId = normalizeDeviceId(access.device_id || request.headers.get("X-Planetka-Device-Id") || "");
  if (authMethod === "api_key" && tokenApiKeyId) {
    try {
      await enforceApiKeyDeviceLimit(db, tokenApiKeyId, String(user.id || ""), planCode, tokenDeviceId, request, env);
    } catch (error) {
      const code = String(error && error.message || "device_limit_exceeded");
      const statusCode = code === "missing_device_id" ? 400 : 429;
      const message = code === "missing_device_id"
        ? "Missing device identifier for API key session."
        : (provisionalRestricted
          ? "This Planetka account can be active on one computer at a time."
          : "This Planetka account can be active on one computer at a time.");
      return json({ ok: false, error: code, message }, statusCode, env);
    }
  }

  const requestStartedAtMs = Date.now();
  const clientIp = requestClientIp(request);
  const cfCountry = requestCountry(request);
  const cfRay = String(request.headers.get("CF-Ray") || "").trim();
  const resolveId = String(request.headers.get("X-Planetka-Resolve-Id") || "").trim().slice(0, 128);
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
    const fileName = decodeURIComponent(parts[1]);
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

    const tileQuality = parseTileQualityFromFileName(fileName);
    const isFreePlan = planCode === PLAN_CODE_PLANETKA;
    const isFullQualityS2Tile = Boolean(
      tileQuality
        && tileQuality.textureType === "S2"
        && Number.isFinite(tileQuality.z)
        && Number.isFinite(tileQuality.d)
        && tileQuality.z === tileQuality.d,
    );
    if (isFreePlan && isFullQualityS2Tile) {
      eventStatusCode = 403;
      eventErrorCode = "quality_not_allowed";
      return json(
        {
          ok: false,
          error: "quality_not_allowed",
          message: "Requested texture quality is not available for this account.",
        },
        403,
        env,
      );
    }

    const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
    const key = prefix ? `${prefix}/${folder}/${fileName}` : `${folder}/${fileName}`;
    eventTileKey = key;

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

    const allowanceState = await buildAllowanceState(db, user, null, env);
    if (allowanceState.dataAllowance.total_remaining_bytes < objectSize) {
      eventStatusCode = 402;
      eventErrorCode = "allowance_exhausted";
      return json(
        {
          ok: false,
          error: "allowance_exhausted",
          message: "Data allowance is exhausted. Contact Planetka for more data.",
          ...serializeAccountState(allowanceState),
        },
        402,
        env,
      );
    }

    let updatedAllowance;
    try {
      updatedAllowance = await consumeAllowanceBytes(db, user, null, env, objectSize);
    } catch (error) {
      if (String(error && error.message || "") === "allowance_exhausted") {
        eventStatusCode = 402;
        eventErrorCode = "allowance_exhausted";
        return json(
          {
            ok: false,
            error: "allowance_exhausted",
            message: "Data allowance is exhausted. Contact Planetka for more data.",
            ...serializeAccountState(await buildAllowanceState(db, user, null, env)),
          },
          402,
          env,
        );
      }
      throw error;
    }

    const responseHeaders = new Headers({
      ...corsHeaders(env),
      "Content-Type": contentType,
      "Content-Length": String(objectSize),
      "Cache-Control": resolveTileCacheControl(env),
      "X-Planetka-Remaining-Bytes": String(updatedAllowance.dataAllowance.total_remaining_bytes),
      "X-Planetka-Warning-State": String(updatedAllowance.dataAllowance.warning_state || "ok"),
      "X-Planetka-Cache": cacheStatus,
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
    if (ctx && typeof ctx.waitUntil === "function") {
      ctx.waitUntil(telemetryWrite);
    } else {
      await telemetryWrite;
    }
  }
}

async function requireAnalyticsAdmin(request, env) {
  const db = requireDb(env);
  let access = null;
  try {
    access = await readBearerUser(request, env);
    if (!access) {
      const url = new URL(request.url);
      const queryToken = String(url.searchParams.get("access_token") || url.searchParams.get("token") || "").trim();
      if (queryToken) {
        const secret = requireSecret(env, "JWT_SIGNING_SECRET");
        const payload = await verifyJwt(queryToken, secret);
        if (payload.type !== "access" || !payload.sub) {
          throw new Error("invalid_access_token");
        }
        access = payload;
      }
    }
  } catch (error) {
    return { error: json({ ok: false, error: String(error.message || "invalid_access_token") }, 401, env) };
  }
  if (!access) {
    return { error: json({ ok: false, error: "missing_bearer_token" }, 401, env) };
  }
  let user = await findUserById(db, access.sub);
  if (!user) {
    return { error: json({ ok: false, error: "user_not_found" }, 404, env) };
  }
  if (isBlockedStatus(user.status)) {
    return { error: blockedAccountResponse(env) };
  }
  user = await enforceUserPlanPolicy(db, user, null, env);
  if (!isAnalyticsAdmin(user, env)) {
    return { error: json({ ok: false, error: "admin_access_required" }, 403, env) };
  }
  return { db, user };
}

async function handleAdminAnalyticsData(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user } = auth;
  const url = new URL(request.url);
  const windowMinutes = sanitizeAnalyticsMinutes(url.searchParams.get("minutes"), DEFAULT_ANALYTICS_WINDOW_MINUTES);
  const snapshot = await collectAnalyticsSnapshot(db, windowMinutes);
  return json(
    {
      ok: true,
      admin_email: String(user.email || ""),
      ...snapshot,
    },
    200,
    env,
  );
}

async function handleAdminAnalyticsPage(request, env) {
  const auth = await requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { user } = auth;
  const htmlContent = `
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
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
    select, button { background:#111827; color:#e5e7eb; border:1px solid #374151; border-radius:8px; padding:7px 10px; }
    table { width:100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }
    th, td { border-bottom: 1px solid #1f2937; padding: 8px 6px; text-align:left; }
    th { color:#93c5fd; font-weight:600; }
    .section { margin-top: 20px; }
    .error { color: #fca5a5; }
  </style>
</head>
<body>
  <h1>Planetka Analytics</h1>
  <div class="muted">Signed in as ${escapeHtml(String(user.email || ""))}. Auto-refresh every 15 seconds.</div>
  <div class="controls">
    <label for="window">Window:</label>
    <select id="window">
      <option value="15">15 min</option>
      <option value="60" selected>60 min</option>
      <option value="360">6 hours</option>
      <option value="1440">24 hours</option>
      <option value="10080">7 days</option>
    </select>
    <button id="refresh">Refresh now</button>
    <span id="status" class="muted"></span>
  </div>

  <div class="grid">
    <div class="card"><div class="label">Active users (5m)</div><div id="active5" class="value">-</div></div>
    <div class="card"><div class="label">Active users (15m)</div><div id="active15" class="value">-</div></div>
    <div class="card"><div class="label">Active users (60m)</div><div id="active60" class="value">-</div></div>
    <div class="card"><div class="label">Live tile events (10s)</div><div id="live10s" class="value">-</div></div>
    <div class="card"><div class="label">Tile requests (window)</div><div id="reqCount" class="value">-</div></div>
    <div class="card"><div class="label">Bytes served (window)</div><div id="bytesServed" class="value">-</div></div>
    <div class="card"><div class="label">Errors (window)</div><div id="errors" class="value">-</div></div>
    <div class="card"><div class="label">Cache hit ratio</div><div id="hitRatio" class="value">-</div></div>
    <div class="card"><div class="label">Tagged resolves</div><div id="resolveCount" class="value">-</div></div>
  </div>

  <div class="section">
    <h3>Top Users</h3>
    <table id="usersTable"><thead><tr><th>Email</th><th>Requests</th><th>GB</th><th>Errors</th><th>Last seen</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Top Tiles</h3>
    <table id="tilesTable"><thead><tr><th>Tile key</th><th>Requests</th><th>GB</th></tr></thead><tbody></tbody></table>
  </div>
  <div class="section">
    <h3>Recent Failures</h3>
    <table id="failsTable"><thead><tr><th>Time</th><th>User</th><th>Status</th><th>Error</th><th>Tile</th><th>Cache</th><th>ms</th></tr></thead><tbody></tbody></table>
  </div>

  <script>
    const statusEl = document.getElementById("status");
    const windowEl = document.getElementById("window");
    const refreshBtn = document.getElementById("refresh");
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const fmtInt = (v) => Number(v || 0).toLocaleString();
    const fmtBytes = (v) => {
      let n = Number(v || 0);
      const units = ["B","KB","MB","GB","TB"];
      let i = 0;
      while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
      return n.toFixed(i === 0 ? 0 : 2) + " " + units[i];
    };
    const fmtGb = (v) => (Number(v || 0) / (1024 * 1024 * 1024)).toFixed(3);
    function renderRows(tableId, rows, rowBuilder) {
      const tbody = document.querySelector("#" + tableId + " tbody");
      if (!tbody) return;
      tbody.innerHTML = "";
      for (const row of rows || []) {
        const tr = document.createElement("tr");
        tr.innerHTML = rowBuilder(row);
        tbody.appendChild(tr);
      }
    }
    const urlParams = new URLSearchParams(window.location.search || "");
    const accessToken = String(urlParams.get("access_token") || urlParams.get("token") || "");
    async function loadAnalytics() {
      const minutes = windowEl.value || "60";
      statusEl.textContent = "Loading...";
      try {
        const tokenQuery = accessToken ? ("&access_token=" + encodeURIComponent(accessToken)) : "";
        const res = await fetch("/admin/analytics/data?minutes=" + encodeURIComponent(minutes) + tokenQuery, { credentials: "same-origin" });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error((data && data.error) || ("HTTP " + res.status));
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
        renderRows("usersTable", data.top_users, (row) => \`<td>\${row.user_email || ""}</td><td>\${fmtInt(row.request_count)}</td><td>\${fmtGb(row.bytes_served)}</td><td>\${fmtInt(row.error_count)}</td><td>\${row.last_seen_at || ""}</td>\`);
        renderRows("tilesTable", data.top_tiles, (row) => \`<td>\${row.tile_key || ""}</td><td>\${fmtInt(row.request_count)}</td><td>\${fmtGb(row.bytes_served)}</td>\`);
        renderRows("failsTable", data.recent_failures, (row) => \`<td>\${row.created_at || ""}</td><td>\${row.user_email || ""}</td><td>\${row.status_code || ""}</td><td>\${row.error_code || ""}</td><td>\${row.tile_key || ""}</td><td>\${row.cache_status || ""}</td><td>\${row.duration_ms || ""}</td>\`);
        statusEl.textContent = "Updated " + new Date().toLocaleTimeString();
        statusEl.className = "muted";
      } catch (error) {
        statusEl.textContent = "Error: " + String(error && error.message || error);
        statusEl.className = "error";
      }
    }
    refreshBtn.addEventListener("click", loadAnalytics);
    windowEl.addEventListener("change", loadAnalytics);
    loadAnalytics();
    setInterval(loadAnalytics, 15000);
  </script>
</body>
</html>
  `;
  return html(htmlContent, 200, env);
}

function sanitizeAttachmentFileName(value, fallback = "planetka_bug_report.json") {
  const raw = String(value || "").trim();
  const safe = raw.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
  if (!safe) {
    return fallback;
  }
  return safe.toLowerCase().endsWith(".json") ? safe : `${safe}.json`;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function handleSupportBugReport(request, env) {
  const db = requireDb(env);
  let access;
  try {
    access = await readBearerUser(request, env);
  } catch (error) {
    return json({ ok: false, error: String(error.message || "invalid_access_token") }, 401, env);
  }
  if (!access) {
    return json({ ok: false, error: "missing_bearer_token" }, 401, env);
  }

  const user = await findUserById(db, access.sub);
  if (!user) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }
  if (isBlockedStatus(user.status)) {
    return blockedAccountResponse(env);
  }

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
    "",
    "Attached: JSON debug report",
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
      <strong>Expected behavior:</strong> ${escapeHtml(issueExpected || "(not provided)")}</p>
      <p>Attached: JSON debug report</p>
    </div>
  `;

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
      attachments: [
        {
          filename: reportFileName,
          content: base64EncodeString(reportJson),
        },
      ],
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
    },
    200,
    env,
  );
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

  const sessionMode = String(session.mode || "").trim().toLowerCase();
  if (sessionMode !== "payment") {
    console.log(
      "stripe.webhook.ignored_mode",
      JSON.stringify({ event_type: eventType, email, mode: sessionMode }),
    );
    return json(
      {
        ok: true,
        ignored: true,
        reason: "unsupported_checkout_mode",
        event_type: eventType,
        email,
        mode: sessionMode,
      },
      200,
      env,
    );
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

  const allowedPriceIds = parseCsvSet(env.STRIPE_ALLOWED_PRICE_IDS);
  const allowedProductIds = parseCsvSet(env.STRIPE_ALLOWED_PRODUCT_IDS);
  if (allowedPriceIds.size === 0 && allowedProductIds.size === 0) {
    console.error(
      "stripe.webhook.misconfigured_entitlement_allowlist",
      JSON.stringify({ event_type: eventType, email, session_id: sessionId }),
    );
    return json({ ok: false, error: "missing_stripe_entitlement_allowlist" }, 500, env);
  }

  const lineItems = await fetchStripeCheckoutSessionLineItems(env, sessionId);
  const entitlements = collectStripeLineItemEntitlements(lineItems);
  const hasAllowedPrice = entitlements.priceIds.some((priceId) => allowedPriceIds.has(priceId));
  const hasAllowedProduct = entitlements.productIds.some((productId) => allowedProductIds.has(productId));
  const entitlementMatched = hasAllowedPrice || hasAllowedProduct;
  if (!entitlementMatched) {
    console.log(
      "stripe.webhook.ignored_disallowed_line_items",
      JSON.stringify({
        event_type: eventType,
        email,
        session_id: sessionId,
        purchased_price_ids: entitlements.priceIds.slice(0, 25),
        purchased_product_ids: entitlements.productIds.slice(0, 25),
      }),
    );
    return json(
      {
        ok: true,
        ignored: true,
        reason: "disallowed_checkout_items",
        event_type: eventType,
        email,
      },
      200,
      env,
    );
  }

  const user = await upsertUserByEmail(
    db,
    email,
    PLAN_CODE_PLANETKA_PRO,
    {
      proConfirmedAt: nowIso(),
      provisionalPlanCode: "",
      provisionalExpiresAt: "",
    },
    env,
  );
  const stripeCustomerId = String(session.customer || "").trim() || "";
  const stripeSubscriptionId = String(session.subscription || "").trim() || "";

  console.log(
    "stripe.webhook.processed",
    JSON.stringify({
      event_type: eventType,
      email,
      session_mode: sessionMode,
      session_id: sessionId,
      stripe_customer_id: stripeCustomerId,
      stripe_subscription_id: stripeSubscriptionId,
      matched_price_ids: entitlements.priceIds.filter((priceId) => allowedPriceIds.has(priceId)).slice(0, 25),
      matched_product_ids: entitlements.productIds.filter((productId) => allowedProductIds.has(productId)).slice(0, 25),
      user_status: String(user && user.status || PLAN_CODE_PLANETKA_PRO),
    }),
  );

  return json(
    {
      ok: true,
      processed: true,
      event_type: eventType,
      email,
    },
    200,
    env,
  );
}

function notImplemented(route, env) {
  return json(
    {
      ok: false,
      error: "not_implemented",
      route,
      message: "This route is scaffolded but not implemented yet.",
    },
    501,
    env,
  );
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

    try {
      if (request.method === "GET" && path === "/health") {
        return json(
          {
            ok: true,
            service: "planetka-api",
            api_base_url: env.API_BASE_URL || "https://api.planetka.io",
            login_url: env.LOGIN_URL || "https://www.planetka.io/login",
            device_login_url: `${env.API_BASE_URL || "https://api.planetka.io"}/device/login`,
            db_bound: Boolean(env.DB),
            r2_bound: Boolean(env.PLANETKA_DATA),
          },
          200,
          env,
        );
      }

      if (request.method === "GET" && path === "/api-key") {
        const requestedPlan = normalizeRequestedPlan(url.searchParams.get("plan") || PLAN_CODE_PLANETKA);
        return renderApiKeyRequestPage(env, "", requestedPlan);
      }

      if (request.method === "GET" && path === "/api-key/activate") {
        return await handleApiKeyActivatePage(request, env);
      }

      if (request.method === "POST" && path === "/auth/start") {
        return await handleAuthStart(request, env);
      }

      if (request.method === "POST" && path === "/auth/api-key/request") {
        return await handleApiKeyRequest(request, env);
      }

      if (request.method === "POST" && path === "/auth/api-key/activate") {
        return await handleApiKeyActivate(request, env);
      }

      if (request.method === "POST" && path === "/auth/api-key/exchange") {
        return await handleApiKeyExchange(request, env);
      }

      if (request.method === "POST" && path === "/auth/verify") {
        return await handleAuthVerify(request, env);
      }

      if (request.method === "POST" && path === "/auth/refresh") {
        return await handleAuthRefresh(request, env);
      }

      if (request.method === "GET" && path === "/me") {
        return await handleMe(request, env);
      }

      if (request.method === "POST" && path === "/device/start") {
        return await handleDeviceStart(request, env);
      }

      if (request.method === "POST" && path === "/device/poll") {
        return await handleDevicePoll(request, env);
      }

      if (request.method === "GET" && path === "/device/login") {
        return await handleDeviceLoginPage(request, env);
      }

      if ((request.method === "GET" || request.method === "HEAD") && path.startsWith("/legal/")) {
        return await handleLegalDocumentRequest(request, env, path);
      }

      if (request.method === "GET" && path === "/billing/portal") {
        return notImplemented("/billing/portal", env);
      }

      if (request.method === "POST" && path === "/support/bug-report") {
        return await handleSupportBugReport(request, env);
      }

      if (request.method === "GET" && path === "/admin/analytics") {
        return await handleAdminAnalyticsPage(request, env);
      }

      if (request.method === "GET" && path === "/admin/analytics/data") {
        return await handleAdminAnalyticsData(request, env);
      }

      if ((request.method === "GET" || request.method === "HEAD") && path.startsWith("/tiles/")) {
        return await handleTileRequest(request, env, path, ctx);
      }

      if (request.method === "POST" && path === "/stripe/webhook") {
        return await handleStripeWebhook(request, env);
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
    } catch (error) {
      if (isAuthOrDevicePath(path)) {
        try {
          const db = requireDb(env);
          await trackThresholdAlertDb(
            db,
            "auth_endpoint_error_spike",
            parseRateLimitInteger(env.LOG_ALERT_AUTH_ERROR_THRESHOLD, DEFAULT_ALERT_AUTH_ERROR_THRESHOLD),
            parseRateLimitInteger(env.LOG_ALERT_AUTH_ERROR_WINDOW_SECONDS, DEFAULT_ALERT_AUTH_ERROR_WINDOW_SECONDS),
            {
              route: path,
              method: request.method,
              error: String(error && error.message || "internal_error"),
            },
          );
        } catch (alertError) {
          // Alert tracking is best-effort and must never alter API error responses.
          console.debug(
            "worker.alert.tracking_failed",
            JSON.stringify({
              route: path,
              method: request.method,
              error: String(alertError && alertError.message || "alert_tracking_failed"),
            }),
          );
        }
      }
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
          error: String(error.message || "internal_error"),
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
        console.log(
          "worker.db_cleanup.completed",
          JSON.stringify({
            scheduled_at: scheduledAt,
            ...summary,
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
