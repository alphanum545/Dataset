from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
from itertools import combinations, product
from typing import Any, Iterable, Mapping

from .canonical import canonical_json_bytes, content_sha256
from .identity import base_instance_id, workflow_id


_DIMENSIONS = (
    "family",
    "target_task_count",
    "replicate_id",
    "resource_scale",
    "scenario_profile",
    "qos_profile",
)
_BASE_DIMENSIONS = _DIMENSIONS[:-1]
_ASSIGNMENT_ORDER = _DIMENSIONS[1:]
_MAX_CONSTRUCTION_ATTEMPTS = 256


class PilotSelectionError(ValueError):
    """Raised when the frozen pilot selection contract cannot be satisfied."""


def _stable_key(seed: int, *parts: object) -> str:
    payload = "|".join((str(seed), *(str(part) for part in parts)))
    return sha256(payload.encode("utf-8")).hexdigest()


def _candidate_signature(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(candidate[dimension] for dimension in _DIMENSIONS)


def _base_signature(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(candidate[dimension] for dimension in _BASE_DIMENSIONS)


def _candidate_id(candidate: Mapping[str, Any], *, dataset_version: str) -> str:
    workflow_identifier = workflow_id(
        family=str(candidate["family"]),
        target_task_count=int(candidate["target_task_count"]),
        replicate_id=str(candidate["replicate_id"]),
        source_sha256=str(candidate["source_sha256"]),
    )
    base_identifier = base_instance_id(
        dataset_version=dataset_version,
        workflow_identifier=workflow_identifier,
        resource_scale=str(candidate["resource_scale"]),
        scenario_profile=str(candidate["scenario_profile"]),
        ifc_realization_seed=int(candidate["ifc_realization_seed"]),
    )
    return f"candidate-{base_identifier.removeprefix('base-')}-{candidate['qos_profile']}"


def enumerate_candidates(
    config: Mapping[str, Any], source_manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Enumerate the complete v1 candidate identity grid without materializing instances."""
    families = tuple(config["workflows"]["families"])
    task_counts = tuple(int(value) for value in config["workflows"]["requested_task_counts"])
    replicates = tuple(config["workflows"]["source_replicates"])
    resource_scales = tuple(config["infrastructure"]["resource_scales"])
    scenarios = tuple(config["scenario_profiles"])
    qos_profiles = tuple(config["budget"]["joint_qos_profiles"])
    seed_by_replicate = config["replications"]["source_to_ifc_seed"]

    source_by_dimension: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    for entry in source_manifest["entries"]:
        key = (
            str(entry["family"]),
            int(entry["target_task_count"]),
            str(entry["replicate_id"]),
        )
        if key in source_by_dimension:
            raise PilotSelectionError(f"duplicate source dimension {key!r}")
        source_by_dimension[key] = entry

    candidates: list[dict[str, Any]] = []
    dataset_version = str(config["dataset"]["version"])
    for family, task_count, replicate, scale, scenario, qos_profile in product(
        families,
        task_counts,
        replicates,
        resource_scales,
        scenarios,
        qos_profiles,
    ):
        source_key = (family, task_count, replicate)
        try:
            source = source_by_dimension[source_key]
            realization_seed = int(seed_by_replicate[replicate])
        except KeyError as exc:
            raise PilotSelectionError(
                f"candidate grid cannot resolve source/seed for {source_key!r}"
            ) from exc
        candidate = {
            "family": family,
            "target_task_count": task_count,
            "replicate_id": replicate,
            "source_sha256": source["sha256"],
            "source_path": source["path"],
            "ifc_realization_seed": realization_seed,
            "resource_scale": scale,
            "scenario_profile": scenario,
            "qos_profile": qos_profile,
        }
        candidate["candidate_id"] = _candidate_id(
            candidate, dataset_version=dataset_version
        )
        candidates.append(candidate)
    return candidates


def _normalize_targets(raw: Mapping[Any, Any]) -> dict[Any, int]:
    targets: dict[Any, int] = {}
    for value, count in raw.items():
        normalized_value: Any = int(value) if isinstance(value, int) else str(value)
        normalized_count = int(count)
        if normalized_count < 0:
            raise PilotSelectionError("marginal target counts must be nonnegative")
        targets[normalized_value] = normalized_count
    return targets


def _split_targets(
    config: Mapping[str, Any], split: str
) -> dict[str, dict[Any, int]]:
    selection = config["pilot_selection"]
    overall = {
        dimension: _normalize_targets(targets)
        for dimension, targets in selection["marginal_targets"].items()
    }
    holdout = {
        dimension: _normalize_targets(targets)
        for dimension, targets in selection["holdout_marginal_targets"].items()
    }
    if split == "holdout":
        return holdout
    if split != "development":
        raise PilotSelectionError(f"unknown pilot split {split!r}")
    return {
        dimension: {
            value: overall[dimension][value] - holdout[dimension].get(value, 0)
            for value in overall[dimension]
        }
        for dimension in _DIMENSIONS
    }


def _assign_dimension(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    targets: Mapping[Any, int],
    seed: int,
    namespace: str,
    attempt: int,
    forbidden_signatures: set[tuple[Any, ...]],
    forbidden_base_signatures: set[tuple[Any, ...]],
    require_unique_bases: bool,
) -> bool:
    remaining = dict(targets)
    previous_dimensions = _DIMENSIONS[: _DIMENSIONS.index(dimension)]
    pair_counts: Counter[tuple[str, Any, Any]] = Counter()
    used_base_signatures: set[tuple[Any, ...]] = set()
    order = sorted(
        range(len(rows)),
        key=lambda index: _stable_key(
            seed, namespace, attempt, dimension, rows[index]["_slot"]
        ),
    )

    for index in order:
        row = rows[index]
        choices: list[tuple[tuple[Any, ...], Any]] = []
        for value, available in remaining.items():
            if available <= 0:
                continue
            if dimension == _BASE_DIMENSIONS[-1]:
                base_signature = tuple(
                    value if item == dimension else row[item]
                    for item in _BASE_DIMENSIONS
                )
                if base_signature in forbidden_base_signatures:
                    continue
                if require_unique_bases and base_signature in used_base_signatures:
                    continue
            if dimension == _DIMENSIONS[-1]:
                signature = tuple(
                    value if item == dimension else row[item] for item in _DIMENSIONS
                )
                if signature in forbidden_signatures:
                    continue
            novelty = sum(
                pair_counts[(previous, row[previous], value)] == 0
                for previous in previous_dimensions
            )
            existing = sum(
                pair_counts[(previous, row[previous], value)]
                for previous in previous_dimensions
            )
            key = (
                -novelty,
                existing,
                -available,
                _stable_key(
                    seed,
                    namespace,
                    attempt,
                    dimension,
                    row["_slot"],
                    value,
                ),
            )
            choices.append((key, value))
        if not choices:
            return False
        _, selected = min(choices)
        row[dimension] = selected
        remaining[selected] -= 1
        if dimension == _BASE_DIMENSIONS[-1]:
            used_base_signatures.add(_base_signature(row))
        for previous in previous_dimensions:
            pair_counts[(previous, row[previous], selected)] += 1
    return all(count == 0 for count in remaining.values())


def _selection_score(rows: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    materialized = list(rows)
    coverage = 0
    imbalance = 0
    for left, right in combinations(_DIMENSIONS, 2):
        counts = Counter((row[left], row[right]) for row in materialized)
        coverage += len(counts)
        if counts:
            values = list(counts.values())
            imbalance += max(values) - min(values)
    return coverage, -imbalance


def _construct_split(
    targets: Mapping[str, Mapping[Any, int]],
    *,
    seed: int,
    split: str,
    forbidden_signatures: set[tuple[Any, ...]] | None = None,
    forbidden_base_signatures: set[tuple[Any, ...]] | None = None,
    require_unique_bases: bool = False,
) -> list[dict[str, Any]]:
    forbidden = set(forbidden_signatures or ())
    forbidden_bases = set(forbidden_base_signatures or ())
    expected_count = sum(targets["family"].values())
    for dimension in _DIMENSIONS:
        if sum(targets[dimension].values()) != expected_count:
            raise PilotSelectionError(
                f"{split} target for {dimension} does not total {expected_count}"
            )

    best_rows: list[dict[str, Any]] | None = None
    best_key: tuple[Any, ...] | None = None
    for attempt in range(_MAX_CONSTRUCTION_ATTEMPTS):
        rows: list[dict[str, Any]] = []
        slot = 0
        for family, count in targets["family"].items():
            for _ in range(count):
                rows.append({"family": family, "_slot": slot})
                slot += 1

        complete = True
        used_signatures = set(forbidden)
        for dimension in _ASSIGNMENT_ORDER:
            if not _assign_dimension(
                rows,
                dimension=dimension,
                targets=targets[dimension],
                seed=seed,
                namespace=split,
                attempt=attempt,
                forbidden_signatures=used_signatures,
                forbidden_base_signatures=forbidden_bases,
                require_unique_bases=require_unique_bases,
            ):
                complete = False
                break
            if dimension == _DIMENSIONS[-1]:
                signatures = [_candidate_signature(row) for row in rows]
                if len(signatures) != len(set(signatures)):
                    complete = False
                    break
                used_signatures.update(signatures)
        if not complete:
            continue
        if require_unique_bases:
            base_signatures = [_base_signature(row) for row in rows]
            if len(base_signatures) != len(set(base_signatures)):
                continue
        if any(_base_signature(row) in forbidden_bases for row in rows):
            continue

        for row in rows:
            row.pop("_slot")
        rows.sort(key=_candidate_signature)
        score = _selection_score(rows)
        signature_key = tuple(_candidate_signature(row) for row in rows)
        candidate_key = (score, tuple(reversed(signature_key)))
        if best_key is None or candidate_key > best_key:
            best_key = candidate_key
            best_rows = deepcopy(rows)

    if best_rows is None:
        raise PilotSelectionError(
            f"could not construct deterministic {split} split after "
            f"{_MAX_CONSTRUCTION_ATTEMPTS} attempts"
        )
    return best_rows


def _marginals(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    materialized = list(rows)
    return {
        dimension: {
            str(value): count
            for value, count in sorted(
                Counter(row[dimension] for row in materialized).items(),
                key=lambda item: str(item[0]),
            )
        }
        for dimension in _DIMENSIONS
    }


def _pairwise_coverage(
    rows: Iterable[Mapping[str, Any]], universe: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    materialized = list(rows)
    all_candidates = list(universe)
    result = []
    for left, right in combinations(_DIMENSIONS, 2):
        observed = {(row[left], row[right]) for row in materialized}
        possible = {(row[left], row[right]) for row in all_candidates}
        result.append(
            {
                "dimensions": [left, right],
                "observed_pairs": len(observed),
                "possible_pairs": len(possible),
            }
        )
    return result


def build_pilot_selection_manifest(
    config: Mapping[str, Any], source_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the frozen, outcome-independent 160/40 pilot selection manifest."""
    selection = config["pilot_selection"]
    seed = int(selection["seed"])
    universe = enumerate_candidates(config, source_manifest)
    expected_universe = int(selection["candidate_universe_count"])
    if len(universe) != expected_universe:
        raise PilotSelectionError(
            f"candidate universe has {len(universe)} entries, expected {expected_universe}"
        )
    universe_by_signature = {
        _candidate_signature(candidate): candidate for candidate in universe
    }
    if len(universe_by_signature) != len(universe):
        raise PilotSelectionError("candidate universe identities are not unique")

    require_unique_holdout_bases = bool(selection["require_unique_holdout_bases"])
    require_base_disjoint_splits = bool(selection["require_base_disjoint_splits"])
    holdout_rows = _construct_split(
        _split_targets(config, "holdout"),
        seed=seed,
        split="holdout",
        require_unique_bases=require_unique_holdout_bases,
    )
    holdout_signatures = {_candidate_signature(row) for row in holdout_rows}
    holdout_base_signatures = {_base_signature(row) for row in holdout_rows}
    if require_unique_holdout_bases and len(holdout_base_signatures) != len(holdout_rows):
        raise PilotSelectionError("holdout selection must use distinct base realizations")

    development_rows = _construct_split(
        _split_targets(config, "development"),
        seed=seed,
        split="development",
        forbidden_signatures=holdout_signatures,
        forbidden_base_signatures=(
            holdout_base_signatures if require_base_disjoint_splits else None
        ),
    )
    development_base_signatures = {_base_signature(row) for row in development_rows}
    overlap = development_base_signatures & holdout_base_signatures
    if require_base_disjoint_splits and overlap:
        raise PilotSelectionError(
            "development and holdout selections must not share base realizations"
        )

    entries: list[dict[str, Any]] = []
    for split, rows in (("development", development_rows), ("holdout", holdout_rows)):
        for row in rows:
            signature = _candidate_signature(row)
            try:
                candidate = universe_by_signature[signature]
            except KeyError as exc:
                raise PilotSelectionError(
                    f"selected row is absent from candidate universe: {signature!r}"
                ) from exc
            entries.append({**candidate, "split": split})
    entries.sort(key=lambda item: (item["split"], _candidate_signature(item)))

    selected_count = int(selection["selected_count"])
    if len(entries) != selected_count:
        raise PilotSelectionError(
            f"selector produced {len(entries)} entries, expected {selected_count}"
        )
    if len({entry["candidate_id"] for entry in entries}) != len(entries):
        raise PilotSelectionError("selected candidate IDs are not unique")

    config_sha256 = sha256(canonical_json_bytes(config)).hexdigest()
    source_sha256 = sha256(canonical_json_bytes(source_manifest)).hexdigest()
    universe_sha256 = sha256(canonical_json_bytes(universe)).hexdigest()
    development = [entry for entry in entries if entry["split"] == "development"]
    holdout = [entry for entry in entries if entry["split"] == "holdout"]
    manifest = {
        "schema_version": 1,
        "selection_id": str(selection["selection_id"]),
        "dataset_version": str(config["dataset"]["version"]),
        "selector": {
            "selector_id": str(selection["selector_id"]),
            "selector_version": int(selection["selector_version"]),
            "seed": seed,
            "construction_attempts": _MAX_CONSTRUCTION_ATTEMPTS,
        },
        "source_manifest_sha256": source_sha256,
        "configuration_sha256": config_sha256,
        "candidate_universe_count": len(universe),
        "candidate_universe_sha256": universe_sha256,
        "selected_count": len(entries),
        "split_counts": {
            "development": len(development),
            "holdout": len(holdout),
        },
        "base_isolation": {
            "development_unique_base_count": len(development_base_signatures),
            "holdout_unique_base_count": len(holdout_base_signatures),
            "cross_split_base_overlap_count": len(overlap),
        },
        "coverage": {
            "overall_marginals": _marginals(entries),
            "development_marginals": _marginals(development),
            "holdout_marginals": _marginals(holdout),
            "overall_pairwise": _pairwise_coverage(entries, universe),
            "holdout_pairwise": _pairwise_coverage(holdout, universe),
        },
        "entries": entries,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    return manifest
