from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from pathlib import Path

import pytest

from generator.canonical import content_sha256
from generator.config import load_config
from generator.dax import normalize_dax
from generator.exact import ceil_div
from generator.instance import build_base_instance
from generator.network import resource_route_metrics
from generator.schedule import (
    ScheduleEvaluationError,
    build_schedule,
    canonical_schedule_id,
    evaluate_schedule,
)
from validation import BenchmarkValidationError, validate_base_instance, validate_schedule


ROOT = Path(__file__).resolve().parents[1]


def _dax(jobs: str, dependencies: str = "") -> str:
    return f'''<?xml version="1.0"?>
<adag xmlns="http://pegasus.isi.edu/schema/DAX" version="3.3" name="schedule-test">
{jobs}
{dependencies}
</adag>
'''


def _base_instance(source: str, *, task_count: int) -> dict:
    workflow = normalize_dax(
        source,
        family="montage",
        target_task_count=task_count,
        replicate_id="r01",
    )
    return build_base_instance(
        workflow,
        load_config(ROOT / "config" / "benchmark-v1.yaml"),
        scale="S01",
        scenario="balanced",
        seed=101,
    )


def _chain_instance() -> dict:
    return _base_instance(
        _dax(
            '''  <job id="A" name="a" runtime="1">
    <uses file="ab.dat" link="output" size="1000" />
  </job>
  <job id="B" name="b" runtime="0.1">
    <uses file="ab.dat" link="input" size="1000" />
  </job>
  <job id="C" name="c" runtime="0.1" />''',
            '  <child ref="B"><parent ref="A" /></child>',
        ),
        task_count=3,
    )


def _join_instance() -> dict:
    return _base_instance(
        _dax(
            '''  <job id="A" name="a" runtime="1">
    <uses file="ac.dat" link="output" size="1000" />
  </job>
  <job id="B" name="b" runtime="0.5">
    <uses file="bc.dat" link="output" size="100000" />
  </job>
  <job id="C" name="c" runtime="0.2">
    <uses file="ac.dat" link="input" size="1000" />
    <uses file="bc.dat" link="input" size="100000" />
  </job>''',
            '''  <child ref="C"><parent ref="A" /></child>
  <child ref="C"><parent ref="B" /></child>''',
        ),
        task_count=3,
    )


def _assignment(schedule: dict, task_id: str) -> dict:
    return next(item for item in schedule["assignments"] if item["task_id"] == task_id)


def _communication(instance: dict, edge_id: str, source: str, target: str) -> dict[str, int]:
    parent, child = edge_id.split("->", 1)
    dependency = next(
        item
        for item in instance["dependencies"]
        if item["parent"] == parent and item["child"] == child
    )
    resource_tiers = {
        resource["resource_id"]: resource["tier"] for resource in instance["resources"]
    }
    return resource_route_metrics(
        instance["network"],
        resource_tiers,
        source_resource_id=source,
        target_resource_id=target,
        data_bits=dependency["data_bits"],
    )


def _resign(instance: dict, schedule: dict) -> None:
    schedule["schedule_id"] = canonical_schedule_id(instance, schedule["assignments"])
    schedule["schedule_sha256"] = content_sha256(
        schedule, checksum_field="schedule_sha256"
    )


