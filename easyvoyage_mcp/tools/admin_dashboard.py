"""
mcp/tools/admin_dashboard.py
=============================
Reproduit EXACTEMENT la logique du backend FastAPI :
  app/services/finances/service.py  → get_dashboard()
  app/services/finances/repository.py → fetch_revenus_bruts()
  app/services/finances/utils.py    → calc_commission_agence()

RÈGLES MÉTIER (copiées depuis le backend) :
  reservation        : clients enregistrés
    id_voyage IS NULL     → hôtel  (commission 10%)
    id_voyage IS NOT NULL → voyage (pas de commission)
    date de ref : date_reservation  (timestamp with time zone)

  reservation_visiteur : visiteurs sans compte
    100% hôtel (commission 10%)
    date de ref : created_at  (PAS date_reservation — colonne inexistante)

  Statuts valides : CONFIRMEE + TERMINEE
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")

TAUX_COMMISSION = 10.0


@mcp.tool(description=(
    "KPIs globaux de la plateforme EasyVoyage — tableau de bord admin. "
    "Retourne : nb hotels/clients/partenaires, nb reservations par type, "
    "CA hotel clients, CA voyage clients, CA hotel visiteurs, CA total, "
    "commission agence 10% sur hotels, part partenaires 90%, "
    "promotions/support/marketing, evolution mensuelle 12 mois."
))
def admin_dashboard_kpis() -> str:
    try:
        stats = db_fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM hotel WHERE actif = true)                        AS nb_hotels_actifs,
                (SELECT COUNT(*) FROM hotel)                                            AS nb_hotels_total,
                (SELECT COUNT(*) FROM utilisateur WHERE role='CLIENT' AND actif=true)  AS nb_clients_actifs,
                (SELECT COUNT(*) FROM utilisateur WHERE role='CLIENT')                 AS nb_clients_total,
                (SELECT COUNT(*) FROM utilisateur WHERE role='PARTENAIRE' AND actif=true) AS nb_partenaires_actifs,

                (SELECT COUNT(*) FROM reservation
                 WHERE id_voyage IS NULL AND statut IN ('CONFIRMEE','TERMINEE'))       AS nb_resa_hotel_clients,
                (SELECT COUNT(*) FROM reservation
                 WHERE id_voyage IS NOT NULL AND statut IN ('CONFIRMEE','TERMINEE'))   AS nb_resa_voyage_clients,
                (SELECT COUNT(*) FROM reservation_visiteur
                 WHERE statut IN ('CONFIRMEE','TERMINEE'))                             AS nb_resa_hotel_visiteurs,

                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation
                 WHERE id_voyage IS NULL AND statut IN ('CONFIRMEE','TERMINEE'))       AS ca_hotel_clients,
                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation
                 WHERE id_voyage IS NOT NULL AND statut IN ('CONFIRMEE','TERMINEE'))   AS ca_voyage_clients,
                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation_visiteur
                 WHERE statut IN ('CONFIRMEE','TERMINEE'))                             AS ca_hotel_visiteurs,

                (SELECT COUNT(*) FROM promotion WHERE statut='PENDING')                AS nb_promos_en_attente,
                (SELECT COUNT(*) FROM promotion WHERE statut='APPROVED' AND actif=true
                 AND date_fin >= CURRENT_DATE)                                         AS nb_promos_actives,
                (SELECT COUNT(*) FROM support_conversation WHERE statut='EN_ATTENTE')  AS nb_supports_ouverts,
                (SELECT COUNT(*) FROM support_conversation WHERE statut='ACCEPTEE')    AS nb_supports_en_cours,
                (SELECT COUNT(*) FROM marketing WHERE statut='ACTIVE')                 AS nb_campagnes_actives,
                (SELECT COUNT(*) FROM catalogue WHERE statut='EN_COURS')               AS nb_catalogues_en_cours
        """)

        ca_hotel_clients   = float(stats.get("ca_hotel_clients")   or 0)
        ca_voyage_clients  = float(stats.get("ca_voyage_clients")  or 0)
        ca_hotel_visiteurs = float(stats.get("ca_hotel_visiteurs") or 0)
        ca_hotel_total     = round(ca_hotel_clients + ca_hotel_visiteurs, 2)
        ca_total           = round(ca_hotel_total + ca_voyage_clients, 2)
        commission_agence  = round(ca_hotel_total * TAUX_COMMISSION / 100, 2)
        part_partenaires   = round(ca_hotel_total - commission_agence, 2)

        stats["ca_hotel_total"]      = ca_hotel_total
        stats["ca_voyage_total"]     = round(ca_voyage_clients, 2)
        stats["ca_total"]            = ca_total
        stats["commission_agence"]   = commission_agence
        stats["part_partenaires"]    = part_partenaires
        stats["taux_commission_pct"] = TAUX_COMMISSION
        stats["nb_resa_total"] = (
            int(stats.get("nb_resa_hotel_clients")   or 0) +
            int(stats.get("nb_resa_voyage_clients")  or 0) +
            int(stats.get("nb_resa_hotel_visiteurs") or 0)
        )

        # Evolution mensuelle — visiteurs utilisent created_at (pas date_reservation)
        evolution = db_fetch("""
            SELECT
                mois,
                SUM(n_hc) AS nb_hotel_clients,
                SUM(n_vc) AS nb_voyage_clients,
                SUM(n_hv) AS nb_hotel_visiteurs,
                SUM(n_hc)+SUM(n_vc)+SUM(n_hv) AS nb_total,
                SUM(c_hc) AS ca_hotel_clients,
                SUM(c_vc) AS ca_voyage_clients,
                SUM(c_hv) AS ca_hotel_visiteurs,
                SUM(c_hc)+SUM(c_vc)+SUM(c_hv) AS ca_total,
                ROUND((SUM(c_hc)+SUM(c_hv))*10.0/100,2) AS commission_agence
            FROM (
                SELECT TO_CHAR(date_reservation,'YYYY-MM') AS mois,
                    COUNT(*) AS n_hc, 0 AS n_vc, 0 AS n_hv,
                    COALESCE(SUM(total_ttc),0) AS c_hc, 0 AS c_vc, 0 AS c_hv
                FROM reservation
                WHERE id_voyage IS NULL AND statut IN ('CONFIRMEE','TERMINEE')
                  AND date_reservation >= NOW()-INTERVAL '12 months'
                GROUP BY TO_CHAR(date_reservation,'YYYY-MM')
                UNION ALL
                SELECT TO_CHAR(date_reservation,'YYYY-MM'),
                    0, COUNT(*), 0,
                    0, COALESCE(SUM(total_ttc),0), 0
                FROM reservation
                WHERE id_voyage IS NOT NULL AND statut IN ('CONFIRMEE','TERMINEE')
                  AND date_reservation >= NOW()-INTERVAL '12 months'
                GROUP BY TO_CHAR(date_reservation,'YYYY-MM')
                UNION ALL
                SELECT TO_CHAR(created_at,'YYYY-MM'),
                    0, 0, COUNT(*),
                    0, 0, COALESCE(SUM(total_ttc),0)
                FROM reservation_visiteur
                WHERE statut IN ('CONFIRMEE','TERMINEE')
                  AND created_at >= NOW()-INTERVAL '12 months'
                GROUP BY TO_CHAR(created_at,'YYYY-MM')
            ) x
            GROUP BY mois ORDER BY mois DESC
        """)

        return json.dumps({
            "ok": True, "kpis": stats, "evolution_mensuelle": evolution
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)