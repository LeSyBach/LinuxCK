from datetime import timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

from .adapters import EXCHANGES


def compare(symbol, rows, end, window_seconds=60, freshness=90):
    start = end - timedelta(seconds=window_seconds)
    selected = {}
    for row in rows:
        if row["symbol"] != symbol or row["exchange"] not in EXCHANGES:
            continue
        collected = row["collected_at"]
        if not start <= collected <= end:
            continue
        current = selected.get(row["exchange"])
        if current is None or collected > current["collected_at"]:
            selected[row["exchange"]] = row
    sources = {}
    for exchange in EXCHANGES:
        candidate = selected.get(exchange)
        if candidate is None:
            sources[exchange] = {"status": "missing"}
            continue
        collected, source = candidate["collected_at"], candidate["source_timestamp"]
        effective = min(collected, source) if source else collected
        age = (end - effective).total_seconds()
        implausible = source is not None and source > collected + timedelta(seconds=5)
        sources[exchange] = dict(
            status="stale" if age > freshness or implausible else "valid",
            price=str(candidate["price"]), collected_at=collected.isoformat(),
            source_timestamp=source.isoformat() if source else None, age_seconds=age,
        )
    values = sorted((Decimal(value["price"]), exchange) for exchange, value in sources.items()
                    if value["status"] == "valid")
    report = dict(symbol=symbol, start=start.isoformat(), end=end.isoformat(), sources=sources,
                  valid=len(values), missing_ratio=sum(v["status"] == "missing" for v in sources.values()) / 3,
                  stale_ratio=sum(v["status"] == "stale" for v in sources.values()) / 3)
    if len(values) >= 2:
        low, low_exchange = values[0]
        high, high_exchange = values[-1]
        report.update(low=str(low), high=str(high), low_exchange=low_exchange,
                      high_exchange=high_exchange, mean=str(sum(p for p, _ in values) / len(values)),
                      spread=str(high-low), spread_percent=str((high-low) / low * 100))
    return report


def historical(postgres, now, window_seconds, freshness):
    floor = int(now.timestamp()) // window_seconds * window_seconds
    closed = now.fromtimestamp(floor, tz=now.tzinfo)
    with postgres.db() as db:
        pending = db.execute("""SELECT symbol,collected_at FROM comparison_pending
                               WHERE collected_at < %s ORDER BY collected_at
                               LIMIT 500 FOR UPDATE SKIP LOCKED""", (closed,)).fetchall()
        groups = {}
        for row in pending:
            start_s = int(row["collected_at"].timestamp()) // window_seconds * window_seconds
            groups.setdefault((row["symbol"], start_s), []).append(row["collected_at"])
        for (symbol, start_s), timestamps in groups.items():
            start = now.fromtimestamp(start_s, tz=now.tzinfo)
            end = start + timedelta(seconds=window_seconds)
            rows = db.execute("""SELECT exchange,symbol,price,collected_at,source_timestamp
                                 FROM market_prices WHERE symbol=%s AND collected_at >= %s
                                 AND collected_at < %s ORDER BY collected_at,id""",
                              (symbol, start, end)).fetchall()
            report = compare(symbol, rows, end, window_seconds, freshness)
            db.execute("""INSERT INTO price_comparisons VALUES(%s,%s,%s)
                          ON CONFLICT(symbol,window_end) DO UPDATE SET data=excluded.data
                          WHERE price_comparisons.data IS DISTINCT FROM excluded.data""",
                       (symbol, end, Jsonb(report)))
            db.execute("DELETE FROM comparison_pending WHERE symbol=%s AND collected_at=ANY(%s)",
                       (symbol, timestamps))
        return [row["data"] for row in db.execute("""
            SELECT data FROM price_comparisons WHERE window_end BETWEEN %s AND %s
            ORDER BY window_end,symbol
        """, (now - timedelta(minutes=2), now)).fetchall()]
