from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Mapping

from .canonical import canonical_json_bytes, content_sha256
from .dax import normalize_dax
from .instance import build_base_instance
from .materialize import build_qos_instance, selected_base_instance_id
from .pilot import enumerate_candidates
from .reference_schedulers import build_calibration_result

FULL_MATERIALIZATION_VERSION = "full_materialization_v1"
COHORT_MANIFEST_VERSION = "full_exposure_v1"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class FullMaterializationError(ValueError):
    """Raised when the full benchmark cannot be materialized safely."""


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> str:
    data = _json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _safe(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
        raise FullMaterializationError(f"unsafe relative path: {relative!r}")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*posix.parts)).resolve()
    if resolved_root not in resolved.parents:
        raise FullMaterializationError(f"path escapes root: {relative!r}")
    return resolved


def _verified_copy(src_root: Path, relative: str, expected_sha: str, dst: Path) -> str:
    src = _safe(src_root, relative)
    actual = _sha(src)
    if actual != expected_sha:
        raise FullMaterializationError(f"reusable pilot artifact checksum mismatch: {relative}")
    if dst.exists():
        if _sha(dst) != expected_sha:
            raise FullMaterializationError(f"existing reused artifact differs from frozen pilot: {dst}")
        return expected_sha
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp-{os.getpid()}")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    return expected_sha


