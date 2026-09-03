# Repository guidance

## Purpose
This repository is the canonical benchmark dataset for Intelligent Workflow Scheduling in IoT-Fog-Cloud research. Benchmark design must be fixed before tuning the proposed scheduling algorithm.

## Dataset invariants
- Every baseline and proposed algorithm must consume the same frozen workflow instances, resource descriptions, network conditions, constraints, and reference metadata.
- Raw Pegasus/Bharathi DAX source artifacts are immutable after acquisition and identified by checksum; do not claim an upstream workflow seed controls legacy Bharathi randomness.
- Core v1 size labels are exact actual task counts; `allowed_size_deviation = 0`.
- There are exactly three frozen source replicates (`r01`, `r02`, `r03`) per family/size, mapped to IFC realization seeds `101`, `202`, `303`.
- Scheduler-visible resources are serial execution slots with `concurrency_slots = 1`.
- Benchmark-owned generation from frozen source DAX, committed configuration, and explicit seeds must be deterministic.
- Deadline/reference and budget calibration must not depend on the proposed novel algorithm.
- Every core v1 joint deadline-budget instance must have a validated stored/reproducible feasibility witness satisfying both constraints.
- Exact normalized cost and budget fields must use integer or exact-decimal arithmetic; binary floating point is not permitted for authoritative cost/budget values.
- Authoritative units are explicit: execution time in microseconds, compute energy in nanojoules, network energy in picojoules, normalized cost/budget in integer nCU.
- Generated data, manifests, schemas, and validation reports must agree on source checksum and instance identifiers/checksums.

## Planned structure
- `docs/` - benchmark specification and methodology.
- `config/` - committed generation/scenario configuration.
- `source_workflows/` - immutable raw DAX source artifacts and source manifest.
- `generator/` - deterministic IFC normalizer, generator, and calibration utilities.
- `schemas/` - machine-readable schemas.
- `validation/` - source, structural, semantic, reference, and freeze validators.
- `datasets/` - generated candidate/frozen benchmark instances.
- `manifests/` - source and instance indexes, provenance, checksums, and version metadata.
- `tests/` - generator/calibration/validator tests and small non-benchmark fixtures.

## Workflow
1. Specify and review benchmark semantics.
2. Implement deterministic source validation, normalization, resource/network generation, calibration, schemas, and tests.
3. Acquire and freeze source DAX files using only predeclared structural acceptance criteria.
4. Generate pilot instances and validate distributions/trade-offs/sensitivity.
5. Resolve only predeclared pilot parameters when evidence shows a benchmark-design problem.
6. Generate candidate instances and verify deterministic regeneration.
7. Freeze a version before running/tuning the proposed algorithm.

## Change discipline
- Do not alter frozen source DAX or dataset files in place; create a new dataset version when benchmark semantics change.
- Do not select source workflows based on scheduler performance or downstream objectives.
- Keep algorithm experiment outputs outside frozen input directories.
- Do not commit credentials, caches, temporary outputs, local environments, or unrelated generated artifacts.
