"""Integration across real RabbitMQ/PostgreSQL and four local processes."""
import json
import os
import select
import socket
import socketserver
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit, urlunsplit

import httpx
import pika
import psycopg
import pytest

from distributed.adapters import EXCHANGES
from distributed.analysis import compare
from distributed.broker import DEAD, QUEUE, connect, emit, topology
from distributed.local import Local
from distributed.postgres import Postgres
from distributed.protocol import message
from worker.models import utc_now

DSN = os.getenv("SIM_POSTGRES_DSN")
AMQP = os.getenv("SIM_AMQP")
pytestmark = pytest.mark.skipif(not DSN or not AMQP, reason="Requires isolated PostgreSQL and RabbitMQ")


def wait_for(function, seconds=22):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            value = function()
            if value:
                return value
        except (OSError, httpx.HTTPError, psycopg.OperationalError):
            pass
        time.sleep(0.2)
    raise AssertionError(f"Timed out: {function.__name__}")


class Relay(socketserver.ThreadingTCPServer):
    daemon_threads = True
    enabled = True


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        if not self.server.enabled:
            return
        with socket.create_connection(self.server.upstream, timeout=2) as upstream:
            pair = [self.request, upstream]
            while self.server.enabled:
                ready, _, _ = select.select(pair, [], [], 0.15)
                for current in ready:
                    data = current.recv(65536)
                    if not data:
                        return
                    pair[1 - pair.index(current)].sendall(data)


