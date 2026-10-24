# Unseen-workflow evaluation set v1 (`ifc-unseen-v1`)

## Purpose

Every v1 instance, including the 1,890-instance expansion cohort, is built from the same 105 frozen source DAGs. `ifc-unseen-v1` is a final test on DAGs that no scheduler was designed, debugged or tuned on. It is frozen (sources, then instances) before any scheduler runs on it, and it is evaluated once.

It is **additive**. The v1 pilot (160 development + 40 holdout), the 105 v1 source DAX files and every v1 manifest are not modified.

## What is new

| Part | Source | Families | Sizes | Replicates | DAGs |
|---|---|---|---|---|---:|
| New replicates | Pegasus WorkflowGenerator, Bharathi, pinned `bb1f8d43` (same as v1) | montage, cybershake, ligo, sipht, genome | 60–1000 (7) | r04 | 35 |
| New families | WfCommons/WfChef, pinned `e5418e13` | 1000genome, srasearch, blast | 60–1000 (7) | r01, r02 | 42 |
| | | soykb | 200, 400, 800 | r01, r02 | 6 |
| **Total** | | | | | **83** |

- **r04 replicates** use the unchanged v1 request policy and exact-count rule. Each must be checksum-distinct from the frozen r01–r03 artifacts of the same family and size.
- **New families** were chosen for shapes unlike the v1 five:
  - 1000Genome: a data-heavy wide merge;
  - SRASearch: many independent chains;
  - BLAST: split, a wide parallel stage, then concatenation;
  - SoyKB: deep per-sample pipelines.
- **Excluded on purpose:** WfCommons Montage and Epigenomics, because they model the same applications as v1 Montage and v1 Genome (the Bharathi GENOME model is the Epigenomics workflow).
- **Exact sizes are decided by recipe structure alone.** At the pinned commit, WfChef deterministically picks a base graph for each request and grows it only by whole duplicable microstructures.
  - SoyKB's microstructures have sizes {6, 16}, {6, 26} or {16}, so it can produce exactly 200, 400 and 800 tasks, but not 60 (below its smallest base), 100, 600 or 1000.
  - Unreachable sizes are omitted, never relabelled, by the same rule that retired the v1 Genome-50 size.
  - BLAST, which reaches all seven sizes, was added so the size grid stays complete.
  - This was decided from the recipe structure after a first acquisition attempt failed at SoyKB-100, and before any scheduler ran on any unseen DAG.

## Acquisition rules for WfCommons (`generator.unseen`)

1. WfChef's `num_tasks` is an upper bound on graph nodes, and the bound includes two synthetic SRC/DST nodes that are dropped on output. Every attempt therefore requests exactly `target + 2`; a larger request can only overshoot.
2. There are at most 100 attempts per replicate, each with a fresh seed.
3. Before every attempt the Python `random` and NumPy global RNGs are seeded with the first 4 bytes of `sha256("ifc-unseen-v1|<family>|<target>|<replicate>|<attempt>")`.
4. An attempt is accepted only if:
   - the parsed task count equals the target exactly;
   - the workflow is a valid DAG with positive runtimes and declared files;
   - every dependency shares at least one producer-output/consumer-input file;
   - its checksum is distinct within that family and size.
5. The first valid attempt is taken (anti-selection-bias rule). Makespan, cost, energy, graph metrics and scheduler outcomes are never inspected.
6. The emitted JSON bytes are frozen by SHA-256. As with Bharathi DAX, the frozen artifact, not the seed, is the reproducibility anchor: the output contains a timestamp and random node identifiers.

## Normalization (`generator.wfformat`)

`normalize_wfformat` produces the same canonical workflow as `normalize_dax`, under the same rules:

- **Task work:** exact-decimal runtime × 1000 MI. The JSON is parsed with `Decimal`, never as binary floats.
- **Edge data:** the sum of the shared files' producer sizes. WfFormat declares one size per file id.
- **Missing linkage:** a dependency with no shared file is invalid; no edge size is invented.
- **Entry and exit data:** external inputs and final outputs are not edge communication.
- **Ordering:** the same stable ordering of tasks, dependencies and transfer files.

`normalize_source` dispatches on the file suffix: `.dax` for Pegasus and `.json` for WfFormat. A unit test checks that a WfFormat workflow and the equivalent DAX normalize to identical tasks and dependencies.

## Instances

The instances are the full factorial of every source with each of:

- 3 resource scales;
- 3 scenario profiles;
- 3 QoS profiles.

That gives 83 × 27 = **2,241 QoS instances over 747 base realizations**, with IFC seed 101, 202 or 404 for replicate r01, r02 or r04.

The resource, network, scenario, cost, calibration and QoS rules are read unchanged from `config/benchmark-v1.yaml`, and its SHA-256 is recorded in the manifest. Materialization uses the v1 code path:

- `build_base_instance`;
- `build_calibration_result` (MOHEFT K = 50);
- `build_qos_instance`, which applies the deadline and budget interpolation and selects the joint-feasibility witness.

## Order of operations

1. `unseen-source-acquisition` (manual dispatch) acquires the 83 sources and pushes them with `manifests/source-workflows-unseen-v1.json` to a new `generated/source-workflows-unseen-v1-<sha8>` branch for review and merge.
2. Instances are materialized in CI and their SHA-256 values are frozen in a manifest, before any scheduler runs.
3. Schedulers are run once. The results are reported whatever they are.
