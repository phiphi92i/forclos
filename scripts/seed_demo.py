"""Build the frozen demo seed -> data/demo_seed.json, then load it.
Debtors are REAL legal persons from public BODACC notices; every invoice, delivery note and contract
is FICTIONAL (creditor: Maison Verdier Distribution, a fictional Lyon food-service wholesaler).
Run once before noon: python scripts/seed_demo.py. Never re-seed during the pitch: POST /api/demo/reset."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bodacc, sirene  # noqa: E402
from app.bodacc import parse_notice  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "demo_seed.json"
D = date.fromisoformat


def eur(x: float) -> int:
    return round(x * 100)


def inv(key, number, inv_date, amount, paid=None, contract=None, terms=30):
    d = D(inv_date)
    return {"key": key, "number": number, "invoice_date": inv_date,
            "due_date": (d + timedelta(days=terms)).isoformat(), "amount_cents": eur(amount),
            "paid_cents": eur(paid if paid is not None else 0), "contract": contract}


def delivery_note(invoice_key, bl, delivered, address, lines, invoice_number=None, note=""):
    body = (f"MAISON VERDIER DISTRIBUTION · Bon de livraison {bl}\n"
            f"Date de livraison : {D(delivered).strftime('%d/%m/%Y')}\n"
            f"Livré à : {address}\n"
            + "".join(f"- {l}\n" for l in lines)
            + (f"Facture associée : {invoice_number}\n" if invoice_number else "")
            + (note + "\n" if note else "")
            + "Marchandise reçue conforme. Signature du client : [signé]\n"
            "Clause de réserve de propriété : voir contrat-cadre le cas échéant.")
    return {"kind": "DELIVERY_NOTE", "invoice": invoice_key, "doc_date": delivered, "body": body}


FRAMEWORK_BODY = ("Contrat-cadre d'approvisionnement n° CC-{n}. Maison Verdier Distribution fournit des denrées "
                  "alimentaires par livraisons successives sur commandes hebdomadaires. Chaque livraison fait "
                  "l'objet d'un bon de livraison; la facturation peut être regroupée. Paiement à 30 jours. "
                  "{rot}Signé le {signed}.")
ROT = ("Clause de réserve de propriété : les marchandises restent la propriété du fournisseur jusqu'au "
       "paiement intégral du prix. ")

# ---------------------------------------------------------------- scenarios (real debtors, fictional ledger)

A_SIREN, B_SIREN, C_SIREN, D_SIREN = "921339081", "524928900", "852699149", "909659427"
E_DEBTOR_SIREN, E_HEALTHY_SIREN = "915096036", "918501974"

SCENARIOS = [
    {   # A clean: the CRM has the right SIREN; every system gets this one right.
        "scenario": "A_CLEAN", "crm_name": "Restaurant L'Inattendu", "crm_siren": A_SIREN,
        "address": "168 allée de l'Innovation, ZI Richard Bloch", "postal_code": "69700", "city": "Beauvallon",
        "contracts": [{"key": "a1", "kind": "FRAMEWORK_SUPPLY", "signed_on": "2024-11-04",
                       "body": FRAMEWORK_BODY.format(n="2024-118", rot="", signed="04/11/2024")}],
        "invoices": [inv("a0", "FA-2026-0702", "2026-07-10", 2480.00, paid=2480.00, contract="a1"),
                     inv("a1", "FA-2026-0811", "2026-08-21", 2140.50, contract="a1"),
                     inv("a2", "FA-2026-0874", "2026-09-04", 3385.00, contract="a1"),
                     inv("a3", "FA-2026-0915", "2026-09-18", 1912.40, contract="a1")],
        "documents": [
            delivery_note("a1", "BL-2026-3902", "2026-08-20", "Restaurant L'Inattendu, 168 allée de l'Innovation, 69700 Beauvallon",
                          ["Viandes et volailles", "Produits laitiers"], "FA-2026-0811"),
            delivery_note("a2", "BL-2026-4310", "2026-09-03", "Restaurant L'Inattendu, 168 allée de l'Innovation, 69700 Beauvallon",
                          ["Épicerie sèche", "Boissons"], "FA-2026-0874"),
            delivery_note("a3", "BL-2026-4688", "2026-09-17", "Restaurant L'Inattendu, 168 allée de l'Innovation, 69700 Beauvallon",
                          ["Fruits et légumes", "Surgelés"], "FA-2026-0915")],
    },
    {   # B identity: sales typed the trade name, no SIREN. Naive name matching finds nothing.
        "scenario": "B_IDENTITY", "crm_name": "Le Lunch Lib", "crm_siren": None,
        "address": "Centre commercial Carrefour, 232 av. Franklin Roosevelt", "postal_code": "69120",
        "city": "Vaulx-en-Velin",
        "contracts": [{"key": "b1", "kind": "FRAMEWORK_SUPPLY", "signed_on": "2025-02-17",
                       "body": FRAMEWORK_BODY.format(n="2025-031", rot="", signed="17/02/2025")}],
        "invoices": [inv("b1", "FA-2026-0829", "2026-08-28", 4280.00, contract="b1"),
                     inv("b2", "FA-2026-0890", "2026-09-11", 2915.60, contract="b1")],
        "documents": [
            delivery_note("b1", "BL-2026-4015", "2026-08-27",
                          "LE LUNCH LIB, Centre commercial Carrefour, 232 avenue Franklin Roosevelt, 69120 Vaulx-en-Velin",
                          ["Pains et viennoiseries surgelés", "Charcuterie"], "FA-2026-0829"),
            delivery_note("b2", "BL-2026-4402", "2026-09-10",
                          "LE LUNCH LIB, Centre commercial Carrefour, 232 avenue Franklin Roosevelt, 69120 Vaulx-en-Velin",
                          ["Boissons", "Emballages vente à emporter"], "FA-2026-0890")],
    },
    {   # C documents: invoice dated after the judgment for a delivery made before it.
        "scenario": "C_DOCUMENTS", "crm_name": "Villa d'Aristide", "crm_siren": C_SIREN,
        "address": "78 rue Aristide Briand", "postal_code": "69800", "city": "Saint-Priest",
        "contracts": [{"key": "c1", "kind": "FRAMEWORK_SUPPLY", "retention_of_title": True, "signed_on": "2025-03-01",
                       "body": FRAMEWORK_BODY.format(n="2025-044", rot=ROT, signed="01/03/2025")}],
        "invoices": [inv("c0", "FA-2026-0688", "2026-07-03", 5210.00, paid=5210.00, contract="c1"),
                     inv("c1", "FA-2026-0790", "2026-08-14", 6820.00, contract="c1"),
                     inv("c2", "FA-2026-0941", "2026-09-14", 18400.00, contract="c1"),
                     inv("c3", "FA-2026-0968", "2026-09-25", 3150.00, contract="c1")],
        "documents": [
            delivery_note("c1", "BL-2026-3811", "2026-08-13", "Villa d'Aristide, 78 rue Aristide Briand, 69800 Saint-Priest",
                          ["Viandes", "Produits de la mer"], "FA-2026-0790"),
            delivery_note("c2", "BL-2026-4471", "2026-09-05", "Villa d'Aristide, 78 rue Aristide Briand, 69800 Saint-Priest",
                          ["Commande séminaire 120 couverts : viandes, fromages, vins", "Épicerie fine"],
                          note="Livraison du samedi 05/09/2026. Facturation regroupée en fin de quinzaine "
                               "(facture FA-2026-0941 du 14/09/2026)."),
            delivery_note("c3", "BL-2026-4790", "2026-09-22", "Villa d'Aristide, 78 rue Aristide Briand, 69800 Saint-Priest",
                          ["Fruits et légumes", "Produits laitiers"], "FA-2026-0968")],
    },
    {   # D conversion: RJ opening, then conversion to LJ. The deadline stays anchored on the opening.
        "scenario": "D_CONVERSION", "crm_name": "Brasserie de Vaucroze", "crm_siren": D_SIREN,
        "address": "Route de Vaucroze", "postal_code": "84700", "city": "Sorgues",
        "contracts": [{"key": "d1", "kind": "FRAMEWORK_SUPPLY", "signed_on": "2025-05-12",
                       "body": FRAMEWORK_BODY.format(n="2025-077", rot="", signed="12/05/2025")}],
        "invoices": [inv("d1", "FA-2026-0655", "2026-07-17", 5640.00, contract="d1"),
                     inv("d2", "FA-2026-0761", "2026-08-07", 2310.75, contract="d1")],
        "documents": [
            delivery_note("d1", "BL-2026-3405", "2026-07-16", "Brasserie de Vaucroze, 84700 Sorgues",
                          ["Produits pour le restaurant de la brasserie", "Boissons"], "FA-2026-0655"),
            delivery_note("d2", "BL-2026-3698", "2026-08-06", "Brasserie de Vaucroze, 84700 Sorgues",
                          ["Épicerie", "Produits laitiers"], "FA-2026-0761")],
    },
    {   # E healthy homonym: same name as a debtor in Montagny (69), different company in Isère.
        "scenario": "E_HOMONYM", "crm_name": "Bella Pizza", "crm_siren": None,
        "address": "14 avenue Charles de Gaulle", "postal_code": "38800", "city": "Le Pont-de-Claix",
        "contracts": [],
        "invoices": [inv("e0", "FA-2026-0721", "2026-07-24", 980.00, paid=980.00),
                     inv("e1", "FA-2026-0951", "2026-09-29", 1240.00)],
        "documents": [delivery_note("e1", "BL-2026-4851", "2026-09-28",
                                    "Bella Pizza, 14 avenue Charles de Gaulle, 38800 Le Pont-de-Claix",
                                    ["Farine, mozzarella, sauce tomate"], "FA-2026-0951")],
    },
]

HEALTHY = ["441137924", "808795793", "419636634", "530342351", "933419160", "519177760", "310174297", "523750586"]


def healthy_customer(i: int, company: dict) -> dict:
    s = company["siege"]
    base = D("2026-08-01") + timedelta(days=7 * i)
    amount = 900 + 431.7 * (i + 1)
    return {"scenario": "HEALTHY", "crm_name": (company["nom_raison_sociale"] or company["nom_complet"]).title(),
            "crm_siren": company["siren"], "address": (s["adresse"] or "").split(" " + (s["code_postal"] or ""))[0],
            "postal_code": s["code_postal"], "city": (s["commune"] or "").title(), "contracts": [],
            "invoices": [inv(f"h{i}a", f"FA-2026-{1100 + 2 * i}", base.isoformat(), amount, paid=amount),
                         inv(f"h{i}b", f"FA-2026-{1101 + 2 * i}", (base + timedelta(days=45)).isoformat(),
                             round(amount * 0.8, 2), paid=0 if i % 2 else round(amount * 0.8, 2))],
            "documents": []}


def main() -> None:
    notices, cache = [], {}
    for siren in (A_SIREN, B_SIREN, C_SIREN, D_SIREN, E_DEBTOR_SIREN):
        hist = bodacc.fetch_history(siren)
        kinds = [parse_notice(r)["event_kind"] for r in hist]
        assert "OPENING" in kinds, f"{siren}: no opening in history"
        notices.extend(hist)
        cache[f"siren:{siren}"] = sirene.get_company(siren)
        print(siren, cache[f"siren:{siren}"]["nom_complet"], kinds)
    assert any(parse_notice(r)["event_kind"] == "CONVERSION" for r in bodacc.fetch_history(D_SIREN))
    assert not bodacc.fetch_history(E_HEALTHY_SIREN), "homonym is not healthy"

    customers = list(SCENARIOS)
    for i, siren in enumerate(HEALTHY):
        if bodacc.fetch_history(siren):
            print("skip healthy candidate with notices:", siren)
            continue
        c = sirene.get_company(siren)
        if c and c["etat_administratif"] == "A" and c["nature_juridique"] != "1000":
            cache[f"siren:{siren}"] = c
            customers.append(healthy_customer(i, c))

    seed = {"label": "Public BODACC data · fictional ledger · live agent run",
            "built_on": date.today().isoformat(), "notices": notices, "company_cache": cache,
            "customers": customers}
    OUT.write_text(json.dumps(seed, ensure_ascii=False, indent=1))
    print(f"wrote {OUT} ({len(customers)} customers, {len(notices)} notices)")


if __name__ == "__main__":
    main()
    if "--no-load" not in sys.argv:
        from app.demo import load_seed
        print(load_seed())
