"""
mcp/tools/admin_partenaires.py
================================
Tools MCP — Gestion des partenaires.
Correspond à : AdminPartenaires.jsx + AdminDemandesPartenaire.jsx

Tools :
  admin_partenaires_liste    → liste avec filtres + agrégats financiers
  admin_partenaire_detail    → profil complet + hôtels + commissions + paiements
  admin_partenaires_demandes → demandes d'inscription partenaire
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les partenaires — page AdminPartenaires. "
    "Filtres : search (nom/prénom/email/nom_entreprise), "
    "statut ('APPROUVE'|'EN_ATTENTE'|'REFUSE'), "
    "actif (bool), type_partenaire (str), limit (int, défaut 50). "
    "Retourne : id, nom, prénom, email, téléphone, actif, nom_entreprise, "
    "type_partenaire, statut, nb_hotels, total_commissions, solde_en_attente."
))
def admin_partenaires_liste(
    search:          str  = None,
    statut:          str  = None,
    actif:           bool = None,
    type_partenaire: str  = None,
    limit:           int  = 50,
) -> str:
    try:
        wheres = ["u.role = 'PARTENAIRE'"]
        params = []
        if search:
            wheres.append(
                "(u.nom ILIKE %s OR u.prenom ILIKE %s "
                "OR u.email ILIKE %s OR p.nom_entreprise ILIKE %s)"
            )
            params += [f"%{search}%"] * 4
        if statut:
            wheres.append("p.statut = %s"); params.append(statut)
        if actif is not None:
            wheres.append("u.actif = %s"); params.append(actif)
        if type_partenaire:
            wheres.append("p.type_partenaire = %s"); params.append(type_partenaire)
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                u.id, u.nom, u.prenom, u.email, u.telephone, u.actif,
                p.nom_entreprise, p.type_partenaire, p.statut,
                COUNT(DISTINCT h.id) AS nb_hotels,
                COALESCE(SUM(cp.montant_commission), 0) AS total_commissions,
                COALESCE(SUM(
                    CASE WHEN cp.statut_commission = 'EN_ATTENTE'
                    THEN cp.montant_commission END
                ), 0) AS solde_en_attente
            FROM utilisateur u
            JOIN partenaire p ON p.id = u.id
            LEFT JOIN hotel h                  ON h.id_partenaire = u.id
            LEFT JOIN commission_partenaire cp ON cp.id_partenaire = u.id
            WHERE {' AND '.join(wheres)}
            GROUP BY u.id, p.id
            ORDER BY u.nom
            LIMIT %s
        """, *params)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Détail complet d'un partenaire par son ID. "
    "Retourne : infos personnelles + entreprise (IBAN, adresse, taux commission), "
    "liste de ses hôtels avec nb_chambres, nb_reservations et CA par hôtel, "
    "récapitulatif commissions (total, solde en attente, total payé, nb total), "
    "10 derniers paiements admin → partenaire."
))
def admin_partenaire_detail(partenaire_id: int) -> str:
    try:
        partenaire = db_fetchrow("""
            SELECT
                u.id, u.nom, u.prenom, u.email, u.telephone, u.actif,
                p.nom_entreprise, p.type_partenaire, p.statut,
                p.iban, p.adresse_entreprise,
                p.commission AS taux_commission
            FROM utilisateur u
            JOIN partenaire p ON p.id = u.id
            WHERE u.id = %s
        """, partenaire_id)
        if not partenaire:
            return json.dumps({"ok": False, "error": f"Partenaire {partenaire_id} introuvable"})

        hotels = db_fetch("""
            SELECT
                h.id, h.nom, h.ville, h.pays, h.etoiles, h.actif,
                COUNT(DISTINCT c.id)               AS nb_chambres,
                COUNT(DISTINCT lrc.id_reservation) AS nb_reservations,
                COALESCE(SUM(DISTINCT r.total_ttc), 0) AS ca
            FROM hotel h
            LEFT JOIN chambre c                    ON c.id_hotel = h.id
            LEFT JOIN ligne_reservation_chambre lrc ON lrc.id_chambre = c.id
            LEFT JOIN reservation r                ON r.id = lrc.id_reservation
                                                   AND r.statut = 'CONFIRMEE'
            WHERE h.id_partenaire = %s
            GROUP BY h.id
            ORDER BY h.nom
        """, partenaire_id)

        commissions = db_fetchrow("""
            SELECT
                COALESCE(SUM(montant_commission), 0) AS total_commissions,
                COALESCE(SUM(CASE WHEN statut_commission='EN_ATTENTE'
                               THEN montant_commission END), 0)  AS solde_en_attente,
                COALESCE(SUM(CASE WHEN statut_commission='PAYEE'
                               THEN montant_commission END), 0)  AS total_paye,
                COUNT(*)                                          AS nb_commissions
            FROM commission_partenaire
            WHERE id_partenaire = %s
        """, partenaire_id)

        paiements_recents = db_fetch("""
            SELECT
                pp.id, pp.montant, pp.note, pp.created_at,
                ua.nom || ' ' || ua.prenom AS admin_nom
            FROM paiement_partenaire pp
            LEFT JOIN utilisateur ua ON ua.id = pp.id_admin
            WHERE pp.id_partenaire = %s
            ORDER BY pp.created_at DESC
            LIMIT 10
        """, partenaire_id)

        return json.dumps({
            "ok":                True,
            "partenaire":        partenaire,
            "hotels":            hotels,
            "commissions":       commissions,
            "paiements_recents": paiements_recents,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Lister les demandes d'inscription partenaire — page AdminDemandesPartenaire. "
    "Filtres : statut ('EN_ATTENTE'|'CONFIRMEE'|'ANNULEE'), "
    "search (nom/prénom/email/nom_entreprise), limit (int, défaut 50). "
    "Retourne : id, nom, prénom, email, téléphone, nom_entreprise, "
    "type_partenaire, statut, message, created_at."
))
def admin_partenaires_demandes(
    statut: str = None,
    search: str = None,
    limit:  int = 50,
) -> str:
    try:
        wheres, params = [], []
        if statut:
            wheres.append("d.statut = %s"); params.append(statut)
        if search:
            wheres.append(
                "(d.nom ILIKE %s OR d.prenom ILIKE %s "
                "OR d.email ILIKE %s OR d.nom_entreprise ILIKE %s)"
            )
            params += [f"%{search}%"] * 4
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                d.id, d.nom, d.prenom, d.email, d.telephone,
                d.nom_entreprise, d.type_partenaire,
                d.statut, d.message, d.created_at
            FROM demande_partenaire d
            {where_sql}
            ORDER BY
                CASE d.statut WHEN 'EN_ATTENTE' THEN 0 ELSE 1 END,
                d.created_at DESC
            LIMIT %s
        """, *params)

        nb_en_attente = sum(1 for r in rows if r.get("statut") == "EN_ATTENTE")

        return json.dumps({
            "ok":            True,
            "total":         len(rows),
            "nb_en_attente": nb_en_attente,
            "data":          rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)