"""Postgres access (Aiven for PostgreSQL). One pool, dict rows, autocommit by default.
Use `with transaction() as conn:` when several writes must land together."""
from __future__ import annotations

import atexit
import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

load_dotenv()

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
_pool: ConnectionPool | None = None

__all__ = ["Jsonb", "execute", "init_schema", "pool", "query", "query_one", "transaction"]


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = ConnectionPool(url, min_size=1, max_size=int(os.getenv("DB_POOL_MAX", "12")),
                               kwargs={"row_factory": dict_row, "autocommit": True}, open=True)
        atexit.register(_pool.close)
    return _pool


def init_schema() -> None:
    with pool().connection() as conn:
        conn.execute(SCHEMA.read_text())


def query(sql: str, params=None) -> list[dict]:
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def query_one(sql: str, params=None) -> dict | None:
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params=None) -> None:
    with pool().connection() as conn:
        conn.execute(sql, params)


@contextmanager
def transaction():
    with pool().connection() as conn:
        with conn.transaction():
            yield conn
