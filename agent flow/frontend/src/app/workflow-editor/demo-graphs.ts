import { defaultStartFields } from "./constants";
import type { WorkflowGraph } from "./types";

const startNode = (position = { x: 80, y: 160 }) => ({
  id: "start_1",
  type: "start" as const,
  name: "开始",
  position,
  config: { fields: defaultStartFields },
});

export function createDeepSeekQaDemoGraph(): WorkflowGraph {
  return {
    schema_version: "1.0",
    nodes: [
      startNode(),
      {
        id: "llm_1",
        type: "llm",
        name: "DeepSeek 大模型",
        position: { x: 360, y: 160 },
        config: {
          provider: "deepseek",
          model: "deepseek-v4-flash",
          system_prompt: "你是一个严谨、清晰的工作流助手。回答要直接、可执行。",
          user_prompt: "用户问题：{{query}}",
          temperature: 0.3,
          max_tokens: 800,
        },
        input_mapping: { query: "{{input.rawQuery}}" },
        output_mapping: {
          output: "variables.output",
          answer: "variables.answer",
          provider: "variables.model_provider",
          model: "variables.model_name",
        },
      },
      {
        id: "end_1",
        type: "end",
        name: "结束",
        position: { x: 640, y: 160 },
        config: {
          response_mode: "parameters",
          outputs: {
            output: "{{outputs.llm_1.output}}",
            rawQuery: "{{outputs.start_1.rawQuery}}",
            provider: "{{outputs.llm_1.provider}}",
            model: "{{outputs.llm_1.model}}",
          },
          output_value_kinds: {
            output: "reference",
            rawQuery: "reference",
            provider: "reference",
            model: "reference",
          },
          template: "",
        },
      },
    ],
    edges: [
      { id: "e1", source: "start_1", target: "llm_1" },
      { id: "e2", source: "llm_1", target: "end_1" },
    ],
  };
}

