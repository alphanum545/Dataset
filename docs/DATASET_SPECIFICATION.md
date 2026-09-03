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

Seven target task-count levels are used so scaling behaviour can be studied without changing the benchmark definition:

- 50
- 100
- 200
- 400
- 600
- 800
- 1000 tasks

A workflow instance records both the requested size level and its actual normalized task count. If the source workflow generator cannot produce the exact requested count, the actual count must be retained and the deviation must be validated and reported; it must never be silently relabelled.

This yields 35 base workflow structures before infrastructure/scenario replication.

### 2.3 Infrastructure tiers

Every benchmark instance exposes resources from all three tiers:

- IoT/edge devices: low compute capacity, low monetary cost, constrained energy budget, closest to data origin.
- Fog resources: medium compute capacity and cost, low-to-moderate network latency to IoT, intermediate energy efficiency.
- Cloud resources: highest compute capacity and elastic capacity, higher network distance from IoT, explicit usage cost.

Resources are heterogeneous within a tier; a tier is not represented by one identical machine type.

### 2.4 Scenario profiles

The v1 candidate benchmark separates workflow structure from infrastructure stress. At minimum it contains:

1. `balanced` — no single resource dimension is intentionally dominant.
2. `compute_constrained` — limited fast-resource capacity makes processor selection and queueing important.
3. `network_constrained` — inter-tier communication delay/energy is emphasized, making placement of dependent tasks important.

These profiles change resource/network parameters, not the workflow DAG itself.

### 2.5 Resource-scale levels

The initial v1 design uses three deterministic infrastructure scales:

- `S01` — small
- `S02` — medium
- `S03` — large

The exact number and composition of IoT, fog, and cloud resources for each scale are defined in `RESOURCE_MODEL.md` and committed configuration. Algorithms must never synthesize their own resource pools.

## 3. Canonical instance model

A benchmark instance is the immutable combination of:

`workflow structure × resource scale × scenario profile × topology seed × constraint profile`

It receives a stable `instance_id` derived from those dimensions. Random generation is allowed only through committed seeds.

Each instance contains the following logical sections.

### 3.1 Metadata

- dataset version
- instance ID
- workflow family
- requested workflow size
- actual task count
- workflow/topology seed
- resource scale
- scenario profile
- provenance/source information
- generator version or commit
- schema version
- content checksum

### 3.2 Tasks

Each task records at least:

- `task_id`
- computational work requirement in a machine-independent unit
- memory requirement
- optional tier eligibility/restriction, when justified by the experiment
- input/output data metadata required for dependency communication

Execution time must not be stored as one universal value. It is resource dependent and is either precomputed as an execution-time matrix or reproducibly derived from task work and resource performance.

### 3.3 Dependencies

Each directed dependency records:

- parent task
- child task
- transferred data size in MB

The graph must be acyclic and every referenced task must exist.

### 3.4 Resources

Each resource records at least:

- resource ID
- tier: `iot`, `fog`, or `cloud`
- compute capacity/performance
- memory capacity
- maximum/active power
- idle power if system-wide idle energy is evaluated
- execution price per second
- availability/concurrency capacity

### 3.5 Network

For each relevant source-tier/destination-tier or source-resource/destination-resource path, the dataset defines:

- bandwidth
- propagation/base latency
- network energy per MB
- optional network transfer price per MB if a cost experiment requires it

Communication of a dependency assigned to the same resource is zero unless a future benchmark version explicitly models local I/O.

### 3.6 Constraints and reference metadata

Each instance stores rather than recomputes during algorithm execution:

- theoretical makespan lower-bound components
- deterministic reference makespan
- deadline factor
- absolute deadline
- reference cost statistics needed for any budget profile
- budget factor and absolute budget once the budget methodology is frozen

This prevents individual algorithms from interpreting constraints differently.

## 4. Execution-time model

For task `i` on resource `r`, the canonical execution time is:

`E(i,r) = work(i) / performance(r)`

If future empirical calibration introduces resource/task-type coefficients, they must be stored explicitly and versioned. Algorithms are not allowed to substitute private execution-time models.

## 5. Communication-time model

For dependency `(i,j)` with data size `d` and resources `r_i`, `r_j`:

