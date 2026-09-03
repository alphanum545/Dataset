# Deadline and Reference-Makespan Strategy — v1 Draft

## Goal

Deadlines must be reproducible, algorithm-neutral with respect to the proposed method, and interpretable across heterogeneous workflow instances. A deadline must never be generated independently by each scheduling algorithm.

## Stored reference values

For every benchmark instance, store:

- `t_cp_lb`: optimistic critical-path lower bound;
- `t_capacity_lb`: aggregate workload/capacity lower bound;
- `t_lb = max(t_cp_lb, t_capacity_lb)`;
- `t_ref`: deterministic calibration-scheduler makespan;
- exact rational deadline factor numerator/denominator;
- absolute integer-microsecond deadline;
- calibration scheduler identity/version;
- calibration schedule checksum or reproducible schedule metadata.

The lower bound and calibration reference serve different purposes. `t_lb` measures theoretical difficulty; `t_ref` provides a reproducibly feasible schedule reference.

## Lower bound

### Critical-path component

For each task, use its optimistic execution time over eligible resources. For each dependency, use the most optimistic valid communication time between eligible resource placements. Compute the longest path from entry to exit in the DAG.

The result is a lower bound because it ignores contention and assumes each task/dependency can independently obtain its most favorable placement.

### Capacity component

Compute total workflow work and compare it against the aggregate usable compute capacity of the resource pool. The exact formula and unit normalization must be fixed in generator code and tested.

### Combined lower bound

`T_LB = max(T_CP, T_CAPACITY)`

This value is diagnostic and must not be labelled an optimum.

## Calibration scheduler

The v1 calibration scheduler is deterministic HEFT.

Reasons:

- it is a well-known static heterogeneous DAG scheduler;
- it uses the same execution and communication matrices available to all algorithms;
- it scales to the largest planned workflows;
- it provides an actual feasible schedule rather than only a lower bound;
- it is fixed before the proposed novel algorithm is designed, preventing circular tuning.

The implementation must use deterministic tie-breaking. Given the same instance, it must produce the same schedule and `t_ref` on every run.

The benchmark documentation must state clearly that `t_ref` is a calibration reference, not the true optimum.

## Deadline profiles

Version 1 uses three paired QoS profiles. Their exact rational factors are:

| Level | Rational factor | Decimal interpretation |
| --- | ---: | ---: |
| tight | `5/4` | 1.25 |
| moderate | `3/2` | 1.50 |
| relaxed | `2/1` | 2.00 |

For factor `alpha = p/q`:

`deadline_us = ceil(p × t_ref_us / q)`

The frozen deadline is stored as an integer number of microseconds. Experimental algorithms read that value rather than recalculate it.

## Feasibility witness

Because every deadline factor is at least 1, the stored HEFT calibration schedule is a deadline-feasibility witness. Validation confirms its makespan is `<= deadline_us`.

For the core v1 benchmark, budget generation is now explicitly conditioned on this deadline. `BUDGET_STRATEGY.md` selects a known schedule that satisfies the deadline and uses its cost as the lower endpoint of the feasible budget range. As a result, every primary deadline-budget pair has a stored joint feasibility witness.

## Why not use only a theoretical lower bound for the deadline?

A deadline such as `alpha × T_LB` can be impossible even for moderate `alpha`, because the lower bound ignores resource contention and other scheduling interactions. That makes it difficult to distinguish an algorithm failure from an intentionally infeasible benchmark case.

The dataset therefore stores `T_LB` for hardness analysis but anchors the primary deadline profile to a known feasible calibration schedule.

## Why not use the proposed algorithm?

Using the proposed algorithm to create its own deadline would bias the benchmark and make later comparisons circular. The proposed algorithm must never participate in dataset calibration.

## Additional diagnostic quantity

Store normalized deadline tightness relative to the lower bound:

`deadline_lb_ratio = deadline / T_LB`

This helps compare how intrinsically tight two instances are even if HEFT quality differs between workflow families or infrastructure profiles.

## Validation rules

For each instance:

1. `T_LB > 0`.
2. `T_ref >= T_LB` within the frozen integer/tolerance policy.
3. calibration schedule is precedence-valid and resource-valid.
4. stored `T_ref` equals the makespan of the stored/recomputed deterministic calibration schedule.
5. deadline factor belongs to the frozen rational factor set.
6. `deadline_us = ceil(p × t_ref_us / q)` exactly.
7. HEFT calibration makespan is not greater than the stored deadline.
8. all values and calculation-version metadata are recorded in the manifest.
9. the paired budget profile passes every joint-feasibility rule in `BUDGET_STRATEGY.md`.

## Budget interaction

Budget and deadline are separate quantities but are calibrated jointly for the primary v1 benchmark.

The budget strategy computes a deterministic cost–makespan calibration set, filters it by the already materialized deadline, chooses the cheapest known deadline-feasible schedule, and interpolates the budget between that cost and the HEFT cost. This avoids assuming that independently selected time and cost constraints are jointly satisfiable.

Full rules, exact cost representation, budget factors, degenerate-range handling, and witness requirements are defined in `BUDGET_STRATEGY.md`.
