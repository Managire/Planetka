function renderAdminSessionStartPage() {
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Admin Session</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b1020; color: #e5e7eb; }
      .card { width: min(92vw, 640px); padding: 24px; border: 1px solid #1f2937; border-radius: 12px; background: #111827; }
      h1 { margin: 0 0 8px; font-size: 22px; }
      p { margin: 8px 0; color: #cbd5e1; }
      .muted { color: #9ca3af; font-size: 13px; }
      input { width: 100%; box-sizing: border-box; background: #0f172a; color: #e5e7eb; border: 1px solid #374151; border-radius: 8px; padding: 10px; margin-top: 10px; }
      button { margin-top: 10px; background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-weight: 600; }
      button[disabled] { opacity: 0.6; cursor: default; }
      .status { margin-top: 12px; font-size: 14px; }
      .ok { color: #86efac; }
      .err { color: #fca5a5; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Start Admin Session</h1>
      <p>Paste admin bearer token and click <strong>Open Analytics</strong>.</p>
      <p class="muted">Tip: one-click link format:<br><code>/admin/session/start#access_token=YOUR_TOKEN</code></p>
      <input id="token" type="password" autocomplete="off" placeholder="Paste bearer token" />
      <button id="startBtn" type="button">Open Analytics</button>
      <div id="status" class="status muted"></div>
    </main>
    <script>
      (function () {
        const tokenInput = document.getElementById("token");
        const startBtn = document.getElementById("startBtn");
        const statusEl = document.getElementById("status");

        function showStatus(message, type) {
          statusEl.textContent = message;
          statusEl.className = "status " + (type || "muted");
        }

        function parseHashToken() {
          const raw = String(window.location.hash || "").replace(/^#/, "");
          if (!raw) return "";
          const params = new URLSearchParams(raw);
          return String(params.get("access_token") || params.get("token") || "").trim();
        }

        async function startSession() {
          const token = String(tokenInput.value || "").trim();
          if (!token) {
            showStatus("Missing token.", "err");
            return;
          }
          startBtn.disabled = true;
          showStatus("Starting admin session...", "muted");
          try {
            const res = await fetch("/admin/session/start", {
              method: "POST",
              headers: { Authorization: "Bearer " + token },
              credentials: "same-origin",
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok || !payload.ok) {
              throw new Error(String((payload && payload.error) || ("HTTP " + res.status)));
            }
            showStatus("Session started. Redirecting...", "ok");
            window.location.href = "/admin/analytics";
          } catch (error) {
            showStatus("Failed to start session: " + String(error && error.message || error), "err");
            startBtn.disabled = false;
          }
        }

        startBtn.addEventListener("click", function () {
          startSession();
        });
        tokenInput.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            event.preventDefault();
            startSession();
          }
        });

        const hashToken = parseHashToken();
        if (hashToken) {
          tokenInput.value = hashToken;
          window.history.replaceState({}, document.title, "/admin/session/start");
          startSession();
        }
      })();
    </script>
  </body>
</html>`;
}

function renderAdminPasswordLoginPage(defaultAdminEmail, escapeHtml) {
  const defaultEmail = escapeHtml(defaultAdminEmail);
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Admin Login</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b1020; color: #e5e7eb; }
      .card { width: min(92vw, 520px); padding: 24px; border: 1px solid #1f2937; border-radius: 12px; background: #111827; }
      h1 { margin: 0 0 8px; font-size: 22px; }
      p { margin: 8px 0; color: #cbd5e1; }
      input { width: 100%; box-sizing: border-box; background: #0f172a; color: #e5e7eb; border: 1px solid #374151; border-radius: 8px; padding: 10px; margin-top: 10px; }
      button { margin-top: 10px; background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-weight: 600; }
      button[disabled] { opacity: 0.6; cursor: default; }
      .status { margin-top: 12px; font-size: 14px; color: #9ca3af; }
      .ok { color: #86efac; }
      .err { color: #fca5a5; }
      .muted { color: #9ca3af; font-size: 13px; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Admin Login</h1>
      <p>Enter password to open Planetka analytics dashboard.</p>
      <input id="adminEmail" type="email" autocomplete="username" value="${defaultEmail}" placeholder="Admin email" />
      <input id="password" type="password" autocomplete="current-password" placeholder="Password" />
      <button id="loginBtn" type="button">Open Analytics</button>
      <div id="status" class="status"></div>
      <p class="muted">Session stays active for about 1 hour on this browser.</p>
    </main>
    <script>
      (function () {
        const adminEmailInput = document.getElementById("adminEmail");
        const passwordInput = document.getElementById("password");
        const loginBtn = document.getElementById("loginBtn");
        const statusEl = document.getElementById("status");
        function showStatus(message, type) {
          statusEl.textContent = message;
          statusEl.className = "status " + (type || "");
        }
        async function login() {
          const adminEmail = String((adminEmailInput && adminEmailInput.value) || "").trim();
          const password = String(passwordInput.value || "");
          if (!password) {
            showStatus("Missing password.", "err");
            return;
          }
          loginBtn.disabled = true;
          showStatus("Signing in...");
          try {
            const res = await fetch("/admin/login", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "same-origin",
              body: JSON.stringify({ password, admin_email: adminEmail }),
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok || !payload.ok) {
              throw new Error(String((payload && payload.error) || ("HTTP " + res.status)));
            }
            showStatus("Success. Redirecting...", "ok");
            window.location.href = "/admin/analytics";
          } catch (error) {
            showStatus("Login failed: " + String(error && error.message || error), "err");
            loginBtn.disabled = false;
          }
        }
        loginBtn.addEventListener("click", function () { login(); });
        passwordInput.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            event.preventDefault();
            login();
          }
        });
      })();
    </script>
  </body>
</html>`;
}

export async function handleAdminSessionStartPage(request, env, deps) {
  void request;
  return deps.html(renderAdminSessionStartPage(), 200, env);
}

export async function handleAdminSessionStart(request, env, deps) {
  const authHeader = String(request.headers.get("Authorization") || "");
  if (!authHeader.startsWith("Bearer ")) {
    return deps.json({ ok: false, error: "missing_bearer_token" }, 401, env);
  }
  const token = authHeader.slice("Bearer ".length).trim();
  if (!token) {
    return deps.json({ ok: false, error: "missing_bearer_token" }, 401, env);
  }
  const auth = await deps.requireAuthenticatedUserContext(
    request,
    env,
    { requireAdmin: true, allowCookieToken: false, enforceApiKeyDevicePolicy: true },
  );
  if (auth.error) {
    return auth.error;
  }
  return deps.jsonWithHeaders(
    {
      ok: true,
      redirect: "/admin/analytics",
    },
    200,
    env,
    {
      "Set-Cookie": deps.buildAdminSessionCookie(token),
    },
  );
}

export async function handleAdminSessionLogout(request, env, deps) {
  void request;
  return new Response(null, {
    status: 302,
    headers: {
      Location: "/admin/login",
      "Set-Cookie": deps.buildAdminSessionClearCookie(),
      ...deps.corsHeaders(env),
    },
  });
}

export async function handleAdminLoginPage(request, env, deps) {
  void request;
  return deps.html(renderAdminPasswordLoginPage(deps.DEFAULT_ADMIN_LOGIN_EMAIL, deps.escapeHtml), 200, env);
}

export async function handleAdminPasswordLogin(request, env, deps) {
  const db = deps.requireDb(env);
  await deps.ensureRateLimitsTable(db);
  const clientIp = deps.requestClientIp(request);
  const rate = await deps.consumeRateLimitWindow(
    db,
    "admin_login_ip",
    clientIp,
    deps.parseRateLimitInteger(env.RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT, deps.DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT),
    deps.parseRateLimitInteger(
      env.RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS,
      deps.DEFAULT_RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS,
    ),
  );
  if (!rate.allowed) {
    return deps.rateLimitedResponse(
      env,
      "admin_login_rate_limited",
      "Too many admin login attempts. Please try again later.",
      rate.retryAfterSeconds,
    );
  }

  const body = await deps.parseJson(request);
  const requestedAdminEmail = deps.normalizeEmail(body.admin_email || "");
  const password = String(body.password || "");
  if (!password) {
    return deps.json({ ok: false, error: "missing_password" }, 400, env);
  }
  let valid = false;
  try {
    valid = await deps.verifyAdminDashboardPassword(env, password);
  } catch (error) {
    console.error(
      "planetka.admin.login.verify_failed",
      JSON.stringify({
        error: String(error && error.message || "admin_login_misconfigured"),
      }),
    );
    return deps.json({ ok: false, error: "admin_login_misconfigured" }, 500, env);
  }
  if (!valid) {
    await deps.trackThresholdAlertDb(
      db,
      "admin_login_invalid_spike",
      5,
      300,
      { scope: "ip", ip: clientIp },
    );
    return deps.json({ ok: false, error: "invalid_admin_password" }, 401, env);
  }

  const adminEmail = deps.resolveAdminLoginEmailFromBody(env, requestedAdminEmail);
  if (!adminEmail) {
    return deps.json({ ok: false, error: "admin_login_email_misconfigured" }, 500, env);
  }

  let user = await deps.upsertUserByEmail(
    db,
    adminEmail,
    deps.PLAN_CODE_PLANETKA_PRO,
    { proConfirmedAt: deps.nowIso() },
    env,
  );
  user = await deps.enforceUserPlanPolicy(db, user, null, env);
  if (!user || !deps.isAnalyticsAdmin(user, env)) {
    return deps.json({ ok: false, error: "admin_access_required" }, 403, env);
  }
  const accessToken = await deps.createAccessToken(
    env,
    user,
    null,
    {
      auth_method: "admin_password",
      admin_login: 1,
    },
  );
  return deps.jsonWithHeaders(
    {
      ok: true,
      email: String(user.email || ""),
      redirect: "/admin/analytics",
    },
    200,
    env,
    {
      "Set-Cookie": deps.buildAdminSessionCookie(accessToken),
    },
  );
}
