# Budget and Joint Feasibility Strategy — v1 Draft

## Goal

Budget constraints must be reproducible, meaningful across heterogeneous instances, and jointly feasible with the stored deadline. The benchmark must not label an algorithm as failing merely because the dataset silently generated an impossible deadline-budget combination.

The v1 core dataset therefore uses **known-feasible joint QoS profiles**. Intentionally infeasible cases, if later useful for robustness testing, belong in a separately labelled stress suite and are not part of the primary benchmark.

## Prior-work basis

Budget-constrained workflow scheduling literature commonly defines a budget inside a range bounded by a cheapest assignment and a faster/high-cost assignment. Arabnejad and Barbosa define a normalized budget level of the form:

`B = C_cheapest + k_budget × (C_high - C_cheapest)`, with `k_budget` in `[0,1]`.

Reference: H. Arabnejad and J. G. Barbosa, *A Budget Constrained Scheduling Algorithm for Workflow Applications*, Journal of Grid Computing 12(4), 2014, DOI `10.1007/s10723-014-9294-7`.

MOHEFT provides a list-based method for obtaining several cost–makespan trade-off schedules rather than one weighted aggregate solution.

Reference: J. J. Durillo et al., *MOHEFT: A multi-objective list-based method for workflow scheduling*, IEEE CloudCom 2012, DOI `10.1109/CloudCom.2012.6427573`.

Recent fog/cloud workflow studies also use separate time-oriented and cost-oriented references to scale user deadline and budget constraints. For example, deadline can be referenced to HEFT while budget is referenced to a greedy cost-oriented schedule.

Reference: *Energy-efficient time and cost constraint scheduling algorithm using improved multi-objective differential evolution in fog computing*, Journal of Supercomputing, DOI `10.1007/s11227-024-06550-7`.

The v1 benchmark adapts these ideas but adds one critical rule: **the lower budget reference is conditioned on the actual deadline**. This is what provides a joint feasibility witness.

## Exact cost representation

The benchmark does not use binary floating point for monetary/normalized cost values.

- one normalized cost unit is represented by `1,000,000,000` integer nano-cost units;
- resource prices are stored as integer `price_ncu_per_second`;
- canonical execution times are stored as integer microseconds;
- task execution cost is computed with integer arithmetic:

`task_cost_ncu = ceil(price_ncu_per_second × execution_time_us / 1,000,000)`

- schedule cost is the exact integer sum of task costs plus any explicitly enabled network monetary cost;
- v1 keeps network monetary cost disabled, so the primary schedule cost is compute cost only.

The scale is a representation choice, not a claim that the benchmark uses a real currency. If a future version maps prices to a real provider, that version must record provider, region, pricing model, and timestamp.

## Calibration schedules

For each workflow/resource/scenario/seed realization, compute the following schedules before materializing the three QoS profiles.

### 1. Time-oriented endpoint

`S_time = deterministic HEFT`

Store:

- `T_time` — HEFT makespan;
- `C_time` — HEFT exact schedule cost.

`T_time` is also the v1 deadline reference `T_ref`.

### 2. Cost-oriented endpoint

`S_cheapest` maps each task to its cheapest eligible resource under the canonical cost model and then builds a precedence/resource-valid deterministic schedule. It provides a global cost-oriented endpoint, but it is **not automatically assumed to satisfy a deadline**.

### 3. Cost–makespan calibration frontier

Run a deterministic MOHEFT calibration pass with:

- objectives: makespan and exact compute cost;
- retained trade-off solutions `K = 50`;
- fixed task ranking and deterministic tie-breaking;
- fixed resource iteration order;
- deterministic non-dominance/crowding tie resolution;
- the same execution, communication, eligibility, cost, and resource-capacity model used by the dataset.

The calibration candidate set is:

`P_cal = MOHEFT_schedules ∪ {S_time, S_cheapest}`

The explicit endpoints are retained even if pruning would otherwise remove them.

`P_cal` is a **calibration set**, not a claim of the true Pareto frontier.

## Deadline-conditioned feasible cost floor

For a stored deadline `D`, define:

`F(D) = { S in P_cal | makespan(S) <= D }`

Because every v1 deadline is at least `1.25 × T_time`, `S_time` belongs to `F(D)`. Therefore `F(D)` must never be empty if the calibration data are internally consistent.

Define:

`C_floor_ref(D) = min cost(S) over S in F(D)`

If multiple schedules have the same exact cost, choose the one with lower makespan; if still tied, use canonical lexicographic mapping order.

The selected schedule `S_floor(D)` is stored or reproducibly identifiable as the **joint feasibility witness**.

Important: `C_floor_ref(D)` is the cheapest cost found by the frozen calibration set. It is not labelled the mathematically optimal cost and is not a theoretical lower bound.

## Budget range

The upper calibration endpoint is the HEFT schedule cost:

`C_ceiling_ref(D) = C_time`

Since `S_time` meets every v1 deadline, this is also a known-feasible endpoint.

By construction:

`C_floor_ref(D) <= C_time`

For budget-gap fraction `beta = p/q`, compute using exact integer arithmetic:

`B(D,beta) = C_floor_ref(D) + floor(p × (C_time - C_floor_ref(D)) / q)`

