const TILE_KEY_RE = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i;
const ASSET_RE = /^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$/i;
const FREE_D_THRESHOLD = 60;
const ACCOUNT_TYPE_STANDARD = "standard";
const DEFAULT_STARTING_CREDITS = 100.0;
const DATASET_BASE_MPP = 10.0;
const EARTH_RADIUS_KM = 6371.0088;
const EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2;

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

function tileFamilyKey(parsed) {
  if (!parsed) {
    return "";
  }
  return `x${String(parsed.x).padStart(3, "0")}_y${String(parsed.y).padStart(3, "0")}_z${String(parsed.z).padStart(3, "0")}`;
}

function detailRatioForTile(parsed) {
  if (!parsed) {
    return Number.POSITIVE_INFINITY;
  }
  const z = Math.max(1, Number.parseFloat(parsed.z || 0) || 1);
  const d = Number.parseFloat(parsed.d || 0) || 0;
  if (d <= 0) {
    return Number.POSITIVE_INFINITY;
  }
  return d / z;
}

function sphericalAreaKm2(lonWest, lonEast, latSouth, latNorth) {
  if (!(lonEast > lonWest) || !(latNorth > latSouth)) {
    return 0;
  }
  const lonDelta = (Number(lonEast) - Number(lonWest)) * Math.PI / 180;
  const southRad = Number(latSouth) * Math.PI / 180;
  const northRad = Number(latNorth) * Math.PI / 180;
  return Math.max(0, (EARTH_RADIUS_KM ** 2) * lonDelta * Math.abs(Math.sin(northRad) - Math.sin(southRad)));
}

function tileAreaKm2(parsed) {
  if (!parsed) {
    return 0;
  }
  const lonWest = Number(parsed.x) - 180;
  const lonEast = Number(parsed.x + parsed.z) - 180;
  const latSouth = Math.max(-90, Number(parsed.y) - 90);
  const latNorth = Math.min(90, Number(parsed.y + parsed.z) - 90);
  return sphericalAreaKm2(lonWest, lonEast, latSouth, latNorth);
}

function paidBandAreaKm2(parsed) {
  if (!parsed) {
    return 0;
  }
  const lonWest = Number(parsed.x) - 180;
  const lonEast = Number(parsed.x + parsed.z) - 180;
  const latSouth = Math.max(-90, Number(parsed.y) - 90);
  const latNorth = Math.min(90, Number(parsed.y + parsed.z) - 90);
  return sphericalAreaKm2(lonWest, lonEast, Math.max(latSouth, -60), Math.min(latNorth, 75));
}

function effectiveBillableLandKm2(parsed, stats, freeReason) {
  if (String(freeReason || "").trim()) {
    return 0;
  }
  const storedBillable = Math.max(0, Number.parseFloat(stats && stats.billable_land_km2 || 0) || 0);
  if (storedBillable > 0) {
    return storedBillable;
  }
  const land = Math.max(0, Number.parseFloat(stats && stats.land_km2 || 0) || 0);
  if (land <= 0) {
    return 0;
  }
  const totalArea = tileAreaKm2(parsed);
  const paidArea = paidBandAreaKm2(parsed);
  if (!(totalArea > 0) || !(paidArea > 0)) {
    return 0;
  }
  return Math.max(0, land * Math.min(1, paidArea / totalArea));
}

function freeReasonForTile(parsed) {
  if (!parsed) {
    return "invalid_tile_key";
  }
  if (parsed.d <= 0) {
    return "d000_global_free";
  }
  if (parsed.d >= FREE_D_THRESHOLD) {
    return "coarse_detail_free";
  }
  const south = Number(parsed.y) - 90;
  const north = Number(parsed.y + parsed.z) - 90;
  if (north <= -60) {
    return "south_polar_free";
  }
  if (south >= 75) {
    return "north_polar_free";
  }
  return "";
}

