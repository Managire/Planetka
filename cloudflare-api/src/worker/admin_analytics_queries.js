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
  "session_blocked",
  "invalid_install_status",
  "cloud_session_not_connected",
]);

function normalizeAnalyticsEdition(value) {
  return String(value || "").trim().toLowerCase() === "pro" ? "pro" : "free";
}

function latestInstallEditionCte() {
  return `
      latest_install_editions AS (
        SELECT
          user_id,
          CASE
            WHEN LOWER(COALESCE(install_edition, '')) = 'pro' THEN 'pro'
            ELSE 'free'
          END AS install_edition
        FROM (
          SELECT
            user_id,
            install_edition,
            ROW_NUMBER() OVER (
              PARTITION BY user_id
              ORDER BY datetime(COALESCE(NULLIF(TRIM(created_at), ''), '1970-01-01T00:00:00Z')) DESC
            ) AS rn
          FROM cloud_session_refresh_tokens
          WHERE user_id IS NOT NULL AND user_id != ''
        )
        WHERE rn = 1
      )`;
}

function splitMetricFromRows(rows, valueKey) {
  const split = { free: 0, pro: 0, total: 0 };
  for (const row of (Array.isArray(rows) ? rows : [])) {
    const edition = normalizeAnalyticsEdition(row && row.install_edition);
    const value = Number(row && row[valueKey] || 0);
    const safeValue = Number.isFinite(value) && value > 0 ? value : 0;
    split[edition] += safeValue;
    split.total += safeValue;
  }
  return split;
}

function splitActiveCounts() {
  return { free: 0, pro: 0, total: 0 };
}

function addSplitCount(target, edition, amount = 1) {
  if (!target) return;
  const safeEdition = normalizeAnalyticsEdition(edition);
  const safeAmount = Number.isFinite(Number(amount)) && Number(amount) > 0 ? Number(amount) : 0;
  target[safeEdition] += safeAmount;
  target.total += safeAmount;
}


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

