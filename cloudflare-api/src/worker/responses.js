export function corsHeaders(env = {}) {
  return {
    "Access-Control-Allow-Origin": env.APP_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Planetka-Device-Id, X-Planetka-Addon-Version, X-Planetka-Resolve-Id, X-Planetka-Quality-Mode, X-Planetka-Tile-Token",
  };
}

export function json(data, status = 200, env = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(env),
    },
  });
}

export function html(markup, status = 200, env = {}) {
  return new Response(markup, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
      Pragma: "no-cache",
      ...corsHeaders(env),
    },
  });
}

export function jsonWithHeaders(data, status = 200, env = {}, extraHeaders = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(env),
      ...extraHeaders,
    },
  });
}

export function publicErrorCode(error, fallbackCode, allowedCodes = null) {
  const code = String(error && error.message || fallbackCode).trim() || String(fallbackCode || "").trim() || "internal_error";
  if (allowedCodes instanceof Set && allowedCodes.size > 0) {
    return allowedCodes.has(code) ? code : String(fallbackCode || "internal_error");
  }
  return String(fallbackCode || "internal_error");
}

export function publicErrorMessage(fallbackMessage) {
  return String(fallbackMessage || "Request failed. Please try again.");
}
