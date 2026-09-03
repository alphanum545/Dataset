# Numerical Parameter Provenance — v1 Draft

## Purpose

The benchmark should use numerical ranges that are traceable to published fog/cloud simulation practice or clearly labelled synthetic normalization. This document records the evidence used to choose the eventual v1 ranges and prevents arbitrary constants from becoming invisible assumptions.

## Published reference points

### EEOA — Sensors 2023

The study *EEOA: Cost and Energy Efficient Task Scheduling in a Cloud-Fog Framework* reports the following simulation ranges:

- Cloud compute: 3000–5000 MIPS
- Fog compute: 1000–2000 MIPS
- Cloud RAM: 5000–20000 MB
- Fog RAM: 250–5000 MB
- Cloud bandwidth: 512–4096 Mbps
- Fog bandwidth: 128–1024 Mbps
- Cloud processing cost: 0.6–1.0 G$ per unit
- Fog processing cost: 0.2–0.5 G$ per unit

Source: Sensors 2023, 23(5), 2445, DOI `10.3390/s23052445`.

### EMCS — Sustainability 2022

The study *EMCS: An Energy-Efficient Makespan Cost-Aware Scheduling Algorithm Using Evolutionary Learning Approach for Cloud-Fog-Based IoT Applications* reports:

- Cloud processing: 250–500 MIPS
- Fog processing: 10–500 MIPS
- Cloud bandwidth options: 10, 100, 512, 1024 Mbps
- Fog bandwidth: 1024 Mbps
- Task communication data: 10–50 MB
- Cloud processing cost: 0.5 G$/s
- Fog processing cost: 0.1–0.5 G$/s
- Fog execution power: 1–5 W
- Fog idle power: 0.05 W
- Cloud execution power: 5–10 W

Source: Sustainability 2022, 14(22), 15096, DOI `10.3390/su142215096`.

### iFogSim-based resource examples

Published iFogSim experiments also use substantially larger machine-level capacities. One reported setup uses approximately:

- Cloud CPU: 44,800 MIPS
- Proxy CPU: 2,800 MIPS
- Fog CPU: 5,800 MIPS
- Cloud RAM: 40,000 MB
- Proxy RAM: 4,000 MB
- Fog RAM: 16,000 MB
- Proxy busy/idle power: about 107/83 W
- Fog busy/idle power: about 157/83 W

These values illustrate that absolute MIPS/power figures vary significantly depending on whether the simulated entity represents a VM, a fog device, or a larger physical host. We should therefore avoid mixing values from different abstraction levels without normalization.

## Implication for our benchmark

The v1 benchmark should model **scheduler-visible execution resources**, not entire datacenter physical hosts. For that reason, the first numeric profile should stay in a VM/device-like range rather than combine 5-W virtual execution power with 1.6-kW physical-server power in the same objective.

## Proposed normalized v1 ranges for validation

The following are candidate ranges to test, not yet frozen:

| Tier | Compute (MIPS) | RAM (MB) | Active Power (W) | Idle Power (W) | Price / sec (normalized units) |
| --- | ---: | ---: | ---: | ---: | ---: |
| IoT | 250–1000 | 256–2048 | 0.5–3 | 0.05–0.5 | 0–0.05 |
| Fog | 1000–3000 | 2048–8192 | 2–8 | 0.1–1.5 | 0.10–0.50 |
| Cloud | 3000–6000 | 4096–16384 | 5–15 | 0.5–3 | 0.50–1.00 |

Rationale:

- Fog/cloud MIPS and cost ranges are anchored primarily to EEOA, with modest extension to produce heterogeneous overlap.
- Cloud/fog power ranges are anchored to the VM-like EMCS values rather than physical-host iFogSim power.
- IoT ranges are intentionally below fog and are labelled synthetic until supported by a specific edge-device source.
- Price values are normalized benchmark cost units, not claims of current public-cloud currency pricing.

Before freeze, the IoT row needs a dedicated empirical/literature source and the full range set needs sensitivity testing.

## Proposed network baseline for validation

The published studies show bandwidth values spanning roughly tens to several thousand Mbps depending on tier and topology. Instead of assigning one bandwidth to each resource, v1 should define tier-pair paths.

Candidate balanced-profile values:

| Path | Bandwidth (Mbps) | Base latency (ms) |
| --- | ---: | ---: |
| IoT↔IoT | 100 | 2 |
| IoT↔Fog | 250 | 5 |
| IoT↔Cloud | 100 | 40 |
| Fog↔Fog | 1000 | 2 |
| Fog↔Cloud | 500 | 20 |
| Cloud↔Cloud | 2000 | 1 |

These latency values are benchmark-design assumptions and therefore remain **synthetic candidate values** until supported or replaced by cited measurements. Bandwidth choices are within published simulation envelopes, but their tier-pair arrangement is our own model.

## Scenario multipliers

Rather than generating unrelated parameter universes for each profile, scenario profiles should derive from one base realization:

### Balanced

- compute multiplier: 1.0
- network bandwidth multiplier: 1.0
- latency multiplier: 1.0
- network-energy multiplier: 1.0

### Compute-constrained

- effective compute multiplier on Fog/Cloud: candidate 0.65–0.80
- bandwidth/latency unchanged from balanced

### Network-constrained

- inter-tier bandwidth multiplier: candidate 0.25–0.50
- inter-tier latency multiplier: candidate 2–4
- network-energy multiplier: candidate 1.5–3
- compute unchanged from balanced

Exact multipliers must be chosen after pilot distributions are inspected.

## Network energy

Published workflow/fog scheduling papers frequently model communication energy but use incompatible units/abstractions. We should not copy a value labelled “W” into an `energy_j_per_mb` field.

Therefore `energy_j_per_mb` remains unresolved until we select a source with directly compatible units or derive it from a documented transmission-power × transfer-time model.

## Cost semantics

The benchmark should label cost as `normalized_cost_units` unless we intentionally map to a real provider and timestamp the price source. This avoids implying that a synthetic G$/s value is an actual contemporary cloud price.

The objective remains valid because scheduling comparisons depend on consistent relative cost, not the currency symbol.

## Freeze gate for numerical values

No numerical range should move from candidate to frozen until:

1. its abstraction level is compatible with our resource model;
2. units are explicit and dimensionally valid;
3. provenance is recorded;
4. pilot generation shows nontrivial placement trade-offs;
5. no tier dominates all objectives by construction;
6. sensitivity analysis shows conclusions are not caused by one arbitrary constant.
