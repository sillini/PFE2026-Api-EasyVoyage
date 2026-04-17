"""
mcp/database.py
===============
Connexion PostgreSQL synchrone partagée par tous les tools MCP.
Lit DATABASE_URL depuis le .env du projet EasyVoyage.

⚠️  CORRECTION RLS :
  Les tools MCP doivent lire TOUTES les données (vue admin global).
  Si la base a des politiques RLS (Row Level Security) activées sur
  des tables comme `client`, `partenaire`, `reservation`, etc.,
  l'utilisateur PostgreSQL ne verra que ses propres lignes → tables vides.

  → On désactive RLS au niveau session avec `SET row_security = off`.
     Cela nécessite que l'utilisateur DB ait soit :
       • le rôle SUPERUSER (postgres par défaut)
       • ou l'attribut BYPASSRLS
     Sinon on log un warning mais on continue (les policies s'appliqueront).
"""

import os
import logging
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_RAW_URL  = os.getenv("DATABASE_URL", "postgresql://postgres:malek123@localhost:5432/voyage_hotel")
DSN       = _RAW_URL.replace("postgresql+asyncpg://", "postgresql://")
DB_SCHEMA = "voyage_hotel"


def _conn():
    """
    Ouvre une connexion avec :
      - search_path = voyage_hotel, public
      - row_security = off  (bypass RLS pour le MCP admin)
    """
    c = psycopg2.connect(DSN, cursor_factory=psycopg2.extras.RealDictCursor)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute(f"SET search_path TO {DB_SCHEMA}, public")

        # ── Bypass RLS (le MCP admin doit voir TOUTES les lignes) ──
        try:
            cur.execute("SET row_security = off")
        except psycopg2.Error as e:
            # Si l'user DB n'a pas SUPERUSER/BYPASSRLS, on log et on continue
            logger.warning(
                "Impossible de désactiver RLS : %s. "
                "Les politiques RLS vont s'appliquer — certaines données "
                "peuvent être masquées. Utilisez un user SUPERUSER ou "
                "ajoutez BYPASSRLS à l'user courant.",
                e,
            )
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