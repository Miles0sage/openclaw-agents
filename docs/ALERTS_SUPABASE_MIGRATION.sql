CREATE TABLE IF NOT EXISTS alerts (
  id              TEXT PRIMARY KEY,
  failure_type    TEXT NOT NULL,
  severity        TEXT NOT NULL DEFAULT 'warning',
  title           TEXT NOT NULL,
  message         TEXT NOT NULL,
  job_id          TEXT,
  agent_key       TEXT,
  extra_data      JSONB,
  acknowledged    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  acknowledged_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alerts_severity    ON alerts (severity);
CREATE INDEX IF NOT EXISTS idx_alerts_job_id      ON alerts (job_id);
CREATE INDEX IF NOT EXISTS idx_alerts_agent_key   ON alerts (agent_key);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at  ON alerts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_unacked     ON alerts (acknowledged) WHERE acknowledged = FALSE;
