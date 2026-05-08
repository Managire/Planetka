import { corsHeaders, html } from "./responses.js";
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
const BALANCE_TOP_UP_OPTIONS = [
  { amount_eur: 10, bonus_percent: 10, guide_region_pack_id: "denmark", guide_label: "Denmark" },
  { amount_eur: 25, bonus_percent: 12.5, guide_region_pack_id: "united_kingdom", guide_label: "United Kingdom" },
  { amount_eur: 50, bonus_percent: 15, guide_region_pack_id: "germany", guide_label: "Germany" },
  { amount_eur: 100, bonus_percent: 20, guide_region_pack_id: "central_europe", guide_label: "Central Europe" },
  { amount_eur: 250, bonus_percent: 22.5, guide_region_pack_id: "argentina", guide_label: "Argentina" },
  { amount_eur: 500, bonus_percent: 25, guide_region_pack_id: "east_africa", guide_label: "East Africa" },
];
const STANDARD_QUALITY_UNLOCK_EUR = 50.0;
const STRIPE_MIN_CHECKOUT_AMOUNT_CENTS = 50;
const MONEY_SCALE = 100;
const METRIC_SCALE = 1_000_000;
const REGION_PACK_CATALOG_VERSION = GENERATED_REGION_PACK_CATALOG_VERSION || "gadm_regions_v8";
const REGION_PACK_MAP_ASSET_REVISION = `${REGION_PACK_CATALOG_VERSION}:outline-v2`;
const SQL_VARIABLE_SAFE_CHUNK_SIZE = 75;
const REGION_PACK_TILE_CHUNK_SIZE = SQL_VARIABLE_SAFE_CHUNK_SIZE;
const REGION_PACK_PAID_Z_LEVELS = [1, 2, 4, 8, 15, 30];
const REGION_PACK_MAP_MAX_OUTLINE_POINTS = 250_000;
const REGION_OFFER_MAX_TILE_COUNTRY_DISTANCE_DEG = 4.0;
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

function balanceTopUpOptions() {
  return BALANCE_TOP_UP_OPTIONS.map((option) => {
    const amount = normalizeCreditAmount(option.amount_eur);
    const bonusPercent = Math.max(0, Number.parseFloat(option.bonus_percent || 0) || 0);
    const bonus = normalizeCreditAmount(amount * bonusPercent / 100.0);
    const guideProduct = regionProductById(option.guide_region_pack_id);
    const guideSummary = guideProduct ? regionProductPricingSummary(guideProduct) : null;
    const guideAmount = guideProduct && guideSummary
      ? discountedRegionPackAmount(guideSummary.gross_eur, guideProduct.discount_percent)
      : null;
    return {
      amount_eur: amount,
      bonus_percent: bonusPercent,
      bonus_eur: bonus,
      balance_eur: normalizeCreditAmount(amount + bonus),
      guide_region_pack_id: String(option.guide_region_pack_id || "").trim(),
      guide_label: String(option.guide_label || guideProduct && guideProduct.name || "").trim(),
      guide_price_eur: guideAmount ? guideAmount.price : 0,
    };
  });
}

function balanceTopUpOptionForAmount(value) {
  const amount = normalizeCreditAmount(value);
  if (amount <= 0) {
    return null;
  }
  return balanceTopUpOptions().find((option) => Math.abs(option.amount_eur - amount) < 0.001) || null;
}

