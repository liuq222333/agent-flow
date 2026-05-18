import json
from pathlib import Path

import pytest

from app.services import runtime
from app.services.graph_validation import default_graph
from app.services.workflow_codegen import generate_workflow_code


def test_generate_workflow_code_creates_version_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "_GENERATED_ROOT", tmp_path.resolve())
    graph = default_graph()
    artifact = generate_workflow_code(
        workflow_id=1,
        version=1,
        graph=graph,
        graph_hash="graph-hash",
        generated_root=tmp_path,
    )

    version_dir = tmp_path / "workflow_000001" / "v000001"
    workflow_file = version_dir / "workflow.py"
    manifest_file = version_dir / "manifest.json"

    assert (version_dir / "__init__.py").exists()
    assert workflow_file.exists()
    assert manifest_file.exists()
    assert artifact.code_hash.startswith("sha256:")
    assert artifact.code_path.endswith("workflow_000001/v000001/workflow.py")

    source = workflow_file.read_text(encoding="utf-8")
    assert "async def run(input_data: dict[str, Any], context) -> dict[str, Any]:" in source
    assert "context.execute_graph(GRAPH, input_data)" in source
    generated = runtime._load_generated_workflow(str(workflow_file), artifact.code_hash)
    assert generated.code_modified is False
    assert runtime._sha256_file(workflow_file) == artifact.code_hash

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["workflow_id"] == 1
    assert manifest["version"] == 1
    assert manifest["graph_hash"] == "graph-hash"
    assert manifest["code_hash"] == artifact.code_hash


def test_generate_workflow_code_does_not_overwrite_existing_version(tmp_path: Path) -> None:
    graph = default_graph()
    generate_workflow_code(
        workflow_id=1,
        version=1,
        graph=graph,
        graph_hash="graph-hash",
        generated_root=tmp_path,
    )

    with pytest.raises(FileExistsError):
        generate_workflow_code(
            workflow_id=1,
            version=1,
            graph=graph,
            graph_hash="graph-hash",
            generated_root=tmp_path,
        )
