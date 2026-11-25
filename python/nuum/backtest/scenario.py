#!/usr/bin/env python3
import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
from pathlib import Path
import re
from typing import Dict, List, Optional, Any

MAX_SCENARIO_BYTES = 256 * 1024
MAX_DURATION = timedelta(days=7)
MAX_SYMBOLS = 16
MAX_STRATEGIES = 8
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or value in {".", ".."} or not SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"{label} must be a safe path component of at most 64 characters")
    return value


def finite_nonnegative(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return number


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class UniverseSpec:
    universe_id: str
    symbols: List[str]
    lake1_snapshot_ts: Optional[str] = None
    lake1_state_path: Optional[str] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "UniverseSpec":
        symbols = data.get("symbols", [])
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= MAX_SYMBOLS:
            raise ValueError(f"symbols must contain 1 to {MAX_SYMBOLS} entries")
        if any(not isinstance(symbol, str) or not 1 <= len(symbol) <= 32 or
               not symbol.isprintable() for symbol in symbols):
            raise ValueError("symbols must be short printable strings")
        if len(set(symbols)) != len(symbols):
            raise ValueError("symbols must be unique")
        return UniverseSpec(
            universe_id=safe_component(data["universe_id"], "universe_id"),
            symbols=symbols,
            lake1_snapshot_ts=data.get("lake1_snapshot_ts"),
            lake1_state_path=data.get("lake1_state_path"),
        )


@dataclass
class StrategySpec:
    strategy_id: str
    kind: str  # "uw", "gamma", "vol"
    params: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "StrategySpec":
        params = data.get("params", {})
        if not isinstance(params, dict) or len(params) > 32:
            raise ValueError("strategy params must be a small mapping")
        if any(not isinstance(key, str) or len(key) > 64 or isinstance(value, bool) or
               not isinstance(value, (int, float)) or not math.isfinite(float(value))
               for key, value in params.items()):
            raise ValueError("strategy params must contain finite numeric values")
        if data["kind"].lower() not in {"uw", "gamma", "vol"}:
            raise ValueError("unsupported strategy kind")
        return StrategySpec(
            strategy_id=safe_component(data["strategy_id"], "strategy_id"),
            kind=data["kind"],
            params=params,
        )


@dataclass
class RiskSpec:
    max_gross_notional: float
    max_leverage: float
    max_drawdown: float
    other_limits: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "RiskSpec":
        return RiskSpec(
            max_gross_notional=finite_nonnegative(data["max_gross_notional"], "max_gross_notional"),
            max_leverage=finite_nonnegative(data["max_leverage"], "max_leverage"),
            max_drawdown=finite_nonnegative(data["max_drawdown"], "max_drawdown"),
            other_limits=dict(data.get("other_limits", {})),
        )


@dataclass
class FeeSpec:
    commission_per_contract: float
    slippage_bps: float
    borrow_cost_bps: float
    other_fees: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FeeSpec":
        return FeeSpec(
            commission_per_contract=finite_nonnegative(data["commission_per_contract"], "commission_per_contract"),
            slippage_bps=finite_nonnegative(data["slippage_bps"], "slippage_bps"),
            borrow_cost_bps=finite_nonnegative(data["borrow_cost_bps"], "borrow_cost_bps"),
            other_fees=dict(data.get("other_fees", {})),
        )


@dataclass
class BacktestScenario:
    scenario_id: str
    description: str
    start_ts: datetime
    end_ts: datetime
    universe: UniverseSpec
    strategies: List[StrategySpec]
    risk: RiskSpec
    fees: FeeSpec
    lake1_env: str = "studio1"
    world_model: str = "volatility"
    artifacts_dir: str = "artifacts"

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "BacktestScenario":
        scenario_id = safe_component(data["scenario_id"], "scenario_id")
        start_ts = _parse_dt(data["start_ts"])
        end_ts = _parse_dt(data["end_ts"])
        if (start_ts.utcoffset() is None or end_ts.utcoffset() is None or
                end_ts < start_ts or end_ts - start_ts > MAX_DURATION):
            raise ValueError("scenario window must be timezone-aware, ordered, and at most seven days")
        specs = data.get("strategies", [])
        if not isinstance(specs, list) or not 1 <= len(specs) <= MAX_STRATEGIES:
            raise ValueError(f"strategies must contain 1 to {MAX_STRATEGIES} entries")
        artifact_parts = Path(data.get("artifacts_dir", "artifacts")).parts
        if not artifact_parts or artifact_parts[0] != "artifacts" or any(
            safe_component(part, "artifacts_dir") != part for part in artifact_parts
        ):
            raise ValueError("scenario artifacts_dir must be under relative artifacts/")
        universe = UniverseSpec.from_dict(data["universe"])
        strategies = [StrategySpec.from_dict(s) for s in specs]
        risk = RiskSpec.from_dict(data["risk"])
        fees = FeeSpec.from_dict(data["fees"])
        return BacktestScenario(
            scenario_id=scenario_id,
            description=data.get("description", ""),
            start_ts=start_ts,
            end_ts=end_ts,
            universe=universe,
            strategies=strategies,
            risk=risk,
            fees=fees,
            lake1_env=data.get("lake1_env", "studio1"),
            world_model=data.get("world_model", "volatility"),
            artifacts_dir=str(Path(*artifact_parts)),
        )

    @staticmethod
    def load(path: str) -> "BacktestScenario":
        p = Path(path)
        with p.open("rb") as source:
            raw = source.read(MAX_SCENARIO_BYTES + 1)
        if len(raw) > MAX_SCENARIO_BYTES:
            raise ValueError("scenario exceeds size limit")
        def reject_nonfinite(value: str):
            raise ValueError(f"nonfinite JSON number: {value}")

        data = json.loads(raw, parse_constant=reject_nonfinite)
        if not isinstance(data, dict):
            raise ValueError("scenario must be a JSON object")
        return BacktestScenario.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "description": self.description,
            "start_ts": self.start_ts.isoformat(),
            "end_ts": self.end_ts.isoformat(),
            "universe": dataclasses.asdict(self.universe),
            "strategies": [dataclasses.asdict(s) for s in self.strategies],
            "risk": dataclasses.asdict(self.risk),
            "fees": dataclasses.asdict(self.fees),
            "lake1_env": self.lake1_env,
            "world_model": self.world_model,
            "artifacts_dir": self.artifacts_dir,
        }

    def dump(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True)
