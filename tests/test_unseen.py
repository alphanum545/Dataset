import json
from decimal import Decimal
from hashlib import sha256

import pytest

from generator.config import load_config
from generator.dax import DaxValidationError, normalize_dax
from generator.materialize import selected_base_instance_id
from generator.unseen import (
    acquire_wfcommons_one,
    attempt_seed,
    build_group,
    enumerate_entries,
    expected_source_count,
    load_unseen_config,
    merge_manifests,
)
from generator.wfformat import WfFormatValidationError, normalize_source, normalize_wfformat


def wf(tasks, files, runtimes):
    """Minimal WfFormat 1.5+ document; tasks = {id: (parents, inputs, outputs)}."""
    children = {t: [] for t in tasks}
    for t, (parents, _, _) in tasks.items():
        for p in parents:
            children[p].append(t)
    return {
        "name": "tiny",
        "schemaVersion": "1.5",
        "workflow": {
            "specification": {
                "tasks": [
                    {"name": t, "id": t, "parents": list(p), "children": children[t],
                     "inputFiles": list(i), "outputFiles": list(o)}
                    for t, (p, i, o) in tasks.items()
                ],
                "files": [{"id": f, "sizeInBytes": s} for f, s in files.items()],
            },
            "execution": {
                "makespanInSeconds": 0.0,
                "executedAt": "20260101T000000+0000",
                "tasks": [{"id": t, "runtimeInSeconds": r} for t, r in runtimes.items()],
            },
        },
    }


def dumps(doc):
    return json.dumps(doc, indent=4).encode()


TINY = wf(
    {"A": ([], ["in.dat"], ["x.dat", "y.dat"]),
     "B": (["A"], ["x.dat"], ["b.out"]),
     "C": (["A"], ["x.dat", "y.dat"], ["c.out"])},
    {"in.dat": 5, "x.dat": 1000, "y.dat": 24, "b.out": 7, "c.out": 9},
    {"A": 1.25, "B": 2.5, "C": 0.001},
)


def test_wfformat_matches_dax_rules():
    out = normalize_wfformat(dumps(TINY), family="srasearch", target_task_count=3, replicate_id="r01")
    assert [t["task_id"] for t in out["tasks"]] == ["A", "B", "C"]
    assert out["tasks"][0]["source_runtime_s"] == "1.25"
    assert out["tasks"][0]["work_mi"] == "1250.00"
    assert out["tasks"][2]["work_mi"] == "1.000"
    deps = {(d["parent"], d["child"]): d for d in out["dependencies"]}
    assert list(deps) == [("A", "B"), ("A", "C")]
    assert deps["A", "B"]["data_bytes"] == 1000 and deps["A", "B"]["data_bits"] == 8000
    assert deps["A", "C"]["data_bytes"] == 1024  # sum of shared producer outputs
    assert [f["name"] for f in deps["A", "C"]["transfer_files"]] == ["x.dat", "y.dat"]
    assert out["metadata"]["workflow_id"].startswith("wf-srasearch-0003-r01-")


def test_wfformat_equals_equivalent_dax():
    dax = '''<?xml version="1.0"?>
<adag xmlns="http://pegasus.isi.edu/schema/DAX" version="3.3" name="tiny">
  <job id="A" runtime="1.25"><uses file="in.dat" link="input" size="5"/>
    <uses file="x.dat" link="output" size="1000"/><uses file="y.dat" link="output" size="24"/></job>
  <job id="B" runtime="2.5"><uses file="x.dat" link="input" size="1000"/><uses file="b.out" link="output" size="7"/></job>
  <job id="C" runtime="0.001"><uses file="x.dat" link="input" size="1000"/><uses file="y.dat" link="input" size="24"/>
    <uses file="c.out" link="output" size="9"/></job>
  <child ref="B"><parent ref="A"/></child><child ref="C"><parent ref="A"/></child>
</adag>'''
    a = normalize_dax(dax, family="x", target_task_count=3, replicate_id="r01")
    b = normalize_wfformat(dumps(TINY), family="x", target_task_count=3, replicate_id="r01")
    assert a["tasks"] == b["tasks"]
    assert a["dependencies"] == b["dependencies"]


def test_wfformat_runtime_is_exact_decimal():
    doc = wf({"A": ([], [], ["o"])}, {"o": 1}, {"A": 0.1})
    raw = dumps(doc).replace(b'"runtimeInSeconds": 0.1', b'"runtimeInSeconds": 0.30000000000000004')
    out = normalize_wfformat(raw, family="x", target_task_count=1, replicate_id="r01")
    assert out["tasks"][0]["source_runtime_s"] == "0.30000000000000004"
    assert Decimal(out["tasks"][0]["work_mi"]) == Decimal("300.00000000000004")


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["workflow"]["specification"]["tasks"][1].__setitem__("inputFiles", ["b.out"]), "no shared file"),
    (lambda d: d["workflow"]["execution"]["tasks"][0].__setitem__("runtimeInSeconds", 0), "> 0"),
    (lambda d: d["workflow"]["specification"]["tasks"][1].__setitem__("inputFiles", ["zzz"]), "undeclared"),
    (lambda d: d["workflow"]["specification"]["tasks"][0].__setitem__("children", ["C"]), "missing from"),
    (lambda d: d["workflow"]["execution"]["tasks"].pop(), "task sets differ"),
])
def test_wfformat_rejects_invalid_sources(mutate, message):
    doc = json.loads(dumps(TINY))
    mutate(doc)
    with pytest.raises(WfFormatValidationError, match=message):
        normalize_wfformat(dumps(doc), family="x", target_task_count=3, replicate_id="r01")


