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
- Base IFC artifacts store compact authoritative communication inputs, not the redundant dependency-by-resource-pair matrix. Communication time and energy for a concrete placement must be derived from dependency `data_bits`, resource tiers, and the stored network through `generator.network.resource_route_metrics`.
- Same-resource communication remains exactly zero; same-tier-different-resource and cross-tier communication must use the frozen route definitions and exact integer formulas. The compact representation is a storage representation change, not a scheduling-model change.
- Benchmark-owned generation from frozen source DAX, committed configuration, and explicit seeds must be deterministic.
- Deadline/reference and budget calibration must not depend on the proposed novel algorithm.
- The pilot selector enumerates all 2,835 candidate identities without materializing them, then selects exactly 200 inputs using `deterministic-stratified-pairwise` selector version 2 and seed `20260905`; scheduler outcomes must never influence selection.
- Selector v2 preserves the predeclared marginal quotas and complete pairwise coverage while enforcing holdout base isolation. Its 40 holdout entries must represent 40 distinct base realizations, and no holdout base realization may appear in development under another QoS profile.
- A base realization is identified by workflow family, task count, source replicate, resource scale, scenario profile, and the replicate-derived IFC seed; `qos_profile` is not part of base isolation.
- Selector v2 replaced selector v1 before any comparative holdout outcome was generated or opened. The correction was triggered only by an identity-level preflight that found 10 base realizations shared across the old development and holdout splits; do not reintroduce that leakage.
- The pilot split is exactly 160 development and 40 holdout inputs. Development may contain multiple QoS entries for the same development-only base, but holdout bases remain unique and disjoint. Holdout comparative outcomes remain unopened until the proposed mechanism and parameters are frozen.
- `validation.pilot.validate_pilot_selection` must recompute base-isolation counts from entries; do not trust manifest `base_isolation` metadata alone.
- Pilot materialization must preserve each frozen `candidate_id` as the QoS `instance_id`; it may not add, drop, rename, or reassign selected candidates or their development/holdout split.
- Selected QoS entries sharing the same workflow/resource/scenario/seed realization share one `base_instance_id`; generate that base and calibration once and reuse them for the associated QoS profiles.
- The pilot materialization manifest is the provenance index for all base, calibration, and QoS artifacts and must record the frozen selection/config/source checksums, generator commit SHA, split counts, artifact paths/checksums, and its own content checksum.
- V1 deadlines use exact interpolation between best-known feasible fast and economical IFC calibration anchors (`1/10`, `1/2`, `9/10`), not a multiplier of HEFT makespan.
- The frozen calibration portfolio is `deterministic_heft_ifc`, `deterministic_peft_ifc`, `deterministic_cpop_ifc`, `deterministic_cost_reference_ifc`, plus `deterministic_moheft` with `K = 50`; the implementation version is `ifc_v1`.
- Reference schedulers may choose task priority and resource mapping only. Final timing, contention, communication, cost, energy, identity, and feasibility must be produced/rechecked by `generator.schedule`.
- HEFT/CPOP rank communication averages use all ordered distinct-resource pairs; PEFT OCT uses the actual derived source/target IFC route; deterministic ties are frozen in `docs/REFERENCE_SCHEDULERS.md` and must not drift silently.
- MOHEFT primary objectives are makespan and exact compute cost. Its nondominated ranking and crowding calculations must remain deterministic and must not use binary floating point.
- Distinct reference scheduler IDs may legitimately produce the same canonical schedule; do not reject reference convergence. Stored MOHEFT candidates must be unique and must not duplicate an explicit reference output.
- Every core v1 joint deadline-budget instance must have a validated stored/reproducible feasibility witness satisfying both constraints.
- The deadline-conditioned cost-floor witness is selected by exact compute cost, then makespan, then lexicographic complete task-to-resource mapping, then schedule ID; do not change this tie order silently.
- Exact normalized cost and budget fields must use integer or exact-decimal arithmetic; binary floating point is not permitted for authoritative cost/budget values.
- Authoritative units are explicit: execution time in microseconds, compute energy in nanojoules, network energy in picojoules, normalized cost/budget in integer nCU.
- Generated data, manifests, schemas, and validation reports must agree on source checksum and instance identifiers/checksums.
- Do not commit the full generated pilot payload to permanent storage until the complete 200-input materialization/validation gate reports the observed raw and compressed payload sizes and the storage choice is explicitly recorded.

