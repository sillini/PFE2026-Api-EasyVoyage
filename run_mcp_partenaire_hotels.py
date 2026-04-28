"""
run_mcp_partenaire_hotels.py
=============================
Serveur MCP PARTENAIRE 1 — Hotels, Chambres, Tarifs, Avis
Port MCP   : 8785
Port Cache : 9100 (partage entre tous les MCP — demarre si pas deja lance)

Tools inclus (9) :
  - partenaire_profil
  - partenaire_mes_hotels
  - partenaire_hotel_detail_par_nom
  - partenaire_hotel_avis
  - partenaire_chambres_liste
  - partenaire_chambre_detail
  - partenaire_tarifs_liste
  - partenaire_hotel_disponibilites
  - partenaire_hotel_statistiques

CONFIGURATION N8N (node MCP Client Tool) :
  Endpoint  : http://127.0.0.1:8785/mcp
  Transport : HTTP Streamable
  Auth      : None (JWT gere via cache sur session_id)

  Si n8n tourne dans Docker (et pas en natif), utiliser :
    http://host.docker.internal:8785/mcp

PREREQUIS :
  - Le backend FastAPI tourne (par defaut http://localhost:8000)
  - Variable d'env BACKEND_URL dans .env si differente
  - Le partenaire doit etre authentifie (JWT role=PARTENAIRE)
"""
import sys
import os

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

# Demarrer le cache JWT en premier (partage entre tous les MCP)
from easyvoyage_mcp.session_cache import start_cache_server
try:
    start_cache_server()
except OSError:
    # Deja lance par un autre MCP server sur le meme port
    pass

from easyvoyage_mcp.tools.partenaire_hotels import (
    partenaire_profil,
    partenaire_mes_hotels,
    partenaire_hotel_detail_par_nom,
    partenaire_hotel_avis,
    partenaire_chambres_liste,
    partenaire_chambre_detail,
    partenaire_tarifs_liste,
    partenaire_hotel_disponibilites,
    partenaire_hotel_statistiques,
)


mcp = FastMCP("easyvoyage-partenaire-hotels")

mcp.tool()(partenaire_profil)
mcp.tool()(partenaire_mes_hotels)
mcp.tool()(partenaire_hotel_detail_par_nom)
mcp.tool()(partenaire_hotel_avis)
mcp.tool()(partenaire_chambres_liste)
mcp.tool()(partenaire_chambre_detail)
mcp.tool()(partenaire_tarifs_liste)
mcp.tool()(partenaire_hotel_disponibilites)
mcp.tool()(partenaire_hotel_statistiques)


if __name__ == "__main__":
    backend = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
    print("🏨  MCP PARTENAIRE 1 — Hotels / Chambres / Tarifs  →  http://127.0.0.1:8785/mcp")
    print(f"    Backend : {backend}")
    print(f"    Tools   : 9 (profil, hotels, chambres, tarifs, avis, dispos, stats)")
    print(f"    Auth    : session_id (JWT dans cache local port 9100)")

    mcp.settings.port = 8785
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")