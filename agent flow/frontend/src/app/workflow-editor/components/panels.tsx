"use client";

import { useState, type MouseEvent, type ReactNode } from "react";
import {
  Bot,
  ChevronRight,
  Copy,
  Database,
  FileText,
  FileJson,
  HelpCircle,
  MinusCircle,
  MoreHorizontal,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";

import type {
  ApiTool,
  GeneratedWorkflowCleanupReport,
  GraphNode,
  JsonObject,
  JsonNodeField,
  KnowledgeBase,
  ModelConfig,
  RunListItem,
  RunTrace,
  ValidationResult,
  Workflow,
  WorkflowVersionCode,
  WorkflowVersion,
  WorkflowGraph,
} from "../types";
import { nodeCatalog } from "../constants";
import {
  formatCodeStatus,
  configNumber,
  configString,
  copyText,
  formatDate,
  getRunId,
  isPlainObject,
  jsonText,
  metadataText,
  normalizeStatus,
  shortHash,
} from "../utils";

type InputValueKind = "reference" | "text" | "number" | "boolean" | "json";
type OutputValueType = "String" | "Number" | "Boolean" | "Object" | "Array";

type ReferenceParam = {
  label: string;
  value: string;
  valueType: string;
};

type ReferenceGroup = {
  id: string;
  label: string;
  Icon: LucideIcon;
  tone: string;
  params: ReferenceParam[];
};

type OutputSchemaItem = {
  type?: OutputValueType | string;
  description?: string;
};

export function AdminHeader({
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

export function DataTable({
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

export function ValidationView({
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

export function NodeConfigPanel({
  graph,
  knowledgeBases,
  modelConfigs,
  node,
  nodeJsonDrafts,
  nodeJsonErrors,
  onConfigChange,
  onNodePatch,
  onNodeJsonChange,
  tools,
}: {
  graph: WorkflowGraph;
  knowledgeBases: KnowledgeBase[];
  modelConfigs: ModelConfig[];
  node: GraphNode;
  nodeJsonDrafts: Record<JsonNodeField, string>;
  nodeJsonErrors: Record<JsonNodeField, string | null>;
  onConfigChange: (patch: JsonObject) => void;
  onNodePatch: (patch: Partial<GraphNode>) => void;
  onNodeJsonChange: (field: JsonNodeField, value: string) => void;
  tools: ApiTool[];
}) {
  const catalogItem = nodeCatalog.find((item) => item.type === node.type);
  const NodeIcon = catalogItem?.Icon ?? Bot;
  const referenceGroups = buildReferenceGroups(graph, node.id);
  const inputMapping = asJsonObject(node.input_mapping);
  const outputMapping = asJsonObject(node.output_mapping);
  const outputSchema = getOutputSchema(node.config);
  const outputRows = getOutputRows(outputMapping, outputSchema);

  const patchInputMapping = (nextMapping: JsonObject) => {
    onNodePatch({ input_mapping: nextMapping });
  };

  const patchOutputMappingAndSchema = (nextMapping: JsonObject, nextSchema: Record<string, OutputSchemaItem>) => {
    onNodePatch({
      output_mapping: nextMapping,
      config: {
        ...node.config,
        output_schema: nextSchema,
      },
    });
  };

  const addInput = () => {
    const key = makeUniqueKey(inputMapping, "input");
    patchInputMapping({
      ...inputMapping,
      [key]: getDefaultInputValue("reference", referenceGroups),
    });
  };

  const addOutput = () => {
    const key = makeUniqueKey(outputMapping, "output");
    patchOutputMappingAndSchema(
      {
        ...outputMapping,
        [key]: `variables.${key}`,
      },
      {
        ...outputSchema,
        [key]: { type: "String", description: "" },
      },
    );
  };

  const updateInputName = (oldKey: string, nextKey: string) => {
    patchInputMapping(renameObjectKey(inputMapping, oldKey, nextKey));
  };

  const updateInputValue = (key: string, kind: InputValueKind, rawValue: string) => {
    patchInputMapping({
      ...inputMapping,
      [key]: coerceInputValue(kind, rawValue),
    });
  };

  const updateInputKind = (key: string, kind: InputValueKind) => {
    patchInputMapping({
      ...inputMapping,
      [key]: getDefaultInputValue(kind, referenceGroups),
    });
  };

  const removeInput = (key: string) => {
    const nextMapping = { ...inputMapping };
    delete nextMapping[key];
    patchInputMapping(nextMapping);
  };

  const updateOutputName = (oldKey: string, nextKey: string) => {
    patchOutputMappingAndSchema(renameObjectKey(outputMapping, oldKey, nextKey), renameObjectKey(outputSchema, oldKey, nextKey));
  };

  const updateOutputType = (key: string, type: OutputValueType) => {
    patchOutputMappingAndSchema(outputMapping, {
      ...outputSchema,
      [key]: { ...outputSchema[key], type },
    });
  };

  const updateOutputDescription = (key: string, description: string) => {
    patchOutputMappingAndSchema(outputMapping, {
      ...outputSchema,
      [key]: { ...outputSchema[key], description },
    });
  };

  const removeOutput = (key: string) => {
    const nextMapping = { ...outputMapping };
    const nextSchema = { ...outputSchema };
    delete nextMapping[key];
    delete nextSchema[key];
    patchOutputMappingAndSchema(nextMapping, nextSchema);
  };

  const inputSection = (
    <section className="node-param-section">
      <div className="node-param-heading">
        <div>
          <strong>输入</strong>
          <HelpCircle size={15} />
        </div>
        <button className="icon-only-button" onClick={addInput} title="添加输入参数" type="button">
          <Plus size={18} />
        </button>
      </div>
      <div className="node-param-grid input-grid header-row">
        <span>参数名</span>
        <span>类型</span>
        <span>值</span>
      </div>
      {Object.entries(inputMapping).map(([key, value]) => {
        const kind = inferInputKind(value);
        return (
          <div className="node-param-grid input-grid" key={key}>
            <input value={key} onChange={(event) => updateInputName(key, event.target.value)} />
            <select value={kind} onChange={(event) => updateInputKind(key, event.target.value as InputValueKind)}>
              <option value="reference">引用</option>
              <option value="text">文本</option>
              <option value="number">数字</option>
              <option value="boolean">布尔</option>
              <option value="json">JSON</option>
            </select>
            {renderInputValueControl({
              keyName: key,
              kind,
              referenceGroups,
              updateValue: updateInputValue,
              value,
            })}
            <button className="icon-only-button danger" onClick={() => removeInput(key)} title="删除输入" type="button">
              <MinusCircle size={18} />
            </button>
          </div>
        );
      })}
      {Object.keys(inputMapping).length === 0 ? <p className="empty">暂无输入参数</p> : null}
    </section>
  );

  const outputSection = (
    <section className="node-param-section">
      <div className="node-param-heading">
        <div>
          <strong>输出</strong>
          <HelpCircle size={15} />
        </div>
        <button className="icon-only-button" onClick={addOutput} title="添加输出参数" type="button">
          <Plus size={18} />
        </button>
      </div>
      <div className="node-param-grid output-grid header-row">
        <span>参数名</span>
        <span>类型</span>
        <span>描述</span>
      </div>
      {outputRows.map((row) => (
        <div className="node-param-grid output-grid" key={row.name}>
          <input value={row.name} onChange={(event) => updateOutputName(row.name, event.target.value)} />
          <select value={row.type} onChange={(event) => updateOutputType(row.name, event.target.value as OutputValueType)}>
            <option value="String">String</option>
            <option value="Number">Number</option>
            <option value="Boolean">Boolean</option>
            <option value="Object">Object</option>
            <option value="Array">Array</option>
          </select>
          <input
            value={row.description}
            onChange={(event) => updateOutputDescription(row.name, event.target.value)}
            placeholder="描述"
          />
          <button className="icon-only-button danger" onClick={() => removeOutput(row.name)} title="删除输出" type="button">
            <MinusCircle size={18} />
          </button>
        </div>
      ))}
      {outputRows.length === 0 ? <p className="empty">暂无输出参数</p> : null}
    </section>
  );

  const protocolJsonSection = (
    <details className="protocol-json-box">
      <summary>协议 JSON</summary>
      {(["config", "input_mapping", "output_mapping"] as JsonNodeField[]).map((field) => (
        <label key={field}>
          <span>{field}</span>
          <textarea
            value={nodeJsonDrafts[field]}
            onChange={(event) => onNodeJsonChange(field, event.target.value)}
            spellCheck={false}
          />
          {nodeJsonErrors[field] ? <small className="error-text">{nodeJsonErrors[field]}</small> : null}
        </label>
      ))}
    </details>
  );

  if (node.type === "llm") {
    return (
      <LlmNodeEditor
        inputSection={inputSection}
        modelConfigs={modelConfigs}
        node={node}
        onConfigChange={onConfigChange}
        onNodePatch={onNodePatch}
        outputSection={outputSection}
        protocolJsonSection={protocolJsonSection}
      />
    );
  }

  return (
    <div className="node-editor">
      <header className="node-editor-header">
        <div className={`node-editor-icon node-${node.type}`}>
          <NodeIcon size={18} />
        </div>
        <div>
          <input
            className="node-editor-title"
            value={node.name}
            onChange={(event) => onNodePatch({ name: event.target.value })}
          />
          <span>{catalogItem?.label ?? node.type}</span>
        </div>
        <button className="icon-only-button" title="仅预览入口，运行仍走右侧运行面板" type="button">
          <Play size={16} />
        </button>
      </header>

      <textarea
        className="node-editor-description"
        value={node.description ?? ""}
        onChange={(event) => onNodePatch({ description: event.target.value })}
        placeholder="节点说明"
      />

      <button className="node-template-button" disabled type="button">
        <Settings2 size={16} />
        节点配置模板
      </button>

      <StructuredNodeConfig
        knowledgeBases={knowledgeBases}
        modelConfigs={modelConfigs}
        node={node}
        onConfigChange={onConfigChange}
        tools={tools}
      />

      {inputSection}
      {outputSection}
      {protocolJsonSection}
    </div>
  );
}

function LlmNodeEditor({
  inputSection,
  modelConfigs,
  node,
  onConfigChange,
  onNodePatch,
  outputSection,
  protocolJsonSection,
}: {
  inputSection: ReactNode;
  modelConfigs: ModelConfig[];
  node: GraphNode;
  onConfigChange: (patch: JsonObject) => void;
  onNodePatch: (patch: Partial<GraphNode>) => void;
  outputSection: ReactNode;
  protocolJsonSection: ReactNode;
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const config = node.config ?? {};
  const chatModels = modelConfigs.filter((configItem) => configItem.model_type === "chat");
  const provider = configString(config, "provider", "deepseek");
  const model = configString(config, "model", provider === "mock" ? "local-mock" : "deepseek-v4-flash");
  const selectedModelConfigId = String(config.model_config_id ?? "");
  const selectedConfigValue = selectedModelConfigId ? `config:${selectedModelConfigId}` : `model:${model}`;
  const hasSelectedConfig = chatModels.some((modelConfig) => String(modelConfig.id) === selectedModelConfigId);
  const displayTitle = node.name === "生成回答" || node.name === "llm" ? "大模型" : node.name;
  const systemPrompt = configString(config, "system_prompt", "");
  const userPrompt = configString(config, "user_prompt", "读取信息 {{a}} 输出主要内容");

  const updateModelSelection = (value: string) => {
    if (value.startsWith("config:")) {
      const modelConfigId = Number(value.replace("config:", ""));
      const modelConfig = chatModels.find((item) => item.id === modelConfigId);
      onConfigChange({
        model_config_id: Number.isFinite(modelConfigId) && modelConfigId > 0 ? modelConfigId : null,
        model: modelConfig?.model_name ?? model,
      });
      return;
    }

    const rawModel = value.replace("model:", "");
    onConfigChange({ model_config_id: null, model: rawModel });
  };

  return (
    <div className="node-editor llm-editor">
      <header className="llm-editor-header">
        <div className="node-editor-icon node-llm">
          <Bot size={18} />
        </div>
        <input
          className="node-editor-title"
          value={displayTitle}
          onChange={(event) => onNodePatch({ name: event.target.value })}
        />
        <div className="llm-header-actions">
          <button className="icon-only-button" title="仅预览入口，运行仍走右侧运行面板" type="button">
            <Play size={16} />
          </button>
          <button className="icon-only-button" title="更多" type="button">
            <MoreHorizontal size={17} />
          </button>
          <span />
          <button className="icon-only-button" title="关闭面板" type="button">
            <X size={17} />
          </button>
        </div>
      </header>

      <p className="llm-editor-description">
        调用大语言模型，根据输入参数和提示词生成回复。
        <button className="text-button" type="button">
          了解更多 <ChevronRight size={15} />
        </button>
      </p>

      <button className="node-template-button llm-template-button" type="button">
        <FileText size={16} />
        大模型配置模板
      </button>

      <section className="llm-model-section">
        <div className="llm-model-heading">
          <div>
            <span className="required-mark">*</span>
            <strong>模型</strong>
            <HelpCircle size={15} />
          </div>
          <button className="llm-advanced-button" onClick={() => setAdvancedOpen((open) => !open)} type="button">
            <Settings2 size={16} />
            高级配置
          </button>
        </div>
        <div className="llm-model-row">
          <label className="llm-model-select">
            <span className="llm-model-provider-icon">
              <Bot size={15} />
            </span>
            <select value={selectedConfigValue} onChange={(event) => updateModelSelection(event.target.value)}>
              {!selectedModelConfigId ? <option value={`model:${model}`}>{model}</option> : null}
              {selectedModelConfigId && !hasSelectedConfig ? <option value={selectedConfigValue}>{model}</option> : null}
              {chatModels.map((modelConfig) => (
                <option key={modelConfig.id} value={`config:${modelConfig.id}`}>
                  {modelConfig.display_name ?? modelConfig.model_name}
                </option>
              ))}
            </select>
            <SlidersHorizontal size={17} />
          </label>
          <button className="llm-refresh-button" onClick={() => onConfigChange({ model })} title="刷新模型" type="button">
            <RefreshCw size={18} />
          </button>
        </div>
        {advancedOpen ? (
          <div className="llm-advanced-grid">
            <label>
              <span>provider</span>
              <select value={provider} onChange={(event) => onConfigChange({ provider: event.target.value })}>
                <option value="mock">mock</option>
                <option value="deepseek">deepseek</option>
                <option value="openai">openai</option>
              </select>
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
          </div>
        ) : null}
      </section>

      {inputSection}

      <section className="llm-prompt-section">
        <h3>提示词</h3>
        <details className="llm-prompt-block">
          <summary>
            <span className="llm-prompt-title">
              <ChevronRight size={15} />
              系统提示词
              <HelpCircle size={15} />
            </span>
            <span className="llm-prompt-actions">
              <button onClick={(event) => event.preventDefault()} type="button">
                <Sparkles size={15} />
                优化
              </button>
              <button onClick={(event) => event.preventDefault()} type="button">
                <FileText size={15} />
                模板
              </button>
            </span>
          </summary>
          <textarea
            value={systemPrompt}
            onChange={(event) => onConfigChange({ system_prompt: event.target.value })}
            placeholder="系统提示词"
          />
        </details>
        <details className="llm-prompt-block" open>
          <summary>
            <span className="llm-prompt-title">
              <ChevronRight size={15} />
              用户提示词 <span className="required-mark">*</span>
              <HelpCircle size={15} />
            </span>
            <span className="llm-prompt-actions">
              <button onClick={(event) => event.preventDefault()} type="button">
                <Sparkles size={15} />
                优化
              </button>
              <button onClick={(event) => event.preventDefault()} type="button">
                <FileText size={15} />
                模板
              </button>
            </span>
          </summary>
          <label className="llm-prompt-editor">
            <textarea value={userPrompt} onChange={(event) => onConfigChange({ user_prompt: event.target.value })} />
            <small>{userPrompt.length}字</small>
          </label>
        </details>
      </section>

      {outputSection}
      {protocolJsonSection}
    </div>
  );
}

function renderInputValueControl({
  keyName,
  kind,
  referenceGroups,
  updateValue,
  value,
}: {
  keyName: string;
  kind: InputValueKind;
  referenceGroups: ReferenceGroup[];
  updateValue: (key: string, kind: InputValueKind, rawValue: string) => void;
  value: unknown;
}) {
  if (kind === "reference") {
    const currentValue = typeof value === "string" ? value : "";
    return (
      <ReferencePicker
        groups={referenceGroups}
        onChange={(nextValue) => updateValue(keyName, kind, nextValue)}
        value={currentValue}
      />
    );
  }

  if (kind === "boolean") {
    return (
      <select value={String(value)} onChange={(event) => updateValue(keyName, kind, event.target.value)}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }

  return (
    <input
      value={mappingValueToText(value)}
      onChange={(event) => updateValue(keyName, kind, event.target.value)}
      placeholder={kind === "json" ? "{\"key\":\"value\"}" : undefined}
    />
  );
}

function ReferencePicker({
  groups,
  onChange,
  value,
}: {
  groups: ReferenceGroup[];
  onChange: (value: string) => void;
  value: string;
}) {
  const selected = findReferenceSelection(groups, value);
  const [open, setOpen] = useState(false);
  const [activeGroupId, setActiveGroupId] = useState(selected?.group.id ?? groups[0]?.id ?? "");
  const [placement, setPlacement] = useState<{ left: number; top: number; width: number } | null>(null);
  const activeGroup = groups.find((group) => group.id === activeGroupId) ?? selected?.group ?? groups[0] ?? null;
  const hasReferences = groups.some((group) => group.params.length > 0);
  const displayLabel = selected ? `${selected.group.label}/${selected.param.label}` : value ? unwrapReferenceToken(value) : "选择引用";

  const togglePicker = (event: MouseEvent<HTMLButtonElement>) => {
    const nextOpen = !open;
    if (nextOpen) {
      const rect = event.currentTarget.getBoundingClientRect();
      const width = Math.min(540, window.innerWidth - 32);
      const left = Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16));
      setActiveGroupId(selected?.group.id ?? groups[0]?.id ?? "");
      setPlacement({ left, top: rect.bottom + 8, width });
    }
    setOpen(nextOpen);
  };

  return (
    <div className="reference-picker">
      <button
        aria-expanded={open}
        className="reference-trigger"
        disabled={!hasReferences}
        onClick={togglePicker}
        title={displayLabel}
        type="button"
      >
        <span>{displayLabel}</span>
        <Search size={14} />
      </button>
      {open ? (
        <div className="reference-popover" style={placement ?? undefined}>
          <div className="reference-card reference-param-card">
            {activeGroup ? (
              activeGroup.params.map((param) => (
                <button
                  className={param.value === value ? "active" : ""}
                  key={param.value}
                  onClick={() => {
                    onChange(param.value);
                    setOpen(false);
                  }}
                  type="button"
                >
                  <span>{param.label}</span>
                  <small>{param.valueType}</small>
                </button>
              ))
            ) : (
              <p className="empty">暂无可引用输出</p>
            )}
          </div>
          <div className="reference-card reference-node-card">
            {groups.map((group) => {
              const GroupIcon = group.Icon;
              return (
                <button
                  className={group.id === activeGroup?.id ? "active" : ""}
                  key={group.id}
                  onClick={() => setActiveGroupId(group.id)}
                  type="button"
                >
                  <span className={`reference-node-icon node-${group.tone}`}>
                    <GroupIcon size={15} />
                  </span>
                  <span>{group.label}</span>
                  <ChevronRight size={16} />
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function buildReferenceGroups(graph: WorkflowGraph, currentNodeId: string): ReferenceGroup[] {
  const systemGroup: ReferenceGroup = {
    id: "system",
    label: "系统参数",
    Icon: Play,
    tone: "system",
    params: [
      { label: "rawQuery", value: "{{input.user_query}}", valueType: "String" },
      { label: "chatHistory", value: "{{messages}}", valueType: "Array<string>" },
      { label: "fileUrls", value: "{{input.fileUrls}}", valueType: "Array<string>" },
      { label: "fileNames", value: "{{input.fileNames}}", valueType: "Array<string>" },
      { label: "end_user_id", value: "{{input.end_user_id}}", valueType: "String" },
      { label: "conversation_id", value: "{{input.conversation_id}}", valueType: "String" },
      { label: "request_id", value: "{{input.request_id}}", valueType: "String" },
      { label: "fields", value: "{{input.fields}}", valueType: "Array<string>" },
    ],
  };

  const nodeGroups = graph.nodes
    .filter((graphNode) => graphNode.id !== currentNodeId)
    .map((graphNode) => {
      const catalogItem = nodeCatalog.find((item) => item.type === graphNode.type);
      return {
        id: graphNode.id,
        label: graphNode.name,
        Icon: catalogItem?.Icon ?? Bot,
        tone: graphNode.type,
        params: getNodeOutputFieldNames(graphNode).map((field) => ({
          label: field,
          value: `{{outputs.${graphNode.id}.${field}}}`,
          valueType: getNodeOutputFieldType(graphNode, field),
        })),
      };
    })
    .filter((group) => group.params.length > 0);

  return [systemGroup, ...nodeGroups];
}

function findReferenceSelection(groups: ReferenceGroup[], value: string): { group: ReferenceGroup; param: ReferenceParam } | null {
  for (const group of groups) {
    const param = group.params.find((item) => item.value === value);
    if (param) {
      return { group, param };
    }
  }
  return null;
}

function unwrapReferenceToken(value: string): string {
  return value.replace(/^\{\{\s*/, "").replace(/\s*\}\}$/, "");
}

function getNodeOutputFieldType(node: GraphNode, field: string): string {
  const schema = getOutputSchema(node.config);
  if (schema[field]?.type) {
    return toDisplayType(schema[field]?.type);
  }

  const fields = node.config.fields;
  if (Array.isArray(fields)) {
    const matchedField = fields.find((item) => isPlainObject(item) && item.name === field);
    if (isPlainObject(matchedField)) {
      return toDisplayType(matchedField.type);
    }
  }

  const outputs = node.config.outputs;
  if (isPlainObject(outputs)) {
    const outputValue = outputs[field];
    if (Array.isArray(outputValue)) {
      return "Array";
    }
    if (isPlainObject(outputValue)) {
      return "Object";
    }
    if (typeof outputValue === "number") {
      return "Number";
    }
    if (typeof outputValue === "boolean") {
      return "Boolean";
    }
  }

  return "String";
}

function toDisplayType(value: unknown): string {
  if (typeof value !== "string" || value.trim() === "") {
    return "String";
  }

  const normalized = value.trim();
  const lower = normalized.toLowerCase();
  if (lower === "string" || lower === "str") {
    return "String";
  }
  if (lower === "number" || lower === "integer" || lower === "int" || lower === "float") {
    return "Number";
  }
  if (lower === "boolean" || lower === "bool") {
    return "Boolean";
  }
  if (lower === "object" || lower === "json") {
    return "Object";
  }
  if (lower.startsWith("array") || lower.endsWith("[]")) {
    return normalized.replace(/^array/i, "Array");
  }

  return normalized;
}

function getFirstReferenceValue(groups: ReferenceGroup[]): string {
  return groups.find((group) => group.params.length > 0)?.params[0]?.value ?? "";
}

function getNodeOutputFieldNames(node: GraphNode): string[] {
  const names = new Set<string>();

  Object.keys(asJsonObject(node.output_mapping)).forEach((key) => names.add(key));

  const outputs = node.config.outputs;
  if (isPlainObject(outputs)) {
    Object.keys(outputs).forEach((key) => names.add(key));
  }

  const fields = node.config.fields;
  if (Array.isArray(fields)) {
    fields.forEach((field) => {
      if (isPlainObject(field) && typeof field.name === "string") {
        names.add(field.name);
      }
    });
  }

  if (names.size === 0) {
    names.add("output");
  }

  return Array.from(names);
}

function getOutputRows(outputMapping: JsonObject, outputSchema: Record<string, OutputSchemaItem>) {
  const names = new Set([...Object.keys(outputMapping), ...Object.keys(outputSchema)]);
  return Array.from(names).map((name) => ({
    name,
    type: normalizeOutputType(outputSchema[name]?.type),
    description: outputSchema[name]?.description ?? mappingValueToText(outputMapping[name]),
  }));
}

function getOutputSchema(config: JsonObject): Record<string, OutputSchemaItem> {
  const schema = config.output_schema;
  if (!isPlainObject(schema)) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(schema).map(([key, value]) => [
      key,
      isPlainObject(value)
        ? {
            type: typeof value.type === "string" ? value.type : "String",
            description: typeof value.description === "string" ? value.description : "",
          }
        : { type: "String", description: "" },
    ]),
  );
}

function normalizeOutputType(value: unknown): OutputValueType {
  if (value === "Number" || value === "Boolean" || value === "Object" || value === "Array") {
    return value;
  }
  return "String";
}

function inferInputKind(value: unknown): InputValueKind {
  if (typeof value === "number") {
    return "number";
  }
  if (typeof value === "boolean") {
    return "boolean";
  }
  if (typeof value === "object" && value !== null) {
    return "json";
  }
  if (typeof value === "string" && value.trim().startsWith("{{") && value.trim().endsWith("}}")) {
    return "reference";
  }
  return "text";
}

function coerceInputValue(kind: InputValueKind, rawValue: string): unknown {
  if (kind === "number") {
    const parsed = Number(rawValue);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (kind === "boolean") {
    return rawValue === "true";
  }
  if (kind === "json") {
    try {
      return JSON.parse(rawValue) as unknown;
    } catch {
      return rawValue;
    }
  }
  return rawValue;
}

function getDefaultInputValue(kind: InputValueKind, referenceGroups: ReferenceGroup[]): unknown {
  if (kind === "reference") {
    return getFirstReferenceValue(referenceGroups);
  }
  if (kind === "number") {
    return 0;
  }
  if (kind === "boolean") {
    return false;
  }
  if (kind === "json") {
    return {};
  }
  return "";
}

function mappingValueToText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function asJsonObject(value?: JsonObject | null): JsonObject {
  return isPlainObject(value) ? value : {};
}

function makeUniqueKey(target: JsonObject, baseName: string): string {
  let index = Object.keys(target).length + 1;
  let key = `${baseName}_${index}`;
  while (Object.hasOwn(target, key)) {
    index += 1;
    key = `${baseName}_${index}`;
  }
  return key;
}

function renameObjectKey<T extends Record<string, unknown>>(target: T, oldKey: string, nextKey: string): T {
  const normalizedKey = nextKey.trim();
  if (!normalizedKey || normalizedKey === oldKey || Object.hasOwn(target, normalizedKey)) {
    return target;
  }

  return Object.fromEntries(
    Object.entries(target).map(([key, value]) => (key === oldKey ? [normalizedKey, value] : [key, value])),
  ) as T;
}

export function VersionCodePanel({
  busy,
  cleanupReport,
  code,
  codeVisible,
  onCleanupGenerated,
  onLoadCode,
  onRegenerateCode,
  onToggleCode,
  selectedCodeVersion,
  versions,
  workflow,
  version,
}: {
  busy: boolean;
  cleanupReport: GeneratedWorkflowCleanupReport | null;
  code: WorkflowVersionCode | null;
  codeVisible: boolean;
  onCleanupGenerated: () => void;
  onLoadCode: (version?: WorkflowVersion) => void;
  onRegenerateCode: (version: WorkflowVersion) => void;
  onToggleCode: () => void;
  selectedCodeVersion: WorkflowVersion | null;
  versions: WorkflowVersion[];
  workflow: Workflow | null;
  version: WorkflowVersion | null;
}) {
  if (!workflow) {
    return (
      <section className="version-code-panel">
        <div className="version-code-empty">
          <span>发布代码</span>
          <strong>未选择工作流</strong>
        </div>
      </section>
    );
  }
  if (!workflow.current_version_id) {
    return (
      <section className="version-code-panel">
        <div className="version-code-empty">
          <span>发布代码</span>
          <strong>当前工作流尚未发布</strong>
        </div>
      </section>
    );
  }

  const codePath = version?.code_path ?? null;
  const codeHash = version?.code_hash ?? null;
  const actualHash = code?.code_hash_actual ?? version?.code_hash_actual ?? null;
  const codeModified = code?.code_modified ?? version?.code_modified ?? null;
  const codeStatus = codePath ? "已生成" : "未生成";
  const versionLabel = `v${version?.version ?? workflow.current_version ?? workflow.current_version_id}`;
  const visibleCodeLabel = selectedCodeVersion ? `v${selectedCodeVersion.version}` : versionLabel;

  return (
    <section className="version-code-panel">
      <div className="version-code-summary">
        <div>
          <span>发布版本</span>
          <strong>{versionLabel}</strong>
        </div>
        <div>
          <span>代码状态</span>
          <strong className={codeModified ? "version-code-status warning" : "version-code-status"}>
            {version ? formatCodeStatus(version.code_status, codeStatus) : "加载中"}
          </strong>
        </div>
        <div>
          <span>生成时间</span>
          <strong>{formatDate(version?.code_generated_at)}</strong>
        </div>
        <div>
          <span>Hash</span>
          <code title={codeHash ?? undefined}>{version ? shortHash(codeHash) : "加载中"}</code>
        </div>
        <div className="version-code-actions">
          <button
            className="icon-button compact"
            disabled={!codePath}
            onClick={() => void copyText(codePath)}
            title="复制代码路径"
            type="button"
          >
            <Copy size={14} />
            路径
          </button>
          <button
            className="icon-button compact"
            disabled={!codePath || busy}
            onClick={codeVisible ? onToggleCode : () => onLoadCode(version ?? undefined)}
            title="查看版本 workflow.py"
            type="button"
          >
            <FileJson size={14} />
            {codeVisible ? "收起" : code ? "刷新" : "代码"}
          </button>
          <button
            className="icon-button compact"
            disabled={busy}
            onClick={onCleanupGenerated}
            title="清理未引用的生成目录"
            type="button"
          >
            <Trash2 size={14} />
            清理
          </button>
        </div>
      </div>
      {codeModified ? (
        <div className="version-code-warning">
          <strong>Hash 已变更</strong>
          <span>发布：{shortHash(codeHash)} · 本地：{shortHash(actualHash)}</span>
        </div>
      ) : null}
      <details className="version-code-details">
        <summary>代码产物详情</summary>
        <div className="version-code-detail-grid">
          <div>
            <span>路径</span>
            <code title={codePath ?? undefined}>{version ? (codePath ?? "未生成") : "版本详情未加载"}</code>
          </div>
          <div>
            <span>完整 Hash</span>
            <code title={codeHash ?? undefined}>{version ? (codeHash ?? "未生成") : "版本详情未加载"}</code>
          </div>
          <div>
            <span>本地 Hash</span>
            <code title={actualHash ?? undefined}>{version ? (actualHash ?? "未读取") : "版本详情未加载"}</code>
          </div>
          <div>
            <span>Version ID</span>
            <strong>{version?.id ?? workflow.current_version_id}</strong>
          </div>
        </div>
      </details>
      {cleanupReport ? (
        <div className="version-code-cleanup">
          <span>目录清理</span>
          <strong>{cleanupReport.dry_run ? "预览" : "已清理"} {cleanupReport.removed_total} 项</strong>
          <small>temp {cleanupReport.removed_temp_dirs.length} · orphan {cleanupReport.removed_orphan_version_dirs.length}</small>
        </div>
      ) : null}
      {versions.length > 0 ? (
        <div className="version-history">
          <div className="version-history-header">
            <span>版本代码</span>
            <strong>{versions.length} 个版本</strong>
          </div>
          <div className="version-history-list">
            {versions.map((item) => {
              const itemStatus = formatCodeStatus(item.code_status, item.code_path ? "已生成" : "未生成");
              const canRegenerate = item.code_status !== "ok" || item.code_modified === true;
              return (
                <div className="version-history-item" key={item.id}>
                  <button
                    className={selectedCodeVersion?.id === item.id && codeVisible ? "version-history-main active" : "version-history-main"}
                    disabled={busy}
                    onClick={() => onLoadCode(item)}
                    type="button"
                  >
                    <span>v{item.version}</span>
                    <strong className={item.code_modified ? "warning-text" : ""}>{itemStatus}</strong>
                    <small title={item.code_hash ?? undefined}>{shortHash(item.code_hash)}</small>
                  </button>
                  <button
                    className="text-button"
                    disabled={busy || !canRegenerate}
                    onClick={() => onRegenerateCode(item)}
                    title={item.code_modified ? "覆盖本地 hash 已变更的代码" : "从发布图重新生成 workflow.py"}
                    type="button"
                  >
                    重生成
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
      {codeVisible && code ? (
        <div className="version-code-source-box">
          <div>
            <span>{visibleCodeLabel} / workflow.py</span>
            <button className="text-button" onClick={() => void copyText(code.source)} type="button">
              复制代码
            </button>
          </div>
          <pre>
            <code>{code.source}</code>
          </pre>
        </div>
      ) : null}
    </section>
  );
}

export function RunHistoryView({
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

export function TraceView({ trace, onSelectNode }: { trace: RunTrace; onSelectNode: (nodeId: string) => void }) {
  const output = trace.run.output_json ? JSON.stringify(trace.run.output_json, null, 2) : "{}";
  const metadata = trace.run.metadata_json ?? {};
  const runId = getRunId(trace.run);
  return (
    <div className="trace">
      <section className="trace-summary">
        <div>
          <span>Run</span>
          <strong>{runId ? `#${runId}` : "-"}</strong>
        </div>
        <div>
          <span>Status</span>
          <strong>{trace.run.status}</strong>
        </div>
        <div>
          <span>Nodes</span>
          <strong>{trace.nodes.length}</strong>
        </div>
      </section>
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
          <span>code_hash_published</span>
          <code>{metadataText(metadata.code_hash_published)}</code>
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

export function StructuredNodeConfig({
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
        <label>
          <span>context_budget_tokens</span>
          <input
            min={1}
            type="number"
            value={configNumber(config, "context_budget_tokens", 3000)}
            onChange={(event) => onConfigChange({ context_budget_tokens: Number(event.target.value) })}
          />
        </label>
      </section>
    );
  }

  if (node.type === "llm") {
    const provider = configString(config, "provider", "deepseek");
    const model = configString(
      config,
      "model",
      provider === "mock" ? "local-mock" : provider === "deepseek" ? "deepseek-v4-flash" : "gpt-4.1-mini",
    );
    const selectedModelConfigId = String(config.model_config_id ?? "");
    return (
      <section className="structured-node-config">
        <div className="node-subheading">
          <Bot size={14} />
          LLM 配置
        </div>
        <label>
          <span>model_config</span>
          <select
            value={selectedModelConfigId}
            onChange={(event) => {
              const modelConfigId = Number(event.target.value);
              const modelConfig = chatModels.find((item) => item.id === modelConfigId);
              onConfigChange({
                model_config_id: Number.isFinite(modelConfigId) && modelConfigId > 0 ? modelConfigId : null,
                model: modelConfig?.model_name ?? model,
              });
            }}
          >
            <option value="">不绑定模型配置</option>
            {chatModels.map((modelConfig) => (
              <option key={modelConfig.id} value={modelConfig.id}>
                #{modelConfig.id} · {modelConfig.display_name ?? modelConfig.model_name}
              </option>
            ))}
          </select>
        </label>
        <div className="inline-fields">
          <label>
            <span>provider</span>
            <select value={provider} onChange={(event) => onConfigChange({ provider: event.target.value })}>
              <option value="mock">mock</option>
              <option value="deepseek">deepseek</option>
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
