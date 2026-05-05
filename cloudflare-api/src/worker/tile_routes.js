import { corsHeaders, json } from "./responses.js";
import {
  isFreeCreditTileKey,
  isTileUnlockedForUser,
  tileKeyFromFileName,
  unlockTilesForSession,
} from "./credit_routes.js";

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

function buildTileResponseHeaders(resolveTileCacheControl, clampNonNegativeInt, env, fileName, sizeBytes, etag) {
  const headers = new Headers({
    ...corsHeaders(env),
    "Content-Type": guessContentType(fileName),
    "Content-Length": String(clampNonNegativeInt(sizeBytes)),
    "Cache-Control": resolveTileCacheControl(env),
  });
  if (etag) {
    headers.set("ETag", String(etag));
  }
  return headers;
}

export async function handleTileSessionStart(request, env, deps) {
  const {
    requireAuthenticatedUserContext,
    parseJson,
    issueTileSessionToken,
    normalizeRequestedPlan,
    requireDb,
    json: jsonResponse,
  } = deps;

  const auth = await requireAuthenticatedUserContext(
    request,
    env,
    { enforceApiKeyDevicePolicy: false, lightweightAccessClaims: false },
  );
  if (auth.error) {
    return auth.error;
  }
  const body = await parseJson(request);
  const requestedQualityMode = String(
    body && body.quality_mode ? body.quality_mode : request.headers.get("X-Planetka-Quality-Mode") || "",
  ).trim();
  const requestedResolveId = String(
    body && body.resolve_id ? body.resolve_id : request.headers.get("X-Planetka-Resolve-Id") || "",
  ).trim();
  const creditProtocol = String(body && (body.credit_protocol || body.creditProtocol) || "").trim();
  const creditTileKeys = body && (
    body.tile_keys
    || body.tileKeys
    || body.tiles
    || body.pricing_tiles
    || body.pricingTiles
  );
  const creditEnforced = creditProtocol === "land_credits_v1" && Array.isArray(creditTileKeys);
  const issued = await issueTileSessionToken(
    env,
    auth,
    requestedQualityMode,
    requestedResolveId,
    {
      creditProtocol,
      creditEnforced,
    },
  );
  if (issued && issued.error) {
    return issued.error;
  }
  const db = requireDb(env);
  const unlockResult = creditEnforced
    ? await unlockTilesForSession(
      db,
      auth.user && auth.user.id,
      issued.qualityMode,
      creditTileKeys,
      issued.resolveId,
      deps,
    )
    : { credits: 0, paid_tile_count: 0, free_tile_count: 0, tile_count: 0, legacy_compat: true };
  if (unlockResult && unlockResult.error === "credit_pricing_missing_tile_stats") {
    return jsonResponse(
      {
        ok: false,
        error: "credit_pricing_missing_tile_stats",
        message: "Planetka EUR pricing metadata is missing for a requested tile.",
        tile_key: String(unlockResult.missing_tile_key || ""),
      },
      503,
      env,
    );
  }
  if (unlockResult && unlockResult.error === "insufficient_credits") {
    return jsonResponse(
      {
        ok: false,
        error: "insufficient_credits",
        message: "Not enough Planetka balance for this Resolve.",
        required_credits: Number(unlockResult.required_credits || 0),
        balance_credits: Number(unlockResult.balance_credits || 0),
        paid_tile_count: Number(unlockResult.paid_tile_count || 0),
        tile_count: Number(unlockResult.tile_count || 0),
      },
      402,
      env,
    );
  }
  return json(
    {
      ok: true,
      resolve_id: issued.resolveId,
      quality_mode: issued.qualityMode,
      tile_token: issued.token,
      expires_in_seconds: issued.expiresInSeconds,
      expires_at: issued.expiresAt,
      plan_code: normalizeRequestedPlan(auth && auth.planCode),
      credit_protocol: creditEnforced ? "land_credits_v1" : "legacy_compat",
      credit_enforced: Boolean(creditEnforced),
      credits_charged: Number(unlockResult && unlockResult.credits || 0),
      eur_charged: Number(unlockResult && unlockResult.credits || 0),
      paid_tile_count: Number(unlockResult && unlockResult.paid_tile_count || 0),
    },
    200,
    env,
  );
}

