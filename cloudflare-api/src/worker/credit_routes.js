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
const DATASET_BASE_MPP = 10.0;
const EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2;
// Runtime pricing policy. Generated catalogs keep coefficient-1.0 gross prices;
// these settings are applied at request time so price policy changes do not
// require rebuilding static region products.
const DEFAULT_FULL_QUALITY_PRICE_COEFFICIENT = 5.00;
const DEFAULT_REGION_PACK_DISCOUNT_MIN_PERCENT = 0;
const DEFAULT_REGION_PACK_DISCOUNT_MAX_PERCENT = 75;
const PRICING_SETTINGS_CACHE_TTL_MS = 30 * 1000;
const PRICING_SETTINGS_KEYS = {
  coefficient: "full_quality_price_coefficient",
  minDiscount: "region_pack_discount_min_percent",
  maxDiscount: "region_pack_discount_max_percent",
  productDiscountPrefix: "region_pack_discount_override:",
};
const REGION_PACK_DISCOUNT_SHARE_BUCKETS = [
  [0.75, 1.0],
  [0.25, 5.0 / 6.0],
  [0.125, 4.0 / 6.0],
  [0.10, 3.0 / 6.0],
  [0.07, 2.0 / 6.0],
  [0.05, 1.0 / 6.0],
  [0.0, 0.0],
];
const STRIPE_MIN_CHECKOUT_AMOUNT_CENTS = 50;
const MONEY_SCALE = 100;
const METRIC_SCALE = 1_000_000;
const REGION_PACK_CATALOG_VERSION = GENERATED_REGION_PACK_CATALOG_VERSION || "gadm_regions_v8";
const REGION_PACK_MAP_ASSET_REVISION = `${REGION_PACK_CATALOG_VERSION}:outline-v4-product-bg-wt-blue-v4-partial-dateline-v7-admin-labels-v1-success-upsell-v1-catalog-flat-v1-price-breakdown-v1-hover-breakdown-v1-summary-partial-v1-pricing-runtime-v3-product-overrides-v1`;
const SQL_VARIABLE_SAFE_CHUNK_SIZE = 75;
const REGION_PACK_TILE_CHUNK_SIZE = SQL_VARIABLE_SAFE_CHUNK_SIZE;
const REGION_PACK_PAID_Z_LEVELS = [1, 2, 4, 8, 15, 30];
const REGION_PACK_MAP_MAX_OUTLINE_POINTS = 250_000;
const REGION_OFFER_MAX_TILE_COUNTRY_DISTANCE_DEG = 4.0;
const REGION_SIMILAR_COUNTRY_MAX_DISTANCE_DEG = 2.0;
const REGION_PRODUCTS = Array.isArray(GENERATED_REGION_PACK_PRODUCTS) ? GENERATED_REGION_PACK_PRODUCTS : [];
const REGION_PRODUCT_BY_ID = new Map(REGION_PRODUCTS.map((product) => [
  String(product && product.id || "").trim().toLowerCase(),
  product,
]).filter(([id]) => Boolean(id)));
const REGION_PRODUCT_TILE_KEYS_CACHE = new Map();
const REGION_PRODUCT_SORTED_TILE_KEYS_CACHE = new Map();
const REGION_PRODUCT_DIRECT_TILE_SET_CACHE = new Map();
const REGION_PRODUCT_Z001_CELL_SET_CACHE = new Map();
const REGION_PRODUCT_COUNTRY_ID_SET_CACHE = new Map();
const REGION_PRODUCT_GROSS_CENTS_CACHE = new Map();
const REGION_PRODUCT_STATIC_MODEL_CACHE = new Map();
const USER_CREDIT_ACCOUNT_CACHE = new Map();
const USER_ENTITLEMENT_SUMMARY_CACHE = new Map();
const REGION_OFFERS_RESPONSE_CACHE = new Map();
const DETAIL_TOKEN_CACHE = new Map();
let PRICING_SETTINGS_CACHE = {
  loaded_at_ms: 0,
  settings: null,
};
const COUNTRY_LIKE_REGION_PRODUCT_IDS = new Set(["australia", "canada", "china", "united_states"]);
const NORTH_AMERICA_SIMILAR_COUNTRY_LIKE_IDS = new Set(["canada", "united_states"]);
const USER_CREDIT_ACCOUNT_CACHE_MAX = 2048;
const USER_ENTITLEMENT_SUMMARY_CACHE_MAX = 512;
const REGION_OFFERS_RESPONSE_CACHE_MAX = 1024;
const DETAIL_TOKEN_CACHE_MAX = 4096;
const USER_CREDIT_ACCOUNT_CACHE_TTL_MS = 30 * 1000;
const USER_ENTITLEMENT_SUMMARY_CACHE_TTL_MS = 2 * 60 * 1000;
const REGION_OFFERS_RESPONSE_CACHE_TTL_MS = 20 * 1000;
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
}

