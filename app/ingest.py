"""BODACC -> bodacc_notices (idempotent upsert), then RULE matching -> cases + case_events."""
from __future__ import annotations

from datetime import timedelta

from app import bodacc
from app.cases import match_customers, today
from app.db import Jsonb, transaction

# Raw fields kept per notice: enough to re-parse, without the bulky unused sections.
RAW_FIELDS = ("id", "dateparution", "familleavis", "typeavis", "parutionavisprecedent", "numerodepartement",
              "tribunal", "commercant", "ville", "cp", "registre", "listepersonnes", "jugement", "url_complete")
EXPORT_THRESHOLD_DAYS = 3
BATCH = 500

UPSERT = """
insert into bodacc_notices (id, siren, denomination, is_legal_person, ville, cp, departement, tribunal,
  date_parution, jugement_famille, jugement_nature, jugement_date, event_kind, procedure, complement,
  officers, url, raw)
values (%(id)s, %(siren)s, %(denomination)s, %(is_legal_person)s, %(ville)s, %(cp)s, %(departement)s,
  %(tribunal)s, %(date_parution)s, %(jugement_famille)s, %(jugement_nature)s, %(jugement_date)s,
  %(event_kind)s, %(procedure)s, %(complement)s, %(officers)s, %(url)s, %(raw)s)
on conflict (id) do update set
  siren = excluded.siren, denomination = excluded.denomination, is_legal_person = excluded.is_legal_person,
  jugement_famille = excluded.jugement_famille, jugement_nature = excluded.jugement_nature,
  jugement_date = excluded.jugement_date, event_kind = excluded.event_kind, procedure = excluded.procedure,
  complement = excluded.complement, officers = excluded.officers, raw = excluded.raw, last_seen_at = now()
returning (xmax = 0) as inserted
"""


def _row(rec: dict) -> dict | None:
    p = bodacc.parse_notice(rec)
    if not p["id"] or not p["date_parution"]:
        return None
    p["officers"] = Jsonb(p["officers"])
    p["raw"] = Jsonb({k: rec.get(k) for k in RAW_FIELDS if rec.get(k) is not None})
    return p


def upsert_records(conn, records: list[dict]) -> tuple[int, int]:
    rows = [r for r in (_row(rec) for rec in records) if r]
    inserted = updated = 0
    with conn.cursor() as cur:
        for i in range(0, len(rows), BATCH):
            cur.executemany(UPSERT, rows[i:i + BATCH], returning=True)
            while True:
                res = cur.fetchone()
                if res is not None:
                    inserted += int(res["inserted"])
                    updated += int(not res["inserted"])
                if not cur.nextset():
                    break
    return inserted, updated


def fetch_recent(days: int) -> list[dict]:
    since = today() - timedelta(days=days)
    if days > EXPORT_THRESHOLD_DAYS:
        return bodacc.export_collective(since)
    out: list[dict] = []
    while True:
        page = bodacc.fetch_collective_page(since, limit=100, offset=len(out))
        out.extend(page)
        if len(page) < 100 or len(out) >= 9900:
            return out


def ingest(days: int = 45) -> dict:
    with transaction() as conn:
        run = conn.execute("insert into ingest_runs (since) values (%s) returning id",
                           (today() - timedelta(days=days),)).fetchone()
    try:
        records = fetch_recent(days)
        with transaction() as conn:
            inserted, updated = upsert_records(conn, records)
            new_cases = match_customers(conn)
    except Exception as e:
        with transaction() as conn:
            conn.execute("update ingest_runs set finished_at = now(), error = %s where id = %s",
                         (f"{type(e).__name__}: {e}"[:500], run["id"]))
        raise
    with transaction() as conn:
        conn.execute("update ingest_runs set finished_at = now(), fetched = %s, inserted = %s, updated = %s "
                     "where id = %s", (len(records), inserted, updated, run["id"]))
    return {"fetched": len(records), "inserted": inserted, "updated": updated, "new_cases": new_cases}


def store_history(conn, siren: str) -> list[dict]:
    """Fetch the full BODACC history of one SIREN from the live API and upsert it."""
    recs = bodacc.fetch_history(siren)
    if recs:
        upsert_records(conn, recs)
    return recs
