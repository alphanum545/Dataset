from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from generator.canonical import canonical_json_bytes, content_sha256
from generator.full_materialize import COHORT_MANIFEST_VERSION, FULL_MATERIALIZATION_VERSION
from generator.materialize import build_qos_instance, selected_base_instance_id
from generator.pilot import enumerate_candidates

from .base_instance import validate_base_instance
from .calibration import validate_calibration_result_against_instance
from .errors import BenchmarkValidationError
from .materialization import validate_pilot_materialization_manifest
from .pilot import validate_pilot_selection
from .qos import validate_qos_instance
from .schema import validate_schema
from .semantic import validate_schedule, validate_source_manifest


def _fail(message: str) -> None:
    raise BenchmarkValidationError(message)


def _safe(root: Path, value: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or "\\" in value:
        _fail(f"unsafe manifest path: {value!r}")
    resolved_root = root.resolve()
    path = (resolved_root / Path(*posix.parts)).resolve()
    if resolved_root not in path.parents:
        _fail(f"manifest path escapes dataset root: {value!r}")
    return path


def _read(root: Path, entry: Mapping[str, Any], label: str) -> dict[str, Any]:
    path = _safe(root, str(entry["path"]))
    try:
        data = path.read_bytes()
    except OSError as exc:
        _fail(f"cannot read {label} {entry['path']!r}: {exc}")
    if sha256(data).hexdigest() != entry["sha256"]:
        _fail(f"{label} checksum mismatch: {entry['path']!r}")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label} JSON: {entry['path']!r}: {exc}")
    if not isinstance(payload, dict):
        _fail(f"{label} must be a JSON object")
    return payload


def validate_exposure_manifest(
    exposure: dict[str, Any],
    *,
    config: dict[str, Any],
    source_manifest: dict[str, Any],
    pilot_selection: dict[str, Any],
) -> None:
    validate_schema(exposure, "full-exposure")
    if exposure.get("exposure_manifest_version") != COHORT_MANIFEST_VERSION:
        _fail("unexpected exposure manifest version")
    if exposure.get("content_sha256") != content_sha256(exposure):
        _fail("exposure manifest checksum mismatch")
    candidates = enumerate_candidates(config, source_manifest)
    expected_ids = {str(c["candidate_id"]) for c in candidates}
    entries = exposure.get("entries", [])
    if len(entries) != 2835 or {str(e["instance_id"]) for e in entries} != expected_ids:
        _fail("exposure manifest does not cover the exact 2,835 candidate universe")
    counts = Counter(str(e["cohort"]) for e in entries)
    expected = {
        "original_development": 160,
        "development_sibling": 317,
        "original_holdout": 40,
        "holdout_sibling": 80,
        "expansion_evaluation": 2238,
    }
    if dict(counts) != expected or exposure.get("cohort_counts") != dict(sorted(counts.items())):
        _fail("exposure cohort counts do not match the frozen plan")
    pilot_by_id = {str(e["candidate_id"]): e for e in pilot_selection["entries"]}
    for item in entries:
        cid = str(item["instance_id"])
        if cid in pilot_by_id and item.get("original_split") != pilot_by_id[cid]["split"]:
            _fail(f"original pilot split changed for {cid}")


