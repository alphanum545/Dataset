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
