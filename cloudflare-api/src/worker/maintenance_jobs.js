export async function cleanupAuthTables(db, env, nowTimestamp, deps) {
  const nowUnix = Math.floor(Date.parse(nowTimestamp) / 1000) || Math.floor(Date.now() / 1000);
  const summary = {
    started_at: nowTimestamp,
    refresh_session_retention_days: Math.max(
      0,
      deps.parseNonNegativeInteger(
        env.CLEANUP_REFRESH_SESSION_RETENTION_DAYS,
        deps.DEFAULT_REFRESH_SESSION_CLEANUP_RETENTION_DAYS,
      ),
    ),
    cloud_session_refresh_tokens_deleted: 0,
    auth_refresh_event_retention_days: Math.max(
      7,
      deps.parseNonNegativeInteger(
        env.CLEANUP_AUTH_REFRESH_EVENT_RETENTION_DAYS,
        deps.DEFAULT_AUTH_REFRESH_EVENT_RETENTION_DAYS,
      ),
    ),
    tile_event_retention_days: Math.max(
      14,
      deps.parseNonNegativeInteger(env.CLEANUP_TILE_EVENT_RETENTION_DAYS, deps.DEFAULT_TILE_EVENT_RETENTION_DAYS),
    ),
    tile_rollup_retention_days: Math.max(
      60,
      deps.parseNonNegativeInteger(env.CLEANUP_TILE_ROLLUP_RETENTION_DAYS, deps.DEFAULT_TILE_ROLLUP_RETENTION_DAYS),
    ),
    tile_request_events_deleted: 0,
    tile_rollup_hourly_deleted: 0,
    tile_rollup_daily_deleted: 0,
    monthly_cost_alert_state_deleted: 0,
    auth_refresh_events_deleted: 0,
  };
  const refreshSessionCutoff = deps.addDaysFromIso(
    nowTimestamp,
    -summary.refresh_session_retention_days,
  );
  const tileEventsCutoffUnix = Math.max(0, nowUnix - (summary.tile_event_retention_days * 86400));
  const authRefreshEventsCutoffUnix = Math.max(
    0,
    nowUnix - (summary.auth_refresh_event_retention_days * 86400),
  );
  const tileRollupCutoffUnix = Math.max(0, nowUnix - (summary.tile_rollup_retention_days * 86400));

  if (await deps.dbTableExists(db, "cloud_session_refresh_tokens")) {
    const refreshSessionsResult = await deps.dbRun(
      db,
      `
        DELETE FROM cloud_session_refresh_tokens
        WHERE
          (expires_at IS NOT NULL AND expires_at != '' AND expires_at < ?)
          OR
          (revoked_at IS NOT NULL AND revoked_at != '' AND revoked_at < ?)
      `,
      [refreshSessionCutoff, refreshSessionCutoff],
    );
    summary.cloud_session_refresh_tokens_deleted = deps.dbMetaChanges(refreshSessionsResult);
  }

  if (await deps.dbTableExists(db, "auth_refresh_events")) {
    const authRefreshEventsResult = await deps.dbRun(
      db,
      `
        DELETE FROM auth_refresh_events
        WHERE created_at_unix < ?
      `,
      [authRefreshEventsCutoffUnix],
    );
    summary.auth_refresh_events_deleted = deps.dbMetaChanges(authRefreshEventsResult);
  }

  if (await deps.dbTableExists(db, "tile_request_events")) {
    const tileEventsResult = await deps.dbRun(
      db,
      `
        DELETE FROM tile_request_events
        WHERE created_at_unix < ?
      `,
      [tileEventsCutoffUnix],
    );
    summary.tile_request_events_deleted = deps.dbMetaChanges(tileEventsResult);
  }

  if (await deps.dbTableExists(db, "tile_request_rollup_hourly_install")) {
    const hourlyRollupResult = await deps.dbRun(
      db,
      `
        DELETE FROM tile_request_rollup_hourly_install
        WHERE bucket_start_unix < ?
      `,
      [tileRollupCutoffUnix],
    );
    summary.tile_rollup_hourly_deleted = deps.dbMetaChanges(hourlyRollupResult);
  }

  if (await deps.dbTableExists(db, "tile_request_rollup_daily_install")) {
    const dailyRollupResult = await deps.dbRun(
      db,
      `
        DELETE FROM tile_request_rollup_daily_install
        WHERE day_start_unix < ?
      `,
      [tileRollupCutoffUnix],
    );
    summary.tile_rollup_daily_deleted = deps.dbMetaChanges(dailyRollupResult);
  }

  if (await deps.dbTableExists(db, "monthly_cost_alert_state")) {
    const monthlyStateCutoff = new Date(Date.parse(nowTimestamp) - (730 * 86400 * 1000)).toISOString().slice(0, 7);
    const monthlyStateResult = await deps.dbRun(
      db,
      `
        DELETE FROM monthly_cost_alert_state
        WHERE month_key < ?
      `,
      [monthlyStateCutoff],
    );
    summary.monthly_cost_alert_state_deleted = deps.dbMetaChanges(monthlyStateResult);
  }

  return summary;
}

