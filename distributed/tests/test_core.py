import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from distributed.adapters import EXCHANGES, SpotAdapter, URLS
from distributed.analysis import compare
from distributed.local import Local
from distributed.protocol import message, validate
from distributed.telegram import preview
from worker.worker_protocol import Job

from .fixtures import fixture

NOW = datetime(2026, 11, 22, 9, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("exchange", EXCHANGES)
def test_spot_adapter_and_storage(exchange, tmp_path):
    async def gather():
        async with httpx.AsyncClient(base_url=URLS[exchange], transport=httpx.MockTransport(
            lambda request: fixture(exchange, lambda: False, request)
        )) as http:
            adapter = SpotAdapter(exchange, http)
            return [await adapter.collect(kind) for kind in ("price","ticker","kline")]
    store = Local(tmp_path / "mock.db", exchange)
    for kind, rows in zip(("price", "ticker", "kline"), asyncio.run(gather())):
        job = Job("example-" + kind, kind)
        assert store.store(job, rows) == (10 if kind == "kline" else 5)
        assert store.store(job, rows) == 0
        assert rows[0]["symbol"] == "BTC/USDT"
        if kind != "kline":
            assert rows[0]["bid"] == "94950" and rows[0]["ask"] == "95100"
        if kind == "price":
            assert (rows[0]["source_timestamp"] is not None) == (exchange == "okx")
    restarted = Local(store.path, exchange)
    assert restarted.status()["pending"] == 20
    restarted.receipt(restarted.pending()[0][0])
    assert restarted.status()["pending"] == 19
    assert sum(restarted.status()["records"].values()) == 20


def test_invalid_message_rolls_back_atomic_outbox(tmp_path):
    store = Local(tmp_path / "mock.db", "binance")
    row = dict(symbol="BTC/USDT", collected_at=NOW.isoformat(), source_timestamp=None, latency_ms=1, price="1.00001")
    job = Job("test", "price")
    payload = message("binance", "price", "test", row)
    with pytest.raises(ValueError):
        validate({**payload, "id": "corrupt"})
    with pytest.raises(ValueError):
        store.store(job, [row, {**row, "symbol": "ETH/USDT", "price": "0"}])
    assert store.status()["pending"] == 0
    assert store.status()["records"]["price"] == 0


def test_comparison_higher_lower_freshness_and_telegram():
    rows = [dict(symbol="BTC/USDT", exchange=exchange, price=price,
                 collected_at=NOW-timedelta(seconds=10), source_timestamp=None)
            for exchange, price in (("binance","95000"),("okx","95020"),("bybit","94980"))]
    all_three = compare("BTC/USDT", rows, NOW)
    assert all_three["spread"] == "40"
    assert all_three["low_exchange"] == "bybit" and all_three["high_exchange"] == "okx"
    rows[-1]["source_timestamp"] = NOW-timedelta(minutes=2)
    partial = compare("BTC/USDT", rows, NOW)
    assert partial["valid"] == 2 and partial["sources"]["bybit"]["status"] == "stale"
    assert partial["spread"] == "20"
    assert "spread" not in compare("BTC/USDT", rows[1:], NOW)
    rendered = preview(partial, NOW)
    assert "22/11/2026 16:10:00 (UTC+7)" in rendered
    assert "Nguồn hợp lệ: 2/3" in rendered
