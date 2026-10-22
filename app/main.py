"""FORCLOS API + static page. One process: FastAPI, sync handlers (run in the threadpool), psycopg pool."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db, scheduler
from app.runs import RunLimitError
from app.routes_cases import router as cases_router
from app.routes_data import router as data_router

STATIC = Path(__file__).resolve().parents[1] / "static"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("forclos")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        db.init_schema()
        scheduler.start()
    except Exception:  # the page and /api/health still come up and report the DB error
        log.exception("schema init failed")
    yield


app = FastAPI(title="FORCLOS", lifespan=lifespan)
app.include_router(data_router)
app.include_router(cases_router)


@app.exception_handler(RunLimitError)
def run_limit(_: Request, exc: RunLimitError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=429)


@app.get("/api/health")
def health() -> dict:
    try:
        row = db.query_one("select now() as db_time, (select count(*) from bodacc_notices) as notices, "
                           "(select count(*) from cases) as cases")
        return {"ok": True, "db": "ok", **row}
    except Exception as e:
        return {"ok": False, "db": f"{type(e).__name__}: {e}"[:300]}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
