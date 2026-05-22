import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = os.environ.get("API_BASE_URL") or os.environ.get(
    "NEXT_PUBLIC_API_BASE_URL",
    "http://localhost:8000/api/v1",
)


def request(method, path, data=None, headers=None, body=None, timeout=30):
    request_headers = dict(headers or {})
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {raw}") from exc


def multipart_upload(path, file_name, content):
    boundary = "----agentflow" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode(),
            b"Content-Type: text/plain\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return request(
        "POST",
        path,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        body=body,
        timeout=60,
    )


def poll_resource(path, terminal_statuses, timeout_seconds=60):
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        last = request("GET", path)
        if last["status"] in terminal_statuses:
            return last
        time.sleep(1)
    raise RuntimeError(f"timed out polling {path}: {last}")


def mock_workflow_graph():
    return {
        "schema_version": "1.0",
        "nodes": [
            node(
                "start_1",
                "start",
                80,
                {
                    "fields": [
                        {"name": "rawQuery", "type": "string", "required": True},
                        {"name": "chatHistory", "type": "array"},
                    ]
                },
            ),
            {
                **node(
                    "llm_1",
                    "llm",
                    360,
                    {
                        "provider": "mock",
                        "model": "local-mock",
                        "user_prompt": "Question: {{query}}",
                    },
                ),
                "input_mapping": {"query": "{{input.rawQuery}}"},
                "output_mapping": {"output": "variables.output", "answer": "variables.answer"},
            },
            node(
                "end_1",
                "end",
                640,
                {
                    "response_mode": "template",
                    "outputs": {
                        "output": "{{outputs.llm_1.output}}",
                        "rawQuery": "{{outputs.start_1.rawQuery}}",
                    },
                    "template": "{{output}}：{{rawQuery}}",
                },
            ),
        ],
        "edges": linear_edges(["start_1", "llm_1", "end_1"]),
    }


def knowledge_workflow_graph(knowledge_base_id):
    return {
        "schema_version": "1.0",
        "nodes": [
            node("start_1", "start", 80, {}),
            node(
                "input_1",
                "input",
                280,
                {"fields": [{"name": "user_query", "type": "string", "required": True}]},
            ),
            {
                **node(
                    "kb_1",
                    "knowledge_base",
                    500,
                    {
                        "knowledge_base_ids": [knowledge_base_id],
                        "query": "{{question}}",
                        "top_k": 3,
                        "score_threshold": 0.0,
                    },
                ),
                "input_mapping": {"question": "{{input.user_query}}"},
                "output_mapping": {"chunks": "variables.kb_context"},
            },
            {
                **node(
                    "llm_1",
                    "llm",
                    720,
                    {
                        "provider": "mock",
                        "model": "local-mock",
                        "system_prompt": "You answer from retrieved knowledge chunks.",
                        "user_prompt": (
                            "Question: {{input.user_query}}\n"
                            "Sources: {{variables.kb_context}}"
                        ),
                    },
                ),
                "input_mapping": {
                    "question": "{{input.user_query}}",
                    "context": "{{variables.kb_context}}",
                },
                "output_mapping": {"answer": "variables.answer"},
            },
            node(
                "output_1",
                "output",
                940,
                {
                    "outputs": {
                        "answer": "{{variables.answer}}",
                        "sources": "{{variables.kb_context}}",
                        "chunks": "{{variables.kb_context}}",
                    }
                },
            ),
            node("end_1", "end", 1160, {}),
        ],
        "edges": linear_edges(["start_1", "input_1", "kb_1", "llm_1", "output_1", "end_1"]),
    }


