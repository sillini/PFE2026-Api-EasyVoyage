"""
mcp/tools/admin_promotions.py
==============================
Tools MCP — Validation des promotions.
Correspond à : AdminPromotions.jsx

Tools :
  admin_promotions_liste → toutes les promos avec filtres, triées PENDING en premier
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister toutes les promotions — page AdminPromotions. "
    "Filtres : statut ('PENDING'|'APPROVED'|'REJECTED'), hotel_id (int), "
    "partenaire_id (int), actif (bool), search (titre), limit (int, défaut 50). "
    "Retourne : id, titre, description, pourcentage, statut, actif, "
    "date_debut, date_fin, raison_refus, date_decision, created_at, "
    "hotel_id, hotel_nom, hotel_ville, partenaire_id, partenaire_nom, "
    "partenaire_email, admin_validateur. "
    "Trié : PENDING d'abord, puis APPROVED, puis REJECTED."
))
def admin_promotions_liste(
    statut:        str  = None,
    hotel_id:      int  = None,
    partenaire_id: int  = None,
    actif:         bool = None,
    search:        str  = None,
    limit:         int  = 50,
) -> str:
    try:
        wheres, params = [], []
        if statut:
            wheres.append("p.statut = %s"); params.append(statut)
        if hotel_id:
            wheres.append("p.id_hotel = %s"); params.append(hotel_id)
        if partenaire_id:
            wheres.append("p.id_partenaire = %s"); params.append(partenaire_id)
        if actif is not None:
            wheres.append("p.actif = %s"); params.append(actif)
        if search:
            wheres.append("p.titre ILIKE %s"); params.append(f"%{search}%")
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                p.id, p.titre, p.description, p.pourcentage,
                p.statut, p.actif,
                p.date_debut, p.date_fin,
                p.raison_refus, p.date_decision, p.created_at,
                h.id   AS hotel_id,
                h.nom  AS hotel_nom,
                h.ville AS hotel_ville,
                u.id   AS partenaire_id,
                u.nom || ' ' || u.prenom AS partenaire_nom,
                u.email                  AS partenaire_email,
                ua.nom || ' ' || ua.prenom AS admin_validateur
            FROM promotion p
            LEFT JOIN hotel h       ON h.id = p.id_hotel
            LEFT JOIN utilisateur u  ON u.id = p.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id = p.id_admin_validateur
            {where_sql}
            ORDER BY
                CASE p.statut
                    WHEN 'PENDING'  THEN 0
                    WHEN 'APPROVED' THEN 1
                    ELSE 2
                END,
                p.created_at DESC
            LIMIT %s
        """, *params)

        nb_pending  = sum(1 for r in rows if r.get("statut") == "PENDING")
        nb_approved = sum(1 for r in rows if r.get("statut") == "APPROVED")
        nb_rejected = sum(1 for r in rows if r.get("statut") == "REJECTED")

        return json.dumps({
            "ok":          True,
            "total":       len(rows),
            "nb_pending":  nb_pending,
            "nb_approved": nb_approved,
            "nb_rejected": nb_rejected,
            "data":        rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)