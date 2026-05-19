import type { WorkflowGraph } from "./types";

export function createKnowledgeDemoGraph(knowledgeBaseId: number | null): WorkflowGraph {
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
        id: "llm_1",
        type: "llm",
        name: "基于资料生成回答",
        position: { x: 720, y: 160 },
        config: {
          provider: "mock",
          model: "local-mock",
          system_prompt: "你是一个知识库问答助手。请基于检索资料回答，无法确定时说明资料不足。",
          user_prompt: "问题：{{input.user_query}}\n\n资料：{{variables.kb_context}}",
          temperature: 0.2,
        },
        input_mapping: {
          question: "{{input.user_query}}",
          context: "{{variables.kb_context}}",
        },
        output_mapping: { answer: "variables.answer" },
      },
      {
        id: "output_1",
        type: "output",
        name: "最终输出",
        position: { x: 940, y: 160 },
        config: {
          outputs: {
            query: "{{input.user_query}}",
            answer: "{{variables.answer}}",
            sources: "{{variables.kb_context}}",
            chunks: "{{variables.kb_context}}",
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
      { id: "e2", source: "input_1", target: "kb_1" },
      { id: "e3", source: "kb_1", target: "llm_1" },
      { id: "e4", source: "llm_1", target: "output_1" },
      { id: "e5", source: "output_1", target: "end_1" },
    ],
  };
}

export function createIntentBranchDemoGraph(): WorkflowGraph {
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

export function createApiMessageDemoGraph(): WorkflowGraph {
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
