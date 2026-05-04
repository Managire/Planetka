const TILE_KEY_RE = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i;
const ASSET_RE = /^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$/i;
const FREE_D_THRESHOLD = 15;
const ACCOUNT_TYPE_UNLIMITED = "unlimited";

function normalizeTileKey(value) {
  const raw = String(value || "").trim();
  const assetMatch = ASSET_RE.exec(raw.split("/").pop() || raw);
  const source = assetMatch ? assetMatch[1] : raw;
  const match = TILE_KEY_RE.exec(source);
  if (!match) {
    return "";
  }
  const x = Number.parseInt(match[1], 10);
  const y = Number.parseInt(match[2], 10);
  const z = Number.parseInt(match[3], 10);
  const d = Number.parseInt(match[4], 10);
  if (![x, y, z, d].every(Number.isFinite)) {
    return "";
  }
  return `x${String(x).padStart(3, "0")}_y${String(y).padStart(3, "0")}_z${String(z).padStart(3, "0")}_d${String(d).padStart(3, "0")}`;
}

function parseTileKey(value) {
  const key = normalizeTileKey(value);
  const match = TILE_KEY_RE.exec(key);
  if (!match) {
    return null;
  }
  return {
    key,
    x: Number.parseInt(match[1], 10),
    y: Number.parseInt(match[2], 10),
    z: Number.parseInt(match[3], 10),
    d: Number.parseInt(match[4], 10),
  };
}

export function tileKeyFromFileName(fileName) {
  return normalizeTileKey(fileName);
}

export function isFreeCreditTileKey(tileKey) {
  const parsed = parseTileKey(tileKey);
  if (!parsed) {
    return true;
  }
  if (parsed.d >= FREE_D_THRESHOLD) {
    return true;
  }
  const south = Number(parsed.y) - 90;
  const north = Number(parsed.y + parsed.z) - 90;
  if (north <= -60) {
    return true;
  }
  if (south >= 75) {
    return true;
  }
  return false;
}

export function defaultAssetsForTile(tileKey) {
  const key = normalizeTileKey(tileKey);
  const parsed = parseTileKey(key);
  if (!parsed) {
    return [];
  }
  const elKey = parsed.z === 1 && parsed.d === 2 ? key.replace("_d002", "_d001") : key;
  return [
    { folder: "S2", file_name: `S2_${key}.exr` },
    { folder: "EL", file_name: `EL_${elKey}.exr` },
    { folder: "WT", file_name: `WT_${key}.exr` },
    { folder: "PO", file_name: `PO_${key}.tif` },
  ];
}

function normalizeCreditAmount(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.round(parsed * 1_000_000) / 1_000_000;
}

function normalizeAccountType(value) {
  const token = String(value || "").trim().toLowerCase();
  if (token === ACCOUNT_TYPE_UNLIMITED) {
    return ACCOUNT_TYPE_UNLIMITED;
  }
  if (token === "standard" || token === "credits" || token === "credit") {
    return "standard";
  }
  return ACCOUNT_TYPE_UNLIMITED;
}

function isUnlimitedCreditAccount(account) {
  return normalizeAccountType(account && account.account_type) === ACCOUNT_TYPE_UNLIMITED;
}

function normalizePricingTiles(value) {
  const source = Array.isArray(value) ? value : [];
  const byKey = new Map();
  for (const entry of source) {
    if (!entry || typeof entry !== "object") {
      continue;
    }
    const tileKey = normalizeTileKey(entry.tile_key || entry.tileKey || entry.key || "");
    if (!tileKey) {
      continue;
    }
    const credits = normalizeCreditAmount(entry.credits);
    const previous = byKey.get(tileKey);
    if (previous && previous.credits >= credits) {
      continue;
    }
    byKey.set(tileKey, {
      tile_key: tileKey,
      credits,
      land_km2: Math.max(0, Number.parseFloat(entry.land_km2 || entry.landKm2 || 0) || 0),
      billable_land_km2: Math.max(0, Number.parseFloat(entry.billable_land_km2 || entry.billableLandKm2 || 0) || 0),
      free_reason: String(entry.free_reason || entry.freeReason || "").trim(),
      stats_source: String(entry.stats_source || entry.statsSource || "").trim(),
    });
  }
  return Array.from(byKey.values());
}

