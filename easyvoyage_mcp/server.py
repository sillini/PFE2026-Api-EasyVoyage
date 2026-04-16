"""
mcp/server.py
=============
Point d'entrée du serveur MCP EasyVoyage — Espace Admin.

Ce fichier assemble tous les tools depuis mcp/tools/.
Chaque fichier tools/ correspond à une page de l'espace admin.

Structure :
  mcp/
  ├── server.py                  ← CE FICHIER
  ├── database.py                ← connexion psycopg2 partagée
  └── tools/
      ├── admin_dashboard.py     → AdminDashboard.jsx
      ├── admin_hotels.py        → AdminHotels.jsx + AdminHotelsVedettes.jsx
      ├── admin_reservations.py  → AdminReservations.jsx
      ├── admin_clients.py       → AdminClients.jsx
      ├── admin_partenaires.py   → AdminPartenaires.jsx + AdminDemandesPartenaire.jsx
      ├── admin_promotions.py    → AdminPromotions.jsx
      ├── admin_finances.py      → AdminFinances.jsx
      ├── admin_factures.py      → AdminFactures.jsx
      ├── admin_marketing.py     → AdminMarketing.jsx + AdminCatalogue.jsx
      ├── admin_support.py       → AdminSupport.jsx
      ├── admin_fiscal.py        → FiscalConfig.jsx
      ├── admin_search.py        → recherche transversale (utilitaire)
      └── admin_reports_pdf.py   → rapport PDF téléchargeable

Lancement standalone :
    python run_mcp.py

Ou via Claude Desktop (mcp.json) :
    { "command": "python", "args": ["run_mcp.py"], "cwd": "/chemin/projet" }
"""

from mcp.server.fastmcp import FastMCP

from easyvoyage_mcp.tools.admin_dashboard    import admin_dashboard_kpis
from easyvoyage_mcp.tools.admin_hotels       import admin_hotels_liste, admin_hotel_detail, admin_hotels_avis
from easyvoyage_mcp.tools.admin_reservations import admin_reservations_liste, admin_reservation_detail
from easyvoyage_mcp.tools.admin_clients      import admin_clients_liste, admin_client_detail
from easyvoyage_mcp.tools.admin_partenaires  import (
    admin_partenaires_liste,
    admin_partenaire_detail,
    admin_partenaires_demandes,
)
from easyvoyage_mcp.tools.admin_promotions   import admin_promotions_liste
from easyvoyage_mcp.tools.admin_finances     import admin_finances_dashboard, admin_finances_commissions
from easyvoyage_mcp.tools.admin_factures     import admin_factures_liste
from easyvoyage_mcp.tools.admin_marketing    import admin_marketing_liste, admin_catalogue_liste
from easyvoyage_mcp.tools.admin_support      import admin_support_conversations, admin_support_messages
from easyvoyage_mcp.tools.admin_fiscal       import admin_fiscal_regles
from easyvoyage_mcp.tools.admin_search       import admin_recherche_globale
from easyvoyage_mcp.tools.admin_reports_pdf  import admin_rapport_pdf

mcp = FastMCP("easyvoyage-admin-mcp")

mcp.tool()(admin_dashboard_kpis)
mcp.tool()(admin_hotels_liste)
mcp.tool()(admin_hotel_detail)
mcp.tool()(admin_hotels_avis)
mcp.tool()(admin_reservations_liste)
mcp.tool()(admin_reservation_detail)
mcp.tool()(admin_clients_liste)
mcp.tool()(admin_client_detail)
mcp.tool()(admin_partenaires_liste)
mcp.tool()(admin_partenaire_detail)
mcp.tool()(admin_partenaires_demandes)
mcp.tool()(admin_promotions_liste)
mcp.tool()(admin_finances_dashboard)
mcp.tool()(admin_finances_commissions)
mcp.tool()(admin_factures_liste)
mcp.tool()(admin_marketing_liste)
mcp.tool()(admin_catalogue_liste)
mcp.tool()(admin_support_conversations)
mcp.tool()(admin_support_messages)
mcp.tool()(admin_fiscal_regles)
mcp.tool()(admin_recherche_globale)
mcp.tool()(admin_rapport_pdf)


if __name__ == "__main__":
    mcp.run()