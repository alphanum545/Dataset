# IFC Benchmark Dataset Specification — v1 Pilot Candidate

## 1. Objective

This benchmark is designed for fair, reproducible evaluation of workflow-scheduling algorithms across heterogeneous IoT-Fog-Cloud infrastructure. The dataset must be fixed before the proposed research algorithm is tuned. Every baseline and future algorithm consumes identical workflow DAGs, resources, network links, execution estimates, costs, energy parameters, constraints, and reference metadata.

The current numerical environment is a **pilot candidate**, not yet frozen v1. It is fixed for generator/pilot implementation and may change only through the pre-declared pilot validation process.

## 2. Core benchmark dimensions

### 2.1 Workflow families

Version 1 uses five established scientific-workflow families:

- Montage
- CyberShake
- LIGO Inspiral
- SIPHT
- Genome

### 2.2 Workflow sizes

Seven exact target task-count levels are used:

- 60
- 100
- 200
- 400
- 600
- 800
- 1000 tasks

The original pilot candidate used 50 as the smallest level. Full acquisition against the pinned Bharathi `Genome` implementation proved that an exact 50-task Genome workflow is structurally unreachable. Genome creates either `4S+4` tasks for a one-lane workflow or `4S+2L+3` tasks for a multi-lane workflow, so 50 cannot be produced by that model. The common smallest size is therefore 60, which is exactly representable, instead of accepting or relabelling a nearby workflow.

A source manifest records the benchmark target, the actual upstream `--numjobs` request, and the actual parsed task count separately. The accepted parsed task count must equal the benchmark target exactly; it is never silently relabelled.

This yields 35 family/size combinations and, with three source replicates, 105 frozen source workflows.

### 2.3 Scheduler-visible resource semantics

A resource is one **serial execution slot** with `concurrency_slots = 1`. V1 does not hide multi-core parallelism inside a resource because several baseline schedulers, including HEFT-style implementations, assume one task executes at a time per processor/resource.

Every instance contains all three tiers:

- IoT/edge — 500–1000 MIPS pilot classes, cheapest local execution, closest to origin;
- Fog — 1000–2000 MIPS pilot classes, moderate normalized cost and active power;
- Cloud — 3000–5000 MIPS pilot classes, fastest and generally most expensive.

Each tier has economy, balanced, and performance classes except a two-resource tier, which deterministically contains economy and performance endpoints.

### 2.4 Resource-scale levels

| Scale | IoT | Fog | Cloud | Total slots |
| --- | ---: | ---: | ---: | ---: |
| `S01` | 4 | 4 | 2 | 10 |
| `S02` | 8 | 8 | 4 | 20 |
| `S03` | 16 | 16 | 8 | 40 |

### 2.5 Scenario profiles

1. `balanced` — base resource/network realization;
2. `compute_constrained` — Fog and Cloud effective MIPS multiplied by `3/4`;
3. `network_constrained` — inter-tier bandwidth × `2/5`, latency × `5/2`, and communication energy/bit × `3/2`.

Scenario multipliers are exact rationals committed in configuration.

### 2.6 Joint QoS profiles and development pilot

Each base workflow/infrastructure realization produces exactly three primary joint deadline-budget profiles:

- `tight`
- `moderate`
- `relaxed`

The core matrix remains:

`5 families × 7 sizes × 3 source replicates × 3 resource scales × 3 scenario profiles × 3 QoS profiles = 2,835 instances`

The immediate development pilot deterministically selects 200 identities from this matrix before scheduler outcomes are observed. It is split into 160 development and 40 holdout inputs. Exact marginal quotas and complete pairwise coverage are defined in `PILOT_SELECTION.md`.

## 3. Canonical instance model

A benchmark instance is the immutable combination of:

`workflow structure × resource scale × scenario profile × resource/topology seed × joint QoS profile`

It receives a stable `instance_id` derived from those dimensions.

### 3.1 Metadata

At minimum:

- dataset/schema/generator versions;
- instance ID;
- workflow family;
- benchmark target and actual parsed task counts;
- source replicate and source checksum;
- deterministic IFC realization seed;
- resource scale and scenario profile;
- QoS profile;
- provenance;
- content checksum.

### 3.2 Tasks

Each task records at least:

- `task_id`;
- machine-independent work;
- source runtime/provenance;
- input/output file metadata;
- optional source-backed memory requirement.

V1 does not invent task-memory constraints merely to restrict tier eligibility. In the absence of defensible task memory requirements, all tasks are eligible on all execution resources.

### 3.3 Dependencies

Each dependency records parent, child, and transferred data size. Internal edge data is derived from shared workflow files whenever possible as defined in `WORKFLOW_MODEL.md`.

### 3.4 Resources

Each resource records:

- `resource_id` and tier;
- resource class;
- integer MIPS;
- memory MB;
- `concurrency_slots = 1`;
- active power in integer milliwatts;
- idle power when sourced/defined;
- exact execution price in integer nCU/s.

The pilot class table is defined in `RESOURCE_MODEL.md` and `config/benchmark-v1.yaml`.

### 3.5 Routed network

Network communication is represented by reusable route segments. Each segment stores:

- decimal Mbps bandwidth;
- base latency in integer microseconds;
- dynamic communication energy in integer picojoules/bit.

Tier-pair routes are compositions of those segments. For example IoT↔Cloud traverses `iot_fog_wireless` plus `fog_cloud_backbone`.

Same-resource communication is zero. Same-tier communication between different resources is not automatically zero.

