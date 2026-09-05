from __future__ import annotations

from collections import Counter, defaultdict, deque
from decimal import Decimal
from hashlib import sha256
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Iterable

from generator.canonical import content_sha256
from generator.dax import execution_time_us
from generator.exact import ceil_div, mul_ratio_ceil, mul_ratio_floor
from generator.identity import base_instance_id, workflow_id
from generator.network import route_metrics

from .errors import BenchmarkValidationError
from .schema import validate_schema

if TYPE_CHECKING:
    from generator.schedule import ScheduleEvaluation


_FAMILIES = ("montage", "cybershake", "ligo", "sipht", "genome")
_TASK_COUNTS = (60, 100, 200, 400, 600, 800, 1000)
_REPLICATES = ("r01", "r02", "r03")
_EXPECTED_ROUTES = {
    "iot_iot_different": ["iot_peer_wireless"],
    "iot_fog": ["iot_fog_wireless"],
    "iot_cloud": ["iot_fog_wireless", "fog_cloud_backbone"],
    "fog_fog_different": ["fog_lan"],
    "fog_cloud": ["fog_cloud_backbone"],
    "cloud_cloud_different": ["cloud_lan"],
}
_EXPECTED_SEGMENTS = {
    "iot_peer_wireless",
    "iot_fog_wireless",
    "fog_lan",
    "fog_cloud_backbone",
    "cloud_lan",
}
_DEADLINE_INTERPOLATION_FRACTIONS = {
    "tight": (1, 10),
    "moderate": (1, 2),
    "relaxed": (9, 10),
}
_REFERENCE_SCHEDULERS = {
    "deterministic_heft_ifc",
    "deterministic_peft_ifc",
    "deterministic_cpop_ifc",
    "deterministic_cost_reference_ifc",
}
_BUDGET_FACTORS = {
    "tight": (1, 10),
    "moderate": (1, 2),
    "relaxed": (9, 10),
}


def _fail(message: str) -> None:
    raise BenchmarkValidationError(message)


def _unique(items: Iterable[dict[str, Any]], key: str, label: str) -> list[Any]:
    values = [item[key] for item in items]
    if len(values) != len(set(values)):
        _fail(f"{label} must be unique")
    return values


def _validate_dag(task_ids: set[str], dependencies: list[dict[str, Any]]) -> None:
    indegree = {task_id: 0 for task_id in task_ids}
    children: dict[str, list[str]] = defaultdict(list)
    edge_keys: set[tuple[str, str]] = set()
    for dependency in dependencies:
        parent = dependency["parent"]
        child = dependency["child"]
        if parent not in task_ids or child not in task_ids:
            _fail(f"dependency {parent!r}->{child!r} references an unknown task")
        if parent == child:
            _fail(f"dependency {parent!r}->{child!r} is a self edge")
        edge = (parent, child)
        if edge in edge_keys:
            _fail(f"duplicate dependency {parent!r}->{child!r}")
        edge_keys.add(edge)
        children[parent].append(child)
        indegree[child] += 1

    ready = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        current = ready.popleft()
        visited += 1
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(task_ids):
        _fail("workflow dependency graph contains a cycle")


