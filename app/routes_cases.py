"""Case routes: case detail, investigations, judge inputs (customer, document), run trail, actions."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app import db, runs
from app.baseline import naive_deadline
from app.cases import to_legal_notice, today

router = APIRouter(prefix="/api")


class InvestigateIn(BaseModel):
    trigger: str = Field("Manual investigation requested from the dashboard.", max_length=300)


class CustomerIn(BaseModel):
    crm_name: str = Field(..., min_length=2, max_length=120)
    postal_code: str = Field(..., pattern=r"^\d{5}$")
    crm_siren: str | None = Field(None, pattern=r"^\d{9}$")
    city: str | None = Field(None, max_length=80)


class DocumentIn(BaseModel):
    customer_id: int
    invoice_id: int | None = None
    kind: str = Field("DELIVERY_NOTE", pattern=r"^(DELIVERY_NOTE|ORDER|PAYMENT|CONTRACT)$")
    doc_date: date | None = None
    body: str = Field(..., min_length=5, max_length=4000)


def _case_or_404(case_id: int) -> dict:
    case = db.query_one("select * from cases where id = %s", (case_id,))
    if not case:
        raise HTTPException(404, "case not found")
    return case


@router.get("/cases/{case_id}")
def get_case(case_id: int) -> dict:
    case = _case_or_404(case_id)
    t = today()
    case["days_left"] = (case["claim_deadline"] - t).days if case["claim_deadline"] else None
    customer = db.query_one(
        """select id, crm_name, crm_siren, address, postal_code, city, payment_terms, identity_status,
                  verified_siren, identity_evidence from customers where id = %s""", (case["customer_id"],))
    timeline = db.query(
        """select n.id, n.date_parution, n.jugement_date, n.jugement_nature as nature, n.event_kind, n.procedure,
                  n.denomination, n.tribunal, n.officers, n.url, n.ville, (n.id = %s) as is_anchor
           from case_events e join bodacc_notices n on n.id = e.notice_id
           where e.case_id = %s order by n.date_parution, n.id""", (case["anchor_notice_id"], case_id))
    anchor = next((n for n in timeline if n["is_anchor"]), None)
    hist = db.query("select * from bodacc_notices where siren = %s and event_kind = any(%s) order by date_parution",
                    (case["siren"], ["OPENING", "CONVERSION", "PRONOUNCED_LJ", "PLAN_RESOLUTION"]))
    naive = naive_deadline([to_legal_notice(n) for n in hist])
    case["naive_deadline"] = naive if naive and naive != case["claim_deadline"] else None
    invoices = db.query(
        """select i.id, i.number, i.invoice_date, i.due_date, i.amount_cents, i.amount_cents - i.paid_cents
                  as outstanding_cents, cc.category, cc.basis, cc.fait_generateur, cc.evidence_document_id,
                  cc.decided_by, cc.rationale, cc.run_id, cc.created_at as decided_at
           from invoices i left join current_classifications cc on cc.invoice_id = i.id and cc.case_id = %s
           where i.customer_id = %s order by i.invoice_date, i.id""", (case_id, case["customer_id"]))
    history = db.query(
        """select id, invoice_id, category, basis, fait_generateur, decided_by, rationale, created_at
           from invoice_classifications where case_id = %s order by id""", (case_id,))
    for inv in invoices:
        inv["history"] = [h for h in history if h["invoice_id"] == inv["id"]]
        prev = inv["history"][-2] if len(inv["history"]) > 1 else None
        inv["previous"] = prev
        inv["changed"] = bool(prev and prev["category"] != inv["category"])
    actions = db.query("select * from actions where case_id = %s order by id", (case_id,))
    run = db.query_one(
        """select id, task, status, summary, model, input_tokens, output_tokens, started_at, finished_at
           from agent_runs where case_id = %s order by started_at desc limit 1""", (case_id,))
    documents = db.query("select id, kind, doc_date, invoice_id, added_by from documents where customer_id = %s "
                         "order by id", (case["customer_id"],))
    contracts = db.query("select id, kind, retention_of_title, published_security, signed_on from contracts "
                         "where customer_id = %s", (case["customer_id"],))
    return {**case, "denomination": anchor["denomination"] if anchor else (timeline[-1]["denomination"]
                                                                        if timeline else None),
            "anchor_publication": anchor["date_parution"] if anchor else None,
            "customer": customer, "timeline": timeline, "invoices": invoices, "actions": actions,
            "latest_run": run, "documents": documents, "contracts": contracts}


@router.post("/cases/{case_id}/investigate")
def investigate(case_id: int, body: InvestigateIn) -> dict:
    case = _case_or_404(case_id)
    if case["status"] == "INVESTIGATING":
        run = db.query_one("select id from agent_runs where case_id = %s and status = 'RUNNING' "
                           "order by started_at desc limit 1", (case_id,))
        if run:
            return {"run_id": str(run["id"]), "already_running": True}
    return {"run_id": runs.investigate_case(case_id, case["customer_id"], body.trigger)}


@router.post("/customers")
def add_customer(body: CustomerIn) -> dict:
    row = db.query_one(
        """insert into customers (crm_name, crm_siren, postal_code, city, dataset) values (%s, %s, %s, %s, 'demo')
           returning id""", (body.crm_name.strip(), body.crm_siren, body.postal_code, body.city))
    return {"customer_id": row["id"], "run_id": runs.resolve_identity(row["id"])}


@router.post("/customers/{customer_id}/resolve")
def resolve_customer(customer_id: int) -> dict:
    if not db.query_one("select 1 from customers where id = %s", (customer_id,)):
        raise HTTPException(404, "customer not found")
    return {"customer_id": customer_id, "run_id": runs.resolve_identity(customer_id)}


@router.get("/customers/{customer_id}/runs/latest")
def latest_customer_run(customer_id: int) -> dict:
    run = db.query_one("select id, task, status, summary, case_id from agent_runs where customer_id = %s "
                       "order by started_at desc limit 1", (customer_id,))
    if not run:
        raise HTTPException(404, "no run for this customer")
    return run


@router.post("/documents")
def add_document(body: DocumentIn) -> dict:
    if body.invoice_id is not None and not db.query_one(
            "select 1 from invoices where id = %s and customer_id = %s", (body.invoice_id, body.customer_id)):
        raise HTTPException(400, "invoice does not belong to this customer")
    doc = db.query_one(
        """insert into documents (customer_id, invoice_id, kind, doc_date, body, added_by)
           values (%s, %s, %s, %s, %s, 'judge') returning id""",
        (body.customer_id, body.invoice_id, body.kind, body.doc_date, body.body))
    case = db.query_one("select id from cases where customer_id = %s order by id desc limit 1", (body.customer_id,))
    if not case:
        return {"document_id": doc["id"], "run_id": None}
    trigger = (f"New document #{doc['id']} ({body.kind}, dated {body.doc_date or 'undated'}) added by a user "
               f"for invoice {body.invoice_id}. Re-examine the affected invoice(s) in light of it.")
    return {"document_id": doc["id"], "run_id": runs.investigate_case(case["id"], body.customer_id, trigger)}


@router.get("/runs/{run_id}/steps")
def run_steps(run_id: str, after: int = 0) -> dict:
    run = db.query_one("select id, status, summary, case_id, customer_id, task, input_tokens, output_tokens "
                       "from agent_runs where id::text = %s", (run_id,))
    if not run:
        raise HTTPException(404, "run not found")
    steps = db.query("select id, kind, tool, payload, created_at from agent_steps where run_id = %s and id > %s "
                     "order by id", (run["id"], after))
    return {**run, "steps": steps}


@router.post("/actions/{action_id}/apply")
def apply_action(action_id: int) -> dict:
    action = db.query_one("select * from actions where id = %s", (action_id,))
    if not action:
        raise HTTPException(404, "action not found")
    with db.transaction() as conn:
        if action["kind"] == "PAYMENT_TERMS_CASH":
            conn.execute("update customers set payment_terms = 'CASH' where id = %s",
                         (action["payload"]["customer_id"],))
        row = conn.execute("update actions set status = 'APPLIED', applied_at = now() where id = %s returning *",
                           (action_id,)).fetchone()
    return row


def _eur(cents: int) -> str:
    s = f"{cents / 100:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} €"


def _fr(d) -> str:
    return date.fromisoformat(str(d)[:10]).strftime("%d/%m/%Y") if d else "—"


@router.get("/actions/{action_id}/claim.txt", response_class=PlainTextResponse)
def claim_txt(action_id: int) -> str:
    action = db.query_one("select * from actions where id = %s and kind = 'CLAIM_DRAFT'", (action_id,))
    if not action:
        raise HTTPException(404, "claim draft not found")
    p = action["payload"]
    cr, de, due, off = p["creditor"], p["debtor"], p["due_split"], p.get("officer") or {}
    lines = "\n".join(
        f"  - Facture {x['number']} du {_fr(x['invoice_date'])}, fait générateur {_fr(x['fait_generateur'])} "
        f"({x['basis']}), échéance {_fr(x['due_date'])} : {_eur(x['cents'])}"
        + (f" [pièce n° {x['evidence_document_id']}]" if x.get("evidence_document_id") else "")
        for x in p["lines"])
    a_echoir = "\n".join(f"  - {_eur(x['cents'])} à échoir le {_fr(x['due_date'])}"
                         for x in due["a_echoir_detail"]) or "  - néant"
    return f"""*** PROJET, NON ENVOYÉ (DRAFT, NOT SENT) ***

