"""Normalize a frozen WfCommons WfFormat (JSON) source into the v1 canonical workflow.

The output has exactly the same structure and rules as `generator.dax.normalize_dax`:

- task work = source runtime (exact decimal) x reference_mips;
- dependency data = sum of the producer's output sizes over files shared by parent
  outputs and child inputs (WfFormat declares one size per file id, so the producer
  size and the consumer size are the same value);
- a dependency without a shared file is invalid (no invented edge sizes);
- external entry inputs and exit outputs are not edge communication;
- tasks sorted by id, dependencies by (parent, child), transfer files by name.

Only the WfFormat 1.5+ layout written by WfCommons generators is accepted:
`workflow.specification.{tasks,files}` and `workflow.execution.tasks[].runtimeInSeconds`.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .dax import DaxValidationError, _validate_acyclic, SourceEdge
from .identity import workflow_id


class WfFormatValidationError(DaxValidationError):
    """Raised when a WfFormat source violates the frozen source contract.

    Subclasses DaxValidationError so acquisition code that rejects invalid source
    attempts treats both source formats identically.
    """


def _require(obj: Any, key: str, kind: type, where: str) -> Any:
    if not isinstance(obj, dict) or key not in obj:
        raise WfFormatValidationError(f"{where} is missing {key!r}")
    value = obj[key]
    if not isinstance(value, kind) or isinstance(value, bool):
        raise WfFormatValidationError(f"{where}.{key} has invalid type {type(value).__name__}")
    return value


def _runtime(value: Any, task_id: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise WfFormatValidationError(f"task {task_id!r} runtimeInSeconds is not a number")
    runtime = Decimal(value)
    if not runtime.is_finite() or runtime <= 0:
        raise WfFormatValidationError(f"task {task_id!r} runtimeInSeconds must be finite and > 0")
    return runtime


def normalize_wfformat(
    source: str | Path | bytes,
    *,
    family: str,
    target_task_count: int,
    replicate_id: str,
    reference_mips: int = 1000,
) -> dict:
    if reference_mips <= 0:
        raise ValueError("reference_mips must be > 0")
    if target_task_count <= 0:
        raise ValueError("target_task_count must be > 0")
    if isinstance(source, Path):
        raw = source.read_bytes()
    elif isinstance(source, bytes):
        raw = source
    else:
        raw = source.encode("utf-8")

    try:
        # Exact decimals: never round-trip runtimes through binary floating point.
        document = json.loads(raw, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WfFormatValidationError(f"invalid JSON: {exc}") from exc

    workflow = _require(document, "workflow", dict, "document")
    specification = _require(workflow, "specification", dict, "workflow")
    execution = _require(workflow, "execution", dict, "workflow")
    spec_tasks = _require(specification, "tasks", list, "workflow.specification")
    exec_tasks = _require(execution, "tasks", list, "workflow.execution")
    spec_files = specification.get("files", [])
    if not isinstance(spec_files, list):
        raise WfFormatValidationError("workflow.specification.files must be a list")

    sizes: dict[str, int] = {}
    for item in spec_files:
        file_id = _require(item, "id", str, "file")
        size = _require(item, "sizeInBytes", int, f"file {file_id!r}")
        if size < 0:
            raise WfFormatValidationError(f"file {file_id!r} has negative size")
        if file_id in sizes:
            raise WfFormatValidationError(f"duplicate file id {file_id!r}")
        sizes[file_id] = size

    runtimes: dict[str, Decimal] = {}
    for item in exec_tasks:
        task_id = _require(item, "id", str, "execution task")
        if task_id in runtimes:
            raise WfFormatValidationError(f"duplicate execution task {task_id!r}")
        if "runtimeInSeconds" not in item:
            raise WfFormatValidationError(f"task {task_id!r} is missing runtimeInSeconds")
        runtimes[task_id] = _runtime(item["runtimeInSeconds"], task_id)

    tasks: dict[str, dict[str, Any]] = {}
    for item in spec_tasks:
        task_id = _require(item, "id", str, "task")
        if not task_id:
            raise WfFormatValidationError("task id must be non-empty")
        if task_id in tasks:
            raise WfFormatValidationError(f"duplicate task id {task_id!r}")
        record = {"id": task_id}
        for key in ("parents", "children", "inputFiles", "outputFiles"):
            values = item.get(key, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise WfFormatValidationError(f"task {task_id!r} {key} must be a list of ids")
            record[key] = values
        for file_id in (*record["inputFiles"], *record["outputFiles"]):
            if file_id not in sizes:
                raise WfFormatValidationError(f"task {task_id!r} uses undeclared file {file_id!r}")
        tasks[task_id] = record
    if not tasks:
        raise WfFormatValidationError("workflow contains no tasks")
    if set(runtimes) != set(tasks):
        raise WfFormatValidationError("specification and execution task sets differ")
    if len(tasks) != target_task_count:
        raise WfFormatValidationError(
            f"actual task count {len(tasks)} does not equal exact target {target_task_count}"
        )

    edge_set: set[tuple[str, str]] = set()
    for task_id, record in tasks.items():
        for parent in record["parents"]:
            if parent not in tasks:
                raise WfFormatValidationError(f"parent ref {parent!r} does not name an existing task")
            if parent == task_id:
                raise WfFormatValidationError(f"self dependency for {task_id!r}")
            if task_id not in tasks[parent]["children"]:
                raise WfFormatValidationError(f"edge {parent!r}->{task_id!r} missing from parent children")
            edge_set.add((parent, task_id))
        for child in record["children"]:
            if child not in tasks or task_id not in tasks[child]["parents"]:
                raise WfFormatValidationError(f"edge {task_id!r}->{child!r} missing from child parents")
    edges = tuple(SourceEdge(parent=p, child=c) for p, c in sorted(edge_set))
    try:
        _validate_acyclic(set(tasks), edges)
    except DaxValidationError as exc:
        raise WfFormatValidationError("workflow dependency graph contains a cycle") from exc

    normalized_tasks = []
    for task_id in sorted(tasks):
        runtime = runtimes[task_id]
        normalized_tasks.append(
            {
                "task_id": task_id,
                "source_runtime_s": format(runtime, "f"),
                "work_mi": format(runtime * Decimal(reference_mips), "f"),
            }
        )

    normalized_edges = []
    for edge in edges:
        shared = sorted(set(tasks[edge.parent]["outputFiles"]) & set(tasks[edge.child]["inputFiles"]))
        if not shared:
            raise WfFormatValidationError(
                f"dependency {edge.parent!r}->{edge.child!r} has no shared file metadata"
            )
        data_bytes = sum(sizes[name] for name in shared)
        normalized_edges.append(
            {
                "parent": edge.parent,
                "child": edge.child,
                "data_bytes": data_bytes,
                "data_bits": data_bytes * 8,
                "data_size_source": "producer_output",
                "transfer_files": [
                    {
                        "name": name,
                        "producer_size_bytes": sizes[name],
                        "consumer_declared_sizes_bytes": [sizes[name]],
                        "consumer_size_matches_producer": True,
                    }
                    for name in shared
                ],
            }
        )

    source_sha256 = sha256(raw).hexdigest()
    return {
        "schema_version": 1,
        "metadata": {
            "workflow_id": workflow_id(
                family=family,
                target_task_count=target_task_count,
                replicate_id=replicate_id,
                source_sha256=source_sha256,
            ),
            "family": family,
            "target_task_count": target_task_count,
            "actual_task_count": len(tasks),
            "source_replicate": replicate_id,
            "source_sha256": source_sha256,
            "reference_mips": reference_mips,
        },
        "tasks": normalized_tasks,
        "dependencies": normalized_edges,
    }


def normalize_source(
    source: Path,
    *,
    family: str,
    target_task_count: int,
    replicate_id: str,
    reference_mips: int = 1000,
) -> dict:
    """Dispatch on the frozen source format: `.dax` (Pegasus) or `.json` (WfFormat)."""
    from .dax import normalize_dax

    kwargs = dict(family=family, target_task_count=target_task_count,
                  replicate_id=replicate_id, reference_mips=reference_mips)
    suffix = Path(source).suffix.lower()
    if suffix == ".dax":
        return normalize_dax(Path(source), **kwargs)
    if suffix == ".json":
        return normalize_wfformat(Path(source), **kwargs)
    raise ValueError(f"unsupported source workflow format: {source}")
