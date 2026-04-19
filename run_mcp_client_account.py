"""
run_mcp_client_account.py
==========================
Serveur MCP CLIENT 2 — Espace personnel
Port MCP  : 8776
Port Cache : 9100 (demarre automatiquement)
"""
import sys
import os

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

# Demarrer le cache JWT en premier
from easyvoyage_mcp.session_cache import start_cache_server
start_cache_server()

from easyvoyage_mcp.tools.client_account import (
    client_profil,
    client_mes_reservations,
    client_reservation_detail,
    client_mes_favoris,
    client_favori_status,
    client_mes_factures,
)


mcp = FastMCP("easyvoyage-client-account")

mcp.tool()(client_profil)
mcp.tool()(client_mes_reservations)
mcp.tool()(client_reservation_detail)
mcp.tool()(client_mes_favoris)
mcp.tool()(client_favori_status)
mcp.tool()(client_mes_factures)


if __name__ == "__main__":
    backend = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
    print("👤  MCP CLIENT 2 — Espace personnel  →  http://127.0.0.1:8776/mcp")
    print(f"    Backend : {backend}")
    print(f"    Tools   : 6 (profil, reservations, favoris, factures)")
    print(f"    Auth    : session_id (JWT dans cache local)")

    mcp.settings.port = 8776
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")