"use client";

import {
  Activity,
  Ban,
  BookOpen,
  Bot,
  CheckCircle2,
  Database,
  EyeOff,
  FileJson,
  GitBranch,
  KeyRound,
  MessageSquare,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Rocket,
  Save,
  Search,
  SquareTerminal,
  Trash2,
  Upload,
  UserCheck,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  type ChangeEvent,
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  adminSections,
  apiBaseUrl,
  defaultKnowledgeForm,
  defaultRunInput,
  emptyFlowEdges,
  emptyGraph,
  nodeCatalog,
  nodeDropMoveThreshold,
} from "./workflow-editor/constants";
import {
  createApiMessageDemoGraph,
  createDeepSeekQaDemoGraph,
  createIntentBranchDemoGraph,
  createKnowledgeDemoGraph,
} from "./workflow-editor/demo-graphs";
import { NodeDragPreviewLayer } from "./workflow-editor/components/node-drag-preview-layer";
import {
  AdminHeader,
  NodeConfigPanel,
  RunHistoryView,
  TraceView,
  ValidationView,
  VersionCodePanel,
} from "./workflow-editor/components/panels";
import { WorkflowEdgeOverlay } from "./workflow-editor/components/workflow-edge-overlay";
import { workflowNodeTypes } from "./workflow-editor/components/workflow-node-view";
import type {
  ActiveSection,
  ApiTool,
  GeneratedWorkflowCleanupReport,
  GraphEdge,
  GraphNode,
  HumanApprovalTask,
  HumanApprovalTaskStatus,
  InspectorTab,
  JsonNodeField,
  JsonObject,
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeDocument,
  ModelConfig,
  ModelConfigDraft,
  ModelDefaults,
  ModelProvider,
  ModelProviderDraft,
  NodeDragPreview,
  NodeEdgeAnchors,
  NodeType,
  OpsDeadJob,
  OpsFailedRun,
  OpsQueue,
  OpsWorker,
  PendingConnection,
  RunListItem,
  RunMode,
  RunTrace,
  Secret,
  SecretDraft,
  ToolDraft,
  ValidationResult,
  Workflow,
  WorkflowGraph,
  WorkflowVersion,
  WorkflowVersionCode,
} from "./workflow-editor/types";
import {
  areNodeEdgeAnchorsEqual,
  createGraphNode,
  fetchWithTimeout,
  findFlowNodeIdAtClientPoint,
  formatBytes,
  formatCodeStatus,
  formatDate,
  formatRuntimeError,
  getConnectionError,
  getDefaultNextNodeType,
  getNodeEdgePoint,
  getRunId,
  graphToFlowNodes,
  groupNodeCatalog,
  isClientPointInsideElement,
  makeEdgeId,
  nodeChangeHasId,
  parseJsonObject,
  shortHash,
  stringifyJson,
} from "./workflow-editor/utils";

const extractItems = <T,>(data: unknown, keys: string[]): T[] => {
  if (Array.isArray(data)) {
    return data as T[];
  }
  if (!data || typeof data !== "object") {
    return [];
  }
  const record = data as Record<string, unknown>;
  for (const key of keys) {
    if (Array.isArray(record[key])) {
      return record[key] as T[];
    }
  }
  return [];
};

const extractNumber = (data: unknown, keys: string[]): number | null => {
  if (!data || typeof data !== "object") {
    return null;
  }
  const record = data as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number") {
      return value;
    }
  }
  return null;
};

const readText = (record: JsonObject, keys: string[], fallback = "-") => {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" || typeof value === "number") {
      return String(value);
    }
  }
  return fallback;
};

const readNumber = (record: JsonObject, keys: string[]) => {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number") {
      return value;
    }
  }
  return 0;
};

const readApiErrorMessage = (data: unknown, fallback: string) => {
  if (!data || typeof data !== "object") {
    return fallback;
  }
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const record = detail as { code?: unknown; message?: unknown };
    if (typeof record.code === "string") {
      return formatRuntimeError(record.code, typeof record.message === "string" ? record.message : null);
    }
    if (typeof record.message === "string") {
      return record.message;
    }
  }
  return fallback;
};

const modelProviderDiagnosticLabel = (status?: string | null) => {
  if (status === "ready") {
    return "可用";
  }
  if (status === "missing_api_key") {
    return "缺少 API Key";
  }
  if (status === "disabled") {
    return "已禁用";
  }
  if (status === "not_required") {
    return "无需密钥";
  }
  return "未知";
};

const modelProviderKeySourceLabel = (source?: string | null) => {
  if (source === "env") {
    return "环境变量";
  }
  if (source === "secret") {
    return "平台 Secret";
  }
  if (source === "not_required") {
    return "无需密钥";
  }
  return "未配置";
};

const approvalStatusOptions: Array<HumanApprovalTaskStatus | "all"> = [
  "pending",
  "approved",
  "rejected",
  "cancelled",
  "expired",
  "all",
];

const approvalStatusLabels: Record<HumanApprovalTaskStatus | "all", string> = {
  pending: "待处理",
  approved: "已同意",
  rejected: "已拒绝",
  cancelled: "已取消",
  expired: "已过期",
  all: "全部",
};

const defaultFinalOutputReference = (sourceNode: GraphNode) => {
  if (sourceNode.type === "llm") {
    return `{{outputs.${sourceNode.id}.output}}`;
  }
  if (sourceNode.type === "message") {
    return `{{outputs.${sourceNode.id}.message}}`;
  }
  if (sourceNode.type === "api") {
    return `{{outputs.${sourceNode.id}.response}}`;
  }
  if (sourceNode.type === "knowledge_base") {
    return `{{outputs.${sourceNode.id}.chunks}}`;
  }
  if (sourceNode.type === "intent") {
    return `{{outputs.${sourceNode.id}.intent}}`;
  }
  if (sourceNode.type === "start") {
    return `{{outputs.${sourceNode.id}.rawQuery}}`;
  }
  return `{{outputs.${sourceNode.id}.output}}`;
};

