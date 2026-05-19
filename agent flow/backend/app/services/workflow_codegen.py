from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
GENERATED_ROOT = BACKEND_ROOT / "generated_workflows"
_VERSION_DIR_RE = re.compile(r"^v\d{6}$")


@dataclass(frozen=True)
class WorkflowCodeArtifact:
    code_path: str
    code_hash: str
    code_generated_at: datetime
    version_dir: Path


@dataclass(frozen=True)
class WorkflowCodeInspection:
    code_path: str
    code_hash_actual: str | None
    code_modified: bool | None
    code_status: str


@dataclass(frozen=True)
class WorkflowCodeSource:
    code_path: str
    code_hash_actual: str
    code_modified: bool
    code_status: str
    source: str


@dataclass(frozen=True)
class GeneratedWorkflowCleanupReport:
    dry_run: bool
    removed_temp_dirs: list[str]
    removed_orphan_version_dirs: list[str]
    removed_empty_workflow_dirs: list[str]
    kept_version_dirs: list[str]


def generate_workflow_code(
    *,
    workflow_id: int,
    version: int,
    graph: dict[str, Any],
    graph_hash: str,
    generated_root: Path = GENERATED_ROOT,
) -> WorkflowCodeArtifact:
    workflow_dir_name = f"workflow_{workflow_id:06d}"
    version_dir_name = f"v{version:06d}"
    workflow_dir = generated_root / workflow_dir_name
    version_dir = workflow_dir / version_dir_name
    tmp_dir = workflow_dir / f".{version_dir_name}.tmp-{uuid4().hex}"

    if version_dir.exists():
        raise FileExistsError(f"generated workflow version already exists: {version_dir}")

    try:
        _remove_version_tmp_dirs(workflow_dir, version_dir_name)
        tmp_dir.mkdir(parents=True, exist_ok=False)
        (tmp_dir / "__init__.py").write_text("", encoding="utf-8")
        workflow_source = _render_workflow_py(graph)
        compile(workflow_source, "workflow.py", "exec")
        workflow_file = tmp_dir / "workflow.py"
        workflow_file.write_text(workflow_source, encoding="utf-8", newline="\n")

        code_hash = _sha256_file(workflow_file)
        generated_at = datetime.now(UTC)
        manifest = {
            "workflow_id": workflow_id,
            "version": version,
            "schema_version": graph.get("schema_version", "1.0"),
            "graph_hash": graph_hash,
            "code_hash": code_hash,
            "generated_at": generated_at.isoformat(),
            "entrypoint": "workflow.run",
        }
        (tmp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        workflow_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.rename(version_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    code_path = version_dir / "workflow.py"
    return WorkflowCodeArtifact(
        code_path=_relative_backend_path(code_path),
        code_hash=code_hash,
        code_generated_at=generated_at,
        version_dir=version_dir,
    )


def remove_generated_workflow_version(version_dir: Path) -> None:
    shutil.rmtree(version_dir, ignore_errors=True)


def generated_workflow_version_dir(
    *,
    workflow_id: int,
    version: int,
    generated_root: Path = GENERATED_ROOT,
) -> Path:
    return generated_root / f"workflow_{workflow_id:06d}" / f"v{version:06d}"


def inspect_workflow_code(
    code_path: str | None,
    published_hash: str | None,
    *,
    generated_root: Path = GENERATED_ROOT,
) -> WorkflowCodeInspection:
    if not code_path:
        return WorkflowCodeInspection(
            code_path="",
            code_hash_actual=None,
            code_modified=None,
            code_status="missing_metadata",
        )

    try:
        resolved_path = resolve_generated_code_path(code_path, generated_root=generated_root)
    except ValueError:
        return WorkflowCodeInspection(
            code_path=code_path,
            code_hash_actual=None,
            code_modified=None,
            code_status="invalid_path",
        )

    relative_path = _relative_backend_path(resolved_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        return WorkflowCodeInspection(
            code_path=relative_path,
            code_hash_actual=None,
            code_modified=None,
            code_status="missing_file",
        )

    actual_hash = _sha256_file(resolved_path)
    modified = bool(published_hash and actual_hash != published_hash)
    return WorkflowCodeInspection(
        code_path=relative_path,
        code_hash_actual=actual_hash,
        code_modified=modified,
        code_status="modified" if modified else "ok",
    )


def read_workflow_code_source(
    code_path: str,
    published_hash: str | None,
    *,
    generated_root: Path = GENERATED_ROOT,
) -> WorkflowCodeSource:
    resolved_path = resolve_generated_code_path(code_path, generated_root=generated_root)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise FileNotFoundError(f"generated workflow code not found: {code_path}")

    source = resolved_path.read_text(encoding="utf-8")
    actual_hash = _sha256_file(resolved_path)
    modified = bool(published_hash and actual_hash != published_hash)
    return WorkflowCodeSource(
        code_path=_relative_backend_path(resolved_path),
        code_hash_actual=actual_hash,
        code_modified=modified,
        code_status="modified" if modified else "ok",
        source=source,
    )


def cleanup_generated_workflow_dirs(
    *,
    referenced_code_paths: Iterable[str],
    generated_root: Path = GENERATED_ROOT,
    dry_run: bool = False,
) -> GeneratedWorkflowCleanupReport:
    root = generated_root.resolve()
    referenced_version_dirs: set[Path] = set()
    for code_path in referenced_code_paths:
        try:
            referenced_version_dirs.add(
                resolve_generated_code_path(code_path, generated_root=root).parent,
            )
        except ValueError:
            continue

    removed_temp_dirs: list[str] = []
    removed_orphan_version_dirs: list[str] = []
    removed_empty_workflow_dirs: list[str] = []
    kept_version_dirs: list[str] = []

    if not root.exists():
        return GeneratedWorkflowCleanupReport(
            dry_run=dry_run,
            removed_temp_dirs=[],
            removed_orphan_version_dirs=[],
            removed_empty_workflow_dirs=[],
            kept_version_dirs=[],
        )

    for workflow_dir in sorted(root.glob("workflow_*")):
        if not workflow_dir.is_dir():
            continue

        leftover_dirs = sorted(
            [*workflow_dir.glob(".v*.tmp-*"), *workflow_dir.glob(".v*.backup-*")]
        )
        for tmp_dir in leftover_dirs:
            if not tmp_dir.is_dir() or not _is_inside(tmp_dir, root):
                continue
            removed_temp_dirs.append(_relative_backend_path(tmp_dir))
            if not dry_run:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        for version_dir in sorted(workflow_dir.iterdir()):
            if (
                not version_dir.is_dir()
                or not _VERSION_DIR_RE.fullmatch(version_dir.name)
                or not _is_inside(version_dir, root)
            ):
                continue
            resolved_version_dir = version_dir.resolve()
            if resolved_version_dir in referenced_version_dirs:
                kept_version_dirs.append(_relative_backend_path(resolved_version_dir))
                continue
            removed_orphan_version_dirs.append(_relative_backend_path(resolved_version_dir))
            if not dry_run:
                shutil.rmtree(resolved_version_dir, ignore_errors=True)

        if _workflow_dir_is_empty(workflow_dir):
            removed_empty_workflow_dirs.append(_relative_backend_path(workflow_dir))
            if not dry_run:
                shutil.rmtree(workflow_dir, ignore_errors=True)

    return GeneratedWorkflowCleanupReport(
        dry_run=dry_run,
        removed_temp_dirs=removed_temp_dirs,
        removed_orphan_version_dirs=removed_orphan_version_dirs,
        removed_empty_workflow_dirs=removed_empty_workflow_dirs,
        kept_version_dirs=kept_version_dirs,
    )


def resolve_generated_code_path(
    code_path: str,
    *,
    generated_root: Path = GENERATED_ROOT,
) -> Path:
    root = generated_root.resolve()
    path = Path(code_path)
    if path.is_absolute():
        candidates = [path]
    else:
        candidates = []
        parts = path.parts
        # Normalize persisted project-relative paths before trying root/path fallback.
        # In containers PROJECT_ROOT can be "/", so "backend/generated_workflows/..."
        # would otherwise be mistaken for "generated_workflows/backend/generated_workflows/...".
        if parts and parts[0] in {"backend", "app", BACKEND_ROOT.name} and len(parts) > 1:
            candidates.append(BACKEND_ROOT / Path(*parts[1:]))
        generated_parts = ("generated_workflows",)
        if generated_parts[0] in parts:
            generated_index = parts.index(generated_parts[0])
            candidates.append(root / Path(*parts[generated_index + 1 :]))
        candidates.extend([PROJECT_ROOT / path, BACKEND_ROOT / path, root / path])

    resolved_candidates = [candidate.resolve() for candidate in candidates]
    resolved = next(
        (candidate for candidate in resolved_candidates if _is_inside(candidate, root)),
        resolved_candidates[0],
    )
    if not _is_inside(resolved, root):
        raise ValueError(
            f"generated workflow code path is outside generated_workflows: {code_path}"
        )
    return resolved


def _render_workflow_py(graph: dict[str, Any]) -> str:
    graph_json_literal = repr(json.dumps(graph, ensure_ascii=False, sort_keys=True))
    return f'''from __future__ import annotations

import json
from typing import Any


GRAPH: dict[str, Any] = json.loads({graph_json_literal})


async def run(input_data: dict[str, Any], context) -> dict[str, Any]:
    return await context.execute_graph(GRAPH, input_data)
'''


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _relative_backend_path(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(BACKEND_ROOT)
    except ValueError:
        relative = path.resolve()
        return relative.as_posix()
    return f"backend/{relative.as_posix()}"


def _remove_version_tmp_dirs(workflow_dir: Path, version_dir_name: str) -> None:
    if not workflow_dir.exists():
        return
    for tmp_dir in workflow_dir.glob(f".{version_dir_name}.tmp-*"):
        if tmp_dir.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _workflow_dir_is_empty(workflow_dir: Path) -> bool:
    try:
        next(workflow_dir.iterdir())
    except StopIteration:
        return True
    except FileNotFoundError:
        return False
    return False
