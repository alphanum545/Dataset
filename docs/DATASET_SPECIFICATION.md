# IFC Benchmark Dataset Specification — v1 Draft

## 1. Objective

This benchmark is designed for fair, reproducible evaluation of workflow-scheduling algorithms across heterogeneous IoT-Fog-Cloud infrastructure. The dataset must be fixed before the proposed research algorithm is tuned. Every baseline and future algorithm consumes identical workflow DAGs, resources, network links, execution estimates, costs, energy parameters, constraints, and reference metadata.

## 2. Core benchmark dimensions

### 2.1 Workflow families

Version 1 uses five established scientific-workflow families:

- Montage
- CyberShake
- LIGO Inspiral
- SIPHT
- Genome

The generator must retain the family identity and provenance for every normalized DAG.

### 2.2 Workflow sizes

Seven target task-count levels are used:

- 50
- 100
- 200
- 400
- 600
- 800
- 1000 tasks

A workflow instance records both requested and actual normalized task count. If the source generator cannot produce the exact requested count, the actual count and deviation are retained and validated; it is never silently relabelled.

This yields 35 base workflow structures before infrastructure/scenario replication.

### 2.3 Infrastructure tiers

Every benchmark instance exposes resources from all three tiers:

- IoT/edge devices — lower compute, low cost, close to data origin;
- Fog resources — intermediate compute/cost and low-to-moderate latency to IoT;
- Cloud resources — highest compute and explicit usage cost, with greater network distance from IoT.

Resources are heterogeneous within a tier.

### 2.4 Scenario profiles

The v1 benchmark separates workflow structure from infrastructure stress:

1. `balanced`
2. `compute_constrained`
3. `network_constrained`

These profiles change resource/network parameters, not the DAG.

### 2.5 Resource-scale levels

The v1 draft uses deterministic infrastructure scales `S01`, `S02`, and `S03`. Exact composition is committed in configuration and validated before freeze. Algorithms never synthesize their own resource pools.

### 2.6 Joint QoS profiles

Each base workflow/infrastructure realization produces exactly three primary joint deadline-budget profiles:

- `tight`
- `moderate`
- `relaxed`

The primary benchmark does not multiply three deadline factors by three independent budget factors. Budget is conditioned on the corresponding deadline so every core instance has a known joint feasibility witness.

The candidate core matrix therefore remains:

`5 families × 7 sizes × 3 resource scales × 3 scenario profiles × 3 seeds × 3 QoS profiles = 2,835 instances`

With seven evaluated algorithms this is `19,845` algorithm-instance runs before repeated stochastic scheduler seeds.

## 3. Canonical instance model

A benchmark instance is the immutable combination of:

`workflow structure × resource scale × scenario profile × topology/resource seed × joint QoS profile`

It receives a stable `instance_id` derived from those dimensions. Random generation is allowed only through committed seeds.

### 3.1 Metadata

At minimum:

- dataset/schema/generator versions
- instance ID
- workflow family
- requested and actual task counts
- deterministic seeds
- resource scale
- scenario profile
- QoS profile
- provenance
- content checksum

### 3.2 Tasks

Each task records at least:

- `task_id`
- machine-independent computational work
- memory requirement
- optional justified tier eligibility
- input/output data metadata

Execution time is resource dependent and is either precomputed or reproducibly derived from task work and resource performance.

### 3.3 Dependencies

Each directed dependency records parent, child, and transferred data size in MB. The graph must be acyclic and every referenced task must exist.

### 3.4 Resources

Each resource records:

- ID and tier
- compute capacity/performance
- memory
- active/max power
- idle power when applicable
- exact execution price representation
- availability/concurrency capacity

### 3.5 Network

For each relevant path, define bandwidth, base latency, communication-energy semantics, and optional network monetary price. Same-resource dependency communication is zero in v1.

### 3.6 Constraints and reference metadata

Each instance stores rather than recomputes:

- theoretical makespan lower-bound components;
- deterministic HEFT reference makespan;
- exact rational deadline factor and absolute deadline;
- HEFT schedule cost;
- deadline-conditioned feasible cost-floor reference;
- exact rational budget-gap factor and absolute budget;
- joint feasibility witness identifier/checksum;
- calibration scheduler identities/versions.

## 4. Execution-time model

For task `i` on resource `r`:

`E(i,r) = work(i) / performance(r)`

Canonical materialization uses a fixed integer time unit such as microseconds, with the rounding policy committed and tested.

## 5. Communication-time model

For dependency `(i,j)` with data size `d` and placements `r_i`, `r_j`:

- if `r_i == r_j`, communication time is zero;
- otherwise communication consists of path base latency plus data-transfer time under the frozen bandwidth model.

