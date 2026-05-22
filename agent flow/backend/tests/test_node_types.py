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
        "human_approval",
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


def test_get_human_approval_node_type_schema() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/node-types/human_approval/schema")

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "human_approval"
    assert payload["node_schema"]["properties"]["type"]["const"] == "human_approval"
    assert "title" in payload["config_schema"]["required"]
    assert any(field["name"] == "config.title" for field in payload["form_schema"]["fields"])


def test_get_output_node_type_schema_includes_response_modes() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/node-types/output/schema")

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "output"
    properties = payload["config_schema"]["properties"]
    assert properties["response_mode"]["enum"] == ["parameters", "template"]
    assert "output_value_kinds" in properties
    assert any(field["name"] == "config.template" for field in payload["form_schema"]["fields"])


def test_get_start_and_end_node_type_schemas_include_three_stage_contract() -> None:
    client = TestClient(app)

    start_response = client.get("/api/v1/node-types/start/schema")
    end_response = client.get("/api/v1/node-types/end/schema")

    assert start_response.status_code == 200
    assert end_response.status_code == 200
    start_payload = start_response.json()
    end_payload = end_response.json()
    assert "fields" in start_payload["config_schema"]["properties"]
    assert any(field["name"] == "config.fields" for field in start_payload["form_schema"]["fields"])
    assert end_payload["config_schema"]["properties"]["response_mode"]["enum"] == [
        "parameters",
        "template",
    ]
    assert any(field["name"] == "config.outputs" for field in end_payload["form_schema"]["fields"])


def test_get_node_type_schema_returns_404_for_unknown_type() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/node-types/unknown/schema")

    assert response.status_code == 404
