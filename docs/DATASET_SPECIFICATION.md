# Dataset Specification — Draft v0.1

## 1. Purpose

This benchmark is intended to evaluate workflow schedulers in a heterogeneous IoT–Fog–Cloud environment under identical, reproducible conditions. The dataset must remain algorithm-neutral: no instance may be regenerated, filtered, or tuned after observing the performance of a proposed scheduler.

## 2. Unit of evaluation

One benchmark **instance** represents the complete scheduling input for one workflow execution:

- one workflow DAG,
- one fixed resource environment,
- task computational requirements,
- dependency/data-transfer requirements,
- execution-time estimates for every valid task–resource pair,
- communication parameters,
- cost and energy parameters,
- a reference makespan,
- one or more externally defined deadline levels,
- complete provenance and deterministic seeds.

Every scheduler receives the same instance without alteration.

## 3. Workflow families

Initial scientific-workflow families retained from the existing research direction:

1. Montage
2. CyberShake
3. Inspiral/LIGO
4. SIPHT
5. Genome

These families provide distinct DAG shapes and communication/computation characteristics. The source/provenance of each workflow topology must be recorded in the manifest. Synthetic structural transformations, if used later, must be explicitly labelled and must not silently replace the original family semantics.

## 4. Workflow-size levels

The benchmark must contain at least 5–7 distinct task-count levels per workflow family. Proposed canonical levels for v1:

- 50 tasks
- 100 tasks
- 200 tasks
- 300 tasks
- 500 tasks
- 750 tasks
- 1000 tasks

Exact available task counts may differ slightly when the upstream workflow generator produces a nearby canonical topology. The manifest must record both the requested and actual task counts; instances must never pretend to have a task count they do not have.

## 5. Multiple instances / topology seeds

A single topology per family/size is insufficient for robust conclusions. v1 should support multiple deterministic variants. Initial target:

- 5 workflow families
- 7 size levels
- 5 topology/data seeds per family-size pair

This yields **175 workflow DAG variants** before multiplying by infrastructure/constraint scenarios.

The number `5` is an initial benchmark-design choice and remains reviewable before v1 freeze.

## 6. IoT–Fog–Cloud environment

The infrastructure is heterogeneous and contains three tiers:

### IoT / edge tier

Resource-constrained devices near data sources. Characteristics:

- low compute capacity,
- low monetary compute cost,
- strict power/energy relevance,
- low latency to local producers,
- not every task must be eligible for execution here.

### Fog tier

Intermediate compute nodes close to the edge. Characteristics:

- moderate compute capacity,
- moderate energy/cost,
- lower WAN latency than cloud,
- geographically/topologically closer to IoT resources.

### Cloud tier

High-capacity remote infrastructure. Characteristics:

- highest compute capability,
- explicit monetary cost,
- WAN communication overhead from edge/fog,
- multiple heterogeneous VM/resource classes.

The exact numeric resource catalogue belongs in `RESOURCE_MODEL.md` and will be frozen independently of scheduler behaviour.

## 7. Task representation

Each task must include at minimum:

- `task_id`
- workflow/family metadata
- computational workload (e.g. MI or an equivalent normalized compute quantity)
- input/output data characteristics where available
- parent task IDs
- child task IDs
- eligibility constraints, if any
- provenance/source metadata

Execution times should be represented explicitly in the frozen instance rather than recomputed differently by each scheduler.

## 8. Dependency representation

Each directed edge must include:

- `parent_task_id`
- `child_task_id`
- data volume transferred
- any provenance relating the transfer volume to the source workflow

The DAG must be acyclic and all referenced tasks must exist.

## 9. Execution-time matrix

For every task `t` and every eligible resource `r`, the instance must provide an execution-time estimate `ET[t,r]`.

This prevents individual baseline implementations from applying inconsistent task-to-resource performance formulas.

If the matrix is derived from computational workload and resource capacity, the generator must preserve both the underlying inputs and the generated matrix so results are auditable.

## 10. Communication-time model

