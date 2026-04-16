"""
mcp/tools/admin_fiscal.py
==========================
Tools MCP — Règles fiscales.
Correspond à : FiscalConfig.jsx

Tools :
  admin_fiscal_regles → toutes les règles (TVA, taxe séjour, droit timbre)
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lire les règles fiscales configurées — page FiscalConfig. "
    "Retourne toutes les règles actives et inactives : "
    "id, type_taxe (TVA|TAXE_SEJOUR|DROIT_TIMBRE), taux, description, "
    "conditions_application, actif, created_at, updated_at. "
    "Aucun paramètre requis."
))
def admin_fiscal_regles() -> str:
    try:
        rows = db_fetch("""
            SELECT
                id, type_taxe, taux, description,
                conditions_application, actif,
                created_at, updated_at
            FROM regle_fiscale
            ORDER BY type_taxe, actif DESC
        """)
        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)