async function ensureCreditAccount(db, userId, deps) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  const now = deps.nowIso();
  await deps.dbRun(
    db,
    `
      INSERT OR IGNORE INTO user_credit_accounts (
        user_id, account_type, balance_credits, total_granted_credits, total_spent_credits, created_at, updated_at
      )
      VALUES (?, 'unlimited', 0, 0, 0, ?, ?)
    `,
    [safeUserId, now, now],
  );
  return await deps.dbGet(db, `SELECT * FROM user_credit_accounts WHERE user_id = ? LIMIT 1`, [safeUserId]);
}

export async function isTileUnlockedForUser(db, userId, tileKey, deps) {
  const key = normalizeTileKey(tileKey);
  if (!key || isFreeCreditTileKey(key)) {
    return true;
  }
  const account = await ensureCreditAccount(db, userId, deps);
  if (isUnlimitedCreditAccount(account)) {
    return true;
  }
  const row = await deps.dbGet(
    db,
    `SELECT 1 FROM user_tile_entitlements WHERE user_id = ? AND tile_key = ? LIMIT 1`,
    [String(userId || "").trim(), key],
  );
  return Boolean(row);
}

async function estimateNewCredits(db, userId, pricingTiles, deps) {
  await deps.ensureCreditTables(db);
  const rows = pricingTiles.length
    ? await deps.dbAll(
      db,
      `
        SELECT tile_key
        FROM user_tile_entitlements
        WHERE user_id = ?
          AND tile_key IN (${pricingTiles.map(() => "?").join(",")})
      `,
      [String(userId || "").trim(), ...pricingTiles.map((tile) => tile.tile_key)],
    )
    : [];
  const owned = new Set((rows || []).map((row) => String(row && row.tile_key || "").trim()));
  let credits = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;
  const newTiles = [];
  for (const tile of pricingTiles) {
    const key = normalizeTileKey(tile.tile_key);
    const globallyFree = isFreeCreditTileKey(key);
    const alreadyOwned = owned.has(key);
    const tileCredits = (globallyFree || alreadyOwned) ? 0 : normalizeCreditAmount(tile.credits);
    if (tileCredits > 0) {
      paidTileCount += 1;
      credits += tileCredits;
    } else {
      freeTileCount += 1;
    }
    if (!globallyFree && !alreadyOwned) {
      newTiles.push({ ...tile, credits: tileCredits });
    }
  }
  return {
    credits: Math.round(credits * 1_000_000) / 1_000_000,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: pricingTiles.length,
    new_tiles: newTiles,
  };
}

