"""Unseen-workflow evaluation set v1: source acquisition, entry enumeration, materialization.

Additive to v1. Nothing here reads or writes the v1 pilot selection, the holdout, or the
frozen v1 source tree; the IFC model is the unchanged v1 model configuration.

CLI (all steps are meant to run in CI):

  python -m generator.unseen acquire-bharathi --upstream-dir <bharathi> --output-root source_workflows --manifest <m.json>
  python -m generator.unseen acquire-wfcommons --output-root source_workflows --manifest <m.json> [--family F --target N]
  python -m generator.unseen merge-manifests --inputs "<glob>" --output manifests/source-workflows-unseen-v1.json
  python -m generator.unseen entries --source-manifest manifests/source-workflows-unseen-v1.json --output <entries.json>
"""
from __future__ import annotations

import argparse
import glob
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .acquire import (
    AcquisitionError,
    _acquire_one,
    _attempts_per_request,
    _default_runner,
    _validate_upstream_dir,
)
from .canonical import content_sha256
from .config import load_config
from .identity import base_instance_id, workflow_id
from .wfformat import WfFormatValidationError, normalize_source, normalize_wfformat

UNSEEN_CONFIG = "config/unseen-v1.yaml"


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def load_unseen_config(path: str | Path = UNSEEN_CONFIG) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("set_id") != "ifc-unseen-v1":
        raise ValueError("not an ifc-unseen-v1 configuration")
    seeds = raw["source_to_ifc_seed"]
    for rep in [*raw["new_replicates"]["replicates"], *raw["new_families"]["replicates"]]:
        if rep not in seeds:
            raise ValueError(f"no IFC seed for replicate {rep!r}")
    overlap = set(raw["new_families"]["families"]) & set(raw["new_replicates"]["families"])
    if overlap:
        raise ValueError(f"new families must not reuse v1 family tokens: {sorted(overlap)}")
    return raw


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- acquisition
def acquire_bharathi(
    unseen: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    upstream_dir: Path,
    output_root: Path,
    v1_manifest: Mapping[str, Any],
    runner=_default_runner,
    families: Iterable[str] | None = None,
    targets: Iterable[int] | None = None,
) -> list[dict]:
    """New r04 replicates with the unchanged v1 Bharathi request policy.

    Each new artifact must be checksum-distinct from the frozen r01-r03 artifacts of the
    same family and size.
    """
    spec = unseen["new_replicates"]
    if spec["pinned_commit"] != model["source_workflows"]["pinned_commit"]:
        raise AcquisitionError("new replicates must use the v1-pinned Bharathi commit")
    executable = _validate_upstream_dir(upstream_dir)
    acquisition_cfg = model["source_workflows"]["acquisition"]
    max_attempts = int(acquisition_cfg["max_attempts_per_replicate"])
    reference_mips = int(model["workflows"]["reference_mips"])
    namespace = f"{unseen['source_root_namespace']}/pegasus-bharathi-{spec['pinned_commit'][:8]}"
    frozen: dict[tuple[str, int], set[str]] = {}
    for e in v1_manifest["entries"]:
        frozen.setdefault((e["family"], int(e["target_task_count"])), set()).add(e["sha256"])

    entries = []
    for family in (families or spec["families"]):
        per_request = _attempts_per_request(acquisition_cfg, family)
        for target in (targets or spec["requested_task_counts"]):
            used = set(frozen.get((family, int(target)), set()))
            for replicate_id in spec["replicates"]:
                raw, meta = _acquire_one(
                    executable=executable, upstream_dir=upstream_dir, family=family,
                    target=int(target), replicate_id=replicate_id, max_attempts=max_attempts,
                    attempts_per_requested_numjobs=per_request, acquisition_cfg=acquisition_cfg,
                    used_checksums=used, reference_mips=reference_mips, runner=runner,
                )
                used.add(meta["sha256"])
                rel = Path(namespace) / family / f"{int(target):04d}" / f"{replicate_id}.dax"
                (output_root / rel).parent.mkdir(parents=True, exist_ok=True)
                (output_root / rel).write_bytes(raw)
                entries.append({**meta, "provider": "pegasus", "source_format": "dax",
                                "kind": "new_replicate", "path": rel.as_posix()})
    return entries