function normalizeAccessStatusStrict(value, deps) {
  const normalized = String(deps.normalizeAccessStatus(value) || "").trim().toLowerCase();
  if (normalized === deps.ACCESS_STATUS_ACTIVE) return deps.ACCESS_STATUS_ACTIVE;
  if (normalized === "blocked") return "blocked";
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

function uniqueEmailPatternsFromSources(sources) {
  const unique = new Set();
  for (const source of (Array.isArray(sources) ? sources : [])) {
    for (const token of String(source || "").split(",")) {
      const pattern = String(token || "").trim().toLowerCase();
      if (!pattern) continue;
      unique.add(pattern);
    }
  }
  return Array.from(unique);
}

function parseAnalyticsExcludedEmailPatterns(env = {}, deps) {
  return uniqueEmailPatternsFromSources([
    env.ANALYTICS_EXCLUDED_EMAIL_PATTERNS || deps.DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS,
    deps.INTERNAL_TEST_ANALYTICS_EMAIL_PATTERNS,
  ]);
}

function parseAnalyticsRevenueExcludedEmailPatterns(env = {}, deps) {
  const baseSource = String(
    env.ANALYTICS_EXCLUDED_EMAIL_PATTERNS || deps.DEFAULT_ANALYTICS_EXCLUDED_EMAIL_PATTERNS || "",
  ).trim();
  const revenueSource = String(
    env.ANALYTICS_REVENUE_EXCLUDED_EMAIL_PATTERNS
      || deps.DEFAULT_ANALYTICS_REVENUE_EXCLUDED_EMAIL_PATTERNS
      || "tom.griger@gmail.com,info@planetka.io,qa@planetka.io",
  ).trim();
  return uniqueEmailPatternsFromSources([
    baseSource,
    revenueSource,
    deps.INTERNAL_TEST_ANALYTICS_EMAIL_PATTERNS,
  ]);
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

function buildTileActivityAccessStatusFilterSql(access_statusFilter, deps) {
  void access_statusFilter;
  void deps;
  return { clause: "", bindings: [] };
}

export function parseHeavyUserAccessStatusFilter(value, deps) {
  void value;
  void deps;
  return "all";
}

export function parseAnalyticsUsersSort(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "resolves") return "total_resolves";
  if (normalized === "lifetime") return "data_downloaded";
  const allowed = new Set(["total_resolves", "data_downloaded", "last_seen"]);
  return allowed.has(normalized) ? normalized : "data_downloaded";
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
  access_statusFilter = "all",
  liveTileMapWindowMinutes,
  env = {},
  deps,
) {
  await deps.ensureTileRequestEventsTable(db);
  await deps.ensureTileRequestRollupTables(db);
  await deps.ensureAuthRefreshEventsTable(db);
  await deps.ensureRefreshSessionColumns(db);
  const nowUnix = Math.floor(Date.now() / 1000);
  const windowMinutes = sanitizeAnalyticsMinutes(minutes, deps.DEFAULT_ANALYTICS_WINDOW_MINUTES, deps);
  const windowStartUnix = Math.max(0, nowUnix - (windowMinutes * 60));
  const rollupStart30d = Math.max(0, nowUnix - (30 * 86400));
  const safeAccessStatusFilter = parseHeavyUserAccessStatusFilter(access_statusFilter, deps);
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

  const topLineInstallsByEdition = await deps.dbAll(
    db,
    `
      WITH ${latestInstallEditionCte()}
      SELECT
        COALESCE(lie.install_edition, 'free') AS install_edition,
        COUNT(*) AS total_installs
      FROM cloud_installs u
      LEFT JOIN latest_install_editions lie ON lie.user_id = u.id
      WHERE 1 = 1
      ${userEmailFilter.condition ? `AND ${userEmailFilter.condition}` : ""}
      GROUP BY COALESCE(lie.install_edition, 'free')
    `,
    [...userEmailFilter.bindings],
  );

  const topLineTrafficByEdition = await deps.dbAll(
    db,
    `
      WITH ${latestInstallEditionCte()}
      SELECT
        COALESCE(lie.install_edition, 'free') AS install_edition,
        COALESCE(SUM(r.request_count), 0) AS total_requests,
        COALESCE(SUM(r.bytes_served), 0) AS total_bytes
      FROM tile_request_rollup_daily_install r
      LEFT JOIN cloud_installs u ON u.id = r.user_id
      LEFT JOIN latest_install_editions lie ON lie.user_id = r.user_id
      WHERE 1 = 1
      ${rollupEmailFilterAliasR.condition ? `AND ${rollupEmailFilterAliasR.condition}` : ""}
      GROUP BY COALESCE(lie.install_edition, 'free')
    `,
    [...rollupEmailFilterAliasR.bindings],
  );

  const topLineResolvesByEdition = await deps.dbAll(
    db,
    `
      WITH ${latestInstallEditionCte()},
      tagged_resolves AS (
        SELECT DISTINCT
          e.user_id,
          e.resolve_id,
          COALESCE(lie.install_edition, 'free') AS install_edition
        FROM tile_request_events e
        LEFT JOIN cloud_installs u ON u.id = e.user_id
        LEFT JOIN latest_install_editions lie ON lie.user_id = e.user_id
        WHERE
          e.resolve_id IS NOT NULL
          AND e.resolve_id != ''
          ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      )
      SELECT
        install_edition,
        COUNT(*) AS total_resolves
      FROM tagged_resolves
      GROUP BY install_edition
    `,
    [...eventEmailFilterAliasE.bindings],
  );

  const topLineRevenue = { total_earned_eur: 0 };
  const topLinePaidResolves = { total_paid_resolves: 0 };


  const activeWindow6mStartUnix = Math.max(0, nowUnix - (180 * 86400));
  const activeWindow3mStartUnix = Math.max(0, nowUnix - (90 * 86400));
  const activeWindow1mStartUnix = Math.max(0, nowUnix - (30 * 86400));
  const activeWindow1wStartUnix = Math.max(0, nowUnix - (7 * 86400));
  const activeWindow1dStartUnix = Math.max(0, nowUnix - 86400);
  const activeWindow1hStartUnix = Math.max(0, nowUnix - 3600);
  const activeInstallRows = await deps.dbAll(
    db,
    `
      WITH ${latestInstallEditionCte()}
      SELECT
        e.user_id,
        MAX(e.created_at_unix) AS last_seen_unix,
        NULLIF(TRIM(LOWER(u.status)), '') AS access_status_norm,
        COALESCE(lie.install_edition, 'free') AS install_edition
      FROM tile_request_events e
      LEFT JOIN cloud_installs u ON u.id = e.user_id
      LEFT JOIN latest_install_editions lie ON lie.user_id = e.user_id
      WHERE
        e.created_at_unix >= ?
        AND e.user_id IS NOT NULL
        AND e.user_id != ''
        ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      GROUP BY
        e.user_id,
        NULLIF(TRIM(LOWER(u.status)), ''),
        COALESCE(lie.install_edition, 'free')
    `,
    [
      activeWindow6mStartUnix,
      ...eventEmailFilterAliasE.bindings,
    ],
  );

  const makeActiveCounts = () => splitActiveCounts();
  const activeWindows = {
    installs_6m: makeActiveCounts(),
    installs_3m: makeActiveCounts(),
    installs_1m: makeActiveCounts(),
    installs_1w: makeActiveCounts(),
    installs_1d: makeActiveCounts(),
    installs_1h: makeActiveCounts(),
  };
  const activeThresholds = [
    ["installs_6m", activeWindow6mStartUnix],
    ["installs_3m", activeWindow3mStartUnix],
    ["installs_1m", activeWindow1mStartUnix],
    ["installs_1w", activeWindow1wStartUnix],
    ["installs_1d", activeWindow1dStartUnix],
    ["installs_1h", activeWindow1hStartUnix],
  ];
  for (const row of (Array.isArray(activeInstallRows) ? activeInstallRows : [])) {
    const lastSeenUnix = deps.clampNonNegativeInt(row && row.last_seen_unix);
    if (lastSeenUnix <= 0) {
      continue;
    }
    for (const [windowKey, thresholdUnix] of activeThresholds) {
      if (lastSeenUnix < thresholdUnix) {
        continue;
      }
      const windowCounts = activeWindows[windowKey];
      if (windowCounts) {
        addSplitCount(windowCounts, row && row.install_edition);
      }
    }
  }


  let activeInstalls10m = [];
  try {
    activeInstalls10m = await deps.dbAll(
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
        LEFT JOIN cloud_installs u ON u.id = e.user_id
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
      "planetka.analytics.active_installs_10m_query_failed",
      JSON.stringify({
        error: String(error && error.message || "active_installs_10m_query_failed"),
      }),
    );
    activeInstalls10m = [];
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

  const topInstalls = await deps.dbAll(
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
      LEFT JOIN cloud_installs u ON u.id = e.user_id
      WHERE e.created_at_unix >= ?
      ${eventEmailFilterAliasE.condition ? `AND ${eventEmailFilterAliasE.condition}` : ""}
      GROUP BY e.user_id, e.user_email, NULLIF(TRIM(LOWER(u.status)), '')
      ORDER BY request_count DESC
      LIMIT 20
    `,
    [windowStartUnix, ...eventEmailFilterAliasE.bindings],
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
  const tileActivityFilter = buildTileActivityAccessStatusFilterSql(safeAccessStatusFilter, deps);
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
      LEFT JOIN cloud_installs u ON u.id = e.user_id
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

  const activeTileInstallsSet = new Set();
  const activeTileKeysSet = new Set();
  const normalizedTileMapRows = Array.isArray(tileMapRows) ? tileMapRows.map((row) => {
    const userId = String(row && row.user_id || "").trim();
    const userEmail = deps.normalizeEmail(row && row.user_email || "");
    const userKey = userId || userEmail;
    if (userKey) {
      activeTileInstallsSet.add(userKey);
    }
    const tileKey = String(row && row.tile_key || "").trim();
    if (tileKey) {
      activeTileKeysSet.add(tileKey);
    }
    return {
      user_id: userId,
      user_email: userEmail,
      user_status: normalizeAccessStatusStrict(row && row.user_status, deps),
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
  const authRefreshTopFailureInstalls = await deps.dbAll(
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
  const authRefreshTopCriticalFailureInstalls = await deps.dbAll(
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
        COUNT(DISTINCT user_id) AS active_installs
      FROM tile_request_rollup_daily_install
      WHERE day_start_unix >= ?
      ${rollupEmailFilter.condition ? `AND ${rollupEmailFilter.condition}` : ""}
    `,
    [rollupStart30d, ...rollupEmailFilter.bindings],
  );

  const topInstalls30d = await deps.dbAll(
    db,
    `
      SELECT
        user_id,
        user_email,
        COALESCE(SUM(request_count), 0) AS request_count,
        COALESCE(SUM(bytes_served), 0) AS bytes_served,
        COALESCE(SUM(error_count), 0) AS error_count,
        MAX(last_event_unix) AS last_event_unix
      FROM tile_request_rollup_daily_install
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
        FROM tile_request_rollup_daily_install r
        LEFT JOIN cloud_installs u ON u.id = r.user_id
        GROUP BY
          r.user_id,
          COALESCE(NULLIF(TRIM(u.email), ''), COALESCE(NULLIF(TRIM(r.user_email), ''), '')),
          NULLIF(TRIM(LOWER(u.status)), '')
      ),
      hour_rollups AS (
        SELECT
          user_id,
          COALESCE(SUM(bytes_served), 0) AS hour_bytes
        FROM tile_request_rollup_hourly_install
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

  let heavyInstalls30d = (Array.isArray(topHeavyLifetime) ? topHeavyLifetime : []).map((row) => ({
    user_id: String(row && row.user_id || "").trim(),
    user_email: deps.normalizeEmail(row && row.user_email || ""),
    user_status: normalizeAccessStatusStrict(row && row.user_status, deps),
    lifetime_bytes: deps.clampNonNegativeInt(row && row.lifetime_bytes),
    month_bytes: deps.clampNonNegativeInt(row && row.month_bytes),
    request_count_month: deps.clampNonNegativeInt(row && row.request_count_month),
    last_event_unix: deps.clampNonNegativeInt(row && row.last_event_unix),
  }));
  heavyInstalls30d = heavyInstalls30d.map((row) => ({
    ...row,
    request_count_30d: deps.clampNonNegativeInt(row && row.request_count_month),
    bytes_served_30d: deps.clampNonNegativeInt(row && row.month_bytes),
  }));
  heavyInstalls30d = heavyInstalls30d
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
        ...(Array.isArray(heavyInstalls30d) ? heavyInstalls30d : []),
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
  const normalizedActiveInstalls10m = (Array.isArray(activeInstalls10m) ? activeInstalls10m : []).map((row) => ({
    user_id: String(row && row.user_id || "").trim(),
    user_email: deps.normalizeEmail(row && row.user_email || ""),
    user_status: normalizeAccessStatusStrict(row && row.user_status, deps),
    request_count: deps.clampNonNegativeInt(row && row.request_count),
    resolve_count: deps.clampNonNegativeInt(row && row.resolve_count),
    bytes_served: deps.clampNonNegativeInt(row && row.bytes_served),
    last_seen_at: String(row && row.last_seen_at || ""),
  }));

  const totalEarnedEur = Number(topLineRevenue && topLineRevenue.total_earned_eur);
  const topLineInstalls = splitMetricFromRows(topLineInstallsByEdition, "total_installs");
  const topLineResolves = splitMetricFromRows(topLineResolvesByEdition, "total_resolves");
  const topLineTileRequests = splitMetricFromRows(topLineTrafficByEdition, "total_requests");
  const topLineBytesServed = splitMetricFromRows(topLineTrafficByEdition, "total_bytes");

  return {
    generated_at: deps.nowIso(),
    window_minutes: windowMinutes,
    window_start_unix: windowStartUnix,
    top_line: {
      installs: {
        free: deps.clampNonNegativeInt(topLineInstalls.free),
        pro: deps.clampNonNegativeInt(topLineInstalls.pro),
        total: deps.clampNonNegativeInt(topLineInstalls.total),
      },
      resolves: {
        free: deps.clampNonNegativeInt(topLineResolves.free),
        pro: deps.clampNonNegativeInt(topLineResolves.pro),
        total: deps.clampNonNegativeInt(topLineResolves.total),
      },
      tile_requests: {
        free: deps.clampNonNegativeInt(topLineTileRequests.free),
        pro: deps.clampNonNegativeInt(topLineTileRequests.pro),
        total: deps.clampNonNegativeInt(topLineTileRequests.total),
      },
      gb_served: {
        free: deps.clampNonNegativeInt(topLineBytesServed.free),
        pro: deps.clampNonNegativeInt(topLineBytesServed.pro),
        total: deps.clampNonNegativeInt(topLineBytesServed.total),
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
      installs_total: deps.clampNonNegativeInt(topLineInstalls.total),
      installs_6m: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_6m && activeWindows.installs_6m.total),
      installs_3m: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_3m && activeWindows.installs_3m.total),
      installs_1m: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1m && activeWindows.installs_1m.total),
      installs_1w: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1w && activeWindows.installs_1w.total),
      installs_1d: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1d && activeWindows.installs_1d.total),
      installs_1h: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1h && activeWindows.installs_1h.total),
      windows: {
        "6m": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_6m && activeWindows.installs_6m.free),
          pro: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_6m && activeWindows.installs_6m.pro),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_6m && activeWindows.installs_6m.total),
        },
        "3m": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_3m && activeWindows.installs_3m.free),
          pro: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_3m && activeWindows.installs_3m.pro),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_3m && activeWindows.installs_3m.total),
        },
        "1m": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1m && activeWindows.installs_1m.free),
          pro: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1m && activeWindows.installs_1m.pro),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1m && activeWindows.installs_1m.total),
        },
        "1w": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1w && activeWindows.installs_1w.free),
          pro: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1w && activeWindows.installs_1w.pro),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1w && activeWindows.installs_1w.total),
        },
        "1d": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1d && activeWindows.installs_1d.free),
          pro: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1d && activeWindows.installs_1d.pro),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1d && activeWindows.installs_1d.total),
        },
        "1h": {
          free: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1h && activeWindows.installs_1h.free),
          pro: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1h && activeWindows.installs_1h.pro),
          total: deps.clampNonNegativeInt(activeWindows && activeWindows.installs_1h && activeWindows.installs_1h.total),
        },
      },
      tile_events_10s: deps.clampNonNegativeInt(activeNow && activeNow.active_download_rows),
    },
    active_installs_10m: normalizedActiveInstalls10m,
    top_installs: Array.isArray(topInstalls) ? topInstalls : [],
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
      top_failure_installs: Array.isArray(authRefreshTopFailureInstalls) ? authRefreshTopFailureInstalls : [],
      error_breakdown: Array.isArray(authRefreshErrorBreakdown) ? authRefreshErrorBreakdown : [],
      top_critical_failure_installs: Array.isArray(authRefreshTopCriticalFailureInstalls) ? authRefreshTopCriticalFailureInstalls : [],
      critical_error_breakdown: Array.isArray(authRefreshCriticalErrorBreakdown) ? authRefreshCriticalErrorBreakdown : [],
    },
    rollup_30d: {
      window_days: 30,
      request_count: deps.clampNonNegativeInt(rollup30d && rollup30d.request_count),
      bytes_served: deps.clampNonNegativeInt(rollup30d && rollup30d.bytes_served),
      error_count: deps.clampNonNegativeInt(rollup30d && rollup30d.error_count),
      cache_hit_count: deps.clampNonNegativeInt(rollup30d && rollup30d.cache_hit_count),
      tagged_request_count: deps.clampNonNegativeInt(rollup30d && rollup30d.tagged_request_count),
      active_installs: deps.clampNonNegativeInt(rollup30d && rollup30d.active_installs),
      top_installs: Array.isArray(topInstalls30d)
        ? topInstalls30d.map((row) => ({
          ...row,
          last_seen_at: Number.isFinite(Number(row && row.last_event_unix))
            ? new Date(Number(row.last_event_unix) * 1000).toISOString()
            : "",
        }))
        : [],
    },
    heavy_installs: {
      access_status_filter: safeAccessStatusFilter,
      top_lifetime: attachHeavyResolveCounts(topHeavyLifetime),
      top_month: attachHeavyResolveCounts(topHeavyMonth),
      top_week: attachHeavyResolveCounts(topHeavyWeek),
      top_day: attachHeavyResolveCounts(topHeavyDay),
      top_hour: attachHeavyResolveCounts(topHeavyHour),
    },
    heavy_installs_30d: attachHeavyResolveCounts(heavyInstalls30d),
    live_tile_map: {
      generated_at: deps.nowIso(),
      window_seconds: tileMapWindowSeconds,
      access_status_filter: safeAccessStatusFilter,
      installs_active: activeTileInstallsSet.size,
      tiles_active: activeTileKeysSet.size,
      row_limit: tileMapRowLimit,
      rows: normalizedTileMapRows,
    },
  };
}

export async function listAnalyticsUsers(db, env, options = {}, deps) {
  await deps.ensureTileRequestEventsTable(db);
  await deps.ensureTileRequestRollupTables(db);
  await deps.ensureCloudInstallAccessColumns(db);
  await deps.ensureRefreshSessionColumns(db);
  const sortBy = parseAnalyticsUsersSort(options.sort_by);
  const sortDir = parseAnalyticsUsersSortDirection(options.sort_dir);
  const query = String(options.query || "").trim().toLowerCase();
  const limit = Math.max(1, Math.min(5000, deps.parseNonNegativeInteger(options.limit, 5000)));
  const orderSqlByKey = {
    total_resolves: "total_resolve_count",
    data_downloaded: "data_downloaded_bytes",
    last_seen: "last_seen_unix",
  };
  const orderSql = orderSqlByKey[sortBy] || orderSqlByKey.data_downloaded;
  const whereParts = [];
  const bindings = [];
  if (query) {
    whereParts.push(`(LOWER(COALESCE(u.email, '')) LIKE ? OR LOWER(COALESCE(u.id, '')) LIKE ?)`);
    bindings.push(`%${query}%`, `%${query}%`);
  }
  const whereSql = whereParts.length ? `WHERE ${whereParts.join(" AND ")}` : "";
  return deps.dbAll(
    db,
    `
      WITH ${latestInstallEditionCte()},
      resolve_counts AS (
        SELECT
          user_id,
          COUNT(DISTINCT resolve_id) AS total_resolve_count
        FROM tile_request_events
        WHERE resolve_id IS NOT NULL AND resolve_id != ''
        GROUP BY user_id
      ),
      daily_usage AS (
        SELECT
          r.user_id,
          COALESCE(SUM(r.bytes_served), 0) AS data_downloaded_bytes,
          COALESCE(MAX(r.last_event_unix), 0) AS last_seen_unix
        FROM tile_request_rollup_daily_install r
        GROUP BY r.user_id
      )
      SELECT
        u.id AS user_id,
        CASE
          WHEN LOWER(COALESCE(u.email, '')) LIKE 'anonymous+%@planetka.local' THEN ''
          ELSE u.email
        END AS user_email,
        NULLIF(TRIM(LOWER(u.status)), '') AS user_status,
        COALESCE(lie.install_edition, 'free') AS install_edition,
        COALESCE(rc.total_resolve_count, 0) AS total_resolve_count,
        COALESCE(du.data_downloaded_bytes, 0) AS data_downloaded_bytes,
        COALESCE(
          NULLIF(TRIM(datetime(du.last_seen_unix, 'unixepoch')), ''),
          COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), ''))
        ) AS last_seen_at,
        COALESCE(du.last_seen_unix, strftime('%s', COALESCE(NULLIF(TRIM(u.last_login_at), ''), COALESCE(NULLIF(TRIM(u.created_at), ''), ''))), 0) AS last_seen_unix
      FROM cloud_installs u
      LEFT JOIN latest_install_editions lie ON lie.user_id = u.id
      LEFT JOIN daily_usage du ON du.user_id = u.id
      LEFT JOIN resolve_counts rc ON rc.user_id = u.id
      ${whereSql}
      ORDER BY ${orderSql} ${sortDir.toUpperCase()}, LOWER(COALESCE(u.email, '')) ASC
      LIMIT ${limit}
    `,
    bindings,
  );
}
