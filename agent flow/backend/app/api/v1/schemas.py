from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JsonObject = dict[str, Any]


class Position(BaseModel):
    x: float
    y: float


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: Literal[
        "start",
        "input",
        "llm",
        "knowledge_base",
        "intent",
        "branch",
        "api",
        "message",
        "output",
        "end",
    ]
    name: str
    position: Position
    config: JsonObject = Field(default_factory=dict)
    description: str | None = None
    input_mapping: JsonObject | None = None
    output_mapping: JsonObject | None = None
    enabled: bool = True


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: str
    target: str
    label: str | None = None
    condition: str | JsonObject | None = None


class WorkflowGraph(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class CreateWorkflowRequest(BaseModel):
    name: str
    description: str | None = None
    draft_graph_json: WorkflowGraph | None = None


class UpdateWorkflowRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    draft_graph_json: WorkflowGraph | None = None


class ValidateGraphRequest(BaseModel):
    mode: Literal["draft", "publish", "run"] = "draft"
    graph_json: WorkflowGraph


class PublishWorkflowRequest(BaseModel):
    release_note: str | None = None


class RunWorkflowRequest(BaseModel):
    input: JsonObject = Field(default_factory=dict)
    version_id: int | None = None
    trigger_type: Literal["manual", "api", "test"] = "manual"
    execution_mode: Literal["sync", "async"] = "sync"


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: str | None = None
    embedding_model: str
    embedding_dim: Literal[1536] = 1536
    tokenizer: str = "cl100k_base"
    slug: str | None = None
    config: JsonObject = Field(default_factory=dict)


class RetrieveKnowledgeRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class CreateToolRequest(BaseModel):
    name: str
    type: Literal["api"]
    description: str | None = None
    config: JsonObject = Field(default_factory=dict)


class TestToolRequest(BaseModel):
    input: JsonObject = Field(default_factory=dict)


class CreateSecretRequest(BaseModel):
    secret_key: str
    display_name: str | None = None
    value: str


class UpdateSecretRequest(BaseModel):
    display_name: str | None = None
    value: str | None = None
