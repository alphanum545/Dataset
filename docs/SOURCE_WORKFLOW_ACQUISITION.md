# Source Workflow Acquisition — v1 Pilot Candidate

## Purpose

The IFC benchmark must preserve the statistical workflow structure, runtime, and file-size characteristics of established Pegasus scientific-workflow models without pretending that an upstream legacy generator is more reproducible than it actually is.

V1 therefore separates two stages:

1. **source acquisition** — obtain and freeze upstream Pegasus DAX artifacts;
2. **IFC benchmark generation** — deterministically normalize those frozen artifacts and combine them with the committed IFC resource/network/QoS model.

Only stage 2 is required to regenerate byte-equivalent IFC benchmark instances. Stage 1 is a provenance/acquisition step whose selected raw artifacts are immutable inputs once committed.

## Upstream generator pinned for v1 pilot

Repository:

`pegasus-isi/WorkflowGenerator`

Implementation:

`bharathi`

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
- requested job-count argument;
- acquisition replicate ID;
- acquisition attempt index;
- actual DAX job count;
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

The seven benchmark size labels represent **actual normalized workflow task counts**, not approximate labels:

`50, 100, 200, 400, 600, 800, 1000`

For each family/size/replicate:

1. invoke the pinned Bharathi `AppGenerator` with the target through the application's `--numjobs/-n` interface;
2. parse the emitted DAX and count actual jobs;
3. validate XML/DAX structure and required runtime/file metadata;
4. accept the artifact only if `actual_job_count == target_job_count`;
5. otherwise discard it only for this declared structural reason and acquire the next attempt;
6. fail acquisition after `100` attempts rather than silently accepting a nearby size.

There is therefore **no requested-vs-actual percentage tolerance** in core v1.

If a family/size cannot produce the exact target within the bounded acquisition rule, that family/size is a benchmark-design failure requiring explicit review; it is not automatically relabelled or rounded.

## Anti-selection-bias rule

For each family/size pair, accept the **first three** acquisition attempts that satisfy only the predeclared structural gates:

- exact task count;
- valid DAG/DAX;
- required task-runtime metadata present and valid;
- dependency/file metadata parseable under the normalizer contract.

Do **not** inspect makespan, cost, energy, graph density, critical-path length, or algorithm performance to decide which valid DAX to keep.

This prevents source-workflow selection from being tuned to favor or disadvantage any scheduling algorithm.

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

A source manifest should sit beside or above this tree and record checksums/provenance for every raw artifact.

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
3. every raw artifact has the exact target job count;
4. every raw artifact is a valid DAG;
5. every accepted artifact satisfies the declared metadata gates;
6. no two replicates within one family/size have the same raw checksum; if duplicates occur, acquisition continues until three distinct valid artifacts are collected or the 100-attempt bound is reached;
7. manifest checksum and file checksum agree;
8. no selection criterion depends on a scheduler's results.