export async function handleTileRequest(request, env, path, ctx, deps) {
  const {
    PLAN_CODE_FREE,
    clampNonNegativeInt,
    isQualityModeAllowedForPlan,
    isTileEventQueueProducerEnabled,
    isTileHotPathMonitoringEnabled,
    maybeSignalTileFarmingActivity,
    minimumPlanQualityForTile,
    normalizeDeviceId,
    normalizeQualityMode,
    normalizeRequestedPlan,
    normalizeResolveId,
    qualityModeNotAllowedMessage,
    readTileSessionClaims,
    recordTileRequestEvent,
    requestClientIp,
    requestCountry,
    requireAuthenticatedUserContext,
    requireDb,
    resolveTileCacheControl,
    nowIso,
  } = deps;

  if (!env.PLANETKA_DATA) {
    return json({ ok: false, error: "missing_r2_binding" }, 500, env);
  }

  const db = requireDb(env);
  let user = { id: "", email: "" };
  let planCode = PLAN_CODE_FREE;
  let qualityAccessPlanCode = PLAN_CODE_FREE;
  let deviceId = "";
  let tokenQualityMode = "";
  let tokenResolveId = "";
  let tokenCreditEnforced = false;
  const tileSessionAuth = await readTileSessionClaims(request, env);
  if (tileSessionAuth && tileSessionAuth.error) {
    return tileSessionAuth.error;
  }
  if (tileSessionAuth && tileSessionAuth.claims) {
    user = {
      id: String(tileSessionAuth.claims.userId || "").trim(),
      email: String(tileSessionAuth.claims.userEmail || "").trim(),
    };
    planCode = normalizeRequestedPlan(tileSessionAuth.claims.storedPlanCode || tileSessionAuth.claims.planCode);
    qualityAccessPlanCode = normalizeRequestedPlan(
      tileSessionAuth.claims.qualityAccessPlanCode || tileSessionAuth.claims.planCode,
    );
    deviceId = normalizeDeviceId(tileSessionAuth.claims.deviceId || request.headers.get("X-Planetka-Device-Id") || "");
    tokenQualityMode = normalizeQualityMode(tileSessionAuth.claims.qualityMode || "");
    tokenResolveId = normalizeResolveId(tileSessionAuth.claims.resolveId || "");
    tokenCreditEnforced = Boolean(tileSessionAuth.claims.creditEnforced);
  } else {
    const auth = await requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: false, lightweightAccessClaims: false },
    );
    if (auth.error) {
      return auth.error;
    }
    user = auth.user;
    planCode = normalizeRequestedPlan(auth.planCode);
    qualityAccessPlanCode = normalizeRequestedPlan(auth.qualityAccessPlanCode || auth.planCode);
    deviceId = normalizeDeviceId(auth.deviceId || request.headers.get("X-Planetka-Device-Id") || "");
  }

  const requestStartedAtMs = Date.now();
  const clientIp = requestClientIp(request);
  const cfCountry = requestCountry(request);
  const cfRay = String(request.headers.get("CF-Ray") || "").trim();
  const resolveIdHeader = normalizeResolveId(request.headers.get("X-Planetka-Resolve-Id") || "");
  if (tokenResolveId && resolveIdHeader && tokenResolveId !== resolveIdHeader) {
    return json({ ok: false, error: "tile_session_resolve_mismatch" }, 403, env);
  }
  const resolveId = tokenResolveId || resolveIdHeader;
  let eventStatusCode = 0;
  let eventBytesServed = 0;
  let eventCacheStatus = "";
  let eventErrorCode = "";
  let eventFolder = "";
  let eventFileName = "";
  let eventTileKey = "";
  let legacyCreditUnlockResult = null;

  try {
    const parts = path.replace(/^\/tiles\//, "").split("/");
    if (parts.length !== 2 || !parts[0] || !parts[1]) {
      eventStatusCode = 400;
      eventErrorCode = "invalid_tile_path";
      return json({ ok: false, error: "invalid_tile_path" }, 400, env);
    }

    const folder = decodeURIComponent(parts[0]);
    const fileName = decodeURIComponent(parts[1]);
    const creditTileKey = tileKeyFromFileName(fileName);
    eventFolder = folder;
    eventFileName = fileName;
    if (
      folder.includes("/") ||
      fileName.includes("/") ||
      folder.includes("..") ||
      fileName.includes("..")
    ) {
      eventStatusCode = 400;
      eventErrorCode = "invalid_tile_path";
      return json({ ok: false, error: "invalid_tile_path" }, 400, env);
    }

    const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
    const key = prefix ? `${prefix}/${folder}/${fileName}` : `${folder}/${fileName}`;
    eventTileKey = key;
    const qualityModeRaw = String(request.headers.get("X-Planetka-Quality-Mode") || "").trim().toLowerCase();
    const requestedQualityMode = normalizeQualityMode(qualityModeRaw);
    if (tokenQualityMode && qualityModeRaw && requestedQualityMode !== tokenQualityMode) {
      eventStatusCode = 403;
      eventErrorCode = "tile_session_quality_mismatch";
      return json({ ok: false, error: "tile_session_quality_mismatch" }, 403, env);
    }
    const effectiveQualityMode = tokenQualityMode || requestedQualityMode;
    const tileRequiredQualityMode = minimumPlanQualityForTile(fileName);
    const creditBillingQualityMode = normalizeQualityMode(
      effectiveQualityMode !== "preview" ? effectiveQualityMode : tileRequiredQualityMode,
    );
    if ((request.method === "GET" || request.method === "HEAD")
      && !tokenCreditEnforced
      && !isQualityModeAllowedForPlan(qualityAccessPlanCode, effectiveQualityMode)) {
      eventStatusCode = 403;
      eventErrorCode = "quality_mode_not_allowed_for_tier";
      return json(
        {
          ok: false,
          error: "quality_mode_not_allowed_for_tier",
          message: qualityModeNotAllowedMessage(planCode, effectiveQualityMode),
          requested_quality_mode: effectiveQualityMode,
        },
        403,
        env,
      );
    }
    if ((request.method === "GET" || request.method === "HEAD")
      && !tokenCreditEnforced
      && !isQualityModeAllowedForPlan(qualityAccessPlanCode, tileRequiredQualityMode)) {
      eventStatusCode = 403;
      eventErrorCode = "tile_quality_not_allowed_for_tier";
      return json(
        {
          ok: false,
          error: "tile_quality_not_allowed_for_tier",
          message: qualityModeNotAllowedMessage(planCode, tileRequiredQualityMode),
          requested_quality_mode: effectiveQualityMode,
          required_quality_mode: tileRequiredQualityMode,
          file_name: fileName,
        },
        403,
        env,
      );
    }
    if (
      (request.method === "GET" || request.method === "HEAD")
      && tokenCreditEnforced
      && effectiveQualityMode !== "preview"
      && creditTileKey
      && !isFreeCreditTileKey(creditTileKey)
    ) {
      const unlocked = await isTileUnlockedForUser(db, user && user.id, creditTileKey, deps, { folder });
      if (!unlocked) {
        eventStatusCode = 402;
        eventErrorCode = "tile_not_unlocked";
        return json(
          {
            ok: false,
            error: "tile_not_unlocked",
            message: "This tile has not been licenced for this account.",
            tile_key: creditTileKey,
            requested_quality_mode: effectiveQualityMode,
          },
          402,
          env,
        );
      }
    }

    const enforceLegacyCreditUnlock = async () => {
      if (
        request.method !== "GET"
        || tokenCreditEnforced
        || creditBillingQualityMode === "preview"
        || !creditTileKey
        || isFreeCreditTileKey(creditTileKey)
      ) {
        return null;
      }
      const unlockResult = await unlockTilesForSession(
        db,
        user && user.id,
        creditBillingQualityMode,
        [creditTileKey],
        resolveId,
        deps,
      );
      if (unlockResult && unlockResult.error === "credit_pricing_missing_tile_stats") {
        return json(
          {
            ok: false,
            error: "credit_pricing_missing_tile_stats",
            message: "Planetka EUR pricing metadata is missing for a requested tile.",
            tile_key: String(unlockResult.missing_tile_key || creditTileKey || ""),
          },
          503,
          env,
        );
      }
      if (unlockResult && unlockResult.error === "insufficient_credits") {
        return json(
          {
            ok: false,
            error: "insufficient_credits",
            message: "Not enough Planetka balance for this tile.",
            required_credits: Number(unlockResult.required_credits || 0),
            balance_credits: Number(unlockResult.balance_credits || 0),
            paid_tile_count: Number(unlockResult.paid_tile_count || 0),
            tile_count: Number(unlockResult.tile_count || 0),
          },
          402,
          env,
        );
      }
      legacyCreditUnlockResult = unlockResult || { credits: 0 };
      return null;
    };

    if (request.method === "HEAD") {
      const objectHead = await env.PLANETKA_DATA.head(key);
      if (!objectHead) {
        eventStatusCode = 404;
        eventErrorCode = "tile_not_found";
        return new Response(null, { status: 404, headers: corsHeaders(env) });
      }
      eventStatusCode = 200;
      eventBytesServed = clampNonNegativeInt(objectHead.size);
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
    let cached = await cache.match(cacheKeyRequest);
    let objectSize = 0;
    let contentType = guessContentType(fileName);
    let etag = "";
    let responseBody = null;
    let cacheStatus = "MISS";

    if (cached) {
      const cachedSize = clampNonNegativeInt(cached.headers.get("Content-Length"));
      cacheStatus = "HIT";
      objectSize = cachedSize;
      contentType = String(cached.headers.get("Content-Type") || contentType);
      etag = String(cached.headers.get("ETag") || "");
      responseBody = cached.body;
    }

    if (!cached) {
      cacheStatus = "MISS";
      const object = await env.PLANETKA_DATA.get(key);
      if (!object) {
        eventStatusCode = 404;
        eventErrorCode = "tile_not_found";
        return new Response("Not Found", { status: 404, headers: corsHeaders(env) });
      }
      objectSize = clampNonNegativeInt(object.size);
      etag = String(object.httpEtag || "");
      const cacheableHeaders = buildTileResponseHeaders(resolveTileCacheControl, clampNonNegativeInt, env, fileName, objectSize, etag);
      const cacheableResponse = new Response(object.body, { status: 200, headers: cacheableHeaders });
      if (ctx && typeof ctx.waitUntil === "function") {
        ctx.waitUntil(cache.put(cacheKeyRequest, cacheableResponse.clone()));
      } else {
        await cache.put(cacheKeyRequest, cacheableResponse.clone());
      }
      responseBody = cacheableResponse.body;
    }

    const legacyCreditError = await enforceLegacyCreditUnlock();
    if (legacyCreditError) {
      eventStatusCode = Number(legacyCreditError.status || 0) || 402;
      eventErrorCode = "legacy_credit_unlock_failed";
      return legacyCreditError;
    }

    const responseHeaders = new Headers({
      ...corsHeaders(env),
      "Content-Type": contentType,
      "Content-Length": String(objectSize),
      "Cache-Control": resolveTileCacheControl(env),
      "X-Planetka-Cache": cacheStatus,
      "X-Planetka-Quality-Mode": effectiveQualityMode,
    });
    if (legacyCreditUnlockResult) {
      responseHeaders.set("X-Planetka-Credit-Protocol", "legacy_per_tile");
      responseHeaders.set("X-Planetka-EUR-Charged", String(Number(legacyCreditUnlockResult.credits || 0)));
    }
    if (etag) {
      responseHeaders.set("ETag", etag);
    }

    eventStatusCode = 200;
    eventBytesServed = objectSize;
    eventCacheStatus = cacheStatus;
    return new Response(responseBody, {
      status: 200,
      headers: responseHeaders,
    });
  } finally {
    const durationMs = Math.max(0, Date.now() - requestStartedAtMs);
    const statusCode = eventStatusCode > 0 ? eventStatusCode : 500;
    const errorCode = String(eventErrorCode || (statusCode >= 400 ? "internal_error" : ""));
    const monitoringEnabled = isTileHotPathMonitoringEnabled(env);
    const tileEventPayload = {
      created_at: nowIso(),
      created_at_unix: Math.floor(Date.now() / 1000),
      user_id: String(user.id || ""),
      user_email: String(user.email || ""),
      device_id: String(deviceId || ""),
      resolve_id: resolveId,
      method: String(request.method || "GET"),
      path,
      folder: eventFolder,
      file_name: eventFileName,
      tile_key: eventTileKey,
      status_code: statusCode,
      bytes_served: eventBytesServed,
      cache_status: eventCacheStatus,
      duration_ms: durationMs,
      cf_ray: cfRay,
      cf_country: cfCountry,
      client_ip: clientIp,
      error_code: errorCode,
      monitoring_enabled: monitoringEnabled,
    };
    const telemetryWrite = recordTileRequestEvent(db, tileEventPayload);
    const processSignals = async () => {
      await telemetryWrite;
      if (!monitoringEnabled) {
        return;
      }
      await maybeSignalTileFarmingActivity(db, env, {
        userId: String(user.id || ""),
        userEmail: String(user.email || ""),
        ip: clientIp,
        deviceId: String(deviceId || ""),
        resolveId,
        tileKey: eventTileKey,
        method: String(request.method || "GET"),
        path,
        statusCode,
      });
    };
    const enqueueTileEvent = async () => {
      if (
        !isTileEventQueueProducerEnabled(env)
        || !env.TILE_EVENT_QUEUE
        || typeof env.TILE_EVENT_QUEUE.send !== "function"
      ) {
        await processSignals();
        return;
      }
      try {
        await env.TILE_EVENT_QUEUE.send(tileEventPayload);
      } catch (error) {
        console.warn(
          "worker.tile_event_queue.enqueue_failed",
          JSON.stringify({
            error: String(error && error.message || "tile_event_queue_enqueue_failed"),
          }),
        );
        try {
          await processSignals();
        } catch (fallbackError) {
          console.warn(
            "worker.tile_event_queue.fallback_failed",
            JSON.stringify({
              error: String(fallbackError && fallbackError.message || "tile_event_fallback_failed"),
            }),
          );
        }
      }
    };
    if (ctx && typeof ctx.waitUntil === "function") {
      ctx.waitUntil(enqueueTileEvent());
    } else {
      await enqueueTileEvent();
    }
  }
}
