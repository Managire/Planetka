CREATE TABLE IF NOT EXISTS user_product_quotes (
  user_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  catalog_version TEXT NOT NULL,
  pricing_version TEXT NOT NULL,
  entitlement_version TEXT NOT NULL,
  quote_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',
  currency TEXT NOT NULL DEFAULT 'eur',
  full_price_cents INTEGER NOT NULL DEFAULT 0,
  already_licenced_cents INTEGER NOT NULL DEFAULT 0,
  partial_licence_credit_cents INTEGER NOT NULL DEFAULT 0,
  discount_percent INTEGER NOT NULL DEFAULT 0,
  discount_cents INTEGER NOT NULL DEFAULT 0,
  final_price_cents INTEGER NOT NULL DEFAULT 0,
  total_tile_count INTEGER NOT NULL DEFAULT 0,
  new_tile_count INTEGER NOT NULL DEFAULT 0,
  charged_tile_count INTEGER NOT NULL DEFAULT 0,
  already_licenced_tile_count INTEGER NOT NULL DEFAULT 0,
  partial_licence_tile_count INTEGER NOT NULL DEFAULT 0,
  free_tile_count INTEGER NOT NULL DEFAULT 0,
  summary_json TEXT NOT NULL DEFAULT '{}',
  map_state_status TEXT NOT NULL DEFAULT 'not_requested',
  map_state_json TEXT,
  map_state_updated_at TEXT,
  stale_reason TEXT,
  error_code TEXT,
  error_message TEXT,
  requested_at TEXT,
  calculated_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, product_id, catalog_version)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_product_quotes_quote_id
ON user_product_quotes(quote_id);

CREATE INDEX IF NOT EXISTS idx_user_product_quotes_user_status
ON user_product_quotes(user_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_product_quotes_product
ON user_product_quotes(product_id, catalog_version, status);

CREATE INDEX IF NOT EXISTS idx_user_product_quotes_versions
ON user_product_quotes(user_id, pricing_version, entitlement_version, catalog_version);

CREATE TABLE IF NOT EXISTS user_product_quote_batches (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  trigger_purchase_id TEXT,
  source_product_id TEXT,
  pricing_version TEXT NOT NULL,
  entitlement_version TEXT NOT NULL,
  catalog_version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  max_round INTEGER NOT NULL DEFAULT 0,
  queued_job_count INTEGER NOT NULL DEFAULT 0,
  completed_job_count INTEGER NOT NULL DEFAULT 0,
  failed_job_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_product_quote_batches_status
ON user_product_quote_batches(status, created_at);

CREATE INDEX IF NOT EXISTS idx_user_product_quote_batches_user
ON user_product_quote_batches(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_product_quote_jobs (
  id TEXT PRIMARY KEY,
  batch_id TEXT,
  user_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  source_product_id TEXT,
  catalog_version TEXT NOT NULL,
  pricing_version TEXT NOT NULL,
  entitlement_version TEXT NOT NULL,
  job_round INTEGER NOT NULL DEFAULT 0,
  priority INTEGER NOT NULL DEFAULT 100,
  status TEXT NOT NULL DEFAULT 'queued',
  trigger_type TEXT NOT NULL,
  trigger_purchase_id TEXT,
  stale_reason TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  available_at TEXT NOT NULL,
  locked_at TEXT,
  lock_token TEXT,
  worker_id TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_product_quote_jobs_queue
ON user_product_quote_jobs(status, available_at, job_round, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_user_product_quote_jobs_queue_round
ON user_product_quote_jobs(status, job_round, priority, available_at, created_at);

CREATE INDEX IF NOT EXISTS idx_user_product_quote_jobs_user_product
ON user_product_quote_jobs(user_id, product_id, catalog_version, status);

CREATE INDEX IF NOT EXISTS idx_user_product_quote_jobs_batch
ON user_product_quote_jobs(batch_id, job_round, status);

CREATE INDEX IF NOT EXISTS idx_user_product_quote_jobs_lock
ON user_product_quote_jobs(lock_token, locked_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_product_quote_jobs_unique_active
ON user_product_quote_jobs(user_id, product_id, catalog_version, pricing_version, entitlement_version)
WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS user_product_quote_job_locks (
  lock_name TEXT PRIMARY KEY,
  lock_token TEXT NOT NULL,
  worker_id TEXT,
  current_job_id TEXT,
  locked_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
