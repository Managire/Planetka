CREATE TABLE IF NOT EXISTS billing_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT INTO billing_settings (key, value, updated_at)
VALUES
  ('full_resolve_price_cents', '1000', datetime('now')),
  ('animation_price_per_300_cents', '2900', datetime('now')),
  ('currency', 'EUR', datetime('now'))
ON CONFLICT(key) DO NOTHING;

CREATE TABLE IF NOT EXISTS billing_intents (
  id TEXT PRIMARY KEY,
  install_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  amount_cents INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'EUR',
  frame_count INTEGER NOT NULL DEFAULT 0,
  frame_units INTEGER NOT NULL DEFAULT 0,
  checkout_id TEXT,
  checkout_url TEXT,
  provider_order_id TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  paid_at TEXT,
  consumed_at TEXT,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_billing_intents_install_kind_status ON billing_intents(install_id, kind, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_intents_checkout_id ON billing_intents(checkout_id);
