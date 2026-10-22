# Start here (5 minutes)

```bash
cd forclos
git init && git add . && git commit -m "FORCLOS starter"
git remote add origin git@github.com:<you>/forclos.git && git push -u origin main
cp .env.example .env            # paste Aiven DATABASE_URL + ANTHROPIC_API_KEY
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                        # legal engine + parser tests must pass
```

## Prompts to paste in Claude Code

**Session 0 (now, alone):**
> Read CLAUDE.md fully. Do build steps 0 and 1: run scripts/sample_bodacc.py, fix app/bodacc.py and
> app/sirene.py against the real responses until all tests pass (do not weaken tests), then write app/db.py
> and app/main.py with /api/health and the static page, and get it deployed on Aiven Runtime from the GitHub
> repo with DATABASE_URL set. Check Aiven Runtime docs for port and env conventions. Stop when the deployed
> URL returns health OK with a DB round-trip, and tell me the exact JSON shapes you saw for jugement and listepersonnes.

**Then three sessions in parallel (separate terminals, same repo):**

DATA
> Read CLAUDE.md. You own app/ingest.py, app/routes_data.py, scripts/seed_demo.py and nothing else.
> Implement §6 data routes, ingestion (upsert, rule SIREN matching, cases, case_events, RULE classifications),
> then the demo seed of §8 written to data/demo_seed.json with /api/demo/reset. Commit often.

AGENT
> Read CLAUDE.md. You own app/tools.py, app/runs.py, app/routes_cases.py and nothing else. Implement every
> handler of §7 against the TOOLS in app/agent.py, background runs persisted to agent_runs/agent_steps, and the
> §6 case routes. Build and test trap C (invoice dated after judgment, delivery before) end to end first.

UI
> Read CLAUDE.md, especially §6 and §10, and load the frontend-design skill. You own static/index.html only.
> Build it against mocked JSON matching §6 exactly, behind a MOCK flag, then switch to the live API.
> Projector-legible, dark, big countdown, RULE/AGENT badges, "+€X added to claim" highlight.

**After DATA + AGENT are merged:**
> Read CLAUDE.md §9. Write benchmark/build.py and benchmark/run.py, build the cases, run the dev split for
> NAIVE, RULES, FORCLOS, and show me the metrics and every FORCLOS failure. Do not touch the held-out split.
