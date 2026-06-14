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
  if (String(key || "").includes("/clouds_vdb/")) {
    cacheUrl.searchParams.set("__planetka_vdb_revision", "openvdb224_20260601");
  }
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

function normalizeQuotaEdition(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "hobby") return "hobby";
  if (normalized === "pro") return "pro";
  if (normalized === "studio" || normalized === "planetka_studio") return "studio";
  if (normalized === "private") return "pro";
  return "free";
}

function quotaFractionForEdition(edition) {
  const normalized = normalizeQuotaEdition(edition);
  if (normalized === "pro" || normalized === "studio") return 0.15;
  return 0.025;
}

function startOfUtcDayUnix(unixSeconds) {
  const date = new Date(Math.max(0, Number(unixSeconds || 0)) * 1000);
  return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) / 1000);
}

function startOfUtcYearUnix(unixSeconds) {
  const date = new Date(Math.max(0, Number(unixSeconds || 0)) * 1000);
  return Math.floor(Date.UTC(date.getUTCFullYear(), 0, 1) / 1000);
}

function isoDateFromUnix(unixSeconds) {
  return new Date(Math.max(0, Number(unixSeconds || 0)) * 1000).toISOString().slice(0, 10);
}

async function ensureUsageLimitAlertsTable(db, deps) {
  await deps.dbRun(
    db,
    `CREATE TABLE IF NOT EXISTS usage_limit_alerts (
      key TEXT PRIMARY KEY,
      created_at TEXT NOT NULL,
      install_id TEXT NOT NULL,
      install_email TEXT,
      install_edition TEXT NOT NULL,
      alert_kind TEXT NOT NULL,
      period_start_unix INTEGER NOT NULL,
      used_bytes INTEGER NOT NULL,
      limit_bytes INTEGER NOT NULL,
      blocked INTEGER NOT NULL DEFAULT 0
    )`,
  );
}

async function sendUsageLimitAlert(env, payload = {}) {
  const webhookUrl = String(env.PLANETKA_USAGE_ALERT_WEBHOOK_URL || "").trim();
  if (!webhookUrl) return false;
  try {
    const response = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({
        type: "planetka_usage_limit",
        ...payload,
      }),
    });
    return response.ok;
  } catch (_error) {
    return false;
  }
}

