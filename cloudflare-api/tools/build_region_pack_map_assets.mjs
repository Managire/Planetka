#!/usr/bin/env node
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const generatedProductsSource = path.join(repoRoot, "cloudflare-api", "src", "worker", "region_packs.products.generated.js");
const generatedTileDataSource = path.join(repoRoot, "cloudflare-api", "src", "worker", "region_packs.tile_data.generated.js");
const catalogSource = path.join(repoRoot, "Resources", "Region Packs", "region_packs_gadm.json");
const dissolveOutlinesScript = path.join(__dirname, "dissolve_region_pack_map_outlines.py");
const defaultOut = path.join(os.tmpdir(), "planetka_region_pack_map_assets");
const execFileAsync = promisify(execFile);

const TILE_KEY_RE = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i;
const FREE_D_THRESHOLD = 60;
const DATASET_BASE_MPP = 10.0;
const EQUATOR_Z001_AREA_KM2 = (40075.016686 / 360.0) ** 2;
const METRIC_SCALE = 1_000_000;
// The R2 map assets are allowed to be larger than Worker inline payloads.  A low
// cap here corrupts borders by drawing shortcut chords across complex polygons.
const REGION_PACK_MAP_MAX_OUTLINE_POINTS = 250_000;
const REGION_SIMILAR_COUNTRY_MAX_DISTANCE_DEG = 2.0;
const COUNTRY_LIKE_REGION_PRODUCT_IDS = new Set(["australia", "canada", "china", "united_states"]);
const NORTH_AMERICA_SIMILAR_COUNTRY_LIKE_IDS = new Set(["canada", "united_states"]);
const WORLD_FRAME_PRODUCT_IDS = new Set(["oceania", "pacific_islands"]);
const PACIFIC_INCLUDED_AREA_CODES = new Set([
  "ASM", "COK", "FJI", "FSM", "GUM", "KIR", "MHL", "MNP",
  "NCL", "NIU", "NRU", "PCN", "PLW", "PYF", "SLB", "TKL",
  "TON", "TUV", "VUT", "WLF", "WSM",
]);
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

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index >= 0 && index + 1 < process.argv.length) {
    return process.argv[index + 1];
  }
  return fallback;
}

function normalizeMetricAmount(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.round(parsed * METRIC_SCALE) / METRIC_SCALE;
}

function normalizeTileKey(value) {
  const match = TILE_KEY_RE.exec(String(value || "").trim());
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

function normalizeTileKeys(value) {
  const seen = new Set();
  const keys = [];
  for (const entry of Array.isArray(value) ? value : []) {
    const key = normalizeTileKey(entry);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    keys.push(key);
  }
  return keys;
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

function mergeCircularIntervals(intervals) {
  const normalized = intervals
    .map(([start, end]) => [
      Math.max(0, Math.min(360, Number(start))),
      Math.max(0, Math.min(360, Number(end))),
    ])
    .filter(([start, end]) => Number.isFinite(start) && Number.isFinite(end) && end > start)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged = [];
  for (const [start, end] of normalized) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
}

function displayLongitudeDomainForRows(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return null;
  }
  const intervals = rows
    .map((row) => [Number(row.x), Number(row.x) + Number(row.z)])
    .filter(([start, end]) => Number.isFinite(start) && Number.isFinite(end) && end > start);
  const merged = mergeCircularIntervals(intervals);
  let minLon = 180;
  let maxLon = -180;
  for (const row of rows) {
    minLon = Math.min(minLon, Number(row.lon_min));
    maxLon = Math.max(maxLon, Number(row.lon_max));
  }
  const rawWidth = maxLon - minLon;
  if (merged.length === 1) {
    const [start, end] = merged[0];
    if (end >= 359.5 && start > 180) {
      return {
        start_angle: start,
        compact_width: end - start,
        raw_width: rawWidth,
      };
    }
    return null;
  }
  if (!Number.isFinite(rawWidth) || rawWidth <= 180) {
    return null;
  }
  let largestGap = { size: -1, start: 0, end: 0 };
  for (let index = 0; index < merged.length; index += 1) {
    const current = merged[index];
    const next = merged[(index + 1) % merged.length];
    const gapStart = current[1];
    const gapEnd = index + 1 < merged.length ? next[0] : next[0] + 360;
    const size = gapEnd - gapStart;
    if (size > largestGap.size) {
      largestGap = { size, start: gapStart, end: gapEnd };
    }
  }
  const compactWidth = 360 - largestGap.size;
  if (!Number.isFinite(compactWidth) || compactWidth <= 0 || compactWidth >= rawWidth - 10) {
    return null;
  }
  return {
    start_angle: largestGap.end % 360,
    compact_width: compactWidth,
    raw_width: rawWidth,
  };
}

function displayLonFromAngle(angle, startAngle) {
  let adjusted = Number(angle);
  while (adjusted < startAngle) {
    adjusted += 360;
  }
  while (adjusted >= startAngle + 360) {
    adjusted -= 360;
  }
  return adjusted - 180;
}

function displayLon(lon, startAngle) {
  return displayLonFromAngle(Number(lon) + 180, startAngle);
}

function wrapPointForDisplay(point, startAngle) {
  if (!Array.isArray(point) || point.length < 2) {
    return point;
  }
  const lon = Number(point[0]);
  const lat = Number(point[1]);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    return point;
  }
  return [displayLon(lon, startAngle), lat];
}

