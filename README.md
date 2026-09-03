# IFC Workflow Benchmark Dataset

This repository is the canonical dataset repository for the Intelligent Workflow Scheduling in IoT–Fog–Cloud research project.

## Research principle

The benchmark dataset must be designed and frozen before any proposed scheduling algorithm is tuned against it. Every baseline and future algorithm must consume the same immutable instances, resource descriptions, constraints, and reference values.

## Current stage

**Stage 1 — Dataset specification**

The current work is to define and review:

- workflow families and workflow-size levels,
- DAG/task and dependency representation,
- IoT–Fog–Cloud resource model,
- execution-time and communication-time model,
- cost and energy parameters,
- reference-makespan methodology,
- deadline-generation strategy,
- random seeds and reproducibility rules,
- dataset schema and manifests,
- validation requirements.

No benchmark instance should be considered frozen until these choices are documented, reviewed, and validated.

## Planned repository structure

```text
Dataset/
├── README.md
├── docs/
│   ├── DATASET_SPECIFICATION.md
│   ├── DEADLINE_STRATEGY.md
│   ├── RESOURCE_MODEL.md
│   └── REPRODUCIBILITY.md
├── config/
├── generator/
├── schemas/
├── validation/
├── datasets/
├── manifests/
└── tests/
```

## Experimental workflow

1. Specify the benchmark.
2. Implement a deterministic generator.
3. Validate generated instances.
4. Freeze dataset version 1.
5. Run all baseline algorithms on the same frozen instances.
6. Analyse scheduling failures and trade-offs.
7. Formulate the novel algorithm only after the empirical weaknesses are understood.

## Status

The repository has been initialized. Dataset generation has **not** started yet; the specification is being developed first.
