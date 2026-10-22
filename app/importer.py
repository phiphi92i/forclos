"""Onboarding: import an aged-receivables export (CSV) as customers + invoices, then put FORCLOS to work:
rule matching on the SIRENs given, agent investigation of the cases it opens, and identity repair for
customers with no SIREN or a SIREN the register reports as ceased or unknown."""
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
DEFAULT_TERMS_DAYS = 30
COLUMNS = {"customer": ("customer", "client", "customer_name", "nom", "raison_sociale"),
           "siren": ("siren", "siret"),
           "postal_code": ("postal_code", "code_postal", "cp", "zip"),
           "city": ("city", "ville"),
           "invoice_number": ("invoice_number", "invoice", "facture", "numero_facture", "n_facture"),
           "invoice_date": ("invoice_date", "date_facture", "date"),
           "due_date": ("due_date", "echeance", "date_echeance"),
           "amount": ("amount", "montant", "montant_ttc", "total"),
           "paid": ("paid", "regle", "paye", "montant_regle", "reglement")}


class ImportError_(ValueError):
    pass


def _date(v: str) -> date:
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"date '{v}' (use YYYY-MM-DD or DD/MM/YYYY)")


def _cents(v: str) -> int:
    s = re.sub(r"[€\s  ]", "", v or "")
    if not s:
        return 0
    if "," in s and "." in s:  # 1.234,56 or 1,234.56
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    return round(float(s) * 100)


def _header_map(fields: list[str]) -> dict[str, str]:
    def key(f: str) -> str:
        f = unicodedata.normalize("NFKD", f).encode("ascii", "ignore").decode().strip().lower()
        return re.sub(r"[^a-z_]", "", f.replace(" ", "_"))
    norm = {key(f): f for f in fields}
    out = {}
    for key, names in COLUMNS.items():
        hit = next((norm[n] for n in names if n in norm), None)
        if hit:
            out[key] = hit
    missing = [k for k in ("customer", "postal_code", "invoice_number", "invoice_date", "amount") if k not in out]
    if missing:
        raise ImportError_(f"missing column(s): {', '.join(missing)}")
    return out


def parse(text: str) -> tuple[list[dict], list[str]]:
    sample = text[:2048]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=delim)
    cols = _header_map(reader.fieldnames or [])
    rows, errors = [], []
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            errors.append(f"only the first {MAX_ROWS} rows were read")
            break
        get = lambda k: (raw.get(cols[k]) or "").strip() if k in cols else ""  # noqa: E731
        try:
            name, cp = get("customer"), re.sub(r"\D", "", get("postal_code"))
            if not name or len(cp) != 5:
                raise ValueError("customer name and a 5-digit postal code are required")
            inv_date = _date(get("invoice_date"))
            siren = re.sub(r"\D", "", get("siren"))[:9] or None
            if siren and len(siren) != 9:
                raise ValueError(f"SIREN '{get('siren')}' must have 9 digits")
            rows.append({"customer": name, "siren": siren, "postal_code": cp, "city": get("city") or None,
                         "number": get("invoice_number") or f"L{n}", "invoice_date": inv_date,
                         "due_date": _date(get("due_date")) if get("due_date") else inv_date + timedelta(DEFAULT_TERMS_DAYS),
                         "amount_cents": _cents(get("amount")), "paid_cents": _cents(get("paid"))})
        except ValueError as e:
            errors.append(f"line {n}: {e}")
    return rows, errors[:20]


def import_csv(text: str) -> dict:
    rows, errors = parse(text)
    if not rows:
        raise ImportError_("no valid row" + (f": {errors[0]}" if errors else ""))
    created_customers, created_invoices, customer_ids = 0, 0, {}
    with transaction() as conn:
        for r in rows:
            key = (r["customer"].upper(), r["postal_code"])
            if key not in customer_ids:
                found = conn.execute("""select id from customers where dataset = 'demo' and upper(crm_name) = %s
                                        and postal_code = %s""", key).fetchone()
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
            conn.execute("""insert into invoices (customer_id, number, invoice_date, due_date, amount_cents, paid_cents)
                            values (%s, %s, %s, %s, %s, %s)""",
                         (cid, r["number"], r["invoice_date"], r["due_date"], r["amount_cents"], r["paid_cents"]))
            created_invoices += 1
        new_cases = match_customers(conn)
        to_check = conn.execute(
            """select id, crm_siren from customers where id = any(%s) and identity_status = 'UNVERIFIED'
               and not exists (select 1 from cases where customer_id = customers.id)""",
            (list(customer_ids.values()),)).fetchall()
    started = []
    for case_id in new_cases:
        case = _case_customer(case_id)
        try:
            started.append(runs.investigate_case(case_id, case, "Opened at import by the exact-SIREN rule."))
        except runs.RunLimitError:
            break
    queued = to_check[:MAX_IDENTITY_CHECKS]
    if queued:
        threading.Thread(target=_identity_worker, args=(queued,), daemon=True, name="import-identity").start()
    return {"rows": len(rows), "customers_created": created_customers, "invoices_created": created_invoices,
            "cases_opened": len(new_cases), "investigations_started": len(started),
            "identity_checks_queued": len(queued), "errors": errors}


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