def validate_normalized_workflow(workflow: dict[str, Any]) -> None:
    validate_schema(workflow, "normalized-workflow")
    metadata = workflow["metadata"]
    tasks = workflow["tasks"]
    dependencies = workflow["dependencies"]

    task_ids = _unique(tasks, "task_id", "task IDs")
    if task_ids != sorted(task_ids):
        _fail("tasks must use canonical task_id ordering")
    if metadata["actual_task_count"] != len(tasks):
        _fail("metadata.actual_task_count does not equal the number of tasks")
    if metadata["target_task_count"] != metadata["actual_task_count"]:
        _fail("target and actual task counts must be identical")

    expected_workflow_id = workflow_id(
        family=metadata["family"],
        target_task_count=metadata["target_task_count"],
        replicate_id=metadata["source_replicate"],
        source_sha256=metadata["source_sha256"],
    )
    if metadata["workflow_id"] != expected_workflow_id:
        _fail("workflow_id does not match the canonical source-derived identity")

    reference_mips = Decimal(metadata["reference_mips"])
    for task in tasks:
        expected_work = Decimal(task["source_runtime_s"]) * reference_mips
        if Decimal(task["work_mi"]) != expected_work:
            _fail(f"task {task['task_id']!r} work_mi does not reconstruct from source runtime")

    dependency_order = [(item["parent"], item["child"]) for item in dependencies]
    if dependency_order != sorted(dependency_order):
        _fail("dependencies must use canonical parent/child ordering")
    _validate_dag(set(task_ids), dependencies)
    for dependency in dependencies:
        files = dependency["transfer_files"]
        names = _unique(files, "name", "dependency transfer-file names")
        if names != sorted(names):
            _fail("dependency transfer_files must use canonical name ordering")
        expected_bytes = sum(item["producer_size_bytes"] for item in files)
        if dependency["data_bytes"] != expected_bytes:
            _fail(
                f"dependency {dependency['parent']}->{dependency['child']} "
                "data_bytes is inconsistent"
            )
        if dependency["data_bits"] != dependency["data_bytes"] * 8:
            _fail(
                f"dependency {dependency['parent']}->{dependency['child']} "
                "data_bits is inconsistent"
            )
        for item in files:
            sizes = item["consumer_declared_sizes_bytes"]
            if sizes != sorted(sizes):
                _fail(f"transfer file {item['name']!r} consumer sizes are not canonical")
            expected_match = sizes == [item["producer_size_bytes"]]
            if item["consumer_size_matches_producer"] is not expected_match:
                _fail(
                    f"transfer file {item['name']!r} producer/consumer match flag "
                    "is inconsistent"
                )


def validate_resources(resources: list[dict[str, Any]]) -> None:
    validate_schema(resources, "resources")
    resource_ids = _unique(resources, "resource_id", "resource IDs")
    tier_order = {"iot": 0, "fog": 1, "cloud": 2}
    expected_order = sorted(
        resource_ids,
        key=lambda identifier: (
            tier_order[identifier.split("-", 1)[0]],
            identifier,
        ),
    )
    if resource_ids != expected_order:
        _fail("resources must use canonical tier/resource_id ordering")
    for resource in resources:
        if not resource["resource_id"].startswith(f"{resource['tier']}-"):
            _fail(f"resource {resource['resource_id']!r} tier prefix is inconsistent")


def validate_network(network: dict[str, Any]) -> None:
    validate_schema(network, "network")
    if set(network["segments"]) != _EXPECTED_SEGMENTS:
        _fail("network must contain exactly the five frozen v1 route segments")
    if network["routes"] != _EXPECTED_ROUTES:
        _fail("network routes do not match the frozen v1 tier routing model")
    for route_name, segments in network["routes"].items():
        missing = [name for name in segments if name not in network["segments"]]
        if missing:
            _fail(f"route {route_name!r} references unknown segments: {', '.join(missing)}")


def _validate_matrix_keys(
    matrix: dict[str, dict[str, int]],
    *,
    task_ids: set[str],
    resource_ids: set[str],
    label: str,
) -> None:
    if set(matrix) != task_ids:
        _fail(f"{label} task keys do not exactly match workflow tasks")
    for task_id, row in matrix.items():
        if set(row) != resource_ids:
            _fail(f"{label}[{task_id!r}] resource keys do not exactly match resources")


