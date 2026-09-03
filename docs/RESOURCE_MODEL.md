# IoT-Fog-Cloud Resource Model — v1 Pilot Candidate

## Design objective

The benchmark must expose genuine heterogeneous placement choices across IoT, Fog, and Cloud while remaining compatible with all baseline schedulers. Resource and network values are generated/materialized once from committed configuration and deterministic seeds. Evaluated schedulers consume those values and do not invent infrastructure.

This document defines the **pilot candidate** numerical model. These values are fixed for generator/pilot implementation, but they are not called frozen v1 values until the pilot validation gates pass.

## Scheduler-visible resource abstraction

A v1 `resource` is a **single serial scheduling slot** rather than an entire multi-core physical host.

Consequences:

- `concurrency_slots = 1` for every resource;
- HEFT-style one-task-at-a-time resource semantics remain valid across all baselines;
- S01/S02/S03 scale by the number of scheduler-visible slots;
- host-level multi-core parallelism is not hidden inside some resources but unavailable to algorithms that model only one processor per resource.

This abstraction is also why v1 uses VM/device-like power ranges rather than combining low-Watt VM/device values with kilowatt-scale whole-datacenter servers in one objective.

## Resource scales

| Scale | IoT | Fog | Cloud | Total serial slots |
| --- | ---: | ---: | ---: | ---: |
| `S01` | 4 | 4 | 2 | 10 |
| `S02` | 8 | 8 | 4 | 20 |
| `S03` | 16 | 16 | 8 | 40 |

The 2:2:1 ratio is a benchmark design choice. It is not claimed to represent a universal deployment topology. Pilot validation must determine whether it creates meaningful contention for workflows from 50 to 1000 tasks.

## Resource classes

V1 uses three scheduler-visible classes per tier. Class values are discrete rather than arbitrary continuous draws. Resource seeds determine duplicate-class allocation after mandatory class coverage rules are satisfied.

### IoT / edge classes

| Class | MIPS | Memory MB | Active power mW | Idle power mW | Price nCU/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| `iot_economy` | 500 | 512 | 3500 | 2100 | 0 |
| `iot_balanced` | 750 | 1024 | 5000 | 2100 | 25,000,000 |
| `iot_performance` | 1000 | 2048 | 6400 | 2100 | 50,000,000 |

The 500-MIPS lower anchor is consistent with published iFogSim sensor-node examples. The power envelope is anchored to Raspberry Pi 4 measurements showing approximately 2.1 W idle and 6.41 W under a heavy synthetic load after firmware improvements. Intermediate values are benchmark class points, not claims about three specific commercial devices.

### Fog classes

| Class | MIPS | Memory MB | Active power mW | Idle power mW | Price nCU/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| `fog_economy` | 1000 | 1024 | 1000 | 50 | 100,000,000 |
| `fog_balanced` | 1500 | 2048 | 3000 | 50 | 300,000,000 |
| `fog_performance` | 2000 | 4096 | 5000 | 50 | 500,000,000 |

Fog compute is within the 1000–2000 MIPS range reported by EEOA. Fog active power and price span the 1–5 W and 0.1–0.5 cost-per-time-unit ranges reported by EMCS.

### Cloud classes

