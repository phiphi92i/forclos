# FORCLOS: build brief for Claude Code

Hackathon: AI Innovate Paris, "Future Founders: Data-Centric Agents" (brief: `docs/brief.pdf` if present).
Today: hacking until the cut, **top 8 pitch at 16:00**. Solo founder. Ship a working, deployed, honest demo.
Deployment on **Aiven Runtime** and data on **Aiven for PostgreSQL** are required (separate Aiven prize).

## 1. Product in one paragraph

When a customer of a French B2B supplier enters a collective procedure, the supplier has **two months from
the BODACC publication of the opening judgment** to file its claim (déclaration de créance) with the
mandataire judiciaire / liquidateur, or it is time-barred (forclos). SMEs without a credit manager don't read
the BODACC. FORCLOS ingests the BODACC daily, repairs the supplier's messy customer data to find who is
really affected, investigates invoices and delivery notes to decide what must be claimed, computes the legal
deadlines, and prepares the claim and protective actions for human sign-off.

Pitch line: *"Alerts tell you a customer is insolvent. FORCLOS does the investigation and gets your claim
ready before the deadline."*

## 2. Why it needs an agent (must be VISIBLE in the UI)

| Layer | Who decides | Examples |
|---|---|---|
| Rules (code) | `app/legal.py`, SQL | exact SIREN match, deadlines (art. 641/642 CPC), pre/post-opening category from a date, amounts |
| Agent | `app/agent.py` | which legal entity "Le Petit Zinc, 69004" is; which delivery note dates an invoice; whether the BODACC history is complete; when to escalate |

The agent never computes a date, category or amount. It supplies evidence; code applies the law.
Show a small "RULE" vs "AGENT" badge on every decision in the UI.

## 3. The three data conflicts the demo is built on

1. **Identity**: CRM says "Bistrot Canuts" (trade name, no SIREN) or carries a stale SIREN of a ceased
   company. Naive matching finds nothing. Agent: `search_company` with name + postal code, cross-checks
   delivery addresses from documents and active status, records the verified SIREN with evidence. Then
   the exact SIREN rule matches the BODACC notice.
2. **Documents**: invoice dated 5 days AFTER the opening judgment, but its delivery note shows delivery
   3 days BEFORE, under a framework supply contract. Baselines classify by invoice date and drop it from
   the claim. Agent reads the delivery note, records `fait_generateur_date` = delivery date with
   `basis=DELIVERY` and the document id; code returns DECLARE; claim amount goes up on screen
   ("added to claim: +€18,400").
3. **Time**: RJ opening published, later a conversion to LJ. Naive restarts a 60-day clock from the
   conversion and misses the real deadline. Engine anchors on the opening publication. If the history
   starts with a conversion, the agent fetches older history; never computes from a conversion.

Plus one negative: **healthy homonym**. Same name as a debtor, different city and SIREN. Naive raises a
false alarm (stopping supply to a healthy customer is costly). Agent rejects with evidence.

## 4. Legal rules (already implemented and tested in `app/legal.py`: do not reimplement)

- Claim deadline: 2 months from BODACC publication of the opening judgment (R622-24 C. com.), 4 months if
  creditor outside metropolitan France. Month math = same day-of-month else last day (art. 641 CPC),
  weekend/holiday → next working day (art. 642 CPC). **Not 60 days.**
- Conversion never restarts it. Revendication (retention of title): 3 months from publication (L624-9).
  Relief from forclusion: 6 months (L622-26).
- Pre/post-opening split by **fait générateur**: delivery date under a framework supply contract with
  successive deliveries; order acceptance for a one-off sale; contract date for a loan. Opening judgment
  takes effect from 0h on its date (same-day = post-opening). Never say "the delivery always dates the claim".
- Post-opening claims are not in the claim draft (L622-17 regime, flagged for review).
- Claim content (L622-25): amount due at judgment date + amounts to fall due with due dates; nature
  (chirographaire); certified sincere by the creditor. LJ opening makes all claims due (L643-1).
- Contracts in progress: supplier must keep performing despite pre-opening debts (L622-13); new deliveries
  are paid **in cash**. Action = `PAYMENT_TERMS_CASH`. Never "block the customer".
- Out of scope → `LAWYER_REVIEW`: published security / published contract (deadline runs from personal
  notice), accelerated safeguard, plan resolution, extension, creditor outside metropole.
