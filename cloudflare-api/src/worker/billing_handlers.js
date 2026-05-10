import {
  grantPaidSceneTileEntitlements,
  grantRegionPackEntitlements,
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
  const metadata = stripeMetadata(session);
  const email = deps.normalizeEmail(
    session.customer_details && session.customer_details.email
      ? session.customer_details.email
      : (session.customer_email || metadata.planetka_email),
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

  const purchaseType = String(metadata.planetka_purchase_type || "").trim().toLowerCase();
  if (!["scene_tiles", "region_pack"].includes(purchaseType)) {
    console.warn(
      "stripe.webhook.unsupported_purchase_type_ignored",
      JSON.stringify({ event_type: eventType, email, session_id: sessionId, purchase_type: purchaseType }),
    );
    return deps.json(
      {
        ok: true,
        ignored: true,
        reason: "unsupported_purchase_type",
        event_type: eventType,
        purchase_type: purchaseType,
      },
      200,
      env,
    );
  }
  if (
    purchaseType === "scene_tiles"
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

  return deps.json({ ok: true, ignored: true, reason: "unsupported_purchase_type", event_type: eventType }, 200, env);
}

export const billingInternals = {
  claimStripeWebhookEvent,
  stripeSignatureHeaderParts,
  verifyStripeWebhook,
};
