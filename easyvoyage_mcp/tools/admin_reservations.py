"""
mcp/tools/admin_reservations.py — recherche par numero_facture ou voucher (jamais par ID)
"""
import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les reservations (clients + visiteurs). "
    "Filtres : statut (EN_ATTENTE|CONFIRMEE|ANNULEE|TERMINEE), source (client|visiteur), "
    "date_debut, date_fin (YYYY-MM-DD), hotel_nom, client_search (nom/prenom/email), limit (defaut 50)."
))
def admin_reservations_liste(
    statut: str=None, source: str=None,
    date_debut: str=None, date_fin: str=None,
    hotel_nom: str=None, client_search: str=None,
    limit: int=50,
) -> str:
    try:
        results = []

        # Clients
        if source in (None, "client"):
            w, p = ["1=1"], []
            if statut:        w.append("CAST(r.statut AS VARCHAR)=%s"); p.append(statut)
            if date_debut:    w.append("r.date_debut >= %s"); p.append(date_debut)
            if date_fin:      w.append("r.date_fin <= %s");   p.append(date_fin)
            if hotel_nom:
                w.append("""EXISTS (
                    SELECT 1 FROM ligne_reservation_chambre lrc
                    JOIN chambre c ON c.id=lrc.id_chambre
                    JOIN hotel h ON h.id=c.id_hotel
                    WHERE lrc.id_reservation=r.id AND h.nom ILIKE %s
                )"""); p.append(f"%{hotel_nom}%")
            if client_search:
                w.append("(u.nom ILIKE %s OR u.prenom ILIKE %s OR u.email ILIKE %s OR u.telephone ILIKE %s)")
                p += [f"%{client_search}%"]*4
            p.append(limit)
            rows = db_fetch(f"""
                SELECT 'client' AS source,
                    CAST(r.statut AS VARCHAR) AS statut,
                    r.total_ttc, r.date_reservation, r.date_debut, r.date_fin,
                    (r.date_fin - r.date_debut) AS nb_nuits,
                    CASE WHEN r.id_voyage IS NOT NULL THEN 'voyage' ELSE 'hotel' END AS type_resa,
                    u.nom AS client_nom, u.prenom AS client_prenom,
                    u.email AS client_email, u.telephone AS client_tel,
                    f.numero AS numero_facture, f.statut AS statut_facture,
                    NULL AS numero_voucher
                FROM reservation r
                JOIN utilisateur u ON u.id=r.id_client
                LEFT JOIN facture f ON f.id_reservation=r.id
                WHERE {' AND '.join(w)}
                ORDER BY r.date_reservation DESC LIMIT %s
            """, *p)
            results.extend(rows)

        # Visiteurs
        if source in (None, "visiteur"):
            w, p = ["1=1"], []
            if statut:     w.append("rv.statut=%s"); p.append(statut)
            if date_debut: w.append("rv.date_debut >= %s"); p.append(date_debut)
            if date_fin:   w.append("rv.date_fin <= %s");   p.append(date_fin)
            if hotel_nom:
                w.append("""EXISTS (
                    SELECT 1 FROM chambre c JOIN hotel h ON h.id=c.id_hotel
                    WHERE c.id=rv.id_chambre AND h.nom ILIKE %s
                )"""); p.append(f"%{hotel_nom}%")
            if client_search:
                w.append("(rv.nom ILIKE %s OR rv.prenom ILIKE %s OR rv.email ILIKE %s OR rv.telephone ILIKE %s)")
                p += [f"%{client_search}%"]*4
            p.append(limit)
            rows = db_fetch(f"""
                SELECT 'visiteur' AS source,
                    rv.statut, rv.total_ttc, rv.created_at AS date_reservation,
                    rv.date_debut, rv.date_fin,
                    (rv.date_fin - rv.date_debut) AS nb_nuits,
                    'hotel' AS type_resa,
                    rv.nom AS client_nom, rv.prenom AS client_prenom,
                    rv.email AS client_email, rv.telephone AS client_tel,
                    NULL AS numero_facture, NULL AS statut_facture,
                    rv.numero_voucher
                FROM reservation_visiteur rv
                WHERE {' AND '.join(w)}
                ORDER BY rv.created_at DESC LIMIT %s
            """, *p)
            results.extend(rows)

        results.sort(key=lambda x: str(x.get("date_reservation", "")), reverse=True)
        results = results[:limit]
        total_ttc    = sum(float(r.get("total_ttc") or 0) for r in results)
        nb_clients   = sum(1 for r in results if r.get("source")=="client")
        nb_visiteurs = sum(1 for r in results if r.get("source")=="visiteur")

        return json.dumps({
            "ok": True, "total": len(results),
            "nb_clients": nb_clients, "nb_visiteurs": nb_visiteurs,
            "total_ttc": round(total_ttc, 2), "data": results,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Detail complet d'une reservation par son NUMERO DE FACTURE ou NUMERO VOUCHER (jamais par ID). "
    "Parametre : reference (str) — numero FAC-XXXX pour client, numero voucher pour visiteur. "
    "Parametre optionnel : source ('client' ou 'visiteur', defaut 'client')."
))
def admin_reservation_detail(reference: str, source: str="client") -> str:
    try:
        if source == "visiteur":
            resa = db_fetchrow("""
                SELECT rv.statut, rv.total_ttc, rv.date_debut, rv.date_fin,
                    rv.nb_adultes, rv.nb_enfants, rv.numero_voucher,
                    rv.nom AS client_nom, rv.prenom AS client_prenom,
                    rv.email AS client_email, rv.telephone AS client_tel,
                    rv.id AS _rid
                FROM reservation_visiteur rv
                WHERE rv.numero_voucher ILIKE %s LIMIT 1
            """, f"%{reference}%")
            if not resa:
                return json.dumps({"ok": False, "error": f"Aucune reservation visiteur avec le voucher '{reference}'"})
            rid = resa.pop("_rid")
            chambres = db_fetch("""
                SELECT tc.nom AS type_chambre, lrv.prix_unitaire,
                    lrv.nb_adultes, lrv.nb_enfants,
                    h.nom AS hotel_nom, h.ville AS hotel_ville
                FROM ligne_reservation_visiteur lrv
                LEFT JOIN chambre c ON c.id=lrv.id_chambre
                LEFT JOIN type_chambre tc ON tc.id=c.id_type_chambre
                LEFT JOIN hotel h ON h.id=c.id_hotel
                WHERE lrv.id_reservation_visiteur=%s
            """, rid)
            resa["chambres"] = chambres

        else:
            resa = db_fetchrow("""
                SELECT CAST(r.statut AS VARCHAR) AS statut, r.total_ttc,
                    r.date_reservation, r.date_debut, r.date_fin,
                    r.nb_adultes, r.nb_enfants,
                    u.nom||' '||u.prenom AS client_nom,
                    u.email AS client_email, u.telephone AS client_tel,
                    f.numero AS numero_facture, CAST(f.statut AS VARCHAR) AS statut_facture,
                    f.total_ht, f.tva, f.taxe_sejour, f.droit_timbre,
                    r.id AS _rid
                FROM reservation r
                JOIN utilisateur u ON u.id=r.id_client
                LEFT JOIN facture f ON f.id_reservation=r.id
                WHERE f.numero ILIKE %s LIMIT 1
            """, f"%{reference}%")
            if not resa:
                return json.dumps({"ok": False, "error": f"Aucune reservation avec la facture '{reference}'"})
            rid = resa.pop("_rid")
            chambres = db_fetch("""
                SELECT tc.nom AS type_chambre, lrc.prix_unitaire,
                    lrc.nb_adultes, lrc.nb_enfants,
                    h.nom AS hotel_nom, h.ville AS hotel_ville
                FROM ligne_reservation_chambre lrc
                LEFT JOIN chambre c ON c.id=lrc.id_chambre
                LEFT JOIN type_chambre tc ON tc.id=c.id_type_chambre
                LEFT JOIN hotel h ON h.id=c.id_hotel
                WHERE lrc.id_reservation=%s
            """, rid)
            resa["chambres"] = chambres

        return json.dumps({"ok": True, "source": source, "data": resa}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)