import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    symbols: tuple[str, ...]
    price_seconds: int = 60
    ticker_seconds: int = 300
    kline_seconds: int = 300
    candle_limit: int = 3

    def __post_init__(self):
        if (not 1 <= len(self.symbols) <= 20
                or len(set(self.symbols)) != len(self.symbols)
                or any(not re.fullmatch(r"[A-Z0-9]{2,30}", s) for s in self.symbols)):
            raise ValueError("Expected 1–20 unique Binance symbols")
        for value, minimum in zip(self.periods.values(), (60, 300, 300)):
            if type(value) is not int or value < minimum:
                raise ValueError(f"Collection period must be at least {minimum} s")
        if type(self.candle_limit) is not int or not 1 <= self.candle_limit <= 1000:
            raise ValueError("candle_limit must be 1–1000")

    @property
    def periods(self):
        return dict(price=self.price_seconds, ticker=self.ticker_seconds, kline=self.kline_seconds)

    @classmethod
    def load(cls, path: Path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["symbols"] = tuple(raw["symbols"])
        return cls(**raw)
