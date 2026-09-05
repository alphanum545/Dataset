# IFC Workflow Benchmark Dataset

This repository is the canonical dataset repository for the Intelligent Workflow Scheduling in IoT-Fog-Cloud research project.

## Research principle

The benchmark dataset is designed and frozen before any proposed scheduling algorithm is tuned against it. Every baseline and future algorithm consumes the same immutable workflow instances, resources, network conditions, constraints, and reference values.

## Current stage

**Stage 3 — pilot IFC benchmark generation and validation.**

The v1 pilot specification, deterministic generator core, source-workflow acquisition, outcome-independent 200-input selector, and frozen deterministic calibration portfolio are implemented. The 105 exact-size Pegasus/Bharathi source DAX artifacts are committed together with `manifests/source-workflows-v1.json`. The selected pilot remains split into 160 development and 40 protected holdout inputs before calibration outcomes are observed.

The v1 pilot candidate defines:

- five Pegasus/Bharathi workflow families;
- seven exact task-count levels;
- three frozen source-workflow replicates per family/size;
- three IoT/Fog/Cloud resource scales;
- balanced, compute-constrained, and network-constrained profiles;
- exact execution, cost, compute-energy, and routed network-energy units;
- a multi-scheduler IFC fast-to-economical deadline envelope;
- deterministic stratified selection of 200 pilot inputs;
- deterministic HEFT-IFC, PEFT-IFC, CPOP-IFC, cost-reference-IFC, and MOHEFT calibration;
- deadline-conditioned budget calibration and joint-feasibility witnesses;
- source acquisition, reproducibility, validation, and freeze rules.

No materialized IFC benchmark instance is frozen yet. The next step is to materialize only the selected 200 base IFC inputs, run the frozen calibration portfolio, and validate envelope/budget behavior before any proposed-algorithm tuning.

## Candidate v1 matrix

- Workflow families: Montage, CyberShake, LIGO, SIPHT, Genome
- Exact workflow sizes: 60, 100, 200, 400, 600, 800, 1000 tasks
- Frozen source replicates: r01, r02, r03
- Resource scales: S01, S02, S03
- Scenario profiles: balanced, compute-constrained, network-constrained
- Joint QoS profiles: tight, moderate, relaxed

The original candidate smallest size was 50. Full acquisition against the pinned Genome generator proved that an exact 50-task Genome DAG is structurally unreachable under its task-construction model. The common smallest size was therefore changed to 60 rather than relabelling an approximate workflow. Exact task counts remain mandatory for every family.

Source workflows:

`5 × 7 × 3 = 105 frozen raw DAX artifacts`

Benchmark instances:

`105 × 3 resource scales × 3 profiles × 3 QoS profiles = 2,835 instances`

With seven algorithms:

`2,835 × 7 = 19,845 algorithm-instance runs`

before repeated stochastic algorithm seeds are added.

Immediate pilot:

`200 selected inputs = 160 development + 40 holdout`

## Source workflow policy

V1 pins the legacy Pegasus `WorkflowGenerator` Bharathi implementation at commit:

`bb1f8d43fe203f5c2cb209540531998af52000ea`

The upstream implementation supports all five required scientific-workflow families and derives workflow structure/runtime/file-size distributions from real workflows. Because the legacy code contains unseeded randomness, v1 does not claim upstream seed reproducibility. Instead, the first three structurally valid exact-size DAX artifacts for each family/size are frozen and checksum-addressed.

The upstream `--numjobs` value is treated as an acquisition parameter, not as the benchmark size label. The parsed DAX must have the exact benchmark target count. Genome uses the pinned generator's explicit one-lane `--lanes`/`--sequences` construction because its `--numjobs` path cannot represent all configured exact targets reliably.

See `docs/SOURCE_WORKFLOW_ACQUISITION.md`.

## Pilot IFC resource model

Scheduler-visible resources are serial execution slots (`concurrency_slots = 1`) so all baseline algorithms receive compatible processor semantics.

Pilot class envelopes:

- IoT: 500–1000 MIPS
- Fog: 1000–2000 MIPS
- Cloud: 3000–5000 MIPS

The numerical model uses explicit integer units:

- execution time: microseconds
- compute energy: nanojoules
- network energy: picojoules
- normalized cost/budget: nano-normalized-cost units

Communication is routed through explicit wireless/LAN/backbone segments rather than using an unexplained J/MB constant.

All schedulers share the authoritative deterministic construction and verification semantics in `generator.schedule`; see `docs/SCHEDULE_EVALUATION.md`. The frozen calibration algorithms and deterministic IFC adaptations are documented in `docs/REFERENCE_SCHEDULERS.md`.

These numerical values are pilot candidates and must pass sensitivity/trade-off validation before dataset freeze.

## Joint QoS profiles

Each core instance has a paired deadline and budget. Deadlines are interpolated between the fastest and most economical validated schedules in the frozen calibration set:

- tight: time-envelope fraction `1/10`, budget gap `1/10`
- moderate: time-envelope fraction `1/2`, budget gap `1/2`
- relaxed: time-envelope fraction `9/10`, budget gap `9/10`

Budget is measured between the cheapest calibration schedule known to satisfy the corresponding deadline and the fast-anchor schedule cost. Every core instance therefore requires a stored/reproducible schedule satisfying both deadline and budget.

## Repository structure

```text
Dataset/
├── README.md
├── AGENTS.md
├── docs/
│   ├── DATASET_SPECIFICATION.md
│   ├── DEADLINE_STRATEGY.md
│   ├── BUDGET_STRATEGY.md
│   ├── PILOT_SELECTION.md
│   ├── REFERENCE_SCHEDULERS.md
│   ├── SCHEDULE_EVALUATION.md
│   ├── RESOURCE_MODEL.md
│   ├── WORKFLOW_MODEL.md
│   ├── SOURCE_WORKFLOW_ACQUISITION.md
│   ├── PARAMETER_PROVENANCE.md
│   └── REPRODUCIBILITY.md
├── config/
│   └── benchmark-v1.yaml
├── source_workflows/
├── generator/
├── schemas/
├── validation/
├── datasets/
├── manifests/
└── tests/
```

## Calibration commands

Run the frozen portfolio for one materialized base instance:

```bash
python -m generator.cli calibrate-instance \
  --config config/benchmark-v1.yaml \
  --base-instance <base-instance.json> \
  --output <calibration-result.json>
```

Validate all stored candidate schedules against that exact base instance:

```bash
python -m validation.cli calibration-result \
  --result <calibration-result.json> \
  --base-instance <base-instance.json>
```

## Experimental workflow

1. Specify and review benchmark semantics. **Done for pilot candidate.**
2. Implement deterministic source validation and the generator core. **Done.**
3. Acquire and freeze the 105 source DAX artifacts using the predeclared acceptance rule. **Done.**
4. Freeze the outcome-independent 200-input pilot selection. **Done.**
5. Implement the calibration portfolio and materialize only selected pilot inputs. **Calibration implementation done; materialization is next.**
6. Adjust only predeclared pilot parameters if validation demonstrates a benchmark-design problem.
7. Generate and freeze dataset v1.
8. Run every baseline algorithm on the same frozen instances.
9. Analyse failures, constraint violations, placement behavior, cost/energy trade-offs, and scaling.
10. Formulate the novel algorithm only after those weaknesses are empirically understood.

## Status

The v1 raw source-workflow corpus and selected pilot identities are frozen on `main`; the full IFC benchmark is **not frozen yet**. The reference calibration implementation is defined, while pilot materialization, calibration-result generation, deadline/budget witness materialization, feasibility validation, and sensitivity analysis remain.
