from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable, Mapping

from .canonical import canonical_json_bytes, content_sha256
from .network import resource_route_metrics


_SCHEDULE_KEYS = {
    "schedule_id",
    "schedule_sha256",
    "assignments",
    "makespan_us",
    "compute_cost_ncu",
    "compute_energy_nj",
    "network_energy_pj",
}
_ASSIGNMENT_KEYS = {"task_id", "resource_id", "start_us", "end_us"}


class ScheduleEvaluationError(ValueError):
    """Raised when a schedule input or evaluated schedule violates v1 semantics."""


@dataclass(frozen=True)
class ScheduleEvaluation:
    """Authoritative metrics for one precedence/resource-valid schedule."""

    schedule: dict[str, Any]
    dependency_arrival_us: dict[str, int]
    task_dependency_ready_us: dict[str, int]
    communication_time_us: int
    deadline_us: int | None
    budget_ncu: int | None
    deadline_feasible: bool | None
    budget_feasible: bool | None
    joint_feasible: bool | None


def _fail(message: str) -> None:
    raise ScheduleEvaluationError(message)


def _exact_int(value: Any, *, label: str, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(f"{label} must be an exact integer")
    if value < minimum:
        _fail(f"{label} must be >= {minimum}")
    return value


def _optional_exact_int(value: Any, *, label: str, minimum: int) -> int | None:
    if value is None:
        return None
    return _exact_int(value, label=label, minimum=minimum)


def _instance_dimensions(instance: Mapping[str, Any]) -> tuple[list[str], set[str]]:
    try:
        task_ids = [task["task_id"] for task in instance["tasks"]]
        resource_ids = {resource["resource_id"] for resource in instance["resources"]}
    except (KeyError, TypeError) as exc:
        _fail(f"base instance is missing evaluator input data: {exc}")
    if not task_ids:
        _fail("base instance must contain at least one task")
    if len(task_ids) != len(set(task_ids)):
        _fail("base instance task IDs must be unique")
    if not resource_ids:
        _fail("base instance must contain at least one resource")
    return task_ids, resource_ids


def _resource_tiers(instance: Mapping[str, Any]) -> dict[str, str]:
    try:
        tiers = {
            str(resource["resource_id"]): str(resource["tier"])
            for resource in instance["resources"]
        }
    except (KeyError, TypeError) as exc:
        _fail(f"base instance is missing resource tier data: {exc}")
    if len(tiers) != len(instance["resources"]):
        _fail("base instance resource IDs must be unique")
    return tiers


def canonical_schedule_id(
    instance: Mapping[str, Any], assignments: Iterable[Mapping[str, Any]]
) -> str:
    """Return the content-derived v1 identity for a schedule's timed assignments."""
    try:
        base_identifier = instance["metadata"]["base_instance_id"]
    except (KeyError, TypeError) as exc:
        _fail(f"base instance is missing metadata.base_instance_id: {exc}")
    if not isinstance(base_identifier, str) or not base_identifier:
        _fail("metadata.base_instance_id must be a non-empty string")
    canonical_assignments = [dict(assignment) for assignment in assignments]
    fingerprint = sha256(canonical_json_bytes(canonical_assignments)).hexdigest()[:16]
    return f"schedule-{base_identifier}-{fingerprint}"


def _canonical_assignment_map(
    instance: Mapping[str, Any], schedule: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(schedule, Mapping):
        _fail("schedule must be an object")
    if set(schedule) != _SCHEDULE_KEYS:
        _fail("schedule fields do not exactly match the v1 schedule contract")
    assignments_value = schedule["assignments"]
    if not isinstance(assignments_value, list) or not assignments_value:
        _fail("schedule assignments must be a non-empty list")

    expected_task_ids, resource_ids = _instance_dimensions(instance)
    expected_task_set = set(expected_task_ids)
    assignments: list[dict[str, Any]] = []
    assignment_by_task: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(assignments_value):
        if not isinstance(candidate, Mapping) or set(candidate) != _ASSIGNMENT_KEYS:
            _fail(f"schedule assignment {index} does not match the v1 assignment contract")
        task_id = candidate["task_id"]
        resource_id = candidate["resource_id"]
        if not isinstance(task_id, str):
            _fail(f"schedule assignment {index} task_id must be a string")
        if task_id in assignment_by_task:
            _fail(f"schedule contains duplicate assignment for task {task_id!r}")
        if task_id not in expected_task_set:
            _fail(f"schedule assigns unknown task {task_id!r}")
        if not isinstance(resource_id, str) or resource_id not in resource_ids:
            _fail(f"schedule assigns task {task_id!r} to unknown resource {resource_id!r}")
        start_us = _exact_int(candidate["start_us"], label=f"start_us for {task_id!r}", minimum=0)
        end_us = _exact_int(candidate["end_us"], label=f"end_us for {task_id!r}", minimum=1)
        if end_us <= start_us:
            _fail(f"schedule task {task_id!r} must end after it starts")
        assignment = {
            "task_id": task_id,
            "resource_id": resource_id,
            "start_us": start_us,
            "end_us": end_us,
        }
        assignments.append(assignment)
        assignment_by_task[task_id] = assignment

    actual_task_ids = [assignment["task_id"] for assignment in assignments]
    if set(actual_task_ids) != expected_task_set:
        missing = sorted(expected_task_set - set(actual_task_ids))
        _fail(f"schedule assignments do not cover every task; missing: {', '.join(missing)}")
    if actual_task_ids != sorted(actual_task_ids):
        _fail("schedule assignments must use canonical task_id ordering")
    return assignments, assignment_by_task


def _check_durations_and_contention(
    instance: Mapping[str, Any],
    assignments: list[dict[str, Any]],
) -> None:
    intervals_by_resource: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assignment in assignments:
        task_id = assignment["task_id"]
        resource_id = assignment["resource_id"]
        try:
            expected_duration = instance["execution_time_us"][task_id][resource_id]
        except (KeyError, TypeError) as exc:
            _fail(f"base instance has no execution time for {task_id!r} on {resource_id!r}: {exc}")
        expected_duration = _exact_int(
            expected_duration,
            label=f"execution_time_us[{task_id!r}][{resource_id!r}]",
            minimum=1,
        )
        if assignment["end_us"] - assignment["start_us"] != expected_duration:
            _fail(
                f"schedule duration for task {task_id!r} does not equal its materialized "
                f"execution time on {resource_id!r}"
            )
        intervals_by_resource[resource_id].append(assignment)

    for resource_id, intervals in intervals_by_resource.items():
        ordered = sorted(
            intervals,
            key=lambda item: (item["start_us"], item["end_us"], item["task_id"]),
        )
        for previous, current in zip(ordered, ordered[1:]):
            if previous["end_us"] > current["start_us"]:
                _fail(
                    f"resource {resource_id!r} has overlapping tasks "
                    f"{previous['task_id']!r} and {current['task_id']!r}"
                )


def _dependency_metrics(
    instance: Mapping[str, Any],
    assignment_by_task: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, int], dict[str, int], int, int]:
    dependency_arrival_us: dict[str, int] = {}
    task_ready_us = {task_id: 0 for task_id in assignment_by_task}
    communication_time_us = 0
    network_energy_pj = 0
    resource_tiers = _resource_tiers(instance)
    try:
        dependencies = instance["dependencies"]
        network = instance["network"]
    except KeyError as exc:
        _fail(f"base instance is missing communication input data: {exc}")

    for dependency in dependencies:
        try:
            parent = dependency["parent"]
            child = dependency["child"]
            data_bits = _exact_int(
                dependency["data_bits"],
                label=f"data_bits for {parent!r}->{child!r}",
                minimum=0,
            )
            parent_assignment = assignment_by_task[parent]
            child_assignment = assignment_by_task[child]
            communication = resource_route_metrics(
                network,
                resource_tiers,
                source_resource_id=parent_assignment["resource_id"],
                target_resource_id=child_assignment["resource_id"],
                data_bits=data_bits,
            )
        except (KeyError, TypeError, ValueError) as exc:
            _fail(f"base instance contains invalid communication input data: {exc}")
        edge_id = f"{parent}->{child}"
        pair = f"{parent_assignment['resource_id']}|{child_assignment['resource_id']}"
        transfer_time = _exact_int(
            communication["communication_time_us"],
            label=f"communication time for {edge_id!r} on {pair!r}",
            minimum=0,
        )
        transfer_energy = _exact_int(
            communication["communication_energy_pj"],
            label=f"communication energy for {edge_id!r} on {pair!r}",
            minimum=0,
        )
        if parent_assignment["resource_id"] == child_assignment["resource_id"] and (
            transfer_time != 0 or transfer_energy != 0
        ):
            _fail(f"same-resource communication for dependency {edge_id!r} must be zero")

        arrival_us = parent_assignment["end_us"] + transfer_time
        dependency_arrival_us[edge_id] = arrival_us
        task_ready_us[child] = max(task_ready_us[child], arrival_us)
        communication_time_us += transfer_time
        network_energy_pj += transfer_energy
        if child_assignment["start_us"] < arrival_us:
            _fail(
                f"task {child!r} starts before dependency {edge_id!r} arrives "
                f"at {arrival_us} us"
            )

    return dependency_arrival_us, task_ready_us, communication_time_us, network_energy_pj


def _matrix_total(
    instance: Mapping[str, Any],
    assignments: Iterable[Mapping[str, Any]],
    *,
    matrix_name: str,
) -> int:
    total = 0
    for assignment in assignments:
        task_id = assignment["task_id"]
        resource_id = assignment["resource_id"]
        try:
            value = instance[matrix_name][task_id][resource_id]
        except (KeyError, TypeError) as exc:
            _fail(f"base instance has no {matrix_name} value for {task_id!r} on {resource_id!r}: {exc}")
        total += _exact_int(
            value,
            label=f"{matrix_name}[{task_id!r}][{resource_id!r}]",
            minimum=0,
        )
    return total


def evaluate_schedule(
    instance: Mapping[str, Any],
    schedule: Mapping[str, Any],
    *,
    deadline_us: int | None = None,
    budget_ncu: int | None = None,
) -> ScheduleEvaluation:
    """Recompute and verify every authoritative metric in an explicit schedule."""
    checked_deadline = _optional_exact_int(deadline_us, label="deadline_us", minimum=1)
    checked_budget = _optional_exact_int(budget_ncu, label="budget_ncu", minimum=0)
    assignments, assignment_by_task = _canonical_assignment_map(instance, schedule)
    _check_durations_and_contention(instance, assignments)
    (
        dependency_arrival_us,
        task_ready_us,
        communication_time_us,
        network_energy_pj,
    ) = _dependency_metrics(instance, assignment_by_task)

    makespan_us = max(assignment["end_us"] for assignment in assignments)
    compute_cost_ncu = _matrix_total(
        instance, assignments, matrix_name="compute_cost_ncu"
    )
    compute_energy_nj = _matrix_total(
        instance, assignments, matrix_name="compute_energy_nj"
    )
    expected_values = {
        "makespan_us": makespan_us,
        "compute_cost_ncu": compute_cost_ncu,
        "compute_energy_nj": compute_energy_nj,
        "network_energy_pj": network_energy_pj,
    }
    for field, expected in expected_values.items():
        actual = _exact_int(schedule[field], label=field, minimum=0)
        if actual != expected:
            _fail(f"schedule {field} is {actual}, expected {expected}")

    expected_id = canonical_schedule_id(instance, assignments)
    if schedule["schedule_id"] != expected_id:
        _fail("schedule_id does not match the canonical timed-assignment identity")
    expected_checksum = content_sha256(dict(schedule), checksum_field="schedule_sha256")
    if schedule["schedule_sha256"] != expected_checksum:
        _fail("schedule_sha256 does not match canonical schedule content")

    deadline_feasible = (
        None if checked_deadline is None else makespan_us <= checked_deadline
    )
    budget_feasible = (
        None if checked_budget is None else compute_cost_ncu <= checked_budget
    )
    joint_feasible = (
        None
        if deadline_feasible is None or budget_feasible is None
        else deadline_feasible and budget_feasible
    )
    verified_schedule = {
        "schedule_id": schedule["schedule_id"],
        "schedule_sha256": schedule["schedule_sha256"],
        "assignments": assignments,
        "makespan_us": makespan_us,
        "compute_cost_ncu": compute_cost_ncu,
        "compute_energy_nj": compute_energy_nj,
        "network_energy_pj": network_energy_pj,
    }
    return ScheduleEvaluation(
        schedule=verified_schedule,
        dependency_arrival_us=dependency_arrival_us,
        task_dependency_ready_us=task_ready_us,
        communication_time_us=communication_time_us,
        deadline_us=checked_deadline,
        budget_ncu=checked_budget,
        deadline_feasible=deadline_feasible,
        budget_feasible=budget_feasible,
        joint_feasible=joint_feasible,
    )


def _earliest_idle_slot(
    intervals: Iterable[Mapping[str, Any]], *, ready_us: int, duration_us: int
) -> int:
    candidate = ready_us
    for interval in sorted(
        intervals,
        key=lambda item: (item["start_us"], item["end_us"], item["task_id"]),
    ):
        if candidate + duration_us <= interval["start_us"]:
            return candidate
        if candidate < interval["end_us"]:
            candidate = interval["end_us"]
    return candidate


def build_schedule(
    instance: Mapping[str, Any],
    *,
    task_order: Iterable[str],
    resource_assignments: Mapping[str, str],
    deadline_us: int | None = None,
    budget_ncu: int | None = None,
) -> ScheduleEvaluation:
    """Build the earliest feasible serial schedule for a fixed order and mapping."""
    expected_task_ids, resource_ids = _instance_dimensions(instance)
    expected_task_set = set(expected_task_ids)
    if isinstance(task_order, (str, bytes)):
        _fail("task_order must be an iterable of task IDs, not a string")
    order = list(task_order)
    if any(not isinstance(task_id, str) for task_id in order):
        _fail("task_order values must be task ID strings")
    if len(order) != len(set(order)):
        _fail("task_order must not contain duplicate task IDs")
    if set(order) != expected_task_set:
        missing = sorted(expected_task_set - set(order))
        extra = sorted(set(order) - expected_task_set)
        _fail(f"task_order must cover every task exactly once; missing={missing}, extra={extra}")
    if not isinstance(resource_assignments, Mapping):
        _fail("resource_assignments must be a task-to-resource mapping")
    if any(not isinstance(task_id, str) for task_id in resource_assignments):
        _fail("resource_assignments keys must be task ID strings")
    if set(resource_assignments) != expected_task_set:
        missing = sorted(expected_task_set - set(resource_assignments))
        extra = sorted(set(resource_assignments) - expected_task_set)
        _fail(
            "resource_assignments must cover every task exactly once; "
            f"missing={missing}, extra={extra}"
        )
    for task_id, resource_id in resource_assignments.items():
        if not isinstance(resource_id, str) or resource_id not in resource_ids:
            _fail(f"task {task_id!r} is assigned to unknown resource {resource_id!r}")

    resource_tiers = _resource_tiers(instance)
    parents_by_task: dict[str, list[str]] = defaultdict(list)
    dependency_bits: dict[str, int] = {}
    for dependency in instance["dependencies"]:
        parent = dependency["parent"]
        child = dependency["child"]
        parents_by_task[child].append(parent)
        dependency_bits[f"{parent}->{child}"] = _exact_int(
            dependency["data_bits"],
            label=f"data_bits for {parent!r}->{child!r}",
            minimum=0,
        )
    for parents in parents_by_task.values():
        parents.sort()

    scheduled: dict[str, dict[str, Any]] = {}
    intervals_by_resource: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task_id in order:
        unscheduled_parents = [
            parent for parent in parents_by_task[task_id] if parent not in scheduled
        ]
        if unscheduled_parents:
            _fail(
                f"task_order is not topological: task {task_id!r} precedes parent(s) "
                f"{', '.join(unscheduled_parents)}"
            )
        resource_id = resource_assignments[task_id]
        duration_us = _exact_int(
            instance["execution_time_us"][task_id][resource_id],
            label=f"execution_time_us[{task_id!r}][{resource_id!r}]",
            minimum=1,
        )
        ready_us = 0
        for parent in parents_by_task[task_id]:
            parent_assignment = scheduled[parent]
            edge_id = f"{parent}->{task_id}"
            try:
                communication = resource_route_metrics(
                    instance["network"],
                    resource_tiers,
                    source_resource_id=parent_assignment["resource_id"],
                    target_resource_id=resource_id,
                    data_bits=dependency_bits[edge_id],
                )
            except (KeyError, TypeError, ValueError) as exc:
                _fail(f"cannot derive communication metrics for {edge_id!r}: {exc}")
            transfer_time = _exact_int(
                communication["communication_time_us"],
                label=(
                    f"communication time for {edge_id!r} on "
                    f"{parent_assignment['resource_id']}|{resource_id}"
                ),
                minimum=0,
            )
            ready_us = max(ready_us, parent_assignment["end_us"] + transfer_time)
        start_us = _earliest_idle_slot(
            intervals_by_resource[resource_id],
            ready_us=ready_us,
            duration_us=duration_us,
        )
        assignment = {
            "task_id": task_id,
            "resource_id": resource_id,
            "start_us": start_us,
            "end_us": start_us + duration_us,
        }
        scheduled[task_id] = assignment
        intervals_by_resource[resource_id].append(assignment)

    assignments = [scheduled[task_id] for task_id in sorted(scheduled)]
    schedule = {
        "schedule_id": canonical_schedule_id(instance, assignments),
        "schedule_sha256": "0" * 64,
        "assignments": assignments,
        "makespan_us": max(assignment["end_us"] for assignment in assignments),
        "compute_cost_ncu": _matrix_total(
            instance, assignments, matrix_name="compute_cost_ncu"
        ),
        "compute_energy_nj": _matrix_total(
            instance, assignments, matrix_name="compute_energy_nj"
        ),
        "network_energy_pj": _dependency_metrics(instance, scheduled)[3],
    }
    schedule["schedule_sha256"] = content_sha256(
        schedule, checksum_field="schedule_sha256"
    )
    return evaluate_schedule(
        instance,
        schedule,
        deadline_us=deadline_us,
        budget_ncu=budget_ncu,
    )
