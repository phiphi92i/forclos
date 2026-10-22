# FORCLOS: submission form

Live app: https://01a16329-c9cc-767c-92a5-68a3efccca2e-8080.eur-1.aiven.app
Repo: https://github.com/phiphi92i/forclos

## One-line pitch

When a customer goes insolvent, a French supplier has two months to file its claim or lose it: FORCLOS's
agent watches the BODACC, finds which of your customers are really affected, investigates your invoices and
gets the claim ready before the deadline.

(Shorter, if there is a character limit: "Alerts tell you a customer is insolvent. FORCLOS's agent gets your
claim ready before the legal deadline.")

## The data layer in action

**What data the agent uses**
- **BODACC**, the official journal of French insolvency judgments: live, pulled every 30 minutes, about 29,000
  notices over 45 days. Upserts on the notice id make ingestion idempotent.
- **The French company register** (API Recherche d'entreprises): legal names, trade names, addresses, active
  or ceased. Cached 7 days, refetched when stale; if the API is down the stale copy is used and labelled.
- **The supplier's own ledger**: customers, invoices, delivery notes, imported from an aged-receivables CSV
  (a fictional wholesaler in the demo).

**Where it lives:** one Aiven for PostgreSQL database, next to the app on Aiven Runtime (connected through a
service integration, so no password in code). On first boot against an empty database the app loads itself.

**How it flows:** a new BODACC notice arrives → an exact-SIREN rule matches it to a customer → a case opens and
the agent starts by itself → its tools read the register, the full BODACC history of the company and the
customer's documents → it records evidence (verified SIREN, notice ids, document ids) → code applies the law
(two-month deadline, art. 641/642 CPC; pre/post-opening category; amounts) → actions wait for sign-off: claim
draft to the mandataire, cash terms for new deliveries, revendication alert, lawyer review.

**Memory:** every notice ever linked to a case is kept, so a conversion is read against the stored opening and
never restarts the deadline. Decisions are append-only with their evidence, so the rule's answer and the
agent's are both visible. Every agent step is stored and shown. An identity the agent repairs once is matched
by the exact rule ever after, with no agent call.

## Evidence it works

Upload: `docs/evidence-benchmark.png` (the Benchmark page of the live app).

Benchmark of 50 cases built from real BODACC notices and register records with synthetic CRM errors (trade
names, typos, stale SIRENs, healthy look-alikes, invoices dated after the judgment, conversions). 20 cases
held out and run once. Recorded live runs; per-case results in the app and in `data/benchmark_results.json`.

| | Value of claims missed | Affected customers found | False alarms | Exact deadline |
|---|---|---|---|---|
| Naive BODACC alert | €684,540 | 22 / 42 | 8 / 8 | 0 / 42 |
| Rules only (same legal engine, no agent) | €622,429 | 20 / 42 | 0 / 8 | 20 / 42 |
| **FORCLOS** | **€0** of €982,335 | **42 / 42** | **0 / 8** | **42 / 42** |

Cost: about 19,000 tokens and a median of 17 to 19 seconds per case.

## 3-minute demo (MP4)

Follow the flow in `DEMO.md` ("3-minute demo, page by page"). On a Mac: click **Reset demo** on the live app,
then press Cmd + Shift + 5, choose **Record Selected Portion** around the browser, Options → Microphone on, and
record while you talk. Stop with the button in the menu bar; the .mov converts to .mp4 with QuickTime → File →
Export As → 1080p, or upload the .mov if the form accepts it.

## One pitch slide (must be a public link)

The slide is built at https://claude.ai/artifact/GjF51Jfgopp5M2ZjixvuB9, which is private. To get a public link:
1. Open it → Share / Export → **PowerPoint (.pptx)**.
2. drive.google.com → New → File upload → the .pptx → right-click → Open with → **Google Slides**.
3. In Google Slides: Share → General access → **Anyone with the link → Viewer** → Copy link.
4. Open that link in a private window to check it opens without signing in, then paste it into the form.
