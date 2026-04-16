"""
mcp/tools/admin_finances.py
=============================
Tools MCP — Finances et commissions.
Correspond à : AdminFinances.jsx

Tools :
  admin_finances_dashboard    → dashboard complet (CA, top hôtels, top partenaires, évolution)
  admin_finances_commissions  → liste des commissions avec filtres
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Dashboard financier complet — page AdminFinances. "
    "Retourne : CA clients, CA visiteurs, CA total, nb réservations, "
    "commissions (total/en_attente/payées/nb_en_attente), "
    "revenus mensuels 12 mois (hotel/voyage/total/nb_reservations), "
    "top 10 hôtels par CA (avec commission agence), "
    "top 10 partenaires par commissions (avec solde en attente)."
))
def admin_finances_dashboard() -> str:
    try:
        global_kpis = db_fetchrow("""
            SELECT
                (SELECT COALESCE(SUM(total_ttc),0)
                   FROM reservation WHERE statut='CONFIRMEE')          AS ca_clients,
                (SELECT COALESCE(SUM(total_ttc),0)
                   FROM reservation_visiteur WHERE statut='CONFIRMEE') AS ca_visiteurs,
                (SELECT COUNT(*) FROM reservation WHERE statut='CONFIRMEE')          AS nb_resa_clients,
                (SELECT COUNT(*) FROM reservation_visiteur WHERE statut='CONFIRMEE') AS nb_resa_visiteurs
        """)

        commissions = db_fetchrow("""
            SELECT
                COALESCE(SUM(montant_commission), 0) AS total,
                COALESCE(SUM(CASE WHEN statut_commission='EN_ATTENTE'
                    THEN montant_commission END), 0) AS en_attente,
                COALESCE(SUM(CASE WHEN statut_commission='PAYEE'
                    THEN montant_commission END), 0) AS payees,
                COUNT(*)                             AS nb_total,
                COUNT(CASE WHEN statut_commission='EN_ATTENTE' THEN 1 END) AS nb_en_attente
            FROM commission_partenaire
        """)

        revenus_mensuels = db_fetch("""
            SELECT
                TO_CHAR(date_reservation, 'YYYY-MM') AS periode,
                COALESCE(SUM(CASE WHEN id_voyage IS NULL     THEN total_ttc END), 0) AS revenu_hotel,
                COALESCE(SUM(CASE WHEN id_voyage IS NOT NULL THEN total_ttc END), 0) AS revenu_voyage,
                COALESCE(SUM(total_ttc), 0)           AS revenu_total,
                COUNT(*)                              AS nb_reservations
            FROM reservation
            WHERE statut = 'CONFIRMEE'
              AND date_reservation >= NOW() - INTERVAL '12 months'
            GROUP BY TO_CHAR(date_reservation, 'YYYY-MM')
            ORDER BY periode DESC
        """)

        top_hotels = db_fetch("""
            SELECT
                h.id, h.nom, h.ville, h.etoiles,
                COUNT(DISTINCT lrc.id_reservation)     AS nb_reservations,
                COALESCE(SUM(DISTINCT r.total_ttc), 0) AS ca,
                COALESCE(SUM(DISTINCT r.total_ttc) * 0.10, 0) AS commission_agence
            FROM hotel h
            LEFT JOIN chambre c                    ON c.id_hotel = h.id
            LEFT JOIN ligne_reservation_chambre lrc ON lrc.id_chambre = c.id
            LEFT JOIN reservation r                ON r.id = lrc.id_reservation
                                                   AND r.statut = 'CONFIRMEE'
            GROUP BY h.id
            ORDER BY ca DESC
            LIMIT 10
        """)

        top_partenaires = db_fetch("""
            SELECT
                u.id,
                u.nom || ' ' || u.prenom AS partenaire_nom,
                p.nom_entreprise,
                COUNT(DISTINCT h.id)                   AS nb_hotels,
                COALESCE(SUM(cp.montant_commission), 0) AS total_commissions,
                COALESCE(SUM(CASE WHEN cp.statut_commission='EN_ATTENTE'
                    THEN cp.montant_commission END), 0) AS solde_en_attente
            FROM utilisateur u
            JOIN partenaire p ON p.id = u.id
            LEFT JOIN hotel h                  ON h.id_partenaire = u.id
            LEFT JOIN commission_partenaire cp ON cp.id_partenaire = u.id
            WHERE u.role = 'PARTENAIRE'
            GROUP BY u.id, p.nom_entreprise
            ORDER BY total_commissions DESC
            LIMIT 10
        """)

        ca_total = float(global_kpis.get("ca_clients") or 0) + float(global_kpis.get("ca_visiteurs") or 0)
        global_kpis["ca_total"] = round(ca_total, 2)

        return json.dumps({
            "ok":               True,
            "global":           global_kpis,
            "commissions":      commissions,
            "revenus_mensuels": revenus_mensuels,
            "top_hotels":       top_hotels,
            "top_partenaires":  top_partenaires,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Lister les commissions partenaires avec filtres. "
    "Filtres : statut_commission ('EN_ATTENTE'|'PAYEE'), partenaire_id (int), "
    "date_debut (YYYY-MM-DD), date_fin (YYYY-MM-DD), limit (int, défaut 50). "
    "Retourne : id, montant_commission, statut_commission, created_at, "
    "partenaire_id, partenaire_nom, partenaire_email, nom_entreprise, "
    "reservation_id, reservation_ttc, reservation_statut. "
    "Retourne aussi montant_total de la sélection."
))
def admin_finances_commissions(
    statut_commission: str = None,
    partenaire_id:     int = None,
    date_debut:        str = None,
    date_fin:          str = None,
    limit:             int = 50,
) -> str:
    try:
        wheres, params = [], []
        if statut_commission:
            wheres.append("cp.statut_commission = %s"); params.append(statut_commission)
        if partenaire_id:
            wheres.append("cp.id_partenaire = %s"); params.append(partenaire_id)
        if date_debut:
            wheres.append("cp.created_at >= %s"); params.append(date_debut)
        if date_fin:
            wheres.append("cp.created_at <= %s"); params.append(date_fin)
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                cp.id, cp.montant_commission, cp.statut_commission, cp.created_at,
                u.id   AS partenaire_id,
                u.nom || ' ' || u.prenom AS partenaire_nom,
                u.email                  AS partenaire_email,
                p.nom_entreprise,
                r.id      AS reservation_id,
                r.total_ttc AS reservation_ttc,
                r.statut    AS reservation_statut
            FROM commission_partenaire cp
            JOIN utilisateur u ON u.id = cp.id_partenaire
            LEFT JOIN partenaire p ON p.id = u.id
            LEFT JOIN reservation r ON r.id = cp.id_reservation
            {where_sql}
            ORDER BY cp.created_at DESC
            LIMIT %s
        """, *params)

        montant_total = sum(float(r.get("montant_commission") or 0) for r in rows)

        return json.dumps({
            "ok":            True,
            "total":         len(rows),
            "montant_total": round(montant_total, 2),
            "data":          rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)