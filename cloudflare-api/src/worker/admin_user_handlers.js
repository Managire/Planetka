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
  const targetPlanRaw = String(body && body.plan_code || "").trim();
  const targetPlan = deps.normalizePlanCode(targetPlanRaw);
  if (!targetPlan || !["free", "personal", "commercial"].includes(targetPlan)) {
    return deps.json({ ok: false, error: "missing_plan_code" }, 400, env);
  }
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
  const body = await deps.parseJson(request);
  const target = await resolveTargetUser(db, body, deps);
  if (target.error) {
    return deps.json({ ok: false, error: target.error }, target.error === "user_not_found" ? 404 : 400, env);
  }

  const targetUserId = String(target.user.id || "").trim();
  const targetEmail = deps.normalizeEmail(target.user.email || "");
  const targetPlanRaw = String(body && body.plan_code || "").trim();
  const targetPlan = deps.normalizePlanCode(targetPlanRaw);
  if (!targetPlan || !["free", "personal", "commercial"].includes(targetPlan)) {
    return deps.json({ ok: false, error: "missing_plan_code" }, 400, env);
  }
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
