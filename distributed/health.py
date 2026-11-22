import os
from datetime import datetime, timezone

from .local import Local
from .protocol import utc


if __name__ == "__main__":
    stats = Local(os.environ["DATABASE_PATH"], os.environ["EXCHANGE"]).status()
    last = stats["last_collection"]
    maximum = 120 + int(os.getenv("COLLECT_INTERVAL", "60"))
    raise SystemExit(0 if last and (datetime.now(timezone.utc) - utc(last)).total_seconds() < maximum else 1)
