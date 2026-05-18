-- Agent Workflow Platform MVP initial schema
-- Target database: PostgreSQL 14+ with pgvector
-- Intended usage: versioned migration executed once by Flyway, Liquibase, Alembic, Prisma, TypeORM, or a similar migration tool.
-- If you manually re-run this file against the same database, existing foreign-key constraints may already exist.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE,
  username VARCHAR(128),
  display_name VARCHAR(128),
  role VARCHAR(32) NOT NULL DEFAULT 'editor',
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_users_role CHECK (role IN ('admin', 'editor', 'viewer')),
  CONSTRAINT chk_users_status CHECK (status IN ('active', 'disabled', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE TABLE IF NOT EXISTS workflows (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  current_version_id BIGINT,
  draft_graph_json JSONB,
  created_by BIGINT,
  updated_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  archived_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ,
  CONSTRAINT chk_workflows_status CHECK (status IN ('draft', 'published', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
CREATE INDEX IF NOT EXISTS idx_workflows_created_by ON workflows(created_by);
CREATE INDEX IF NOT EXISTS idx_workflows_updated_at ON workflows(updated_at);
CREATE INDEX IF NOT EXISTS idx_workflows_deleted_at ON workflows(deleted_at);
CREATE INDEX IF NOT EXISTS idx_workflows_draft_graph_gin ON workflows USING GIN(draft_graph_json);

CREATE TABLE IF NOT EXISTS workflow_versions (
  id BIGSERIAL PRIMARY KEY,
  workflow_id BIGINT NOT NULL,
  version INT NOT NULL,
  schema_version VARCHAR(32) NOT NULL DEFAULT '1.0',
  graph_json JSONB NOT NULL,
  graph_hash VARCHAR(128),
  release_note TEXT,
  published_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uk_workflow_versions_workflow_version UNIQUE (workflow_id, version)
);

CREATE INDEX IF NOT EXISTS idx_workflow_versions_workflow_id ON workflow_versions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_versions_created_at ON workflow_versions(created_at);
CREATE INDEX IF NOT EXISTS idx_workflow_versions_graph_gin ON workflow_versions USING GIN(graph_json);

CREATE TABLE IF NOT EXISTS workflow_runs (
  id BIGSERIAL PRIMARY KEY,
  workflow_id BIGINT NOT NULL,
  version_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  trigger_type VARCHAR(32) NOT NULL DEFAULT 'manual',
  input_json JSONB,
  output_json JSONB,
  state_json JSONB,
  error_code VARCHAR(128),
  error_message TEXT,
  created_by BIGINT,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_workflow_runs_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
  CONSTRAINT chk_workflow_runs_trigger_type CHECK (trigger_type IN ('manual', 'api', 'test', 'schedule', 'webhook', 'batch'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_version_id ON workflow_runs(version_id);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_by ON workflow_runs(created_by);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at ON workflow_runs(created_at);

CREATE TABLE IF NOT EXISTS node_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL,
  node_id VARCHAR(128) NOT NULL,
  node_type VARCHAR(64) NOT NULL,
  node_name VARCHAR(255),
  status VARCHAR(32) NOT NULL,
  attempt INT NOT NULL DEFAULT 1,
  input_json JSONB,
  output_json JSONB,
  error_code VARCHAR(128),
  error_message TEXT,
  duration_ms INT,
  metadata_json JSONB,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_node_runs_status CHECK (status IN ('running', 'success', 'failed', 'skipped', 'retrying')),
  CONSTRAINT chk_node_runs_attempt CHECK (attempt >= 1)
);

CREATE INDEX IF NOT EXISTS idx_node_runs_run_id ON node_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_node_runs_node_id ON node_runs(node_id);
CREATE INDEX IF NOT EXISTS idx_node_runs_node_type ON node_runs(node_type);
CREATE INDEX IF NOT EXISTS idx_node_runs_status ON node_runs(status);
CREATE INDEX IF NOT EXISTS idx_node_runs_created_at ON node_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_node_runs_metadata_gin ON node_runs USING GIN(metadata_json);

CREATE TABLE IF NOT EXISTS model_providers (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  provider_type VARCHAR(64) NOT NULL,
  base_url TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  config_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uk_model_providers_name UNIQUE (name),
  CONSTRAINT chk_model_providers_status CHECK (status IN ('active', 'disabled'))
);

CREATE INDEX IF NOT EXISTS idx_model_providers_status ON model_providers(status);

CREATE TABLE IF NOT EXISTS model_configs (
  id BIGSERIAL PRIMARY KEY,
  provider_id BIGINT NOT NULL,
  model_name VARCHAR(255) NOT NULL,
  model_type VARCHAR(64) NOT NULL,
  display_name VARCHAR(255),
  context_window INT,
  default_config_json JSONB,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_model_configs_model_type CHECK (model_type IN ('chat', 'embedding', 'rerank')),
  CONSTRAINT chk_model_configs_status CHECK (status IN ('active', 'disabled')),
  CONSTRAINT uk_model_configs_provider_model UNIQUE (provider_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_model_configs_provider_id ON model_configs(provider_id);
CREATE INDEX IF NOT EXISTS idx_model_configs_model_type ON model_configs(model_type);
CREATE INDEX IF NOT EXISTS idx_model_configs_status ON model_configs(status);

CREATE TABLE IF NOT EXISTS secrets (
  id BIGSERIAL PRIMARY KEY,
  secret_key VARCHAR(128) NOT NULL,
  display_name VARCHAR(255),
  encrypted_value TEXT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_by BIGINT,
  updated_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT chk_secrets_status CHECK (status IN ('active', 'disabled'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_secrets_key_active
  ON secrets(secret_key)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_secrets_status ON secrets(status);
CREATE INDEX IF NOT EXISTS idx_secrets_created_by ON secrets(created_by);

CREATE TABLE IF NOT EXISTS tools (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  type VARCHAR(64) NOT NULL,
  description TEXT,
  config_json JSONB NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT chk_tools_type CHECK (type IN ('api')),
  CONSTRAINT chk_tools_status CHECK (status IN ('active', 'disabled', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_tools_type ON tools(type);
CREATE INDEX IF NOT EXISTS idx_tools_status ON tools(status);
CREATE INDEX IF NOT EXISTS idx_tools_created_by ON tools(created_by);
CREATE INDEX IF NOT EXISTS idx_tools_config_gin ON tools USING GIN(config_json);

CREATE TABLE IF NOT EXISTS knowledge_bases (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  embedding_model VARCHAR(255),
  config_json JSONB,
  created_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT chk_knowledge_bases_status CHECK (status IN ('active', 'disabled', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_bases_status ON knowledge_bases(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_created_by ON knowledge_bases(created_by);
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_deleted_at ON knowledge_bases(deleted_at);

CREATE TABLE IF NOT EXISTS documents (
  id BIGSERIAL PRIMARY KEY,
  knowledge_base_id BIGINT NOT NULL,
  file_name VARCHAR(512) NOT NULL,
  file_type VARCHAR(64),
  file_size BIGINT,
  storage_url TEXT,
  content_hash VARCHAR(128),
  status VARCHAR(64) NOT NULL DEFAULT 'uploaded',
  error_stage VARCHAR(64),
  error_message TEXT,
  uploaded_by BIGINT,
  metadata_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT chk_documents_status CHECK (status IN ('uploaded', 'parsing', 'chunking', 'embedding', 'indexed', 'failed', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_documents_kb_id ON documents(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_uploaded_by ON documents(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_metadata_gin ON documents USING GIN(metadata_json);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id BIGSERIAL PRIMARY KEY,
  knowledge_base_id BIGINT NOT NULL,
  document_id BIGINT NOT NULL,
  chunk_index INT NOT NULL,
  content TEXT NOT NULL,
  token_count INT,
  embedding vector(1536),
  status VARCHAR(64) NOT NULL DEFAULT 'created',
  metadata_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_knowledge_chunks_status CHECK (status IN ('created', 'indexed', 'failed', 'deleted')),
  CONSTRAINT chk_knowledge_chunks_index CHECK (chunk_index >= 0)
);

CREATE INDEX IF NOT EXISTS idx_chunks_kb_id ON knowledge_chunks(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_status ON knowledge_chunks(status);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin ON knowledge_chunks USING GIN(metadata_json);
CREATE UNIQUE INDEX IF NOT EXISTS uk_chunks_document_index ON knowledge_chunks(document_id, chunk_index);

-- Requires pgvector version that supports HNSW. If unavailable, comment this index
-- and create IVFFlat or no vector index for the first local MVP run.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON knowledge_chunks
  USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS document_processing_jobs (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL,
  job_type VARCHAR(64) NOT NULL,
  status VARCHAR(64) NOT NULL DEFAULT 'pending',
  error_stage VARCHAR(64),
  error_message TEXT,
  retry_count INT NOT NULL DEFAULT 0,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_doc_jobs_job_type CHECK (job_type IN ('parse', 'chunk', 'embedding', 'reindex')),
  CONSTRAINT chk_doc_jobs_status CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled')),
  CONSTRAINT chk_doc_jobs_retry_count CHECK (retry_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_doc_jobs_document_id ON document_processing_jobs(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_jobs_status ON document_processing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_doc_jobs_job_type ON document_processing_jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_doc_jobs_created_at ON document_processing_jobs(created_at);

CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  actor_user_id BIGINT,
  action VARCHAR(128) NOT NULL,
  resource_type VARCHAR(64) NOT NULL,
  resource_id VARCHAR(128),
  request_id VARCHAR(128),
  ip_address VARCHAR(64),
  user_agent TEXT,
  detail_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);

ALTER TABLE workflows
  ADD CONSTRAINT fk_workflows_created_by
  FOREIGN KEY (created_by) REFERENCES users(id);

ALTER TABLE workflows
  ADD CONSTRAINT fk_workflows_updated_by
  FOREIGN KEY (updated_by) REFERENCES users(id);

ALTER TABLE workflow_versions
  ADD CONSTRAINT fk_workflow_versions_workflow
  FOREIGN KEY (workflow_id) REFERENCES workflows(id);

ALTER TABLE workflow_versions
  ADD CONSTRAINT fk_workflow_versions_published_by
  FOREIGN KEY (published_by) REFERENCES users(id);

ALTER TABLE workflows
  ADD CONSTRAINT fk_workflows_current_version
  FOREIGN KEY (current_version_id) REFERENCES workflow_versions(id);

ALTER TABLE workflow_runs
  ADD CONSTRAINT fk_workflow_runs_workflow
  FOREIGN KEY (workflow_id) REFERENCES workflows(id);

ALTER TABLE workflow_runs
  ADD CONSTRAINT fk_workflow_runs_version
  FOREIGN KEY (version_id) REFERENCES workflow_versions(id);

ALTER TABLE workflow_runs
  ADD CONSTRAINT fk_workflow_runs_created_by
  FOREIGN KEY (created_by) REFERENCES users(id);

ALTER TABLE node_runs
  ADD CONSTRAINT fk_node_runs_run
  FOREIGN KEY (run_id) REFERENCES workflow_runs(id);

ALTER TABLE model_configs
  ADD CONSTRAINT fk_model_configs_provider
  FOREIGN KEY (provider_id) REFERENCES model_providers(id);

ALTER TABLE secrets
  ADD CONSTRAINT fk_secrets_created_by
  FOREIGN KEY (created_by) REFERENCES users(id);

ALTER TABLE secrets
  ADD CONSTRAINT fk_secrets_updated_by
  FOREIGN KEY (updated_by) REFERENCES users(id);

ALTER TABLE tools
  ADD CONSTRAINT fk_tools_created_by
  FOREIGN KEY (created_by) REFERENCES users(id);

ALTER TABLE knowledge_bases
  ADD CONSTRAINT fk_knowledge_bases_created_by
  FOREIGN KEY (created_by) REFERENCES users(id);

ALTER TABLE documents
  ADD CONSTRAINT fk_documents_kb
  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id);

ALTER TABLE documents
  ADD CONSTRAINT fk_documents_uploaded_by
  FOREIGN KEY (uploaded_by) REFERENCES users(id);

ALTER TABLE knowledge_chunks
  ADD CONSTRAINT fk_chunks_kb
  FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id);

ALTER TABLE knowledge_chunks
  ADD CONSTRAINT fk_chunks_document
  FOREIGN KEY (document_id) REFERENCES documents(id);

ALTER TABLE document_processing_jobs
  ADD CONSTRAINT fk_doc_jobs_document
  FOREIGN KEY (document_id) REFERENCES documents(id);

ALTER TABLE audit_logs
  ADD CONSTRAINT fk_audit_logs_actor
  FOREIGN KEY (actor_user_id) REFERENCES users(id);

INSERT INTO model_providers (name, provider_type, status, config_json)
VALUES
  ('openai', 'openai', 'active', '{}'::jsonb)
ON CONFLICT (name) DO NOTHING;

INSERT INTO model_configs (
  provider_id,
  model_name,
  model_type,
  display_name,
  context_window,
  default_config_json,
  status
)
SELECT
  p.id,
  'gpt-4.1-mini',
  'chat',
  'GPT-4.1 Mini',
  128000,
  '{"temperature": 0.3, "max_tokens": 1000}'::jsonb,
  'active'
FROM model_providers p
WHERE p.name = 'openai'
ON CONFLICT (provider_id, model_name) DO NOTHING;

INSERT INTO model_configs (
  provider_id,
  model_name,
  model_type,
  display_name,
  context_window,
  default_config_json,
  status
)
SELECT
  p.id,
  'text-embedding-3-small',
  'embedding',
  'Text Embedding 3 Small',
  NULL,
  '{"dimensions": 1536}'::jsonb,
  'active'
FROM model_providers p
WHERE p.name = 'openai'
ON CONFLICT (provider_id, model_name) DO NOTHING;
