const TILE_KEY_RE = /x(\d{3})_y(\d{3})_z(\d{3})_d(\d{3})/i;
const ASSET_RE = /^(?:S2|EL|WT|PO)_(x\d{3}_y\d{3}_z\d{3}_d\d{3})\.(?:exr|tif)$/i;
const FREE_D_THRESHOLD = 60;
const SESSION_CACHE = new Map();
const SESSION_CACHE_MAX = 512;

export function normalizeTileKey(value) {
  const raw = String(value || "").trim();
  const file = raw.split("/").pop() || raw;
  const assetMatch = ASSET_RE.exec(file);
  const source = assetMatch ? assetMatch[1] : raw;
  const match = TILE_KEY_RE.exec(source);
  if (!match) return "";
  const x = Number.parseInt(match[1], 10);
  const y = Number.parseInt(match[2], 10);
  const z = Number.parseInt(match[3], 10);
  const d = Number.parseInt(match[4], 10);
  if (![x, y, z, d].every(Number.isFinite)) return "";
  return `x${String(x).padStart(3, "0")}_y${String(y).padStart(3, "0")}_z${String(z).padStart(3, "0")}_d${String(d).padStart(3, "0")}`;
}

export function normalizeTileKeys(values) {
  const keys = [];
  const seen = new Set();
  for (const value of values || []) {
    const key = normalizeTileKey(value);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    keys.push(key);
  }
  return keys;
}

export function parseTileKey(value) {
  const key = normalizeTileKey(value);
  const match = TILE_KEY_RE.exec(key);
  if (!match) return null;
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

export function tileFamilyKey(parsed) {
  if (!parsed) return "";
  return `x${String(parsed.x).padStart(3, "0")}_y${String(parsed.y).padStart(3, "0")}_z${String(parsed.z).padStart(3, "0")}`;
}

export function isFreeCreditTileKey(tileKey) {
  const parsed = parseTileKey(tileKey);
  if (!parsed) return true;
  return parsed.d <= 0 || parsed.d >= FREE_D_THRESHOLD;
}

function sessionCacheSet(id, row) {
  const key = String(id || "").trim();
  if (!key) return;
  while (SESSION_CACHE.size >= SESSION_CACHE_MAX) {
    const oldest = SESSION_CACHE.keys().next().value;
    if (!oldest) break;
    SESSION_CACHE.delete(oldest);
  }
  SESSION_CACHE.set(key, { row, cached_at_ms: Date.now() });
}

function sessionCacheGet(id) {
  const key = String(id || "").trim();
  if (!key) return null;
  const cached = SESSION_CACHE.get(key);
  if (!cached || !cached.row) return null;
  const expiresAt = Date.parse(String(cached.row.expires_at || ""));
  if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
    SESSION_CACHE.delete(key);
    return null;
  }
  return cached.row;
}

export async function ensureTileDownloadSessionsTable(db, deps = {}) {
  if (!db) throw new Error("missing_db_binding");
  const dbRun = deps.dbRun || ((database, sql, bindings = []) => database.prepare(sql).bind(...bindings).run());
  await dbRun(
    db,
    `
      CREATE TABLE IF NOT EXISTS tile_download_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        resolve_id TEXT NOT NULL,
        quality_mode TEXT NOT NULL DEFAULT 'full',
        credit_enforced INTEGER NOT NULL DEFAULT 0,
        allowed_tiles_json TEXT NOT NULL DEFAULT '[]',
        allowed_tile_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
      )
    `,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_download_sessions_user_resolve ON tile_download_sessions(user_id, resolve_id, expires_at)`,
  );
  await dbRun(
    db,
    `CREATE INDEX IF NOT EXISTS idx_tile_download_sessions_expires ON tile_download_sessions(expires_at)`,
  );
}

export async function createTileDownloadSession(db, details = {}, deps = {}) {
  await ensureTileDownloadSessionsTable(db, deps);
  const dbRun = deps.dbRun || ((database, sql, bindings = []) => database.prepare(sql).bind(...bindings).run());
  const nowIso = deps.nowIso || (() => new Date().toISOString());
  const id = String(details.id || crypto.randomUUID()).trim();
  const userId = String(details.userId || details.user_id || "").trim();
  const resolveId = String(details.resolveId || details.resolve_id || "").trim().slice(0, 128);
  const rawQualityMode = String(details.qualityMode || details.quality_mode || "full").trim().toLowerCase();
  const qualityMode = rawQualityMode === "preview" || rawQualityMode === "balanced" ? rawQualityMode : "full";
  const allowedTiles = normalizeTileKeys(details.allowedTileKeys || details.allowed_tile_keys || details.tileKeys || details.tile_keys || []);
  const expiresAt = String(details.expiresAt || details.expires_at || "").trim() || new Date(Date.now() + 3600 * 1000).toISOString();
  const row = {
    id,
    user_id: userId,
    resolve_id: resolveId,
    quality_mode: qualityMode,
    credit_enforced: details.creditEnforced || details.credit_enforced ? 1 : 0,
    allowed_tiles_json: JSON.stringify(allowedTiles),
    allowed_tile_count: allowedTiles.length,
    created_at: String(details.createdAt || details.created_at || nowIso()),
    expires_at: expiresAt,
  };
  await dbRun(
    db,
    `
      INSERT OR REPLACE INTO tile_download_sessions (
        id, user_id, resolve_id, quality_mode, credit_enforced,
        allowed_tiles_json, allowed_tile_count, created_at, expires_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      row.id,
      row.user_id,
      row.resolve_id,
      row.quality_mode,
      row.credit_enforced,
      row.allowed_tiles_json,
      row.allowed_tile_count,
      row.created_at,
      row.expires_at,
    ],
  );
  sessionCacheSet(id, row);
  return { id, allowed_tile_count: allowedTiles.length, expires_at: expiresAt };
}

