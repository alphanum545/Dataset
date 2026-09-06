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
- selector: `deterministic-stratified-pairwise` version 2;
- seed: `20260905`;
- selected inputs: 200;
- development split: 160;
- holdout split: 40;
- holdout bases: exactly 40 distinct base realizations;
- development/holdout base overlap: exactly 0.

The exact marginal targets are committed in `config/benchmark-v1.yaml`. The category receiving the smaller ternary count rotates across dimensions so the same category index is not systematically underrepresented.

The selector constructs the holdout and development splits from exact marginal quotas. SHA-256-derived ordering is used only for deterministic tie-breaking. For every assigned dimension, it prioritizes unseen pairs with dimensions already assigned, then lower existing pair counts, remaining quota, and finally the seeded hash.

It evaluates a fixed 256 deterministic constructions per split and selects the design with maximum pairwise coverage and minimum pair-count imbalance. Candidate tuples must be unique and belong to the enumerated universe.

## Base-level holdout isolation

A candidate QoS identity contains six experimental dimensions, but the underlying base IFC realization excludes `qos_profile`. Base isolation therefore uses:

- workflow family;
- exact task count;
- source replicate, which also fixes the IFC realization seed;
- resource scale;
- scenario profile.

Selector v2 adds two structural constraints before any QoS instance is materialized:

1. all 40 holdout entries must have distinct base signatures;
2. every holdout base signature is forbidden from the development split, even under a different QoS profile.

Development may contain more than one QoS entry for the same development-only base. The current deterministic v2 selection has 160 development entries over 159 unique development bases, 40 holdout entries over 40 unique holdout bases, and zero cross-split base overlap.

### Why selector v2 replaced selector v1

An identity-only preflight of selector v1 found 10 base realizations present in both development and holdout under different QoS profiles. That would weaken the claim that holdout workflows/resource environments are unseen during development.

This was detected before full pilot materialization and before any comparative holdout scheduler outcome was generated or opened. The correction therefore uses no performance outcome, feasibility result, placement result, or objective value. Selector v2 retains the original seed, 200/160/40 counts, exact marginal quotas, and complete overall/holdout pairwise coverage while adding base-disjoint holdout protection.

The manifest filename and selection ID remain `pilot-selection-v1` because this is still the pre-freeze v1 benchmark candidate; `selector_version: 2` records the algorithmic correction explicitly.

## Holdout protection

The holdout contains exactly 40 inputs, including eight from every workflow family. It has predeclared near-balanced task-count and ternary-factor marginals, complete pairwise factor coverage, 40 distinct base realizations, and zero base overlap with development.

Rules:

1. Development outcomes may be inspected to diagnose baselines and formulate/tune the proposed algorithm.
2. Holdout reference calibration may run automatically because deadlines and budgets are input data, but comparative algorithm outcomes must not be inspected during development.
3. Proposed-algorithm mechanism and parameters are frozen before its holdout results are opened.
4. Every reported comparative algorithm runs on the identical holdout entries and constraints.
5. Extra proposed-only runs may support scalability or stability analysis, not superiority claims.
6. A holdout base may never be reintroduced into development merely by changing the QoS profile.

## Manifest integrity

`manifests/pilot-selection-v1.json` stores:

- canonical checksums of parsed configuration and source manifest;
- the complete candidate-universe identity checksum;
- selector identity, version, seed, and attempt count;
- every selected identity and source checksum;
- development/holdout label;
- exact overall and split marginals;
- observed and possible pairwise coverage;
- development and holdout unique-base counts plus cross-split overlap count;
- a canonical content checksum.

Validation recomputes base signatures from the selected entries and rejects a manifest whose `base_isolation` metadata does not match the entries themselves.

The selection manifest is not the final dataset manifest and contains no fabricated artifact checksums. Materialized base/QoS paths and checksums belong to the later materialization manifest.

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

Any post-freeze change to configuration, source-manifest content, seed, quotas, selector implementation, or selected entry requires a new benchmark/selection version. Selector v2 is the final pre-freeze integrity correction to the v1 pilot candidate unless a later validation gate demonstrates another predeclared benchmark-design defect before comparative holdout outcomes are opened.
