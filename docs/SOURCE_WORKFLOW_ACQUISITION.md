# Source Workflow Acquisition — v1 Pilot Candidate

## Purpose

The IFC benchmark must preserve the statistical workflow structure, runtime, and file-size characteristics of established Pegasus scientific-workflow models without pretending that an upstream legacy generator is more reproducible or exact than it actually is.

V1 separates two stages:

1. **source acquisition** — obtain and freeze upstream Pegasus DAX artifacts;
2. **IFC benchmark generation** — deterministically normalize those frozen artifacts and combine them with the committed IFC resource/network/QoS model.

Only stage 2 is required to regenerate byte-equivalent IFC benchmark instances. Stage 1 is a provenance/acquisition step whose selected raw artifacts are immutable inputs once committed.

## Upstream generator pinned for v1 pilot

Repository: `pegasus-isi/WorkflowGenerator`

Implementation: `bharathi`

Pinned upstream commit:

`bb1f8d43fe203f5c2cb209540531998af52000ea`

The Bharathi implementation supports all five required application DAX families:

- CYBERSHAKE
- MONTAGE
- SIPHT
- LIGO
- GENOME

and its workflow structure, runtime, and file-size distributions were derived from real workflows.

## Why upstream regeneration is not treated as deterministic

The legacy Bharathi source contains unseeded randomness. V1 therefore does not claim an upstream seed can reproduce an identical DAX.

Raw DAX files are instead frozen source artifacts. Each artifact records:

- upstream repository and pinned commit;
- application family;
- benchmark target task count;
- acquisition request mode and request parameters;
- acquisition replicate ID;
- acquisition attempt index;
- actual parsed DAX job count;
- SHA-256 checksum;
- acquisition command/environment metadata.

The raw DAX checksum is the source reproducibility anchor.

## Replicates

For every workflow family and target size, acquire three independent source artifacts: `r01`, `r02`, and `r03`.

This yields:

`5 families × 7 sizes × 3 source replicates = 105 frozen source DAX files`

These are crossed with resource scale, scenario profile, and joint QoS profile:

`105 × 3 scales × 3 profiles × 3 QoS profiles = 2,835 IFC benchmark instances`

## Exact task-count rule

The seven benchmark size labels represent **actual parsed workflow task counts**:

`60, 100, 200, 400, 600, 800, 1000`

`allowed_size_deviation = 0`.

The earlier common target of 50 was retired before dataset freeze because the pinned Genome model cannot structurally produce exactly 50 jobs. A nearby Genome DAG is never relabelled as 50.

## Family-aware upstream request policy

### Montage, CyberShake, and SIPHT

These families use Bharathi `--numjobs/-n` as an upstream model input. Because `--numjobs` is not always an exact-output contract, each candidate request is tried twice before increasing it by one:

`N, N, N+1, N+1, N+2, N+2, ...`

Only an emitted DAX whose parsed task count equals the benchmark target is accepted.

### LIGO

LIGO also uses `--numjobs`, but the pinned implementation rejects odd requests and can transiently fail topology construction for otherwise valid even requests. Therefore each even request is tried five times and the request advances by two:

`N ×5, (N+2) ×5, (N+4) ×5, ...`

The exact parsed task-count rule remains unchanged.

### Genome

Genome does **not** use `--numjobs` for core v1 acquisition.

The pinned Genome generator exposes explicit `--lanes/-l` and `--sequences/-s` parameters. Inspection of its construction shows that a one-lane workflow contains exactly:

`task_count = 4 × sequences + 4`

All configured common targets are divisible by four, so v1 fixes:

`lanes = 1`

and derives:

`sequences = target/4 - 1`

Examples:

- 60 tasks → `-l 1 -s 14`
- 100 tasks → `-l 1 -s 24`
- 200 tasks → `-l 1 -s 49`
- 1000 tasks → `-l 1 -s 249`

This is source-backed exact construction, not post-generation trimming or relabelling. Because the upstream generator still randomizes runtime/file-size values, repeated invocations can produce checksum-distinct source replicates even when the structural lane/sequence parameters are identical.

Genome manifest entries record:

- `request_mode: genome_lanes_sequences_exact`
- `requested_numjobs: null`
- `requested_lanes: 1`
- `requested_sequences: <derived value>`

## Bounded acquisition

The total attempt budget remains `max_attempts_per_replicate = 100`.

For every attempt:

1. invoke the pinned Bharathi generator using the family-specific request mode;
2. parse the emitted DAX and count actual jobs;
3. validate XML/DAX structure, runtimes, dependencies, and required file metadata;
4. accept only if `actual_task_count == benchmark_target`;
5. reject duplicate checksums within the same family/size replicate set;
6. continue according to the predeclared family-specific request policy;
7. fail after the bounded attempt budget rather than accepting an approximate size.

## Anti-selection-bias rule

For each family/size pair, accept the **first three** artifacts that satisfy only the declared structural gates:

- exact actual task count;
- valid DAG/DAX;
- required task-runtime metadata present and valid;
- dependency/file metadata parseable under the normalizer contract;
- checksum distinct from already accepted replicates for that family/size.

Do **not** inspect makespan, cost, energy, graph density, critical-path length, or algorithm performance when selecting source artifacts.

## Proposed source tree

```text
source_workflows/
└── pegasus-bharathi-bb1f8d43/
    ├── montage/
    │   ├── 0060/r01.dax
    │   ├── 0060/r02.dax
    │   └── ...
    ├── cybershake/
    ├── ligo/
    ├── sipht/
    └── genome/
```

## Deterministic IFC realization seeds

| Source replicate | IFC realization seed |
| --- | ---: |
| `r01` | `101` |
| `r02` | `202` |
| `r03` | `303` |

These seeds control benchmark-owned deterministic processes only; they do not control legacy Bharathi randomness.

## Source immutability

After source acquisition is reviewed:

- raw DAX files are immutable;
- normalizers read them but never rewrite them;
- source checksums are recorded in generated-instance provenance;
- replacing a raw DAX after dataset freeze requires a new dataset version.

## Validation before pilot generation

The source set must pass:

1. exactly 105 raw artifacts exist;
2. exactly three replicates exist per family/size;
3. every raw artifact has the exact benchmark target task count;
4. every manifest entry records the family-appropriate request parameters and actual count;
5. every raw artifact is a valid DAG;
6. every accepted artifact satisfies the declared metadata gates;
7. no two replicates within one family/size have the same raw checksum;
8. manifest checksum and file checksum agree;
9. every accepted attempt follows the configured family-specific acquisition policy;
10. no selection criterion depends on scheduler results.