def attempt_seed(family: str, target: int, replicate_id: str, attempt: int) -> int:
    token = f"ifc-unseen-v1|{family}|{target}|{replicate_id}|{attempt}".encode()
    return int.from_bytes(sha256(token).digest()[:4], "big")


def _wfcommons_emit(recipe_name: str, num_tasks: int, seed: int) -> bytes:
    """Generate one WfChef workflow with seeded global RNGs and return its JSON bytes."""
    import random
    import tempfile

    import numpy as np
    import wfcommons.wfchef.recipes as recipes
    from wfcommons import WorkflowGenerator

    random.seed(seed)
    np.random.seed(seed)
    recipe = getattr(recipes, recipe_name).from_num_tasks(num_tasks=num_tasks)
    workflow = WorkflowGenerator(recipe).build_workflow()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "wf.json"
        workflow.write_json(out)
        return out.read_bytes()


def acquire_wfcommons_one(
    *,
    family: str,
    recipe_name: str,
    target: int,
    replicate_id: str,
    policy: Mapping[str, Any],
    used_checksums: set[str],
    reference_mips: int,
    emit=_wfcommons_emit,
) -> tuple[bytes, dict]:
    offset = int(policy["request_offset"])
    per_request = int(policy["attempts_per_request"])
    max_attempts = int(policy["max_attempts_per_replicate"])
    failures: list[str] = []
    for attempt in range(1, max_attempts + 1):
        requested = target + offset + (attempt - 1) // per_request
        seed = attempt_seed(family, target, replicate_id, attempt)
        try:
            raw = emit(recipe_name, requested, seed)
        except Exception as exc:  # upstream generator failure is a rejected attempt
            failures.append(f"attempt {attempt} (num_tasks {requested}): {type(exc).__name__}: {exc}"[:240])
            continue
        checksum = sha256(raw).hexdigest()
        if checksum in used_checksums:
            failures.append(f"attempt {attempt}: duplicate checksum")
            continue
        try:
            normalized = normalize_wfformat(raw, family=family, target_task_count=target,
                                            replicate_id=replicate_id, reference_mips=reference_mips)
        except WfFormatValidationError as exc:
            failures.append(f"attempt {attempt} (num_tasks {requested}): {exc}"[:240])
            continue
        return raw, {
            "family": family,
            "recipe": recipe_name,
            "target_task_count": target,
            "request_mode": "wfchef_num_tasks_search",
            "requested_num_tasks": requested,
            "rng_seed": seed,
            "actual_task_count": normalized["metadata"]["actual_task_count"],
            "replicate_id": replicate_id,
            "acquisition_attempt": attempt,
            "sha256": checksum,
        }
    raise AcquisitionError(
        f"unable to acquire {family}/{target}/{replicate_id} in {max_attempts} attempts; "
        f"last failures={failures[-5:]!r}"
    )


def acquire_wfcommons(
    unseen: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    output_root: Path,
    families: Iterable[str] | None = None,
    targets: Iterable[int] | None = None,
    emit=_wfcommons_emit,
) -> list[dict]:
    spec = unseen["new_families"]
    namespace = f"{unseen['source_root_namespace']}/wfcommons-{spec['pinned_commit'][:8]}"
    reference_mips = int(model["workflows"]["reference_mips"])
    entries = []
    for family in (families or spec["families"]):
        fam = spec["families"][family]
        for target in fam["requested_task_counts"]:
            if targets and int(target) not in {int(t) for t in targets}:
                continue
            used: set[str] = set()
            for replicate_id in spec["replicates"]:
                raw, meta = acquire_wfcommons_one(
                    family=family, recipe_name=fam["recipe"], target=int(target),
                    replicate_id=replicate_id, policy=spec["acquisition"],
                    used_checksums=used, reference_mips=reference_mips, emit=emit,
                )
                used.add(meta["sha256"])
                rel = Path(namespace) / family / f"{int(target):04d}" / f"{replicate_id}.json"
                (output_root / rel).parent.mkdir(parents=True, exist_ok=True)
                (output_root / rel).write_bytes(raw)
                entries.append({**meta, "provider": "wfcommons", "source_format": "wfformat",
                                "repository": spec["repository"], "pinned_commit": spec["pinned_commit"],
                                "kind": "new_family", "path": rel.as_posix()})
    return entries


