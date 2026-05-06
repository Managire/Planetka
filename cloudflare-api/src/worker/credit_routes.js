const TILE_KEY_RE = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i;
const ASSET_RE = /^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$/i;
const FREE_D_THRESHOLD = 60;
const ACCOUNT_TYPE_STANDARD = "standard";
const DEFAULT_STARTING_CREDITS = 100.0;
const DATASET_BASE_MPP = 10.0;
const EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2;
const CHECKOUT_BALANCE_TOP_UP_EUR = 10.0;
const STRIPE_MIN_CHECKOUT_AMOUNT_CENTS = 50;
const MONEY_SCALE = 100;
const METRIC_SCALE = 1_000_000;

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

function effectiveBillableLandKm2(parsed, stats, freeReason) {
  if (String(freeReason || "").trim()) {
    return 0;
  }
  const storedBillable = Math.max(0, Number.parseFloat(stats && stats.billable_land_km2 || 0) || 0);
  return storedBillable;
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
  return Math.round((parsed + Number.EPSILON) * MONEY_SCALE) / MONEY_SCALE;
}

function normalizeSignedCreditAmount(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  const sign = parsed < 0 ? -1 : 1;
  return sign * Math.round((Math.abs(parsed) + Number.EPSILON) * MONEY_SCALE) / MONEY_SCALE;
}

function normalizeMetricAmount(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.round(parsed * METRIC_SCALE) / METRIC_SCALE;
}

function centsForEur(value) {
  const amount = normalizeCreditAmount(value);
  if (amount <= 0) {
    return 0;
  }
  return Math.max(0, Math.round(amount * 100));
}

function defaultCheckoutSuccessUrl(env) {
  return String(
    env.STRIPE_CHECKOUT_SUCCESS_URL
    || env.PLANETKA_CHECKOUT_SUCCESS_URL
    || "https://www.planetka.io/payment/success",
  ).trim();
}

function defaultCheckoutCancelUrl(env) {
  return String(
    env.STRIPE_CHECKOUT_CANCEL_URL
    || env.PLANETKA_CHECKOUT_CANCEL_URL
    || "https://www.planetka.io/payment/cancelled",
  ).trim();
}

