"""
run_mcp_partenaire_finances.py
===============================
Serveur MCP PARTENAIRE 2 — Finances, Revenus, Reservations
Port MCP   : 8786
Port Cache : 9100 (partage entre tous les MCP — demarre si pas deja lance)

Tools inclus (9) :
  - partenaire_dashboard
  - partenaire_revenus_mensuels
  - partenaire_finances_mes_hotels
  - partenaire_reservations_financieres
  - partenaire_paiements_recus
  - partenaire_mes_demandes_retrait
  - partenaire_reservations_mes_hotels
  - partenaire_reservations_par_hotel
  - partenaire_bilan_financier

CONFIGURATION N8N (node MCP Client Tool) :
  Endpoint  : http://127.0.0.1:8786/mcp
  Transport : HTTP Streamable
  Auth      : None (JWT gere via cache sur session_id)

  Si n8n tourne dans Docker (et pas en natif), utiliser :
    http://host.docker.internal:8786/mcp

PREREQUIS :
  - Le backend FastAPI tourne (par defaut http://localhost:8000)
  - Variable d'env BACKEND_URL dans .env si differente
  - Le partenaire doit etre authentifie (JWT role=PARTENAIRE)

LECTURE SEULE :
  Ces tools sont en LECTURE SEULE. Les demandes de retrait, paiements et
  virements doivent passer par l'interface officielle (pas via l'IA).
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

from easyvoyage_mcp.tools.partenaire_finances import (
    partenaire_dashboard,
    partenaire_revenus_mensuels,
    partenaire_finances_mes_hotels,
    partenaire_reservations_financieres,
    partenaire_paiements_recus,
    partenaire_mes_demandes_retrait,
    partenaire_reservations_mes_hotels,
    partenaire_reservations_par_hotel,
    partenaire_bilan_financier,
)


mcp = FastMCP("easyvoyage-partenaire-finances")

mcp.tool()(partenaire_dashboard)
mcp.tool()(partenaire_revenus_mensuels)
mcp.tool()(partenaire_finances_mes_hotels)
mcp.tool()(partenaire_reservations_financieres)
mcp.tool()(partenaire_paiements_recus)
mcp.tool()(partenaire_mes_demandes_retrait)
mcp.tool()(partenaire_reservations_mes_hotels)
mcp.tool()(partenaire_reservations_par_hotel)
mcp.tool()(partenaire_bilan_financier)


if __name__ == "__main__":
    backend = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
    print("💰  MCP PARTENAIRE 2 — Finances / Reservations  →  http://127.0.0.1:8786/mcp")
    print(f"    Backend : {backend}")
    print(f"    Tools   : 9 (dashboard, revenus, reservations, paiements, demandes, bilan)")
    print(f"    Auth    : session_id (JWT dans cache local port 9100)")

    mcp.settings.port = 8786
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")