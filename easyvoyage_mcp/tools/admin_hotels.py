"""
mcp/tools/admin_hotels.py — recherche par NOM (jamais par ID)

Colonnes réelles vérifiées :
  chambre      : id, capacite, description, id_hotel, id_type_chambre, actif, nb_chambres
  type_chambre : id, nom, description
  tarif        : id, prix, date_debut, date_fin, id_chambre, id_type_reservation
  avis         : id, note, commentaire, date, id_client, id_hotel
  promotion    : id, titre, description, id_hotel, pourcentage, date_debut, date_fin, actif, statut
"""
import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les hotels. Filtres : search (nom), ville, pays, etoiles_min (1-5), "
    "actif (bool), mis_en_avant (bool), partenaire_email, limit (defaut 50)."
))
def admin_hotels_liste(
    search: str=None, ville: str=None, pays: str=None,
    etoiles_min: int=None, actif: bool=None, mis_en_avant: bool=None,
    partenaire_email: str=None, limit: int=50,
) -> str:
    try:
        w, p = [], []
        if search:                   w.append("h.nom ILIKE %s");        p.append(f"%{search}%")
        if ville:                    w.append("h.ville ILIKE %s");      p.append(f"%{ville}%")
        if pays:                     w.append("h.pays ILIKE %s");       p.append(f"%{pays}%")
        if etoiles_min:              w.append("h.etoiles >= %s");       p.append(etoiles_min)
        if actif is not None:        w.append("h.actif = %s");          p.append(actif)
        if mis_en_avant is not None: w.append("h.mis_en_avant = %s");   p.append(mis_en_avant)
        if partenaire_email:         w.append("u.email ILIKE %s");      p.append(f"%{partenaire_email}%")
        where_sql = ("WHERE " + " AND ".join(w)) if w else ""
        p.append(limit)

        rows = db_fetch(f"""
            SELECT
                h.nom, h.ville, h.pays, h.etoiles, h.actif, h.mis_en_avant,
                u.nom||' '||u.prenom  AS partenaire_nom,
                u.email               AS partenaire_email,
                (SELECT COUNT(*) FROM chambre c WHERE c.id_hotel=h.id) AS nb_chambres,
                COALESCE(ca_c.nb,0)+COALESCE(ca_v.nb,0) AS nb_reservations_total,
                COALESCE(ca_c.ca,0)+COALESCE(ca_v.ca,0) AS ca_total,
                ROUND((COALESCE(ca_c.ca,0)+COALESCE(ca_v.ca,0))*10.0/100,2) AS commission_agence
            FROM hotel h
            LEFT JOIN utilisateur u ON u.id=h.id_partenaire
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
            {where_sql}
            GROUP BY h.id, u.nom, u.prenom, u.email,
                     ca_c.nb, ca_c.ca, ca_v.nb, ca_v.ca
            ORDER BY ca_total DESC LIMIT %s
        """, *p)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Detail complet d'un hotel par son NOM (jamais par ID). "
    "Parametre : hotel_nom (str) — nom exact ou partiel."
))
def admin_hotel_detail(hotel_nom: str) -> str:
    try:
        hotel = db_fetchrow("""
            SELECT h.nom, h.ville, h.pays, h.etoiles, h.actif, h.mis_en_avant,
                h.adresse, h.description, h.note_moyenne,
                u.nom||' '||u.prenom AS partenaire_nom,
                u.email              AS partenaire_email,
                p.nom_entreprise, p.commission AS taux_commission,
                h.id AS _hid
            FROM hotel h
            LEFT JOIN utilisateur u ON u.id=h.id_partenaire
            LEFT JOIN partenaire p  ON p.id=h.id_partenaire
            WHERE h.nom ILIKE %s ORDER BY h.actif DESC LIMIT 1
        """, f"%{hotel_nom}%")

        if not hotel:
            return json.dumps({"ok": False, "error": f"Aucun hotel trouve avec le nom '{hotel_nom}'"})

        hid = hotel.pop("_hid")

        chambres = db_fetch("""
            SELECT tc.nom AS type_chambre, c.nb_chambres, c.capacite, c.actif,
                MIN(t.prix) AS prix_min, MAX(t.prix) AS prix_max,
                (SELECT COUNT(*) FROM reservation_visiteur rv
                 WHERE rv.id_chambre=c.id AND rv.statut IN ('CONFIRMEE','TERMINEE')) AS nb_resa_visiteurs,
                (SELECT COUNT(DISTINCT r.id) FROM reservation r
                 JOIN ligne_reservation_chambre lrc ON lrc.id_reservation=r.id
                 WHERE lrc.id_chambre=c.id AND r.id_voyage IS NULL
                   AND r.statut IN ('CONFIRMEE','TERMINEE')) AS nb_resa_clients
            FROM chambre c
            LEFT JOIN type_chambre tc ON tc.id=c.id_type_chambre
            LEFT JOIN tarif t ON t.id_chambre=c.id
            WHERE c.id_hotel=%s GROUP BY c.id, tc.nom ORDER BY tc.nom
        """, hid)

        promos = db_fetch("""
            SELECT titre, pourcentage, date_debut, date_fin, actif,
                   CAST(statut AS VARCHAR) AS statut
            FROM promotion
            WHERE id_hotel=%s AND CAST(statut AS VARCHAR)='APPROVED'
              AND actif=true AND date_fin >= CURRENT_DATE
            ORDER BY date_fin
        """, hid)

        avis = db_fetch("""
            SELECT a.note, a.commentaire, a.date AS created_at,
                   u.nom||' '||u.prenom AS client_nom
            FROM avis a LEFT JOIN utilisateur u ON u.id=a.id_client
            WHERE a.id_hotel=%s ORDER BY a.date DESC LIMIT 10
        """, hid)

        stats = db_fetchrow("""
            SELECT COALESCE(c.nb,0)+COALESCE(v.nb,0) AS nb_reservations_total,
                COALESCE(c.nb,0) AS nb_clients, COALESCE(v.nb,0) AS nb_visiteurs,
                COALESCE(c.ca,0) AS ca_clients, COALESCE(v.ca,0) AS ca_visiteurs,
                COALESCE(c.ca,0)+COALESCE(v.ca,0) AS ca_total,
                ROUND((COALESCE(c.ca,0)+COALESCE(v.ca,0))*10.0/100,2) AS commission_agence,
                ROUND((COALESCE(c.ca,0)+COALESCE(v.ca,0))*90.0/100,2) AS part_partenaire
            FROM (SELECT 1) d
            LEFT JOIN (
                SELECT COUNT(DISTINCT r.id) AS nb, COALESCE(SUM(r.total_ttc),0) AS ca
                FROM reservation r JOIN ligne_reservation_chambre lrc ON lrc.id_reservation=r.id
                JOIN chambre ch ON ch.id=lrc.id_chambre
                WHERE ch.id_hotel=%s AND r.id_voyage IS NULL AND r.statut IN ('CONFIRMEE','TERMINEE')
            ) c ON true
            LEFT JOIN (
                SELECT COUNT(DISTINCT rv.id) AS nb, COALESCE(SUM(rv.total_ttc),0) AS ca
                FROM reservation_visiteur rv JOIN chambre ch ON ch.id=rv.id_chambre
                WHERE ch.id_hotel=%s AND rv.statut IN ('CONFIRMEE','TERMINEE')
            ) v ON true
        """, hid, hid)

        return json.dumps({"ok": True, "hotel": hotel, "chambres": chambres,
                           "promos": promos, "avis": avis, "stats": stats}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Avis clients par hotel. Filtres : hotel_nom (partiel), note_min (1-5), "
    "search (commentaire/nom client), limit."
))
def admin_hotels_avis(
    hotel_nom: str=None, note_min: int=None, search: str=None, limit: int=50
) -> str:
    try:
        w, p = [], []
        if hotel_nom: w.append("h.nom ILIKE %s"); p.append(f"%{hotel_nom}%")
        if note_min:  w.append("a.note >= %s");   p.append(note_min)
        if search:
            w.append("(a.commentaire ILIKE %s OR u.nom ILIKE %s OR u.prenom ILIKE %s)")
            p += [f"%{search}%"]*3
        where_sql = ("WHERE "+" AND ".join(w)) if w else ""
        p.append(limit)

        rows = db_fetch(f"""
            SELECT a.note, a.commentaire, a.date AS created_at,
                   u.nom||' '||u.prenom AS client_nom,
                   h.nom AS hotel_nom, h.ville
            FROM avis a
            LEFT JOIN utilisateur u ON u.id=a.id_client
            LEFT JOIN hotel h ON h.id=a.id_hotel
            {where_sql} ORDER BY a.date DESC LIMIT %s
        """, *p)

        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Classement de TOUS les hotels par note de satisfaction client — UN SEUL appel. "
    "Utiliser pour : meilleur/pire hotel, classement satisfaction, "
    "hotel le mieux/moins bien note, score satisfaction, comparaison notes. "
    "Aucun parametre requis — retourne le classement complet avec nb_avis et note_moyenne."
))
def admin_hotels_classement_satisfaction() -> str:
    try:
        rows = db_fetch("""
            SELECT
                h.nom                                   AS hotel_nom,
                h.ville,
                h.etoiles,
                h.actif,
                COUNT(a.id)                             AS nb_avis,
                ROUND(AVG(a.note)::numeric, 2)          AS note_moyenne,
                MIN(a.note)                             AS note_min,
                MAX(a.note)                             AS note_max
            FROM hotel h
            LEFT JOIN avis a ON a.id_hotel = h.id
            GROUP BY h.id
            ORDER BY note_moyenne DESC NULLS LAST, nb_avis DESC
        """)

        return json.dumps({
            "ok": True,
            "total": len(rows),
            "classement": rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)