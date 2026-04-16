"""
mcp/database.py
===============
Connexion PostgreSQL synchrone partagée par tous les tools MCP.
Lit DATABASE_URL depuis le .env du projet EasyVoyage.
"""

import os
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

_RAW_URL  = os.getenv("DATABASE_URL", "postgresql://postgres:malek123@localhost:5432/voyage_hotel")
DSN       = _RAW_URL.replace("postgresql+asyncpg://", "postgresql://")
DB_SCHEMA = "voyage_hotel"


def _conn():
    """Ouvre une connexion avec search_path = voyage_hotel."""
    c = psycopg2.connect(DSN, cursor_factory=psycopg2.extras.RealDictCursor)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute(f"SET search_path TO {DB_SCHEMA}, public")
    return c


def db_fetch(sql: str, *params) -> list:
    """SELECT → liste de dicts."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or None)
            return [dict(r) for r in cur.fetchall()]


def db_fetchrow(sql: str, *params) -> Optional[dict]:
    """SELECT → un seul dict ou None."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or None)
            row = cur.fetchone()
            return dict(row) if row else None


def db_execute(sql: str, *params) -> list:
    """INSERT / UPDATE avec RETURNING → liste de dicts."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or None)
            try:
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                return []