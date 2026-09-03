from __future__ import annotations

from hashlib import sha256
from typing import Any

from .exact import mul_ratio_floor


CLASS_ORDER = ("economy", "balanced", "performance")
TIER_ORDER = ("iot", "fog", "cloud")


def _deterministic_class(seed: int, tier: str, slot_index: int) -> str:
    digest = sha256(f"ifc-resource-v1:{seed}:{tier}:{slot_index}".encode("ascii")).digest()
    return CLASS_ORDER[int.from_bytes(digest[:8], "big") % len(CLASS_ORDER)]


def _class_sequence(count: int, *, seed: int, tier: str) -> list[str]:
    if count <= 0:
        raise ValueError(f"resource count for {tier} must be > 0")
    if count == 1:
        required = ["balanced"]
    elif count == 2:
        required = ["economy", "performance"]
    else:
        required = list(CLASS_ORDER)
    result = required[:count]
    for index in range(len(result), count):
        result.append(_deterministic_class(seed, tier, index))
    return result


def build_resources(config: dict[str, Any], *, scale: str, scenario: str, seed: int) -> list[dict]:
    infrastructure = config["infrastructure"]
    scale_counts = infrastructure["resource_scales"].get(scale)
    if scale_counts is None:
        raise ValueError(f"unknown resource scale {scale!r}")
    if scenario not in config["scenario_profiles"]:
        raise ValueError(f"unknown scenario profile {scenario!r}")

    resources: list[dict] = []
    for tier in TIER_ORDER:
        count = int(scale_counts[tier])
        classes = infrastructure["resource_classes"][tier]
        for position, class_name in enumerate(_class_sequence(count, seed=seed, tier=tier), start=1):
            values = dict(classes[class_name])
            mips = int(values["mips"])
            if scenario == "compute_constrained" and tier in {"fog", "cloud"}:
                ratio = config["scenario_profiles"][scenario]["fog_cloud_compute_multiplier"]
                mips = mul_ratio_floor(mips, int(ratio["numerator"]), int(ratio["denominator"]))
                if mips <= 0:
                    raise ValueError("scenario produced non-positive MIPS")
            resources.append(
                {
                    "resource_id": f"{tier}-{position:03d}",
                    "tier": tier,
                    "class": class_name,
                    "mips": mips,
                    "memory_mb": int(values["memory_mb"]),
                    "concurrency_slots": 1,
                    "active_power_mw": int(values["active_power_mw"]),
                    "idle_power_mw": None if values.get("idle_power_mw") is None else int(values["idle_power_mw"]),
                    "price_ncu_per_second": int(values["price_ncu_per_second"]),
                }
            )
    return resources
