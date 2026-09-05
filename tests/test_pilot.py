from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from generator.canonical import content_sha256
from generator.config import load_config
from generator.pilot import build_pilot_selection_manifest, enumerate_candidates
from validation import BenchmarkValidationError, validate_pilot_selection


ROOT = Path(__file__).resolve().parents[1]
_BASE_DIMENSIONS = (
    "family",
    "target_task_count",
    "replicate_id",
    "resource_scale",
    "scenario_profile",
)


@pytest.fixture(scope="module")
def inputs() -> tuple[dict, dict]:
    config = load_config(ROOT / "config" / "benchmark-v1.yaml")
    source_manifest = json.loads(
        (ROOT / "manifests" / "source-workflows-v1.json").read_text(encoding="utf-8")
    )
    return config, source_manifest


@pytest.fixture(scope="module")
def selection(inputs: tuple[dict, dict]) -> dict:
    return build_pilot_selection_manifest(*inputs)


def _string_keys(values: dict) -> dict[str, int]:
    return {str(key): int(value) for key, value in values.items()}


def _base_signature(entry: dict) -> tuple:
    return tuple(entry[dimension] for dimension in _BASE_DIMENSIONS)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    return False


def test_candidate_universe_is_complete_and_unique(inputs: tuple[dict, dict]):
    candidates = enumerate_candidates(*inputs)
    assert len(candidates) == 2_835
    assert len({candidate["candidate_id"] for candidate in candidates}) == 2_835


def test_pilot_has_frozen_counts_marginals_and_pairwise_coverage(
    inputs: tuple[dict, dict], selection: dict
):
    config, _ = inputs
    assert selection["selector"]["selector_version"] == 2
    assert selection["selected_count"] == 200
    assert selection["split_counts"] == {"development": 160, "holdout": 40}
    assert len({entry["candidate_id"] for entry in selection["entries"]}) == 200

    expected_overall = config["pilot_selection"]["marginal_targets"]
    expected_holdout = config["pilot_selection"]["holdout_marginal_targets"]
    for dimension, targets in expected_overall.items():
        assert selection["coverage"]["overall_marginals"][dimension] == _string_keys(
            targets
        )
    for dimension, targets in expected_holdout.items():
        assert selection["coverage"]["holdout_marginals"][dimension] == _string_keys(
            targets
        )

    assert all(
        item["observed_pairs"] == item["possible_pairs"]
        for item in selection["coverage"]["overall_pairwise"]
    )
    assert all(
        item["observed_pairs"] == item["possible_pairs"]
        for item in selection["coverage"]["holdout_pairwise"]
    )


def test_holdout_uses_unique_bases_disjoint_from_development(selection: dict):
    development = [
        entry for entry in selection["entries"] if entry["split"] == "development"
    ]
    holdout = [entry for entry in selection["entries"] if entry["split"] == "holdout"]
    development_bases = {_base_signature(entry) for entry in development}
    holdout_bases = {_base_signature(entry) for entry in holdout}

    assert len(holdout_bases) == 40
    assert development_bases.isdisjoint(holdout_bases)
    assert selection["base_isolation"] == {
        "development_unique_base_count": len(development_bases),
        "holdout_unique_base_count": 40,
        "cross_split_base_overlap_count": 0,
    }


def test_selection_is_deterministic_and_seed_sensitive(
    inputs: tuple[dict, dict], selection: dict
):
    config, source_manifest = inputs
    assert build_pilot_selection_manifest(config, source_manifest) == selection

    alternate = deepcopy(config)
    alternate["pilot_selection"]["seed"] += 1
    changed = build_pilot_selection_manifest(alternate, source_manifest)
    assert [entry["candidate_id"] for entry in changed["entries"]] != [
        entry["candidate_id"] for entry in selection["entries"]
    ]
    assert changed["coverage"]["overall_marginals"] == selection["coverage"][
        "overall_marginals"
    ]
    changed_development_bases = {
        _base_signature(entry)
        for entry in changed["entries"]
        if entry["split"] == "development"
    }
    changed_holdout_bases = {
        _base_signature(entry)
        for entry in changed["entries"]
        if entry["split"] == "holdout"
    }
    assert len(changed_holdout_bases) == 40
    assert changed_development_bases.isdisjoint(changed_holdout_bases)


def test_selection_validates_exactly_and_rejects_tampering(
    inputs: tuple[dict, dict], selection: dict
):
    config, source_manifest = inputs
    validate_pilot_selection(
        selection, config=config, source_manifest=source_manifest
    )

    tampered = deepcopy(selection)
    tampered["entries"][0]["split"] = "holdout"
    with pytest.raises(BenchmarkValidationError):
        validate_pilot_selection(tampered)

    tampered_coverage = deepcopy(selection)
    tampered_coverage["coverage"]["holdout_pairwise"][0]["observed_pairs"] -= 1
    tampered_coverage["content_sha256"] = content_sha256(tampered_coverage)
    with pytest.raises(BenchmarkValidationError):
        validate_pilot_selection(tampered_coverage)

    tampered_isolation = deepcopy(selection)
    tampered_isolation["base_isolation"]["cross_split_base_overlap_count"] = 1
    tampered_isolation["content_sha256"] = content_sha256(tampered_isolation)
    with pytest.raises(BenchmarkValidationError):
        validate_pilot_selection(tampered_isolation)


def test_selection_contains_no_binary_floats(selection: dict):
    assert not _contains_float(selection)
