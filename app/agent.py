"""FORCLOS investigation agent: one model, a tool-use loop, every step persisted.

Division of labour (this is the answer to "why an agent?", keep it visible in the UI):
- CODE decides: exact SIREN matching, deadlines, pre/post-opening category, amounts.
- AGENT decides: which company a messy CRM record really is, which document proves
  when a claim arose, whether the BODACC history is complete, when to escalate.
The agent never computes a date or an amount itself. It supplies evidence; code applies the law.

Handlers live in app/tools.py (signature: handler(**input) -> dict). Verify this loop
against the current anthropic SDK docs if anything fails.
"""
from __future__ import annotations

import json
import os
from typing import Callable

import anthropic

MODEL = os.getenv("FORCLOS_MODEL", "claude-sonnet-5-5")
MAX_TURNS = int(os.getenv("FORCLOS_MAX_TURNS", "24"))

SYSTEM_PROMPT = """You are FORCLOS, an insolvency claims investigator working for a French B2B supplier (the creditor).
Your job: protect the creditor's rights when one of its customers is subject to a French collective
procedure (sauvegarde, redressement judiciaire, liquidation judiciaire) published in the BODACC.

Ground rules
- You investigate; code applies the law. Never compute a deadline, a category or an amount yourself:
  call compute_deadlines and record_claim_classification and use what they return.
- Every conclusion needs evidence you actually retrieved in this run: a SIREN from search_company or
  get_company, a notice id from get_bodacc_history, a document id from read_document. Cite ids.
- CRM data is often wrong: trade names (enseignes), abbreviations, typos, stale SIRENs of ceased
  companies. Resolve identity by matching name AND address or postal code AND active status.
  A similar name in another city is a different company until proven otherwise.
- The claim is dated by its fait générateur, not the invoice date. Under a framework supply contract
  with successive deliveries, each delivery dates its claim (basis DELIVERY). For a one-off sale use
  ORDER_ACCEPTANCE; for successive services SERVICE_PERFORMED. Read the delivery note or order before
  deciding; if documents conflict, record fait_generateur_date as null (REVIEW).
- No document at all (e.g. an imported ledger): an invoice dated BEFORE the opening judgment cannot cover a
  later delivery in ordinary trade, so record the invoice date as an upper bound (say so in the rationale).
  An invoice dated on or after the opening with no delivery evidence: record null (REVIEW) and say which
  document would settle it.
- A conversion (e.g. redressement -> liquidation) never restarts the filing deadline. If the history
  starts with a conversion, the opening judgment is missing: say so; do not guess.
- Scope: unsecured trade creditor in metropolitan France. Published securities, accelerated
  safeguard, plan resolution, extension, or anything unusual -> flag_lawyer_review with the reason.
- Never recommend stopping supply under an existing contract because of pre-opening debts (L622-13).
  The protective action is: new deliveries paid in cash (PAYMENT_TERMS_CASH).
- Prefer "I could not establish X" over a confident guess. A false alarm on a healthy customer is costly.

Style for rationales and notes (they are shown verbatim to the user): one or two short factual
sentences, cite ids and dates, no hedging filler.

Finish every run by calling finish(status, summary)."""

