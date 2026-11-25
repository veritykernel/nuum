#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Dict, Any

from .engine import BacktestResult
from .scenario import BacktestScenario, safe_component


class ArtifactWriter:
    def __init__(self, base_dir: str, *, trusted_override: bool = False):
        self.base_dir = Path(base_dir)
        self.trusted_override = trusted_override

    @staticmethod
    def _open_components(root: Path, parts: tuple[str, ...]) -> int:
        """Create and open each directory relative to its parent fd, rejecting links."""
        current_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                if part in {"", ".", ".."}:
                    raise ValueError("artifact path contains an unsafe component")
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current_fd,
                )
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    def _open_base(self) -> tuple[int, Path]:
        if self.trusted_override:
            # The explicit CLI root is operator selected. Canonicalize that choice,
            # then reject links introduced while opening its components.
            chosen = self.base_dir.expanduser()
            if not chosen.is_absolute():
                chosen = Path.cwd() / chosen
            base = chosen.resolve(strict=False)
            return self._open_components(Path(base.anchor), base.parts[1:]), base

        # Scenario-selected roots stay inside the physical working directory.
        # Never resolve a scenario component before opening it without following links.
        parts = self.base_dir.parts
        if self.base_dir.is_absolute() or not parts or parts[0] != "artifacts":
            raise ValueError("scenario artifact root must be under relative artifacts/")
        for part in parts:
            safe_component(part, "artifacts_dir")
        anchor = Path.cwd().resolve(strict=True)
        return self._open_components(Path("."), parts), anchor.joinpath(*parts)

    def write_all(self, scenario: BacktestScenario, result: BacktestResult) -> Dict[str, str]:
        scenario_id = safe_component(scenario.scenario_id, "scenario_id")
        base_fd, base = self._open_base()
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
