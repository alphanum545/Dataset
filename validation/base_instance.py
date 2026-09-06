from __future__ import annotations

from typing import Any

from generator.canonical import content_sha256
from generator.dax import execution_time_us
from generator.exact import ceil_div
from generator.identity import base_instance_id

from .errors import BenchmarkValidationError
from .schema import validate_schema
from .semantic import validate_network, validate_normalized_workflow, validate_resources


def _fail(message: str) -> None:
    raise BenchmarkValidationError(message)


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
    """Recompute every stored compact base-instance field from authoritative inputs."""
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
            expected_cost = ceil_div(
                resource["price_ncu_per_second"] * duration, 1_000_000
            )
            if instance["compute_cost_ncu"][task_id][resource_id] != expected_cost:
                _fail(f"compute_cost_ncu[{task_id!r}][{resource_id!r}] is inconsistent")
            expected_energy = resource["active_power_mw"] * duration
            if instance["compute_energy_nj"][task_id][resource_id] != expected_energy:
                _fail(f"compute_energy_nj[{task_id!r}][{resource_id!r}] is inconsistent")

    if instance["content_sha256"] != content_sha256(instance):
        _fail("base instance content_sha256 does not match canonical content")
