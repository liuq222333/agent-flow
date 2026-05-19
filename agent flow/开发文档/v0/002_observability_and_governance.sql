-- Agent Workflow Platform MVP governance and observability schema patch
-- Target database: PostgreSQL 14+ with pgvector
-- Intended usage: run after 001_init_agent_workflow_platform_mvp.sql as a versioned migration.

ALTER TABLE knowledge_bases
  ADD COLUMN IF NOT EXISTS embedding_dim INT NOT NULL DEFAULT 1536,
  ADD COLUMN IF NOT EXISTS tokenizer VARCHAR(64) NOT NULL DEFAULT 'cl100k_base',
  ADD COLUMN IF NOT EXISTS slug VARCHAR(64);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_kb_embedding_dim'
      AND conrelid = 'knowledge_bases'::regclass
  ) THEN
    ALTER TABLE knowledge_bases
      ADD CONSTRAINT chk_kb_embedding_dim
      CHECK (embedding_dim = 1536);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uk_knowledge_bases_slug
  ON knowledge_bases(slug)
  WHERE deleted_at IS NULL;

ALTER TABLE secrets
  ADD COLUMN IF NOT EXISTS key_version INT NOT NULL DEFAULT 1;

ALTER TABLE workflow_runs
  ADD COLUMN IF NOT EXISTS metadata_json JSONB;

CREATE INDEX IF NOT EXISTS idx_workflow_runs_metadata_gin
  ON workflow_runs USING GIN(metadata_json);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_audit_logs_action_format'
      AND conrelid = 'audit_logs'::regclass
  ) THEN
    ALTER TABLE audit_logs
      ADD CONSTRAINT chk_audit_logs_action_format
      CHECK (action ~ '^[a-z][a-z_]*\.[a-z][a-z_]*(\.[a-z][a-z_]*)?$');
  END IF;
END $$;

UPDATE model_providers
SET config_json = jsonb_set(
  COALESCE(config_json, '{}'::jsonb),
  '{api_key_secret}',
  '"openai_api_key"'::jsonb,
  true
)
WHERE name = 'openai'
  AND NOT (COALESCE(config_json, '{}'::jsonb) ? 'api_key_secret');

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON knowledge_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
