"""Data routes: ingestion, live feed, dashboard, demo reset, benchmark."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db, runs
from app.cases import CASE_KINDS, today
from app.demo import load_seed
from app.scheduler import SYNC_MINUTES, sync

router = APIRouter(prefix="/api")


class IngestIn(BaseModel):
    days: int = Field(45, ge=1, le=90)


@router.post("/ingest")
def post_ingest(body: IngestIn) -> dict:
    try:
        return sync(trigger="manual", days=body.days)
    except Exception as e:
        raise HTTPException(502, f"BODACC ingestion failed: {type(e).__name__}") from e


@router.get("/feed")
def feed(limit: int = 30) -> list[dict]:
    limit = max(1, min(limit, 100))
    return db.query(
        """with matched as (
             select n.id, c.id as customer_id from bodacc_notices n
             join customers c on c.dataset = 'demo' and n.siren = coalesce(c.verified_siren, c.crm_siren)
             where n.event_kind = any(%(kinds)s))
           select n.id, n.siren, n.denomination, n.ville, n.cp, n.date_parution, n.event_kind, n.procedure,
                  n.tribunal, m.customer_id as matched_customer_id
           from bodacc_notices n left join matched m on m.id = n.id
           where n.event_kind = any(%(kinds)s) and n.is_legal_person
             and (m.customer_id is not null or n.id in (
                  select id from bodacc_notices where event_kind = any(%(kinds)s) and is_legal_person
                  order by date_parution desc, id desc limit %(limit)s))
           order by n.date_parution desc, n.id desc""",
        {"kinds": list(CASE_KINDS), "limit": limit})


@router.get("/dashboard")
def dashboard() -> dict:
    cases = db.query(
        """select c.id, c.siren, c.status, c.current_procedure as procedure, c.claim_deadline,
                  c.declare_cents, c.exposure_cents, c.opening_judgment_date,
                  json_build_object('id', cu.id, 'crm_name', cu.crm_name) as customer,
                  coalesce(a.denomination, (select denomination from bodacc_notices where siren = c.siren
                           order by date_parution desc limit 1)) as denomination
           from cases c join customers cu on cu.id = c.customer_id
           left join bodacc_notices a on a.id = c.anchor_notice_id
           where cu.dataset = 'demo'
           order by c.claim_deadline nulls last, c.id""")
    t = today()
    for c in cases:
        c["days_left"] = (c["claim_deadline"] - t).days if c["claim_deadline"] else None
    live = [c for c in cases if c["status"] != "CLOSED"]
    upcoming = [c for c in live if c["claim_deadline"] and c["claim_deadline"] >= t]
    nearest = min(upcoming, key=lambda c: c["claim_deadline"]) if upcoming else None
    customers = db.query(
        """select cu.id, cu.crm_name, cu.crm_siren, cu.postal_code, cu.city, cu.identity_status, cu.verified_siren,
                  cu.payment_terms, exists (select 1 from cases where customer_id = cu.id) as has_case,
                  (select coalesce(sum(amount_cents - paid_cents), 0) from invoices
                   where customer_id = cu.id and amount_cents > paid_cents) as outstanding_cents
           from customers cu where cu.dataset = 'demo' order by cu.id""")
    last_sync = db.query_one(
        """select finished_at, trigger, inserted, new_cases, investigations from ingest_runs
           where finished_at is not null and error is null order by id desc limit 1""")
    return {
        "last_sync": last_sync, "sync_every_minutes": SYNC_MINUTES,
        "latest_notice": db.query_one("select max(date_parution) as d from bodacc_notices")["d"],
        "exposure_cents": sum(c["exposure_cents"] for c in live),
        "declare_cents": sum(c["declare_cents"] for c in live),
        "customers_at_risk": len({c["customer"]["id"] for c in live}),
        "nearest_deadline": nearest["claim_deadline"] if nearest else None,
        "nearest_days_left": nearest["days_left"] if nearest else None,
        "live_runs": db.query_one(
            f"""select count(*) as n from agent_runs r join customers cu on cu.id = r.customer_id
                where cu.dataset = 'demo' and r.status = 'RUNNING' and not {runs.STALLED}""")["n"],
        "today": t,
        "cases": cases,
        "customers": customers,
    }


@router.post("/demo/reset")
def demo_reset() -> dict:
    try:
        return load_seed()
    except FileNotFoundError as e:
        raise HTTPException(404, "data/demo_seed.json not found: run scripts/seed_demo.py") from e


@router.get("/benchmark")
def benchmark() -> list[dict]:
    return db.query(
        """select distinct on (split, system) id, run_at, split, system, metrics, details
           from benchmark_runs order by split, system, id desc""")


@router.get("/data")
def data_layer() -> dict:
    """What the agent's data is, where it lives in Postgres, and how fresh it is."""
    q1 = db.query_one
    return {
        "database": {**q1("select split_part(version(), ' on ', 1) as engine, "
                          "pg_size_pretty(pg_database_size(current_database())) as size"),
                     "provider": "Aiven for PostgreSQL" if "aivencloud.com" in os.getenv("DATABASE_URL", "")
                                 else "PostgreSQL (local development)"},
        "bodacc": q1("""select count(*) as rows, max(date_parution) as latest_publication,
                          count(*) filter (where event_kind = any(%s)) as procedure_notices,
                          count(distinct siren) as companies from bodacc_notices""", (list(CASE_KINDS),)),
        "register": q1("""select count(*) as rows, min(fetched_at) as oldest, max(fetched_at) as newest,
                            count(*) filter (where fetched_at < now() - interval '7 days') as stale
                          from company_cache"""),
        "ledger": q1("""select (select count(*) from customers where dataset = 'demo') as customers,
                          (select count(*) from invoices i join customers c on c.id = i.customer_id
                           where c.dataset = 'demo') as invoices,
                          (select count(*) from documents d join customers c on c.id = d.customer_id
                           where c.dataset = 'demo') as documents"""),
        "memory": q1("""with k as (select c.id from cases c join customers cu on cu.id = c.customer_id
                                   where cu.dataset = 'demo')
                        select (select count(*) from k) as cases,
                          (select count(*) from case_events where case_id in (select id from k)) as case_events,
                          (select count(*) from invoice_classifications where case_id in (select id from k)) as decisions,
                          (select count(*) from invoice_classifications where case_id in (select id from k)
                             and decided_by = 'AGENT') as agent_decisions,
                          (select count(*) from actions where case_id in (select id from k)) as actions"""),
        "agent": q1("""select count(*) as runs, coalesce(sum(input_tokens + output_tokens), 0) as tokens,
                         (select count(*) from agent_steps) as steps,
                         percentile_cont(0.5) within group (order by extract(epoch from finished_at - started_at))
                           as median_seconds
                       from agent_runs where finished_at is not null"""),
        "syncs": db.query("""select id, trigger, started_at, finished_at, fetched, inserted, updated, new_cases,
                               investigations, error from ingest_runs order by id desc limit 8"""),
        "sync_every_minutes": SYNC_MINUTES,
    }
