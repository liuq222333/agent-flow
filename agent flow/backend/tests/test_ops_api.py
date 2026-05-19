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
