# Repository guidance

## Purpose
This repository is the canonical benchmark dataset for Intelligent Workflow Scheduling in IoT-Fog-Cloud research. Benchmark design must be fixed before tuning the proposed scheduling algorithm.

## Dataset invariants
- Every baseline and proposed algorithm must consume the same frozen workflow instances, resource descriptions, network conditions, constraints, and reference metadata.
- Generation must be deterministic from committed configuration and explicit random seeds.
- Raw workflow structure and provenance must remain traceable; generated benchmark instances must not silently mutate after a dataset version is frozen.
- Deadline/reference and budget calibration must not depend on the proposed novel algorithm.
- Every core v1 joint deadline-budget instance must have a validated stored/reproducible feasibility witness satisfying both constraints.
- Exact normalized cost and budget fields must use integer or exact-decimal arithmetic; binary floating point is not permitted for materialized cost/budget values.
- Generated data, manifests, schemas, and validation reports must agree on instance identifiers and checksums.

## Planned structure
- `docs/` - benchmark specification and methodology.
- `config/` - committed generation/scenario configuration.
- `generator/` - deterministic dataset generator and calibration utilities.
- `schemas/` - machine-readable dataset schemas.
- `validation/` - structural and semantic validators.
- `datasets/` - generated frozen benchmark instances.
- `manifests/` - instance indexes, provenance, checksums, and version metadata.
- `tests/` - generator and validator tests.

## Workflow
1. Specify and review the benchmark.
2. Implement deterministic generation, calibration, and validation.
3. Generate pilot instances and validate distributions/trade-offs.
4. Resolve only pre-declared candidate parameters when evidence shows a benchmark-design problem.
5. Generate candidate instances and validate deterministic regeneration.
6. Freeze a version before running/tuning the proposed algorithm.

## Change discipline
- Do not alter frozen dataset files in place; create a new dataset version when benchmark semantics change.
- Do not commit credentials, caches, temporary outputs, or untracked experimental artifacts.
