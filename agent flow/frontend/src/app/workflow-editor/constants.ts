import type { Edge } from "@xyflow/react";
import {
  BookOpen,
  Bot,
  CheckCircle2,
  CircleStop,
  Cpu,
  Database,
  GitBranch,
  KeyRound,
  LogIn,
  LogOut,
  MessageSquare,
  SquareTerminal,
  TextCursorInput,
  UserCheck,
  Variable,
  Wrench,
} from "lucide-react";

import type { ActiveSection, JsonNodeField, NodeCatalogItem, WorkflowGraph } from "./types";

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const emptyGraph: WorkflowGraph = { schema_version: "1.0", nodes: [], edges: [] };
export const emptyFlowEdges: Edge[] = [];
export const defaultRunInput = JSON.stringify({ rawQuery: "我想申请退款" }, null, 2);
export const nodeDropMoveThreshold = 8;
export const defaultStartFields = [
  { name: "rawQuery", type: "string", label: "用户输入", required: true },
  { name: "chatHistory", type: "array", label: "历史消息", required: false },
  { name: "fileUrls", type: "array", label: "文件 URL", required: false },
  { name: "fileNames", type: "array", label: "文件名", required: false },
  { name: "end_user_id", type: "string", label: "终端用户 ID", required: false },
  { name: "conversation_id", type: "string", label: "会话 ID", required: false },
  { name: "request_id", type: "string", label: "请求 ID", required: false },
  { name: "fields", type: "array", label: "扩展字段", required: false },
];
export const defaultKnowledgeForm = {
  name: "",
  description: "",
  embedding_model: "local-embedding",
  embedding_provider: "local",
  tokenizer: "cl100k_base",
  chunk_size_tokens: "500",
  chunk_overlap_tokens: "80",
};

export const nodeCatalog: NodeCatalogItem[] = [
  { type: "start", label: "开始", group: "输入输出", Icon: CircleStop, config: { fields: defaultStartFields } },
  {
    type: "input",
    label: "用户输入",
    group: "兼容节点",
    Icon: TextCursorInput,
    config: {
      fields: [{ name: "user_query", type: "string", label: "用户问题", required: true }],
    },
    output_mapping: { user_query: "variables.user_query" },
    hidden: true,
  },
  {
    type: "llm",
    label: "大模型",
    group: "AI",
    Icon: Bot,
    config: {
      provider: "deepseek",
      model: "deepseek-v4-flash",
      system_prompt: "你是一个严谨、清晰的 AI 助手。",
      user_prompt: "问题：{{query}}",
      temperature: 0.3,
    },
    input_mapping: { query: "{{input.rawQuery}}" },
    output_mapping: { output: "variables.output", answer: "variables.answer" },
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
    input_mapping: { question: "{{input.rawQuery}}" },
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
    input_mapping: { text: "{{input.rawQuery}}" },
    output_mapping: {
      intent: "variables.intent_result.intent",
      confidence: "variables.intent_result.confidence",
    },
  },
  { type: "branch", label: "条件分支", group: "控制流", Icon: GitBranch, config: { branches: [] } },
  {
    type: "human_approval",
    label: "人工审批",
    group: "控制流",
    Icon: UserCheck,
    config: {
      title: "人工审批",
      description: "",
      timeout_seconds: 3600,
    },
  },
  {
    type: "set_variable",
    label: "变量赋值",
    group: "工具",
    Icon: Variable,
    config: {
      assignments: {
        normalized_query: "{{input.rawQuery}}",
      },
    },
    output_mapping: { values: "variables.last_set_variables" },
  },
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
    config: { message_type: "text", template: "{{variables.output}}" },
    input_mapping: { output: "{{variables.output}}" },
    output_mapping: { message: "messages" },
  },
  {
    type: "output",
    label: "最终输出",
    group: "兼容节点",
    Icon: LogOut,
    config: {
      response_mode: "parameters",
      outputs: { answer: "{{variables.answer}}" },
      output_value_kinds: { answer: "reference" },
      template: "",
    },
    hidden: true,
  },
  {
    type: "end",
    label: "结束",
    group: "输入输出",
    Icon: CheckCircle2,
    config: {
      response_mode: "parameters",
      outputs: { output: "" },
      output_value_kinds: { output: "reference" },
      template: "",
    },
  },
];

export const nodeJsonFieldLabels: Record<JsonNodeField, string> = {
  config: "config JSON",
  input_mapping: "input_mapping JSON",
  output_mapping: "output_mapping JSON",
};

export const adminSections: Array<{ id: ActiveSection; label: string; Icon: typeof GitBranch }> = [
  { id: "workflow", label: "Workflow", Icon: GitBranch },
  { id: "approvals", label: "Approvals", Icon: UserCheck },
  { id: "knowledge", label: "Knowledge", Icon: BookOpen },
  { id: "tools", label: "Tools", Icon: Wrench },
  { id: "secrets", label: "Secrets", Icon: KeyRound },
  { id: "models", label: "Models", Icon: Cpu },
];
