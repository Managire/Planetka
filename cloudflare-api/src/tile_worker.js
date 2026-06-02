import { corsHeaders, json } from "./worker/responses.js";
import {
  normalizeQualityMode,
} from "./worker/entitlements.js";
import {
  parseNonNegativeInteger,
} from "./worker/env.js";
import {
  handleTileRequest,
  handleResolveSummary,
  handleTileSessionStart,
} from "./worker/tile_routes.js";

const encoder = new TextEncoder();
const DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS = 1800;
const MAX_TILE_MAX_AGE_SECONDS = 31536000;
const DEFAULT_TILE_BROWSER_MAX_AGE_SECONDS = 86400;
const DEFAULT_TILE_EDGE_MAX_AGE_SECONDS = 604800;
const AUTH_CACHE = new Map();
const AUTH_CACHE_MAX = 4096;

function clampNonNegativeInt(value) {
  return Math.max(0, parseNonNegativeInteger(value, 0));
}

function nowIso() {
  return new Date().toISOString();
}

function requireDb(env) {
  if (!env.DB) throw new Error("missing_db_binding");
  return env.DB;
}

function requireSecret(env, name) {
  const value = String(env[name] || "").trim();
  if (!value) throw new Error(`missing_secret_${name}`);
  return value;
}

async function parseJson(request) {
  try {
    return await request.json();
  } catch (_error) {
    return {};
  }
}

function normalizeDeviceId(value) {
  return String(value || "").trim().replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 128);
}

function requestClientIp(request) {
  const direct = String(request.headers.get("CF-Connecting-IP") || request.headers.get("True-Client-IP") || "").trim();
  if (direct) return direct;
  const forwarded = String(request.headers.get("X-Forwarded-For") || "").trim();
  if (forwarded) return String(forwarded.split(",")[0] || "").trim() || "unknown";
  return "unknown";
}

