import {
  PLAN_CODE_PROFESSIONAL,
  normalizeRequestedPlan,
} from "./entitlements.js";

const LEMON_API_BASE = "https://api.lemonsqueezy.com/v1";
const LEMON_LICENSE_API_BASE = "https://api.lemonsqueezy.com/v1/licenses";
const LEMON_WEBHOOK_EVENTS_TABLE = "lemon_webhook_events";
const SCENE_PURCHASES_TABLE = "scene_full_quality_purchases";
const SCENE_PURCHASE_PENDING_TABLE = "scene_full_quality_purchase_pending";
const DEFAULT_PRO_PRICE_LABEL = "€349";
const DEFAULT_SCENE_PRICE_EUR = 15;

function textEncoder() {
  return new TextEncoder();
}

function bytesToHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeStringEquals(left, right) {
  const a = textEncoder().encode(String(left || ""));
  const b = textEncoder().encode(String(right || ""));
  if (a.length !== b.length) {
    return false;
  }
  let diff = 0;
  for (let index = 0; index < a.length; index += 1) {
    diff |= a[index] ^ b[index];
  }
  return diff === 0;
}

async function hmacSha256Hex(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    textEncoder().encode(String(secret || "")),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, textEncoder().encode(String(message || "")));
  return bytesToHex(new Uint8Array(signature));
}

async function verifyLemonSignature(request, rawBody, env, deps) {
  const signature = String(request.headers.get("X-Signature") || "").trim();
  if (!signature) {
    throw new Error("missing_lemon_signature");
  }
  const secret = deps.requireSecret(env, "LEMONSQUEEZY_WEBHOOK_SECRET");
  const digest = await hmacSha256Hex(secret, rawBody);
  if (!constantTimeStringEquals(digest, signature)) {
    throw new Error("invalid_lemon_signature");
  }
}

function boolFromEnv(value, fallback = false) {
  const raw = String(value ?? "").trim().toLowerCase();
  if (!raw) {
    return Boolean(fallback);
  }
  return ["1", "true", "yes", "on", "test"].includes(raw);
}

function lemonEnv(env, deps) {
  return {
    apiKey: deps.requireSecret(env, "LEMONSQUEEZY_API_KEY"),
    storeId: String(env.LEMONSQUEEZY_STORE_ID || "").trim(),
    proVariantId: String(env.LEMONSQUEEZY_PRO_VARIANT_ID || "").trim(),
    sceneProductId: String(env.LEMONSQUEEZY_SCENE_PRODUCT_ID || "").trim(),
    sceneVariantId: String(env.LEMONSQUEEZY_SCENE_VARIANT_ID || "").trim(),
    testMode: boolFromEnv(env.LEMONSQUEEZY_TEST_MODE, false),
    priceLabel: String(env.LEMONSQUEEZY_PRO_PRICE_LABEL || DEFAULT_PRO_PRICE_LABEL).trim() || DEFAULT_PRO_PRICE_LABEL,
  };
}

function requireLemonIds(config) {
  if (!config.storeId) {
    throw new Error("missing_lemonsqueezy_store_id");
  }
  if (!config.proVariantId) {
    throw new Error("missing_lemonsqueezy_pro_variant_id");
  }
}

function requireLemonSceneIds(config) {
  if (!config.storeId) {
    throw new Error("missing_lemonsqueezy_store_id");
  }
  if (!config.sceneVariantId) {
    throw new Error("missing_lemonsqueezy_scene_variant_id");
  }
}

function extractCheckoutUrl(payload) {
  return String(payload && payload.data && payload.data.attributes && payload.data.attributes.url || "").trim();
}

function extractCheckoutId(payload) {
  return String(payload && payload.data && payload.data.id || "").trim();
}

