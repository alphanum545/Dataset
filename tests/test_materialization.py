from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from generator.canonical import canonical_json_bytes, content_sha256
from generator.config import load_config
from generator.dax import normalize_dax
from generator.instance import build_base_instance
from generator.materialize import (
    PilotMaterializationError,
    build_qos_instance,
    materialize_pilot_dataset,
    selected_base_instance_id,
)
from generator.schedule import build_schedule
from validation import (
    BenchmarkValidationError,
    validate_pilot_materialization_manifest,
    validate_qos_instance,
    validate_schedule,
)


ROOT = Path(__file__).resolve().parents[1]
DAX = '''<?xml version="1.0"?>
<adag xmlns="http://pegasus.isi.edu/schema/DAX" version="3.3" name="materialize-test">
  <job id="A" name="a" runtime="1">
    <uses file="ab.dat" link="output" size="1000" />
  </job>
  <job id="B" name="b" runtime="0.5">
    <uses file="ab.dat" link="input" size="1000" />
  </job>
  <child ref="B"><parent ref="A" /></child>
</adag>
'''


def _base() -> tuple[dict, dict]:
    config = load_config(ROOT / "config" / "benchmark-v1.yaml")
    workflow = normalize_dax(
        DAX,
        family="montage",
        target_task_count=2,
        replicate_id="r01",
    )
    instance = build_base_instance(
        workflow,
        config,
        scale="S01",
        scenario="balanced",
        seed=101,
    )
    return config, instance


def _calibration(instance: dict) -> dict:
    order = ["A", "B"]
    schedules = {
        "iot": build_schedule(
            instance,
            task_order=order,
            resource_assignments={"A": "iot-001", "B": "iot-001"},
        ).schedule,
        "fog": build_schedule(
            instance,
            task_order=order,
            resource_assignments={"A": "fog-001", "B": "fog-001"},
        ).schedule,
        "cloud": build_schedule(
            instance,
            task_order=order,
            resource_assignments={"A": "cloud-001", "B": "cloud-001"},
        ).schedule,
    }
    references = [
        {"scheduler_id": "deterministic_heft_ifc", "scheduler_version": "ifc_v1", "schedule": schedules["cloud"]},
        {"scheduler_id": "deterministic_peft_ifc", "scheduler_version": "ifc_v1", "schedule": schedules["cloud"]},
        {"scheduler_id": "deterministic_cpop_ifc", "scheduler_version": "ifc_v1", "schedule": schedules["fog"]},
        {"scheduler_id": "deterministic_cost_reference_ifc", "scheduler_version": "ifc_v1", "schedule": schedules["iot"]},
    ]
    moheft = {
        "scheduler_id": "deterministic_moheft",
        "scheduler_version": "ifc_v1",
        "k": 50,
        "candidate_schedules": [schedules["fog"]],
    }
    candidates = [
        *(item["schedule"] for item in references),
        *moheft["candidate_schedules"],
    ]
    fast = min(
        candidates,
        key=lambda item: (
            item["makespan_us"],
            item["compute_cost_ncu"],
            item["schedule_id"],
        ),
    )
    economical = min(
        candidates,
        key=lambda item: (
            item["compute_cost_ncu"],
            item["makespan_us"],
            item["schedule_id"],
        ),
    )
    return {
        "schema_version": 1,
        "base_instance_id": instance["metadata"]["base_instance_id"],
        "calibration_version": "ifc_calibration_v1",
        "lower_bounds": {"t_cp_lb_us": 1, "t_capacity_lb_us": 1, "t_lb_us": 1},
        "reference_schedulers": references,
        "moheft": moheft,
        "anchors": {
            "fast_schedule_id": fast["schedule_id"],
            "economical_schedule_id": economical["schedule_id"],
            "t_fast_us": fast["makespan_us"],
            "t_economical_us": economical["makespan_us"],
            "cost_fast_ncu": fast["compute_cost_ncu"],
            "cost_economical_ncu": economical["compute_cost_ncu"],
            "deadline_range_degenerate": fast["makespan_us"]
            == economical["makespan_us"],
        },
        "candidate_set_sha256": "a" * 64,
    }