def _canonical_topological_order(instance: dict) -> list[str]:
    task_ids = [task["task_id"] for task in instance["tasks"]]
    indegree = {task_id: 0 for task_id in task_ids}
    children: dict[str, list[str]] = defaultdict(list)
    for dependency in instance["dependencies"]:
        children[dependency["parent"]].append(dependency["child"])
        indegree[dependency["child"]] += 1
    ready = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
    order = []
    while ready:
        task_id = ready.popleft()
        order.append(task_id)
        for child in sorted(children[task_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return order


def test_same_resource_dependencies_have_zero_communication():
    instance = _chain_instance()
    evaluation = build_schedule(
        instance,
        task_order=["A", "B", "C"],
        resource_assignments={"A": "iot-001", "B": "iot-001", "C": "fog-001"},
    )
    first = _assignment(evaluation.schedule, "A")
    second = _assignment(evaluation.schedule, "B")

    assert second["start_us"] == first["end_us"]
    assert evaluation.dependency_arrival_us["A->B"] == first["end_us"]
    assert evaluation.communication_time_us == 0
    assert evaluation.schedule["network_energy_pj"] == 0


def test_same_tier_different_resources_use_the_derived_route():
    instance = _chain_instance()
    evaluation = build_schedule(
        instance,
        task_order=["A", "B", "C"],
        resource_assignments={"A": "iot-001", "B": "iot-002", "C": "fog-001"},
    )
    parent = _assignment(evaluation.schedule, "A")
    expected = _communication(instance, "A->B", "iot-001", "iot-002")

    assert "communication" not in instance
    assert expected["communication_time_us"] > 0
    assert evaluation.dependency_arrival_us["A->B"] == (
        parent["end_us"] + expected["communication_time_us"]
    )
    assert evaluation.schedule["network_energy_pj"] == expected[
        "communication_energy_pj"
    ]


def test_latest_parent_arrival_controls_join_start_across_tiers():
    instance = _join_instance()
    evaluation = build_schedule(
        instance,
        task_order=["A", "B", "C"],
        resource_assignments={"A": "iot-001", "B": "cloud-001", "C": "fog-001"},
    )
    child = _assignment(evaluation.schedule, "C")
    arrivals = {
        edge: evaluation.dependency_arrival_us[edge]
        for edge in ("A->C", "B->C")
    }
    expected = [
        _communication(instance, "A->C", "iot-001", "fog-001"),
        _communication(instance, "B->C", "cloud-001", "fog-001"),
    ]

    assert child["start_us"] == max(arrivals.values())
    assert evaluation.task_dependency_ready_us["C"] == max(arrivals.values())
    assert evaluation.communication_time_us == sum(
        item["communication_time_us"] for item in expected
    )
    assert evaluation.schedule["network_energy_pj"] == sum(
        item["communication_energy_pj"] for item in expected
    )


def test_serial_contention_uses_half_open_intervals_and_fills_idle_gaps():
    instance = _chain_instance()
    evaluation = build_schedule(
        instance,
        task_order=["A", "B", "C"],
        resource_assignments={"A": "iot-001", "B": "cloud-001", "C": "cloud-001"},
    )
    delayed = _assignment(evaluation.schedule, "B")
    gap_filler = _assignment(evaluation.schedule, "C")

    assert gap_filler["start_us"] == 0
    assert gap_filler["end_us"] <= delayed["start_us"]
    validate_schedule(instance, evaluation.schedule)


def test_exact_totals_constraints_and_deterministic_identity():
    instance = _join_instance()
    mapping = {"A": "cloud-001", "B": "fog-002", "C": "iot-002"}
    first = build_schedule(instance, task_order=["A", "B", "C"], resource_assignments=mapping)
    second = build_schedule(instance, task_order=["A", "B", "C"], resource_assignments=mapping)

    assert first == second
    assert first.schedule["compute_cost_ncu"] == sum(
        instance["compute_cost_ncu"][task_id][resource_id]
        for task_id, resource_id in mapping.items()
    )
    assert isinstance(first.schedule["compute_cost_ncu"], int)
    assert first.schedule["compute_energy_nj"] == sum(
        instance["compute_energy_nj"][task_id][resource_id]
        for task_id, resource_id in mapping.items()
    )

    constrained = evaluate_schedule(
        instance,
        first.schedule,
        deadline_us=first.schedule["makespan_us"],
        budget_ncu=first.schedule["compute_cost_ncu"] - 1,
    )
    assert constrained.deadline_feasible is True
    assert constrained.budget_feasible is False
    assert constrained.joint_feasible is False


def test_compute_cost_uses_exact_per_task_ceiling_before_sum():
    instance = _chain_instance()
    cloud = next(
        resource for resource in instance["resources"] if resource["resource_id"] == "cloud-001"
    )
    cloud["price_ncu_per_second"] = 1
    for task in instance["tasks"]:
        task_id = task["task_id"]
        duration = instance["execution_time_us"][task_id]["cloud-001"]
        instance["compute_cost_ncu"][task_id]["cloud-001"] = ceil_div(
            duration, 1_000_000
        )
    instance["content_sha256"] = content_sha256(instance)
    validate_base_instance(instance)

    evaluation = build_schedule(
        instance,
        task_order=["A", "B", "C"],
        resource_assignments={
            "A": "cloud-001",
            "B": "cloud-001",
            "C": "cloud-001",
        },
    )

    assert evaluation.schedule["compute_cost_ncu"] == 3


def test_builder_rejects_incomplete_unknown_and_nontopological_inputs():
    instance = _chain_instance()
    with pytest.raises(ScheduleEvaluationError, match="resource_assignments must cover"):
        build_schedule(
            instance,
            task_order=["A", "B", "C"],
            resource_assignments={"A": "iot-001", "B": "iot-001"},
        )
    with pytest.raises(ScheduleEvaluationError, match="unknown resource"):
        build_schedule(
            instance,
            task_order=["A", "B", "C"],
            resource_assignments={"A": "edge-999", "B": "iot-001", "C": "iot-001"},
        )
    with pytest.raises(ScheduleEvaluationError, match="not topological"):
        build_schedule(
            instance,
            task_order=["B", "A", "C"],
            resource_assignments={"A": "iot-001", "B": "iot-001", "C": "iot-001"},
        )
    with pytest.raises(ScheduleEvaluationError, match="exact integer"):
        build_schedule(
            instance,
            task_order=["A", "B", "C"],
            resource_assignments={"A": "iot-001", "B": "iot-001", "C": "iot-001"},
            budget_ncu=1.0,
        )


def test_explicit_evaluator_rejects_overlap_and_precedence_violations():
    independent = _base_instance(
        _dax(
            '''  <job id="A" name="a" runtime="0.1" />
  <job id="B" name="b" runtime="0.1" />'''
        ),
        task_count=2,
    )
    schedule = deepcopy(
        build_schedule(
            independent,
            task_order=["A", "B"],
            resource_assignments={"A": "fog-001", "B": "fog-001"},
        ).schedule
    )
    second = _assignment(schedule, "B")
    duration = second["end_us"] - second["start_us"]
    second["start_us"] = 0
    second["end_us"] = duration
    schedule["makespan_us"] = max(item["end_us"] for item in schedule["assignments"])
    _resign(independent, schedule)
    with pytest.raises(ScheduleEvaluationError, match="overlapping tasks"):
        evaluate_schedule(independent, schedule)

    chain = _chain_instance()
    schedule = deepcopy(
        build_schedule(
            chain,
            task_order=["A", "B", "C"],
            resource_assignments={"A": "iot-001", "B": "cloud-001", "C": "fog-001"},
        ).schedule
    )
    parent = _assignment(schedule, "A")
    child = _assignment(schedule, "B")
    duration = child["end_us"] - child["start_us"]
    child["start_us"] = parent["end_us"]
    child["end_us"] = child["start_us"] + duration
    schedule["makespan_us"] = max(item["end_us"] for item in schedule["assignments"])
    _resign(chain, schedule)
    with pytest.raises(ScheduleEvaluationError, match="starts before dependency"):
        evaluate_schedule(chain, schedule)


def test_validator_rejects_tampered_totals_identity_and_checksum():
    instance = _chain_instance()
    original = build_schedule(
        instance,
        task_order=["A", "B", "C"],
        resource_assignments={"A": "iot-001", "B": "cloud-001", "C": "fog-001"},
    ).schedule

    tampered_total = deepcopy(original)
    tampered_total["compute_cost_ncu"] += 1
    tampered_total["schedule_sha256"] = content_sha256(
        tampered_total, checksum_field="schedule_sha256"
    )
    with pytest.raises(BenchmarkValidationError, match="compute_cost_ncu"):
        validate_schedule(instance, tampered_total)

    tampered_id = deepcopy(original)
    tampered_id["schedule_id"] = "schedule-wrong"
    tampered_id["schedule_sha256"] = content_sha256(
        tampered_id, checksum_field="schedule_sha256"
    )
    with pytest.raises(BenchmarkValidationError, match="schedule_id"):
        validate_schedule(instance, tampered_id)

    tampered_checksum = deepcopy(original)
    tampered_checksum["schedule_sha256"] = "0" * 64
    with pytest.raises(BenchmarkValidationError, match="schedule_sha256"):
        validate_schedule(instance, tampered_checksum)

    missing_assignment = deepcopy(original)
    missing_assignment["assignments"] = missing_assignment["assignments"][:-1]
    _resign(instance, missing_assignment)
    with pytest.raises(BenchmarkValidationError, match="do not cover every task"):
        validate_schedule(instance, missing_assignment)


def test_frozen_montage_60_builds_and_validates_on_real_data():
    source = ROOT / (
        "source_workflows/pegasus-bharathi-bb1f8d43/montage/0060/r01.dax"
    )
    workflow = normalize_dax(
        source,
        family="montage",
        target_task_count=60,
        replicate_id="r01",
    )
    instance = build_base_instance(
        workflow,
        load_config(ROOT / "config" / "benchmark-v1.yaml"),
        scale="S01",
        scenario="balanced",
        seed=101,
    )
    order = _canonical_topological_order(instance)
    mapping = {task_id: "fog-001" for task_id in order}

    evaluation = build_schedule(
        instance,
        task_order=order,
        resource_assignments=mapping,
    )
    validated = validate_schedule(instance, evaluation.schedule)

    assert "communication" not in instance
    assert len(evaluation.schedule["assignments"]) == 60
    assert validated.schedule == evaluation.schedule
    assert evaluation.schedule["network_energy_pj"] == 0
