export function createAuthSessionRouteHandlers(deps) {
  const strictStoredTier = (value) => {
    const normalized = typeof deps.normalizeTierCodeStrict === "function"
      ? deps.normalizeTierCodeStrict(value)
      : "";
    if (!normalized) {
      throw new Error("invalid_user_status");
    }
    return normalized;
  };

  async function handleAuthRefresh(request, env) {
    const db = deps.requireDb(env);
    await deps.ensureRateLimitsTable(db);
    const refreshEventBase = {
      client_ip: deps.requestClientIp(request),
      cf_country: deps.requestCountry(request),
      cf_ray: String(request.headers.get("CF-Ray") || "").trim(),
    };
    const refreshIpRate = await deps.consumeRateLimitWindow(
      db,
      "auth_refresh_ip",
      refreshEventBase.client_ip,
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_REFRESH_IP_LIMIT,
        deps.DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_LIMIT,
      ),
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS,
        deps.DEFAULT_RATE_LIMIT_AUTH_REFRESH_IP_WINDOW_SECONDS,
      ),
    );
    if (!refreshIpRate.allowed) {
      return deps.rateLimitedResponse(
        env,
        "auth_refresh_ip_rate_limited",
        "Too many refresh requests. Please try again shortly.",
        refreshIpRate.retryAfterSeconds,
      );
    }
    const recordRefreshEvent = async ({
      outcome = "error",
      errorCode = "",
      httpStatus = 0,
      userId = "",
      userEmail = "",
      sessionRow = null,
      details = null,
    } = {}) => {
      await deps.logAuthRefreshEvent(db, {
        ...refreshEventBase,
        user_id: userId,
        user_email: userEmail,
        auth_method: sessionRow ? String(sessionRow.auth_method || "").trim() : "",
        api_key_id: sessionRow ? String(sessionRow.api_key_id || "").trim() : "",
        device_id: sessionRow ? String(sessionRow.device_id || "").trim() : "",
        outcome,
        error_code: errorCode,
        http_status: httpStatus,
        details,
      });
    };
    const errorResponse = async (errorCode, httpStatus, sessionRow = null, details = null) => {
      await recordRefreshEvent({
        outcome: "error",
        errorCode,
        httpStatus,
        userId: sessionRow ? String(sessionRow.user_id || "").trim() : "",
        userEmail: sessionRow ? deps.normalizeEmail(sessionRow.email || "") : "",
        sessionRow,
        details,
      });
      return deps.json({ ok: false, error: errorCode }, httpStatus, env);
    };
    const body = await deps.parseJson(request);
    const refreshToken = String(body.refresh_token || "").trim();
    if (!refreshToken) {
      return errorResponse("missing_refresh_token", 400, null, {
        has_body: Boolean(body && Object.keys(body).length),
      });
    }

    const refreshHash = await deps.sha256Hex(refreshToken);
    const session = await deps.dbGet(
      db,
      `
        SELECT
          rs.id,
          rs.user_id,
          rs.expires_at,
          rs.revoked_at,
          rs.auth_method,
          rs.api_key_id,
          rs.device_id,
          u.email,
          u.status
        FROM refresh_sessions rs
        JOIN users u ON u.id = rs.user_id
        WHERE rs.refresh_token_hash = ?
        LIMIT 1
      `,
      [refreshHash],
    );
    if (!session) {
      return errorResponse("invalid_refresh_token", 400);
    }
    if (deps.isBlockedStatus(session.status)) {
      await recordRefreshEvent({
        outcome: "error",
        errorCode: "account_blocked",
        httpStatus: 403,
        userId: String(session.user_id || "").trim(),
        userEmail: deps.normalizeEmail(session.email || ""),
        sessionRow: session,
      });
      return deps.blockedAccountResponse(env);
    }
    if (session.revoked_at) {
      return errorResponse("refresh_token_revoked", 400, session);
    }
    if (Date.parse(session.expires_at) < Date.now()) {
      return errorResponse("refresh_token_expired", 400, session);
    }
    if (
      String(session.auth_method || "").trim().toLowerCase() === "api_key"
      && String(session.api_key_id || "").trim()
    ) {
      const keyUsable = await deps.isApiKeyUsableById(db, session.api_key_id, session.user_id);
      if (!keyUsable) {
        return errorResponse("api_key_revoked", 401, session);
      }
    }

    let strictSessionStatus = "";
    try {
      strictSessionStatus = strictStoredTier(session.status);
    } catch (_error) {
      return errorResponse("invalid_user_status", 500, session);
    }
    let user = {
      id: session.user_id,
      email: session.email,
      status: strictSessionStatus,
    };
    user = await deps.enforceUserPlanPolicy(db, user, env);

    await deps.dbRun(
      db,
      `UPDATE refresh_sessions SET revoked_at = ? WHERE id = ?`,
      [deps.nowIso(), session.id],
    );
    const accountState = await deps.buildAccountState(db, user, env);
    const accessToken = await deps.createAccessToken(
      env,
      user,
      {
        plan_code: String(accountState.planCode || ""),
        user_status: String(accountState.planCode || ""),
        account_tier: String(accountState.accountTier || accountState.storedAccountTier || ""),
        stored_plan_code: String(accountState.storedPlanCode || ""),
        stored_account_tier: String(accountState.storedAccountTier || ""),
        quality_access_plan_code: String(accountState.qualityAccessPlanCode || ""),
        auth_method: String(session.auth_method || "").trim(),
        api_key_id: String(session.api_key_id || "").trim(),
        device_id: String(session.device_id || "").trim(),
      },
    );
    const nextRefreshToken = await deps.createRefreshSession(
      db,
      session.user_id,
      "",
      {
        auth_method: String(session.auth_method || "").trim(),
        api_key_id: String(session.api_key_id || "").trim(),
        device_id: String(session.device_id || "").trim(),
      },
    );
    await recordRefreshEvent({
      outcome: "success",
      errorCode: "",
      httpStatus: 200,
      userId: String(user.id || "").trim(),
      userEmail: deps.normalizeEmail(user.email || ""),
      sessionRow: session,
    });

    return deps.json(
      {
        ok: true,
        access_token: accessToken,
        refresh_token: nextRefreshToken,
        email: user.email,
        ...deps.serializeAccountState(accountState),
      },
      200,
      env,
    );
  }

  async function handleAuthLogout(request, env) {
    const db = deps.requireDb(env);
    await deps.ensureRefreshSessionColumns(db);
    await deps.ensureApiKeyTables(db);
    const body = await deps.parseJson(request);

    const refreshToken = String(body.refresh_token || "").trim();
    let deviceId = deps.normalizeDeviceId(
      body.device_id || request.headers.get("X-Planetka-Device-Id") || "",
    );
    let userId = "";
    let revokedSessions = 0;
    let clearedDeviceActivity = 0;

    if (refreshToken) {
      const refreshHash = await deps.sha256Hex(refreshToken);
      const session = await deps.dbGet(
        db,
        `
          SELECT id, user_id, device_id
          FROM refresh_sessions
          WHERE refresh_token_hash = ?
          LIMIT 1
        `,
        [refreshHash],
      );
      if (session) {
        userId = String(session.user_id || "").trim();
        if (!deviceId) {
          deviceId = deps.normalizeDeviceId(session.device_id || "");
        }
      }
    }

    if (!userId) {
      try {
        const access = await deps.readBearerUser(request, env);
        if (access && access.sub) {
          userId = String(access.sub || "").trim();
        }
        if (!deviceId && access) {
          deviceId = deps.normalizeDeviceId(access.device_id || "");
        }
      } catch (_error) {
        // Best-effort logout: silently allow local logout even when token is missing/expired.
      }
    }

    if (userId) {
      const revokedAt = deps.nowIso();
      let revokeSql = `
        UPDATE refresh_sessions
        SET revoked_at = ?
        WHERE user_id = ?
          AND (revoked_at IS NULL OR revoked_at = '')
      `;
      const revokeBindings = [revokedAt, userId];
      if (deviceId) {
        revokeSql += " AND device_id = ?";
        revokeBindings.push(deviceId);
      }
      const revokeResult = await deps.dbRun(db, revokeSql, revokeBindings);
      revokedSessions = deps.dbMetaChanges(revokeResult);
    }

    if (userId && deviceId) {
      const clearResult = await deps.dbRun(
        db,
        `
          DELETE FROM api_key_device_activity
          WHERE user_id = ?
            AND device_id = ?
        `,
        [userId, deviceId],
      );
      clearedDeviceActivity = deps.dbMetaChanges(clearResult);
    }

    return deps.json(
      {
        ok: true,
        revoked_sessions: revokedSessions,
        cleared_device_activity: clearedDeviceActivity,
      },
      200,
      env,
    );
  }

  async function handleMe(request, env) {
    const auth = await deps.requireAuthenticatedUserContext(
      request,
      env,
      { enforceApiKeyDevicePolicy: true },
    );
    if (auth.error) {
      return auth.error;
    }
    const { db, user } = auth;
    const accountState = await deps.buildAccountState(db, user, env);

    return deps.json(
      {
        ok: true,
        email: user.email,
        user_status: String(accountState.planCode || ""),
        ...deps.serializeAccountState(accountState),
      },
      200,
      env,
    );
  }

  return {
    handleAuthRefresh,
    handleAuthLogout,
    handleMe,
  };
}
