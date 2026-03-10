-- OpenClaw v5: idempotency + lease columns for jobs table
-- Run on Supabase project: djdilkhedpnlercxggby

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS execution_id TEXT,
  ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_lease_expires
  ON jobs (lease_expires_at)
  WHERE status = 'running';

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency_key
  ON jobs (idempotency_key)
  WHERE idempotency_key IS NOT NULL;
