import { html } from "./responses.js";
import {
  GENERATED_REGION_PACK_CATALOG_VERSION,
  GENERATED_REGION_PACK_DETAILS,
  GENERATED_REGION_PACK_OUTLINES,
  GENERATED_REGION_PACK_PRODUCTS,
  GENERATED_REGION_PACK_TILE_KEYS,
  GENERATED_REGION_PACK_TILE_GROSS_CENTS,
  GENERATED_REGION_PACK_TILE_REFS,
} from "./region_packs.generated.js";

const TILE_KEY_RE = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i;
const ASSET_RE = /^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$/i;
const FREE_D_THRESHOLD = 60;
const ACCOUNT_TYPE_STANDARD = "standard";
const DEFAULT_STARTING_CREDITS = 100.0;
const DATASET_BASE_MPP = 10.0;
const EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2;
const CHECKOUT_BALANCE_TOP_UP_EUR = 10.0;
const STANDARD_QUALITY_UNLOCK_EUR = 50.0;
const STRIPE_MIN_CHECKOUT_AMOUNT_CENTS = 50;
const MONEY_SCALE = 100;
const METRIC_SCALE = 1_000_000;
const REGION_PACK_CATALOG_VERSION = GENERATED_REGION_PACK_CATALOG_VERSION || "gadm_regions_v8";
const SQL_VARIABLE_SAFE_CHUNK_SIZE = 75;
const REGION_PACK_TILE_CHUNK_SIZE = SQL_VARIABLE_SAFE_CHUNK_SIZE;
const REGION_PACK_PAID_Z_LEVELS = [1, 2, 4, 8, 15, 30];
const REGION_PRODUCTS = Array.isArray(GENERATED_REGION_PACK_PRODUCTS) ? GENERATED_REGION_PACK_PRODUCTS : [];

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

function standardQualityUnlockPriceEur(env = {}) {
  const configured = Number.parseFloat(env.STANDARD_QUALITY_UNLOCK_EUR || env.BALANCED_QUALITY_UNLOCK_EUR || "");
  if (Number.isFinite(configured) && configured > 0) {
    return normalizeCreditAmount(configured);
  }
  return STANDARD_QUALITY_UNLOCK_EUR;
}

function defaultCheckoutSuccessUrl(env) {
  return String(
    env.STRIPE_CHECKOUT_SUCCESS_URL
    || env.PLANETKA_CHECKOUT_SUCCESS_URL
    || "https://api.planetka.io/credits/payment-success",
  ).trim();
}

function defaultCheckoutCancelUrl(env) {
  return String(
    env.STRIPE_CHECKOUT_CANCEL_URL
    || env.PLANETKA_CHECKOUT_CANCEL_URL
    || "https://api.planetka.io/credits/payment-cancelled",
  ).trim();
}

function checkoutReturnUrl(baseUrl, sessionPlaceholder = "") {
  const safeBaseUrl = String(baseUrl || "").trim();
  if (!safeBaseUrl || !sessionPlaceholder) {
    return safeBaseUrl;
  }
  const separator = safeBaseUrl.includes("?") ? "&" : "?";
  return `${safeBaseUrl}${separator}session_id=${sessionPlaceholder}`;
}

function clampNumber(value, minValue, maxValue) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return minValue;
  }
  return Math.min(maxValue, Math.max(minValue, parsed));
}

function regionProductById(regionId) {
  const safeId = String(regionId || "").trim().toLowerCase();
  if (!safeId) {
    return null;
  }
  return REGION_PRODUCTS.find((product) => String(product.id || "").toLowerCase() === safeId) || null;
}

function fixedSizeChunks(values, chunkSize = SQL_VARIABLE_SAFE_CHUNK_SIZE) {
  const source = Array.isArray(values) ? values : [];
  const safeSize = Math.max(1, Number.parseInt(chunkSize, 10) || SQL_VARIABLE_SAFE_CHUNK_SIZE);
  const chunks = [];
  for (let index = 0; index < source.length; index += safeSize) {
    chunks.push(source.slice(index, index + safeSize));
  }
  return chunks;
}

function regionProductPublicPayload(product) {
  if (!product) {
    return {};
  }
  return {
    id: String(product.id || ""),
    name: String(product.name || ""),
    type: String(product.type || ""),
    discount_percent: Math.max(0, Number.parseInt(product.discount_percent || 0, 10) || 0),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    included_countries: regionProductIncludedCountries(product),
  };
}

function regionProductPricingSummary(product) {
  if (!product || typeof product !== "object") {
    return null;
  }
  const grossCents = Math.max(0, Number.parseInt(product.gross_cents || 0, 10) || 0);
  const grossEur = grossCents > 0
    ? normalizeCreditAmount(grossCents / 100.0)
    : normalizeCreditAmount(product.gross_eur || 0);
  return {
    gross_cents: grossCents || centsForEur(grossEur),
    gross_eur: grossEur,
    paid_tile_count: Math.max(0, Number.parseInt(product.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(product.free_tile_count || 0, 10) || 0),
    licensable_tile_count: Math.max(0, Number.parseInt(product.licensable_tile_count || 0, 10) || 0),
    tile_count: Math.max(0, Number.parseInt(product.tile_count || 0, 10) || 0),
  };
}

function worldRegionProductSummary() {
  return regionProductPricingSummary(regionProductById("world")) || {
    tile_count: 0,
    licensable_tile_count: 0,
    paid_tile_count: 0,
    gross_eur: 0,
  };
}

function discountedRegionPackAmount(grossEur, discountPercent) {
  const gross = normalizeCreditAmount(grossEur);
  const discount = normalizeCreditAmount(gross * (Math.max(0, Math.min(95, Number.parseInt(discountPercent || 0, 10) || 0)) / 100.0));
  const price = normalizeCreditAmount(Math.max(0, gross - discount));
  return { gross, discount, price };
}

function generatedTileGrossCents(tileKey) {
  const key = normalizeTileKey(tileKey);
  if (!key) {
    return 0;
  }
  return Math.max(0, Number.parseInt(GENERATED_REGION_PACK_TILE_GROSS_CENTS && GENERATED_REGION_PACK_TILE_GROSS_CENTS[key] || 0, 10) || 0);
}

function generatedTileGrossEur(tileKey) {
  return normalizeCreditAmount(generatedTileGrossCents(tileKey) / 100.0);
}

function countryNameByRegionId(regionId) {
  const product = regionProductById(regionId);
  return product && String(product.type || "") === "country" ? String(product.name || "").trim() : "";
}

function regionProductIncludedCountries(product) {
  if (!product) {
    return [];
  }
  const id = String(product.id || "").trim();
  const generated = GENERATED_REGION_PACK_DETAILS[id];
  if (generated && Array.isArray(generated.countries)) {
    return generated.countries
      .map((entry) => String(entry && (entry.NAME_1 || entry.name || entry.COUNTRY) || "").trim())
      .filter(Boolean);
  }
  if (String(product.type || "") === "country") {
    const name = String(product.name || "").trim();
    return name ? [name] : [];
  }
  if (!Array.isArray(product.countries)) {
    return [];
  }
  return product.countries
    .map((countryId) => countryNameByRegionId(countryId))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
}

function bboxArea(product) {
  const bbox = product && product.bbox || [];
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return Number.POSITIVE_INFINITY;
  }
  const width = Math.max(0, Number(bbox[2]) - Number(bbox[0]));
  const height = Math.max(0, Number(bbox[3]) - Number(bbox[1]));
  return width * height;
}

function productSpecificityScore(product) {
  const tileCount = Number.parseInt(product && product.tile_count || 0, 10) || 0;
  if (tileCount > 0) {
    return tileCount;
  }
  return bboxArea(product);
}

function pointInPolygonRing(lon, lat, ring) {
  if (!Array.isArray(ring) || ring.length < 4) {
    return false;
  }
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const currentPoint = Array.isArray(ring[index]) ? ring[index] : [];
    const previousPoint = Array.isArray(ring[previous]) ? ring[previous] : [];
    const xi = Number(currentPoint[0]);
    const yi = Number(currentPoint[1]);
    const xj = Number(previousPoint[0]);
    const yj = Number(previousPoint[1]);
    if (![xi, yi, xj, yj].every(Number.isFinite)) {
      continue;
    }
    const intersects = ((yi > lat) !== (yj > lat))
      && (lon < ((xj - xi) * (lat - yi)) / ((yj - yi) || Number.EPSILON) + xi);
    if (intersects) {
      inside = !inside;
    }
  }
  return inside;
}

function regionProductOutlines(product) {
  const detail = GENERATED_REGION_PACK_DETAILS[String(product && product.id || "")] || {};
  if (Array.isArray(detail.outlines) && detail.outlines.length) {
    return detail.outlines;
  }
  const refs = Array.isArray(detail.outline_refs) ? detail.outline_refs : [];
  const outlines = [];
  for (const ref of refs) {
    const outline = GENERATED_REGION_PACK_OUTLINES[String(ref || "")];
    if (outline) {
      outlines.push(outline);
    }
  }
  return outlines;
}

function pointInGeneratedRegionOutlines(product, latitudeDeg, longitudeDeg) {
  const outlines = regionProductOutlines(product);
  if (!outlines.length) {
    return null;
  }
  const lon = clampNumber(longitudeDeg, -180.0, 180.0);
  const lat = clampNumber(latitudeDeg, -90.0, 90.0);
  for (const outline of outlines) {
    const polygons = Array.isArray(outline && outline.polygons) ? outline.polygons : [];
    for (const ring of polygons) {
      if (pointInPolygonRing(lon, lat, ring)) {
        return true;
      }
    }
  }
  return false;
}

function pointInRegionProduct(product, latitudeDeg, longitudeDeg) {
  const bbox = product && product.bbox || [];
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return false;
  }
  const lon = clampNumber(longitudeDeg, -180.0, 180.0);
  const lat = clampNumber(latitudeDeg, -90.0, 90.0);
  const inBBox = lon >= Number(bbox[0]) && lon <= Number(bbox[2]) && lat >= Number(bbox[1]) && lat <= Number(bbox[3]);
  if (!inBBox) {
    return false;
  }
  const inOutlines = pointInGeneratedRegionOutlines(product, lat, lon);
  return inOutlines === null ? true : inOutlines;
}

