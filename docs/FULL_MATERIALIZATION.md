# Full benchmark materialization

## Scope

`full_materialization_v1` expands the frozen v1-draft candidate universe to all 2,835 QoS inputs without changing the benchmark configuration, source workflows, candidate identifiers, calibration portfolio, deadline arithmetic, budget arithmetic, or pilot selection.

The full grid contains 945 base realizations and exactly three joint QoS profiles per base. The canonical 200-input pilot remains a frozen subset and is reused byte-for-byte.

## Exposure manifest

Before full-grid calibration begins, `materialize-full` writes a deterministic `full_exposure_v1` manifest. Its outcome-independent cohorts are:

- `original_development`: 160 inputs.
- `development_sibling`: 317 additional profiles of exposed development bases.
- `original_holdout`: 40 frozen holdout inputs.
- `holdout_sibling`: 80 other profiles of those holdout bases.
- `expansion_evaluation`: 2,238 profiles of 746 additional bases.

The 2,835 inputs are therefore a descriptive full benchmark, not 2,835 independent unseen samples. Additional profiles of an exposed base remain dependent on that base.

## Materialization command

Run only from a repository revision containing the full-materialization implementation. Do not modify `pilot_selection.selected_count`, and do not use `materialize-pilot` for this release.

```bash
python -m generator.cli materialize-full \
  --config config/benchmark-v1.yaml \
  --source-manifest manifests/source-workflows-v1.json \
  --pilot-selection manifests/pilot-selection-v1.json \
  --pilot-manifest <canonical-pilot-manifest.json> \
  --source-root source_workflows \
  --pilot-root <canonical-pilot-root> \
  --output-root <full-release-root> \
  --exposure-manifest <full-exposure-v1.json> \
  --manifest <full-materialization-v1.json> \
  --generator-commit-sha <40-character-commit-sha> \
  --workers <bounded-worker-count>
```

The worker count must be selected from measured resource usage before the large population run. The command creates one independent work unit per base, uses atomic artifact writes, and stores completion markers under `<full-release-root>/.complete/`. A rerun trusts a completion marker only when every referenced artifact still exists and matches its recorded SHA-256.

For each of the 199 pilot bases, base and calibration files are copied only after their canonical pilot checksums are verified. The original 200 pilot QoS files retain their exact paths and SHA-256 values. Reused artifacts record the pilot generator commit; newly generated artifacts record the actual full-materialization generator commit.

## Validation command

```bash
python -m validation.cli full-materialization \
  --manifest <full-materialization-v1.json> \
  --exposure-manifest <full-exposure-v1.json> \
  --dataset-root <full-release-root> \
  --config config/benchmark-v1.yaml \
  --source-manifest manifests/source-workflows-v1.json \
  --pilot-selection manifests/pilot-selection-v1.json \
  --pilot-manifest <canonical-pilot-manifest.json> \
  --pilot-root <canonical-pilot-root> \
  --source-root source_workflows
```

Full validation requires exactly 2,835 unique QoS identities, 945 unique bases, 945 calibrations, three QoS profiles per base, exact cohort accounting, unchanged pilot artifacts, and correct per-artifact generator provenance. It validates all source checksums, regenerates each base deterministically from its frozen DAX, validates every calibration against its base, reconstructs every QoS input from the frozen calibration arithmetic, and re-evaluates every stored joint-feasibility witness.

A complete release must also record measured run duration, peak memory, retries/failures, raw/compressed sizes, degeneracy counts, deterministic regeneration evidence, and durable release checksums. Manifest counts alone are not completion evidence.

## Information protection

Dataset construction may calibrate and validate protected inputs, but protected calibration schedules, joint witnesses, or comparative scheduler outcomes must not be sent to the algorithm-development track before its algorithm/protocol freeze. Difficulty of a proposed algorithm is not a reason to alter the benchmark inputs.