async function createLemonCheckout({ env, deps, user, config, variantId, checkoutData, customPriceCents = null, successPath = "/billing/lemonsqueezy/success" }) {
  const apiBaseUrl = String(env.API_BASE_URL || "https://api.planetka.io").trim().replace(/\/+$/, "");
  const envRedirectKey = successPath === "/billing/lemonsqueezy/scene-success"
    ? "LEMONSQUEEZY_SCENE_SUCCESS_URL"
    : "LEMONSQUEEZY_SUCCESS_URL";
  const redirectUrl = String(env[envRedirectKey] || `${apiBaseUrl}${successPath}`).trim();
  const userEmail = typeof deps.isSyntheticAnonymousEmail === "function" && deps.isSyntheticAnonymousEmail(user.email)
    ? ""
    : String(user.email || "").trim().toLowerCase();
  const finalCheckoutData = checkoutData && typeof checkoutData === "object"
    ? { ...checkoutData, custom: { ...(checkoutData.custom || {}) } }
    : {
      custom: {
        user_id: String(user.id || "").trim(),
        product: "planetka_pro",
      },
    };
  if (!finalCheckoutData.custom.user_id) {
    finalCheckoutData.custom.user_id = String(user.id || "").trim();
  }
  if (!finalCheckoutData.custom.product) {
    finalCheckoutData.custom.product = "planetka_pro";
  }
  if (userEmail && !finalCheckoutData.email) {
    finalCheckoutData.email = userEmail;
    if (!finalCheckoutData.custom.email) {
      finalCheckoutData.custom.email = userEmail;
    }
  }
  const selectedVariantId = String(variantId || config.proVariantId || "").trim();
  const attributes = {
    product_options: {
      enabled_variants: [Number(selectedVariantId)],
      redirect_url: redirectUrl,
    },
    checkout_options: {
      embed: false,
      media: true,
      logo: true,
      desc: true,
      discount: true,
    },
    checkout_data: finalCheckoutData,
    test_mode: Boolean(config.testMode),
    preview: false,
  };
  if (Number.isFinite(Number(customPriceCents)) && Number(customPriceCents) >= 0) {
    attributes.custom_price = Math.max(0, Math.round(Number(customPriceCents)));
  }
  const body = {
    data: {
      type: "checkouts",
      attributes,
      relationships: {
        store: { data: { type: "stores", id: String(config.storeId) } },
        variant: { data: { type: "variants", id: String(selectedVariantId) } },
      },
    },
  };
  const response = await fetch(`${LEMON_API_BASE}/checkouts`, {
    method: "POST",
    headers: {
      Accept: "application/vnd.api+json",
      "Content-Type": "application/vnd.api+json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify(body),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (!response.ok) {
    console.error("lemonsqueezy.checkout_create_failed", JSON.stringify({ status: response.status }));
    return { error: "lemonsqueezy_checkout_create_failed", status: 502 };
  }
  const checkoutUrl = extractCheckoutUrl(payload);
  if (!checkoutUrl) {
    return { error: "lemonsqueezy_checkout_url_missing", status: 502 };
  }
  return { checkoutUrl, checkoutId: extractCheckoutId(payload) };
}

async function createProLemonCheckout({ env, deps, user, config }) {
  requireLemonIds(config);
  return await createLemonCheckout({
    env,
    deps,
    user,
    config,
    variantId: config.proVariantId,
    checkoutData: {
      custom: {
      user_id: String(user.id || "").trim(),
      product: "planetka_pro",
      },
    },
  });
}

async function validateLemonLicenseKey(licenseKey) {
  const body = new URLSearchParams();
  body.set("license_key", String(licenseKey || "").trim());
  const response = await fetch(`${LEMON_LICENSE_API_BASE}/validate`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (!response.ok) {
    return { error: "lemonsqueezy_license_validate_failed", status: 400, payload };
  }
  if (!payload || payload.valid !== true) {
    return { error: "invalid_lemonsqueezy_license", status: 400, payload };
  }
  return { payload };
}

async function ensureLemonWebhookEventsTable(db, deps) {
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS ${LEMON_WEBHOOK_EVENTS_TABLE} (
        id TEXT PRIMARY KEY,
        event_name TEXT NOT NULL,
        order_id TEXT,
        user_id TEXT,
        variant_id TEXT,
        processing_status TEXT NOT NULL DEFAULT 'processing',
        error TEXT,
        received_at TEXT NOT NULL,
        processed_at TEXT
      )
    `,
  );
}

function webhookEventId(payload, request) {
  const meta = payload && payload.meta || {};
  const data = payload && payload.data || {};
  const eventName = String(meta.event_name || request.headers.get("X-Event-Name") || "").trim();
  const dataType = String(data.type || "").trim();
  const dataId = String(data.id || "").trim();
  if (eventName && dataType && dataId) {
    return `${eventName}:${dataType}:${dataId}`;
  }
  return crypto.randomUUID();
}

async function claimLemonWebhookEvent(db, eventId, eventName, orderId, userId, variantId, deps) {
  await ensureLemonWebhookEventsTable(db, deps);
  const now = deps.nowIso();
  try {
    await deps.dbRun(
      db,
      `
        INSERT INTO ${LEMON_WEBHOOK_EVENTS_TABLE} (
          id, event_name, order_id, user_id, variant_id, processing_status, received_at
        ) VALUES (?, ?, ?, ?, ?, 'processing', ?)
      `,
      [eventId, eventName, orderId, userId, variantId, now],
    );
    return { claimed: true };
  } catch (_error) {
    const existing = await deps.dbGet(
      db,
      `SELECT processing_status FROM ${LEMON_WEBHOOK_EVENTS_TABLE} WHERE id = ? LIMIT 1`,
      [eventId],
    );
    if (String(existing && existing.processing_status || "") === "processed") {
      return { claimed: false, processed: true };
    }
    return { claimed: false, processed: false };
  }
}

async function markLemonWebhookEventProcessed(db, eventId, deps) {
  await deps.dbRun(
    db,
    `UPDATE ${LEMON_WEBHOOK_EVENTS_TABLE} SET processing_status = 'processed', processed_at = ?, error = '' WHERE id = ?`,
    [deps.nowIso(), eventId],
  );
}

async function markLemonWebhookEventFailed(db, eventId, error, deps) {
  await deps.dbRun(
    db,
    `UPDATE ${LEMON_WEBHOOK_EVENTS_TABLE} SET processing_status = 'failed', error = ? WHERE id = ?`,
    [String(error || "webhook_failed").slice(0, 1000), eventId],
  );
}

function centsForScenePrice(env, rawValue) {
  const fallback = Number(env.PLANETKA_SCENE_FULL_QUALITY_PRICE_EUR || DEFAULT_SCENE_PRICE_EUR);
  const parsed = Number.parseFloat(String(rawValue ?? fallback));
  const eur = Number.isFinite(parsed) ? Math.max(0, Math.min(10000, parsed)) : DEFAULT_SCENE_PRICE_EUR;
  return Math.round(eur * 100);
}

async function scenePriceCents(db, env, deps) {
  try {
    const row = await deps.dbGet(
      db,
      `SELECT value FROM app_settings WHERE key = ? LIMIT 1`,
      ["custom_scene_licence_fee_eur"],
    );
    return centsForScenePrice(env, row && row.value);
  } catch (_error) {
    return centsForScenePrice(env, env.PLANETKA_SCENE_FULL_QUALITY_PRICE_EUR);
  }
}

function normalizeSceneId(value) {
  return String(value || "").trim().toLowerCase().replace(/[^a-z0-9_.:-]/g, "").slice(0, 160);
}

function normalizeTileList(value) {
  const source = Array.isArray(value) ? value : [];
  const seen = new Set();
  const result = [];
  for (const item of source) {
    const tile = String(item || "").trim();
    if (!tile || tile.length > 120 || seen.has(tile)) {
      continue;
    }
    seen.add(tile);
    result.push(tile);
  }
  result.sort();
  return result.slice(0, 64);
}

function safeJsonString(value, maxLength = 20000) {
  try {
    return JSON.stringify(value ?? null).slice(0, maxLength);
  } catch (_error) {
    return "null";
  }
}

async function ensureScenePurchaseTables(db, deps) {
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS ${SCENE_PURCHASE_PENDING_TABLE} (
        id TEXT PRIMARY KEY,
        scene_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        variant_id TEXT,
        amount_cents INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'EUR',
        camera_json TEXT,
        tiles_json TEXT,
        tile_hash TEXT,
        checkout_id TEXT,
        checkout_url TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT
      )
    `,
  );
  await deps.dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_scene_pending_user_scene ON ${SCENE_PURCHASE_PENDING_TABLE}(user_id, scene_id)`,
  );
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS ${SCENE_PURCHASES_TABLE} (
        id TEXT PRIMARY KEY,
        scene_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT,
        purchase_type TEXT NOT NULL DEFAULT 'scene_full_quality_commercial_license',
        order_id TEXT,
        variant_id TEXT,
        amount_cents INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'EUR',
        camera_json TEXT,
        tiles_json TEXT,
        tile_hash TEXT,
        status TEXT NOT NULL DEFAULT 'paid',
        created_at TEXT NOT NULL,
        purchased_at TEXT NOT NULL
      )
    `,
  );
  await deps.dbRun(
    db,
    `CREATE UNIQUE INDEX IF NOT EXISTS idx_scene_purchase_user_scene_paid ON ${SCENE_PURCHASES_TABLE}(user_id, scene_id)`,
  );
  await deps.dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_scene_purchase_email ON ${SCENE_PURCHASES_TABLE}(lower(user_email), purchased_at DESC)`,
  );
}

async function loadScenePurchase(db, userId, sceneId, deps) {
  await ensureScenePurchaseTables(db, deps);
  return await deps.dbGet(
    db,
    `
      SELECT *
      FROM ${SCENE_PURCHASES_TABLE}
      WHERE user_id = ? AND scene_id = ? AND status = 'paid'
      LIMIT 1
    `,
    [String(userId || ""), normalizeSceneId(sceneId)],
  );
}

async function listScenePurchases(db, userId, deps, limit = 50) {
  await ensureScenePurchaseTables(db, deps);
  const rows = typeof deps.dbAll === "function"
    ? await deps.dbAll(
      db,
      `
        SELECT id, scene_id, user_id, user_email, purchase_type, amount_cents, currency,
               camera_json, tiles_json, tile_hash, purchased_at
        FROM ${SCENE_PURCHASES_TABLE}
        WHERE user_id = ? AND status = 'paid'
        ORDER BY purchased_at DESC
        LIMIT ?
      `,
      [String(userId || ""), Math.max(1, Math.min(200, Number.parseInt(limit, 10) || 50))],
    )
    : [];
  return (Array.isArray(rows) ? rows : []).map((row) => ({
    id: String(row && row.id || ""),
    scene_id: String(row && row.scene_id || ""),
    purchase_type: String(row && row.purchase_type || "scene_full_quality_commercial_license"),
    amount_cents: Number.parseInt(row && row.amount_cents || 0, 10) || 0,
    currency: String(row && row.currency || "EUR"),
    camera: (() => {
      try { return JSON.parse(String(row && row.camera_json || "{}")); } catch (_error) { return {}; }
    })(),
    tiles: (() => {
      try { return JSON.parse(String(row && row.tiles_json || "[]")); } catch (_error) { return []; }
    })(),
    tile_hash: String(row && row.tile_hash || ""),
    purchased_at: String(row && row.purchased_at || ""),
  }));
}

function extractWebhookDetails(payload, request) {
  const meta = payload && payload.meta || {};
  const data = payload && payload.data || {};
  const attrs = data.attributes || {};
  const custom = meta.custom_data || {};
  const firstOrderItem = Array.isArray(attrs.first_order_item) ? attrs.first_order_item[0] : null;
  const variantId = String(
    attrs.variant_id
      || attrs.first_order_item && attrs.first_order_item.variant_id
      || firstOrderItem && firstOrderItem.variant_id
      || custom.variant_id
      || "",
  ).trim();
  return {
    eventName: String(meta.event_name || request.headers.get("X-Event-Name") || "").trim(),
    orderId: String(data.id || attrs.identifier || "").trim(),
    userId: String(custom.user_id || custom.userId || "").trim(),
    email: String(custom.email || attrs.user_email || attrs.customer_email || "").trim().toLowerCase(),
    product: String(custom.product || "").trim(),
    purchaseId: String(custom.purchase_id || custom.purchaseId || "").trim(),
    sceneId: normalizeSceneId(custom.scene_id || custom.sceneId || ""),
    variantId,
    amountCents: Number.parseInt(attrs.total || attrs.subtotal || attrs.total_usd || 0, 10) || 0,
    currency: String(attrs.currency || "EUR").trim().toUpperCase() || "EUR",
    testMode: Boolean(meta.test_mode || attrs.test_mode),
  };
}

async function upgradeUserToPro(db, { userId, email }, deps) {
  const normalizedEmail = deps.normalizeEmail(email || "");
  let user = null;
  if (userId) {
    user = await deps.dbGet(db, `SELECT id, email, status FROM users WHERE id = ? LIMIT 1`, [userId]);
  }
  if (!user && normalizedEmail) {
    user = await deps.dbGet(db, `SELECT id, email, status FROM users WHERE lower(email) = ? LIMIT 1`, [normalizedEmail]);
  }
  if (!user) {
    return { error: "user_not_found", status: 404 };
  }
  if (deps.isBlockedStatus(user.status)) {
    return { error: "user_blocked", status: 409 };
  }
  const targetUserId = String(user.id || "").trim();
  const previousPlan = normalizeRequestedPlan(user.status);
  const now = deps.nowIso();
  let finalEmail = deps.normalizeEmail(user.email || normalizedEmail);
  if (normalizedEmail && normalizedEmail.includes("@")) {
    const existingEmailUser = await deps.dbGet(
      db,
      `SELECT id FROM users WHERE lower(email) = ? AND id != ? LIMIT 1`,
      [normalizedEmail, targetUserId],
    );
    if (!existingEmailUser) {
      finalEmail = normalizedEmail;
      await deps.dbRun(db, `UPDATE users SET status = ?, email = ? WHERE id = ?`, [PLAN_CODE_PROFESSIONAL, normalizedEmail, targetUserId]);
    } else {
      await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [PLAN_CODE_PROFESSIONAL, targetUserId]);
    }
  } else {
    await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [PLAN_CODE_PROFESSIONAL, targetUserId]);
  }
  const apiKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET plan_code = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [PLAN_CODE_PROFESSIONAL, targetUserId],
  );
  const revokedSessionsResult = await deps.dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [now, targetUserId],
  );
  return {
    userId: targetUserId,
    email: finalEmail,
    previousPlan,
    planCode: PLAN_CODE_PROFESSIONAL,
    updatedActiveApiKeys: deps.dbMetaChanges(apiKeysResult),
    revokedSessions: deps.dbMetaChanges(revokedSessionsResult),
    updatedAt: now,
  };
}

export function createLemonSqueezyBillingHandlers(deps) {
  async function handleCreateCheckout(request, env) {
    const auth = await deps.requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: true },
    );
    if (auth.error) {
      return auth.error;
    }
    const { db, user } = auth;
    const accountState = await deps.buildAccountState(db, user, env);
    const planCode = normalizeRequestedPlan(accountState.planCode || user.status);
    if (planCode === PLAN_CODE_PROFESSIONAL) {
      return deps.json({ ok: true, already_pro: true, plan_code: PLAN_CODE_PROFESSIONAL }, 200, env);
    }
    let config;
    try {
      config = lemonEnv(env, deps);
      requireLemonIds(config);
    } catch (error) {
      console.error("lemonsqueezy.checkout_config_error", String(error && error.message || error));
      return deps.json({ ok: false, error: "lemonsqueezy_not_configured" }, 503, env);
    }
    const checkout = await createProLemonCheckout({ env, deps, user, config });
    if (checkout.error) {
      return deps.json({ ok: false, error: checkout.error }, checkout.status || 502, env);
    }
    return deps.json(
      {
        ok: true,
        checkout_url: checkout.checkoutUrl,
        price_label: config.priceLabel,
        test_mode: Boolean(config.testMode),
      },
      200,
      env,
    );
  }

  async function handleCreateSceneCheckout(request, env) {
    const auth = await deps.requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: true },
    );
    if (auth.error) {
      return auth.error;
    }
    const { db, user } = auth;
    const body = await deps.parseJson(request);
    const sceneId = normalizeSceneId(body.scene_id || body.sceneId || "");
    const tiles = normalizeTileList(body.tiles || body.full_quality_tiles || body.fullQualityTiles || []);
    if (!sceneId || !tiles.length) {
      return deps.json({ ok: false, error: "missing_scene_purchase_details" }, 400, env);
    }
    await ensureScenePurchaseTables(db, deps);
    const existing = await loadScenePurchase(db, user.id, sceneId, deps);
    if (existing) {
      return deps.json({ ok: true, already_purchased: true, scene_id: sceneId, purchase_id: String(existing.id || "") }, 200, env);
    }
    let config;
    try {
      config = lemonEnv(env, deps);
      requireLemonSceneIds(config);
    } catch (error) {
      console.error("lemonsqueezy.scene_checkout_config_error", String(error && error.message || error));
      return deps.json({ ok: false, error: "scene_checkout_not_configured" }, 503, env);
    }
    const amountCents = await scenePriceCents(db, env, deps);
    const purchaseId = crypto.randomUUID();
    const now = deps.nowIso();
    const userEmail = typeof deps.isSyntheticAnonymousEmail === "function" && deps.isSyntheticAnonymousEmail(user.email)
      ? ""
      : deps.normalizeEmail(user.email || "");
    const cameraPayload = body.camera && typeof body.camera === "object" ? body.camera : {};
    const tileHash = String(body.tile_hash || body.tileHash || "").trim().slice(0, 128);
    await deps.dbRun(
      db,
      `
        INSERT INTO ${SCENE_PURCHASE_PENDING_TABLE} (
          id, scene_id, user_id, user_email, status, variant_id, amount_cents, currency,
          camera_json, tiles_json, tile_hash, created_at
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?, 'EUR', ?, ?, ?, ?)
      `,
      [
        purchaseId,
        sceneId,
        String(user.id || ""),
        userEmail,
        String(config.sceneVariantId),
        amountCents,
        safeJsonString(cameraPayload),
        safeJsonString(tiles),
        tileHash,
        now,
      ],
    );
    const checkout = await createLemonCheckout({
      env,
      deps,
      user,
      config,
      variantId: config.sceneVariantId,
      customPriceCents: amountCents,
      successPath: "/billing/lemonsqueezy/scene-success",
      checkoutData: {
        custom: {
          user_id: String(user.id || ""),
          product: "scene_full_quality_commercial_license",
          purchase_id: purchaseId,
          scene_id: sceneId,
        },
      },
    });
    if (checkout.error) {
      return deps.json({ ok: false, error: checkout.error }, checkout.status || 502, env);
    }
    await deps.dbRun(
      db,
      `UPDATE ${SCENE_PURCHASE_PENDING_TABLE} SET checkout_id = ?, checkout_url = ? WHERE id = ?`,
      [String(checkout.checkoutId || ""), String(checkout.checkoutUrl || ""), purchaseId],
    );
    return deps.json(
      {
        ok: true,
        checkout_url: checkout.checkoutUrl,
        purchase_id: purchaseId,
        scene_id: sceneId,
        amount_cents: amountCents,
        currency: "EUR",
        test_mode: Boolean(config.testMode),
      },
      200,
      env,
    );
  }

  async function handleListScenePurchases(request, env) {
    const auth = await deps.requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: true },
    );
    if (auth.error) {
      return auth.error;
    }
    const url = new URL(request.url);
    const limit = Number.parseInt(url.searchParams.get("limit") || "50", 10) || 50;
    const purchases = await listScenePurchases(auth.db, auth.user.id, deps, limit);
    return deps.json({ ok: true, purchases }, 200, env);
  }

  async function handleCheckScenePurchase(request, env) {
    const auth = await deps.requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: true },
    );
    if (auth.error) {
      return auth.error;
    }
    const url = new URL(request.url);
    let sceneId = normalizeSceneId(url.searchParams.get("scene_id") || "");
    if (!sceneId && request.method === "POST") {
      const body = await deps.parseJson(request);
      sceneId = normalizeSceneId(body.scene_id || body.sceneId || "");
    }
    if (!sceneId) {
      return deps.json({ ok: false, error: "missing_scene_id" }, 400, env);
    }
    const purchase = await loadScenePurchase(auth.db, auth.user.id, sceneId, deps);
    return deps.json(
      {
        ok: true,
        purchased: Boolean(purchase),
        scene_id: sceneId,
        purchase_id: purchase ? String(purchase.id || "") : "",
      },
      200,
      env,
    );
  }

  async function handleWebhook(request, env) {
    const rawBody = await request.text();
    try {
      await verifyLemonSignature(request, rawBody, env, deps);
    } catch (error) {
      return deps.json({ ok: false, error: String(error && error.message || "invalid_signature") }, 401, env);
    }

    let payload;
    try {
      payload = JSON.parse(rawBody || "{}");
    } catch (_error) {
      return deps.json({ ok: false, error: "invalid_json" }, 400, env);
    }

    const db = deps.requireDb(env);
    await deps.ensureApiKeyTables(db);
    await deps.ensureRefreshSessionColumns(db);
    const config = lemonEnv(env, deps);
    const details = extractWebhookDetails(payload, request);
    const eventId = webhookEventId(payload, request);
    const claimed = await claimLemonWebhookEvent(
      db,
      eventId,
      details.eventName,
      details.orderId,
      details.userId,
      details.variantId,
      deps,
    );
    if (!claimed.claimed) {
      return deps.json({ ok: true, duplicate: true, processed: Boolean(claimed.processed) }, 200, env);
    }

    try {
      if (details.eventName !== "order_created") {
        await markLemonWebhookEventProcessed(db, eventId, deps);
        return deps.json({ ok: true, ignored: true, event_name: details.eventName }, 200, env);
      }
      if (String(details.variantId) === String(config.sceneVariantId)) {
        await ensureScenePurchaseTables(db, deps);
        const pending = details.purchaseId
          ? await deps.dbGet(
            db,
            `SELECT * FROM ${SCENE_PURCHASE_PENDING_TABLE} WHERE id = ? LIMIT 1`,
            [details.purchaseId],
          )
          : null;
        const sceneId = normalizeSceneId((pending && pending.scene_id) || details.sceneId || "");
        const targetUserId = String((pending && pending.user_id) || details.userId || "").trim();
        if (!sceneId || !targetUserId) {
          await markLemonWebhookEventFailed(db, eventId, "missing_scene_purchase_context", deps);
          return deps.json({ ok: false, error: "missing_scene_purchase_context" }, 400, env);
        }
        const email = deps.normalizeEmail(details.email || pending && pending.user_email || "");
        const purchaseId = String((pending && pending.id) || details.purchaseId || crypto.randomUUID());
        const now = deps.nowIso();
        await deps.dbRun(
          db,
          `
            INSERT INTO ${SCENE_PURCHASES_TABLE} (
              id, scene_id, user_id, user_email, purchase_type, order_id, variant_id,
              amount_cents, currency, camera_json, tiles_json, tile_hash, status, created_at, purchased_at
            ) VALUES (?, ?, ?, ?, 'scene_full_quality_commercial_license', ?, ?, ?, ?, ?, ?, ?, 'paid', ?, ?)
            ON CONFLICT(user_id, scene_id) DO UPDATE SET
              user_email = excluded.user_email,
              order_id = excluded.order_id,
              variant_id = excluded.variant_id,
              amount_cents = excluded.amount_cents,
              currency = excluded.currency,
              camera_json = excluded.camera_json,
              tiles_json = excluded.tiles_json,
              tile_hash = excluded.tile_hash,
              status = 'paid',
              purchased_at = excluded.purchased_at
          `,
          [
            purchaseId,
            sceneId,
            targetUserId,
            email,
            details.orderId,
            String(details.variantId || config.sceneVariantId),
            Number.parseInt((pending && pending.amount_cents) || details.amountCents || 0, 10) || 0,
            String(details.currency || "EUR"),
            String(pending && pending.camera_json || "{}"),
            String(pending && pending.tiles_json || "[]"),
            String(pending && pending.tile_hash || ""),
            String(pending && pending.created_at || now),
            now,
          ],
        );
        if (email) {
          const existingEmailUser = await deps.dbGet(
            db,
            `SELECT id FROM users WHERE lower(email) = ? AND id != ? LIMIT 1`,
            [email, targetUserId],
          );
          if (!existingEmailUser) {
            await deps.dbRun(db, `UPDATE users SET email = ? WHERE id = ?`, [email, targetUserId]);
          }
        }
        await deps.dbRun(
          db,
          `UPDATE ${SCENE_PURCHASE_PENDING_TABLE} SET status = 'paid', completed_at = ? WHERE id = ?`,
          [now, purchaseId],
        );
        await markLemonWebhookEventProcessed(db, eventId, deps);
        return deps.json({ ok: true, processed: true, purchase_type: "scene", scene_id: sceneId }, 200, env);
      }
      if (String(details.variantId) !== String(config.proVariantId)) {
        await markLemonWebhookEventProcessed(db, eventId, deps);
        return deps.json({ ok: true, ignored: true, reason: "variant_mismatch" }, 200, env);
      }
      const upgraded = await upgradeUserToPro(db, { userId: details.userId, email: details.email }, deps);
      if (upgraded.error) {
        await markLemonWebhookEventFailed(db, eventId, upgraded.error, deps);
        return deps.json({ ok: false, error: upgraded.error }, upgraded.status || 500, env);
      }
      await markLemonWebhookEventProcessed(db, eventId, deps);
      console.log(
        "lemonsqueezy.pro_upgrade_processed",
        JSON.stringify({
          event_id: eventId,
          order_id: details.orderId,
          user_id: upgraded.userId,
          user_email: upgraded.email,
          previous_plan: upgraded.previousPlan,
          plan_code: upgraded.planCode,
          updated_active_api_keys: upgraded.updatedActiveApiKeys,
          revoked_sessions: upgraded.revokedSessions,
        }),
      );
      return deps.json({ ok: true, processed: true, user_id: upgraded.userId, plan_code: upgraded.planCode }, 200, env);
    } catch (error) {
      const message = String(error && error.message || "lemonsqueezy_webhook_failed");
      await markLemonWebhookEventFailed(db, eventId, message, deps);
      console.error("lemonsqueezy.webhook_failed", JSON.stringify({ event_id: eventId, error: message }));
      return deps.json({ ok: false, error: "lemonsqueezy_webhook_failed" }, 500, env);
    }
  }

  async function handleRestoreLicense(request, env) {
    const auth = await deps.requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: true },
    );
    if (auth.error) {
      return auth.error;
    }
    const { db, user } = auth;
    const body = await deps.parseJson(request);
    const licenseKey = String(body.license_key || body.licenseKey || "").trim();
    if (!licenseKey) {
      return deps.json({ ok: false, error: "missing_license_key" }, 400, env);
    }
    let config;
    try {
      config = lemonEnv(env, deps);
      requireLemonIds(config);
    } catch (error) {
      console.error("lemonsqueezy.restore_config_error", String(error && error.message || error));
      return deps.json({ ok: false, error: "lemonsqueezy_not_configured" }, 503, env);
    }
    const validation = await validateLemonLicenseKey(licenseKey);
    if (validation.error) {
      return deps.json({ ok: false, error: validation.error }, validation.status || 400, env);
    }
    const meta = validation.payload && validation.payload.meta || {};
    const variantId = String(meta.variant_id || "").trim();
    if (variantId !== String(config.proVariantId)) {
      return deps.json({ ok: false, error: "license_variant_mismatch" }, 403, env);
    }
    const customerEmail = deps.normalizeEmail(meta.customer_email || "");
    const upgraded = await upgradeUserToPro(db, { userId: String(user.id || ""), email: customerEmail }, deps);
    if (upgraded.error) {
      return deps.json({ ok: false, error: upgraded.error }, upgraded.status || 500, env);
    }
    return deps.json(
      {
        ok: true,
        restored: true,
        user_id: upgraded.userId,
        planetka_user_id: upgraded.userId,
        email: upgraded.email,
        plan_code: upgraded.planCode,
      },
      200,
      env,
    );
  }

  async function handleSuccess(_request, env) {
    const htmlBody = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Planetka Pro Upgrade</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f3ed; color: #172033; margin: 0; padding: 40px 20px; }
    main { max-width: 680px; margin: 0 auto; background: #fffaf1; border: 1px solid #d9c9a6; border-radius: 18px; padding: 32px; box-shadow: 0 20px 60px rgba(40, 29, 10, 0.12); }
    h1 { margin: 0 0 14px; font-size: 30px; }
    p { font-size: 17px; line-height: 1.5; }
  </style>
</head>
<body>
  <main>
    <h1>Thank you for upgrading to Planetka Pro.</h1>
    <p>Return to Blender. Planetka will refresh your account and unlock Pro features automatically once the checkout is confirmed.</p>
  </main>
</body>
</html>`;
    return deps.html(htmlBody, 200, env, { "Cache-Control": "no-store" });
  }

  async function handleSceneSuccess(_request, env) {
    const htmlBody = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Planetka Scene Licence</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f3ed; color: #172033; margin: 0; padding: 40px 20px; }
    main { max-width: 680px; margin: 0 auto; background: #fffaf1; border: 1px solid #d9c9a6; border-radius: 18px; padding: 32px; box-shadow: 0 20px 60px rgba(40, 29, 10, 0.12); }
    h1 { margin: 0 0 14px; font-size: 30px; }
    p { font-size: 17px; line-height: 1.5; }
  </style>
</head>
<body>
  <main>
    <h1>Thank you for purchasing a Planetka scene licence.</h1>
    <p>Return to Blender. Planetka will unlock Full Quality and the commercial licence for this scene once the checkout is confirmed.</p>
  </main>
</body>
</html>`;
    return deps.html(htmlBody, 200, env, { "Cache-Control": "no-store" });
  }

  return {
    handleCreateCheckout,
    handleCreateSceneCheckout,
    handleListScenePurchases,
    handleCheckScenePurchase,
    handleWebhook,
    handleRestoreLicense,
    handleSuccess,
    handleSceneSuccess,
  };
}
