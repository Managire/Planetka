function resolveLegalDocumentConfig(path, env) {
  const normalized = String(path || "").trim().toLowerCase();
  if (normalized === "/legal/terms-of-service.pdf") {
    return {
      key: String(env.LEGAL_TERMS_KEY || "legal/terms-of-service.pdf").trim() || "legal/terms-of-service.pdf",
      fileName: "Planetka-Terms-of-Service.pdf",
      contentType: "application/pdf",
    };
  }
  if (normalized === "/legal/privacy-policy.pdf") {
    return {
      key: String(env.LEGAL_PRIVACY_KEY || "legal/privacy-policy.pdf").trim() || "legal/privacy-policy.pdf",
      fileName: "Planetka-Privacy-Policy.pdf",
      contentType: "application/pdf",
    };
  }
  if (normalized === "/legal/using-planetka-free-and-pro.txt") {
    return {
      key: String(env.LEGAL_USAGE_KEY || "legal/using-planetka-free-and-pro.txt").trim() || "legal/using-planetka-free-and-pro.txt",
      fileName: "Planetka-Free-and-Pro.txt",
      contentType: "text/plain; charset=utf-8",
    };
  }
  if (normalized === "/legal/attribution-for-user-renders.txt") {
    return {
      key: String(env.LEGAL_ATTRIBUTION_KEY || "legal/attribution-for-user-renders.txt").trim() || "legal/attribution-for-user-renders.txt",
      fileName: "Planetka-Attribution-for-User-Renders.txt",
      contentType: "text/plain; charset=utf-8",
    };
  }
  return null;
}

function sanitizeAttachmentFileName(value, fallback = "planetka_bug_report.json") {
  const raw = String(value || "").trim();
  const safe = raw.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
  if (!safe) {
    return fallback;
  }
  return safe.toLowerCase().endsWith(".json") ? safe : `${safe}.json`;
}

function sanitizeImageAttachmentFileName(value, fallback = "planetka_bug_screenshot.png") {
  const raw = String(value || "").trim();
  const safe = raw.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
  const candidate = safe || fallback;
  const lower = candidate.toLowerCase();
  if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".webp")) {
    return candidate;
  }
  return fallback;
}

function normalizeBugReportImageMime(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "image/png" || normalized === "image/jpeg" || normalized === "image/webp") {
    return normalized;
  }
  return "";
}

function base64DecodeToBytes(value) {
  const compact = String(value || "").replace(/\s+/g, "");
  if (!compact) {
    return new Uint8Array();
  }
  const binary = atob(compact);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index) & 0xff;
  }
  return bytes;
}

function normalizeAddonUpdateVersion(value, fallback) {
  const text = String(value || "").trim();
  if (!text) {
    return String(fallback || "").trim();
  }
  return text;
}

function parseAddonUpdateSha256(value) {
  const token = String(value || "").trim().toLowerCase();
  if (!token) {
    return "";
  }
  if (/^[a-f0-9]{64}$/.test(token)) {
    return token;
  }
  return "";
}

function parseVersionTuple(value) {
  const text = String(value || "").trim();
  if (!text) {
    return [];
  }
  return text.split(".").map((part) => {
    const match = String(part || "").trim().match(/^(\d+)/);
    return match ? Number.parseInt(match[1], 10) : 0;
  });
}

function compareVersions(left, right) {
  const a = parseVersionTuple(left);
  const b = parseVersionTuple(right);
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const av = Number.isFinite(a[index]) ? a[index] : 0;
    const bv = Number.isFinite(b[index]) ? b[index] : 0;
    if (av !== bv) {
      return av > bv ? 1 : -1;
    }
  }
  return 0;
}

function requestAddonUpdaterVersion(request) {
  const explicit = String(
    request.headers.get("X-Planetka-Addon-Version")
      || request.headers.get("X-Planetka-Updater-Version")
      || "",
  ).trim();
  if (explicit) {
    return explicit;
  }
  const userAgent = String(request.headers.get("User-Agent") || "").trim();
  const match = userAgent.match(/Planetka-Addon-Updater\/([0-9]+(?:\.[0-9]+)*(?:[-+._a-zA-Z0-9]*)?)/i);
  return match ? String(match[1] || "").trim() : "";
}

export async function handleLegalDocumentRequest(request, env, path, deps) {
  if (!env.PLANETKA_DATA) {
    return deps.json({ ok: false, error: "missing_r2_binding" }, 500, env);
  }
  const doc = resolveLegalDocumentConfig(path, env);
  if (!doc) {
    return deps.json({ ok: false, error: "not_found" }, 404, env);
  }
  const object = await env.PLANETKA_DATA.get(doc.key);
  if (!object) {
    return deps.json({ ok: false, error: "legal_document_not_found" }, 404, env);
  }
  const headers = new Headers({
    ...deps.corsHeaders(env),
    "Content-Type": doc.contentType || "application/octet-stream",
    "Content-Disposition": `inline; filename="${doc.fileName}"`,
    "Cache-Control": "public, max-age=300, s-maxage=86400",
  });
  if (Number.isFinite(Number(object.size))) {
    headers.set("Content-Length", String(Math.max(0, Number(object.size))));
  }
  if (object.httpEtag) {
    headers.set("ETag", String(object.httpEtag));
  }
  if (request.method === "HEAD") {
    return new Response(null, { status: 200, headers });
  }
  return new Response(object.body, { status: 200, headers });
}

