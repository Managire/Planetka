import {
  PLAN_CODE_COMMERCIAL,
  normalizeRequestedPlan,
} from "./entitlements.js";

const LEMON_API_BASE = "https://api.lemonsqueezy.com/v1";
const LEMON_LICENSE_API_BASE = "https://api.lemonsqueezy.com/v1/licenses";
const LEMON_WEBHOOK_EVENTS_TABLE = "lemon_webhook_events";
const DEFAULT_COMMERCIAL_PRICE_LABEL = "";
const DEFAULT_COMMERCIAL_PRICE_CENTS = 25000;

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
    commercialVariantId: String(env.LEMONSQUEEZY_COMMERCIAL_VARIANT_ID || "").trim(),
    testMode: boolFromEnv(env.LEMONSQUEEZY_TEST_MODE, false),
    priceLabel: String(env.LEMONSQUEEZY_COMMERCIAL_PRICE_LABEL || DEFAULT_COMMERCIAL_PRICE_LABEL).trim() || DEFAULT_COMMERCIAL_PRICE_LABEL,
  };
}

function requireLemonIds(config) {
  if (!config.storeId) {
    throw new Error("missing_lemonsqueezy_store_id");
  }
  if (!config.commercialVariantId) {
    throw new Error("missing_lemonsqueezy_commercial_variant_id");
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
  const envRedirectKey = "LEMONSQUEEZY_SUCCESS_URL";
  const redirectUrl = String(env[envRedirectKey] || `${apiBaseUrl}${successPath}`).trim();
  const userEmail = typeof deps.isSyntheticAnonymousEmail === "function" && deps.isSyntheticAnonymousEmail(user.email)
    ? ""
    : String(user.email || "").trim().toLowerCase();
  const finalCheckoutData = checkoutData && typeof checkoutData === "object"
    ? { ...checkoutData, custom: { ...(checkoutData.custom || {}) } }
    : {
      custom: {
        user_id: String(user.id || "").trim(),
        product: "planetka_commercial",
      },
    };
  if (!finalCheckoutData.custom.user_id) {
    finalCheckoutData.custom.user_id = String(user.id || "").trim();
  }
  if (!finalCheckoutData.custom.product) {
    finalCheckoutData.custom.product = "planetka_commercial";
  }
  if (userEmail && !finalCheckoutData.email) {
    finalCheckoutData.email = userEmail;
    if (!finalCheckoutData.custom.email) {
      finalCheckoutData.custom.email = userEmail;
    }
  }
  const selectedVariantId = String(variantId || config.commercialVariantId || "").trim();
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
      discount: false,
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

async function createCommercialLemonCheckout({ env, deps, user, config }) {
  requireLemonIds(config);
  return await createLemonCheckout({
    env,
    deps,
    user,
    config,
    variantId: config.commercialVariantId,
    checkoutData: {
      custom: {
        user_id: String(user.id || "").trim(),
        product: "planetka_commercial",
      },
    },
    customPriceCents: DEFAULT_COMMERCIAL_PRICE_CENTS,
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
    variantId,
    amountCents: Number.parseInt(attrs.total || attrs.subtotal || attrs.total_usd || 0, 10) || 0,
    currency: String(attrs.currency || "EUR").trim().toUpperCase() || "EUR",
    testMode: Boolean(meta.test_mode || attrs.test_mode),
  };
}

async function upgradeUserToCommercial(db, { userId, email }, deps) {
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
      await deps.dbRun(db, `UPDATE users SET status = ?, email = ? WHERE id = ?`, [PLAN_CODE_COMMERCIAL, normalizedEmail, targetUserId]);
    } else {
      await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [PLAN_CODE_COMMERCIAL, targetUserId]);
    }
  } else {
    await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [PLAN_CODE_COMMERCIAL, targetUserId]);
  }
  const apiKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET plan_code = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [PLAN_CODE_COMMERCIAL, targetUserId],
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
    planCode: PLAN_CODE_COMMERCIAL,
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
    if (planCode === PLAN_CODE_COMMERCIAL) {
      return deps.json({ ok: true, already_commercial: true, plan_code: PLAN_CODE_COMMERCIAL }, 200, env);
    }
    let config;
    try {
      config = lemonEnv(env, deps);
      requireLemonIds(config);
    } catch (error) {
      console.error("lemonsqueezy.checkout_config_error", String(error && error.message || error));
      return deps.json({ ok: false, error: "lemonsqueezy_not_configured" }, 503, env);
    }
    const checkout = await createCommercialLemonCheckout({ env, deps, user, config });
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
      if (String(details.variantId) !== String(config.commercialVariantId)) {
        await markLemonWebhookEventProcessed(db, eventId, deps);
        return deps.json({ ok: true, ignored: true, reason: "variant_mismatch" }, 200, env);
      }
      const upgraded = await upgradeUserToCommercial(db, { userId: details.userId, email: details.email }, deps);
      if (upgraded.error) {
        await markLemonWebhookEventFailed(db, eventId, upgraded.error, deps);
        return deps.json({ ok: false, error: upgraded.error }, upgraded.status || 500, env);
      }
      await markLemonWebhookEventProcessed(db, eventId, deps);
      console.log(
        "lemonsqueezy.commercial_purchase_processed",
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
    if (variantId !== String(config.commercialVariantId)) {
      return deps.json({ ok: false, error: "license_variant_mismatch" }, 403, env);
    }
    const customerEmail = deps.normalizeEmail(meta.customer_email || "");
    const upgraded = await upgradeUserToCommercial(db, { userId: String(user.id || ""), email: customerEmail }, deps);
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
  <title>Planetka Commercial Licence</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f3ed; color: #172033; margin: 0; padding: 40px 20px; }
    main { max-width: 680px; margin: 0 auto; background: #fffaf1; border: 1px solid #d9c9a6; border-radius: 18px; padding: 32px; box-shadow: 0 20px 60px rgba(40, 29, 10, 0.12); }
    h1 { margin: 0 0 14px; font-size: 30px; }
    p { font-size: 17px; line-height: 1.5; }
  </style>
</head>
<body>
  <main>
    <h1>Thank you for buying a Planetka Commercial Licence.</h1>
    <p>Return to Blender. Planetka will refresh your account and unlock Commercial licence status automatically once the checkout is confirmed.</p>
  </main>
</body>
</html>`;
    return deps.html(htmlBody, 200, env, { "Cache-Control": "no-store" });
  }

  return {
    handleCreateCheckout,
    handleWebhook,
    handleRestoreLicense,
    handleSuccess,
  };
}
