-- Worker heartbeat and runtime stability indexes.
-- Intended usage: run after 003_generated_workflow_code.sql as a versioned migration.

CREATE INDEX IF NOT EXISTS idx_workflow_runs_status_updated_at
  ON workflow_runs(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_node_runs_run_status
  ON node_runs(run_id, status);

CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id VARCHAR(255) PRIMARY KEY,
  worker_type VARCHAR(64) NOT NULL,
  queue_name VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  current_run_id BIGINT,
  current_job_id VARCHAR(128),
  hostname VARCHAR(255),
  pid INT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata_json JSONB,
  CONSTRAINT chk_worker_heartbeats_status
    CHECK (status IN ('idle', 'busy', 'stopping', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_type
  ON worker_heartbeats(worker_type);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_queue
  ON worker_heartbeats(queue_name);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_last_seen
  ON worker_heartbeats(last_seen_at);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_current_run
  ON worker_heartbeats(current_run_id);
