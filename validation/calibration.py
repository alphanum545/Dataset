from __future__ import annotations

from hashlib import sha256
from typing import Any

from generator.canonical import canonical_json_bytes
from generator.reference_schedulers import (
    CALIBRATION_VERSION,
    REFERENCE_SCHEDULER_VERSION,
    calibration_lower_bounds,
)

from .errors import BenchmarkValidationError
from .schema import validate_schema


_REFERENCE_SCHEDULERS = {
    "deterministic_heft_ifc",
    "deterministic_peft_ifc",
    "deterministic_cpop_ifc",
    "deterministic_cost_reference_ifc",
}


def _fail(message: str) -> None:
    raise BenchmarkValidationError(message)


def validate_calibration_result(result: dict[str, Any]) -> None:
    """Validate calibration-set structure and frozen envelope selection semantics.

    Different reference algorithms are allowed to converge to the same canonical
    schedule. MOHEFT candidates, however, must be unique and must not duplicate an
    explicit reference endpoint because they are stored as the retained candidate set.
    """
    validate_schema(result, "calibration-result")
    lower = result["lower_bounds"]
    if lower["t_lb_us"] != max(lower["t_cp_lb_us"], lower["t_capacity_lb_us"]):
        _fail("t_lb_us must equal max(t_cp_lb_us, t_capacity_lb_us)")

    references = result["reference_schedulers"]
    scheduler_ids = [reference["scheduler_id"] for reference in references]
    if len(scheduler_ids) != len(set(scheduler_ids)):
        _fail("reference scheduler IDs must be unique")
    if set(scheduler_ids) != _REFERENCE_SCHEDULERS:
        _fail("calibration must contain the frozen IFC reference scheduler portfolio")

    reference_schedules = [reference["schedule"] for reference in references]
    moheft_schedules = result["moheft"]["candidate_schedules"]
    moheft_ids = [schedule["schedule_id"] for schedule in moheft_schedules]
    moheft_checksums = [schedule["schedule_sha256"] for schedule in moheft_schedules]
    if len(moheft_ids) != len(set(moheft_ids)):
        _fail("MOHEFT candidate schedule IDs must be unique")
    if len(moheft_checksums) != len(set(moheft_checksums)):
        _fail("MOHEFT candidate schedule checksums must be unique")

    reference_ids = {schedule["schedule_id"] for schedule in reference_schedules}
    reference_checksums = {
        schedule["schedule_sha256"] for schedule in reference_schedules
    }
    if reference_ids.intersection(moheft_ids):
        _fail("MOHEFT candidates must not duplicate explicit reference schedules")
    if reference_checksums.intersection(moheft_checksums):
        _fail("MOHEFT candidates must not duplicate explicit reference checksums")

    schedules = [*reference_schedules, *moheft_schedules]
    if any(schedule["makespan_us"] < lower["t_lb_us"] for schedule in schedules):
        _fail("a calibration makespan cannot be below the stored lower bound")

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
    anchors = result["anchors"]
    expected_anchors = {
        "fast_schedule_id": fast["schedule_id"],
        "economical_schedule_id": economical["schedule_id"],
        "t_fast_us": fast["makespan_us"],
        "t_economical_us": economical["makespan_us"],
        "cost_fast_ncu": fast["compute_cost_ncu"],
        "cost_economical_ncu": economical["compute_cost_ncu"],
        "deadline_range_degenerate": fast["makespan_us"]
        == economical["makespan_us"],
    }
    if anchors != expected_anchors:
        _fail("calibration anchors do not match the frozen selection rules")


def validate_calibration_result_against_instance(
    result: dict[str, Any], base_instance: dict[str, Any]
) -> int:
    """Re-evaluate every calibration schedule against one authoritative base instance."""
    from .semantic import validate_base_instance, validate_schedule

    validate_base_instance(base_instance)
    validate_calibration_result(result)
    if result["base_instance_id"] != base_instance["metadata"]["base_instance_id"]:
        _fail("calibration base_instance_id does not match the supplied base instance")
    if result["calibration_version"] != CALIBRATION_VERSION:
        _fail("calibration_version is not the frozen v1 version")
    versions = [
        reference["scheduler_version"] for reference in result["reference_schedulers"]
    ]
    versions.append(result["moheft"]["scheduler_version"])
    if any(version != REFERENCE_SCHEDULER_VERSION for version in versions):
        _fail("calibration scheduler version is not the frozen v1 version")
    if result["lower_bounds"] != calibration_lower_bounds(base_instance):
        _fail(
            "calibration lower bounds do not reconstruct from the supplied base instance"
        )

    candidate_payload = {
        "reference_schedulers": result["reference_schedulers"],
        "moheft": result["moheft"],
    }
    expected_checksum = sha256(canonical_json_bytes(candidate_payload)).hexdigest()
    if result["candidate_set_sha256"] != expected_checksum:
        _fail(
            "candidate_set_sha256 does not match the canonical calibration candidate set"
        )

    schedules = [
        *(reference["schedule"] for reference in result["reference_schedulers"]),
        *result["moheft"]["candidate_schedules"],
    ]
    for schedule in schedules:
        validate_schedule(base_instance, schedule)
    return len(schedules)
