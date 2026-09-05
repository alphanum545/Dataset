import json

import pytest

from generator.config import ConfigError, load_config
from generator.canonical import content_sha256
from generator.dax import DaxValidationError, execution_time_us, normalize_dax
from generator.instance import build_base_instance
from generator.network import build_network, resource_route_metrics, route_metrics
from generator.resources import build_resources


DAX = '''<?xml version="1.0"?>
<adag xmlns="http://pegasus.isi.edu/schema/DAX" version="3.3" name="tiny">
  <job id="A" name="a" runtime="1.25">
    <uses file="x.dat" link="output" size="1000" />
  </job>
  <job id="B" name="b" runtime="2.5">
    <uses file="x.dat" link="input" size="1000" />
  </job>
  <child ref="B"><parent ref="A" /></child>
</adag>
'''


CONFIG = {
    "dataset": {"version": "v1-draft"},
    "infrastructure": {
        "resource_scales": {"S01": {"iot": 4, "fog": 4, "cloud": 2}},
        "resource_classes": {
            "iot": {
                "economy": {"mips": 500, "memory_mb": 512, "active_power_mw": 3500, "idle_power_mw": 2100, "price_ncu_per_second": 0},
                "balanced": {"mips": 750, "memory_mb": 1024, "active_power_mw": 5000, "idle_power_mw": 2100, "price_ncu_per_second": 25000000},
                "performance": {"mips": 1000, "memory_mb": 2048, "active_power_mw": 6400, "idle_power_mw": 2100, "price_ncu_per_second": 50000000},
            },
            "fog": {
                "economy": {"mips": 1000, "memory_mb": 1024, "active_power_mw": 1000, "idle_power_mw": 50, "price_ncu_per_second": 100000000},
                "balanced": {"mips": 1500, "memory_mb": 2048, "active_power_mw": 3000, "idle_power_mw": 50, "price_ncu_per_second": 300000000},
                "performance": {"mips": 2000, "memory_mb": 4096, "active_power_mw": 5000, "idle_power_mw": 50, "price_ncu_per_second": 500000000},
            },
            "cloud": {
                "economy": {"mips": 3000, "memory_mb": 5000, "active_power_mw": 5000, "idle_power_mw": None, "price_ncu_per_second": 600000000},
                "balanced": {"mips": 4000, "memory_mb": 10000, "active_power_mw": 7500, "idle_power_mw": None, "price_ncu_per_second": 800000000},
                "performance": {"mips": 5000, "memory_mb": 20000, "active_power_mw": 10000, "idle_power_mw": None, "price_ncu_per_second": 1000000000},
            },
        },
    },
    "scenario_profiles": {
        "balanced": {},
        "compute_constrained": {"fog_cloud_compute_multiplier": {"numerator": 3, "denominator": 4}},
        "network_constrained": {
            "stressed_segments": ["iot_fog_wireless", "fog_cloud_backbone"],
            "bandwidth_multiplier": {"numerator": 2, "denominator": 5},
            "latency_multiplier": {"numerator": 5, "denominator": 2},
            "energy_multiplier": {"numerator": 3, "denominator": 2},
        },
    },
    "network": {
        "segments": {
            "iot_peer_wireless": {"bandwidth_mbps": 100, "latency_us": 2000, "energy_pj_per_bit": 110000},
            "iot_fog_wireless": {"bandwidth_mbps": 100, "latency_us": 5000, "energy_pj_per_bit": 162500},
            "fog_lan": {"bandwidth_mbps": 1000, "latency_us": 2000, "energy_pj_per_bit": 2000},
            "fog_cloud_backbone": {"bandwidth_mbps": 500, "latency_us": 20000, "energy_pj_per_bit": 16660},
            "cloud_lan": {"bandwidth_mbps": 2000, "latency_us": 1000, "energy_pj_per_bit": 2000},
        },
        "routes": {
            "iot_iot_different": ["iot_peer_wireless"],
            "iot_fog": ["iot_fog_wireless"],
            "iot_cloud": ["iot_fog_wireless", "fog_cloud_backbone"],
            "fog_fog_different": ["fog_lan"],
            "fog_cloud": ["fog_cloud_backbone"],
            "cloud_cloud_different": ["cloud_lan"],
        },
    },
}


def test_normalize_dax_preserves_exact_runtime_and_edge_bytes():
    result = normalize_dax(DAX, family="montage", target_task_count=2, replicate_id="r01")
    assert result["schema_version"] == 1
    assert result["metadata"]["workflow_id"].startswith("wf-montage-0002-r01-")
    assert result["metadata"]["actual_task_count"] == 2
    assert result["tasks"][0]["work_mi"] == "1250.00"
    assert result["dependencies"] == [
        {
            "parent": "A",
            "child": "B",
            "data_bytes": 1000,
            "data_bits": 8000,
            "data_size_source": "producer_output",
            "transfer_files": [
                {
                    "name": "x.dat",
                    "producer_size_bytes": 1000,
                    "consumer_declared_sizes_bytes": [1000],
                    "consumer_size_matches_producer": True,
                }
            ],
        }
    ]
    assert execution_time_us("1250.00", 500) == 2_500_000


def test_exact_task_count_is_enforced():
    with pytest.raises(DaxValidationError, match="does not equal exact target"):
        normalize_dax(DAX, family="montage", target_task_count=3, replicate_id="r01")


