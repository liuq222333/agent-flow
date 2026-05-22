import json
import uuid

from smoke_e2e import (
    api_message_workflow_graph,
    assert_api_message_run,
    assert_completed_run,
    assert_intent_branch_run,
    assert_published_code_path,
    intent_branch_workflow_graph,
    mock_workflow_graph,
    output_of,
    request,
    run_id_of,
)


def assert_trace_code_metadata(trace):
    metadata = trace.get("run", {}).get("metadata_json") or {}
    code_path = metadata.get("code_path_at_run")
    code_hash = metadata.get("code_hash_at_run")
    if "/generated_workflows/" not in f"/{code_path or ''}":
        raise RuntimeError(f"trace missing generated code path: {metadata}")
    if not str(code_hash or "").startswith("sha256:"):
        raise RuntimeError(f"trace missing code hash: {metadata}")
    if metadata.get("runtime") != "generated_workflow":
        raise RuntimeError(f"trace did not use generated runtime: {metadata}")
    if metadata.get("code_modified") not in (True, False):
        raise RuntimeError(f"trace missing code_modified flag: {metadata}")


def main():
    stamp = uuid.uuid4().hex[:8]
    health = request("GET", "/health")
    ready = request("GET", "/ready")

    mock_workflow = request(
        "POST",
        "/workflows",
        {"name": f"Core Smoke Mock {stamp}", "draft_graph_json": mock_workflow_graph()},
    )
    mock_published = request(
        "POST",
        f"/workflows/{mock_workflow['id']}/publish",
        {"release_note": "core smoke mock"},
    )
    assert_published_code_path(mock_published)
    code = request("GET", f"/workflow-versions/{mock_published['version_id']}/code")
    if "async def run" not in code.get("source", ""):
        raise RuntimeError("generated workflow.py missing async run entrypoint")
    if code.get("code_status") not in {"ok", "modified"}:
        raise RuntimeError(f"unexpected code status: {code.get('code_status')}")
    mock_run, mock_trace = assert_completed_run(
        mock_workflow["id"],
        "sync",
        {"rawQuery": "core smoke"},
    )
    mock_output = output_of(mock_run)
    if "core smoke" not in str(mock_output.get("output")):
        raise RuntimeError(f"template output did not render selected parameters: {mock_output}")
    assert_trace_code_metadata(mock_trace)

    intent_workflow = request(
        "POST",
        "/workflows",
        {
            "name": f"Core Smoke Intent {stamp}",
            "draft_graph_json": intent_branch_workflow_graph(),
        },
    )
    intent_published = request(
        "POST",
        f"/workflows/{intent_workflow['id']}/publish",
        {"release_note": "core smoke intent"},
    )
    assert_published_code_path(intent_published)
    intent_run, intent_trace = assert_completed_run(
        intent_workflow["id"],
        "sync",
        {"user_query": "refund billing payment help"},
    )
    assert_intent_branch_run(intent_run, intent_trace)
    assert_trace_code_metadata(intent_trace)

    secret_key = f"core_smoke_api_token_{stamp}"
    secret_value = f"core-secret-{stamp}"
    secret = request(
        "POST",
        "/secrets",
        {
            "secret_key": secret_key,
            "display_name": f"Core Smoke API Token {stamp}",
            "value": secret_value,
        },
    )
    api_workflow = request(
        "POST",
        "/workflows",
        {
            "name": f"Core Smoke API Message {stamp}",
            "draft_graph_json": api_message_workflow_graph(secret_key),
        },
    )
    api_published = request(
        "POST",
        f"/workflows/{api_workflow['id']}/publish",
        {"release_note": "core smoke api"},
    )
    assert_published_code_path(api_published)
    api_run, api_trace = assert_completed_run(
        api_workflow["id"],
        "sync",
        {"user_query": "open billing ticket", "customer_id": "cust-42"},
    )
    assert_api_message_run(api_run, api_trace, secret_value)
    assert_trace_code_metadata(api_trace)

    print(
        json.dumps(
            {
                "health": health.get("status"),
                "ready": ready.get("status"),
                "mock_workflow_id": mock_workflow["id"],
                "mock_code_path": mock_published["code_path"],
                "mock_run_id": run_id_of(mock_run),
                "mock_output": mock_output,
                "intent_workflow_id": intent_workflow["id"],
                "intent_code_path": intent_published["code_path"],
                "intent_run_id": run_id_of(intent_run),
                "api_workflow_id": api_workflow["id"],
                "api_code_path": api_published["code_path"],
                "api_run_id": run_id_of(api_run),
                "api_secret_id": secret["id"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