def test_four_nodes(tmp_path):
    if urlsplit(DSN).path != "/linuxck_sim" or urlsplit(AMQP).path != "/linuxck-sim":
        pytest.fail("Use the dedicated linuxck_sim database and linuxck-sim vhost")
    pg = Postgres(DSN)
    pg.setup()
    broker = urlsplit(AMQP)
    relay = Relay(("127.0.0.1", 0), Forward)
    relay.upstream = broker.hostname, broker.port
    thread = Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    netloc = broker.netloc.rsplit("@", 1)[0] + f"@127.0.0.1:{relay.server_address[1]}"
    worker_amqp = urlunsplit(broker._replace(netloc=netloc))
    processes = {}
    stores = {e: Local(tmp_path / (e + ".sqlite3"), e) for e in EXCHANGES}
    outage = tmp_path / "bybit-offline"
    port = 58081
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2)
    admin = Postgres(urlunsplit(urlsplit(DSN)._replace(path="/postgres")))
    database_disabled = False

    def spawn(name, arguments, env):
        output = tmp_path / (name + ".log")
        with output.open("a") as log:
            processes[name] = subprocess.Popen([sys.executable, *arguments], stdout=log, stderr=log,
                                               env={**os.environ, **env})
    def stop(name):
        process = processes.pop(name, None)
        if process is None:
            return
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    def start_master():
        spawn("master", ["-m","uvicorn","distributed.master:create_app","--factory","--host","127.0.0.1",
                         "--port",str(port),"--no-access-log"],
              dict(POSTGRES_DSN=DSN, MASTER_ADDRESS=AMQP, WORKER_TIMEOUT="10", TELEGRAM_ENABLED="false"))
        wait_for(lambda: client.get("/health").status_code == 200)
    def start_worker(e):
        spawn(e, ["-m","distributed.tests.sim_worker"],
              dict(EXCHANGE=e, MASTER_ADDRESS=worker_amqp, DATABASE_PATH=str(stores[e].path),
                   FIXTURE_OUTAGE=str(outage if e == "bybit" else tmp_path/"unused")))
    def prices(e):
        return stores[e].status()["records"]["price"]
    def advance(ex, baseline):
        return wait_for(lambda: all(prices(e) > baseline[e] for e in ex))
    def counts():
        return {e: prices(e) for e in EXCHANGES}
    def pending(e):
        return stores[e].status()["pending"]
    def synced(keys):
        with pg.db() as db:
            return db.execute("SELECT count(*) AS n FROM received_messages WHERE id=ANY(%s)", (keys,)).fetchone()["n"]
    def pending_ids(e, since=""):
        with stores[e].db() as db:
            return [row[0] for row in db.execute(
                "SELECT id FROM outbox_messages WHERE synced_at IS NULL AND created_at >= ?", (since,))]
    def receipts(keys):
        for store in stores.values():
            with store.db() as db:
                for key in keys:
                    row = db.execute("SELECT synced_at FROM outbox_messages WHERE id=?", (key,)).fetchone()
                    if row is not None and not row[0]:
                        return False
        return True
    def database_available(enabled):
        with admin.db() as db:
            db.autocommit = True
            db.execute(f"ALTER DATABASE linuxck_sim ALLOW_CONNECTIONS {'true' if enabled else 'false'}")
            if not enabled:
                db.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='linuxck_sim'")
    def result(case, **values):
        print(json.dumps(dict(simulation=True, case=case, status="PASS", **values)), flush=True)

    try:
        start_master()
        for e in EXCHANGES:
            start_worker(e)
        wait_for(lambda: all(prices(e) >= 5 for e in EXCHANGES))
        wait_for(lambda: client.get("/api/overview").json()["online"] == 3)
        for case, exchange in zip("ABC", EXCHANGES):
            stop(exchange)
            baseline = counts()
            peers = [e for e in EXCHANGES if e != exchange]
            advance(peers, baseline)
            def offline():
                overview = client.get("/api/overview").json()
                return any(w["exchange"] == exchange and not w["online"] for w in overview["workers"])
            wait_for(offline)
            assert prices(exchange) == baseline[exchange]
            result(case, stopped=exchange, peers={e: prices(e)-baseline[e] for e in peers},
                   dashboard_offline=True)
            start_worker(exchange)
            advance((exchange,), baseline)
            wait_for(lambda: client.get("/api/overview").json()["online"] == 3)

        stop("master")
        outage_started = utc_now()
        baseline = counts()
        advance(EXCHANGES, baseline)
        wait_for(lambda: all(len(pending_ids(e, outage_started)) >= 5 for e in EXCHANGES))
        held = [key for e in EXCHANGES for key in pending_ids(e, outage_started)]
        assert len(held) >= 15
        assert synced(held) == 0
        result("D", local_deltas={e: prices(e)-baseline[e] for e in EXCHANGES}, pending=len(held),
               postgres_commits=0)
        began = time.monotonic()
        start_master()
        wait_for(lambda: synced(held) == len(held) and receipts(held))
        with pg.db() as db:
            sample = db.execute("SELECT body FROM received_messages WHERE id=%s", (held[0],)).fetchone()["body"]
        assert pg.ingest(sample) == held[0] and synced(held) == len(held)
        result("E", synchronized=len(held), duplicate_commits=0,
               recovery_seconds=round(time.monotonic()-began, 2))

        outage.touch()
        baseline = counts()
        bybit_errors = stores["bybit"].status()["errors"]
        advance(("binance", "okx"), baseline)
        wait_for(lambda: stores["bybit"].status()["errors"] > bybit_errors)
        assert prices("bybit") == baseline["bybit"]
        result("F", injected="Bybit HTTP 503", peers={e: prices(e)-baseline[e] for e in ("binance","okx")})
        outage.unlink()
        advance(("bybit",), baseline)

        relay.enabled = False
        baseline = counts()
        advance(EXCHANGES, baseline)
        wait_for(lambda: all(pending(e) >= 5 for e in EXCHANGES))
        held = [key for e in EXCHANGES for key in pending_ids(e)]
        assert len(held) >= 15 and synced(held) < len(held)
        relay.enabled = True
        wait_for(lambda: synced(held) == len(held) and receipts(held))
        result("G", injected="TCP relay disconnected all worker broker sessions", recovered=len(held))

        database_available(False)
        database_disabled = True
        baseline = counts()
        advance(EXCHANGES, baseline)
        wait_for(lambda: all(pending(e) >= 5 for e in EXCHANGES))
        held = [key for e in EXCHANGES for key in pending_ids(e)]
        assert client.get("/health").status_code == 503
        began = time.monotonic()
        database_available(True)
        database_disabled = False
        wait_for(lambda: synced(held) == len(held) and receipts(held))
        result("H", injected="PostgreSQL test database disabled", recovered=len(held),
               recovery_seconds=round(time.monotonic()-began, 2))

        stop("binance")
        record_count = prices("binance")
        assert Local(stores["binance"].path, "binance").status()["records"]["price"] == record_count
        start_worker("binance")
        wait_for(lambda: prices("binance") > record_count)
        result("I", before=record_count, after=prices("binance"))

        instant = datetime.now(timezone.utc)
        rows = [dict(exchange=e, symbol="BTC/USDT", price="123", collected_at=instant,
                     source_timestamp=instant-timedelta(seconds=100) if e=="bybit" else None)
                for e in EXCHANGES]
        checked = compare("BTC/USDT", rows, instant)
        assert checked["valid"] == 2 and checked["sources"]["bybit"]["status"] == "stale"
        result("J", valid=checked["valid"], bybit=checked["sources"]["bybit"]["status"])

        connection = connect(AMQP)
        try:
            channel = connection.channel()
            topology(channel)
            before = channel.queue_declare(DEAD, passive=True).method.message_count
            emit(channel, QUEUE, {"invalid": "simulation"})
            wait_for(lambda: channel.queue_declare(DEAD, passive=True).method.message_count > before)
        finally:
            connection.close()
        result("DLQ", invalid_messages_rejected=1)

        # Use a fresh deterministic window so concurrent fixture prices cannot supersede
        # the intended spread, and prior dry runs cannot satisfy this assertion.
        end = datetime.now(timezone.utc) + timedelta(days=1)
        with pg.db() as db:
            prior = db.execute("SELECT max(window_end) AS end FROM alerts").fetchone()["end"]
        if prior and prior >= end - timedelta(minutes=10):
            end = prior + timedelta(minutes=11)
        prices_for_alert = [
            dict(exchange=e, symbol="BTC/USDT", price=str(95000+index*1000),
                 collected_at=end-timedelta(seconds=12), source_timestamp=None)
            for index, e in enumerate(EXCHANGES)
        ]
        report = compare("BTC/USDT", prices_for_alert, end)
        from distributed.telegram import Telegram
        telegram = Telegram()
        telegram.record(pg, [report], end)
        telegram.record(pg, [report], end)
        with pg.db() as db:
            alerts = db.execute("""SELECT state,kind FROM alerts
                                  WHERE symbol='BTC/USDT' AND window_end=%s""", (end,)).fetchall()
        assert sorted(r["kind"] for r in alerts) == ["report", "spread"]
        assert all(r["state"] == "dry_run" for r in alerts)
        assert client.get("/").status_code == 200
        assert client.get("/api/overview").json()["counts"]["price"] > 0
        result("telegram-dashboard", alerts=len(alerts), state="dry_run", api=200)
    finally:
        if database_disabled:
            database_available(True)
        for name in list(processes):
            stop(name)
        relay.shutdown()
        relay.server_close()
        client.close()
        if log_dir := os.getenv("SIM_LOG_DIR"):
            target = Path(log_dir)
            target.mkdir(parents=True, exist_ok=True)
            for path in tmp_path.glob("*.log"):
                (target / path.name).write_bytes(path.read_bytes())


