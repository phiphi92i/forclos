import re
import unicodedata

LEGAL_FORM_TOKENS = {"SAS", "SASU", "SARL", "EURL", "SA", "SCI", "SNC", "SCOP", "SELARL", "SELAS", "SCEA",
                     "EARL", "GAEC", "SCA", "STE", "SOCIETE", "ETS", "ETABLISSEMENTS"}


def norm_name(s: str | None) -> str:
    """Uppercase, no accents, no punctuation, no legal-form tokens."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t not in LEGAL_FORM_TOKENS)
