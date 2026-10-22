"""Benchmark generator primitives. Cases are built from REAL BODACC notices and
REAL company records, then the CRM side is degraded programmatically. Because we
create the degradation, ground truth is known. Say so on the slide:
"real public notices, synthetic CRM perturbations".

Perturbation families (target ~50 cases, 30 dev / 20 held out, seed fixed):
  EXACT_SIREN      CRM has the right SIREN                        -> everyone should get it
  TRADE_NAME       CRM name = enseigne/sigle, no SIREN            -> naive & rules miss
  ABBREV_TYPO      abbreviated / typo'd legal name, no SIREN      -> naive & rules miss
  STALE_SIREN      CRM SIREN belongs to a ceased company at the same address,
                   real debtor is the active one                  -> rules miss
  HOMONYM_HEALTHY  healthy company sharing a name with a debtor   -> naive false positive
  LATE_INVOICE     invoice dated after judgment, delivery before  -> baselines under-declare
  CONVERSION       RJ then conversion to LJ                       -> naive deadline too late
"""
from __future__ import annotations

import random
import re

ABBREVIATIONS = {
    "RESTAURATION": "RESTO", "RESTAURANT": "RESTO", "COMPAGNIE": "CIE", "SOCIETE": "STE",
    "ETABLISSEMENTS": "ETS", "INTERNATIONAL": "INTL", "SAINT": "ST", "SAINTE": "STE",
    "DISTRIBUTION": "DISTRIB", "CONSTRUCTION": "CONSTR", "BOULANGERIE": "BOULANG",
    "TRANSPORTS": "TRANSP", "SERVICES": "SERV", "FRANCE": "FR", "GROUPE": "GRP",
}
FORMS = r"\b(SAS|SASU|SARL|EURL|SA|SCI|SNC|SELARL|SELAS)\b"


def strip_form(name: str) -> str:
    return " ".join(re.sub(FORMS, " ", name.upper()).split())


def abbreviate(name: str) -> str:
    words = strip_form(name).split()
    return " ".join(ABBREVIATIONS.get(w, w) for w in words).title()


def typo(name: str, rng: random.Random) -> str:
    s = strip_form(name)
    letters = [i for i, c in enumerate(s) if c.isalpha()]
    if len(letters) < 6:
        return s.title()
    i = rng.choice(letters[1:-1])
    op = rng.choice(["drop", "swap", "double"])
    if op == "drop":
        s = s[:i] + s[i + 1:]
    elif op == "swap" and i + 1 < len(s):
        s = s[:i] + s[i + 1] + s[i] + s[i + 2:]
    else:
        s = s[:i] + s[i] + s[i:]
    return s.title()


def trade_name(company: dict) -> str | None:
    """Enseigne or sigle from API Recherche d'entreprises, if it differs from the legal name."""
    legal = strip_form(company.get("nom_raison_sociale") or company.get("nom_complet") or "")
    for cand in (company.get("enseignes") or []) + [company.get("sigle")]:
        if cand and strip_form(cand) != legal:
            return cand.title()
    return None


def crm_name_for(company: dict, family: str, rng: random.Random) -> str:
    if family == "TRADE_NAME":
        return trade_name(company) or abbreviate(company["nom_complet"])
    if family == "ABBREV_TYPO":
        return typo(abbreviate(company["nom_complet"]), rng) if rng.random() < 0.5 else abbreviate(company["nom_complet"])
    return (company.get("nom_raison_sociale") or company["nom_complet"]).title()
