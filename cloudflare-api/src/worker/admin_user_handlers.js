async function resolveTargetInstall(db, body, deps) {
  const requestedInstallId = String(body && body.install_id || "").trim();
  const requestedEmail = deps.normalizeEmail(body && body.email || "");
  if (!requestedInstallId && !requestedEmail) {
    return { error: "missing_install_id_or_email", install: null };
  }
  let install = requestedInstallId ? await deps.findInstallById(db, requestedInstallId) : null;
  if (!install && requestedEmail) {
    install = await deps.findInstallByEmail(db, requestedEmail);
  }
  if (!install) {
    return { error: "cloud_install_not_found", install: null };
  }
  return { error: "", install };
}

const DEFAULT_INTERNAL_QA_RESET_EMAILS = [
  "qa@planetka.io",
  "tom.griger@gmail.com",
].join(",");

function parseQaResetEmailSet(env, deps) {
  return deps.parseCsvEmailSet(
    env.INTERNAL_QA_RESET_EMAILS,
    DEFAULT_INTERNAL_QA_RESET_EMAILS,
  );
}

function isAllowedQaResetEmail(email, env, deps) {
  const normalized = deps.normalizeEmail(email || "");
  if (!normalized) {
    return false;
  }
  return parseQaResetEmailSet(env, deps).has(normalized);
}

function resolveQaResetAccessStatus(email, requestedAccessStatus, existingInstall, deps) {
  const explicitAccessStatus = deps.normalizeRequestedAccessStatus(requestedAccessStatus || "");
  if (explicitAccessStatus) {
    return explicitAccessStatus;
  }
  const normalizedEmail = deps.normalizeEmail(email || "");
  if (normalizedEmail === "tom.griger@gmail.com") {
    return deps.ACCESS_STATUS_ACTIVE;
  }
  const existingAccessStatus = deps.normalizeRequestedAccessStatus(existingInstall && existingInstall.status || "");
  if (existingAccessStatus) {
    return existingAccessStatus;
  }
  return deps.ACCESS_STATUS_ACTIVE;
}

async function clearRateLimitBucket(db, scope, rawKey, deps) {
  const normalizedRawKey = String(rawKey || "").trim();
  if (!normalizedRawKey) {
    return 0;
  }
  const hashedKey = await deps.sha256Hex(`${scope}:${normalizedRawKey}`);
  const storageKey = `${scope}:${hashedKey}`;
  const result = await deps.dbRun(db, `DELETE FROM rate_limits WHERE key = ?`, [storageKey]);
  return deps.dbMetaChanges(result);
}

async function clearQaAuthRateLimits(db, request, deps) {
  await deps.ensureRateLimitsTable(db);
  const clientIp = deps.requestClientIp(request);
  const cleared = { auth_refresh_ip: 0, auth_anonymous_ip: 0 };
  if (clientIp) {
    cleared.auth_refresh_ip = await clearRateLimitBucket(db, "auth_refresh_ip", clientIp, deps);
    cleared.auth_anonymous_ip = await clearRateLimitBucket(db, "auth_anonymous_ip", clientIp, deps);
  }
  return cleared;
}

async function revokeRefreshSessions(db, installId, deps) {
  await deps.ensureRefreshSessionColumns(db);
  const result = await deps.dbRun(
    db,
    `
      UPDATE cloud_session_refresh_tokens
      SET revoked_at = ?
      WHERE install_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [deps.nowIso(), installId],
  );
  return deps.dbMetaChanges(result);
}

async function invalidateAdminAnalyticsSnapshots(env, deps) {
  try {
    await deps.invalidateAnalyticsSnapshots(env);
  } catch (error) {
    console.warn(
      "planetka.admin.analytics_snapshot_invalidate_failed",
      JSON.stringify({ error: String(error && error.message || "analytics_snapshot_invalidate_failed") }),
    );
  }
}

export async function handleAdminInstallBlock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, install: adminInstall } = auth;
  await deps.ensureRefreshSessionColumns(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetInstall(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "cloud_install_not_found" ? 404 : 400, env);
  }

  const targetInstallId = String(target.install.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.install.email || "");
  const now = deps.nowIso();
  await deps.dbRun(db, `UPDATE cloud_installs SET status = 'blocked' WHERE id = ?`, [targetInstallId]);
  const revokedSessions = await revokeRefreshSessions(db, targetInstallId, deps);
  console.log("admin.install_blocked", JSON.stringify({ install_id: targetInstallId, install_email: targetEmail, admin_email: deps.normalizeEmail(adminInstall && adminInstall.email || "") }));
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json({ ok: true, action: "block_install", install_id: targetInstallId, install_email: targetEmail, status: "blocked", revoked_sessions: revokedSessions, updated_at: now }, 200, env);
}

export async function handleAdminInstallUnblock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, install: adminInstall } = auth;
  await deps.ensureRefreshSessionColumns(db);
  await deps.ensureAdminHardBlocksTable(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetInstall(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "cloud_install_not_found" ? 404 : 400, env);
  }

  const targetInstallId = String(target.install.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.install.email || "");
  const targetStatus = deps.ACCESS_STATUS_ACTIVE;
  const now = deps.nowIso();
  await deps.dbRun(db, `UPDATE cloud_installs SET status = ? WHERE id = ?`, [targetStatus, targetInstallId]);
  const hardBlocksClearedResult = await deps.dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET active = 0
      WHERE active = 1
        AND (
          source_install_id = ?
          OR LOWER(COALESCE(source_install_email, '')) = ?
          OR LOWER(COALESCE(blocked_email, '')) = ?
        )
    `,
    [targetInstallId, targetEmail, targetEmail],
  );
  const revokedSessions = await revokeRefreshSessions(db, targetInstallId, deps);
  console.log("admin.install_unblocked", JSON.stringify({ install_id: targetInstallId, install_email: targetEmail, admin_email: deps.normalizeEmail(adminInstall && adminInstall.email || "") }));
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json({ ok: true, action: "unblock_install", install_id: targetInstallId, install_email: targetEmail, status: targetStatus, hard_blocks_cleared: deps.dbMetaChanges(hardBlocksClearedResult), revoked_sessions: revokedSessions, updated_at: now }, 200, env);
}

