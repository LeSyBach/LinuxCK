import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Protocol

from .models import decimal_text

TICKER_FIELDS = ("open_time", "open", "high", "low", "price_change",
                 "price_change_percent", "volume", "quote_volume")
KLINE_FIELDS = ("interval", "open_time", "close_time", "open", "high",
                "low", "close", "volume", "quote_volume")
PAYLOAD_FIELDS = {"price": (), "ticker": TICKER_FIELDS, "kline": KLINE_FIELDS}


def utc_datetime(value):
    if not isinstance(value, str):
        raise ValueError("Expected an ISO-8601 UTC timestamp")
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() != timedelta(0):
        raise ValueError("Timestamp must be UTC")
    return instant


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", self.job_id):
            raise ValueError("Invalid job_id")
        if self.kind not in {"price", "ticker", "kline"}:
            raise ValueError("Invalid job kind")


@dataclass(frozen=True)
class MarketResult:
    job_id: str
    kind: str
    symbol: str
    price: str
    collected_at: str
    source_timestamp: str | None
    data: dict
    worker_id: str = "worker-2"
    exchange: str = "binance"
    status: str = "success"
    schema_version: int = 1

    def __post_init__(self):
        Job(self.job_id, self.kind)
        if not re.fullmatch(r"[A-Z0-9]{2,30}", self.symbol):
            raise ValueError("Invalid result symbol")
        if not isinstance(self.price, str):
            raise ValueError("Protocol price must be a decimal string")
        decimal_text(self.price, positive=True)
        if (self.exchange, self.worker_id, self.status, self.schema_version) != (
            "binance", "worker-2", "success", 1
        ):
            raise ValueError("Invalid result metadata")
        utc_datetime(self.collected_at)
        if (self.source_timestamp is None) != (self.kind == "price"):
            raise ValueError("Invalid source timestamp")
        if not isinstance(self.data, dict) or set(self.data) != set(PAYLOAD_FIELDS[self.kind]):
            raise ValueError("Unexpected or missing payload fields")
        if self.kind == "price":
            return
        opened = utc_datetime(self.data["open_time"])
        source = utc_datetime(self.source_timestamp)
        if opened > source:
            raise ValueError("Invalid market time range")
        for field, value in self.data.items():
            if field in ("interval", "open_time", "close_time"):
                continue
            if not isinstance(value, str):
                raise ValueError("Market values must be decimal strings")
            decimal_text(value, positive=field in ("open", "high", "low", "close"),
                         nonnegative=field in ("volume", "quote_volume"))
        if self.kind == "kline" and (
            self.data["interval"] not in ("1m", "5m")
            or utc_datetime(self.data["close_time"]) != source
            or self.data["close"] != self.price
        ):
            raise ValueError("Invalid kline payload")

    def to_message(self):
        return {**asdict(self), "collection_run_id": self.job_id}


class ResultSink(Protocol):
    def completed(self, job: Job) -> bool: ...
    def save(self, job: Job, started: str, finished: str, elapsed: float,
             results: list[MarketResult]) -> None: ...
    def failure(self, job: Job, started: str, finished: str, elapsed: float,
                error: Exception) -> None: ...