def intent_branch_workflow_graph():
    return {
        "schema_version": "1.0",
        "nodes": [
            node("start_1", "start", 80, {}),
            node(
                "input_1",
                "input",
                260,
                {"fields": [{"name": "user_query", "type": "string", "required": True}]},
            ),
            {
                **node(
                    "intent_1",
                    "intent",
                    440,
                    {
                        "provider": "keyword",
                        "model": "local-keyword",
                        "query": "{{input.user_query}}",
                        "intents": [
                            {
                                "name": "refund",
                                "description": "refund billing payment invoice",
                            },
                            {
                                "name": "sales",
                                "description": "sales pricing quote purchase",
                            },
                        ],
                        "fallback_intent": "other",
                    },
                ),
                "output_mapping": {
                    "intent": "variables.intent",
                    "confidence": "variables.intent_confidence",
                },
            },
            node(
                "branch_1",
                "branch",
                620,
                {
                    "branches": [
                        {
                            "id": "refund_path",
                            "condition": {
                                "left": "{{variables.intent}}",
                                "operator": "eq",
                                "right": "refund",
                            },
                            "target": "message_refund",
                        },
                        {
                            "id": "fallback_path",
                            "condition": True,
                            "target": "message_other",
                        },
                    ]
                },
            ),
            {
                **node(
                    "message_refund",
                    "message",
                    800,
                    {
                        "message_type": "text",
                        "template": "refund branch handled {{input.user_query}}",
                    },
                ),
                "output_mapping": {"message": "variables.branch_message"},
            },
            {
                **node(
                    "message_other",
                    "message",
                    800,
                    {
                        "message_type": "text",
                        "template": "fallback branch handled {{input.user_query}}",
                    },
                ),
                "output_mapping": {"message": "variables.branch_message"},
            },
            node(
                "output_1",
                "output",
                980,
                {
                    "outputs": {
                        "intent": "{{variables.intent}}",
                        "confidence": "{{variables.intent_confidence}}",
                        "branch_message": "{{variables.branch_message}}",
                        "path": "{{path}}",
                    }
                },
            ),
            node("end_1", "end", 1160, {}),
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "input_1"},
            {"id": "e2", "source": "input_1", "target": "intent_1"},
            {"id": "e3", "source": "intent_1", "target": "branch_1"},
            {"id": "e4", "source": "branch_1", "target": "message_refund"},
            {"id": "e5", "source": "branch_1", "target": "message_other"},
            {"id": "e6", "source": "message_refund", "target": "output_1"},
            {"id": "e7", "source": "message_other", "target": "output_1"},
            {"id": "e8", "source": "output_1", "target": "end_1"},
        ],
    }


def api_message_workflow_graph(secret_key):
    return {
        "schema_version": "1.0",
        "nodes": [
            node("start_1", "start", 80, {}),
            node(
                "input_1",
                "input",
                260,
                {
                    "fields": [
                        {"name": "user_query", "type": "string", "required": True},
                        {"name": "customer_id", "type": "string", "required": True},
                    ]
                },
            ),
            {
                **node(
                    "api_1",
                    "api",
                    440,
                    {
                        "mode": "mock",
                        "method": "POST",
                        "url": "https://api.example.test/tickets",
                        "headers": {
                            "Authorization": f"Bearer {{{{secrets.{secret_key}}}}}",
                            "X-Smoke-Run": "{{input.customer_id}}",
                        },
                        "body": {
                            "customer": "{{input.customer_id}}",
                            "query": "{{input.user_query}}",
                            "source": "smoke",
                        },
                        "mock_status_code": 202,
                        "mock_response": {
                            "ticket_id": "SMK-{{input.customer_id}}",
                            "customer": "{{input.customer_id}}",
                            "summary": "created for {{input.user_query}}",
                        },
                    },
                ),
                "output_mapping": {
                    "response": "variables.api_response",
                    "status": "variables.api_status",
                },
            },
            {
                **node(
                    "message_1",
                    "message",
                    620,
                    {
                        "message_type": "text",
                        "template": (
                            "Ticket {{variables.api_response.ticket_id}} for "
                            "{{variables.api_response.customer}}: {{input.user_query}}"
                        ),
                    },
                ),
                "output_mapping": {"message": "variables.message_text"},
            },
            node(
                "output_1",
                "output",
                800,
                {
                    "outputs": {
                        "ticket_id": "{{variables.api_response.ticket_id}}",
                        "message": "{{variables.message_text}}",
                        "api_status": "{{variables.api_status}}",
                        "api_request_body": "{{outputs.api_1.request.body}}",
                        "api_authorization_header": (
                            "{{outputs.api_1.request.headers.Authorization}}"
                        ),
                    }
                },
            ),
            node("end_1", "end", 980, {}),
        ],
        "edges": linear_edges(["start_1", "input_1", "api_1", "message_1", "output_1", "end_1"]),
    }


def node(node_id, node_type, x, config):
    return {
        "id": node_id,
        "type": node_type,
        "name": node_type,
        "position": {"x": x, "y": 160},
        "config": config,
    }


def linear_edges(node_ids):
    return [
        {"id": f"e{index}", "source": source, "target": target}
        for index, (source, target) in enumerate(
            zip(node_ids[:-1], node_ids[1:], strict=True),
            start=1,
        )
    ]