export function isFreeCreditTileKey(tileKey) {
  return Boolean(freeReasonForTile(parseTileKey(tileKey)));
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

function deliveredMppForD(dValue) {
  let d = Number.parseInt(dValue, 10);
  if (!Number.isFinite(d)) {
    d = FREE_D_THRESHOLD;
  }
  if (d <= 0) {
    d = 1440;
  }
  return DATASET_BASE_MPP * Math.max(1, d);
}

function creditsForTileStats(tile, stats, qualityMode) {
  const safeMode = String(qualityMode || "").trim().toLowerCase();
  const derivedFreeReason = freeReasonForTile(tile);
  const freeReason = safeMode === "preview"
    ? "preview_quality"
    : derivedFreeReason;
  const mpp = deliveredMppForD(tile && tile.d);
  const billableLandKm2 = effectiveBillableLandKm2(tile, stats, freeReason);
  const baseCredits = Math.max(0, billableLandKm2 / EQUATOR_Z001_AREA_KM2);
  const qualityFactor = (DATASET_BASE_MPP / Math.max(DATASET_BASE_MPP, mpp)) ** 2;
  const credits = freeReason ? 0 : baseCredits * qualityFactor;
  const priceEur = normalizeCreditAmount(credits);
  return {
    tile_key: tile.key,
    credits: priceEur,
    price_eur: priceEur,
    land_km2: Math.max(0, Number.parseFloat(stats && stats.land_km2 || 0) || 0),
    billable_land_km2: billableLandKm2,
    delivered_mpp: normalizeCreditAmount(mpp),
    detail_ratio: normalizeCreditAmount(detailRatioForTile(tile)),
    price_factor: normalizeCreditAmount(qualityFactor),
    free_reason: freeReason,
    stats_source: "backend_d1",
  };
}

function normalizeAccountType(value) {
  const token = String(value || "").trim().toLowerCase();
  if (token === "standard" || token === "credits" || token === "credit") {
    return ACCOUNT_TYPE_STANDARD;
  }
  return ACCOUNT_TYPE_STANDARD;
}

function isUnlimitedCreditAccount(account) {
  void account;
  return false;
}

function normalizeTileKeys(value) {
  const source = Array.isArray(value) ? value : [];
  const keys = [];
  const seen = new Set();
  for (const entry of source) {
    const tileKey = typeof entry === "object" && entry !== null
      ? normalizeTileKey(entry.tile_key || entry.tileKey || entry.key || "")
      : normalizeTileKey(entry);
    if (!tileKey) {
      continue;
    }
    if (seen.has(tileKey)) {
      continue;
    }
    seen.add(tileKey);
    keys.push(tileKey);
  }
  return keys;
}

function requestTileKeysFromBody(body) {
  return normalizeTileKeys(
    body && (
      body.tile_keys
      || body.tileKeys
      || body.tiles
      || body.pricing_tiles
      || body.pricingTiles
    ),
  );
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
      VALUES (?, 'standard', ?, ?, 0, ?, ?)
    `,
    [safeUserId, DEFAULT_STARTING_CREDITS, DEFAULT_STARTING_CREDITS, now, now],
  );
  await deps.dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET account_type = 'standard',
          balance_credits = CASE
            WHEN account_type = 'unlimited' THEN ?
            ELSE balance_credits
          END,
          total_granted_credits = CASE
            WHEN account_type = 'unlimited' THEN ?
            ELSE total_granted_credits
          END,
          total_spent_credits = CASE
            WHEN account_type = 'unlimited' THEN 0
            ELSE total_spent_credits
          END,
          updated_at = ?
      WHERE user_id = ?
        AND account_type != 'standard'
    `,
    [DEFAULT_STARTING_CREDITS, DEFAULT_STARTING_CREDITS, now, safeUserId],
  );
  return await deps.dbGet(db, `SELECT * FROM user_credit_accounts WHERE user_id = ? LIMIT 1`, [safeUserId]);
}

