import {
  addCreditBalance,
  grantPaidSceneTileEntitlements,
  grantRegionPackEntitlements,
  grantStandardQualityUnlock,
} from "./credit_routes.js";

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

function stripeMetadata(session) {
  const metadata = session && session.metadata && typeof session.metadata === "object"
    ? session.metadata
    : {};
  return metadata || {};
}

function parseStripeMetadataTileKeys(value) {
  try {
    const parsed = JSON.parse(String(value || "[]"));
    return Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return [];
  }
}

function eurFromStripeAmountCents(value) {
  const cents = Number.parseInt(value, 10);
  if (!Number.isFinite(cents) || cents <= 0) {
    return 0;
  }
  return Math.round((cents / 100.0) * 100.0) / 100.0;
}

function normalizeEur(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.round((parsed + Number.EPSILON) * 100.0) / 100.0;
}

async function verifyStripeWebhook(request, env, rawBody, deps) {
  const secret = deps.requireSecret(env, "STRIPE_WEBHOOK_SECRET");
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
    Math.floor(deps.parsePositiveNumber(env.STRIPE_WEBHOOK_TOLERANCE_SECONDS, 300)),
  );
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSeconds - parsedTimestamp) > toleranceSeconds) {
    throw new Error("stripe_signature_tolerance_exceeded");
  }

  const signedPayload = `${timestamp}.${rawBody}`;
  const computed = await deps.hmacSha256Hex(secret, signedPayload);
  if (!expectedSignatures.includes(computed)) {
    throw new Error("invalid_stripe_signature");
  }

  return JSON.parse(rawBody);
}

async function claimStripeWebhookEvent(db, event, deps) {
  const eventId = String(event && event.id || "").trim();
  if (!eventId) {
    return { inserted: false, eventId: "" };
  }
  const eventType = String(event && event.type || "").trim() || "unknown";
  const stripeCreatedRaw = Number(event && event.created);
  const stripeCreated = Number.isFinite(stripeCreatedRaw)
    ? Math.floor(stripeCreatedRaw)
    : null;
  const result = await deps.dbRun(
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
    [crypto.randomUUID(), eventId, eventType, stripeCreated, deps.nowIso()],
  );
  const inserted = Number(result && result.meta && result.meta.changes) > 0;
  return { inserted, eventId, eventType };
}

function parseStripePlanMap(value, deps) {
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
    const planCode = deps.normalizeRequestedPlan(String(planRaw || "").trim());
    if (!id || !planCode) {
      continue;
    }
    map.set(id, planCode);
  }
  return map;
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

