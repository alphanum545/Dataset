# Numerical Parameter Provenance — v1 Pilot Candidate

## Purpose

The benchmark uses numerical values only when their abstraction level and units are explicit. Published values are used as anchors; benchmark-specific interpolation, topology distances, and latency points are labelled as design assumptions rather than presented as empirical measurements.

The numerical model in `RESOURCE_MODEL.md` is the **pilot candidate**. It becomes frozen v1 only after the pilot validation gates pass.

## Execution-resource abstraction

V1 models scheduler-visible **serial execution slots** rather than entire multi-core hosts. Each resource has `concurrency_slots = 1`.

This choice avoids giving some algorithms implicit parallelism that HEFT-style baselines do not model. It also allows published VM/device-like MIPS, price, and task-attributed active-power ranges to be used consistently.

## Published Fog/Cloud anchors

### EEOA — Sensors 2023

*EEOA: Cost and Energy Efficient Task Scheduling in a Cloud-Fog Framework* reports simulation ranges including:

- Cloud compute: 3000–5000 MIPS
- Fog compute: 1000–2000 MIPS
- Cloud RAM: 5000–20000 MB
- Fog RAM: 250–5000 MB
- Cloud bandwidth: 512–4096 Mbps
- Fog bandwidth: 128–1024 Mbps
- Cloud processing cost: 0.6–1.0 normalized/G$ units per time unit
- Fog processing cost: 0.2–0.5 units per time unit

Source: Sensors 2023, 23(5), 2445. DOI `10.3390/s23052445`.

V1 uses EEOA directly for the Fog/Cloud compute envelopes and Cloud memory envelope. Price ratios are retained as normalized benchmark cost rather than claimed as a real currency.

### EMCS — Sustainability 2022

*EMCS: An Energy-Efficient Makespan Cost-Aware Scheduling Algorithm Using Evolutionary Learning Approach for Cloud-Fog-Based IoT Applications* reports:

- Fog active/execution power: 1–5 W
- Fog idle power: 0.05 W
- Cloud active/execution power: 5–10 W
- Fog processing cost: 0.1–0.5 per second/time unit
- Cloud processing cost: approximately 0.5 in that experiment
- Cloud/Fog bandwidth values spanning 10–1024 Mbps

Source: Sustainability 2022, 14(22), 15096. DOI `10.3390/su142215096`.

V1 uses the 1–5 W Fog active envelope, 0.05 W Fog idle point, and 5–10 W Cloud active envelope. It does not invent Cloud idle power because idle energy is excluded from the primary v1 energy objective.

## IoT anchors

### iFogSim-style sensor compute

Published iFogSim simulation configurations commonly model sensor/edge nodes around 500 MIPS while Fog/Cloud entities are faster. V1 uses 500 MIPS as the IoT lower class and 1000 MIPS as the upper class so the IoT tier overlaps the slow Fog boundary without becoming uniformly dominated by compute alone.

These are scheduler-normalization points, not claims about instruction throughput of a specific CPU model.

### Raspberry Pi 4 power

Raspberry Pi engineering measurements for Raspberry Pi 4 after firmware improvements report approximately:

- idle power: about 2.1 W;
- synthetic load power: about 6.41 W.

Source: Raspberry Pi, *Thermal testing Raspberry Pi 4*, 2019, https://www.raspberrypi.com/news/thermal-testing-raspberry-pi-4/ .

V1 therefore bounds IoT active class power between 3.5 W and 6.4 W and uses 2.1 W as an idle anchor. The 3.5 W and 5.0 W class points are benchmark interpolation values; only the envelope anchor is empirical.

## Pilot resource classes

All monetary values below are normalized, not currency.

| Tier/class | MIPS | Memory MB | Active W | Idle W | normalized price/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| IoT economy | 500 | 512 | 3.5 | 2.1 | 0.000 |
| IoT balanced | 750 | 1024 | 5.0 | 2.1 | 0.025 |
| IoT performance | 1000 | 2048 | 6.4 | 2.1 | 0.050 |
| Fog economy | 1000 | 1024 | 1.0 | 0.05 | 0.10 |
| Fog balanced | 1500 | 2048 | 3.0 | 0.05 | 0.30 |
| Fog performance | 2000 | 4096 | 5.0 | 0.05 | 0.50 |
| Cloud economy | 3000 | 5000 | 5.0 | n/a | 0.60 |
| Cloud balanced | 4000 | 10000 | 7.5 | n/a | 0.80 |
| Cloud performance | 5000 | 20000 | 10.0 | n/a | 1.00 |

The table deliberately creates conflicting objectives:

- Cloud is fastest but generally expensive;
- Fog can be substantially more energy efficient for task execution;
- IoT can be monetarily free/cheap but slow and can have worse task energy than an efficient Fog slot;
- communication can reverse a compute-only placement preference.