def test_wfformat_rejects_wrong_count_and_cycles():
    with pytest.raises(WfFormatValidationError, match="exact target"):
        normalize_wfformat(dumps(TINY), family="x", target_task_count=4, replicate_id="r01")
    cyc = wf({"A": (["B"], ["b"], ["a"]), "B": (["A"], ["a"], ["b"])}, {"a": 1, "b": 1}, {"A": 1, "B": 1})
    with pytest.raises(WfFormatValidationError, match="cycle"):
        normalize_wfformat(dumps(cyc), family="x", target_task_count=2, replicate_id="r01")
    assert issubclass(WfFormatValidationError, DaxValidationError)


def test_normalize_source_dispatch(tmp_path):
    p = tmp_path / "w.json"
    p.write_bytes(dumps(TINY))
    assert normalize_source(p, family="x", target_task_count=3, replicate_id="r01")["metadata"]["actual_task_count"] == 3
    with pytest.raises(ValueError):
        normalize_source(tmp_path / "w.txt", family="x", target_task_count=3, replicate_id="r01")


def test_wfcommons_acquisition_policy_exact_count_and_request_schedule():
    calls = []
    policy = {"request_offset": 2, "attempts_per_request": 2, "max_attempts_per_replicate": 10}

    def emit(recipe, num_tasks, seed):
        calls.append((num_tasks, seed))
        # only num_tasks == 6 (target 3 + 2 + 1 increase) produces exactly 3 tasks
        if num_tasks < 6:
            return dumps(wf({"A": ([], [], ["o"])}, {"o": 1}, {"A": 1}))  # 1 task: rejected
        doc = json.loads(dumps(TINY))
        doc["name"] = f"seed{seed}"
        return dumps(doc)

    raw, meta = acquire_wfcommons_one(family="srasearch", recipe_name="SrasearchRecipe", target=3,
                                      replicate_id="r01", policy=policy, used_checksums=set(),
                                      reference_mips=1000, emit=emit)
    assert [c[0] for c in calls] == [5, 5, 6]
    assert meta["acquisition_attempt"] == 3 and meta["requested_num_tasks"] == 6
    assert meta["rng_seed"] == attempt_seed("srasearch", 3, "r01", 3)
    assert meta["sha256"] == sha256(raw).hexdigest()

    # the same output again is a duplicate and must be skipped
    with pytest.raises(Exception, match="unable to acquire"):
        acquire_wfcommons_one(family="srasearch", recipe_name="SrasearchRecipe", target=3,
                              replicate_id="r01", policy={**policy, "max_attempts_per_replicate": 1},
                              used_checksums={sha256(dumps(TINY)).hexdigest()}, reference_mips=1000,
                              emit=lambda r, n, s: dumps(TINY))


def test_repository_unseen_config():
    unseen = load_unseen_config("config/unseen-v1.yaml")
    assert expected_source_count(unseen) == 5 * 7 * 1 + (7 + 7 + 6) * 2 == 75
    assert "montage" not in unseen["new_families"]["families"]
    assert "epigenomics" not in unseen["new_families"]["families"]


def _manifest(unseen, entries):
    return merge_manifests(unseen, [{"entries": entries}], unseen_config_sha256="0" * 64,
                           model_config_sha256="1" * 64)


def test_entries_full_factorial_and_identity(tmp_path):
    unseen = load_unseen_config("config/unseen-v1.yaml")
    unseen = {**unseen, "new_replicates": {**unseen["new_replicates"], "families": []},
              "new_families": {**unseen["new_families"],
                               "families": {"srasearch": {"recipe": "SrasearchRecipe", "requested_task_counts": [3]}},
                               "replicates": ["r01"]}}
    model = load_config("config/benchmark-v1.yaml")
    raw = dumps(TINY)
    rel = "unseen-v1/wfcommons-e5418e13/srasearch/0003/r01.json"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(raw)
    src = {"family": "srasearch", "target_task_count": 3, "replicate_id": "r01", "kind": "new_family",
           "sha256": sha256(raw).hexdigest(), "path": rel}
    man = _manifest(unseen, [src])
    entries = enumerate_entries(unseen, model, man)
    assert len(entries) == 3 * 3 * 3
    for e in entries:
        assert e["base_instance_id"] == selected_base_instance_id(e, model)
        assert e["split"] == "unseen_evaluation" and e["ifc_realization_seed"] == 101

    group = [e for e in entries if e["base_instance_id"] == entries[0]["base_instance_id"]]
    files = build_group(tmp_path, group, model)
    assert len(files) == 1 + 3
    for e in group:
        inst = json.loads(files[e["path"]])
        assert inst["instance_id"] == e["candidate_id"]
        assert inst["base_instance_id"] == e["base_instance_id"]
        assert inst["profile"] == e["qos_profile"]
        assert inst["deadline"]["deadline_us"] >= inst["deadline"]["t_fast_us"] > 0
        assert inst["budget"]["budget_ncu"] >= inst["budget"]["cost_floor_ref_ncu"]
    # deterministic: the same group rebuilds to identical bytes
    assert build_group(tmp_path, group, model) == files


def test_merge_rejects_missing_or_duplicate_sources():
    unseen = load_unseen_config("config/unseen-v1.yaml")
    with pytest.raises(Exception, match="expected 75"):
        _manifest(unseen, [])