def build_exposure_manifest(
    config: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    pilot_selection: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = enumerate_candidates(config, source_manifest)
    pilot_by_id = {str(e["candidate_id"]): e for e in pilot_selection["entries"]}
    dev_bases = {
        selected_base_instance_id(e, config)
        for e in pilot_selection["entries"]
        if e["split"] == "development"
    }
    holdout_bases = {
        selected_base_instance_id(e, config)
        for e in pilot_selection["entries"]
        if e["split"] == "holdout"
    }
    if dev_bases & holdout_bases:
        raise FullMaterializationError("pilot development and holdout bases overlap")

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        base_id = selected_base_instance_id(candidate, config)
        pilot = pilot_by_id.get(cid)
        if pilot is not None:
            cohort = "original_development" if pilot["split"] == "development" else "original_holdout"
            original_split = str(pilot["split"])
        elif base_id in dev_bases:
            cohort = "development_sibling"
            original_split = None
        elif base_id in holdout_bases:
            cohort = "holdout_sibling"
            original_split = None
        else:
            cohort = "expansion_evaluation"
            original_split = None
        rows.append({
            "instance_id": cid,
            "base_instance_id": base_id,
            "cohort": cohort,
            "original_split": original_split,
        })
    rows.sort(key=lambda item: item["instance_id"])
    counts = Counter(item["cohort"] for item in rows)
    expected = {
        "original_development": 160,
        "development_sibling": 317,
        "original_holdout": 40,
        "holdout_sibling": 80,
        "expansion_evaluation": 2238,
    }
    if dict(counts) != expected:
        raise FullMaterializationError(f"exposure cohort counts differ from frozen plan: {dict(counts)}")
    manifest = {
        "schema_version": 1,
        "exposure_manifest_version": COHORT_MANIFEST_VERSION,
        "dataset_version": str(config["dataset"]["version"]),
        "configuration_sha256": sha256(canonical_json_bytes(config)).hexdigest(),
        "source_manifest_sha256": sha256(canonical_json_bytes(source_manifest)).hexdigest(),
        "pilot_selection_sha256": str(pilot_selection["content_sha256"]),
        "instance_count": len(rows),
        "cohort_counts": dict(sorted(counts.items())),
        "entries": rows,
        "content_sha256": "0" * 64,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    return manifest


def _pilot_maps(pilot_manifest: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    return (
        {str(e["base_instance_id"]): e for e in pilot_manifest["base_entries"]},
        {str(e["base_instance_id"]): e for e in pilot_manifest["calibration_entries"]},
        {str(e["instance_id"]): e for e in pilot_manifest["entries"]},
    )


def materialize_full_dataset(
    config: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    pilot_selection: Mapping[str, Any],
    pilot_manifest: Mapping[str, Any],
    *,
    source_root: str | Path,
    pilot_root: str | Path,
    output_root: str | Path,
    generator_commit_sha: str,
    workers: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if workers < 1:
        raise FullMaterializationError("workers must be >= 1")
    if not _GIT_SHA.fullmatch(generator_commit_sha):
        raise FullMaterializationError(
            "generator_commit_sha must be a lowercase 40-character Git SHA"
        )
    candidates = enumerate_candidates(config, source_manifest)
    if len(candidates) != 2835:
        raise FullMaterializationError(f"candidate universe has {len(candidates)} entries, expected 2835")
    if len({str(c["candidate_id"]) for c in candidates}) != 2835:
        raise FullMaterializationError("full candidate IDs are not unique")

    exposure = build_exposure_manifest(config, source_manifest, pilot_selection)
    exposure_by_id = {e["instance_id"]: e for e in exposure["entries"]}
    pilot_base, pilot_cal, pilot_instances = _pilot_maps(pilot_manifest)
    pilot_ids = {str(e["candidate_id"]) for e in pilot_selection["entries"]}
    if pilot_ids != set(pilot_instances):
        raise FullMaterializationError("pilot materialization does not match frozen pilot selection")

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[selected_base_instance_id(candidate, config)].append(candidate)
    if len(grouped) != 945 or any(len(v) != 3 for v in grouped.values()):
        raise FullMaterializationError("full grid must contain 945 bases with exactly three QoS profiles each")

    source_path = Path(source_root)
    frozen_pilot = Path(pilot_root)
    out = Path(output_root)
    out.mkdir(parents=True, exist_ok=True)
    marker_root = out / ".complete"
    marker_root.mkdir(parents=True, exist_ok=True)

    def run_base(base_id: str, group: list[Mapping[str, Any]]) -> dict[str, Any]:
        marker = marker_root / f"{base_id}.json"
        if marker.is_file():
            payload = json.loads(marker.read_text(encoding="utf-8"))
            referenced = [payload["base"], payload["calibration"], *payload["instances"]]
            pilot_generator_sha = str(pilot_manifest["generator_commit_sha"])
            provenance_ok = all(
                item.get("generator_commit_sha")
                == (pilot_generator_sha if item.get("provenance") == "reused_pilot" else generator_commit_sha)
                for item in referenced
            )
            files_ok = all(
                _safe(out, item["path"]).is_file()
                and _sha(_safe(out, item["path"])) == item["sha256"]
                for item in referenced
            )
            if provenance_ok and files_ok:
                return payload

        representative = sorted(group, key=lambda x: str(x["candidate_id"]))[0]
        if base_id in pilot_base:
            bmeta = pilot_base[base_id]
            cmeta = pilot_cal[base_id]
            bpath = f"base/{base_id}.json"
            cpath = f"calibration/{base_id}.json"
            _verified_copy(frozen_pilot, str(bmeta["path"]), str(bmeta["sha256"]), _safe(out, bpath))
            _verified_copy(frozen_pilot, str(cmeta["path"]), str(cmeta["sha256"]), _safe(out, cpath))
            base = json.loads(_safe(out, bpath).read_text(encoding="utf-8"))
            calibration = json.loads(_safe(out, cpath).read_text(encoding="utf-8"))
            base_entry = {
                "base_instance_id": base_id,
                "path": bpath,
                "sha256": str(bmeta["sha256"]),
                "provenance": "reused_pilot",
                "generator_commit_sha": str(pilot_manifest["generator_commit_sha"]),
            }
            cal_entry = {
                "base_instance_id": base_id,
                "path": cpath,
                "sha256": str(cmeta["sha256"]),
                "candidate_set_sha256": str(cmeta["candidate_set_sha256"]),
                "provenance": "reused_pilot",
                "generator_commit_sha": str(pilot_manifest["generator_commit_sha"]),
            }
        else:
            src = _safe(source_path, str(representative["source_path"]))
            if _sha(src) != str(representative["source_sha256"]):
                raise FullMaterializationError(f"source checksum mismatch for {representative['source_path']}")
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
                raise FullMaterializationError("generated base identity mismatch")
            calibration = build_calibration_result(base, k=int(config["budget"]["calibration"]["tradeoff_solutions"]))
            bpath = f"base/{base_id}.json"
            cpath = f"calibration/{base_id}.json"
            bsha = _atomic_json(_safe(out, bpath), base)
            csha = _atomic_json(_safe(out, cpath), calibration)
            base_entry = {
                "base_instance_id": base_id,
                "path": bpath,
                "sha256": bsha,
                "provenance": "generated_full",
                "generator_commit_sha": generator_commit_sha,
            }
            cal_entry = {
                "base_instance_id": base_id,
                "path": cpath,
                "sha256": csha,
                "candidate_set_sha256": str(calibration["candidate_set_sha256"]),
                "provenance": "generated_full",
                "generator_commit_sha": generator_commit_sha,
            }

        instance_entries = []
        for candidate in sorted(group, key=lambda x: str(x["candidate_id"])):
            cid = str(candidate["candidate_id"])
            cohort = str(exposure_by_id[cid]["cohort"])
            if cid in pilot_instances:
                meta = pilot_instances[cid]
                rel = str(meta["path"])
                digest = _verified_copy(frozen_pilot, rel, str(meta["sha256"]), _safe(out, rel))
                provenance = "reused_pilot"
                artifact_generator_commit_sha = str(pilot_manifest["generator_commit_sha"])
                original_split = str(meta["split"])
            else:
                rel = f"instances/expanded/{cid}.json"
                instance = build_qos_instance(candidate, calibration, config)
                digest = _atomic_json(_safe(out, rel), instance)
                provenance = "generated_full"
                artifact_generator_commit_sha = generator_commit_sha
                original_split = None
            instance_entries.append({
                "instance_id": cid,
                "base_instance_id": base_id,
                "path": rel,
                "sha256": digest,
                "cohort": cohort,
                "original_split": original_split,
                "family": str(candidate["family"]),
                "target_task_count": int(candidate["target_task_count"]),
                "replicate_id": str(candidate["replicate_id"]),
                "source_sha256": str(candidate["source_sha256"]),
                "resource_scale": str(candidate["resource_scale"]),
                "scenario_profile": str(candidate["scenario_profile"]),
                "qos_profile": str(candidate["qos_profile"]),
                "ifc_realization_seed": int(candidate["ifc_realization_seed"]),
                "provenance": provenance,
                "generator_commit_sha": artifact_generator_commit_sha,
            })
        payload = {"base": base_entry, "calibration": cal_entry, "instances": instance_entries}
        _atomic_json(marker, payload)
        return payload

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_base, base_id, group): base_id for base_id, group in sorted(grouped.items())}
        for future in as_completed(futures):
            results.append(future.result())

    bases = sorted((r["base"] for r in results), key=lambda x: x["base_instance_id"])
    calibrations = sorted((r["calibration"] for r in results), key=lambda x: x["base_instance_id"])
    instances = sorted((i for r in results for i in r["instances"]), key=lambda x: x["instance_id"])
    if len(bases) != 945 or len(calibrations) != 945 or len(instances) != 2835:
        raise FullMaterializationError("deterministic reduction is incomplete")
    if len({i["instance_id"] for i in instances}) != 2835:
        raise FullMaterializationError("deterministic reduction contains duplicate instance IDs")

    cohort_counts = Counter(i["cohort"] for i in instances)
    manifest = {
        "schema_version": 1,
        "materialization_version": FULL_MATERIALIZATION_VERSION,
        "dataset_version": str(config["dataset"]["version"]),
        "generator_commit_sha": generator_commit_sha,
        "configuration_sha256": sha256(canonical_json_bytes(config)).hexdigest(),
        "source_manifest_sha256": sha256(canonical_json_bytes(source_manifest)).hexdigest(),
        "pilot_selection_sha256": str(pilot_selection["content_sha256"]),
        "pilot_materialization_sha256": str(pilot_manifest["content_sha256"]),
        "exposure_manifest_sha256": str(exposure["content_sha256"]),
        "base_instance_count": len(bases),
        "calibration_count": len(calibrations),
        "instance_count": len(instances),
        "cohort_counts": dict(sorted(cohort_counts.items())),
        "base_entries": bases,
        "calibration_entries": calibrations,
        "entries": instances,
        "content_sha256": "0" * 64,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    return manifest, exposure
