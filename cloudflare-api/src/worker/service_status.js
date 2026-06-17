const DEFAULT_SERVICE_STATUS_KEY = "Admin/service_status.json";
const SERVICE_STATUS_SEVERITIES = new Set(["info", "warning", "error", "maintenance"]);

function serviceStatusKey(env) {
  return String(env && env.PLANETKA_SERVICE_STATUS_KEY || DEFAULT_SERVICE_STATUS_KEY).trim() || DEFAULT_SERVICE_STATUS_KEY;
}

function cleanString(value, maxLength) {
  return String(value || "").trim().slice(0, maxLength);
}

function cleanUrl(value) {
  const text = cleanString(value, 500);
  if (!text) return "";
  try {
    const parsed = new URL(text);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") {
      return parsed.toString();
    }
  } catch (_error) {
    return "";
  }
  return "";
}

export function sanitizeServiceStatus(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  const message = cleanString(source.message, 160);
  const severityRaw = cleanString(source.severity, 32).toLowerCase();
  const severity = SERVICE_STATUS_SEVERITIES.has(severityRaw) ? severityRaw : "info";
  const enabled = Boolean(source.enabled) && Boolean(message);
  return {
    enabled,
    message: enabled ? message : "",
    url: enabled ? cleanUrl(source.url || source.details_url) : "",
    severity,
    updated_at: cleanString(source.updated_at, 40),
    updated_by: cleanString(source.updated_by, 120),
  };
}

export function publicServiceStatus(value = {}) {
  const status = sanitizeServiceStatus(value);
  if (!status.enabled || !status.message) {
    return null;
  }
  return {
    active: true,
    message: status.message,
    url: status.url,
    severity: status.severity,
    updated_at: status.updated_at,
  };
}

export async function readServiceStatus(env) {
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return sanitizeServiceStatus();
  }
  try {
    const object = await bucket.get(serviceStatusKey(env));
    if (!object) {
      return sanitizeServiceStatus();
    }
    const payload = await object.json();
    return sanitizeServiceStatus(payload);
  } catch (error) {
    console.error("planetka.service_status.read_failed", String(error && error.message || "read_failed"));
    return sanitizeServiceStatus();
  }
}

export async function writeServiceStatus(env, value = {}, updatedBy = "") {
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.put !== "function") {
    throw new Error("r2_not_bound");
  }
  const status = sanitizeServiceStatus({
    ...value,
    updated_at: new Date().toISOString(),
    updated_by: updatedBy,
  });
  await bucket.put(serviceStatusKey(env), JSON.stringify(status, null, 2), {
    httpMetadata: {
      contentType: "application/json; charset=utf-8",
    },
  });
  return status;
}

