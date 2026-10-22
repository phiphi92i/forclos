"""BODACC client + parser (official DILA open-data API on Opendatasoft, free, no key).

Verified on live data (tests/fixtures/bodacc_real.json): jugement and listepersonnes are
JSON strings inside the JSON; registre is a list like ["890717895", "890 717 895"].
Some courts (notably Alsace-Moselle) publish openings and conversions under the generic
nature "Autre jugement et ordonnance": the event is then read from complementJugement.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

import httpx

from app.legal import EventKind, Procedure, _norm, classify_judgment

BASE = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales"
TIMEOUT = 30

LEGAL_FORMS = r"\b(SAS|SASU|SARL|EURL|SA|SCI|SNC|SCOP|SELARL|SELAS|SCEA|EARL|GAEC|SCA)\b"
_MONTHS = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
           "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12}


# ---------------------------------------------------------------- helpers

def maybe_json(v):
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "{[":
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return v
    return v


def parse_date(v) -> date | None:
    """ISO, dd/mm/yyyy, or '15 mai 2026'."""
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})(?:er)?\s+([a-zéû]+)\s+(\d{4})", s.lower())
    if m and m.group(2) in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    return None


def extract_sirens(*values) -> list[str]:
    found: list[str] = []
    for v in values:
        if v is None:
            continue
        text = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
        for m in re.finditer(r"(?<!\d)(\d{3})[  .]?(\d{3})[  .]?(\d{3})(?!\d)", text):
            s = "".join(m.groups())
            if s not in found:
                found.append(s)
    return found


def _first_person(listepersonnes) -> dict:
    lp = maybe_json(listepersonnes)
    if isinstance(lp, dict):
        p = lp.get("personne", lp)
        if isinstance(p, list):
            p = p[0] if p else {}
        return p if isinstance(p, dict) else {}
    if isinstance(lp, list) and lp:
        p = lp[0]
        return p.get("personne", p) if isinstance(p, dict) else {}
    return {}


_GENERIC_NATURES = ("autre jugement", "extrait de jugement")
_VERB_SYNONYMS = (("ouvre les operations de la ", "ouverture "), ("ouvre la procedure de ", "ouverture "),
                  ("ouvre une procedure de ", "ouverture "), ("prononce la liquidation", "prononcant la liquidation"),
                  ("sur conversion", "conversion"))


def classify_notice(famille: str | None, nature: str | None, complement: str | None) -> tuple[EventKind, Procedure | None]:
    """classify_judgment, plus a fallback on the first clause of the judgment text when the
    nature is generic ("Autre jugement et ordonnance")."""
    kind, procedure = classify_judgment(famille, nature)
    if kind != EventKind.OTHER or not any(g in _norm(nature) for g in _GENERIC_NATURES):
        return kind, procedure
    first = re.split(r" - |\.\s|,", _norm(complement), maxsplit=1)[0]
    for old, new in _VERB_SYNONYMS:
        first = first.replace(old, new)
    return classify_judgment(None, first)


def extract_officers(text: str) -> list[dict]:
    """Best-effort: mandataire judiciaire / liquidateur / administrateur from the judgment text.
    The agent also reads the raw text, so this only needs to be good, not perfect."""
    out = []
    for m in re.finditer(
        r"(mandataire(?: judiciaire)?|liquidateur(?: judiciaire)?|administrateur(?: judiciaire| provisoire)?)\s*:?\s*"
        r"((?:SELARL|SELAS|SCP|SAS|Me|Maître|M\.|Mme)?[^,;]{3,120})",
        text or "", flags=re.IGNORECASE,
    ):
        role = m.group(1).lower()
        name = re.split(r"\s+-\s+|\.\s*Les\s|\.\s+[A-ZÉ]", m.group(2))[0].strip().rstrip(".")
        if name.lower().startswith(("à ", "ou ", "sur ", "dans ", "associ")):
            continue
        out.append({"role": role, "text": name})
    return out


# ---------------------------------------------------------------- parser

def parse_notice(rec: dict) -> dict:
    """Normalise one BODACC record into the columns of bodacc_notices."""
    jug = maybe_json(rec.get("jugement")) or {}
    if not isinstance(jug, dict):
        jug = {"complementJugement": str(jug)}
    person = _first_person(rec.get("listepersonnes"))

    famille = jug.get("famille")
    nature = jug.get("nature")
    complement = jug.get("complementJugement") or jug.get("complement") or ""
    kind, procedure = classify_notice(famille, nature, complement)

    denomination = (person.get("denomination") or rec.get("commercant") or "").strip() or None
    type_personne = (person.get("typePersonne") or "").lower()
    if type_personne in ("pm", "pp"):
        is_legal_person = type_personne == "pm"
    elif denomination and re.search(LEGAL_FORMS, denomination.upper()):
        is_legal_person = True
    else:
        is_legal_person = None

    sirens = extract_sirens(rec.get("registre"), person.get("numeroImmatriculation"), person.get("inscriptionRM"))
    return {
        "id": str(rec.get("id") or rec.get("numeroannonce")),
        "siren": sirens[0] if sirens else None,
        "denomination": denomination,
        "is_legal_person": is_legal_person,
        "ville": rec.get("ville"),
        "cp": rec.get("cp"),
        "departement": rec.get("numerodepartement") or rec.get("departement_nom_officiel"),
        "tribunal": rec.get("tribunal"),
        "date_parution": parse_date(rec.get("dateparution")),
        "jugement_famille": famille,
        "jugement_nature": nature,
        "jugement_date": parse_date(jug.get("date")),
        "complement": complement,
        "officers": extract_officers(complement),
        "event_kind": kind.value,
        "procedure": procedure.value if procedure else None,
        "url": rec.get("url_complete"),
        "raw": rec,
    }


# ---------------------------------------------------------------- client

def _get(path: str, params: dict) -> dict | list:
    r = httpx.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_collective_page(since: date, until: date | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    where = f'familleavis="collective" AND dateparution>=date\'{since.isoformat()}\''
    if until:
        where += f" AND dateparution<=date'{until.isoformat()}'"
    data = _get("/records", {"where": where, "order_by": "dateparution desc", "limit": limit, "offset": offset})
    return data.get("results", [])


def export_collective(since: date, until: date | None = None) -> list[dict]:
    """Bulk export, no 10k offset cap. Use for the initial 60-day ingest."""
    where = f'familleavis="collective" AND dateparution>=date\'{since.isoformat()}\''
    if until:
        where += f" AND dateparution<=date'{until.isoformat()}'"
    r = httpx.get(f"{BASE}/exports/json", params={"where": where}, timeout=180)
    r.raise_for_status()
    return r.json()


def fetch_history(siren: str) -> list[dict]:
    """All collective-procedure notices for one SIREN, any date. registre is an exact-match array field."""
    if not re.fullmatch(r"\d{9}", siren or ""):
        return []
    data = _get("/records", {"where": f'familleavis="collective" AND registre="{siren}"', "limit": 100,
                             "order_by": "dateparution asc"})
    recs = data.get("results", [])
    return [r for r in recs if siren in extract_sirens(r.get("registre"), r.get("listepersonnes"))]
