# IoT–Fog–Cloud Resource Model — Draft v0.1

## 1. Purpose

This document defines the proposed static infrastructure model for benchmark dataset v1. The resource catalogue is part of the benchmark input and must be identical for every scheduler evaluated on a given instance.

The values below are **controlled benchmark parameters**, not claims about a particular commercial device, edge server, or cloud VM. Their purpose is to create reproducible and interpretable heterogeneity across IoT, Fog, and Cloud tiers while preserving meaningful time–cost–energy–communication trade-offs.

Nothing in this document should be tuned after observing the performance of the future proposed scheduler.

---

## 2. Design principles

The v1 resource model follows these rules:

1. **Static and deterministic** — a resource environment does not change during one scheduling run.
2. **Tier heterogeneity** — IoT, Fog, and Cloud differ in compute speed, power, economic cost, and network position.
3. **Within-tier heterogeneity** — every tier contains at least two resource classes.
4. **No algorithm-specific parameters** — resources expose raw characteristics only.
5. **Explicit execution matrix** — task execution times are generated once and frozen in the benchmark instance.
6. **Explicit network matrix** — bandwidth, latency, and network-energy coefficients are frozen in the instance.
7. **Controlled scaling** — resource-scale scenarios change resource multiplicity while preserving class proportions.
8. **No hidden background load in v1** — the first benchmark version isolates static scheduling behaviour. Dynamic-load extensions can be introduced as a separately versioned experiment later.

---

## 3. Canonical resource classes

Dataset v1 proposes six canonical resource classes: two IoT, two Fog, and two Cloud.

| Class ID | Tier | Compute capacity (MIPS) | Max power (W) | Price per second (CU/s) | Intended role |
|---|---|---:|---:|---:|---|
| `iot-micro` | IoT | 500 | 3 | 0.0000005 | very low-power, slow edge execution |
| `iot-plus` | IoT | 1000 | 6 | 0.0000010 | stronger edge device |
| `fog-standard` | Fog | 2500 | 35 | 0.0000040 | moderate nearby compute |
| `fog-performance` | Fog | 4500 | 60 | 0.0000075 | faster fog node |
| `cloud-standard` | Cloud | 8000 | 130 | 0.0000200 | high-capacity remote compute |
| `cloud-performance` | Cloud | 14000 | 220 | 0.0000400 | fastest and most expensive compute |

`CU` means **benchmark cost unit**. v1 deliberately does not label these values as USD or any specific provider price. If a future experiment maps the benchmark to real provider pricing, that mapping must be documented and versioned separately.

### Why use normalized cost units?

Commercial pricing changes over time and differs by region, billing model, tenancy, and reserved/spot/on-demand policy. A normalized coefficient keeps the benchmark reproducible while still creating an explicit economic trade-off.

### Intended qualitative ordering

The catalogue is deliberately arranged so that, in general:

- IoT is slowest, cheapest, and most compute-energy-efficient per unit of work.
- Fog provides a middle ground in speed, cost, and distance.
- Cloud is fastest, but has the highest monetary coefficient and higher compute power draw.

The scheduler is therefore forced to make genuine trade-offs rather than always preferring one tier on every objective.

---

## 4. Resource-scale scenarios

The resource catalogue is replicated deterministically to produce three infrastructure scales while preserving the same class proportions.

| Scale | Instances of each class | IoT nodes | Fog nodes | Cloud nodes | Total resources |
|---|---:|---:|---:|---:|---:|
| `S01` | 1 | 2 | 2 | 2 | 6 |
| `S02` | 2 | 4 | 4 | 4 | 12 |
| `S03` | 3 | 6 | 6 | 6 | 18 |

Example deterministic resource IDs for `S02`:

- `iot-micro-01`, `iot-micro-02`
- `iot-plus-01`, `iot-plus-02`
- `fog-standard-01`, `fog-standard-02`
- `fog-performance-01`, `fog-performance-02`
- `cloud-standard-01`, `cloud-standard-02`
- `cloud-performance-01`, `cloud-performance-02`

This proportional scaling is intentional: changing from `S01` to `S02` or `S03` changes capacity through multiplicity without simultaneously changing the resource-class mix.

---

## 5. Task workload and execution-time model

Each task stores a normalized computational workload in million instructions (`workload_mi`).

For an eligible task `t` and resource `r`:

`ET[t,r] = workload_mi[t] / mips[r]`

where `ET` is measured in seconds.

### Source-runtime conversion

