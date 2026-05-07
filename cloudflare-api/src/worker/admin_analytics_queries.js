let supportMissingManifestCache = {
  loadedAtMs: 0,
  expiresAtMs: 0,
  key: "",
  version: "",
  generatedAt: "",
  byLayer: {},
};

let cloudBillableUsageCache = {
  expiresAtMs: 0,
  cacheKey: "",
  value: null,
};

const R2_CLASS_A_ACTION_TYPES = new Set([
  "listbuckets",
  "putbucket",
  "listobjects",
  "putobject",
  "copyobject",
  "completemultipartupload",
  "createmultipartupload",
  "lifecyclestoragetiertransition",
  "listmultipartuploads",
  "uploadpart",
  "uploadpartcopy",
  "listparts",
  "putbucketencryption",
  "putbucketcors",
  "putbucketlifecycleconfiguration",
]);

const R2_CLASS_B_ACTION_TYPES = new Set([
  "headbucket",
  "headobject",
  "getobject",
  "usagesummary",
  "getbucketencryption",
  "getbucketlocation",
  "getbucketcors",
  "getbucketlifecycleconfiguration",
]);

const AUTH_REFRESH_CRITICAL_ERROR_CODES = new Set([
  "invalid_refresh_token",
  "refresh_token_revoked",
  "refresh_token_expired",
  "api_key_revoked",
  "account_blocked",
  "invalid_user_status",
  "account_not_connected",
]);


function authRefreshCriticalFailureSql(tableAlias = "") {
  const alias = String(tableAlias || "").trim();
  const columnPrefix = alias ? `${alias}.` : "";
  const errorCodeExpr = `LOWER(COALESCE(NULLIF(TRIM(${columnPrefix}error_code), ''), 'unknown_error'))`;
  const httpStatusExpr = `COALESCE(${columnPrefix}http_status, 0)`;
  const codeList = Array.from(AUTH_REFRESH_CRITICAL_ERROR_CODES)
    .map((code) => `'${String(code).replace(/'/g, "''")}'`)
    .join(", ");
  return `(${errorCodeExpr} IN (${codeList}) OR ${httpStatusExpr} IN (401, 403))`;
}

export function sanitizeAnalyticsMinutes(value, fallback, deps) {
  const parsed = deps.parseNonNegativeInteger(value, fallback);
  if (parsed <= 0) {
    return fallback;
  }
  return Math.min(deps.MAX_ANALYTICS_WINDOW_MINUTES, parsed);
}

export function sanitizeLiveTileMapMinutes(value, fallback, deps) {
  const parsed = deps.parseNonNegativeInteger(value, fallback);
  if (!deps.ALLOWED_LIVE_TILE_MAP_WINDOW_MINUTES.has(parsed)) {
    return fallback;
  }
  return parsed;
}

function normalizeTierCodeStrict(value, deps) {
  const normalized = String(deps.normalizePlanCode(value) || "").trim().toLowerCase();
  if (normalized === deps.PLAN_CODE_FREE) return deps.PLAN_CODE_FREE;
  if (normalized === deps.PLAN_CODE_PERSONAL) return deps.PLAN_CODE_PERSONAL;
  if (normalized === deps.PLAN_CODE_COMMERCIAL) return deps.PLAN_CODE_COMMERCIAL;
  return "";
}

function _normalizeErrorCode(value) {
  return String(value || "").trim().toLowerCase();
}

function _isTileNotFoundRow(row, deps) {
  const statusCode = deps.parseNonNegativeInteger(row && row.status_code, 0);
  if (statusCode !== 404) {
    return false;
  }
  const errorCode = _normalizeErrorCode(row && row.error_code);
  return !errorCode || errorCode === "tile_not_found";
}

async function loadSupportMissingManifest(env, deps) {
  const manifestKey = String(
    env.ADMIN_SUPPORT_MISSING_MANIFEST_KEY || deps.DEFAULT_ADMIN_SUPPORT_MISSING_MANIFEST_KEY,
  ).trim();
  const nowMs = Date.now();
  if (
    supportMissingManifestCache.key === manifestKey
    && nowMs < supportMissingManifestCache.expiresAtMs
    && supportMissingManifestCache.byLayer
  ) {
    return supportMissingManifestCache;
  }
  const bucket = env.PLANETKA_DATA;
  if (!bucket || !manifestKey) {
    supportMissingManifestCache = {
      loadedAtMs: nowMs,
      expiresAtMs: nowMs + (5 * 60 * 1000),
      key: manifestKey,
      version: "",
      generatedAt: "",
      byLayer: {},
    };
    return supportMissingManifestCache;
  }
  try {
    const object = await bucket.get(manifestKey);
    if (!object || !object.body) {
      supportMissingManifestCache = {
        loadedAtMs: nowMs,
        expiresAtMs: nowMs + (5 * 60 * 1000),
        key: manifestKey,
        version: "",
        generatedAt: "",
        byLayer: {},
      };
      return supportMissingManifestCache;
    }
    const raw = await object.text();
    const parsed = JSON.parse(String(raw || "{}"));
    const expected = parsed && parsed.expected_missing && typeof parsed.expected_missing === "object"
      ? parsed.expected_missing
      : {};
    const byLayer = {};
    for (const layer of ["PO", "EL", "WT"]) {
      const entries = Array.isArray(expected[layer]) ? expected[layer] : [];
      byLayer[layer] = new Set(entries.map((item) => String(item || "").trim()).filter(Boolean));
    }
    supportMissingManifestCache = {
      loadedAtMs: nowMs,
      expiresAtMs: nowMs + (10 * 60 * 1000),
      key: manifestKey,
      version: String(parsed && parsed.version || ""),
      generatedAt: String(parsed && parsed.generated_at || ""),
      byLayer,
    };
    return supportMissingManifestCache;
  } catch (_error) {
    supportMissingManifestCache = {
      loadedAtMs: nowMs,
      expiresAtMs: nowMs + (5 * 60 * 1000),
      key: manifestKey,
      version: "",
      generatedAt: "",
      byLayer: {},
    };
    return supportMissingManifestCache;
  }
}

function isExpectedSupportFallbackMiss(row, supportMissingManifest, deps) {
  if (!_isTileNotFoundRow(row, deps)) {
    return false;
  }
  const folder = String(row && row.folder || "").trim().toUpperCase();
  if (!["PO", "EL", "WT"].includes(folder)) {
    return false;
  }
  const fileName = String(row && row.file_name || "").trim();
  if (!fileName) {
    return true;
  }
  const byLayer = supportMissingManifest && supportMissingManifest.byLayer
    ? supportMissingManifest.byLayer
    : {};
  const layerSet = byLayer[folder];
  if (!(layerSet instanceof Set) || layerSet.size <= 0) {
    return true;
  }
  return layerSet.has(fileName);
}

function parseAnalyticsExcludedEmailPatterns(env = {}, deps) {
  const source = String(
    env.ANALYTICS_EXCLUDED_EMAIL_PATTERNS || deps.DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS,
  ).trim();
  if (!source) {
    return [];
  }
  const unique = new Set();
  for (const token of source.split(",")) {
    const pattern = String(token || "").trim().toLowerCase();
    if (!pattern) continue;
    unique.add(pattern);
  }
  return Array.from(unique);
}

function parseAnalyticsRevenueExcludedEmailPatterns(env = {}, deps) {
  const baseSource = String(
    env.ANALYTICS_EXCLUDED_EMAIL_PATTERNS || deps.DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS || "",
  ).trim();
  const revenueSource = String(
    env.ANALYTICS_REVENUE_EXCLUDED_EMAIL_PATTERNS
      || deps.DEFAULT_ANALYTICS_REVENUE_EXCLUDED_EMAIL_PATTERNS
      || "tom.griger@gmail.com,info@planetka.io,free@planetka.io,personal@planetka.io,commercial@planetka.io,credits@planetka.io",
  ).trim();
  const unique = new Set();
  for (const source of [baseSource, revenueSource]) {
    for (const token of String(source || "").split(",")) {
      const pattern = String(token || "").trim().toLowerCase();
      if (!pattern) continue;
      unique.add(pattern);
    }
  }
  return Array.from(unique);
}

function buildAnalyticsExcludedEmailFilter(emailColumnSql, env = {}, deps) {
  const patterns = parseAnalyticsExcludedEmailPatterns(env, deps);
  if (!patterns.length) {
    return { condition: "", bindings: [] };
  }
  const safeColumn = String(emailColumnSql || "").trim() || "user_email";
  const condition = patterns
    .map(() => `LOWER(COALESCE(${safeColumn}, '')) NOT LIKE ?`)
    .join(" AND ");
  return { condition, bindings: patterns };
}