def assert_completed_run(workflow_id, mode, input_data):
    run = request(
        "POST",
        f"/workflows/{workflow_id}/run",
        {"input": input_data, "trigger_type": "test", "execution_mode": mode},
    )
    if mode == "async":
        run = poll_resource(f"/runs/{run['run_id']}", {"completed", "failed", "cancelled"})
    if run["status"] != "completed":
        raise RuntimeError(f"{mode} run failed: {run}")
    trace = request("GET", f"/runs/{run['id' if 'id' in run else 'run_id']}/trace")
    if len(trace.get("nodes", [])) < 1:
        raise RuntimeError(f"{mode} trace missing node runs: {trace}")
    return run, trace


def run_id_of(run):
    return run["id"] if "id" in run else run["run_id"]


def output_of(run):
    return run.get("output_json") or run.get("output") or {}


def node_trace(trace, node_id):
    for item in trace.get("nodes", []):
        if item.get("node_id") == node_id:
            return item
    raise RuntimeError(f"trace missing node {node_id}: {trace}")


def assert_published_code_path(published):
    if not str(published.get("code_path", "")).startswith("backend/generated_workflows/"):
        raise RuntimeError(f"unexpected code_path: {published.get('code_path')}")


def assert_intent_branch_run(run, trace):
    output = output_of(run)
    path = output.get("path") or trace.get("run", {}).get("state_json", {}).get("path") or []
    if output.get("intent") != "refund":
        raise RuntimeError(f"intent workflow chose wrong intent: {output}")
    if "message_refund" not in path or "message_other" in path:
        raise RuntimeError(f"intent workflow chose wrong branch path: {path}")
    if "refund branch handled" not in str(output.get("branch_message")):
        raise RuntimeError(f"intent workflow final output missing branch proof: {output}")

    intent_output = node_trace(trace, "intent_1").get("output_json") or {}
    branch_output = node_trace(trace, "branch_1").get("output_json") or {}
    if intent_output.get("intent") != "refund":
        raise RuntimeError(f"trace intent output mismatch: {intent_output}")
    if branch_output.get("selected") != "message_refund":
        raise RuntimeError(f"trace branch output mismatch: {branch_output}")
    return path


def assert_api_message_run(run, trace, secret_value):
    output = output_of(run)
    expected_body = {
        "customer": "cust-42",
        "query": "open billing ticket",
        "source": "smoke",
    }
    if output.get("ticket_id") != "SMK-cust-42":
        raise RuntimeError(f"api workflow ticket mapping failed: {output}")
    if output.get("api_status") != "mocked":
        raise RuntimeError(f"api workflow status mapping failed: {output}")
    if output.get("api_request_body") != expected_body:
        raise RuntimeError(f"api workflow request body mapping failed: {output}")
    if "Ticket SMK-cust-42 for cust-42" not in str(output.get("message")):
        raise RuntimeError(f"message workflow output mapping failed: {output}")
    if output.get("api_authorization_header") != "Bearer ***":
        raise RuntimeError(f"api workflow did not expose redacted header: {output}")

    api_output = node_trace(trace, "api_1").get("output_json") or {}
    api_request = api_output.get("request") or {}
    if api_request.get("body") != expected_body:
        raise RuntimeError(f"trace api request body mapping failed: {api_request}")
    if api_request.get("headers", {}).get("Authorization") != "Bearer ***":
        raise RuntimeError(f"trace api authorization header was not redacted: {api_request}")

    trace_text = json.dumps(trace, ensure_ascii=False, default=str)
    if secret_value in trace_text:
        raise RuntimeError("trace leaked sensitive header value in plaintext")