function accountEntitlementVersion(account) {
  return [
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
  return {
    id: String(product.id || ""),
    name: String(product.name || ""),
    type: String(product.type || ""),
    discount_percent: regionProductDiscountPercent(product),
    catalog_version: REGION_PACK_CATALOG_VERSION,
    included_countries: regionProductIncludedCountries(product),
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
    // The generated catalog stores static coefficient-1.0 totals. Runtime
    // requests only apply the current global multiplier and user-specific
    // licence deductions; they must not recompute the pack's basic price.
    grossCents = applyFullQualityPriceCoefficientCents(product.gross_cents || centsForEur(product.gross_eur || 0));
    REGION_PRODUCT_GROSS_CENTS_CACHE.set(cacheKey, grossCents);
  }
  const grossEur = grossCents > 0
    ? normalizeCreditAmount(grossCents / 100.0)
    : applyFullQualityPriceCoefficientEur(product.gross_eur || 0);
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
  const discount = normalizeCreditAmount(gross * (Math.max(0, Math.min(100, Number.parseInt(discountPercent || 0, 10) || 0)) / 100.0));
  const price = normalizeCreditAmount(Math.max(0, gross - discount));
  return { gross, discount, price };
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
  return {
    full_quality_price_coefficient: coefficient,
    region_pack_discount_min_percent: Math.min(minDiscount, maxDiscount),
    region_pack_discount_max_percent: Math.max(minDiscount, maxDiscount),
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
  const productDiscountOverrides = normalizeProductDiscountOverrides(raw && raw.product_discount_overrides);
  return {
    full_quality_price_coefficient: coefficient,
    region_pack_discount_min_percent: Math.min(minDiscount, maxDiscount),
    region_pack_discount_max_percent: Math.max(minDiscount, maxDiscount),
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
    Number(settings.full_quality_price_coefficient || 1).toFixed(6),
    Number(settings.region_pack_discount_min_percent || 0),
    Number(settings.region_pack_discount_max_percent || 0),
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
  REGION_PRODUCT_STATIC_MODEL_CACHE.clear();
  REGION_OFFERS_RESPONSE_CACHE.clear();
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
      `SELECT key, value FROM app_settings WHERE key IN (?, ?, ?) OR key LIKE ?`,
      [
        PRICING_SETTINGS_KEYS.coefficient,
        PRICING_SETTINGS_KEYS.minDiscount,
        PRICING_SETTINGS_KEYS.maxDiscount,
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
    PRICING_SETTINGS_CACHE = { loaded_at_ms: now, settings: defaults };
    return defaults;
  }
}

export async function setRuntimePricingSettings(db, values = {}, adminUserId = "", deps = {}) {
  if (!db || !deps || typeof deps.dbRun !== "function") {
    throw new Error("pricing_settings_db_unavailable");
  }
  const currentSettings = activePricingSettings();
  const settings = normalizeRuntimePricingSettings(
    {
      ...values,
      product_discount_overrides: currentSettings.product_discount_overrides || {},
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
  const productId = String(product.id || "").trim().toLowerCase();
  if (productId === "world") {
    return roundDiscountPercentToNearestFive(maxPercent);
  }
  const share = regionProductLandShare(product);
  const bucket = REGION_PACK_DISCOUNT_SHARE_BUCKETS.find(([threshold]) => share >= threshold);
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

function regionProductPricingAdminRow(product, settings = activePricingSettings()) {
  const summary = regionProductPricingSummary(product) || {};
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
  const rows = REGION_PRODUCTS
    .filter((product) => product && !isHiddenRegionProduct(product))
    .map((product) => regionProductPricingAdminRow(product, settings))
    .sort((left, right) => (
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

function fullQualityPriceCoefficient() {
  const coefficient = Number.parseFloat(activePricingSettings().full_quality_price_coefficient);
  return Number.isFinite(coefficient) && coefficient > 0 ? coefficient : 1.0;
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

function generatedTileBaseGrossCents(tileKey) {
  const key = normalizeTileKey(tileKey);
  if (!key) {
    return 0;
  }
  return Math.max(0, Number.parseInt(GENERATED_REGION_PACK_TILE_GROSS_CENTS && GENERATED_REGION_PACK_TILE_GROSS_CENTS[key] || 0, 10) || 0);
}

function generatedTileGrossCents(tileKey) {
  return applyFullQualityPriceCoefficientCents(generatedTileBaseGrossCents(tileKey));
}

function generatedTileGrossEur(tileKey) {
  return normalizeCreditAmount(generatedTileGrossCents(tileKey) / 100.0);
}

function regionProductDirectTileSet(productId, cache = {}) {
  const safeId = String(productId || "").trim();
  if (!safeId) {
    return new Set();
  }
  if (REGION_PRODUCT_DIRECT_TILE_SET_CACHE.has(safeId)) {
    return REGION_PRODUCT_DIRECT_TILE_SET_CACHE.get(safeId);
  }
  if (!cache.directTileSets) {
    cache.directTileSets = new Map();
  }
  if (cache.directTileSets.has(safeId)) {
    return cache.directTileSets.get(safeId);
  }
  const set = new Set(normalizeTileKeys(GENERATED_REGION_PACK_TILE_KEYS[safeId] || []));
  cache.directTileSets.set(safeId, set);
  REGION_PRODUCT_DIRECT_TILE_SET_CACHE.set(safeId, set);
  return set;
}

function regionProductZ001CellSet(product, cache = {}) {
  const productId = String(product && product.id || product || "").trim();
  if (!productId) {
    return new Set();
  }
  if (REGION_PRODUCT_Z001_CELL_SET_CACHE.has(productId)) {
    return REGION_PRODUCT_Z001_CELL_SET_CACHE.get(productId);
  }
  if (!cache.z001CellSets) {
    cache.z001CellSets = new Map();
  }
  if (cache.z001CellSets.has(productId)) {
    return cache.z001CellSets.get(productId);
  }
  const cells = new Set();
  for (const key of regionProductDirectTileSet(productId, cache)) {
    const parsed = parseTileKey(key);
    if (parsed && parsed.z === 1 && parsed.d === 1) {
      cells.add(`${parsed.x},${parsed.y}`);
    }
  }
  cache.z001CellSets.set(productId, cells);
  REGION_PRODUCT_Z001_CELL_SET_CACHE.set(productId, cells);
  return cells;
}

function regionProductsShareZ001Footprint(productA, productB, cache = {}) {
  const cellsA = regionProductZ001CellSet(productA, cache);
  const cellsB = regionProductZ001CellSet(productB, cache);
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

function cloneOwnedRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map((row) => ({ tile_key: normalizeTileKey(row && row.tile_key || "") }))
    .filter((row) => row.tile_key);
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
  const account = options && options.account ? options.account : await ensureCreditAccount(db, safeUserId, deps);
  const version = accountEntitlementVersion(account);
  const cacheKey = `${safeUserId}|${version}`;
  const nowMs = monotonicNowMs();
  const cached = USER_ENTITLEMENT_SUMMARY_CACHE.get(cacheKey);
  if (
    cached
    && (nowMs - Number(cached.cached_at_ms || 0)) <= USER_ENTITLEMENT_SUMMARY_CACHE_TTL_MS
  ) {
    return {
      rows: cloneOwnedRows(cached.rows),
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
        rows: storedRows,
        ownedByFamily,
        cached_at_ms: nowMs,
      },
      USER_ENTITLEMENT_SUMMARY_CACHE_MAX,
    );
    return {
      rows: cloneOwnedRows(storedRows),
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
      rows: safeRows,
      ownedByFamily,
      cached_at_ms: nowMs,
    },
    USER_ENTITLEMENT_SUMMARY_CACHE_MAX,
  );
  return {
    rows: cloneOwnedRows(safeRows),
    ownedByFamily,
    cache_hit: false,
    version,
  };
}

async function ownedTileRowsForUser(db, userId, deps, options = {}) {
  const summary = await ownedEntitlementSummaryForUser(db, userId, deps, options);
  return cloneOwnedRows(summary.rows);
}

async function freshCreditAccountForUser(db, userId, deps) {
  await deps.ensureCreditTables(db);
  const safeUserId = String(userId || "").trim();
  if (!safeUserId) {
    return null;
  }
  return await deps.dbGet(
    db,
    `SELECT * FROM user_credit_accounts WHERE user_id = ? LIMIT 1`,
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

function regionPackCatalogAssetKey(env) {
  const prefix = cleanR2Prefix(env);
  const relative = `region_pack_maps/${REGION_PACK_CATALOG_VERSION}/catalog.json`;
  return prefix ? `${prefix}/${relative}` : relative;
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


const REGION_PACK_PAGE_ASSETS = new Map([
  ["region-pack-dynamic-map.css", { content_type: "text/css; charset=utf-8", body: ":root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--new:#e45745;--partial:#e2bc49;--licenced:#4fa86a;--free:#69707a;--country:#2a3748;--country-line:#98b4d8}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}\nmain{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}.muted{color:var(--muted)}\n.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:22px;margin-top:4px}.card.final-price{border-color:#8f732f;box-shadow:0 0 0 1px rgba(217,164,65,.16) inset}.card.final-price b{font-size:26px}.buy-now{width:100%;font-size:16px}\n.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}\nselect{background:#262626;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px}svg{width:100%;height:auto;background:#0d1118;border:1px solid var(--line);border-radius:10px}\n.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0}.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}.new{background:var(--new)}.partial{background:var(--partial)}.licenced{background:var(--licenced)}.free{background:var(--free)}\n.countries{columns:2;column-gap:26px}.countries div{break-inside:avoid;margin:2px 0}.small{font-size:13px}\n.upsells{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.upsell{background:#151515;border:1px solid var(--line);border-radius:12px;padding:12px}.upsell h3{margin:0 0 8px;font-size:18px}.upsell p{margin:6px 0}.upsell svg{min-height:0}.button{display:inline-flex;align-items:center;justify-content:center;margin-top:10px;padding:9px 12px;border-radius:8px;background:#d9a441;color:#111;text-decoration:none;font-weight:700}.button.secondary{margin-left:8px;background:#2a2a2a;color:var(--text);border:1px solid var(--line)}" }],
  ["region-pack-dynamic-map.js", { content_type: "application/javascript; charset=utf-8", body: "const DATA=window.PLANETKA_REGION_PACK_DATA||{};\nconst NS=\"http://www.w3.org/2000/svg\";\nconst fmt=(v)=>\"€\"+Number(v||0).toFixed(2);\nconst cents=(v)=>Math.max(0,Math.round(Number(v||0)*100)||0);\nfunction priceBreakdownText(tile,discountPct){const full=cents(tile.full_price_eur);const final=cents(tile.price_eur);const status=String(tile.status||\"\");const already=status===\"licenced\"?full:0;const partial=status===\"partial\"?Math.min(Math.max(0,full-already),cents(tile.upgrade_credit_eur)):0;const preDiscount=Math.max(0,full-already-partial);const discount=Math.max(0,preDiscount-final);const pct=Math.max(0,Number(discountPct||0)||0);const lines=[\"Full Price: \"+fmt(full/100)];if(already>0)lines.push(\"Licenced: - \"+fmt(already/100));if(partial>0)lines.push(\"Partially licenced: - \"+fmt(partial/100));if(discount>0)lines.push(\"Volume Discount (\"+pct+\"%): - \"+fmt(discount/100));lines.push(\"Final Price: \"+fmt(final/100));return lines.join(\"\\n\")}\nconst MAP_BG=\"/credits/region-pack-map-background.jpg?v=\"+encodeURIComponent(String(DATA.catalog_version||DATA.token||Date.now()));\nfunction mapBgHref(id){const safe=encodeURIComponent(String(id||\"\").trim());return safe?\"/credits/region-pack-map-background.jpg?region_pack_id=\"+safe+\"&v=\"+encodeURIComponent(String(DATA.catalog_version||DATA.token||Date.now())):MAP_BG}\nconst bounds=DATA.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};\nfunction frameForBounds(rawBounds,width,minHeight,maxHeight,padSize){const b=rawBounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const minLon=Number.isFinite(Number(b.min_lon))?Number(b.min_lon):-10,minLat=Number.isFinite(Number(b.min_lat))?Number(b.min_lat):35,maxLon=Number.isFinite(Number(b.max_lon))?Number(b.max_lon):30,maxLat=Number.isFinite(Number(b.max_lat))?Number(b.max_lat):48;const lonSpan=Math.max(1e-6,maxLon-minLon),latSpan=Math.max(1e-6,maxLat-minLat),innerW=Math.max(1,width-padSize*2);const naturalH=Math.round(latSpan*(innerW/lonSpan))+padSize*2,height=Math.max(minHeight,Math.min(maxHeight,naturalH)),innerH=Math.max(1,height-padSize*2),scale=Math.min(innerW/lonSpan,innerH/latSpan),usedW=lonSpan*scale,usedH=latSpan*scale;return{bounds:{min_lon:minLon,min_lat:minLat,max_lon:maxLon,max_lat:maxLat},width,height,scale,ox:(width-usedW)/2,oy:(height-usedH)/2}}\nconst W=1000, mainFrame=frameForBounds(bounds,W,320,820,20), H=mainFrame.height;\nfunction xy(lon,lat){return [mainFrame.ox+(lon-mainFrame.bounds.min_lon)*mainFrame.scale,mainFrame.oy+(mainFrame.bounds.max_lat-lat)*mainFrame.scale]}\nfunction el(name,attrs){const node=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs||{})){node.setAttribute(k,String(v))}return node}\nfunction addMapBackground(svg,project,width,height,id,bounds){svg.appendChild(el(\"rect\",{x:0,y:0,width,height,fill:\"#0d1118\"}));const safeId=String(id||\"\").trim();if(safeId&&safeId!==\"scene\"){svg.appendChild(el(\"image\",{href:mapBgHref(safeId),x:0,y:0,width,height,preserveAspectRatio:\"none\",opacity:\"1.0\"}))}else{const tl=project(-180,90),br=project(180,-90);svg.appendChild(el(\"image\",{href:MAP_BG,x:tl[0],y:tl[1],width:br[0]-tl[0],height:br[1]-tl[1],preserveAspectRatio:\"none\",opacity:\"1.0\"}))}svg.appendChild(el(\"rect\",{x:0,y:0,width,height,fill:\"#05070a\",opacity:\"0.0\"}))}\nfunction pathFor(poly){return poly.map((pt,i)=>{const p=xy(pt[0],pt[1]);return (i?\"L\":\"M\")+p[0].toFixed(2)+\" \"+p[1].toFixed(2)}).join(\" \")}\nfunction render(level){const svg=document.getElementById(\"map\");svg.replaceChildren();svg.setAttribute(\"viewBox\",\"0 0 \"+W+\" \"+H);\n  svg.setAttribute(\"preserveAspectRatio\",\"xMidYMid meet\");\n  addMapBackground(svg,xy,W,H,DATA.region_pack&&DATA.region_pack.id,bounds);\n  for(const outline of DATA.outlines||[]){for(const poly of outline.polygons||[]){const p=el(\"path\",{d:pathFor(poly),fill:\"none\",stroke:\"var(--country-line)\",\"stroke-width\":\"0.7\",opacity:\"0.72\"});const t=el(\"title\",{});t.textContent=outline.name; p.appendChild(t); svg.appendChild(p);}}\n  const rows=(DATA.tiles||[]).filter(t=>Number(t.z)===Number(level)); let chargedCount=0, licencedCount=0, partialCount=0, freeCount=0, price=0;\n  for(const tile of rows){const a=xy(tile.lon_min,tile.lat_max), b=xy(tile.lon_max,tile.lat_min); const cls=tile.status===\"new\"?\"var(--new)\":(tile.status===\"partial\"?\"var(--partial)\":(tile.status===\"licenced\"?\"var(--licenced)\":\"var(--free)\"));\n    if(tile.status===\"new\"||tile.status===\"partial\"){chargedCount++; price+=Number(tile.price_eur||0); if(tile.status===\"partial\") partialCount++} else if(tile.status===\"licenced\"){licencedCount++} else {freeCount++}\n    const r=el(\"rect\",{x:a[0],y:a[1],width:Math.max(1,b[0]-a[0]),height:Math.max(1,b[1]-a[1]),fill:cls,stroke:\"#fff\",\"stroke-width\":\"0.45\",opacity:(tile.status===\"new\"||tile.status===\"partial\")?\"0.58\":\"0.43\"});\n    const title=el(\"title\",{}); const statusText=tile.status===\"partial\"?\"partially licenced (upgrade price only)\":tile.status; let hover=tile.tile_key+\"\\nLand: \"+Number(tile.billable_land_km2||0).toFixed(2)+\" km²\"+\"\\nStatus: \"+statusText+\"\\n\"+priceBreakdownText(tile,DATA.summary&&DATA.summary.discount_percent||0); title.textContent=hover; r.appendChild(title); svg.appendChild(r);}\n  const licenceBenefitCount=licencedCount+partialCount;\n  const newCount=Math.max(0,rows.length-licenceBenefitCount);\n  document.getElementById(\"levelSummary\").textContent=rows.length+\" tiles at \"+zoomLabel(level)+\" · new \"+newCount+\" · charged \"+chargedCount+\" · already licenced \"+licenceBenefitCount+\" · free \"+freeCount+\" · current zoom price \"+fmt(price);\n}\nconst levels=(DATA.levels&&DATA.levels.length?DATA.levels:[1]); function zoomLabel(level){const i=Math.max(0,levels.indexOf(Number(level)));return \"Zoom \"+(i+1)+(i===0?\" - closest\":\"\")} const select=document.getElementById(\"levelSelect\");\nfor(const z of levels){const o=document.createElement(\"option\");o.value=String(z);o.textContent=zoomLabel(z);select.appendChild(o)}\nselect.addEventListener(\"change\",()=>render(Number(select.value))); render(Number(select.value||levels[0]));\nfunction miniFrame(bounds){return frameForBounds(bounds,1000,320,820,20)}\nfunction miniXY(frame,lon,lat){return [frame.ox+(lon-frame.bounds.min_lon)*frame.scale,frame.oy+(frame.bounds.max_lat-lat)*frame.scale]}\nfunction renderMiniMap(svg,card){const b=card.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const frame=miniFrame(b),w=frame.width,h=frame.height;svg.setAttribute(\"viewBox\",\"0 0 \"+w+\" \"+h);svg.style.aspectRatio=w+\" / \"+h;svg.setAttribute(\"preserveAspectRatio\",\"xMidYMid meet\");svg.replaceChildren();const bgId=card&&card.region_pack&&card.region_pack.id||\"\";addMapBackground(svg,(lon,lat)=>miniXY(frame,lon,lat),w,h,bgId,b);for(const tile of card.tiles||[]){const a=miniXY(frame,tile.lon_min,tile.lat_max),c=miniXY(frame,tile.lon_max,tile.lat_min);const cls=tile.status===\"new\"?\"var(--new)\":(tile.status===\"partial\"?\"var(--partial)\":(tile.status===\"licenced\"?\"var(--licenced)\":\"var(--free)\"));const r=el(\"rect\",{x:a[0],y:a[1],width:Math.max(1,c[0]-a[0]),height:Math.max(1,c[1]-a[1]),fill:cls,stroke:\"#fff\",\"stroke-width\":\"0.5\",opacity:(tile.status===\"new\"||tile.status===\"partial\")?\"0.58\":\"0.43\"});svg.appendChild(r)}}\nfunction renderUpsells(){const grid=document.getElementById(\"upsellGrid\");if(!grid)return;const token=encodeURIComponent(DATA.token||\"\");const catalog=\"&catalog=1\";for(const card of DATA.upsells||[]){const pack=card.region_pack||{},s=card.summary||{};const id=encodeURIComponent(pack.id||\"\");const div=document.createElement(\"div\");div.className=\"upsell\";const title=document.createElement(\"h3\");title.textContent=pack.name||\"Region Pack\";div.appendChild(title);const map=document.createElementNS(NS,\"svg\");div.appendChild(map);renderMiniMap(map,card);const meta=document.createElement(\"p\");meta.className=\"muted small\";const alreadyValue=Number(s.already_licenced_deduction_eur||s.already_licenced_saving_eur||0)+Number(s.partial_licence_credit_eur||0);const bits=[\"Full \"+fmt(s.full_price_eur)];if(alreadyValue>0)bits.push(\"Already -\"+fmt(alreadyValue));if(Number(s.discount_eur||0)>0)bits.push(\"Discount \"+Number(s.discount_percent||0)+\"% (-\"+fmt(s.discount_eur)+\")\");bits.push(\"Final \"+fmt(s.price_eur));meta.textContent=bits.join(\" · \" );div.appendChild(meta);const checkout=document.createElement(\"a\");checkout.className=\"button\";checkout.href=\"/credits/region-pack-checkout?token=\"+token+\"&region_pack_id=\"+id+catalog;checkout.textContent=\"Buy \"+(pack.name||\"Pack\")+\" (\"+fmt(s.price_eur)+\")\";div.appendChild(checkout);const detail=document.createElement(\"a\");detail.className=\"button secondary\";detail.href=\"/credits/region-pack-map?token=\"+token+\"&region_pack_id=\"+id+catalog;detail.textContent=\"View map\";div.appendChild(detail);grid.appendChild(div)}}\nrenderUpsells();" }],
  ["region-pack-map.css", { content_type: "text/css; charset=utf-8", body: ":root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--new:#e45745;--partial:#e2bc49;--licenced:#4fa86a;--free:#69707a;--country:#2a3748;--country-line:#98b4d8;--accent:#d9a441}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}\nmain{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}.muted{color:var(--muted)}\n.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:22px;margin-top:4px}.card.final-price{border-color:#8f732f;box-shadow:0 0 0 1px rgba(217,164,65,.16) inset}.card.final-price b{font-size:26px}.buy-now{width:100%;font-size:16px}\n.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}\nselect{background:#262626;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px}svg{width:100%;height:auto;background:#0d1118;border:1px solid var(--line);border-radius:10px}\n.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0}.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}.new{background:var(--new)}.partial{background:var(--partial)}.licenced{background:var(--licenced)}.free{background:var(--free)}\n.countries{columns:2;column-gap:26px}.countries div{break-inside:avoid;margin:2px 0}.small{font-size:13px}.error{color:#ffb4a9}\n.upsells{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.upsell{background:#151515;border:1px solid var(--line);border-radius:12px;padding:12px}.upsell h3{margin:0 0 8px;font-size:18px}.upsell p{margin:6px 0}.upsell svg{min-height:0}\n.button{display:inline-flex;align-items:center;justify-content:center;margin-top:10px;padding:9px 12px;border-radius:8px;background:var(--accent);color:#111;text-decoration:none;font-weight:700}.button.secondary{margin-left:8px;background:#2a2a2a;color:var(--text);border:1px solid var(--line)}" }],
  ["region-pack-map.js", { content_type: "application/javascript; charset=utf-8", body: "const DATA=window.PLANETKA_REGION_PACK_DATA||{};\nconst NS=\"http://www.w3.org/2000/svg\";\nconst fmtCents=(v)=>\"€\"+(Math.max(0,Number(v||0)||0)/100).toFixed(2);\nconst int=(v)=>Math.max(0,Math.round(Number(v||0)||0));\nfunction priceBreakdownCents(tile,discountPct){const full=int(tile.full_price_cents);const final=int(tile.price_cents);const status=String(tile.status||\"\");const already=status===\"licenced\"?full:0;const partial=status===\"partial\"?Math.min(Math.max(0,full-already),int(tile.upgrade_credit_cents)):0;const preDiscount=Math.max(0,full-already-partial);const discount=Math.max(0,preDiscount-final);const pct=Math.max(0,Number(discountPct||0)||0);const lines=[\"Full Price: \"+fmtCents(full)];if(already>0)lines.push(\"Licenced: - \"+fmtCents(already));if(partial>0)lines.push(\"Partially licenced: - \"+fmtCents(partial));if(discount>0)lines.push(\"Volume Discount (\"+pct+\"%): - \"+fmtCents(discount));lines.push(\"Final Price: \"+fmtCents(final));return lines.join(\"\\n\")}\nfunction zoomLabel(level){const list=(window.PLANETKA_MAP_ZOOM_LEVELS&&window.PLANETKA_MAP_ZOOM_LEVELS.length?window.PLANETKA_MAP_ZOOM_LEVELS:[Number(level)]).map(Number);const i=Math.max(0,list.indexOf(Number(level)));return \"Zoom \"+(i+1)+(i===0?\" - closest\":\"\")}\nconst PRICE_COEFFICIENT=Math.max(0.000001,Number(DATA.price_coefficient||1)||1);\nfunction discountShare(row){return Math.max(0,Number(row&&row.volume_discount_basis&&row.volume_discount_basis.world_land_share||0)||0)}\nfunction roundDiscount(v){return Math.max(0,Math.min(95,Math.round((Number(v||0)||0)/5)*5))}\nconst DISCOUNT_MIN=roundDiscount(DATA.region_pack_discount_min_percent||0);\nconst DISCOUNT_MAX=Math.max(DISCOUNT_MIN,roundDiscount(DATA.region_pack_discount_max_percent||75));\nconst PRODUCT_DISCOUNT_OVERRIDES=DATA.product_discount_overrides||{};\nfunction productDiscountOverride(id){const raw=PRODUCT_DISCOUNT_OVERRIDES[String(id||'').toLowerCase()];const n=Number(raw);return Number.isFinite(n)?Math.max(0,Math.min(100,Math.round(n))):null}\nfunction discountPercentForRow(row){const id=String(row&&row.id||'').toLowerCase();const override=productDiscountOverride(id);if(override!==null)return override;if(id==='world')return DISCOUNT_MAX;const share=discountShare(row);if(share<=0&&row&&row.discount_percent!==undefined)return Math.max(0,Math.min(95,Number(row.discount_percent||0)||0));const ratio=share>=0.75?1:share>=0.25?5/6:share>=0.125?4/6:share>=0.10?3/6:share>=0.07?2/6:share>=0.05?1/6:0;return roundDiscount(DISCOUNT_MIN+(DISCOUNT_MAX-DISCOUNT_MIN)*ratio)}\nconst scaleFullCents=(v)=>Math.max(0,Math.round(int(v)*PRICE_COEFFICIENT));\nconst assetCache=new Map();\nconst assetVersion=encodeURIComponent(String(DATA.map_asset_revision||DATA.catalog_version||DATA.token||Date.now()));\nconst MAP_BG=\"/credits/region-pack-map-background.jpg?v=\"+assetVersion;\nfunction mapBgHref(id){const safe=encodeURIComponent(String(id||\"\").trim());return safe?\"/credits/region-pack-map-background.jpg?region_pack_id=\"+safe+\"&v=\"+assetVersion:MAP_BG}\nconst currentToken=encodeURIComponent(DATA.token||\"\");\nconst currentPackIdEncoded=encodeURIComponent(DATA.asset_id||DATA.region_pack&&DATA.region_pack.id||\"\");\nconst currentCatalog=DATA.catalog_mode?\"&catalog=1\":\"\";\nfunction esc(value){return String(value||\"\").replace(/&/g,\"&amp;\").replace(/</g,\"&lt;\").replace(/>/g,\"&gt;\").replace(/\"/g,\"&quot;\")}\nfunction countryName(value){return typeof value===\"object\"&&value?String(value.name||value.COUNTRY||value.NAME_1||value.GID_0||\"\"):String(value||\"\")}\nconst CHINA_ADMIN_LABELS=new Set([\"anhui\",\"beijing\",\"chongqing\",\"fujian\",\"gansu\",\"guangdong\",\"guangxi\",\"guizhou\",\"hainan\",\"hebei\",\"heilongjiang\",\"henan\",\"hong kong\",\"hubei\",\"hunan\",\"jiangsu\",\"jiangxi\",\"jilin\",\"liaoning\",\"macau\",\"nei mongol\",\"ningxia hui\",\"qinghai\",\"shaanxi\",\"shandong\",\"shanghai\",\"shanxi\",\"sichuan\",\"tianjin\",\"xinjiang uygur\",\"xizang\",\"yunnan\",\"zhejiang\"]);\nconst US_ADMIN_LABELS=new Set([\"alabama\",\"alaska\",\"arizona\",\"arkansas\",\"california\",\"colorado\",\"connecticut\",\"delaware\",\"district of columbia\",\"florida\",\"georgia\",\"hawaii\",\"idaho\",\"illinois\",\"indiana\",\"iowa\",\"kansas\",\"kentucky\",\"louisiana\",\"maine\",\"maryland\",\"massachusetts\",\"michigan\",\"minnesota\",\"mississippi\",\"missouri\",\"montana\",\"nebraska\",\"nevada\",\"new hampshire\",\"new jersey\",\"new mexico\",\"new york\",\"north carolina\",\"north dakota\",\"ohio\",\"oklahoma\",\"oregon\",\"pennsylvania\",\"rhode island\",\"south carolina\",\"south dakota\",\"tennessee\",\"texas\",\"utah\",\"vermont\",\"virginia\",\"washington\",\"west virginia\",\"wisconsin\",\"wyoming\"]);\nconst CANADA_ADMIN_LABELS=new Set([\"alberta\",\"british columbia\",\"manitoba\",\"new brunswick\",\"newfoundland and labrador\",\"northwest territories\",\"nova scotia\",\"nunavut\",\"ontario\",\"prince edward island\",\"québec\",\"quebec\",\"saskatchewan\",\"yukon\"]);\nfunction currentPackId(){return String(DATA.asset_id||DATA.region_pack&&DATA.region_pack.id||\"\").trim().toLowerCase()}\nfunction collapsedIncludedLabel(key){const id=currentPackId();if(CHINA_ADMIN_LABELS.has(key))return \"China\";if((id===\"north_america\"||id===\"united_states\")&&US_ADMIN_LABELS.has(key))return \"United States\";if((id===\"north_america\"||id===\"canada\")&&CANADA_ADMIN_LABELS.has(key))return \"Canada\";return \"\"}\nfunction uniqueCountryNames(values){const seen=new Set(),out=[];for(const entry of Array.isArray(values)?values:[]){let label=countryName(entry).trim();let key=label.toLowerCase();const collapsed=collapsedIncludedLabel(key);if(collapsed){label=collapsed;key=label.toLowerCase()}if(!label||seen.has(key))continue;seen.add(key);out.push(label)}return out.sort((a,b)=>a.localeCompare(b))}\nfunction parseTileKey(key){const m=/x(\\d{3})_y(\\d{3})_z(\\d{3})_d(\\d{3})/i.exec(String(key||\"\"));return m?{key:m[0],x:Number(m[1]),y:Number(m[2]),z:Number(m[3]),d:Number(m[4])}:null}\nfunction family(parsed){return parsed?\"x\"+String(parsed.x).padStart(3,\"0\")+\"_y\"+String(parsed.y).padStart(3,\"0\")+\"_z\"+String(parsed.z).padStart(3,\"0\"):\"\"}\nfunction tileSort(a,b){const pa=parseTileKey(a.tile_key),pb=parseTileKey(b.tile_key),fa=family(pa),fb=family(pb);return fa===fb?(Number(pa&&pa.d||0)-Number(pb&&pb.d||0)):fa<fb?-1:1}\n\tfunction buildOwnedByFamily(){const map=new Map();for(const row of DATA.owned_tiles||[]){const p=parseTileKey(row.tile_key);const f=family(p);if(!p||!f)continue;if(!map.has(f))map.set(f,[]);map.get(f).push({d:p.d,gross_cents:int(row.gross_cents)})}return map}\n\tasync function loadAsset(id){const safe=String(id||\"\").trim();if(assetCache.has(safe))return assetCache.get(safe);const res=await fetch(\"/credits/region-pack-map-asset?region_pack_id=\"+encodeURIComponent(safe)+\"&v=\"+assetVersion,{cache:\"reload\"});if(!res.ok)throw new Error(\"map_asset_\"+res.status);const asset=await res.json();assetCache.set(safe,asset);return asset}\n\tfunction rawPackGrossCents(rows){const owned=new Map();let total=0;for(const tile of rows){const p=parseTileKey(tile.tile_key);const f=family(p);const full=scaleFullCents(tile.full_price_cents||tile.gross_cents);const globallyFree=!!tile.globally_free||full<=0;if(!p||!f||globallyFree)continue;if(!owned.has(f))owned.set(f,[]);const entries=owned.get(f);const covered=entries.some((entry)=>Number(entry.d)<=Number(p.d));let coarser=0;for(const entry of entries){if(Number(entry.d)>Number(p.d))coarser=Math.max(coarser,int(entry.gross_cents))}const charge=covered?0:Math.max(0,full-coarser);if(charge>0){total+=charge;entries.push({d:Number(p.d),gross_cents:full})}}return total}\n\tfunction computeAsset(asset){const initiallyOwned=buildOwnedByFamily();const owned=buildOwnedByFamily();const world=!!DATA.world_full_quality_unlocked;const discountPct=discountPercentForRow(asset&&asset.region_pack||{});const rows=(asset.tiles||[]).slice().sort(tileSort);const rawFullCents=rawPackGrossCents(rows);const paid=[];let grossCents=0,alreadyCount=0,freeCount=0,alreadyDeductionCents=0,partialCount=0,partialCreditCents=0;\n\t  for(const tile of rows){const p=parseTileKey(tile.tile_key);const f=family(p);const full=scaleFullCents(tile.full_price_cents||tile.gross_cents);const globallyFree=!!tile.globally_free||full<=0;if(!owned.has(f))owned.set(f,[]);const entries=owned.get(f);const initialEntries=initiallyOwned.get(f)||[];const previouslyCovered=world||initialEntries.some((entry)=>Number(entry.d)<=Number(p&&p.d||0));const coveredForCharge=world||entries.some((entry)=>Number(entry.d)<=Number(p&&p.d||0));let coarser=0;for(const entry of entries){if(Number(entry.d)>Number(p&&p.d||0))coarser=Math.max(coarser,int(entry.gross_cents))}let initialCoarser=0;for(const entry of initialEntries){if(Number(entry.d)>Number(p&&p.d||0))initialCoarser=Math.max(initialCoarser,int(entry.gross_cents))}\n\t    const charge=globallyFree||coveredForCharge?0:Math.max(0,full-coarser);const appliedPartial=!globallyFree&&!previouslyCovered&&!coveredForCharge?Math.min(full,initialCoarser):0;let status=\"free\";if(previouslyCovered&&!globallyFree){status=\"licenced\";alreadyCount+=1;alreadyDeductionCents+=full}else if(charge>0){status=appliedPartial>0?\"partial\":\"new\";if(appliedPartial>0){partialCount+=1;partialCreditCents+=appliedPartial}grossCents+=charge;paid.push({tile,cents:charge})}else{if(appliedPartial>0){status=\"partial\";partialCount+=1;partialCreditCents+=appliedPartial}else{freeCount+=1}}\n\t    if(charge>0&&entries){entries.push({d:Number(p&&p.d||0),gross_cents:full})}\n\t    tile.x=p?p.x:null;tile.y=p?p.y:null;tile.z=p?p.z:null;tile.d=p?p.d:null;const lonMin=Number(tile.lon_min),lonMax=Number(tile.lon_max),latMin=Number(tile.lat_min),latMax=Number(tile.lat_max);tile.lon_min=Number.isFinite(lonMin)?lonMin:(p?p.x-180:null);tile.lon_max=Number.isFinite(lonMax)?lonMax:(p?p.x-180+p.z:null);tile.lat_min=Number.isFinite(latMin)?latMin:(p?p.y-90:null);tile.lat_max=Number.isFinite(latMax)?latMax:(p?p.y-90+p.z:null);tile.status=status;tile.charge_cents=charge;tile.upgrade_credit_cents=appliedPartial;tile.partially_licenced=status===\"partial\";tile.price_cents=0;tile.full_price_cents=full;tile.full_price_eur=full/100;tile.price_eur=0;\n\t  }\n\t  const discountCents=Math.round(grossCents*discountPct/100);const targetCents=Math.max(0,grossCents-discountCents);let allocated=0;const alloc=paid.map((entry,index)=>{const raw=grossCents>0?(entry.cents*targetCents/grossCents):0;const floor=Math.floor(raw);allocated+=floor;return{entry,index,cents:floor,remainder:raw-floor}}).sort((a,b)=>b.remainder!==a.remainder?b.remainder-a.remainder:a.index-b.index);let rem=Math.max(0,targetCents-allocated);for(const item of alloc){if(rem<=0)break;item.cents+=1;rem-=1}for(const item of alloc){item.entry.tile.price_cents=item.cents;item.entry.tile.price_eur=item.cents/100;if(item.cents<=0&&item.entry.tile.status!==\"partial\")item.entry.tile.status=\"free\"}\n\t  const levels=Array.from(new Set(rows.map((row)=>Number(row.z)).filter(Number.isFinite))).sort((a,b)=>a-b);const unlicencedCount=world?0:Math.max(0,rows.length-alreadyCount);return{asset,rows,levels,summary:{new_tiles:unlicencedCount,charged_tiles:paid.filter((entry)=>entry.tile.price_cents>0).length,total_tiles:rows.length,already_licenced_tiles:alreadyCount,partial_licence_tiles:partialCount,free_tiles:freeCount,full_price_cents:rawFullCents,discount_percent:discountPct,discount_cents:discountCents,price_cents:targetCents,already_licenced_deduction_cents:alreadyDeductionCents,already_licenced_saving_cents:alreadyDeductionCents,partial_licence_credit_cents:partialCreditCents}}}\n\tfunction currentBuyHref(){return currentPackIdEncoded?\"/credits/region-pack-checkout?token=\"+currentToken+\"&region_pack_id=\"+currentPackIdEncoded+currentCatalog:\"\"}\n\tfunction renderCards(vm){const s=vm.summary;const partialTiles=Number(s.partial_licence_tiles||0);const alreadyTiles=Number(s.already_licenced_tiles||0)+partialTiles;const alreadyValue=int(s.already_licenced_deduction_cents)+int(s.partial_licence_credit_cents);const discountValue=int(s.discount_cents);const newTiles=Math.max(0,Number(s.new_tiles||0)-partialTiles);const cards=[[\"New Tiles / Total Tiles\",newTiles+\" / \"+Number(s.total_tiles||0)],[\"Full Price\",fmtCents(s.full_price_cents)]];if(alreadyValue>0)cards.push([\"Already Licenced\",alreadyTiles+\" tiles (-\"+fmtCents(alreadyValue)+\")\"]);if(discountValue>0)cards.push([\"Volume Discount\",Number(s.discount_percent||0)+\"% (-\"+fmtCents(discountValue)+\")\"]);const buy=currentBuyHref()?\"<a class=\\\"button buy-now\\\" href=\\\"\"+currentBuyHref()+\"\\\">\"+(int(s.price_cents)>0?\"Buy Now\":\"Licence Now\")+\"</a>\":\"\";cards.push([\"Final Price\",fmtCents(s.price_cents),buy]);document.getElementById(\"cards\").innerHTML=cards.map((c)=>\"<div class=\\\"card \"+(c[0]===\"Final Price\"?\"final-price\":\"\")+\"\\\"><span>\"+esc(c[0])+\"</span><b>\"+esc(c[1])+\"</b>\"+(c[2]||\"\")+\"</div>\").join(\"\")}\nfunction frameForBounds(rawBounds,width,minHeight,maxHeight,padSize){const b=rawBounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const minLon=Number.isFinite(Number(b.min_lon))?Number(b.min_lon):-10,minLat=Number.isFinite(Number(b.min_lat))?Number(b.min_lat):35,maxLon=Number.isFinite(Number(b.max_lon))?Number(b.max_lon):30,maxLat=Number.isFinite(Number(b.max_lat))?Number(b.max_lat):48;const lonSpan=Math.max(1e-6,maxLon-minLon),latSpan=Math.max(1e-6,maxLat-minLat),innerW=Math.max(1,width-padSize*2);const naturalH=Math.round(latSpan*(innerW/lonSpan))+padSize*2,height=Math.max(minHeight,Math.min(maxHeight,naturalH)),innerH=Math.max(1,height-padSize*2),scale=Math.min(innerW/lonSpan,innerH/latSpan),usedW=lonSpan*scale,usedH=latSpan*scale;return{bounds:{min_lon:minLon,min_lat:minLat,max_lon:maxLon,max_lat:maxLat},width,height,scale,ox:(width-usedW)/2,oy:(height-usedH)/2}}\nlet currentFrame=frameForBounds({min_lon:-10,min_lat:35,max_lon:30,max_lat:48},1000,320,820,20),W=currentFrame.width,H=currentFrame.height;\nfunction setBounds(bounds){currentFrame=frameForBounds(bounds||currentFrame.bounds,1000,320,820,20);W=currentFrame.width;H=currentFrame.height}\nfunction xy(lon,lat){return [currentFrame.ox+(lon-currentFrame.bounds.min_lon)*currentFrame.scale,currentFrame.oy+(currentFrame.bounds.max_lat-lat)*currentFrame.scale]}\nfunction el(name,attrs){const node=document.createElementNS(NS,name);for(const k in attrs||{})node.setAttribute(k,String(attrs[k]));return node}\nfunction addMapBackground(svg,project,width,height,id,bounds){svg.appendChild(el(\"rect\",{x:0,y:0,width,height,fill:\"#0d1118\"}));const safeId=String(id||\"\").trim();if(safeId&&safeId!==\"scene\"){svg.appendChild(el(\"image\",{href:mapBgHref(safeId),x:0,y:0,width,height,preserveAspectRatio:\"none\",opacity:\"1.0\"}))}else{const tl=project(-180,90),br=project(180,-90);svg.appendChild(el(\"image\",{href:MAP_BG,x:tl[0],y:tl[1],width:br[0]-tl[0],height:br[1]-tl[1],preserveAspectRatio:\"none\",opacity:\"1.0\"}))}svg.appendChild(el(\"rect\",{x:0,y:0,width,height,fill:\"#05070a\",opacity:\"0.0\"}))}\nfunction pathFor(poly){return(poly||[]).map((pt,i)=>{const p=xy(pt[0],pt[1]);return(i?\"L\":\"M\")+p[0].toFixed(2)+\" \"+p[1].toFixed(2)}).join(\" \")}\nfunction renderMap(vm,level){const svg=document.getElementById(\"map\");svg.replaceChildren();svg.setAttribute(\"viewBox\",\"0 0 \"+W+\" \"+H);svg.setAttribute(\"preserveAspectRatio\",\"xMidYMid meet\");addMapBackground(svg,xy,W,H,vm.asset&&vm.asset.region_pack&&vm.asset.region_pack.id,vm.asset&&vm.asset.bounds);for(const outline of vm.asset.outlines||[]){for(const poly of outline.polygons||[]){const p=el(\"path\",{d:pathFor(poly),fill:\"none\",stroke:\"var(--country-line)\",\"stroke-width\":\"0.7\",opacity:\"0.72\"});const t=el(\"title\",{});t.textContent=outline.name;p.appendChild(t);svg.appendChild(p)}}const rows=vm.rows.filter((row)=>Number(row.z)===Number(level));let chargedCount=0,licencedCount=0,partialCount=0,freeCount=0,price=0;for(const tile of rows){const a=xy(tile.lon_min,tile.lat_max),b=xy(tile.lon_max,tile.lat_min);const cls=tile.status===\"new\"?\"var(--new)\":(tile.status===\"partial\"?\"var(--partial)\":(tile.status===\"licenced\"?\"var(--licenced)\":\"var(--free)\"));if(tile.status===\"new\"||tile.status===\"partial\"){chargedCount++;price+=int(tile.price_cents);if(tile.status===\"partial\")partialCount++}else if(tile.status===\"licenced\"){licencedCount++}else{freeCount++}const r=el(\"rect\",{x:a[0],y:a[1],width:Math.max(1,b[0]-a[0]),height:Math.max(1,b[1]-a[1]),fill:cls,stroke:\"#fff\",\"stroke-width\":\"0.45\",opacity:(tile.status===\"new\"||tile.status===\"partial\")?\"0.58\":\"0.43\"});const title=el(\"title\",{});const statusText=tile.status===\"partial\"?\"partially licenced (upgrade price only)\":tile.status;let hover=tile.tile_key+\"\\nLand: \"+Number(tile.billable_land_km2||0).toFixed(2)+\" km²\\nStatus: \"+statusText+\"\\n\"+priceBreakdownCents(tile,vm.summary&&vm.summary.discount_percent||0);title.textContent=hover;r.appendChild(title);svg.appendChild(r)}const licenceBenefitCount=licencedCount+partialCount;const newCount=Math.max(0,rows.length-licenceBenefitCount);document.getElementById(\"levelSummary\").textContent=rows.length+\" tiles at \"+zoomLabel(level)+\" · new \"+newCount+\" · charged \"+chargedCount+\" · already licenced \"+licenceBenefitCount+\" · free \"+freeCount+\" · current zoom price \"+fmtCents(price)}\nfunction miniFrame(bounds){return frameForBounds(bounds,1000,320,820,20)}\nfunction miniXY(frame,lon,lat){return[frame.ox+(lon-frame.bounds.min_lon)*frame.scale,frame.oy+(frame.bounds.max_lat-lat)*frame.scale]}\nfunction renderMiniMap(svg,vm){const b=vm.asset.bounds||{min_lon:-10,min_lat:35,max_lon:30,max_lat:48};const frame=miniFrame(b),w=frame.width,h=frame.height;svg.setAttribute(\"viewBox\",\"0 0 \"+w+\" \"+h);svg.style.aspectRatio=w+\" / \"+h;svg.setAttribute(\"preserveAspectRatio\",\"xMidYMid meet\");svg.replaceChildren();const bgId=vm&&vm.asset&&vm.asset.region_pack&&vm.asset.region_pack.id||\"\";addMapBackground(svg,(lon,lat)=>miniXY(frame,lon,lat),w,h,bgId,b);const first=vm.levels.length?vm.levels[0]:null;for(const tile of vm.rows.filter((row)=>Number(row.z)===Number(first))){const a=miniXY(frame,tile.lon_min,tile.lat_max),c=miniXY(frame,tile.lon_max,tile.lat_min);const cls=tile.status===\"new\"?\"var(--new)\":(tile.status===\"partial\"?\"var(--partial)\":(tile.status===\"licenced\"?\"var(--licenced)\":\"var(--free)\"));svg.appendChild(el(\"rect\",{x:a[0],y:a[1],width:Math.max(1,c[0]-a[0]),height:Math.max(1,c[1]-a[1]),fill:cls,stroke:\"#fff\",\"stroke-width\":\"0.5\",opacity:(tile.status===\"new\"||tile.status===\"partial\")?\"0.58\":\"0.43\"}))}}\nasync function renderUpsells(asset){const ids=Array.isArray(DATA.similar_pack_ids)?DATA.similar_pack_ids:(Array.isArray(asset.upsell_ids)?asset.upsell_ids:[]);const grid=document.getElementById(\"upsellGrid\");if(!grid||!ids.length)return;const token=encodeURIComponent(DATA.token||\"\");const catalog=\"&catalog=1\";for(const idRaw of ids){try{const upAsset=await loadAsset(idRaw);const vm=computeAsset(upAsset);if(vm.summary.price_cents<=0&&Number(vm.summary.charged_tiles||0)<=0)continue;const id=encodeURIComponent(upAsset.region_pack.id||idRaw);const div=document.createElement(\"div\");div.className=\"upsell\";const title=document.createElement(\"h3\");title.textContent=upAsset.region_pack.name||\"Region Pack\";div.appendChild(title);const map=document.createElementNS(NS,\"svg\");div.appendChild(map);renderMiniMap(map,vm);const meta=document.createElement(\"p\");meta.className=\"muted small\";const alreadyValue=int(vm.summary.already_licenced_deduction_cents)+int(vm.summary.partial_licence_credit_cents);const bits=[\"Full \"+fmtCents(vm.summary.full_price_cents)];if(alreadyValue>0)bits.push(\"Already -\"+fmtCents(alreadyValue));if(int(vm.summary.discount_cents)>0)bits.push(\"Discount \"+Number(vm.summary.discount_percent||0)+\"% (-\"+fmtCents(vm.summary.discount_cents)+\")\");bits.push(\"Final \"+fmtCents(vm.summary.price_cents));meta.textContent=bits.join(\" · \" );div.appendChild(meta);const checkout=document.createElement(\"a\");checkout.className=\"button\";checkout.href=\"/credits/region-pack-checkout?token=\"+token+\"&region_pack_id=\"+id+catalog;checkout.textContent=\"Buy \"+(upAsset.region_pack.name||\"Pack\")+\" (\"+fmtCents(vm.summary.price_cents)+\")\";div.appendChild(checkout);const detail=document.createElement(\"a\");detail.className=\"button secondary\";detail.href=\"/credits/region-pack-map?token=\"+token+\"&region_pack_id=\"+id+catalog;detail.textContent=\"View map\";div.appendChild(detail);grid.appendChild(div);document.getElementById(\"upsellsPanel\").style.display=\"\"}catch(error){console.warn(\"Planetka upsell map failed\",idRaw,error)}}}\nasync function init(){try{const asset=await loadAsset(DATA.asset_id);const titlePrefix=String(DATA.title_prefix||DATA.success&&DATA.success.context_title_prefix||\"\").trim();document.getElementById(\"pageTitle\").textContent=(titlePrefix?titlePrefix+\": \":\"\")+(asset.region_pack.name||\"Region Pack\")+\" Full Quality Pack\";const vm=computeAsset(asset);renderCards(vm);setBounds(asset.bounds);const countries=uniqueCountryNames(asset.included_countries);if(countries.length){document.getElementById(\"countries\").innerHTML=countries.map((c)=>\"<div>\"+esc(c)+\"</div>\").join(\"\");document.getElementById(\"countriesPanel\").style.display=\"\"}const select=document.getElementById(\"levelSelect\");select.replaceChildren();const levels=vm.levels.length?vm.levels:[1];window.PLANETKA_MAP_ZOOM_LEVELS=levels;for(const z of levels){const o=document.createElement(\"option\");o.value=String(z);o.textContent=zoomLabel(z);select.appendChild(o)}select.addEventListener(\"change\",()=>renderMap(vm,Number(select.value)));renderMap(vm,Number(select.value||levels[0]));document.getElementById(\"mapStatus\").textContent=\"Map loaded.\";renderUpsells(asset)}catch(error){console.warn(\"Planetka region-pack map failed\",error);document.getElementById(\"mapStatus\").className=\"error small\";document.getElementById(\"mapStatus\").textContent=\"Map failed to load. Please reopen this page from Blender.\"}}\ninit();" }],
  ["region-pack-catalog.css", { content_type: "text/css; charset=utf-8", body: ":root{color-scheme:dark;--bg:#111;--panel:#1b1b1b;--line:#3c3c3c;--text:#eee;--muted:#aaa;--accent:#d9a441;--soft:#262626}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}\nmain{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 8px;font-size:28px;font-weight:650}h2{margin:26px 0 10px;font-size:19px}.muted{color:var(--muted)}\n.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}\ninput{min-width:260px;flex:1;background:var(--soft);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 11px}.small{font-size:13px}.saving{color:#9dd18d}.price{font-weight:700;color:#f4d28d}.error{color:#ffb4a9}.empty{padding:12px;color:var(--muted)}\n.catalog-section{margin-top:14px}.subsection-title{margin:18px 0 8px;color:#ddd;font-size:15px;font-weight:700}.catalog-table{width:100%;border-collapse:separate;border-spacing:0 7px}.catalog-table th{padding:0 10px 5px;text-align:right;color:var(--muted);font-size:12px;font-weight:650}.catalog-table th:first-child{text-align:left}.catalog-table td{padding:10px;background:#151515;border-top:1px solid var(--line);border-bottom:1px solid var(--line);text-align:right;vertical-align:middle;white-space:nowrap}.catalog-table td:first-child{border-left:1px solid var(--line);border-radius:9px 0 0 9px;text-align:left;white-space:normal}.catalog-table td:last-child{border-right:1px solid var(--line);border-radius:0 9px 9px 0}.catalog-table tr:hover td{border-color:#575757;background:#181818}.pack-name{font-weight:700}.pack-kind{display:block;color:var(--muted);font-size:12px;margin-top:1px}.actions{display:flex;justify-content:flex-end;gap:7px;flex-wrap:wrap}.button{display:inline-flex;align-items:center;justify-content:center;padding:7px 10px;border-radius:8px;background:var(--accent);color:#111;text-decoration:none;font-weight:700;border:0}.button.secondary{background:#2a2a2a;color:var(--text);border:1px solid var(--line)}\n@media(max-width:760px){main{padding:16px}.catalog-table,.catalog-table tbody,.catalog-table tr,.catalog-table td{display:block;width:100%}.catalog-table thead{display:none}.catalog-table tr{margin:0 0 9px}.catalog-table td{border-left:1px solid var(--line);border-right:1px solid var(--line);border-radius:0;text-align:left}.catalog-table td:first-child{border-radius:9px 9px 0 0}.catalog-table td:last-child{border-radius:0 0 9px 9px}.catalog-table td[data-label]::before{content:attr(data-label);display:block;color:var(--muted);font-size:12px}.actions{justify-content:flex-start}}" }],
  ["region-pack-catalog.js", { content_type: "application/javascript; charset=utf-8", body: "const DATA=window.PLANETKA_REGION_PACK_DATA||{};\nconst fmtCents=(v)=>\"\u20ac\"+(Math.max(0,Number(v||0)||0)/100).toFixed(2);\nconst int=(v)=>Math.max(0,Math.round(Number(v||0)||0));\nconst PRICE_COEFFICIENT=Math.max(0.000001,Number(DATA.price_coefficient||1)||1);\nfunction discountShare(row){return Math.max(0,Number(row&&row.volume_discount_basis&&row.volume_discount_basis.world_land_share||0)||0)}\nfunction roundDiscount(v){return Math.max(0,Math.min(95,Math.round((Number(v||0)||0)/5)*5))}\nconst DISCOUNT_MIN=roundDiscount(DATA.region_pack_discount_min_percent||0);\nconst DISCOUNT_MAX=Math.max(DISCOUNT_MIN,roundDiscount(DATA.region_pack_discount_max_percent||75));\nconst PRODUCT_DISCOUNT_OVERRIDES=DATA.product_discount_overrides||{};\nfunction productDiscountOverride(id){const raw=PRODUCT_DISCOUNT_OVERRIDES[String(id||'').toLowerCase()];const n=Number(raw);return Number.isFinite(n)?Math.max(0,Math.min(100,Math.round(n))):null}\nfunction discountPercentForRow(row){const id=String(row&&row.id||'').toLowerCase();const override=productDiscountOverride(id);if(override!==null)return override;if(id==='world')return DISCOUNT_MAX;const share=discountShare(row);if(share<=0&&row&&row.discount_percent!==undefined)return Math.max(0,Math.min(95,Number(row.discount_percent||0)||0));const ratio=share>=0.75?1:share>=0.25?5/6:share>=0.125?4/6:share>=0.10?3/6:share>=0.07?2/6:share>=0.05?1/6:0;return roundDiscount(DISCOUNT_MIN+(DISCOUNT_MAX-DISCOUNT_MIN)*ratio)}\nconst scaleFullCents=(v)=>Math.max(0,Math.round(int(v)*PRICE_COEFFICIENT));\nconst token=encodeURIComponent(DATA.token||\"\");\nconst COUNTRY_LIKE_IDS=new Set([\"australia\",\"canada\",\"china\",\"united_states\"]);\nconst STATE_PARENT_IDS={\n  \"Australia\":new Set([\"new_south_wales\",\"northern_territory\",\"queensland\",\"south_australia\",\"tasmania\",\"victoria\",\"western_australia\"]),\n  \"Canada\":new Set([\"alberta\",\"british_columbia\",\"manitoba\",\"new_brunswick\",\"newfoundland_and_labrador\",\"northwest_territories\",\"nova_scotia\",\"nunavut\",\"ontario\",\"prince_edward_island\",\"quebec\",\"saskatchewan\",\"yukon\"]),\n  \"China\":new Set([\"anhui\",\"beijing\",\"chongqing\",\"fujian\",\"gansu\",\"guangdong\",\"guangxi\",\"guizhou\",\"hainan\",\"hebei\",\"heilongjiang\",\"henan\",\"hong_kong\",\"hubei\",\"hunan\",\"jiangsu\",\"jiangxi\",\"jilin\",\"liaoning\",\"macau\",\"nei_mongol\",\"ningxia_hui\",\"qinghai\",\"shaanxi\",\"shandong\",\"shanghai\",\"shanxi\",\"sichuan\",\"tianjin\",\"xinjiang_uygur\",\"xizang\",\"yunnan\",\"zhejiang\"]),\n  \"United States\":new Set([\"alabama\",\"alaska\",\"arizona\",\"arkansas\",\"california\",\"colorado\",\"connecticut\",\"delaware\",\"district_of_columbia\",\"florida\",\"georgia\",\"hawaii\",\"idaho\",\"illinois\",\"indiana\",\"iowa\",\"kansas\",\"kentucky\",\"louisiana\",\"maine\",\"maryland\",\"massachusetts\",\"michigan\",\"minnesota\",\"mississippi\",\"missouri\",\"montana\",\"nebraska\",\"nevada\",\"new_hampshire\",\"new_jersey\",\"new_mexico\",\"new_york\",\"north_carolina\",\"north_dakota\",\"ohio\",\"oklahoma\",\"oregon\",\"pennsylvania\",\"rhode_island\",\"south_carolina\",\"south_dakota\",\"tennessee\",\"texas\",\"utah\",\"vermont\",\"virginia\",\"washington\",\"west_virginia\",\"wisconsin\",\"wyoming\"])\n};\nfunction esc(value){return String(value||\"\").replace(/&/g,\"&amp;\").replace(/</g,\"&lt;\").replace(/>/g,\"&gt;\").replace(/\\\"/g,\"&quot;\")}\nfunction parseTileKey(key){const m=/x(\\d{3})_y(\\d{3})_z(\\d{3})_d(\\d{3})/i.exec(String(key||\"\"));return m?{key:m[0],x:Number(m[1]),y:Number(m[2]),z:Number(m[3]),d:Number(m[4])}:null}\nfunction family(parsed){return parsed?\"x\"+String(parsed.x).padStart(3,\"0\")+\"_y\"+String(parsed.y).padStart(3,\"0\")+\"_z\"+String(parsed.z).padStart(3,\"0\"):\"\"}\nfunction tileSort(a,b){const pa=parseTileKey(a[0]),pb=parseTileKey(b[0]),fa=family(pa),fb=family(pb);return fa===fb?(Number(pa&&pa.d||0)-Number(pb&&pb.d||0)):fa<fb?-1:1}\nfunction buildOwnedByFamily(){const map=new Map();for(const row of DATA.owned_tiles||[]){const p=parseTileKey(row.tile_key);const f=family(p);if(!p||!f)continue;if(!map.has(f))map.set(f,[]);map.get(f).push({d:p.d,gross_cents:int(row.gross_cents)})}return map}\nfunction rawProductGrossCents(row){const tiles=(row.tiles||[]).slice().sort(tileSort);if(!tiles.length)return scaleFullCents(row.full_price_cents||row.gross_cents);const owned=new Map();let total=0;for(const tile of tiles){const p=parseTileKey(tile[0]);const f=family(p);const full=scaleFullCents(tile[1]);const globallyFree=!!tile[2]||full<=0;if(!p||!f||globallyFree)continue;if(!owned.has(f))owned.set(f,[]);const entries=owned.get(f);const covered=entries.some((entry)=>Number(entry.d)<=Number(p.d));let coarser=0;for(const entry of entries){if(Number(entry.d)>Number(p.d))coarser=Math.max(coarser,int(entry.gross_cents))}const charge=covered?0:Math.max(0,full-coarser);if(charge>0){total+=charge;entries.push({d:Number(p.d),gross_cents:full})}}return total}\nfunction computeProduct(row){const discountPct=discountPercentForRow(row);const fullGross=rawProductGrossCents(row);if(row.world){const discount=Math.round(fullGross*discountPct/100);const price=DATA.world_full_quality_unlocked?0:Math.max(0,fullGross-discount);const already=DATA.world_full_quality_unlocked?fullGross:0;return{...row,new_tiles:DATA.world_full_quality_unlocked?0:Number(row.total_tiles||0),charged_tiles:DATA.world_full_quality_unlocked?0:Number(row.total_tiles||0),already_licenced_tiles:DATA.world_full_quality_unlocked?Number(row.total_tiles||0):0,full_price_cents:fullGross,chargeable_full_price_cents:DATA.world_full_quality_unlocked?0:fullGross,discount_cents:DATA.world_full_quality_unlocked?0:discount,price_cents:price,already_licenced_deduction_cents:already,already_licenced_saving_cents:already}}\n  const initiallyOwned=buildOwnedByFamily();const owned=buildOwnedByFamily();const world=!!DATA.world_full_quality_unlocked;const tiles=(row.tiles||[]).slice().sort(tileSort);let gross=0,alreadyCount=0,freeCount=0,chargedCount=0,already=0,partialCount=0,partialCredit=0;for(const tile of tiles){const p=parseTileKey(tile[0]);const f=family(p);const full=scaleFullCents(tile[1]);const globallyFree=!!tile[2]||full<=0;if(!owned.has(f))owned.set(f,[]);const entries=owned.get(f);const initialEntries=initiallyOwned.get(f)||[];const previouslyCovered=world||initialEntries.some((entry)=>Number(entry.d)<=Number(p&&p.d||0));const coveredForCharge=world||entries.some((entry)=>Number(entry.d)<=Number(p&&p.d||0));let coarser=0;for(const entry of entries){if(Number(entry.d)>Number(p&&p.d||0))coarser=Math.max(coarser,int(entry.gross_cents))}let initialCoarser=0;for(const entry of initialEntries){if(Number(entry.d)>Number(p&&p.d||0))initialCoarser=Math.max(initialCoarser,int(entry.gross_cents))}const charge=globallyFree||coveredForCharge?0:Math.max(0,full-coarser);const appliedPartial=!globallyFree&&!previouslyCovered&&!coveredForCharge?Math.min(full,initialCoarser):0;if(previouslyCovered&&!globallyFree){alreadyCount++;already+=full}else if(charge>0){chargedCount++;gross+=charge;if(appliedPartial>0){partialCount++;partialCredit+=appliedPartial}entries.push({d:Number(p&&p.d||0),gross_cents:full})}else{if(appliedPartial>0){partialCount++;partialCredit+=appliedPartial}else{freeCount++}}}const discount=Math.round(gross*discountPct/100);const price=Math.max(0,gross-discount);const newCount=world?0:Math.max(0,tiles.length-alreadyCount);return{...row,new_tiles:newCount,charged_tiles:chargedCount,already_licenced_tiles:alreadyCount,partial_licence_tiles:partialCount,free_tiles:freeCount,full_price_cents:fullGross,chargeable_full_price_cents:gross,discount_cents:discount,price_cents:price,already_licenced_deduction_cents:already,already_licenced_saving_cents:already,partial_licence_credit_cents:partialCredit}}\nfunction kindLabel(row){return String(row.group_label||row.type||\"Data Pack\")}\nfunction buyHref(row){return \"/credits/region-pack-checkout?token=\"+token+\"&region_pack_id=\"+encodeURIComponent(row.id||\"\")+\"&catalog=1\"}\nfunction mapHref(row){return \"/credits/region-pack-map?token=\"+token+\"&region_pack_id=\"+encodeURIComponent(row.id||\"\")+\"&catalog=1\"}\nfunction parentLabel(row){const id=String(row&&row.id||\"\").toLowerCase();for(const [label,ids] of Object.entries(STATE_PARENT_IDS)){if(ids.has(id))return label}return \"Other\"}\nfunction sectionKey(row){const id=String(row&&row.id||\"\").toLowerCase();const group=String(row&&row.group_key||\"\").toLowerCase();const type=String(row&&row.type||\"\").toLowerCase();if(id===\"world\"||group===\"world\"||row.world)return \"world\";if(COUNTRY_LIKE_IDS.has(id))return \"countries\";if(group===\"states_provinces\")return \"states_provinces\";if(group===\"continents\")return \"continents\";if(group===\"regions\")return \"regions\";if(group===\"countries\"||type===\"country\"||type===\"admin_region\")return \"countries\";return \"regions\"}\nfunction rowHtml(row){return \"<tr>\"\n+\"<td><span class=\\\"pack-name\\\">\"+esc(row.name||\"Data Pack\")+\"</span></td>\"\n+\"<td data-label=\\\"New / Total\\\">\"+Number(row.new_tiles||0)+\" / \"+Number(row.total_tiles||0)+\"</td>\"\n+\"<td data-label=\\\"Full Price\\\">\"+fmtCents(row.full_price_cents)+\"</td>\"\n+\"<td data-label=\\\"Final Price\\\" class=\\\"price\\\">\"+fmtCents(row.price_cents)+\"</td>\"\n+\"<td data-label=\\\"Buy\\\"><a class=\\\"button\\\" href=\\\"\"+buyHref(row)+\"\\\">Buy</a></td>\"\n+\"<td data-label=\\\"Map\\\"><a class=\\\"button secondary\\\" href=\\\"\"+mapHref(row)+\"\\\">Map</a></td>\"\n+\"</tr>\"}\nfunction tableHtml(rows){if(!rows.length)return \"<div class=\\\"empty\\\">No data packs in this section.</div>\";return \"<table class=\\\"catalog-table\\\"><thead><tr><th>Data Pack</th><th>New / Total</th><th>Full Price</th><th>Final Price</th><th>Buy</th><th>Map</th></tr></thead><tbody>\"+rows.map(rowHtml).join(\"\")+\"</tbody></table>\"}\nfunction sortRows(rows){return rows.slice().sort((a,b)=>String(a.name||\"\").localeCompare(String(b.name||\"\")))}\nfunction renderSections(rows){const buckets={countries:[],regions:[],states_provinces:[],continents:[],world:[]};for(const row of rows){(buckets[sectionKey(row)]||buckets.regions).push(row)}let html=\"\";html+=\"<section class=\\\"catalog-section\\\"><h2>Countries</h2>\"+tableHtml(sortRows(buckets.countries))+\"</section>\";html+=\"<section class=\\\"catalog-section\\\"><h2>Regions</h2>\"+tableHtml(sortRows(buckets.regions))+\"</section>\";html+=\"<section class=\\\"catalog-section\\\"><h2>States / Provinces</h2>\";const stateGroups=new Map();for(const row of buckets.states_provinces){const parent=parentLabel(row);if(!stateGroups.has(parent))stateGroups.set(parent,[]);stateGroups.get(parent).push(row)}const parents=[...stateGroups.keys()].sort((a,b)=>a.localeCompare(b));if(!parents.length){html+=\"<div class=\\\"empty\\\">No state or province packs available.</div>\"}else{for(const parent of parents){html+=\"<h3 class=\\\"subsection-title\\\">\"+esc(parent)+\"</h3>\"+tableHtml(sortRows(stateGroups.get(parent)||[]))}}html+=\"</section>\";html+=\"<section class=\\\"catalog-section\\\"><h2>Continents</h2>\"+tableHtml(sortRows(buckets.continents))+\"</section>\";html+=\"<section class=\\\"catalog-section\\\"><h2>World</h2>\"+tableHtml(sortRows(buckets.world))+\"</section>\";return html}\nlet ROWS=[];\nfunction render(){const filter=String(document.getElementById(\"filter\").value||\"\").trim().toLowerCase();let rows=ROWS;if(filter){rows=ROWS.filter((row)=>String(row.name||\"\").toLowerCase().includes(filter)||String(row.group_label||\"\").toLowerCase().includes(filter)||String(row.id||\"\").toLowerCase().includes(filter)||parentLabel(row).toLowerCase().includes(filter))}document.getElementById(\"catalog\").innerHTML=renderSections(rows);document.getElementById(\"count\").textContent=rows.length+\" data packs\"}\nasync function init(){try{const res=await fetch(\"/credits/region-pack-catalog-asset?v=\"+encodeURIComponent(String(DATA.map_asset_revision||DATA.catalog_version||Date.now())),{cache:\"force-cache\"});if(!res.ok)throw new Error(\"catalog_asset_\"+res.status);const data=await res.json();ROWS=(data.products||[]).map(computeProduct);document.getElementById(\"filter\").addEventListener(\"input\",render);render()}catch(error){console.warn(\"Planetka catalog failed\",error);document.getElementById(\"count\").className=\"error small\";document.getElementById(\"count\").textContent=\"Data-pack catalog failed to load.\"}}\ninit();" }],
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
        gross_cents: generatedTileGrossCents(parsed.key),
      };
    })
    .filter(Boolean);
}

function regionPackStaticMapPayload(product, token, account, ownedRows, options = {}) {
  const success = options && options.success && typeof options.success === "object" ? options.success : null;
  const pricingSettings = activePricingSettings();
  return {
    ok: true,
    static_asset_mode: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
    price_coefficient: fullQualityPriceCoefficient(),
    region_pack_discount_min_percent: Number(pricingSettings.region_pack_discount_min_percent || 0),
    region_pack_discount_max_percent: Number(pricingSettings.region_pack_discount_max_percent || 0),
    product_discount_overrides: pricingSettings.product_discount_overrides || {},
    token: String(token || ""),
    catalog_mode: Boolean(options && options.catalogMode),
    asset_id: String(product && product.id || ""),
    region_pack: regionProductPublicPayload(product),
    similar_pack_ids: relatedRegionProducts(product, 6)
      .map((candidate) => String(candidate && candidate.id || "").trim())
      .filter(Boolean),
    owned_tiles: ownedTilePayloadRows(ownedRows),
    world_full_quality_unlocked: isWorldFullQualityUnlocked(account),
    title_prefix: String(options && options.titlePrefix || success && success.context_title_prefix || "").trim(),
    success,
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

function pointRegionOfferTileKey(latitudeDeg, longitudeDeg) {
  const lon = clampNumber(longitudeDeg, -180.0, 180.0);
  const lat = clampNumber(latitudeDeg, -90.0, 90.0);
  const x = Math.max(0, Math.min(359, Math.floor(lon + 180.0)));
  const y = Math.max(0, Math.min(179, Math.floor(lat + 90.0)));
  return regionTileKey(x, y, 1, 1);
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
  if (inOutlines !== null) {
    return inOutlines;
  }
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "country" || type === "admin_region") {
    // Some countries span the antimeridian and have huge bboxes. The generated
    // z001 membership is cheap and avoids offering distant country packs.
    return regionProductContainsGeneratedTileKey(product, pointRegionOfferTileKey(lat, lon), {});
  }
  return true;
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

function relatedSimilarRegionProducts(product, limit = 3) {
  const currentRank = regionProductRank(product);
  const currentId = String(product && product.id || "").trim();
  const currentBbox = product && product.bbox || [];
  const currentIsCountryOption = isCountryOptionRegionProduct(product) && currentRank !== 3;
  if (!currentId || (!currentIsCountryOption && currentRank !== 1) || !Array.isArray(currentBbox) || currentBbox.length < 4) {
    return [];
  }
  const footprintCache = {};
  const matches = REGION_PRODUCTS
    .filter((candidate) => {
      const candidateId = String(candidate && candidate.id || "").trim();
      if (!candidateId || candidateId === currentId || isHiddenRegionProduct(candidate)) {
        return false;
      }
      if (currentIsCountryOption) {
        return isCountryOptionRegionProduct(candidate)
          && regionProductsShareZ001Footprint(product, candidate, footprintCache);
      }
      if (regionProductRank(candidate) !== currentRank) {
        return false;
      }
      const candidateBbox = candidate && candidate.bbox || [];
      if (
        bboxLongitudeSpanDegrees(candidateBbox) >= 180.0
        && !regionProductsShareZ001Footprint(product, candidate, footprintCache)
      ) {
        return false;
      }
      const distance = bboxDistanceDegrees(currentBbox, candidateBbox);
      return Number.isFinite(distance) && distance <= REGION_SIMILAR_COUNTRY_MAX_DISTANCE_DEG;
    })
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

function relatedRegionProducts(product, limit = 6) {
  const currentRank = regionProductRank(product);
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
  const similarLimit = currentRank === 1 || isCountryOptionPage ? 0 : 3;
  for (const candidate of relatedSimilarRegionProducts(product, similarLimit)) {
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
  if (currentRank === 1 || isCountryOptionPage) {
    return result;
  }
  if (includedAreas.length || includedCountries.length) {
    return result;
  }
  return result.slice(0, Math.max(0, Number.parseInt(limit, 10) || 6));
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
  return relatedRegionProducts(baseProduct, 12)
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
  const useCache = Boolean(productId) && (!seenProductIds || seenProductIds.size === 0);
  if (useCache && REGION_PRODUCT_TILE_KEYS_CACHE.has(productId)) {
    return REGION_PRODUCT_TILE_KEYS_CACHE.get(productId).slice();
  }
  const finish = (keys) => {
    const safeKeys = normalizeTileKeys(keys || []);
    if (useCache) {
      REGION_PRODUCT_TILE_KEYS_CACHE.set(productId, safeKeys);
    }
    return safeKeys.slice();
  };
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
    return finish(keys);
  }
  if (Array.isArray(generatedKeys) && generatedKeys.length) {
    return finish(generatedKeys);
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
  return finish(keys);
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

function regionProductSortedTileKeys(product) {
  const productId = String(product && product.id || "").trim();
  if (productId && REGION_PRODUCT_SORTED_TILE_KEYS_CACHE.has(productId)) {
    return REGION_PRODUCT_SORTED_TILE_KEYS_CACHE.get(productId).slice();
  }
  const keys = regionProductTileKeys(product).sort(compareRegionTileKeys);
  if (productId) {
    REGION_PRODUCT_SORTED_TILE_KEYS_CACHE.set(productId, keys);
  }
  return keys.slice();
}

function safeOwnedEntriesForFamily(ownedByFamily, family) {
  const source = ownedByFamily instanceof Map ? ownedByFamily.get(family) : [];
  return Array.isArray(source)
    ? source.map((entry) => ({
      key: normalizeTileKey(entry && entry.key),
      d: Number(entry && entry.d),
      value: generatedTileGrossCents(entry && entry.key),
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
    if (previouslyCovered && !globallyFree) {
      alreadyLicencedCount += 1;
      alreadyLicencedGrossCents += grossCentsForTile;
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

function regionProductStaticModel(product) {
  if (!product || typeof product !== "object") {
    return null;
  }
  const productId = String(product.id || "").trim();
  const cacheKey = `${productId || "anon"}|${fullQualityPriceCoefficient().toFixed(6)}`;
  if (productId && REGION_PRODUCT_STATIC_MODEL_CACHE.has(cacheKey)) {
    return REGION_PRODUCT_STATIC_MODEL_CACHE.get(cacheKey);
  }

  const rows = [];
  const familyRows = new Map();
  for (const tileKey of regionProductSortedTileKeys(product)) {
    const parsed = parseTileKey(tileKey);
    const family = tileFamilyKey(parsed);
    if (!parsed || !family) {
      continue;
    }
    const grossCents = generatedTileGrossCents(tileKey);
    const row = {
      key: tileKey,
      parsed,
      family,
      gross_cents: grossCents,
      base_gross_cents: generatedTileBaseGrossCents(tileKey),
      globally_free: Boolean(isFreeCreditTileKey(tileKey) || grossCents <= 0),
    };
    rows.push(row);
    if (!familyRows.has(family)) {
      familyRows.set(family, []);
    }
    familyRows.get(family).push(row);
  }

  const families = [];
  let grossCents = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;
  for (const [family, familyTileRows] of familyRows.entries()) {
    const staticEstimate = estimateRegionPackFamilyRows(familyTileRows, []);
    grossCents += staticEstimate.gross_cents;
    paidTileCount += staticEstimate.paid_tile_count;
    freeTileCount += staticEstimate.free_tile_count;
    families.push({
      family,
      rows: familyTileRows,
      static_gross_cents: staticEstimate.gross_cents,
      static_paid_tile_count: staticEstimate.paid_tile_count,
      static_free_tile_count: staticEstimate.free_tile_count,
      static_already_licenced_count: staticEstimate.already_licenced_count,
      static_already_licenced_gross_cents: staticEstimate.already_licenced_gross_cents,
    });
  }

  const model = {
    product_id: productId,
    coefficient: fullQualityPriceCoefficient(),
    rows,
    families,
    gross_cents: Math.max(0, Number.parseInt(grossCents || 0, 10) || 0),
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: rows.length,
  };
  if (productId) {
    REGION_PRODUCT_STATIC_MODEL_CACHE.set(cacheKey, model);
  }
  return model;
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

function estimateRegionPackSummaryWithOwned(product, account, ownedByFamily, options = {}) {
  const summary = regionProductPricingSummary(product);
  if (!summary) {
    return { error: "missing_region_pack_summary" };
  }
  const discountPercent = regionProductDiscountPercent(product);
  const productId = String(product && product.id || "").trim().toLowerCase();
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
  if (productId === "world") {
    let alreadyLicencedCount = 0;
    let partialLicenceCount = 0;
    let alreadyLicencedGrossCents = 0;
    let partialLicenceCreditCents = 0;
    if (ownedByFamily instanceof Map && ownedByFamily.size > 0) {
      for (const [family, ownedEntries] of ownedByFamily.entries()) {
        const entries = safeOwnedEntriesForFamily(ownedByFamily, family);
        if (!entries.length) {
          continue;
        }
        const parsed = parseTileKey(entries[0].key);
        const paidDLevels = paidDLevelsForRegionZ(parsed && parsed.z);
        const paidD = paidDLevels.length ? paidDLevels[0] : 0;
        if (!parsed || !paidD) {
          continue;
        }
        const worldTileKey = regionTileKey(parsed.x, parsed.y, parsed.z, paidD);
        const worldTileGrossCents = generatedTileGrossCents(worldTileKey);
        if (worldTileGrossCents <= 0) {
          continue;
        }
        let fullCoverage = false;
        let partialCreditCents = 0;
        for (const entry of entries) {
          if (Number(entry.d) <= paidD) {
            fullCoverage = true;
            partialCreditCents = worldTileGrossCents;
            break;
          }
          if (Number(entry.d) > paidD) {
            partialCreditCents = Math.max(partialCreditCents, Math.min(worldTileGrossCents, Number(entry.value || 0) || 0));
          }
        }
        if (fullCoverage) {
          alreadyLicencedCount += 1;
          alreadyLicencedGrossCents += worldTileGrossCents;
        } else if (partialCreditCents > 0) {
          partialLicenceCount += 1;
          partialLicenceCreditCents += Math.max(0, Math.min(worldTileGrossCents, partialCreditCents));
        }
      }
    }
    const totalGrossCents = Math.max(0, Number.parseInt(summary.gross_cents || 0, 10) || 0);
    const grossCents = Math.max(0, totalGrossCents - alreadyLicencedGrossCents - partialLicenceCreditCents);
    const grossEur = normalizeCreditAmount(grossCents / 100.0);
    const amounts = discountedRegionPackAmount(grossEur, discountPercent);
    const alreadyLicencedGrossEur = normalizeCreditAmount(alreadyLicencedGrossCents / 100.0);
    const alreadyLicencedAmounts = discountedRegionPackAmount(alreadyLicencedGrossEur, discountPercent);
    const chargedTileCount = Math.max(0, summary.paid_tile_count - alreadyLicencedCount);
    return {
      ok: true,
      summary_estimate: true,
      static_catalog_estimate: true,
      world_summary_estimate: true,
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
      paid_tile_count: chargedTileCount,
      free_tile_count: summary.free_tile_count,
      tile_count: summary.tile_count,
      unlicenced_tile_count: Math.max(0, summary.tile_count - alreadyLicencedCount),
      charged_tile_count: chargedTileCount,
      new_tile_count: chargedTileCount,
      already_licenced_tile_count: alreadyLicencedCount,
      partial_licence_tile_count: partialLicenceCount,
      partial_licence_credit_eur: normalizeCreditAmount(partialLicenceCreditCents / 100.0),
      new_tiles: [],
      excluded_tiles: new Array(alreadyLicencedCount).fill(null),
      integrity_warnings: [],
      metadata_missing_tile_keys: [],
      tiles: [],
    };
  }
  if (!(ownedByFamily instanceof Map) || ownedByFamily.size <= 0) {
    const amounts = discountedRegionPackAmount(summary.gross_eur, discountPercent);
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
      gross_price_eur: amounts.gross,
      discount_eur: amounts.discount,
      already_licenced_gross_eur: 0,
      already_licenced_saving_eur: 0,
      credits: amounts.price,
      price_eur: amounts.price,
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
  const model = regionProductStaticModel(product);
  if (!model) {
    return { error: "missing_region_pack_static_model" };
  }
  let alreadyLicencedCount = 0;
  let grossCents = 0;
  let alreadyLicencedGrossCents = 0;
  let partialLicenceCount = 0;
  let partialLicenceCreditCents = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;

  for (const familyModel of model.families || []) {
    const family = String(familyModel && familyModel.family || "");
    const ownedEntries = safeOwnedEntriesForFamily(ownedByFamily, family);
    if (!ownedEntries.length) {
      grossCents += Math.max(0, Number.parseInt(familyModel && familyModel.static_gross_cents || 0, 10) || 0);
      paidTileCount += Math.max(0, Number.parseInt(familyModel && familyModel.static_paid_tile_count || 0, 10) || 0);
      freeTileCount += Math.max(0, Number.parseInt(familyModel && familyModel.static_free_tile_count || 0, 10) || 0);
      continue;
    }
    const familyEstimate = estimateRegionPackFamilyRows(familyModel.rows, ownedEntries);
    grossCents += familyEstimate.gross_cents;
    alreadyLicencedCount += familyEstimate.already_licenced_count;
    alreadyLicencedGrossCents += familyEstimate.already_licenced_gross_cents;
    partialLicenceCount += Math.max(0, Number.parseInt(familyEstimate.partial_licence_count || 0, 10) || 0);
    partialLicenceCreditCents += Math.max(0, Number.parseInt(familyEstimate.partial_licence_credit_cents || 0, 10) || 0);
    paidTileCount += familyEstimate.paid_tile_count;
    freeTileCount += familyEstimate.free_tile_count;
  }

  const grossEur = normalizeCreditAmount(grossCents / 100.0);
  const amounts = discountedRegionPackAmount(grossEur, discountPercent);
  const alreadyLicencedGrossEur = normalizeCreditAmount(alreadyLicencedGrossCents / 100.0);
  const alreadyLicencedAmounts = discountedRegionPackAmount(alreadyLicencedGrossEur, discountPercent);
  const newLicensableCount = paidTileCount;
  const unlicencedTileCount = Math.max(0, summary.tile_count - alreadyLicencedCount);
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
    unlicenced_tile_count: unlicencedTileCount,
    charged_tile_count: newLicensableCount,
    new_tile_count: newLicensableCount,
    partial_licence_tile_count: partialLicenceCount,
    partial_licence_credit_eur: normalizeCreditAmount(partialLicenceCreditCents / 100.0),
    new_tiles: [],
    excluded_tiles: new Array(alreadyLicencedCount).fill(null),
    integrity_warnings: [],
    metadata_missing_tile_keys: [],
    tiles: [],
  };
}

async function estimateRegionPackSummary(db, userId, product, deps) {
  await deps.ensureCreditTables(db);
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  const ownedSummary = await ownedEntitlementSummaryForUser(db, userId, deps, { account });
  return estimateRegionPackSummaryWithOwned(
    product,
    account,
    ownedSummary.ownedByFamily,
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
  const discountPercent = regionProductDiscountPercent(product);
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
    partial_licence_tile_count: Math.max(0, Number.parseInt(gross && gross.partial_licence_tile_count || 0, 10) || 0),
    partial_licence_credit_eur: normalizeCreditAmount(gross && gross.partial_licence_credit_eur),
    credits: priceEur,
    price_eur: priceEur,
    paid_tile_count: Math.max(0, Number.parseInt(gross && gross.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(gross && gross.free_tile_count || 0, 10) || 0),
    tile_count: Math.max(0, Number.parseInt(gross && gross.tile_count || 0, 10) || 0),
    unlicenced_tile_count: estimateUnlicencedTileCount(gross),
    charged_tile_count: Array.isArray(gross && gross.new_tiles) ? gross.new_tiles.length : 0,
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
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  if (String(product && product.id || "").trim().toLowerCase() === "world") {
    return estimateRegionPack(db, userId, product, deps, { includeRows: false });
  }

  const ownedRows = await ownedTileRowsForUser(db, userId, deps, { account });
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
  const initiallyOwnedByFamily = new Map();
  for (const [family, entries] of ownedByFamily.entries()) {
    initiallyOwnedByFamily.set(family, Array.isArray(entries) ? entries.map((entry) => ({ ...entry })) : []);
  }

  const worldFullQualityUnlocked = isWorldFullQualityUnlocked(account);
  const tileKeys = regionProductSortedTileKeys(product);

  let credits = 0;
  let paidTileCount = 0;
  let freeTileCount = 0;
  let alreadyLicencedGross = 0;
  let partialLicenceCount = 0;
  let partialLicenceCredit = 0;
  const tiles = [];
  const newTiles = [];
  const excludedTiles = [];

  for (const tileKey of tileKeys) {
    const parsed = parseTileKey(tileKey);
    const family = tileFamilyKey(parsed);
    if (!parsed || !family) {
      continue;
    }
    const baseGrossCents = generatedTileBaseGrossCents(tileKey);
    const grossCents = generatedTileGrossCents(tileKey);
    const grossCredits = normalizeCreditAmount(grossCents / 100.0);
    const globallyFree = Boolean(isFreeCreditTileKey(tileKey) || grossCents <= 0);
    const familyEntitlements = ownedByFamily.get(family) || [];
    if (!ownedByFamily.has(family)) {
      ownedByFamily.set(family, familyEntitlements);
    }
    const initialFamilyEntitlements = initiallyOwnedByFamily.get(family) || [];
    const previouslyCoveredByFiner = Boolean(worldFullQualityUnlocked)
      || initialFamilyEntitlements.some((entry) => Number(entry.d) <= Number(parsed.d));
    const coveredForCharge = Boolean(worldFullQualityUnlocked)
      || familyEntitlements.some((entry) => Number(entry.d) <= Number(parsed.d));
    const coarserCredit = Math.max(
      0,
      ...familyEntitlements
        .filter((entry) => Number(entry.d) > Number(parsed.d))
        .map((entry) => normalizeCreditAmount(entry.value)),
    );
    const initialCoarserCredit = Math.max(
      0,
      ...initialFamilyEntitlements
        .filter((entry) => Number(entry.d) > Number(parsed.d))
        .map((entry) => normalizeCreditAmount(entry.value)),
    );
    const appliedPartialCredit = (!globallyFree && !previouslyCoveredByFiner && !coveredForCharge)
      ? normalizeCreditAmount(Math.min(grossCredits, initialCoarserCredit))
      : 0;
    const tileCredits = (globallyFree || coveredForCharge)
      ? 0
      : normalizeCreditAmount(Math.max(0, grossCredits - coarserCredit));
    const landKm2 = billableLandKm2FromGeneratedGrossCents(tileKey, baseGrossCents);
    const row = {
      tile_key: tileKey,
      credits: tileCredits,
      price_eur: tileCredits,
      gross_credits: grossCredits,
      gross_price_eur: grossCredits,
      land_km2: landKm2,
      billable_land_km2: landKm2,
      already_owned: Boolean(previouslyCoveredByFiner),
      globally_free: Boolean(globallyFree),
      free_reason: globallyFree
        ? (freeReasonForTile(parsed) || "no_billable_land")
        : (previouslyCoveredByFiner ? "already_unlocked" : ""),
    };
    if (appliedPartialCredit > 0) {
      row.upgrade_credit_applied = appliedPartialCredit;
      row.partially_licenced = !globallyFree && !coveredForCharge && tileCredits > 0;
      partialLicenceCount += 1;
      partialLicenceCredit = normalizeCreditAmount(partialLicenceCredit + appliedPartialCredit);
    }
    tiles.push(row);
    if (previouslyCoveredByFiner) {
      excludedTiles.push(row);
      alreadyLicencedGross = normalizeCreditAmount(alreadyLicencedGross + grossCredits);
    }
    if (tileCredits > 0) {
      paidTileCount += 1;
      credits = normalizeCreditAmount(credits + tileCredits);
    } else {
      freeTileCount += 1;
    }
    if (!globallyFree && !coveredForCharge) {
      newTiles.push(row);
      familyEntitlements.push({ key: tileKey, d: Number(parsed.d), value: grossCredits });
    }
  }

  const discountPercent = regionProductDiscountPercent(product);
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
    partial_licence_tile_count: partialLicenceCount,
    partial_licence_credit_eur: partialLicenceCredit,
    credits: amounts.price,
    price_eur: amounts.price,
    paid_tile_count: paidTileCount,
    free_tile_count: freeTileCount,
    tile_count: tiles.length,
    unlicenced_tile_count: Math.max(0, tiles.length - excludedTiles.length),
    charged_tile_count: newTiles.length,
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

function buildRegionPackUpsellCardData(product, estimate, options = {}) {
  const includeTiles = Boolean(options && options.includeTiles !== false);
  const tileRows = includeTiles ? allocatedRegionPackTileRows(estimate) : [];
  const productSummary = regionProductPricingSummary(product) || {};
  const fullPriceEur = normalizeCreditAmount(productSummary.gross_eur);
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
    bounds: regionMapBounds(product, detail, displayTiles.length ? displayTiles : tileRows),
    display_level: displayLevel,
    tiles: displayTiles,
    summary: {
      new_tiles: estimateUnlicencedTileCount(estimate),
      charged_tiles: estimateChargedTileCount(estimate),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
      full_price_eur: fullPriceEur,
      already_licenced_deduction_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
      partial_licence_tiles: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
      partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
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
      new_tiles: estimateUnlicencedTileCount(estimate),
      charged_tiles: estimateChargedTileCount(estimate),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
      already_licenced_saving_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
      already_licenced_deduction_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
      partial_licence_tiles: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
      partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
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

function regionProductTileFamilySet(product, cache = {}) {
  const productId = String(product && product.id || "").trim();
  if (!productId) {
    return new Set();
  }
  if (!cache.tileFamilySets) {
    cache.tileFamilySets = new Map();
  }
  if (cache.tileFamilySets.has(productId)) {
    return cache.tileFamilySets.get(productId);
  }
  const families = new Set();
  for (const key of regionProductTileKeys(product)) {
    const family = tileFamilyKey(parseTileKey(key));
    if (family) {
      families.add(family);
    }
  }
  cache.tileFamilySets.set(productId, families);
  return families;
}

function regionProductContainsTileFootprint(product, tileKey, cache = {}) {
  const key = normalizeTileKey(tileKey);
  const parsed = parseTileKey(key);
  const family = tileFamilyKey(parsed);
  if (!product || !key || !parsed || !family) {
    return false;
  }
  if (regionProductContainsGeneratedTileKey(product, key, cache)) {
    return true;
  }
  return regionProductTileFamilySet(product, cache).has(family);
}

function regionProductContainsAllTileFootprints(product, tileKeys, cache = {}) {
  const keys = normalizeTileKeys(tileKeys);
  if (!keys.length || !product || isHiddenRegionProduct(product)) {
    return false;
  }
  if (String(product && product.id || "").trim().toLowerCase() === "world") {
    return true;
  }
  for (const key of keys) {
    if (!regionProductContainsTileFootprint(product, key, cache)) {
      return false;
    }
  }
  return true;
}

function sceneSuccessCandidateProductsForTileKeys(tileKeys) {
  const keys = normalizeTileKeys(tileKeys);
  if (!keys.length) {
    return [];
  }
  const cache = {};
  return REGION_PRODUCTS
    .filter((product) => {
      const rank = regionProductRank(product);
      return rank > 0
        && rank < 4
        && !isHiddenRegionProduct(product)
        && regionProductContainsAllTileFootprints(product, keys, cache);
    })
    .sort((a, b) => (
      regionProductRank(a) - regionProductRank(b)
      || productSpecificityScore(a) - productSpecificityScore(b)
      || bboxArea(a) - bboxArea(b)
      || regionProductTileKeys(a).length - regionProductTileKeys(b).length
      || String(a.name || "").localeCompare(String(b.name || ""))
    ));
}

function sceneSuccessContextProduct(tileKeys, fallbackRows = []) {
  const containingProducts = sceneSuccessCandidateProductsForTileKeys(tileKeys);
  if (containingProducts.length) {
    return containingProducts[0];
  }
  const center = tileRowsCenter(fallbackRows);
  const fallbackProducts = center
    ? suggestedRegionProductsForContext(center.latitude_deg, center.longitude_deg, tileKeys)
    : [];
  return fallbackProducts.length ? fallbackProducts[0] : null;
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
  const partialLicenceCredit = normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur);
  const partialLicenceCount = Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0);
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
      new_tiles: estimateUnlicencedTileCount(estimate),
      charged_tiles: estimateChargedTileCount(estimate),
      total_tiles: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
      already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
      partial_licence_tiles: partialLicenceCount,
      partial_licence_credit_eur: partialLicenceCredit,
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

function regionPackOfferPayload(product, estimate) {
  const priceEur = normalizeCreditAmount(estimate && estimate.price_eur);
  const chargedTileCount = estimateChargedTileCount(estimate);
  const newTileCount = estimateUnlicencedTileCount(estimate);
  return {
    ok: true,
    ...regionProductPublicPayload(product),
    gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
    gross_price_eur: normalizeCreditAmount(estimate && estimate.gross_price_eur),
    discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
    already_licenced_gross_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
    already_licenced_saving_eur: normalizeCreditAmount(estimate && estimate.already_licenced_saving_eur),
    partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
    partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
    credits: normalizeCreditAmount(estimate && estimate.credits),
    price_eur: priceEur,
    paid_tile_count: Math.max(0, Number.parseInt(estimate && estimate.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(estimate && estimate.free_tile_count || 0, 10) || 0),
    tile_count: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
    unlicenced_tile_count: newTileCount,
    new_tile_count: newTileCount,
    charged_tile_count: chargedTileCount,
    already_licenced_tile_count: Math.max(0, Number.parseInt(estimate && estimate.excluded_tiles && estimate.excluded_tiles.length || 0, 10) || 0),
    metadata_missing_tile_keys: Array.isArray(estimate && estimate.metadata_missing_tile_keys)
      ? estimate.metadata_missing_tile_keys.slice(0, 100)
      : [],
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
  const already = Array.isArray(estimate && estimate.excluded_tiles)
    ? estimate.excluded_tiles.length
    : Math.max(0, Number.parseInt(estimate && estimate.already_licenced_tile_count || 0, 10) || 0);
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
    new_tiles: estimateUnlicencedTileCount(estimate),
    unlicenced_tile_count: estimateUnlicencedTileCount(estimate),
    charged_tiles: estimateChargedTileCount(estimate),
    already_licenced_tiles: Math.max(0, Array.isArray(estimate && estimate.excluded_tiles) ? estimate.excluded_tiles.length : 0),
    full_price_eur: normalizeCreditAmount(productSummary.gross_eur),
    chargeable_full_price_eur: normalizeCreditAmount(estimate && estimate.gross_eur),
    already_licenced_saving_eur: normalizeCreditAmount(estimate && estimate.already_licenced_saving_eur),
    discount_percent: Math.max(0, Number.parseInt(estimate && estimate.discount_percent || regionProductDiscountPercent(product), 10) || 0),
    discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur),
    price_eur: normalizeCreditAmount(estimate && estimate.price_eur),
  };
}

async function buildRegionPackCatalogData(db, userId, token, deps) {
  await deps.ensureCreditTables(db);
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
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
  cacheDetailToken("region_pack", token, {
    token,
    user_id: String(userId || "").trim(),
    region_pack_id: String(regionPackId || "").trim(),
    created_at: now,
    expires_at: expiresAt,
  });
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
  cacheDetailToken("scene", token, {
    token,
    user_id: String(userId || "").trim(),
    tile_keys_json: JSON.stringify(keys),
    created_at: now,
    expires_at: expiresAt,
  });
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
  const partialLicenceTiles = Math.max(0, Number.parseInt(summary.partial_licence_tiles ?? summary.partial_licence_tile_count ?? 0, 10) || 0);
  const partialLicenceCreditEur = Number(summary.partial_licence_credit_eur || 0);
  const alreadyLicencedTiles = Math.max(0, Number.parseInt(summary.already_licenced_tiles || 0, 10) || 0) + partialLicenceTiles;
  const alreadyLicencedDeductionEur = Number(summary.already_licenced_deduction_eur ?? summary.already_licenced_saving_eur ?? 0) + partialLicenceCreditEur;
  const totalTiles = Number(summary.total_tiles || 0);
  const newTiles = Math.max(0, Number(summary.new_tiles || 0) - partialLicenceTiles);
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
	<div class="card final-price"><span>Final Price</span><b>€${Number(summary.price_eur || 0).toFixed(2)}</b>${primaryBuyHref ? `<a class="button buy-now" href="${primaryBuyHref}">${Number(summary.price_eur || 0) > 0 ? "Buy Now" : "Licence Now"}</a>` : ""}</div>
	</section>
<section class="panel">
<div class="toolbar">
<label>Zoom level <select id="levelSelect"></select></label>
<span id="levelSummary" class="muted"></span>
</div>
<p class="muted small">Included zoom levels are part of the Full Quality pack and are required for reliable Planetka rendering across different camera distances.</p>
<svg id="map" role="img" aria-label="${escapeHtmlText(name)} tile map"></svg>
<p class="muted small">Tile prices shown on hover are user-specific: already licenced tiles are €0.00; partially licenced tiles show only the remaining upgrade price.</p>
<div class="legend">
<span><i class="swatch new"></i>New in this pack</span>
<span><i class="swatch partial"></i>Partially licenced</span>
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
<h2>Similar Options</h2>
<div id="upsellGrid" class="upsells"></div>
</section>` : ""}
<section class="panel">
<a class="button secondary" href="/credits/region-pack-catalog?token=${tokenParam}">View all Full Quality data packs</a>
</section>
</main>
<script>window.PLANETKA_REGION_PACK_DATA=${payload};</script>
<script src="/credits/page-assets/region-pack-dynamic-map.js?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}" defer></script>
</body>
</html>`;
}

function regionPackStaticMapHtml(data) {
  const pack = data && data.region_pack || {};
  const name = String(pack.name || "Region Pack").trim() || "Region Pack";
  const success = data && data.success && typeof data.success === "object" ? data.success : null;
  const titlePrefix = String(data && data.title_prefix || success && success.context_title_prefix || "").trim();
  const pageTitle = `${titlePrefix ? `${titlePrefix}: ` : ""}${name} Full Quality Pack`;
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
<label>Zoom level <select id="levelSelect"></select></label>
<span id="levelSummary" class="muted"></span>
</div>
<p class="muted small">Included zoom levels are part of the Full Quality pack and are required for reliable Planetka rendering across different camera distances.</p>
<svg id="map" role="img" aria-label="${escapeHtmlText(name)} tile map"></svg>
<p class="muted small">Tile prices shown on hover are user-specific: already licenced tiles are €0.00; partially licenced tiles show only the remaining upgrade price.</p>
<div class="legend">
<span><i class="swatch new"></i>New in this pack</span>
<span><i class="swatch partial"></i>Partially licenced</span>
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
<h2>Similar Options</h2>
<div id="upsellGrid" class="upsells"></div>
</section>
<section class="panel">
<a class="button secondary" href="/credits/region-pack-catalog?token=${escapeHtmlText(encodeURIComponent(String(data && data.token || "")))}">View all Full Quality data packs</a>
</section>
</main>
<script>window.PLANETKA_REGION_PACK_DATA=${payload};</script>
<script src="/credits/page-assets/region-pack-map.js?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}" defer></script>
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
function rowHtml(row){const id=encodeURIComponent(row.id||"");const partialCount=Number(row.partial_licence_tiles??row.partial_licence_tile_count??0);const partial=Number(row.partial_licence_credit_eur||0);const licenced=Number(row.already_licenced_tiles||0)+partialCount;const saving=Number(row.already_licenced_deduction_eur??row.already_licenced_saving_eur??0)+partial;const newTiles=Math.max(0,Number(row.new_tiles||0)-partialCount);const mapLink=String(row.id||"").toLowerCase()==="world"?"":" <a class=\\"button secondary\\" href=\\"/credits/region-pack-map?token="+token+"&region_pack_id="+id+"&catalog=1\\">Map</a>";return "<tr>"
+"<td><b>"+escapeCell(row.name||"Data Pack")+"</b><div class=\\"muted small\\">"+escapeCell(row.group_label||"")+"</div></td>"
+"<td>"+newTiles+" / "+Number(row.total_tiles||0)+"</td>"
+"<td>"+fmt(row.full_price_eur)+"</td>"
+"<td>"+licenced+" tiles <span class=\\"saving\\">(-"+fmt(saving)+")</span></td>"
+"<td>"+Number(row.discount_percent||0)+"% <span class=\\"saving\\">(-"+fmt(row.discount_eur)+")</span></td>"
+"<td class=\\"price\\">"+fmt(row.price_eur)+"</td>"
+"<td><a class=\\"button\\" href=\\"/credits/region-pack-checkout?token="+token+"&region_pack_id="+id+"&catalog=1\\">Buy</a>"+mapLink+"</td>"
+"</tr>"}
function escapeCell(value){return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function render(){const filter=String(document.getElementById("filter").value||"").trim().toLowerCase();let shown=0;const html=(DATA.groups||[]).map(group=>{const rows=(group.rows||[]).filter(row=>!filter||String(row.name||"").toLowerCase().includes(filter));if(!rows.length)return "";shown+=rows.length;return "<h2>"+escapeCell(group.label)+"</h2><table><thead><tr><th>Data Pack</th><th>New Tiles / Total Tiles</th><th>Full Price</th><th>Already Licenced</th><th>Volume Discount</th><th>Final Price</th><th>Actions</th></tr></thead><tbody>"+rows.map(rowHtml).join("")+"</tbody></table>"}).join("");document.getElementById("catalog").innerHTML=html||"<div class=\\"empty\\">No data packs match this search.</div>";document.getElementById("count").textContent=shown+" data packs";}document.getElementById("filter").addEventListener("input",render);render();
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
<link rel="stylesheet" href="/credits/page-assets/region-pack-catalog.css?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}">
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
<script>window.PLANETKA_REGION_PACK_DATA=${payload};</script>
<script src="/credits/page-assets/region-pack-catalog.js?v=${encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION)}" defer></script>
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
  let account = await deps.dbGet(db, `SELECT * FROM user_credit_accounts WHERE user_id = ? LIMIT 1`, [safeUserId]);
  if (!account) {
    await deps.dbRun(
      db,
      `
        INSERT OR IGNORE INTO user_credit_accounts (
          user_id, account_type, created_at, updated_at
        )
        VALUES (?, 'standard', ?, ?)
      `,
      [safeUserId, now, now],
    );
    account = await deps.dbGet(db, `SELECT * FROM user_credit_accounts WHERE user_id = ? LIMIT 1`, [safeUserId]);
  } else if (String(account && account.account_type || "").trim().toLowerCase() !== "standard") {
    await deps.dbRun(
      db,
      `
        UPDATE user_credit_accounts
        SET account_type = 'standard',
            pricing_version = COALESCE(pricing_version, 0) + 1,
            updated_at = ?
        WHERE user_id = ?
      `,
      [now, safeUserId],
    );
    account = await deps.dbGet(db, `SELECT * FROM user_credit_accounts WHERE user_id = ? LIMIT 1`, [safeUserId]);
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
  const ownedSummary = await ownedEntitlementSummaryForUser(db, userId, deps, { account });
  const familyEntries = ownedSummary.ownedByFamily.get(family) || [];
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
  if (safeMode === "balanced") {
    return {
      error: "unsupported_quality_mode",
      message: "Only Preview and Full Quality are available.",
    };
  }
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
  const familySet = new Set(familyList);
  const ownedSummary = await ownedEntitlementSummaryForUser(db, userId, deps, { account });
  const rows = (ownedSummary.rows || []).filter((row) => {
    const owned = parseTileKey(row && row.tile_key || "");
    return familySet.has(tileFamilyKey(owned));
  });
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

export async function unlockTilesForSession(db, userId, qualityMode, tileKeys, resolveId, deps) {
  const safeMode = deps.normalizeQualityMode(qualityMode || "");
  if (safeMode === "balanced") {
    return {
      error: "unsupported_quality_mode",
      message: "Only Preview and Full Quality are available.",
    };
  }
  if (safeMode === "preview") {
    return { credits: 0, paid_tile_count: 0, free_tile_count: 0, tile_count: 0 };
  }
  const safeUserId = String(userId || "").trim();
  const estimate = await estimateNewCredits(db, safeUserId, tileKeys, safeMode, deps);
  if (estimate && estimate.error === "credit_pricing_missing_tile_stats") {
    return estimate;
  }
  const requiredCredits = normalizeCreditAmount(estimate.credits);
  if (requiredCredits > 0) {
    return {
      error: "payment_required",
      required_credits: requiredCredits,
      price_eur: requiredCredits,
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

export async function grantPaidSceneTileEntitlements(db, userId, qualityMode, tileKeys, resolveId, amountPaidEur, deps, userEmail = "", stripePaymentIntentId = "") {
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
    const existingLedger = await deps.dbGet(
      db,
      `
        SELECT COUNT(*) AS count
        FROM credit_ledger
        WHERE user_id = ?
          AND LOWER(COALESCE(reason, '')) = 'stripe_scene_purchase'
          AND json_valid(COALESCE(metadata_json, ''))
          AND COALESCE(json_extract(metadata_json, '$.stripe_session_id'), '') = ?
      `,
      [safeUserId, safeResolveId],
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
        id, user_id, amount_eur, reason, metadata_json, created_at
      )
      VALUES (?, ?, ?, 'stripe_scene_purchase', ?, ?)
    `,
    [
      deps.randomToken(16),
      safeUserId,
      normalizeCreditAmount(amountPaidEur),
      JSON.stringify({
        stripe_session_id: String(resolveId || ""),
        stripe_payment_intent_id: String(stripePaymentIntentId || "").trim(),
        resolve_id: String(resolveId || ""),
        quality_mode: safeMode,
        tile_count: insertedTiles.length,
        tile_count_total: Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0),
        tile_count_new: insertedTiles.length,
        tile_count_already_licenced: alreadyLicencedCount,
        partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
        partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
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
        partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
        partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
      },
      created_at: now,
    },
    deps,
  );
  if (insertedTiles.length > 0) {
    await touchUserPricingVersion(db, safeUserId, deps, now);
  }
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
  const discountPercent = regionProductDiscountPercent(product);
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
	          pricing_version = COALESCE(pricing_version, 0) + 1,
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
            already_licenced_gross_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
            partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
            partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
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
          already_licenced_gross_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
          partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
          partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
          world_full_quality_unlocked: true,
        },
        created_at: now,
      },
      deps,
    );
    invalidateUserPricingCaches(safeUserId);
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
          tile_count_new: estimateNewTiles,
          tile_count_already_licenced: alreadyLicencedTiles,
          already_licenced_gross_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
          partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
          partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
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
        already_licenced_gross_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
        partial_licence_tile_count: Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0),
        partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
      },
      created_at: now,
    },
    deps,
  );
  if (insertedTiles.length > 0) {
    await touchUserPricingVersion(db, safeUserId, deps, now);
  }
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

  if (!["scene", "region_pack", "broader_pack"].includes(option)) {
    return deps.json(
      {
        ok: false,
        error: "unsupported_checkout_option",
        message: "Planetka supports direct payment for Full Quality scenes and data packs only.",
      },
      400,
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
    // Keep the Blender JSON endpoint lightweight. The browser payment page is
    // authoritative and recalculates current user-specific price/payment choices.
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
        message: "This scene price is below Stripe's minimum checkout amount. Please choose a larger Full Quality scene or data pack.",
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
  if (qualityMode === "balanced") {
    return deps.json(
      {
        ok: false,
        error: "unsupported_quality_mode",
        message: "Only Preview and Full Quality are available.",
      },
      410,
      env,
    );
  }
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
  const response = deps.json(
    {
      ok: true,
      ...estimate,
      credits: estimate.credits,
      price_eur: normalizeCreditAmount(estimate.credits),
      paid_tile_count: estimate.paid_tile_count,
      free_tile_count: estimate.free_tile_count,
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
    price_eur: normalizeCreditAmount(estimate && estimate.credits),
  });
}

export async function handleCreditRegionOffers(request, env, deps) {
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
  const products = suggestedRegionProductsForContext(latitude, longitude, tileKeys);
  timing.mark("products");
  const ownedSummary = await ownedEntitlementSummaryForUser(db, auth.user.id, deps, { account });
  const ownedByFamily = ownedSummary.ownedByFamily;
  timing.mark(ownedSummary.cache_hit ? "entitlements_cache" : "entitlements_d1");
  const offers = [];
  for (const product of products) {
    const estimate = estimateRegionPackSummaryWithOwned(product, account, ownedByFamily);
    if (estimate && estimate.error) {
      offers.push({
        ok: false,
        ...regionProductPublicPayload(product),
        error: String(estimate.error || "region_pack_estimate_failed"),
      });
      continue;
    }
    const priceEur = normalizeCreditAmount(estimate && estimate.price_eur);
    const chargedTileCount = estimateChargedTileCount(estimate);
    if (priceEur <= 0 && chargedTileCount <= 0) {
      continue;
    }
    offers.push(regionPackOfferPayload(product, estimate));
  }
  timing.mark("estimate");
  const payload = {
    ok: true,
    catalog_version: REGION_PACK_CATALOG_VERSION,
    latitude_deg: latitude,
    longitude_deg: longitude,
    offers,
    server_cache_hit: false,
  };
  boundedCacheSet(
    REGION_OFFERS_RESPONSE_CACHE,
    cacheKey,
    {
      payload,
      cached_at_ms: nowMs,
    },
    REGION_OFFERS_RESPONSE_CACHE_MAX,
  );
  const response = deps.json(payload, 200, env);
  return withEndpointTiming(response, timing, env, {
    cache_hit: false,
    entitlement_cache_hit: Boolean(ownedSummary.cache_hit),
    product_count: products.length,
    offer_count: offers.length,
  });
}

export async function handleCreditRegionPackRelatedOffers(request, env, deps) {
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
  const products = relatedRegionProducts(product, 6);
  timing.mark("products");
  const ownedSummary = await ownedEntitlementSummaryForUser(db, auth.user.id, deps, { account });
  const ownedByFamily = ownedSummary.ownedByFamily;
  timing.mark(ownedSummary.cache_hit ? "entitlements_cache" : "entitlements_d1");
  const offers = [];
  for (const candidate of products) {
    const estimate = estimateRegionPackSummaryWithOwned(candidate, account, ownedByFamily);
    if (estimate && estimate.error) {
      offers.push({
        ok: false,
        ...regionProductPublicPayload(candidate),
        error: String(estimate.error || "region_pack_estimate_failed"),
      });
      continue;
    }
    const offer = regionPackOfferPayload(candidate, estimate);
    if (normalizeCreditAmount(offer && offer.price_eur) <= 0 && Number(offer && offer.charged_tile_count || 0) <= 0) {
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
    },
    200,
    env,
  );
  return withEndpointTiming(response, timing, env, {
    entitlement_cache_hit: Boolean(ownedSummary.cache_hit),
    product_count: products.length,
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
  const estimate = data && data.estimate || {};
  const account = data && data.account || {};
  const name = String(product && product.name || "Region Pack").trim() || "Region Pack";
  const token = escapeHtmlText(String(data && data.token || ""));
  const regionPackId = escapeHtmlText(String(product && product.id || ""));
  const catalogInput = data && data.catalog_mode ? `<input type="hidden" name="catalog" value="1">` : "";
  const catalogParam = data && data.catalog_mode ? "&catalog=1" : "";
  const mapHref = `/credits/region-pack-map?token=${escapeHtmlText(encodeURIComponent(String(data && data.token || "")))}&region_pack_id=${escapeHtmlText(encodeURIComponent(String(product && product.id || "")))}${catalogParam}`;
  const priceEur = normalizeCreditAmount(estimate && estimate.price_eur);
  const fullPriceEur = normalizeCreditAmount(regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur);
  const alreadyLicencedDeductionEur = normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur);
  const partialLicenceCount = Math.max(0, Number.parseInt(estimate && estimate.partial_licence_tile_count || 0, 10) || 0);
  const partialLicenceCreditEur = normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur);
  const displayedAlreadyLicencedCount = Math.max(0, Number.parseInt(estimate && estimate.excluded_tiles && estimate.excluded_tiles.length || 0, 10) || 0) + partialLicenceCount;
  const displayedAlreadyLicencedDeductionEur = normalizeCreditAmount(alreadyLicencedDeductionEur + partialLicenceCreditEur);
  const discountEur = normalizeCreditAmount(estimate && estimate.discount_eur);
  const discountPercent = regionProductDiscountPercent(product);
  const unlicencedTileCount = estimateUnlicencedTileCount(estimate);
  const stripeAvailable = centsForEur(priceEur) >= STRIPE_MIN_CHECKOUT_AMOUNT_CENTS;
  const stripeButton = stripeAvailable
    ? `<form method="post" action="/credits/region-pack-checkout"><input type="hidden" name="token" value="${token}"><input type="hidden" name="region_pack_id" value="${regionPackId}">${catalogInput}<input type="hidden" name="method" value="stripe"><button class="button" type="submit">Pay Now (€${priceEur.toFixed(2)})</button></form>`
    : `<button class="button disabled" type="button" disabled>Payment gateway unavailable below €${(STRIPE_MIN_CHECKOUT_AMOUNT_CENTS / 100).toFixed(2)}</button>`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>Planetka ${escapeHtmlText(name)} Payment</title>
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
			<p>Licence this Full Quality data pack with direct payment.</p>
			<div class="summary">
		<div class="card"><span>New Tiles / Total Tiles</span><b>${Math.max(0, unlicencedTileCount - partialLicenceCount)} / ${Math.max(0, Number.parseInt(estimate && estimate.tile_count || 0, 10) || 0)}</b></div>
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
  const timing = createEndpointTimer("credits.region_pack_checkout");
  const { token, requestedRegionId, allowCatalogProduct, method } = await regionPackCheckoutParams(request);
  timing.mark("params");
  const db = deps.requireDb(env);
  const tokenResult = allowCatalogProduct
    ? await getValidAnyDetailToken(db, token, deps)
    : await getValidRegionPackDetailToken(db, token, deps);
  timing.mark("token");
  if (tokenResult.error) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Region Pack</title><h1>This region-pack payment link expired.</h1><p>Please open it again from Blender.</p>",
      tokenResult.status || 400,
      env,
    ), timing, env, { error: tokenResult.error });
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
  timing.mark("product");
  if (productResult.error) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Region pack unavailable.</h1><p>${escapeHtmlText(productResult.error)}</p>`,
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
  const ownedSummary = await ownedEntitlementSummaryForUser(db, userId, deps, { account });
  const ownedByFamily = ownedSummary.ownedByFamily;
  timing.mark(ownedSummary.cache_hit ? "entitlements_cache" : "entitlements_d1");
  const estimate = estimateRegionPackSummaryWithOwned(product, account, ownedByFamily);
  timing.mark("estimate");
  if (estimate && estimate.error) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Region pack estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
      500,
      env,
    ), timing, env, { error: estimate.error, region_pack_id: String(product && product.id || "") });
  }
  const priceEur = normalizeCreditAmount(estimate && estimate.price_eur);
  if (priceEur <= 0) {
    if (estimateChargedTileCount(estimate) <= 0) {
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
        heading: `${String(product.name || "Region Pack")} licence applied`,
        message: "This promotional Full Quality data pack has been licenced at no charge. You can return to Blender.",
        icon: "OK",
        tone: "success",
      }),
      200,
      env,
    );
  }
  const amountCents = centsForEur(priceEur);

  if (method && method !== "stripe") {
    return withEndpointTiming(html(
      regionPackPaymentChoiceHtml({
        token,
        product,
        estimate,
        account,
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
        estimate,
        account,
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
        planetka_price_eur: priceEur.toFixed(2),
        planetka_gross_eur: normalizeCreditAmount(estimate && estimate.gross_eur).toFixed(2),
        planetka_discount_percent: String(regionProductDiscountPercent(product)),
        planetka_discount_eur: normalizeCreditAmount(estimate && estimate.discount_eur).toFixed(2),
        planetka_already_licenced_gross_eur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur).toFixed(2),
        planetka_partial_licence_credit_eur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur).toFixed(2),
        planetka_checkout_source: allowCatalogProduct ? "region_pack_catalog" : "region_pack_map_upsell",
      },
    },
    deps,
  );
  timing.mark("stripe_session");
  if (session.error || !session.checkout_url) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Stripe checkout failed.</h1><p>${escapeHtmlText(session.message || session.error || "checkout_failed")}</p>`,
      502,
      env,
    ), timing, env, { error: session.message || session.error || "checkout_failed", region_pack_id: String(product && product.id || "") });
  }
  return withEndpointTiming(Response.redirect(session.checkout_url, 303), timing, env, {
    region_pack_id: String(product && product.id || ""),
    amount_cents: amountCents,
  });
}

export async function handleCreditRegionPackMap(request, env, deps) {
  const timing = createEndpointTimer("credits.region_pack_map");
  const url = new URL(request.url);
  const token = String(url.searchParams.get("token") || "").trim();
  const allowCatalogProduct = String(url.searchParams.get("catalog") || "") === "1";
  if (!token) {
    return withEndpointTiming(html(
      "<!doctype html><title>Planetka Region Pack</title><h1>Missing region-pack detail token.</h1>",
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
      "<!doctype html><title>Planetka Region Pack</title><h1>This region-pack detail link expired.</h1><p>Please open it again from Blender.</p>",
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
    : resolveRegionPackFromDetailTokenRow(tokenResult.row, requestedRegionId);
  timing.mark("product");
  if (productResult.error) {
    return withEndpointTiming(html(
      `<!doctype html><title>Planetka Region Pack</title><h1>Region pack unavailable.</h1><p>${escapeHtmlText(productResult.error)}</p>`,
      productResult.status || 404,
      env,
    ), timing, env, { error: productResult.error });
  }
  const userId = String(tokenResult.row && tokenResult.row.user_id || "").trim();
  const product = productResult.product;
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  timing.mark("account");
  if (String(product && product.id || "").trim().toLowerCase() === "world") {
    const estimate = await estimateRegionPack(db, userId, product, deps, { includeRows: false });
    timing.mark("estimate");
    if (estimate && estimate.error) {
      return withEndpointTiming(html(
        `<!doctype html><title>Planetka Region Pack</title><h1>Region pack estimate failed.</h1><p>${escapeHtmlText(estimate.error)}</p>`,
        500,
        env,
      ), timing, env, { error: estimate.error, region_pack_id: "world" });
    }
    const safeToken = escapeHtmlText(encodeURIComponent(token));
    const safeRevision = escapeHtmlText(encodeURIComponent(REGION_PACK_MAP_ASSET_REVISION));
    const price = normalizeCreditAmount(estimate && estimate.price_eur);
    const fullPrice = normalizeCreditAmount(regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur);
    const worldBreakdown = fullQualityPriceBreakdownHtml({
      fullPriceEur: fullPrice,
      alreadyLicencedEur: normalizeCreditAmount(estimate && estimate.already_licenced_gross_eur),
      partialLicenceEur: normalizeCreditAmount(estimate && estimate.partial_licence_credit_eur),
      discountPercent: regionProductDiscountPercent(product),
      discountEur: normalizeCreditAmount(estimate && estimate.discount_eur),
      finalPriceEur: price,
    });
    return withEndpointTiming(html(
      `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Planetka World Pack</title><style>:root{color-scheme:dark}body{margin:0;background:#111;color:#eee;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1180px;margin:0 auto;padding:24px}.panel{background:#1b1b1b;border:1px solid #3c3c3c;border-radius:12px;padding:14px;margin-top:14px}.world-map{background:#0d1118;border:1px solid #3c3c3c;border-radius:12px;overflow:hidden;margin:14px 0}.world-map img{display:block;width:100%;height:auto}.button{display:inline-flex;align-items:center;justify-content:center;margin:8px 8px 0 0;padding:9px 12px;border-radius:8px;background:#d9a441;color:#111;text-decoration:none;font-weight:700}.secondary{background:#2a2a2a;color:#eee;border:1px solid #3c3c3c}.muted{color:#aaa}</style></head><body><main><h1>World Full Quality Pack</h1><section class="panel"><p>The World pack includes the complete Full Quality texture dataset.</p><div class="world-map"><img src="/credits/region-pack-map-background.jpg?v=${safeRevision}" alt="World map overview"></div>${worldBreakdown}<a class="button" href="/credits/region-pack-checkout?token=${safeToken}&region_pack_id=world&catalog=1">Buy World (€${price.toFixed(2)})</a><a class="button secondary" href="/credits/region-pack-catalog?token=${safeToken}">Back to all data packs</a></section></main></body></html>`,
      200,
      env,
    ), timing, env, { region_pack_id: "world", price_eur: price });
  }
  const ownedSummary = await ownedEntitlementSummaryForUser(db, userId, deps, { account });
  timing.mark(ownedSummary.cache_hit ? "entitlements_cache" : "entitlements_d1");
  const data = regionPackStaticMapPayload(product, token, account, ownedSummary.rows, { catalogMode: allowCatalogProduct });
  timing.mark("payload");
  return withEndpointTiming(html(regionPackStaticMapHtml(data), 200, env), timing, env, {
    region_pack_id: String(product && product.id || ""),
    entitlement_cache_hit: Boolean(ownedSummary.cache_hit),
  });
}

export async function handleCreditRegionPackMapAsset(request, env, deps) {
  const timing = createEndpointTimer("credits.region_pack_map_asset");
  const url = new URL(request.url);
  const regionPackId = String(url.searchParams.get("region_pack_id") || url.searchParams.get("id") || "").trim();
  const product = regionProductById(regionPackId);
  if (!product || isHiddenRegionProduct(product) || String(product.id || "").trim().toLowerCase() === "world") {
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

export async function handleCreditRegionPackCatalogAsset(request, env, deps) {
  void request;
  const timing = createEndpointTimer("credits.region_pack_catalog_asset");
  const bucket = env && env.PLANETKA_DATA;
  if (!bucket || typeof bucket.get !== "function") {
    return withEndpointTiming(deps.json({ ok: false, error: "r2_binding_unavailable" }, 500, env), timing, env);
  }
  const object = await bucket.get(regionPackCatalogAssetKey(env));
  timing.mark("r2_get");
  if (!object || !object.body) {
    return withEndpointTiming(deps.json({ ok: false, error: "region_pack_catalog_asset_missing" }, 404, env), timing, env);
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
  const timing = createEndpointTimer("credits.region_pack_catalog");
  const account = await ensureFreshCreditAccountForUser(db, userId, deps);
  timing.mark("account");
  const ownedSummary = await ownedEntitlementSummaryForUser(db, userId, deps, { account });
  timing.mark(ownedSummary.cache_hit ? "entitlements_cache" : "entitlements_d1");
  const pricingSettings = activePricingSettings();
  return withEndpointTiming(html(
    regionPackStaticCatalogHtml({
      ok: true,
      catalog_version: REGION_PACK_CATALOG_VERSION,
      map_asset_revision: REGION_PACK_MAP_ASSET_REVISION,
      price_coefficient: fullQualityPriceCoefficient(),
      region_pack_discount_min_percent: Number(pricingSettings.region_pack_discount_min_percent || 0),
      region_pack_discount_max_percent: Number(pricingSettings.region_pack_discount_max_percent || 0),
      product_discount_overrides: pricingSettings.product_discount_overrides || {},
      token,
      owned_tiles: ownedTilePayloadRows(ownedSummary.rows),
      world_full_quality_unlocked: isWorldFullQualityUnlocked(account),
    }),
    200,
    env,
  ), timing, env, { entitlement_cache_hit: Boolean(ownedSummary.cache_hit) });
}

export async function handleCreditSceneMap(request, env, deps) {
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
  const center = tileRowsCenter(preliminaryRows);
  const contextProducts = center
    ? suggestedRegionProductsForPoint(center.latitude_deg, center.longitude_deg)
    : [];
  const contextProduct = contextProducts.length ? contextProducts[0] : null;
  timing.mark("products");
  const ownedSummary = await ownedEntitlementSummaryForUser(db, userId, deps, { account });
  const ownedByFamily = ownedSummary.ownedByFamily;
  timing.mark(ownedSummary.cache_hit ? "entitlements_cache" : "entitlements_d1");
  const upsells = [];
  for (const product of contextProducts.slice(0, 4)) {
    const relatedEstimate = estimateRegionPackSummaryWithOwned(product, account, ownedByFamily);
    if (relatedEstimate && !relatedEstimate.error) {
      const relatedPrice = normalizeCreditAmount(relatedEstimate && relatedEstimate.price_eur);
      const relatedNewTiles = Math.max(0, Number.parseInt(relatedEstimate && relatedEstimate.new_tile_count || 0, 10) || 0);
      if (relatedPrice <= 0 && relatedNewTiles <= 0) {
        continue;
      }
      upsells.push(buildRegionPackUpsellCardData(product, relatedEstimate, { includeTiles: false }));
    }
  }
  timing.mark("upsells");
  const data = buildSceneFullQualityMapData(estimate, { token, contextProduct, upsells });
  timing.mark("html");
  return withEndpointTiming(html(regionPackMapHtml(data), 200, env), timing, env, {
    entitlement_cache_hit: Boolean(ownedSummary.cache_hit),
    tile_count: tileKeys.length,
    upsell_count: upsells.length,
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
      const contextProduct = sceneSuccessContextProduct(tileKeys, preliminaryRows);
      if (contextProduct) {
        const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(contextProduct.id || ""), env, deps);
        const account = await ensureFreshCreditAccountForUser(db, userId, deps);
        const ownedRows = await ownedTileRowsForUser(db, userId, deps);
        const data = regionPackStaticMapPayload(contextProduct, tokenResult.token, account, ownedRows, {
          catalogMode: true,
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

  if (purchaseType === "region_pack") {
    const regionPackId = String(purchase && purchase.region_pack_id || metadata.planetka_region_id || "").trim();
    const product = regionProductById(regionPackId);
    if (product) {
      const tokenResult = await createRegionPackDetailTokenForUser(db, userId, String(product.id || ""), env, deps);
      if (String(product.id || "").trim().toLowerCase() === "world") {
        const purchaseMeta = parsePurchaseMetadataJson(purchase);
        const fullPrice = normalizeCreditAmount(
          purchase && purchase.gross_eur
            || metadata.planetka_gross_eur
            || regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur,
        );
        const rawFullPrice = normalizeCreditAmount(regionProductPricingSummary(product) && regionProductPricingSummary(product).gross_eur || fullPrice);
        const price = amountPaidEur;
        const partialLicenceEur = normalizeCreditAmount(
          purchaseMeta.partial_licence_credit_eur
            || metadata.planetka_partial_licence_credit_eur,
        );
        const alreadyLicencedEur = normalizeCreditAmount(
          purchaseMeta.already_licenced_gross_eur
            || metadata.planetka_already_licenced_gross_eur
            || Math.max(0, rawFullPrice - fullPrice - partialLicenceEur),
        );
        const discountPercent = Math.max(
          0,
          Number.parseInt(purchase && purchase.discount_percent || metadata.planetka_discount_percent || regionProductDiscountPercent(product), 10) || 0,
        );
        const discountEur = normalizeCreditAmount(
          purchase && purchase.discount_eur
            || metadata.planetka_discount_eur
            || Math.max(0, fullPrice - price),
        );
        const worldBreakdown = fullQualityPriceBreakdownHtml({
          fullPriceEur: rawFullPrice,
          alreadyLicencedEur,
          partialLicenceEur,
          discountPercent,
          discountEur,
          finalPriceEur: price,
        });
        const safeToken = escapeHtmlText(encodeURIComponent(tokenResult.token));
        return html(
          `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Planetka World Pack</title><style>:root{color-scheme:dark}body{margin:0;background:#111;color:#eee;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:820px;margin:0 auto;padding:24px}.panel{background:#1b1b1b;border:1px solid #3c3c3c;border-radius:12px;padding:14px;margin-top:14px}.button{display:inline-flex;align-items:center;justify-content:center;margin:8px 8px 0 0;padding:9px 12px;border-radius:8px;background:#d9a441;color:#111;text-decoration:none;font-weight:700}.secondary{background:#2a2a2a;color:#eee;border:1px solid #3c3c3c}.muted{color:#aaa}</style></head><body><main><h1>World Full Quality Pack</h1><section class="panel"><h2>Payment successful</h2><p>${escapeHtmlText(success.message)}</p></section><section class="panel"><p>The World pack includes the complete Full Quality texture dataset. A full interactive tile map is intentionally not generated because it would be too large for a useful browser view.</p>${worldBreakdown}<a class="button secondary" href="/credits/region-pack-catalog?token=${safeToken}">View all data packs</a></section></main></body></html>`,
          200,
          env,
        );
      }
      const account = await ensureFreshCreditAccountForUser(db, userId, deps);
      const ownedRows = await ownedTileRowsForUser(db, userId, deps);
      const data = regionPackStaticMapPayload(product, tokenResult.token, account, ownedRows, {
        catalogMode: true,
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

async function applyStripeCreditPurchaseFromSession(db, session, deps, env) {
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
    result = await grantRegionPackEntitlements(
      db,
      userId,
      String(metadata.planetka_region_id || "").trim(),
      sessionId,
      amountPaidEur,
      deps,
      email,
      stripePaymentIntentId,
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
