# FORCLOS: demo, pitch, Q&A

Live app: **https://01a16329-c9cc-767c-92a5-68a3efccca2e-8080.eur-1.aiven.app**
(Aiven Runtime, data in Aiven for PostgreSQL. Health check: `/api/health`.)

## What is live and what is recorded (say it once, early)

| On screen | Source |
|---|---|
| BODACC notices, register lookups | Real, public, live (synced every 30 min) |
| Customers, invoices, delivery notes | Fictional ledger of a fictional wholesaler (Maison Verdier Distribution) |
| Agent runs during the demo | Live, on stage |
| Benchmark tab | Recorded live runs of `benchmark/run.py`, 22 Oct 2026, 12:06 to 12:10 |

## 30-second hook

> In 2025, about 68,600 French companies entered insolvency proceedings, a record. If one of them owes you
> money, you have two months from the official notice to file your claim. Miss it and you're time-barred:
> forclos. Nobody in an SME reads the BODACC. FORCLOS does: it finds which of your customers are affected,
> investigates your invoices and gets the claim ready before the deadline.

Founder line: "I'm a law graduate from Assas and an engineer. This is the problem where both matter."

## 3-minute demo, page by page

Start state (after **Reset demo**): 3 customers in proceedings, €22,209 to declare, next deadline D-11.
Each agent run takes 20 to 30 seconds: talk over it, never wait in silence.

| Time | Page and click | Say |
|---|---|---|
| 0:00 | **Overview** | The hook. Point at "€22,209 to declare" and the red **D-11**. "Synced with today's BODACC, automatically, every 30 minutes." |
| 0:20 | **Overview**, right column | "This is today's real BODACC. Our client is a fictional Lyon food-service wholesaler; the companies are real." |
| 0:30 | **Customers** → *Le Lunch Lib* → **Check identity** | "Sales typed a trade name, no SIREN. A keyword alert finds nothing." Trail: register search "Le Lunch Lib" in 69120 → SHERFAN SEPT CHEMINS, active, same address → in redressement judiciaire → **case opened by itself**, claim prepared. |
| 1:05 | **Overview** → *Villa d'Aristide* | "The invoice-date rule says €6,820. This €18,400 invoice is dated 14 Sept, after the 8 Sept judgment, so a rules system leaves it out." |
| 1:15 | **Run investigation** | Trail: the agent reads delivery note BL-2026-4471, **delivered 5 Sept**, before the judgment. Row flips *Post-opening (RULE)* → *Declare (AGENT)*: **"Added to claim: +€18,400"**. To declare: **€25,220**. |
| 1:45 | Same page, right column | Claim draft addressed to the mandataire (Selarlu Martin), échu / à échoir split, **Mark ready to sign**. Cash on delivery for new deliveries (never "block the customer"). Retention of title: reclaim goods by 18 Dec. If the agent flags it (it did in every rehearsal run): lawyer review, because the cessation of payments is dated a year before the opening, so payments received since then are at risk. |
| 2:05 | **Overview** → *Brasserie de Vaucroze* | "Redressement, then liquidation published this morning. A tool that restarts a 60-day clock says 21 Dec. The law says 2 Nov: **D-11**. Filing on the naive date is 49 days too late." Point at *Conversion: does not restart the deadline*. |
| 2:25 | **Data layer** | The Aiven story (below), in two sentences. |
| 2:40 | **Benchmark** → *Held-out set* | "Twenty cases never used during development. FORCLOS missed no claim. Rules-only would have missed €280,976 of claims, a naive alert €259,591, with 5 false alarms out of 5." Say n=20, a simulation, recorded runs; scroll to *Every case* if asked. |
| 2:55 | Slide | Who / why now / first users. |

**If behind at 2:05:** skip the Data layer page and say its one line on the Benchmark page.

**Judge moment (only if asked, or in Q&A):**
- *Add a customer*: **Customers → Add a customer**, the judge types any trade name and postal code; the
  agent resolves the company and says whether it is in proceedings.
- *Add evidence*: on Villa d'Aristide, **Add a delivery note** for invoice FA-2026-0968 with a date of the
  judge's choice; the agent re-runs and the category follows the date (before 8 Sept → declare).
- *Onboarding*: **Import receivables → Use the sample → Import and check**: "Maison Vivier", no SIREN,
  becomes VIVIER BRON, in redressement, case and claim prepared.

## Benchmark numbers

Real BODACC notices and register records; the CRM side is degraded on purpose (trade names, typos, stale
SIRENs of ceased companies, healthy homonyms, invoices dated after the judgment, RJ→LJ conversions), so
the ground truth is known. Every debtor's claim deadline is still open. Fixed seed, 30 dev / 20 held out.