def validate_base_instance(instance: dict[str, Any]) -> None:
    validate_schema(instance, "base-ifc-instance")
    metadata = instance["metadata"]
    workflow = {
        "schema_version": instance["schema_version"],
        "metadata": {
            key: metadata[key]
            for key in (
                "workflow_id",
                "family",
                "target_task_count",
                "actual_task_count",
                "source_replicate",
                "source_sha256",
                "reference_mips",
            )
        },
        "tasks": instance["tasks"],
        "dependencies": instance["dependencies"],
    }
    validate_normalized_workflow(workflow)
    validate_resources(instance["resources"])
    validate_network(instance["network"])

    expected_id = base_instance_id(
        dataset_version=metadata["dataset_version"],
        workflow_identifier=metadata["workflow_id"],
        resource_scale=metadata["resource_scale"],
        scenario_profile=metadata["scenario_profile"],
        ifc_realization_seed=metadata["ifc_realization_seed"],
    )
    if metadata["base_instance_id"] != expected_id:
        _fail("base_instance_id does not match the canonical dimension-derived identity")
    if metadata["resource_count"] != len(instance["resources"]):
        _fail("metadata.resource_count does not equal the number of resources")

    task_ids = {task["task_id"] for task in instance["tasks"]}
    resources = {resource["resource_id"]: resource for resource in instance["resources"]}
    resource_ids = set(resources)
    for label in ("execution_time_us", "compute_cost_ncu", "compute_energy_nj"):
        _validate_matrix_keys(
            instance[label], task_ids=task_ids, resource_ids=resource_ids, label=label
        )

    tasks = {task["task_id"]: task for task in instance["tasks"]}
    for task_id, task in tasks.items():
        for resource_id, resource in resources.items():
            duration = execution_time_us(task["work_mi"], resource["mips"])
            if instance["execution_time_us"][task_id][resource_id] != duration:
                _fail(f"execution_time_us[{task_id!r}][{resource_id!r}] is inconsistent")
            expected_cost = ceil_div(resource["price_ncu_per_second"] * duration, 1_000_000)
            if instance["compute_cost_ncu"][task_id][resource_id] != expected_cost:
                _fail(f"compute_cost_ncu[{task_id!r}][{resource_id!r}] is inconsistent")
            expected_energy = resource["active_power_mw"] * duration
            if instance["compute_energy_nj"][task_id][resource_id] != expected_energy:
                _fail(f"compute_energy_nj[{task_id!r}][{resource_id!r}] is inconsistent")

    expected_edges = {
        f"{dependency['parent']}->{dependency['child']}": dependency
        for dependency in instance["dependencies"]
    }
    if set(instance["communication"]) != set(expected_edges):
        _fail("communication edge keys do not exactly match workflow dependencies")
    expected_pairs = {f"{source}|{target}" for source in resource_ids for target in resource_ids}
    for edge_id, dependency in expected_edges.items():
        edge_routes = instance["communication"][edge_id]
        if set(edge_routes) != expected_pairs:
            _fail(f"communication[{edge_id!r}] resource-pair keys are incomplete")
        for source_id, source in resources.items():
            for target_id, target in resources.items():
                pair = f"{source_id}|{target_id}"
                expected = route_metrics(
                    instance["network"],
                    source_tier=source["tier"],
                    target_tier=target["tier"],
                    same_resource=source_id == target_id,
                    data_bits=dependency["data_bits"],
                )
                if edge_routes[pair] != expected:
                    _fail(f"communication[{edge_id!r}][{pair!r}] is inconsistent")
    if instance["content_sha256"] != content_sha256(instance):
        _fail("base instance content_sha256 does not match canonical content")


def _contains_subsequence(values: list[str], subsequence: list[str]) -> bool:
    width = len(subsequence)
    return any(
        values[index : index + width] == subsequence
        for index in range(len(values) - width + 1)
    )


