import asyncio
import csv
import json
import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from decimal import InvalidOperation
from pathlib import Path
from threading import Thread

import httpx
import pytest

from worker.binance_client import BinanceClient, retry_delay
from worker.collector import Collector
from worker.config import Config
from worker.metrics import database_stats
from worker.models import parse_rows, timestamp
from worker.scheduler import run_schedule
from worker.storage import COLUMNS, TABLES, Storage
from worker.worker_protocol import Job, MarketResult

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT")
CONFIG = Config(SYMBOLS)
NOW = 1_800_000_310_000


def exchange_reply(request):
    endpoint = request.url.path.removeprefix("/api/v3/")
    symbols = json.loads(request.url.params.get("symbols", "[]"))
    if endpoint == "ping":
        payload = {}
    elif endpoint == "time":
        payload = {"serverTime": NOW}
    elif endpoint == "exchangeInfo":
        payload = {"symbols": [dict(symbol=s, status="TRADING", isSpotTradingAllowed=True) for s in symbols]}
    elif endpoint == "ticker/price":
        payload = [dict(symbol=s, price="1.2500") for s in symbols]
    elif endpoint == "ticker/24hr":
        payload = [dict(symbol=s, lastPrice="1.25", openPrice="1", highPrice="2", lowPrice="1",
                        priceChange="0.25", priceChangePercent="25", volume="100", quoteVolume="125",
                        openTime=NOW-86_400_000, closeTime=NOW) for s in symbols]
    elif endpoint == "klines":
        duration = {"1m": 60_000, "5m": 300_000}[request.url.params["interval"]]
        opened = NOW // duration * duration
        payload = [[start, "1", "2", "1", "1.25", "100", start+duration-1,
                    "125", 10, "50", "62.5", "0"] for start in (opened-duration, opened)]
    else:
        raise AssertionError(endpoint)
    return httpx.Response(200, json=payload)


