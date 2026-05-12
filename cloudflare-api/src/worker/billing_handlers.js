import {
  applyStripeCreditPurchaseFromSession,
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
    return { inserted: false, eventId: "", processingNeeded: false };
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
        received_at,
        processing_status,
        last_attempt_at,
        attempt_count
      ) VALUES (?, ?, ?, ?, ?, 'processing', ?, 1)
      ON CONFLICT(event_id) DO NOTHING
    `,
    [crypto.randomUUID(), eventId, eventType, stripeCreated, deps.nowIso(), deps.nowIso()],
  );
  const inserted = Number(result && result.meta && result.meta.changes) > 0;
  if (inserted) {
    return { inserted: true, eventId, eventType, processingNeeded: true, status: "processing" };
  }
  const existing = await deps.dbGet(
    db,
    `
      SELECT processing_status, attempt_count, last_attempt_at
      FROM stripe_webhook_events
      WHERE event_id = ?
      LIMIT 1
    `,
    [eventId],
  );
  const status = String(existing && existing.processing_status || "").trim().toLowerCase();
  if (status === "processed") {
    return {
      inserted: false,
      eventId,
      eventType,
      processingNeeded: false,
      status: "processed",
      attemptCount: Number(existing && existing.attempt_count || 0) || 0,
    };
  }
  const lastAttemptMs = Date.parse(String(existing && existing.last_attempt_at || ""));
  const processingAgeSeconds = Number.isFinite(lastAttemptMs)
    ? Math.max(0, Math.floor((Date.now() - lastAttemptMs) / 1000))
    : 999999;
  if (status === "processing" && processingAgeSeconds < 300) {
    return {
      inserted: false,
      eventId,
      eventType,
      processingNeeded: false,
      inProgress: true,
      status: "processing",
      processingAgeSeconds,
      attemptCount: Number(existing && existing.attempt_count || 0) || 0,
    };
  }
  await deps.dbRun(
    db,
    `
      UPDATE stripe_webhook_events
      SET
        processing_status = 'processing',
        last_attempt_at = ?,
        attempt_count = COALESCE(attempt_count, 0) + 1,
        error_message = NULL
      WHERE event_id = ?
        AND COALESCE(processing_status, 'processing') != 'processed'
    `,
    [deps.nowIso(), eventId],
  );
  return {
    inserted: false,
    eventId,
    eventType,
    processingNeeded: true,
    status: status || "processing",
    retry: true,
    attemptCount: Number(existing && existing.attempt_count || 0) || 0,
  };
}

async function markStripeWebhookEventProcessed(db, eventId, deps) {
  const safeEventId = String(eventId || "").trim();
  if (!safeEventId) {
    return;
  }
  await deps.dbRun(
    db,
    `
      UPDATE stripe_webhook_events
      SET
        processing_status = 'processed',
        processed_at = ?,
        last_attempt_at = ?,
        error_message = NULL
      WHERE event_id = ?
    `,
    [deps.nowIso(), deps.nowIso(), safeEventId],
  );
}

async function markStripeWebhookEventFailed(db, eventId, deps, error) {
  const safeEventId = String(eventId || "").trim();
  if (!safeEventId) {
    return;
  }
  const message = String(error && error.message || error || "stripe_webhook_processing_failed").slice(0, 1000);
  await deps.dbRun(
    db,
    `
      UPDATE stripe_webhook_events
      SET
        processing_status = 'failed',
        last_attempt_at = ?,
        error_message = ?
      WHERE event_id = ?
    `,
    [deps.nowIso(), message, safeEventId],
  );
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
  if (!claimedEvent.processingNeeded) {
    if (claimedEvent.inProgress) {
      console.log(
        "stripe.webhook.processing_in_progress",
        JSON.stringify({
          event_type: eventType,
          event_id: eventId,
          age_seconds: claimedEvent.processingAgeSeconds || 0,
        }),
      );
      return deps.json(
        {
          ok: false,
          retry: true,
          reason: "event_processing_in_progress",
          event_type: eventType,
          event_id: eventId,
        },
        409,
        env,
      );
    }
    console.log("stripe.webhook.duplicate_processed", JSON.stringify({ event_type: eventType, event_id: eventId }));
    return deps.json(
      {
        ok: true,
        ignored: true,
        reason: "duplicate_event_processed",
        event_type: eventType,
        event_id: eventId,
      },
      200,
      env,
    );
  }
  console.log(
    claimedEvent.inserted ? "stripe.webhook.received" : "stripe.webhook.retrying",
    JSON.stringify({ event_type: eventType, event_id: eventId, status: claimedEvent.status || "" }),
  );

  const processedJson = async (payload, status = 200) => {
    await markStripeWebhookEventProcessed(db, eventId, deps);
    return deps.json(payload, status, env);
  };
  const failedJson = async (payload, status = 500, error = null) => {
    await markStripeWebhookEventFailed(db, eventId, deps, error || payload && payload.error || "stripe_webhook_failed");
    return deps.json(payload, status, env);
  };

  if (eventType !== "checkout.session.completed") {
    console.log("stripe.webhook.ignored", JSON.stringify({ event_type: eventType }));
    return processedJson({ ok: true, ignored: true, event_type: eventType }, 200);
  }

  const session = event.data && event.data.object ? event.data.object : null;
  if (!session) {
    return failedJson({ ok: false, error: "missing_checkout_session" }, 400);
  }
  const sessionId = String(session.id || "").trim();
  if (!sessionId) {
    return failedJson({ ok: false, error: "missing_checkout_session_id" }, 400);
  }
  const metadata = stripeMetadata(session);
  const email = deps.normalizeEmail(
    session.customer_details && session.customer_details.email
      ? session.customer_details.email
      : (session.customer_email || metadata.planetka_email),
  );
  if (!email) {
    console.error("stripe.webhook.missing_email", JSON.stringify({ event_type: eventType }));
    return failedJson({ ok: false, error: "missing_customer_email" }, 400);
  }
  const paymentStatus = String(session.payment_status || "").trim().toLowerCase();
  const paidCheckout = paymentStatus === "paid" || paymentStatus === "no_payment_required";
  if (!paidCheckout) {
    console.log(
      "stripe.webhook.ignored_unpaid_checkout",
      JSON.stringify({ event_type: eventType, email, payment_status: paymentStatus }),
    );
    return processedJson(
      {
        ok: true,
        ignored: true,
        reason: "unpaid_checkout_session",
        event_type: eventType,
        email,
        payment_status: paymentStatus,
      },
      200,
    );
  }

  const purchaseType = String(metadata.planetka_purchase_type || "").trim().toLowerCase();
  if (!["scene_tiles", "region_pack", "animation_tiles"].includes(purchaseType)) {
    console.warn(
      "stripe.webhook.unsupported_purchase_type_ignored",
      JSON.stringify({ event_type: eventType, email, session_id: sessionId, purchase_type: purchaseType }),
    );
    return processedJson(
      {
        ok: true,
        ignored: true,
        reason: "unsupported_purchase_type",
        event_type: eventType,
        purchase_type: purchaseType,
      },
      200,
    );
  }
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
    return failedJson({ ok: false, error: "credit_purchase_user_not_found" }, 404);
  }
  await deps.ensureCreditTables(db);
  const applyResult = await applyStripeCreditPurchaseFromSession(db, session, deps, env);
  if (applyResult && applyResult.error) {
    console.error(
      "stripe.webhook.credit_purchase_failed",
      JSON.stringify({
        event_type: eventType,
        email,
        session_id: sessionId,
        user_id: String(targetUser.id || ""),
        purchase_type: purchaseType,
        error: applyResult.error,
        missing_tile_key: applyResult.missing_tile_key || "",
      }),
    );
    return failedJson(
      { ok: false, error: applyResult.error, tile_key: applyResult.missing_tile_key || "" },
      500,
      applyResult.error,
    );
  }
  const grant = applyResult && applyResult.result || {};
  console.log(
    "stripe.webhook.credit_purchase_processed",
    JSON.stringify({
      event_type: eventType,
      email,
      session_id: sessionId,
      user_id: String(targetUser.id || ""),
      purchase_type: purchaseType,
      amount_paid_eur: eurFromStripeAmountCents(session.amount_total),
      applied: Boolean(applyResult && applyResult.applied),
      duplicate_session: Boolean(applyResult && applyResult.duplicate_session),
      unlocked_tile_count: grant && grant.paid_tile_count || 0,
      free_tile_count: grant && grant.free_tile_count || 0,
    }),
  );
  return processedJson(
    {
      ok: true,
      processed: true,
      event_type: eventType,
      email,
      purchase_type: purchaseType,
      applied: Boolean(applyResult && applyResult.applied),
      duplicate_session: Boolean(applyResult && applyResult.duplicate_session),
      unlocked_tile_count: grant && grant.paid_tile_count || 0,
      free_tile_count: grant && grant.free_tile_count || 0,
    },
    200,
  );
}

export const billingInternals = {
  claimStripeWebhookEvent,
  stripeSignatureHeaderParts,
  verifyStripeWebhook,
};
