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

function normalizeSceneId(value) {
  return String(value || "").trim().toLowerCase().replace(/[^a-z0-9_.:-]/g, "").slice(0, 160);
}

function normalizeTileFileName(value) {
  const text = String(value || "").trim();
  return text && !text.includes("/") && !text.includes("..") ? text : "";
}

async function ensureScenePurchaseTables(db, deps) {
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS scene_full_quality_purchases (
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
    `CREATE UNIQUE INDEX IF NOT EXISTS idx_scene_purchase_user_scene_paid ON scene_full_quality_purchases(user_id, scene_id)`,
  );
}

async function loadPurchasedScene(db, userId, sceneId, deps) {
  const safeSceneId = normalizeSceneId(sceneId);
  if (!db || !safeSceneId || !userId || !deps || typeof deps.dbGet !== "function") {
    return null;
  }
  await ensureScenePurchaseTables(db, deps);
  return await deps.dbGet(
    db,
    `
      SELECT *
      FROM scene_full_quality_purchases
      WHERE user_id = ? AND scene_id = ? AND status = 'paid'
      LIMIT 1
    `,
    [String(userId || ""), safeSceneId],
  );
}

function purchasedSceneTileFiles(row) {
  try {
    const tiles = JSON.parse(String(row && row.tiles_json || "[]"));
    return Array.isArray(tiles)
      ? tiles.map((tile) => `S2_${String(tile || "").trim()}.exr`).map(normalizeTileFileName).filter(Boolean)
      : [];
  } catch (_error) {
    return [];
  }
}

function isPublicCloudAssetFolder(folder) {
  const normalized = String(folder || "").trim().toLowerCase();
  return normalized === "clouds_global"
    || normalized === "clouds_local"
    || normalized === "clouds_local_adaptive"
    || normalized === "clouds_local_thumbnails"
    || normalized === "clouds_local_thumbnails_v2"
    || normalized === "clouds_local_thumbnails_v3"
    || normalized === "clouds_vdb_thumbnails_v1"
    || normalized === "clouds_vdb";
}

export async function handleTileSessionStart(request, env, deps) {
  const {
    requireAuthenticatedUserContext,
    parseJson,
    issueTileSessionToken,
    normalizeQualityMode,
    normalizeRequestedPlan,
    json: jsonResponse,
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
  const requestedFeature = String(
    body && (body.feature || body.feature_code || body.featureCode) || request.headers.get("X-Planetka-Feature") || "",
  ).trim().toLowerCase();
  const requestedSceneId = normalizeSceneId(
    body && (body.scene_id || body.sceneId) || request.headers.get("X-Planetka-Scene-Id") || "",
  );
  const planCode = normalizeRequestedPlan(
    auth && (auth.qualityAccessPlanCode || auth.planCode || auth.user && auth.user.status),
  );
  const qualityMode = normalizeQualityMode(requestedQualityMode);
  let scenePurchase = null;
  let allowedTileFiles = [];
  if (planCode !== "pro") {
    if (qualityMode === "full") {
      scenePurchase = await loadPurchasedScene(deps.requireDb(env), auth && auth.user && auth.user.id, requestedSceneId, deps);
      allowedTileFiles = purchasedSceneTileFiles(scenePurchase);
      if (!scenePurchase || !allowedTileFiles.length) {
        return jsonResponse(
          {
            ok: false,
            error: "scene_full_quality_purchase_required",
            message: "Full Quality for this scene requires a scene licence.",
          },
          403,
          env,
        );
      }
    }
    if (requestedResolveId.toLowerCase().startsWith("anim-") || requestedFeature === "final_animation_render") {
      return jsonResponse(
        { ok: false, error: "pro_feature_required", message: "Final Animation Render requires a Pro account." },
        403,
        env,
      );
    }
    if (requestedFeature === "panorama") {
      return jsonResponse(
        { ok: false, error: "pro_feature_required", message: "Panoramic camera rendering requires a Pro account." },
        403,
        env,
      );
    }
  }
  const issued = await issueTileSessionToken(
    env,
    auth,
    requestedQualityMode,
    requestedResolveId,
    {
      sceneId: scenePurchase ? requestedSceneId : "",
      allowedTileFiles,
    },
  );
  if (issued && issued.error) {
    return issued.error;
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
      scene_id: scenePurchase ? requestedSceneId : "",
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

  const parts = path.replace(/^\/tiles\//, "").split("/");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    return json({ ok: false, error: "invalid_tile_path" }, 400, env);
  }
  const folder = decodeURIComponent(parts[0]);
  const fileName = decodeURIComponent(parts[1]);
  if (
    folder.includes("/")
    || fileName.includes("/")
    || folder.includes("..")
    || fileName.includes("..")
  ) {
    return json({ ok: false, error: "invalid_tile_path" }, 400, env);
  }
  const publicCloudAsset = isPublicCloudAssetFolder(folder);

  let tokenQualityMode = "";
  const tileSessionAuth = await readTileSessionClaims(request, env);
  if (tileSessionAuth && tileSessionAuth.error) {
    return tileSessionAuth.error;
  }
  if (tileSessionAuth && tileSessionAuth.claims) {
    tokenQualityMode = normalizeQualityMode(tileSessionAuth.claims.qualityMode || "");
  } else if (!publicCloudAsset) {
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
    if (tileSessionAuth && tileSessionAuth.claims) {
      const planCode = firstNonEmpty(
        tileSessionAuth.claims.qualityAccessPlanCode,
        tileSessionAuth.claims.planCode,
        tileSessionAuth.claims.storedPlanCode,
      );
      const allowedTileFiles = Array.isArray(tileSessionAuth.claims.allowedTileFiles)
        ? tileSessionAuth.claims.allowedTileFiles
        : [];
      const sceneAllowsFile = allowedTileFiles.includes(fileName);
      if (
        !publicCloudAsset
        &&
        typeof isTileFileAllowedForPlan === "function"
        && !sceneAllowsFile
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
