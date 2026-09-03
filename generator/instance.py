from __future__ import annotations

from typing import Any

from .dax import execution_time_us
from .exact import ceil_div
from .network import build_network, route_metrics
from .resources import build_resources


def build_base_instance(
    normalized_workflow: dict[str, Any],
    config: dict[str, Any],
    *,
    scale: str,
    scenario: str,
    seed: int,
) -> dict[str, Any]:
    """Build the deterministic scheduling input before deadline/budget calibration."""
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

    communication_matrix: dict[str, dict[str, dict[str, int]]] = {}
    for dependency in normalized_workflow["dependencies"]:
        edge_id = f"{dependency['parent']}->{dependency['child']}"
        edge_routes: dict[str, dict[str, int]] = {}
        data_bits = int(dependency["data_bits"])
        for source in resources:
            for target in resources:
                pair_key = f"{source['resource_id']}|{target['resource_id']}"
                edge_routes[pair_key] = route_metrics(
                    network,
                    source_tier=source["tier"],
                    target_tier=target["tier"],
                    same_resource=source["resource_id"] == target["resource_id"],
                    data_bits=data_bits,
                )
        communication_matrix[edge_id] = edge_routes

    return {
        "metadata": {
            **normalized_workflow["metadata"],
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
        "communication": communication_matrix,
    }
