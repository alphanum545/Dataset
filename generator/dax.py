from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

from .exact import ceil_decimal, parse_positive_decimal


class DaxValidationError(ValueError):
    """Raised when a source DAX violates the frozen source contract."""


@dataclass(frozen=True)
class SourceFileUse:
    name: str
    link: str
    size_bytes: int


@dataclass(frozen=True)
class SourceTask:
    task_id: str
    runtime_text: str
    runtime_s: Decimal
    files: tuple[SourceFileUse, ...]


@dataclass(frozen=True)
class SourceEdge:
    parent: str
    child: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> Iterable[ET.Element]:
    for child in element:
        if _local_name(child.tag) == name:
            yield child


def _parse_size(value: str | None, *, task_id: str, file_name: str) -> int:
    if value is None:
        raise DaxValidationError(
            f"file {file_name!r} used by {task_id!r} is missing required size"
        )
    try:
        parsed = int(value)
    except ValueError as exc:
        raise DaxValidationError(
            f"file {file_name!r} used by {task_id!r} has invalid size {value!r}"
        ) from exc
    if parsed < 0:
        raise DaxValidationError(
            f"file {file_name!r} used by {task_id!r} has negative size"
        )
    return parsed


def _parse_jobs(root: ET.Element) -> dict[str, SourceTask]:
    tasks: dict[str, SourceTask] = {}
    for job in root.iter():
        if _local_name(job.tag) != "job":
            continue
        task_id = job.attrib.get("id")
        runtime_text = job.attrib.get("runtime")
        if not task_id:
            raise DaxValidationError("job is missing id")
        if task_id in tasks:
            raise DaxValidationError(f"duplicate job id {task_id!r}")
        if runtime_text is None:
            raise DaxValidationError(f"job {task_id!r} is missing runtime")
        try:
            runtime_s = parse_positive_decimal(runtime_text, field=f"runtime[{task_id}]")
        except ValueError as exc:
            raise DaxValidationError(str(exc)) from exc

        files: list[SourceFileUse] = []
        for use in _children(job, "uses"):
            name = use.attrib.get("file") or use.attrib.get("name")
            link = (use.attrib.get("link") or "").lower()
            if not name:
                raise DaxValidationError(f"job {task_id!r} contains unnamed file use")
            if link not in {"input", "output"}:
                raise DaxValidationError(
                    f"job {task_id!r} file {name!r} has unsupported link {link!r}"
                )
            files.append(
                SourceFileUse(
                    name=name,
                    link=link,
                    size_bytes=_parse_size(use.attrib.get("size"), task_id=task_id, file_name=name),
                )
            )
        tasks[task_id] = SourceTask(
            task_id=task_id,
            runtime_text=runtime_text,
            runtime_s=runtime_s,
            files=tuple(sorted(files, key=lambda item: (item.name, item.link, item.size_bytes))),
        )
    if not tasks:
        raise DaxValidationError("DAX contains no jobs")
    return tasks


def _parse_edges(root: ET.Element, task_ids: set[str]) -> tuple[SourceEdge, ...]:
    edges: set[tuple[str, str]] = set()
    for child_node in root.iter():
        if _local_name(child_node.tag) != "child":
            continue
        child = child_node.attrib.get("ref")
        if not child or child not in task_ids:
            raise DaxValidationError(f"child ref {child!r} does not name an existing job")
        for parent_node in _children(child_node, "parent"):
            parent = parent_node.attrib.get("ref")
            if not parent or parent not in task_ids:
                raise DaxValidationError(
                    f"parent ref {parent!r} does not name an existing job"
                )
            if parent == child:
                raise DaxValidationError(f"self dependency for {parent!r}")
            edges.add((parent, child))
    return tuple(SourceEdge(parent=p, child=c) for p, c in sorted(edges))


def _validate_acyclic(task_ids: set[str], edges: tuple[SourceEdge, ...]) -> None:
    indegree = {task_id: 0 for task_id in task_ids}
    children: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        children[edge.parent].append(edge.child)
        indegree[edge.child] += 1

    ready = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        current = ready.popleft()
        visited += 1
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(task_ids):
        raise DaxValidationError("DAX dependency graph contains a cycle")


def _edge_transfer_metadata(parent: SourceTask, child: SourceTask) -> tuple[int, list[dict]]:
    parent_outputs: dict[str, int] = {}
    for use in parent.files:
        if use.link == "output":
            previous = parent_outputs.get(use.name)
            if previous is not None and previous != use.size_bytes:
                raise DaxValidationError(
                    f"parent {parent.task_id!r} declares inconsistent sizes for {use.name!r}"
                )
            parent_outputs[use.name] = use.size_bytes

    child_inputs: dict[str, set[int]] = defaultdict(set)
    for use in child.files:
        if use.link == "input":
            child_inputs[use.name].add(use.size_bytes)

    shared = sorted(set(parent_outputs).intersection(child_inputs))
    if not shared:
        raise DaxValidationError(
            f"dependency {parent.task_id!r}->{child.task_id!r} has no shared file metadata"
        )

    total = 0
    transfer_files: list[dict] = []
    for name in shared:
        producer_size = parent_outputs[name]
        consumer_sizes = sorted(child_inputs[name])
        total += producer_size
        transfer_files.append(
            {
                "name": name,
                "producer_size_bytes": producer_size,
                "consumer_declared_sizes_bytes": consumer_sizes,
                "consumer_size_matches_producer": consumer_sizes == [producer_size],
            }
        )
    return total, transfer_files


def normalize_dax(
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
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DaxValidationError(f"invalid XML: {exc}") from exc

    tasks = _parse_jobs(root)
    if len(tasks) != target_task_count:
        raise DaxValidationError(
            f"actual task count {len(tasks)} does not equal exact target {target_task_count}"
        )
    edges = _parse_edges(root, set(tasks))
    _validate_acyclic(set(tasks), edges)

    normalized_tasks = []
    for task_id in sorted(tasks):
        task = tasks[task_id]
        work_mi = task.runtime_s * Decimal(reference_mips)
        normalized_tasks.append(
            {
                "task_id": task_id,
                "source_runtime_s": format(task.runtime_s, "f"),
                "work_mi": format(work_mi, "f"),
            }
        )

    normalized_edges = []
    for edge in edges:
        data_bytes, transfer_files = _edge_transfer_metadata(tasks[edge.parent], tasks[edge.child])
        normalized_edges.append(
            {
                "parent": edge.parent,
                "child": edge.child,
                "data_bytes": data_bytes,
                "data_bits": data_bytes * 8,
                "data_size_source": "producer_output",
                "transfer_files": transfer_files,
            }
        )

    return {
        "metadata": {
            "family": family,
            "target_task_count": target_task_count,
            "actual_task_count": len(tasks),
            "source_replicate": replicate_id,
            "source_sha256": sha256(raw).hexdigest(),
            "reference_mips": reference_mips,
        },
        "tasks": normalized_tasks,
        "dependencies": normalized_edges,
    }


def execution_time_us(work_mi_text: str, resource_mips: int) -> int:
    if resource_mips <= 0:
        raise ValueError("resource_mips must be > 0")
    work_mi = parse_positive_decimal(work_mi_text, field="work_mi")
    return ceil_decimal(work_mi * Decimal(1_000_000) / Decimal(resource_mips))
