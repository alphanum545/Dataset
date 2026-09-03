from __future__ import annotations

from pathlib import Path

import pytest

from generator.acquire import AcquisitionError, CommandResult, acquire_source_workflows


def dax(task_count: int, *, marker: str) -> bytes:
    jobs = []
    children = []
    for index in range(task_count):
        task_id = f"ID{index:05d}"
        uses = ""
        if index < task_count - 1:
            uses += f'<uses file="f{index}-{marker}.dat" link="output" size="10" />'
        if index > 0:
            uses += f'<uses file="f{index-1}-{marker}.dat" link="input" size="10" />'
        jobs.append(f'<job id="{task_id}" runtime="1.0">{uses}</job>')
        if index > 0:
            children.append(f'<child ref="{task_id}"><parent ref="ID{index-1:05d}" /></child>')
    return ("<adag>" + "".join(jobs) + "".join(children) + "</adag>").encode()


def base_config() -> dict:
    return {
        "source_workflows": {
            "provider": "pegasus",
            "repository": "pegasus-isi/WorkflowGenerator",
            "implementation": "bharathi",
            "pinned_commit": "bb1f8d43fe203f5c2cb209540531998af52000ea",
            "expected_raw_artifacts": 3,
            "acquisition": {"max_attempts_per_replicate": 4},
        },
        "workflows": {
            "families": ["montage"],
            "requested_task_counts": [2],
            "source_replicates": ["r01", "r02", "r03"],
            "reference_mips": 1000,
        },
    }


def upstream(tmp_path: Path) -> Path:
    root = tmp_path / "upstream"
    executable = root / "bin" / "AppGenerator"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    return root


def test_acquisition_accepts_first_three_distinct_structurally_valid_exact_outputs(tmp_path):
    outputs = iter([
        dax(1, marker="wrong-count"),
        dax(2, marker="one"),
        dax(2, marker="one"),
        dax(2, marker="two"),
        dax(2, marker="three"),
    ])

    def runner(command: list[str], cwd: Path) -> CommandResult:
        assert command[:4] == ["bin/AppGenerator", "-a", "MONTAGE", "-n"]
        assert command[4] == "2"
        return CommandResult(stdout=next(outputs), stderr=b"", returncode=0)

    manifest = acquire_source_workflows(
        base_config(),
        upstream_dir=upstream(tmp_path),
        output_root=tmp_path / "source_workflows",
        manifest_path=tmp_path / "manifests" / "source.json",
        runner=runner,
    )

    assert manifest["artifact_count"] == 3
    assert [entry["acquisition_attempt"] for entry in manifest["entries"]] == [2, 2, 1]
    assert len({entry["sha256"] for entry in manifest["entries"]}) == 3
    assert [entry["replicate_id"] for entry in manifest["entries"]] == ["r01", "r02", "r03"]
    for entry in manifest["entries"]:
        assert (tmp_path / "source_workflows" / entry["path"]).is_file()


def test_acquisition_rejects_dimension_count_mismatch(tmp_path):
    config = base_config()
    config["source_workflows"]["expected_raw_artifacts"] = 105
    with pytest.raises(AcquisitionError, match="dimensions imply 3"):
        acquire_source_workflows(
            config,
            upstream_dir=upstream(tmp_path),
            output_root=tmp_path / "source_workflows",
            manifest_path=tmp_path / "manifest.json",
        )


def test_acquisition_fails_after_bounded_invalid_attempts(tmp_path):
    config = base_config()
    config["workflows"]["source_replicates"] = ["r01"]
    config["source_workflows"]["expected_raw_artifacts"] = 1
    config["source_workflows"]["acquisition"]["max_attempts_per_replicate"] = 2

    def runner(command: list[str], cwd: Path) -> CommandResult:
        return CommandResult(stdout=dax(1, marker="bad"), stderr=b"", returncode=0)

    with pytest.raises(AcquisitionError, match="in 2 attempts"):
        acquire_source_workflows(
            config,
            upstream_dir=upstream(tmp_path),
            output_root=tmp_path / "source_workflows",
            manifest_path=tmp_path / "manifest.json",
            runner=runner,
        )
