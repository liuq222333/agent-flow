import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.services import runtime
from app.workers import workflow_run_worker


def test_workflow_run_job_codec_round_trips_run_id() -> None:
    raw = workflow_run_worker.encode_workflow_run_job(
        123,
        job_id="wrj_test",
        queue_attempt=2,
        enqueued_at_epoch=1000,
    )

    assert json.loads(raw) == {
        "job_id": "wrj_test",
        "run_id": 123,
        "queue_name": "workflow_runs",
        "enqueued_at_epoch": 1000,
        "queue_attempt": 2,
    }
    assert workflow_run_worker.decode_workflow_run_job(raw) == 123
    assert workflow_run_worker.decode_workflow_run_job(raw.encode("utf-8")) == 123
    record = workflow_run_worker.decode_workflow_run_job_record(raw)
    assert record.run_id == 123
    assert record.job_id == "wrj_test"
    assert record.queue_attempt == 2


def test_workflow_run_job_codec_rejects_invalid_payload() -> None:
    with pytest.raises(ValueError):
        workflow_run_worker.decode_workflow_run_job('{"run_id":0}')


class _FakeRedis:
    def __init__(self) -> None:
        self.queues: dict[str, list[str]] = {
            workflow_run_worker.WORKFLOW_RUN_QUEUE: [],
            workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE: [],
            workflow_run_worker.WORKFLOW_RUN_DEAD_QUEUE: [],
        }
        self.closed = False

    async def lpush(self, queue_name: str, value: str) -> int:
        self.queues.setdefault(queue_name, []).insert(0, value)
        return len(self.queues[queue_name])

    async def brpoplpush(self, source: str, destination: str, timeout: int = 0) -> str | None:
        source_queue = self.queues.setdefault(source, [])
        if not source_queue:
            return None
        value = source_queue.pop()
        self.queues.setdefault(destination, []).insert(0, value)
        return value

    async def lrem(self, queue_name: str, count: int, value: str) -> int:
        queue = self.queues.setdefault(queue_name, [])
        removed = 0
        next_queue: list[str] = []
        for item in queue:
            if item == value and (count == 0 or removed < abs(count)):
                removed += 1
                continue
            next_queue.append(item)
        self.queues[queue_name] = next_queue
        return removed

    async def lrange(self, queue_name: str, start: int, end: int) -> list[str]:
        queue = self.queues.setdefault(queue_name, [])
        end_index = None if end == -1 else end + 1
        return queue[start:end_index]

    async def llen(self, queue_name: str) -> int:
        return len(self.queues.setdefault(queue_name, []))

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_dequeue_moves_job_to_processing_and_ack_removes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeRedis()
    raw = workflow_run_worker.encode_workflow_run_job(123, job_id="wrj_ack")
    await client.lpush(workflow_run_worker.WORKFLOW_RUN_QUEUE, raw)
    monkeypatch.setattr(workflow_run_worker.redis, "from_url", lambda url: client)

    job = await workflow_run_worker.dequeue_workflow_run(redis_url="redis://test")

    assert isinstance(job, workflow_run_worker.WorkflowRunJob)
    assert job.run_id == 123
    assert client.queues[workflow_run_worker.WORKFLOW_RUN_QUEUE] == []
    assert client.queues[workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE] == [raw]

    await workflow_run_worker.ack_workflow_run_job(job, redis_url="redis://test")

    assert client.queues[workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE] == []


