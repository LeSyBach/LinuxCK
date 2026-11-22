"""Run the production collector, scheduler, SQLite and publisher against HTTP fixtures."""
import asyncio
import logging
import os
import signal
import time
from pathlib import Path
from threading import Event, Thread

import httpx

from distributed.adapters import EXCHANGES, SpotAdapter, URLS
from distributed.broker import publisher
from distributed.local import Local
from distributed.node import Collector
from worker.scheduler import run_schedule

from .fixtures import fixture


def main():
    exchange = os.environ["EXCHANGE"]
    local = Local(os.environ["DATABASE_PATH"], exchange)
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    outage = Path(os.environ["FIXTURE_OUTAGE"])
    health = {}
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("pika").setLevel(logging.CRITICAL)
    thread = Thread(target=publisher, args=(os.environ["MASTER_ADDRESS"], local, EXCHANGES[exchange],
                                           stop, health), daemon=True)
    thread.start()

    async def run():
        transport = httpx.MockTransport(lambda request: fixture(exchange, outage.exists, request))
        async with httpx.AsyncClient(base_url=URLS[exchange], transport=transport) as http:
            adapter = SpotAdapter(exchange, http)
            adapter.api.attempts = 1
            collector = Collector(adapter, local, health)
            epoch = time.monotonic()
            def clock():
                return (time.monotonic() - epoch) * 60
            async def sleep(seconds):
                await asyncio.sleep(seconds / 60)
            task = asyncio.create_task(run_schedule(collector, dict(price=60, ticker=300, kline=300),
                                                    seconds=60*110, clock=clock, sleep=sleep))
            while not stop.is_set() and not task.done():
                await asyncio.wait({task}, timeout=0.1)
            if task.done():
                task.result()
            else:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    try:
        asyncio.run(run())
    finally:
        stop.set()
        thread.join(7)


if __name__ == "__main__":
    main()
