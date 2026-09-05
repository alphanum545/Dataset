from __future__ import annotations

import json
from pathlib import Path

from generator.config import load_config
from generator.dax import normalize_dax
from generator.instance import build_base_instance
from generator.reference_schedulers import (
    REFERENCE_SCHEDULER_IDS,
    build_calibration_result,
    calibration_candidate_set_sha256,
    calibration_lower_bounds,
    schedule_cpop_ifc,
    schedule_cost_reference_ifc,
    schedule_heft_ifc,
    schedule_moheft_ifc,
    schedule_peft_ifc,
)
from generator.cli import main as generator_main
from validation import validate_calibration_result, validate_schedule
from validation.cli import main as validation_main


ROOT = Path(__file__).resolve().parents[1]
DAX = '''<?xml version="1.0"?>
<adag xmlns="http://pegasus.isi.edu/schema/DAX" version="3.3" name="reference-schedulers">
  <job id="A" name="a" runtime="2.0">
    <uses file="ab.dat" link="output" size="1000" />
    <uses file="ac.dat" link="output" size="50000" />
  </job>
  <job id="B" name="b" runtime="1.5">
    <uses file="ab.dat" link="input" size="1000" />
    <uses file="bd.dat" link="output" size="200000" />
  </job>
  <job id="C" name="c" runtime="0.6">
    <uses file="ac.dat" link="input" size="50000" />
    <uses file="cd.dat" link="output" size="3000" />
  </job>
  <job id="D" name="d" runtime="1.2">
    <uses file="bd.dat" link="input" size="200000" />
    <uses file="cd.dat" link="input" size="3000" />
    <uses file="de.dat" link="output" size="10000" />
  </job>
  <job id="E" name="e" runtime="0.8">
    <uses file="de.dat" link="input" size="10000" />
  </job>
  <child ref="B"><parent ref="A" /></child>
  <child ref="C"><parent ref="A" /></child>
  <child ref="D"><parent ref="B" /></child>
  <child ref="D"><parent ref="C" /></child>
  <child ref="E"><parent ref="D" /></child>
</adag>
'''


def _base_instance() -> dict:
    workflow = normalize_dax(
        DAX,
        family="montage",
        target_task_count=5,
        replicate_id="r01",
    )
    return build_base_instance(
        workflow,
        load_config(ROOT / "config" / "benchmark-v1.yaml"),
        scale="S01",
        scenario="balanced",
        seed=101,
    )


def _calibration_schedules(result: dict) -> list[dict]:
    return [
        *(reference["schedule"] for reference in result["reference_schedulers"]),
        *result["moheft"]["candidate_schedules"],
    ]


def test_reference_portfolio_is_deterministic_and_authoritatively_valid():
    instance = _base_instance()
    schedulers = (
        schedule_heft_ifc,
        schedule_peft_ifc,
        schedule_cpop_ifc,
        schedule_cost_reference_ifc,
    )

    for scheduler in schedulers:
        first = scheduler(instance)
        second = scheduler(instance)
        assert first.schedule == second.schedule
        assert len(first.schedule["assignments"]) == 5
        assert validate_schedule(instance, first.schedule).schedule == first.schedule


def test_cost_reference_reaches_global_additive_compute_cost_minimum():
    instance = _base_instance()
    result = schedule_cost_reference_ifc(instance)
    expected = sum(min(row.values()) for row in instance["compute_cost_ncu"].values())

    assert result.schedule["compute_cost_ncu"] == expected


def test_moheft_is_deterministic_unique_and_preserves_the_economical_boundary():
    instance = _base_instance()
    first = schedule_moheft_ifc(instance, k=12)
    second = schedule_moheft_ifc(instance, k=12)

    assert [item.schedule for item in first] == [item.schedule for item in second]
    assert 1 <= len(first) <= 12
    assert len({item.schedule["schedule_id"] for item in first}) == len(first)
    for evaluation in first:
        validate_schedule(instance, evaluation.schedule)

    economical = schedule_cost_reference_ifc(instance).schedule["compute_cost_ncu"]
    assert min(item.schedule["compute_cost_ncu"] for item in first) == economical


def test_calibration_result_has_frozen_portfolio_valid_anchors_and_lower_bounds():
    instance = _base_instance()
    result = build_calibration_result(instance)
    validate_calibration_result(result)

    assert {item["scheduler_id"] for item in result["reference_schedulers"]} == set(
        REFERENCE_SCHEDULER_IDS
    )
    assert result["moheft"]["k"] == 50
    schedules = _calibration_schedules(result)
    reference_ids = {
        item["schedule"]["schedule_id"] for item in result["reference_schedulers"]
    }
    moheft_ids = [
        schedule["schedule_id"] for schedule in result["moheft"]["candidate_schedules"]
    ]
    assert len(moheft_ids) == len(set(moheft_ids))
    assert reference_ids.isdisjoint(moheft_ids)
    for schedule in schedules:
        validate_schedule(instance, schedule)

    expected_checksum = calibration_candidate_set_sha256(
        result["reference_schedulers"], result["moheft"]
    )
    assert result["candidate_set_sha256"] == expected_checksum

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
    assert result["anchors"]["fast_schedule_id"] == fast["schedule_id"]
    assert result["anchors"]["economical_schedule_id"] == economical["schedule_id"]

    lower = calibration_lower_bounds(instance)
    assert result["lower_bounds"] == lower
    assert lower["t_lb_us"] <= min(schedule["makespan_us"] for schedule in schedules)


def test_calibration_generator_and_validator_clis_round_trip(tmp_path, capsys):
    instance_path = tmp_path / "base.json"
    result_path = tmp_path / "calibration.json"
    instance_path.write_text(
        json.dumps(_base_instance(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    generated = generator_main(
        [
            "calibrate-instance",
            "--config",
            str(ROOT / "config" / "benchmark-v1.yaml"),
            "--base-instance",
            str(instance_path),
            "--output",
            str(result_path),
        ]
    )
    assert generated == 0

    validated = validation_main(
        [
            "calibration-result",
            "--result",
            str(result_path),
            "--base-instance",
            str(instance_path),
        ]
    )
    assert validated == 0
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "passed"
    assert response["candidate_count"] >= 5
