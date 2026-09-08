from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Mapping

from generator.config import load_config
from generator.dax import normalize_dax
from generator.full_materialize import _GIT_SHA, _atomic_json, _safe, _sha
from generator.instance import build_base_instance
from generator.materialize import build_qos_instance, selected_base_instance_id
from generator.pilot import enumerate_candidates
from generator.reference_schedulers import build_calibration_result


# Integer-only empirical load weights. They affect orchestration only, never dataset content.
_TASK_WEIGHTS = {
    60: 1,
    100: 2,
    200: 5,
    400: 14,
    600: 27,
    800: 45,
    1000: 65,
}
_FAMILY_WEIGHTS = {
    "CyberShake": 115,
    "Montage": 105,
    "Genome": 100,
    "SIPHT": 90,
    "LIGO": 90,
}
_SCALE_WEIGHTS = {"S01": 80, "S02": 100, "S03": 120}


class ShardError(ValueError):
    """Raised when deterministic sharded materialization cannot proceed safely."""


def _weight(candidate: Mapping[str, Any]) -> int:
    return (
        _TASK_WEIGHTS[int(candidate["target_task_count"])]
        * _FAMILY_WEIGHTS[str(candidate["family"])]
        * _SCALE_WEIGHTS[str(candidate["resource_scale"])]
    )


def build_shard_plan(
    config: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    pilot_selection: Mapping[str, Any],
    *,
    shard_count: int,
) -> list[list[tuple[str, list[Mapping[str, Any]], int]]]:
    if shard_count < 1:
        raise ShardError("shard_count must be >= 1")

    candidates = enumerate_candidates(config, source_manifest)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[selected_base_instance_id(candidate, config)].append(candidate)
    if len(grouped) != 945 or any(len(group) != 3 for group in grouped.values()):
        raise ShardError("candidate universe must contain 945 bases with three QoS profiles each")

    pilot_bases = {
        selected_base_instance_id(entry, config)
        for entry in pilot_selection["entries"]
    }
    if len(pilot_bases) != 199:
        raise ShardError(f"frozen pilot contains {len(pilot_bases)} unique bases, expected 199")

    work: list[tuple[str, list[Mapping[str, Any]], int]] = []
    for base_id, group in grouped.items():
        if base_id in pilot_bases:
            continue
        representative = min(group, key=lambda item: str(item["candidate_id"]))
        work.append((base_id, group, _weight(representative)))
    if len(work) != 746:
        raise ShardError(f"expansion contains {len(work)} bases, expected 746")

    # Longest-processing-time allocation with deterministic tie-breaking.
    bins: list[list[tuple[str, list[Mapping[str, Any]], int]]] = [
        [] for _ in range(shard_count)
    ]
    loads = [0] * shard_count
    for item in sorted(work, key=lambda row: (-row[2], row[0])):
        shard_index = min(range(shard_count), key=lambda idx: (loads[idx], idx))
        bins[shard_index].append(item)
        loads[shard_index] += item[2]

    assigned = [base_id for shard in bins for base_id, _, _ in shard]
    if len(assigned) != 746 or len(set(assigned)) != 746:
        raise ShardError("shard plan must assign every expansion base exactly once")
    return bins


