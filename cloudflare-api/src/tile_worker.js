import { corsHeaders, json } from "./worker/responses.js";
import {
  isProfessionalPlan,
  normalizeQualityMode,
  normalizeRequestedPlan,
  personalFreeLocationBlockedMessage,
  personalFreeRegionForPoint,
} from "./worker/entitlements.js";
import {
  parseBooleanFlag,
  parseNonNegativeInteger,
} from "./worker/env.js";
import {
  handleTileRequest,
  handleTileSessionStart,
} from "./worker/tile_routes.js";
import {
  normalizeTileKeys,
} from "./worker/tile_sessions.js";

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
  const cached = authCacheGet(token);
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
  const planCode = normalizeRequestedPlan(access.plan_code || access.user_status || access.plan || "");
  const qualityAccessPlanCode = normalizeRequestedPlan(access.quality_access_plan_code || access.qualityAccessPlanCode || planCode);
  const result = {
    db: requireDb(env),
    user: {
      id: String(access.sub || "").trim(),
      email: String(access.email || "").trim(),
      status: planCode,
    },
    access,
    planCode,
    qualityAccessPlanCode: qualityAccessPlanCode || planCode,
    authMethod: String(access.auth_method || "").trim(),
    apiKeyId: String(access.api_key_id || "").trim(),
    deviceId: normalizeDeviceId(access.device_id || request.headers.get("X-Planetka-Device-Id") || ""),
    devicePolicy: null,
    tokenSource: "bearer_lightweight",
  };
  authCacheSet(token, result);
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
  const status = String(row.status || "").trim().toLowerCase();
  if (status === "blocked") {
    return { error: json({ ok: false, error: "account_blocked", message: "Planetka account is blocked. Contact info@planetka.io." }, 403, env) };
  }
  const currentPlan = normalizeRequestedPlan(status);
  return {
    ...auth,
    user: {
      id: String(row.id || "").trim(),
      email: String(row.email || auth.user.email || "").trim(),
      status: currentPlan,
    },
    planCode: currentPlan,
    qualityAccessPlanCode: currentPlan,
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
  const planCode = normalizeRequestedPlan(auth && auth.planCode);
  const qualityAccessPlanCode = normalizeRequestedPlan(auth && (auth.qualityAccessPlanCode || auth.planCode));
  const creditEnforced = Boolean(options && options.creditEnforced);
  const ttlSeconds = resolveTileSessionTokenTtlSeconds(env);
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const resolveId = normalizeResolveId(requestedResolveId) || crypto.randomUUID();
  const payload = {
    type: "tile_session",
    sub: String(auth && auth.user && auth.user.id || "").trim(),
    email: String(auth && auth.user && auth.user.email || "").trim(),
    plan_code: qualityAccessPlanCode,
    stored_plan_code: planCode,
    quality_access_plan_code: qualityAccessPlanCode,
    quality_mode: qualityMode,
    resolve_id: resolveId,
    credit_protocol: String(options && options.creditProtocol || "").trim(),
    credit_enforced: creditEnforced,
    session_id: String(options && (options.sessionId || options.session_id) || "").trim(),
    personal_free_region: String(options && (options.personalFreeRegion || options.personal_free_region) || "").trim(),
    auth_method: String(auth && auth.authMethod || "").trim(),
    device_id: String(auth && auth.deviceId || "").trim(),
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
  const cached = authCacheGet(`tile:${rawToken}`);
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
  const claims = {
    userId: String(payload.sub || "").trim(),
    userEmail: String(payload.email || "").trim(),
    planCode: normalizeRequestedPlan(payload.plan_code || payload.user_status || ""),
    storedPlanCode: normalizeRequestedPlan(payload.stored_plan_code || payload.storedPlanCode || payload.plan_code || ""),
    qualityAccessPlanCode: normalizeRequestedPlan(payload.quality_access_plan_code || payload.qualityAccessPlanCode || payload.plan_code || ""),
    qualityMode: normalizeQualityMode(payload.quality_mode || ""),
    resolveId: normalizeResolveId(payload.resolve_id || ""),
    creditProtocol: String(payload.credit_protocol || payload.creditProtocol || "").trim(),
    creditEnforced: Boolean(payload.credit_enforced || payload.creditEnforced),
    sessionId: String(payload.session_id || payload.sessionId || "").trim(),
    personalFreeRegion: String(payload.personal_free_region || payload.personalFreeRegion || "").trim(),
    authMethod: String(payload.auth_method || "").trim(),
    deviceId: normalizeDeviceId(payload.device_id || ""),
  };
  authCacheSet(`tile:${rawToken}`, claims);
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

function requestClientIp(request) {
  return String(request.headers.get("CF-Connecting-IP") || request.headers.get("True-Client-IP") || request.headers.get("X-Forwarded-For") || "unknown").split(",")[0].trim() || "unknown";
}

function requestCountry(request) {
  const country = String(request.headers.get("CF-IPCountry") || "").trim().toUpperCase();
  return country && country !== "XX" && country !== "T1" ? country : "UNKNOWN";
}

function isTileEventQueueProducerEnabled(env = {}) {
  const raw = env.ENABLE_TILE_EVENT_QUEUE_PRODUCER;
  if (raw === undefined || raw === null || String(raw).trim() === "") return true;
  return parseBooleanFlag(raw);
}

function isTileHotPathMonitoringEnabled(env = {}) {
  return parseBooleanFlag(env.ENABLE_TILE_HOT_PATH_MONITORING);
}

const TILE_DEPS = {
  clampNonNegativeInt,
  createTileDownloadSession: null,
  isTileEventQueueProducerEnabled,
  isTileHotPathMonitoringEnabled,
  isProfessionalPlan,
  issueTileSessionToken,
  json,
  maybeSignalTileFarmingActivity: async () => {},
  normalizeDeviceId,
  normalizeQualityMode,
  normalizeRequestedPlan,
  normalizeResolveId,
  normalizeTileKeys,
  nowIso,
  personalFreeLocationBlockedMessage,
  personalFreeRegionForPoint,
  parseJson,
  readTileSessionClaims,
  recordPreviewUsageAndMaybeAlert: async () => ({ alerted: false }),
  recordTileRequestEvent: async () => {},
  requestClientIp,
  requestCountry,
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
