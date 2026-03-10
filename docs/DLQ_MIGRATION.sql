-- Dead-letter queue: permanent failures land here
CREATE TABLE IF NOT EXISTS dead_letter_queue (
  id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  job_id          TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  failure_reason  TEXT NOT NULL,
  last_error      TEXT,
  attempt_count   INT NOT NULL DEFAULT 1,
  cost_total      NUMERIC(10,6) DEFAULT 0,
  retry_count     INT NOT NULL DEFAULT 0,
  dlq_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_retry_at   TIMESTAMPTZ,
  resolved        BOOLEAN NOT NULL DEFAULT FALSE,
  resolved_at     TIMESTAMPTZ,
  metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_dlq_job_id     ON dead_letter_queue (job_id);
CREATE INDEX IF NOT EXISTS idx_dlq_unresolved ON dead_letter_queue (resolved) WHERE resolved = FALSE;
CREATE INDEX IF NOT EXISTS idx_dlq_dlq_at     ON dead_letter_queue (dlq_at DESC);

-- Per-job attempt tracking (for retry history visibility)
CREATE TABLE IF NOT EXISTS job_attempts (
  id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  job_id        TEXT NOT NULL,
  attempt_num   INT NOT NULL,
  execution_id  TEXT,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at   TIMESTAMPTZ,
  outcome       TEXT,
  cost          NUMERIC(10,6) DEFAULT 0,
  error         TEXT,
  phase_reached TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_job_id ON job_attempts (job_id);