export async function handleSupportBugReport(request, env, deps) {
  const auth = await deps.requireCloudSessionContext(
    request,
    env,
    { enforceApiKeyDevicePolicy: true },
  );
  if (auth.error) {
    return auth.error;
  }
  const install = auth.install || {};

  const body = await deps.parseJson(request);
  const reportJson = String(body.report_json || "").trim();
  if (!reportJson) {
    return deps.json({ ok: false, error: "missing_report_json" }, 400, env);
  }
  if (reportJson.length > 500000) {
    return deps.json({ ok: false, error: "report_json_too_large" }, 413, env);
  }
  try {
    JSON.parse(reportJson);
  } catch (_error) {
    return deps.json({ ok: false, error: "invalid_report_json" }, 400, env);
  }

  const reportFileName = sanitizeAttachmentFileName(body.report_filename, "planetka_bug_report.json");
  const issueWhat = String(body.issue_what_happened || "").trim();
  const issueSteps = String(body.issue_steps_to_reproduce || "").trim();
  const issueExpected = String(body.issue_expected_behavior || "").trim();
  const sourcePath = String(body.report_path || "").trim();
  const attachmentBase64 = String(body.attachment_base64 || "").trim();

  let imageAttachment = null;
  if (attachmentBase64) {
    const mime = normalizeBugReportImageMime(body.attachment_mime);
    if (!mime) {
      return deps.json({ ok: false, error: "invalid_attachment_mime" }, 400, env);
    }
    let imageBytes;
    try {
      imageBytes = base64DecodeToBytes(attachmentBase64);
    } catch (_error) {
      return deps.json({ ok: false, error: "invalid_attachment_base64" }, 400, env);
    }
    if (!imageBytes || imageBytes.length <= 0) {
      return deps.json({ ok: false, error: "empty_attachment" }, 400, env);
    }
    if (imageBytes.length > deps.BUG_REPORT_IMAGE_MAX_BYTES) {
      return deps.json({ ok: false, error: "attachment_too_large" }, 413, env);
    }
    imageAttachment = {
      filename: sanitizeImageAttachmentFileName(body.attachment_filename, "planetka_bug_screenshot.png"),
      contentType: mime,
      content: deps.base64EncodeBytes(imageBytes),
      sizeBytes: imageBytes.length,
    };
  }

  const apiKey = deps.requireSecret(env, "EMAIL_API_KEY");
  const from = String(env.EMAIL_FROM || "info@planetka.io").trim();
  const to = String(env.BUG_REPORT_EMAIL || env.SECURITY_ALERT_EMAIL || "info@planetka.io").trim() || "info@planetka.io";
  const sentAt = deps.nowIso();
  const reporterEmail = String(install.email || "").trim();

  const textBody = [
    "Planetka bug report submitted from Blender.",
    "",
    `reported_at_utc=${sentAt}`,
    `reporter_email=${reporterEmail || "unknown"}`,
    `reporter_install_id=${String(install.id || "")}`,
    `report_file_name=${reportFileName}`,
    `local_report_path=${sourcePath || "n/a"}`,
    "",
    "Issue description:",
    `- What happened: ${issueWhat || "(not provided)"}`,
    `- Steps to reproduce: ${issueSteps || "(not provided)"}`,
    `- Expected behavior: ${issueExpected || "(not provided)"}`,
    `- Screenshot attached: ${imageAttachment ? "yes" : "no"}`,
    ...(imageAttachment ? [`- Screenshot file: ${imageAttachment.filename} (${imageAttachment.sizeBytes} bytes)`] : []),
    "",
    "Attached: JSON debug report",
    ...(imageAttachment ? ["Attached: Screenshot/image"] : []),
  ].join("\n");

  const htmlBody = `
    <div style="font-family:Arial,sans-serif;line-height:1.5;color:#111827;">
      <h2 style="margin:0 0 12px 0;">Planetka Bug Report</h2>
      <p><strong>Reported at (UTC):</strong> ${deps.escapeHtml(sentAt)}<br/>
      <strong>Reporter email:</strong> ${deps.escapeHtml(reporterEmail || "unknown")}<br/>
      <strong>Install ID:</strong> ${deps.escapeHtml(String(install.id || ""))}<br/>
      <strong>Report file:</strong> ${deps.escapeHtml(reportFileName)}<br/>
      <strong>Local report path:</strong> ${deps.escapeHtml(sourcePath || "n/a")}</p>
      <h3 style="margin:16px 0 8px 0;">Issue Description</h3>
      <p><strong>What happened:</strong> ${deps.escapeHtml(issueWhat || "(not provided)")}<br/>
      <strong>Steps to reproduce:</strong> ${deps.escapeHtml(issueSteps || "(not provided)")}<br/>
      <strong>Expected behavior:</strong> ${deps.escapeHtml(issueExpected || "(not provided)")}<br/>
      <strong>Screenshot attached:</strong> ${imageAttachment ? "yes" : "no"}${imageAttachment ? `<br/><strong>Screenshot file:</strong> ${deps.escapeHtml(imageAttachment.filename)} (${imageAttachment.sizeBytes} bytes)` : ""}</p>
      <p>Attached: JSON debug report</p>
      ${imageAttachment ? "<p>Attached: Screenshot/image</p>" : ""}
    </div>
  `;

  const attachments = [
    {
      filename: reportFileName,
      content: deps.base64EncodeString(reportJson),
    },
  ];
  if (imageAttachment) {
    attachments.push({
      filename: imageAttachment.filename,
      content: imageAttachment.content,
      contentType: imageAttachment.contentType,
    });
  }

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject: `Planetka Bug Report - ${reporterEmail || "unknown"}`,
      text: textBody,
      html: htmlBody,
      attachments,
    }),
  });

  if (!response.ok) {
    const resendBody = await response.text();
    return deps.json(
      {
        ok: false,
        error: `bug_report_email_failed_${response.status}`,
        detail: String(resendBody || "").slice(0, 500),
      },
      502,
      env,
    );
  }

  return deps.json(
    {
      ok: true,
      sent: true,
      reporter_email: reporterEmail,
      report_file_name: reportFileName,
      image_attachment: Boolean(imageAttachment),
    },
    200,
    env,
  );
}

