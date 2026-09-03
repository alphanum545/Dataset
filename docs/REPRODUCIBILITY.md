# Reproducibility and Freeze Policy — v1 Draft

## Principle

A benchmark result is meaningful only if another implementation can reconstruct the same scheduling input. Every source of randomness must therefore be explicit, versioned, and materialized into the frozen dataset.

## Seed separation

Use independent deterministic seeds for logically different stochastic processes:

- `workflow_seed` — workflow/topology generation where the source generator supports randomness;
- `resource_seed` — heterogeneous resource parameter realization;
- `network_seed` — network realization when parameters are sampled rather than fixed by profile;
- `constraint_seed` — reserved for future stochastic constraint generation.

Do not reuse one global RNG stream for all components. Adding a new random draw in one component must not silently change unrelated benchmark dimensions.

## Candidate v1 seed set

For the first candidate generation pass, use three replications:

- 101
- 202
- 303

These are intentionally simple stable identifiers. They remain candidate values until the resource parameter distributions and workflow generator behaviour are validated.

## Stable instance identity

An instance ID must encode or deterministically derive from:

- dataset version;
- workflow family;
- requested workflow size;
- actual task count;
- resource scale;
- scenario profile;
- replication/seed ID;
- deadline level;
- budget level when enabled.

Human-readable fields should be present in the manifest even if the final ID also contains a hash.

## Materialization rule

Algorithms consume generated files, not generator RNGs. Each frozen instance must include the concrete:

- DAG/tasks/dependencies;
- resource pool;
- network matrix;
- execution-time matrix or all data needed to deterministically derive it;
- cost and energy parameters;
- reference values;
- deadline/budget values.

## Manifest

A version manifest must include at least:

- dataset version;
- schema version;
- generator commit SHA;
- configuration checksum;
- instance count;
- expected dimension counts;
- one entry per instance;
- relative instance path;
- instance checksum;
- provenance;
- generation timestamp in UTC;
- validation status.

## Determinism verification

Before freeze, generate the same candidate dataset twice from a clean environment and compare normalized file checksums. Any mismatch must be explained or treated as a defect.

Generated timestamps must not be included in content checksums if they prevent byte-for-byte reproducibility; place volatile provenance in the manifest or normalize it consistently.

## Freeze policy

A version can be tagged/frozen only when:

1. all schemas validate;
2. all semantic validators pass;
3. deterministic regeneration is verified;
4. aggregate dimension counts match the specification;
5. reference schedules validate;
6. constraint calculations validate;
7. checksums are generated;
8. the configuration and generator commit are recorded.

After freeze, benchmark input files are immutable. Corrections require a new dataset version and a changelog describing whether results from the old and new versions are comparable.

## Experiment output separation

Algorithm outputs must not be written into frozen input directories. Experimental results should live in a separate repository/directory or a clearly separate results tree so rerunning experiments cannot mutate the benchmark.

## Baseline fairness

Every algorithm run must record:

- dataset version;
- instance ID;
- algorithm name/version/commit;
- parameter configuration;
- random seed used by the algorithm itself, if stochastic;
- schedule/result checksum where practical.

Algorithm randomness is independent of dataset randomness. Repeated algorithm runs may use multiple algorithm seeds, but all runs still consume the exact same frozen benchmark instance.