export async function loadTileDownloadSession(db, sessionId, deps = {}) {
  const id = String(sessionId || "").trim();
  if (!id) return null;
  const cached = sessionCacheGet(id);
  if (cached) return cached;
  await ensureTileDownloadSessionsTable(db, deps);
  const dbGet = deps.dbGet || (async (database, sql, bindings = []) => database.prepare(sql).bind(...bindings).first());
  const row = await dbGet(
    db,
    `
      SELECT id, user_id, resolve_id, quality_mode, credit_enforced,
             allowed_tiles_json, allowed_tile_count, created_at, expires_at
      FROM tile_download_sessions
      WHERE id = ?
      LIMIT 1
    `,
    [id],
  );
  if (!row || !row.id) return null;
  const expiresAtMs = Date.parse(String(row.expires_at || ""));
  if (Number.isFinite(expiresAtMs) && expiresAtMs <= Date.now()) return null;
  sessionCacheSet(id, row);
  return row;
}

function allowedFamilyMap(keys) {
  const exact = new Set();
  const families = new Map();
  for (const key of normalizeTileKeys(keys)) {
    const parsed = parseTileKey(key);
    if (!parsed) continue;
    exact.add(parsed.key);
    const family = tileFamilyKey(parsed);
    if (!family) continue;
    if (!families.has(family)) families.set(family, new Set());
    families.get(family).add(Number(parsed.d));
  }
  return { exact, families };
}

export function parseTileDownloadSessionAllowedTiles(row) {
  try {
    const parsed = JSON.parse(String(row && row.allowed_tiles_json || "[]"));
    return normalizeTileKeys(Array.isArray(parsed) ? parsed : []);
  } catch (_error) {
    return [];
  }
}

export async function isTileAllowedByDownloadSession(db, claims, tileKey, deps = {}, options = {}) {
  const key = normalizeTileKey(tileKey);
  if (!key || isFreeCreditTileKey(key)) return true;
  const sessionId = String(claims && (claims.sessionId || claims.session_id) || "").trim();
  if (!sessionId) return false;
  const row = await loadTileDownloadSession(db, sessionId, deps);
  if (!row || !row.id) return false;
  if (String(row.user_id || "").trim() !== String(claims && claims.userId || "").trim()) return false;
  if (String(row.resolve_id || "").trim() !== String(claims && claims.resolveId || "").trim()) return false;
  const allowed = allowedFamilyMap(parseTileDownloadSessionAllowedTiles(row));
  if (allowed.exact.has(key)) return true;
  const parsed = parseTileKey(key);
  if (!parsed) return false;
  let requestedD = Number(parsed.d);
  let family = tileFamilyKey(parsed);
  if (
    String(options && options.folder || "").trim().toUpperCase() === "EL"
    && Number(parsed.z) === 1
    && Number(parsed.d) === 1
  ) {
    requestedD = 2;
    family = `x${String(parsed.x).padStart(3, "0")}_y${String(parsed.y).padStart(3, "0")}_z001`;
  }
  const familyDs = allowed.families.get(family) || new Set();
  for (const d of familyDs) {
    if (Number(d) <= requestedD) return true;
  }
  return false;
}
