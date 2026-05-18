from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[2]
GENERATED_ROOT = BACKEND_ROOT / "generated_workflows"


@dataclass(frozen=True)
class WorkflowCodeArtifact:
    code_path: str
    code_hash: str
    code_generated_at: datetime
    version_dir: Path


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
        tmp_dir.mkdir(parents=True, exist_ok=False)
        (tmp_dir / "__init__.py").write_text("", encoding="utf-8")
        workflow_source = _render_workflow_py(graph)
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
