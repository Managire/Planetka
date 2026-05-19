const API_KEY_PAGE_CSS = `:root{color-scheme:light dark;--bg1:#000;--bg2:#000;--card:rgba(8,15,29,.82);--line:rgba(148,163,184,.2);--field:rgba(15,23,42,.85);--field-line:rgba(148,163,184,.35);--text:#e5edf7;--muted:#cbd5e1;--subtle:#94a3b8;--link:#93c5fd;--button:#1d4ed8;--button-text:#fff;--pre:#0f172a;--pre-text:#f8fafc;--status-muted:#cbd5e1;--status-ok:#86efac;--status-error:#fca5a5;--shadow:0 20px 60px rgba(0,0,0,.35)}
@media (prefers-color-scheme:light){:root{--bg1:#fff;--bg2:#fff;--card:#fff;--line:#d8d8d8;--field:#fff;--field-line:#d8d8d8;--text:#1f252d;--muted:#4b5563;--subtle:#667085;--link:#1d4ed8;--button:#1d4ed8;--button-text:#fff;--pre:#fff;--pre-text:#1f252d;--status-muted:#667085;--status-ok:#247a3e;--status-error:#b42318;--shadow:0 20px 60px rgba(20,25,32,.10)}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(180deg,var(--bg1) 0%,var(--bg2) 100%);font-family:Inter,system-ui,sans-serif;color:var(--text)}
.card{width:min(92vw,560px);padding:28px;border-radius:18px;background:var(--card);border:1px solid var(--line);box-shadow:var(--shadow)}
h1{margin:0 0 12px;font-size:30px}p{margin:0 0 16px;color:var(--muted);line-height:1.5}label{display:block;margin:0 0 8px;color:var(--muted);font-size:14px}
input[type="email"],input[type="text"]{width:100%;box-sizing:border-box;padding:14px 16px;border-radius:10px;border:1px solid var(--field-line);background:var(--field);color:var(--pre-text);font-size:16px;margin-bottom:14px}
.checkbox{display:flex;gap:8px;align-items:flex-start;margin:10px 0;font-size:14px;color:var(--muted)}.checkbox input{margin-top:3px}.checkbox a,a{color:var(--link);text-decoration:underline}
button{margin-top:14px;width:100%;border:none;border-radius:12px;padding:13px 16px;background:var(--button);color:var(--button-text);font-size:16px;font-weight:600;cursor:pointer}button:disabled{opacity:.6;cursor:wait}
.help{margin-top:12px;font-size:13px;color:var(--subtle)}.hidden{display:none!important}.status{margin-top:14px;color:var(--status-muted)}.status.success{color:var(--status-ok)}.status.error{color:var(--status-error)}
pre{margin:10px 0 12px;padding:12px;border-radius:10px;background:var(--pre);border:1px solid var(--line);color:var(--pre-text);overflow:auto}.muted{color:var(--subtle);font-size:13px}`;

