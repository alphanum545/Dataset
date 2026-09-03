# IFC Workflow Benchmark Dataset

This repository is the canonical dataset repository for the Intelligent Workflow Scheduling in IoT–Fog–Cloud research project.

## Research principle

The benchmark dataset must be designed and frozen before any proposed scheduling algorithm is tuned against it. Every baseline and future algorithm must consume the same immutable instances, resource descriptions, constraints, and reference values.

## Current stage

**Stage 1 — Dataset specification**

The v1 draft now defines the candidate benchmark dimensions, reference-makespan/deadline methodology, IoT–Fog–Cloud resource model, and reproducibility/freeze rules. Dataset generation has not started yet.

### Candidate v1 matrix

- Workflow families: Montage, CyberShake, LIGO, SIPHT, Genome
- Workflow sizes: 50, 100, 200, 400, 600, 800, 1000 tasks
- Resource scales: S01, S02, S03
- Scenario profiles: balanced, compute-constrained, network-constrained
- Replication seeds: 101, 202, 303
- Deadline levels: 1.25×, 1.50×, 2.00× deterministic reference makespan

If each deadline level is materialized as a separate scheduling instance, the candidate matrix contains:

`5 × 7 × 3 × 3 × 3 × 3 = 2,835 instances`

With seven algorithms, that corresponds to `19,845` algorithm-instance runs before repeated stochastic algorithm seeds are added.

## Repository structure

```text
Dataset/
├── README.md
├── AGENTS.md
├── docs/
│   ├── DATASET_SPECIFICATION.md
│   ├── DEADLINE_STRATEGY.md
│   ├── RESOURCE_MODEL.md
│   └── REPRODUCIBILITY.md
├── config/
│   └── benchmark-v1.yaml
├── generator/
├── schemas/
├── validation/
├── datasets/
├── manifests/
└── tests/
```

## Current design documents

- `docs/DATASET_SPECIFICATION.md` — complete candidate benchmark contract and instance model.
- `docs/DEADLINE_STRATEGY.md` — lower bounds, deterministic HEFT reference makespan, and deadline factors.
- `docs/RESOURCE_MODEL.md` — IoT/Fog/Cloud tiers, resource scales, scenario profiles, cost/energy/network semantics.
- `docs/REPRODUCIBILITY.md` — seed separation, deterministic regeneration, manifests, and freeze policy.
- `config/benchmark-v1.yaml` — machine-readable candidate benchmark matrix.

## Decisions still required before v1 freeze

The following are deliberately not hidden behind arbitrary constants:

- exact compute/memory/power/price ranges per tier;
- exact network bandwidth/latency/energy values;
- tolerance for requested versus generated workflow task count;
- final validation of the S01/S02/S03 resource counts;
- budget-reference and budget-factor methodology;
- literature/provenance support for numerical parameter ranges.

## Experimental workflow

1. Specify and review the benchmark.
2. Lock supported numerical ranges using literature/specification evidence.
3. Implement a deterministic generator and schemas.
4. Validate generated candidate instances and distributions.
5. Freeze dataset version 1.
6. Run every baseline algorithm on the same frozen instances.
7. Analyse scheduling failures, constraint violations, and trade-offs.
8. Formulate the novel algorithm only after those empirical weaknesses are understood.

## Status

The candidate v1 benchmark specification is now under review on a feature branch. No generated benchmark instance is frozen yet.