function buildAnalyticsRevenueExcludedEmailFilter(emailColumnSql, env = {}, deps) {
  const patterns = parseAnalyticsRevenueExcludedEmailPatterns(env, deps);
  if (!patterns.length) {
    return { condition: "", bindings: [] };
  }
  const safeColumn = String(emailColumnSql || "").trim() || "user_email";
  const condition = patterns
    .map(() => `LOWER(COALESCE(${safeColumn}, '')) NOT LIKE ?`)
    .join(" AND ");
  return { condition, bindings: patterns };
}

function buildTileActivityPlanFilterSql(planFilter, deps) {
  void planFilter;
  void deps;
  return { clause: "", bindings: [] };
}

export function parseHeavyUserPlanFilter(value, deps) {
  void value;
  void deps;
  return "all";
}

export function parseAnalyticsUsersSort(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "resolves") return "paid_resolves";
  if (normalized === "lifetime") return "preview_lifetime";
  const allowed = new Set(["balance", "paid_eur", "standard", "paid_resolves", "paid_tiles", "data_downloaded", "preview_lifetime", "last_seen"]);
  return allowed.has(normalized) ? normalized : "paid_eur";
}

export function parseAnalyticsUsersSortDirection(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "asc" ? "asc" : "desc";
}

async function buildFallbackBillableUsageFromTelemetry(env, db, reason = "fallback_estimate", deps) {
  const nowUnix = Math.floor(Date.now() / 1000);
  const startDate = deps.monthStartIso(nowUnix);
  const endDate = new Date(nowUnix * 1000).toISOString();
  let monthClassBOps = 0;
  if (db) {
    monthClassBOps = await deps.countRowsFromQuery(
      db,
      `
        SELECT COUNT(*) AS count
        FROM tile_request_events
        WHERE created_at_unix >= ?
      `,
      [deps.monthStartUnix(nowUnix)],
    );
  }
  const estimate = deps.estimateR2MonthlyCostUsd(env, monthClassBOps);
  return {
    available: true,
    estimated: true,
    source: "telemetry_estimate",
    reason,
    period_start: startDate,
    period_end: endDate,
    bucket_filter: "",
    generated_at: deps.nowIso(),
    storage: {
      bytes: Math.max(0, Math.floor(Number(estimate.storage_gb_estimate || 0) * deps.BYTES_PER_GB)),
      gb: Number(Number(estimate.storage_gb_estimate || 0).toFixed(3)),
      object_count: 0,
      upload_count: 0,
      sample_datetime: "",
      free_gb: deps.clampNonNegativeInt(estimate.storage_gb_free),
      billable_gb_rounded: deps.clampNonNegativeInt(estimate.storage_gb_billable_rounded),
    },
    class_a: {
      operations: deps.clampNonNegativeInt(estimate.class_a_ops_estimate),
      free_operations: deps.clampNonNegativeInt(estimate.class_a_ops_free),
      billable_operations: deps.clampNonNegativeInt(estimate.class_a_ops_billable),
      billable_million_rounded: deps.clampNonNegativeInt(estimate.class_a_million_billable_rounded),
    },
    class_b: {
      operations: deps.clampNonNegativeInt(estimate.class_b_ops_month),
      free_operations: deps.clampNonNegativeInt(estimate.class_b_ops_free),
      billable_operations: deps.clampNonNegativeInt(estimate.class_b_ops_billable),
      billable_million_rounded: deps.clampNonNegativeInt(estimate.class_b_million_billable_rounded),
    },
    unknown_operations: 0,
    estimated_cost_usd: {
      storage: Number(Number(estimate.storage_cost_usd || 0).toFixed(2)),
      class_a: Number(Number(estimate.class_a_cost_usd || 0).toFixed(2)),
      class_b: Number(Number(estimate.class_b_cost_usd || 0).toFixed(2)),
      total: Number(Number(estimate.total_cost_usd || 0).toFixed(2)),
    },
  };
}

async function fetchCloudflareR2BillableUsage(env, db = null, deps) {
  const accountTag = String(
    env.CLOUDFLARE_ACCOUNT_ID
    || env.CF_ACCOUNT_ID
    || "",
  ).trim();
  const apiToken = String(
    env.CLOUDFLARE_GRAPHQL_API_TOKEN
    || env.CLOUDFLARE_API_TOKEN
    || "",
  ).trim();
  if (!accountTag || !apiToken) {
    try {
      return await buildFallbackBillableUsageFromTelemetry(env, db, "missing_graphql_credentials", deps);
    } catch (_error) {
      return {
        available: false,
        source: "cloud_live",
        reason: "not_configured",
        message: "Cloud billing credentials are not configured.",
      };
    }
  }
  const nowUnix = Math.floor(Date.now() / 1000);
  const startDate = deps.monthStartIso(nowUnix);
  const endDate = new Date(nowUnix * 1000).toISOString();
  const bucketName = String(
    env.CLOUDFLARE_R2_BILLING_BUCKET
    || env.R2_BILLING_BUCKET
    || "",
  ).trim();
  const ttlSeconds = Math.max(
    30,
    deps.parseNonNegativeInteger(
      env.CLOUDFLARE_BILLABLE_CACHE_TTL_SECONDS,
      deps.DEFAULT_CLOUDFLARE_BILLABLE_CACHE_TTL_SECONDS,
    ),
  );
  const cacheKey = [accountTag, bucketName || "*", startDate.slice(0, 7)].join("::");
  const nowMs = Date.now();
  if (
    cloudBillableUsageCache.cacheKey === cacheKey
    && cloudBillableUsageCache.value
    && nowMs < cloudBillableUsageCache.expiresAtMs
  ) {
    return cloudBillableUsageCache.value;
  }

  const hasBucketFilter = Boolean(bucketName);
  const query = `
    query PlanetkaR2BillableUsage($accountTag: string!, $startDate: Time!, $endDate: Time!${hasBucketFilter ? ", $bucketName: string!" : ""}) {
      viewer {
        accounts(filter: { accountTag: $accountTag }) {
          r2OperationsAdaptiveGroups(
            limit: 10000
            filter: {
              datetime_geq: $startDate
              datetime_leq: $endDate
              ${hasBucketFilter ? "bucketName: $bucketName" : ""}
            }
          ) {
            sum {
              requests
            }
            dimensions {
              actionType
            }
          }
          r2StorageAdaptiveGroups(
            limit: 1
            filter: {
              datetime_leq: $endDate
              ${hasBucketFilter ? "bucketName: $bucketName" : ""}
            }
            orderBy: [datetime_DESC]
          ) {
            max {
              objectCount
              uploadCount
              payloadSize
              metadataSize
            }
            dimensions {
              datetime
              bucketName
            }
          }
        }
      }
    }
  `;
  const variables = {
    accountTag,
    startDate,
    endDate,
    ...(hasBucketFilter ? { bucketName } : {}),
  };

  try {
    const response = await fetch(
      "https://api.cloudflare.com/client/v4/graphql",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query, variables }),
      },
    );
    const payload = await response.json();
    const errors = Array.isArray(payload && payload.errors) ? payload.errors : [];
    if (!response.ok || errors.length > 0) {
      const errorMessage = errors.length > 0
        ? String(errors[0] && errors[0].message || "graphql_error")
        : String(payload && payload.errors || `http_${response.status}`);
      try {
        const fallback = await buildFallbackBillableUsageFromTelemetry(env, db, "graphql_query_failed", deps);
        fallback.message = deps.publicErrorMessage("Usage data is temporarily unavailable.");
        return fallback;
      } catch (_error) {
        return {
          available: false,
          source: "cloud_live",
          reason: "query_failed",
          message: errorMessage,
        };
      }
    }

    const accounts = (((payload || {}).data || {}).viewer || {}).accounts;
    const account = Array.isArray(accounts) && accounts.length > 0 ? accounts[0] : null;
    const opRows = Array.isArray(account && account.r2OperationsAdaptiveGroups)
      ? account.r2OperationsAdaptiveGroups
      : [];
    const storageRows = Array.isArray(account && account.r2StorageAdaptiveGroups)
      ? account.r2StorageAdaptiveGroups
      : [];

    let classAOps = 0;
    let classBOps = 0;
    let unknownOps = 0;
    for (const row of opRows) {
      const actionType = String(((row || {}).dimensions || {}).actionType || "").trim().toLowerCase();
      const requests = deps.clampNonNegativeInt(((row || {}).sum || {}).requests);
      if (!actionType) {
        unknownOps += requests;
        continue;
      }
      if (R2_CLASS_A_ACTION_TYPES.has(actionType)) {
        classAOps += requests;
      } else if (R2_CLASS_B_ACTION_TYPES.has(actionType)) {
        classBOps += requests;
      } else {
        unknownOps += requests;
      }
    }

    const storageRow = storageRows.length > 0 ? storageRows[0] : null;
    const storageMax = (storageRow && storageRow.max) || {};
    const payloadBytes = deps.clampNonNegativeInt(storageMax.payloadSize);
    const metadataBytes = deps.clampNonNegativeInt(storageMax.metadataSize);
    const totalStorageBytes = payloadBytes + metadataBytes;
    const storageGb = totalStorageBytes / deps.BYTES_PER_GB;
    const classAFreeOps = deps.parseNonNegativeInteger(env.R2_CLASS_A_FREE_OPS_PER_MONTH, deps.DEFAULT_R2_CLASS_A_FREE_OPS_PER_MONTH);
    const classBFreeOps = deps.parseNonNegativeInteger(env.R2_CLASS_B_FREE_OPS_PER_MONTH, deps.DEFAULT_R2_CLASS_B_FREE_OPS_PER_MONTH);
    const storageFreeGb = deps.parseNonNegativeInteger(env.R2_STORAGE_FREE_GB_MONTH, deps.DEFAULT_R2_STORAGE_FREE_GB_MONTH);
    const classAPricePerMillion = deps.parsePositiveNumber(
      env.R2_CLASS_A_PRICE_PER_MILLION_USD,
      deps.DEFAULT_R2_CLASS_A_PRICE_PER_MILLION_USD,
    );
    const classBPricePerMillion = deps.parsePositiveNumber(
      env.R2_CLASS_B_PRICE_PER_MILLION_USD,
      deps.DEFAULT_R2_CLASS_B_PRICE_PER_MILLION_USD,
    );
    const storagePricePerGbMonth = deps.parsePositiveNumber(
      env.R2_STORAGE_PRICE_PER_GB_MONTH_USD,
      deps.DEFAULT_R2_STORAGE_PRICE_PER_GB_MONTH_USD,
    );

    const classABillableOps = Math.max(0, classAOps - classAFreeOps);
    const classBBillableOps = Math.max(0, classBOps - classBFreeOps);
    const classABillableMillionRounded = classABillableOps > 0 ? Math.ceil(classABillableOps / 1000000) : 0;
    const classBBillableMillionRounded = classBBillableOps > 0 ? Math.ceil(classBBillableOps / 1000000) : 0;
    const storageBillableGbRounded = Math.max(0, Math.ceil(storageGb - storageFreeGb));
    const storageCostUsd = storageBillableGbRounded * storagePricePerGbMonth;
    const classACostUsd = classABillableMillionRounded * classAPricePerMillion;
    const classBCostUsd = classBBillableMillionRounded * classBPricePerMillion;
    const totalEstimatedUsd = storageCostUsd + classACostUsd + classBCostUsd;

    const result = {
      available: true,
      source: "cloud_live",
      period_start: startDate,
      period_end: endDate,
      bucket_filter: bucketName || "",
      generated_at: deps.nowIso(),
      storage: {
        bytes: totalStorageBytes,
        gb: Number(storageGb.toFixed(3)),
        object_count: deps.clampNonNegativeInt(storageMax.objectCount),
        upload_count: deps.clampNonNegativeInt(storageMax.uploadCount),
        sample_datetime: String(((storageRow || {}).dimensions || {}).datetime || ""),
        free_gb: storageFreeGb,
        billable_gb_rounded: storageBillableGbRounded,
      },
      class_a: {
        operations: classAOps,
        free_operations: classAFreeOps,
        billable_operations: classABillableOps,
        billable_million_rounded: classABillableMillionRounded,
      },
      class_b: {
        operations: classBOps,
        free_operations: classBFreeOps,
        billable_operations: classBBillableOps,
        billable_million_rounded: classBBillableMillionRounded,
      },
      unknown_operations: unknownOps,
      estimated_cost_usd: {
        storage: Number(storageCostUsd.toFixed(2)),
        class_a: Number(classACostUsd.toFixed(2)),
        class_b: Number(classBCostUsd.toFixed(2)),
        total: Number(totalEstimatedUsd.toFixed(2)),
      },
    };
    cloudBillableUsageCache = {
      cacheKey,
      value: result,
      expiresAtMs: nowMs + (ttlSeconds * 1000),
    };
    return result;
  } catch (_error) {
    try {
      const fallback = await buildFallbackBillableUsageFromTelemetry(env, db, "graphql_request_failed", deps);
      fallback.message = deps.publicErrorMessage("Usage data is temporarily unavailable.");
      return fallback;
    } catch (__error) {
      return {
        available: false,
        source: "cloud_live",
        reason: "request_failed",
        message: deps.publicErrorMessage("Usage data is temporarily unavailable."),
      };
    }
  }
}

