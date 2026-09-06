# Deadline Sensitivity Analysis — v1 Draft

## Purpose

This document records the development-only sensitivity analysis used to choose the final pilot deadline interpolation levels before the proposed scheduling mechanism is designed or tuned.

The analysis uses only the 159 unique base realizations represented by the 160 development inputs. The 40 holdout bases are not used for parameter selection, and no comparative holdout scheduler outcome is inspected.

## Method held fixed

The deadline construction remains the feasible time-cost envelope:

`D = T_fast + ceil(alpha * (T_economical - T_fast))`

where:

- `T_fast` is the minimum makespan among the validated deterministic IFC calibration schedules;
- `T_economical` is the makespan of the lowest-cost validated calibration schedule;
- the proposed algorithm is excluded from calibration;
- arithmetic is exact integer/rational arithmetic.

Only the profile interpolation fractions are revised. The calibration portfolio, anchor definitions, scheduler semantics, selection, source workflows, resource model, network model, and budget-gap fractions remain unchanged.

## Why the original fractions were rejected

The first materialized pilot used:

- tight: `1/10`;
- moderate: `1/2`;
- relaxed: `9/10`.

Across the 159 unique development bases, the economical anchor was typically much slower than the fast anchor: the median `T_economical / T_fast` ratio was about `27x`. Therefore `1/10` of the envelope did not mean a deadline near `T_fast`; the median `D_tight / T_fast` was about `3.56x` when the same `1/10` level was applied uniformly to every development base.

More importantly, under the original `1/10` tight level, HEFT-IFC, PEFT-IFC, and CPOP-IFC all met the deadline on every development base. Thus the nominally tight level did not create meaningful time pressure among the time-oriented reference schedulers.

## Development-only fraction sweep

For each unique development base, candidate fractions were applied to the same frozen `T_fast` and `T_economical` anchors. For each candidate fraction, the analysis measured the proportion of unique stored calibration schedules whose makespan was at or below the resulting deadline.

| Envelope fraction | Median feasible calibration fraction | Interquartile range | Min–max |
| --- | ---: | ---: | ---: |
| `1/100` | 0.094 | 0.093–0.131 | 0.019–0.189 |
| `1/50` | 0.132 | 0.111–0.179 | 0.019–0.346 |
| `1/20` | 0.241 | 0.204–0.299 | 0.093–0.472 |
| `1/10` | 0.352 | 0.315–0.419 | 0.185–0.547 |
| `1/4` | 0.528 | 0.481–0.566 | 0.352–0.698 |
| `1/2` | 0.679 | 0.660–0.717 | 0.519–0.811 |
| `3/4` | 0.830 | 0.811–0.849 | 0.593–0.889 |
| `9/10` | 0.906 | 0.889–0.925 | 0.630–0.962 |

The selected levels are:

- **tight:** `1/100`;
- **moderate:** `1/4`;
- **relaxed:** `3/4`.

This gives a deliberately separated progression of approximately 9%, 53%, and 83% median calibration-schedule feasibility without defining deadlines from the proposed algorithm.

## Reference-scheduler behavior at the selected levels

On the 159 unique development bases:

- at `1/100`, HEFT-IFC met 100% of deadlines, CPOP-IFC about 93.7%, and PEFT-IFC about 85.5%; the cost-reference endpoint met 0%;
- at `1/4`, HEFT-IFC, PEFT-IFC, and CPOP-IFC all met the deadline; the cost-reference endpoint remained outside the deadline;
- at `3/4`, the three time-oriented references all met the deadline while the economical endpoint remained outside the deadline by construction for non-degenerate envelopes.

The tight profile therefore creates observable deadline pressure among the time-oriented reference set, while moderate and relaxed profiles progressively admit a larger portion of the calibration trade-off population.

## Stability across workflow families and sizes

Median feasible calibration fractions under the selected levels were stable across all five workflow families:

| Family | `1/100` | `1/4` | `3/4` |
| --- | ---: | ---: | ---: |
| CyberShake | 0.094 | 0.519 | 0.849 |
| Genome | 0.095 | 0.500 | 0.810 |
| LIGO | 0.094 | 0.491 | 0.830 |
| Montage | 0.094 | 0.566 | 0.830 |
| SIPHT | 0.111 | 0.533 | 0.830 |

They were also stable across every configured task-count level from 60 through 1000 tasks. No workflow family or size class forced a separate deadline rule.

## Budget interaction

The budget method is intentionally not retuned in the same step. After the new deadline is constructed, the existing deadline-conditioned cost floor is recomputed:

`C_floor_ref(D) = min cost among calibration schedules satisfying D`

The existing budget gap fractions remain:

- tight: `1/10`;
- moderate: `1/2`;
- relaxed: `9/10`.

Therefore changing the deadline can change the cost-floor witness and the resulting concrete budget even though the budget interpolation fractions themselves are unchanged. The regenerated pilot must pass the full joint-feasibility witness gate before this deadline revision can be frozen.

## Decision discipline

This revision is based only on benchmark calibration behavior from the development split and occurs before the proposed algorithm is formulated or tuned. It does not use holdout comparative outcomes. Any later change to these fractions after proposed-algorithm tuning would require a new benchmark version rather than silently modifying v1.
