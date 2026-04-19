"""
run_mcp_client_catalog.py
==========================
Serveur MCP CLIENT 1 — Catalogue public EasyVoyage
Port : 8775

Tools inclus (9) :
  - client_hotels_liste
  - client_hotel_detail_par_nom
  - client_hotels_featured
  - client_villes_vedettes
  - client_hotel_disponibilites
  - client_voyages_liste
  - client_voyage_detail_par_titre
  - client_promotion_hotel
  - client_fiscal_preview

Aucun JWT requis — tous les endpoints appeles sont publics.

CONFIGURATION N8N (node MCP Client Tool) :
  Endpoint  : http://127.0.0.1:8775/mcp
  (meme logique que le MCP admin sur 127.0.0.1:8765)
  Transport : HTTP Streamable
  Auth      : None

  Si n8n tourne dans Docker (et pas en natif), utiliser :
    http://host.docker.internal:8775/mcp

PREREQUIS :
  - Le backend FastAPI tourne (par defaut http://localhost:8000)
  - Variable d'env BACKEND_URL dans .env si differente
"""
import sys
import os

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from easyvoyage_mcp.tools.client_catalog import (
    client_hotels_liste,
    client_hotel_detail_par_nom,
    client_hotels_featured,
    client_villes_vedettes,
    client_hotel_disponibilites,
    client_voyages_liste,
    client_voyage_detail_par_titre,
    client_promotion_hotel,
    client_fiscal_preview,
)


mcp = FastMCP("easyvoyage-client-catalog")

mcp.tool()(client_hotels_liste)
mcp.tool()(client_hotel_detail_par_nom)
mcp.tool()(client_hotels_featured)
mcp.tool()(client_villes_vedettes)
mcp.tool()(client_hotel_disponibilites)
mcp.tool()(client_voyages_liste)
mcp.tool()(client_voyage_detail_par_titre)
mcp.tool()(client_promotion_hotel)
mcp.tool()(client_fiscal_preview)


if __name__ == "__main__":
    backend = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
    print("🔎  MCP CLIENT 1 — Catalogue public  →  http://127.0.0.1:8775/mcp")
    print(f"    Backend : {backend}")
    print(f"    Tools   : 9 (hotels, voyages, promos, fiscal)")
    print(f"    Auth    : aucune (endpoints publics)")

    mcp.settings.port = 8775
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")