def validate_source_manifest(
    manifest: dict[str, Any],
    *,
    source_root: str | Path | None = None,
    require_complete: bool = True,
) -> None:
    validate_schema(manifest, "source-manifest")
    entries = manifest["entries"]
    if manifest["artifact_count"] != len(entries):
        _fail("source manifest artifact_count does not equal entries length")

    dimensions: set[tuple[str, int, str]] = set()
    paths: set[str] = set()
    checksums: set[str] = set()
    prefix = f"pegasus-bharathi-{manifest['pinned_commit'][:8]}"
    application_by_family = {family: family.upper() for family in _FAMILIES}
    for entry in entries:
        dimension = (entry["family"], entry["target_task_count"], entry["replicate_id"])
        if dimension in dimensions:
            _fail(f"duplicate source manifest dimension {dimension!r}")
        dimensions.add(dimension)
        if entry["path"] in paths:
            _fail(f"duplicate source manifest path {entry['path']!r}")
        paths.add(entry["path"])
        if entry["sha256"] in checksums:
            _fail(f"duplicate source checksum {entry['sha256']!r}")
        checksums.add(entry["sha256"])

        if entry["actual_task_count"] != entry["target_task_count"]:
            _fail(f"source entry {dimension!r} does not have an exact task count")
        if entry["application"] != application_by_family[entry["family"]]:
            _fail(f"source entry {dimension!r} application/family is inconsistent")
        expected_path = (
            f"{prefix}/{entry['family']}/{entry['target_task_count']:04d}/"
            f"{entry['replicate_id']}.dax"
        )
        if entry["path"] != expected_path:
            _fail(f"source entry {dimension!r} path is not canonical")

        command = entry["command"]
        if command[:3] != ["bin/AppGenerator", "-a", entry["application"]]:
            _fail(f"source entry {dimension!r} acquisition command is inconsistent")
        if entry["family"] == "genome":
            expected_sequences = entry["target_task_count"] // 4 - 1
            if (
                entry["request_mode"] != "genome_lanes_sequences_exact"
                or entry["requested_numjobs"] is not None
                or entry["requested_lanes"] != 1
                or entry["requested_sequences"] != expected_sequences
                or not _contains_subsequence(command, ["-l", "1"])
                or not _contains_subsequence(command, ["-s", str(expected_sequences)])
            ):
                _fail(f"Genome source entry {dimension!r} request provenance is inconsistent")
        elif (
            entry["request_mode"] != "numjobs_search"
            or entry["requested_numjobs"] is None
            or entry["requested_numjobs"] < entry["target_task_count"]
            or entry["requested_lanes"] is not None
            or entry["requested_sequences"] is not None
            or not _contains_subsequence(command, ["-n", str(entry["requested_numjobs"])])
        ):
            _fail(f"source entry {dimension!r} numjobs provenance is inconsistent")
        if entry["family"] == "ligo" and entry["requested_numjobs"] % 2 != 0:
            _fail(f"LIGO source entry {dimension!r} uses an odd numjobs request")

    if require_complete:
        expected = {
            (family, task_count, replicate)
            for family in _FAMILIES
            for task_count in _TASK_COUNTS
            for replicate in _REPLICATES
        }
        if dimensions != expected or manifest["artifact_count"] != 105:
            _fail("source manifest does not contain the complete 105-artifact v1 grid")
        expected_order = [
            (family, task_count, replicate)
            for family in _FAMILIES
            for task_count in _TASK_COUNTS
            for replicate in _REPLICATES
        ]
        actual_order = [
            (entry["family"], entry["target_task_count"], entry["replicate_id"])
            for entry in entries
        ]
        if actual_order != expected_order:
            _fail("source manifest entries do not use canonical family/size/replicate ordering")

    if source_root is not None:
        root = Path(source_root).resolve()
        for entry in entries:
            source = (root / entry["path"]).resolve()
            if root not in source.parents:
                _fail(f"source entry path escapes source root: {entry['path']!r}")
            try:
                digest = sha256(source.read_bytes()).hexdigest()
            except OSError as exc:
                _fail(f"cannot read source artifact {entry['path']!r}: {exc}")
            if digest != entry["sha256"]:
                _fail(f"source artifact checksum mismatch for {entry['path']!r}")


