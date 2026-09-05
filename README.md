# IFC Workflow Benchmark Dataset

This repository is the canonical dataset repository for the Intelligent Workflow Scheduling in IoT-Fog-Cloud research project.

## Research principle

The benchmark dataset is designed and frozen before any proposed scheduling algorithm is tuned against it. Every baseline and future algorithm consumes the same immutable workflow instances, resources, network conditions, constraints, and reference values.

## Current stage

**Stage 3 — pilot IFC benchmark generation and validation.**

The v1 pilot specification, deterministic generator core, source-workflow acquisition, outcome-independent 200-input selector, frozen deterministic calibration portfolio, and pilot materialization pipeline are implemented. The 105 exact-size Pegasus/Bharathi source DAX artifacts are committed together with `manifests/source-workflows-v1.json`. The selected pilot remains split into 160 development and 40 protected holdout inputs.

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
- exact materialization of deadline-conditioned budgets and joint-feasibility witnesses;
- a checksummed materialization manifest preserving the development/holdout split and all support artifacts;
- source acquisition, reproducibility, validation, and freeze rules.

A real 1000-task/S03 sizing run exposed that the earlier expanded dependency-by-resource-pair communication matrix was redundant and too large. V1 draft now stores compact communication inputs and derives placement communication through one authoritative route function. On the same representative case, base JSON fell from 363,028,528 to 3,630,983 raw bytes and peak base-build memory fell from 2,195,180 kB to 43,732 kB. The full frozen 200-input generation/validation gate is now the remaining payload-size decision before permanent storage.

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

Communication is routed through explicit wireless/LAN/backbone segments rather than using an unexplained J/MB constant. Base instances store dependency `data_bits`, resource tiers, and the scenario-adjusted network; concrete placement communication is derived exactly by `generator.network.resource_route_metrics` instead of storing an `E × R²` pair matrix.

All schedulers share the authoritative deterministic construction and verification semantics in `generator.schedule`; see `docs/SCHEDULE_EVALUATION.md`. The frozen calibration algorithms and deterministic IFC adaptations are documented in `docs/REFERENCE_SCHEDULERS.md`.

These numerical values are pilot candidates and must pass sensitivity/trade-off validation before dataset freeze.

## Joint QoS profiles

Each core instance has a paired deadline and budget. Deadlines are interpolated between the fastest and most economical validated schedules in the frozen calibration set:

- tight: time-envelope fraction `1/10`, budget gap `1/10`
- moderate: time-envelope fraction `1/2`, budget gap `1/2`
- relaxed: time-envelope fraction `9/10`, budget gap `9/10`

Budget is measured between the cheapest calibration schedule known to satisfy the corresponding deadline and the fast-anchor schedule cost. Every core instance therefore requires a stored/reproducible schedule satisfying both deadline and budget.

The frozen `candidate_id` is retained as the materialized QoS `instance_id`. Multiple selected QoS profiles may share one base realization; that base and its calibration are generated once and referenced by every associated materialized input. See `docs/PILOT_MATERIALIZATION.md`.

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
│   ├── PILOT_MATERIALIZATION.md
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

## Pilot materialization commands

Materialize exactly the frozen 200 pilot identities into a new/empty output root:

```bash
python -m generator.cli materialize-pilot \
  --config config/benchmark-v1.yaml \
  --source-manifest manifests/source-workflows-v1.json \
  --pilot-selection manifests/pilot-selection-v1.json \
  --source-root source_workflows \
  --output-root <pilot-root> \
  --manifest <pilot-materialization-manifest.json> \
  --generator-commit-sha <40-char-git-sha>
```

Then recheck source checksums, deterministic base regeneration, all calibration schedules, exact QoS reconstruction, artifact checksums, and each joint witness:

```bash
python -m validation.cli pilot-materialization \
  --manifest <pilot-materialization-manifest.json> \
  --dataset-root <pilot-root> \
  --config config/benchmark-v1.yaml \
  --source-manifest manifests/source-workflows-v1.json \
  --pilot-selection manifests/pilot-selection-v1.json \
  --source-root source_workflows
```

## Experimental workflow

1. Specify and review benchmark semantics. **Done for pilot candidate.**
2. Implement deterministic source validation and the generator core. **Done.**
3. Acquire and freeze the 105 source DAX artifacts using the predeclared acceptance rule. **Done.**
4. Freeze the outcome-independent 200-input pilot selection. **Done.**
5. Implement the calibration portfolio, compact IFC base representation, and pilot materializer. **Done.**
6. Materialize and fully validate the exact selected 200-input pilot, then inspect development-side benchmark behavior and adjust only predeclared parameters if validation demonstrates a benchmark-design problem. **Current.**
7. Generate and freeze dataset v1.
8. Run every baseline algorithm on the same frozen instances.
9. Analyse failures, constraint violations, placement behavior, cost/energy trade-offs, and scaling.
10. Formulate the novel algorithm only after those weaknesses are empirically understood.

## Status

The v1 raw source-workflow corpus and selected pilot identities are frozen on `main`; the full IFC benchmark is **not frozen yet**. Reference calibration and deterministic pilot materialization are implemented, and the representative compact S03 sizing gate has passed. The current gate is full 200-input generation, cross-artifact validation, degeneracy reporting, and observed total payload sizing. Holdout comparative outcomes remain sealed.
