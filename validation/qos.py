from __future__ import annotations

from typing import Any

from generator.canonical import content_sha256
from generator.exact import mul_ratio_ceil, mul_ratio_floor

from .errors import BenchmarkValidationError
from .schema import validate_schema
from .semantic import _validate_schedule_shape


_REFERENCE_SCHEDULERS = {
    "deterministic_heft_ifc",
    "deterministic_peft_ifc",
    "deterministic_cpop_ifc",
    "deterministic_cost_reference_ifc",
}
_DEADLINE_INTERPOLATION_FRACTIONS = {
    "tight": (1, 100),
    "moderate": (1, 4),
    "relaxed": (3, 4),
}
_BUDGET_FACTORS = {
    "tight": (1, 10),
    "moderate": (1, 2),
    "relaxed": (9, 10),
}


def _fail(message: str) -> None:
    raise BenchmarkValidationError(message)


def validate_qos_instance(instance: dict[str, Any]) -> None:
    """Validate the frozen v1-draft joint QoS construction contract."""
    validate_schema(instance, "qos-instance")
    profile = instance["profile"]
    if profile not in _DEADLINE_INTERPOLATION_FRACTIONS:
        _fail(f"unknown QoS profile {profile!r}")

    deadline = instance["deadline"]
    budget = instance["budget"]
    witness = instance["joint_feasibility_witness"]
    _validate_schedule_shape(witness)
    if set(instance["calibration"]["reference_scheduler_versions"]) != _REFERENCE_SCHEDULERS:
        _fail("QoS calibration versions do not identify the frozen reference portfolio")

    fraction = (
        deadline["interpolation_numerator"],
        deadline["interpolation_denominator"],
    )
    if fraction != _DEADLINE_INTERPOLATION_FRACTIONS[profile]:
        _fail(f"deadline interpolation does not match the frozen {profile!r} profile")
    if deadline["t_economical_us"] < deadline["t_fast_us"]:
        _fail("t_economical_us cannot be below t_fast_us")
    time_gap = deadline["t_economical_us"] - deadline["t_fast_us"]
    if deadline["time_gap_us"] != time_gap:
        _fail("time_gap_us does not match the deadline anchors")
    if deadline["deadline_range_degenerate"] is not (time_gap == 0):
        _fail("deadline_range_degenerate is inconsistent with the deadline anchors")
    expected_deadline = deadline["t_fast_us"] + mul_ratio_ceil(
        time_gap,
        deadline["interpolation_numerator"],
        deadline["interpolation_denominator"],
    )
    if deadline["deadline_us"] != expected_deadline:
        _fail("deadline_us does not reconstruct from the exact envelope interpolation")

    if (budget["factor_numerator"], budget["factor_denominator"]) != _BUDGET_FACTORS[profile]:
        _fail(f"budget factor does not match the frozen {profile!r} profile")
    if budget["cost_floor_ref_ncu"] > budget["cost_fast_ncu"]:
        _fail("cost_floor_ref_ncu cannot exceed cost_fast_ncu")
    tradeoff_width = budget["cost_fast_ncu"] - budget["cost_floor_ref_ncu"]
    expected_budget_gap = mul_ratio_floor(
        tradeoff_width, budget["factor_numerator"], budget["factor_denominator"]
    )
    if budget["budget_gap_ncu"] != expected_budget_gap:
        _fail("budget_gap_ncu does not reconstruct from the exact interpolation rule")
    expected_budget = budget["cost_floor_ref_ncu"] + expected_budget_gap
    if budget["budget_ncu"] != expected_budget:
        _fail("budget_ncu does not reconstruct from the exact interpolation rule")
    if budget["budget_range_degenerate"] is not (tradeoff_width == 0):
        _fail("budget_range_degenerate is inconsistent with the calibration endpoints")
    if witness["compute_cost_ncu"] != budget["cost_floor_ref_ncu"]:
        _fail("joint witness cost does not equal cost_floor_ref_ncu")
    if witness["compute_cost_ncu"] > budget["budget_ncu"]:
        _fail("joint witness exceeds the materialized budget")
    if witness["makespan_us"] > deadline["deadline_us"]:
        _fail("joint witness exceeds the materialized deadline")
    if instance["content_sha256"] != content_sha256(instance):
        _fail("QoS instance content_sha256 does not match canonical content")