Units and conversion/rounding rules are canonical generator behavior, not scheduler-specific choices.

## 6. Cost model

V1 cost is normalized rather than presented as contemporary public-cloud currency.

Canonical compute cost is represented exactly as integer nano-normalized-cost units. With execution time in integer microseconds:

`task_cost_ncu = ceil(price_ncu_per_second × execution_time_us / 1,000,000)`

Schedule cost is the exact integer sum of task costs. V1 network monetary pricing is disabled. Binary floating point is never used to materialize budget/cost fields.

Full joint budget rules are in `BUDGET_STRATEGY.md`.

## 7. Energy model

Task compute energy:

`Energy_compute(i,r) = active_power_w(r) × E(i,r)`

Inter-resource communication energy uses the frozen dimensionally valid network-energy model. System-wide idle energy remains a separate metric/configuration choice and cannot be silently mixed with task-attributed energy.

## 8. Reference makespan and deadlines

The benchmark stores a theoretical lower bound and a feasible calibration reference.

### 8.1 Lower bound

`T_LB = max(T_CP, T_CAPACITY)`

where `T_CP` is an optimistic critical-path bound and `T_CAPACITY` is an aggregate-work/capacity bound. This is diagnostic and is not claimed achievable.

### 8.2 Reference makespan

`T_ref` comes from frozen deterministic HEFT with fixed tie-breaking and the same canonical execution/communication model as all schedulers. HEFT is a calibration reference, not an optimum.

### 8.3 Deadlines

The three exact factors are:

- tight: `5/4`
- moderate: `3/2`
- relaxed: `2/1`

`deadline_us = ceil(factor_num × t_ref_us / factor_den)`

The HEFT schedule is a deadline-feasibility witness for all three profiles.

## 9. Budget and joint deadline-budget feasibility

For each materialized deadline, generate a deterministic cost–makespan calibration candidate set using frozen deterministic MOHEFT (`K=50`) plus explicit HEFT and cheapest-resource-assignment endpoints.

Filter candidates to schedules whose makespan satisfies the deadline. Let:

`C_floor_ref(D) = minimum exact cost among deadline-feasible calibration candidates`

and let `C_time` be the HEFT schedule cost.

The primary QoS profiles use exact rational budget-gap fractions:

- tight: `1/10`
- moderate: `1/2`
- relaxed: `9/10`

For `beta=p/q`:

`budget_ncu = C_floor_ref(D) + floor(p × (C_time - C_floor_ref(D)) / q)`

The schedule that produced `C_floor_ref(D)` is stored/reproducibly identified as the joint feasibility witness. Therefore every core v1 instance contains at least one schedule satisfying both its deadline and budget.

`C_floor_ref(D)` is only the cheapest cost found by the frozen calibration set; it is not claimed globally optimal.

Full rules are in `BUDGET_STRATEGY.md`.

## 10. Replication and random seeds

Workflow, resource, network, and constraint random streams are separated and explicitly seeded. No evaluated algorithm generates a fresh topology, resource pool, or constraint.

## 11. Static first, dynamic later

Core v1 uses fixed DAGs, resources, network parameters, and no time-varying background load. Dynamic load/resource scenarios belong to a separately versioned extension.

## 12. Required validation before freezing

Every candidate instance must pass:

- DAG acyclicity and unique IDs;
- valid dependency endpoints;
- positive/valid work, capacity, and network fields;
- finite execution for every eligible task-resource pair;
- at least one eligible resource per task;
- deterministic regeneration;
- reference schedule validity;
- exact deadline reconstruction;
- exact cost/budget reconstruction;
- nonempty deadline-feasible calibration set;
- valid joint feasibility witness satisfying both deadline and budget;
- explicit reporting of degenerate budget ranges;
- manifest/checksum consistency.

Aggregate distribution checks across families, sizes, scales, scenarios, seeds, and QoS profiles are also required.

## 13. Experiment contract

After freeze, schedulers may read benchmark inputs and produce results but may not modify them. Any semantic change to workflow normalization, generator, schema, resources, cost/energy/network model, references, seeds, or constraint calculation requires a new dataset version.

## 14. Open items before v1 freeze

Still unresolved and intentionally visible:

- final evidence-backed IoT/Fog/Cloud numeric performance/power/cost ranges;
- final network bandwidth/latency/energy values;
- tolerance/rule for requested versus generated workflow size;
- pilot validation of S01/S02/S03 resource composition;
- validation that MOHEFT `K=50` yields sufficiently nondegenerate cost ranges;
- exact network-energy model/source.

The deadline-budget methodology itself is now defined, subject to pilot validation rather than arbitrary post-hoc tuning.
