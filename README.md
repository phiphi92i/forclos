# FORCLOS

When a customer of a French B2B supplier enters insolvency proceedings, the supplier has two months from the
BODACC publication of the opening judgment to file its claim (déclaration de créance), or it is time-barred
(forclos). FORCLOS reads the BODACC daily, repairs messy customer data to find who is really affected,
investigates invoices and delivery notes, computes the legal deadlines and prepares the claim for sign-off.

Rules (code, `app/legal.py`) decide deadlines, categories and amounts. The agent (`app/agent.py`) supplies
evidence: which legal entity a CRM record is, which document dates a claim, whether the history is complete.

Run locally: `cp .env.example .env`, fill it, `pip install -r requirements.txt`,
`uvicorn app.main:app --reload`. Build brief: `CLAUDE.md`.

Public BODACC data · fictional ledger · live agent run.
