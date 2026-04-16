"""
mcp/tools/admin_clients.py
===========================
Tools MCP — Gestion des clients.
Correspond à : AdminClients.jsx

Tools :
  admin_clients_liste   → liste paginée avec recherche et filtres
  admin_client_detail   → profil complet + historique réservations + stats
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les clients inscrits — page AdminClients. "
    "Filtres : search (nom/prénom/email/téléphone), actif (bool), limit (int, défaut 50). "
    "Retourne : id, nom, prénom, email, téléphone, actif, date_inscription, "
    "derniere_connexion, nb_reservations, total_dépensé, panier_moyen, derniere_reservation. "
    "Trié par total dépensé décroissant."
))
def admin_clients_liste(
    search: str  = None,
    actif:  bool = None,
    limit:  int  = 50,
) -> str:
    try:
        wheres = ["u.role = 'CLIENT'"]
        params = []
        if search:
            wheres.append(
                "(u.nom ILIKE %s OR u.prenom ILIKE %s "
                "OR u.email ILIKE %s OR u.telephone ILIKE %s)"
            )
            params += [f"%{search}%"] * 4
        if actif is not None:
            wheres.append("u.actif = %s"); params.append(actif)
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                u.id, u.nom, u.prenom, u.email, u.telephone,
                u.actif,
                u.created_at  AS date_inscription,
                u.last_login  AS derniere_connexion,
                COUNT(DISTINCT r.id)          AS nb_reservations,
                COALESCE(SUM(r.total_ttc), 0) AS total_depense,
                COALESCE(AVG(r.total_ttc), 0) AS panier_moyen,
                MAX(r.date_reservation)        AS derniere_reservation
            FROM utilisateur u
            LEFT JOIN reservation r ON r.id_client = u.id
            WHERE {' AND '.join(wheres)}
            GROUP BY u.id
            ORDER BY total_depense DESC
            LIMIT %s
        """, *params)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Profil complet d'un client par son ID. "
    "Retourne : infos personnelles, statistiques globales "
    "(nb réservations, total dépensé, panier moyen, nb confirmées/annulées), "
    "historique complet de toutes ses réservations (hotels + voyages) "
    "avec numéro facture et statut."
))
def admin_client_detail(client_id: int) -> str:
    try:
        client = db_fetchrow("""
            SELECT
                u.id, u.nom, u.prenom, u.email, u.telephone,
                u.actif,
                u.created_at  AS date_inscription,
                u.last_login  AS derniere_connexion
            FROM utilisateur u
            WHERE u.id = %s AND u.role = 'CLIENT'
        """, client_id)
        if not client:
            return json.dumps({"ok": False, "error": f"Client {client_id} introuvable"})

        stats = db_fetchrow("""
            SELECT
                COUNT(*)                                          AS nb_reservations,
                COALESCE(SUM(total_ttc), 0)                      AS total_depense,
                COALESCE(AVG(total_ttc), 0)                      AS panier_moyen,
                COUNT(CASE WHEN statut='CONFIRMEE' THEN 1 END)   AS nb_confirmees,
                COUNT(CASE WHEN statut='ANNULEE'   THEN 1 END)   AS nb_annulees,
                COUNT(CASE WHEN statut='TERMINEE'  THEN 1 END)   AS nb_terminees,
                MAX(date_reservation)                             AS derniere_reservation
            FROM reservation
            WHERE id_client = %s
        """, client_id)

        reservations = db_fetch("""
            SELECT
                r.id, r.statut, r.total_ttc,
                r.date_reservation, r.date_debut, r.date_fin,
                (r.date_fin - r.date_debut)                              AS nb_nuits,
                CASE WHEN r.id_voyage IS NOT NULL THEN 'voyage' ELSE 'hotel' END AS type_resa,
                f.numero  AS numero_facture,
                f.statut  AS statut_facture
            FROM reservation r
            LEFT JOIN facture f ON f.id_reservation = r.id
            WHERE r.id_client = %s
            ORDER BY r.date_reservation DESC
        """, client_id)

        return json.dumps({
            "ok":           True,
            "client":       client,
            "stats":        stats,
            "reservations": reservations,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)