| Class | MIPS | Memory MB | Active power mW | Idle power mW | Price nCU/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cloud_economy` | 3000 | 5000 | 5000 | null | 600,000,000 |
| `cloud_balanced` | 4000 | 10000 | 7500 | null | 800,000,000 |
| `cloud_performance` | 5000 | 20000 | 10000 | null | 1,000,000,000 |

Cloud compute, memory, and normalized price follow the 3000–5000 MIPS, 5000–20000 MB, and 0.6–1.0 ranges reported by EEOA. Active power follows the 5–10 W cloud execution range reported by EMCS.

`idle_power_mw` is intentionally `null` for v1 cloud classes because the chosen VM/device-level source does not provide a compatible cloud idle-power value. V1 does **not** include system-wide idle energy in its primary energy objective, so inventing an idle value would add false precision without affecting the primary metric.

## Resource-class allocation

For each tier and resource scale:

1. if the tier contains at least three resources, include at least one economy, balanced, and performance class;
2. if a tier contains exactly two resources, include economy and performance classes;
3. remaining slots are filled by deterministic seeded sampling from the three classes;
4. class counts and canonical resource IDs are materialized in the instance;
5. schedulers never repeat class sampling.

This prevents a resource seed from accidentally producing a pool with no cheap endpoint or no fast endpoint while still allowing controlled variation across replications.

## Memory and eligibility

V1 stores resource memory as provenance/descriptive capacity, but **does not synthesize arbitrary per-task memory requirements** merely to force tier restrictions. Unless the source workflow supplies a defensible task memory requirement, all tasks remain eligible on all scheduler-visible resources.

This keeps v1 focused on scheduling, communication, cost, and energy rather than introducing an unsupported memory-allocation model. A future benchmark version may enable memory eligibility if source-backed requirements are available.

## Exact execution-time model

Pegasus source runtime is normalized to machine-independent work as defined in `WORKFLOW_MODEL.md`.

For task `i` and resource `r`:

`execution_time_us(i,r) = ceil(task_work_mi(i) × 1,000,000 / mips(r))`

The implementation must perform this with exact-decimal/integer arithmetic after canonical work normalization. Materialized execution times are integer microseconds.

## Exact compute-energy model

Active task-attributed compute energy is the primary v1 compute-energy metric.

Because active power is stored in milliwatts and execution time in microseconds:

`compute_energy_nj(i,r) = active_power_mw(r) × execution_time_us(i,r)`

This is exact because `1 mW × 1 us = 1 nJ`.

Idle energy remains disabled in the primary v1 objective. If reported later, it must be a separate component and cannot silently change the objective definition.

## Exact compute-cost model

Prices are normalized benchmark cost, not contemporary cloud-provider currency.

One normalized cost unit is `1,000,000,000` nano-normalized-cost units (`nCU`).

For task `i` on resource `r`:

`task_cost_ncu = ceil(price_ncu_per_second(r) × execution_time_us(i,r) / 1,000,000)`

Schedule compute cost is the exact integer sum of task costs. Network monetary cost is disabled in core v1.

## Network abstraction

V1 uses **routed network segments** rather than assigning an unrelated energy-per-MB number to every tier pair.

For every segment, store:

- `bandwidth_mbps` — decimal megabits per second;
- `latency_us` — base propagation/processing latency;
- `energy_pj_per_bit` — dynamic communication energy attributable to transmitting one bit over that segment.

For a dependency containing `data_bits` routed over segment `s`:

`segment_transfer_time_us = latency_us(s) + ceil(data_bits / bandwidth_mbps(s))`

The simplification follows from decimal Mbps: `1 Mbps = 1,000,000 bit/s`, so the transfer-only duration in microseconds is `data_bits / bandwidth_mbps`.

Segment communication energy is:

`segment_energy_pj = data_bits × energy_pj_per_bit(s)`

For a multi-segment route, communication time and energy are the sums over its segments. Same-resource communication remains zero.

## Balanced-profile network segments

| Segment | Bandwidth Mbps | Latency us | Energy pJ/bit | Derivation/status |
| --- | ---: | ---: | ---: | --- |
| `iot_peer_wireless` | 100 | 2000 | 110000 | first-order radio model, 10 m benchmark distance |
| `iot_fog_wireless` | 100 | 5000 | 162500 | first-order radio model, 25 m benchmark distance |
| `fog_lan` | 1000 | 2000 | 2000 | 1 GbE switch dynamic energy reference |
| `fog_cloud_backbone` | 500 | 20000 | 16660 | backbone + two 1 GbE switch contributions |
| `cloud_lan` | 2000 | 1000 | 2000 | LAN switching reference; bandwidth is a benchmark point within published cloud envelopes |

### Wireless energy derivation

The first-order radio model uses:

- transmitter/receiver electronics: `E_elec = 50 nJ/bit`;
- transmit amplifier: `E_amp = 100 pJ/bit/m^2`.

For a transfer of one bit over distance `d`:

`E_tx = E_elec + E_amp × d^2`

`E_rx = E_elec`

`E_total = E_tx + E_rx`

Therefore:

- at 10 m: `50 nJ + 10 nJ + 50 nJ = 110 nJ/bit = 110000 pJ/bit`;
- at 25 m: `50 nJ + 62.5 nJ + 50 nJ = 162.5 nJ/bit = 162500 pJ/bit`.

The distances are explicit benchmark topology assumptions. The radio coefficients are literature-backed.

### Wired/backbone energy derivation

Kopras et al. report approximately:

- `2 nJ/bit` dynamic cost for a 1 GbE switch;
- `12.66 nJ/bit` for the modeled backbone path to the Cloud;
- an additional `2 nJ/bit` per relevant Ethernet switch.

The v1 `fog_cloud_backbone` candidate assumes the backbone plus two 1-GbE switch contributions:

`12.66 + 2 × 2 = 16.66 nJ/bit = 16660 pJ/bit`.

This model captures transfer-attributable network energy; network-device idle power is not allocated to individual workflow edges in v1.

## Tier-pair routes

| Placement pair | Route |
| --- | --- |
| same IoT resource | zero |
| different IoT resources | `iot_peer_wireless` |
| IoT ↔ Fog | `iot_fog_wireless` |
| IoT ↔ Cloud | `iot_fog_wireless` → `fog_cloud_backbone` |
| different Fog resources | `fog_lan` |
| Fog ↔ Cloud | `fog_cloud_backbone` |
| different Cloud resources | `cloud_lan` |
| same Fog/Cloud resource | zero |

Routes are symmetric in v1. Directional networking can be introduced only in a new benchmark version.

## Scenario profiles

All three profiles begin from the same seeded resource-class realization. A profile changes the environment, not the workflow DAG or resource identity.

### `balanced`

No multiplier is applied.

### `compute_constrained`

- IoT MIPS unchanged;
- Fog and Cloud effective MIPS multiplied by `3/4`;
- result rounded down to integer MIPS after multiplication;
- power, price, bandwidth, latency, and network energy unchanged.

Lowering effective Fog/Cloud throughput without reducing their per-second price/power intentionally increases execution time, cost, and active energy in the compute-stress scenario.

### `network_constrained`

Only inter-tier segments `iot_fog_wireless` and `fog_cloud_backbone` are stressed:

- bandwidth multiplier: `2/5`;
- latency multiplier: `5/2`;
- energy-per-bit multiplier: `3/2`;
- resource compute/power/price unchanged;
- same-tier LAN/peer segments unchanged.

This makes cross-tier placement materially more expensive without globally slowing every transfer.

All multipliers are exact rationals committed in configuration; the generator defines deterministic integer rounding.

## Required pilot validations

Before these pilot values become frozen v1 values, validate across every workflow family and all three scales/profiles that:

1. execution-time matrices contain meaningful tier heterogeneity;
2. at least two resource choices are Pareto-relevant in time/cost or time/energy for representative tasks;
3. no tier globally dominates all other tiers across time, compute cost, compute energy, and communication effects;
4. `compute_constrained` materially changes makespan/resource utilization without making the calibration schedule invalid;
5. `network_constrained` materially changes placement/communication metrics for communication-heavy workflows;
6. S01/S02/S03 produce observable contention differences;
7. deadline-conditioned budget ranges are nondegenerate for a useful fraction of instances;
8. conclusions are not driven solely by one synthetic latency or distance constant.

Only after this pilot evidence is reviewed should the values be marked frozen.

## Provenance

Detailed source citations, abstraction decisions, and synthetic assumptions are recorded in `PARAMETER_PROVENANCE.md`.
