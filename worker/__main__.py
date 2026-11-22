import argparse
import asyncio
import json
import logging
from pathlib import Path

import httpx

from .binance_client import BASE_URL, BinanceClient
from .collector import Collector
from .config import Config
from .metrics import ProcessSampler, database_stats
from .models import utc_now
from .scheduler import run_schedule
from .storage import Storage, TABLES
from .worker_protocol import Job


async def live(args, storage):
    started = utc_now()
    config = Config.load(args.config)
    blocked = None
    outcomes = None
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=8) as http:
        api = BinanceClient(http)
        collector = Collector(api, config, storage)
        async with ProcessSampler() as sampler:
            try:
                await collector.preflight()
                await collector.btc_probe()
            except Exception as error:
                blocked = str(error)
                logging.error("Live preflight BLOCKED: %s", error)
                await asyncio.to_thread(storage.failure, Job("preflight-" + started.replace("+", "-"), "price"),
                                        started, utc_now(), sum(r["milliseconds"] for r in api.requests), error)
            if blocked is None:
                outcomes = await run_schedule(collector, config.periods, once=args.once or args.seconds is None,
                                              seconds=args.seconds)
    result = dict(mode="live", started=started, finished=utc_now(),
                  status="BLOCKED" if blocked else "FAIL" if outcomes["failed"] else "PASS",
                  blocked=blocked, outcomes=outcomes, process=sampler.summary(),
                  stats=database_stats(storage, api.requests), requests=api.requests)
    print(json.dumps(result, indent=2))
    return int(result["status"] != "PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("worker/trial/live.sqlite3"))
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    duration = collect.add_mutually_exclusive_group()
    duration.add_argument("--once", action="store_true")
    duration.add_argument("--seconds", type=int)
    stats = sub.add_parser("stats")
    stats.add_argument("--session", type=Path, help="Read HTTP timing from a saved collect JSON report")
    export = sub.add_parser("export")
    export.add_argument("table", choices=TABLES.values())
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "collect" and args.seconds is not None and args.seconds < 1:
        parser.error("--seconds must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    storage = Storage(args.database)
    if args.command == "collect":
        return asyncio.run(live(args, storage))
    if args.command == "stats":
        requests = ()
        if args.session is not None:
            requests = json.loads(args.session.read_text(encoding="utf-8"))["requests"]
        print(json.dumps(database_stats(storage, requests), indent=2))
    else:
        storage.export(args.table, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
