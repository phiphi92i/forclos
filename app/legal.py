"""FORCLOS legal engine. Deterministic. No LLM in this file.

Scope (shown in the UI): unsecured trade creditor (créancier chirographaire)
established in metropolitan France, ordinary sauvegarde / redressement /
liquidation judiciaire. Everything else is flagged for lawyer review.

Rules implemented:
- Claim filing deadline: 2 months from BODACC publication of the OPENING judgment
  (R622-24 C. com.), +2 months if the creditor is outside metropolitan France.
- A conversion (e.g. RJ -> LJ) does NOT restart the deadline (Cass. com.).
- Revendication (retention of title): 3 months from publication of the opening
  judgment (L624-9 C. com.).
- Relief from forclusion (relevé de forclusion): 6 months from publication (L622-26).
- Month arithmetic: same day-of-month ("quantième"), else last day of month (art. 641 CPC).
- A deadline ending on Saturday, Sunday or a public holiday moves to the next
  working day (art. 642 CPC).
- Pre/post-opening split uses the FAIT GÉNÉRATEUR, not the invoice date. The
  opening judgment takes effect from 0h on its date, so a same-day fait
  générateur is post-opening.
- Creditors holding a published security or published contract are notified
  personally and their deadline runs from that notice: out of scope -> REVIEW.
"""
from __future__ import annotations

import calendar
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum


# ---------------------------------------------------------------- calendar

def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def french_public_holidays(year: int) -> set[date]:
    """Fêtes légales (L3133-1 C. trav.). Alsace-Moselle extras not included."""
    e = easter(year)
    return {
        date(year, 1, 1),
        e + timedelta(days=1),   # lundi de Pâques
        date(year, 5, 1),
        date(year, 5, 8),
        e + timedelta(days=39),  # Ascension
        e + timedelta(days=50),  # lundi de Pentecôte
        date(year, 7, 14),
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
    }


def add_months(d: date, months: int) -> date:
    """Art. 641 al. 2 CPC: same quantième, else last day of the month."""
    y, m0 = divmod(d.month - 1 + months, 12)
    y += d.year
    m = m0 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def next_working_day(d: date) -> date:
    """Art. 642 CPC."""
    while d.weekday() >= 5 or d in french_public_holidays(d.year):
        d += timedelta(days=1)
    return d


def deadline_after_months(start: date, months: int) -> date:
    return next_working_day(add_months(start, months))


# ---------------------------------------------------------------- judgments

class EventKind(str, Enum):
    OPENING = "OPENING"                  # starts a procedure: anchors deadlines
    CONVERSION = "CONVERSION"            # does not restart anything
    PRONOUNCED_LJ = "PRONOUNCED_LJ"      # "prononçant la liquidation": opening or conversion, needs history
    PLAN_RESOLUTION = "PLAN_RESOLUTION"  # résolution du plan + new procedure
    PLAN = "PLAN"
    CLOSURE = "CLOSURE"
    CLAIMS_LIST = "CLAIMS_LIST"          # avis de dépôt de l'état / liste des créances: procedure already running
    OTHER = "OTHER"


class Procedure(str, Enum):
    SAUVEGARDE = "SAUVEGARDE"
    SAUVEGARDE_ACCELEREE = "SAUVEGARDE_ACCELEREE"
    REDRESSEMENT = "REDRESSEMENT"
    LIQUIDATION = "LIQUIDATION"


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("'", " ").split())


def _procedure_in(text: str) -> Procedure | None:
    if "liquidation" in text:
        return Procedure.LIQUIDATION
    if "redressement" in text:
        return Procedure.REDRESSEMENT
    if "sauvegarde acceleree" in text:
        return Procedure.SAUVEGARDE_ACCELEREE
    if "sauvegarde" in text:
        return Procedure.SAUVEGARDE
    return None


def classify_judgment(famille: str | None, nature: str | None) -> tuple[EventKind, Procedure | None]:
    """Classify a BODACC judgment from its 'famille' + 'nature' strings."""
    t = _norm(f"{famille or ''} {nature or ''}")
    if "avis de depot" in t or "etat des creances" in t or "liste des creances" in t:
        return EventKind.CLAIMS_LIST, None
    if "conversion" in t:
        if "en liquidation" in t:
            return EventKind.CONVERSION, Procedure.LIQUIDATION
        if "en redressement" in t:
            return EventKind.CONVERSION, Procedure.REDRESSEMENT
        return EventKind.CONVERSION, _procedure_in(t)
    if "resolution du plan" in t:
        after = t.split("resolution du plan", 1)[1]
        after = after.split(" et ", 1)[1] if " et " in after else after
        return EventKind.PLAN_RESOLUTION, _procedure_in(after)
    if "cloture" in t:
        return EventKind.CLOSURE, None
    if "ouverture" in t:
        return EventKind.OPENING, _procedure_in(t)
    if "prononcant la liquidation" in t:
        return EventKind.PRONOUNCED_LJ, Procedure.LIQUIDATION
    if "plan" in t:
        return EventKind.PLAN, None
    return EventKind.OTHER, None


# ---------------------------------------------------------------- deadlines

@dataclass
class Notice:
    id: str
    date_parution: date
    jugement_date: date | None
    kind: EventKind
    procedure: Procedure | None = None
    nature: str = ""