async function maybeRecordUsageLimitAlert(env, deps, options = {}) {
  const db = options.db;
  if (!db) return;
  const fullDatabaseBytes = deps.clampNonNegativeInt(env.PLANETKA_FULL_DATABASE_BYTES || 0);
  if (fullDatabaseBytes <= 0) return;
  const installId = String(options.installId || "").trim();
  if (!installId) return;
  const edition = normalizeQuotaEdition(options.installEdition);
  const limitBytes = Math.floor(fullDatabaseBytes * quotaFractionForEdition(edition));
  if (limitBytes <= 0) return;

  const createdAtUnix = deps.clampNonNegativeInt(options.createdAtUnix || Math.floor(Date.now() / 1000));
  const dayStart = startOfUtcDayUnix(createdAtUnix);
  const yearStart = startOfUtcYearUnix(createdAtUnix);
  const dailyRow = await deps.dbGet(
    db,
    `SELECT COALESCE(SUM(bytes_served), 0) AS used_bytes
     FROM tile_request_rollup_daily_install
     WHERE user_id = ? AND day_start_unix = ?`,
    [installId, dayStart],
  );
  const yearlyRow = await deps.dbGet(
    db,
    `SELECT COALESCE(SUM(bytes_served), 0) AS used_bytes
     FROM tile_request_rollup_daily_install
     WHERE user_id = ? AND day_start_unix >= ?`,
    [installId, yearStart],
  );
  const dailyBytes = deps.clampNonNegativeInt(dailyRow && dailyRow.used_bytes || 0);
  const yearlyBytes = deps.clampNonNegativeInt(yearlyRow && yearlyRow.used_bytes || 0);
  const installEmail = String(options.installEmail || "").trim();

  async function alert(kind, periodStartUnix, usedBytes, blocked) {
    const key = `${kind}:${installId}:${periodStartUnix}:${edition}`;
    await ensureUsageLimitAlertsTable(db, deps);
    const result = await deps.dbRun(
      db,
      `INSERT OR IGNORE INTO usage_limit_alerts (
        key, created_at, install_id, install_email, install_edition, alert_kind,
        period_start_unix, used_bytes, limit_bytes, blocked
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        key,
        deps.nowIso(),
        installId,
        installEmail,
        edition,
        kind,
        periodStartUnix,
        deps.clampNonNegativeInt(usedBytes),
        deps.clampNonNegativeInt(limitBytes),
        blocked ? 1 : 0,
      ],
    );
    const changes = Number(result && result.meta && result.meta.changes || 0);
    if (changes <= 0) return;
    await sendUsageLimitAlert(env, {
      alert_kind: kind,
      install_id: installId,
      install_email: installEmail,
      install_edition: edition,
      period_start: isoDateFromUnix(periodStartUnix),
      used_bytes: deps.clampNonNegativeInt(usedBytes),
      limit_bytes: deps.clampNonNegativeInt(limitBytes),
      blocked: Boolean(blocked),
    });
  }

  if (dailyBytes >= limitBytes) {
    await deps.dbRun(db, `UPDATE cloud_installs SET status = 'blocked' WHERE id = ?`, [installId]);
    await alert("daily_limit_reached", dayStart, dailyBytes, true);
    return;
  }
  if (yearlyBytes >= limitBytes) {
    await alert("annual_limit_reached", yearStart, yearlyBytes, false);
  }
}

function isPublicCloudAssetFolder(folder) {
  const normalized = String(folder || "").trim().toLowerCase();
  return normalized === "clouds_global"
    || normalized === "clouds_local_adaptive"
    || normalized === "clouds_local_thumbnails"
    || normalized === "clouds_local_thumbnails_v2"
    || normalized === "clouds_local_thumbnails_v3"
    || normalized === "clouds_vdb_thumbnails_v1"
    || normalized === "clouds_vdb";
}

export async function handleTileSessionStart(request, env, deps) {
  const {
    requireCloudSessionContext,
    parseJson,
    issueTileSessionToken,
    normalizeQualityMode,
    json: jsonResponse,
  } = deps;

  let auth = await requireCloudSessionContext(
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
    body && body.feature ? body.feature : request.headers.get("X-Planetka-Feature") || "",
  ).trim();
  const issued = await issueTileSessionToken(
    env,
    auth,
    requestedQualityMode,
    requestedResolveId,
    { feature: requestedFeature },
  );
  if (issued && issued.error) {
    return issued.error;
  }
  return json(
    {
      ok: true,
      resolve_id: issued.resolveId,
      quality_mode: issued.qualityMode,
      feature: issued.feature || "",
      tile_token: issued.token,
      expires_in_seconds: issued.expiresInSeconds,
      expires_at: issued.expiresAt,
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
    requireCloudSessionContext,
    requireDb,
  } = deps;

  const auth = await requireCloudSessionContext(
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
  const cfCountryRaw = String(request.headers.get("CF-IPCountry") || request.cf && request.cf.country || "").trim().toUpperCase();
  const cfRegion = String(request.cf && (request.cf.region || request.cf.regionCode) || "").trim();

  if (typeof recordResolveSummaryEvent !== "function") {
    return jsonResponse({ ok: false, error: "resolve_summary_unavailable" }, 503, env);
  }

  const result = await recordResolveSummaryEvent(requireDb(env), {
    created_at: deps.nowIso(),
    created_at_unix: Math.floor(Date.now() / 1000),
    user_id: String(auth && ((auth.install && auth.install.id)) || ""),
    user_email: String(auth && ((auth.install && auth.install.email)) || ""),
    resolve_id: resolveId,
    quality_mode: qualityMode,
    bytes_served: bytesServed,
    total_bytes: totalBytes,
    tile_count: tileCount,
    duration_ms: durationMs,
    cf_country: cfCountryRaw && cfCountryRaw !== "XX" && cfCountryRaw !== "T1" ? cfCountryRaw : "UNKNOWN",
    cf_region: cfRegion,
    path: "/tiles/resolve-summary",
  });
  await maybeRecordUsageLimitAlert(env, deps, {
    db: requireDb(env),
    installId: String(auth && ((auth.install && auth.install.id)) || ""),
    installEmail: String(auth && ((auth.install && auth.install.email)) || ""),
    installEdition: String(auth && (auth.installEdition || (auth.access && (auth.access.install_edition || auth.access.access_tier))) || ""),
    createdAtUnix: Math.floor(Date.now() / 1000),
  });
  return jsonResponse({ ok: true, stored: Boolean(result && result.stored) }, 200, env);
}

export async function handleTileRequest(request, env, path, ctx, deps) {
  const {
    clampNonNegativeInt,
    normalizeQualityMode,
    readTileSessionClaims,
    resolveTileCacheControl,
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
  let tokenInstallEdition = "";
  const tileSessionAuth = await readTileSessionClaims(request, env);
  if (tileSessionAuth && tileSessionAuth.error) {
    return tileSessionAuth.error;
  }
  if (tileSessionAuth && tileSessionAuth.claims) {
    tokenQualityMode = normalizeQualityMode(tileSessionAuth.claims.qualityMode || "");
    tokenInstallEdition = String(tileSessionAuth.claims.installEdition || "").trim().toLowerCase();
  } else if (publicCloudAsset) {
    if (typeof deps.requireCloudSessionContext !== "function") {
      return json({ ok: false, error: "missing_cloud_session_context" }, 500, env);
    }
    const cloudAuth = await deps.requireCloudSessionContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: false, lightweightAccessClaims: false },
    );
    if (cloudAuth && cloudAuth.error) {
      return cloudAuth.error;
    }
    tokenInstallEdition = String(
      cloudAuth && (
        cloudAuth.installEdition
        || (cloudAuth.access && (cloudAuth.access.install_edition || cloudAuth.access.access_tier))
      ) || "",
    ).trim().toLowerCase();
    const normalizedAssetEdition = normalizeQuotaEdition(tokenInstallEdition);
    if (normalizedAssetEdition !== "pro" && normalizedAssetEdition !== "studio") {
      return json({ ok: false, error: "cloud_asset_not_available_for_edition" }, 403, env);
    }
  } else {
    return json({ ok: false, error: "missing_tile_session_token" }, 401, env);
  }

  try {
    const prefix = String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
    const key = prefix ? `${prefix}/${folder}/${fileName}` : `${folder}/${fileName}`;
    const qualityModeRaw = String(request.headers.get("X-Planetka-Quality-Mode") || "").trim().toLowerCase();
    const requestedQualityMode = normalizeQualityMode(qualityModeRaw);
    const effectiveQualityMode = requestedQualityMode || tokenQualityMode;
    void effectiveQualityMode;
    if (
      typeof deps.isTileFileAllowedForEdition === "function"
      && !deps.isTileFileAllowedForEdition(tokenInstallEdition, fileName)
    ) {
      return json({ ok: false, error: "tile_not_available_for_edition" }, 403, env);
    }
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
