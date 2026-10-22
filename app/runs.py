"""Agent runs in background threads; every step persisted to agent_steps (the UI polls it)."""
from __future__ import annotations

import logging
import os
import threading
import uuid

from app import agent
from app.db import Jsonb, transaction
from app.tools import RunContext, _dumps, make_handlers

log = logging.getLogger("forclos.runs")
MAX_CONCURRENT_RUNS = 6
MAX_RUNS_PER_10_MIN = int(os.getenv("FORCLOS_MAX_RUNS_PER_10_MIN", "40"))  # the URL is public; runs cost tokens
_slots = threading.Semaphore(MAX_CONCURRENT_RUNS)


class RunLimitError(RuntimeError):
    pass


def _on_step(run_id: str):
    def on_step(kind: str, tool: str | None = None, payload=None) -> None:
        with transaction() as conn:
            conn.execute("insert into agent_steps (run_id, kind, tool, payload) values (%s, %s, %s, %s)",
                         (run_id, kind, tool, Jsonb(payload, dumps=_dumps)))
    return on_step


def _execute(ctx: RunContext, task: str) -> dict:
    with _slots:
        on_step = _on_step(ctx.run_id)
        try:
            result = agent.run_agent(task, make_handlers(ctx), on_step)
            status = "DONE"
        except Exception as e:
            log.exception("agent run %s failed", ctx.run_id)
            on_step("ERROR", payload={"error": f"{type(e).__name__}: {e}"[:500]})
            result = {"status": "NEEDS_REVIEW", "summary": f"Run failed: {type(e).__name__}.", "usage": {}}
            status = "ERROR"
        usage = result.get("usage") or {}
        with transaction() as conn:
            conn.execute(
                """update agent_runs set status = %s, summary = %s, input_tokens = %s, output_tokens = %s,
                   finished_at = now() where id = %s""",
                (status, result.get("summary"), usage.get("input_tokens"), usage.get("output_tokens"), ctx.run_id))
            if ctx.case_id:  # a run that never called finish leaves the case for a human
                conn.execute("update cases set status = 'NEEDS_REVIEW', updated_at = now() "
                             "where id = %s and status = 'INVESTIGATING'", (ctx.case_id,))
        return result


def start_run(kind: str, task: str, case_id: int | None = None, customer_id: int | None = None,
              wait: bool = False) -> str | dict:
    """kind: RESOLVE_IDENTITY | INVESTIGATE_CASE. Returns the run id (or the result when wait=True)."""
    ctx = RunContext(run_id=str(uuid.uuid4()), case_id=case_id, customer_id=customer_id)
    with transaction() as conn:
        recent = conn.execute("select count(*) as n from agent_runs where started_at > now() - interval '10 minutes'"
                              ).fetchone()["n"]
        if not wait and recent >= MAX_RUNS_PER_10_MIN:
            raise RunLimitError("Too many agent runs in the last 10 minutes. Try again shortly.")
        conn.execute("insert into agent_runs (id, case_id, customer_id, task, model) values (%s, %s, %s, %s, %s)",
                     (ctx.run_id, case_id, customer_id, kind, agent.MODEL))
        if case_id:
            conn.execute("update cases set status = 'INVESTIGATING', updated_at = now() where id = %s", (case_id,))
    if wait:
        return {"run_id": ctx.run_id, **_execute(ctx, task)}
    threading.Thread(target=_execute, args=(ctx, task), daemon=True, name=f"run-{ctx.run_id[:8]}").start()
    return ctx.run_id


def investigate_case(case_id: int, customer_id: int, trigger: str, wait: bool = False):
    return start_run("INVESTIGATE_CASE", agent.task_investigate_case(case_id, customer_id, trigger),
                     case_id=case_id, customer_id=customer_id, wait=wait)


def resolve_identity(customer_id: int, wait: bool = False):
    return start_run("RESOLVE_IDENTITY", agent.task_resolve_identity(customer_id),
                     customer_id=customer_id, wait=wait)
