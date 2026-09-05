from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import heapq
from typing import Any, Callable, Iterable, Mapping

from .canonical import canonical_json_bytes
from .schedule import ScheduleEvaluation, build_schedule


REFERENCE_SCHEDULER_VERSION = "ifc_v1"
CALIBRATION_VERSION = "ifc_calibration_v1"
HEFT_IFC_ID = "deterministic_heft_ifc"
PEFT_IFC_ID = "deterministic_peft_ifc"
CPOP_IFC_ID = "deterministic_cpop_ifc"
COST_IFC_ID = "deterministic_cost_reference_ifc"
MOHEFT_ID = "deterministic_moheft"
REFERENCE_SCHEDULER_IDS = (HEFT_IFC_ID, PEFT_IFC_ID, CPOP_IFC_ID, COST_IFC_ID)


class ReferenceSchedulerError(ValueError):
    """Raised when a reference scheduler cannot construct a valid deterministic schedule."""


@dataclass(frozen=True)
class _Graph:
    task_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    parents: dict[str, tuple[str, ...]]
    children: dict[str, tuple[str, ...]]
    topological_order: tuple[str, ...]


@dataclass(frozen=True)
class _PartialState:
    assignments: dict[str, dict[str, Any]]
    intervals_by_resource: dict[str, tuple[dict[str, Any], ...]]
    makespan_us: int
    compute_cost_ncu: int
    path_code: int


@dataclass(frozen=True)
class _Expansion:
    base: _PartialState
    assignment: dict[str, Any]
    makespan_us: int
    compute_cost_ncu: int
    path_code: int