function suggestedRegionProductsForPoint(latitudeDeg, longitudeDeg) {
  const matches = REGION_PRODUCTS.filter((product) => pointInRegionProduct(product, latitudeDeg, longitudeDeg));
  const selected = [];
  const seen = new Set();
  const addProduct = (product) => {
    const id = String(product && product.id || "");
    if (!id || seen.has(id)) {
      return;
    }
    seen.add(id);
    selected.push(product);
  };
  const countryMatches = matches
    .filter((product) => String(product.type || "") === "country")
    .sort((a, b) => bboxArea(a) - bboxArea(b));
  const country = countryMatches.length ? countryMatches[0] : null;
  if (countryMatches.length) {
    addProduct(country);
  }
  const macroSource = country
    ? REGION_PRODUCTS.filter((product) => (
      String(product.type || "") === "macro_region"
      && Array.isArray(product.countries)
      && product.countries.includes(String(country.id || ""))
    ))
    : matches.filter((product) => String(product.type || "") === "macro_region");
  const macroMatches = macroSource.sort((a, b) => (
    productSpecificityScore(a) - productSpecificityScore(b)
    || bboxArea(a) - bboxArea(b)
  ));
  for (const product of macroMatches.slice(0, 2)) {
    addProduct(product);
  }
  const continent = matches.find((product) => String(product.type || "") === "continent");
  if (continent) {
    addProduct(continent);
  }
  return selected.slice(0, 4);
}

function paidDLevelsForRegionZ(zValue) {
  const z = Math.max(1, Number.parseInt(zValue, 10) || 1);
  // A finer entitlement grants access to all coarser d-levels in the same tile
  // family, so region packs only need the finest paid d-level per z footprint.
  return z > 0 && z < FREE_D_THRESHOLD ? [z] : [];
}

function regionTileKey(x, y, z, d) {
  return `x${String(x).padStart(3, "0")}_y${String(y).padStart(3, "0")}_z${String(z).padStart(3, "0")}_d${String(d).padStart(3, "0")}`;
}

function regionProductTileKeys(product, seenProductIds = new Set()) {
  const productId = String(product && product.id || "").trim();
  if (productId) {
    if (seenProductIds.has(productId)) {
      return [];
    }
    seenProductIds.add(productId);
  }
  const generatedKeys = GENERATED_REGION_PACK_TILE_KEYS[productId];
  const generatedRefs = GENERATED_REGION_PACK_TILE_REFS[productId];
  if (Array.isArray(generatedRefs) && generatedRefs.length) {
    const keys = [];
    const seenKeys = new Set();
    for (const ref of generatedRefs) {
      const refProduct = regionProductById(ref);
      for (const key of regionProductTileKeys(refProduct, seenProductIds)) {
        if (seenKeys.has(key)) {
          continue;
        }
        seenKeys.add(key);
        keys.push(key);
      }
    }
    for (const key of normalizeTileKeys(generatedKeys || [])) {
      if (seenKeys.has(key)) {
        continue;
      }
      seenKeys.add(key);
      keys.push(key);
    }
    return keys;
  }
  if (Array.isArray(generatedKeys) && generatedKeys.length) {
    return normalizeTileKeys(generatedKeys);
  }
  const bbox = product && product.bbox || [];
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return [];
  }
  const minLon = clampNumber(Math.min(Number(bbox[0]), Number(bbox[2])), -180.0, 180.0);
  const maxLon = clampNumber(Math.max(Number(bbox[0]), Number(bbox[2])), -180.0, 180.0);
  const minLat = clampNumber(Math.min(Number(bbox[1]), Number(bbox[3])), -90.0, 90.0);
  const maxLat = clampNumber(Math.max(Number(bbox[1]), Number(bbox[3])), -90.0, 90.0);
  const minX = Math.max(0, Math.min(359, Math.floor(minLon + 180.0)));
  const maxX = Math.max(0, Math.min(359, Math.ceil(maxLon + 180.0) - 1));
  const minY = Math.max(0, Math.min(179, Math.floor(minLat + 90.0)));
  const maxY = Math.max(0, Math.min(179, Math.ceil(maxLat + 90.0) - 1));
  if (maxX < minX || maxY < minY) {
    return [];
  }
  const keys = [];
  const seen = new Set();
  for (const z of REGION_PACK_PAID_Z_LEVELS) {
    const startX = Math.floor(minX / z) * z;
    const endX = Math.floor(maxX / z) * z;
    const startY = Math.floor(minY / z) * z;
    const endY = Math.floor(maxY / z) * z;
    const dLevels = paidDLevelsForRegionZ(z);
    for (let x = startX; x <= endX; x += z) {
      for (let y = startY; y <= endY; y += z) {
        if (x < 0 || x > 359 || y < 0 || y > 179) {
          continue;
        }
        for (const d of dLevels) {
          const key = regionTileKey(x, y, z, d);
          if (seen.has(key)) {
            continue;
          }
          seen.add(key);
          keys.push(key);
        }
      }
    }
  }
  return keys;
}

function tileFamilyFromKey(tileKey) {
  return tileFamilyKey(parseTileKey(tileKey));
}

function chunkTileKeysByFamily(tileKeys, maxChunkSize = REGION_PACK_TILE_CHUNK_SIZE) {
  const keys = normalizeTileKeys(tileKeys).sort((a, b) => {
    const familyA = tileFamilyFromKey(a);
    const familyB = tileFamilyFromKey(b);
    if (familyA !== familyB) {
      return familyA < familyB ? -1 : 1;
    }
    const tileA = parseTileKey(a);
    const tileB = parseTileKey(b);
    return Number(tileA && tileA.d || 0) - Number(tileB && tileB.d || 0);
  });
  const chunks = [];
  let chunk = [];
  let currentFamily = "";
  for (const key of keys) {
    const family = tileFamilyFromKey(key);
    if (chunk.length >= maxChunkSize && family !== currentFamily) {
      chunks.push(chunk);
      chunk = [];
    }
    chunk.push(key);
    currentFamily = family;
  }
  if (chunk.length) {
    chunks.push(chunk);
  }
  return chunks;
}

function combineIntegrityWarnings(warnings) {
  const byCode = new Map();
  for (const warning of warnings || []) {
    if (!warning || typeof warning !== "object") {
      continue;
    }
    const code = String(warning.code || "").trim() || "warning";
    if (!byCode.has(code)) {
      byCode.set(code, { ...warning, tile_keys: [] });
    }
    const target = byCode.get(code);
    const keys = Array.isArray(warning.tile_keys) ? warning.tile_keys : [];
    target.tile_keys = Array.from(new Set([...(target.tile_keys || []), ...keys]));
  }
  return Array.from(byCode.values());
}

async function estimateNewCreditsChunked(db, userId, tileKeys, qualityMode, deps, options = {}) {
  const chunks = chunkTileKeysByFamily(tileKeys);
  const includeRows = Boolean(options && options.includeRows);
  const aggregate = {
    credits: 0,
    price_eur: 0,
    paid_tile_count: 0,
    free_tile_count: 0,
    tile_count: 0,
    new_tiles: [],
    tiles: [],
    excluded_tiles: [],
    integrity_warnings: [],
    metadata_missing_tile_keys: [],
  };
  for (const chunk of chunks) {
    const estimate = await estimateNewCredits(db, userId, chunk, qualityMode, deps);
    if (estimate && estimate.error) {
      return estimate;
    }
    aggregate.credits = normalizeCreditAmount(aggregate.credits + normalizeCreditAmount(estimate && estimate.credits));
    aggregate.price_eur = aggregate.credits;
    aggregate.paid_tile_count += Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0);
    aggregate.free_tile_count += Math.max(0, Number.parseInt(estimate && estimate.free_tile_count || 0, 10) || 0);
    aggregate.tile_count += Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0);
    aggregate.new_tiles.push(...(Array.isArray(estimate && estimate.new_tiles) ? estimate.new_tiles : []));
    aggregate.excluded_tiles.push(...(Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles : []));
    aggregate.integrity_warnings.push(...(Array.isArray(estimate && estimate.integrity_warnings) ? estimate.integrity_warnings : []));
    aggregate.metadata_missing_tile_keys.push(...(Array.isArray(estimate && estimate.metadata_missing_tile_keys) ? estimate.metadata_missing_tile_keys : []));
    if (includeRows) {
      aggregate.tiles.push(...(Array.isArray(estimate && estimate.tiles) ? estimate.tiles : []));
    }
  }
  aggregate.integrity_warnings = combineIntegrityWarnings(aggregate.integrity_warnings);
  aggregate.metadata_missing_tile_keys = Array.from(new Set(aggregate.metadata_missing_tile_keys));
  return aggregate;
}

async function estimateRegionPackSummary(db, userId, product, deps) {
  await deps.ensureCreditTables(db);
  const summary = regionProductPricingSummary(product);
  if (!summary) {
    return { error: "missing_region_pack_summary" };
  }
  const account = await ensureCreditAccount(db, userId, deps);
  if (isWorldFullQualityUnlocked(account)) {
    return {
      ok: true,
      summary_estimate: true,
      world_full_quality_unlocked: true,
      region_pack: regionProductPublicPayload(product),
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      discount_percent: Math.max(0, Math.min(95, Number.parseInt(product && product.discount_percent || 0, 10) || 0)),
      gross_eur: 0,
      gross_price_eur: 0,
      discount_eur: 0,
      credits: 0,
      price_eur: 0,
      paid_tile_count: 0,
      free_tile_count: summary.tile_count,
      tile_count: summary.tile_count,
      new_tile_count: 0,
      new_tiles: [],
      excluded_tiles: new Array(summary.licensable_tile_count).fill(null),
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
      tiles: [],
    };
  }
  const tileKeys = regionProductTileKeys(product);
  const discountPercent = Math.max(0, Math.min(95, Number.parseInt(product && product.discount_percent || 0, 10) || 0));
  const ownedRows = await deps.dbAll(
    db,
    `
      SELECT tile_key
      FROM user_tile_entitlements
      WHERE user_id = ?
    `,
    [String(userId || "").trim()],
  );
  const ownedByFamily = new Map();
  for (const row of ownedRows || []) {
    const owned = parseTileKey(row && row.tile_key || "");
    const family = tileFamilyKey(owned);
    if (!owned || !family) {
      continue;
    }
    if (!ownedByFamily.has(family)) {
      ownedByFamily.set(family, []);
    }
    ownedByFamily.get(family).push({ key: owned.key, d: Number(owned.d) });
  }
  const coveredKeys = [];
  const upgradeOwnedKeys = [];
  let alreadyLicencedCount = 0;
  let newLicensableCount = 0;
  for (const key of tileKeys) {
    const parsed = parseTileKey(key);
    const family = tileFamilyKey(parsed);
    if (!parsed || !family || isFreeCreditTileKey(key)) {
      continue;
    }
    const entries = ownedByFamily.get(family) || [];
    const coveredByFiner = entries.some((entry) => Number(entry.d) <= Number(parsed.d));
    if (coveredByFiner) {
      alreadyLicencedCount += 1;
      coveredKeys.push(key);
      continue;
    }
    newLicensableCount += 1;
    const coarserEntries = entries.filter((entry) => Number(entry.d) > Number(parsed.d));
    for (const entry of coarserEntries) {
      upgradeOwnedKeys.push(entry.key);
    }
  }

  let coveredGrossEur = 0;
  let coveredPaidTileCount = 0;
  if (coveredKeys.length && coveredKeys.length >= summary.licensable_tile_count) {
    coveredGrossEur = summary.gross_eur;
    coveredPaidTileCount = summary.paid_tile_count;
  } else if (coveredKeys.length) {
    let coveredCents = 0;
    for (const key of coveredKeys) {
      const cents = generatedTileGrossCents(key);
      coveredCents += cents;
      if (cents > 0) {
        coveredPaidTileCount += 1;
      }
    }
    coveredGrossEur = normalizeCreditAmount(coveredCents / 100.0);
  }

  let upgradeCreditEur = 0;
  const uniqueUpgradeKeys = normalizeTileKeys(upgradeOwnedKeys);
  if (uniqueUpgradeKeys.length) {
    let upgradeCents = 0;
    for (const key of uniqueUpgradeKeys) {
      upgradeCents += generatedTileGrossCents(key);
    }
    upgradeCreditEur = normalizeCreditAmount(upgradeCents / 100.0);
  }

  const grossEur = normalizeCreditAmount(Math.max(0, summary.gross_eur - coveredGrossEur - upgradeCreditEur));
  const amounts = discountedRegionPackAmount(grossEur, discountPercent);
  const paidTileCount = Math.max(0, summary.paid_tile_count - coveredPaidTileCount);
  const freeTileCount = Math.max(0, summary.tile_count - paidTileCount);
  return {
    ok: true,
    summary_estimate: true,
    region_pack: regionProductPublicPayload(product),
    region_pack_id: String(product.id || ""),
    region_pack_name: String(product.name || ""),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    discount_percent: discountPercent,
    gross_eur: amounts.gross,
    gross_price_eur: amounts.gross,
    discount_eur: amounts.discount,
    credits: amounts.price,
    price_eur: amounts.price,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: summary.tile_count,
    new_tile_count: newLicensableCount,
    new_tiles: [],
    excluded_tiles: new Array(alreadyLicencedCount).fill(null),
    integrity_warnings: [],
    metadata_missing_tile_keys: [],
    tiles: [],
  };
}