def validate_pilot_selection(
    manifest: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    source_manifest: dict[str, Any] | None = None,
) -> None:
    """Validate the frozen pilot selection and optionally reproduce it exactly."""
    validate_schema(manifest, "pilot-selection")
    entries = manifest["entries"]
    if manifest["selected_count"] != len(entries):
        _fail("pilot selected_count does not equal entries length")
    _unique(entries, "candidate_id", "pilot candidate IDs")

    dimensions = (
        "family",
        "target_task_count",
        "replicate_id",
        "resource_scale",
        "scenario_profile",
        "qos_profile",
    )
    signatures = [tuple(entry[key] for key in dimensions) for entry in entries]
    if len(signatures) != len(set(signatures)):
        _fail("pilot candidate dimension tuples must be unique")
    expected_order = sorted(
        entries,
        key=lambda entry: (
            entry["split"],
            *(entry[key] for key in dimensions),
        ),
    )
    if entries != expected_order:
        _fail("pilot entries do not use canonical split/dimension ordering")

    split_counts = Counter(entry["split"] for entry in entries)
    if dict(split_counts) != manifest["split_counts"]:
        _fail("pilot split_counts do not match entries")
    for entry in entries:
        _validate_relative_posix_path(entry["source_path"], label="pilot source path")

    def marginals(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        return {
            dimension: {
                str(value): count
                for value, count in sorted(
                    Counter(item[dimension] for item in items).items(),
                    key=lambda pair: str(pair[0]),
                )
            }
            for dimension in dimensions
        }

    def pairwise_coverage(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "dimensions": [left, right],
                "observed_pairs": len(
                    {(item[left], item[right]) for item in items}
                ),
                "possible_pairs": len({item[left] for item in items})
                * len({item[right] for item in items}),
            }
            for left, right in combinations(dimensions, 2)
        ]

    development = [entry for entry in entries if entry["split"] == "development"]
    holdout = [entry for entry in entries if entry["split"] == "holdout"]
    coverage = manifest["coverage"]
    if coverage["overall_marginals"] != marginals(entries):
        _fail("pilot overall marginal counts are inconsistent")
    if coverage["development_marginals"] != marginals(development):
        _fail("pilot development marginal counts are inconsistent")
    if coverage["holdout_marginals"] != marginals(holdout):
        _fail("pilot holdout marginal counts are inconsistent")
    if coverage["overall_pairwise"] != pairwise_coverage(entries):
        _fail("pilot overall pairwise coverage is inconsistent")
    if coverage["holdout_pairwise"] != pairwise_coverage(holdout):
        _fail("pilot holdout pairwise coverage is inconsistent")
    if any(
        item["observed_pairs"] != item["possible_pairs"]
        for key in ("overall_pairwise", "holdout_pairwise")
        for item in coverage[key]
    ):
        _fail("pilot must provide complete overall and holdout pairwise coverage")

    if manifest["content_sha256"] != content_sha256(manifest):
        _fail("pilot selection content_sha256 does not match canonical content")

    if (config is None) is not (source_manifest is None):
        _fail("config and source_manifest must be supplied together")
    if config is not None and source_manifest is not None:
        from generator.canonical import canonical_json_bytes
        from generator.pilot import build_pilot_selection_manifest

        validate_source_manifest(source_manifest)
        if manifest["configuration_sha256"] != sha256(
            canonical_json_bytes(config)
        ).hexdigest():
            _fail("pilot configuration_sha256 does not match the supplied configuration")
        if manifest["source_manifest_sha256"] != sha256(
            canonical_json_bytes(source_manifest)
        ).hexdigest():
            _fail("pilot source_manifest_sha256 does not match the supplied source manifest")
        expected = build_pilot_selection_manifest(config, source_manifest)
        if manifest != expected:
            _fail("pilot selection does not reproduce from its frozen inputs and seed")


