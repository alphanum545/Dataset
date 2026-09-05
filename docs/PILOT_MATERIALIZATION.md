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

## Storage decision gate

The full generated pilot is not automatically committed to Git. The base instance representation contains a route-specific communication entry for every dependency and resource pair, and large S03 realizations can therefore be substantial.

Before selecting permanent storage, the repository runs a representative real 1000-task/S03 sizing smoke and records:

- raw base-instance size;
- compressed base-instance size;
- raw calibration-artifact size;
- compressed calibration-artifact size;
- peak resident memory;
- runtime for base construction and calibration.

The storage decision must be based on these observed values. The checksummed materialization manifest remains the authoritative provenance index regardless of whether payload files are ultimately stored in Git or another durable artifact store.
