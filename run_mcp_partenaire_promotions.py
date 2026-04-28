"""
run_mcp_partenaire_promotions.py
=================================
Serveur MCP PARTENAIRE 3 — Promotions, Support, Notifications
Port MCP   : 8787
Port Cache : 9100 (partage entre tous les MCP — demarre si pas deja lance)

NOTE : Le partenaire N'A PAS acces au module Marketing (reserve a l'admin).
       Ce serveur couvre uniquement Promotions + Support + Notifications.

Tools inclus (7) :
  - partenaire_promotions_liste
  - partenaire_promotion_detail
  - partenaire_promotion_active_hotel
  - partenaire_support_conversations
  - partenaire_support_messages
  - partenaire_notifications
  - partenaire_vue_globale

CONFIGURATION N8N (node MCP Client Tool) :
  Endpoint  : http://127.0.0.1:8787/mcp
  Transport : HTTP Streamable
  Auth      : None (JWT gere via cache sur session_id)

  Si n8n tourne dans Docker (et pas en natif), utiliser :
    http://host.docker.internal:8787/mcp

PREREQUIS :
  - Le backend FastAPI tourne (par defaut http://localhost:8000)
  - Variable d'env BACKEND_URL dans .env si differente
  - Le partenaire doit etre authentifie (JWT role=PARTENAIRE)

LECTURE SEULE :
  Ces tools sont en LECTURE SEULE. Creer/modifier/supprimer des promotions
  ou envoyer des messages support doit se faire via l'interface officielle.
"""
import sys
import os

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

# Cache partage — demarre si pas deja lance
from easyvoyage_mcp.session_cache import start_cache_server
try:
    start_cache_server()
except OSError:
    pass

from easyvoyage_mcp.tools.partenaire_promotions_support import (
    partenaire_promotions_liste,
    partenaire_promotion_detail,
    partenaire_promotion_active_hotel,
    partenaire_support_conversations,
    partenaire_support_messages,
    partenaire_notifications,
    partenaire_vue_globale,
)


mcp = FastMCP("easyvoyage-partenaire-promotions-support")

mcp.tool()(partenaire_promotions_liste)
mcp.tool()(partenaire_promotion_detail)
mcp.tool()(partenaire_promotion_active_hotel)
mcp.tool()(partenaire_support_conversations)
mcp.tool()(partenaire_support_messages)
mcp.tool()(partenaire_notifications)
mcp.tool()(partenaire_vue_globale)


if __name__ == "__main__":
    backend = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
    print("🎯  MCP PARTENAIRE 3 — Promotions / Support  →  http://127.0.0.1:8787/mcp")
    print(f"    Backend : {backend}")
    print(f"    Tools   : 7 (promotions, support, notifications, vue globale)")
    print(f"    Auth    : session_id (JWT dans cache local port 9100)")

    mcp.settings.port = 8787
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")