## Implementation stack and verification
- Generator runtime: Python 3.11 or newer.
- Install development/test dependencies with `python -m pip install -e '.[test]'`.
- Run the repository test gate with `python -m pytest`.
- Generate the frozen pilot selection with `python -m generator.cli select-pilot --config config/benchmark-v1.yaml --source-manifest manifests/source-workflows-v1.json --output manifests/pilot-selection-v1.json`.
- Reproduce and validate it with `python -m validation.cli pilot-selection --manifest manifests/pilot-selection-v1.json --config config/benchmark-v1.yaml --source-manifest manifests/source-workflows-v1.json`.
- Run one frozen calibration with `python -m generator.cli calibrate-instance --config config/benchmark-v1.yaml --base-instance <base-instance.json> --output <calibration-result.json>`.
- Validate calibration schedules against the exact base instance with `python -m validation.cli calibration-result --result <calibration-result.json> --base-instance <base-instance.json>`.
- Materialize the exact selected pilot with `python -m generator.cli materialize-pilot --config config/benchmark-v1.yaml --source-manifest manifests/source-workflows-v1.json --pilot-selection manifests/pilot-selection-v1.json --source-root source_workflows --output-root <pilot-root> --manifest <pilot-manifest.json> --generator-commit-sha <40-char-sha>`.
- Fully validate the materialized pilot with `python -m validation.cli pilot-materialization --manifest <pilot-manifest.json> --dataset-root <pilot-root> --config config/benchmark-v1.yaml --source-manifest manifests/source-workflows-v1.json --pilot-selection manifests/pilot-selection-v1.json --source-root source_workflows`.
- Invoke the generator CLI with `python -m generator.cli`.
- Validate the complete frozen source manifest and all referenced DAX checksums with `python -m validation.cli source-manifest --manifest manifests/source-workflows-v1.json --source-root source_workflows`.
- Machine-readable artifact contracts use JSON Schema Draft 2020-12 under `schemas/`; `validation/` adds exact-type and cross-field semantic checks that JSON Schema alone cannot express.
- `generator.network.resource_route_metrics` is the single placement-level derivation boundary for compact IFC communication. Do not reintroduce a stored `E × R²` communication matrix or duplicate route arithmetic inside schedulers.
- `generator.schedule` is the authoritative v1 scheduling boundary: algorithms provide a complete topological task order and task-to-resource mapping to `build_schedule`, while imported/explicit schedules must pass `validation.validate_schedule` against their base instance. Task intervals are half-open, resources are serial, insertion into safe idle gaps is allowed, and all totals/feasibility/identity fields are recomputed with exact integers.
- `generator.reference_schedulers` owns the frozen HEFT-IFC, PEFT-IFC, CPOP-IFC, economical-reference, MOHEFT, calibration-anchor, candidate-checksum, and diagnostic lower-bound implementation. Keep algorithm-specific policy out of `generator.schedule`.
- `generator.materialize` owns selected-pilot grouping, exact deadline/budget construction, joint-witness selection, staged writes, and the pilot materialization manifest. `validation.materialization` owns cross-artifact reproduction and witness verification.
- Run source acquisition with `python -m generator.acquire --config config/benchmark-v1.yaml --upstream-dir <bharathi-dir> --output-root source_workflows --manifest manifests/source-workflows-v1.json`.
- Python package discovery is intentionally limited to `generator*` and `validation*`; repository data/configuration directories are not importable Python packages.
- GitHub Actions runs the install and pytest gates for pull requests and pushes to `main`.
- The `pilot-selection-regeneration` workflow deterministically regenerates selector-v2 `manifests/pilot-selection-v1.json`, validates base isolation, runs focused selector tests, and commits the regenerated manifest when required.
- The `pilot-materialization` workflow measures a real 1000-task/S03 base and calibration artifact; the compact representation reduced that base from 363,028,528 raw bytes to 3,630,983 raw bytes and peak base-build RSS from 2,195,180 kB to 43,732 kB.
- The `full-pilot-materialization` workflow first rejects any development/holdout base overlap, then generates and fully validates all 200 selected inputs, reports complete payload sizing/degeneracy, and uploads a short-retention review artifact. Superseded PR runs are cancelled by concurrency guards.
- The source-acquisition workflow compiles the pinned upstream Bharathi generator and smoke-tests exact 60-task acquisition for all five families, every configured Genome target, plus the observed SIPHT-600 and LIGO-1000 boundary cases, on relevant PRs. After acquisition changes reach `main`, it generates all 105 source DAX artifacts and pushes them to a new `generated/source-workflows-v1-<main-sha>` branch for review; it must never overwrite an existing generated branch.

## Planned structure
- `docs/` - benchmark specification and methodology.
- `config/` - committed generation/scenario configuration.
- `source_workflows/` - immutable raw DAX source artifacts and source manifest.
- `generator/` - deterministic IFC normalizer, generator, calibration, and pilot materialization utilities.
- `schemas/` - machine-readable schemas.
- `validation/` - source, structural, semantic, reference, materialization, and freeze validators.
- `datasets/` - generated candidate/frozen benchmark instances.
- `manifests/` - source, selection, materialization, and instance provenance/checksums.
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