async function estimateRegionPack(db, userId, product, deps, options = {}) {
  if (!product) {
    return { error: "unknown_region_pack" };
  }
  if (!Boolean(options && options.includeRows) && !Boolean(options && options.forceDetailed)) {
    const summaryEstimate = await estimateRegionPackSummary(db, userId, product, deps);
    if (summaryEstimate && !summaryEstimate.error) {
      return summaryEstimate;
    }
  }
  const tileKeys = regionProductTileKeys(product);
  const gross = await estimateNewCreditsChunked(db, userId, tileKeys, "full", deps, {
    includeRows: Boolean(options && options.includeRows),
  });
  if (gross && gross.error) {
    return gross;
  }
  const grossEur = normalizeCreditAmount(gross && gross.credits);
  const discountPercent = Math.max(0, Math.min(95, Number.parseInt(product.discount_percent || 0, 10) || 0));
  const amounts = discountedRegionPackAmount(grossEur, discountPercent);
  const discountEur = amounts.discount;
  const priceEur = amounts.price;
  return {
    ok: true,
    region_pack: regionProductPublicPayload(product),
    region_pack_id: String(product.id || ""),
    region_pack_name: String(product.name || ""),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    discount_percent: discountPercent,
    gross_eur: grossEur,
    gross_price_eur: grossEur,
    discount_eur: discountEur,
    credits: priceEur,
    price_eur: priceEur,
    paid_tile_count: Math.max(0, Number.parseInt(gross && gross.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(gross && gross.free_tile_count || 0, 10) || 0),
    tile_count: Math.max(0, Number.parseInt(gross && gross.tile_count || 0, 10) || 0),
    new_tile_count: Array.isArray(gross && gross.new_tiles) ? gross.new_tiles.length : 0,
    new_tiles: Array.isArray(gross && gross.new_tiles) ? gross.new_tiles : [],
    excluded_tiles: Array.isArray(gross && gross.excluded_tiles) ? gross.excluded_tiles : [],
    integrity_warnings: Array.isArray(gross && gross.integrity_warnings) ? gross.integrity_warnings : [],
    metadata_missing_tile_keys: Array.isArray(gross && gross.metadata_missing_tile_keys) ? gross.metadata_missing_tile_keys : [],
    tiles: Array.isArray(gross && gross.tiles) ? gross.tiles : [],
  };
}

function purchaseMetadataJson(metadata) {
  try {
    return JSON.stringify(metadata && typeof metadata === "object" ? metadata : {});
  } catch (error) {
    return JSON.stringify({ metadata_error: String(error && error.message || "metadata_json_failed") });
  }
}

function compactPurchaseTile(row, status = "new") {
  const key = normalizeTileKey(row && row.tile_key || "");
  if (!key) {
    return null;
  }
  return {
    tile_key: key,
    tile_status: String(status || "new").trim() || "new",
    price_eur: normalizeCreditAmount(row && (row.credits ?? row.price_eur)),
    gross_price_eur: normalizeCreditAmount(row && (row.gross_credits ?? row.gross_price_eur ?? row.credits ?? row.price_eur)),
    land_km2: normalizeMetricAmount(row && row.land_km2),
    billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
  };
}

async function recordPurchaseHistory(db, details, deps) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(details && details.user_id || details && details.userId || "").trim();
  const purchaseType = String(details && details.purchase_type || details && details.purchaseType || "").trim().toLowerCase();
  if (!safeUserId || !purchaseType) {
    return { error: "missing_purchase_history_identity" };
  }
  const stripeSessionId = String(details && details.stripe_session_id || details && details.stripeSessionId || "").trim();
  if (stripeSessionId) {
    const existing = await deps.dbGet(
      db,
      `SELECT id FROM purchase_history WHERE stripe_session_id = ? LIMIT 1`,
      [stripeSessionId],
    );
    if (existing && existing.id) {
      return { ok: true, duplicate: true, purchase_id: String(existing.id || "") };
    }
  }
  const purchaseId = String(details && details.id || "").trim() || deps.randomToken(16);
  const createdAt = String(details && details.created_at || "").trim() || deps.nowIso();
  const tileRows = Array.isArray(details && details.tiles) ? details.tiles : [];
  const normalizedTiles = tileRows
    .map((tile) => compactPurchaseTile(tile, tile && (tile.tile_status || tile.status) || "new"))
    .filter(Boolean);
  await deps.dbRun(
    db,
    `
      INSERT INTO purchase_history (
        id,
        user_id,
        user_email,
        purchase_type,
        stripe_session_id,
        stripe_payment_intent_id,
        currency,
        amount_paid_eur,
        nominal_eur,
        gross_eur,
        discount_eur,
        discount_percent,
        quality_mode,
        region_pack_id,
        region_pack_name,
        region_pack_type,
        catalog_version,
        tile_count_total,
        tile_count_new,
        tile_count_already_licenced,
        metadata_json,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, 'eur', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      purchaseId,
      safeUserId,
      String(details && details.user_email || details && details.userEmail || "").trim().toLowerCase(),
      purchaseType,
      stripeSessionId || null,
      String(details && details.stripe_payment_intent_id || details && details.stripePaymentIntentId || "").trim() || null,
      normalizeCreditAmount(details && details.amount_paid_eur),
      normalizeCreditAmount(details && details.nominal_eur),
      normalizeCreditAmount(details && details.gross_eur),
      normalizeCreditAmount(details && details.discount_eur),
      Math.max(0, Number.parseInt(details && details.discount_percent || 0, 10) || 0),
      String(details && details.quality_mode || details && details.qualityMode || "").trim().toLowerCase(),
      String(details && details.region_pack_id || details && details.regionPackId || "").trim(),
      String(details && details.region_pack_name || details && details.regionPackName || "").trim(),
      String(details && details.region_pack_type || details && details.regionPackType || "").trim(),
      String(details && details.catalog_version || details && details.catalogVersion || "").trim(),
      Math.max(0, Number.parseInt(details && details.tile_count_total || 0, 10) || 0),
      Math.max(0, Number.parseInt(details && details.tile_count_new || normalizedTiles.length, 10) || 0),
      Math.max(0, Number.parseInt(details && details.tile_count_already_licenced || 0, 10) || 0),
      purchaseMetadataJson(details && details.metadata),
      createdAt,
    ],
  );
  for (const tile of normalizedTiles) {
    await deps.dbRun(
      db,
      `
        INSERT OR IGNORE INTO purchase_history_tiles (
          purchase_id,
          tile_key,
          tile_status,
          price_eur,
          gross_price_eur,
          land_km2,
          billable_land_km2,
          quality_mode,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        purchaseId,
        tile.tile_key,
        tile.tile_status,
        normalizeCreditAmount(tile.price_eur),
        normalizeCreditAmount(tile.gross_price_eur),
        normalizeMetricAmount(tile.land_km2),
        normalizeMetricAmount(tile.billable_land_km2),
        String(details && details.quality_mode || details && details.qualityMode || "full").trim().toLowerCase() || "full",
        createdAt,
      ],
    );
  }
  return { ok: true, purchase_id: purchaseId, tile_count: normalizedTiles.length };
}

async function recordPurchaseHistoryBestEffort(db, details, deps) {
  try {
    return await recordPurchaseHistory(db, details, deps);
  } catch (error) {
    const errorMessage = error && error.stack ? String(error.stack) : String(error || "unknown_error");
    console.error("planetka.purchase_history_record_failed", JSON.stringify({
      purchase_type: String(details && details.purchase_type || details && details.purchaseType || ""),
      user_id: String(details && details.user_id || details && details.userId || ""),
      stripe_session_id: String(details && details.stripe_session_id || details && details.stripeSessionId || ""),
      error: errorMessage.slice(0, 1200),
    }));
    return { ok: false, error: "purchase_history_record_failed" };
  }
}

