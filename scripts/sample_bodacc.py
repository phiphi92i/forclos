"""Build step 0: pull a real BODACC sample and check the parser against it.
Run from the repo root: python scripts/sample_bodacc.py"""
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bodacc, sirene  # noqa: E402

out = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "bodacc_real.json"
recs = bodacc.fetch_collective_page(date.today() - timedelta(days=14), limit=60)
out.write_text(json.dumps(recs, ensure_ascii=False, indent=1))
print(f"saved {len(recs)} records -> {out}")
if not recs:
    sys.exit("No records: check the where clause / familleavis value in app/bodacc.py")

print("\nRAW keys of first record:", sorted(recs[0].keys()))
for k in ("jugement", "listepersonnes", "registre"):
    v = recs[0].get(k)
    print(f"  {k}: type={type(v).__name__} sample={str(v)[:300]!r}")

parsed = [bodacc.parse_notice(r) for r in recs]
print("\nevent kinds:", Counter(p["event_kind"] for p in parsed))
print("procedures:", Counter(p["procedure"] for p in parsed))
print("missing siren:", sum(not p["siren"] for p in parsed), "/", len(parsed))
print("missing jugement_date:", sum(not p["jugement_date"] for p in parsed))
print("legal person:", Counter(p["is_legal_person"] for p in parsed))
print("natures seen:")
for n, c in Counter(p["jugement_nature"] for p in parsed).most_common(15):
    print(f"  {c:3d}  {n}")

first = next((p for p in parsed if p["siren"]), None)
if first:
    print("\nregister check for", first["siren"], first["denomination"])
    print(json.dumps(sirene.get_company(first["siren"]), ensure_ascii=False, indent=1)[:1200])
