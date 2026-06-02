import {
  corsHeaders,
  json,
  jsonWithHeaders,
} from "./worker/responses.js";
import {
  parseBooleanFlag,
  parseNonNegativeInteger,
} from "./worker/env.js";
import {
  ACCESS_STATUS_ACTIVE,
  isBlockedStatus,
  isQualityModeAllowedForAccess,
  normalizeAccessStatus,
  normalizeQualityMode,
  normalizeRequestedAccessStatus,
  qualityModeNotAllowedMessage,
  resolvePolicyAccessStatus,
} from "./worker/entitlements.js";
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

const encoder = new TextEncoder();
const ADDON_ID = "planetka";
const DEFAULT_TERMS_URL = "https://api.planetka.io/legal/terms-of-service.pdf";
const DEFAULT_PRIVACY_URL = "https://api.planetka.io/legal/privacy-policy.pdf";
const DEFAULT_LEGAL_VERSION = "2026-05-12";
const DEFAULT_ADDON_UPDATE_MANIFEST_VERSION = "0.2.0";
const DEFAULT_ADDON_UPDATE_CHANNEL = "stable";
const DEFAULT_ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS = 300;
const DEFAULT_ADDON_UPDATE_RELEASE_NOTES_URL = "https://www.planetka.io/blender/documentation/";
const DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_LIMIT = 60;
const DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS = 60;
const DEFAULT_AUTH_CONTEXT_CACHE_TTL_SECONDS = 60;
const DEFAULT_AUTH_CONTEXT_CACHE_MAX_ENTRIES = 4096;
const DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS = 1800;
const RATE_LIMIT_PRUNE_INTERVAL_SECONDS = 300;
const RATE_LIMIT_ENTRY_TTL_SECONDS = 172800;

const FIXED_INTERNAL_ACCESS_STATUS_BY_EMAIL = Object.freeze({});

let rateLimitsTableReady = false;
let adminHardBlocksTableReady = false;
let apiKeyTablesReady = false;
let refreshSessionColumnsReady = false;
let userConsentColumnsReady = false;
let userQualityAccessColumnsReady = false;
let newsletterContactsTableReady = false;
let authRefreshEventsTableReady = false;
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

function requestClientIpScope(request) {
  const ip = String(requestClientIp(request) || "").trim().toLowerCase();
  if (!ip || ip === "unknown") {
    return "";
  }
  if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(ip)) {
    const parts = ip.split(".");
    return `${parts[0]}.${parts[1]}.${parts[2]}.0/24`;
  }
  if (ip.includes(":")) {
    const [headRaw, tailRaw = ""] = ip.split("::");
    const head = headRaw ? headRaw.split(":").filter(Boolean) : [];
    const tail = tailRaw ? tailRaw.split(":").filter(Boolean) : [];
    const missing = Math.max(0, 8 - head.length - tail.length);
    const expanded = [
      ...head.map((part) => part.padStart(4, "0")),
      ...Array.from({ length: missing }, () => "0000"),
      ...tail.map((part) => part.padStart(4, "0")),
    ];
    return `${expanded.slice(0, 4).join(":")}::/64`;
  }
  return "";
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

function normalizeDeviceId(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  return raw.replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 128);
}

function isSyntheticAnonymousEmail(value) {
  return /^anonymous\+[a-f0-9]{32}@planetka\.local$/i.test(String(value || "").trim());
}