function balanceTopUpOptionFromCheckoutOption(option) {
  const safe = String(option || "").trim().toLowerCase();
  const match = /(?:balance|top[_-]?up|topup)[_-]?(\d+(?:\.\d+)?)/.exec(safe);
  if (!match) {
    return null;
  }
  return balanceTopUpOptionForAmount(match[1]);
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

function regionProductDirectTileSet(productId, cache = {}) {
  const safeId = String(productId || "").trim();
  if (!safeId) {
    return new Set();
  }
  if (!cache.directTileSets) {
    cache.directTileSets = new Map();
  }
  if (cache.directTileSets.has(safeId)) {
    return cache.directTileSets.get(safeId);
  }
  const set = new Set(normalizeTileKeys(GENERATED_REGION_PACK_TILE_KEYS[safeId] || []));
  cache.directTileSets.set(safeId, set);
  return set;
}

function regionProductContainsGeneratedTileKey(product, tileKey, cache = {}, seenProductIds = new Set()) {
  const key = normalizeTileKey(tileKey);
  const productId = String(product && product.id || "").trim();
  if (!productId || !key) {
    return false;
  }
  if (String(productId).toLowerCase() === "world") {
    return Boolean(parseTileKey(key));
  }
  const memoKey = `${productId}|${key}`;
  if (!cache.membership) {
    cache.membership = new Map();
  } else if (cache.membership.has(memoKey)) {
    return cache.membership.get(memoKey);
  }
  if (seenProductIds.has(productId)) {
    return false;
  }
  seenProductIds.add(productId);

  const directSet = regionProductDirectTileSet(productId, cache);
  if (directSet.has(key)) {
    cache.membership.set(memoKey, true);
    return true;
  }

  const refs = Array.isArray(GENERATED_REGION_PACK_TILE_REFS[productId])
    ? GENERATED_REGION_PACK_TILE_REFS[productId]
    : [];
  for (const ref of refs) {
    const refProduct = regionProductById(ref);
    if (regionProductContainsGeneratedTileKey(refProduct, key, cache, new Set(seenProductIds))) {
      cache.membership.set(memoKey, true);
      return true;
    }
  }

  cache.membership.set(memoKey, false);
  return false;
}

function ownedByFamilyFromTileRows(rows) {
  const ownedByFamily = new Map();
  for (const row of rows || []) {
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
  return ownedByFamily;
}

async function ownedTileRowsForUser(db, userId, deps) {
  await deps.ensureCreditTables(db);
  return await deps.dbAll(
    db,
    `
      SELECT tile_key
      FROM user_tile_entitlements
      WHERE user_id = ?
    `,
    [String(userId || "").trim()],
  );
}

function countryNameByRegionId(regionId) {
  const product = regionProductById(regionId);
  return product && String(product.type || "") === "country" ? String(product.name || "").trim() : "";
}

const INCLUDED_AREA_NEUTRALITY_NOTICE = "Included area labels are provided only to describe possible texture coverage for this data pack. They do not define borders, sovereignty, or political status. Planetka does not draw or decide national borders; this pack simply unlocks texture tiles that may be relevant to the selected area.";
const DISPLAY_AREA_LABEL_BY_ADM0_CODE = new Map([
  ["Z01", "Himalayan Disputed Territories"],
  ["Z02", "Himalayan Disputed Territories"],
  ["Z03", "Himalayan Disputed Territories"],
  ["Z04", "Himalayan Disputed Territories"],
  ["Z05", "Himalayan Disputed Territories"],
  ["Z06", "Himalayan Disputed Territories"],
  ["Z07", "Himalayan Disputed Territories"],
  ["Z08", "Himalayan Disputed Territories"],
  ["Z09", "Himalayan Disputed Territories"],
  ["XPI", "Paracel Islands"],
  ["XSP", "Spratly Islands"],
  ["ZNC", "Northern Cyprus"],
  ["XAD", "Akrotiri and Dhekelia"],
]);

function uniqueDisplayStrings(values) {
  const seen = new Set();
  const result = [];
  for (const value of Array.isArray(values) ? values : []) {
    const label = String(value || "").trim();
    const key = label.toLowerCase();
    if (!label || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(label);
  }
  return result;
}

function regionProductIncludedCountries(product) {
  if (!product) {
    return [];
  }
  const id = String(product.id || "").trim();
  const generated = GENERATED_REGION_PACK_DETAILS[id];
  if (generated && Array.isArray(generated.countries)) {
    return uniqueDisplayStrings(generated.countries
      .map((entry) => {
        const code = String(entry && entry.GID_0 || "").trim().toUpperCase();
        return String(DISPLAY_AREA_LABEL_BY_ADM0_CODE.get(code) || entry && (entry.NAME_1 || entry.name || entry.COUNTRY) || "").trim();
      })
      .filter(Boolean));
  }
  if (String(product.type || "") === "country") {
    const name = String(product.name || "").trim();
    return name ? [name] : [];
  }
  if (!Array.isArray(product.countries)) {
    return [];
  }
  return uniqueDisplayStrings(product.countries
    .map((countryId) => countryNameByRegionId(countryId))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b)));
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

function longitudeDistanceDegrees(a, b) {
  const diff = Math.abs(Number(a) - Number(b));
  if (!Number.isFinite(diff)) {
    return 180.0;
  }
  return Math.min(diff, 360.0 - diff);
}

function pointToBboxDistanceDegrees(latitudeDeg, longitudeDeg, product) {
  const bbox = product && product.bbox || [];
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return 0;
  }
  const lon = clampNumber(longitudeDeg, -180.0, 180.0);
  const lat = clampNumber(latitudeDeg, -90.0, 90.0);
  const minLon = Math.min(Number(bbox[0]), Number(bbox[2]));
  const maxLon = Math.max(Number(bbox[0]), Number(bbox[2]));
  const minLat = Math.min(Number(bbox[1]), Number(bbox[3]));
  const maxLat = Math.max(Number(bbox[1]), Number(bbox[3]));
  const latDistance = lat < minLat ? minLat - lat : lat > maxLat ? lat - maxLat : 0;
  const lonDistance = lon >= minLon && lon <= maxLon
    ? 0
    : Math.min(longitudeDistanceDegrees(lon, minLon), longitudeDistanceDegrees(lon, maxLon));
  return Math.sqrt(latDistance * latDistance + lonDistance * lonDistance);
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

function outlinePointCount(outlines) {
  let count = 0;
  for (const outline of outlines || []) {
    const polygons = Array.isArray(outline && outline.polygons) ? outline.polygons : [];
    for (const ring of polygons) {
      count += Array.isArray(ring) ? ring.length : 0;
    }
  }
  return count;
}

function simplifyRingForMap(ring, stride) {
  const source = Array.isArray(ring) ? ring : [];
  if (source.length <= 4 || stride <= 1) {
    return source;
  }
  const simplified = [];
  for (let index = 0; index < source.length; index += stride) {
    simplified.push(source[index]);
  }
  const last = source[source.length - 1];
  if (last && simplified[simplified.length - 1] !== last) {
    simplified.push(last);
  }
  if (simplified.length >= 3) {
    return simplified;
  }
  return source.slice(0, Math.min(source.length, 4));
}

function regionProductOutlinesForMap(product, maxPoints = REGION_PACK_MAP_MAX_OUTLINE_POINTS) {
  const outlines = regionProductOutlines(product);
  const totalPoints = outlinePointCount(outlines);
  const safeMax = Math.max(500, Number.parseInt(maxPoints, 10) || REGION_PACK_MAP_MAX_OUTLINE_POINTS);
  if (totalPoints <= safeMax) {
    return outlines;
  }
  const stride = Math.max(1, Math.ceil(totalPoints / safeMax));
  return outlines.map((outline) => ({
    id: String(outline && outline.id || ""),
    name: String(outline && outline.name || ""),
    polygons: (Array.isArray(outline && outline.polygons) ? outline.polygons : [])
      .map((ring) => simplifyRingForMap(ring, stride))
    .filter((ring) => Array.isArray(ring) && ring.length >= 3),
  })).filter((outline) => Array.isArray(outline.polygons) && outline.polygons.length);
}

function cleanR2Prefix(env = {}) {
  return String(env.R2_PREFIX || "").trim().replace(/^\/+|\/+$/g, "");
}

function regionPackMapAssetKey(env, regionPackId) {
  const prefix = cleanR2Prefix(env);
  const id = String(regionPackId || "").trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
  const relative = `region_pack_maps/${REGION_PACK_CATALOG_VERSION}/${id}.json`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function regionPackCatalogAssetKey(env) {
  const prefix = cleanR2Prefix(env);
  const relative = `region_pack_maps/${REGION_PACK_CATALOG_VERSION}/catalog.json`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function regionPackMapBackgroundKey(env) {
  const prefix = cleanR2Prefix(env);
  const relative = `region_pack_maps/${REGION_PACK_CATALOG_VERSION}/world_s2_background.jpg`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function isHiddenRegionProduct(product) {
  return Boolean(product && product.hidden);
}

function ownedTilePayloadRows(ownedRows) {
  return (Array.isArray(ownedRows) ? ownedRows : [])
    .map((row) => {
      const parsed = parseTileKey(row && row.tile_key || "");
      if (!parsed) {
        return null;
      }
      return {
        tile_key: parsed.key,
        z: parsed.z,
        d: parsed.d,
        gross_cents: generatedTileGrossCents(parsed.key),
      };
    })
    .filter(Boolean);
}

function regionPackStaticMapPayload(product, token, account, ownedRows, options = {}) {
  return {
    ok: true,
    static_asset_mode: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
    token: String(token || ""),
    catalog_mode: Boolean(options && options.catalogMode),
    asset_id: String(product && product.id || ""),
    region_pack: regionProductPublicPayload(product),
    owned_tiles: ownedTilePayloadRows(ownedRows),
    world_full_quality_unlocked: isWorldFullQualityUnlocked(account),
    success: options && options.success ? options.success : null,
  };
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
  const matches = REGION_PRODUCTS.filter((product) => !isHiddenRegionProduct(product) && pointInRegionProduct(product, latitudeDeg, longitudeDeg));
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

function regionOfferTileLookupKey(parsed) {
  if (!parsed) {
    return "";
  }
  const paidDLevels = paidDLevelsForRegionZ(parsed.z);
  const paidD = paidDLevels.length ? paidDLevels[0] : parsed.d;
  return regionTileKey(parsed.x, parsed.y, parsed.z, paidD);
}

function parsedTileBbox(parsed) {
  if (!parsed) {
    return null;
  }
  const z = Math.max(1, Number.parseInt(parsed.z || 0, 10) || 1);
  return [
    clampNumber(Number(parsed.x) - 180.0, -180.0, 180.0),
    clampNumber(Number(parsed.y) - 90.0, -90.0, 90.0),
    clampNumber(Number(parsed.x) + z - 180.0, -180.0, 180.0),
    clampNumber(Number(parsed.y) + z - 90.0, -90.0, 90.0),
  ];
}

function bboxIntersects(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length < 4 || b.length < 4) {
    return false;
  }
  return Number(a[0]) <= Number(b[2])
    && Number(a[2]) >= Number(b[0])
    && Number(a[1]) <= Number(b[3])
    && Number(a[3]) >= Number(b[1]);
}

function regionProductIntersectsAnyTileBbox(product, parsedTiles) {
  const productBbox = product && product.bbox || [];
  if (!Array.isArray(productBbox) || productBbox.length < 4) {
    return true;
  }
  for (const parsed of parsedTiles) {
    if (bboxIntersects(productBbox, parsedTileBbox(parsed))) {
      return true;
    }
  }
  return false;
}

function finestPaidTilesForRegionOffers(tileKeys) {
  const parsedTiles = normalizeTileKeys(tileKeys)
    .map((key) => parseTileKey(key))
    .filter((parsed) => parsed && parsed.z > 0 && parsed.d > 0 && parsed.d < FREE_D_THRESHOLD);
  if (!parsedTiles.length) {
    return [];
  }
  const minZ = parsedTiles.reduce((best, parsed) => Math.min(best, parsed.z), Number.POSITIVE_INFINITY);
  const zLimit = minZ <= 4 ? Math.max(minZ, minZ * 2) : minZ;
  const seen = new Set();
  const result = [];
  for (const parsed of parsedTiles) {
    if (parsed.z > zLimit) {
      continue;
    }
    const lookupKey = regionOfferTileLookupKey(parsed);
    if (!lookupKey || seen.has(lookupKey)) {
      continue;
    }
    seen.add(lookupKey);
    result.push({
      ...parsed,
      key: lookupKey,
      source_key: parsed.key,
    });
  }
  return result;
}

function regionCountryProductsForTileKeys(tileKeys, latitudeDeg, longitudeDeg, limit = 8) {
  const parsedTiles = finestPaidTilesForRegionOffers(tileKeys);
  if (!parsedTiles.length) {
    return [];
  }
  const lookupKeys = Array.from(new Set(parsedTiles.map((parsed) => parsed.key).filter(Boolean)));
  const cache = {};
  const matches = [];
  for (const product of REGION_PRODUCTS) {
    if (isHiddenRegionProduct(product)) {
      continue;
    }
    const type = String(product && product.type || "").trim().toLowerCase();
    if (type !== "country" && type !== "admin_region") {
      continue;
    }
    if (!regionProductIntersectsAnyTileBbox(product, parsedTiles)) {
      continue;
    }
    let overlap = 0;
    for (const key of lookupKeys) {
      if (regionProductContainsGeneratedTileKey(product, key, cache)) {
        overlap += 1;
      }
    }
    if (overlap > 0) {
      const distanceDeg = pointToBboxDistanceDegrees(latitudeDeg, longitudeDeg, product);
      if (distanceDeg <= REGION_OFFER_MAX_TILE_COUNTRY_DISTANCE_DEG) {
        matches.push({ product, overlap, distanceDeg });
      }
    }
  }
  return matches
    .sort((a, b) => (
      Number(b.overlap || 0) - Number(a.overlap || 0)
      || Number(a.distanceDeg || 0) - Number(b.distanceDeg || 0)
      || bboxArea(a.product) - bboxArea(b.product)
      || String(a.product && a.product.name || "").localeCompare(String(b.product && b.product.name || ""))
    ))
    .slice(0, Math.max(1, Number.parseInt(limit, 10) || 8))
    .map((entry) => entry.product);
}

function regionProductsContainingAnyCountry(countryIds, type, limit = 3) {
  const ids = countryIds instanceof Set ? countryIds : new Set(countryIds || []);
  if (!ids.size) {
    return [];
  }
  const safeType = String(type || "").trim().toLowerCase();
  const matches = [];
  for (const product of REGION_PRODUCTS) {
    if (isHiddenRegionProduct(product)) {
      continue;
    }
    if (String(product && product.type || "").trim().toLowerCase() !== safeType) {
      continue;
    }
    const productCountryIds = regionProductCountryIdSet(product);
    for (const id of ids) {
      if (productCountryIds.has(id)) {
        matches.push(product);
        break;
      }
    }
  }
  return matches
    .sort((a, b) => (
      productSpecificityScore(a) - productSpecificityScore(b)
      || bboxArea(a) - bboxArea(b)
      || String(a.name || "").localeCompare(String(b.name || ""))
    ))
    .slice(0, Math.max(1, Number.parseInt(limit, 10) || 3));
}

function suggestedRegionProductsForContext(latitudeDeg, longitudeDeg, tileKeys = []) {
  const pointProducts = suggestedRegionProductsForPoint(latitudeDeg, longitudeDeg);
  const tileCountryProducts = regionCountryProductsForTileKeys(tileKeys, latitudeDeg, longitudeDeg, 8);
  const selected = [];
  const seen = new Set();
  const addProduct = (product) => {
    const id = String(product && product.id || "").trim();
    if (!id || seen.has(id)) {
      return;
    }
    seen.add(id);
    selected.push(product);
  };
  const isCountryProduct = (product) => {
    const type = String(product && product.type || "").trim().toLowerCase();
    return type === "country" || type === "admin_region";
  };

  for (const product of pointProducts.filter(isCountryProduct)) {
    addProduct(product);
  }
  for (const product of tileCountryProducts) {
    addProduct(product);
  }

  const countryIds = new Set();
  for (const product of selected.filter(isCountryProduct)) {
    for (const countryId of regionProductCountryIdSet(product)) {
      countryIds.add(countryId);
    }
  }

  if (!countryIds.size) {
    for (const product of pointProducts) {
      addProduct(product);
    }
    return selected.slice(0, 8);
  }

  for (const product of regionProductsContainingAnyCountry(countryIds, "macro_region", 3)) {
    addProduct(product);
  }
  for (const product of regionProductsContainingAnyCountry(countryIds, "continent", 1)) {
    addProduct(product);
  }

  return selected.slice(0, 8);
}

function regionProductRank(product) {
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "country" || type === "admin_region") {
    return 1;
  }
  if (type === "macro_region") {
    return 2;
  }
  if (type === "continent") {
    return 3;
  }
  if (type === "world") {
    return 4;
  }
  return 0;
}

function regionProductCountryIdSet(product, seenProductIds = new Set()) {
  const id = String(product && product.id || "").trim();
  if (!id || seenProductIds.has(id)) {
    return new Set();
  }
  seenProductIds.add(id);
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "country" || type === "admin_region") {
    return new Set([id]);
  }
  const result = new Set();
  const countryIds = Array.isArray(product && product.countries) ? product.countries : [];
  for (const countryId of countryIds) {
    const child = regionProductById(countryId);
    if (child) {
      for (const nestedId of regionProductCountryIdSet(child, seenProductIds)) {
        result.add(nestedId);
      }
    } else {
      const safeId = String(countryId || "").trim();
      if (safeId) {
        result.add(safeId);
      }
    }
  }
  if (!result.size && type === "world") {
    for (const candidate of REGION_PRODUCTS) {
      if (String(candidate && candidate.type || "").trim().toLowerCase() === "country") {
        const candidateId = String(candidate && candidate.id || "").trim();
        if (candidateId) {
          result.add(candidateId);
        }
      }
    }
  }
  return result;
}

function regionProductsShareCountry(productA, productB) {
  const a = regionProductCountryIdSet(productA);
  const b = regionProductCountryIdSet(productB);
  if (!a.size || !b.size) {
    return false;
  }
  for (const id of a) {
    if (b.has(id)) {
      return true;
    }
  }
  return false;
}

function relatedHigherRegionProducts(product, limit = 3) {
  const currentRank = regionProductRank(product);
  const currentId = String(product && product.id || "").trim();
  if (!currentId || currentRank <= 0) {
    return [];
  }
  return REGION_PRODUCTS
    .filter((candidate) => {
      const candidateId = String(candidate && candidate.id || "").trim();
      if (!candidateId || candidateId === currentId) {
        return false;
      }
      const candidateRank = regionProductRank(candidate);
      if (candidateRank <= currentRank) {
        return false;
      }
      // World is deliberately not shown as a contextual upsell yet.
      if (candidateRank >= 4) {
        return false;
      }
      return regionProductsShareCountry(product, candidate);
    })
    .sort((a, b) => (
      regionProductRank(a) - regionProductRank(b)
      || productSpecificityScore(a) - productSpecificityScore(b)
      || bboxArea(a) - bboxArea(b)
      || String(a.name || "").localeCompare(String(b.name || ""))
    ))
    .slice(0, Math.max(0, Number.parseInt(limit, 10) || 3));
}

function isSameOrRelatedHigherRegionProduct(baseProduct, requestedProduct) {
  const baseId = String(baseProduct && baseProduct.id || "").trim();
  const requestedId = String(requestedProduct && requestedProduct.id || "").trim();
  if (!baseId || !requestedId) {
    return false;
  }
  if (baseId === requestedId) {
    return true;
  }
  return relatedHigherRegionProducts(baseProduct, 12)
    .some((product) => String(product && product.id || "").trim() === requestedId);
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

function estimateRegionPackSummaryWithOwned(product, account, ownedByFamily, options = {}) {
  const summary = regionProductPricingSummary(product);
  if (!summary) {
    return { error: "missing_region_pack_summary" };
  }
  const discountPercent = Math.max(0, Math.min(95, Number.parseInt(product && product.discount_percent || 0, 10) || 0));
  if (isWorldFullQualityUnlocked(account)) {
    const alreadyLicencedAmounts = discountedRegionPackAmount(summary.gross_eur, discountPercent);
    return {
      ok: true,
      summary_estimate: true,
      world_full_quality_unlocked: true,
      region_pack: regionProductPublicPayload(product),
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      discount_percent: discountPercent,
      gross_eur: 0,
      gross_price_eur: 0,
      discount_eur: 0,
      already_licenced_gross_eur: alreadyLicencedAmounts.gross,
      already_licenced_saving_eur: alreadyLicencedAmounts.price,
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
  const membershipCache = options && options.membershipCache || {};
  const upgradeOwnedKeys = [];
  let alreadyLicencedCount = 0;
  let coveredCents = 0;
  let coveredPaidTileCount = 0;
  for (const entries of ownedByFamily.values()) {
    if (!Array.isArray(entries) || !entries.length) {
      continue;
    }
    const owned = parseTileKey(entries[0] && entries[0].key || "");
    if (!owned || isFreeCreditTileKey(owned.key)) {
      continue;
    }
    const paidDLevels = paidDLevelsForRegionZ(owned.z);
    if (!paidDLevels.length) {
      continue;
    }
    const packD = paidDLevels[0];
    const packKey = regionTileKey(owned.x, owned.y, owned.z, packD);
    if (!packKey || isFreeCreditTileKey(packKey)) {
      continue;
    }
    if (!regionProductContainsGeneratedTileKey(product, packKey, membershipCache)) {
      continue;
    }

    const coveredByFiner = entries.some((entry) => Number(entry.d) <= Number(packD));
    if (coveredByFiner) {
      alreadyLicencedCount += 1;
      const cents = generatedTileGrossCents(packKey);
      coveredCents += cents;
      if (cents > 0) {
        coveredPaidTileCount += 1;
      }
      continue;
    }
    const coarserEntries = entries.filter((entry) => Number(entry.d) > Number(packD));
    for (const entry of coarserEntries) {
      upgradeOwnedKeys.push(entry.key);
    }
  }

  let coveredGrossEur = normalizeCreditAmount(coveredCents / 100.0);
  if (coveredPaidTileCount > 0 && coveredPaidTileCount >= summary.paid_tile_count) {
    coveredGrossEur = summary.gross_eur;
    coveredPaidTileCount = summary.paid_tile_count;
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
  const alreadyLicencedAmounts = discountedRegionPackAmount(coveredGrossEur, discountPercent);
  const paidTileCount = Math.max(0, summary.paid_tile_count - coveredPaidTileCount);
  const freeTileCount = Math.max(0, summary.tile_count - paidTileCount);
  const newLicensableCount = paidTileCount;
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
    already_licenced_gross_eur: alreadyLicencedAmounts.gross,
    already_licenced_saving_eur: alreadyLicencedAmounts.price,
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

async function estimateRegionPackSummary(db, userId, product, deps) {
  await deps.ensureCreditTables(db);
  const account = await ensureCreditAccount(db, userId, deps);
  const ownedRows = await ownedTileRowsForUser(db, userId, deps);
  return estimateRegionPackSummaryWithOwned(
    product,
    account,
    ownedByFamilyFromTileRows(ownedRows),
  );
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
  const alreadyLicencedGrossEur = normalizeCreditAmount((Array.isArray(gross && gross.excluded_tiles) ? gross.excluded_tiles : []).reduce(
    (total, row) => total + normalizeCreditAmount(row && (row.gross_price_eur ?? row.gross_credits ?? row.price_eur ?? row.credits)),
    0,
  ));
  const alreadyLicencedAmounts = discountedRegionPackAmount(alreadyLicencedGrossEur, discountPercent);
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
    already_licenced_gross_eur: alreadyLicencedAmounts.gross,
    already_licenced_saving_eur: alreadyLicencedAmounts.price,
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

function billableLandKm2FromGeneratedGrossCents(tileKey, grossCents) {
  const cents = Math.max(0, Number.parseInt(grossCents || 0, 10) || 0);
  if (cents <= 0) {
    return 0;
  }
  const parsed = parseTileKey(tileKey);
  if (!parsed) {
    return 0;
  }
  const mpp = deliveredMppForD(parsed.d);
  const qualityFactor = (DATASET_BASE_MPP / Math.max(DATASET_BASE_MPP, mpp)) ** 2;
  if (!Number.isFinite(qualityFactor) || qualityFactor <= 0) {
    return 0;
  }
  return normalizeMetricAmount((cents / 100.0) * EQUATOR_Z001_AREA_KM2 / qualityFactor);
}

async function estimateRegionPackForMap(db, userId, product, deps) {
  if (!product) {
    return { error: "unknown_region_pack" };
  }
  await deps.ensureCreditTables(db);
  const account = await ensureCreditAccount(db, userId, deps);
  if (String(product && product.id || "").trim().toLowerCase() === "world") {
    return estimateRegionPack(db, userId, product, deps, { includeRows: false });
  }

  const ownedRows = await ownedTileRowsForUser(db, userId, deps);
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
    ownedByFamily.get(family).push({
      key: owned.key,
      d: Number(owned.d),
      value: generatedTileGrossEur(owned.key),
    });
  }

  const worldFullQualityUnlocked = isWorldFullQualityUnlocked(account);
  const tileKeys = regionProductTileKeys(product).sort((a, b) => {
    const parsedA = parseTileKey(a);
    const parsedB = parseTileKey(b);
    const familyA = tileFamilyKey(parsedA);
    const familyB = tileFamilyKey(parsedB);
    if (familyA !== familyB) {
      return familyA < familyB ? -1 : 1;
    }
    return Number(parsedA && parsedA.d || 0) - Number(parsedB && parsedB.d || 0);
  });

  let credits = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;
  let alreadyLicencedGross = 0;
  const tiles = [];
  const newTiles = [];
  const excludedTiles = [];

  for (const tileKey of tileKeys) {
    const parsed = parseTileKey(tileKey);
    const family = tileFamilyKey(parsed);
    if (!parsed || !family) {
      continue;
    }
    const grossCents = generatedTileGrossCents(tileKey);
    const grossCredits = normalizeCreditAmount(grossCents / 100.0);
    const globallyFree = Boolean(isFreeCreditTileKey(tileKey) || grossCents <= 0);
    const familyEntitlements = ownedByFamily.get(family) || [];
    if (!ownedByFamily.has(family)) {
      ownedByFamily.set(family, familyEntitlements);
    }
    const coveredByFiner = Boolean(worldFullQualityUnlocked)
      || familyEntitlements.some((entry) => Number(entry.d) <= Number(parsed.d));
    const coarserCredit = Math.max(
      0,
      ...familyEntitlements
        .filter((entry) => Number(entry.d) > Number(parsed.d))
        .map((entry) => normalizeCreditAmount(entry.value)),
    );
    const tileCredits = (globallyFree || coveredByFiner)
      ? 0
      : normalizeCreditAmount(Math.max(0, grossCredits - coarserCredit));
    const landKm2 = billableLandKm2FromGeneratedGrossCents(tileKey, grossCents);
    const row = {
      tile_key: tileKey,
      credits: tileCredits,
      price_eur: tileCredits,
      gross_credits: grossCredits,
      gross_price_eur: grossCredits,
      land_km2: landKm2,
      billable_land_km2: landKm2,
      already_owned: Boolean(coveredByFiner),
      globally_free: Boolean(globallyFree),
      free_reason: globallyFree
        ? (freeReasonForTile(parsed) || "no_billable_land")
        : (coveredByFiner ? "already_unlocked" : ""),
    };
    if (coarserCredit > 0) {
      row.upgrade_credit_applied = coarserCredit;
    }
    tiles.push(row);
    if (coveredByFiner) {
      excludedTiles.push(row);
      alreadyLicencedGross = normalizeCreditAmount(alreadyLicencedGross + grossCredits);
    }
    if (tileCredits > 0) {
      paidTileCount += 1;
      credits = normalizeCreditAmount(credits + tileCredits);
    } else {
      freeTileCount += 1;
    }
    if (!globallyFree && !coveredByFiner) {
      newTiles.push(row);
      familyEntitlements.push({ key: tileKey, d: Number(parsed.d), value: grossCredits });
    }
  }

  const discountPercent = Math.max(0, Math.min(95, Number.parseInt(product.discount_percent || 0, 10) || 0));
  const amounts = discountedRegionPackAmount(credits, discountPercent);
  const alreadyLicencedAmounts = discountedRegionPackAmount(alreadyLicencedGross, discountPercent);
  return {
    ok: true,
    map_estimate: true,
    region_pack: regionProductPublicPayload(product),
    region_pack_id: String(product.id || ""),
    region_pack_name: String(product.name || ""),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    discount_percent: discountPercent,
    gross_eur: amounts.gross,
    gross_price_eur: amounts.gross,
    discount_eur: amounts.discount,
    already_licenced_gross_eur: alreadyLicencedAmounts.gross,
    already_licenced_saving_eur: alreadyLicencedAmounts.price,
    credits: amounts.price,
    price_eur: amounts.price,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: tiles.length,
    new_tile_count: newTiles.length,
    new_tiles: newTiles,
    excluded_tiles: excludedTiles,
    integrity_warnings: [],
    metadata_missing_tile_keys: [],
    tiles,
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
      full_price_eur: normalizeCreditAmount(grossCents / 100.0),
      normal_price_eur: normalizeCreditAmount(grossCents / 100.0),
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

function buildRegionPackUpsellCardData(product, estimate) {
  const tileRows = allocatedRegionPackTileRows(estimate);
  const productSummary = regionProductPricingSummary(product) || {};
  const fullPriceEur = normalizeCreditAmount(productSummary.gross_eur);
  const chargeableFullPriceEur = normalizeCreditAmount(estimate && estimate.gross_eur);
  const levels = Array.from(new Set(tileRows.map((row) => row.z).filter((z) => Number.isFinite(z))))
    .sort((a, b) => a - b);
  const displayLevel = levels.length ? levels[0] : null;
  const displayTiles = displayLevel === null
    ? []
    : tileRows.filter((row) => Number(row.z) === Number(displayLevel));
  const detail = GENERATED_REGION_PACK_DETAILS[String(product && product.id || "")] || {};
  return {
    region_pack: regionProductPublicPayload(product),
    bounds: regionMapBounds(product, detail, displayTiles.length ? displayTiles : tileRows),
    display_level: displayLevel,
    tiles: displayTiles,
    summary: {
      new_tiles: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
      full_price_eur: fullPriceEur,
      already_licenced_deduction_eur: normalizeCreditAmount(Math.max(0, fullPriceEur - chargeableFullPriceEur)),
      discount_percent: Math.max(0, Number.parseInt(estimate && estimate.discount_percent || 0, 10) || 0),
      discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
      price_eur: normalizeCreditAmount(estimate && estimate.price_eur),
    },
  };
}

function buildRegionPackMapData(product, estimate, options = {}) {
  const id = String(product && product.id || "");
  const detail = GENERATED_REGION_PACK_DETAILS[id] || {};
  const productSummary = regionProductPricingSummary(product) || {};
  const fullPriceEur = normalizeCreditAmount(productSummary.gross_eur);
  const chargeableFullPriceEur = normalizeCreditAmount(estimate && estimate.gross_eur);
  const tileRows = allocatedRegionPackTileRows(estimate);
  const countries = regionProductIncludedCountries(product);
  const levels = Array.from(new Set(tileRows.map((row) => row.z).filter((z) => Number.isFinite(z))))
    .sort((a, b) => a - b);
  return {
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
    token: String(options && options.token || ""),
    catalog_mode: Boolean(options && options.catalogMode),
    generated_detail_available: Boolean(detail && Object.keys(detail).length),
    region_pack: regionProductPublicPayload(product),
    included_countries: countries,
    outlines: regionProductOutlinesForMap(product),
    bounds: regionMapBounds(product, detail, tileRows),
    levels,
    summary: {
      new_tiles: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
      already_licenced_saving_eur: normalizeCreditAmount(Math.max(0, fullPriceEur - chargeableFullPriceEur)),
      already_licenced_deduction_eur: normalizeCreditAmount(Math.max(0, fullPriceEur - chargeableFullPriceEur)),
      full_price_eur: fullPriceEur,
      discount_percent: Math.max(0, Number.parseInt(estimate && estimate.discount_percent || 0, 10) || 0),
      discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
      price_eur: normalizeCreditAmount(estimate && estimate.price_eur),
      tile_price_sum_eur: normalizeCreditAmount(tileRows.reduce((total, row) => total + normalizeCreditAmount(row.price_eur), 0)),
    },
    tiles: tileRows,
    upsells: Array.isArray(options && options.upsells) ? options.upsells : [],
    success: options && options.success ? options.success : null,
  };
}

function expandedMapBounds(bounds, paddingFraction = 0.08) {
  const minLon = Number(bounds && bounds.min_lon);
  const minLat = Number(bounds && bounds.min_lat);
  const maxLon = Number(bounds && bounds.max_lon);
  const maxLat = Number(bounds && bounds.max_lat);
  if (![minLon, minLat, maxLon, maxLat].every(Number.isFinite)) {
    return { min_lon: -10, min_lat: 35, max_lon: 30, max_lat: 47.5 };
  }
  const width = Math.max(0.5, maxLon - minLon);
  const height = Math.max(0.5, maxLat - minLat);
  const padLon = width * Math.max(0, Number(paddingFraction) || 0);
  const padLat = height * Math.max(0, Number(paddingFraction) || 0);
  return {
    min_lon: clampNumber(minLon - padLon, -180, 180),
    min_lat: clampNumber(minLat - padLat, -90, 90),
    max_lon: clampNumber(maxLon + padLon, -180, 180),
    max_lat: clampNumber(maxLat + padLat, -90, 90),
  };
}

function tileRowsCenter(tileRows) {
  const rows = Array.isArray(tileRows) ? tileRows : [];
  if (!rows.length) {
    return null;
  }
  const bounds = regionMapBounds(null, null, rows);
  return {
    latitude_deg: (Number(bounds.min_lat) + Number(bounds.max_lat)) / 2.0,
    longitude_deg: (Number(bounds.min_lon) + Number(bounds.max_lon)) / 2.0,
    bounds,
  };
}

function contextRegionProductForTileRows(tileRows) {
  const center = tileRowsCenter(tileRows);
  if (!center) {
    return null;
  }
  const products = suggestedRegionProductsForPoint(center.latitude_deg, center.longitude_deg);
  return products.length ? products[0] : null;
}

function buildSceneFullQualityMapData(estimate, options = {}) {
  const tileRows = allocatedRegionPackTileRows(estimate);
  const contextProduct = options && options.contextProduct ? options.contextProduct : contextRegionProductForTileRows(tileRows);
  const contextDetail = GENERATED_REGION_PACK_DETAILS[String(contextProduct && contextProduct.id || "")] || {};
  const contextCountries = contextProduct ? regionProductIncludedCountries(contextProduct) : [];
  const levels = Array.from(new Set(tileRows.map((row) => row.z).filter((z) => Number.isFinite(z))))
    .sort((a, b) => a - b);
  const tileBounds = regionMapBounds(null, null, tileRows);
  const contextBounds = contextProduct
    ? regionMapBounds(contextProduct, contextDetail, tileRows)
    : expandedMapBounds(tileBounds, 0.18);
  const fullPrice = normalizeCreditAmount(tileRows.reduce((total, row) => total + normalizeCreditAmount(row.full_price_eur), 0));
  const alreadyLicencedSaving = normalizeCreditAmount(tileRows
    .filter((row) => String(row.status || "") === "licenced")
    .reduce((total, row) => total + normalizeCreditAmount(row.full_price_eur), 0));
  return {
    ok: true,
    scene_detail: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
    token: String(options && options.token || ""),
    catalog_mode: true,
    generated_detail_available: Boolean(contextProduct && Object.keys(contextDetail).length),
    region_pack: {
      id: "scene",
      name: "This Scene",
      type: "scene",
      discount_percent: 0,
      catalog_version: REGION_PACK_CATALOG_VERSION,
      included_countries: contextCountries,
    },
    included_countries: contextCountries,
    outlines: contextProduct ? regionProductOutlinesForMap(contextProduct) : [],
    bounds: contextBounds,
    tile_bounds: tileBounds,
    levels,
    summary: {
      new_tiles: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
      already_licenced_saving_eur: alreadyLicencedSaving,
      already_licenced_deduction_eur: alreadyLicencedSaving,
      full_price_eur: fullPrice,
      discount_percent: 0,
      discount_eur: 0,
      price_eur: normalizeCreditAmount(estimate && estimate.price_eur),
      tile_price_sum_eur: normalizeCreditAmount(tileRows.reduce((total, row) => total + normalizeCreditAmount(row.price_eur), 0)),
    },
    tiles: tileRows,
    upsells: Array.isArray(options && options.upsells) ? options.upsells : [],
    success: options && options.success ? options.success : null,
  };
}

function regionProductCatalogGroup(product) {
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "world") {
    return { key: "world", label: "World" };
  }
  if (type === "continent") {
    return { key: "continents", label: "Continents" };
  }
  if (type === "macro_region") {
    return { key: "regions", label: "Regions" };
  }
  const adm1Codes = Array.isArray(product && product.adm1_codes) ? product.adm1_codes : [];
  if (adm1Codes.length) {
    return { key: "states_provinces", label: "States / Provinces" };
  }
  if (type === "country" || type === "admin_region") {
    return { key: "countries", label: "Countries" };
  }
  return { key: "other", label: "Other Data Packs" };
}

function regionPackCatalogRow(product, estimate) {
  const productSummary = regionProductPricingSummary(product) || {};
  const group = regionProductCatalogGroup(product);
  return {
    id: String(product && product.id || ""),
    name: String(product && product.name || ""),
    type: String(product && product.type || ""),
    group_key: group.key,
    group_label: group.label,
    total_tiles: Math.max(0, Number.parseInt(productSummary.tile_count || estimate && estimate.tile_count || 0, 10) || 0),
    new_tiles: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
    already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
    full_price_eur: normalizeCreditAmount(productSummary.gross_eur),
    chargeable_full_price_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
    already_licenced_saving_eur: normalizeCreditAmount(estimate && estimate.already_licenced_saving_eur),
    discount_percent: Math.max(0, Number.parseInt(estimate && estimate.discount_percent || product && product.discount_percent || 0, 10) || 0),
    discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
    price_eur: normalizeCreditAmount(estimate && estimate.price_eur),
  };
}

async function buildRegionPackCatalogData(db, userId, token, deps) {
  await deps.ensureCreditTables(db);
  const account = await ensureCreditAccount(db, userId, deps);
  const ownedRows = await ownedTileRowsForUser(db, userId, deps);
  const ownedByFamily = ownedByFamilyFromTileRows(ownedRows);
  const membershipCache = { directTileSets: new Map(), membership: new Map() };
  const rows = REGION_PRODUCTS
    .map((product) => {
      const estimate = estimateRegionPackSummaryWithOwned(product, account, ownedByFamily, { membershipCache });
      if (!estimate || estimate.error) {
        return null;
      }
      return regionPackCatalogRow(product, estimate);
    })
    .filter(Boolean)
    .sort((a, b) => (
      String(a.group_label || "").localeCompare(String(b.group_label || ""))
      || String(a.name || "").localeCompare(String(b.name || ""))
    ));
  const groupOrder = ["world", "continents", "regions", "countries", "states_provinces", "other"];
  const groups = [];
  for (const key of groupOrder) {
    const groupRows = rows.filter((row) => String(row.group_key || "") === key);
    if (!groupRows.length) {
      continue;
    }
    groups.push({
      key,
      label: String(groupRows[0].group_label || key),
      rows: groupRows,
    });
  }
  return {
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    token: String(token || ""),
    total_packs: rows.length,
    groups,
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

async function ensureSceneFullQualityDetailTokenTable(db, deps) {
  await deps.ensureCreditTables(db);
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS scene_full_quality_detail_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        tile_keys_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await deps.dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_scene_full_quality_detail_tokens_expires ON scene_full_quality_detail_tokens(expires_at)`,
  );
}

async function ensureBalanceTopUpTokenTable(db, deps) {
  await deps.ensureCreditTables(db);
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS balance_top_up_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await deps.dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_balance_top_up_tokens_expires ON balance_top_up_tokens(expires_at)`,
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

async function createRegionPackDetailTokenForUser(db, userId, regionPackId, env, deps) {
  await ensureRegionPackDetailTokenTable(db, deps);
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
    [token, String(userId || "").trim(), String(regionPackId || "").trim(), now, expiresAt],
  );
  return { token, expires_at: expiresAt };
}

async function createBalanceTopUpTokenForUser(db, userId, env, deps) {
  await ensureBalanceTopUpTokenTable(db, deps);
  const now = deps.nowIso();
  await deps.dbRun(db, `DELETE FROM balance_top_up_tokens WHERE expires_at <= ?`, [now]);
  const token = deps.randomToken(32);
  const expiresAt = addMinutesIsoFromDeps(deps, regionPackDetailTokenTtlMinutes(env));
  await deps.dbRun(
    db,
    `
      INSERT INTO balance_top_up_tokens (
        token, user_id, created_at, expires_at
      ) VALUES (?, ?, ?, ?)
    `,
    [token, String(userId || "").trim(), now, expiresAt],
  );
  return { token, expires_at: expiresAt };
}

async function createSceneFullQualityDetailTokenForUser(db, userId, tileKeys, env, deps) {
  await ensureSceneFullQualityDetailTokenTable(db, deps);
  const keys = normalizeTileKeys(tileKeys);
  const now = deps.nowIso();
  await deps.dbRun(db, `DELETE FROM scene_full_quality_detail_tokens WHERE expires_at <= ?`, [now]);
  const token = deps.randomToken(32);
  const expiresAt = addMinutesIsoFromDeps(deps, regionPackDetailTokenTtlMinutes(env));
  await deps.dbRun(
    db,
    `
      INSERT INTO scene_full_quality_detail_tokens (
        token, user_id, tile_keys_json, created_at, expires_at
      ) VALUES (?, ?, ?, ?, ?)
    `,
    [token, String(userId || "").trim(), JSON.stringify(keys), now, expiresAt],
  );
  return { token, expires_at: expiresAt };
}

function regionPackMapHtml(data) {
  const pack = data && data.region_pack || {};
  const name = String(pack.name || "Region Pack").trim() || "Region Pack";
  const isSceneDetail = Boolean(data && data.scene_detail);
  const countries = Array.isArray(data && data.included_countries) ? data.included_countries : [];
  const summary = data && data.summary || {};
  const success = data && data.success && typeof data.success === "object" ? data.success : null;
  const tokenParam = escapeHtmlText(encodeURIComponent(String(data && data.token || "")));
  const packIdParam = escapeHtmlText(encodeURIComponent(String(pack && pack.id || "")));
  const catalogParam = data && data.catalog_mode ? "&catalog=1" : "";
  const primaryBuyHref = !isSceneDetail && packIdParam
    ? `/credits/region-pack-checkout?token=${tokenParam}&region_pack_id=${packIdParam}${catalogParam}`
    : "";
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
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:22px;margin-top:4px}.card.final-price{border-color:#8f732f;box-shadow:0 0 0 1px rgba(217,164,65,.16) inset}.card.final-price b{font-size:26px}.buy-now{width:100%;font-size:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select{background:#262626;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px}svg{width:100%;height:auto;background:#0d1118;border:1px solid var(--line);border-radius:10px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0}.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}.new{background:var(--new)}.licenced{background:var(--licenced)}.free{background:var(--free)}
.countries{columns:2;column-gap:26px}.countries div{break-inside:avoid;margin:2px 0}.small{font-size:13px}
.upsells{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.upsell{background:#151515;border:1px solid var(--line);border-radius:12px;padding:12px}.upsell h3{margin:0 0 8px;font-size:18px}.upsell p{margin:6px 0}.upsell svg{aspect-ratio:1/1;min-height:0}.button{display:inline-flex;align-items:center;justify-content:center;margin-top:10px;padding:9px 12px;border-radius:8px;background:#d9a441;color:#111;text-decoration:none;font-weight:700}.button.secondary{margin-left:8px;background:#2a2a2a;color:var(--text);border:1px solid var(--line)}
</style>
</head>
<body>
<main>
<h1>${isSceneDetail ? "Full Quality Textures for This Scene" : `${escapeHtmlText(name)} Full Quality Pack`}</h1>
	${success ? `<section class="panel"><h2>${escapeHtmlText(success.title || "Payment successful")}</h2><p>${escapeHtmlText(success.message || "Your Planetka purchase has been processed.")}</p></section>` : ""}
	<section class="cards">
	<div class="card"><span>New / Total Tiles</span><b>${Number(summary.new_tiles || 0)} / ${Number(summary.total_tiles || 0)}</b></div>
	<div class="card"><span>Full Price</span><b>€${Number(summary.full_price_eur || 0).toFixed(2)}</b></div>
	<div class="card"><span>Already Licenced</span><b>-€${Number(summary.already_licenced_deduction_eur ?? summary.already_licenced_saving_eur ?? 0).toFixed(2)}</b></div>
	<div class="card"><span>Volume Discount</span><b>${Number(summary.discount_percent || 0)}% (-€${Number(summary.discount_eur || 0).toFixed(2)})</b></div>
	<div class="card final-price"><span>Final Price</span><b>€${Number(summary.price_eur || 0).toFixed(2)}</b>${primaryBuyHref && Number(summary.price_eur || 0) > 0 ? `<a class="button buy-now" href="${primaryBuyHref}">Buy Now</a>` : ""}</div>
	</section>
<section class="panel">
<div class="toolbar">
<label>Detail level <select id="levelSelect"></select></label>
<span id="levelSummary" class="muted"></span>
</div>
<p class="muted small">Included detail levels are part of the Full Quality pack and are required for reliable Planetka rendering across different camera distances.</p>
<svg id="map" role="img" aria-label="${escapeHtmlText(name)} tile map"></svg>
<p class="muted small">Tile prices shown on hover are user-specific: already licenced tiles are €0.00.</p>
<div class="legend">
<span><i class="swatch new"></i>New in this pack</span>
<span><i class="swatch licenced"></i>Already licenced</span>
<span><i class="swatch free"></i>Free / not charged</span>
</div>
</section>
${countries.length ? `<section class="panel">
<h2>${isSceneDetail ? "Map Context" : "Included Area Labels"}</h2>
<p class="muted small">${escapeHtmlText(INCLUDED_AREA_NEUTRALITY_NOTICE)}</p>
<div class="countries">${countries.map((country) => `<div>${escapeHtmlText(country)}</div>`).join("")}</div>
</section>` : ""}
${Array.isArray(data && data.upsells) && data.upsells.length ? `<section class="panel">
<h2>Larger Full Quality options</h2>
<div id="upsellGrid" class="upsells"></div>
</section>` : ""}
<section class="panel">
<a class="button secondary" href="/credits/region-pack-catalog?token=${tokenParam}">View all Full Quality data packs</a>
</section>
</main>
<script>const DATA=${payload};
const NS="http://www.w3.org/2000/svg";
const fmt=(v)=>"€"+Number(v||0).toFixed(2);
const MAP_BG="/credits/region-pack-map-background.jpg?v="+encodeURIComponent(String(DATA.catalog_version||DATA.token||Date.now()));
const bounds=DATA.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};
const pad=20, innerW=1000, aspect=Math.max(0.28,Math.min(0.9,(bounds.max_lat-bounds.min_lat)/Math.max(1e-6,bounds.max_lon-bounds.min_lon)));
const W=innerW, H=Math.round(innerW*aspect)+pad*2;
function xy(lon,lat){return [pad+((lon-bounds.min_lon)/(bounds.max_lon-bounds.min_lon||1))*(W-pad*2),pad+((bounds.max_lat-lat)/(bounds.max_lat-bounds.min_lat||1))*(H-pad*2)]}
function el(name,attrs){const node=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs||{})){node.setAttribute(k,String(v))}return node}
function addMapBackground(svg,project,width,height){svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#0d1118"}));const tl=project(-180,90),br=project(180,-90);svg.appendChild(el("image",{href:MAP_BG,x:tl[0],y:tl[1],width:br[0]-tl[0],height:br[1]-tl[1],preserveAspectRatio:"none",opacity:"0.22"}));svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#05070a",opacity:"0.48"}))}
function pathFor(poly){return poly.map((pt,i)=>{const p=xy(pt[0],pt[1]);return (i?"L":"M")+p[0].toFixed(2)+" "+p[1].toFixed(2)}).join(" ")}
function render(level){const svg=document.getElementById("map");svg.replaceChildren();svg.setAttribute("viewBox","0 0 "+W+" "+H);
  addMapBackground(svg,xy,W,H);
  for(const outline of DATA.outlines||[]){for(const poly of outline.polygons||[]){const p=el("path",{d:pathFor(poly),fill:"none",stroke:"var(--country-line)","stroke-width":"0.7",opacity:"0.72"});const t=el("title",{});t.textContent=outline.name; p.appendChild(t); svg.appendChild(p);}}
  const rows=(DATA.tiles||[]).filter(t=>Number(t.z)===Number(level)); let newCount=0, licencedCount=0, freeCount=0, price=0;
  for(const tile of rows){const a=xy(tile.lon_min,tile.lat_max), b=xy(tile.lon_max,tile.lat_min); const cls=tile.status==="new"?"var(--new)":(tile.status==="licenced"?"var(--licenced)":"var(--free)");
    if(tile.status==="new"){newCount++; price+=Number(tile.price_eur||0)} else if(tile.status==="licenced"){licencedCount++} else {freeCount++}
    const r=el("rect",{x:a[0],y:a[1],width:Math.max(1,b[0]-a[0]),height:Math.max(1,b[1]-a[1]),fill:cls,stroke:"#fff","stroke-width":"0.45",opacity:tile.status==="new"?"0.58":"0.43"});
    const title=el("title",{}); title.textContent=tile.tile_key+"\\nLand: "+Number(tile.billable_land_km2||0).toFixed(2)+" km²"+"\\nStatus: "+tile.status+"\\nFull price: "+fmt(tile.full_price_eur)+"\\nFinal price: "+fmt(tile.price_eur); r.appendChild(title); svg.appendChild(r);}
  document.getElementById("levelSummary").textContent=rows.length+" tiles at z"+String(level).padStart(3,"0")+" · new "+newCount+" · already licenced "+licencedCount+" · free "+freeCount+" · visible-level price "+fmt(price);
}
const levels=(DATA.levels&&DATA.levels.length?DATA.levels:[1]); const select=document.getElementById("levelSelect");
for(const z of levels){const o=document.createElement("option");o.value=String(z);o.textContent="z"+String(z).padStart(3,"0");select.appendChild(o)}
select.addEventListener("change",()=>render(Number(select.value))); render(Number(select.value||levels[0]));
function miniFrame(bounds,w,h){const p=12,lonSpan=Math.max(1e-6,bounds.max_lon-bounds.min_lon),latSpan=Math.max(1e-6,bounds.max_lat-bounds.min_lat),scale=Math.min((w-p*2)/lonSpan,(h-p*2)/latSpan),usedW=lonSpan*scale,usedH=latSpan*scale;return{bounds,scale,ox:(w-usedW)/2,oy:(h-usedH)/2}}
function miniXY(frame,lon,lat){return [frame.ox+(lon-frame.bounds.min_lon)*frame.scale,frame.oy+(frame.bounds.max_lat-lat)*frame.scale]}
function renderMiniMap(svg,card){const b=card.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const w=360,h=360,frame=miniFrame(b,w,h);svg.setAttribute("viewBox","0 0 "+w+" "+h);svg.setAttribute("preserveAspectRatio","xMidYMid meet");svg.replaceChildren();addMapBackground(svg,(lon,lat)=>miniXY(frame,lon,lat),w,h);for(const tile of card.tiles||[]){const a=miniXY(frame,tile.lon_min,tile.lat_max),c=miniXY(frame,tile.lon_max,tile.lat_min);const cls=tile.status==="new"?"var(--new)":(tile.status==="licenced"?"var(--licenced)":"var(--free)");const r=el("rect",{x:a[0],y:a[1],width:Math.max(1,c[0]-a[0]),height:Math.max(1,c[1]-a[1]),fill:cls,stroke:"#fff","stroke-width":"0.5",opacity:tile.status==="new"?"0.58":"0.43"});svg.appendChild(r)}}
function renderUpsells(){const grid=document.getElementById("upsellGrid");if(!grid)return;const token=encodeURIComponent(DATA.token||"");const catalog=DATA.catalog_mode?"&catalog=1":"";for(const card of DATA.upsells||[]){const pack=card.region_pack||{},s=card.summary||{};const id=encodeURIComponent(pack.id||"");const div=document.createElement("div");div.className="upsell";const title=document.createElement("h3");title.textContent=pack.name||"Region Pack";div.appendChild(title);const map=document.createElementNS(NS,"svg");div.appendChild(map);renderMiniMap(map,card);const meta=document.createElement("p");meta.className="muted small";meta.textContent=Number(s.new_tiles||0)+" new tiles · "+Number(s.discount_percent||0)+"% volume discount · "+fmt(s.price_eur);div.appendChild(meta);const checkout=document.createElement("a");checkout.className="button";checkout.href="/credits/region-pack-checkout?token="+token+"&region_pack_id="+id+catalog;checkout.textContent="Buy "+(pack.name||"Pack")+" ("+fmt(s.price_eur)+")";div.appendChild(checkout);const detail=document.createElement("a");detail.className="button secondary";detail.href="/credits/region-pack-map?token="+token+"&region_pack_id="+id+catalog;detail.textContent="View map";div.appendChild(detail);grid.appendChild(div)}}
renderUpsells();
</script>
</body>
</html>`;
}

function regionPackStaticMapHtml(data) {
  const pack = data && data.region_pack || {};
  const name = String(pack.name || "Region Pack").trim() || "Region Pack";
  const success = data && data.success && typeof data.success === "object" ? data.success : null;
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka ${escapeHtmlText(name)} Pack Detail</title>
<style>
:root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--new:#e45745;--licenced:#e2bc49;--free:#69707a;--country:#2a3748;--country-line:#98b4d8;--accent:#d9a441}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:22px;margin-top:4px}.card.final-price{border-color:#8f732f;box-shadow:0 0 0 1px rgba(217,164,65,.16) inset}.card.final-price b{font-size:26px}.buy-now{width:100%;font-size:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select{background:#262626;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px}svg{width:100%;height:auto;background:#0d1118;border:1px solid var(--line);border-radius:10px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0}.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}.new{background:var(--new)}.licenced{background:var(--licenced)}.free{background:var(--free)}
.countries{columns:2;column-gap:26px}.countries div{break-inside:avoid;margin:2px 0}.small{font-size:13px}.error{color:#ffb4a9}
.upsells{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.upsell{background:#151515;border:1px solid var(--line);border-radius:12px;padding:12px}.upsell h3{margin:0 0 8px;font-size:18px}.upsell p{margin:6px 0}.upsell svg{aspect-ratio:1/1;min-height:0}
.button{display:inline-flex;align-items:center;justify-content:center;margin-top:10px;padding:9px 12px;border-radius:8px;background:var(--accent);color:#111;text-decoration:none;font-weight:700}.button.secondary{margin-left:8px;background:#2a2a2a;color:var(--text);border:1px solid var(--line)}
</style>
</head>
<body>
<main>
<h1 id="pageTitle">${escapeHtmlText(name)} Full Quality Pack</h1>
${success ? `<section class="panel"><h2>${escapeHtmlText(success.title || "Payment successful")}</h2><p>${escapeHtmlText(success.message || "Your Planetka purchase has been processed.")}</p></section>` : ""}
<section id="cards" class="cards"></section>
<section class="panel">
<div class="toolbar">
<label>Detail level <select id="levelSelect"></select></label>
<span id="levelSummary" class="muted"></span>
</div>
<p class="muted small">Included detail levels are part of the Full Quality pack and are required for reliable Planetka rendering across different camera distances.</p>
<svg id="map" role="img" aria-label="${escapeHtmlText(name)} tile map"></svg>
<p class="muted small">Tile prices shown on hover are user-specific: already licenced tiles are €0.00.</p>
<div class="legend">
<span><i class="swatch new"></i>New in this pack</span>
<span><i class="swatch licenced"></i>Already licenced</span>
<span><i class="swatch free"></i>Free / not charged</span>
</div>
<p id="mapStatus" class="muted small">Loading map...</p>
</section>
<section id="countriesPanel" class="panel" style="display:none">
<h2>Included Area Labels</h2>
<p class="muted small">${escapeHtmlText(INCLUDED_AREA_NEUTRALITY_NOTICE)}</p>
<div id="countries" class="countries"></div>
</section>
<section id="upsellsPanel" class="panel" style="display:none">
<h2>Larger Full Quality options</h2>
<div id="upsellGrid" class="upsells"></div>
</section>
<section class="panel">
<a class="button secondary" href="/credits/region-pack-catalog?token=${escapeHtmlText(encodeURIComponent(String(data && data.token || "")))}">View all Full Quality data packs</a>
</section>
</main>
<script>const DATA=${payload};
const NS="http://www.w3.org/2000/svg";
const fmtCents=(v)=>"€"+(Math.max(0,Number(v||0)||0)/100).toFixed(2);
const int=(v)=>Math.max(0,Math.round(Number(v||0)||0));
const assetCache=new Map();
const assetVersion=encodeURIComponent(String(DATA.map_asset_revision||DATA.catalog_version||DATA.token||Date.now()));
const MAP_BG="/credits/region-pack-map-background.jpg?v="+assetVersion;
const currentToken=encodeURIComponent(DATA.token||"");
const currentPackId=encodeURIComponent(DATA.asset_id||DATA.region_pack&&DATA.region_pack.id||"");
const currentCatalog=DATA.catalog_mode?"&catalog=1":"";
function esc(value){return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function countryName(value){return typeof value==="object"&&value?String(value.name||value.COUNTRY||value.NAME_1||value.GID_0||""):String(value||"")}
function uniqueCountryNames(values){const seen=new Set(),out=[];for(const entry of Array.isArray(values)?values:[]){const label=countryName(entry).trim();const key=label.toLowerCase();if(!label||seen.has(key))continue;seen.add(key);out.push(label)}return out}
function parseTileKey(key){const m=/x(\\d{3})_y(\\d{3})_z(\\d{3})_d(\\d{3})/i.exec(String(key||""));return m?{key:m[0],x:Number(m[1]),y:Number(m[2]),z:Number(m[3]),d:Number(m[4])}:null}
function family(parsed){return parsed?"x"+String(parsed.x).padStart(3,"0")+"_y"+String(parsed.y).padStart(3,"0")+"_z"+String(parsed.z).padStart(3,"0"):""}
function tileSort(a,b){const pa=parseTileKey(a.tile_key),pb=parseTileKey(b.tile_key),fa=family(pa),fb=family(pb);return fa===fb?(Number(pa&&pa.d||0)-Number(pb&&pb.d||0)):fa<fb?-1:1}
	function buildOwnedByFamily(){const map=new Map();for(const row of DATA.owned_tiles||[]){const p=parseTileKey(row.tile_key);const f=family(p);if(!p||!f)continue;if(!map.has(f))map.set(f,[]);map.get(f).push({d:p.d,gross_cents:int(row.gross_cents)})}return map}
	async function loadAsset(id){const safe=String(id||"").trim();if(assetCache.has(safe))return assetCache.get(safe);const res=await fetch("/credits/region-pack-map-asset?region_pack_id="+encodeURIComponent(safe)+"&v="+assetVersion,{cache:"reload"});if(!res.ok)throw new Error("map_asset_"+res.status);const asset=await res.json();assetCache.set(safe,asset);return asset}
	function rawPackGrossCents(rows){const owned=new Map();let total=0;for(const tile of rows){const p=parseTileKey(tile.tile_key);const f=family(p);const full=int(tile.full_price_cents||tile.gross_cents);const globallyFree=!!tile.globally_free||full<=0;if(!p||!f||globallyFree)continue;if(!owned.has(f))owned.set(f,[]);const entries=owned.get(f);const covered=entries.some((entry)=>Number(entry.d)<=Number(p.d));let coarser=0;for(const entry of entries){if(Number(entry.d)>Number(p.d))coarser=Math.max(coarser,int(entry.gross_cents))}const charge=covered?0:Math.max(0,full-coarser);if(charge>0){total+=charge;entries.push({d:Number(p.d),gross_cents:full})}}return total}
	function computeAsset(asset){const owned=buildOwnedByFamily();const world=!!DATA.world_full_quality_unlocked;const discountPct=Math.max(0,Math.min(95,Number(asset&&asset.region_pack&&asset.region_pack.discount_percent||0)||0));const rows=(asset.tiles||[]).slice().sort(tileSort);const rawFullCents=rawPackGrossCents(rows);const paid=[];let grossCents=0,alreadyCount=0,freeCount=0;
	  for(const tile of rows){const p=parseTileKey(tile.tile_key);const f=family(p);const full=int(tile.full_price_cents||tile.gross_cents);const globallyFree=!!tile.globally_free||full<=0;if(!owned.has(f))owned.set(f,[]);const entries=owned.get(f);const covered=world||entries.some((entry)=>Number(entry.d)<=Number(p&&p.d||0));let coarser=0;for(const entry of entries){if(Number(entry.d)>Number(p&&p.d||0))coarser=Math.max(coarser,int(entry.gross_cents))}
	    const charge=globallyFree||covered?0:Math.max(0,full-coarser);let status="free";if(covered&&!globallyFree){status="licenced";alreadyCount+=1}else if(charge>0){status="new";grossCents+=charge;paid.push({tile,cents:charge})}else{freeCount+=1}
	    if(charge>0&&entries){entries.push({d:Number(p&&p.d||0),gross_cents:full})}
	    tile.x=p?p.x:null;tile.y=p?p.y:null;tile.z=p?p.z:null;tile.d=p?p.d:null;tile.lon_min=p?p.x-180:null;tile.lon_max=p?p.x-180+p.z:null;tile.lat_min=p?p.y-90:null;tile.lat_max=p?p.y-90+p.z:null;tile.status=status;tile.charge_cents=charge;tile.price_cents=0;tile.full_price_cents=full;tile.full_price_eur=full/100;tile.price_eur=0;
	  }
	  const discountCents=Math.round(grossCents*discountPct/100);const targetCents=Math.max(0,grossCents-discountCents);let allocated=0;const alloc=paid.map((entry,index)=>{const raw=grossCents>0?(entry.cents*targetCents/grossCents):0;const floor=Math.floor(raw);allocated+=floor;return{entry,index,cents:floor,remainder:raw-floor}}).sort((a,b)=>b.remainder!==a.remainder?b.remainder-a.remainder:a.index-b.index);let rem=Math.max(0,targetCents-allocated);for(const item of alloc){if(rem<=0)break;item.cents+=1;rem-=1}for(const item of alloc){item.entry.tile.price_cents=item.cents;item.entry.tile.price_eur=item.cents/100;if(item.cents<=0)item.entry.tile.status="free"}
	  const alreadyDeductionCents=Math.max(0,rawFullCents-grossCents);
	  const levels=Array.from(new Set(rows.map((row)=>Number(row.z)).filter(Number.isFinite))).sort((a,b)=>a-b);return{asset,rows,levels,summary:{new_tiles:paid.filter((entry)=>entry.tile.price_cents>0).length,total_tiles:rows.length,already_licenced_tiles:alreadyCount,free_tiles:freeCount,full_price_cents:rawFullCents,discount_percent:discountPct,discount_cents:discountCents,price_cents:targetCents,already_licenced_deduction_cents:alreadyDeductionCents,already_licenced_saving_cents:alreadyDeductionCents}}}
	function currentBuyHref(){return currentPackId?"/credits/region-pack-checkout?token="+currentToken+"&region_pack_id="+currentPackId+currentCatalog:""}
	function renderCards(vm){const s=vm.summary;const cards=[["New / Total Tiles",Number(s.new_tiles||0)+" / "+Number(s.total_tiles||0)],["Full Price",fmtCents(s.full_price_cents)],["Already Licenced","-"+fmtCents(s.already_licenced_deduction_cents)],["Volume Discount",Number(s.discount_percent||0)+"% (-"+fmtCents(s.discount_cents)+")"]];const buy=currentBuyHref()&&int(s.price_cents)>0?"<a class=\\"button buy-now\\" href=\\""+currentBuyHref()+"\\">Buy Now</a>":"";cards.push(["Final Price",fmtCents(s.price_cents),buy]);document.getElementById("cards").innerHTML=cards.map((c)=>"<div class=\\"card "+(c[0]==="Final Price"?"final-price":"")+"\\"><span>"+esc(c[0])+"</span><b>"+esc(c[1])+"</b>"+(c[2]||"")+"</div>").join("")}
let currentBounds={min_lon:-10,min_lat:35,max_lon:30,max_lat:48},pad=20,W=1000,H=520;
function setBounds(bounds){currentBounds=bounds||currentBounds;const aspect=Math.max(0.28,Math.min(0.9,(currentBounds.max_lat-currentBounds.min_lat)/Math.max(1e-6,currentBounds.max_lon-currentBounds.min_lon)));H=Math.round(W*aspect)+pad*2}
function xy(lon,lat){return [pad+((lon-currentBounds.min_lon)/(currentBounds.max_lon-currentBounds.min_lon||1))*(W-pad*2),pad+((currentBounds.max_lat-lat)/(currentBounds.max_lat-currentBounds.min_lat||1))*(H-pad*2)]}
function el(name,attrs){const node=document.createElementNS(NS,name);for(const k in attrs||{})node.setAttribute(k,String(attrs[k]));return node}
function addMapBackground(svg,project,width,height){svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#0d1118"}));const tl=project(-180,90),br=project(180,-90);svg.appendChild(el("image",{href:MAP_BG,x:tl[0],y:tl[1],width:br[0]-tl[0],height:br[1]-tl[1],preserveAspectRatio:"none",opacity:"0.22"}));svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#05070a",opacity:"0.48"}))}
function pathFor(poly){return(poly||[]).map((pt,i)=>{const p=xy(pt[0],pt[1]);return(i?"L":"M")+p[0].toFixed(2)+" "+p[1].toFixed(2)}).join(" ")}
function renderMap(vm,level){const svg=document.getElementById("map");svg.replaceChildren();svg.setAttribute("viewBox","0 0 "+W+" "+H);addMapBackground(svg,xy,W,H);for(const outline of vm.asset.outlines||[]){for(const poly of outline.polygons||[]){const p=el("path",{d:pathFor(poly),fill:"none",stroke:"var(--country-line)","stroke-width":"0.7",opacity:"0.72"});const t=el("title",{});t.textContent=outline.name;p.appendChild(t);svg.appendChild(p)}}const rows=vm.rows.filter((row)=>Number(row.z)===Number(level));let newCount=0,licencedCount=0,freeCount=0,price=0;for(const tile of rows){const a=xy(tile.lon_min,tile.lat_max),b=xy(tile.lon_max,tile.lat_min);const cls=tile.status==="new"?"var(--new)":(tile.status==="licenced"?"var(--licenced)":"var(--free)");if(tile.status==="new"){newCount++;price+=int(tile.price_cents)}else if(tile.status==="licenced"){licencedCount++}else{freeCount++}const r=el("rect",{x:a[0],y:a[1],width:Math.max(1,b[0]-a[0]),height:Math.max(1,b[1]-a[1]),fill:cls,stroke:"#fff","stroke-width":"0.45",opacity:tile.status==="new"?"0.58":"0.43"});const title=el("title",{});title.textContent=tile.tile_key+"\\nLand: "+Number(tile.billable_land_km2||0).toFixed(2)+" km²\\nStatus: "+tile.status+"\\nFull price: "+fmtCents(tile.full_price_cents)+"\\nFinal price: "+fmtCents(tile.price_cents);r.appendChild(title);svg.appendChild(r)}document.getElementById("levelSummary").textContent=rows.length+" tiles at z"+String(level).padStart(3,"0")+" · new "+newCount+" · already licenced "+licencedCount+" · free "+freeCount+" · visible-level price "+fmtCents(price)}
function miniFrame(bounds,w,h){const p=12,lonSpan=Math.max(1e-6,bounds.max_lon-bounds.min_lon),latSpan=Math.max(1e-6,bounds.max_lat-bounds.min_lat),scale=Math.min((w-p*2)/lonSpan,(h-p*2)/latSpan),usedW=lonSpan*scale,usedH=latSpan*scale;return{bounds,scale,ox:(w-usedW)/2,oy:(h-usedH)/2}}
function miniXY(frame,lon,lat){return[frame.ox+(lon-frame.bounds.min_lon)*frame.scale,frame.oy+(frame.bounds.max_lat-lat)*frame.scale]}
function renderMiniMap(svg,vm){const b=vm.asset.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const w=360,h=360,frame=miniFrame(b,w,h);svg.setAttribute("viewBox","0 0 "+w+" "+h);svg.setAttribute("preserveAspectRatio","xMidYMid meet");svg.replaceChildren();addMapBackground(svg,(lon,lat)=>miniXY(frame,lon,lat),w,h);const first=vm.levels.length?vm.levels[0]:null;for(const tile of vm.rows.filter((row)=>Number(row.z)===Number(first))){const a=miniXY(frame,tile.lon_min,tile.lat_max),c=miniXY(frame,tile.lon_max,tile.lat_min);const cls=tile.status==="new"?"var(--new)":(tile.status==="licenced"?"var(--licenced)":"var(--free)");svg.appendChild(el("rect",{x:a[0],y:a[1],width:Math.max(1,c[0]-a[0]),height:Math.max(1,c[1]-a[1]),fill:cls,stroke:"#fff","stroke-width":"0.5",opacity:tile.status==="new"?"0.58":"0.43"}))}}
async function renderUpsells(asset){const ids=Array.isArray(asset.upsell_ids)?asset.upsell_ids:[];const grid=document.getElementById("upsellGrid");if(!grid||!ids.length)return;const token=encodeURIComponent(DATA.token||"");const catalog=DATA.catalog_mode?"&catalog=1":"";for(const idRaw of ids){try{const upAsset=await loadAsset(idRaw);const vm=computeAsset(upAsset);if(vm.summary.price_cents<=0&&vm.summary.new_tiles<=0)continue;const id=encodeURIComponent(upAsset.region_pack.id||idRaw);const div=document.createElement("div");div.className="upsell";const title=document.createElement("h3");title.textContent=upAsset.region_pack.name||"Region Pack";div.appendChild(title);const map=document.createElementNS(NS,"svg");div.appendChild(map);renderMiniMap(map,vm);const meta=document.createElement("p");meta.className="muted small";meta.textContent=Number(vm.summary.new_tiles||0)+" new tiles · "+Number(vm.summary.discount_percent||0)+"% volume discount · "+fmtCents(vm.summary.price_cents);div.appendChild(meta);const checkout=document.createElement("a");checkout.className="button";checkout.href="/credits/region-pack-checkout?token="+token+"&region_pack_id="+id+catalog;checkout.textContent="Buy "+(upAsset.region_pack.name||"Pack")+" ("+fmtCents(vm.summary.price_cents)+")";div.appendChild(checkout);const detail=document.createElement("a");detail.className="button secondary";detail.href="/credits/region-pack-map?token="+token+"&region_pack_id="+id+catalog;detail.textContent="View map";div.appendChild(detail);grid.appendChild(div);document.getElementById("upsellsPanel").style.display=""}catch(error){console.warn("Planetka upsell map failed",idRaw,error)}}}
async function init(){try{const asset=await loadAsset(DATA.asset_id);document.getElementById("pageTitle").textContent=(asset.region_pack.name||"Region Pack")+" Full Quality Pack";const vm=computeAsset(asset);renderCards(vm);setBounds(asset.bounds);const countries=uniqueCountryNames(asset.included_countries);if(countries.length){document.getElementById("countries").innerHTML=countries.map((c)=>"<div>"+esc(c)+"</div>").join("");document.getElementById("countriesPanel").style.display=""}const select=document.getElementById("levelSelect");select.replaceChildren();const levels=vm.levels.length?vm.levels:[1];for(const z of levels){const o=document.createElement("option");o.value=String(z);o.textContent="z"+String(z).padStart(3,"0");select.appendChild(o)}select.addEventListener("change",()=>renderMap(vm,Number(select.value)));renderMap(vm,Number(select.value||levels[0]));document.getElementById("mapStatus").textContent="Map loaded.";renderUpsells(asset)}catch(error){console.warn("Planetka region-pack map failed",error);document.getElementById("mapStatus").className="error small";document.getElementById("mapStatus").textContent="Map failed to load. Please reopen this page from Blender."}}
init();
</script>
</body>
</html>`;
}

function regionPackCatalogHtml(data) {
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka Full Quality Data Packs</title>
<style>
:root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--accent:#d9a441}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}h2{margin:22px 0 10px}.muted{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}
input{min-width:260px;flex:1;background:#262626;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
table{width:100%;border-collapse:collapse;background:#151515;border:1px solid var(--line);border-radius:10px;overflow:hidden}th,td{padding:8px 10px;border-bottom:1px solid #2d2d2d;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left;white-space:normal}tr:last-child td{border-bottom:0}th{color:#ddd;background:#202020;font-weight:650}.small{font-size:13px}.saving{color:#9dd18d}.price{font-weight:700;color:#f4d28d}
.button{display:inline-flex;align-items:center;justify-content:center;padding:7px 10px;border-radius:8px;background:var(--accent);color:#111;text-decoration:none;font-weight:700}.button.secondary{background:#2a2a2a;color:var(--text);border:1px solid var(--line)}
.empty{padding:12px;color:var(--muted)}
</style>
</head>
<body>
<main>
<h1>All Full Quality Data Packs</h1>
<p class="muted">Prices are calculated for this account. Already licenced tiles are deducted automatically.</p>
<section class="panel">
<div class="toolbar">
<input id="filter" type="search" placeholder="Search countries, regions, states, provinces...">
<span id="count" class="muted small"></span>
</div>
<div id="catalog"></div>
</section>
</main>
<script>const DATA=${payload};
const fmt=(v)=>"€"+Number(v||0).toFixed(2);
const token=encodeURIComponent(DATA.token||"");
function rowHtml(row){const id=encodeURIComponent(row.id||"");const licenced=Number(row.already_licenced_tiles||0);const saving=Number(row.already_licenced_saving_eur||0);const mapLink=String(row.id||"").toLowerCase()==="world"?"":" <a class=\\"button secondary\\" href=\\"/credits/region-pack-map?token="+token+"&region_pack_id="+id+"&catalog=1\\">Map</a>";return "<tr>"
+"<td><b>"+escapeCell(row.name||"Data Pack")+"</b><div class=\\"muted small\\">"+escapeCell(row.group_label||"")+"</div></td>"
+"<td>"+Number(row.new_tiles||0)+"</td>"
+"<td>"+Number(row.total_tiles||0)+"</td>"
+"<td>"+fmt(row.full_price_eur)+"</td>"
+"<td>"+(licenced?licenced+" tiles <span class=\\"saving\\">(-"+fmt(saving)+")</span>":"-")+"</td>"
+"<td>"+Number(row.discount_percent||0)+"% <span class=\\"saving\\">(-"+fmt(row.discount_eur)+")</span></td>"
+"<td class=\\"price\\">"+fmt(row.price_eur)+"</td>"
+"<td><a class=\\"button\\" href=\\"/credits/region-pack-checkout?token="+token+"&region_pack_id="+id+"&catalog=1\\">Buy</a>"+mapLink+"</td>"
+"</tr>"}
function escapeCell(value){return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function render(){const filter=String(document.getElementById("filter").value||"").trim().toLowerCase();let shown=0;const html=(DATA.groups||[]).map(group=>{const rows=(group.rows||[]).filter(row=>!filter||String(row.name||"").toLowerCase().includes(filter));if(!rows.length)return "";shown+=rows.length;return "<h2>"+escapeCell(group.label)+"</h2><table><thead><tr><th>Data Pack</th><th>New Tiles</th><th>Total Tiles</th><th>Full Price</th><th>Already Licenced</th><th>Volume Discount</th><th>Final Price</th><th>Actions</th></tr></thead><tbody>"+rows.map(rowHtml).join("")+"</tbody></table>"}).join("");document.getElementById("catalog").innerHTML=html||"<div class=\\"empty\\">No data packs match this search.</div>";document.getElementById("count").textContent=shown+" data packs";}document.getElementById("filter").addEventListener("input",render);render();
</script>
</body>
</html>`;
}

function regionPackStaticCatalogHtml(data) {
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka Full Quality Data Packs</title>
<style>
:root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--accent:#d9a441}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}h2{margin:22px 0 10px}.muted{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}
input{min-width:260px;flex:1;background:#262626;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
table{width:100%;border-collapse:collapse;background:#151515;border:1px solid var(--line);border-radius:10px;overflow:hidden}th,td{padding:8px 10px;border-bottom:1px solid #2d2d2d;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left;white-space:normal}tr:last-child td{border-bottom:0}th{color:#ddd;background:#202020;font-weight:650}.small{font-size:13px}.saving{color:#9dd18d}.price{font-weight:700;color:#f4d28d}.error{color:#ffb4a9}
.button{display:inline-flex;align-items:center;justify-content:center;padding:7px 10px;border-radius:8px;background:var(--accent);color:#111;text-decoration:none;font-weight:700}.button.secondary{background:#2a2a2a;color:var(--text);border:1px solid var(--line)}
.empty{padding:12px;color:var(--muted)}
</style>
</head>
<body>
<main>
<h1>All Full Quality Data Packs</h1>
<p class="muted">Prices are calculated for this account. Already licenced tiles are deducted automatically.</p>
<section class="panel">
<div class="toolbar">
<input id="filter" type="search" placeholder="Search countries, regions, states, provinces...">
<span id="count" class="muted small">Loading data packs...</span>
</div>
<div id="catalog"></div>
</section>
</main>
<script>const DATA=${payload};
const fmtCents=(v)=>"€"+(Math.max(0,Number(v||0)||0)/100).toFixed(2);
const int=(v)=>Math.max(0,Math.round(Number(v||0)||0));
const token=encodeURIComponent(DATA.token||"");
function esc(value){return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function parseTileKey(key){const m=/x(\\d{3})_y(\\d{3})_z(\\d{3})_d(\\d{3})/i.exec(String(key||""));return m?{key:m[0],x:Number(m[1]),y:Number(m[2]),z:Number(m[3]),d:Number(m[4])}:null}
function family(parsed){return parsed?"x"+String(parsed.x).padStart(3,"0")+"_y"+String(parsed.y).padStart(3,"0")+"_z"+String(parsed.z).padStart(3,"0"):""}
function tileSort(a,b){const pa=parseTileKey(a[0]),pb=parseTileKey(b[0]),fa=family(pa),fb=family(pb);return fa===fb?(Number(pa&&pa.d||0)-Number(pb&&pb.d||0)):fa<fb?-1:1}
function buildOwnedByFamily(){const map=new Map();for(const row of DATA.owned_tiles||[]){const p=parseTileKey(row.tile_key);const f=family(p);if(!p||!f)continue;if(!map.has(f))map.set(f,[]);map.get(f).push({d:p.d,gross_cents:int(row.gross_cents)})}return map}
	function computeProduct(row){const discountPct=Math.max(0,Math.min(95,Number(row.discount_percent||0)||0));if(row.world){const full=int(row.full_price_cents);const discount=Math.round(full*discountPct/100);const price=DATA.world_full_quality_unlocked?0:Math.max(0,full-discount);const already=DATA.world_full_quality_unlocked?full:0;return{...row,new_tiles:DATA.world_full_quality_unlocked?0:Number(row.total_tiles||0),already_licenced_tiles:DATA.world_full_quality_unlocked?Number(row.total_tiles||0):0,full_price_cents:full,chargeable_full_price_cents:DATA.world_full_quality_unlocked?0:full,discount_cents:DATA.world_full_quality_unlocked?0:discount,price_cents:price,already_licenced_deduction_cents:already,already_licenced_saving_cents:already}}
	  const owned=buildOwnedByFamily();const world=!!DATA.world_full_quality_unlocked;const tiles=(row.tiles||[]).slice().sort(tileSort);let gross=0,alreadyCount=0,freeCount=0,newCount=0;for(const tile of tiles){const p=parseTileKey(tile[0]);const f=family(p);const full=int(tile[1]);const globallyFree=!!tile[2]||full<=0;if(!owned.has(f))owned.set(f,[]);const entries=owned.get(f);const covered=world||entries.some((entry)=>Number(entry.d)<=Number(p&&p.d||0));let coarser=0;for(const entry of entries){if(Number(entry.d)>Number(p&&p.d||0))coarser=Math.max(coarser,int(entry.gross_cents))}const charge=globallyFree||covered?0:Math.max(0,full-coarser);if(covered&&!globallyFree){alreadyCount++}else if(charge>0){newCount++;gross+=charge;entries.push({d:Number(p&&p.d||0),gross_cents:full})}else{freeCount++}}const full=int(row.full_price_cents);const discount=Math.round(gross*discountPct/100);const price=Math.max(0,gross-discount);const already=Math.max(0,full-gross);return{...row,new_tiles:newCount,already_licenced_tiles:alreadyCount,free_tiles:freeCount,chargeable_full_price_cents:gross,discount_cents:discount,price_cents:price,already_licenced_deduction_cents:already,already_licenced_saving_cents:already}}
	function rowHtml(row){const id=encodeURIComponent(row.id||"");const licenced=Number(row.already_licenced_tiles||0);const saving=int(row.already_licenced_saving_cents);const mapLink=String(row.id||"").toLowerCase()==="world"?"":" <a class=\\"button secondary\\" href=\\"/credits/region-pack-map?token="+token+"&region_pack_id="+id+"&catalog=1\\">Map</a>";return "<tr>"
+"<td><b>"+esc(row.name||"Data Pack")+"</b><div class=\\"muted small\\">"+esc(row.group_label||"")+"</div></td>"
+"<td>"+Number(row.new_tiles||0)+"</td>"
+"<td>"+Number(row.total_tiles||0)+"</td>"
+"<td>"+fmtCents(row.full_price_cents)+"</td>"
+"<td>"+(licenced?licenced+" tiles <span class=\\"saving\\">(-"+fmtCents(saving)+")</span>":"-")+"</td>"
+"<td>"+Number(row.discount_percent||0)+"% <span class=\\"saving\\">(-"+fmtCents(row.discount_cents)+")</span></td>"
+"<td class=\\"price\\">"+fmtCents(row.price_cents)+"</td>"
+"<td><a class=\\"button\\" href=\\"/credits/region-pack-checkout?token="+token+"&region_pack_id="+id+"&catalog=1\\">Buy</a>"+mapLink+"</td>"
+"</tr>"}
let ROWS=[];
function render(){const filter=String(document.getElementById("filter").value||"").trim().toLowerCase();let shown=0;const groupOrder=["world","continents","regions","countries","states_provinces","other"];const chunks=[];for(const key of groupOrder){const rows=ROWS.filter((row)=>String(row.group_key||"")===key&&(!filter||String(row.name||"").toLowerCase().includes(filter)));if(!rows.length)continue;shown+=rows.length;chunks.push("<h2>"+esc(rows[0].group_label||key)+"</h2><table><thead><tr><th>Data Pack</th><th>New Tiles</th><th>Total Tiles</th><th>Full Price</th><th>Already Licenced</th><th>Volume Discount</th><th>Final Price</th><th>Actions</th></tr></thead><tbody>"+rows.map(rowHtml).join("")+"</tbody></table>")}document.getElementById("catalog").innerHTML=chunks.join("")||"<div class=\\"empty\\">No data packs match this search.</div>";document.getElementById("count").textContent=shown+" data packs"}
async function init(){try{const res=await fetch("/credits/region-pack-catalog-asset",{cache:"force-cache"});if(!res.ok)throw new Error("catalog_asset_"+res.status);const data=await res.json();ROWS=(data.products||[]).map(computeProduct).sort((a,b)=>String(a.group_label||"").localeCompare(String(b.group_label||""))||String(a.name||"").localeCompare(String(b.name||"")));document.getElementById("filter").addEventListener("input",render);render()}catch(error){document.getElementById("count").className="error small";document.getElementById("count").textContent="Data-pack catalog failed to load."}}
init();
</script>
</body>
</html>`;
}

function balanceTopUpPageHtml(data) {
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka Add Balance</title>
<style>
:root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--accent:#d9a441;--tile:#e45745;--country:#2a3748;--country-line:#98b4d8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1120px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:30px;font-weight:700}p{margin:8px 0}.muted{color:var(--muted)}.small{font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px}
.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.pay{font-size:26px;font-weight:750}.bonus{color:#bdeaa7;font-weight:700}.balance{font-size:18px;font-weight:700}.guide{color:var(--muted)}
svg{width:100%;aspect-ratio:1/1;height:auto;background:#0d1118;border:1px solid var(--line);border-radius:10px}.button{display:inline-flex;align-items:center;justify-content:center;padding:10px 12px;border-radius:9px;background:var(--accent);color:#111;text-decoration:none;font-weight:750}
</style>
</head>
<body>
<main>
<h1>Add Planetka Balance</h1>
<p class="muted">Choose how much balance to add. Bonus balance is added automatically after Stripe confirms the payment.</p>
<section id="options" class="grid"></section>
<p class="muted small">Visual guides are approximate examples based on current Full Quality pack prices. Actual scene prices depend on the visible tiles and any data already licenced to your account.</p>
</main>
<script>const DATA=${payload};
const NS="http://www.w3.org/2000/svg";
const fmt=(v)=>"€"+Number(v||0).toFixed(2);
const assetVersion=encodeURIComponent(String(DATA.map_asset_revision||DATA.catalog_version||DATA.token||Date.now()));
const MAP_BG="/credits/region-pack-map-background.jpg?v="+assetVersion;
function esc(value){return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function parseTileKey(key){const m=/x(\\d{3})_y(\\d{3})_z(\\d{3})_d(\\d{3})/i.exec(String(key||""));return m?{x:Number(m[1]),y:Number(m[2]),z:Number(m[3]),d:Number(m[4])}:null}
function frame(bounds,w,h){const p=12,lonSpan=Math.max(1e-6,bounds.max_lon-bounds.min_lon),latSpan=Math.max(1e-6,bounds.max_lat-bounds.min_lat),scale=Math.min((w-p*2)/lonSpan,(h-p*2)/latSpan),usedW=lonSpan*scale,usedH=latSpan*scale;return{bounds,scale,ox:(w-usedW)/2,oy:(h-usedH)/2}}
function xy(f,lon,lat){return[f.ox+(lon-f.bounds.min_lon)*f.scale,f.oy+(f.bounds.max_lat-lat)*f.scale]}
function el(name,attrs){const node=document.createElementNS(NS,name);for(const k in attrs||{})node.setAttribute(k,String(attrs[k]));return node}
function addMapBackground(svg,project,width,height){svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#0d1118"}));const tl=project(-180,90),br=project(180,-90);svg.appendChild(el("image",{href:MAP_BG,x:tl[0],y:tl[1],width:br[0]-tl[0],height:br[1]-tl[1],preserveAspectRatio:"none",opacity:"0.22"}));svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#05070a",opacity:"0.48"}))}
function pathFor(f,poly){return(poly||[]).map((pt,i)=>{const p=xy(f,pt[0],pt[1]);return(i?"L":"M")+p[0].toFixed(2)+" "+p[1].toFixed(2)}).join(" ")}
async function renderMiniMap(svg,id){try{const res=await fetch("/credits/region-pack-map-asset?region_pack_id="+encodeURIComponent(id)+"&v="+assetVersion,{cache:"reload"});if(!res.ok)throw new Error("asset_"+res.status);const asset=await res.json();const b=asset.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const w=360,h=360,f=frame(b,w,h);svg.setAttribute("viewBox","0 0 "+w+" "+h);svg.setAttribute("preserveAspectRatio","xMidYMid meet");svg.replaceChildren();addMapBackground(svg,(lon,lat)=>xy(f,lon,lat),w,h);for(const outline of asset.outlines||[]){for(const poly of outline.polygons||[]){svg.appendChild(el("path",{d:pathFor(f,poly),fill:"none",stroke:"var(--country-line)","stroke-width":"0.7",opacity:"0.7"}))}}const parsed=(asset.tiles||[]).map(t=>({tile:t,parsed:parseTileKey(t.tile_key)})).filter(v=>v.parsed);const levels=[...new Set(parsed.map(v=>v.parsed.z))].sort((a,b)=>a-b);const level=levels.length?levels[0]:1;for(const entry of parsed.filter(v=>v.parsed.z===level)){const p=entry.parsed;const a=xy(f,p.x-180,p.y-90+p.z),c=xy(f,p.x-180+p.z,p.y-90);svg.appendChild(el("rect",{x:a[0],y:a[1],width:Math.max(1,c[0]-a[0]),height:Math.max(1,c[1]-a[1]),fill:"var(--tile)",stroke:"#fff","stroke-width":"0.5",opacity:"0.58"}))}}catch(error){svg.replaceChildren();svg.setAttribute("viewBox","0 0 360 360");svg.appendChild(el("rect",{x:0,y:0,width:360,height:360,fill:"#0d1118"}));const t=el("text",{x:180,y:180,"text-anchor":"middle",fill:"#ffb4a9"});t.textContent="Map unavailable";svg.appendChild(t);}}
function render(){const root=document.getElementById("options");root.innerHTML=(DATA.options||[]).map((option)=>{const href="/credits/balance-checkout?token="+encodeURIComponent(DATA.token||"")+"&amount_eur="+encodeURIComponent(option.amount_eur);return "<article class=\\"card\\"><div class=\\"top\\"><div><div class=\\"pay\\">Pay "+fmt(option.amount_eur)+"</div><div class=\\"balance\\">Adds "+fmt(option.balance_eur)+" balance</div></div><div class=\\"bonus\\">+"+Number(option.bonus_percent||0)+"%<br><span class=\\"small\\">"+fmt(option.bonus_eur)+" bonus</span></div></div><svg data-pack=\\""+esc(option.guide_region_pack_id||"")+"\\" aria-label=\\""+esc(option.guide_label||"guide map")+"\\"></svg><div class=\\"guide\\">Roughly comparable to "+esc(option.guide_label||"a regional pack")+" ("+fmt(option.guide_price_eur)+")</div><a class=\\"button\\" href=\\""+href+"\\">Add "+fmt(option.amount_eur)+"</a></article>"}).join("");for(const svg of root.querySelectorAll("svg[data-pack]")){renderMiniMap(svg,svg.getAttribute("data-pack")||"")}}
render();
</script>
</body>
</html>`;
}

export async function handleCreditBalanceTopUpPage(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const db = deps.requireDb(env);
  const tokenResult = await getValidBalanceTopUpToken(db, token, deps);
  if (tokenResult.error) {
    return html(
      "<!doctype html><title>Planetka Add Balance</title><h1>This balance top-up link expired.</h1><p>Please open Add Balance again from Blender.</p>",
      tokenResult.status || 410,
      env,
    );
  }
  return html(
    balanceTopUpPageHtml({
      ok: true,
      catalog_version: REGION_PACK_CATALOG_VERSION,
      map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
      token,
      options: balanceTopUpOptions(),
    }),
    200,
    env,
  );
}

export async function handleCreditBalanceTopUpCheckoutFromToken(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const topUpOption = balanceTopUpOptionForAmount(url.searchParams.get("amount_eur") || url.searchParams.get("amount") || "");
  if (!topUpOption) {
    return html(
      "<!doctype html><title>Planetka Add Balance</title><h1>Unknown balance top-up amount.</h1><p>Please choose one of the listed Planetka balance options.</p>",
      400,
      env,
    );
  }
  const db = deps.requireDb(env);
  const tokenResult = await getValidBalanceTopUpToken(db, token, deps);
  if (tokenResult.error) {
    return html(
      "<!doctype html><title>Planetka Add Balance</title><h1>This balance top-up link expired.</h1><p>Please open Add Balance again from Blender.</p>",
      tokenResult.status || 410,
      env,
    );
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const user = await deps.dbGet(db, `SELECT id, email FROM users WHERE id = ? LIMIT 1`, [userId]);
  const email = deps.normalizeEmail(user && user.email || "");
  if (!userId || !email) {
    return html(
      "<!doctype html><title>Planetka Add Balance</title><h1>Account not found.</h1><p>Please return to Blender and sign in again.</p>",
      404,
      env,
    );
  }
  const session = await createBalanceTopUpStripeSession(env, topUpOption, email, userId, deps);
  if (session.error || !session.checkout_url) {
    return html(
      `<!doctype html><title>Planetka Add Balance</title><h1>Could not open payment.</h1><p>${escapeHtmlText(session.message || session.error || "Stripe Checkout could not be created.")}</p>`,
      502,
      env,
    );
  }
  return Response.redirect(session.checkout_url, 303);
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
          top_up_payment_eur: normalizeCreditAmount(metadata && (metadata.top_up_payment_eur ?? metadata.stripe_amount_paid_eur)),
          top_up_bonus_eur: normalizeCreditAmount(metadata && metadata.top_up_bonus_eur),
          top_up_bonus_percent: Math.max(0, Number.parseFloat(metadata && metadata.top_up_bonus_percent || 0) || 0),
          top_up_eur: amount,
          balance_added_eur: amount,
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

export async function grantRegionPackEntitlements(db, userId, regionPackId, stripeSessionId, amountPaidEur, deps, userEmail = "", stripePaymentIntentId = "", options = {}) {
  const safeUserId = String(userId || "").trim();
  const safeStripeSessionId = String(stripeSessionId || "").trim();
  const safeOptions = options && typeof options === "object" ? options : {};
  const paymentSourceRaw = String(
    safeOptions.payment_source
      || safeOptions.paymentSource
      || (safeStripeSessionId.startsWith("region_pack_no_payment_") ? "none" : "stripe")
      || "",
  ).trim().toLowerCase();
  const paymentSource = paymentSourceRaw === "balance" || paymentSourceRaw === "none" ? paymentSourceRaw : "stripe";
  const ledgerReason = paymentSource === "balance"
    ? "balance_region_pack_purchase"
    : paymentSource === "none"
    ? "region_pack_no_payment"
    : "stripe_region_pack_purchase";
  const entitlementSource = paymentSource === "balance"
    ? "balance_region_pack"
    : paymentSource === "none"
    ? "region_pack_no_payment"
    : "stripe_region_pack";
  const paymentReferenceId = String(safeOptions.payment_reference_id || safeOptions.paymentReferenceId || "").trim();
  const purchaseHistoryId = String(safeOptions.purchase_history_id || safeOptions.purchaseHistoryId || "").trim();
  const shouldWriteLedger = !Boolean(safeOptions.skip_credit_ledger || safeOptions.skipCreditLedger);
  const purchaseStripeSessionId = paymentSource === "stripe" ? safeStripeSessionId : "";
  const product = regionProductById(regionPackId);
  if (!safeUserId) {
    return { error: "missing_user_id" };
  }
  if (!product) {
    return { error: "unknown_region_pack" };
  }
  if (paymentSource === "stripe" && safeStripeSessionId) {
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
      [now, purchaseStripeSessionId || null, paidEur, now, safeUserId],
    );
    if (shouldWriteLedger) {
      await deps.dbRun(
        db,
        `
          INSERT INTO credit_ledger (
            id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
          )
          VALUES (?, ?, 0, (SELECT balance_credits FROM user_credit_accounts WHERE user_id = ?), ?, ?, ?)
        `,
        [
          deps.randomToken(16),
          safeUserId,
          safeUserId,
          ledgerReason,
          JSON.stringify({
            stripe_session_id: purchaseStripeSessionId,
            stripe_payment_intent_id: paymentSource === "stripe" ? String(stripePaymentIntentId || "").trim() : "",
            payment_source: paymentSource,
            payment_reference_id: paymentReferenceId,
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
    }
    await recordPurchaseHistoryBestEffort(
      db,
      {
        id: purchaseHistoryId || undefined,
        user_id: safeUserId,
        user_email: String(userEmail || "").trim().toLowerCase(),
        purchase_type: "region_pack",
        stripe_session_id: purchaseStripeSessionId,
        stripe_payment_intent_id: paymentSource === "stripe" ? String(stripePaymentIntentId || "").trim() : "",
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
          payment_source: paymentSource,
          payment_reference_id: paymentReferenceId,
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
      `${entitlementSource}_summary`,
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
        VALUES (?, ?, 'full', ?, ?, ?, ?, ?)
      `,
      [
        safeUserId,
        tileKey,
        nominalTileCredits,
        Math.max(0, Number.parseFloat(tile && tile.land_km2 || 0) || 0),
        Math.max(0, Number.parseFloat(tile && tile.billable_land_km2 || 0) || 0),
        entitlementSource,
        now,
      ],
    );
    if (deps.dbMetaChanges(insert) > 0) {
      insertedTiles.push(tile);
      nominalCredits = normalizeCreditAmount(nominalCredits + nominalTileCredits);
    }
  }
  if (shouldWriteLedger) {
    await deps.dbRun(
      db,
      `
        INSERT INTO credit_ledger (
          id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
        )
        VALUES (?, ?, 0, (SELECT balance_credits FROM user_credit_accounts WHERE user_id = ?), ?, ?, ?)
      `,
      [
        deps.randomToken(16),
        safeUserId,
        safeUserId,
        ledgerReason,
        JSON.stringify({
          stripe_session_id: purchaseStripeSessionId,
          stripe_payment_intent_id: paymentSource === "stripe" ? String(stripePaymentIntentId || "").trim() : "",
          payment_source: paymentSource,
          payment_reference_id: paymentReferenceId,
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
  }
  await recordPurchaseHistoryBestEffort(
    db,
    {
      id: purchaseHistoryId || undefined,
      user_id: safeUserId,
      user_email: String(userEmail || "").trim().toLowerCase(),
      purchase_type: "region_pack",
      stripe_session_id: purchaseStripeSessionId,
      stripe_payment_intent_id: paymentSource === "stripe" ? String(stripePaymentIntentId || "").trim() : "",
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
        payment_source: paymentSource,
        payment_reference_id: paymentReferenceId,
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

async function fetchStripeCheckoutSession(env, sessionId, deps) {
  const safeSessionId = String(sessionId || "").trim();
  if (!safeSessionId) {
    return { error: "missing_session_id" };
  }
  const secretKey = deps.requireSecret(env, "STRIPE_SECRET_KEY");
  const response = await fetch(`https://api.stripe.com/v1/checkout/sessions/${encodeURIComponent(safeSessionId)}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${secretKey}`,
    },
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
      error: "stripe_session_fetch_failed",
      status: response.status,
      message: String(payload && (payload.error && payload.error.message || payload.message) || responseText || "stripe_session_fetch_failed"),
    };
  }
  return { ok: true, session: payload };
}

async function createBalanceTopUpStripeSession(env, topUpOption, email, userId, deps) {
  const amountEur = normalizeCreditAmount(topUpOption && topUpOption.amount_eur);
  const balanceEur = normalizeCreditAmount(topUpOption && topUpOption.balance_eur);
  const bonusEur = normalizeCreditAmount(topUpOption && topUpOption.bonus_eur);
  const bonusPercent = Math.max(0, Number.parseFloat(topUpOption && topUpOption.bonus_percent || 0) || 0);
  return await createStripeCheckoutSession(
    env,
    {
      amountCents: centsForEur(amountEur),
      customerEmail: email,
      clientReferenceId: userId,
      productName: `Planetka €${amountEur.toFixed(2)} Balance Top-Up (+${bonusPercent}% Bonus)`,
      metadata: {
        planetka_purchase_type: "balance_top_up",
        planetka_user_id: userId,
        planetka_email: email,
        planetka_top_up_payment_eur: amountEur.toFixed(2),
        planetka_top_up_eur: balanceEur.toFixed(2),
        planetka_top_up_bonus_eur: bonusEur.toFixed(2),
        planetka_top_up_bonus_percent: String(bonusPercent),
      },
    },
    deps,
  );
}

function stripeSessionMetadata(session) {
  return session && session.metadata && typeof session.metadata === "object" ? session.metadata : {};
}

function parseStripeMetadataTileKeys(value) {
  try {
    const parsed = JSON.parse(String(value || "[]"));
    return normalizeTileKeys(Array.isArray(parsed) ? parsed : []);
  } catch (_error) {
    return [];
  }
}

function eurFromStripeAmountCents(value) {
  const cents = Number.parseInt(value, 10);
  if (!Number.isFinite(cents) || cents <= 0) {
    return 0;
  }
  return normalizeCreditAmount(cents / 100.0);
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

  if (option === "balance_options" || option === "balance" || option === "add_balance" || option === "top_up_options") {
    const tokenResult = await createBalanceTopUpTokenForUser(db, userId, env, deps);
    const url = new URL(request.url);
    url.pathname = "/credits/balance";
    url.search = "";
    url.searchParams.set("token", tokenResult.token);
    return deps.json(
      {
        ok: true,
        option: "balance_options",
        checkout_url: url.toString(),
        top_up_options: balanceTopUpOptions(),
        expires_at: tokenResult.expires_at,
      },
      200,
      env,
    );
  }

  const topUpOption = balanceTopUpOptionFromCheckoutOption(option);
  if (topUpOption) {
    const amountEur = topUpOption.amount_eur;
    const balanceEur = topUpOption.balance_eur;
    const bonusEur = topUpOption.bonus_eur;
    const session = await createBalanceTopUpStripeSession(env, topUpOption, email, userId, deps);
    if (session.error) {
      return deps.json({ ok: false, ...session }, 502, env);
    }
    return deps.json({
      ok: true,
      option: `balance_${String(amountEur).replace(".", "_")}`,
      price_eur: amountEur,
      balance_eur: balanceEur,
      bonus_eur: bonusEur,
      bonus_percent: topUpOption.bonus_percent,
      ...session,
    }, 200, env);
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
    const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(product.id || ""), env, deps);
    const url = new URL(request.url);
    url.pathname = "/credits/region-pack-checkout";
    url.search = "";
    url.searchParams.set("token", tokenResult.token);
    url.searchParams.set("region_pack_id", String(product.id || ""));
    return deps.json(
      {
        ok: true,
        option: "region_pack",
        payment_choice_required: true,
        region_pack: regionProductPublicPayload(product),
        price_eur: priceEur,
        gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
        discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
        paid_tile_count: estimate.paid_tile_count,
        new_tile_count: estimate.new_tile_count,
        tile_count: estimate.tile_count,
        checkout_url: url.toString(),
        expires_at: tokenResult.expires_at,
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
        message: "This scene price is below Stripe's minimum checkout amount. Add Planetka balance instead.",
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
  const tileKeys = requestTileKeysFromBody(body).slice(0, 256);
  const products = suggestedRegionProductsForContext(latitude, longitude, tileKeys);
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
    const priceEur = normalizeCreditAmount(estimate && estimate.price_eur);
    const newTileCount = Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0);
    if (priceEur <= 0 && newTileCount <= 0) {
      continue;
    }
    offers.push({
      ok: true,
      ...regionProductPublicPayload(product),
      gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
      gross_price_eur: normalizeCreditAmount(estimate && estimate.gross_price_eur),
      discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
      already_licenced_gross_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
      already_licenced_saving_eur: normalizeCreditAmount(estimate && estimate.already_licenced_saving_eur),
      credits: normalizeCreditAmount(estimate && estimate.credits),
      price_eur: priceEur,
      paid_tile_count: Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0),
      free_tile_count: Math.max(0, Number.parseInt(estimate && estimate.free_tile_count || 0, 10) || 0),
      tile_count: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      new_tile_count: newTileCount,
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
  if (!product || isHiddenRegionProduct(product)) {
    return deps.json({ ok: false, error: "unknown_region_pack" }, 404, env);
  }
  const tokenResult = await createRegionPackDetailTokenForUser(
    db,
    auth.user.id,
    String(product.id || ""),
    env,
    deps,
  );
  const url = new URL(request.url);
  url.pathname = "/credits/region-pack-map";
  url.search = "";
  url.searchParams.set("token", tokenResult.token);
  return deps.json(
    {
      ok: true,
      region_pack: regionProductPublicPayload(product),
      detail_url: url.toString(),
      expires_at: tokenResult.expires_at,
    },
    200,
    env,
  );
}

export async function handleCreditSceneDetailLink(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await ensureCreditAccount(db, auth.user.id, deps);
  await ensureSceneFullQualityDetailTokenTable(db, deps);
  const body = await deps.parseJson(request);
  const tileKeys = normalizeTileKeys(
    body && (
      body.tile_keys
      || body.tileKeys
      || body.tiles
      || body.pricing_tiles
      || body.pricingTiles
    ),
  );
  if (!tileKeys.length) {
    return deps.json({ ok: false, error: "missing_scene_tile_keys" }, 400, env);
  }
  if (tileKeys.length > 500) {
    return deps.json({ ok: false, error: "too_many_scene_tile_keys", tile_count: tileKeys.length }, 400, env);
  }
  const tokenResult = await createSceneFullQualityDetailTokenForUser(db, auth.user.id, tileKeys, env, deps);
  const url = new URL(request.url);
  url.pathname = "/credits/scene-map";
  url.search = "";
  url.searchParams.set("token", tokenResult.token);
  return deps.json(
    {
      ok: true,
      tile_count: tileKeys.length,
      detail_url: url.toString(),
      expires_at: tokenResult.expires_at,
    },
    200,
    env,
  );
}

async function getValidRegionPackDetailToken(db, token, deps) {
  const safeToken = String(token || "").trim();
  if (!safeToken) {
    return { error: "missing_token", status: 400 };
  }
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
    [safeToken],
  );
  if (!row || String(row.expires_at || "") <= now) {
    return { error: "expired_token", status: 410 };
  }
  return { ok: true, row };
}

async function getValidSceneFullQualityDetailToken(db, token, deps) {
  const safeToken = String(token || "").trim();
  if (!safeToken) {
    return { error: "missing_token", status: 400 };
  }
  await ensureSceneFullQualityDetailTokenTable(db, deps);
  const now = deps.nowIso();
  const row = await deps.dbGet(
    db,
    `
      SELECT token, user_id, tile_keys_json, expires_at
      FROM scene_full_quality_detail_tokens
      WHERE token = ?
      LIMIT 1
    `,
    [safeToken],
  );
  if (!row || String(row.expires_at || "") <= now) {
    return { error: "expired_token", status: 410 };
  }
  let tileKeys = [];
  try {
    tileKeys = normalizeTileKeys(JSON.parse(String(row.tile_keys_json || "[]")));
  } catch (error) {
    tileKeys = [];
  }
  if (!tileKeys.length) {
    return { error: "scene_detail_has_no_tiles", status: 410 };
  }
  return { ok: true, row: { ...row, tile_keys: tileKeys } };
}

async function getValidBalanceTopUpToken(db, token, deps) {
  const safeToken = String(token || "").trim();
  if (!safeToken) {
    return { error: "missing_token", status: 400 };
  }
  await ensureBalanceTopUpTokenTable(db, deps);
  const now = deps.nowIso();
  const row = await deps.dbGet(
    db,
    `
      SELECT token, user_id, expires_at
      FROM balance_top_up_tokens
      WHERE token = ?
      LIMIT 1
    `,
    [safeToken],
  );
  if (!row || String(row.expires_at || "") <= now) {
    return { error: "expired_token", status: 410 };
  }
  return { ok: true, row };
}

async function getValidAnyDetailToken(db, token, deps) {
  const region = await getValidRegionPackDetailToken(db, token, deps);
  if (region && region.ok) {
    return { ...region, token_type: "region_pack" };
  }
  const scene = await getValidSceneFullQualityDetailToken(db, token, deps);
  if (scene && scene.ok) {
    return { ...scene, token_type: "scene" };
  }
  return region && region.error ? region : scene;
}

function resolveRegionPackFromDetailTokenRow(row, requestedRegionId = "", options = {}) {
  const baseProduct = regionProductById(row && row.region_pack_id);
  if (!baseProduct) {
    return { error: "unknown_region_pack", status: 404 };
  }
  const requestedId = String(requestedRegionId || "").trim();
  const product = requestedId ? regionProductById(requestedId) : baseProduct;
  if (!product || isHiddenRegionProduct(product)) {
    return { error: "region_pack_not_available_for_this_detail_link", status: 403 };
  }
  if (!Boolean(options && options.allowAnyProduct) && !isSameOrRelatedHigherRegionProduct(baseProduct, product)) {
    return { error: "region_pack_not_available_for_this_detail_link", status: 403 };
  }
  return { ok: true, baseProduct, product };
}

async function regionPackCheckoutParams(request) {
  const url = new URL(request.url);
  const params = new Map();
  for (const key of ["token", "region_pack_id", "catalog", "method"]) {
    params.set(key, String(url.searchParams.get(key) || "").trim());
  }
  if (String(request.method || "GET").trim().toUpperCase() === "POST") {
    try {
      const form = await request.formData();
      for (const key of ["token", "region_pack_id", "catalog", "method"]) {
        const value = form.get(key);
        if (value !== null && value !== undefined) {
          params.set(key, String(value || "").trim());
        }
      }
    } catch (_error) {
      // Keep URL parameters as a fallback for malformed form posts.
    }
  }
  return {
    token: params.get("token") || "",
    requestedRegionId: params.get("region_pack_id") || "",
    allowCatalogProduct: params.get("catalog") === "1",
    method: String(params.get("method") || "").trim().toLowerCase(),
  };
}

function regionPackPaymentChoiceHtml(data) {
  const product = data && data.product || {};
  const estimate = data && data.estimate || {};
  const account = data && data.account || {};
  const name = String(product && product.name || "Region Pack").trim() || "Region Pack";
  const token = escapeHtmlText(String(data && data.token || ""));
  const regionPackId = escapeHtmlText(String(product && product.id || ""));
  const catalogInput = data && data.catalog_mode ? `<input type="hidden" name="catalog" value="1">` : "";
  const catalogParam = data && data.catalog_mode ? "&catalog=1" : "";
  const balanceTopUpToken = String(data && data.balance_top_up_token || "").trim();
  const balanceTopUpHref = balanceTopUpToken ? `/credits/balance?token=${escapeHtmlText(encodeURIComponent(balanceTopUpToken))}` : "";
  const mapHref = `/credits/region-pack-map?token=${escapeHtmlText(encodeURIComponent(String(data && data.token || "")))}&region_pack_id=${escapeHtmlText(encodeURIComponent(String(product && product.id || "")))}${catalogParam}`;
  const priceEur = normalizeCreditAmount(estimate && estimate.price_eur);
  const fullPriceEur = normalizeCreditAmount(regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur);
  const chargeableFullPriceEur = normalizeCreditAmount(estimate && estimate.gross_eur);
  const alreadyLicencedDeductionEur = normalizeCreditAmount(Math.max(0, fullPriceEur - chargeableFullPriceEur));
  const discountEur = normalizeCreditAmount(estimate && estimate.discount_eur);
  const discountPercent = Math.max(0, Number.parseInt(product && product.discount_percent || 0, 10) || 0);
  const balanceEur = normalizeSignedCreditAmount(account && account.balance_credits);
  const canUseBalance = priceEur > 0 && balanceEur >= priceEur;
  const stripeAvailable = centsForEur(priceEur) >= STRIPE_MIN_CHECKOUT_AMOUNT_CENTS;
  const insufficientBalance = priceEur > 0 && !canUseBalance;
  const stripeButton = stripeAvailable
    ? `<form method="post" action="/credits/region-pack-checkout"><input type="hidden" name="token" value="${token}"><input type="hidden" name="region_pack_id" value="${regionPackId}">${catalogInput}<input type="hidden" name="method" value="stripe"><button class="button" type="submit">Pay through payment gateway (€${priceEur.toFixed(2)})</button></form>`
    : `<button class="button disabled" type="button" disabled>Payment gateway unavailable below €${(STRIPE_MIN_CHECKOUT_AMOUNT_CENTS / 100).toFixed(2)}</button>`;
  const balanceButton = canUseBalance
    ? `<form method="post" action="/credits/region-pack-checkout"><input type="hidden" name="token" value="${token}"><input type="hidden" name="region_pack_id" value="${regionPackId}">${catalogInput}<input type="hidden" name="method" value="balance"><button class="button secondary" type="submit">Use Planetka balance (€${priceEur.toFixed(2)})</button></form>`
    : `<button class="button disabled" type="button" disabled>Use Planetka balance (€${balanceEur.toFixed(2)} available)</button>`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka ${escapeHtmlText(name)} Payment Options</title>
<style>
:root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--accent:#d9a441}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px}h1{margin:0 0 10px;font-size:28px;font-weight:650}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:14px}.muted{color:var(--muted)}.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}.card{background:#151515;border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:21px;margin-top:3px}.actions{display:grid;gap:10px;margin-top:14px}.button{width:100%;display:inline-flex;align-items:center;justify-content:center;padding:11px 13px;border:0;border-radius:9px;background:var(--accent);color:#111;text-decoration:none;font-weight:750;font:inherit;cursor:pointer}.button.secondary{background:#2a2a2a;color:var(--text);border:1px solid var(--line)}.button.disabled{background:#333;color:#888;border:1px solid var(--line);cursor:not-allowed}.notice{color:#f2c36b}.links{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}.links a{color:#f4d28d;text-decoration:none}
</style>
</head>
<body>
<main>
<h1>${escapeHtmlText(name)} Full Quality Pack</h1>
<section class="panel">
	<p>Choose how you want to licence this Full Quality data pack.</p>
	<div class="summary">
	<div class="card"><span>New / Total Tiles</span><b>${Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0)} / ${Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0)}</b></div>
	<div class="card"><span>Full Price</span><b>€${fullPriceEur.toFixed(2)}</b></div>
	<div class="card"><span>Already Licenced</span><b>-€${alreadyLicencedDeductionEur.toFixed(2)}</b></div>
	<div class="card"><span>Volume Discount</span><b>${discountPercent}% (-€${discountEur.toFixed(2)})</b></div>
	<div class="card"><span>Final Price</span><b>€${priceEur.toFixed(2)}</b></div>
	<div class="card"><span>Your Balance</span><b>€${balanceEur.toFixed(2)}</b></div>
	</div>
	${insufficientBalance ? `<p class="notice">Your balance is lower than this pack price. Use the payment gateway or add balance first.</p>` : ""}
<div class="actions">
${stripeButton}
${balanceButton}
</div>
<div class="links">
${balanceTopUpHref ? `<a href="${balanceTopUpHref}">Add balance</a>` : ""}
<a href="${mapHref}">View detailed map</a>
</div>
</section>
</main>
</body>
</html>`;
}

async function grantRegionPackFromBalance(db, userId, email, product, priceEur, estimate, deps) {
  const safeUserId = String(userId || "").trim();
  const amount = normalizeCreditAmount(priceEur);
  if (!safeUserId || amount <= 0) {
    return { error: "missing_positive_region_pack_amount" };
  }
  const account = await ensureCreditAccount(db, safeUserId, deps);
  const balanceBefore = normalizeSignedCreditAmount(account && account.balance_credits);
  if (balanceBefore < amount) {
    return {
      error: "insufficient_balance",
      balance_credits: balanceBefore,
      required_credits: amount,
    };
  }
  const now = deps.nowIso();
  const balancePurchaseId = `balance_region_pack_${deps.randomToken(16)}`;
  const update = await deps.dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET
        balance_credits = ROUND((balance_credits - ?) * 100.0) / 100.0,
        total_spent_credits = ROUND((total_spent_credits + ?) * 100.0) / 100.0,
        updated_at = ?
      WHERE user_id = ?
        AND balance_credits >= ?
    `,
    [amount, amount, now, safeUserId, amount],
  );
  if (deps.dbMetaChanges(update) <= 0) {
    const fresh = await ensureCreditAccount(db, safeUserId, deps);
    return {
      error: "insufficient_balance",
      balance_credits: normalizeSignedCreditAmount(fresh && fresh.balance_credits),
      required_credits: amount,
    };
  }
  const afterAccount = await ensureCreditAccount(db, safeUserId, deps);
  const balanceAfter = normalizeSignedCreditAmount(afterAccount && afterAccount.balance_credits);
  await deps.dbRun(
    db,
    `
      INSERT INTO credit_ledger (
        id, user_id, delta_credits, balance_after_credits, reason, metadata_json, created_at
      )
      VALUES (?, ?, ?, ?, 'balance_region_pack_purchase', ?, ?)
    `,
    [
      deps.randomToken(16),
      safeUserId,
      -amount,
      balanceAfter,
      JSON.stringify({
        payment_source: "balance",
        payment_reference_id: balancePurchaseId,
        region_pack_id: String(product && product.id || ""),
        region_pack_name: String(product && product.name || ""),
        region_pack_type: String(product && product.type || ""),
        catalog_version: REGION_PACK_CATALOG_VERSION,
        discount_percent: Math.max(0, Number.parseInt(product && product.discount_percent || 0, 10) || 0),
        discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
        quality_mode: "full",
        tile_count: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
        tile_count_total: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
        tile_count_new: Math.max(0, Number.parseInt(estimate && estimate.new_tile_count || 0, 10) || 0),
        tile_count_already_licenced: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
        gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
        paid_eur: amount,
      }),
      now,
    ],
  );
  const grant = await grantRegionPackEntitlements(
    db,
    safeUserId,
    String(product && product.id || ""),
    "",
    amount,
    deps,
    email,
    "",
    {
      payment_source: "balance",
      payment_reference_id: balancePurchaseId,
      purchase_history_id: balancePurchaseId,
      skip_credit_ledger: true,
    },
  );
  if (grant && grant.error) {
    await addCreditBalance(
      db,
      safeUserId,
      amount,
      "balance_region_pack_refund",
      {
        payment_source: "balance",
        payment_reference_id: balancePurchaseId,
        region_pack_id: String(product && product.id || ""),
        refund_reason: String(grant.error || "region_pack_grant_failed"),
      },
      deps,
    );
    return grant;
  }
  return {
    ok: true,
    balance_before_credits: balanceBefore,
    balance_after_credits: balanceAfter,
    payment_reference_id: balancePurchaseId,
    grant,
  };
}

export async function handleCreditRegionPackCheckoutFromToken(request, env, deps) {
  const { token, requestedRegionId, allowCatalogProduct, method } = await regionPackCheckoutParams(request);
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  if (tokenResult.error) {
    return html(
      "<!doctype html><title>Planetka Region Pack</title><h1>This region-pack payment link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 400,
      env,
    );
  }
  const productResult = allowCatalogProduct
    ? (() => {
      const product = regionProductById(requestedRegionId || tokenResult.row && tokenResult.row.region_pack_id);
      return product && !isHiddenRegionProduct(product) ? { ok: true, product } : { error: "region_pack_not_available_for_this_detail_link", status: 403 };
    })()
    : resolveRegionPackFromDetailTokenRow(tokenResult.row, requestedRegionId);
  if (!productResult.error && isHiddenRegionProduct(productResult.product)) {
    productResult.error = "region_pack_not_available_for_this_detail_link";
    productResult.status = 404;
  }
  if (productResult.error) {
    return html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Region pack unavailable.</h1><p>${escapeHtmlText(productResult.error)}</p>`,
      productResult.status || 400,
      env,
    );
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const user = await deps.dbGet(
    db,
    `SELECT id, email FROM users WHERE id = ? LIMIT 1`,
    [userId],
  );
  const email = deps.normalizeEmail(user && user.email || "");
  await ensureCreditAccount(db, userId, deps);
  const product = productResult.product;
  const estimate = await estimateRegionPack(db, userId, product, deps, { includeRows: false });
  if (estimate && estimate.error) {
    return html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Region pack estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
      500,
      env,
    );
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
      email,
    );
    if (grant && grant.error) {
      return html(
        `<!doctype html><title>Planetka Region Pack</title><h1>Region pack licence failed.</h1><p>${escapeHtmlText(grant.error)}</p>`,
        500,
        env,
      );
    }
    return html(
      checkoutReturnHtml({
        title: "Planetka Region Pack",
        heading: `${String(product.name || "Region Pack")} is already licenced`,
        message: "This pack has no newly charged Full Quality tiles. You can return to Blender.",
        icon: "OK",
        tone: "success",
      }),
      200,
      env,
    );
  }
  const amountCents = centsForEur(priceEur);
  const account = await ensureCreditAccount(db, userId, deps);
  const balanceToken = await createBalanceTopUpTokenForUser(db, userId, env, deps);

  if (method === "balance") {
    const balanceGrant = await grantRegionPackFromBalance(db, userId, email, product, priceEur, estimate, deps);
    if (balanceGrant && balanceGrant.error) {
      return html(
        regionPackPaymentChoiceHtml({
          token,
          product,
          estimate,
          account: await ensureCreditAccount(db, userId, deps),
          catalog_mode: allowCatalogProduct,
          balance_top_up_token: balanceToken && balanceToken.token,
        }),
        balanceGrant.error === "insufficient_balance" ? 402 : 500,
        env,
      );
    }
    if (typeof deps.invalidateAnalyticsSnapshots === "function") {
      try {
        await deps.invalidateAnalyticsSnapshots(env);
      } catch (error) {
        console.warn(
          "region_pack.balance_purchase_snapshot_invalidate_failed",
          JSON.stringify({ user_id: userId, region_pack_id: String(product.id || ""), error: String(error && error.message || "snapshot_invalidate_failed") }),
        );
      }
    }
    const success = {
      title: "Licence applied",
      message: `€${priceEur.toFixed(2)} was deducted from your Planetka balance. ${String(product.name || "This pack")} is now licenced to your account.`,
    };
    if (String(product.id || "").trim().toLowerCase() === "world") {
      const safeToken = escapeHtmlText(encodeURIComponent(token));
      const fullPrice = normalizeCreditAmount(regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur).toFixed(2);
      return html(
        `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Planetka World Pack</title><style>:root{color-scheme:dark}body{margin:0;background:#111;color:#eee;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:820px;margin:0 auto;padding:24px}.panel{background:#1b1b1b;border:1px solid #3c3c3c;border-radius:12px;padding:14px;margin-top:14px}.button{display:inline-flex;align-items:center;justify-content:center;margin:8px 8px 0 0;padding:9px 12px;border-radius:8px;background:#d9a441;color:#111;text-decoration:none;font-weight:700}.secondary{background:#2a2a2a;color:#eee;border:1px solid #3c3c3c}.muted{color:#aaa}</style></head><body><main><h1>World Full Quality Pack</h1><section class="panel"><h2>${escapeHtmlText(success.title)}</h2><p>${escapeHtmlText(success.message)}</p></section><section class="panel"><p>The World pack includes the complete Full Quality texture dataset. A full interactive tile map is intentionally not generated because it would be too large for a useful browser view.</p><p class="muted">Full price: €${fullPrice}<br>Final price: €${priceEur.toFixed(2)}</p><a class="button secondary" href="/credits/region-pack-catalog?token=${safeToken}">View all data packs</a></section></main></body></html>`,
        200,
        env,
      );
    }
    const ownedRows = await ownedTileRowsForUser(db, userId, deps);
    const refreshedAccount = await ensureCreditAccount(db, userId, deps);
    const data = regionPackStaticMapPayload(product, token, refreshedAccount, ownedRows, {
      catalogMode: allowCatalogProduct,
      success,
    });
    return html(regionPackStaticMapHtml(data), 200, env);
  }

  if (method !== "stripe") {
    return html(
      regionPackPaymentChoiceHtml({
        token,
        product,
        estimate,
        account,
        catalog_mode: allowCatalogProduct,
        balance_top_up_token: balanceToken && balanceToken.token,
      }),
      200,
      env,
    );
  }

  if (amountCents < STRIPE_MIN_CHECKOUT_AMOUNT_CENTS) {
    return html(
      regionPackPaymentChoiceHtml({
        token,
        product,
        estimate,
        account,
        catalog_mode: allowCatalogProduct,
        balance_top_up_token: balanceToken && balanceToken.token,
      }),
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
        planetka_checkout_source: allowCatalogProduct ? "region_pack_catalog" : "region_pack_map_upsell",
      },
    },
    deps,
  );
  if (session.error || !session.checkout_url) {
    return html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Stripe checkout failed.</h1><p>${escapeHtmlText(session.message || session.error || "checkout_failed")}</p>`,
      502,
      env,
    );
  }
  return Response.redirect(session.checkout_url, 303);
}

export async function handleCreditRegionPackMap(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const allowCatalogProduct = String(url.searchParams.get("catalog") || "") === "1";
  if (!token) {
    return html(
      "<!doctype html><title>Planetka Region Pack</title><h1>Missing region-pack detail token.</h1>",
      400,
      env,
    );
  }
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  if (tokenResult.error) {
    return html(
      "<!doctype html><title>Planetka Region Pack</title><h1>This region-pack detail link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 410,
      env,
    );
  }
  const requestedRegionId = String(url.searchParams.get("region_pack_id") || "").trim();
  const productResult = allowCatalogProduct
    ? (() => {
      const product = regionProductById(requestedRegionId || tokenResult.row && tokenResult.row.region_pack_id);
      return product ? { ok: true, product } : { error: "region_pack_not_available_for_this_detail_link", status: 403 };
    })()
    : resolveRegionPackFromDetailTokenRow(tokenResult.row, requestedRegionId);
  if (productResult.error) {
    return html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Region pack unavailable.</h1><p>${escapeHtmlText(productResult.error)}</p>`,
      productResult.status || 404,
      env,
    );
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const product = productResult.product;
  const account = await ensureCreditAccount(db, userId, deps);
  if (String(product && product.id || "").trim().toLowerCase() === "world") {
    const estimate = await estimateRegionPack(db, userId, product, deps, { includeRows: false });
    if (estimate && estimate.error) {
      return html(
        `<!doctype html><title>Planetka Region Pack</title><h1>Region pack estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
        500,
        env,
      );
    }
    const safeToken = escapeHtmlText(encodeURIComponent(token));
    const price = normalizeCreditAmount(estimate && estimate.price_eur).toFixed(2);
    const fullPrice = normalizeCreditAmount(regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur).toFixed(2);
    return html(
      `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Planetka World Pack</title><style>:root{color-scheme:dark}body{margin:0;background:#111;color:#eee;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:820px;margin:0 auto;padding:24px}.panel{background:#1b1b1b;border:1px solid #3c3c3c;border-radius:12px;padding:14px}.button{display:inline-flex;align-items:center;justify-content:center;margin:8px 8px 0 0;padding:9px 12px;border-radius:8px;background:#d9a441;color:#111;text-decoration:none;font-weight:700}.secondary{background:#2a2a2a;color:#eee;border:1px solid #3c3c3c}.muted{color:#aaa}</style></head><body><main><h1>World Full Quality Pack</h1><section class="panel"><p>The World pack includes the complete Full Quality texture dataset. A full interactive tile map is intentionally not generated because it would be too large for a useful browser view.</p><p class="muted">Full price: €${fullPrice}<br>Final price: €${price}</p><a class="button" href="/credits/region-pack-checkout?token=${safeToken}&region_pack_id=world&catalog=1">Buy World (€${price})</a><a class="button secondary" href="/credits/region-pack-catalog?token=${safeToken}">Back to all data packs</a></section></main></body></html>`,
      200,
      env,
    );
  }
  const ownedRows = await ownedTileRowsForUser(db, userId, deps);
  const data = regionPackStaticMapPayload(product, token, account, ownedRows, { catalogMode: allowCatalogProduct });
  return html(regionPackStaticMapHtml(data), 200, env);
}

export async function handleCreditRegionPackMapAsset(request, env, deps) {
  const url = new URL(request.url);
  const regionPackId = String(url.searchParams.get("region_pack_id") || url.searchParams.get("id") || "").trim();
  const product = regionProductById(regionPackId);
  if (!product || isHiddenRegionProduct(product) || String(product.id || "").trim().toLowerCase() === "world") {
    return deps.json({ ok: false, error: "region_pack_map_asset_not_available" }, 404, env);
  }
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env);
  }
  const object = await bucket.get(regionPackMapAssetKey(env, product.id));
  if (!object || !object.body) {
    return deps.json({ ok: false, error: "region_pack_map_asset_missing" }, 404, env);
  }
  return new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      ...corsHeaders(env),
    },
  });
}

export async function handleCreditRegionPackMapBackground(request, env, deps) {
  void request;
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env);
  }
  const object = await bucket.get(regionPackMapBackgroundKey(env));
  if (!object || !object.body) {
    return deps.json({ ok: false, error: "region_pack_map_background_missing" }, 404, env);
  }
  return new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": "public, max-age=86400",
      ...corsHeaders(env),
    },
  });
}

export async function handleCreditRegionPackCatalogAsset(request, env, deps) {
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env);
  }
  const object = await bucket.get(regionPackCatalogAssetKey(env));
  if (!object || !object.body) {
    return deps.json({ ok: false, error: "region_pack_catalog_asset_missing" }, 404, env);
  }
  return new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=86400",
      ...corsHeaders(env),
    },
  });
}

export async function handleCreditRegionPackCatalog(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return html(
      "<!doctype html><title>Planetka Data Packs</title><h1>Missing region-pack detail token.</h1>",
      400,
      env,
    );
  }
  const db = deps.requireDb(env);
  const tokenResult = await getValidAnyDetailToken(db, token, deps);
  if (tokenResult.error) {
    return html(
      "<!doctype html><title>Planetka Data Packs</title><h1>This data-pack link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 410,
      env,
    );
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const account = await ensureCreditAccount(db, userId, deps);
  const ownedRows = await ownedTileRowsForUser(db, userId, deps);
  return html(
    regionPackStaticCatalogHtml({
      ok: true,
      catalog_version: REGION_PACK_CATALOG_VERSION,
      map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
      token,
      owned_tiles: ownedTilePayloadRows(ownedRows),
      world_full_quality_unlocked: isWorldFullQualityUnlocked(account),
    }),
    200,
    env,
  );
}

export async function handleCreditSceneMap(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return html(
      "<!doctype html><title>Planetka Scene Textures</title><h1>Missing scene detail token.</h1>",
      400,
      env,
    );
  }
  const db = deps.requireDb(env);
  const tokenResult = await getValidSceneFullQualityDetailToken(db, token, deps);
  if (tokenResult.error) {
    return html(
      "<!doctype html><title>Planetka Scene Textures</title><h1>This scene detail link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 410,
      env,
    );
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  await ensureCreditAccount(db, userId, deps);
  const tileKeys = normalizeTileKeys(tokenResult.row && tokenResult.row.tile_keys);
  const estimate = await estimateNewCredits(db, userId, tileKeys, "full", deps);
  if (estimate && estimate.error) {
    return html(
      `<!doctype html><title>Planetka Scene Textures</title><h1>Scene estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
      500,
      env,
    );
  }
  const preliminaryRows = allocatedRegionPackTileRows(estimate);
  const center = tileRowsCenter(preliminaryRows);
  const contextProducts = center
    ? suggestedRegionProductsForPoint(center.latitude_deg, center.longitude_deg)
    : [];
  const contextProduct = contextProducts.length ? contextProducts[0] : null;
  const upsells = [];
  for (const product of contextProducts.slice(0, 4)) {
    const relatedEstimate = await estimateRegionPackForMap(db, userId, product, deps);
    if (relatedEstimate && !relatedEstimate.error) {
      const relatedPrice = normalizeCreditAmount(relatedEstimate && relatedEstimate.price_eur);
      const relatedNewTiles = Math.max(0, Number.parseInt(relatedEstimate && relatedEstimate.new_tile_count || 0, 10) || 0);
      if (relatedPrice <= 0 && relatedNewTiles <= 0) {
        continue;
      }
      upsells.push(buildRegionPackUpsellCardData(product, relatedEstimate));
    }
  }
  const data = buildSceneFullQualityMapData(estimate, { token, contextProduct, upsells });
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
  const url = new URL(request.url);
  const sessionId = String(url.searchParams.get("session_id") || "").trim();
  if (!sessionId) {
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

  const db = deps.requireDb(env);
  await deps.ensureCreditTables(db);
  const purchase = await loadPurchaseHistoryByStripeSession(db, sessionId, deps);
  let session = null;
  let metadata = {};
  if (!purchase) {
    const sessionResult = await fetchStripeCheckoutSession(env, sessionId, deps);
    if (sessionResult && sessionResult.ok) {
      session = sessionResult.session;
      metadata = stripeSessionMetadata(session);
    }
  }
  const purchaseType = String(
    purchase && purchase.purchase_type
      || metadata.planetka_purchase_type
      || "",
  ).trim().toLowerCase();
  const userId = String(
    purchase && purchase.user_id
      || metadata.planetka_user_id
      || session && session.client_reference_id
      || "",
  ).trim();
  const amountPaidEur = normalizeCreditAmount(
    purchase && purchase.amount_paid_eur
      || metadata.planetka_price_eur
      || eurFromStripeAmountCents(session && session.amount_total),
  );
  const applied = Boolean(purchase && purchase.id);
  const success = {
    title: "Payment successful",
    message: applied
      ? `Your Planetka licence has been applied. Here are the details of your purchase${amountPaidEur > 0 ? ` (€${amountPaidEur.toFixed(2)})` : ""}.`
      : "Your payment was successful. Stripe is applying the licence now; Blender will refresh automatically. Here are the purchase details.",
  };

  if (!userId || !purchaseType) {
    return html(
      checkoutReturnHtml({
        title: "Planetka Payment Complete",
        heading: "Payment successful",
        message: "Your Planetka payment was completed. Return to Blender; the panel will refresh automatically.",
        icon: "OK",
        tone: "success",
      }),
      200,
      env,
    );
  }

  if (purchaseType === "scene_tiles") {
    const historyTiles = purchase && purchase.id ? await loadPurchaseHistoryTiles(db, purchase.id, deps) : [];
    const tileKeys = historyTiles.length
      ? normalizeTileKeys(historyTiles.map((row) => row && row.tile_key || ""))
      : parseStripeMetadataTileKeys(metadata.planetka_tile_keys_json);
    if (!tileKeys.length) {
      return html(
        checkoutReturnHtml({
          title: "Planetka Payment Complete",
          heading: "Payment successful",
          message: "Your Full Quality scene texture purchase was completed. Return to Blender; the panel will refresh automatically.",
          icon: "OK",
          tone: "success",
        }),
        200,
        env,
      );
    }
    const tokenResult = await createSceneFullQualityDetailTokenForUser(db, userId, tileKeys, env, deps);
    const estimate = historyTiles.length
      ? sceneEstimateFromPurchaseTiles(purchase, historyTiles)
      : await estimateNewCredits(db, userId, tileKeys, "full", deps);
    if (estimate && !estimate.error) {
      const preliminaryRows = allocatedRegionPackTileRows(estimate);
      const center = tileRowsCenter(preliminaryRows);
      const contextProducts = center
        ? suggestedRegionProductsForPoint(center.latitude_deg, center.longitude_deg)
        : [];
      const contextProduct = contextProducts.length ? contextProducts[0] : null;
      const upsells = [];
      for (const product of contextProducts.slice(0, 4)) {
        const relatedEstimate = await estimateRegionPackForMap(db, userId, product, deps);
        if (relatedEstimate && !relatedEstimate.error) {
          const relatedPrice = normalizeCreditAmount(relatedEstimate && relatedEstimate.price_eur);
          const relatedNewTiles = Math.max(0, Number.parseInt(relatedEstimate && relatedEstimate.new_tile_count || 0, 10) || 0);
          if (relatedPrice <= 0 && relatedNewTiles <= 0) {
            continue;
          }
          upsells.push(buildRegionPackUpsellCardData(product, relatedEstimate));
        }
      }
      const data = buildSceneFullQualityMapData(estimate, {
        token: tokenResult.token,
        contextProduct,
        upsells,
        success,
      });
      return html(regionPackMapHtml(data), 200, env);
    }
  }

  if (purchaseType === "region_pack") {
    const regionPackId = String(purchase && purchase.region_pack_id || metadata.planetka_region_id || "").trim();
    const product = regionProductById(regionPackId);
    if (product) {
      const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(product.id || ""), env, deps);
      if (String(product.id || "").trim().toLowerCase() === "world") {
        const fullPrice = normalizeCreditAmount(
          purchase && purchase.gross_eur
            || metadata.planetka_gross_eur
            || regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur,
        );
        const price = amountPaidEur;
        const safeToken = escapeHtmlText(encodeURIComponent(tokenResult.token));
        return html(
          `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Planetka World Pack</title><style>:root{color-scheme:dark}body{margin:0;background:#111;color:#eee;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:820px;margin:0 auto;padding:24px}.panel{background:#1b1b1b;border:1px solid #3c3c3c;border-radius:12px;padding:14px;margin-top:14px}.button{display:inline-flex;align-items:center;justify-content:center;margin:8px 8px 0 0;padding:9px 12px;border-radius:8px;background:#d9a441;color:#111;text-decoration:none;font-weight:700}.secondary{background:#2a2a2a;color:#eee;border:1px solid #3c3c3c}.muted{color:#aaa}</style></head><body><main><h1>World Full Quality Pack</h1><section class="panel"><h2>Payment successful</h2><p>${escapeHtmlText(success.message)}</p></section><section class="panel"><p>The World pack includes the complete Full Quality texture dataset. A full interactive tile map is intentionally not generated because it would be too large for a useful browser view.</p><p class="muted">Full price: €${fullPrice.toFixed(2)}<br>Final price: €${price.toFixed(2)}</p><a class="button secondary" href="/credits/region-pack-catalog?token=${safeToken}">View all data packs</a></section></main></body></html>`,
          200,
          env,
        );
      }
      const account = await ensureCreditAccount(db, userId, deps);
      const ownedRows = await ownedTileRowsForUser(db, userId, deps);
      const data = regionPackStaticMapPayload(product, tokenResult.token, account, ownedRows, {
        catalogMode: true,
        success,
      });
      return html(regionPackStaticMapHtml(data), 200, env);
    }
  }

  if (purchaseType === "standard_quality_unlock") {
    return html(
      checkoutReturnHtml({
        title: "Planetka Standard Quality",
        heading: "Standard Quality unlocked",
        message: `Payment successful${amountPaidEur > 0 ? ` (€${amountPaidEur.toFixed(2)})` : ""}. Standard Quality textures are now unlocked for this account.`,
        icon: "OK",
        tone: "success",
      }),
      200,
      env,
    );
  }

  if (purchaseType === "balance_top_up") {
    let creditedEur = normalizeCreditAmount(
      purchase && purchase.nominal_eur
        || metadata.planetka_top_up_eur
        || amountPaidEur,
    );
    let bonusEur = normalizeCreditAmount(metadata.planetka_top_up_bonus_eur || 0);
    if (purchase && purchase.metadata_json) {
      try {
        const purchaseMetadata = JSON.parse(String(purchase.metadata_json || "{}"));
        creditedEur = normalizeCreditAmount(purchaseMetadata.balance_added_eur || purchaseMetadata.top_up_eur || creditedEur);
        bonusEur = normalizeCreditAmount(purchaseMetadata.top_up_bonus_eur || bonusEur);
      } catch (_error) {
        // The success page is best-effort; webhook state remains authoritative.
      }
    }
    const bonusText = bonusEur > 0 ? ` including €${bonusEur.toFixed(2)} bonus` : "";
    return html(
      checkoutReturnHtml({
        title: "Planetka Balance Added",
        heading: "Balance added",
        message: `Payment successful${amountPaidEur > 0 ? ` (€${amountPaidEur.toFixed(2)})` : ""}. €${creditedEur.toFixed(2)} was added to your Planetka balance${bonusText}. Blender will refresh automatically.`,
        icon: "OK",
        tone: "success",
      }),
      200,
      env,
    );
  }

  return html(
    checkoutReturnHtml({
      title: "Planetka Payment Complete",
      heading: "Payment successful",
      message: "Your Planetka payment was completed. Return to Blender; the panel will refresh automatically.",
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

async function loadPurchaseHistoryByStripeSession(db, stripeSessionId, deps) {
  await deps.ensureCreditTables(db);
  const safeSessionId = String(stripeSessionId || "").trim();
  if (!safeSessionId) {
    return null;
  }
  return await deps.dbGet(
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
      WHERE stripe_session_id = ?
      LIMIT 1
    `,
    [safeSessionId],
  );
}

async function loadPurchaseHistoryTiles(db, purchaseId, deps) {
  await deps.ensureCreditTables(db);
  const safePurchaseId = String(purchaseId || "").trim();
  if (!safePurchaseId) {
    return [];
  }
  return await deps.dbAll(
    db,
    `
      SELECT
        tile_key,
        tile_status,
        price_eur,
        gross_price_eur,
        land_km2,
        billable_land_km2,
        quality_mode,
        created_at
      FROM purchase_history_tiles
      WHERE purchase_id = ?
      ORDER BY tile_key ASC
    `,
    [safePurchaseId],
  );
}

function sceneEstimateFromPurchaseTiles(purchase, rows) {
  const tiles = [];
  let total = 0;
  for (const row of rows || []) {
    const key = normalizeTileKey(row && row.tile_key || "");
    if (!key) {
      continue;
    }
    const price = normalizeCreditAmount(row && row.price_eur);
    const gross = normalizeCreditAmount(row && (row.gross_price_eur ?? row.price_eur));
    total = normalizeCreditAmount(total + price);
    tiles.push({
      tile_key: key,
      credits: price,
      price_eur: price,
      gross_credits: gross,
      gross_price_eur: gross,
      land_km2: normalizeMetricAmount(row && row.land_km2),
      billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
      already_owned: false,
      globally_free: false,
      free_reason: "",
    });
  }
  const amountPaid = normalizeCreditAmount(purchase && purchase.amount_paid_eur);
  return {
    ok: true,
    credits: amountPaid > 0 ? amountPaid : total,
    price_eur: amountPaid > 0 ? amountPaid : total,
    paid_tile_count: tiles.length,
    free_tile_count: 0,
    tile_count: Math.max(tiles.length, Number.parseInt(purchase && purchase.tile_count_total || 0, 10) || 0),
    new_tile_count: tiles.length,
    new_tiles: tiles,
    tiles,
    excluded_tiles: [],
    integrity_warnings: [],
    metadata_missing_tile_keys: [],
  };
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

export async function handleCreditLicencedDownloadReport(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await deps.ensureCreditTables(db);
  await ensureCreditAccount(db, auth.user.id, deps);
  const body = await deps.parseJson(request);
  const maxBytes = 20 * 1024 * 1024 * 1024 * 1024;
  const downloadedBytes = Math.min(
    maxBytes,
    deps.clampNonNegativeInt(body && (body.downloaded_bytes ?? body.downloadedBytes ?? body.bytes)),
  );
  const downloadedTiles = Math.min(
    10000000,
    deps.clampNonNegativeInt(body && (body.downloaded_tile_count ?? body.downloadedTileCount ?? body.tiles)),
  );
  const downloadedFiles = Math.min(
    10000000,
    deps.clampNonNegativeInt(body && (body.downloaded_file_count ?? body.downloadedFileCount ?? body.files)),
  );
  const skippedExistingFiles = Math.min(
    10000000,
    deps.clampNonNegativeInt(body && (body.skipped_existing_files ?? body.skippedExistingFiles)),
  );
  const missingFiles = Math.min(
    10000000,
    deps.clampNonNegativeInt(body && (body.missing_files ?? body.missingFiles)),
  );
  const period = String(body && body.period || "ALL").trim().toUpperCase().slice(0, 32) || "ALL";
  const status = String(body && body.status || "FINISHED").trim().toUpperCase().slice(0, 32) || "FINISHED";
  const source = String(body && body.source || "blender_download_licenced").trim().slice(0, 80) || "blender_download_licenced";
  if (downloadedBytes <= 0 && downloadedTiles <= 0 && downloadedFiles <= 0) {
    return deps.json({ ok: true, recorded: false }, 200, env);
  }
  const userId = String(auth.user.id || "").trim();
  const now = deps.nowIso();
  await deps.dbRun(
    db,
    `
      INSERT INTO user_licenced_download_events (
        id, user_id, downloaded_bytes, downloaded_tiles, downloaded_files,
        skipped_existing_files, missing_files, period, status, source, created_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      deps.randomToken(16),
      userId,
      downloadedBytes,
      downloadedTiles,
      downloadedFiles,
      skippedExistingFiles,
      missingFiles,
      period,
      status,
      source,
      now,
    ],
  );
  await deps.dbRun(
    db,
    `
      INSERT INTO user_licenced_download_stats (
        user_id, total_downloaded_bytes, total_downloaded_tiles, total_downloaded_files, last_downloaded_at
      )
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(user_id) DO UPDATE SET
        total_downloaded_bytes = user_licenced_download_stats.total_downloaded_bytes + excluded.total_downloaded_bytes,
        total_downloaded_tiles = user_licenced_download_stats.total_downloaded_tiles + excluded.total_downloaded_tiles,
        total_downloaded_files = user_licenced_download_stats.total_downloaded_files + excluded.total_downloaded_files,
        last_downloaded_at = excluded.last_downloaded_at
    `,
    [userId, downloadedBytes, downloadedTiles, downloadedFiles, now],
  );
  if (typeof deps.invalidateAnalyticsSnapshots === "function") {
    try {
      await deps.invalidateAnalyticsSnapshots(env);
    } catch (error) {
      console.warn(
        "planetka.licenced_download.analytics_snapshot_invalidate_failed",
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
      recorded: true,
      downloaded_bytes: downloadedBytes,
      downloaded_tile_count: downloadedTiles,
      downloaded_file_count: downloadedFiles,
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
