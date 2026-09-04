from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from generator.config import load_config
from generator.canonical import content_sha256
from generator.dax import normalize_dax
from generator.instance import build_base_instance
from validation import (
    BenchmarkValidationError,
    SchemaValidationError,
    validate_base_instance,
    validate_calibration_result,
    validate_dataset_manifest,
    validate_normalized_workflow,
    validate_qos_instance,
    validate_source_manifest,
)
from validation.cli import main as validation_main


ROOT = Path(__file__).resolve().parents[1]
DAX = '''<?xml version="1.0"?>
<adag xmlns="http://pegasus.isi.edu/schema/DAX" version="3.3" name="tiny">
  <job id="A" name="a" runtime="1.25">
    <uses file="x.dat" link="output" size="1000" />
  </job>
  <job id="B" name="b" runtime="2.5">
    <uses file="x.dat" link="input" size="1000" />
  </job>
  <child ref="B"><parent ref="A" /></child>
</adag>
'''


def _workflow() -> dict:
    return normalize_dax(DAX, family="montage", target_task_count=2, replicate_id="r01")


def _base_instance() -> dict:
    return build_base_instance(
        _workflow(),
        load_config(ROOT / "config" / "benchmark-v1.yaml"),
        scale="S01",
        scenario="balanced",
        seed=101,
    )


def _schedule(identifier: str, *, makespan: int, cost: int) -> dict:
    schedule = {
        "schedule_id": identifier,
        "schedule_sha256": "0" * 64,
        "assignments": [
            {"task_id": "A", "resource_id": "iot-001", "start_us": 0, "end_us": makespan}
        ],
        "makespan_us": makespan,
        "compute_cost_ncu": cost,
        "compute_energy_nj": 100,
        "network_energy_pj": 0,
    }
    schedule["schedule_sha256"] = content_sha256(
        schedule, checksum_field="schedule_sha256"
    )
    return schedule


def test_normalized_workflow_schema_and_semantics_accept_generator_output():
    validate_normalized_workflow(_workflow())


def test_normalized_workflow_rejects_duplicate_tasks_and_cycles():
    duplicate = _workflow()
    duplicate["tasks"].append(deepcopy(duplicate["tasks"][0]))
    duplicate["metadata"]["actual_task_count"] += 1
    duplicate["metadata"]["target_task_count"] += 1
    with pytest.raises(BenchmarkValidationError, match="task IDs must be unique"):
        validate_normalized_workflow(duplicate)

    cyclic = _workflow()
    reverse = deepcopy(cyclic["dependencies"][0])
    reverse["parent"], reverse["child"] = reverse["child"], reverse["parent"]
    cyclic["dependencies"].append(reverse)
    with pytest.raises(BenchmarkValidationError, match="contains a cycle"):
        validate_normalized_workflow(cyclic)


def test_normalized_workflow_rejects_inconsistent_exact_values_and_identity():
    workflow = _workflow()
    workflow["dependencies"][0]["data_bits"] += 1
    with pytest.raises(BenchmarkValidationError, match="data_bits is inconsistent"):
        validate_normalized_workflow(workflow)

    workflow = _workflow()
    workflow["metadata"]["workflow_id"] = "wf-wrong"
    with pytest.raises(BenchmarkValidationError, match="workflow_id"):
        validate_normalized_workflow(workflow)


def test_base_instance_recomputes_every_materialized_matrix():
    instance = _base_instance()
    validate_base_instance(instance)

    instance["compute_cost_ncu"]["A"]["fog-001"] += 1
    with pytest.raises(BenchmarkValidationError, match="compute_cost_ncu"):
        validate_base_instance(instance)

    instance = _base_instance()
    instance["metadata"]["base_instance_id"] = "base-wrong"
    with pytest.raises(BenchmarkValidationError, match="base_instance_id"):
        validate_base_instance(instance)


def test_base_instance_rejects_incomplete_and_incorrect_routes():
    instance = _base_instance()
    del instance["execution_time_us"]["A"]["iot-001"]
    with pytest.raises(BenchmarkValidationError, match="resource keys do not exactly match"):
        validate_base_instance(instance)

    instance = _base_instance()
    instance["communication"]["A->B"]["iot-001|iot-001"]["communication_time_us"] = 1
    with pytest.raises(BenchmarkValidationError, match="communication.*is inconsistent"):
        validate_base_instance(instance)

    instance = _base_instance()
    instance["content_sha256"] = "0" * 64
    with pytest.raises(BenchmarkValidationError, match="content_sha256"):
        validate_base_instance(instance)


def test_schema_rejects_binary_float_in_authoritative_cost_field():
    instance = _base_instance()
    instance["compute_cost_ncu"]["A"]["iot-001"] = 0.0
    with pytest.raises(SchemaValidationError, match="is not of type 'integer'"):
        validate_base_instance(instance)


def test_frozen_source_manifest_has_complete_valid_semantics():
    manifest = json.loads(
        (ROOT / "manifests" / "source-workflows-v1.json").read_text(encoding="utf-8")
    )
    validate_source_manifest(manifest)