Communication time must be derived consistently from:

- data volume,
- source and destination resource/tier,
- link bandwidth,
- propagation/base latency,
- any explicitly modelled contention or load scenario.

Communication within the same resource is zero unless the benchmark explicitly models local I/O overhead.

The resource/network topology used to derive communication delay must be frozen with the instance.

## 11. Cost model

At minimum, resource execution cost must be derivable from:

`compute_cost = execution_time × resource_price_per_second`

If network transfer cost is modelled, it must be a separate explicit component and not hidden inside compute price.

## 12. Energy model

The existing research direction has used separable compute and network energy components. v1 should preserve the raw parameters required for these components rather than baking in an algorithm-specific objective weighting.

At minimum, the dataset should expose:

- resource power-related parameter(s),
- execution time,
- network-energy-per-data parameter(s),
- transfer data volume.

The evaluation layer may compute objective totals, but the immutable benchmark must contain the inputs.

## 13. Deadline design

Deadlines must not be chosen from the proposed novel scheduler. A scheduler-independent reference makespan must first be computed from an explicitly documented reference procedure, then deadline levels derived from it.

The proposed structure is:

`deadline(instance, factor) = reference_makespan(instance) × deadline_factor`

The final reference-makespan method and factors are specified separately in `DEADLINE_STRATEGY.md` and must be frozen before baseline comparison.

## 14. Scenario dimensions

A benchmark instance may vary over independent dimensions such as:

- workflow family,
- workflow size,
- topology/data seed,
- resource scale,
- infrastructure/network profile,
- deadline factor,
- optional controlled load configuration.

Dimensions must be orthogonal where possible so a result can be attributed to a known experimental change.

## 15. Instance identity

Every generated instance must have a deterministic, human-readable identifier encoding the relevant experimental dimensions, for example:

`montage-n200-seed003-rs02-balanced-df150`

The exact naming convention will be frozen in the schema.

## 16. Reproducibility requirements

Each instance must record:

- generator version/commit,
- configuration version,
- all random seeds,
- source workflow provenance,
- requested and actual task counts,
- resource-profile identifier,
- deadline/reference method version,
- hashes/checksums of immutable files.

Generating v1 twice using the same version and seeds must produce byte-identical canonical outputs where practical, or logically identical outputs with deterministic canonical serialization.

## 17. Validation gates

An instance cannot enter the frozen dataset unless it passes at least:

1. schema validation,
2. DAG acyclicity,
3. task-reference integrity,
4. exact/recorded task count check,
5. valid resource references,
6. complete eligible task–resource execution-time matrix,
7. non-negative execution/communication/cost/energy inputs,
8. deterministic ID uniqueness,
9. reference makespan/deadline consistency,
10. reproducibility/checksum validation.

## 18. Freeze policy

Once `datasets/v1` is declared frozen:

- algorithms may read but never mutate benchmark files,
- failed algorithm runs do not justify modifying instances,
- a benchmark correction requires a new version (e.g. v1.1/v2) and a changelog,
- all algorithms used in a paper must be compared on the same benchmark version.

## 19. Initial benchmark-size calculation

Using the current draft choices:

- 5 workflow families
- 7 task-count levels
- 5 seeds

= **175 base workflow variants**.

The final number of scheduling instances will be:

`175 × resource_scales × infrastructure_profiles × deadline_factors × load_profiles`

We should deliberately choose those remaining dimensions so the experiment is statistically useful without creating unnecessary tens of thousands of redundant cases.

## 20. Open decisions before v1 freeze

The following are intentionally **not yet locked**:

- exact number of seeds,
- exact resource catalogue and resource-scale levels,
- infrastructure/network profiles,
- whether controlled background-load scenarios belong in v1,
- final reference-makespan procedure,
- final deadline factors,
- exact JSON/CSV file partitioning,
- whether task eligibility constraints are derived from task type or remain universal in the first dataset version.

These must be resolved from research-methodological considerations, not from whichever choice improves the proposed scheduler's result.
