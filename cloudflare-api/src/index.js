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
const DEFAULT_UPGRADE_URL = "https://www.planetka.io/signup";
const DEFAULT_CONTACT_URL = "https://www.planetka.io/contact";
const DEFAULT_TERMS_URL = "https://api.planetka.io/legal/terms-of-service.pdf";
const DEFAULT_PRIVACY_URL = "https://api.planetka.io/legal/privacy-policy.pdf";
const DEFAULT_LEGAL_VERSION = "2026-03-26";
let manualCreditModeCache = "";
let userConsentColumnsReady = false;

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.APP_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
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

function base64UrlEncode(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlEncodeString(value) {
  return base64UrlEncode(encoder.encode(value));
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

function resolvePlanCode(user, subscription) {
  const userStatus = String(user && user.status ? user.status : "").trim().toLowerCase();
  if (userStatus === PLAN_CODE_PLANETKA_STUDIO || userStatus === "studio") {
    return PLAN_CODE_PLANETKA_STUDIO;
  }
  if (userStatus === PLAN_CODE_PLANETKA_PRO || userStatus === "pro") {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (subscription && isSubscriptionActive(subscription) && String(subscription.stripe_subscription_id || "").trim()) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (userStatus === PLAN_CODE_PLANETKA || userStatus === "free" || userStatus === "personal") {
    return PLAN_CODE_PLANETKA;
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
  const cfg = buildPlanConfig(env);
  const planCode = resolvePlanCode(user, subscription);
  const period = await ensureCurrentUsagePeriod(db, user.id, planCode, cfg);
  const includedLimitBytesBase = clampNonNegativeInt(period && period.included_limit_bytes);
  const includedConsumedBytes = clampNonNegativeInt(period && period.included_consumed_bytes);
  const includedRemainingBytesBase = Math.max(0, includedLimitBytesBase - includedConsumedBytes);
  const nowTs = nowIso();
  const manualCreditRemainingBytes = await getManualCreditRemaining(db, user.id, nowTs);
  // Product UX uses one monthly pool. Manual credits are folded into monthly allowance.
  const includedLimitBytes = Math.max(0, includedLimitBytesBase + manualCreditRemainingBytes);
  const includedRemainingBytes = Math.max(0, includedRemainingBytesBase + manualCreditRemainingBytes);
  const totalRemainingBytes = includedRemainingBytes;
  const downloadedPeriodBytes = await getDownloadedPeriodBytes(
    db,
    user.id,
    String(period.period_start || nowTs),
    String(period.period_end || nowTs),
  );
  const warningState = computeWarningState(totalRemainingBytes, includedLimitBytes, cfg);
  const exhausted = totalRemainingBytes <= 0;

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
      period: "monthly",
      period_end: String(period.period_end || ""),
      warning_state: warningState,
      exhausted,
      counting_rule: cfg.countingRule,
    },
    includedRemainingBytesBase,
    periodId: String(period.id || ""),
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
  const chargeBytes = clampNonNegativeInt(bytesUsed);
  if (chargeBytes <= 0) {
    return buildAllowanceState(db, user, subscription, env);
  }

  const state = await buildAllowanceState(db, user, subscription, env);
  if (state.dataAllowance.total_remaining_bytes < chargeBytes) {
    throw new Error("allowance_exhausted");
  }

  let remaining = chargeBytes;
  const useIncluded = Math.min(
    clampNonNegativeInt(state.includedRemainingBytesBase),
    remaining,
  );
  const nowTimestamp = nowIso();
  if (useIncluded > 0) {
    await dbRun(
      db,
      `
        UPDATE usage_periods
        SET
          included_consumed_bytes = included_consumed_bytes + ?,
          updated_at = ?
        WHERE id = ?
      `,
      [useIncluded, nowTimestamp, state.periodId],
    );
    remaining -= useIncluded;
  }
  if (remaining > 0) {
    const consumedManual = await consumeManualCredits(db, user.id, remaining, nowTimestamp);
    remaining -= consumedManual;
  }
  if (remaining > 0) {
    throw new Error("allowance_exhausted");
  }

  await dbRun(
    db,
    `
      INSERT INTO usage_charges (id, user_id, period_id, bytes_used, created_at)
      VALUES (?, ?, ?, ?, ?)
    `,
    [crypto.randomUUID(), user.id, state.periodId, chargeBytes, nowTimestamp],
  );

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

async function findSubscriptionByUserId(db, userId) {
  return dbGet(
    db,
    `
      SELECT
        id,
        user_id,
        status,
        trial_ends_at,
        renews_at,
        current_period_end,
        stripe_customer_id,
        stripe_subscription_id
      FROM subscriptions
      WHERE user_id = ?
      ORDER BY updated_at DESC, created_at DESC
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

async function upsertUserByEmail(db, email, status = PLAN_CODE_PLANETKA, options = {}) {
  const normalizedEmail = normalizeEmail(email);
  await ensureUserConsentColumns(db);
  let user = await findUserByEmail(db, normalizedEmail);
  if (user) {
    const currentStatus = String(user.status || "").trim().toLowerCase();
    const nextStatus = String(status || "").trim().toLowerCase() || PLAN_CODE_PLANETKA;
    // Never downgrade paid plans when this helper is called from other flows.
    const protectedStatus = (
      (currentStatus === PLAN_CODE_PLANETKA_PRO || currentStatus === PLAN_CODE_PLANETKA_STUDIO)
      && nextStatus === PLAN_CODE_PLANETKA
    )
      ? currentStatus
      : nextStatus;
    await dbRun(
      db,
      `UPDATE users SET status = ? WHERE id = ?`,
      [protectedStatus, user.id],
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
        privacy_version
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      id,
      normalizedEmail,
      status,
      createdAt,
      termsAcceptedAt,
      privacyAcceptedAt,
      termsVersion,
      privacyVersion,
    ],
  );
  user = await findUserByEmail(db, normalizedEmail);
  return user;
}

function isSubscriptionActive(subscription) {
  if (!subscription) {
    return false;
  }
  const status = String(subscription.status || "").toLowerCase();
  if (status === "active" || status === "trialing") {
    return true;
  }
  return false;
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

async function sendSecurityAlertEmail(env, subject, lines) {
  const apiKey = String(env.EMAIL_API_KEY || "").trim();
  if (!apiKey) {
    console.error("security.alert.email_missing_api_key", JSON.stringify({ subject }));
    return false;
  }

  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const to = String(env.SECURITY_ALERT_EMAIL || "info@planetka.io").trim() || "info@planetka.io";
  const bodyLines = Array.isArray(lines) ? lines.map((line) => String(line)) : [String(lines || "")];
  const textBody = bodyLines.join("\n");
  const htmlBody = `<pre style="white-space:pre-wrap;font-family:monospace;">${textBody
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")}</pre>`;

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject: String(subject || "Planetka Security Alert"),
      text: textBody,
      html: htmlBody,
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    console.error(
      "security.alert.email_failed",
      JSON.stringify({ status: response.status, body: String(body || "").slice(0, 500) }),
    );
    return false;
  }
  return true;
}

async function blockUserForAbuse(db, user, env, details = {}) {
  if (!user || !user.id) {
    return;
  }
  const blockedAt = nowIso();
  await dbRun(db, `UPDATE users SET status = 'blocked' WHERE id = ?`, [user.id]);
  await dbRun(
    db,
    `UPDATE refresh_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL`,
    [blockedAt, user.id],
  );

  const email = String(user.email || "").trim();
  const detailLines = [
    "Planetka security block triggered.",
    `time_utc=${blockedAt}`,
    `user_id=${user.id}`,
    `email=${email || "unknown"}`,
    `reason=${String(details.reason || "unknown")}`,
    `path=${String(details.path || "")}`,
    `file_name=${String(details.file_name || "")}`,
    `z=${String(details.z ?? "")}`,
    `d=${String(details.d ?? "")}`,
    `plan_code=${String(details.plan_code || "")}`,
    `ip=${String(details.ip || "")}`,
    `user_agent=${String(details.user_agent || "")}`,
  ];
  console.error("security.account_blocked", JSON.stringify({ user_id: user.id, email, details }));
  try {
    await sendSecurityAlertEmail(env, "Planetka Security: account blocked for full-quality abuse", detailLines);
  } catch (error) {
    console.error("security.alert.email_exception", String(error && error.message ? error.message : error));
  }
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

async function createAccessToken(env, user, subscription) {
  const secret = requireSecret(env, "JWT_SIGNING_SECRET");
  const exp = Math.floor(Date.now() / 1000) + (60 * 60);
  return signJwt(
    {
      type: "access",
      sub: user.id,
      email: user.email,
      subscription_status: subscription ? subscription.status : "inactive",
      exp,
    },
    secret,
  );
}

async function createRefreshSession(db, userId) {
  const refreshToken = randomToken(48);
  const refreshHash = await sha256Hex(refreshToken);
  const refreshSessionId = crypto.randomUUID();
  const createdAt = nowIso();
  const expiresAt = addDaysIso(30);
  await dbRun(
    db,
    `
      INSERT INTO refresh_sessions (
        id,
        user_id,
        refresh_token_hash,
        expires_at,
        created_at
      ) VALUES (?, ?, ?, ?, ?)
    `,
    [refreshSessionId, userId, refreshHash, expiresAt, createdAt],
  );
  return refreshToken;
}

function stripeSignatureHeaderParts(header) {
  const parts = String(header || "").split(",");
  const values = {};
  for (const part of parts) {
    const [key, value] = part.split("=", 2);
    if (key && value) {
      values[key.trim()] = value.trim();
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
  const timestamp = String(parts.t || "");
  const expectedSignature = String(parts.v1 || "");
  if (!timestamp || !expectedSignature) {
    throw new Error("invalid_stripe_signature_header");
  }

  const signedPayload = `${timestamp}.${rawBody}`;
  const computed = await hmacSha256Hex(secret, signedPayload);
  if (computed !== expectedSignature) {
    throw new Error("invalid_stripe_signature");
  }

  return JSON.parse(rawBody);
}

async function fetchStripeSubscription(env, subscriptionId) {
  const secretKey = requireSecret(env, "STRIPE_SECRET_KEY");
  const response = await fetch(`https://api.stripe.com/v1/subscriptions/${encodeURIComponent(subscriptionId)}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${secretKey}`,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`stripe_subscription_fetch_failed_${response.status}_${body}`);
  }
  return response.json();
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

async function handleAuthStart(request, env) {
  const db = requireDb(env);
  await ensureUserConsentColumns(db);
  const body = await parseJson(request);
  const email = normalizeEmail(body.email);
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
    });
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
  const body = await parseJson(request);
  const token = String(body.token || "").trim();
  const deviceCode = String(body.device_code || "").trim();
  if (!token) {
    return json({ ok: false, error: "missing_token" }, 400, env);
  }

  const tokenHash = await sha256Hex(token);
  const magicLink = await dbGet(
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

  const subscription = await findSubscriptionByUserId(db, magicLink.user_id);
  const subscriptionStatus = subscription ? String(subscription.status || "inactive") : "inactive";

  const usedAt = nowIso();
  await dbRun(
    db,
    `UPDATE magic_links SET used_at = ? WHERE id = ?`,
    [usedAt, magicLink.id],
  );
  await dbRun(
    db,
    `UPDATE users SET last_login_at = ? WHERE id = ?`,
    [usedAt, magicLink.user_id],
  );

  const user = {
    id: magicLink.user_id,
    email: magicLink.email,
    status: magicLink.user_status || PLAN_CODE_PLANETKA,
  };
  const accessToken = await createAccessToken(env, user, subscription);
  const refreshToken = await createRefreshSession(db, magicLink.user_id);
  const accountState = await buildAllowanceState(db, user, subscription, env);

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
          subscription ? subscription.renews_at : null,
          subscription ? subscription.trial_ends_at : null,
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
      renews_at: subscription ? subscription.renews_at : null,
      trial_ends_at: subscription ? subscription.trial_ends_at : null,
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

  const subscription = await findSubscriptionByUserId(db, session.user_id);
  const subscriptionStatus = subscription ? String(subscription.status || "inactive") : "inactive";

  await dbRun(
    db,
    `UPDATE refresh_sessions SET revoked_at = ? WHERE id = ?`,
    [nowIso(), session.id],
  );
  const accessToken = await createAccessToken(
    env,
    { id: session.user_id, email: session.email, status: session.status || "active" },
    subscription,
  );
  const nextRefreshToken = await createRefreshSession(db, session.user_id);
  const accountState = await buildAllowanceState(
    db,
    { id: session.user_id, email: session.email, status: session.status || "active" },
    subscription,
    env,
  );

  return json(
    {
      ok: true,
      access_token: accessToken,
      refresh_token: nextRefreshToken,
      email: session.email,
      subscription_status: subscriptionStatus,
      renews_at: subscription ? subscription.renews_at : null,
      trial_ends_at: subscription ? subscription.trial_ends_at : null,
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

  const user = await dbGet(
    db,
    `
      SELECT id, email, status, created_at, last_login_at
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
  const subscription = await findSubscriptionByUserId(db, user.id);
  const accountState = await buildAllowanceState(db, user, subscription, env);

  return json(
    {
      ok: true,
      email: user.email,
      user_status: user.status,
      subscription_status: subscription ? subscription.status : "inactive",
      trial_ends_at: subscription ? subscription.trial_ends_at : null,
      renews_at: subscription ? subscription.renews_at : null,
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
  const body = await parseJson(request);
  const deviceCode = String(body.device_code || "").trim();
  if (!deviceCode) {
    return json({ ok: false, error: "missing_device_code" }, 400, env);
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
    const user = await findUserByEmail(db, normalizeEmail(session.email));
    const subscription = user ? await findSubscriptionByUserId(db, user.id) : null;
    if (user) {
      const accountState = await buildAllowanceState(db, user, subscription, env);
      accountPayload = serializeAccountState(accountState);
    }
  } catch (_error) {
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

function renderDeviceLoginPage(env, deviceCode = "") {
  const termsUrl = String(env.TERMS_URL || DEFAULT_TERMS_URL).trim() || DEFAULT_TERMS_URL;
  const privacyUrl = String(env.PRIVACY_URL || DEFAULT_PRIVACY_URL).trim() || DEFAULT_PRIVACY_URL;
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
      .optin {
        margin-top: 12px;
        padding: 12px;
        border-radius: 12px;
        border: 1px solid rgba(148, 163, 184, 0.28);
        background: rgba(15, 23, 42, 0.6);
      }
      .optin label {
        display: flex;
        gap: 10px;
        align-items: flex-start;
        margin: 0;
        font-size: 14px;
        line-height: 1.4;
        color: #e2e8f0;
      }
      .optin input[type="checkbox"] {
        width: 18px;
        height: 18px;
        margin-top: 1px;
        flex: 0 0 auto;
      }
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
    </style>
  </head>
  <body>
    <div class="card">
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
      <div class="optin">
        <label for="planetka-news-optin">
          <input id="planetka-news-optin" type="checkbox" />
          <span>Opt in to receive news about Planetka by email.</span>
        </label>
      </div>
      <button id="planetka-send-link">Send Login Link</button>
      <div id="planetka-status" class="status"></div>
    </div>
    <script>
      (() => {
        const API = "${String(env.API_BASE_URL || "https://api.planetka.io").trim()}";
        const DEVICE_CODE = ${JSON.stringify(deviceCode)};
        const email = document.getElementById("planetka-email");
        const consent = document.getElementById("planetka-consent");
        const newsOptIn = document.getElementById("planetka-news-optin");
        const button = document.getElementById("planetka-send-link");
        const status = document.getElementById("planetka-status");
        let busy = false;

        function show(message, type = "info") {
          status.textContent = message || "";
          status.style.display = message ? "block" : "none";
          if (type === "error") {
            status.style.background = "rgba(127,29,29,.18)";
            status.style.border = "1px solid rgba(248,113,113,.35)";
            status.style.color = "#fecaca";
            return;
          }
          if (type === "success") {
            status.style.background = "rgba(20,83,45,.18)";
            status.style.border = "1px solid rgba(74,222,128,.35)";
            status.style.color = "#bbf7d0";
            return;
          }
          status.style.background = "rgba(30,41,59,.35)";
          status.style.border = "1px solid rgba(148,163,184,.25)";
          status.style.color = "#e2e8f0";
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
          busy = true;
          button.disabled = true;
          button.textContent = "Verifying...";
          show("Verifying login...", "info");
          try {
            await post("/auth/verify", { token, device_code: DEVICE_CODE });
            button.textContent = "Verified";
            show("Verified. Blender is now connected. You can return to Blender.", "success");
          } catch (error) {
            console.error("planetka auth/verify failed", error);
            show("This login link is invalid or expired. Please request a new one.", "error");
            busy = false;
            button.disabled = false;
            button.textContent = "Send Login Link";
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
  if (!deviceCode) {
    return html(renderDeviceLoginPage(env, ""), 200, env);
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
    return html(renderDeviceLoginPage(env, ""), 410, env);
  }

  return html(renderDeviceLoginPage(env, deviceCode), 200, env);
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
    // Shared edge cache enabled for immutable tile assets.
    "Cache-Control": "public, max-age=3600, s-maxage=86400",
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
  const user = await findUserById(db, access.sub);
  if (!user) {
    return json({ ok: false, error: "user_not_found" }, 404, env);
  }
  if (isBlockedStatus(user.status)) {
    return blockedAccountResponse(env);
  }
  const subscription = await findSubscriptionByUserId(db, access.sub);
  const planCode = resolvePlanCode(user, subscription);

  const parts = path.replace(/^\/tiles\//, "").split("/");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    return json({ ok: false, error: "invalid_tile_path" }, 400, env);
  }

  const folder = decodeURIComponent(parts[0]);
  const fileName = decodeURIComponent(parts[1]);
  if (
    folder.includes("/") ||
    fileName.includes("/") ||
    folder.includes("..") ||
    fileName.includes("..")
  ) {
    return json({ ok: false, error: "invalid_tile_path" }, 400, env);
  }
  const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
  const key = prefix ? `${prefix}/${folder}/${fileName}` : `${folder}/${fileName}`;

  const parsedTile = parseTileQualityFromFileName(fileName);
  if (request.method === "GET" && planCode === PLAN_CODE_PLANETKA && parsedTile && parsedTile.z === parsedTile.d) {
    await blockUserForAbuse(db, user, env, {
      reason: "free_account_full_quality_tile_request",
      path,
      file_name: fileName,
      z: parsedTile.z,
      d: parsedTile.d,
      plan_code: planCode,
      ip: request.headers.get("CF-Connecting-IP") || "",
      user_agent: request.headers.get("User-Agent") || "",
    });
    return blockedAccountResponse(
      env,
      "Attempt to download full quality texture under Free Account licence detected. Account Blocked.",
    );
  }

  if (request.method === "HEAD") {
    const objectHead = await env.PLANETKA_DATA.head(key);
    if (!objectHead) {
      return new Response(null, { status: 404, headers: corsHeaders(env) });
    }
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

  const allowanceState = await buildAllowanceState(db, user, subscription, env);
  if (allowanceState.dataAllowance.total_remaining_bytes < objectSize) {
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
    updatedAllowance = await consumeAllowanceBytes(db, user, subscription, env, objectSize);
  } catch (error) {
    if (String(error && error.message || "") === "allowance_exhausted") {
      return json(
        {
          ok: false,
          error: "allowance_exhausted",
          message: "Data allowance is exhausted. Contact Planetka for more data.",
          ...serializeAccountState(await buildAllowanceState(db, user, subscription, env)),
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
    "Cache-Control": "public, max-age=3600, s-maxage=86400",
    "X-Planetka-Remaining-Bytes": String(updatedAllowance.dataAllowance.total_remaining_bytes),
    "X-Planetka-Warning-State": String(updatedAllowance.dataAllowance.warning_state || "ok"),
    "X-Planetka-Cache": cacheStatus,
  });
  if (etag) {
    responseHeaders.set("ETag", etag);
  }

  return new Response(responseBody, {
    status: 200,
    headers: responseHeaders,
  });
}

async function handleStripeWebhook(request, env) {
  const db = requireDb(env);
  const rawBody = await request.text();
  const event = await verifyStripeWebhook(request, env, rawBody);
  const eventType = String(event.type || "");
  console.log("stripe.webhook.received", JSON.stringify({ event_type: eventType }));

  if (eventType !== "checkout.session.completed") {
    console.log("stripe.webhook.ignored", JSON.stringify({ event_type: eventType }));
    return json({ ok: true, ignored: true, event_type: eventType }, 200, env);
  }

  const session = event.data && event.data.object ? event.data.object : null;
  if (!session) {
    return json({ ok: false, error: "missing_checkout_session" }, 400, env);
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

  const user = await upsertUserByEmail(db, email, PLAN_CODE_PLANETKA_PRO);
  const stripeCustomerId = String(session.customer || "").trim() || null;
  const stripeSubscriptionId = String(session.subscription || "").trim() || null;
  const createdAt = nowIso();
  let trialEndsAt = null;
  let renewsAt = null;
  let currentPeriodEnd = null;
  let subscriptionStatus = "active";

  if (stripeSubscriptionId) {
    const stripeSubscription = await fetchStripeSubscription(env, stripeSubscriptionId);
    subscriptionStatus = String(stripeSubscription.status || subscriptionStatus || "active");
    trialEndsAt = stripeSubscription.trial_end
      ? new Date(Number(stripeSubscription.trial_end) * 1000).toISOString()
      : null;
    renewsAt = stripeSubscription.current_period_end
      ? new Date(Number(stripeSubscription.current_period_end) * 1000).toISOString()
      : null;
    currentPeriodEnd = renewsAt;
  }

  let existingSubscription = null;
  if (stripeSubscriptionId) {
    existingSubscription = await dbGet(
      db,
      `
        SELECT id
        FROM subscriptions
        WHERE stripe_subscription_id = ?
        LIMIT 1
      `,
      [stripeSubscriptionId],
    );
  }

  if (existingSubscription) {
    await dbRun(
      db,
      `
        UPDATE subscriptions
        SET
          user_id = ?,
          stripe_customer_id = ?,
          status = ?,
          trial_ends_at = COALESCE(trial_ends_at, ?),
          renews_at = COALESCE(renews_at, ?),
          current_period_end = COALESCE(current_period_end, ?),
          updated_at = ?
        WHERE id = ?
      `,
      [
        user.id,
        stripeCustomerId,
        subscriptionStatus,
        trialEndsAt,
        renewsAt,
        currentPeriodEnd,
        createdAt,
        existingSubscription.id,
      ],
    );
  } else {
    await dbRun(
      db,
      `
        INSERT INTO subscriptions (
          id,
          user_id,
        stripe_customer_id,
        stripe_subscription_id,
        status,
        trial_ends_at,
        renews_at,
          current_period_end,
          created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        crypto.randomUUID(),
        user.id,
        stripeCustomerId,
        stripeSubscriptionId,
        subscriptionStatus,
        trialEndsAt,
        renewsAt,
        currentPeriodEnd,
        createdAt,
        createdAt,
      ],
    );
  }

  console.log(
    "stripe.webhook.processed",
    JSON.stringify({
      event_type: eventType,
      email,
      stripe_customer_id: stripeCustomerId,
      stripe_subscription_id: stripeSubscriptionId,
      subscription_status: subscriptionStatus,
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

      if (request.method === "POST" && path === "/auth/start") {
        return await handleAuthStart(request, env);
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
};