def _graph(instance: Mapping[str, Any]) -> _Graph:
    try:
        task_ids = tuple(task["task_id"] for task in instance["tasks"])
        resource_ids = tuple(resource["resource_id"] for resource in instance["resources"])
        dependencies = instance["dependencies"]
    except (KeyError, TypeError) as exc:
        raise ReferenceSchedulerError(f"invalid base instance: {exc}") from exc
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ReferenceSchedulerError("base instance must contain unique tasks")
    if not resource_ids or len(resource_ids) != len(set(resource_ids)):
        raise ReferenceSchedulerError("base instance must contain unique resources")

    parents: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    children: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    indegree = {task_id: 0 for task_id in task_ids}
    task_set = set(task_ids)
    for dependency in dependencies:
        parent = dependency["parent"]
        child = dependency["child"]
        if parent not in task_set or child not in task_set:
            raise ReferenceSchedulerError(f"dependency {parent!r}->{child!r} references an unknown task")
        parents[child].append(parent)
        children[parent].append(child)
        indegree[child] += 1
    for values in parents.values():
        values.sort()
    for values in children.values():
        values.sort()

    ready = [task_id for task_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []
    remaining = dict(indegree)
    while ready:
        task_id = heapq.heappop(ready)
        order.append(task_id)
        for child in children[task_id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                heapq.heappush(ready, child)
    if len(order) != len(task_ids):
        raise ReferenceSchedulerError("workflow dependency graph contains a cycle")

    return _Graph(
        task_ids=task_ids,
        resource_ids=resource_ids,
        parents={key: tuple(value) for key, value in parents.items()},
        children={key: tuple(value) for key, value in children.items()},
        topological_order=tuple(order),
    )


def _mean(values: Iterable[int | Fraction]) -> Fraction:
    items = list(values)
    if not items:
        return Fraction(0, 1)
    return sum((Fraction(value) for value in items), Fraction(0, 1)) / len(items)


def _average_execution(instance: Mapping[str, Any], graph: _Graph) -> dict[str, Fraction]:
    return {
        task_id: _mean(instance["execution_time_us"][task_id][resource_id] for resource_id in graph.resource_ids)
        for task_id in graph.task_ids
    }


def _average_communication(instance: Mapping[str, Any], graph: _Graph) -> dict[str, Fraction]:
    averages: dict[str, Fraction] = {}
    for parent in graph.task_ids:
        for child in graph.children[parent]:
            edge_id = f"{parent}->{child}"
            values = [
                instance["communication"][edge_id][f"{source}|{target}"]["communication_time_us"]
                for source in graph.resource_ids
                for target in graph.resource_ids
                if source != target
            ]
            averages[edge_id] = _mean(values)
    return averages


def _upward_ranks(
    instance: Mapping[str, Any], graph: _Graph
) -> tuple[dict[str, Fraction], dict[str, Fraction], dict[str, Fraction]]:
    average_execution = _average_execution(instance, graph)
    average_communication = _average_communication(instance, graph)
    rank: dict[str, Fraction] = {}
    for task_id in reversed(graph.topological_order):
        descendants = graph.children[task_id]
        tail = max(
            (
                average_communication[f"{task_id}->{child}"] + rank[child]
                for child in descendants
            ),
            default=Fraction(0, 1),
        )
        rank[task_id] = average_execution[task_id] + tail
    return rank, average_execution, average_communication


def _downward_ranks(
    graph: _Graph,
    average_execution: Mapping[str, Fraction],
    average_communication: Mapping[str, Fraction],
) -> dict[str, Fraction]:
    rank: dict[str, Fraction] = {}
    for task_id in graph.topological_order:
        rank[task_id] = max(
            (
                rank[parent]
                + average_execution[parent]
                + average_communication[f"{parent}->{task_id}"]
                for parent in graph.parents[task_id]
            ),
            default=Fraction(0, 1),
        )
    return rank


def _priority_order(graph: _Graph, priorities: Mapping[str, Fraction]) -> list[str]:
    indegree = {task_id: len(graph.parents[task_id]) for task_id in graph.task_ids}
    ready: list[tuple[Fraction, str]] = [
        (-priorities[task_id], task_id)
        for task_id, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, task_id = heapq.heappop(ready)
        order.append(task_id)
        for child in graph.children[task_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, (-priorities[child], child))
    if len(order) != len(graph.task_ids):
        raise ReferenceSchedulerError("priority ordering could not cover every task")
    return order


def _earliest_idle_slot(
    intervals: Iterable[Mapping[str, Any]], *, ready_us: int, duration_us: int
) -> int:
    candidate = ready_us
    for interval in intervals:
        if candidate + duration_us <= interval["start_us"]:
            return candidate
        if candidate < interval["end_us"]:
            candidate = interval["end_us"]
    return candidate


def _candidate_assignment(
    instance: Mapping[str, Any],
    graph: _Graph,
    *,
    task_id: str,
    resource_id: str,
    assignments: Mapping[str, Mapping[str, Any]],
    intervals_by_resource: Mapping[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    duration_us = int(instance["execution_time_us"][task_id][resource_id])
    ready_us = 0
    for parent in graph.parents[task_id]:
        try:
            parent_assignment = assignments[parent]
        except KeyError as exc:
            raise ReferenceSchedulerError(
                f"task {task_id!r} considered before parent {parent!r}"
            ) from exc
        edge_id = f"{parent}->{task_id}"
        pair = f"{parent_assignment['resource_id']}|{resource_id}"
        transfer_us = int(
            instance["communication"][edge_id][pair]["communication_time_us"]
        )
        ready_us = max(ready_us, int(parent_assignment["end_us"]) + transfer_us)
    intervals = intervals_by_resource.get(resource_id, ())
    start_us = _earliest_idle_slot(intervals, ready_us=ready_us, duration_us=duration_us)
    return {
        "task_id": task_id,
        "resource_id": resource_id,
        "start_us": start_us,
        "end_us": start_us + duration_us,
    }


def _insert_interval(
    intervals: tuple[dict[str, Any], ...], assignment: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    return tuple(
        sorted(
            (*intervals, assignment),
            key=lambda item: (item["start_us"], item["end_us"], item["task_id"]),
        )
    )


def _commit_assignment(
    assignments: dict[str, dict[str, Any]],
    intervals_by_resource: dict[str, tuple[dict[str, Any], ...]],
    assignment: dict[str, Any],
) -> None:
    assignments[assignment["task_id"]] = assignment
    resource_id = assignment["resource_id"]
    intervals_by_resource[resource_id] = _insert_interval(
        intervals_by_resource.get(resource_id, ()), assignment
    )


def _greedy_schedule(
    instance: Mapping[str, Any],
    graph: _Graph,
    *,
    order: list[str],
    candidate_resources: Callable[[str], Iterable[str]],
    candidate_key: Callable[[str, str, dict[str, Any]], tuple[Any, ...]],
) -> ScheduleEvaluation:
    assignments: dict[str, dict[str, Any]] = {}
    intervals: dict[str, tuple[dict[str, Any], ...]] = {}
    mapping: dict[str, str] = {}
    for task_id in order:
        candidates: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for resource_id in candidate_resources(task_id):
            assignment = _candidate_assignment(
                instance,
                graph,
                task_id=task_id,
                resource_id=resource_id,
                assignments=assignments,
                intervals_by_resource=intervals,
            )
            candidates.append((candidate_key(task_id, resource_id, assignment), assignment))
        if not candidates:
            raise ReferenceSchedulerError(f"task {task_id!r} has no candidate resource")
        _, selected = min(candidates, key=lambda item: item[0])
        mapping[task_id] = selected["resource_id"]
        _commit_assignment(assignments, intervals, selected)
    return build_schedule(instance, task_order=order, resource_assignments=mapping)


def schedule_heft_ifc(instance: Mapping[str, Any]) -> ScheduleEvaluation:
    """Run deterministic HEFT over the full materialized IFC resource/network model."""
    graph = _graph(instance)
    upward, _, _ = _upward_ranks(instance, graph)
    order = _priority_order(graph, upward)
    return _greedy_schedule(
        instance,
        graph,
        order=order,
        candidate_resources=lambda _task: graph.resource_ids,
        candidate_key=lambda _task, resource, assignment: (
            assignment["end_us"],
            resource,
        ),
    )


def _optimistic_cost_table(
    instance: Mapping[str, Any], graph: _Graph
) -> dict[str, dict[str, int]]:
    oct_table: dict[str, dict[str, int]] = {}
    for task_id in reversed(graph.topological_order):
        row: dict[str, int] = {}
        for current_resource in graph.resource_ids:
            child_costs: list[int] = []
            for child in graph.children[task_id]:
                edge_id = f"{task_id}->{child}"
                best_child = min(
                    oct_table[child][child_resource]
                    + int(instance["execution_time_us"][child][child_resource])
                    + int(
                        instance["communication"][edge_id][
                            f"{current_resource}|{child_resource}"
                        ]["communication_time_us"]
                    )
                    for child_resource in graph.resource_ids
                )
                child_costs.append(best_child)
            row[current_resource] = max(child_costs, default=0)
        oct_table[task_id] = row
    return oct_table


def schedule_peft_ifc(instance: Mapping[str, Any]) -> ScheduleEvaluation:
    """Run deterministic PEFT with route-specific IFC communication in the OCT."""
    graph = _graph(instance)
    oct_table = _optimistic_cost_table(instance, graph)
    rank_oct = {
        task_id: _mean(oct_table[task_id][resource] for resource in graph.resource_ids)
        for task_id in graph.task_ids
    }
    order = _priority_order(graph, rank_oct)
    return _greedy_schedule(
        instance,
        graph,
        order=order,
        candidate_resources=lambda _task: graph.resource_ids,
        candidate_key=lambda task, resource, assignment: (
            assignment["end_us"] + oct_table[task][resource],
            assignment["end_us"],
            resource,
        ),
    )


def schedule_cpop_ifc(instance: Mapping[str, Any]) -> ScheduleEvaluation:
    """Run deterministic CPOP using the full IFC pool for non-critical tasks."""
    graph = _graph(instance)
    upward, average_execution, average_communication = _upward_ranks(instance, graph)
    downward = _downward_ranks(graph, average_execution, average_communication)
    priority = {task_id: upward[task_id] + downward[task_id] for task_id in graph.task_ids}
    critical_length = max(priority.values())
    critical_tasks = {task_id for task_id, value in priority.items() if value == critical_length}
    critical_resource = min(
        graph.resource_ids,
        key=lambda resource_id: (
            sum(int(instance["execution_time_us"][task_id][resource_id]) for task_id in critical_tasks),
            resource_id,
        ),
    )
    order = _priority_order(graph, priority)

    def resources(task_id: str) -> Iterable[str]:
        if task_id in critical_tasks:
            return (critical_resource,)
        return graph.resource_ids

    return _greedy_schedule(
        instance,
        graph,
        order=order,
        candidate_resources=resources,
        candidate_key=lambda _task, resource, assignment: (
            assignment["end_us"],
            resource,
        ),
    )


def schedule_cost_reference_ifc(instance: Mapping[str, Any]) -> ScheduleEvaluation:
    """Construct a globally minimum-compute-cost mapping with deterministic EFT tie-breaking."""
    graph = _graph(instance)
    upward, _, _ = _upward_ranks(instance, graph)
    order = _priority_order(graph, upward)
    cheapest: dict[str, tuple[str, ...]] = {}
    for task_id in graph.task_ids:
        row = instance["compute_cost_ncu"][task_id]
        minimum = min(int(row[resource_id]) for resource_id in graph.resource_ids)
        cheapest[task_id] = tuple(
            resource_id
            for resource_id in graph.resource_ids
            if int(row[resource_id]) == minimum
        )
    return _greedy_schedule(
        instance,
        graph,
        order=order,
        candidate_resources=lambda task: cheapest[task],
        candidate_key=lambda _task, resource, assignment: (
            assignment["end_us"],
            resource,
        ),
    )


def _pareto_front_ranks(candidates: list[_Expansion]) -> dict[int, int]:
    """Return exact 2-objective nondominated front numbers in O(n log n)."""
    if not candidates:
        return {}
    costs = sorted({candidate.compute_cost_ncu for candidate in candidates})
    cost_index = {value: index + 1 for index, value in enumerate(costs)}
    tree = [0] * (len(costs) + 1)

    def query(index: int) -> int:
        result = 0
        while index > 0:
            result = max(result, tree[index])
            index -= index & -index
        return result

    def update(index: int, value: int) -> None:
        while index < len(tree):
            tree[index] = max(tree[index], value)
            index += index & -index

    ordered = sorted(
        range(len(candidates)),
        key=lambda index: (
            candidates[index].makespan_us,
            candidates[index].compute_cost_ncu,
            candidates[index].path_code,
        ),
    )
    ranks: dict[int, int] = {}
    cursor = 0
    while cursor < len(ordered):
        first = candidates[ordered[cursor]]
        objective = (first.makespan_us, first.compute_cost_ncu)
        end = cursor + 1
        while end < len(ordered):
            candidate = candidates[ordered[end]]
            if (candidate.makespan_us, candidate.compute_cost_ncu) != objective:
                break
            end += 1
        index = cost_index[objective[1]]
        rank = query(index) + 1
        for position in ordered[cursor:end]:
            ranks[position] = rank
        update(index, rank)
        cursor = end
    return ranks


def _crowding_select(front: list[_Expansion], count: int) -> list[_Expansion]:
    if count <= 0:
        return []
    if len(front) <= count:
        return sorted(front, key=lambda item: (item.makespan_us, item.compute_cost_ncu, item.path_code))
    size = len(front)
    distances = [Fraction(0, 1) for _ in front]
    boundary = [False] * size
    for accessor in (
        lambda item: item.makespan_us,
        lambda item: item.compute_cost_ncu,
    ):
        order = sorted(range(size), key=lambda index: (accessor(front[index]), front[index].path_code))
        low = accessor(front[order[0]])
        high = accessor(front[order[-1]])
        if high == low:
            continue
        boundary[order[0]] = True
        boundary[order[-1]] = True
        width = high - low
        for offset in range(1, size - 1):
            current = order[offset]
            previous_value = accessor(front[order[offset - 1]])
            next_value = accessor(front[order[offset + 1]])
            distances[current] += Fraction(next_value - previous_value, width)
    ranked = sorted(
        range(size),
        key=lambda index: (
            not boundary[index],
            -distances[index],
            front[index].makespan_us,
            front[index].compute_cost_ncu,
            front[index].path_code,
        ),
    )
    return [front[index] for index in ranked[:count]]


def _select_moheft_candidates(candidates: list[_Expansion], k: int) -> list[_Expansion]:
    ranks = _pareto_front_ranks(candidates)
    fronts: dict[int, list[_Expansion]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        fronts[ranks[index]].append(candidate)
    selected: list[_Expansion] = []
    for rank in sorted(fronts):
        front = fronts[rank]
        remaining = k - len(selected)
        if remaining <= 0:
            break
        if len(front) <= remaining:
            selected.extend(
                sorted(
                    front,
                    key=lambda item: (
                        item.makespan_us,
                        item.compute_cost_ncu,
                        item.path_code,
                    ),
                )
            )
        else:
            selected.extend(_crowding_select(front, remaining))
            break
    return selected


def schedule_moheft_ifc(
    instance: Mapping[str, Any], *, k: int = 50
) -> list[ScheduleEvaluation]:
    """Run deterministic bi-objective MOHEFT for makespan and exact compute cost."""
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise ReferenceSchedulerError("MOHEFT k must be a positive integer")
    graph = _graph(instance)
    upward, _, _ = _upward_ranks(instance, graph)
    order = _priority_order(graph, upward)
    resource_index = {resource_id: index for index, resource_id in enumerate(graph.resource_ids)}
    resource_count = len(graph.resource_ids)
    states = [
        _PartialState(
            assignments={},
            intervals_by_resource={},
            makespan_us=0,
            compute_cost_ncu=0,
            path_code=0,
        )
    ]

    for task_id in order:
        expansions: list[_Expansion] = []
        for state in states:
            for resource_id in graph.resource_ids:
                assignment = _candidate_assignment(
                    instance,
                    graph,
                    task_id=task_id,
                    resource_id=resource_id,
                    assignments=state.assignments,
                    intervals_by_resource=state.intervals_by_resource,
                )
                expansions.append(
                    _Expansion(
                        base=state,
                        assignment=assignment,
                        makespan_us=max(state.makespan_us, assignment["end_us"]),
                        compute_cost_ncu=state.compute_cost_ncu
                        + int(instance["compute_cost_ncu"][task_id][resource_id]),
                        path_code=state.path_code * resource_count + resource_index[resource_id],
                    )
                )
        selected = _select_moheft_candidates(expansions, min(k, len(expansions)))
        new_states: list[_PartialState] = []
        for candidate in selected:
            assignments = dict(candidate.base.assignments)
            assignments[task_id] = candidate.assignment
            intervals = dict(candidate.base.intervals_by_resource)
            resource_id = candidate.assignment["resource_id"]
            intervals[resource_id] = _insert_interval(
                intervals.get(resource_id, ()), candidate.assignment
            )
            new_states.append(
                _PartialState(
                    assignments=assignments,
                    intervals_by_resource=intervals,
                    makespan_us=candidate.makespan_us,
                    compute_cost_ncu=candidate.compute_cost_ncu,
                    path_code=candidate.path_code,
                )
            )
        states = new_states

    evaluations: list[ScheduleEvaluation] = []
    seen_ids: set[str] = set()
    for state in states:
        mapping = {
            task_id: state.assignments[task_id]["resource_id"]
            for task_id in order
        }
        evaluation = build_schedule(instance, task_order=order, resource_assignments=mapping)
        schedule = evaluation.schedule
        if schedule["makespan_us"] != state.makespan_us or schedule["compute_cost_ncu"] != state.compute_cost_ncu:
            raise ReferenceSchedulerError("MOHEFT partial-state metrics diverged from authoritative schedule construction")
        if schedule["schedule_id"] not in seen_ids:
            seen_ids.add(schedule["schedule_id"])
            evaluations.append(evaluation)
    evaluations.sort(
        key=lambda evaluation: (
            evaluation.schedule["makespan_us"],
            evaluation.schedule["compute_cost_ncu"],
            evaluation.schedule["schedule_id"],
        )
    )
    return evaluations


def _ceil_fraction(value: Fraction) -> int:
    return (value.numerator + value.denominator - 1) // value.denominator


def calibration_lower_bounds(instance: Mapping[str, Any]) -> dict[str, int]:
    """Compute the frozen optimistic critical-path and aggregate-capacity lower bounds."""
    graph = _graph(instance)
    fastest_execution = {
        task_id: min(int(instance["execution_time_us"][task_id][resource]) for resource in graph.resource_ids)
        for task_id in graph.task_ids
    }
    fastest_communication: dict[str, int] = {}
    for parent in graph.task_ids:
        for child in graph.children[parent]:
            edge_id = f"{parent}->{child}"
            fastest_communication[edge_id] = min(
                int(instance["communication"][edge_id][f"{source}|{target}"]["communication_time_us"])
                for source in graph.resource_ids
                for target in graph.resource_ids
            )
    cp_tail: dict[str, int] = {}
    for task_id in reversed(graph.topological_order):
        cp_tail[task_id] = fastest_execution[task_id] + max(
            (
                fastest_communication[f"{task_id}->{child}"] + cp_tail[child]
                for child in graph.children[task_id]
            ),
            default=0,
        )
    roots = [task_id for task_id in graph.task_ids if not graph.parents[task_id]]
    t_cp = max(cp_tail[root] for root in roots)

    total_work_mi = sum((Fraction(str(task["work_mi"])) for task in instance["tasks"]), Fraction(0, 1))
    total_mips = sum(int(resource["mips"]) for resource in instance["resources"])
    t_capacity = _ceil_fraction(total_work_mi * 1_000_000 / total_mips)
    t_capacity = max(1, t_capacity)
    return {
        "t_cp_lb_us": t_cp,
        "t_capacity_lb_us": t_capacity,
        "t_lb_us": max(t_cp, t_capacity),
    }


def run_reference_portfolio(instance: Mapping[str, Any]) -> list[dict[str, Any]]:
    schedulers = (
        (HEFT_IFC_ID, schedule_heft_ifc),
        (PEFT_IFC_ID, schedule_peft_ifc),
        (CPOP_IFC_ID, schedule_cpop_ifc),
        (COST_IFC_ID, schedule_cost_reference_ifc),
    )
    return [
        {
            "scheduler_id": scheduler_id,
            "scheduler_version": REFERENCE_SCHEDULER_VERSION,
            "schedule": scheduler(instance).schedule,
        }
        for scheduler_id, scheduler in schedulers
    ]


def calibration_candidate_set_sha256(
    reference_schedulers: Iterable[Mapping[str, Any]],
    moheft: Mapping[str, Any],
) -> str:
    """Return the canonical checksum of the frozen calibration candidate set."""
    payload = {
        "reference_schedulers": [dict(item) for item in reference_schedulers],
        "moheft": dict(moheft),
    }
    return sha256(canonical_json_bytes(payload)).hexdigest()


def build_calibration_result(
    instance: Mapping[str, Any], *, k: int = 50
) -> dict[str, Any]:
    """Build the complete deterministic reference-envelope calibration artifact."""
    if k != 50:
        raise ReferenceSchedulerError("v1 calibration artifacts require MOHEFT k = 50")
    references = run_reference_portfolio(instance)
    reference_ids = {item["schedule"]["schedule_id"] for item in references}
    moheft_evaluations = schedule_moheft_ifc(instance, k=k)
    moheft_schedules = [
        evaluation.schedule
        for evaluation in moheft_evaluations
        if evaluation.schedule["schedule_id"] not in reference_ids
    ]
    if not moheft_schedules:
        raise ReferenceSchedulerError("MOHEFT produced no schedule distinct from the explicit reference endpoints")
    moheft = {
        "scheduler_id": MOHEFT_ID,
        "scheduler_version": REFERENCE_SCHEDULER_VERSION,
        "k": k,
        "candidate_schedules": moheft_schedules,
    }
    schedules = [
        *(item["schedule"] for item in references),
        *moheft_schedules,
    ]
    fast = min(
        schedules,
        key=lambda schedule: (
            schedule["makespan_us"],
            schedule["compute_cost_ncu"],
            schedule["schedule_id"],
        ),
    )
    economical = min(
        schedules,
        key=lambda schedule: (
            schedule["compute_cost_ncu"],
            schedule["makespan_us"],
            schedule["schedule_id"],
        ),
    )
    return {
        "schema_version": 1,
        "base_instance_id": instance["metadata"]["base_instance_id"],
        "calibration_version": CALIBRATION_VERSION,
        "lower_bounds": calibration_lower_bounds(instance),
        "reference_schedulers": references,
        "moheft": moheft,
        "anchors": {
            "fast_schedule_id": fast["schedule_id"],
            "economical_schedule_id": economical["schedule_id"],
            "t_fast_us": fast["makespan_us"],
            "t_economical_us": economical["makespan_us"],
            "cost_fast_ncu": fast["compute_cost_ncu"],
            "cost_economical_ncu": economical["compute_cost_ncu"],
            "deadline_range_degenerate": fast["makespan_us"] == economical["makespan_us"],
        },
        "candidate_set_sha256": calibration_candidate_set_sha256(references, moheft),
    }
