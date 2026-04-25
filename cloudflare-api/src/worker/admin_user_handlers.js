async function resolveDownloadCounterTarget(db, userId, email, deps) {
  const requestedUserId = String(userId || "").trim();
  const requestedEmail = deps.normalizeEmail(email || "");
  if (!requestedUserId && !requestedEmail) {
    return null;
  }
  let counter = requestedUserId ? await deps.findUserDownloadCounter(db, requestedUserId) : null;
  if (!counter && requestedEmail) {
    counter = await deps.findUserDownloadCounterByEmail(db, requestedEmail);
  }
  return counter;
}

export async function handleAdminUserUnthrottle(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db } = auth;
  await deps.ensureUserDownloadCountersTable(db);
  const body = await deps.parseJson(request);
  const hasResetHourFlag = Object.prototype.hasOwnProperty.call(body, "reset_hour");
  const resetHour = hasResetHourFlag ? deps.parseBooleanFlag(body.reset_hour) : true;
  const counter = await resolveDownloadCounterTarget(db, body.user_id, body.email, deps);
  if (!counter) {
    return deps.json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  const previousThrottledUntil = String(counter.throttled_until || "").trim();
  const updated = await deps.clearUserDownloadThrottle(db, String(counter.user_id || "").trim(), { resetHour });
  if (!updated) {
    return deps.json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  return deps.json(
    {
      ok: true,
      action: "unthrottle",
      user_id: String(updated.user_id || ""),
      user_email: String(updated.user_email || ""),
      reset_hour: resetHour,
      previous_throttled_until: previousThrottledUntil || null,
      throttled_until: String(updated.throttled_until || "").trim() || null,
      hour_bytes: deps.clampNonNegativeInt(updated.hour_bytes),
      hour_bucket_start_unix: deps.clampNonNegativeInt(updated.hour_bucket_start_unix),
      updated_at: String(updated.updated_at || deps.nowIso()),
    },
    200,
    env,
  );
}

export async function handleAdminUserThrottle(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db } = auth;
  await deps.ensureUserDownloadCountersTable(db);
  const body = await deps.parseJson(request);
  const hasResetHourFlag = Object.prototype.hasOwnProperty.call(body, "reset_hour");
  const resetHour = hasResetHourFlag ? deps.parseBooleanFlag(body.reset_hour) : false;
  const durationMinutes = Math.max(
    1,
    deps.parseNonNegativeInteger(body.duration_minutes, deps.DEFAULT_DOWNLOAD_THROTTLE_DURATION_MINUTES),
  );
  const counter = await resolveDownloadCounterTarget(db, body.user_id, body.email, deps);
  if (!counter) {
    return deps.json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  const updated = await deps.setUserDownloadThrottle(
    db,
    String(counter.user_id || "").trim(),
    { durationMinutes, resetHour },
  );
  if (!updated) {
    return deps.json({ ok: false, error: "download_counter_not_found" }, 404, env);
  }
  return deps.json(
    {
      ok: true,
      action: "throttle",
      user_id: String(updated.user_id || ""),
      user_email: String(updated.user_email || ""),
      duration_minutes: durationMinutes,
      reset_hour: resetHour,
      throttled_until: String(updated.throttled_until || "").trim() || null,
      hour_bytes: deps.clampNonNegativeInt(updated.hour_bytes),
      hour_bucket_start_unix: deps.clampNonNegativeInt(updated.hour_bucket_start_unix),
      updated_at: String(updated.updated_at || deps.nowIso()),
    },
    200,
    env,
  );
}

export async function handleAdminUserBlock(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  await deps.ensureApiKeyTables(db);
  await deps.ensureRefreshSessionColumns(db);
  await deps.ensureUserProvisionalColumns(db);
  await deps.ensureUserDownloadCountersTable(db);
  const body = await deps.parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = deps.normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return deps.json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }
  let targetUser = requestedUserId ? await deps.findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await deps.findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return deps.json({ ok: false, error: "user_not_found" }, 404, env);
  }
  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = deps.normalizeEmail(targetUser.email || "");
  const now = deps.nowIso();
  await deps.dbRun(
    db,
    `
      UPDATE users
      SET
        status = 'blocked',
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = NULL
      WHERE id = ?
    `,
    [targetUserId],
  );
  const revokedKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET
        status = 'revoked',
        revoked_at = ?
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
  const updatedCounter = await deps.clearUserDownloadThrottle(db, targetUserId, { resetHour: true });
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
  return deps.json(
    {
      ok: true,
      action: "block_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: "blocked",
      revoked_api_keys: deps.dbMetaChanges(revokedKeysResult),
      revoked_sessions: deps.dbMetaChanges(revokedSessionsResult),
      throttled_until: String(updatedCounter && updatedCounter.throttled_until || "").trim() || null,
      updated_at: String(updatedCounter && updatedCounter.updated_at || now),
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
  await deps.ensureUserProvisionalColumns(db);
  await deps.ensureUserDownloadCountersTable(db);
  await deps.ensureAdminHardBlocksTable(db);
  const body = await deps.parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = deps.normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return deps.json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }
  let targetUser = requestedUserId ? await deps.findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await deps.findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return deps.json({ ok: false, error: "user_not_found" }, 404, env);
  }
  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = deps.normalizeEmail(targetUser.email || "");
  const targetPlan = deps.normalizeRequestedPlan(body.plan_code || deps.PLAN_CODE_PLANETKA);
  const now = deps.nowIso();
  const proConfirmedAt = deps.isPaidRequestedPlan(targetPlan) ? now : null;
  await deps.dbRun(
    db,
    `
      UPDATE users
      SET
        status = ?,
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = ?
      WHERE id = ?
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  const apiKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        provisional = 0,
        provisional_expires_at = NULL,
        confirmed_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  await deps.dbRun(
    db,
    `
      UPDATE user_download_counters
      SET plan_code = ?, updated_at = ?
      WHERE user_id = ?
    `,
    [targetPlan, now, targetUserId],
  );
  const hardBlocksClearedResult = await deps.dbRun(
    db,
    `
      UPDATE admin_hard_blocks
      SET
        active = 0
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
  const updatedCounter = await deps.clearUserDownloadThrottle(db, targetUserId, { resetHour: true });
  try {
    console.log(
      "admin.user_unblocked",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        plan_code: targetPlan,
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }
  return deps.json(
    {
      ok: true,
      action: "unblock_user",
      user_id: targetUserId,
      user_email: targetEmail,
      status: targetPlan,
      updated_active_api_keys: deps.dbMetaChanges(apiKeysResult),
      hard_blocks_cleared: deps.dbMetaChanges(hardBlocksClearedResult),
      throttled_until: String(updatedCounter && updatedCounter.throttled_until || "").trim() || null,
      updated_at: String(updatedCounter && updatedCounter.updated_at || now),
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
  await deps.ensureUserProvisionalColumns(db);
  await deps.ensureUserDownloadCountersTable(db);
  await deps.ensureAdminHardBlocksTable(db);

  const body = await deps.parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = deps.normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return deps.json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }

  let targetUser = requestedUserId ? await deps.findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await deps.findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return deps.json({ ok: false, error: "user_not_found" }, 404, env);
  }

  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = deps.normalizeEmail(targetUser.email || "");
  const now = deps.nowIso();

  await deps.dbRun(
    db,
    `
      UPDATE users
      SET
        status = 'blocked',
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = NULL
      WHERE id = ?
    `,
    [targetUserId],
  );
  const revokedKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET
        status = 'revoked',
        revoked_at = ?
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

  const counter = await deps.findUserDownloadCounter(db, targetUserId);
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
  const blockedDeviceId = deps.normalizeDeviceId(
    String(counter && counter.last_device_id || "") || String(fallbackRequest && fallbackRequest.request_device_id || ""),
  );
  const blockedIp = String(counter && counter.last_ip || "").trim() || String(fallbackRequest && fallbackRequest.request_ip || "").trim();
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
  const updatedCounter = await deps.clearUserDownloadThrottle(db, targetUserId, { resetHour: true });
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
      throttled_until: String(updatedCounter && updatedCounter.throttled_until || "").trim() || null,
      updated_at: String(updatedCounter && updatedCounter.updated_at || now),
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
  await deps.ensureUserProvisionalColumns(db);
  await deps.ensureUserDownloadCountersTable(db);

  const body = await deps.parseJson(request);
  const requestedUserId = String(body.user_id || "").trim();
  const requestedEmail = deps.normalizeEmail(body.email || "");
  if (!requestedUserId && !requestedEmail) {
    return deps.json({ ok: false, error: "missing_user_id_or_email" }, 400, env);
  }

  let targetUser = requestedUserId ? await deps.findUserById(db, requestedUserId) : null;
  if (!targetUser && requestedEmail) {
    targetUser = await deps.findUserByEmail(db, requestedEmail);
  }
  if (!targetUser) {
    return deps.json({ ok: false, error: "user_not_found" }, 404, env);
  }

  const targetUserId = String(targetUser.id || "").trim();
  const targetEmail = deps.normalizeEmail(targetUser.email || "");
  const targetPlan = deps.normalizeRequestedPlan(body.plan_code || deps.PLAN_CODE_PLANETKA);
  const now = deps.nowIso();
  const proConfirmedAt = deps.isPaidRequestedPlan(targetPlan) ? now : null;

  await deps.dbRun(
    db,
    `
      UPDATE users
      SET
        status = ?,
        provisional_plan_code = NULL,
        provisional_expires_at = NULL,
        pro_confirmed_at = ?
      WHERE id = ?
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  const apiKeysResult = await deps.dbRun(
    db,
    `
      UPDATE api_keys
      SET
        plan_code = ?,
        provisional = 0,
        provisional_expires_at = NULL,
        confirmed_at = ?
      WHERE user_id = ?
        AND status = 'active'
    `,
    [targetPlan, proConfirmedAt, targetUserId],
  );
  await deps.dbRun(
    db,
    `
      UPDATE user_download_counters
      SET plan_code = ?, updated_at = ?
      WHERE user_id = ?
    `,
    [targetPlan, now, targetUserId],
  );

  try {
    console.log(
      "admin.user_set_plan",
      JSON.stringify({
        user_id: targetUserId,
        user_email: targetEmail,
        plan_code: targetPlan,
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
      }),
    );
  } catch (_error) {
    // no-op logging guard
  }

  return deps.json(
    {
      ok: true,
      action: "set_plan",
      user_id: targetUserId,
      user_email: targetEmail,
      plan_code: targetPlan,
      updated_active_api_keys: deps.dbMetaChanges(apiKeysResult),
      updated_at: now,
    },
    200,
    env,
  );
}