No floating-point calculation is permitted when materializing the budget.

## Core v1 joint QoS profiles

The benchmark deliberately uses **three paired joint-constraint profiles**, not a 3×3 deadline-budget Cartesian product. This keeps the primary benchmark at the already planned scale while moving from deadline-only to genuine deadline-and-budget evaluation.

| Profile | Deadline factor | Budget-gap fraction | Meaning |
| --- | ---: | ---: | --- |
| `tight` | `5/4 = 1.25` | `1/10 = 0.10` | deadline close to HEFT and budget close to the cheapest known schedule that still meets that deadline |
| `moderate` | `3/2 = 1.50` | `1/2 = 0.50` | balanced joint slack |
| `relaxed` | `2/1 = 2.00` | `9/10 = 0.90` | broad time and cost slack while retaining a nontrivial budget ceiling |

Thus one base workflow/infrastructure realization still produces exactly three primary scheduling instances.

The v1 core matrix remains:

`5 workflow families × 7 sizes × 3 resource scales × 3 scenario profiles × 3 seeds × 3 QoS profiles = 2,835 instances`

For seven evaluated algorithms this remains `19,845` algorithm-instance runs before any repeated stochastic algorithm seeds.

A separate sensitivity extension may later evaluate all nine deadline×budget combinations, but it must be labelled separately so it does not silently change the primary benchmark contract.

## Why the joint pair is guaranteed feasible

For every profile:

1. `S_floor(D)` has `makespan <= D` by definition.
2. `cost(S_floor(D)) = C_floor_ref(D)`.
3. `B(D,beta) >= C_floor_ref(D)` for all `beta >= 0`.

Therefore the same stored witness schedule satisfies **both**:

`makespan <= deadline` and `cost <= budget`.

This is the central v1 feasibility guarantee.

It does not prove that all algorithms can find a feasible schedule. It only proves that a feasible schedule exists in the benchmark model, so a violation can meaningfully be attributed to algorithm behaviour rather than an impossible generated constraint pair.

## Degenerate budget ranges

If:

`C_floor_ref(D) = C_time`

then the known feasible budget range has zero width. The instance is still valid, but the generator must set:

- `budget_range_degenerate = true`;
- `budget_gap_ncu = 0`;
- all budget-gap fractions resolve to the same absolute budget for that deadline.

Aggregate validation must report how often this occurs. A high degenerate rate means the resource/cost model or calibration frontier is not creating a meaningful time-cost trade-off and must be fixed before dataset freeze.

## Calibration independence and fairness

The proposed novel algorithm must never participate in calibration.

The calibration implementations and versions are frozen before the proposed method is tuned. The manifest records HEFT and MOHEFT calibration versions, `K`, tie-breaking rules, and schedule checksums.

If the exact MOHEFT calibration implementation is later included among the seven primary algorithms, the dependency must be explicitly disclosed because it contributed to constraint construction. Preferably, the calibration implementation should remain a benchmark-construction utility rather than a primary success-rate baseline.

## Stored per-instance fields

Each instance/manifest must store at least:

- `t_ref_us`;
- `deadline_factor_num`, `deadline_factor_den`;
- `deadline_us`;
- `cost_time_ncu` (`C_time`);
- `cost_floor_ref_ncu` (`C_floor_ref(D)`);
- `budget_gap_ncu`;
- `budget_factor_num`, `budget_factor_den`;
- `budget_ncu`;
- `budget_range_degenerate`;
- calibration scheduler identities/versions;
- `moheft_k`;
- joint witness schedule identifier/checksum;
- witness makespan and exact cost;
- calibration candidate-set checksum or reproducible generation metadata.

Useful diagnostics include:

- `deadline_lb_ratio`;
- `budget_floor_ratio = budget_ncu / max(cost_floor_ref_ncu, 1)` for reporting only;
- `cost_tradeoff_width_ncu = cost_time_ncu - cost_floor_ref_ncu`.

Diagnostic ratios may be computed in analysis using decimal arithmetic; the frozen budget itself remains integer-exact.

## Validation rules

For every materialized joint-QoS instance:

1. exact cost fields are integers and nonnegative;
2. `deadline_us` is positive;
3. `F(D)` is nonempty;
4. `S_time` is precedence/resource valid and meets `D`;
5. `S_floor(D)` is precedence/resource valid and meets `D`;
6. stored witness cost equals `C_floor_ref(D)` exactly;
7. `C_floor_ref(D) <= budget_ncu <= C_time`;
8. budget is reproduced exactly from the stored rational factor;
9. witness cost is `<= budget_ncu`;
10. witness makespan is `<= deadline_us`;
11. repeated calibration produces identical schedules/costs/checksums;
12. degenerate ranges are explicitly counted and reported;
13. no core v1 instance is intentionally infeasible.

## What this strategy does not claim

- `C_floor_ref(D)` is not the globally optimal cost under deadline `D`.
- HEFT is not the optimal makespan scheduler.
- MOHEFT's retained set is not asserted to be the exact Pareto frontier.
- a known feasible benchmark does not guarantee that any particular scheduler succeeds.

These distinctions are important for paper-quality reporting and prevent calibration heuristics from being mistaken for optimization oracles.