def _selection_entry(
    instance: dict,
    *,
    profile: str,
    candidate_id: str,
    split: str = "development",
) -> dict:
    metadata = instance["metadata"]
    return {
        "family": metadata["family"],
        "target_task_count": metadata["target_task_count"],
        "replicate_id": metadata["source_replicate"],
        "source_sha256": metadata["source_sha256"],
        "source_path": "source/test.dax",
        "ifc_realization_seed": metadata["ifc_realization_seed"],
        "resource_scale": metadata["resource_scale"],
        "scenario_profile": metadata["scenario_profile"],
        "qos_profile": profile,
        "candidate_id": candidate_id,
        "split": split,
    }


def test_qos_materialization_uses_exact_deadline_budget_and_joint_witness():
    config, instance = _base()
    calibration = _calibration(instance)
    entry = _selection_entry(
        instance,
        profile="moderate",
        candidate_id="candidate-test-moderate",
    )

    qos = build_qos_instance(entry, calibration, config)
    validate_qos_instance(qos)
    evaluation = validate_schedule(
        instance,
        qos["joint_feasibility_witness"],
        deadline_us=qos["deadline"]["deadline_us"],
        budget_ncu=qos["budget"]["budget_ncu"],
    )

    gap = (
        calibration["anchors"]["t_economical_us"]
        - calibration["anchors"]["t_fast_us"]
    )
    assert qos["deadline"]["deadline_us"] == (
        calibration["anchors"]["t_fast_us"] + (gap + 1) // 2
    )
    assert qos["budget"]["cost_floor_ref_ncu"] == qos[
        "joint_feasibility_witness"
    ]["compute_cost_ncu"]
    assert qos["budget"]["budget_ncu"] >= qos["budget"]["cost_floor_ref_ncu"]
    assert evaluation.joint_feasible is True


def test_materializer_deduplicates_shared_base_calibration(monkeypatch, tmp_path):
    config, instance = _base()
    config = deepcopy(config)
    config["pilot_selection"]["selected_count"] = 2
    config["pilot_selection"]["split_counts"] = {"development": 1, "holdout": 1}
    source_root = tmp_path / "sources"
    source = source_root / "source" / "test.dax"
    source.parent.mkdir(parents=True)
    source.write_text(DAX, encoding="utf-8")
    source_sha = sha256(source.read_bytes()).hexdigest()
    source_manifest = {"entries": [{"sha256": source_sha}]}

    base_entry = _selection_entry(
        instance,
        profile="tight",
        candidate_id="candidate-a",
        split="development",
    )
    base_entry["source_sha256"] = source_sha
    holdout_entry = {
        **base_entry,
        "candidate_id": "candidate-b",
        "qos_profile": "relaxed",
        "split": "holdout",
    }
    selection = {
        "selection_id": "pilot-selection-test",
        "selected_count": 2,
        "configuration_sha256": sha256(canonical_json_bytes(config)).hexdigest(),
        "source_manifest_sha256": sha256(
            canonical_json_bytes(source_manifest)
        ).hexdigest(),
        "entries": [base_entry, holdout_entry],
        "content_sha256": "0" * 64,
    }
    selection["content_sha256"] = content_sha256(selection)
    calls = 0

    def fake_calibration(base: dict, *, k: int) -> dict:
        nonlocal calls
        calls += 1
        assert k == 50
        return _calibration(base)

    monkeypatch.setattr(
        "generator.materialize.build_calibration_result", fake_calibration
    )
    output = tmp_path / "pilot"
    manifest = materialize_pilot_dataset(
        config,
        source_manifest,
        selection,
        source_root=source_root,
        output_root=output,
        generator_commit_sha="1" * 40,
    )

    assert calls == 1
    assert manifest["base_instance_count"] == 1
    assert manifest["calibration_count"] == 1
    assert manifest["instance_count"] == 2
    assert (output / "instances" / "development" / "candidate-a.json").is_file()
    assert (output / "instances" / "holdout" / "candidate-b.json").is_file()


