from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from generator.config import ConfigError, load_config

from .calibration import validate_calibration_result_against_instance
from .errors import BenchmarkValidationError
from .materialization import validate_pilot_materialization_manifest
from .pilot import validate_pilot_selection
from .semantic import validate_source_manifest


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
    materialization = subparsers.add_parser(
        "pilot-materialization",
        description=(
            "Validate the frozen 200-input pilot manifest and every referenced base, "
            "calibration, QoS, and joint-witness artifact"
        ),
    )
    materialization.add_argument("--manifest", type=Path, required=True)
    materialization.add_argument("--dataset-root", type=Path, required=True)
    materialization.add_argument("--config", type=Path, required=True)
    materialization.add_argument("--source-manifest", type=Path, required=True)
    materialization.add_argument("--pilot-selection", type=Path, required=True)
    materialization.add_argument("--source-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "calibration-result":
            result = json.loads(args.result.read_text(encoding="utf-8"))
            base_instance = json.loads(
                args.base_instance.read_text(encoding="utf-8")
            )
            candidate_count = validate_calibration_result_against_instance(
                result, base_instance
            )
            output = {
                "base_instance_id": result["base_instance_id"],
                "candidate_count": candidate_count,
                "result": str(args.result),
                "status": "passed",
            }
        elif args.command == "pilot-materialization":
            config = load_config(args.config)
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            source_manifest = json.loads(
                args.source_manifest.read_text(encoding="utf-8")
            )
            selection_manifest = json.loads(
                args.pilot_selection.read_text(encoding="utf-8")
            )
            validate_pilot_materialization_manifest(
                manifest,
                config=config,
                source_manifest=source_manifest,
                selection_manifest=selection_manifest,
                dataset_root=args.dataset_root,
                source_root=args.source_root,
            )
            output = {
                "base_instance_count": manifest["base_instance_count"],
                "calibration_count": manifest["calibration_count"],
                "instance_count": manifest["instance_count"],
                "manifest": str(args.manifest),
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
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ConfigError,
        BenchmarkValidationError,
        ValueError,
    ) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