function normalizeAccessStatusStrict(value) {
  const normalized = normalizeAccessStatus(value);
  if (normalized === ACCESS_STATUS_ACTIVE) {
    return ACCESS_STATUS_ACTIVE;
  }
  if (normalized === "blocked") {
    return "blocked";
  }
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
          id, created_at, created_at_unix, user_id, user_email, auth_method, device_id,
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
        device_id TEXT,
        client_ip_scope TEXT
      )
    `,
  );
  const pragma = await db.prepare(`PRAGMA table_info(refresh_sessions)`).all();
  const rows = Array.isArray(pragma && pragma.results) ? pragma.results : [];
  const names = new Set(rows.map((row) => String(row && row.name || "").trim().toLowerCase()));
  for (const statement of [
    !names.has("auth_method") ? `ALTER TABLE refresh_sessions ADD COLUMN auth_method TEXT` : "",
    !names.has("device_id") ? `ALTER TABLE refresh_sessions ADD COLUMN device_id TEXT` : "",
    !names.has("client_ip_scope") ? `ALTER TABLE refresh_sessions ADD COLUMN client_ip_scope TEXT` : "",
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

function fixedInternalAccessStatusForEmail(email) {
  return FIXED_INTERNAL_ACCESS_STATUS_BY_EMAIL[normalizeEmail(email)] || "";
}

function resolveFixedInternalAccessStatusForEmail(email, requestedAccessStatus = ACCESS_STATUS_ACTIVE) {
  const fixedAccessStatus = fixedInternalAccessStatusForEmail(email);
  if (fixedAccessStatus) {
    return fixedAccessStatus;
  }
  return normalizeAccessStatusStrict(requestedAccessStatus);
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

async function upsertAnonymousUserByDeviceId(db, deviceId, env = {}) {
  const safeDeviceId = normalizeDeviceId(deviceId);
  if (!safeDeviceId) {
    throw new Error("missing_device_id");
  }
  await ensureUserConsentColumns(db);
  await ensureUserQualityAccessColumns(db);
  await ensureRefreshSessionColumns(db);
  const hashed = await sha256Hex(`planetka-anonymous:${safeDeviceId}`);
  const anonymousId = `anon_${hashed.slice(0, 32)}`;
  const syntheticEmail = `anonymous+${hashed.slice(0, 32)}@planetka.local`;
  const now = nowIso();
  let user = await findUserById(db, anonymousId);
  if (user) {
    if (isBlockedStatus(user.status)) {
      return user;
    }
    const normalizedStatus = normalizeAccessStatusStrict(user.status);
    if (!normalizedStatus) {
      throw new Error("invalid_user_status");
    }
    await dbRun(db, `UPDATE users SET last_login_at = ? WHERE id = ?`, [now, anonymousId]);
    return findUserById(db, anonymousId);
  }
  user = await dbGet(db, `SELECT id, email, status FROM users WHERE lower(email) = ? LIMIT 1`, [syntheticEmail]);
  if (user) {
    await dbRun(db, `UPDATE users SET last_login_at = ? WHERE id = ?`, [now, user.id]);
    return findUserById(db, user.id);
  }
  await dbRun(
    db,
    `
      INSERT INTO users (id, email, status, created_at, last_login_at, terms_accepted_at, privacy_accepted_at, terms_version, privacy_version)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      anonymousId,
      syntheticEmail,
      ACCESS_STATUS_ACTIVE,
      now,
      now,
      now,
      now,
      DEFAULT_LEGAL_VERSION,
      DEFAULT_LEGAL_VERSION,
    ],
  );
  void env;
  return findUserById(db, anonymousId);
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

