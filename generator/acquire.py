from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Callable, Iterable

from .config import load_config
from .dax import DaxValidationError, normalize_dax


FAMILY_TO_APPLICATION = {
    "montage": "MONTAGE",
    "cybershake": "CYBERSHAKE",
    "ligo": "LIGO",
    "sipht": "SIPHT",
    "genome": "GENOME",
}


class AcquisitionError(RuntimeError):
    """Raised when the pinned upstream source set cannot be acquired safely."""


@dataclass(frozen=True)
class CommandResult:
    stdout: bytes
    stderr: bytes
    returncode: int


Runner = Callable[[list[str], Path], CommandResult]


def _default_runner(command: list[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
    )
    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def _validate_upstream_dir(upstream_dir: Path) -> Path:
    executable = upstream_dir / "bin" / "AppGenerator"
    if not executable.is_file():
        raise AcquisitionError(f"missing pinned Bharathi AppGenerator: {executable}")
    return executable


def _request_step(family: str) -> int:
    # LIGO rejects odd --numjobs values; the benchmark target sizes are even.
    return 2 if family == "ligo" else 1


def _attempts_per_request(acquisition_cfg: dict, family: str) -> int:
    configured = acquisition_cfg.get("attempts_per_requested_numjobs")
    if isinstance(configured, dict):
        value = configured.get(family, configured.get("default"))
    elif configured is not None:
        value = configured
    else:
        value = 5 if family == "ligo" else 2
    if value is None or int(value) <= 0:
        raise AcquisitionError("attempts_per_requested_numjobs must resolve to > 0")
    return int(value)


def _genome_exact_request(target: int, acquisition_cfg: dict) -> tuple[list[str], dict]:
    lanes = int(acquisition_cfg.get("genome_exact_lanes", 1))
    if lanes != 1:
        raise AcquisitionError("core v1 Genome exact acquisition requires genome_exact_lanes = 1")
    if target < 8 or target % 4 != 0:
        raise AcquisitionError(
            f"Genome exact single-lane acquisition requires target >= 8 and divisible by 4; got {target}"
        )
    sequences = target // 4 - 1
    return ["-l", str(lanes), "-s", str(sequences)], {
        "request_mode": "genome_lanes_sequences_exact",
        "requested_numjobs": None,
        "requested_lanes": lanes,
        "requested_sequences": sequences,
    }


def _numjobs_request(
    *,
    family: str,
    target: int,
    attempt: int,
    attempts_per_requested_numjobs: int,
) -> tuple[list[str], dict]:
    request_index = (attempt - 1) // attempts_per_requested_numjobs
    requested_numjobs = target + request_index * _request_step(family)
    return ["-n", str(requested_numjobs)], {
        "request_mode": "numjobs_search",
        "requested_numjobs": requested_numjobs,
        "requested_lanes": None,
        "requested_sequences": None,
    }


def _acquire_one(
    *,
    executable: Path,
    upstream_dir: Path,
    family: str,
    target: int,
    replicate_id: str,
    max_attempts: int,
    attempts_per_requested_numjobs: int,
    acquisition_cfg: dict,
    used_checksums: set[str],
    reference_mips: int,
    runner: Runner,
) -> tuple[bytes, dict]:
    application = FAMILY_TO_APPLICATION.get(family)
    if application is None:
        raise AcquisitionError(f"unsupported workflow family {family!r}")

    failures: list[str] = []
    relative_executable = str(executable.relative_to(upstream_dir))
    for attempt in range(1, max_attempts + 1):
        if family == "genome":
            request_args, request_metadata = _genome_exact_request(target, acquisition_cfg)
        else:
            request_args, request_metadata = _numjobs_request(
                family=family,
                target=target,
                attempt=attempt,
                attempts_per_requested_numjobs=attempts_per_requested_numjobs,
            )

        command = [relative_executable, "-a", application, *request_args]
        request_label = (
            f"lanes={request_metadata['requested_lanes']},sequences={request_metadata['requested_sequences']}"
            if family == "genome"
            else f"requested {request_metadata['requested_numjobs']}"
        )
        try:
            result = runner(command, upstream_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            failures.append(
                f"attempt {attempt} ({request_label}): process error {type(exc).__name__}: {exc}"
            )
            continue
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            failures.append(
                f"attempt {attempt} ({request_label}): exit {result.returncode}: {stderr[:240]}"
            )
            continue

        raw = result.stdout
        checksum = sha256(raw).hexdigest()
        if checksum in used_checksums:
            failures.append(f"attempt {attempt} ({request_label}): duplicate checksum {checksum}")
            continue
        try:
            normalized = normalize_dax(
                raw,
                family=family,
                target_task_count=target,
                replicate_id=replicate_id,
                reference_mips=reference_mips,
            )
        except DaxValidationError as exc:
            failures.append(f"attempt {attempt} ({request_label}): {exc}")
            continue

        return raw, {
            "family": family,
            "application": application,
            "target_task_count": target,
            **request_metadata,
            "actual_task_count": normalized["metadata"]["actual_task_count"],
            "replicate_id": replicate_id,
            "acquisition_attempt": attempt,
            "sha256": checksum,
            "command": command,
        }

    detail = failures[-5:]
    raise AcquisitionError(
        f"unable to acquire {family}/{target}/{replicate_id} in {max_attempts} attempts; "
        f"last failures={detail!r}"
    )


def acquire_source_workflows(
    config: dict,
    *,
    upstream_dir: Path,
    output_root: Path,
    manifest_path: Path,
    runner: Runner = _default_runner,
) -> dict:
    source_cfg = config["source_workflows"]
    workflows = config["workflows"]
    executable = _validate_upstream_dir(upstream_dir)

    families = list(workflows["families"])
    targets = [int(value) for value in workflows["requested_task_counts"]]
    replicates = list(workflows["source_replicates"])
    acquisition_cfg = source_cfg["acquisition"]
    max_attempts = int(acquisition_cfg["max_attempts_per_replicate"])
    reference_mips = int(workflows["reference_mips"])
    pinned_commit = str(source_cfg["pinned_commit"])
    source_namespace = f"pegasus-bharathi-{pinned_commit[:8]}"

    entries: list[dict] = []
    expected = len(families) * len(targets) * len(replicates)
    configured_expected = int(source_cfg["expected_raw_artifacts"])
    if expected != configured_expected:
        raise AcquisitionError(
            f"configured expected_raw_artifacts={configured_expected} but dimensions imply {expected}"
        )

    for family in families:
        attempts_per_requested_numjobs = _attempts_per_request(acquisition_cfg, family)
        used_checksums_by_target: dict[int, set[str]] = {target: set() for target in targets}
        for target in targets:
            for replicate_id in replicates:
                raw, metadata = _acquire_one(
                    executable=executable,
                    upstream_dir=upstream_dir,
                    family=family,
                    target=target,
                    replicate_id=replicate_id,
                    max_attempts=max_attempts,
                    attempts_per_requested_numjobs=attempts_per_requested_numjobs,
                    acquisition_cfg=acquisition_cfg,
                    used_checksums=used_checksums_by_target[target],
                    reference_mips=reference_mips,
                    runner=runner,
                )
                used_checksums_by_target[target].add(metadata["sha256"])
                relative_path = Path(source_namespace) / family / f"{target:04d}" / f"{replicate_id}.dax"
                destination = output_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                entries.append({**metadata, "path": relative_path.as_posix()})

    manifest = {
        "schema_version": 1,
        "provider": source_cfg["provider"],
        "repository": source_cfg["repository"],
        "implementation": source_cfg["implementation"],
        "pinned_commit": pinned_commit,
        "artifact_count": len(entries),
        "entries": entries,
    }
    if len(entries) != configured_expected:
        raise AcquisitionError(
            f"acquired {len(entries)} artifacts but expected {configured_expected}"
        )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_canonical_json(manifest), encoding="utf-8")
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="ifc-acquire-sources")
    parser.add_argument("--config", required=True)
    parser.add_argument("--upstream-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = load_config(args.config)
    acquire_source_workflows(
        config,
        upstream_dir=Path(args.upstream_dir),
        output_root=Path(args.output_root),
        manifest_path=Path(args.manifest),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
