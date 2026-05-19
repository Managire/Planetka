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
  "free@planetka.io",
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
  const allowed = parseQaResetEmailSet(env, deps);
  return allowed.has(normalized);
}

function defaultQaPlanForEmail(email, deps) {
  const normalized = deps.normalizeEmail(email || "");
  if (normalized === "free@planetka.io") {
    return "free";
  }
  if (normalized === "tom.griger@gmail.com") {
    return "free";
  }
  return "";
}

function resolveQaResetPlanCode(email, requestedPlanCode, existingUser, deps) {
  const explicitPlan = deps.normalizePlanCode(requestedPlanCode || "");
  if (explicitPlan === "free") {
    return explicitPlan;
  }
  const emailDefault = defaultQaPlanForEmail(email, deps);
  if (emailDefault) {
    return emailDefault;
  }
  const existingPlan = deps.normalizePlanCode(existingUser && existingUser.status || "");
  if (existingPlan === "free") {
    return existingPlan;
  }
  return deps.normalizeRequestedPlan(existingPlan || "free");
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

async function clearQaAuthRateLimits(db, request, email, deps) {
  await deps.ensureRateLimitsTable(db);
  const clientIp = deps.requestClientIp(request);
  const targetEmail = deps.normalizeEmail(email || "");
  const cleared = {
    api_key_request_ip: 0,
    api_key_request_email: 0,
    api_key_exchange_ip: 0,
    auth_refresh_ip: 0,
  };
  if (clientIp) {
    cleared.api_key_request_ip = await clearRateLimitBucket(db, "api_key_request_ip", clientIp, deps);
    cleared.api_key_exchange_ip = await clearRateLimitBucket(db, "api_key_exchange_ip", clientIp, deps);
    cleared.auth_refresh_ip = await clearRateLimitBucket(db, "auth_refresh_ip", clientIp, deps);
  }
  if (targetEmail) {
    cleared.api_key_request_email = await clearRateLimitBucket(db, "api_key_request_email", targetEmail, deps);
  }
  return cleared;
}

async function invalidateAdminAnalyticsSnapshots(env, deps) {
  try {
    await deps.invalidateAnalyticsSnapshots(env);
  } catch (error) {
    console.warn(
      "planetka.admin.analytics_snapshot_invalidate_failed",
      JSON.stringify({
        error: String(error && error.message || "analytics_snapshot_invalidate_failed"),
      }),
    );
  }
}

export async function handleAdminUserBlock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await deps.ensureApiKeyTables(db);
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
  const revokedKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET status = 'revoked', revoked_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [now, targetUserId],
  );
  const revokedSessionsResult = await deps.dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [now, targetUserId],
  );
  try {
    console.log(
      "admin.user_blocked",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json(
    {
      ok: true,
      action: "block_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: "blocked",
      revoked_api_keys: deps.dbMetaChanges(revokedKeysResult),
      revoked_sessions: deps.dbMetaChanges(revokedSessionsResult),
      updated_at: now,
    },
    200,
    env,
  );
}

export async function handleAdminUserUnblock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await deps.ensureApiKeyTables(db);
  await deps.ensureRefreshSessionColumns(db);
  await deps.ensureAdminHardBlocksTable(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetUser(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "user_not_found" ? 404 : 400, env);
  }

  const targetUserId = String(target.user.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.user.email || "");
  const targetStatus = deps.PLAN_CODE_PROFESSIONAL || "professional";
  const now = deps.nowIso();
  await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetStatus, targetUserId]);
  const apiKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET plan_code = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetStatus, targetUserId],
  );
  const hardBlocksClearedResult = await deps.dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET active = 0
      WHERE
        active = 1
        AND (
          source_user_id = ?
          OR LOWER(COALESCE(source_user_email, '')) = ?
          OR LOWER(COALESCE(blocked_email, '')) = ?
        )
    `,
    [targetUserId, targetEmail, targetEmail],
  );
  try {
    console.log(
      "admin.user_unblocked",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json(
    {
      ok: true,
      action: "unblock_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: targetStatus,
      updated_active_api_keys: deps.dbMetaChanges(apiKeysResult),
      hard_blocks_cleared: deps.dbMetaChanges(hardBlocksClearedResult),
      updated_at: now,
    },
    200,
    env,
  );
}

export async function handleAdminUserHardBlock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await deps.ensureApiKeyTables(db);
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

  await deps.dbRun(db, `UPDATE users SET status = 'blocked' WHERE id = ?`, [targetUserId]);
  const revokedKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET status = 'revoked', revoked_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [now, targetUserId],
  );
  const revokedSessionsResult = await deps.dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [now, targetUserId],
  );

  const fallbackRequest = await deps.dbGet(
    db,
    `
      SELECT request_device_id, request_ip
      FROM api_key_requests
      WHERE LOWER(email) = ?
      ORDER BY created_at DESC
      LIMIT 1
    `,
    [targetEmail],
  );
  const blockedDeviceId = deps.normalizeDeviceId(String(fallbackRequest && fallbackRequest.request_device_id || ""));
  const blockedIp = String(fallbackRequest && fallbackRequest.request_ip || "").trim();
  const reason = String(body.reason || "manual_admin_hard_block").trim().slice(0, 160) || "manual_admin_hard_block";
  await deps.dbRun(
    db,
    `
      INSERT INTO admin_hard_blocks (
        id,
        blocked_email,
        blocked_device_id,
        blocked_ip,
        source_user_id,
        source_user_email,
        reason,
        created_by,
        created_at,
        active
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
  return deps.json(
    {
      ok: true,
      action: "hard_block_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: "blocked",
      blocked_device_id: blockedDeviceId || null,
      blocked_ip: blockedIp || null,
      revoked_api_keys: deps.dbMetaChanges(revokedKeysResult),
      revoked_sessions: deps.dbMetaChanges(revokedSessionsResult),
      updated_at: now,
    },
    200,
    env,
  );
}

