"""Load the Aiven for PostgreSQL database used by the deployed app: schema, 45 days of BODACC notices,
the frozen demo seed, and the latest benchmark results computed locally.
Usage: python scripts/sync_to_aiven.py   (reads AIVEN_DATABASE_URL and DATABASE_URL from .env)"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
LOCAL_URL = os.environ["DATABASE_URL"]
AIVEN_URL = os.environ.get("AIVEN_DATABASE_URL", "")
if not AIVEN_URL or "PASSWORD@" in AIVEN_URL:
    sys.exit("Set AIVEN_DATABASE_URL in .env (Aiven console > service > Overview > Service URI).")
os.environ["DATABASE_URL"] = AIVEN_URL  # app.db reads it on first use
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app import db  # noqa: E402
from app.demo import load_seed  # noqa: E402
from app.ingest import ingest  # noqa: E402


def copy_benchmarks() -> int:
    with psycopg.connect(LOCAL_URL, row_factory=dict_row) as src:
        rows = src.execute("""select distinct on (split, system) run_at, split, system, metrics, details
                              from benchmark_runs order by split, system, id desc""").fetchall()
    with db.transaction() as conn:
        for r in rows:
            conn.execute("insert into benchmark_runs (run_at, split, system, metrics, details) values (%s,%s,%s,%s,%s)",
                         (r["run_at"], r["split"], r["system"], db.Jsonb(r["metrics"]), db.Jsonb(r["details"])))
    return len(rows)


if __name__ == "__main__":
    db.init_schema()
    print("schema ok")
    print("ingest", ingest(45))
    print("seed", load_seed())
    print("benchmark rows copied", copy_benchmarks())
    print("health", db.query_one("select (select count(*) from bodacc_notices) as notices, "
                                 "(select count(*) from cases) as cases"))
