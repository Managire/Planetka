export async function handleAdminServiceStatus(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const adminEmail = String(auth.install && auth.install.email || "");

  if (request.method === "GET") {
    const status = await deps.readServiceStatus(env);
    return deps.json({ ok: true, status }, 200, env);
  }

  if (request.method !== "POST") {
    return deps.json({ ok: false, error: "method_not_allowed" }, 405, env);
  }

  const body = await deps.parseJson(request);
  const action = String(body.action || "").trim().toLowerCase();
  const nextStatus = action === "clear"
    ? { enabled: false, message: "", url: "", severity: "info" }
    : {
      enabled: Boolean(body.enabled),
      message: body.message,
      url: body.url || body.details_url,
      severity: body.severity,
    };
  const status = await deps.writeServiceStatus(env, nextStatus, adminEmail);
  return deps.json({ ok: true, status }, 200, env);
}

