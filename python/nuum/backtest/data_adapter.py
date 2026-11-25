#!/usr/bin/env python3
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import stat
from typing import Dict, Iterable, List, Any, Generator

MAX_BARS = 20_000
MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024


@dataclass
class MarketBar:
    ts: datetime
    symbol: str
    price: float
    volume: float
    iv: float  # implied volatility proxy


class Lake1DataAdapter:
    """
    Simplified adapter that replays lake1 state.

    In a real deployment this would query lake1; here we support:
    - JSON lines file with synthetic bars
    - Or generate dummy bars if no file is provided
    """

    def __init__(self, universe_symbols: List[str], start_ts: datetime, end_ts: datetime, state_path: str | None):
        self.universe_symbols = universe_symbols
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.state_path = state_path

    def _iter_from_file(self, path: Path) -> Generator[MarketBar, None, None]:
        source_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(source_fd, "rb") as source:
            size = os.fstat(source.fileno())
            if not stat.S_ISREG(size.st_mode) or size.st_size > MAX_STATE_BYTES:
                raise ValueError("state file must be regular and at most 8 MiB")
            total_bytes = 0
            records = 0
            while line := source.readline(MAX_LINE_BYTES + 1):
                total_bytes += len(line)
                records += 1
                if len(line) > MAX_LINE_BYTES or total_bytes > MAX_STATE_BYTES or records > MAX_BARS:
                    raise ValueError("state file exceeds record, line, or byte limit")
                if not line.strip():
                    continue
                rec = json.loads(line)
                if not isinstance(rec, dict):
                    raise ValueError("state line must be a JSON object")
                ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                if ts.utcoffset() is None:
                    raise ValueError("state timestamp must include a timezone")
                if ts < self.start_ts or ts > self.end_ts:
                    continue
                symbol = rec["symbol"]
                if symbol not in self.universe_symbols:
                    raise ValueError("state symbol not in scenario universe")
                price = float(rec["price"])
                volume = float(rec.get("volume", 0.0))
                iv = float(rec.get("iv", 0.0))
                if not all(math.isfinite(value) for value in (price, volume, iv)) or price <= 0 or volume < 0:
                    raise ValueError("state bar has invalid numeric values")
                yield MarketBar(
                    ts=ts,
                    symbol=symbol,
                    price=price,
                    volume=volume,
                    iv=iv,
                )

    def _iter_synthetic(self) -> Generator[MarketBar, None, None]:
        step = timedelta(minutes=5)
        steps = int((self.end_ts - self.start_ts) // step) + 1
        if steps * len(self.universe_symbols) > MAX_BARS:
            raise ValueError("synthetic scenario exceeds bar limit")
        ts = self.start_ts
        while ts <= self.end_ts:
            for i, sym in enumerate(self.universe_symbols):
                base = 100.0 + i
                price = base * (1.0 + 0.01 * ((ts - self.start_ts).total_seconds() / 3600.0))
                iv = 0.2 + 0.01 * (i % 5)
                yield MarketBar(ts=ts, symbol=sym, price=price, volume=1000.0, iv=iv)
            ts += step

    def iter_bars(self) -> Iterable[MarketBar]:
        if self.state_path:
            return self._iter_from_file(Path(self.state_path))
        return self._iter_synthetic()
