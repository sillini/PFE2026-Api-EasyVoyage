"""
mcp/tools/admin_marketing.py
=============================
Tools MCP — Marketing et catalogues email.
Correspond à : AdminMarketing.jsx + AdminCatalogue.jsx

Tools :
  admin_marketing_liste   → campagnes marketing avec filtres
  admin_catalogue_liste   → catalogues email avec filtres
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les campagnes marketing — page AdminMarketing. "
    "Filtres : statut ('DRAFT'|'ACTIVE'|'EXPIRED'|'REJECTED'|'DISABLED'), "
    "type ('hotel'|'voyage'|'promotion'|'offre'), "
    "search (titre ou message), limit (int, défaut 50). "
    "Retourne : id, titre, message, statut, type, hashtags, cta, image_url, "
    "date_debut, date_fin, created_at, partenaire_nom, hotel_nom."
))
def admin_marketing_liste(
    statut: str = None,
    type:   str = None,
    search: str = None,
    limit:  int = 50,
) -> str:
    try:
        wheres, params = [], []
        if statut:
            wheres.append("m.statut = %s"); params.append(statut)
        if type:
            wheres.append("m.type = %s"); params.append(type)
        if search:
            wheres.append("(m.titre ILIKE %s OR m.message ILIKE %s)")
            params += [f"%{search}%"] * 2
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                m.id, m.titre, m.message, m.statut, m.type,
                m.hashtags, m.cta, m.image_url,
                m.date_debut, m.date_fin, m.created_at,
                u.nom || ' ' || u.prenom AS partenaire_nom,
                u.email                  AS partenaire_email,
                h.nom                    AS hotel_nom
            FROM marketing m
            LEFT JOIN utilisateur u ON u.id = m.id_partenaire
            LEFT JOIN hotel h       ON h.id = m.id_hotel
            {where_sql}
            ORDER BY m.created_at DESC
            LIMIT %s
        """, *params)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Lister les catalogues email — page AdminCatalogue. "
    "Filtres : statut ('BROUILLON'|'PLANIFIE'|'EN_COURS'|'ENVOYE'|'ECHOUE'), "
    "search (titre), limit (int, défaut 30). "
    "Retourne : id, titre, statut, description, nb_contacts_envoye, "
    "nb_ouverts, scheduled_at, sent_at, created_at, cree_par (admin)."
))
def admin_catalogue_liste(
    statut: str = None,
    search: str = None,
    limit:  int = 30,
) -> str:
    try:
        wheres, params = [], []
        if statut:
            wheres.append("c.statut = %s"); params.append(statut)
        if search:
            wheres.append("c.titre ILIKE %s"); params.append(f"%{search}%")
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                c.id, c.titre, c.statut, c.description,
                c.nb_contacts_envoye, c.nb_ouverts,
                c.scheduled_at, c.sent_at, c.created_at,
                ua.nom || ' ' || ua.prenom AS cree_par
            FROM catalogue c
            LEFT JOIN utilisateur ua ON ua.id = c.id_admin
            {where_sql}
            ORDER BY c.created_at DESC
            LIMIT %s
        """, *params)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)