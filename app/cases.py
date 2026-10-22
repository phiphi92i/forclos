"""Case lifecycle shared by ingestion (rule matching) and the agent tools.
Everything here is deterministic: it applies app/legal.py to what is in the database."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import legal
from app.db import Jsonb

PARIS = ZoneInfo("Europe/Paris")
CASE_KINDS = ("OPENING", "CONVERSION", "PRONOUNCED_LJ", "PLAN_RESOLUTION")


def today() -> date:
    return datetime.now(PARIS).date()


def notices_for(conn, siren: str) -> list[dict]:
    return conn.execute(
        "select * from bodacc_notices where siren = %s order by date_parution, id", (siren,)).fetchall()


def has_case_notice(conn, siren: str) -> bool:
    return conn.execute("select 1 from bodacc_notices where siren = %s and event_kind = any(%s) limit 1",
                        (siren, list(CASE_KINDS))).fetchone() is not None


def to_legal_notice(n: dict) -> legal.Notice:
    return legal.Notice(id=n["id"], date_parution=n["date_parution"], jugement_date=n["jugement_date"],
                        kind=legal.EventKind(n["event_kind"]),
                        procedure=legal.Procedure(n["procedure"]) if n["procedure"] else None,
                        nature=n["jugement_nature"] or "")


def compute_case_deadlines(conn, case_id: int) -> dict:
    case = conn.execute("select * from cases where id = %s", (case_id,)).fetchone()
    hist = notices_for(conn, case["siren"])
    for n in hist:
        conn.execute("insert into case_events (case_id, notice_id) values (%s, %s) on conflict do nothing",
                     (case_id, n["id"]))
    d = legal.compute_deadlines([to_legal_notice(n) for n in hist])
    status = {"REVIEW": "NEEDS_REVIEW", "CLOSED": "CLOSED"}.get(d.status)
    conn.execute(
        """update cases set anchor_notice_id = %s, opening_judgment_date = %s, current_procedure = %s,
           claim_deadline = %s, revendication_deadline = %s, relief_deadline = %s, notes = %s,
           status = coalesce(%s, case when status = 'CLOSED' then 'DETECTED' else status end), updated_at = now()
           where id = %s""",
        (d.anchor_notice_id, d.opening_judgment_date, d.current_procedure.value if d.current_procedure else None,
         d.claim_deadline, d.revendication_deadline, d.relief_deadline, Jsonb(d.notes), status, case_id))
    return {
        "status": d.status,
        "anchor_notice_id": d.anchor_notice_id,
        "anchor_publication": d.anchor_publication,
        "opening_judgment_date": d.opening_judgment_date,
        "current_procedure": d.current_procedure.value if d.current_procedure else None,
        "claim_deadline": d.claim_deadline,
        "revendication_deadline": d.revendication_deadline,
        "relief_deadline": d.relief_deadline,
        "days_left": d.days_left(today()),
        "notes": d.notes,
    }


def unpaid_invoices(conn, customer_id: int) -> list[dict]:
    return conn.execute(
        "select * from invoices where customer_id = %s and amount_cents > paid_cents order by invoice_date, id",
        (customer_id,)).fetchall()


def rule_classify(conn, case_id: int) -> int:
    """RULE layer: date every unpaid invoice by its invoice date (what a rules system does).
    Only for invoices with no classification yet: agent decisions are never overwritten here."""
    case = conn.execute("select * from cases where id = %s", (case_id,)).fetchone()
    n = 0
    for inv in unpaid_invoices(conn, case["customer_id"]):
        exists = conn.execute("select 1 from invoice_classifications where case_id = %s and invoice_id = %s",
                              (case_id, inv["id"])).fetchone()
        if exists:
            continue
        cat, reason = legal.classify_claim(inv["invoice_date"], case["opening_judgment_date"],
                                           inv["amount_cents"] - inv["paid_cents"])
        conn.execute(
            """insert into invoice_classifications (case_id, invoice_id, category, fait_generateur, basis,
               rationale, decided_by) values (%s, %s, %s, %s, 'INVOICE_DATE', %s, 'RULE')""",
            (case_id, inv["id"], cat.value, inv["invoice_date"], f"Invoice date rule. {reason}"))
        n += 1
    return n


def recompute_amounts(conn, case_id: int) -> dict:
    return conn.execute(
        """update cases c set
             exposure_cents = (select coalesce(sum(amount_cents - paid_cents), 0) from invoices
                               where customer_id = c.customer_id and amount_cents > paid_cents),
             declare_cents = (select coalesce(sum(i.amount_cents - i.paid_cents), 0)
                              from current_classifications cc join invoices i on i.id = cc.invoice_id
                              where cc.case_id = c.id and cc.category = 'DECLARE'),
             updated_at = now()
           where id = %s returning exposure_cents, declare_cents""", (case_id,)).fetchone()


def open_case(conn, customer_id: int, siren: str) -> tuple[int, bool]:
    """Create (or refresh) the case for a customer whose SIREN has collective-procedure notices.
    Returns (case_id, created)."""
    row = conn.execute(
        """insert into cases (customer_id, siren) values (%s, %s)
           on conflict (customer_id, siren) do update set updated_at = now()
           returning id, (xmax = 0) as created""", (customer_id, siren)).fetchone()
    compute_case_deadlines(conn, row["id"])
    rule_classify(conn, row["id"])
    recompute_amounts(conn, row["id"])
    return row["id"], row["created"]


def match_customers(conn, dataset: str = "demo") -> list[int]:
    """RULE matching: exact SIREN (verified if any, else as typed in the CRM) against case notices.
    Returns the ids of the cases created by this call."""
    rows = conn.execute(
        """select c.id, coalesce(c.verified_siren, c.crm_siren) as siren from customers c
           where c.dataset = %s and coalesce(c.verified_siren, c.crm_siren) is not null
             and c.identity_status <> 'NOT_FOUND'
             and exists (select 1 from bodacc_notices n where n.siren = coalesce(c.verified_siren, c.crm_siren)
                         and n.event_kind = any(%s))""", (dataset, list(CASE_KINDS))).fetchall()
    created = []
    for r in rows:
        case_id, is_new = open_case(conn, r["id"], r["siren"])
        if is_new:
            created.append(case_id)
    return created
