"""
mcp/tools/admin_partenaires.py — recherche par EMAIL (jamais par ID)
"""
import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les partenaires. Filtres : search (nom/email/entreprise), actif (bool), limit (defaut 50)."
))
def admin_partenaires_liste(search: str=None, actif: bool=None, limit: int=50) -> str:
    try:
        w = ["u.role='PARTENAIRE'"]
        p = []
        if search:
            w.append("(u.nom ILIKE %s OR u.prenom ILIKE %s OR u.email ILIKE %s OR p.nom_entreprise ILIKE %s)")
            p += [f"%{search}%"]*4
        if actif is not None:
            w.append("u.actif=%s"); p.append(actif)
        p.append(limit)

        rows = db_fetch(f"""
            SELECT u.nom, u.prenom, u.email, u.telephone, u.actif,
                p.nom_entreprise, p.type_partenaire, p.statut,
                p.commission AS taux_commission,
                COUNT(DISTINCT h.id) AS nb_hotels
            FROM utilisateur u
            JOIN partenaire p ON p.id=u.id
            LEFT JOIN hotel h ON h.id_partenaire=u.id
            WHERE {' AND '.join(w)}
            GROUP BY u.id, p.nom_entreprise, p.type_partenaire, p.statut, p.commission
            ORDER BY u.nom LIMIT %s
        """, *p)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Profil complet d'un partenaire par son EMAIL (jamais par ID). "
    "Parametre : email (str) — adresse email du partenaire."
))
def admin_partenaire_detail(email: str) -> str:
    try:
        partenaire = db_fetchrow("""
            SELECT u.nom, u.prenom, u.email, u.telephone, u.actif,
                p.nom_entreprise, p.type_partenaire, p.statut,
                p.iban, p.adresse_entreprise, p.commission AS taux_commission,
                u.id AS _uid
            FROM utilisateur u
            JOIN partenaire p ON p.id=u.id
            WHERE u.email ILIKE %s AND u.role='PARTENAIRE' LIMIT 1
        """, f"%{email}%")

        if not partenaire:
            return json.dumps({"ok": False, "error": f"Aucun partenaire trouvé avec l'email '{email}'"})

        uid = partenaire.pop("_uid")

        hotels = db_fetch("""
            SELECT h.nom, h.ville, h.etoiles, h.actif,
                (SELECT COUNT(*) FROM chambre c WHERE c.id_hotel=h.id) AS nb_chambres,
                COALESCE(ca_c.nb,0)+COALESCE(ca_v.nb,0) AS nb_reservations,
                COALESCE(ca_c.ca,0)+COALESCE(ca_v.ca,0) AS ca_total
            FROM hotel h
            LEFT JOIN (
                SELECT ch.id_hotel, COUNT(DISTINCT r.id) AS nb, COALESCE(SUM(r.total_ttc),0) AS ca
                FROM reservation r
                JOIN ligne_reservation_chambre lrc ON lrc.id_reservation=r.id
                JOIN chambre ch ON ch.id=lrc.id_chambre
                WHERE r.id_voyage IS NULL AND r.statut IN ('CONFIRMEE','TERMINEE')
                GROUP BY ch.id_hotel
            ) ca_c ON ca_c.id_hotel=h.id
            LEFT JOIN (
                SELECT ch.id_hotel, COUNT(DISTINCT rv.id) AS nb, COALESCE(SUM(rv.total_ttc),0) AS ca
                FROM reservation_visiteur rv JOIN chambre ch ON ch.id=rv.id_chambre
                WHERE rv.statut IN ('CONFIRMEE','TERMINEE')
                GROUP BY ch.id_hotel
            ) ca_v ON ca_v.id_hotel=h.id
            WHERE h.id_partenaire=%s ORDER BY h.nom
        """, uid)

        commissions = db_fetchrow("""
            SELECT COALESCE(SUM(montant_commission),0)                           AS total_commissions,
                COALESCE(SUM(CASE WHEN statut_commission='EN_ATTENTE'
                    THEN montant_commission END),0)                              AS solde_en_attente,
                COALESCE(SUM(CASE WHEN statut_commission='PAYEE'
                    THEN montant_commission END),0)                              AS total_paye,
                COUNT(*)                                                          AS nb_commissions
            FROM commission_partenaire WHERE id_partenaire=%s
        """, uid)

        paiements = db_fetch("""
            SELECT pp.montant, pp.note, pp.created_at,
                ua.nom||' '||ua.prenom AS admin_nom
            FROM paiement_partenaire pp
            LEFT JOIN utilisateur ua ON ua.id=pp.id_admin
            WHERE pp.id_partenaire=%s ORDER BY pp.created_at DESC LIMIT 10
        """, uid)

        return json.dumps({"ok": True, "partenaire": partenaire, "hotels": hotels,
                           "commissions": commissions, "paiements_recents": paiements},
                          default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Demandes d'inscription partenaire. "
    "Filtres : statut (EN_ATTENTE|APPROUVEE|REFUSEE), limit (defaut 50)."
))
def admin_partenaires_demandes(statut: str=None, limit: int=50) -> str:
    try:
        w, p = [], []
        if statut: w.append("statut=%s"); p.append(statut)
        where_sql = ("WHERE "+" AND ".join(w)) if w else ""
        p.append(limit)
        rows = db_fetch(f"""
            SELECT nom, prenom, email, telephone, nom_entreprise,
                type_partenaire, statut, message, created_at
            FROM demande_partenaire
            {where_sql} ORDER BY created_at DESC LIMIT %s
        """, *p)
        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)