@pytest.mark.asyncio
async def test_retry_or_dead_letter_requeues_until_attempt_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeRedis()
    raw = workflow_run_worker.encode_workflow_run_job(
        123,
        job_id="wrj_retry",
        queue_attempt=1,
    )
    await client.lpush(workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE, raw)
    monkeypatch.setattr(workflow_run_worker.redis, "from_url", lambda url: client)
    job = workflow_run_worker.decode_workflow_run_job_record(raw)

    result = await workflow_run_worker.retry_or_dead_letter_workflow_run_job(
        job,
        redis_url="redis://test",
        reason="worker_execution_exception",
        max_attempts=2,
    )

    assert result == "requeued"
    assert client.queues[workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE] == []
    requeued = json.loads(client.queues[workflow_run_worker.WORKFLOW_RUN_QUEUE][0])
    assert requeued["run_id"] == 123
    assert requeued["queue_attempt"] == 2

    job2 = workflow_run_worker.decode_workflow_run_job_record(
        client.queues[workflow_run_worker.WORKFLOW_RUN_QUEUE][0]
    )
    await client.lpush(workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE, job2.raw)
    client.queues[workflow_run_worker.WORKFLOW_RUN_QUEUE] = []

    result = await workflow_run_worker.retry_or_dead_letter_workflow_run_job(
        job2,
        redis_url="redis://test",
        reason="worker_execution_exception",
        max_attempts=2,
    )

    assert result == "dead"
    assert client.queues[workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE] == []
    dead = json.loads(client.queues[workflow_run_worker.WORKFLOW_RUN_DEAD_QUEUE][0])
    assert dead["dead_reason"] == "worker_execution_exception"
    assert dead["job"]["run_id"] == 123


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


