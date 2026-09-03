# Deadline and Reference-Makespan Strategy — v1 Draft

## Goal

Deadlines must be reproducible, algorithm-neutral with respect to the proposed method, and interpretable across heterogeneous workflow instances. A deadline must never be generated independently by each scheduling algorithm.

## Stored reference values

For every benchmark instance, store:

- `t_cp_lb`: optimistic critical-path lower bound;
- `t_capacity_lb`: aggregate workload/capacity lower bound;
- `t_lb = max(t_cp_lb, t_capacity_lb)`;
- `t_ref`: deterministic calibration-scheduler makespan;
- `deadline_factor`;
- `deadline`;
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

The v1 candidate calibration scheduler is deterministic HEFT.

Reasons:

- it is a well-known static heterogeneous DAG scheduler;
- it uses the same execution and communication matrices available to all algorithms;
- it scales to the largest planned workflows;
- it provides an actual feasible schedule rather than only a lower bound;
- it is fixed before the proposed novel algorithm is designed, preventing circular tuning.

The implementation must use deterministic tie-breaking. Given the same instance, it must produce the same schedule and `t_ref` on every run.

The benchmark documentation must state clearly that `t_ref` is a calibration reference, not the true optimum.

## Deadline factors

Version 1 uses three candidate levels:

| Level | Factor | Interpretation |
| --- | ---: | --- |
| tight | 1.25 | limited slack over the calibration schedule |
| moderate | 1.50 | meaningful but not excessive slack |
| relaxed | 2.00 | broad feasibility region |

For factor `alpha`:

`deadline = alpha × t_ref`

Store the absolute value in the instance. Experimental code should read that value rather than recalculate it.

## Feasibility witness

For a deadline-only instance with `alpha >= 1`, the stored HEFT calibration schedule is a deadline-feasibility witness. Validation should confirm its makespan is `<= deadline` within a defined numerical tolerance.

This does not prove feasibility when other constraints are imposed simultaneously. In particular, adding a budget can make the joint deadline-budget instance infeasible even when the deadline alone is feasible.

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
2. `T_ref >= T_LB` within numerical tolerance.
3. calibration schedule is precedence-valid and resource-valid.
4. stored `T_ref` equals the makespan of the stored/recomputed deterministic calibration schedule.
5. `deadline_factor` belongs to the frozen factor set.
6. `deadline = deadline_factor × T_ref` within tolerance.
7. for deadline-only cases, calibration makespan is not greater than the deadline.
8. all values and calculation-version metadata are recorded in the manifest.

## Budget interaction

Budget generation is deliberately kept separate from deadline generation. Before v1 is frozen, the budget strategy must define a known-feasible or explicitly classified feasibility region. We should not simply multiply an arbitrary cost number and assume that all deadline-budget pairs are feasible.

A useful next step is to compute two deterministic reference schedules per instance after the resource model is fixed:

- time-oriented calibration schedule;
- cost-oriented calibration schedule.

Their makespan/cost trade-off can then be used to define meaningful budget profiles and to label joint deadline-budget cases as feasible, hard, or intentionally infeasible.