async function upsertUserByEmail(db, email, status = ACCESS_STATUS_ACTIVE, options = {}, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  await ensureUserConsentColumns(db);
  await ensureUserQualityAccessColumns(db);
  const requestedStatus = resolveFixedInternalAccessStatusForEmail(normalizedEmail, status);
  if (!requestedStatus) {
    throw new Error("invalid_access_status_code");
  }
  let user = await findUserByEmail(db, normalizedEmail);
  if (user) {
    const currentStatus = String(user.status || "").trim().toLowerCase();
    if (!isBlockedStatus(currentStatus) && !normalizeAccessStatusStrict(currentStatus)) {
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
  if (!parseBooleanFlag(options.suppressNewUserAlert)) {
    try {
      await sendNewUserLoginAlert(env, {
        email: normalizedEmail,
        source: String(options.signupSource || options.source || "unknown").trim() || "unknown",
        accessStatus: requestedStatus,
        createdAt,
      });
    } catch (error) {
      console.warn("auth_worker.new_user_alert_email_failed", String(error && error.message || "new_user_alert_email_failed"));
    }
  }
  return findUserByEmail(db, normalizedEmail);
}

async function enforceUserAccessStatusPolicy(db, user, env = {}) {
  void db;
  void env;
  if (!user || !user.id || isBlockedStatus(user.status)) {
    return user;
  }
  const currentStatus = normalizeAccessStatusStrict(user.status);
  if (!currentStatus) {
    throw new Error("invalid_user_status");
  }
  return { ...user, status: currentStatus };
}

async function resolveUserQualityAccessState(db, user, env = {}) {
  void db;
  void env;
  const storedAccessStatus = normalizeAccessStatusStrict(user && user.status);
  if (!user || !user.id) {
    return { storedAccessStatus: ACCESS_STATUS_ACTIVE, qualityAccessStatus: ACCESS_STATUS_ACTIVE };
  }
  if (!storedAccessStatus && !isBlockedStatus(user && user.status)) {
    throw new Error("invalid_user_status");
  }
  return { storedAccessStatus: storedAccessStatus || "", qualityAccessStatus: storedAccessStatus || "" };
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
  const storedAccessStatus = normalizeAccessStatusStrict(qualityAccess.storedAccessStatus);
  if (!storedAccessStatus) {
    throw new Error("invalid_user_status");
  }
  return {
    accessStatus: storedAccessStatus,
    storedAccessStatus,
    qualityAccessStatus: qualityAccess.qualityAccessStatus,
    previewFairUsageHold: getPreviewFairUsageHoldForUserFromRow(user),
  };
}

function serializeAccountState(state) {
  const safeState = state || {};
  const accessStatus = normalizeAccessStatusStrict(safeState.accessStatus);
  const storedAccessStatus = normalizeAccessStatusStrict(safeState.storedAccessStatus);
  const qualityAccessStatus = normalizeAccessStatusStrict(safeState.qualityAccessStatus);
  return {
    access_status: { code: accessStatus || "" },
    access_status_code: accessStatus || "",
    stored_access_status_code: storedAccessStatus || "",
    quality_access_status_code: qualityAccessStatus || "",
    preview_fair_usage_hold: safeState.previewFairUsageHold || { held: false },
    previewFairUsageHold: safeState.previewFairUsageHold || { held: false },
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

const authSessionDepsBase = {
  requireDb,
  parseBooleanFlag,
  authContextCacheGet,
  authContextCacheSet,
  verifyJwt,
  requireSecret,
  requestClientIpScope,
  normalizeDeviceId,
  normalizeAccessStatusStrict,
  findUserById,
  isBlockedStatus,
  blockedAccountResponse,
  enforceUserAccessStatusPolicy,
  resolveUserQualityAccessState,
  isAnalyticsAdmin: () => false,
  isPrimaryAnalyticsAdmin: () => false,
  json,
};

const readBearerUser = (request, env) => readBearerUserRoute(request, env, authSessionDeps);
const requireAuthenticatedUserContext = (request, env, options = {}) => requireAuthenticatedUserContextRoute(request, env, options, authSessionDeps);

const authCoreDeps = {
  ACCESS_STATUS_ACTIVE,
  DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS,
  requireSecret,
  dbAll,
  dbGet,
  dbRun,
  ensureRefreshSessionColumns,
  normalizeRequestedAccessStatus,
  resolvePolicyAccessStatus,
  normalizeDeviceId,
  parseRateLimitInteger,
  requestClientIp,
  requestClientIpScope,
  requestCountry,
  nowIso,
  addDaysIso,
  randomToken,
  sha256Hex,
  signJwt,
  verifyJwt,
  normalizeQualityMode,
  isQualityModeAllowedForAccess,
  qualityModeNotAllowedMessage,
  json,
  authContextCacheGet,
  authContextCacheSet,
};

const authCore = createAuthCore(authCoreDeps);

const authSessionDeps = {
  ...authSessionDepsBase,
};

const authSessionRouteDeps = {
  DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_LIMIT,
  DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS,
  requireDb,
  requireSecret,
  ensureRateLimitsTable,
  requestClientIp,
  requestClientIpScope,
  requestCountry,
  consumeRateLimitWindow,
  parseRateLimitInteger,
  rateLimitedResponse,
  logAuthRefreshEvent,
  parseJson,
  sha256Hex,
  dbGet,
  dbRun,
  dbAll,
  dbMetaChanges,
  isBlockedStatus,
  blockedAccountResponse,
  normalizeAccessStatusStrict,
  enforceUserAccessStatusPolicy,
  nowIso,
  buildAccountState,
  createAccessToken: authCore.createAccessToken,
  createRefreshSession: authCore.createRefreshSession,
  normalizeEmail,
  json,
  serializeAccountState,
  ensureRefreshSessionColumns,
  normalizeDeviceId,
  readBearerUser,
  requireAuthenticatedUserContext,
  isSyntheticAnonymousEmail,
};

const authSessionRouteHandlers = createAuthSessionRouteHandlers(authSessionRouteDeps);

async function handleAnonymousAuth(request, env) {
  const db = requireDb(env);
  await ensureRateLimitsTable(db);
  const body = await parseJson(request);
  const deviceId = normalizeDeviceId(body.device_id || request.headers.get("X-Planetka-Device-Id") || "");
  const clientIpScope = requestClientIpScope(request);
  if (!deviceId) {
    return json({ ok: false, error: "missing_device_id" }, 400, env);
  }
  const ipRate = await consumeRateLimitWindow(
    db,
    "auth_anonymous_ip",
    requestClientIp(request),
    parseRateLimitInteger(env.RATE_LIMIT_AUTH_ANONYMOUS_IP_LIMIT, 120),
    parseRateLimitInteger(env.RATE_LIMIT_AUTH_ANONYMOUS_IP_WINDOW_SECONDS, 60),
  );
  if (!ipRate.allowed) {
    return rateLimitedResponse(
      env,
      "auth_anonymous_ip_rate_limited",
      "Too many session requests. Please try again shortly.",
      ipRate.retryAfterSeconds,
    );
  }
  const block = await findActiveHardBlock(db, {
    device_id: deviceId,
    ip: requestClientIp(request),
  });
  if (block) {
    return blockedAccountResponse(env);
  }
  const user = await upsertAnonymousUserByDeviceId(db, deviceId, env);
  if (!user || !user.id) {
    return json({ ok: false, error: "anonymous_user_create_failed" }, 500, env);
  }
  if (isBlockedStatus(user.status)) {
    return blockedAccountResponse(env);
  }
  const policyUser = await enforceUserAccessStatusPolicy(db, user, env);
  const accessToken = await authCore.createAccessToken(
    env,
    policyUser,
    {
      auth_method: "anonymous",
      device_id: deviceId,
      client_ip_scope: clientIpScope,
    },
  );
  const refreshToken = await authCore.createRefreshSession(
    db,
    policyUser.id,
    "",
    {
      auth_method: "anonymous",
      device_id: deviceId,
      client_ip_scope: clientIpScope,
    },
  );
  const publicEmail = isSyntheticAnonymousEmail(policyUser.email) ? "" : String(policyUser.email || "");
  return json(
    {
      ok: true,
      anonymous: true,
      planetka_user_id: String(policyUser.id || ""),
      user_id: String(policyUser.id || ""),
      email: publicEmail,
      access_token: accessToken,
      refresh_token: refreshToken,
    },
    200,
    env,
  );
}


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
  if (path === "/auth/anonymous") {
    if (request.method !== "POST") {
      return methodNotAllowed(env);
    }
    return handleAnonymousAuth(request, env);
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

export default {
  async fetch(request, env) {
    try {
      return await dispatchAuthRequest(request, env);
    } catch (error) {
      const message = String(error && error.message || "auth_worker_error");
      console.error("auth_worker.unhandled", message);
      const status = message.startsWith("missing_secret_") || message === "missing_db_binding" ? 503 : 500;
      return json(
        {
          ok: false,
          error: status === 503 ? "auth_temporarily_unavailable" : "auth_worker_error",
          message: status === 503
            ? "Planetka account access is temporarily unavailable. Please try again in a few moments."
            : "Planetka account access failed. Please try again.",
        },
        status,
        env,
      );
    }
  },
};