When the upstream workflow source provides a task runtime but not an instruction count, the generator should retain that original runtime and deterministically derive a normalized workload using a fixed benchmark reference capacity:

`workload_mi = source_runtime_seconds × REFERENCE_MIPS`

Proposed v1 value:

`REFERENCE_MIPS = 1000`

This does **not** claim that the source workflow originally ran on a 1000-MIPS processor. It is a deterministic normalization that preserves relative runtime magnitudes while allowing execution time to scale consistently across the benchmark resource catalogue.

The instance should retain both:

- the source runtime/provenance when available, and
- the derived `workload_mi`.

The complete `ET[t,r]` matrix is then materialized and frozen so each scheduling implementation consumes exactly the same execution times.

### Numerical precision

- Calculate with full floating-point precision during generation.
- Do not round intermediate execution times.
- Canonical serialization precision will be defined in the schema/reproducibility specification.

---

## 6. Task eligibility policy for v1

The proposed v1 policy is **universal compute eligibility**:

> Every task may execute on every benchmark compute resource.

This is intentional for the first static benchmark because the Pegasus-derived workflow tasks do not inherently encode trustworthy IoT/Fog/Cloud placement restrictions such as memory, accelerator, privacy, or sensor-affinity requirements.

Inventing task-type-specific eligibility rules without source evidence would introduce a hidden modelling assumption and could bias results.

If later research explicitly studies placement/security/locality constraints, they should be introduced as a separate versioned benchmark dimension with independently justified metadata.

---

## 7. Compute-energy model

For dataset v1, task compute energy on resource `r` is defined using the existing static evaluation convention:

`compute_energy_j = max_power_w[r] × execution_time_seconds`

Assumptions:

- utilization during task execution is treated as 1,
- system-wide idle energy is not charged,
- no DVFS state is modelled,
- no startup/shutdown energy is modelled,
- no separate memory/storage energy is modelled in v1.

This is a benchmark simplification, not a full physical power model. Its advantage is that every scheduler can be evaluated identically from immutable resource parameters and frozen execution times.

The raw `max_power_w` value must remain in each resource description so the energy objective is auditable.

---

## 8. Compute-cost model

For task `t` on resource `r`:

`compute_cost = execution_time_seconds × price_per_second[r]`

The dataset stores the raw `price_per_second` coefficient. Objective weights, scalarization coefficients, budgets, or scheduler-specific utility functions must **not** be stored as resource properties.

---

## 9. Network model

Communication between two tasks is charged only when their assigned resources differ.

If parent and child run on the same resource:

`communication_time = 0`

`network_energy = 0`

For different resources, communication depends on the tier pair of the source and destination resources.

### Balanced network profile

| Tier pair | Bandwidth (Mbps) | Base latency (ms) | Network energy (J/MB) |
|---|---:|---:|---:|
| IoT ↔ IoT | 80 | 2 | 0.030 |
| IoT ↔ Fog | 100 | 5 | 0.050 |
| IoT ↔ Cloud | 40 | 45 | 0.150 |
| Fog ↔ Fog | 500 | 2 | 0.015 |
| Fog ↔ Cloud | 300 | 25 | 0.080 |
| Cloud ↔ Cloud | 1000 | 1 | 0.008 |

The first v1 model is symmetric: `A → B` and `B → A` use the same coefficient for the same tier pair. Directional networking can be added only in a later explicitly versioned model.

### Communication-time equation

For a dependency transferring `data_mb` over a link with bandwidth `bandwidth_mbps` and base latency `latency_ms`:

`communication_time_seconds = latency_ms / 1000 + (data_mb × 8) / bandwidth_mbps`

This treats `MB` as a benchmark megabyte quantity and converts it to megabits using the factor 8 for transmission-time calculation.

### Network-energy equation

For inter-resource communication:

`network_energy_j = data_mb × energy_j_per_mb`

No network energy is charged for same-resource dependencies in v1.

---

## 10. Network profiles

To test sensitivity to communication conditions without changing the workflow DAG or compute catalogue, v1 proposes two deterministic infrastructure/network profiles.

### `balanced`

Uses the base network table exactly as specified above.

### `network-constrained`

Models poorer inter-tier connectivity while leaving compute capacities unchanged.

For **inter-tier** links only:

- bandwidth multiplier: `0.50`
- latency multiplier: `1.50`
- network-energy multiplier: `1.25`

Same-tier links remain at the balanced values.

This design isolates the impact of cross-tier communication pressure rather than simultaneously changing compute capacity and network quality.

