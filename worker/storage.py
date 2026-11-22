import csv
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .worker_protocol import KLINE_FIELDS, TICKER_FIELDS

TABLES = dict(price="price_snapshots", ticker="ticker_24h", kline="klines")
COLUMNS = {"price": ("price",), "ticker": ("price",) + TICKER_FIELDS, "kline": KLINE_FIELDS}
COMMON = ("exchange", "symbol", "source_timestamp", "collected_at", "worker_id",
          "collection_run_id", "status")


class Storage:
    def __init__(self, path, *, busy_timeout=0.3):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout = busy_timeout
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS crawl_runs (
                    run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL, elapsed_ms REAL NOT NULL, status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawler_errors (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES crawl_runs,
                    at TEXT NOT NULL, error_type TEXT NOT NULL, http_status INTEGER, message TEXT NOT NULL
                );
            """)
            for kind, table in TABLES.items():
                fields = ", ".join(f"{c} TEXT" if c == "source_timestamp" else f"{c} TEXT NOT NULL"
                                   for c in COMMON + COLUMNS[kind])
                unique = ("exchange, symbol, interval, open_time" if kind == "kline"
                          else "collection_run_id, symbol")
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    {fields}, UNIQUE ({unique}),
                    FOREIGN KEY (collection_run_id) REFERENCES crawl_runs (run_id)
                )""")
                db.execute(f"""CREATE INDEX IF NOT EXISTS {table}_symbol_time
                               ON {table} (symbol, collected_at)""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=self.busy_timeout)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def completed(self, job):
        with closing(self.connect()) as db:
            row = db.execute("SELECT kind, status FROM crawl_runs WHERE run_id=?", (job.job_id,)).fetchone()
        if row and row["kind"] != job.kind:
            raise ValueError("Job ID already belongs to a different kind")
        return bool(row and row["status"] == "success")

    def write(self, operation):
        for attempt in range(3):
            try:
                with closing(self.connect()) as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    operation(db)
                return
            except sqlite3.OperationalError as exc:
                if attempt == 2 or not any(word in str(exc) for word in ("locked", "busy")):
                    raise
                time.sleep(0.05 * 2 ** attempt)

    def save(self, job, started, finished, elapsed, results):
        def operation(db):
            row = db.execute("SELECT kind, status FROM crawl_runs WHERE run_id=?", (job.job_id,)).fetchone()
            if row and row["kind"] != job.kind:
                raise ValueError("Job ID already belongs to a different kind")
            if row and row["status"] == "success":
                return
            db.execute("""INSERT INTO crawl_runs VALUES (?, ?, ?, ?, ?, 'success')
                          ON CONFLICT(run_id) DO UPDATE SET finished_at=excluded.finished_at,
                          elapsed_ms=excluded.elapsed_ms, status='success'""",
                       (job.job_id, job.kind, started, finished, elapsed))
            table = TABLES[job.kind]
            columns = COMMON + COLUMNS[job.kind]
            placeholders = ", ".join("?" for _ in columns)
            unique = ("exchange, symbol, interval, open_time" if job.kind == "kline"
                      else "collection_run_id, symbol")
            expected = []
            for result in results:
                if result.job_id != job.job_id or result.kind != job.kind:
                    raise ValueError("Result does not match collection job")
                msg = result.to_message()
                record = {**msg["data"], **msg}
                values = tuple(record[key] for key in columns)
                cursor = db.execute(f"""INSERT INTO {table} ({', '.join(columns)})
                    VALUES ({placeholders}) ON CONFLICT ({unique}) DO NOTHING""", values)
                if cursor.rowcount:
                    expected.append(values)
            stored = db.execute(f"""SELECT {', '.join(columns)} FROM {table}
                                    WHERE collection_run_id=?""", (job.job_id,))
            if sorted(map(tuple, stored)) != sorted(expected):
                raise ValueError("SQLite round-trip mismatch")
        self.write(operation)

    def failure(self, job, started, finished, elapsed, error):
        def operation(db):
            db.execute("""INSERT INTO crawl_runs VALUES (?, ?, ?, ?, ?, 'failed')
                          ON CONFLICT(run_id) DO NOTHING""",
                       (job.job_id, job.kind, started, finished, elapsed))
            response = getattr(error, "response", None)
            db.execute("INSERT INTO crawler_errors VALUES (NULL, ?, ?, ?, ?, ?)",
                       (job.job_id, finished, type(error).__name__,
                        response.status_code if response is not None else None, str(error)))
        self.write(operation)

    def export(self, table, destination):
        if table not in TABLES.values():
            raise ValueError("Unknown export table")
        with closing(self.connect()) as db, Path(destination).open("w", newline="", encoding="utf-8") as out:
            cursor = db.execute(f"SELECT * FROM {table} ORDER BY collected_at, symbol")
            writer = csv.writer(out)
            writer.writerow(column[0] for column in cursor.description)
            writer.writerows(cursor)

    def sample(self, table, limit=5):
        if table not in TABLES.values():
            raise ValueError("Unknown sample table")
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                f"SELECT * FROM {table} ORDER BY collected_at DESC, symbol LIMIT ?", (limit,)
            )]
