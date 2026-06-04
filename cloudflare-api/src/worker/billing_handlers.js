const DEFAULT_FULL_RESOLVE_PRICE_CENTS = 1000;
const DEFAULT_ANIMATION_PRICE_PER_300_CENTS = 2900;
const DEFAULT_CURRENCY = "EUR";
const BILLING_INTENT_TTL_HOURS = 24;

function nowIso() {
  return new Date().toISOString();
}

function addHoursIso(hours) {
  return new Date(Date.now() + Math.max(1, Number(hours || 1)) * 3600 * 1000).toISOString();
}

function parseCents(value, fallback) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  if (!Number.isFinite(parsed) || parsed < 0) return Math.max(0, Number.parseInt(String(fallback || 0), 10) || 0);
  return parsed;
}

function normalizeCurrency(value) {
  const text = String(value || DEFAULT_CURRENCY).trim().toUpperCase();
  return /^[A-Z]{3}$/.test(text) ? text : DEFAULT_CURRENCY;
}

function normalizeBillingKind(value) {
  const text = String(value || "").trim().toLowerCase();
  if (text === "animation" || text === "final_animation" || text === "final_animation_render") return "animation";
  if (text === "full" || text === "full_resolve" || text === "full_resolution") return "full_resolve";
  return "";
}

function safeFrameCount(value) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  return Math.max(1, Number.isFinite(parsed) ? parsed : 1);
}

function animationUnitsForFrames(frameCount) {
  return Math.max(1, Math.ceil(safeFrameCount(frameCount) / 300));
}

function isProInstall(auth) {
  return String(auth && auth.installEdition || "").trim().toLowerCase() === "pro";
}

async function dbRun(db, sql, bindings = []) {
  return db.prepare(sql).bind(...bindings).run();
}

async function dbGet(db, sql, bindings = []) {
  return await db.prepare(sql).bind(...bindings).first();
}

