import fs from 'fs';
import { GENERATED_REGION_PACK_TILE_KEYS, GENERATED_REGION_PACK_TILE_GROSS_CENTS } from '../src/worker/region_packs.tile_data.generated.js';
import { GENERATED_REGION_PACK_RELATIONS_BY_TARGET } from '../src/worker/region_packs.relations.generated.js';

const catalog = 'gadm_regions_v9';
const impacted = new Set(['pacific_islands','oceania']);
const rowFields = ['owned_region_pack_id','relation_type','overlap_tile_count','overlap_paid_tile_count','overlap_free_tile_count','overlap_base_gross_cents','target_tile_count','owned_tile_count','target_base_gross_cents','owned_base_gross_cents','impact_class'];
const quoteUsers = ['tom.griger@gmail.com','free@planetka.io'];
function q(s){ return `'${String(s).replaceAll("'", "''")}'`; }
function chunk(arr, n){ const out=[]; for(let i=0;i<arr.length;i+=n) out.push(arr.slice(i,i+n)); return out; }
function parseKey(key){
  const m = /^x(\d+)_y(\d+)_z(\d+)_d(\d+)$/.exec(key);
  if (!m) throw new Error(`bad tile ${key}`);
  return {x:+m[1], y:+m[2], z:+m[3], d:+m[4]};
}
let sql=[];
sql.push('-- Generated targeted refresh for Pacific Islands / Australia and Oceania.');
sql.push(`DELETE FROM region_pack_tile_entries WHERE catalog_version=${q(catalog)} AND region_pack_id IN (${[...impacted].map(q).join(',')});`);
sql.push(`DELETE FROM region_pack_relations WHERE catalog_version=${q(catalog)} AND (target_region_pack_id IN (${[...impacted].map(q).join(',')}) OR owned_region_pack_id IN (${[...impacted].map(q).join(',')}));`);
sql.push(`DELETE FROM user_product_quotes WHERE catalog_version=${q(catalog)} AND product_id IN (${[...impacted].map(q).join(',')});`);
sql.push(`DELETE FROM pricing_quotes WHERE catalog_version=${q(catalog)} AND quote_type='region_pack' AND subject_id IN (${[...impacted].map(q).join(',')});`);
const tileRows=[];
for (const id of impacted) {
  for (const key of GENERATED_REGION_PACK_TILE_KEYS[id] || []) {
    const {x,y,z,d}=parseKey(key);
    const family = key.replace(/_d\d+$/, '');
    const gross = GENERATED_REGION_PACK_TILE_GROSS_CENTS[key] || 0;
    tileRows.push(`(${q(catalog)},${q(id)},${q(key)},${q(family)},${x},${y},${z},${d},${gross},${gross > 0 ? 0 : 1})`);
  }
}
for (const part of chunk(tileRows, 350)) {
  sql.push('INSERT OR REPLACE INTO region_pack_tile_entries (catalog_version, region_pack_id, tile_key, family_key, x, y, z, d, base_gross_cents, globally_free) VALUES');
  sql.push(part.join(',\n') + ';');
}
const relationRows=[];
for (const [target, rows] of Object.entries(GENERATED_REGION_PACK_RELATIONS_BY_TARGET)) {
  for (const arr of rows) {
    const rec = Object.fromEntries(rowFields.map((f,i)=>[f, arr[i]]));
    if (!impacted.has(target) && !impacted.has(rec.owned_region_pack_id)) continue;
    relationRows.push(`(${q(catalog)},${q(target)},${q(rec.owned_region_pack_id)},${q(rec.relation_type)},${rec.target_tile_count|0},${rec.owned_tile_count|0},${rec.overlap_tile_count|0},${rec.overlap_paid_tile_count|0},${rec.overlap_free_tile_count|0},${rec.overlap_base_gross_cents|0},${rec.target_base_gross_cents|0},${rec.owned_base_gross_cents|0},datetime('now'))`);
  }
}
for (const part of chunk(relationRows, 250)) {
  sql.push('INSERT OR REPLACE INTO region_pack_relations (catalog_version, target_region_pack_id, owned_region_pack_id, relation_type, target_tile_count, owned_tile_count, overlap_tile_count, overlap_paid_tile_count, overlap_free_tile_count, overlap_base_gross_cents, target_base_gross_cents, owned_base_gross_cents, computed_at) VALUES');
  sql.push(part.join(',\n') + ';');
}
sql.push(`DELETE FROM quote_recalculation_jobs WHERE catalog_version=${q(catalog)} AND product_id IN (${[...impacted].map(q).join(',')});`);
for (const email of quoteUsers) {
  for (const product of impacted) {
    sql.push(`INSERT INTO quote_recalculation_jobs (job_id, user_id, product_id, catalog_version, priority, status, reason, created_at, updated_at) SELECT lower(hex(randomblob(16))), id, ${q(product)}, ${q(catalog)}, 0, 'queued', 'oceania_product_refresh', datetime('now'), datetime('now') FROM accounts WHERE lower(email)=lower(${q(email)});`);
  }
}
fs.writeFileSync('generated/oceania_pacific_refresh.sql', sql.join('\n') + '\n');
console.log(JSON.stringify({tileRows: tileRows.length, relationRows: relationRows.length, out:'generated/oceania_pacific_refresh.sql'}, null, 2));
