"""Onboarding: import an aged-receivables export (CSV) as customers + invoices, then put FORCLOS to work:
rule matching on the SIRENs given, agent investigation of the cases it opens, and identity repair for
customers with no SIREN or a SIREN the register reports as ceased or unknown.

Exports differ from one accounting tool to the next, so columns are recognised by meaning (English or
French, any order) and nothing but a customer is required. A bad row is reported, never fatal."""
from __future__ import annotations

import csv
import io
import logging
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta

from app import runs, sirene
from app.cases import match_customers
from app.db import transaction

log = logging.getLogger("forclos.import")
MAX_ROWS = 2000
MAX_IDENTITY_CHECKS = 25
MAX_ERRORS = 20
DEFAULT_TERMS_DAYS = 30

# Checked in this order against the header's words; a header takes the first role it matches. Order matters:
# "due_date" is a due date before it is a date, "montant_regle" is a payment before it is an amount.
ROLES = (
    ("remaining", ("remaining", "outstanding", "reste", "restant", "solde", "du")),
    ("paid", ("paid", "regle", "paye", "encaisse", "reglement", "settled")),
    ("due_date", ("due", "echeance")),
    ("delivery_date", ("delivery", "delivered", "livraison", "livre")),
    ("invoice_date", ("date",)),
    ("invoice_number", ("invoice", "facture", "piece", "numero", "number")),
    ("amount", ("amount", "montant", "total", "ttc", "ht", "value")),
    ("siren", ("siren", "siret")),
    ("postal_code", ("postal", "cp", "zip", "postcode", "codepostal")),
    ("city", ("city", "ville", "commune", "town")),
    ("customer", ("customer", "client", "nom", "name", "raison", "company", "societe", "tiers", "debiteur")),
    ("description", ("description", "libelle", "designation", "objet", "label", "comment", "commentaire")),
)


CUSTOMER_WORDS = set(dict(ROLES)["customer"])
INVOICE_WORDS = {"invoice", "facture", "piece"}
ID_WORDS = {"n", "no", "num", "numero", "number", "code", "id", "ref", "reference", "compte", "account"}


class ImportError_(ValueError):
    pass


def _words(header: str) -> list[str]:
    h = unicodedata.normalize("NFKD", header).encode("ascii", "ignore").decode().lower()
    return [w for w in re.split(r"[^a-z0-9]+", h) if w]


def map_columns(fields: list[str]) -> dict[str, str]:
    """role -> header, for every header we recognise. Unknown headers are simply ignored."""
    out: dict[str, str] = {}
    for f in fields:
        words = _words(f)
        if "code" in words and "postal" in words:
            words.append("codepostal")
        role = next((r for r, keys in ROLES if any(k in words for k in keys)), None)
        w = set(words)
        if role in ("customer", "invoice_number") and w & CUSTOMER_WORDS and w & ID_WORDS and not w & INVOICE_WORDS:
            role = None  # "N° client", "code client", "customer id": an account code, neither name nor invoice
        if role and role not in out:
            out[role] = f
    return out


def _date(v: str) -> date:
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v[:10] if fmt.startswith("%Y") else v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unreadable date '{v}'")


def _cents(v: str) -> int | None:
    s = re.sub(r"[€\s  ]|EUR", "", v or "", flags=re.I)
    if not s:
        return None
    if "," in s and "." in s:  # 1.234,56 or 1,234.56
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return round(float(s) * 100)
    except ValueError as e:
        raise ValueError(f"unreadable amount '{v}'") from e


def _delimiter(text: str) -> str:
    head = text[:4096]
    return max((";", ",", "\t"), key=head.count)


def _row(get, n: int, warnings: list[str]) -> dict:
    name = get("customer")
    siren = re.sub(r"\D", "", get("siren"))
    if len(siren) == 14:  # a SIRET: its first 9 digits are the SIREN
        siren = siren[:9]
    if siren and len(siren) != 9:
        warnings.append(f"line {n}: SIREN '{get('siren')}' ignored (not 9 digits)")
        siren = ""
    if not name and not siren:
        raise ValueError("no customer name or SIREN")
    cp = re.sub(r"\D", "", get("postal_code"))
    cp = cp.zfill(5) if len(cp) == 4 else cp  # spreadsheets drop the leading zero of 0xxxx codes
    if cp and len(cp) != 5:
        warnings.append(f"line {n}: postal code '{get('postal_code')}' ignored")
        cp = ""

    delivered = _date(get("delivery_date")) if get("delivery_date") else None
    due = _date(get("due_date")) if get("due_date") else None
    if get("invoice_date"):
        inv_date = _date(get("invoice_date"))
    elif delivered or due:
        inv_date = delivered or due - timedelta(DEFAULT_TERMS_DAYS)
    else:
        raise ValueError("no invoice, delivery or due date")

    amount, paid, remaining = _cents(get("amount")), _cents(get("paid")), _cents(get("remaining"))
    if amount is None and remaining is None:
        raise ValueError("no amount")
    if amount is None:
        amount = remaining + (paid or 0)
    if paid is None:
        paid = amount - remaining if remaining is not None else 0
    return {"customer": name or siren, "siren": siren or None, "postal_code": cp or None, "city": get("city") or None,
            "number": get("invoice_number") or f"L{n}", "invoice_date": inv_date,
            "due_date": due or inv_date + timedelta(DEFAULT_TERMS_DAYS), "delivery_date": delivered,
            "description": get("description") or None, "amount_cents": amount, "paid_cents": max(0, min(paid, amount))}


