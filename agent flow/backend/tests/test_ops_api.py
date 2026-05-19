import json
from typing import Any

from fastapi.testclient import TestClient

from app.api.v1 import ops
from app.main import app


def test_ops_routes_are_registered() -> None:
    client = TestClient(app)

    openapi = client.get("/api/openapi.json").json()

    assert "/api/v1/ops/workers" in openapi["paths"]
    assert "/api/v1/ops/queues" in openapi["paths"]
    assert "/api/v1/ops/queues/workflow_runs/dead" in openapi["paths"]
    assert "/api/v1/ops/queues/workflow_runs/recover" in openapi["paths"]
    assert "/api/v1/ops/workflow_runs/failed" in openapi["paths"]
    assert "/api/v1/ops/workflow_runs/{run_id}/recover" in openapi["paths"]


def test_ops_queues_uses_redis_depths(monkeypatch) -> None:
    class FakeRedis:
        async def llen(self, key: str) -> int:
            return {
                ops.WORKFLOW_RUN_QUEUE: 7,
                ops.WORKFLOW_RUN_PROCESSING_QUEUE: 2,
                ops.WORKFLOW_RUN_DEAD_QUEUE: 1,
            }[key]

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(ops.redis, "from_url", lambda redis_url: FakeRedis())
    client = TestClient(app)

    response = client.get("/api/v1/ops/queues")

    assert response.status_code == 200
    assert response.json() == {
        "queue_name": "workflow_runs",
        "main_depth": 7,
        "processing_depth": 2,
        "dead_letter_depth": 1,
    }


class _OpsTransaction:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    async def __aenter__(self) -> Any:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _OpsEngine:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def connect(self) -> _OpsTransaction:
        return _OpsTransaction(self.conn)

    def begin(self) -> _OpsTransaction:
        return _OpsTransaction(self.conn)


class _OpsResult:
    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        row: dict[str, Any] | None = None,
    ) -> None:
        self.rows = rows or []
        self.row = row

    def mappings(self) -> "_OpsResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def one_or_none(self) -> dict[str, Any] | None:
        return self.row

    def one(self) -> dict[str, Any]:
        assert self.row is not None
        return self.row


class _FailedRunsConnection:
    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _OpsResult:
        assert params == {"limit": 2}
        return _OpsResult(
            rows=[
                {
                    "run_id": 7,
                    "workflow_id": 3,
                    "workflow_version_id": 5,
                    "status": "failed",
                    "error_code": "node_error",
                    "error_message": "boom",
                    "created_at": "2026-05-19T01:00:00Z",
                    "updated_at": "2026-05-19T01:02:00Z",
                }
            ]
        )


class _RecoverConnection:
    def __init__(self, run: dict[str, Any] | None) -> None:
        self.run = run
        self.node_reset_run_ids: list[int] = []
        self.metadata_json: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _OpsResult:
        sql = str(statement)
        params = params or {}

        if "SELECT" in sql and "FROM workflow_runs wr" in sql:
            return _OpsResult(row=dict(self.run) if self.run is not None else None)
        if "UPDATE node_runs" in sql:
            self.node_reset_run_ids.append(int(params["run_id"]))
            return _OpsResult(rows=[])
        if "UPDATE workflow_runs" in sql:
            assert self.run is not None
            self.metadata_json = params["metadata_json"]
            self.run["status"] = "pending"
            self.run["error_code"] = None
            self.run["error_message"] = None
            return _OpsResult(row={"run_id": params["run_id"], "status": "pending"})

        raise AssertionError(f"unexpected SQL: {sql}")


class _OpsRedis:
    def __init__(self) -> None:
        self.queues: dict[str, list[str]] = {
            ops.WORKFLOW_RUN_QUEUE: [],
            ops.WORKFLOW_RUN_DEAD_QUEUE: [],
        }
        self.closed = False

    async def lrange(self, queue_name: str, start: int, end: int) -> list[str]:
        queue = self.queues.setdefault(queue_name, [])
        end_index = None if end == -1 else end + 1
        return queue[start:end_index]

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

    async def lpush(self, queue_name: str, value: str) -> int:
        self.queues.setdefault(queue_name, []).insert(0, value)
        return len(self.queues[queue_name])

    async def aclose(self) -> None:
        self.closed = True


def _run_row(status: str, *, is_stale: bool = False) -> dict[str, Any]:
    return {
        "run_id": 42,
        "workflow_id": 3,
        "workflow_version_id": 5,
        "status": status,
        "error_code": "worker_execution_exception" if status == "failed" else None,
        "error_message": "worker exploded" if status == "failed" else None,
        "metadata_json": {"execution_mode": "async"},
        "created_at": "2026-05-19T01:00:00Z",
        "updated_at": "2026-05-19T01:02:00Z",
        "is_stale": is_stale,
    }


