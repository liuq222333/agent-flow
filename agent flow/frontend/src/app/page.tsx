"use client";

import {
  Activity,
  Bot,
  BookOpen,
  CheckCircle2,
  CircleStop,
  Cpu,
  Database,
  EyeOff,
  FileJson,
  GitBranch,
  KeyRound,
  LogIn,
  LogOut,
  MessageSquare,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Rocket,
  Save,
  Search,
  SquareTerminal,
  TextCursorInput,
  Trash2,
  Upload,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import { type ChangeEvent, type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

type JsonObject = Record<string, unknown>;
type NodeType =
  | "start"
  | "input"
  | "llm"
  | "knowledge_base"
  | "intent"
  | "branch"
  | "api"
  | "message"
  | "output"
  | "end";

type GraphNode = {
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

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
};

type WorkflowGraph = {
  schema_version: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

type Workflow = {
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

type WorkflowVersion = {
  id: number;
  workflow_id: number;
  version: number;
  schema_version?: string | null;
  release_note?: string | null;
  code_path?: string | null;
  code_hash?: string | null;
  code_generated_at?: string | null;
  created_at?: string | null;
};

type ActiveSection = "workflow" | "knowledge" | "tools" | "secrets" | "models";

type KnowledgeBase = {
  id: number;
  name: string;
  description?: string | null;
  status: string;
  embedding_model?: string | null;
  embedding_dim?: number | null;
  document_count?: number | null;
  updated_at?: string | null;
};

type KnowledgeDocument = {
  id: number;
  file_name: string;
  file_type?: string | null;
  file_size?: number | null;
  status: string;
  created_at?: string | null;
};

type ApiTool = {
  id: number;
  name: string;
  type: "api";
  description?: string | null;
  status: string;
  config_json?: JsonObject | null;
  updated_at?: string | null;
};

type Secret = {
  id: number;
  secret_key: string;
  display_name?: string | null;
  status: string;
  key_version: number;
  updated_at?: string | null;
};

type ModelProvider = {
  id: number;
  name: string;
  provider_type: string;
  base_url?: string | null;
  status: string;
  config_json?: JsonObject | null;
};

type ModelConfig = {
  id: number;
  provider_id: number;
  model_name: string;
  model_type: string;
  display_name?: string | null;
  context_window?: number | null;
  default_config?: JsonObject | null;
  status: string;
};

type ValidationResult = {
  valid: boolean;
  errors: Array<{ code: string; message: string; path: string; node_id?: string | null }>;
  warnings: Array<{ code: string; message: string; path: string; node_id?: string | null }>;
};

type NodeRun = {
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

type RunTrace = {
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

type RunListItem = {
  id?: number;
  run_id?: number;
  status: string;
  created_at?: string | null;
};

type RunMode = "sync" | "async";

type KnowledgeChunk = {
  id?: number;
  chunk_id?: string;
  document_id?: number;
  chunk_index?: number;
  content?: string;
  text?: string;
  score?: number;
  metadata_json?: JsonObject | null;
  source?: {
    document_id?: number;
    file_name?: string;
    chunk_index?: number;
    metadata_json?: JsonObject | null;
  };
};

type NodeCatalogItem = {
  type: NodeType;
  label: string;
  group: string;
  Icon: LucideIcon;
  config: JsonObject;
  input_mapping?: JsonObject;
  output_mapping?: JsonObject;
};

type JsonNodeField = "config" | "input_mapping" | "output_mapping";

type ToolDraft = {
  name: string;
  description: string;
  config: string;
  error?: string | null;
};

type SecretDraft = {
  display_name: string;
  value: string;
};

const emptyGraph: WorkflowGraph = { schema_version: "1.0", nodes: [], edges: [] };
const defaultRunInput = JSON.stringify({ user_query: "我想申请退款" }, null, 2);

const nodeCatalog: NodeCatalogItem[] = [
  { type: "start", label: "开始", group: "输入输出", Icon: CircleStop, config: {} },
  {
    type: "input",
    label: "用户输入",
    group: "输入输出",
    Icon: TextCursorInput,
    config: {
      fields: [{ name: "user_query", type: "string", label: "用户问题", required: true }],
    },
    output_mapping: { user_query: "variables.user_query" },
  },
  {
    type: "llm",
    label: "生成回答",
    group: "AI",
    Icon: Bot,
    config: {
      provider: "mock",
      model: "local-mock",
      system_prompt: "你是一个本地调试助手。",
      user_prompt: "问题：{{input.user_query}}",
      temperature: 0.2,
    },
    output_mapping: { answer: "variables.answer" },
  },
  {
    type: "knowledge_base",
    label: "检索知识库",
    group: "知识",
    Icon: Database,
    config: {
      knowledge_base_ids: [],
      query: "{{question}}",
      retrieval_mode: "vector",
      top_k: 5,
      score_threshold: 0.65,
      context_budget_tokens: 3000,
    },
    input_mapping: { question: "{{input.user_query}}" },
    output_mapping: { chunks: "variables.kb_context" },
  },
  {
    type: "intent",
    label: "识别意图",
    group: "AI",
    Icon: LogIn,
    config: {
      model: "local-mock",
      intents: [
        { name: "refund_request", description: "用户申请退款" },
        { name: "general_question", description: "普通咨询问题" },
      ],
      fallback_intent: "general_question",
    },
    input_mapping: { text: "{{input.user_query}}" },
    output_mapping: {
      intent: "variables.intent_result.intent",
      confidence: "variables.intent_result.confidence",
    },
  },
  { type: "branch", label: "条件分支", group: "控制流", Icon: GitBranch, config: { branches: [] } },
  {
    type: "api",
    label: "调用 API",
    group: "工具",
    Icon: SquareTerminal,
    config: {
      method: "GET",
      url: "",
      headers: {},
      query_params: {},
      body: {},
      response_path: "",
      timeout: 30,
    },
    output_mapping: { response: "variables.api_response" },
  },
  {
    type: "message",
    label: "回复消息",
    group: "消息",
    Icon: MessageSquare,
    config: { message_type: "text", template: "{{variables.answer}}" },
    input_mapping: { answer: "{{variables.answer}}" },
    output_mapping: { message: "messages" },
  },
  {
    type: "output",
    label: "最终输出",
    group: "输入输出",
    Icon: LogOut,
    config: { outputs: { answer: "{{variables.answer}}" } },
  },
  { type: "end", label: "结束", group: "输入输出", Icon: CheckCircle2, config: {} },
];

const nodeJsonFieldLabels: Record<JsonNodeField, string> = {
  config: "config JSON",
  input_mapping: "input_mapping JSON",
  output_mapping: "output_mapping JSON",
};

const adminSections: Array<{ id: ActiveSection; label: string; Icon: LucideIcon }> = [
  { id: "workflow", label: "Workflow", Icon: GitBranch },
  { id: "knowledge", label: "Knowledge", Icon: BookOpen },
  { id: "tools", label: "Tools", Icon: Wrench },
  { id: "secrets", label: "Secrets", Icon: KeyRound },
  { id: "models", label: "Models", Icon: Cpu },
];

export default function Home() {
  const [activeSection, setActiveSection] = useState<ActiveSection>("workflow");
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(null);
  const [currentVersionDetail, setCurrentVersionDetail] = useState<WorkflowVersion | null>(null);
  const [graph, setGraph] = useState<WorkflowGraph>(emptyGraph);
  const [flowNodes, setFlowNodes] = useState<Node[]>([]);
  const [flowEdges, setFlowEdges] = useState<Edge[]>([]);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeJsonDrafts, setNodeJsonDrafts] = useState<Record<JsonNodeField, string>>({
    config: "{}",
    input_mapping: "{}",
    output_mapping: "{}",
  });
  const [nodeJsonErrors, setNodeJsonErrors] = useState<Record<JsonNodeField, string | null>>({
    config: null,
    input_mapping: null,
    output_mapping: null,
  });
  const [nameDraft, setNameDraft] = useState("");
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [runInput, setRunInput] = useState(defaultRunInput);
  const [runMode, setRunMode] = useState<RunMode>("sync");
  const [runInputError, setRunInputError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [statusLine, setStatusLine] = useState("正在连接本地 API");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState<number | null>(null);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeForm, setKnowledgeForm] = useState({
    name: "",
    description: "",
    embedding_model: "local-embedding",
  });
  const [retrieveForm, setRetrieveForm] = useState({
    query: "",
    top_k: "5",
    score_threshold: "0",
  });
  const [retrieveResults, setRetrieveResults] = useState<KnowledgeChunk[]>([]);
  const [retrieveError, setRetrieveError] = useState<string | null>(null);
  const [tools, setTools] = useState<ApiTool[]>([]);
  const [toolForm, setToolForm] = useState({
    name: "",
    description: "",
    config: stringifyJson({
      method: "GET",
      url: "https://example.com",
      headers: {},
      timeout: 30,
    }),
  });
  const [toolConfigError, setToolConfigError] = useState<string | null>(null);
  const [toolDrafts, setToolDrafts] = useState<Record<number, ToolDraft>>({});
  const [toolTestInputs, setToolTestInputs] = useState<Record<number, string>>({});
  const [toolTestResults, setToolTestResults] = useState<Record<number, string>>({});
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [secretForm, setSecretForm] = useState({ secret_key: "", display_name: "", value: "" });
  const [secretDrafts, setSecretDrafts] = useState<Record<number, SecretDraft>>({});
  const [modelProviders, setModelProviders] = useState<ModelProvider[]>([]);
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);

  const selectedVersion = selectedWorkflow?.current_version_id
    ? `v${selectedWorkflow.current_version ?? selectedWorkflow.current_version_id}`
    : "未发布";

  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [graph.nodes, selectedNodeId],
  );

  const traceStatusByNodeId = useMemo(() => {
    const statusMap = new Map<string, string>();
    trace?.nodes.forEach((node) => {
      statusMap.set(node.node_id, node.status);
    });
    return statusMap;
  }, [trace]);

  useEffect(() => {
    setFlowNodes((currentNodes) => graphToFlowNodes(graph, selectedNodeId, traceStatusByNodeId, currentNodes));
    setFlowEdges((currentEdges) => graphToFlowEdges(graph, currentEdges));
  }, [graph, selectedNodeId, traceStatusByNodeId]);

  useEffect(() => {
    if (!selectedNode) {
      setNodeJsonDrafts({ config: "{}", input_mapping: "{}", output_mapping: "{}" });
      setNodeJsonErrors({ config: null, input_mapping: null, output_mapping: null });
      return;
    }

    setNodeJsonDrafts({
      config: stringifyJson(selectedNode.config),
      input_mapping: stringifyJson(selectedNode.input_mapping ?? {}),
      output_mapping: stringifyJson(selectedNode.output_mapping ?? {}),
    });
    setNodeJsonErrors({ config: null, input_mapping: null, output_mapping: null });
  }, [selectedNodeId, selectedNode]);

  const loadWorkflow = useCallback(async (workflowId: number) => {
    const response = await fetch(`${apiBaseUrl}/workflows/${workflowId}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`GET /workflows/${workflowId} ${response.status}`);
    }
    const workflow = (await response.json()) as Workflow;
    let versionDetail: WorkflowVersion | null = null;
    if (workflow.current_version_id) {
      const versionResponse = await fetch(`${apiBaseUrl}/workflow-versions/${workflow.current_version_id}`, {
        cache: "no-store",
      });
      if (versionResponse.ok) {
        versionDetail = (await versionResponse.json()) as WorkflowVersion;
      }
    }
    setSelectedWorkflow(workflow);
    setCurrentVersionDetail(versionDetail);
    setNameDraft(workflow.name);
    setDescriptionDraft(workflow.description ?? "");
    setGraph(workflow.draft_graph_json);
    setSelectedNodeId(null);
    setValidation(null);
    setTrace(null);
  }, []);

  const loadRuns = useCallback(async (workflowId: number) => {
    const response = await fetch(`${apiBaseUrl}/runs?workflow_id=${workflowId}&page_size=8`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`GET /runs?workflow_id=${workflowId} ${response.status}`);
    }
    const data = await response.json();
    setRuns((data.items ?? []) as RunListItem[]);
  }, []);

  useEffect(() => {
    if (!selectedWorkflow) {
      setRuns([]);
      return;
    }
    void loadRuns(selectedWorkflow.id).catch((error) => {
      setStatusLine(error instanceof Error ? error.message : "运行历史同步失败");
    });
  }, [loadRuns, selectedWorkflow]);

  const loadWorkflows = useCallback(
    async (preferredWorkflowId?: number) => {
      setBusyAction("refresh");
      try {
        const response = await fetch(`${apiBaseUrl}/workflows`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`GET /workflows ${response.status}`);
        }
        const data = await response.json();
        const items = data.items as Workflow[];
        setWorkflows(items);
        if (items.length > 0) {
          const currentId = preferredWorkflowId ?? items[0].id;
          const next = items.find((item) => item.id === currentId) ?? items[0];
          await loadWorkflow(next.id);
        } else {
          setSelectedWorkflow(null);
          setCurrentVersionDetail(null);
          setGraph(emptyGraph);
          setSelectedNodeId(null);
          setRuns([]);
        }
        setStatusLine("工作流列表已同步");
      } catch (error) {
        setStatusLine(error instanceof Error ? error.message : "同步失败");
      } finally {
        setBusyAction(null);
      }
    },
    [loadWorkflow],
  );

  useEffect(() => {
    void loadWorkflows();
  }, [loadWorkflows]);

  const loadKnowledge = useCallback(async (preferredKnowledgeBaseId?: number) => {
    setBusyAction("knowledge");
    try {
      const response = await fetch(`${apiBaseUrl}/knowledge-bases`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`GET /knowledge-bases ${response.status}`);
      }
      const data = await response.json();
      const items = data.items as KnowledgeBase[];
      setKnowledgeBases(items);
      const nextId = preferredKnowledgeBaseId ?? items[0]?.id ?? null;
      setSelectedKnowledgeBaseId(nextId);
      if (nextId) {
        const documentsResponse = await fetch(`${apiBaseUrl}/knowledge-bases/${nextId}/documents`, {
          cache: "no-store",
        });
        if (documentsResponse.ok) {
          const documentsData = await documentsResponse.json();
          setKnowledgeDocuments(documentsData.items as KnowledgeDocument[]);
        } else {
          setKnowledgeDocuments([]);
        }
      } else {
        setKnowledgeDocuments([]);
      }
      setStatusLine("知识库已同步");
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "知识库同步失败");
    } finally {
      setBusyAction(null);
    }
  }, []);

  const loadKnowledgeDocuments = useCallback(async (kbId: number) => {
    setSelectedKnowledgeBaseId(kbId);
    setBusyAction("knowledge-documents");
    try {
      const response = await fetch(`${apiBaseUrl}/knowledge-bases/${kbId}/documents`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`GET /knowledge-bases/${kbId}/documents ${response.status}`);
      }
      const data = await response.json();
      setKnowledgeDocuments(data.items as KnowledgeDocument[]);
      setStatusLine(`已载入知识库 #${kbId} 文档`);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "文档同步失败");
    } finally {
      setBusyAction(null);
    }
  }, []);

  const loadTools = useCallback(async () => {
    setBusyAction("tools");
    try {
      const response = await fetch(`${apiBaseUrl}/tools?type=api`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`GET /tools ${response.status}`);
      }
      const data = await response.json();
      const items = data.items as ApiTool[];
      setTools(items);
      setToolDrafts((currentDrafts) =>
        items.reduce<Record<number, ToolDraft>>((drafts, tool) => {
          drafts[tool.id] = currentDrafts[tool.id] ?? {
            name: tool.name,
            description: tool.description ?? "",
            config: stringifyJson(tool.config_json ?? {}),
            error: null,
          };
          return drafts;
        }, {}),
      );
      setStatusLine("Tools 已同步");
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "Tools 同步失败");
    } finally {
      setBusyAction(null);
    }
  }, []);

  const loadSecrets = useCallback(async () => {
    setBusyAction("secrets");
    try {
      const response = await fetch(`${apiBaseUrl}/secrets`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`GET /secrets ${response.status}`);
      }
      const data = await response.json();
      const items = data.items as Secret[];
      setSecrets(items);
      setSecretDrafts((currentDrafts) =>
        items.reduce<Record<number, SecretDraft>>((drafts, secret) => {
          drafts[secret.id] = currentDrafts[secret.id] ?? {
            display_name: secret.display_name ?? "",
            value: "",
          };
          return drafts;
        }, {}),
      );
      setStatusLine("Secrets 已同步");
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "Secrets 同步失败");
    } finally {
      setBusyAction(null);
    }
  }, []);

  const loadModels = useCallback(async () => {
    setBusyAction("models");
    try {
      const [providersResponse, configsResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/model-providers`, { cache: "no-store" }),
        fetch(`${apiBaseUrl}/model-configs`, { cache: "no-store" }),
      ]);
      if (!providersResponse.ok) {
        throw new Error(`GET /model-providers ${providersResponse.status}`);
      }
      if (!configsResponse.ok) {
        throw new Error(`GET /model-configs ${configsResponse.status}`);
      }
      const providersData = await providersResponse.json();
      const configsData = await configsResponse.json();
      setModelProviders(providersData.items as ModelProvider[]);
      setModelConfigs(configsData.items as ModelConfig[]);
      setStatusLine("Models 已同步");
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "Models 同步失败");
    } finally {
      setBusyAction(null);
    }
  }, []);

  useEffect(() => {
    if (activeSection === "knowledge") {
      void loadKnowledge();
    }
    if (activeSection === "tools") {
      void loadTools();
    }
    if (activeSection === "secrets") {
      void loadSecrets();
    }
    if (activeSection === "models") {
      void loadModels();
    }
  }, [activeSection, loadKnowledge, loadModels, loadSecrets, loadTools]);

  useEffect(() => {
    if (activeSection !== "workflow" || !selectedNode) {
      return;
    }
    if (selectedNode.type === "knowledge_base" && knowledgeBases.length === 0) {
      void loadKnowledge(selectedKnowledgeBaseId ?? undefined);
    }
    if (selectedNode.type === "api" && tools.length === 0) {
      void loadTools();
    }
    if (selectedNode.type === "llm" && modelConfigs.length === 0) {
      void loadModels();
    }
  }, [
    activeSection,
    knowledgeBases.length,
    loadKnowledge,
    loadModels,
    loadTools,
    modelConfigs.length,
    selectedKnowledgeBaseId,
    selectedNode,
    tools.length,
  ]);

  const nodeCount = graph.nodes.length;
  const edgeCount = graph.edges.length;

  const runSummary = useMemo(() => {
    if (!trace) {
      return "尚未运行";
    }
    return `${trace.run.status} · ${trace.nodes.length} 个节点`;
  }, [trace]);

  const createWorkflow = async () => {
    setBusyAction("create");
    try {
      const response = await fetch(`${apiBaseUrl}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `本地调试工作流 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`,
          description: "MVP 纵向链路验证",
        }),
      });
      if (!response.ok) {
        throw new Error(`POST /workflows ${response.status}`);
      }
      const workflow = (await response.json()) as Workflow;
      setStatusLine(`已创建工作流 #${workflow.id}`);
      await loadWorkflows(workflow.id);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "创建失败");
    } finally {
      setBusyAction(null);
    }
  };

  const createKnowledgeBase = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusyAction("create-knowledge");
    try {
      const response = await fetch(`${apiBaseUrl}/knowledge-bases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: knowledgeForm.name,
          description: knowledgeForm.description || null,
          embedding_model: knowledgeForm.embedding_model,
          embedding_dim: 1536,
          tokenizer: "cl100k_base",
          config: {},
        }),
      });
      if (!response.ok) {
        throw new Error(`POST /knowledge-bases ${response.status}`);
      }
      const knowledgeBase = (await response.json()) as KnowledgeBase;
      setKnowledgeForm({ name: "", description: "", embedding_model: "local-embedding" });
      setSelectedKnowledgeBaseId(knowledgeBase.id);
      setStatusLine(`已创建知识库 #${knowledgeBase.id}`);
      await loadKnowledge(knowledgeBase.id);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "创建知识库失败");
    } finally {
      setBusyAction(null);
    }
  };

  const createTool = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsedConfig = parseJsonObject(toolForm.config);
    if (parsedConfig.error) {
      setToolConfigError(parsedConfig.error);
      setStatusLine("Tool config 不是合法 JSON 对象");
      return;
    }

    setToolConfigError(null);
    setBusyAction("create-tool");
    try {
      const response = await fetch(`${apiBaseUrl}/tools`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: toolForm.name,
          type: "api",
          description: toolForm.description || null,
          config: parsedConfig.value,
        }),
      });
      if (!response.ok) {
        throw new Error(`POST /tools ${response.status}`);
      }
      const tool = (await response.json()) as ApiTool;
      setToolForm({
        name: "",
        description: "",
        config: stringifyJson({ method: "GET", url: "https://example.com", headers: {}, timeout: 30 }),
      });
      setStatusLine(`已创建 API tool #${tool.id}`);
      await loadTools();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "创建 Tool 失败");
    } finally {
      setBusyAction(null);
    }
  };

  const testTool = async (toolId: number) => {
    const rawInput = toolTestInputs[toolId] ?? "{}";
    const parsedInput = parseJsonObject(rawInput);
    if (parsedInput.error) {
      setToolTestResults((results) => ({ ...results, [toolId]: parsedInput.error ?? "JSON 解析失败" }));
      setStatusLine("Tool test input 不是合法 JSON 对象");
      return;
    }

    setBusyAction(`test-tool-${toolId}`);
    try {
      const response = await fetch(`${apiBaseUrl}/tools/${toolId}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: parsedInput.value }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `POST /tools/${toolId}/test ${response.status}`);
      }
      setToolTestResults((results) => ({ ...results, [toolId]: JSON.stringify(result, null, 2) }));
      setStatusLine(`Tool #${toolId} 测试完成`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Tool 测试失败";
      setToolTestResults((results) => ({ ...results, [toolId]: message }));
      setStatusLine(message);
    } finally {
      setBusyAction(null);
    }
  };

  const createSecret = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusyAction("create-secret");
    try {
      const response = await fetch(`${apiBaseUrl}/secrets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          secret_key: secretForm.secret_key,
          display_name: secretForm.display_name || null,
          value: secretForm.value,
        }),
      });
      if (!response.ok) {
        throw new Error(`POST /secrets ${response.status}`);
      }
      const secret = (await response.json()) as Secret;
      setSecretForm({ secret_key: "", display_name: "", value: "" });
      setStatusLine(`已创建 Secret #${secret.id}`);
      await loadSecrets();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "创建 Secret 失败");
    } finally {
      setBusyAction(null);
    }
  };

  const uploadKnowledgeDocument = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    const kbId = selectedKnowledgeBaseId;
    event.target.value = "";
    if (!file || !kbId) {
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    setBusyAction("upload-document");
    try {
      const response = await fetch(`${apiBaseUrl}/knowledge-bases/${kbId}/documents`, {
        method: "POST",
        body: formData,
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `POST /knowledge-bases/${kbId}/documents ${response.status}`);
      }
      setStatusLine(`已上传文档 #${result.document_id}`);
      await loadKnowledgeDocuments(kbId);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "文档上传失败");
    } finally {
      setBusyAction(null);
    }
  };

  const retryKnowledgeDocument = async (documentId: number) => {
    if (!selectedKnowledgeBaseId) {
      return;
    }

    setBusyAction(`retry-document-${documentId}`);
    try {
      const response = await fetch(`${apiBaseUrl}/documents/${documentId}/retry`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `POST /documents/${documentId}/retry ${response.status}`);
      }
      setStatusLine(`已重试文档 #${documentId}`);
      await loadKnowledgeDocuments(selectedKnowledgeBaseId);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "文档重试失败");
    } finally {
      setBusyAction(null);
    }
  };

  const deleteKnowledgeDocument = async (documentId: number) => {
    if (!selectedKnowledgeBaseId) {
      return;
    }

    setBusyAction(`delete-document-${documentId}`);
    try {
      const response = await fetch(`${apiBaseUrl}/documents/${documentId}`, { method: "DELETE" });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `DELETE /documents/${documentId} ${response.status}`);
      }
      setStatusLine(`已删除文档 #${documentId}`);
      await loadKnowledgeDocuments(selectedKnowledgeBaseId);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "文档删除失败");
    } finally {
      setBusyAction(null);
    }
  };

  const retrieveKnowledge = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const kbId = selectedKnowledgeBaseId;
    if (!kbId) {
      return;
    }

    const topK = Number(retrieveForm.top_k);
    const scoreThreshold = Number(retrieveForm.score_threshold);
    if (!retrieveForm.query.trim() || !Number.isFinite(topK) || !Number.isFinite(scoreThreshold)) {
      setRetrieveError("请填写 query，并确认 top_k / score_threshold 是数字");
      return;
    }

    setRetrieveError(null);
    setBusyAction("retrieve-knowledge");
    try {
      const response = await fetch(`${apiBaseUrl}/knowledge-bases/${kbId}/retrieve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: retrieveForm.query,
          top_k: topK,
          score_threshold: scoreThreshold,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `POST /knowledge-bases/${kbId}/retrieve ${response.status}`);
      }
      setRetrieveResults((result.chunks ?? []) as KnowledgeChunk[]);
      setStatusLine(`Retrieve 返回 ${(result.chunks ?? []).length} 个 chunks`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Retrieve 失败";
      setRetrieveError(message);
      setStatusLine(message);
    } finally {
      setBusyAction(null);
    }
  };

  const updateTool = async (toolId: number) => {
    const draft = toolDrafts[toolId];
    if (!draft) {
      return;
    }

    const parsedConfig = parseJsonObject(draft.config);
    if (parsedConfig.error) {
      setToolDrafts((drafts) => ({ ...drafts, [toolId]: { ...draft, error: parsedConfig.error } }));
      setStatusLine("Tool config 不是合法 JSON 对象");
      return;
    }

    setBusyAction(`update-tool-${toolId}`);
    try {
      const response = await fetch(`${apiBaseUrl}/tools/${toolId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: draft.name,
          type: "api",
          description: draft.description || null,
          config: parsedConfig.value,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `PUT /tools/${toolId} ${response.status}`);
      }
      setToolDrafts((drafts) => ({ ...drafts, [toolId]: { ...draft, error: null } }));
      setStatusLine(`已保存 Tool #${toolId}`);
      await loadTools();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "保存 Tool 失败");
    } finally {
      setBusyAction(null);
    }
  };

  const updateSecret = async (secretId: number) => {
    const draft = secretDrafts[secretId];
    if (!draft) {
      return;
    }

    const payload: { display_name?: string | null; value?: string } = {
      display_name: draft.display_name || null,
    };
    if (draft.value.trim()) {
      payload.value = draft.value;
    }

    setBusyAction(`update-secret-${secretId}`);
    try {
      const response = await fetch(`${apiBaseUrl}/secrets/${secretId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `PUT /secrets/${secretId} ${response.status}`);
      }
      setSecretDrafts((drafts) => ({ ...drafts, [secretId]: { display_name: result.display_name ?? "", value: "" } }));
      setStatusLine(`已更新 Secret #${secretId}`);
      await loadSecrets();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "更新 Secret 失败");
    } finally {
      setBusyAction(null);
    }
  };

  const saveDraft = async () => {
    if (!selectedWorkflow) {
      return false;
    }
    setBusyAction("save");
    try {
      const response = await fetch(`${apiBaseUrl}/workflows/${selectedWorkflow.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: nameDraft,
          description: descriptionDraft,
          draft_graph_json: graph,
        }),
      });
      if (!response.ok) {
        throw new Error(`PUT /workflows/${selectedWorkflow.id} ${response.status}`);
      }
      const workflow = (await response.json()) as Workflow;
      setSelectedWorkflow(workflow);
      setStatusLine("草稿已保存");
      await loadWorkflows(workflow.id);
      return true;
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "保存失败");
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const focusNode = useCallback(
    (nodeId: string) => {
      const node = graph.nodes.find((item) => item.id === nodeId);
      if (!node) {
        setStatusLine(`未找到节点：${nodeId}`);
        return;
      }
      setSelectedNodeId(nodeId);
      flowInstance?.setCenter(node.position.x + 75, node.position.y + 30, {
        zoom: 1.2,
        duration: 320,
      });
      setStatusLine(`已定位节点：${node.name}`);
    },
    [flowInstance, graph.nodes],
  );

  const loadRunTrace = async (runId: number) => {
    setBusyAction("trace");
    try {
      const traceResponse = await fetch(`${apiBaseUrl}/runs/${runId}/trace`, { cache: "no-store" });
      if (!traceResponse.ok) {
        throw new Error(`GET /runs/${runId}/trace ${traceResponse.status}`);
      }
      const nextTrace = (await traceResponse.json()) as RunTrace;
      setTrace(nextTrace);
      setStatusLine(`已载入运行 #${runId} · ${nextTrace.run.status}`);
      const firstFailedNode = nextTrace.nodes.find((node) => node.status === "failed");
      if (firstFailedNode) {
        focusNode(firstFailedNode.node_id);
      }
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "Trace 载入失败");
    } finally {
      setBusyAction(null);
    }
  };

  const validateDraft = async () => {
    if (!selectedWorkflow) {
      return;
    }
    setBusyAction("validate");
    try {
      const response = await fetch(`${apiBaseUrl}/workflows/${selectedWorkflow.id}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "publish", graph_json: graph }),
      });
      const result = (await response.json()) as ValidationResult;
      setValidation(result);
      setStatusLine(result.valid ? "发布校验通过" : "发布校验未通过");
      const issueNodeId = [...result.errors, ...result.warnings].find((issue) => issue.node_id)?.node_id;
      if (issueNodeId) {
        focusNode(issueNodeId);
      }
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "校验失败");
    } finally {
      setBusyAction(null);
    }
  };

  const publishWorkflow = async () => {
    if (!selectedWorkflow) {
      return false;
    }
    setBusyAction("publish");
    try {
      const saved = await saveDraft();
      if (!saved) {
        throw new Error("保存草稿失败，发布已取消");
      }
      const response = await fetch(`${apiBaseUrl}/workflows/${selectedWorkflow.id}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ release_note: "MVP vertical slice" }),
      });
      const result = await response.json();
      if (!response.ok) {
        setValidation(result.detail as ValidationResult);
        throw new Error("发布校验未通过");
      }
      setStatusLine(`已发布 v${result.version}`);
      await loadWorkflows(selectedWorkflow.id);
      await loadWorkflow(selectedWorkflow.id);
      return true;
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "发布失败");
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const pollRunUntilTerminal = async (runId: number) => {
    const terminalStatuses = new Set(["completed", "failed", "cancelled"]);
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const response = await fetch(`${apiBaseUrl}/runs/${runId}`, { cache: "no-store" });
      const run = await response.json();
      if (!response.ok) {
        throw new Error(run.detail ?? `GET /runs/${runId} ${response.status}`);
      }
      setStatusLine(`异步运行 #${runId} · ${run.status}`);
      if (terminalStatuses.has(String(run.status))) {
        return run;
      }
      await new Promise((resolve) => {
        window.setTimeout(resolve, 1000);
      });
    }
    throw new Error(`异步运行 #${runId} 轮询超时`);
  };

  const runWorkflow = async () => {
    if (!selectedWorkflow) {
      return false;
    }

    const parsedInput = parseJsonObject(runInput);
    if (parsedInput.error) {
      setRunInputError(parsedInput.error);
      setStatusLine("测试输入不是合法 JSON 对象");
      return false;
    }

    setRunInputError(null);
    setBusyAction("run");
    try {
      const response = await fetch(`${apiBaseUrl}/workflows/${selectedWorkflow.id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input: parsedInput.value,
          trigger_type: "test",
          execution_mode: runMode,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `POST /run ${response.status}`);
      }
      if (runMode === "async") {
        setStatusLine(`异步运行已提交 #${result.run_id}，等待完成`);
        await pollRunUntilTerminal(result.run_id);
      }
      const traceResponse = await fetch(`${apiBaseUrl}/runs/${result.run_id}/trace`, {
        cache: "no-store",
      });
      if (!traceResponse.ok) {
        throw new Error(`GET /runs/${result.run_id}/trace ${traceResponse.status}`);
      }
      const nextTrace = (await traceResponse.json()) as RunTrace;
      setTrace(nextTrace);
      setStatusLine(`${runMode === "async" ? "异步" : "同步"}运行完成 #${result.run_id} · ${nextTrace.run.status}`);
      const firstFailedNode = nextTrace.nodes.find((node) => node.status === "failed");
      if (firstFailedNode) {
        focusNode(firstFailedNode.node_id);
      }
      const listResponse = await fetch(`${apiBaseUrl}/workflows`, { cache: "no-store" });
      if (listResponse.ok) {
        const data = await listResponse.json();
        setWorkflows(data.items as Workflow[]);
      }
      await loadRuns(selectedWorkflow.id);
      return true;
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "运行失败");
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const publishAndRunWorkflow = async () => {
    if (!selectedWorkflow) {
      return;
    }
    setStatusLine("准备发布并运行");
    const published = await publishWorkflow();
    if (published) {
      await runWorkflow();
    }
  };

  const addNode = useCallback(
    (type: NodeType) => {
      const template = nodeCatalog.find((item) => item.type === type);
      if (!template) {
        return;
      }

      const sameTypeCount = graph.nodes.filter((node) => node.type === type).length;
      const nextNode = createGraphNode(template, sameTypeCount + 1, graph.nodes.length);
      setGraph((currentGraph) => ({
        ...currentGraph,
        nodes: [...currentGraph.nodes, nextNode],
      }));
      setSelectedNodeId(nextNode.id);
      setTrace(null);
      setStatusLine(`已添加节点：${template.label}`);
    },
    [graph.nodes],
  );

  const applyKnowledgeDemoTemplate = useCallback(async () => {
    if (!selectedWorkflow) {
      return;
    }
    if (
      (graph.nodes.length > 0 || graph.edges.length > 0) &&
      !window.confirm("知识库示例会替换当前画布草稿，是否继续？")
    ) {
      setStatusLine("已取消套用知识库示例，当前草稿未改变");
      return;
    }

    let knowledgeBaseId = selectedKnowledgeBaseId ?? knowledgeBases[0]?.id ?? null;
    let loadError: string | null = null;
    if (!knowledgeBaseId) {
      setBusyAction("knowledge-template");
      try {
        const response = await fetch(`${apiBaseUrl}/knowledge-bases`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`GET /knowledge-bases ${response.status}`);
        }
        const data = await response.json();
        const items = data.items as KnowledgeBase[];
        setKnowledgeBases(items);
        knowledgeBaseId = items[0]?.id ?? null;
        setSelectedKnowledgeBaseId(knowledgeBaseId);
      } catch (error) {
        loadError = error instanceof Error ? error.message : "知识库同步失败";
      } finally {
        setBusyAction(null);
      }
    }

    const nextGraph = createKnowledgeDemoGraph(knowledgeBaseId);
    setGraph(nextGraph);
    setSelectedNodeId("kb_1");
    setRunInput(JSON.stringify({ user_query: "refund billing policy" }, null, 2));
    setValidation(null);
    setTrace(null);
    setStatusLine(
      loadError
        ? `${loadError}；已生成 Knowledge 示例草稿，请手动选择知识库`
        : knowledgeBaseId
          ? `已生成 Knowledge 示例草稿，默认使用知识库 #${knowledgeBaseId}`
          : "已生成 Knowledge 示例草稿，请在节点表单中选择知识库",
    );
  }, [graph.edges.length, graph.nodes.length, knowledgeBases, selectedKnowledgeBaseId, selectedWorkflow]);

  const applyIntentBranchDemoTemplate = useCallback(() => {
    if (!selectedWorkflow) {
      return;
    }
    if (
      (graph.nodes.length > 0 || graph.edges.length > 0) &&
      !window.confirm("意图分支示例会替换当前画布草稿，是否继续？")
    ) {
      setStatusLine("已取消套用意图分支示例，当前草稿未改变");
      return;
    }

    setGraph(createIntentBranchDemoGraph());
    setSelectedNodeId("branch_1");
    setRunInput(JSON.stringify({ user_query: "refund_request 用户申请退款" }, null, 2));
    setValidation(null);
    setTrace(null);
    setStatusLine("已生成 Intent + Branch 示例草稿");
  }, [graph.edges.length, graph.nodes.length, selectedWorkflow]);

  const applyApiMessageDemoTemplate = useCallback(() => {
    if (!selectedWorkflow) {
      return;
    }
    if (
      (graph.nodes.length > 0 || graph.edges.length > 0) &&
      !window.confirm("API 消息示例会替换当前画布草稿，是否继续？")
    ) {
      setStatusLine("已取消套用 API 消息示例，当前草稿未改变");
      return;
    }

    setGraph(createApiMessageDemoGraph());
    setSelectedNodeId("api_1");
    setRunInput(JSON.stringify({ user_query: "查询订单状态", order_id: "A-1001" }, null, 2));
    setValidation(null);
    setTrace(null);
    setStatusLine("已生成 API + Message 示例草稿");
  }, [graph.edges.length, graph.nodes.length, selectedWorkflow]);

  const updateSelectedNode = useCallback(
    (patch: Partial<GraphNode>) => {
      if (!selectedNodeId) {
        return;
      }
      setGraph((currentGraph) => ({
        ...currentGraph,
        nodes: currentGraph.nodes.map((node) => (node.id === selectedNodeId ? { ...node, ...patch } : node)),
      }));
      setTrace(null);
    },
    [selectedNodeId],
  );

  const updateSelectedNodeConfig = useCallback(
    (patch: JsonObject) => {
      if (!selectedNode) {
        return;
      }
      updateSelectedNode({ config: { ...selectedNode.config, ...patch } });
    },
    [selectedNode, updateSelectedNode],
  );

  const updateSelectedNodeJson = (field: JsonNodeField, value: string) => {
    setNodeJsonDrafts((drafts) => ({ ...drafts, [field]: value }));
    const parsed = parseJsonObject(value);
    setNodeJsonErrors((errors) => ({ ...errors, [field]: parsed.error ?? null }));
    if (!parsed.error) {
      updateSelectedNode({ [field]: parsed.value } as Pick<GraphNode, JsonNodeField>);
    }
  };

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const selectedChange = changes.find((change) => change.type === "select" && change.selected);
    if (selectedChange && nodeChangeHasId(selectedChange)) {
      setSelectedNodeId(selectedChange.id);
    }

    setFlowNodes((nodes) => {
      const nextNodes = applyNodeChanges(changes, nodes);
      const removedIds = new Set(
        changes
          .filter((change) => nodeChangeHasId(change) && change.type === "remove")
          .map((change) => change.id),
      );
      const flowNodeById = new Map(nextNodes.map((node) => [node.id, node]));

      setGraph((currentGraph) => ({
        ...currentGraph,
        nodes: currentGraph.nodes
          .filter((node) => !removedIds.has(node.id))
          .map((node) => {
            const flowNode = flowNodeById.get(node.id);
            return flowNode ? { ...node, position: flowNode.position } : node;
          }),
        edges: currentGraph.edges.filter(
          (edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target),
        ),
      }));

      if (removedIds.size > 0) {
        setTrace(null);
      }
      return nextNodes;
    });
  }, []);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setFlowEdges((edges) => {
      const nextEdges = applyEdgeChanges(changes, edges);
      setGraph((currentGraph) => ({
        ...currentGraph,
        edges: flowEdgesToGraphEdges(nextEdges),
      }));
      setTrace(null);
      return nextEdges;
    });
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) {
      return;
    }
    if (connection.source === connection.target) {
      setStatusLine("不能连接到自身节点");
      return;
    }

    setGraph((currentGraph) => {
      const exists = currentGraph.edges.some(
        (edge) => edge.source === connection.source && edge.target === connection.target,
      );
      if (exists) {
        setStatusLine("该连线已存在");
        return currentGraph;
      }

      const sourceNode = currentGraph.nodes.find((node) => node.id === connection.source);
      const nextEdge: GraphEdge = {
        id: makeEdgeId(connection.source, connection.target, currentGraph.edges.length),
        source: connection.source,
        target: connection.target,
        label: sourceNode?.type === "branch" ? "branch" : undefined,
      };
      return { ...currentGraph, edges: [...currentGraph.edges, nextEdge] };
    });
    setTrace(null);
  }, []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <section className="brand">
          <p className="eyebrow">Agent Flow</p>
          <h1>工作流控制台</h1>
        </section>

        <nav className="main-nav" aria-label="管理入口">
          {adminSections.map(({ id, label, Icon }) => (
            <button
              className={activeSection === id ? "nav-tab active" : "nav-tab"}
              key={id}
              onClick={() => setActiveSection(id)}
            >
              <Icon size={16} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        {activeSection === "workflow" ? (
          <section className="sidebar-actions">
          <button className="icon-button primary" onClick={createWorkflow} disabled={busyAction !== null}>
            <Plus size={16} />
            新建
          </button>
          <button
            className="icon-button"
            onClick={() => void loadWorkflows(selectedWorkflow?.id)}
            disabled={busyAction !== null}
          >
            <RefreshCw size={16} />
            刷新
          </button>
          <button
            className="icon-button"
            onClick={() => void applyKnowledgeDemoTemplate()}
            disabled={!selectedWorkflow || busyAction !== null}
          >
            <Database size={16} />
            知识库示例
          </button>
          <button
            className="icon-button"
            onClick={() => applyIntentBranchDemoTemplate()}
            disabled={!selectedWorkflow || busyAction !== null}
          >
            <GitBranch size={16} />
            意图分支
          </button>
          <button
            className="icon-button"
            onClick={() => applyApiMessageDemoTemplate()}
            disabled={!selectedWorkflow || busyAction !== null}
          >
            <MessageSquare size={16} />
            API 消息
          </button>
          </section>
        ) : null}

        {activeSection === "workflow" ? (
          <section className="node-library">
          <div className="section-heading">
            <Plus size={16} />
            节点库
          </div>
          {groupNodeCatalog(nodeCatalog).map(([group, items]) => (
            <div className="node-group" key={group}>
              <p>{group}</p>
              <div>
                {items.map(({ type, label, Icon }) => (
                  <button
                    className="node-add-button"
                    key={type}
                    onClick={() => addNode(type)}
                    disabled={!selectedWorkflow || busyAction !== null}
                  >
                    <Icon size={15} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
          </section>
        ) : null}

        {activeSection === "workflow" ? (
          <nav className="workflow-list">
          {workflows.map((workflow) => (
            <button
              className={workflow.id === selectedWorkflow?.id ? "workflow-item active" : "workflow-item"}
              key={workflow.id}
              onClick={() => void loadWorkflow(workflow.id)}
            >
              <span>{workflow.name}</span>
              <small>{workflow.status}</small>
            </button>
          ))}
          {workflows.length === 0 ? <p className="empty">暂无工作流</p> : null}
          </nav>
        ) : (
          <section className="admin-sidebar-note">
            <strong>{adminSections.find((section) => section.id === activeSection)?.label}</strong>
            <span>管理数据来自本地 API，表单提交后自动刷新。</span>
          </section>
        )}

        <section className="sidebar-footer">
          <span>{statusLine}</span>
        </section>
      </aside>

      <section className="workspace">
        {activeSection === "workflow" ? (
          <>
        <header className="topbar">
          <div className="title-block">
            <p className="eyebrow">Local MVP Runtime</p>
            <input
              className="title-input"
              value={nameDraft}
              onChange={(event) => setNameDraft(event.target.value)}
              placeholder="选择或新建工作流"
            />
            <input
              className="description-input"
              value={descriptionDraft}
              onChange={(event) => setDescriptionDraft(event.target.value)}
              placeholder="描述"
            />
          </div>
          <div className="toolbar">
            <a className="icon-button" href={`${apiBaseUrl}/health`}>
              <Activity size={16} />
              Health
            </a>
            <button className="icon-button" onClick={saveDraft} disabled={!selectedWorkflow || busyAction !== null}>
              <Save size={16} />
              保存
            </button>
            <button
              className="icon-button"
              onClick={validateDraft}
              disabled={!selectedWorkflow || busyAction !== null}
            >
              <CheckCircle2 size={16} />
              校验
            </button>
            <button
              className="icon-button"
              onClick={() => void publishWorkflow()}
              disabled={!selectedWorkflow || busyAction !== null}
            >
              <Rocket size={16} />
              发布
            </button>
            <button
              className="icon-button primary"
              onClick={() => void publishAndRunWorkflow()}
              disabled={!selectedWorkflow || busyAction !== null}
            >
              <Play size={16} />
              发布并运行
            </button>
          </div>
        </header>

        <section className="metric-strip">
          <div>
            <span>状态</span>
            <strong>{selectedWorkflow?.status ?? "未选择"}</strong>
          </div>
          <div>
            <span>版本</span>
            <strong>{selectedVersion}</strong>
          </div>
          <div>
            <span>节点</span>
            <strong>{nodeCount}</strong>
          </div>
          <div>
            <span>连线</span>
            <strong>{edgeCount}</strong>
          </div>
          <div>
            <span>运行</span>
            <strong>{runSummary}</strong>
          </div>
        </section>

        <VersionCodePanel workflow={selectedWorkflow} version={currentVersionDetail} />

        <section className="designer">
          <div className="canvas-flow">
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              onInit={setFlowInstance}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              onPaneClick={() => setSelectedNodeId(null)}
              deleteKeyCode={["Backspace", "Delete"]}
              fitView
            >
              <Background />
              <MiniMap pannable zoomable />
              <Controls />
            </ReactFlow>
          </div>

          <aside className="inspector">
            <section className="node-config-box">
              <div className="section-heading">
                <SquareTerminal size={16} />
                节点配置
              </div>
              {selectedNode ? (
                <div className="node-form">
                  <label>
                    <span>name</span>
                    <input
                      value={selectedNode.name}
                      onChange={(event) => updateSelectedNode({ name: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>type</span>
                    <select
                      value={selectedNode.type}
                      onChange={(event) => updateSelectedNode({ type: event.target.value as NodeType })}
                    >
                      {nodeCatalog.map((item) => (
                        <option key={item.type} value={item.type}>
                          {item.type}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={selectedNode.enabled ?? true}
                      onChange={(event) => updateSelectedNode({ enabled: event.target.checked })}
                    />
                    <span>enabled</span>
                  </label>
                  <StructuredNodeConfig
                    knowledgeBases={knowledgeBases}
                    modelConfigs={modelConfigs}
                    node={selectedNode}
                    onConfigChange={updateSelectedNodeConfig}
                    tools={tools}
                  />
                  {(["config", "input_mapping", "output_mapping"] as JsonNodeField[]).map((field) => (
                    <label key={field}>
                      <span>{nodeJsonFieldLabels[field]}</span>
                      <textarea
                        value={nodeJsonDrafts[field]}
                        onChange={(event) => updateSelectedNodeJson(field, event.target.value)}
                        spellCheck={false}
                      />
                      {nodeJsonErrors[field] ? <small className="error-text">{nodeJsonErrors[field]}</small> : null}
                    </label>
                  ))}
                </div>
              ) : (
                <p className="empty">选择画布节点后编辑配置</p>
              )}
            </section>

            <section className="run-box">
              <div className="run-box-header">
                <label htmlFor="run-input">测试输入 JSON</label>
                <div className="segmented-control" aria-label="运行模式">
                  {(["sync", "async"] as RunMode[]).map((mode) => (
                    <button
                      key={mode}
                      className={runMode === mode ? "active" : ""}
                      type="button"
                      onClick={() => setRunMode(mode)}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
              </div>
              <textarea
                id="run-input"
                value={runInput}
                onChange={(event) => {
                  setRunInput(event.target.value);
                  setRunInputError(null);
                }}
                spellCheck={false}
              />
              {runInputError ? <small className="error-text">{runInputError}</small> : null}
              <button
                className="icon-button primary"
                onClick={runWorkflow}
                disabled={!selectedWorkflow || selectedWorkflow.status !== "published" || busyAction !== null}
              >
                <Play size={16} />
                运行
              </button>
            </section>

            <section className="result-box">
              <div className="section-heading">
                <FileJson size={16} />
                校验结果
              </div>
              {validation ? <ValidationView validation={validation} onSelectNode={focusNode} /> : <p className="empty">等待校验</p>}
            </section>

            <section className="result-box">
              <div className="result-box-header">
                <div className="section-heading">
                  <Activity size={16} />
                  最近运行
                </div>
                <button
                  className="text-button"
                  onClick={() => {
                    if (selectedWorkflow) {
                      void loadRuns(selectedWorkflow.id).catch((error) => {
                        setStatusLine(error instanceof Error ? error.message : "运行历史同步失败");
                      });
                    }
                  }}
                  disabled={!selectedWorkflow || busyAction !== null}
                  type="button"
                >
                  刷新
                </button>
              </div>
              <RunHistoryView
                runs={runs}
                activeRunId={trace ? getRunId(trace.run) : null}
                busy={busyAction !== null}
                onLoadTrace={(runId) => void loadRunTrace(runId)}
              />
            </section>

            <section className="result-box">
              <div className="section-heading">
                <Activity size={16} />
                运行 Trace
              </div>
              {trace ? <TraceView trace={trace} onSelectNode={focusNode} /> : <p className="empty">等待运行</p>}
            </section>
          </aside>
        </section>
          </>
        ) : null}

        {activeSection === "knowledge" ? (
          <section className="admin-page">
            <AdminHeader
              eyebrow="Knowledge"
              title="知识库"
              description="管理检索节点可引用的知识库，并查看已上传 documents 的基础信息。"
              onRefresh={() => void loadKnowledge(selectedKnowledgeBaseId ?? undefined)}
              busy={busyAction !== null}
            />
            <section className="admin-grid">
              <form className="admin-form" onSubmit={createKnowledgeBase}>
                <div className="section-heading">
                  <BookOpen size={16} />
                  新建知识库
                </div>
                <label>
                  <span>name</span>
                  <input
                    required
                    value={knowledgeForm.name}
                    onChange={(event) => setKnowledgeForm((form) => ({ ...form, name: event.target.value }))}
                  />
                </label>
                <label>
                  <span>description</span>
                  <input
                    value={knowledgeForm.description}
                    onChange={(event) => setKnowledgeForm((form) => ({ ...form, description: event.target.value }))}
                  />
                </label>
                <label>
                  <span>embedding_model</span>
                  <input
                    required
                    value={knowledgeForm.embedding_model}
                    onChange={(event) =>
                      setKnowledgeForm((form) => ({ ...form, embedding_model: event.target.value }))
                    }
                  />
                </label>
                <button className="icon-button primary" disabled={busyAction !== null}>
                  <Plus size={16} />
                  创建
                </button>
              </form>

              <section className="admin-panel">
                <div className="section-heading">
                  <Database size={16} />
                  Knowledge Bases
                </div>
                <div className="admin-list">
                  {knowledgeBases.map((kb) => (
                    <button
                      className={kb.id === selectedKnowledgeBaseId ? "admin-item active" : "admin-item"}
                      key={kb.id}
                      onClick={() => void loadKnowledgeDocuments(kb.id)}
                    >
                      <span>{kb.name}</span>
                      <small>{kb.status}</small>
                      <em>{kb.embedding_model ?? "embedding"}</em>
                    </button>
                  ))}
                  {knowledgeBases.length === 0 ? <p className="empty">暂无知识库</p> : null}
                </div>
              </section>
            </section>

            <section className="admin-grid compact">
              <section className="admin-panel">
                <div className="section-heading">
                  <Upload size={16} />
                  上传 Document
                </div>
                <label className="file-upload">
                  <input
                    type="file"
                    onChange={uploadKnowledgeDocument}
                    disabled={!selectedKnowledgeBaseId || busyAction !== null}
                  />
                  <span>{selectedKnowledgeBaseId ? "选择文件并上传" : "先选择知识库"}</span>
                </label>
              </section>

              <form className="admin-form" onSubmit={retrieveKnowledge}>
                <div className="section-heading">
                  <Search size={16} />
                  Retrieve 测试
                </div>
                <label>
                  <span>query</span>
                  <textarea
                    required
                    value={retrieveForm.query}
                    onChange={(event) => setRetrieveForm((form) => ({ ...form, query: event.target.value }))}
                  />
                </label>
                <div className="inline-fields">
                  <label>
                    <span>top_k</span>
                    <input
                      min={1}
                      max={50}
                      type="number"
                      value={retrieveForm.top_k}
                      onChange={(event) => setRetrieveForm((form) => ({ ...form, top_k: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>score_threshold</span>
                    <input
                      max={1}
                      min={0}
                      step={0.05}
                      type="number"
                      value={retrieveForm.score_threshold}
                      onChange={(event) =>
                        setRetrieveForm((form) => ({ ...form, score_threshold: event.target.value }))
                      }
                    />
                  </label>
                </div>
                {retrieveError ? <small className="error-text">{retrieveError}</small> : null}
                <button className="icon-button primary" disabled={!selectedKnowledgeBaseId || busyAction !== null}>
                  <Search size={16} />
                  Retrieve
                </button>
              </form>
            </section>

            {retrieveResults.length > 0 ? (
              <section className="admin-panel">
                <div className="section-heading">
                  <FileJson size={16} />
                  Retrieved Chunks
                </div>
                <div className="chunk-list">
                  {retrieveResults.map((chunk, index) => (
                    <article
                      className="chunk-card"
                      key={`${chunk.chunk_id ?? chunk.id ?? chunk.source?.document_id ?? "chunk"}-${index}`}
                    >
                      <div>
                        <strong>#{chunk.chunk_id ?? chunk.id ?? index + 1}</strong>
                        <small>
                          doc {chunk.source?.document_id ?? chunk.document_id ?? "-"} ·{" "}
                          {chunk.source?.file_name ?? "source"} · chunk{" "}
                          {chunk.source?.chunk_index ?? chunk.chunk_index ?? "-"} · score{" "}
                          {typeof chunk.score === "number" ? chunk.score.toFixed(3) : "-"}
                        </small>
                      </div>
                      <p>{chunk.content ?? chunk.text ?? JSON.stringify(chunk)}</p>
                    </article>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="admin-panel">
              <div className="section-heading">
                <FileJson size={16} />
                Documents
              </div>
              {knowledgeDocuments.length > 0 ? (
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>File</th>
                        <th>Status</th>
                        <th>Size</th>
                        <th>Created</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {knowledgeDocuments.map((document) => (
                        <tr key={document.id}>
                          <td>#{document.id}</td>
                          <td>{document.file_name}</td>
                          <td>{document.status}</td>
                          <td>{formatBytes(document.file_size)}</td>
                          <td>{formatDate(document.created_at)}</td>
                          <td>
                            <div className="table-actions">
                              <button
                                className="icon-button"
                                onClick={() => void retryKnowledgeDocument(document.id)}
                                disabled={busyAction !== null}
                                type="button"
                              >
                                <RotateCcw size={16} />
                                Retry
                              </button>
                              <button
                                className="icon-button danger"
                                onClick={() => void deleteKnowledgeDocument(document.id)}
                                disabled={busyAction !== null}
                                type="button"
                              >
                                <Trash2 size={16} />
                                Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="empty">选择知识库后查看 documents</p>
              )}
            </section>
          </section>
        ) : null}

        {activeSection === "tools" ? (
          <section className="admin-page">
            <AdminHeader
              eyebrow="Tools"
              title="API Tools"
              description="创建 API tool，并通过 /tools/{id}/test 进行本地 mock 调用。"
              onRefresh={loadTools}
              busy={busyAction !== null}
            />
            <section className="admin-grid">
              <form className="admin-form" onSubmit={createTool}>
                <div className="section-heading">
                  <Wrench size={16} />
                  新建 API Tool
                </div>
                <label>
                  <span>name</span>
                  <input
                    required
                    value={toolForm.name}
                    onChange={(event) => setToolForm((form) => ({ ...form, name: event.target.value }))}
                  />
                </label>
                <label>
                  <span>description</span>
                  <input
                    value={toolForm.description}
                    onChange={(event) => setToolForm((form) => ({ ...form, description: event.target.value }))}
                  />
                </label>
                <label>
                  <span>config JSON</span>
                  <textarea
                    value={toolForm.config}
                    onChange={(event) => {
                      setToolForm((form) => ({ ...form, config: event.target.value }));
                      setToolConfigError(null);
                    }}
                    spellCheck={false}
                  />
                  {toolConfigError ? <small className="error-text">{toolConfigError}</small> : null}
                </label>
                <button className="icon-button primary" disabled={busyAction !== null}>
                  <Plus size={16} />
                  创建
                </button>
              </form>

              <section className="admin-panel">
                <div className="section-heading">
                  <SquareTerminal size={16} />
                  Tools
                </div>
                <div className="tool-list">
                  {tools.map((tool) => (
                    <article className="tool-card" key={tool.id}>
                      <div>
                        <strong>{tool.name}</strong>
                        <span>{tool.description || "无描述"}</span>
                        <small>
                          #{tool.id} · {tool.status}
                        </small>
                      </div>
                      <div className="edit-fields">
                        <label>
                          <span>name</span>
                          <input
                            required
                            value={toolDrafts[tool.id]?.name ?? tool.name}
                            onChange={(event) =>
                              setToolDrafts((drafts) => ({
                                ...drafts,
                                [tool.id]: {
                                  name: event.target.value,
                                  description: drafts[tool.id]?.description ?? tool.description ?? "",
                                  config: drafts[tool.id]?.config ?? stringifyJson(tool.config_json ?? {}),
                                  error: null,
                                },
                              }))
                            }
                          />
                        </label>
                        <label>
                          <span>description</span>
                          <input
                            value={toolDrafts[tool.id]?.description ?? tool.description ?? ""}
                            onChange={(event) =>
                              setToolDrafts((drafts) => ({
                                ...drafts,
                                [tool.id]: {
                                  name: drafts[tool.id]?.name ?? tool.name,
                                  description: event.target.value,
                                  config: drafts[tool.id]?.config ?? stringifyJson(tool.config_json ?? {}),
                                  error: null,
                                },
                              }))
                            }
                          />
                        </label>
                      </div>
                      <label className="stacked-field">
                        <span>config JSON</span>
                        <textarea
                          value={toolDrafts[tool.id]?.config ?? stringifyJson(tool.config_json ?? {})}
                          onChange={(event) =>
                            setToolDrafts((drafts) => ({
                              ...drafts,
                              [tool.id]: {
                                name: drafts[tool.id]?.name ?? tool.name,
                                description: drafts[tool.id]?.description ?? tool.description ?? "",
                                config: event.target.value,
                                error: null,
                              },
                            }))
                          }
                          spellCheck={false}
                        />
                      </label>
                      {toolDrafts[tool.id]?.error ? (
                        <small className="error-text">{toolDrafts[tool.id]?.error}</small>
                      ) : null}
                      <button
                        className="icon-button primary"
                        onClick={() => void updateTool(tool.id)}
                        disabled={busyAction !== null}
                        type="button"
                      >
                        <Save size={16} />
                        保存 Tool
                      </button>
                      <label className="stacked-field">
                        <span>test input JSON</span>
                      <textarea
                        value={toolTestInputs[tool.id] ?? "{}"}
                        onChange={(event) =>
                          setToolTestInputs((inputs) => ({ ...inputs, [tool.id]: event.target.value }))
                        }
                        spellCheck={false}
                      />
                      </label>
                      <button
                        className="icon-button"
                        onClick={() => void testTool(tool.id)}
                        disabled={busyAction !== null}
                      >
                        <Play size={16} />
                        Test
                      </button>
                      {toolTestResults[tool.id] ? <pre>{toolTestResults[tool.id]}</pre> : null}
                    </article>
                  ))}
                  {tools.length === 0 ? <p className="empty">暂无 API tool</p> : null}
                </div>
              </section>
            </section>
          </section>
        ) : null}

        {activeSection === "secrets" ? (
          <section className="admin-page">
            <AdminHeader
              eyebrow="Secrets"
              title="Secrets"
              description="创建和查看 secret 元数据；列表不会展示 value 或 encrypted_value。"
              onRefresh={loadSecrets}
              busy={busyAction !== null}
            />
            <section className="admin-grid">
              <form className="admin-form" onSubmit={createSecret}>
                <div className="section-heading">
                  <KeyRound size={16} />
                  新建 Secret
                </div>
                <label>
                  <span>secret_key</span>
                  <input
                    required
                    value={secretForm.secret_key}
                    onChange={(event) => setSecretForm((form) => ({ ...form, secret_key: event.target.value }))}
                  />
                </label>
                <label>
                  <span>display_name</span>
                  <input
                    value={secretForm.display_name}
                    onChange={(event) => setSecretForm((form) => ({ ...form, display_name: event.target.value }))}
                  />
                </label>
                <label>
                  <span>value</span>
                  <input
                    required
                    type="password"
                    value={secretForm.value}
                    onChange={(event) => setSecretForm((form) => ({ ...form, value: event.target.value }))}
                  />
                </label>
                <button className="icon-button primary" disabled={busyAction !== null}>
                  <Plus size={16} />
                  创建
                </button>
              </form>

              <section className="admin-panel">
                <div className="section-heading">
                  <EyeOff size={16} />
                  Secret Metadata
                </div>
                {secrets.length > 0 ? (
                  <div className="secret-list">
                    {secrets.map((secret) => (
                      <article className="secret-card" key={secret.id}>
                        <div>
                          <strong>{secret.secret_key}</strong>
                          <small>
                            #{secret.id} · {secret.status} · v{secret.key_version} · {formatDate(secret.updated_at)}
                          </small>
                        </div>
                        <div className="edit-fields">
                          <label>
                            <span>display_name</span>
                            <input
                              value={secretDrafts[secret.id]?.display_name ?? secret.display_name ?? ""}
                              onChange={(event) =>
                                setSecretDrafts((drafts) => ({
                                  ...drafts,
                                  [secret.id]: {
                                    display_name: event.target.value,
                                    value: drafts[secret.id]?.value ?? "",
                                  },
                                }))
                              }
                            />
                          </label>
                          <label>
                            <span>new value</span>
                            <input
                              type="password"
                              value={secretDrafts[secret.id]?.value ?? ""}
                              onChange={(event) =>
                                setSecretDrafts((drafts) => ({
                                  ...drafts,
                                  [secret.id]: {
                                    display_name: drafts[secret.id]?.display_name ?? secret.display_name ?? "",
                                    value: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                        </div>
                        <button
                          className="icon-button primary"
                          onClick={() => void updateSecret(secret.id)}
                          disabled={busyAction !== null}
                          type="button"
                        >
                          <Save size={16} />
                          更新 Secret
                        </button>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="empty">暂无 secret</p>
                )}
              </section>
            </section>
          </section>
        ) : null}

        {activeSection === "models" ? (
          <section className="admin-page">
            <AdminHeader
              eyebrow="Models"
              title="Model Providers & Configs"
              description="查看模型 provider 以及关联 model config。"
              onRefresh={loadModels}
              busy={busyAction !== null}
            />
            <section className="model-grid">
              {modelProviders.map((provider) => (
                <article className="model-provider-card" key={provider.id}>
                  <div>
                    <strong>{provider.name}</strong>
                    <span>{provider.provider_type}</span>
                    <small>{provider.base_url || "no base_url"}</small>
                  </div>
                  <DataTable
                    emptyText="暂无 configs"
                    rows={modelConfigs
                      .filter((config) => config.provider_id === provider.id)
                      .map((config) => [
                        config.model_name,
                        config.model_type,
                        config.display_name ?? "-",
                        String(config.context_window ?? "-"),
                        config.status,
                      ])}
                    headers={["Model", "Type", "Display", "Context", "Status"]}
                  />
                </article>
              ))}
              {modelProviders.length === 0 ? <p className="empty">暂无 model provider</p> : null}
            </section>
          </section>
        ) : null}
      </section>
    </main>
  );
}

function AdminHeader({
  eyebrow,
  title,
  description,
  onRefresh,
  busy,
}: {
  eyebrow: string;
  title: string;
  description: string;
  onRefresh: () => void;
  busy: boolean;
}) {
  return (
    <header className="admin-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <button className="icon-button" onClick={onRefresh} disabled={busy}>
        <RefreshCw size={16} />
        刷新
      </button>
    </header>
  );
}

function DataTable({
  headers,
  rows,
  emptyText,
}: {
  headers: string[];
  rows: string[][];
  emptyText: string;
}) {
  if (rows.length === 0) {
    return <p className="empty">{emptyText}</p>;
  }

  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${row[0]}-${rowIndex}`}>
              {row.map((cell, cellIndex) => (
                <td key={`${cell}-${cellIndex}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ValidationView({
  validation,
  onSelectNode,
}: {
  validation: ValidationResult;
  onSelectNode: (nodeId: string) => void;
}) {
  const issues = [...validation.errors, ...validation.warnings];
  if (issues.length === 0) {
    return <p className="success-text">valid</p>;
  }
  return (
    <ul className="issue-list">
      {issues.map((issue) => (
        <li key={`${issue.code}-${issue.path}`}>
          <strong>{issue.code}</strong>
          <span>{issue.message}</span>
          <small>{issue.path}</small>
          {issue.node_id ? (
            <button className="text-button" onClick={() => onSelectNode(issue.node_id as string)}>
              定位节点
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function VersionCodePanel({
  workflow,
  version,
}: {
  workflow: Workflow | null;
  version: WorkflowVersion | null;
}) {
  if (!workflow) {
    return (
      <section className="version-code-panel">
        <div>
          <span>版本代码</span>
          <strong>未选择工作流</strong>
        </div>
      </section>
    );
  }
  if (!workflow.current_version_id) {
    return (
      <section className="version-code-panel">
        <div>
          <span>版本代码</span>
          <strong>当前工作流尚未发布</strong>
        </div>
      </section>
    );
  }

  return (
    <section className="version-code-panel">
      <div>
        <span>版本</span>
        <strong>v{version?.version ?? workflow.current_version ?? workflow.current_version_id}</strong>
      </div>
      <div>
        <span>code_path</span>
        <code>{version ? (version.code_path ?? "未生成") : "版本详情未加载"}</code>
      </div>
      <div>
        <span>code_hash</span>
        <code>{version ? (version.code_hash ?? "未生成") : "版本详情未加载"}</code>
      </div>
      <div>
        <span>generated_at</span>
        <strong>{formatDate(version?.code_generated_at)}</strong>
      </div>
    </section>
  );
}

function RunHistoryView({
  runs,
  activeRunId,
  busy,
  onLoadTrace,
}: {
  runs: RunListItem[];
  activeRunId: number | null;
  busy: boolean;
  onLoadTrace: (runId: number) => void;
}) {
  if (runs.length === 0) {
    return <p className="empty">暂无运行记录</p>;
  }

  return (
    <div className="run-history">
      {runs.map((run) => {
        const runId = getRunId(run);
        if (runId === null) {
          return null;
        }
        return (
          <button
            key={runId}
            className={`run-history-item${activeRunId === runId ? " active" : ""}`}
            disabled={busy}
            onClick={() => onLoadTrace(runId)}
            type="button"
          >
            <span>#{runId}</span>
            <strong>{run.status}</strong>
            <small>{formatDate(run.created_at)}</small>
          </button>
        );
      })}
    </div>
  );
}

function TraceView({ trace, onSelectNode }: { trace: RunTrace; onSelectNode: (nodeId: string) => void }) {
  const output = trace.run.output_json ? JSON.stringify(trace.run.output_json, null, 2) : "{}";
  const metadata = trace.run.metadata_json ?? {};
  return (
    <div className="trace">
      <section className="trace-code-metadata">
        <div>
          <span>code_path_at_run</span>
          <code>{metadataText(metadata.code_path_at_run)}</code>
        </div>
        <div>
          <span>code_hash_at_run</span>
          <code>{metadataText(metadata.code_hash_at_run)}</code>
        </div>
        <div>
          <span>code_modified</span>
          <strong className={metadata.code_modified === true ? "warning-text" : "success-text"}>
            {metadata.code_modified === true ? "true" : metadata.code_modified === false ? "false" : "unknown"}
          </strong>
        </div>
        {trace.run.error_code ? (
          <div>
            <span>error</span>
            <code>{trace.run.error_message ? `${trace.run.error_code}: ${trace.run.error_message}` : trace.run.error_code}</code>
          </div>
        ) : null}
      </section>
      <pre>{output}</pre>
      <ol>
        {trace.nodes.map((node) => (
          <li key={node.id}>
            <details className={`trace-node trace-${normalizeStatus(node.status)}`}>
              <summary>
                <strong>{node.node_name ?? node.node_id}</strong>
                <span>{node.status}</span>
                <small>{node.duration_ms ?? 0}ms</small>
                <button
                  className="text-button"
                  onClick={(event) => {
                    event.preventDefault();
                    onSelectNode(node.node_id);
                  }}
                  type="button"
                >
                  定位
                </button>
              </summary>
              <div className="trace-node-payload">
                <label>
                  <span>input</span>
                  <pre>{jsonText(node.input_json ?? {})}</pre>
                </label>
                <label>
                  <span>output</span>
                  <pre>{jsonText(node.output_json ?? {})}</pre>
                </label>
                {node.metadata_json ? (
                  <label>
                    <span>metadata</span>
                    <pre>{jsonText(node.metadata_json)}</pre>
                  </label>
                ) : null}
                {node.error_code || node.error_message ? (
                  <label>
                    <span>error</span>
                    <pre>{jsonText({ code: node.error_code, message: node.error_message })}</pre>
                  </label>
                ) : null}
              </div>
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}

function StructuredNodeConfig({
  node,
  knowledgeBases,
  modelConfigs,
  tools,
  onConfigChange,
}: {
  node: GraphNode;
  knowledgeBases: KnowledgeBase[];
  modelConfigs: ModelConfig[];
  tools: ApiTool[];
  onConfigChange: (patch: JsonObject) => void;
}) {
  const config = node.config ?? {};
  const chatModels = modelConfigs.filter((configItem) => configItem.model_type === "chat");

  if (node.type === "knowledge_base") {
    const selectedKnowledgeBaseId = Array.isArray(config.knowledge_base_ids)
      ? String(config.knowledge_base_ids[0] ?? "")
      : String(config.knowledge_base_id ?? "");
    return (
      <section className="structured-node-config">
        <div className="node-subheading">
          <Database size={14} />
          Knowledge 配置
        </div>
        <label>
          <span>knowledge_base</span>
          <select
            value={selectedKnowledgeBaseId}
            onChange={(event) => {
              const nextId = Number(event.target.value);
              onConfigChange({ knowledge_base_ids: Number.isFinite(nextId) && nextId > 0 ? [nextId] : [] });
            }}
          >
            <option value="">选择知识库</option>
            {knowledgeBases.map((knowledgeBase) => (
              <option key={knowledgeBase.id} value={knowledgeBase.id}>
                {knowledgeBase.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>query template</span>
          <input
            value={configString(config, "query", "{{input.user_query}}")}
            onChange={(event) => onConfigChange({ query: event.target.value })}
          />
        </label>
        <div className="inline-fields">
          <label>
            <span>top_k</span>
            <input
              min={1}
              max={50}
              type="number"
              value={configNumber(config, "top_k", 5)}
              onChange={(event) => onConfigChange({ top_k: Number(event.target.value) })}
            />
          </label>
          <label>
            <span>score_threshold</span>
            <input
              max={1}
              min={0}
              step={0.05}
              type="number"
              value={configNumber(config, "score_threshold", 0)}
              onChange={(event) => onConfigChange({ score_threshold: Number(event.target.value) })}
            />
          </label>
        </div>
      </section>
    );
  }

  if (node.type === "llm") {
    const provider = configString(config, "provider", "mock");
    const model = configString(config, "model", provider === "mock" ? "local-mock" : "gpt-4.1-mini");
    return (
      <section className="structured-node-config">
        <div className="node-subheading">
          <Bot size={14} />
          LLM 配置
        </div>
        <div className="inline-fields">
          <label>
            <span>provider</span>
            <select value={provider} onChange={(event) => onConfigChange({ provider: event.target.value })}>
              <option value="mock">mock</option>
              <option value="openai">openai</option>
            </select>
          </label>
          <label>
            <span>model</span>
            <select value={model} onChange={(event) => onConfigChange({ model: event.target.value })}>
              <option value={model}>{model}</option>
              {chatModels
                .filter((modelConfig) => modelConfig.model_name !== model)
                .map((modelConfig) => (
                  <option key={modelConfig.id} value={modelConfig.model_name}>
                    {modelConfig.display_name ?? modelConfig.model_name}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <label>
          <span>system_prompt</span>
          <textarea
            value={configString(config, "system_prompt", "")}
            onChange={(event) => onConfigChange({ system_prompt: event.target.value })}
          />
        </label>
        <label>
          <span>user_prompt</span>
          <textarea
            value={configString(config, "user_prompt", "问题：{{input.user_query}}")}
            onChange={(event) => onConfigChange({ user_prompt: event.target.value })}
          />
        </label>
        <label>
          <span>temperature</span>
          <input
            max={2}
            min={0}
            step={0.1}
            type="number"
            value={configNumber(config, "temperature", 0.2)}
            onChange={(event) => onConfigChange({ temperature: Number(event.target.value) })}
          />
        </label>
      </section>
    );
  }

  if (node.type === "api") {
    const selectedToolId = String(config.tool_id ?? "");
    return (
      <section className="structured-node-config">
        <div className="node-subheading">
          <Wrench size={14} />
          API 配置
        </div>
        <label>
          <span>tool preset</span>
          <select
            value={selectedToolId}
            onChange={(event) => {
              const toolId = Number(event.target.value);
              const tool = tools.find((item) => item.id === toolId);
              const toolConfig = isPlainObject(tool?.config_json) ? tool.config_json : {};
              onConfigChange({ ...toolConfig, tool_id: Number.isFinite(toolId) && toolId > 0 ? toolId : null });
            }}
          >
            <option value="">不使用 preset</option>
            {tools.map((tool) => (
              <option key={tool.id} value={tool.id}>
                {tool.name}
              </option>
            ))}
          </select>
        </label>
        <div className="inline-fields">
          <label>
            <span>mode</span>
            <select
              value={configString(config, "mode", "mock")}
              onChange={(event) => onConfigChange({ mode: event.target.value })}
            >
              <option value="mock">mock</option>
              <option value="http">http</option>
            </select>
          </label>
          <label>
            <span>method</span>
            <select
              value={configString(config, "method", "GET")}
              onChange={(event) => onConfigChange({ method: event.target.value })}
            >
              {["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => (
                <option key={method} value={method}>
                  {method}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          <span>url</span>
          <input
            value={configString(config, "url", "")}
            onChange={(event) => onConfigChange({ url: event.target.value })}
          />
        </label>
        <label>
          <span>timeout_seconds</span>
          <input
            min={1}
            max={120}
            type="number"
            value={configNumber(config, "timeout_seconds", configNumber(config, "timeout", 30))}
            onChange={(event) => onConfigChange({ timeout_seconds: Number(event.target.value) })}
          />
        </label>
      </section>
    );
  }

  return null;
}

function graphToFlowNodes(
  graph: WorkflowGraph,
  selectedNodeId: string | null,
  statusByNodeId: Map<string, string>,
  currentNodes: Node[],
): Node[] {
  return graph.nodes.map((node) => {
    const currentNode = currentNodes.find((item) => item.id === node.id);
    const status = statusByNodeId.get(node.id);
    return {
      id: node.id,
      position: node.position,
      data: {
        label: (
          <div className="node-card">
            <span>{node.name}</span>
            <small>{node.type}</small>
          </div>
        ),
        nodeType: node.type,
      },
      className: getFlowNodeClassName(node, status),
      selected: node.id === selectedNodeId,
      dragging: currentNode?.dragging,
    };
  });
}

function graphToFlowEdges(graph: WorkflowGraph, currentEdges: Edge[]): Edge[] {
  return graph.edges.map((edge) => {
    const currentEdge = currentEdges.find((item) => item.id === edge.id);
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      selected: currentEdge?.selected,
      animated: false,
    };
  });
}

function flowEdgesToGraphEdges(edges: Edge[]): GraphEdge[] {
  return edges
    .filter((edge) => edge.source && edge.target)
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: typeof edge.label === "string" ? edge.label : undefined,
    }));
}

function createKnowledgeDemoGraph(knowledgeBaseId: number | null): WorkflowGraph {
  const knowledgeBaseIds = knowledgeBaseId ? [knowledgeBaseId] : [];
  return {
    schema_version: "1.0",
    nodes: [
      {
        id: "start_1",
        type: "start",
        name: "开始",
        position: { x: 80, y: 160 },
        config: {},
      },
      {
        id: "input_1",
        type: "input",
        name: "用户输入",
        position: { x: 280, y: 160 },
        config: {
          fields: [{ name: "user_query", type: "string", label: "用户问题", required: true }],
        },
        output_mapping: { user_query: "variables.user_query" },
      },
      {
        id: "kb_1",
        type: "knowledge_base",
        name: "检索知识库",
        position: { x: 500, y: 160 },
        config: {
          knowledge_base_ids: knowledgeBaseIds,
          query: "{{question}}",
          retrieval_mode: "vector",
          top_k: 3,
          score_threshold: 0,
        },
        input_mapping: { question: "{{input.user_query}}" },
        output_mapping: { chunks: "variables.kb_context" },
      },
      {
        id: "output_1",
        type: "output",
        name: "最终输出",
        position: { x: 720, y: 160 },
        config: {
          outputs: {
            query: "{{input.user_query}}",
            chunks: "{{variables.kb_context}}",
          },
        },
      },
      {
        id: "end_1",
        type: "end",
        name: "结束",
        position: { x: 920, y: 160 },
        config: {},
      },
    ],
    edges: [
      { id: "e1", source: "start_1", target: "input_1" },
      { id: "e2", source: "input_1", target: "kb_1" },
      { id: "e3", source: "kb_1", target: "output_1" },
      { id: "e4", source: "output_1", target: "end_1" },
    ],
  };
}

function createIntentBranchDemoGraph(): WorkflowGraph {
  return {
    schema_version: "1.0",
    nodes: [
      {
        id: "start_1",
        type: "start",
        name: "开始",
        position: { x: 80, y: 190 },
        config: {},
      },
      {
        id: "input_1",
        type: "input",
        name: "用户输入",
        position: { x: 280, y: 190 },
        config: {
          fields: [{ name: "user_query", type: "string", label: "用户问题", required: true }],
        },
        output_mapping: { user_query: "variables.user_query" },
      },
      {
        id: "intent_1",
        type: "intent",
        name: "识别意图",
        position: { x: 500, y: 190 },
        config: {
          provider: "keyword",
          intents: [
            { name: "refund_request", description: "refund 退款 用户申请退款" },
            { name: "general_question", description: "general 普通咨询" },
          ],
          fallback_intent: "general_question",
        },
        input_mapping: { text: "{{input.user_query}}" },
        output_mapping: {
          intent: "variables.intent_result.intent",
          confidence: "variables.intent_result.confidence",
        },
      },
      {
        id: "branch_1",
        type: "branch",
        name: "按意图分支",
        position: { x: 720, y: 190 },
        config: {
          branches: [
            {
              id: "refund",
              label: "退款",
              target: "refund_message_1",
              condition: {
                left: "{{variables.intent_result.intent}}",
                operator: "eq",
                value: "refund_request",
              },
            },
            {
              id: "general",
              label: "普通咨询",
              target: "general_message_1",
              condition: {
                left: "{{variables.intent_result.intent}}",
                operator: "eq",
                value: "general_question",
              },
            },
          ],
          default_target: "general_message_1",
        },
      },
      {
        id: "refund_message_1",
        type: "message",
        name: "退款回复",
        position: { x: 960, y: 90 },
        config: {
          message_type: "text",
          template: "已识别为退款诉求，意图：{{variables.intent_result.intent}}",
        },
        output_mapping: { message: "messages" },
      },
      {
        id: "general_message_1",
        type: "message",
        name: "普通咨询回复",
        position: { x: 960, y: 290 },
        config: {
          message_type: "text",
          template: "已进入普通咨询路径，意图：{{variables.intent_result.intent}}",
        },
        output_mapping: { message: "messages" },
      },
      {
        id: "refund_output_1",
        type: "output",
        name: "退款输出",
        position: { x: 1180, y: 90 },
        config: {
          outputs: {
            route: "refund",
            intent: "{{variables.intent_result.intent}}",
            confidence: "{{variables.intent_result.confidence}}",
            message: "{{outputs.refund_message_1.message}}",
            messages: "{{messages}}",
          },
        },
      },
      {
        id: "general_output_1",
        type: "output",
        name: "普通输出",
        position: { x: 1180, y: 290 },
        config: {
          outputs: {
            route: "general",
            intent: "{{variables.intent_result.intent}}",
            confidence: "{{variables.intent_result.confidence}}",
            message: "{{outputs.general_message_1.message}}",
            messages: "{{messages}}",
          },
        },
      },
      {
        id: "end_1",
        type: "end",
        name: "结束",
        position: { x: 1400, y: 190 },
        config: {},
      },
    ],
    edges: [
      { id: "e1", source: "start_1", target: "input_1" },
      { id: "e2", source: "input_1", target: "intent_1" },
      { id: "e3", source: "intent_1", target: "branch_1" },
      { id: "e4", source: "branch_1", target: "refund_message_1", label: "refund" },
      { id: "e5", source: "branch_1", target: "general_message_1", label: "general" },
      { id: "e6", source: "refund_message_1", target: "refund_output_1" },
      { id: "e7", source: "general_message_1", target: "general_output_1" },
      { id: "e8", source: "refund_output_1", target: "end_1" },
      { id: "e9", source: "general_output_1", target: "end_1" },
    ],
  };
}

function createApiMessageDemoGraph(): WorkflowGraph {
  return {
    schema_version: "1.0",
    nodes: [
      {
        id: "start_1",
        type: "start",
        name: "开始",
        position: { x: 80, y: 160 },
        config: {},
      },
      {
        id: "input_1",
        type: "input",
        name: "订单输入",
        position: { x: 280, y: 160 },
        config: {
          fields: [
            { name: "user_query", type: "string", label: "用户问题", required: true },
            { name: "order_id", type: "string", label: "订单号", required: true },
          ],
        },
        output_mapping: {
          user_query: "variables.user_query",
          order_id: "variables.order_id",
        },
      },
      {
        id: "api_1",
        type: "api",
        name: "查询订单 API",
        position: { x: 500, y: 160 },
        config: {
          mode: "mock",
          method: "POST",
          url: "https://orders.example.test/lookup",
          headers: {
            Authorization: "{{secrets.demo_api_key}}",
            "X-Order-ID": "{{input.order_id}}",
          },
          body: {
            order_id: "{{input.order_id}}",
            query: "{{input.user_query}}",
          },
          mock_status_code: 200,
          mock_response: {
            order_id: "A-1001",
            order_status: "paid",
            next_step: "send_message",
          },
        },
        output_mapping: { response: "variables.api_response" },
      },
      {
        id: "message_1",
        type: "message",
        name: "生成消息",
        position: { x: 720, y: 160 },
        config: {
          message_type: "text",
          template: "订单 {{variables.api_response.order_id}} 当前状态：{{variables.api_response.order_status}}",
        },
        output_mapping: { message: "messages" },
      },
      {
        id: "output_1",
        type: "output",
        name: "最终输出",
        position: { x: 940, y: 160 },
        config: {
          outputs: {
            api_response: "{{variables.api_response}}",
            message: "{{outputs.message_1.message}}",
            messages: "{{messages}}",
          },
        },
      },
      {
        id: "end_1",
        type: "end",
        name: "结束",
        position: { x: 1160, y: 160 },
        config: {},
      },
    ],
    edges: [
      { id: "e1", source: "start_1", target: "input_1" },
      { id: "e2", source: "input_1", target: "api_1" },
      { id: "e3", source: "api_1", target: "message_1" },
      { id: "e4", source: "message_1", target: "output_1" },
      { id: "e5", source: "output_1", target: "end_1" },
    ],
  };
}

function createGraphNode(template: NodeCatalogItem, index: number, nodeCount: number): GraphNode {
  const idSuffix = `${index}_${Date.now().toString(36)}`;
  return {
    id: `${template.type}_${idSuffix}`,
    type: template.type,
    name: template.label,
    position: {
      x: 120 + (nodeCount % 4) * 210,
      y: 120 + Math.floor(nodeCount / 4) * 130,
    },
    config: cloneJsonObject(template.config),
    input_mapping: cloneJsonObject(template.input_mapping ?? {}),
    output_mapping: cloneJsonObject(template.output_mapping ?? {}),
    enabled: true,
  };
}

function cloneJsonObject(value: JsonObject): JsonObject {
  return JSON.parse(JSON.stringify(value)) as JsonObject;
}

function groupNodeCatalog(items: NodeCatalogItem[]): Array<[string, NodeCatalogItem[]]> {
  const groups = new Map<string, NodeCatalogItem[]>();
  items.forEach((item) => {
    groups.set(item.group, [...(groups.get(item.group) ?? []), item]);
  });
  return Array.from(groups.entries());
}

function parseJsonObject(rawValue: string): { value?: JsonObject; error?: string } {
  const value = rawValue.trim();
  if (!value) {
    return { value: {} };
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!isPlainObject(parsed)) {
      return { error: "必须是 JSON 对象，例如 {\"user_query\":\"...\"}" };
    }
    return { value: parsed };
  } catch (error) {
    return { error: error instanceof Error ? error.message : "JSON 解析失败" };
  }
}

function isPlainObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringifyJson(value: JsonObject): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function configString(config: JsonObject, key: string, fallback: string): string {
  const value = config[key];
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

function configNumber(config: JsonObject, key: string, fallback: number): number {
  const value = config[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

function makeEdgeId(source: string, target: string, index: number): string {
  return `edge_${source}_${target}_${index + 1}_${Date.now().toString(36)}`;
}

function getFlowNodeClassName(node: GraphNode, status?: string): string {
  return [
    "flow-node",
    `node-${node.type}`,
    node.enabled === false ? "node-disabled" : null,
    status ? `status-${normalizeStatus(status)}` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

function normalizeStatus(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "completed") {
    return "success";
  }
  return normalized;
}

function nodeChangeHasId(change: NodeChange): change is NodeChange & { id: string } {
  return "id" in change;
}

function formatBytes(value?: number | null): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function getRunId(run: { id?: number; run_id?: number }): number | null {
  return run.run_id ?? run.id ?? null;
}

function metadataText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}
