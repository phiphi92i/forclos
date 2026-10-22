"""Build the benchmark: real BODACC debtors + real register records, CRM side degraded on purpose
(benchmark/perturb.py), so ground truth is known. Writes data/bench_cases.json.
Fixed seed; 30 dev / 20 held out. Run: python -m benchmark.build
Only debtors whose claim deadline is still open at build time: FORCLOS reads the BODACC daily, so the case
that matters is a notice arriving while the creditor can still file (a conversion inside the claim window)."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from app import bodacc, legal, sirene
from app.bodacc import parse_notice
from app.cases import CASE_KINDS, to_legal_notice
from app.db import query
from benchmark.perturb import abbreviate, trade_name, typo

OUT = Path(__file__).resolve().parents[1] / "data" / "bench_cases.json"
SEED = 20261022
TARGET = {"EXACT_SIREN": 6, "TRADE_NAME": 8, "ABBREV_TYPO": 8, "STALE_SIREN": 6, "HOMONYM_HEALTHY": 8,
          "LATE_INVOICE": 8, "CONVERSION": 6}
N_DEV = 30
SOLE_TRADER = "1000"


def history(siren: str) -> list[dict]:
    return [parse_notice(r) for r in bodacc.fetch_history(siren)]


def truth_deadlines(hist: list[dict]) -> legal.Deadlines:
    return legal.compute_deadlines([to_legal_notice(n) for n in hist if n["event_kind"] in CASE_KINDS])


def ledger(rng: random.Random, opening: date, address: str, late: bool, post: bool) -> dict:
    """Fictional invoices + delivery notes. Truth category comes from the delivery date (fait générateur)."""
    invoices, documents, truth = [], [], 0
    specs = [(opening - timedelta(days=rng.randint(20, 45)), 0), (opening - timedelta(days=rng.randint(6, 18)), 0)]
    if late:   # invoiced after the judgment, delivered before it
        specs.append((opening - timedelta(days=rng.randint(1, 5)), rng.randint(7, 12)))
    if post:   # delivered and invoiced after the judgment: truly post-opening
        specs.append((opening + timedelta(days=rng.randint(2, 9)), 1))
    for k, (delivered, lag) in enumerate(specs):
        cents = rng.randint(800, 22000) * 100
        inv_date = delivered + timedelta(days=lag)
        key = f"i{k}"
        invoices.append({"key": key, "number": f"FB-{rng.randint(10000, 99999)}", "invoice_date": inv_date.isoformat(),
                         "due_date": (inv_date + timedelta(days=30)).isoformat(), "amount_cents": cents,
                         "contract": "k"})
        documents.append({"kind": "DELIVERY_NOTE", "invoice": key, "doc_date": delivered.isoformat(), "body": (
            f"MAISON VERDIER DISTRIBUTION · Bon de livraison BL-{rng.randint(10000, 99999)}\n"
            f"Date de livraison : {delivered.strftime('%d/%m/%Y')}\nLivré à : {address}\n"
            + ("Facturation regroupée ultérieurement.\n" if lag > 3 else f"Facture associée : {invoices[-1]['number']}\n")
            + "Marchandise reçue conforme. Signature du client : [signé]")})
        if delivered < opening:
            truth += cents
    contract = {"key": "k", "kind": "FRAMEWORK_SUPPLY", "signed_on": "2025-01-15",
                "body": "Contrat-cadre d'approvisionnement : livraisons successives sur commandes, bon de livraison "
                        "pour chaque livraison, facturation éventuellement regroupée, paiement à 30 jours."}
    return {"contracts": [contract], "invoices": invoices, "documents": documents, "truth_declare_cents": truth}


def candidates() -> list[dict]:
    rows = query(
        """select distinct on (siren) siren, denomination, cp, ville, date_parution, jugement_date, procedure
           from bodacc_notices where event_kind = 'OPENING' and is_legal_person and siren is not null
             and jugement_date is not null and date_parution between current_date - 45 and current_date - 5
             and cp ~ '^[0-8]' order by siren, date_parution""")
    return rows


def main() -> None:
    rng = random.Random(SEED)
    pool = candidates()
    rng.shuffle(pool)
    conv = query(
        """select distinct siren from bodacc_notices where event_kind = 'CONVERSION' and is_legal_person
           and siren is not null and date_parution >= current_date - 40 and cp ~ '^[0-8]'""")
    conv_sirens = [r["siren"] for r in conv]
    rng.shuffle(conv_sirens)

    cases, used, counts = [], set(), {k: 0 for k in TARGET}

    def add(family: str, debtor: dict | None, hist: list[dict], crm: dict, company: dict, late=False, healthy=None):
        d = truth_deadlines(hist) if hist else None
        opening = d.opening_judgment_date if d else None
        addr = f"{crm['crm_name']}, {(healthy or company)['siege']['adresse']}"
        led = ledger(rng, opening or date.today() - timedelta(days=20), addr, late=late, post=rng.random() < 0.4)
        affected = healthy is None
        cases.append({
            "bench_case_id": f"B{len(cases) + 1:03d}", "family": family, **crm, **{k: led[k] for k in
                                                                               ("contracts", "invoices", "documents")},
            "truth_siren": (healthy or company)["siren"], "truth_affected": affected,
            "truth_claim_deadline": d.claim_deadline.isoformat() if affected and d and d.claim_deadline else None,
            "truth_declare_cents": led["truth_declare_cents"] if affected else 0,
            "debtor_siren": debtor["siren"] if debtor else None,
        })
        counts[family] += 1
        print(f"{family:16s} {crm['crm_name'][:34]:34s} crm_siren={crm.get('crm_siren')} truth={(healthy or company)['siren']}")

    def clean_history(siren: str) -> list[dict] | None:
        hist = history(siren)
        d = truth_deadlines(hist)
        return hist if d.status == "OK" and d.claim_deadline and d.claim_deadline > date.today() else None

    # conversions first (scarce)
    for siren in conv_sirens:
        if counts["CONVERSION"] >= TARGET["CONVERSION"]:
            break
        hist = history(siren)
        d = truth_deadlines(hist)
        if d.status != "OK" or not any(n["event_kind"] == "CONVERSION" for n in hist) or d.claim_deadline <= date.today():
            continue
        company = sirene.get_company(siren)
        if not company or company["nature_juridique"] == SOLE_TRADER:
            continue
        used.add(siren)
        add("CONVERSION", {"siren": siren}, hist, {"crm_name": company["nom_complet"].title(), "crm_siren": siren,
            "postal_code": company["siege"]["code_postal"], "city": company["siege"]["commune"]}, company)

    for debtor in pool:
        if all(counts[f] >= TARGET[f] for f in TARGET if f != "CONVERSION"):
            break
        if debtor["siren"] in used:
            continue
        company = sirene.get_company(debtor["siren"])
        if not company or company["nature_juridique"] == SOLE_TRADER or not company["siege"]["code_postal"]:
            continue
        hist = clean_history(debtor["siren"])
        if not hist:
            continue
        used.add(debtor["siren"])
        legal_name = company["nom_raison_sociale"] or company["nom_complet"]
        base = {"postal_code": company["siege"]["code_postal"], "city": company["siege"]["commune"]}
        tn = trade_name(company)
        if tn and counts["TRADE_NAME"] < TARGET["TRADE_NAME"]:
            add("TRADE_NAME", debtor, hist, {"crm_name": tn, "crm_siren": None, **base}, company)
            continue
        if counts["HOMONYM_HEALTHY"] < TARGET["HOMONYM_HEALTHY"]:
            homs = [r for r in sirene.search_company(legal_name, None, per_page=10)
                    if r["siren"] != debtor["siren"] and r["etat_administratif"] == "A"
                    and r["nature_juridique"] != SOLE_TRADER and (r["nom_raison_sociale"] or "").upper() == legal_name.upper()
                    and (r["siege"]["code_postal"] or "")[:2] != base["postal_code"][:2]]
            homs = [h for h in homs if not bodacc.fetch_history(h["siren"])]
            if homs:
                h = homs[0]
                add("HOMONYM_HEALTHY", debtor, hist, {"crm_name": legal_name.title(), "crm_siren": None,
                    "postal_code": h["siege"]["code_postal"], "city": h["siege"]["commune"]}, company, healthy=h)
                continue
        if counts["STALE_SIREN"] < TARGET["STALE_SIREN"]:
            ceased = [r for r in sirene._get("/search", {"q": legal_name, "etat_administratif": "C",
                                                         "per_page": 5}).get("results", [])
                      if r.get("siren") != debtor["siren"] and r.get("nature_juridique") != SOLE_TRADER]
            if ceased:
                add("STALE_SIREN", debtor, hist, {"crm_name": legal_name.title(), "crm_siren": ceased[0]["siren"],
                                                  **base}, company)
                continue
        if counts["ABBREV_TYPO"] < TARGET["ABBREV_TYPO"]:
            name = typo(abbreviate(legal_name), rng) if rng.random() < 0.5 else abbreviate(legal_name)
            if name.upper() != legal_name.upper():
                add("ABBREV_TYPO", debtor, hist, {"crm_name": name, "crm_siren": None, **base}, company)
                continue
        if counts["LATE_INVOICE"] < TARGET["LATE_INVOICE"]:
            add("LATE_INVOICE", debtor, hist, {"crm_name": legal_name.title(), "crm_siren": debtor["siren"], **base},
                company, late=True)
            continue
        if counts["EXACT_SIREN"] < TARGET["EXACT_SIREN"]:
            add("EXACT_SIREN", debtor, hist, {"crm_name": legal_name.title(), "crm_siren": debtor["siren"], **base},
                company)

    rng.shuffle(cases)
    for i, c in enumerate(cases):
        c["split"] = "dev" if i < N_DEV else "holdout"
    OUT.write_text(json.dumps({"seed": SEED, "built_on": date.today().isoformat(), "counts": counts,
                               "cases": cases}, ensure_ascii=False, indent=1))
    print(f"wrote {OUT}: {len(cases)} cases {counts}")


if __name__ == "__main__":
    main()