- Show on screen: "Scope: unsecured trade creditor, metropolitan France. Other cases sent to a lawyer."

## 5. Architecture (keep it this small)

- Python 3.12, FastAPI, psycopg 3, httpx, anthropic SDK. One container. No frontend build step.
- `static/index.html`: single page, vanilla JS + Tailwind CDN, polls the API.
- Aiven for PostgreSQL: everything. `pg_trgm` for candidate name search. Upserts make ingestion idempotent.
- Agent model: `FORCLOS_MODEL` env, default `claude-sonnet-5-5`.
- Do NOT add OpenSearch, Kafka, Redis, auth, React, or a second agent. A Postgres `LISTEN/NOTIFY` → SSE
  stream for agent steps is a bonus only if everything else works (polling is fine).

```
app/legal.py        DONE + tests. Deadlines, judgment classification, claim category, due split.
app/bodacc.py       DONE (shape unverified). Client + parser. Step 1 verifies it on real data.
app/sirene.py       DONE (shape unverified). API Recherche d'entreprises client.
app/baseline.py     DONE. NAIVE and RULES comparison systems.
app/agent.py        DONE. Tool schemas, system prompt, tool-use loop.
app/normalize.py    DONE. Name normalisation.
benchmark/perturb.py DONE. CRM degradation primitives.
db/schema.sql       DONE. Idempotent.
app/db.py           TODO  psycopg pool from DATABASE_URL, run schema.sql on startup.
app/ingest.py       TODO  BODACC → bodacc_notices upsert; then rule matching → cases + case_events.
app/tools.py        TODO  handlers for every tool in app/agent.py TOOLS (see §7).
app/runs.py         TODO  start agent run in a background thread, persist agent_runs/agent_steps.
app/main.py         TODO  FastAPI app, /api/health, serves static/, includes the two routers below.
app/routes_data.py  TODO  ingest, feed, dashboard, demo reset, benchmark routes (session DATA owns it).
app/routes_cases.py TODO  cases, customers, documents, runs, actions routes (session AGENT owns it).
scripts/sample_bodacc.py   DONE  writes tests/fixtures/bodacc_real.json.
scripts/seed_demo.py       TODO  demo ledger from real notices (§8).
benchmark/build.py, run.py TODO  (§9).
static/index.html   TODO  (§10).
Dockerfile          DONE  check Aiven Runtime port/env conventions in their docs.
```

## 6. API contract (freeze this first; UI and backend build against it in parallel)

```
GET  /api/health
POST /api/ingest                 {"days": 45}  -> {"fetched","inserted","updated","new_cases"}
GET  /api/feed?limit=30          latest notices (left panel), each: id, denomination, ville, date_parution, event_kind, procedure, matched_customer_id|null
GET  /api/dashboard              {"exposure_cents","declare_cents","customers_at_risk","nearest_deadline","nearest_days_left",
                                  "cases":[{id, customer:{id,crm_name}, denomination, siren, status, procedure,
                                  claim_deadline, days_left, declare_cents, exposure_cents}]}
GET  /api/cases/{id}             case + customer + timeline (notices, oldest first) + invoices with current
                                 classification (category, basis, fait_generateur, evidence_document_id, decided_by, rationale)
                                 + previous classifications (to show "changed") + actions + latest run summary
POST /api/cases/{id}/investigate {"trigger": "..."} -> {"run_id"}
POST /api/customers              {"crm_name","postal_code","crm_siren"?} -> {"customer_id","run_id"}   (judge adds a customer live: runs RESOLVE_IDENTITY, then case detection)
POST /api/documents              {"customer_id","invoice_id","kind","doc_date","body"} -> {"document_id","run_id"}   (judge adds evidence: re-investigates the case)
GET  /api/runs/{run_id}/steps?after={step_id}   -> {"status","summary","steps":[{id,kind,tool,payload,created_at}]}
POST /api/actions/{id}/apply     PAYMENT_TERMS_CASH sets customers.payment_terms='CASH'; CLAIM_DRAFT status APPLIED = "ready to sign"
GET  /api/actions/{id}/claim.txt claim draft as printable text (French), watermark "DRAFT, NOT SENT"
POST /api/demo/reset             restore the frozen demo seed (data/demo_seed.json)
GET  /api/benchmark              latest benchmark_runs per system and split
```

