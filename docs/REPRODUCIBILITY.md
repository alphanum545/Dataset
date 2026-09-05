# Reproducibility and Freeze Policy — v1 Pilot Candidate

## Principle

A benchmark result is meaningful only if another implementation can reconstruct the same scheduling input. Every source of randomness owned by the IFC benchmark must therefore be explicit, versioned, and materialized.

The legacy upstream Pegasus/Bharathi source generator is treated differently: its accepted raw DAX outputs are frozen as immutable source artifacts because the pinned implementation contains unseeded randomness. See `SOURCE_WORKFLOW_ACQUISITION.md`.

## Source-workflow reproducibility boundary

Core v1 contains three frozen source-workflow replicates per family/size:

- `r01`
- `r02`
- `r03`

A source replicate is identified by its raw DAX checksum and acquisition provenance. It is **not** represented as an upstream workflow RNG seed.

The IFC dataset generator must reproduce the same normalized benchmark inputs from the committed raw DAX artifacts and benchmark configuration.

## Benchmark-owned seed separation

Use independent deterministic RNG streams for benchmark-owned stochastic processes:

- `resource_seed` — filling heterogeneous resource-class slots after mandatory class coverage;
- `network_seed` — reserved for any future sampled network realization; current pilot segment values are fixed;
- `constraint_seed` — reserved for future stochastic constraints; current deadline/budget profiles are deterministic.

Do not reuse one global RNG stream for all components. Adding a random draw in one component must not silently change unrelated dimensions.

## V1 realization mapping

Each frozen source replicate maps to one deterministic IFC realization seed:

| Source replicate | IFC realization seed |
| --- | ---: |
| `r01` | `101` |
| `r02` | `202` |
| `r03` | `303` |

The mapping is stable and committed in configuration.

## Stable instance identity

An instance ID must encode or deterministically derive from:

- dataset version;
- workflow family;
- exact workflow size;
- source replicate ID and source checksum;
- resource scale;
- scenario profile;
- IFC realization seed;
- joint QoS profile.

Human-readable fields are present in the manifest even if the final identifier includes a hash.

## Materialization rule

Algorithms consume generated files, not RNGs. Each frozen instance includes the concrete:

- DAG/tasks/dependencies;
- source-workflow checksum/provenance;
- resource pool;
- routed network values;
- execution-time matrix or exact derivation inputs;
- cost and energy parameters;
- reference values;
- deadline/budget values and witness metadata.

## Outcome-independent pilot selection

Before any calibration or competitive result is inspected, enumerate all 2,835 candidate identities and select the committed 200-input pilot with selector version 1 and seed `20260905`. The selection contains 160 development and 40 holdout inputs.

`manifests/pilot-selection-v1.json` records canonical checksums of the parsed configuration, source manifest, and complete candidate universe together with exact marginal and pairwise coverage. It must reproduce byte-for-byte in canonical JSON from those inputs. Scheduler metrics never participate in selection.

The holdout may be materialized and calibrated to create its input deadlines/budgets, but comparative outcomes remain unopened until the proposed mechanism and parameters are frozen.

## Source manifest

The raw source-workflow manifest includes at least:

- upstream repository;
- pinned upstream commit;
- family;
- exact target/actual job count;
- replicate ID;
- acquisition attempt index;
- raw DAX relative path;
- SHA-256 checksum;
- acquisition command/environment metadata;
- structural validation status.

## Dataset manifest

A dataset-version manifest includes at least:

- dataset version;
- schema version;
- generator commit SHA;
- configuration checksum;
- source-manifest checksum;
- instance count and expected dimension counts;
- one entry per instance;
- relative path;
- instance checksum;
- source replicate/checksum;
- resource/scenario/QoS identifiers;
- provenance;
- generation timestamp in UTC outside deterministic content where appropriate;
- validation status.

The preceding selection manifest is separate: it freezes identities and split membership before artifacts exist, and therefore does not fabricate future artifact paths or checksums.

## Determinism verification

Before freeze:

1. start from the same committed source DAX set, configuration, and generator commit;
2. generate the full candidate dataset twice from clean environments;
3. normalize intentionally volatile metadata;
4. compare file checksums;
5. treat any unexplained mismatch as a defect.

The project does **not** require the legacy upstream Bharathi acquisition process to regenerate the same raw DAX bytes. Its committed raw artifacts are the source boundary.

## Exactness rules

Materialized values use committed units and deterministic rounding:

- execution time: integer microseconds;
- compute energy: integer nanojoules;
- network energy: integer picojoules;
- normalized cost/budget: integer nCU;
- rational multipliers represented by integer numerator/denominator.

Binary floating point must not become the authoritative representation for cost/budget or exact reference reconstruction.

## Freeze policy

A version can be tagged/frozen only when:

1. all 105 expected raw source artifacts exist and source validation passes;
2. source checksums/manifests validate;
3. all generated schemas validate;
4. all semantic validators pass;
5. deterministic IFC regeneration is verified;
6. aggregate dimensions match specification;
7. reference schedules validate;
8. deadline/budget calculations and joint witnesses validate;
9. pilot numerical freeze gates pass;
10. configuration, source manifest, and generator commit are recorded.

After freeze, raw source workflows and benchmark instance files are immutable. Corrections require a new dataset version.

## Experiment output separation

Algorithm outputs must not be written into frozen input directories. Experimental results belong in a separate results tree/repository so rerunning experiments cannot mutate benchmark inputs.

## Baseline fairness

Every algorithm run records:

- dataset version;
- instance ID;
- algorithm name/version/commit;
- parameter configuration;
- algorithm RNG seed if stochastic;
- schedule/result checksum where practical.

Algorithm randomness is independent of benchmark realization. Repeated algorithm runs may use multiple algorithm seeds, but every algorithm consumes the exact same frozen benchmark instance for a given `instance_id`.
