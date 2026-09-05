# Pilot Materialization and QoS Construction — v1

## Purpose

This phase turns the outcome-independent 200-entry pilot selection into authoritative IFC scheduling inputs. It does not select new candidates and it does not run comparative experimental algorithms.

The frozen input selection remains exactly:

- 160 development entries;
- 40 holdout entries;
- candidate identities from `manifests/pilot-selection-v1.json`.

Holdout calibration is permitted because it constructs the stored deadline and budget of an input. Comparative holdout scheduler outcomes remain unopened until the proposed mechanism and parameters are frozen.

## Identity preservation

The frozen `candidate_id` becomes the materialized QoS `instance_id`. Materialization may not rename, replace, add, or omit selected candidates.

Several selected QoS entries can share one workflow/resource/scenario/seed realization. Such entries share one `base_instance_id`, one base IFC artifact, and one calibration artifact. The base and calibration are generated once and reused for all selected QoS profiles attached to that base realization.

## Base and calibration construction

For each distinct selected base realization:

1. read the checksum-addressed frozen DAX;
2. normalize it using the committed benchmark configuration;
3. build the deterministic IFC base instance;
4. run the frozen calibration portfolio once;
5. write the base and calibration artifacts;
6. materialize every selected QoS profile that references the base.

The implementation processes one base group at a time so memory usage is bounded by the current base, calibration population, and associated QoS outputs rather than the complete 200-input pilot.

## Compact communication representation

The base instance stores the information that defines communication rather than a redundant dependency-by-resource-pair expansion:

- each dependency stores its authoritative `data_bits`;
- each resource stores its tier;
- the base stores the scenario-adjusted network segments and frozen route definitions;
- `generator.network.resource_route_metrics(...)` derives the exact transfer time and network energy for a concrete source/target resource pair.

`generator.schedule` and every frozen reference scheduler use this same derivation boundary. Same-resource communication remains exactly zero. Different resources in the same tier and cross-tier placements use the same frozen routes and exact integer formulas as before.

This is a representation change, not a scheduling-model change. Before the benchmark is frozen, the originally expanded `edge × source-resource × target-resource` matrix was removed because every stored value was deterministically reconstructible from the compact authoritative inputs.

## Deadline materialization

For profile fraction `alpha = p/q`:

`D = T_fast + ceil(p * (T_economical - T_fast) / q)`

The frozen fractions are:

- tight: `1/10`;
- moderate: `1/2`;
- relaxed: `9/10`.

All arithmetic is integer/rational. Binary floating point is not authoritative.

## Deadline-conditioned cost floor

Let `P_cal` be the complete stored calibration schedule set. For deadline `D`:

`F(D) = {S in P_cal | makespan(S) <= D}`

The joint witness `S_floor(D)` is chosen deterministically by:

1. minimum exact compute cost;
2. lower makespan;
3. lexicographically lower complete task-to-resource mapping;
4. canonical schedule ID.

Then:

`C_floor_ref(D) = cost(S_floor(D))`

The mapping-level tie break is recorded explicitly because schedule IDs contain timed assignments; using the mapping before the schedule ID keeps the budget-witness policy aligned with the frozen scheduling decision itself.

## Budget materialization

For profile fraction `beta = p/q`:

`B = C_floor_ref(D) + floor(p * (C_fast - C_floor_ref(D)) / q)`

The paired fractions are:

- tight: `1/10`;
- moderate: `1/2`;
- relaxed: `9/10`.

The stored joint witness has cost exactly `C_floor_ref(D)`, so by construction it satisfies both the deadline and the materialized budget.

## Artifact layout

The materializer writes into a previously absent or empty output directory through a temporary staging directory. It replaces the destination only after generation succeeds.

```text
<pilot-root>/
├── base/
│   └── <base_instance_id>.json
├── calibration/
│   └── <base_instance_id>.json
└── instances/
    ├── development/
    │   └── <candidate_id>.json
    └── holdout/
        └── <candidate_id>.json
```

A separate `pilot-materialization` manifest records:

- the exact frozen selection ID and checksum;
- configuration and source-manifest checksums;
- generator commit SHA;
- exact development/holdout counts;
- every distinct base artifact and file checksum;
- every calibration artifact, file checksum, and candidate-set checksum;
- every materialized candidate, split, dimensions, base identity, path, and file checksum;
- its own canonical content checksum.

## Validation

Full validation must verify all of the following:

1. the pilot selection exactly reproduces from the frozen configuration, source manifest, selector version, and seed;
2. the materialization contains exactly the same 200 candidate IDs and the same 160/40 split;
3. source files match their frozen checksums;
4. base artifacts deterministically regenerate from source + configuration;
5. calibration schedules re-evaluate against their exact base instances;
6. QoS deadline and budget fields reconstruct exactly;
7. each QoS instance reconstructs from its frozen selection entry and calibration artifact;
8. each stored joint witness passes the authoritative evaluator under the stored deadline and budget;
9. every referenced artifact checksum matches its file bytes.

The full validator command is:

```bash
python -m validation.cli pilot-materialization \
  --manifest <pilot-materialization-manifest.json> \
  --dataset-root <pilot-root> \
  --config config/benchmark-v1.yaml \
  --source-manifest manifests/source-workflows-v1.json \
  --pilot-selection manifests/pilot-selection-v1.json \
  --source-root source_workflows
```

## Observed large-instance sizing gate

The storage/memory risk was measured on the real frozen Montage 1000-task source with S03, balanced networking, and IFC seed 101.

The first measurement exposed the redundant expanded communication matrix. After replacing it with the compact derivation boundary, the same case produced:

| Measure | Expanded representation | Compact representation |
| --- | ---: | ---: |
| Base JSON raw bytes | 363,028,528 | 3,630,983 |
| Base JSON gzip bytes | 13,497,787 | 245,296 |
| Base-build peak RSS | 2,195,180 kB | 43,732 kB |
| Base-build wall time | about 15.00 s | 0.27 s |
| Calibration JSON raw bytes | 4,673,429 | 4,673,429 |
| Calibration JSON gzip bytes | 677,064 | 677,064 |
| Calibration peak RSS | about 1,505,600 kB | 84,028 kB |
| Calibration wall time | about 55.69 s | 85.02 s |

The compact representation therefore removes roughly two orders of magnitude of base-instance storage and memory while preserving the same validated 54-schedule calibration candidate set. The extra calibration CPU time is accepted at the pilot stage because it avoids storing or retaining the full `E × R²` expansion and keeps the authoritative representation small.

## Full-pilot storage gate

The compact representative base is small enough that Git storage is plausible, but the complete 200-input payload is not committed merely from a single-case extrapolation.

The `full-pilot-materialization` workflow now:

1. materializes exactly the frozen 200 entries from the exact generator head;
2. fully validates every source/base/calibration/QoS/witness relationship;
3. reports the number of distinct base realizations, development/holdout counts, deadline/budget degeneracy counts, and raw payload size;
4. creates a compressed archive to measure total compressed size;
5. publishes a short-retention review artifact.

Permanent payload storage is chosen only after this complete observed size is reviewed. The checksummed materialization manifest remains the authoritative provenance index regardless of the eventual payload storage location.
