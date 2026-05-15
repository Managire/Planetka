#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const productsFile = resolve(rootDir, "src/worker/region_packs.products.generated.js");
const relationsFile = resolve(rootDir, "src/worker/region_packs.relations.generated.js");
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

const productsSource = readFileSync(productsFile, "utf8");
const relationsSource = readFileSync(relationsFile, "utf8");
const catalogVersion = extractJson(productsSource, /GENERATED_REGION_PACK_CATALOG_VERSION\s*=\s*(".*?");/s, "catalog version");
const graphVersion = extractJson(relationsSource, /GENERATED_REGION_PACK_RELATION_GRAPH_VERSION\s*=\s*(".*?");/s, "relation graph version");
const relationsByTarget = extractJson(
  relationsSource,
  /GENERATED_REGION_PACK_RELATIONS_BY_TARGET\s*=\s*(\{.*?\});\s*export const GENERATED_REGION_PACK_RELATIONS_BY_OWNED/s,
  "relations by target",
);
const relationCounts = extractJson(
  relationsSource,
  /GENERATED_REGION_PACK_RELATION_COUNTS\s*=\s*(\{.*?\});/s,
  "relation counts",
);

if (graphVersion !== catalogVersion) {
  throw new Error(`Relation graph version ${graphVersion} does not match catalog version ${catalogVersion}.`);
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
  console.log(`Wrote ${writtenRows} meaningful region pack relation rows...`);
}

for (const [targetId, rows] of Object.entries(relationsByTarget)) {
  for (const row of rows || []) {
    const ownedId = String(row[0] || "");
    const relationType = String(row[1] || "overlap");
    pendingRows.push(`(${[
      sqlString(catalogVersion),
      sqlString(targetId),
      sqlString(ownedId),
      sqlString(relationType),
      sqlNumber(row[6]),
      sqlNumber(row[7]),
      sqlNumber(row[2]),
      sqlNumber(row[3]),
      sqlNumber(row[4]),
      sqlNumber(row[5]),
      sqlNumber(row[8]),
      sqlNumber(row[9]),
      sqlString(computedAt),
    ].join(", ")})`);
    if (pendingRows.length >= insertBatchSize) {
      flushRows();
    }
  }
}

flushRows();
console.log("Static relation graph summary:", JSON.stringify(relationCounts));
runWranglerSql(`
SELECT
  COUNT(*) AS relation_rows,
  SUM(CASE WHEN relation_type = 'parent_covers_target' THEN 1 ELSE 0 END) AS parent_covers_target_rows,
  SUM(CASE WHEN relation_type = 'owned_child_of_target' THEN 1 ELSE 0 END) AS owned_child_of_target_rows,
  SUM(CASE WHEN relation_type = 'overlap' THEN 1 ELSE 0 END) AS overlap_rows
FROM region_pack_relations
WHERE catalog_version = ${sqlString(catalogVersion)};
`);
