async function resolveTargetUser(db, body, deps) {
  const requestedUserId = String(body && body.user_id || "").trim();
  const requestedEmail = deps.normalizeEmail(body && body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return { error: "missing_user_id_or_email", user: null };
  }
  let user = requestedUserId ? await deps.findUserById(db, requestedUserId) : null;
  if (!user && requestedEmail) {
    user = await deps.findUserByEmail(db, requestedEmail);
  }
  if (!user) {
    return { error: "user_not_found", user: null };
  }
  return { error: "", user };
}

const DEFAULT_INTERNAL_QA_RESET_EMAILS = [
  "personal@planetka.io",
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

function resolveQaResetPlanCode(email, requestedPlanCode, existingUser, deps) {
  const explicitPlan = deps.normalizeRequestedPlan(requestedPlanCode || "");
  if ([deps.PLAN_CODE_PERSONAL, deps.PLAN_CODE_COMMERCIAL].includes(explicitPlan)) {
    return explicitPlan;
  }
  const normalizedEmail = deps.normalizeEmail(email || "");
  if (normalizedEmail === "tom.griger@gmail.com") {
    return deps.PLAN_CODE_COMMERCIAL;
  }
  const existingPlan = deps.normalizeRequestedPlan(existingUser && existingUser.status || "");
  if ([deps.PLAN_CODE_PERSONAL, deps.PLAN_CODE_COMMERCIAL].includes(existingPlan)) {
    return existingPlan;
  }
  return deps.PLAN_CODE_COMMERCIAL;
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

async function revokeRefreshSessions(db, userId, deps) {
  await deps.ensureRefreshSessionColumns(db);
  const result = await deps.dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [deps.nowIso(), userId],
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

export async function handleAdminUserBlock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, user: adminUser } = auth;
  await deps.ensureRefreshSessionColumns(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetUser(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "user_not_found" ? 404 : 400, env);
  }

  const targetUserId = String(target.user.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.user.email || "");
  const now = deps.nowIso();
  await deps.dbRun(db, `UPDATE users SET status = 'blocked' WHERE id = ?`, [targetUserId]);
  const revokedSessions = await revokeRefreshSessions(db, targetUserId, deps);
  console.log("admin.user_blocked", JSON.stringify({ user_id: targetUserId, user_email: targetEmail, admin_email: deps.normalizeEmail(adminUser && adminUser.email || "") }));
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json({ ok: true, action: "block_user", user_id: targetUserId, user_email: targetEmail, status: "blocked", revoked_sessions: revokedSessions, updated_at: now }, 200, env);
}

export async function handleAdminUserUnblock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, user: adminUser } = auth;
  await deps.ensureRefreshSessionColumns(db);
  await deps.ensureAdminHardBlocksTable(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetUser(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "user_not_found" ? 404 : 400, env);
  }

  const targetUserId = String(target.user.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.user.email || "");
  const targetStatus = deps.PLAN_CODE_COMMERCIAL;
  const now = deps.nowIso();
  await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetStatus, targetUserId]);
  const hardBlocksClearedResult = await deps.dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET active = 0
      WHERE active = 1
        AND (
          source_user_id = ?
          OR LOWER(COALESCE(source_user_email, '')) = ?
          OR LOWER(COALESCE(blocked_email, '')) = ?
        )
    `,
    [targetUserId, targetEmail, targetEmail],
  );
  const revokedSessions = await revokeRefreshSessions(db, targetUserId, deps);
  console.log("admin.user_unblocked", JSON.stringify({ user_id: targetUserId, user_email: targetEmail, admin_email: deps.normalizeEmail(adminUser && adminUser.email || "") }));
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json({ ok: true, action: "unblock_user", user_id: targetUserId, user_email: targetEmail, status: targetStatus, hard_blocks_cleared: deps.dbMetaChanges(hardBlocksClearedResult), revoked_sessions: revokedSessions, updated_at: now }, 200, env);
}

export async function handleAdminUserHardBlock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, user: adminUser } = auth;
  await deps.ensureRefreshSessionColumns(db);
  await deps.ensureAdminHardBlocksTable(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetUser(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "user_not_found" ? 404 : 400, env);
  }

  const targetUserId = String(target.user.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.user.email || "");
  const now = deps.nowIso();
  const blockedDeviceId = deps.normalizeDeviceId(String(body.blocked_device_id || body.device_id || ""));
  const blockedIp = String(body.blocked_ip || body.ip || deps.requestClientIp(request) || "").trim();
  const reason = String(body.reason || "manual_admin_hard_block").trim().slice(0, 160) || "manual_admin_hard_block";

  await deps.dbRun(db, `UPDATE users SET status = 'blocked' WHERE id = ?`, [targetUserId]);
  const revokedSessions = await revokeRefreshSessions(db, targetUserId, deps);
  await deps.dbRun(
    db,
    `
      INSERT INTO admin_hard_blocks (
        id, blocked_email, blocked_device_id, blocked_ip, source_user_id,
        source_user_email, reason, created_by, created_at, active
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    `,
    [
      crypto.randomUUID(),
      targetEmail || null,
      blockedDeviceId || null,
      blockedIp || null,
      targetUserId || null,
      targetEmail || null,
      reason,
      deps.normalizeEmail(adminUser && adminUser.email || "") || null,
      now,
    ],
  );
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json({ ok: true, action: "hard_block_user", user_id: targetUserId, user_email: targetEmail, status: "blocked", blocked_device_id: blockedDeviceId || null, blocked_ip: blockedIp || null, revoked_sessions: revokedSessions, updated_at: now }, 200, env);
}

export async function handleAdminQaAuthReset(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) return auth.error;
  const { db, user: adminUser } = auth;
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

  const existingUser = await deps.findUserByEmail(db, targetEmail);
  const targetPlan = resolveQaResetPlanCode(targetEmail, body && body.plan_code || "", existingUser, deps);
  const now = deps.nowIso();
  let user = existingUser;
  if (!user) {
    user = await deps.upsertUserByEmail(db, targetEmail, targetPlan, { signupSource: "admin_qa_reset" }, env);
  } else {
    await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetPlan, String(user.id || "").trim()]);
    user = { ...user, status: targetPlan };
  }

  const userId = String(user && user.id || "").trim();
  if (!userId) {
    return deps.json({ ok: false, error: "user_not_found" }, 404, env);
  }

  const revokedSessions = await revokeRefreshSessions(db, userId, deps);
  const clearedHardBlocksResult = await deps.dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET active = 0
      WHERE active = 1
        AND (
          source_user_id = ?
          OR LOWER(COALESCE(source_user_email, '')) = ?
          OR LOWER(COALESCE(blocked_email, '')) = ?
        )
    `,
    [userId, targetEmail, targetEmail],
  );
  const clearedRateLimits = await clearQaAuthRateLimits(db, request, deps);
  console.log("admin.qa_auth_reset", JSON.stringify({ user_id: userId, user_email: targetEmail, plan_code: targetPlan, admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""), revoked_sessions: revokedSessions, cleared_hard_blocks: deps.dbMetaChanges(clearedHardBlocksResult) }));
  await invalidateAdminAnalyticsSnapshots(env, deps);

  return deps.json({ ok: true, action: "qa_auth_reset", user_id: userId, user_email: targetEmail, plan_code: targetPlan, revoked_sessions: revokedSessions, cleared_hard_blocks: deps.dbMetaChanges(clearedHardBlocksResult), cleared_rate_limits: clearedRateLimits, updated_at: now }, 200, env);
}