export async function isTileUnlockedForUser(db, userId, tileKey, deps, options = {}) {
  const key = normalizeTileKey(tileKey);
  if (!key || isFreeCreditTileKey(key)) {
    return true;
  }
  const requested = parseTileKey(key);
  let family = tileFamilyKey(requested);
  let requestedD = Number(requested && requested.d);
  if (
    String(options && options.folder || "").trim().toUpperCase() === "EL"
    && requested
    && Number(requested.z) === 1
    && Number(requested.d) === 1
  ) {
    // EL z001 d002 resolves to the stored d001 file. Authorize it against the
    // user's z001 tile family instead of rejecting the alias as a separate tile.
    family = `x${String(requested.x).padStart(3, "0")}_y${String(requested.y).padStart(3, "0")}_z001`;
    requestedD = 2;
  }
  if (!requested || !family) {
    return true;
  }
  const account = await ensureCreditAccount(db, userId, deps);
  if (isUnlimitedCreditAccount(account)) {
    return true;
  }
  const rows = await deps.dbAll(
    db,
    `
      SELECT tile_key
      FROM user_tile_entitlements
      WHERE user_id = ?
        AND tile_key LIKE ?
    `,
    [String(userId || "").trim(), `${family}_d%`],
  );
  return (rows || []).some((row) => {
    const owned = parseTileKey(row && row.tile_key || "");
    return Boolean(owned && tileFamilyKey(owned) === family && Number(owned.d) <= requestedD);
  });
}

async function backendPricingRecordsForTileKeys(db, tileKeys, qualityMode, deps) {
  await deps.ensureCreditTables(db);
  const keys = normalizeTileKeys(tileKeys);
  if (!keys.length) {
    return [];
  }
  const rows = await deps.dbAll(
    db,
    `
      SELECT tile_key, land_km2, billable_land_km2, base_credits, free_reason
      FROM tile_land_stats
      WHERE tile_key IN (${keys.map(() => "?").join(",")})
    `,
    keys,
  );
  const byKey = new Map((rows || []).map((row) => [String(row && row.tile_key || "").trim(), row]));
  const records = [];
  for (const key of keys) {
    const tile = parseTileKey(key);
    if (!tile) {
      continue;
    }
    const stats = byKey.get(key);
    if (!stats && !isFreeCreditTileKey(key)) {
      return {
        error: "credit_pricing_missing_tile_stats",
        missing_tile_key: key,
      };
    }
    records.push(creditsForTileStats(
      tile,
      stats || { land_km2: 0, billable_land_km2: 0, base_credits: 0, free_reason: "globally_free" },
      qualityMode,
    ));
  }
  return records;
}