export async function unlockTilesForSession(db, userId, qualityMode, pricingTiles, resolveId, deps) {
  const safeMode = deps.normalizeQualityMode(qualityMode || "");
  if (safeMode === "preview") {
    return { credits: 0, paid_tile_count: 0, free_tile_count: 0, tile_count: 0 };
  }
  const safeUserId = String(userId || "").trim();
  const normalizedTiles = normalizePricingTiles(pricingTiles);
  const estimate = await estimateNewCredits(db, safeUserId, normalizedTiles, deps);
  const requiredCredits = normalizeCreditAmount(estimate.credits);
  const account = await ensureCreditAccount(db, safeUserId, deps);
  if (isUnlimitedCreditAccount(account)) {
    const now = deps.nowIso();
    for (const tile of estimate.new_tiles || []) {
      await deps.dbRun(
        db,
        `
          INSERT OR IGNORE INTO user_tile_entitlements (
            user_id, tile_key, quality_mode, credits_spent, land_km2, billable_land_km2, source, unlocked_at
          )
          VALUES (?, ?, ?, 0, ?, ?, ?, ?)
        `,
        [
          safeUserId,
          tile.tile_key,
          safeMode,
          Math.max(0, Number.parseFloat(tile.land_km2 || 0) || 0),
          Math.max(0, Number.parseFloat(tile.billable_land_km2 || 0) || 0),
          "unlimited",
          now,
        ],
      );
    }
    return {
      ...estimate,
      credits: 0,
      paid_tile_count: 0,
      free_tile_count: estimate.tile_count,
      unlimited_credits: true,
    };
  }
  const balance = normalizeCreditAmount(account && account.balance_credits);
  if (requiredCredits > balance) {
    return {
      error: "insufficient_credits",
      required_credits: requiredCredits,
      balance_credits: balance,
      paid_tile_count: estimate.paid_tile_count,
      tile_count: estimate.tile_count,
    };
  }

  const now = deps.nowIso();
  if (requiredCredits > 0) {
    const update = await deps.dbRun(
      db,
      `
        UPDATE user_credit_accounts
        SET
          balance_credits = balance_credits - ?,
          total_spent_credits = total_spent_credits + ?,
          updated_at = ?
        WHERE user_id = ?
          AND balance_credits >= ?
      `,
      [requiredCredits, requiredCredits, now, safeUserId, requiredCredits],
    );
    if (deps.dbMetaChanges(update) <= 0) {
      const fresh = await ensureCreditAccount(db, safeUserId, deps);
      return {
        error: "insufficient_credits",
        required_credits: requiredCredits,
        balance_credits: normalizeCreditAmount(fresh && fresh.balance_credits),
        paid_tile_count: estimate.paid_tile_count,
        tile_count: estimate.tile_count,
      };
    }
    const balanceAfter = Math.round((balance - requiredCredits) * 1_000_000) / 1_000_000;
    await deps.dbRun(
      db,
      `
        INSERT INTO credit_ledger (
          id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, 'tile_unlock', ?, ?)
      `,
      [
        deps.randomToken(16),
        safeUserId,
        -requiredCredits,
        balanceAfter,
        JSON.stringify({ resolve_id: String(resolveId || ""), quality_mode: safeMode, tile_count: estimate.paid_tile_count }),
        now,
      ],
    );
  }

  for (const tile of estimate.new_tiles || []) {
    await deps.dbRun(
      db,
      `
        INSERT OR IGNORE INTO user_tile_entitlements (
          user_id, tile_key, quality_mode, credits_spent, land_km2, billable_land_km2, source, unlocked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        safeUserId,
        tile.tile_key,
        safeMode,
        normalizeCreditAmount(tile.credits),
        Math.max(0, Number.parseFloat(tile.land_km2 || 0) || 0),
        Math.max(0, Number.parseFloat(tile.billable_land_km2 || 0) || 0),
        String(tile.stats_source || "client_pricing").trim() || "client_pricing",
        now,
      ],
    );
  }

  return estimate;
}

export async function handleCreditMe(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  const account = await ensureCreditAccount(db, auth.user.id, deps);
  const countRow = await deps.dbGet(
    db,
    `SELECT COUNT(*) AS count FROM user_tile_entitlements WHERE user_id = ?`,
    [String(auth.user.id || "").trim()],
  );
  return deps.json(
    {
      ok: true,
      account_type: normalizeAccountType(account && account.account_type),
      unlimited_credits: isUnlimitedCreditAccount(account),
      balance_credits: normalizeCreditAmount(account && account.balance_credits),
      unlocked_tile_count: Number(countRow && countRow.count || 0),
      user_id: String(auth.user.id || ""),
    },
    200,
    env,
  );
}

export async function handleCreditEstimate(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await ensureCreditAccount(db, auth.user.id, deps);
  const body = await deps.parseJson(request);
  const pricingTiles = normalizePricingTiles(body && (body.tiles || body.pricing_tiles));
  const estimate = await estimateNewCredits(db, auth.user.id, pricingTiles, deps);
  const account = await ensureCreditAccount(db, auth.user.id, deps);
  const unlimited = isUnlimitedCreditAccount(account);
  return deps.json(
    {
      ok: true,
      ...estimate,
      credits: unlimited ? 0 : estimate.credits,
      paid_tile_count: unlimited ? 0 : estimate.paid_tile_count,
      free_tile_count: unlimited ? estimate.tile_count : estimate.free_tile_count,
      account_type: normalizeAccountType(account && account.account_type),
      unlimited_credits: unlimited,
      balance_credits: normalizeCreditAmount(account && account.balance_credits),
    },
    200,
    env,
  );
}

export async function handleCreditUnlocked(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await deps.ensureCreditTables(db);
  const rows = await deps.dbAll(
    db,
    `
      SELECT tile_key, quality_mode, credits_spent, land_km2, billable_land_km2, unlocked_at
      FROM user_tile_entitlements
      WHERE user_id = ?
      ORDER BY unlocked_at DESC, tile_key ASC
      LIMIT 50000
    `,
    [String(auth.user.id || "").trim()],
  );
  const tiles = (rows || []).map((row) => ({
    tile_key: String(row && row.tile_key || ""),
    quality_mode: String(row && row.quality_mode || ""),
    credits_spent: normalizeCreditAmount(row && row.credits_spent),
    land_km2: Math.max(0, Number.parseFloat(row && row.land_km2 || 0) || 0),
    billable_land_km2: Math.max(0, Number.parseFloat(row && row.billable_land_km2 || 0) || 0),
    unlocked_at: String(row && row.unlocked_at || ""),
    assets: defaultAssetsForTile(row && row.tile_key || ""),
  }));
  return deps.json({ ok: true, tiles, unlocked_tile_count: tiles.length }, 200, env);
}

export async function handleAdminGiftCredits(request, env, deps) {
  const auth = await deps.requireAnalyticsAdmin(request, env);
  if (auth.error) {
    return auth.error;
  }
  const { db, user: adminUser } = auth;
  const body = await deps.parseJson(request);
  const requestedUserId = String(body && body.user_id || "").trim();
  const requestedEmail = deps.normalizeEmail(body && body.email || "");
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
  const amount = normalizeCreditAmount(body && (body.credits || body.amount || body.delta_credits));
  if (amount <= 0) {
    return deps.json({ ok: false, error: "missing_positive_credits" }, 400, env);
  }
  const reason = String(body && body.reason || "admin_gift").trim().slice(0, 160) || "admin_gift";
  const userId = String(targetUser.id || "").trim();
  const now = deps.nowIso();
  await ensureCreditAccount(db, userId, deps);
  await deps.dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET
        balance_credits = balance_credits + ?,
        total_granted_credits = total_granted_credits + ?,
        updated_at = ?
      WHERE user_id = ?
    `,
    [amount, amount, now, userId],
  );
  const account = await ensureCreditAccount(db, userId, deps);
  const balanceAfter = normalizeCreditAmount(account && account.balance_credits);
  await deps.dbRun(
    db,
    `
      INSERT INTO credit_ledger (
        id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `,
    [
      deps.randomToken(16),
      userId,
      amount,
      balanceAfter,
      reason,
      JSON.stringify({
        admin_user_id: String(adminUser && adminUser.id || ""),
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
      }),
      now,
    ],
  );
  return deps.json(
    {
      ok: true,
      action: "gift_credits",
      user_id: userId,
      user_email: deps.normalizeEmail(targetUser.email || ""),
      gifted_credits: amount,
      balance_credits: balanceAfter,
      updated_at: now,
    },
    200,
    env,
  );
}
