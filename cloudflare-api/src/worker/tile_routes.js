import { corsHeaders, json } from "./responses.js";

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

export async function handleResolveSummary(request, env, deps) {
  const {
    clampNonNegativeInt,
    json: jsonResponse,
    normalizeQualityMode,
    normalizeResolveId,
    parseJson,
    recordResolveSummaryEvent,
    requireAuthenticatedUserContext,
    requireDb,
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
  const resolveId = normalizeResolveId(
    body && (body.resolve_id || body.resolveId) || request.headers.get("X-Planetka-Resolve-Id") || "",
  );
  if (!resolveId) {
    return jsonResponse({ ok: false, error: "missing_resolve_id" }, 400, env);
  }
  const qualityMode = normalizeQualityMode(
    body && (body.quality_mode || body.qualityMode) || request.headers.get("X-Planetka-Quality-Mode") || "",
  );
  const bytesServed = clampNonNegativeInt(body && (
    body.bytes_served
    || body.bytesServed
    || body.downloaded_bytes
    || body.downloadedBytes
  ));
  const totalBytes = clampNonNegativeInt(body && (body.total_bytes || body.totalBytes));
  const tileCount = clampNonNegativeInt(body && (body.tile_count || body.tileCount));
  const durationMs = clampNonNegativeInt(body && (body.duration_ms || body.durationMs));

  if (typeof recordResolveSummaryEvent !== "function") {
    return jsonResponse({ ok: false, error: "resolve_summary_unavailable" }, 503, env);
  }

  const result = await recordResolveSummaryEvent(requireDb(env), {
    created_at: deps.nowIso(),
    created_at_unix: Math.floor(Date.now() / 1000),
    user_id: String(auth && auth.user && auth.user.id || ""),
    user_email: String(auth && auth.user && auth.user.email || ""),
    resolve_id: resolveId,
    quality_mode: qualityMode,
    bytes_served: bytesServed,
    total_bytes: totalBytes,
    tile_count: tileCount,
    duration_ms: durationMs,
    path: "/tiles/resolve-summary",
  });
  return jsonResponse({ ok: true, stored: Boolean(result && result.stored) }, 200, env);
}

export async function handleTileRequest(request, env, path, ctx, deps) {
  const {
    clampNonNegativeInt,
    normalizeQualityMode,
    isTileFileAllowedForPlan,
    readTileSessionClaims,
    requireAuthenticatedUserContext,
    resolveTileCacheControl,
    tileFileNotAllowedMessage,
  } = deps;

  if (!env.PLANETKA_DATA) {
    return json({ ok: false, error: "missing_r2_binding" }, 500, env);
  }

  let tokenQualityMode = "";
  const tileSessionAuth = await readTileSessionClaims(request, env);
  if (tileSessionAuth && tileSessionAuth.error) {
    return tileSessionAuth.error;
  }
  if (tileSessionAuth && tileSessionAuth.claims) {
    tokenQualityMode = normalizeQualityMode(tileSessionAuth.claims.qualityMode || "");
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
  }

  try {
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
    if (tileSessionAuth && tileSessionAuth.claims) {
      const planCode = firstNonEmpty(
        tileSessionAuth.claims.qualityAccessPlanCode,
        tileSessionAuth.claims.planCode,
        tileSessionAuth.claims.storedPlanCode,
      );
      if (
        typeof isTileFileAllowedForPlan === "function"
        && !isTileFileAllowedForPlan(planCode, fileName)
      ) {
        return json(
          {
            ok: false,
            error: "tile_quality_not_allowed_for_tier",
            message: typeof tileFileNotAllowedMessage === "function"
              ? tileFileNotAllowedMessage(planCode, fileName)
              : "This texture file is not available for this account.",
            plan_code: planCode,
          },
          403,
          env,
        );
      }
    }

    const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
    const key = prefix ? `${prefix}/${folder}/${fileName}` : `${folder}/${fileName}`;
    const qualityModeRaw = String(request.headers.get("X-Planetka-Quality-Mode") || "").trim().toLowerCase();
    const requestedQualityMode = normalizeQualityMode(qualityModeRaw);
    const effectiveQualityMode = requestedQualityMode || tokenQualityMode;
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

    return new Response(responseBody, {
      status: 200,
      headers: responseHeaders,
    });
  } finally {
    // Tile requests are the hot path. Usage analytics are recorded once per
    // completed resolve through /tiles/resolve-summary, not once per tile file.
  }
}