function checkoutMetadataValue(value, maxLength = 480) {
  return String(value || "").trim().slice(0, Math.max(1, Number(maxLength) || 480));
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
  const statsFreeReason = String(stats && stats.free_reason || "").trim();
  const freeReason = safeMode === "preview"
    ? "preview_quality"
    : (derivedFreeReason || statsFreeReason);
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
    land_km2: normalizeMetricAmount(stats && stats.land_km2),
    billable_land_km2: normalizeMetricAmount(billableLandKm2),
    delivered_mpp: normalizeMetricAmount(mpp),
    detail_ratio: normalizeMetricAmount(detailRatioForTile(tile)),
    price_factor: normalizeMetricAmount(qualityFactor),
    free_reason: freeReason,
    stats_source: String(stats && stats.source || "backend_d1").trim() || "backend_d1",
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
  await deps.dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET
        balance_credits = ROUND(balance_credits * 100.0) / 100.0,
        total_granted_credits = ROUND(total_granted_credits * 100.0) / 100.0,
        total_spent_credits = ROUND(total_spent_credits * 100.0) / 100.0
      WHERE user_id = ?
    `,
    [safeUserId],
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
      SELECT tile_key, land_km2, billable_land_km2, free_reason
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
    const fallbackStats = isFreeCreditTileKey(key)
      ? { land_km2: 0, billable_land_km2: 0, free_reason: "globally_free", source: "global_free_fallback" }
      : { land_km2: 0, billable_land_km2: 0, free_reason: "pricing_metadata_missing", source: "missing_pricing_metadata" };
    records.push(creditsForTileStats(
      tile,
      stats || fallbackStats,
      qualityMode,
    ));
  }
  return records;
}

function pricingMetadataMissingTileKeys(records) {
  const keys = [];
  for (const record of records || []) {
    if (String(record && record.free_reason || "").trim() !== "pricing_metadata_missing") {
      continue;
    }
    const key = normalizeTileKey(record && record.tile_key || "");
    if (key) {
      keys.push(key);
    }
  }
  return Array.from(new Set(keys));
}

function pricingIntegrityWarnings(records) {
  const missingKeys = pricingMetadataMissingTileKeys(records);
  if (!missingKeys.length) {
    return [];
  }
  return [
    {
      code: "pricing_metadata_missing",
      severity: "error",
      tile_keys: missingKeys,
      message: "Backend pricing metadata is missing for actual requested S2 tile keys; affected tiles are not charged.",
    },
  ];
}

async function recordPricingIntegrityWarnings(db, userId, qualityMode, records, deps) {
  const missingKeys = pricingMetadataMissingTileKeys(records);
  if (!missingKeys.length) {
    return;
  }
  console.warn(JSON.stringify({
    event: "planetka_pricing_metadata_missing",
    user_id: String(userId || ""),
    quality_mode: String(qualityMode || ""),
    missing_tile_count: missingKeys.length,
    missing_tile_keys: missingKeys.slice(0, 100),
  }));
  try {
    await deps.dbRun(
      db,
      `
        INSERT INTO pricing_integrity_events (
          id, user_id, quality_mode, issue_code, missing_tile_count, tile_keys_json, created_at
        )
        VALUES (?, ?, ?, 'pricing_metadata_missing', ?, ?, ?)
      `,
      [
        deps.randomToken(16),
        String(userId || "").trim(),
        String(qualityMode || "").trim().toLowerCase(),
        missingKeys.length,
        JSON.stringify(missingKeys.slice(0, 500)),
        deps.nowIso(),
      ],
    );
  } catch (error) {
    console.warn(JSON.stringify({
      event: "planetka_pricing_integrity_event_record_failed",
      user_id: String(userId || ""),
      error: String(error && error.message || "pricing_integrity_event_record_failed"),
    }));
  }
}

async function estimateNewCredits(db, userId, tileKeys, qualityMode, deps) {
  await deps.ensureCreditTables(db);
  const pricingRecords = await backendPricingRecordsForTileKeys(db, tileKeys, qualityMode, deps);
  if (pricingRecords && pricingRecords.error) {
    return pricingRecords;
  }
  await recordPricingIntegrityWarnings(db, userId, qualityMode, pricingRecords, deps);
  const integrityWarnings = pricingIntegrityWarnings(pricingRecords);
  const metadataMissingTileKeys = pricingMetadataMissingTileKeys(pricingRecords);
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
      credits = normalizeCreditAmount(credits + tileCredits);
    } else {
      freeTileCount += 1;
    }
    pricedTiles.push(breakdownTile);
    if (coveredByFiner) {
      excludedTiles.push(breakdownTile);
    }
    if (!globallyFree && !coveredByFiner) {
      const newTile = { ...tile, credits: tileCredits };
      if (coarserCredit > 0) {
        newTile.upgrade_credit_applied = coarserCredit;
      }
      newTiles.push(newTile);
      familyEntitlements.push({ d: Number(item.parsed.d), value: grossCredits });
    }
  }
  const totalEur = normalizeCreditAmount(credits);
  return {
    credits: totalEur,
    price_eur: totalEur,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: pricingRecords.length,
    new_tiles: newTiles,
    tiles: pricedTiles,
    excluded_tiles: excludedTiles,
    integrity_warnings: integrityWarnings,
    metadata_missing_tile_keys: metadataMissingTileKeys,
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
  const balance = normalizeSignedCreditAmount(account && account.balance_credits);
  if (requiredCredits > 0 && balance < 0) {
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

  if (actualCredits > 0 && balance < 0) {
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
      paid_tile_count: insertedTiles.filter((tile) => normalizeCreditAmount(tile && tile.credits) > 0).length,
      tile_count: estimate.tile_count,
    };
  }

  if (actualCredits > 0) {
    const update = await deps.dbRun(
      db,
      `
        UPDATE user_credit_accounts
        SET
          balance_credits = ROUND((balance_credits - ?) * 100.0) / 100.0,
          total_spent_credits = ROUND((total_spent_credits + ?) * 100.0) / 100.0,
          updated_at = ?
        WHERE user_id = ?
      `,
      [actualCredits, actualCredits, now, safeUserId],
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
        balance_credits: normalizeSignedCreditAmount(fresh && fresh.balance_credits),
        paid_tile_count: insertedTiles.filter((tile) => normalizeCreditAmount(tile && tile.credits) > 0).length,
        tile_count: estimate.tile_count,
      };
    }
    const balanceAfter = normalizeSignedCreditAmount(balance - actualCredits);
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
  const insertedPaidCount = insertedTiles.filter((tile) => normalizeCreditAmount(tile && tile.credits) > 0).length;
  const skippedPaidCount = Math.max(0, estimatedPaidCount - insertedPaidCount);
  return {
    ...estimate,
    credits: normalizeCreditAmount(actualCredits),
    price_eur: normalizeCreditAmount(actualCredits),
    paid_tile_count: insertedPaidCount,
    free_tile_count: estimatedFreeCount + skippedPaidCount,
    new_tiles: insertedTiles,
  };
}

export async function addCreditBalance(db, userId, amountEur, reason, metadata, deps) {
  const safeUserId = String(userId || "").trim();
  const amount = normalizeCreditAmount(amountEur);
  if (!safeUserId || amount <= 0) {
    return { error: "missing_positive_amount", balance_credits: 0 };
  }
  const safeReason = String(reason || "balance_top_up").trim().slice(0, 160) || "balance_top_up";
  const now = deps.nowIso();
  await ensureCreditAccount(db, safeUserId, deps);
  await deps.dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET
        balance_credits = ROUND((balance_credits + ?) * 100.0) / 100.0,
        total_granted_credits = ROUND((total_granted_credits + ?) * 100.0) / 100.0,
        updated_at = ?
      WHERE user_id = ?
    `,
    [amount, amount, now, safeUserId],
  );
  const account = await ensureCreditAccount(db, safeUserId, deps);
  const balanceAfter = normalizeSignedCreditAmount(account && account.balance_credits);
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
      safeUserId,
      amount,
      balanceAfter,
      safeReason,
      JSON.stringify(metadata && typeof metadata === "object" ? metadata : {}),
      now,
    ],
  );
  return {
    ok: true,
    added_credits: amount,
    added_eur: amount,
    balance_credits: balanceAfter,
    balance_eur: balanceAfter,
  };
}

