import { corsHeaders, json } from "./responses.js";
import {
  tileKeyFromFileName,
} from "./tile_sessions.js";

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

function firstNonEmpty(...values) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) return text;
  }
  return "";
}

function parseFiniteNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : NaN;
}

export async function handleTileSessionStart(request, env, deps) {
  const {
    requireAuthenticatedUserContext,
    parseJson,
    issueTileSessionToken,
    normalizeRequestedPlan,
    isProfessionalPlan,
    personalFreeRegionForPoint,
    personalFreeLocationBlockedMessage,
    requireDb,
    json: jsonResponse,
    createTileDownloadSession,
    normalizeTileKeys,
  } = deps;

  let auth = await requireAuthenticatedUserContext(
    request,
    env,
    { enforceApiKeyDevicePolicy: false, lightweightAccessClaims: false },
  );
  if (auth.error) {
    return auth.error;
  }
  if (typeof deps.resolveTileSessionAuth === "function") {
    const resolvedAuth = await deps.resolveTileSessionAuth(request, env, auth);
    if (resolvedAuth && resolvedAuth.error) {
      return resolvedAuth.error;
    }
    if (resolvedAuth) {
      auth = resolvedAuth;
    }
  }
  const body = await parseJson(request);
  const requestedQualityMode = String(
    body && body.quality_mode ? body.quality_mode : request.headers.get("X-Planetka-Quality-Mode") || "",
  ).trim();
  const requestedResolveId = String(
    body && body.resolve_id ? body.resolve_id : request.headers.get("X-Planetka-Resolve-Id") || "",
  ).trim();
  const planCode = normalizeRequestedPlan(
    auth && (auth.qualityAccessPlanCode || auth.planCode || auth.user && auth.user.status),
  );
  let personalFreeRegion = "";
  if (!isProfessionalPlan(planCode)) {
    const navLatitude = parseFiniteNumber(firstNonEmpty(
      body && (body.nav_latitude_deg ?? body.navLatitudeDeg ?? body.nav_latitude ?? body.navLatitude),
      request.headers.get("X-Planetka-Nav-Latitude"),
    ));
    const navLongitude = parseFiniteNumber(firstNonEmpty(
      body && (body.nav_longitude_deg ?? body.navLongitudeDeg ?? body.nav_longitude ?? body.navLongitude),
      request.headers.get("X-Planetka-Nav-Longitude"),
    ));
    const region = typeof personalFreeRegionForPoint === "function"
      ? personalFreeRegionForPoint(navLatitude, navLongitude)
      : null;
    if (!region || !region.id) {
      return jsonResponse(
        {
          ok: false,
          error: "not_allowed_for_tier",
          message: typeof personalFreeLocationBlockedMessage === "function"
            ? personalFreeLocationBlockedMessage()
            : "Personal accounts can stream Planetka free locations only.",
        },
        403,
        env,
      );
    }
    personalFreeRegion = String(region.id || "").trim();
  }
  const creditProtocol = String(body && (body.credit_protocol || body.creditProtocol) || "").trim();
  const creditTileKeys = body && (
    body.tile_keys
    || body.tileKeys
    || body.tiles
    || body.pricing_tiles
    || body.pricingTiles
  );
  const creditEnforced = creditProtocol === "land_credits_v1" && Array.isArray(creditTileKeys);
  if (creditEnforced) {
    return jsonResponse(
      {
        ok: false,
        error: "legacy_pricing_disabled",
        message: "This Planetka version no longer supports scene-purchase tile sessions. Update Planetka and reconnect your account.",
      },
      410,
      env,
    );
  }
  const sessionId = creditEnforced ? crypto.randomUUID() : "";
  const issued = await issueTileSessionToken(
    env,
    auth,
    requestedQualityMode,
    requestedResolveId,
    {
      creditProtocol,
      creditEnforced,
      sessionId,
      personalFreeRegion,
    },
  );
  if (issued && issued.error) {
    return issued.error;
  }
  const unlockResult = creditEnforced
    && typeof deps.unlockTilesForSession === "function"
    ? await deps.unlockTilesForSession(
      requireDb(env),
      auth.user && auth.user.id,
      issued.qualityMode,
      creditTileKeys,
      issued.resolveId,
      deps,
      { allowSmallSceneFree: true },
    )
    : { credits: 0, paid_tile_count: 0, free_tile_count: 0, tile_count: 0 };
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
  if (unlockResult && unlockResult.error === "tile_unlock_verification_failed") {
    return jsonResponse(
      {
        ok: false,
        error: "tile_unlock_verification_failed",
        message: String(unlockResult.message || "This old tile-session flow is no longer available."),
        tile_key: String(unlockResult.missing_tile_key || ""),
      },
      503,
      env,
    );
  }
  if (
    unlockResult
    && (
      unlockResult.error === "payment_required"
    )
  ) {
    return jsonResponse(
      {
        ok: false,
        error: String(unlockResult.error || "payment_required"),
        message: "This old tile-session flow is no longer available.",
        required_credits: Number(unlockResult.required_credits || 0),
        price_eur: Number(unlockResult.price_eur || unlockResult.required_credits || 0),
        paid_tile_count: Number(unlockResult.paid_tile_count || 0),
        tile_count: Number(unlockResult.tile_count || 0),
      },
      402,
      env,
    );
  }
  if (unlockResult && unlockResult.error) {
    return jsonResponse(
      {
        ok: false,
        error: String(unlockResult.error || "tile_unlock_failed"),
        message: String(unlockResult.message || "This old tile-session flow is no longer available."),
      },
      503,
      env,
    );
  }
  const allowedTileKeys = normalizeTileKeys
    ? normalizeTileKeys(
      body && (
        body.allowed_tile_keys
        || body.allowedTileKeys
        || body.session_tile_keys
        || body.sessionTileKeys
        || creditTileKeys
      ),
    )
    : Array.isArray(creditTileKeys) ? creditTileKeys : [];
  if (creditEnforced && typeof createTileDownloadSession === "function") {
    await createTileDownloadSession(requireDb(env), {
      id: sessionId,
      userId: auth.user && auth.user.id,
      resolveId: issued.resolveId,
      qualityMode: issued.qualityMode,
      creditEnforced: true,
      allowedTileKeys,
      expiresAt: issued.expiresAt,
    });
  }
  return json(
    {
      ok: true,
      resolve_id: issued.resolveId,
      quality_mode: issued.qualityMode,
      tile_token: issued.token,
      expires_in_seconds: issued.expiresInSeconds,
      expires_at: issued.expiresAt,
      plan_code: planCode,
      personal_free_region: personalFreeRegion,
      credit_protocol: creditEnforced ? "land_credits_v1" : "none",
      credit_enforced: Boolean(creditEnforced),
      tile_session_id: sessionId,
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
    clampNonNegativeInt,
    isTileEventQueueProducerEnabled,
    isTileHotPathMonitoringEnabled,
    maybeSignalTileFarmingActivity,
    normalizeDeviceId,
    normalizeQualityMode,
    normalizeResolveId,
    readTileSessionClaims,
    recordPreviewUsageAndMaybeAlert,
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
  let deviceId = "";
  let tokenQualityMode = "";
  let tokenResolveId = "";
  const tileSessionAuth = await readTileSessionClaims(request, env);
  if (tileSessionAuth && tileSessionAuth.error) {
    return tileSessionAuth.error;
  }
  if (tileSessionAuth && tileSessionAuth.claims) {
    user = {
      id: String(tileSessionAuth.claims.userId || "").trim(),
      email: String(tileSessionAuth.claims.userEmail || "").trim(),
    };
    deviceId = normalizeDeviceId(tileSessionAuth.claims.deviceId || request.headers.get("X-Planetka-Device-Id") || "");
    tokenQualityMode = normalizeQualityMode(tileSessionAuth.claims.qualityMode || "");
    tokenResolveId = normalizeResolveId(tileSessionAuth.claims.resolveId || "");
  } else {
    if (request.method !== "HEAD") {
      return json({ ok: false, error: "missing_tile_session_token" }, 401, env);
    }
    const auth = await requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: false, lightweightAccessClaims: false },
    );
    if (auth.error) {
      return auth.error;
    }
    user = auth.user;
    deviceId = normalizeDeviceId(auth.deviceId || request.headers.get("X-Planetka-Device-Id") || "");
  }

  const requestStartedAtMs = Date.now();
  const clientIp = requestClientIp(request);
  const cfCountry = requestCountry(request);
  const cfRay = String(request.headers.get("CF-Ray") || "").trim();
  const resolveIdHeader = normalizeResolveId(request.headers.get("X-Planetka-Resolve-Id") || "");
  const resolveId = tokenResolveId || resolveIdHeader;
  let eventStatusCode = 0;
  let eventBytesServed = 0;
  let eventCacheStatus = "";
  let eventErrorCode = "";
  let eventFolder = "";
  let eventFileName = "";
  let eventTileKey = "";
  let eventQualityMode = "";

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
    const effectiveQualityMode = requestedQualityMode || tokenQualityMode;
    eventQualityMode = effectiveQualityMode;
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

    const responseHeaders = new Headers({
      ...corsHeaders(env),
      "Content-Type": contentType,
      "Content-Length": String(objectSize),
      "Cache-Control": resolveTileCacheControl(env),
      "X-Planetka-Cache": cacheStatus,
      "X-Planetka-Quality-Mode": effectiveQualityMode,
    });
    if (etag) {
      responseHeaders.set("ETag", etag);
    }

    eventStatusCode = 200;
    eventBytesServed = objectSize;
    eventCacheStatus = cacheStatus;
    if (effectiveQualityMode === "preview" && request.method === "GET") {
      const previewUsageWrite = recordPreviewUsageAndMaybeAlert(db, env, {
        created_at_unix: Math.floor(Date.now() / 1000),
        user_id: String(user.id || ""),
        user_email: String(user.email || ""),
        method: "GET",
        quality_mode: effectiveQualityMode,
        status_code: 200,
        bytes_served: objectSize,
        tile_key: creditTileKey || eventTileKey,
      });
      if (ctx && typeof ctx.waitUntil === "function") {
        ctx.waitUntil(previewUsageWrite);
      } else {
        await previewUsageWrite;
      }
    }
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
      quality_mode: eventQualityMode,
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
    const processSignals = async () => {
      await recordTileRequestEvent(db, tileEventPayload);
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
