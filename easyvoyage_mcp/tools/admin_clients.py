"""
mcp/tools/admin_clients.py — recherche par EMAIL (jamais par ID)
"""
import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les clients inscrits. "
    "Filtres : search (nom/prenom/email/telephone), actif (bool), limit (defaut 50)."
))
def admin_clients_liste(search: str=None, actif: bool=None, limit: int=50) -> str:
    try:
        w = ["u.role = 'CLIENT'"]
        p = []
        if search:
            w.append("(u.nom ILIKE %s OR u.prenom ILIKE %s OR u.email ILIKE %s OR u.telephone ILIKE %s)")
            p += [f"%{search}%"]*4
        if actif is not None:
            w.append("u.actif = %s"); p.append(actif)
        p.append(limit)

        rows = db_fetch(f"""
            SELECT u.nom, u.prenom, u.email, u.telephone, u.actif,
                u.date_inscription, u.derniere_connexion,
                COUNT(DISTINCT r.id)          AS nb_reservations,
                COALESCE(SUM(r.total_ttc), 0) AS total_depense,
                COALESCE(AVG(r.total_ttc), 0) AS panier_moyen,
                MAX(r.date_reservation)        AS derniere_reservation
            FROM utilisateur u
            LEFT JOIN reservation r ON r.id_client=u.id
            WHERE {' AND '.join(w)}
            GROUP BY u.id ORDER BY total_depense DESC LIMIT %s
        """, *p)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Profil complet d'un client par son EMAIL (jamais par ID). "
    "Parametre : email (str) — adresse email exacte ou partielle du client."
))
def admin_client_detail(email: str) -> str:
    try:
        client = db_fetchrow("""
            SELECT u.nom, u.prenom, u.email, u.telephone, u.actif,
                u.date_inscription, u.derniere_connexion, u.id AS _uid
            FROM utilisateur u
            WHERE u.email ILIKE %s AND u.role='CLIENT' LIMIT 1
        """, f"%{email}%")

        if not client:
            return json.dumps({"ok": False, "error": f"Aucun client trouvé avec l'email '{email}'"})

        uid = client.pop("_uid")

        stats = db_fetchrow("""
            SELECT COUNT(*) AS nb_reservations,
                COALESCE(SUM(total_ttc),0) AS total_depense,
                COALESCE(AVG(total_ttc),0) AS panier_moyen,
                COUNT(CASE WHEN statut='CONFIRMEE' THEN 1 END) AS nb_confirmees,
                COUNT(CASE WHEN statut='ANNULEE'   THEN 1 END) AS nb_annulees,
                COUNT(CASE WHEN statut='TERMINEE'  THEN 1 END) AS nb_terminees,
                MAX(date_reservation) AS derniere_reservation
            FROM reservation WHERE id_client=%s
        """, uid)

        reservations = db_fetch("""
            SELECT r.statut, r.total_ttc, r.date_reservation, r.date_debut, r.date_fin,
                (r.date_fin - r.date_debut) AS nb_nuits,
                CASE WHEN r.id_voyage IS NOT NULL THEN 'voyage' ELSE 'hotel' END AS type_resa,
                f.numero AS numero_facture, f.statut AS statut_facture
            FROM reservation r
            LEFT JOIN facture f ON f.id_reservation=r.id
            WHERE r.id_client=%s ORDER BY r.date_reservation DESC
        """, uid)

        return json.dumps({"ok": True, "client": client, "stats": stats,
                           "reservations": reservations}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)