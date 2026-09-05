from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping

from .canonical import canonical_json_bytes, content_sha256
from .dax import normalize_dax
from .exact import mul_ratio_ceil, mul_ratio_floor
from .identity import base_instance_id, workflow_id
from .instance import build_base_instance
from .reference_schedulers import build_calibration_result


PILOT_MATERIALIZATION_VERSION = "pilot_materialization_v1"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class PilotMaterializationError(ValueError):
    """Raised when the frozen pilot cannot be materialized deterministically."""


def _json_file_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    data = _json_file_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256(data).hexdigest()


def _safe_source(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
        raise PilotMaterializationError(
            f"source path must be a relative canonical POSIX path: {relative!r}"
        )
    resolved_root = root.resolve()
    source = (resolved_root / Path(*posix.parts)).resolve()
    if resolved_root not in source.parents:
        raise PilotMaterializationError(f"source path escapes source root: {relative!r}")
    return source


def selected_base_instance_id(
    entry: Mapping[str, Any], config: Mapping[str, Any]
) -> str:
    workflow_identifier = workflow_id(
        family=str(entry["family"]),
        target_task_count=int(entry["target_task_count"]),
        replicate_id=str(entry["replicate_id"]),
        source_sha256=str(entry["source_sha256"]),
    )
    return base_instance_id(
        dataset_version=str(config["dataset"]["version"]),
        workflow_identifier=workflow_identifier,
        resource_scale=str(entry["resource_scale"]),
        scenario_profile=str(entry["scenario_profile"]),
        ifc_realization_seed=int(entry["ifc_realization_seed"]),
    )


def calibration_schedules(calibration: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        *(dict(item["schedule"]) for item in calibration["reference_schedulers"]),
        *(dict(schedule) for schedule in calibration["moheft"]["candidate_schedules"]),
    ]


def _mapping_key(schedule: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(assignment["task_id"]), str(assignment["resource_id"]))
        for assignment in schedule["assignments"]
    )


