import asyncio
from contextlib import closing
from statistics import mean

import psutil

from .storage import TABLES


def database_stats(storage, requests=()):
    with closing(storage.connect()) as db:
        tables = {}
        for table in TABLES.values():
            tables[table] = dict(db.execute(f"SELECT symbol, count(*) FROM {table} GROUP BY symbol"))
        runs = dict(db.execute("SELECT status, count(*) FROM crawl_runs GROUP BY status"))
        first, last = db.execute("SELECT min(started_at), max(finished_at) FROM crawl_runs").fetchone()
        errors = db.execute("SELECT count(*) FROM crawler_errors").fetchone()[0]
        journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
    sizes = [storage.path, storage.path.with_name(storage.path.name + "-wal")]
    return dict(tables=tables, total=sum(sum(values.values()) for values in tables.values()),
                runs=runs, total_runs=sum(runs.values()), start_utc=first, end_utc=last,
                errors=errors, journal_mode=journal_mode, integrity=integrity,
                database_bytes=storage.path.stat().st_size,
                database_plus_wal_bytes=sum(path.stat().st_size for path in sizes if path.exists()),
                requests=len(requests), request_success=sum(row["error"] is None for row in requests),
                request_failed=sum(row["error"] is not None for row in requests),
                response_ms_mean=round(mean(row["milliseconds"] for row in requests), 2) if requests else None)


class ProcessSampler:
    def __init__(self):
        self.process = psutil.Process()
        self.cpu_sum = 0.0
        self.cpu_samples = 0
        self.rss_sum = 0
        self.rss_peak = 0
        self.rss_samples = 0

    def take_sample(self, *, cpu=True):
        if cpu:
            self.cpu_sum += self.process.cpu_percent()
            self.cpu_samples += 1
        rss = self.process.memory_info().rss
        self.rss_sum += rss
        self.rss_peak = max(self.rss_peak, rss)
        self.rss_samples += 1

    async def __aenter__(self):
        self.process.cpu_percent()
        self.take_sample(cpu=False)
        self.task = asyncio.create_task(self.sample())
        return self

    async def sample(self):
        while True:
            await asyncio.sleep(1)
            self.take_sample()

    async def __aexit__(self, *args):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.take_sample()

    def summary(self):
        return dict(cpu_percent_mean=round(self.cpu_sum / self.cpu_samples, 3),
                    rss_mib_mean=round(self.rss_sum / self.rss_samples / 2**20, 2),
                    rss_mib_peak=round(self.rss_peak / 2**20, 2), rss_samples=self.rss_samples)
