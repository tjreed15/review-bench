"""Postgres connection management for Cloud SQL with connection pooling."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()

_DATABASE_URL: str | None = None
_pool: ConnectionPool | None = None


def get_database_url() -> str:
    global _DATABASE_URL
    if _DATABASE_URL is None:
        _DATABASE_URL = os.environ.get("DATABASE_URL")
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL environment variable not set")
    return _DATABASE_URL


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_database_url(),
            min_size=0,
            max_size=10,
            timeout=60,
            reconnect_timeout=300,
            kwargs={"autocommit": False, "connect_timeout": 30},
        )
    return _pool


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    """Get a database connection from the pool."""
    pool = _get_pool()
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def fetch_one(sql: str, params: tuple | dict | None = None) -> dict | None:
    """Fetch a single row as a dict."""
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        cols = [desc.name for desc in cur.description]
        return dict(zip(cols, row))


def fetch_all(sql: str, params: tuple | dict | None = None) -> list[dict]:
    """Fetch all rows as dicts."""
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        cols = [desc.name for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