**Held-out (n=20: 15 affected, 5 healthy homonyms), run once:**

| | Value of claims missed | Affected found | False alarms | Exact deadline |
|---|---|---|---|---|
| Naive BODACC alert | €259,591 | 8 / 15 | 5 / 5 | 0 / 15 |
| Rules (exact SIREN + legal engine) | €280,976 | 6 / 15 | 0 / 5 | 6 / 15 |
| **FORCLOS** | **€0** of €386,318 | **15 / 15** | **0 / 5** | **15 / 15** |

**Dev (n=30: 27 affected, 3 healthy):** claims missed: naive €424,949, rules €341,453, FORCLOS €0 of €596,017;
FORCLOS 27/27 found, 27/27 exact deadlines, 0/3 false alarms.

**Both splits:** FORCLOS missed €0 of €982,335 of claims, 42/42 found, 0/8 false alarms.
Rules-only would have missed €622,429, the naive alert €684,540.

Wording: say **"value of claims missed in the simulation"**, never "money lost". A late filing loses the
right to be paid from the procedure (unless a judge grants relief within 6 months), not necessarily the debt.

**Cost:** about 19,000 tokens and a median of 17 to 19 seconds per case. 2 held-out cases were escalated
to review, and the claim was still found and dated correctly.

**Say the limits before a judge does:**
- The CRM errors are synthetic, generated by us; real CRMs are messier.
- An earlier dev run, on a first version of the dataset, missed one trade name (L'Argentera): the agent
  escalated it to review instead of guessing. One prompt rule was added after the dev runs (invoices
  without any document); no benchmark case lacks documents.
- On an opening alone, the naive alert's 60-day clock lands one or two days early (no loss, but never the
  exact date); it is the conversions that make it late.

## Defending the perfect score

Perfect scores attract scrutiny. Answer with method and logs, not adjectives.

- **How were the 50 cases built?** `benchmark/build.py`, fixed seed. Each case starts from a real company with a
  real opening judgment in the BODACC (last 45 days, legal persons, deadline still open) and its real register
  record. We then degrade the CRM side the way sales teams do: trade name instead of legal name, abbreviation or
  typo, the SIREN of a ceased company, a healthy company sharing the debtor's name, an invoice dated after the
  judgment for a delivery made before, an RJ converted to LJ. Because we create the error, the ground truth is
  known: the right SIREN, whether the customer is affected, the legal deadline, the amount to declare.
- **Why do the baselines miss so much?** Each family breaks one assumption. No SIREN or a stale one: exact
  matching finds nothing, so the whole claim is missed. Trade names: name matching finds nothing. Healthy
  look-alikes: name matching raises a false alarm. Conversions: a 60-day clock restarted at the latest notice
  files too late. Invoice dates: the invoice after the judgment is left out of the claim. The rules baseline is
  FORCLOS without the agent: same legal engine, so the gap is the agent.
- **Were the 20 held-out cases unseen?** The split was fixed before any run; held-out was run once, after the
  dev runs, and nothing was tuned on it. Be honest about the two changes made during development: the dataset
  was rebuilt once to keep only cases whose deadline was still open (some conversions had deadlines already
  past, which no system can meet), and one prompt rule was added for invoices with no documents.
- **Can we inspect or reproduce it?** Yes. The Benchmark page lists every case and every system's result. In the
  repo: `data/bench_cases.json` (cases and ground truth), `data/benchmark_results.json` (per-case results of the
  recorded runs), and `python -m benchmark.run --split dev` reruns it (about 5 minutes, live model calls).
- **Isn't it too easy?** The errors are synthetic and one at a time; real CRMs combine them. That is why the
  pilot starts from a real receivables export, and why FORCLOS escalates instead of guessing (2 held-out cases).

## The Aiven data story

One Aiven for PostgreSQL database is the agent's memory; Aiven Runtime runs the app from the GitHub
Dockerfile, with the database injected through a service integration (no password in code).

- **Live stream:** the BODACC is pulled every 30 minutes. Upsert on notice id makes ingestion idempotent,
  and a Postgres advisory lock means only one replica syncs. A new notice matching a customer opens a case
  and starts the agent: no one clicks.
- **Freshness:** register lookups are cached for 7 days, then refetched; if the register API is down, the
  stale copy is used and labelled as stale in the agent's evidence.
- **Memory:** every notice ever linked to a case (`case_events`), so a conversion is read against the
  opening already stored and never re-alerted. Decisions are append-only (`invoice_classifications`): the UI
  shows the rule's answer and the agent's, with the evidence document. Every agent step is stored and
  streamed to the trail.
- **Grounding:** the agent never computes a date or an amount. It writes evidence; SQL and `app/legal.py`
  apply the law.