def test_producer_output_size_is_authoritative_when_consumer_metadata_differs():
    mismatch = DAX.replace('link="input" size="1000"', 'link="input" size="777"')
    result = normalize_dax(mismatch, family="montage", target_task_count=2, replicate_id="r01")
    edge = result["dependencies"][0]
    assert edge["data_bytes"] == 1000
    assert edge["data_size_source"] == "producer_output"
    assert edge["transfer_files"][0]["consumer_declared_sizes_bytes"] == [777]
    assert edge["transfer_files"][0]["consumer_size_matches_producer"] is False


def test_dependency_without_shared_file_is_rejected():
    broken = DAX.replace('file="x.dat" link="input"', 'file="other.dat" link="input"')
    with pytest.raises(DaxValidationError, match="no shared file metadata"):
        normalize_dax(broken, family="montage", target_task_count=2, replicate_id="r01")


def test_resource_generation_is_deterministic_and_has_required_endpoints():
    first = build_resources(CONFIG, scale="S01", scenario="balanced", seed=101)
    second = build_resources(CONFIG, scale="S01", scenario="balanced", seed=101)
    assert first == second
    assert len(first) == 10
    cloud = [resource for resource in first if resource["tier"] == "cloud"]
    assert [resource["class"] for resource in cloud] == ["economy", "performance"]
    fog_classes = {resource["class"] for resource in first if resource["tier"] == "fog"}
    assert {"economy", "balanced", "performance"}.issubset(fog_classes)
    assert all(resource["concurrency_slots"] == 1 for resource in first)


def test_compute_constrained_changes_only_fog_cloud_mips():
    balanced = build_resources(CONFIG, scale="S01", scenario="balanced", seed=101)
    constrained = build_resources(CONFIG, scale="S01", scenario="compute_constrained", seed=101)
    for base, stressed in zip(balanced, constrained, strict=True):
        assert base["resource_id"] == stressed["resource_id"]
        if base["tier"] == "iot":
            assert stressed["mips"] == base["mips"]
        else:
            assert stressed["mips"] == base["mips"] * 3 // 4
        assert stressed["active_power_mw"] == base["active_power_mw"]
        assert stressed["price_ncu_per_second"] == base["price_ncu_per_second"]


def test_network_constrained_route_uses_exact_segment_math():
    balanced = build_network(CONFIG, scenario="balanced")
    stressed = build_network(CONFIG, scenario="network_constrained")
    assert stressed["segments"]["iot_fog_wireless"] == {
        "bandwidth_mbps": 40,
        "latency_us": 12500,
        "energy_pj_per_bit": 243750,
    }
    assert stressed["segments"]["fog_lan"] == balanced["segments"]["fog_lan"]

    metrics = route_metrics(
        balanced,
        source_tier="iot",
        target_tier="cloud",
        same_resource=False,
        data_bits=8000,
    )
    assert metrics["communication_time_us"] == 25096
    assert metrics["communication_energy_pj"] == 8000 * (162500 + 16660)


def test_same_resource_communication_is_zero():
    network = build_network(CONFIG, scenario="balanced")
    assert route_metrics(network, source_tier="fog", target_tier="fog", same_resource=True, data_bits=999) == {
        "communication_time_us": 0,
        "communication_energy_pj": 0,
    }


def test_base_instance_stores_compact_inputs_and_derives_routes():
    workflow = normalize_dax(DAX, family="montage", target_task_count=2, replicate_id="r01")
    instance = build_base_instance(workflow, CONFIG, scale="S01", scenario="balanced", seed=101)
    assert instance["metadata"]["base_instance_id"].startswith(
        "base-v1-draft-wf-montage-0002-r01-"
    )
    assert instance["content_sha256"] == content_sha256(instance)
    assert instance["metadata"]["resource_count"] == 10
    assert instance["execution_time_us"]["A"]["iot-001"] == 2_500_000
    assert instance["compute_cost_ncu"]["A"]["iot-001"] == 0
    assert instance["compute_energy_nj"]["A"]["iot-001"] == 3_500 * 2_500_000
    assert "communication" not in instance

    tiers = {resource["resource_id"]: resource["tier"] for resource in instance["resources"]}
    same = resource_route_metrics(
        instance["network"],
        tiers,
        source_resource_id="iot-001",
        target_resource_id="iot-001",
        data_bits=instance["dependencies"][0]["data_bits"],
    )
    cross = resource_route_metrics(
        instance["network"],
        tiers,
        source_resource_id="iot-001",
        target_resource_id="cloud-001",
        data_bits=instance["dependencies"][0]["data_bits"],
    )
    assert same == {"communication_time_us": 0, "communication_energy_pj": 0}
    assert cross["communication_time_us"] == 25096


def test_base_instance_is_byte_stable_after_sorted_json_serialization():
    workflow = normalize_dax(DAX, family="montage", target_task_count=2, replicate_id="r01")
    first = build_base_instance(workflow, CONFIG, scale="S01", scenario="network_constrained", seed=202)
    second = build_base_instance(workflow, CONFIG, scale="S01", scenario="network_constrained", seed=202)
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"))
    assert encode(first) == encode(second)


def test_config_loader_enforces_core_v1_invariants(tmp_path):
    path = tmp_path / "benchmark.yaml"
    path.write_text(
        """
source_workflows: {}
workflows:
  task_count_policy: exact
  allowed_size_deviation: 0
infrastructure:
  concurrency_slots_per_resource: 1
network: {}
scenario_profiles: {}
replications: {}
cost_model: {}
""".strip(),
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded["workflows"]["allowed_size_deviation"] == 0

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "allowed_size_deviation: 0", "allowed_size_deviation: 5"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="exact task counts"):
        load_config(path)
