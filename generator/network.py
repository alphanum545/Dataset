from __future__ import annotations

from copy import deepcopy
from typing import Any

from .exact import ceil_div, mul_ratio_floor


def build_network(config: dict[str, Any], *, scenario: str) -> dict:
    if scenario not in config["scenario_profiles"]:
        raise ValueError(f"unknown scenario profile {scenario!r}")
    network = deepcopy(config["network"])
    if scenario != "network_constrained":
        return network

    profile = config["scenario_profiles"][scenario]
    stressed = set(profile["stressed_segments"])
    bw = profile["bandwidth_multiplier"]
    latency = profile["latency_multiplier"]
    energy = profile["energy_multiplier"]

    for name, segment in network["segments"].items():
        if name not in stressed:
            continue
        segment["bandwidth_mbps"] = mul_ratio_floor(
            int(segment["bandwidth_mbps"]), int(bw["numerator"]), int(bw["denominator"])
        )
        segment["latency_us"] = mul_ratio_floor(
            int(segment["latency_us"]), int(latency["numerator"]), int(latency["denominator"])
        )
        segment["energy_pj_per_bit"] = mul_ratio_floor(
            int(segment["energy_pj_per_bit"]), int(energy["numerator"]), int(energy["denominator"])
        )
        if segment["bandwidth_mbps"] <= 0:
            raise ValueError(f"scenario produced non-positive bandwidth for {name}")
    return network


def placement_route_key(source_tier: str, target_tier: str, *, same_resource: bool) -> str | None:
    if same_resource:
        return None
    if source_tier == target_tier:
        if source_tier == "iot":
            return "iot_iot_different"
        if source_tier == "fog":
            return "fog_fog_different"
        if source_tier == "cloud":
            return "cloud_cloud_different"
    pair = frozenset((source_tier, target_tier))
    if pair == {"iot", "fog"}:
        return "iot_fog"
    if pair == {"iot", "cloud"}:
        return "iot_cloud"
    if pair == {"fog", "cloud"}:
        return "fog_cloud"
    raise ValueError(f"unsupported tier pair {source_tier!r}, {target_tier!r}")


def route_metrics(
    network: dict[str, Any],
    *,
    source_tier: str,
    target_tier: str,
    same_resource: bool,
    data_bits: int,
) -> dict[str, int]:
    if data_bits < 0:
        raise ValueError("data_bits must be >= 0")
    route_key = placement_route_key(source_tier, target_tier, same_resource=same_resource)
    if route_key is None or data_bits == 0:
        return {"communication_time_us": 0, "communication_energy_pj": 0}

    time_us = 0
    energy_pj = 0
    for segment_name in network["routes"][route_key]:
        segment = network["segments"][segment_name]
        time_us += int(segment["latency_us"]) + ceil_div(data_bits, int(segment["bandwidth_mbps"]))
        energy_pj += data_bits * int(segment["energy_pj_per_bit"])
    return {"communication_time_us": time_us, "communication_energy_pj": energy_pj}
