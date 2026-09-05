from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from generator.config import ConfigError, load_config

from .errors import BenchmarkValidationError
from .semantic import validate_pilot_selection, validate_source_manifest


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
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
    except (OSError, json.JSONDecodeError, ConfigError, BenchmarkValidationError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                count_key: manifest[count_key],
                "manifest": str(args.manifest),
                "status": "passed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
