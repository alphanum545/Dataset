from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from generator.canonical import canonical_json_bytes, content_sha256
from generator.dax import normalize_dax
from generator.instance import build_base_instance
from generator.materialize import (
    PILOT_MATERIALIZATION_VERSION,
    build_qos_instance,
    selected_base_instance_id,
)

from .calibration import validate_calibration_result_against_instance
from .errors import BenchmarkValidationError
from .schema import validate_schema
from .semantic import (
    validate_base_instance,
    validate_pilot_selection,
    validate_qos_instance,
    validate_schedule,
)


def _fail(message: str) -> None:
    raise BenchmarkValidationError(message)


def _relative_path(root: Path, value: str, *, label: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or "\\" in value:
        _fail(f"{label} must be a relative canonical POSIX path")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*posix.parts)).resolve()
    if resolved_root not in resolved.parents:
        _fail(f"{label} escapes its root: {value!r}")
    return resolved


def _read_verified_json(
    root: Path, value: str, expected_sha: str, *, label: str
) -> dict[str, Any]:
    path = _relative_path(root, value, label=label)
    try:
        data = path.read_bytes()
    except OSError as exc:
        _fail(f"cannot read {label} {value!r}: {exc}")
    if sha256(data).hexdigest() != expected_sha:
        _fail(f"{label} checksum mismatch for {value!r}")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not valid UTF-8 JSON: {value!r}: {exc}")
    if not isinstance(payload, dict):
        _fail(f"{label} must contain a JSON object: {value!r}")
    return payload


def _dimension_summary(entries: list[Mapping[str, Any]]) -> dict[str, list[Any]]:
    return {
        "families": sorted({str(entry["family"]) for entry in entries}),
        "task_counts": sorted({int(entry["target_task_count"]) for entry in entries}),
        "replicates": sorted({str(entry["replicate_id"]) for entry in entries}),
        "resource_scales": sorted({str(entry["resource_scale"]) for entry in entries}),
        "scenario_profiles": sorted({str(entry["scenario_profile"]) for entry in entries}),
        "qos_profiles": sorted({str(entry["qos_profile"]) for entry in entries}),
    }


