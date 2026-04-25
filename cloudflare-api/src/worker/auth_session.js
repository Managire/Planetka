export function readCookieValue(request, cookieName) {
  const safeName = String(cookieName || "").trim();
  if (!safeName) {
    return "";
  }
  const cookieHeader = String(request.headers.get("Cookie") || "");
  if (!cookieHeader) {
    return "";
  }
  const parts = cookieHeader.split(";");
  for (const part of parts) {
    const [nameRaw, ...rest] = String(part || "").split("=");
    const name = String(nameRaw || "").trim();
    if (name !== safeName) {
      continue;
    }
    return decodeURIComponent(String(rest.join("=") || "").trim());
  }
  return "";
}

export function buildAdminSessionCookie(token) {
  const safe = encodeURIComponent(String(token || "").trim());
  return `planetka_admin_token=${safe}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=3600`;
}

export function buildAdminSessionClearCookie() {
  return "planetka_admin_token=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0";
}

export function readBearerToken(request) {
  const header = String(request.headers.get("Authorization") || "");
  if (!header.startsWith("Bearer ")) {
    return "";
  }
  const token = header.slice("Bearer ".length).trim();
  if (!token) {
    return "";
  }
  return token;
}

export async function readBearerUser(request, env, deps) {
  const token = readBearerToken(request);
  if (!token) {
    return null;
  }
  const secret = deps.requireSecret(env, "JWT_SIGNING_SECRET");
  const payload = await deps.verifyJwt(token, secret);
  if (payload.type !== "access" || !payload.sub) {
    throw new Error("invalid_access_token");
  }
  return payload;
}

export async function requireAuthenticatedUserContext(request, env, options = {}, deps) {
  const db = deps.requireDb(env);
  const allowCookieToken = deps.parseBooleanFlag(options.allowCookieToken);
  const requireAdmin = deps.parseBooleanFlag(options.requireAdmin);
  const enforceApiKeyDevicePolicy = options.enforceApiKeyDevicePolicy !== false;
  const lightweightAccessClaims = deps.parseBooleanFlag(options.lightweightAccessClaims);
  const canUseLightweightAuthCache = (
    lightweightAccessClaims
    && !requireAdmin
    && !allowCookieToken
    && !enforceApiKeyDevicePolicy
  );
  const bearerToken = readBearerToken(request);
  const authCacheKey = canUseLightweightAuthCache && bearerToken
    ? `lightweight_auth:${bearerToken}`
    : "";

  let access = null;
  let tokenSource = "";
  let bearerError = "";
  const cachedAuth = authCacheKey ? deps.authContextCacheGet(authCacheKey, env) : null;
  if (cachedAuth) {
    access = cachedAuth.access;
    tokenSource = "bearer_cache";
  }
  try {
    if (!access) {
      access = await readBearerUser(request, env, deps);
      if (access) {
        tokenSource = "bearer";
      }
    }
  } catch (error) {
    bearerError = String(error && error.message || "invalid_access_token");
  }
  if (!access && allowCookieToken) {
    const cookieToken = String(readCookieValue(request, "planetka_admin_token") || "").trim();
    if (cookieToken) {
      try {
        const secret = deps.requireSecret(env, "JWT_SIGNING_SECRET");
        const payload = await deps.verifyJwt(cookieToken, secret);
        if (payload.type === "access" && payload.sub) {
          access = payload;
          tokenSource = "admin_cookie";
        } else {
          bearerError = "invalid_access_token";
        }
      } catch (error) {
        bearerError = String(error && error.message || "invalid_access_token");
      }
    }
  }
  if (!access) {
    if (bearerError) {
      return { error: deps.json({ ok: false, error: bearerError }, 401, env) };
    }
    return { error: deps.json({ ok: false, error: "missing_bearer_token" }, 401, env) };
  }

  const authMethod = String(access.auth_method || "").trim().toLowerCase();
  const apiKeyId = String(access.api_key_id || "").trim();
  const deviceId = deps.normalizeDeviceId(
    access.device_id || request.headers.get("X-Planetka-Device-Id") || "",
  );
  const tokenPlanRaw = String(
    access.plan_code || access.user_status || access.plan || access.planCode || access.userStatus || "",
  ).trim();
  const tokenPlanCode = tokenPlanRaw ? deps.normalizeRequestedPlan(tokenPlanRaw) : "";
  if (
    lightweightAccessClaims
    && !requireAdmin
    && tokenPlanCode
  ) {
    if (authCacheKey && tokenSource !== "bearer_cache") {
      deps.authContextCacheSet(
        authCacheKey,
        {
          access,
        },
        env,
      );
    }
    return {
      db,
      user: {
        id: String(access.sub || "").trim(),
        email: String(access.email || "").trim(),
        status: tokenPlanCode,
      },
      access,
      planCode: tokenPlanCode,
      authMethod,
      apiKeyId,
      deviceId,
      devicePolicy: null,
      tokenSource,
    };
  }

  let user = await deps.findUserById(db, access.sub);
  if (!user) {
    return { error: deps.json({ ok: false, error: "user_not_found" }, 404, env) };
  }
  if (deps.isBlockedStatus(user.status)) {
    return { error: deps.blockedAccountResponse(env) };
  }
  user = await deps.enforceUserPlanPolicy(db, user, null, env);
  if (!user) {
    return { error: deps.json({ ok: false, error: "user_not_found" }, 404, env) };
  }
  const planCode = deps.resolvePlanCode(user, null, env);
  let devicePolicy = null;
  if (enforceApiKeyDevicePolicy && authMethod === "api_key" && apiKeyId) {
    const keyUsable = await deps.isApiKeyUsableById(db, apiKeyId, String(user.id || ""));
    if (!keyUsable) {
      return { error: deps.json({ ok: false, error: "api_key_revoked", message: "API key is no longer active." }, 401, env) };
    }
    try {
      devicePolicy = await deps.enforceApiKeyDeviceLimit(
        db,
        apiKeyId,
        String(user.id || ""),
        String(user.email || ""),
        planCode,
        deviceId,
        request,
        env,
      );
    } catch (error) {
      const code = String(error && error.message || "device_limit_exceeded");
      const statusCode = code === "missing_device_id" ? 400 : 429;
      const message = code === "missing_device_id"
        ? "Missing device identifier for API key session."
        : "This Planetka account can be active on one computer at a time.";
      return { error: deps.json({ ok: false, error: code, message }, statusCode, env) };
    }
  }
  if (requireAdmin && !deps.isAnalyticsAdmin(user, env)) {
    return { error: deps.json({ ok: false, error: "admin_access_required" }, 403, env) };
  }
  return {
    db,
    user,
    access,
    planCode,
    authMethod,
    apiKeyId,
    deviceId,
    devicePolicy,
    tokenSource,
  };
}

export async function requireAnalyticsAdmin(request, env, deps) {
  const auth = await requireAuthenticatedUserContext(
    request,
    env,
    { requireAdmin: true, allowCookieToken: true, enforceApiKeyDevicePolicy: false },
    deps,
  );
  if (auth && auth.error) {
    return auth;
  }
  if (!deps.isPrimaryAnalyticsAdmin(auth && auth.user, env)) {
    return { error: deps.json({ ok: false, error: "primary_admin_required" }, 403, env) };
  }
  return auth;
}