export async function grantPaidSceneTileEntitlements(db, userId, qualityMode, tileKeys, resolveId, amountPaidEur, deps) {
  const safeMode = deps.normalizeQualityMode(qualityMode || "");
  if (safeMode !== "full") {
    return { error: "unsupported_quality_mode" };
  }
  const safeUserId = String(userId || "").trim();
  const estimate = await estimateNewCredits(db, safeUserId, tileKeys, safeMode, deps);
  if (estimate && estimate.error) {
    return estimate;
  }
  await ensureCreditAccount(db, safeUserId, deps);
  const now = deps.nowIso();
  const insertedTiles = [];
  let nominalCredits = 0;
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
        "stripe_checkout",
        now,
      ],
    );
    if (deps.dbMetaChanges(insert) > 0) {
      insertedTiles.push(tile);
      nominalCredits = normalizeCreditAmount(nominalCredits + tileCredits);
    }
  }
  const insertedPaidCount = insertedTiles.filter((tile) => normalizeCreditAmount(tile && tile.credits) > 0).length;
  await deps.dbRun(
    db,
    `
      INSERT INTO credit_ledger (
        id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
      )
      VALUES (?, ?, 0, (SELECT balance_credits FROM user_credit_accounts WHERE user_id = ?), 'stripe_scene_purchase', ?, ?)
    `,
    [
      deps.randomToken(16),
      safeUserId,
      safeUserId,
      JSON.stringify({
        resolve_id: String(resolveId || ""),
        quality_mode: safeMode,
        tile_count: insertedTiles.length,
        nominal_eur: nominalCredits,
        paid_eur: normalizeCreditAmount(amountPaidEur),
      }),
      now,
    ],
  );
  return {
    ...estimate,
    credits: 0,
    price_eur: 0,
    paid_eur: normalizeCreditAmount(amountPaidEur),
    nominal_eur: nominalCredits,
    paid_tile_count: insertedPaidCount,
    new_tiles: insertedTiles,
  };
}