Pilot validation must confirm this produces nontrivial Pareto trade-offs rather than relying on the intended qualitative behavior.

## Network-energy model

The earlier draft `energy_j_per_mb` placeholder is retired. V1 uses a dimensionally explicit `energy_pj_per_bit` for each routed segment.

### Short-range wireless: first-order radio model

A widely used first-order wireless-sensor-network radio model uses:

- electronics energy `E_elec = 50 nJ/bit` for transmit and receive electronics;
- free-space amplifier coefficient `E_amp = 100 pJ/bit/m^2`.

For one bit transmitted a distance `d` and received once:

`E_total_bit = 2 × E_elec + E_amp × d^2`

V1 applies explicit benchmark distances:

- IoT↔IoT peer: `d = 10 m` → `110 nJ/bit`;
- IoT↔Fog access: `d = 25 m` → `162.5 nJ/bit`.

The coefficients are literature-backed; the 10 m and 25 m distances are transparent benchmark assumptions to be sensitivity-tested.

### Ethernet/backbone: Kopras et al.

Kopras et al., *Communication and Computing Task Allocation for Energy-Efficient Fog Networks*, model dynamic communication energy with values including approximately:

- `2 nJ/bit` for a 1 GbE switch;
- `12.66 nJ/bit` for the modeled backbone path toward Cloud.

The paper reports energy attributable to network transmission separately from computation and is therefore compatible with our per-edge communication-energy objective.

V1 uses:

- Fog LAN: `2 nJ/bit`;
- Cloud LAN: `2 nJ/bit`;
- Fog↔Cloud route: `12.66 + 2 + 2 = 16.66 nJ/bit`, representing backbone plus two Ethernet-switch contributions.

This is a benchmark route decomposition; it is not intended to model every real Internet hop.

## Pilot balanced network

| Segment | Bandwidth Mbps | Base latency ms | Energy nJ/bit | Status |
| --- | ---: | ---: | ---: | --- |
| IoT peer wireless | 100 | 2 | 110.00 | radio coefficients sourced; distance synthetic |
| IoT↔Fog wireless | 100 | 5 | 162.50 | radio coefficients sourced; distance synthetic |
| Fog LAN | 1000 | 2 | 2.00 | energy anchored to Ethernet source; latency synthetic |
| Fog↔Cloud backbone | 500 | 20 | 16.66 | energy derived from backbone/switch source; latency synthetic |
| Cloud LAN | 2000 | 1 | 2.00 | energy anchored to Ethernet source; latency synthetic |

Bandwidth points stay within the broad simulation envelopes reported by EEOA/EMCS. The exact tier-pair bandwidth and latency topology is our benchmark design and must be sensitivity-tested.

## Scenario multipliers

### Balanced

No changes.

### Compute-constrained

Fog and Cloud MIPS are multiplied by exact ratio `3/4`; IoT and networking remain unchanged.

Rationale: this creates a compute-stress variant without changing resource identity or simultaneously perturbing network conditions.

### Network-constrained

Only inter-tier IoT↔Fog and Fog↔Cloud segments change:

- bandwidth × `2/5`;
- latency × `5/2`;
- transfer energy/bit × `3/2`.

Same-tier links and compute remain unchanged.

These multipliers are benchmark-design stress parameters, not measurements. They must pass profile-effect and sensitivity checks before freeze.

## Exact units and arithmetic

V1 stores:

- compute performance: integer MIPS;
- execution time: integer microseconds;
- active power: integer milliwatts;
- task compute energy: integer nanojoules (`mW × us`);
- network energy coefficient: integer picojoules/bit;
- edge network energy: integer picojoules;
- cost and budget: integer nano-normalized-cost units.

This prevents unit ambiguity and avoids binary floating-point drift in materialized reference values.

## Explicitly synthetic assumptions

The following are design choices rather than empirical facts:

- three discrete classes per tier;
- IoT intermediate compute/power/price points;
- Fog/Cloud class interpolation within literature envelopes;
- IoT normalized execution prices;
- 10 m and 25 m wireless distances;
- tier-pair latency values;
- exact bandwidth assignment to routed segments;
- compute/network stress multipliers;
- S01/S02/S03 2:2:1 resource-count ratio.

These remain legitimate benchmark parameters because they are explicit, versioned, and sensitivity-tested instead of being presented as measured reality.

## Freeze gate for numerical values

Pilot values become frozen only if aggregate validation shows:

1. no tier dominates all objectives by construction;
2. representative tasks expose multiple Pareto-relevant placements;
3. profile changes have intended, measurable effects;
4. the three infrastructure scales show meaningful contention differences;
5. network-heavy workflows respond to network stress;
6. calibration/budget ranges are sufficiently nondegenerate;
7. conclusions are robust to sensitivity variation of the explicitly synthetic assumptions;
8. all units and derivations reconstruct exactly from committed configuration.