function requestClientIpScope(request) {
  const ip = String(requestClientIp(request) || "").trim().toLowerCase();
  if (!ip || ip === "unknown") return "";
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

function base64UrlEncode(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlEncodeString(value) {
  return base64UrlEncode(encoder.encode(String(value || "")));
}

function base64UrlDecodeToBytes(value) {
  const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function base64UrlDecodeToString(value) {
  return new TextDecoder().decode(base64UrlDecodeToBytes(value));
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
  if (parts.length !== 3) throw new Error("invalid_token_format");
  const [encodedHeader, encodedPayload, encodedSignature] = parts;
  void encodedHeader;
  const signingInput = `${encodedHeader}.${encodedPayload}`;
  const expected = await hmacSha256(secret, signingInput);
  const actual = base64UrlDecodeToBytes(encodedSignature);
  if (actual.length !== expected.length) throw new Error("invalid_token_signature");
  let mismatch = 0;
  for (let i = 0; i < actual.length; i += 1) mismatch |= actual[i] ^ expected[i];
  if (mismatch !== 0) throw new Error("invalid_token_signature");
  const payload = JSON.parse(base64UrlDecodeToString(encodedPayload));
  if (payload.exp && Number(payload.exp) < Math.floor(Date.now() / 1000)) throw new Error("token_expired");
  return payload;
}

function readBearerToken(request) {
  const header = String(request.headers.get("Authorization") || "");
  return header.startsWith("Bearer ") ? header.slice("Bearer ".length).trim() : "";
}

function authCacheGet(key) {
  const safeKey = String(key || "").trim();
  const entry = safeKey ? AUTH_CACHE.get(safeKey) : null;
  if (!entry) return null;
  if (Number(entry.expires_at_ms || 0) <= Date.now()) {
    AUTH_CACHE.delete(safeKey);
    return null;
  }
  return entry.value || null;
}

function authCacheSet(key, value, ttlMs = 60000) {
  const safeKey = String(key || "").trim();
  if (!safeKey) return;
  while (AUTH_CACHE.size >= AUTH_CACHE_MAX) {
    const oldest = AUTH_CACHE.keys().next().value;
    if (!oldest) break;
    AUTH_CACHE.delete(oldest);
  }
  AUTH_CACHE.set(safeKey, { value, expires_at_ms: Date.now() + Math.max(1000, ttlMs) });
}

async function requireAuthenticatedUserContext(request, env) {
  const token = readBearerToken(request);
  if (!token) return { error: json({ ok: false, error: "missing_bearer_token" }, 401, env) };
  const currentIpScope = requestClientIpScope(request);
  const cacheKey = `${token}:${currentIpScope}`;
  const cached = authCacheGet(cacheKey);
  if (cached) return cached;
  let access;
  try {
    access = await verifyJwt(token, requireSecret(env, "JWT_SIGNING_SECRET"));
  } catch (error) {
    const code = String(error && error.message || "invalid_access_token");
    return { error: json({ ok: false, error: code === "token_expired" ? "token_expired" : "invalid_access_token" }, 401, env) };
  }
  if (String(access && access.type || "") !== "access" || !access.sub) {
    return { error: json({ ok: false, error: "invalid_access_token" }, 401, env) };
  }
  const authMethod = String(access.auth_method || "").trim();
  const tokenIpScope = String(access.client_ip_scope || access.clientIpScope || "").trim();
  if (authMethod.toLowerCase() === "anonymous" && tokenIpScope && currentIpScope && tokenIpScope !== currentIpScope) {
    return { error: json({ ok: false, error: "anonymous_ip_scope_changed" }, 401, env) };
  }
  const result = {
    db: requireDb(env),
    user: {
      id: String(access.sub || "").trim(),
      email: String(access.email || "").trim(),
      status: "",
    },
    access,
    authMethod,
    deviceId: normalizeDeviceId(access.device_id || request.headers.get("X-Planetka-Device-Id") || ""),
    tokenSource: "bearer_lightweight",
  };
  authCacheSet(cacheKey, result);
  return result;
}

async function resolveTileSessionAuth(_request, env, auth) {
  const db = requireDb(env);
  const userId = String(auth && auth.user && auth.user.id || "").trim();
  if (!userId) {
    return { error: json({ ok: false, error: "invalid_access_token" }, 401, env) };
  }
  const row = await db.prepare(
    `
      SELECT id, email, status
      FROM users
      WHERE id = ?
      LIMIT 1
    `,
  ).bind(userId).first();
  if (!row || !row.id) {
    return { error: json({ ok: false, error: "user_not_found" }, 404, env) };
  }
  if (String(row.status || "").trim().toLowerCase() === "blocked") {
    return { error: json({ ok: false, error: "session_blocked", message: "Planetka Cloud access is blocked. Contact info@planetka.io." }, 403, env) };
  }
  return {
    ...auth,
    user: {
      id: String(row.id || "").trim(),
      email: String(row.email || auth.user.email || "").trim(),
      status: "",
    },
  };
}

function resolveTileSessionTokenTtlSeconds(env = {}) {
  const parsed = Number(env.TILE_SESSION_TOKEN_TTL_SECONDS || DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS);
  return Math.min(1800, Math.max(60, Number.isFinite(parsed) ? Math.floor(parsed) : DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS));
}

function normalizeResolveId(value) {
  return String(value || "").trim().slice(0, 128);
}

async function issueTileSessionToken(env, auth, requestedQualityMode, requestedResolveId = "", options = {}) {
  const qualityMode = normalizeQualityMode(requestedQualityMode);
  const ttlSeconds = resolveTileSessionTokenTtlSeconds(env);
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const resolveId = normalizeResolveId(requestedResolveId) || crypto.randomUUID();
  const payload = {
    type: "tile_session",
    sub: String(auth && auth.user && auth.user.id || "").trim(),
    email: String(auth && auth.user && auth.user.email || "").trim(),
    quality_mode: qualityMode,
    resolve_id: resolveId,
    auth_method: String(auth && auth.authMethod || "").trim(),
    device_id: String(auth && auth.deviceId || "").trim(),
    client_ip_scope: String(auth && auth.access && (auth.access.client_ip_scope || auth.access.clientIpScope) || "").trim(),
    scene_id: String(options && options.sceneId || "").trim(),
    allowed_tile_files: Array.isArray(options && options.allowedTileFiles)
      ? options.allowedTileFiles.map((value) => String(value || "").trim()).filter(Boolean).slice(0, 128)
      : [],
    exp,
  };
  const token = await signJwt(payload, requireSecret(env, "JWT_SIGNING_SECRET"));
  return {
    token,
    resolveId,
    qualityMode,
    expiresInSeconds: ttlSeconds,
    expiresAt: new Date(exp * 1000).toISOString(),
    exp,
  };
}

async function readTileSessionClaims(request, env) {
  const rawToken = String(request.headers.get("X-Planetka-Tile-Token") || "").trim();
  if (!rawToken) return { claims: null };
  const currentIpScope = requestClientIpScope(request);
  const cacheKey = `tile:${rawToken}:${currentIpScope}`;
  const cached = authCacheGet(cacheKey);
  if (cached) return { claims: cached };
  let payload;
  try {
    payload = await verifyJwt(rawToken, requireSecret(env, "JWT_SIGNING_SECRET"));
  } catch (error) {
    const code = String(error && error.message || "invalid_tile_session_token");
    return { error: json({ ok: false, error: code === "token_expired" ? "tile_session_token_expired" : "invalid_tile_session_token" }, 401, env) };
  }
  if (String(payload && payload.type || "") !== "tile_session" || !payload.sub) {
    return { error: json({ ok: false, error: "invalid_tile_session_token" }, 401, env) };
  }
  const authMethod = String(payload.auth_method || "").trim();
  const tokenIpScope = String(payload.client_ip_scope || payload.clientIpScope || "").trim();
  if (authMethod.toLowerCase() === "anonymous" && tokenIpScope && currentIpScope && tokenIpScope !== currentIpScope) {
    return { error: json({ ok: false, error: "anonymous_ip_scope_changed" }, 401, env) };
  }
  const claims = {
    userId: String(payload.sub || "").trim(),
    userEmail: String(payload.email || "").trim(),
    qualityMode: normalizeQualityMode(payload.quality_mode || ""),
    resolveId: normalizeResolveId(payload.resolve_id || ""),
    authMethod,
    deviceId: normalizeDeviceId(payload.device_id || ""),
    sceneId: String(payload.scene_id || payload.sceneId || "").trim(),
    allowedTileFiles: Array.isArray(payload.allowed_tile_files || payload.allowedTileFiles)
      ? (payload.allowed_tile_files || payload.allowedTileFiles).map((value) => String(value || "").trim()).filter(Boolean).slice(0, 128)
      : [],
  };
  authCacheSet(cacheKey, claims);
  return { claims };
}

function resolveTileCacheControl(env) {
  const browserMaxAge = Math.min(MAX_TILE_MAX_AGE_SECONDS, parseNonNegativeInteger(env.TILE_BROWSER_MAX_AGE_SECONDS, DEFAULT_TILE_BROWSER_MAX_AGE_SECONDS));
  const edgeMaxAge = Math.min(MAX_TILE_MAX_AGE_SECONDS, Math.max(browserMaxAge, parseNonNegativeInteger(env.TILE_EDGE_MAX_AGE_SECONDS, DEFAULT_TILE_EDGE_MAX_AGE_SECONDS)));
  const immutable = String(env.TILE_CACHE_IMMUTABLE ?? "1").trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(immutable)
    ? `public, max-age=${browserMaxAge}, s-maxage=${edgeMaxAge}, immutable`
    : `public, max-age=${browserMaxAge}, s-maxage=${edgeMaxAge}`;
}

async function dbRun(db, sql, bindings = []) {
  return db.prepare(sql).bind(...bindings).run();
}

async function dbGet(db, sql, bindings = []) {
  return db.prepare(sql).bind(...bindings).first();
}

async function dbAll(db, sql, bindings = []) {
  const result = await db.prepare(sql).bind(...bindings).all();
  return Array.isArray(result && result.results) ? result.results : [];
}

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

async function ensureResolveUsageTables(db) {
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

function isoFromUnix(unixSeconds) {
  return new Date(Math.max(0, clampNonNegativeInt(unixSeconds)) * 1000).toISOString();
}

async function recordResolveUsageRollups(db, payload) {
  const createdAtUnix = clampNonNegativeInt(payload.created_at_unix || Math.floor(Date.now() / 1000));
  const hourStart = Math.floor(createdAtUnix / 3600) * 3600;
  const dayStart = Math.floor(createdAtUnix / 86400) * 86400;
  const userId = String(payload.user_id || "unknown").trim() || "unknown";
  const userEmail = normalizeEmail(payload.user_email || "");
  const bytesServed = clampNonNegativeInt(payload.bytes_served);
  const taggedRequest = String(payload.resolve_id || "").trim() ? 1 : 0;
  const writeRollup = async (tableName, startColumn, labelColumn, startUnix) => {
    await dbRun(
      db,
      `
        INSERT INTO ${tableName} (
          ${startColumn}, ${labelColumn}, user_id, user_email,
          request_count, bytes_served, error_count, cache_hit_count, tagged_request_count, last_event_unix
        ) VALUES (?, ?, ?, ?, 1, ?, 0, 0, ?, ?)
        ON CONFLICT(${startColumn}, user_id) DO UPDATE SET
          user_email = excluded.user_email,
          request_count = ${tableName}.request_count + 1,
          bytes_served = ${tableName}.bytes_served + excluded.bytes_served,
          tagged_request_count = ${tableName}.tagged_request_count + excluded.tagged_request_count,
          last_event_unix = CASE
            WHEN excluded.last_event_unix > ${tableName}.last_event_unix THEN excluded.last_event_unix
            ELSE ${tableName}.last_event_unix
          END
      `,
      [startUnix, isoFromUnix(startUnix), userId, userEmail, bytesServed, taggedRequest, createdAtUnix],
    );
  };
  await writeRollup("tile_request_rollup_hourly_account", "bucket_start_unix", "bucket_start", hourStart);
  await writeRollup("tile_request_rollup_daily_account", "day_start_unix", "day_start", dayStart);
}

async function recordResolveSummaryEvent(db, payload = {}) {
  await ensureResolveUsageTables(db);
  const userId = String(payload.user_id || "").trim();
  const resolveId = normalizeResolveId(payload.resolve_id || "");
  if (!userId || !resolveId) return { stored: false };
  const createdAt = String(payload.created_at || nowIso());
  const createdAtUnix = clampNonNegativeInt(payload.created_at_unix || Math.floor(Date.now() / 1000));
  const eventId = `resolve:${userId}:${resolveId}`.slice(0, 512);
  const insertResult = await dbRun(
    db,
    `
      INSERT OR IGNORE INTO tile_request_events (
        id, created_at, created_at_unix, user_id, user_email, resolve_id, method, path, folder, file_name,
        tile_key, quality_mode, status_code, bytes_served, cache_status, duration_ms, cf_ray, cf_country, client_ip, error_code
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      eventId,
      createdAt,
      createdAtUnix,
      userId,
      normalizeEmail(payload.user_email || ""),
      resolveId,
      "RESOLVE",
      String(payload.path || "/tiles/resolve-summary"),
      "",
      "",
      "",
      normalizeQualityMode(payload.quality_mode || payload.qualityMode || ""),
      200,
      clampNonNegativeInt(payload.bytes_served),
      "SUMMARY",
      clampNonNegativeInt(payload.duration_ms),
      "",
      "",
      "",
      "",
    ],
  );
  const changes = Number(insertResult && insertResult.meta && insertResult.meta.changes || 0);
  if (changes > 0) {
    await recordResolveUsageRollups(db, {
      ...payload,
      created_at_unix: createdAtUnix,
      user_id: userId,
      resolve_id: resolveId,
    });
  }
  return { stored: changes > 0 };
}

const TILE_DEPS = {
  clampNonNegativeInt,
  dbAll,
  dbGet,
  dbRun,
  issueTileSessionToken,
  json,
  normalizeDeviceId,
  normalizeQualityMode,
  normalizeResolveId,
  nowIso,
  parseJson,
  readTileSessionClaims,
  recordResolveSummaryEvent,
  requireAuthenticatedUserContext,
  requireDb,
  resolveTileSessionAuth,
  resolveTileCacheControl,
};

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }
    const url = new URL(request.url);
    const path = url.pathname;
    try {
      if (path === "/health") {
        return json({ ok: true, worker: "planetka-tiles" }, 200, env);
      }
      if (path === "/tiles/session" && request.method === "POST") {
        return await handleTileSessionStart(request, env, TILE_DEPS);
      }
      if (path === "/tiles/resolve-summary" && request.method === "POST") {
        return await handleResolveSummary(request, env, TILE_DEPS);
      }
      if ((request.method === "GET" || request.method === "HEAD") && path.startsWith("/tiles/")) {
        return await handleTileRequest(request, env, path, ctx, TILE_DEPS);
      }
      return json({ ok: false, error: "not_found", path }, 404, env);
    } catch (error) {
      console.error("planetka.tiles.request_error", JSON.stringify({ path, method: request.method, error: String(error && error.message || "internal_error") }));
      return json({ ok: false, error: "internal_error" }, 500, env);
    }
  },
};
