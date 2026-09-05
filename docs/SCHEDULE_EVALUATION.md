# Authoritative Schedule Evaluation

## Purpose

All reference, baseline, and future proposed schedulers use the same v1 schedule
construction and evaluation semantics. Algorithms choose a complete topological task
priority and one resource for every task; they do not redefine execution,
communication, cost, energy, or constraint calculations.

The public implementation is `generator.schedule`:

- `build_schedule(...)` constructs the deterministic earliest-feasible schedule for
  a fixed task order and task-to-resource mapping;
- `evaluate_schedule(...)` independently recomputes and verifies a complete explicit
  schedule;
- `validation.validate_schedule(...)` adds JSON Schema validation and exposes
  evaluation failures as benchmark validation errors.

The base instance is validated once with `validation.validate_base_instance(...)`
before schedulers reuse it to construct or evaluate candidate schedules.

## Time semantics

Task intervals are half-open: `[start_us, end_us)`. Each v1 resource has one serial
slot, so two tasks assigned to the same resource may touch at an endpoint but may not
overlap.

For dependency `p -> t`, with assignments to resources `r_p` and `r_t`:

`arrival_us(p,t) = end_us(p) + communication_time_us[p->t][r_p|r_t]`

The dependency-ready time of `t` is the latest of all parent arrivals, or zero for an
entry task. `build_schedule` places `t` in the earliest resource idle interval that is
long enough and starts no earlier than this dependency-ready time. It uses insertion
scheduling, so a task considered later may fill a safe idle gap before a previously
placed task.

Same-resource communication time and energy are exactly zero. Same-tier tasks on
different resources still use the materialized same-tier route.

## Objective accounting

The evaluator reads, but never recalculates or rounds differently from, the
materialized base-instance matrices:

- schedule compute cost is the exact integer sum of `compute_cost_ncu`;
- schedule compute energy is the exact integer sum of `compute_energy_nj`;
- schedule network energy is the exact integer sum of dependency-route
  `communication_energy_pj`;
- aggregate communication time is the sum of dependency-route communication times
  and is diagnostic; precedence arrival times, not this aggregate, constrain task
  starts;
- makespan is the maximum task end time.

Binary floating point and booleans are rejected for authoritative integer fields and
constraints.

## Feasibility and identity

When supplied, deadline feasibility is `makespan_us <= deadline_us` and budget
feasibility is `compute_cost_ncu <= budget_ncu`. Joint feasibility is reported only
when both constraints are supplied. Constraints are evaluation context and do not
change the schedule identity.

Assignments are serialized in canonical task-ID order. `schedule_id` contains the
base-instance identity plus a deterministic fingerprint of the timed assignments;
`schedule_sha256` is the full canonical checksum of the schedule document. The
explicit evaluator rejects a schedule if either identity, any stored total, task
duration, precedence arrival, or resource interval is inconsistent.

## Required input checks

`build_schedule` rejects incomplete or extra tasks, duplicate tasks, unknown
resources, and non-topological orders. `evaluate_schedule` additionally rejects
missing/duplicate assignments, noncanonical ordering, invalid durations, resource
overlaps, precedence violations, tampered totals, and tampered identity/checksum
fields.
