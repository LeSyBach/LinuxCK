from datetime import datetime, timezone
from decimal import Decimal


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def timestamp(milliseconds):
    if type(milliseconds) is not int or milliseconds < 0:
        raise ValueError("Invalid Binance timestamp")
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat(timespec="milliseconds")


def decimal_text(value, *, positive=False, nonnegative=False):
    if not isinstance(value, (str, Decimal, int)) or isinstance(value, bool):
        raise ValueError("Expected decimal string or integer")
    number = Decimal(value)
    if not number.is_finite() or (positive and number <= 0) or (nonnegative and number < 0):
        raise ValueError(f"Invalid decimal: {value!r}")
    return format(number, "f")


def parse_rows(kind, raw, symbols, *, interval=None, server_ms=None):
    if not isinstance(raw, list):
        raise ValueError("Expected a JSON array")
    if kind == "kline":
        if not raw:
            raise ValueError("Empty kline response")
        rows = []
        for item in raw:
            if not isinstance(item, list) or len(item) != 12:
                raise ValueError("Invalid kline shape")
            opened, closed = timestamp(item[0]), timestamp(item[6])
            duration = {"1m": 60_000, "5m": 300_000}[interval]
            if item[0] % duration or item[6] != item[0] + duration - 1:
                raise ValueError("Invalid kline time range")
            prices = [decimal_text(v, positive=True) for v in item[1:5]]
            op, high, low, close = map(Decimal, prices)
            if not low <= min(op, close) <= max(op, close) <= high:
                raise ValueError("Invalid OHLC range")
            volume = decimal_text(item[5], nonnegative=True)
            quote = decimal_text(item[7], nonnegative=True)
            if item[6] < server_ms:
                rows.append(dict(symbol=symbols[0], interval=interval, open_time=opened,
                                 close_time=closed, open=prices[0], high=prices[1],
                                 low=prices[2], close=prices[3], volume=volume,
                                 quote_volume=quote, source_timestamp=closed))
        return rows
    if sorted(item["symbol"] for item in raw) != sorted(symbols):
        raise ValueError("Missing, duplicate, or unexpected symbol")
    rows = []
    for item in raw:
        row = dict(symbol=item["symbol"], source_timestamp=None)
        if kind == "price":
            row["price"] = decimal_text(item["price"], positive=True)
        else:
            row.update(
                source_timestamp=timestamp(item["closeTime"]),
                open_time=timestamp(item["openTime"]),
                price=decimal_text(item["lastPrice"], positive=True),
                open=decimal_text(item["openPrice"], positive=True),
                high=decimal_text(item["highPrice"], positive=True),
                low=decimal_text(item["lowPrice"], positive=True),
                price_change=decimal_text(item["priceChange"]),
                price_change_percent=decimal_text(item["priceChangePercent"]),
                volume=decimal_text(item["volume"], nonnegative=True),
                quote_volume=decimal_text(item["quoteVolume"], nonnegative=True),
            )
            if row["open_time"] > row["source_timestamp"]:
                raise ValueError("Invalid ticker time range")
        rows.append(row)
    return rows
