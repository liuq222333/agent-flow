from fastapi.testclient import TestClient

from app.main import app


def test_list_node_types() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/node-types")

    assert response.status_code == 200
    payload = response.json()
    assert [item["type"] for item in payload["items"]] == [
        "start",
        "input",
        "llm",
        "knowledge_base",
        "intent",
        "branch",
        "set_variable",
        "api",
        "message",
        "output",
        "end",
    ]
    assert payload["items"][0]["name"] == "开始"


def test_get_node_type_schema() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/node-types/llm/schema")

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "llm"
    assert payload["node_schema"]["properties"]["type"]["const"] == "llm"
    assert "model" in payload["config_schema"]["required"]
    assert any(field["name"] == "config.user_prompt" for field in payload["form_schema"]["fields"])


def test_get_set_variable_node_type_schema() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/node-types/set_variable/schema")

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "set_variable"
    assert payload["node_schema"]["properties"]["type"]["const"] == "set_variable"
    assert "assignments" in payload["config_schema"]["properties"]
    assert any(field["name"] == "config.assignments" for field in payload["form_schema"]["fields"])


def test_get_node_type_schema_returns_404_for_unknown_type() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/node-types/unknown/schema")

    assert response.status_code == 404