## 7. Tool handlers (`app/tools.py`)

All return JSON-serialisable dicts, small (truncate long text to ~1,500 chars). Cache every external call in
`company_cache` / `bodacc_notices` so the demo survives a network failure.

- `get_customer_file(customer_id)`: customer row, contracts (kind, retention_of_title, published_security),
  invoices (id, number, invoice_date, due_date, amount, outstanding), documents index (id, kind, doc_date, invoice_id).
- `read_document(document_id)`: body.
- `search_company(query, postal_code)`: `app.sirene.search_company`, cached. Drop `nature_juridique == "1000"`
  (sole traders) from results shown in the demo.
- `get_company(siren)`.
- `get_bodacc_history(siren)`: local notices for the SIREN; if none or oldest is a conversion, call
  `app.bodacc.fetch_history`, upsert, return. Fields: id, date_parution, jugement_date, nature, event_kind,
  procedure, officers, complement (truncated), url.
- `record_identity(customer_id, status, siren, evidence)`: writes verified_siren / identity_status /
  identity_evidence. If VERIFIED and that SIREN has OPENING-family notices → create case (upsert on
  customer_id, siren) + case_events.
- `compute_deadlines(case_id)`: build `legal.Notice` list from the case SIREN's notices,
  `legal.compute_deadlines`, write to cases, return with `days_left` (today in Europe/Paris).
- `record_claim_classification(...)`: outstanding from invoice; `legal.classify_claim` with the case's
  opening judgment date; insert into invoice_classifications (decided_by AGENT, run_id); recompute
  `cases.declare_cents` / `exposure_cents`; return category, reason, previous category if changed.
- `propose_actions(...)`: upsert actions. CLAIM_DRAFT payload: creditor (fictional wholesaler), debtor
  (denomination, SIREN, tribunal), procedure + opening judgment date + publication date, officer, lines of
  DECLARE invoices with evidence doc ids, `legal.split_due`, total, deadline. PAYMENT_TERMS_CASH.
  REVENDICATION_ALERT if any contract has retention_of_title (deadline = revendication_deadline).
- `flag_lawyer_review(reason, case_id?, customer_id?)`: upsert LAWYER_REVIEW action, case status NEEDS_REVIEW.
- `finish(status, summary)`: close agent_runs, set case status.

Rule-layer classification: when a case is created, insert a RULE classification per unpaid invoice using
`basis=INVOICE_DATE` (what a rules system would do). The agent's later AGENT rows supersede it. The UI shows
the change: this IS the demo's key moment.

## 8. Demo data (`scripts/seed_demo.py`): freeze it by noon

Creditor: **"Maison Verdier Distribution"** (fictional food-service wholesaler, Lyon). Label everywhere:
**"Public BODACC data · fictional ledger · live agent run"**.

Pick REAL legal-person debtors (`is_legal_person`, `nature_juridique != 1000`) from ingested notices:
- **A clean**: opening published 10–40 days ago; CRM has the right SIREN. 3 unpaid pre-opening invoices.
  Proves the baseline is not a strawman.
- **B identity**: opening 10–40 days ago, company has an enseigne or sigle different from its legal name.
  CRM name = trade name, no SIREN, postal code of the establishment. Delivery notes carry the address.
- **C documents**: framework supply contract with successive deliveries + retention of title.
  Invoice #1 delivered and invoiced pre-opening; invoice #2 dated opening+5d for delivery opening−3d
  (delivery note says so; ~€18,400); invoice #3 delivered after opening (true POST_OPENING).
- **D conversion**: real company with RJ opening published 30–55 days ago AND a later conversion notice.
  Find it: query conversion notices of the last 20 days, `fetch_history` each SIREN, keep one whose
  opening is in history. Pre-opening invoices only.
- **E healthy homonym**: for a debtor name, `search_company(name)`, pick an ACTIVE company with a different
  SIREN, no collective notice, in another département. CRM name = shared name.
- 8–10 healthy fictional customers with paid and unpaid invoices for realism.
Write the result to `data/demo_seed.json` and load from it in `/api/demo/reset`. Never re-seed during the pitch.
Live judge moments use this frozen data plus the two POST endpoints.

## 9. Benchmark (criterion 4: "Evidence it works")

