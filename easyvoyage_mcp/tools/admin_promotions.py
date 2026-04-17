"""
mcp/tools/admin_promotions.py
==============================
Colonnes réelles vérifiées :
  promotion : id, titre, description, id_hotel, pourcentage,
              date_debut, date_fin, actif, statut (USER-DEFINED enum),
              id_partenaire, id_admin_validateur, raison_refus, date_decision

Statuts réels en base : APPROVED | REJECTED | PENDING
IMPORTANT : statut est un type enum PostgreSQL → utiliser CAST(statut AS VARCHAR)
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister toutes les promotions — page AdminPromotions. "
    "Filtres : statut ('PENDING'|'APPROVED'|'REJECTED'), "
    "hotel_nom (nom partiel), partenaire_email, actif (bool), "
    "search (titre), limit (defaut 50). "
    "Retourne : titre, pourcentage, statut, actif, date_debut, date_fin, "
    "hotel_nom, hotel_ville, partenaire_nom, partenaire_email, "
    "raison_refus, date_decision. "
    "Trie : PENDING d'abord, puis APPROVED, puis REJECTED."
))
def admin_promotions_liste(
    statut:           str  = None,
    hotel_nom:        str  = None,
    partenaire_email: str  = None,
    actif:            bool = None,
    search:           str  = None,
    limit:            int  = 50,
    hotel_id:         int  = None,
    partenaire_id:    int  = None,
) -> str:
    try:
        w, p = [], []

        # CAST obligatoire car statut est un type enum PostgreSQL
        if statut:
            w.append("CAST(p.statut AS VARCHAR) = %s")
            p.append(statut)
        if hotel_nom:
            w.append("h.nom ILIKE %s")
            p.append(f"%{hotel_nom}%")
        if hotel_id:
            w.append("p.id_hotel = %s")
            p.append(hotel_id)
        if partenaire_email:
            w.append("u.email ILIKE %s")
            p.append(f"%{partenaire_email}%")
        if partenaire_id:
            w.append("p.id_partenaire = %s")
            p.append(partenaire_id)
        if actif is not None:
            w.append("p.actif = %s")
            p.append(actif)
        if search:
            w.append("p.titre ILIKE %s")
            p.append(f"%{search}%")

        where_sql = ("WHERE " + " AND ".join(w)) if w else ""
        p.append(limit)

        rows = db_fetch(f"""
            SELECT
                p.titre,
                p.description,
                p.pourcentage,
                CAST(p.statut AS VARCHAR)  AS statut,
                p.actif,
                p.date_debut,
                p.date_fin,
                p.raison_refus,
                p.date_decision,
                p.created_at,
                h.nom                      AS hotel_nom,
                h.ville                    AS hotel_ville,
                u.nom||' '||u.prenom       AS partenaire_nom,
                u.email                    AS partenaire_email,
                ua.nom||' '||ua.prenom     AS admin_validateur
            FROM promotion p
            LEFT JOIN hotel h       ON h.id  = p.id_hotel
            LEFT JOIN utilisateur u  ON u.id  = p.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id = p.id_admin_validateur
            {where_sql}
            ORDER BY
                CASE CAST(p.statut AS VARCHAR)
                    WHEN 'PENDING'  THEN 0
                    WHEN 'APPROVED' THEN 1
                    ELSE 2
                END,
                p.created_at DESC
            LIMIT %s
        """, *p)

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