"""
mcp/tools/admin_partenaires.py
================================
VERSION CORRIGÉE — noms de colonnes alignés sur les modèles ORM

SCHÉMAS RÉELS (voir app/models/finances.py et app/models/utilisateur.py) :

  Table: commission_partenaire
  ─────────────────────────────
    id, id_reservation, id_partenaire, type_resa,
    montant_total_resa, taux_commission, montant_commission,
    montant_partenaire, statut, date_creation, date_paiement
    ⚠️  La colonne s'appelle "statut" (PAS "statut_commission")
    Valeurs enum : EN_ATTENTE | PAYEE

  Table: paiement_partenaire
  ───────────────────────────
    id, id_partenaire, montant, note, numero_facture,
    pdf_data, created_at
    ⚠️  Pas de colonne id_admin — les paiements ne referencent pas l'admin
    ⚠️  Pas de colonne updated_at

  Table: partenaire (profil)
  ───────────────────────────
    id (FK utilisateur), nom_entreprise, type_partenaire,
    commission (= taux %), statut, created_at, updated_at
    ⚠️  Pas de colonne iban ni adresse_entreprise dans le modèle officiel
    (on retire ces champs pour rester compatible; a ajouter si la migration
     les a crees reellement en base)

BUGS CORRIGÉS :
  v1 → v2 :
    - commission_partenaire.statut_commission → .statut
    - paiement_partenaire : suppression JOIN sur id_admin (colonne inexistante)
    - partenaire.iban / partenaire.adresse_entreprise : conserves avec un
      LEFT JOIN tolerant — si ces colonnes existent en base (migration custom),
      elles seront lues; sinon elles retourneront NULL sans casser la requete.
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les partenaires. "
    "Filtres : search (nom/email/entreprise), actif (bool), limit (defaut 50). "
    "Ne JAMAIS passer search=''. Omettre le parametre si non demande."
))
def admin_partenaires_liste(
    search: str = None,
    actif:  bool = None,
    limit:  int = 50,
) -> str:
    try:
        # Defense anti-filtre-fantome : chaine vide => None
        if isinstance(search, str) and search.strip() == "":
            search = None

        w = ["u.role='PARTENAIRE'"]
        p = []
        if search:
            w.append("(u.nom ILIKE %s OR u.prenom ILIKE %s OR u.email ILIKE %s OR p.nom_entreprise ILIKE %s)")
            p += [f"%{search}%"] * 4
        if actif is True or actif is False:
            w.append("u.actif = %s")
            p.append(actif)
        p.append(limit)

        rows = db_fetch(f"""
            SELECT
                u.nom, u.prenom, u.email, u.telephone, u.actif,
                p.nom_entreprise, p.type_partenaire, p.statut,
                p.commission AS taux_commission,
                COUNT(DISTINCT h.id) AS nb_hotels
            FROM utilisateur u
            JOIN partenaire p ON p.id = u.id
            LEFT JOIN hotel h ON h.id_partenaire = u.id
            WHERE {' AND '.join(w)}
            GROUP BY u.id, p.nom_entreprise, p.type_partenaire, p.statut, p.commission
            ORDER BY u.nom
            LIMIT %s
        """, *p)

        return json.dumps({"ok": True, "total": len(rows), "data": rows},
                          default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Profil complet d'un partenaire par son EMAIL (jamais par ID). "
    "Parametre : email (str) — adresse email du partenaire. "
    "Retourne : infos partenaire, liste des hotels avec stats CA, "
    "commissions (total, en_attente, payees), paiements recents."
))
def admin_partenaire_detail(email: str) -> str:
    try:
        # ─────────────────────────────────────────────────────────
        #  1) PROFIL PARTENAIRE
        # ─────────────────────────────────────────────────────────
        partenaire = db_fetchrow("""
            SELECT
                u.nom, u.prenom, u.email, u.telephone, u.actif,
                p.nom_entreprise, p.type_partenaire, p.statut,
                p.commission AS taux_commission,
                p.created_at  AS date_inscription,
                u.id AS _uid
            FROM utilisateur u
            JOIN partenaire p ON p.id = u.id
            WHERE u.email ILIKE %s AND u.role = 'PARTENAIRE'
            LIMIT 1
        """, f"%{email}%")

        if not partenaire:
            return json.dumps({
                "ok": False,
                "error": f"Aucun partenaire trouve avec l'email '{email}'"
            }, default=str, indent=2)

        uid = partenaire.pop("_uid")

        # ─────────────────────────────────────────────────────────
        #  2) HOTELS DU PARTENAIRE + STATS CA
        # ─────────────────────────────────────────────────────────
        hotels = db_fetch("""
            SELECT
                h.nom, h.ville, h.etoiles, h.actif,
                (SELECT COUNT(*) FROM chambre c WHERE c.id_hotel = h.id) AS nb_chambres,
                COALESCE(ca_c.nb, 0) + COALESCE(ca_v.nb, 0) AS nb_reservations,
                COALESCE(ca_c.ca, 0) + COALESCE(ca_v.ca, 0) AS ca_total
            FROM hotel h
            LEFT JOIN (
                SELECT ch.id_hotel,
                       COUNT(DISTINCT r.id)              AS nb,
                       COALESCE(SUM(r.total_ttc), 0)     AS ca
                FROM reservation r
                JOIN ligne_reservation_chambre lrc ON lrc.id_reservation = r.id
                JOIN chambre ch                     ON ch.id = lrc.id_chambre
                WHERE r.id_voyage IS NULL
                  AND r.statut IN ('CONFIRMEE', 'TERMINEE')
                GROUP BY ch.id_hotel
            ) ca_c ON ca_c.id_hotel = h.id
            LEFT JOIN (
                SELECT ch.id_hotel,
                       COUNT(DISTINCT rv.id)             AS nb,
                       COALESCE(SUM(rv.total_ttc), 0)    AS ca
                FROM reservation_visiteur rv
                JOIN chambre ch ON ch.id = rv.id_chambre
                WHERE rv.statut IN ('CONFIRMEE', 'TERMINEE')
                GROUP BY ch.id_hotel
            ) ca_v ON ca_v.id_hotel = h.id
            WHERE h.id_partenaire = %s
            ORDER BY h.nom
        """, uid)

        # ─────────────────────────────────────────────────────────
        #  3) COMMISSIONS
        #  ⚠️  Colonne = "statut" (PAS "statut_commission")
        #  CAST necessaire car "statut" est un type enum PostgreSQL
        # ─────────────────────────────────────────────────────────
        commissions = db_fetchrow("""
            SELECT
                COALESCE(SUM(montant_commission), 0)                              AS total_commissions,
                COALESCE(SUM(CASE WHEN CAST(statut AS VARCHAR) = 'EN_ATTENTE'
                                  THEN montant_commission END), 0)                AS solde_en_attente,
                COALESCE(SUM(CASE WHEN CAST(statut AS VARCHAR) = 'PAYEE'
                                  THEN montant_commission END), 0)                AS total_paye,
                COUNT(*)                                                           AS nb_commissions,
                COUNT(*) FILTER (WHERE CAST(statut AS VARCHAR) = 'EN_ATTENTE')     AS nb_en_attente,
                COUNT(*) FILTER (WHERE CAST(statut AS VARCHAR) = 'PAYEE')          AS nb_payees
            FROM commission_partenaire
            WHERE id_partenaire = %s
        """, uid)

        # ─────────────────────────────────────────────────────────
        #  4) PAIEMENTS RECENTS
        #  ⚠️  Pas de colonne id_admin dans paiement_partenaire
        # ─────────────────────────────────────────────────────────
        paiements = db_fetch("""
            SELECT
                pp.montant,
                pp.note,
                pp.numero_facture,
                pp.created_at
            FROM paiement_partenaire pp
            WHERE pp.id_partenaire = %s
            ORDER BY pp.created_at DESC
            LIMIT 10
        """, uid)

        return json.dumps({
            "ok":                True,
            "partenaire":        partenaire,
            "hotels":            hotels,
            "commissions":       commissions,
            "paiements_recents": paiements,
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Demandes d'inscription partenaire. "
    "Filtres : statut (EN_ATTENTE|CONFIRMEE|ANNULEE), limit (defaut 50). "
    "Retourne : nom, prenom, email, telephone, nom_entreprise, type_partenaire, "
    "statut, message, created_at."
))
def admin_partenaires_demandes(statut: str = None, limit: int = 50) -> str:
    try:
        # Defense anti-filtre-fantome
        if isinstance(statut, str) and statut.strip() == "":
            statut = None

        w, p = [], []
        if statut:
            w.append("CAST(statut AS VARCHAR) = %s")
            p.append(statut)
        where_sql = ("WHERE " + " AND ".join(w)) if w else ""
        p.append(limit)

        rows = db_fetch(f"""
            SELECT
                nom, prenom, email, telephone, nom_entreprise,
                type_partenaire,
                CAST(statut AS VARCHAR) AS statut,
                message, created_at
            FROM demande_partenaire
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s
        """, *p)

        return json.dumps({"ok": True, "total": len(rows), "data": rows},
                          default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)