import type { Node, NodeChange } from "@xyflow/react";

import type {
  GraphNode,
  JsonObject,
  NodeCatalogItem,
  NodeEdgeAnchors,
  NodeType,
  WorkflowGraph,
} from "./types";

export function graphToFlowNodes(
  graph: WorkflowGraph,
  selectedNodeId: string | null,
  statusByNodeId: Map<string, string>,
  onQuickAdd: (sourceNodeId: string) => void,
  onManualConnectStart: (sourceNodeId: string, clientX: number, clientY: number) => void,
  currentNodes: Node[],
): Node[] {
  return graph.nodes.map((node) => {
    const currentNode = currentNodes.find((item) => item.id === node.id);
    const status = statusByNodeId.get(node.id);
    return {
      id: node.id,
      type: "workflowNode",
      position: node.position,
      width: 150,
      height: 50,
      data: {
        name: node.name,
        nodeType: node.type,
        status,
        onQuickAdd,
        onManualConnectStart,
      },
      className: getFlowNodeClassName(node, status),
      selected: node.id === selectedNodeId,
      dragging: currentNode?.dragging,
    };
  });
}

export function getConnectionError(graph: WorkflowGraph, sourceNodeId: string, targetNodeId: string): string | null {
  if (sourceNodeId === targetNodeId) {
    return "不能连接到自身节点";
  }

  const sourceNode = graph.nodes.find((node) => node.id === sourceNodeId);
  const targetNode = graph.nodes.find((node) => node.id === targetNodeId);
  if (!sourceNode || !targetNode) {
    return "未找到连线节点，请重新拖拽";
  }

  if (sourceNode.type === "end") {
    return "结束节点不能作为连线起点";
  }

  if (targetNode.type === "start") {
    return "开始节点不能作为连线终点";
  }

  const exists = graph.edges.some((edge) => edge.source === sourceNodeId && edge.target === targetNodeId);
  if (exists) {
    return "该连线已存在";
  }

  const sourceOutgoingCount = graph.edges.filter((edge) => edge.source === sourceNodeId).length;
  if (sourceNode.type !== "branch" && sourceOutgoingCount > 0) {
    return "普通节点只能保留一条出边";
  }

  if (hasPath(graph, targetNodeId, sourceNodeId)) {
    return "当前连接会形成环路";
  }

  return null;
}

function hasPath(graph: WorkflowGraph, fromNodeId: string, toNodeId: string, visited = new Set<string>()): boolean {
  if (fromNodeId === toNodeId) {
    return true;
  }
  if (visited.has(fromNodeId)) {
    return false;
  }
  visited.add(fromNodeId);
  return graph.edges
    .filter((edge) => edge.source === fromNodeId)
    .some((edge) => hasPath(graph, edge.target, toNodeId, visited));
}

export function getDefaultNextNodeType(sourceType: NodeType): NodeType {
  if (sourceType === "start") {
    return "input";
  }
  if (sourceType === "input") {
    return "intent";
  }
  if (sourceType === "intent" || sourceType === "branch") {
    return "llm";
  }
  if (sourceType === "human_approval") {
    return "branch";
  }
  if (sourceType === "llm" || sourceType === "knowledge_base" || sourceType === "api") {
    return "message";
  }
  if (sourceType === "message") {
    return "output";
  }
  return "end";
}

export function getNodeEdgePoint(node: GraphNode, side: "source" | "target"): { x: number; y: number } {
  return {
    x: side === "source" ? node.position.x + 150 : node.position.x,
    y: node.position.y + 25,
  };
}

export function makeWorkflowEdgePath(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const curve = Math.min(120, Math.max(36, Math.abs(to.x - from.x) * 0.35));
  return `M ${from.x} ${from.y} C ${from.x + curve} ${from.y}, ${to.x - curve} ${to.y}, ${to.x} ${to.y}`;
}

export function getWorkflowEdgeMidpoint(
  from: { x: number; y: number },
  to: { x: number; y: number },
): { x: number; y: number } {
  const curve = Math.min(120, Math.max(36, Math.abs(to.x - from.x) * 0.35));
  const control1 = { x: from.x + curve, y: from.y };
  const control2 = { x: to.x - curve, y: to.y };
  const t = 0.5;
  const oneMinusT = 1 - t;
  return {
    x:
      oneMinusT ** 3 * from.x +
      3 * oneMinusT ** 2 * t * control1.x +
      3 * oneMinusT * t ** 2 * control2.x +
      t ** 3 * to.x,
    y:
      oneMinusT ** 3 * from.y +
      3 * oneMinusT ** 2 * t * control1.y +
      3 * oneMinusT * t ** 2 * control2.y +
      t ** 3 * to.y,
  };
}

export function areNodeEdgeAnchorsEqual(currentAnchors: NodeEdgeAnchors, nextAnchors: NodeEdgeAnchors): boolean {
  const currentKeys = Object.keys(currentAnchors);
  const nextKeys = Object.keys(nextAnchors);
  if (currentKeys.length !== nextKeys.length) {
    return false;
  }

  return nextKeys.every((key) => {
    const current = currentAnchors[key];
    const next = nextAnchors[key];
    return (
      current &&
      Math.abs(current.source.x - next.source.x) < 0.5 &&
      Math.abs(current.source.y - next.source.y) < 0.5 &&
      Math.abs(current.target.x - next.target.x) < 0.5 &&
      Math.abs(current.target.y - next.target.y) < 0.5
    );
  });
}

