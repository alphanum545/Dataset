# Frozen IFC Reference Schedulers — v1

## Purpose

The reference portfolio constructs the feasible time–cost calibration envelope used to
materialize v1 deadlines and budgets. These schedulers are calibration instruments,
not proposed contributions, and the future novel algorithm is excluded from their
implementation and outputs.

All algorithms consume the same fully materialized IoT–Fog–Cloud base instance and
must finish through `generator.schedule.build_schedule`. They may choose task
priorities and resource mappings, but they do not redefine execution time,
route-specific communication, insertion scheduling, serial contention, cost, energy,
or schedule identity.

The frozen implementation version is `ifc_v1`; the calibration artifact version is
`ifc_calibration_v1`.

## Shared deterministic conventions

- Every authoritative time and cost value is an integer. Rank averages and crowding
  calculations use `fractions.Fraction`; binary floating point is not used.
- Resource ties use ascending `resource_id` after the algorithm's primary metric.
- Task-priority ties use ascending `task_id` while preserving precedence readiness.
- Candidate placement uses the same insertion policy as the authoritative schedule
  builder: the earliest safe idle slot at or after all dependency arrivals.
- Actual parent-to-child resource choices always use the materialized
  `communication[edge][source|target]` route.
- HEFT/CPOP average communication rank weights are the exact arithmetic mean over all
  ordered *distinct-resource* pairs. Same-resource zero transfer is not treated as an
  inter-resource average sample.
- Multiple entry and exit tasks are supported directly; no synthetic task is stored
  in benchmark artifacts.

## Deterministic HEFT-IFC

`deterministic_heft_ifc` follows the HEFT list-scheduling structure:

1. Average execution time is computed over every eligible IFC resource.
2. Upward ranks are computed bottom-up using the frozen average communication rule.
3. Ready tasks are selected by descending upward rank.
4. For the selected task, every IFC resource is evaluated using insertion-based
   earliest finish time (EFT) with the actual route from each already placed parent.
5. The minimum `(EFT, resource_id)` candidate is chosen.

The completed mapping is rebuilt and verified by the authoritative schedule builder.

## Deterministic PEFT-IFC

`deterministic_peft_ifc` follows the PEFT optimistic-cost-table (OCT) structure. For a
task `i` tentatively associated with resource `r`, each child's continuation uses the
minimum over child resource `q` of:

`OCT(child,q) + execution(child,q) + communication(i->child,r|q)`.

The maximum child continuation is the OCT value for `(i,r)`; exit-task OCT values are
zero. Task priority is descending exact mean OCT. Resource selection minimizes:

`OEFT = EFT(i,r) + OCT(i,r)`

with ties by lower EFT and then `resource_id`.

The IFC adaptation is intentionally route-specific: the original PEFT continuation
term is evaluated with the benchmark's materialized source/target route instead of a
single homogeneous-link transfer constant.

## Deterministic CPOP-IFC

`deterministic_cpop_ifc` computes HEFT-style upward ranks and forward downward ranks.
Task priority is `rank_u + rank_d`. Tasks whose priority equals the maximum critical
length form the CPOP critical set. One IFC resource is chosen for that complete set by
minimum summed critical-task execution time, tied by `resource_id`.

Critical-set tasks are restricted to that resource. Other ready tasks consider the
whole IFC resource pool and choose minimum insertion-based EFT. Final timing and
metrics are again rebuilt by `build_schedule`.

## Deterministic cost reference

`deterministic_cost_reference_ifc` provides the economical endpoint without pretending
to solve a time objective. Because v1 monetary cost is the additive sum of per-task
`compute_cost_ncu` and network monetary cost is disabled, the globally minimum compute
cost is obtained by restricting each task to resources attaining that task's minimum
materialized cost.

Tasks use HEFT upward-rank priority. If several resources have the same minimum task
cost, the reference chooses minimum insertion-based EFT and then `resource_id`. This
preserves the globally minimum compute cost while avoiding arbitrary equal-cost
placement.

## Deterministic MOHEFT calibration pass

`deterministic_moheft` is the retained bi-objective calibration search with `K = 50`.
It uses the HEFT upward-rank task order. At each task, every retained partial schedule
is expanded by assigning that task to every IFC resource. Each expansion is measured
by partial makespan and exact accumulated compute cost.

The candidate population is reduced to at most `K` using deterministic two-objective
nondominated-front ranking followed, when a front must be truncated, by crowding
distance. Crowding arithmetic is exact rational arithmetic. Objective-boundary
solutions are preferred; remaining ties use `(makespan, cost, deterministic mapping
path)`.

Final retained mappings are rebuilt with the authoritative scheduler. Any mismatch
between the incremental MOHEFT metrics and the authoritative makespan/cost is an
implementation error. Duplicate final MOHEFT schedules are removed. When calibration
artifacts are assembled, MOHEFT schedules identical to an explicit reference output
are omitted. Different explicit reference algorithms are allowed to converge to the
same canonical schedule; scheduler provenance remains distinct even when their output
is identical.

## Diagnostic lower bounds

The calibration artifact also stores two deterministic optimistic lower bounds:

- `t_cp_lb_us`: longest optimistic DAG path using each task's fastest execution time
  and each edge's minimum materialized communication time over all resource pairs;
- `t_capacity_lb_us`: aggregate work divided by total IFC MIPS, rounded upward.

`t_lb_us = max(t_cp_lb_us, t_capacity_lb_us)`.

These values diagnose difficulty. They do not define deadlines and are not claimed to
be attainable.

## Calibration artifact and validation

Run one calibration with:

```bash
python -m generator.cli calibrate-instance \
  --config config/benchmark-v1.yaml \
  --base-instance <base-instance.json> \
  --output <calibration-result.json>
```

Validate the stored result against the exact base instance with:

```bash
python -m validation.cli calibration-result \
  --result <calibration-result.json> \
  --base-instance <base-instance.json>
```

Validation checks the calibration schema and anchor rules, the candidate-set checksum,
and every reference/MOHEFT schedule through the authoritative base-instance evaluator.