export async function runProductionAlertChecks(db, env, nowTimestamp, deps) {
  const nowUnix = Math.floor(Date.parse(nowTimestamp) / 1000) || Math.floor(Date.now() / 1000);
  const nowIsoValue = String(nowTimestamp || deps.nowIso());
  const cooldownSeconds = Math.max(
    60,
    deps.parseRateLimitInteger(env.PROD_ALERT_COOLDOWN_SECONDS, deps.DEFAULT_ALERT_PROD_COOLDOWN_SECONDS),
  );
  const summary = {
    started_at: nowIsoValue,
    cooldown_seconds: cooldownSeconds,
    metrics: [],
  };

  const hasTileEvents = await deps.dbTableExists(db, "tile_request_events");
  const metricSpecs = [
    {
      key: "http_403_spike",
      label: "HTTP 403 spike",
      threshold: deps.parseRateLimitInteger(env.PROD_ALERT_403_THRESHOLD, deps.DEFAULT_ALERT_PROD_403_THRESHOLD),
      windowSeconds: deps.parseRateLimitInteger(env.PROD_ALERT_403_WINDOW_SECONDS, deps.DEFAULT_ALERT_PROD_403_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `SELECT COUNT(*) AS count FROM tile_request_events WHERE created_at_unix >= ? AND status_code = 403`,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
    {
      key: "http_429_spike",
      label: "HTTP 429 spike",
      threshold: deps.parseRateLimitInteger(env.PROD_ALERT_429_THRESHOLD, deps.DEFAULT_ALERT_PROD_429_THRESHOLD),
      windowSeconds: deps.parseRateLimitInteger(env.PROD_ALERT_429_WINDOW_SECONDS, deps.DEFAULT_ALERT_PROD_429_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `SELECT COUNT(*) AS count FROM tile_request_events WHERE created_at_unix >= ? AND status_code = 429`,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
    {
      key: "tile_miss_burst",
      label: "S2 tile miss burst",
      threshold: deps.parseRateLimitInteger(env.PROD_ALERT_TILE_MISS_THRESHOLD, deps.DEFAULT_ALERT_PROD_TILE_MISS_THRESHOLD),
      windowSeconds: deps.parseRateLimitInteger(env.PROD_ALERT_TILE_MISS_WINDOW_SECONDS, deps.DEFAULT_ALERT_PROD_TILE_MISS_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `
        SELECT COUNT(*) AS count
        FROM tile_request_events
        WHERE created_at_unix >= ?
          AND tile_key LIKE '%/S2/%'
          AND (
            error_code = 'tile_not_found'
            OR (status_code = 404 AND (error_code IS NULL OR error_code = '' OR error_code = 'tile_not_found'))
          )
      `,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
    {
      key: "tile_error_burst",
      label: "Tile error burst",
      threshold: deps.parseRateLimitInteger(env.PROD_ALERT_TILE_ERROR_THRESHOLD, deps.DEFAULT_ALERT_PROD_TILE_ERROR_THRESHOLD),
      windowSeconds: deps.parseRateLimitInteger(env.PROD_ALERT_TILE_ERROR_WINDOW_SECONDS, deps.DEFAULT_ALERT_PROD_TILE_ERROR_WINDOW_SECONDS),
      tableAvailable: hasTileEvents,
      countSql: `
        SELECT COUNT(*) AS count
        FROM tile_request_events
        WHERE created_at_unix >= ?
          AND (
            status_code >= 500
            OR error_code = 'internal_error'
          )
      `,
      countBindings: (windowStartUnix) => [windowStartUnix],
    },
  ];

  for (const metric of metricSpecs) {
    const metricSummary = {
      key: metric.key,
      label: metric.label,
      threshold: Math.max(0, Number(metric.threshold) || 0),
      window_seconds: Math.max(0, Number(metric.windowSeconds) || 0),
      count: 0,
      triggered: false,
      suppressed_by_cooldown: false,
      disabled: false,
      unavailable: false,
      error: "",
    };
    try {
      if (!metric.tableAvailable) {
        metricSummary.unavailable = true;
        summary.metrics.push(metricSummary);
        continue;
      }
      if (metricSummary.threshold <= 0 || metricSummary.window_seconds <= 0) {
        metricSummary.disabled = true;
        summary.metrics.push(metricSummary);
        continue;
      }
      const windowStartUnix = Math.max(0, nowUnix - metricSummary.window_seconds);
      metricSummary.count = await deps.countRowsFromQuery(
        db,
        metric.countSql,
        metric.countBindings(windowStartUnix),
      );
      if (metricSummary.count < metricSummary.threshold) {
        summary.metrics.push(metricSummary);
        continue;
      }

      await deps.ensureRateLimitsTable(db);
      const alertRate = await deps.consumeRateLimitWindow(
        db,
        "prod_alert_mail",
        metric.key,
        1,
        cooldownSeconds,
      );
      if (!alertRate.allowed || Math.max(0, Number(alertRate.count) || 0) > 1) {
        metricSummary.suppressed_by_cooldown = true;
        summary.metrics.push(metricSummary);
        continue;
      }

      metricSummary.triggered = true;
      const metricWindowStart = new Date(Math.max(0, nowUnix - metricSummary.window_seconds) * 1000).toISOString();
      await deps.sendOpsAlertEmail(
        env,
        `Planetka production alert: ${metric.label}`,
        [
          `metric=${metric.key}`,
          `count=${metricSummary.count}`,
          `threshold=${metricSummary.threshold}`,
          `window_seconds=${metricSummary.window_seconds}`,
          `window_start_utc=${metricWindowStart}`,
          `window_end_utc=${nowIsoValue}`,
          `cooldown_seconds=${cooldownSeconds}`,
        ],
      );
    } catch (error) {
      metricSummary.error = String(error && error.message || "metric_alert_failed");
      console.warn(
        "worker.production_alert.metric_failed",
        JSON.stringify({
          metric: metric.key,
          error: metricSummary.error,
        }),
      );
    }
    summary.metrics.push(metricSummary);
  }

  return summary;
}

export async function runMonthlyCostEstimateAlerts(db, env, nowTimestamp, deps) {
  await deps.ensureRateLimitsTable(db);
  await deps.ensureMonthlyCostAlertStateTable(db);
  await deps.ensureTileRequestEventsTable(db);
  const nowUnix = Math.floor(Date.parse(String(nowTimestamp || deps.nowIso())) / 1000) || Math.floor(Date.now() / 1000);
  const monthStart = deps.monthStartUnix(nowUnix);
  const monthKey = deps.monthKeyFromUnix(nowUnix);
  const monthClassBOps = await deps.countRowsFromQuery(
    db,
    `
      SELECT COUNT(*) AS count
      FROM tile_request_events
      WHERE created_at_unix >= ?
        AND path LIKE '/tiles/%'
    `,
    [monthStart],
  );
  const estimate = deps.estimateR2MonthlyCostUsd(env, monthClassBOps);

  const baseUsd = Math.max(
    0,
    deps.parseNonNegativeInteger(env.MONTHLY_COST_ALERT_BASE_USD, deps.DEFAULT_MONTHLY_COST_ALERT_BASE_USD),
  );
  const stepUsd = Math.max(
    1,
    deps.parseNonNegativeInteger(env.MONTHLY_COST_ALERT_STEP_USD, deps.DEFAULT_MONTHLY_COST_ALERT_STEP_USD),
  );
  const state = await deps.dbGet(
    db,
    `
      SELECT
        month_key,
        last_notified_mark_usd,
        last_estimated_usd,
        last_alert_at,
        updated_at
      FROM monthly_cost_alert_state
      WHERE month_key = ?
      LIMIT 1
    `,
    [monthKey],
  );
  const lastNotifiedMark = Math.max(0, Number(state && state.last_notified_mark_usd) || 0);
  const totalCostRounded = Number(estimate.total_cost_usd.toFixed(2));
  let highestCrossedMark = 0;
  if (totalCostRounded >= (baseUsd + stepUsd)) {
    const markIndex = Math.floor((totalCostRounded - baseUsd) / stepUsd);
    highestCrossedMark = baseUsd + (markIndex * stepUsd);
  }

  let notifiedMarkUsd = lastNotifiedMark;
  if (highestCrossedMark > lastNotifiedMark) {
    await deps.sendOpsAlertEmail(
      env,
      "Planetka estimated monthly Cloud cost crossed threshold",
      [
        `month=${monthKey}`,
        `estimated_total_usd=${totalCostRounded.toFixed(2)}`,
        `threshold_crossed_usd=${highestCrossedMark}`,
        `base_usd=${baseUsd}`,
        `step_usd=${stepUsd}`,
        `r2_storage_gb_estimate=${estimate.storage_gb_estimate}`,
        `r2_storage_gb_billable_rounded=${estimate.storage_gb_billable_rounded}`,
        `r2_storage_cost_usd=${estimate.storage_cost_usd.toFixed(2)}`,
        `r2_class_a_ops_estimate=${estimate.class_a_ops_estimate}`,
        `r2_class_a_million_billable_rounded=${estimate.class_a_million_billable_rounded}`,
        `r2_class_a_cost_usd=${estimate.class_a_cost_usd.toFixed(2)}`,
        `r2_class_b_ops_month=${estimate.class_b_ops_month}`,
        `r2_class_b_million_billable_rounded=${estimate.class_b_million_billable_rounded}`,
        `r2_class_b_cost_usd=${estimate.class_b_cost_usd.toFixed(2)}`,
        "note=Estimate based on configured R2 storage GB and monthly tile operation telemetry.",
      ],
    );
    notifiedMarkUsd = highestCrossedMark;
  }

  const updatedAt = deps.nowIso();
  await deps.dbRun(
    db,
    `
      INSERT INTO monthly_cost_alert_state (
        month_key,
        last_notified_mark_usd,
        last_estimated_usd,
        last_alert_at,
        updated_at,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(month_key) DO UPDATE SET
        last_notified_mark_usd = excluded.last_notified_mark_usd,
        last_estimated_usd = excluded.last_estimated_usd,
        last_alert_at = excluded.last_alert_at,
        updated_at = excluded.updated_at
    `,
    [
      monthKey,
      notifiedMarkUsd,
      totalCostRounded,
      highestCrossedMark > lastNotifiedMark ? updatedAt : String(state && state.last_alert_at || ""),
      updatedAt,
      updatedAt,
    ],
  );

  return {
    month: monthKey,
    base_usd: baseUsd,
    step_usd: stepUsd,
    estimated_total_usd: totalCostRounded,
    last_notified_mark_usd: notifiedMarkUsd,
    threshold_crossed_usd: highestCrossedMark > lastNotifiedMark ? highestCrossedMark : 0,
    storage_cost_usd: Number(estimate.storage_cost_usd.toFixed(2)),
    class_a_cost_usd: Number(estimate.class_a_cost_usd.toFixed(2)),
    class_b_cost_usd: Number(estimate.class_b_cost_usd.toFixed(2)),
    class_b_ops_month: estimate.class_b_ops_month,
  };
}

export async function runScheduledMaintenanceJobs(db, env, nowTimestamp, deps) {
  const summary = await cleanupAuthTables(db, env, nowTimestamp, deps);
  const alertSummary = await runProductionAlertChecks(db, env, nowTimestamp, deps);
  const monthlyCostSummary = await runMonthlyCostEstimateAlerts(db, env, nowTimestamp, deps);
  return {
    summary,
    alertSummary,
    monthlyCostSummary,
  };
}
