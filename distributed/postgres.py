from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .adapters import EXCHANGES
from .protocol import utc, validate

TABLES = dict(price="market_prices", ticker="market_tickers", kline="market_klines")


class Postgres:
    def __init__(self, dsn):
        self.dsn = dsn

    def db(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=3,
                               options="-c statement_timeout=6000")

    def setup(self):
        with self.db() as db:
            db.execute(Path(__file__).with_name("schema.sql").read_text())

    def ingest(self, message):
        body = validate(message)
        row = body["data"]
        table = TABLES[body["kind"]]
        with self.db() as db:
            inserted = db.execute("""INSERT INTO received_messages(id,worker_id,body) VALUES(%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING id""",
                                  (body["id"], body["worker_id"], Jsonb(body))).fetchone()
            if inserted:
                db.execute(f"""INSERT INTO {table}
                    (id,exchange,symbol,price,collected_at,source_timestamp,data) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                           (body["id"], body["exchange"], row["symbol"], row["price"],
                            row["collected_at"], row["source_timestamp"], Jsonb(row)))
                if body["kind"] == "price":
                    db.execute("INSERT INTO comparison_pending VALUES(%s,%s) ON CONFLICT DO NOTHING",
                               (row["symbol"], row["collected_at"]))
            else:
                prior = db.execute("SELECT body FROM received_messages WHERE id=%s", (body["id"],)).fetchone()
                prior_body = prior["body"]
                same_payload = prior_body == body
                if body["kind"] == "kline":
                    # A rebuilt SQLite outbox can rediscover the same closed candle.
                    # Collection timing and transport latency are local observation metadata.
                    ignored = {"collected_at", "latency_ms"}
                    current_candle = {key: value for key, value in row.items() if key not in ignored}
                    saved_candle = {key: value for key, value in prior_body["data"].items() if key not in ignored}
                    same_payload = current_candle == saved_candle
                if not same_payload:
                    raise ValueError("Conflicting payload for an existing message ID")
        return body["id"]

    def heartbeat(self, body):
        if body["worker_id"] != EXCHANGES[body["exchange"]]:
            raise ValueError("Invalid heartbeat identity")
        seen = utc(body["at"])
        with self.db() as db:
            db.execute("""UPDATE workers SET last_heartbeat=LEAST(%s,now()),data=%s WHERE id=%s
                          AND (last_heartbeat IS NULL OR last_heartbeat<%s)""",
                       (seen, Jsonb(body["stats"]), body["worker_id"], seen))

    def event(self, event, detail):
        with self.db() as db:
            db.execute("INSERT INTO system_events(event,detail) VALUES(%s,%s)", (event, detail))
