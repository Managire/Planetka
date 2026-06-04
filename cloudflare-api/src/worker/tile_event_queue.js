export async function handleTileEventQueueBatch(batch, env, deps) {
  if (!batch || !Array.isArray(batch.messages) || batch.messages.length <= 0) {
    return;
  }

  const db = deps.requireDb(env);
  for (const message of batch.messages) {
    try {
      const payload = message && message.body && typeof message.body === "object"
        ? message.body
        : null;
      if (!payload) {
        continue;
      }

      await deps.recordTileRequestEvent(db, {
        created_at: String(payload.created_at || deps.nowIso()),
        created_at_unix: deps.clampNonNegativeInt(payload.created_at_unix),
        user_id: String(payload.user_id || ""),
        user_email: String(payload.user_email || ""),
        resolve_id: String(payload.resolve_id || ""),
        method: String(payload.method || "GET"),
        path: String(payload.path || ""),
        folder: String(payload.folder || ""),
        file_name: String(payload.file_name || ""),
        tile_key: String(payload.tile_key || ""),
        quality_mode: String(payload.quality_mode || payload.qualityMode || ""),
        status_code: deps.clampNonNegativeInt(payload.status_code),
        bytes_served: deps.clampNonNegativeInt(payload.bytes_served),
        cache_status: String(payload.cache_status || ""),
        duration_ms: deps.clampNonNegativeInt(payload.duration_ms),
        cf_ray: String(payload.cf_ray || ""),
        cf_country: String(payload.cf_country || ""),
        cf_region: String(payload.cf_region || ""),
        client_ip: String(payload.client_ip || ""),
        error_code: String(payload.error_code || ""),
      });
      if (
        String(payload.quality_mode || payload.qualityMode || "").trim().toLowerCase() === "preview"
        && String(payload.method || "GET").trim().toUpperCase() === "GET"
        && deps.clampNonNegativeInt(payload.status_code) === 200
        && typeof deps.recordPreviewUsageAndMaybeAlert === "function"
      ) {
        await deps.recordPreviewUsageAndMaybeAlert(db, env, {
          created_at_unix: deps.clampNonNegativeInt(payload.created_at_unix),
          user_id: String(payload.user_id || ""),
          user_email: String(payload.user_email || ""),
          method: String(payload.method || "GET"),
          quality_mode: String(payload.quality_mode || payload.qualityMode || "preview"),
          status_code: deps.clampNonNegativeInt(payload.status_code),
          bytes_served: deps.clampNonNegativeInt(payload.bytes_served),
          tile_key: String(payload.tile_key || ""),
        });
      }

      if (
        payload.monitoring_enabled
        && deps.isTileHotPathMonitoringEnabled(env)
      ) {
        await deps.maybeSignalTileFarmingActivity(db, env, {
          userId: String(payload.user_id || ""),
          userEmail: String(payload.user_email || ""),
          ip: String(payload.client_ip || ""),
          deviceId: String(payload.device_id || ""),
          resolveId: String(payload.resolve_id || ""),
          tileKey: String(payload.tile_key || ""),
          method: String(payload.method || "GET"),
          path: String(payload.path || ""),
          statusCode: deps.clampNonNegativeInt(payload.status_code),
        });
      }
    } catch (error) {
      console.warn(
        "worker.tile_event_queue.process_failed",
        JSON.stringify({
          queue: String(batch && batch.queue || ""),
          error: String(error && error.message || "tile_event_queue_process_failed"),
        }),
      );
    }
  }
}
