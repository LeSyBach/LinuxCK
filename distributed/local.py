import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from worker.models import utc_now
from .protocol import KINDS, message, validate

TABLES = dict(zip(KINDS, ("collected_prices", "collected_tickers", "collected_klines")))


class Local:
    def __init__(self, path, exchange):
        self.path = Path(path)
        self.exchange = exchange
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), exchange TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_runs (id TEXT PRIMARY KEY, kind TEXT, at TEXT, status TEXT);
                CREATE TABLE IF NOT EXISTS collection_errors (id INTEGER PRIMARY KEY, run_id TEXT, at TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS outbox_messages (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL, synced_at TEXT
                );
                CREATE INDEX IF NOT EXISTS pending ON outbox_messages(created_at) WHERE synced_at IS NULL;
            """)
            db.execute("INSERT OR IGNORE INTO identity VALUES(1,?)", (exchange,))
            if db.execute("SELECT exchange FROM identity").fetchone()[0] != exchange:
                raise ValueError("SQLite path belongs to a different exchange")
            for table in TABLES.values():
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL, collected_at TEXT NOT NULL, body TEXT NOT NULL
                )""")
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_time ON {table}(symbol,collected_at)")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def completed(self, job):
        with self.db() as db:
            row = db.execute("SELECT status FROM collection_runs WHERE id=?", (job.job_id,)).fetchone()
        return bool(row and row[0] == "success")

    def store(self, job, rows):
        count = 0
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("SELECT status FROM collection_runs WHERE id=?", (job.job_id,)).fetchone()
            if result and result[0] == "success":
                return 0
            for row in rows:
                body = validate(message(self.exchange, job.kind, job.job_id, row))
                encoded = json.dumps(body, separators=(",", ":"), allow_nan=False)
                key = body["id"]
                table = TABLES[job.kind]
                inserted = db.execute(f"INSERT OR IGNORE INTO {table} VALUES(?,?,?,?)",
                                      (key, row["symbol"], row["collected_at"], encoded)).rowcount
                if inserted:
                    db.execute("INSERT INTO outbox_messages VALUES(?,?,?,NULL)",
                               (key, encoded, row["collected_at"]))
                    count += 1
            db.execute("""INSERT INTO collection_runs VALUES(?,?,?,'success')
                        ON CONFLICT(id) DO UPDATE SET status='success',at=excluded.at""",
                       (job.job_id, job.kind, utc_now()))
        return count

    def error(self, job, error):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO collection_runs VALUES(?,?,?,'failed')",
                       (job.job_id, job.kind, utc_now()))
            db.execute("INSERT INTO collection_errors VALUES(NULL,?,?,?)",
                       (job.job_id, utc_now(), str(error)))

    def pending(self, limit=50):
        with self.db() as db:
            return list(db.execute("""SELECT id,body FROM outbox_messages WHERE synced_at IS NULL
                                     ORDER BY created_at,id LIMIT ?""", (limit,)))

    def receipt(self, key):
        with self.db() as db:
            db.execute("UPDATE outbox_messages SET synced_at=? WHERE id=? AND synced_at IS NULL",
                       (utc_now(), key))

    def status(self):
        with self.db() as db:
            stats = {kind: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for kind, table in TABLES.items()}
            pending = db.execute("SELECT count(*) FROM outbox_messages WHERE synced_at IS NULL").fetchone()[0]
            errors = db.execute("SELECT count(*) FROM collection_errors").fetchone()[0]
            runs = db.execute("SELECT count(*),max(CASE WHEN status='success' THEN at END) FROM collection_runs").fetchone()
            return dict(records=stats, pending=pending, errors=errors, runs=runs[0], last_collection=runs[1],
                        sqlite_bytes=self.path.stat().st_size)