def test_source_manifest_can_verify_artifact_checksum(tmp_path):
    full = json.loads((ROOT / "manifests" / "source-workflows-v1.json").read_text(encoding="utf-8"))
    manifest = {**full, "artifact_count": 1, "entries": [deepcopy(full["entries"][0])]}
    target = tmp_path / manifest["entries"][0]["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not-the-frozen-dax")
    with pytest.raises(BenchmarkValidationError, match="checksum mismatch"):
        validate_source_manifest(manifest, source_root=tmp_path, require_complete=False)


def test_source_manifest_cli_reports_validation_failure(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"artifact_count":0}', encoding="utf-8")
    result = validation_main(
        [
            "source-manifest",
            "--manifest",
            str(manifest_path),
            "--source-root",
            str(tmp_path),
            "--allow-partial",
        ]
    )
    assert result == 1
    assert "validation failed:" in capsys.readouterr().err


def test_calibration_schema_and_lower_bound_semantics():
    result = {
        "schema_version": 1,
        "base_instance_id": "base-example",
        "calibration_version": "v1",
        "lower_bounds": {"t_cp_lb_us": 10, "t_capacity_lb_us": 8, "t_lb_us": 10},
        "heft": {
            "scheduler_id": "deterministic_heft",
            "scheduler_version": "v1",
            "schedule": _schedule("heft", makespan=12, cost=100),
        },
        "cheapest_resource_assignment": {
            "scheduler_id": "deterministic_cheapest_resource",
            "scheduler_version": "v1",
            "schedule": _schedule("cheapest", makespan=20, cost=40),
        },
        "moheft": {
            "scheduler_id": "deterministic_moheft",
            "scheduler_version": "v1",
            "k": 50,
            "candidate_schedules": [_schedule("moheft-01", makespan=14, cost=60)],
        },
        "candidate_set_sha256": "d" * 64,
    }
    validate_calibration_result(result)
    result["lower_bounds"]["t_lb_us"] = 9
    with pytest.raises(BenchmarkValidationError, match="must equal max"):
        validate_calibration_result(result)


def test_qos_instance_reconstructs_deadline_budget_and_joint_witness():
    witness = _schedule("witness", makespan=14, cost=40)
    instance = {
        "schema_version": 1,
        "instance_id": "instance-tight",
        "base_instance_id": "base-example",
        "profile": "tight",
        "source_sha256": "f" * 64,
        "resource_scale": "S01",
        "scenario_profile": "balanced",
        "ifc_realization_seed": 101,
        "deadline": {
            "t_ref_us": 12,
            "factor_numerator": 5,
            "factor_denominator": 4,
            "deadline_us": 15,
        },
        "budget": {
            "cost_time_ncu": 100,
            "cost_floor_ref_ncu": 40,
            "budget_gap_ncu": 6,
            "factor_numerator": 1,
            "factor_denominator": 10,
            "budget_ncu": 46,
            "budget_range_degenerate": False,
        },
        "calibration": {
            "heft_scheduler_version": "v1",
            "cheapest_scheduler_version": "v1",
            "moheft_scheduler_version": "v1",
            "moheft_k": 50,
            "candidate_set_sha256": "1" * 64,
        },
        "joint_feasibility_witness": witness,
        "content_sha256": "2" * 64,
    }
    instance["content_sha256"] = content_sha256(instance)
    validate_qos_instance(instance)

    instance["budget"]["budget_ncu"] = 47
    with pytest.raises(BenchmarkValidationError, match="does not reconstruct"):
        validate_qos_instance(instance)


def test_dataset_manifest_validates_counts_uniqueness_and_file_checksum(tmp_path):
    instance_path = tmp_path / "instances" / "one.json"
    instance_path.parent.mkdir()
    instance_path.write_text("{}\n", encoding="utf-8")
    digest = sha256(instance_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "dataset_version": "v1-draft",
        "generator_commit_sha": "a" * 40,
        "configuration_sha256": "b" * 64,
        "source_manifest_sha256": "c" * 64,
        "instance_count": 1,
        "dimensions": {
            "families": ["montage"],
            "task_counts": [60],
            "replicates": ["r01"],
            "resource_scales": ["S01"],
            "scenario_profiles": ["balanced"],
            "qos_profiles": ["tight"],
        },
        "entries": [
            {
                "instance_id": "instance-one",
                "path": "instances/one.json",
                "sha256": digest,
                "family": "montage",
                "target_task_count": 60,
                "replicate_id": "r01",
                "source_sha256": "d" * 64,
                "resource_scale": "S01",
                "scenario_profile": "balanced",
                "qos_profile": "tight",
                "validation_status": "passed",
            }
        ],
    }
    validate_dataset_manifest(manifest, dataset_root=tmp_path)

    manifest["instance_count"] = 2
    with pytest.raises(BenchmarkValidationError, match="instance_count"):
        validate_dataset_manifest(manifest)

    manifest["instance_count"] = 1
    manifest["entries"][0]["path"] = "../one.json"
    with pytest.raises(BenchmarkValidationError, match="relative canonical POSIX path"):
        validate_dataset_manifest(manifest)
