export function createAuthCore(deps) {
  async function createAccessToken(env, install, extraClaims = {}) {
    const secret = deps.requireSecret(env, "JWT_SIGNING_SECRET");
    const exp = Math.floor(Date.now() / 1000) + (60 * 60);
    const basePayload = {
      type: "access",
      sub: install.id,
      email: install.email,
      exp,
    };
    const payload = { ...basePayload };
    if (extraClaims && typeof extraClaims === "object") {
      for (const [key, value] of Object.entries(extraClaims)) {
        if (value === undefined || value === null || key === "sub" || key === "email" || key === "exp") {
          continue;
        }
        payload[key] = value;
      }
    }
    return deps.signJwt(payload, secret);
  }

  function resolveTileSessionTokenTtlSeconds(env = {}) {
    return Math.min(
      1800,
      Math.max(
        60,
        deps.parseRateLimitInteger(
          env.TILE_SESSION_TOKEN_TTL_SECONDS,
          deps.DEFAULT_TILE_SESSION_TOKEN_TTL_SECONDS,
        ),
      ),
    );
  }

  function normalizeResolveId(value) {
    return String(value || "").trim().slice(0, 128);
  }

  async function issueTileSessionToken(env, auth, requestedQualityMode, requestedResolveId = "", options = {}) {
    const safeQualityMode = deps.normalizeQualityMode(requestedQualityMode);
    const safeFeature = deps.normalizeTileSessionFeature
      ? deps.normalizeTileSessionFeature(options && options.feature || "")
      : "";
    const installEdition = deps.normalizeRequestedAccessTier
      ? deps.normalizeRequestedAccessTier(auth && (auth.installEdition || (auth.access && (auth.access.install_edition || auth.access.access_tier))) || "")
      : (() => {
        const value = String(auth && (auth.installEdition || (auth.access && (auth.access.install_edition || auth.access.access_tier))) || "").trim().toLowerCase();
        if (value === "pro") return "pro";
        if (value === "studio" || value === "planetka_studio") return "studio";
        if (value === "private") return "pro";
        return "free";
      })();
    if (
      typeof deps.isTileSessionFeatureAllowedForEdition === "function"
      && !deps.isTileSessionFeatureAllowedForEdition(installEdition, safeFeature)
    ) {
      return { error: deps.json({ ok: false, error: "feature_not_available_for_edition" }, 403, env) };
    }
    const safeResolveId = normalizeResolveId(requestedResolveId) || crypto.randomUUID();
    const ttlSeconds = resolveTileSessionTokenTtlSeconds(env);
    const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
    const payload = {
      type: "tile_session",
      sub: String(auth && ((auth.install && auth.install.id)) || "").trim(),
      email: String(auth && ((auth.install && auth.install.email)) || "").trim(),
      quality_mode: safeQualityMode,
      feature: safeFeature,
      resolve_id: safeResolveId,
      auth_method: String(auth && auth.authMethod || "").trim(),
      install_edition: installEdition,
      device_id: String(auth && auth.deviceId || "").trim(),
      client_ip_scope: String(auth && auth.access && (auth.access.client_ip_scope || auth.access.clientIpScope) || "").trim(),
      exp,
    };
    const secret = deps.requireSecret(env, "JWT_SIGNING_SECRET");
    const tileToken = await deps.signJwt(payload, secret);
    return {
      token: tileToken,
      resolveId: safeResolveId,
      qualityMode: safeQualityMode,
      feature: safeFeature,
      expiresInSeconds: ttlSeconds,
      expiresAt: new Date(exp * 1000).toISOString(),
      exp,
    };
  }

  async function readTileSessionClaims(request, env) {
    const rawToken = String(request.headers.get("X-Planetka-Tile-Token") || "").trim();
    if (!rawToken) {
      return { claims: null };
    }
    const currentIpScope = typeof deps.requestClientIpScope === "function"
      ? String(deps.requestClientIpScope(request) || "").trim()
      : "";
    const cacheKey = `tile_session:${rawToken}:${currentIpScope}`;
    const cached = deps.authContextCacheGet(cacheKey, env);
    if (cached && cached.tileSessionClaims) {
      return { claims: cached.tileSessionClaims };
    }
    let payload;
    try {
      const secret = deps.requireSecret(env, "JWT_SIGNING_SECRET");
      payload = await deps.verifyJwt(rawToken, secret);
    } catch (error) {
      const code = String(error && error.message || "invalid_tile_token");
      const normalized = code === "token_expired" ? "tile_session_token_expired" : "invalid_tile_session_token";
      return {
        error: deps.json(
          {
            ok: false,
            error: normalized,
          },
          401,
          env,
        ),
      };
    }

    if (String(payload && payload.type || "").trim() !== "tile_session") {
      return { error: deps.json({ ok: false, error: "invalid_tile_session_token" }, 401, env) };
    }
    const installId = String(payload && payload.sub || "").trim();
    if (!installId) {
      return { error: deps.json({ ok: false, error: "invalid_tile_session_token" }, 401, env) };
    }
    const authMethod = String(payload && payload.auth_method || "").trim();
    const tokenIpScope = String(payload && (payload.client_ip_scope || payload.clientIpScope) || "").trim();
    if (authMethod.toLowerCase() === "anonymous" && tokenIpScope && currentIpScope && tokenIpScope !== currentIpScope) {
      return { error: deps.json({ ok: false, error: "anonymous_ip_scope_changed" }, 401, env) };
    }
    const qualityMode = deps.normalizeQualityMode(payload && payload.quality_mode || "");
    const feature = deps.normalizeTileSessionFeature
      ? deps.normalizeTileSessionFeature(payload && payload.feature || "")
      : "";
    const resolveId = normalizeResolveId(payload && payload.resolve_id || "");
    const claims = {
      installId,
      userId: installId,
      userEmail: String(payload && payload.email || "").trim(),
      qualityMode,
      feature,
      resolveId,
      authMethod,
      installEdition: deps.normalizeRequestedAccessTier
        ? deps.normalizeRequestedAccessTier(payload && (payload.install_edition || payload.access_tier) || "")
        : (() => {
          const value = String(payload && (payload.install_edition || payload.access_tier) || "").trim().toLowerCase();
          if (value === "pro") return "pro";
          if (value === "studio" || value === "planetka_studio") return "studio";
          if (value === "private") return "pro";
          return "free";
        })(),
      deviceId: deps.normalizeDeviceId(payload && payload.device_id || ""),
    };
    deps.authContextCacheSet(
      cacheKey,
      {
        access: { exp: Number(payload && payload.exp || 0) || 0 },
        tileSessionClaims: claims,
      },
      env,
    );
    return { claims };
  }

  async function createRefreshSession(db, installId, expiresAtOverride = "", metadata = {}) {
    await deps.ensureRefreshSessionColumns(db);
    const refreshToken = deps.randomToken(48);
    const refreshHash = await deps.sha256Hex(refreshToken);
    const refreshSessionId = crypto.randomUUID();
    const createdAt = deps.nowIso();
    const expiresAt = String(expiresAtOverride || "").trim() || deps.addDaysIso(30);
    const authMethod = String(metadata.auth_method || metadata.authMethod || "").trim();
    const installEdition = deps.normalizeRequestedAccessTier
      ? deps.normalizeRequestedAccessTier(metadata.install_edition || metadata.installEdition || "")
      : (() => {
        const value = String(metadata.install_edition || metadata.installEdition || "").trim().toLowerCase();
        if (value === "pro") return "pro";
        if (value === "studio" || value === "planetka_studio") return "studio";
        if (value === "private") return "pro";
        return "free";
      })();
    const editionSignature = String(metadata.edition_signature || metadata.editionSignature || "").trim().slice(0, 256);
    const deviceId = deps.normalizeDeviceId(metadata.device_id || metadata.deviceId || "");
    const clientIpScope = String(metadata.client_ip_scope || metadata.clientIpScope || "").trim().slice(0, 80);
    const addonVersion = String(metadata.addon_version || metadata.addonVersion || "").trim().slice(0, 80);
    await deps.dbRun(
      db,
      `
        INSERT INTO cloud_session_refresh_tokens (
          id,
          user_id,
          refresh_token_hash,
          expires_at,
          created_at,
          auth_method,
          install_edition,
          edition_signature,
          device_id,
          client_ip_scope,
          addon_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        refreshSessionId,
        installId,
        refreshHash,
        expiresAt,
        createdAt,
        authMethod || null,
        installEdition,
        editionSignature || null,
        deviceId || null,
        clientIpScope || null,
        addonVersion || null,
      ],
    );
    return refreshToken;
  }


  return {
    createAccessToken,
    createRefreshSession,
    issueTileSessionToken,
    normalizeResolveId,
    readTileSessionClaims,
  };
}
