import { corsHeaders, html } from "./responses.js";
import {
  GENERATED_REGION_PACK_CATALOG_VERSION,
  GENERATED_REGION_PACK_PRODUCTS,
} from "./region_packs.products.generated.js";
import {
  GENERATED_REGION_PACK_RELATION_GRAPH_VERSION,
  GENERATED_REGION_PACK_RELATIONS_BY_OWNED,
  GENERATED_REGION_PACK_RELATIONS_BY_TARGET,
} from "./region_packs.relations.generated.js";

const TILE_KEY_RE = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i;
const ASSET_RE = /^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$/i;
const FREE_D_THRESHOLD = 60;
const ACCOUNT_TYPE_DEFAULT = "account";
const DATASET_BASE_MPP = 10.0;
const EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2;
// Runtime pricing policy. Generated catalogs keep coefficient-1.0 gross prices;
// these settings are applied at request time so price policy changes do not
// require rebuilding static region products.
const DEFAULT_FULL_QUALITY_PRICE_COEFFICIENT = 5.00;
const PUBLIC_COEFFICIENT_TO_LEGACY_GROSS_MULTIPLIER = EQUATOR_Z001_AREA_KM2 / 10000;
const DEFAULT_REGION_PACK_DISCOUNT_MIN_PERCENT = 0;
const DEFAULT_REGION_PACK_DISCOUNT_MAX_PERCENT = 75;
const DEFAULT_SCENE_CUSTOM_LICENCE_FEE_EUR = 1.50;
const DEFAULT_ANIMATION_CUSTOM_LICENCE_MAX_FEE_EUR = 9.00;
const BETA_FULL_WORLD_ACCESS_ENABLED = true;
const BETA_FULL_WORLD_ACCESS_EXCLUDED_EMAILS = new Set(["tom.griger@gmail.com"]);
const DEFAULT_NO_PURCHASE_QUOTE_USER_ID = "__planetka_default_no_purchase__";
const DEFAULT_BETA_FULL_WORLD_QUOTE_USER_ID = "__planetka_default_beta_full_world__";
const DEFAULT_NO_PURCHASE_ENTITLEMENT_VERSION = "default_no_purchase_v1";
const DEFAULT_BETA_FULL_WORLD_ENTITLEMENT_VERSION = "default_beta_full_world_v1";
const PRICING_SETTINGS_CACHE_TTL_MS = 30 * 1000;
const PRICING_SETTINGS_KEYS = {
  coefficient: "full_quality_price_coefficient",
  minDiscount: "region_pack_discount_min_percent",
  maxDiscount: "region_pack_discount_max_percent",
  discountShareBuckets: "region_pack_discount_share_buckets_json",
  sceneCustomLicenceFee: "custom_scene_licence_fee_eur",
  animationCustomLicenceMaxFee: "custom_animation_licence_max_fee_eur",
  legacyAnimationCustomLicenceFee: "custom_animation_licence_fee_eur",
  productDiscountPrefix: "region_pack_discount_override:",
};
const DEFAULT_REGION_PACK_DISCOUNT_SHARE_BUCKETS = [
  [0.40, 1.0],
  [0.20, 5.0 / 6.0],
  [0.10, 4.0 / 6.0],
  [0.05, 3.0 / 6.0],
  [0.025, 2.0 / 6.0],
  [0.0125, 1.0 / 6.0],
  [0.0, 0.0],
];
const STRIPE_MIN_CHECKOUT_AMOUNT_CENTS = 50;
const SCENE_SMALL_FREE_THRESHOLD_CENTS = 50;
const SCENE_CUSTOM_LICENCE_LABEL = "Custom scene-specific licence";
const ANIMATION_CUSTOM_LICENCE_LABEL = "Custom animation licence";
const ANIMATION_CHECKOUT_MAX_UNIQUE_TILES = 5000;
const CHECKOUT_TILE_SET_TOKEN_TTL_MINUTES = 24 * 60;
const MONEY_SCALE = 100;
const METRIC_SCALE = 1_000_000;
const REGION_PACK_CATALOG_VERSION = GENERATED_REGION_PACK_CATALOG_VERSION || "gadm_regions_v8";
const REGION_PACK_MAP_ASSET_REVISION = `${REGION_PACK_CATALOG_VERSION}:outline-v4-product-bg-wt-blue-v4-partial-dateline-v7-admin-labels-v1-success-upsell-v1-catalog-flat-v1-price-breakdown-v1-hover-breakdown-v1-summary-partial-v1-pricing-runtime-v5-runtime-buckets-v1-canonical-pricing-v2-coeff-km2-v1-post-purchase-new-v1-button-border-gold-v1-tile-tooltip-v5-immediate-static-js-v10-product-outlines-v1-on-demand-map-v4-incremental-chunks-v1-geo-bg-v1-soft-red-v1-scene-map-v1-tooltip-cardinal-v2-product-bg-frame-v1-white-bg-v2-mini-upsell-tiles-v2-product-map-d-equals-z-v1-chunk1000-v2-wt-tile-bg-v2-scene-page-v3-map-loading-v6-live-bounds-nofallback-bg-v1`;
const REGION_PACK_PRICING_ENGINE_REVISION = "d1-complete-map-state-v2";
const ACCOUNT_COUNTRY_BORDERS_ASSET_REVISION = `${REGION_PACK_CATALOG_VERSION}:account-country-borders-v1`;
const SQL_VARIABLE_SAFE_CHUNK_SIZE = 75;
const REGION_PACK_TILE_CHUNK_SIZE = SQL_VARIABLE_SAFE_CHUNK_SIZE;
const REGION_PACK_PAID_Z_LEVELS = [1, 2, 4, 8, 15, 30];
const REGION_PACK_MAP_MAX_OUTLINE_POINTS = 250_000;
const REGION_OFFER_MAX_TILE_COUNTRY_DISTANCE_DEG = 4.0;
const REGION_SIMILAR_COUNTRY_MAX_DISTANCE_DEG = 2.0;
const REGION_PRODUCTS = Array.isArray(GENERATED_REGION_PACK_PRODUCTS) ? GENERATED_REGION_PACK_PRODUCTS : [];
const GENERATED_REGION_PACK_DETAILS = {};
const GENERATED_REGION_PACK_OUTLINES = {};
const REGION_PRODUCT_BY_ID = new Map(REGION_PRODUCTS.map((product) => [
  String(product && product.id || "").trim().toLowerCase(),
  product,
]).filter(([id]) => Boolean(id)));
const REGION_PACK_STATIC_RELATION_GRAPH_READY = String(GENERATED_REGION_PACK_RELATION_GRAPH_VERSION || "") === REGION_PACK_CATALOG_VERSION
  && GENERATED_REGION_PACK_RELATIONS_BY_TARGET
  && typeof GENERATED_REGION_PACK_RELATIONS_BY_TARGET === "object";
const REGION_PRODUCT_COUNTRY_ID_SET_CACHE = new Map();
const REGION_PRODUCT_GROSS_CENTS_CACHE = new Map();
const REGION_PRODUCT_PRICING_SUMMARY_CACHE = new Map();
const REGION_PRODUCT_Z001_CELL_CACHE = new Map();
const REGION_PRODUCT_TILE_FAMILY_CACHE = new Map();
const USER_CREDIT_ACCOUNT_CACHE = new Map();
const USER_ENTITLEMENT_SUMMARY_CACHE = new Map();
const REGION_OFFERS_RESPONSE_CACHE = new Map();
const REGION_PACK_ESTIMATE_CACHE = new Map();
const REGION_PACK_RELATION_CACHE = new Map();
const DETAIL_TOKEN_CACHE = new Map();
let PRICING_SETTINGS_CACHE = {
  loaded_at_ms: 0,
  settings: null,
};
const COUNTRY_LIKE_REGION_PRODUCT_IDS = new Set(["australia", "canada", "china", "united_states"]);
const NORTH_AMERICA_SIMILAR_COUNTRY_LIKE_IDS = new Set(["canada", "united_states"]);
const USER_CREDIT_ACCOUNT_CACHE_MAX = 2048;
const USER_ENTITLEMENT_SUMMARY_CACHE_MAX = 32;
const REGION_OFFERS_RESPONSE_CACHE_MAX = 1024;
const REGION_PACK_ESTIMATE_CACHE_MAX = 512;
const REGION_PACK_RELATION_CACHE_MAX = 4096;
const DETAIL_TOKEN_CACHE_MAX = 4096;
const REGION_PRODUCT_TILE_KEYS_CACHE_MAX = 128;
const REGION_PRODUCT_SORTED_TILE_KEYS_CACHE_MAX = 128;
const REGION_PRODUCT_TILE_KEYS_CACHE_MAX_KEYS = 1200;
const REGION_PACK_CATALOG_PAGE_MAX_LIMIT = 20;
const REGION_PACK_MAP_LEVEL_CHUNK_LIMIT = 1000;
const USER_CREDIT_ACCOUNT_CACHE_TTL_MS = 30 * 1000;
const USER_ENTITLEMENT_SUMMARY_CACHE_TTL_MS = 2 * 60 * 1000;
const REGION_OFFERS_RESPONSE_CACHE_TTL_MS = 20 * 1000;
const REGION_PACK_ESTIMATE_CACHE_TTL_MS = 90 * 1000;
const DETAIL_TOKEN_CACHE_TTL_MS = 5 * 60 * 1000;
const ENDPOINT_TIMING_LOG_THRESHOLD_MS = 1200;

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

function regionPackTileEntryFromRow(row) {
  const parsed = parseTileKey(row && row.tile_key || "");
  if (!parsed) {
    return null;
  }
  const baseGrossCents = Math.max(0, Number.parseInt(row && row.base_gross_cents || 0, 10) || 0);
  const grossCents = applyFullQualityPriceCoefficientCents(baseGrossCents);
  return {
    key: parsed.key,
    tile_key: parsed.key,
    parsed,
    family: String(row && row.family_key || tileFamilyKey(parsed)),
    gross_cents: grossCents,
    base_gross_cents: baseGrossCents,
    globally_free: Boolean(Number(row && row.globally_free || 0) || isFreeCreditTileKey(parsed.key) || grossCents <= 0),
    land_km2: normalizeMetricAmount(row && row.land_km2),
    billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
  };
}

function sortedRegionPackTileEntries(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map(regionPackTileEntryFromRow)
    .filter(Boolean)
    .sort((a, b) => compareRegionTileKeys(a.key, b.key));
}

async function ensureRegionPackTileEntryTable(db, deps) {
  await deps.ensureCreditTables(db);
}

async function regionPackTileRowsForProductFamilies(db, product, familyKeys, deps) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  const families = Array.from(new Set((Array.isArray(familyKeys) ? familyKeys : [])
    .map((family) => String(family || "").trim())
    .filter(Boolean)));
  if (!productId || !families.length) {
    return [];
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const rows = [];
  for (const chunk of fixedSizeChunks(families, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
    rows.push(...await deps.dbAll(
      db,
      `
        SELECT tile_key, family_key, x, y, z, d, base_gross_cents, globally_free
        FROM region_pack_tile_entries
        WHERE catalog_version = ?
          AND region_pack_id = ?
          AND family_key IN (${chunk.map(() => "?").join(",")})
        ORDER BY family_key ASC, d ASC, tile_key ASC
      `,
      [REGION_PACK_CATALOG_VERSION, productId, ...chunk],
    ));
  }
  return sortedRegionPackTileEntries(rows);
}

async function regionPackAllTileRowsForProduct(db, product, deps, options = {}) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  if (!productId) {
    return [];
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const limit = Math.max(1, Math.min(5000, Number.parseInt(options && options.limit || 5000, 10) || 5000));
  let offset = Math.max(0, Number.parseInt(options && options.offset || 0, 10) || 0);
  const rows = [];
  for (;;) {
    const chunk = await deps.dbAll(
      db,
      `
        SELECT tile_key, family_key, x, y, z, d, base_gross_cents, globally_free
        FROM region_pack_tile_entries
        WHERE catalog_version = ?
          AND region_pack_id = ?
        ORDER BY family_key ASC, d ASC, tile_key ASC
        LIMIT ? OFFSET ?
      `,
      [REGION_PACK_CATALOG_VERSION, productId, limit, offset],
    );
    rows.push(...(chunk || []));
    if (!chunk || chunk.length < limit) {
      break;
    }
    offset += limit;
  }
  return sortedRegionPackTileEntries(rows);
}

async function regionPackTileRowsForProductPage(db, product, deps, options = {}) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  if (!productId) {
    return [];
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const limit = Math.max(1, Math.min(5000, Number.parseInt(options && options.limit || 5000, 10) || 5000));
  const offset = Math.max(0, Number.parseInt(options && options.offset || 0, 10) || 0);
  const rows = await deps.dbAll(
    db,
    `
      SELECT tile_key, family_key, x, y, z, d, base_gross_cents, globally_free
      FROM region_pack_tile_entries
      WHERE catalog_version = ?
        AND region_pack_id = ?
      ORDER BY family_key ASC, d ASC, tile_key ASC
      LIMIT ? OFFSET ?
    `,
    [REGION_PACK_CATALOG_VERSION, productId, limit, offset],
  );
  return sortedRegionPackTileEntries(rows || []);
}

async function regionPackTileRowsForProductAfterCursor(db, product, deps, options = {}) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  if (!productId) {
    return [];
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const limit = Math.max(1, Math.min(5000, Number.parseInt(options && options.limit || 5000, 10) || 5000));
  const cursor = options && options.cursor && typeof options.cursor === "object" ? options.cursor : {};
  const familyKey = String(cursor.family_key || "").trim();
  const dValue = Number.parseInt(cursor.d || 0, 10) || 0;
  const tileKey = normalizeTileKey(cursor.tile_key || "");
  const hasCursor = Boolean(familyKey && tileKey);
  const rows = await deps.dbAll(
    db,
    `
      SELECT e.tile_key, e.family_key, e.x, e.y, e.z, e.d,
             e.base_gross_cents, e.globally_free,
             COALESCE(s.land_km2, 0) AS land_km2,
             COALESCE(s.billable_land_km2, 0) AS billable_land_km2
      FROM region_pack_tile_entries e
      LEFT JOIN tile_land_stats s ON s.tile_key = e.tile_key
      WHERE e.catalog_version = ?
        AND e.region_pack_id = ?
        ${hasCursor ? `
          AND (
            e.family_key > ?
            OR (e.family_key = ? AND e.d > ?)
            OR (e.family_key = ? AND e.d = ? AND e.tile_key > ?)
          )
        ` : ""}
      ORDER BY e.family_key ASC, e.d ASC, e.tile_key ASC
      LIMIT ?
    `,
    hasCursor
      ? [REGION_PACK_CATALOG_VERSION, productId, familyKey, familyKey, dValue, familyKey, dValue, tileKey, limit]
      : [REGION_PACK_CATALOG_VERSION, productId, limit],
  );
  return sortedRegionPackTileEntries(rows || []);
}

async function regionPackTileRowsForProductLevelAfterCursor(db, product, level, deps, options = {}) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  const safeLevel = Math.max(1, Number.parseInt(level || 0, 10) || 0);
  if (!productId || !safeLevel) {
    return [];
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const limit = Math.max(1, Math.min(5000, Number.parseInt(options && options.limit || 5000, 10) || 5000));
  const cursor = options && options.cursor && typeof options.cursor === "object" ? options.cursor : {};
  const familyKey = String(cursor.family_key || "").trim();
  const dValue = Number.parseInt(cursor.d || 0, 10) || 0;
  const tileKey = normalizeTileKey(cursor.tile_key || "");
  const hasCursor = Boolean(familyKey && tileKey);
  const rows = await deps.dbAll(
    db,
    `
      SELECT e.tile_key, e.family_key, e.x, e.y, e.z, e.d,
             e.base_gross_cents, e.globally_free,
             COALESCE(s.land_km2, 0) AS land_km2,
             COALESCE(s.billable_land_km2, 0) AS billable_land_km2
      FROM region_pack_tile_entries e
      LEFT JOIN tile_land_stats s ON s.tile_key = e.tile_key
      WHERE e.catalog_version = ?
        AND e.region_pack_id = ?
        AND e.z = ?
        AND e.d = e.z
        ${hasCursor ? `
          AND (
            e.family_key > ?
            OR (e.family_key = ? AND e.d > ?)
            OR (e.family_key = ? AND e.d = ? AND e.tile_key > ?)
          )
        ` : ""}
      ORDER BY e.family_key ASC, e.d ASC, e.tile_key ASC
      LIMIT ?
    `,
    hasCursor
      ? [REGION_PACK_CATALOG_VERSION, productId, safeLevel, familyKey, familyKey, dValue, familyKey, dValue, tileKey, limit]
      : [REGION_PACK_CATALOG_VERSION, productId, safeLevel, limit],
  );
  return sortedRegionPackTileEntries(rows || []);
}

async function regionPackTileLevelCountsForProduct(db, product, deps) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  if (!productId) {
    return {};
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const rows = await deps.dbAll(
    db,
    `
      SELECT z, COUNT(*) AS count
      FROM region_pack_tile_entries
      WHERE catalog_version = ?
        AND region_pack_id = ?
        AND d = z
      GROUP BY z
      ORDER BY z ASC
    `,
    [REGION_PACK_CATALOG_VERSION, productId],
  );
  const counts = {};
  for (const row of rows || []) {
    const z = Number.parseInt(row && row.z || 0, 10);
    const count = Math.max(0, Number.parseInt(row && row.count || 0, 10) || 0);
    if (isRegionPackPaidZLevel(z)) {
      counts[String(z)] = count;
    }
  }
  return counts;
}

async function regionPackProductContainsTileKey(db, product, tileKey, deps) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  const key = normalizeTileKey(tileKey);
  if (!productId || !key) {
    return false;
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const row = await deps.dbGet(
    db,
    `
      SELECT 1 AS ok
      FROM region_pack_tile_entries
      WHERE catalog_version = ?
        AND region_pack_id = ?
        AND tile_key = ?
      LIMIT 1
    `,
    [REGION_PACK_CATALOG_VERSION, productId, key],
  );
  return Boolean(row && row.ok);
}

async function regionPackProductZ001CellSet(db, product, deps) {
  const productId = String(product && product.id || product || "").trim().toLowerCase();
  if (!productId) {
    return new Set();
  }
  const cacheKey = `${REGION_PACK_CATALOG_VERSION}|${productId}`;
  if (REGION_PRODUCT_Z001_CELL_CACHE.has(cacheKey)) {
    return REGION_PRODUCT_Z001_CELL_CACHE.get(cacheKey);
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const rows = await deps.dbAll(
    db,
    `
      SELECT x, y
      FROM region_pack_tile_entries
      WHERE catalog_version = ?
        AND region_pack_id = ?
        AND z = 1
        AND d = 1
    `,
    [REGION_PACK_CATALOG_VERSION, productId],
  );
  const cells = new Set((rows || []).map((row) => `${Number(row && row.x)},${Number(row && row.y)}`));
  boundedCacheSet(REGION_PRODUCT_Z001_CELL_CACHE, cacheKey, cells, 256);
  return cells;
}

async function regionProductsShareZ001Footprint(db, productA, productB, deps) {
  const cellsA = await regionPackProductZ001CellSet(db, productA, deps);
  const cellsB = await regionPackProductZ001CellSet(db, productB, deps);
  if (!cellsA.size || !cellsB.size) {
    return false;
  }
  const smaller = cellsA.size <= cellsB.size ? cellsA : cellsB;
  const larger = cellsA.size <= cellsB.size ? cellsB : cellsA;
  for (const cell of smaller) {
    if (larger.has(cell)) {
      return true;
    }
  }
  return false;
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

function integerCents(value) {
  const parsed = Number.parseInt(value || 0, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return parsed;
}

function centsToEur(cents) {
  return normalizeCreditAmount(integerCents(cents) / MONEY_SCALE);
}

function centsFromField(source, centsKey, eurKey) {
  if (source && Object.prototype.hasOwnProperty.call(source, centsKey)) {
    return integerCents(source[centsKey]);
  }
  return centsForEur(source && source[eurKey]);
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

function roundForCache(value, decimals = 3) {
  const scale = 10 ** Math.max(0, Math.min(8, Number.parseInt(decimals || 0, 10) || 0));
  return Math.round((Number(value) || 0) * scale) / scale;
}

async function sha1Hex(value, length = 16) {
  const text = String(value || "");
  try {
    const bytes = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest("SHA-1", bytes);
    const hex = Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
    return hex.slice(0, Math.max(1, Number.parseInt(length || 16, 10) || 16));
  } catch (_error) {
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, "0").slice(0, Math.max(1, Number.parseInt(length || 16, 10) || 16));
  }
}

function monotonicNowMs() {
  try {
    if (typeof performance !== "undefined" && typeof performance.now === "function") {
      return performance.now();
    }
  } catch (_error) {
    // Fall back below.
  }
  return Date.now();
}

function boundedCacheSet(cache, key, value, maxEntries) {
  if (!cache || typeof cache.set !== "function" || !key) {
    return;
  }
  if (cache.has(key)) {
    cache.delete(key);
  }
  cache.set(key, value);
  const limit = Math.max(1, Number.parseInt(maxEntries || 0, 10) || 1);
  while (cache.size > limit) {
    const firstKey = cache.keys().next().value;
    if (firstKey === undefined) {
      break;
    }
    cache.delete(firstKey);
  }
}

function deleteCacheEntriesByPrefix(cache, prefix) {
  const safePrefix = String(prefix || "");
  if (!safePrefix || !cache || typeof cache.keys !== "function") {
    return;
  }
  for (const key of Array.from(cache.keys())) {
    if (String(key || "").startsWith(safePrefix)) {
      cache.delete(key);
    }
  }
}

function invalidateUserPricingCaches(userId) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return;
  }
  deleteCacheEntriesByPrefix(USER_CREDIT_ACCOUNT_CACHE, `${safeUserId}|`);
  deleteCacheEntriesByPrefix(USER_ENTITLEMENT_SUMMARY_CACHE, `${safeUserId}|`);
  deleteCacheEntriesByPrefix(REGION_OFFERS_RESPONSE_CACHE, `${safeUserId}|`);
  deleteCacheEntriesByPrefix(REGION_PACK_ESTIMATE_CACHE, `${safeUserId}|`);
}

function isDefaultProductQuoteUserId(userId) {
  const safeUserId = String(userId || "").trim();
  return safeUserId === DEFAULT_NO_PURCHASE_QUOTE_USER_ID
    || safeUserId === DEFAULT_BETA_FULL_WORLD_QUOTE_USER_ID;
}

function accountPricingVersionNumber(account) {
  return Math.max(0, Number.parseInt(account && account.pricing_version || 0, 10) || 0);
}

function hasExplicitWorldFullQualityUnlock(account) {
  return Boolean(String(account && account.world_full_quality_unlocked_at || "").trim());
}

function accountUsesDefaultProductQuotes(account) {
  const userId = String(account && account.user_id || account && account.id || "").trim();
  if (isDefaultProductQuoteUserId(userId)) {
    return true;
  }
  return accountPricingVersionNumber(account) === 0
    && !hasExplicitWorldFullQualityUnlock(account);
}

function defaultProductQuoteUserIdForAccount(account) {
  if (!accountUsesDefaultProductQuotes(account)) {
    return "";
  }
  return isWorldFullQualityUnlocked(account)
    ? DEFAULT_BETA_FULL_WORLD_QUOTE_USER_ID
    : DEFAULT_NO_PURCHASE_QUOTE_USER_ID;
}

function productQuoteLookupUserIdForAccount(userId, account) {
  const defaultUserId = defaultProductQuoteUserIdForAccount(account);
  return defaultUserId || String(userId || "").trim();
}

function accountEntitlementVersion(account) {
  const userId = String(account && account.user_id || account && account.id || "").trim();
  if (userId === DEFAULT_NO_PURCHASE_QUOTE_USER_ID) {
    return DEFAULT_NO_PURCHASE_ENTITLEMENT_VERSION;
  }
  if (userId === DEFAULT_BETA_FULL_WORLD_QUOTE_USER_ID) {
    return DEFAULT_BETA_FULL_WORLD_ENTITLEMENT_VERSION;
  }
  if (accountUsesDefaultProductQuotes(account)) {
    return isWorldFullQualityUnlocked(account)
      ? DEFAULT_BETA_FULL_WORLD_ENTITLEMENT_VERSION
      : DEFAULT_NO_PURCHASE_ENTITLEMENT_VERSION;
  }
  return [
    BETA_FULL_WORLD_ACCESS_ENABLED ? "beta_full_world_access" : "",
    String(account && (account.user_email || account.email) || "").trim().toLowerCase(),
    String((account && account.pricing_version) ?? ""),
    String(account && account.updated_at || ""),
    String(account && account.world_full_quality_unlocked_at || ""),
  ].join("|");
}

function cloneCreditAccount(account) {
  return account && typeof account === "object" ? { ...account } : null;
}

function cachedCreditAccount(userId) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  const prefix = `${safeUserId}|`;
  const nowMs = monotonicNowMs();
  for (const [key, entry] of USER_CREDIT_ACCOUNT_CACHE.entries()) {
    if (!String(key || "").startsWith(prefix)) {
      continue;
    }
    if ((nowMs - Number(entry && entry.cached_at_ms || 0)) <= USER_CREDIT_ACCOUNT_CACHE_TTL_MS) {
      return cloneCreditAccount(entry.account);
    }
    USER_CREDIT_ACCOUNT_CACHE.delete(key);
  }
  return null;
}

function cacheCreditAccount(account) {
  const safeUserId = String(account && account.user_id || "").trim();
  if (!safeUserId) {
    return;
  }
  const key = `${safeUserId}|${accountEntitlementVersion(account)}`;
  boundedCacheSet(
    USER_CREDIT_ACCOUNT_CACHE,
    key,
    { account: cloneCreditAccount(account), cached_at_ms: monotonicNowMs() },
    USER_CREDIT_ACCOUNT_CACHE_MAX,
  );
}

function detailTokenCacheKey(kind, token) {
  return `${String(kind || "").trim()}|${String(token || "").trim()}`;
}

function cachedDetailToken(kind, token, deps) {
  const key = detailTokenCacheKey(kind, token);
  if (!key || key.endsWith("|")) {
    return null;
  }
  const entry = DETAIL_TOKEN_CACHE.get(key);
  if (!entry || (monotonicNowMs() - Number(entry.cached_at_ms || 0)) > DETAIL_TOKEN_CACHE_TTL_MS) {
    DETAIL_TOKEN_CACHE.delete(key);
    return null;
  }
  const now = String(deps && deps.nowIso && deps.nowIso() || new Date().toISOString());
  if (String(entry.row && entry.row.expires_at || "") <= now) {
    DETAIL_TOKEN_CACHE.delete(key);
    return null;
  }
  return { ...entry.row };
}

function cacheDetailToken(kind, token, row) {
  const key = detailTokenCacheKey(kind, token);
  if (!key || key.endsWith("|") || !row) {
    return;
  }
  boundedCacheSet(
    DETAIL_TOKEN_CACHE,
    key,
    { row: { ...row }, cached_at_ms: monotonicNowMs() },
    DETAIL_TOKEN_CACHE_MAX,
  );
}

function createEndpointTimer(route) {
  const started = monotonicNowMs();
  let last = started;
  const steps = [];
  return {
    route: String(route || "unknown"),
    mark(name) {
      const now = monotonicNowMs();
      steps.push({ name: String(name || "step"), dur: Math.max(0, now - last) });
      last = now;
    },
    finish(extra = {}) {
      const total = Math.max(0, monotonicNowMs() - started);
      return {
        route: String(route || "unknown"),
        total_ms: total,
        steps,
        extra: extra && typeof extra === "object" ? extra : {},
      };
    },
  };
}

function withEndpointTiming(response, timing, env, extra = {}) {
  if (!(response instanceof Response) || !timing || typeof timing.finish !== "function") {
    return response;
  }
  const result = timing.finish({ ...extra, status: response.status });
  const headers = new Headers(response.headers);
  const serverTiming = [
    `total;dur=${result.total_ms.toFixed(1)}`,
    ...result.steps.map((step) => `${String(step.name || "step").replace(/[^a-zA-Z0-9_-]/g, "_")};dur=${Number(step.dur || 0).toFixed(1)}`),
  ].slice(0, 16).join(", ");
  headers.set("Server-Timing", serverTiming);
  headers.set("X-Planetka-Endpoint", result.route);
  headers.set("X-Planetka-Worker-Ms", result.total_ms.toFixed(1));
  try {
    const threshold = Math.max(0, Number.parseFloat(env && env.ENDPOINT_TIMING_LOG_THRESHOLD_MS || ENDPOINT_TIMING_LOG_THRESHOLD_MS) || ENDPOINT_TIMING_LOG_THRESHOLD_MS);
    if (result.total_ms >= threshold || Number(response.status || 0) >= 500) {
      console.log(JSON.stringify({
        event: "planetka_endpoint_timing",
        route: result.route,
        total_ms: Math.round(result.total_ms * 10) / 10,
        status: response.status,
        steps: result.steps.map((step) => ({
          name: step.name,
          ms: Math.round(Number(step.dur || 0) * 10) / 10,
        })),
        ...result.extra,
      }));
    }
  } catch (_error) {
    // Telemetry must never affect the response path.
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function regionProductById(regionId) {
  const safeId = String(regionId || "").trim().toLowerCase();
  if (!safeId) {
    return null;
  }
  return REGION_PRODUCT_BY_ID.get(safeId) || null;
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
  const bbox = Array.isArray(product.bbox) ? product.bbox.map((value) => Number(value)) : [];
  const bounds = bbox.length >= 4 && bbox.every((value) => Number.isFinite(value))
    ? { min_lon: bbox[0], min_lat: bbox[1], max_lon: bbox[2], max_lat: bbox[3] }
    : null;
  return {
    id: String(product.id || ""),
    name: String(product.name || ""),
    type: String(product.type || ""),
    discount_percent: regionProductDiscountPercent(product),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    included_countries: regionProductIncludedCountries(product),
    bounds,
  };
}

function regionProductPricingSummary(product) {
  if (!product || typeof product !== "object") {
    return null;
  }
  const productId = String(product.id || "").trim();
  const cacheKey = `${productId || "anon"}|${fullQualityPriceCoefficient().toFixed(6)}`;
  let grossCents = REGION_PRODUCT_GROSS_CENTS_CACHE.get(cacheKey);
  if (!Number.isFinite(grossCents)) {
    // Generated product metadata stores the coefficient-1.0 integer-cent gross
    // sum. Runtime coefficient changes are applied here; user-specific
    // deductions are read from D1 region_pack_tile_entries, not the generated
    // tile-data module.
    grossCents = applyFullQualityPriceCoefficientCents(product.gross_cents || centsForEur(product.gross_eur || 0));
    REGION_PRODUCT_GROSS_CENTS_CACHE.set(cacheKey, grossCents);
  }
  const grossEur = centsToEur(grossCents);
  return {
    gross_cents: grossCents,
    gross_eur: grossEur,
    paid_tile_count: Math.max(0, Number.parseInt(product.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(product.free_tile_count || 0, 10) || 0),
    licensable_tile_count: Math.max(0, Number.parseInt(product.licensable_tile_count || 0, 10) || 0),
    tile_count: Math.max(0, Number.parseInt(product.tile_count || 0, 10) || 0),
  };
}

async function regionProductPricingSummaryD1(db, product, deps) {
  if (!product || typeof product !== "object") {
    return null;
  }
  const productId = String(product.id || "").trim().toLowerCase();
  if (!productId) {
    return regionProductPricingSummary(product);
  }
  const cacheKey = [
    REGION_PACK_CATALOG_VERSION,
    productId,
    fullQualityPriceCoefficient().toFixed(6),
  ].join("|");
  const cached = REGION_PRODUCT_PRICING_SUMMARY_CACHE.get(cacheKey);
  if (cached) {
    return { ...cached };
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const row = await deps.dbGet(
    db,
    `
      SELECT
        COALESCE(SUM(CAST(ROUND(base_gross_cents * ?) AS INTEGER)), 0) AS gross_cents,
        COUNT(*) AS tile_count,
        COALESCE(SUM(CASE WHEN globally_free = 0 AND CAST(ROUND(base_gross_cents * ?) AS INTEGER) > 0 THEN 1 ELSE 0 END), 0) AS paid_tile_count,
        COALESCE(SUM(CASE WHEN globally_free != 0 OR CAST(ROUND(base_gross_cents * ?) AS INTEGER) <= 0 THEN 1 ELSE 0 END), 0) AS free_tile_count
      FROM region_pack_tile_entries
      WHERE catalog_version = ?
        AND region_pack_id = ?
    `,
    [
      fullQualityPriceCoefficient(),
      fullQualityPriceCoefficient(),
      fullQualityPriceCoefficient(),
      REGION_PACK_CATALOG_VERSION,
      productId,
    ],
  );
  const tileCount = Math.max(0, Number.parseInt(row && row.tile_count || 0, 10) || 0);
  if (!tileCount) {
    return regionProductPricingSummary(product);
  }
  const summary = {
    gross_cents: Math.max(0, Number.parseInt(row && row.gross_cents || 0, 10) || 0),
    gross_eur: centsToEur(row && row.gross_cents),
    paid_tile_count: Math.max(0, Number.parseInt(row && row.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(row && row.free_tile_count || 0, 10) || 0),
    licensable_tile_count: tileCount,
    tile_count: tileCount,
  };
  boundedCacheSet(REGION_PRODUCT_PRICING_SUMMARY_CACHE, cacheKey, summary, 512);
  return { ...summary };
}

function normalizedRegionPackProductId(productOrId) {
  return String(productOrId && productOrId.id || productOrId || "").trim().toLowerCase();
}

function regionPackRelationCacheKey(targetId, ownedId) {
  const target = normalizedRegionPackProductId(targetId);
  const owned = normalizedRegionPackProductId(ownedId);
  return target && owned ? `${REGION_PACK_CATALOG_VERSION}|${target}|${owned}` : "";
}

function normalizedRegionPackRelationRow(row) {
  if (!row || typeof row !== "object") {
    return null;
  }
  const targetId = normalizedRegionPackProductId(row.target_region_pack_id);
  const ownedId = normalizedRegionPackProductId(row.owned_region_pack_id);
  if (!targetId || !ownedId) {
    return null;
  }
  return {
    catalog_version: String(row.catalog_version || REGION_PACK_CATALOG_VERSION),
    target_region_pack_id: targetId,
    owned_region_pack_id: ownedId,
    relation_type: String(row.relation_type || "exclusive").trim().toLowerCase() || "exclusive",
    target_tile_count: Math.max(0, Number.parseInt(row.target_tile_count || 0, 10) || 0),
    owned_tile_count: Math.max(0, Number.parseInt(row.owned_tile_count || 0, 10) || 0),
    overlap_tile_count: Math.max(0, Number.parseInt(row.overlap_tile_count || 0, 10) || 0),
    overlap_paid_tile_count: Math.max(0, Number.parseInt(row.overlap_paid_tile_count || 0, 10) || 0),
    overlap_free_tile_count: Math.max(0, Number.parseInt(row.overlap_free_tile_count || 0, 10) || 0),
    overlap_base_gross_cents: Math.max(0, Number.parseInt(row.overlap_base_gross_cents || 0, 10) || 0),
    target_base_gross_cents: Math.max(0, Number.parseInt(row.target_base_gross_cents || 0, 10) || 0),
    owned_base_gross_cents: Math.max(0, Number.parseInt(row.owned_base_gross_cents || 0, 10) || 0),
    computed_at: String(row.computed_at || ""),
  };
}

function relationTypeFromOverlapCounts(targetId, ownedId, targetTileCount, ownedTileCount, overlapTileCount) {
  const target = normalizedRegionPackProductId(targetId);
  const owned = normalizedRegionPackProductId(ownedId);
  const targetCount = Math.max(0, Number.parseInt(targetTileCount || 0, 10) || 0);
  const ownedCount = Math.max(0, Number.parseInt(ownedTileCount || 0, 10) || 0);
  const overlapCount = Math.max(0, Number.parseInt(overlapTileCount || 0, 10) || 0);
  if (!target || !owned || overlapCount <= 0) {
    return "exclusive";
  }
  if (target === owned) {
    return "self";
  }
  if (targetCount > 0 && overlapCount >= targetCount) {
    return "parent_covers_target";
  }
  if (ownedCount > 0 && overlapCount >= ownedCount) {
    return "owned_child_of_target";
  }
  return "overlap";
}

function regionPackRelationCoversTarget(relation) {
  const type = String(relation && relation.relation_type || "").trim().toLowerCase();
  return type === "self" || type === "parent_covers_target";
}

function regionPackRelationHasOverlap(relation) {
  if (!relation) {
    return false;
  }
  if (regionPackRelationCoversTarget(relation)) {
    return true;
  }
  return Math.max(0, Number.parseInt(relation.overlap_tile_count || 0, 10) || 0) > 0
    && String(relation.relation_type || "").trim().toLowerCase() !== "exclusive";
}

function syntheticRegionPackRelation(targetProduct, ownedProduct, relationType = "") {
  const targetId = normalizedRegionPackProductId(targetProduct);
  const ownedId = normalizedRegionPackProductId(ownedProduct);
  if (!targetId || !ownedId) {
    return null;
  }
  const targetSummary = regionProductPricingSummary(targetProduct) || {};
  const ownedSummary = regionProductPricingSummary(ownedProduct) || {};
  const targetTileCount = Math.max(0, Number.parseInt(targetSummary.tile_count || 0, 10) || 0);
  const ownedTileCount = Math.max(0, Number.parseInt(ownedSummary.tile_count || 0, 10) || 0);
  const overlapTileCount = relationType === "parent_covers_target" || relationType === "self"
    ? targetTileCount
    : ownedTileCount;
  return normalizedRegionPackRelationRow({
    catalog_version: REGION_PACK_CATALOG_VERSION,
    target_region_pack_id: targetId,
    owned_region_pack_id: ownedId,
    relation_type: relationType || relationTypeFromOverlapCounts(targetId, ownedId, targetTileCount, ownedTileCount, overlapTileCount),
    target_tile_count: targetTileCount,
    owned_tile_count: ownedTileCount,
    overlap_tile_count: overlapTileCount,
    overlap_paid_tile_count: relationType === "parent_covers_target" || relationType === "self"
      ? Math.max(0, Number.parseInt(targetSummary.paid_tile_count || 0, 10) || 0)
      : Math.max(0, Number.parseInt(ownedSummary.paid_tile_count || 0, 10) || 0),
    overlap_free_tile_count: relationType === "parent_covers_target" || relationType === "self"
      ? Math.max(0, Number.parseInt(targetSummary.free_tile_count || 0, 10) || 0)
      : Math.max(0, Number.parseInt(ownedSummary.free_tile_count || 0, 10) || 0),
    overlap_base_gross_cents: relationType === "parent_covers_target" || relationType === "self"
      ? Math.max(0, Number.parseInt(targetProduct && targetProduct.gross_cents || 0, 10) || 0)
      : Math.max(0, Number.parseInt(ownedProduct && ownedProduct.gross_cents || 0, 10) || 0),
    target_base_gross_cents: Math.max(0, Number.parseInt(targetProduct && targetProduct.gross_cents || 0, 10) || 0),
    owned_base_gross_cents: Math.max(0, Number.parseInt(ownedProduct && ownedProduct.gross_cents || 0, 10) || 0),
    computed_at: "",
  });
}

function staticRegionPackRelationForPair(targetProduct, ownedProduct) {
  if (!REGION_PACK_STATIC_RELATION_GRAPH_READY) {
    return null;
  }
  const targetId = normalizedRegionPackProductId(targetProduct);
  const ownedId = normalizedRegionPackProductId(ownedProduct);
  if (!targetId || !ownedId) {
    return null;
  }
  if (targetId === ownedId) {
    return syntheticRegionPackRelation(targetProduct, ownedProduct, "self");
  }
  const targetRows = Array.isArray(GENERATED_REGION_PACK_RELATIONS_BY_TARGET[targetId])
    ? GENERATED_REGION_PACK_RELATIONS_BY_TARGET[targetId]
    : [];
  const row = targetRows.find((entry) => Array.isArray(entry) && String(entry[0] || "").trim().toLowerCase() === ownedId);
  if (row) {
    return normalizedRegionPackRelationRow({
      catalog_version: REGION_PACK_CATALOG_VERSION,
      target_region_pack_id: targetId,
      owned_region_pack_id: ownedId,
      relation_type: row[1],
      overlap_tile_count: row[2],
      overlap_paid_tile_count: row[3],
      overlap_free_tile_count: row[4],
      overlap_base_gross_cents: row[5],
      target_tile_count: row[6],
      owned_tile_count: row[7],
      target_base_gross_cents: row[8],
      owned_base_gross_cents: row[9],
      computed_at: "",
    });
  }
  const targetSummary = regionProductPricingSummary(targetProduct) || {};
  const ownedSummary = regionProductPricingSummary(ownedProduct) || {};
  return normalizedRegionPackRelationRow({
    catalog_version: REGION_PACK_CATALOG_VERSION,
    target_region_pack_id: targetId,
    owned_region_pack_id: ownedId,
    relation_type: "exclusive",
    target_tile_count: targetSummary.tile_count,
    owned_tile_count: ownedSummary.tile_count,
    overlap_tile_count: 0,
    overlap_paid_tile_count: 0,
    overlap_free_tile_count: 0,
    overlap_base_gross_cents: 0,
    target_base_gross_cents: targetProduct && targetProduct.gross_cents,
    owned_base_gross_cents: ownedProduct && ownedProduct.gross_cents,
    computed_at: "",
  });
}

async function computeRegionPackRelation(db, targetProduct, ownedProduct, deps) {
  const targetId = normalizedRegionPackProductId(targetProduct);
  const ownedId = normalizedRegionPackProductId(ownedProduct);
  if (!targetId || !ownedId) {
    return null;
  }
  const targetSummary = await regionProductPricingSummaryD1(db, targetProduct, deps);
  const ownedSummary = await regionProductPricingSummaryD1(db, ownedProduct, deps);
  const targetTileCount = Math.max(0, Number.parseInt(targetSummary && targetSummary.tile_count || 0, 10) || 0);
  const ownedTileCount = Math.max(0, Number.parseInt(ownedSummary && ownedSummary.tile_count || 0, 10) || 0);
  let overlapTileCount = 0;
  let overlapPaidTileCount = 0;
  let overlapFreeTileCount = 0;
  let overlapBaseGrossCents = 0;
  if (targetId === ownedId) {
    overlapTileCount = targetTileCount;
    overlapPaidTileCount = Math.max(0, Number.parseInt(targetSummary && targetSummary.paid_tile_count || 0, 10) || 0);
    overlapFreeTileCount = Math.max(0, Number.parseInt(targetSummary && targetSummary.free_tile_count || 0, 10) || 0);
    overlapBaseGrossCents = Math.max(0, Number.parseInt(targetProduct && targetProduct.gross_cents || 0, 10) || 0);
  } else {
    const row = await deps.dbGet(
      db,
      `
        SELECT
          COUNT(*) AS overlap_tile_count,
          COALESCE(SUM(CASE WHEN t.globally_free = 0 AND t.base_gross_cents > 0 THEN 1 ELSE 0 END), 0) AS overlap_paid_tile_count,
          COALESCE(SUM(CASE WHEN t.globally_free != 0 OR t.base_gross_cents <= 0 THEN 1 ELSE 0 END), 0) AS overlap_free_tile_count,
          COALESCE(SUM(t.base_gross_cents), 0) AS overlap_base_gross_cents
        FROM region_pack_tile_entries AS t
        INNER JOIN region_pack_tile_entries AS o
          ON o.catalog_version = t.catalog_version
         AND o.tile_key = t.tile_key
        WHERE t.catalog_version = ?
          AND t.region_pack_id = ?
          AND o.region_pack_id = ?
      `,
      [REGION_PACK_CATALOG_VERSION, targetId, ownedId],
    );
    overlapTileCount = Math.max(0, Number.parseInt(row && row.overlap_tile_count || 0, 10) || 0);
    overlapPaidTileCount = Math.max(0, Number.parseInt(row && row.overlap_paid_tile_count || 0, 10) || 0);
    overlapFreeTileCount = Math.max(0, Number.parseInt(row && row.overlap_free_tile_count || 0, 10) || 0);
    overlapBaseGrossCents = Math.max(0, Number.parseInt(row && row.overlap_base_gross_cents || 0, 10) || 0);
  }
  return normalizedRegionPackRelationRow({
    catalog_version: REGION_PACK_CATALOG_VERSION,
    target_region_pack_id: targetId,
    owned_region_pack_id: ownedId,
    relation_type: relationTypeFromOverlapCounts(targetId, ownedId, targetTileCount, ownedTileCount, overlapTileCount),
    target_tile_count: targetTileCount,
    owned_tile_count: ownedTileCount,
    overlap_tile_count: overlapTileCount,
    overlap_paid_tile_count: overlapPaidTileCount,
    overlap_free_tile_count: overlapFreeTileCount,
    overlap_base_gross_cents: overlapBaseGrossCents,
    target_base_gross_cents: Math.max(0, Number.parseInt(targetProduct && targetProduct.gross_cents || 0, 10) || 0),
    owned_base_gross_cents: Math.max(0, Number.parseInt(ownedProduct && ownedProduct.gross_cents || 0, 10) || 0),
    computed_at: deps.nowIso(),
  });
}

async function regionPackRelationForPair(db, targetProduct, ownedProduct, deps) {
  const targetId = normalizedRegionPackProductId(targetProduct);
  const ownedId = normalizedRegionPackProductId(ownedProduct);
  const cacheKey = regionPackRelationCacheKey(targetId, ownedId);
  if (!targetId || !ownedId || !cacheKey) {
    return null;
  }
  if (targetId === ownedId) {
    return syntheticRegionPackRelation(targetProduct, ownedProduct, "self");
  }
  const cached = REGION_PACK_RELATION_CACHE.get(cacheKey);
  if (cached) {
    return { ...cached };
  }
  const staticRelation = staticRegionPackRelationForPair(targetProduct, ownedProduct);
  if (staticRelation) {
    boundedCacheSet(REGION_PACK_RELATION_CACHE, cacheKey, staticRelation, REGION_PACK_RELATION_CACHE_MAX);
    return { ...staticRelation };
  }
  await deps.ensureCreditTables(db);
  const existing = normalizedRegionPackRelationRow(await deps.dbGet(
    db,
    `
      SELECT *
      FROM region_pack_relations
      WHERE catalog_version = ?
        AND target_region_pack_id = ?
        AND owned_region_pack_id = ?
      LIMIT 1
    `,
    [REGION_PACK_CATALOG_VERSION, targetId, ownedId],
  ));
  if (existing) {
    boundedCacheSet(REGION_PACK_RELATION_CACHE, cacheKey, existing, REGION_PACK_RELATION_CACHE_MAX);
    return { ...existing };
  }
  const relation = await computeRegionPackRelation(db, targetProduct, ownedProduct, deps);
  if (!relation) {
    return null;
  }
  await deps.dbRun(
    db,
    `
      INSERT OR REPLACE INTO region_pack_relations (
        catalog_version,
        target_region_pack_id,
        owned_region_pack_id,
        relation_type,
        target_tile_count,
        owned_tile_count,
        overlap_tile_count,
        overlap_paid_tile_count,
        overlap_free_tile_count,
        overlap_base_gross_cents,
        target_base_gross_cents,
        owned_base_gross_cents,
        computed_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      relation.catalog_version,
      relation.target_region_pack_id,
      relation.owned_region_pack_id,
      relation.relation_type,
      relation.target_tile_count,
      relation.owned_tile_count,
      relation.overlap_tile_count,
      relation.overlap_paid_tile_count,
      relation.overlap_free_tile_count,
      relation.overlap_base_gross_cents,
      relation.target_base_gross_cents,
      relation.owned_base_gross_cents,
      relation.computed_at,
    ],
  );
  boundedCacheSet(REGION_PACK_RELATION_CACHE, cacheKey, relation, REGION_PACK_RELATION_CACHE_MAX);
  return { ...relation };
}

async function purchasedRegionPackIdsForUser(db, userId, deps) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return [];
  }
  await deps.ensureCreditTables(db);
  const rows = await deps.dbAll(
    db,
    `
      SELECT DISTINCT LOWER(TRIM(region_pack_id)) AS region_pack_id
      FROM purchase_history
      WHERE user_id = ?
        AND LOWER(TRIM(purchase_type)) = 'region_pack'
        AND catalog_version = ?
        AND region_pack_id IS NOT NULL
        AND TRIM(region_pack_id) != ''
    `,
    [safeUserId, REGION_PACK_CATALOG_VERSION],
  );
  return Array.from(new Set((rows || [])
    .map((row) => normalizedRegionPackProductId(row && row.region_pack_id))
    .filter((id) => id && regionProductById(id))));
}

async function purchasedSceneTileRowsForUser(db, userId, deps) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return [];
  }
  await deps.ensureCreditTables(db);
  const rows = await deps.dbAll(
    db,
    `
      SELECT
        pht.tile_key AS tile_key,
        MAX(CAST(ROUND(COALESCE(NULLIF(pht.gross_price_eur, 0), pht.price_eur, 0) * 100.0) AS INTEGER)) AS value_cents
      FROM purchase_history AS ph
      INNER JOIN purchase_history_tiles AS pht
        ON pht.purchase_id = ph.id
      WHERE ph.user_id = ?
        AND LOWER(TRIM(ph.purchase_type)) IN ('scene_tiles', 'animation_tiles')
        AND pht.tile_key IS NOT NULL
        AND TRIM(pht.tile_key) != ''
      GROUP BY pht.tile_key
    `,
    [safeUserId],
  );
  return (rows || [])
    .map((row) => {
      const key = normalizeTileKey(row && row.tile_key || "");
      const parsed = parseTileKey(key);
      const family = tileFamilyKey(parsed);
      if (!key || !parsed || !family) {
        return null;
      }
      return {
        tile_key: key,
        key,
        family,
        d: Number(parsed.d),
        value_cents: integerCents(row && row.value_cents),
      };
    })
    .filter(Boolean);
}

function ownedByFamilyFromSceneTileRows(rows) {
  const ownedByFamily = new Map();
  for (const row of rows || []) {
    const key = normalizeTileKey(row && (row.key || row.tile_key) || "");
    const parsed = parseTileKey(key);
    const family = String(row && row.family || tileFamilyKey(parsed) || "");
    if (!key || !parsed || !family) {
      continue;
    }
    if (!ownedByFamily.has(family)) {
      ownedByFamily.set(family, []);
    }
    ownedByFamily.get(family).push({
      key,
      d: Number(parsed.d),
      value_cents: integerCents(row && row.value_cents),
    });
  }
  return ownedByFamily;
}

async function regionPackPricingOwnershipContext(db, userId, account, deps, options = {}) {
  if (options && options.pricingOwnershipContext) {
    return options.pricingOwnershipContext;
  }
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return {
      userId: "",
      purchasedPackIds: [],
      purchasedPackIdSet: new Set(),
      sceneTileRows: [],
      sceneOwnedByFamily: new Map(),
      hasPurchaseHistoryFacts: false,
    };
  }
  const purchasedPackIds = await purchasedRegionPackIdsForUser(db, safeUserId, deps);
  const purchasedPackIdSet = new Set(purchasedPackIds);
  const sceneTileRows = await purchasedSceneTileRowsForUser(db, safeUserId, deps);
  return {
    userId: safeUserId,
    purchasedPackIds,
    purchasedPackIdSet,
    sceneTileRows,
    sceneOwnedByFamily: ownedByFamilyFromSceneTileRows(sceneTileRows),
    hasPurchaseHistoryFacts: purchasedPackIds.length > 0 || sceneTileRows.length > 0,
    world_full_quality_unlocked: isWorldFullQualityUnlocked(account),
  };
}

async function relevantPurchasedPackRelations(db, targetProduct, purchasedPackIds, deps) {
  const targetId = normalizedRegionPackProductId(targetProduct);
  const relations = [];
  if (!targetId || !Array.isArray(purchasedPackIds) || !purchasedPackIds.length) {
    return relations;
  }
  for (const ownedId of purchasedPackIds) {
    const ownedProduct = regionProductById(ownedId);
    if (!ownedProduct || isHiddenRegionProduct(ownedProduct)) {
      continue;
    }
    const relation = await regionPackRelationForPair(db, targetProduct, ownedProduct, deps);
    if (regionPackRelationHasOverlap(relation)) {
      relations.push(relation);
    }
  }
  return relations;
}

async function packCoverageAggregateForTarget(db, targetProduct, ownedPackIds, deps) {
  const targetId = normalizedRegionPackProductId(targetProduct);
  const ids = Array.from(new Set((Array.isArray(ownedPackIds) ? ownedPackIds : [])
    .map(normalizedRegionPackProductId)
    .filter((id) => id && id !== targetId && regionProductById(id))));
  if (!targetId || !ids.length) {
    return {
      tile_count: 0,
      paid_tile_count: 0,
      free_tile_count: 0,
      base_gross_cents: 0,
      gross_cents: 0,
    };
  }
  await ensureRegionPackTileEntryTable(db, deps);
  if (ids.length > SQL_VARIABLE_SAFE_CHUNK_SIZE) {
    const byTileKey = new Map();
    for (const chunk of fixedSizeChunks(ids, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
      const rows = await deps.dbAll(
        db,
        `
          SELECT DISTINCT
            t.tile_key,
            t.base_gross_cents,
            t.globally_free
          FROM region_pack_tile_entries AS owned
          INNER JOIN region_pack_tile_entries AS t
            ON t.catalog_version = owned.catalog_version
           AND t.tile_key = owned.tile_key
          WHERE owned.catalog_version = ?
            AND owned.region_pack_id IN (${chunk.map(() => "?").join(",")})
            AND t.region_pack_id = ?
        `,
        [REGION_PACK_CATALOG_VERSION, ...chunk, targetId],
      );
      for (const row of rows || []) {
        const key = normalizeTileKey(row && row.tile_key || "");
        if (key && !byTileKey.has(key)) {
          byTileKey.set(key, row);
        }
      }
    }
    let paidTileCount = 0;
    let freeTileCount = 0;
    let baseGrossCents = 0;
    let grossCents = 0;
    for (const row of byTileKey.values()) {
      const baseCents = Math.max(0, Number.parseInt(row && row.base_gross_cents || 0, 10) || 0);
      const runtimeCents = applyFullQualityPriceCoefficientCents(baseCents);
      const globallyFree = Boolean(Number(row && row.globally_free || 0) || runtimeCents <= 0);
      if (globallyFree) {
        freeTileCount += 1;
      } else {
        paidTileCount += 1;
      }
      baseGrossCents += baseCents;
      grossCents += runtimeCents;
    }
    return {
      tile_count: byTileKey.size,
      paid_tile_count: paidTileCount,
      free_tile_count: freeTileCount,
      base_gross_cents: baseGrossCents,
      gross_cents: grossCents,
    };
  }
  let tileCount = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;
  let baseGrossCents = 0;
  let grossCents = 0;
  for (const chunk of fixedSizeChunks(ids, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
    const row = await deps.dbGet(
      db,
      `
        SELECT
          COUNT(*) AS tile_count,
          COALESCE(SUM(CASE WHEN globally_free = 0 AND gross_cents > 0 THEN 1 ELSE 0 END), 0) AS paid_tile_count,
          COALESCE(SUM(CASE WHEN globally_free != 0 OR gross_cents <= 0 THEN 1 ELSE 0 END), 0) AS free_tile_count,
          COALESCE(SUM(base_gross_cents), 0) AS base_gross_cents,
          COALESCE(SUM(gross_cents), 0) AS gross_cents
        FROM (
          SELECT DISTINCT
            t.tile_key,
            t.base_gross_cents,
            t.globally_free,
            CAST(ROUND(t.base_gross_cents * ?) AS INTEGER) AS gross_cents
          FROM region_pack_tile_entries AS owned
          INNER JOIN region_pack_tile_entries AS t
            ON t.catalog_version = owned.catalog_version
           AND t.tile_key = owned.tile_key
          WHERE owned.catalog_version = ?
            AND owned.region_pack_id IN (${chunk.map(() => "?").join(",")})
            AND t.region_pack_id = ?
        )
      `,
      [fullQualityPriceCoefficient(), REGION_PACK_CATALOG_VERSION, ...chunk, targetId],
    );
    tileCount += Math.max(0, Number.parseInt(row && row.tile_count || 0, 10) || 0);
    paidTileCount += Math.max(0, Number.parseInt(row && row.paid_tile_count || 0, 10) || 0);
    freeTileCount += Math.max(0, Number.parseInt(row && row.free_tile_count || 0, 10) || 0);
    baseGrossCents += Math.max(0, Number.parseInt(row && row.base_gross_cents || 0, 10) || 0);
    grossCents += Math.max(0, Number.parseInt(row && row.gross_cents || 0, 10) || 0);
  }
  return {
    tile_count: tileCount,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    base_gross_cents: baseGrossCents,
    gross_cents: grossCents,
  };
}

async function packCoveredTileKeysForFamilies(db, targetProduct, ownedPackIds, familyKeys, deps) {
  const targetId = normalizedRegionPackProductId(targetProduct);
  const ids = Array.from(new Set((Array.isArray(ownedPackIds) ? ownedPackIds : [])
    .map(normalizedRegionPackProductId)
    .filter((id) => id && id !== targetId && regionProductById(id))));
  const families = Array.from(new Set((Array.isArray(familyKeys) ? familyKeys : [])
    .map((family) => String(family || "").trim())
    .filter(Boolean)));
  const covered = new Set();
  if (!targetId || !ids.length || !families.length) {
    return covered;
  }
  await ensureRegionPackTileEntryTable(db, deps);
  for (const familyChunk of fixedSizeChunks(families, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
    for (const idChunk of fixedSizeChunks(ids, Math.max(1, SQL_VARIABLE_SAFE_CHUNK_SIZE - familyChunk.length - 8))) {
      const rows = await deps.dbAll(
        db,
        `
          SELECT DISTINCT t.tile_key AS tile_key
          FROM region_pack_tile_entries AS owned
          INNER JOIN region_pack_tile_entries AS t
            ON t.catalog_version = owned.catalog_version
           AND t.tile_key = owned.tile_key
          WHERE owned.catalog_version = ?
            AND owned.region_pack_id IN (${idChunk.map(() => "?").join(",")})
            AND t.region_pack_id = ?
            AND t.family_key IN (${familyChunk.map(() => "?").join(",")})
        `,
        [REGION_PACK_CATALOG_VERSION, ...idChunk, targetId, ...familyChunk],
      );
      for (const row of rows || []) {
        const key = normalizeTileKey(row && row.tile_key || "");
        if (key) {
          covered.add(key);
        }
      }
    }
  }
  return covered;
}

async function ownedTileKeysForRegionPackMap(db, targetProduct, ownershipContext, deps) {
  const targetId = normalizedRegionPackProductId(targetProduct);
  if (!targetId || !ownershipContext || ownershipContext.world_full_quality_unlocked) {
    return [];
  }
  const purchasedPackIds = Array.from(new Set(Array.isArray(ownershipContext.purchasedPackIds)
    ? ownershipContext.purchasedPackIds.map(normalizedRegionPackProductId).filter(Boolean)
    : []));
  const relations = await relevantPurchasedPackRelations(db, targetProduct, purchasedPackIds, deps);
  const packIds = relations
    .filter(regionPackRelationHasOverlap)
    .map((relation) => normalizedRegionPackProductId(relation.owned_region_pack_id))
    .filter((id) => id && id !== targetId);
  const keys = new Set();
  if (relations.some(regionPackRelationCoversTarget) || (ownershipContext.purchasedPackIdSet && ownershipContext.purchasedPackIdSet.has(targetId))) {
    const rows = await regionPackAllTileRowsForProduct(db, targetProduct, deps);
    for (const row of rows) {
      const key = normalizeTileKey(row && row.key || row && row.tile_key || "");
      if (key) {
        keys.add(key);
      }
    }
  } else if (packIds.length) {
    await ensureRegionPackTileEntryTable(db, deps);
    for (const chunk of fixedSizeChunks(packIds, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
      const rows = await deps.dbAll(
        db,
        `
          SELECT DISTINCT t.tile_key AS tile_key
          FROM region_pack_tile_entries AS owned
          INNER JOIN region_pack_tile_entries AS t
            ON t.catalog_version = owned.catalog_version
           AND t.tile_key = owned.tile_key
          WHERE owned.catalog_version = ?
            AND owned.region_pack_id IN (${chunk.map(() => "?").join(",")})
            AND t.region_pack_id = ?
        `,
        [REGION_PACK_CATALOG_VERSION, ...chunk, targetId],
      );
      for (const row of rows || []) {
        const key = normalizeTileKey(row && row.tile_key || "");
        if (key) {
          keys.add(key);
        }
      }
    }
  }
  return Array.from(keys).sort(compareRegionTileKeys);
}

async function estimateRegionPackSummaryWithPackRelations(db, product, account, ownershipContext, deps, options = {}) {
  const summary = await regionProductPricingSummaryD1(db, product, deps);
  if (!summary) {
    return { error: "missing_region_pack_summary" };
  }
  const discountPercent = regionProductDiscountPercent(product);
  const productId = normalizedRegionPackProductId(product);
  if (isWorldFullQualityUnlocked(account)) {
    const fullCents = integerCents(summary.gross_cents);
    return {
      ok: true,
      summary_estimate: true,
      relation_pricing_estimate: true,
      world_full_quality_unlocked: true,
      region_pack: regionProductPublicPayload(product),
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      discount_percent: discountPercent,
      gross_eur: 0,
      gross_cents: 0,
      gross_price_eur: 0,
      gross_price_cents: 0,
      discount_eur: 0,
      discount_cents: 0,
      already_licenced_gross_eur: centsToEur(fullCents),
      already_licenced_gross_cents: fullCents,
      already_licenced_saving_eur: centsToEur(fullCents),
      already_licenced_saving_cents: fullCents,
      credits: 0,
      credits_cents: 0,
      price_eur: 0,
      price_cents: 0,
      paid_tile_count: 0,
      free_tile_count: summary.tile_count,
      tile_count: summary.tile_count,
      unlicenced_tile_count: 0,
      charged_tile_count: 0,
      new_tile_count: 0,
      new_tiles: [],
      excluded_tiles: new Array(summary.licensable_tile_count).fill(null),
      already_licenced_tile_count: summary.tile_count,
      partial_licence_tile_count: 0,
      partial_licence_credit_eur: 0,
      partial_licence_credit_cents: 0,
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
      tiles: [],
    };
  }
  const context = ownershipContext || await regionPackPricingOwnershipContext(
    db,
    account && account.user_id || "",
    account,
    deps,
    options,
  );
  const purchasedPackIds = Array.from(new Set(Array.isArray(context && context.purchasedPackIds) ? context.purchasedPackIds : []));
  const relations = await relevantPurchasedPackRelations(db, product, purchasedPackIds, deps);
  if (relations.some(regionPackRelationCoversTarget)) {
    const fullCents = integerCents(summary.gross_cents);
    return {
      ok: true,
      summary_estimate: true,
      relation_pricing_estimate: true,
      covered_by_region_pack_relation: true,
      region_pack: regionProductPublicPayload(product),
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      discount_percent: discountPercent,
      gross_eur: 0,
      gross_cents: 0,
      gross_price_eur: 0,
      gross_price_cents: 0,
      discount_eur: 0,
      discount_cents: 0,
      already_licenced_gross_eur: centsToEur(fullCents),
      already_licenced_gross_cents: fullCents,
      already_licenced_saving_eur: centsToEur(fullCents),
      already_licenced_saving_cents: fullCents,
      credits: 0,
      credits_cents: 0,
      price_eur: 0,
      price_cents: 0,
      paid_tile_count: 0,
      free_tile_count: summary.tile_count,
      tile_count: summary.tile_count,
      unlicenced_tile_count: 0,
      charged_tile_count: 0,
      new_tile_count: 0,
      new_tiles: [],
      excluded_tiles: new Array(summary.tile_count).fill(null),
      already_licenced_tile_count: summary.tile_count,
      partial_licence_tile_count: 0,
      partial_licence_credit_eur: 0,
      partial_licence_credit_cents: 0,
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
      tiles: [],
    };
  }

  const relevantPackIds = relations
    .filter(regionPackRelationHasOverlap)
    .map((relation) => normalizedRegionPackProductId(relation.owned_region_pack_id))
    .filter(Boolean);
  const packCoverage = await packCoverageAggregateForTarget(db, product, relevantPackIds, deps);
  const packCoverageGrossCents = Math.max(0, integerCents(packCoverage.gross_cents));
  let grossCents = Math.max(0, integerCents(summary.gross_cents) - packCoverageGrossCents);
  let paidTileCount = Math.max(0, Number.parseInt(summary.paid_tile_count || 0, 10) - Math.max(0, Number.parseInt(packCoverage.paid_tile_count || 0, 10) || 0));
  let freeTileCount = Math.max(0, Number.parseInt(summary.free_tile_count || 0, 10) - Math.max(0, Number.parseInt(packCoverage.free_tile_count || 0, 10) || 0));
  let alreadyLicencedCount = Math.max(0, Number.parseInt(packCoverage.tile_count || 0, 10) || 0);
  let alreadyLicencedGrossCents = packCoverageGrossCents;
  let partialLicenceCount = 0;
  let partialLicenceCreditCents = 0;

  const sceneOwnedByFamily = context && context.sceneOwnedByFamily instanceof Map
    ? context.sceneOwnedByFamily
    : new Map();
  if (sceneOwnedByFamily.size > 0) {
    const familyKeys = Array.from(sceneOwnedByFamily.keys());
    const familyRowsRaw = await regionPackTileRowsForProductFamilies(db, product, familyKeys, deps);
    const packCoveredKeys = await packCoveredTileKeysForFamilies(db, product, relevantPackIds, familyKeys, deps);
    const rowsByFamily = new Map();
    for (const row of familyRowsRaw) {
      const key = normalizeTileKey(row && row.key || row && row.tile_key || "");
      if (key && packCoveredKeys.has(key)) {
        continue;
      }
      const family = String(row && row.family || "");
      if (!family || !sceneOwnedByFamily.has(family)) {
        continue;
      }
      if (!rowsByFamily.has(family)) {
        rowsByFamily.set(family, []);
      }
      rowsByFamily.get(family).push(row);
    }
    for (const [family, familyRows] of rowsByFamily.entries()) {
      const ownedEntries = safeOwnedEntriesForFamily(sceneOwnedByFamily, family, familyRows);
      if (!ownedEntries.length) {
        continue;
      }
      const staticEstimate = estimateRegionPackFamilyRows(familyRows, []);
      const familyEstimate = estimateRegionPackFamilyRows(familyRows, ownedEntries);
      grossCents += familyEstimate.gross_cents - staticEstimate.gross_cents;
      paidTileCount += familyEstimate.paid_tile_count - staticEstimate.paid_tile_count;
      freeTileCount += familyEstimate.free_tile_count - staticEstimate.free_tile_count;
      alreadyLicencedCount += familyEstimate.already_licenced_count;
      alreadyLicencedGrossCents += familyEstimate.already_licenced_gross_cents;
      partialLicenceCount += Math.max(0, Number.parseInt(familyEstimate.partial_licence_count || 0, 10) || 0);
      partialLicenceCreditCents += Math.max(0, Number.parseInt(familyEstimate.partial_licence_credit_cents || 0, 10) || 0);
    }
  }

  grossCents = Math.max(0, Math.round(grossCents));
  paidTileCount = Math.max(0, Math.round(paidTileCount));
  freeTileCount = Math.max(0, Math.round(freeTileCount));
  alreadyLicencedGrossCents = Math.max(0, Math.min(integerCents(summary.gross_cents), Math.round(alreadyLicencedGrossCents)));
  const amounts = discountedRegionPackAmountCents(grossCents, discountPercent);
  const unlicencedTileCount = regionPackVisibleNewTileCount(paidTileCount, freeTileCount);
  return {
    ok: true,
    summary_estimate: true,
    relation_pricing_estimate: true,
    relation_count: relations.length,
    relation_pack_count: relevantPackIds.length,
    region_pack: regionProductPublicPayload(product),
    region_pack_id: String(product.id || ""),
    region_pack_name: String(product.name || ""),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    discount_percent: discountPercent,
    gross_eur: amounts.gross,
    gross_cents: amounts.gross_cents,
    gross_price_eur: amounts.gross,
    gross_price_cents: amounts.gross_cents,
    discount_eur: amounts.discount,
    discount_cents: amounts.discount_cents,
    already_licenced_gross_eur: centsToEur(alreadyLicencedGrossCents),
    already_licenced_gross_cents: alreadyLicencedGrossCents,
    already_licenced_saving_eur: centsToEur(alreadyLicencedGrossCents),
    already_licenced_saving_cents: alreadyLicencedGrossCents,
    credits: amounts.price,
    credits_cents: amounts.price_cents,
    price_eur: amounts.price,
    price_cents: amounts.price_cents,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: summary.tile_count,
    unlicenced_tile_count: unlicencedTileCount,
    charged_tile_count: paidTileCount,
    new_tile_count: paidTileCount,
    already_licenced_tile_count: alreadyLicencedCount,
    partial_licence_tile_count: partialLicenceCount,
    partial_licence_credit_eur: centsToEur(partialLicenceCreditCents),
    partial_licence_credit_cents: partialLicenceCreditCents,
    new_tiles: [],
    excluded_tiles: new Array(alreadyLicencedCount).fill(null),
    integrity_warnings: [],
    metadata_missing_tile_keys: [],
    tiles: [],
  };
}

function worldRegionProductSummary() {
  const product = regionProductById("world");
  if (!product) {
    return {
      tile_count: 0,
      licensable_tile_count: 0,
      paid_tile_count: 0,
      gross_eur: 0,
      gross_cents: 0,
    };
  }
  const grossCents = applyFullQualityPriceCoefficientCents(product.gross_cents || centsForEur(product.gross_eur || 0));
  return {
    tile_count: Math.max(0, Number.parseInt(product.tile_count || 0, 10) || 0),
    licensable_tile_count: Math.max(0, Number.parseInt(product.licensable_tile_count || 0, 10) || 0),
    paid_tile_count: Math.max(0, Number.parseInt(product.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(product.free_tile_count || 0, 10) || 0),
    gross_cents: grossCents,
    gross_eur: centsToEur(grossCents),
  };
}

function discountedRegionPackAmountCents(grossCents, discountPercent) {
  const gross = integerCents(grossCents);
  const percent = Math.max(0, Math.min(100, Number.parseInt(discountPercent || 0, 10) || 0));
  const discount = Math.max(0, Math.min(gross, Math.round((gross * percent) / 100)));
  const price = Math.max(0, gross - discount);
  return {
    gross_cents: gross,
    discount_cents: discount,
    price_cents: price,
    gross: centsToEur(gross),
    discount: centsToEur(discount),
    price: centsToEur(price),
  };
}

function discountedRegionPackAmount(grossEur, discountPercent) {
  return discountedRegionPackAmountCents(centsForEur(grossEur), discountPercent);
}

function parsePricingNumber(value, fallback, options = {}) {
  const numeric = Number.parseFloat(value);
  const min = Number.isFinite(Number(options.min)) ? Number(options.min) : Number.NEGATIVE_INFINITY;
  const max = Number.isFinite(Number(options.max)) ? Number(options.max) : Number.POSITIVE_INFINITY;
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, numeric));
}

function roundDiscountPercentToNearestFive(value) {
  const numeric = Math.max(0, Math.min(95, Number.parseFloat(value || 0) || 0));
  return Math.max(0, Math.min(95, Math.round(numeric / 5) * 5));
}

function normalizeDiscountShareBucketPair(raw) {
  let threshold = null;
  let ratio = null;
  if (Array.isArray(raw)) {
    threshold = Number(raw[0]);
    ratio = Number(raw[1]);
  } else if (raw && typeof raw === "object") {
    threshold = Number(raw.threshold ?? raw.threshold_share ?? raw.threshold_percent);
    ratio = Number(raw.ratio ?? raw.range_ratio ?? raw.range_percent);
  }
  if (!Number.isFinite(threshold) || !Number.isFinite(ratio)) {
    return null;
  }
  const normalizedThreshold = threshold > 1 ? threshold / 100.0 : threshold;
  const normalizedRatio = ratio > 1 ? ratio / 100.0 : ratio;
  return [
    Math.max(0, Math.min(1, normalizedThreshold)),
    Math.max(0, Math.min(1, normalizedRatio)),
  ];
}

function normalizeDiscountShareBuckets(rawBuckets) {
  let source = rawBuckets;
  if (typeof source === "string") {
    try {
      source = JSON.parse(source);
    } catch (_error) {
      source = null;
    }
  }
  const sourceWasArray = Array.isArray(source);
  const rawList = sourceWasArray ? source : DEFAULT_REGION_PACK_DISCOUNT_SHARE_BUCKETS;
  const byThreshold = new Map();
  for (const raw of rawList) {
    const pair = normalizeDiscountShareBucketPair(raw);
    if (!pair) {
      continue;
    }
    const [threshold, ratio] = pair;
    if (threshold <= 0) {
      continue;
    }
    byThreshold.set(threshold.toFixed(6), [threshold, ratio]);
  }
  const buckets = Array.from(byThreshold.values())
    .sort(([left], [right]) => right - left)
    .slice(0, 20);
  if (!buckets.length) {
    if (sourceWasArray) {
      return [[0, 0]];
    }
    return DEFAULT_REGION_PACK_DISCOUNT_SHARE_BUCKETS.map(([threshold, ratio]) => [threshold, ratio]);
  }
  buckets.push([0, 0]);
  return buckets;
}

function discountShareBucketsSignature(buckets = []) {
  return normalizeDiscountShareBuckets(buckets)
    .map(([threshold, ratio]) => `${threshold.toFixed(6)}:${ratio.toFixed(6)}`)
    .join("|");
}

function discountShareBucketsStorageValue(buckets = []) {
  return JSON.stringify(
    normalizeDiscountShareBuckets(buckets)
      .filter(([threshold]) => threshold > 0)
      .map(([threshold, ratio]) => [Number(threshold.toFixed(6)), Number(ratio.toFixed(6))]),
  );
}

function defaultRuntimePricingSettings(env = {}) {
  const coefficient = parsePricingNumber(
    env && env.FULL_QUALITY_PRICE_COEFFICIENT,
    DEFAULT_FULL_QUALITY_PRICE_COEFFICIENT,
    { min: 0.000001, max: 1000 },
  );
  const minDiscount = roundDiscountPercentToNearestFive(parsePricingNumber(
    env && env.REGION_PACK_DISCOUNT_MIN_PERCENT,
    DEFAULT_REGION_PACK_DISCOUNT_MIN_PERCENT,
    { min: 0, max: 95 },
  ));
  const maxDiscount = roundDiscountPercentToNearestFive(parsePricingNumber(
    env && env.REGION_PACK_DISCOUNT_MAX_PERCENT,
    DEFAULT_REGION_PACK_DISCOUNT_MAX_PERCENT,
    { min: 0, max: 95 },
  ));
  const sceneCustomLicenceFee = normalizeCreditAmount(parsePricingNumber(
    env && env.CUSTOM_SCENE_LICENCE_FEE_EUR,
    DEFAULT_SCENE_CUSTOM_LICENCE_FEE_EUR,
    { min: 0, max: 1000 },
  ));
  const animationCustomLicenceMaxFee = normalizeCreditAmount(parsePricingNumber(
    env && (env.CUSTOM_ANIMATION_LICENCE_MAX_FEE_EUR ?? env.CUSTOM_ANIMATION_LICENCE_FEE_EUR),
    DEFAULT_ANIMATION_CUSTOM_LICENCE_MAX_FEE_EUR,
    { min: 0, max: 1000 },
  ));
  return {
    full_quality_price_coefficient: coefficient,
    region_pack_discount_min_percent: Math.min(minDiscount, maxDiscount),
    region_pack_discount_max_percent: Math.max(minDiscount, maxDiscount),
    region_pack_discount_share_buckets: normalizeDiscountShareBuckets(DEFAULT_REGION_PACK_DISCOUNT_SHARE_BUCKETS),
    region_pack_discount_share_buckets_signature: discountShareBucketsSignature(DEFAULT_REGION_PACK_DISCOUNT_SHARE_BUCKETS),
    custom_scene_licence_fee_eur: sceneCustomLicenceFee,
    custom_animation_licence_max_fee_eur: animationCustomLicenceMaxFee,
    product_discount_overrides: {},
    product_discount_overrides_signature: "",
  };
}

function normalizeRegionProductId(value) {
  return String(value || "").trim().toLowerCase();
}

function normalizeProductDiscountOverridePercent(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const text = String(value).trim();
  if (!text) {
    return null;
  }
  const numeric = Number.parseFloat(text);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function normalizeProductDiscountOverrides(rawOverrides = {}) {
  const overrides = {};
  if (!rawOverrides || typeof rawOverrides !== "object") {
    return overrides;
  }
  for (const [rawId, rawValue] of Object.entries(rawOverrides)) {
    const productId = normalizeRegionProductId(rawId);
    const value = normalizeProductDiscountOverridePercent(rawValue);
    if (productId && value !== null && regionProductById(productId)) {
      overrides[productId] = value;
    }
  }
  return overrides;
}

function productDiscountOverridesSignature(overrides = {}) {
  const pairs = Object.entries(overrides || {})
    .filter(([id, value]) => Boolean(id) && Number.isFinite(Number(value)))
    .sort(([left], [right]) => String(left).localeCompare(String(right)));
  return pairs.map(([id, value]) => `${id}:${Number(value)}`).join("|");
}

function normalizeRuntimePricingSettings(raw, env = {}) {
  const fallback = defaultRuntimePricingSettings(env);
  const coefficient = parsePricingNumber(
    raw && raw.full_quality_price_coefficient,
    fallback.full_quality_price_coefficient,
    { min: 0.000001, max: 1000 },
  );
  const minDiscount = roundDiscountPercentToNearestFive(parsePricingNumber(
    raw && raw.region_pack_discount_min_percent,
    fallback.region_pack_discount_min_percent,
    { min: 0, max: 95 },
  ));
  const maxDiscount = roundDiscountPercentToNearestFive(parsePricingNumber(
    raw && raw.region_pack_discount_max_percent,
    fallback.region_pack_discount_max_percent,
    { min: 0, max: 95 },
  ));
  const discountShareBuckets = normalizeDiscountShareBuckets(
    raw && (raw.region_pack_discount_share_buckets_json ?? raw.region_pack_discount_share_buckets)
      || fallback.region_pack_discount_share_buckets,
  );
  const sceneCustomLicenceFee = normalizeCreditAmount(parsePricingNumber(
    raw && raw.custom_scene_licence_fee_eur,
    fallback.custom_scene_licence_fee_eur,
    { min: 0, max: 1000 },
  ));
  const animationCustomLicenceMaxFee = normalizeCreditAmount(parsePricingNumber(
    raw && (raw.custom_animation_licence_max_fee_eur ?? raw.custom_animation_licence_fee_eur),
    fallback.custom_animation_licence_max_fee_eur,
    { min: 0, max: 1000 },
  ));
  const productDiscountOverrides = normalizeProductDiscountOverrides(raw && raw.product_discount_overrides);
  return {
    full_quality_price_coefficient: coefficient,
    region_pack_discount_min_percent: Math.min(minDiscount, maxDiscount),
    region_pack_discount_max_percent: Math.max(minDiscount, maxDiscount),
    region_pack_discount_share_buckets: discountShareBuckets,
    region_pack_discount_share_buckets_signature: discountShareBucketsSignature(discountShareBuckets),
    custom_scene_licence_fee_eur: sceneCustomLicenceFee,
    custom_animation_licence_max_fee_eur: animationCustomLicenceMaxFee,
    product_discount_overrides: productDiscountOverrides,
    product_discount_overrides_signature: productDiscountOverridesSignature(productDiscountOverrides),
  };
}

function activePricingSettings() {
  return PRICING_SETTINGS_CACHE.settings || defaultRuntimePricingSettings({});
}

function pricingSettingsCacheKey() {
  const settings = activePricingSettings();
  return [
    REGION_PACK_PRICING_ENGINE_REVISION,
    Number(settings.full_quality_price_coefficient || 1).toFixed(6),
    Number(settings.region_pack_discount_min_percent || 0),
    Number(settings.region_pack_discount_max_percent || 0),
    String(settings.region_pack_discount_share_buckets_signature || ""),
    Number(settings.custom_scene_licence_fee_eur || 0).toFixed(2),
    Number(settings.custom_animation_licence_max_fee_eur || 0).toFixed(2),
    String(settings.product_discount_overrides_signature || ""),
  ].join("|");
}

async function ensurePricingSettingsTable(db, deps) {
  if (!db || !deps || typeof deps.dbRun !== "function") {
    return;
  }
  await deps.dbRun(
    db,
    `CREATE TABLE IF NOT EXISTS app_settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      updated_by_user_id TEXT
    )`,
  );
}

export function invalidatePricingSettingsCache() {
  PRICING_SETTINGS_CACHE = {
    loaded_at_ms: 0,
    settings: null,
  };
  REGION_PRODUCT_GROSS_CENTS_CACHE.clear();
  REGION_OFFERS_RESPONSE_CACHE.clear();
  REGION_PACK_ESTIMATE_CACHE.clear();
}

export async function getRuntimePricingSettings(env = {}, deps = {}, options = {}) {
  const force = Boolean(options && options.force);
  const now = Date.now();
  if (
    !force
    && PRICING_SETTINGS_CACHE.settings
    && (now - Number(PRICING_SETTINGS_CACHE.loaded_at_ms || 0)) < PRICING_SETTINGS_CACHE_TTL_MS
  ) {
    return PRICING_SETTINGS_CACHE.settings;
  }
  const defaults = defaultRuntimePricingSettings(env);
  const db = env && env.DB ? env.DB : null;
  if (!db || !deps || typeof deps.dbAll !== "function") {
    PRICING_SETTINGS_CACHE = { loaded_at_ms: now, settings: defaults };
    return defaults;
  }
  try {
    await ensurePricingSettingsTable(db, deps);
    const rows = await deps.dbAll(
      db,
      `SELECT key, value FROM app_settings WHERE key IN (?, ?, ?, ?, ?, ?, ?) OR key LIKE ?`,
      [
        PRICING_SETTINGS_KEYS.coefficient,
        PRICING_SETTINGS_KEYS.minDiscount,
        PRICING_SETTINGS_KEYS.maxDiscount,
        PRICING_SETTINGS_KEYS.discountShareBuckets,
        PRICING_SETTINGS_KEYS.sceneCustomLicenceFee,
        PRICING_SETTINGS_KEYS.animationCustomLicenceMaxFee,
        PRICING_SETTINGS_KEYS.legacyAnimationCustomLicenceFee,
        `${PRICING_SETTINGS_KEYS.productDiscountPrefix}%`,
      ],
    );
    const raw = { ...defaults };
    const overrides = {};
    for (const row of Array.isArray(rows) ? rows : []) {
      const key = String(row && row.key || "");
      if (key === PRICING_SETTINGS_KEYS.coefficient) raw.full_quality_price_coefficient = row.value;
      if (key === PRICING_SETTINGS_KEYS.minDiscount) raw.region_pack_discount_min_percent = row.value;
      if (key === PRICING_SETTINGS_KEYS.maxDiscount) raw.region_pack_discount_max_percent = row.value;
      if (key === PRICING_SETTINGS_KEYS.discountShareBuckets) raw.region_pack_discount_share_buckets_json = row.value;
      if (key === PRICING_SETTINGS_KEYS.sceneCustomLicenceFee) raw.custom_scene_licence_fee_eur = row.value;
      if (key === PRICING_SETTINGS_KEYS.animationCustomLicenceMaxFee) raw.custom_animation_licence_max_fee_eur = row.value;
      if (key.startsWith(PRICING_SETTINGS_KEYS.productDiscountPrefix)) {
        const productId = normalizeRegionProductId(key.slice(PRICING_SETTINGS_KEYS.productDiscountPrefix.length));
        if (productId) {
          overrides[productId] = row.value;
        }
      }
    }
    raw.product_discount_overrides = overrides;
    const settings = normalizeRuntimePricingSettings(raw, env);
    PRICING_SETTINGS_CACHE = { loaded_at_ms: now, settings };
    return settings;
  } catch (error) {
    console.error("planetka.pricing_settings_load_failed", JSON.stringify({
      error: String(error && error.message || error || "pricing_settings_load_failed"),
    }));
    if (options && options.strict) {
      throw error;
    }
    PRICING_SETTINGS_CACHE = { loaded_at_ms: now, settings: defaults };
    return defaults;
  }
}

async function ensureRuntimePricingSettings(env = {}, deps = {}) {
  // Pricing settings live in D1 and Worker isolates are independent. Always
  // load them before any public pricing calculation so Blender, map pages,
  // success pages, and Stripe checkout cannot diverge.
  return await getRuntimePricingSettings(env, deps, { force: true, strict: true });
}

export async function setRuntimePricingSettings(db, values = {}, adminUserId = "", deps = {}) {
  if (!db || !deps || typeof deps.dbRun !== "function") {
    throw new Error("pricing_settings_db_unavailable");
  }
  const currentSettings = activePricingSettings();
  const settings = normalizeRuntimePricingSettings(
    {
      ...currentSettings,
      product_discount_overrides: currentSettings.product_discount_overrides || {},
      ...values,
    },
    {},
  );
  await ensurePricingSettingsTable(db, deps);
  const updatedAt = new Date().toISOString();
  const adminId = String(adminUserId || "");
  const pairs = [
    [PRICING_SETTINGS_KEYS.coefficient, String(settings.full_quality_price_coefficient)],
    [PRICING_SETTINGS_KEYS.minDiscount, String(settings.region_pack_discount_min_percent)],
    [PRICING_SETTINGS_KEYS.maxDiscount, String(settings.region_pack_discount_max_percent)],
    [PRICING_SETTINGS_KEYS.discountShareBuckets, discountShareBucketsStorageValue(settings.region_pack_discount_share_buckets)],
    [PRICING_SETTINGS_KEYS.sceneCustomLicenceFee, String(settings.custom_scene_licence_fee_eur)],
    [PRICING_SETTINGS_KEYS.animationCustomLicenceMaxFee, String(settings.custom_animation_licence_max_fee_eur)],
  ];
  for (const [key, value] of pairs) {
    await deps.dbRun(
      db,
      `INSERT INTO app_settings (key, value, updated_at, updated_by_user_id)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(key) DO UPDATE SET
         value = excluded.value,
         updated_at = excluded.updated_at,
         updated_by_user_id = excluded.updated_by_user_id`,
      [key, value, updatedAt, adminId],
    );
  }
  await deps.dbRun(db, `DELETE FROM app_settings WHERE key = ?`, [PRICING_SETTINGS_KEYS.legacyAnimationCustomLicenceFee]);
  const overrideRows = await deps.dbAll(
    db,
    `SELECT key, value FROM app_settings WHERE key LIKE ?`,
    [`${PRICING_SETTINGS_KEYS.productDiscountPrefix}%`],
  );
  const overrides = {};
  for (const row of Array.isArray(overrideRows) ? overrideRows : []) {
    const key = String(row && row.key || "");
    const productId = normalizeRegionProductId(key.slice(PRICING_SETTINGS_KEYS.productDiscountPrefix.length));
    if (productId) {
      overrides[productId] = row.value;
    }
  }
  settings.product_discount_overrides = normalizeProductDiscountOverrides(overrides);
  settings.product_discount_overrides_signature = productDiscountOverridesSignature(settings.product_discount_overrides);
  invalidatePricingSettingsCache();
  PRICING_SETTINGS_CACHE = { loaded_at_ms: Date.now(), settings };
  return settings;
}

export async function setRegionProductDiscountOverride(db, env = {}, regionPackId = "", discountPercent = null, adminUserId = "", deps = {}) {
  if (!db || !deps || typeof deps.dbRun !== "function") {
    throw new Error("pricing_settings_db_unavailable");
  }
  const productId = normalizeRegionProductId(regionPackId);
  const product = regionProductById(productId);
  if (!product || isHiddenRegionProduct(product)) {
    throw new Error("unknown_region_pack");
  }
  const overridePercent = normalizeProductDiscountOverridePercent(discountPercent);
  await ensurePricingSettingsTable(db, deps);
  const key = `${PRICING_SETTINGS_KEYS.productDiscountPrefix}${productId}`;
  if (overridePercent === null) {
    await deps.dbRun(db, `DELETE FROM app_settings WHERE key = ?`, [key]);
  } else {
    await deps.dbRun(
      db,
      `INSERT INTO app_settings (key, value, updated_at, updated_by_user_id)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(key) DO UPDATE SET
         value = excluded.value,
         updated_at = excluded.updated_at,
         updated_by_user_id = excluded.updated_by_user_id`,
      [key, String(overridePercent), new Date().toISOString(), String(adminUserId || "")],
    );
  }
  invalidatePricingSettingsCache();
  return await getRuntimePricingSettings(env, deps, { force: true });
}

function regionProductLandShare(product) {
  const share = Number(product && product.volume_discount_basis && product.volume_discount_basis.world_land_share);
  return Number.isFinite(share) && share > 0 ? share : 0;
}

function regionProductDefaultDiscountPercent(product, settings = activePricingSettings()) {
  if (!product || typeof product !== "object") {
    return 0;
  }
  const minPercent = Math.max(0, Math.min(95, Number(settings.region_pack_discount_min_percent || 0) || 0));
  const maxPercent = Math.max(minPercent, Math.min(95, Number(settings.region_pack_discount_max_percent || 0) || 0));
  const share = regionProductLandShare(product);
  const buckets = Array.isArray(settings.region_pack_discount_share_buckets) && settings.region_pack_discount_share_buckets.length
    ? settings.region_pack_discount_share_buckets
    : DEFAULT_REGION_PACK_DISCOUNT_SHARE_BUCKETS;
  const bucket = buckets.find(([threshold]) => share >= threshold);
  const ratio = bucket ? Number(bucket[1]) : 0;
  return roundDiscountPercentToNearestFive(minPercent + ((maxPercent - minPercent) * ratio));
}

function regionProductDiscountPercent(product) {
  if (!product || typeof product !== "object") {
    return 0;
  }
  const settings = activePricingSettings();
  const productId = normalizeRegionProductId(product.id);
  const overrides = settings && settings.product_discount_overrides && typeof settings.product_discount_overrides === "object"
    ? settings.product_discount_overrides
    : {};
  const override = normalizeProductDiscountOverridePercent(overrides[productId]);
  if (override !== null) {
    return override;
  }
  return regionProductDefaultDiscountPercent(product, settings);
}

function regionProductPricingAdminRow(product, settings = activePricingSettings(), pricingSummary = null) {
  const summary = pricingSummary || regionProductPricingSummary(product) || {};
  const productId = normalizeRegionProductId(product && product.id);
  const overrides = settings && settings.product_discount_overrides && typeof settings.product_discount_overrides === "object"
    ? settings.product_discount_overrides
    : {};
  const overrideDiscount = normalizeProductDiscountOverridePercent(overrides[productId]);
  const defaultDiscount = regionProductDefaultDiscountPercent(product, settings);
  const effectiveDiscount = overrideDiscount !== null ? overrideDiscount : defaultDiscount;
  const fullPriceEur = normalizeCreditAmount(summary.gross_eur);
  const defaultAmounts = discountedRegionPackAmount(fullPriceEur, defaultDiscount);
  const effectiveAmounts = discountedRegionPackAmount(fullPriceEur, effectiveDiscount);
  return {
    id: productId,
    name: String(product && product.name || ""),
    type: String(product && product.type || ""),
    tile_count: Math.max(0, Number.parseInt(summary.tile_count || product && product.tile_count || 0, 10) || 0),
    paid_tile_count: Math.max(0, Number.parseInt(summary.paid_tile_count || product && product.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(summary.free_tile_count || product && product.free_tile_count || 0, 10) || 0),
    gross_base_eur: normalizeCreditAmount((Number(product && product.gross_cents || 0) || 0) / 100.0),
    full_price_eur: fullPriceEur,
    default_discount_percent: defaultDiscount,
    override_discount_percent: overrideDiscount,
    effective_discount_percent: effectiveDiscount,
    default_final_price_eur: defaultAmounts.price,
    discount_eur: effectiveAmounts.discount,
    final_price_eur: effectiveAmounts.price,
    world_land_share: regionProductLandShare(product),
    has_override: overrideDiscount !== null,
  };
}

export async function listRegionProductPricingRows(env = {}, deps = {}) {
  const settings = await getRuntimePricingSettings(env, deps, { force: false });
  const db = deps && typeof deps.requireDb === "function" ? deps.requireDb(env) : null;
  const rows = [];
  for (const product of REGION_PRODUCTS.filter((entry) => entry && !isHiddenRegionProduct(entry))) {
    const summary = db ? await regionProductPricingSummaryD1(db, product, deps) : null;
    rows.push(regionProductPricingAdminRow(product, settings, summary));
  }
  rows.sort((left, right) => (
      String(left.type || "").localeCompare(String(right.type || ""))
      || String(left.name || "").localeCompare(String(right.name || ""))
    ));
  return {
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    pricing_settings: settings,
    rows,
  };
}

function fullQualityPublicPriceCoefficient() {
  const coefficient = Number.parseFloat(activePricingSettings().full_quality_price_coefficient);
  return Number.isFinite(coefficient) && coefficient > 0 ? coefficient : 1.0;
}

function fullQualityPriceCoefficient() {
  // Generated catalog gross values were built with d001 equator tile area as
  // the coefficient-1.0 baseline. The Analytics-facing coefficient is now
  // defined as EUR per 10,000 km2, so convert it to the generated-catalog
  // multiplier here and keep every downstream pricing path unchanged.
  return fullQualityPublicPriceCoefficient() * PUBLIC_COEFFICIENT_TO_LEGACY_GROSS_MULTIPLIER;
}

function customSceneLicenceCents() {
  return centsForEur(activePricingSettings().custom_scene_licence_fee_eur);
}

function customAnimationLicencePerResolveCents() {
  return customSceneLicenceCents();
}

function customAnimationLicenceMaxCents() {
  return centsForEur(activePricingSettings().custom_animation_licence_max_fee_eur);
}

function checkoutMetadataCents(metadata, key, fallbackCents) {
  if (!metadata || typeof metadata !== "object" || !Object.prototype.hasOwnProperty.call(metadata, key)) {
    return Math.max(0, Number.parseInt(fallbackCents || 0, 10) || 0);
  }
  return centsForEur(metadata[key]);
}

function applyFullQualityPriceCoefficientCents(baseCents) {
  const cents = Math.max(0, Number.parseInt(baseCents || 0, 10) || 0);
  if (cents <= 0) {
    return 0;
  }
  return Math.max(0, Math.round(cents * fullQualityPriceCoefficient()));
}

function applyFullQualityPriceCoefficientEur(baseEur) {
  const eur = Math.max(0, Number.parseFloat(baseEur || 0) || 0);
  return normalizeCreditAmount(eur * fullQualityPriceCoefficient());
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

function cloneOwnedRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map((row) => ({ tile_key: normalizeTileKey(row && row.tile_key || "") }))
    .filter((row) => row.tile_key);
}

function ownedRowsFromFamilyMap(ownedByFamily) {
  if (!(ownedByFamily instanceof Map) || ownedByFamily.size <= 0) {
    return [];
  }
  const rows = [];
  for (const entries of ownedByFamily.values()) {
    for (const entry of Array.isArray(entries) ? entries : []) {
      const key = normalizeTileKey(entry && entry.key || "");
      if (key) {
        rows.push({ tile_key: key });
      }
    }
  }
  return rows;
}

async function loadStoredEntitlementSummary(db, userId, version, deps) {
  const safeUserId = String(userId || "").trim();
  const safeVersion = String(version || "");
  if (!safeUserId || !safeVersion) {
    return null;
  }
  try {
    const row = await deps.dbGet(
      db,
      `
        SELECT rows_json
        FROM user_entitlement_summaries
        WHERE user_id = ?
          AND version = ?
        LIMIT 1
      `,
      [safeUserId, safeVersion],
    );
    if (!row || !row.rows_json) {
      return null;
    }
    return cloneOwnedRows(JSON.parse(String(row.rows_json || "[]")));
  } catch (_error) {
    return null;
  }
}

async function storeEntitlementSummaryBestEffort(db, userId, version, rows, deps) {
  const safeUserId = String(userId || "").trim();
  const safeVersion = String(version || "");
  if (!safeUserId || !safeVersion) {
    return;
  }
  try {
    await deps.dbRun(
      db,
      `
        INSERT INTO user_entitlement_summaries (user_id, version, rows_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          version = excluded.version,
          rows_json = excluded.rows_json,
          updated_at = excluded.updated_at
      `,
      [safeUserId, safeVersion, JSON.stringify(cloneOwnedRows(rows)), deps.nowIso && deps.nowIso() || new Date().toISOString()],
    );
  } catch (_error) {
    // The summary table is an optimization only; pricing stays correct by
    // falling back to authoritative user_tile_entitlements rows.
  }
}

async function touchUserPricingVersion(db, userId, deps, timestamp = "") {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return;
  }
  const now = String(timestamp || deps.nowIso && deps.nowIso() || new Date().toISOString());
  await deps.dbRun(
    db,
    `
      UPDATE user_credit_accounts
      SET
        pricing_version = COALESCE(pricing_version, 0) + 1,
        updated_at = ?
      WHERE user_id = ?
    `,
    [now, safeUserId],
  );
  try {
    await deps.dbRun(
      db,
      `DELETE FROM user_entitlement_summaries WHERE user_id = ?`,
      [safeUserId],
    );
  } catch (_error) {
    // Cache invalidation must never block entitlement writes.
  }
  invalidateUserPricingCaches(safeUserId);
}

async function verifyInsertedTileEntitlements(db, userId, insertedTiles, deps) {
  const safeUserId = String(userId || "").trim();
  const keys = normalizeTileKeys((insertedTiles || []).map((tile) => tile && tile.tile_key || ""));
  if (!safeUserId || !keys.length) {
    return [];
  }
  const failed = [];
  for (const key of keys) {
    if (isFreeCreditTileKey(key)) {
      continue;
    }
    const unlocked = await isTileUnlockedForUser(db, safeUserId, key, deps, { authoritative: true });
    if (!unlocked) {
      failed.push(key);
    }
  }
  return failed;
}

async function ownedEntitlementSummaryForUser(db, userId, deps, options = {}) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return { rows: [], ownedByFamily: new Map(), cache_hit: false, version: "" };
  }
  const includeRows = !(options && options.includeRows === false);
  const account = options && options.account ? options.account : await ensureCreditAccount(db, safeUserId, deps);
  const version = accountEntitlementVersion(account);
  if (isWorldFullQualityUnlocked(account)) {
    return {
      rows: [],
      ownedByFamily: new Map(),
      cache_hit: true,
      version,
      world_full_quality_unlocked: true,
    };
  }
  const cacheKey = `${safeUserId}|${version}`;
  const nowMs = monotonicNowMs();
  const cached = USER_ENTITLEMENT_SUMMARY_CACHE.get(cacheKey);
  if (
    cached
    && (nowMs - Number(cached.cached_at_ms || 0)) <= USER_ENTITLEMENT_SUMMARY_CACHE_TTL_MS
    ) {
    return {
      rows: includeRows
        ? (cached.has_rows ? cloneOwnedRows(cached.rows) : ownedRowsFromFamilyMap(cached.ownedByFamily))
        : [],
      ownedByFamily: cached.ownedByFamily,
      cache_hit: true,
      version,
    };
  }
  const storedRows = await loadStoredEntitlementSummary(db, safeUserId, version, deps);
  if (storedRows) {
    const ownedByFamily = ownedByFamilyFromTileRows(storedRows);
    boundedCacheSet(
        USER_ENTITLEMENT_SUMMARY_CACHE,
        cacheKey,
        {
          rows: includeRows ? storedRows : [],
          has_rows: includeRows,
          ownedByFamily,
          cached_at_ms: nowMs,
      },
      USER_ENTITLEMENT_SUMMARY_CACHE_MAX,
    );
    return {
      rows: includeRows ? cloneOwnedRows(storedRows) : [],
      ownedByFamily,
      cache_hit: true,
      version,
      stored_cache_hit: true,
    };
  }
  const rows = await deps.dbAll(
    db,
    `
      SELECT tile_key
      FROM user_tile_entitlements
      WHERE user_id = ?
    `,
    [safeUserId],
  );
  const safeRows = cloneOwnedRows(rows);
  const ownedByFamily = ownedByFamilyFromTileRows(safeRows);
  await storeEntitlementSummaryBestEffort(db, safeUserId, version, safeRows, deps);
  boundedCacheSet(
    USER_ENTITLEMENT_SUMMARY_CACHE,
    cacheKey,
    {
      rows: includeRows ? safeRows : [],
      has_rows: includeRows,
      ownedByFamily,
      cached_at_ms: nowMs,
    },
    USER_ENTITLEMENT_SUMMARY_CACHE_MAX,
  );
  return {
    rows: includeRows ? cloneOwnedRows(safeRows) : [],
    ownedByFamily,
    cache_hit: false,
    version,
  };
}

async function ownedTileRowsForUser(db, userId, deps, options = {}) {
  const summary = await ownedEntitlementSummaryForUser(db, userId, deps, options);
  return cloneOwnedRows(summary.rows);
}

async function ownedTileRowsForUserFamilies(db, userId, familyKeys, deps) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  const families = Array.from(new Set((Array.isArray(familyKeys) ? familyKeys : [])
    .map((family) => String(family || "").trim())
    .filter(Boolean)));
  if (!safeUserId || !families.length) {
    return [];
  }
  const rows = [];
  const rangesPerChunk = Math.max(1, Math.floor((SQL_VARIABLE_SAFE_CHUNK_SIZE - 1) / 2));
  for (const chunk of fixedSizeChunks(families, rangesPerChunk)) {
    const params = [safeUserId];
    const clauses = [];
    for (const family of chunk) {
      const prefix = `${family}_d`;
      const end = `${family}_e`;
      clauses.push("(tile_key >= ? AND tile_key < ?)");
      params.push(prefix, end);
    }
    rows.push(...await deps.dbAll(
      db,
      `
        SELECT tile_key
        FROM user_tile_entitlements
        WHERE user_id = ?
          AND (${clauses.join(" OR ")})
      `,
      params,
    ));
  }
  return cloneOwnedRows(rows);
}

async function freshCreditAccountForUser(db, userId, deps) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  return await deps.dbGet(
    db,
    `
      SELECT ca.*, u.email AS user_email
      FROM user_credit_accounts ca
      LEFT JOIN users u ON u.id = ca.user_id
      WHERE ca.user_id = ?
      LIMIT 1
    `,
    [safeUserId],
  );
}

async function ensureFreshCreditAccountForUser(db, userId, deps) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  let account = await freshCreditAccountForUser(db, safeUserId, deps);
  if (account) {
    return cloneCreditAccount(account);
  }
  await ensureCreditAccount(db, safeUserId, deps);
  account = await freshCreditAccountForUser(db, safeUserId, deps);
  return cloneCreditAccount(account);
}

async function tileUnlockedAuthoritative(db, userId, family, requestedD, deps) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  const safeFamily = String(family || "").trim();
  const safeRequestedD = Number(requestedD);
  if (!safeUserId || !safeFamily || !Number.isFinite(safeRequestedD)) {
    return false;
  }
  const rows = await deps.dbAll(
    db,
    `
      SELECT tile_key
      FROM user_tile_entitlements
      WHERE user_id = ?
        AND substr(tile_key, 1, ?) = ?
    `,
    [safeUserId, safeFamily.length, safeFamily],
  );
  for (const row of rows || []) {
    const owned = parseTileKey(row && row.tile_key || "");
    if (owned && Number(owned.d) <= safeRequestedD) {
      return true;
    }
  }
  return false;
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
const CHINA_ADMIN_REGION_LABELS = new Set([
  "anhui",
  "beijing",
  "chongqing",
  "fujian",
  "gansu",
  "guangdong",
  "guangxi",
  "guizhou",
  "hainan",
  "hebei",
  "heilongjiang",
  "henan",
  "hong kong",
  "hubei",
  "hunan",
  "jiangsu",
  "jiangxi",
  "jilin",
  "liaoning",
  "macau",
  "nei mongol",
  "ningxia hui",
  "qinghai",
  "shaanxi",
  "shandong",
  "shanghai",
  "shanxi",
  "sichuan",
  "tianjin",
  "xinjiang uygur",
  "xizang",
  "yunnan",
  "zhejiang",
]);
const ADMIN_REGION_PARENT_LABEL_BY_ADM0_CODE = new Map([
  ["CAN", "Canada"],
  ["CHN", "China"],
  ["USA", "United States"],
]);

function adminRegionParentLabelForProduct(product) {
  const adm0Codes = Array.isArray(product && product.adm0_codes) ? product.adm0_codes : [];
  const adm1Codes = Array.isArray(product && product.adm1_codes) ? product.adm1_codes : [];
  for (const adm0Code of adm0Codes) {
    const safeAdm0Code = String(adm0Code || "").trim().toUpperCase();
    const parentLabel = ADMIN_REGION_PARENT_LABEL_BY_ADM0_CODE.get(safeAdm0Code);
    if (!parentLabel) {
      continue;
    }
    const prefix = `${safeAdm0Code}.`;
    if (adm1Codes.some((code) => String(code || "").trim().toUpperCase().startsWith(prefix))) {
      return parentLabel;
    }
  }
  return "";
}

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

function collapseChinaAdminRegionLabels(values) {
  let includesChinaAdminRegion = false;
  const labels = [];
  for (const value of Array.isArray(values) ? values : []) {
    const label = String(value || "").trim();
    if (!label) {
      continue;
    }
    if (CHINA_ADMIN_REGION_LABELS.has(label.toLowerCase())) {
      includesChinaAdminRegion = true;
      continue;
    }
    labels.push(label);
  }
  if (includesChinaAdminRegion) {
    labels.push("China");
  }
  return uniqueDisplayStrings(labels)
    .sort((a, b) => a.localeCompare(b));
}

function regionProductIncludedCountries(product) {
  if (!product) {
    return [];
  }
  const id = String(product.id || "").trim();
  const generated = GENERATED_REGION_PACK_DETAILS[id];
  if (generated && Array.isArray(generated.countries)) {
    return collapseChinaAdminRegionLabels(generated.countries
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
  const labels = [];
  for (const countryId of product.countries) {
    const child = regionProductById(countryId);
    const parentLabel = adminRegionParentLabelForProduct(child);
    if (parentLabel) {
      labels.push(parentLabel);
      continue;
    }
    const label = countryNameByRegionId(countryId);
    if (label) {
      labels.push(label);
    }
  }
  return collapseChinaAdminRegionLabels(labels);
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

function pointToBboxCenterDistanceDegrees(latitudeDeg, longitudeDeg, product) {
  const bbox = product && product.bbox || [];
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return Number.POSITIVE_INFINITY;
  }
  const lon = clampNumber(longitudeDeg, -180.0, 180.0);
  const lat = clampNumber(latitudeDeg, -90.0, 90.0);
  const centerLon = (Number(bbox[0]) + Number(bbox[2])) / 2.0;
  const centerLat = (Number(bbox[1]) + Number(bbox[3])) / 2.0;
  if (!Number.isFinite(centerLon) || !Number.isFinite(centerLat)) {
    return Number.POSITIVE_INFINITY;
  }
  const lonDistance = longitudeDistanceDegrees(lon, centerLon);
  const latDistance = Math.abs(lat - centerLat);
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

function regionPackMapOutlinesAssetKey(env, regionPackId) {
  const prefix = cleanR2Prefix(env);
  const id = String(regionPackId || "").trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
  const relative = `region_pack_map_outlines/${REGION_PACK_CATALOG_VERSION}/${id}.json`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function regionPackCatalogAssetKey(env) {
  const prefix = cleanR2Prefix(env);
  const relative = `region_pack_maps/${REGION_PACK_CATALOG_VERSION}/catalog.json`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function accountCountryBordersAssetKey(env) {
  const prefix = cleanR2Prefix(env);
  const relative = `account_maps/${REGION_PACK_CATALOG_VERSION}/country_borders.json`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function userProductMapStateObjectKey(env, userId, productId, pricingVersion, entitlementVersion) {
  const prefix = cleanR2Prefix(env);
  const safeUserId = String(userId || "").trim().replace(/[^A-Za-z0-9_-]/g, "");
  const safeProductId = String(productId || "").trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
  const safePricingVersion = String(pricingVersion || "").trim().replace(/[^A-Za-z0-9_.:-]/g, "_");
  const safeEntitlementVersion = String(entitlementVersion || "").trim().replace(/[^A-Za-z0-9_.:-]/g, "_");
  const relative = `user_product_map_states/${REGION_PACK_CATALOG_VERSION}/${safeUserId}/${safeProductId}/${safePricingVersion}/${safeEntitlementVersion}.json`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function userProductMapStateShardObjectKey(env, quote, level, shardIndex) {
  const prefix = cleanR2Prefix(env);
  const safeUserId = String(quote && quote.user_id || "").trim().replace(/[^A-Za-z0-9_-]/g, "");
  const safeProductId = String(quote && (quote.subject_id || quote.region_pack_id) || "").trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
  const safePricingVersion = String(quote && quote.pricing_version || "").trim().replace(/[^A-Za-z0-9_.:-]/g, "_");
  const safeEntitlementVersion = String(quote && quote.entitlement_version || "").trim().replace(/[^A-Za-z0-9_.:-]/g, "_");
  const safeQuoteId = String(quote && quote.quote_id || "").trim().replace(/[^A-Za-z0-9_-]/g, "");
  const safeLevel = Math.max(1, Number.parseInt(level || 0, 10) || 0);
  const safeShardIndex = Math.max(0, Number.parseInt(shardIndex || 0, 10) || 0);
  const relative = `user_product_map_states/${REGION_PACK_CATALOG_VERSION}/${safeUserId}/${safeProductId}/${safePricingVersion}/${safeEntitlementVersion}/shards/${safeQuoteId}/z${String(safeLevel).padStart(3, "0")}_${String(safeShardIndex).padStart(6, "0")}.json`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function isRegionPackPaidZLevel(zValue) {
  const z = Number.parseInt(zValue || 0, 10);
  return Number.isFinite(z) && REGION_PACK_PAID_Z_LEVELS.includes(z);
}

function defaultRegionPackMapLevel(levelCounts, maxInitialTiles = REGION_PACK_MAP_LEVEL_CHUNK_LIMIT) {
  const counts = levelCounts && typeof levelCounts === "object" ? levelCounts : {};
  const levels = Object.keys(counts)
    .map((level) => Number.parseInt(level, 10))
    .filter((level) => isRegionPackPaidZLevel(level))
    .sort((a, b) => a - b);
  if (!levels.length) {
    return 0;
  }
  const limit = Math.max(1, Number.parseInt(maxInitialTiles || REGION_PACK_MAP_LEVEL_CHUNK_LIMIT, 10) || REGION_PACK_MAP_LEVEL_CHUNK_LIMIT);
  for (const level of levels) {
    const count = Math.max(0, Number.parseInt(counts[String(level)] || 0, 10) || 0);
    if (count > 0 && count <= limit) {
      return level;
    }
  }
  return levels[levels.length - 1];
}

function regionPackMapBackgroundKey(env) {
  const prefix = cleanR2Prefix(env);
  const relative = `region_pack_maps/${REGION_PACK_CATALOG_VERSION}/world_wt_background.jpg`;
  return prefix ? `${prefix}/${relative}` : relative;
}

function regionPackMapProductBackgroundKey(env, regionPackId) {
  const prefix = cleanR2Prefix(env);
  const id = String(regionPackId || "").trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
  if (!id) {
    return "";
  }
  const relative = `region_pack_maps/${REGION_PACK_CATALOG_VERSION}/backgrounds_wt/${id}.jpg`;
  return prefix ? `${prefix}/${relative}` : relative;
}



const REGION_PACK_SHARED_CSS = `:root{color-scheme:light dark;--bg:#000;--panel:#1b1b1b;--subpanel:#151515;--line:#3c3c3c;--text:#eee;--muted:#aaa;--input:#262626;--table-line:#2d2d2d;--table-head:#202020;--secondary-btn:#2a2a2a;--map-bg:#0d1118;--new:#d76d62;--partial:#e2bc49;--licenced:#4fa86a;--free:#69707a;--country:#2a3748;--country-line:#98b4d8;--accent:#d9a441;--button-accent:#d9a441;--button-text:#111}
@media (prefers-color-scheme:light){:root{--bg:#fff;--panel:#fff;--subpanel:#fff;--line:#d8d8d8;--text:#1f252d;--muted:#667085;--input:#fff;--table-line:#e4e4e4;--table-head:#fff;--secondary-btn:#fff;--map-bg:#eef2f6;--country:#dbe8f2;--country-line:#45637d;--accent:#c28a21;--button-accent:#8f732f;--button-text:#fff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:22px;margin-top:4px}.card.final-price{border-color:#8f732f;box-shadow:0 0 0 1px rgba(217,164,65,.16) inset}.card.final-price b{font-size:26px}.buy-now{width:100%;font-size:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select,input{background:var(--input);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px}svg{width:100%;height:auto;background:var(--map-bg);border:1px solid var(--line);border-radius:10px}.map-shell{position:relative}.map-loading-overlay{position:absolute;inset:0;z-index:2;display:grid;place-items:center;pointer-events:none;font-weight:750;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.65)}.map-loading-overlay span{display:inline-flex;align-items:center;gap:8px;padding:10px 14px;border-radius:999px;background:rgba(7,10,16,.72);border:1px solid rgba(255,255,255,.25)}.map-loading-overlay span::before{content:"";width:13px;height:13px;border-radius:50%;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;animation:planetka-spin .75s linear infinite}@keyframes planetka-spin{to{transform:rotate(360deg)}}.map-loading-overlay.hidden{display:none}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0}.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}.new{background:var(--new)}.partial{background:var(--partial)}.licenced{background:var(--licenced)}.free{background:var(--free)}
.countries{columns:2;column-gap:26px}.countries div{break-inside:avoid;margin:2px 0}.small{font-size:13px}.error{color:#d24533}
.tile-tooltip{position:fixed;z-index:50;display:none;max-width:340px;white-space:pre-line;pointer-events:none;background:rgba(13,17,24,.95);color:#eef2f7;border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:12px;line-height:1.35;box-shadow:0 10px 30px rgba(0,0,0,.28)}@media (prefers-color-scheme:light){.tile-tooltip{background:#fff;color:#1f252d;border-color:#d8d8d8;box-shadow:0 10px 28px rgba(20,25,32,.14)}}
.upsells{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.upsell{background:var(--subpanel);border:1px solid var(--line);border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:10px}.upsell h3{margin:0;font-size:18px}.upsell p{margin:0}.upsell-map-link{display:block;width:100%;aspect-ratio:1 / 1;overflow:hidden;border:1px solid var(--line);border-radius:10px;background:var(--map-bg)}.upsell-map-link svg{width:100%;height:100%;display:block;border:0;border-radius:0;min-height:0}.upsell .button{width:100%;box-sizing:border-box;text-align:center;min-height:46px;display:flex;align-items:center;justify-content:center}.upsell .button.secondary{margin-left:0}.upsell .upsell-buy{min-height:54px}
.button{display:inline-flex;align-items:center;justify-content:center;margin-top:10px;padding:9px 12px;border-radius:8px;background:var(--button-accent);color:var(--button-text,#111);text-decoration:none;font-weight:700}.button.secondary{margin-left:8px;background:var(--secondary-btn);color:var(--text);border:1px solid var(--line)}`;

const REGION_PACK_CATALOG_CSS = `:root{color-scheme:light dark;--bg:#000;--panel:#1b1b1b;--subpanel:#151515;--line:#3c3c3c;--table-line:#2d2d2d;--table-head:#202020;--text:#eee;--muted:#aaa;--input:#262626;--accent:#d9a441;--button-accent:#d9a441;--secondary-btn:#2a2a2a;--saving:#9dd18d;--price:#f4d28d}
@media (prefers-color-scheme:light){:root{--bg:#fff;--panel:#fff;--subpanel:#fff;--line:#d8d8d8;--table-line:#e4e4e4;--table-head:#fff;--text:#1f252d;--muted:#667085;--input:#fff;--accent:#c28a21;--button-accent:#8f732f;--button-text:#fff;--secondary-btn:#fff;--saving:#2f7d3b;--price:#966915}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}h2{margin:22px 0 10px}.muted{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}
input{min-width:260px;flex:1;background:var(--input);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--subpanel);border:1px solid var(--line);border-radius:10px;overflow:visible}th,td{padding:8px 10px;border-bottom:1px solid var(--table-line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left;white-space:normal}tr:last-child td{border-bottom:0}th{position:sticky;top:0;z-index:5;color:var(--text);background:var(--table-head);font-weight:650;box-shadow:0 1px 0 var(--table-line),0 8px 14px rgba(0,0,0,.18)}thead th:first-child{border-top-left-radius:9px}thead th:last-child{border-top-right-radius:9px}.small{font-size:13px}.saving{color:var(--saving)}.price{font-weight:700;color:var(--price)}.pending{color:var(--muted);font-weight:650}
.button{display:inline-flex;align-items:center;justify-content:center;padding:7px 10px;border-radius:8px;background:var(--button-accent);color:var(--button-text,#111);text-decoration:none;font-weight:700}.button.secondary{background:var(--secondary-btn);color:var(--text);border:1px solid var(--line)}.button.disabled{opacity:.55;pointer-events:none;filter:grayscale(.25)}.empty{padding:12px;color:var(--muted)}.load-status{display:inline-grid;grid-template-columns:auto 3ch auto 3ch;column-gap:4px;align-items:baseline;font-variant-numeric:tabular-nums}.load-status .loaded{text-align:right}.load-status .total{text-align:left}.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}`;

const REGION_PACK_CHECKOUT_CSS = `:root{color-scheme:light dark;--bg:#000;--panel:#1b1b1b;--card:#151515;--line:#3c3c3c;--text:#eee;--muted:#aaa;--accent:#d9a441;--button-accent:#d9a441;--secondary-btn:#2a2a2a;--disabled:#333;--disabled-text:#888;--notice:#f2c36b;--link:#f4d28d}
@media (prefers-color-scheme:light){:root{--bg:#fff;--panel:#fff;--card:#fff;--line:#d8d8d8;--text:#1f252d;--muted:#667085;--accent:#c28a21;--button-accent:#8f732f;--button-text:#fff;--secondary-btn:#fff;--disabled:#e7e7e7;--disabled-text:#777;--notice:#936500;--link:#966915}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px}h1{margin:0 0 10px;font-size:28px;font-weight:650}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:14px}.muted{color:var(--muted)}.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:21px;margin-top:3px}.actions{display:grid;gap:10px;margin-top:14px}.button{width:100%;display:inline-flex;align-items:center;justify-content:center;padding:11px 13px;border:0;border-radius:9px;background:var(--button-accent);color:var(--button-text,#111);text-decoration:none;font-weight:750;font:inherit;cursor:pointer}.button.secondary{background:var(--secondary-btn);color:var(--text);border:1px solid var(--line)}.button.disabled{background:var(--disabled);color:var(--disabled-text);border:1px solid var(--line);cursor:not-allowed}.notice{color:var(--notice)}.links{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}.links a{color:var(--link);text-decoration:none}`;

const ACCOUNT_PAGE_CSS = `:root{color-scheme:light dark;--bg:#000;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--accent:#d9a441;--green:#4fa86a;--map-bg:#0d1118;--grid:rgba(255,255,255,.34);--country-border:rgba(230,238,248,.72);--input:#262626;--code:#f7e6b0}
@media (prefers-color-scheme:light){:root{--bg:#fff;--panel:#fff;--line:#d8d8d8;--text:#1f252d;--muted:#667085;--accent:#c28a21;--green:#3f9657;--map-bg:#eef2f6;--grid:rgba(34,44,58,.38);--country-border:rgba(42,67,91,.62);--input:#fff;--code:#6d4a00}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:30px}h2{margin:0 0 10px;font-size:20px}.muted{color:var(--muted)}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:8px 0 12px}select{background:var(--input);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px}.coverage-map{width:100%;aspect-ratio:2 / 1;background:var(--map-bg);border:1px solid var(--line);border-radius:10px}.coverage-map .country-border{fill:none;stroke:var(--country-border);stroke-width:.55;opacity:.78;vector-effect:non-scaling-stroke;pointer-events:none}.coverage-map .owned-tile{fill:var(--green);opacity:.68;stroke:none}.coverage-map .world-owned-fill{fill:var(--green);opacity:.52;stroke:none}.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0}.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}.licenced{background:var(--green)}table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:8px 6px;text-align:left;vertical-align:top}th{color:var(--accent);font-weight:650;white-space:nowrap}details summary{cursor:pointer;color:var(--accent)}.tile-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:4px 12px;margin-top:8px}code{color:var(--code)}`;

const ACCOUNT_PAGE_MAP_JS = `(() => {
  const DATA = window.PLANETKA_ACCOUNT_MAP_DATA || {};
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.getElementById("accountCoverageMap");
  const select = document.getElementById("accountLevelSelect");
  const summary = document.getElementById("accountMapSummary");
  if (!svg || !select) return;
  const bordersUrl = "/credits/account-country-borders.json?v=" + encodeURIComponent(String(DATA.country_borders_revision || DATA.map_asset_revision || Date.now()));
  let countryBorders = null;
  let countryBordersPromise = null;
  const levels = (Array.isArray(DATA.levels) && DATA.levels.length ? DATA.levels : [1, 2, 4, 8, 15, 30])
    .map((value) => Math.max(1, Number(value) || 1))
    .filter((value, index, values) => values.indexOf(value) === index)
    .sort((a, b) => a - b);
  function zoomLabel(level) {
    const index = Math.max(0, levels.indexOf(Number(level)));
    return "Zoom " + (index + 1) + (index === 0 ? " - closest" : "");
  }
  function el(name, attrs) {
    const node = document.createElementNS(NS, name);
    for (const key of Object.keys(attrs || {})) node.setAttribute(key, String(attrs[key]));
    return node;
  }
  function tileForRow(row) {
    const x = Number(row && row.x);
    const y = Number(row && row.y);
    const z = Number(row && row.z);
    const d = Number(row && row.d);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z) || z <= 0) return null;
    return {
      key: String(row && row.key || ""),
      x,
      y,
      z,
      d: Number.isFinite(d) ? d : 0,
    };
  }
  const ownedByLevel = new Map();
  for (const row of Array.isArray(DATA.tiles) ? DATA.tiles : []) {
    const tile = tileForRow(row);
    if (!tile) continue;
    if (!ownedByLevel.has(tile.z)) ownedByLevel.set(tile.z, new Map());
    const levelMap = ownedByLevel.get(tile.z);
    const cellKey = tile.x + "," + tile.y + "," + tile.z;
    const existing = levelMap.get(cellKey) || { ...tile, dLevels: [] };
    if (tile.d && !existing.dLevels.includes(tile.d)) existing.dLevels.push(tile.d);
    if (tile.key && !existing.key) existing.key = tile.key;
    levelMap.set(cellKey, existing);
  }
  function projectedPoint(point) {
    const lon = Number(Array.isArray(point) ? point[0] : NaN);
    const lat = Number(Array.isArray(point) ? point[1] : NaN);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
    return [lon + 180, 90 - lat, lon];
  }
  function borderPathForRing(ring) {
    let path = "";
    let previousLon = null;
    let started = false;
    for (const point of Array.isArray(ring) ? ring : []) {
      const projected = projectedPoint(point);
      if (!projected) {
        started = false;
        previousLon = null;
        continue;
      }
      const [x, y, lon] = projected;
      if (previousLon !== null && Math.abs(lon - previousLon) > 180) {
        // Avoid drawing long antimeridian connector lines across the map.
        started = false;
      }
      path += (started ? "L" : "M") + x.toFixed(2) + " " + y.toFixed(2);
      started = true;
      previousLon = lon;
    }
    return path;
  }
  function drawCountryBorders() {
    const outlines = Array.isArray(countryBorders && countryBorders.outlines) ? countryBorders.outlines : [];
    if (!outlines.length) return;
    const group = el("g", { class: "country-borders", "aria-hidden": "true" });
    for (const outline of outlines) {
      for (const ring of Array.isArray(outline && outline.polygons) ? outline.polygons : []) {
        const path = borderPathForRing(ring);
        if (path) {
          group.appendChild(el("path", { class: "country-border", d: path }));
        }
      }
    }
    svg.appendChild(group);
  }
  function loadCountryBorders() {
    if (countryBorders || countryBordersPromise) return countryBordersPromise;
    countryBordersPromise = fetch(bordersUrl, { cache: "force-cache" })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => {
        if (payload && Array.isArray(payload.outlines)) {
          countryBorders = payload;
          render(Number(select.value || levels[0]));
        }
      })
      .catch(() => null);
    return countryBordersPromise;
  }
  function setGridPattern(level) {
    const defs = el("defs", {});
    const patternId = "accountGrid" + String(level).replace(/[^0-9]/g, "");
    const pattern = el("pattern", { id: patternId, width: level, height: level, patternUnits: "userSpaceOnUse" });
    pattern.appendChild(el("path", {
      d: "M " + level + " 0 L 0 0 0 " + level,
      fill: "none",
      stroke: "var(--grid)",
      "stroke-width": Math.max(0.05, Math.min(0.18, level * 0.018)),
    }));
    defs.appendChild(pattern);
    svg.appendChild(defs);
    return patternId;
  }
  function render(level) {
    svg.replaceChildren();
    svg.setAttribute("viewBox", "0 0 360 180");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.appendChild(el("rect", { x: 0, y: 0, width: 360, height: 180, fill: "var(--map-bg)" }));
    svg.appendChild(el("image", {
      href: "/credits/region-pack-map-background.jpg?v=" + encodeURIComponent(String(DATA.map_asset_revision || Date.now())),
      x: 0,
      y: 0,
      width: 360,
      height: 180,
      preserveAspectRatio: "none",
    }));
    const patternId = setGridPattern(level);
    let shown = 0;
    if (DATA.world_unlocked) {
      const fill = el("rect", { class: "world-owned-fill", x: 0, y: 0, width: 360, height: 180 });
      fill.appendChild(el("title", {})).textContent = "Complete Full Quality tile coverage";
      svg.appendChild(fill);
      shown = Math.ceil(360 / level) * Math.ceil(180 / level);
    } else {
      const levelMap = ownedByLevel.get(Number(level)) || new Map();
      shown = levelMap.size;
      for (const tile of levelMap.values()) {
        const rect = el("rect", {
          class: "owned-tile",
          x: tile.x,
          y: 180 - tile.y - tile.z,
          width: tile.z,
          height: tile.z,
        });
        const title = el("title", {});
        const detail = tile.dLevels.length ? "Files licenced for this grid cell: " + tile.dLevels.length : "Licenced";
        title.textContent = (tile.key || "Licenced tile") + "\\n" + detail;
        rect.appendChild(title);
        svg.appendChild(rect);
      }
    }
    drawCountryBorders();
    svg.appendChild(el("rect", { x: 0, y: 0, width: 360, height: 180, fill: "url(#" + patternId + ")", "pointer-events": "none" }));
    if (summary) {
      const truncated = !DATA.world_unlocked && DATA.truncated ? " Display is limited for browser performance." : "";
      summary.textContent = DATA.world_unlocked
        ? "Complete coverage shown at " + zoomLabel(level) + "."
        : shown.toLocaleString("en-US") + " licenced tile" + (shown === 1 ? "" : "s") + " shown at " + zoomLabel(level) + "." + truncated;
    }
  }
  for (const level of levels) {
    const option = document.createElement("option");
    option.value = String(level);
    option.textContent = zoomLabel(level);
    select.appendChild(option);
  }
  if (levels.includes(Number(DATA.default_level))) {
    select.value = String(Number(DATA.default_level));
  }
  select.addEventListener("change", () => render(Number(select.value)));
  render(Number(select.value || levels[0]));
  loadCountryBorders();
})();`;

const REGION_PACK_STATIC_MAP_JS = `const DATA=window.PLANETKA_REGION_PACK_DATA||{};
const NS="http://www.w3.org/2000/svg";
const int=(v)=>Math.max(0,Math.round(Number(v||0)||0));
const fmtCents=(v)=>"€"+(int(v)/100).toFixed(2);
const assetCache=new Map();
const assetVersion=encodeURIComponent(String(DATA.map_asset_revision||DATA.catalog_version||DATA.token||Date.now()));
const MAP_BG="/credits/region-pack-map-background.jpg?v="+assetVersion;
const outlinesUrl=(id)=>"/credits/region-pack-map-outlines?region_pack_id="+encodeURIComponent(String(id||""))+"&v="+assetVersion;
const miniOutlinesUrl="/credits/account-country-borders.json?v="+assetVersion;
const currentToken=encodeURIComponent(DATA.token||"");
const currentPackIdEncoded=encodeURIComponent(DATA.asset_id||DATA.region_pack&&DATA.region_pack.id||"");
const currentCatalog=DATA.catalog_mode?"&catalog=1":"";
function productMapBgHref(id){const safe=encodeURIComponent(String(id||"").trim());return safe?"/credits/region-pack-map-background.jpg?region_pack_id="+safe+"&v="+assetVersion:""}
function esc(value){return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\"/g,"&quot;")}
function countryName(value){return typeof value==="object"&&value?String(value.name||value.COUNTRY||value.NAME_1||value.GID_0||""):String(value||"")}
const CHINA_ADMIN_LABELS=new Set(["anhui","beijing","chongqing","fujian","gansu","guangdong","guangxi","guizhou","hainan","hebei","heilongjiang","henan","hong kong","hubei","hunan","jiangsu","jiangxi","jilin","liaoning","macau","nei mongol","ningxia hui","qinghai","shaanxi","shandong","shanghai","shanxi","sichuan","tianjin","xinjiang uygur","xizang","yunnan","zhejiang"]);
const US_ADMIN_LABELS=new Set(["alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware","district of columbia","florida","georgia","hawaii","idaho","illinois","indiana","iowa","kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan","minnesota","mississippi","missouri","montana","nebraska","nevada","new hampshire","new jersey","new mexico","new york","north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island","south carolina","south dakota","tennessee","texas","utah","vermont","virginia","washington","west virginia","wisconsin","wyoming"]);
const CANADA_ADMIN_LABELS=new Set(["alberta","british columbia","manitoba","new brunswick","newfoundland and labrador","northwest territories","nova scotia","nunavut","ontario","prince edward island","québec","quebec","saskatchewan","yukon"]);
function currentPackId(){return String(DATA.asset_id||DATA.region_pack&&DATA.region_pack.id||"").trim().toLowerCase()}
function collapsedIncludedLabel(key){const id=currentPackId();if(CHINA_ADMIN_LABELS.has(key))return "China";if((id==="north_america"||id==="united_states")&&US_ADMIN_LABELS.has(key))return "United States";if((id==="north_america"||id==="canada")&&CANADA_ADMIN_LABELS.has(key))return "Canada";return ""}
function uniqueCountryNames(values){const seen=new Set(),out=[];for(const entry of Array.isArray(values)?values:[]){let label=countryName(entry).trim();let key=label.toLowerCase();const collapsed=collapsedIncludedLabel(key);if(collapsed){label=collapsed;key=label.toLowerCase()}if(!label||seen.has(key))continue;seen.add(key);out.push(label)}return out.sort((a,b)=>a.localeCompare(b))}
function parseTileKey(key){const m=/x([0-9]{3})_y([0-9]{3})_z([0-9]{3})_d([0-9]{3})/i.exec(String(key||""));return m?{key:m[0],x:Number(m[1]),y:Number(m[2]),z:Number(m[3]),d:Number(m[4])}:null}
function family(parsed){return parsed?"x"+String(parsed.x).padStart(3,"0")+"_y"+String(parsed.y).padStart(3,"0")+"_z"+String(parsed.z).padStart(3,"0"):""}
function tileSort(a,b){const pa=parseTileKey(a.tile_key),pb=parseTileKey(b.tile_key),fa=family(pa),fb=family(pb);return fa===fb?(Number(pa&&pa.d||0)-Number(pb&&pb.d||0)):fa<fb?-1:1}
function buildOwnedFamilies(){const map=new Map();const source=Array.isArray(DATA.owned_tile_keys)&&DATA.owned_tile_keys.length?DATA.owned_tile_keys:(DATA.owned_tiles||[]);for(const row of source){const key=typeof row==="string"?row:row&&row.tile_key;const p=parseTileKey(key);const f=family(p);if(!p||!f)continue;if(!map.has(f))map.set(f,new Set());map.get(f).add(Number(p.d))}return map}
async function loadAsset(id){const safe=String(id||"").trim();if(assetCache.has(safe))return assetCache.get(safe);const res=await fetch("/credits/region-pack-map-asset?region_pack_id="+encodeURIComponent(safe)+"&v="+assetVersion,{cache:"reload"});if(!res.ok)throw new Error("map_asset_"+res.status);const asset=await res.json();assetCache.set(safe,asset);return asset}
function normaliseTile(tile,owned){const p=parseTileKey(tile&&tile.tile_key);const f=family(p);const ownedDs=owned.get(f)||new Set();const gross=int(tile&&((tile.gross_cents!==undefined?tile.gross_cents:tile.full_price_cents)));const globallyFree=!!(tile&&tile.globally_free)||gross<=0;let status="new";if(DATA.world_full_quality_unlocked||DATA.product_full_quality_unlocked||Array.from(ownedDs).some((d)=>Number(d)<=Number(p&&p.d||0))){status="licenced"}else if(globallyFree){status="free"}else if(Array.from(ownedDs).some((d)=>Number(d)>Number(p&&p.d||0))){status="partial"}const lonMin=Number(tile&&tile.lon_min),lonMax=Number(tile&&tile.lon_max),latMin=Number(tile&&tile.lat_min),latMax=Number(tile&&tile.lat_max);return{...tile,tile_key:p?p.key:String(tile&&tile.tile_key||""),x:p?p.x:null,y:p?p.y:null,z:p?p.z:null,d:p?p.d:null,lon_min:Number.isFinite(lonMin)?lonMin:(p?p.x-180:null),lon_max:Number.isFinite(lonMax)?lonMax:(p?p.x-180+p.z:null),lat_min:Number.isFinite(latMin)?latMin:(p?p.y-90:null),lat_max:Number.isFinite(latMax)?latMax:(p?p.y-90+p.z:null),full_price_cents:gross,gross_cents:gross,status}}
function computeAsset(asset){const owned=buildOwnedFamilies();const rows=(asset.tiles||[]).map((tile)=>normaliseTile(tile,owned)).filter((tile)=>tile.tile_key&&Number.isFinite(tile.x)&&Number.isFinite(tile.y)&&Number.isFinite(tile.z)).sort(tileSort);const levels=Array.from(new Set(rows.map((row)=>Number(row.z)).filter(Number.isFinite))).sort((a,b)=>a-b);return{asset,rows,levels}}
function normaliseStoredTile(tile){const p=parseTileKey(tile&&tile.tile_key);const lonMin=Number(tile&&tile.lon_min),lonMax=Number(tile&&tile.lon_max),latMin=Number(tile&&tile.lat_min),latMax=Number(tile&&tile.lat_max);return{...tile,tile_key:p?p.key:String(tile&&tile.tile_key||""),display_tile_key:String(tile&&tile.display_tile_key||""),x:p?p.x:null,y:p?p.y:null,z:p?p.z:null,d:p?p.d:null,lon_min:Number.isFinite(lonMin)?lonMin:(p?p.x-180:null),lon_max:Number.isFinite(lonMax)?lonMax:(p?p.x-180+p.z:null),lat_min:Number.isFinite(latMin)?latMin:(p?p.y-90:null),lat_max:Number.isFinite(latMax)?latMax:(p?p.y-90+p.z:null),status:String(tile&&tile.status||"free")}}
function computeViewModel(asset){const state=DATA.map_state_ready&&DATA.map_state&&typeof DATA.map_state==="object"?DATA.map_state:null;if(state&&state.on_demand&&state.level_tile_counts&&typeof state.level_tile_counts==="object"){const levels=(Array.isArray(state.levels)&&state.levels.length?state.levels:Object.keys(state.level_tile_counts||{})).map(Number).filter(Number.isFinite).sort((a,b)=>a-b);return{asset:{...asset,bounds:state.bounds||asset.bounds,outlines:Array.isArray(state.outlines)?state.outlines:asset.outlines,included_countries:Array.isArray(state.included_countries)?state.included_countries:asset.included_countries,region_pack:state.region_pack||asset.region_pack},rows:[],levels,onDemand:true,sharded:false,state}}if(state&&state.sharded&&state.level_shards&&typeof state.level_shards==="object"){const levels=(Array.isArray(state.levels)&&state.levels.length?state.levels:Object.keys(state.level_shards||{})).map(Number).filter(Number.isFinite).sort((a,b)=>a-b);return{asset:{...asset,bounds:state.bounds||asset.bounds,outlines:Array.isArray(state.outlines)?state.outlines:asset.outlines,included_countries:Array.isArray(state.included_countries)?state.included_countries:asset.included_countries,region_pack:state.region_pack||asset.region_pack},rows:[],levels,onDemand:false,sharded:true,state}}if(state&&Array.isArray(state.tiles)&&state.tiles.length){const rows=state.tiles.map(normaliseStoredTile).filter((tile)=>tile.tile_key&&Number.isFinite(tile.x)&&Number.isFinite(tile.y)&&Number.isFinite(tile.z)).sort(tileSort);const levels=(Array.isArray(state.levels)&&state.levels.length?state.levels:Array.from(new Set(rows.map((row)=>Number(row.z)).filter(Number.isFinite)))).map(Number).filter(Number.isFinite).sort((a,b)=>a-b);return{asset:{...asset,bounds:state.bounds||asset.bounds,outlines:Array.isArray(state.outlines)?state.outlines:asset.outlines,included_countries:Array.isArray(state.included_countries)?state.included_countries:asset.included_countries,region_pack:state.region_pack||asset.region_pack},rows,levels,onDemand:false,sharded:false,state}}return{asset,rows:[],levels:[],onDemand:false,sharded:false,state:null}}
function priceBreakdownText(tile){const full=int(tile.full_price_cents!==undefined?tile.full_price_cents:tile.gross_cents);const already=int(tile.already_licenced_cents);const partial=int(tile.partial_licence_credit_cents);const discount=int(tile.discount_cents);const final=int(tile.final_price_cents!==undefined?tile.final_price_cents:tile.price_cents);const pct=int(tile.discount_percent!==undefined?tile.discount_percent:DATA.summary&&DATA.summary.discount_percent);const lines=["Full Price: "+fmtCents(full)];if(already>0)lines.push("Licenced: - "+fmtCents(already));if(partial>0)lines.push("Partially licenced: - "+fmtCents(partial));if(discount>0)lines.push("Volume Discount ("+pct+"%): - "+fmtCents(discount));lines.push("Final Price: "+fmtCents(final));return lines.join("\\n")}
function tileDisplayKey(tile){if(tile&&tile.display_tile_key)return String(tile.display_tile_key);const p=parseTileKey(tile&&tile.tile_key);if(!p)return String(tile&&tile.tile_key||"");const d=Math.max(1,Number(p.z)||1);return "x"+String(p.x).padStart(3,"0")+"_y"+String(p.y).padStart(3,"0")+"_z"+String(p.z).padStart(3,"0")+"_d"+String(d).padStart(3,"0")}
function fmtLat(value){const n=Number(value);if(!Number.isFinite(n))return "—";const rounded=Math.round(Math.abs(n));return rounded+"° "+(n<0?"S":"N")}
function fmtLon(value){const n=Number(value);if(!Number.isFinite(n))return "—";const rounded=Math.round(Math.abs(n));return rounded+"° "+(n<0?"W":"E")}
function fmtLand(value){const n=Number(value);return Number.isFinite(n)?Math.round(Math.max(0,n)).toLocaleString("en-US")+" km²":"—"}
function spatialResolutionText(tile){const p=parseTileKey(tile&&tile.tile_key);const d=Math.max(1,Number(p&&p.z||tile&&tile.d||1)||1);return (10*d).toLocaleString("en-US",{maximumFractionDigits:0})+" m"}
function tileTooltipText(tile,statusText){const base=tileDisplayKey(tile)+"\\nLatitude: "+fmtLat(tile.lat_min)+" to "+fmtLat(tile.lat_max)+"\\nLongitude: "+fmtLon(tile.lon_min)+" to "+fmtLon(tile.lon_max)+"\\nSpatial Resolution: "+spatialResolutionText(tile)+"\\nLand: "+fmtLand(tile.billable_land_km2||0)+"\\nStatus: "+statusText;return statusText==="outside this scene"?base:base+"\\n"+priceBreakdownText(tile)}
function zoomLabel(level){const list=(window.PLANETKA_MAP_ZOOM_LEVELS&&window.PLANETKA_MAP_ZOOM_LEVELS.length?window.PLANETKA_MAP_ZOOM_LEVELS:[Number(level)]).map(Number);const i=Math.max(0,list.indexOf(Number(level)));return "Zoom "+(i+1)+(i===0?" - closest":"")}
function currentBuyHref(){if(DATA.scene_detail&&DATA.scene_checkout_url)return String(DATA.scene_checkout_url);const q=encodeURIComponent(String(DATA.quote&&DATA.quote.quote_id||""));return currentPackIdEncoded&&q?"/credits/region-pack-checkout?token="+currentToken+"&region_pack_id="+currentPackIdEncoded+currentCatalog+"&quote_id="+q:""}
function renderCards(){const s=DATA.summary;if(!s){const label=DATA.price_pending?"Price updating":"Price unavailable";const detail=DATA.price_pending?"Please wait a few moments.":"Reopen this page from Blender or the data-pack list.";document.getElementById("cards").innerHTML='<div class="card final-price"><span>'+label+'</span><b>'+detail+'</b></div>';return}const partialTiles=Number(s.partial_licence_tiles||0);const alreadyTiles=Number(s.already_licenced_tiles||0)+partialTiles;const alreadyValue=int(s.already_licenced_deduction_cents)+int(s.partial_licence_credit_cents);const discountValue=int(s.discount_cents);const newTiles=Math.max(0,Number(s.new_tiles||0)-partialTiles);const cards=[["New Tiles / Total Tiles",newTiles+" / "+Number(s.total_tiles||0)],["Full Price",fmtCents(s.full_price_cents)]];if(alreadyValue>0)cards.push(["Already Licenced",alreadyTiles+" tiles (-"+fmtCents(alreadyValue)+")"]);if(discountValue>0)cards.push(["Volume Discount",Number(s.discount_percent||0)+"% (-"+fmtCents(discountValue)+")"]);if(DATA.scene_detail&&int(s.custom_scene_licence_cents)>0)cards.push([s.scene_custom_licence_label||"Custom scene-specific licence",fmtCents(s.custom_scene_licence_cents)]);const buy=currentBuyHref()?'<a class="button buy-now" href="'+currentBuyHref()+'">'+(int(s.price_cents)>0?"Buy Now":"Licence Now")+'</a>':"";cards.push(["Final Price",fmtCents(s.price_cents),buy]);document.getElementById("cards").innerHTML=cards.map((c)=>'<div class="card '+(c[0]==="Final Price"?"final-price":"")+'"><span>'+esc(c[0])+'</span><b>'+esc(c[1])+'</b>'+(c[2]||"")+'</div>').join("")}
function frameForBounds(rawBounds,width,minHeight,maxHeight,padSize){const b=rawBounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const minLon=Number.isFinite(Number(b.min_lon))?Number(b.min_lon):-10,minLat=Number.isFinite(Number(b.min_lat))?Number(b.min_lat):35,maxLon=Number.isFinite(Number(b.max_lon))?Number(b.max_lon):30,maxLat=Number.isFinite(Number(b.max_lat))?Number(b.max_lat):48;const lonSpan=Math.max(1e-6,maxLon-minLon),latSpan=Math.max(1e-6,maxLat-minLat),innerW=Math.max(1,width-padSize*2);const naturalH=Math.round(latSpan*(innerW/lonSpan))+padSize*2,height=Math.max(minHeight,Math.min(maxHeight,naturalH)),innerH=Math.max(1,height-padSize*2),scale=Math.min(innerW/lonSpan,innerH/latSpan),usedW=lonSpan*scale,usedH=latSpan*scale;return{bounds:{min_lon:minLon,min_lat:minLat,max_lon:maxLon,max_lat:maxLat},width,height,scale,ox:(width-usedW)/2,oy:(height-usedH)/2}}
let currentFrame=frameForBounds({min_lon:-10,min_lat:35,max_lon:30,max_lat:48},1000,320,820,20),W=currentFrame.width,H=currentFrame.height;
function setBounds(bounds){currentFrame=frameForBounds(bounds||currentFrame.bounds,1000,320,820,20);W=currentFrame.width;H=currentFrame.height}
function xy(lon,lat){return[currentFrame.ox+(lon-currentFrame.bounds.min_lon)*currentFrame.scale,currentFrame.oy+(currentFrame.bounds.max_lat-lat)*currentFrame.scale]}
function el(name,attrs){const node=document.createElementNS(NS,name);for(const k in attrs||{})node.setAttribute(k,String(attrs[k]));return node}
let activeTileTooltip=null;function tileTooltip(){let node=document.getElementById("tileTooltip");if(!node){node=document.createElement("div");node.id="tileTooltip";node.className="tile-tooltip";document.body.appendChild(node)}return node}function moveTileTooltip(event){if(!activeTileTooltip)return;const pad=14;activeTileTooltip.style.left=Math.min(window.innerWidth-activeTileTooltip.offsetWidth-pad,event.clientX+pad)+"px";activeTileTooltip.style.top=Math.min(window.innerHeight-activeTileTooltip.offsetHeight-pad,event.clientY+pad)+"px"}function showTileTooltip(text,event){const node=tileTooltip();node.textContent=text;node.style.display="block";activeTileTooltip=node;moveTileTooltip(event)}function hideTileTooltip(){if(activeTileTooltip){activeTileTooltip.style.display="none";activeTileTooltip=null}}function attachTileTooltip(node,text){node.addEventListener("pointerenter",event=>showTileTooltip(text,event));node.addEventListener("pointermove",moveTileTooltip);node.addEventListener("pointerleave",hideTileTooltip)}
function addMapBackground(svg,project,width,height,id,bounds){svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#0d1118"}));const productHref=productMapBgHref(id);if(productHref){const img=el("image",{href:productHref,x:0,y:0,width,height,preserveAspectRatio:"none",opacity:"1.0"});img.addEventListener("error",()=>img.remove());svg.appendChild(img)}else{const tl=project(-180,90),br=project(180,-90);svg.appendChild(el("image",{href:MAP_BG,x:tl[0],y:tl[1],width:br[0]-tl[0],height:br[1]-tl[1],preserveAspectRatio:"none",opacity:"1.0"}))}svg.appendChild(el("rect",{x:0,y:0,width,height,fill:"#05070a",opacity:"0.0"}))}
function pathFor(poly){return(poly||[]).map((pt,i)=>{const p=xy(pt[0],pt[1]);return(i?"L":"M")+p[0].toFixed(2)+" "+p[1].toFixed(2)}).join(" ")}
function drawOutlineRingPath(ring){let path="",previousLon=null,started=false;for(const point of Array.isArray(ring)?ring:[]){const lon=Number(point&&point[0]),lat=Number(point&&point[1]);if(!Number.isFinite(lon)||!Number.isFinite(lat)){started=false;previousLon=null;continue}if(previousLon!==null&&Math.abs(lon-previousLon)>180)started=false;const p=xy(lon,lat);path+=(started?"L":"M")+p[0].toFixed(2)+" "+p[1].toFixed(2);started=true;previousLon=lon}return path}
async function loadProductOutlines(asset){const current=Array.isArray(asset&&asset.outlines)?asset.outlines:[];if(current.length)return current;const id=asset&&asset.region_pack&&asset.region_pack.id||currentPackId();if(!id)return current;try{const response=await fetch(outlinesUrl(id),{cache:"force-cache"});if(!response.ok)return current;const payload=await response.json();const outlines=Array.isArray(payload&&payload.outlines)?payload.outlines:[];if(outlines.length)asset.outlines=outlines;return outlines}catch(_error){return current}}
function drawProductOutlines(svg,asset){const outlines=Array.isArray(asset&&asset.outlines)?asset.outlines:[];if(!svg||!outlines.length)return;const group=el("g",{class:"product-outlines","aria-hidden":"true"});for(const outline of outlines){for(const ring of Array.isArray(outline&&outline.polygons)?outline.polygons:[]){const path=drawOutlineRingPath(ring);if(!path)continue;const p=el("path",{d:path,fill:"none",stroke:"var(--country-line)","stroke-width":"0.7",opacity:"0.72"});const t=el("title",{});t.textContent=outline.name||"";p.appendChild(t);group.appendChild(p)}}svg.appendChild(group)}
const shardRowsCache=new Map();
const shardRowsLoading=new Map();
const levelRowsCache=new Map();
const levelRowsLoading=new Map();
let mapRenderSeq=0;
function shardCacheKey(level){return String(Number(level)||level||"")}
function mapStateShardUrl(level,index){const q=encodeURIComponent(String(DATA.quote&&DATA.quote.quote_id||""));return"/credits/region-pack-map-state-shard?token="+currentToken+"&region_pack_id="+currentPackIdEncoded+currentCatalog+"&quote_id="+q+"&level="+encodeURIComponent(String(level))+"&shard="+encodeURIComponent(String(index))}
function mapLevelChunkUrl(level,cursor){const q=encodeURIComponent(String(DATA.quote&&DATA.quote.quote_id||""));let url="/credits/region-pack-map-level-chunk?token="+currentToken+"&region_pack_id="+currentPackIdEncoded+currentCatalog+"&quote_id="+q+"&level="+encodeURIComponent(String(level));if(cursor&&cursor.family_key&&cursor.tile_key){url+="&cursor_family_key="+encodeURIComponent(cursor.family_key)+"&cursor_d="+encodeURIComponent(String(cursor.d||0))+"&cursor_tile_key="+encodeURIComponent(cursor.tile_key)}return url}
function mapCounts(){return{total:0,newCount:0,licencedCount:0,partialCount:0,freeCount:0}}
function setMapLoading(active,text){const overlay=document.getElementById("mapLoadingOverlay");if(!overlay)return;overlay.classList.toggle("hidden",!active);const label=overlay.querySelector("span");if(label&&text)label.textContent=text}
function completeMapLoading(){window.setTimeout(()=>setMapLoading(false),120)}
function updateMapSummary(level,counts,loaded,expected,complete){const summary=document.getElementById("levelSummary");if(complete){summary.textContent=counts.total+" tiles at "+zoomLabel(level)+" · new "+counts.newCount+" · already licenced "+(counts.licencedCount+counts.partialCount)+" · free "+counts.freeCount;document.getElementById("mapStatus").textContent="Map loaded.";completeMapLoading();return}summary.textContent="Loading "+zoomLabel(level)+" tiles... "+Number(loaded||0).toLocaleString("en-US")+" / "+Number(expected||0).toLocaleString("en-US");document.getElementById("mapStatus").textContent="Loading map tiles... "+Number(loaded||0).toLocaleString("en-US")+" / "+Number(expected||0).toLocaleString("en-US");setMapLoading(true,"Loading map...")}
function drawMapBase(vm){const svg=document.getElementById("map");svg.replaceChildren();svg.setAttribute("viewBox","0 0 "+W+" "+H);svg.setAttribute("preserveAspectRatio","xMidYMid meet");addMapBackground(svg,xy,W,H,vm.asset&&vm.asset.region_pack&&vm.asset.region_pack.id,vm.asset&&vm.asset.bounds);drawProductOutlines(svg,vm.asset);return svg}
function appendTileRows(svg,level,sourceRows,counts){const rows=(Array.isArray(sourceRows)?sourceRows:[]).filter((row)=>Number(row.z)===Number(level));for(const tile of rows){const a=xy(tile.lon_min,tile.lat_max),b=xy(tile.lon_max,tile.lat_min);const contextOnly=tile.status==="context";const lower=tile.status==="lower_resolution";const cls=contextOnly?"none":(tile.status==="new"?"var(--new)":((tile.status==="partial"||lower)?"var(--partial)":(tile.status==="licenced"?"var(--licenced)":"var(--free)")));if(!contextOnly){if(tile.status==="new"||lower)counts.newCount++;else if(tile.status==="partial")counts.partialCount++;else if(tile.status==="licenced")counts.licencedCount++;else counts.freeCount++}counts.total++;const r=el("rect",{x:a[0],y:a[1],width:Math.max(1,b[0]-a[0]),height:Math.max(1,b[1]-a[1]),fill:cls,stroke:"#fff","stroke-width":contextOnly?"0.35":"0.45",opacity:contextOnly?"0.26":((tile.status==="new"||tile.status==="partial"||lower)?"0.58":"0.43")});const statusText=contextOnly?"outside this scene":(lower?"new lower resolution tile":(tile.status==="partial"?"partially licenced":tile.status));attachTileTooltip(r,tileTooltipText(tile,statusText));svg.appendChild(r)}}
function drawMapRows(vm,level,sourceRows){const svg=drawMapBase(vm);const counts=mapCounts();appendTileRows(svg,level,sourceRows,counts);updateMapSummary(level,counts,counts.total,counts.total,true)}
async function loadShardedRows(vm,level,onChunk){const key=shardCacheKey(level);if(shardRowsCache.has(key))return shardRowsCache.get(key);if(shardRowsLoading.has(key))return shardRowsLoading.get(key);const shards=vm&&vm.state&&vm.state.level_shards&&vm.state.level_shards[key]||[];const promise=(async()=>{const rows=[];for(const [index,shard] of shards.entries()){const res=await fetch(mapStateShardUrl(level,shard.index!==undefined?shard.index:index),{cache:"no-store"});if(!res.ok)throw new Error("map_state_shard_"+res.status);const item=await res.json();const chunk=(Array.isArray(item&&item.tiles)?item.tiles:[]).map(normaliseStoredTile).filter((tile)=>tile.tile_key&&Number.isFinite(tile.x)&&Number.isFinite(tile.y)&&Number.isFinite(tile.z));rows.push(...chunk);if(typeof onChunk==="function")onChunk(chunk,rows.length)}rows.sort(tileSort);shardRowsCache.set(key,rows);shardRowsLoading.delete(key);return rows})().catch((error)=>{shardRowsLoading.delete(key);throw error});shardRowsLoading.set(key,promise);return promise}
function shardedRowsIfLoaded(vm,level){return shardRowsCache.get(shardCacheKey(level))||null}
function onDemandRowsIfLoaded(vm,level){return levelRowsCache.get(shardCacheKey(level))||null}
async function loadOnDemandRows(vm,level,onChunk){const key=shardCacheKey(level);if(levelRowsCache.has(key))return levelRowsCache.get(key);if(levelRowsLoading.has(key))return levelRowsLoading.get(key);const expected=Math.max(0,Number(vm&&vm.state&&vm.state.level_tile_counts&&vm.state.level_tile_counts[key]||0)||0);const promise=(async()=>{const rows=[];let cursor=null;let guard=0;for(;;){const res=await fetch(mapLevelChunkUrl(level,cursor),{cache:"no-store"});if(!res.ok)throw new Error("map_level_chunk_"+res.status);const payload=await res.json();const chunk=(Array.isArray(payload&&payload.tiles)?payload.tiles:[]).map(normaliseStoredTile).filter((tile)=>tile.tile_key&&Number.isFinite(tile.x)&&Number.isFinite(tile.y)&&Number.isFinite(tile.z));rows.push(...chunk);if(typeof onChunk==="function")onChunk(chunk,rows.length,expected);cursor=payload&&payload.next_cursor||null;guard+=1;if(!cursor||guard>1000)break;}rows.sort(tileSort);if(expected>0&&rows.length===0)throw new Error("map_level_empty_"+key);levelRowsCache.set(key,rows);levelRowsLoading.delete(key);return rows})().catch((error)=>{levelRowsLoading.delete(key);throw error});levelRowsLoading.set(key,promise);return promise}
function renderMap(vm,level){const seq=++mapRenderSeq;const key=shardCacheKey(level);const expected=Math.max(0,Number(vm&&vm.state&&vm.state.level_tile_counts&&vm.state.level_tile_counts[key]||0)||0);document.getElementById("mapStatus").className="muted small";if(vm.onDemand){const cached=onDemandRowsIfLoaded(vm,level);if(cached){drawMapRows(vm,level,cached);return}const svg=drawMapBase(vm),counts=mapCounts();updateMapSummary(level,counts,0,expected,false);loadOnDemandRows(vm,level,(chunk,loaded,total)=>{if(seq!==mapRenderSeq)return;appendTileRows(svg,level,chunk,counts);updateMapSummary(level,counts,loaded,total,false)}).then((rows)=>{if(seq===mapRenderSeq)drawMapRows(vm,level,rows)}).catch((error)=>{if(seq!==mapRenderSeq)return;console.warn("Planetka map level failed",error);setMapLoading(false);document.getElementById("mapStatus").className="error small";document.getElementById("mapStatus").textContent="Map tiles failed to load. Please refresh this page.";});return}if(vm.sharded){const cached=shardedRowsIfLoaded(vm,level);if(cached){drawMapRows(vm,level,cached);return}const shards=vm&&vm.state&&vm.state.level_shards&&vm.state.level_shards[key]||[];const svg=drawMapBase(vm),counts=mapCounts();updateMapSummary(level,counts,0,expected||0,false);loadShardedRows(vm,level,(chunk,loaded)=>{if(seq!==mapRenderSeq)return;appendTileRows(svg,level,chunk,counts);updateMapSummary(level,counts,loaded,expected||loaded,false)}).then((rows)=>{if(seq===mapRenderSeq)drawMapRows(vm,level,rows)}).catch((error)=>{if(seq!==mapRenderSeq)return;console.warn("Planetka map shard failed",error);setMapLoading(false);document.getElementById("mapStatus").className="error small";document.getElementById("mapStatus").textContent="Map tiles failed to load. Please refresh this page.";});return}drawMapRows(vm,level,vm.rows)}
function miniFrame(bounds){return frameForBounds(bounds,1000,320,820,20)}
function miniXY(frame,lon,lat){return[frame.ox+(lon-frame.bounds.min_lon)*frame.scale,frame.oy+(frame.bounds.max_lat-lat)*frame.scale]}
let miniOutlinesPromise=null;async function loadMiniOutlines(){if(!miniOutlinesPromise){miniOutlinesPromise=fetch(miniOutlinesUrl,{cache:"force-cache"}).then((res)=>res.ok?res.json():null).then((payload)=>Array.isArray(payload&&payload.outlines)?payload.outlines:[]).catch(()=>[])}return miniOutlinesPromise}
function drawMiniOutlines(svg,frame,asset){const outlines=Array.isArray(asset&&asset.outlines)?asset.outlines:[];if(!outlines.length)return;const group=el("g",{class:"product-outlines","aria-hidden":"true"});for(const outline of outlines){for(const ring of Array.isArray(outline&&outline.polygons)?outline.polygons:[]){let path="",previousLon=null,started=false;for(const point of Array.isArray(ring)?ring:[]){const lon=Number(point&&point[0]),lat=Number(point&&point[1]);if(!Number.isFinite(lon)||!Number.isFinite(lat)){started=false;previousLon=null;continue}if(previousLon!==null&&Math.abs(lon-previousLon)>180)started=false;const p=miniXY(frame,lon,lat);path+=(started?"L":"M")+p[0].toFixed(2)+" "+p[1].toFixed(2);started=true;previousLon=lon}if(path)group.appendChild(el("path",{d:path,fill:"none",stroke:"var(--country-line)","stroke-width":"0.7",opacity:"0.72"}))}}svg.appendChild(group)}
function renderMiniMap(svg,vm){const asset=vm&&vm.asset||{};const b=asset.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const frame=miniFrame(b),w=frame.width,h=frame.height;svg.setAttribute("viewBox","0 0 "+w+" "+h);svg.style.aspectRatio="1 / 1";svg.setAttribute("preserveAspectRatio","xMidYMid meet");svg.replaceChildren();const bgId=asset&&asset.region_pack&&asset.region_pack.id||"";addMapBackground(svg,(lon,lat)=>miniXY(frame,lon,lat),w,h,bgId,b);drawMiniOutlines(svg,frame,asset);const first=vm&&vm.levels&&vm.levels.length?vm.levels[0]:null;for(const tile of (Array.isArray(vm&&vm.rows)?vm.rows:[]).filter((row)=>Number(row.z)===Number(first))){const a=miniXY(frame,tile.lon_min,tile.lat_max),c=miniXY(frame,tile.lon_max,tile.lat_min);const lower=tile.status==="lower_resolution";const cls=tile.status==="new"?"var(--new)":((tile.status==="partial"||lower)?"var(--partial)":(tile.status==="licenced"?"var(--licenced)":"var(--free)"));svg.appendChild(el("rect",{x:a[0],y:a[1],width:Math.max(1,c[0]-a[0]),height:Math.max(1,c[1]-a[1]),fill:cls,stroke:"#fff","stroke-width":"0.5",opacity:(tile.status==="new"||tile.status==="partial"||lower)?"0.58":"0.43"}))}}
async function loadMiniMap(id,q){const url="/credits/region-pack-mini-map?token="+currentToken+"&region_pack_id="+encodeURIComponent(String(id||""))+currentCatalog+(q?"&quote_id="+encodeURIComponent(String(q)):"");const res=await fetch(url,{cache:"no-store"});if(!res.ok)throw new Error("mini_map_"+res.status);return res.json()}
async function renderUpsells(){const serverUpsells=Array.isArray(DATA.upsells)?DATA.upsells:[];const grid=document.getElementById("upsellGrid");if(!grid||!serverUpsells.length)return;const token=encodeURIComponent(DATA.token||"");const catalog="&catalog=1";for(const card of serverUpsells){try{const idRaw=card.asset_id||card.region_pack&&card.region_pack.id||"";const pack=card.region_pack||{};const summary=card.summary||null;if(!idRaw&&!pack.id)continue;const id=encodeURIComponent(pack.id||idRaw);const div=document.createElement("div");div.className="upsell";const title=document.createElement("h3");title.textContent=pack.name||"Data Pack";div.appendChild(title);const q=String(card.quote_id||"");const quoteParam=q?"&quote_id="+encodeURIComponent(q):"";const detailHref="/credits/region-pack-map?token="+token+"&region_pack_id="+id+catalog+quoteParam;const mapLink=document.createElement("a");mapLink.href=detailHref;mapLink.className="upsell-map-link";mapLink.setAttribute("aria-label","View map for "+(pack.name||"data pack"));const map=document.createElementNS(NS,"svg");mapLink.appendChild(map);div.appendChild(mapLink);renderMiniMap(map,{asset:{bounds:pack.bounds||null,region_pack:{id:pack.id||idRaw,name:pack.name||"Data Pack"},outlines:[]},rows:[],levels:[]});Promise.all([loadMiniMap(pack.id||idRaw,q),loadMiniOutlines()]).then(([mini,outlines])=>{const rows=(Array.isArray(mini&&mini.tiles)?mini.tiles:[]).map(normaliseStoredTile);renderMiniMap(map,{asset:{bounds:mini.bounds||pack.bounds||null,region_pack:mini.region_pack||{id:pack.id||idRaw,name:pack.name||"Data Pack"},outlines:Array.isArray(outlines)?outlines:[]},rows,levels:[Number(mini&&mini.level||0)||null].filter(Boolean)})}).catch((error)=>console.warn("Planetka upsell mini map failed",card,error));const meta=document.createElement("p");meta.className="muted small";if(summary){const alreadyValue=int(summary.already_licenced_deduction_cents)+int(summary.partial_licence_credit_cents);const bits=["Full "+fmtCents(summary.full_price_cents)];if(alreadyValue>0)bits.push("Already -"+fmtCents(alreadyValue));if(int(summary.discount_cents)>0)bits.push("Discount "+Number(summary.discount_percent||0)+"% (-"+fmtCents(summary.discount_cents)+")");bits.push("Final "+fmtCents(summary.price_cents));meta.textContent=bits.join(" · ");}else{meta.textContent="Price updating";}div.appendChild(meta);if(summary&&q&&int(summary.price_cents)>0){const checkout=document.createElement("a");checkout.className="button upsell-buy";checkout.href="/credits/region-pack-checkout?token="+token+"&region_pack_id="+id+catalog+"&quote_id="+encodeURIComponent(q);checkout.textContent=(pack.name||"Pack")+" ("+fmtCents(summary.price_cents)+")";div.appendChild(checkout);}const detail=document.createElement("a");detail.className="button secondary";detail.href=detailHref;detail.textContent="View map";div.appendChild(detail);grid.appendChild(div);document.getElementById("upsellsPanel").style.display=""}catch(error){console.warn("Planetka upsell map failed",card,error)}}}
function serverMapAsset(){const state=DATA.map_state_ready&&DATA.map_state&&typeof DATA.map_state==="object"?DATA.map_state:null;if(state&&state.on_demand){return{region_pack:state.region_pack||DATA.region_pack||{},bounds:state.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48},outlines:Array.isArray(state.outlines)?state.outlines:[],included_countries:Array.isArray(state.included_countries)?state.included_countries:[],tiles:[]}}return null}
async function init(){try{setMapLoading(true,"Loading map...");const asset=serverMapAsset()||await loadAsset(DATA.asset_id);const titlePrefix=String(DATA.title_prefix||DATA.success&&DATA.success.context_title_prefix||"").trim();const explicitTitle=String(DATA.page_title||"").trim();document.getElementById("pageTitle").textContent=explicitTitle||((titlePrefix?titlePrefix+": ":"")+(asset.region_pack.name||"Data Pack")+" Full Quality Pack");const vm=computeViewModel(asset);renderCards();setBounds(vm.asset.bounds);const countries=uniqueCountryNames(vm.asset.included_countries);if(countries.length){document.getElementById("countries").innerHTML=countries.map((c)=>"<div>"+esc(c)+"</div>").join("");document.getElementById("countriesPanel").style.display=""}const select=document.getElementById("levelSelect");select.replaceChildren();let levels=vm.levels.length?vm.levels:[1];const preferred=Number(vm&&vm.state&&vm.state.default_level);if(DATA.scene_detail&&levels.includes(preferred))levels=[preferred];window.PLANETKA_MAP_ZOOM_LEVELS=levels;for(const z of levels){const o=document.createElement("option");o.value=String(z);o.textContent=zoomLabel(z);select.appendChild(o)}const defaultLevel=levels.includes(preferred)?preferred:levels[0];select.value=String(defaultLevel);if(DATA.scene_detail&&select.closest("label"))select.closest("label").style.display="none";else select.addEventListener("change",()=>renderMap(vm,Number(select.value)));await loadProductOutlines(vm.asset);renderMap(vm,Number(select.value||defaultLevel));if(!DATA.map_state_ready){document.getElementById("mapStatus").textContent=DATA.price_pending?"Price and map are updating. Please wait a few moments.":"Map is updating. Please wait a few moments.";if(DATA.map_pending)setTimeout(()=>window.location.reload(),6000);return}renderUpsells()}catch(error){console.warn("Planetka region-pack map failed",error);document.getElementById("mapStatus").className="error small";document.getElementById("mapStatus").textContent="Map failed to load. Please reopen this page from Blender."}}
init();`;

const REGION_PACK_PAGE_ASSETS = new Map([
  ["region-pack-dynamic-map.css", { content_type: "text/css; charset=utf-8", body: REGION_PACK_SHARED_CSS }],
  ["region-pack-dynamic-map.js", { content_type: "application/javascript; charset=utf-8", body: REGION_PACK_STATIC_MAP_JS }],
  ["region-pack-map.css", { content_type: "text/css; charset=utf-8", body: REGION_PACK_SHARED_CSS }],
  ["region-pack-map.js", { content_type: "application/javascript; charset=utf-8", body: REGION_PACK_STATIC_MAP_JS }],
]);

export function handleCreditRegionPackPageAsset(request, env, deps) {
  const timing = createEndpointTimer("credits.page_asset");
  const url = new URL(request.url);
  const fileName = String(url.pathname || "").split("/").pop() || "";
  const asset = REGION_PACK_PAGE_ASSETS.get(fileName);
  if (!asset) {
    return withEndpointTiming(deps.json({ ok: false, error: "page_asset_not_found" }, 404, env), timing, env, { asset: fileName });
  }
  const response = new Response(asset.body, {
    status: 200,
    headers: {
      "Content-Type": asset.content_type,
      "Cache-Control": "public, max-age=86400",
      ...corsHeaders(env),
    },
  });
  timing.mark("asset");
  return withEndpointTiming(response, timing, env, { asset: fileName });
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
      };
    })
    .filter(Boolean);
}

function regionPackStaticMapPayload(product, token, account, ownedRows, options = {}) {
  const success = options && options.success && typeof options.success === "object" ? options.success : null;
  const quote = options && options.quote && typeof options.quote === "object"
    ? options.quote
    : null;
  const mapState = options && options.mapState && typeof options.mapState === "object"
    ? options.mapState
    : null;
  const storedUpsells = mapState && Array.isArray(mapState.upsells) ? mapState.upsells : null;
  const upsells = storedUpsells || (Array.isArray(options && options.upsells)
    ? options.upsells
      .map((entry) => {
        const upsellProduct = entry && entry.product || null;
        const upsellQuote = entry && entry.quote || null;
        const upsellSummary = upsellQuote && upsellQuote.summary ? upsellQuote.summary : null;
        if (!upsellProduct || !upsellSummary) {
          return null;
        }
        return {
          region_pack: regionProductPublicPayload(upsellProduct),
          asset_id: String(upsellProduct && upsellProduct.id || ""),
          quote_id: String(upsellQuote && upsellQuote.quote_id || ""),
          summary: upsellSummary,
        };
      })
      .filter(Boolean)
    : []);
  const explicitSimilarPackIds = Array.isArray(options && options.similarPackIds)
    ? options.similarPackIds.map((entry) => String(entry || "").trim()).filter(Boolean)
    : null;
  const similarPackIds = explicitSimilarPackIds
    || (upsells.length
      ? upsells.map((entry) => String(entry && entry.asset_id || "").trim()).filter(Boolean)
      : null);
  const explicitOwnedTileKeys = Array.isArray(options && options.ownedTileKeys)
    ? normalizeTileKeys(options.ownedTileKeys)
    : null;
  return {
    ok: true,
    static_asset_mode: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
    token: String(token || ""),
    catalog_mode: Boolean(options && options.catalogMode),
    asset_id: String(product && product.id || ""),
    region_pack: regionProductPublicPayload(product),
    quote: quote ? {
      quote_id: String(quote.quote_id || ""),
      amount_cents: integerCents(quote.amount_cents),
      currency: String(quote.currency || "eur"),
      pricing_version: String(quote.pricing_version || ""),
      entitlement_version: String(quote.entitlement_version || ""),
    } : null,
    summary: quote && quote.summary ? quote.summary : null,
    quote_status: String(options && options.quoteStatus || (quote ? "ready" : "missing")),
    price_pending: Boolean(options && options.pricePending),
    map_state_status: String(options && options.mapStateStatus || mapState && "ready" || "not_requested"),
    map_state_ready: Boolean(mapState),
    map_pending: Boolean(options && options.mapPending),
    map_state: mapState,
    ...(similarPackIds && similarPackIds.length ? { similar_pack_ids: similarPackIds } : {}),
    upsells,
    upsell_title: String(options && options.upsellTitle || "").trim(),
    owned_tiles: [],
    owned_tile_keys: explicitOwnedTileKeys
      ? explicitOwnedTileKeys
      : ownedTilePayloadRows(ownedRows).map((row) => row.tile_key).filter(Boolean),
    world_full_quality_unlocked: isWorldFullQualityUnlocked(account),
    product_full_quality_unlocked: Boolean(
      options && options.productUnlocked
      || mapState && mapState.product_full_quality_unlocked
    ),
    title_prefix: String(options && options.titlePrefix || success && success.context_title_prefix || "").trim(),
    page_title: String(options && options.pageTitle || "").trim(),
    scene_detail: Boolean(options && options.sceneDetail),
    scene_checkout_url: String(options && options.sceneCheckoutUrl || "").trim(),
    success,
  };
}

async function relatedRegionPackQuoteEntries(db, product, userId, account, _pricingOwnershipContext, deps, options = {}) {
  const limit = Math.max(0, Number.parseInt(options && options.limit || 6, 10) || 6);
  const includePending = Boolean(options && options.includePending);
  const candidates = await relatedRegionProducts(db, product, deps, limit);
  const quoteResults = await materializedRegionPackQuoteResults(db, userId, candidates, account, deps, {
    fastTrack: Boolean(options && options.fastTrack),
    jobRound: options && Object.prototype.hasOwnProperty.call(options, "jobRound") ? options.jobRound : 0,
    priority: options && Object.prototype.hasOwnProperty.call(options, "priority") ? options.priority : 40,
    triggerType: String(options && options.triggerType || "related_offer_requested"),
    staleReason: String(options && options.staleReason || "related_offer_quote_not_ready"),
    sourceProductId: normalizedRegionPackProductId(product),
  });
  const entries = candidates
    .map((candidate) => {
      const entry = quoteResults.get(normalizedRegionPackProductId(candidate));
      if (entry && entry.quote) {
        return { product: candidate, quote: entry.quote };
      }
      return includePending ? { product: candidate, quote: null } : null;
    })
    .filter(Boolean);
  return entries;
}

async function relatedRegionPackReadyQuoteEntries(db, product, userId, account, deps, options = {}) {
  const limit = Math.max(0, Number.parseInt(options && options.limit || 6, 10) || 6);
  const candidates = await relatedRegionProducts(db, product, deps, limit);
  if (!candidates.length) {
    return [];
  }
  const candidateIds = candidates
    .map((candidate) => String(candidate && candidate.id || "").trim().toLowerCase())
    .filter(Boolean);
  const quoteRows = await loadEffectiveUserProductQuoteRows(db, userId, account, candidateIds, deps, { includeMapState: false });
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  return candidates
    .map((candidate) => {
      const candidateId = String(candidate && candidate.id || "").trim().toLowerCase();
      const row = quoteRows.get(candidateId) || null;
      if (productQuoteStatus(row, pricingVersion, entitlementVersion) !== "ready") {
        return null;
      }
      const quote = userProductQuoteFromRow(row);
      return quote && quote.summary ? { product: candidate, quote } : null;
    })
    .filter(Boolean);
}

async function relevantSceneProductPackReadyQuoteEntries(db, contextProduct, userId, account, deps, options = {}) {
  if (!contextProduct) {
    return [];
  }
  const limit = Math.max(0, Number.parseInt(options && options.limit || 8, 10) || 8);
  const candidates = [contextProduct, ...await relatedRegionProducts(db, contextProduct, deps, limit)];
  const seen = new Set();
  const uniqueCandidates = [];
  for (const candidate of candidates) {
    const id = String(candidate && candidate.id || "").trim().toLowerCase();
    if (!id || seen.has(id) || isHiddenRegionProduct(candidate)) {
      continue;
    }
    seen.add(id);
    uniqueCandidates.push(candidate);
  }
  const quoteRows = await loadEffectiveUserProductQuoteRows(
    db,
    userId,
    account,
    uniqueCandidates.map((candidate) => String(candidate && candidate.id || "").trim().toLowerCase()).filter(Boolean),
    deps,
    { includeMapState: false },
  );
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  return uniqueCandidates
    .map((candidate) => {
      const candidateId = String(candidate && candidate.id || "").trim().toLowerCase();
      const row = quoteRows.get(candidateId) || null;
      if (productQuoteStatus(row, pricingVersion, entitlementVersion) !== "ready") {
        return { product: candidate, quote: null };
      }
      const quote = userProductQuoteFromRow(row);
      return { product: candidate, quote: quote && quote.summary ? quote : null };
    })
    .filter(Boolean);
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

function pointRegionOfferTileKey(latitudeDeg, longitudeDeg) {
  const lon = clampNumber(longitudeDeg, -180.0, 180.0);
  const lat = clampNumber(latitudeDeg, -90.0, 90.0);
  const x = Math.max(0, Math.min(359, Math.floor(lon + 180.0)));
  const y = Math.max(0, Math.min(179, Math.floor(lat + 90.0)));
  return regionTileKey(x, y, 1, 1);
}

async function pointInRegionProduct(db, product, latitudeDeg, longitudeDeg, deps) {
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
  if (inOutlines !== null) {
    return inOutlines;
  }
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "country" || type === "admin_region") {
    // Some countries span the antimeridian and have huge bboxes. The generated
    // z001 membership avoids offering distant country packs.
    return await regionPackProductContainsTileKey(db, product, pointRegionOfferTileKey(lat, lon), deps);
  }
  return true;
}

async function suggestedRegionProductsForPoint(db, latitudeDeg, longitudeDeg, deps) {
  const matches = [];
  for (const product of REGION_PRODUCTS) {
    if (isHiddenRegionProduct(product)) {
      continue;
    }
    if (await pointInRegionProduct(db, product, latitudeDeg, longitudeDeg, deps)) {
      matches.push(product);
    }
  }
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
    .sort((a, b) => (
      pointToBboxDistanceDegrees(latitudeDeg, longitudeDeg, a) - pointToBboxDistanceDegrees(latitudeDeg, longitudeDeg, b)
      || pointToBboxCenterDistanceDegrees(latitudeDeg, longitudeDeg, a) - pointToBboxCenterDistanceDegrees(latitudeDeg, longitudeDeg, b)
      || bboxArea(a) - bboxArea(b)
      || String(a.name || "").localeCompare(String(b.name || ""))
    ));
  const country = countryMatches.length ? countryMatches[0] : null;
  for (const product of countryMatches.slice(0, 4)) {
    addProduct(product);
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

function bboxDistanceDegrees(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length < 4 || b.length < 4) {
    return Number.POSITIVE_INFINITY;
  }
  if (bboxIntersects(a, b)) {
    return 0;
  }
  const aMinLon = Math.min(Number(a[0]), Number(a[2]));
  const aMaxLon = Math.max(Number(a[0]), Number(a[2]));
  const aMinLat = Math.min(Number(a[1]), Number(a[3]));
  const aMaxLat = Math.max(Number(a[1]), Number(a[3]));
  const bMinLon = Math.min(Number(b[0]), Number(b[2]));
  const bMaxLon = Math.max(Number(b[0]), Number(b[2]));
  const bMinLat = Math.min(Number(b[1]), Number(b[3]));
  const bMaxLat = Math.max(Number(b[1]), Number(b[3]));
  const latGap = aMaxLat < bMinLat ? bMinLat - aMaxLat : bMaxLat < aMinLat ? aMinLat - bMaxLat : 0;
  const lonGapDirect = aMaxLon < bMinLon ? bMinLon - aMaxLon : bMaxLon < aMinLon ? aMinLon - bMaxLon : 0;
  const lonGap = Math.min(lonGapDirect, Math.max(0, 360.0 - lonGapDirect));
  return Math.sqrt(latGap * latGap + lonGap * lonGap);
}

function bboxLongitudeSpanDegrees(bbox) {
  if (!Array.isArray(bbox) || bbox.length < 4) {
    return 360.0;
  }
  const minLon = Math.min(Number(bbox[0]), Number(bbox[2]));
  const maxLon = Math.max(Number(bbox[0]), Number(bbox[2]));
  if (!Number.isFinite(minLon) || !Number.isFinite(maxLon)) {
    return 360.0;
  }
  return Math.max(0, maxLon - minLon);
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

async function regionCountryProductsForTileKeys(db, tileKeys, latitudeDeg, longitudeDeg, deps, limit = 8) {
  const parsedTiles = finestPaidTilesForRegionOffers(tileKeys);
  if (!parsedTiles.length) {
    return [];
  }
  const lookupKeys = Array.from(new Set(parsedTiles.map((parsed) => parsed.key).filter(Boolean)));
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
      if (await regionPackProductContainsTileKey(db, product, key, deps)) {
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

async function suggestedRegionProductsForContext(db, latitudeDeg, longitudeDeg, tileKeys = [], deps) {
  const pointProducts = await suggestedRegionProductsForPoint(db, latitudeDeg, longitudeDeg, deps);
  const tileCountryProducts = await regionCountryProductsForTileKeys(db, tileKeys, latitudeDeg, longitudeDeg, deps, 8);
  const hasTileContext = normalizeTileKeys(tileKeys).length > 0;
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
  const isBroadProduct = (product) => {
    const type = String(product && product.type || "").trim().toLowerCase();
    return type === "macro_region" || type === "continent" || type === "world";
  };

  if (!hasTileContext) {
    for (const product of pointProducts.filter(isBroadProduct)) {
      addProduct(product);
    }
    for (const product of pointProducts.filter(isCountryProduct)) {
      addProduct(product);
    }
    return selected.slice(0, 8);
  }

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
  const useCache = seenProductIds.size === 0;
  if (useCache && REGION_PRODUCT_COUNTRY_ID_SET_CACHE.has(id)) {
    return new Set(REGION_PRODUCT_COUNTRY_ID_SET_CACHE.get(id));
  }
  seenProductIds.add(id);
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "country" || type === "admin_region") {
    const result = new Set([id]);
    if (useCache) {
      REGION_PRODUCT_COUNTRY_ID_SET_CACHE.set(id, Array.from(result));
    }
    return result;
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
  if (useCache) {
    REGION_PRODUCT_COUNTRY_ID_SET_CACHE.set(id, Array.from(result));
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

function isCountryOptionRegionProduct(product) {
  const id = String(product && product.id || "").trim();
  const type = String(product && product.type || "").trim().toLowerCase();
  if (COUNTRY_LIKE_REGION_PRODUCT_IDS.has(id)) {
    return true;
  }
  return type === "country" && !(Array.isArray(product && product.adm1_codes) && product.adm1_codes.length);
}

function isCountryIdSetSubset(candidateSet, parentSet) {
  if (!candidateSet.size || !parentSet.size) {
    return false;
  }
  for (const id of candidateSet) {
    if (!parentSet.has(id)) {
      return false;
    }
  }
  return true;
}

function includedCountryRegionProducts(product) {
  const currentId = String(product && product.id || "").trim();
  const currentRank = regionProductRank(product);
  if (!currentId || currentRank <= 1) {
    return [];
  }
  const parentSet = regionProductCountryIdSet(product);
  if (!parentSet.size) {
    return [];
  }
  return REGION_PRODUCTS
    .filter((candidate) => {
      const candidateId = String(candidate && candidate.id || "").trim();
      if (!candidateId || candidateId === currentId || isHiddenRegionProduct(candidate)) {
        return false;
      }
      if (!isCountryOptionRegionProduct(candidate)) {
        return false;
      }
      return isCountryIdSetSubset(regionProductCountryIdSet(candidate), parentSet);
    })
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
}

function includedAreaRegionProducts(product) {
  const currentId = String(product && product.id || "").trim();
  const currentRank = regionProductRank(product);
  if (!currentId || currentRank !== 3) {
    return [];
  }
  const parentSet = regionProductCountryIdSet(product);
  if (!parentSet.size) {
    return [];
  }
  return REGION_PRODUCTS
    .filter((candidate) => {
      const candidateId = String(candidate && candidate.id || "").trim();
      if (!candidateId || candidateId === currentId || isHiddenRegionProduct(candidate)) {
        return false;
      }
      if (
        COUNTRY_LIKE_REGION_PRODUCT_IDS.has(candidateId)
        && !(currentId === "north_america" && NORTH_AMERICA_SIMILAR_COUNTRY_LIKE_IDS.has(candidateId))
      ) {
        return false;
      }
      if (regionProductRank(candidate) !== 2) {
        return false;
      }
      return isCountryIdSetSubset(regionProductCountryIdSet(candidate), parentSet);
    })
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
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

function directChildRegionProducts(product) {
  const currentId = String(product && product.id || "").trim();
  if (!currentId || !Array.isArray(product && product.countries)) {
    return [];
  }
  const seen = new Set();
  const result = [];
  for (const childId of product.countries) {
    const id = String(childId || "").trim();
    if (!id || id === currentId || seen.has(id)) {
      continue;
    }
    seen.add(id);
    const child = regionProductById(id);
    if (!child || isHiddenRegionProduct(child)) {
      continue;
    }
    result.push(child);
  }
  return result.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
}

async function relatedSimilarRegionProducts(db, product, deps, limit = 3) {
  const currentRank = regionProductRank(product);
  const currentId = String(product && product.id || "").trim();
  const currentBbox = product && product.bbox || [];
  const currentIsCountryOption = isCountryOptionRegionProduct(product) && currentRank !== 3;
  if (!currentId || (!currentIsCountryOption && currentRank !== 1 && currentRank !== 2) || !Array.isArray(currentBbox) || currentBbox.length < 4) {
    return [];
  }
  const matches = [];
  for (const candidate of REGION_PRODUCTS) {
      const candidateId = String(candidate && candidate.id || "").trim();
      if (!candidateId || candidateId === currentId || isHiddenRegionProduct(candidate)) {
        continue;
      }
      if (currentIsCountryOption) {
        const candidateBbox = candidate && candidate.bbox || [];
        const distance = bboxDistanceDegrees(currentBbox, candidateBbox);
        if (!Number.isFinite(distance) || distance > REGION_SIMILAR_COUNTRY_MAX_DISTANCE_DEG) {
          continue;
        }
        if (
          isCountryOptionRegionProduct(candidate)
          && await regionProductsShareZ001Footprint(db, product, candidate, deps)
        ) {
          matches.push(candidate);
        }
        continue;
      }
      if (regionProductRank(candidate) !== currentRank) {
        continue;
      }
      const candidateBbox = candidate && candidate.bbox || [];
      if (
        bboxLongitudeSpanDegrees(candidateBbox) >= 180.0
        && !await regionProductsShareZ001Footprint(db, product, candidate, deps)
      ) {
        continue;
      }
      const distance = bboxDistanceDegrees(currentBbox, candidateBbox);
      if (Number.isFinite(distance) && distance <= REGION_SIMILAR_COUNTRY_MAX_DISTANCE_DEG) {
        matches.push(candidate);
      }
  }
  matches
    .sort((a, b) => (
      bboxDistanceDegrees(currentBbox, a && a.bbox || []) - bboxDistanceDegrees(currentBbox, b && b.bbox || [])
      || productSpecificityScore(a) - productSpecificityScore(b)
      || bboxArea(a) - bboxArea(b)
      || String(a.name || "").localeCompare(String(b.name || ""))
    ));
  const parsedLimit = Number(limit);
  return Number.isFinite(parsedLimit) && parsedLimit > 0
    ? matches.slice(0, Math.floor(parsedLimit))
    : matches;
}

async function relatedRegionProducts(db, product, deps, limit = 6) {
  const currentRank = regionProductRank(product);
  if (currentRank >= 4) {
    return REGION_PRODUCTS
      .filter((candidate) => (
        String(candidate && candidate.type || "").trim().toLowerCase() === "continent"
        && !isHiddenRegionProduct(candidate)
      ))
      .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
  }
  const result = [];
  const seen = new Set([String(product && product.id || "").trim()]);
  const add = (candidate) => {
    const id = String(candidate && candidate.id || "").trim();
    if (!id || seen.has(id) || isHiddenRegionProduct(candidate)) {
      return;
    }
    seen.add(id);
    result.push(candidate);
  };
  const isCountryOptionPage = isCountryOptionRegionProduct(product) && currentRank !== 3;
  const similarLimit = currentRank === 1 || isCountryOptionPage ? 8 : (currentRank === 2 ? 12 : 3);
  for (const candidate of await relatedSimilarRegionProducts(db, product, deps, similarLimit)) {
    add(candidate);
  }
  if (isCountryOptionRegionProduct(product)) {
    for (const candidate of directChildRegionProducts(product)) {
      add(candidate);
    }
  }
  const includedAreas = includedAreaRegionProducts(product);
  for (const candidate of includedAreas) {
    add(candidate);
  }
  const includeCountries = currentRank !== 3;
  const includedCountries = includeCountries ? includedCountryRegionProducts(product) : [];
  for (const candidate of includedCountries) {
    add(candidate);
  }
  for (const candidate of relatedHigherRegionProducts(product, 6)) {
    add(candidate);
  }
  if (currentRank === 3) {
    add(regionProductById("world"));
  }
  if (currentRank === 1 || isCountryOptionPage) {
    return result;
  }
  if (includedAreas.length || includedCountries.length) {
    return result;
  }
  return result.slice(0, Math.max(0, Number.parseInt(limit, 10) || 6));
}

async function isSameOrRelatedHigherRegionProduct(db, baseProduct, requestedProduct, deps) {
  const baseId = String(baseProduct && baseProduct.id || "").trim();
  const requestedId = String(requestedProduct && requestedProduct.id || "").trim();
  if (!baseId || !requestedId) {
    return false;
  }
  if (baseId === requestedId) {
    return true;
  }
  return (await relatedRegionProducts(db, baseProduct, deps, 12))
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

function compareRegionTileKeys(a, b) {
  const parsedA = parseTileKey(a);
  const parsedB = parseTileKey(b);
  const familyA = tileFamilyKey(parsedA);
  const familyB = tileFamilyKey(parsedB);
  if (familyA !== familyB) {
    return familyA < familyB ? -1 : 1;
  }
  return Number(parsedA && parsedA.d || 0) - Number(parsedB && parsedB.d || 0);
}

function safeOwnedEntriesForFamily(ownedByFamily, family, familyRows = []) {
  const valueByKey = new Map((Array.isArray(familyRows) ? familyRows : [])
    .map((row) => [normalizeTileKey(row && (row.key || row.tile_key) || ""), integerCents(row && row.gross_cents)]));
  const source = ownedByFamily instanceof Map ? ownedByFamily.get(family) : [];
  return Array.isArray(source)
    ? source.map((entry) => ({
      key: normalizeTileKey(entry && entry.key),
      d: Number(entry && entry.d),
      value: valueByKey.get(normalizeTileKey(entry && entry.key))
        || integerCents(entry && (entry.value_cents ?? entry.gross_cents))
        || centsForEur(entry && (entry.value_eur ?? entry.gross_price_eur ?? entry.price_eur))
        || 0,
    })).filter((entry) => entry.key && Number.isFinite(entry.d))
    : [];
}

function estimateRegionPackFamilyRows(rows, ownedEntries = []) {
  const initialEntries = Array.isArray(ownedEntries)
    ? ownedEntries.map((entry) => ({ ...entry }))
    : [];
  const workingEntries = initialEntries.map((entry) => ({ ...entry }));
  let alreadyLicencedCount = 0;
  let grossCents = 0;
  let alreadyLicencedGrossCents = 0;
  let partialLicenceCount = 0;
  let partialLicenceCreditCents = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;

  for (const row of rows || []) {
    const parsed = row && row.parsed;
    if (!parsed) {
      continue;
    }
    const grossCentsForTile = Math.max(0, Number.parseInt(row.gross_cents || 0, 10) || 0);
    const globallyFree = Boolean(row.globally_free);
    const previouslyCovered = initialEntries.some((entry) => Number(entry.d) <= Number(parsed.d));
    const coveredForCharge = workingEntries.some((entry) => Number(entry.d) <= Number(parsed.d));
    let coarserCreditCents = 0;
    let initialCoarserCreditCents = 0;
    for (const entry of workingEntries) {
      if (Number(entry.d) > Number(parsed.d)) {
        coarserCreditCents = Math.max(coarserCreditCents, Number(entry.value || 0) || 0);
      }
    }
    for (const entry of initialEntries) {
      if (Number(entry.d) > Number(parsed.d)) {
        initialCoarserCreditCents = Math.max(initialCoarserCreditCents, Number(entry.value || 0) || 0);
      }
    }
    const chargeCents = (globallyFree || coveredForCharge)
      ? 0
      : Math.max(0, grossCentsForTile - coarserCreditCents);
    const partialCreditCents = (!globallyFree && !previouslyCovered && !coveredForCharge)
      ? Math.max(0, Math.min(grossCentsForTile, initialCoarserCreditCents))
      : 0;
    if (previouslyCovered) {
      alreadyLicencedCount += 1;
      if (!globallyFree) {
        alreadyLicencedGrossCents += grossCentsForTile;
      }
      continue;
    }
    if (partialCreditCents > 0) {
      partialLicenceCount += 1;
      partialLicenceCreditCents += partialCreditCents;
    }
    if (chargeCents > 0) {
      grossCents += chargeCents;
      paidTileCount += 1;
      workingEntries.push({ key: row.key, d: Number(parsed.d), value: grossCentsForTile });
    } else {
      freeTileCount += 1;
    }
  }

  return {
    gross_cents: grossCents,
    already_licenced_count: alreadyLicencedCount,
    already_licenced_gross_cents: alreadyLicencedGrossCents,
    partial_licence_count: partialLicenceCount,
    partial_licence_credit_cents: partialLicenceCreditCents,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
  };
}

async function regionProductOwnedFamilyRows(db, product, ownedByFamily, deps, options = {}) {
  if (!product || !(ownedByFamily instanceof Map) || ownedByFamily.size <= 0) {
    return new Map();
  }
  const families = new Map();
  const rows = await regionPackTileRowsForProductFamilies(db, product, Array.from(ownedByFamily.keys()), deps);
  for (const row of rows) {
    const productFamily = String(row && row.family || "");
    if (!productFamily || !ownedByFamily.has(productFamily)) {
      continue;
    }
    if (!families.has(productFamily)) {
      families.set(productFamily, []);
    }
    families.get(productFamily).push(row);
  }
  return families;
}

function regionPackVisibleNewTileCount(chargeableTileCount, freeTileCount) {
  const chargeable = Math.max(0, Number.parseInt(chargeableTileCount || 0, 10) || 0);
  const free = Math.max(0, Number.parseInt(freeTileCount || 0, 10) || 0);
  return chargeable > 0 ? chargeable + free : 0;
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
    partial_licence_tile_count: 0,
    partial_licence_credit_eur: 0,
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
    aggregate.partial_licence_tile_count += Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0);
    aggregate.partial_licence_credit_eur = normalizeCreditAmount(
      aggregate.partial_licence_credit_eur + normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
    );
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

async function estimateRegionPackSummaryWithOwned(db, product, account, ownedByFamily, deps, options = {}) {
  const summary = await regionProductPricingSummaryD1(db, product, deps);
  if (!summary) {
    return { error: "missing_region_pack_summary" };
  }
  const discountPercent = regionProductDiscountPercent(product);
  if (isWorldFullQualityUnlocked(account)) {
    const fullCents = integerCents(summary.gross_cents);
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
      gross_cents: 0,
      gross_price_eur: 0,
      gross_price_cents: 0,
      discount_eur: 0,
      discount_cents: 0,
      already_licenced_gross_eur: centsToEur(fullCents),
      already_licenced_gross_cents: fullCents,
      already_licenced_saving_eur: centsToEur(fullCents),
      already_licenced_saving_cents: fullCents,
      credits: 0,
      credits_cents: 0,
      price_eur: 0,
      price_cents: 0,
      paid_tile_count: 0,
      free_tile_count: summary.tile_count,
      tile_count: summary.tile_count,
      unlicenced_tile_count: 0,
      charged_tile_count: 0,
      new_tile_count: 0,
      new_tiles: [],
      excluded_tiles: new Array(summary.licensable_tile_count).fill(null),
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
      tiles: [],
    };
  }
  if (!(ownedByFamily instanceof Map) || ownedByFamily.size <= 0) {
    const amounts = discountedRegionPackAmountCents(summary.gross_cents, discountPercent);
    return {
      ok: true,
      summary_estimate: true,
      static_catalog_estimate: true,
      region_pack: regionProductPublicPayload(product),
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      discount_percent: discountPercent,
      gross_eur: amounts.gross,
      gross_cents: amounts.gross_cents,
      gross_price_eur: amounts.gross,
      gross_price_cents: amounts.gross_cents,
      discount_eur: amounts.discount,
      discount_cents: amounts.discount_cents,
      already_licenced_gross_eur: 0,
      already_licenced_gross_cents: 0,
      already_licenced_saving_eur: 0,
      already_licenced_saving_cents: 0,
      credits: amounts.price,
      credits_cents: amounts.price_cents,
      price_eur: amounts.price,
      price_cents: amounts.price_cents,
      paid_tile_count: summary.paid_tile_count,
      free_tile_count: summary.free_tile_count,
      tile_count: summary.tile_count,
      unlicenced_tile_count: summary.tile_count,
      charged_tile_count: summary.paid_tile_count,
      new_tile_count: summary.paid_tile_count,
      new_tiles: [],
      excluded_tiles: [],
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
      tiles: [],
    };
  }
  const ownedFamilyRows = await regionProductOwnedFamilyRows(db, product, ownedByFamily, deps, options);
  if (!ownedFamilyRows.size) {
    const amounts = discountedRegionPackAmountCents(summary.gross_cents, discountPercent);
    return {
      ok: true,
      summary_estimate: true,
      static_catalog_estimate: true,
      no_owned_family_overlap: true,
      region_pack: regionProductPublicPayload(product),
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      discount_percent: discountPercent,
      gross_eur: amounts.gross,
      gross_cents: amounts.gross_cents,
      gross_price_eur: amounts.gross,
      gross_price_cents: amounts.gross_cents,
      discount_eur: amounts.discount,
      discount_cents: amounts.discount_cents,
      already_licenced_gross_eur: 0,
      already_licenced_gross_cents: 0,
      already_licenced_saving_eur: 0,
      already_licenced_saving_cents: 0,
      credits: amounts.price,
      credits_cents: amounts.price_cents,
      price_eur: amounts.price,
      price_cents: amounts.price_cents,
      paid_tile_count: summary.paid_tile_count,
      free_tile_count: summary.free_tile_count,
      tile_count: summary.tile_count,
      unlicenced_tile_count: summary.tile_count,
      charged_tile_count: summary.paid_tile_count,
      new_tile_count: summary.paid_tile_count,
      new_tiles: [],
      excluded_tiles: [],
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
      tiles: [],
    };
  }
  let alreadyLicencedCount = 0;
  let grossCents = Math.max(0, Number.parseInt(summary.gross_cents || 0, 10) || 0);
  let alreadyLicencedGrossCents = 0;
  let partialLicenceCount = 0;
  let partialLicenceCreditCents = 0;
  let paidTileCount = Math.max(0, Number.parseInt(summary.paid_tile_count || 0, 10) || 0);
  let freeTileCount = Math.max(0, Number.parseInt(summary.free_tile_count || 0, 10) || 0);

  for (const [family, familyRows] of ownedFamilyRows.entries()) {
    const ownedEntries = safeOwnedEntriesForFamily(ownedByFamily, family, familyRows);
    if (!ownedEntries.length) {
      continue;
    }
    const staticEstimate = estimateRegionPackFamilyRows(familyRows, []);
    const familyEstimate = estimateRegionPackFamilyRows(familyRows, ownedEntries);
    grossCents += familyEstimate.gross_cents - staticEstimate.gross_cents;
    alreadyLicencedCount += familyEstimate.already_licenced_count;
    alreadyLicencedGrossCents += familyEstimate.already_licenced_gross_cents;
    partialLicenceCount += Math.max(0, Number.parseInt(familyEstimate.partial_licence_count || 0, 10) || 0);
    partialLicenceCreditCents += Math.max(0, Number.parseInt(familyEstimate.partial_licence_credit_cents || 0, 10) || 0);
    paidTileCount += familyEstimate.paid_tile_count - staticEstimate.paid_tile_count;
    freeTileCount += familyEstimate.free_tile_count - staticEstimate.free_tile_count;
  }
  grossCents = Math.max(0, Math.round(grossCents));
  paidTileCount = Math.max(0, Math.round(paidTileCount));
  freeTileCount = Math.max(0, Math.round(freeTileCount));

  const amounts = discountedRegionPackAmountCents(grossCents, discountPercent);
  const newLicensableCount = paidTileCount;
  const unlicencedTileCount = regionPackVisibleNewTileCount(newLicensableCount, freeTileCount);
  return {
    ok: true,
    summary_estimate: true,
    region_pack: regionProductPublicPayload(product),
    region_pack_id: String(product.id || ""),
    region_pack_name: String(product.name || ""),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    discount_percent: discountPercent,
    gross_eur: amounts.gross,
    gross_cents: amounts.gross_cents,
    gross_price_eur: amounts.gross,
    gross_price_cents: amounts.gross_cents,
    discount_eur: amounts.discount,
    discount_cents: amounts.discount_cents,
    already_licenced_gross_eur: centsToEur(alreadyLicencedGrossCents),
    already_licenced_gross_cents: alreadyLicencedGrossCents,
    already_licenced_saving_eur: centsToEur(alreadyLicencedGrossCents),
    already_licenced_saving_cents: alreadyLicencedGrossCents,
    credits: amounts.price,
    credits_cents: amounts.price_cents,
    price_eur: amounts.price,
    price_cents: amounts.price_cents,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: summary.tile_count,
    unlicenced_tile_count: unlicencedTileCount,
    charged_tile_count: newLicensableCount,
    new_tile_count: newLicensableCount,
    partial_licence_tile_count: partialLicenceCount,
    partial_licence_credit_eur: centsToEur(partialLicenceCreditCents),
    partial_licence_credit_cents: partialLicenceCreditCents,
    new_tiles: [],
    excluded_tiles: new Array(alreadyLicencedCount).fill(null),
    integrity_warnings: [],
    metadata_missing_tile_keys: [],
    tiles: [],
  };
}

function regionPackEstimateCacheKey(product, account) {
  const userId = String(account && account.user_id || account && account.id || "").trim();
  const productId = String(product && product.id || "").trim().toLowerCase();
  if (!userId || !productId) {
    return "";
  }
  return [
    userId,
    productId,
    REGION_PACK_CATALOG_VERSION,
    pricingSettingsCacheKey(),
    accountEntitlementVersion(account),
  ].join("|");
}

function estimateAlreadyLicencedTileCount(estimate) {
  if (!estimate || typeof estimate !== "object") {
    return 0;
  }
  if (Object.prototype.hasOwnProperty.call(estimate, "already_licenced_tile_count")) {
    return Math.max(0, Number.parseInt(estimate.already_licenced_tile_count || 0, 10) || 0);
  }
  return Array.isArray(estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0;
}

function compactRegionPackSummaryEstimate(estimate) {
  if (!estimate || typeof estimate !== "object") {
    return estimate;
  }
  const alreadyLicencedCount = estimateAlreadyLicencedTileCount(estimate);
  const compact = {
    ...estimate,
    already_licenced_tile_count: alreadyLicencedCount,
  };
  delete compact.excluded_tiles;
  delete compact.new_tiles;
  delete compact.tiles;
  return compact;
}

async function estimateRegionPackSummaryCached(db, product, account, ownedByFamily, deps, options = {}) {
  const useCache = !(options && options.cache === false);
  const cacheKey = useCache ? regionPackEstimateCacheKey(product, account) : "";
  const nowMs = monotonicNowMs();
  if (cacheKey) {
    const cached = REGION_PACK_ESTIMATE_CACHE.get(cacheKey);
    if (
      cached
      && (nowMs - Number(cached.cached_at_ms || 0)) <= REGION_PACK_ESTIMATE_CACHE_TTL_MS
      && cached.estimate
    ) {
      return {
        ...cached.estimate,
        estimate_cache_hit: true,
      };
    }
  }
  let estimateSource = null;
  if (!(options && options.useRelationPricing === false)) {
    const ownershipContext = options && options.pricingOwnershipContext
      ? options.pricingOwnershipContext
      : await regionPackPricingOwnershipContext(db, account && account.user_id || "", account, deps, options);
    estimateSource = await estimateRegionPackSummaryWithPackRelations(
      db,
      product,
      account,
      ownershipContext,
      deps,
      options,
    );
  } else {
    estimateSource = await estimateRegionPackSummaryWithOwned(db, product, account, ownedByFamily, deps, options);
  }
  const estimate = compactRegionPackSummaryEstimate(
    estimateSource,
  );
  if (cacheKey && estimate && !estimate.error) {
    boundedCacheSet(
      REGION_PACK_ESTIMATE_CACHE,
      cacheKey,
      {
        estimate,
        cached_at_ms: nowMs,
      },
      REGION_PACK_ESTIMATE_CACHE_MAX,
    );
  }
  return estimate;
}

function purchaseMetadataJson(metadata) {
  try {
    return JSON.stringify(metadata && typeof metadata === "object" ? metadata : {});
  } catch (error) {
    return JSON.stringify({ metadata_error: String(error && error.message || "metadata_json_failed") });
  }
}

function parsePurchaseMetadataJson(row) {
  try {
    const value = row && row.metadata_json;
    return value ? JSON.parse(String(value || "{}")) : {};
  } catch (_error) {
    return {};
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
  const targetCents = centsFromField(estimate, "price_cents", "price_eur");
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
    const upgradeCreditEur = normalizeCreditAmount(row && row.upgrade_credit_applied);
    let status = "free";
    if (Boolean(row && row.already_owned)) {
      status = "licenced";
    } else if (allocatedCents > 0) {
      status = upgradeCreditEur > 0 ? "partial" : "new";
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
      upgrade_credit_eur: upgradeCreditEur,
      land_km2: normalizeMetricAmount(row && row.land_km2),
      billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
      free_reason: String(row && row.free_reason || "").trim(),
      already_licenced: Boolean(row && row.already_owned),
      partially_licenced: status === "partial",
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

function buildRegionPackUpsellCardData(product, quote, options = {}) {
  void options;
  if (!quote || quote.error || !quote.summary) {
    return null;
  }
  const tileRows = [];
  const canonicalSummary = quote.summary;
  const levels = Array.from(new Set(tileRows.map((row) => row.z).filter((z) => Number.isFinite(z))))
    .sort((a, b) => a - b);
  const displayLevel = levels.length ? levels[0] : null;
  const displayTiles = displayLevel === null
    ? []
    : tileRows.filter((row) => Number(row.z) === Number(displayLevel));
  const detail = GENERATED_REGION_PACK_DETAILS[String(product && product.id || "")] || {};
  return {
    region_pack: regionProductPublicPayload(product),
    asset_id: String(product && product.id || ""),
    quote_id: String(quote && quote.quote_id || ""),
    bounds: regionMapBounds(product, detail, displayTiles.length ? displayTiles : tileRows),
    display_level: displayLevel,
    tiles: displayTiles,
    summary: {
      ...canonicalSummary,
    },
  };
}

function buildCanonicalRegionPackSummary(product, estimate) {
  const productSummary = regionProductPricingSummary(product) || {};
  const partialLicenceTiles = Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0);
  const excludedTileCount = estimateAlreadyLicencedTileCount(estimate);
  const chargeableGrossCents = centsFromField(estimate, "gross_price_cents", "gross_price_eur")
    || centsFromField(estimate, "gross_cents", "gross_eur");
  const alreadyLicencedCentsRaw = centsFromField(estimate, "already_licenced_gross_cents", "already_licenced_gross_eur");
  const partialLicenceCentsRaw = centsFromField(estimate, "partial_licence_credit_cents", "partial_licence_credit_eur");
  const fullPriceCents = centsFromField(estimate, "full_price_cents", "full_price_eur")
    || centsFromField(estimate, "full_pack_gross_cents", "full_pack_gross_eur")
    || Math.max(0, chargeableGrossCents + alreadyLicencedCentsRaw + partialLicenceCentsRaw)
    || integerCents(productSummary.gross_cents)
    || centsForEur(productSummary.gross_eur);
  const alreadyLicencedCents = Math.min(
    fullPriceCents,
    alreadyLicencedCentsRaw,
  );
  const partialLicenceCents = Math.min(
    Math.max(0, fullPriceCents - alreadyLicencedCents),
    partialLicenceCentsRaw,
  );
  const discountPercent = Math.max(0, Number.parseInt(estimate && estimate.discount_percent || regionProductDiscountPercent(product), 10) || 0);
  const chargeableCents = Math.max(0, fullPriceCents - alreadyLicencedCents - partialLicenceCents);
  const amounts = discountedRegionPackAmountCents(chargeableCents, discountPercent);
  return {
    new_tiles: estimateUnlicencedTileCount(estimate),
    charged_tiles: estimateChargedTileCount(estimate),
    total_tiles: Math.max(0, Number.parseInt(productSummary.tile_count || estimate && estimate.tile_count || 0, 10) || 0),
    already_licenced_tiles: excludedTileCount,
    partial_licence_tiles: partialLicenceTiles,
    full_price_eur: centsToEur(fullPriceCents),
    full_price_cents: fullPriceCents,
    already_licenced_deduction_eur: centsToEur(alreadyLicencedCents),
    already_licenced_deduction_cents: alreadyLicencedCents,
    already_licenced_saving_eur: centsToEur(alreadyLicencedCents),
    partial_licence_credit_eur: centsToEur(partialLicenceCents),
    partial_licence_credit_cents: partialLicenceCents,
    discount_percent: discountPercent,
    discount_eur: centsToEur(amounts.discount_cents),
    discount_cents: amounts.discount_cents,
    price_eur: centsToEur(amounts.price_cents),
    price_cents: amounts.price_cents,
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

async function contextRegionProductForTileRows(db, tileRows, deps) {
  const center = tileRowsCenter(tileRows);
  if (!center) {
    return null;
  }
  const products = await suggestedRegionProductsForPoint(db, center.latitude_deg, center.longitude_deg, deps);
  return products.length ? products[0] : null;
}

async function regionProductTileFamilySet(db, product, deps) {
  const productId = String(product && product.id || "").trim();
  if (!productId) {
    return new Set();
  }
  const cacheKey = `${REGION_PACK_CATALOG_VERSION}|${productId}`;
  if (REGION_PRODUCT_TILE_FAMILY_CACHE.has(cacheKey)) {
    return REGION_PRODUCT_TILE_FAMILY_CACHE.get(cacheKey);
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const rows = await deps.dbAll(
    db,
    `
      SELECT DISTINCT family_key
      FROM region_pack_tile_entries
      WHERE catalog_version = ?
        AND region_pack_id = ?
    `,
    [REGION_PACK_CATALOG_VERSION, productId],
  );
  const families = new Set((rows || []).map((row) => String(row && row.family_key || "").trim()).filter(Boolean));
  boundedCacheSet(REGION_PRODUCT_TILE_FAMILY_CACHE, cacheKey, families, 256);
  return families;
}

async function regionProductContainsTileFootprint(db, product, tileKey, deps) {
  const key = normalizeTileKey(tileKey);
  const parsed = parseTileKey(key);
  const family = tileFamilyKey(parsed);
  if (!product || !key || !parsed || !family) {
    return false;
  }
  if (await regionPackProductContainsTileKey(db, product, key, deps)) {
    return true;
  }
  return (await regionProductTileFamilySet(db, product, deps)).has(family);
}

async function regionProductContainsAllTileFootprints(db, product, tileKeys, deps) {
  const keys = normalizeTileKeys(tileKeys);
  if (!keys.length || !product || isHiddenRegionProduct(product)) {
    return false;
  }
  for (const key of keys) {
    if (!await regionProductContainsTileFootprint(db, product, key, deps)) {
      return false;
    }
  }
  return true;
}

async function sceneSuccessCandidateProductsForTileKeys(db, tileKeys, deps) {
  const keys = normalizeTileKeys(tileKeys);
  if (!keys.length) {
    return [];
  }
  const matches = [];
  for (const product of REGION_PRODUCTS) {
    const rank = regionProductRank(product);
    if (
      rank > 0
      && rank < 4
      && !isHiddenRegionProduct(product)
      && await regionProductContainsAllTileFootprints(db, product, keys, deps)
    ) {
      matches.push(product);
    }
  }
  return matches.sort((a, b) => (
      regionProductRank(a) - regionProductRank(b)
      || productSpecificityScore(a) - productSpecificityScore(b)
      || bboxArea(a) - bboxArea(b)
      || Math.max(0, Number(a && a.tile_count || 0) || 0) - Math.max(0, Number(b && b.tile_count || 0) || 0)
      || String(a.name || "").localeCompare(String(b.name || ""))
    ));
}

async function sceneSuccessContextProduct(db, tileKeys, fallbackRows = [], deps) {
  const containingProducts = await sceneSuccessCandidateProductsForTileKeys(db, tileKeys, deps);
  if (containingProducts.length) {
    return containingProducts[0];
  }
  const center = tileRowsCenter(fallbackRows);
  const fallbackProducts = center
    ? await suggestedRegionProductsForContext(db, center.latitude_deg, center.longitude_deg, tileKeys, deps)
    : [];
  return fallbackProducts.length ? fallbackProducts[0] : null;
}

function buildSceneFullQualityMapData(estimate, options = {}) {
  const tileRows = allocatedRegionPackTileRows(estimate);
  const contextProduct = options && options.contextProduct ? options.contextProduct : null;
  const contextDetail = GENERATED_REGION_PACK_DETAILS[String(contextProduct && contextProduct.id || "")] || {};
  const contextCountries = contextProduct ? regionProductIncludedCountries(contextProduct) : [];
  const levels = Array.from(new Set(tileRows.map((row) => row.z).filter((z) => Number.isFinite(z))))
    .sort((a, b) => a - b);
  const tileBounds = regionMapBounds(null, null, tileRows);
  const contextBounds = contextProduct
    ? regionMapBounds(contextProduct, contextDetail, tileRows)
    : expandedMapBounds(tileBounds, 0.18);
  const fullPrice = normalizeCreditAmount(tileRows.reduce((total, row) => total + normalizeCreditAmount(row.full_price_eur), 0));
  const partialLicenceCredit = normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur);
  const partialLicenceCount = Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0);
  const alreadyLicencedSaving = normalizeCreditAmount(tileRows
    .filter((row) => String(row.status || "") === "licenced")
    .reduce((total, row) => total + normalizeCreditAmount(row.full_price_eur), 0));
  const scenePolicy = scenePaymentPolicyForEstimate(estimate);
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
      new_tiles: estimateUnlicencedTileCount(estimate),
      charged_tiles: estimateChargedTileCount(estimate),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: estimateAlreadyLicencedTileCount(estimate),
      partial_licence_tiles: partialLicenceCount,
      partial_licence_credit_eur: partialLicenceCredit,
      already_licenced_saving_eur: alreadyLicencedSaving,
      already_licenced_deduction_eur: alreadyLicencedSaving,
      full_price_eur: fullPrice,
      discount_percent: 0,
      discount_eur: 0,
      price_eur: scenePolicy.scene_payable_eur,
      raw_price_eur: scenePolicy.scene_tile_price_eur,
      scene_tile_price_eur: scenePolicy.scene_tile_price_eur,
      custom_scene_licence_eur: scenePolicy.custom_scene_licence_eur,
      custom_scene_licence_cents: scenePolicy.custom_scene_licence_cents,
      scene_custom_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
      scene_custom_licence_applied: scenePolicy.scene_custom_licence_applied,
      scene_small_free_threshold_eur: scenePolicy.scene_small_free_threshold_eur,
      scene_small_free_threshold_applied: scenePolicy.scene_small_free_threshold_applied,
      tile_price_sum_eur: normalizeCreditAmount(tileRows.reduce((total, row) => total + normalizeCreditAmount(row.price_eur), 0)),
    },
    tiles: tileRows,
    upsells: Array.isArray(options && options.upsells) ? options.upsells : [],
    success: options && options.success ? options.success : null,
  };
}

function sceneQuoteForStaticMap(estimate, userId, account, token, deps) {
  const tileRows = allocatedRegionPackTileRows(estimate);
  const scenePolicy = scenePaymentPolicyForEstimate(estimate);
  const partialLicenceCreditCents = centsForEur(estimate && estimate.partial_licence_credit_eur);
  const partialLicenceCount = Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0);
  const alreadyLicencedDeductionCents = tileRows
    .filter((row) => String(row.status || "") === "licenced")
    .reduce((total, row) => total + centsForEur(row && row.full_price_eur), 0);
  const fullPriceCents = tileRows.reduce((total, row) => total + centsForEur(row && row.full_price_eur), 0);
  const quoteId = `scene_${String(token || "").slice(0, 24)}`;
  const createdAt = quoteIsoNow(deps);
  return {
    quote_id: quoteId,
    quote_type: "scene_tiles",
    user_id: String(userId || "").trim(),
    subject_id: quoteId,
    pricing_version: pricingSettingsCacheKey(),
    entitlement_version: accountEntitlementVersion(account),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    amount_cents: scenePolicy.scene_payable_cents,
    currency: "eur",
    created_at: createdAt,
    expires_at: addMinutesIsoFromDeps(deps, REGION_PACK_QUOTE_TTL_MINUTES),
    summary: {
      new_tiles: estimateUnlicencedTileCount(estimate),
      charged_tiles: estimateChargedTileCount(estimate),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || tileRows.length, 10) || tileRows.length),
      already_licenced_tiles: estimateAlreadyLicencedTileCount(estimate),
      partial_licence_tiles: partialLicenceCount,
      partial_licence_credit_cents: partialLicenceCreditCents,
      partial_licence_credit_eur: normalizeCreditAmount(partialLicenceCreditCents / 100),
      already_licenced_deduction_cents: alreadyLicencedDeductionCents,
      already_licenced_deduction_eur: normalizeCreditAmount(alreadyLicencedDeductionCents / 100),
      full_price_cents: fullPriceCents,
      full_price_eur: normalizeCreditAmount(fullPriceCents / 100),
      discount_percent: 0,
      discount_cents: 0,
      discount_eur: 0,
      price_cents: scenePolicy.scene_payable_cents,
      price_eur: scenePolicy.scene_payable_eur,
      raw_price_eur: scenePolicy.scene_tile_price_eur,
      scene_tile_price_cents: scenePolicy.scene_tile_price_cents,
      scene_tile_price_eur: scenePolicy.scene_tile_price_eur,
      custom_scene_licence_cents: scenePolicy.custom_scene_licence_cents,
      custom_scene_licence_eur: scenePolicy.custom_scene_licence_eur,
      scene_custom_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
      scene_custom_licence_applied: scenePolicy.scene_custom_licence_applied,
      scene_small_free_threshold_eur: scenePolicy.scene_small_free_threshold_eur,
      scene_small_free_threshold_applied: scenePolicy.scene_small_free_threshold_applied,
    },
  };
}

async function sceneProductContextMapState(db, product, estimate, deps) {
  const contextDetail = GENERATED_REGION_PACK_DETAILS[String(product && product.id || "")] || {};
  const sceneRows = allocatedRegionPackTileRows(estimate);
  const sceneByKey = new Map(sceneRows.map((row) => [normalizeTileKey(row && row.tile_key || ""), row]));
  const sceneByFamily = new Map();
  for (const row of sceneRows) {
    const parsed = parseTileKey(row && row.tile_key || "");
    if (!parsed) {
      continue;
    }
    const familyKey = tileFamilyKey(parsed);
    if (familyKey && !sceneByFamily.has(familyKey)) {
      sceneByFamily.set(familyKey, row);
    }
  }
  const productRows = await regionPackAllTileRowsForProduct(db, product, deps);
  const tiles = [];
  const levelCounts = {};
  const representedSceneKeys = new Set();
  for (const row of productRows) {
    const key = normalizeTileKey(row && (row.tile_key || row.key) || "");
    const parsed = parseTileKey(key);
    if (!parsed || !isRegionPackPaidZLevel(parsed.z)) {
      continue;
    }
    const sceneRow = sceneByKey.get(key) || sceneByFamily.get(tileFamilyKey(parsed));
    const sceneParsed = sceneRow ? parseTileKey(sceneRow.tile_key || "") : null;
    const lowerResolutionSceneTile = Boolean(sceneParsed && sceneParsed.d > parsed.d);
    const sceneStatus = sceneRow
      ? (lowerResolutionSceneTile && String(sceneRow.status || "") !== "licenced" ? "lower_resolution" : String(sceneRow.status || "free"))
      : "context";
    const displayKey = sceneParsed ? sceneParsed.key : "";
    if (displayKey) {
      representedSceneKeys.add(displayKey);
    }
    const grossCents = sceneRow ? centsForEur(sceneRow.full_price_eur) : integerCents(row && row.gross_cents);
    const partialCreditCents = sceneRow ? centsForEur(sceneRow.upgrade_credit_eur || sceneRow.partial_licence_credit_eur || 0) : 0;
    const finalCents = sceneRow ? centsForEur(sceneRow.price_eur) : 0;
    tiles.push({
      tile_key: displayKey || key,
      display_tile_key: displayKey || key,
      x: parsed.x,
      y: parsed.y,
      z: parsed.z,
      d: sceneParsed ? sceneParsed.d : parsed.d,
      lon_min: parsed.x - 180,
      lon_max: parsed.x - 180 + parsed.z,
      lat_min: parsed.y - 90,
      lat_max: parsed.y - 90 + parsed.z,
      status: sceneStatus,
      full_price_cents: grossCents,
      gross_cents: grossCents,
      already_licenced_cents: sceneRow && String(sceneRow.status || "") === "licenced" ? grossCents : 0,
      partial_licence_credit_cents: partialCreditCents,
      discount_cents: 0,
      discount_percent: 0,
      final_price_cents: finalCents,
      price_cents: finalCents,
      land_km2: normalizeMetricAmount(row && row.land_km2),
      billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
      globally_free: Boolean(row && row.globally_free),
    });
    levelCounts[String(parsed.z)] = (Number(levelCounts[String(parsed.z)] || 0) || 0) + 1;
  }
  for (const sceneRow of sceneRows) {
    const parsed = parseTileKey(sceneRow && sceneRow.tile_key || "");
    if (!parsed || representedSceneKeys.has(parsed.key) || !isRegionPackPaidZLevel(parsed.z)) {
      continue;
    }
    const lowerResolutionSceneTile = parsed.d > parsed.z;
    const sceneStatus = lowerResolutionSceneTile && String(sceneRow.status || "") !== "licenced"
      ? "lower_resolution"
      : String(sceneRow.status || "free");
    const grossCents = centsForEur(sceneRow.full_price_eur);
    const partialCreditCents = centsForEur(sceneRow.upgrade_credit_eur || sceneRow.partial_licence_credit_eur || 0);
    const finalCents = centsForEur(sceneRow.price_eur);
    tiles.push({
      tile_key: parsed.key,
      display_tile_key: parsed.key,
      x: parsed.x,
      y: parsed.y,
      z: parsed.z,
      d: parsed.d,
      lon_min: parsed.x - 180,
      lon_max: parsed.x - 180 + parsed.z,
      lat_min: parsed.y - 90,
      lat_max: parsed.y - 90 + parsed.z,
      status: sceneStatus,
      full_price_cents: grossCents,
      gross_cents: grossCents,
      already_licenced_cents: String(sceneRow.status || "") === "licenced" ? grossCents : 0,
      partial_licence_credit_cents: partialCreditCents,
      discount_cents: 0,
      discount_percent: 0,
      final_price_cents: finalCents,
      price_cents: finalCents,
      land_km2: normalizeMetricAmount(sceneRow.land_km2),
      billable_land_km2: normalizeMetricAmount(sceneRow.billable_land_km2),
      globally_free: Boolean(sceneRow.globally_free),
    });
    levelCounts[String(parsed.z)] = (Number(levelCounts[String(parsed.z)] || 0) || 0) + 1;
  }
  const sceneLevels = Array.from(new Set(sceneRows.map((row) => Number(row && row.z)).filter(Number.isFinite))).sort((a, b) => a - b);
  const levels = Object.keys(levelCounts).map((level) => Number.parseInt(level, 10)).filter(Number.isFinite).sort((a, b) => a - b);
  const defaultLevel = sceneLevels.find((level) => levelCounts[String(level)] > 0) || defaultRegionPackMapLevel(levelCounts);
  return {
    schema: 4,
    scene_detail: true,
    tile_status_mode: "scene_quote_on_product_context",
    region_pack: regionProductPublicPayload(product),
    product_full_quality_unlocked: false,
    bounds: regionMapBounds(product, contextDetail, sceneRows),
    outlines: regionProductOutlinesForMap(product),
    included_countries: regionProductIncludedCountries(product),
    levels: defaultLevel ? [defaultLevel] : levels,
    default_level: defaultLevel,
    level_tile_counts: levelCounts,
    tiles,
  };
}

function regionPackOfferPayload(product, quote) {
  if (!quote || quote.error || !quote.summary) {
    return {
      ok: false,
      ...regionProductPublicPayload(product),
      error: String(quote && quote.error || "quote_failed"),
    };
  }
  const summary = quote.summary;
  const priceEur = summary.price_eur;
  const chargedTileCount = Math.max(0, Number.parseInt(summary.charged_tiles || 0, 10) || 0);
  const newTileCount = Math.max(0, Number.parseInt(summary.new_tiles || 0, 10) || 0);
  return {
    ok: true,
    ...regionProductPublicPayload(product),
    quote_id: String(quote.quote_id || ""),
    pricing_version: String(quote.pricing_version || ""),
    entitlement_version: String(quote.entitlement_version || ""),
    full_price_eur: summary.full_price_eur,
    full_price_cents: summary.full_price_cents,
    gross_eur: summary.full_price_eur,
    gross_price_eur: summary.full_price_eur,
    discount_eur: summary.discount_eur,
    discount_cents: summary.discount_cents,
    already_licenced_gross_eur: summary.already_licenced_deduction_eur,
    already_licenced_deduction_eur: summary.already_licenced_deduction_eur,
    already_licenced_deduction_cents: summary.already_licenced_deduction_cents,
    already_licenced_saving_eur: summary.already_licenced_saving_eur,
    partial_licence_tile_count: summary.partial_licence_tiles,
    partial_licence_credit_eur: summary.partial_licence_credit_eur,
    partial_licence_credit_cents: summary.partial_licence_credit_cents,
    credits: priceEur,
    price_eur: priceEur,
    price_cents: summary.price_cents,
    paid_tile_count: chargedTileCount,
    free_tile_count: Math.max(0, Number.parseInt(summary.free_tiles || 0, 10) || 0),
    tile_count: Math.max(0, Number.parseInt(summary.total_tiles || 0, 10) || 0),
    unlicenced_tile_count: newTileCount,
    new_tile_count: newTileCount,
    charged_tile_count: chargedTileCount,
    already_licenced_tile_count: summary.already_licenced_tiles,
    metadata_missing_tile_keys: [],
  };
}

function regionProductCatalogGroup(product) {
  const id = String(product && product.id || "").trim().toLowerCase();
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "world") {
    return { key: "world", label: "World" };
  }
  if (COUNTRY_LIKE_REGION_PRODUCT_IDS.has(id)) {
    return { key: "countries", label: "Countries" };
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

function estimateUnlicencedTileCount(estimate) {
  if (estimate && estimate.world_full_quality_unlocked) {
    return 0;
  }
  if (estimate && Object.prototype.hasOwnProperty.call(estimate, "unlicenced_tile_count")) {
    return Math.max(0, Number.parseInt(estimate.unlicenced_tile_count || 0, 10) || 0);
  }
  const total = Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0);
  const already = estimateAlreadyLicencedTileCount(estimate);
  return Math.max(0, total - already);
}

function estimateChargedTileCount(estimate) {
  if (!estimate || typeof estimate !== "object") {
    return 0;
  }
  if (Object.prototype.hasOwnProperty.call(estimate, "charged_tile_count")) {
    return Math.max(0, Number.parseInt(estimate.charged_tile_count || 0, 10) || 0);
  }
  if (Object.prototype.hasOwnProperty.call(estimate, "new_tile_count")) {
    return Math.max(0, Number.parseInt(estimate.new_tile_count || 0, 10) || 0);
  }
  if (Array.isArray(estimate.new_tiles)) {
    return estimate.new_tiles.length;
  }
  return Math.max(0, Number.parseInt(estimate.paid_tile_count || 0, 10) || 0);
}

function productQuoteStatus(row, pricingVersion, entitlementVersion) {
  if (!row || typeof row !== "object") {
    return "missing";
  }
  const status = String(row.status || "").trim().toLowerCase();
  if (
    String(row.pricing_version || "") !== String(pricingVersion || "")
    || String(row.entitlement_version || "") !== String(entitlementVersion || "")
    || String(row.catalog_version || "") !== REGION_PACK_CATALOG_VERSION
  ) {
    return "stale";
  }
  if (status === "ready") {
    if (!String(row.quote_id || "").trim()) {
      return "stale";
    }
    return "ready";
  }
  if (status === "error" || status === "failed") {
    return "error";
  }
  return status || "updating";
}

function regionPackCatalogQuoteRow(product, row, status) {
  const group = regionProductCatalogGroup(product);
  const ready = status === "ready";
  const fullPriceCents = ready ? integerCents(row && row.full_price_cents) : 0;
  const alreadyLicencedCents = ready ? integerCents(row && row.already_licenced_cents) : 0;
  const partialLicenceCreditCents = ready ? integerCents(row && row.partial_licence_credit_cents) : 0;
  const discountCents = ready ? integerCents(row && row.discount_cents) : 0;
  const priceCents = ready ? integerCents(row && row.final_price_cents) : 0;
  return {
    id: String(product && product.id || ""),
    quote_id: ready ? String(row && row.quote_id || "") : "",
    quote_status: status,
    price_pending: !ready,
    status_label: ready ? "" : (status === "error" ? "Price unavailable" : "Price updating"),
    error_message: status === "error" ? String(row && row.error_message || "Price could not be calculated.") : "",
    name: String(product && product.name || ""),
    type: String(product && product.type || ""),
    group_key: group.key,
    group_label: group.label,
    total_tiles: ready ? Math.max(0, Number.parseInt(row && row.total_tile_count || 0, 10) || 0) : null,
    new_tiles: ready ? Math.max(0, Number.parseInt(row && row.new_tile_count || 0, 10) || 0) : null,
    unlicenced_tile_count: ready ? Math.max(0, Number.parseInt(row && row.new_tile_count || 0, 10) || 0) : null,
    charged_tiles: ready ? Math.max(0, Number.parseInt(row && row.charged_tile_count || 0, 10) || 0) : null,
    already_licenced_tiles: ready ? Math.max(0, Number.parseInt(row && row.already_licenced_tile_count || 0, 10) || 0) : null,
    partial_licence_tiles: ready ? Math.max(0, Number.parseInt(row && row.partial_licence_tile_count || 0, 10) || 0) : null,
    full_price_eur: ready ? centsToEur(fullPriceCents) : null,
    full_price_cents: ready ? fullPriceCents : null,
    chargeable_full_price_eur: ready ? centsToEur(Math.max(0, fullPriceCents - alreadyLicencedCents - partialLicenceCreditCents)) : null,
    already_licenced_deduction_eur: ready ? centsToEur(alreadyLicencedCents) : null,
    already_licenced_saving_eur: ready ? centsToEur(alreadyLicencedCents) : null,
    already_licenced_deduction_cents: ready ? alreadyLicencedCents : null,
    partial_licence_credit_eur: ready ? centsToEur(partialLicenceCreditCents) : null,
    partial_licence_credit_cents: ready ? partialLicenceCreditCents : null,
    discount_percent: ready ? Math.max(0, Number.parseInt(row && row.discount_percent || 0, 10) || 0) : null,
    discount_eur: ready ? centsToEur(discountCents) : null,
    discount_cents: ready ? discountCents : null,
    price_eur: ready ? centsToEur(priceCents) : null,
    price_cents: ready ? priceCents : null,
  };
}

function secureRandomIdentifier(byteLength = 16) {
  if (typeof crypto === "undefined" || !crypto) {
    throw new Error("crypto_unavailable");
  }
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  if (typeof crypto.getRandomValues === "function") {
    const bytes = new Uint8Array(Math.max(8, Math.min(64, Number.parseInt(byteLength || 16, 10) || 16)));
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  throw new Error("crypto_unavailable");
}

function userProductQuoteJobId() {
  const randomId = secureRandomIdentifier(24);
  return `upqj_${String(randomId).replace(/[^A-Za-z0-9]/g, "").slice(0, 48)}`;
}

function userProductQuoteBatchId() {
  const randomId = secureRandomIdentifier(24);
  return `upqb_${String(randomId).replace(/[^A-Za-z0-9]/g, "").slice(0, 48)}`;
}

const USER_PRODUCT_QUOTE_JOB_LOCK_NAME = "user_product_quote_jobs_global";
const USER_PRODUCT_QUOTE_JOB_LOCK_TTL_SECONDS = 45;
const USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_JOBS = 12;
const USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_MS = 20000;
const USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_MAP_JOBS = 8;
const USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_HEAVY_MAP_JOBS = 1;
const USER_PRODUCT_QUOTE_JOB_MAX_ATTEMPTS = 3;
const USER_PRODUCT_QUOTE_JOB_STALE_RUNNING_SECONDS = 120;
const USER_PRODUCT_QUOTE_FAST_TRACK_AVAILABLE_AT = "1970-01-01T00:00:00.000Z";
const USER_PRODUCT_QUOTE_MEDIUM_MAP_TILE_COUNT = 250;
const USER_PRODUCT_QUOTE_HEAVY_MAP_TILE_COUNT = 1000;
const USER_PRODUCT_MAP_STATE_INLINE_MAX_BYTES = 500000;
const USER_PRODUCT_MAP_STATE_SHARD_TILE_COUNT = 5000;
const USER_PRODUCT_MAP_STATE_SHARD_STEP_TILE_LIMIT = 3000;

function userProductQuoteWorkerId(deps) {
  const random = deps && typeof deps.randomToken === "function"
    ? deps.randomToken(8)
    : secureRandomIdentifier(8);
  return `upqw_${String(random || "").replace(/[^A-Za-z0-9]/g, "").slice(0, 24)}`;
}

function addSecondsIsoFromDeps(deps, seconds) {
  const base = Date.parse(String(deps && deps.nowIso && deps.nowIso() || ""));
  const nowMs = Number.isFinite(base) ? base : Date.now();
  return new Date(nowMs + (Math.max(1, Number(seconds) || 1) * 1000)).toISOString();
}

function addRawSecondsIsoFromDeps(deps, seconds) {
  const base = Date.parse(String(deps && deps.nowIso && deps.nowIso() || ""));
  const nowMs = Number.isFinite(base) ? base : Date.now();
  return new Date(nowMs + ((Number(seconds) || 0) * 1000)).toISOString();
}

async function enqueueUserProductQuoteJob(db, userId, productId, pricingVersion, entitlementVersion, deps, options = {}) {
  const safeUserId = String(userId || "").trim();
  const safeProductId = String(productId || "").trim().toLowerCase();
  if (!safeUserId || !safeProductId) {
    return false;
  }
  const now = quoteIsoNow(deps);
  const rawJobRound = options && Object.prototype.hasOwnProperty.call(options, "jobRound") ? options.jobRound : 0;
  const rawPriority = options && Object.prototype.hasOwnProperty.call(options, "priority") ? options.priority : 70;
  const jobRound = Number.isFinite(Number(rawJobRound)) ? Math.max(0, Number.parseInt(rawJobRound, 10) || 0) : 0;
  const priority = Number.isFinite(Number(rawPriority)) ? Math.max(0, Number.parseInt(rawPriority, 10) || 0) : 70;
  const availableAt = Boolean(options && options.fastTrack)
    ? USER_PRODUCT_QUOTE_FAST_TRACK_AVAILABLE_AT
    : now;
  const result = await deps.dbRun(
    db,
    `
      INSERT OR IGNORE INTO user_product_quote_jobs (
        id, batch_id, user_id, product_id, source_product_id, catalog_version,
        pricing_version, entitlement_version, job_round, priority, status,
        trigger_type, trigger_purchase_id, stale_reason, attempts, available_at,
        created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, 0, ?, ?, ?)
    `,
    [
      userProductQuoteJobId(),
      String(options && options.batchId || "") || null,
      safeUserId,
      safeProductId,
      String(options && options.sourceProductId || "") || null,
      REGION_PACK_CATALOG_VERSION,
      String(pricingVersion || ""),
      String(entitlementVersion || ""),
      jobRound,
      priority,
      String(options && options.triggerType || "catalog_view"),
      String(options && options.triggerPurchaseId || "") || null,
      String(options && options.staleReason || "catalog_quote_not_ready"),
      availableAt,
      now,
      now,
    ],
  );
  const inserted = deps.dbMetaChanges(result) > 0;
  if (inserted || !Boolean(options && options.fastTrack)) {
    return inserted;
  }
  // A stale product requested directly by the user must be promoted even if a
  // low-priority batch job for the same product already exists. INSERT OR
  // IGNORE alone would leave continent/world jobs stuck behind older rounds.
  const promote = await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_jobs
      SET
        job_round = CASE WHEN job_round > ? THEN ? ELSE job_round END,
        priority = CASE
          WHEN job_round > ? OR priority > ? THEN ?
          ELSE priority
        END,
        available_at = CASE WHEN available_at > ? THEN ? ELSE available_at END,
        trigger_type = ?,
        stale_reason = ?,
        source_product_id = COALESCE(?, source_product_id),
        trigger_purchase_id = COALESCE(?, trigger_purchase_id),
        updated_at = ?
      WHERE user_id = ?
        AND product_id = ?
        AND catalog_version = ?
        AND pricing_version = ?
        AND entitlement_version = ?
        AND status = 'queued'
    `,
    [
      jobRound,
      jobRound,
      jobRound,
      priority,
      priority,
      availableAt,
      availableAt,
      String(options && options.triggerType || "product_requested"),
      String(options && options.staleReason || "requested_quote_not_ready"),
      String(options && options.sourceProductId || "") || null,
      String(options && options.triggerPurchaseId || "") || null,
      now,
      safeUserId,
      safeProductId,
      REGION_PACK_CATALOG_VERSION,
      String(pricingVersion || ""),
      String(entitlementVersion || ""),
    ],
  );
  return deps.dbMetaChanges(promote) > 0;
}

function quotePlanEntryForProduct(productId, jobRound, priority, relationType = "") {
  const safeProductId = String(productId || "").trim().toLowerCase();
  if (!safeProductId || !regionProductById(safeProductId)) {
    return null;
  }
  return {
    product_id: safeProductId,
    job_round: Math.max(0, Number.parseInt(jobRound || 0, 10) || 0),
    priority: Number.isFinite(Number(priority)) ? Math.max(0, Number.parseInt(priority, 10) || 0) : 70,
    relation_type: String(relationType || "").trim().toLowerCase(),
  };
}

function mergeQuotePlanEntry(plan, entry) {
  if (!(plan instanceof Map) || !entry || !entry.product_id) {
    return;
  }
  const current = plan.get(entry.product_id);
  if (
    !current
    || entry.job_round < current.job_round
    || (entry.job_round === current.job_round && entry.priority < current.priority)
  ) {
    plan.set(entry.product_id, entry);
  }
}

function quoteJobRoundForOwnedRelation(targetProductId, relationType) {
  const product = regionProductById(targetProductId);
  const productType = String(product && product.type || "").trim().toLowerCase();
  const type = String(relationType || "").trim().toLowerCase();
  if (type === "parent_covers_target") {
    return 1;
  }
  if (type === "owned_child_of_target") {
    if (productType === "world") {
      return 7;
    }
    if (productType === "continent") {
      return 6;
    }
    return 4;
  }
  if (type === "overlap") {
    return 5;
  }
  return 8;
}

function quoteJobPriorityForRound(jobRound, productId) {
  const productType = String(regionProductById(productId) && regionProductById(productId).type || "").trim().toLowerCase();
  const round = Math.max(0, Number.parseInt(jobRound || 0, 10) || 0);
  if (round <= 0) {
    return 0;
  }
  if (round === 1) {
    return 10;
  }
  if (round === 2) {
    return 20;
  }
  if (round === 4) {
    return 40;
  }
  if (round === 5) {
    return 50;
  }
  if (productType === "world") {
    return 90;
  }
  if (productType === "continent") {
    return 80;
  }
  return 70;
}

function quoteInvalidationPlanForRegionPackPurchase(sourceProductId) {
  const safeSourceId = String(sourceProductId || "").trim().toLowerCase();
  const plan = new Map();
  if (!safeSourceId || !regionProductById(safeSourceId)) {
    return plan;
  }
  mergeQuotePlanEntry(plan, quotePlanEntryForProduct(safeSourceId, 0, 0, "self"));
  const relationRows = REGION_PACK_STATIC_RELATION_GRAPH_READY
    && GENERATED_REGION_PACK_RELATIONS_BY_OWNED
    && typeof GENERATED_REGION_PACK_RELATIONS_BY_OWNED === "object"
    && Array.isArray(GENERATED_REGION_PACK_RELATIONS_BY_OWNED[safeSourceId])
      ? GENERATED_REGION_PACK_RELATIONS_BY_OWNED[safeSourceId]
      : [];
  for (const row of relationRows) {
    if (!Array.isArray(row)) {
      continue;
    }
    const targetProductId = String(row[0] || "").trim().toLowerCase();
    const relationType = String(row[1] || "").trim().toLowerCase();
    if (!targetProductId || targetProductId === safeSourceId || !regionPackRelationHasOverlap({
      relation_type: relationType,
      overlap_tile_count: row[2],
    })) {
      continue;
    }
    const jobRound = quoteJobRoundForOwnedRelation(targetProductId, relationType);
    mergeQuotePlanEntry(
      plan,
      quotePlanEntryForProduct(
        targetProductId,
        jobRound,
        quoteJobPriorityForRound(jobRound, targetProductId),
        relationType,
      ),
    );
  }
  return plan;
}

function quoteInvalidationPlanForAllProducts(reason = "entitlement_change") {
  const plan = new Map();
  for (const product of REGION_PRODUCTS) {
    const productId = String(product && product.id || "").trim().toLowerCase();
    if (!productId) {
      continue;
    }
    const productType = String(product && product.type || "").trim().toLowerCase();
    const jobRound = productType === "world"
      ? 7
      : productType === "continent"
        ? 6
        : productType === "macro_region"
          ? 4
          : 2;
    mergeQuotePlanEntry(plan, quotePlanEntryForProduct(
      productId,
      jobRound,
      quoteJobPriorityForRound(jobRound, productId),
      reason,
    ));
  }
  return plan;
}

async function productIdsAffectedByTileKeys(db, tileKeys, deps) {
  const families = Array.from(new Set(normalizeTileKeys(tileKeys)
    .map((tileKey) => tileFamilyKey(parseTileKey(tileKey)))
    .filter(Boolean)));
  if (!families.length) {
    return [];
  }
  if (families.length > 250) {
    return REGION_PRODUCTS.map((product) => String(product && product.id || "").trim().toLowerCase()).filter(Boolean);
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const productIds = new Set();
  for (const chunk of fixedSizeChunks(families, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
    const rows = await deps.dbAll(
      db,
      `
        SELECT DISTINCT region_pack_id
        FROM region_pack_tile_entries
        WHERE catalog_version = ?
          AND family_key IN (${chunk.map(() => "?").join(",")})
      `,
      [REGION_PACK_CATALOG_VERSION, ...chunk],
    );
    for (const row of rows || []) {
      const productId = String(row && row.region_pack_id || "").trim().toLowerCase();
      if (productId) {
        productIds.add(productId);
      }
    }
  }
  return Array.from(productIds);
}

async function quoteInvalidationPlanForScenePurchase(db, tileKeys, deps) {
  const productIds = await productIdsAffectedByTileKeys(db, tileKeys, deps);
  const plan = new Map();
  for (const productId of productIds) {
    const product = regionProductById(productId);
    const productType = String(product && product.type || "").trim().toLowerCase();
    const jobRound = productType === "world"
      ? 7
      : productType === "continent"
        ? 6
        : productType === "macro_region"
          ? 4
          : 2;
    mergeQuotePlanEntry(plan, quotePlanEntryForProduct(
      productId,
      jobRound,
      quoteJobPriorityForRound(jobRound, productId),
      "scene_tile_overlap",
    ));
  }
  return plan;
}

async function markUserProductQuotesStale(db, userId, productIds, deps, reason, timestamp) {
  const safeUserId = String(userId || "").trim();
  const ids = Array.from(new Set((Array.isArray(productIds) ? productIds : [])
    .map((id) => String(id || "").trim().toLowerCase())
    .filter(Boolean)));
  if (!safeUserId || !ids.length) {
    return 0;
  }
  let changed = 0;
  const now = String(timestamp || quoteIsoNow(deps));
  for (const chunk of fixedSizeChunks(ids, SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
    const result = await deps.dbRun(
      db,
      `
        UPDATE user_product_quotes
        SET
          status = 'stale',
          map_state_status = CASE
            WHEN COALESCE(map_state_status, '') = 'ready' THEN 'stale'
            ELSE COALESCE(map_state_status, 'stale')
          END,
          stale_reason = ?,
          error_code = NULL,
          error_message = NULL,
          updated_at = ?
        WHERE user_id = ?
          AND catalog_version = ?
          AND product_id IN (${chunk.map(() => "?").join(",")})
      `,
      [String(reason || "entitlement_changed"), now, safeUserId, REGION_PACK_CATALOG_VERSION, ...chunk],
    );
    changed += Math.max(0, deps.dbMetaChanges(result) || 0);
  }
  return changed;
}

async function cancelSupersededUserProductQuoteJobs(db, userId, entitlementVersion, deps, timestamp) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return 0;
  }
  const now = String(timestamp || quoteIsoNow(deps));
  const result = await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_jobs
      SET status = 'cancelled',
          last_error = 'Superseded by a newer purchase.',
          updated_at = ?,
          finished_at = ?
      WHERE user_id = ?
        AND catalog_version = ?
        AND status = 'queued'
        AND entitlement_version != ?
    `,
    [now, now, safeUserId, REGION_PACK_CATALOG_VERSION, String(entitlementVersion || "")],
  );
  return Math.max(0, deps.dbMetaChanges(result) || 0);
}

async function insertUserProductQuoteBatch(db, userId, pricingVersion, entitlementVersion, deps, options = {}) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return "";
  }
  const now = quoteIsoNow(deps);
  const batchId = userProductQuoteBatchId();
  await deps.dbRun(
    db,
    `
      INSERT INTO user_product_quote_batches (
        id, user_id, trigger_type, trigger_purchase_id, source_product_id,
        pricing_version, entitlement_version, catalog_version, status,
        max_round, queued_job_count, completed_job_count, failed_job_count,
        created_at, updated_at, finished_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 0, 0, 0, ?, ?, NULL)
    `,
    [
      batchId,
      safeUserId,
      String(options && options.triggerType || "entitlement_changed"),
      String(options && options.triggerPurchaseId || "") || null,
      String(options && options.sourceProductId || "") || null,
      String(pricingVersion || ""),
      String(entitlementVersion || ""),
      REGION_PACK_CATALOG_VERSION,
      Math.max(0, Number.parseInt(options && options.maxRound || 0, 10) || 0),
      now,
      now,
    ],
  );
  return batchId;
}

async function updateUserProductQuoteBatchCount(db, batchId, queuedJobCount, deps) {
  const safeBatchId = String(batchId || "").trim();
  if (!safeBatchId) {
    return;
  }
  const count = Math.max(0, Number.parseInt(queuedJobCount || 0, 10) || 0);
  const now = quoteIsoNow(deps);
  await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_batches
      SET queued_job_count = ?,
          status = ?,
          updated_at = ?,
          finished_at = CASE WHEN ? = 0 THEN ? ELSE finished_at END
      WHERE id = ?
    `,
    [count, count > 0 ? "queued" : "finished", now, count, now, safeBatchId],
  );
}

async function ensureUserProductQuoteDeltaTable(db, deps) {
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS user_product_quote_deltas (
        batch_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        catalog_version TEXT NOT NULL,
        pricing_version TEXT NOT NULL,
        entitlement_version TEXT NOT NULL,
        delta_tile_count INTEGER NOT NULL DEFAULT 0,
        delta_paid_tile_count INTEGER NOT NULL DEFAULT 0,
        delta_free_tile_count INTEGER NOT NULL DEFAULT 0,
        delta_base_gross_cents INTEGER NOT NULL DEFAULT 0,
        delta_gross_cents INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        PRIMARY KEY (batch_id, product_id)
      )
    `,
  );
  await deps.dbRun(
    db,
    `
      CREATE INDEX IF NOT EXISTS idx_user_product_quote_deltas_user
      ON user_product_quote_deltas(user_id, catalog_version, product_id)
    `,
  );
}

function userProductQuoteRowIsDeltaEligible(row) {
  if (!row || typeof row !== "object") {
    return false;
  }
  const status = String(row.status || "").trim().toLowerCase();
  if (status !== "ready" || !String(row.quote_id || "").trim()) {
    return false;
  }
  return Math.max(0, Number.parseInt(row.partial_licence_tile_count || 0, 10) || 0) <= 0
    && integerCents(row.partial_licence_credit_cents) <= 0
    && Boolean(userProductQuoteSummaryFromRow(row));
}

async function regionProductIdsContainingExactTileKeys(db, productIds, tileKeys, deps) {
  const ids = Array.from(new Set((Array.isArray(productIds) ? productIds : [])
    .map((id) => String(id || "").trim().toLowerCase())
    .filter((id) => id && regionProductById(id))));
  const keys = normalizeTileKeys(tileKeys || []);
  if (!ids.length || !keys.length) {
    return new Set();
  }
  await ensureRegionPackTileEntryTable(db, deps);
  const productIdsWithOverlap = new Set();
  const productChunks = fixedSizeChunks(ids, 32);
  const tileChunks = fixedSizeChunks(keys, 80);
  for (const productChunk of productChunks) {
    for (const tileChunk of tileChunks) {
      const rows = await deps.dbAll(
        db,
        `
          SELECT DISTINCT region_pack_id AS product_id
          FROM region_pack_tile_entries
          WHERE catalog_version = ?
            AND region_pack_id IN (${productChunk.map(() => "?").join(",")})
            AND tile_key IN (${tileChunk.map(() => "?").join(",")})
        `,
        [REGION_PACK_CATALOG_VERSION, ...productChunk, ...tileChunk],
      );
      for (const row of rows || []) {
        const productId = String(row && row.product_id || "").trim().toLowerCase();
        if (productId) {
          productIdsWithOverlap.add(productId);
        }
      }
    }
  }
  return productIdsWithOverlap;
}

async function materializeUserProductQuoteDeltaAggregates(db, userId, batchId, productIds, deltaTileKeys, pricingVersion, entitlementVersion, deps, options = {}) {
  const safeUserId = String(userId || "").trim();
  const safeBatchId = String(batchId || "").trim();
  const ids = Array.from(new Set((Array.isArray(productIds) ? productIds : [])
    .map((id) => String(id || "").trim().toLowerCase())
    .filter((id) => id && regionProductById(id))));
  const keys = normalizeTileKeys(deltaTileKeys || []);
  const eligibleIds = new Set((Array.isArray(options && options.eligibleProductIds) ? options.eligibleProductIds : ids)
    .map((id) => String(id || "").trim().toLowerCase())
    .filter((id) => id && ids.includes(id)));
  if (!safeUserId || !safeBatchId || !ids.length || !keys.length || !eligibleIds.size) {
    return { ok: true, delta_product_count: 0, delta_tile_count: 0 };
  }
  await ensureUserProductQuoteDeltaTable(db, deps);
  await ensureRegionPackTileEntryTable(db, deps);
  const aggregates = new Map();
  const productChunks = fixedSizeChunks(Array.from(eligibleIds), 24);
  const tileChunks = fixedSizeChunks(keys, 40);
  const coefficient = fullQualityPriceCoefficient();
  for (const productChunk of productChunks) {
    for (const tileChunk of tileChunks) {
      const rowParams = [coefficient, coefficient, coefficient, REGION_PACK_CATALOG_VERSION, ...productChunk, ...tileChunk];
      const rows = await deps.dbAll(
        db,
        `
          SELECT
            region_pack_id AS product_id,
            COUNT(*) AS delta_tile_count,
            COALESCE(SUM(CASE WHEN globally_free = 0 AND CAST(ROUND(base_gross_cents * ?) AS INTEGER) > 0 THEN 1 ELSE 0 END), 0) AS delta_paid_tile_count,
            COALESCE(SUM(CASE WHEN globally_free != 0 OR CAST(ROUND(base_gross_cents * ?) AS INTEGER) <= 0 THEN 1 ELSE 0 END), 0) AS delta_free_tile_count,
            COALESCE(SUM(base_gross_cents), 0) AS delta_base_gross_cents,
            COALESCE(SUM(CAST(ROUND(base_gross_cents * ?) AS INTEGER)), 0) AS delta_gross_cents
          FROM region_pack_tile_entries
          WHERE catalog_version = ?
            AND region_pack_id IN (${productChunk.map(() => "?").join(",")})
            AND tile_key IN (${tileChunk.map(() => "?").join(",")})
          GROUP BY region_pack_id
        `,
        rowParams,
      );
      for (const row of rows || []) {
        const productId = String(row && row.product_id || "").trim().toLowerCase();
        if (!productId) {
          continue;
        }
        const current = aggregates.get(productId) || {
          tile: 0,
          paid: 0,
          free: 0,
          baseGross: 0,
          gross: 0,
        };
        current.tile += Math.max(0, Number.parseInt(row && row.delta_tile_count || 0, 10) || 0);
        current.paid += Math.max(0, Number.parseInt(row && row.delta_paid_tile_count || 0, 10) || 0);
        current.free += Math.max(0, Number.parseInt(row && row.delta_free_tile_count || 0, 10) || 0);
        current.baseGross += Math.max(0, Number.parseInt(row && row.delta_base_gross_cents || 0, 10) || 0);
        current.gross += Math.max(0, Number.parseInt(row && row.delta_gross_cents || 0, 10) || 0);
        aggregates.set(productId, current);
      }
    }
  }
  const now = quoteIsoNow(deps);
  let deltaProductCount = 0;
  let deltaTileCount = 0;
  for (const [productId, aggregate] of aggregates.entries()) {
    if (aggregate.tile <= 0) {
      continue;
    }
    await deps.dbRun(
      db,
      `
        INSERT OR REPLACE INTO user_product_quote_deltas (
          batch_id, user_id, product_id, catalog_version, pricing_version,
          entitlement_version, delta_tile_count, delta_paid_tile_count,
          delta_free_tile_count, delta_base_gross_cents, delta_gross_cents,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      [
        safeBatchId,
        safeUserId,
        productId,
        REGION_PACK_CATALOG_VERSION,
        String(pricingVersion || ""),
        String(entitlementVersion || ""),
        Math.max(0, Math.round(aggregate.tile)),
        Math.max(0, Math.round(aggregate.paid)),
        Math.max(0, Math.round(aggregate.free)),
        Math.max(0, Math.round(aggregate.baseGross)),
        Math.max(0, Math.round(aggregate.gross)),
        now,
      ],
    );
    deltaProductCount += 1;
    deltaTileCount += Math.max(0, Math.round(aggregate.tile));
  }
  return {
    ok: true,
    delta_product_count: deltaProductCount,
    delta_tile_count: deltaTileCount,
    delta_product_ids: Array.from(aggregates.keys()).sort(),
  };
}

async function enqueueUserProductQuotePlan(db, userId, plan, pricingVersion, entitlementVersion, deps, options = {}) {
  const safeUserId = String(userId || "").trim();
  const entries = Array.from((plan instanceof Map ? plan.values() : []))
    .filter((entry) => entry && entry.product_id)
    .sort((a, b) => (a.job_round - b.job_round) || (a.priority - b.priority) || a.product_id.localeCompare(b.product_id));
  if (!safeUserId || !entries.length) {
    return { queued_job_count: 0, affected_product_count: 0, batch_id: "" };
  }
  const maxRound = entries.reduce((max, entry) => Math.max(max, entry.job_round), 0);
  const batchId = await insertUserProductQuoteBatch(db, safeUserId, pricingVersion, entitlementVersion, deps, {
    ...options,
    maxRound,
  });
  const deltaResult = await materializeUserProductQuoteDeltaAggregates(
    db,
    safeUserId,
    batchId,
    entries.map((entry) => entry.product_id),
    options && (options.deltaTileKeys || options.insertedTileKeys),
    pricingVersion,
    entitlementVersion,
    deps,
    { eligibleProductIds: options && options.deltaEligibleProductIds },
  );
  let queued = 0;
  for (const entry of entries) {
    const inserted = await enqueueUserProductQuoteJob(
      db,
      safeUserId,
      entry.product_id,
      pricingVersion,
      entitlementVersion,
      deps,
      {
        ...options,
        batchId,
        jobRound: entry.job_round,
        priority: entry.priority,
        staleReason: String(options && options.staleReason || "entitlement_changed"),
      },
    );
    if (inserted) {
      queued += 1;
    }
  }
  await updateUserProductQuoteBatchCount(db, batchId, queued, deps);
  return {
    queued_job_count: queued,
    affected_product_count: entries.length,
    batch_id: batchId,
    delta_product_count: Math.max(0, Number.parseInt(deltaResult && deltaResult.delta_product_count || 0, 10) || 0),
    delta_tile_count: Math.max(0, Number.parseInt(deltaResult && deltaResult.delta_tile_count || 0, 10) || 0),
  };
}

async function invalidateAndQueueUserProductQuotes(db, userId, deps, options = {}) {
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return { queued_job_count: 0, affected_product_count: 0, stale_quote_count: 0 };
  }
  await deps.ensureCreditTables(db);
  const account = await ensureFreshCreditAccountForUser(db, safeUserId, deps);
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  const sourceProductId = String(options && options.sourceProductId || options && options.regionPackId || "").trim().toLowerCase();
  const tileKeys = normalizeTileKeys(options && options.tileKeys || []);
  const staleReason = String(options && options.staleReason || "entitlement_changed");
  let plan = new Map();
  if (sourceProductId) {
    plan = quoteInvalidationPlanForRegionPackPurchase(sourceProductId);
  } else if (tileKeys.length) {
    plan = await quoteInvalidationPlanForScenePurchase(db, tileKeys, deps);
  } else {
    plan = quoteInvalidationPlanForAllProducts(staleReason);
  }
  const immediateReadyProductIds = new Set((Array.isArray(options && options.immediateReadyProductIds)
    ? options.immediateReadyProductIds
    : [])
    .map((id) => String(id || "").trim().toLowerCase())
    .filter(Boolean));
  for (const productId of immediateReadyProductIds) {
    plan.delete(productId);
  }
  const deltaTileKeys = normalizeTileKeys(
    options && (options.insertedTileKeys || options.deltaTileKeys) || [],
  );
  if (deltaTileKeys.length && plan.size) {
    const productIdsWithExactDelta = await regionProductIdsContainingExactTileKeys(
      db,
      Array.from(plan.keys()),
      deltaTileKeys,
      deps,
    );
    for (const productId of Array.from(plan.keys())) {
      if (!productIdsWithExactDelta.has(productId)) {
        plan.delete(productId);
      }
    }
  }
  const productIds = Array.from(plan.keys());
  let deltaEligibleProductIds = [];
  if (deltaTileKeys.length && productIds.length) {
    const currentQuoteRows = await loadUserProductQuoteRows(
      db,
      safeUserId,
      productIds,
      deps,
      { includeMapState: false },
    );
    deltaEligibleProductIds = productIds.filter((productId) => userProductQuoteRowIsDeltaEligible(currentQuoteRows.get(productId)));
  }
  const staleQuoteCount = await markUserProductQuotesStale(db, safeUserId, productIds, deps, staleReason, quoteIsoNow(deps));
  const cancelledJobCount = await cancelSupersededUserProductQuoteJobs(db, safeUserId, entitlementVersion, deps, quoteIsoNow(deps));
  const result = await enqueueUserProductQuotePlan(db, safeUserId, plan, pricingVersion, entitlementVersion, deps, {
    triggerType: String(options && options.triggerType || "entitlement_changed"),
    triggerPurchaseId: String(options && options.triggerPurchaseId || "") || null,
    sourceProductId: sourceProductId || null,
    staleReason,
    deltaTileKeys,
    deltaEligibleProductIds,
  });
  return {
    ...result,
    stale_quote_count: staleQuoteCount,
    cancelled_job_count: cancelledJobCount,
    immediate_ready_product_count: immediateReadyProductIds.size,
    pricing_version: pricingVersion,
    entitlement_version: entitlementVersion,
  };
}

export async function enqueueDefaultNoPurchaseProductQuoteJobs(db, deps, options = {}) {
  await deps.ensureCreditTables(db);
  const includePaid = options && Object.prototype.hasOwnProperty.call(options, "includePaid")
    ? Boolean(options.includePaid)
    : true;
  const includeBeta = options && Object.prototype.hasOwnProperty.call(options, "includeBeta")
    ? Boolean(options.includeBeta)
    : true;
  const defaultUserIds = [];
  if (includePaid) {
    defaultUserIds.push(DEFAULT_NO_PURCHASE_QUOTE_USER_ID);
  }
  if (includeBeta) {
    defaultUserIds.push(DEFAULT_BETA_FULL_WORLD_QUOTE_USER_ID);
  }
  const products = REGION_PRODUCTS.filter((product) => product && !isHiddenRegionProduct(product));
  const pricingVersion = pricingSettingsCacheKey();
  let queued = 0;
  let requested = 0;
  for (const userId of defaultUserIds) {
    const account = await ensureFreshCreditAccountForUser(db, userId, deps);
    const entitlementVersion = accountEntitlementVersion(account);
    for (const product of products) {
      const productId = normalizedRegionPackProductId(product);
      if (!productId) {
        continue;
      }
      requested += 1;
      const inserted = await enqueueUserProductQuoteJob(db, userId, productId, pricingVersion, entitlementVersion, deps, {
        jobRound: 0,
        priority: userProductQuotePriority(product),
        triggerType: "default_no_purchase_quote_prewarm",
        staleReason: "default_no_purchase_quote_missing",
        fastTrack: Boolean(options && options.fastTrack),
      });
      if (inserted) {
        queued += 1;
      }
    }
  }
  return {
    ok: true,
    default_user_count: defaultUserIds.length,
    product_count: products.length,
    requested_job_count: requested,
    queued_job_count: queued,
    pricing_version: pricingVersion,
  };
}

async function materializePurchasedRegionPackQuoteNow(db, userId, product, deps, purchasedQuote = null) {
  const safeUserId = String(userId || "").trim();
  const productId = String(product && product.id || "").trim().toLowerCase();
  if (!safeUserId || !productId || !product) {
    return { error: "invalid_purchased_region_pack_quote_context" };
  }
  const account = await ensureFreshCreditAccountForUser(db, safeUserId, deps);
  const sourceSummary = regionPackQuoteSummary(purchasedQuote);
  const totalTiles = Math.max(0, Number.parseInt(sourceSummary.total_tiles || 0, 10) || 0);
  const fullPriceCents = integerCents(sourceSummary.full_price_cents);
  const quoteId = await regionPackQuoteIdFor(safeUserId, product, account, deps);
  const now = quoteIsoNow(deps);
  const summary = {
    new_tiles: 0,
    charged_tiles: 0,
    total_tiles: totalTiles,
    already_licenced_tiles: totalTiles,
    partial_licence_tiles: 0,
    free_tiles: 0,
    full_price_eur: centsToEur(fullPriceCents),
    full_price_cents: fullPriceCents,
    already_licenced_deduction_eur: centsToEur(fullPriceCents),
    already_licenced_deduction_cents: fullPriceCents,
    already_licenced_saving_eur: centsToEur(fullPriceCents),
    partial_licence_credit_eur: 0,
    partial_licence_credit_cents: 0,
    discount_percent: 0,
    discount_eur: 0,
    discount_cents: 0,
    price_eur: 0,
    price_cents: 0,
  };
  const quote = await storePricingQuote(db, {
    ok: true,
    quote_id: quoteId,
    quote_type: "region_pack",
    user_id: safeUserId,
    subject_id: productId,
    region_pack_id: productId,
    pricing_version: pricingSettingsCacheKey(),
    entitlement_version: accountEntitlementVersion(account),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    currency: "eur",
    amount_cents: 0,
    amount_eur: 0,
    summary,
    region_pack: regionProductPublicPayload(product),
    created_at: now,
    expires_at: addMinutesIsoFromDeps(deps, REGION_PACK_QUOTE_TTL_MINUTES),
  }, deps);
  const storedSummary = await storeUserProductQuoteFromQuote(db, quote, deps, { mapStateStatus: "stale" });
  return { ok: true, quote, summary: storedSummary };
}

async function acquireUserProductQuoteJobLock(db, deps, workerId) {
  const now = quoteIsoNow(deps);
  const expiresAt = addSecondsIsoFromDeps(deps, USER_PRODUCT_QUOTE_JOB_LOCK_TTL_SECONDS);
  await deps.dbRun(
    db,
    `DELETE FROM user_product_quote_job_locks WHERE lock_name = ? AND expires_at <= ?`,
    [USER_PRODUCT_QUOTE_JOB_LOCK_NAME, now],
  );
  const token = userProductQuoteJobId();
  const result = await deps.dbRun(
    db,
    `
      INSERT OR IGNORE INTO user_product_quote_job_locks (
        lock_name, lock_token, worker_id, current_job_id, locked_at, expires_at, updated_at
      ) VALUES (?, ?, ?, NULL, ?, ?, ?)
    `,
    [USER_PRODUCT_QUOTE_JOB_LOCK_NAME, token, workerId, now, expiresAt, now],
  );
  if (deps.dbMetaChanges(result) <= 0) {
    return "";
  }
  return token;
}

async function releaseUserProductQuoteJobLock(db, deps, lockToken) {
  const safeToken = String(lockToken || "").trim();
  if (!safeToken) {
    return;
  }
  await deps.dbRun(
    db,
    `DELETE FROM user_product_quote_job_locks WHERE lock_name = ? AND lock_token = ?`,
    [USER_PRODUCT_QUOTE_JOB_LOCK_NAME, safeToken],
  );
}

async function requeueStaleRunningUserProductQuoteJobs(db, deps) {
  const now = quoteIsoNow(deps);
  const cutoff = addRawSecondsIsoFromDeps(deps, -USER_PRODUCT_QUOTE_JOB_STALE_RUNNING_SECONDS);
  const result = await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_jobs
      SET status = 'queued',
          available_at = ?,
          lock_token = NULL,
          locked_at = NULL,
          worker_id = NULL,
          last_error = ?,
          updated_at = ?
      WHERE status = 'running'
        AND catalog_version = ?
        AND locked_at <= ?
        AND COALESCE(attempts, 0) < ?
    `,
    [
      now,
      "Recovered stale running quote job after Worker interruption.",
      now,
      REGION_PACK_CATALOG_VERSION,
      cutoff,
      USER_PRODUCT_QUOTE_JOB_MAX_ATTEMPTS,
    ],
  );
  const recovered = deps.dbMetaChanges(result);
  const failed = await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_jobs
      SET status = 'failed',
          lock_token = NULL,
          locked_at = NULL,
          worker_id = NULL,
          last_error = ?,
          updated_at = ?
      WHERE status = 'running'
        AND catalog_version = ?
        AND locked_at <= ?
        AND COALESCE(attempts, 0) >= ?
    `,
    [
      "Quote job failed after repeated Worker interruptions.",
      now,
      REGION_PACK_CATALOG_VERSION,
      cutoff,
      USER_PRODUCT_QUOTE_JOB_MAX_ATTEMPTS,
    ],
  );
  return { recovered, failed: deps.dbMetaChanges(failed) };
}

async function claimNextUserProductQuoteJob(db, deps, lockToken, workerId) {
  const now = quoteIsoNow(deps);
  const row = await deps.dbGet(
    db,
    `
      SELECT *
      FROM user_product_quote_jobs
      WHERE status = 'queued'
        AND catalog_version = ?
        AND available_at <= ?
      ORDER BY job_round ASC, priority ASC, available_at ASC, created_at ASC
      LIMIT 1
    `,
    [REGION_PACK_CATALOG_VERSION, now],
  );
  if (!row || !row.id) {
    return null;
  }
  const result = await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_jobs
      SET
        status = 'running',
        attempts = COALESCE(attempts, 0) + 1,
        locked_at = ?,
        lock_token = ?,
        worker_id = ?,
        updated_at = ?
      WHERE id = ?
        AND status = 'queued'
    `,
    [now, lockToken, workerId, now, String(row.id || "")],
  );
  if (deps.dbMetaChanges(result) <= 0) {
    return null;
  }
  await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_job_locks
      SET current_job_id = ?,
          updated_at = ?
      WHERE lock_name = ?
        AND lock_token = ?
    `,
    [String(row.id || ""), now, USER_PRODUCT_QUOTE_JOB_LOCK_NAME, lockToken],
  );
  return {
    ...row,
    attempts: Math.max(1, Number.parseInt(row.attempts || 0, 10) + 1 || 1),
  };
}

async function refreshUserProductQuoteBatchStatus(db, batchId, deps) {
  const safeBatchId = String(batchId || "").trim();
  if (!safeBatchId) {
    return null;
  }
  const row = await deps.dbGet(
    db,
    `
      SELECT
        COUNT(*) AS total_count,
        SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END) AS active_count,
        SUM(CASE WHEN status = 'finished' THEN 1 ELSE 0 END) AS completed_count,
        SUM(CASE WHEN status IN ('failed', 'error') THEN 1 ELSE 0 END) AS failed_count
      FROM user_product_quote_jobs
      WHERE batch_id = ?
    `,
    [safeBatchId],
  );
  const active = Math.max(0, Number.parseInt(row && row.active_count || 0, 10) || 0);
  const completed = Math.max(0, Number.parseInt(row && row.completed_count || 0, 10) || 0);
  const failed = Math.max(0, Number.parseInt(row && row.failed_count || 0, 10) || 0);
  const status = active > 0 ? "queued" : (failed > 0 ? "finished_with_errors" : "finished");
  const now = quoteIsoNow(deps);
  await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_batches
      SET
        completed_job_count = ?,
        failed_job_count = ?,
        status = ?,
        updated_at = ?,
        finished_at = CASE WHEN ? = 0 THEN COALESCE(finished_at, ?) ELSE finished_at END
      WHERE id = ?
    `,
    [completed, failed, status, now, active, now, safeBatchId],
  );
  return { active_count: active, completed_count: completed, failed_count: failed, status };
}

function utf8ByteLength(value) {
  const text = String(value || "");
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(text).length;
  }
  if (typeof Buffer !== "undefined") {
    return Buffer.byteLength(text, "utf8");
  }
  return text.length;
}

async function userProductMapStateStoragePayload(env, quote, mapState) {
  if (!mapState) {
    return null;
  }
  const payloadJson = JSON.stringify({ map_state: mapState });
  const byteLength = utf8ByteLength(payloadJson);
  if (byteLength <= USER_PRODUCT_MAP_STATE_INLINE_MAX_BYTES) {
    return payloadJson;
  }
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.put !== "function") {
    throw new Error("map_state_object_store_unavailable");
  }
  const key = userProductMapStateObjectKey(
    env,
    quote && quote.user_id,
    quote && (quote.subject_id || quote.region_pack_id),
    quote && quote.pricing_version,
    quote && quote.entitlement_version,
  );
  await bucket.put(key, payloadJson, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    customMetadata: {
      catalog_version: REGION_PACK_CATALOG_VERSION,
      product_id: String(quote && (quote.subject_id || quote.region_pack_id) || ""),
      pricing_version: String(quote && quote.pricing_version || ""),
      entitlement_version: String(quote && quote.entitlement_version || ""),
      bytes: String(byteLength),
    },
  });
  return JSON.stringify({
    map_state_ref: {
      storage: "r2",
      key,
      bytes: byteLength,
      schema: Number.parseInt(mapState && mapState.schema || 0, 10) || null,
    },
  });
}

async function storeUserProductMapStateManifest(db, quote, mapState, deps, options = {}) {
  const userId = String(quote && quote.user_id || "").trim();
  const productId = String(quote && (quote.subject_id || quote.region_pack_id) || "").trim().toLowerCase();
  if (!db || !userId || !productId || !mapState || typeof mapState !== "object") {
    throw new Error("invalid_user_product_map_state_manifest");
  }
  const now = quoteIsoNow(deps);
  const status = String(options && options.status || "building").trim().toLowerCase() || "building";
  await deps.dbRun(
    db,
    `
      UPDATE user_product_quotes
      SET map_state_status = ?,
          map_state_json = ?,
          map_state_updated_at = CASE WHEN ? = 'ready' THEN ? ELSE map_state_updated_at END,
          updated_at = ?
      WHERE user_id = ?
        AND product_id = ?
        AND catalog_version = ?
        AND pricing_version = ?
        AND entitlement_version = ?
    `,
    [
      status,
      JSON.stringify({ map_state: mapState }),
      status,
      now,
      now,
      userId,
      productId,
      REGION_PACK_CATALOG_VERSION,
      String(quote && quote.pricing_version || ""),
      String(quote && quote.entitlement_version || ""),
    ],
  );
}

async function storeUserProductQuoteFromQuote(db, quote, deps, options = {}) {
  const productId = String(quote && (quote.subject_id || quote.region_pack_id) || "").trim().toLowerCase();
  const userId = String(quote && quote.user_id || "").trim();
  if (!quote || !userId || !productId) {
    throw new Error("invalid_user_product_quote_payload");
  }
  const summary = regionPackQuoteSummary(quote);
  const now = quoteIsoNow(deps);
  const mapState = options && options.mapState && typeof options.mapState === "object"
    ? options.mapState
    : null;
  const mapStateStatus = mapState ? "ready" : String(options && options.mapStateStatus || "stale");
  const mapStateJson = mapState ? await userProductMapStateStoragePayload(options && options.env, quote, mapState) : null;
  const mapStateUpdatedAt = mapState ? now : null;
  await deps.dbRun(
    db,
    `
      INSERT INTO user_product_quotes (
        user_id, product_id, catalog_version, pricing_version, entitlement_version,
        quote_id, status, currency, full_price_cents, already_licenced_cents,
        partial_licence_credit_cents, discount_percent, discount_cents,
        final_price_cents, total_tile_count, new_tile_count, charged_tile_count,
        already_licenced_tile_count, partial_licence_tile_count, free_tile_count,
        summary_json, map_state_status, map_state_json, map_state_updated_at,
        stale_reason, error_code, error_message, requested_at, calculated_at,
        created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
      ON CONFLICT(user_id, product_id, catalog_version) DO UPDATE SET
        pricing_version = excluded.pricing_version,
        entitlement_version = excluded.entitlement_version,
        quote_id = excluded.quote_id,
        status = 'ready',
        currency = excluded.currency,
        full_price_cents = excluded.full_price_cents,
        already_licenced_cents = excluded.already_licenced_cents,
        partial_licence_credit_cents = excluded.partial_licence_credit_cents,
        discount_percent = excluded.discount_percent,
        discount_cents = excluded.discount_cents,
        final_price_cents = excluded.final_price_cents,
        total_tile_count = excluded.total_tile_count,
        new_tile_count = excluded.new_tile_count,
        charged_tile_count = excluded.charged_tile_count,
        already_licenced_tile_count = excluded.already_licenced_tile_count,
        partial_licence_tile_count = excluded.partial_licence_tile_count,
        free_tile_count = excluded.free_tile_count,
        summary_json = excluded.summary_json,
        map_state_status = CASE
          WHEN excluded.map_state_status = 'ready' THEN excluded.map_state_status
          WHEN user_product_quotes.pricing_version = excluded.pricing_version
           AND user_product_quotes.entitlement_version = excluded.entitlement_version
          THEN user_product_quotes.map_state_status
          ELSE 'stale'
        END,
        map_state_json = CASE
          WHEN excluded.map_state_status = 'ready' THEN excluded.map_state_json
          WHEN user_product_quotes.pricing_version = excluded.pricing_version
           AND user_product_quotes.entitlement_version = excluded.entitlement_version
          THEN user_product_quotes.map_state_json
          ELSE NULL
        END,
        map_state_updated_at = CASE
          WHEN excluded.map_state_status = 'ready' THEN excluded.map_state_updated_at
          WHEN user_product_quotes.pricing_version = excluded.pricing_version
           AND user_product_quotes.entitlement_version = excluded.entitlement_version
          THEN user_product_quotes.map_state_updated_at
          ELSE NULL
        END,
        stale_reason = NULL,
        error_code = NULL,
        error_message = NULL,
        requested_at = excluded.requested_at,
        calculated_at = excluded.calculated_at,
        updated_at = excluded.updated_at
    `,
    [
      userId,
      productId,
      REGION_PACK_CATALOG_VERSION,
      String(quote.pricing_version || ""),
      String(quote.entitlement_version || ""),
      String(quote.quote_id || ""),
      String(quote.currency || "eur"),
      integerCents(summary.full_price_cents),
      integerCents(summary.already_licenced_deduction_cents),
      integerCents(summary.partial_licence_credit_cents),
      Math.max(0, Number.parseInt(summary.discount_percent || 0, 10) || 0),
      integerCents(summary.discount_cents),
      integerCents(summary.price_cents),
      Math.max(0, Number.parseInt(summary.total_tiles || 0, 10) || 0),
      Math.max(0, Number.parseInt(summary.new_tiles || 0, 10) || 0),
      Math.max(0, Number.parseInt(summary.charged_tiles || 0, 10) || 0),
      Math.max(0, Number.parseInt(summary.already_licenced_tiles || 0, 10) || 0),
      Math.max(0, Number.parseInt(summary.partial_licence_tiles || 0, 10) || 0),
      Math.max(0, Number.parseInt(summary.free_tiles || 0, 10) || 0),
      JSON.stringify(summary),
      mapStateStatus,
      mapStateJson,
      mapStateUpdatedAt,
      now,
      now,
      now,
      now,
    ],
  );
  return summary;
}

async function finishUserProductQuoteJob(db, job, deps, status, message = "") {
  const now = quoteIsoNow(deps);
  await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_jobs
      SET status = ?,
          last_error = ?,
          lock_token = NULL,
          locked_at = NULL,
          worker_id = NULL,
          updated_at = ?,
          finished_at = ?
      WHERE id = ?
    `,
    [String(status || "finished"), String(message || "") || null, now, now, String(job && job.id || "")],
  );
  await refreshUserProductQuoteBatchStatus(db, job && job.batch_id, deps);
}

async function retryOrFailUserProductQuoteJob(db, job, deps, error) {
  const attempts = Math.max(0, Number.parseInt(job && job.attempts || 0, 10) || 0);
  const now = quoteIsoNow(deps);
  const message = String(error && error.message || error || "quote_job_failed").slice(0, 500);
  if (attempts < USER_PRODUCT_QUOTE_JOB_MAX_ATTEMPTS) {
    const delaySeconds = Math.min(15 * attempts, 120);
    await deps.dbRun(
      db,
      `
        UPDATE user_product_quote_jobs
        SET status = 'queued',
            available_at = ?,
            last_error = ?,
            lock_token = NULL,
            locked_at = NULL,
            worker_id = NULL,
            updated_at = ?
        WHERE id = ?
      `,
      [addSecondsIsoFromDeps(deps, delaySeconds), message, now, String(job && job.id || "")],
    );
    await refreshUserProductQuoteBatchStatus(db, job && job.batch_id, deps);
    return "requeued";
  }
  await deps.dbRun(
    db,
    `
      INSERT INTO user_product_quotes (
        user_id, product_id, catalog_version, pricing_version, entitlement_version,
        quote_id, status, currency, stale_reason, error_code, error_message,
        requested_at, calculated_at, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, 'error', 'eur', ?, 'quote_job_failed', ?, ?, ?, ?, ?)
      ON CONFLICT(user_id, product_id, catalog_version) DO UPDATE SET
        pricing_version = excluded.pricing_version,
        entitlement_version = excluded.entitlement_version,
        quote_id = excluded.quote_id,
        status = 'error',
        stale_reason = excluded.stale_reason,
        error_code = excluded.error_code,
        error_message = excluded.error_message,
        requested_at = excluded.requested_at,
        calculated_at = excluded.calculated_at,
        updated_at = excluded.updated_at
    `,
    [
      String(job && job.user_id || ""),
      String(job && job.product_id || "").trim().toLowerCase(),
      REGION_PACK_CATALOG_VERSION,
      String(job && job.pricing_version || ""),
      String(job && job.entitlement_version || ""),
      `upq_error_${String(job && job.id || "").replace(/[^A-Za-z0-9]/g, "").slice(0, 40)}`,
      String(job && job.stale_reason || "quote_job_failed"),
      message,
      now,
      now,
      now,
      now,
    ],
  );
  await finishUserProductQuoteJob(db, job, deps, "failed", message);
  return "failed";
}

function userProductQuoteJobWantsMapState(job) {
  const triggerType = String(job && job.trigger_type || "").trim().toLowerCase();
  const staleReason = String(job && job.stale_reason || "").trim().toLowerCase();
  return triggerType.includes("map_state") || staleReason.includes("map_state");
}

function userProductQuoteJobIsShardedMapStep(job) {
  const triggerType = String(job && job.trigger_type || "").trim().toLowerCase();
  const staleReason = String(job && job.stale_reason || "").trim().toLowerCase();
  return triggerType.includes("map_state_shard") || staleReason.includes("map_state_shard");
}

function userProductQuoteMapTileCount(product) {
  return Math.max(0, Number.parseInt(product && product.tile_count || 0, 10) || 0);
}

function userProductQuoteMapPriority(product) {
  const type = String(product && product.type || "").trim().toLowerCase();
  const tileCount = userProductQuoteMapTileCount(product);
  if (type === "world") {
    return 280;
  }
  if (type === "continent" || tileCount > 5000) {
    return 240;
  }
  if (tileCount > USER_PRODUCT_QUOTE_HEAVY_MAP_TILE_COUNT) {
    return 220;
  }
  if (tileCount > 500) {
    return 180;
  }
  if (tileCount > USER_PRODUCT_QUOTE_MEDIUM_MAP_TILE_COUNT) {
    return 140;
  }
  return 100;
}

function userProductQuotePriority(product) {
  const type = String(product && product.type || "").trim().toLowerCase();
  const tileCount = userProductQuoteMapTileCount(product);
  if (type === "world") {
    return 160;
  }
  if (type === "continent" || tileCount > 5000) {
    return 130;
  }
  if (tileCount > USER_PRODUCT_QUOTE_HEAVY_MAP_TILE_COUNT) {
    return 100;
  }
  if (tileCount > 500) {
    return 70;
  }
  if (tileCount > USER_PRODUCT_QUOTE_MEDIUM_MAP_TILE_COUNT) {
    return 45;
  }
  return 25;
}

function userProductQuoteMapIsHeavy(product) {
  const type = String(product && product.type || "").trim().toLowerCase();
  return type === "world"
    || type === "continent"
    || userProductQuoteMapTileCount(product) > USER_PRODUCT_QUOTE_HEAVY_MAP_TILE_COUNT;
}

async function deferClaimedUserProductQuoteJob(db, job, deps, reason, delaySeconds = 5) {
  const now = quoteIsoNow(deps);
  await deps.dbRun(
    db,
    `
      UPDATE user_product_quote_jobs
      SET status = 'queued',
          attempts = CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
          available_at = ?,
          last_error = ?,
          lock_token = NULL,
          locked_at = NULL,
          worker_id = NULL,
          updated_at = ?
      WHERE id = ?
    `,
    [
      addRawSecondsIsoFromDeps(deps, delaySeconds),
      String(reason || "deferred").slice(0, 500),
      now,
      String(job && job.id || ""),
    ],
  );
  await refreshUserProductQuoteBatchStatus(db, job && job.batch_id, deps);
}

async function loadUserProductQuoteDelta(db, job, deps) {
  const batchId = String(job && job.batch_id || "").trim();
  const userId = String(job && job.user_id || "").trim();
  const productId = String(job && job.product_id || "").trim().toLowerCase();
  if (!batchId || !userId || !productId) {
    return null;
  }
  await ensureUserProductQuoteDeltaTable(db, deps);
  const row = await deps.dbGet(
    db,
    `
      SELECT *
      FROM user_product_quote_deltas
      WHERE batch_id = ?
        AND user_id = ?
        AND product_id = ?
        AND catalog_version = ?
      LIMIT 1
    `,
    [batchId, userId, productId, REGION_PACK_CATALOG_VERSION],
  );
  if (!row) {
    return null;
  }
  return {
    delta_tile_count: Math.max(0, Number.parseInt(row.delta_tile_count || 0, 10) || 0),
    delta_paid_tile_count: Math.max(0, Number.parseInt(row.delta_paid_tile_count || 0, 10) || 0),
    delta_free_tile_count: Math.max(0, Number.parseInt(row.delta_free_tile_count || 0, 10) || 0),
    delta_base_gross_cents: Math.max(0, Number.parseInt(row.delta_base_gross_cents || 0, 10) || 0),
    delta_gross_cents: Math.max(0, Number.parseInt(row.delta_gross_cents || 0, 10) || 0),
  };
}

async function materializeUserProductQuoteFromDeltaJob(db, job, product, account, deps) {
  const delta = await loadUserProductQuoteDelta(db, job, deps);
  if (!delta || delta.delta_tile_count <= 0) {
    return null;
  }
  const userId = String(job && job.user_id || "").trim();
  const productId = String(job && job.product_id || "").trim().toLowerCase();
  const rows = await loadUserProductQuoteRows(db, userId, [productId], deps, { includeMapState: false });
  const existingRow = rows.get(productId) || null;
  if (!existingRow || !userProductQuoteRowIsDeltaEligible({
    ...existingRow,
    status: "ready",
  })) {
    return null;
  }
  const previous = userProductQuoteSummaryFromRow(existingRow);
  if (!previous || Math.max(0, Number.parseInt(previous.partial_licence_tiles || 0, 10) || 0) > 0 || integerCents(previous.partial_licence_credit_cents) > 0) {
    return null;
  }
  const fullPriceCents = integerCents(previous.full_price_cents);
  const oldAlreadyCents = integerCents(previous.already_licenced_deduction_cents);
  const oldPartialCents = integerCents(previous.partial_licence_credit_cents);
  const deltaGrossCents = Math.min(
    Math.max(0, fullPriceCents - oldAlreadyCents - oldPartialCents),
    integerCents(delta.delta_gross_cents),
  );
  if (deltaGrossCents <= 0 && delta.delta_tile_count <= 0) {
    return null;
  }
  const discountPercent = Math.max(0, Number.parseInt(previous.discount_percent || regionProductDiscountPercent(product), 10) || 0);
  const alreadyCents = Math.min(fullPriceCents, oldAlreadyCents + deltaGrossCents);
  const chargeableCents = Math.max(0, fullPriceCents - alreadyCents - oldPartialCents);
  const amounts = discountedRegionPackAmountCents(chargeableCents, discountPercent);
  const totalTiles = Math.max(0, Number.parseInt(previous.total_tiles || 0, 10) || 0);
  const alreadyTiles = Math.min(
    totalTiles,
    Math.max(0, Number.parseInt(previous.already_licenced_tiles || 0, 10) || 0) + delta.delta_tile_count,
  );
  const summary = {
    new_tiles: Math.max(0, Number.parseInt(previous.new_tiles || 0, 10) - delta.delta_tile_count),
    charged_tiles: Math.max(0, Number.parseInt(previous.charged_tiles || 0, 10) - delta.delta_paid_tile_count),
    total_tiles: totalTiles,
    already_licenced_tiles: alreadyTiles,
    partial_licence_tiles: 0,
    free_tiles: Math.max(0, Number.parseInt(previous.free_tiles || 0, 10) - delta.delta_free_tile_count),
    full_price_eur: centsToEur(fullPriceCents),
    full_price_cents: fullPriceCents,
    already_licenced_deduction_eur: centsToEur(alreadyCents),
    already_licenced_deduction_cents: alreadyCents,
    already_licenced_saving_eur: centsToEur(alreadyCents),
    partial_licence_credit_eur: 0,
    partial_licence_credit_cents: 0,
    discount_percent: discountPercent,
    discount_eur: centsToEur(amounts.discount_cents),
    discount_cents: amounts.discount_cents,
    price_eur: centsToEur(amounts.price_cents),
    price_cents: amounts.price_cents,
  };
  const now = quoteIsoNow(deps);
  const quoteId = await regionPackQuoteIdFor(userId, product, account, deps);
  const quote = await storePricingQuote(db, {
    ok: true,
    quote_id: quoteId,
    quote_type: "region_pack",
    user_id: userId,
    subject_id: productId,
    region_pack_id: productId,
    pricing_version: pricingSettingsCacheKey(),
    entitlement_version: accountEntitlementVersion(account),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    currency: "eur",
    amount_cents: integerCents(summary.price_cents),
    amount_eur: centsToEur(summary.price_cents),
    summary,
    region_pack: regionProductPublicPayload(product),
    created_at: now,
    expires_at: addMinutesIsoFromDeps(deps, REGION_PACK_QUOTE_TTL_MINUTES),
  }, deps);
  const storedSummary = await storeUserProductQuoteFromQuote(db, quote, deps);
  return { quote, summary: storedSummary, delta };
}

async function processSingleUserProductQuoteJob(db, job, deps, runContext = {}) {
  const userId = String(job && job.user_id || "").trim();
  const productId = String(job && job.product_id || "").trim().toLowerCase();
  const product = regionProductById(productId);
  if (!userId || !product) {
    await finishUserProductQuoteJob(db, job, deps, "cancelled", "Product is no longer available.");
    return { status: "cancelled", reason: "invalid_product" };
  }
  const accountCache = runContext && runContext.accountByUser instanceof Map
    ? runContext.accountByUser
    : null;
  let account = accountCache ? accountCache.get(userId) : null;
  if (!account) {
    account = await ensureFreshCreditAccountForUser(db, userId, deps);
    if (accountCache) {
      accountCache.set(userId, account);
    }
  }
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  if (
    String(job.pricing_version || "") !== pricingVersion
    || String(job.entitlement_version || "") !== entitlementVersion
    || String(job.catalog_version || "") !== REGION_PACK_CATALOG_VERSION
  ) {
    await finishUserProductQuoteJob(db, job, deps, "cancelled", "Superseded by newer pricing or entitlement version.");
    return { status: "cancelled", reason: "superseded" };
  }
  const jobIncludesMapState = userProductQuoteJobWantsMapState(job);
  const ownershipContextCache = runContext && runContext.ownershipContextByVersion instanceof Map
    ? runContext.ownershipContextByVersion
    : null;
  const ownershipContextKey = `${userId}:${pricingVersion}:${entitlementVersion}`;
  let pricingOwnershipContext = ownershipContextCache ? ownershipContextCache.get(ownershipContextKey) : null;
  if (!pricingOwnershipContext && !jobIncludesMapState) {
    pricingOwnershipContext = await regionPackPricingOwnershipContext(db, userId, account, deps);
    if (ownershipContextCache) {
      ownershipContextCache.set(ownershipContextKey, pricingOwnershipContext);
    }
  }
  let quote = null;
  let summary = null;
  let existingQuoteRow = null;
  if (jobIncludesMapState) {
    const quoteRows = await loadUserProductQuoteRows(db, userId, [productId], deps, { includeMapState: true });
    existingQuoteRow = quoteRows.get(productId) || null;
    if (productQuoteStatus(existingQuoteRow, pricingVersion, entitlementVersion) === "ready") {
      quote = userProductQuoteFromRow(existingQuoteRow);
      summary = quote && quote.summary;
    }
  }
  if (!quote) {
    const deltaQuote = !jobIncludesMapState
      ? await materializeUserProductQuoteFromDeltaJob(db, job, product, account, deps)
      : null;
    if (deltaQuote && deltaQuote.quote) {
      quote = deltaQuote.quote;
      summary = deltaQuote.summary;
    }
  }
  if (!quote) {
    if (!pricingOwnershipContext) {
      pricingOwnershipContext = await regionPackPricingOwnershipContext(db, userId, account, deps);
      if (ownershipContextCache) {
        ownershipContextCache.set(ownershipContextKey, pricingOwnershipContext);
      }
    }
    quote = await createRegionPackQuote(db, userId, product, deps, { account, pricingOwnershipContext });
    if (!quote || quote.error) {
      const message = quote && (quote.error || quote.status) || "quote_creation_failed";
      throw new Error(String(message));
    }
    summary = await storeUserProductQuoteFromQuote(db, quote, deps);
  }
  // Quote payloads are the only materialized pricing source. Map overlays are
  // generated on demand by bounded read-only chunk endpoints, so quote jobs must
  // never do map-state work or enqueue map-state follow-ups.
  if (jobIncludesMapState) {
    await finishUserProductQuoteJob(db, job, deps, "finished");
    return {
      status: "quote_ready_map_on_demand",
      product_id: productId,
      quote_id: String(quote.quote_id || ""),
      final_price_cents: integerCents(summary && summary.price_cents),
    };
  }
  await finishUserProductQuoteJob(db, job, deps, "finished");
  return {
    status: "finished",
    product_id: productId,
    quote_id: String(quote.quote_id || ""),
    final_price_cents: integerCents(summary && summary.price_cents),
  };
}

export async function processUserProductQuoteJobs(db, env = {}, deps = {}, options = {}) {
  if (!db || !deps || typeof deps.dbRun !== "function") {
    return { ok: false, error: "quote_job_db_unavailable" };
  }
  await deps.ensureCreditTables(db);
  if (!Boolean(options && options.skipPricingSettingsLoad)) {
    await ensureRuntimePricingSettings(env, deps);
  }
  const maxJobs = Math.max(1, Math.min(60, Number.parseInt(options && options.maxJobs || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_JOBS, 10) || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_JOBS));
  const maxMs = Math.max(500, Math.min(28000, Number.parseInt(options && options.maxMs || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_MS, 10) || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_MS));
  const maxMapJobs = Math.max(0, Math.min(30, Number.parseInt(options && options.maxMapJobs || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_MAP_JOBS, 10) || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_MAP_JOBS));
  const maxHeavyMapJobs = Math.max(0, Math.min(maxMapJobs, Number.parseInt(options && options.maxHeavyMapJobs || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_HEAVY_MAP_JOBS, 10) || USER_PRODUCT_QUOTE_JOB_DEFAULT_MAX_HEAVY_MAP_JOBS));
  const workerId = userProductQuoteWorkerId(deps);
  const runContext = {
    env,
    accountByUser: new Map(),
    ownershipContextByVersion: new Map(),
  };
  const lockToken = await acquireUserProductQuoteJobLock(db, deps, workerId);
  if (!lockToken) {
    return { ok: true, lock_acquired: false, processed: 0, message: "quote_job_processor_already_running" };
  }
  const startedMs = monotonicNowMs();
  const results = [];
  let processed = 0;
  let requeued = 0;
  let failed = 0;
  let cancelled = 0;
  let staleRecovered = 0;
  let staleFailed = 0;
  let mapProcessed = 0;
  let heavyMapProcessed = 0;
  let mapDeferred = 0;
  try {
    const stale = await requeueStaleRunningUserProductQuoteJobs(db, deps);
    staleRecovered = Math.max(0, Number.parseInt(stale && stale.recovered || 0, 10) || 0);
    staleFailed = Math.max(0, Number.parseInt(stale && stale.failed || 0, 10) || 0);
    while (processed < maxJobs && (monotonicNowMs() - startedMs) < maxMs) {
      const job = await claimNextUserProductQuoteJob(db, deps, lockToken, workerId);
      if (!job) {
        break;
      }
      const jobIncludesMapState = userProductQuoteJobWantsMapState(job);
      const jobProduct = jobIncludesMapState
        ? regionProductById(String(job && job.product_id || "").trim().toLowerCase())
        : null;
      const jobIsHeavyMap = jobIncludesMapState
        && userProductQuoteMapIsHeavy(jobProduct)
        && !userProductQuoteJobIsShardedMapStep(job);
      if (jobIncludesMapState && mapProcessed >= maxMapJobs) {
        await deferClaimedUserProductQuoteJob(db, job, deps, "Deferred to keep map-state batch bounded.", 2);
        mapDeferred += 1;
        break;
      }
      if (jobIsHeavyMap && heavyMapProcessed >= maxHeavyMapJobs) {
        await deferClaimedUserProductQuoteJob(db, job, deps, "Deferred to keep large map-state jobs isolated.", 8);
        mapDeferred += 1;
        if (mapDeferred >= 8) {
          break;
        }
        continue;
      }
      try {
        const result = await processSingleUserProductQuoteJob(db, job, deps, runContext);
        results.push(result);
        if (result && result.status === "cancelled") {
          cancelled += 1;
        } else {
          processed += 1;
        }
        if (jobIncludesMapState && !(result && result.status === "cancelled")) {
          mapProcessed += 1;
          if (jobIsHeavyMap) {
            heavyMapProcessed += 1;
          }
        }
        if ((monotonicNowMs() - startedMs) >= Math.max(500, maxMs - 1500)) {
          break;
        }
      } catch (error) {
        const retryStatus = await retryOrFailUserProductQuoteJob(db, job, deps, error);
        if (retryStatus === "requeued") {
          requeued += 1;
        } else {
          failed += 1;
        }
        results.push({
          status: retryStatus,
          product_id: String(job && job.product_id || ""),
          error: String(error && error.message || error || "quote_job_failed"),
        });
        if (jobIncludesMapState) {
          break;
        }
      }
    }
  } finally {
    await releaseUserProductQuoteJobLock(db, deps, lockToken);
  }
  return {
    ok: true,
    lock_acquired: true,
    processed,
    requeued,
    failed,
    cancelled,
    stale_recovered: staleRecovered,
    stale_failed: staleFailed,
    map_processed: mapProcessed,
    heavy_map_processed: heavyMapProcessed,
    map_deferred: mapDeferred,
    max_jobs: maxJobs,
    max_ms: maxMs,
    max_map_jobs: maxMapJobs,
    max_heavy_map_jobs: maxHeavyMapJobs,
    elapsed_ms: Math.round(monotonicNowMs() - startedMs),
    results,
  };
}

async function loadUserProductQuoteRows(db, userId, productIds, deps, options = {}) {
  const ids = Array.from(new Set((Array.isArray(productIds) ? productIds : [])
    .map((id) => String(id || "").trim().toLowerCase())
    .filter(Boolean)));
  if (!ids.length) {
    return new Map();
  }
  const includeMapState = Boolean(options && options.includeMapState);
  const placeholders = ids.map(() => "?").join(", ");
  const rows = await deps.dbAll(
    db,
    `
      SELECT user_id, product_id, catalog_version, pricing_version, entitlement_version,
             quote_id, status, currency, full_price_cents, already_licenced_cents,
             partial_licence_credit_cents, discount_percent, discount_cents,
             final_price_cents, total_tile_count, new_tile_count, charged_tile_count,
             already_licenced_tile_count, partial_licence_tile_count, free_tile_count,
             summary_json, map_state_status,
             ${includeMapState ? "map_state_json," : ""}
             map_state_updated_at,
             stale_reason, error_code, error_message,
             requested_at, calculated_at, created_at, updated_at
      FROM user_product_quotes
      WHERE user_id = ?
        AND catalog_version = ?
        AND product_id IN (${placeholders})
    `,
    [String(userId || "").trim(), REGION_PACK_CATALOG_VERSION, ...ids],
  );
  const result = new Map();
  for (const row of rows || []) {
    const productId = String(row && row.product_id || "").trim().toLowerCase();
    if (productId) {
      result.set(productId, row);
    }
  }
  return result;
}

async function loadEffectiveUserProductQuoteRows(db, userId, account, productIds, deps, options = {}) {
  return await loadUserProductQuoteRows(
    db,
    productQuoteLookupUserIdForAccount(userId, account),
    productIds,
    deps,
    options,
  );
}

function userProductQuoteSummaryFromRow(row) {
  if (!row || typeof row !== "object") {
    return null;
  }
  const fullPriceCents = integerCents(row.full_price_cents);
  const alreadyLicencedCents = integerCents(row.already_licenced_cents);
  const partialLicenceCreditCents = integerCents(row.partial_licence_credit_cents);
  const discountCents = integerCents(row.discount_cents);
  const finalPriceCents = integerCents(row.final_price_cents);
  return {
    new_tiles: Math.max(0, Number.parseInt(row.new_tile_count || 0, 10) || 0),
    charged_tiles: Math.max(0, Number.parseInt(row.charged_tile_count || 0, 10) || 0),
    total_tiles: Math.max(0, Number.parseInt(row.total_tile_count || 0, 10) || 0),
    already_licenced_tiles: Math.max(0, Number.parseInt(row.already_licenced_tile_count || 0, 10) || 0),
    partial_licence_tiles: Math.max(0, Number.parseInt(row.partial_licence_tile_count || 0, 10) || 0),
    free_tiles: Math.max(0, Number.parseInt(row.free_tile_count || 0, 10) || 0),
    full_price_eur: centsToEur(fullPriceCents),
    full_price_cents: fullPriceCents,
    already_licenced_deduction_eur: centsToEur(alreadyLicencedCents),
    already_licenced_deduction_cents: alreadyLicencedCents,
    already_licenced_saving_eur: centsToEur(alreadyLicencedCents),
    partial_licence_credit_eur: centsToEur(partialLicenceCreditCents),
    partial_licence_credit_cents: partialLicenceCreditCents,
    discount_percent: Math.max(0, Number.parseInt(row.discount_percent || 0, 10) || 0),
    discount_eur: centsToEur(discountCents),
    discount_cents: discountCents,
    price_eur: centsToEur(finalPriceCents),
    price_cents: finalPriceCents,
  };
}

function userProductQuoteFromRow(row) {
  const summary = userProductQuoteSummaryFromRow(row);
  if (!summary) {
    return null;
  }
  return {
    quote_id: String(row && row.quote_id || ""),
    quote_type: "region_pack",
    user_id: String(row && row.user_id || ""),
    subject_id: String(row && row.product_id || ""),
    pricing_version: String(row && row.pricing_version || ""),
    entitlement_version: String(row && row.entitlement_version || ""),
    catalog_version: String(row && row.catalog_version || REGION_PACK_CATALOG_VERSION),
    amount_cents: integerCents(row && row.final_price_cents),
    currency: String(row && row.currency || "eur"),
    summary,
  };
}

async function materializedRegionPackQuoteResults(db, userId, products, account, deps, options = {}) {
  const safeUserId = String(userId || "").trim();
  const productList = Array.isArray(products) ? products.filter(Boolean) : [];
  const result = new Map();
  if (!safeUserId || !productList.length) {
    return result;
  }
  const productIds = productList
    .map((product) => normalizedRegionPackProductId(product))
    .filter(Boolean);
  const pricingVersion = String(options && options.pricingVersion || pricingSettingsCacheKey());
  const entitlementVersion = String(options && options.entitlementVersion || accountEntitlementVersion(account));
  const quoteUserId = productQuoteLookupUserIdForAccount(safeUserId, account);
  const quoteRows = await loadUserProductQuoteRows(
    db,
    quoteUserId,
    productIds,
    deps,
    { includeMapState: false },
  );
  for (const product of productList) {
    const productId = normalizedRegionPackProductId(product);
    if (!productId) {
      continue;
    }
    const row = quoteRows.get(productId) || null;
    const status = productQuoteStatus(row, pricingVersion, entitlementVersion);
    const quote = status === "ready" ? userProductQuoteFromRow(row) : null;
    if (!quote) {
      const baseTrigger = String(options && options.triggerType || "public_quote_requested").trim() || "public_quote_requested";
      const baseStaleReason = String(options && options.staleReason || `quote_${status || "missing"}`).trim() || `quote_${status || "missing"}`;
      await enqueueUserProductQuoteJob(db, quoteUserId, productId, pricingVersion, entitlementVersion, deps, {
        jobRound: options && Object.prototype.hasOwnProperty.call(options, "jobRound") ? options.jobRound : 0,
        priority: options && Object.prototype.hasOwnProperty.call(options, "priority") ? options.priority : 30,
        triggerType: baseTrigger,
        staleReason: baseStaleReason,
        fastTrack: Boolean(options && options.fastTrack),
        sourceProductId: String(options && options.sourceProductId || "") || null,
        triggerPurchaseId: String(options && options.triggerPurchaseId || "") || null,
      });
    }
    result.set(productId, {
      product,
      quote,
      quoteRow: row,
      quoteStatus: status,
      pricePending: !quote,
      pricingVersion,
      entitlementVersion,
    });
  }
  return result;
}

async function materializedRegionPackQuoteResult(db, userId, product, account, deps, options = {}) {
  const productId = normalizedRegionPackProductId(product);
  if (!productId) {
    return {
      product,
      quote: null,
      quoteRow: null,
      quoteStatus: "missing",
      pricePending: true,
      requestedQuoteMismatch: false,
    };
  }
  const results = await materializedRegionPackQuoteResults(db, userId, [product], account, deps, options);
  const entry = results.get(productId) || {
    product,
    quote: null,
    quoteRow: null,
    quoteStatus: "missing",
    pricePending: true,
    pricingVersion: pricingSettingsCacheKey(),
    entitlementVersion: accountEntitlementVersion(account),
  };
  const requestedQuoteId = String(options && options.quoteId || "").trim();
  const actualQuoteId = String(entry.quote && entry.quote.quote_id || "").trim();
  return {
    ...entry,
    requestedQuoteMismatch: Boolean(requestedQuoteId && actualQuoteId && requestedQuoteId !== actualQuoteId),
  };
}

async function parseUserProductMapStatePayload(row, env = {}, options = {}) {
  if (!row || typeof row !== "object") {
    return null;
  }
  if (!Boolean(options && options.allowNonReady) && String(row.map_state_status || "").trim().toLowerCase() !== "ready") {
    return null;
  }
  try {
    let parsed = JSON.parse(String(row.map_state_json || "{}"));
    const ref = parsed && parsed.map_state_ref && typeof parsed.map_state_ref === "object"
      ? parsed.map_state_ref
      : null;
    if (ref && String(ref.storage || "").trim().toLowerCase() === "r2") {
      const bucket = env && env.PLANETKA_DATA;
      const key = String(ref.key || "").trim();
      if (!bucket || typeof bucket.get !== "function" || !key) {
        return null;
      }
      const object = await bucket.get(key);
      if (!object || !object.body || typeof object.text !== "function") {
        return null;
      }
      parsed = JSON.parse(await object.text());
    }
    const mapState = parsed && parsed.map_state && typeof parsed.map_state === "object"
      ? parsed.map_state
      : parsed;
    if (!mapState || typeof mapState !== "object") {
      return null;
    }
    const sharded = Boolean(mapState.sharded && mapState.level_shards && typeof mapState.level_shards === "object");
    if (Number.parseInt(mapState.schema || 0, 10) < 3 || (!sharded && (!Array.isArray(mapState.tiles) || mapState.tiles.length <= 0))) {
      return null;
    }
    if (sharded && !Array.isArray(mapState.tiles)) {
      mapState.tiles = [];
    }
    return mapState;
  } catch (_error) {
    return null;
  }
}

async function parseUserProductMapState(row, env = {}) {
  return parseUserProductMapStatePayload(row, env, { allowNonReady: false });
}

function mapStateOwnedDLevelsByFamily(tileKeys = []) {
  const result = new Map();
  for (const key of normalizeTileKeys(tileKeys)) {
    const parsed = parseTileKey(key);
    const family = tileFamilyKey(parsed);
    if (!parsed || !family) {
      continue;
    }
    if (!result.has(family)) {
      result.set(family, []);
    }
    result.get(family).push(Number(parsed.d));
  }
  for (const levels of result.values()) {
    levels.sort((a, b) => a - b);
  }
  return result;
}

function mapStateSceneCreditForCoarserTile(sceneOwnedByFamily, family, targetD) {
  const source = sceneOwnedByFamily instanceof Map ? sceneOwnedByFamily.get(family) : [];
  if (!Array.isArray(source) || !source.length) {
    return 0;
  }
  let creditCents = 0;
  for (const entry of source) {
    const ownedD = Number(entry && entry.d);
    if (Number.isFinite(ownedD) && ownedD > Number(targetD)) {
      creditCents = Math.max(creditCents, integerCents(entry && entry.value_cents));
    }
  }
  return creditCents;
}

async function buildMapStateSceneFamilyStates(db, product, ownershipContext, deps) {
  const sceneOwnedByFamily = ownershipContext && ownershipContext.sceneOwnedByFamily instanceof Map
    ? ownershipContext.sceneOwnedByFamily
    : new Map();
  if (!sceneOwnedByFamily.size) {
    return new Map();
  }
  const familyKeys = Array.from(sceneOwnedByFamily.keys())
    .map((family) => String(family || "").trim())
    .filter(Boolean);
  if (!familyKeys.length) {
    return new Map();
  }
  const targetId = normalizedRegionPackProductId(product);
  const sceneKeys = [];
  for (const entries of sceneOwnedByFamily.values()) {
    for (const entry of Array.isArray(entries) ? entries : []) {
      const key = normalizeTileKey(entry && entry.key || "");
      if (key) {
        sceneKeys.push(key);
      }
    }
  }
  const currentValueByKey = new Map();
  if (targetId && sceneKeys.length) {
    await ensureRegionPackTileEntryTable(db, deps);
    for (const chunk of fixedSizeChunks(Array.from(new Set(sceneKeys)), SQL_VARIABLE_SAFE_CHUNK_SIZE)) {
      const rows = await deps.dbAll(
        db,
        `
          SELECT tile_key, base_gross_cents
          FROM region_pack_tile_entries
          WHERE catalog_version = ?
            AND region_pack_id = ?
            AND tile_key IN (${chunk.map(() => "?").join(",")})
        `,
        [REGION_PACK_CATALOG_VERSION, targetId, ...chunk],
      );
      for (const row of rows || []) {
        const key = normalizeTileKey(row && row.tile_key || "");
        if (key) {
          currentValueByKey.set(key, applyFullQualityPriceCoefficientCents(row && row.base_gross_cents));
        }
      }
    }
  }
  const states = new Map();
  for (const family of familyKeys) {
    const source = sceneOwnedByFamily.get(family) || [];
    const initialEntries = (Array.isArray(source) ? source : [])
      .map((entry) => {
        const key = normalizeTileKey(entry && entry.key || "");
        return {
          key,
          d: Number(entry && entry.d),
          value: currentValueByKey.get(key)
            || integerCents(entry && (entry.value_cents ?? entry.gross_cents))
            || centsForEur(entry && (entry.value_eur ?? entry.gross_price_eur ?? entry.price_eur))
            || 0,
        };
      })
      .filter((entry) => entry.key && Number.isFinite(entry.d));
    if (!initialEntries.length) {
      continue;
    }
    states.set(family, {
      initialEntries: initialEntries.map((entry) => ({ ...entry })),
      workingEntries: initialEntries.map((entry) => ({ ...entry })),
    });
  }
  return states;
}

async function buildUserProductMapStateContext(db, product, quote, account, deps, options = {}) {
  const productId = normalizedRegionPackProductId(product);
  const userId = String(quote && quote.user_id || account && account.user_id || options && options.userId || "").trim();
  if (!db || !productId || !product || !quote || !quote.summary) {
    throw new Error("invalid_user_product_map_state_context");
  }
  const ownershipContext = options && options.pricingOwnershipContext
    ? options.pricingOwnershipContext
    : await regionPackPricingOwnershipContext(db, userId, account, deps, options);
  const purchasedSet = ownershipContext && ownershipContext.purchasedPackIdSet instanceof Set
    ? ownershipContext.purchasedPackIdSet
    : new Set();
  const purchasedRelations = await relevantPurchasedPackRelations(db, product, ownershipContext && ownershipContext.purchasedPackIds || [], deps);
  const targetFullyCovered = Boolean(
    ownershipContext && ownershipContext.world_full_quality_unlocked
    || purchasedSet.has(productId)
    || purchasedRelations.some(regionPackRelationCoversTarget),
  );
  const ownedTileKeys = targetFullyCovered
    ? []
    : await ownedTileKeysForRegionPackMap(db, product, ownershipContext, deps);
  const sceneFamilyStates = targetFullyCovered
    ? new Map()
    : await buildMapStateSceneFamilyStates(db, product, ownershipContext, deps);
  const expectedTileCount = Math.max(0, Number.parseInt(product && product.tile_count || 0, 10) || 0);
  return {
    productId,
    userId,
    targetFullyCovered,
    expectedTileCount,
    ownedDByFamily: mapStateOwnedDLevelsByFamily(ownedTileKeys),
    sceneFamilyStates,
    discountPercent: Math.max(0, Number.parseInt(quote.summary.discount_percent || 0, 10) || 0),
  };
}

async function buildUserProductMapChunkContext(db, product, quote, account, deps, rows, options = {}) {
  const productId = normalizedRegionPackProductId(product);
  const userId = String(quote && quote.user_id || account && account.user_id || options && options.userId || "").trim();
  if (!db || !productId || !product || !quote || !quote.summary) {
    throw new Error("invalid_user_product_map_chunk_context");
  }
  const ownershipContext = options && options.pricingOwnershipContext
    ? options.pricingOwnershipContext
    : await regionPackPricingOwnershipContext(db, userId, account, deps, options);
  const purchasedSet = ownershipContext && ownershipContext.purchasedPackIdSet instanceof Set
    ? ownershipContext.purchasedPackIdSet
    : new Set();
  const purchasedRelations = await relevantPurchasedPackRelations(db, product, ownershipContext && ownershipContext.purchasedPackIds || [], deps);
  const targetFullyCovered = Boolean(
    ownershipContext && ownershipContext.world_full_quality_unlocked
    || purchasedSet.has(productId)
    || purchasedRelations.some(regionPackRelationCoversTarget),
  );
  let ownedDByFamily = new Map();
  if (!targetFullyCovered) {
    const packIds = purchasedRelations
      .filter(regionPackRelationHasOverlap)
      .map((relation) => normalizedRegionPackProductId(relation && relation.owned_region_pack_id))
      .filter((id) => id && id !== productId);
    if (packIds.length) {
      const families = Array.from(new Set((Array.isArray(rows) ? rows : [])
        .map((row) => String(row && (row.family || row.family_key) || "").trim())
        .filter(Boolean)));
      const covered = families.length
        ? await packCoveredTileKeysForFamilies(db, product, packIds, families, deps)
        : new Set();
      ownedDByFamily = mapStateOwnedDLevelsByFamily(Array.from(covered));
    }
  }
  const sceneFamilyStates = targetFullyCovered
    ? new Map()
    : await buildMapStateSceneFamilyStates(db, product, ownershipContext, deps);
  const expectedTileCount = Math.max(0, Number.parseInt(product && product.tile_count || 0, 10) || 0);
  return {
    productId,
    userId,
    targetFullyCovered,
    expectedTileCount,
    ownedDByFamily,
    sceneFamilyStates,
    discountPercent: Math.max(0, Number.parseInt(quote.summary.discount_percent || 0, 10) || 0),
  };
}

function buildUserProductMapTileFromRow(row, context) {
  const parsed = row && row.parsed || parseTileKey(row && (row.tile_key || row.key) || "");
  const key = normalizeTileKey(row && (row.tile_key || row.key) || "");
  const family = String(row && row.family || tileFamilyKey(parsed) || "");
  if (!key || !parsed || !family) {
    return null;
  }
  const fullCents = Math.max(0, integerCents(row && row.gross_cents));
  const globallyFree = Boolean(row && row.globally_free) || fullCents <= 0;
  const ownedDLevels = context && context.ownedDByFamily instanceof Map
    ? context.ownedDByFamily.get(family) || []
    : [];
  const licencedByExisting = Boolean(context && context.targetFullyCovered)
    || ownedDLevels.some((ownedD) => Number(ownedD) <= Number(parsed.d));
  const sceneState = !licencedByExisting && !globallyFree && context && context.sceneFamilyStates instanceof Map
    ? context.sceneFamilyStates.get(family)
    : null;
  if (sceneState && Array.isArray(sceneState.initialEntries) && Array.isArray(sceneState.workingEntries)) {
    const previouslyCovered = sceneState.initialEntries.some((entry) => Number(entry.d) <= Number(parsed.d));
    const coveredForCharge = sceneState.workingEntries.some((entry) => Number(entry.d) <= Number(parsed.d));
    let coarserCreditCents = 0;
    let initialCoarserCreditCents = 0;
    for (const entry of sceneState.workingEntries) {
      if (Number(entry.d) > Number(parsed.d)) {
        coarserCreditCents = Math.max(coarserCreditCents, Number(entry.value || 0) || 0);
      }
    }
    for (const entry of sceneState.initialEntries) {
      if (Number(entry.d) > Number(parsed.d)) {
        initialCoarserCreditCents = Math.max(initialCoarserCreditCents, Number(entry.value || 0) || 0);
      }
    }
    const partialCreditCents = (!previouslyCovered && !coveredForCharge)
      ? Math.max(0, Math.min(fullCents, initialCoarserCreditCents))
      : 0;
    const preDiscountCents = coveredForCharge
      ? 0
      : Math.max(0, fullCents - coarserCreditCents);
    let status = "new";
    if (previouslyCovered) {
      status = "licenced";
    } else if (partialCreditCents > 0) {
      status = "partial";
    } else if (preDiscountCents <= 0) {
      status = "free";
    }
    if (preDiscountCents > 0 && !coveredForCharge) {
      sceneState.workingEntries.push({ key, d: Number(parsed.d), value: fullCents });
    }
    const alreadyLicencedCents = status === "licenced" ? fullCents : 0;
    return {
      tile_key: key,
      x: parsed.x,
      y: parsed.y,
      z: parsed.z,
      d: parsed.d,
      lon_min: parsed.x - 180,
      lon_max: parsed.x - 180 + parsed.z,
      lat_min: parsed.y - 90,
      lat_max: parsed.y - 90 + parsed.z,
      status,
      full_price_cents: fullCents,
      full_price_eur: centsToEur(fullCents),
      gross_cents: fullCents,
      gross_eur: centsToEur(fullCents),
      already_licenced_cents: alreadyLicencedCents,
      already_licenced_eur: centsToEur(alreadyLicencedCents),
      partial_licence_credit_cents: partialCreditCents,
      partial_licence_credit_eur: centsToEur(partialCreditCents),
      pre_discount_cents: preDiscountCents,
      pre_discount_eur: centsToEur(preDiscountCents),
      discount_percent: Math.max(0, Number.parseInt(context && context.discountPercent || 0, 10) || 0),
      globally_free: false,
      land_km2: normalizeMetricAmount(row && row.land_km2),
      billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
    };
  }
  const partialCreditCents = licencedByExisting || globallyFree
    ? 0
    : 0;
  let status = "new";
  if (licencedByExisting) {
    status = "licenced";
  } else if (globallyFree) {
    status = "free";
  } else if (partialCreditCents > 0) {
    status = "partial";
  }
  const alreadyLicencedCents = status === "licenced" ? fullCents : 0;
  const preDiscountCents = status === "new"
    ? fullCents
    : status === "partial"
      ? Math.max(0, fullCents - partialCreditCents)
      : 0;
  return {
    tile_key: key,
    x: parsed.x,
    y: parsed.y,
    z: parsed.z,
    d: parsed.d,
    lon_min: parsed.x - 180,
    lon_max: parsed.x - 180 + parsed.z,
    lat_min: parsed.y - 90,
    lat_max: parsed.y - 90 + parsed.z,
    status,
    full_price_cents: fullCents,
    full_price_eur: centsToEur(fullCents),
    gross_cents: fullCents,
    gross_eur: centsToEur(fullCents),
    already_licenced_cents: alreadyLicencedCents,
    already_licenced_eur: centsToEur(alreadyLicencedCents),
    partial_licence_credit_cents: partialCreditCents,
    partial_licence_credit_eur: centsToEur(partialCreditCents),
    pre_discount_cents: preDiscountCents,
    pre_discount_eur: centsToEur(preDiscountCents),
    discount_percent: Math.max(0, Number.parseInt(context && context.discountPercent || 0, 10) || 0),
    globally_free: globallyFree,
    land_km2: normalizeMetricAmount(row && row.land_km2),
    billable_land_km2: normalizeMetricAmount(row && row.billable_land_km2),
  };
}

function applyOnDemandMapTileDiscount(tile, context) {
  if (!tile || typeof tile !== "object") {
    return tile;
  }
  const preDiscountCents = Math.max(0, integerCents(tile.pre_discount_cents));
  const discountPercent = Math.max(0, Math.min(100, Number.parseInt(context && context.discountPercent || tile.discount_percent || 0, 10) || 0));
  const amounts = discountedRegionPackAmountCents(preDiscountCents, discountPercent);
  tile.discount_percent = discountPercent;
  tile.discount_cents = Math.max(0, integerCents(amounts.discount_cents));
  tile.discount_eur = centsToEur(tile.discount_cents);
  tile.final_price_cents = Math.max(0, integerCents(amounts.price_cents));
  tile.price_cents = tile.final_price_cents;
  tile.price_eur = centsToEur(tile.final_price_cents);
  return tile;
}

function regionPackQuotePreDiscountCents(quote) {
  const summary = quote && quote.summary && typeof quote.summary === "object" ? quote.summary : {};
  return Math.max(0,
    integerCents(summary.full_price_cents)
    - integerCents(summary.already_licenced_deduction_cents)
    - integerCents(summary.partial_licence_credit_cents),
  );
}

function allocateCumulativeFinalMapTilePrice(tile, progress, totalBaseCents, targetFinalCents) {
  const base = Math.max(0, integerCents(tile && tile.pre_discount_cents));
  const safeTotalBase = Math.max(0, integerCents(totalBaseCents));
  const safeTarget = Math.max(0, Math.min(safeTotalBase, integerCents(targetFinalCents)));
  const currentBase = Math.max(0, integerCents(progress && progress.base_processed_cents));
  if (base <= 0 || safeTotalBase <= 0 || safeTarget <= 0) {
    tile.final_price_cents = 0;
    tile.price_cents = 0;
    tile.price_eur = 0;
    tile.discount_cents = base;
    tile.discount_eur = centsToEur(tile.discount_cents);
    if (progress) {
      progress.base_processed_cents = currentBase + base;
    }
    return;
  }
  const nextBase = currentBase + base;
  const before = Math.floor((currentBase * safeTarget) / safeTotalBase);
  const after = Math.floor((nextBase * safeTarget) / safeTotalBase);
  tile.final_price_cents = Math.max(0, after - before);
  tile.price_cents = tile.final_price_cents;
  tile.price_eur = centsToEur(tile.final_price_cents);
  tile.discount_cents = Math.max(0, base - tile.final_price_cents);
  tile.discount_eur = centsToEur(tile.discount_cents);
  if (progress) {
    progress.base_processed_cents = nextBase;
  }
}

function allocateFinalMapTilePrices(mapTiles, targetFinalCents) {
  const rows = (Array.isArray(mapTiles) ? mapTiles : [])
    .map((tile, index) => ({
      tile,
      index,
      base: Math.max(0, integerCents(tile && tile.pre_discount_cents)),
    }))
    .filter((entry) => entry.base > 0);
  const totalBase = rows.reduce((total, entry) => total + entry.base, 0);
  const target = Math.max(0, Math.min(totalBase, integerCents(targetFinalCents)));
  if (!rows.length || totalBase <= 0 || target <= 0) {
    for (const tile of mapTiles || []) {
      tile.final_price_cents = 0;
      tile.price_cents = 0;
      tile.price_eur = 0;
      tile.discount_cents = Math.max(0, integerCents(tile && tile.pre_discount_cents));
      tile.discount_eur = centsToEur(tile.discount_cents);
    }
    return;
  }
  let allocated = 0;
  const priced = rows.map((entry) => {
    const raw = (entry.base * target) / totalBase;
    const floor = Math.floor(raw);
    allocated += floor;
    return {
      ...entry,
      cents: floor,
      remainder: raw - floor,
    };
  }).sort((a, b) => {
    if (b.remainder !== a.remainder) {
      return b.remainder - a.remainder;
    }
    return a.index - b.index;
  });
  let remaining = Math.max(0, target - allocated);
  for (const entry of priced) {
    if (remaining <= 0) {
      break;
    }
    entry.cents += 1;
    remaining -= 1;
  }
  for (const entry of priced) {
    entry.tile.final_price_cents = Math.max(0, entry.cents);
    entry.tile.price_cents = entry.tile.final_price_cents;
    entry.tile.price_eur = centsToEur(entry.tile.final_price_cents);
    entry.tile.discount_cents = Math.max(0, entry.base - entry.tile.final_price_cents);
    entry.tile.discount_eur = centsToEur(entry.tile.discount_cents);
  }
  for (const tile of mapTiles || []) {
    if (integerCents(tile && tile.pre_discount_cents) > 0) {
      continue;
    }
    tile.final_price_cents = 0;
    tile.price_cents = 0;
    tile.price_eur = 0;
    tile.discount_cents = 0;
    tile.discount_eur = 0;
  }
}

async function buildUserProductMapState(db, product, quote, account, deps, options = {}) {
  const productId = normalizedRegionPackProductId(product);
  if (!db || !productId || !product || !quote || !quote.summary) {
    throw new Error("invalid_user_product_map_state_context");
  }
  const context = await buildUserProductMapStateContext(db, product, quote, account, deps, options);
  const allRows = await regionPackAllTileRowsForProduct(db, product, deps);
  const expectedTileCount = Math.max(0, Number.parseInt(context && context.expectedTileCount || 0, 10) || 0);
  if (expectedTileCount > 0 && allRows.length !== expectedTileCount) {
    throw new Error(`map_state_tile_count_mismatch:${productId}:${allRows.length}:${expectedTileCount}`);
  }
  const mapTiles = [];
  for (const row of allRows) {
    const tile = buildUserProductMapTileFromRow(row, context);
    if (tile) {
      mapTiles.push(tile);
    }
  }
  const preDiscountTotalCents = mapTiles.reduce((total, tile) => total + Math.max(0, integerCents(tile && tile.pre_discount_cents)), 0);
  const targetFinalCents = integerCents(quote.summary.price_cents);
  if (targetFinalCents > preDiscountTotalCents) {
    throw new Error(`map_state_price_total_mismatch:${productId}:${targetFinalCents}:${preDiscountTotalCents}`);
  }
  allocateFinalMapTilePrices(mapTiles, targetFinalCents);
  const allocatedFinalCents = mapTiles.reduce((total, tile) => total + Math.max(0, integerCents(tile && tile.final_price_cents)), 0);
  if (allocatedFinalCents !== targetFinalCents) {
    throw new Error(`map_state_final_price_allocation_mismatch:${productId}:${allocatedFinalCents}:${targetFinalCents}`);
  }
  const levels = Array.from(new Set(mapTiles.map((tile) => Number(tile && tile.z)).filter(isRegionPackPaidZLevel))).sort((a, b) => a - b);
  const levelCounts = {};
  for (const tile of mapTiles) {
    const z = Number(tile && tile.z);
    if (isRegionPackPaidZLevel(z)) {
      levelCounts[String(z)] = Math.max(0, Number.parseInt(levelCounts[String(z)] || 0, 10) || 0) + 1;
    }
  }
  const detail = GENERATED_REGION_PACK_DETAILS[String(product && product.id || "")] || {};
  return {
    schema: 3,
    tile_status_mode: "complete",
    tile_status_count: mapTiles.length,
    total_tile_status_count: expectedTileCount || mapTiles.length,
    product_full_quality_unlocked: Boolean(context && context.targetFullyCovered),
    generated_at: quoteIsoNow(deps),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    pricing_version: String(quote.pricing_version || ""),
    entitlement_version: String(quote.entitlement_version || ""),
    quote_id: String(quote.quote_id || ""),
    region_pack: regionProductPublicPayload(product),
    bounds: regionMapBounds(product, detail, mapTiles),
    outlines: regionProductOutlinesForMap(product),
    included_countries: regionProductIncludedCountries(product),
    levels,
    default_level: defaultRegionPackMapLevel(levelCounts),
    tiles: mapTiles,
  };
}

function userProductMapStateShouldShard(product) {
  return userProductQuoteMapTileCount(product) > USER_PRODUCT_MAP_STATE_SHARD_TILE_COUNT;
}

function validExistingShardedMapState(mapState, quote, expectedTileCount) {
  if (!mapState || typeof mapState !== "object" || !mapState.sharded) {
    return false;
  }
  return Number.parseInt(mapState.schema || 0, 10) >= 3
    && String(mapState.quote_id || "") === String(quote && quote.quote_id || "")
    && String(mapState.catalog_version || "") === REGION_PACK_CATALOG_VERSION
    && String(mapState.pricing_version || "") === String(quote && quote.pricing_version || "")
    && String(mapState.entitlement_version || "") === String(quote && quote.entitlement_version || "")
    && Math.max(0, Number.parseInt(mapState.total_tile_status_count || 0, 10) || 0) === Math.max(0, Number.parseInt(expectedTileCount || 0, 10) || 0);
}

function shardedMapStateLevelBuiltCount(mapState, level) {
  const levelKey = String(Math.max(1, Number.parseInt(level || 0, 10) || 0));
  const shards = Array.isArray(mapState && mapState.level_shards && mapState.level_shards[levelKey])
    ? mapState.level_shards[levelKey]
    : [];
  return shards.reduce((total, shard) => total + Math.max(0, Number.parseInt(shard && shard.count || 0, 10) || 0), 0);
}

function shardedMapStateBuiltTileCount(mapState) {
  const levelShards = mapState && mapState.level_shards && typeof mapState.level_shards === "object"
    ? mapState.level_shards
    : {};
  let total = 0;
  for (const shards of Object.values(levelShards)) {
    if (!Array.isArray(shards)) {
      continue;
    }
    total += shards.reduce((sum, shard) => sum + Math.max(0, Number.parseInt(shard && shard.count || 0, 10) || 0), 0);
  }
  return total;
}

function shardedMapStateNextPendingLevel(mapState) {
  const levels = (Array.isArray(mapState && mapState.levels) ? mapState.levels : [])
    .map((level) => Math.max(1, Number.parseInt(level || 0, 10) || 0))
    .filter(Boolean)
    .sort((a, b) => a - b);
  const counts = mapState && mapState.level_tile_counts && typeof mapState.level_tile_counts === "object"
    ? mapState.level_tile_counts
    : {};
  for (const level of levels) {
    const expected = Math.max(0, Number.parseInt(counts[String(level)] || 0, 10) || 0);
    if (expected > 0 && shardedMapStateLevelBuiltCount(mapState, level) < expected) {
      return level;
    }
  }
  return 0;
}

function shardedMapStateDefaultLevelReady(mapState) {
  const levels = (Array.isArray(mapState && mapState.levels) ? mapState.levels : [])
    .map((level) => Math.max(1, Number.parseInt(level || 0, 10) || 0))
    .filter(Boolean)
    .sort((a, b) => a - b);
  const storedDefaultLevel = Math.max(0, Number.parseInt(mapState && mapState.default_level || 0, 10) || 0);
  const defaultLevel = levels.includes(storedDefaultLevel) ? storedDefaultLevel : (levels.length ? levels[0] : 0);
  if (!defaultLevel) {
    return false;
  }
  const expected = Math.max(0, Number.parseInt(mapState && mapState.level_tile_counts && mapState.level_tile_counts[String(defaultLevel)] || 0, 10) || 0);
  return expected > 0 && shardedMapStateLevelBuiltCount(mapState, defaultLevel) >= expected;
}

async function initialUserProductShardedMapState(db, product, quote, context, deps) {
  const detail = GENERATED_REGION_PACK_DETAILS[String(product && product.id || "")] || {};
  const levelCounts = await regionPackTileLevelCountsForProduct(db, product, deps);
  const levels = Object.keys(levelCounts)
    .map((level) => Number.parseInt(level, 10))
    .filter((level) => isRegionPackPaidZLevel(level))
    .sort((a, b) => a - b);
  const defaultLevel = defaultRegionPackMapLevel(levelCounts);
  const totalBaseCents = regionPackQuotePreDiscountCents(quote);
  const targetFinalCents = integerCents(quote && quote.summary && quote.summary.price_cents);
  if (targetFinalCents > totalBaseCents) {
    throw new Error(`map_state_price_total_mismatch:${normalizedRegionPackProductId(product)}:${targetFinalCents}:${totalBaseCents}`);
  }
  return {
    schema: 3,
    sharded: true,
    tile_status_mode: "sharded",
    tile_status_count: 0,
    total_tile_status_count: Math.max(0, Number.parseInt(context && context.expectedTileCount || 0, 10) || 0),
    product_full_quality_unlocked: Boolean(context && context.targetFullyCovered),
    generated_at: quoteIsoNow(deps),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    pricing_version: String(quote && quote.pricing_version || ""),
    entitlement_version: String(quote && quote.entitlement_version || ""),
    quote_id: String(quote && quote.quote_id || ""),
    region_pack: regionProductPublicPayload(product),
    bounds: regionMapBounds(product, detail, []),
    outlines: regionProductOutlinesForMap(product),
    included_countries: regionProductIncludedCountries(product),
    levels,
    default_level: defaultLevel,
    level_tile_counts: levelCounts,
    level_shards: {},
    progress: {
      active_level: defaultLevel || (levels.length ? levels[0] : 0),
      offset: 0,
      cursor_family_key: "",
      cursor_d: 0,
      cursor_tile_key: "",
      base_processed_cents: 0,
      final_processed_cents: 0,
      total_base_cents: totalBaseCents,
      target_final_cents: targetFinalCents,
      active_scene_family: "",
      active_scene_working_entries: [],
    },
    tiles: [],
  };
}

async function putUserProductMapStateShard(env, quote, level, shardIndex, tiles) {
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.put !== "function") {
    throw new Error("map_state_object_store_unavailable");
  }
  const key = userProductMapStateShardObjectKey(env, quote, level, shardIndex);
  const payload = {
    schema: 3,
    level: Math.max(1, Number.parseInt(level || 0, 10) || 0),
    shard_index: Math.max(0, Number.parseInt(shardIndex || 0, 10) || 0),
    count: Array.isArray(tiles) ? tiles.length : 0,
    tiles: Array.isArray(tiles) ? tiles : [],
  };
  const json = JSON.stringify(payload);
  const bytes = utf8ByteLength(json);
  await bucket.put(key, json, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    customMetadata: {
      catalog_version: REGION_PACK_CATALOG_VERSION,
      product_id: String(quote && (quote.subject_id || quote.region_pack_id) || ""),
      pricing_version: String(quote && quote.pricing_version || ""),
      entitlement_version: String(quote && quote.entitlement_version || ""),
      quote_id: String(quote && quote.quote_id || ""),
      level: String(level),
      shard_index: String(shardIndex),
      count: String(payload.count),
      bytes: String(bytes),
    },
  });
  return {
    level: payload.level,
    index: payload.shard_index,
    key,
    count: payload.count,
    bytes,
  };
}

async function buildUserProductShardedMapStateStep(db, product, quote, account, deps, options = {}) {
  const productId = normalizedRegionPackProductId(product);
  const env = options && options.env || {};
  if (!db || !productId || !product || !quote || !quote.summary) {
    throw new Error("invalid_user_product_sharded_map_state_context");
  }
  const context = await buildUserProductMapStateContext(db, product, quote, account, deps, options);
  const expectedTileCount = Math.max(0, Number.parseInt(context.expectedTileCount || 0, 10) || 0);
  const quoteRows = await loadUserProductQuoteRows(db, String(quote.user_id || ""), [productId], deps, { includeMapState: true });
  const quoteRow = quoteRows.get(productId) || null;
  let mapState = await parseUserProductMapStatePayload(quoteRow, env, { allowNonReady: true });
  if (!validExistingShardedMapState(mapState, quote, expectedTileCount)) {
    mapState = await initialUserProductShardedMapState(db, product, quote, context, deps);
  }
  const progress = mapState.progress && typeof mapState.progress === "object" ? mapState.progress : {};
  const levels = (Array.isArray(mapState.levels) ? mapState.levels : [])
    .map((level) => Math.max(1, Number.parseInt(level || 0, 10) || 0))
    .filter(Boolean)
    .sort((a, b) => a - b);
  const levelCounts = mapState.level_tile_counts && typeof mapState.level_tile_counts === "object" ? mapState.level_tile_counts : {};
  let activeLevel = Math.max(1, Number.parseInt(progress.active_level || 0, 10) || 0);
  let activeExpected = activeLevel ? Math.max(0, Number.parseInt(levelCounts[String(activeLevel)] || 0, 10) || 0) : 0;
  progress.offset = Math.max(0, Number.parseInt(progress.offset || 0, 10) || 0);
  if (
    !activeLevel
    || !activeExpected
    || (progress.offset >= activeExpected && shardedMapStateLevelBuiltCount(mapState, activeLevel) >= activeExpected)
    || (progress.offset > 0 && !normalizeTileKey(progress.cursor_tile_key || ""))
  ) {
    activeLevel = shardedMapStateNextPendingLevel(mapState);
    activeExpected = activeLevel ? Math.max(0, Number.parseInt(levelCounts[String(activeLevel)] || 0, 10) || 0) : 0;
    progress.active_level = activeLevel;
    progress.offset = shardedMapStateLevelBuiltCount(mapState, activeLevel);
    progress.cursor_family_key = "";
    progress.cursor_d = 0;
    progress.cursor_tile_key = "";
    progress.base_processed_cents = 0;
    progress.final_processed_cents = 0;
    progress.active_scene_family = "";
    progress.active_scene_working_entries = [];
  }
  if (!activeLevel || !activeExpected) {
    mapState.tile_status_count = shardedMapStateBuiltTileCount(mapState);
    await storeUserProductMapStateManifest(db, quote, mapState, deps, { status: "ready" });
    return { complete: true, processed: 0, offset: mapState.tile_status_count, expected: expectedTileCount, default_ready: true };
  }
  progress.active_level = activeLevel;
  progress.cursor_family_key = String(progress.cursor_family_key || "").trim();
  progress.cursor_d = Number.parseInt(progress.cursor_d || 0, 10) || 0;
  progress.cursor_tile_key = normalizeTileKey(progress.cursor_tile_key || "");
  progress.base_processed_cents = Math.max(0, integerCents(progress.base_processed_cents));
  progress.final_processed_cents = Math.max(0, integerCents(progress.final_processed_cents));
  progress.total_base_cents = regionPackQuotePreDiscountCents(quote);
  progress.target_final_cents = integerCents(quote.summary.price_cents);
  progress.active_scene_family = String(progress.active_scene_family || "").trim();
  progress.active_scene_working_entries = Array.isArray(progress.active_scene_working_entries)
    ? progress.active_scene_working_entries
      .map((entry) => ({
        key: normalizeTileKey(entry && entry.key || ""),
        d: Number(entry && entry.d),
        value: integerCents(entry && entry.value),
      }))
      .filter((entry) => entry.key && Number.isFinite(entry.d))
    : [];
  if (
    progress.active_scene_family
    && progress.active_scene_working_entries.length
    && context.sceneFamilyStates instanceof Map
    && context.sceneFamilyStates.has(progress.active_scene_family)
  ) {
    const state = context.sceneFamilyStates.get(progress.active_scene_family);
    state.workingEntries = progress.active_scene_working_entries.map((entry) => ({ ...entry }));
  }
  mapState.progress = progress;
  if (progress.target_final_cents > progress.total_base_cents) {
    throw new Error(`map_state_price_total_mismatch:${productId}:${progress.target_final_cents}:${progress.total_base_cents}`);
  }
  if (progress.offset >= activeExpected) {
    mapState.tile_status_count = shardedMapStateBuiltTileCount(mapState);
    const defaultReady = shardedMapStateDefaultLevelReady(mapState);
    const allComplete = !shardedMapStateNextPendingLevel(mapState);
    await storeUserProductMapStateManifest(db, quote, mapState, deps, { status: defaultReady ? "ready" : "building" });
    return { complete: allComplete, processed: 0, offset: mapState.tile_status_count, expected: expectedTileCount, default_ready: defaultReady };
  }
  const rows = await regionPackTileRowsForProductLevelAfterCursor(db, product, activeLevel, deps, {
    cursor: {
      family_key: progress.cursor_family_key,
      d: progress.cursor_d,
      tile_key: progress.cursor_tile_key,
    },
    limit: USER_PRODUCT_MAP_STATE_SHARD_STEP_TILE_LIMIT,
  });
  if (!rows.length) {
    throw new Error(`map_state_level_tile_count_mismatch:${productId}:z${activeLevel}:${progress.offset}:${activeExpected}`);
  }
  const shardBuffers = new Map();
  let processed = 0;
  let lastCursor = null;
  let lastSceneFamily = "";
  for (const row of rows) {
    const rowFamily = String(row && row.family || tileFamilyKey(parseTileKey(row && (row.tile_key || row.key) || "")) || "");
    const tile = buildUserProductMapTileFromRow(row, context);
    if (!tile) {
      continue;
    }
    allocateCumulativeFinalMapTilePrice(tile, progress, progress.total_base_cents, progress.target_final_cents);
    progress.final_processed_cents += Math.max(0, integerCents(tile.final_price_cents));
    const levelKey = String(tile.z);
    if (!shardBuffers.has(levelKey)) {
      const existing = Array.isArray(mapState.level_shards && mapState.level_shards[levelKey])
        ? mapState.level_shards[levelKey]
        : [];
      if (!mapState.level_shards || typeof mapState.level_shards !== "object") {
        mapState.level_shards = {};
      }
      mapState.level_shards[levelKey] = existing;
      shardBuffers.set(levelKey, {
        level: Number(tile.z),
        shardIndex: existing.length,
        tiles: [],
      });
    }
    shardBuffers.get(levelKey).tiles.push(tile);
    lastCursor = {
      family_key: rowFamily,
      d: Number(tile.d),
      tile_key: tile.tile_key,
    };
    if (rowFamily && context.sceneFamilyStates instanceof Map && context.sceneFamilyStates.has(rowFamily)) {
      lastSceneFamily = rowFamily;
    }
    processed += 1;
  }
  if (processed <= 0) {
    throw new Error(`map_state_empty_shard:${productId}:${progress.offset}`);
  }
  for (const buffer of shardBuffers.values()) {
    const descriptor = await putUserProductMapStateShard(env, quote, buffer.level, buffer.shardIndex, buffer.tiles);
    const levelKey = String(buffer.level);
    if (!Array.isArray(mapState.level_shards[levelKey])) {
      mapState.level_shards[levelKey] = [];
    }
    mapState.level_shards[levelKey].push(descriptor);
  }
  progress.offset += processed;
  if (lastCursor) {
    progress.cursor_family_key = String(lastCursor.family_key || "");
    progress.cursor_d = Number.parseInt(lastCursor.d || 0, 10) || 0;
    progress.cursor_tile_key = normalizeTileKey(lastCursor.tile_key || "");
  }
  if (lastSceneFamily && context.sceneFamilyStates instanceof Map && context.sceneFamilyStates.has(lastSceneFamily)) {
    const state = context.sceneFamilyStates.get(lastSceneFamily);
    progress.active_scene_family = lastSceneFamily;
    progress.active_scene_working_entries = Array.isArray(state && state.workingEntries)
      ? state.workingEntries.map((entry) => ({
        key: normalizeTileKey(entry && entry.key || ""),
        d: Number(entry && entry.d),
        value: integerCents(entry && entry.value),
      })).filter((entry) => entry.key && Number.isFinite(entry.d))
      : [];
  } else {
    progress.active_scene_family = "";
    progress.active_scene_working_entries = [];
  }
  mapState.tile_status_count = shardedMapStateBuiltTileCount(mapState);
  mapState.generated_at = quoteIsoNow(deps);
  const activeLevelComplete = progress.offset >= activeExpected;
  if (activeLevelComplete) {
    progress.active_level = 0;
    progress.offset = 0;
    progress.cursor_family_key = "";
    progress.cursor_d = 0;
    progress.cursor_tile_key = "";
    progress.base_processed_cents = 0;
    progress.final_processed_cents = 0;
    progress.active_scene_family = "";
    progress.active_scene_working_entries = [];
  }
  const defaultReady = shardedMapStateDefaultLevelReady(mapState);
  const complete = !shardedMapStateNextPendingLevel(mapState);
  await storeUserProductMapStateManifest(db, quote, mapState, deps, {
    status: defaultReady ? "ready" : "building",
  });
  return { complete, processed, offset: mapState.tile_status_count, expected: expectedTileCount, default_ready: defaultReady, active_level: activeLevel };
}

function sortedCatalogProducts() {
  const groupOrder = new Map([
    ["countries", 0],
    ["regions", 1],
    ["states_provinces", 2],
    ["continents", 3],
    ["world", 4],
    ["other", 5],
  ]);
  return REGION_PRODUCTS
    .filter((product) => product && !isHiddenRegionProduct(product))
    .slice()
    .sort((a, b) => {
      const groupA = regionProductCatalogGroup(a);
      const groupB = regionProductCatalogGroup(b);
      const orderA = groupOrder.has(groupA.key) ? groupOrder.get(groupA.key) : 99;
      const orderB = groupOrder.has(groupB.key) ? groupOrder.get(groupB.key) : 99;
      return (orderA - orderB)
        || String(a && a.name || "").localeCompare(String(b && b.name || ""));
    });
}

async function buildRegionPackCatalogPageData(db, userId, token, deps, options = {}) {
  await deps.ensureCreditTables(db);
  const products = sortedCatalogProducts();
  const total = products.length;
  const offset = Math.max(0, Number.parseInt(options && options.offset || 0, 10) || 0);
  const limit = Math.max(1, Math.min(REGION_PACK_CATALOG_PAGE_MAX_LIMIT, Number.parseInt(options && options.limit || 1, 10) || 1));
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  const pageProducts = products.slice(offset, offset + limit);
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  const quoteUserId = productQuoteLookupUserIdForAccount(userId, account);
  const productIds = pageProducts.map((product) => String(product && product.id || "").trim().toLowerCase()).filter(Boolean);
  const quoteRows = await loadUserProductQuoteRows(db, quoteUserId, productIds, deps);
  const rows = [];
  let queuedQuoteJobs = 0;
  let readyQuoteRows = 0;
  // Catalog requests must stay read-only for pricing. Missing/stale prices are
  // queued for the quote worker instead of calculated inside this request.
  for (const product of pageProducts) {
    const productId = String(product && product.id || "").trim().toLowerCase();
    const quoteRow = quoteRows.get(productId) || null;
    const status = productQuoteStatus(quoteRow, pricingVersion, entitlementVersion);
    if (status !== "ready") {
      const queued = await enqueueUserProductQuoteJob(db, quoteUserId, productId, pricingVersion, entitlementVersion, deps, {
        staleReason: status === "missing" ? "catalog_quote_missing" : `catalog_quote_${status}`,
        priority: userProductQuotePriority(product),
        triggerType: "catalog_page_visible_requested",
        fastTrack: true,
      });
      if (queued) {
        queuedQuoteJobs += 1;
      }
    } else {
      readyQuoteRows += 1;
    }
    rows.push(regionPackCatalogQuoteRow(product, quoteRow, status));
  }
  return {
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    token: String(token || ""),
    offset,
    limit,
    total_packs: total,
    next_offset: offset + pageProducts.length < total ? offset + pageProducts.length : null,
    rows,
    quote_pricing: true,
    quote_rows_read_only: true,
    ready_quote_rows: readyQuoteRows,
    queued_quote_jobs: queuedQuoteJobs,
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

async function ensureAccountPageTokenTable(db, deps) {
  await deps.ensureCreditTables(db);
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS account_page_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await deps.dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_account_page_tokens_expires ON account_page_tokens(expires_at)`,
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

const REGION_PACK_QUOTE_TTL_MINUTES = 60;

async function ensurePricingQuoteTable(db, deps) {
  await deps.ensureCreditTables(db);
  await deps.dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS pricing_quotes (
        quote_id TEXT PRIMARY KEY,
        quote_type TEXT NOT NULL,
        user_id TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        pricing_version TEXT NOT NULL,
        entitlement_version TEXT NOT NULL,
        catalog_version TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        currency TEXT NOT NULL DEFAULT 'eur',
        quote_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await deps.dbRun(
    db,
    `
      CREATE INDEX IF NOT EXISTS idx_pricing_quotes_subject
      ON pricing_quotes(user_id, quote_type, subject_id, pricing_version, entitlement_version, catalog_version)
    `,
  );
  await deps.dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_pricing_quotes_expires ON pricing_quotes(expires_at)`,
  );
}

function quoteIsoNow(deps) {
  return String(deps && deps.nowIso && deps.nowIso() || new Date().toISOString());
}

async function regionPackQuoteIdFor(userId, product, account, deps) {
  const productId = String(product && product.id || "").trim().toLowerCase();
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  const input = JSON.stringify({
    quote_type: "region_pack",
    user_id: String(userId || "").trim(),
    subject_id: productId,
    pricing_version: pricingVersion,
    entitlement_version: entitlementVersion,
    catalog_version: REGION_PACK_CATALOG_VERSION,
  });
  const hasher = deps && deps.sha256Hex;
  if (typeof hasher !== "function") {
    throw new Error("pricing_quote_hash_unavailable");
  }
  const hash = await hasher(input);
  return `rpq_${String(hash || "").slice(0, 40)}`;
}

function normalizePricingQuoteRow(row) {
  if (!row || typeof row !== "object") {
    return null;
  }
  let payload = {};
  try {
    payload = JSON.parse(String(row.quote_json || "{}"));
  } catch (_error) {
    payload = {};
  }
  return {
    ...payload,
    quote_id: String(row.quote_id || payload.quote_id || ""),
    quote_type: String(row.quote_type || payload.quote_type || ""),
    user_id: String(row.user_id || payload.user_id || ""),
    subject_id: String(row.subject_id || payload.subject_id || ""),
    pricing_version: String(row.pricing_version || payload.pricing_version || ""),
    entitlement_version: String(row.entitlement_version || payload.entitlement_version || ""),
    catalog_version: String(row.catalog_version || payload.catalog_version || ""),
    amount_cents: integerCents(row.amount_cents ?? payload.amount_cents),
    currency: String(row.currency || payload.currency || "eur"),
    created_at: String(row.created_at || payload.created_at || ""),
    expires_at: String(row.expires_at || payload.expires_at || ""),
  };
}

async function loadPricingQuote(db, quoteId, deps, options = {}) {
  const safeQuoteId = String(quoteId || "").trim();
  if (!safeQuoteId) {
    return null;
  }
  await ensurePricingQuoteTable(db, deps);
  const row = await deps.dbGet(
    db,
    `
      SELECT quote_id, quote_type, user_id, subject_id, pricing_version,
             entitlement_version, catalog_version, amount_cents, currency,
             quote_json, created_at, expires_at
      FROM pricing_quotes
      WHERE quote_id = ?
      LIMIT 1
    `,
    [safeQuoteId],
  );
  const quote = normalizePricingQuoteRow(row);
  if (!quote) {
    return null;
  }
  if (!Boolean(options && options.allowExpired)) {
    const nowMs = Date.parse(quoteIsoNow(deps));
    const expiresMs = Date.parse(String(quote.expires_at || ""));
    if (Number.isFinite(nowMs) && Number.isFinite(expiresMs) && expiresMs <= nowMs) {
      return null;
    }
  }
  return quote;
}

async function storePricingQuote(db, quote, deps) {
  if (!quote || typeof quote !== "object" || !quote.quote_id) {
    return null;
  }
  await ensurePricingQuoteTable(db, deps);
  await deps.dbRun(
    db,
    `
      INSERT OR REPLACE INTO pricing_quotes (
        quote_id, quote_type, user_id, subject_id, pricing_version,
        entitlement_version, catalog_version, amount_cents, currency,
        quote_json, created_at, expires_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      String(quote.quote_id || ""),
      String(quote.quote_type || ""),
      String(quote.user_id || ""),
      String(quote.subject_id || ""),
      String(quote.pricing_version || ""),
      String(quote.entitlement_version || ""),
      String(quote.catalog_version || ""),
      integerCents(quote.amount_cents),
      String(quote.currency || "eur"),
      JSON.stringify(quote),
      String(quote.created_at || quoteIsoNow(deps)),
      String(quote.expires_at || addMinutesIsoFromDeps(deps, REGION_PACK_QUOTE_TTL_MINUTES)),
    ],
  );
  return quote;
}

function regionPackQuoteSummary(quote) {
  return quote && typeof quote === "object" && quote.summary && typeof quote.summary === "object"
    ? quote.summary
    : {};
}

function regionPackQuoteMatches(quote, { userId, product, account } = {}) {
  if (!quote) {
    return false;
  }
  const productId = String(product && product.id || "").trim().toLowerCase();
  return String(quote.quote_type || "") === "region_pack"
    && String(quote.user_id || "") === String(userId || "").trim()
    && String(quote.subject_id || "").trim().toLowerCase() === productId
    && String(quote.pricing_version || "") === pricingSettingsCacheKey()
    && String(quote.entitlement_version || "") === accountEntitlementVersion(account)
    && String(quote.catalog_version || "") === REGION_PACK_CATALOG_VERSION;
}

async function createRegionPackQuote(db, userId, product, deps, options = {}) {
  const safeUserId = String(userId || "").trim();
  const productId = String(product && product.id || "").trim().toLowerCase();
  if (!safeUserId || !productId || !product) {
    return { error: "invalid_region_pack_quote_context" };
  }
  const account = options && options.account
    ? options.account
    : await ensureFreshCreditAccountForUser(db, safeUserId, deps);
  const quoteId = await regionPackQuoteIdFor(safeUserId, product, account, deps);
  const requestedQuoteId = String(options && options.quoteId || "").trim();
  if (requestedQuoteId && requestedQuoteId !== quoteId) {
    return { error: "stale_or_invalid_quote", status: 409, expected_quote_id: quoteId };
  }
  const cached = await loadPricingQuote(db, quoteId, deps);
  if (regionPackQuoteMatches(cached, { userId: safeUserId, product, account })) {
    return cached;
  }
  const pricingOwnershipContext = options && options.pricingOwnershipContext
    ? options.pricingOwnershipContext
    : await regionPackPricingOwnershipContext(db, safeUserId, account, deps, options);
  const estimate = await estimateRegionPackSummaryCached(db, product, account, null, deps, {
    cache: true,
    pricingOwnershipContext,
  });
  if (!estimate || estimate.error) {
    return {
      error: estimate && estimate.error || "region_pack_quote_estimate_failed",
      status: 500,
    };
  }
  const summary = buildCanonicalRegionPackSummary(product, estimate);
  const now = quoteIsoNow(deps);
  const quote = {
    ok: true,
    quote_id: quoteId,
    quote_type: "region_pack",
    user_id: safeUserId,
    subject_id: productId,
    region_pack_id: productId,
    pricing_version: pricingSettingsCacheKey(),
    entitlement_version: accountEntitlementVersion(account),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    currency: "eur",
    amount_cents: integerCents(summary.price_cents),
    amount_eur: centsToEur(summary.price_cents),
    summary,
    region_pack: regionProductPublicPayload(product),
    created_at: now,
    expires_at: addMinutesIsoFromDeps(deps, REGION_PACK_QUOTE_TTL_MINUTES),
  };
  return await storePricingQuote(db, quote, deps);
}

async function accountSpecificRegionPackQuoteForCheckout(db, quote, userId, product, account, deps) {
  const safeUserId = String(userId || "").trim();
  const productId = String(product && product.id || quote && quote.subject_id || "").trim().toLowerCase();
  if (!quote || !safeUserId || !productId || !product) {
    return quote;
  }
  if (!isDefaultProductQuoteUserId(quote.user_id)) {
    return quote;
  }
  const quoteId = await regionPackQuoteIdFor(safeUserId, product, account, deps);
  const cached = await loadPricingQuote(db, quoteId, deps);
  if (regionPackQuoteMatches(cached, { userId: safeUserId, product, account })) {
    return cached;
  }
  const now = quoteIsoNow(deps);
  const summary = regionPackQuoteSummary(quote);
  return await storePricingQuote(db, {
    ...quote,
    ok: true,
    quote_id: quoteId,
    quote_type: "region_pack",
    user_id: safeUserId,
    subject_id: productId,
    region_pack_id: productId,
    pricing_version: pricingSettingsCacheKey(),
    entitlement_version: accountEntitlementVersion(account),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    currency: String(quote.currency || "eur"),
    amount_cents: integerCents(summary.price_cents),
    amount_eur: centsToEur(summary.price_cents),
    summary,
    region_pack: regionProductPublicPayload(product),
    created_at: now,
    expires_at: addMinutesIsoFromDeps(deps, REGION_PACK_QUOTE_TTL_MINUTES),
  }, deps);
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
  cacheDetailToken("region_pack", token, {
    token,
    user_id: String(userId || "").trim(),
    region_pack_id: String(regionPackId || "").trim(),
    created_at: now,
    expires_at: expiresAt,
  });
  return { token, expires_at: expiresAt };
}

async function createSceneFullQualityDetailTokenForUser(db, userId, tileKeys, env, deps, options = {}) {
  await ensureSceneFullQualityDetailTokenTable(db, deps);
  const keys = normalizeTileKeys(tileKeys);
  const now = deps.nowIso();
  await deps.dbRun(db, `DELETE FROM scene_full_quality_detail_tokens WHERE expires_at <= ?`, [now]);
  const token = deps.randomToken(32);
  const configuredTtl = Number.parseFloat(options && options.ttlMinutes || "");
  const ttlMinutes = Number.isFinite(configuredTtl) && configuredTtl > 0
    ? Math.min(24 * 60, Math.max(5, configuredTtl))
    : regionPackDetailTokenTtlMinutes(env);
  const expiresAt = addMinutesIsoFromDeps(deps, ttlMinutes);
  await deps.dbRun(
    db,
    `
      INSERT INTO scene_full_quality_detail_tokens (
        token, user_id, tile_keys_json, created_at, expires_at
      ) VALUES (?, ?, ?, ?, ?)
    `,
    [token, String(userId || "").trim(), JSON.stringify(keys), now, expiresAt],
  );
  cacheDetailToken("scene", token, {
    token,
    user_id: String(userId || "").trim(),
    tile_keys_json: JSON.stringify(keys),
    created_at: now,
    expires_at: expiresAt,
  });
  return { token, expires_at: expiresAt };
}

async function createAccountPageTokenForUser(db, userId, env, deps) {
  await ensureAccountPageTokenTable(db, deps);
  const now = deps.nowIso();
  await deps.dbRun(db, `DELETE FROM account_page_tokens WHERE expires_at <= ?`, [now]);
  const token = deps.randomToken(32);
  const expiresAt = addMinutesIsoFromDeps(deps, regionPackDetailTokenTtlMinutes(env));
  await deps.dbRun(
    db,
    `
      INSERT INTO account_page_tokens (
        token, user_id, created_at, expires_at
      ) VALUES (?, ?, ?, ?)
    `,
    [token, String(userId || "").trim(), now, expiresAt],
  );
  cacheDetailToken("account_page", token, {
    token,
    user_id: String(userId || "").trim(),
    created_at: now,
    expires_at: expiresAt,
  });
  return { token, expires_at: expiresAt };
}

function regionPackMapHtml(data) {
  const pack = data && data.region_pack || {};
  const name = String(pack.name || "Data Pack").trim() || "Data Pack";
  const isSceneDetail = Boolean(data && data.scene_detail);
  const countries = Array.isArray(data && data.included_countries) ? data.included_countries : [];
  const summary = data && data.summary || {};
  const success = data && data.success && typeof data.success === "object" ? data.success : null;
  const tokenParam = escapeHtmlText(encodeURIComponent(String(data && data.token || "")));
  const packIdParam = escapeHtmlText(encodeURIComponent(String(pack && pack.id || "")));
  const catalogParam = data && data.catalog_mode ? "&catalog=1" : "";
  const quoteParam = data && data.quote && data.quote.quote_id
    ? `&quote_id=${escapeHtmlText(encodeURIComponent(String(data.quote.quote_id || "")))}`
    : "";
  const primaryBuyHref = !isSceneDetail && packIdParam
    ? `/credits/region-pack-checkout?token=${tokenParam}&region_pack_id=${packIdParam}${catalogParam}${quoteParam}`
    : "";
  const partialLicenceTiles = Math.max(0, Number.parseInt(summary.partial_licence_tiles ?? summary.partial_licence_tile_count ?? 0, 10) || 0);
  const partialLicenceCreditEur = Number(summary.partial_licence_credit_eur || 0);
  const alreadyLicencedTiles = Math.max(0, Number.parseInt(summary.already_licenced_tiles || 0, 10) || 0) + partialLicenceTiles;
  const alreadyLicencedDeductionEur = Number(summary.already_licenced_deduction_eur ?? summary.already_licenced_saving_eur ?? 0) + partialLicenceCreditEur;
  const totalTiles = Number(summary.total_tiles || 0);
  const newTiles = Math.max(0, Number(summary.new_tiles || 0) - partialLicenceTiles);
  const customSceneLicenceEur = Number(summary.custom_scene_licence_eur || 0);
  const sceneSmallFreeApplied = Boolean(summary.scene_small_free_threshold_applied);
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka ${escapeHtmlText(name)} Pack Detail</title>
<link rel="stylesheet" href="/credits/page-assets/region-pack-dynamic-map.css?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}">
</head>
<body>
<main>
<h1>${isSceneDetail ? "Full Quality for This Scene" : `${escapeHtmlText(name)} Full Quality Pack`}</h1>
	${success ? `<section class="panel"><h2>${escapeHtmlText(success.title || "Payment successful")}</h2><p>${escapeHtmlText(success.message || "Your Planetka purchase has been processed.")}</p></section>` : ""}
		<section class="cards">
		<div class="card"><span>New Tiles / Total Tiles</span><b>${newTiles} / ${totalTiles}</b></div>
		<div class="card"><span>Full Price</span><b>€${Number(summary.full_price_eur || 0).toFixed(2)}</b></div>
		${alreadyLicencedDeductionEur > 0 ? `<div class="card"><span>Already Licenced</span><b>${alreadyLicencedTiles} tiles (-€${alreadyLicencedDeductionEur.toFixed(2)})</b></div>` : ""}
		${Number(summary.discount_eur || 0) > 0 ? `<div class="card"><span>Volume Discount</span><b>${Number(summary.discount_percent || 0)}% (-€${Number(summary.discount_eur || 0).toFixed(2)})</b></div>` : ""}
		${customSceneLicenceEur > 0 ? `<div class="card"><span>${escapeHtmlText(summary.scene_custom_licence_label || SCENE_CUSTOM_LICENCE_LABEL)}</span><b>€${customSceneLicenceEur.toFixed(2)}</b></div>` : ""}
		${customSceneLicenceEur <= 0 && sceneSmallFreeApplied ? `<div class="card"><span>Small Scene</span><b>Free below €${Number(summary.scene_small_free_threshold_eur || 0.5).toFixed(2)}</b></div>` : ""}
	<div class="card final-price"><span>Final Price</span><b>€${Number(summary.price_eur || 0).toFixed(2)}</b>${primaryBuyHref ? `<a class="button buy-now" href="${primaryBuyHref}">${Number(summary.price_eur || 0) > 0 ? "Buy Now" : "Licence Now"}</a>` : ""}</div>
	</section>
<section class="panel">
<div class="toolbar">
${isSceneDetail ? `<select id="levelSelect" style="display:none"></select>` : `<label>Zoom level <select id="levelSelect"></select></label>`}
<span id="levelSummary" class="muted"></span>
</div>
${isSceneDetail ? "" : `<p class="muted small">Included zoom levels are part of the Full Quality pack and are required for reliable Planetka rendering across different camera distances.</p>`}
<p class="muted small">Hover over any tile to see individual tile details.</p>
<div class="map-shell">
<svg id="map" role="img" aria-label="${escapeHtmlText(name)} tile map"></svg>
<div id="mapLoadingOverlay" class="map-loading-overlay"><span>Loading map...</span></div>
</div>
	<p class="muted small">Tile hover shows tile status and land coverage. The purchase price above is generated by the backend quote.</p>
<div class="legend">
<span><i class="swatch new"></i>${isSceneDetail ? "Red - New full resolution tile" : "New in this pack"}</span>
<span><i class="swatch partial"></i>${isSceneDetail ? "Yellow - New lower resolution tile" : "Partially licenced"}</span>
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
<h2>${isSceneDetail ? "Relevant Product Packs" : "Similar Options"}</h2>
<div id="upsellGrid" class="upsells"></div>
</section>` : ""}
<section class="panel">
<a class="button secondary" href="/credits/region-pack-catalog?token=${tokenParam}">Product Catalog</a>
</section>
</main>
<script>window.PLANETKA_REGION_PACK_DATA=${payload};</script>
<script src="/credits/page-assets/region-pack-dynamic-map.js?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}" defer></script>
</body>
</html>`;
}

function regionPackStaticMapHtml(data) {
  const pack = data && data.region_pack || {};
  const name = String(pack.name || "Data Pack").trim() || "Data Pack";
  const success = data && data.success && typeof data.success === "object" ? data.success : null;
  const titlePrefix = String(data && data.title_prefix || success && success.context_title_prefix || "").trim();
  const explicitPageTitle = String(data && data.page_title || "").trim();
  const pageTitle = explicitPageTitle || `${titlePrefix ? `${titlePrefix}: ` : ""}${name} Full Quality Pack`;
  const isSceneDetail = Boolean(data && data.scene_detail);
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka ${escapeHtmlText(name)} Pack Detail</title>
<link rel="stylesheet" href="/credits/page-assets/region-pack-map.css?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}">
</head>
<body>
<main>
${success ? `<section class="panel"><h2>${escapeHtmlText(success.title || "Payment successful")}</h2><p>${escapeHtmlText(success.message || "Your Planetka purchase has been processed.")}</p></section>` : ""}
<h1 id="pageTitle">${escapeHtmlText(pageTitle)}</h1>
<section id="cards" class="cards"></section>
<section class="panel">
<div class="toolbar">
${isSceneDetail ? `<select id="levelSelect" style="display:none"></select>` : `<label>Zoom level <select id="levelSelect"></select></label>`}
<span id="levelSummary" class="muted"></span>
</div>
${isSceneDetail ? "" : `<p class="muted small">Included zoom levels are part of the Full Quality pack and are required for reliable Planetka rendering across different camera distances.</p>`}
<p class="muted small">Hover over any tile to see individual tile details.</p>
<div class="map-shell">
<svg id="map" role="img" aria-label="${escapeHtmlText(name)} tile map"></svg>
<div id="mapLoadingOverlay" class="map-loading-overlay"><span>Loading map...</span></div>
</div>
<p class="muted small">Tile hover shows tile status and land coverage. The purchase price above is generated by the backend quote.</p>
<div class="legend">
<span><i class="swatch new"></i>${data && data.scene_detail ? "Red - New full resolution tile" : "New in this pack"}</span>
<span><i class="swatch partial"></i>${data && data.scene_detail ? "Yellow - New lower resolution tile" : "Partially licenced"}</span>
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
<h2>${escapeHtmlText(String(data && data.upsell_title || "Similar Options"))}</h2>
<div id="upsellGrid" class="upsells"></div>
</section>
<section class="panel">
<a class="button secondary" href="/credits/region-pack-catalog?token=${escapeHtmlText(encodeURIComponent(String(data && data.token || "")))}">Product Catalog</a>
</section>
</main>
<script>window.PLANETKA_REGION_PACK_DATA=${payload};</script>
<script src="/credits/page-assets/region-pack-map.js?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}" defer></script>
</body>
</html>`;
}

function regionPackCatalogShellHtml(data) {
  const payload = jsonForInlineScript(data);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planetka Product Catalog</title>
<style>${REGION_PACK_CATALOG_CSS}</style>
</head>
<body>
<main>
<h1>Product Catalog</h1>
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
const fmt=(v)=>"€"+Number(v||0).toFixed(2);
const token=encodeURIComponent(DATA.token||"");
  let ROWS=[];let loading=false;let loadedAll=false;let nextOffset=0;const FIRST_LIMIT=20;const NEXT_LIMIT=20;
function escapeCell(value){return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
	function rowHtml(row){const id=encodeURIComponent(row.id||"");const quote=encodeURIComponent(row.quote_id||"");const ready=String(row.quote_status||"ready")==="ready"&&!row.price_pending&&quote;const quoteParam=quote?"&quote_id="+quote:"";const partialCount=Number(row.partial_licence_tiles??row.partial_licence_tile_count??0);const partial=Number(row.partial_licence_credit_eur||0);const licenced=Number(row.already_licenced_tiles||0)+partialCount;const saving=Number(row.already_licenced_deduction_eur??row.already_licenced_saving_eur??0)+partial;const newTiles=Math.max(0,Number(row.new_tiles||0)-partialCount);const pending="<span class=\\"pending\\">"+escapeCell(row.status_label||"Price updating")+"</span>";const mapLink=ready?" <a class=\\"button secondary\\" href=\\"/credits/region-pack-map?token="+token+"&region_pack_id="+id+"&catalog=1"+quoteParam+"\\">Map</a>":" <span class=\\"button secondary disabled\\">Map</span>";return "<tr>"
+"<td><b>"+escapeCell(row.name||"Data Pack")+"</b><div class=\\"muted small\\">"+escapeCell(row.group_label||"")+"</div></td>"
+"<td>"+(ready?newTiles+" / "+Number(row.total_tiles||0):pending)+"</td>"
+"<td>"+(ready?fmt(row.full_price_eur):pending)+"</td>"
+"<td>"+(ready&&saving>0?licenced+" tiles <span class=\\"saving\\">(-"+fmt(saving)+")</span>":"")+"</td>"
+"<td>"+(ready&&Number(row.discount_eur||0)>0?Number(row.discount_percent||0)+"% <span class=\\"saving\\">(-"+fmt(row.discount_eur)+")</span>":"")+"</td>"
+"<td class=\\"price\\">"+(ready?fmt(row.price_eur):pending)+"</td>"
	+"<td>"+(ready?"<a class=\\"button\\" href=\\"/credits/region-pack-checkout?token="+token+"&region_pack_id="+id+"&catalog=1"+quoteParam+"\\">Buy</a>":"<span class=\\"button disabled\\">Buy</span>")+mapLink+"</td>"
+"</tr>"}
function groupRows(rows){const groups=[];const byKey=new Map();for(const row of rows){const key=String(row.group_key||"other");if(!byKey.has(key)){byKey.set(key,{key,label:String(row.group_label||key),rows:[]});groups.push(byKey.get(key));}byKey.get(key).rows.push(row)}return groups}
function loadStatusHtml(label,loaded,total){return "<span class=\\"load-status\\"><span>"+escapeCell(label)+"</span><span class=\\"loaded\\">"+Number(loaded||0)+"</span><span>/</span><span class=\\"total\\">"+Number(total||0)+"</span></span>"}
function render(){const filter=String(document.getElementById("filter").value||"").trim().toLowerCase();let shown=0;const total=Number(DATA.total_packs||ROWS.length||0);const rows=ROWS.filter(row=>!filter||String(row.name||"").toLowerCase().includes(filter)||String(row.group_label||"").toLowerCase().includes(filter)||String(row.id||"").toLowerCase().includes(filter));let html=groupRows(rows).map(group=>{const groupRows=group.rows||[];if(!groupRows.length)return "";shown+=groupRows.length;return "<h2>"+escapeCell(group.label)+"</h2><table><thead><tr><th>Data Pack</th><th>New Tiles / Total Tiles</th><th>Full Price</th><th>Already Licenced</th><th>Volume Discount</th><th>Final Price</th><th>Actions</th></tr></thead><tbody>"+groupRows.map(rowHtml).join("")+"</tbody></table>"}).join("");if(!html){html="<div class=\\"empty\\">"+(loadedAll?"No data packs match this search.":loadStatusHtml("Loading",ROWS.length,total))+"</div>"}document.getElementById("catalog").innerHTML=html;document.getElementById("count").innerHTML=loadStatusHtml(loadedAll?"Loaded":"Loading",ROWS.length,total);}
function maybeLoadMore(){if(!loading&&!loadedAll)loadNext()}
async function loadNext(){if(loading||loadedAll)return;loading=true;render();try{const pageLimit=ROWS.length?NEXT_LIMIT:FIRST_LIMIT;const url="/credits/region-pack-catalog-page?token="+token+"&offset="+encodeURIComponent(String(nextOffset))+"&limit="+encodeURIComponent(String(pageLimit));const res=await fetch(url,{cache:"no-store"});if(!res.ok)throw new Error("catalog_page_"+res.status);const page=await res.json();ROWS=ROWS.concat(Array.isArray(page.rows)?page.rows:[]);if(Number.isFinite(Number(page.total_packs)))DATA.total_packs=Number(page.total_packs);if(page.next_offset===null||page.next_offset===undefined){loadedAll=true}else{nextOffset=Number(page.next_offset||ROWS.length)}loading=false;render();setTimeout(maybeLoadMore,120)}catch(error){console.warn("Planetka catalog page failed",error);loading=false;document.getElementById("count").className="error small";document.getElementById("count").textContent="Data-pack catalog failed to load.";render();}}
document.getElementById("filter").addEventListener("input",render);window.addEventListener("scroll",maybeLoadMore,{passive:true});loadNext();
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
  const adjustedPriceEur = applyFullQualityPriceCoefficientEur(priceEur);
  return {
    tile_key: tile.key,
    credits: adjustedPriceEur,
    price_eur: adjustedPriceEur,
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
  void value;
  return ACCOUNT_TYPE_DEFAULT;
}

function isUnlimitedCreditAccount(account) {
  void account;
  return false;
}

export function isWorldFullQualityUnlocked(account) {
  const userId = String(account && account.user_id || account && account.id || "").trim();
  if (userId === DEFAULT_NO_PURCHASE_QUOTE_USER_ID) {
    return false;
  }
  if (userId === DEFAULT_BETA_FULL_WORLD_QUOTE_USER_ID) {
    return true;
  }
  const email = String(account && (account.user_email || account.email) || "").trim().toLowerCase();
  if (
    BETA_FULL_WORLD_ACCESS_ENABLED
    && (!email || !BETA_FULL_WORLD_ACCESS_EXCLUDED_EMAILS.has(email))
  ) {
    return true;
  }
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
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  const cached = cachedCreditAccount(safeUserId);
  if (cached) {
    return cached;
  }
  await deps.ensureCreditTables(db);
  const now = deps.nowIso();
  let account = await freshCreditAccountForUser(db, safeUserId, deps);
  if (!account) {
    await deps.dbRun(
      db,
      `
        INSERT OR IGNORE INTO user_credit_accounts (
          user_id, account_type, created_at, updated_at
        )
        VALUES (?, 'account', ?, ?)
      `,
      [safeUserId, now, now],
    );
    account = await freshCreditAccountForUser(db, safeUserId, deps);
  } else if (String(account && account.account_type || "").trim().toLowerCase() !== ACCOUNT_TYPE_DEFAULT) {
    await deps.dbRun(
      db,
      `
        UPDATE user_credit_accounts
        SET account_type = 'account',
            pricing_version = COALESCE(pricing_version, 0) + 1,
            updated_at = ?
        WHERE user_id = ?
      `,
      [now, safeUserId],
    );
    account = await freshCreditAccountForUser(db, safeUserId, deps);
  }
  cacheCreditAccount(account);
  return cloneCreditAccount(account);
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
  const authoritative = Boolean(options && (options.authoritative || options.bypassCache || options.fresh));
  const account = authoritative
    ? await freshCreditAccountForUser(db, userId, deps)
    : await ensureCreditAccount(db, userId, deps);
  if (isUnlimitedCreditAccount(account) || isWorldFullQualityUnlocked(account)) {
    return true;
  }
  if (authoritative) {
    return await tileUnlockedAuthoritative(db, userId, family, requestedD, deps);
  }
  const ownedRows = await ownedTileRowsForUserFamilies(db, userId, [family], deps);
  const familyEntries = ownedByFamilyFromTileRows(ownedRows).get(family) || [];
  return familyEntries.some((entry) => Number(entry && entry.d) <= requestedD);
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
  if (safeMode === "preview") {
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
        free_reason: "preview_quality",
      })),
      excluded_tiles: [],
      partial_licence_tile_count: 0,
      partial_licence_credit_eur: 0,
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
    };
  }
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
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
      partial_licence_tile_count: 0,
      partial_licence_credit_eur: 0,
      integrity_warnings: integrityWarnings,
      metadata_missing_tile_keys: metadataMissingTileKeys,
    };
  }
  const familyList = Array.from(families);
  const rows = await ownedTileRowsForUserFamilies(db, userId, familyList, deps);
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
  let partialLicenceCount = 0;
  let partialLicenceCredit = 0;
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
    const appliedCoarserCredit = (!globallyFree && !coveredByFiner)
      ? normalizeCreditAmount(Math.min(grossCredits, coarserCredit))
      : 0;
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
    if (appliedCoarserCredit > 0) {
      breakdownTile.upgrade_credit_applied = appliedCoarserCredit;
      breakdownTile.partially_licenced = !globallyFree && !coveredByFiner && tileCredits > 0;
      if (breakdownTile.partially_licenced) {
        partialLicenceCount += 1;
        partialLicenceCredit = normalizeCreditAmount(partialLicenceCredit + appliedCoarserCredit);
      }
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
      if (appliedCoarserCredit > 0) {
        newTile.upgrade_credit_applied = appliedCoarserCredit;
        newTile.partially_licenced = tileCredits > 0;
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
    partial_licence_tile_count: partialLicenceCount,
    partial_licence_credit_eur: partialLicenceCredit,
    integrity_warnings: integrityWarnings,
    metadata_missing_tile_keys: metadataMissingTileKeys,
  };
}

function paymentPolicyForEstimate(estimate, customLicenceCents, customLicenceLabel) {
  const tileCents = centsForEur(estimate && (estimate.credits ?? estimate.price_eur));
  const smallFreeApplied = tileCents > 0 && tileCents < SCENE_SMALL_FREE_THRESHOLD_CENTS;
  const safeCustomLicenceCents = Math.max(0, Number.parseInt(customLicenceCents || 0, 10) || 0);
  const appliedCustomLicenceCents = tileCents >= SCENE_SMALL_FREE_THRESHOLD_CENTS
    ? safeCustomLicenceCents
    : 0;
  const safeCustomLicenceLabel = String(customLicenceLabel || SCENE_CUSTOM_LICENCE_LABEL).trim() || SCENE_CUSTOM_LICENCE_LABEL;
  const payableCents = smallFreeApplied ? 0 : tileCents + appliedCustomLicenceCents;
  return {
    scene_tile_price_cents: tileCents,
    scene_tile_price_eur: normalizeCreditAmount(tileCents / 100),
    custom_scene_licence_cents: appliedCustomLicenceCents,
    custom_scene_licence_eur: normalizeCreditAmount(appliedCustomLicenceCents / 100),
    scene_custom_licence_label: safeCustomLicenceLabel,
    scene_custom_licence_applied: appliedCustomLicenceCents > 0,
    scene_small_free_threshold_cents: SCENE_SMALL_FREE_THRESHOLD_CENTS,
    scene_small_free_threshold_eur: normalizeCreditAmount(SCENE_SMALL_FREE_THRESHOLD_CENTS / 100),
    scene_small_free_threshold_applied: smallFreeApplied,
    scene_payable_cents: payableCents,
    scene_payable_eur: normalizeCreditAmount(payableCents / 100),
  };
}

function scenePaymentPolicyForEstimate(estimate) {
  return paymentPolicyForEstimate(estimate, customSceneLicenceCents(), SCENE_CUSTOM_LICENCE_LABEL);
}

function sceneEstimateWithPaymentPolicy(estimate) {
  const policy = scenePaymentPolicyForEstimate(estimate);
  const rawCredits = normalizeCreditAmount(estimate && (estimate.credits ?? estimate.price_eur));
  return {
    ...estimate,
    ...policy,
    raw_credits: rawCredits,
    raw_price_eur: rawCredits,
    credits: policy.scene_payable_eur,
    price_eur: policy.scene_payable_eur,
  };
}

function normalizeAnimationSegments(value) {
  const source = Array.isArray(value) ? value : [];
  const segments = [];
  for (const entry of source) {
    const rawTiles = entry && typeof entry === "object"
      ? (
        entry.tile_keys
        || entry.tileKeys
        || entry.tiles
        || entry.pricing_tiles
        || entry.pricingTiles
      )
      : [];
    const tileKeys = normalizeTileKeys(rawTiles);
    if (!tileKeys.length) {
      continue;
    }
    const index = Math.max(1, Number.parseInt(entry && entry.index || segments.length + 1, 10) || segments.length + 1);
    const start = Math.max(0, Number.parseInt(entry && entry.start || entry && entry.frame_start || entry && entry.frameStart || 0, 10) || 0);
    const end = Math.max(start, Number.parseInt(entry && entry.end || entry && entry.frame_end || entry && entry.frameEnd || start, 10) || start);
    segments.push({
      index,
      start,
      end,
      tile_keys: tileKeys,
    });
  }
  return segments;
}

function uniqueAnimationTileKeys(segments) {
  const keys = [];
  const seen = new Set();
  for (const segment of segments || []) {
    for (const key of normalizeTileKeys(segment && segment.tile_keys || [])) {
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      keys.push(key);
    }
  }
  return keys;
}

function animationEstimateRecordCentsByKey(estimate) {
  const records = new Map();
  for (const source of [estimate && estimate.tiles, estimate && estimate.new_tiles]) {
    for (const row of Array.isArray(source) ? source : []) {
      const tileKey = normalizeTileKey(row && row.tile_key || "");
      if (!tileKey) {
        continue;
      }
      records.set(tileKey, centsForEur(row && (row.credits ?? row.price_eur)));
    }
  }
  return records;
}

function animationSegmentLicencePolicy(estimate, segments = []) {
  const records = animationEstimateRecordCentsByKey(estimate);
  const normalizedSegments = normalizeAnimationSegments(segments);
  const fallbackTileKeys = normalizeTileKeys(
    (estimate && estimate.new_tiles || []).map((row) => row && row.tile_key || ""),
  );
  const effectiveSegments = normalizedSegments.length
    ? normalizedSegments
    : (fallbackTileKeys.length ? [{ index: 1, start: 0, end: 0, tile_keys: fallbackTileKeys }] : []);
  const perResolveCents = customAnimationLicencePerResolveCents();
  const maxCents = customAnimationLicenceMaxCents();
  const thresholdCents = SCENE_SMALL_FREE_THRESHOLD_CENTS;
  const chargedSeen = new Set();
  const breakdown = [];
  let totalLicenceCents = 0;
  let chargeableSegments = 0;

  for (const segment of effectiveSegments) {
    let segmentTileCents = 0;
    let newTileCount = 0;
    for (const tileKey of normalizeTileKeys(segment && segment.tile_keys || [])) {
      const tileCents = Math.max(0, Number.parseInt(records.get(tileKey) || 0, 10) || 0);
      if (tileCents <= 0 || chargedSeen.has(tileKey)) {
        continue;
      }
      chargedSeen.add(tileKey);
      segmentTileCents += tileCents;
      newTileCount += 1;
    }
    const chargeable = segmentTileCents > thresholdCents && perResolveCents > 0 && totalLicenceCents < maxCents;
    const licenceCents = chargeable
      ? Math.min(perResolveCents, Math.max(0, maxCents - totalLicenceCents))
      : 0;
    if (licenceCents > 0) {
      chargeableSegments += 1;
      totalLicenceCents += licenceCents;
    }
    breakdown.push({
      index: Math.max(1, Number.parseInt(segment && segment.index || breakdown.length + 1, 10) || breakdown.length + 1),
      start: Math.max(0, Number.parseInt(segment && segment.start || 0, 10) || 0),
      end: Math.max(0, Number.parseInt(segment && segment.end || segment && segment.start || 0, 10) || 0),
      tile_price_cents: segmentTileCents,
      tile_price_eur: normalizeCreditAmount(segmentTileCents / 100),
      custom_animation_licence_cents: licenceCents,
      custom_animation_licence_eur: normalizeCreditAmount(licenceCents / 100),
      custom_animation_licence_applied: licenceCents > 0,
      new_tile_count: newTileCount,
    });
  }

  return {
    custom_animation_licence_cents: totalLicenceCents,
    custom_animation_licence_eur: normalizeCreditAmount(totalLicenceCents / 100),
    custom_animation_licence_segments: chargeableSegments,
    custom_animation_licence_per_resolve_cents: perResolveCents,
    custom_animation_licence_per_resolve_eur: normalizeCreditAmount(perResolveCents / 100),
    custom_animation_licence_max_cents: maxCents,
    custom_animation_licence_max_eur: normalizeCreditAmount(maxCents / 100),
    custom_animation_licence_threshold_cents: thresholdCents,
    custom_animation_licence_threshold_eur: normalizeCreditAmount(thresholdCents / 100),
    animation_segment_breakdown: breakdown,
  };
}

function animationEstimateWithScenePolicy(estimate, segments = []) {
  const animationPolicy = animationSegmentLicencePolicy(estimate, segments);
  const tileCents = centsForEur(estimate && (estimate.credits ?? estimate.price_eur));
  const smallFreeApplied = tileCents > 0 && tileCents < SCENE_SMALL_FREE_THRESHOLD_CENTS;
  const payableCents = smallFreeApplied
    ? 0
    : tileCents + Math.max(0, Number.parseInt(animationPolicy.custom_animation_licence_cents || 0, 10) || 0);
  const policy = {
    scene_tile_price_cents: tileCents,
    scene_tile_price_eur: normalizeCreditAmount(tileCents / 100),
    custom_scene_licence_cents: smallFreeApplied ? 0 : animationPolicy.custom_animation_licence_cents,
    custom_scene_licence_eur: smallFreeApplied ? 0 : animationPolicy.custom_animation_licence_eur,
    scene_custom_licence_label: ANIMATION_CUSTOM_LICENCE_LABEL,
    scene_custom_licence_applied: !smallFreeApplied && animationPolicy.custom_animation_licence_cents > 0,
    scene_small_free_threshold_cents: SCENE_SMALL_FREE_THRESHOLD_CENTS,
    scene_small_free_threshold_eur: normalizeCreditAmount(SCENE_SMALL_FREE_THRESHOLD_CENTS / 100),
    scene_small_free_threshold_applied: smallFreeApplied,
    scene_payable_cents: payableCents,
    scene_payable_eur: normalizeCreditAmount(payableCents / 100),
  };
  const rawCredits = normalizeCreditAmount(estimate && (estimate.credits ?? estimate.price_eur));
  const publicEstimate = {
    ...estimate,
    ...policy,
    raw_credits: rawCredits,
    raw_price_eur: rawCredits,
    credits: policy.scene_payable_eur,
    price_eur: policy.scene_payable_eur,
  };
  return {
    ...publicEstimate,
    custom_animation_licence_eur: publicEstimate.scene_small_free_threshold_applied ? 0 : animationPolicy.custom_animation_licence_eur,
    custom_animation_licence_label: ANIMATION_CUSTOM_LICENCE_LABEL,
    custom_animation_licence_applied: publicEstimate.scene_custom_licence_applied,
    custom_animation_licence_segments: publicEstimate.scene_small_free_threshold_applied ? 0 : animationPolicy.custom_animation_licence_segments,
    custom_animation_licence_fee_eur: animationPolicy.custom_animation_licence_per_resolve_eur,
    custom_animation_licence_per_resolve_eur: animationPolicy.custom_animation_licence_per_resolve_eur,
    custom_animation_licence_max_fee_eur: animationPolicy.custom_animation_licence_max_eur,
    custom_animation_licence_max_eur: animationPolicy.custom_animation_licence_max_eur,
    custom_animation_licence_threshold_eur: publicEstimate.scene_small_free_threshold_eur,
    animation_segment_breakdown: animationPolicy.animation_segment_breakdown,
    animation_tile_price_eur: publicEstimate.scene_tile_price_eur,
    animation_payable_eur: publicEstimate.scene_payable_eur,
    animation_small_free_threshold_eur: publicEstimate.scene_small_free_threshold_eur,
    animation_small_free_threshold_applied: publicEstimate.scene_small_free_threshold_applied,
  };
}

async function animationCheckoutTileKeysFromBody(db, userId, body, env, deps) {
  const directKeys = requestTileKeysFromBody(body);
  const segments = normalizeAnimationSegments(body && (
    body.segments
    || body.animation_segments
    || body.animationSegments
    || body.segment_plan
    || body.segmentPlan
  ));
  const tileKeys = directKeys.length ? directKeys : uniqueAnimationTileKeys(segments);
  if (!tileKeys.length) {
    return { error: "missing_animation_tiles" };
  }
  if (tileKeys.length > ANIMATION_CHECKOUT_MAX_UNIQUE_TILES) {
    return {
      error: "animation_checkout_too_large",
      message: "This animation contains too many unique Full Quality tiles for direct animation checkout. Use data packs for this render.",
      tile_count: tileKeys.length,
      max_tile_count: ANIMATION_CHECKOUT_MAX_UNIQUE_TILES,
    };
  }
  const tokenResult = await createSceneFullQualityDetailTokenForUser(db, userId, tileKeys, env, deps, {
    ttlMinutes: CHECKOUT_TILE_SET_TOKEN_TTL_MINUTES,
  });
  return {
    ok: true,
    tile_keys: tileKeys,
    segments,
    tile_set_token: tokenResult.token,
    expires_at: tokenResult.expires_at,
    segment_count: segments.length || Math.max(0, Number.parseInt(body && (body.segment_count || body.segmentCount) || 0, 10) || 0),
  };
}

async function checkoutTileKeysFromMetadata(db, metadata, deps) {
  const directKeys = parseStripeMetadataTileKeys(metadata && metadata.planetka_tile_keys_json);
  if (directKeys.length) {
    return directKeys;
  }
  const token = String(metadata && (metadata.planetka_tile_set_token || metadata.planetka_scene_detail_token) || "").trim();
  if (!token) {
    return [];
  }
  const tokenResult = await getValidSceneFullQualityDetailToken(db, token, deps);
  if (tokenResult.error) {
    return [];
  }
  return normalizeTileKeys(tokenResult.row && tokenResult.row.tile_keys);
}

export async function unlockTilesForSession(db, userId, qualityMode, tileKeys, resolveId, deps, options = {}) {
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
  const policy = scenePaymentPolicyForEstimate(estimate);
  const allowSmallSceneFree = Boolean(options && options.allowSmallSceneFree);
  const freeSmallScene = allowSmallSceneFree && Boolean(policy.scene_small_free_threshold_applied);
  if (requiredCredits > 0 && !freeSmallScene) {
    const paymentRequiredPrice = policy.scene_payable_cents > 0 ? policy.scene_payable_eur : requiredCredits;
    return {
      error: "payment_required",
      required_credits: requiredCredits,
      price_eur: paymentRequiredPrice,
      scene_tile_price_eur: policy.scene_tile_price_eur,
      custom_scene_licence_eur: policy.custom_scene_licence_eur,
      scene_custom_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
      scene_custom_licence_applied: policy.scene_custom_licence_applied,
      scene_small_free_threshold_eur: policy.scene_small_free_threshold_eur,
      scene_small_free_threshold_applied: false,
      paid_tile_count: estimate.paid_tile_count,
      tile_count: estimate.tile_count,
    };
  }

  const now = deps.nowIso();
  const insertedTiles = [];
  let actualCredits = 0;
  for (const tile of estimate.new_tiles || []) {
    const tileCredits = freeSmallScene ? 0 : normalizeCreditAmount(tile.credits);
    const insertedTile = freeSmallScene
      ? {
        ...tile,
        credits: 0,
        price_eur: 0,
        scene_small_free: true,
        gross_credits: normalizeCreditAmount(tile && (tile.gross_credits ?? tile.credits)),
        gross_price_eur: normalizeCreditAmount(tile && (tile.gross_price_eur ?? tile.gross_credits ?? tile.credits)),
      }
      : tile;
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
        freeSmallScene ? "scene_small_free" : (String(tile.stats_source || "backend_d1").trim() || "backend_d1"),
        now,
      ],
    );
    if (deps.dbMetaChanges(insert) > 0) {
      insertedTiles.push(insertedTile);
      actualCredits = normalizeCreditAmount(actualCredits + tileCredits);
    }
  }

  if (insertedTiles.length > 0) {
    await touchUserPricingVersion(db, safeUserId, deps, now);
    const verificationFailures = await verifyInsertedTileEntitlements(db, safeUserId, insertedTiles, deps);
    if (verificationFailures.length > 0) {
      for (const tile of insertedTiles) {
        await deps.dbRun(
          db,
          `DELETE FROM user_tile_entitlements WHERE user_id = ? AND tile_key = ?`,
          [safeUserId, tile.tile_key],
        );
      }
      await touchUserPricingVersion(db, safeUserId, deps, deps.nowIso());
      return {
        error: "tile_unlock_verification_failed",
        message: "Planetka Full Quality licence could not be confirmed for all requested tiles.",
        missing_tile_key: verificationFailures[0],
        tile_keys: verificationFailures.slice(0, 10),
        required_credits: actualCredits,
        paid_tile_count: insertedTiles.filter((tile) => normalizeCreditAmount(tile && tile.credits) > 0).length,
        tile_count: estimate.tile_count,
      };
    }
  }

  if (actualCredits > 0) {
    for (const tile of insertedTiles) {
      await deps.dbRun(
        db,
        `DELETE FROM user_tile_entitlements WHERE user_id = ? AND tile_key = ?`,
        [safeUserId, tile.tile_key],
      );
    }
    if (insertedTiles.length > 0) {
      await touchUserPricingVersion(db, safeUserId, deps, deps.nowIso());
    }
    return {
      error: "payment_required",
      required_credits: actualCredits,
      price_eur: actualCredits,
      paid_tile_count: insertedTiles.filter((tile) => normalizeCreditAmount(tile && tile.credits) > 0).length,
      tile_count: estimate.tile_count,
    };
  }

  if (insertedTiles.length > 0) {
    await invalidateAndQueueUserProductQuotes(db, safeUserId, deps, {
      tileKeys: insertedTiles.map((tile) => tile && tile.tile_key || "").filter(Boolean),
      triggerType: freeSmallScene ? "scene_small_free" : "scene_unlock",
      triggerPurchaseId: String(resolveId || ""),
      staleReason: freeSmallScene ? "scene_small_free_entitlement" : "scene_entitlement_changed",
    });
  }

  const estimatedPaidCount = Math.max(0, Number.parseInt(estimate.paid_tile_count || 0, 10) || 0);
  const estimatedFreeCount = Math.max(0, Number.parseInt(estimate.free_tile_count || 0, 10) || 0);
  const insertedPaidCount = insertedTiles.filter((tile) => normalizeCreditAmount(tile && tile.credits) > 0).length;
  const skippedPaidCount = Math.max(0, estimatedPaidCount - insertedPaidCount);
  return {
    ...estimate,
    credits: normalizeCreditAmount(actualCredits),
    price_eur: normalizeCreditAmount(actualCredits),
    scene_tile_price_eur: policy.scene_tile_price_eur,
    custom_scene_licence_eur: freeSmallScene ? 0 : policy.custom_scene_licence_eur,
    scene_custom_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
    scene_custom_licence_applied: false,
    scene_small_free_threshold_eur: policy.scene_small_free_threshold_eur,
    scene_small_free_threshold_applied: freeSmallScene,
    paid_tile_count: insertedPaidCount,
    free_tile_count: estimatedFreeCount + skippedPaidCount,
    new_tiles: insertedTiles,
  };
}

export async function grantPaidSceneTileEntitlements(
  db,
  userId,
  qualityMode,
  tileKeys,
  resolveId,
  amountPaidEur,
  deps,
  userEmail = "",
  stripePaymentIntentId = "",
  options = {},
) {
  const safeMode = deps.normalizeQualityMode(qualityMode || "");
  if (safeMode !== "full") {
    return { error: "unsupported_quality_mode" };
  }
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return { error: "missing_user_id" };
  }
  await ensureCreditAccount(db, safeUserId, deps);
  const safeResolveId = String(resolveId || "").trim();
  if (safeResolveId) {
    const existingPurchase = await deps.dbGet(
      db,
      `SELECT id FROM purchase_history WHERE stripe_session_id = ? LIMIT 1`,
      [safeResolveId],
    );
    if (existingPurchase && existingPurchase.id) {
      return {
        ok: true,
        duplicate_session: true,
        paid_eur: 0,
        paid_tile_count: 0,
        new_tiles: [],
      };
    }
    const ledgerReason = String(options && options.ledgerReason || "stripe_scene_purchase").trim() || "stripe_scene_purchase";
    const existingLedger = await deps.dbGet(
      db,
      `
        SELECT COUNT(*) AS count
        FROM credit_ledger
        WHERE user_id = ?
          AND LOWER(COALESCE(reason, '')) = ?
          AND json_valid(COALESCE(metadata_json, ''))
          AND COALESCE(json_extract(metadata_json, '$.stripe_session_id'), '') = ?
      `,
      [safeUserId, ledgerReason.toLowerCase(), safeResolveId],
    );
    if (Number(existingLedger && existingLedger.count || 0) > 0) {
      return {
        ok: true,
        duplicate_session: true,
        paid_eur: 0,
        paid_tile_count: 0,
        new_tiles: [],
      };
    }
  }
  const estimate = await estimateNewCredits(db, safeUserId, tileKeys, safeMode, deps);
  if (estimate && estimate.error) {
    return estimate;
  }
  const purchaseType = String(options && options.purchaseType || "scene_tiles").trim() || "scene_tiles";
  const ledgerReason = String(options && options.ledgerReason || "stripe_scene_purchase").trim() || "stripe_scene_purchase";
  const entitlementSource = String(options && options.entitlementSource || "stripe_checkout").trim() || "stripe_checkout";
  const customLicenceLabel = String(options && options.customLicenceLabel || SCENE_CUSTOM_LICENCE_LABEL).trim() || SCENE_CUSTOM_LICENCE_LABEL;
  const configuredCustomLicenceCents = Number(options && options.customLicenceCents);
  const customLicenceCents = Number.isFinite(configuredCustomLicenceCents)
    ? Math.max(0, Math.round(configuredCustomLicenceCents))
    : customSceneLicenceCents();
  const policy = paymentPolicyForEstimate(estimate, customLicenceCents, customLicenceLabel);
  const metadataExtras = options && options.metadata && typeof options.metadata === "object" ? options.metadata : {};
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
        entitlementSource,
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
  const alreadyLicencedCount = estimateAlreadyLicencedTileCount(estimate);
  await deps.dbRun(
    db,
    `
      INSERT INTO credit_ledger (
        id, user_id, amount_eur, reason, metadata_json, created_at
      )
        VALUES (?, ?, ?, ?, ?, ?)
      `,
      [
        deps.randomToken(16),
        safeUserId,
        normalizeCreditAmount(amountPaidEur),
        ledgerReason,
        JSON.stringify({
          stripe_session_id: String(resolveId || ""),
          stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
          resolve_id: String(resolveId || ""),
          quality_mode: safeMode,
          purchase_type: purchaseType,
          tile_count: insertedTiles.length,
          tile_count_total: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
          tile_count_new: insertedTiles.length,
        tile_count_already_licenced: alreadyLicencedCount,
        partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
        partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
        nominal_eur: nominalCredits,
        paid_eur: normalizeCreditAmount(amountPaidEur),
          scene_tile_price_eur: policy.scene_tile_price_eur,
          custom_scene_licence_eur: policy.custom_scene_licence_eur,
          scene_payable_eur: policy.scene_payable_eur,
          scene_custom_licence_label: customLicenceLabel,
          scene_custom_licence_applied: policy.scene_custom_licence_applied,
          scene_small_free_threshold_eur: policy.scene_small_free_threshold_eur,
          scene_small_free_threshold_applied: policy.scene_small_free_threshold_applied,
          purchased_tile_keys: purchasedTileKeys,
          purchased_tiles: purchasedTileRows.map((tile) => compactPurchaseTile(tile, "new")).filter(Boolean),
          ...metadataExtras,
        }),
        now,
      ],
  );
  await recordPurchaseHistoryBestEffort(
    db,
    {
      user_id: safeUserId,
      user_email: String(userEmail || "").trim().toLowerCase(),
      purchase_type: purchaseType,
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
        partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
        partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
        scene_tile_price_eur: policy.scene_tile_price_eur,
        custom_scene_licence_eur: policy.custom_scene_licence_eur,
        scene_payable_eur: policy.scene_payable_eur,
        scene_custom_licence_label: customLicenceLabel,
        scene_custom_licence_applied: policy.scene_custom_licence_applied,
        scene_small_free_threshold_eur: policy.scene_small_free_threshold_eur,
        scene_small_free_threshold_applied: policy.scene_small_free_threshold_applied,
        ...metadataExtras,
      },
      created_at: now,
    },
    deps,
  );
  if (insertedTiles.length > 0) {
    await touchUserPricingVersion(db, safeUserId, deps, now);
    await invalidateAndQueueUserProductQuotes(db, safeUserId, deps, {
      tileKeys: purchasedTileKeys,
      insertedTileKeys: insertedTiles.map((tile) => tile && tile.tile_key).filter(Boolean),
      triggerType: purchaseType,
      triggerPurchaseId: safeResolveId,
      staleReason: `${purchaseType}_entitlement_changed`,
    });
  }
  return {
    ...estimate,
    credits: 0,
    price_eur: 0,
    paid_eur: normalizeCreditAmount(amountPaidEur),
    nominal_eur: nominalCredits,
    scene_tile_price_eur: policy.scene_tile_price_eur,
    custom_scene_licence_eur: policy.custom_scene_licence_eur,
    scene_payable_eur: policy.scene_payable_eur,
    scene_custom_licence_label: customLicenceLabel,
    paid_tile_count: insertedPaidCount,
    new_tiles: insertedTiles,
  };
}

async function regionPackEntitlementRowsForGrant(db, userId, product, deps) {
  await deps.ensureCreditTables(db);
  const tileRows = await regionPackAllTileRowsForProduct(db, product, deps);
  const existingRows = await ownedTileRowsForUser(db, userId, deps);
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
  for (const tileRow of tileRows) {
    const tileKey = normalizeTileKey(tileRow && tileRow.key || "");
    const parsed = parseTileKey(tileKey);
    const family = tileFamilyKey(parsed);
    if (!tileKey || !parsed || !family) {
      continue;
    }
    const ownedDLevels = ownedByFamily.get(family) || [];
    if (ownedDLevels.some((ownedD) => Number(ownedD) <= Number(parsed.d))) {
      continue;
    }
    const gross = normalizeCreditAmount(integerCents(tileRow && tileRow.gross_cents) / 100.0);
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

async function reconcileRegionPackEntitlements(db, userId, product, source, now, deps) {
  const rows = await regionPackEntitlementRowsForGrant(db, userId, product, deps);
  if (!rows.length) {
    return [];
  }
  return await insertRegionPackEntitlementRows(db, userId, rows, source, now, deps);
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
  const paymentSource = paymentSourceRaw === "none" ? "none" : "stripe";
  const ledgerReason = paymentSource === "none"
    ? "region_pack_no_payment"
    : "stripe_region_pack_purchase";
  const entitlementSource = paymentSource === "none"
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
  const quote = safeOptions.quote && typeof safeOptions.quote === "object" ? safeOptions.quote : null;
  if (
    !quote
    || quote.error
    || String(quote.quote_type || "") !== "region_pack"
    || String(quote.user_id || "") !== safeUserId
    || String(quote.subject_id || "").trim().toLowerCase() !== String(product.id || "").trim().toLowerCase()
    || String(quote.catalog_version || "") !== REGION_PACK_CATALOG_VERSION
  ) {
    return { error: "missing_or_invalid_region_pack_quote" };
  }
  const summary = regionPackQuoteSummary(quote);
  const paidEur = normalizeCreditAmount(amountPaidEur);
  const quotePriceCents = integerCents(summary.price_cents);
  if (paymentSource === "stripe" && centsForEur(paidEur) !== quotePriceCents) {
    return {
      error: "region_pack_quote_amount_mismatch",
      paid_cents: centsForEur(paidEur),
      quote_amount_cents: quotePriceCents,
    };
  }
  const estimateTotalTiles = Math.max(0, Number.parseInt(summary.total_tiles || 0, 10) || 0);
  const estimateNewTiles = Math.max(0, Number.parseInt(summary.new_tiles || 0, 10) || 0);
  const chargedTiles = Math.max(0, Number.parseInt(summary.charged_tiles || 0, 10) || 0);
  const partialLicenceTiles = Math.max(0, Number.parseInt(summary.partial_licence_tiles || 0, 10) || 0);
  const alreadyLicencedTiles = Math.max(0, Number.parseInt(summary.already_licenced_tiles || 0, 10) || 0) + partialLicenceTiles;
  const grossEur = normalizeCreditAmount(summary.full_price_eur);
  const discountEur = normalizeCreditAmount(summary.discount_eur);
  const discountPercent = Math.max(0, Number.parseInt(summary.discount_percent || 0, 10) || 0);
  const alreadyLicencedGrossEur = normalizeCreditAmount(summary.already_licenced_deduction_eur);
  const partialLicenceCreditEur = normalizeCreditAmount(summary.partial_licence_credit_eur);
  const quoteMetadata = {
    quote_id: String(quote.quote_id || ""),
    pricing_version: String(quote.pricing_version || ""),
    entitlement_version: String(quote.entitlement_version || ""),
    quote_amount_cents: quotePriceCents,
    full_price_eur: grossEur,
    already_licenced_gross_eur: alreadyLicencedGrossEur,
    partial_licence_tile_count: partialLicenceTiles,
    partial_licence_credit_eur: partialLicenceCreditEur,
  };
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
      const now = deps.nowIso();
      const repairedTiles = await reconcileRegionPackEntitlements(
        db,
        safeUserId,
        product,
        `${entitlementSource}_repair`,
        now,
        deps,
      );
      if (repairedTiles.length > 0) {
        await touchUserPricingVersion(db, safeUserId, deps, now);
        await invalidateAndQueueUserProductQuotes(db, safeUserId, deps, {
          sourceProductId: String(product.id || ""),
          triggerType: "region_pack_repair",
          triggerPurchaseId: safeStripeSessionId,
          staleReason: "region_pack_repair_entitlement_changed",
        });
      }
      return {
        ok: true,
        duplicate_session: true,
        repaired_tile_count: repairedTiles.length,
        region_pack: regionProductPublicPayload(product),
        paid_eur: 0,
        paid_tile_count: 0,
      };
    }
  }
  await ensureCreditAccount(db, safeUserId, deps);
  if (paidEur <= 0 && estimateNewTiles <= 0) {
    return {
      ok: true,
      quote_id: String(quote.quote_id || ""),
      region_pack: regionProductPublicPayload(product),
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      credits: 0,
      price_eur: 0,
      paid_eur: 0,
      nominal_eur: 0,
      paid_tile_count: 0,
      tile_count: estimateTotalTiles,
      new_tile_count: 0,
      new_tiles: [],
    };
  }
  const now = deps.nowIso();
  const insertedTiles = [];
  const grantTiles = await regionPackEntitlementRowsForGrant(db, safeUserId, product, deps);
  insertedTiles.push(...await insertRegionPackEntitlementRows(
    db,
    safeUserId,
    grantTiles,
    `${entitlementSource}_quote`,
    now,
    deps,
  ));
  if (shouldWriteLedger) {
    await deps.dbRun(
      db,
      `
        INSERT INTO credit_ledger (
          id, user_id, amount_eur, reason, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
      `,
      [
        deps.randomToken(16),
        safeUserId,
        paidEur,
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
          tile_count_new: insertedTiles.length,
          tile_count_already_licenced: alreadyLicencedTiles,
          already_licenced_gross_eur: alreadyLicencedGrossEur,
          partial_licence_tile_count: partialLicenceTiles,
          partial_licence_credit_eur: partialLicenceCreditEur,
          nominal_eur: grossEur,
          gross_eur: grossEur,
          paid_eur: paidEur,
          ...quoteMetadata,
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
      region_pack_id: String(product.id || ""),
      region_pack_name: String(product.name || ""),
      region_pack_type: String(product.type || ""),
      catalog_version: REGION_PACK_CATALOG_VERSION,
      tile_count_total: estimateTotalTiles,
      tile_count_new: insertedTiles.length,
      tile_count_already_licenced: alreadyLicencedTiles,
      metadata: {
        payment_source: paymentSource,
        payment_reference_id: paymentReferenceId,
        inserted_tile_count: insertedTiles.length,
        already_licenced_gross_eur: alreadyLicencedGrossEur,
        partial_licence_tile_count: partialLicenceTiles,
        partial_licence_credit_eur: partialLicenceCreditEur,
        ...quoteMetadata,
      },
      created_at: now,
    },
    deps,
  );
  if (insertedTiles.length > 0) {
    await touchUserPricingVersion(db, safeUserId, deps, now);
    const immediateReadyProductIds = [];
    const immediateQuote = await materializePurchasedRegionPackQuoteNow(db, safeUserId, product, deps, quote);
    if (immediateQuote && immediateQuote.ok) {
      immediateReadyProductIds.push(String(product.id || ""));
    } else {
      console.warn(
        "planetka.purchased_region_pack_quote_immediate_failed",
        JSON.stringify({
          user_id: safeUserId,
          region_pack_id: String(product.id || ""),
          error: String(immediateQuote && immediateQuote.error || "purchased_region_pack_quote_failed"),
        }),
      );
    }
    await invalidateAndQueueUserProductQuotes(db, safeUserId, deps, {
      sourceProductId: String(product.id || ""),
      triggerType: "region_pack_purchase",
      triggerPurchaseId: safeStripeSessionId || paymentReferenceId || purchaseHistoryId,
      staleReason: "region_pack_entitlement_changed",
      immediateReadyProductIds,
      insertedTileKeys: insertedTiles.map((tile) => tile && tile.tile_key).filter(Boolean),
    });
  }
  return {
    ok: true,
    quote_id: String(quote.quote_id || ""),
    region_pack: regionProductPublicPayload(product),
    region_pack_id: String(product.id || ""),
    region_pack_name: String(product.name || ""),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    credits: 0,
    price_eur: 0,
    paid_eur: paidEur,
    nominal_eur: grossEur,
    paid_tile_count: insertedTiles.filter((tile) => normalizeCreditAmount(tile && (tile.gross_credits ?? tile.credits)) > 0).length,
    tile_count: estimateTotalTiles,
    new_tile_count: insertedTiles.length,
    new_tiles: insertedTiles.slice(0, 500),
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
    console.warn(
      "planetka.stripe.checkout_create_failed",
      JSON.stringify({
        status: response.status,
        purchase_type: String(metadata && metadata.planetka_purchase_type || ""),
        amount_cents: Math.max(0, Math.floor(params.amountCents || 0)),
        message: String(payload && payload.error && payload.error.message || responseText || "").slice(0, 500),
      }),
    );
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
  await ensureRuntimePricingSettings(env, deps);
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

  if (!["scene", "region_pack", "broader_pack", "animation", "animation_tiles"].includes(option)) {
    return deps.json(
      {
        ok: false,
        error: "unsupported_checkout_option",
        message: "Planetka supports direct payment for Full Quality scenes, animations, and data packs only.",
      },
      400,
      env,
    );
  }

  if (option === "animation" || option === "animation_tiles") {
    const animationQualityMode = deps.normalizeQualityMode(body && body.quality_mode || body && body.qualityMode || "full");
    if (animationQualityMode !== "full") {
      return deps.json({ ok: false, error: "unsupported_checkout_quality" }, 400, env);
    }
    const keyResult = await animationCheckoutTileKeysFromBody(db, userId, body, env, deps);
    if (keyResult && keyResult.error) {
      const status = String(keyResult.error || "") === "animation_checkout_too_large" ? 413 : 400;
      return deps.json({ ok: false, ...keyResult }, status, env);
    }
    const tileKeys = normalizeTileKeys(keyResult.tile_keys);
    const estimate = await estimateNewCredits(db, userId, tileKeys, "full", deps);
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
    if (estimate && estimate.error) {
      return deps.json({ ok: false, ...estimate }, 400, env);
    }
    const animationPolicy = animationEstimateWithScenePolicy(estimate, keyResult.segments);
    const rawTilePriceEur = normalizeCreditAmount(animationPolicy.scene_tile_price_eur);
    const priceEur = normalizeCreditAmount(animationPolicy.scene_payable_eur);
    const amountCents = centsForEur(priceEur);
    if (amountCents <= 0) {
      const grant = await unlockTilesForSession(
        db,
        userId,
        "full",
        tileKeys,
        `animation_no_payment_${deps.randomToken(8)}`,
        deps,
        { allowSmallSceneFree: true },
      );
      if (grant && grant.error) {
        return deps.json({ ok: false, ...grant }, 400, env);
      }
      return deps.json(
        {
          ok: true,
          option: "animation",
          no_payment_required: true,
          price_eur: 0,
          raw_tile_price_eur: rawTilePriceEur,
          tile_price_eur: rawTilePriceEur,
          custom_animation_licence_eur: 0,
          custom_animation_licence_label: ANIMATION_CUSTOM_LICENCE_LABEL,
          custom_animation_licence_fee_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_fee_eur),
          custom_animation_licence_per_resolve_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_per_resolve_eur),
          custom_animation_licence_max_fee_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_max_fee_eur),
          custom_animation_licence_segments: 0,
          custom_animation_licence_threshold_eur: animationPolicy.scene_small_free_threshold_eur,
          animation_small_free_threshold_applied: Boolean(animationPolicy.scene_small_free_threshold_applied),
          paid_tile_count: grant && grant.paid_tile_count || 0,
          free_tile_count: grant && grant.free_tile_count || 0,
          tile_count: Math.max(0, Number.parseInt(estimate && estimate.tile_count || tileKeys.length, 10) || tileKeys.length),
          segment_count: Math.max(0, Number.parseInt(keyResult.segment_count || 0, 10) || 0),
          message: Boolean(animationPolicy.scene_small_free_threshold_applied)
            ? "This small Full Quality animation is below €0.50 and has been licenced at no charge."
            : "This animation has no newly charged Full Quality tiles.",
        },
        200,
        env,
      );
    }
    if (amountCents < STRIPE_MIN_CHECKOUT_AMOUNT_CENTS) {
      return deps.json(
        {
          ok: false,
          error: "amount_below_stripe_minimum",
          price_eur: priceEur,
          minimum_eur: STRIPE_MIN_CHECKOUT_AMOUNT_CENTS / 100.0,
          message: "This animation price is below the minimum card payment amount.",
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
        productName: "Planetka Custom Animation Licence",
        metadata: {
          planetka_purchase_type: "animation_tiles",
          planetka_user_id: userId,
          planetka_email: email,
          planetka_quality_mode: "full",
          planetka_tile_set_token: String(keyResult.tile_set_token || ""),
          planetka_price_eur: priceEur.toFixed(2),
          planetka_raw_tile_price_eur: rawTilePriceEur.toFixed(2),
          planetka_animation_tile_price_eur: rawTilePriceEur.toFixed(2),
          planetka_scene_tile_price_eur: rawTilePriceEur.toFixed(2),
          planetka_custom_animation_licence_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_eur).toFixed(2),
          planetka_custom_scene_licence_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_eur).toFixed(2),
          planetka_custom_animation_licence_label: ANIMATION_CUSTOM_LICENCE_LABEL,
          planetka_custom_animation_licence_fee_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_fee_eur).toFixed(2),
          planetka_custom_animation_licence_per_resolve_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_per_resolve_eur).toFixed(2),
          planetka_custom_animation_licence_max_fee_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_max_fee_eur).toFixed(2),
          planetka_custom_animation_licence_segments: String(Math.max(0, Number.parseInt(animationPolicy.custom_animation_licence_segments || 0, 10) || 0)),
          planetka_custom_animation_licence_threshold_eur: animationPolicy.scene_small_free_threshold_eur.toFixed(2),
          planetka_animation_small_free_threshold_applied: animationPolicy.scene_small_free_threshold_applied ? "1" : "0",
          planetka_tile_count: String(Math.max(0, Number.parseInt(estimate && estimate.tile_count || tileKeys.length, 10) || tileKeys.length)),
          planetka_segment_count: String(Math.max(0, Number.parseInt(keyResult.segment_count || 0, 10) || 0)),
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
        option: "animation",
        price_eur: priceEur,
        raw_tile_price_eur: rawTilePriceEur,
        tile_price_eur: rawTilePriceEur,
        custom_animation_licence_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_eur),
        custom_animation_licence_label: ANIMATION_CUSTOM_LICENCE_LABEL,
        custom_animation_licence_fee_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_fee_eur),
        custom_animation_licence_per_resolve_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_per_resolve_eur),
        custom_animation_licence_max_fee_eur: normalizeCreditAmount(animationPolicy.custom_animation_licence_max_fee_eur),
        custom_animation_licence_segments: Math.max(0, Number.parseInt(animationPolicy.custom_animation_licence_segments || 0, 10) || 0),
        custom_animation_licence_threshold_eur: animationPolicy.scene_small_free_threshold_eur,
        animation_small_free_threshold_applied: Boolean(animationPolicy.scene_small_free_threshold_applied),
        paid_tile_count: Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0),
        free_tile_count: Math.max(0, Number.parseInt(estimate && estimate.free_tile_count || 0, 10) || 0),
        tile_count: Math.max(0, Number.parseInt(estimate && estimate.tile_count || tileKeys.length, 10) || tileKeys.length),
        segment_count: Math.max(0, Number.parseInt(keyResult.segment_count || 0, 10) || 0),
        ...session,
      },
      200,
      env,
    );
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
    const account = await ensureFreshCreditAccountForUser(db, userId, deps);
    const quoteId = String(body && (body.quote_id || body.quoteId) || "").trim();
    const quoteResult = await materializedRegionPackQuoteResult(db, userId, product, account, deps, {
      quoteId,
      fastTrack: true,
      jobRound: 0,
      priority: 0,
      triggerType: "checkout_region_pack_requested",
      staleReason: "checkout_quote_not_ready",
    });
    const quote = await accountSpecificRegionPackQuoteForCheckout(
      db,
      quoteResult.quote,
      userId,
      product,
      account,
      deps,
    );
    if (!quote) {
      return deps.json(
        {
          ok: false,
          error: "data_pack_price_updating",
          quote_status: String(quoteResult.quoteStatus || "missing"),
          message: "This data-pack price is updating. Please wait a few moments and try again.",
        },
        409,
        env,
      );
    }
    // Keep the Blender JSON endpoint lightweight. The browser payment page is
    // only receives an existing backend quote. It must not recalculate a
    // different data-pack price.
    const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(product.id || ""), env, deps);
    const url = new URL(request.url);
    url.pathname = "/credits/region-pack-checkout";
    url.search = "";
    url.searchParams.set("token", tokenResult.token);
    url.searchParams.set("region_pack_id", String(product.id || ""));
    url.searchParams.set("quote_id", String(quote.quote_id || ""));
    return deps.json(
      {
        ok: true,
        option: "region_pack",
        payment_choice_required: true,
        region_pack: regionProductPublicPayload(product),
        quote_id: String(quote.quote_id || ""),
        price_eur: normalizeCreditAmount(quote.summary && quote.summary.price_eur),
        price_cents: integerCents(quote.amount_cents),
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
  const scenePolicy = scenePaymentPolicyForEstimate(estimate);
  const rawScenePriceEur = scenePolicy.scene_tile_price_eur;
  const priceEur = scenePolicy.scene_payable_eur;
  if (scenePolicy.scene_payable_cents <= 0) {
    const unlockResult = await unlockTilesForSession(
      db,
      userId,
      qualityMode,
      tileKeys,
      `checkout_no_payment_${deps.randomToken(8)}`,
      deps,
      { allowSmallSceneFree: true },
    );
    if (unlockResult && unlockResult.error) {
      return deps.json({ ok: false, ...unlockResult }, 400, env);
    }
    const smallFree = Boolean(scenePolicy.scene_small_free_threshold_applied);
    return deps.json(
      {
        ok: true,
        option: "scene",
        no_payment_required: true,
        price_eur: 0,
        raw_price_eur: rawScenePriceEur,
        scene_tile_price_eur: rawScenePriceEur,
        custom_scene_licence_eur: 0,
        scene_custom_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
        scene_custom_licence_applied: false,
        scene_small_free_threshold_eur: scenePolicy.scene_small_free_threshold_eur,
        scene_small_free_threshold_applied: smallFree,
        paid_tile_count: unlockResult && unlockResult.paid_tile_count || 0,
        tile_count: unlockResult && unlockResult.tile_count || estimate.tile_count,
        message: smallFree
          ? "This small Full Quality scene is below €0.50 and has been licenced at no charge."
          : "This scene has no newly charged Full Quality tiles.",
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
        message: "This scene price is below the minimum card payment amount. Please choose a larger Full Quality scene or data pack.",
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
      productName: "Planetka Custom Scene-Specific Licence",
      metadata: {
        planetka_purchase_type: "scene_tiles",
        planetka_user_id: userId,
        planetka_email: email,
        planetka_quality_mode: "full",
        planetka_tile_keys_json: JSON.stringify(normalizedKeys),
        planetka_price_eur: priceEur.toFixed(2),
        planetka_scene_tile_price_eur: rawScenePriceEur.toFixed(2),
        planetka_custom_scene_licence_eur: scenePolicy.custom_scene_licence_eur.toFixed(2),
        planetka_scene_payable_eur: scenePolicy.scene_payable_eur.toFixed(2),
        planetka_custom_scene_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
        planetka_scene_custom_licence_applied: scenePolicy.scene_custom_licence_applied ? "1" : "0",
        planetka_scene_small_free_threshold_eur: scenePolicy.scene_small_free_threshold_eur.toFixed(2),
        planetka_scene_small_free_threshold_applied: scenePolicy.scene_small_free_threshold_applied ? "1" : "0",
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
      raw_price_eur: rawScenePriceEur,
      scene_tile_price_eur: rawScenePriceEur,
      custom_scene_licence_eur: scenePolicy.custom_scene_licence_eur,
      scene_payable_eur: scenePolicy.scene_payable_eur,
      scene_custom_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
      scene_custom_licence_applied: scenePolicy.scene_custom_licence_applied,
      scene_small_free_threshold_eur: scenePolicy.scene_small_free_threshold_eur,
      scene_small_free_threshold_applied: scenePolicy.scene_small_free_threshold_applied,
      paid_tile_count: estimate.paid_tile_count,
      tile_count: estimate.tile_count,
      ...session,
    },
    200,
    env,
  );
}

export async function handleCreditMe(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  const account = await ensureFreshCreditAccountForUser(db, auth.user.id, deps);
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
      unlocked_tile_count: worldUnlocked
        ? Math.max(Number(countRow && countRow.count || 0), Number(worldSummary.licensable_tile_count || 0))
        : Number(countRow && countRow.count || 0),
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
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.estimate");
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  timing.mark("auth");
  const db = deps.requireDb(env);
  const account = await ensureFreshCreditAccountForUser(db, auth.user.id, deps);
  timing.mark("account");
  const body = await deps.parseJson(request);
  const tileKeys = requestTileKeysFromBody(body);
  const qualityMode = deps.normalizeQualityMode(body && body.quality_mode || body && body.qualityMode || "full");
  timing.mark("parse");
  const estimate = await estimateNewCredits(db, auth.user.id, tileKeys, qualityMode, deps);
  timing.mark("estimate");
  if (estimate && estimate.error === "credit_pricing_missing_tile_stats") {
    return withEndpointTiming(deps.json(
      {
        ok: false,
        error: "credit_pricing_missing_tile_stats",
        message: "Planetka EUR pricing metadata is missing for a requested tile.",
        tile_key: String(estimate.missing_tile_key || ""),
      },
      503,
      env,
    ), timing, env, { tile_count: tileKeys.length, quality_mode: qualityMode });
  }
  const unlimited = isUnlimitedCreditAccount(account);
  const worldUnlocked = isWorldFullQualityUnlocked(account);
  const worldSummary = worldRegionProductSummary();
  const pricingContext = String(body && (body.pricing_context || body.pricingContext || "") || "").trim().toLowerCase();
  const publicEstimate = qualityMode === "full"
    ? (pricingContext === "animation" ? animationEstimateWithScenePolicy(estimate) : sceneEstimateWithPaymentPolicy(estimate))
    : estimate;
  const response = deps.json(
    {
      ok: true,
      ...publicEstimate,
      credits: publicEstimate.credits,
      price_eur: normalizeCreditAmount(publicEstimate.credits),
      paid_tile_count: publicEstimate.paid_tile_count,
      free_tile_count: publicEstimate.free_tile_count,
      account_type: normalizeAccountType(account && account.account_type),
      unlimited_credits: unlimited,
      world_full_quality_unlocked: worldUnlocked,
      world_full_quality_unlocked_at: String(account && account.world_full_quality_unlocked_at || ""),
      world_full_quality_paid_eur: normalizeCreditAmount(account && account.world_full_quality_paid_eur),
      world_full_quality_tile_count: Number(worldSummary.tile_count || 0),
      world_full_quality_licensable_tile_count: Number(worldSummary.licensable_tile_count || 0),
    },
    200,
    env,
  );
  return withEndpointTiming(response, timing, env, {
    tile_count: tileKeys.length,
    quality_mode: qualityMode,
    price_eur: normalizeCreditAmount(publicEstimate && publicEstimate.credits),
  });
}

export async function handleCreditRegionOffers(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_offers");
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  timing.mark("auth");
  const db = deps.requireDb(env);
  const account = await ensureFreshCreditAccountForUser(db, auth.user.id, deps);
  timing.mark("account");
  const body = await deps.parseJson(request);
  const latitude = clampNumber(body && (body.latitude_deg ?? body.latitude ?? body.lat), -90.0, 90.0);
  const longitude = clampNumber(body && (body.longitude_deg ?? body.longitude ?? body.lon), -180.0, 180.0);
  const tileKeys = requestTileKeysFromBody(body).slice(0, 256);
  const tileSignature = tileKeys.length
    ? await sha1Hex(tileKeys.join("|"), 16)
    : "none";
  const cacheKey = [
    String(auth.user.id || "").trim(),
    accountEntitlementVersion(account),
    REGION_PACK_CATALOG_VERSION,
    pricingSettingsCacheKey(),
    roundForCache(latitude, 3).toFixed(3),
    roundForCache(longitude, 3).toFixed(3),
    tileSignature,
  ].join("|");
  const cached = REGION_OFFERS_RESPONSE_CACHE.get(cacheKey);
  const nowMs = monotonicNowMs();
  if (
    cached
    && (nowMs - Number(cached.cached_at_ms || 0)) <= REGION_OFFERS_RESPONSE_CACHE_TTL_MS
    && cached.payload
  ) {
    const response = deps.json(
      {
        ...cached.payload,
        server_cache_hit: true,
      },
      200,
      env,
    );
    timing.mark("cache_hit");
    return withEndpointTiming(response, timing, env, {
      cache_hit: true,
      offer_count: Array.isArray(cached.payload.offers) ? cached.payload.offers.length : 0,
    });
  }
  timing.mark("parse");
  const products = await suggestedRegionProductsForContext(db, latitude, longitude, tileKeys, deps);
  timing.mark("products");
  const quoteResults = await materializedRegionPackQuoteResults(db, auth.user.id, products, account, deps, {
    fastTrack: true,
    jobRound: 0,
    priority: 15,
    triggerType: "region_offers_requested",
    staleReason: "region_offer_quote_not_ready",
  });
  timing.mark("quotes");
  const offers = [];
  let pendingQuoteCount = 0;
  for (const product of products) {
    const quoteEntry = quoteResults.get(normalizedRegionPackProductId(product));
    const quote = quoteEntry && quoteEntry.quote;
    if (!quote) {
      pendingQuoteCount += 1;
      continue;
    }
    const offer = regionPackOfferPayload(product, quote);
    if (integerCents(offer.price_cents) <= 0 && Number(offer.charged_tile_count || 0) <= 0) {
      continue;
    }
    offers.push(offer);
  }
  timing.mark("estimate");
  const payload = {
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    latitude_deg: latitude,
    longitude_deg: longitude,
    offers,
    price_pending: pendingQuoteCount > 0,
    pending_quote_count: pendingQuoteCount,
    server_cache_hit: false,
  };
  if (pendingQuoteCount <= 0) {
    boundedCacheSet(
      REGION_OFFERS_RESPONSE_CACHE,
      cacheKey,
      {
        payload,
        cached_at_ms: nowMs,
      },
      REGION_OFFERS_RESPONSE_CACHE_MAX,
    );
  }
  const response = deps.json(payload, 200, env);
  return withEndpointTiming(response, timing, env, {
    cache_hit: false,
    product_count: products.length,
    pending_quote_count: pendingQuoteCount,
    offer_count: offers.length,
  });
}

export async function handleCreditRegionPackRelatedOffers(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_pack_related_offers");
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  timing.mark("auth");
  const db = deps.requireDb(env);
  const account = await ensureFreshCreditAccountForUser(db, auth.user.id, deps);
  timing.mark("account");
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
  timing.mark("parse");
  const products = await relatedRegionProducts(db, product, deps, 6);
  timing.mark("products");
  const quoteResults = await materializedRegionPackQuoteResults(db, auth.user.id, products, account, deps, {
    fastTrack: true,
    jobRound: 0,
    priority: 20,
    triggerType: "region_pack_related_offers_requested",
    staleReason: "region_pack_related_quote_not_ready",
    sourceProductId: normalizedRegionPackProductId(product),
  });
  timing.mark("quotes");
  const offers = [];
  let pendingQuoteCount = 0;
  for (const candidate of products) {
    const quoteEntry = quoteResults.get(normalizedRegionPackProductId(candidate));
    const quote = quoteEntry && quoteEntry.quote;
    if (!quote) {
      pendingQuoteCount += 1;
      continue;
    }
    const offer = regionPackOfferPayload(candidate, quote);
    if (integerCents(offer && offer.price_cents) <= 0 && Number(offer && offer.charged_tile_count || 0) <= 0) {
      continue;
    }
    offers.push(offer);
  }
  timing.mark("estimate");
  const response = deps.json(
    {
      ok: true,
      catalog_version: REGION_PACK_CATALOG_VERSION,
      region_pack: regionProductPublicPayload(product),
      offers,
      price_pending: pendingQuoteCount > 0,
      pending_quote_count: pendingQuoteCount,
    },
    200,
    env,
  );
  return withEndpointTiming(response, timing, env, {
    product_count: products.length,
    pending_quote_count: pendingQuoteCount,
    offer_count: offers.length,
  });
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

export async function handleCreditAccountPageLink(request, env, deps) {
  const auth = await deps.requireAuthenticatedUserContext(request, env, { enforceApiKeyDevicePolicy: false });
  if (auth.error) {
    return auth.error;
  }
  const db = deps.requireDb(env);
  await ensureCreditAccount(db, auth.user.id, deps);
  const tokenResult = await createAccountPageTokenForUser(db, auth.user.id, env, deps);
  const url = new URL(request.url);
  url.pathname = "/credits/account";
  url.search = "";
  url.searchParams.set("token", tokenResult.token);
  return deps.json(
    {
      ok: true,
      url: url.toString(),
      account_url: url.toString(),
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
  const cached = cachedDetailToken("region_pack", safeToken, deps);
  if (cached) {
    return { ok: true, row: cached, cache_hit: true };
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
  cacheDetailToken("region_pack", safeToken, row);
  return { ok: true, row };
}

async function getValidSceneFullQualityDetailToken(db, token, deps) {
  const safeToken = String(token || "").trim();
  if (!safeToken) {
    return { error: "missing_token", status: 400 };
  }
  const cached = cachedDetailToken("scene", safeToken, deps);
  if (cached) {
    let cachedKeys = [];
    try {
      cachedKeys = normalizeTileKeys(JSON.parse(String(cached.tile_keys_json || "[]")));
    } catch (_error) {
      cachedKeys = [];
    }
    if (cachedKeys.length) {
      return { ok: true, row: { ...cached, tile_keys: cachedKeys }, cache_hit: true };
    }
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
  cacheDetailToken("scene", safeToken, row);
  return { ok: true, row: { ...row, tile_keys: tileKeys } };
}

async function getValidAccountPageToken(db, token, deps) {
  const safeToken = String(token || "").trim();
  if (!safeToken) {
    return { error: "missing_token", status: 400 };
  }
  const cached = cachedDetailToken("account_page", safeToken, deps);
  if (cached) {
    return { ok: true, row: cached, cache_hit: true };
  }
  await ensureAccountPageTokenTable(db, deps);
  const now = deps.nowIso();
  const row = await deps.dbGet(
    db,
    `
      SELECT token, user_id, expires_at
      FROM account_page_tokens
      WHERE token = ?
      LIMIT 1
    `,
    [safeToken],
  );
  if (!row || String(row.expires_at || "") <= now) {
    return { error: "expired_token", status: 410 };
  }
  cacheDetailToken("account_page", safeToken, row);
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

async function resolveRegionPackFromDetailTokenRow(db, row, requestedRegionId = "", deps, options = {}) {
  const baseProduct = regionProductById(row && row.region_pack_id);
  if (!baseProduct) {
    return { error: "unknown_region_pack", status: 404 };
  }
  const requestedId = String(requestedRegionId || "").trim();
  const product = requestedId ? regionProductById(requestedId) : baseProduct;
  if (!product || isHiddenRegionProduct(product)) {
    return { error: "region_pack_not_available_for_this_detail_link", status: 403 };
  }
  if (!Boolean(options && options.allowAnyProduct) && !await isSameOrRelatedHigherRegionProduct(db, baseProduct, product, deps)) {
    return { error: "region_pack_not_available_for_this_detail_link", status: 403 };
  }
  return { ok: true, baseProduct, product };
}

async function regionPackCheckoutParams(request) {
  const url = new URL(request.url);
  const params = new Map();
  for (const key of ["token", "region_pack_id", "catalog", "method", "quote_id"]) {
    params.set(key, String(url.searchParams.get(key) || "").trim());
  }
  if (String(request.method || "GET").trim().toUpperCase() === "POST") {
    try {
      const form = await request.formData();
      for (const key of ["token", "region_pack_id", "catalog", "method", "quote_id"]) {
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
    quoteId: String(params.get("quote_id") || "").trim(),
  };
}

function fullQualityPriceBreakdownHtml({
  fullPriceEur = 0,
  alreadyLicencedEur = 0,
  partialLicenceEur = 0,
  discountPercent = 0,
  discountEur = 0,
  finalPriceEur = 0,
} = {}) {
  const full = normalizeCreditAmount(fullPriceEur);
  const already = normalizeCreditAmount(alreadyLicencedEur);
  const partial = normalizeCreditAmount(partialLicenceEur);
  const discount = normalizeCreditAmount(discountEur);
  const final = normalizeCreditAmount(finalPriceEur);
  const pct = Math.max(0, Number.parseInt(discountPercent || 0, 10) || 0);
  let html = `<p class="muted">Full Price: €${full.toFixed(2)}<br>`;
  if (already > 0) {
    html += `Licenced: - €${already.toFixed(2)}<br>`;
  }
  if (partial > 0) {
    html += `Partially licenced: - €${partial.toFixed(2)}<br>`;
  }
  if (discount > 0) {
    html += `Volume Discount (${pct}%): - €${discount.toFixed(2)}<br>`;
  }
  html += `Final Price: €${final.toFixed(2)}</p>`;
  return html;
}

function regionPackPaymentChoiceHtml(data) {
  const product = data && data.product || {};
  const account = data && data.account || {};
  void account;
  const quote = data && data.quote && typeof data.quote === "object" ? data.quote : null;
  if (!quote || !quote.summary) {
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Planetka Data Pack Payment</title><style>${REGION_PACK_CHECKOUT_CSS}</style></head><body><main><section class="panel"><h1>Data pack price is updating.</h1><p>Please wait a few moments, then reload this page or reopen the data pack from Blender.</p></section></main></body></html>`;
  }
  const summary = quote.summary;
  const name = String(product && product.name || "Data Pack").trim() || "Data Pack";
  const token = escapeHtmlText(String(data && data.token || ""));
  const regionPackId = escapeHtmlText(String(product && product.id || ""));
  const quoteInput = quote && quote.quote_id ? `<input type="hidden" name="quote_id" value="${escapeHtmlText(String(quote.quote_id || ""))}">` : "";
  const quoteParam = quote && quote.quote_id ? `&quote_id=${escapeHtmlText(encodeURIComponent(String(quote.quote_id || "")))}` : "";
  const catalogInput = data && data.catalog_mode ? `<input type="hidden" name="catalog" value="1">` : "";
  const catalogParam = data && data.catalog_mode ? "&catalog=1" : "";
  const mapHref = `/credits/region-pack-map?token=${escapeHtmlText(encodeURIComponent(String(data && data.token || "")))}&region_pack_id=${escapeHtmlText(encodeURIComponent(String(product && product.id || "")))}${catalogParam}${quoteParam}`;
  const priceEur = summary.price_eur;
  const fullPriceEur = summary.full_price_eur;
  const partialLicenceCount = summary.partial_licence_tiles;
  const displayedAlreadyLicencedCount = summary.already_licenced_tiles + partialLicenceCount;
  const displayedAlreadyLicencedDeductionEur = normalizeCreditAmount(summary.already_licenced_deduction_eur + summary.partial_licence_credit_eur);
  const discountEur = summary.discount_eur;
  const discountPercent = summary.discount_percent;
  const unlicencedTileCount = summary.new_tiles;
  const stripeAvailable = summary.price_cents >= STRIPE_MIN_CHECKOUT_AMOUNT_CENTS;
  const stripeButton = stripeAvailable
    ? `<form method="post" action="/credits/region-pack-checkout"><input type="hidden" name="token" value="${token}"><input type="hidden" name="region_pack_id" value="${regionPackId}">${catalogInput}${quoteInput}<input type="hidden" name="method" value="stripe"><button class="button" type="submit">Pay Now (€${priceEur.toFixed(2)})</button></form>`
    : `<button class="button disabled" type="button" disabled>Payment gateway unavailable below €${(STRIPE_MIN_CHECKOUT_AMOUNT_CENTS / 100).toFixed(2)}</button>`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>Planetka ${escapeHtmlText(name)} Payment</title>
<style>${REGION_PACK_CHECKOUT_CSS}</style>
</head>
<body>
	<main>
	<h1>${escapeHtmlText(name)} Full Quality Pack</h1>
	<section class="panel">
			<p>Licence this Full Quality data pack with direct payment.</p>
			<div class="summary">
		<div class="card"><span>New Tiles / Total Tiles</span><b>${Math.max(0, unlicencedTileCount - partialLicenceCount)} / ${summary.total_tiles}</b></div>
		<div class="card"><span>Full Price</span><b>€${fullPriceEur.toFixed(2)}</b></div>
		${displayedAlreadyLicencedDeductionEur > 0 ? `<div class="card"><span>Already Licenced</span><b>${displayedAlreadyLicencedCount} tiles (-€${displayedAlreadyLicencedDeductionEur.toFixed(2)})</b></div>` : ""}
		${discountEur > 0 ? `<div class="card"><span>Volume Discount</span><b>${discountPercent}% (-€${discountEur.toFixed(2)})</b></div>` : ""}
	<div class="card"><span>Final Price</span><b>€${priceEur.toFixed(2)}</b></div>
		</div>
	<div class="actions">
	${stripeButton}
	</div>
<div class="links">
<a href="${mapHref}">View detailed map</a>
</div>
</section>
</main>
</body>
</html>`;
}

export async function handleCreditRegionPackCheckoutFromToken(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_pack_checkout");
  const { token, requestedRegionId, allowCatalogProduct, method, quoteId } = await regionPackCheckoutParams(request);
  timing.mark("params");
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  timing.mark("token");
  if (tokenResult.error) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Data Pack</title><h1>This data-pack payment link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 400,
      env,
    ), timing, env, { error: tokenResult.error });
  }
  const productResult = allowCatalogProduct
    ? (() => {
      const product = regionProductById(requestedRegionId || tokenResult.row && tokenResult.row.region_pack_id);
      return product && !isHiddenRegionProduct(product) ? { ok: true, product } : { error: "region_pack_not_available_for_this_detail_link", status: 403 };
    })()
    : await resolveRegionPackFromDetailTokenRow(db, tokenResult.row, requestedRegionId, deps);
  if (!productResult.error && isHiddenRegionProduct(productResult.product)) {
    productResult.error = "region_pack_not_available_for_this_detail_link";
    productResult.status = 404;
  }
  timing.mark("product");
  if (productResult.error) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Data Pack</title><h1>Data pack unavailable.</h1><p>${escapeHtmlText(productResult.error)}</p>`,
      productResult.status || 400,
      env,
    ), timing, env, { error: productResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const user = await deps.dbGet(
    db,
    `SELECT id, email FROM users WHERE id = ? LIMIT 1`,
    [userId],
  );
  const email = deps.normalizeEmail(user && user.email || "");
  const product = productResult.product;
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  timing.mark("account");
  const quoteResult = await materializedRegionPackQuoteResult(db, userId, product, account, deps, {
    quoteId,
    fastTrack: true,
    jobRound: 0,
    priority: 0,
    triggerType: "region_pack_checkout_page_requested",
    staleReason: "region_pack_checkout_quote_not_ready",
  });
  let quote = quoteResult.quote;
  timing.mark("quote");
  if (!quote) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Data Pack</title><h1>Data pack price is updating.</h1><p>Please wait a few moments, then reload this page or reopen the data pack from Blender.</p>`,
      409,
      env,
    ), timing, env, {
      error: "data_pack_price_updating",
      quote_status: String(quoteResult.quoteStatus || "missing"),
      region_pack_id: String(product && product.id || ""),
    });
  }
  quote = await accountSpecificRegionPackQuoteForCheckout(db, quote, userId, product, account, deps);
  timing.mark("checkout_quote");
  if (method === "stripe" && quoteResult.requestedQuoteMismatch) {
    return withEndpointTiming(html(
      regionPackPaymentChoiceHtml({
        token,
        product,
        account,
        quote,
        catalog_mode: allowCatalogProduct,
      }),
      200,
      env,
    ), timing, env, {
      region_pack_id: String(product && product.id || ""),
      quote_id: String(quote && quote.quote_id || ""),
      quote_id_mismatch: true,
    });
  }
  const summary = regionPackQuoteSummary(quote);
  const priceCents = integerCents(summary.price_cents);
  if (priceCents <= 0) {
    if (Math.max(0, Number.parseInt(summary.new_tiles || 0, 10) || 0) <= 0) {
      return html(
        checkoutReturnHtml({
          title: "Planetka Data Pack",
          heading: `${String(product.name || "Data Pack")} is already licenced`,
          message: "This pack has no newly charged Full Quality tiles. You can return to Blender.",
          icon: "OK",
          tone: "success",
        }),
        200,
        env,
      );
    }
    const grant = await grantRegionPackEntitlements(
      db,
      userId,
      String(product.id || ""),
      `region_pack_no_payment_${deps.randomToken(8)}`,
      0,
      deps,
      email,
      "",
      { quote, payment_source: "none" },
    );
    if (grant && grant.error) {
      return html(
        `<!doctype html><title>Planetka Data Pack</title><h1>Data pack licence failed.</h1><p>${escapeHtmlText(grant.error)}</p>`,
        500,
        env,
      );
    }
    return html(
      checkoutReturnHtml({
        title: "Planetka Data Pack",
        heading: `${String(product.name || "Data Pack")} licence applied`,
        message: "This promotional Full Quality data pack has been licenced at no charge. You can return to Blender.",
        icon: "OK",
        tone: "success",
      }),
      200,
      env,
    );
  }
  const amountCents = priceCents;

  if (method && method !== "stripe") {
    return withEndpointTiming(html(
      regionPackPaymentChoiceHtml({
        token,
        product,
        account,
        quote,
        catalog_mode: allowCatalogProduct,
      }),
      410,
      env,
    ), timing, env, { region_pack_id: String(product && product.id || ""), method, error: "payment_method_removed" });
  }

  if (amountCents < STRIPE_MIN_CHECKOUT_AMOUNT_CENTS) {
    return withEndpointTiming(html(
      regionPackPaymentChoiceHtml({
        token,
        product,
        account,
        quote,
        catalog_mode: allowCatalogProduct,
      }),
      400,
      env,
    ), timing, env, { region_pack_id: String(product && product.id || ""), error: "below_stripe_minimum" });
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
	        planetka_quote_id: String(quote.quote_id || ""),
	        planetka_pricing_version: String(quote.pricing_version || ""),
	        planetka_entitlement_version: String(quote.entitlement_version || "").slice(0, 240),
	        planetka_price_eur: summary.price_eur.toFixed(2),
	        planetka_price_cents: String(summary.price_cents),
	        planetka_gross_eur: summary.full_price_eur.toFixed(2),
	        planetka_discount_percent: String(summary.discount_percent),
	        planetka_discount_eur: summary.discount_eur.toFixed(2),
	        planetka_already_licenced_gross_eur: summary.already_licenced_deduction_eur.toFixed(2),
	        planetka_partial_licence_credit_eur: summary.partial_licence_credit_eur.toFixed(2),
	        planetka_checkout_source: allowCatalogProduct ? "region_pack_catalog" : "region_pack_map_upsell",
	      },
	    },
    deps,
  );
  timing.mark("stripe_session");
  if (session.error || !session.checkout_url) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Data Pack</title><h1>Payment checkout failed.</h1><p>${escapeHtmlText(session.message || session.error || "checkout_failed")}</p>`,
      502,
      env,
    ), timing, env, { error: session.message || session.error || "checkout_failed", region_pack_id: String(product && product.id || "") });
  }
  return withEndpointTiming(new Response(null, {
    status: 303,
    headers: {
      Location: session.checkout_url,
      "Cache-Control": "no-store",
      "X-Planetka-Price-Cents": String(amountCents),
      "X-Planetka-Region-Pack-Id": String(product && product.id || ""),
      "X-Planetka-Quote-Id": String(quote.quote_id || ""),
    },
  }), timing, env, {
    region_pack_id: String(product && product.id || ""),
    amount_cents: amountCents,
    quote_id: String(quote.quote_id || ""),
  });
}

export async function handleCreditRegionPackMap(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_pack_map");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const allowCatalogProduct = String(url.searchParams.get("catalog") || "") === "1";
  if (!token) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Data Pack</title><h1>Missing data-pack detail token.</h1>",
      400,
      env,
    ), timing, env, { error: "missing_token" });
  }
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  timing.mark("token");
  if (tokenResult.error) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Data Pack</title><h1>This data-pack detail link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 410,
      env,
    ), timing, env, { error: tokenResult.error });
  }
  const requestedRegionId = String(url.searchParams.get("region_pack_id") || "").trim();
  const productResult = allowCatalogProduct
    ? (() => {
      const product = regionProductById(requestedRegionId || tokenResult.row && tokenResult.row.region_pack_id);
      return product ? { ok: true, product } : { error: "region_pack_not_available_for_this_detail_link", status: 403 };
    })()
    : await resolveRegionPackFromDetailTokenRow(db, tokenResult.row, requestedRegionId, deps);
  timing.mark("product");
  if (productResult.error) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Data Pack</title><h1>Data pack unavailable.</h1><p>${escapeHtmlText(productResult.error)}</p>`,
      productResult.status || 404,
      env,
    ), timing, env, { error: productResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const product = productResult.product;
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  timing.mark("account");
  const requestedQuoteId = String(url.searchParams.get("quote_id") || "").trim();
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  const quoteUserId = productQuoteLookupUserIdForAccount(userId, account);
  const productId = String(product && product.id || "").trim().toLowerCase();
  const quoteRows = await loadUserProductQuoteRows(db, quoteUserId, [productId], deps, { includeMapState: false });
  const quoteRow = quoteRows.get(productId) || null;
  let quoteStatus = productQuoteStatus(quoteRow, pricingVersion, entitlementVersion);
  let quote = quoteStatus === "ready" ? userProductQuoteFromRow(quoteRow) : null;
  const requestedQuoteMismatch = Boolean(requestedQuoteId && quote && String(quote.quote_id || "") !== requestedQuoteId);
  let mapState = null;
  let mapStateStatus = "not_requested";
  if (quoteStatus === "ready") {
    const levelCounts = await regionPackTileLevelCountsForProduct(db, product, deps);
    const levels = Object.keys(levelCounts)
      .map((level) => Number.parseInt(level, 10))
      .filter((level) => isRegionPackPaidZLevel(level))
      .sort((a, b) => a - b);
    mapState = {
      schema: 4,
      on_demand: true,
      tile_status_mode: "on_demand_level_chunks",
      region_pack: regionProductPublicPayload(product),
      product_full_quality_unlocked: Boolean(quote && quote.summary && integerCents(quote.summary.price_cents) <= 0),
      bounds: regionMapBounds(product, GENERATED_REGION_PACK_DETAILS[String(product && product.id || "")] || {}, []),
      outlines: regionProductOutlinesForMap(product),
      included_countries: regionProductIncludedCountries(product),
      levels,
      default_level: defaultRegionPackMapLevel(levelCounts),
      level_tile_counts: levelCounts,
      chunk_limit: REGION_PACK_MAP_LEVEL_CHUNK_LIMIT,
      tiles: [],
    };
    mapStateStatus = "ready";
  }
  if (quoteStatus !== "ready") {
    await enqueueUserProductQuoteJob(db, quoteUserId, productId, pricingVersion, entitlementVersion, deps, {
      staleReason: `product_page_quote_${quoteStatus}`,
      jobRound: 0,
      priority: 0,
      triggerType: "product_page_quote_requested",
      fastTrack: true,
    });
  }
  timing.mark("quote_rows");
  // Product pages only read materialized quote/map-state rows. Missing rows are
  // queued above and shown as updating instead of calculated in this request.
  const relatedLimit = regionProductRank(product) === 2 ? 96 : 16;
  const upsells = quoteStatus === "ready"
    ? await relatedRegionPackQuoteEntries(db, product, userId, account, null, deps, {
      limit: relatedLimit,
      priority: 60,
      triggerType: "product_page_related_quote_requested",
      staleReason: "product_page_related_quote_not_ready",
      includePending: true,
    })
    : [];
  timing.mark("upsells");
  const data = regionPackStaticMapPayload(product, token, account, [], {
    catalogMode: allowCatalogProduct,
    quote,
    quoteStatus,
    pricePending: quoteStatus !== "ready",
    mapState,
    mapStateStatus,
    mapPending: quoteStatus !== "ready",
    upsells,
  });
  timing.mark("payload");
  return withEndpointTiming(html(regionPackStaticMapHtml(data), 200, env), timing, env, {
    region_pack_id: String(product && product.id || ""),
    quote_rows_read_only: true,
    quote_status: quoteStatus,
    map_state_status: mapStateStatus,
    quote_id: String(quote && quote.quote_id || ""),
    quote_id_mismatch: requestedQuoteMismatch,
  });
}

export async function handleCreditRegionPackMapLevelChunk(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_pack_map_level_chunk");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const allowCatalogProduct = String(url.searchParams.get("catalog") || "") === "1";
  if (!token) {
    return withEndpointTiming(deps.json({ ok: false, error: "missing_token" }, 400, env), timing, env, { error: "missing_token" });
  }
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  if (tokenResult.error) {
    return withEndpointTiming(deps.json({ ok: false, error: tokenResult.error }, tokenResult.status || 410, env), timing, env, { error: tokenResult.error });
  }
  const requestedRegionId = String(url.searchParams.get("region_pack_id") || "").trim();
  const productResult = allowCatalogProduct
    ? (() => {
      const product = regionProductById(requestedRegionId || tokenResult.row && tokenResult.row.region_pack_id);
      return product ? { ok: true, product } : { error: "region_pack_not_available_for_this_detail_link", status: 403 };
    })()
    : await resolveRegionPackFromDetailTokenRow(db, tokenResult.row, requestedRegionId, deps);
  if (productResult.error) {
    return withEndpointTiming(deps.json({ ok: false, error: productResult.error }, productResult.status || 404, env), timing, env, { error: productResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const product = productResult.product;
  const productId = String(product && product.id || "").trim().toLowerCase();
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  const quoteUserId = productQuoteLookupUserIdForAccount(userId, account);
  const quoteRows = await loadUserProductQuoteRows(db, quoteUserId, [productId], deps, { includeMapState: false });
  const quoteRow = quoteRows.get(productId) || null;
  const quoteStatus = productQuoteStatus(quoteRow, pricingVersion, entitlementVersion);
  if (quoteStatus !== "ready") {
    await enqueueUserProductQuoteJob(db, quoteUserId, productId, pricingVersion, entitlementVersion, deps, {
      staleReason: `map_chunk_quote_${quoteStatus}`,
      jobRound: 0,
      priority: 0,
      triggerType: "map_chunk_quote_requested",
      fastTrack: true,
    });
    return withEndpointTiming(deps.json({ ok: false, error: "quote_not_ready", quote_status: quoteStatus }, 409, env), timing, env, { region_pack_id: productId, quote_status: quoteStatus });
  }
  const requestedQuoteId = String(url.searchParams.get("quote_id") || "").trim();
  if (requestedQuoteId && String(quoteRow && quoteRow.quote_id || "") !== requestedQuoteId) {
    return withEndpointTiming(deps.json({ ok: false, error: "quote_id_mismatch" }, 409, env), timing, env, { region_pack_id: productId });
  }
  const quote = userProductQuoteFromRow(quoteRow);
  if (!quote || !quote.summary) {
    return withEndpointTiming(deps.json({ ok: false, error: "quote_payload_unavailable" }, 409, env), timing, env, { region_pack_id: productId });
  }
  const level = Math.max(1, Number.parseInt(url.searchParams.get("level") || "0", 10) || 0);
  const limit = Math.max(1, Math.min(REGION_PACK_MAP_LEVEL_CHUNK_LIMIT, Number.parseInt(url.searchParams.get("limit") || REGION_PACK_MAP_LEVEL_CHUNK_LIMIT, 10) || REGION_PACK_MAP_LEVEL_CHUNK_LIMIT));
  const cursor = {
    family_key: String(url.searchParams.get("cursor_family_key") || "").trim(),
    d: Number.parseInt(url.searchParams.get("cursor_d") || "0", 10) || 0,
    tile_key: normalizeTileKey(url.searchParams.get("cursor_tile_key") || ""),
  };
  const rows = await regionPackTileRowsForProductLevelAfterCursor(db, product, level, deps, { limit, cursor });
  timing.mark("tile_rows");
  const context = await buildUserProductMapChunkContext(db, product, quote, account, deps, rows, { userId });
  const tiles = [];
  for (const row of rows) {
    const tile = buildUserProductMapTileFromRow(row, context);
    if (tile) {
      tiles.push(applyOnDemandMapTileDiscount(tile, context));
    }
  }
  timing.mark("tiles");
  const last = rows.length ? rows[rows.length - 1] : null;
  const nextCursor = rows.length >= limit && last
    ? {
      family_key: String(last.family || last.family_key || ""),
      d: Number.parseInt(last.parsed && last.parsed.d || last.d || 0, 10) || 0,
      tile_key: normalizeTileKey(last.key || last.tile_key || ""),
    }
    : null;
  const levelCounts = await regionPackTileLevelCountsForProduct(db, product, deps);
  const expectedCount = Math.max(0, Number.parseInt(levelCounts[String(level)] || 0, 10) || 0);
  return withEndpointTiming(deps.json({
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    region_pack_id: productId,
    quote_id: String(quote.quote_id || ""),
    level,
    count: tiles.length,
    expected_count: expectedCount,
    next_cursor: nextCursor,
    tiles,
  }, 200, env), timing, env, {
    region_pack_id: productId,
    quote_id: String(quote.quote_id || ""),
    level,
    count: tiles.length,
    has_next: Boolean(nextCursor),
  });
}

export async function handleCreditRegionPackMapStateShard(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_pack_map_state_shard");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const allowCatalogProduct = String(url.searchParams.get("catalog") || "") === "1";
  if (!token) {
    return withEndpointTiming(deps.json({ ok: false, error: "missing_token" }, 400, env), timing, env, { error: "missing_token" });
  }
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  if (tokenResult.error) {
    return withEndpointTiming(deps.json({ ok: false, error: tokenResult.error }, tokenResult.status || 410, env), timing, env, { error: tokenResult.error });
  }
  const requestedRegionId = String(url.searchParams.get("region_pack_id") || "").trim();
  const productResult = allowCatalogProduct
    ? (() => {
      const product = regionProductById(requestedRegionId || tokenResult.row && tokenResult.row.region_pack_id);
      return product ? { ok: true, product } : { error: "region_pack_not_available_for_this_detail_link", status: 403 };
    })()
    : await resolveRegionPackFromDetailTokenRow(db, tokenResult.row, requestedRegionId, deps);
  if (productResult.error) {
    return withEndpointTiming(deps.json({ ok: false, error: productResult.error }, productResult.status || 404, env), timing, env, { error: productResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const product = productResult.product;
  const productId = String(product && product.id || "").trim().toLowerCase();
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  const quoteUserId = productQuoteLookupUserIdForAccount(userId, account);
  const quoteRows = await loadUserProductQuoteRows(db, quoteUserId, [productId], deps, { includeMapState: true });
  const quoteRow = quoteRows.get(productId) || null;
  const quoteStatus = productQuoteStatus(quoteRow, pricingVersion, entitlementVersion);
  if (quoteStatus !== "ready") {
    return withEndpointTiming(deps.json({ ok: false, error: "quote_not_ready" }, 409, env), timing, env, { region_pack_id: productId, quote_status: quoteStatus });
  }
  const requestedQuoteId = String(url.searchParams.get("quote_id") || "").trim();
  if (requestedQuoteId && String(quoteRow && quoteRow.quote_id || "") !== requestedQuoteId) {
    return withEndpointTiming(deps.json({ ok: false, error: "quote_id_mismatch" }, 409, env), timing, env, { region_pack_id: productId });
  }
  const mapState = await parseUserProductMapState(quoteRow, env);
  if (!mapState || !mapState.sharded || !mapState.level_shards || typeof mapState.level_shards !== "object") {
    return withEndpointTiming(deps.json({ ok: false, error: "map_state_shard_not_ready" }, 409, env), timing, env, { region_pack_id: productId });
  }
  const level = String(Math.max(1, Number.parseInt(url.searchParams.get("level") || "0", 10) || 0));
  const shardIndex = Math.max(0, Number.parseInt(url.searchParams.get("shard") || "0", 10) || 0);
  const shards = Array.isArray(mapState.level_shards[level]) ? mapState.level_shards[level] : [];
  const descriptor = shards.find((item, index) => Math.max(0, Number.parseInt(item && item.index || index, 10) || 0) === shardIndex);
  const key = String(descriptor && descriptor.key || "").trim();
  const bucket = env && env.PLANETKA_DATA;
  if (!key || !bucket || typeof bucket.get !== "function") {
    return withEndpointTiming(deps.json({ ok: false, error: "map_state_shard_missing" }, 404, env), timing, env, { region_pack_id: productId, level, shard_index: shardIndex });
  }
  const object = await bucket.get(key);
  if (!object || !object.body) {
    return withEndpointTiming(deps.json({ ok: false, error: "map_state_shard_missing" }, 404, env), timing, env, { region_pack_id: productId, level, shard_index: shardIndex });
  }
  return withEndpointTiming(new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...corsHeaders(env),
    },
  }), timing, env, { region_pack_id: productId, level, shard_index: shardIndex });
}


function chooseMiniMapPreviewLevel(levelCounts, maxTiles = 250) {
  const entries = Object.entries(levelCounts || {})
    .map(([level, count]) => [Math.max(1, Number.parseInt(level || 0, 10) || 0), Math.max(0, Number.parseInt(count || 0, 10) || 0)])
    .filter(([level, count]) => isRegionPackPaidZLevel(level) && count > 0)
    .sort((a, b) => a[0] - b[0]);
  const underLimit = entries.find(([, count]) => count <= maxTiles);
  if (underLimit) {
    return underLimit[0];
  }
  return entries.length ? entries[entries.length - 1][0] : 1;
}

export async function handleCreditRegionPackMiniMap(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_pack_mini_map");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const allowCatalogProduct = String(url.searchParams.get("catalog") || "") === "1";
  if (!token) {
    return withEndpointTiming(deps.json({ ok: false, error: "missing_token" }, 400, env), timing, env, { error: "missing_token" });
  }
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  if (tokenResult.error) {
    return withEndpointTiming(deps.json({ ok: false, error: tokenResult.error }, tokenResult.status || 410, env), timing, env, { error: tokenResult.error });
  }
  const requestedRegionId = String(url.searchParams.get("region_pack_id") || "").trim();
  const productResult = allowCatalogProduct
    ? (() => {
      const product = regionProductById(requestedRegionId || tokenResult.row && tokenResult.row.region_pack_id);
      return product ? { ok: true, product } : { error: "region_pack_not_available_for_this_detail_link", status: 403 };
    })()
    : await resolveRegionPackFromDetailTokenRow(db, tokenResult.row, requestedRegionId, deps);
  if (productResult.error) {
    return withEndpointTiming(deps.json({ ok: false, error: productResult.error }, productResult.status || 404, env), timing, env, { error: productResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const product = productResult.product;
  const productId = String(product && product.id || "").trim().toLowerCase();
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  const pricingVersion = pricingSettingsCacheKey();
  const entitlementVersion = accountEntitlementVersion(account);
  const quoteUserId = productQuoteLookupUserIdForAccount(userId, account);
  const quoteRows = await loadUserProductQuoteRows(db, quoteUserId, [productId], deps, { includeMapState: false });
  const quoteRow = quoteRows.get(productId) || null;
  const quoteStatus = productQuoteStatus(quoteRow, pricingVersion, entitlementVersion);
  if (quoteStatus !== "ready") {
    return withEndpointTiming(deps.json({ ok: false, error: "quote_not_ready", quote_status: quoteStatus }, 409, env), timing, env, { region_pack_id: productId, quote_status: quoteStatus });
  }
  const requestedQuoteId = String(url.searchParams.get("quote_id") || "").trim();
  if (requestedQuoteId && String(quoteRow && quoteRow.quote_id || "") !== requestedQuoteId) {
    return withEndpointTiming(deps.json({ ok: false, error: "quote_id_mismatch" }, 409, env), timing, env, { region_pack_id: productId });
  }
  const quote = userProductQuoteFromRow(quoteRow);
  if (!quote || !quote.summary) {
    return withEndpointTiming(deps.json({ ok: false, error: "quote_payload_unavailable" }, 409, env), timing, env, { region_pack_id: productId });
  }
  const levelCounts = await regionPackTileLevelCountsForProduct(db, product, deps);
  const productIdForLevel = String(product && product.id || "").trim().toLowerCase();
  const level = productIdForLevel === "world" ? 30 : chooseMiniMapPreviewLevel(levelCounts, 250);
  const levelTileCount = Math.max(0, Number.parseInt(levelCounts[String(level)] || 0, 10) || 0);
  const rowLimit = levelTileCount > 250 ? Math.min(levelTileCount, 500) : 250;
  timing.mark("level");
  const rows = await regionPackTileRowsForProductLevelAfterCursor(db, product, level, deps, { limit: rowLimit });
  timing.mark("tile_rows");
  const context = await buildUserProductMapChunkContext(db, product, quote, account, deps, rows, { userId });
  const tiles = [];
  for (const row of rows) {
    const tile = buildUserProductMapTileFromRow(row, context);
    if (tile) {
      const priced = applyOnDemandMapTileDiscount(tile, context);
      tiles.push({
        tile_key: priced.tile_key,
        status: priced.status,
        lon_min: priced.lon_min,
        lon_max: priced.lon_max,
        lat_min: priced.lat_min,
        lat_max: priced.lat_max,
      });
    }
  }
  timing.mark("tiles");
  const publicProduct = regionProductPublicPayload(product);
  return withEndpointTiming(deps.json({
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    region_pack: publicProduct,
    bounds: publicProduct.bounds,
    outlines: [],
    level,
    level_tile_count: levelTileCount || rows.length,
    tiles,
  }, 200, env, { "Cache-Control": "no-store" }), timing, env, { region_pack_id: productId, level, count: tiles.length });
}

export async function handleCreditRegionPackMapAsset(request, env, deps) {
  const timing = createEndpointTimer("credits.region_pack_map_asset");
  const url = new URL(request.url);
  const regionPackId = String(url.searchParams.get("region_pack_id") || url.searchParams.get("id") || "").trim();
  const product = regionProductById(regionPackId);
  if (!product || isHiddenRegionProduct(product)) {
    return withEndpointTiming(deps.json({ ok: false, error: "region_pack_map_asset_not_available" }, 404, env), timing, env, { region_pack_id: regionPackId });
  }
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return withEndpointTiming(deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env), timing, env, { region_pack_id: regionPackId });
  }
  const object = await bucket.get(regionPackMapAssetKey(env, product.id));
  timing.mark("r2_get");
  if (!object || !object.body) {
    return withEndpointTiming(deps.json({ ok: false, error: "region_pack_map_asset_missing" }, 404, env), timing, env, { region_pack_id: regionPackId });
  }
  return withEndpointTiming(new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      ...corsHeaders(env),
    },
  }), timing, env, { region_pack_id: regionPackId });
}

export async function handleCreditRegionPackMapOutlines(request, env, deps) {
  const timing = createEndpointTimer("credits.region_pack_map_outlines");
  const url = new URL(request.url);
  const regionPackId = String(url.searchParams.get("region_pack_id") || url.searchParams.get("id") || "").trim();
  const product = regionProductById(regionPackId);
  if (!product || isHiddenRegionProduct(product)) {
    return withEndpointTiming(deps.json({ ok: false, error: "region_pack_map_outlines_not_available" }, 404, env), timing, env, { region_pack_id: regionPackId });
  }
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return withEndpointTiming(deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env), timing, env, { region_pack_id: regionPackId });
  }
  let object = await bucket.get(regionPackMapOutlinesAssetKey(env, product.id));
  timing.mark("r2_outline_get");
  if (object && object.body) {
    return withEndpointTiming(new Response(object.body, {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "public, max-age=86400",
        ...corsHeaders(env),
      },
    }), timing, env, { region_pack_id: regionPackId, source: "outline_asset" });
  }
  object = await bucket.get(regionPackMapAssetKey(env, product.id));
  timing.mark("r2_map_asset_get");
  if (!object || !object.body) {
    return withEndpointTiming(deps.json({ ok: false, error: "region_pack_map_outlines_missing" }, 404, env), timing, env, { region_pack_id: regionPackId });
  }
  const fullAsset = await object.json();
  const payload = {
    ok: true,
    static_outline_asset: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    region_pack: regionProductPublicPayload(product),
    bounds: fullAsset && fullAsset.bounds || null,
    outlines: Array.isArray(fullAsset && fullAsset.outlines) ? fullAsset.outlines : [],
  };
  return withEndpointTiming(deps.json(payload, 200, env, {
    "Cache-Control": "public, max-age=300",
  }), timing, env, { region_pack_id: regionPackId, source: "map_asset_fallback" });
}

export async function handleCreditAccountCountryBorders(request, env, deps) {
  const timing = createEndpointTimer("credits.account_country_borders");
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return withEndpointTiming(deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env), timing, env);
  }
  const object = await bucket.get(accountCountryBordersAssetKey(env));
  timing.mark("r2_get");
  if (!object || !object.body) {
    return withEndpointTiming(deps.json({ ok: false, error: "account_country_borders_missing" }, 404, env), timing, env);
  }
  return withEndpointTiming(new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=86400",
      ...corsHeaders(env),
    },
  }), timing, env);
}

export async function handleCreditRegionPackMapBackground(request, env, deps) {
  const timing = createEndpointTimer("credits.region_pack_map_background");
  const url = new URL(request.url);
  const regionPackId = String(url.searchParams.get("region_pack_id") || url.searchParams.get("id") || "").trim();
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return withEndpointTiming(deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env), timing, env);
  }
  let key = "";
  let object = null;
  if (regionPackId) {
    key = regionPackMapProductBackgroundKey(env, regionPackId);
    object = key ? await bucket.get(key) : null;
    timing.mark(object && object.body ? "r2_get_product" : "r2_get_product_miss");
  }
  if (regionPackId && (!object || !object.body)) {
    return withEndpointTiming(deps.json({ ok: false, error: "region_pack_product_background_missing" }, 404, env), timing, env, { region_pack_id: regionPackId, key });
  }
  if (!object || !object.body) {
    key = regionPackMapBackgroundKey(env);
    object = await bucket.get(key);
  }
  timing.mark("r2_get");
  if (!object || !object.body) {
    return withEndpointTiming(deps.json({ ok: false, error: "region_pack_map_background_missing" }, 404, env), timing, env);
  }
  return withEndpointTiming(new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": "public, max-age=86400",
      ...corsHeaders(env),
    },
  }), timing, env, { region_pack_id: regionPackId || "world", key });
}

export async function handleCreditRegionPackCatalog(request, env, deps) {
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return html(
      "<!doctype html><title>Planetka Data Packs</title><h1>Missing data-pack detail token.</h1>",
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
  const timing = createEndpointTimer("credits.region_pack_catalog");
  const productCount = sortedCatalogProducts().length;
  timing.mark("shell");
  return withEndpointTiming(html(
    regionPackCatalogShellHtml({
      ok: true,
      catalog_version: REGION_PACK_CATALOG_VERSION,
      token,
      total_packs: productCount,
    }),
    200,
    env,
  ), timing, env, { product_count: productCount, paged: true });
}

export async function handleCreditRegionPackCatalogPage(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.region_pack_catalog_page");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const offset = Math.max(0, Number.parseInt(url.searchParams.get("offset") || "0", 10) || 0);
  const limit = Math.max(1, Math.min(REGION_PACK_CATALOG_PAGE_MAX_LIMIT, Number.parseInt(url.searchParams.get("limit") || "1", 10) || 1));
  const db = deps.requireDb(env);
  const tokenResult = await getValidAnyDetailToken(db, token, deps);
  timing.mark("token");
  if (tokenResult.error) {
    return withEndpointTiming(deps.json({ ok: false, error: tokenResult.error }, tokenResult.status || 400, env), timing, env, { error: tokenResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const data = await buildRegionPackCatalogPageData(db, userId, token, deps, { offset, limit });
  timing.mark("catalog_page");
  return withEndpointTiming(deps.json(data, 200, env), timing, env, {
    offset,
    limit,
    row_count: Array.isArray(data && data.rows) ? data.rows.length : 0,
    total_packs: Number(data && data.total_packs || 0),
    ready_quote_rows: Number(data && data.ready_quote_rows || 0),
    queued_quote_jobs: Number(data && data.queued_quote_jobs || 0),
    quote_rows_read_only: Boolean(data && data.quote_rows_read_only),
  });
}

export async function handleCreditSceneMap(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.scene_map");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Scene Textures</title><h1>Missing scene detail token.</h1>",
      400,
      env,
    ), timing, env, { error: "missing_token" });
  }
  const db = deps.requireDb(env);
  const tokenResult = await getValidSceneFullQualityDetailToken(db, token, deps);
  timing.mark("token");
  if (tokenResult.error) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Scene Textures</title><h1>This scene detail link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 410,
      env,
    ), timing, env, { error: tokenResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  timing.mark("account");
  const tileKeys = normalizeTileKeys(tokenResult.row && tokenResult.row.tile_keys);
  const estimate = await estimateNewCredits(db, userId, tileKeys, "full", deps);
  timing.mark("estimate");
  if (estimate && estimate.error) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Scene Textures</title><h1>Scene estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
      500,
      env,
    ), timing, env, { error: estimate.error, tile_count: tileKeys.length });
  }
  const preliminaryRows = allocatedRegionPackTileRows(estimate);
  const contextProduct = await sceneSuccessContextProduct(db, tileKeys, preliminaryRows, deps);
  timing.mark("products");
  if (!contextProduct) {
    const data = buildSceneFullQualityMapData(estimate, { token, contextProduct: null, upsells: [] });
    timing.mark("html");
    return withEndpointTiming(html(regionPackMapHtml(data), 200, env), timing, env, {
      tile_count: tileKeys.length,
      fallback_scene_map: true,
    });
  }
  const upsells = [];
  const relatedEntries = await relevantSceneProductPackReadyQuoteEntries(db, contextProduct, userId, account, deps, { limit: 8 });
  for (const entry of relatedEntries) {
    const card = entry.quote
      ? buildRegionPackUpsellCardData(entry.product, entry.quote, { includeTiles: false })
      : {
        region_pack: regionProductPublicPayload(entry.product),
        asset_id: String(entry.product && entry.product.id || ""),
        quote_id: "",
        summary: null,
      };
    if (card) {
      upsells.push(card);
    }
  }
  timing.mark("upsells");
  const quote = sceneQuoteForStaticMap(estimate, userId, account, token, deps);
  const mapState = await sceneProductContextMapState(db, contextProduct, estimate, deps);
  const sceneCheckoutUrl = `/credits/scene-checkout?token=${encodeURIComponent(token)}`;
  const data = regionPackStaticMapPayload(contextProduct, token, account, [], {
    catalogMode: true,
    quote,
    quoteStatus: "ready",
    pricePending: false,
    mapState,
    mapStateStatus: "ready",
    mapPending: false,
    upsells,
    upsellTitle: "Relevant Product Packs",
    pageTitle: "Full Quality for This Scene",
    sceneDetail: true,
    sceneCheckoutUrl,
  });
  timing.mark("html");
  return withEndpointTiming(html(regionPackStaticMapHtml(data), 200, env), timing, env, {
    tile_count: tileKeys.length,
    context_product_id: String(contextProduct && contextProduct.id || ""),
    upsell_count: upsells.length,
  });
}

export async function handleCreditSceneCheckout(request, env, deps) {
  await ensureRuntimePricingSettings(env, deps);
  const timing = createEndpointTimer("credits.scene_checkout");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Scene Payment</title><h1>Missing scene payment token.</h1>",
      400,
      env,
    ), timing, env, { error: "missing_token" });
  }
  const db = deps.requireDb(env);
  const tokenResult = await getValidSceneFullQualityDetailToken(db, token, deps);
  if (tokenResult.error) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Scene Payment</title><h1>This scene payment link expired.</h1><p>Please reopen it from Blender.</p>",
      tokenResult.status || 410,
      env,
    ), timing, env, { error: tokenResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  const email = String(account && account.email || "").trim();
  const tileKeys = normalizeTileKeys(tokenResult.row && tokenResult.row.tile_keys);
  const estimate = await estimateNewCredits(db, userId, tileKeys, "full", deps);
  if (estimate && estimate.error) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Scene Payment</title><h1>Scene estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
      500,
      env,
    ), timing, env, { error: estimate.error });
  }
  const scenePolicy = scenePaymentPolicyForEstimate(estimate);
  if (scenePolicy.scene_payable_cents <= 0) {
    const unlockResult = await unlockTilesForSession(
      db,
      userId,
      "full",
      tileKeys,
      `scene_checkout_no_payment_${deps.randomToken(8)}`,
      deps,
      { allowSmallSceneFree: true },
    );
    if (unlockResult && unlockResult.error) {
      return withEndpointTiming(html(
        `<!doctype html><title>Planetka Scene Payment</title><h1>Scene licence failed.</h1><p>${escapeHtmlText(unlockResult.error)}</p>`,
        400,
        env,
      ), timing, env, { error: unlockResult.error });
    }
    return withEndpointTiming(html(
      checkoutReturnHtml({
        title: "Planetka Full Quality Scene",
        heading: "Scene licenced",
        message: "This Full Quality scene has no newly charged tiles. Return to Blender; the panel will refresh automatically.",
        icon: "OK",
        tone: "success",
      }),
      200,
      env,
    ), timing, env, { no_payment_required: true });
  }
  const amountCents = integerCents(scenePolicy.scene_payable_cents);
  if (amountCents < STRIPE_MIN_CHECKOUT_AMOUNT_CENTS) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Scene Payment</title><h1>Scene payment is below the minimum card payment amount.</h1><p>Please choose a larger Full Quality scene or a data pack.</p>",
      400,
      env,
    ), timing, env, { error: "amount_below_stripe_minimum" });
  }
  const session = await createStripeCheckoutSession(
    env,
    {
      amountCents,
      customerEmail: email,
      clientReferenceId: userId,
      productName: "Planetka Custom Scene-Specific Licence",
      metadata: {
        planetka_purchase_type: "scene_tiles",
        planetka_user_id: userId,
        planetka_email: email,
        planetka_quality_mode: "full",
        planetka_tile_set_token: token,
        planetka_price_eur: scenePolicy.scene_payable_eur.toFixed(2),
        planetka_scene_tile_price_eur: scenePolicy.scene_tile_price_eur.toFixed(2),
        planetka_custom_scene_licence_eur: scenePolicy.custom_scene_licence_eur.toFixed(2),
        planetka_scene_payable_eur: scenePolicy.scene_payable_eur.toFixed(2),
        planetka_custom_scene_licence_label: SCENE_CUSTOM_LICENCE_LABEL,
        planetka_scene_custom_licence_applied: scenePolicy.scene_custom_licence_applied ? "1" : "0",
        planetka_scene_small_free_threshold_eur: scenePolicy.scene_small_free_threshold_eur.toFixed(2),
        planetka_scene_small_free_threshold_applied: scenePolicy.scene_small_free_threshold_applied ? "1" : "0",
        planetka_paid_tile_count: String(Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0)),
      },
    },
    deps,
  );
  if (session.error || !session.checkout_url) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Scene Payment</title><h1>Checkout could not be created.</h1><p>${escapeHtmlText(session.error || "stripe_checkout_create_failed")}</p>`,
      502,
      env,
    ), timing, env, { error: session.error || "stripe_checkout_create_failed" });
  }
  return withEndpointTiming(Response.redirect(session.checkout_url, 303), timing, env, {
    tile_count: tileKeys.length,
    amount_cents: amountCents,
  });
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
      --page-bg: #101214;
      --text: #f4f0e8;
      --muted: rgba(244, 240, 232, 0.78);
      --panel: rgba(18, 20, 22, 0.82);
      --border: rgba(255, 255, 255, 0.14);
      --shadow: 0 2rem 6rem rgba(0, 0, 0, 0.36);
      background: var(--page-bg);
      color: var(--text);
    }
    @media (prefers-color-scheme: light) {
      :root {
        --page-bg: #f6f2ea;
        --text: #1f252d;
        --muted: #667085;
        --panel: rgba(255, 250, 242, 0.92);
        --border: rgba(83, 65, 39, 0.18);
        --shadow: 0 2rem 6rem rgba(60, 47, 26, 0.14);
      }
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at 20% 20%, rgba(93, 160, 255, 0.22), transparent 32rem),
        radial-gradient(circle at 85% 75%, rgba(64, 180, 126, 0.18), transparent 28rem),
        var(--page-bg);
    }
    main {
      width: min(38rem, calc(100vw - 2rem));
      padding: 2.4rem;
      border: 1px solid var(--border);
      border-radius: 1.25rem;
      background: var(--panel);
      box-shadow: var(--shadow);
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
      color: var(--muted);
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
  await ensureRuntimePricingSettings(env, deps);
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
  let purchase = await loadPurchaseHistoryByStripeSession(db, sessionId, deps);
  let session = null;
  let metadata = {};
  if (!purchase) {
    const sessionResult = await fetchStripeCheckoutSession(env, sessionId, deps);
    if (sessionResult && sessionResult.ok) {
      session = sessionResult.session;
      metadata = stripeSessionMetadata(session);
      const applyResult = await applyStripeCreditPurchaseFromSession(db, session, deps, env);
      if (applyResult && applyResult.ok) {
        purchase = applyResult.purchase || await loadPurchaseHistoryByStripeSession(db, sessionId, deps);
      } else if (applyResult && applyResult.error) {
        console.warn(
          "stripe.payment_success_apply_deferred",
          JSON.stringify({ session_id: sessionId, error: String(applyResult.error || "apply_failed") }),
        );
      }
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
  const paymentSuccessTitle = amountPaidEur > 0
    ? `Payment of €${amountPaidEur.toFixed(2)} successful`
    : "Payment successful";
  const success = {
    title: paymentSuccessTitle,
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
    const estimate = historyTiles.length
      ? sceneEstimateFromPurchaseTiles(purchase, historyTiles)
      : await estimateNewCredits(db, userId, tileKeys, "full", deps);
    if (estimate && !estimate.error) {
      const preliminaryRows = allocatedRegionPackTileRows(estimate);
      const contextProduct = await sceneSuccessContextProduct(db, tileKeys, preliminaryRows, deps);
      if (contextProduct) {
        const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(contextProduct.id || ""), env, deps);
        const account = await ensureFreshCreditAccountForUser(db, userId, deps);
        const quoteResult = await materializedRegionPackQuoteResult(db, userId, contextProduct, account, deps, {
          env,
          includeMapState: true,
          fastTrack: true,
          jobRound: 0,
          priority: 5,
          triggerType: "scene_success_context_requested",
          staleReason: "scene_success_context_quote_not_ready",
        });
        const mapState = await parseUserProductMapState(quoteResult.quoteRow, env);
        const mapStateStatus = String(quoteResult.quoteRow && quoteResult.quoteRow.map_state_status || (mapState ? "ready" : "not_requested")).trim().toLowerCase() || "not_requested";
        const upsells = await relatedRegionPackQuoteEntries(db, contextProduct, userId, account, null, deps, {
          fastTrack: true,
          priority: 35,
          triggerType: "scene_success_related_requested",
          staleReason: "scene_success_related_quote_not_ready",
        });
        const data = regionPackStaticMapPayload(contextProduct, tokenResult.token, account, [], {
          catalogMode: true,
          quote: quoteResult.quote,
          quoteStatus: quoteResult.quoteStatus,
          pricePending: !quoteResult.quote,
          mapState,
          mapStateStatus,
          mapPending: !mapState || mapStateStatus !== "ready",
          upsells,
          ownedTileKeys: tileKeys,
          titlePrefix: "Data Pack to Consider",
          success: {
            title: paymentSuccessTitle,
            message: "Your Full Quality scene purchase is complete. The map below shows a relevant data pack containing the scene area; the tiles you just licenced are shown as already licenced on this map.",
            context_title_prefix: "Data Pack to Consider",
          },
        });
        return html(regionPackStaticMapHtml(data), 200, env);
      }
    }
  }

  if (purchaseType === "animation_tiles") {
    const historyTiles = purchase && purchase.id ? await loadPurchaseHistoryTiles(db, purchase.id, deps) : [];
    const tileKeys = historyTiles.length
      ? normalizeTileKeys(historyTiles.map((row) => row && row.tile_key || ""))
      : await checkoutTileKeysFromMetadata(db, metadata, deps);
    if (!tileKeys.length) {
      return html(
        checkoutReturnHtml({
          title: "Planetka Payment Complete",
          heading: "Payment successful",
          message: "Your Full Quality animation purchase was completed. Return to Blender; the panel will refresh automatically.",
          icon: "OK",
          tone: "success",
        }),
        200,
        env,
      );
    }
    const estimate = historyTiles.length
      ? sceneEstimateFromPurchaseTiles(purchase, historyTiles)
      : await estimateNewCredits(db, userId, tileKeys, "full", deps);
    if (estimate && !estimate.error) {
      const preliminaryRows = allocatedRegionPackTileRows(estimate);
      const contextProduct = await sceneSuccessContextProduct(db, tileKeys, preliminaryRows, deps);
      if (contextProduct) {
        const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(contextProduct.id || ""), env, deps);
        const account = await ensureFreshCreditAccountForUser(db, userId, deps);
        const quoteResult = await materializedRegionPackQuoteResult(db, userId, contextProduct, account, deps, {
          env,
          includeMapState: true,
          fastTrack: true,
          jobRound: 0,
          priority: 5,
          triggerType: "animation_success_context_requested",
          staleReason: "animation_success_context_quote_not_ready",
        });
        const mapState = await parseUserProductMapState(quoteResult.quoteRow, env);
        const mapStateStatus = String(quoteResult.quoteRow && quoteResult.quoteRow.map_state_status || (mapState ? "ready" : "not_requested")).trim().toLowerCase() || "not_requested";
        const upsells = await relatedRegionPackQuoteEntries(db, contextProduct, userId, account, null, deps, {
          fastTrack: true,
          priority: 35,
          triggerType: "animation_success_related_requested",
          staleReason: "animation_success_related_quote_not_ready",
        });
        const data = regionPackStaticMapPayload(contextProduct, tokenResult.token, account, [], {
          catalogMode: true,
          quote: quoteResult.quote,
          quoteStatus: quoteResult.quoteStatus,
          pricePending: !quoteResult.quote,
          mapState,
          mapStateStatus,
          mapPending: !mapState || mapStateStatus !== "ready",
          upsells,
          ownedTileKeys: tileKeys,
          titlePrefix: "Data Pack to Consider",
          success: {
            title: paymentSuccessTitle,
            message: "Your Full Quality animation purchase is complete. The map below shows a relevant data pack containing the animation area; the tiles you just licenced are shown as already licenced on this map.",
            context_title_prefix: "Data Pack to Consider",
          },
        });
        return html(regionPackStaticMapHtml(data), 200, env);
      }
    }
  }

  if (purchaseType === "region_pack") {
    const regionPackId = String(purchase && purchase.region_pack_id || metadata.planetka_region_id || "").trim();
    const product = regionProductById(regionPackId);
    if (product) {
      const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(product.id || ""), env, deps);
      const repairNow = deps.nowIso();
      const repairedTiles = await reconcileRegionPackEntitlements(
        db,
        userId,
        product,
        "stripe_region_pack_success_repair",
        repairNow,
        deps,
      );
      if (repairedTiles.length > 0) {
        await touchUserPricingVersion(db, userId, deps, repairNow);
        await invalidateAndQueueUserProductQuotes(db, userId, deps, {
          sourceProductId: String(product.id || ""),
          triggerType: "region_pack_success_repair",
          triggerPurchaseId: sessionId,
          staleReason: "region_pack_success_repair_entitlement_changed",
        });
      }
      const account = await ensureFreshCreditAccountForUser(db, userId, deps);
      const quoteResult = await materializedRegionPackQuoteResult(db, userId, product, account, deps, {
        env,
        includeMapState: true,
        fastTrack: true,
        jobRound: 0,
        priority: 0,
        triggerType: "region_pack_success_product_requested",
        staleReason: "region_pack_success_quote_not_ready",
        triggerPurchaseId: sessionId,
      });
      const mapState = await parseUserProductMapState(quoteResult.quoteRow, env);
      const mapStateStatus = String(quoteResult.quoteRow && quoteResult.quoteRow.map_state_status || (mapState ? "ready" : "not_requested")).trim().toLowerCase() || "not_requested";
      const upsells = await relatedRegionPackQuoteEntries(db, product, userId, account, null, deps, {
        fastTrack: true,
        priority: 30,
        triggerType: "region_pack_success_related_requested",
        staleReason: "region_pack_success_related_quote_not_ready",
        triggerPurchaseId: sessionId,
      });
      const data = regionPackStaticMapPayload(product, tokenResult.token, account, [], {
        catalogMode: true,
        quote: quoteResult.quote,
        quoteStatus: quoteResult.quoteStatus,
        pricePending: !quoteResult.quote,
        mapState,
        mapStateStatus,
        mapPending: !mapState || mapStateStatus !== "ready",
        upsells,
        productUnlocked: true,
        success,
      });
      return html(regionPackStaticMapHtml(data), 200, env);
    }
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
  const metadata = parsePurchaseMetadataJson(purchase);
  const amountPaid = normalizeCreditAmount(purchase && purchase.amount_paid_eur);
  const customSceneLicenceEur = normalizeCreditAmount(metadata.custom_scene_licence_eur);
  const scenePayableEur = normalizeCreditAmount(
    metadata.scene_payable_eur
      || amountPaid
      || total + customSceneLicenceEur,
  );
  return {
    ok: true,
    credits: total,
    price_eur: total,
    scene_tile_price_eur: total,
    raw_credits: total,
    raw_price_eur: total,
    custom_scene_licence_eur: customSceneLicenceEur,
    scene_payable_eur: scenePayableEur,
    scene_custom_licence_label: String(metadata.scene_custom_licence_label || SCENE_CUSTOM_LICENCE_LABEL),
    scene_custom_licence_applied: customSceneLicenceEur > 0,
    scene_small_free_threshold_eur: normalizeCreditAmount(metadata.scene_small_free_threshold_eur || SCENE_SMALL_FREE_THRESHOLD_CENTS / 100),
    scene_small_free_threshold_applied: Boolean(metadata.scene_small_free_threshold_applied),
    amount_paid_eur: amountPaid,
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

export async function applyStripeCreditPurchaseFromSession(db, session, deps, env) {
  await ensureRuntimePricingSettings(env, deps);
  const sessionId = String(session && session.id || "").trim();
  if (!sessionId) {
    return { error: "missing_session_id" };
  }
  const existingPurchase = await loadPurchaseHistoryByStripeSession(db, sessionId, deps);
  if (existingPurchase && existingPurchase.id) {
    return { ok: true, applied: false, duplicate_session: true, purchase: existingPurchase };
  }
  const paymentStatus = String(session && session.payment_status || "").trim().toLowerCase();
  if (paymentStatus !== "paid" && paymentStatus !== "no_payment_required") {
    return { error: "stripe_session_not_paid", payment_status: paymentStatus };
  }
  const metadata = stripeSessionMetadata(session);
  const purchaseType = String(metadata.planetka_purchase_type || "").trim().toLowerCase();
  const userId = String(metadata.planetka_user_id || session && session.client_reference_id || "").trim();
  if (!purchaseType || !userId) {
    return { error: "missing_credit_purchase_metadata" };
  }
  const email = String(
    metadata.planetka_email
      || session && session.customer_details && session.customer_details.email
      || session && session.customer_email
      || "",
  ).trim().toLowerCase();
  const amountPaidEur = eurFromStripeAmountCents(session && session.amount_total);
  const stripePaymentIntentId = String(session && (session.payment_intent || session.payment_intent_id) || "").trim();
  let result = null;
  if (purchaseType === "region_pack") {
    const quoteId = String(metadata.planetka_quote_id || "").trim();
    if (!quoteId) {
      return { error: "missing_region_pack_quote_id" };
    }
    const quote = await loadPricingQuote(db, quoteId, deps, { allowExpired: true });
    if (!quote || String(quote.quote_type || "") !== "region_pack") {
      return { error: "region_pack_quote_not_found" };
    }
    const regionPackId = String(metadata.planetka_region_id || "").trim().toLowerCase();
    if (
      String(quote.user_id || "") !== userId
      || String(quote.subject_id || "").trim().toLowerCase() !== regionPackId
      || String(quote.catalog_version || "") !== REGION_PACK_CATALOG_VERSION
    ) {
      return { error: "region_pack_quote_context_mismatch" };
    }
    const amountTotalCents = integerCents(session && session.amount_total);
    const quoteAmountCents = integerCents(quote.amount_cents);
    if (amountTotalCents !== quoteAmountCents) {
      return {
        error: "region_pack_quote_amount_mismatch",
        stripe_amount_cents: amountTotalCents,
        quote_amount_cents: quoteAmountCents,
      };
    }
    result = await grantRegionPackEntitlements(
      db,
      userId,
      String(metadata.planetka_region_id || "").trim(),
      sessionId,
      amountPaidEur,
      deps,
      email,
      stripePaymentIntentId,
      { quote },
    );
  } else if (purchaseType === "animation_tiles") {
    const animationTileKeys = await checkoutTileKeysFromMetadata(db, metadata, deps);
    if (!animationTileKeys.length) {
      return { error: "missing_animation_tile_keys" };
    }
    result = await grantPaidSceneTileEntitlements(
      db,
      userId,
      "full",
      animationTileKeys,
      sessionId,
      amountPaidEur,
      deps,
      email,
      stripePaymentIntentId,
      {
        purchaseType: "animation_tiles",
        ledgerReason: "stripe_animation_purchase",
        entitlementSource: "stripe_animation",
        customLicenceLabel: ANIMATION_CUSTOM_LICENCE_LABEL,
        customLicenceCents: checkoutMetadataCents(metadata, "planetka_custom_animation_licence_eur", 0),
        metadata: {
          segment_count: Math.max(0, Number.parseInt(metadata.planetka_segment_count || 0, 10) || 0),
          custom_animation_licence_eur: normalizeCreditAmount(metadata.planetka_custom_animation_licence_eur),
          custom_animation_licence_label: ANIMATION_CUSTOM_LICENCE_LABEL,
          custom_animation_licence_segments: Math.max(0, Number.parseInt(metadata.planetka_custom_animation_licence_segments || 0, 10) || 0),
          custom_animation_licence_fee_eur: normalizeCreditAmount(metadata.planetka_custom_animation_licence_fee_eur || customAnimationLicencePerResolveCents() / 100),
          custom_animation_licence_per_resolve_eur: normalizeCreditAmount(metadata.planetka_custom_animation_licence_per_resolve_eur || metadata.planetka_custom_animation_licence_fee_eur || customAnimationLicencePerResolveCents() / 100),
          custom_animation_licence_max_fee_eur: normalizeCreditAmount(metadata.planetka_custom_animation_licence_max_fee_eur || customAnimationLicenceMaxCents() / 100),
          custom_animation_licence_threshold_eur: normalizeCreditAmount(metadata.planetka_custom_animation_licence_threshold_eur || SCENE_SMALL_FREE_THRESHOLD_CENTS / 100),
          animation_tile_price_eur: normalizeCreditAmount(metadata.planetka_animation_tile_price_eur || metadata.planetka_scene_tile_price_eur),
          tile_set_token: String(metadata.planetka_tile_set_token || "").trim(),
        },
      },
    );
  } else if (purchaseType === "scene_tiles") {
    result = await grantPaidSceneTileEntitlements(
      db,
      userId,
      deps.normalizeQualityMode(metadata.planetka_quality_mode || "full"),
      parseStripeMetadataTileKeys(metadata.planetka_tile_keys_json),
      sessionId,
      amountPaidEur,
      deps,
      email,
      stripePaymentIntentId,
      {
        customLicenceCents: checkoutMetadataCents(metadata, "planetka_custom_scene_licence_eur", customSceneLicenceCents()),
        metadata: {
          checkout_scene_tile_price_eur: normalizeCreditAmount(metadata.planetka_scene_tile_price_eur),
          checkout_scene_payable_eur: normalizeCreditAmount(metadata.planetka_scene_payable_eur || metadata.planetka_price_eur),
          checkout_custom_scene_licence_eur: normalizeCreditAmount(metadata.planetka_custom_scene_licence_eur),
        },
      },
    );
  } else {
    return { error: "unsupported_credit_purchase_type", purchase_type: purchaseType };
  }
  if (result && result.error) {
    return result;
  }
  if (typeof deps.invalidateAnalyticsSnapshots === "function") {
    try {
      await deps.invalidateAnalyticsSnapshots(env);
    } catch (error) {
      console.warn(
        "stripe.success_page_snapshot_invalidate_failed",
        JSON.stringify({ error: String(error && error.message || "snapshot_invalidate_failed"), user_id: userId }),
      );
    }
  }
  return {
    ok: true,
    applied: true,
    purchase_type: purchaseType,
    result,
    purchase: await loadPurchaseHistoryByStripeSession(db, sessionId, deps),
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
    const metadata = parsePurchaseMetadataJson(row);
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

function accountPageFmtEur(value) {
  return `€${normalizeCreditAmount(value).toFixed(2)}`;
}

function accountPageFmtInt(value) {
  return Math.max(0, Number.parseInt(value || 0, 10) || 0).toLocaleString("en-US");
}

function accountPagePurchaseLabel(row) {
  const type = String(row && row.purchase_type || "").trim().toLowerCase();
  const packName = String(row && (row.region_pack_name || row.region_pack_id) || "").trim();
  if (type === "region_pack") {
    return packName ? `Data Pack: ${packName}` : "Data Pack";
  }
  if (type === "animation_tiles") {
    return "Animation Full Quality";
  }
  if (type === "scene_tiles") {
    return "Scene Full Quality";
  }
  if (type === "world") {
    return "World Full Quality";
  }
  return type ? type.replace(/_/g, " ") : "Purchase";
}

function accountPagePurchaseRowsHtml(purchases) {
  const rows = Array.isArray(purchases) ? purchases : [];
  if (!rows.length) {
    return `<tr><td colspan="6" class="muted">No purchase history recorded yet.</td></tr>`;
  }
  return rows.map((row) => {
    const tiles = Array.isArray(row && row.tiles) ? row.tiles : [];
    const tileDetails = tiles.length
      ? `<details><summary>${accountPageFmtInt(tiles.length)} tile${tiles.length === 1 ? "" : "s"}</summary><div class="tile-list">${tiles.map((tile) => {
        const key = escapeHtmlText(tile && tile.tile_key || "");
        const status = escapeHtmlText(tile && tile.tile_status || "");
        const price = escapeHtmlText(accountPageFmtEur(tile && tile.price_eur));
        const gross = escapeHtmlText(accountPageFmtEur(tile && tile.gross_price_eur));
        return `<div><code>${key}</code> <span>${status}</span> <span>${price}</span> <span class="muted">full ${gross}</span></div>`;
      }).join("")}</div></details>`
      : "";
    const discount = normalizeCreditAmount(row && row.discount_eur) > 0
      ? `<div class="muted">Volume discount ${Math.max(0, Number.parseInt(row && row.discount_percent || 0, 10) || 0)}% (-${escapeHtmlText(accountPageFmtEur(row && row.discount_eur))})</div>`
      : "";
    return `<tr>
      <td>${escapeHtmlText(row && row.created_at || "")}</td>
      <td>${escapeHtmlText(accountPagePurchaseLabel(row))}</td>
      <td>${escapeHtmlText(accountPageFmtEur(row && row.amount_paid_eur))}</td>
      <td>${escapeHtmlText(accountPageFmtEur(row && row.gross_eur))}${discount}</td>
      <td>${accountPageFmtInt(row && row.tile_count_new)} / ${accountPageFmtInt(row && row.tile_count_total)}</td>
      <td>${tileDetails}</td>
    </tr>`;
  }).join("");
}

function accountPageMapPayload({ worldUnlocked, tileRows, totalTileCount, visibleTileLimit }) {
  const rows = Array.isArray(tileRows) ? tileRows : [];
  const levels = new Set(REGION_PACK_PAID_Z_LEVELS);
  const tiles = [];
  const seen = new Set();
  const ownedLevels = new Set();
  for (const row of rows) {
    const parsed = parseTileKey(row && row.tile_key || "");
    if (!parsed) {
      continue;
    }
    const key = `${parsed.key}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    levels.add(parsed.z);
    ownedLevels.add(parsed.z);
    tiles.push({
      key: parsed.key,
      x: parsed.x,
      y: parsed.y,
      z: parsed.z,
      d: parsed.d,
    });
  }
  const sortedLevels = Array.from(levels)
    .filter((value) => Number.isFinite(Number(value)) && Number(value) > 0)
    .sort((a, b) => a - b);
  const sortedOwnedLevels = Array.from(ownedLevels)
    .filter((value) => Number.isFinite(Number(value)) && Number(value) > 0)
    .sort((a, b) => a - b);
  return {
    map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
    country_borders_revision: ACCOUNT_COUNTRY_BORDERS_ASSET_REVISION,
    world_unlocked: Boolean(worldUnlocked),
    levels: sortedLevels,
    default_level: worldUnlocked
      ? (sortedLevels[0] || 1)
      : (sortedOwnedLevels[0] || sortedLevels[0] || 1),
    tiles,
    total_tile_count: Math.max(0, Number(totalTileCount || 0) || 0),
    visible_tile_limit: Math.max(0, Number(visibleTileLimit || 0) || 0),
    truncated: !worldUnlocked && Math.max(0, Number(totalTileCount || 0) || 0) > Math.max(0, Number(visibleTileLimit || 0) || 0),
  };
}

function accountPageJsonScript(value) {
  return JSON.stringify(value || {})
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
}

function accountPageCoverageMapHtml({ worldUnlocked, tileRows, totalTileCount, visibleTileLimit }) {
  const safeRevision = escapeHtmlText(encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION));
  const mapPayload = accountPageMapPayload({ worldUnlocked, tileRows, totalTileCount, visibleTileLimit });
  const note = worldUnlocked
    ? "Full Quality coverage is currently available across all zoom levels for this account."
    : "";
  return `<section class="panel">
    <h2>Licenced Tile Coverage</h2>
    ${note ? `<p class="muted">${escapeHtmlText(note)}</p>` : ""}
    <div class="toolbar">
      <label>Zoom level <select id="accountLevelSelect"></select></label>
      <span id="accountMapSummary" class="muted small"></span>
    </div>
    <svg id="accountCoverageMap" class="coverage-map" viewBox="0 0 360 180" role="img" aria-label="Planetka licenced tile coverage map" preserveAspectRatio="xMidYMid meet">
      <image href="/credits/region-pack-map-background.jpg?v=${safeRevision}" x="0" y="0" width="360" height="180" preserveAspectRatio="none"></image>
    </svg>
    <div class="legend"><span><i class="swatch licenced"></i>Licenced</span></div>
    <script>window.PLANETKA_ACCOUNT_MAP_DATA=${accountPageJsonScript(mapPayload)};</script>
    <script>${ACCOUNT_PAGE_MAP_JS}</script>
  </section>`;
}

export async function handleCreditAccountPage(request, env, deps) {
  const db = deps.requireDb(env);
  const url = new URL(request.url);
  const tokenResult = await getValidAccountPageToken(db, url.searchParams.get("token"), deps);
  if (!tokenResult || tokenResult.error) {
    return html(
      `<!doctype html><title>Planetka Account</title><body><h1>Account link expired</h1><p>Please reopen this page from Blender.</p></body>`,
      tokenResult && tokenResult.status || 410,
      env,
    );
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const user = await deps.dbGet(db, `SELECT id, email FROM users WHERE id = ? LIMIT 1`, [userId]);
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  const email = deps.normalizeEmail(user && user.email || account && account.user_email || "");
  const worldUnlocked = isWorldFullQualityUnlocked(account);
  const visibleTileLimit = worldUnlocked ? 0 : 200000;
  const [tileSummary, tileRows, purchases] = await Promise.all([
    deps.dbGet(
      db,
      `
        SELECT
          COUNT(*) AS tile_count
        FROM user_tile_entitlements
        WHERE user_id = ?
      `,
      [userId],
    ),
    worldUnlocked
      ? Promise.resolve([])
      : deps.dbAll(
        db,
        `
          SELECT tile_key
          FROM user_tile_entitlements
          WHERE user_id = ?
          ORDER BY tile_key ASC
          LIMIT ?
        `,
        [userId, visibleTileLimit],
      ),
    loadPurchaseHistoryForUser(db, userId, deps, { limit: 200 }),
  ]);
  const actualTileCount = Math.max(0, Number(tileSummary && tileSummary.tile_count || 0));
  const htmlContent = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Planetka Account</title>
  <style>${ACCOUNT_PAGE_CSS}</style>
</head>
<body>
<main>
  <h1>Planetka Account</h1>
  <p class="muted">${escapeHtmlText(email || "Connected account")}</p>
  ${accountPageCoverageMapHtml({ worldUnlocked, tileRows, totalTileCount: actualTileCount, visibleTileLimit })}
  <section class="panel">
    <h2>Purchase History</h2>
    <table>
      <thead><tr><th>Time</th><th>Purchase</th><th>Paid</th><th>Full Price</th><th>New / Total Tiles</th><th>Tile Details</th></tr></thead>
      <tbody>${accountPagePurchaseRowsHtml(purchases)}</tbody>
    </table>
  </section>
</main>
</body>
</html>`;
  return html(htmlContent, 200, env);
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
  const account = await ensureFreshCreditAccountForUser(db, auth.user.id, deps);
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