- **Scale today:** about 29,000 notices for 45 days, backfilled automatically on first boot of an empty
  database.

## The slide

Slide: https://claude.ai/artifact/GjF51Jfgopp5M2ZjixvuB9 (present full screen; export to PDF or PPTX from its menu).
It stands alone if the jury only sees the slide: headline, what the agent does on every notice, the benchmark
(value of claims missed), who / why now / first users, and the live link. The 45-second talk track is in its
speaker notes.

**Who:** French B2B SMEs selling on credit with no credit manager: food-service wholesalers, building
suppliers, B2B services. One missed claim can be a month of margin.
**Why now:** record insolvencies (about 68,600 in 2025, Banque de France). BODACC and the company register
are open APIs. Agents can now read legal notices and documents reliably enough, with code enforcing the law.
**First users:** accounting firms. They already hold their clients' receivables and see hundreds of SMEs.
Pilot offer: "Send your aged receivables export. We check 45 days of BODACC today and watch every day after."
The import page does exactly that.
**Today:** [N] people in this room told us who watches insolvency notices at their company: [answers].

## Q&A prep

- **Why an agent and not rules?** Rules do what is deterministic: SIREN match, deadlines, categories. The
  agent handles what isn't: who the CRM record really is, which document proves when a claim arose, whether
  the history is complete. The benchmark shows RULES and FORCLOS separately: same engine, the agent is the
  difference.
- **Is the benchmark rigged?** Real notices, synthetic CRM errors, ground truth fixed before the runs,
  held-out set run once. FORCLOS was also wrong once in development, and the code is public.
- **What if the agent is wrong?** It supplies evidence with document ids; code decides. Drafts only, a human
  signs. Ambiguity goes to REVIEW, and the scope is on screen. A false alarm on a healthy customer costs a
  relationship, so the agent must prove identity with name, address and active status.
- **Competition?** BODACC alerts exist, and credit-management suites exist for companies with a credit
  team. Alerts stop at "this company is insolvent". FORCLOS starts there: identity repair, evidence, a claim
  ready to sign, for the SME with nobody to do it.
- **Unsecured creditors rarely get paid.** True. The value: you keep your rights, you stop extending credit
  (cash terms), and goods under retention of title can be reclaimed within 3 months, which is real money.
- **Liability?** Drafts only, a human signs. Narrow scope shown on screen; everything else goes to a lawyer.
- **Is it production-ready?** It is deployed, syncs on its own, bootstraps an empty database, imports a
  real receivables export, rate-limits agent runs and caches every external call. Missing for a paying
  customer: accounts and per-firm data isolation, and e-filing on the creditors' portal.
- **Personal data?** Legal persons only; sole traders are excluded from register results.
- **Why Aiven / why Postgres?** The product is a memory problem: notices over time, decisions that change
  with evidence, idempotent ingestion, trigram search. One managed Postgres does all of it; Runtime puts the
  app next to it.

## Before 16:00

- [ ] 15:30: open the live URL, `/api/health` shows `"ok": true` and about 29,000 notices.
- [ ] Click **Reset demo** (sidebar). Overview shows €22,209 to declare and D-11.
- [ ] Rehearse 3 times with the timer; agent runs on stage are real, so expect 20 to 30 seconds each.
- [ ] Ask organisers: how the top 8 are selected, the deadline, what to submit.
- [ ] Ask 5 people at lunch: "At your company, who watches customers' insolvency notices?"
- [ ] Check the URL on your phone and on the venue wifi; keep a phone hotspot ready.
- [ ] Record the 2-minute backup video of the flow above.
- [ ] After the last rehearsal, **Reset demo** again.

## Backup plan

| If | Then |
|---|---|
| The agent is slow (more than 40 s) | Keep talking over the trail; it streams step by step. If it stalls, open the second case and come back. |
| The agent fails (model API down) | Switch to the local instance, which keeps recorded runs (below), and say "recorded run". |
| The venue wifi dies | Phone hotspot. The data is in Postgres; only agent runs and the BODACC sync need the internet. |
| The Aiven app is down | Aiven console → Runtime → app → **Actions → Deploy latest commit**; meanwhile use the local instance. |
| "Too many agent runs" (429) | The public URL allows 40 runs per 10 minutes; wait a minute or use the local instance. Don't let the room spam it. |
| Everything fails | Play the backup video. |

**Local instance (recorded runs, works offline except new agent runs):**

```bash
brew services start postgresql@17
```

```bash
cd ~/Downloads/forclos && FORCLOS_SCHEDULER=off .venv/bin/uvicorn app.main:app --port 8080
```

Then open http://localhost:8080. Do not click **Reset demo** there: it would erase the recorded runs.
