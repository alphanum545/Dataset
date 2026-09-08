from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from generator.config import load_config
from generator.full_materialize import build_exposure_manifest
from generator.materialize import selected_base_instance_id

ROOT = Path(__file__).resolve().parents[1]


def test_full_exposure_manifest_matches_frozen_cohort_accounting():
    config = load_config(ROOT / "config" / "benchmark-v1.yaml")
    source_manifest = json.loads((ROOT / "manifests" / "source-workflows-v1.json").read_text(encoding="utf-8"))
    pilot = json.loads((ROOT / "manifests" / "pilot-selection-v1.json").read_text(encoding="utf-8"))

    exposure = build_exposure_manifest(config, source_manifest, pilot)

    assert exposure["instance_count"] == 2835
    assert exposure["cohort_counts"] == {
        "development_sibling": 317,
        "expansion_evaluation": 2238,
        "holdout_sibling": 80,
        "original_development": 160,
        "original_holdout": 40,
    }
    assert len({entry["instance_id"] for entry in exposure["entries"]}) == 2835

    pilot_by_id = {entry["candidate_id"]: entry for entry in pilot["entries"]}
    original = [entry for entry in exposure["entries"] if entry["instance_id"] in pilot_by_id]
    assert Counter(entry["original_split"] for entry in original) == {"development": 160, "holdout": 40}


def test_exposure_keeps_holdout_and_development_base_sets_disjoint():
    config = load_config(ROOT / "config" / "benchmark-v1.yaml")
    pilot = json.loads((ROOT / "manifests" / "pilot-selection-v1.json").read_text(encoding="utf-8"))
    dev = {selected_base_instance_id(entry, config) for entry in pilot["entries"] if entry["split"] == "development"}
    holdout = {selected_base_instance_id(entry, config) for entry in pilot["entries"] if entry["split"] == "holdout"}
    assert len(dev) == 159
    assert len(holdout) == 40
    assert not (dev & holdout)


def test_full_materializer_rejects_invalid_worker_count_before_work(tmp_path):
    from generator.full_materialize import FullMaterializationError, materialize_full_dataset
    import pytest

    with pytest.raises(FullMaterializationError, match="workers"):
        materialize_full_dataset({}, {}, {}, {}, source_root=tmp_path, pilot_root=tmp_path, output_root=tmp_path / "out", generator_commit_sha="1" * 40, workers=0)


def test_full_materializer_rejects_invalid_generator_sha_before_work(tmp_path):
    from generator.full_materialize import FullMaterializationError, materialize_full_dataset
    import pytest

    with pytest.raises(FullMaterializationError, match="generator_commit_sha"):
        materialize_full_dataset({}, {}, {}, {}, source_root=tmp_path, pilot_root=tmp_path, output_root=tmp_path / "out", generator_commit_sha="not-a-git-sha", workers=1)


def test_exposure_manifest_passes_full_schema_and_semantic_validation():
    from validation.full_materialization import validate_exposure_manifest

    config = load_config(ROOT / "config" / "benchmark-v1.yaml")
    source_manifest = json.loads((ROOT / "manifests" / "source-workflows-v1.json").read_text(encoding="utf-8"))
    pilot = json.loads((ROOT / "manifests" / "pilot-selection-v1.json").read_text(encoding="utf-8"))
    exposure = build_exposure_manifest(config, source_manifest, pilot)
    validate_exposure_manifest(exposure, config=config, source_manifest=source_manifest, pilot_selection=pilot)