export function findFlowNodeIdAtClientPoint(
  canvas: HTMLDivElement | null,
  clientX: number,
  clientY: number,
): string | null {
  if (!canvas) {
    return null;
  }

  const nodes = Array.from(canvas.querySelectorAll<HTMLElement>(".react-flow__node.flow-node")).reverse();
  for (const node of nodes) {
    const rect = node.getBoundingClientRect();
    if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
      return node.getAttribute("data-id");
    }
  }
  return null;
}

export function isClientPointInsideElement(element: HTMLElement | null, clientX: number, clientY: number): boolean {
  const rect = element?.getBoundingClientRect();
  if (!rect) {
    return false;
  }
  return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
}

export function createGraphNode(
  template: NodeCatalogItem,
  index: number,
  nodeCount: number,
  position?: { x: number; y: number },
): GraphNode {
  const idSuffix = `${index}_${Date.now().toString(36)}`;
  return {
    id: `${template.type}_${idSuffix}`,
    type: template.type,
    name: template.label,
    position: position ?? {
      x: 120 + (nodeCount % 4) * 210,
      y: 120 + Math.floor(nodeCount / 4) * 130,
    },
    config: cloneJsonObject(template.config),
    input_mapping: cloneJsonObject(template.input_mapping ?? {}),
    output_mapping: cloneJsonObject(template.output_mapping ?? {}),
    enabled: true,
  };
}

export function cloneJsonObject(value: JsonObject): JsonObject {
  return JSON.parse(JSON.stringify(value)) as JsonObject;
}

export function groupNodeCatalog(items: NodeCatalogItem[]): Array<[string, NodeCatalogItem[]]> {
  const groups = new Map<string, NodeCatalogItem[]>();
  items.forEach((item) => {
    groups.set(item.group, [...(groups.get(item.group) ?? []), item]);
  });
  return Array.from(groups.entries());
}

export function parseJsonObject(rawValue: string): { value?: JsonObject; error?: string } {
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

export function isPlainObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function stringifyJson(value: JsonObject): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export function configString(config: JsonObject, key: string, fallback: string): string {
  const value = config[key];
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

export function configNumber(config: JsonObject, key: string, fallback: number): number {
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

export function makeEdgeId(source: string, target: string, index: number): string {
  return `edge_${source}_${target}_${index + 1}_${Date.now().toString(36)}`;
}

export function getFlowNodeClassName(node: GraphNode, status?: string): string {
  return [
    "flow-node",
    `node-${node.type}`,
    node.enabled === false ? "node-disabled" : null,
    status ? `status-${normalizeStatus(status)}` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

export function normalizeStatus(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "completed") {
    return "success";
  }
  return normalized;
}

export function nodeChangeHasId(change: NodeChange): change is NodeChange & { id: string } {
  return "id" in change;
}

export function formatBytes(value?: number | null): string {
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

export function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export function shortHash(value?: string | null): string {
  if (!value) {
    return "-";
  }
  const [algorithm, digest] = value.includes(":") ? value.split(":", 2) : ["sha256", value];
  return `${algorithm}:${digest.slice(0, 12)}`;
}

export function formatCodeStatus(status?: string | null, fallback = "-"): string {
  if (status === "ok") {
    return "Hash 一致";
  }
  if (status === "modified") {
    return "Hash 已变更";
  }
  if (status === "missing_file") {
    return "文件缺失";
  }
  if (status === "missing_metadata") {
    return "未生成";
  }
  if (status === "invalid_path") {
    return "路径异常";
  }
  return fallback;
}

export function formatRuntimeError(code?: string | null, message?: string | null): string {
  if (!code) {
    return message ?? "-";
  }

  const hints: Record<string, string> = {
    model_api_key_missing: "模型 API Key 未配置，请检查环境变量或 Secret 引用。",
    model_request_failed: "模型请求失败，请检查模型服务、网络或 provider 配置。",
    model_response_invalid: "模型响应格式异常，请查看节点 trace 中的 provider/model 信息。",
    model_timeout: "模型请求超时，请调大节点超时时间或稍后重试。",
    workflow_code_missing: "本地 workflow.py 缺失，请重新发布或恢复生成代码。",
    workflow_code_import_failed: "本地 workflow.py 导入失败，请检查语法和依赖。",
    workflow_entrypoint_missing: "本地 workflow.py 缺少 async run(input_data, context) 入口。",
    api_response_error: "API 节点响应不符合预期，请检查状态码、response_path 或响应体。",
    api_request_error: "API 节点请求失败，请检查 URL、网络或外呼配置。",
    response_too_large: "API 响应超过节点配置的大小限制，请调小响应或提高 max_response_bytes。",
    network_error: "网络请求失败，请检查目标服务和网络连通性。",
    rate_limit: "上游服务限流，请稍后重试或调整重试策略。",
    timeout: "节点执行超时，请调大超时时间或检查外部服务。",
  };

  const hint = hints[code];
  if (!hint) {
    return message ? `${code}: ${message}` : code;
  }
  return message ? `${code}: ${hint} 原始信息：${message}` : `${code}: ${hint}`;
}

export async function copyText(value?: string | null): Promise<void> {
  if (!value || typeof navigator === "undefined" || !navigator.clipboard) {
    return;
  }
  await navigator.clipboard.writeText(value);
}

export function getRunId(run: { id?: number; run_id?: number }): number | null {
  return run.run_id ?? run.id ?? null;
}

export function metadataText(value: unknown): string {
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

export function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: (RequestInit & { timeoutMs?: number }) = {},
): Promise<Response> {
  const { timeoutMs = 15000, signal, ...requestInit } = init;
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  const abortFromCaller = () => controller.abort();

  if (signal?.aborted) {
    controller.abort();
  } else {
    signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  try {
    return await fetch(input, { ...requestInit, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("本地 API 请求超时，请检查 8000 端口服务");
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}