def _manifest_shell(config: dict, selection: dict) -> dict:
    selected = selection["entries"]
    base_ids = sorted(
        {selected_base_instance_id(entry, config) for entry in selected}
    )
    entries = []
    for item in selected:
        candidate_id = item["candidate_id"]
        entries.append(
            {
                "instance_id": candidate_id,
                "candidate_id": candidate_id,
                "base_instance_id": selected_base_instance_id(item, config),
                "split": item["split"],
                "path": f"instances/{item['split']}/{candidate_id}.json",
                "sha256": "1" * 64,
                "family": item["family"],
                "target_task_count": item["target_task_count"],
                "replicate_id": item["replicate_id"],
                "source_sha256": item["source_sha256"],
                "resource_scale": item["resource_scale"],
                "scenario_profile": item["scenario_profile"],
                "qos_profile": item["qos_profile"],
                "ifc_realization_seed": item["ifc_realization_seed"],
            }
        )
    entries.sort(key=lambda item: (item["split"], item["candidate_id"]))
    manifest = {
        "schema_version": 1,
        "materialization_version": "pilot_materialization_v1",
        "selection_id": selection["selection_id"],
        "selection_sha256": selection["content_sha256"],
        "dataset_version": config["dataset"]["version"],
        "generator_commit_sha": "2" * 40,
        "configuration_sha256": selection["configuration_sha256"],
        "source_manifest_sha256": selection["source_manifest_sha256"],
        "base_instance_count": len(base_ids),
        "calibration_count": len(base_ids),
        "instance_count": len(entries),
        "split_counts": selection["split_counts"],
        "dimensions": {
            "families": sorted({item["family"] for item in selected}),
            "task_counts": sorted({item["target_task_count"] for item in selected}),
            "replicates": sorted({item["replicate_id"] for item in selected}),
            "resource_scales": sorted({item["resource_scale"] for item in selected}),
            "scenario_profiles": sorted(
                {item["scenario_profile"] for item in selected}
            ),
            "qos_profiles": sorted({item["qos_profile"] for item in selected}),
        },
        "base_entries": [
            {
                "base_instance_id": base_id,
                "path": f"base/{base_id}.json",
                "sha256": "3" * 64,
            }
            for base_id in base_ids
        ],
        "calibration_entries": [
            {
                "base_instance_id": base_id,
                "path": f"calibration/{base_id}.json",
                "sha256": "4" * 64,
                "candidate_set_sha256": "5" * 64,
            }
            for base_id in base_ids
        ],
        "entries": entries,
        "content_sha256": "0" * 64,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    return manifest


def test_manifest_only_validation_matches_frozen_200_selection():
    config = load_config(ROOT / "config" / "benchmark-v1.yaml")
    source_manifest = json.loads(
        (ROOT / "manifests" / "source-workflows-v1.json").read_text(
            encoding="utf-8"
        )
    )
    selection = json.loads(
        (ROOT / "manifests" / "pilot-selection-v1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = _manifest_shell(config, selection)

    validate_pilot_materialization_manifest(
        manifest,
        config=config,
        source_manifest=source_manifest,
        selection_manifest=selection,
    )

    tampered = deepcopy(manifest)
    tampered["entries"][0]["split"] = "holdout"
    tampered["content_sha256"] = content_sha256(tampered)
    with pytest.raises(BenchmarkValidationError, match="split"):
        validate_pilot_materialization_manifest(
            tampered,
            config=config,
            source_manifest=source_manifest,
            selection_manifest=selection,
        )


def test_materializer_rejects_nonempty_output_root(tmp_path):
    config, instance = _base()
    config = deepcopy(config)
    config["pilot_selection"]["selected_count"] = 1
    config["pilot_selection"]["split_counts"] = {"development": 1}
    source_manifest = {}
    selection = {
        "selection_id": "pilot-selection-test",
        "selected_count": 1,
        "configuration_sha256": sha256(canonical_json_bytes(config)).hexdigest(),
        "source_manifest_sha256": sha256(
            canonical_json_bytes(source_manifest)
        ).hexdigest(),
        "entries": [
            _selection_entry(
                instance,
                profile="tight",
                candidate_id="candidate-a",
            )
        ],
        "content_sha256": "0" * 64,
    }
    selection["content_sha256"] = content_sha256(selection)
    output = tmp_path / "pilot"
    output.mkdir()
    (output / "stale.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(PilotMaterializationError, match="missing or empty"):
        materialize_pilot_dataset(
            config,
            source_manifest,
            selection,
            source_root=tmp_path,
            output_root=output,
            generator_commit_sha="1" * 40,
        )
