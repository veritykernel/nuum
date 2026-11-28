# NUUM Unified Backtest Engine (studio1, volatility world-model)

This module provides a single backtesting engine capable of replaying UW, gamma, and vol strategies
off lake1 state and emitting standardized performance artifacts.

## Layout

- `python/nuum/backtest/`
  - `scenario.py` – scenario specification (universe, strategies, risk, fees, world-model).
  - `data_adapter.py` – simplified lake1 data adapter (synthetic or file-based).
  - `strategies.py` – UW, gamma, and vol strategy adapters.
  - `engine.py` – unified backtest engine and result model.
  - `artifacts.py` – artifact writer (equity curve, trades, summary, diagnostics).
  - `cli_runner.py` – Python CLI entrypoint.

- `cli/backtest/`
  - `nuum_backtest_run.sh` – shell wrapper for the Python CLI.
  - `nuum_backtest_smoke.sh` – smoke test runner using the sample scenario.

- `config/backtest/sample_scenario_vol_world.json` – example scenario spec.

- `tests/backtest/test_unified_engine.py` – basic end-to-end test.

## Usage

From the repo root:

```bash
cli/backtest/nuum_backtest_run.sh --scenario config/backtest/sample_scenario_vol_world.json --artifacts-dir /trusted/output
```

Scenario IDs are one safe path component. Scenario files are limited to 256 KiB, seven days, 16 symbols, and eight strategies. A run accepts at most 20,000 bars and 50,000 trades; a JSONL state file is limited to 8 MiB, 16 KiB per line, and 20,000 records. An explicit state file requires `--state-path FILE`; a path embedded in scenario JSON alone does not authorize reading it.

Scenario and state inputs must be regular files; FIFOs and symlinks are rejected before reading. Diagnostic `lake1_env` and `world_model` labels must be short safe components. Nonfinite arithmetic or JSON values fail the run before artifact creation, and artifact JSON serialization rejects `NaN` and `Infinity`.

Scenario-selected artifact roots stay under the current directory's `artifacts/` tree. Every component is opened without following symlinks, so an intermediate redirect cannot move writes outside that tree. An explicit `--artifacts-dir` is a separate trusted operator choice; its selected destination is canonicalized before opening. Artifact runs create a fresh private scenario directory and refuse to overwrite an existing one. Choose a new output root or remove a prior run under its data-retention authority. These demo backtests are not live trading or market-data acceptance.
