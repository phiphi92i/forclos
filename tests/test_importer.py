from datetime import date

import pytest

from app.importer import ImportError_, map_columns, parse

EXPORT = """invoice_number,customer_name,siren,invoice_date,due_date,amount_eur,paid_eur,remaining_eur,delivery_date,description
FAC-MD-26091,Martin Distrib.,999100010,2026-09-01,2026-10-01,18400,0,18400,2026-08-26,"Lot C - livraison avant jugement, facture après"
FAC-LL-091,Le Lunch Lib,999100028,2026-09-24,2026-10-24,3300,500,2800,2026-09-22,Réassort cuisine
FAC-CB-101,Côte Blanche,999100086,2026-10-03,2026-11-02,9800,0,9800,,Mobilier livré selon email
"""


def test_english_export_without_postal_code():
    rows, problems, cols = parse(EXPORT)
    assert problems == []
    assert cols["customer"] == "customer_name" and cols["amount"] == "amount_eur"
    assert cols["remaining"] == "remaining_eur" and cols["delivery_date"] == "delivery_date"
    first, second, third = rows
    assert first["postal_code"] is None and first["siren"] == "999100010"
    assert first["amount_cents"] == 1840000 and first["delivery_date"] == date(2026, 8, 26)
    assert "avant jugement" in first["description"]
    assert second["paid_cents"] == 50000
    assert third["delivery_date"] is None


def test_french_headers_semicolons_and_decimal_commas():
    text = ("client;code postal;ville;n° facture;date facture;échéance;montant TTC;réglé\n"
            "Maison Vivier;6500;Bron;FA-1;28/08/2026;27/09/2026;3 120,40;100,00\n")
    (row,), problems, cols = parse(text)
    assert problems == []
    assert cols["invoice_number"] == "n° facture" and cols["due_date"] == "échéance"
    assert row["postal_code"] == "06500"  # leading zero dropped by a spreadsheet, restored
    assert row["amount_cents"] == 312040 and row["paid_cents"] == 10000


def test_remaining_only_and_missing_invoice_date():
    text = "client,reste à payer,date livraison\nAtelier Nord,5900,16/07/2026\n"
    (row,), problems, _ = parse(text)
    assert problems == []
    assert row["amount_cents"] == 590000 and row["paid_cents"] == 0
    assert row["invoice_date"] == date(2026, 7, 16)  # falls back to the delivery date
    assert row["number"] == "L2"


def test_bad_rows_are_reported_not_fatal():
    text = "client,date,montant,siren\nA,2026-08-01,100,123\nB,not a date,100,\nC,2026-08-02,,\nD,2026-08-03,50,\n"
    rows, problems, _ = parse(text)
    assert [r["customer"] for r in rows] == ["A", "D"]
    assert rows[0]["siren"] is None
    assert any("line 2" in p and "SIREN" in p for p in problems)
    assert any("line 3" in p for p in problems) and any("line 4" in p for p in problems)


def test_customer_number_is_not_the_invoice_number():
    cols = map_columns(["N° client", "Nom client", "N° facture", "Montant"])
    assert cols["invoice_number"] == "N° facture" and cols["customer"] == "Nom client"


def test_no_customer_column_is_a_clear_error():
    with pytest.raises(ImportError_, match="Columns found: date, montant"):
        parse("date,montant\n2026-08-01,100\n")
