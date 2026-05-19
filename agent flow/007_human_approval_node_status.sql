-- Allows Human Approval nodes to stay visible as waiting in node trace.
-- Intended usage: run after 006_human_approval_tasks.sql.

ALTER TABLE node_runs DROP CONSTRAINT IF EXISTS chk_node_runs_status;

ALTER TABLE node_runs
  ADD CONSTRAINT chk_node_runs_status
  CHECK (status IN ('running', 'success', 'failed', 'skipped', 'retrying', 'waiting_approval'));
