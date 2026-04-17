"""
run_mcp_admin.py
================
Serveur MCP 3 — Marketing & Support & Fiscal & Recherche & PDF
Port : 8767

Tools inclus (12) :

  MARKETING (6 tools) :
    - admin_marketing_liste
    - admin_catalogue_liste
    - admin_facebook_publications       ← NOUVEAU v3
    - admin_facebook_config             ← NOUVEAU v3
    - admin_video_campaigns_liste       ← NOUVEAU v3
    - admin_video_campaign_detail       ← NOUVEAU v3

  SUPPORT (3 tools) :
    - admin_support_conversations
    - admin_support_messages
    - admin_support_conversations_partenaire  ← NOUVEAU v3

  AUTRES :
    - admin_fiscal_regles
    - admin_recherche_globale
    - admin_rapport_pdf
"""
import sys, os
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

# ── Marketing (enrichi avec Facebook + Videos) ─────────────
from easyvoyage_mcp.tools.admin_marketing import (
    admin_marketing_liste,
    admin_catalogue_liste,
    admin_facebook_publications,
    admin_facebook_config,
    admin_video_campaigns_liste,
    admin_video_campaign_detail,
)

# ── Support (3 tools, tous par email/nom/sujet, jamais par ID) ──
from easyvoyage_mcp.tools.admin_support import (
    admin_support_conversations,
    admin_support_messages,
    admin_support_conversations_partenaire,
)

# ── Autres tools ──────────────────────────────────────────
from easyvoyage_mcp.tools.admin_fiscal      import admin_fiscal_regles
from easyvoyage_mcp.tools.admin_search      import admin_recherche_globale
from easyvoyage_mcp.tools.admin_reports_pdf import admin_rapport_pdf


mcp = FastMCP("easyvoyage-marketing-support-admin")

# Enregistrement des 12 tools
mcp.tool()(admin_marketing_liste)
mcp.tool()(admin_catalogue_liste)
mcp.tool()(admin_facebook_publications)
mcp.tool()(admin_facebook_config)
mcp.tool()(admin_video_campaigns_liste)
mcp.tool()(admin_video_campaign_detail)

mcp.tool()(admin_support_conversations)
mcp.tool()(admin_support_messages)
mcp.tool()(admin_support_conversations_partenaire)

mcp.tool()(admin_fiscal_regles)
mcp.tool()(admin_recherche_globale)
mcp.tool()(admin_rapport_pdf)


if __name__ == "__main__":
    print("📢  MCP 3 — Marketing / Support / Admin  →  http://localhost:8767/mcp")
    print("   Tools : 12 (Marketing x6, Support x3, Fiscal x1, Search x1, PDF x1)")
    mcp.settings.port = 8767
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")