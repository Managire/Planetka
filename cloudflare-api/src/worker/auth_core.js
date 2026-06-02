export function createAuthCore(deps) {
  async function createAccessToken(env, user, extraClaims = {}) {
    const secret = deps.requireSecret(env, "JWT_SIGNING_SECRET");
    const exp = Math.floor(Date.now() / 1000) + (60 * 60);
    const effectivePlanCode = deps.normalizeRequestedPlan(
      deps.resolvePolicyPlanCode(user, env),
    ) || deps.PLAN_CODE_PERSONAL;
    const basePayload = {
      type: "access",
      sub: user.id,
      email: user.email,
      plan_code: effectivePlanCode,
      user_status: effectivePlanCode,
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

  async function issueTileSessionToken(env, auth, requestedQualityMode, requestedResolveId = "") {
    const safeQualityMode = deps.normalizeQualityMode(requestedQualityMode);
    const safeStoredPlanCode = deps.normalizeRequestedPlan(auth && auth.planCode);
    const safeQualityAccessPlanCode = deps.normalizeRequestedPlan(
      auth && (auth.qualityAccessPlanCode || auth.planCode),
    );
    const safeResolveId = normalizeResolveId(requestedResolveId) || crypto.randomUUID();
    const ttlSeconds = resolveTileSessionTokenTtlSeconds(env);
    const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
    const payload = {
      type: "tile_session",
      sub: String(auth && auth.user && auth.user.id || "").trim(),
      email: String(auth && auth.user && auth.user.email || "").trim(),
      plan_code: safeQualityAccessPlanCode,
      stored_plan_code: safeStoredPlanCode,
      quality_access_plan_code: safeQualityAccessPlanCode,
      quality_mode: safeQualityMode,
      resolve_id: safeResolveId,
      auth_method: String(auth && auth.authMethod || "").trim(),
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
    const userId = String(payload && payload.sub || "").trim();
    if (!userId) {
      return { error: deps.json({ ok: false, error: "invalid_tile_session_token" }, 401, env) };
    }
    const authMethod = String(payload && payload.auth_method || "").trim();
    const tokenIpScope = String(payload && (payload.client_ip_scope || payload.clientIpScope) || "").trim();
    if (authMethod.toLowerCase() === "anonymous" && tokenIpScope && currentIpScope && tokenIpScope !== currentIpScope) {
      return { error: deps.json({ ok: false, error: "anonymous_ip_scope_changed" }, 401, env) };
    }
    const planCode = deps.normalizeRequestedPlan(payload && (payload.plan_code || payload.user_status) || "");
    const storedPlanCode = deps.normalizeRequestedPlan(
      payload && (payload.stored_plan_code || payload.storedPlanCode || planCode) || "",
    );
    const qualityAccessPlanCode = deps.normalizeRequestedPlan(
      payload && (payload.quality_access_plan_code || payload.qualityAccessPlanCode || planCode) || "",
    );
    const qualityMode = deps.normalizeQualityMode(payload && payload.quality_mode || "");
    const resolveId = normalizeResolveId(payload && payload.resolve_id || "");
    const claims = {
      userId,
      userEmail: String(payload && payload.email || "").trim(),
      planCode,
      storedPlanCode: storedPlanCode || planCode,
      qualityAccessPlanCode: qualityAccessPlanCode || planCode,
      qualityMode,
      resolveId,
      authMethod,
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

  async function createRefreshSession(db, userId, expiresAtOverride = "", metadata = {}) {
    await deps.ensureRefreshSessionColumns(db);
    const refreshToken = deps.randomToken(48);
    const refreshHash = await deps.sha256Hex(refreshToken);
    const refreshSessionId = crypto.randomUUID();
    const createdAt = deps.nowIso();
    const expiresAt = String(expiresAtOverride || "").trim() || deps.addDaysIso(30);
    const authMethod = String(metadata.auth_method || metadata.authMethod || "").trim();
    const deviceId = deps.normalizeDeviceId(metadata.device_id || metadata.deviceId || "");
    const clientIpScope = String(metadata.client_ip_scope || metadata.clientIpScope || "").trim().slice(0, 80);
    await deps.dbRun(
      db,
      `
        INSERT INTO refresh_sessions (
          id,
          user_id,
          refresh_token_hash,
          expires_at,
          created_at,
          auth_method,
          device_id,
          client_ip_scope
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        refreshSessionId,
        userId,
        refreshHash,
        expiresAt,
        createdAt,
        authMethod || null,
        deviceId || null,
        clientIpScope || null,
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