- if `r_i == r_j`, communication time is `0` in v1;
- otherwise:

`C(i,j,r_i,r_j) = latency(r_i,r_j) + d / bandwidth(r_i,r_j)`

Units must be normalized consistently by the generator and validated.

## 6. Cost model

Compute cost for task `i` on resource `r`:

`Cost_compute(i,r) = price_per_sec(r) × E(i,r)`

If a scenario includes network pricing:

`Cost_network(i,j) = data_mb(i,j) × network_price_per_mb(r_i,r_j)`

The benchmark must state whether network pricing is enabled for each frozen version.

## 7. Energy model

Task compute energy:

`Energy_compute(i,r) = active_power_w(r) × E(i,r)`

Inter-resource communication energy:

`Energy_network(i,j) = data_mb(i,j) × energy_j_per_mb(r_i,r_j)`

System-wide idle energy is a separate metric/configuration choice and must not be mixed silently with task-attributed energy. The v1 manifest must explicitly state whether idle energy is included.

## 8. Reference makespan and deadlines

The benchmark stores both a lower bound and a feasible calibration reference.

### 8.1 Lower bound

At minimum compute:

- a critical-path lower bound using optimistic resource/communication times;
- a workload/capacity lower bound.

`T_LB = max(T_CP, T_CAPACITY)`

This is diagnostic only; it is not assumed to be achievable.

### 8.2 Reference makespan

`T_ref` is generated by a fixed deterministic calibration scheduler defined before the proposed algorithm is developed. For v1, the candidate calibration scheduler is deterministic HEFT with fixed tie-breaking and the same execution/communication model as the dataset.

HEFT is used only to calibrate a reproducibly feasible reference; it is not treated as the optimum.

### 8.3 Deadline levels

Candidate deadline factors are:

- `1.25` — tight
- `1.50` — moderate
- `2.00` — relaxed

For factor `alpha`:

`deadline = alpha × T_ref`

Because `alpha >= 1`, the deterministic calibration schedule provides a known deadline-feasibility witness unless another simultaneous constraint, such as budget, makes the combined case infeasible.

Full rules are in `DEADLINE_STRATEGY.md`.

## 9. Replication and random seeds

Workflow topology and infrastructure randomness are separated. Seeds are explicitly committed and reused across algorithms. No algorithm may generate a fresh topology, resource pool, or constraint during an experimental run.

A v1 candidate should include multiple topology/resource seeds per base workflow so conclusions are not tied to one random realization. The exact frozen seed list is committed in `config/benchmark-v1.yaml` before generation.

## 10. Static first, dynamic later

The core v1 benchmark starts with static scheduling inputs:

- fixed DAG
- fixed resource capacities
- fixed network parameters
- no time-varying background load during a run

This isolates scheduling quality and makes baseline diagnosis interpretable. Dynamic resource/load scenarios should be introduced as a separately versioned extension after the static benchmark is understood, not mixed into the first comparison.

## 11. Required validation before freezing

Every candidate instance must pass:

- DAG acyclicity
- unique task/resource IDs
- all dependency endpoints exist
- positive task work/data sizes where required
- positive compute/memory/network capacities
- nonnegative latency, price, and energy parameters
- finite execution time for every eligible task-resource pair
- at least one eligible resource for every task
- deterministic regeneration from seed/configuration
- reference schedule validity
- deadline consistency with stored `T_ref`
- manifest/checksum consistency

The full dataset is frozen only after aggregate distribution checks are also reviewed across families, sizes, resource scales, profiles, and deadline levels.

## 12. Experiment contract

After freeze, schedulers may read the dataset and produce schedules/results, but may not modify benchmark inputs. Any semantic change to the generator, schema, resource model, reference calculation, seed set, or constraint calculation requires a new dataset version.

## 13. Open items before v1 freeze

The following remain explicit design items, not hidden assumptions:

- exact IoT/Fog/Cloud resource counts and performance/power/cost ranges per `S01`/`S02`/`S03`;
- exact deterministic seed list and number of replications;
- whether v1 compute energy includes idle energy;
- whether network monetary cost is enabled;
- budget-reference and budget-factor methodology;
- exact tolerance allowed between requested and generated workflow size.

These must be resolved before generation is declared final.
