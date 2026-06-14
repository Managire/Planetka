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

export async function readBearerInstall(request, env, deps) {
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

export async function requireCloudSessionContext(request, env, options = {}, deps) {
  const db = deps.requireDb(env);
  const allowCookieToken = deps.parseBooleanFlag(options.allowCookieToken);
  const requireAdmin = deps.parseBooleanFlag(options.requireAdmin);
  const lightweightAccessClaims = deps.parseBooleanFlag(options.lightweightAccessClaims);
  const canUseLightweightAuthCache = (
    lightweightAccessClaims
    && !requireAdmin
    && !allowCookieToken
  );
  const bearerToken = readBearerToken(request);
  const requestIpScope = typeof deps.requestClientIpScope === "function"
    ? String(deps.requestClientIpScope(request) || "").trim()
    : "";
  const authCacheKey = canUseLightweightAuthCache && bearerToken
    ? `lightweight_auth:${bearerToken}:${requestIpScope}`
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
      access = await readBearerInstall(request, env, deps);
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
  const installEdition = typeof deps.normalizeRequestedAccessTier === "function"
    ? deps.normalizeRequestedAccessTier(access.install_edition || access.access_tier || "")
    : (() => {
      const value = String(access.install_edition || access.access_tier || "").trim().toLowerCase();
      if (value === "pro") return "pro";
      if (value === "private") return "private";
      return "free";
    })();
  const tokenIpScope = String(access.client_ip_scope || access.clientIpScope || "").trim();
  if (authMethod === "anonymous" && tokenIpScope && requestIpScope && tokenIpScope !== requestIpScope) {
    return { error: deps.json({ ok: false, error: "anonymous_ip_scope_changed" }, 401, env) };
  }
  const deviceId = deps.normalizeDeviceId(
    access.device_id || request.headers.get("X-Planetka-Device-Id") || "",
  );
  const tokenAccessStatusRaw = String(
    access.access_status_code || access.install_status || access.access_status || access.accessStatus || access.installStatus || "",
  ).trim();
  const tokenAccessStatus = tokenAccessStatusRaw && typeof deps.normalizeAccessStatusStrict === "function"
    ? deps.normalizeAccessStatusStrict(tokenAccessStatusRaw)
    : "";
  const tokenQualityAccessAccessStatusRaw = String(
    access.quality_access_status_code || access.qualityAccessStatus || tokenAccessStatusRaw || "",
  ).trim();
  const tokenQualityAccessAccessStatus = tokenQualityAccessAccessStatusRaw && typeof deps.normalizeAccessStatusStrict === "function"
    ? deps.normalizeAccessStatusStrict(tokenQualityAccessAccessStatusRaw)
    : tokenAccessStatus;
  if (
    lightweightAccessClaims
    && !requireAdmin
    && tokenAccessStatus
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
        install: {
          id: String(access.sub || "").trim(),
          email: String(access.email || "").trim(),
          status: tokenAccessStatus,
        },
        access,
        accessStatus: tokenAccessStatus,
        qualityAccessStatus: tokenQualityAccessAccessStatus || tokenAccessStatus,
        authMethod,
        installEdition,
        deviceId,
        tokenSource,
    };
  }

  let install = await deps.findInstallById(db, access.sub);
  if (!install) {
    return { error: deps.json({ ok: false, error: "cloud_install_not_found" }, 404, env) };
  }
  if (deps.isBlockedStatus(install.status)) {
    return { error: deps.blockedCloudSessionResponse(env) };
  }
  install = await deps.enforceInstallAccessStatusPolicy(db, install, env);
  if (!install) {
    return { error: deps.json({ ok: false, error: "cloud_install_not_found" }, 404, env) };
  }
  const qualityAccess = await deps.resolveInstallQualityAccessState(db, install, env);
  const accessStatus = qualityAccess.storedAccessStatus;
  const qualityAccessStatus = qualityAccess.qualityAccessStatus;
  if (requireAdmin && !deps.isAnalyticsAdmin(install, env)) {
    return { error: deps.json({ ok: false, error: "admin_access_required" }, 403, env) };
  }
  return {
    db,
    install,
    access,
    accessStatus,
    qualityAccessStatus,
    authMethod,
    installEdition,
    deviceId,
    tokenSource,
  };
}

export async function requireAnalyticsAdmin(request, env, deps) {
  const auth = await requireCloudSessionContext(
    request,
    env,
    { requireAdmin: true, allowCookieToken: true },
    deps,
  );
  if (auth && auth.error) {
    return auth;
  }
  if (!deps.isPrimaryAnalyticsAdmin(auth && auth.install, env)) {
    return { error: deps.json({ ok: false, error: "primary_admin_required" }, 403, env) };
  }
  return auth;
}
