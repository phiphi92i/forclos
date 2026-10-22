"""First boot on an empty database (e.g. a fresh Aiven for PostgreSQL service): load the frozen demo seed,
the recorded benchmark runs, and 45 days of BODACC. Runs in a background thread so the HTTP port is up at
once; a Postgres advisory lock keeps two replicas from doing it twice. Every step is skipped if done."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from app import db, scheduler
from app.demo import load_seed

log = logging.getLogger("forclos.bootstrap")
BENCHMARKS = Path(__file__).resolve().parents[1] / "data" / "benchmark_results.json"
LOCK_KEY = 4_242_027
BACKFILL_DAYS = 45
MIN_NOTICES = 5000


def load_benchmarks() -> int:
    """Recorded live runs of benchmark/run.py (labelled as recorded in the UI)."""
    rows = json.loads(BENCHMARKS.read_text())
    with db.transaction() as conn:
        for r in rows:
            conn.execute("""insert into benchmark_runs (run_at, split, system, metrics, details)
                            values (%s, %s, %s, %s, %s)""",
                         (r["run_at"], r["split"], r["system"], db.Jsonb(r["metrics"]), db.Jsonb(r["details"])))
    return len(rows)


def bootstrap() -> None:
    with db.pool().connection() as conn:
        if not conn.execute("select pg_try_advisory_lock(%s) as ok", (LOCK_KEY,)).fetchone()["ok"]:
            return
        try:
            if not db.query_one("select 1 from customers where dataset = 'demo' limit 1"):
                log.info("demo seed: %s", load_seed())
            if not db.query_one("select 1 from benchmark_runs limit 1") and BENCHMARKS.exists():
                log.info("benchmark runs loaded: %s", load_benchmarks())
            if db.query_one("select count(*) as n from bodacc_notices")["n"] < MIN_NOTICES:
                log.info("BODACC backfill: %s", scheduler.sync(trigger="setup", days=BACKFILL_DAYS))
        except Exception:
            log.exception("bootstrap failed")
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))


def start() -> None:
    threading.Thread(target=bootstrap, daemon=True, name="bootstrap").start()
