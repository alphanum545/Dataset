# Deadline and Reference-Envelope Strategy — v1 Draft

## Goal

Deadlines must be reproducible, jointly feasible with their budgets, and independent of the proposed novel algorithm. Every compared scheduler receives the same stored deadline; no experimental algorithm recalculates it.

The original pilot proposal used a fixed multiple of deterministic HEFT makespan. V1 now uses a feasible time–cost envelope so one heuristic does not control benchmark difficulty.

## Frozen calibration set

For every selected base IoT–Fog–Cloud instance, construct schedules using the same authoritative evaluator and all eligible resources:

- deterministic HEFT-IFC;
- deterministic PEFT-IFC;
- deterministic CPOP-IFC;
- a deterministic cost-oriented IFC reference;
- the retained deterministic MOHEFT calibration schedules used for joint budget calibration.

The proposed algorithm is permanently excluded. Scheduler implementations, versions, exact arithmetic, resource iteration order, and tie-breaking must be frozen before proposed-algorithm development.

This collection is a **calibration set**, not a claim of the exact Pareto frontier.

## Lower bounds

Store two diagnostic lower-bound components:

- `t_cp_lb_us` — optimistic critical-path time using the most favorable eligible execution and communication values;
- `t_capacity_lb_us` — aggregate work/capacity relaxation.

Define:

`T_LB = max(T_CP, T_CAPACITY)`

The lower bound measures difficulty but does not define the deadline because it need not be attainable.

## Feasible envelope anchors

From all validated calibration schedules, select:

### Fast anchor

`S_fast` is the schedule with minimum makespan. Ties use lower exact compute cost and then canonical schedule ID.

Store:

- `T_fast = makespan(S_fast)`;
- `C_fast = cost(S_fast)`;
- schedule ID and checksum.

### Economical anchor

`S_economical` is the schedule with minimum exact compute cost. Ties use lower makespan and then canonical schedule ID.

Store:

- `T_economical = makespan(S_economical)`;
- `C_economical = cost(S_economical)`;
- schedule ID and checksum.

Because `S_fast` is selected from the same set, `T_fast <= T_economical`. Because `S_economical` is the least-cost member, `C_economical <= C_fast`.

These are **best-known feasible anchors**, not mathematical optima.

## Deadline profiles

Let:

`time_gap_us = T_economical - T_fast`

For profile fraction `alpha = p/q`, materialize:

`deadline_us = T_fast + ceil(p × time_gap_us / q)`

The frozen profiles are:

| Profile | Fraction | Interpretation |
| --- | ---: | --- |
| tight | `1/10` | 10% of the feasible time–cost interval above the fast anchor |
| moderate | `1/2` | midpoint of the interval |
| relaxed | `9/10` | 90% of the interval toward the economical anchor |

All calculations use integers and exact rational arithmetic. Binary floating point is forbidden.

## Feasibility

Every profile satisfies `deadline >= T_fast`; therefore `S_fast` is a deadline-feasibility witness. Budget generation then searches the calibration set for the least-cost schedule meeting that exact deadline and stores the selected schedule as the joint deadline–budget witness.

If `T_fast = T_economical`, the deadline interval has zero width. The instance remains reproducible, but it must set `deadline_range_degenerate = true`. Aggregate pilot validation must report the rate; a high rate is a benchmark-design failure requiring review before freeze.

## Why this is IoT–Fog–Cloud aware

Every calibration scheduler receives the full IoT, Fog, and Cloud resource pool, task execution matrix, resource contention, and route-specific communication model. A valid schedule is not forced to use all three tiers; placement is chosen according to the model. Artificial mandatory tier usage would change the scheduling problem.

## Stored values

Each calibration/QoS artifact records at least:

- lower-bound components and `T_LB`;
- calibration scheduler identities and versions;
- calibration candidate-set checksum;
- fast/economical schedule IDs and checksums;
- `T_fast`, `T_economical`, and `time_gap_us`;
- exact interpolation numerator and denominator;
- absolute integer-microsecond deadline;
- degeneracy flag;
- joint-feasibility witness metadata.

## Validation rules

For every materialized profile:

1. every calibration schedule passes the authoritative evaluator;
2. every calibration makespan is at least `T_LB`;
3. the fast and economical anchors reproduce from the frozen tie-breaking rules;
4. `time_gap_us = T_economical - T_fast >= 0`;
5. the profile fraction matches committed configuration;
6. the deadline reconstructs exactly from the interpolation rule;
7. `S_fast` meets the deadline;
8. the stored joint witness meets both deadline and budget;
9. repeated calibration yields identical identities, totals, and checksums.

The deadline methodology must be frozen before the 40 holdout outcomes are inspected.
