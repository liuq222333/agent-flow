-- Generated workflow code metadata patch
-- Target database: PostgreSQL 14+ with pgvector
-- Intended usage: run after 001_init_agent_workflow_platform_mvp.sql and 002_observability_and_governance.sql.

ALTER TABLE workflow_versions
  ADD COLUMN IF NOT EXISTS code_path TEXT,
  ADD COLUMN IF NOT EXISTS code_hash VARCHAR(128),
  ADD COLUMN IF NOT EXISTS code_generated_at TIMESTAMPTZ;
