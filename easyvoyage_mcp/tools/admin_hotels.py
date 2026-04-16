"""
mcp/tools/admin_hotels.py
==========================
Tools MCP — Gestion des hôtels.
Correspond à : AdminHotels.jsx + AdminHotelsVedettes.jsx

Tools :
  admin_hotels_liste   → liste avec filtres avancés
  admin_hotel_detail   → détail complet (chambres, promos, avis, stats)
  admin_hotels_avis    → tous les avis avec filtres
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les hôtels — page AdminHotels. "
    "Filtres optionnels : search (nom), ville, pays, etoiles_min (int 1-5), "
    "actif (bool), mis_en_avant (bool), partenaire_id (int), limit (int, défaut 50). "
    "Retourne : id, nom, ville, pays, etoiles, actif, mis_en_avant, "
    "nb_chambres, partenaire_nom, partenaire_email, nb_reservations, ca_total."
))
def admin_hotels_liste(
    search:        str  = None,
    ville:         str  = None,
    pays:          str  = None,
    etoiles_min:   int  = None,
    actif:         bool = None,
    mis_en_avant:  bool = None,
    partenaire_id: int  = None,
    limit:         int  = 50,
) -> str:
    try:
        wheres, params = [], []
        if search:
            wheres.append("h.nom ILIKE %s"); params.append(f"%{search}%")
        if ville:
            wheres.append("h.ville ILIKE %s"); params.append(f"%{ville}%")
        if pays:
            wheres.append("h.pays ILIKE %s"); params.append(f"%{pays}%")
        if etoiles_min is not None:
            wheres.append("h.etoiles >= %s"); params.append(etoiles_min)
        if actif is not None:
            wheres.append("h.actif = %s"); params.append(actif)
        if mis_en_avant is not None:
            wheres.append("h.mis_en_avant = %s"); params.append(mis_en_avant)
        if partenaire_id is not None:
            wheres.append("h.id_partenaire = %s"); params.append(partenaire_id)

        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                h.id, h.nom, h.ville, h.pays, h.etoiles,
                h.actif, h.mis_en_avant, h.id_partenaire,
                COUNT(DISTINCT c.id)                       AS nb_chambres,
                u.nom || ' ' || u.prenom                   AS partenaire_nom,
                u.email                                    AS partenaire_email,
                COUNT(DISTINCT lrc.id_reservation)         AS nb_reservations,
                COALESCE(SUM(DISTINCT r.total_ttc), 0)     AS ca_total
            FROM hotel h
            LEFT JOIN chambre c                    ON c.id_hotel = h.id
            LEFT JOIN utilisateur u                ON u.id = h.id_partenaire
            LEFT JOIN ligne_reservation_chambre lrc ON lrc.id_chambre = c.id
            LEFT JOIN reservation r                ON r.id = lrc.id_reservation
                                                   AND r.statut != 'ANNULEE'
            {where_sql}
            GROUP BY h.id, u.nom, u.prenom, u.email
            ORDER BY h.nom
            LIMIT %s
        """, *params)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Détail complet d'un hôtel par son ID. "
    "Retourne : infos générales + partenaire, chambres avec tarifs (min/max), "
    "toutes les promotions (PENDING/APPROVED/REJECTED), "
    "stats avis (note moyenne, nb positifs/négatifs), 10 derniers avis, "
    "statistiques réservations clients ET visiteurs (nb + CA)."
))
def admin_hotel_detail(hotel_id: int) -> str:
    try:
        hotel = db_fetchrow("""
            SELECT h.*,
                   u.nom || ' ' || u.prenom AS partenaire_nom,
                   u.email                  AS partenaire_email,
                   u.telephone              AS partenaire_tel
            FROM hotel h
            LEFT JOIN utilisateur u ON u.id = h.id_partenaire
            WHERE h.id = %s
        """, hotel_id)
        if not hotel:
            return json.dumps({"ok": False, "error": f"Hôtel {hotel_id} introuvable"})

        chambres = db_fetch("""
            SELECT c.id, c.description, c.capacite, c.nb_chambres,
                   tc.nom     AS type_chambre,
                   MIN(t.prix) AS prix_min,
                   MAX(t.prix) AS prix_max,
                   COUNT(t.id) AS nb_tarifs
            FROM chambre c
            LEFT JOIN type_chambre tc ON tc.id = c.id_type_chambre
            LEFT JOIN tarif t          ON t.id_chambre = c.id
            WHERE c.id_hotel = %s
            GROUP BY c.id, tc.nom
            ORDER BY c.id
        """, hotel_id)

        promotions = db_fetch("""
            SELECT p.id, p.titre, p.pourcentage, p.statut, p.actif,
                   p.date_debut, p.date_fin, p.raison_refus, p.created_at,
                   u.nom || ' ' || u.prenom AS partenaire_nom
            FROM promotion p
            LEFT JOIN utilisateur u ON u.id = p.id_partenaire
            WHERE p.id_hotel = %s
            ORDER BY p.created_at DESC
            LIMIT 20
        """, hotel_id)

        avis_stats = db_fetchrow("""
            SELECT
                COUNT(*)                                           AS nb_avis,
                ROUND(AVG(note)::numeric, 2)                      AS note_moyenne,
                COUNT(CASE WHEN note >= 4 THEN 1 END)             AS nb_positifs,
                COUNT(CASE WHEN note = 3 THEN 1 END)              AS nb_neutres,
                COUNT(CASE WHEN note <= 2 THEN 1 END)             AS nb_negatifs
            FROM avis WHERE id_hotel = %s
        """, hotel_id)

        avis_recents = db_fetch("""
            SELECT a.id, a.note, a.commentaire, a.created_at,
                   u.nom || ' ' || u.prenom AS client_nom, u.email AS client_email
            FROM avis a
            LEFT JOIN utilisateur u ON u.id = a.id_client
            WHERE a.id_hotel = %s
            ORDER BY a.created_at DESC
            LIMIT 10
        """, hotel_id)

        stats_resa = db_fetchrow("""
            SELECT
                COUNT(DISTINCT lrc.id_reservation)          AS nb_resa_clients,
                COUNT(DISTINCT lrv.id_reservation_visiteur) AS nb_resa_visiteurs,
                COALESCE(SUM(DISTINCT r.total_ttc),  0)     AS ca_clients,
                COALESCE(SUM(DISTINCT rv.total_ttc), 0)     AS ca_visiteurs
            FROM chambre c
            LEFT JOIN ligne_reservation_chambre lrc ON lrc.id_chambre = c.id
            LEFT JOIN reservation r                 ON r.id = lrc.id_reservation
            LEFT JOIN ligne_reservation_visiteur lrv ON lrv.id_chambre = c.id
            LEFT JOIN reservation_visiteur rv        ON rv.id = lrv.id_reservation_visiteur
            WHERE c.id_hotel = %s
        """, hotel_id)

        return json.dumps({
            "ok": True,
            "hotel":        hotel,
            "chambres":     chambres,
            "promotions":   promotions,
            "avis_stats":   avis_stats,
            "avis_recents": avis_recents,
            "stats_resa":   stats_resa,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Lister les avis clients de la plateforme. "
    "Filtres : hotel_id (int), note_min (int 1-5), "
    "hotel_search (str nom hôtel), client_search (str nom/email), limit (int). "
    "Retourne : note, commentaire, date, hotel_nom, hotel_ville, client_nom, client_email."
))
def admin_hotels_avis(
    hotel_id:      int = None,
    note_min:      int = None,
    hotel_search:  str = None,
    client_search: str = None,
    limit:         int = 50,
) -> str:
    try:
        wheres, params = [], []
        if hotel_id:
            wheres.append("a.id_hotel = %s"); params.append(hotel_id)
        if note_min:
            wheres.append("a.note >= %s"); params.append(note_min)
        if hotel_search:
            wheres.append("h.nom ILIKE %s"); params.append(f"%{hotel_search}%")
        if client_search:
            wheres.append("(u.nom ILIKE %s OR u.email ILIKE %s)")
            params += [f"%{client_search}%"] * 2
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT a.id, a.note, a.commentaire, a.created_at,
                   h.id AS hotel_id, h.nom AS hotel_nom, h.ville AS hotel_ville,
                   u.nom || ' ' || u.prenom AS client_nom,
                   u.email                  AS client_email
            FROM avis a
            JOIN hotel h ON h.id = a.id_hotel
            LEFT JOIN utilisateur u ON u.id = a.id_client
            {where_sql}
            ORDER BY a.created_at DESC
            LIMIT %s
        """, *params)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)