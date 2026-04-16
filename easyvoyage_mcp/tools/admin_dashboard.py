"""
mcp/tools/admin_dashboard.py
=============================
Tools MCP — Tableau de bord admin.
Correspond à : AdminDashboard.jsx

Tools :
  admin_dashboard_kpis  → KPIs globaux + évolution mensuelle 12 mois
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "KPIs globaux de la plateforme — tableau de bord admin (AdminDashboard). "
    "Retourne : nb hôtels actifs/total, nb clients inscrits/actifs, "
    "nb partenaires actifs, nb réservations clients + visiteurs, "
    "nb confirmées, CA clients, CA visiteurs, CA total, "
    "nb promotions en attente/actives, nb supports ouverts/en cours, "
    "nb campagnes actives, nb catalogues en cours, "
    "évolution mensuelle sur 12 mois."
))
def admin_dashboard_kpis() -> str:
    try:
        stats = db_fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM hotel WHERE actif = true)                               AS nb_hotels_actifs,
                (SELECT COUNT(*) FROM hotel)                                                   AS nb_hotels_total,
                (SELECT COUNT(*) FROM utilisateur WHERE role='CLIENT' AND actif=true)          AS nb_clients_actifs,
                (SELECT COUNT(*) FROM utilisateur WHERE role='CLIENT')                         AS nb_clients_total,
                (SELECT COUNT(*) FROM utilisateur WHERE role='PARTENAIRE' AND actif=true)      AS nb_partenaires_actifs,
                (SELECT COUNT(*) FROM reservation)                                             AS nb_reservations_clients,
                (SELECT COUNT(*) FROM reservation_visiteur)                                    AS nb_reservations_visiteurs,
                (SELECT COUNT(*) FROM reservation WHERE statut='CONFIRMEE')                    AS nb_reservations_confirmees,
                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation WHERE statut='CONFIRMEE')          AS ca_clients,
                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation_visiteur WHERE statut='CONFIRMEE') AS ca_visiteurs,
                (SELECT COUNT(*) FROM promotion WHERE statut='PENDING')                        AS nb_promos_en_attente,
                (SELECT COUNT(*) FROM promotion WHERE statut='APPROVED' AND actif=true AND date_fin >= CURRENT_DATE) AS nb_promos_actives,
                (SELECT COUNT(*) FROM support_conversation WHERE statut='EN_ATTENTE')          AS nb_supports_ouverts,
                (SELECT COUNT(*) FROM support_conversation WHERE statut='ACCEPTEE')            AS nb_supports_en_cours,
                (SELECT COUNT(*) FROM marketing WHERE statut='ACTIVE')                         AS nb_campagnes_actives,
                (SELECT COUNT(*) FROM catalogue WHERE statut='EN_COURS')                       AS nb_catalogues_en_cours
        """)

        evolution = db_fetch("""
            SELECT
                TO_CHAR(date_reservation, 'YYYY-MM') AS mois,
                COUNT(*)                             AS nb_reservations,
                COALESCE(SUM(total_ttc), 0)          AS ca
            FROM reservation
            WHERE date_reservation >= NOW() - INTERVAL '12 months'
            GROUP BY TO_CHAR(date_reservation, 'YYYY-MM')
            ORDER BY mois DESC
        """)

        ca_total = float(stats.get("ca_clients") or 0) + float(stats.get("ca_visiteurs") or 0)
        stats["ca_total"] = round(ca_total, 2)

        return json.dumps({
            "ok": True,
            "kpis": stats,
            "evolution_mensuelle": evolution,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)