async function createStripeCheckoutSession(env, params, deps) {
  const secretKey = deps.requireSecret(env, "STRIPE_SECRET_KEY");
  const metadata = params.metadata && typeof params.metadata === "object" ? params.metadata : {};
  const body = new URLSearchParams();
  body.set("mode", "payment");
  body.set("success_url", defaultCheckoutSuccessUrl(env));
  body.set("cancel_url", defaultCheckoutCancelUrl(env));
  body.set("client_reference_id", checkoutMetadataValue(params.clientReferenceId || ""));
  if (params.customerEmail) {
    body.set("customer_email", checkoutMetadataValue(params.customerEmail || "", 320));
  }
  body.set("line_items[0][quantity]", "1");
  body.set("line_items[0][price_data][currency]", "eur");
  body.set("line_items[0][price_data][unit_amount]", String(Math.max(0, Math.floor(params.amountCents || 0))));
  body.set("line_items[0][price_data][product_data][name]", checkoutMetadataValue(params.productName || "Planetka Data", 320));
  for (const [key, value] of Object.entries(metadata)) {
    const safeKey = String(key || "").trim().slice(0, 40);
    if (!safeKey) {
      continue;
    }
    const safeValue = checkoutMetadataValue(value, 480);
    body.set(`metadata[${safeKey}]`, safeValue);
    body.set(`payment_intent_data[metadata][${safeKey}]`, safeValue);
  }
  const response = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${secretKey}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });
  const responseText = await response.text();
  let payload = {};
  try {
    payload = JSON.parse(responseText || "{}");
  } catch (_error) {
    payload = {};
  }
  if (!response.ok) {
    return {
      error: "stripe_checkout_create_failed",
      status: response.status,
      message: String(payload && payload.error && payload.error.message || responseText || "").slice(0, 500),
    };
  }
  return {
    ok: true,
    session_id: String(payload && payload.id || ""),
    checkout_url: String(payload && payload.url || ""),
  };
}

