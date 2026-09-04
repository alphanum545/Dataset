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
            "acquisition": {
                "max_attempts_per_replicate": 8,
                "attempts_per_requested_numjobs": 2,
                "genome_exact_lanes": 1,
            },
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
    requests: list[int] = []

    def runner(command: list[str], cwd: Path) -> CommandResult:
        requests.append(int(command[4]))
        return CommandResult(stdout=next(outputs), stderr=b"", returncode=0)

    manifest = acquire_source_workflows(
        base_config(),
        upstream_dir=upstream(tmp_path),
        output_root=tmp_path / "source_workflows",
        manifest_path=tmp_path / "manifests" / "source.json",
        runner=runner,
    )

    assert manifest["artifact_count"] == 3
    assert [entry["requested_numjobs"] for entry in manifest["entries"]] == [2, 2, 2]
    assert requests == [2, 2, 2, 2, 2]
    assert len({entry["sha256"] for entry in manifest["entries"]}) == 3


def test_acquisition_retries_same_request_before_searching_upward(tmp_path):
    config = base_config()
    config["workflows"]["source_replicates"] = ["r01"]
    config["source_workflows"]["expected_raw_artifacts"] = 1
    requests: list[int] = []

    def runner(command: list[str], cwd: Path) -> CommandResult:
        requested = int(command[4])
        requests.append(requested)
        if len(requests) == 1:
            return CommandResult(stdout=b"", stderr=b"transient", returncode=1)
        return CommandResult(stdout=dax(2, marker="ok"), stderr=b"", returncode=0)

    manifest = acquire_source_workflows(
        config,
        upstream_dir=upstream(tmp_path),
        output_root=tmp_path / "source_workflows",
        manifest_path=tmp_path / "manifest.json",
        runner=runner,
    )
    assert requests == [2, 2]
    assert manifest["entries"][0]["requested_numjobs"] == 2


def test_acquisition_searches_upward_after_retry_budget(tmp_path):
    config = base_config()
    config["workflows"]["source_replicates"] = ["r01"]
    config["source_workflows"]["expected_raw_artifacts"] = 1
    requests: list[int] = []

    def runner(command: list[str], cwd: Path) -> CommandResult:
        requested = int(command[4])
        requests.append(requested)
        actual = 2 if requested == 4 else 1
        return CommandResult(stdout=dax(actual, marker=f"req-{requested}-{len(requests)}"), stderr=b"", returncode=0)

    manifest = acquire_source_workflows(
        config,
        upstream_dir=upstream(tmp_path),
        output_root=tmp_path / "source_workflows",
        manifest_path=tmp_path / "manifest.json",
        runner=runner,
    )
    assert requests == [2, 2, 3, 3, 4]
    assert manifest["entries"][0]["requested_numjobs"] == 4
    assert manifest["entries"][0]["actual_task_count"] == 2


def test_ligo_search_never_requests_odd_numjobs(tmp_path):
    config = base_config()
    config["workflows"]["families"] = ["ligo"]
    config["workflows"]["source_replicates"] = ["r01"]
    config["source_workflows"]["expected_raw_artifacts"] = 1
    requests: list[int] = []

    def runner(command: list[str], cwd: Path) -> CommandResult:
        requested = int(command[4])
        requests.append(requested)
        actual = 2 if requested == 6 else 1
        return CommandResult(stdout=dax(actual, marker=f"req-{requested}-{len(requests)}"), stderr=b"", returncode=0)

    manifest = acquire_source_workflows(
        config,
        upstream_dir=upstream(tmp_path),
        output_root=tmp_path / "source_workflows",
        manifest_path=tmp_path / "manifest.json",
        runner=runner,
    )
    assert requests == [2, 2, 4, 4, 6]
    assert all(request % 2 == 0 for request in requests)
    assert manifest["entries"][0]["requested_numjobs"] == 6


def test_genome_uses_exact_lane_sequence_request(tmp_path):
    config = base_config()
    config["workflows"]["families"] = ["genome"]
    config["workflows"]["requested_task_counts"] = [200]
    config["workflows"]["source_replicates"] = ["r01"]
    config["source_workflows"]["expected_raw_artifacts"] = 1
    commands: list[list[str]] = []

    def runner(command: list[str], cwd: Path) -> CommandResult:
        commands.append(command)
        return CommandResult(stdout=dax(200, marker="genome"), stderr=b"", returncode=0)

    manifest = acquire_source_workflows(
        config,
        upstream_dir=upstream(tmp_path),
        output_root=tmp_path / "source_workflows",
        manifest_path=tmp_path / "manifest.json",
        runner=runner,
    )

    assert commands == [["bin/AppGenerator", "-a", "GENOME", "-l", "1", "-s", "49"]]
    entry = manifest["entries"][0]
    assert entry["request_mode"] == "genome_lanes_sequences_exact"
    assert entry["requested_numjobs"] is None
    assert entry["requested_lanes"] == 1
    assert entry["requested_sequences"] == 49
    assert entry["actual_task_count"] == 200


def test_genome_rejects_target_not_representable_by_exact_single_lane_mode(tmp_path):
    config = base_config()
    config["workflows"]["families"] = ["genome"]
    config["workflows"]["requested_task_counts"] = [50]
    config["workflows"]["source_replicates"] = ["r01"]
    config["source_workflows"]["expected_raw_artifacts"] = 1

    with pytest.raises(AcquisitionError, match="divisible by 4"):
        acquire_source_workflows(
            config,
            upstream_dir=upstream(tmp_path),
            output_root=tmp_path / "source_workflows",
            manifest_path=tmp_path / "manifest.json",
            runner=lambda command, cwd: CommandResult(stdout=b"", stderr=b"", returncode=0),
        )


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