def _validate_schedule_shape(schedule: dict[str, Any]) -> None:
    assignments = schedule["assignments"]
    task_ids = _unique(assignments, "task_id", "schedule task assignments")
    if task_ids != sorted(task_ids):
        _fail("schedule assignments must use canonical task_id ordering")
    for assignment in assignments:
        if assignment["end_us"] <= assignment["start_us"]:
            _fail(f"schedule task {assignment['task_id']!r} must end after it starts")
    if schedule["makespan_us"] != max(item["end_us"] for item in assignments):
        _fail("schedule makespan_us does not equal its maximum task end time")
    expected_checksum = content_sha256(schedule, checksum_field="schedule_sha256")
    if schedule["schedule_sha256"] != expected_checksum:
        _fail("schedule_sha256 does not match canonical schedule content")


def validate_schedule(
    instance: dict[str, Any],
    schedule: dict[str, Any],
    *,
    deadline_us: int | None = None,
    budget_ncu: int | None = None,
) -> ScheduleEvaluation:
    """Validate a schedule against its authoritative base-instance semantics."""
    from generator.schedule import ScheduleEvaluationError, evaluate_schedule

    validate_schema(schedule, "schedule")
    try:
        return evaluate_schedule(
            instance,
            schedule,
            deadline_us=deadline_us,
            budget_ncu=budget_ncu,
        )
    except ScheduleEvaluationError as exc:
        _fail(str(exc))


