"""Two comparison systems for the benchmark. Keep them honest: they are what a
reasonable non-agent tool would do, not strawmen.

NAIVE  = what a basic "BODACC alert" does: match on SIREN if present, else exact
         normalised name; deadline = latest notice + 60 days; pre/post split by invoice date.
RULES  = FORCLOS without the agent: SIREN match only (no identity repair), the
         correct legal engine (app/legal.py), pre/post split by invoice date.
FORCLOS = RULES + the agent (identity repair, history lookup, document evidence).
"""
from __future__ import annotations

from datetime import date, timedelta

from app.legal import Category, Notice, classify_claim, compute_deadlines
from app.normalize import norm_name


# ---------------------------------------------------------------- matching

def naive_match(crm_name: str, crm_siren: str | None, notices: list[dict]) -> list[dict]:
    if crm_siren:
        return [n for n in notices if n.get("siren") == crm_siren]
    key = norm_name(crm_name)
    return [n for n in notices if norm_name(n.get("denomination")) == key]


def rules_match(crm_siren: str | None, notices: list[dict]) -> list[dict]:
    return [n for n in notices if crm_siren and n.get("siren") == crm_siren]


# ---------------------------------------------------------------- deadlines

def naive_deadline(history: list[Notice]) -> date | None:
    """Restarts the clock on every new notice. This is the bug that makes creditors forclos."""
    if not history:
        return None
    latest = max(history, key=lambda n: n.date_parution)
    return latest.date_parution + timedelta(days=60)


def rules_deadline(history: list[Notice]) -> date | None:
    return compute_deadlines(history).claim_deadline


# ---------------------------------------------------------------- invoices

def invoice_date_classify(invoice_date: date, opening_judgment_date: date | None,
                          outstanding_cents: int) -> Category:
    """Both baselines date the claim by the invoice date (wrong: the fait générateur counts)."""
    return classify_claim(invoice_date, opening_judgment_date, outstanding_cents)[0]
