import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000/api/v1"
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def request(
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    *,
    base_url: str,
    token: str | None,
    timeout: int = 30,
) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {raw}") from exc


def human_approval_workflow_graph() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "nodes": [
            node("start_1", "start", 80, {}),
            node(
                "input_1",
                "input",
                280,
                {
                    "fields": [
                        {"name": "request_id", "type": "string", "required": True},
                        {"name": "amount", "type": "number", "required": True},
                    ]
                },
            ),
            {
                **node(
                    "approval_1",
                    "human_approval",
                    500,
                    {
                        "title": "Smoke Human Approval",
                        "description": "Approve request {{input.request_id}}",
                        "input": {
                            "request_id": "{{input.request_id}}",
                            "amount": "{{input.amount}}",
                        },
                        "approval_schema": {
                            "required": ["approved"],
                            "properties": {"approved": {"type": "boolean"}},
                        },
                        "timeout_seconds": 3600,
                    },
                ),
                "output_mapping": {
                    "decision": "variables.approval_decision",
                    "approved": "variables.approved",
                    "comment": "variables.approval_comment",
                },
            },
            node(
                "output_1",
                "output",
                720,
                {
                    "outputs": {
                        "request_id": "{{input.request_id}}",
                        "decision": "{{variables.approval_decision}}",
                        "approved": "{{variables.approved}}",
                        "comment": "{{variables.approval_comment}}",
                    }
                },
            ),
            node("end_1", "end", 920, {}),
        ],
        "edges": linear_edges(["start_1", "input_1", "approval_1", "output_1", "end_1"]),
    }


def node(node_id: str, node_type: str, x: int, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": node_type,
        "position": {"x": x, "y": 160},
        "config": config,
    }


def linear_edges(node_ids: list[str]) -> list[dict[str, str]]:
    return [
        {"id": f"e{index}", "source": source, "target": target}
        for index, (source, target) in enumerate(
            zip(node_ids[:-1], node_ids[1:], strict=True),
            start=1,
        )
    ]


def poll_run_status(
    run_id: int,
    expected_statuses: set[str],
    *,
    base_url: str,
    token: str | None,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        last = request("GET", f"/runs/{run_id}", base_url=base_url, token=token)
        if last and last.get("status") in expected_statuses:
            return last
        time.sleep(poll_interval_seconds)
    raise RuntimeError(f"timed out waiting for run {run_id}: {last}")


def poll_pending_approval_task(
    run_id: int,
    *,
    base_url: str,
    token: str | None,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = None
    query = urllib.parse.urlencode({"run_id": run_id, "status": "pending", "page_size": 10})
    while time.time() < deadline:
        last = request(
            "GET",
            f"/human-approval-tasks?{query}",
            base_url=base_url,
            token=token,
        )
        items = last.get("items", []) if last else []
        if items:
            return items[0]
        time.sleep(poll_interval_seconds)
    raise RuntimeError(f"timed out waiting for pending approval task for run {run_id}: {last}")


def assert_trace(run_id: int, *, base_url: str, token: str | None) -> dict[str, Any]:
    trace = request("GET", f"/runs/{run_id}/trace", base_url=base_url, token=token)
    nodes = trace.get("nodes", []) if trace else []
    approval_node = trace_node(nodes, "approval_1")
    output_node = trace_node(nodes, "output_1")
    approval_output = approval_node.get("output_json") or {}
    output_json = output_node.get("output_json") or {}

    if approval_node.get("status") not in {"waiting_approval", "success"}:
        raise RuntimeError(f"approval trace node has unexpected status: {approval_node}")
    if not approval_output.get("task_id"):
        raise RuntimeError(f"approval trace node missing task id: {approval_node}")
    if output_node.get("status") != "success":
        raise RuntimeError(f"output trace node did not complete: {output_node}")
    if output_json.get("decision") != "approve" or output_json.get("approved") is not True:
        raise RuntimeError(f"output trace did not include approval decision: {output_json}")
    return trace


def trace_node(nodes: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    for item in nodes:
        if item.get("node_id") == node_id:
            return item
    raise RuntimeError(f"trace missing node {node_id}: {nodes}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Human Approval smoke flow.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AGENT_FLOW_BASE_URL", DEFAULT_BASE_URL),
        help="API base URL. Defaults to AGENT_FLOW_BASE_URL or localhost.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AGENT_FLOW_API_TOKEN") or os.environ.get("API_BEARER_TOKEN"),
        help="Bearer token when auth_mode=bearer.",
    )
    parser.add_argument("--timeout", type=int, default=120, help="Polling timeout in seconds.")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval.")
    args = parser.parse_args()

    stamp = uuid.uuid4().hex[:8]
    base_url = args.base_url.rstrip("/")
    token = args.token
    input_payload = {"request_id": f"smoke-approval-{stamp}", "amount": 128.5}

    health = request("GET", "/health", base_url=base_url, token=token)
    workflow = request(
        "POST",
        "/workflows",
        {
            "name": f"Smoke Human Approval {stamp}",
            "draft_graph_json": human_approval_workflow_graph(),
        },
        base_url=base_url,
        token=token,
    )
    published = request(
        "POST",
        f"/workflows/{workflow['id']}/publish",
        {"release_note": "human approval smoke"},
        base_url=base_url,
        token=token,
    )
    run = request(
        "POST",
        f"/workflows/{workflow['id']}/run",
        {"input": input_payload, "trigger_type": "test", "execution_mode": "async"},
        base_url=base_url,
        token=token,
    )
    run_id = int(run["run_id"])

    waiting_run = poll_run_status(
        run_id,
        {"waiting_approval", "failed", "cancelled"},
        base_url=base_url,
        token=token,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )
    if waiting_run["status"] != "waiting_approval":
        raise RuntimeError(f"run did not wait for approval: {waiting_run}")

    task = poll_pending_approval_task(
        run_id,
        base_url=base_url,
        token=token,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )
    submitted = request(
        "POST",
        f"/human-approval-tasks/{task['id']}/submit",
        {
            "decision": "approve",
            "response": {"approved": True, "reviewer": "smoke"},
            "comment": f"approved by smoke {stamp}",
        },
        base_url=base_url,
        token=token,
    )

    final_run = poll_run_status(
        run_id,
        TERMINAL_STATUSES,
        base_url=base_url,
        token=token,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )
    if final_run["status"] != "completed":
        raise RuntimeError(f"run did not complete after approval: {final_run}")

    output = final_run.get("output_json") or final_run.get("output") or {}
    if output.get("decision") != "approve" or output.get("approved") is not True:
        raise RuntimeError(f"run output did not include approval decision: {output}")

    trace = assert_trace(run_id, base_url=base_url, token=token)
    print(
        json.dumps(
            {
                "health": health.get("status") if health else None,
                "workflow_id": workflow["id"],
                "version_id": published.get("id"),
                "code_path": published.get("code_path"),
                "run_id": run_id,
                "waiting_status": waiting_run["status"],
                "approval_task_id": task["id"],
                "approval_submit_status": submitted.get("status") if submitted else None,
                "final_status": final_run["status"],
                "output": output,
                "trace_nodes": [item.get("node_id") for item in trace.get("nodes", [])],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