export async function collectAnalyticsSnapshot(
  db,
  minutes,
  planFilter = "all",
  liveTileMapWindowMinutes,
  env = {},
  deps,
) {
  await deps.ensureTileRequestEventsTable(db);
  await deps.ensureTileRequestRollupTables(db);
  await deps.ensureAuthRefreshEventsTable(db);
  if (typeof deps.ensureCreditTables === "function") {
    await deps.ensureCreditTables(db);
  }
  const nowUnix = Math.floor(Date.now() / 1000);
  const windowMinutes = sanitizeAnalyticsMinutes(minutes, deps.DEFAULT_ANALYTICS_WINDOW_MINUTES, deps);
  const windowStartUnix = Math.max(0, nowUnix - (windowMinutes * 60));
  const rollupStart30d = Math.max(0, nowUnix - (30 * 86400));
  const safePlanFilter = parseHeavyUserPlanFilter(planFilter, deps);
  const authRefreshWindowSeconds = Math.max(
    3600,
    deps.parseNonNegativeInteger(env.AUTH_REFRESH_HEALTH_WINDOW_SECONDS, deps.DEFAULT_AUTH_REFRESH_HEALTH_WINDOW_SECONDS),
  );
  const authRefreshWindowStartUnix = Math.max(0, nowUnix - authRefreshWindowSeconds);
  const eventEmailFilter = buildAnalyticsExcludedEmailFilter("user_email", env, deps);
  const eventEmailFilterAliasE = buildAnalyticsExcludedEmailFilter("e.user_email", env, deps);
  const userEmailFilter = buildAnalyticsExcludedEmailFilter("email", env, deps);
  const rollupEmailFilter = buildAnalyticsExcludedEmailFilter("user_email", env, deps);
  const rollupEmailFilterAliasR = buildAnalyticsExcludedEmailFilter("r.user_email", env, deps);
  const heavyEmailFilter = buildAnalyticsExcludedEmailFilter("agg.user_email", env, deps);
  const authRefreshEmailFilter = buildAnalyticsExcludedEmailFilter("user_email", env, deps);
  const revenueEmailFilterAliasU = buildAnalyticsRevenueExcludedEmailFilter("u.email", env, deps);

  const summary = await deps.dbGet(
    db,
    `
      SELECT
        COUNT(*) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END), 0) AS error_count,
        COALESCE(SUM(CASE WHEN UPPER(COALESCE(cache_status, '')) = 'HIT' THEN 1 ELSE 0 END), 0) AS cache_hit_count,
        COALESCE(SUM(CASE WHEN resolve_id IS NOT NULL AND resolve_id != '' THEN 1 ELSE 0 END), 0) AS tagged_request_count,
        COALESCE(COUNT(DISTINCT CASE WHEN resolve_id IS NOT NULL AND resolve_id != '' THEN resolve_id END), 0) AS tagged_resolve_count
      FROM tile_request_events
      WHERE created_at_unix >= ?
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
    `,
    [windowStartUnix, ...eventEmailFilter.bindings],
  );

  const topLineUsers = await deps.dbGet(
    db,
    `
      WITH users_normalized AS (
        SELECT
          CASE
            WHEN LOWER(COALESCE(status, '')) = 'commercial' THEN 'commercial'
            WHEN LOWER(COALESCE(status, '')) = 'personal' THEN 'personal'
            ELSE 'free'
          END AS tier_code
        FROM users
        WHERE 1 = 1
        ${userEmailFilter.condition ? `AND ${userEmailFilter.condition}` : ""}
      )
      SELECT
        COALESCE(SUM(CASE WHEN tier_code = 'free' THEN 1 ELSE 0 END), 0) AS free_users,
        COALESCE(SUM(CASE WHEN tier_code = 'personal' THEN 1 ELSE 0 END), 0) AS personal_users,
        COALESCE(SUM(CASE WHEN tier_code = 'commercial' THEN 1 ELSE 0 END), 0) AS commercial_users,
        COUNT(*) AS total_users
      FROM users_normalized
    `,
    [...userEmailFilter.bindings],
  );

  const topLineTraffic = await deps.dbGet(
    db,
    `
      WITH traffic AS (
        SELECT
          r.request_count,
          r.bytes_served,
          NULLIF(TRIM(LOWER(u.status)), '') AS plan_norm
        FROM tile_request_rollup_daily_account r
        LEFT JOIN users u ON u.id = r.user_id
        WHERE 1 = 1
        ${rollupEmailFilterAliasR.condition ? `AND ${rollupEmailFilterAliasR.condition}` : ""}
      )
      SELECT
        COALESCE(SUM(CASE WHEN plan_norm = 'free' THEN request_count ELSE 0 END), 0) AS free_requests,
        COALESCE(SUM(CASE WHEN plan_norm = 'personal' THEN request_count ELSE 0 END), 0) AS personal_requests,
        COALESCE(SUM(CASE WHEN plan_norm = 'commercial' THEN request_count ELSE 0 END), 0) AS commercial_requests,
        COALESCE(SUM(request_count), 0) AS total_requests,
        COALESCE(SUM(CASE WHEN plan_norm = 'free' THEN bytes_served ELSE 0 END), 0) AS free_bytes,
        COALESCE(SUM(CASE WHEN plan_norm = 'personal' THEN bytes_served ELSE 0 END), 0) AS personal_bytes,
        COALESCE(SUM(CASE WHEN plan_norm = 'commercial' THEN bytes_served ELSE 0 END), 0) AS commercial_bytes,
        COALESCE(SUM(bytes_served), 0) AS total_bytes
      FROM traffic
    `,
    [...rollupEmailFilterAliasR.bindings],
  );

  const topLineResolves = await deps.dbGet(
    db,
    `
      WITH tagged_resolves AS (
        SELECT DISTINCT
          e.user_id,
          e.resolve_id,
          NULLIF(TRIM(LOWER(u.status)), '') AS plan_norm
        FROM tile_request_events e
        LEFT JOIN users u ON u.id = e.user_id
        WHERE
          e.resolve_id IS NOT NULL
          AND e.resolve_id != ''
          ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      )
      SELECT
        COALESCE(SUM(CASE WHEN plan_norm = 'free' THEN 1 ELSE 0 END), 0) AS free_resolves,
        COALESCE(SUM(CASE WHEN plan_norm = 'personal' THEN 1 ELSE 0 END), 0) AS personal_resolves,
        COALESCE(SUM(CASE WHEN plan_norm = 'commercial' THEN 1 ELSE 0 END), 0) AS commercial_resolves,
        COUNT(*) AS total_resolves
      FROM tagged_resolves
    `,
    [...eventEmailFilterAliasE.bindings],
  );

  const topLineRevenue = await deps.dbGet(
    db,
    `
      WITH paid_ledger AS (
        SELECT
          LOWER(COALESCE(cl.reason, '')) AS reason_norm,
          COALESCE(cl.delta_credits, 0) AS delta_credits,
          CASE
            WHEN json_valid(COALESCE(cl.metadata_json, '')) THEN cl.metadata_json
            ELSE NULL
          END AS metadata_json
        FROM credit_ledger cl
        LEFT JOIN users u ON u.id = cl.user_id
        WHERE LOWER(COALESCE(cl.reason, '')) IN ('stripe_balance_top_up', 'stripe_scene_purchase', 'stripe_standard_quality_unlock', 'stripe_region_pack_purchase')
        ${revenueEmailFilterAliasU.condition ? `AND ${revenueEmailFilterAliasU.condition}` : ""}
      ),
      paid_amounts AS (
        SELECT
          CASE
            WHEN reason_norm = 'stripe_balance_top_up' THEN COALESCE(
              CAST(json_extract(metadata_json, '$.stripe_amount_paid_eur') AS REAL),
              ABS(delta_credits),
              0
            )
            WHEN reason_norm = 'stripe_scene_purchase' THEN COALESCE(
              CAST(json_extract(metadata_json, '$.paid_eur') AS REAL),
              CAST(json_extract(metadata_json, '$.nominal_eur') AS REAL),
              0
            )
            WHEN reason_norm = 'stripe_standard_quality_unlock' THEN COALESCE(
              CAST(json_extract(metadata_json, '$.paid_eur') AS REAL),
              0
            )
            WHEN reason_norm = 'stripe_region_pack_purchase' THEN COALESCE(
              CAST(json_extract(metadata_json, '$.paid_eur') AS REAL),
              CAST(json_extract(metadata_json, '$.nominal_eur') AS REAL),
              0
            )
            ELSE 0
          END AS amount_eur
        FROM paid_ledger
      )
      SELECT
        COALESCE(ROUND(SUM(CASE WHEN amount_eur > 0 THEN amount_eur ELSE 0 END) * 100.0) / 100.0, 0) AS total_earned_eur
      FROM paid_amounts
    `,
    [...revenueEmailFilterAliasU.bindings],
  );

  const topLinePaidResolves = await deps.dbGet(
    db,
    `
      SELECT COUNT(*) AS total_paid_resolves
      FROM credit_ledger cl
      LEFT JOIN users u ON u.id = cl.user_id
      WHERE LOWER(COALESCE(cl.reason, '')) IN ('tile_unlock', 'stripe_scene_purchase')
        AND json_valid(COALESCE(cl.metadata_json, ''))
        AND LOWER(COALESCE(json_extract(cl.metadata_json, '$.quality_mode'), '')) = 'full'
        AND COALESCE(CAST(json_extract(cl.metadata_json, '$.tile_count') AS INTEGER), 0) > 0
        ${revenueEmailFilterAliasU.condition ? `AND ${revenueEmailFilterAliasU.condition}` : ""}
    `,
    [...revenueEmailFilterAliasU.bindings],
  );

  const activeWindow6mStartUnix = Math.max(0, nowUnix - (180 * 86400));
  const activeWindow3mStartUnix = Math.max(0, nowUnix - (90 * 86400));
  const activeWindow1mStartUnix = Math.max(0, nowUnix - (30 * 86400));
  const activeWindow1wStartUnix = Math.max(0, nowUnix - (7 * 86400));
  const activeWindow1dStartUnix = Math.max(0, nowUnix - 86400);
  const activeWindow1hStartUnix = Math.max(0, nowUnix - 3600);
  const activeUserRows = await deps.dbAll(
    db,
    `
      SELECT
        e.user_id,
        MAX(e.created_at_unix) AS last_seen_unix,
        NULLIF(TRIM(LOWER(u.status)), '') AS plan_norm
      FROM tile_request_events e
      LEFT JOIN users u ON u.id = e.user_id
      WHERE
        e.created_at_unix >= ?
        AND e.user_id IS NOT NULL
        AND e.user_id != ''
        ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      GROUP BY
        e.user_id,
        NULLIF(TRIM(LOWER(u.status)), '')
    `,
    [
      activeWindow6mStartUnix,
      ...eventEmailFilterAliasE.bindings,
    ],
  );

  const makeActiveSplit = () => ({
    free: 0,
    personal: 0,
    commercial: 0,
    total: 0,
  });
  const activeWindows = {
    users_6m: makeActiveSplit(),
    users_3m: makeActiveSplit(),
    users_1m: makeActiveSplit(),
    users_1w: makeActiveSplit(),
    users_1d: makeActiveSplit(),
    users_1h: makeActiveSplit(),
  };
  const activeThresholds = [
    ["users_6m", activeWindow6mStartUnix],
    ["users_3m", activeWindow3mStartUnix],
    ["users_1m", activeWindow1mStartUnix],
    ["users_1w", activeWindow1wStartUnix],
    ["users_1d", activeWindow1dStartUnix],
    ["users_1h", activeWindow1hStartUnix],
  ];
  const resolveAnalyticsTierCode = (planValue) => {
    const normalized = normalizeTierCodeStrict(planValue, deps);
    if (normalized === deps.PLAN_CODE_COMMERCIAL) return "commercial";
    if (normalized === deps.PLAN_CODE_PERSONAL) return "personal";
    if (normalized === deps.PLAN_CODE_FREE) return "free";
    return "";
  };
  for (const row of (Array.isArray(activeUserRows) ? activeUserRows : [])) {
    const lastSeenUnix = deps.clampNonNegativeInt(row && row.last_seen_unix);
    if (lastSeenUnix <= 0) {
      continue;
    }
    const tierCode = resolveAnalyticsTierCode(row && row.plan_norm);
    for (const [windowKey, thresholdUnix] of activeThresholds) {
      if (lastSeenUnix < thresholdUnix) {
        continue;
      }
      const windowCounts = activeWindows[windowKey];
      if (!windowCounts) {
        continue;
      }
      if (!tierCode) {
        continue;
      }
      windowCounts.total += 1;
      if (tierCode === "commercial") {
        windowCounts.commercial += 1;
      } else if (tierCode === "personal") {
        windowCounts.personal += 1;
      } else {
        windowCounts.free += 1;
      }
    }
  }

  let activeUsers10m = [];
  try {
    activeUsers10m = await deps.dbAll(
      db,
      `
        SELECT
          e.user_id,
          COALESCE(NULLIF(TRIM(e.user_email), ''), COALESCE(NULLIF(TRIM(u.email), ''), '')) AS user_email,
          NULLIF(TRIM(LOWER(u.status)), '') AS user_status,
          COUNT(*) AS request_count,
          COALESCE(COUNT(DISTINCT CASE WHEN e.resolve_id IS NOT NULL AND e.resolve_id != '' THEN e.resolve_id END), 0) AS resolve_count,
          COALESCE(SUM(e.bytes_served), 0) AS bytes_served,
          MAX(e.created_at) AS last_seen_at
        FROM tile_request_events e
        LEFT JOIN users u ON u.id = e.user_id
        WHERE
          e.created_at_unix >= ?
          AND e.status_code < 400
          ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
        GROUP BY
          e.user_id,
          COALESCE(NULLIF(TRIM(e.user_email), ''), COALESCE(NULLIF(TRIM(u.email), ''), '')),
          NULLIF(TRIM(LOWER(u.status)), '')
        ORDER BY MAX(e.created_at_unix) DESC, bytes_served DESC
      `,
      [
        Math.max(0, nowUnix - 600),
        ...eventEmailFilterAliasE.bindings,
      ],
    );
  } catch (error) {
    console.warn(
      "planetka.analytics.active_users_10m_query_failed",
      JSON.stringify({
        error: String(error && error.message || "active_users_10m_query_failed"),
      }),
    );
    activeUsers10m = [];
  }

  const activeNow = await deps.dbGet(
    db,
    `
      SELECT COUNT(*) AS active_download_rows
      FROM tile_request_events
      WHERE created_at_unix >= ?
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
    `,
    [Math.max(0, nowUnix - 10), ...eventEmailFilter.bindings],
  );

  const topUsers = await deps.dbAll(
    db,
    `
        SELECT
          e.user_id,
          e.user_email,
          NULLIF(TRIM(LOWER(u.status)), '') AS user_status,
          COUNT(*) AS request_count,
          COALESCE(COUNT(DISTINCT CASE WHEN e.resolve_id IS NOT NULL AND e.resolve_id != '' THEN e.resolve_id END), 0) AS resolve_count,
          COALESCE(SUM(e.bytes_served), 0) AS bytes_served,
          COALESCE(SUM(CASE WHEN e.status_code >= 400 THEN 1 ELSE 0 END), 0) AS error_count,
        MAX(e.created_at) AS last_seen_at
      FROM tile_request_events e
      LEFT JOIN users u ON u.id = e.user_id
      WHERE e.created_at_unix >= ?
      ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      GROUP BY e.user_id, e.user_email, NULLIF(TRIM(LOWER(u.status)), '')
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [windowStartUnix, ...eventEmailFilterAliasE.bindings],
  );

  const topTiles = await deps.dbAll(
    db,
    `
      SELECT
        tile_key,
        COUNT(*) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served
      FROM tile_request_events
      WHERE created_at_unix >= ? AND tile_key IS NOT NULL AND tile_key != ''
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
      GROUP BY tile_key
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [windowStartUnix, ...eventEmailFilter.bindings],
  );

  const tileMapWindowSeconds = Math.max(
    60,
    sanitizeLiveTileMapMinutes(
      liveTileMapWindowMinutes,
      deps.DEFAULT_LIVE_TILE_MAP_WINDOW_MINUTES,
      deps,
    ) * 60,
  );
  const tileMapStartUnix = Math.max(0, nowUnix - tileMapWindowSeconds);
  const tileMapRowLimit = 2500;
  const tileActivityFilter = buildTileActivityPlanFilterSql(safePlanFilter, deps);
  const tileMapRows = await deps.dbAll(
    db,
    `
      SELECT
        e.user_id,
        e.user_email,
        e.tile_key,
        MAX(e.created_at_unix) AS last_seen_unix,
        COUNT(*) AS request_count,
        COALESCE(SUM(e.bytes_served), 0) AS bytes_served,
        NULLIF(TRIM(LOWER(u.status)), '') AS user_status
      FROM tile_request_events e
      LEFT JOIN users u ON u.id = e.user_id
      WHERE
        e.created_at_unix >= ?
        AND e.status_code < 400
        AND e.tile_key IS NOT NULL
        AND e.tile_key != ''
        ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
        ${tileActivityFilter.clause}
      GROUP BY
        e.user_id,
        e.user_email,
        e.tile_key,
        NULLIF(TRIM(LOWER(u.status)), '')
      ORDER BY last_seen_unix DESC
      LIMIT ${tileMapRowLimit}
    `,
    [
      tileMapStartUnix,
      ...eventEmailFilterAliasE.bindings,
      ...tileActivityFilter.bindings,
    ],
  );

  const activeTileUsersSet = new Set();
  const activeTileKeysSet = new Set();
  const normalizedTileMapRows = Array.isArray(tileMapRows) ? tileMapRows.map((row) => {
    const userId = String(row && row.user_id || "").trim();
    const userEmail = deps.normalizeEmail(row && row.user_email || "");
    const userKey = userId || userEmail;
    if (userKey) {
      activeTileUsersSet.add(userKey);
    }
    const tileKey = String(row && row.tile_key || "").trim();
    if (tileKey) {
      activeTileKeysSet.add(tileKey);
    }
    return {
      user_id: userId,
      user_email: userEmail,
      user_status: normalizeTierCodeStrict(row && row.user_status, deps),
      tile_key: tileKey,
      last_seen_unix: deps.clampNonNegativeInt(row && row.last_seen_unix),
      request_count: deps.clampNonNegativeInt(row && row.request_count),
      bytes_served: deps.clampNonNegativeInt(row && row.bytes_served),
    };
  }) : [];

  const supportMissingManifest = await loadSupportMissingManifest(env, deps);
  const recentFailuresRaw = await deps.dbAll(
    db,
    `
      SELECT
        created_at,
        user_email,
        folder,
        file_name,
        tile_key,
        status_code,
        error_code,
        cache_status,
        duration_ms
      FROM tile_request_events
      WHERE status_code >= 400
      ${eventEmailFilter.condition ? `AND ${eventEmailFilter.condition}` : ""}
      ORDER BY created_at_unix DESC
      LIMIT 50
    `,
    [...eventEmailFilter.bindings],
  );
  const recentFailures = [];
  for (const row of (Array.isArray(recentFailuresRaw) ? recentFailuresRaw : [])) {
    if (isExpectedSupportFallbackMiss(row, supportMissingManifest, deps)) {
      continue;
    }
    recentFailures.push(row);
  }

  const authRefreshSummary = await deps.dbGet(
    db,
    `
      SELECT
        COUNT(*) AS total_count,
        COALESCE(SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END), 0) AS success_count,
        COALESCE(SUM(CASE WHEN outcome != 'success' THEN 1 ELSE 0 END), 0) AS failure_count,
        COALESCE(COUNT(DISTINCT CASE WHEN outcome != 'success' AND user_id IS NOT NULL AND user_id != '' THEN user_id END), 0) AS failed_user_count,
        COALESCE(SUM(CASE WHEN outcome != 'success' AND ${authRefreshCriticalFailureSql()} THEN 1 ELSE 0 END), 0) AS critical_failure_count,
        COALESCE(COUNT(DISTINCT CASE WHEN outcome != 'success' AND ${authRefreshCriticalFailureSql()} AND user_id IS NOT NULL AND user_id != '' THEN user_id END), 0) AS critical_failed_user_count
      FROM auth_refresh_events
      WHERE created_at_unix >= ?
      ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );
  const authRefreshTopFailureUsers = await deps.dbAll(
    db,
    `
      SELECT
        user_id,
        user_email,
        COUNT(*) AS failure_count,
        MAX(created_at) AS last_failure_at
      FROM auth_refresh_events
      WHERE
        created_at_unix >= ?
        AND outcome != 'success'
        ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
      GROUP BY user_id, user_email
      ORDER BY failure_count DESC
      LIMIT 20
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );
  const authRefreshErrorBreakdown = await deps.dbAll(
    db,
    `
      SELECT
        COALESCE(NULLIF(TRIM(error_code), ''), 'unknown_error') AS error_code,
        COUNT(*) AS count
      FROM auth_refresh_events
      WHERE
        created_at_unix >= ?
        AND outcome != 'success'
        ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
      GROUP BY COALESCE(NULLIF(TRIM(error_code), ''), 'unknown_error')
      ORDER BY count DESC
      LIMIT 20
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );
  const authRefreshTopCriticalFailureUsers = await deps.dbAll(
    db,
    `
      SELECT
        user_id,
        user_email,
        COUNT(*) AS failure_count,
        MAX(created_at) AS last_failure_at
      FROM auth_refresh_events
      WHERE
        created_at_unix >= ?
        AND outcome != 'success'
        AND ${authRefreshCriticalFailureSql()}
        ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
      GROUP BY user_id, user_email
      ORDER BY failure_count DESC
      LIMIT 20
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );
  const authRefreshCriticalErrorBreakdown = await deps.dbAll(
    db,
    `
      SELECT
        COALESCE(NULLIF(TRIM(error_code), ''), 'unknown_error') AS error_code,
        COUNT(*) AS count
      FROM auth_refresh_events
      WHERE
        created_at_unix >= ?
        AND outcome != 'success'
        AND ${authRefreshCriticalFailureSql()}
        ${authRefreshEmailFilter.condition ? `AND ${authRefreshEmailFilter.condition}` : ""}
      GROUP BY COALESCE(NULLIF(TRIM(error_code), ''), 'unknown_error')
      ORDER BY count DESC
      LIMIT 20
    `,
    [authRefreshWindowStartUnix, ...authRefreshEmailFilter.bindings],
  );

  const rollup30d = await deps.dbGet(
    db,
    `
      SELECT
        COALESCE(SUM(request_count), 0) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(error_count), 0) AS error_count,
        COALESCE(SUM(cache_hit_count), 0) AS cache_hit_count,
        COALESCE(SUM(tagged_request_count), 0) AS tagged_request_count,
        COUNT(DISTINCT user_id) AS active_users
      FROM tile_request_rollup_daily_account
      WHERE day_start_unix >= ?
      ${rollupEmailFilter.condition ? `AND ${rollupEmailFilter.condition}` : ""}
    `,
    [rollupStart30d, ...rollupEmailFilter.bindings],
  );

  const topAccounts30d = await deps.dbAll(
    db,
    `
      SELECT
        user_id,
        user_email,
        COALESCE(SUM(request_count), 0) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(error_count), 0) AS error_count,
        MAX(last_event_unix) AS last_event_unix
      FROM tile_request_rollup_daily_account
      WHERE day_start_unix >= ?
      ${rollupEmailFilter.condition ? `AND ${rollupEmailFilter.condition}` : ""}
      GROUP BY user_id, user_email
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [rollupStart30d, ...rollupEmailFilter.bindings],
  );

  const heavyWhereParts = [];
  const heavyBindings = [
    deps.monthStartUnix(nowUnix),
    deps.startOfWeekUnix(nowUnix),
    deps.startOfDayUnix(nowUnix),
    deps.monthStartUnix(nowUnix),
    deps.startOfHourUnix(nowUnix),
  ];
  if (heavyEmailFilter.condition) {
    heavyWhereParts.push(String(heavyEmailFilter.condition));
    heavyBindings.push(...heavyEmailFilter.bindings);
  }
  const heavyWhereSql = heavyWhereParts.length ? `WHERE ${heavyWhereParts.join(" AND ")}` : "";
  const heavyBaseSql = `
      WITH user_rollups AS (
        SELECT
          r.user_id,
          COALESCE(NULLIF(TRIM(u.email), ''), COALESCE(NULLIF(TRIM(r.user_email), ''), '')) AS user_email,
          NULLIF(TRIM(LOWER(u.status)), '') AS user_status,
          COALESCE(SUM(r.bytes_served), 0) AS lifetime_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS month_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS week_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.bytes_served ELSE 0 END), 0) AS day_bytes,
          COALESCE(SUM(CASE WHEN r.day_start_unix >= ? THEN r.request_count ELSE 0 END), 0) AS request_count_month,
          COALESCE(MAX(r.last_event_unix), 0) AS last_event_unix
        FROM tile_request_rollup_daily_account r
        LEFT JOIN users u ON u.id = r.user_id
        GROUP BY
          r.user_id,
          COALESCE(NULLIF(TRIM(u.email), ''), COALESCE(NULLIF(TRIM(r.user_email), ''), '')),
          NULLIF(TRIM(LOWER(u.status)), '')
      ),
      hour_rollups AS (
        SELECT
          user_id,
          COALESCE(SUM(bytes_served), 0) AS hour_bytes
        FROM tile_request_rollup_hourly_account
        WHERE bucket_start_unix >= ?
        GROUP BY user_id
      )
      SELECT
        agg.user_id,
        agg.user_email,
        agg.user_status,
        agg.lifetime_bytes,
        agg.month_bytes,
        agg.week_bytes,
        agg.day_bytes,
        COALESCE(hr.hour_bytes, 0) AS hour_bytes,
        agg.request_count_month,
        agg.last_event_unix
      FROM user_rollups agg
      LEFT JOIN hour_rollups hr ON hr.user_id = agg.user_id
      ${heavyWhereSql}
    `;
  const topHeavyLifetime = await deps.dbAll(db, `${heavyBaseSql} ORDER BY lifetime_bytes DESC LIMIT 50`, heavyBindings);
  const topHeavyMonth = await deps.dbAll(db, `${heavyBaseSql} ORDER BY month_bytes DESC LIMIT 50`, heavyBindings);
  const topHeavyWeek = await deps.dbAll(db, `${heavyBaseSql} ORDER BY week_bytes DESC LIMIT 50`, heavyBindings);
  const topHeavyDay = await deps.dbAll(db, `${heavyBaseSql} ORDER BY day_bytes DESC LIMIT 50`, heavyBindings);
  const topHeavyHour = await deps.dbAll(db, `${heavyBaseSql} ORDER BY hour_bytes DESC LIMIT 50`, heavyBindings);

  let heavyUsers30d = (Array.isArray(topHeavyLifetime) ? topHeavyLifetime : []).map((row) => ({
    user_id: String(row && row.user_id || "").trim(),
    user_email: deps.normalizeEmail(row && row.user_email || ""),
    user_status: normalizeTierCodeStrict(row && row.user_status, deps),
    lifetime_bytes: deps.clampNonNegativeInt(row && row.lifetime_bytes),
    month_bytes: deps.clampNonNegativeInt(row && row.month_bytes),
    request_count_month: deps.clampNonNegativeInt(row && row.request_count_month),
    last_event_unix: deps.clampNonNegativeInt(row && row.last_event_unix),
  }));
  heavyUsers30d = heavyUsers30d.map((row) => ({
    ...row,
    request_count_30d: deps.clampNonNegativeInt(row && row.request_count_month),
    bytes_served_30d: deps.clampNonNegativeInt(row && row.month_bytes),
  }));
  heavyUsers30d = heavyUsers30d
    .sort((a, b) => deps.clampNonNegativeInt(b && b.lifetime_bytes) - deps.clampNonNegativeInt(a && a.lifetime_bytes))
    .slice(0, 20);

  const heavyResolveCountByUserId = new Map();
  const heavyUserIds = Array.from(
    new Set(
      [
        ...(Array.isArray(topHeavyLifetime) ? topHeavyLifetime : []),
        ...(Array.isArray(topHeavyMonth) ? topHeavyMonth : []),
        ...(Array.isArray(topHeavyWeek) ? topHeavyWeek : []),
        ...(Array.isArray(topHeavyDay) ? topHeavyDay : []),
        ...(Array.isArray(topHeavyHour) ? topHeavyHour : []),
        ...(Array.isArray(heavyUsers30d) ? heavyUsers30d : []),
      ].map((row) => String(row && row.user_id || "").trim()).filter(Boolean),
    ),
  );
  if (heavyUserIds.length > 0) {
    const placeholders = heavyUserIds.map(() => "?").join(",");
    const heavyResolveRows = await deps.dbAll(
      db,
      `
        SELECT
          user_id,
          COUNT(DISTINCT resolve_id) AS resolve_count
        FROM tile_request_events
        WHERE
          user_id IN (${placeholders})
          AND resolve_id IS NOT NULL
          AND resolve_id != ''
        GROUP BY user_id
      `,
      heavyUserIds,
    );
    for (const row of heavyResolveRows || []) {
      const userId = String(row && row.user_id || "").trim();
      if (!userId) continue;
      heavyResolveCountByUserId.set(userId, deps.clampNonNegativeInt(row && row.resolve_count));
    }
  }
  const attachHeavyResolveCounts = (rows) =>
    (Array.isArray(rows) ? rows : []).map((row) => {
      const userId = String(row && row.user_id || "").trim();
      return {
        ...row,
        resolve_count: deps.clampNonNegativeInt(heavyResolveCountByUserId.get(userId) || 0),
      };
    });
  const normalizedActiveUsers10m = (Array.isArray(activeUsers10m) ? activeUsers10m : []).map((row) => ({
    user_id: String(row && row.user_id || "").trim(),
    user_email: deps.normalizeEmail(row && row.user_email || ""),
    user_status: normalizeTierCodeStrict(row && row.user_status, deps),
    request_count: deps.clampNonNegativeInt(row && row.request_count),
    resolve_count: deps.clampNonNegativeInt(row && row.resolve_count),
    bytes_served: deps.clampNonNegativeInt(row && row.bytes_served),
    last_seen_at: String(row && row.last_seen_at || ""),
  }));

  const cloudBillableUsage = await fetchCloudflareR2BillableUsage(env, db, deps);
  const totalEarnedEur = Number(topLineRevenue && topLineRevenue.total_earned_eur);

  return {
    generated_at: deps.nowIso(),
    window_minutes: windowMinutes,
    window_start_unix: windowStartUnix,
    top_line: {
      users: {
        free: deps.clampNonNegativeInt(topLineUsers && topLineUsers.free_users),
        personal: deps.clampNonNegativeInt(topLineUsers && topLineUsers.personal_users),
        commercial: deps.clampNonNegativeInt(topLineUsers && topLineUsers.commercial_users),
        total: deps.clampNonNegativeInt(topLineUsers && topLineUsers.total_users),
      },
      resolves: {
        free: deps.clampNonNegativeInt(topLineResolves && topLineResolves.free_resolves),
        personal: deps.clampNonNegativeInt(topLineResolves && topLineResolves.personal_resolves),
        commercial: deps.clampNonNegativeInt(topLineResolves && topLineResolves.commercial_resolves),
        total: deps.clampNonNegativeInt(topLineResolves && topLineResolves.total_resolves),
      },
      tile_requests: {
        free: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.free_requests),
        personal: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.personal_requests),
        commercial: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.commercial_requests),
        total: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.total_requests),
      },
      gb_served: {
        free: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.free_bytes),
        personal: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.personal_bytes),
        commercial: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.commercial_bytes),
        total: deps.clampNonNegativeInt(topLineTraffic && topLineTraffic.total_bytes),
      },
      earned_eur: {
        total: Number.isFinite(totalEarnedEur) ? Number(totalEarnedEur.toFixed(2)) : 0,
      },
      paid_resolves: {
        total: deps.clampNonNegativeInt(topLinePaidResolves && topLinePaidResolves.total_paid_resolves),
      },
    },
    summary: {
      request_count: deps.clampNonNegativeInt(summary && summary.request_count),
      bytes_served: deps.clampNonNegativeInt(summary && summary.bytes_served),
      error_count: deps.clampNonNegativeInt(summary && summary.error_count),
      cache_hit_count: deps.clampNonNegativeInt(summary && summary.cache_hit_count),
      tagged_request_count: deps.clampNonNegativeInt(summary && summary.tagged_request_count),
      tagged_resolve_count: deps.clampNonNegativeInt(summary && summary.tagged_resolve_count),
    },
    active: {
      users_total: deps.clampNonNegativeInt(topLineUsers && topLineUsers.total_users),
      users_6m: deps.clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.total),
      users_3m: deps.clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.total),
      users_1m: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.total),
      users_1w: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.total),
      users_1d: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.total),
      users_1h: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.total),
      windows: {
        "6m": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.free),
          personal: deps.clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.personal),
          commercial: deps.clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.commercial),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.users_6m && activeWindows.users_6m.total),
        },
        "3m": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.free),
          personal: deps.clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.personal),
          commercial: deps.clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.commercial),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.users_3m && activeWindows.users_3m.total),
        },
        "1m": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.free),
          personal: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.personal),
          commercial: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.commercial),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1m && activeWindows.users_1m.total),
        },
        "1w": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.free),
          personal: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.personal),
          commercial: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.commercial),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1w && activeWindows.users_1w.total),
        },
        "1d": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.free),
          personal: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.personal),
          commercial: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.commercial),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1d && activeWindows.users_1d.total),
        },
        "1h": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.free),
          personal: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.personal),
          commercial: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.commercial),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.users_1h && activeWindows.users_1h.total),
        },
      },
      tile_events_10s: deps.clampNonNegativeInt(activeNow && activeNow.active_download_rows),
    },
    active_users_10m: normalizedActiveUsers10m,
    top_users: Array.isArray(topUsers) ? topUsers : [],
    top_tiles: Array.isArray(topTiles) ? topTiles : [],
    recent_failures: Array.isArray(recentFailures) ? recentFailures : [],
    auth_refresh_health: {
      window_seconds: authRefreshWindowSeconds,
      window_start_unix: authRefreshWindowStartUnix,
      total_count: deps.clampNonNegativeInt(authRefreshSummary && authRefreshSummary.total_count),
      success_count: deps.clampNonNegativeInt(authRefreshSummary && authRefreshSummary.success_count),
      failure_count: deps.clampNonNegativeInt(authRefreshSummary && authRefreshSummary.failure_count),
      failed_user_count: deps.clampNonNegativeInt(authRefreshSummary && authRefreshSummary.failed_user_count),
      critical_failure_count: deps.clampNonNegativeInt(authRefreshSummary && authRefreshSummary.critical_failure_count),
      critical_failed_user_count: deps.clampNonNegativeInt(authRefreshSummary && authRefreshSummary.critical_failed_user_count),
      top_failure_users: Array.isArray(authRefreshTopFailureUsers) ? authRefreshTopFailureUsers : [],
      error_breakdown: Array.isArray(authRefreshErrorBreakdown) ? authRefreshErrorBreakdown : [],
      top_critical_failure_users: Array.isArray(authRefreshTopCriticalFailureUsers) ? authRefreshTopCriticalFailureUsers : [],
      critical_error_breakdown: Array.isArray(authRefreshCriticalErrorBreakdown) ? authRefreshCriticalErrorBreakdown : [],
    },
    rollup_30d: {
      window_days: 30,
      request_count: deps.clampNonNegativeInt(rollup30d && rollup30d.request_count),
      bytes_served: deps.clampNonNegativeInt(rollup30d && rollup30d.bytes_served),
      error_count: deps.clampNonNegativeInt(rollup30d && rollup30d.error_count),
      cache_hit_count: deps.clampNonNegativeInt(rollup30d && rollup30d.cache_hit_count),
      tagged_request_count: deps.clampNonNegativeInt(rollup30d && rollup30d.tagged_request_count),
      active_users: deps.clampNonNegativeInt(rollup30d && rollup30d.active_users),
      top_accounts: Array.isArray(topAccounts30d)
        ? topAccounts30d.map((row) => ({
          ...row,
          last_seen_at: Number.isFinite(Number(row && row.last_event_unix))
            ? new Date(Number(row.last_event_unix) * 1000).toISOString()
            : "",
        }))
        : [],
    },
    heavy_users: {
      plan_filter: safePlanFilter,
      top_lifetime: attachHeavyResolveCounts(topHeavyLifetime),
      top_month: attachHeavyResolveCounts(topHeavyMonth),
      top_week: attachHeavyResolveCounts(topHeavyWeek),
      top_day: attachHeavyResolveCounts(topHeavyDay),
      top_hour: attachHeavyResolveCounts(topHeavyHour),
    },
    heavy_users_30d: attachHeavyResolveCounts(heavyUsers30d),
    cloudflare_billable_usage: cloudBillableUsage,
    live_tile_map: {
      generated_at: deps.nowIso(),
      window_seconds: tileMapWindowSeconds,
      plan_filter: safePlanFilter,
      users_active: activeTileUsersSet.size,
      tiles_active: activeTileKeysSet.size,
      row_limit: tileMapRowLimit,
      rows: normalizedTileMapRows,
    },
  };
}

export async function listAnalyticsUsers(db, env, options = {}, deps) {
  await deps.ensureTileRequestEventsTable(db);
  await deps.ensureTileRequestRollupTables(db);
  await deps.ensureUserQualityAccessColumns(db);
  if (typeof deps.ensureCreditTables === "function") {
    await deps.ensureCreditTables(db);
  }
  const nowUnix = Math.floor(Date.now() / 1000);
  const currentHourUnix = deps.startOfHourUnix(nowUnix);
  const currentDayUnix = deps.startOfDayUnix(nowUnix);
  const sortBy = parseAnalyticsUsersSort(options.sort_by);
  const sortDir = parseAnalyticsUsersSortDirection(options.sort_dir);
  const query = String(options.query || "").trim().toLowerCase();
  const limit = Math.max(1, Math.min(5000, deps.parseNonNegativeInteger(options.limit, 5000)));
  const orderSqlByKey = {
    balance: "balance_credits",
    paid_eur: "paid_eur_lifetime",
    standard: "standard_quality_unlocked",
    paid_resolves: "paid_full_resolve_count",
    paid_tiles: "unlocked_tile_count",
    data_downloaded: "licenced_downloaded_bytes",
    preview_lifetime: "preview_lifetime_bytes",
    last_seen: "last_seen_unix",
  };
  const orderSql = orderSqlByKey[sortBy] || orderSqlByKey.paid_eur;
  const emailFilter = buildAnalyticsExcludedEmailFilter("u.email", env, deps);
  const whereParts = [];
  const bindings = [];
  if (emailFilter.condition) {
    whereParts.push(emailFilter.condition);
    bindings.push(...emailFilter.bindings);
  }
  if (query) {
    whereParts.push(`LOWER(COALESCE(u.email, '')) LIKE ?`);
    bindings.push(`%${query}%`);
  }
  const whereSql = whereParts.length ? `WHERE ${whereParts.join(" AND ")}` : "";
  return deps.dbAll(
    db,
    `
      WITH resolve_counts AS (
        SELECT
          user_id,
          COUNT(DISTINCT resolve_id) AS resolve_count
        FROM tile_request_events
        WHERE resolve_id IS NOT NULL AND resolve_id != ''
        GROUP BY user_id
      ),
      daily_usage AS (
        SELECT
          r.user_id,
          COALESCE(SUM(r.bytes_served), 0) AS lifetime_bytes,
          COALESCE(MAX(r.last_event_unix), 0) AS last_seen_unix
        FROM tile_request_rollup_daily_account r
        GROUP BY r.user_id
      ),
      preview_hour AS (
        SELECT
          user_id,
          COALESCE(SUM(bytes_served), 0) AS preview_hour_bytes,
          COALESCE(SUM(request_count), 0) AS preview_hour_requests,
          COALESCE(MAX(d004_unique_count), 0) AS preview_d004_unique_hour
        FROM preview_usage_hourly_account
        WHERE bucket_start_unix = ?
        GROUP BY user_id
      ),
      preview_day AS (
        SELECT
          user_id,
          COALESCE(SUM(bytes_served), 0) AS preview_day_bytes,
          COALESCE(SUM(request_count), 0) AS preview_day_requests
        FROM tile_request_rollup_daily_account_quality
        WHERE quality_mode = 'preview'
          AND day_start_unix = ?
        GROUP BY user_id
      ),
      preview_lifetime AS (
        SELECT
          user_id,
          COALESCE(SUM(bytes_served), 0) AS preview_lifetime_bytes,
          COALESCE(SUM(request_count), 0) AS preview_lifetime_requests
        FROM tile_request_rollup_daily_account_quality
        WHERE quality_mode = 'preview'
        GROUP BY user_id
      ),
      full_lifetime AS (
        SELECT
          user_id,
          COALESCE(SUM(bytes_served), 0) AS full_lifetime_bytes,
          COALESCE(SUM(request_count), 0) AS full_lifetime_requests
        FROM tile_request_rollup_daily_account_quality
        WHERE quality_mode = 'full'
        GROUP BY user_id
      ),
      paid_full_resolves AS (
        SELECT
          user_id,
          COUNT(*) AS paid_full_resolve_count
        FROM credit_ledger
        WHERE LOWER(COALESCE(reason, '')) IN ('tile_unlock', 'stripe_scene_purchase')
          AND LOWER(COALESCE(json_extract(metadata_json, '$.quality_mode'), '')) = 'full'
          AND COALESCE(CAST(json_extract(metadata_json, '$.tile_count') AS INTEGER), 0) > 0
        GROUP BY user_id
      ),
      paid_eur_lifetime AS (
        SELECT
          cl.user_id,
          COALESCE(ROUND(SUM(
            CASE
              WHEN LOWER(COALESCE(cl.reason, '')) = 'stripe_balance_top_up' THEN COALESCE(
                CAST(json_extract(CASE WHEN json_valid(COALESCE(cl.metadata_json, '')) THEN cl.metadata_json ELSE NULL END, '$.stripe_amount_paid_eur') AS REAL),
                ABS(COALESCE(cl.delta_credits, 0)),
                0
              )
              WHEN LOWER(COALESCE(cl.reason, '')) = 'stripe_scene_purchase' THEN COALESCE(
                CAST(json_extract(CASE WHEN json_valid(COALESCE(cl.metadata_json, '')) THEN cl.metadata_json ELSE NULL END, '$.paid_eur') AS REAL),
                CAST(json_extract(CASE WHEN json_valid(COALESCE(cl.metadata_json, '')) THEN cl.metadata_json ELSE NULL END, '$.nominal_eur') AS REAL),
                0
              )
              WHEN LOWER(COALESCE(cl.reason, '')) = 'stripe_standard_quality_unlock' THEN COALESCE(
                CAST(json_extract(CASE WHEN json_valid(COALESCE(cl.metadata_json, '')) THEN cl.metadata_json ELSE NULL END, '$.paid_eur') AS REAL),
                0
              )
              WHEN LOWER(COALESCE(cl.reason, '')) = 'stripe_region_pack_purchase' THEN COALESCE(
                CAST(json_extract(CASE WHEN json_valid(COALESCE(cl.metadata_json, '')) THEN cl.metadata_json ELSE NULL END, '$.paid_eur') AS REAL),
                CAST(json_extract(CASE WHEN json_valid(COALESCE(cl.metadata_json, '')) THEN cl.metadata_json ELSE NULL END, '$.nominal_eur') AS REAL),
                0
              )
              ELSE 0
            END
          ) * 100.0) / 100.0, 0) AS paid_eur_lifetime
        FROM credit_ledger cl
        WHERE LOWER(COALESCE(cl.reason, '')) IN ('stripe_balance_top_up', 'stripe_scene_purchase', 'stripe_standard_quality_unlock', 'stripe_region_pack_purchase')
        GROUP BY cl.user_id
      ),
      unlocked_tiles AS (
        SELECT
          user_id,
          COUNT(*) AS unlocked_tile_count
        FROM user_tile_entitlements
        GROUP BY user_id
      ),
      licenced_downloads AS (
        SELECT
          user_id,
          COALESCE(total_downloaded_bytes, 0) AS licenced_downloaded_bytes,
          COALESCE(total_downloaded_tiles, 0) AS licenced_downloaded_tiles,
          COALESCE(total_downloaded_files, 0) AS licenced_downloaded_files
        FROM user_licenced_download_stats
      )
      SELECT
        u.id AS user_id,
        u.email AS user_email,
        NULLIF(TRIM(LOWER(u.status)), '') AS user_status,
        COALESCE(NULLIF(TRIM(u.preview_fair_usage_hold_at), ''), '') AS preview_fair_usage_hold_at,
        COALESCE(NULLIF(TRIM(u.preview_fair_usage_hold_reason), ''), '') AS preview_fair_usage_hold_reason,
        COALESCE(ca.balance_credits, 0) AS balance_credits,
        COALESCE(ca.total_granted_credits, 0) AS total_granted_credits,
        COALESCE(ca.total_spent_credits, 0) AS total_spent_credits,
        COALESCE(pe.paid_eur_lifetime, 0) AS paid_eur_lifetime,
        CASE
          WHEN COALESCE(NULLIF(TRIM(ca.standard_quality_unlocked_at), ''), '') != '' THEN 1
          ELSE 0
        END AS standard_quality_unlocked,
        COALESCE(NULLIF(TRIM(ca.standard_quality_unlocked_at), ''), '') AS standard_quality_unlocked_at,
        COALESCE(ut.unlocked_tile_count, 0) AS unlocked_tile_count,
        COALESCE(rc.resolve_count, 0) AS resolve_count,
        COALESCE(du.lifetime_bytes, 0) AS lifetime_bytes,
        COALESCE(ph.preview_hour_bytes, 0) AS preview_hour_bytes,
        COALESCE(ph.preview_hour_requests, 0) AS preview_hour_requests,
        COALESCE(ph.preview_d004_unique_hour, 0) AS preview_d004_unique_hour,
        COALESCE(pd.preview_day_bytes, 0) AS preview_day_bytes,
        COALESCE(pd.preview_day_requests, 0) AS preview_day_requests,
        COALESCE(pl.preview_lifetime_bytes, 0) AS preview_lifetime_bytes,
        COALESCE(pl.preview_lifetime_requests, 0) AS preview_lifetime_requests,
        COALESCE(fl.full_lifetime_bytes, 0) AS full_lifetime_bytes,
        COALESCE(fl.full_lifetime_requests, 0) AS full_lifetime_requests,
        COALESCE(ld.licenced_downloaded_bytes, 0) AS licenced_downloaded_bytes,
        COALESCE(ld.licenced_downloaded_tiles, 0) AS licenced_downloaded_tiles,
        COALESCE(ld.licenced_downloaded_files, 0) AS licenced_downloaded_files,
        COALESCE(pfr.paid_full_resolve_count, 0) AS paid_full_resolve_count,
        COALESCE(
          NULLIF(TRIM(datetime(du.last_seen_unix, 'unixepoch')), ''),
          COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), ''))
        ) AS last_seen_at,
        COALESCE(du.last_seen_unix, strftime('%s', COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), ''))), 0) AS last_seen_unix
      FROM users u
      LEFT JOIN daily_usage du ON du.user_id = u.id
      LEFT JOIN resolve_counts rc ON rc.user_id = u.id
      LEFT JOIN preview_hour ph ON ph.user_id = u.id
      LEFT JOIN preview_day pd ON pd.user_id = u.id
      LEFT JOIN preview_lifetime pl ON pl.user_id = u.id
      LEFT JOIN full_lifetime fl ON fl.user_id = u.id
      LEFT JOIN paid_full_resolves pfr ON pfr.user_id = u.id
      LEFT JOIN paid_eur_lifetime pe ON pe.user_id = u.id
      LEFT JOIN user_credit_accounts ca ON ca.user_id = u.id
      LEFT JOIN unlocked_tiles ut ON ut.user_id = u.id
      LEFT JOIN licenced_downloads ld ON ld.user_id = u.id
      ${whereSql}
      ORDER BY ${orderSql} ${sortDir.toUpperCase()}, LOWER(COALESCE(u.email, '')) ASC
      LIMIT ${limit}
    `,
    [currentHourUnix, currentDayUnix, ...bindings],
  );
}
