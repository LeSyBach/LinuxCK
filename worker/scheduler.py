import asyncio
import time
import uuid

from .worker_protocol import Job


async def run_schedule(collector, periods, *, seconds=None, once=False,
                       clock=time.monotonic, sleep=asyncio.sleep, make_job=None):
    if make_job is None:
        def make_job(kind):
            return Job(uuid.uuid4().hex, kind)
    start = clock()
    deadline = start + seconds if seconds is not None else float("inf")
    due = dict.fromkeys(periods, start)
    outcomes = dict(success=0, failed=0, cycles=0)
    while clock() < deadline:
        wake = min(due.values())
        if wake >= deadline:
            break
        if wake > clock():
            await sleep(wake - clock())
        if clock() >= deadline:
            break
        eligible = [kind for kind in periods if due[kind] <= clock()]
        if not eligible:
            continue
        outcomes["cycles"] += 1
        for kind in eligible:
            if clock() >= deadline:
                break
            due[kind] = clock() + periods[kind]
            ok = await collector.run(make_job(kind))
            outcomes["success" if ok else "failed"] += 1
        if once:
            break
    return outcomes
