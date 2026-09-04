from __future__ import annotations

import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SCALE = re.compile(r"^S[0-9]{2}$")


def _token(value: str, *, field: str) -> str:
    if not _TOKEN.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase identifier token: {value!r}")
    return value


def workflow_id(
    *, family: str, target_task_count: int, replicate_id: str, source_sha256: str
) -> str:
    """Return the stable identity of one normalized frozen source workflow."""
    _token(family, field="family")
    _token(replicate_id, field="replicate_id")
    if target_task_count <= 0:
        raise ValueError("target_task_count must be > 0")
    if not _SHA256.fullmatch(source_sha256):
        raise ValueError("source_sha256 must be 64 lowercase hexadecimal characters")
    return f"wf-{family}-{target_task_count:04d}-{replicate_id}-{source_sha256[:12]}"


def base_instance_id(
    *,
    dataset_version: str,
    workflow_identifier: str,
    resource_scale: str,
    scenario_profile: str,
    ifc_realization_seed: int,
) -> str:
    """Return the stable identity of an IFC realization before QoS materialization."""
    _token(dataset_version, field="dataset_version")
    _token(workflow_identifier, field="workflow_identifier")
    if not _SCALE.fullmatch(resource_scale):
        raise ValueError(f"resource_scale must match SNN: {resource_scale!r}")
    _token(scenario_profile, field="scenario_profile")
    if ifc_realization_seed < 0:
        raise ValueError("ifc_realization_seed must be >= 0")
    return (
        f"base-{dataset_version}-{workflow_identifier}-{resource_scale.lower()}-"
        f"{scenario_profile}-seed{ifc_realization_seed}"
    )
