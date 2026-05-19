import type { Node } from "@xyflow/react";
import type { LucideIcon } from "lucide-react";

export type JsonObject = Record<string, unknown>;

export type NodeType =
  | "start"
  | "input"
  | "llm"
  | "knowledge_base"
  | "intent"
  | "branch"
  | "set_variable"
  | "api"
  | "message"
  | "output"
  | "end";

export type GraphNode = {
  id: string;
  type: NodeType;
  name: string;
  description?: string | null;
  position: { x: number; y: number };
  config: JsonObject;
  input_mapping?: JsonObject;
  output_mapping?: JsonObject;
  enabled?: boolean;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
};

export type WorkflowGraph = {
  schema_version: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type Workflow = {
  id: number;
  name: string;
  description?: string | null;
  status: "draft" | "published" | "archived";
  current_version_id?: number | null;
  current_version?: number | null;
  draft_graph_json: WorkflowGraph;
  updated_at: string;
  latest_run?: { run_id: number; status: string; created_at: string } | null;
};

export type WorkflowVersion = {
  id: number;
  workflow_id: number;
  version: number;
  schema_version?: string | null;
  release_note?: string | null;
  code_path?: string | null;
  code_hash?: string | null;
  code_hash_actual?: string | null;
  code_modified?: boolean | null;
  code_status?: string | null;
  code_generated_at?: string | null;
  created_at?: string | null;
};

export type WorkflowVersionCode = WorkflowVersion & {
  source: string;
};

export type GeneratedWorkflowCleanupReport = {
  dry_run: boolean;
  removed_temp_dirs: string[];
  removed_orphan_version_dirs: string[];
  removed_empty_workflow_dirs: string[];
  kept_version_dirs: string[];
  removed_total: number;
  kept_total: number;
};

export type ActiveSection = "workflow" | "knowledge" | "tools" | "secrets" | "models" | "ops";

export type OpsQueue = JsonObject & {
  name?: string;
  queue?: string;
  queue_name?: string;
  pending?: number;
  queued?: number;
  ready?: number;
  main_depth?: number;
  processing_depth?: number;
  dead_letter_depth?: number;
  active?: number;
  running?: number;
  delayed?: number;
  dead?: number;
  failed?: number;
};

export type OpsWorker = JsonObject & {
  id?: string | number;
  name?: string;
  worker_id?: string | number;
  status?: string;
  queue?: string;
  queue_name?: string;
  current_job_id?: string | number | null;
  heartbeat_at?: string | null;
  last_seen_at?: string | null;
  updated_at?: string | null;
};

export type OpsDeadJob = JsonObject & {
  id?: string | number;
  job_id?: string | number;
  run_id?: string | number;
  workflow_id?: string | number;
  status?: string;
  error?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  failed_at?: string | null;
  updated_at?: string | null;
};

export type OpsFailedRun = JsonObject & {
  run_id?: string | number;
  id?: string | number;
  workflow_id?: string | number;
  workflow_version_id?: string | number;
  version_id?: string | number;
  status?: string;
  error_code?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type KnowledgeBase = {
  id: number;
  name: string;
  description?: string | null;
  status: string;
  embedding_model?: string | null;
  embedding_dim?: number | null;
  tokenizer?: string | null;
  config_json?: JsonObject | null;
  document_count?: number | null;
  indexed_document_count?: number | null;
  chunk_count?: number | null;
  updated_at?: string | null;
};

export type KnowledgeDocument = {
  id: number;
  file_name: string;
  file_type?: string | null;
  file_size?: number | null;
  status: string;
  created_at?: string | null;
};

export type ApiTool = {
  id: number;
  name: string;
  type: "api";
  description?: string | null;
  status: string;
  config_json?: JsonObject | null;
  updated_at?: string | null;
};

export type Secret = {
  id: number;
  secret_key: string;
  display_name?: string | null;
  status: string;
  key_version: number;
  updated_at?: string | null;
};

export type ModelProvider = {
  id: number;
  name: string;
  provider_type: string;
  base_url?: string | null;
  status: string;
  config_json?: JsonObject | null;
};

export type ModelConfig = {
  id: number;
  provider_id: number;
  model_name: string;
  model_type: string;
  display_name?: string | null;
  context_window?: number | null;
  default_config?: JsonObject | null;
  status: string;
};

export type ModelProviderDraft = {
  name: string;
  provider_type: string;
  base_url: string;
  status: string;
  config: string;
  error?: string | null;
};

export type ModelConfigDraft = {
  provider_id: string;
  model_name: string;
  model_type: string;
  display_name: string;
  context_window: string;
  default_config: string;
  status: string;
  error?: string | null;
};

export type ValidationResult = {
  valid: boolean;
  errors: Array<{ code: string; message: string; path: string; node_id?: string | null }>;
  warnings: Array<{ code: string; message: string; path: string; node_id?: string | null }>;
};

export type NodeRun = {
  id: number;
  node_id: string;
  node_type: string;
  node_name?: string | null;
  status: string;
  duration_ms?: number | null;
  input_json?: JsonObject | null;
  output_json?: JsonObject | null;
  metadata_json?: JsonObject | null;
  error_code?: string | null;
  error_message?: string | null;
};

export type RunTrace = {
  run: {
    id: number;
    run_id?: number;
    status: string;
    output_json?: JsonObject | null;
    metadata_json?: JsonObject | null;
    error_code?: string | null;
    error_message?: string | null;
  };
  nodes: NodeRun[];
  graph_json: WorkflowGraph;
};

export type RunListItem = {
  id?: number;
  run_id?: number;
  status: string;
  created_at?: string | null;
};

export type RunMode = "sync" | "async";

export type KnowledgeChunk = {
  id?: number;
  chunk_id?: string;
  document_id?: number;
  chunk_index?: number;
  content?: string;
  text?: string;
  token_count?: number;
  score?: number;
  retrieval_mode?: string;
  metadata_json?: JsonObject | null;
  source?: {
    document_id?: number;
    file_name?: string;
    chunk_index?: number;
    metadata_json?: JsonObject | null;
  };
};

export type NodeCatalogItem = {
  type: NodeType;
  label: string;
  group: string;
  Icon: LucideIcon;
  config: JsonObject;
  input_mapping?: JsonObject;
  output_mapping?: JsonObject;
};

export type WorkflowNodeData = Record<string, unknown> & {
  name: string;
  nodeType: NodeType;
  status?: string;
  onQuickAdd: (sourceNodeId: string) => void;
  onManualConnectStart: (sourceNodeId: string, clientX: number, clientY: number) => void;
};

export type WorkflowFlowNode = Node<WorkflowNodeData, "workflowNode">;

export type PendingConnection = {
  sourceNodeId: string;
  startClientX: number;
  startClientY: number;
  from: { x: number; y: number };
  to: { x: number; y: number };
};

export type NodeEdgeAnchors = Record<
  string,
  {
    source: { x: number; y: number };
    target: { x: number; y: number };
  }
>;

export type NodeDragPreview = {
  type: NodeType;
  x: number;
  y: number;
  overCanvas: boolean;
};

export type JsonNodeField = "config" | "input_mapping" | "output_mapping";

export type ToolDraft = {
  name: string;
  description: string;
  config: string;
  error?: string | null;
};

export type SecretDraft = {
  display_name: string;
  value: string;
};

export type InspectorTab = "config" | "run" | "trace";