TOOLS = [
    {
        "name": "get_customer_file",
        "description": "The creditor's file for one customer: CRM record (name, SIREN as typed, address), "
                       "verified identity if any, contracts, invoices with outstanding amounts, and an index of "
                       "documents (id, kind, date) without their bodies.",
        "input_schema": {"type": "object", "properties": {"customer_id": {"type": "integer"}},
                         "required": ["customer_id"]},
    },
    {
        "name": "read_document",
        "description": "Full text of one document (delivery note, order, payment advice, contract).",
        "input_schema": {"type": "object", "properties": {"document_id": {"type": "integer"}},
                         "required": ["document_id"]},
    },
    {
        "name": "search_company",
        "description": "Search the official French company register (API Recherche d'entreprises) by name, "
                       "trade name or address words, optionally filtered by postal code. Returns SIREN, legal "
                       "name, trade names, head office, matching establishments and active/ceased status.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string"}, "postal_code": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "get_company",
        "description": "Official register record for one SIREN.",
        "input_schema": {"type": "object", "properties": {"siren": {"type": "string"}}, "required": ["siren"]},
    },
    {
        "name": "get_bodacc_history",
        "description": "All collective-procedure notices published in the BODACC for one SIREN, oldest first: "
                       "notice id, publication date, judgment date, judgment nature, event kind, officers, "
                       "and the judgment text. Checks the live API if the local store has nothing older.",
        "input_schema": {"type": "object", "properties": {"siren": {"type": "string"}}, "required": ["siren"]},
    },
    {
        "name": "record_identity",
        "description": "Record the verified identity of a customer. Use status VERIFIED only with a SIREN "
                       "confirmed by name AND address/postal code AND active status (or the debtor of a notice). "
                       "Use REVIEW when candidates remain ambiguous, NOT_FOUND when nothing fits.",
        "input_schema": {"type": "object", "properties": {
            "customer_id": {"type": "integer"},
            "status": {"type": "string", "enum": ["VERIFIED", "REVIEW", "NOT_FOUND"]},
            "siren": {"type": ["string", "null"]},
            "evidence": {"type": "string", "description": "What matched: name, address, status, sources."},
        }, "required": ["customer_id", "status", "evidence"]},
    },
    {
        "name": "compute_deadlines",
        "description": "Deterministic legal engine. Returns claim filing deadline, revendication deadline, "
                       "relief deadline, the anchoring opening notice, the opening judgment date, days left, "
                       "status (OK | REVIEW | CLOSED) and notes. Updates the case.",
        "input_schema": {"type": "object", "properties": {"case_id": {"type": "integer"}}, "required": ["case_id"]},
    },
    {
        "name": "record_claim_classification",
        "description": "Record when one invoice's claim arose, with evidence. Code then returns the category "
                       "(DECLARE | POST_OPENING | PAID | REVIEW) from the opening judgment date. Pass "
                       "fait_generateur_date null if documents are missing or conflict.",
        "input_schema": {"type": "object", "properties": {
            "case_id": {"type": "integer"},
            "invoice_id": {"type": "integer"},
            "fait_generateur_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
            "basis": {"type": "string", "enum": ["DELIVERY", "SERVICE_PERFORMED", "ORDER_ACCEPTANCE",
                                                 "CONTRACT_CONCLUSION"]},
            "evidence_document_id": {"type": ["integer", "null"]},
            "rationale": {"type": "string"},
        }, "required": ["case_id", "invoice_id", "fait_generateur_date", "basis", "rationale"]},
    },
    {
        "name": "propose_actions",
        "description": "Build the protective actions from what is recorded: claim draft (déclaration de créance) "
                       "addressed to the officer named in the notice, cash terms for new deliveries, "
                       "revendication alert if a retention-of-title clause exists. Code assembles amounts.",
        "input_schema": {"type": "object", "properties": {
            "case_id": {"type": "integer"},
            "officer_name": {"type": ["string", "null"], "description": "Mandataire judiciaire or liquidateur, as written in the notice."},
            "officer_role": {"type": ["string", "null"], "enum": ["mandataire judiciaire", "liquidateur", None]},
            "include_payment_terms_cash": {"type": "boolean"},
            "include_revendication_alert": {"type": "boolean"},
        }, "required": ["case_id", "include_payment_terms_cash", "include_revendication_alert"]},
    },
    {
        "name": "flag_lawyer_review",
        "description": "Escalate a point outside scope or unresolved, with the reason.",
        "input_schema": {"type": "object", "properties": {
            "case_id": {"type": ["integer", "null"]}, "customer_id": {"type": ["integer", "null"]},
            "reason": {"type": "string"}}, "required": ["reason"]},
    },
    {
        "name": "finish",
        "description": "End the run.",
        "input_schema": {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["READY", "NEEDS_REVIEW", "NO_CASE", "IDENTITY_RESOLVED"]},
            "summary": {"type": "string", "description": "Two sentences max, shown to the user."}},
            "required": ["status", "summary"]},
    },
]


def task_resolve_identity(customer_id: int) -> str:
    return (f"Task RESOLVE_IDENTITY for customer_id={customer_id}. Read the customer file and the delivery "
            "addresses in its documents, find the legal entity in the official register, record the identity, "
            "then check get_bodacc_history for the verified SIREN. If record_identity opens a case, continue in this "
            "run: compute deadlines, classify every unpaid invoice from its documents, propose actions, finish. "
            "Otherwise finish with IDENTITY_RESOLVED (or NO_CASE) and say whether a collective procedure exists.")


def task_investigate_case(case_id: int, customer_id: int, trigger: str) -> str:
    return (f"Task INVESTIGATE_CASE case_id={case_id} customer_id={customer_id}. Trigger: {trigger}. "
            "Confirm the identity, get the full BODACC history, compute deadlines, classify every unpaid invoice "
            "from its documents, propose actions, escalate what is out of scope, finish.")


def run_agent(task: str, handlers: dict[str, Callable[..., dict]], on_step: Callable[..., None],
              max_turns: int = MAX_TURNS) -> dict:
    """on_step(kind, tool=None, payload=None) persists to agent_steps (UI polls it)."""
    client = anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": task}]
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(max_turns):
        resp = client.messages.create(model=MODEL, max_tokens=2048, tools=TOOLS, messages=messages,
                                      system=[{"type": "text", "text": SYSTEM_PROMPT,
                                               "cache_control": {"type": "ephemeral"}}])
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})

        for block in resp.content:
            if block.type == "text" and block.text.strip():
                on_step("NOTE", payload={"text": block.text.strip()})
        if resp.stop_reason != "tool_use":
            return {"status": "NEEDS_REVIEW", "summary": "Agent stopped without finishing.", "usage": usage}

        results = []
        finished = None
        for block in resp.content:
            if block.type != "tool_use":
                continue
            on_step("TOOL_CALL", tool=block.name, payload=block.input)
            try:
                out = handlers[block.name](**block.input)
            except Exception as e:  # tool errors go back to the model, never crash the run
                out = {"error": f"{type(e).__name__}: {e}"}
                on_step("ERROR", tool=block.name, payload=out)
            else:
                on_step("TOOL_RESULT", tool=block.name, payload=out)
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(out, default=str, ensure_ascii=False)})
            if block.name == "finish":
                finished = {**block.input, "usage": usage}
        messages.append({"role": "user", "content": results})
        if finished:
            return finished

    return {"status": "NEEDS_REVIEW", "summary": "Turn limit reached.", "usage": usage}
