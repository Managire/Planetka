export function createAuthSessionRouteHandlers(deps) {
  const normalizeEdition = (value) => {
    if (typeof deps.normalizeRequestedAccessTier === "function") {
      return deps.normalizeRequestedAccessTier(value);
    }
    return String(value || "").trim().toLowerCase() === "pro" ? "pro" : "free";
  };

  const strictStoredTier = (value) => {
    const normalized = typeof deps.normalizeAccessStatusStrict === "function"
      ? deps.normalizeAccessStatusStrict(value)
      : "";
    if (!normalized) {
      throw new Error("invalid_install_status");
    }
    return normalized;
  };

  async function handleAuthRefresh(request, env) {
    const db = deps.requireDb(env);
    await deps.ensureRateLimitsTable(db);
    if (typeof deps.ensureRefreshSessionColumns === "function") {
      await deps.ensureRefreshSessionColumns(db);
    }
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
      installId = "",
      installEmail = "",
      sessionRow = null,
      details = null,
    } = {}) => {
      await deps.logAuthRefreshEvent(db, {
        ...refreshEventBase,
        install_id: installId,
        install_email: installEmail,
        auth_method: sessionRow ? String(sessionRow.auth_method || "").trim() : "",
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
        installId: sessionRow ? String(sessionRow.install_id || "").trim() : "",
        installEmail: sessionRow ? deps.normalizeEmail(sessionRow.email || "") : "",
        sessionRow,
        details,
      });
      return deps.json({ ok: false, error: errorCode }, httpStatus, env);
    };
    const body = await deps.parseJson(request);
    const refreshToken = String(body.refresh_token || "").trim();
    const hasRequestEdition = Boolean(String(body.install_edition || body.edition || body.access_tier || "").trim());
    const requestInstallEdition = hasRequestEdition
      ? (
        typeof deps.resolveVerifiedInstallEdition === "function"
          ? await deps.resolveVerifiedInstallEdition(body, env)
          : normalizeEdition(body.install_edition || body.edition || body.access_tier || "")
      )
      : "";
    const requestEditionSignature = String(body.edition_signature || body.package_signature || "").trim().slice(0, 256);
    const requestDeviceId = deps.normalizeDeviceId(
      body.device_id || request.headers.get("X-Planetka-Device-Id") || "",
    );
    const requestIpScope = typeof deps.requestClientIpScope === "function"
      ? String(deps.requestClientIpScope(request) || "").trim()
      : "";
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
          rs.install_edition,
          rs.edition_signature,
          rs.device_id,
          rs.client_ip_scope,
          u.email,
          u.status
        FROM cloud_session_refresh_tokens rs
        JOIN cloud_installs u ON u.id = rs.user_id
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
        errorCode: "session_blocked",
        httpStatus: 403,
        installId: String(session.user_id || "").trim(),
        installEmail: deps.normalizeEmail(session.email || ""),
        sessionRow: session,
      });
      return deps.blockedCloudSessionResponse(env);
    }
    if (session.revoked_at) {
      return errorResponse("refresh_token_revoked", 400, session);
    }
    if (Date.parse(session.expires_at) < Date.now()) {
      return errorResponse("refresh_token_expired", 400, session);
    }
    const sessionAuthMethod = String(session.auth_method || "").trim().toLowerCase();
    const installEdition = normalizeEdition(requestInstallEdition || session.install_edition || "pro");
    const editionSignature = requestEditionSignature || String(session.edition_signature || "").trim().slice(0, 256);
    const sessionDeviceId = deps.normalizeDeviceId(session.device_id || "");
    if (sessionAuthMethod === "anonymous" && sessionDeviceId && (!requestDeviceId || sessionDeviceId !== requestDeviceId)) {
      return errorResponse("device_id_mismatch", 401, session, {
        request_device_id: requestDeviceId,
      });
    }


    let strictSessionStatus = "";
    try {
      strictSessionStatus = strictStoredTier(session.status);
    } catch (_error) {
      return errorResponse("invalid_install_status", 500, session);
    }
    let install = {
      id: session.user_id,
      email: session.email,
      status: strictSessionStatus,
    };
    install = await deps.enforceInstallAccessStatusPolicy(db, install, env);

    await deps.dbRun(
      db,
      `UPDATE cloud_session_refresh_tokens SET revoked_at = ? WHERE id = ?`,
      [deps.nowIso(), session.id],
    );
    const accessToken = await deps.createAccessToken(
      env,
      install,
      {
        auth_method: String(session.auth_method || "").trim(),
        access_tier: installEdition,
        install_edition: installEdition,
        device_id: String(session.device_id || "").trim(),
        client_ip_scope: requestIpScope || String(session.client_ip_scope || "").trim(),
      },
    );
    const nextRefreshToken = await deps.createRefreshSession(
      db,
      session.user_id,
      "",
      {
        auth_method: String(session.auth_method || "").trim(),
        install_edition: installEdition,
        edition_signature: editionSignature,
        device_id: String(session.device_id || "").trim(),
        client_ip_scope: requestIpScope || String(session.client_ip_scope || "").trim(),
      },
    );
    await recordRefreshEvent({
      outcome: "success",
      errorCode: "",
      httpStatus: 200,
      installId: String(install.id || "").trim(),
      installEmail: deps.normalizeEmail(install.email || ""),
      sessionRow: session,
      details: requestIpScope && String(session.client_ip_scope || "").trim() && requestIpScope !== String(session.client_ip_scope || "").trim()
        ? {
          previous_ip_scope: String(session.client_ip_scope || "").trim(),
          current_ip_scope: requestIpScope,
        }
        : null,
    });

    return deps.json(
      {
        ok: true,
        access_token: accessToken,
        refresh_token: nextRefreshToken,
        planetka_install_id: String(install.id || ""),
        install_id: String(install.id || ""),
        email: typeof deps.isSyntheticAnonymousEmail === "function" && deps.isSyntheticAnonymousEmail(install.email)
          ? ""
          : install.email,
        install_edition: installEdition,
        install_edition_label: typeof deps.accessTierDisplayName === "function"
          ? deps.accessTierDisplayName(installEdition)
          : (installEdition === "pro" ? "Pro" : "Free"),
        access_tier: installEdition,
        access_tier_label: typeof deps.accessTierDisplayName === "function"
          ? deps.accessTierDisplayName(installEdition)
          : (installEdition === "pro" ? "Pro" : "Free"),
      },
      200,
      env,
    );
  }

  async function handleAuthLogout(request, env) {
    const db = deps.requireDb(env);
    await deps.ensureRefreshSessionColumns(db);
    const body = await deps.parseJson(request);

    const refreshToken = String(body.refresh_token || "").trim();
    let deviceId = deps.normalizeDeviceId(
      body.device_id || request.headers.get("X-Planetka-Device-Id") || "",
    );
    let installId = "";
    let revokedSessions = 0;

    if (refreshToken) {
      const refreshHash = await deps.sha256Hex(refreshToken);
      const session = await deps.dbGet(
        db,
        `
          SELECT id, user_id, device_id
          FROM cloud_session_refresh_tokens
          WHERE refresh_token_hash = ?
          LIMIT 1
        `,
        [refreshHash],
      );
      if (session) {
        installId = String(session.user_id || "").trim();
        if (!deviceId) {
          deviceId = deps.normalizeDeviceId(session.device_id || "");
        }
      }
    }

    if (!installId) {
      try {
        const access = await deps.readBearerInstall(request, env);
        if (access && access.sub) {
          installId = String(access.sub || "").trim();
        }
        if (!deviceId && access) {
          deviceId = deps.normalizeDeviceId(access.device_id || "");
        }
      } catch (_error) {
        // Best-effort logout: silently allow local logout even when token is missing/expired.
      }
    }

    if (installId) {
      const revokedAt = deps.nowIso();
      let revokeSql = `
        UPDATE cloud_session_refresh_tokens
        SET revoked_at = ?
        WHERE user_id = ?
          AND (revoked_at IS NULL OR revoked_at = '')
      `;
      const revokeBindings = [revokedAt, installId];
      if (deviceId) {
        revokeSql += " AND device_id = ?";
        revokeBindings.push(deviceId);
      }
      const revokeResult = await deps.dbRun(db, revokeSql, revokeBindings);
      revokedSessions = deps.dbMetaChanges(revokeResult);
    }


    return deps.json(
      {
        ok: true,
        revoked_sessions: revokedSessions,
      },
      200,
      env,
    );
  }

  async function handleMe(request, env) {
    const auth = await deps.requireCloudSessionContext(
      request,
      env,
      {},
    );
    if (auth.error) {
      return auth.error;
    }
    const { install } = auth;
    const installEdition = normalizeEdition(auth && auth.access && (auth.access.install_edition || auth.access.access_tier) || auth.installEdition || "pro");
    const installEditionLabel = typeof deps.accessTierDisplayName === "function"
      ? deps.accessTierDisplayName(installEdition)
      : (installEdition === "pro" ? "Pro" : "Free");

    return deps.json(
      {
        ok: true,
        planetka_install_id: String(install.id || ""),
        install_id: String(install.id || ""),
        email: typeof deps.isSyntheticAnonymousEmail === "function" && deps.isSyntheticAnonymousEmail(install.email)
          ? ""
          : install.email,
        install_edition: installEdition,
        install_edition_label: installEditionLabel,
        access_tier: installEdition,
        access_tier_label: installEditionLabel,
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