export function createKnowledgeDemoGraph(knowledgeBaseId: number | null): WorkflowGraph {
  const knowledgeBaseIds = knowledgeBaseId ? [knowledgeBaseId] : [];
  return {
    schema_version: "1.0",
    nodes: [
      startNode(),
      {
        id: "kb_1",
        type: "knowledge_base",
        name: "检索知识库",
        position: { x: 360, y: 160 },
        config: {
          knowledge_base_ids: knowledgeBaseIds,
          query: "{{query}}",
          retrieval_mode: "vector",
          top_k: 3,
          score_threshold: 0,
        },
        input_mapping: { query: "{{input.rawQuery}}" },
        output_mapping: { chunks: "variables.kb_context" },
      },
      {
        id: "llm_1",
        type: "llm",
        name: "基于资料生成回答",
        position: { x: 640, y: 160 },
        config: {
          provider: "mock",
          model: "local-mock",
          system_prompt: "你是一个知识库问答助手。请基于检索资料回答，无法确定时说明资料不足。",
          user_prompt: "问题：{{query}}\n\n资料：{{context}}",
          temperature: 0.2,
        },
        input_mapping: {
          query: "{{input.rawQuery}}",
          context: "{{variables.kb_context}}",
        },
        output_mapping: { output: "variables.output", answer: "variables.answer" },
      },
      {
        id: "end_1",
        type: "end",
        name: "结束",
        position: { x: 920, y: 160 },
        config: {
          response_mode: "parameters",
          outputs: {
            output: "{{outputs.llm_1.output}}",
            rawQuery: "{{input.rawQuery}}",
            sources: "{{variables.kb_context}}",
            chunks: "{{variables.kb_context}}",
          },
          output_value_kinds: {
            output: "reference",
            rawQuery: "reference",
            sources: "reference",
            chunks: "reference",
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "start_1", target: "kb_1" },
      { id: "e2", source: "kb_1", target: "llm_1" },
      { id: "e3", source: "llm_1", target: "end_1" },
    ],
  };
}

export function createIntentBranchDemoGraph(): WorkflowGraph {
  return {
    schema_version: "1.0",
    nodes: [
      startNode({ x: 80, y: 190 }),
      {
        id: "intent_1",
        type: "intent",
        name: "识别意图",
        position: { x: 360, y: 190 },
        config: {
          provider: "keyword",
          query: "{{text}}",
          intents: [
            { name: "refund_request", description: "refund 退款 用户申请退款" },
            { name: "general_question", description: "general 普通咨询" },
          ],
          fallback_intent: "general_question",
        },
        input_mapping: { text: "{{input.rawQuery}}" },
        output_mapping: {
          intent: "variables.intent_result.intent",
          confidence: "variables.intent_result.confidence",
        },
      },
      {
        id: "branch_1",
        type: "branch",
        name: "按意图分支",
        position: { x: 640, y: 190 },
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
        position: { x: 920, y: 90 },
        config: {
          message_type: "text",
          template: "已识别为退款诉求，意图：{{variables.intent_result.intent}}",
        },
        output_mapping: { message: "variables.branch_message" },
      },
      {
        id: "general_message_1",
        type: "message",
        name: "普通咨询回复",
        position: { x: 920, y: 290 },
        config: {
          message_type: "text",
          template: "已进入普通咨询路径，意图：{{variables.intent_result.intent}}",
        },
        output_mapping: { message: "variables.branch_message" },
      },
      {
        id: "end_1",
        type: "end",
        name: "结束",
        position: { x: 1200, y: 190 },
        config: {
          response_mode: "parameters",
          outputs: {
            route: "{{outputs.branch_1.selected}}",
            intent: "{{variables.intent_result.intent}}",
            confidence: "{{variables.intent_result.confidence}}",
            output: "{{variables.branch_message}}",
            messages: "{{messages}}",
          },
          output_value_kinds: {
            route: "reference",
            intent: "reference",
            confidence: "reference",
            output: "reference",
            messages: "reference",
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "start_1", target: "intent_1" },
      { id: "e2", source: "intent_1", target: "branch_1" },
      { id: "e3", source: "branch_1", target: "refund_message_1", label: "refund" },
      { id: "e4", source: "branch_1", target: "general_message_1", label: "general" },
      { id: "e5", source: "refund_message_1", target: "end_1" },
      { id: "e6", source: "general_message_1", target: "end_1" },
    ],
  };
}

export function createApiMessageDemoGraph(): WorkflowGraph {
  return {
    schema_version: "1.0",
    nodes: [
      {
        ...startNode(),
        config: {
          fields: [
            ...defaultStartFields,
            { name: "order_id", type: "string", label: "订单号", required: true },
          ],
        },
      },
      {
        id: "api_1",
        type: "api",
        name: "查询订单 API",
        position: { x: 360, y: 160 },
        config: {
          mode: "mock",
          method: "POST",
          url: "https://orders.example.test/lookup/{{input.order_id}}",
          headers: {
            Authorization: "Bearer {{secrets.demo_api_key}}",
            "X-Order-ID": "{{input.order_id}}",
          },
          query_params: {
            tenant: "demo",
            trace_id: "{{input.order_id}}",
          },
          body: {
            order_id: "{{input.order_id}}",
            query: "{{input.rawQuery}}",
          },
          response_path: "data.order",
          mock_status_code: 200,
          mock_response: {
            data: {
              order: {
                order_id: "{{input.order_id}}",
                order_status: "paid",
                next_step: "send_message",
              },
            },
          },
        },
        output_mapping: { response: "variables.api_response" },
      },
      {
        id: "message_1",
        type: "message",
        name: "生成消息",
        position: { x: 640, y: 160 },
        config: {
          message_type: "text",
          template: "订单 {{variables.api_response.order_id}} 当前状态：{{variables.api_response.order_status}}",
        },
        output_mapping: { message: "variables.branch_message" },
      },
      {
        id: "end_1",
        type: "end",
        name: "结束",
        position: { x: 920, y: 160 },
        config: {
          response_mode: "parameters",
          outputs: {
            api_response: "{{variables.api_response}}",
            output: "{{outputs.message_1.message}}",
            messages: "{{messages}}",
          },
          output_value_kinds: {
            api_response: "reference",
            output: "reference",
            messages: "reference",
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "start_1", target: "api_1" },
      { id: "e2", source: "api_1", target: "message_1" },
      { id: "e3", source: "message_1", target: "end_1" },
    ],
  };
}
