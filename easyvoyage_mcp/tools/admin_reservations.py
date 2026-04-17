"""
mcp/tools/admin_reservations.py
================================
VERSION CORRIGÉE v3 — tous les noms de colonnes alignés sur les modèles ORM

SCHEMAS REELS (voir app/models/reservation.py) :

  Table: facture
  ──────────────
    id, numero, date_emission, montant_total, montant_ht,
    taxe_sejour, tva_montant, taux_tva, droit_timbre,
    nb_nuits_taxables, statut, fichier_pdf, id_reservation,
    created_at, updated_at

  Table: ligne_reservation_chambre
  ─────────────────────────────────
    id_reservation, id_chambre, prix_unitaire, quantite,
    nb_adultes, nb_enfants, created_at, updated_at
    ⚠️  nb_nuits N'EXISTE PAS ici — il se CALCULE depuis reservation.date_*
    (via: (r.date_fin - r.date_debut) en jours)

  Table: ligne_reservation_visiteur
  ──────────────────────────────────
    id_reservation_visiteur, id_chambre, prix_unitaire,
    nb_adultes, nb_enfants, ...

BUGS CORRIGÉS :
  v1 → v2 : Colonnes facture renommées
      f.total_ht   → f.montant_ht
      f.tva        → f.tva_montant
      f.total_ttc  → f.montant_total

  v2 → v3 : Colonne inexistante dans ligne_reservation_chambre
      lrc.nb_nuits → SUPPRIMEE (calcul via date_fin - date_debut)
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les reservations — page AdminReservations. "
    "Filtres : statut (EN_ATTENTE|CONFIRMEE|ANNULEE|TERMINEE), "
    "source ('client' ou 'visiteur'), date_debut (YYYY-MM-DD), "
    "date_fin (YYYY-MM-DD), hotel_nom (str), client_search (str), "
    "limit (int, defaut 50)."
))
def admin_reservations_liste(
    statut:        str = None,
    source:        str = None,
    date_debut:    str = None,
    date_fin:      str = None,
    hotel_nom:     str = None,
    client_search: str = None,
    limit:         int = 50,
) -> str:
    try:
        results = []

        # ═════════════════════════════════════════════════════════
        #  RESERVATIONS CLIENTS
        # ═════════════════════════════════════════════════════════
        if source in (None, "", "client"):
            w, p = [], []
            if statut:        w.append("CAST(r.statut AS VARCHAR) = %s"); p.append(statut)
            if date_debut:    w.append("r.date_debut >= %s");             p.append(date_debut)
            if date_fin:      w.append("r.date_fin <= %s");               p.append(date_fin)
            if hotel_nom:
                w.append("""EXISTS (
                    SELECT 1 FROM ligne_reservation_chambre lrc
                    JOIN chambre c ON c.id = lrc.id_chambre
                    JOIN hotel   h ON h.id = c.id_hotel
                    WHERE lrc.id_reservation = r.id AND h.nom ILIKE %s
                )""")
                p.append(f"%{hotel_nom}%")
            if client_search:
                w.append("(u.nom ILIKE %s OR u.prenom ILIKE %s OR u.email ILIKE %s)")
                p += [f"%{client_search}%"] * 3

            where_sql = ("WHERE " + " AND ".join(w)) if w else ""
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    'client'                      AS source,
                    CAST(r.statut AS VARCHAR)     AS statut,
                    r.total_ttc,
                    r.date_reservation,
                    r.date_debut,
                    r.date_fin,
                    (r.date_fin - r.date_debut)   AS nb_nuits,
                    r.nb_adultes,
                    r.nb_enfants,
                    u.nom||' '||u.prenom          AS client_nom,
                    u.email                        AS client_email,
                    f.numero                       AS numero_facture,
                    CAST(f.statut AS VARCHAR)      AS statut_facture
                FROM reservation r
                JOIN utilisateur u ON u.id = r.id_client
                LEFT JOIN facture f ON f.id_reservation = r.id
                {where_sql}
                ORDER BY r.date_reservation DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        # ═════════════════════════════════════════════════════════
        #  RESERVATIONS VISITEURS
        # ═════════════════════════════════════════════════════════
        if source in (None, "", "visiteur"):
            w, p = [], []
            if statut:     w.append("CAST(rv.statut AS VARCHAR) = %s"); p.append(statut)
            if date_debut: w.append("rv.date_debut >= %s");             p.append(date_debut)
            if date_fin:   w.append("rv.date_fin <= %s");               p.append(date_fin)
            if hotel_nom:
                w.append("""EXISTS (
                    SELECT 1 FROM chambre c
                    JOIN hotel h ON h.id = c.id_hotel
                    WHERE c.id = rv.id_chambre AND h.nom ILIKE %s
                )""")
                p.append(f"%{hotel_nom}%")
            if client_search:
                w.append("(rv.nom ILIKE %s OR rv.prenom ILIKE %s OR rv.email ILIKE %s)")
                p += [f"%{client_search}%"] * 3

            where_sql = ("WHERE " + " AND ".join(w)) if w else ""
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    'visiteur'                    AS source,
                    CAST(rv.statut AS VARCHAR)    AS statut,
                    rv.total_ttc,
                    rv.created_at                 AS date_reservation,
                    rv.date_debut,
                    rv.date_fin,
                    (rv.date_fin - rv.date_debut) AS nb_nuits,
                    rv.nb_adultes,
                    rv.nb_enfants,
                    rv.nom||' '||rv.prenom        AS client_nom,
                    rv.email                      AS client_email,
                    rv.numero_voucher             AS numero_facture,
                    NULL                          AS statut_facture
                FROM reservation_visiteur rv
                {where_sql}
                ORDER BY rv.created_at DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        return json.dumps({
            "ok":    True,
            "total": len(results),
            "data":  results,
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Details complets d'une reservation — page AdminReservationDetail. "
    "Parametre : reference (str) — numero FAC-XXXX pour client, numero voucher pour visiteur. "
    "Parametre optionnel : source ('client' ou 'visiteur', defaut 'client'). "
    "Retourne : statut, dates, nb_nuits, client, facture (avec detail fiscal), chambres."
))
def admin_reservation_detail(reference: str, source: str = "client") -> str:
    try:
        # ═════════════════════════════════════════════════════════
        #  RESERVATION VISITEUR
        # ═════════════════════════════════════════════════════════
        if source == "visiteur":
            resa = db_fetchrow("""
                SELECT
                    CAST(rv.statut AS VARCHAR)     AS statut,
                    rv.total_ttc,
                    rv.date_debut,
                    rv.date_fin,
                    (rv.date_fin - rv.date_debut)  AS nb_nuits,
                    rv.nb_adultes,
                    rv.nb_enfants,
                    rv.numero_voucher,
                    rv.nom       AS client_nom,
                    rv.prenom    AS client_prenom,
                    rv.email     AS client_email,
                    rv.telephone AS client_tel,
                    rv.methode_paiement,
                    f.numero                      AS numero_facture,
                    CAST(f.statut AS VARCHAR)     AS statut_facture,
                    f.date_emission               AS facture_date_emission,
                    f.montant_ht                  AS facture_montant_ht,
                    f.tva_montant                 AS facture_tva,
                    f.taux_tva                    AS facture_taux_tva,
                    f.taxe_sejour                 AS facture_taxe_sejour,
                    f.droit_timbre                AS facture_droit_timbre,
                    f.nb_nuits_taxables           AS facture_nb_nuits_taxables,
                    f.montant_total               AS facture_montant_total,
                    rv.id AS _rid
                FROM reservation_visiteur rv
                LEFT JOIN facture f ON f.id = rv.id_facture
                WHERE rv.numero_voucher ILIKE %s
                LIMIT 1
            """, f"%{reference}%")

            if not resa:
                return json.dumps({
                    "ok": False,
                    "error": f"Aucune reservation visiteur avec le voucher '{reference}'"
                }, indent=2)

            rid = resa.pop("_rid")

            # NOTE: ligne_reservation_visiteur n'a PAS nb_nuits non plus
            chambres = db_fetch("""
                SELECT
                    tc.nom              AS type_chambre,
                    lrv.prix_unitaire,
                    lrv.nb_adultes,
                    lrv.nb_enfants,
                    h.nom               AS hotel_nom,
                    h.ville             AS hotel_ville
                FROM ligne_reservation_visiteur lrv
                LEFT JOIN chambre       c  ON c.id  = lrv.id_chambre
                LEFT JOIN type_chambre  tc ON tc.id = c.id_type_chambre
                LEFT JOIN hotel         h  ON h.id  = c.id_hotel
                WHERE lrv.id_reservation_visiteur = %s
            """, rid)
            resa["chambres"] = chambres

        # ═════════════════════════════════════════════════════════
        #  RESERVATION CLIENT
        # ═════════════════════════════════════════════════════════
        else:
            resa = db_fetchrow("""
                SELECT
                    CAST(r.statut AS VARCHAR)  AS statut,
                    r.total_ttc,
                    r.date_reservation,
                    r.date_debut,
                    r.date_fin,
                    (r.date_fin - r.date_debut) AS nb_nuits,
                    r.nb_adultes,
                    r.nb_enfants,
                    u.nom||' '||u.prenom       AS client_nom,
                    u.email                    AS client_email,
                    u.telephone                AS client_tel,
                    f.numero                   AS numero_facture,
                    CAST(f.statut AS VARCHAR)  AS statut_facture,
                    f.date_emission            AS facture_date_emission,
                    f.montant_ht               AS facture_montant_ht,
                    f.tva_montant              AS facture_tva,
                    f.taux_tva                 AS facture_taux_tva,
                    f.taxe_sejour              AS facture_taxe_sejour,
                    f.droit_timbre             AS facture_droit_timbre,
                    f.nb_nuits_taxables        AS facture_nb_nuits_taxables,
                    f.montant_total            AS facture_montant_total,
                    r.id AS _rid
                FROM reservation r
                JOIN utilisateur u ON u.id = r.id_client
                LEFT JOIN facture f ON f.id_reservation = r.id
                WHERE f.numero ILIKE %s
                LIMIT 1
            """, f"%{reference}%")

            if not resa:
                return json.dumps({
                    "ok": False,
                    "error": f"Aucune reservation client avec la facture '{reference}'"
                }, indent=2)

            rid = resa.pop("_rid")

            # ⚠️  lrc.nb_nuits N'EXISTE PAS — on utilise quantite
            # (quantite = nombre d'unites reservees, pas nb nuits).
            # Le nb_nuits est au niveau de la reservation, deja present dans 'resa' ci-dessus.
            chambres = db_fetch("""
                SELECT
                    tc.nom              AS type_chambre,
                    lrc.prix_unitaire,
                    lrc.quantite,
                    lrc.nb_adultes,
                    lrc.nb_enfants,
                    h.nom               AS hotel_nom,
                    h.ville             AS hotel_ville
                FROM ligne_reservation_chambre lrc
                LEFT JOIN chambre       c  ON c.id  = lrc.id_chambre
                LEFT JOIN type_chambre  tc ON tc.id = c.id_type_chambre
                LEFT JOIN hotel         h  ON h.id  = c.id_hotel
                WHERE lrc.id_reservation = %s
            """, rid)
            resa["chambres"] = chambres

        return json.dumps({"ok": True, "data": resa}, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)