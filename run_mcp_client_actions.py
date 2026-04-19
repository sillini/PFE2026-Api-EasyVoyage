"""
run_mcp_client_actions.py
==========================
Serveur MCP CLIENT 3 — Actions
Port MCP : 8777
"""
import sys
import os

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

# Cache partage entre MCP servers — demarre si pas deja lance
from easyvoyage_mcp.session_cache import start_cache_server
try:
    start_cache_server()
except OSError:
    # Deja lance par un autre MCP server sur le meme port
    pass

from easyvoyage_mcp.tools.client_actions import (
    client_favori_toggle,
    client_reserver_voyage,
    client_reserver_chambres,
    client_payer_reservation,
    client_annuler_reservation,
    client_simuler_reservation_chambres,
)


mcp = FastMCP("easyvoyage-client-actions")

mcp.tool()(client_favori_toggle)
mcp.tool()(client_reserver_voyage)
mcp.tool()(client_reserver_chambres)
mcp.tool()(client_payer_reservation)
mcp.tool()(client_annuler_reservation)
mcp.tool()(client_simuler_reservation_chambres)


if __name__ == "__main__":
    backend = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
    print("🎯  MCP CLIENT 3 — Actions  →  http://127.0.0.1:8777/mcp")
    print(f"    Backend : {backend}")
    print(f"    Tools   : 6 (favoris, reserver, payer, annuler, simuler)")
    print(f"    Auth    : session_id (JWT dans cache local)")

    mcp.settings.port = 8777
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")