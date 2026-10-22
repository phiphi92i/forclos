"""Handlers for every tool in app/agent.py TOOLS. The agent supplies evidence; these functions
apply the law (app/legal.py) and persist. Results stay small: they go back into the model context."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable

from app import legal, sirene
from app.cases import (CASE_KINDS, compute_case_deadlines, has_case_notice, open_case, recompute_amounts,
                       today)
from app.db import Jsonb, transaction
from app.ingest import store_history

TEXT_LIMIT = 1500
NOTICE_TEXT_LIMIT = 600
SOLE_TRADER = "1000"

CREDITOR = {
    "name": "Maison Verdier Distribution",
    "form": "SAS (fictional creditor for the demo)",
    "address": "12 quai Rambaud, 69002 Lyon",
    "activity": "Food-service wholesale",
}


class ToolError(ValueError):
    """Bad input from the model: reported back to it as an error result."""


@dataclass
class RunContext:
    run_id: str
    case_id: int | None = None
    customer_id: int | None = None


def _cut(s: str | None, n: int = TEXT_LIMIT) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + " […]"


def _siren(s: str | None) -> str:
    s = re.sub(r"\D", "", s or "")
    if len(s) != 9:
        raise ToolError("SIREN must have 9 digits")
    return s


def _case(conn, case_id: int) -> dict:
    case = conn.execute("select * from cases where id = %s", (case_id,)).fetchone()
    if not case:
        raise ToolError(f"case {case_id} not found")
    return case


def _euros(cents: int) -> str:
    return f"€{cents / 100:,.2f}"


# ---------------------------------------------------------------- customer file

def get_customer_file(customer_id: int) -> dict:
    with transaction() as conn:
        c = conn.execute(
            """select id, crm_name, crm_siren, address, postal_code, city, payment_terms, identity_status,
                      verified_siren, identity_evidence from customers where id = %s""", (customer_id,)).fetchone()
        if not c:
            raise ToolError(f"customer {customer_id} not found")
        contracts = conn.execute(
            """select id, kind, retention_of_title, published_security, signed_on from contracts
               where customer_id = %s order by id""", (customer_id,)).fetchall()
        invoices = conn.execute(
            """select id, number, invoice_date, due_date, amount_cents, amount_cents - paid_cents as outstanding_cents,
                      contract_id from invoices where customer_id = %s order by invoice_date, id""",
            (customer_id,)).fetchall()
        documents = conn.execute(
            """select id, kind, doc_date, invoice_id, added_by from documents where customer_id = %s order by id""",
            (customer_id,)).fetchall()
        cases = conn.execute("select id, siren, status from cases where customer_id = %s", (customer_id,)).fetchall()
    return {"customer": c, "contracts": contracts, "invoices": invoices, "documents": documents, "cases": cases}


def read_document(document_id: int) -> dict:
    with transaction() as conn:
        d = conn.execute("select id, customer_id, invoice_id, kind, doc_date, added_by, body from documents "
                         "where id = %s", (document_id,)).fetchone()
    if not d:
        raise ToolError(f"document {document_id} not found")
    return {**d, "body": _cut(d["body"])}


# ---------------------------------------------------------------- company register (cached)

def _cached(key: str, fetch: Callable[[], object]):
    with transaction() as conn:
        row = conn.execute("select payload from company_cache where cache_key = %s", (key,)).fetchone()
    if row:
        return row["payload"]
    payload = fetch()
    with transaction() as conn:
        conn.execute("""insert into company_cache (cache_key, payload) values (%s, %s)
                        on conflict (cache_key) do update set payload = excluded.payload, fetched_at = now()""",
                     (key, Jsonb(payload)))
    return payload


def search_company(query: str, postal_code: str | None = None) -> dict:
    q = " ".join((query or "").split())
    if not q:
        raise ToolError("query is empty")
    cp = (postal_code or "").strip() or None
    results = _cached(f"search:{q.upper()}|{cp or ''}", lambda: sirene.search_company(q, cp))
    results = [r for r in results if r.get("nature_juridique") != SOLE_TRADER]
    return {"query": q, "postal_code": cp, "results": results,
            "note": "Sole traders (nature juridique 1000) are excluded." if results is not None else None}


def get_company(siren: str) -> dict:
    s = _siren(siren)
    company = _cached(f"siren:{s}", lambda: sirene.get_company(s))
    return {"company": company} if company else {"company": None, "note": f"No register record for {s}."}


# ---------------------------------------------------------------- BODACC history

def _notice_view(n: dict) -> dict:
    return {"id": n["id"], "date_parution": n["date_parution"], "jugement_date": n["jugement_date"],
            "nature": n["jugement_nature"], "event_kind": n["event_kind"], "procedure": n["procedure"],
            "denomination": n["denomination"], "tribunal": n["tribunal"], "officers": n["officers"],
            "complement": _cut(n["complement"], NOTICE_TEXT_LIMIT), "url": n["url"]}


def get_bodacc_history(siren: str) -> dict:
    s = _siren(siren)
    with transaction() as conn:
        local = conn.execute("select * from bodacc_notices where siren = %s order by date_parution, id",
                             (s,)).fetchall()
        has_opening = any(n["event_kind"] in ("OPENING", "PLAN_RESOLUTION") for n in local)
        source = "local store"
        if not local or not has_opening:
            try:
                fetched = store_history(conn, s)
                source = f"live BODACC API ({len(fetched)} notices)"
            except Exception as e:  # offline: the local store is all we have, say so
                source = f"local store only (live API failed: {type(e).__name__})"
            local = conn.execute("select * from bodacc_notices where siren = %s order by date_parution, id",
                                 (s,)).fetchall()
    return {"siren": s, "source": source, "count": len(local),
            "collective_procedure": any(n["event_kind"] in CASE_KINDS for n in local),
            "notices": [_notice_view(n) for n in local]}


# ---------------------------------------------------------------- identity

def record_identity(ctx: RunContext, customer_id: int, status: str, evidence: str, siren: str | None = None) -> dict:
    if status not in ("VERIFIED", "REVIEW", "NOT_FOUND"):
        raise ToolError("status must be VERIFIED, REVIEW or NOT_FOUND")
    s = _siren(siren) if status == "VERIFIED" else (re.sub(r"\D", "", siren or "") or None)
    with transaction() as conn:
        if not conn.execute("select 1 from customers where id = %s", (customer_id,)).fetchone():
            raise ToolError(f"customer {customer_id} not found")
        conn.execute(
            """update customers set identity_status = %s, verified_siren = %s, identity_evidence = %s
               where id = %s""",
            (status, s if status == "VERIFIED" else None,
             Jsonb({"evidence": evidence, "candidate_siren": s, "run_id": ctx.run_id, "decided_by": "AGENT"}),
             customer_id))
        out = {"customer_id": customer_id, "status": status, "siren": s, "case_id": None, "case_created": False}
        if status == "VERIFIED" and has_case_notice(conn, s):
            case_id, created = open_case(conn, customer_id, s)
            conn.execute("update agent_runs set case_id = coalesce(case_id, %s) where id = %s", (case_id, ctx.run_id))
            ctx.case_id = ctx.case_id or case_id
            out.update(case_id=case_id, case_created=created,
                       note="Exact SIREN rule now matches collective-procedure notices: case opened.")
        elif status == "VERIFIED":
            out["note"] = "No collective-procedure notice for this SIREN: no case, no alert."
    return out


# ---------------------------------------------------------------- deadlines and claims

def compute_deadlines(case_id: int) -> dict:
    with transaction() as conn:
        _case(conn, case_id)
        d = compute_case_deadlines(conn, case_id)
    return {"case_id": case_id, **d}


def record_claim_classification(ctx: RunContext, case_id: int, invoice_id: int, fait_generateur_date: str | None,
                                basis: str, rationale: str, evidence_document_id: int | None = None) -> dict:
    if basis not in {b.value for b in legal.Basis}:
        raise ToolError(f"basis must be one of {[b.value for b in legal.Basis]}")
    try:
        fg = date.fromisoformat(fait_generateur_date) if fait_generateur_date else None
    except ValueError as e:
        raise ToolError("fait_generateur_date must be YYYY-MM-DD or null") from e
    with transaction() as conn:
        case = _case(conn, case_id)
        inv = conn.execute("select * from invoices where id = %s and customer_id = %s",
                           (invoice_id, case["customer_id"])).fetchone()
        if not inv:
            raise ToolError(f"invoice {invoice_id} does not belong to this case's customer")
        if evidence_document_id is not None and not conn.execute(
                "select 1 from documents where id = %s and customer_id = %s",
                (evidence_document_id, case["customer_id"])).fetchone():
            raise ToolError(f"document {evidence_document_id} does not belong to this case's customer")
        prev = conn.execute("select * from current_classifications where case_id = %s and invoice_id = %s",
                            (case_id, invoice_id)).fetchone()
        outstanding = inv["amount_cents"] - inv["paid_cents"]
        cat, reason = legal.classify_claim(fg, case["opening_judgment_date"], outstanding)
        conn.execute(
            """insert into invoice_classifications (case_id, invoice_id, category, fait_generateur, basis,
               evidence_document_id, rationale, decided_by, run_id) values (%s,%s,%s,%s,%s,%s,%s,'AGENT',%s)""",
            (case_id, invoice_id, cat.value, fg, basis, evidence_document_id, rationale, ctx.run_id))
        totals = recompute_amounts(conn, case_id)
    was_declared = bool(prev and prev["category"] == "DECLARE")
    delta = (outstanding if cat == legal.Category.DECLARE else 0) - (outstanding if was_declared else 0)
    return {"invoice_id": invoice_id, "number": inv["number"], "category": cat.value, "reason": reason,
            "opening_judgment_date": case["opening_judgment_date"],
            "previous_category": prev["category"] if prev else None,
            "changed": bool(prev and prev["category"] != cat.value),
            "declare_delta_cents": delta, "case_declare_cents": totals["declare_cents"]}


def _claim_lines(conn, case_id: int) -> tuple[list[dict], list[dict], list[dict]]:
    rows = conn.execute(
        """select cc.*, i.number, i.invoice_date, i.due_date, i.amount_cents - i.paid_cents as outstanding_cents,
                  i.contract_id
           from current_classifications cc join invoices i on i.id = cc.invoice_id
           where cc.case_id = %s order by i.invoice_date, i.id""", (case_id,)).fetchall()
    lines = [{"invoice_id": r["invoice_id"], "number": r["number"], "invoice_date": r["invoice_date"],
              "fait_generateur": r["fait_generateur"], "basis": r["basis"], "due_date": r["due_date"],
              "cents": r["outstanding_cents"], "evidence_document_id": r["evidence_document_id"],
              "decided_by": r["decided_by"], "category": r["category"], "contract_id": r["contract_id"]}
             for r in rows]
    return ([x for x in lines if x["category"] == "DECLARE"], [x for x in lines if x["category"] == "REVIEW"],
            [x for x in lines if x["category"] == "POST_OPENING"])


def _upsert_action(conn, case_id: int, kind: str, payload: dict) -> int:
    return conn.execute(
        """insert into actions (case_id, kind, payload) values (%s, %s, %s)
           on conflict (case_id, kind) do update set payload = excluded.payload,
             status = case when actions.payload = excluded.payload then actions.status else 'PROPOSED' end,
             applied_at = case when actions.payload = excluded.payload then actions.applied_at else null end
           returning id""", (case_id, kind, Jsonb(payload, dumps=_dumps))).fetchone()["id"]


def _dumps(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def propose_actions(case_id: int, include_payment_terms_cash: bool, include_revendication_alert: bool,
                    officer_name: str | None = None, officer_role: str | None = None) -> dict:
    with transaction() as conn:
        case = _case(conn, case_id)
        cust = conn.execute("select * from customers where id = %s", (case["customer_id"],)).fetchone()
        anchor = conn.execute("select * from bodacc_notices where id = %s", (case["anchor_notice_id"],)).fetchone()
        contracts = conn.execute("select * from contracts where customer_id = %s", (cust["id"],)).fetchall()
        declare, review, post = _claim_lines(conn, case_id)
        made, warnings = [], []
        if any(c["published_security"] for c in contracts):
            warnings.append("A contract carries a published security: deadline runs from personal notice. "
                            "Out of scope: call flag_lawyer_review.")
        if not case["claim_deadline"]:
            warnings.append("No claim deadline (no opening judgment in history): the draft cannot be dated.")

        opening_proc = legal.Procedure(anchor["procedure"]) if anchor and anchor["procedure"] else None
        officer = ({"name": officer_name, "role": officer_role} if officer_name
                   else (anchor["officers"][0] | {"name": anchor["officers"][0]["text"]}
                         if anchor and anchor["officers"] else {"name": None, "role": None}))
        if declare and case["opening_judgment_date"]:
            due = legal.split_due([(x["due_date"], x["cents"]) for x in declare], case["opening_judgment_date"],
                                  opening_proc)
            payload = {
                "watermark": "DRAFT, NOT SENT",
                "creditor": CREDITOR,
                "debtor": {"denomination": anchor["denomination"] if anchor else None, "siren": case["siren"],
                           "tribunal": anchor["tribunal"] if anchor else None},
                "procedure": opening_proc.value if opening_proc else None,
                "current_procedure": case["current_procedure"],
                "opening_judgment_date": case["opening_judgment_date"],
                "publication_date": anchor["date_parution"] if anchor else None,
                "anchor_notice_id": case["anchor_notice_id"],
                "officer": officer,
                "nature": "chirographaire (unsecured)",
                "lines": declare,
                "due_split": due,
                "total_cents": due["total_cents"],
                "claim_deadline": case["claim_deadline"],
                "pending_review": review,
                "excluded_post_opening": post,
            }
            _upsert_action(conn, case_id, "CLAIM_DRAFT", payload)
            made.append({"kind": "CLAIM_DRAFT", "total": _euros(due["total_cents"]), "lines": len(declare)})
        else:
            warnings.append("No invoice classified DECLARE: no claim draft.")

        if include_payment_terms_cash:
            _upsert_action(conn, case_id, "PAYMENT_TERMS_CASH", {
                "customer_id": cust["id"], "current_terms": cust["payment_terms"], "proposed_terms": "CASH",
                "text": "Keep supplying under the contract (L622-13 C. com.: pre-opening debts are no ground to "
                        "stop). New deliveries are paid in cash on delivery."})
            made.append({"kind": "PAYMENT_TERMS_CASH"})

        rot = [c for c in contracts if c["retention_of_title"]]
        if include_revendication_alert and rot:
            ids = {c["id"] for c in rot}
            goods = [x for x in declare if x["contract_id"] in ids]
            _upsert_action(conn, case_id, "REVENDICATION_ALERT", {
                "deadline": case["revendication_deadline"],
                "contracts": [{"id": c["id"], "kind": c["kind"], "signed_on": c["signed_on"]} for c in rot],
                "invoices": goods,
                "text": "Retention-of-title clause: goods still held by the debtor can be reclaimed "
                        "(action en revendication, L624-9 C. com.) within 3 months of the opening publication."})
            made.append({"kind": "REVENDICATION_ALERT", "deadline": case["revendication_deadline"]})
        elif include_revendication_alert:
            warnings.append("No contract with a retention-of-title clause: no revendication alert.")
    return {"case_id": case_id, "actions": made, "warnings": warnings}


def flag_lawyer_review(ctx: RunContext, reason: str, case_id: int | None = None,
                       customer_id: int | None = None) -> dict:
    case_id = case_id or ctx.case_id
    with transaction() as conn:
        if case_id:
            _case(conn, case_id)
            prev = conn.execute("select payload from actions where case_id = %s and kind = 'LAWYER_REVIEW'",
                                (case_id,)).fetchone()
            reasons = (prev["payload"].get("reasons", []) if prev else [])
            if reason not in reasons:
                reasons.append(reason)
            _upsert_action(conn, case_id, "LAWYER_REVIEW", {"reasons": reasons})
            conn.execute("update cases set status = 'NEEDS_REVIEW', updated_at = now() where id = %s", (case_id,))
            return {"case_id": case_id, "flagged": True, "reasons": reasons}
        customer_id = customer_id or ctx.customer_id
        if not customer_id:
            raise ToolError("case_id or customer_id required")
        conn.execute(
            """update customers set identity_status = case when identity_status = 'VERIFIED' then identity_status
               else 'REVIEW' end, identity_evidence = coalesce(identity_evidence, '{}'::jsonb) || %s where id = %s""",
            (Jsonb({"review_reason": reason}), customer_id))
    return {"customer_id": customer_id, "flagged": True, "reason": reason}


def finish(ctx: RunContext, status: str, summary: str) -> dict:
    case_status = {"READY": "READY", "NEEDS_REVIEW": "NEEDS_REVIEW"}.get(status)
    with transaction() as conn:
        if ctx.case_id and case_status:
            case = _case(conn, ctx.case_id)
            if not case["claim_deadline"]:  # side review items do not block a claim the agent judged ready
                case_status = "NEEDS_REVIEW"
            conn.execute("update cases set status = %s, updated_at = now() where id = %s", (case_status, ctx.case_id))
    return {"ok": True, "status": status, "summary": summary}


def make_handlers(ctx: RunContext) -> dict[str, Callable[..., dict]]:
    return {
        "get_customer_file": get_customer_file,
        "read_document": read_document,
        "search_company": search_company,
        "get_company": get_company,
        "get_bodacc_history": get_bodacc_history,
        "record_identity": lambda **kw: record_identity(ctx, **kw),
        "compute_deadlines": compute_deadlines,
        "record_claim_classification": lambda **kw: record_claim_classification(ctx, **kw),
        "propose_actions": propose_actions,
        "flag_lawyer_review": lambda **kw: flag_lawyer_review(ctx, **kw),
        "finish": lambda **kw: finish(ctx, **kw),
    }
