"""Frozen demo seed: data/demo_seed.json (written by scripts/seed_demo.py) -> database.
Public BODACC notices and register records are real; the creditor's ledger is fictional."""
from __future__ import annotations

import json
from pathlib import Path

from app.cases import match_customers
from app.db import Jsonb, transaction
from app.ingest import upsert_records

SEED = Path(__file__).resolve().parents[1] / "data" / "demo_seed.json"


def insert_customer(conn, c: dict, dataset: str = "demo", bench_case_id: str | None = None) -> int:
    cid = conn.execute(
        """insert into customers (crm_name, crm_siren, address, postal_code, city, payment_terms, dataset,
           bench_case_id) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (c["crm_name"], c.get("crm_siren"), c.get("address"), c.get("postal_code"), c.get("city"),
         c.get("payment_terms", "NET30"), dataset, bench_case_id)).fetchone()["id"]
    contracts = {}
    for k in c.get("contracts", []):
        contracts[k["key"]] = conn.execute(
            """insert into contracts (customer_id, kind, retention_of_title, published_security, signed_on, body)
               values (%s, %s, %s, %s, %s, %s) returning id""",
            (cid, k["kind"], k.get("retention_of_title", False), k.get("published_security", False),
             k.get("signed_on"), k.get("body"))).fetchone()["id"]
    invoices = {}
    for i in c.get("invoices", []):
        invoices[i["key"]] = conn.execute(
            """insert into invoices (customer_id, number, invoice_date, due_date, amount_cents, paid_cents, contract_id)
               values (%s, %s, %s, %s, %s, %s, %s) returning id""",
            (cid, i["number"], i["invoice_date"], i["due_date"], i["amount_cents"], i.get("paid_cents", 0),
             contracts.get(i.get("contract")))).fetchone()["id"]
    for d in c.get("documents", []):
        conn.execute(
            """insert into documents (customer_id, invoice_id, kind, doc_date, body)
               values (%s, %s, %s, %s, %s)""",
            (cid, invoices.get(d.get("invoice")), d["kind"], d.get("doc_date"), d["body"]))
    return cid


def load_seed(path: Path = SEED) -> dict:
    seed = json.loads(path.read_text())
    with transaction() as conn:
        conn.execute("delete from customers where dataset = 'demo'")
        conn.execute("delete from agent_runs where case_id is null and customer_id is null")
        upsert_records(conn, seed.get("notices", []))
        for key, payload in seed.get("company_cache", {}).items():
            conn.execute("""insert into company_cache (cache_key, payload) values (%s, %s)
                            on conflict (cache_key) do update set payload = excluded.payload""",
                         (key, Jsonb(payload)))
        ids = [insert_customer(conn, c) for c in seed["customers"]]
        new_cases = match_customers(conn)
    return {"customers": len(ids), "notices": len(seed.get("notices", [])), "cases": len(new_cases)}
