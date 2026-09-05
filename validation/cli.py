from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Sequence

from generator.canonical import canonical_json_bytes
from generator.config import ConfigError, load_config
from generator.reference_schedulers import (
    CALIBRATION_VERSION,
    REFERENCE_SCHEDULER_VERSION,
    calibration_lower_bounds,
)

from .calibration import validate_calibration_result
from .errors import BenchmarkValidationError
from .semantic import (
    validate_base_instance,
    validate_pilot_selection,
    validate_schedule,
    validate_source_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate IFC benchmark artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    source = subparsers.add_parser(
        "source-manifest", description="Validate source-manifest structure, provenance, and files"
    )
    source.add_argument("--manifest", type=Path, required=True)
    source.add_argument("--source-root", type=Path, required=True)
    source.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Allow a structurally valid subset instead of requiring the complete "
            "105-artifact grid"
        ),
    )
    pilot = subparsers.add_parser(
        "pilot-selection",
        description="Validate and exactly reproduce a frozen pilot selection",
    )
    pilot.add_argument("--manifest", type=Path, required=True)
    pilot.add_argument("--config", type=Path, required=True)
    pilot.add_argument("--source-manifest", type=Path, required=True)
    calibration = subparsers.add_parser(
        "calibration-result",
        description="Validate a calibration artifact against its authoritative base IFC instance",
    )
    calibration.add_argument("--result", type=Path, required=True)
    calibration.add_argument("--base-instance", type=Path, required=True)
    return parser


def _validate_calibration_files(result_path: Path, base_instance_path: Path) -> tuple[dict, int]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    base_instance = json.loads(base_instance_path.read_text(encoding="utf-8"))
    validate_base_instance(base_instance)
    validate_calibration_result(result)
    if result["base_instance_id"] != base_instance["metadata"]["base_instance_id"]:
        raise BenchmarkValidationError(
            "calibration base_instance_id does not match the supplied base instance"
        )

    if result["calibration_version"] != CALIBRATION_VERSION:
        raise BenchmarkValidationError("calibration_version is not the frozen v1 version")
    versions = [
        reference["scheduler_version"] for reference in result["reference_schedulers"]
    ]
    versions.append(result["moheft"]["scheduler_version"])
    if any(version != REFERENCE_SCHEDULER_VERSION for version in versions):
        raise BenchmarkValidationError("calibration scheduler version is not the frozen v1 version")
    if result["lower_bounds"] != calibration_lower_bounds(base_instance):
        raise BenchmarkValidationError(
            "calibration lower bounds do not reconstruct from the supplied base instance"
        )

    candidate_payload = {
        "reference_schedulers": result["reference_schedulers"],
        "moheft": result["moheft"],
    }
    expected_checksum = sha256(canonical_json_bytes(candidate_payload)).hexdigest()
    if result["candidate_set_sha256"] != expected_checksum:
        raise BenchmarkValidationError(
            "candidate_set_sha256 does not match the canonical calibration candidate set"
        )

    schedules = [
        *(reference["schedule"] for reference in result["reference_schedulers"]),
        *result["moheft"]["candidate_schedules"],
    ]
    for schedule in schedules:
        validate_schedule(base_instance, schedule)
    return result, len(schedules)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "calibration-result":
            result, candidate_count = _validate_calibration_files(
                args.result, args.base_instance
            )
            output = {
                "base_instance_id": result["base_instance_id"],
                "candidate_count": candidate_count,
                "result": str(args.result),
                "status": "passed",
            }
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.command == "source-manifest":
                validate_source_manifest(
                    manifest,
                    source_root=args.source_root,
                    require_complete=not args.allow_partial,
                )
                count_key = "artifact_count"
            else:
                config = load_config(args.config)
                source_manifest = json.loads(
                    args.source_manifest.read_text(encoding="utf-8")
                )
                validate_pilot_selection(
                    manifest,
                    config=config,
                    source_manifest=source_manifest,
                )
                count_key = "selected_count"
            output = {
                count_key: manifest[count_key],
                "manifest": str(args.manifest),
                "status": "passed",
            }
    except (OSError, json.JSONDecodeError, ConfigError, BenchmarkValidationError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
