# Workflow Normalization Model — v1 Draft

## Source

The benchmark uses synthetic scientific workflows from the Pegasus WorkflowGenerator lineage for the five selected families. The upstream generator documentation states that its workflow models are parameterized using file-size and task-runtime data from execution logs and workflow publications. The legacy repository is no longer maintained, so the exact generator/version used for v1 must be recorded in provenance and frozen with the dataset.

## Goal

Preserve the structural and workload characteristics of the source scientific workflows while converting them into one algorithm-neutral representation suitable for heterogeneous IoT-Fog-Cloud scheduling.

The normalization process must not replace source runtimes and file sizes with unrelated random task lengths or communication volumes.

## Canonical DAG

Each normalized workflow contains:

- tasks with stable IDs;
- directed precedence edges;
- source runtime metadata;
- source input/output file metadata when available;
- a derived machine-independent work value;
- a derived edge data-transfer size;
- workflow-family and generator provenance.

The normalized DAG must remain acyclic and preserve source precedence semantics.

## Task work derivation

Scientific workflow generators commonly expose a runtime estimate for each generated job. A single runtime cannot be used directly as the execution time on every heterogeneous resource.

For v1, normalize source runtime into machine-independent work using a fixed reference performance:

`task_work_mi = source_runtime_s × reference_mips`

Candidate reference:

`reference_mips = 1000`

This does not claim that the source workflow originally ran on a 1000-MIPS processor. It is a unit-conversion convention that preserves relative source runtime while allowing resource-dependent execution times.

For resource `r`:

`execution_time_s(i,r) = task_work_mi(i) / resource_mips(r)`

The reference MIPS value must be stored in dataset metadata and configuration. Changing it after freeze requires a new dataset version.

## Why this approach

This keeps three important properties:

1. relative task heaviness from the source workflow is preserved;
2. heterogeneous resources produce different task execution times;
3. all schedulers receive exactly the same execution model.

Using fresh random instruction counts would discard workload information already present in the workflow generator.

## Dependency data derivation

Communication volume for a precedence edge should be derived from files produced by the parent and consumed by the child whenever the source representation provides file-level dependencies.

For edge `(parent, child)`:

`edge_data_bytes = sum(size(file))`

for files that are outputs of `parent` and inputs of `child`.

Then:

`edge_data_mb = edge_data_bytes / 1_000_000`

The generator must document whether decimal MB or MiB is used and apply that convention everywhere. Candidate v1 uses decimal MB.

## Missing or ambiguous file linkage

Do not silently invent edge sizes. If the source workflow format cannot establish a parent-child shared-file set, the normalizer must apply a documented fallback policy and mark the edge with provenance such as `data_size_source: fallback`.

The preferred fallback hierarchy is:

1. explicit shared-file size from source metadata;
2. workflow-family empirical distribution supplied by the source generator/model;
3. deterministic seeded fallback distribution defined by v1 configuration.

The fraction of fallback-derived edges must be reported during validation. If it is large, the workflow source/normalization method should be reconsidered before freeze.

## Entry and exit data

External input files for entry tasks and final outputs from exit tasks are retained as task metadata. They are not DAG edge communication unless the scheduling model explicitly includes transfer to/from an IoT data origin or sink.

For v1, workflow-internal dependency communication and external ingress/egress should remain separate fields so later experiments can decide whether ingress/egress belongs in makespan, cost, and energy objectives.

## Requested versus actual task count

The benchmark has requested size levels of 50, 100, 200, 400, 600, 800, and 1000 tasks. The generator must record:

- requested task count;
- actual normalized task count;
- absolute and relative deviation.

No workflow may be relabelled as an exact size if the source generator produced a materially different node count.

The allowed deviation tolerance remains an explicit pre-freeze decision.

## Determinism

The normalizer must produce byte-equivalent canonical task/dependency values from the same source workflow, configuration, and seed after volatile metadata is normalized.

Stable ordering rules:

- tasks sorted by canonical task ID;
- dependencies sorted by `(parent_id, child_id)`;
- file metadata sorted by stable file identifier/path;
- numeric rounding policy fixed in schema/configuration.

## Validation

For every normalized workflow:

- DAG is acyclic;
- all task IDs are unique;
- every edge endpoint exists;
- every source runtime used for work derivation is finite and positive;
- every derived work value is finite and positive;
- every edge data size is finite and nonnegative;
- provenance records whether runtime/data values were direct or fallback-derived;
- actual task count is reported and checked against requested size;
- regeneration produces identical normalized content.

## Provenance to record

At minimum:

- workflow family;
- source generator project;
- generator version/commit or release;
- generator command/options;
- source workflow seed;
- normalization code commit;
- reference MIPS conversion value;
- MB conversion convention;
- fallback policy/version;
- normalized workflow checksum.
