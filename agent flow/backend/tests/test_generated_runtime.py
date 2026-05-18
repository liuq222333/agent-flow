from pathlib import Path

import pytest

from app.services import runtime


def _generated_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> Path:
    generated_root = tmp_path / "generated_workflows"
    workflow_file = generated_root / "workflow_000001" / "v000001" / "workflow.py"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text(source, encoding="utf-8")
    monkeypatch.setattr(runtime, "_GENERATED_ROOT", generated_root.resolve())
    return workflow_file


def test_load_generated_workflow_rejects_missing_workflow_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_root = tmp_path / "generated_workflows"
    missing_file = generated_root / "workflow_000001" / "v000001" / "workflow.py"
    monkeypatch.setattr(runtime, "_GENERATED_ROOT", generated_root.resolve())

    with pytest.raises(runtime.WorkflowCodeError) as exc_info:
        runtime._load_generated_workflow(str(missing_file), published_hash=None)

    assert exc_info.value.code == "workflow_code_missing"


def test_load_generated_workflow_rejects_missing_async_run_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_file = _generated_file(
        tmp_path,
        monkeypatch,
        "def run(input_data, context):\n    return {'ok': True}\n",
    )

    with pytest.raises(runtime.WorkflowCodeError) as exc_info:
        runtime._load_generated_workflow(str(workflow_file), published_hash=None)

    assert exc_info.value.code == "workflow_entrypoint_missing"


def test_load_generated_workflow_wraps_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_file = _generated_file(
        tmp_path,
        monkeypatch,
        "raise RuntimeError('boom during import')\n",
    )

    with pytest.raises(runtime.WorkflowCodeError) as exc_info:
        runtime._load_generated_workflow(str(workflow_file), published_hash=None)

    assert exc_info.value.code == "workflow_code_import_failed"
    assert "boom during import" in str(exc_info.value)


def test_load_generated_workflow_marks_modified_code_when_hash_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_file = _generated_file(
        tmp_path,
        monkeypatch,
        "async def run(input_data, context):\n    return {'version': 1}\n",
    )
    published_hash = runtime._sha256_file(workflow_file)
    workflow_file.write_text(
        "async def run(input_data, context):\n    return {'version': 2}\n",
        encoding="utf-8",
    )

    generated = runtime._load_generated_workflow(str(workflow_file), published_hash=published_hash)

    assert generated.code_hash_at_run != published_hash
    assert generated.code_modified is True


def test_load_generated_workflow_accepts_backend_prefixed_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_root = tmp_path / "backend"
    generated_root = backend_root / "generated_workflows"
    workflow_file = generated_root / "workflow_000001" / "v000001" / "workflow.py"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text(
        "async def run(input_data, context):\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_PROJECT_ROOT", tmp_path.resolve())
    monkeypatch.setattr(runtime, "_BACKEND_ROOT", backend_root.resolve())
    monkeypatch.setattr(runtime, "_GENERATED_ROOT", generated_root.resolve())

    generated = runtime._load_generated_workflow(
        "backend/generated_workflows/workflow_000001/v000001/workflow.py",
        published_hash=None,
    )

    assert generated.code_path == workflow_file.resolve()


def test_load_generated_workflow_accepts_legacy_app_prefixed_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_root = tmp_path / "backend"
    generated_root = backend_root / "generated_workflows"
    workflow_file = generated_root / "workflow_000001" / "v000001" / "workflow.py"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text(
        "async def run(input_data, context):\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_PROJECT_ROOT", tmp_path.resolve())
    monkeypatch.setattr(runtime, "_BACKEND_ROOT", backend_root.resolve())
    monkeypatch.setattr(runtime, "_GENERATED_ROOT", generated_root.resolve())

    generated = runtime._load_generated_workflow(
        "app/generated_workflows/workflow_000001/v000001/workflow.py",
        published_hash=None,
    )

    assert generated.code_path == workflow_file.resolve()
