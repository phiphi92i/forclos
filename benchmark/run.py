"""Run NAIVE, RULES and FORCLOS on one split of data/bench_cases.json and store metrics in benchmark_runs.
  python -m benchmark.run --split dev
  python -m benchmark.run --split holdout     # once, at the end. Never tune on it.
Headline metric: € lost to forclusion (truth_declare_cents minus what the system would have claimed on time)."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from app import legal, runs
from app.baseline import invoice_date_classify, naive_deadline, rules_deadline
from app.cases import CASE_KINDS, match_customers, to_legal_notice
from app.db import Jsonb, query, transaction
from app.demo import insert_customer
from app.ingest import store_history
from app.normalize import norm_name

CASES = Path(__file__).resolve().parents[1] / "data" / "bench_cases.json"
CONCURRENCY = 5


def load(split: str) -> list[dict]:
    return [c for c in json.loads(CASES.read_text())["cases"] if c["split"] == split]


def ensure_histories(cases: list[dict]) -> None:
    with transaction() as conn:
        for siren in {c["debtor_siren"] for c in cases if c["debtor_siren"]}:
            store_history(conn, siren)


def notices_by() -> tuple[dict, dict]:
    rows = query("select id, siren, denomination, date_parution, jugement_date, event_kind, procedure, "
                 "jugement_nature from bodacc_notices where event_kind = any(%s)", (list(CASE_KINDS),))
    by_siren, by_name = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["siren"]:
            by_siren[r["siren"]].append(r)
        by_name[norm_name(r["denomination"])].append(r)
    return by_siren, by_name


def truth_invoices(case: dict, by_siren: dict) -> dict[str, bool]:
    """invoice number -> truly DECLARE (delivered before the opening judgment)."""
    if not case["truth_affected"]:
        return {}
    opening = legal.compute_deadlines([to_legal_notice(n) for n in by_siren[case["truth_siren"]]]).opening_judgment_date
    delivered = {d["invoice"]: date.fromisoformat(d["doc_date"]) for d in case["documents"]}
    return {i["number"]: delivered[i["key"]] < opening for i in case["invoices"]}


def score(case: dict, flagged_sirens: set[str], deadline: date | None, declared: set[str], truth_inv: dict,
          reviewed: bool = False) -> dict:
    found = case["truth_affected"] and case["truth_siren"] in flagged_sirens
    truth_deadline = date.fromisoformat(case["truth_claim_deadline"]) if case["truth_claim_deadline"] else None
    deadline_ok = found and deadline is not None and deadline == truth_deadline
    on_time = found and deadline is not None and truth_deadline is not None and deadline <= truth_deadline
    amounts = {i["number"]: i["amount_cents"] for i in case["invoices"]}
    claimed = sum(amounts[n] for n in declared if truth_inv.get(n)) if on_time else 0
    return {"bench_case_id": case["bench_case_id"], "family": case["family"], "crm_name": case["crm_name"],
            "affected": case["truth_affected"], "flagged": bool(flagged_sirens), "found": found,
            "false_alarm": (not case["truth_affected"]) and bool(flagged_sirens),
            "deadline": deadline, "truth_deadline": truth_deadline, "deadline_ok": deadline_ok,
            "truth_declare_cents": case["truth_declare_cents"], "claimed_cents": claimed,
            "lost_cents": case["truth_declare_cents"] - claimed, "reviewed": reviewed,
            "wrongly_declared": sorted(n for n in declared if not truth_inv.get(n))}


def run_baseline(system: str, cases: list[dict]) -> list[dict]:
    by_siren, by_name = notices_by()
    out = []
    for c in cases:
        if system == "NAIVE":
            matched = by_siren.get(c["crm_siren"], []) if c["crm_siren"] else by_name.get(norm_name(c["crm_name"]), [])
        else:
            matched = by_siren.get(c["crm_siren"], []) if c["crm_siren"] else []
        sirens = {n["siren"] for n in matched if n["siren"]}
        deadline, declared = None, set()
        if sirens:
            hist = [to_legal_notice(n) for s in sirens for n in by_siren[s]]
            if system == "NAIVE":
                deadline = naive_deadline(hist)
                opening = max(hist, key=lambda n: n.date_parution).jugement_date
            else:
                deadline = rules_deadline(hist)
                opening = legal.compute_deadlines(hist).opening_judgment_date
            declared = {i["number"] for i in c["invoices"]
                        if invoice_date_classify(date.fromisoformat(i["invoice_date"]), opening,
                                                 i["amount_cents"]) == legal.Category.DECLARE}
        out.append(score(c, sirens, deadline, declared, truth_invoices(c, by_siren)))
    return out


def run_forclos(cases: list[dict]) -> list[dict]:
    ids = [c["bench_case_id"] for c in cases]
    with transaction() as conn:
        conn.execute("delete from customers where dataset = 'bench' and bench_case_id = any(%s)", (ids,))
        cust = {c["bench_case_id"]: insert_customer(conn, c, dataset="bench", bench_case_id=c["bench_case_id"])
                for c in cases}
        match_customers(conn, dataset="bench")

    def one(c: dict) -> tuple[str, float, int]:
        cid = cust[c["bench_case_id"]]
        t0 = time.monotonic()
        case = query("select id from cases where customer_id = %s", (cid,))
        if case:
            r = runs.investigate_case(case[0]["id"], cid, "BODACC notice matched by SIREN.", wait=True)
        else:
            r = runs.resolve_identity(cid, wait=True)
        u = r.get("usage") or {}
        return c["bench_case_id"], time.monotonic() - t0, u.get("input_tokens", 0) + u.get("output_tokens", 0)

    with ThreadPoolExecutor(CONCURRENCY) as ex:
        perf = {k: (s, t) for k, s, t in ex.map(one, cases)}

    by_siren, _ = notices_by()
    out = []
    for c in cases:
        cid = cust[c["bench_case_id"]]
        cu = query("select identity_status from customers where id = %s", (cid,))[0]
        kases = query("select id, siren, claim_deadline, status from cases where customer_id = %s", (cid,))
        declared = {r["number"] for r in query(
            """select i.number from current_classifications cc join invoices i on i.id = cc.invoice_id
               join cases k on k.id = cc.case_id where k.customer_id = %s and cc.category = 'DECLARE'""", (cid,))}
        review_cat = query("""select 1 from current_classifications cc join cases k on k.id = cc.case_id
                              where k.customer_id = %s and cc.category = 'REVIEW' limit 1""", (cid,))
        target = next((k for k in kases if k["siren"] == c["truth_siren"]), kases[0] if kases else None)
        reviewed = cu["identity_status"] in ("REVIEW", "NOT_FOUND") or bool(review_cat) or any(
            k["status"] == "NEEDS_REVIEW" for k in kases)
        s = score(c, {k["siren"] for k in kases}, target["claim_deadline"] if target else None, declared,
                  truth_invoices(c, by_siren), reviewed)
        s["seconds"], s["tokens"] = perf[c["bench_case_id"]]
        out.append(s)
    return out


def metrics(results: list[dict]) -> dict:
    aff = [r for r in results if r["affected"]]
    m = {"n": len(results), "affected": len(aff), "found": sum(r["found"] for r in aff),
         "recall": round(sum(r["found"] for r in aff) / len(aff), 3) if aff else None,
         "false_alarms": sum(r["false_alarm"] for r in results),
         "healthy": len(results) - len(aff),
         "deadline_ok": sum(r["deadline_ok"] for r in aff), "found_with_deadline": sum(r["found"] for r in aff),
         "deadline_accuracy": round(sum(r["deadline_ok"] for r in aff) / len(aff), 3) if aff else None,
         "eur_lost_cents": sum(r["lost_cents"] for r in aff),
         "truth_declare_cents": sum(r["truth_declare_cents"] for r in aff),
         "reviewed": sum(r["reviewed"] for r in results),
         "review_rate": round(sum(r["reviewed"] for r in results) / len(results), 3) if results else None}
    if any("seconds" in r for r in results):
        m["median_seconds"] = statistics.median(r["seconds"] for r in results)
        m["tokens_per_case"] = statistics.mean(r["tokens"] for r in results)
    else:
        m["median_seconds"], m["tokens_per_case"] = 0.0, 0
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout"], default="dev")
    ap.add_argument("--systems", default="NAIVE,RULES,FORCLOS")
    args = ap.parse_args()
    cases = load(args.split)
    ensure_histories(cases)
    for system in args.systems.split(","):
        results = run_forclos(cases) if system == "FORCLOS" else run_baseline(system, cases)
        m = metrics(results)
        with transaction() as conn:
            conn.execute("insert into benchmark_runs (split, system, metrics, details) values (%s, %s, %s, %s)",
                         (args.split, system, Jsonb(m), Jsonb(results, dumps=lambda o: json.dumps(o, default=str))))
        print(f"\n{system} [{args.split}] {json.dumps(m, default=str)}")
        for r in results:
            if r["lost_cents"] or r["false_alarm"] or (r["affected"] and not r["deadline_ok"]) or r["wrongly_declared"]:
                print(f"  FAIL {r['bench_case_id']} {r['family']:15s} {r['crm_name'][:30]:30s} lost=€{r['lost_cents'] / 100:,.0f}"
                      f" found={r['found']} fa={r['false_alarm']} deadline={r['deadline']} truth={r['truth_deadline']}"
                      f" over={r['wrongly_declared']} review={r['reviewed']}")


if __name__ == "__main__":
    main()