@pytest.mark.asyncio
async def test_run_once_with_worker_id_claims_and_marks_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, int | str | None]] = []

    async def dequeue(**kwargs: Any) -> int:
        return 456

    async def claim(run_id: int, *, worker_id: str, lease_seconds: int = 60) -> None:
        events.append(("claim", run_id))
        events.append(("worker", worker_id))

    async def write_heartbeat(
        worker_id: str,
        *,
        status_value: str,
        current_run_id: int | None = None,
        current_job_id: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        events.append((status_value, current_run_id))

    async def heartbeat_loop(
        worker_id: str,
        run_id: int,
        interval_seconds: int,
        job_id: str | None,
    ) -> None:
        events.append(("loop", run_id))
        await asyncio.sleep(3600)

    async def execute(run_id: int) -> dict[str, Any]:
        events.append(("execute", run_id))
        return {"id": run_id, "status": "completed"}

    monkeypatch.setattr(workflow_run_worker, "dequeue_workflow_run", dequeue)
    monkeypatch.setattr(workflow_run_worker, "claim_workflow_run", claim)
    monkeypatch.setattr(workflow_run_worker, "write_worker_heartbeat", write_heartbeat)
    monkeypatch.setattr(workflow_run_worker, "_heartbeat_loop", heartbeat_loop)
    monkeypatch.setattr(workflow_run_worker, "execute_workflow_run", execute)

    result = await workflow_run_worker.run_once(
        worker_id="workflow-worker:test",
        heartbeat_interval_seconds=1,
        lease_seconds=30,
    )

    assert result is True
    assert ("claim", 456) in events
    assert ("worker", "workflow-worker:test") in events
    assert ("busy", 456) in events
    assert ("execute", 456) in events
    assert events[-1] == ("idle", None)


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

    def connect(self) -> _WorkflowWorkerTransaction:
        return _WorkflowWorkerTransaction(self.conn)


class _WorkflowWorkerConnection:
    def __init__(self, status: str) -> None:
        self.status = status

    async def scalar(self, statement: Any, params: dict[str, Any]) -> str:
        return self.status


class _ProcessingRecoveryConnection:
    def __init__(self, statuses: dict[int, str | None]) -> None:
        self.statuses = statuses

    async def scalar(self, statement: Any, params: dict[str, Any]) -> str | None:
        return self.statuses.get(int(params["run_id"]))


@pytest.mark.asyncio
async def test_recover_processing_jobs_requeues_pending_and_acks_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeRedis()
    old_epoch = 1000
    terminal = workflow_run_worker.encode_workflow_run_job(
        1,
        job_id="wrj_done",
        enqueued_at_epoch=old_epoch,
    )
    pending = workflow_run_worker.encode_workflow_run_job(
        2,
        job_id="wrj_pending",
        enqueued_at_epoch=old_epoch,
    )
    running = workflow_run_worker.encode_workflow_run_job(
        3,
        job_id="wrj_running",
        enqueued_at_epoch=old_epoch,
    )
    invalid = '{"run_id":0}'
    client.queues[workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE] = [
        terminal,
        pending,
        running,
        invalid,
    ]
    monkeypatch.setattr(workflow_run_worker.redis, "from_url", lambda url: client)
    monkeypatch.setattr(
        workflow_run_worker,
        "engine",
        _WorkflowWorkerEngine(
            _ProcessingRecoveryConnection({1: "completed", 2: "pending", 3: "running"})
        ),
    )
    monkeypatch.setattr(workflow_run_worker.time, "time", lambda: old_epoch + 100)

    result = await workflow_run_worker.recover_processing_workflow_run_jobs(
        redis_url="redis://test",
        stale_after_seconds=1,
    )

    assert result == {
        "requeued": [2],
        "acked_terminal": [1],
        "skipped_running": [3],
        "invalid_payloads": 1,
    }
    assert client.queues[workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE] == [running]
    requeued = json.loads(client.queues[workflow_run_worker.WORKFLOW_RUN_QUEUE][0])
    assert requeued["run_id"] == 2
    assert requeued["queue_attempt"] == 2
    dead = json.loads(client.queues[workflow_run_worker.WORKFLOW_RUN_DEAD_QUEUE][0])
    assert dead["dead_reason"] == "invalid_payload"


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
    assert run["metadata_json"]["code_hash_published"] == runtime._sha256_file(workflow_file)
    assert run["metadata_json"]["code_hash_at_run"] == runtime._sha256_file(workflow_file)
    assert run["metadata_json"]["code_modified"] is False
    assert conn.node_runs[10]["output_json"] == {"message": "Hello Ada"}


class _RowsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_RowsResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _RecoveryConnection:
    def __init__(self) -> None:
        self.rows = [
            {
                "id": 101,
                "status": "pending",
                "metadata_json": {"execution_mode": "async"},
            },
            {
                "id": 202,
                "status": "running",
                "metadata_json": {"execution_mode": "async", "worker_recovery_count": 2},
            },
        ]
        self.metadata_updates: dict[int, dict[str, Any]] = {}
        self.failed_node_run_ids: list[int] = []
        self.failed_run_ids: list[int] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(statement)
        params = params or {}

        if "SELECT wr.id, wr.status, wr.metadata_json" in sql:
            return _RowsResult(self.rows)
        if "UPDATE workflow_runs" in sql and "metadata_json = :metadata_json" in sql:
            self.metadata_updates[int(params["run_id"])] = params["metadata_json"]
            if "status = 'failed'" in sql:
                self.failed_run_ids.append(int(params["run_id"]))
            return _RowsResult([])
        if "UPDATE node_runs" in sql:
            self.failed_node_run_ids.append(int(params["run_id"]))
            return _RowsResult([])

        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_recover_stale_workflow_runs_requeues_pending_and_fails_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _RecoveryConnection()
    engine = _WorkflowWorkerEngine(conn)
    enqueued: list[int] = []

    async def enqueue(run_id: int, *, redis_url: str | None = None) -> None:
        enqueued.append(run_id)

    monkeypatch.setattr(workflow_run_worker, "engine", engine)
    monkeypatch.setattr(workflow_run_worker, "enqueue_workflow_run", enqueue)

    result = await workflow_run_worker.recover_stale_workflow_runs(stale_after_seconds=1)

    assert result == {"requeued": [101], "failed": [202], "requeue_errors": []}
    assert enqueued == [101]
    assert conn.failed_node_run_ids == [202]
    assert conn.failed_run_ids == [202]
    assert conn.metadata_updates[101]["worker_recovery_count"] == 1
    assert conn.metadata_updates[202]["worker_recovery_count"] == 3
    assert conn.metadata_updates[202]["last_worker_recovery_status"] == "running"