def validate_full_materialization_manifest(
    manifest: dict[str, Any],
    *,
    exposure: dict[str, Any],
    config: dict[str, Any],
    source_manifest: dict[str, Any],
    pilot_selection: dict[str, Any],
    pilot_manifest: dict[str, Any],
    dataset_root: str | Path | None = None,
    pilot_root: str | Path | None = None,
    source_root: str | Path | None = None,
) -> None:
    validate_schema(manifest, "full-materialization")
    validate_pilot_selection(pilot_selection, config=config, source_manifest=source_manifest)
    validate_exposure_manifest(exposure, config=config, source_manifest=source_manifest, pilot_selection=pilot_selection)
    if pilot_root is not None:
        validate_pilot_materialization_manifest(
            pilot_manifest,
            config=config,
            source_manifest=source_manifest,
            selection_manifest=pilot_selection,
            dataset_root=pilot_root,
            source_root=source_root,
        )
    if manifest.get("materialization_version") != FULL_MATERIALIZATION_VERSION:
        _fail("unexpected full materialization version")
    if manifest.get("content_sha256") != content_sha256(manifest):
        _fail("full materialization checksum mismatch")
    config_sha = sha256(canonical_json_bytes(config)).hexdigest()
    source_sha = sha256(canonical_json_bytes(source_manifest)).hexdigest()
    if manifest.get("configuration_sha256") != config_sha:
        _fail("full materialization configuration checksum mismatch")
    if manifest.get("source_manifest_sha256") != source_sha:
        _fail("full materialization source checksum mismatch")
    if manifest.get("pilot_selection_sha256") != pilot_selection["content_sha256"]:
        _fail("full materialization pilot selection checksum mismatch")
    if manifest.get("pilot_materialization_sha256") != pilot_manifest["content_sha256"]:
        _fail("full materialization pilot manifest checksum mismatch")
    if manifest.get("exposure_manifest_sha256") != exposure["content_sha256"]:
        _fail("full materialization exposure checksum mismatch")

    candidates = enumerate_candidates(config, source_manifest)
    by_id = {str(c["candidate_id"]): c for c in candidates}
    entries = manifest.get("entries", [])
    if manifest.get("instance_count") != 2835 or len(entries) != 2835:
        _fail("full materialization must contain exactly 2,835 QoS entries")
    if {str(e["instance_id"]) for e in entries} != set(by_id):
        _fail("full materialization instance identities do not match the candidate universe")
    base_entries = manifest.get("base_entries", [])
    calibration_entries = manifest.get("calibration_entries", [])
    if manifest.get("base_instance_count") != 945 or len(base_entries) != 945:
        _fail("full materialization must contain exactly 945 bases")
    if manifest.get("calibration_count") != 945 or len(calibration_entries) != 945:
        _fail("full materialization must contain exactly 945 calibrations")
    if len({e["base_instance_id"] for e in base_entries}) != 945:
        _fail("full materialization base identities are not unique")
    if len({e["base_instance_id"] for e in calibration_entries}) != 945:
        _fail("full materialization calibration identities are not unique")

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in by_id.values():
        grouped[selected_base_instance_id(candidate, config)].append(candidate)
    if set(grouped) != {str(e["base_instance_id"]) for e in base_entries}:
        _fail("base artifact identities do not match the 945 expected bases")
    if any(len(v) != 3 for v in grouped.values()):
        _fail("each full base must have exactly three QoS profiles")

    exposure_by_id = {str(e["instance_id"]): e for e in exposure["entries"]}
    pilot_by_id = {str(e["instance_id"]): e for e in pilot_manifest["entries"]}
    cohort_counts = Counter()
    for entry in entries:
        cid = str(entry["instance_id"])
        candidate = by_id[cid]
        expected_base = selected_base_instance_id(candidate, config)
        if entry["base_instance_id"] != expected_base:
            _fail(f"wrong base identity for {cid}")
        if entry["cohort"] != exposure_by_id[cid]["cohort"]:
            _fail(f"wrong exposure cohort for {cid}")
        cohort_counts[entry["cohort"]] += 1
        if cid in pilot_by_id:
            frozen = pilot_by_id[cid]
            if entry["path"] != frozen["path"] or entry["sha256"] != frozen["sha256"]:
                _fail(f"original pilot artifact changed in full release: {cid}")
            if entry.get("original_split") != frozen["split"]:
                _fail(f"original split changed in full release: {cid}")
            if entry.get("provenance") != "reused_pilot":
                _fail(f"pilot provenance missing for {cid}")
    if manifest.get("cohort_counts") != dict(sorted(cohort_counts.items())):
        _fail("full materialization cohort_counts do not match entries")

    if dataset_root is None:
        return
    root = Path(dataset_root)
    base_by_id = {str(e["base_instance_id"]): e for e in base_entries}
    cal_by_id = {str(e["base_instance_id"]): e for e in calibration_entries}
    entry_by_id = {str(e["instance_id"]): e for e in entries}

    if source_root is not None:
        validate_source_manifest(source_manifest, source_root=source_root, require_complete=True)

    for base_id in sorted(grouped):
        base = _read(root, base_by_id[base_id], "base")
        validate_base_instance(base)
        if base["metadata"]["base_instance_id"] != base_id:
            _fail(f"base identity mismatch inside artifact {base_id}")
        calibration = _read(root, cal_by_id[base_id], "calibration")
        validate_calibration_result_against_instance(calibration, base)
        for candidate in grouped[base_id]:
            cid = str(candidate["candidate_id"])
            instance = _read(root, entry_by_id[cid], "QoS instance")
            validate_qos_instance(instance)
            expected = build_qos_instance(candidate, calibration, config)
            if instance != expected:
                _fail(f"QoS instance does not reconstruct from calibration: {cid}")
            evaluation = validate_schedule(
                base,
                instance["joint_feasibility_witness"],
                deadline_us=instance["deadline"]["deadline_us"],
                budget_ncu=instance["budget"]["budget_ncu"],
            )
            if evaluation.joint_feasible is not True:
                _fail(f"joint feasibility witness failed: {cid}")