def validate_pilot_materialization_manifest(
    manifest: dict[str, Any],
    *,
    config: dict[str, Any],
    source_manifest: dict[str, Any],
    selection_manifest: dict[str, Any],
    dataset_root: str | Path | None = None,
    source_root: str | Path | None = None,
) -> None:
    """Validate pilot provenance and, when roots are supplied, every materialized artifact."""
    validate_schema(manifest, "pilot-materialization")
    validate_pilot_selection(
        selection_manifest,
        config=config,
        source_manifest=source_manifest,
    )
    if manifest["materialization_version"] != PILOT_MATERIALIZATION_VERSION:
        _fail("pilot materialization version is not the frozen v1 version")
    if manifest["selection_id"] != selection_manifest["selection_id"]:
        _fail("pilot materialization selection_id does not match the frozen selection")
    if manifest["selection_sha256"] != selection_manifest["content_sha256"]:
        _fail("pilot materialization selection checksum does not match the frozen selection")
    config_sha = sha256(canonical_json_bytes(config)).hexdigest()
    source_sha = sha256(canonical_json_bytes(source_manifest)).hexdigest()
    if manifest["configuration_sha256"] != config_sha:
        _fail("pilot materialization configuration checksum is inconsistent")
    if manifest["source_manifest_sha256"] != source_sha:
        _fail("pilot materialization source-manifest checksum is inconsistent")
    if manifest["content_sha256"] != content_sha256(manifest):
        _fail("pilot materialization content_sha256 does not match canonical content")

    selected = selection_manifest["entries"]
    selected_by_id = {str(entry["candidate_id"]): entry for entry in selected}
    materialized_entries = manifest["entries"]
    materialized_by_id = {
        str(entry["candidate_id"]): entry for entry in materialized_entries
    }
    if len(materialized_by_id) != len(materialized_entries):
        _fail("pilot materialization candidate IDs must be unique")
    if set(materialized_by_id) != set(selected_by_id):
        _fail("pilot materialization instances do not exactly match the frozen 200 candidates")
    if manifest["instance_count"] != len(materialized_entries):
        _fail("pilot materialization instance_count does not match entries")
    split_counts = Counter(str(entry["split"]) for entry in materialized_entries)
    if dict(split_counts) != manifest["split_counts"]:
        _fail("pilot materialization split_counts do not match entries")
    if manifest["dimensions"] != _dimension_summary(selected):
        _fail("pilot materialization dimensions do not match the frozen selection")

    selected_by_base: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate_id, selection in selected_by_id.items():
        base_id = selected_base_instance_id(selection, config)
        selected_by_base[base_id].append(selection)
        actual = materialized_by_id[candidate_id]
        expected_entry = {
            "instance_id": candidate_id,
            "candidate_id": candidate_id,
            "base_instance_id": base_id,
            "split": str(selection["split"]),
            "path": f"instances/{selection['split']}/{candidate_id}.json",
            "family": str(selection["family"]),
            "target_task_count": int(selection["target_task_count"]),
            "replicate_id": str(selection["replicate_id"]),
            "source_sha256": str(selection["source_sha256"]),
            "resource_scale": str(selection["resource_scale"]),
            "scenario_profile": str(selection["scenario_profile"]),
            "qos_profile": str(selection["qos_profile"]),
            "ifc_realization_seed": int(selection["ifc_realization_seed"]),
        }
        for key, expected in expected_entry.items():
            if actual[key] != expected:
                _fail(
                    f"pilot materialization entry {candidate_id!r} has inconsistent {key}"
                )

    expected_base_ids = set(selected_by_base)
    base_entries = manifest["base_entries"]
    calibration_entries = manifest["calibration_entries"]
    base_by_id = {str(entry["base_instance_id"]): entry for entry in base_entries}
    calibration_by_id = {
        str(entry["base_instance_id"]): entry for entry in calibration_entries
    }
    if len(base_by_id) != len(base_entries):
        _fail("pilot materialization base_instance_id entries must be unique")
    if len(calibration_by_id) != len(calibration_entries):
        _fail("pilot materialization calibration base_instance_id entries must be unique")
    if set(base_by_id) != expected_base_ids:
        _fail("pilot materialization base artifacts do not match selected base identities")
    if set(calibration_by_id) != expected_base_ids:
        _fail("pilot materialization calibration artifacts do not match selected base identities")
    if manifest["base_instance_count"] != len(expected_base_ids):
        _fail("pilot materialization base_instance_count is inconsistent")
    if manifest["calibration_count"] != len(expected_base_ids):
        _fail("pilot materialization calibration_count is inconsistent")

    if dataset_root is None:
        if source_root is not None:
            _fail("source_root requires dataset_root for full materialization validation")
        return

    dataset_path = Path(dataset_root)
    source_path = Path(source_root) if source_root is not None else None
    for base_id in sorted(expected_base_ids):
        base_entry = base_by_id[base_id]
        calibration_entry = calibration_by_id[base_id]
        base = _read_verified_json(
            dataset_path,
            base_entry["path"],
            base_entry["sha256"],
            label="base instance",
        )
        validate_base_instance(base)
        if base["metadata"]["base_instance_id"] != base_id:
            _fail(f"base artifact {base_id!r} contains the wrong identity")

        representative = selected_by_base[base_id][0]
        if source_path is not None:
            source_file = _relative_path(
                source_path,
                str(representative["source_path"]),
                label="frozen source path",
            )
            try:
                source_bytes = source_file.read_bytes()
            except OSError as exc:
                _fail(
                    f"cannot read frozen source {representative['source_path']!r}: {exc}"
                )
            if sha256(source_bytes).hexdigest() != representative["source_sha256"]:
                _fail(f"frozen source checksum mismatch for base {base_id!r}")
            workflow = normalize_dax(
                source_file,
                family=str(representative["family"]),
                target_task_count=int(representative["target_task_count"]),
                replicate_id=str(representative["replicate_id"]),
                reference_mips=int(config["workflows"]["reference_mips"]),
            )
            expected_base = build_base_instance(
                workflow,
                config,
                scale=str(representative["resource_scale"]),
                scenario=str(representative["scenario_profile"]),
                seed=int(representative["ifc_realization_seed"]),
            )
            if base != expected_base:
                _fail(f"base artifact {base_id!r} does not deterministically regenerate")

        calibration = _read_verified_json(
            dataset_path,
            calibration_entry["path"],
            calibration_entry["sha256"],
            label="calibration artifact",
        )
        validate_calibration_result_against_instance(calibration, base)
        if (
            calibration_entry["candidate_set_sha256"]
            != calibration["candidate_set_sha256"]
        ):
            _fail(
                f"calibration manifest checksum metadata is inconsistent for {base_id!r}"
            )

        for selection in selected_by_base[base_id]:
            candidate_id = str(selection["candidate_id"])
            entry = materialized_by_id[candidate_id]
            instance = _read_verified_json(
                dataset_path,
                entry["path"],
                entry["sha256"],
                label="QoS instance",
            )
            validate_qos_instance(instance)
            expected_instance = build_qos_instance(selection, calibration, config)
            if instance != expected_instance:
                _fail(
                    f"QoS instance {candidate_id!r} does not reconstruct from frozen calibration"
                )
            evaluation = validate_schedule(
                base,
                instance["joint_feasibility_witness"],
                deadline_us=instance["deadline"]["deadline_us"],
                budget_ncu=instance["budget"]["budget_ncu"],
            )
            if evaluation.joint_feasible is not True:
                _fail(f"QoS instance {candidate_id!r} joint witness is not feasible")