def _validate_relative_posix_path(value: str, *, label: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        _fail(f"{label} must be a relative canonical POSIX path")


def validate_calibration_result(result: dict[str, Any]) -> None:
    validate_schema(result, "calibration-result")
    lower = result["lower_bounds"]
    if lower["t_lb_us"] != max(lower["t_cp_lb_us"], lower["t_capacity_lb_us"]):
        _fail("t_lb_us must equal max(t_cp_lb_us, t_capacity_lb_us)")
    references = result["reference_schedulers"]
    scheduler_ids = _unique(references, "scheduler_id", "reference scheduler IDs")
    if set(scheduler_ids) != _REFERENCE_SCHEDULERS:
        _fail("calibration must contain the frozen IFC reference scheduler portfolio")

    schedules = [
        *(reference["schedule"] for reference in references),
        *result["moheft"]["candidate_schedules"],
    ]
    for schedule in schedules:
        _validate_schedule_shape(schedule)
    _unique(schedules, "schedule_id", "calibration schedule IDs")
    _unique(schedules, "schedule_sha256", "calibration schedule checksums")
    if any(schedule["makespan_us"] < lower["t_lb_us"] for schedule in schedules):
        _fail("a calibration makespan cannot be below the stored lower bound")

    fast = min(
        schedules,
        key=lambda schedule: (
            schedule["makespan_us"],
            schedule["compute_cost_ncu"],
            schedule["schedule_id"],
        ),
    )
    economical = min(
        schedules,
        key=lambda schedule: (
            schedule["compute_cost_ncu"],
            schedule["makespan_us"],
            schedule["schedule_id"],
        ),
    )
    anchors = result["anchors"]
    expected_anchors = {
        "fast_schedule_id": fast["schedule_id"],
        "economical_schedule_id": economical["schedule_id"],
        "t_fast_us": fast["makespan_us"],
        "t_economical_us": economical["makespan_us"],
        "cost_fast_ncu": fast["compute_cost_ncu"],
        "cost_economical_ncu": economical["compute_cost_ncu"],
        "deadline_range_degenerate": fast["makespan_us"]
        == economical["makespan_us"],
    }
    if anchors != expected_anchors:
        _fail("calibration anchors do not match the frozen selection rules")


def validate_qos_instance(instance: dict[str, Any]) -> None:
    validate_schema(instance, "qos-instance")
    profile = instance["profile"]
    deadline = instance["deadline"]
    budget = instance["budget"]
    witness = instance["joint_feasibility_witness"]
    _validate_schedule_shape(witness)
    if set(instance["calibration"]["reference_scheduler_versions"]) != _REFERENCE_SCHEDULERS:
        _fail("QoS calibration versions do not identify the frozen reference portfolio")

    fraction = (
        deadline["interpolation_numerator"],
        deadline["interpolation_denominator"],
    )
    if fraction != _DEADLINE_INTERPOLATION_FRACTIONS[profile]:
        _fail(f"deadline interpolation does not match the frozen {profile!r} profile")
    if deadline["t_economical_us"] < deadline["t_fast_us"]:
        _fail("t_economical_us cannot be below t_fast_us")
    time_gap = deadline["t_economical_us"] - deadline["t_fast_us"]
    if deadline["time_gap_us"] != time_gap:
        _fail("time_gap_us does not match the deadline anchors")
    if deadline["deadline_range_degenerate"] is not (time_gap == 0):
        _fail("deadline_range_degenerate is inconsistent with the deadline anchors")
    expected_deadline = deadline["t_fast_us"] + mul_ratio_ceil(
        time_gap,
        deadline["interpolation_numerator"],
        deadline["interpolation_denominator"],
    )
    if deadline["deadline_us"] != expected_deadline:
        _fail("deadline_us does not reconstruct from the exact envelope interpolation")

    if (budget["factor_numerator"], budget["factor_denominator"]) != _BUDGET_FACTORS[profile]:
        _fail(f"budget factor does not match the frozen {profile!r} profile")
    if budget["cost_floor_ref_ncu"] > budget["cost_fast_ncu"]:
        _fail("cost_floor_ref_ncu cannot exceed cost_fast_ncu")
    tradeoff_width = budget["cost_fast_ncu"] - budget["cost_floor_ref_ncu"]
    expected_budget_gap = mul_ratio_floor(
        tradeoff_width, budget["factor_numerator"], budget["factor_denominator"]
    )
    if budget["budget_gap_ncu"] != expected_budget_gap:
        _fail("budget_gap_ncu does not reconstruct from the exact interpolation rule")
    expected_budget = budget["cost_floor_ref_ncu"] + expected_budget_gap
    if budget["budget_ncu"] != expected_budget:
        _fail("budget_ncu does not reconstruct from the exact interpolation rule")
    if budget["budget_range_degenerate"] is not (tradeoff_width == 0):
        _fail("budget_range_degenerate is inconsistent with the calibration endpoints")
    if witness["compute_cost_ncu"] != budget["cost_floor_ref_ncu"]:
        _fail("joint witness cost does not equal cost_floor_ref_ncu")
    if witness["compute_cost_ncu"] > budget["budget_ncu"]:
        _fail("joint witness exceeds the materialized budget")
    if witness["makespan_us"] > deadline["deadline_us"]:
        _fail("joint witness exceeds the materialized deadline")
    if instance["content_sha256"] != content_sha256(instance):
        _fail("QoS instance content_sha256 does not match canonical content")


def validate_dataset_manifest(
    manifest: dict[str, Any], *, dataset_root: str | Path | None = None
) -> None:
    validate_schema(manifest, "dataset-manifest")
    entries = manifest["entries"]
    if manifest["instance_count"] != len(entries):
        _fail("dataset manifest instance_count does not equal entries length")
    _unique(entries, "instance_id", "dataset instance IDs")
    _unique(entries, "path", "dataset instance paths")
    _unique(entries, "sha256", "dataset instance checksums")
    for entry in entries:
        _validate_relative_posix_path(entry["path"], label="dataset instance path")

    if dataset_root is not None:
        root = Path(dataset_root).resolve()
        for entry in entries:
            source = (root / entry["path"]).resolve()
            if root not in source.parents:
                _fail(f"dataset entry path escapes dataset root: {entry['path']!r}")
            try:
                digest = sha256(source.read_bytes()).hexdigest()
            except OSError as exc:
                _fail(f"cannot read dataset instance {entry['path']!r}: {exc}")
            if digest != entry["sha256"]:
                _fail(f"dataset instance checksum mismatch for {entry['path']!r}")