export async function handleAdminInstallHardBlock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, install: adminInstall } = auth;
  await deps.ensureRefreshSessionColumns(db);
  await deps.ensureAdminHardBlocksTable(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetInstall(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "cloud_install_not_found" ? 404 : 400, env);
  }

  const targetInstallId = String(target.install.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.install.email || "");
  const now = deps.nowIso();
  const blockedDeviceId = deps.normalizeDeviceId(String(body.blocked_device_id || body.device_id || ""));
  const blockedIp = String(body.blocked_ip || body.ip || deps.requestClientIp(request) || "").trim();
  const reason = String(body.reason || "manual_admin_hard_block").trim().slice(0, 160) || "manual_admin_hard_block";

  await deps.dbRun(db, `UPDATE cloud_installs SET status = 'blocked' WHERE id = ?`, [targetInstallId]);
  const revokedSessions = await revokeRefreshSessions(db, targetInstallId, deps);
  await deps.dbRun(
    db,
    `
      INSERT INTO admin_hard_blocks (
        id, blocked_email, blocked_device_id, blocked_ip, source_install_id,
        source_install_email, reason, created_by, created_at, active
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    `,
    [
      crypto.randomUUID(),
      targetEmail || null,
      blockedDeviceId || null,
      blockedIp || null,
      targetInstallId || null,
      targetEmail || null,
      reason,
      deps.normalizeEmail(adminInstall && adminInstall.email || "") || null,
      now,
    ],
  );
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json({ ok: true, action: "hard_block_install", install_id: targetInstallId, install_email: targetEmail, status: "blocked", blocked_device_id: blockedDeviceId || null, blocked_ip: blockedIp || null, revoked_sessions: revokedSessions, updated_at: now }, 200, env);
}

export async function handleAdminQaAuthReset(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, install: adminInstall } = auth;
  await deps.ensureRefreshSessionColumns(db);
  await deps.ensureAdminHardBlocksTable(db);
  await deps.ensureRateLimitsTable(db);

  const body = await deps.parseJson(request);
  const targetEmail = deps.normalizeEmail(body && body.email || "");
  if (!targetEmail || !targetEmail.includes("@")) {
    return deps.json({ ok: false, error: "invalid_email" }, 400, env);
  }
  if (!isAllowedQaResetEmail(targetEmail, env, deps)) {
    return deps.json({ ok: false, error: "qa_reset_not_allowed" }, 403, env);
  }

  const existingInstall = await deps.findInstallByEmail(db, targetEmail);
  const targetAccessStatus = resolveQaResetAccessStatus(targetEmail, body && body.access_status || "", existingInstall, deps);
  const now = deps.nowIso();
  let install = existingInstall;
  if (!install) {
    install = await deps.upsertInstallByEmail(db, targetEmail, targetAccessStatus, { signupSource: "admin_qa_reset" }, env);
  } else {
    await deps.dbRun(db, `UPDATE cloud_installs SET status = ? WHERE id = ?`, [targetAccessStatus, String(install.id || "").trim()]);
    install = { ...install, status: targetAccessStatus };
  }

  const installId = String(install && install.id || "").trim();
  if (!installId) {
    return deps.json({ ok: false, error: "cloud_install_not_found" }, 404, env);
  }

  const revokedSessions = await revokeRefreshSessions(db, installId, deps);
  const clearedHardBlocksResult = await deps.dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET active = 0
      WHERE active = 1
        AND (
          source_install_id = ?
          OR LOWER(COALESCE(source_install_email, '')) = ?
          OR LOWER(COALESCE(blocked_email, '')) = ?
        )
    `,
    [installId, targetEmail, targetEmail],
  );
  const clearedRateLimits = await clearQaAuthRateLimits(db, request, deps);
  console.log("admin.qa_auth_reset", JSON.stringify({ install_id: installId, install_email: targetEmail, access_status: targetAccessStatus, admin_email: deps.normalizeEmail(adminInstall && adminInstall.email || ""), revoked_sessions: revokedSessions, cleared_hard_blocks: deps.dbMetaChanges(clearedHardBlocksResult) }));
  await invalidateAdminAnalyticsSnapshots(env, deps);

  return deps.json({ ok: true, action: "qa_auth_reset", install_id: installId, install_email: targetEmail, access_status: targetAccessStatus, revoked_sessions: revokedSessions, cleared_hard_blocks: deps.dbMetaChanges(clearedHardBlocksResult), cleared_rate_limits: clearedRateLimits, updated_at: now }, 200, env);
}