async function estimateNewCredits(db, userId, tileKeys, qualityMode, deps) {
  await deps.ensureCreditTables(db);
  const pricingRecords = await backendPricingRecordsForTileKeys(db, tileKeys, qualityMode, deps);
  if (pricingRecords && pricingRecords.error) {
    return pricingRecords;
  }
  const requested = [];
  const families = new Set();
  for (const record of pricingRecords) {
    const parsed = parseTileKey(record && record.tile_key || "");
    const family = tileFamilyKey(parsed);
    if (!parsed || !family) {
      continue;
    }
    requested.push({ record, parsed, family });
    families.add(family);
  }
  const familyList = Array.from(families);
  const rows = familyList.length
    ? await deps.dbAll(
      db,
      `
        SELECT tile_key
        FROM user_tile_entitlements
        WHERE user_id = ?
          AND (${familyList.map(() => "tile_key LIKE ?").join(" OR ")})
      `,
      [String(userId || "").trim(), ...familyList.map((family) => `${family}_d%`)],
    )
    : [];
  const ownedKeys = normalizeTileKeys((rows || []).map((row) => row && row.tile_key || ""));
  const ownedPricing = ownedKeys.length ? await backendPricingRecordsForTileKeys(db, ownedKeys, "full", deps) : [];
  const ownedByFamily = new Map();
  if (Array.isArray(ownedPricing)) {
    for (const ownedRecord of ownedPricing) {
      const parsed = parseTileKey(ownedRecord && ownedRecord.tile_key || "");
      const family = tileFamilyKey(parsed);
      if (!parsed || !family) {
        continue;
      }
      if (!ownedByFamily.has(family)) {
        ownedByFamily.set(family, []);
      }
      ownedByFamily.get(family).push({
        d: Number(parsed.d),
        value: normalizeCreditAmount(ownedRecord && ownedRecord.credits),
      });
    }
  }
  let credits = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;
  const newTiles = [];
  const pricedTiles = [];
  const excludedTiles = [];
  for (const item of requested.sort((a, b) => {
    if (a.family !== b.family) {
      return a.family < b.family ? -1 : 1;
    }
    return Number(a.parsed.d) - Number(b.parsed.d);
  })) {
    const tile = item.record;
    const key = normalizeTileKey(tile.tile_key);
    const globallyFree = isFreeCreditTileKey(key);
    const grossCredits = normalizeCreditAmount(tile.credits);
    const familyEntitlements = ownedByFamily.get(item.family) || [];
    if (!ownedByFamily.has(item.family)) {
      ownedByFamily.set(item.family, familyEntitlements);
    }
    const coveredByFiner = familyEntitlements.some((entry) => Number(entry.d) <= Number(item.parsed.d));
    const coarserCredit = Math.max(
      0,
      ...familyEntitlements
        .filter((entry) => Number(entry.d) > Number(item.parsed.d))
        .map((entry) => normalizeCreditAmount(entry.value)),
    );
    const tileCredits = (globallyFree || coveredByFiner)
      ? 0
      : normalizeCreditAmount(Math.max(0, grossCredits - coarserCredit));
    const breakdownTile = {
      ...tile,
      credits: tileCredits,
      price_eur: tileCredits,
      gross_credits: grossCredits,
      gross_price_eur: grossCredits,
      already_owned: Boolean(coveredByFiner),
      globally_free: Boolean(globallyFree),
    };
    if (coarserCredit > 0) {
      breakdownTile.upgrade_credit_applied = coarserCredit;
    }
    if (coveredByFiner) {
      breakdownTile.free_reason = String(tile.free_reason || "already_unlocked");
    }
    if (tileCredits > 0) {
      paidTileCount += 1;
      credits += tileCredits;
    } else {
      freeTileCount += 1;
    }
    pricedTiles.push(breakdownTile);
    if (coveredByFiner) {
      excludedTiles.push(breakdownTile);
    }
    if (!globallyFree && !coveredByFiner && tileCredits > 0) {
      const newTile = { ...tile, credits: tileCredits };
      if (coarserCredit > 0) {
        newTile.upgrade_credit_applied = coarserCredit;
      }
      newTiles.push(newTile);
      familyEntitlements.push({ d: Number(item.parsed.d), value: grossCredits });
    }
  }
  const totalEur = Math.round(credits * 1_000_000) / 1_000_000;
  return {
    credits: totalEur,
    price_eur: totalEur,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: pricingRecords.length,
    new_tiles: newTiles,
    tiles: pricedTiles,
    excluded_tiles: excludedTiles,
  };
}

