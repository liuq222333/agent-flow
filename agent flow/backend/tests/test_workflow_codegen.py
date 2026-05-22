import json
from pathlib import Path

import pytest

from app.services import runtime, workflow_codegen
from app.services.graph_validation import default_graph
from app.services.workflow_codegen import (
    cleanup_generated_workflow_dirs,
    generate_workflow_code,
    inspect_workflow_code,
    read_workflow_code_source,
    resolve_generated_code_path,
)


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


def test_generate_workflow_code_creates_separate_version_dirs(tmp_path: Path) -> None:
    graph = default_graph()
    first = generate_workflow_code(
        workflow_id=1,
        version=1,
        graph=graph,
        graph_hash="graph-hash-v1",
        generated_root=tmp_path,
    )
    second = generate_workflow_code(
        workflow_id=1,
        version=2,
        graph=graph,
        graph_hash="graph-hash-v2",
        generated_root=tmp_path,
    )

    assert first.code_path.endswith("workflow_000001/v000001/workflow.py")
    assert second.code_path.endswith("workflow_000001/v000002/workflow.py")
    assert first.code_path != second.code_path
    assert (tmp_path / "workflow_000001" / "v000001" / "workflow.py").exists()
    assert (tmp_path / "workflow_000001" / "v000002" / "workflow.py").exists()


def test_read_workflow_code_source_detects_hash_changes(tmp_path: Path) -> None:
    artifact = generate_workflow_code(
        workflow_id=1,
        version=1,
        graph=default_graph(),
        graph_hash="graph-hash",
        generated_root=tmp_path,
    )
    workflow_file = tmp_path / "workflow_000001" / "v000001" / "workflow.py"
    workflow_file.write_text(
        workflow_file.read_text(encoding="utf-8") + "\n# local debug edit\n",
        encoding="utf-8",
    )

    code = read_workflow_code_source(
        str(workflow_file),
        artifact.code_hash,
        generated_root=tmp_path,
    )
    inspection = inspect_workflow_code(
        str(workflow_file),
        artifact.code_hash,
        generated_root=tmp_path,
    )

    assert code.code_modified is True
    assert code.code_status == "modified"
    assert code.code_hash_actual != artifact.code_hash
    assert "async def run" in code.source
    assert inspection.code_modified is True


def test_resolve_generated_code_path_prefers_canonical_backend_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_root = tmp_path / "app"
    generated_root = backend_root / "generated_workflows"
    workflow_file = generated_root / "workflow_000001" / "v000001" / "workflow.py"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text("async def run(input_data, context):\n    return {}\n")

    monkeypatch.setattr(workflow_codegen, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(workflow_codegen, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(workflow_codegen, "GENERATED_ROOT", generated_root)

    resolved = resolve_generated_code_path(
        "backend/generated_workflows/workflow_000001/v000001/workflow.py",
        generated_root=generated_root,
    )
    inspection = inspect_workflow_code(
        "backend/generated_workflows/workflow_000001/v000001/workflow.py",
        None,
        generated_root=generated_root,
    )

    assert resolved == workflow_file.resolve()
    assert inspection.code_status == "ok"


def test_cleanup_generated_workflow_dirs_removes_tmp_and_orphans(tmp_path: Path) -> None:
    kept_artifact = generate_workflow_code(
        workflow_id=1,
        version=1,
        graph=default_graph(),
        graph_hash="graph-hash",
        generated_root=tmp_path,
    )
    orphan_dir = tmp_path / "workflow_000001" / "v000002"
    orphan_dir.mkdir()
    (orphan_dir / "workflow.py").write_text("async def run(input_data, context):\n    return {}\n")
    tmp_dir = tmp_path / "workflow_000001" / ".v000003.tmp-leftover"
    tmp_dir.mkdir()
    empty_workflow_dir = tmp_path / "workflow_000002"
    empty_workflow_dir.mkdir()

    report = cleanup_generated_workflow_dirs(
        referenced_code_paths=[kept_artifact.code_path],
        generated_root=tmp_path,
    )

    assert (tmp_path / "workflow_000001" / "v000001").exists()
    assert not orphan_dir.exists()
    assert not tmp_dir.exists()
    assert not empty_workflow_dir.exists()
    assert any(
        path.endswith("workflow_000001/v000002")
        for path in report.removed_orphan_version_dirs
    )
    assert any(path.endswith(".v000003.tmp-leftover") for path in report.removed_temp_dirs)
    assert any(path.endswith("workflow_000002") for path in report.removed_empty_workflow_dirs)
