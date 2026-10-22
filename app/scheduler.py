"""Autonomous loop: every FORCLOS_SYNC_MINUTES, pull the latest BODACC notices, apply the exact-SIREN rule,
and start an agent investigation for every case that ingestion just opened. No one has to click.
A Postgres advisory lock makes sure only one replica syncs at a time."""
from __future__ import annotations

import logging
import os
import threading
import time

from app import db, runs
from app.ingest import ingest

log = logging.getLogger("forclos.scheduler")
SYNC_MINUTES = int(os.getenv("FORCLOS_SYNC_MINUTES", "30"))
SYNC_DAYS = 2                    # BODACC publishes daily; two days covers a missed run
FIRST_SYNC_DELAY_S = 90
LOCK_KEY = 4_242_026             # pg_advisory_lock key for the sync job
_started = False


def sync(trigger: str = "schedule", days: int = SYNC_DAYS) -> dict:
    """One sync: ingest, rule matching, then an agent run per newly opened case."""
    with db.pool().connection() as conn:
        if not conn.execute("select pg_try_advisory_lock(%s) as ok", (LOCK_KEY,)).fetchone()["ok"]:
            return {"skipped": "another sync is running"}
        try:
            result = ingest(days, trigger=trigger)
            started = []
            for case_id in result["new_case_ids"]:
                case = db.query_one("select customer_id from cases where id = %s", (case_id,))
                try:
                    started.append(runs.investigate_case(
                        case_id, case["customer_id"], "New BODACC notice matched by exact SIREN during the automatic sync."))
                except runs.RunLimitError:
                    log.warning("run limit reached; case %s left for the next sync", case_id)
            db.execute("update ingest_runs set investigations = %s where id = %s", (len(started), result["ingest_run_id"]))
            return {**result, "investigations_started": len(started)}
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))


def _loop() -> None:
    time.sleep(FIRST_SYNC_DELAY_S)
    while True:
        try:
            log.info("scheduled sync: %s", sync())
        except Exception:
            log.exception("scheduled sync failed")
        time.sleep(SYNC_MINUTES * 60)


def start() -> None:
    global _started
    if _started or os.getenv("FORCLOS_SCHEDULER", "on") == "off":
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="bodacc-sync").start()
    log.info("BODACC sync every %s minutes", SYNC_MINUTES)
