# Deterministic 200-Instance Pilot Selection

## Purpose

The 200-instance pilot is the common development benchmark used to implement references, diagnose existing schedulers, and formulate the proposed algorithm without immediately materializing all 2,835 candidate QoS inputs.

Selection is performed before scheduler outcomes are observed. The selector never reads makespan, cost, energy, placement, feasibility, or runtime results.

## Candidate universe

The selector first enumerates identities only:

`5 families × 7 task counts × 3 source replicates × 3 resource scales × 3 scenarios × 3 QoS profiles = 2,835 candidates`

Every identity resolves to one frozen source-manifest entry and its checksum. Enumeration does not normalize DAX files or materialize IFC/QoS artifacts.

## Frozen selector

- selection ID: `pilot-selection-v1`;
- selector: `deterministic-stratified-pairwise` version 1;
- seed: `20260905`;
- selected inputs: 200;
- development split: 160;
- holdout split: 40.

The exact marginal targets are committed in `config/benchmark-v1.yaml`. The category receiving the smaller ternary count rotates across dimensions so the same category index is not systematically underrepresented.

The selector constructs the holdout and development splits from exact marginal quotas. SHA-256-derived ordering is used only for deterministic tie-breaking. For every assigned dimension, it prioritizes unseen pairs with dimensions already assigned, then lower existing pair counts, remaining quota, and finally the seeded hash.

It evaluates a fixed 256 deterministic constructions per split and selects the design with maximum pairwise coverage and minimum pair-count imbalance. Candidate tuples must be unique and belong to the enumerated universe.

## Holdout protection

The holdout contains exactly 40 inputs, including eight from every workflow family. It has predeclared near-balanced task-count and ternary-factor marginals and complete pairwise factor coverage.

Rules:

1. Development outcomes may be inspected to diagnose baselines and formulate/tune the proposed algorithm.
2. Holdout reference calibration may run automatically because deadlines and budgets are input data, but comparative algorithm outcomes must not be inspected during development.
3. Proposed-algorithm mechanism and parameters are frozen before its holdout results are opened.
4. Every reported comparative algorithm runs on the identical holdout entries and constraints.
5. Extra proposed-only runs may support scalability or stability analysis, not superiority claims.

## Manifest integrity

`manifests/pilot-selection-v1.json` stores:

- canonical checksums of parsed configuration and source manifest;
- the complete candidate-universe identity checksum;
- selector identity, version, seed, and attempt count;
- every selected identity and source checksum;
- development/holdout label;
- exact overall and split marginals;
- observed and possible pairwise coverage;
- a canonical content checksum.

The selection manifest is not the final dataset manifest and contains no fabricated artifact checksums. Materialized base/QoS paths and checksums belong to the later dataset manifest.

## Commands

Generate the manifest:

```bash
python -m generator.cli select-pilot \
  --config config/benchmark-v1.yaml \
  --source-manifest manifests/source-workflows-v1.json \
  --output manifests/pilot-selection-v1.json
```

Reproduce and validate it:

```bash
python -m validation.cli pilot-selection \
  --manifest manifests/pilot-selection-v1.json \
  --config config/benchmark-v1.yaml \
  --source-manifest manifests/source-workflows-v1.json
```

Any change to configuration, source-manifest content, seed, quotas, selector implementation, or selected entry changes a recorded checksum and requires an explicit new selection version after freeze.