def main():
    stamp = uuid.uuid4().hex[:8]
    health = request("GET", "/health")
    ready = request("GET", "/ready")

    kb = request(
        "POST",
        "/knowledge-bases",
        {"name": f"Smoke KB {stamp}", "embedding_model": "local-hash"},
    )
    upload = multipart_upload(
        f"/knowledge-bases/{kb['id']}/documents",
        f"refund-policy-{stamp}.txt",
        b"Refund policy billing refund request payment verified within 30 days.",
    )
    document = poll_resource(
        f"/documents/{upload['document_id']}",
        {"indexed", "failed", "deleted"},
    )
    if document["status"] != "indexed":
        raise RuntimeError(f"document was not indexed: {document}")
    retrieved = request(
        "POST",
        f"/knowledge-bases/{kb['id']}/retrieve",
        {"query": "refund billing", "top_k": 3, "score_threshold": 0},
    )
    if not retrieved.get("chunks"):
        raise RuntimeError("knowledge retrieve returned no chunks")
    if retrieved["chunks"][0].get("retrieval_mode") != "vector":
        raise RuntimeError(f"knowledge retrieve did not use vector mode: {retrieved['chunks'][0]}")

    workflow = request(
        "POST",
        "/workflows",
        {"name": f"Smoke Mock {stamp}", "draft_graph_json": mock_workflow_graph()},
    )
    published = request(
        "POST",
        f"/workflows/{workflow['id']}/publish",
        {"release_note": "smoke"},
    )
    assert_published_code_path(published)
    sync_run, _ = assert_completed_run(workflow["id"], "sync", {"rawQuery": "refund"})
    async_run, _ = assert_completed_run(workflow["id"], "async", {"rawQuery": "async refund"})

    kb_workflow = request(
        "POST",
        "/workflows",
        {
            "name": f"Smoke KB Runtime {stamp}",
            "draft_graph_json": knowledge_workflow_graph(kb["id"]),
        },
    )
    kb_published = request(
        "POST",
        f"/workflows/{kb_workflow['id']}/publish",
        {"release_note": "kb smoke"},
    )
    kb_run, _ = assert_completed_run(kb_workflow["id"], "sync", {"user_query": "refund billing"})
    kb_output = kb_run.get("output_json", kb_run.get("output", {}))
    kb_chunks = kb_output.get("sources") or kb_output.get("chunks") or []
    if not kb_chunks:
        raise RuntimeError(f"knowledge workflow returned no chunks: {kb_run}")
    if not kb_output.get("answer"):
        raise RuntimeError(f"knowledge workflow returned no answer: {kb_run}")

    intent_workflow = request(
        "POST",
        "/workflows",
        {
            "name": f"Smoke Intent Branch {stamp}",
            "draft_graph_json": intent_branch_workflow_graph(),
        },
    )
    intent_published = request(
        "POST",
        f"/workflows/{intent_workflow['id']}/publish",
        {"release_note": "intent branch smoke"},
    )
    assert_published_code_path(intent_published)
    intent_run, intent_trace = assert_completed_run(
        intent_workflow["id"],
        "sync",
        {"user_query": "refund billing payment help"},
    )
    intent_path = assert_intent_branch_run(intent_run, intent_trace)

    secret_key = f"smoke_api_token_{stamp}"
    secret_value = f"smoke-secret-{stamp}"
    secret = request(
        "POST",
        "/secrets",
        {
            "secret_key": secret_key,
            "display_name": f"Smoke API Token {stamp}",
            "value": secret_value,
        },
    )
    api_workflow = request(
        "POST",
        "/workflows",
        {
            "name": f"Smoke API Message {stamp}",
            "draft_graph_json": api_message_workflow_graph(secret_key),
        },
    )
    api_published = request(
        "POST",
        f"/workflows/{api_workflow['id']}/publish",
        {"release_note": "api message smoke"},
    )
    assert_published_code_path(api_published)
    api_run, api_trace = assert_completed_run(
        api_workflow["id"],
        "sync",
        {"user_query": "open billing ticket", "customer_id": "cust-42"},
    )
    assert_api_message_run(api_run, api_trace, secret_value)
    api_output = output_of(api_run)

    print(
        json.dumps(
            {
                "health": health.get("status"),
                "ready": ready.get("status"),
                "knowledge_base_id": kb["id"],
                "document_id": upload["document_id"],
                "document_status": document["status"],
                "retrieved_chunks": len(retrieved["chunks"]),
                "retrieve_mode": retrieved["chunks"][0].get("retrieval_mode"),
                "workflow_id": workflow["id"],
                "code_path": published["code_path"],
                "sync_run_id": run_id_of(sync_run),
                "async_run_id": run_id_of(async_run),
                "kb_workflow_id": kb_workflow["id"],
                "kb_code_path": kb_published["code_path"],
                "kb_run_id": run_id_of(kb_run),
                "kb_output_chunks": len(kb_chunks),
                "intent_workflow_id": intent_workflow["id"],
                "intent_code_path": intent_published["code_path"],
                "intent_run_id": run_id_of(intent_run),
                "intent_output": {
                    "intent": output_of(intent_run).get("intent"),
                    "path": intent_path,
                    "branch_message": output_of(intent_run).get("branch_message"),
                },
                "api_workflow_id": api_workflow["id"],
                "api_code_path": api_published["code_path"],
                "api_run_id": run_id_of(api_run),
                "api_secret_id": secret["id"],
                "api_output": {
                    "ticket_id": api_output.get("ticket_id"),
                    "message": api_output.get("message"),
                    "api_status": api_output.get("api_status"),
                    "authorization_header": api_output.get("api_authorization_header"),
                },
                "api_trace_secret_redacted": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
