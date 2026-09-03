# Deadline and Reference Makespan Strategy — Draft v0.1

## Goal

Deadline construction must be independent of the proposed novel scheduler. The benchmark should define a reproducible reference makespan first, then derive deadline scenarios from that reference.

## Design principles

1. **Algorithm neutrality** — do not use the proposed algorithm to define the benchmark deadline.
2. **Reproducibility** — the same instance always receives the same reference makespan and deadlines.
3. **Feasibility awareness** — deadline factors should span challenging through relaxed scenarios rather than creating mostly impossible or trivial cases.
4. **Transparency** — both the reference procedure and the resulting numeric values are stored in the dataset manifest.
5. **Versioning** — any later change to the reference procedure requires a benchmark-version change.

## Candidate reference methodology

The reference should represent a deterministic baseline notion of attainable schedule length rather than the output of whichever algorithm is under study.

The preferred v1 approach is to compute multiple algorithm-independent bounds/reference quantities and then select one documented reference rule before freezing the benchmark.

### Quantity A — optimistic critical-path lower bound

For each task, use its minimum eligible execution time across resources. For each dependency, use an explicitly defined optimistic communication term. Compute the longest source-to-sink path.

This gives a theoretical/optimistic lower-bound-style quantity and is useful for sanity checking, but by itself may produce unrealistically tight deadlines because it ignores resource contention.

### Quantity B — deterministic reference schedule

Use one simple, fixed, published/reference scheduling rule solely as a calibration instrument. It must:

- be deterministic,
- remain unchanged across all experiments,
- not be the proposed scheduler,
- use the same frozen execution/communication model,
- have no dataset-specific tuning.

A classic deterministic list scheduler such as HEFT is a candidate calibration schedule, but the benchmark documentation must clearly distinguish **reference calibration** from **algorithm evaluation**.

### Quantity C — serialized/upper reference sanity value

Compute a deterministic conservative schedule or total-work-based upper reference to detect malformed instances and provide scale context. This is not intended to define deadlines directly.

## Proposed v1 decision rule

Before freeze, evaluate the distributions of the optimistic lower bound and the deterministic reference schedule across all generated base instances. Then lock a rule such as:

`reference_makespan = deterministic_reference_schedule_makespan`

while retaining the optimistic lower bound as metadata.

Why this is preferable to using the lower bound directly:

- it reflects precedence, communication and resource contention in an actual feasible schedule,
- it is reproducible,
- it is independent of the future proposed scheduler,
- deadline factors become interpretable relative to a feasible reference schedule.

This remains a **draft choice** until the initial generated instances are inspected for pathological calibration behaviour.

## Deadline formula

For a frozen reference value `M_ref`:

`D_f = f × M_ref`

where `f` is a benchmark deadline factor.

## Initial candidate deadline factors

A useful first calibration set is:

- `1.00` — reference-tight
- `1.10` — tight
- `1.25` — moderately tight
- `1.50` — moderate
- `2.00` — relaxed

These are not yet frozen. The calibration pass must check the proportion of baseline algorithms meeting each factor. If one factor is universally impossible or universally trivial across essentially every instance, we should revise the factor grid **before** v1 is frozen, without consulting proposed-algorithm performance.

## Anti-leakage rule

After dataset v1 is frozen, deadline factors cannot be changed because a proposed algorithm performs poorly or because another factor would make plots look better.

## Manifest fields

Each scenario should record at minimum:

- `reference_method_version`
- `optimistic_lower_bound`
- `reference_makespan`
- `deadline_factor`
- `deadline`
- calibration implementation/version
- any rounding convention

## Rounding

Use full-precision numeric computation internally. Canonical serialization should use a documented precision policy. Do not round intermediate execution or communication times when calculating the reference makespan.

## Calibration stage

The first generated dataset is initially marked **candidate**, not frozen. We run only benchmark-integrity/calibration analyses to answer:

- Are reference schedules always valid?
- How far is the reference schedule from the optimistic bound?
- Do factors cover meaningful tight-to-relaxed regimes?
- Are there malformed or degenerate workflow/resource combinations?

This calibration is permitted because it evaluates the benchmark design itself. It must not use the proposed novel scheduler to tune factors.

## Final freeze requirement

`DEADLINE_STRATEGY.md` must be promoted from Draft to Frozen and assigned a version before `datasets/v1` is released.