export async function handleAddonUpdateManifest(request, env, deps) {
  const localVersion = normalizeAddonUpdateVersion(
    env.ADDON_UPDATE_VERSION || env.EXTENSION_VERSION || env.ADDON_VERSION,
    deps.DEFAULT_ADDON_UPDATE_MANIFEST_VERSION,
  );
  const channel = String(env.ADDON_UPDATE_CHANNEL || deps.DEFAULT_ADDON_UPDATE_CHANNEL).trim().toLowerCase() || deps.DEFAULT_ADDON_UPDATE_CHANNEL;
  const downloadUrl = String(env.ADDON_UPDATE_DOWNLOAD_URL || "").trim();
  const sha256 = parseAddonUpdateSha256(env.ADDON_UPDATE_SHA256);
  const releaseNotesUrl = String(env.ADDON_UPDATE_RELEASE_NOTES_URL || deps.DEFAULT_ADDON_UPDATE_RELEASE_NOTES_URL).trim();
  const minBlenderVersion = String(env.ADDON_UPDATE_MIN_BLENDER || "4.5.7").trim();
  const publishedAt = String(env.ADDON_UPDATE_PUBLISHED_AT || "").trim() || deps.nowIso();
  const mandatory = String(env.ADDON_UPDATE_MANDATORY || "").trim().toLowerCase() === "true";
  const minimumUpdaterVersion = String(env.ADDON_UPDATE_MIN_UPDATER_VERSION || "0.9.1").trim();
  const clientUpdaterVersion = requestAddonUpdaterVersion(request);
  const updaterAllowed = !clientUpdaterVersion
    || !minimumUpdaterVersion
    || compareVersions(clientUpdaterVersion, minimumUpdaterVersion) >= 0;
  const maxAge = Math.max(
    30,
    deps.parseNonNegativeInteger(env.ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS, deps.DEFAULT_ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS),
  );
  const effectiveDownloadUrl = updaterAllowed ? downloadUrl : "";
  const effectiveSha256 = updaterAllowed ? sha256 : "";

  const payload = {
    ok: true,
    addon_id: deps.ADDON_ID,
    channel,
    version: localVersion,
    download_url: effectiveDownloadUrl,
    sha256: effectiveSha256,
    release_notes_url: releaseNotesUrl,
    min_blender_version: minBlenderVersion,
    mandatory,
    published_at: publishedAt,
    available: Boolean(effectiveDownloadUrl),
    minimum_updater_version: minimumUpdaterVersion,
  };
  if (!updaterAllowed) {
    payload.update_blocked_reason = "updater_too_old";
  }

  if (request.method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: {
        ...deps.corsHeaders(env),
        "Cache-Control": `public, max-age=${maxAge}`,
        "Vary": "User-Agent, X-Planetka-Addon-Version, X-Planetka-Updater-Version",
      },
    });
  }

  return deps.jsonWithHeaders(payload, 200, env, {
    "Cache-Control": `public, max-age=${maxAge}`,
    "Vary": "User-Agent, X-Planetka-Addon-Version, X-Planetka-Updater-Version",
  });
}

export async function handleHealth(env, deps) {
  return deps.json(
    {
      ok: true,
      service: "planetka-api",
      api_base_url: env.API_BASE_URL || "https://api.planetka.io",
      login_url: env.LOGIN_URL || "https://www.planetka.io/login",
      db_bound: Boolean(env.DB),
      r2_bound: Boolean(env.PLANETKA_DATA),
    },
    200,
    env,
  );
}
