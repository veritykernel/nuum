#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Dict, Any

from .engine import BacktestResult
from .scenario import BacktestScenario, safe_component


class ArtifactWriter:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def write_all(self, scenario: BacktestScenario, result: BacktestResult) -> Dict[str, str]:
        scenario_id = safe_component(scenario.scenario_id, "scenario_id")
        base = self.base_dir.resolve()
        base.mkdir(parents=True, exist_ok=True)
        base_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            # Reject an existing directory or symlink rather than truncating a prior run.
            os.mkdir(scenario_id, mode=0o700, dir_fd=base_fd)
            out_fd = os.open(
                scenario_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd
            )
            try:
                def write_json(name: str, value: Any) -> None:
                    with os.fdopen(
                        os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                0o600, dir_fd=out_fd),
                        "w", encoding="utf-8",
                    ) as output:
                        json.dump(value, output, indent=2, sort_keys=True)

                write_json("scenario.json", scenario.to_dict())
                write_json("equity_curve.json", result.equity_curve)
                write_json("trades.json", result.trades)
                write_json("summary.json", result.summary)
                with os.fdopen(
                    os.open("diagnostics.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=out_fd),
                    "w", encoding="utf-8",
                ) as output:
                    output.write("NUUM Unified Backtest Diagnostics\n")
                    output.write(f"Scenario: {scenario_id}\n")
                    output.write(f"World model: {scenario.world_model}\n")
                    output.write(f"Lake1 env: {scenario.lake1_env}\n")
                    output.write(f"Universe: {scenario.universe.universe_id}\n")
                    output.write(f"Symbols: {', '.join(scenario.universe.symbols)}\n")
                    output.write(f"Strategies: {[s.strategy_id for s in scenario.strategies]}\n")
                    output.write(f"Summary: {json.dumps(result.summary, sort_keys=True)}\n")
            finally:
                os.close(out_fd)
        finally:
            os.close(base_fd)

        out_dir = base / scenario_id
        return {key: str(out_dir / filename) for key, filename in (
            ("scenario", "scenario.json"), ("equity_curve", "equity_curve.json"),
            ("trades", "trades.json"), ("summary", "summary.json"),
            ("diagnostics", "diagnostics.txt"),
        )}