async function ensureBillingTables(db) {
  await dbRun(db, `CREATE TABLE IF NOT EXISTS billing_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)`);
  await dbRun(db, `CREATE TABLE IF NOT EXISTS billing_intents (
    id TEXT PRIMARY KEY,
    install_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    amount_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'EUR',
    frame_count INTEGER NOT NULL DEFAULT 0,
    frame_units INTEGER NOT NULL DEFAULT 0,
    checkout_id TEXT,
    checkout_url TEXT,
    provider_order_id TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    paid_at TEXT,
    consumed_at TEXT,
    metadata_json TEXT
  )`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_billing_intents_install_kind_status ON billing_intents(install_id, kind, status, created_at DESC)`);
  await dbRun(db, `CREATE INDEX IF NOT EXISTS idx_billing_intents_checkout_id ON billing_intents(checkout_id)`);
}

async function getBillingSettings(db) {
  await ensureBillingTables(db);
  const result = await db.prepare(`SELECT key, value FROM billing_settings`).all();
  const rows = Array.isArray(result && result.results) ? result.results : [];
  const values = new Map(rows.map((row) => [String(row.key || ""), String(row.value || "")]));
  return {
    full_resolve_price_cents: parseCents(values.get("full_resolve_price_cents"), DEFAULT_FULL_RESOLVE_PRICE_CENTS),
    animation_price_per_300_cents: parseCents(values.get("animation_price_per_300_cents"), DEFAULT_ANIMATION_PRICE_PER_300_CENTS),
    currency: normalizeCurrency(values.get("currency") || DEFAULT_CURRENCY),
  };
}

async function setBillingSettings(db, settings = {}) {
  await ensureBillingTables(db);
  const current = await getBillingSettings(db);
  const next = {
    full_resolve_price_cents: parseCents(settings.full_resolve_price_cents, current.full_resolve_price_cents),
    animation_price_per_300_cents: parseCents(settings.animation_price_per_300_cents, current.animation_price_per_300_cents),
    currency: normalizeCurrency(settings.currency || current.currency),
  };
  const updatedAt = nowIso();
  for (const [key, value] of Object.entries(next)) {
    await dbRun(db, `INSERT INTO billing_settings (key, value, updated_at) VALUES (?, ?, ?)
      ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`, [key, String(value), updatedAt]);
  }
  return next;
}

function publicPrices(settings, auth) {
  const edition = isProInstall(auth) ? "pro" : "free";
  return {
    ok: true,
    install_edition: edition,
    full_resolve_requires_payment: edition !== "pro",
    animation_requires_payment: edition !== "pro",
    currency: settings.currency,
    full_resolve_price_cents: settings.full_resolve_price_cents,
    animation_price_per_300_cents: settings.animation_price_per_300_cents,
  };
}

function requireLemonConfig(env, kind) {
  const apiKey = String(env.LEMONSQUEEZY_API_KEY || "").trim();
  const storeId = String(env.LEMONSQUEEZY_STORE_ID || "").trim();
  const fullVariant = String(env.LEMONSQUEEZY_FULL_RESOLVE_VARIANT_ID || env.LEMONSQUEEZY_PRO_VARIANT_ID || "").trim();
  const animationVariant = String(env.LEMONSQUEEZY_ANIMATION_VARIANT_ID || fullVariant || "").trim();
  const variantId = kind === "animation" ? animationVariant : fullVariant;
  if (!apiKey || !storeId || !variantId) {
    throw new Error("billing_checkout_not_configured");
  }
  return { apiKey, storeId, variantId };
}

function checkoutProductName(kind, units = 1) {
  if (kind === "animation") {
    return units > 1 ? `Planetka Animation Render (${units} blocks)` : "Planetka Animation Render";
  }
  return "Planetka Full Resolution Resolve";
}

async function createLemonCheckout(env, intent, settings) {
  const { apiKey, storeId, variantId } = requireLemonConfig(env, intent.kind);
  const apiBase = String(env.LEMONSQUEEZY_API_BASE_URL || "https://api.lemonsqueezy.com/v1").replace(/\/+$/, "");
  const redirectUrl = String(env.PLANETKA_CHECKOUT_REDIRECT_URL || "https://planetka.io/checkout-complete").trim();
  const body = {
    data: {
      type: "checkouts",
      attributes: {
        custom_price: Number(intent.amount_cents || 0),
        checkout_options: { embed: false, media: false, logo: true, discount: false },
        product_options: {
          name: checkoutProductName(intent.kind, intent.frame_units),
          enabled_variants: [Number(variantId)],
          redirect_url: redirectUrl,
        },
        checkout_data: {
          custom: {
            planetka_intent_id: intent.id,
            planetka_install_id: intent.install_id,
            planetka_kind: intent.kind,
            planetka_frame_count: String(intent.frame_count || 0),
            planetka_frame_units: String(intent.frame_units || 0),
          },
        },
        expires_at: intent.expires_at,
        test_mode: String(env.LEMONSQUEEZY_TEST_MODE || "").trim().toLowerCase() === "true",
      },
      relationships: {
        store: { data: { type: "stores", id: String(storeId) } },
        variant: { data: { type: "variants", id: String(variantId) } },
      },
    },
  };
  const response = await fetch(`${apiBase}/checkouts`, {
    method: "POST",
    headers: {
      Accept: "application/vnd.api+json",
      "Content-Type": "application/vnd.api+json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    console.error("planetka.billing.checkout_failed", JSON.stringify({ status: response.status, payload }));
    throw new Error("billing_checkout_failed");
  }
  const data = payload && payload.data ? payload.data : {};
  const attrs = data && data.attributes ? data.attributes : {};
  return {
    checkout_id: String(data.id || ""),
    checkout_url: String(attrs.url || ""),
  };
}

async function createBillingIntent(db, auth, kind, settings, frameCount = 0) {
  const installId = String(auth && auth.install && auth.install.id || "").trim();
  const id = crypto.randomUUID();
  const createdAt = nowIso();
  const expiresAt = addHoursIso(BILLING_INTENT_TTL_HOURS);
  const safeKind = normalizeBillingKind(kind);
  const frames = safeKind === "animation" ? safeFrameCount(frameCount) : 0;
  const units = safeKind === "animation" ? animationUnitsForFrames(frames) : 0;
  const unitPrice = safeKind === "animation" ? settings.animation_price_per_300_cents : settings.full_resolve_price_cents;
  const amount = safeKind === "animation" ? unitPrice * units : unitPrice;
  const intent = {
    id,
    install_id: installId,
    kind: safeKind,
    status: "pending",
    amount_cents: amount,
    currency: settings.currency,
    frame_count: frames,
    frame_units: units,
    created_at: createdAt,
    expires_at: expiresAt,
  };
  await dbRun(db, `INSERT INTO billing_intents (
    id, install_id, kind, status, amount_cents, currency, frame_count, frame_units, created_at, expires_at, metadata_json
  ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)`, [
    id, installId, safeKind, amount, settings.currency, frames, units, createdAt, expiresAt, JSON.stringify({ install_edition: auth.installEdition || "" }),
  ]);
  return intent;
}

async function findPaidIntent(db, installId, kind) {
  await ensureBillingTables(db);
  return await dbGet(db, `SELECT * FROM billing_intents
    WHERE install_id = ? AND kind = ? AND status = 'paid' AND (expires_at IS NULL OR expires_at > ?)
    ORDER BY paid_at DESC, created_at DESC LIMIT 1`, [installId, kind, nowIso()]);
}

async function consumePaidIntent(db, installId, kind) {
  const row = await findPaidIntent(db, installId, kind);
  if (!row || !row.id) return null;
  const consumedAt = nowIso();
  await dbRun(db, `UPDATE billing_intents SET status = 'consumed', consumed_at = ? WHERE id = ? AND status = 'paid'`, [consumedAt, row.id]);
  return { ...row, status: "consumed", consumed_at: consumedAt };
}

async function markIntentPaid(db, intentId, checkoutId, orderId) {
  if (!intentId) return null;
  await ensureBillingTables(db);
  const paidAt = nowIso();
  await dbRun(db, `UPDATE billing_intents SET status = 'paid', paid_at = COALESCE(paid_at, ?), checkout_id = COALESCE(checkout_id, ?), provider_order_id = COALESCE(provider_order_id, ?)
    WHERE id = ? AND status IN ('pending', 'paid')`, [paidAt, checkoutId || null, orderId || null, intentId]);
  return await dbGet(db, `SELECT * FROM billing_intents WHERE id = ? LIMIT 1`, [intentId]);
}

async function verifyLemonSignature(request, env, rawBody) {
  const secret = String(env.LEMONSQUEEZY_WEBHOOK_SECRET || "").trim();
  if (!secret) throw new Error("billing_webhook_not_configured");
  const signature = String(request.headers.get("X-Signature") || "").trim().toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(signature)) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(rawBody));
  const expected = Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
  if (expected.length !== signature.length) return false;
  let diff = 0;
  for (let index = 0; index < expected.length; index += 1) diff |= expected.charCodeAt(index) ^ signature.charCodeAt(index);
  return diff === 0;
}

export async function handleBillingPrices(request, env, deps) {
  const auth = await deps.requireCloudSessionContext(request, env, { lightweightAccessClaims: false });
  if (auth.error) return auth.error;
  const settings = await getBillingSettings(deps.requireDb(env));
  return deps.json(publicPrices(settings, auth), 200, env);
}

export async function handleBillingCheckout(request, env, deps) {
  const auth = await deps.requireCloudSessionContext(request, env, { lightweightAccessClaims: false });
  if (auth.error) return auth.error;
  const settings = await getBillingSettings(deps.requireDb(env));
  const body = await deps.parseJson(request);
  const kind = normalizeBillingKind(body && body.kind);
  if (!kind) return deps.json({ ok: false, error: "invalid_billing_kind" }, 400, env);
  if (isProInstall(auth)) {
    return deps.json({ ok: true, required: false, paid: true, install_edition: "pro" }, 200, env);
  }
  const db = deps.requireDb(env);
  const paid = await findPaidIntent(db, String(auth.install.id || ""), kind);
  if (paid && paid.id) {
    return deps.json({ ok: true, required: false, paid: true, intent_id: String(paid.id || "") }, 200, env);
  }
  const intent = await createBillingIntent(db, auth, kind, settings, body && (body.frame_count || body.frameCount));
  const checkout = await createLemonCheckout(env, intent, settings);
  await dbRun(db, `UPDATE billing_intents SET checkout_id = ?, checkout_url = ? WHERE id = ?`, [checkout.checkout_id || null, checkout.checkout_url || null, intent.id]);
  return deps.json({
    ok: true,
    required: true,
    paid: false,
    intent_id: intent.id,
    checkout_url: checkout.checkout_url,
    amount_cents: intent.amount_cents,
    currency: intent.currency,
    frame_count: intent.frame_count,
    frame_units: intent.frame_units,
  }, 200, env);
}

export async function handleBillingConsume(request, env, deps) {
  const auth = await deps.requireCloudSessionContext(request, env, { lightweightAccessClaims: false });
  if (auth.error) return auth.error;
  const body = await deps.parseJson(request);
  const kind = normalizeBillingKind(body && body.kind);
  if (!kind) return deps.json({ ok: false, error: "invalid_billing_kind" }, 400, env);
  if (isProInstall(auth)) {
    return deps.json({ ok: true, allowed: true, install_edition: "pro", consumed: false }, 200, env);
  }
  const consumed = await consumePaidIntent(deps.requireDb(env), String(auth.install.id || ""), kind);
  if (consumed && consumed.id) {
    return deps.json({ ok: true, allowed: true, install_edition: "free", consumed: true, intent_id: String(consumed.id || "") }, 200, env);
  }
  return deps.json({ ok: false, allowed: false, error: "payment_required" }, 402, env);
}

export async function handleBillingWebhook(request, env, deps) {
  const rawBody = await request.text();
  const valid = await verifyLemonSignature(request, env, rawBody);
  if (!valid) return deps.json({ ok: false, error: "invalid_signature" }, 403, env);
  let payload = {};
  try { payload = JSON.parse(rawBody || "{}"); } catch (_error) { payload = {}; }
  const meta = payload && payload.meta && typeof payload.meta === "object" ? payload.meta : {};
  const custom = meta.custom_data && typeof meta.custom_data === "object" ? meta.custom_data : {};
  const intentId = String(custom.planetka_intent_id || custom.intent_id || "").trim();
  const checkoutId = String(payload && payload.data && payload.data.attributes && payload.data.attributes.checkout_id || "").trim();
  const orderId = String(payload && payload.data && payload.data.id || "").trim();
  const eventName = String(meta.event_name || request.headers.get("X-Event-Name") || "").trim().toLowerCase();
  if (intentId && (!eventName || eventName === "order_created" || eventName === "order_refunded" || eventName === "order_updated")) {
    if (eventName !== "order_refunded") {
      await markIntentPaid(deps.requireDb(env), intentId, checkoutId, orderId);
    }
  }
  return deps.json({ ok: true }, 200, env);
}

export async function handleAdminBillingPrices(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const db = deps.requireDb(env);
  if (request.method === "GET") {
    const settings = await getBillingSettings(db);
    return deps.json({ ok: true, ...settings }, 200, env);
  }
  const body = await deps.parseJson(request);
  const settings = await setBillingSettings(db, body || {});
  return deps.json({ ok: true, ...settings }, 200, env);
}

export async function readAdminBillingSettings(db) {
  return await getBillingSettings(db);
}