function escapeHtmlText(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function jsonForInlineScript(value) {
  return JSON.stringify(value || {})
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function parseRegionMapTile(row) {
  const parsed = parseTileKey(row && row.tile_key || "");
  if (!parsed) {
    return null;
  }
  return parsed;
}

function allocatedRegionPackTileRows(estimate) {
  const rows = Array.isArray(estimate && estimate.tiles) ? estimate.tiles : [];
  const paid = [];
  let normalCentsTotal = 0;
  for (const row of rows) {
    const normalCents = centsForEur(row && (row.credits ?? row.price_eur));
    if (normalCents <= 0 || Boolean(row && row.already_owned) || Boolean(row && row.globally_free)) {
      continue;
    }
    normalCentsTotal += normalCents;
    paid.push({ row, normalCents });
  }
  const targetCents = centsForEur(estimate && estimate.price_eur);
  const allocations = new Map();
  if (normalCentsTotal > 0 && targetCents > 0 && paid.length) {
    let allocated = 0;
    const sortable = paid.map((entry, index) => {
      const raw = (entry.normalCents * targetCents) / normalCentsTotal;
      const floor = Math.floor(raw);
      allocated += floor;
      return {
        index,
        row: entry.row,
        cents: floor,
        remainder: raw - floor,
      };
    });
    sortable.sort((a, b) => {
      if (b.remainder !== a.remainder) {
        return b.remainder - a.remainder;
      }
      return a.index - b.index;
    });
    let remaining = Math.max(0, targetCents - allocated);
    for (const entry of sortable) {
      if (remaining <= 0) {
        break;
      }
      entry.cents += 1;
      remaining -= 1;
    }
    for (const entry of sortable) {
      allocations.set(normalizeTileKey(entry.row && entry.row.tile_key || ""), entry.cents);
    }
  }

  return rows.map((row) => {
    const parsed = parseRegionMapTile(row);
    const key = normalizeTileKey(row && row.tile_key || "");
    const allocatedCents = Math.max(0, Number(allocations.get(key) || 0) || 0);
    const normalCents = centsForEur(row && (row.credits ?? row.price_eur));
    const grossCents = centsForEur(row && (row.gross_credits ?? row.gross_price_eur ?? row.credits ?? row.price_eur));
    let status = "free";
    if (Boolean(row && row.already_owned)) {
      status = "licenced";
    } else if (allocatedCents > 0) {
      status = "new";
    }
    return {
      tile_key: key,
      x: parsed ? parsed.x : null,
      y: parsed ? parsed.y : null,
      z: parsed ? parsed.z : null,
      d: parsed ? parsed.d : null,
      lon_min: parsed ? parsed.x - 180 : null,
      lon_max: parsed ? parsed.x - 180 + parsed.z : null,
      lat_min: parsed ? parsed.y - 90 : null,
      lat_max: parsed ? parsed.y - 90 + parsed.z : null,
      status,
      price_eur: normalizeCreditAmount(allocatedCents / 100.0),
      normal_price_eur: normalizeCreditAmount(normalCents / 100.0),
      original_price_eur: normalizeCreditAmount(grossCents / 100.0),
      land_km2: normalizeMetricAmount(row && row.land_km2),
      billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
      free_reason: String(row && row.free_reason || "").trim(),
      already_licenced: Boolean(row && row.already_owned),
      globally_free: Boolean(row && row.globally_free),
    };
  }).filter((row) => row.tile_key && Number.isFinite(row.x) && Number.isFinite(row.y) && Number.isFinite(row.z));
}

function regionMapBounds(product, detail, tileRows) {
  const bounds = detail && Array.isArray(detail.bounds) ? detail.bounds : null;
  if (bounds && bounds.length >= 4) {
    return {
      min_lon: Number(bounds[0]),
      min_lat: Number(bounds[1]),
      max_lon: Number(bounds[2]),
      max_lat: Number(bounds[3]),
    };
  }
  const bbox = product && Array.isArray(product.bbox) ? product.bbox : null;
  if (bbox && bbox.length >= 4) {
    return {
      min_lon: Number(bbox[0]),
      min_lat: Number(bbox[1]),
      max_lon: Number(bbox[2]),
      max_lat: Number(bbox[3]),
    };
  }
  const rows = Array.isArray(tileRows) ? tileRows : [];
  if (!rows.length) {
    return { min_lon: -10, min_lat: 35, max_lon: 30, max_lat: 47.5 };
  }
  return rows.reduce((acc, row) => ({
    min_lon: Math.min(acc.min_lon, Number(row.lon_min)),
    min_lat: Math.min(acc.min_lat, Number(row.lat_min)),
    max_lon: Math.max(acc.max_lon, Number(row.lon_max)),
    max_lat: Math.max(acc.max_lat, Number(row.lat_max)),
  }), {
    min_lon: 180,
    min_lat: 90,
    max_lon: -180,
    max_lat: -90,
  });
}

function buildRegionPackMapData(product, estimate) {
  const id = String(product && product.id || "");
  const detail = GENERATED_REGION_PACK_DETAILS[id] || {};
  const tileRows = allocatedRegionPackTileRows(estimate);
  const countries = regionProductIncludedCountries(product);
  const levels = Array.from(new Set(tileRows.map((row) => row.z).filter((z) => Number.isFinite(z))))
    .sort((a, b) => a - b);
  return {
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    generated_detail_available: Boolean(detail && Object.keys(detail).length),
    region_pack: regionProductPublicPayload(product),
    included_countries: countries,
    outlines: regionProductOutlines(product),
    bounds: regionMapBounds(product, detail, tileRows),
    levels,
    summary: {
      new_tiles: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
      full_price_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
      discount_percent: Math.max(0, Number.parseInt(estimate && estimate.discount_percent || 0, 10) || 0),
      discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
      price_eur: normalizeCreditAmount(estimate && estimate.price_eur),
      tile_price_sum_eur: normalizeCreditAmount(tileRows.reduce((total, row) => total + normalizeCreditAmount(row.price_eur), 0)),
    },
    tiles: tileRows,
  };
}

async function ensureRegionPackDetailTokenTable(db, deps) {
  await deps.ensureCreditTables(db);
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS region_pack_detail_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        region_pack_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await deps.dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_region_pack_detail_tokens_expires ON region_pack_detail_tokens(expires_at)`,
  );
}

function regionPackDetailTokenTtlMinutes(env = {}) {
  const configured = Number.parseFloat(env.REGION_PACK_DETAIL_TOKEN_TTL_MINUTES || "");
  if (Number.isFinite(configured) && configured > 0) {
    return Math.min(24 * 60, Math.max(5, configured));
  }
  return 60;
}

function addMinutesIsoFromDeps(deps, minutes) {
  const base = Date.parse(String(deps.nowIso && deps.nowIso() || ""));
  const nowMs = Number.isFinite(base) ? base : Date.now();
  return new Date(nowMs + (Math.max(1, Number(minutes) || 1) * 60 * 1000)).toISOString();
}

function regionPackMapHtml(data) {
  const pack = data && data.region_pack || {};
  const name = String(pack.name || "Region Pack").trim() || "Region Pack";
  const countries = Array.isArray(data && data.included_countries) ? data.included_countries : [];
  const summary = data && data.summary || {};
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka ${escapeHtmlText(name)} Pack Detail</title>
<style>
:root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--new:#e45745;--licenced:#e2bc49;--free:#69707a;--country:#2a3748;--country-line:#98b4d8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:22px;margin-top:4px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select{background:#262626;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px}svg{width:100%;height:auto;background:#0d1118;border:1px solid var(--line);border-radius:10px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0}.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}.new{background:var(--new)}.licenced{background:var(--licenced)}.free{background:var(--free)}
.countries{columns:2;column-gap:26px}.countries div{break-inside:avoid;margin:2px 0}.small{font-size:13px}
</style>
</head>
<body>
<main>
<h1>${escapeHtmlText(name)} Full Quality Pack</h1>
<p class="muted">This is the same backend estimate used by Blender. Tile prices shown on hover are user-specific: already licenced tiles are €0.00.</p>
<section class="cards">
<div class="card"><span>New Tiles</span><b>${Number(summary.new_tiles || 0)}</b></div>
<div class="card"><span>Total Tiles</span><b>${Number(summary.total_tiles || 0)}</b></div>
<div class="card"><span>Full Price</span><b>€${Number(summary.full_price_eur || 0).toFixed(2)}</b></div>
<div class="card"><span>Volume Discount</span><b>${Number(summary.discount_percent || 0)}%</b></div>
<div class="card"><span>Your Price</span><b>€${Number(summary.price_eur || 0).toFixed(2)}</b></div>
</section>
<section class="panel">
<div class="toolbar">
<label>Detail level <select id="levelSelect"></select></label>
<span id="levelSummary" class="muted"></span>
</div>
<svg id="map" role="img" aria-label="${escapeHtmlText(name)} tile map"></svg>
<div class="legend">
<span><i class="swatch new"></i>New in this pack</span>
<span><i class="swatch licenced"></i>Already licenced</span>
<span><i class="swatch free"></i>Free / not charged</span>
</div>
</section>
<section class="panel">
<h2>Included Areas</h2>
<div class="countries">${countries.map((country) => `<div>${escapeHtmlText(country)}</div>`).join("")}</div>
</section>
<section class="panel small muted">
<p>Price check: the sum of visible charged tile prices for all detail levels is €${Number(summary.tile_price_sum_eur || 0).toFixed(2)} and the pack price is €${Number(summary.price_eur || 0).toFixed(2)}.</p>
</section>
</main>
<script>const DATA=${payload};
const NS="http://www.w3.org/2000/svg";
const fmt=(v)=>"€"+Number(v||0).toFixed(2);
const bounds=DATA.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};
const pad=20, innerW=1000, aspect=Math.max(0.28,Math.min(0.9,(bounds.max_lat-bounds.min_lat)/Math.max(1e-6,bounds.max_lon-bounds.min_lon)));
const W=innerW, H=Math.round(innerW*aspect)+pad*2;
function xy(lon,lat){return [pad+((lon-bounds.min_lon)/(bounds.max_lon-bounds.min_lon||1))*(W-pad*2),pad+((bounds.max_lat-lat)/(bounds.max_lat-bounds.min_lat||1))*(H-pad*2)]}
function el(name,attrs){const node=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs||{})){node.setAttribute(k,String(v))}return node}
function pathFor(poly){return poly.map((pt,i)=>{const p=xy(pt[0],pt[1]);return (i?"L":"M")+p[0].toFixed(2)+" "+p[1].toFixed(2)}).join(" ")+" Z"}
function render(level){const svg=document.getElementById("map");svg.replaceChildren();svg.setAttribute("viewBox","0 0 "+W+" "+H);
  svg.appendChild(el("rect",{x:0,y:0,width:W,height:H,fill:"#0d1118"}));
  for(const outline of DATA.outlines||[]){for(const poly of outline.polygons||[]){const p=el("path",{d:pathFor(poly),fill:"var(--country)",stroke:"var(--country-line)","stroke-width":"0.7",opacity:"0.72"});const t=el("title",{});t.textContent=outline.name; p.appendChild(t); svg.appendChild(p);}}
  const rows=(DATA.tiles||[]).filter(t=>Number(t.z)===Number(level)); let newCount=0, licencedCount=0, freeCount=0, price=0;
  for(const tile of rows){const a=xy(tile.lon_min,tile.lat_max), b=xy(tile.lon_max,tile.lat_min); const cls=tile.status==="new"?"var(--new)":(tile.status==="licenced"?"var(--licenced)":"var(--free)");
    if(tile.status==="new"){newCount++; price+=Number(tile.price_eur||0)} else if(tile.status==="licenced"){licencedCount++} else {freeCount++}
    const r=el("rect",{x:a[0],y:a[1],width:Math.max(1,b[0]-a[0]),height:Math.max(1,b[1]-a[1]),fill:cls,stroke:"#fff","stroke-width":"0.45",opacity:tile.status==="new"?"0.58":"0.43"});
    const title=el("title",{}); title.textContent=tile.tile_key+"\\nStatus: "+tile.status+"\\nPack price: "+fmt(tile.price_eur)+"\\nNormal price: "+fmt(tile.normal_price_eur)+"\\nLand: "+Number(tile.billable_land_km2||0).toFixed(2)+" km²"; r.appendChild(title); svg.appendChild(r);}
  document.getElementById("levelSummary").textContent=rows.length+" tiles at z"+String(level).padStart(3,"0")+" · new "+newCount+" · already licenced "+licencedCount+" · free "+freeCount+" · visible-level price "+fmt(price);
}
const levels=(DATA.levels&&DATA.levels.length?DATA.levels:[1]); const select=document.getElementById("levelSelect");
for(const z of levels){const o=document.createElement("option");o.value=String(z);o.textContent="z"+String(z).padStart(3,"0");select.appendChild(o)}
select.addEventListener("change",()=>render(Number(select.value))); render(Number(select.value||levels[0]));
</script>
</body>
</html>`;
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

export function isStandardQualityUnlocked(account) {
  return Boolean(String(account && (
    account.standard_quality_unlocked_at
    || account.balanced_quality_unlocked_at
    || ""
  ) || "").trim());
}

export async function isStandardQualityUnlockedForUser(db, userId, deps) {
  const account = await ensureCreditAccount(db, userId, deps);
  return isStandardQualityUnlocked(account);
}

export function isWorldFullQualityUnlocked(account) {
  return Boolean(String(account && (
    account.world_full_quality_unlocked_at
    || ""
  ) || "").trim());
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
  if (isUnlimitedCreditAccount(account) || isWorldFullQualityUnlocked(account)) {
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
  const rows = [];
  for (const chunk of fixedSizeChunks(keys)) {
    rows.push(...await deps.dbAll(
      db,
      `
        SELECT tile_key, land_km2, billable_land_km2, free_reason
        FROM tile_land_stats
        WHERE tile_key IN (${chunk.map(() => "?").join(",")})
      `,
      chunk,
    ));
  }
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
  const safeMode = deps.normalizeQualityMode(qualityMode || "");
  if (safeMode === "preview" || safeMode === "balanced") {
    const keys = normalizeTileKeys(tileKeys);
    return {
      credits: 0,
      price_eur: 0,
      paid_tile_count: 0,
      free_tile_count: keys.length,
      tile_count: keys.length,
      new_tiles: [],
      tiles: keys.map((tileKey) => ({
        tile_key: tileKey,
        credits: 0,
        price_eur: 0,
        free_reason: safeMode === "balanced" ? "standard_quality_unlock" : "preview_quality",
      })),
      excluded_tiles: [],
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
    };
  }
  const account = await ensureCreditAccount(db, userId, deps);
  const worldFullQualityUnlocked = isWorldFullQualityUnlocked(account);
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
  if (worldFullQualityUnlocked) {
    const pricedTiles = pricingRecords.map((tile) => ({
      ...tile,
      credits: 0,
      price_eur: 0,
      gross_credits: normalizeCreditAmount(tile && tile.credits),
      gross_price_eur: normalizeCreditAmount(tile && tile.credits),
      already_owned: true,
      globally_free: Boolean(isFreeCreditTileKey(tile && tile.tile_key || "")),
      free_reason: "world_full_quality_licence",
    }));
    return {
      credits: 0,
      price_eur: 0,
      paid_tile_count: 0,
      free_tile_count: pricingRecords.length,
      tile_count: pricingRecords.length,
      new_tiles: [],
      tiles: pricedTiles,
      excluded_tiles: pricedTiles,
      integrity_warnings: integrityWarnings,
      metadata_missing_tile_keys: metadataMissingTileKeys,
    };
  }
  const familyList = Array.from(families);
  const rows = [];
  if (familyList.length) {
    for (const familyChunk of fixedSizeChunks(familyList)) {
      rows.push(...await deps.dbAll(
      db,
      `
        SELECT tile_key
        FROM user_tile_entitlements
        WHERE user_id = ?
          AND (${familyChunk.map(() => "tile_key LIKE ?").join(" OR ")})
      `,
      [String(userId || "").trim(), ...familyChunk.map((family) => `${family}_d%`)],
      ));
    }
  }
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
  if (safeMode === "preview" || safeMode === "balanced") {
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
  if (requiredCredits > 0 && balance <= 0) {
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

  if (actualCredits > 0 && balance <= 0) {
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
  const stripeSessionId = String(metadata && metadata.stripe_session_id || "").trim();
  if (safeReason === "stripe_balance_top_up" && stripeSessionId) {
    await recordPurchaseHistoryBestEffort(
      db,
      {
        user_id: safeUserId,
        user_email: String(metadata && metadata.customer_email || "").trim().toLowerCase(),
        purchase_type: "balance_top_up",
        stripe_session_id: stripeSessionId,
        stripe_payment_intent_id: String(metadata && metadata.stripe_payment_intent_id || "").trim(),
        amount_paid_eur: normalizeCreditAmount(metadata && (metadata.stripe_amount_paid_eur ?? amount)),
        nominal_eur: amount,
        gross_eur: amount,
        tile_count_total: 0,
        tile_count_new: 0,
        metadata: {
          stripe_amount_paid_eur: normalizeCreditAmount(metadata && metadata.stripe_amount_paid_eur),
          stripe_payment_intent_id: String(metadata && metadata.stripe_payment_intent_id || "").trim(),
          top_up_eur: amount,
        },
        created_at: now,
      },
      deps,
    );
  }
  return {
    ok: true,
    added_credits: amount,
    added_eur: amount,
    balance_credits: balanceAfter,
    balance_eur: balanceAfter,
  };
}

export async function grantPaidSceneTileEntitlements(db, userId, qualityMode, tileKeys, resolveId, amountPaidEur, deps, userEmail = "", stripePaymentIntentId = "") {
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
  const purchasedTileRows = insertedTiles.map((tile) => ({
    ...tile,
    tile_status: "new",
  }));
  const purchasedTileKeys = purchasedTileRows.map((tile) => normalizeTileKey(tile && tile.tile_key || "")).filter(Boolean);
  const alreadyLicencedCount = Array.isArray(estimate && estimate.excluded_tiles)
    ? estimate.excluded_tiles.length
    : 0;
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
        stripe_session_id: String(resolveId || ""),
        stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
        resolve_id: String(resolveId || ""),
        quality_mode: safeMode,
        tile_count: insertedTiles.length,
        tile_count_total: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
        tile_count_new: insertedTiles.length,
        tile_count_already_licenced: alreadyLicencedCount,
        nominal_eur: nominalCredits,
        paid_eur: normalizeCreditAmount(amountPaidEur),
        purchased_tile_keys: purchasedTileKeys,
        purchased_tiles: purchasedTileRows.map((tile) => compactPurchaseTile(tile, "new")).filter(Boolean),
      }),
      now,
    ],
  );
  await recordPurchaseHistoryBestEffort(
    db,
    {
      user_id: safeUserId,
      user_email: String(userEmail || "").trim().toLowerCase(),
      purchase_type: "scene_tiles",
      stripe_session_id: String(resolveId || "").trim(),
      stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
      amount_paid_eur: normalizeCreditAmount(amountPaidEur),
      nominal_eur: nominalCredits,
      gross_eur: nominalCredits,
      quality_mode: safeMode,
      tile_count_total: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      tile_count_new: insertedTiles.length,
      tile_count_already_licenced: alreadyLicencedCount,
      tiles: purchasedTileRows,
      metadata: {
        purchased_tile_keys: purchasedTileKeys,
      },
      created_at: now,
    },
    deps,
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

async function regionPackEntitlementRowsForGrant(db, userId, product, deps) {
  await deps.ensureCreditTables(db);
  const tileKeys = regionProductTileKeys(product);
  const existingRows = await deps.dbAll(
    db,
    `
      SELECT tile_key
      FROM user_tile_entitlements
      WHERE user_id = ?
    `,
    [String(userId || "").trim()],
  );
  const ownedByFamily = new Map();
  for (const row of existingRows || []) {
    const owned = parseTileKey(row && row.tile_key || "");
    const family = tileFamilyKey(owned);
    if (!owned || !family) {
      continue;
    }
    if (!ownedByFamily.has(family)) {
      ownedByFamily.set(family, []);
    }
    ownedByFamily.get(family).push(Number(owned.d));
  }
  const rows = [];
  for (const key of tileKeys) {
    const tileKey = normalizeTileKey(key);
    const parsed = parseTileKey(tileKey);
    const family = tileFamilyKey(parsed);
    if (!tileKey || !parsed || !family || isFreeCreditTileKey(tileKey)) {
      continue;
    }
    const ownedDLevels = ownedByFamily.get(family) || [];
    if (ownedDLevels.some((ownedD) => Number(ownedD) <= Number(parsed.d))) {
      continue;
    }
    const gross = generatedTileGrossEur(tileKey);
    rows.push({
      tile_key: tileKey,
      credits: gross,
      gross_credits: gross,
      price_eur: gross,
      gross_price_eur: gross,
      land_km2: 0,
      billable_land_km2: 0,
      source: "stripe_region_pack_summary",
    });
    ownedDLevels.push(Number(parsed.d));
    ownedByFamily.set(family, ownedDLevels);
  }
  return rows;
}

async function insertRegionPackEntitlementRows(db, userId, rows, source, now, deps) {
  const safeUserId = String(userId || "").trim();
  const sourceName = String(source || "stripe_region_pack").trim() || "stripe_region_pack";
  const inserted = [];
  // D1 rejects large multi-value INSERT statements well below SQLite's usual
  // variable limit in Workers. Ten rows keeps this path under 70 bound values.
  const chunks = fixedSizeChunks(rows || [], 10);
  for (const chunk of chunks) {
    const valuesSql = chunk.map(() => "(?, ?, 'full', ?, ?, ?, ?, ?)").join(",");
    const bindings = [];
    for (const row of chunk) {
      bindings.push(
        safeUserId,
        normalizeTileKey(row && row.tile_key || ""),
        normalizeCreditAmount(row && (row.gross_credits ?? row.credits)),
        Math.max(0, Number.parseFloat(row && row.land_km2 || 0) || 0),
        Math.max(0, Number.parseFloat(row && row.billable_land_km2 || 0) || 0),
        sourceName,
        now,
      );
    }
    if (!bindings.length) {
      continue;
    }
    await deps.dbRun(
      db,
      `
        INSERT OR IGNORE INTO user_tile_entitlements (
          user_id, tile_key, quality_mode, credits_spent, land_km2, billable_land_km2, source, unlocked_at
        )
        VALUES ${valuesSql}
      `,
      bindings,
    );
    inserted.push(...chunk);
  }
  return inserted;
}

export async function grantRegionPackEntitlements(db, userId, regionPackId, stripeSessionId, amountPaidEur, deps, userEmail = "", stripePaymentIntentId = "") {
  const safeUserId = String(userId || "").trim();
  const safeStripeSessionId = String(stripeSessionId || "").trim();
  const product = regionProductById(regionPackId);
  if (!safeUserId) {
    return { error: "missing_user_id" };
  }
  if (!product) {
    return { error: "unknown_region_pack" };
  }
  if (safeStripeSessionId) {
    const existingLedger = await deps.dbGet(
      db,
      `
        SELECT COUNT(*) AS count
        FROM credit_ledger
        WHERE user_id = ?
          AND LOWER(COALESCE(reason, '')) = 'stripe_region_pack_purchase'
          AND json_valid(COALESCE(metadata_json, ''))
          AND COALESCE(json_extract(metadata_json, '$.stripe_session_id'), '') = ?
      `,
      [safeUserId, safeStripeSessionId],
    );
    if (Number(existingLedger && existingLedger.count || 0) > 0) {
      return {
        ok: true,
        duplicate_session: true,
        region_pack: regionProductPublicPayload(product),
        paid_eur: 0,
        paid_tile_count: 0,
      };
    }
  }
  await ensureCreditAccount(db, safeUserId, deps);
  const useDetailedGrant = Math.max(0, Number.parseInt(product && product.tile_count || 0, 10) || 0) <= 1000;
  const estimate = await estimateRegionPack(db, safeUserId, product, deps, { includeRows: false, forceDetailed: useDetailedGrant });
  if (estimate && estimate.error) {
    return estimate;
  }
  const paidEur = normalizeCreditAmount(amountPaidEur);
  const estimateTotalTiles = Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0);
  const estimateNewTiles = Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0);
  const alreadyLicencedTiles = Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0);
  const grossEur = normalizeCreditAmount(estimate && estimate.gross_eur);
  const discountEur = normalizeCreditAmount(estimate && estimate.discount_eur);
  const discountPercent = Math.max(0, Number.parseInt(product.discount_percent || 0, 10) || 0);
  if (paidEur <= 0 && estimateNewTiles <= 0) {
    return {
      ...estimate,
      credits: 0,
      price_eur: 0,
      paid_eur: 0,
      nominal_eur: 0,
      paid_tile_count: 0,
      new_tiles: [],
    };
  }
  const now = deps.nowIso();
  const isWorldPack = String(product.id || "").trim().toLowerCase() === "world";
  if (isWorldPack) {
    await deps.dbRun(
      db,
      `
        UPDATE user_credit_accounts
        SET
          world_full_quality_unlocked_at = COALESCE(NULLIF(TRIM(world_full_quality_unlocked_at), ''), ?),
          world_full_quality_checkout_session_id = ?,
          world_full_quality_paid_eur = ROUND((COALESCE(world_full_quality_paid_eur, 0) + ?) * 100.0) / 100.0,
          updated_at = ?
        WHERE user_id = ?
      `,
      [now, safeStripeSessionId || null, paidEur, now, safeUserId],
    );
    await deps.dbRun(
      db,
      `
        INSERT INTO credit_ledger (
          id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
        )
        VALUES (?, ?, 0, (SELECT balance_credits FROM user_credit_accounts WHERE user_id = ?), 'stripe_region_pack_purchase', ?, ?)
      `,
      [
        deps.randomToken(16),
        safeUserId,
        safeUserId,
        JSON.stringify({
          stripe_session_id: safeStripeSessionId,
          stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
          region_pack_id: "world",
          region_pack_name: String(product.name || "World"),
          region_pack_type: String(product.type || "world"),
          catalog_version: REGION_PACK_CATALOG_VERSION,
          discount_percent: discountPercent,
          discount_eur: discountEur,
          quality_mode: "full",
          tile_count: estimateNewTiles,
          tile_count_total: estimateTotalTiles,
          tile_count_new: estimateNewTiles,
          tile_count_already_licenced: alreadyLicencedTiles,
          nominal_eur: grossEur,
          gross_eur: grossEur,
          paid_eur: paidEur,
          world_full_quality_unlocked: true,
        }),
        now,
      ],
    );
    await recordPurchaseHistoryBestEffort(
      db,
      {
        user_id: safeUserId,
        user_email: String(userEmail || "").trim().toLowerCase(),
        purchase_type: "region_pack",
        stripe_session_id: safeStripeSessionId,
        stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
        amount_paid_eur: paidEur,
        nominal_eur: grossEur,
        gross_eur: grossEur,
        discount_eur: discountEur,
        discount_percent: discountPercent,
        quality_mode: "full",
        region_pack_id: "world",
        region_pack_name: String(product.name || "World"),
        region_pack_type: String(product.type || "world"),
        catalog_version: REGION_PACK_CATALOG_VERSION,
        tile_count_total: estimateTotalTiles,
        tile_count_new: estimateNewTiles,
        tile_count_already_licenced: alreadyLicencedTiles,
        metadata: {
          world_full_quality_unlocked: true,
        },
        created_at: now,
      },
      deps,
    );
    return {
      ...estimate,
      credits: 0,
      price_eur: 0,
      paid_eur: paidEur,
      nominal_eur: grossEur,
      paid_tile_count: Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0),
      new_tiles: [],
      world_full_quality_unlocked: true,
    };
  }
  const insertedTiles = [];
  let nominalCredits = 0;
  const grantTiles = useDetailedGrant
    ? (estimate.new_tiles || [])
    : await regionPackEntitlementRowsForGrant(db, safeUserId, product, deps);
  if (!useDetailedGrant) {
    insertedTiles.push(...await insertRegionPackEntitlementRows(
      db,
      safeUserId,
      grantTiles,
      "stripe_region_pack_summary",
      now,
      deps,
    ));
    nominalCredits = normalizeCreditAmount(estimate && estimate.gross_eur);
  }
  for (const tile of (useDetailedGrant ? grantTiles : [])) {
    const tileKey = normalizeTileKey(tile && tile.tile_key || "");
    if (!tileKey || isFreeCreditTileKey(tileKey)) {
      continue;
    }
    const nominalTileCredits = normalizeCreditAmount(tile && (tile.gross_credits ?? tile.credits));
    const insert = await deps.dbRun(
      db,
      `
        INSERT OR IGNORE INTO user_tile_entitlements (
          user_id, tile_key, quality_mode, credits_spent, land_km2, billable_land_km2, source, unlocked_at
        )
        VALUES (?, ?, 'full', ?, ?, ?, 'stripe_region_pack', ?)
      `,
      [
        safeUserId,
        tileKey,
        nominalTileCredits,
        Math.max(0, Number.parseFloat(tile && tile.land_km2 || 0) || 0),
        Math.max(0, Number.parseFloat(tile && tile.billable_land_km2 || 0) || 0),
        now,
      ],
    );
    if (deps.dbMetaChanges(insert) > 0) {
      insertedTiles.push(tile);
      nominalCredits = normalizeCreditAmount(nominalCredits + nominalTileCredits);
    }
  }
  await deps.dbRun(
    db,
    `
      INSERT INTO credit_ledger (
        id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
      )
      VALUES (?, ?, 0, (SELECT balance_credits FROM user_credit_accounts WHERE user_id = ?), 'stripe_region_pack_purchase', ?, ?)
    `,
    [
      deps.randomToken(16),
      safeUserId,
      safeUserId,
      JSON.stringify({
        stripe_session_id: safeStripeSessionId,
        stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
        region_pack_id: String(product.id || ""),
        region_pack_name: String(product.name || ""),
        region_pack_type: String(product.type || ""),
        catalog_version: REGION_PACK_CATALOG_VERSION,
        discount_percent: discountPercent,
        discount_eur: discountEur,
        quality_mode: "full",
        tile_count: insertedTiles.length,
        tile_count_total: estimateTotalTiles,
        tile_count_new: estimateNewTiles,
        tile_count_already_licenced: alreadyLicencedTiles,
        nominal_eur: nominalCredits,
        gross_eur: grossEur,
        paid_eur: paidEur,
      }),
      now,
    ],
  );
  await recordPurchaseHistoryBestEffort(
    db,
    {
      user_id: safeUserId,
      user_email: String(userEmail || "").trim().toLowerCase(),
      purchase_type: "region_pack",
      stripe_session_id: safeStripeSessionId,
      stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
      amount_paid_eur: paidEur,
      nominal_eur: nominalCredits,
      gross_eur: grossEur,
      discount_eur: discountEur,
      discount_percent: discountPercent,
      quality_mode: "full",
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      region_pack_type: String(product.type || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      tile_count_total: estimateTotalTiles,
      tile_count_new: estimateNewTiles,
      tile_count_already_licenced: alreadyLicencedTiles,
      metadata: {
        inserted_tile_count: insertedTiles.length,
      },
      created_at: now,
    },
    deps,
  );
  return {
    ...estimate,
    credits: 0,
    price_eur: 0,
    paid_eur: paidEur,
    nominal_eur: nominalCredits,
    paid_tile_count: useDetailedGrant
      ? insertedTiles.filter((tile) => normalizeCreditAmount(tile && (tile.gross_credits ?? tile.credits)) > 0).length
      : Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0),
    new_tiles: insertedTiles.slice(0, 500),
  };
}

export async function grantStandardQualityUnlock(db, userId, stripeSessionId, amountPaidEur, deps, userEmail = "", stripePaymentIntentId = "") {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return { error: "missing_user_id" };
  }
  const safeStripeSessionId = String(stripeSessionId || "").trim();
  if (safeStripeSessionId) {
    const existingLedger = await deps.dbGet(
      db,
      `
        SELECT COUNT(*) AS count
        FROM credit_ledger
        WHERE user_id = ?
          AND LOWER(COALESCE(reason, '')) = 'stripe_standard_quality_unlock'
          AND json_valid(COALESCE(metadata_json, ''))
          AND COALESCE(json_extract(metadata_json, '$.stripe_session_id'), '') = ?
      `,
      [safeUserId, safeStripeSessionId],
    );
    if (Number(existingLedger && existingLedger.count || 0) > 0) {
      const account = await ensureCreditAccount(db, safeUserId, deps);
      return {
        ok: true,
        already_unlocked: true,
        duplicate_session: true,
        standard_quality_unlocked: isStandardQualityUnlocked(account),
        standard_quality_unlocked_at: String(account && account.standard_quality_unlocked_at || ""),
        paid_eur: 0,
      };
    }
  }
  const account = await ensureCreditAccount(db, safeUserId, deps);
  const alreadyUnlocked = isStandardQualityUnlocked(account);
  const now = deps.nowIso();
  if (!alreadyUnlocked) {
    await deps.dbRun(
      db,
      `
        UPDATE user_credit_accounts
        SET
          standard_quality_unlocked_at = ?,
          standard_quality_checkout_session_id = ?,
          standard_quality_paid_eur = ?,
          updated_at = ?
        WHERE user_id = ?
      `,
      [
        now,
        safeStripeSessionId,
        normalizeCreditAmount(amountPaidEur),
        now,
        safeUserId,
      ],
    );
  }
  await deps.dbRun(
    db,
    `
      INSERT INTO credit_ledger (
        id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
      )
      VALUES (?, ?, 0, (SELECT balance_credits FROM user_credit_accounts WHERE user_id = ?), 'stripe_standard_quality_unlock', ?, ?)
    `,
    [
      deps.randomToken(16),
      safeUserId,
      safeUserId,
      JSON.stringify({
        stripe_session_id: safeStripeSessionId,
        stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
        paid_eur: normalizeCreditAmount(amountPaidEur),
        already_unlocked: alreadyUnlocked,
      }),
      now,
    ],
  );
  await recordPurchaseHistoryBestEffort(
    db,
    {
      user_id: safeUserId,
      user_email: String(userEmail || "").trim().toLowerCase(),
      purchase_type: "standard_quality_unlock",
      stripe_session_id: safeStripeSessionId,
      stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
      amount_paid_eur: normalizeCreditAmount(amountPaidEur),
      nominal_eur: normalizeCreditAmount(amountPaidEur),
      gross_eur: normalizeCreditAmount(amountPaidEur),
      quality_mode: "balanced",
      tile_count_total: 0,
      tile_count_new: 0,
      metadata: {
        already_unlocked: alreadyUnlocked,
      },
      created_at: now,
    },
    deps,
  );
  const refreshed = await ensureCreditAccount(db, safeUserId, deps);
  return {
    ok: true,
    already_unlocked: alreadyUnlocked,
    standard_quality_unlocked: isStandardQualityUnlocked(refreshed),
    standard_quality_unlocked_at: String(refreshed && refreshed.standard_quality_unlocked_at || ""),
    paid_eur: normalizeCreditAmount(amountPaidEur),
  };
}

