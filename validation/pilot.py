from __future__ import annotations

from typing import Any

from .errors import BenchmarkValidationError
from .semantic import validate_pilot_selection as _validate_selection_contract


_BASE_DIMENSIONS = (
    "family",
    "target_task_count",
    "replicate_id",
    "resource_scale",
    "scenario_profile",
)


def _fail(message: str) -> None:
    raise BenchmarkValidationError(message)


def _base_signature(entry: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(entry[dimension] for dimension in _BASE_DIMENSIONS)


def validate_pilot_selection(
    manifest: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    source_manifest: dict[str, Any] | None = None,
) -> None:
    """Validate the frozen pilot contract plus base-level holdout isolation."""
    _validate_selection_contract(
        manifest,
        config=config,
        source_manifest=source_manifest,
    )

    development_bases = {
        _base_signature(entry)
        for entry in manifest["entries"]
        if entry["split"] == "development"
    }
    holdout_bases = {
        _base_signature(entry)
        for entry in manifest["entries"]
        if entry["split"] == "holdout"
    }
    overlap = development_bases & holdout_bases
    expected = {
        "development_unique_base_count": len(development_bases),
        "holdout_unique_base_count": len(holdout_bases),
        "cross_split_base_overlap_count": len(overlap),
    }
    if manifest["base_isolation"] != expected:
        _fail("pilot base_isolation metadata does not match selected entries")
    if len(holdout_bases) != 40:
        _fail("pilot holdout must contain 40 unique base realizations")
    if overlap:
        _fail("pilot development and holdout splits share base realizations")