@dataclass
class Deadlines:
    status: str                              # OK | REVIEW | CLOSED
    anchor_notice_id: str | None = None
    anchor_publication: date | None = None
    opening_judgment_date: date | None = None
    current_procedure: Procedure | None = None
    claim_deadline: date | None = None
    revendication_deadline: date | None = None
    relief_deadline: date | None = None
    notes: list[str] = field(default_factory=list)

    def days_left(self, today: date) -> int | None:
        return None if self.claim_deadline is None else (self.claim_deadline - today).days


def compute_deadlines(history: list[Notice], creditor_outside_metropole: bool = False) -> Deadlines:
    """Deadlines from the full BODACC history of ONE debtor (one SIREN)."""
    hist = sorted(history, key=lambda n: (n.date_parution, n.id))
    anchor: Notice | None = None
    procedure: Procedure | None = None
    status = "OK"
    notes: list[str] = []

    for n in hist:
        if n.kind == EventKind.OPENING:
            if anchor is not None and n.jugement_date and n.jugement_date == anchor.jugement_date:
                notes.append(f"Same opening judgment published again {n.date_parution} (rectificatif). Deadline kept "
                             f"on the first publication {anchor.date_parution}: the earliest date is the safe one.")
                continue
            if anchor is not None:
                notes.append(f"New opening judgment published {n.date_parution}: new procedure, deadlines re-anchored.")
            anchor, procedure = n, n.procedure
            if n.procedure == Procedure.SAUVEGARDE_ACCELEREE:
                status = "REVIEW"
                notes.append("Accelerated safeguard only affects listed creditors. Lawyer review.")
        elif n.kind == EventKind.PLAN_RESOLUTION:
            anchor, procedure, status = n, n.procedure, "REVIEW"
            notes.append(
                f"Plan resolution published {n.date_parution} opens a new procedure. New claims must be filed; "
                "claims already admitted under the plan follow L626-27. Lawyer review."
            )
        elif n.kind in (EventKind.CONVERSION, EventKind.PRONOUNCED_LJ):
            if anchor is None:
                status = "REVIEW"
                notes.append(
                    f"{n.kind.value} published {n.date_parution} but no opening judgment in history. "
                    "Never compute the deadline from a conversion. Fetch older history."
                )
            else:
                procedure = n.procedure or procedure
                notes.append(
                    f"Conversion published {n.date_parution} does NOT restart the claim deadline "
                    f"(still anchored on the opening published {anchor.date_parution})."
                )
        elif n.kind == EventKind.CLOSURE and anchor is not None:
            status = "CLOSED"
            notes.append(f"Closure published {n.date_parution}.")

    if anchor is None:
        return Deadlines(status="REVIEW", notes=notes or ["No opening judgment found."])

    months = 4 if creditor_outside_metropole else 2
    pub = anchor.date_parution
    return Deadlines(
        status=status,
        anchor_notice_id=anchor.id,
        anchor_publication=pub,
        opening_judgment_date=anchor.jugement_date,
        current_procedure=procedure,
        claim_deadline=deadline_after_months(pub, months),
        revendication_deadline=deadline_after_months(pub, 3),
        relief_deadline=deadline_after_months(pub, 6),
        notes=notes,
    )


# ---------------------------------------------------------------- claims

class Basis(str, Enum):
    """What dates the claim (fait générateur). The agent must pick one AND cite evidence."""
    DELIVERY = "DELIVERY"                        # each delivery under a framework supply contract
    SERVICE_PERFORMED = "SERVICE_PERFORMED"      # successive services: date the service was performed
    ORDER_ACCEPTANCE = "ORDER_ACCEPTANCE"        # one-off sale: contract formed at order acceptance
    CONTRACT_CONCLUSION = "CONTRACT_CONCLUSION"  # e.g. loan: date of the contract


class Category(str, Enum):
    DECLARE = "DECLARE"            # pre-opening, unpaid: goes in the claim
    POST_OPENING = "POST_OPENING"  # arose after opening: not in the claim (L622-17 regime), review
    PAID = "PAID"
    REVIEW = "REVIEW"              # missing or conflicting evidence


def classify_claim(fait_generateur: date | None, opening_judgment_date: date | None,
                   outstanding_cents: int) -> tuple[Category, str]:
    if outstanding_cents <= 0:
        return Category.PAID, "Fully paid."
    if fait_generateur is None or opening_judgment_date is None:
        return Category.REVIEW, "Fait générateur or opening judgment date unknown."
    if fait_generateur < opening_judgment_date:
        return Category.DECLARE, f"Arose {fait_generateur}, before the opening judgment of {opening_judgment_date}."
    if fait_generateur == opening_judgment_date:
        return Category.POST_OPENING, ("Arose on the judgment day. The judgment takes effect from 0h, "
                                       "so this is post-opening. Flag for review.")
    return Category.POST_OPENING, (f"Arose {fait_generateur}, after the opening judgment of {opening_judgment_date}. "
                                   "Not in the claim; payable at due date if it meets L622-17.")


def split_due(items: list[tuple[date, int]], opening_judgment_date: date,
              opening_procedure: Procedure | None) -> dict:
    """Claim must state amounts due at the judgment date and amounts to fall due (L622-25).
    items: (due_date, outstanding_cents) for DECLARE invoices.
    An LJ opening makes non-due claims due (L643-1)."""
    echu = a_echoir = 0
    future: list[dict] = []
    for due, cents in items:
        if opening_procedure == Procedure.LIQUIDATION or due <= opening_judgment_date:
            echu += cents
        else:
            a_echoir += cents
            future.append({"due_date": due.isoformat(), "cents": cents})
    return {"echu_cents": echu, "a_echoir_cents": a_echoir, "a_echoir_detail": future,
            "total_cents": echu + a_echoir}