export default function Home() {
  const [activeSection, setActiveSection] = useState<ActiveSection>("workflow");
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(null);
  const [currentVersionDetail, setCurrentVersionDetail] = useState<WorkflowVersion | null>(null);
  const [workflowVersions, setWorkflowVersions] = useState<WorkflowVersion[]>([]);
  const [currentVersionCode, setCurrentVersionCode] = useState<WorkflowVersionCode | null>(null);
  const [selectedCodeVersion, setSelectedCodeVersion] = useState<WorkflowVersion | null>(null);
  const [showCurrentVersionCode, setShowCurrentVersionCode] = useState(false);
  const [generatedCleanupReport, setGeneratedCleanupReport] = useState<GeneratedWorkflowCleanupReport | null>(null);
  const [graph, setGraph] = useState<WorkflowGraph>(emptyGraph);
  const [flowNodes, setFlowNodes] = useState<Node[]>([]);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [pendingConnection, setPendingConnection] = useState<PendingConnection | null>(null);
  const [nodeEdgeAnchors, setNodeEdgeAnchors] = useState<NodeEdgeAnchors>({});
  const [nodeDragPreview, setNodeDragPreview] = useState<NodeDragPreview | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("config");
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
  const [humanApprovalTasks, setHumanApprovalTasks] = useState<HumanApprovalTask[]>([]);
  const [approvalCenterTasks, setApprovalCenterTasks] = useState<HumanApprovalTask[]>([]);
  const [approvalCenterStatus, setApprovalCenterStatus] = useState<HumanApprovalTaskStatus | "all">("pending");
  const [approvalCenterTotal, setApprovalCenterTotal] = useState(0);
  const [approvalCenterError, setApprovalCenterError] = useState<string | null>(null);
  const [approvalResponseDrafts, setApprovalResponseDrafts] = useState<Record<number, string>>({});
  const [approvalCommentDrafts, setApprovalCommentDrafts] = useState<Record<number, string>>({});
  const [selectedApprovalTaskIds, setSelectedApprovalTaskIds] = useState<Set<number>>(new Set());
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("正在连接本地 API");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState<number | null>(null);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeForm, setKnowledgeForm] = useState(defaultKnowledgeForm);
  const [retrieveForm, setRetrieveForm] = useState({
    query: "",
    top_k: "5",
    score_threshold: "0",
    context_budget_tokens: "3000",
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
  const [modelDefaults, setModelDefaults] = useState<ModelDefaults | null>(null);
  const [modelProviderForm, setModelProviderForm] = useState({
    name: "deepseek",
    provider_type: "deepseek",
    base_url: "https://api.deepseek.com",
    status: "active",
    config: stringifyJson({ api_key_secret: "deepseek_api_key" }),
  });
  const [modelProviderConfigError, setModelProviderConfigError] = useState<string | null>(null);
  const [modelProviderDrafts, setModelProviderDrafts] = useState<Record<number, ModelProviderDraft>>({});
  const [modelConfigForm, setModelConfigForm] = useState({
    provider_id: "",
    model_name: "deepseek-v4-flash",
    model_type: "chat",
    display_name: "DeepSeek V4-Flash",
    context_window: "1000000",
    default_config: stringifyJson({
      temperature: 0.3,
      max_tokens: 1000,
      model_version: "DeepSeek-V4-Flash",
      api_model_alias: "deepseek-v4-flash",
      thinking_mode: false,
    }),
    status: "active",
  });
  const [modelConfigError, setModelConfigError] = useState<string | null>(null);
  const [modelConfigDrafts, setModelConfigDrafts] = useState<Record<number, ModelConfigDraft>>({});
  const [opsQueues, setOpsQueues] = useState<OpsQueue[]>([]);
  const [opsWorkers, setOpsWorkers] = useState<OpsWorker[]>([]);
  const [opsDeadJobs, setOpsDeadJobs] = useState<OpsDeadJob[]>([]);
  const [opsFailedRuns, setOpsFailedRuns] = useState<OpsFailedRun[]>([]);
  const [opsDeadCount, setOpsDeadCount] = useState(0);
  const [opsRecoverResult, setOpsRecoverResult] = useState<string | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const mouseDragRef = useRef<{ type: NodeType; startX: number; startY: number } | null>(null);
  const pendingConnectionRef = useRef<PendingConnection | null>(null);
  const ignoreNextNodeClickRef = useRef(false);

  const navigationSections = useMemo(
    () => [...adminSections, { id: "ops" as const, label: "Ops", Icon: Activity }],
    [],
  );

  const selectedVersion = selectedWorkflow?.current_version_id
    ? `v${currentVersionDetail?.version ?? selectedWorkflow.current_version ?? selectedWorkflow.current_version_id}`
    : "未发布";
  const runVersionLabel = currentVersionDetail
    ? `v${currentVersionDetail.version}`
    : selectedWorkflow?.current_version_id
      ? selectedVersion
      : "未发布";
  const runCodeStatus = currentVersionDetail
    ? formatCodeStatus(currentVersionDetail.code_status, currentVersionDetail.code_path ? "已生成" : "未生成")
    : selectedWorkflow?.current_version_id
      ? "版本详情加载中"
      : "未生成";
  const runCodeModified = currentVersionDetail?.code_modified === true || currentVersionCode?.code_modified === true;
  const runCodeHash = shortHash(
    currentVersionCode?.code_hash_actual ?? currentVersionDetail?.code_hash_actual ?? currentVersionDetail?.code_hash,
  );
  const runCodePath = currentVersionCode?.code_path ?? currentVersionDetail?.code_path ?? null;

  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [graph.nodes, selectedNodeId],
  );

  const selectedEdge = useMemo(
    () => graph.edges.find((edge) => edge.id === selectedEdgeId) ?? null,
    [graph.edges, selectedEdgeId],
  );

  const selectedKnowledgeBase = useMemo(
    () => knowledgeBases.find((knowledgeBase) => knowledgeBase.id === selectedKnowledgeBaseId) ?? null,
    [knowledgeBases, selectedKnowledgeBaseId],
  );

  const hasProcessingKnowledgeDocuments = useMemo(
    () =>
      knowledgeDocuments.some((document) =>
        ["uploaded", "parsing", "chunking", "embedding"].includes(document.status),
      ),
    [knowledgeDocuments],
  );

  const pendingApprovalCenterTasks = useMemo(
    () => approvalCenterTasks.filter((task) => task.status === "pending"),
    [approvalCenterTasks],
  );

  const selectedPendingApprovalTasks = useMemo(
    () => pendingApprovalCenterTasks.filter((task) => selectedApprovalTaskIds.has(task.id)),
    [pendingApprovalCenterTasks, selectedApprovalTaskIds],
  );

  const selectedEdgeEndpoints = useMemo(() => {
    if (!selectedEdge) {
      return null;
    }
    return {
      source: graph.nodes.find((node) => node.id === selectedEdge.source) ?? null,
      target: graph.nodes.find((node) => node.id === selectedEdge.target) ?? null,
    };
  }, [graph.nodes, selectedEdge]);

  const selectGraphNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
    setInspectorTab("config");
  }, []);

  const clearCanvasSelection = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const traceStatusByNodeId = useMemo(() => {
    const statusMap = new Map<string, string>();
    trace?.nodes.forEach((node) => {
      statusMap.set(node.node_id, node.status);
    });
    return statusMap;
  }, [trace]);

  const measureNodeEdgeAnchors = useCallback(() => {
    if (!canvasRef.current || !flowInstance) {
      return;
    }

    const nextAnchors: NodeEdgeAnchors = {};
    canvasRef.current.querySelectorAll<HTMLElement>(".react-flow__node.flow-node").forEach((nodeElement) => {
      const nodeId = nodeElement.getAttribute("data-id");
      if (!nodeId) {
        return;
      }

      const rect = nodeElement.getBoundingClientRect();
      const centerY = rect.top + rect.height / 2;
      nextAnchors[nodeId] = {
        source: flowInstance.screenToFlowPosition({ x: rect.right, y: centerY }),
        target: flowInstance.screenToFlowPosition({ x: rect.left, y: centerY }),
      };
    });

    setNodeEdgeAnchors((currentAnchors) =>
      areNodeEdgeAnchorsEqual(currentAnchors, nextAnchors) ? currentAnchors : nextAnchors,
    );
  }, [flowInstance]);

  useEffect(() => {
    const frameId = window.requestAnimationFrame(measureNodeEdgeAnchors);
    return () => window.cancelAnimationFrame(frameId);
  }, [flowNodes, graph.nodes, measureNodeEdgeAnchors, selectedNodeId]);

  const connectGraphNodes = useCallback(
    (sourceNodeId: string, targetNodeId: string) => {
      const sourceNode = graph.nodes.find((node) => node.id === sourceNodeId);
      const targetNode = graph.nodes.find((node) => node.id === targetNodeId);
      const error = getConnectionError(graph, sourceNodeId, targetNodeId);
      if (error || !sourceNode || !targetNode) {
        setStatusLine(error ?? "未找到连线节点，请重新拖拽");
        return;
      }

      const nextEdge: GraphEdge = {
        id: makeEdgeId(sourceNodeId, targetNodeId, graph.edges.length),
        source: sourceNodeId,
        target: targetNodeId,
        label: sourceNode.type === "branch" ? "branch" : undefined,
      };
      setGraph({ ...graph, edges: [...graph.edges, nextEdge] });
      setSelectedEdgeId(nextEdge.id);
      setSelectedNodeId(null);
      setInspectorTab("config");
      setTrace(null);
      setStatusLine(`已连接：${sourceNode.name} -> ${targetNode.name}`);
    },
    [graph],
  );

  const deleteGraphEdge = useCallback(
    (edgeId: string) => {
      const edge = graph.edges.find((item) => item.id === edgeId);
      setGraph({ ...graph, edges: graph.edges.filter((item) => item.id !== edgeId) });
      setSelectedEdgeId(null);
      setTrace(null);
      setStatusLine(edge ? `已删除连线：${edge.source} -> ${edge.target}` : "已删除连线");
    },
    [graph],
  );

  const updateSelectedEdge = useCallback(
    (patch: Partial<GraphEdge>) => {
      if (!selectedEdgeId) {
        return;
      }
      setGraph((currentGraph) => ({
        ...currentGraph,
        edges: currentGraph.edges.map((edge) => (edge.id === selectedEdgeId ? { ...edge, ...patch } : edge)),
      }));
      setTrace(null);
    },
    [selectedEdgeId],
  );

  useEffect(() => {
    if (!selectedEdgeId) {
      return undefined;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Backspace" && event.key !== "Delete") {
        return;
      }
      event.preventDefault();
      deleteGraphEdge(selectedEdgeId);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteGraphEdge, selectedEdgeId]);

  useEffect(() => {
    if (selectedEdgeId && !graph.edges.some((edge) => edge.id === selectedEdgeId)) {
      setSelectedEdgeId(null);
    }
  }, [graph.edges, selectedEdgeId]);

  const quickAddConnectedNode = useCallback(
    (sourceNodeId: string) => {
      if (!selectedWorkflow || busyAction !== null) {
        return;
      }

      const sourceNode = graph.nodes.find((node) => node.id === sourceNodeId);
      if (!sourceNode) {
        setStatusLine("未找到当前节点，无法添加后续节点");
        return;
      }
      if (sourceNode.type === "end") {
        setStatusLine("结束节点不能继续添加后续节点");
        return;
      }
      if (sourceNode.type !== "branch" && graph.edges.some((edge) => edge.source === sourceNodeId)) {
        setStatusLine("普通节点只能保留一条出边");
        return;
      }

      const nextType = getDefaultNextNodeType(sourceNode.type);
      const template = nodeCatalog.find((item) => item.type === nextType);
      if (!template) {
        return;
      }

      const sameTypeCount = graph.nodes.filter((node) => node.type === nextType).length;
      const nextNode = createGraphNode(template, sameTypeCount + 1, graph.nodes.length, {
        x: Math.round(sourceNode.position.x + 240),
        y: Math.round(sourceNode.position.y),
      });
      if (nextNode.type === "end") {
        nextNode.config = {
          ...nextNode.config,
          outputs: { output: defaultFinalOutputReference(sourceNode) },
          output_value_kinds: { output: "reference" },
        };
      }
      const nextEdge: GraphEdge = {
        id: makeEdgeId(sourceNode.id, nextNode.id, graph.edges.length),
        source: sourceNode.id,
        target: nextNode.id,
        label: sourceNode.type === "branch" ? "branch" : undefined,
      };

      setGraph({
        ...graph,
        nodes: [...graph.nodes, nextNode],
        edges: [...graph.edges, nextEdge],
      });
      setSelectedNodeId(nextNode.id);
      setSelectedEdgeId(null);
      setTrace(null);
      setStatusLine(`已添加并连接节点：${template.label}`);
    },
    [busyAction, graph, selectedWorkflow],
  );

  const startManualConnection = useCallback(
    (sourceNodeId: string, clientX: number, clientY: number) => {
      if (!selectedWorkflow || busyAction !== null) {
        return;
      }

      const sourceNode = graph.nodes.find((node) => node.id === sourceNodeId);
      if (!sourceNode) {
        return;
      }

      const from = nodeEdgeAnchors[sourceNodeId]?.source ?? getNodeEdgePoint(sourceNode, "source");
      const to = flowInstance?.screenToFlowPosition({ x: clientX, y: clientY }) ?? from;
      const pending: PendingConnection = {
        sourceNodeId,
        startClientX: clientX,
        startClientY: clientY,
        from,
        to,
      };
      pendingConnectionRef.current = pending;
      setPendingConnection(pending);

      const handleMouseMove = (mouseEvent: MouseEvent) => {
        const current = pendingConnectionRef.current;
        if (!current) {
          return;
        }
        const nextPending = {
          ...current,
          to: flowInstance?.screenToFlowPosition({ x: mouseEvent.clientX, y: mouseEvent.clientY }) ?? current.to,
        };
        pendingConnectionRef.current = nextPending;
        setPendingConnection(nextPending);
      };

      const handleMouseUp = (mouseEvent: MouseEvent) => {
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
        const current = pendingConnectionRef.current;
        pendingConnectionRef.current = null;
        setPendingConnection(null);

        if (!current) {
          return;
        }
        const moved = Math.hypot(mouseEvent.clientX - current.startClientX, mouseEvent.clientY - current.startClientY);
        if (moved < nodeDropMoveThreshold) {
          return;
        }

        const targetNodeId = findFlowNodeIdAtClientPoint(canvasRef.current, mouseEvent.clientX, mouseEvent.clientY);
        if (!targetNodeId) {
          setStatusLine("请把连线拖到目标节点上释放");
          return;
        }
        connectGraphNodes(current.sourceNodeId, targetNodeId);
      };

      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    },
    [busyAction, connectGraphNodes, flowInstance, graph.nodes, nodeEdgeAnchors, selectedWorkflow],
  );

  useEffect(() => {
    setFlowNodes((currentNodes) =>
      graphToFlowNodes(
        graph,
        selectedNodeId,
        traceStatusByNodeId,
        quickAddConnectedNode,
        startManualConnection,
        currentNodes,
      ),
    );
  }, [graph, quickAddConnectedNode, selectedNodeId, startManualConnection, traceStatusByNodeId]);

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

  const loadWorkflowVersions = useCallback(async (workflowId: number) => {
    const response = await fetchWithTimeout(`${apiBaseUrl}/workflows/${workflowId}/versions?page_size=20`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`GET /workflows/${workflowId}/versions ${response.status}`);
    }
    const data = await response.json();
    const items = (data.items ?? []) as WorkflowVersion[];
    setWorkflowVersions(items);
    return items;
  }, []);

  const loadWorkflow = useCallback(async (workflowId: number) => {
    const response = await fetchWithTimeout(`${apiBaseUrl}/workflows/${workflowId}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`GET /workflows/${workflowId} ${response.status}`);
    }
    const workflow = (await response.json()) as Workflow;
    let versionDetail: WorkflowVersion | null = null;
    if (workflow.current_version_id) {
      const versionResponse = await fetchWithTimeout(`${apiBaseUrl}/workflow-versions/${workflow.current_version_id}`, {
        cache: "no-store",
      });
      if (versionResponse.ok) {
        versionDetail = (await versionResponse.json()) as WorkflowVersion;
      }
    }
    const versions = await loadWorkflowVersions(workflowId).catch(() => []);
    setSelectedWorkflow(workflow);
    setCurrentVersionDetail(versionDetail);
    setWorkflowVersions(versions);
    setCurrentVersionCode(null);
    setSelectedCodeVersion(null);
    setShowCurrentVersionCode(false);
    setGeneratedCleanupReport(null);
    setNameDraft(workflow.name);
    setDescriptionDraft(workflow.description ?? "");
    setGraph(workflow.draft_graph_json);
    setSelectedNodeId(null);
    setValidation(null);
    setTrace(null);
  }, [loadWorkflowVersions]);

  const loadRuns = useCallback(async (workflowId: number) => {
    const response = await fetchWithTimeout(`${apiBaseUrl}/runs?workflow_id=${workflowId}&page_size=8`, { cache: "no-store" });
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
        const response = await fetchWithTimeout(`${apiBaseUrl}/workflows`, { cache: "no-store" });
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

  const loadKnowledge = useCallback(async (preferredKnowledgeBaseId?: number, options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setBusyAction("knowledge");
    }
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/knowledge-bases`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`GET /knowledge-bases ${response.status}`);
      }
      const data = await response.json();
      const items = data.items as KnowledgeBase[];
      setKnowledgeBases(items);
      const nextId = preferredKnowledgeBaseId ?? items[0]?.id ?? null;
      setSelectedKnowledgeBaseId(nextId);
      if (nextId) {
        const documentsResponse = await fetchWithTimeout(`${apiBaseUrl}/knowledge-bases/${nextId}/documents`, {
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
      if (!options?.silent) {
        setStatusLine("知识库已同步");
      }
    } catch (error) {
      if (!options?.silent) {
        setStatusLine(error instanceof Error ? error.message : "知识库同步失败");
      }
    } finally {
      if (!options?.silent) {
        setBusyAction(null);
      }
    }
  }, []);

  const loadKnowledgeDocuments = useCallback(async (kbId: number, options?: { silent?: boolean }) => {
    setSelectedKnowledgeBaseId(kbId);
    if (!options?.silent) {
      setBusyAction("knowledge-documents");
    }
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/knowledge-bases/${kbId}/documents`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`GET /knowledge-bases/${kbId}/documents ${response.status}`);
      }
      const data = await response.json();
      setKnowledgeDocuments(data.items as KnowledgeDocument[]);
      if (!options?.silent) {
        setStatusLine(`已载入知识库 #${kbId} 文档`);
      }
    } catch (error) {
      if (!options?.silent) {
        setStatusLine(error instanceof Error ? error.message : "文档同步失败");
      }
    } finally {
      if (!options?.silent) {
        setBusyAction(null);
      }
    }
  }, []);

  const loadTools = useCallback(async () => {
    setBusyAction("tools");
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/tools?type=api`, { cache: "no-store" });
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/secrets`, { cache: "no-store" });
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
      const [providersResponse, configsResponse, defaultsResponse] = await Promise.all([
        fetchWithTimeout(`${apiBaseUrl}/model-providers`, { cache: "no-store" }),
        fetchWithTimeout(`${apiBaseUrl}/model-configs`, { cache: "no-store" }),
        fetchWithTimeout(`${apiBaseUrl}/model-defaults`, { cache: "no-store" }),
      ]);
      if (!providersResponse.ok) {
        throw new Error(`GET /model-providers ${providersResponse.status}`);
      }
      if (!configsResponse.ok) {
        throw new Error(`GET /model-configs ${configsResponse.status}`);
      }
      if (!defaultsResponse.ok) {
        throw new Error(`GET /model-defaults ${defaultsResponse.status}`);
      }
      const providersData = await providersResponse.json();
      const configsData = await configsResponse.json();
      const defaultsData = (await defaultsResponse.json()) as ModelDefaults;
      const providers = providersData.items as ModelProvider[];
      const configs = configsData.items as ModelConfig[];
      setModelProviders(providers);
      setModelConfigs(configs);
      setModelDefaults(defaultsData);
      const deepseekProvider = providers.find((provider) => provider.name === "deepseek");
      setModelConfigForm((form) =>
        form.provider_id || !deepseekProvider
          ? form
          : {
              ...form,
              provider_id: String(deepseekProvider.id),
              model_name:
                form.model_name === "deepseek-v4-flash" || !form.model_name
                  ? defaultsData.deepseek.model_name
                  : form.model_name,
              display_name:
                form.display_name === "DeepSeek V4-Flash" || !form.display_name
                  ? defaultsData.deepseek.display_name
                  : form.display_name,
              context_window:
                form.context_window === "1000000" || !form.context_window
                  ? String(defaultsData.deepseek.context_window)
                  : form.context_window,
              default_config:
                form.default_config ===
                  stringifyJson({
                    temperature: 0.3,
                    max_tokens: 1000,
                    model_version: "DeepSeek-V4-Flash",
                    api_model_alias: "deepseek-v4-flash",
                    thinking_mode: false,
                  }) || !form.default_config
                  ? stringifyJson(defaultsData.deepseek.default_config)
                  : form.default_config,
            },
      );
      setModelProviderForm((form) =>
        form.name === "deepseek" && form.provider_type === "deepseek"
          ? {
              ...form,
              base_url:
                form.base_url === "https://api.deepseek.com" || !form.base_url
                  ? defaultsData.deepseek.base_url
                  : form.base_url,
              config:
                form.config === stringifyJson({ api_key_secret: "deepseek_api_key" }) || !form.config
                  ? stringifyJson({ api_key_secret: defaultsData.deepseek.api_key_secret })
                  : form.config,
            }
          : form,
      );
      setModelProviderDrafts((currentDrafts) =>
        providers.reduce<Record<number, ModelProviderDraft>>((drafts, provider) => {
          drafts[provider.id] = currentDrafts[provider.id] ?? {
            name: provider.name,
            provider_type: provider.provider_type,
            base_url: provider.base_url ?? "",
            status: provider.status,
            config: stringifyJson(provider.config_json ?? {}),
            error: null,
          };
          return drafts;
        }, {}),
      );
      setModelConfigDrafts((currentDrafts) =>
        configs.reduce<Record<number, ModelConfigDraft>>((drafts, modelConfig) => {
          drafts[modelConfig.id] = currentDrafts[modelConfig.id] ?? {
            provider_id: String(modelConfig.provider_id),
            model_name: modelConfig.model_name,
            model_type: modelConfig.model_type,
            display_name: modelConfig.display_name ?? "",
            context_window: modelConfig.context_window ? String(modelConfig.context_window) : "",
            default_config: stringifyJson(modelConfig.default_config ?? {}),
            status: modelConfig.status,
            error: null,
          };
          return drafts;
        }, {}),
      );
      setStatusLine("Models 已同步");
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "Models 同步失败");
    } finally {
      setBusyAction(null);
    }
  }, []);

  const loadOps = useCallback(async () => {
    setBusyAction("ops");
    try {
      const [queuesResponse, workersResponse, deadResponse, failedRunsResponse] = await Promise.all([
        fetchWithTimeout(`${apiBaseUrl}/ops/queues`, { cache: "no-store" }),
        fetchWithTimeout(`${apiBaseUrl}/ops/workers?active_seconds=600`, { cache: "no-store" }),
        fetchWithTimeout(`${apiBaseUrl}/ops/queues/workflow_runs/dead`, { cache: "no-store" }),
        fetchWithTimeout(`${apiBaseUrl}/ops/workflow_runs/failed?limit=20`, { cache: "no-store" }),
      ]);
      if (!queuesResponse.ok) {
        throw new Error(`GET /ops/queues ${queuesResponse.status}`);
      }
      if (!workersResponse.ok) {
        throw new Error(`GET /ops/workers ${workersResponse.status}`);
      }
      if (!deadResponse.ok) {
        throw new Error(`GET /ops/queues/workflow_runs/dead ${deadResponse.status}`);
      }
      if (!failedRunsResponse.ok) {
        throw new Error(`GET /ops/workflow_runs/failed ${failedRunsResponse.status}`);
      }

      const [queuesData, workersData, deadData, failedRunsData] = await Promise.all([
        queuesResponse.json(),
        workersResponse.json(),
        deadResponse.json(),
        failedRunsResponse.json(),
      ]);
      const deadJobs = extractItems<OpsDeadJob>(deadData, ["items", "jobs", "dead_jobs", "dead"]);
      const failedRuns = extractItems<OpsFailedRun>(failedRunsData, ["items", "runs", "workflow_runs", "failed_runs"]);
      const queueItems = extractItems<OpsQueue>(queuesData, ["items", "queues"]);
      setOpsQueues(queueItems.length > 0 ? queueItems : ([queuesData] as OpsQueue[]));
      setOpsWorkers(extractItems<OpsWorker>(workersData, ["items", "workers"]));
      setOpsDeadJobs(deadJobs);
      setOpsFailedRuns(failedRuns);
      setOpsDeadCount(
        extractNumber(deadData, ["count", "dead_count", "total"])
          ?? extractNumber(queuesData, ["dead_letter_depth"])
          ?? deadJobs.length,
      );
      setStatusLine("Ops 已同步");
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "Ops 同步失败");
    } finally {
      setBusyAction(null);
    }
  }, []);

  const seedApprovalDrafts = useCallback((tasks: HumanApprovalTask[]) => {
    setApprovalResponseDrafts((drafts) => {
      const nextDrafts = { ...drafts };
      tasks.forEach((task) => {
        if (!nextDrafts[task.id]) {
          nextDrafts[task.id] = stringifyJson({});
        }
      });
      return nextDrafts;
    });
    setApprovalCommentDrafts((drafts) => {
      const nextDrafts = { ...drafts };
      tasks.forEach((task) => {
        if (!(task.id in nextDrafts)) {
          nextDrafts[task.id] = "";
        }
      });
      return nextDrafts;
    });
  }, []);

  const loadApprovalCenterTasks = useCallback(async () => {
    setBusyAction("approvals");
    try {
      const params = new URLSearchParams({ page_size: "50" });
      if (approvalCenterStatus !== "all") {
        params.set("status", approvalCenterStatus);
      }
      const response = await fetchWithTimeout(`${apiBaseUrl}/human-approval-tasks?${params.toString()}`, {
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = data && typeof data === "object" ? (data as { detail?: unknown }).detail : null;
        const message =
          typeof detail === "string"
            ? detail
            : detail && typeof detail === "object" && "message" in detail
              ? String((detail as { message?: unknown }).message)
              : `GET /human-approval-tasks ${response.status}`;
        throw new Error(message);
      }
      const tasks = extractItems<HumanApprovalTask>(data, ["items"]);
      setApprovalCenterTasks(tasks);
      setApprovalCenterTotal(extractNumber(data, ["total", "count"]) ?? tasks.length);
      setSelectedApprovalTaskIds((selectedIds) => {
        const pendingIds = new Set(tasks.filter((task) => task.status === "pending").map((task) => task.id));
        return new Set(Array.from(selectedIds).filter((taskId) => pendingIds.has(taskId)));
      });
      seedApprovalDrafts(tasks.filter((task) => task.status === "pending"));
      setApprovalCenterError(null);
      setStatusLine(`审批任务已同步：${tasks.length} / ${extractNumber(data, ["total", "count"]) ?? tasks.length}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "审批任务同步失败";
      setApprovalCenterError(message);
      setStatusLine(message);
    } finally {
      setBusyAction(null);
    }
  }, [approvalCenterStatus, seedApprovalDrafts]);

  const recoverWorkflowRunsQueue = async () => {
    setBusyAction("ops-recover");
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/ops/queues/workflow_runs/recover`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(`POST /ops/queues/workflow_runs/recover ${response.status}`);
      }
      const rawResult = await response.text();
      const data = rawResult ? (JSON.parse(rawResult) as unknown) : {};
      setOpsRecoverResult(JSON.stringify(data ?? {}, null, 2));
      setStatusLine("workflow_runs 恢复完成");
      await loadOps();
    } catch (error) {
      const message = error instanceof Error ? error.message : "恢复队列失败";
      setOpsRecoverResult(message);
      setStatusLine(message);
    } finally {
      setBusyAction(null);
    }
  };

  const recoverWorkflowRun = async (runId: string | number) => {
    setBusyAction(`ops-recover-${runId}`);
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/ops/workflow_runs/${runId}/recover`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(`POST /ops/workflow_runs/${runId}/recover ${response.status}`);
      }
      const rawResult = await response.text();
      const data = rawResult ? (JSON.parse(rawResult) as unknown) : {};
      setOpsRecoverResult(JSON.stringify(data ?? {}, null, 2));
      setStatusLine(`workflow_run #${runId} 恢复完成`);
      await loadOps();
    } catch (error) {
      const message = error instanceof Error ? error.message : `恢复 run #${runId} 失败`;
      setOpsRecoverResult(message);
      setStatusLine(message);
    } finally {
      setBusyAction(null);
    }
  };

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
    if (activeSection === "approvals") {
      void loadApprovalCenterTasks();
    }
    if (activeSection === "ops") {
      void loadOps();
    }
  }, [activeSection, loadApprovalCenterTasks, loadKnowledge, loadModels, loadOps, loadSecrets, loadTools]);

  useEffect(() => {
    if (activeSection !== "knowledge" || !selectedKnowledgeBaseId || !hasProcessingKnowledgeDocuments) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      void loadKnowledgeDocuments(selectedKnowledgeBaseId, { silent: true });
      void loadKnowledge(selectedKnowledgeBaseId, { silent: true });
    }, 3000);
    return () => window.clearInterval(intervalId);
  }, [
    activeSection,
    hasProcessingKnowledgeDocuments,
    loadKnowledge,
    loadKnowledgeDocuments,
    selectedKnowledgeBaseId,
  ]);

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
      const response = await fetchWithTimeout(`${apiBaseUrl}/workflows`, {
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
    const chunkSize = Number(knowledgeForm.chunk_size_tokens);
    const chunkOverlap = Number(knowledgeForm.chunk_overlap_tokens);
    if (
      !Number.isInteger(chunkSize) ||
      !Number.isInteger(chunkOverlap) ||
      chunkSize <= 0 ||
      chunkOverlap < 0 ||
      chunkOverlap >= chunkSize
    ) {
      setStatusLine("chunk_size_tokens 必须大于 0，chunk_overlap_tokens 必须小于 chunk_size_tokens");
      return;
    }

    setBusyAction("create-knowledge");
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/knowledge-bases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: knowledgeForm.name,
          description: knowledgeForm.description || null,
          embedding_model: knowledgeForm.embedding_model,
          embedding_dim: 1536,
          tokenizer: knowledgeForm.tokenizer,
          config: {
            embedding_provider: knowledgeForm.embedding_provider,
            chunk_size_tokens: chunkSize,
            chunk_overlap_tokens: chunkOverlap,
          },
        }),
      });
      if (!response.ok) {
        throw new Error(`POST /knowledge-bases ${response.status}`);
      }
      const knowledgeBase = (await response.json()) as KnowledgeBase;
      setKnowledgeForm(defaultKnowledgeForm);
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/tools`, {
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/tools/${toolId}/test`, {
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/secrets`, {
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/knowledge-bases/${kbId}/documents`, {
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/documents/${documentId}/retry`, { method: "POST" });
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/documents/${documentId}`, { method: "DELETE" });
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
    const contextBudgetTokens = Number(retrieveForm.context_budget_tokens);
    if (
      !retrieveForm.query.trim() ||
      !Number.isFinite(topK) ||
      !Number.isFinite(scoreThreshold) ||
      !Number.isFinite(contextBudgetTokens)
    ) {
      setRetrieveError("请填写 query，并确认 top_k / score_threshold / context_budget_tokens 是数字");
      return;
    }

    setRetrieveError(null);
    setBusyAction("retrieve-knowledge");
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/knowledge-bases/${kbId}/retrieve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: retrieveForm.query,
          top_k: topK,
          score_threshold: scoreThreshold,
          context_budget_tokens: contextBudgetTokens,
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/tools/${toolId}`, {
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/secrets/${secretId}`, {
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

  const createModelProvider = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsedConfig = parseJsonObject(modelProviderForm.config);
    if (parsedConfig.error) {
      setModelProviderConfigError(parsedConfig.error);
      setStatusLine("Provider config 不是合法 JSON 对象");
      return;
    }

    setModelProviderConfigError(null);
    setBusyAction("create-model-provider");
    try {
      const response = await fetch(`${apiBaseUrl}/model-providers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: modelProviderForm.name,
          provider_type: modelProviderForm.provider_type,
          base_url: modelProviderForm.base_url || null,
          status: modelProviderForm.status,
          config: parsedConfig.value,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(readApiErrorMessage(result, `POST /model-providers ${response.status}`));
      }
      setModelProviderForm({
        name: modelDefaults?.deepseek.provider_name ?? "deepseek",
        provider_type: modelDefaults?.deepseek.provider_type ?? "deepseek",
        base_url: modelDefaults?.deepseek.base_url ?? "https://api.deepseek.com",
        status: "active",
        config: stringifyJson({ api_key_secret: modelDefaults?.deepseek.api_key_secret ?? "deepseek_api_key" }),
      });
      setStatusLine(`已创建 Model Provider #${result.id}`);
      await loadModels();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "创建 Model Provider 失败");
    } finally {
      setBusyAction(null);
    }
  };

  const updateModelProvider = async (providerId: number) => {
    const draft = modelProviderDrafts[providerId];
    if (!draft) {
      return;
    }
    const parsedConfig = parseJsonObject(draft.config);
    if (parsedConfig.error) {
      setModelProviderDrafts((drafts) => ({
        ...drafts,
        [providerId]: { ...draft, error: parsedConfig.error },
      }));
      setStatusLine("Provider config 不是合法 JSON 对象");
      return;
    }

    setBusyAction(`update-model-provider-${providerId}`);
    try {
      const response = await fetch(`${apiBaseUrl}/model-providers/${providerId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: draft.name,
          provider_type: draft.provider_type,
          base_url: draft.base_url || null,
          status: draft.status,
          config: parsedConfig.value,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(readApiErrorMessage(result, `PUT /model-providers/${providerId} ${response.status}`));
      }
      setStatusLine(`已更新 Model Provider #${providerId}`);
      await loadModels();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "更新 Model Provider 失败");
    } finally {
      setBusyAction(null);
    }
  };

  const createModelConfig = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsedDefaultConfig = parseJsonObject(modelConfigForm.default_config);
    const providerId = Number(modelConfigForm.provider_id);
    const contextWindow = modelConfigForm.context_window ? Number(modelConfigForm.context_window) : null;
    if (parsedDefaultConfig.error || !Number.isInteger(providerId) || providerId <= 0) {
      setModelConfigError(parsedDefaultConfig.error ?? "请选择 Provider");
      setStatusLine("Model Config 表单不完整");
      return;
    }
    if (contextWindow !== null && (!Number.isInteger(contextWindow) || contextWindow <= 0)) {
      setModelConfigError("context_window 必须是正整数");
      return;
    }

    setModelConfigError(null);
    setBusyAction("create-model-config");
    try {
      const response = await fetch(`${apiBaseUrl}/model-configs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_id: providerId,
          model_name: modelConfigForm.model_name,
          model_type: modelConfigForm.model_type,
          display_name: modelConfigForm.display_name || null,
          context_window: contextWindow,
          default_config: parsedDefaultConfig.value,
          status: modelConfigForm.status,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(readApiErrorMessage(result, `POST /model-configs ${response.status}`));
      }
      setModelConfigForm((form) => ({
        ...form,
        model_name: modelDefaults?.deepseek.model_name ?? "deepseek-v4-flash",
        display_name: modelDefaults?.deepseek.display_name ?? "DeepSeek V4-Flash",
        context_window: String(modelDefaults?.deepseek.context_window ?? 1000000),
        default_config: stringifyJson(
          modelDefaults?.deepseek.default_config ?? {
            temperature: 0.3,
            max_tokens: 1000,
            model_version: "DeepSeek-V4-Flash",
            api_model_alias: "deepseek-v4-flash",
            thinking_mode: false,
          },
        ),
      }));
      setStatusLine(`已创建 Model Config #${result.id}`);
      await loadModels();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "创建 Model Config 失败");
    } finally {
      setBusyAction(null);
    }
  };

  const updateModelConfig = async (modelConfigId: number) => {
    const draft = modelConfigDrafts[modelConfigId];
    if (!draft) {
      return;
    }
    const parsedDefaultConfig = parseJsonObject(draft.default_config);
    const providerId = Number(draft.provider_id);
    const contextWindow = draft.context_window ? Number(draft.context_window) : null;
    if (parsedDefaultConfig.error || !Number.isInteger(providerId) || providerId <= 0) {
      setModelConfigDrafts((drafts) => ({
        ...drafts,
        [modelConfigId]: { ...draft, error: parsedDefaultConfig.error ?? "请选择 Provider" },
      }));
      setStatusLine("Model Config 表单不完整");
      return;
    }
    if (contextWindow !== null && (!Number.isInteger(contextWindow) || contextWindow <= 0)) {
      setModelConfigDrafts((drafts) => ({
        ...drafts,
        [modelConfigId]: { ...draft, error: "context_window 必须是正整数" },
      }));
      return;
    }

    setBusyAction(`update-model-config-${modelConfigId}`);
    try {
      const response = await fetch(`${apiBaseUrl}/model-configs/${modelConfigId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_id: providerId,
          model_name: draft.model_name,
          model_type: draft.model_type,
          display_name: draft.display_name || null,
          context_window: contextWindow,
          default_config: parsedDefaultConfig.value,
          status: draft.status,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(readApiErrorMessage(result, `PUT /model-configs/${modelConfigId} ${response.status}`));
      }
      setStatusLine(`已更新 Model Config #${modelConfigId}`);
      await loadModels();
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "更新 Model Config 失败");
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/workflows/${selectedWorkflow.id}`, {
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

  const loadPendingApprovalTasks = useCallback(async (runId: number) => {
    const response = await fetchWithTimeout(
      `${apiBaseUrl}/human-approval-tasks?run_id=${runId}&status=pending&page_size=20`,
      { cache: "no-store" },
    );
    const data = await response.json();
    if (!response.ok) {
      const detail = data && typeof data === "object" ? (data as { detail?: unknown }).detail : null;
      const message =
        typeof detail === "string"
          ? detail
          : detail && typeof detail === "object" && "message" in detail
            ? String((detail as { message?: unknown }).message)
            : `GET /human-approval-tasks ${response.status}`;
      throw new Error(message);
    }
    const tasks = extractItems<HumanApprovalTask>(data, ["items"]);
    setHumanApprovalTasks(tasks);
    seedApprovalDrafts(tasks);
    setApprovalError(null);
  }, [seedApprovalDrafts]);

  useEffect(() => {
    const runId = trace ? getRunId(trace.run) : null;
    if (!runId || trace?.run.status !== "waiting_approval") {
      setHumanApprovalTasks([]);
      setApprovalError(null);
      return;
    }

    void loadPendingApprovalTasks(runId).catch((error) => {
      setApprovalError(error instanceof Error ? error.message : "待审批任务载入失败");
    });
  }, [loadPendingApprovalTasks, trace]);

  const loadRunTrace = async (runId: number) => {
    setBusyAction("trace");
    try {
      const traceResponse = await fetchWithTimeout(`${apiBaseUrl}/runs/${runId}/trace`, { cache: "no-store" });
      if (!traceResponse.ok) {
        throw new Error(`GET /runs/${runId}/trace ${traceResponse.status}`);
      }
      const nextTrace = (await traceResponse.json()) as RunTrace;
      setTrace(nextTrace);
      setInspectorTab(nextTrace.run.status === "waiting_approval" ? "run" : "trace");
      const runtimeHint = nextTrace.run.error_code
        ? formatRuntimeError(nextTrace.run.error_code, nextTrace.run.error_message)
        : null;
      setStatusLine(runtimeHint ? `已载入运行 #${runId} · ${runtimeHint}` : `已载入运行 #${runId} · ${nextTrace.run.status}`);
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/workflows/${selectedWorkflow.id}/validate`, {
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

  const refreshCurrentVersionDetail = async () => {
    if (!selectedWorkflow?.current_version_id) {
      setCurrentVersionDetail(null);
      return null;
    }

    const response = await fetchWithTimeout(`${apiBaseUrl}/workflow-versions/${selectedWorkflow.current_version_id}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`GET /workflow-versions/${selectedWorkflow.current_version_id} ${response.status}`);
    }
    const version = (await response.json()) as WorkflowVersion;
    setCurrentVersionDetail(version);
    void loadWorkflowVersions(selectedWorkflow.id).catch(() => undefined);
    if (currentVersionCode && currentVersionCode.id !== version.id) {
      setCurrentVersionCode(null);
      setSelectedCodeVersion(null);
      setShowCurrentVersionCode(false);
    }
    return version;
  };

  const loadCurrentVersionCode = async (targetVersion?: WorkflowVersion) => {
    const versionId = targetVersion?.id ?? selectedWorkflow?.current_version_id;
    if (!versionId) {
      return;
    }
    setBusyAction("version-code");
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/workflow-versions/${versionId}/code`, {
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail?.message ?? `GET /workflow-versions/code ${response.status}`);
      }
      const code = result as WorkflowVersionCode;
      setCurrentVersionCode(code);
      setSelectedCodeVersion({ ...(targetVersion ?? code), ...code });
      setShowCurrentVersionCode(true);
      setCurrentVersionDetail((current) => (current?.id === code.id ? { ...current, ...code } : current));
      setWorkflowVersions((items) => items.map((item) => (item.id === code.id ? { ...item, ...code } : item)));
      setStatusLine(
        code.code_modified
          ? `v${code.version} workflow.py hash 已变更，运行将以本地代码为准`
          : `已载入 v${code.version} 版本代码`,
      );
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "版本代码载入失败");
    } finally {
      setBusyAction(null);
    }
  };

  const regenerateVersionCode = async (targetVersion: WorkflowVersion) => {
    const status = targetVersion.code_status ?? (targetVersion.code_path ? "ok" : "missing_metadata");
    const force = status === "ok" || status === "modified";
    if (
      force &&
      !window.confirm(
        status === "modified"
          ? `v${targetVersion.version} 的本地 workflow.py hash 已变更，重生成会覆盖本地代码。是否继续？`
          : `v${targetVersion.version} 当前 hash 一致，是否仍然强制重生成？`,
      )
    ) {
      setStatusLine("已取消代码重生成");
      return;
    }

    setBusyAction("version-code-regenerate");
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/workflow-versions/${targetVersion.id}/regenerate-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }),
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail?.message ?? `POST /workflow-versions/regenerate-code ${response.status}`);
      }
      const regenerated = result as WorkflowVersion;
      setWorkflowVersions((items) =>
        items.map((item) => (item.id === regenerated.id ? { ...item, ...regenerated } : item)),
      );
      setCurrentVersionDetail((current) => (current?.id === regenerated.id ? { ...current, ...regenerated } : current));
      if (selectedCodeVersion?.id === regenerated.id) {
        setCurrentVersionCode(null);
        setSelectedCodeVersion(regenerated);
        setShowCurrentVersionCode(false);
      }
      if (selectedWorkflow) {
        await loadWorkflowVersions(selectedWorkflow.id);
      }
      setStatusLine(`已重生成 v${regenerated.version} workflow.py`);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "代码重生成失败");
    } finally {
      setBusyAction(null);
    }
  };

  const cleanupGeneratedWorkflowDirs = async () => {
    setBusyAction("generated-cleanup");
    try {
      const previewResponse = await fetchWithTimeout(`${apiBaseUrl}/generated-workflows/cleanup?dry_run=true`, {
        method: "POST",
        cache: "no-store",
      });
      const previewResult = await previewResponse.json();
      if (!previewResponse.ok) {
        throw new Error(previewResult.detail ?? `POST /generated-workflows/cleanup ${previewResponse.status}`);
      }
      const preview = previewResult as GeneratedWorkflowCleanupReport;
      setGeneratedCleanupReport(preview);
      if (preview.removed_total === 0) {
        setStatusLine(`生成目录清理预览：无需移除，保留 ${preview.kept_total} 个已发布版本`);
        return;
      }
      if (
        !window.confirm(
          `生成目录清理预览将移除 ${preview.removed_total} 项：temp ${preview.removed_temp_dirs.length}，orphan ${preview.removed_orphan_version_dirs.length}。是否执行？`,
        )
      ) {
        setStatusLine("已完成生成目录清理预览，未执行删除");
        return;
      }

      const response = await fetchWithTimeout(`${apiBaseUrl}/generated-workflows/cleanup?dry_run=false`, {
        method: "POST",
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail ?? `POST /generated-workflows/cleanup ${response.status}`);
      }
      const report = result as GeneratedWorkflowCleanupReport;
      setGeneratedCleanupReport(report);
      setStatusLine(
        `生成目录清理完成：移除 ${report.removed_total} 项，保留 ${report.kept_total} 个已发布版本`,
      );
      if (selectedWorkflow?.current_version_id) {
        await refreshCurrentVersionDetail();
      }
      if (selectedWorkflow) {
        await loadWorkflowVersions(selectedWorkflow.id);
      }
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : "生成目录清理失败");
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
      const response = await fetchWithTimeout(`${apiBaseUrl}/workflows/${selectedWorkflow.id}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ release_note: "MVP vertical slice" }),
      });
      const result = await response.json();
      if (!response.ok) {
        setValidation(result.detail as ValidationResult);
        throw new Error("发布校验未通过");
      }
      setStatusLine(`已发布 v${result.version}，可进入对话体验`);
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
    const terminalStatuses = new Set(["completed", "failed", "cancelled", "waiting_approval"]);
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const response = await fetchWithTimeout(`${apiBaseUrl}/runs/${runId}`, { cache: "no-store" });
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

  const submitHumanApprovalTask = async (
    task: HumanApprovalTask,
    decision: "approve" | "reject",
    options: { waitForRun?: boolean } = {},
  ) => {
    const parsedResponse = parseJsonObject(
      approvalResponseDrafts[task.id] ?? stringifyJson({ approved: decision === "approve" }),
    );
    if (parsedResponse.error) {
      setApprovalError(parsedResponse.error);
      setStatusLine("审批响应不是合法 JSON 对象");
      return false;
    }

    setBusyAction(`approval-${decision}-${task.id}`);
    setApprovalError(null);
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/human-approval-tasks/${task.id}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          response: parsedResponse.value ?? {},
          comment: approvalCommentDrafts[task.id]?.trim() || null,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        const detail = result && typeof result === "object" ? (result as { detail?: unknown }).detail : null;
        const message =
          typeof detail === "string"
            ? detail
            : detail && typeof detail === "object" && "message" in detail
              ? String((detail as { message?: unknown }).message)
              : `POST /human-approval-tasks/${task.id}/submit ${response.status}`;
        throw new Error(message);
      }

      setHumanApprovalTasks((items) => items.filter((item) => item.id !== task.id));
      setApprovalCenterTasks((items) => items.filter((item) => item.id !== task.id));
      setSelectedApprovalTaskIds((selectedIds) => {
        const nextIds = new Set(selectedIds);
        nextIds.delete(task.id);
        return nextIds;
      });
      if (options.waitForRun ?? true) {
        setStatusLine(`审批已提交：${decision === "approve" ? "同意" : "拒绝"}，等待运行恢复`);
        await pollRunUntilTerminal(task.run_id);

        const traceResponse = await fetchWithTimeout(`${apiBaseUrl}/runs/${task.run_id}/trace`, { cache: "no-store" });
        if (!traceResponse.ok) {
          throw new Error(`GET /runs/${task.run_id}/trace ${traceResponse.status}`);
        }
        const nextTrace = (await traceResponse.json()) as RunTrace;
        setTrace(nextTrace);
        setInspectorTab(nextTrace.run.status === "waiting_approval" ? "run" : "trace");
        setStatusLine(`审批后运行 #${task.run_id} · ${nextTrace.run.status}`);
        const firstFailedNode = nextTrace.nodes.find((node) => node.status === "failed");
        if (firstFailedNode) {
          focusNode(firstFailedNode.node_id);
        }
      } else {
        setStatusLine(`审批已提交：${decision === "approve" ? "同意" : "拒绝"}，运行已重新入队`);
      }
      if (activeSection === "approvals") {
        await loadApprovalCenterTasks();
      }
      if (selectedWorkflow) {
        await loadRuns(selectedWorkflow.id);
      }
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "审批提交失败";
      setApprovalError(message);
      setStatusLine(message);
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const submitSelectedApprovalTasks = async (decision: "approve" | "reject") => {
    if (selectedPendingApprovalTasks.length === 0) {
      setApprovalCenterError("请选择 pending 审批任务");
      return;
    }

    const payloads = selectedPendingApprovalTasks.map((task) => {
      const parsedResponse = parseJsonObject(
        approvalResponseDrafts[task.id] ?? stringifyJson({ approved: decision === "approve" }),
      );
      return { task, parsedResponse };
    });
    const invalid = payloads.find(({ parsedResponse }) => parsedResponse.error);
    if (invalid) {
      const message = `#${invalid.task.id} 响应 JSON 无效：${invalid.parsedResponse.error}`;
      setApprovalCenterError(message);
      setStatusLine(message);
      return;
    }

    setBusyAction(`approval-bulk-${decision}`);
    setApprovalCenterError(null);
    setApprovalError(null);
    try {
      let submittedCount = 0;
      for (const { task, parsedResponse } of payloads) {
        const response = await fetchWithTimeout(`${apiBaseUrl}/human-approval-tasks/${task.id}/submit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            response: parsedResponse.value ?? {},
            comment: approvalCommentDrafts[task.id]?.trim() || null,
          }),
        });
        const result = await response.json();
        if (!response.ok) {
          const detail = result && typeof result === "object" ? (result as { detail?: unknown }).detail : null;
          const message =
            typeof detail === "string"
              ? detail
              : detail && typeof detail === "object" && "message" in detail
                ? String((detail as { message?: unknown }).message)
                : `POST /human-approval-tasks/${task.id}/submit ${response.status}`;
          throw new Error(`#${task.id} ${message}`);
        }
        submittedCount += 1;
      }
      setSelectedApprovalTaskIds(new Set());
      setStatusLine(`已批量${decision === "approve" ? "同意" : "拒绝"} ${submittedCount} 个审批任务`);
      await loadApprovalCenterTasks();
      if (selectedWorkflow) {
        await loadRuns(selectedWorkflow.id);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "批量审批提交失败";
      setApprovalCenterError(message);
      setStatusLine(message);
    } finally {
      setBusyAction(null);
    }
  };

  const cancelHumanApprovalTask = async (
    task: HumanApprovalTask,
    options: { refreshTrace?: boolean } = {},
  ) => {
    setBusyAction(`approval-cancel-${task.id}`);
    setApprovalError(null);
    setApprovalCenterError(null);
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/human-approval-tasks/${task.id}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: approvalCommentDrafts[task.id]?.trim() || null,
        }),
      });
      const result = (await response.json()) as HumanApprovalTask & { run_cancelled?: boolean };
      if (!response.ok) {
        const detail = result && typeof result === "object" ? (result as { detail?: unknown }).detail : null;
        const message =
          typeof detail === "string"
            ? detail
            : detail && typeof detail === "object" && "message" in detail
              ? String((detail as { message?: unknown }).message)
              : `POST /human-approval-tasks/${task.id}/cancel ${response.status}`;
        throw new Error(message);
      }

      setHumanApprovalTasks((items) => items.filter((item) => item.id !== task.id));
      setApprovalCenterTasks((items) => items.filter((item) => item.id !== task.id));
      setSelectedApprovalTaskIds((selectedIds) => {
        const nextIds = new Set(selectedIds);
        nextIds.delete(task.id);
        return nextIds;
      });
      setStatusLine(`审批任务 #${task.id} 已取消${result.run_cancelled ? "，运行已取消" : ""}`);

      if ((options.refreshTrace ?? true) && trace && getRunId(trace.run) === task.run_id) {
        const traceResponse = await fetchWithTimeout(`${apiBaseUrl}/runs/${task.run_id}/trace`, { cache: "no-store" });
        if (!traceResponse.ok) {
          throw new Error(`GET /runs/${task.run_id}/trace ${traceResponse.status}`);
        }
        const nextTrace = (await traceResponse.json()) as RunTrace;
        setTrace(nextTrace);
        setInspectorTab(nextTrace.run.status === "waiting_approval" ? "run" : "trace");
      }
      if (activeSection === "approvals") {
        await loadApprovalCenterTasks();
      }
      if (selectedWorkflow) {
        await loadRuns(selectedWorkflow.id);
      }
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "审批取消失败";
      setApprovalError(message);
      setApprovalCenterError(message);
      setStatusLine(message);
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const cancelSelectedApprovalTasks = async () => {
    if (selectedPendingApprovalTasks.length === 0) {
      setApprovalCenterError("请选择 pending 审批任务");
      return;
    }

    setBusyAction("approval-bulk-cancel");
    setApprovalCenterError(null);
    setApprovalError(null);
    try {
      let cancelledCount = 0;
      let runCancelledCount = 0;
      for (const task of selectedPendingApprovalTasks) {
        const response = await fetchWithTimeout(`${apiBaseUrl}/human-approval-tasks/${task.id}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            reason: approvalCommentDrafts[task.id]?.trim() || null,
          }),
        });
        const result = (await response.json()) as HumanApprovalTask & { run_cancelled?: boolean };
        if (!response.ok) {
          const detail = result && typeof result === "object" ? (result as { detail?: unknown }).detail : null;
          const message =
            typeof detail === "string"
              ? detail
              : detail && typeof detail === "object" && "message" in detail
                ? String((detail as { message?: unknown }).message)
                : `POST /human-approval-tasks/${task.id}/cancel ${response.status}`;
          throw new Error(`#${task.id} ${message}`);
        }
        cancelledCount += 1;
        if (result.run_cancelled) {
          runCancelledCount += 1;
        }
      }
      setSelectedApprovalTaskIds(new Set());
      setStatusLine(`已取消 ${cancelledCount} 个审批任务，${runCancelledCount} 个运行已取消`);
      await loadApprovalCenterTasks();
      if (selectedWorkflow) {
        await loadRuns(selectedWorkflow.id);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "批量取消审批失败";
      setApprovalCenterError(message);
      setStatusLine(message);
    } finally {
      setBusyAction(null);
    }
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
    let versionForRun = currentVersionDetail;
    if (selectedWorkflow.current_version_id) {
      try {
        versionForRun = await refreshCurrentVersionDetail();
      } catch (error) {
        setStatusLine(error instanceof Error ? error.message : "发布代码状态检查失败");
      }
    }
    if (versionForRun?.code_modified === true) {
      const shouldRun = window.confirm(
        "当前版本的本地 workflow.py hash 与发布记录不一致。继续运行会以本地代码为准，并在 trace 中记录 code_modified=true。",
      );
      if (!shouldRun) {
        setStatusLine("已取消运行：本地代码 hash 已变更");
        return false;
      }
    }

    setBusyAction("run");
    try {
      const response = await fetchWithTimeout(`${apiBaseUrl}/workflows/${selectedWorkflow.id}/run`, {
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
        throw new Error(readApiErrorMessage(result, `POST /run ${response.status}`));
      }
      if (runMode === "async") {
        setStatusLine(`异步运行已提交 #${result.run_id}，等待完成`);
        await pollRunUntilTerminal(result.run_id);
      }
      const traceResponse = await fetchWithTimeout(`${apiBaseUrl}/runs/${result.run_id}/trace`, {
        cache: "no-store",
      });
      if (!traceResponse.ok) {
        throw new Error(`GET /runs/${result.run_id}/trace ${traceResponse.status}`);
      }
      const nextTrace = (await traceResponse.json()) as RunTrace;
      setTrace(nextTrace);
      setInspectorTab(nextTrace.run.status === "waiting_approval" ? "run" : "trace");
      const runtimeHint = nextTrace.run.error_code
        ? formatRuntimeError(nextTrace.run.error_code, nextTrace.run.error_message)
        : null;
      setStatusLine(
        runtimeHint
          ? `${runMode === "async" ? "异步" : "同步"}运行失败 #${result.run_id} · ${runtimeHint}`
          : `${runMode === "async" ? "异步" : "同步"}运行完成 #${result.run_id} · ${nextTrace.run.status}`,
      );
      const firstFailedNode = nextTrace.nodes.find((node) => node.status === "failed");
      if (firstFailedNode) {
        focusNode(firstFailedNode.node_id);
      }
      const listResponse = await fetchWithTimeout(`${apiBaseUrl}/workflows`, { cache: "no-store" });
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
    (type: NodeType, position?: { x: number; y: number }) => {
      const template = nodeCatalog.find((item) => item.type === type);
      if (!template) {
        return;
      }

      const sameTypeCount = graph.nodes.filter((node) => node.type === type).length;
      const nextNode = createGraphNode(template, sameTypeCount + 1, graph.nodes.length, position);
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

  const addNodeAtClientPoint = useCallback(
    (type: NodeType, clientX: number, clientY: number) => {
      const position = flowInstance?.screenToFlowPosition({ x: clientX, y: clientY });
      addNode(
        type,
        position
          ? {
              x: Math.round(position.x - 75),
              y: Math.round(position.y - 30),
            }
          : undefined,
      );
    },
    [addNode, flowInstance],
  );

  const onNodeMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLButtonElement>, type: NodeType) => {
      if (event.button !== 0 || !selectedWorkflow || busyAction !== null) {
        return;
      }

      event.preventDefault();
      mouseDragRef.current = { type, startX: event.clientX, startY: event.clientY };

      const onMouseMove = (mouseEvent: MouseEvent) => {
        const drag = mouseDragRef.current;
        if (!drag) {
          return;
        }

        const moved = Math.hypot(mouseEvent.clientX - drag.startX, mouseEvent.clientY - drag.startY);
        if (moved < nodeDropMoveThreshold) {
          return;
        }

        setNodeDragPreview({
          type: drag.type,
          x: mouseEvent.clientX,
          y: mouseEvent.clientY,
          overCanvas: isClientPointInsideElement(canvasRef.current, mouseEvent.clientX, mouseEvent.clientY),
        });
      };

      const onMouseUp = (mouseEvent: MouseEvent) => {
        const drag = mouseDragRef.current;
        mouseDragRef.current = null;
        setNodeDragPreview(null);
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);

        if (!drag) {
          return;
        }

        const moved = Math.hypot(mouseEvent.clientX - drag.startX, mouseEvent.clientY - drag.startY);
        if (moved < nodeDropMoveThreshold) {
          return;
        }

        ignoreNextNodeClickRef.current = true;
        const canvasRect = canvasRef.current?.getBoundingClientRect();
        const droppedOnCanvas =
          canvasRect &&
          mouseEvent.clientX >= canvasRect.left &&
          mouseEvent.clientX <= canvasRect.right &&
          mouseEvent.clientY >= canvasRect.top &&
          mouseEvent.clientY <= canvasRect.bottom;

        if (!droppedOnCanvas) {
          setStatusLine("请把节点拖到画布区域内释放");
          return;
        }

        addNodeAtClientPoint(drag.type, mouseEvent.clientX, mouseEvent.clientY);
      };

      window.addEventListener("mouseup", onMouseUp);
      window.addEventListener("mousemove", onMouseMove);
    },
    [addNodeAtClientPoint, busyAction, selectedWorkflow],
  );

  const onNodeButtonClick = useCallback(
    (type: NodeType) => {
      if (ignoreNextNodeClickRef.current) {
        ignoreNextNodeClickRef.current = false;
        return;
      }
      addNode(type);
    },
    [addNode],
  );

  const applyDeepSeekQaDemoTemplate = useCallback(() => {
    if (!selectedWorkflow) {
      return;
    }
    if (
      (graph.nodes.length > 0 || graph.edges.length > 0) &&
      !window.confirm("DeepSeek 问答模板会替换当前画布草稿，是否继续？")
    ) {
      setStatusLine("已取消套用 DeepSeek 问答模板，当前草稿未改变");
      return;
    }

    setGraph(createDeepSeekQaDemoGraph());
    setSelectedNodeId("llm_1");
    setRunInput(JSON.stringify({ rawQuery: "用三句话解释这个工作流平台的用途" }, null, 2));
    setValidation(null);
    setTrace(null);
    setStatusLine("已生成 DeepSeek 问答草稿；存在 DEEPSEEK_API_KEY 时可真实调用，否则建议测试使用 mock 路径");
  }, [graph.edges.length, graph.nodes.length, selectedWorkflow]);

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
        const response = await fetchWithTimeout(`${apiBaseUrl}/knowledge-bases`, { cache: "no-store" });
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
    setRunInput(JSON.stringify({ rawQuery: "refund billing policy" }, null, 2));
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
    setRunInput(JSON.stringify({ rawQuery: "refund_request 用户申请退款" }, null, 2));
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
    setRunInput(JSON.stringify({ rawQuery: "查询订单状态", order_id: "A-1001" }, null, 2));
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

    setFlowNodes((currentNodes) => {
      const nextNodes = applyNodeChanges(changes, currentNodes);
      const removedIds = new Set(
        changes
          .filter((change) => nodeChangeHasId(change) && change.type === "remove")
          .map((change) => change.id),
      );
      const hasPositionChange = changes.some((change) => nodeChangeHasId(change) && change.type === "position");

      if (removedIds.size > 0 || hasPositionChange) {
        const flowNodeById = new Map(nextNodes.map((node) => [node.id, node]));
        setGraph((currentGraph) => ({
          ...currentGraph,
          nodes: currentGraph.nodes
            .filter((node) => !removedIds.has(node.id))
            .map((node) => {
              const flowNode = flowNodeById.get(node.id);
              return flowNode ? { ...node, position: flowNode.position } : node;
            }),
          edges: currentGraph.edges.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)),
        }));
      }

      if (removedIds.size > 0) {
        setSelectedEdgeId(null);
        setTrace(null);
      }
      return nextNodes;
    });
  }, []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <section className="brand">
          <p className="eyebrow">Agent Flow</p>
          <h1>工作流控制台</h1>
        </section>

        <nav className="main-nav" aria-label="管理入口">
          {navigationSections.map(({ id, label, Icon }) => (
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
            onClick={() => applyDeepSeekQaDemoTemplate()}
            disabled={!selectedWorkflow || busyAction !== null}
          >
            <Bot size={16} />
            DeepSeek 问答
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
                    onClick={() => onNodeButtonClick(type)}
                    onMouseDown={(event) => onNodeMouseDown(event, type)}
                    disabled={!selectedWorkflow || busyAction !== null}
                    title="拖到画布，或点击添加"
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
            <strong>{navigationSections.find((section) => section.id === activeSection)?.label}</strong>
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
            <a
              className="icon-button"
              href={selectedWorkflow?.current_version_id ? `/chat?workflow_id=${selectedWorkflow.id}` : "/chat"}
            >
              <MessageSquare size={16} />
              去对话
            </a>
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

        <VersionCodePanel
          busy={busyAction !== null}
          cleanupReport={generatedCleanupReport}
          code={currentVersionCode}
          codeVisible={showCurrentVersionCode}
          onCleanupGenerated={cleanupGeneratedWorkflowDirs}
          onLoadCode={loadCurrentVersionCode}
          onRegenerateCode={regenerateVersionCode}
          onToggleCode={() => setShowCurrentVersionCode((visible) => !visible)}
          selectedCodeVersion={selectedCodeVersion}
          version={currentVersionDetail}
          versions={workflowVersions}
          workflow={selectedWorkflow}
        />

        <section className="designer">
          <div className={nodeDragPreview?.overCanvas ? "canvas-flow dropping" : "canvas-flow"} ref={canvasRef}>
            <ReactFlow
              nodes={flowNodes}
              edges={emptyFlowEdges}
              nodeTypes={workflowNodeTypes}
              onInit={setFlowInstance}
              onNodesChange={onNodesChange}
              onNodeClick={(_, node) => selectGraphNode(node.id)}
              onPaneClick={clearCanvasSelection}
              deleteKeyCode={["Backspace", "Delete"]}
              fitView
            >
              <WorkflowEdgeOverlay
                deleteEdge={deleteGraphEdge}
                graph={graph}
                nodeEdgeAnchors={nodeEdgeAnchors}
                pendingConnection={pendingConnection}
                selectedEdgeId={selectedEdgeId}
                selectEdge={(edgeId) => {
                  setSelectedEdgeId(edgeId);
                  setSelectedNodeId(null);
                  setInspectorTab("config");
                }}
              />
              <Background />
              <MiniMap pannable zoomable />
              <Controls />
            </ReactFlow>
          </div>
          {nodeDragPreview ? <NodeDragPreviewLayer preview={nodeDragPreview} /> : null}

          <aside className="inspector">
            <div className="panel-tabs" aria-label="编辑器面板">
              {(["config", "run", "trace"] as InspectorTab[]).map((tab) => (
                <button
                  className={inspectorTab === tab ? "active" : ""}
                  key={tab}
                  onClick={() => setInspectorTab(tab)}
                  type="button"
                >
                  {tab === "config" ? "配置" : tab === "run" ? "运行" : "Trace"}
                </button>
              ))}
            </div>

            {inspectorTab === "config" ? (
              <>
                <section className="node-config-box">
                  <div className="section-heading">
                    <SquareTerminal size={16} />
                    {selectedEdge ? "连线配置" : "节点配置"}
                  </div>
                  {selectedNode ? (
                    <NodeConfigPanel
                      graph={graph}
                      knowledgeBases={knowledgeBases}
                      modelConfigs={modelConfigs}
                      node={selectedNode}
                      nodeJsonDrafts={nodeJsonDrafts}
                      nodeJsonErrors={nodeJsonErrors}
                      onConfigChange={updateSelectedNodeConfig}
                      onNodeJsonChange={updateSelectedNodeJson}
                      onNodePatch={updateSelectedNode}
                      tools={tools}
                    />
                  ) : selectedEdge ? (
                    <div className="node-form edge-form">
                      <div className="edge-endpoints">
                        <span>{selectedEdgeEndpoints?.source?.name ?? selectedEdge.source}</span>
                        <strong>→</strong>
                        <span>{selectedEdgeEndpoints?.target?.name ?? selectedEdge.target}</span>
                      </div>
                      <label>
                        <span>label</span>
                        <input
                          value={selectedEdge.label ?? ""}
                          onChange={(event) => updateSelectedEdge({ label: event.target.value || undefined })}
                          placeholder="branch / condition"
                        />
                      </label>
                      <button className="icon-button danger" onClick={() => deleteGraphEdge(selectedEdge.id)} type="button">
                        <Trash2 size={16} />
                        删除连线
                      </button>
                    </div>
                  ) : (
                    <p className="empty">选择画布节点后编辑配置</p>
                  )}
                </section>

                <section className="result-box">
                  <div className="section-heading">
                    <FileJson size={16} />
                    校验结果
                  </div>
                  {validation ? (
                    <ValidationView validation={validation} onSelectNode={focusNode} />
                  ) : (
                    <p className="empty">等待校验</p>
                  )}
                </section>
              </>
            ) : null}

            {inspectorTab === "run" ? (
              <>
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
                  <div className="run-preflight">
                    <div>
                      <span>运行版本</span>
                      <strong>{runVersionLabel}</strong>
                    </div>
                    <div>
                      <span>本地代码</span>
                      <strong className={runCodeModified ? "warning-text" : ""}>{runCodeStatus}</strong>
                    </div>
                    <div>
                      <span>代码 Hash</span>
                      <code title={currentVersionDetail?.code_hash ?? undefined}>{runCodeHash}</code>
                    </div>
                  </div>
                  {runCodeModified ? (
                    <p className="run-preflight-warning">
                      本地 workflow.py 已改动，本次运行会执行本地文件，并在 Trace 记录 code_modified=true。
                    </p>
                  ) : null}
                  {runCodePath ? (
                    <small className="run-code-path" title={runCodePath}>
                      代码路径：{runCodePath}
                    </small>
                  ) : null}
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

                {trace?.run.status === "waiting_approval" ? (
                  <section className="approval-box">
                    <div className="approval-box-header">
                      <div className="section-heading">
                        <UserCheck size={16} />
                        待人工审批
                      </div>
                      <button
                        className="text-button"
                        onClick={() => {
                          const runId = getRunId(trace.run);
                          if (runId) {
                            void loadPendingApprovalTasks(runId).catch((error) => {
                              setApprovalError(error instanceof Error ? error.message : "待审批任务同步失败");
                            });
                          }
                        }}
                        disabled={busyAction !== null}
                        type="button"
                      >
                        同步
                      </button>
                    </div>
                    {approvalError ? <small className="error-text">{approvalError}</small> : null}
                    {humanApprovalTasks.length > 0 ? (
                      <div className="approval-list">
                        {humanApprovalTasks.map((task) => (
                          <article className="approval-card" key={task.id}>
                            <div className="approval-card-header">
                              <div>
                                <strong>{task.title}</strong>
                                <span>{task.node_name || task.node_id}</span>
                              </div>
                              <small>#{task.id} · {formatDate(task.created_at)}</small>
                            </div>
                            {task.description ? <p>{task.description}</p> : null}
                            <label className="approval-field">
                              <span>审批输入</span>
                              <pre>{stringifyJson(task.input_json ?? {})}</pre>
                            </label>
                            <label className="approval-field" htmlFor={`approval-comment-${task.id}`}>
                              <span>备注</span>
                              <textarea
                                id={`approval-comment-${task.id}`}
                                value={approvalCommentDrafts[task.id] ?? ""}
                                onChange={(event) =>
                                  setApprovalCommentDrafts((drafts) => ({
                                    ...drafts,
                                    [task.id]: event.target.value,
                                  }))
                                }
                                placeholder="可选"
                              />
                            </label>
                            <label className="approval-field" htmlFor={`approval-response-${task.id}`}>
                              <span>响应 JSON</span>
                              <textarea
                                id={`approval-response-${task.id}`}
                                value={approvalResponseDrafts[task.id] ?? stringifyJson({})}
                                onChange={(event) => {
                                  setApprovalResponseDrafts((drafts) => ({
                                    ...drafts,
                                    [task.id]: event.target.value,
                                  }));
                                  setApprovalError(null);
                                }}
                                spellCheck={false}
                              />
                            </label>
                            <div className="approval-actions">
                              <button
                                className="icon-button primary"
                                type="button"
                                onClick={() => void submitHumanApprovalTask(task, "approve")}
                                disabled={busyAction !== null}
                              >
                                <CheckCircle2 size={16} />
                                同意
                              </button>
                              <button
                                className="icon-button danger"
                                type="button"
                                onClick={() => void submitHumanApprovalTask(task, "reject")}
                                disabled={busyAction !== null}
                              >
                                <XCircle size={16} />
                                拒绝
                              </button>
                              <button
                                className="icon-button danger"
                                type="button"
                                onClick={() => void cancelHumanApprovalTask(task)}
                                disabled={busyAction !== null}
                              >
                                <Ban size={16} />
                                取消任务
                              </button>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className="empty">当前运行正在等待审批任务同步</p>
                    )}
                  </section>
                ) : null}

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
              </>
            ) : null}

            {inspectorTab === "trace" ? (
              <section className="result-box">
                <div className="section-heading">
                  <Activity size={16} />
                  运行 Trace
                </div>
                {trace ? <TraceView trace={trace} onSelectNode={focusNode} /> : <p className="empty">等待运行</p>}
              </section>
            ) : null}
          </aside>
        </section>
          </>
        ) : null}

        {activeSection === "approvals" ? (
          <section className="admin-page">
            <AdminHeader
              eyebrow="Approvals"
              title="人工审批"
              description="集中查看等待人工确认的 workflow run，并提交 approve/reject 让 worker 继续执行。"
              onRefresh={() => void loadApprovalCenterTasks()}
              busy={busyAction !== null}
            />
            <section className="admin-panel approval-center">
              <div className="approval-toolbar">
                <div className="segmented-control" aria-label="审批状态筛选">
                  {approvalStatusOptions.map((status) => (
                    <button
                      className={approvalCenterStatus === status ? "active" : ""}
                      key={status}
                      type="button"
                      onClick={() => setApprovalCenterStatus(status)}
                    >
                      {approvalStatusLabels[status]}
                    </button>
                  ))}
                </div>
                <span>{approvalCenterTotal} 条</span>
              </div>
              {pendingApprovalCenterTasks.length > 0 ? (
                <div className="approval-bulk-bar">
                  <label>
                    <input
                      type="checkbox"
                      checked={selectedPendingApprovalTasks.length === pendingApprovalCenterTasks.length}
                      onChange={(event) =>
                        setSelectedApprovalTaskIds(
                          event.target.checked ? new Set(pendingApprovalCenterTasks.map((task) => task.id)) : new Set(),
                        )
                      }
                    />
                    <span>选择当前 pending</span>
                  </label>
                  <small>
                    已选择 {selectedPendingApprovalTasks.length} / {pendingApprovalCenterTasks.length}
                  </small>
                  <div className="approval-actions">
                    <button
                      className="icon-button primary"
                      type="button"
                      onClick={() => void submitSelectedApprovalTasks("approve")}
                      disabled={busyAction !== null || selectedPendingApprovalTasks.length === 0}
                    >
                      <CheckCircle2 size={16} />
                      批量同意
                    </button>
                    <button
                      className="icon-button danger"
                      type="button"
                      onClick={() => void submitSelectedApprovalTasks("reject")}
                      disabled={busyAction !== null || selectedPendingApprovalTasks.length === 0}
                    >
                      <XCircle size={16} />
                      批量拒绝
                    </button>
                    <button
                      className="icon-button danger"
                      type="button"
                      onClick={() => void cancelSelectedApprovalTasks()}
                      disabled={busyAction !== null || selectedPendingApprovalTasks.length === 0}
                    >
                      <Ban size={16} />
                      批量取消
                    </button>
                  </div>
                </div>
              ) : null}
              {approvalCenterError ? <small className="error-text">{approvalCenterError}</small> : null}
              {approvalCenterTasks.length > 0 ? (
                <div className="approval-list">
                  {approvalCenterTasks.map((task) => {
                    const statusLabel =
                      approvalStatusLabels[task.status as HumanApprovalTaskStatus] ?? task.status ?? "-";
                    return (
                      <article className="approval-card" key={task.id}>
                        <div className="approval-card-header">
                          {task.status === "pending" ? (
                            <input
                              aria-label={`选择审批任务 ${task.id}`}
                              checked={selectedApprovalTaskIds.has(task.id)}
                              type="checkbox"
                              onChange={(event) =>
                                setSelectedApprovalTaskIds((selectedIds) => {
                                  const nextIds = new Set(selectedIds);
                                  if (event.target.checked) {
                                    nextIds.add(task.id);
                                  } else {
                                    nextIds.delete(task.id);
                                  }
                                  return nextIds;
                                })
                              }
                            />
                          ) : null}
                          <div>
                            <strong>{task.title}</strong>
                            <span>
                              workflow #{task.workflow_id} · run #{task.run_id} · {task.node_name || task.node_id}
                            </span>
                          </div>
                          <small className={`approval-status approval-status-${task.status}`}>{statusLabel}</small>
                        </div>
                        {task.description ? <p>{task.description}</p> : null}
                        <label className="approval-field">
                          <span>审批输入</span>
                          <pre>{stringifyJson(task.input_json ?? {})}</pre>
                        </label>
                        {task.status === "pending" ? (
                          <>
                            <label className="approval-field" htmlFor={`approval-center-comment-${task.id}`}>
                              <span>备注</span>
                              <textarea
                                id={`approval-center-comment-${task.id}`}
                                value={approvalCommentDrafts[task.id] ?? ""}
                                onChange={(event) =>
                                  setApprovalCommentDrafts((drafts) => ({
                                    ...drafts,
                                    [task.id]: event.target.value,
                                  }))
                                }
                                placeholder="可选"
                              />
                            </label>
                            <label className="approval-field" htmlFor={`approval-center-response-${task.id}`}>
                              <span>响应 JSON</span>
                              <textarea
                                id={`approval-center-response-${task.id}`}
                                value={approvalResponseDrafts[task.id] ?? stringifyJson({})}
                                onChange={(event) => {
                                  setApprovalResponseDrafts((drafts) => ({
                                    ...drafts,
                                    [task.id]: event.target.value,
                                  }));
                                  setApprovalCenterError(null);
                                }}
                                spellCheck={false}
                              />
                            </label>
                            <div className="approval-actions">
                              <button
                                className="icon-button primary"
                                type="button"
                                onClick={() =>
                                  void submitHumanApprovalTask(task, "approve", {
                                    waitForRun: false,
                                  })
                                }
                                disabled={busyAction !== null}
                              >
                                <CheckCircle2 size={16} />
                                同意
                              </button>
                              <button
                                className="icon-button danger"
                                type="button"
                                onClick={() =>
                                  void submitHumanApprovalTask(task, "reject", {
                                    waitForRun: false,
                                  })
                                }
                                disabled={busyAction !== null}
                              >
                                <XCircle size={16} />
                                拒绝
                              </button>
                              <button
                                className="icon-button danger"
                                type="button"
                                onClick={() =>
                                  void cancelHumanApprovalTask(task, {
                                    refreshTrace: false,
                                  })
                                }
                                disabled={busyAction !== null}
                              >
                                <Ban size={16} />
                                取消任务
                              </button>
                            </div>
                          </>
                        ) : (
                          <label className="approval-field">
                            <span>审批结果</span>
                            <pre>{stringifyJson(task.response_json ?? {})}</pre>
                          </label>
                        )}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <p className="empty">暂无审批任务</p>
              )}
            </section>
          </section>
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
                <div className="inline-fields">
                  <label>
                    <span>provider</span>
                    <select
                      value={knowledgeForm.embedding_provider}
                      onChange={(event) =>
                        setKnowledgeForm((form) => ({ ...form, embedding_provider: event.target.value }))
                      }
                    >
                      <option value="local">local</option>
                      <option value="openai">openai</option>
                    </select>
                  </label>
                  <label>
                    <span>tokenizer</span>
                    <input
                      readOnly
                      value={knowledgeForm.tokenizer}
                      onChange={(event) => setKnowledgeForm((form) => ({ ...form, tokenizer: event.target.value }))}
                    />
                  </label>
                </div>
                <div className="inline-fields">
                  <label>
                    <span>chunk_size_tokens</span>
                    <input
                      min={1}
                      required
                      type="number"
                      value={knowledgeForm.chunk_size_tokens}
                      onChange={(event) =>
                        setKnowledgeForm((form) => ({ ...form, chunk_size_tokens: event.target.value }))
                      }
                    />
                  </label>
                  <label>
                    <span>chunk_overlap_tokens</span>
                    <input
                      min={0}
                      required
                      type="number"
                      value={knowledgeForm.chunk_overlap_tokens}
                      onChange={(event) =>
                        setKnowledgeForm((form) => ({ ...form, chunk_overlap_tokens: event.target.value }))
                      }
                    />
                  </label>
                </div>
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
                      <small>
                        docs {kb.indexed_document_count ?? 0}/{kb.document_count ?? 0} · chunks {kb.chunk_count ?? 0}
                      </small>
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
                {selectedKnowledgeBase ? (
                  <div className="chunk-card">
                    <div>
                      <strong>{selectedKnowledgeBase.name}</strong>
                      <small>
                        provider {String(selectedKnowledgeBase.config_json?.embedding_provider ?? "-")} · tokenizer{" "}
                        {selectedKnowledgeBase.tokenizer ?? "-"}
                      </small>
                      <small>
                        chunk {String(selectedKnowledgeBase.config_json?.chunk_size_tokens ?? "-")} / overlap{" "}
                        {String(selectedKnowledgeBase.config_json?.chunk_overlap_tokens ?? "-")}
                      </small>
                    </div>
                  </div>
                ) : null}
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
                <label>
                  <span>context_budget_tokens</span>
                  <input
                    min={1}
                    type="number"
                    value={retrieveForm.context_budget_tokens}
                    onChange={(event) =>
                      setRetrieveForm((form) => ({ ...form, context_budget_tokens: event.target.value }))
                    }
                  />
                </label>
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
                        <small>
                          mode {chunk.retrieval_mode ?? "-"} · tokens {chunk.token_count ?? "-"}
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
              {hasProcessingKnowledgeDocuments ? (
                <p className="empty">文档正在处理，列表会自动刷新。</p>
              ) : null}
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

        {activeSection === "ops" ? (
          <section className="admin-page">
            <AdminHeader
              eyebrow="Operations"
              title="Ops"
              description="查看队列、worker 和 workflow_runs dead-letter，并执行最小恢复操作。"
              onRefresh={loadOps}
              busy={busyAction !== null}
            />

            <section className="metric-strip">
              <div>
                <span>Queues</span>
                <strong>{opsQueues.length}</strong>
              </div>
              <div>
                <span>Workers</span>
                <strong>{opsWorkers.length}</strong>
              </div>
              <div>
                <span>workflow_runs dead</span>
                <strong>{opsDeadCount}</strong>
              </div>
              <div>
                <span>failed runs</span>
                <strong>{opsFailedRuns.length}</strong>
              </div>
            </section>

            <section className="admin-grid">
              <section className="admin-panel">
                <div className="section-heading">
                  <Database size={16} />
                  Queues
                </div>
                {opsQueues.length > 0 ? (
                  <div className="data-table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Queue</th>
                          <th>Ready</th>
                          <th>Active</th>
                          <th>Delayed</th>
                          <th>Dead</th>
                        </tr>
                      </thead>
                      <tbody>
                        {opsQueues.map((queue, index) => (
                          <tr key={`${readText(queue, ["name", "queue", "queue_name"], "queue")}-${index}`}>
                            <td>{readText(queue, ["name", "queue", "queue_name"])}</td>
                            <td>{readNumber(queue, ["main_depth", "ready", "queued", "pending"])}</td>
                            <td>{readNumber(queue, ["processing_depth", "active", "running"])}</td>
                            <td>{readNumber(queue, ["delayed"])}</td>
                            <td>{readNumber(queue, ["dead_letter_depth", "dead", "failed"])}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="empty">暂无队列数据</p>
                )}
              </section>

              <section className="admin-panel">
                <div className="section-heading">
                  <Activity size={16} />
                  Workers
                </div>
                {opsWorkers.length > 0 ? (
                  <div className="data-table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Worker</th>
                          <th>Status</th>
                          <th>Queue</th>
                          <th>Current Job</th>
                          <th>Heartbeat</th>
                        </tr>
                      </thead>
                      <tbody>
                        {opsWorkers.map((worker, index) => (
                          <tr key={`${readText(worker, ["id", "worker_id", "name"], "worker")}-${index}`}>
                            <td>{readText(worker, ["name", "worker_id", "id"])}</td>
                            <td>{readText(worker, ["status"])}</td>
                            <td>{readText(worker, ["queue_name", "queue"])}</td>
                            <td>{readText(worker, ["current_job_id"])}</td>
                            <td>
                              {formatDate(
                                (worker.last_seen_at ?? worker.heartbeat_at ?? worker.updated_at) as
                                  | string
                                  | null
                                  | undefined,
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="empty">暂无 worker 数据</p>
                )}
              </section>
            </section>

            <section className="admin-panel">
              <div className="section-heading">
                <RotateCcw size={16} />
                Failed workflow_runs
              </div>
              {opsFailedRuns.length > 0 ? (
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Run</th>
                        <th>Workflow</th>
                        <th>Status</th>
                        <th>Error</th>
                        <th>Updated</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {opsFailedRuns.map((run, index) => {
                        const runId = readText(run, ["run_id", "id"], `#${index + 1}`);
                        const rawRunId = run.run_id ?? run.id ?? runId;
                        return (
                          <tr key={`${runId}-${index}`}>
                            <td>{runId}</td>
                            <td>
                              {readText(run, ["workflow_id"])} / v
                              {readText(run, ["workflow_version_id", "version_id"])}
                            </td>
                            <td>{readText(run, ["status"])}</td>
                            <td title={readText(run, ["error_message"], "")}>
                              {readText(run, ["error_code"], "unknown")}
                            </td>
                            <td>{formatDate((run.updated_at ?? run.created_at) as string | null | undefined)}</td>
                            <td>
                              <button
                                className="text-button"
                                disabled={busyAction !== null}
                                onClick={() => void recoverWorkflowRun(rawRunId)}
                                type="button"
                              >
                                恢复
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="empty">暂无 failed workflow_runs</p>
              )}
            </section>

            <section className="admin-panel">
              <div className="section-heading">
                <RotateCcw size={16} />
                workflow_runs Dead Letter
              </div>
              <div className="table-actions">
                <button
                  className="icon-button primary"
                  onClick={() => void recoverWorkflowRunsQueue()}
                  disabled={busyAction !== null}
                  type="button"
                >
                  <RotateCcw size={16} />
                  恢复队列
                </button>
                <button className="icon-button" onClick={() => void loadOps()} disabled={busyAction !== null}>
                  <RefreshCw size={16} />
                  刷新
                </button>
              </div>
              {opsRecoverResult ? <pre className="ops-json">{opsRecoverResult}</pre> : null}
              {opsDeadJobs.length > 0 ? (
                <div className="chunk-list">
                  {opsDeadJobs.slice(0, 6).map((job, index) => (
                    <article className="chunk-card" key={`${readText(job, ["job_id", "id", "run_id"], "job")}-${index}`}>
                      <div>
                        <strong>Job {readText(job, ["job_id", "id", "run_id"], `#${index + 1}`)}</strong>
                        <small>
                          run {readText(job, ["run_id"])} · workflow {readText(job, ["workflow_id"])} ·{" "}
                          {readText(job, ["status"], "dead")}
                        </small>
                        <small>
                          failed {formatDate((job.failed_at ?? job.updated_at ?? job.created_at) as string | null | undefined)}
                        </small>
                      </div>
                      <p>{readText(job, ["error_message", "error"], "无错误摘要")}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="empty">暂无 dead jobs</p>
              )}
            </section>
          </section>
        ) : null}

        {activeSection === "models" ? (
          <section className="admin-page">
            <AdminHeader
              eyebrow="Models"
              title="Model Providers & Configs"
              description="管理模型 provider、密钥引用和可绑定到 LLM 节点的 model config。"
              onRefresh={loadModels}
              busy={busyAction !== null}
            />
            <section className="admin-grid">
              <form className="admin-form" onSubmit={createModelProvider}>
                <div className="section-heading">
                  <Database size={16} />
                  新建 Provider
                </div>
                <label>
                  <span>name</span>
                  <input
                    required
                    value={modelProviderForm.name}
                    onChange={(event) => setModelProviderForm((form) => ({ ...form, name: event.target.value }))}
                  />
                </label>
                <div className="inline-fields">
                  <label>
                    <span>type</span>
                    <select
                      value={modelProviderForm.provider_type}
                      onChange={(event) =>
                        setModelProviderForm((form) => ({ ...form, provider_type: event.target.value }))
                      }
                    >
                      <option value="mock">mock</option>
                      <option value="deepseek">deepseek</option>
                      <option value="openai">openai</option>
                      <option value="custom">custom</option>
                    </select>
                  </label>
                  <label>
                    <span>status</span>
                    <select
                      value={modelProviderForm.status}
                      onChange={(event) => setModelProviderForm((form) => ({ ...form, status: event.target.value }))}
                    >
                      <option value="active">active</option>
                      <option value="disabled">disabled</option>
                    </select>
                  </label>
                </div>
                <label>
                  <span>base_url</span>
                  <input
                    value={modelProviderForm.base_url}
                    onChange={(event) => setModelProviderForm((form) => ({ ...form, base_url: event.target.value }))}
                  />
                </label>
                <label>
                  <span>config JSON</span>
                  <textarea
                    value={modelProviderForm.config}
                    onChange={(event) => {
                      setModelProviderForm((form) => ({ ...form, config: event.target.value }));
                      setModelProviderConfigError(null);
                    }}
                    spellCheck={false}
                  />
                  {modelProviderConfigError ? <small className="error-text">{modelProviderConfigError}</small> : null}
                </label>
                <button className="icon-button primary" disabled={busyAction !== null}>
                  <Plus size={16} />
                  创建 Provider
                </button>
              </form>

              <form className="admin-form" onSubmit={createModelConfig}>
                <div className="section-heading">
                  <FileJson size={16} />
                  新建 Model Config
                </div>
                <label>
                  <span>provider</span>
                  <select
                    required
                    value={modelConfigForm.provider_id}
                    onChange={(event) => setModelConfigForm((form) => ({ ...form, provider_id: event.target.value }))}
                  >
                    <option value="">选择 Provider</option>
                    {modelProviders.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="inline-fields">
                  <label>
                    <span>model_name</span>
                    <input
                      required
                      value={modelConfigForm.model_name}
                      onChange={(event) =>
                        setModelConfigForm((form) => ({ ...form, model_name: event.target.value }))
                      }
                    />
                  </label>
                  <label>
                    <span>type</span>
                    <select
                      value={modelConfigForm.model_type}
                      onChange={(event) =>
                        setModelConfigForm((form) => ({ ...form, model_type: event.target.value }))
                      }
                    >
                      <option value="chat">chat</option>
                      <option value="embedding">embedding</option>
                      <option value="rerank">rerank</option>
                    </select>
                  </label>
                </div>
                <div className="inline-fields">
                  <label>
                    <span>display_name</span>
                    <input
                      value={modelConfigForm.display_name}
                      onChange={(event) =>
                        setModelConfigForm((form) => ({ ...form, display_name: event.target.value }))
                      }
                    />
                  </label>
                  <label>
                    <span>context_window</span>
                    <input
                      min={1}
                      type="number"
                      value={modelConfigForm.context_window}
                      onChange={(event) =>
                        setModelConfigForm((form) => ({ ...form, context_window: event.target.value }))
                      }
                    />
                  </label>
                </div>
                <label>
                  <span>default_config JSON</span>
                  <textarea
                    value={modelConfigForm.default_config}
                    onChange={(event) => {
                      setModelConfigForm((form) => ({ ...form, default_config: event.target.value }));
                      setModelConfigError(null);
                    }}
                    spellCheck={false}
                  />
                  {modelConfigError ? <small className="error-text">{modelConfigError}</small> : null}
                </label>
                <button className="icon-button primary" disabled={busyAction !== null}>
                  <Plus size={16} />
                  创建 Config
                </button>
              </form>
            </section>

            <section className="model-grid">
              {modelProviders.map((provider) => {
                const diagnostic = provider.diagnostic;
                return (
                <article className="model-provider-card" key={provider.id}>
                  <div className="model-card-heading">
                    <div>
                      <strong>{provider.name}</strong>
                      <span>
                        #{provider.id} · {provider.provider_type} · {provider.status}
                      </span>
                      <small>{provider.base_url || "no base_url"}</small>
                    </div>
                    <span className={`model-provider-health ${diagnostic?.status ?? "unknown"}`}>
                      {modelProviderDiagnosticLabel(diagnostic?.status)}
                    </span>
                  </div>
                  {diagnostic ? (
                    <div className="model-provider-diagnostic">
                      <div>
                        <span>API Key</span>
                        <strong>{diagnostic.api_key_available ? "可用" : "不可用"}</strong>
                      </div>
                      <div>
                        <span>来源</span>
                        <strong>{modelProviderKeySourceLabel(diagnostic.api_key_source)}</strong>
                      </div>
                      <div>
                        <span>引用</span>
                        <strong>{diagnostic.api_key_env ?? diagnostic.api_key_secret ?? "无"}</strong>
                      </div>
                      <small>{diagnostic.message}</small>
                    </div>
                  ) : null}
                  {provider.provider_type === "deepseek" && modelDefaults ? (
                    <div className="model-provider-defaults">
                      <span>DeepSeek 默认模型</span>
                      <strong>{modelDefaults.deepseek.model_name}</strong>
                      <small>
                        {modelDefaults.deepseek.base_url} · context {modelDefaults.deepseek.context_window}
                      </small>
                    </div>
                  ) : null}
                  <div className="edit-fields">
                    <label>
                      <span>name</span>
                      <input
                        value={modelProviderDrafts[provider.id]?.name ?? provider.name}
                        onChange={(event) =>
                          setModelProviderDrafts((drafts) => ({
                            ...drafts,
                            [provider.id]: {
                              name: event.target.value,
                              provider_type: drafts[provider.id]?.provider_type ?? provider.provider_type,
                              base_url: drafts[provider.id]?.base_url ?? provider.base_url ?? "",
                              status: drafts[provider.id]?.status ?? provider.status,
                              config: drafts[provider.id]?.config ?? stringifyJson(provider.config_json ?? {}),
                              error: null,
                            },
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>type</span>
                      <select
                        value={modelProviderDrafts[provider.id]?.provider_type ?? provider.provider_type}
                        onChange={(event) =>
                          setModelProviderDrafts((drafts) => ({
                            ...drafts,
                            [provider.id]: {
                              name: drafts[provider.id]?.name ?? provider.name,
                              provider_type: event.target.value,
                              base_url: drafts[provider.id]?.base_url ?? provider.base_url ?? "",
                              status: drafts[provider.id]?.status ?? provider.status,
                              config: drafts[provider.id]?.config ?? stringifyJson(provider.config_json ?? {}),
                              error: null,
                            },
                          }))
                        }
                      >
                        <option value="mock">mock</option>
                        <option value="deepseek">deepseek</option>
                        <option value="openai">openai</option>
                        <option value="custom">custom</option>
                      </select>
                    </label>
                  </div>
                  <div className="edit-fields">
                    <label>
                      <span>base_url</span>
                      <input
                        value={modelProviderDrafts[provider.id]?.base_url ?? provider.base_url ?? ""}
                        onChange={(event) =>
                          setModelProviderDrafts((drafts) => ({
                            ...drafts,
                            [provider.id]: {
                              name: drafts[provider.id]?.name ?? provider.name,
                              provider_type: drafts[provider.id]?.provider_type ?? provider.provider_type,
                              base_url: event.target.value,
                              status: drafts[provider.id]?.status ?? provider.status,
                              config: drafts[provider.id]?.config ?? stringifyJson(provider.config_json ?? {}),
                              error: null,
                            },
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>status</span>
                      <select
                        value={modelProviderDrafts[provider.id]?.status ?? provider.status}
                        onChange={(event) =>
                          setModelProviderDrafts((drafts) => ({
                            ...drafts,
                            [provider.id]: {
                              name: drafts[provider.id]?.name ?? provider.name,
                              provider_type: drafts[provider.id]?.provider_type ?? provider.provider_type,
                              base_url: drafts[provider.id]?.base_url ?? provider.base_url ?? "",
                              status: event.target.value,
                              config: drafts[provider.id]?.config ?? stringifyJson(provider.config_json ?? {}),
                              error: null,
                            },
                          }))
                        }
                      >
                        <option value="active">active</option>
                        <option value="disabled">disabled</option>
                      </select>
                    </label>
                  </div>
                  <label className="stacked-field">
                    <span>config JSON</span>
                    <textarea
                      value={modelProviderDrafts[provider.id]?.config ?? stringifyJson(provider.config_json ?? {})}
                      onChange={(event) =>
                        setModelProviderDrafts((drafts) => ({
                          ...drafts,
                          [provider.id]: {
                            name: drafts[provider.id]?.name ?? provider.name,
                            provider_type: drafts[provider.id]?.provider_type ?? provider.provider_type,
                            base_url: drafts[provider.id]?.base_url ?? provider.base_url ?? "",
                            status: drafts[provider.id]?.status ?? provider.status,
                            config: event.target.value,
                            error: null,
                          },
                        }))
                      }
                      spellCheck={false}
                    />
                  </label>
                  {modelProviderDrafts[provider.id]?.error ? (
                    <small className="error-text">{modelProviderDrafts[provider.id]?.error}</small>
                  ) : null}
                  <button
                    className="icon-button primary"
                    disabled={busyAction !== null}
                    onClick={() => void updateModelProvider(provider.id)}
                    type="button"
                  >
                    <Save size={16} />
                    保存 Provider
                  </button>
                  <div className="model-config-list">
                    {modelConfigs
                      .filter((config) => config.provider_id === provider.id)
                      .map((config) => (
                        <div className="model-config-row" key={config.id}>
                          <div>
                            <strong>{config.model_name}</strong>
                            <small>
                              #{config.id} · {config.model_type} · {config.status}
                            </small>
                          </div>
                          <div className="edit-fields">
                            <label>
                              <span>model_name</span>
                              <input
                                value={modelConfigDrafts[config.id]?.model_name ?? config.model_name}
                                onChange={(event) =>
                                  setModelConfigDrafts((drafts) => ({
                                    ...drafts,
                                    [config.id]: {
                                      provider_id: drafts[config.id]?.provider_id ?? String(config.provider_id),
                                      model_name: event.target.value,
                                      model_type: drafts[config.id]?.model_type ?? config.model_type,
                                      display_name: drafts[config.id]?.display_name ?? config.display_name ?? "",
                                      context_window:
                                        drafts[config.id]?.context_window ??
                                        (config.context_window ? String(config.context_window) : ""),
                                      default_config:
                                        drafts[config.id]?.default_config ?? stringifyJson(config.default_config ?? {}),
                                      status: drafts[config.id]?.status ?? config.status,
                                      error: null,
                                    },
                                  }))
                                }
                              />
                            </label>
                            <label>
                              <span>type</span>
                              <select
                                value={modelConfigDrafts[config.id]?.model_type ?? config.model_type}
                                onChange={(event) =>
                                  setModelConfigDrafts((drafts) => ({
                                    ...drafts,
                                    [config.id]: {
                                      provider_id: drafts[config.id]?.provider_id ?? String(config.provider_id),
                                      model_name: drafts[config.id]?.model_name ?? config.model_name,
                                      model_type: event.target.value,
                                      display_name: drafts[config.id]?.display_name ?? config.display_name ?? "",
                                      context_window:
                                        drafts[config.id]?.context_window ??
                                        (config.context_window ? String(config.context_window) : ""),
                                      default_config:
                                        drafts[config.id]?.default_config ?? stringifyJson(config.default_config ?? {}),
                                      status: drafts[config.id]?.status ?? config.status,
                                      error: null,
                                    },
                                  }))
                                }
                              >
                                <option value="chat">chat</option>
                                <option value="embedding">embedding</option>
                                <option value="rerank">rerank</option>
                              </select>
                            </label>
                          </div>
                          <div className="edit-fields">
                            <label>
                              <span>display_name</span>
                              <input
                                value={modelConfigDrafts[config.id]?.display_name ?? config.display_name ?? ""}
                                onChange={(event) =>
                                  setModelConfigDrafts((drafts) => ({
                                    ...drafts,
                                    [config.id]: {
                                      provider_id: drafts[config.id]?.provider_id ?? String(config.provider_id),
                                      model_name: drafts[config.id]?.model_name ?? config.model_name,
                                      model_type: drafts[config.id]?.model_type ?? config.model_type,
                                      display_name: event.target.value,
                                      context_window:
                                        drafts[config.id]?.context_window ??
                                        (config.context_window ? String(config.context_window) : ""),
                                      default_config:
                                        drafts[config.id]?.default_config ?? stringifyJson(config.default_config ?? {}),
                                      status: drafts[config.id]?.status ?? config.status,
                                      error: null,
                                    },
                                  }))
                                }
                              />
                            </label>
                            <label>
                              <span>status</span>
                              <select
                                value={modelConfigDrafts[config.id]?.status ?? config.status}
                                onChange={(event) =>
                                  setModelConfigDrafts((drafts) => ({
                                    ...drafts,
                                    [config.id]: {
                                      provider_id: drafts[config.id]?.provider_id ?? String(config.provider_id),
                                      model_name: drafts[config.id]?.model_name ?? config.model_name,
                                      model_type: drafts[config.id]?.model_type ?? config.model_type,
                                      display_name: drafts[config.id]?.display_name ?? config.display_name ?? "",
                                      context_window:
                                        drafts[config.id]?.context_window ??
                                        (config.context_window ? String(config.context_window) : ""),
                                      default_config:
                                        drafts[config.id]?.default_config ?? stringifyJson(config.default_config ?? {}),
                                      status: event.target.value,
                                      error: null,
                                    },
                                  }))
                                }
                              >
                                <option value="active">active</option>
                                <option value="disabled">disabled</option>
                              </select>
                            </label>
                          </div>
                          <label className="stacked-field">
                            <span>default_config JSON</span>
                            <textarea
                              value={modelConfigDrafts[config.id]?.default_config ?? stringifyJson(config.default_config ?? {})}
                              onChange={(event) =>
                                setModelConfigDrafts((drafts) => ({
                                  ...drafts,
                                  [config.id]: {
                                    provider_id: drafts[config.id]?.provider_id ?? String(config.provider_id),
                                    model_name: drafts[config.id]?.model_name ?? config.model_name,
                                    model_type: drafts[config.id]?.model_type ?? config.model_type,
                                    display_name: drafts[config.id]?.display_name ?? config.display_name ?? "",
                                    context_window:
                                      drafts[config.id]?.context_window ??
                                      (config.context_window ? String(config.context_window) : ""),
                                    default_config: event.target.value,
                                    status: drafts[config.id]?.status ?? config.status,
                                    error: null,
                                  },
                                }))
                              }
                              spellCheck={false}
                            />
                          </label>
                          {modelConfigDrafts[config.id]?.error ? (
                            <small className="error-text">{modelConfigDrafts[config.id]?.error}</small>
                          ) : null}
                          <button
                            className="icon-button"
                            disabled={busyAction !== null}
                            onClick={() => void updateModelConfig(config.id)}
                            type="button"
                          >
                            <Save size={16} />
                            保存 Config
                          </button>
                        </div>
                      ))}
                    {modelConfigs.filter((config) => config.provider_id === provider.id).length === 0 ? (
                      <p className="empty">暂无 configs</p>
                    ) : null}
                  </div>
                </article>
                );
              })}
              {modelProviders.length === 0 ? <p className="empty">暂无 model provider</p> : null}
            </section>
          </section>
        ) : null}
      </section>
    </main>
  );
}
