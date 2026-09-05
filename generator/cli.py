from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .dax import normalize_dax
from .instance import build_base_instance
from .pilot import build_pilot_selection_manifest
from .reference_schedulers import build_calibration_result


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ifc-dataset")
    sub = parser.add_subparsers(dest="command", required=True)

    normalize = sub.add_parser("normalize-dax", help="Normalize one frozen source DAX")
    normalize.add_argument("--config", required=True)
    normalize.add_argument("--dax", required=True)
    normalize.add_argument("--family", required=True)
    normalize.add_argument("--task-count", required=True, type=int)
    normalize.add_argument("--replicate", required=True)
    normalize.add_argument("--output", required=True)

    build = sub.add_parser("build-base-instance", help="Build one pre-QoS IFC instance")
    build.add_argument("--config", required=True)
    build.add_argument("--normalized-workflow", required=True)
    build.add_argument("--scale", required=True)
    build.add_argument("--scenario", required=True)
    build.add_argument("--seed", required=True, type=int)
    build.add_argument("--output", required=True)

    pilot = sub.add_parser(
        "select-pilot",
        help="Freeze the outcome-independent stratified 200-instance pilot selection",
    )
    pilot.add_argument("--config", required=True)
    pilot.add_argument("--source-manifest", required=True)
    pilot.add_argument("--output", required=True)

    calibration = sub.add_parser(
        "calibrate-instance",
        help="Run the frozen deterministic IFC calibration portfolio on one base instance",
    )
    calibration.add_argument("--config", required=True)
    calibration.add_argument("--base-instance", required=True)
    calibration.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    if args.command == "select-pilot":
        source_manifest = json.loads(
            Path(args.source_manifest).read_text(encoding="utf-8")
        )
        manifest = build_pilot_selection_manifest(config, source_manifest)
        _write_json(Path(args.output), manifest)
        return 0

    if args.command == "normalize-dax":
        workflow = normalize_dax(
            Path(args.dax),
            family=args.family,
            target_task_count=args.task_count,
            replicate_id=args.replicate,
            reference_mips=int(config["workflows"]["reference_mips"]),
        )
        _write_json(Path(args.output), workflow)
        return 0

    if args.command == "calibrate-instance":
        instance = json.loads(Path(args.base_instance).read_text(encoding="utf-8"))
        k = int(config["budget"]["calibration"]["tradeoff_solutions"])
        result = build_calibration_result(instance, k=k)
        _write_json(Path(args.output), result)
        return 0

    workflow = json.loads(Path(args.normalized_workflow).read_text(encoding="utf-8"))
    instance = build_base_instance(
        workflow,
        config,
        scale=args.scale,
        scenario=args.scenario,
        seed=args.seed,
    )
    _write_json(Path(args.output), instance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
