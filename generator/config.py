from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the committed benchmark configuration is structurally invalid."""


def load_config(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read configuration {source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("benchmark configuration root must be a mapping")
    _validate_minimum(raw)
    return raw


def _validate_minimum(config: dict[str, Any]) -> None:
    required = (
        "source_workflows",
        "workflows",
        "infrastructure",
        "network",
        "scenario_profiles",
        "replications",
        "cost_model",
    )
    missing = [key for key in required if key not in config]
    if missing:
        raise ConfigError(f"configuration missing required sections: {', '.join(missing)}")

    workflows = config["workflows"]
    if workflows.get("task_count_policy") != "exact" or int(workflows.get("allowed_size_deviation", -1)) != 0:
        raise ConfigError("core v1 requires exact task counts with allowed_size_deviation=0")
    if config["infrastructure"].get("concurrency_slots_per_resource") != 1:
        raise ConfigError("core v1 requires one serial scheduling slot per resource")

    pilot = config.get("pilot_selection")
    if pilot is not None:
        selected_count = int(pilot.get("selected_count", -1))
        split_counts = pilot.get("split_counts", {})
        if selected_count != 200 or split_counts != {
            "development": 160,
            "holdout": 40,
        }:
            raise ConfigError("pilot selection must define the frozen 160/40 split of 200")
        for target_name in ("marginal_targets", "holdout_marginal_targets"):
            targets = pilot.get(target_name, {})
            expected_total = 200 if target_name == "marginal_targets" else 40
            for dimension in (
                "family",
                "target_task_count",
                "replicate_id",
                "resource_scale",
                "scenario_profile",
                "qos_profile",
            ):
                values = targets.get(dimension, {})
                if sum(int(count) for count in values.values()) != expected_total:
                    raise ConfigError(
                        f"{target_name}.{dimension} must total {expected_total}"
                    )

    reference = config.get("reference_makespan")
    if reference is not None and reference.get("strategy") != "feasible_time_cost_envelope":
        raise ConfigError("reference_makespan must use the feasible time-cost envelope")
