export function createAuthApiKeyHandlers(deps) {
  const NEWSLETTER_CONSENT_TEXT = "Opt in to receive Planetka updates and offers by email. Email addresses are not shared with third parties.";
  const NEWSLETTER_CONSENT_VERSION = "2026-05-13-updates-offers";

  const strictStoredTier = (value) => {
    const normalized = typeof deps.normalizeTierCodeStrict === "function"
      ? deps.normalizeTierCodeStrict(value)
      : "";
    if (!normalized) {
      throw new Error("invalid_user_status");
    }
    return normalized;
  };

  async function handleApiKeyRequest(request, env) {
    const db = deps.requireDb(env);
    await deps.ensureApiKeyTables(db);
    await deps.ensureRateLimitsTable(db);
    const body = await deps.parseJson(request);
    const email = deps.normalizeEmail(body.email);
    const requestDeviceId = deps.normalizeDeviceId(body.device_id || "");
    const acceptTerms = deps.parseBooleanFlag(body.accept_terms);
    const acceptPrivacy = deps.parseBooleanFlag(body.accept_privacy);
    const optInNews = deps.parseBooleanFlag(body.opt_in_news);
    const requestedPlan = deps.PLAN_CODE_FREE;
    const honeypot = String(body.website || "").trim();
    const submittedAtMs = deps.parseNonNegativeInteger(body.submitted_at_ms, 0);
    const minFormAgeMs = Math.max(
      0,
      Math.floor(
        deps.parsePositiveNumber(
          env.API_KEY_REQUEST_MIN_AGE_SECONDS,
          deps.DEFAULT_API_KEY_REQUEST_MIN_AGE_SECONDS,
        ) * 1000,
      ),
    );
    if (honeypot) {
      return deps.genericAuthStartResponse(env);
    }
    if (submittedAtMs > 0 && submittedAtMs < minFormAgeMs) {
      return deps.genericAuthStartResponse(env);
    }
    if (!email || !email.includes("@")) {
      return deps.json({ ok: false, error: "invalid_email" }, 400, env);
    }
    if (!acceptTerms || !acceptPrivacy) {
      return deps.json({ ok: false, error: "terms_consent_required" }, 400, env);
    }

    const clientIp = deps.requestClientIp(request);
    const hardBlockedByRequest = await deps.findActiveHardBlock(
      db,
      {
        email,
        device_id: requestDeviceId,
        ip: clientIp,
      },
    );
    if (hardBlockedByRequest) {
      return deps.blockedAccountResponse(env, "This Planetka account is blocked. Contact info@planetka.io.");
    }
    const authStartIpRate = await deps.consumeRateLimitWindow(
      db,
      "api_key_request_ip",
      clientIp,
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_START_IP_LIMIT,
        deps.DEFAULT_RATE_LIMIT_AUTH_START_IP_LIMIT,
      ),
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS,
        deps.DEFAULT_RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS,
      ),
    );
    if (!authStartIpRate.allowed) {
      return deps.rateLimitedResponse(
        env,
        "api_key_request_ip_rate_limited",
        "Too many requests. Please try again shortly.",
        authStartIpRate.retryAfterSeconds,
      );
    }
    const authStartEmailRate = await deps.consumeRateLimitWindow(
      db,
      "api_key_request_email",
      email,
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_START_EMAIL_LIMIT,
        deps.DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_LIMIT,
      ),
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS,
        deps.DEFAULT_RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS,
      ),
    );
    if (!authStartEmailRate.allowed) {
      return deps.rateLimitedResponse(
        env,
        "api_key_request_email_rate_limited",
        "Too many requests for this email. Please try again later.",
        authStartEmailRate.retryAfterSeconds,
      );
    }

    let existingUser = await deps.findUserByEmail(db, email);
    if (existingUser && !deps.isBlockedStatus(existingUser.status)) {
      existingUser = await deps.enforceUserPlanPolicy(db, existingUser, env);
      try {
        await deps.enforceApiKeyIssueDeviceLimit(
          db,
          String(existingUser.id || "").trim(),
          String(existingUser.email || "").trim(),
          strictStoredTier(existingUser && existingUser.status),
          requestDeviceId,
          env,
        );
      } catch (error) {
        const code = String(error && error.message || "device_limit_exceeded");
        if (code === "device_limit_exceeded") {
          return deps.json(
            {
              ok: false,
              error: "device_limit_exceeded",
              message: "This Planetka account can be active on one computer at a time.",
            },
            429,
            env,
          );
        }
        throw error;
      }
    }

    const legalVersion = String(
      env.TERMS_VERSION || env.LEGAL_VERSION || deps.DEFAULT_LEGAL_VERSION,
    ).trim() || deps.DEFAULT_LEGAL_VERSION;
    const privacyVersion = String(
      env.PRIVACY_VERSION || env.LEGAL_VERSION || deps.DEFAULT_LEGAL_VERSION,
    ).trim() || deps.DEFAULT_LEGAL_VERSION;
    const acceptedAt = deps.nowIso();
    await deps.upsertUserByEmail(
      db,
      email,
      requestedPlan,
      {
        termsAcceptedAt: acceptedAt,
        privacyAcceptedAt: acceptedAt,
        termsVersion: legalVersion,
        privacyVersion,
        signupSource: "api_key_request",
      },
      env,
    );
    if (optInNews) {
      await deps.recordNewsletterOptIn(db, email, "api_key_request", {
        consentText: NEWSLETTER_CONSENT_TEXT,
        consentVersion: NEWSLETTER_CONSENT_VERSION,
      });
    }

    const token = deps.randomToken(36);
    const tokenHash = await deps.sha256Hex(token);
    await deps.dbRun(
      db,
      `
        INSERT INTO api_key_requests (
          id,
          email,
          requested_plan,
          token_hash,
          expires_at,
          accept_terms,
          accept_privacy,
          opt_in_news,
          submitted_at_ms,
          request_ip,
          request_device_id,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        crypto.randomUUID(),
        email,
        requestedPlan,
        tokenHash,
        deps.addMinutesIso(30),
        acceptTerms ? 1 : 0,
        acceptPrivacy ? 1 : 0,
        optInNews ? 1 : 0,
        submittedAtMs,
        clientIp,
        requestDeviceId || null,
        deps.nowIso(),
      ],
    );
    await deps.sendApiKeyActivationEmail(env, email, token);
    return deps.json(
      {
        ok: true,
        message: "If the email is valid, a Planetka API key activation link has been sent.",
      },
      200,
      env,
    );
  }

  async function activateApiKeyFromToken(db, env, rawToken) {
    await deps.ensureApiKeyTables(db);
    const token = String(rawToken || "").trim();
    if (!token) {
      throw new Error("missing_token");
    }
    const tokenHash = await deps.sha256Hex(token);
    const now = deps.nowIso();
    const requestRow = await deps.dbGet(
      db,
      `
        UPDATE api_key_requests
        SET used_at = ?
        WHERE token_hash = ?
          AND used_at IS NULL
          AND expires_at >= ?
        RETURNING
          id,
          email,
          requested_plan,
          request_ip,
          request_device_id,
          opt_in_news
      `,
      [
        now,
        tokenHash,
        now,
      ],
    );
    if (!requestRow) {
      throw new Error("invalid_or_expired_token");
    }

    const email = deps.normalizeEmail(requestRow.email);
    let user = await deps.upsertUserByEmail(
      db,
      email,
      deps.PLAN_CODE_FREE,
      {},
      env,
    );
    user = await deps.enforceUserPlanPolicy(db, user, env);
    const storedPlanCode = strictStoredTier(user && user.status);

    const issued = await deps.issueApiKeyForUser(
      db,
      env,
      user,
      storedPlanCode,
      {},
    );

    await deps.sendApiKeyIssuedEmail(env, email, issued.apiKey, issued.planCode, issued.expiresAt);
    return {
      email,
      apiKey: issued.apiKey,
      planCode: issued.planCode,
      expiresAt: issued.expiresAt,
    };
  }

  async function handleApiKeyActivate(request, env) {
    const db = deps.requireDb(env);
    const body = await deps.parseJson(request);
    try {
      const activated = await activateApiKeyFromToken(db, env, body.token);
      return deps.json(
        {
          ok: true,
          email: activated.email,
          api_key: activated.apiKey,
          plan_code: activated.planCode,
          expires_at: activated.expiresAt,
        },
        200,
        env,
      );
    } catch (error) {
      const publicCode = deps.publicErrorCode(
        error,
        "activation_failed",
        new Set(["missing_token", "invalid_or_expired_token"]),
      );
      return deps.json(
        { ok: false, error: publicCode },
        publicCode === "activation_failed" ? 500 : 400,
        env,
      );
    }
  }

  async function handleApiKeyExchange(request, env) {
    const db = deps.requireDb(env);
    await deps.ensureRateLimitsTable(db);
    const body = await deps.parseJson(request);
    const apiKey = String(body.api_key || "").trim();
    const deviceId = deps.normalizeDeviceId(body.device_id || "");
    const clientIp = deps.requestClientIp(request);
    const exchangeIpRate = await deps.consumeRateLimitWindow(
      db,
      "api_key_exchange_ip",
      clientIp,
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_EXCHANGE_IP_LIMIT,
        deps.DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_LIMIT,
      ),
      deps.parseRateLimitInteger(
        env.RATE_LIMIT_AUTH_EXCHANGE_IP_WINDOW_SECONDS,
        deps.DEFAULT_RATE_LIMIT_AUTH_EXCHANGE_IP_WINDOW_SECONDS,
      ),
    );
    if (!exchangeIpRate.allowed) {
      return deps.rateLimitedResponse(
        env,
        "api_key_exchange_ip_rate_limited",
        "Too many sign-in attempts. Please try again shortly.",
        exchangeIpRate.retryAfterSeconds,
      );
    }
    if (!deps.isValidApiKey(apiKey)) {
      return deps.json({ ok: false, error: "invalid_api_key" }, 400, env);
    }
    if (!deviceId) {
      return deps.json({ ok: false, error: "missing_device_id" }, 400, env);
    }

    let record = await deps.findActiveApiKeyRecord(db, apiKey);
    if (!record) {
      return deps.json({ ok: false, error: "invalid_api_key" }, 401, env);
    }
    if (String(record.api_key_status || "").trim().toLowerCase() !== "active") {
      return deps.json({ ok: false, error: "api_key_revoked" }, 401, env);
    }
    if (deps.isBlockedStatus(record.status)) {
      return deps.blockedAccountResponse(env);
    }
    const hardBlockedByExchange = await deps.findActiveHardBlock(
      db,
      {
        email: String(record && record.email || ""),
        device_id: deviceId,
        ip: clientIp,
      },
    );
    if (hardBlockedByExchange) {
      return deps.blockedAccountResponse(env, "This Planetka account is blocked. Contact info@planetka.io.");
    }

    let user = {
      id: record.id,
      email: record.email,
      status: strictStoredTier(record.status),
    };
    user = await deps.enforceUserPlanPolicy(db, user, env);
    const storedPlanCode = strictStoredTier(user && user.status);
    if (storedPlanCode === deps.PLAN_CODE_FREE) {
      const freePolicy = await deps.enforceSingleActiveFreeApiKey(
        db,
        String(user.id || ""),
        String(record.api_key_id || ""),
      );
      if (!freePolicy.allowed) {
        return deps.json(
          {
            ok: false,
            error: "api_key_revoked",
            message: "This API key has been replaced. Request a new API key.",
          },
          401,
          env,
        );
      }
    }
    try {
      await deps.enforceApiKeyDeviceLimit(
        db,
        String(record.api_key_id || ""),
        String(user.id || ""),
        String(user.email || ""),
        storedPlanCode,
        deviceId,
        request,
        env,
      );
    } catch (error) {
      const code = String(error && error.message || "device_limit_exceeded");
      if (code === "missing_device_id") {
        return deps.json({ ok: false, error: "missing_device_id" }, 400, env);
      }
      if (code !== "device_limit_exceeded") {
        throw error;
      }
      return deps.json(
        {
          ok: false,
          error: "device_limit_exceeded",
          message: "This Planetka account can be active on one computer at a time.",
        },
        429,
        env,
      );
    }

    const now = deps.nowIso();
    await deps.dbRun(db, `UPDATE users SET last_login_at = ? WHERE id = ?`, [now, user.id]);
    await deps.dbRun(db, `UPDATE api_keys SET last_used_at = ? WHERE id = ?`, [now, record.api_key_id]);

    const accountState = await deps.buildAccountState(db, user, env);
    const refreshExpiresAt = deps.addDaysIso(7);
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
        api_key_id: String(record.api_key_id || ""),
        device_id: deviceId,
        auth_method: "api_key",
      },
    );
    const refreshToken = await deps.createRefreshSession(
      db,
      user.id,
      refreshExpiresAt,
      {
        auth_method: "api_key",
        api_key_id: String(record.api_key_id || ""),
        device_id: deviceId,
      },
    );
    return deps.json(
      {
        ok: true,
        email: user.email,
        access_token: accessToken,
        refresh_token: refreshToken,
        api_key_mask: deps.maskApiKey(apiKey),
        ...deps.serializeAccountState(accountState),
      },
      200,
      env,
    );
  }

  return {
    activateApiKeyFromToken,
    handleApiKeyActivate,
    handleApiKeyExchange,
    handleApiKeyRequest,
  };
}