function resolveStripePlanEntitlement(lineItems, env, deps) {
  const byPrice = parseStripePlanMap(env.STRIPE_PLAN_PRICE_CODE_MAP, deps);
  const byProduct = parseStripePlanMap(env.STRIPE_PLAN_PRODUCT_CODE_MAP, deps);
  let resolvedPlan = "";
  const matched = [];
  for (const item of collectStripeLineItemsWithQuantity(lineItems)) {
    let planCode = "";
    if (item.priceId && byPrice.has(item.priceId)) {
      planCode = deps.normalizeRequestedPlan(byPrice.get(item.priceId));
    } else if (item.productId && byProduct.has(item.productId)) {
      planCode = deps.normalizeRequestedPlan(byProduct.get(item.productId));
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
    if (deps.resolvePlanPriority(planCode) > deps.resolvePlanPriority(resolvedPlan)) {
      resolvedPlan = planCode;
    }
  }
  return {
    planCode: deps.normalizeRequestedPlan(resolvedPlan || ""),
    matched,
  };
}

async function fetchStripeCheckoutSessionLineItems(env, sessionId, deps) {
  const secretKey = deps.requireSecret(env, "STRIPE_SECRET_KEY");
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

async function createStripeRefundForCheckoutSession(env, session, details = {}, deps) {
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
  const reason = String(details.reason || "").trim() || "requested_by_customer";
  const secretKey = deps.requireSecret(env, "STRIPE_SECRET_KEY");
  const body = new URLSearchParams();
  if (paymentIntentId) {
    body.set("payment_intent", paymentIntentId);
  } else {
    body.set("charge", chargeId);
  }
  body.set("reason", "requested_by_customer");
  const existingPlanCode = deps.normalizeRequestedPlan(details.existingPlanCode || "");
  const requestedPlanCode = deps.normalizeRequestedPlan(details.requestedPlanCode || "");
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

async function applyPermanentLicenseEntitlement(db, env, details = {}, deps) {
  const email = deps.normalizeEmail(details.email || "");
  if (!email) {
    throw new Error("missing_customer_email");
  }
  const requestedPlan = deps.normalizePlanCode(details.planCode || "");
  if (!requestedPlan || (requestedPlan !== deps.PLAN_CODE_PERSONAL && requestedPlan !== deps.PLAN_CODE_COMMERCIAL)) {
    throw new Error("missing_plan_code");
  }
  const existingUser = await deps.findUserByEmail(db, email);
  const existingStatus = deps.normalizeUserStatus(existingUser && existingUser.status);
  const finalPlan = (
    requestedPlan === deps.PLAN_CODE_PERSONAL
    && existingStatus === deps.PLAN_CODE_COMMERCIAL
  )
    ? deps.PLAN_CODE_COMMERCIAL
    : requestedPlan;

  let user = await deps.upsertUserByEmail(db, email, finalPlan, {}, env);
  user = await deps.enforceUserPlanPolicy(db, user, env);
  if (!user || !user.id) {
    throw new Error("user_upsert_failed");
  }
  const currentPlanCode = deps.normalizeRequestedPlan(user && user.status || "");
  let appliedPlanCode = currentPlanCode;
  if (currentPlanCode !== finalPlan) {
    await deps.dbRun(
      db,
      `UPDATE users SET status = ? WHERE id = ?`,
      [finalPlan, String(user.id || "").trim()],
    );
    appliedPlanCode = finalPlan;
    user = { ...user, status: finalPlan };
  }
  await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        expires_at = NULL
      WHERE user_id = ?
        AND status = 'active'
    `,
    [appliedPlanCode, String(user.id || "").trim()],
  );

  return {
    user,
    planCode: appliedPlanCode,
  };
}

export async function handleStripeWebhook(request, env, deps) {
  const db = deps.requireDb(env);
  await deps.ensureStripeWebhookEventsTable(db);
  const rawBody = await request.text();
  const event = await verifyStripeWebhook(request, env, rawBody, deps);
  const claimedEvent = await claimStripeWebhookEvent(db, event, deps);
  const eventType = String(event.type || "");
  const eventId = String(claimedEvent.eventId || "").trim();
  if (!eventId) {
    return deps.json({ ok: false, error: "missing_stripe_event_id" }, 400, env);
  }
  if (!claimedEvent.inserted) {
    console.log("stripe.webhook.duplicate", JSON.stringify({ event_type: eventType, event_id: eventId }));
    return deps.json(
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
    return deps.json({ ok: true, ignored: true, event_type: eventType }, 200, env);
  }

  const session = event.data && event.data.object ? event.data.object : null;
  if (!session) {
    return deps.json({ ok: false, error: "missing_checkout_session" }, 400, env);
  }
  const sessionId = String(session.id || "").trim();
  if (!sessionId) {
    return deps.json({ ok: false, error: "missing_checkout_session_id" }, 400, env);
  }
  const email = deps.normalizeEmail(
    session.customer_details && session.customer_details.email
      ? session.customer_details.email
      : session.customer_email,
  );
  if (!email) {
    console.error("stripe.webhook.missing_email", JSON.stringify({ event_type: eventType }));
    return deps.json({ ok: false, error: "missing_customer_email" }, 400, env);
  }
  const paymentStatus = String(session.payment_status || "").trim().toLowerCase();
  const paidCheckout = paymentStatus === "paid" || paymentStatus === "no_payment_required";
  if (!paidCheckout) {
    console.log(
      "stripe.webhook.ignored_unpaid_checkout",
      JSON.stringify({ event_type: eventType, email, payment_status: paymentStatus }),
    );
    return deps.json(
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

  const metadata = stripeMetadata(session);
  const purchaseType = String(metadata.planetka_purchase_type || "").trim().toLowerCase();
  if (
    purchaseType === "balance_top_up"
    || purchaseType === "scene_tiles"
    || purchaseType === "standard_quality_unlock"
    || purchaseType === "region_pack"
  ) {
    const metadataUserId = String(metadata.planetka_user_id || "").trim();
    let targetUser = metadataUserId && typeof deps.findUserById === "function"
      ? await deps.findUserById(db, metadataUserId)
      : null;
    if (!targetUser) {
      targetUser = await deps.findUserByEmail(db, email);
    }
    if (!targetUser || !targetUser.id) {
      console.error(
        "stripe.webhook.credit_purchase_missing_user",
        JSON.stringify({ event_type: eventType, email, session_id: sessionId, purchase_type: purchaseType }),
      );
      return deps.json({ ok: false, error: "credit_purchase_user_not_found" }, 404, env);
    }
    await deps.ensureCreditTables(db);
    const userId = String(targetUser.id || "").trim();
    const amountPaidEur = eurFromStripeAmountCents(session.amount_total);
    const stripePaymentIntentId = String(session.payment_intent || session.payment_intent_id || "").trim();
    if (purchaseType === "balance_top_up") {
      const requestedTopUp = Number.parseFloat(metadata.planetka_top_up_eur || "");
      const topUpEur = Number.isFinite(requestedTopUp) && requestedTopUp > 0
        ? normalizeEur(requestedTopUp)
        : amountPaidEur;
      const topUp = await addCreditBalance(
        db,
        userId,
        topUpEur,
        "stripe_balance_top_up",
        {
          stripe_session_id: sessionId,
          stripe_payment_intent_id: stripePaymentIntentId,
          stripe_amount_paid_eur: amountPaidEur,
          customer_email: email,
        },
        deps,
      );
      if (topUp.error) {
        return deps.json({ ok: false, error: topUp.error }, 400, env);
      }
      if (typeof deps.invalidateAnalyticsSnapshots === "function") {
        try {
          await deps.invalidateAnalyticsSnapshots(env);
        } catch (error) {
          console.warn(
            "stripe.webhook.balance_top_up_snapshot_invalidate_failed",
            JSON.stringify({ error: String(error && error.message || "snapshot_invalidate_failed"), user_id: userId }),
          );
        }
      }
      console.log(
        "stripe.webhook.balance_top_up_processed",
        JSON.stringify({
          event_type: eventType,
          email,
          session_id: sessionId,
          user_id: userId,
          top_up_eur: topUpEur,
          balance_eur: topUp.balance_eur,
        }),
      );
      return deps.json(
        {
          ok: true,
          processed: true,
          event_type: eventType,
          email,
          purchase_type: purchaseType,
          balance_eur: topUp.balance_eur,
        },
        200,
        env,
      );
    }

    if (purchaseType === "standard_quality_unlock") {
      const unlock = await grantStandardQualityUnlock(
        db,
        userId,
        sessionId,
        amountPaidEur,
        deps,
        email,
        stripePaymentIntentId,
      );
      if (unlock && unlock.error) {
        return deps.json({ ok: false, error: unlock.error }, 400, env);
      }
      if (typeof deps.invalidateAnalyticsSnapshots === "function") {
        try {
          await deps.invalidateAnalyticsSnapshots(env);
        } catch (error) {
          console.warn(
            "stripe.webhook.standard_quality_snapshot_invalidate_failed",
            JSON.stringify({ error: String(error && error.message || "snapshot_invalidate_failed"), user_id: userId }),
          );
        }
      }
      console.log(
        "stripe.webhook.standard_quality_unlock_processed",
        JSON.stringify({
          event_type: eventType,
          email,
          session_id: sessionId,
          user_id: userId,
          amount_paid_eur: amountPaidEur,
          already_unlocked: Boolean(unlock && unlock.already_unlocked),
        }),
      );
      return deps.json(
        {
          ok: true,
          processed: true,
          event_type: eventType,
          email,
          purchase_type: purchaseType,
          standard_quality_unlocked: Boolean(unlock && unlock.standard_quality_unlocked),
        },
        200,
        env,
      );
    }

    if (purchaseType === "region_pack") {
      const regionPackId = String(metadata.planetka_region_id || "").trim();
      const grant = await grantRegionPackEntitlements(
        db,
        userId,
        regionPackId,
        sessionId,
        amountPaidEur,
        deps,
        email,
        stripePaymentIntentId,
      );
      if (grant && grant.error) {
        console.error(
          "stripe.webhook.region_pack_purchase_failed",
          JSON.stringify({
            event_type: eventType,
            email,
            session_id: sessionId,
            user_id: userId,
            region_pack_id: regionPackId,
            error: grant.error,
          }),
        );
        return deps.json({ ok: false, error: grant.error }, 500, env);
      }
      if (typeof deps.invalidateAnalyticsSnapshots === "function") {
        try {
          await deps.invalidateAnalyticsSnapshots(env);
        } catch (error) {
          console.warn(
            "stripe.webhook.region_pack_snapshot_invalidate_failed",
            JSON.stringify({ error: String(error && error.message || "snapshot_invalidate_failed"), user_id: userId }),
          );
        }
      }
      console.log(
        "stripe.webhook.region_pack_purchase_processed",
        JSON.stringify({
          event_type: eventType,
          email,
          session_id: sessionId,
          user_id: userId,
          amount_paid_eur: amountPaidEur,
          region_pack_id: regionPackId,
          unlocked_tile_count: grant && grant.paid_tile_count || 0,
        }),
      );
      return deps.json(
        {
          ok: true,
          processed: true,
          event_type: eventType,
          email,
          purchase_type: purchaseType,
          region_pack_id: regionPackId,
          unlocked_tile_count: grant && grant.paid_tile_count || 0,
        },
        200,
        env,
      );
    }

    const tileKeys = parseStripeMetadataTileKeys(metadata.planetka_tile_keys_json);
    const qualityMode = deps.normalizeQualityMode(metadata.planetka_quality_mode || "full");
    const grant = await grantPaidSceneTileEntitlements(
      db,
      userId,
      qualityMode,
      tileKeys,
      sessionId,
      amountPaidEur,
      deps,
      email,
      stripePaymentIntentId,
    );
    if (grant && grant.error) {
      console.error(
        "stripe.webhook.scene_purchase_failed",
        JSON.stringify({
          event_type: eventType,
          email,
          session_id: sessionId,
          user_id: userId,
          error: grant.error,
          missing_tile_key: grant.missing_tile_key || "",
        }),
      );
      return deps.json({ ok: false, error: grant.error, tile_key: grant.missing_tile_key || "" }, 500, env);
    }
    if (typeof deps.invalidateAnalyticsSnapshots === "function") {
      try {
        await deps.invalidateAnalyticsSnapshots(env);
      } catch (error) {
        console.warn(
          "stripe.webhook.scene_purchase_snapshot_invalidate_failed",
          JSON.stringify({ error: String(error && error.message || "snapshot_invalidate_failed"), user_id: userId }),
        );
      }
    }
    console.log(
      "stripe.webhook.scene_purchase_processed",
      JSON.stringify({
        event_type: eventType,
        email,
        session_id: sessionId,
        user_id: userId,
        amount_paid_eur: amountPaidEur,
        tile_count: Array.isArray(tileKeys) ? tileKeys.length : 0,
        unlocked_tile_count: grant && grant.paid_tile_count || 0,
      }),
    );
    return deps.json(
      {
        ok: true,
        processed: true,
        event_type: eventType,
        email,
        purchase_type: purchaseType,
        unlocked_tile_count: grant && grant.paid_tile_count || 0,
      },
      200,
      env,
    );
  }

  const lineItems = await fetchStripeCheckoutSessionLineItems(env, sessionId, deps);
  const planEntitlement = resolveStripePlanEntitlement(lineItems, env, deps);
  if (planEntitlement.planCode) {
    let existingPlanCode = deps.PLAN_CODE_FREE;
    const existingUser = await deps.findUserByEmail(db, email);
    if (existingUser && !deps.isBlockedStatus(existingUser.status)) {
      const enforcedUser = await deps.enforceUserPlanPolicy(db, existingUser, env);
      existingPlanCode = deps.normalizeRequestedPlan(deps.resolvePlanCode(enforcedUser, env));
    }
    const purchaseGuard = deps.evaluateStripePlanPurchaseGuard(existingPlanCode, planEntitlement.planCode);
    if (purchaseGuard.blocked) {
      const refund = await createStripeRefundForCheckoutSession(
        env,
        session,
        {
          reason: purchaseGuard.reason,
          existingPlanCode: purchaseGuard.existingPlanCode,
          requestedPlanCode: purchaseGuard.requestedPlanCode,
        },
        deps,
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
      return deps.json(
        {
          ok: true,
          ignored: true,
          reason: purchaseGuard.reason,
          event_type: eventType,
          email,
          existing_plan_code: purchaseGuard.existingPlanCode,
          requested_plan_code: purchaseGuard.requestedPlanCode,
          message: `This email already has ${deps.planDisplayName(purchaseGuard.existingPlanCode)}.`,
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
      deps,
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
    return deps.json(
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
  return deps.json(
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

export const billingInternals = {
  applyPermanentLicenseEntitlement,
  claimStripeWebhookEvent,
  collectStripeLineItemsWithQuantity,
  createStripeRefundForCheckoutSession,
  fetchStripeCheckoutSessionLineItems,
  parseStripePlanMap,
  resolveStripePlanEntitlement,
  stripeSignatureHeaderParts,
  verifyStripeWebhook,
};
