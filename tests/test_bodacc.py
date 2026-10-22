"""Parser tests. bodacc_assumed.json is a GUESS of the real shape.
Build step 1: run scripts/sample_bodacc.py, which writes tests/fixtures/bodacc_real.json,
then make test_real_sample pass (adjust app/bodacc.py, not the test)."""
import json
from datetime import date
from pathlib import Path

import pytest

from app.bodacc import extract_officers, extract_sirens, parse_date, parse_notice

FIX = Path(__file__).parent / "fixtures"


def test_parse_assumed_shape():
    recs = json.loads((FIX / "bodacc_assumed.json").read_text())
    a, b = (parse_notice(r) for r in recs)
    assert a["siren"] == "912345678"
    assert a["is_legal_person"] is True
    assert a["date_parution"] == date(2026, 9, 1)
    assert a["jugement_date"] == date(2026, 8, 27)
    assert a["event_kind"] == "OPENING" and a["procedure"] == "REDRESSEMENT"
    assert any(o["role"].startswith("mandataire") for o in a["officers"])
    assert b["event_kind"] == "CONVERSION" and b["procedure"] == "LIQUIDATION"
    assert b["jugement_date"] == date(2026, 10, 8)


def test_helpers():
    assert extract_sirens(["912 345 678", "912345678"]) == ["912345678"]
    assert parse_date("2026-09-01T00:00:00+00:00") == date(2026, 9, 1)
    assert parse_date("01/09/2026") == date(2026, 9, 1)
    assert parse_date("1er septembre 2026") == date(2026, 9, 1)
    assert extract_officers("désignant liquidateur SELARL X en la personne de Me Y, ")[0]["role"] == "liquidateur"


@pytest.mark.skipif(not (FIX / "bodacc_real.json").exists(), reason="run scripts/sample_bodacc.py first")
def test_real_sample():
    recs = json.loads((FIX / "bodacc_real.json").read_text())
    parsed = [parse_notice(r) for r in recs]
    assert len(parsed) >= 10
    assert all(p["date_parution"] for p in parsed)
    # Unregistered debtors (associations, syndicats de copropriété, some individuals) carry no
    # identifier at all in the source; every record that does carry one must yield a SIREN.
    has_id = [p for p in parsed if p["raw"].get("registre") or '"numeroIdentification' in str(p["raw"].get("listepersonnes"))]
    assert len(has_id) / len(parsed) > 0.8
    assert all(p["siren"] for p in has_id), "SIREN not extracted from a record that has one"
    assert sum(p["jugement_date"] is not None for p in parsed) / len(parsed) > 0.9
    assert sum(p["event_kind"] != "OTHER" for p in parsed) / len(parsed) > 0.7
    assert any(p["event_kind"] == "OPENING" for p in parsed)