function renderApiKeyRequestPage(env, deps, message = "", requestedPlan = "") {
  const termsUrl = String(env.TERMS_URL || deps.DEFAULT_TERMS_URL).trim() || deps.DEFAULT_TERMS_URL;
  const privacyUrl = String(env.PRIVACY_URL || deps.DEFAULT_PRIVACY_URL).trim() || deps.DEFAULT_PRIVACY_URL;
  const contactUrl = deps.normalizeContactUrl(env.CONTACT_URL || deps.DEFAULT_CONTACT_URL);
  const safeMessage = String(message || "").trim();
  const messageMarkup = safeMessage
    ? `<p id="status" class="status success">${deps.escapeHtml(safeMessage)}</p>`
    : `<p id="status" class="status"></p>`;
  void requestedPlan;
  const safePlan = deps.PLAN_CODE_PROFESSIONAL || deps.PLAN_CODE_FREE;
  const subTitle = "Request account access to connect Blender and access Planetka-hosted data.";
  return deps.html(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Account Access</title>
    <style>${API_KEY_PAGE_CSS}</style>
  </head>
  <body>
    <main class="card">
      <h1>Request Account Access</h1>
      <p>${deps.escapeHtml(subTitle)}</p>
      <form id="form">
        <label for="email">Email</label>
        <input id="email" type="email" placeholder="you@example.com" required />
        <div class="checkbox">
          <input id="terms" type="checkbox" required />
          <label for="terms">I agree to the <a href="${termsUrl}" target="_blank" rel="noopener noreferrer">Terms and Conditions</a> and <a href="${privacyUrl}" target="_blank" rel="noopener noreferrer">Privacy Policy</a>.</label>
        </div>
        <div class="checkbox">
          <input id="news" type="checkbox" />
          <label for="news">Opt in to receive Planetka updates and offers by email. Email addresses are not shared with third parties.</label>
        </div>
        <input id="website" class="hidden" type="text" autocomplete="off" tabindex="-1" />
        <button id="submit" type="submit">Request Account Access</button>
      </form>
      ${messageMarkup}
      <p class="help">Problem connecting? <a href="${contactUrl}" target="_blank" rel="noopener noreferrer">Contact Me</a></p>
    </main>
    <script>
      const startedAt = Date.now();
      const form = document.getElementById("form");
      const status = document.getElementById("status");
      const submit = document.getElementById("submit");
      function errorMessageFromCode(code, fallbackMessage) {
        const normalized = String(code || "").trim().toLowerCase();
        if (normalized === "invalid_email") {
          return "Invalid email address. Please check the format (for example: name@example.com).";
        }
        if (normalized === "terms_consent_required") {
          return "Please accept Terms and Privacy to continue.";
        }
        if (normalized === "api_key_request_ip_rate_limited") {
          return "Too many requests from this network. Please try again shortly.";
        }
        if (normalized === "api_key_request_email_rate_limited") {
          return "Too many requests for this email. Please try again later.";
        }
        if (normalized === "device_limit_exceeded") {
          return String(fallbackMessage || "This account is already active on another computer.");
        }
        if (normalized === "blocked_account") {
          return String(fallbackMessage || "This account is blocked. Contact support.");
        }
        return String(fallbackMessage || "Request failed. Please try again.");
      }
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        status.style.color = "var(--status-muted)";
        status.textContent = "Sending...";
        try {
          const payload = {
            email: String(document.getElementById("email").value || "").trim(),
            accept_terms: document.getElementById("terms").checked,
            accept_privacy: document.getElementById("terms").checked,
            opt_in_news: document.getElementById("news").checked,
            website: String(document.getElementById("website").value || ""),
            submitted_at_ms: Date.now() - startedAt,
            requested_plan: "${safePlan}",
          };
          const response = await fetch("/auth/api-key/request", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await response.json();
          if (!response.ok || !data.ok) {
            const errorCode = String((data && data.error) || ("http_" + response.status));
            const errorMessage = errorMessageFromCode(errorCode, data && data.message);
            throw new Error(String(errorMessage || "Request failed."));
          }
          status.style.color = "var(--status-ok)";
          status.textContent = "Check your email for the activation link.";
        } catch (error) {
          status.style.color = "var(--status-error)";
          status.textContent = String(error && error.message || "Request failed. Please try again.");
          console.error("planetka api-key request failed", error);
        } finally {
          submit.disabled = false;
        }
      });
    </script>
  </body>
</html>`, 200, env);
}

function renderApiKeyActivatedPage(env, deps, data = {}) {
  const contactUrl = deps.normalizeContactUrl(env.CONTACT_URL || deps.DEFAULT_CONTACT_URL);
  const key = String(data.apiKey || "").trim();
  const keyMask = key ? deps.maskApiKey(key) : "";
  const email = String(data.email || "").trim();
  const planCode = deps.normalizeRequestedPlan(data.planCode || deps.PLAN_CODE_PROFESSIONAL || deps.PLAN_CODE_FREE);
  const planLabel = deps.planDisplayName(planCode);
  const accessSummary = deps.planAccessSummary(planCode);
  return deps.html(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Planetka Account Access Ready</title>
    <style>${API_KEY_PAGE_CSS}</style>
  </head>
  <body>
    <main class="card">
      <h1>Access key generated</h1>
      <p>Email: <strong>${deps.escapeHtml(email || "unknown")}</strong></p>
      <p>Access: <strong>${deps.escapeHtml(planLabel)}</strong></p>
      <p>${deps.escapeHtml(accessSummary)}</p>
      <pre id="apiKey">${deps.escapeHtml(key)}</pre>
      <button id="copyBtn" type="button">Copy access key</button>
      <p class="muted" id="copyStatus">Key mask: ${deps.escapeHtml(keyMask)}</p>
      <p>Paste this access key in Blender: Planetka &rarr; Account.</p>
      <p>Problem connecting? <a href="${contactUrl}" target="_blank" rel="noopener noreferrer">Contact Me</a></p>
    </main>
    <script>
      const btn = document.getElementById("copyBtn");
      const status = document.getElementById("copyStatus");
      btn.addEventListener("click", async () => {
        const text = document.getElementById("apiKey").textContent || "";
        try {
          await navigator.clipboard.writeText(text);
          status.textContent = "Copied to clipboard.";
          status.style.color = "var(--status-ok)";
        } catch (error) {
          status.textContent = "Copy failed. Select and copy manually.";
          status.style.color = "var(--status-error)";
        }
      });
    </script>
  </body>
</html>`, 200, env);
}

export function handleApiKeyPage(request, env, deps) {
  if (request.method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: {
        ...deps.corsHeaders(env),
        "Content-Type": "text/html; charset=utf-8",
      },
    });
  }
  return renderApiKeyRequestPage(env, deps, "", deps.PLAN_CODE_PROFESSIONAL || deps.PLAN_CODE_FREE);
}

export async function handleApiKeyActivatePage(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return renderApiKeyRequestPage(env, deps, "Missing activation token.");
  }
  const db = deps.requireDb(env);
  try {
    const activated = await deps.activateApiKeyFromToken(db, env, token);
    return renderApiKeyActivatedPage(env, deps, activated);
  } catch (_error) {
    return renderApiKeyRequestPage(env, deps, "Activation link is invalid or expired. Request a new key.");
  }
}