function applyDisplayLongitudeWrap(asset) {
  const rows = Array.isArray(asset && asset.tiles) ? asset.tiles : [];
  const domain = displayLongitudeDomainForRows(rows);
  if (!domain) {
    return asset;
  }
  const startAngle = Number(domain.start_angle);
  for (const row of rows) {
    const x = Number(row.x);
    const z = Number(row.z);
    if (!Number.isFinite(x) || !Number.isFinite(z)) {
      continue;
    }
    row.lon_min = displayLonFromAngle(x, startAngle);
    row.lon_max = displayLonFromAngle(x + z, startAngle);
    if (row.lon_max <= row.lon_min) {
      row.lon_max += 360;
    }
  }
  asset.outlines = (Array.isArray(asset.outlines) ? asset.outlines : []).map((outline) => ({
    ...outline,
    polygons: (Array.isArray(outline.polygons) ? outline.polygons : []).map((polygon) => polygon.map((point) => wrapPointForDisplay(point, startAngle))),
  }));
  asset.bounds = boundsForProduct(null, null, rows);
  asset.display_longitude_wrap = {
    start_angle: startAngle,
    compact_width: domain.compact_width,
    raw_width: domain.raw_width,
  };
  return asset;
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

function bboxArea(product) {
  const bbox = Array.isArray(product && product.bbox) ? product.bbox : [];
  if (bbox.length < 4) {
    return Number.POSITIVE_INFINITY;
  }
  return Math.max(0, Number(bbox[2]) - Number(bbox[0])) * Math.max(0, Number(bbox[3]) - Number(bbox[1]));
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
  const lonDistance = Math.max(0, Math.max(aMinLon, bMinLon) - Math.min(aMaxLon, bMaxLon));
  const latDistance = Math.max(0, Math.max(aMinLat, bMinLat) - Math.min(aMaxLat, bMaxLat));
  return Math.hypot(lonDistance, latDistance);
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

function productRank(product) {
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "country" || type === "admin_region") return 1;
  if (type === "macro_region") return 2;
  if (type === "continent") return 3;
  if (type === "world") return 4;
  return 0;
}

function productSpecificityScore(product) {
  const type = String(product && product.type || "").trim().toLowerCase();
  if (type === "country" || type === "admin_region") return 1;
  if (type === "macro_region") return 2;
  if (type === "continent") return 3;
  if (type === "world") return 4;
  return 10;
}

function outlinePointCount(outlines) {
  let count = 0;
  for (const outline of outlines || []) {
    for (const ring of Array.isArray(outline && outline.polygons) ? outline.polygons : []) {
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
  return simplified.length >= 3 ? simplified : source.slice(0, Math.min(source.length, 4));
}

async function loadGenerated() {
  const tmpProducts = path.join(os.tmpdir(), `planetka_region_pack_products_${process.pid}_${Date.now()}.mjs`);
  const tmpTileData = path.join(os.tmpdir(), `planetka_region_pack_tile_data_${process.pid}_${Date.now()}.mjs`);
  await fs.copyFile(generatedProductsSource, tmpProducts);
  await fs.copyFile(generatedTileDataSource, tmpTileData);
  try {
    const products = await import(pathToFileURL(tmpProducts).href);
    const tileData = await import(pathToFileURL(tmpTileData).href);
    return { ...products, ...tileData };
  } finally {
    await fs.rm(tmpProducts, { force: true });
    await fs.rm(tmpTileData, { force: true });
  }
}

async function loadCatalog() {
  const source = path.resolve(argValue("--catalog-json", catalogSource));
  try {
    return JSON.parse(await fs.readFile(source, "utf8"));
  } catch (error) {
    if (error && error.code === "ENOENT") {
      return {};
    }
    throw error;
  }
}

async function dissolveGeneratedOutlines(outDir) {
  if (process.argv.includes("--skip-dissolve-outlines")) {
    return { skipped: true };
  }
  const { stdout, stderr } = await execFileAsync(
    "python3",
    [dissolveOutlinesScript, "--assets-dir", outDir],
    { maxBuffer: 10 * 1024 * 1024 },
  );
  if (stderr && stderr.trim()) {
    console.error(stderr.trim());
  }
  try {
    return JSON.parse(stdout);
  } catch {
    return { raw_stdout: stdout.trim() };
  }
}

function buildHelpers(generated, catalog = {}) {
  const products = Array.isArray(generated.GENERATED_REGION_PACK_PRODUCTS)
    ? generated.GENERATED_REGION_PACK_PRODUCTS
    : [];
  const productById = new Map(products.map((product) => [String(product && product.id || ""), product]));
  const catalogProductById = new Map((Array.isArray(catalog && catalog.products) ? catalog.products : [])
    .map((product) => [String(product && product.id || ""), product]));
  const catalogOutlines = catalog && typeof catalog.outlines === "object" && catalog.outlines
    ? catalog.outlines
    : {};
  const product = (id) => productById.get(String(id || "").trim()) || null;
  const detail = (id) => {
    const safeId = String(id || "").trim();
    const generatedDetail = generated.GENERATED_REGION_PACK_DETAILS[safeId] || {};
    const catalogProduct = catalogProductById.get(safeId) || {};
    return {
      ...catalogProduct,
      ...generatedDetail,
      countries: Array.isArray(generatedDetail.countries)
        ? generatedDetail.countries
        : (Array.isArray(catalogProduct.countries) ? catalogProduct.countries : []),
      outline_refs: Array.isArray(generatedDetail.outline_refs)
        ? generatedDetail.outline_refs
        : (Array.isArray(catalogProduct.outline_refs) ? catalogProduct.outline_refs : []),
      bounds: Array.isArray(generatedDetail.bounds)
        ? generatedDetail.bounds
        : (Array.isArray(catalogProduct.bounds) ? catalogProduct.bounds : catalogProduct.bbox),
    };
  };
  const tileKeys = (sourceProduct, seen = new Set()) => {
    const productId = String(sourceProduct && sourceProduct.id || "").trim();
    if (!productId || seen.has(productId)) {
      return [];
    }
    seen.add(productId);
    const refs = Array.isArray(generated.GENERATED_REGION_PACK_TILE_REFS[productId])
      ? generated.GENERATED_REGION_PACK_TILE_REFS[productId]
      : [];
    const keys = [];
    const seenKeys = new Set();
    for (const ref of refs) {
      for (const key of tileKeys(product(ref), seen)) {
        if (!seenKeys.has(key)) {
          seenKeys.add(key);
          keys.push(key);
        }
      }
    }
    for (const key of normalizeTileKeys(generated.GENERATED_REGION_PACK_TILE_KEYS[productId] || [])) {
      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        keys.push(key);
      }
    }
    return keys;
  };
  const z001CellCache = new Map();
  const z001Cells = (sourceProduct) => {
    const productId = String(sourceProduct && sourceProduct.id || "").trim();
    if (!productId) {
      return new Set();
    }
    if (z001CellCache.has(productId)) {
      return z001CellCache.get(productId);
    }
    const cells = new Set();
    for (const key of tileKeys(sourceProduct)) {
      const parsed = parseTileKey(key);
      if (parsed && parsed.z === 1 && parsed.d === 1) {
        cells.add(`${parsed.x},${parsed.y}`);
      }
    }
    z001CellCache.set(productId, cells);
    return cells;
  };
  const z001FootprintsOverlap = (sourceProduct, candidateProduct) => {
    const sourceCells = z001Cells(sourceProduct);
    const candidateCells = z001Cells(candidateProduct);
    if (!sourceCells.size || !candidateCells.size) {
      return false;
    }
    const smaller = sourceCells.size <= candidateCells.size ? sourceCells : candidateCells;
    const larger = sourceCells.size <= candidateCells.size ? candidateCells : sourceCells;
    for (const cell of smaller) {
      if (larger.has(cell)) {
        return true;
      }
    }
    return false;
  };
  const outlines = (sourceProduct) => {
    const sourceDetail = detail(sourceProduct && sourceProduct.id);
    if (Array.isArray(sourceDetail.outlines) && sourceDetail.outlines.length) {
      return sourceDetail.outlines;
    }
    const refs = Array.isArray(sourceDetail.outline_refs) ? sourceDetail.outline_refs : [];
    const result = [];
    for (const ref of refs) {
      const safeRef = String(ref || "");
      const outline = generated.GENERATED_REGION_PACK_OUTLINES[safeRef] || catalogOutlines[safeRef];
      if (outline) {
        result.push(outline);
      }
    }
    const points = outlinePointCount(result);
    if (points <= REGION_PACK_MAP_MAX_OUTLINE_POINTS) {
      return result;
    }
    const stride = Math.max(1, Math.ceil(points / REGION_PACK_MAP_MAX_OUTLINE_POINTS));
    return result.map((outline) => ({
      id: String(outline && outline.id || ""),
      name: String(outline && outline.name || ""),
      polygons: (Array.isArray(outline && outline.polygons) ? outline.polygons : [])
        .map((ring) => simplifyRingForMap(ring, stride))
        .filter((ring) => Array.isArray(ring) && ring.length >= 3),
    })).filter((outline) => outline.polygons.length);
  };
  const countrySet = (sourceProduct, seen = new Set()) => {
    const id = String(sourceProduct && sourceProduct.id || "").trim();
    if (!id || seen.has(id)) {
      return new Set();
    }
    seen.add(id);
    const type = String(sourceProduct && sourceProduct.type || "").trim().toLowerCase();
    if (type === "country" || type === "admin_region") {
      return new Set([id]);
    }
    const result = new Set();
    for (const countryId of Array.isArray(sourceProduct && sourceProduct.countries) ? sourceProduct.countries : []) {
      const child = product(countryId);
      if (child) {
        for (const nested of countrySet(child, seen)) {
          result.add(nested);
        }
      } else if (countryId) {
        result.add(String(countryId));
      }
    }
    return result;
  };
  const shareCountry = (a, b) => {
    const setA = countrySet(a);
    const setB = countrySet(b);
    for (const id of setA) {
      if (setB.has(id)) {
        return true;
      }
    }
    return false;
  };
  const countryOption = (candidate) => {
    const id = String(candidate && candidate.id || "").trim();
    const type = String(candidate && candidate.type || "").trim().toLowerCase();
    if (COUNTRY_LIKE_REGION_PRODUCT_IDS.has(id)) {
      return true;
    }
    return type === "country" && !(Array.isArray(candidate && candidate.adm1_codes) && candidate.adm1_codes.length);
  };
  const subset = (candidateSet, parentSet) => {
    if (!candidateSet.size || !parentSet.size) {
      return false;
    }
    for (const id of candidateSet) {
      if (!parentSet.has(id)) {
        return false;
      }
    }
    return true;
  };
  const includedCountries = (sourceProduct) => {
    const currentId = String(sourceProduct && sourceProduct.id || "").trim();
    const currentRank = productRank(sourceProduct);
    if (!currentId || currentRank <= 1) {
      return [];
    }
    const parentSet = countrySet(sourceProduct);
    return products
      .filter((candidate) => {
        const candidateId = String(candidate && candidate.id || "").trim();
        return candidateId
          && candidateId !== currentId
          && !candidate.hidden
          && countryOption(candidate)
          && subset(countrySet(candidate), parentSet);
      })
      .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
  };
  const includedAreas = (sourceProduct) => {
    const currentId = String(sourceProduct && sourceProduct.id || "").trim();
    const currentRank = productRank(sourceProduct);
    if (!currentId || currentRank !== 3) {
      return [];
    }
    const parentSet = countrySet(sourceProduct);
    return products
      .filter((candidate) => {
        const candidateId = String(candidate && candidate.id || "").trim();
        return candidateId
          && candidateId !== currentId
          && !candidate.hidden
          && (
            !COUNTRY_LIKE_REGION_PRODUCT_IDS.has(candidateId)
            || (currentId === "north_america" && NORTH_AMERICA_SIMILAR_COUNTRY_LIKE_IDS.has(candidateId))
          )
          && productRank(candidate) === 2
          && subset(countrySet(candidate), parentSet);
      })
      .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
  };
  const related = (sourceProduct, limit = 3) => {
    const currentRank = productRank(sourceProduct);
    const currentId = String(sourceProduct && sourceProduct.id || "").trim();
    if (!currentId || currentRank <= 0) {
      return [];
    }
    const result = [];
    const seen = new Set([currentId]);
    const add = (candidate) => {
      const id = String(candidate && candidate.id || "").trim();
      if (!id || seen.has(id)) {
        return;
      }
      seen.add(id);
      result.push(candidate);
    };
    const sourceIsCountryOption = countryOption(sourceProduct) && currentRank !== 3;
    if (currentRank === 1 || sourceIsCountryOption) {
      for (const candidate of products
        .filter((candidate) => {
          const candidateId = String(candidate && candidate.id || "").trim();
          if (!candidateId || candidateId === currentId) {
            return false;
          }
          if (sourceIsCountryOption) {
            return countryOption(candidate) && z001FootprintsOverlap(sourceProduct, candidate);
          }
          if (productRank(candidate) !== 1) {
            return false;
          }
          const candidateBbox = candidate && candidate.bbox || [];
          if (
            bboxLongitudeSpanDegrees(candidateBbox) >= 180.0
            && !z001FootprintsOverlap(sourceProduct, candidate)
          ) {
            return false;
          }
          const distance = bboxDistanceDegrees(sourceProduct && sourceProduct.bbox || [], candidateBbox);
          return Number.isFinite(distance) && distance <= REGION_SIMILAR_COUNTRY_MAX_DISTANCE_DEG;
        })
        .sort((a, b) => (
          bboxDistanceDegrees(sourceProduct && sourceProduct.bbox || [], a && a.bbox || [])
          - bboxDistanceDegrees(sourceProduct && sourceProduct.bbox || [], b && b.bbox || [])
          || productSpecificityScore(a) - productSpecificityScore(b)
          || bboxArea(a) - bboxArea(b)
          || String(a.name || "").localeCompare(String(b.name || ""))
        ))) {
        add(candidate);
      }
    }
    const areas = includedAreas(sourceProduct);
    for (const candidate of areas) {
      add(candidate);
    }
    const includeCountries = currentRank !== 3;
    const included = includeCountries ? includedCountries(sourceProduct) : [];
    for (const candidate of included) {
      add(candidate);
    }
    for (const candidate of products
      .filter((candidate) => {
        const candidateId = String(candidate && candidate.id || "").trim();
        const candidateRank = productRank(candidate);
        return candidateId
          && candidateId !== currentId
          && candidateRank > currentRank
          && candidateRank < 4
          && shareCountry(sourceProduct, candidate);
      })
      .sort((a, b) => (
        productRank(a) - productRank(b)
        || productSpecificityScore(a) - productSpecificityScore(b)
        || bboxArea(a) - bboxArea(b)
        || String(a.name || "").localeCompare(String(b.name || ""))
      ))) {
      add(candidate);
    }
    if (currentRank === 1 || sourceIsCountryOption) {
      return result;
    }
    if (areas.length || included.length) {
      return result;
    }
    return result.slice(0, limit);
  };
  const directChildIds = (sourceProduct) => {
    const ids = [];
    const seenIds = new Set();
    for (const childId of Array.isArray(sourceProduct && sourceProduct.countries) ? sourceProduct.countries : []) {
      const id = String(childId || "").trim();
      if (!id || seenIds.has(id) || !product(id)) {
        continue;
      }
      seenIds.add(id);
      ids.push(id);
    }
    return ids;
  };
  const hierarchyChildren = (sourceProduct) => {
    const currentId = String(sourceProduct && sourceProduct.id || "").trim();
    const currentRank = productRank(sourceProduct);
    if (!currentId || currentRank <= 0) {
      return [];
    }
    const result = [];
    const seenIds = new Set([currentId]);
    const add = (candidate) => {
      const id = String(candidate && candidate.id || "").trim();
      if (!id || seenIds.has(id) || candidate.hidden) {
        return;
      }
      seenIds.add(id);
      result.push(candidate);
    };
    if (currentRank === 4) {
      for (const candidate of products
        .filter((candidate) => productRank(candidate) === 3 && !candidate.hidden)
        .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")))) {
        add(candidate);
      }
      return result;
    }
    if (currentRank === 3) {
      const parentSet = countrySet(sourceProduct);
      const covered = new Set();
      const macroChildren = products
        .filter((candidate) => {
          const id = String(candidate && candidate.id || "").trim();
          return id
            && id !== currentId
            && !candidate.hidden
            && productRank(candidate) === 2
            && subset(countrySet(candidate), parentSet);
        })
        .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
      for (const candidate of macroChildren) {
        add(candidate);
        for (const id of countrySet(candidate)) {
          covered.add(id);
        }
      }
      for (const candidate of products
        .filter((candidate) => {
          const id = String(candidate && candidate.id || "").trim();
          if (!id || id === currentId || candidate.hidden || !countryOption(candidate)) {
            return false;
          }
          const candidateSet = countrySet(candidate);
          if (!subset(candidateSet, parentSet)) {
            return false;
          }
          if (!COUNTRY_LIKE_REGION_PRODUCT_IDS.has(id)) {
            for (const countryId of candidateSet) {
              if (covered.has(countryId)) {
                return false;
              }
            }
          }
          return true;
        })
        .sort((a, b) => productSpecificityScore(a) - productSpecificityScore(b) || String(a.name || "").localeCompare(String(b.name || "")))) {
        add(candidate);
      }
      return result;
    }
    for (const id of directChildIds(sourceProduct)) {
      const child = product(id);
      if (child) {
        add(child);
      }
    }
    return result;
  };
  return { products, product, detail, tileKeys, outlines, related, directChildIds, hierarchyChildren };
}

function boundsForProduct(sourceProduct, sourceDetail, rows) {
  const productId = String(sourceProduct && sourceProduct.id || "").trim().toLowerCase();
  if (WORLD_FRAME_PRODUCT_IDS.has(productId)) {
    return { min_lon: -180, min_lat: -90, max_lon: 180, max_lat: 90 };
  }
  const detailBounds = sourceDetail && Array.isArray(sourceDetail.bounds) ? sourceDetail.bounds : null;
  const bbox = sourceProduct && Array.isArray(sourceProduct.bbox) ? sourceProduct.bbox : null;
  const bounds = detailBounds && detailBounds.length >= 4 ? detailBounds : bbox;
  if (bounds && bounds.length >= 4) {
    return {
      min_lon: Number(bounds[0]),
      min_lat: Number(bounds[1]),
      max_lon: Number(bounds[2]),
      max_lat: Number(bounds[3]),
    };
  }
  if (!rows.length) {
    return { min_lon: -10, min_lat: 35, max_lon: 30, max_lat: 47.5 };
  }
  return rows.reduce((acc, row) => ({
    min_lon: Math.min(acc.min_lon, Number(row.lon_min)),
    min_lat: Math.min(acc.min_lat, Number(row.lat_min)),
    max_lon: Math.max(acc.max_lon, Number(row.lon_max)),
    max_lat: Math.max(acc.max_lat, Number(row.lat_max)),
  }), { min_lon: 180, min_lat: 90, max_lon: -180, max_lat: -90 });
}

function productPublicPayload(product, version, includedCountries) {
  return {
    id: String(product && product.id || ""),
    name: String(product && product.name || ""),
    type: String(product && product.type || ""),
    discount_percent: Math.max(0, Number.parseInt(product && product.discount_percent || 0, 10) || 0),
    catalog_version: version,
    included_countries: includedCountries,
  };
}

function includedCountryDisplayName(value, helpers) {
  if (value && typeof value === "object") {
    const code = String(value.GID_0 || "").trim().toUpperCase();
    const label = String(DISPLAY_AREA_LABEL_BY_ADM0_CODE.get(code) || value.name || value.COUNTRY || value.NAME_1 || value.GID_0 || "").trim();
    return label && PACIFIC_INCLUDED_AREA_CODES.has(code) ? `${label} ${code}` : label;
  }
  const id = String(value || "").trim();
  const product = helpers && typeof helpers.product === "function" ? helpers.product(id) : null;
  return String(product && product.name || id).trim();
}

function outlineDisplayName(outline) {
  const code = String(outline && outline.id || "").trim().toUpperCase();
  return String(DISPLAY_AREA_LABEL_BY_ADM0_CODE.get(code) || outline && outline.name || "").trim();
}

function uniqueIncludedCountries(values, helpers) {
  const seen = new Set();
  const result = [];
  for (const entry of Array.isArray(values) ? values : []) {
    const label = includedCountryDisplayName(entry, helpers);
    const key = label.toLowerCase();
    if (!label || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(label);
  }
  return result;
}

function catalogGroupForProduct(product) {
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
  if (Array.isArray(product && product.adm1_codes) && product.adm1_codes.length) {
    return { key: "states_provinces", label: "States / Provinces" };
  }
  if (type === "country" || type === "admin_region") {
    return { key: "countries", label: "Countries" };
  }
  return { key: "other", label: "Other Data Packs" };
}

function assetForProduct(product, helpers, generated) {
  const id = String(product && product.id || "");
  const sourceDetail = helpers.detail(id);
  const includedCountries = uniqueIncludedCountries(Array.isArray(sourceDetail.countries)
    ? sourceDetail.countries
    : (Array.isArray(product && product.countries) ? product.countries : []), helpers);
  const rows = helpers.tileKeys(product)
    .map((tileKey) => {
      const parsed = parseTileKey(tileKey);
      if (!parsed) {
        return null;
      }
      const fullPriceCents = Math.max(0, Number.parseInt(generated.GENERATED_REGION_PACK_TILE_GROSS_CENTS[tileKey] || 0, 10) || 0);
      const freeReason = freeReasonForTile(parsed) || (fullPriceCents <= 0 ? "no_billable_land" : "");
      const landKm2 = billableLandKm2FromGeneratedGrossCents(tileKey, fullPriceCents);
      return {
        tile_key: tileKey,
        x: parsed.x,
        y: parsed.y,
        z: parsed.z,
        d: parsed.d,
        lon_min: parsed.x - 180,
        lon_max: parsed.x - 180 + parsed.z,
        lat_min: parsed.y - 90,
        lat_max: parsed.y - 90 + parsed.z,
        full_price_cents: fullPriceCents,
        billable_land_km2: landKm2,
        globally_free: Boolean(freeReason || fullPriceCents <= 0),
        free_reason: freeReason,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.tile_key.localeCompare(b.tile_key));
  const levels = Array.from(new Set(rows.map((row) => row.z))).sort((a, b) => a - b);
  const asset = {
    ok: true,
    static_asset: true,
    catalog_version: generated.GENERATED_REGION_PACK_CATALOG_VERSION || "unknown",
    region_pack: productPublicPayload(product, generated.GENERATED_REGION_PACK_CATALOG_VERSION || "unknown", includedCountries),
    included_countries: includedCountries,
    outlines: helpers.outlines(product).map((outline) => ({
      ...outline,
      name: outlineDisplayName(outline),
    })),
    bounds: boundsForProduct(product, sourceDetail, rows),
    levels,
    tiles: rows,
    upsell_ids: helpers.related(product, 3).map((entry) => String(entry && entry.id || "")).filter(Boolean),
  };
  return WORLD_FRAME_PRODUCT_IDS.has(String(product && product.id || "").trim().toLowerCase())
    ? asset
    : applyDisplayLongitudeWrap(asset);
}

async function main() {
  const outDir = path.resolve(argValue("--out", defaultOut));
  const generated = await loadGenerated();
  const catalog = await loadCatalog();
  const helpers = buildHelpers(generated, catalog);
  await fs.rm(outDir, { recursive: true, force: true });
  await fs.mkdir(outDir, { recursive: true });
  let count = 0;
  let totalBytes = 0;
  const catalogProducts = [];
  for (const product of helpers.products) {
    const id = String(product && product.id || "").trim();
    if (!id) {
      continue;
    }
    const group = catalogGroupForProduct(product);
    const fullPriceCents = Math.max(0, Number.parseInt(product && product.gross_cents || 0, 10) || 0);
    if (id.toLowerCase() === "world") {
      const asset = assetForProduct(product, helpers, generated);
      const body = JSON.stringify(asset);
      await fs.writeFile(path.join(outDir, `${id}.json`), body);
      count += 1;
      totalBytes += Buffer.byteLength(body);
      catalogProducts.push({
        id,
        name: String(product && product.name || ""),
        type: String(product && product.type || ""),
        group_key: group.key,
        group_label: group.label,
        discount_percent: Math.max(0, Number.parseInt(product && product.discount_percent || 0, 10) || 0),
        total_tiles: asset.tiles.length,
        full_price_cents: fullPriceCents,
        child_ids: helpers.directChildIds(product),
        hierarchy_child_ids: helpers.hierarchyChildren(product)
          .map((entry) => String(entry && entry.id || ""))
          .filter(Boolean),
        // Keep the catalog small; the full World tile payload lives in world.json.
        tiles: [],
        world: true,
      });
      continue;
    }
    const asset = assetForProduct(product, helpers, generated);
    const body = JSON.stringify(asset);
    await fs.writeFile(path.join(outDir, `${id}.json`), body);
    count += 1;
    totalBytes += Buffer.byteLength(body);
    catalogProducts.push({
      id,
      name: String(product && product.name || ""),
      type: String(product && product.type || ""),
      group_key: group.key,
      group_label: group.label,
      discount_percent: Math.max(0, Number.parseInt(product && product.discount_percent || 0, 10) || 0),
      total_tiles: asset.tiles.length,
      full_price_cents: fullPriceCents,
      child_ids: helpers.directChildIds(product),
      hierarchy_child_ids: helpers.hierarchyChildren(product)
        .map((entry) => String(entry && entry.id || ""))
        .filter(Boolean),
      tiles: asset.tiles.map((tile) => [
        tile.tile_key,
        Math.max(0, Number.parseInt(tile.full_price_cents || 0, 10) || 0),
        tile.globally_free ? 1 : 0,
      ]),
    });
  }
  const catalogBody = JSON.stringify({
    ok: true,
    static_catalog: true,
    catalog_version: generated.GENERATED_REGION_PACK_CATALOG_VERSION || "unknown",
    products: catalogProducts,
  });
  await fs.writeFile(path.join(outDir, "catalog.json"), catalogBody);
  totalBytes += Buffer.byteLength(catalogBody);
  const dissolveResult = await dissolveGeneratedOutlines(outDir);
  console.log(JSON.stringify({ ok: true, outDir, count, totalBytes, dissolveResult }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
