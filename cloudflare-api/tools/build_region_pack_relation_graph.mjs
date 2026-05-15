#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const productsFile = resolve(rootDir, "src/worker/region_packs.products.generated.js");
const tileDataFile = resolve(rootDir, "src/worker/region_packs.tile_data.generated.js");
const outputFile = resolve(rootDir, "src/worker/region_packs.relations.generated.js");

function extractJson(source, regex, label) {
  const match = source.match(regex);
  if (!match) {
    throw new Error(`Could not read ${label}.`);
  }
  return Function(`"use strict"; return (${match[1]});`)();
}

function safeInt(value) {
  const numeric = Number.parseInt(value, 10);
  return Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
}

function uniqueStrings(values) {
  const seen = new Set();
  const result = [];
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) {
      continue;
    }
    seen.add(text);
    result.push(text);
  }
  return result;
}

function relationType(targetId, ownedId, targetCount, ownedCount, overlapCount) {
  if (!overlapCount) {
    return "exclusive";
  }
  if (targetId === ownedId) {
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

function impactClass(target) {
  const id = String(target.id || "");
  const type = String(target.type || "");
  const tileCount = safeInt(target.tile_count);
  if (id === "world" || type === "world") {
    return "world";
  }
  if (type === "continent") {
    return "continent";
  }
  if (tileCount >= 8000) {
    return "large";
  }
  if (tileCount >= 1500) {
    return "medium";
  }
  return "small";
}

function buildRelationGraph({ catalogVersion, products, tileKeysByProduct, grossCentsByTile }) {
  const relationProducts = products
    .filter((product) => product && product.id && Array.isArray(tileKeysByProduct[product.id]))
    .map((product) => {
      const tileKeys = uniqueStrings(tileKeysByProduct[product.id]);
      return {
        id: String(product.id),
        type: String(product.type || ""),
        tile_count: tileKeys.length,
        base_gross_cents: safeInt(product.gross_cents),
        tile_keys: tileKeys,
      };
    })
    .filter((product) => product.id && product.tile_count > 0);

  const productById = new Map(relationProducts.map((product) => [product.id, product]));
  const productIdsByTile = new Map();
  for (const product of relationProducts) {
    for (const tileKey of product.tile_keys) {
      let productIds = productIdsByTile.get(tileKey);
      if (!productIds) {
        productIds = [];
        productIdsByTile.set(tileKey, productIds);
      }
      productIds.push(product.id);
    }
  }

  const byTarget = {};
  const byOwned = {};
  const typeCounts = {
    parent_covers_target: 0,
    owned_child_of_target: 0,
    overlap: 0,
  };
  let meaningfulEdgeCount = 0;

  for (const target of relationProducts) {
    const overlapByOwnedId = new Map();
    for (const tileKey of target.tile_keys) {
      const grossCents = safeInt(grossCentsByTile[tileKey]);
      const ownedIds = productIdsByTile.get(tileKey) || [];
      for (const ownedId of ownedIds) {
        if (ownedId === target.id) {
          continue;
        }
        let overlap = overlapByOwnedId.get(ownedId);
        if (!overlap) {
          overlap = {
            overlap_tile_count: 0,
            overlap_paid_tile_count: 0,
            overlap_free_tile_count: 0,
            overlap_base_gross_cents: 0,
          };
          overlapByOwnedId.set(ownedId, overlap);
        }
        overlap.overlap_tile_count += 1;
        overlap.overlap_base_gross_cents += grossCents;
        if (grossCents > 0) {
          overlap.overlap_paid_tile_count += 1;
        } else {
          overlap.overlap_free_tile_count += 1;
        }
      }
    }

    const targetRows = [];
    for (const [ownedId, overlap] of [...overlapByOwnedId.entries()].sort(([a], [b]) => a.localeCompare(b))) {
      const owned = productById.get(ownedId);
      if (!owned) {
        continue;
      }
      const type = relationType(
        target.id,
        owned.id,
        target.tile_count,
        owned.tile_count,
        overlap.overlap_tile_count,
      );
      if (type === "exclusive" || type === "self") {
        continue;
      }
      const row = [
        owned.id,
        type,
        overlap.overlap_tile_count,
        overlap.overlap_paid_tile_count,
        overlap.overlap_free_tile_count,
        overlap.overlap_base_gross_cents,
        target.tile_count,
        owned.tile_count,
        target.base_gross_cents,
        owned.base_gross_cents,
        impactClass(target),
      ];
      targetRows.push(row);
      const ownedRows = byOwned[owned.id] || [];
      ownedRows.push([
        target.id,
        type,
        overlap.overlap_tile_count,
        overlap.overlap_paid_tile_count,
        overlap.overlap_free_tile_count,
        overlap.overlap_base_gross_cents,
        target.tile_count,
        owned.tile_count,
        target.base_gross_cents,
        owned.base_gross_cents,
        impactClass(target),
      ]);
      byOwned[owned.id] = ownedRows;
      typeCounts[type] = (typeCounts[type] || 0) + 1;
      meaningfulEdgeCount += 1;
    }
    if (targetRows.length) {
      byTarget[target.id] = targetRows;
    }
  }

  for (const rows of Object.values(byOwned)) {
    rows.sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  }

  const productCount = relationProducts.length;
  const totalOrderedPairs = productCount * productCount;
  const selfPairCount = productCount;
  return {
    catalogVersion,
    byTarget,
    byOwned,
    counts: {
      product_count: productCount,
      meaningful_edge_count: meaningfulEdgeCount,
      parent_covers_target_edge_count: typeCounts.parent_covers_target || 0,
      owned_child_of_target_edge_count: typeCounts.owned_child_of_target || 0,
      overlap_edge_count: typeCounts.overlap || 0,
      self_pair_count: selfPairCount,
      omitted_exclusive_pair_count: Math.max(0, totalOrderedPairs - selfPairCount - meaningfulEdgeCount),
      total_ordered_pair_count: totalOrderedPairs,
    },
  };
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

const graph = buildRelationGraph({ catalogVersion, products, tileKeysByProduct, grossCentsByTile });
const output = [
  "// Generated by cloudflare-api/tools/build_region_pack_relation_graph.mjs. Do not edit by hand.",
  `export const GENERATED_REGION_PACK_RELATION_GRAPH_VERSION = ${JSON.stringify(catalogVersion)};`,
  "export const GENERATED_REGION_PACK_RELATION_TARGET_ROW_FIELDS = [\"owned_region_pack_id\",\"relation_type\",\"overlap_tile_count\",\"overlap_paid_tile_count\",\"overlap_free_tile_count\",\"overlap_base_gross_cents\",\"target_tile_count\",\"owned_tile_count\",\"target_base_gross_cents\",\"owned_base_gross_cents\",\"impact_class\"];",
  "export const GENERATED_REGION_PACK_RELATION_OWNED_ROW_FIELDS = [\"target_region_pack_id\",\"relation_type\",\"overlap_tile_count\",\"overlap_paid_tile_count\",\"overlap_free_tile_count\",\"overlap_base_gross_cents\",\"target_tile_count\",\"owned_tile_count\",\"target_base_gross_cents\",\"owned_base_gross_cents\",\"impact_class\"];",
  `export const GENERATED_REGION_PACK_RELATIONS_BY_TARGET = ${JSON.stringify(graph.byTarget)};`,
  `export const GENERATED_REGION_PACK_RELATIONS_BY_OWNED = ${JSON.stringify(graph.byOwned)};`,
  `export const GENERATED_REGION_PACK_RELATION_COUNTS = ${JSON.stringify(graph.counts)};`,
  "",
].join("\n");

writeFileSync(outputFile, output, "utf8");
console.log(`Wrote ${outputFile}`);
console.log(JSON.stringify(graph.counts, null, 2));