DÉCLARATION DE CRÉANCE
(articles L622-24 et L622-25 du Code de commerce)

À l'attention de : {off.get('name') or '[mandataire judiciaire / liquidateur à compléter]'}
Qualité : {off.get('role') or '—'}

Créancier : {cr['name']}, {cr['form']}, {cr['address']}
Débiteur : {de['denomination']}, SIREN {de['siren']}
Juridiction : {de['tribunal'] or '—'}
Procédure : {p['procedure'] or '—'} ouverte par jugement du {_fr(p['opening_judgment_date'])},
publié au BODACC le {_fr(p['publication_date'])} (annonce {p['anchor_notice_id']})
Procédure en cours : {p.get('current_procedure') or '—'}

Nature de la créance : chirographaire

Détail :
{lines}

Sommes échues au jour du jugement d'ouverture : {_eur(due['echu_cents'])}
Sommes à échoir :
{a_echoir}

TOTAL DÉCLARÉ : {_eur(due['total_cents'])}

Date limite de déclaration : {_fr(p['claim_deadline'])}
(2 mois à compter de la publication au BODACC du jugement d'ouverture, art. R622-24 C. com.)

Je certifie sincère et véritable la présente déclaration de créance.

Fait à Lyon, le ____________          Signature : ____________

Pièces justificatives : factures et bons de livraison référencés ci-dessus.

Préparé par FORCLOS. Données BODACC publiques, grand livre fictif de démonstration.
"""
