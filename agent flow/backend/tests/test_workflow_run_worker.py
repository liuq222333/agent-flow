import json
from pathlib import Path
from typing import Any

import pytest

from app.services import runtime
from app.workers import workflow_run_worker


def test_workflow_run_job_codec_round_trips_run_id() -> None:
    raw = workflow_run_worker.encode_workflow_run_job(123)

    assert json.loads(raw) == {"run_id": 123}
    assert workflow_run_worker.decode_workflow_run_job(raw) == 123
    assert workflow_run_worker.decode_workflow_run_job(raw.encode("utf-8")) == 123


def test_workflow_run_job_codec_rejects_invalid_payload() -> None:
    with pytest.raises(ValueError):
        workflow_run_worker.decode_workflow_run_job('{"run_id":0}')


@pytest.mark.asyncio
async def test_run_once_discards_bad_job_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_dequeue(**kwargs: Any) -> int:
        raise ValueError("bad payload")

    monkeypatch.setattr(workflow_run_worker, "dequeue_workflow_run", fail_dequeue)

    assert await workflow_run_worker.run_once() is True


@pytest.mark.asyncio
async def test_run_once_logs_execute_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def dequeue(**kwargs: Any) -> int:
        return 123

    async def fail_execute(run_id: int) -> None:
        raise RuntimeError(f"run {run_id} exploded")

    monkeypatch.setattr(workflow_run_worker, "dequeue_workflow_run", dequeue)
    monkeypatch.setattr(workflow_run_worker, "execute_workflow_run", fail_execute)

    assert await workflow_run_worker.run_once() is True


class _WorkflowWorkerTransaction:
    def __init__(self, conn: "_WorkflowWorkerConnection") -> None:
        self.conn = conn

    async def __aenter__(self) -> "_WorkflowWorkerConnection":
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _WorkflowWorkerEngine:
    def __init__(self, conn: "_WorkflowWorkerConnection") -> None:
        self.conn = conn

    def begin(self) -> _WorkflowWorkerTransaction:
        return _WorkflowWorkerTransaction(self.conn)


class _WorkflowWorkerConnection:
    def __init__(self, status: str) -> None:
        self.status = status

    async def scalar(self, statement: Any, params: dict[str, Any]) -> str:
        return self.status


@pytest.mark.asyncio
async def test_execute_workflow_run_skips_cancelled_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def execute_pending(conn: Any, *, run_id: int) -> dict[str, Any]:
        raise AssertionError("cancelled run should not execute")

    engine = _WorkflowWorkerEngine(_WorkflowWorkerConnection("cancelled"))
    monkeypatch.setattr(workflow_run_worker, "engine", engine)
    monkeypatch.setattr(
        workflow_run_worker,
        "execute_pending_generated_workflow_run",
        execute_pending,
    )

    result = await workflow_run_worker.execute_workflow_run(123)

    assert result == {"id": 123, "status": "cancelled", "skipped": True}


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value


class _MappingResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def mappings(self) -> "_MappingResult":
        return self

    def one(self) -> dict[str, Any]:
        return self._row


class _FakeConnection:
    def __init__(self, run: dict[str, Any]) -> None:
        self.run = run
        self.node_run_id = 10
        self.node_runs: dict[int, dict[str, Any]] = {}

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(statement)
        params = params or {}

        if "SELECT" in sql and "FROM workflow_runs wr" in sql:
            return _MappingResult(dict(self.run))
        if "SELECT * FROM workflow_runs WHERE id = :run_id" in sql:
            return _MappingResult(dict(self.run))
        if "UPDATE workflow_runs" in sql:
            if "metadata_json" in params:
                self.run["metadata_json"] = params["metadata_json"]
            if "output_json" in params:
                self.run["status"] = "completed"
                self.run["output_json"] = params["output_json"]
                self.run["state_json"] = params["state_json"]
            if "state_json" in params and "error_code" in params:
                self.run["status"] = "failed"
                self.run["error_code"] = params["error_code"]
                self.run["error_message"] = params["error_message"]
                self.run["state_json"] = params["state_json"]
            if "SET status = 'running'" in sql:
                self.run["status"] = "running"
            return _MappingResult(dict(self.run))
        if "INSERT INTO node_runs" in sql:
            node_run_id = self.node_run_id
            self.node_run_id += 1
            self.node_runs[node_run_id] = {
                "node_id": params["node_id"],
                "node_type": params["node_type"],
                "input_json": params["input_json"],
            }
            return _ScalarResult(node_run_id)
        if "UPDATE node_runs" in sql:
            self.node_runs[params["node_run_id"]].update(params)
            return _MappingResult({})

        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_execute_pending_generated_workflow_run_runs_published_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_root = tmp_path / "generated_workflows"
    workflow_file = generated_root / "workflow_000001" / "v000001" / "workflow.py"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text(
        "async def run(input_data, context):\n"
        "    result = await context.execute_node(\n"
        "        'message_1', 'message', {'template': 'Hello {{ input.name }}'}\n"
        "    )\n"
        "    return context.finish({'message': result['message']})\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_GENERATED_ROOT", generated_root.resolve())

    conn = _FakeConnection(
        {
            "id": 1,
            "workflow_id": 1,
            "version_id": 2,
            "status": "pending",
            "input_json": {"name": "Ada"},
            "output_json": None,
            "state_json": {},
            "metadata_json": {"execution_mode": "async"},
            "code_path": str(workflow_file),
            "code_hash": runtime._sha256_file(workflow_file),
        }
    )

    run = await runtime.execute_pending_generated_workflow_run(conn, run_id=1)

    assert run["status"] == "completed"
    assert run["output_json"] == {"message": "Hello Ada"}
    assert run["metadata_json"]["runtime"] == "generated_workflow"
    assert run["metadata_json"]["code_modified"] is False
    assert conn.node_runs[10]["output_json"] == {"message": "Hello Ada"}
