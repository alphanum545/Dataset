# Workflow Normalization Model — v1 Pilot Candidate

## Source boundary

The benchmark uses frozen synthetic scientific workflows from the Pegasus WorkflowGenerator Bharathi lineage for:

- Montage
- CyberShake
- LIGO
- SIPHT
- Genome

The pinned upstream revision and source-acquisition rules are defined in `SOURCE_WORKFLOW_ACQUISITION.md`.

The upstream generator's raw DAX files are immutable source artifacts once accepted. IFC normalization does not rerun the legacy generator during normal dataset regeneration.

## Goal

Preserve the structural, runtime, and file-size characteristics of the source scientific workflows while converting them into one algorithm-neutral representation suitable for heterogeneous IoT-Fog-Cloud scheduling.

The normalizer must not replace source runtimes and file sizes with unrelated random task lengths or communication volumes.

## Canonical DAG

Each normalized workflow contains:

- tasks with stable IDs;
- directed precedence edges;
- source runtime metadata;
- source input/output file metadata when available;
- a derived machine-independent work value;
- a derived edge data-transfer size;
- workflow-family and source-artifact provenance.

The normalized DAG remains acyclic and preserves source precedence semantics.

## Frozen source replicates

For every family and exact target size, v1 uses three raw source artifacts:

- `r01`
- `r02`
- `r03`

The source replicate identity is anchored by SHA-256 checksum, not an unsupported upstream RNG seed.

This produces `5 × 7 × 3 = 105` normalized base workflows.

## Exact task-count rule

Core v1 size labels are exact actual task counts:

- 50
- 100
- 200
- 400
- 600
- 800
- 1000

The acquisition stage passes the desired count through the Bharathi application's `--numjobs/-n` option and accepts only DAX artifacts whose parsed job count equals the target exactly.

`allowed_size_deviation = 0`.

There is no percentage tolerance and no silent relabelling. If a family/size cannot produce an exact valid artifact within the bounded acquisition rule, acquisition fails for explicit review.

## Task work derivation

For v1, normalize source runtime into machine-independent work using:

`reference_mips = 1000`

For a task whose source runtime is `source_runtime_s`:

`task_work_mi = source_runtime_s × 1000`

This is a unit-normalization convention. It is not a claim that the original task executed on a historical 1000-MIPS processor.

For resource `r`:

`execution_time_us(i,r) = ceil(task_work_mi(i) × 1,000,000 / mips(r))`

The authoritative materialized execution-time unit is integer microseconds.

### Runtime decimal handling

Source runtime text is parsed with exact-decimal semantics. The generator must not round-trip runtime through binary floating point before computing canonical work/execution values. The exact decimal text or normalized decimal representation and derivation version are retained in provenance.

## Dependency data derivation

Communication volume for a precedence edge is derived from files produced by the parent and consumed by the child whenever source file metadata establishes the linkage.

For edge `(parent, child)`:

`edge_data_bytes = sum(size(file))`

for files that are outputs of `parent` and inputs of `child`.

V1 uses decimal megabytes for descriptive data-size fields:

`edge_data_mb = edge_data_bytes / 1,000,000`

For exact communication calculations, the generator uses integer bytes/bits rather than the rounded/display MB value:

`edge_data_bits = edge_data_bytes × 8`

## Missing or ambiguous file linkage

Do not silently invent edge sizes.

Fallback hierarchy:

1. explicit shared-file size from the frozen source DAX;
2. workflow-family distribution that is itself part of the pinned source model and can be reconstructed without arbitrary new assumptions;
3. otherwise mark the source artifact unsupported for core v1 and fail source/normalization validation.

Core v1 does **not** introduce a generic seeded edge-size distribution merely to make an unsupported source pass.

The fraction of directly derived versus fallback-derived edges is reported. Any fallback mechanism used must be versioned and separately identifiable.

## Entry and exit data

External input files for entry tasks and final outputs from exit tasks are retained as metadata. They are not automatically counted as internal DAG-edge communication.

Core v1 evaluates workflow-internal dependency communication only. External ingress/egress can be introduced later as a separately versioned experiment if origin/sink semantics are defined consistently for all workflow families.

## Stable normalization ordering

- tasks sorted by canonical task ID;
- dependencies sorted by `(parent_id, child_id)`;
- file metadata sorted by stable file identifier/path;
- resource-independent task fields serialized canonically;
- integers serialized as integers;
- exact decimal source values normalized through one documented decimal policy.

## Validation

For every frozen raw and normalized workflow:

- raw source checksum matches source manifest;
- actual task count equals the declared target exactly;
- three replicates per family/size are checksum-distinct;
- DAG is acyclic;
- all task IDs are unique;
- every edge endpoint exists;
- source runtimes used for work derivation are finite and positive;
- derived work and execution matrices are positive and reconstructible;
- every edge data size is nonnegative and provenance-labelled;
- no scheduler result influenced source-artifact acceptance;
- normalized regeneration from the same raw source and configuration produces identical content/checksum.

## Provenance to record

At minimum:

- workflow family;
- pinned source repository and commit;
- raw DAX path and SHA-256;
- source replicate ID;
- acquisition attempt index;
- acquisition command/options;
- exact target and actual task count;
- normalization code commit;
- reference MIPS;
- decimal MB convention;
- edge-data derivation status;
- normalized workflow checksum.
