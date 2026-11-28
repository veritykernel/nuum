"""Behavior and adversarial limits for the isolated backtest demo."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from nuum.backtest.artifacts import ArtifactWriter
from nuum.backtest.engine import BacktestEngine
from nuum.backtest.scenario import BacktestScenario, MAX_SCENARIO_BYTES
import nuum.backtest.engine as engine_module


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "config" / "backtest" / "sample_scenario_vol_world.json"


def sample_data():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def run_cli(scenario: Path, artifacts_dir: Path, *extra: str):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
    return subprocess.run(
        (sys.executable, "-m", "nuum.backtest.cli_runner", "--scenario", str(scenario),
         "--artifacts-dir", str(artifacts_dir), *extra),
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )


class UnifiedEngineTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nuum-backtest-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_scenario(self, data: dict) -> Path:
        path = self.root / "scenario.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_sample_scenario_runs_without_overwriting_a_prior_run(self):
        artifacts = self.root / "artifacts"
        result = run_cli(SAMPLE, artifacts, "--print-summary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("final_equity", result.stdout)
        out_dir = artifacts / "sample_vol_world_studio1"
        for name in ("equity_curve.json", "trades.json", "summary.json"):
            self.assertTrue((out_dir / name).is_file())
        summary = json.loads((out_dir / "summary.json").read_text())
        self.assertEqual(summary["scenario_id"], "sample_vol_world_studio1")
        self.assertGreater(summary["num_points"], 0)
        digest = hashlib.sha256((out_dir / "summary.json").read_bytes()).hexdigest()
        second = run_cli(SAMPLE, artifacts)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(hashlib.sha256((out_dir / "summary.json").read_bytes()).hexdigest(), digest)

    def test_path_escape_and_symlink_target_are_rejected(self):
        for bad_id in ("../outside", "/tmp/outside", "..", "a/b"):
            data = sample_data()
            data["scenario_id"] = bad_id
            with self.subTest(bad_id=bad_id), self.assertRaises(ValueError):
                BacktestScenario.from_dict(data)
        data = sample_data()
        for bad_root in ("/tmp/outside", "artifacts/../../outside"):
            data["artifacts_dir"] = bad_root
            with self.subTest(bad_root=bad_root), self.assertRaises(ValueError):
                BacktestScenario.from_dict(data)

        scenario = BacktestScenario.from_dict(sample_data())
        result = BacktestEngine(scenario).run()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "summary.json").write_text("must remain")
        artifact_root = self.root / "artifacts"
        artifact_root.mkdir()
        (artifact_root / scenario.scenario_id).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            ArtifactWriter(str(artifact_root), trusted_override=True).write_all(scenario, result)
        self.assertEqual((outside / "summary.json").read_text(), "must remain")

    def test_scenario_artifact_root_rejects_intermediate_symlinks(self):
        data = sample_data()
        data["artifacts_dir"] = "artifacts/redirect"
        scenario_path = self.write_scenario(data)
        sandbox = self.root / "sandbox"
        sandbox.mkdir()
        artifacts = sandbox / "artifacts"
        artifacts.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (artifacts / "redirect").symlink_to(outside, target_is_directory=True)
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}

        def run_in_sandbox():
            return subprocess.run(
                (sys.executable, "-m", "nuum.backtest.cli_runner", "--scenario", str(scenario_path)),
                cwd=sandbox, env=env, capture_output=True, text=True,
            )

        escaped = run_in_sandbox()
        self.assertNotEqual(escaped.returncode, 0)
        self.assertFalse((outside / data["scenario_id"]).exists())

        (artifacts / "redirect").unlink()
        artifacts.rmdir()
        artifacts.symlink_to(outside, target_is_directory=True)
        escaped_root = run_in_sandbox()
        self.assertNotEqual(escaped_root.returncode, 0)
        self.assertFalse((outside / "redirect" / data["scenario_id"]).exists())

        artifacts.unlink()
        artifacts.mkdir()
        valid = run_in_sandbox()
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertTrue((artifacts / "redirect" / data["scenario_id"] / "summary.json").is_file())

    def test_scenario_window_cardinality_and_size_limits(self):
        data = sample_data()
        data["end_ts"] = "2024-02-01T00:00:00Z"
        with self.assertRaises(ValueError):
            BacktestScenario.from_dict(data)
        data = sample_data()
        data["universe"]["symbols"] = [f"SYM{i}" for i in range(17)]
        with self.assertRaises(ValueError):
            BacktestScenario.from_dict(data)
        data = sample_data()
        data["strategies"] = data["strategies"] * 3
        with self.assertRaises(ValueError):
            BacktestScenario.from_dict(data)
        path = self.root / "large.json"
        path.write_bytes(b" " * (MAX_SCENARIO_BYTES + 1))
        with self.assertRaises(ValueError):
            BacktestScenario.load(str(path))

    def test_synthetic_bar_and_trade_limits(self):
        data = sample_data()
        data["end_ts"] = "2024-01-08T00:00:00Z"
        data["universe"]["symbols"] = [f"S{i}" for i in range(16)]
        scenario = BacktestScenario.from_dict(data)
        with self.assertRaisesRegex(ValueError, "bar limit"):
            BacktestEngine(scenario).run()

        scenario = BacktestScenario.from_dict(sample_data())
        with mock.patch.object(engine_module, "MAX_TRADES", 1):
            with self.assertRaisesRegex(ValueError, "trade limit"):
                BacktestEngine(scenario).run()

    def test_state_file_is_explicit_and_bounded(self):
        data = sample_data()
        state = self.root / "state.jsonl"
        state.write_text('{"ts":"2024-01-01T00:00:00Z","symbol":"SPX","price":100}\n')
        data["universe"]["lake1_state_path"] = str(state)
        scenario_path = self.write_scenario(data)
        rejected = run_cli(scenario_path, self.root / "out1")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("--state-path", rejected.stderr)
        accepted = run_cli(scenario_path, self.root / "out2", "--state-path", str(state))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        summary = json.loads((self.root / "out2" / data["scenario_id"] / "summary.json").read_text())
        self.assertEqual(summary["num_points"], 1)

        oversized = self.root / "oversized.jsonl"
        with oversized.open("wb") as output:
            output.truncate(8 * 1024 * 1024 + 1)
        too_large = run_cli(scenario_path, self.root / "out3", "--state-path", str(oversized))
        self.assertNotEqual(too_large.returncode, 0)
        self.assertIn("8 MiB", too_large.stderr)

    def test_extreme_finite_inputs_cannot_emit_nonfinite_artifacts(self):
        data = sample_data()
        data["strategies"] = [{
            "strategy_id": "vol_overflow", "kind": "vol",
            "params": {"vol_target": 0.25, "vol_leverage": 1e308},
        }]
        state = self.root / "finite-state.jsonl"
        state.write_text(
            '{"ts":"2024-01-01T00:00:00Z","symbol":"SPX",'
            '"price":100,"volume":1,"iv":1e308}\n', encoding="utf-8",
        )
        scenario_path = self.write_scenario(data)
        out = self.root / "overflow-artifacts"
        rejected = run_cli(scenario_path, out, "--state-path", str(state))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("not finite", rejected.stderr)
        self.assertFalse((out / data["scenario_id"]).exists())

        scenario = BacktestScenario.from_dict(sample_data())
        result = BacktestEngine(scenario).run()
        result.summary["final_equity"] = float("inf")
        with self.assertRaises(ValueError):
            ArtifactWriter(str(out), trusted_override=True).write_all(scenario, result)
        self.assertFalse((out / scenario.scenario_id).exists())

    def test_diagnostic_labels_reject_controls_and_unbounded_values(self):
        for field in ("lake1_env", "world_model"):
            for bad in ("safe\nForged: pass", "safe\x1b]0;forged\x07", "x" * 65):
                data = sample_data()
                data[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    BacktestScenario.from_dict(data)

    def test_fifo_inputs_fail_before_blocking(self):
        scenario_fifo = self.root / "scenario.fifo"
        state_fifo = self.root / "state.fifo"
        os.mkfifo(scenario_fifo)
        os.mkfifo(state_fifo)
        scenario_rejected = run_cli(scenario_fifo, self.root / "fifo-scenario-artifacts")
        self.assertNotEqual(scenario_rejected.returncode, 0)
        self.assertIn("regular file", scenario_rejected.stderr)

        data = sample_data()
        scenario_path = self.write_scenario(data)
        state_rejected = run_cli(scenario_path, self.root / "fifo-state-artifacts",
                                 "--state-path", str(state_fifo))
        self.assertNotEqual(state_rejected.returncode, 0)
        self.assertIn("regular", state_rejected.stderr)


if __name__ == "__main__":
    unittest.main()