async function createStripeCheckoutSession(env, params, deps) {
  const secretKey = deps.requireSecret(env, "STRIPE_SECRET_KEY");
  const metadata = params.metadata && typeof params.metadata === "object" ? params.metadata : {};
  const body = new URLSearchParams();
  body.set("mode", "payment");
  body.set("success_url", checkoutReturnUrl(defaultCheckoutSuccessUrl(env), "{CHECKOUT_SESSION_ID}"));
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

  if (option === "standard_unlock" || option === "balanced_unlock") {
    const account = await ensureCreditAccount(db, userId, deps);
    if (isStandardQualityUnlocked(account)) {
      return deps.json(
        {
          ok: true,
          option: "standard_unlock",
          no_payment_required: true,
          standard_quality_unlocked: true,
          price_eur: 0,
          message: "Standard Quality is already unlocked for this account.",
        },
        200,
        env,
      );
    }
    const amountEur = standardQualityUnlockPriceEur(env);
    const session = await createStripeCheckoutSession(
      env,
      {
        amountCents: centsForEur(amountEur),
        customerEmail: email,
        clientReferenceId: userId,
        productName: "Planetka Standard Quality Unlock",
        metadata: {
          planetka_purchase_type: "standard_quality_unlock",
          planetka_user_id: userId,
          planetka_email: email,
          planetka_quality_mode: "balanced",
          planetka_standard_quality_price_eur: amountEur.toFixed(2),
        },
      },
      deps,
    );
    if (session.error) {
      return deps.json({ ok: false, ...session }, 502, env);
    }
    return deps.json({ ok: true, option: "standard_unlock", price_eur: amountEur, ...session }, 200, env);
  }

  if (option === "region_pack" || option === "broader_pack") {
    const product = regionProductById(body && (
      body.region_pack_id
      || body.regionPackId
      || body.region_id
      || body.regionId
      || body.pack_id
      || body.packId
    ));
    if (!product) {
      return deps.json({ ok: false, error: "unknown_region_pack" }, 404, env);
    }
    const estimate = await estimateRegionPack(db, userId, product, deps, { includeRows: false });
    if (estimate && estimate.error) {
      return deps.json({ ok: false, ...estimate }, 400, env);
    }
    const priceEur = normalizeCreditAmount(estimate && estimate.price_eur);
    if (priceEur <= 0) {
      const grant = await grantRegionPackEntitlements(
        db,
        userId,
        String(product.id || ""),
        `region_pack_no_payment_${deps.randomToken(8)}`,
        0,
        deps,
      );
      if (grant && grant.error) {
        return deps.json({ ok: false, ...grant }, 400, env);
      }
      return deps.json(
        {
          ok: true,
          option: "region_pack",
          region_pack: regionProductPublicPayload(product),
          no_payment_required: true,
          price_eur: 0,
          gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
          discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
          paid_tile_count: grant && grant.paid_tile_count || 0,
          new_tile_count: grant && grant.new_tiles && grant.new_tiles.length || estimate.new_tile_count || 0,
          tile_count: grant && grant.tile_count || estimate.tile_count,
          message: "This region pack has no newly charged Full Quality tiles.",
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
          option: "region_pack",
          region_pack: regionProductPublicPayload(product),
          price_eur: priceEur,
          minimum_eur: STRIPE_MIN_CHECKOUT_AMOUNT_CENTS / 100.0,
          message: "This region pack price is below Stripe's minimum checkout amount.",
        },
        400,
        env,
      );
    }
    const session = await createStripeCheckoutSession(
      env,
      {
        amountCents,
        customerEmail: email,
        clientReferenceId: userId,
        productName: `Planetka Full Quality ${String(product.name || "Region")} Pack`,
        metadata: {
          planetka_purchase_type: "region_pack",
          planetka_user_id: userId,
          planetka_email: email,
          planetka_quality_mode: "full",
          planetka_region_id: String(product.id || ""),
          planetka_region_name: String(product.name || ""),
          planetka_region_type: String(product.type || ""),
          planetka_catalog_version: REGION_PACK_CATALOG_VERSION,
          planetka_price_eur: priceEur.toFixed(2),
          planetka_gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur).toFixed(2),
          planetka_discount_percent: String(Math.max(0, Number.parseInt(product.discount_percent || 0, 10) || 0)),
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
        option: "region_pack",
        region_pack: regionProductPublicPayload(product),
        price_eur: priceEur,
        gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
        discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
        paid_tile_count: estimate.paid_tile_count,
        new_tile_count: estimate.new_tile_count,
        tile_count: estimate.tile_count,
        ...session,
      },
      200,
      env,
    );
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
  const worldUnlocked = isWorldFullQualityUnlocked(account);
  const worldSummary = worldRegionProductSummary();
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
      unlocked_tile_count: worldUnlocked
        ? Math.max(Number(countRow && countRow.count || 0), Number(worldSummary.licensable_tile_count || 0))
        : Number(countRow && countRow.count || 0),
      standard_quality_unlocked: isStandardQualityUnlocked(account),
      standard_quality_unlocked_at: String(account && account.standard_quality_unlocked_at || ""),
      standard_quality_price_eur: standardQualityUnlockPriceEur(env),
      world_full_quality_unlocked: worldUnlocked,
      world_full_quality_unlocked_at: String(account && account.world_full_quality_unlocked_at || ""),
      world_full_quality_paid_eur: normalizeCreditAmount(account && account.world_full_quality_paid_eur),
      world_full_quality_tile_count: Number(worldSummary.tile_count || 0),
      world_full_quality_licensable_tile_count: Number(worldSummary.licensable_tile_count || 0),
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
  const worldUnlocked = isWorldFullQualityUnlocked(account);
  const worldSummary = worldRegionProductSummary();
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
      standard_quality_unlocked: isStandardQualityUnlocked(account),
      standard_quality_unlocked_at: String(account && account.standard_quality_unlocked_at || ""),
      standard_quality_price_eur: standardQualityUnlockPriceEur(env),
      world_full_quality_unlocked: worldUnlocked,
      world_full_quality_unlocked_at: String(account && account.world_full_quality_unlocked_at || ""),
      world_full_quality_paid_eur: normalizeCreditAmount(account && account.world_full_quality_paid_eur),
      world_full_quality_tile_count: Number(worldSummary.tile_count || 0),
      world_full_quality_licensable_tile_count: Number(worldSummary.licensable_tile_count || 0),
    },
    200,
    env,
  );
}

