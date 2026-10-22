# FORCLOS: demo, pitch, Q&A

## 30-second hook (English)

> Last year, nearly 70,000 French companies went insolvent. If one of them owes you money, you have two
> months from the official notice to file your claim. Miss it and you're time-barred: forclos.
> Nobody reads the BODACC. FORCLOS does: it finds which of your customers are affected, investigates your
> invoices and gets the claim ready before the deadline.

Founder line: "I'm a law graduate from Assas and an engineer. This is the problem where both matter."

## 3-minute demo (rehearse 5 times, time it)

| Time | On screen | Say |
|---|---|---|
| 0:00 | Hook, KPI row | The hook. Point at "Exposure at risk" and the countdown. |
| 0:20 | Live feed | "This is this week's real BODACC. Our client is a fictional Lyon wholesaler with 40 customers." Label visible. |
| 0:35 | Case B (identity) | "Their CRM says 'Bistrot Canuts'. No SIREN. A keyword alert finds nothing." Agent trail: register search, address check, verified SIREN, notice matched. |
| 1:05 | Case C (documents) | "This €18,400 invoice is dated after the judgment, so a rules system leaves it out. The agent opens the delivery note: delivered three days before. It goes back in the claim." Row flips RULE → AGENT, "+€18,400". |
| 1:35 | Judge moment | Hand a judge the form: add a delivery note with a date of their choice. Agent re-runs, category follows the date. |
| 2:00 | Case D (conversion) | "Redressement, then liquidation. A naive tool restarts the clock: day 51. The law says it doesn't: 9 days left." |
| 2:20 | Actions | Claim draft to the named mandataire, amounts due / to fall due, "ready to sign". Cash terms on new deliveries. |
| 2:35 | Benchmark tab | Headline: € lost to forclusion, NAIVE vs RULES vs FORCLOS, held-out set. Say the n and one failure. |
| 2:50 | Slide | Who / why now / first users. |

If the network dies: the feed and register calls are cached in Postgres; the demo seed is frozen. If the
agent stalls: switch to the recorded run (case page keeps the last run's trail) and say "recorded run".

## The slide

**Who**: French B2B SMEs selling on credit with no credit manager: food-service wholesalers, building
suppliers, B2B services. One missed claim can be a month of margin.
**Why now**: near-record insolvency levels (≈70,000 in 2025); BODACC and the company register are open APIs;
agents can now read legal notices and documents reliably enough, with code enforcing the law.
**First users**: accounting firms. They already hold their clients' receivables and see hundreds of SMEs.
Pilot offer: "send your aged receivables export, we scan 24 months of BODACC and show what you missed."
**Today**: [N] people in this room told us who watches insolvency notices at their company: [answers].

## Q&A prep

- **Why an agent and not rules?** Rules do what is deterministic: SIREN match, deadlines, categories.
  The agent handles what isn't: who the CRM record really is, which document proves when a claim arose,
  whether the history is complete. Benchmark shows RULES vs FORCLOS separately.
- **Competition?** BODACC alerts exist, and credit-management suites exist for companies with a credit
  team. Alerts stop at "this company is insolvent". FORCLOS starts there: identity repair, evidence,
  claim ready to sign, for the SME with nobody to do it.
- **Unsecured creditors rarely get paid.** True. The value: you keep your rights, you stop extending credit
  (cash terms), and retention-of-title goods can be reclaimed within 3 months, which is real money.
- **Liability?** Drafts only, a human signs. Narrow scope shown on screen; everything else goes to a lawyer.
- **Is the data real?** Notices and company records: real, public, live. Ledger and invoices: fictional.
  Benchmark: real notices with synthetic CRM perturbations. Results are from live runs.
- **Aiven?** Postgres is the agent's memory: every notice ever linked to a case, append-only decisions so
  you can see how evidence changed them, idempotent ingestion, trigram search, offline cache.

## Before 16:00

- [ ] Ask organisers: how are the top 8 selected, deadline, what to submit.
- [ ] Ask 5 people at lunch: "At your company, who watches customers' insolvency notices?"
- [ ] Deployed URL works on phone and on the venue wifi.
- [ ] Backup video recorded.
