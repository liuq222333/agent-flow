import argparse
import json
import os
import time
import urllib.error
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
    timeout: int,
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


def deepseek_workflow_graph(model: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "nodes": [
            node(
                "start_1",
                "start",
                80,
                {"fields": [{"name": "rawQuery", "type": "string", "required": True}]},
            ),
            {
                **node(
                    "llm_1",
                    "llm",
                    360,
                    {
                        "provider": "deepseek",
                        "model": model,
                        "system_prompt": "You are a concise workflow acceptance checker.",
                        "user_prompt": (
                            "Return one short sentence confirming this check phrase: "
                            "{{query}}"
                        ),
                        "temperature": 0,
                    },
                ),
                "input_mapping": {"query": "{{input.rawQuery}}"},
                "output_mapping": {"output": "variables.output", "answer": "variables.answer"},
            },
            node(
                "end_1",
                "end",
                640,
                {"outputs": {"output": "{{outputs.llm_1.output}}", "rawQuery": "{{input.rawQuery}}"}},
            ),
        ],
        "edges": linear_edges(["start_1", "llm_1", "end_1"]),
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


def run_id_of(run: dict[str, Any]) -> int:
    return int(run["id"] if "id" in run else run["run_id"])


def output_of(run: dict[str, Any]) -> dict[str, Any]:
    return run.get("output_json") or run.get("output") or {}


def poll_run(
    run_id: int,
    *,
    base_url: str,
    token: str | None,
    request_timeout: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        last = request(
            "GET",
            f"/runs/{run_id}",
            base_url=base_url,
            token=token,
            timeout=request_timeout,
        )
        if last and last.get("status") in TERMINAL_STATUSES:
            return last
        time.sleep(1)
    raise RuntimeError(f"timed out waiting for run {run_id}: {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real DeepSeek LLM workflow check.")
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
    parser.add_argument(
        "--model",
        default=os.environ.get("DEEPSEEK_ACCEPTANCE_MODEL", "deepseek-v4-flash"),
        help="DeepSeek model configured for the LLM node.",
    )
    parser.add_argument("--timeout", type=int, default=120, help="Polling timeout in seconds.")
    args = parser.parse_args()

    stamp = uuid.uuid4().hex[:8]
    base_url = args.base_url.rstrip("/")
    health = request("GET", "/health", base_url=base_url, token=args.token, timeout=30)
    ready = request("GET", "/ready", base_url=base_url, token=args.token, timeout=30)
    workflow = request(
        "POST",
        "/workflows",
        {
            "name": f"DeepSeek Real Acceptance {stamp}",
            "draft_graph_json": deepseek_workflow_graph(args.model),
        },
        base_url=base_url,
        token=args.token,
        timeout=30,
    )
    published = request(
        "POST",
        f"/workflows/{workflow['id']}/publish",
        {"release_note": "deepseek real acceptance"},
        base_url=base_url,
        token=args.token,
        timeout=30,
    )
    run = request(
        "POST",
        f"/workflows/{workflow['id']}/run",
        {
            "input": {"rawQuery": f"deepseek acceptance {stamp}"},
            "trigger_type": "test",
            "execution_mode": "async",
        },
        base_url=base_url,
        token=args.token,
        timeout=30,
    )
    final_run = poll_run(
        run_id_of(run),
        base_url=base_url,
        token=args.token,
        request_timeout=30,
        timeout_seconds=args.timeout,
    )
    if final_run.get("status") != "completed":
        raise RuntimeError(f"DeepSeek run did not complete: {final_run}")

    output = output_of(final_run)
    answer = str(output.get("output") or output.get("answer") or "").strip()
    if not answer:
        raise RuntimeError(f"DeepSeek run completed without answer output: {final_run}")

    trace = request(
        "GET",
        f"/runs/{run_id_of(final_run)}/trace",
        base_url=base_url,
        token=args.token,
        timeout=30,
    )
    llm_nodes = [
        item
        for item in (trace or {}).get("nodes", [])
        if item.get("node_id") == "llm_1" and item.get("status") == "success"
    ]
    if not llm_nodes:
        raise RuntimeError(f"DeepSeek trace missing successful llm node: {trace}")

    print(
        json.dumps(
            {
                "health": health.get("status") if health else None,
                "ready": ready.get("status") if ready else None,
                "workflow_id": workflow["id"],
                "version_id": published.get("id") or published.get("version_id"),
                "code_path": published.get("code_path"),
                "run_id": run_id_of(final_run),
                "final_status": final_run["status"],
                "model": args.model,
                "answer_preview": answer[:160],
                "trace_nodes": [item.get("node_id") for item in (trace or {}).get("nodes", [])],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
