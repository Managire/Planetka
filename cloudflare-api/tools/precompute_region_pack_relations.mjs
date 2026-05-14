#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const productsFile = resolve(rootDir, "src/worker/region_packs.products.generated.js");
const tileDataFile = resolve(rootDir, "src/worker/region_packs.tile_data.generated.js");
const insertBatchSize = Math.max(1, Number.parseInt(process.env.PLANETKA_RELATION_INSERT_BATCH_SIZE || "500", 10) || 500);

function extractJson(source, regex, label) {
  const match = source.match(regex);
  if (!match) {
    throw new Error(`Could not read ${label}.`);
  }
  return Function(`"use strict"; return (${match[1]});`)();
}

function sqlString(value) {
  return `'${String(value ?? "").replaceAll("'", "''")}'`;
}

function sqlNumber(value) {
  const numeric = Number.parseInt(value, 10);
  return Number.isFinite(numeric) ? String(Math.max(0, numeric)) : "0";
}

function runWranglerSql(sql) {
  const result = spawnSync(
    "npx",
    ["wrangler", "d1", "execute", "planetka-auth", "--remote", "--command", sql],
    {
      cwd: rootDir,
      stdio: "inherit",
      env: process.env,
    },
  );
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

function relationType(targetId, ownedId, targetCount, ownedCount, overlapCount) {
  if (!overlapCount) {
    return "exclusive";
  }
  if (targetId === ownedId) {
    return "self";
  }
  if (overlapCount >= targetCount) {
    return "parent_covers_target";
  }
  if (overlapCount >= ownedCount) {
    return "owned_child_of_target";
  }
  return "overlap";
}

const productsSource = readFileSync(productsFile, "utf8");
const tileDataSource = readFileSync(tileDataFile, "utf8");
const catalogVersion = extractJson(productsSource, /GENERATED_REGION_PACK_CATALOG_VERSION\s*=\s*(".*?");/s, "catalog version");
const products = extractJson(productsSource, /GENERATED_REGION_PACK_PRODUCTS\s*=\s*(\[.*\]);/s, "products");
const tileKeysByProduct = extractJson(
  tileDataSource,
  /GENERATED_REGION_PACK_TILE_KEYS\s*=\s*(\{.*?\});\s*export const GENERATED_REGION_PACK_TILE_REFS/s,
  "tile keys",
);
const grossCentsByTile = extractJson(
  tileDataSource,
  /GENERATED_REGION_PACK_TILE_GROSS_CENTS\s*=\s*(\{.*?\});/s,
  "tile gross cents",
);

const visibleProducts = products
  .filter((product) => product && product.id && Array.isArray(tileKeysByProduct[product.id]))
  .map((product) => ({
    id: String(product.id),
    tile_count: Math.max(0, Number.parseInt(product.tile_count || tileKeysByProduct[product.id].length || 0, 10) || 0),
    paid_tile_count: Math.max(0, Number.parseInt(product.paid_tile_count || 0, 10) || 0),
    free_tile_count: Math.max(0, Number.parseInt(product.free_tile_count || 0, 10) || 0),
    base_gross_cents: Math.max(0, Number.parseInt(product.gross_cents || 0, 10) || 0),
    tile_keys: tileKeysByProduct[product.id],
  }));
const productById = new Map(visibleProducts.map((product) => [product.id, product]));

const productIdsByTile = new Map();
for (const product of visibleProducts) {
  for (const tileKey of product.tile_keys) {
    if (!productIdsByTile.has(tileKey)) {
      productIdsByTile.set(tileKey, []);
    }
    productIdsByTile.get(tileKey).push(product.id);
  }
}

const computedAt = new Date().toISOString();
const ddl = `
CREATE TABLE IF NOT EXISTS region_pack_relations (
  catalog_version TEXT NOT NULL,
  target_region_pack_id TEXT NOT NULL,
  owned_region_pack_id TEXT NOT NULL,
  relation_type TEXT NOT NULL DEFAULT 'exclusive',
  target_tile_count INTEGER NOT NULL DEFAULT 0,
  owned_tile_count INTEGER NOT NULL DEFAULT 0,
  overlap_tile_count INTEGER NOT NULL DEFAULT 0,
  overlap_paid_tile_count INTEGER NOT NULL DEFAULT 0,
  overlap_free_tile_count INTEGER NOT NULL DEFAULT 0,
  overlap_base_gross_cents INTEGER NOT NULL DEFAULT 0,
  target_base_gross_cents INTEGER NOT NULL DEFAULT 0,
  owned_base_gross_cents INTEGER NOT NULL DEFAULT 0,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (catalog_version, target_region_pack_id, owned_region_pack_id)
);
CREATE INDEX IF NOT EXISTS idx_region_pack_relations_owned
ON region_pack_relations(catalog_version, owned_region_pack_id, target_region_pack_id);
DELETE FROM region_pack_relations WHERE catalog_version = ${sqlString(catalogVersion)};
`;

runWranglerSql(ddl);

const columns = [
  "catalog_version",
  "target_region_pack_id",
  "owned_region_pack_id",
  "relation_type",
  "target_tile_count",
  "owned_tile_count",
  "overlap_tile_count",
  "overlap_paid_tile_count",
  "overlap_free_tile_count",
  "overlap_base_gross_cents",
  "target_base_gross_cents",
  "owned_base_gross_cents",
  "computed_at",
];

let pendingRows = [];
let writtenRows = 0;

function flushRows() {
  if (!pendingRows.length) {
    return;
  }
  const sql = `INSERT OR REPLACE INTO region_pack_relations (${columns.join(", ")}) VALUES\n${pendingRows.join(",\n")};`;
  runWranglerSql(sql);
  writtenRows += pendingRows.length;
  pendingRows = [];
  console.log(`Wrote ${writtenRows} region pack relation rows...`);
}

for (const [targetIndex, target] of visibleProducts.entries()) {
  const overlapByOwnedId = new Map();
  for (const tileKey of target.tile_keys) {
    const grossCents = Math.max(0, Number.parseInt(grossCentsByTile[tileKey] || 0, 10) || 0);
    const ownedIds = productIdsByTile.get(tileKey) || [];
    for (const ownedId of ownedIds) {
      let row = overlapByOwnedId.get(ownedId);
      if (!row) {
        row = {
          overlap_tile_count: 0,
          overlap_paid_tile_count: 0,
          overlap_free_tile_count: 0,
          overlap_base_gross_cents: 0,
        };
        overlapByOwnedId.set(ownedId, row);
      }
      row.overlap_tile_count += 1;
      row.overlap_base_gross_cents += grossCents;
      if (grossCents > 0) {
        row.overlap_paid_tile_count += 1;
      } else {
        row.overlap_free_tile_count += 1;
      }
    }
  }

  for (const owned of visibleProducts) {
    const overlap = overlapByOwnedId.get(owned.id) || {
      overlap_tile_count: 0,
      overlap_paid_tile_count: 0,
      overlap_free_tile_count: 0,
      overlap_base_gross_cents: 0,
    };
    pendingRows.push(`(${[
      sqlString(catalogVersion),
      sqlString(target.id),
      sqlString(owned.id),
      sqlString(relationType(target.id, owned.id, target.tile_count, owned.tile_count, overlap.overlap_tile_count)),
      sqlNumber(target.tile_count),
      sqlNumber(owned.tile_count),
      sqlNumber(overlap.overlap_tile_count),
      sqlNumber(overlap.overlap_paid_tile_count),
      sqlNumber(overlap.overlap_free_tile_count),
      sqlNumber(overlap.overlap_base_gross_cents),
      sqlNumber(target.base_gross_cents),
      sqlNumber(productById.get(owned.id)?.base_gross_cents || 0),
      sqlString(computedAt),
    ].join(", ")})`);
    if (pendingRows.length >= insertBatchSize) {
      flushRows();
    }
  }
  if ((targetIndex + 1) % 25 === 0 || targetIndex + 1 === visibleProducts.length) {
    console.log(`Prepared relations for ${targetIndex + 1}/${visibleProducts.length} products.`);
  }
}

flushRows();
runWranglerSql(`
SELECT
  COUNT(*) AS relation_rows,
  SUM(CASE WHEN relation_type != 'exclusive' THEN 1 ELSE 0 END) AS overlapping_rows
FROM region_pack_relations
WHERE catalog_version = ${sqlString(catalogVersion)};
`);
