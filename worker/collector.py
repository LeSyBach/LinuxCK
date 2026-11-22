import json
import logging
import time

from .models import parse_rows, timestamp, utc_now
from .worker_protocol import Job, MarketResult, ResultSink

LOG = logging.getLogger(__name__)


class Collector:
    def __init__(self, api, config, sink: ResultSink):
        self.api = api
        self.config = config
        self.sink = sink
        self.symbols_param = json.dumps(config.symbols, separators=(",", ":"))
        self.ready = False
        self.request_weight_limit = None

    async def preflight(self):
        self.ready = False
        if await self.api.get("ping") != {}:
            raise ValueError("Unexpected ping response")
        server_ms = (await self.api.get("time"))["serverTime"]
        LOG.info("Binance server time %s", timestamp(server_ms))
        info = await self.api.get("exchangeInfo", symbols=self.symbols_param)
        self.request_weight_limit = next(
            (item["limit"] for item in info.get("rateLimits", [])
             if item["rateLimitType"] == "REQUEST_WEIGHT" and item["interval"] == "MINUTE"
             and item["intervalNum"] == 1), None,
        )
        symbols = info["symbols"]
        active = {item["symbol"] for item in symbols
                  if item["status"] == "TRADING" and item["isSpotTradingAllowed"] is True}
        if active != set(self.config.symbols) or len(symbols) != len(active):
            raise ValueError(f"Spot trading unavailable for {set(self.config.symbols) - active}")
        self.ready = True
        LOG.info("Verified tradable symbols %s; exchange one-minute weight limit %s",
                 ", ".join(self.config.symbols), self.request_weight_limit)

    async def btc_probe(self):
        if "BTCUSDT" in self.config.symbols:
            if not self.ready:
                raise RuntimeError("Run preflight first")
            response = await self.api.get("ticker/price", symbol="BTCUSDT")
            row, = parse_rows("price", [response], ("BTCUSDT",))
            LOG.info("BTCUSDT single-symbol probe price=%s", row["price"])

    async def fetch(self, kind):
        if kind in ("price", "ticker"):
            path = "ticker/price" if kind == "price" else "ticker/24hr"
            raw = await self.api.get(path, symbols=self.symbols_param)
            return parse_rows(kind, raw, self.config.symbols)
        server_ms = (await self.api.get("time"))["serverTime"]
        timestamp(server_ms)
        rows = []
        for symbol in self.config.symbols:
            for interval in ("1m", "5m"):
                raw = await self.api.get("klines", symbol=symbol, interval=interval,
                                         limit=self.config.candle_limit, endTime=server_ms - 1)
                rows.extend(parse_rows(kind, raw, (symbol,), interval=interval, server_ms=server_ms))
        return rows

    async def run(self, job: Job):
        started = utc_now()
        clock = time.monotonic()
        try:
            if self.sink.completed(job):
                return True
            if not self.ready:
                await self.preflight()
            rows = await self.fetch(job.kind)
            collected = utc_now()
            results = [
                MarketResult(job.job_id, job.kind, row["symbol"],
                             row["close"] if job.kind == "kline" else row["price"],
                             collected, row["source_timestamp"],
                             {key: value for key, value in row.items()
                              if key not in {"symbol", "source_timestamp", "price"}})
                for row in rows
            ]
            self.sink.save(job, started, utc_now(), (time.monotonic() - clock) * 1000, results)
            LOG.info("Job %s %s OK, %s validated API rows processed", job.job_id, job.kind, len(results))
            return True
        except Exception as exc:
            LOG.error("Job %s %s failed: %s", job.job_id, job.kind, exc)
            try:
                self.sink.failure(job, started, utc_now(), (time.monotonic() - clock) * 1000, exc)
            except Exception:
                LOG.exception("Could not record failure in result sink")
            return False
