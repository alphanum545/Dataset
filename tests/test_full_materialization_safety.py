from __future__ import annotations

import pytest

from generator.full_materialize import FullMaterializationError, materialize_full_dataset


def _call(tmp_path, *, source_root, pilot_root, output_root):
    return materialize_full_dataset(
        {},
        {},
        {},
        {},
        source_root=source_root,
        pilot_root=pilot_root,
        output_root=output_root,
        generator_commit_sha="1" * 40,
        workers=1,
    )


def test_full_materializer_refuses_output_inside_frozen_source(tmp_path):
    source = tmp_path / "source"
    pilot = tmp_path / "pilot"
    with pytest.raises(FullMaterializationError, match="source_root"):
        _call(
            tmp_path,
            source_root=source,
            pilot_root=pilot,
            output_root=source / "full",
        )


def test_full_materializer_refuses_output_inside_frozen_pilot(tmp_path):
    source = tmp_path / "source"
    pilot = tmp_path / "pilot"
    with pytest.raises(FullMaterializationError, match="pilot_root"):
        _call(
            tmp_path,
            source_root=source,
            pilot_root=pilot,
            output_root=pilot / "full",
        )


def test_full_materializer_refuses_output_parent_of_frozen_pilot(tmp_path):
    source = tmp_path / "source"
    pilot = tmp_path / "release" / "pilot"
    with pytest.raises(FullMaterializationError, match="pilot_root"):
        _call(
            tmp_path,
            source_root=source,
            pilot_root=pilot,
            output_root=tmp_path / "release",
        )
