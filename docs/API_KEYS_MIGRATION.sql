-- API key registry with quotas
CREATE TABLE IF NOT EXISTS api_keys (
  id                  TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  key_hash            TEXT UNIQUE NOT NULL,
  owner               TEXT NOT NULL,
  tier                TEXT NOT NULL DEFAULT 'standard',
  rate_limit_per_min  INT NOT NULL DEFAULT 60,
  rate_limit_per_day  INT NOT NULL DEFAULT 1000,
  max_concurrent_jobs INT NOT NULL DEFAULT 3,
  max_jobs_per_day    INT NOT NULL DEFAULT 100,
  credit_limit_usd    NUMERIC(10,4) DEFAULT 10.00,
  credit_used_today   NUMERIC(10,4) DEFAULT 0.00,
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_used_at        TIMESTAMPTZ,
  notes               TEXT
);

-- Per-key usage counters (reset daily)
CREATE TABLE IF NOT EXISTS api_key_usage (
  key_id        TEXT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
  date          DATE NOT NULL DEFAULT CURRENT_DATE,
  request_count INT NOT NULL DEFAULT 0,
  job_count     INT NOT NULL DEFAULT 0,
  cost_usd      NUMERIC(10,6) DEFAULT 0,
  PRIMARY KEY (key_id, date)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS idx_usage_key_date ON api_key_usage (key_id, date);

-- Add key linkage to jobs for concurrent/quota checks
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS api_key_id TEXT REFERENCES api_keys(id);
CREATE INDEX IF NOT EXISTS idx_jobs_api_key ON jobs (api_key_id);

-- Atomic usage increment helper
CREATE OR REPLACE FUNCTION increment_api_usage(
  p_key_id TEXT,
  p_date DATE,
  p_requests INT,
  p_jobs INT,
  p_cost NUMERIC
) RETURNS void AS $$
BEGIN
  INSERT INTO api_key_usage (key_id, date, request_count, job_count, cost_usd)
  VALUES (p_key_id, p_date, p_requests, p_jobs, p_cost)
  ON CONFLICT (key_id, date) DO UPDATE SET
    request_count = api_key_usage.request_count + EXCLUDED.request_count,
    job_count     = api_key_usage.job_count + EXCLUDED.job_count,
    cost_usd      = api_key_usage.cost_usd + EXCLUDED.cost_usd;
END;
$$ LANGUAGE plpgsql;
