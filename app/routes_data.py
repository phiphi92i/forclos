"""Data routes: ingestion, live feed, dashboard, demo reset, benchmark."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db
from app.cases import CASE_KINDS, today
from app.demo import load_seed
from app.ingest import ingest

router = APIRouter(prefix="/api")


class IngestIn(BaseModel):
    days: int = Field(45, ge=1, le=90)


@router.post("/ingest")
def post_ingest(body: IngestIn) -> dict:
    try:
        return ingest(body.days)
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
    return {
        "exposure_cents": sum(c["exposure_cents"] for c in live),
        "declare_cents": sum(c["declare_cents"] for c in live),
        "customers_at_risk": len({c["customer"]["id"] for c in live}),
        "nearest_deadline": nearest["claim_deadline"] if nearest else None,
        "nearest_days_left": nearest["days_left"] if nearest else None,
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