def test_late_backfill_and_candle_duplicate():
    from distributed.analysis import historical

    pg = Postgres(DSN)
    pg.setup()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=2)).replace(second=0, microsecond=0)
    close_time = old + timedelta(seconds=59.999)
    candle = dict(symbol="ADA/USDT", interval="1m", open_time=old.isoformat(),
                  collected_at=now.isoformat(), source_timestamp=close_time.isoformat(),
                  latency_ms=10, price="1.1000", open="1", high="1.2", low="0.9")
    first = message("binance", "kline", "first-local-database", candle)
    second = message("binance", "kline", "recreated-local-database",
                     {**candle, "collected_at": (now+timedelta(seconds=1)).isoformat(), "latency_ms": 90})
    assert first["id"] == second["id"]
    assert pg.ingest(first) == pg.ingest(second) == first["id"]
    with pg.db() as db:
        assert db.execute("SELECT count(*) AS n FROM market_klines WHERE id=%s", (first["id"],)).fetchone()["n"] == 1

    for exchange, price in (("binance", "1.01"), ("okx", "1.02")):
        row = dict(symbol="ADA/USDT", price=price, collected_at=(old+timedelta(seconds=30)).isoformat(),
                   source_timestamp=None, latency_ms=10)
        pg.ingest(message(exchange, "price", "late-test-" + old.isoformat(), row))
    historical(pg, now, 60, 90)
    with pg.db() as db:
        result = db.execute("""SELECT data FROM price_comparisons WHERE symbol=%s AND window_end=%s""",
                            ("ADA/USDT", old+timedelta(minutes=1))).fetchone()["data"]
    assert result["valid"] == 2
    assert result["high_exchange"] == "okx"
