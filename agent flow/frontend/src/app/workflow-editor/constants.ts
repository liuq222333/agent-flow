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
  Variable,
  Wrench,
} from "lucide-react";

import type { ActiveSection, JsonNodeField, NodeCatalogItem, WorkflowGraph } from "./types";

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const emptyGraph: WorkflowGraph = { schema_version: "1.0", nodes: [], edges: [] };
export const emptyFlowEdges: Edge[] = [];
export const defaultRunInput = JSON.stringify({ user_query: "我想申请退款" }, null, 2);
export const nodeDropMoveThreshold = 8;
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
      provider: "deepseek",
      model: "deepseek-v4-flash",
      system_prompt: "你是一个严谨、清晰的 AI 助手。",
      user_prompt: "问题：{{input.user_query}}",
      temperature: 0.3,
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
    type: "set_variable",
    label: "变量赋值",
    group: "工具",
    Icon: Variable,
    config: {
      assignments: {
        normalized_query: "{{input.user_query}}",
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

export const nodeJsonFieldLabels: Record<JsonNodeField, string> = {
  config: "config JSON",
  input_mapping: "input_mapping JSON",
  output_mapping: "output_mapping JSON",
};

export const adminSections: Array<{ id: ActiveSection; label: string; Icon: typeof GitBranch }> = [
  { id: "workflow", label: "Workflow", Icon: GitBranch },
  { id: "knowledge", label: "Knowledge", Icon: BookOpen },
  { id: "tools", label: "Tools", Icon: Wrench },
  { id: "secrets", label: "Secrets", Icon: KeyRound },
  { id: "models", label: "Models", Icon: Cpu },
];
