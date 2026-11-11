-- RolePilot preparation pipeline. Applied with: wrangler d1 execute rolepilot-staging --remote --file schema.sql
CREATE TABLE IF NOT EXISTS prep_registry (
  opportunity TEXT PRIMARY KEY,
  identity TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL UNIQUE,
  audit INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prep_jobs (
  id TEXT PRIMARY KEY,
  opportunity TEXT NOT NULL UNIQUE,
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'READY',
  attempts INTEGER NOT NULL DEFAULT 0,
  lease_until INTEGER NOT NULL DEFAULT 0,
  result TEXT,
  audit INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS prep_jobs_claim ON prep_jobs(audit, status, lease_until, created_at);
CREATE TABLE IF NOT EXISTS prep_events (
  id INTEGER PRIMARY KEY,
  job_id TEXT,
  opportunity TEXT,
  event TEXT NOT NULL,
  detail TEXT,
  audit INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER IF NOT EXISTS prep_events_no_update BEFORE UPDATE ON prep_events
  BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER IF NOT EXISTS prep_events_no_delete BEFORE DELETE ON prep_events WHEN OLD.audit = 0
  BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
