# Source Workflow Acquisition — v1 Pilot Candidate

## Purpose

The IFC benchmark must preserve the statistical workflow structure, runtime, and file-size characteristics of established Pegasus scientific-workflow models without pretending that an upstream legacy generator is more reproducible or exact than it actually is.

V1 therefore separates two stages:

1. **source acquisition** — obtain and freeze upstream Pegasus DAX artifacts;
2. **IFC benchmark generation** — deterministically normalize those frozen artifacts and combine them with the committed IFC resource/network/QoS model.

Only stage 2 is required to regenerate byte-equivalent IFC benchmark instances. Stage 1 is a provenance/acquisition step whose selected raw artifacts are immutable inputs once committed.

## Upstream generator pinned for v1 pilot

Repository: `pegasus-isi/WorkflowGenerator`

Implementation: `bharathi`

Pinned upstream commit:

`bb1f8d43fe203f5c2cb209540531998af52000ea`

The Bharathi implementation is selected because its own README explicitly supports all five required application DAX families:

- CYBERSHAKE
- MONTAGE
- SIPHT
- LIGO
- GENOME

and states that workflow structure, runtime, and file-size distributions were derived from real workflows.

The upstream repository itself is archived/unmaintained in favor of newer WorkflowHub work. Pinning the exact legacy commit prevents future upstream changes from silently altering provenance.

## Why upstream regeneration is not treated as deterministic

The legacy Bharathi source contains several unseeded `java.util.Random` constructions, including a shared random utility and topology/connection helpers. Therefore a nominal workflow seed cannot be claimed to reproduce an identical DAX from this upstream implementation.

V1 must not label `101`, `202`, or `303` as upstream workflow seeds.

Instead, raw DAX files are **frozen source artifacts**. Each artifact receives:

- upstream repository and pinned commit;
- application family;
- benchmark target task count;
- actual `--numjobs/-n` value sent to Bharathi;
- acquisition replicate ID;
- acquisition attempt index;
- actual parsed DAX job count;
- SHA-256 checksum;
- acquisition command/environment metadata.

The raw DAX checksum, not an unsupported upstream seed claim, is the reproducibility anchor.

## Replicates

For every workflow family and target size, acquire three independent source artifacts:

- `r01`
- `r02`
- `r03`

This yields:

`5 families × 7 sizes × 3 source replicates = 105 frozen source DAX files`

These 105 source workflows are then crossed with resource scale, scenario profile, and joint QoS profile:

`105 × 3 scales × 3 profiles × 3 QoS profiles = 2,835 IFC benchmark instances`

The benchmark size therefore does not change.

## Exact task-count rule

The seven benchmark size labels represent **actual parsed workflow task counts**, not the upstream request parameter:

`50, 100, 200, 400, 600, 800, 1000`

`allowed_size_deviation = 0` remains unchanged.

A real full-source acquisition run demonstrated why this distinction is necessary: Bharathi SIPHT invoked with `-n 50` repeatedly emits a 48-task DAG. Inspection of the pinned SIPHT implementation confirms that `numJobs` is transformed into subworkflow counts and is therefore a model/planning input rather than an exact-output contract.

### Deterministic request search

For benchmark target `N`, one replicate uses the fixed request sequence:

`N, N+1, N+2, ... , N+(max_attempts-1)`

With the v1 bound of 100 attempts, the largest permitted upstream request is `N+99`.

For each attempt:

1. invoke the pinned Bharathi `AppGenerator` with current `requested_numjobs`;
2. parse the emitted DAX and count actual jobs;
3. validate XML/DAX structure, runtimes, dependencies, and required file metadata;
4. accept only if `actual_task_count == benchmark_target`;
5. reject an otherwise valid artifact whose actual count differs from the target;
6. proceed to the next larger request value;
7. fail acquisition after the bounded search rather than accepting a nearby actual size.

Therefore a source manifest may contain, for example:

- `target_task_count: 50`
- `requested_numjobs: 52`
- `actual_task_count: 50`

The benchmark instance is still a genuine **50-task** workflow. The value 52 is only upstream acquisition provenance.

This rule is family-neutral; there is no hand-coded SIPHT correction formula. It adapts to the pinned generator's actual output while preserving an exact cross-family benchmark size grid.

## Anti-selection-bias rule

For each family/size pair, accept the **first three** acquisition attempts that satisfy only the predeclared structural gates:

- exact actual task count;
- valid DAG/DAX;
- required task-runtime metadata present and valid;
- dependency/file metadata parseable under the normalizer contract;
- checksum distinct from already accepted replicates for that family/size.

Do **not** inspect makespan, cost, energy, graph density, critical-path length, or algorithm performance to decide which valid DAX to keep.

The deterministic increasing request sequence and first-valid rule prevent manual hunting for a favorable topology.

## Proposed source tree

```text
source_workflows/
└── pegasus-bharathi-bb1f8d43/
    ├── montage/
    │   ├── 0050/r01.dax
    │   ├── 0050/r02.dax
    │   └── ...
    ├── cybershake/
    ├── ligo/
    ├── sipht/
    └── genome/
```

A source manifest sits beside or above this tree and records checksums/provenance for every raw artifact.

## Deterministic IFC replication seeds

The numerical IFC environment remains reproducibly seeded. Map source replicate IDs to deterministic IFC realization IDs:

| Source replicate | IFC realization seed |
| --- | ---: |
| `r01` | `101` |
| `r02` | `202` |
| `r03` | `303` |

These seeds control only benchmark-owned deterministic processes such as resource-class filling or future explicitly enabled stochastic normalization. They do not claim to control the legacy upstream DAX generator.

## Source immutability

After source acquisition is reviewed:

- raw DAX files are immutable;
- normalizers read them but never rewrite them;
- source checksums are recorded in generated-instance provenance;
- changing or replacing a raw DAX after dataset freeze requires a new dataset version.

## Validation before pilot generation

The source set must pass:

1. exactly 105 raw artifacts exist;
2. exactly three replicates exist per family/size;
3. every raw artifact has the exact benchmark target task count;
4. every manifest entry records both `requested_numjobs` and actual count;
5. every raw artifact is a valid DAG;
6. every accepted artifact satisfies the declared metadata gates;
7. no two replicates within one family/size have the same raw checksum;
8. manifest checksum and file checksum agree;
9. every accepted attempt follows the deterministic increasing request sequence;
10. no selection criterion depends on a scheduler's results.
