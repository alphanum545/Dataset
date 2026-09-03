# IoT-Fog-Cloud Resource Model — v1 Draft

## Design objective

The benchmark must expose genuine heterogeneous placement choices across IoT, Fog, and Cloud without allowing each algorithm to invent its own infrastructure. Resource parameters are generated once from committed profiles/seeds and stored in every frozen instance.

## Tiers

### IoT / edge

Intended characteristics:

- smallest compute capacity;
- lowest memory capacity;
- low or zero direct monetary execution price for local-device execution;
- constrained active/idle power budget;
- closest to workflow data origin;
- limited concurrency.

### Fog

Intended characteristics:

- moderate compute and memory;
- moderate execution price;
- lower latency to IoT than Cloud;
- better compute performance than IoT;
- multiple nodes so placement and contention matter.

### Cloud

Intended characteristics:

- highest compute/memory performance;
- explicit execution price;
- higher latency from IoT-origin data;
- elastic-looking capacity represented by a finite benchmark pool so all algorithms see the same choices.

## Resource scales

Version 1 will use three named scale levels. Exact counts are frozen in configuration rather than hard-coded in algorithms.

A candidate starting layout is:

| Scale | IoT | Fog | Cloud | Total |
| --- | ---: | ---: | ---: | ---: |
| S01 | 4 | 4 | 2 | 10 |
| S02 | 8 | 8 | 4 | 20 |
| S03 | 16 | 16 | 8 | 40 |

This 2:2:1 ratio is a benchmark-design starting point, not a claim about real deployments. We should validate whether these counts create meaningful contention for workflow sizes 50–1000 before freezing them.

## Per-resource fields

Every resource record contains:

- `resource_id`
- `tier`
- `performance_units_per_sec`
- `memory_mb`
- `concurrency_slots`
- `active_power_w`
- `idle_power_w`
- `price_per_sec`
- optional provenance/model label

All values use explicit units.

## Candidate parameter envelopes

The following ranges are deliberately separated by tier but overlap enough to avoid a trivial rule such as “always choose Cloud.” Exact distributions and seeds must be fixed before freeze.

| Parameter | IoT | Fog | Cloud |
| --- | --- | --- | --- |
| performance units/s | low | medium | high |
| memory | low | medium | high |
| price/s | zero/very low | low/medium | medium/high |
| active power | low absolute power | medium | high absolute power |
| concurrency | 1–2 | 2–4 | 4–8 |

Absolute numeric ranges should be justified either from literature, public cloud/edge specifications, or explicitly labelled synthetic calibration. We should avoid arbitrary precision that gives synthetic values a false empirical appearance.

## Scenario profiles

### Balanced

Compute, network, and price differences are moderate. No single dimension is intentionally dominant.

### Compute-constrained

Compared with balanced:

- fewer high-performance effective slots and/or lower performance multipliers;
- network remains moderate;
- queueing and resource selection become important.

### Network-constrained

Compared with balanced:

- lower inter-tier bandwidth;
- higher inter-tier latency;
- higher network energy per MB;
- compute performance remains comparable to balanced.

Profiles must be represented by committed multipliers/configuration and applied deterministically.

## Network model

The canonical v1 network matrix is directional if the configuration requires it, but the first candidate can use symmetric paths for simplicity. For every relevant path, store:

- `bandwidth_mbps`
- `latency_ms`
- `energy_j_per_mb`
- `price_per_mb` when network monetary pricing is enabled

At minimum distinguish:

- IoT↔IoT
- IoT↔Fog
- IoT↔Cloud
- Fog↔Fog
- Fog↔Cloud
- Cloud↔Cloud

A same-resource dependency has zero communication time/energy in v1. Same-tier but different-resource transfers are not automatically zero.

## Execution time

`execution_time(task, resource) = task_work / resource_performance`

This result may be materialized as a matrix in the generated instance to guarantee identical scheduler inputs and simplify validation.

## Compute energy

Task-attributed active compute energy:

`energy_j = active_power_w × execution_time_s`

Idle energy must be separately enabled/disabled at dataset-version level. The first static benchmark should report task-attributed energy as the primary metric; if idle energy is later included, it should be reported as a separate component to avoid changing objective semantics invisibly.

## Compute cost

`cost = price_per_sec × execution_time_s`

The exact currency is less important than consistency if the values are synthetic, but the dataset must label whether prices are empirical currency values or normalized synthetic cost units.

## Eligibility

By default, tasks are eligible for all resources that satisfy memory/capability requirements. Tier restrictions should be used only when the workflow semantics justify them. Arbitrary eligibility restrictions could turn a placement optimization problem into a predetermined mapping.

## Reproducibility

Resource parameters are generated from:

`resource_scale + scenario_profile + resource_seed + config_version`

The fully materialized resource/network values are then stored in the instance. Schedulers must never regenerate them.

## Before freeze

We still need to validate and then lock:

1. absolute performance ranges;
2. memory ranges;
3. active/idle power ranges;
4. execution-price ranges;
5. network bandwidth/latency/energy matrices;
6. whether network price is used;
7. whether the candidate 10/20/40-resource scale creates appropriate contention.

These values should be chosen with literature/specification support and then sensitivity-tested before the dataset is frozen.
