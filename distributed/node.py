import argparse
import asyncio
import json
import logging
import os
import signal
import time
from threading import Event, Thread

import httpx

from worker.metrics import ProcessSampler
from worker.models import utc_now
from worker.scheduler import run_schedule
from worker.worker_protocol import Job
from .adapters import EXCHANGES, URLS, SpotAdapter
from .broker import publisher
from .local import Local

LOG = logging.getLogger(__name__)


class Collector:
    def __init__(self, adapter, store, health):
        self.adapter, self.store, self.health = adapter, store, health

    async def run(self, job):
        try:
            if self.store.completed(job):
                return True
            rows = await asyncio.wait_for(self.adapter.collect(job.kind), timeout=45)
            count = self.store.store(job, rows)
            self.health["market_status"] = "collecting"
            LOG.info("%s %s stored %s rows", utc_now(), job.kind, count)
            return True
        except Exception as error:
            self.store.error(job, error)
            self.health["market_status"] = "blocked" if self.adapter.api.access_denied else "error"
            LOG.error("%s %s: %s", utc_now(), job.kind, error)
            return False
        finally:
            api = self.adapter.api
            self.health.update(requests=api.request_count, api_errors=api.request_errors)


async def run(args, local, stop, health):
    exchange = local.exchange
    options = dict(base_url=URLS[exchange], timeout=6)
    # Optional injection is confined to tests that instantiate SpotAdapter directly.
    async with httpx.AsyncClient(**options) as http:
        adapter = SpotAdapter(exchange, http)
        collector = Collector(adapter, local, health)
        periods = dict(price=int(os.getenv("COLLECT_INTERVAL", "60")),
                       ticker=int(os.getenv("TICKER_INTERVAL", "300")),
                       kline=int(os.getenv("KLINE_INTERVAL", "300")))
        if any(value < minimum for value, minimum in zip(periods.values(), (60, 300, 300))):
            raise ValueError("Intervals below 60/300/300 seconds")
        async with ProcessSampler() as sampler:
            def make_job(kind):
                period = periods[kind]
                return Job(f"{kind}-{period}-{int(time.time()) // period}", kind)

            task = asyncio.create_task(run_schedule(collector, periods, seconds=args.seconds,
                                                    once=args.once, make_job=make_job))
            while not task.done() and not stop.is_set():
                await asyncio.wait({task}, timeout=0.5)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if args.flush and not stop.is_set():
                start = asyncio.get_running_loop().time()
                while local.pending(1) and asyncio.get_running_loop().time() - start < args.flush and not stop.is_set():
                    await asyncio.sleep(0.25)
        return dict(exchange=exchange, at=utc_now(), **local.status(), performance=sampler.summary(),
                    requests=list(adapter.api.requests), request_count=adapter.api.request_count,
                    request_errors=adapter.api.request_errors,
                    outcome=task.result() if not task.cancelled() else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--flush", type=int, default=0)
    args = parser.parse_args()
    exchange = os.environ["EXCHANGE"]
    worker_id = os.environ.get("WORKER_ID", EXCHANGES[exchange])
    if worker_id != EXCHANGES[exchange]:
        parser.error("Worker ID and exchange do not match")
    address = os.environ.get("MASTER_ADDRESS")
    local = Local(os.getenv("DATABASE_PATH", f"worker/trial/{exchange}.sqlite3"), exchange)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("pika").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    health = {}
    thread = Thread(target=publisher, args=(address, local, worker_id, stop, health), daemon=True) if address else None
    if thread:
        thread.start()
    try:
        result = asyncio.run(run(args, local, stop, health))
        print(json.dumps(result, indent=2), flush=True)
        return int(bool(result["outcome"] and result["outcome"]["failed"]))
    finally:
        stop.set()
        if thread:
            thread.join(timeout=7)


if __name__ == "__main__":
    raise SystemExit(main())