def mock_http(handler=exchange_reply):
    return httpx.AsyncClient(base_url="https://mock.invalid", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", None, 2.5, "invalid"])
def test_invalid_price(price):
    with pytest.raises((ValueError, InvalidOperation)):
        parse_rows("price", [{"symbol": "BTCUSDT", "price": price}], ("BTCUSDT",))


@pytest.mark.parametrize("raw", [{}, [], [{"symbol": "BTCUSDT"}], [{"symbol": "ETHUSDT", "price": "1"}],
                                 [{"symbol": "BTCUSDT", "price": "1"}] * 2])
def test_invalid_shape(raw):
    with pytest.raises((ValueError, KeyError)):
        parse_rows("price", raw, ("BTCUSDT",))


def test_price_and_utc():
    row, = parse_rows("price", [{"symbol": "BTCUSDT", "price": "1.2500"}], ("BTCUSDT",))
    assert row == dict(symbol="BTCUSDT", price="1.2500", source_timestamp=None)
    assert datetime.fromisoformat(timestamp(NOW)).utcoffset().total_seconds() == 0
    with pytest.raises(ValueError):
        timestamp(-1)


def test_protocol():
    result = MarketResult("job-42", "price", "BTCUSDT", "1.2500", timestamp(NOW), None, {})
    assert result.to_message()["collection_run_id"] == "job-42"
    assert json.loads(json.dumps(result.to_message()))["price"] == "1.2500"
    with pytest.raises(ValueError):
        MarketResult("job", "price", "BTCUSDT", "1", "2026-01-01T00:00:00", None, {})
    with pytest.raises(ValueError):
        Job("job", "unknown")
    with pytest.raises(ValueError, match="payload"):
        MarketResult("job", "ticker", "BTCUSDT", "1", timestamp(NOW), timestamp(NOW), {})


@pytest.mark.parametrize("symbols", [(), ("btcusdt",), ("BTCUSDT", "BTCUSDT")])
def test_configuration_symbols(symbols):
    with pytest.raises(ValueError):
        Config(symbols)
    with pytest.raises(ValueError):
        Config(SYMBOLS, price_seconds=59)


def test_preflight_rejects_halted_spot(tmp_path):
    def handler(request):
        if request.url.path.endswith("exchangeInfo"):
            return httpx.Response(200, json={"symbols": [
                dict(symbol=s, status="BREAK", isSpotTradingAllowed=True) for s in SYMBOLS
            ]})
        return exchange_reply(request)

    async def run():
        async with mock_http(handler) as http:
            collector = Collector(BinanceClient(http), CONFIG, Storage(tmp_path / "mock.sqlite3"))
            with pytest.raises(ValueError, match="Spot trading unavailable"):
                await collector.preflight()
            assert not collector.ready
    asyncio.run(run())


@pytest.mark.parametrize("failure,expected_attempts,expected_waits", [
    ("offline", 3, [1, 2]), ("dns", 3, [1, 2]), ("timeout", 3, [1, 2]),
    (429, 2, [75]), (418, 1, []), (403, 1, []), (451, 1, []), (500, 3, [1, 2]),
    ("invalid-json", 1, []),
])
def test_api_recovery(failure, expected_attempts, expected_waits):
    waits = []
    calls = 0

    async def sleep(seconds):
        waits.append(seconds)

    def handler(request):
        nonlocal calls
        calls += 1
        if failure == "offline":
            raise httpx.ConnectError("offline", request=request)
        if failure == "dns":
            try:
                raise socket.gaierror("DNS lookup failed")
            except socket.gaierror as exc:
                raise httpx.ConnectError("DNS lookup failed", request=request) from exc
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if failure == "invalid-json":
            return httpx.Response(200, text="invalid")
        if failure == 429 and calls == 2:
            return httpx.Response(200, json={})
        return httpx.Response(failure, headers={"Retry-After": "75"})

    async def run():
        async with mock_http(handler) as http:
            client = BinanceClient(http, sleep=sleep)
            if failure == 429:
                assert await client.get("ping") == {}
            else:
                with pytest.raises((httpx.HTTPError, ValueError)):
                    await client.get("ping")
            if failure == 418:
                with pytest.raises(RuntimeError, match="cooldown"):
                    await client.get("ping")
            if failure in (403, 451):
                with pytest.raises(RuntimeError, match="denied access"):
                    await client.get("ping")
            assert len(client.requests) == expected_attempts
        assert calls == expected_attempts
        assert waits == expected_waits
    asyncio.run(run())


def test_retry_after():
    assert retry_delay("100", 60) == 100
    assert retry_delay("bad", 60) == 60
    assert retry_delay("inf", 60) == 60


class FakeClock:
    instant = 0

    def __call__(self):
        return self.instant

    async def sleep(self, duration):
        self.instant += duration


def test_stability_restart_and_export(tmp_path):
    path = tmp_path / "mock.sqlite3"

    async def run():
        storage = Storage(path)
        async with mock_http() as http:
            api = BinanceClient(http)
            collector = Collector(api, CONFIG, storage)
            clock = FakeClock()
            observed = await run_schedule(collector, CONFIG.periods, seconds=600, clock=clock, sleep=clock.sleep)
            assert observed == dict(success=14, failed=0, cycles=10)
            first = database_stats(storage, api.requests)
            assert first["requests"] == 37
            assert first["total"] == 70
            assert first["journal_mode"] == "wal"
            assert first["integrity"] == "ok"
            print(f"MOCK CLOCK {observed} | {first['requests']} requests | {first['total']} rows")

        reopened = Storage(path)
        async with mock_http() as http:
            collector = Collector(BinanceClient(http), CONFIG, reopened)
            job = Job("retry-job", "price")
            assert await collector.run(job)
            assert await collector.run(job)
        counts = database_stats(reopened)
        assert counts["total"] == 75
        assert counts["runs"] == {"success": 15}
        csv_path = tmp_path / "prices.csv"
        reopened.export("price_snapshots", csv_path)
        with csv_path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 55
        assert all(row["price"] == "1.2500" and not row["source_timestamp"] for row in rows)

    asyncio.run(run())


def test_database_lock_recovery(tmp_path):
    storage = Storage(tmp_path / "mock.sqlite3", busy_timeout=0.01)
    holder = sqlite3.connect(storage.path, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    failed_job = Job("locked", "price")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        storage.failure(failed_job, timestamp(NOW), timestamp(NOW), 10, ValueError("mock"))
    holder.rollback()

    holder.execute("BEGIN IMMEDIATE")
    from time import sleep
    def release():
        sleep(0.035)
        holder.rollback()
    thread = Thread(target=release)
    thread.start()
    try:
        storage.failure(failed_job, timestamp(NOW), timestamp(NOW), 10, ValueError("mock"))
    finally:
        thread.join()
        holder.close()
    assert database_stats(storage)["errors"] == 1
    assert database_stats(storage)["integrity"] == "ok"


def test_abrupt_process_exit(tmp_path):
    path = tmp_path / "mock.sqlite3"
    storage = Storage(path)
    storage.failure(Job("committed", "price"), timestamp(NOW), timestamp(NOW), 1, ValueError("mock"))
    code = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("BEGIN IMMEDIATE")
db.execute("DELETE FROM crawl_runs")
os._exit(17)
"""
    child = subprocess.run([sys.executable, "-c", code, str(path)], check=False)
    assert child.returncode == 17
    assert database_stats(Storage(path))["runs"] == {"failed": 1}
    assert database_stats(Storage(path))["integrity"] == "ok"


def test_bad_payload_then_same_job_recovers(tmp_path):
    storage = Storage(tmp_path / "mock.sqlite3")
    job = Job("recover", "price")

    def broken(request):
        if request.url.path.endswith("ticker/price"):
            return httpx.Response(200, json=[{"symbol": "BTCUSDT"}])
        return exchange_reply(request)

    async def run():
        async with mock_http(broken) as http:
            assert not await Collector(BinanceClient(http), CONFIG, storage).run(job)
        assert database_stats(storage)["total"] == 0
        async with mock_http() as http:
            assert await Collector(BinanceClient(http), CONFIG, storage).run(job)
        assert database_stats(storage)["runs"] == {"success": 1}
        assert database_stats(storage)["errors"] == 1
        assert database_stats(storage)["total"] == 5
    asyncio.run(run())


def test_live_session_evidence():
    if not os.getenv("BINANCE_LIVE_RESULTS"):
        pytest.skip("Set BINANCE_LIVE_RESULTS to the report of a real CLI collection")
    evidence = json.loads(Path(os.environ["BINANCE_LIVE_RESULTS"]).read_text())
    if evidence["status"] == "BLOCKED":
        pytest.skip("Live API BLOCKED: " + evidence["blocked"])
    assert evidence["status"] == "PASS"
    assert evidence["stats"]["request_success"] > 0
    assert {"ping", "time", "exchangeInfo", "ticker/price", "ticker/24hr", "klines"} <= {
        row["endpoint"] for row in evidence["requests"] if row["status"] == 200
    }
    storage = Storage(os.environ["BINANCE_LIVE_DATABASE"])
    with closing(storage.connect()) as db:
        assert {row[0] for row in db.execute("SELECT DISTINCT symbol FROM price_snapshots")} == set(SYMBOLS)
        assert {row[0] for row in db.execute("SELECT DISTINCT symbol FROM ticker_24h")} == set(SYMBOLS)
        assert db.execute("SELECT count(*) FROM price_snapshots WHERE source_timestamp IS NOT NULL").fetchone()[0] == 0
        assert {row[0] for row in db.execute("SELECT DISTINCT interval FROM klines")} == {"1m", "5m"}
        for kind, table in TABLES.items():
            for row in db.execute(f"SELECT * FROM {table}"):
                fields = tuple(field for field in COLUMNS[kind] if field != "price")
                MarketResult(row["collection_run_id"], kind, row["symbol"],
                             row["close"] if kind == "kline" else row["price"],
                             row["collected_at"], row["source_timestamp"],
                             {field: row[field] for field in fields})
    live_stats = database_stats(storage)
    assert live_stats["total"] == evidence["stats"]["total"]
    assert live_stats["integrity"] == "ok"
