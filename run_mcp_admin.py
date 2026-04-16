"""
run_mcp_admin.py
================
Serveur MCP 3 — Marketing & Support & Fiscal & Recherche & PDF
Port : 8767

Tools inclus (7) :
  - admin_marketing_liste
  - admin_catalogue_liste
  - admin_support_conversations
  - admin_support_messages
  - admin_fiscal_regles
  - admin_recherche_globale
  - admin_rapport_pdf
"""
import sys, os
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.tools.admin_marketing    import admin_marketing_liste, admin_catalogue_liste
from easyvoyage_mcp.tools.admin_support      import admin_support_conversations, admin_support_messages
from easyvoyage_mcp.tools.admin_fiscal       import admin_fiscal_regles
from easyvoyage_mcp.tools.admin_search       import admin_recherche_globale
from easyvoyage_mcp.tools.admin_reports_pdf  import admin_rapport_pdf

mcp = FastMCP("easyvoyage-marketing-support-admin")

mcp.tool()(admin_marketing_liste)
mcp.tool()(admin_catalogue_liste)
mcp.tool()(admin_support_conversations)
mcp.tool()(admin_support_messages)
mcp.tool()(admin_fiscal_regles)
mcp.tool()(admin_recherche_globale)
mcp.tool()(admin_rapport_pdf)

if __name__ == "__main__":
    print("📢  MCP 3 — Marketing / Support / Admin  →  http://localhost:8767/mcp")
    mcp.settings.port = 8767
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")