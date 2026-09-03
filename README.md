# IFC Workflow Benchmark Dataset

This repository is the canonical dataset repository for the Intelligent Workflow Scheduling in IoT–Fog–Cloud research project.

## Research principle

The benchmark dataset must be designed and frozen before any proposed scheduling algorithm is tuned against it. Every baseline and future algorithm must consume the same immutable instances, resource descriptions, constraints, and reference values.

## Current stage

**Stage 1 — Dataset specification**

The v1 draft now defines the candidate benchmark dimensions, reference-makespan/deadline methodology, deadline-conditioned budget methodology, IoT–Fog–Cloud resource model, and reproducibility/freeze rules. Dataset generation has not started yet.

### Candidate v1 matrix

- Workflow families: Montage, CyberShake, LIGO, SIPHT, Genome
- Workflow sizes: 50, 100, 200, 400, 600, 800, 1000 tasks
- Resource scales: S01, S02, S03
- Scenario profiles: balanced, compute-constrained, network-constrained
- Replication seeds: 101, 202, 303
- Joint QoS profiles: tight, moderate, relaxed

Each joint QoS profile has a paired deadline and budget:

- tight: deadline `5/4 × T_ref`, budget gap `1/10`
- moderate: deadline `3/2 × T_ref`, budget gap `1/2`
- relaxed: deadline `2 × T_ref`, budget gap `9/10`

The budget gap is measured between the cheapest calibration schedule known to satisfy that deadline and the deterministic HEFT schedule cost. Each primary instance therefore has a stored joint deadline-budget feasibility witness.

The candidate matrix contains:

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
│   ├── BUDGET_STRATEGY.md
│   ├── RESOURCE_MODEL.md
│   ├── WORKFLOW_MODEL.md
│   ├── PARAMETER_PROVENANCE.md
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

- `docs/DATASET_SPECIFICATION.md` — candidate benchmark contract and instance model.
- `docs/DEADLINE_STRATEGY.md` — theoretical lower bounds, deterministic HEFT reference makespan, and exact rational deadline factors.
- `docs/BUDGET_STRATEGY.md` — exact cost representation, deadline-conditioned cost calibration, budget factors, and joint feasibility witnesses.
- `docs/RESOURCE_MODEL.md` — IoT/Fog/Cloud tiers, resource scales, scenario profiles, cost/energy/network semantics.
- `docs/WORKFLOW_MODEL.md` — Pegasus workflow normalization and task/dependency semantics.
- `docs/PARAMETER_PROVENANCE.md` — provenance and status of numerical resource/network assumptions.
- `docs/REPRODUCIBILITY.md` — seed separation, deterministic regeneration, manifests, and freeze policy.
- `config/benchmark-v1.yaml` — machine-readable candidate benchmark matrix and QoS calibration settings.

## Decisions still required before v1 freeze

The following remain deliberately unresolved rather than hidden behind arbitrary constants:

- final evidence-backed compute/memory/power/price ranges per tier;
- final network bandwidth/latency/energy values;
- dimensionally valid network-energy model;
- tolerance/rule for requested versus generated workflow task count;
- pilot validation of the S01/S02/S03 resource counts;
- pilot confirmation that the calibration frontier creates useful nondegenerate cost ranges.

## Experimental workflow

1. Specify and review the benchmark.
2. Lock supported numerical ranges using literature/specification evidence.
3. Implement deterministic generator, calibration utilities, schemas, and validators.
4. Generate a small pilot benchmark and inspect distributions/trade-offs.
5. Adjust only pre-declared candidate parameters when pilot validation demonstrates a benchmark-design problem.
6. Generate and freeze dataset version 1.
7. Run every baseline algorithm on the same frozen instances.
8. Analyse scheduling failures, constraint violations, and trade-offs.
9. Formulate the novel algorithm only after those empirical weaknesses are understood.

## Status

The candidate v1 benchmark specification is under review on `feature/dataset-spec-v1`. No generated benchmark instance is frozen yet.