def parse(text: str) -> tuple[list[dict], list[str], dict[str, str]]:
    """Returns (rows, problems, columns). Problems name the line; a bad line never stops the others."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=_delimiter(text))
    cols = map_columns(reader.fieldnames or [])
    if "customer" not in cols and "siren" not in cols:
        raise ImportError_("no column names the customer (looked for: customer, client, nom, name, raison sociale, "
                           f"siren). Columns found: {', '.join(reader.fieldnames or []) or 'none'}")
    rows, problems = [], []
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            problems.append(f"only the first {MAX_ROWS} rows were read")
            break
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        get = lambda k: (raw.get(cols[k]) or "").strip() if k in cols else ""  # noqa: E731
        try:
            rows.append(_row(get, n, problems))
        except ValueError as e:
            problems.append(f"line {n}: skipped, {e}")
    return rows, problems[:MAX_ERRORS], cols


def _delivery_note(r: dict) -> str:
    lines = ["Bon de livraison (importé avec la balance âgée du client)",
             f"Date de livraison : {r['delivery_date']:%d/%m/%Y}",
             f"Facture associée : {r['number']} du {r['invoice_date']:%d/%m/%Y}"]
    if r["description"]:
        lines.append(f"Désignation : {r['description']}")
    return "\n".join(lines)


def import_csv(text: str) -> dict:
    rows, problems, cols = parse(text)
    if not rows:
        raise ImportError_("no row could be read" + (f": {problems[0]}" if problems else ""))
    created_customers = created_invoices = delivery_notes = 0
    customer_ids: dict[tuple, int] = {}
    with transaction() as conn:
        for r in rows:
            key = (r["customer"].upper(), r["postal_code"], r["siren"])
            if key not in customer_ids:
                found = conn.execute(
                    """select id from customers where dataset = 'demo' and upper(crm_name) = %s
                       and postal_code is not distinct from %s and crm_siren is not distinct from %s""", key).fetchone()
                if found:
                    customer_ids[key] = found["id"]
                else:
                    customer_ids[key] = conn.execute(
                        """insert into customers (crm_name, crm_siren, postal_code, city, dataset)
                           values (%s, %s, %s, %s, 'demo') returning id""",
                        (r["customer"], r["siren"], r["postal_code"], r["city"])).fetchone()["id"]
                    created_customers += 1
            cid = customer_ids[key]
            if conn.execute("select 1 from invoices where customer_id = %s and number = %s", (cid, r["number"])).fetchone():
                continue
            inv_id = conn.execute(
                """insert into invoices (customer_id, number, invoice_date, due_date, amount_cents, paid_cents)
                   values (%s, %s, %s, %s, %s, %s) returning id""",
                (cid, r["number"], r["invoice_date"], r["due_date"], r["amount_cents"], r["paid_cents"])).fetchone()["id"]
            created_invoices += 1
            if r["delivery_date"]:
                conn.execute("""insert into documents (customer_id, invoice_id, kind, doc_date, body, added_by)
                                values (%s, %s, 'DELIVERY_NOTE', %s, %s, 'import')""",
                             (cid, inv_id, r["delivery_date"], _delivery_note(r)))
                delivery_notes += 1
        new_cases = match_customers(conn)
        to_check = conn.execute(
            """select id, crm_siren from customers where id = any(%s) and identity_status = 'UNVERIFIED'
               and not exists (select 1 from cases where customer_id = customers.id)""",
            (list(customer_ids.values()),)).fetchall()
    started = []
    for case_id in new_cases:
        try:
            started.append(runs.investigate_case(case_id, _case_customer(case_id), "Opened at import by the exact-SIREN rule."))
        except runs.RunLimitError:
            break
    queued = to_check[:MAX_IDENTITY_CHECKS]
    if queued:
        threading.Thread(target=_identity_worker, args=(queued,), daemon=True, name="import-identity").start()
    return {"rows": len(rows), "customers_created": created_customers, "invoices_created": created_invoices,
            "delivery_notes": delivery_notes, "cases_opened": len(new_cases), "investigations_started": len(started),
            "identity_checks_queued": len(queued), "columns": cols, "errors": problems}


def _case_customer(case_id: int) -> int:
    with transaction() as conn:
        return conn.execute("select customer_id from cases where id = %s", (case_id,)).fetchone()["customer_id"]


def _identity_worker(customers: list[dict]) -> None:
    """Sequential, so an import never floods the model API. A SIREN the register confirms as active is
    left to the exact rule; only missing, ceased or unknown SIRENs go to the agent."""
    for c in customers:
        try:
            if c["crm_siren"]:
                company = sirene.get_company(c["crm_siren"])
                if company and company.get("etat_administratif") == "A":
                    continue
            runs.resolve_identity(c["id"], wait=True)
        except Exception:
            log.exception("identity check failed for customer %s", c["id"])
