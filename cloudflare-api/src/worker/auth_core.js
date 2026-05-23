export function createAuthCore(deps) {
  async function isApiKeyUsableById(db, apiKeyId, expectedUserId = "") {
    await deps.ensureApiKeyTables(db);
    const safeApiKeyId = String(apiKeyId || "").trim();
    if (!safeApiKeyId) {
      return false;
    }
    const row = await deps.dbGet(
      db,
      `
        SELECT id, user_id, status, expires_at
        FROM api_keys
        WHERE id = ?
        LIMIT 1
      `,
      [safeApiKeyId],
    );
    if (!row || !row.id) {
      return false;
    }
    if (String(row.status || "").trim().toLowerCase() !== "active") {
      return false;
    }
    const safeExpectedUserId = String(expectedUserId || "").trim();
    if (safeExpectedUserId && String(row.user_id || "").trim() !== safeExpectedUserId) {
      return false;
    }
    return true;
  }

  async function issueApiKeyForUser(db, env, user, planCode, options = {}) {
    await deps.ensureApiKeyTables(db);
    const safePlan = deps.normalizeRequestedPlan(planCode || user.status || deps.PLAN_CODE_FREE);
    const token = `pka_${deps.randomToken(36)}`;
    const keyHash = await deps.sha256Hex(token);
    const keyPrefix = String(token.slice(0, 16));
    const keyId = crypto.randomUUID();
    const issuedAt = deps.nowIso();
    void options;
    const expiresAt = String(options.expiresAt || deps.computeApiKeyExpiryIso(safePlan, env) || "").trim();
    await deps.dbRun(
      db,
      `
        INSERT INTO api_keys (
          id,
          user_id,
          key_hash,
          key_prefix,
          status,
          plan_code,
          expires_at,
          issued_at
        ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
      `,
      [
        keyId,
        user.id,
        keyHash,
        keyPrefix,
        safePlan,
        expiresAt || null,
        issuedAt,
      ],
    );
    if (safePlan === deps.PLAN_CODE_FREE) {
      await deps.enforceSingleActiveFreeApiKey(
        db,
        String(user && user.id || "").trim(),
        keyId,
      );
    }

    return {
      apiKey: token,
      apiKeyId: keyId,
      keyPrefix,
      planCode: safePlan,
      expiresAt,
    };
  }

  async function findActiveApiKeyRecord(db, apiKeyValue) {
    await deps.ensureApiKeyTables(db);
    const keyHash = await deps.sha256Hex(apiKeyValue);
    return deps.dbGet(
      db,
      `
        SELECT
          ak.id AS api_key_id,
          ak.user_id,
          ak.status AS api_key_status,
          ak.plan_code AS api_key_plan_code,
          ak.expires_at AS api_key_expires_at,
          ak.key_prefix,
          u.id,
          u.email,
          u.status,
          u.created_at,
          u.last_login_at
        FROM api_keys ak
        JOIN users u ON u.id = ak.user_id
        WHERE ak.key_hash = ?
        LIMIT 1
      `,
      [keyHash],
    );
  }

  function maxDevicesForPlan(planCode) {
    void deps.normalizeRequestedPlan(planCode);
    return 1;
  }

  async function listActiveApiKeyDevicesForUser(db, userId, env) {
    await deps.ensureApiKeyTables(db);
    const safeUserId = String(userId || "").trim();
    if (!safeUserId) {
      return new Set();
    }
    const nowUnix = Math.floor(Date.now() / 1000);
    const activeWindowSeconds = Math.max(
      60,
      Math.floor(
        deps.parsePositiveNumber(
          env.API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS,
          deps.DEFAULT_API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS,
        ),
      ),
    );
    const windowStart = Math.max(0, nowUnix - activeWindowSeconds);

    await deps.dbRun(
      db,
      `
        DELETE FROM api_key_device_activity
        WHERE last_seen_unix < ?
      `,
      [Math.max(0, nowUnix - (activeWindowSeconds * 4))],
    );

    const rows = await deps.dbAll(
      db,
      `
        SELECT DISTINCT device_id
        FROM api_key_device_activity
        WHERE user_id = ?
          AND last_seen_unix >= ?
      `,
      [safeUserId, windowStart],
    );
    return new Set(
      rows.map((row) => deps.normalizeDeviceId(row && row.device_id)).filter((value) => Boolean(value)),
    );
  }

  async function enforceApiKeyIssueDeviceLimit(db, userId, userEmail, planCode, deviceId, env) {
    const safeUserId = String(userId || "").trim();
    if (!safeUserId) {
      return { activeDeviceCount: 0, maxDevices: maxDevicesForPlan(planCode), matchedDevice: false };
    }
    if (deps.isDeviceLimitExemptEmail(userEmail, env)) {
      return { activeDeviceCount: 0, maxDevices: Number.MAX_SAFE_INTEGER, matchedDevice: true, exempted: true };
    }
    const safeDeviceId = deps.normalizeDeviceId(deviceId);
    const activeDeviceIds = await listActiveApiKeyDevicesForUser(db, safeUserId, env);
    const maxDevices = maxDevicesForPlan(planCode);
    const matchedDevice = Boolean(safeDeviceId && activeDeviceIds.has(safeDeviceId));
    if (activeDeviceIds.size >= maxDevices && !matchedDevice) {
      throw new Error("device_limit_exceeded");
    }
    return {
      activeDeviceCount: activeDeviceIds.size,
      maxDevices,
      matchedDevice,
    };
  }

  async function touchApiKeyDeviceActivity(db, apiKeyId, userId, deviceId, request, env) {
    await deps.ensureApiKeyTables(db);
    const safeUserId = String(userId || "").trim();
    const safeDeviceId = deps.normalizeDeviceId(deviceId);
    if (!safeUserId || !safeDeviceId) {
      throw new Error("missing_device_id");
    }
    const nowUnix = Math.floor(Date.now() / 1000);
    const now = deps.nowIso();
    const ip = deps.requestClientIp(request);
    const country = deps.requestCountry(request);
    const existingRows = await deps.dbAll(
      db,
      `
        SELECT id
        FROM api_key_device_activity
        WHERE user_id = ? AND device_id = ?
        ORDER BY last_seen_unix DESC
      `,
      [safeUserId, safeDeviceId],
    );
    const primaryExisting = Array.isArray(existingRows) && existingRows.length > 0 ? existingRows[0] : null;
    if (primaryExisting && primaryExisting.id) {
      await deps.dbRun(
        db,
        `
          UPDATE api_key_device_activity
          SET
            api_key_id = ?,
            last_seen_at = ?,
            last_seen_unix = ?,
            last_ip = ?,
            last_country = ?
          WHERE id = ?
        `,
        [apiKeyId, now, nowUnix, ip, country, primaryExisting.id],
      );
      if (existingRows.length > 1) {
        await deps.dbRun(
          db,
          `
            DELETE FROM api_key_device_activity
            WHERE user_id = ?
              AND device_id = ?
              AND id != ?
          `,
          [safeUserId, safeDeviceId, primaryExisting.id],
        );
      }
      return primaryExisting.id;
    }
    await deps.dbRun(
      db,
      `
        INSERT INTO api_key_device_activity (
          id,
          api_key_id,
          user_id,
          device_id,
          first_seen_at,
          last_seen_at,
          last_seen_unix,
          last_ip,
          last_country
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [crypto.randomUUID(), apiKeyId, safeUserId, safeDeviceId, now, now, nowUnix, ip, country],
    );
    return "";
  }

  async function enforceApiKeyDeviceLimit(db, apiKeyId, userId, userEmail, planCode, deviceId, request, env) {
    await deps.ensureApiKeyTables(db);
    const safeUserId = String(userId || "").trim();
    if (!safeUserId) {
      throw new Error("user_not_found");
    }
    const safeDeviceId = deps.normalizeDeviceId(deviceId);
    if (!safeDeviceId) {
      throw new Error("missing_device_id");
    }
    const activeDeviceIds = await listActiveApiKeyDevicesForUser(db, safeUserId, env);
    if (deps.isDeviceLimitExemptEmail(userEmail, env)) {
      await touchApiKeyDeviceActivity(db, apiKeyId, safeUserId, safeDeviceId, request, env);
      return {
        activeDeviceCount: activeDeviceIds.has(safeDeviceId) ? activeDeviceIds.size : (activeDeviceIds.size + 1),
        maxDevices: Number.MAX_SAFE_INTEGER,
        exempted: true,
      };
    }
    const alreadyActive = activeDeviceIds.has(safeDeviceId);
    const maxDevices = maxDevicesForPlan(planCode);
    if (!alreadyActive && activeDeviceIds.size >= maxDevices) {
      throw new Error("device_limit_exceeded");
    }

    await touchApiKeyDeviceActivity(db, apiKeyId, safeUserId, safeDeviceId, request, env);
    return {
      activeDeviceCount: activeDeviceIds.has(safeDeviceId) ? activeDeviceIds.size : (activeDeviceIds.size + 1),
      maxDevices,
    };
  }

  async function createAccessToken(env, user, extraClaims = {}) {
    const secret = deps.requireSecret(env, "JWT_SIGNING_SECRET");
    const exp = Math.floor(Date.now() / 1000) + (60 * 60);
    const effectivePlanCode = deps.normalizeRequestedPlan(
      deps.resolvePolicyPlanCode(user, env),
    ) || deps.PLAN_CODE_FREE;
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

  async function issueTileSessionToken(env, auth, requestedQualityMode, requestedResolveId = "", options = {}) {
    const safeQualityMode = deps.normalizeQualityMode(requestedQualityMode);
    const safeStoredPlanCode = deps.normalizeRequestedPlan(auth && auth.planCode);
    const safeQualityAccessPlanCode = deps.normalizeRequestedPlan(
      auth && (auth.qualityAccessPlanCode || auth.planCode),
    );
    const sessionId = String(
      options && (options.sessionId || options.session_id) || "",
    ).trim();
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
      credit_protocol: String(options && options.creditProtocol || "").trim(),
      credit_enforced: Boolean(options && options.creditEnforced),
      session_id: sessionId,
      auth_method: String(auth && auth.authMethod || "").trim(),
      device_id: String(auth && auth.deviceId || "").trim(),
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
    const cacheKey = `tile_session:${rawToken}`;
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
    const planCode = deps.normalizeRequestedPlan(payload && (payload.plan_code || payload.user_status) || "");
    const storedPlanCode = deps.normalizeRequestedPlan(
      payload && (payload.stored_plan_code || payload.storedPlanCode || planCode) || "",
    );
    const qualityAccessPlanCode = deps.normalizeRequestedPlan(
      payload && (payload.quality_access_plan_code || payload.qualityAccessPlanCode || planCode) || "",
    );
    const qualityMode = deps.normalizeQualityMode(payload && payload.quality_mode || "");
    const resolveId = normalizeResolveId(payload && payload.resolve_id || "");
    const creditProtocol = String(payload && (payload.credit_protocol || payload.creditProtocol) || "").trim();
    const claims = {
      userId,
      userEmail: String(payload && payload.email || "").trim(),
      planCode,
      storedPlanCode: storedPlanCode || planCode,
      qualityAccessPlanCode: qualityAccessPlanCode || planCode,
      qualityMode,
      resolveId,
      creditProtocol,
      creditEnforced: Boolean(payload && (payload.credit_enforced || payload.creditEnforced)),
      sessionId: String(payload && (payload.session_id || payload.sessionId) || "").trim(),
      authMethod: String(payload && payload.auth_method || "").trim(),
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
    const apiKeyId = String(metadata.api_key_id || metadata.apiKeyId || "").trim();
    const deviceId = deps.normalizeDeviceId(metadata.device_id || metadata.deviceId || "");
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
          api_key_id,
          device_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [refreshSessionId, userId, refreshHash, expiresAt, createdAt, authMethod || null, apiKeyId || null, deviceId || null],
    );
    return refreshToken;
  }

  function genericAuthStartResponse(env) {
    return deps.json(
      {
        ok: true,
        message: "Planetka access key activation link has been sent.",
      },
      200,
      env,
    );
  }

  return {
    createAccessToken,
    createRefreshSession,
    enforceApiKeyDeviceLimit,
    enforceApiKeyIssueDeviceLimit,
    findActiveApiKeyRecord,
    genericAuthStartResponse,
    isApiKeyUsableById,
    issueApiKeyForUser,
    issueTileSessionToken,
    normalizeResolveId,
    readTileSessionClaims,
  };
}