export async function handleCreditRegionOffers(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await ensureCreditAccount(db, auth.user.id, deps);
  const body = await deps.parseJson(request);
  const latitude = clampNumber(body && (body.latitude_deg ?? body.latitude ?? body.lat), -90.0, 90.0);
  const longitude = clampNumber(body && (body.longitude_deg ?? body.longitude ?? body.lon), -180.0, 180.0);
  const products = suggestedRegionProductsForPoint(latitude, longitude);
  const offers = [];
  for (const product of products) {
    const estimate = await estimateRegionPack(db, auth.user.id, product, deps, { includeRows: false });
    if (estimate && estimate.error) {
      offers.push({
        ok: false,
        ...regionProductPublicPayload(product),
        error: String(estimate.error || "region_pack_estimate_failed"),
      });
      continue;
    }
    offers.push({
      ok: true,
      ...regionProductPublicPayload(product),
      gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
      gross_price_eur: normalizeCreditAmount(estimate && estimate.gross_price_eur),
      discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
      credits: normalizeCreditAmount(estimate && estimate.credits),
      price_eur: normalizeCreditAmount(estimate && estimate.price_eur),
      paid_tile_count: Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0),
      free_tile_count: Math.max(0, Number.parseInt(estimate && estimate.free_tile_count || 0, 10) || 0),
      tile_count: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      new_tile_count: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
      already_licenced_tile_count: Math.max(0, Number.parseInt(estimate && estimate.excluded_tiles && estimate.excluded_tiles.length || 0, 10) || 0),
      metadata_missing_tile_keys: Array.isArray(estimate && estimate.metadata_missing_tile_keys)
        ? estimate.metadata_missing_tile_keys.slice(0, 100)
        : [],
    });
  }
  return deps.json(
    {
      ok: true,
      catalog_version: REGION_PACK_CATALOG_VERSION,
      latitude_deg: latitude,
      longitude_deg: longitude,
      offers,
    },
    200,
    env,
  );
}

