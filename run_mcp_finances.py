"""
run_mcp_finances.py
===================
Serveur MCP 2 — Finances & Partenaires & Promotions
Port : 8766

Tools inclus (7) :
  - admin_partenaires_liste
  - admin_partenaire_detail
  - admin_partenaires_demandes
  - admin_promotions_liste
  - admin_finances_dashboard
  - admin_finances_commissions
  - admin_factures_liste
"""
import sys, os
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.tools.admin_partenaires import (
    admin_partenaires_liste, admin_partenaire_detail, admin_partenaires_demandes
)
from easyvoyage_mcp.tools.admin_promotions  import admin_promotions_liste
from easyvoyage_mcp.tools.admin_finances    import admin_finances_dashboard, admin_finances_commissions
from easyvoyage_mcp.tools.admin_factures    import admin_factures_liste

mcp = FastMCP("easyvoyage-finances-partenaires-promotions")

mcp.tool()(admin_partenaires_liste)
mcp.tool()(admin_partenaire_detail)
mcp.tool()(admin_partenaires_demandes)
mcp.tool()(admin_promotions_liste)
mcp.tool()(admin_finances_dashboard)
mcp.tool()(admin_finances_commissions)
mcp.tool()(admin_factures_liste)

if __name__ == "__main__":
    print("💰  MCP 2 — Finances / Partenaires / Promotions  →  http://localhost:8766/mcp")
    mcp.settings.port = 8766
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")