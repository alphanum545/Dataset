# Repository guidance

## Purpose
This repository is the canonical benchmark dataset for Intelligent Workflow Scheduling in IoT-Fog-Cloud research. Benchmark design must be fixed before tuning the proposed scheduling algorithm.

## Dataset invariants
- Every baseline and proposed algorithm must consume the same frozen workflow instances, resource descriptions, network conditions, constraints, and reference metadata.
- Raw Pegasus/Bharathi DAX source artifacts are immutable after acquisition and identified by checksum; do not claim an upstream workflow seed controls legacy Bharathi randomness.
- Core v1 size labels are exact actual task counts: `60, 100, 200, 400, 600, 800, 1000`; `allowed_size_deviation = 0`.
- The earlier 50-task common target was retired before dataset freeze because the pinned Bharathi Genome model cannot structurally produce exactly 50 tasks. Do not silently relabel a nearby Genome workflow as 50.
- Bharathi `--numjobs/-n` is an upstream model input, not an exact-output guarantee for every family. For Montage, CyberShake, SIPHT, and LIGO, acquisition uses the configured deterministic request search and accepts only a parsed DAX whose actual task count equals the benchmark target.
- Genome is acquired through the pinned generator's explicit `--lanes/-l` and `--sequences/-s` interface, not `--numjobs`. Core v1 uses one Genome lane and `sequences = target/4 - 1`, which yields exactly `4*sequences + 4 = target` for every configured common size. Manifest entries record `request_mode`, `requested_lanes`, and `requested_sequences`; `requested_numjobs` is null for Genome.
- The default `--numjobs` acquisition policy retries each request twice before increasing it by one. LIGO retries each even request five times and advances by two because odd requests are rejected upstream and valid requests can fail topology construction stochastically.
- There are exactly three frozen source replicates (`r01`, `r02`, `r03`) per family/size, mapped to IFC realization seeds `101`, `202`, `303`.
- Scheduler-visible resources are serial execution slots with `concurrency_slots = 1`.
- Benchmark-owned generation from frozen source DAX, committed configuration, and explicit seeds must be deterministic.
- Deadline/reference and budget calibration must not depend on the proposed novel algorithm.
- Every core v1 joint deadline-budget instance must have a validated stored/reproducible feasibility witness satisfying both constraints.
- Exact normalized cost and budget fields must use integer or exact-decimal arithmetic; binary floating point is not permitted for authoritative cost/budget values.
- Authoritative units are explicit: execution time in microseconds, compute energy in nanojoules, network energy in picojoules, normalized cost/budget in integer nCU.
- Generated data, manifests, schemas, and validation reports must agree on source checksum and instance identifiers/checksums.

## Implementation stack and verification
- Generator runtime: Python 3.11 or newer.
- Install development/test dependencies with `python -m pip install -e '.[test]'`.
- Run the repository test gate with `python -m pytest`.
- Invoke the generator CLI with `python -m generator.cli`.
- Validate the complete frozen source manifest and all referenced DAX checksums with `python -m validation.cli source-manifest --manifest manifests/source-workflows-v1.json --source-root source_workflows`.
- Machine-readable artifact contracts use JSON Schema Draft 2020-12 under `schemas/`; `validation/` adds exact-type and cross-field semantic checks that JSON Schema alone cannot express.
- Run source acquisition with `python -m generator.acquire --config config/benchmark-v1.yaml --upstream-dir <bharathi-dir> --output-root source_workflows --manifest manifests/source-workflows-v1.json`.
- Python package discovery is intentionally limited to `generator*` and `validation*`; repository data/configuration directories are not importable Python packages.
- GitHub Actions runs the install and pytest gates for pull requests and pushes to `main`.
- The source-acquisition workflow compiles the pinned upstream Bharathi generator and smoke-tests exact 60-task acquisition for all five families, every configured Genome target, plus the observed SIPHT-600 and LIGO-1000 boundary cases, on relevant PRs. After acquisition changes reach `main`, it generates all 105 source DAX artifacts and pushes them to a new `generated/source-workflows-v1-<main-sha>` branch for review; it must never overwrite an existing generated branch.

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
- Keep generated source-workflow changes on a review branch until their manifest, counts, and checksums are validated.
- Keep algorithm experiment outputs outside frozen input directories.
- Do not commit credentials, caches, temporary outputs, local environments, or unrelated generated artifacts.