export async function handleCreditRegionPackDetailLink(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await ensureCreditAccount(db, auth.user.id, deps);
  await ensureRegionPackDetailTokenTable(db, deps);
  const body = await deps.parseJson(request);
  const product = regionProductById(body && (
    body.region_pack_id
    || body.regionPackId
    || body.region_id
    || body.regionId
    || body.pack_id
    || body.packId
  ));
  if (!product) {
    return deps.json({ ok: false, error: "unknown_region_pack" }, 404, env);
  }
  const now = deps.nowIso();
  await deps.dbRun(db, `DELETE FROM region_pack_detail_tokens WHERE expires_at <= ?`, [now]);
  const token = deps.randomToken(32);
  const expiresAt = addMinutesIsoFromDeps(deps, regionPackDetailTokenTtlMinutes(env));
  await deps.dbRun(
    db,
    `
      INSERT INTO region_pack_detail_tokens (
        token, user_id, region_pack_id, created_at, expires_at
      ) VALUES (?, ?, ?, ?, ?)
    `,
    [token, String(auth.user.id || "").trim(), String(product.id || ""), now, expiresAt],
  );
  const url = new URL(request.url);
  url.pathname = "/credits/region-pack-map";
  url.search = "";
  url.searchParams.set("token", token);
  return deps.json(
    {
      ok: true,
      region_pack: regionProductPublicPayload(product),
      detail_url: url.toString(),
      expires_at: expiresAt,
    },
    200,
    env,
  );
}