def expected_source_count(unseen: Mapping[str, Any]) -> int:
    rep = unseen["new_replicates"]
    n = len(rep["families"]) * len(rep["requested_task_counts"]) * len(rep["replicates"])
    fam = unseen["new_families"]
    n += sum(len(f["requested_task_counts"]) for f in fam["families"].values()) * len(fam["replicates"])
    return n


def merge_manifests(unseen: Mapping[str, Any], parts: list[Mapping[str, Any]], *,
                    unseen_config_sha256: str, model_config_sha256: str) -> dict:
    entries = sorted((e for p in parts for e in p["entries"]),
                     key=lambda e: (e["family"], int(e["target_task_count"]), e["replicate_id"]))
    keys = [(e["family"], int(e["target_task_count"]), e["replicate_id"]) for e in entries]
    if len(set(keys)) != len(keys):
        raise AcquisitionError("duplicate source dimension in unseen manifests")
    if len({e["sha256"] for e in entries}) != len(entries):
        raise AcquisitionError("duplicate source checksum in unseen manifests")
    expected = expected_source_count(unseen)
    if len(entries) != expected:
        raise AcquisitionError(f"acquired {len(entries)} unseen sources but expected {expected}")
    manifest = {
        "schema_version": 1,
        "set_id": unseen["set_id"],
        "unseen_config_sha256": unseen_config_sha256,
        "model_config_sha256": model_config_sha256,
        "artifact_count": len(entries),
        "entries": entries,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    return manifest


# --------------------------------------------------------------------------- entries
def enumerate_entries(unseen: Mapping[str, Any], model: Mapping[str, Any],
                      source_manifest: Mapping[str, Any]) -> list[dict]:
    """Full factorial: every unseen source x resource scale x scenario x QoS profile."""
    dataset_version = str(model["dataset"]["version"])
    scales = tuple(model["infrastructure"]["resource_scales"])
    scenarios = tuple(model["scenario_profiles"])
    qos_profiles = tuple(model["budget"]["joint_qos_profiles"])
    seeds = unseen["source_to_ifc_seed"]
    out = []
    for src in sorted(source_manifest["entries"],
                      key=lambda e: (e["family"], int(e["target_task_count"]), e["replicate_id"])):
        wf = workflow_id(family=src["family"], target_task_count=int(src["target_task_count"]),
                         replicate_id=src["replicate_id"], source_sha256=src["sha256"])
        for scale, scenario, qos in product(scales, scenarios, qos_profiles):
            seed = int(seeds[src["replicate_id"]])
            base = base_instance_id(dataset_version=dataset_version, workflow_identifier=wf,
                                    resource_scale=scale, scenario_profile=scenario,
                                    ifc_realization_seed=seed)
            cid = f"candidate-{base.removeprefix('base-')}-{qos}"
            out.append({
                "candidate_id": cid,
                "instance_id": cid,
                "base_instance_id": base,
                "family": src["family"],
                "source_kind": src["kind"],
                "target_task_count": int(src["target_task_count"]),
                "replicate_id": src["replicate_id"],
                "source_path": src["path"],
                "source_sha256": src["sha256"],
                "resource_scale": scale,
                "scenario_profile": scenario,
                "ifc_realization_seed": seed,
                "qos_profile": qos,
                "split": unseen["split"],
                "path": f"instances/unseen/{cid}.json",
            })
    if len({e["candidate_id"] for e in out}) != len(out):
        raise ValueError("duplicate unseen candidate identities")
    return out


def build_group(source_root: Path, entries: list[Mapping[str, Any]], model: Mapping[str, Any]) -> dict[str, bytes]:
    """Materialize one base realization and all its QoS instances (same code path as v1)."""
    import generator.materialize as M
    from .instance import build_base_instance

    first = entries[0]
    if any(e["base_instance_id"] != first["base_instance_id"] for e in entries):
        raise ValueError("entries of one group must share a base instance")
    source = M._safe_source(source_root, first["source_path"])
    if file_sha256(source) != first["source_sha256"]:
        raise ValueError(f"source checksum mismatch for {first['source_path']}")
    wf = normalize_source(source, family=first["family"], target_task_count=int(first["target_task_count"]),
                          replicate_id=first["replicate_id"],
                          reference_mips=int(model["workflows"]["reference_mips"]))
    base = build_base_instance(wf, dict(model), scale=first["resource_scale"],
                               scenario=first["scenario_profile"], seed=int(first["ifc_realization_seed"]))
    if base["metadata"]["base_instance_id"] != first["base_instance_id"]:
        raise ValueError(f"base identity mismatch for {first['base_instance_id']}")
    cal = M.build_calibration_result(base, k=int(model["budget"]["calibration"]["tradeoff_solutions"]))
    files = {f"base/{first['base_instance_id']}.json": M._json_file_bytes(base)}
    for e in entries:
        files[e["path"]] = M._json_file_bytes(M.build_qos_instance(e, cal, model))
    return files


# --------------------------------------------------------------------------- CLI
def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ifc-unseen")
    p.add_argument("--unseen-config", default=UNSEEN_CONFIG)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("acquire-bharathi")
    b.add_argument("--upstream-dir", required=True)
    b.add_argument("--output-root", required=True)
    b.add_argument("--manifest", required=True)
    b.add_argument("--family", action="append")
    w = sub.add_parser("acquire-wfcommons")
    w.add_argument("--output-root", required=True)
    w.add_argument("--manifest", required=True)
    w.add_argument("--family", action="append")
    w.add_argument("--target", action="append", type=int)
    m = sub.add_parser("merge-manifests")
    m.add_argument("--inputs", required=True)
    m.add_argument("--output", required=True)
    e = sub.add_parser("entries")
    e.add_argument("--source-manifest", required=True)
    e.add_argument("--output", required=True)
    a = p.parse_args(list(argv) if argv is not None else None)

    unseen = load_unseen_config(a.unseen_config)
    model = load_config(unseen["model_config"])
    if a.cmd == "acquire-bharathi":
        v1 = json.loads(Path(unseen["new_replicates"]["must_differ_from_source_manifest"]).read_text())
        entries = acquire_bharathi(unseen, model, upstream_dir=Path(a.upstream_dir),
                                   output_root=Path(a.output_root), v1_manifest=v1, families=a.family)
        Path(a.manifest).write_text(_canonical_json({"entries": entries}), encoding="utf-8")
    elif a.cmd == "acquire-wfcommons":
        entries = acquire_wfcommons(unseen, model, output_root=Path(a.output_root),
                                    families=a.family, targets=a.target)
        Path(a.manifest).write_text(_canonical_json({"entries": entries}), encoding="utf-8")
    elif a.cmd == "merge-manifests":
        parts = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(a.inputs))]
        manifest = merge_manifests(unseen, parts,
                                   unseen_config_sha256=file_sha256(Path(a.unseen_config)),
                                   model_config_sha256=file_sha256(Path(unseen["model_config"])))
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(_canonical_json(manifest), encoding="utf-8")
        print(f"{manifest['artifact_count']} unseen sources, content_sha256 {manifest['content_sha256']}")
    elif a.cmd == "entries":
        src = json.loads(Path(a.source_manifest).read_text())
        if src.get("set_id") != unseen["set_id"]:
            raise SystemExit("source manifest is not an unseen-v1 manifest")
        entries = enumerate_entries(unseen, model, src)
        Path(a.output).write_text(_canonical_json({"entries": entries}), encoding="utf-8")
        print(f"{len(entries)} unseen instances over {len({e['base_instance_id'] for e in entries})} bases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
