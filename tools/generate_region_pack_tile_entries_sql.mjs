#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const tileDataPath = path.join(root, "cloudflare-api/src/worker/region_packs.tile_data.generated.js");
const productsPath = path.join(root, "cloudflare-api/src/worker/region_packs.products.generated.js");

const {
  GENERATED_REGION_PACK_TILE_KEYS,
  GENERATED_REGION_PACK_TILE_GROSS_CENTS,
} = await import(pathToFileUrl(tileDataPath));
const {
  GENERATED_REGION_PACK_CATALOG_VERSION,
} = await import(pathToFileUrl(productsPath));

function pathToFileUrl(filePath) {
  return new URL(`file://${path.resolve(filePath)}`).href;
}

function sqlString(value) {
  return `'${String(value ?? "").replace(/'/g, "''")}'`;
}

function parseTileKey(tileKey) {
  const match = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i.exec(String(tileKey || ""));
  if (!match) {
    return null;
  }
  return {
    key: match[0],
    x: Number.parseInt(match[1], 10),
    y: Number.parseInt(match[2], 10),
    z: Number.parseInt(match[3], 10),
    d: Number.parseInt(match[4], 10),
  };
}

function isFreeTile(parsed, baseGrossCents) {
  if (!parsed) {
    return true;
  }
  return Number(baseGrossCents || 0) <= 0 || Number(parsed.d) >= 60;
}

function rowSql(catalogVersion, productId, tileKey) {
  const parsed = parseTileKey(tileKey);
  if (!parsed) {
    return "";
  }
  const family = `x${String(parsed.x).padStart(3, "0")}_y${String(parsed.y).padStart(3, "0")}_z${String(parsed.z).padStart(3, "0")}`;
  const baseGrossCents = Math.max(0, Number.parseInt(GENERATED_REGION_PACK_TILE_GROSS_CENTS[parsed.key] || 0, 10) || 0);
  const globallyFree = isFreeTile(parsed, baseGrossCents) ? 1 : 0;
  return `(${[
    sqlString(catalogVersion),
    sqlString(productId),
    sqlString(parsed.key),
    sqlString(family),
    parsed.x,
    parsed.y,
    parsed.z,
    parsed.d,
    baseGrossCents,
    globallyFree,
  ].join(",")})`;
}

const outFile = process.argv[2] || path.join(root, "cloudflare-api/generated/region_pack_tile_entries.sql");
const catalogVersion = GENERATED_REGION_PACK_CATALOG_VERSION || "gadm_regions_v8";
const batchSize = Math.max(1, Number.parseInt(process.env.PLANETKA_REGION_PACK_TILE_SQL_BATCH || "100", 10) || 100);

fs.mkdirSync(path.dirname(outFile), { recursive: true });
const stream = fs.createWriteStream(outFile, { encoding: "utf8" });
stream.write("CREATE TABLE IF NOT EXISTS region_pack_tile_entries (catalog_version TEXT NOT NULL, region_pack_id TEXT NOT NULL, tile_key TEXT NOT NULL, family_key TEXT NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL, z INTEGER NOT NULL, d INTEGER NOT NULL, base_gross_cents INTEGER NOT NULL DEFAULT 0, globally_free INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (catalog_version, region_pack_id, tile_key));\n");
stream.write("CREATE INDEX IF NOT EXISTS idx_region_pack_tile_entries_pack_family ON region_pack_tile_entries(catalog_version, region_pack_id, family_key);\n");
stream.write("CREATE INDEX IF NOT EXISTS idx_region_pack_tile_entries_pack_z001 ON region_pack_tile_entries(catalog_version, region_pack_id, z, d, x, y);\n");
stream.write("CREATE INDEX IF NOT EXISTS idx_region_pack_tile_entries_tile ON region_pack_tile_entries(catalog_version, tile_key);\n");
stream.write(`DELETE FROM region_pack_tile_entries WHERE catalog_version = ${sqlString(catalogVersion)};\n`);

let batch = [];
let rowCount = 0;
for (const productId of Object.keys(GENERATED_REGION_PACK_TILE_KEYS || {}).sort()) {
  const safeProductId = String(productId || "").trim().toLowerCase();
  const keys = Array.isArray(GENERATED_REGION_PACK_TILE_KEYS[productId]) ? GENERATED_REGION_PACK_TILE_KEYS[productId] : [];
  for (const tileKey of keys) {
    const row = rowSql(catalogVersion, safeProductId, tileKey);
    if (!row) {
      continue;
    }
    batch.push(row);
    rowCount += 1;
    if (batch.length >= batchSize) {
      stream.write(`INSERT OR REPLACE INTO region_pack_tile_entries (catalog_version, region_pack_id, tile_key, family_key, x, y, z, d, base_gross_cents, globally_free) VALUES\n${batch.join(",\n")};\n`);
      batch = [];
    }
  }
}
if (batch.length) {
  stream.write(`INSERT OR REPLACE INTO region_pack_tile_entries (catalog_version, region_pack_id, tile_key, family_key, x, y, z, d, base_gross_cents, globally_free) VALUES\n${batch.join(",\n")};\n`);
}
stream.end();
await new Promise((resolve) => stream.on("finish", resolve));
console.log(JSON.stringify({ ok: true, outFile, catalogVersion, rowCount, batchSize }));
