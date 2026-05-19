-- Adds the minimal Human Approval task contract for second-stage development.
-- Intended usage: run after 005_seed_deepseek_default_model.sql.

ALTER TABLE workflow_runs DROP CONSTRAINT IF EXISTS chk_workflow_runs_status;

ALTER TABLE workflow_runs
  ADD CONSTRAINT chk_workflow_runs_status
  CHECK (status IN ('pending', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled'));

CREATE TABLE IF NOT EXISTS human_approval_tasks (
  id BIGSERIAL PRIMARY KEY,
  workflow_id BIGINT NOT NULL,
  run_id BIGINT NOT NULL,
  node_id VARCHAR(128) NOT NULL,
  node_name VARCHAR(255),
  title VARCHAR(255) NOT NULL,
  description TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  decision VARCHAR(32),
  input_json JSONB,
  response_json JSONB,
  metadata_json JSONB,
  requested_by BIGINT,
  decided_by BIGINT,
  expires_at TIMESTAMPTZ,
  decided_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_human_approval_tasks_status
    CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')),
  CONSTRAINT chk_human_approval_tasks_decision
    CHECK (decision IS NULL OR decision IN ('approve', 'reject'))
);

CREATE INDEX IF NOT EXISTS idx_human_approval_tasks_workflow_id
  ON human_approval_tasks(workflow_id);

CREATE INDEX IF NOT EXISTS idx_human_approval_tasks_run_id
  ON human_approval_tasks(run_id);

CREATE INDEX IF NOT EXISTS idx_human_approval_tasks_status
  ON human_approval_tasks(status);

CREATE INDEX IF NOT EXISTS idx_human_approval_tasks_created_at
  ON human_approval_tasks(created_at);

CREATE INDEX IF NOT EXISTS idx_human_approval_tasks_metadata_gin
  ON human_approval_tasks USING GIN(metadata_json);