`benchmark/build.py`: ~50 cases from real notices + real register data using `benchmark/perturb.py`
families (EXACT_SIREN, TRADE_NAME, ABBREV_TYPO, STALE_SIREN, HOMONYM_HEALTHY, LATE_INVOICE, CONVERSION).
Fixed seed, 30 dev / 20 held out. Store cases as `dataset='bench'` customers + `data/bench_cases.json`
with ground truth: `truth_siren|null`, `truth_affected`, `truth_claim_deadline`, `truth_declare_cents`.

`benchmark/run.py`: run NAIVE, RULES, FORCLOS on a split (FORCLOS with 4–6 concurrent agent runs).
Metrics per system:
- affected customers found (recall) and false alarms (healthy flagged)
- correct claim deadline (exact date)
- **€ lost to forclusion** = for each affected case, `truth_declare_cents` minus what the system would have
  claimed on time (missed detection or a deadline later than the truth → the whole amount; invoices wrongly
  left out → their amount). Headline metric.
- cases correctly escalated to REVIEW; agent cost (tokens) and median time per case
Run the held-out split ONCE at the end and show real numbers, failures included. Never tune on held-out.

## 10. UI (`static/index.html`): one screen + a benchmark tab

Projector-legible: dark background, numbers ≥ 48px, max 3 colours (red = deadline risk, amber = review,
green = ready). English UI, French legal terms kept in parentheses (déclaration de créance, mandataire judiciaire).

- Header: "FORCLOS" · label "Public BODACC data · fictional ledger · live agent run" · scope line.
- KPI row: **Exposure at risk €** · **To declare €** · **Customers at risk** · **Next deadline: D-18** (countdown, red under 15 days).
- Left (25%): live BODACC feed (latest collective notices, matched ones highlighted).
- Center (50%): selected case. Big countdown + deadline date + "anchored on opening published …".
  Timeline of notices (opening → conversion, with "does not restart the deadline" note).
  Invoices table: number, invoice date, fait générateur, basis, category chip, RULE/AGENT badge, evidence link.
  When a category changes, highlight the row and show "added to claim: +€18,400".
  Agent evidence trail streaming below (tool calls rendered as readable lines, not JSON).
- Right (25%): actions. Claim draft preview (officer, amounts échu / à échoir, deadline) + "Mark ready to sign";
  "Switch to cash on delivery"; revendication alert; lawyer-review items.
- Wording: "Insolvency proceedings" (not "bankruptcy"). Never "block the customer".
- Benchmark tab: 3 columns NAIVE / RULES / FORCLOS, headline "€ lost to forclusion", then recall,
  false alarms, deadline accuracy, review rate, cost. Footnote: "Real BODACC notices, synthetic CRM perturbations, n=…".

## 11. Build order (solo + parallel sessions). Stop adding features at the freeze.

0. (10 min) `pytest -q`. Run `python scripts/sample_bodacc.py`; fix `app/bodacc.py` until
   `tests/test_bodacc.py::test_real_sample` passes. Check one live `app/sirene.py` response.
1. (20 min) `app/db.py`, `app/main.py` with `/api/health` + static page, Dockerfile, deploy to Aiven Runtime
   with `DATABASE_URL`. **Deployed URL working before anything else.**
2. Parallel:
   - Session DATA: `app/ingest.py`, `app/routes_data.py`, `scripts/seed_demo.py`.
   - Session AGENT: `app/tools.py`, `app/runs.py`, `app/routes_cases.py`.
     Build trap C (documents) first: it is the demo's key moment.
   - Session UI: `static/index.html` only, against the §6 contract with mocked JSON, then the live API.
   Sessions own disjoint files. Commit small and often. Only step 1 touches `app/main.py`.
3. Benchmark build + run (dev split), fix, then held-out once.
4. Freeze 45 min before the selection deadline. Record a 2-minute backup video of the full flow.

## 12. Constraints

- Secrets only from env (`DATABASE_URL`, `ANTHROPIC_API_KEY`). Never commit `.env`.
- Real companies appear only through public BODACC/register data; invoices and documents are fictional and
  labelled. Legal persons only, no sole traders (personal data).
- Every number on screen must come from the DB or a live run. No hardcoded results.
- If something is unknown, the product says REVIEW. A wrong confident answer is worse than an escalation.
