from __future__ import annotations

from hashlib import sha256
import json

from generator.full_materialize import _load_completion_marker


def _entry(path, data, provenance, generator_sha):
    path.write_bytes(data)
    return {
        "path": path.name,
        "sha256": sha256(data).hexdigest(),
        "provenance": provenance,
        "generator_commit_sha": generator_sha,
    }


def test_completion_marker_accepts_only_verified_current_artifacts(tmp_path):
    pilot_sha = "1" * 40
    full_sha = "2" * 40
    base = _entry(tmp_path / "base.json", b"base", "reused_pilot", pilot_sha)
    calibration = _entry(tmp_path / "calibration.json", b"cal", "generated_full", full_sha)
    instance = _entry(tmp_path / "instance.json", b"qos", "generated_full", full_sha)
    marker = tmp_path / "marker.json"
    payload = {"base": base, "calibration": calibration, "instances": [instance]}
    marker.write_text(json.dumps(payload), encoding="utf-8")

    assert _load_completion_marker(
        marker,
        output_root=tmp_path,
        pilot_generator_sha=pilot_sha,
        generator_commit_sha=full_sha,
    ) == payload


def test_completion_marker_ignores_corrupt_json(tmp_path):
    marker = tmp_path / "marker.json"
    marker.write_text("{not-json", encoding="utf-8")
    assert _load_completion_marker(
        marker,
        output_root=tmp_path,
        pilot_generator_sha="1" * 40,
        generator_commit_sha="2" * 40,
    ) is None


def test_completion_marker_invalidates_old_generator_checkpoint(tmp_path):
    old_sha = "3" * 40
    current_sha = "4" * 40
    entry = _entry(tmp_path / "base.json", b"base", "generated_full", old_sha)
    marker = tmp_path / "marker.json"
    marker.write_text(
        json.dumps({"base": entry, "calibration": entry, "instances": [entry]}),
        encoding="utf-8",
    )
    assert _load_completion_marker(
        marker,
        output_root=tmp_path,
        pilot_generator_sha="1" * 40,
        generator_commit_sha=current_sha,
    ) is None
