import asyncio
import logging
import math
import time
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .models import utc_now

BASE_URL = "https://data-api.binance.vision"
LOG = logging.getLogger(__name__)


def retry_delay(header, default):
    if header:
        try:
            seconds = float(header)
            if math.isfinite(seconds):
                return max(default, seconds)
        except ValueError:
            try:
                until = parsedate_to_datetime(header)
                return max(default, (until - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return default


class BinanceClient:
    def __init__(self, client: httpx.AsyncClient, *, sleep=asyncio.sleep, attempts=3, prefix="/api/v3/", label="Binance", history_limit=None):
        self.client = client
        self.prefix = prefix
        self.sleep = sleep
        self.attempts = attempts
        self.label = label
        self.requests = [] if history_limit is None else deque(maxlen=history_limit)
        self.request_count = 0
        self.request_errors = 0
        self.cooldown_until = 0.0
        self.access_denied = False

    async def get(self, endpoint, **params):
        if self.access_denied:
            raise RuntimeError(f"{self.label} denied access earlier in this session")
        if time.monotonic() < self.cooldown_until:
            raise RuntimeError(f"{self.label} rate-limit cooldown active")
        for attempt in range(self.attempts):
            start = time.monotonic()
            status = None
            delay = 2 ** attempt
            result = None
            error = None
            retry = False
            try:
                response = await self.client.get(self.prefix + endpoint, params=params)
                status = response.status_code
                response.raise_for_status()
                result = response.json()
            except httpx.HTTPStatusError as exc:
                error = exc
                if status in (403, 451):
                    self.access_denied = True
                if status in (418, 429):
                    delay = retry_delay(response.headers.get("Retry-After"), 120 if status == 418 else 60)
                    self.cooldown_until = time.monotonic() + delay
                retry = status >= 500 or status == 429 and delay <= 90
            except httpx.TransportError as exc:
                error = exc
                retry = True
            except ValueError as exc:
                error = exc
            event = dict(at=utc_now(), endpoint=endpoint, status=status,
                         milliseconds=round((time.monotonic() - start) * 1000, 2),
                         error=str(error) if error is not None else None)
            self.requests.append(event)
            self.request_count += 1
            self.request_errors += int(error is not None)
            LOG.info("%s", event)
            if error is None:
                return result
            if not retry or attempt + 1 == self.attempts:
                raise error
            await self.sleep(delay)
