create table if not exists jobs (
  id text primary key,
  project text not null default '',
  task text not null,
  priority text not null default 'P2',
  status text not null default 'pending',
  api_key_id text,
  execution_id text,
  lease_expires_at timestamptz,
  idempotency_key text unique,
  created_at timestamptz default now(),
  started_at timestamptz,
  updated_at timestamptz,
  completed_at timestamptz,
  error text,
  pr_url text,
  branch_name text,
  approved_by text
);

create index if not exists idx_jobs_status on jobs(status);
create index if not exists idx_jobs_priority on jobs(priority);