export async function handleCreditRegionPackMap(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return html(
      "<!doctype html><title>Planetka Region Pack</title><h1>Missing region-pack detail token.</h1>",
      400,
      env,
    );
  }
  const db = deps.requireDb(env);
  await ensureRegionPackDetailTokenTable(db, deps);
  const now = deps.nowIso();
  const row = await deps.dbGet(
    db,
    `
      SELECT token, user_id, region_pack_id, expires_at
      FROM region_pack_detail_tokens
      WHERE token = ?
      LIMIT 1
    `,
    [token],
  );
  if (!row || String(row.expires_at || "") <= now) {
    return html(
      "<!doctype html><title>Planetka Region Pack</title><h1>This region-pack detail link expired.</h1><p>Please open it again from Blender.</p>",
      410,
      env,
    );
  }
  const product = regionProductById(row.region_pack_id);
  if (!product) {
    return html(
      "<!doctype html><title>Planetka Region Pack</title><h1>Unknown region pack.</h1>",
      404,
      env,
    );
  }
  await ensureCreditAccount(db, row.user_id, deps);
  const estimate = await estimateRegionPack(db, row.user_id, product, deps, { includeRows: true });
  if (estimate && estimate.error) {
    return html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Region pack estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
      500,
      env,
    );
  }
  const data = buildRegionPackMapData(product, estimate);
  return html(regionPackMapHtml(data), 200, env);
}

function checkoutReturnHtml({ title, heading, message, icon, tone }) {
  const safeTitle = escapeHtmlText(title || "Planetka Payment");
  const safeHeading = escapeHtmlText(heading || "Payment processed");
  const safeMessage = escapeHtmlText(message || "You can return to Blender.");
  const safeIcon = escapeHtmlText(icon || "OK");
  const safeTone = String(tone || "success").trim() === "cancel" ? "cancel" : "success";
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${safeTitle}</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #101214;
      color: #f4f0e8;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at 20% 20%, rgba(93, 160, 255, 0.22), transparent 32rem),
        radial-gradient(circle at 85% 75%, rgba(64, 180, 126, 0.18), transparent 28rem),
        #101214;
    }
    main {
      width: min(38rem, calc(100vw - 2rem));
      padding: 2.4rem;
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 1.25rem;
      background: rgba(18, 20, 22, 0.82);
      box-shadow: 0 2rem 6rem rgba(0, 0, 0, 0.36);
    }
    .mark {
      width: 3.25rem;
      height: 3.25rem;
      display: inline-grid;
      place-items: center;
      border-radius: 999px;
      margin-bottom: 1.2rem;
      font-size: 1.7rem;
      background: ${safeTone === "cancel" ? "rgba(255, 181, 71, 0.18)" : "rgba(74, 222, 128, 0.18)"};
      color: ${safeTone === "cancel" ? "#ffd08a" : "#91f7b5"};
    }
    h1 {
      margin: 0 0 0.75rem;
      font-size: clamp(1.8rem, 5vw, 2.6rem);
      letter-spacing: -0.04em;
    }
    p {
      margin: 0;
      color: rgba(244, 240, 232, 0.78);
      line-height: 1.55;
      font-size: 1.05rem;
    }
  </style>
</head>
<body>
  <main>
    <div class="mark">${safeIcon}</div>
    <h1>${safeHeading}</h1>
    <p>${safeMessage}</p>
  </main>
</body>
</html>`;
}

export async function handleCreditPaymentSuccess(request, env, deps) {
  return html(
    checkoutReturnHtml({
      title: "Planetka Payment Complete",
      heading: "Payment complete",
      message: "Your Planetka licence is being applied to your account. Return to Blender; the panel will refresh automatically after Stripe confirms the payment.",
      icon: "OK",
      tone: "success",
    }),
    200,
    env,
  );
}

export async function handleCreditPaymentCancelled(request, env, deps) {
  return html(
    checkoutReturnHtml({
      title: "Planetka Payment Cancelled",
      heading: "Payment cancelled",
      message: "No Planetka payment was completed. You can return to Blender and continue with Preview or start the purchase again.",
      icon: "!",
      tone: "cancel",
    }),
    200,
    env,
  );
}

async function loadPurchaseHistoryForUser(db, userId, deps, options = {}) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  const limit = Math.max(1, Math.min(500, Number.parseInt(options && options.limit || 100, 10) || 100));
  const purchases = await deps.dbAll(
    db,
    `
      SELECT
        id,
        user_id,
        user_email,
        purchase_type,
        stripe_session_id,
        stripe_payment_intent_id,
        currency,
        amount_paid_eur,
        nominal_eur,
        gross_eur,
        discount_eur,
        discount_percent,
        quality_mode,
        region_pack_id,
        region_pack_name,
        region_pack_type,
        catalog_version,
        tile_count_total,
        tile_count_new,
        tile_count_already_licenced,
        metadata_json,
        created_at
      FROM purchase_history
      WHERE user_id = ?
      ORDER BY created_at DESC
      LIMIT ?
    `,
    [safeUserId, limit],
  );
  const purchaseIds = (purchases || []).map((row) => String(row && row.id || "").trim()).filter(Boolean);
  const tilesByPurchase = new Map();
  if (purchaseIds.length) {
    for (const chunk of fixedSizeChunks(purchaseIds, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
      const tileRows = await deps.dbAll(
        db,
        `
          SELECT
            purchase_id,
            tile_key,
            tile_status,
            price_eur,
            gross_price_eur,
            land_km2,
            billable_land_km2,
            quality_mode,
            created_at
          FROM purchase_history_tiles
          WHERE purchase_id IN (${chunk.map(() => "?").join(",")})
          ORDER BY tile_key ASC
        `,
        chunk,
      );
      for (const tile of tileRows || []) {
        const purchaseId = String(tile && tile.purchase_id || "").trim();
        if (!tilesByPurchase.has(purchaseId)) {
          tilesByPurchase.set(purchaseId, []);
        }
        tilesByPurchase.get(purchaseId).push({
          tile_key: normalizeTileKey(tile && tile.tile_key || ""),
          tile_status: String(tile && tile.tile_status || "new"),
          price_eur: normalizeCreditAmount(tile && tile.price_eur),
          gross_price_eur: normalizeCreditAmount(tile && tile.gross_price_eur),
          land_km2: normalizeMetricAmount(tile && tile.land_km2),
          billable_land_km2: normalizeMetricAmount(tile && tile.billable_land_km2),
          quality_mode: String(tile && tile.quality_mode || "full"),
          created_at: String(tile && tile.created_at || ""),
        });
      }
    }
  }
  return (purchases || []).map((row) => {
    const id = String(row && row.id || "");
    let metadata = {};
    try {
      metadata = JSON.parse(String(row && row.metadata_json || "{}"));
    } catch (error) {
      metadata = {};
    }
    return {
      id,
      user_id: String(row && row.user_id || ""),
      user_email: String(row && row.user_email || ""),
      purchase_type: String(row && row.purchase_type || ""),
      stripe_session_id: String(row && row.stripe_session_id || ""),
      stripe_payment_intent_id: String(row && row.stripe_payment_intent_id || ""),
      currency: String(row && row.currency || "eur"),
      amount_paid_eur: normalizeCreditAmount(row && row.amount_paid_eur),
      nominal_eur: normalizeCreditAmount(row && row.nominal_eur),
      gross_eur: normalizeCreditAmount(row && row.gross_eur),
      discount_eur: normalizeCreditAmount(row && row.discount_eur),
      discount_percent: Math.max(0, Number.parseInt(row && row.discount_percent || 0, 10) || 0),
      quality_mode: String(row && row.quality_mode || ""),
      region_pack_id: String(row && row.region_pack_id || ""),
      region_pack_name: String(row && row.region_pack_name || ""),
      region_pack_type: String(row && row.region_pack_type || ""),
      catalog_version: String(row && row.catalog_version || ""),
      tile_count_total: Math.max(0, Number.parseInt(row && row.tile_count_total || 0, 10) || 0),
      tile_count_new: Math.max(0, Number.parseInt(row && row.tile_count_new || 0, 10) || 0),
      tile_count_already_licenced: Math.max(0, Number.parseInt(row && row.tile_count_already_licenced || 0, 10) || 0),
      created_at: String(row && row.created_at || ""),
      metadata,
      tiles: tilesByPurchase.get(id) || [],
    };
  });
}

export async function handleCreditPurchaseHistory(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await ensureCreditAccount(db, auth.user.id, deps);
  const url = new URL(request.url);
  const limit = Math.max(1, Math.min(200, Number.parseInt(url.searchParams.get("limit") || "100", 10) || 100));
  const purchases = await loadPurchaseHistoryForUser(db, auth.user.id, deps, { limit });
  return deps.json(
    {
      ok: true,
      user_id: String(auth.user.id || ""),
      user_email: String(auth.user.email || ""),
      purchases,
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
  const account = await ensureCreditAccount(db, auth.user.id, deps);
  const worldUnlocked = isWorldFullQualityUnlocked(account);
  const worldSummary = worldRegionProductSummary();
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
  return deps.json({
    ok: true,
    tiles,
    unlocked_tile_count: worldUnlocked
      ? Math.max(tiles.length, Number(worldSummary.licensable_tile_count || 0))
      : tiles.length,
    world_full_quality_unlocked: worldUnlocked,
    world_full_quality_unlocked_at: String(account && account.world_full_quality_unlocked_at || ""),
    world_full_quality_tile_count: Number(worldSummary.tile_count || 0),
    world_full_quality_licensable_tile_count: Number(worldSummary.licensable_tile_count || 0),
  }, 200, env);
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
