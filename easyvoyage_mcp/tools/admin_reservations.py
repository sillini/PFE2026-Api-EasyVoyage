"""
mcp/tools/admin_reservations.py
================================
Tools MCP — Réservations clients et visiteurs.
Correspond à : AdminReservations.jsx

Tools :
  admin_reservations_liste   → liste fusionnée clients + visiteurs avec filtres
  admin_reservation_detail   → détail complet d'une réservation
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister toutes les réservations — page AdminReservations. "
    "Fusionne réservations clients ET visiteurs en une seule liste. "
    "Filtres : statut (CONFIRMEE|EN_ATTENTE|ANNULEE|TERMINEE), "
    "hotel_id (int), client_search (str nom/prénom/email/téléphone), "
    "date_debut (YYYY-MM-DD), date_fin (YYYY-MM-DD), "
    "source ('client'|'visiteur', None = les deux), "
    "type_resa ('hotel'|'voyage'), limit (int, défaut 50). "
    "Retourne aussi : total_ttc agrégé, nb_clients, nb_visiteurs."
))
def admin_reservations_liste(
    statut:        str = None,
    hotel_id:      int = None,
    client_search: str = None,
    date_debut:    str = None,
    date_fin:      str = None,
    source:        str = None,
    type_resa:     str = None,
    limit:         int = 50,
) -> str:
    try:
        results = []

        # ── Réservations clients ──────────────────────────────
        if source in (None, "client"):
            w, p = [], []
            if statut:      w.append("r.statut = %s");                   p.append(statut)
            if date_debut:  w.append("r.date_debut >= %s");              p.append(date_debut)
            if date_fin:    w.append("r.date_fin <= %s");                p.append(date_fin)
            if type_resa == "hotel":  w.append("r.id_voyage IS NULL")
            if type_resa == "voyage": w.append("r.id_voyage IS NOT NULL")
            if hotel_id:
                w.append("""EXISTS (
                    SELECT 1 FROM ligne_reservation_chambre lrc
                    JOIN chambre c ON c.id = lrc.id_chambre
                    WHERE lrc.id_reservation = r.id AND c.id_hotel = %s
                )""")
                p.append(hotel_id)
            if client_search:
                w.append("(u.nom ILIKE %s OR u.prenom ILIKE %s OR u.email ILIKE %s OR u.telephone ILIKE %s)")
                p += [f"%{client_search}%"] * 4
            where_sql = ("WHERE " + " AND ".join(w)) if w else ""
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    r.id,
                    'client'                                                  AS source,
                    r.statut,
                    r.total_ttc,
                    r.date_reservation,
                    r.date_debut,
                    r.date_fin,
                    (r.date_fin - r.date_debut)                               AS nb_nuits,
                    CASE WHEN r.id_voyage IS NOT NULL THEN 'voyage' ELSE 'hotel' END AS type_resa,
                    u.id                                                       AS client_id,
                    u.nom                                                      AS client_nom,
                    u.prenom                                                   AS client_prenom,
                    u.email                                                    AS client_email,
                    u.telephone                                                AS client_tel,
                    f.numero                                                   AS numero_facture,
                    f.statut                                                   AS statut_facture,
                    f.total_ttc                                                AS facture_ttc,
                    NULL::text                                                 AS numero_voucher
                FROM reservation r
                JOIN utilisateur u ON u.id = r.id_client
                LEFT JOIN facture f ON f.id_reservation = r.id
                {where_sql}
                ORDER BY r.date_reservation DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        # ── Réservations visiteurs ────────────────────────────
        if source in (None, "visiteur"):
            w, p = [], []
            if statut:     w.append("rv.statut = %s");    p.append(statut)
            if date_debut: w.append("rv.date_debut >= %s"); p.append(date_debut)
            if date_fin:   w.append("rv.date_fin <= %s");   p.append(date_fin)
            if hotel_id:
                w.append("""EXISTS (
                    SELECT 1 FROM ligne_reservation_visiteur lrv
                    JOIN chambre c ON c.id = lrv.id_chambre
                    WHERE lrv.id_reservation_visiteur = rv.id AND c.id_hotel = %s
                )""")
                p.append(hotel_id)
            if client_search:
                w.append("(rv.nom ILIKE %s OR rv.prenom ILIKE %s OR rv.email ILIKE %s OR rv.telephone ILIKE %s)")
                p += [f"%{client_search}%"] * 4
            where_sql = ("WHERE " + " AND ".join(w)) if w else ""
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    rv.id,
                    'visiteur'           AS source,
                    rv.statut,
                    rv.total_ttc,
                    rv.created_at        AS date_reservation,
                    rv.date_debut,
                    rv.date_fin,
                    (rv.date_fin - rv.date_debut) AS nb_nuits,
                    'hotel'              AS type_resa,
                    NULL::int            AS client_id,
                    rv.nom               AS client_nom,
                    rv.prenom            AS client_prenom,
                    rv.email             AS client_email,
                    rv.telephone         AS client_tel,
                    NULL::text           AS numero_facture,
                    NULL::text           AS statut_facture,
                    rv.total_ttc         AS facture_ttc,
                    rv.numero_voucher
                FROM reservation_visiteur rv
                {where_sql}
                ORDER BY rv.created_at DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        results.sort(key=lambda x: str(x.get("date_reservation", "")), reverse=True)
        results = results[:limit]

        total_ttc    = sum(float(r.get("total_ttc") or 0) for r in results)
        nb_clients   = sum(1 for r in results if r.get("source") == "client")
        nb_visiteurs = sum(1 for r in results if r.get("source") == "visiteur")

        return json.dumps({
            "ok":          True,
            "total":       len(results),
            "nb_clients":  nb_clients,
            "nb_visiteurs": nb_visiteurs,
            "total_ttc":   round(total_ttc, 2),
            "data":        results,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Détail complet d'une réservation par son ID. "
    "Paramètres : reservation_id (int), source ('client'|'visiteur', défaut 'client'). "
    "Pour client : retourne lignes chambres + facture (total_ht, tva, taxe_sejour, timbre, ttc). "
    "Pour visiteur : retourne lignes chambres + numéro voucher."
))
def admin_reservation_detail(reservation_id: int, source: str = "client") -> str:
    try:
        if source == "visiteur":
            resa = db_fetchrow("""
                SELECT rv.*
                FROM reservation_visiteur rv
                WHERE rv.id = %s
            """, reservation_id)
            if resa:
                chambres = db_fetch("""
                    SELECT lrv.id_chambre, lrv.prix_unitaire,
                           lrv.nb_adultes, lrv.nb_enfants,
                           tc.nom AS type_chambre,
                           h.nom  AS hotel_nom, h.ville AS hotel_ville
                    FROM ligne_reservation_visiteur lrv
                    LEFT JOIN chambre c       ON c.id = lrv.id_chambre
                    LEFT JOIN type_chambre tc ON tc.id = c.id_type_chambre
                    LEFT JOIN hotel h         ON h.id = c.id_hotel
                    WHERE lrv.id_reservation_visiteur = %s
                """, reservation_id)
                resa["chambres"] = chambres
        else:
            resa = db_fetchrow("""
                SELECT
                    r.*,
                    u.nom || ' ' || u.prenom AS client_nom_complet,
                    u.email                  AS client_email,
                    u.telephone              AS client_tel,
                    f.numero                 AS numero_facture,
                    f.statut                 AS statut_facture,
                    f.total_ht, f.tva,
                    f.taxe_sejour, f.droit_timbre,
                    f.total_ttc              AS facture_ttc
                FROM reservation r
                JOIN utilisateur u ON u.id = r.id_client
                LEFT JOIN facture f ON f.id_reservation = r.id
                WHERE r.id = %s
            """, reservation_id)
            if resa:
                chambres = db_fetch("""
                    SELECT lrc.id_chambre, lrc.prix_unitaire,
                           lrc.nb_adultes, lrc.nb_enfants,
                           tc.nom  AS type_chambre,
                           h.id    AS hotel_id,
                           h.nom   AS hotel_nom, h.ville AS hotel_ville
                    FROM ligne_reservation_chambre lrc
                    LEFT JOIN chambre c       ON c.id = lrc.id_chambre
                    LEFT JOIN type_chambre tc ON tc.id = c.id_type_chambre
                    LEFT JOIN hotel h         ON h.id = c.id_hotel
                    WHERE lrc.id_reservation = %s
                """, reservation_id)
                resa["chambres"] = chambres

        if not resa:
            return json.dumps({
                "ok": False,
                "error": f"Réservation {reservation_id} introuvable (source={source})"
            })

        return json.dumps({"ok": True, "source": source, "data": resa}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)