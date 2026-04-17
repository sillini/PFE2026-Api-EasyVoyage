"""
run_mcp_hotels.py
=================
Serveur MCP 1 — Hotels & Reservations & Clients
Port : 8765

Tools inclus :
  - admin_dashboard_kpis
  - admin_hotels_liste
  - admin_hotel_detail
  - admin_hotels_avis
  - admin_hotels_classement_satisfaction  ← NOUVEAU
  - admin_reservations_liste
  - admin_reservation_detail
  - admin_clients_liste
  - admin_client_detail
"""
import sys, os
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.tools.admin_dashboard    import admin_dashboard_kpis
from easyvoyage_mcp.tools.admin_hotels       import (
    admin_hotels_liste,
    admin_hotel_detail,
    admin_hotels_avis,
    admin_hotels_classement_satisfaction,
)
from easyvoyage_mcp.tools.admin_reservations import admin_reservations_liste, admin_reservation_detail
from easyvoyage_mcp.tools.admin_clients      import admin_clients_liste, admin_client_detail

mcp = FastMCP("easyvoyage-hotels-reservations-clients")

mcp.tool()(admin_dashboard_kpis)
mcp.tool()(admin_hotels_liste)
mcp.tool()(admin_hotel_detail)
mcp.tool()(admin_hotels_avis)
mcp.tool()(admin_hotels_classement_satisfaction)
mcp.tool()(admin_reservations_liste)
mcp.tool()(admin_reservation_detail)
mcp.tool()(admin_clients_liste)
mcp.tool()(admin_client_detail)

if __name__ == "__main__":
    print("🏨  MCP 1 — Hotels / Reservations / Clients  →  http://localhost:8765/mcp")
    mcp.settings.port = 8765
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")