export async function unlockTilesForSession(db, userId, qualityMode, tileKeys, resolveId, deps) {
  const safeMode = deps.normalizeQualityMode(qualityMode || "");
  if (safeMode === "preview") {
    return { credits: 0, paid_tile_count: 0, free_tile_count: 0, tile_count: 0 };
  }
  const safeUserId = String(userId || "").trim();
  const estimate = await estimateNewCredits(db, safeUserId, tileKeys, safeMode, deps);
  if (estimate && estimate.error === "credit_pricing_missing_tile_stats") {
    return estimate;
  }
  const requiredCredits = normalizeCreditAmount(estimate.credits);
  const account = await ensureCreditAccount(db, safeUserId, deps);
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
  const insertedTiles = [];
  let actualCredits = 0;
  for (const tile of estimate.new_tiles || []) {
    const tileCredits = normalizeCreditAmount(tile.credits);
    const insert = await deps.dbRun(
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
        tileCredits,
        Math.max(0, Number.parseFloat(tile.land_km2 || 0) || 0),
        Math.max(0, Number.parseFloat(tile.billable_land_km2 || 0) || 0),
        String(tile.stats_source || "backend_d1").trim() || "backend_d1",
        now,
      ],
    );
    if (deps.dbMetaChanges(insert) > 0) {
      insertedTiles.push(tile);
      actualCredits = normalizeCreditAmount(actualCredits + tileCredits);
    }
  }

  if (actualCredits > balance) {
    for (const tile of insertedTiles) {
      await deps.dbRun(
        db,
        `DELETE FROM user_tile_entitlements WHERE user_id = ? AND tile_key = ?`,
        [safeUserId, tile.tile_key],
      );
    }
    return {
      error: "insufficient_credits",
      required_credits: actualCredits,
      balance_credits: balance,
      paid_tile_count: insertedTiles.length,
      tile_count: estimate.tile_count,
    };
  }

  if (actualCredits > 0) {
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
      [actualCredits, actualCredits, now, safeUserId, actualCredits],
    );
    if (deps.dbMetaChanges(update) <= 0) {
      for (const tile of insertedTiles) {
        await deps.dbRun(
          db,
          `DELETE FROM user_tile_entitlements WHERE user_id = ? AND tile_key = ?`,
          [safeUserId, tile.tile_key],
        );
      }
      const fresh = await ensureCreditAccount(db, safeUserId, deps);
      return {
        error: "insufficient_credits",
        required_credits: actualCredits,
        balance_credits: normalizeCreditAmount(fresh && fresh.balance_credits),
        paid_tile_count: insertedTiles.length,
        tile_count: estimate.tile_count,
      };
    }
    const balanceAfter = Math.round((balance - actualCredits) * 1_000_000) / 1_000_000;
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
        -actualCredits,
        balanceAfter,
        JSON.stringify({ resolve_id: String(resolveId || ""), quality_mode: safeMode, tile_count: insertedTiles.length }),
        now,
      ],
    );
  }

  const estimatedPaidCount = Math.max(0, Number.parseInt(estimate.paid_tile_count || 0, 10) || 0);
  const estimatedFreeCount = Math.max(0, Number.parseInt(estimate.free_tile_count || 0, 10) || 0);
  const skippedPaidCount = Math.max(0, estimatedPaidCount - insertedTiles.length);
  return {
    ...estimate,
    credits: actualCredits,
    price_eur: actualCredits,
    paid_tile_count: insertedTiles.length,
    free_tile_count: estimatedFreeCount + skippedPaidCount,
    new_tiles: insertedTiles,
  };
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
      balance_eur: normalizeCreditAmount(account && account.balance_credits),
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
  const tileKeys = requestTileKeysFromBody(body);
  const qualityMode = deps.normalizeQualityMode(body && body.quality_mode || body && body.qualityMode || "full");
  const estimate = await estimateNewCredits(db, auth.user.id, tileKeys, qualityMode, deps);
  if (estimate && estimate.error === "credit_pricing_missing_tile_stats") {
    return deps.json(
      {
        ok: false,
        error: "credit_pricing_missing_tile_stats",
        message: "Planetka EUR pricing metadata is missing for a requested tile.",
        tile_key: String(estimate.missing_tile_key || ""),
      },
      503,
      env,
    );
  }
  const account = await ensureCreditAccount(db, auth.user.id, deps);
  const unlimited = isUnlimitedCreditAccount(account);
  return deps.json(
    {
      ok: true,
      ...estimate,
      credits: estimate.credits,
      price_eur: normalizeCreditAmount(estimate.credits),
      paid_tile_count: estimate.paid_tile_count,
      free_tile_count: estimate.free_tile_count,
      account_type: normalizeAccountType(account && account.account_type),
      unlimited_credits: unlimited,
      balance_credits: normalizeCreditAmount(account && account.balance_credits),
      balance_eur: normalizeCreditAmount(account && account.balance_credits),
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
  const reason = String(body && body.reason || "admin_top_up").trim().slice(0, 160) || "admin_top_up";
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
  if (typeof deps.invalidateAnalyticsSnapshots === "function") {
    try {
      await deps.invalidateAnalyticsSnapshots(env);
    } catch (error) {
      console.warn(
        "planetka.admin.credit_topup_snapshot_invalidate_failed",
        JSON.stringify({
          error: String(error && error.message || "analytics_snapshot_invalidate_failed"),
          user_id: userId,
        }),
      );
    }
  }
  return deps.json(
    {
      ok: true,
      action: "top_up_eur",
      user_id: userId,
      user_email: deps.normalizeEmail(targetUser.email || ""),
      top_up_eur: amount,
      gifted_credits: amount,
      balance_credits: balanceAfter,
      balance_eur: balanceAfter,
      updated_at: now,
    },
    200,
    env,
  );
}