### 3.6 Constraints and reference metadata

Each instance stores rather than recomputes:

- theoretical makespan lower-bound components;
- best-known feasible fast and economical calibration anchors;
- exact rational deadline-envelope fraction and absolute deadline;
- fast-anchor schedule cost;
- deadline-conditioned feasible cost-floor reference;
- exact rational budget-gap factor and absolute budget;
- joint feasibility witness identifier/checksum;
- calibration scheduler identities/versions.

## 4. Execution-time model

Pegasus source runtime is converted to work using `reference_mips = 1000`.

For task `i` on resource `r`:

`execution_time_us(i,r) = ceil(task_work_mi(i) × 1,000,000 / mips(r))`

Materialized execution times are integer microseconds.

## 5. Communication-time model

For a dependency containing `data_bits` routed over segment `s`:

`segment_transfer_time_us = latency_us(s) + ceil(data_bits / bandwidth_mbps(s))`

because decimal `1 Mbps = 1,000,000 bit/s`.

For a multi-segment route, communication time is the sum of segment transfer times.

## 6. Cost model

V1 cost is normalized rather than presented as contemporary currency.

`task_cost_ncu = ceil(price_ncu_per_second × execution_time_us / 1,000,000)`

Schedule cost is the exact integer sum of task costs. Network monetary pricing is disabled.

## 7. Energy model

### 7.1 Compute energy

Active task-attributed compute energy is primary:

`compute_energy_nj = active_power_mw × execution_time_us`

because `1 mW × 1 us = 1 nJ`.

Idle energy is not included in the primary v1 objective.

### 7.2 Communication energy

For each route segment:

`segment_energy_pj = data_bits × energy_pj_per_bit`

Total dependency communication energy is the exact integer sum over route segments.

The pilot uses a first-order radio model for IoT wireless segments and Ethernet/backbone energy-per-bit anchors for Fog/Cloud routing. Full derivations are in `PARAMETER_PROVENANCE.md`.

## 8. Reference makespan and deadlines

`T_LB = max(T_CP, T_CAPACITY)`

is diagnostic only.

`T_fast` is the minimum validated makespan in the frozen IFC calibration set. `T_economical` is the makespan of the minimum-cost member of that same set. Both are feasible best-known references, not claimed optima.

Deadline-envelope fractions are exact rationals:

- tight `1/10`;
- moderate `1/2`;
- relaxed `9/10`.

`deadline_us = T_fast + ceil(fraction_num × (T_economical - T_fast) / fraction_den)`

## 9. Budget and joint feasibility

Generate a deterministic calibration set from MOHEFT (`K=50`), HEFT-IFC, PEFT-IFC, CPOP-IFC, and a deterministic cost-oriented IFC reference.

For deadline `D`:

`C_floor_ref(D) = minimum exact cost among calibration schedules with makespan <= D`

Let `C_fast` be the cost of the fast-anchor schedule. Budget-gap fractions are:

- tight `1/10`;
- moderate `1/2`;
- relaxed `9/10`.

For `beta=p/q`:

`budget_ncu = C_floor_ref(D) + floor(p × (C_fast - C_floor_ref(D)) / q)`

The schedule that produced `C_floor_ref(D)` is the joint feasibility witness.

## 10. Determinism and replication

The three source replicates are independently generated, checksum-distinct source DAGs. They are not identical replicas. Their identities are `r01`, `r02`, and `r03`, and each maps to a deterministic IFC realization seed (`101`, `202`, `303`) for benchmark-owned resource/network construction.

The upstream Bharathi generator itself is not claimed seed-reproducible. Source acquisition follows a bounded, predeclared family-aware request policy and accepts only the first structurally valid checksum-distinct DAG whose actual parsed count equals the benchmark target.

Resource, network, and constraint random streams are separated and explicitly seeded. Resource-class allocation uses mandatory endpoint/class coverage before deterministic seeded filling of remaining slots. No evaluated algorithm generates fresh infrastructure or constraints.

## 11. Static first

Core v1 uses fixed DAGs, resources, network parameters, and no time-varying background load. Dynamic-load scenarios belong to a separately versioned extension.

## 12. Required pilot validation

Before pilot numerical values can be frozen, aggregate checks must demonstrate:

1. multiple Pareto-relevant resource choices for representative tasks;
2. no tier dominates all objectives by construction;
3. `compute_constrained` produces a material compute-stress effect;
4. `network_constrained` produces a material communication/placement effect;
5. S01/S02/S03 show meaningful contention/scaling differences;
6. deadline-conditioned budget ranges are sufficiently nondegenerate;
7. results are robust to sensitivity variation of synthetic latency/distance/stress constants;
8. every exact unit conversion reconstructs from configuration.

Every generated candidate instance must also pass DAG, ID, execution matrix, route, reference schedule, deadline, exact cost/budget, feasibility witness, checksum, and deterministic-regeneration validation.

## 13. Experiment contract

After freeze, schedulers may read benchmark inputs and produce results but may not modify benchmark semantics. Any change to workflow normalization, resource classes, route model, objective units, references, seeds, or constraint calculation requires a new dataset version.

## 14. Source-acquisition status before pilot generation

The source provider, pinned commit, exact-count rule, source-replicate policy, producer-side edge-size rule, and family-aware bounded request search are specified and implemented. The remaining gate is empirical acquisition and validation of all 105 source DAX artifacts. Only after that corpus is reviewed and frozen does the project proceed to pilot IFC instance generation and calibration.
