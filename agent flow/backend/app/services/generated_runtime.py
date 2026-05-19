import hashlib
import importlib.util
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
GENERATED_ROOT = (BACKEND_ROOT / "generated_workflows").resolve()


class WorkflowCodeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GeneratedWorkflow:
    run: Any
    code_path: Path
    code_hash_at_run: str
    code_modified: bool


@dataclass(frozen=True)
class _RuntimePaths:
    backend_root: Path
    project_root: Path
    generated_root: Path


def load_generated_workflow(
    code_path: str | None,
    published_hash: str | None,
    *,
    backend_root: Path | None = None,
    project_root: Path | None = None,
    generated_root: Path | None = None,
) -> GeneratedWorkflow:
    if not code_path:
        raise WorkflowCodeError("workflow_code_missing", "workflow version has no code_path")

    paths = _runtime_paths(
        backend_root=backend_root,
        project_root=project_root,
        generated_root=generated_root,
    )
    resolved_path = resolve_code_path(
        code_path,
        backend_root=paths.backend_root,
        project_root=paths.project_root,
        generated_root=paths.generated_root,
    )
    if not resolved_path.exists() or not resolved_path.is_file():
        raise WorkflowCodeError(
            "workflow_code_missing",
            f"generated workflow code not found: {code_path}",
        )

    actual_hash = sha256_file(resolved_path)
    module_key = hashlib.sha256(f"{resolved_path.as_posix()}:{actual_hash}".encode()).hexdigest()
    module_name = f"generated_workflow_{module_key}"
    spec = importlib.util.spec_from_file_location(module_name, resolved_path)
    if spec is None or spec.loader is None:
        raise WorkflowCodeError(
            "workflow_code_import_failed",
            f"cannot create import spec for generated workflow: {code_path}",
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise WorkflowCodeError("workflow_code_import_failed", str(exc)) from exc

    run = getattr(module, "run", None)
    if not inspect.iscoroutinefunction(run):
        raise WorkflowCodeError(
            "workflow_entrypoint_missing",
            "generated workflow must expose async def run(input_data, context)",
        )

    return GeneratedWorkflow(
        run=run,
        code_path=resolved_path,
        code_hash_at_run=actual_hash,
        code_modified=bool(published_hash and actual_hash != published_hash),
    )


def resolve_code_path(
    code_path: str,
    *,
    backend_root: Path | None = None,
    project_root: Path | None = None,
    generated_root: Path | None = None,
) -> Path:
    paths = _runtime_paths(
        backend_root=backend_root,
        project_root=project_root,
        generated_root=generated_root,
    )
    path = Path(code_path)
    if not path.is_absolute():
        candidates = [paths.project_root / path, paths.backend_root / path]
        parts = path.parts
        if parts and parts[0] in {"backend", "app", paths.backend_root.name} and len(parts) > 1:
            candidates.append(paths.backend_root / Path(*parts[1:]))
    else:
        candidates = [path]

    resolved_candidates = [candidate.resolve() for candidate in candidates]
    resolved = next(
        (
            candidate
            for candidate in resolved_candidates
            if is_generated_workflow_path(candidate, generated_root=paths.generated_root)
        ),
        resolved_candidates[0],
    )
    try:
        resolved.relative_to(paths.generated_root)
    except ValueError as exc:
        raise WorkflowCodeError(
            "workflow_code_missing",
            f"generated workflow code path is outside generated_workflows: {code_path}",
        ) from exc
    return resolved


def is_generated_workflow_path(path: Path, *, generated_root: Path | None = None) -> bool:
    root = Path(generated_root or GENERATED_ROOT).resolve()
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def relative_project_path(path: Path, *, project_root: Path | None = None) -> str:
    root = Path(project_root or PROJECT_ROOT).resolve()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        relative = path.resolve()
    return relative.as_posix()


def _runtime_paths(
    *,
    backend_root: Path | None = None,
    project_root: Path | None = None,
    generated_root: Path | None = None,
) -> _RuntimePaths:
    backend = Path(backend_root or BACKEND_ROOT).resolve()
    project = Path(project_root or PROJECT_ROOT).resolve()
    generated = Path(generated_root or GENERATED_ROOT).resolve()
    return _RuntimePaths(
        backend_root=backend,
        project_root=project,
        generated_root=generated,
    )
