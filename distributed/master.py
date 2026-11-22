import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread

import psutil
from fastapi import FastAPI, Query, Response
from fastapi.responses import HTMLResponse

from .analysis import historical
from .broker import consumer
from .postgres import Postgres, TABLES
from .telegram import Telegram

LOG = logging.getLogger(__name__)


def create_app(postgres=None, address=None):
    pg = postgres or Postgres(os.environ["POSTGRES_DSN"])
    address = address or os.environ["MASTER_ADDRESS"]
    watchdog = max(10, int(os.getenv("WORKER_TIMEOUT", "25")))
    window = int(os.getenv("COMPARISON_WINDOW", "60"))
    if window not in (60, 300):
        raise ValueError("COMPARISON_WINDOW must be 60 or 300")
    freshness = max(1, int(os.getenv("FRESHNESS_SECONDS", "90")))
    telegram = Telegram()
    process = psutil.Process()
    process.cpu_percent()

    def summarize(stop):
        while not stop.is_set():
            try:
                instant = datetime.now(timezone.utc)
                reports = historical(pg, instant, window, freshness)
                telegram.record(pg, reports, instant)
            except Exception as error:
                LOG.warning("Analysis unavailable (%s)", type(error).__name__)
            stop.wait(5)

    @asynccontextmanager
    async def lifespan(app):
        logging.getLogger("pika").setLevel(logging.CRITICAL)
        pg.setup()
        stop = Event()
        threads = [Thread(target=consumer, args=(address, pg, stop), daemon=True),
                   Thread(target=summarize, args=(stop,), daemon=True)]
        for thread in threads:
            thread.start()
        try:
            yield
        finally:
            stop.set()
            for thread in threads:
                thread.join(7)

    api = FastAPI(title="LinuxCK Market Monitor", lifespan=lifespan)

    @api.get("/", response_class=HTMLResponse)
    def dashboard():
        return Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")

    @api.get("/health")
    def health(response: Response):
        try:
            with pg.db() as db:
                db.execute("SELECT 1")
            return {"status": "ok"}
        except Exception:
            response.status_code = 503
            return {"status": "database unavailable"}

    @api.get("/api/overview")
    def overview(limit: int = Query(60, ge=1, le=250)):
        now = datetime.now(timezone.utc)
        with pg.db() as db:
            workers = db.execute("SELECT * FROM workers ORDER BY id").fetchall()
            latest = db.execute("""SELECT DISTINCT ON (symbol,exchange) symbol,exchange,price,collected_at,source_timestamp
                                 FROM market_prices ORDER BY symbol,exchange,collected_at DESC,id DESC""").fetchall()
            history = db.execute("""SELECT symbol,exchange,price,collected_at FROM market_prices
                                    ORDER BY collected_at DESC,id LIMIT %s""", (limit,)).fetchall()
            reports = db.execute("SELECT data FROM price_comparisons ORDER BY window_end DESC,symbol LIMIT %s",
                                 (limit,)).fetchall()
            alerts = db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 20").fetchall()
            counts = {kind: db.execute(f"SELECT count(*) FROM {table}").fetchone()["count"]
                      for kind, table in TABLES.items()}
        for item in workers:
            beat = item["last_heartbeat"]
            item["online"] = beat is not None and now - beat <= timedelta(seconds=watchdog)
        for row in latest + history:
            row["price"] = str(row["price"])
        disk = psutil.disk_usage("/")
        traffic = psutil.net_io_counters()
        return dict(at=now, workers=workers, online=sum(w["online"] for w in workers),
                    latest=latest, history=history, counts=counts, alerts=alerts,
                    comparisons=[r["data"] for r in reports],
                    master=dict(cpu_percent=process.cpu_percent(), rss_mib=round(process.memory_info().rss/2**20, 2),
                                disk_percent=disk.percent, network_rx_bytes=traffic.bytes_recv,
                                network_tx_bytes=traffic.bytes_sent))

    return api