def _materialize_base(
    *,
    base_id: str,
    group: list[Mapping[str, Any]],
    config: Mapping[str, Any],
    source_root: Path,
    output_root: Path,
    generator_commit_sha: str,
) -> dict[str, Any]:
    representative = min(group, key=lambda item: str(item["candidate_id"]))
    src = _safe(source_root, str(representative["source_path"]))
    if _sha(src) != str(representative["source_sha256"]):
        raise ShardError(f"source checksum mismatch for {representative['source_path']}")

    workflow = normalize_dax(
        src,
        family=str(representative["family"]),
        target_task_count=int(representative["target_task_count"]),
        replicate_id=str(representative["replicate_id"]),
        reference_mips=int(config["workflows"]["reference_mips"]),
    )
    base = build_base_instance(
        workflow,
        dict(config),
        scale=str(representative["resource_scale"]),
        scenario=str(representative["scenario_profile"]),
        seed=int(representative["ifc_realization_seed"]),
    )
    if base["metadata"]["base_instance_id"] != base_id:
        raise ShardError(f"generated base identity mismatch for {base_id}")

    calibration = build_calibration_result(
        base,
        k=int(config["budget"]["calibration"]["tradeoff_solutions"]),
    )
    base_path = f"base/{base_id}.json"
    calibration_path = f"calibration/{base_id}.json"
    base_sha = _atomic_json(_safe(output_root, base_path), base)
    calibration_sha = _atomic_json(_safe(output_root, calibration_path), calibration)

    base_entry = {
        "base_instance_id": base_id,
        "path": base_path,
        "sha256": base_sha,
        "provenance": "generated_full",
        "generator_commit_sha": generator_commit_sha,
    }
    calibration_entry = {
        "base_instance_id": base_id,
        "path": calibration_path,
        "sha256": calibration_sha,
        "candidate_set_sha256": str(calibration["candidate_set_sha256"]),
        "provenance": "generated_full",
        "generator_commit_sha": generator_commit_sha,
    }

    instance_entries: list[dict[str, Any]] = []
    for candidate in sorted(group, key=lambda item: str(item["candidate_id"])):
        candidate_id = str(candidate["candidate_id"])
        relative = f"instances/expanded/{candidate_id}.json"
        instance = build_qos_instance(candidate, calibration, config)
        digest = _atomic_json(_safe(output_root, relative), instance)
        instance_entries.append(
            {
                "instance_id": candidate_id,
                "base_instance_id": base_id,
                "path": relative,
                "sha256": digest,
                "cohort": "expansion_evaluation",
                "original_split": None,
                "family": str(candidate["family"]),
                "target_task_count": int(candidate["target_task_count"]),
                "replicate_id": str(candidate["replicate_id"]),
                "source_sha256": str(candidate["source_sha256"]),
                "resource_scale": str(candidate["resource_scale"]),
                "scenario_profile": str(candidate["scenario_profile"]),
                "qos_profile": str(candidate["qos_profile"]),
                "ifc_realization_seed": int(candidate["ifc_realization_seed"]),
                "provenance": "generated_full",
                "generator_commit_sha": generator_commit_sha,
            }
        )

    marker = output_root / ".complete" / f"{base_id}.json"
    payload = {
        "base": base_entry,
        "calibration": calibration_entry,
        "instances": instance_entries,
    }
    _atomic_json(marker, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize one deterministic expansion shard")
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--pilot-selection", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--generator-commit-sha", required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--plan-only", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not _GIT_SHA.fullmatch(args.generator_commit_sha):
        raise ShardError("generator_commit_sha must be a lowercase 40-character Git SHA")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        raise ShardError("shard_index must satisfy 0 <= shard_index < shard_count")

    config = load_config(args.config)
    source_manifest = json.loads(Path(args.source_manifest).read_text(encoding="utf-8"))
    pilot_selection = json.loads(Path(args.pilot_selection).read_text(encoding="utf-8"))
    plan = build_shard_plan(
        config,
        source_manifest,
        pilot_selection,
        shard_count=args.shard_count,
    )
    shard = plan[args.shard_index]
    output_root = Path(args.output_root).resolve()
    source_root = Path(args.source_root).resolve()
    if output_root == source_root or output_root in source_root.parents or source_root in output_root.parents:
        raise ShardError("output_root must not overlap immutable source_root")

    if not args.plan_only:
        output_root.mkdir(parents=True, exist_ok=True)
        for base_id, group, _ in shard:
            _materialize_base(
                base_id=base_id,
                group=group,
                config=config,
                source_root=source_root,
                output_root=output_root,
                generator_commit_sha=args.generator_commit_sha,
            )

    loads = [sum(item[2] for item in bucket) for bucket in plan]
    counts = [len(bucket) for bucket in plan]
    summary = {
        "shard_count": args.shard_count,
        "shard_index": args.shard_index,
        "assigned_base_count": len(shard),
        "assigned_instance_count": len(shard) * 3,
        "assigned_weight": sum(item[2] for item in shard),
        "all_shard_base_counts": counts,
        "all_shard_weights": loads,
        "total_expansion_base_count": sum(counts),
        "total_expansion_instance_count": sum(counts) * 3,
        "generator_commit_sha": args.generator_commit_sha,
        "status": "planned" if args.plan_only else "materialized",
        "base_ids": sorted(base_id for base_id, _, _ in shard),
    }
    if summary["total_expansion_base_count"] != 746:
        raise ShardError("shard summary does not cover 746 expansion bases")
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "base_ids"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