def build_qos_instance(
    selection_entry: Mapping[str, Any],
    calibration: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize one exact joint deadline-budget instance from frozen calibration."""
    base_identifier = selected_base_instance_id(selection_entry, config)
    if calibration["base_instance_id"] != base_identifier:
        raise PilotMaterializationError(
            "calibration base_instance_id does not match the selected pilot identity"
        )

    profile = str(selection_entry["qos_profile"])
    try:
        deadline_fraction = config["reference_makespan"][
            "deadline_interpolation_fractions"
        ][profile]
        budget_profile = config["budget"]["joint_qos_profiles"][profile]
        budget_fraction = budget_profile["budget_gap_fraction"]
    except KeyError as exc:
        raise PilotMaterializationError(
            f"missing frozen QoS configuration for profile {profile!r}"
        ) from exc
    if str(budget_profile["deadline_level"]) != profile:
        raise PilotMaterializationError(
            f"budget deadline_level does not match profile {profile!r}"
        )

    anchors = calibration["anchors"]
    t_fast = int(anchors["t_fast_us"])
    t_economical = int(anchors["t_economical_us"])
    if t_economical < t_fast:
        raise PilotMaterializationError("economical anchor makespan is below fast anchor")
    time_gap = t_economical - t_fast
    deadline_numerator = int(deadline_fraction["numerator"])
    deadline_denominator = int(deadline_fraction["denominator"])
    deadline_us = t_fast + mul_ratio_ceil(
        time_gap, deadline_numerator, deadline_denominator
    )

    feasible = [
        schedule
        for schedule in calibration_schedules(calibration)
        if int(schedule["makespan_us"]) <= deadline_us
    ]
    if not feasible:
        raise PilotMaterializationError(
            "frozen calibration set has no schedule meeting the materialized deadline"
        )
    witness = min(
        feasible,
        key=lambda schedule: (
            int(schedule["compute_cost_ncu"]),
            int(schedule["makespan_us"]),
            _mapping_key(schedule),
            str(schedule["schedule_id"]),
        ),
    )
    cost_floor = int(witness["compute_cost_ncu"])
    cost_fast = int(anchors["cost_fast_ncu"])
    if cost_floor > cost_fast:
        raise PilotMaterializationError(
            "deadline-conditioned calibration cost floor exceeds fast-anchor cost"
        )
    budget_numerator = int(budget_fraction["numerator"])
    budget_denominator = int(budget_fraction["denominator"])
    budget_width = cost_fast - cost_floor
    budget_gap = mul_ratio_floor(
        budget_width, budget_numerator, budget_denominator
    )
    budget_ncu = cost_floor + budget_gap

    reference_versions = {
        str(reference["scheduler_id"]): str(reference["scheduler_version"])
        for reference in calibration["reference_schedulers"]
    }
    materialized = {
        "schema_version": 1,
        "instance_id": str(selection_entry["candidate_id"]),
        "base_instance_id": base_identifier,
        "profile": profile,
        "source_sha256": str(selection_entry["source_sha256"]),
        "resource_scale": str(selection_entry["resource_scale"]),
        "scenario_profile": str(selection_entry["scenario_profile"]),
        "ifc_realization_seed": int(selection_entry["ifc_realization_seed"]),
        "deadline": {
            "fast_schedule_id": str(anchors["fast_schedule_id"]),
            "economical_schedule_id": str(anchors["economical_schedule_id"]),
            "t_fast_us": t_fast,
            "t_economical_us": t_economical,
            "time_gap_us": time_gap,
            "interpolation_numerator": deadline_numerator,
            "interpolation_denominator": deadline_denominator,
            "deadline_us": deadline_us,
            "deadline_range_degenerate": bool(anchors["deadline_range_degenerate"]),
        },
        "budget": {
            "cost_fast_ncu": cost_fast,
            "cost_floor_ref_ncu": cost_floor,
            "budget_gap_ncu": budget_gap,
            "factor_numerator": budget_numerator,
            "factor_denominator": budget_denominator,
            "budget_ncu": budget_ncu,
            "budget_range_degenerate": budget_width == 0,
        },
        "calibration": {
            "reference_scheduler_versions": reference_versions,
            "moheft_scheduler_version": str(calibration["moheft"]["scheduler_version"]),
            "moheft_k": int(calibration["moheft"]["k"]),
            "candidate_set_sha256": str(calibration["candidate_set_sha256"]),
        },
        "joint_feasibility_witness": witness,
        "content_sha256": "0" * 64,
    }
    materialized["content_sha256"] = content_sha256(materialized)
    return materialized


def _dimension_summary(entries: Iterable[Mapping[str, Any]]) -> dict[str, list[Any]]:
    rows = list(entries)
    return {
        "families": sorted({str(entry["family"]) for entry in rows}),
        "task_counts": sorted({int(entry["target_task_count"]) for entry in rows}),
        "replicates": sorted({str(entry["replicate_id"]) for entry in rows}),
        "resource_scales": sorted({str(entry["resource_scale"]) for entry in rows}),
        "scenario_profiles": sorted({str(entry["scenario_profile"]) for entry in rows}),
        "qos_profiles": sorted({str(entry["qos_profile"]) for entry in rows}),
    }


def materialize_pilot_dataset(
    config: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    selection_manifest: Mapping[str, Any],
    *,
    source_root: str | Path,
    output_root: str | Path,
    generator_commit_sha: str,
) -> dict[str, Any]:
    """Materialize the exact frozen 200-input pilot into an isolated output directory."""
    if not _GIT_SHA.fullmatch(generator_commit_sha):
        raise PilotMaterializationError(
            "generator_commit_sha must be a lowercase 40-character Git SHA"
        )
    config_sha = sha256(canonical_json_bytes(config)).hexdigest()
    source_manifest_sha = sha256(canonical_json_bytes(source_manifest)).hexdigest()
    if selection_manifest.get("content_sha256") != content_sha256(dict(selection_manifest)):
        raise PilotMaterializationError("pilot selection content checksum is invalid")
    if selection_manifest.get("configuration_sha256") != config_sha:
        raise PilotMaterializationError(
            "pilot selection does not match the supplied benchmark configuration"
        )
    if selection_manifest.get("source_manifest_sha256") != source_manifest_sha:
        raise PilotMaterializationError(
            "pilot selection does not match the supplied source manifest"
        )

    entries = list(selection_manifest["entries"])
    expected_count = int(config["pilot_selection"]["selected_count"])
    if len(entries) != expected_count or int(selection_manifest["selected_count"]) != expected_count:
        raise PilotMaterializationError(
            f"pilot selection must contain exactly {expected_count} entries"
        )
    candidate_ids = [str(entry["candidate_id"]) for entry in entries]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise PilotMaterializationError("pilot candidate IDs must be unique")
    split_counts = Counter(str(entry["split"]) for entry in entries)
    expected_splits = {
        str(key): int(value)
        for key, value in config["pilot_selection"]["split_counts"].items()
    }
    if dict(split_counts) != expected_splits:
        raise PilotMaterializationError("pilot split counts do not match frozen configuration")

    destination = Path(output_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise PilotMaterializationError(
                f"output root must be missing or empty: {destination}"
            )
        destination.rmdir()
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    source_root_path = Path(source_root)
    workflow_cache: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}
    base_cache: dict[str, dict[str, Any]] = {}
    calibration_cache: dict[str, dict[str, Any]] = {}
    base_entries: list[dict[str, Any]] = []
    calibration_entries: list[dict[str, Any]] = []
    instance_entries: list[dict[str, Any]] = []

    try:
        for selected in entries:
            source_key = (
                str(selected["source_path"]),
                str(selected["family"]),
                int(selected["target_task_count"]),
                str(selected["replicate_id"]),
                str(selected["source_sha256"]),
            )
            workflow = workflow_cache.get(source_key)
            if workflow is None:
                source = _safe_source(source_root_path, source_key[0])
                try:
                    source_bytes = source.read_bytes()
                except OSError as exc:
                    raise PilotMaterializationError(
                        f"cannot read frozen source {source_key[0]!r}: {exc}"
                    ) from exc
                if sha256(source_bytes).hexdigest() != source_key[4]:
                    raise PilotMaterializationError(
                        f"frozen source checksum mismatch for {source_key[0]!r}"
                    )
                workflow = normalize_dax(
                    source,
                    family=source_key[1],
                    target_task_count=source_key[2],
                    replicate_id=source_key[3],
                    reference_mips=int(config["workflows"]["reference_mips"]),
                )
                workflow_cache[source_key] = workflow

            base_identifier = selected_base_instance_id(selected, config)
            base = base_cache.get(base_identifier)
            calibration = calibration_cache.get(base_identifier)
            if base is None or calibration is None:
                base = build_base_instance(
                    workflow,
                    dict(config),
                    scale=str(selected["resource_scale"]),
                    scenario=str(selected["scenario_profile"]),
                    seed=int(selected["ifc_realization_seed"]),
                )
                if base["metadata"]["base_instance_id"] != base_identifier:
                    raise PilotMaterializationError(
                        "materialized base instance identity does not match pilot selection"
                    )
                calibration = build_calibration_result(
                    base, k=int(config["budget"]["calibration"]["tradeoff_solutions"])
                )
                base_cache[base_identifier] = base
                calibration_cache[base_identifier] = calibration

                base_path = PurePosixPath("base") / f"{base_identifier}.json"
                base_digest = _write_json(staging / Path(*base_path.parts), base)
                base_entries.append(
                    {
                        "base_instance_id": base_identifier,
                        "path": base_path.as_posix(),
                        "sha256": base_digest,
                    }
                )
                calibration_path = (
                    PurePosixPath("calibration") / f"{base_identifier}.json"
                )
                calibration_digest = _write_json(
                    staging / Path(*calibration_path.parts), calibration
                )
                calibration_entries.append(
                    {
                        "base_instance_id": base_identifier,
                        "path": calibration_path.as_posix(),
                        "sha256": calibration_digest,
                        "candidate_set_sha256": str(
                            calibration["candidate_set_sha256"]
                        ),
                    }
                )

            instance = build_qos_instance(selected, calibration, config)
            split = str(selected["split"])
            candidate_id = str(selected["candidate_id"])
            instance_path = (
                PurePosixPath("instances") / split / f"{candidate_id}.json"
            )
            instance_digest = _write_json(
                staging / Path(*instance_path.parts), instance
            )
            instance_entries.append(
                {
                    "instance_id": candidate_id,
                    "candidate_id": candidate_id,
                    "base_instance_id": base_identifier,
                    "split": split,
                    "path": instance_path.as_posix(),
                    "sha256": instance_digest,
                    "family": str(selected["family"]),
                    "target_task_count": int(selected["target_task_count"]),
                    "replicate_id": str(selected["replicate_id"]),
                    "source_sha256": str(selected["source_sha256"]),
                    "resource_scale": str(selected["resource_scale"]),
                    "scenario_profile": str(selected["scenario_profile"]),
                    "qos_profile": str(selected["qos_profile"]),
                    "ifc_realization_seed": int(selected["ifc_realization_seed"]),
                }
            )

        base_entries.sort(key=lambda item: item["base_instance_id"])
        calibration_entries.sort(key=lambda item: item["base_instance_id"])
        instance_entries.sort(
            key=lambda item: (item["split"], item["candidate_id"])
        )
        manifest = {
            "schema_version": 1,
            "materialization_version": PILOT_MATERIALIZATION_VERSION,
            "selection_id": str(selection_manifest["selection_id"]),
            "selection_sha256": str(selection_manifest["content_sha256"]),
            "dataset_version": str(config["dataset"]["version"]),
            "generator_commit_sha": generator_commit_sha,
            "configuration_sha256": config_sha,
            "source_manifest_sha256": source_manifest_sha,
            "base_instance_count": len(base_entries),
            "calibration_count": len(calibration_entries),
            "instance_count": len(instance_entries),
            "split_counts": dict(sorted(split_counts.items())),
            "dimensions": _dimension_summary(entries),
            "base_entries": base_entries,
            "calibration_entries": calibration_entries,
            "entries": instance_entries,
            "content_sha256": "0" * 64,
        }
        manifest["content_sha256"] = content_sha256(manifest)
        staging.replace(destination)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