export async function handleAdminUserSetPlan(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await deps.ensureApiKeyTables(db);
  await deps.ensureRefreshSessionColumns(db);
  const body = await deps.parseJson(request);
  const target = await resolveTargetUser(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "user_not_found" ? 404 : 400, env);
  }

  const targetPlan = deps.normalizeRequestedPlan(body && body.plan_code || "");
  if (![deps.PLAN_CODE_PERSONAL, deps.PLAN_CODE_PROFESSIONAL].includes(targetPlan)) {
    return deps.json({ ok: false, error: "invalid_plan_code" }, 400, env);
  }
  if (deps.isBlockedStatus && deps.isBlockedStatus(target.user.status)) {
    return deps.json({ ok: false, error: "user_blocked", message: "Unblock the user before changing account type." }, 409, env);
  }

  const targetUserId = String(target.user.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.user.email || "");
  const now = deps.nowIso();
  await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetPlan, targetUserId]);
  const apiKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET plan_code = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetPlan, targetUserId],
  );
  const revokedSessionsResult = await deps.dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [now, targetUserId],
  );
  try {
    console.log(
      "admin.user_plan_set",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        plan_code: targetPlan,
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
        updated_active_api_keys: deps.dbMetaChanges(apiKeysResult),
        revoked_sessions: deps.dbMetaChanges(revokedSessionsResult),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
  await invalidateAdminAnalyticsSnapshots(env, deps);
  return deps.json(
    {
      ok: true,
      action: "set_user_plan",
      user_id: targetUserId,
      user_email: targetEmail,
      plan_code: targetPlan,
      updated_active_api_keys: deps.dbMetaChanges(apiKeysResult),
      revoked_sessions: deps.dbMetaChanges(revokedSessionsResult),
      updated_at: now,
    },
    200,
    env,
  );
}

export async function handleAdminQaAuthReset(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await deps.ensureApiKeyTables(db);
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
  const targetPlan = resolveQaResetPlanCode(
    targetEmail,
    body && body.plan_code || "",
    existingUser,
    deps,
  );
  if (targetPlan !== "free") {
    return deps.json({ ok: false, error: "missing_plan_code" }, 400, env);
  }

  const now = deps.nowIso();
  let user = existingUser;
  if (!user) {
    user = await deps.upsertUserByEmail(
      db,
      targetEmail,
      targetPlan,
      { signupSource: "admin_qa_reset" },
      env,
    );
  } else {
    await deps.dbRun(db, `UPDATE users SET status = ? WHERE id = ?`, [targetPlan, String(user.id || "").trim()]);
    user = { ...user, status: targetPlan };
  }

  const userId = String(user && user.id || "").trim();
  if (!userId) {
    return deps.json({ ok: false, error: "user_not_found" }, 404, env);
  }

  const revokedKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET status = 'revoked', revoked_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [now, userId],
  );
  const revokedSessionsResult = await deps.dbRun(
    db,
    `
      UPDATE refresh_sessions
      SET revoked_at = ?
      WHERE user_id = ?
        AND (revoked_at IS NULL OR revoked_at = '')
    `,
    [now, userId],
  );
  const clearedDeviceActivityResult = await deps.dbRun(
    db,
    `DELETE FROM api_key_device_activity WHERE user_id = ?`,
    [userId],
  );
  const clearedApiKeyRequestsResult = await deps.dbRun(
    db,
    `DELETE FROM api_key_requests WHERE LOWER(email) = ?`,
    [targetEmail],
  );
  const clearedHardBlocksResult = await deps.dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET active = 0
      WHERE
        active = 1
        AND (
          source_user_id = ?
          OR LOWER(COALESCE(source_user_email, '')) = ?
          OR LOWER(COALESCE(blocked_email, '')) = ?
        )
    `,
    [userId, targetEmail, targetEmail],
  );
  const clearedRateLimits = await clearQaAuthRateLimits(db, request, targetEmail, deps);
  const issued = await deps.issueApiKeyForUser(
    db,
    env,
    user,
    targetPlan,
    {},
  );

  try {
    console.log(
      "admin.qa_auth_reset",
      JSON.stringify({
        user_id: userId,
        user_email: targetEmail,
        plan_code: targetPlan,
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
        revoked_api_keys: deps.dbMetaChanges(revokedKeysResult),
        revoked_sessions: deps.dbMetaChanges(revokedSessionsResult),
        cleared_device_activity: deps.dbMetaChanges(clearedDeviceActivityResult),
        cleared_api_key_requests: deps.dbMetaChanges(clearedApiKeyRequestsResult),
        cleared_hard_blocks: deps.dbMetaChanges(clearedHardBlocksResult),
        issued_api_key_id: String(issued && issued.apiKeyId || "").trim(),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
  await invalidateAdminAnalyticsSnapshots(env, deps);

  return deps.json(
    {
      ok: true,
      action: "qa_auth_reset",
      user_id: userId,
      user_email: targetEmail,
      plan_code: targetPlan,
      revoked_api_keys: deps.dbMetaChanges(revokedKeysResult),
      revoked_sessions: deps.dbMetaChanges(revokedSessionsResult),
      cleared_device_activity: deps.dbMetaChanges(clearedDeviceActivityResult),
      cleared_api_key_requests: deps.dbMetaChanges(clearedApiKeyRequestsResult),
      cleared_hard_blocks: deps.dbMetaChanges(clearedHardBlocksResult),
      cleared_rate_limits: clearedRateLimits,
      api_key: issued.apiKey,
      api_key_id: issued.apiKeyId,
      expires_at: issued.expiresAt,
      updated_at: now,
    },
    200,
    env,
  );
}
