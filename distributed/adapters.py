"""Public spot endpoints. No credentials or alternate hosts."""
import json
import time
from datetime import datetime, timezone
from decimal import Decimal

from worker.binance_client import BinanceClient
from worker.models import decimal_text, timestamp, utc_now

SYMBOLS = ("BTC", "ETH", "SOL", "XRP", "ADA")
EXCHANGES = {"binance": "worker-2", "okx": "worker-3", "bybit": "worker-4"}
URLS = dict(binance="https://data-api.binance.vision", okx="https://www.okx.com",
            bybit="https://api.bybit.com")


def product(base, exchange):
    return base + ("-" if exchange == "okx" else "") + "USDT"


def optional(value):
    return None if value in (None, "") else decimal_text(value, nonnegative=True)


class SpotAdapter:
    def __init__(self, exchange, http):
        self.exchange = exchange
        self.api = BinanceClient(http, prefix={"binance": "/api/v3/", "okx": "/api/v5/",
                                               "bybit": "/v5/"}[exchange],
                                 label=exchange.upper(), history_limit=2000)
        self.products = {product(base, exchange): base + "/USDT" for base in SYMBOLS}
        self.binance_symbols = json.dumps(list(self.products), separators=(",", ":"))
        self.validated = False

    async def get(self, path, **params):
        payload = await self.api.get(path, **params)
        if self.exchange == "binance":
            return payload
        if self.exchange == "okx":
            if payload["code"] != "0":
                raise ValueError(f"OKX application error {payload['code']}")
            return payload["data"]
        if payload["retCode"] != 0:
            raise ValueError(f"Bybit application error {payload['retCode']}")
        result = payload["result"]
        if result.get("category", "spot") != "spot":
            raise ValueError("Unexpected Bybit market category")
        return result["list"]

    async def validate(self):
        if self.exchange == "binance":
            data = await self.get("exchangeInfo", symbols=self.binance_symbols)
            active = {r["symbol"] for r in data["symbols"]
                      if r["status"] == "TRADING" and r["isSpotTradingAllowed"]}
        elif self.exchange == "okx":
            data = await self.get("public/instruments", instType="SPOT")
            active = {r["instId"] for r in data if r["state"] == "live" and r["quoteCcy"] == "USDT"}
        else:
            active = set()
            for symbol in self.products:
                data = await self.get("market/instruments-info", category="spot", symbol=symbol)
                active.update(r["symbol"] for r in data
                              if r["status"] == "Trading" and r["quoteCoin"] == "USDT")
        if not self.products.keys() <= active:
            raise ValueError(f"Inactive or absent spot symbols: {self.products.keys() - active}")
        self.validated = True

    def normalize(self, row, kind, book=None):
        if self.exchange == "binance":
            key = row["symbol"]
            price = row["price"] if kind == "price" else row["lastPrice"]
            quote, volume = row.get("quoteVolume"), row.get("volume")
            bidask = book if book is not None else row
            bid, ask = bidask.get("bidPrice"), bidask.get("askPrice")
            change = row.get("priceChangePercent")
            source = timestamp(row["closeTime"]) if "closeTime" in row else None
        elif self.exchange == "okx":
            key, price = row["instId"], row["last"]
            quote, volume = row["volCcy24h"], row["vol24h"]
            bid, ask = row["bidPx"], row["askPx"]
            opening = Decimal(row["open24h"])
            change = (Decimal(price) / opening - 1) * 100 if opening > 0 else None
            source = timestamp(int(row["ts"])) if row.get("ts") else None
        else:
            key, price = row["symbol"], row["lastPrice"]
            quote, volume = row["turnover24h"], row["volume24h"]
            bid, ask = row["bid1Price"], row["ask1Price"]
            change = Decimal(row["price24hPcnt"]) * 100 if row.get("price24hPcnt") else None
            source = None
        result = dict(symbol=self.products[key], price=decimal_text(price, positive=True),
                      bid=optional(bid), ask=optional(ask), source_timestamp=source)
        if kind == "ticker":
            result.update(volume=optional(volume), quote_volume=optional(quote),
                          change_percent=None if change is None else decimal_text(change))
        return result

    async def market(self, kind):
        if self.exchange == "binance":
            if kind == "ticker":
                data = await self.get("ticker/24hr", symbols=self.binance_symbols)
                return [self.normalize(row, kind) for row in data]
            data = await self.get("ticker/price", symbols=self.binance_symbols)
            books = {row["symbol"]: row for row in
                     await self.get("ticker/bookTicker", symbols=self.binance_symbols)}
            return [self.normalize(row, kind, books[row["symbol"]]) for row in data]
        if self.exchange == "okx":
            data = await self.get("market/tickers", instType="SPOT")
            return [self.normalize(row, kind) for row in data if row["instId"] in self.products]
        rows = []
        for key in self.products:
            data = await self.get("market/tickers", category="spot", symbol=key)
            rows.extend(self.normalize(row, kind) for row in data)
        return rows

    async def candles(self):
        rows = []
        if self.exchange == "binance":
            cutoff = (await self.get("time"))["serverTime"]
        else:
            cutoff = int(datetime.now(timezone.utc).timestamp() * 1000)
        for key, symbol in self.products.items():
            for minutes in (1, 5):
                interval = f"{minutes}m"
                if self.exchange == "binance":
                    data = await self.get("klines", symbol=key, interval=interval, limit=3)
                    records = [(int(r[0]), r[1:6], r[7]) for r in data]
                elif self.exchange == "okx":
                    data = await self.get("market/candles", instId=key, bar=interval, limit=3)
                    records = [(int(r[0]), r[1:6], r[7]) for r in data if r[8] == "1"]
                else:
                    data = await self.get("market/kline", category="spot", symbol=key,
                                          interval=minutes, limit=3)
                    records = [(int(r[0]), r[1:6], r[6]) for r in data]
                for opened, values, quote in records:
                    closed = opened + minutes * 60_000 - 1
                    if closed >= cutoff:
                        continue
                    op, high, low, close = [decimal_text(value, positive=True) for value in values[:4]]
                    if not Decimal(low) <= min(Decimal(op), Decimal(close)) <= max(Decimal(op), Decimal(close)) <= Decimal(high):
                        raise ValueError("Invalid OHLC range")
                    rows.append(dict(symbol=symbol, interval=interval, open_time=timestamp(opened),
                                     source_timestamp=timestamp(closed), open=op, high=high,
                                     low=low, price=close, volume=optional(values[4]),
                                     quote_volume=optional(quote)))
        return rows

    async def collect(self, kind):
        start = time.monotonic()
        if not self.validated:
            await self.validate()
        rows = await (self.candles() if kind == "kline" else self.market(kind))
        if kind != "kline" and sorted(row["symbol"] for row in rows) != sorted(self.products.values()):
            raise ValueError("Missing or duplicated spot symbol")
        if kind == "kline" and {(r["symbol"], r["interval"]) for r in rows} != {
            (symbol, interval) for symbol in self.products.values() for interval in ("1m", "5m")
        }:
            raise ValueError("Missing closed candles")
        now = utc_now()
        return [dict(row, collected_at=now, latency_ms=round((time.monotonic() - start) * 1000, 2))
                for row in rows]
