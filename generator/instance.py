from __future__ import annotations

from typing import Any

from .canonical import content_sha256
from .dax import execution_time_us
from .exact import ceil_div
from .identity import base_instance_id
from .network import build_network
from .resources import build_resources


def build_base_instance(
    normalized_workflow: dict[str, Any],
    config: dict[str, Any],
    *,
    scale: str,
    scenario: str,
    seed: int,
) -> dict[str, Any]:
    """Build the deterministic scheduling input before deadline/budget calibration.

    Route-specific communication metrics are intentionally not expanded into an
    edge-by-resource-pair matrix. They are exactly derivable from dependencies,
    resource tiers, and the stored network model through generator.network.
    """
    resources = build_resources(config, scale=scale, scenario=scenario, seed=seed)
    network = build_network(config, scenario=scenario)

    execution_matrix: dict[str, dict[str, int]] = {}
    cost_matrix: dict[str, dict[str, int]] = {}
    compute_energy_matrix: dict[str, dict[str, int]] = {}

    for task in normalized_workflow["tasks"]:
        task_id = task["task_id"]
        execution_matrix[task_id] = {}
        cost_matrix[task_id] = {}
        compute_energy_matrix[task_id] = {}
        for resource in resources:
            resource_id = resource["resource_id"]
            duration_us = execution_time_us(task["work_mi"], int(resource["mips"]))
            execution_matrix[task_id][resource_id] = duration_us
            cost_matrix[task_id][resource_id] = ceil_div(
                int(resource["price_ncu_per_second"]) * duration_us,
                1_000_000,
            )
            compute_energy_matrix[task_id][resource_id] = int(resource["active_power_mw"]) * duration_us

    dataset_version = str(config["dataset"]["version"])
    identifier = base_instance_id(
        dataset_version=dataset_version,
        workflow_identifier=normalized_workflow["metadata"]["workflow_id"],
        resource_scale=scale,
        scenario_profile=scenario,
        ifc_realization_seed=seed,
    )

    instance = {
        "schema_version": 1,
        "metadata": {
            **normalized_workflow["metadata"],
            "base_instance_id": identifier,
            "dataset_version": dataset_version,
            "resource_scale": scale,
            "scenario_profile": scenario,
            "ifc_realization_seed": seed,
            "resource_count": len(resources),
        },
        "tasks": normalized_workflow["tasks"],
        "dependencies": normalized_workflow["dependencies"],
        "resources": resources,
        "network": network,
        "execution_time_us": execution_matrix,
        "compute_cost_ncu": cost_matrix,
        "compute_energy_nj": compute_energy_matrix,
    }
    instance["content_sha256"] = content_sha256(instance)
    return instance