export async function handleCreditCheckout(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await ensureCreditAccount(db, auth.user.id, deps);
  const body = await deps.parseJson(request);
  const option = String(body && (body.option || body.purchase_type || body.purchaseType) || "scene").trim().toLowerCase();
  const email = deps.normalizeEmail(auth.user && auth.user.email || "");
  const userId = String(auth.user && auth.user.id || "").trim();

  if (option === "balance_10" || option === "top_up_10" || option === "topup_10") {
    const amountEur = CHECKOUT_BALANCE_TOP_UP_EUR;
    const session = await createStripeCheckoutSession(
      env,
      {
        amountCents: centsForEur(amountEur),
        customerEmail: email,
        clientReferenceId: userId,
        productName: "Planetka EUR Balance Top-Up",
        metadata: {
          planetka_purchase_type: "balance_top_up",
          planetka_user_id: userId,
          planetka_email: email,
          planetka_top_up_eur: amountEur.toFixed(2),
        },
      },
      deps,
    );
    if (session.error) {
      return deps.json({ ok: false, ...session }, 502, env);
    }
    return deps.json({ ok: true, option: "balance_10", price_eur: amountEur, ...session }, 200, env);
  }

  const tileKeys = requestTileKeysFromBody(body);
  const qualityMode = deps.normalizeQualityMode(body && body.quality_mode || body && body.qualityMode || "full");
  if (qualityMode !== "full") {
    return deps.json({ ok: false, error: "unsupported_checkout_quality" }, 400, env);
  }
  const estimate = await estimateNewCredits(db, userId, tileKeys, qualityMode, deps);
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
  const priceEur = normalizeCreditAmount(estimate && estimate.credits);
  if (priceEur <= 0) {
    const unlockResult = await unlockTilesForSession(
      db,
      userId,
      qualityMode,
      tileKeys,
      `checkout_no_payment_${deps.randomToken(8)}`,
      deps,
    );
    if (unlockResult && unlockResult.error) {
      return deps.json({ ok: false, ...unlockResult }, 400, env);
    }
    return deps.json(
      {
        ok: true,
        option: "scene",
        no_payment_required: true,
        price_eur: 0,
        paid_tile_count: unlockResult && unlockResult.paid_tile_count || 0,
        tile_count: unlockResult && unlockResult.tile_count || estimate.tile_count,
        message: "This scene has no newly charged Full Quality tiles.",
      },
      200,
      env,
    );
  }
  const amountCents = centsForEur(priceEur);
  if (amountCents < STRIPE_MIN_CHECKOUT_AMOUNT_CENTS) {
    return deps.json(
      {
        ok: false,
        error: "amount_below_stripe_minimum",
        price_eur: priceEur,
        minimum_eur: STRIPE_MIN_CHECKOUT_AMOUNT_CENTS / 100.0,
        message: "This scene price is below Stripe's minimum checkout amount. Add €10 balance instead.",
      },
      400,
      env,
    );
  }

  const normalizedKeys = normalizeTileKeys(tileKeys);
  const session = await createStripeCheckoutSession(
    env,
    {
      amountCents,
      customerEmail: email,
      clientReferenceId: userId,
      productName: "Planetka Full Quality Scene Data",
      metadata: {
        planetka_purchase_type: "scene_tiles",
        planetka_user_id: userId,
        planetka_email: email,
        planetka_quality_mode: "full",
        planetka_tile_keys_json: JSON.stringify(normalizedKeys),
        planetka_price_eur: priceEur.toFixed(2),
        planetka_paid_tile_count: String(Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0)),
      },
    },
    deps,
  );
  if (session.error) {
    return deps.json({ ok: false, ...session }, 502, env);
  }
  return deps.json(
    {
      ok: true,
      option: "scene",
      price_eur: priceEur,
      paid_tile_count: estimate.paid_tile_count,
      tile_count: estimate.tile_count,
      ...session,
    },
    200,
    env,
  );
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
  const previewHold = typeof deps.getPreviewFairUsageHoldForUser === "function"
    ? await deps.getPreviewFairUsageHoldForUser(db, auth.user && auth.user.id)
    : { held: false };
  return deps.json(
    {
      ok: true,
      account_type: normalizeAccountType(account && account.account_type),
      unlimited_credits: isUnlimitedCreditAccount(account),
      balance_credits: normalizeSignedCreditAmount(account && account.balance_credits),
      balance_eur: normalizeSignedCreditAmount(account && account.balance_credits),
      unlocked_tile_count: Number(countRow && countRow.count || 0),
      user_id: String(auth.user.id || ""),
      preview_fair_usage_hold: previewHold,
      previewFairUsageHold: previewHold,
      preview_fair_usage_held: Boolean(previewHold && previewHold.held),
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
      balance_credits: normalizeSignedCreditAmount(account && account.balance_credits),
      balance_eur: normalizeSignedCreditAmount(account && account.balance_credits),
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
  const rawDelta = body && (
    body.delta_credits ?? body.delta_eur ?? body.credits ?? body.amount
  );
  let delta = normalizeSignedCreditAmount(rawDelta);
  const operation = String(body && (body.operation || body.action) || "").trim().toLowerCase();
  if (delta > 0 && ["subtract", "take", "remove", "deduct", "withdraw"].includes(operation)) {
    delta = -delta;
  }
  if (delta === 0) {
    return deps.json({ ok: false, error: "missing_nonzero_credits" }, 400, env);
  }
  const grantedDelta = delta > 0 ? delta : 0;
  const defaultReason = delta < 0 ? "admin_balance_subtract" : "admin_top_up";
  const reason = String(body && body.reason || defaultReason).trim().slice(0, 160) || defaultReason;
  const userId = String(targetUser.id || "").trim();
  const now = deps.nowIso();
  await ensureCreditAccount(db, userId, deps);
  await deps.dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET
        balance_credits = ROUND((balance_credits + ?) * 100.0) / 100.0,
        total_granted_credits = ROUND((total_granted_credits + ?) * 100.0) / 100.0,
        updated_at = ?
      WHERE user_id = ?
    `,
    [delta, grantedDelta, now, userId],
  );
  const account = await ensureCreditAccount(db, userId, deps);
  const balanceAfter = normalizeSignedCreditAmount(account && account.balance_credits);
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
      delta,
      balanceAfter,
      reason,
      JSON.stringify({
        admin_user_id: String(adminUser && adminUser.id || ""),
        admin_email: deps.normalizeEmail(adminUser && adminUser.email || ""),
        operation: delta < 0 ? "subtract" : "top_up",
      }),
      now,
    ],
  );
  if (typeof deps.invalidateAnalyticsSnapshots === "function") {
    try {
      await deps.invalidateAnalyticsSnapshots(env);
    } catch (error) {
      console.warn(
        "planetka.admin.credit_adjustment_snapshot_invalidate_failed",
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
      action: delta < 0 ? "subtract_eur" : "top_up_eur",
      user_id: userId,
      user_email: deps.normalizeEmail(targetUser.email || ""),
      delta_credits: delta,
      delta_eur: delta,
      top_up_eur: delta > 0 ? delta : 0,
      subtracted_eur: delta < 0 ? Math.abs(delta) : 0,
      gifted_credits: delta > 0 ? delta : 0,
      balance_credits: balanceAfter,
      balance_eur: balanceAfter,
      updated_at: now,
    },
    200,
    env,
  );
}
