import hashlib
import math
from datetime import datetime, timedelta

from worker.models import decimal_text
from .adapters import EXCHANGES, SYMBOLS

KINDS = ("price", "ticker", "kline")


def utc(value):
    if not isinstance(value, str):
        raise ValueError("Expected UTC timestamp")
    result = datetime.fromisoformat(value)
    if result.utcoffset() != timedelta(0):
        raise ValueError("Expected UTC timestamp")
    return result


def message(exchange, kind, collection, row):
    key = "|".join((exchange, kind, row["symbol"], row.get("interval", ""),
                    row.get("open_time", collection)))
    digest = hashlib.sha256(key.encode()).hexdigest()
    return dict(version=1, id=digest, idempotency_key=digest, collection_id=collection,
                exchange=exchange, worker_id=EXCHANGES[exchange], market="spot", kind=kind, data=row)


def validate(body):
    exchange, kind, row = body["exchange"], body["kind"], body["data"]
    if body["version"] != 1 or body["worker_id"] != EXCHANGES[exchange] or body["market"] != "spot":
        raise ValueError("Invalid message metadata")
    if kind not in KINDS or row["symbol"] not in {s + "/USDT" for s in SYMBOLS}:
        raise ValueError("Unsupported market data")
    if not isinstance(body["collection_id"], str) or not 1 <= len(body["collection_id"]) <= 128:
        raise ValueError("Invalid collection ID")
    rebuilt = message(exchange, kind, body["collection_id"], row)
    if any(body[k] != rebuilt[k] for k in ("id", "idempotency_key")):
        raise ValueError("Invalid idempotency key")
    utc(row["collected_at"])
    if row["source_timestamp"] is not None:
        utc(row["source_timestamp"])
    decimal_text(row["price"], positive=True)
    latency = row["latency_ms"]
    if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
        raise ValueError("Invalid latency")
    for field in ("bid", "ask", "volume", "quote_volume", "change_percent"):
        if row.get(field) is not None:
            decimal_text(row[field], nonnegative=field != "change_percent")
    if kind == "kline":
        if row["interval"] not in ("1m", "5m") or utc(row["open_time"]) >= utc(row["source_timestamp"]):
            raise ValueError("Invalid candle interval")
        for field in ("open", "high", "low"):
            decimal_text(row[field], positive=True)
    return body
