from datetime import date

from app.legal import (
    Category, EventKind, Notice, Procedure, add_months, classify_claim, classify_judgment,
    compute_deadlines, deadline_after_months, easter, split_due,
)


def test_easter():
    assert easter(2025) == date(2025, 4, 20)
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2027) == date(2027, 3, 28)


def test_add_months_quantieme():
    assert add_months(date(2026, 8, 15), 2) == date(2026, 10, 15)
    assert add_months(date(2026, 12, 31), 2) == date(2027, 2, 28)   # no 31 Feb -> last day
    assert add_months(date(2027, 12, 31), 2) == date(2028, 2, 29)   # leap year
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_weekend_and_holiday_extension():
    # 31 Oct 2026 is a Saturday, 1 Nov a Sunday and a holiday -> Monday 2 Nov
    assert deadline_after_months(date(2026, 8, 31), 2) == date(2026, 11, 2)
    # 28 Feb 2027 is a Sunday -> Monday 1 Mar
    assert deadline_after_months(date(2026, 12, 31), 2) == date(2027, 3, 1)
    # 14 May 2026 = Ascension (Thursday) -> Friday 15 May
    assert deadline_after_months(date(2026, 3, 14), 2) == date(2026, 5, 15)
    # 14 July 2026 is a Tuesday holiday -> Wednesday 15
    assert deadline_after_months(date(2026, 5, 14), 2) == date(2026, 7, 15)


def test_sixty_days_is_wrong():
    from datetime import timedelta
    pub = date(2026, 7, 1)
    assert pub + timedelta(days=60) == date(2026, 8, 30)
    assert deadline_after_months(pub, 2) == date(2026, 9, 1)


def test_classify_judgment():
    assert classify_judgment("Jugement d'ouverture", "Jugement d'ouverture d'une procédure de redressement judiciaire") == (EventKind.OPENING, Procedure.REDRESSEMENT)
    assert classify_judgment("Jugement d'ouverture", "Jugement d'ouverture de liquidation judiciaire") == (EventKind.OPENING, Procedure.LIQUIDATION)
    assert classify_judgment(None, "Jugement d'ouverture d'une procédure de sauvegarde") == (EventKind.OPENING, Procedure.SAUVEGARDE)
    assert classify_judgment("Jugement de conversion", "Jugement de conversion en liquidation judiciaire") == (EventKind.CONVERSION, Procedure.LIQUIDATION)
    assert classify_judgment(None, "Jugement de conversion de la procédure de sauvegarde en redressement judiciaire") == (EventKind.CONVERSION, Procedure.REDRESSEMENT)
    assert classify_judgment(None, "Jugement prononçant la résolution du plan de redressement et la liquidation judiciaire") == (EventKind.PLAN_RESOLUTION, Procedure.LIQUIDATION)
    assert classify_judgment("Jugement de clôture", "Jugement de clôture pour insuffisance d'actif")[0] == EventKind.CLOSURE
    assert classify_judgment(None, "Jugement arrêtant le plan de redressement")[0] == EventKind.PLAN
    assert classify_judgment(None, "Jugement prononçant la liquidation judiciaire")[0] == EventKind.PRONOUNCED_LJ


def _n(i, pub, jug, kind, proc=None):
    return Notice(id=i, date_parution=pub, jugement_date=jug, kind=kind, procedure=proc)


def test_conversion_does_not_restart_deadline():
    hist = [
        _n("A1", date(2026, 9, 1), date(2026, 8, 27), EventKind.OPENING, Procedure.REDRESSEMENT),
        _n("A2", date(2026, 10, 13), date(2026, 10, 8), EventKind.CONVERSION, Procedure.LIQUIDATION),
    ]
    d = compute_deadlines(hist)
    assert d.status == "OK"
    assert d.anchor_notice_id == "A1"
    assert d.claim_deadline == date(2026, 11, 2)     # 1 Nov is Sunday + holiday
    assert d.opening_judgment_date == date(2026, 8, 27)
    assert d.current_procedure == Procedure.LIQUIDATION
    assert d.revendication_deadline == date(2026, 12, 1)
    assert any("does NOT restart" in n for n in d.notes)


def test_conversion_without_opening_is_review():
    d = compute_deadlines([_n("A2", date(2026, 10, 13), date(2026, 10, 8), EventKind.CONVERSION, Procedure.LIQUIDATION)])
    assert d.status == "REVIEW" and d.claim_deadline is None


def test_outside_metropole_four_months():
    d = compute_deadlines([_n("A1", date(2026, 9, 15), date(2026, 9, 10), EventKind.OPENING, Procedure.LIQUIDATION)],
                          creditor_outside_metropole=True)
    assert d.claim_deadline == date(2027, 1, 15)


def test_plan_resolution_is_review():
    hist = [
        _n("A1", date(2024, 1, 10), date(2024, 1, 5), EventKind.OPENING, Procedure.REDRESSEMENT),
        _n("A2", date(2024, 9, 10), date(2024, 9, 5), EventKind.PLAN),
        _n("A3", date(2026, 10, 1), date(2026, 9, 28), EventKind.PLAN_RESOLUTION, Procedure.LIQUIDATION),
    ]
    d = compute_deadlines(hist)
    assert d.status == "REVIEW" and d.anchor_notice_id == "A3"


def test_classify_claim_uses_fait_generateur():
    jug = date(2026, 9, 10)
    # invoice issued after the judgment for a delivery made before it -> DECLARE
    assert classify_claim(date(2026, 9, 7), jug, 1840000)[0] == Category.DECLARE
    assert classify_claim(date(2026, 9, 10), jug, 100)[0] == Category.POST_OPENING
    assert classify_claim(date(2026, 9, 12), jug, 100)[0] == Category.POST_OPENING
    assert classify_claim(None, jug, 100)[0] == Category.REVIEW
    assert classify_claim(date(2026, 9, 1), jug, 0)[0] == Category.PAID


def test_split_due():
    jug = date(2026, 9, 10)
    items = [(date(2026, 9, 1), 1000), (date(2026, 10, 1), 500)]
    assert split_due(items, jug, Procedure.REDRESSEMENT)["a_echoir_cents"] == 500
    assert split_due(items, jug, Procedure.LIQUIDATION)["echu_cents"] == 1500


def test_republished_opening_keeps_first_publication():
    hist = [
        _n("A1", date(2026, 3, 5), date(2026, 2, 18), EventKind.OPENING, Procedure.REDRESSEMENT),
        _n("A2", date(2026, 3, 27), date(2026, 2, 18), EventKind.OPENING, Procedure.REDRESSEMENT),
    ]
    d = compute_deadlines(hist)
    assert d.anchor_notice_id == "A1" and d.claim_deadline == date(2026, 5, 5)
    assert any("rectificatif" in n for n in d.notes)