The generator must materialize the resulting link matrix in each instance; schedulers should not independently apply profile multipliers at run time.

---

## 11. Topology construction

The logical infrastructure topology is a complete resource-to-resource communication matrix derived from the tier-pair rules.

For every ordered resource pair `(r_i, r_j)`, the frozen instance must contain or deterministically reference:

- source resource ID,
- destination resource ID,
- bandwidth in Mbps,
- base latency in milliseconds,
- network energy in J/MB,
- profile identifier.

For `r_i == r_j`, communication time and network energy are zero regardless of the tier defaults.

A complete matrix avoids differences between scheduler implementations when looking up communication parameters.

---

## 12. Resource instance schema — minimum fields

Every resource record should expose at least:

- `resource_id`
- `resource_class`
- `tier`
- `mips`
- `max_power_w`
- `price_per_sec`
- `scale_id`
- `profile_id`

Optional descriptive metadata may be included, but a scheduler must not require undocumented fields.

---

## 13. Derived sanity metrics

The generator/validator should compute diagnostic quantities, but these must remain metadata rather than scheduler inputs where not required.

Examples:

- compute energy per MI for each class,
- compute cost per MI for each class,
- fastest/slowest execution-time ratio,
- inter-tier communication-time ratios for fixed transfer sizes,
- number of resources per tier,
- total aggregate MIPS by tier and by scale.

These checks help detect accidental parameter inversions or malformed profiles before dataset freeze.

---

## 14. Why background load is excluded from v1

The current research stage needs to understand baseline scheduling behaviour before adding dynamic uncertainty.

Including background utilization immediately would add another dimension involving:

- time-varying compute availability,
- queueing assumptions,
- load trace generation,
- load observability assumptions,
- potential stochastic replication requirements.

Therefore v1 sets:

`load_profile = static-no-background-load`

A dynamic-load benchmark can later be released independently once the static benchmark and baseline algorithms are understood.

---

## 15. Proposed v1 scenario dimensions after this model

If the current dataset draft is retained:

- 5 workflow families,
- 7 workflow-size levels,
- 5 topology/data seeds,
- 3 resource scales (`S01`, `S02`, `S03`),
- 2 network profiles (`balanced`, `network-constrained`),
- 5 candidate deadline factors,
- 1 static load profile,

then the candidate benchmark contains:

`5 × 7 × 5 × 3 × 2 × 5 × 1 = 5,250 scheduling instances`

For seven scheduling algorithms, a complete evaluation would involve:

`5,250 × 7 = 36,750 algorithm-instance runs`

This is large enough to support stratified analysis while remaining practical for automated benchmarking.

The count is still **draft** because seeds and deadline factors are not yet frozen.

---

## 16. Validation requirements

Before a resource environment is accepted into dataset v1, validation must confirm:

1. every resource ID is unique,
2. every class belongs to exactly one valid tier,
3. MIPS is strictly positive,
4. max power is strictly positive,
5. price per second is non-negative,
6. scale multiplicities match their specification,
7. the full execution-time matrix exists for all task–resource pairs,
8. every network matrix entry references valid resources,
9. bandwidth is strictly positive for different resources,
10. latency and network-energy coefficients are non-negative,
11. same-resource communication is zero,
12. profile transformations are deterministic,
13. repeated generation from identical configuration produces identical canonical output.

---

## 17. Freeze policy

The numerical values in this document are currently **Draft v0.1**.

Before v1 freeze we may perform benchmark-calibration checks to detect obvious degeneracy, for example:

- one tier dominating all others on time, cost, and energy simultaneously,
- communication being negligible for every workflow,
- communication overwhelming computation for every workflow,
- unrealistic numeric overflow/underflow,
- reference schedules becoming pathological at one scale/profile.

Any adjustment must be justified by benchmark quality and performed **before** evaluating or tuning the proposed novel scheduler.

After v1 freeze, changing any resource capacity, price, power, bandwidth, latency, network-energy coefficient, scale definition, or profile multiplier requires a new benchmark version.

---

## 18. Current decisions proposed for lock

The following choices are recommended for the first implementation/calibration pass:

- six resource classes: two per tier,
- three proportional scales: 6, 12, and 18 resources,
- universal task eligibility,
- deterministic execution-time matrix from normalized workload/MIPS,
- static compute-energy model using max power × execution time,
- normalized compute cost units rather than live cloud pricing,
- pairwise deterministic network model,
- two network profiles: balanced and network-constrained,
- no background load in v1.

These should be treated as **candidate benchmark design**, not yet as paper conclusions.
