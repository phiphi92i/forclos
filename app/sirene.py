"""API Recherche d'entreprises (DINUM / annuaire-entreprises). Free, no key, ~7 req/s.
Docs: https://recherche-entreprises.api.gouv.fr/docs/
Verify field names against one live response at build step 1."""
from __future__ import annotations

import time

import httpx

BASE = "https://recherche-entreprises.api.gouv.fr"
_last_call = 0.0


def _get(path: str, params: dict) -> dict:
    global _last_call
    wait = 0.16 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        _last_call = time.monotonic()
        r = httpx.get(f"{BASE}{path}", params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return {}


def _normalise(c: dict) -> dict:
    siege = c.get("siege") or {}
    return {
        "siren": c.get("siren"),
        "nom_complet": c.get("nom_complet"),
        "nom_raison_sociale": c.get("nom_raison_sociale"),
        "sigle": c.get("sigle"),
        "enseignes": siege.get("liste_enseignes") or [],
        "nature_juridique": c.get("nature_juridique"),   # "1000" = entrepreneur individuel: exclude from demo
        "etat_administratif": c.get("etat_administratif"),  # "A" active, "C" ceased
        "siege": {
            "siret": siege.get("siret"),
            "adresse": siege.get("adresse"),
            "code_postal": siege.get("code_postal"),
            "commune": siege.get("libelle_commune"),
        },
        "matching_etablissements": [
            {
                "siret": e.get("siret"),
                "adresse": e.get("adresse"),
                "code_postal": e.get("code_postal"),
                "commune": e.get("libelle_commune"),
                "etat_administratif": e.get("etat_administratif"),
                "enseignes": e.get("liste_enseignes") or [],
            }
            for e in (c.get("matching_etablissements") or [])[:5]
        ],
    }


def search_company(query: str, postal_code: str | None = None, per_page: int = 5) -> list[dict]:
    params = {"q": query, "per_page": per_page}
    if postal_code:
        params["code_postal"] = postal_code
    return [_normalise(c) for c in _get("/search", params).get("results", [])]


def get_company(siren: str) -> dict | None:
    res = _get("/search", {"q": siren, "per_page": 1}).get("results", [])
    res = [c for c in res if c.get("siren") == siren]
    return _normalise(res[0]) if res else None