def test_failed_workflow_runs_returns_expected_fields(monkeypatch) -> None:
    monkeypatch.setattr(ops, "engine", _OpsEngine(_FailedRunsConnection()))
    client = TestClient(app)

    response = client.get("/api/v1/ops/workflow_runs/failed?limit=2")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "run_id": 7,
                "workflow_id": 3,
                "workflow_version_id": 5,
                "status": "failed",
                "error_code": "node_error",
                "error_message": "boom",
                "created_at": "2026-05-19T01:00:00Z",
                "updated_at": "2026-05-19T01:02:00Z",
            }
        ],
        "count": 1,
    }


def test_recover_failed_workflow_run_resets_and_queues(monkeypatch) -> None:
    conn = _RecoverConnection(_run_row("failed"))
    redis_client = _OpsRedis()
    monkeypatch.setattr(ops, "engine", _OpsEngine(conn))
    monkeypatch.setattr(ops.redis, "from_url", lambda redis_url: redis_client)
    client = TestClient(app)

    response = client.post("/api/v1/ops/workflow_runs/42/recover")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 42,
        "status": "pending",
        "recovered": True,
        "reason": "failed",
        "queued": True,
    }
    assert conn.node_reset_run_ids == [42]
    assert conn.metadata_json is not None
    assert conn.metadata_json["last_ops_recovery_reason"] == "failed"
    queued = json.loads(redis_client.queues[ops.WORKFLOW_RUN_QUEUE][0])
    assert queued["run_id"] == 42


def test_recover_dead_letter_pending_workflow_run_removes_dead_job(monkeypatch) -> None:
    conn = _RecoverConnection(_run_row("pending"))
    redis_client = _OpsRedis()
    dead_job = json.dumps(
        {
            "job": {"run_id": "42", "queue_name": "workflow_runs"},
            "dead_reason": "worker_execution_exception",
        }
    )
    other_dead_job = json.dumps(
        {"job": {"run_id": 99}, "dead_reason": "worker_execution_exception"}
    )
    redis_client.queues[ops.WORKFLOW_RUN_DEAD_QUEUE] = [dead_job, other_dead_job]
    monkeypatch.setattr(ops, "engine", _OpsEngine(conn))
    monkeypatch.setattr(ops.redis, "from_url", lambda redis_url: redis_client)
    client = TestClient(app)

    response = client.post("/api/v1/ops/workflow_runs/42/recover")

    assert response.status_code == 200
    assert response.json()["reason"] == "dead_letter"
    assert response.json()["queued"] is True
    assert redis_client.queues[ops.WORKFLOW_RUN_DEAD_QUEUE] == [other_dead_job]


def test_recover_stale_pending_workflow_run_requeues(monkeypatch) -> None:
    conn = _RecoverConnection(_run_row("pending", is_stale=True))
    redis_client = _OpsRedis()
    monkeypatch.setattr(ops, "engine", _OpsEngine(conn))
    monkeypatch.setattr(ops.redis, "from_url", lambda redis_url: redis_client)
    client = TestClient(app)

    response = client.post("/api/v1/ops/workflow_runs/42/recover")

    assert response.status_code == 200
    assert response.json()["reason"] == "stale"
    assert response.json()["recovered"] is True
    assert json.loads(redis_client.queues[ops.WORKFLOW_RUN_QUEUE][0])["run_id"] == 42


def test_recover_running_workflow_run_is_idempotent(monkeypatch) -> None:
    conn = _RecoverConnection(_run_row("running"))
    redis_client = _OpsRedis()
    monkeypatch.setattr(ops, "engine", _OpsEngine(conn))
    monkeypatch.setattr(ops.redis, "from_url", lambda redis_url: redis_client)
    client = TestClient(app)

    response = client.post("/api/v1/ops/workflow_runs/42/recover")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 42,
        "status": "running",
        "recovered": False,
        "reason": "already_running",
        "queued": False,
    }
    assert redis_client.queues[ops.WORKFLOW_RUN_QUEUE] == []
    assert conn.node_reset_run_ids == []


def test_recover_completed_workflow_run_is_idempotent(monkeypatch) -> None:
    conn = _RecoverConnection(_run_row("completed"))
    redis_client = _OpsRedis()
    monkeypatch.setattr(ops, "engine", _OpsEngine(conn))
    monkeypatch.setattr(ops.redis, "from_url", lambda redis_url: redis_client)
    client = TestClient(app)

    response = client.post("/api/v1/ops/workflow_runs/42/recover")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 42,
        "status": "completed",
        "recovered": False,
        "reason": "already_completed",
        "queued": False,
    }
    assert redis_client.queues[ops.WORKFLOW_RUN_QUEUE] == []
    assert conn.node_reset_run_ids == []
