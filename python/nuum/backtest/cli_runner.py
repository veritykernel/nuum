#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from .scenario import BacktestScenario
from .engine import BacktestEngine
from .artifacts import ArtifactWriter


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="NUUM unified backtest runner (studio1)")
    p.add_argument(
        "--scenario",
        required=True,
        help="Path to scenario JSON spec",
    )
    p.add_argument(
        "--artifacts-dir",
        default=None,
        help="Override artifacts base directory (default from scenario or ./artifacts)",
    )
    p.add_argument(
        "--state-path",
        default=None,
        help="Explicitly authorize a local JSONL state file for this run",
    )
    p.add_argument(
        "--print-summary",
        action="store_true",
        help="Print summary JSON to stdout",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    scenario = BacktestScenario.load(args.scenario)
    if args.artifacts_dir:
        scenario.artifacts_dir = args.artifacts_dir
    if scenario.universe.lake1_state_path and not args.state_path:
        raise ValueError("scenario requests a state file; pass --state-path explicitly")
    scenario.universe.lake1_state_path = args.state_path

    engine = BacktestEngine(scenario)
    result = engine.run()
    writer = ArtifactWriter(scenario.artifacts_dir, trusted_override=bool(args.artifacts_dir))
    paths = writer.write_all(scenario, result)

    if args.print_summary:
        print(json.dumps(result.summary, indent=2, sort_keys=True, allow_nan=False))

    sys.stderr.write(f"Artifacts written under: {paths['summary']}\n")


if __name__ == "__main__":
    main()
