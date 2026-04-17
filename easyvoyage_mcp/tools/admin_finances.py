"""
mcp/tools/admin_finances.py
=============================
Colonnes réelles commission_partenaire :
  id, id_reservation, id_partenaire, type_resa,
  montant_total_resa, taux_commission, montant_commission, montant_partenaire,
  statut (varchar: EN_ATTENTE | PAYEE), date_creation, date_paiement
"""
import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")

TAUX_COMMISSION = 10.0


@mcp.tool(description=(
    "Dashboard financier complet. "
    "Retourne : CA hotel/voyage/visiteurs/total, commission agence 10%, part partenaires, "
    "commissions (total/en_attente/payees), revenus mensuels 12 mois, "
    "top 10 hotels, top 10 partenaires."
))
def admin_finances_dashboard() -> str:
    try:
        global_kpis = db_fetchrow("""
            SELECT
                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation
                 WHERE id_voyage IS NULL AND statut IN ('CONFIRMEE','TERMINEE'))     AS ca_hotel_clients,
                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation
                 WHERE id_voyage IS NOT NULL AND statut IN ('CONFIRMEE','TERMINEE')) AS ca_voyage_clients,
                (SELECT COALESCE(SUM(total_ttc),0) FROM reservation_visiteur
                 WHERE statut IN ('CONFIRMEE','TERMINEE'))                           AS ca_hotel_visiteurs,
                (SELECT COUNT(*) FROM reservation
                 WHERE id_voyage IS NULL AND statut IN ('CONFIRMEE','TERMINEE'))     AS nb_resa_hotel_clients,
                (SELECT COUNT(*) FROM reservation
                 WHERE id_voyage IS NOT NULL AND statut IN ('CONFIRMEE','TERMINEE')) AS nb_resa_voyage_clients,
                (SELECT COUNT(*) FROM reservation_visiteur
                 WHERE statut IN ('CONFIRMEE','TERMINEE'))                           AS nb_resa_hotel_visiteurs
        """)

        ca_hc = float(global_kpis.get("ca_hotel_clients")   or 0)
        ca_vc = float(global_kpis.get("ca_voyage_clients")  or 0)
        ca_hv = float(global_kpis.get("ca_hotel_visiteurs") or 0)
        ca_hotel_total    = round(ca_hc + ca_hv, 2)
        ca_total          = round(ca_hotel_total + ca_vc, 2)
        commission_agence = round(ca_hotel_total * TAUX_COMMISSION / 100, 2)
        part_partenaires  = round(ca_hotel_total - commission_agence, 2)

        global_kpis["ca_hotel_total"]    = ca_hotel_total
        global_kpis["ca_voyage_total"]   = round(ca_vc, 2)
        global_kpis["ca_total"]          = ca_total
        global_kpis["commission_agence"] = commission_agence
        global_kpis["part_partenaires"]  = part_partenaires
        global_kpis["nb_resa_total"] = (
            int(global_kpis.get("nb_resa_hotel_clients")   or 0) +
            int(global_kpis.get("nb_resa_voyage_clients")  or 0) +
            int(global_kpis.get("nb_resa_hotel_visiteurs") or 0)
        )

        # Commissions — colonne "statut" (pas statut_commission)
        commissions = db_fetchrow("""
            SELECT
                COALESCE(SUM(montant_commission),0)                              AS total,
                COALESCE(SUM(CASE WHEN statut='EN_ATTENTE'
                    THEN montant_commission END),0)                              AS en_attente,
                COALESCE(SUM(CASE WHEN statut='PAYEE'
                    THEN montant_commission END),0)                              AS payees,
                COUNT(*)                                                          AS nb_total,
                COUNT(CASE WHEN statut='EN_ATTENTE' THEN 1 END)                  AS nb_en_attente
            FROM commission_partenaire
        """)

        # Revenus mensuels — visiteurs utilisent created_at
        revenus_mensuels = db_fetch("""
            SELECT periode,
                SUM(rh_c) AS revenu_hotel_clients,
                SUM(rv_c) AS revenu_voyage_clients,
                SUM(rh_v) AS revenu_hotel_visiteurs,
                SUM(rh_c)+SUM(rh_v) AS revenu_hotel_total,
                SUM(rh_c)+SUM(rv_c)+SUM(rh_v) AS revenu_total,
                ROUND((SUM(rh_c)+SUM(rh_v))*10.0/100,2) AS commission_agence,
                SUM(nb) AS nb_reservations
            FROM (
                SELECT TO_CHAR(date_reservation,'YYYY-MM') AS periode,
                    COALESCE(SUM(CASE WHEN id_voyage IS NULL THEN total_ttc END),0) AS rh_c,
                    COALESCE(SUM(CASE WHEN id_voyage IS NOT NULL THEN total_ttc END),0) AS rv_c,
                    0 AS rh_v, COUNT(*) AS nb
                FROM reservation
                WHERE statut IN ('CONFIRMEE','TERMINEE')
                  AND date_reservation >= NOW()-INTERVAL '12 months'
                GROUP BY TO_CHAR(date_reservation,'YYYY-MM')
                UNION ALL
                SELECT TO_CHAR(created_at,'YYYY-MM'), 0, 0, COALESCE(SUM(total_ttc),0), COUNT(*)
                FROM reservation_visiteur
                WHERE statut IN ('CONFIRMEE','TERMINEE')
                  AND created_at >= NOW()-INTERVAL '12 months'
                GROUP BY TO_CHAR(created_at,'YYYY-MM')
            ) x GROUP BY periode ORDER BY periode DESC
        """)

        # Top 10 hotels
        top_hotels = db_fetch("""
            SELECT h.nom, h.ville, h.etoiles,
                COALESCE(c.nb,0)+COALESCE(v.nb,0) AS nb_reservations,
                COALESCE(c.ca,0)+COALESCE(v.ca,0) AS ca,
                ROUND((COALESCE(c.ca,0)+COALESCE(v.ca,0))*10.0/100,2) AS commission_agence,
                ROUND((COALESCE(c.ca,0)+COALESCE(v.ca,0))*90.0/100,2) AS part_partenaire
            FROM hotel h
            LEFT JOIN (
                SELECT ch.id_hotel, COUNT(DISTINCT r.id) AS nb, COALESCE(SUM(r.total_ttc),0) AS ca
                FROM reservation r
                JOIN ligne_reservation_chambre lrc ON lrc.id_reservation=r.id
                JOIN chambre ch ON ch.id=lrc.id_chambre
                WHERE r.id_voyage IS NULL AND r.statut IN ('CONFIRMEE','TERMINEE')
                GROUP BY ch.id_hotel
            ) c ON c.id_hotel=h.id
            LEFT JOIN (
                SELECT ch.id_hotel, COUNT(DISTINCT rv.id) AS nb, COALESCE(SUM(rv.total_ttc),0) AS ca
                FROM reservation_visiteur rv JOIN chambre ch ON ch.id=rv.id_chambre
                WHERE rv.statut IN ('CONFIRMEE','TERMINEE')
                GROUP BY ch.id_hotel
            ) v ON v.id_hotel=h.id
            ORDER BY ca DESC LIMIT 10
        """)

        # Top 10 partenaires — colonne statut (pas statut_commission)
        top_partenaires = db_fetch("""
            SELECT u.nom||' '||u.prenom AS partenaire_nom, p.nom_entreprise,
                COUNT(DISTINCT h.id) AS nb_hotels,
                COALESCE(SUM(cp.montant_commission),0) AS total_commissions,
                COALESCE(SUM(CASE WHEN cp.statut='EN_ATTENTE'
                    THEN cp.montant_commission END),0) AS solde_en_attente
            FROM utilisateur u
            JOIN partenaire p ON p.id=u.id
            LEFT JOIN hotel h ON h.id_partenaire=u.id
            LEFT JOIN commission_partenaire cp ON cp.id_partenaire=u.id
            WHERE u.role='PARTENAIRE'
            GROUP BY u.id, p.nom_entreprise
            ORDER BY total_commissions DESC LIMIT 10
        """)

        return json.dumps({
            "ok": True,
            "global": global_kpis,
            "commissions": commissions,
            "revenus_mensuels": revenus_mensuels,
            "top_hotels": top_hotels,
            "top_partenaires": top_partenaires,
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Lister les commissions en attente — clients ET visiteurs combinés. "
    "Filtres : statut ('EN_ATTENTE'|'PAYEE'), partenaire_email, "
    "date_debut, date_fin (YYYY-MM-DD), limit (defaut 50 par source). "
    "Retourne la liste unifiée avec source (client|visiteur), "
    "partenaire_nom, hotel_nom, montant_commission, montant_partenaire, statut, date_creation. "
    "Retourne aussi les totaux groupes par partenaire."
))
def admin_finances_commissions(
    statut:           str = None,
    partenaire_email: str = None,
    date_debut:       str = None,
    date_fin:         str = None,
    limit:            int = 50,
) -> str:
    try:
        # ── Clients (commission_partenaire) ──────────────────────────────
        w_c, p_c = [], []
        if statut:           w_c.append("cp.statut=%s");            p_c.append(statut)
        if partenaire_email: w_c.append("u.email ILIKE %s");        p_c.append(f"%{partenaire_email}%")
        if date_debut:       w_c.append("cp.date_creation>=%s");    p_c.append(date_debut)
        if date_fin:         w_c.append("cp.date_creation<=%s");    p_c.append(date_fin)
        where_c = ("WHERE " + " AND ".join(w_c)) if w_c else ""
        p_c.append(limit)

        rows_c = db_fetch(f"""
            SELECT
                'client'               AS source,
                u.nom||' '||u.prenom    AS partenaire_nom,
                u.email                 AS partenaire_email,
                p.nom_entreprise,
                h.nom                   AS hotel_nom,
                cp.montant_total_resa   AS montant_total,
                cp.taux_commission,
                cp.montant_commission,
                cp.montant_partenaire,
                cp.statut,
                cp.date_creation,
                cp.date_paiement
            FROM commission_partenaire cp
            JOIN utilisateur u  ON u.id=cp.id_partenaire
            JOIN partenaire p   ON p.id=cp.id_partenaire
            LEFT JOIN reservation r ON r.id=cp.id_reservation
            LEFT JOIN ligne_reservation_chambre lrc ON lrc.id_reservation=r.id
            LEFT JOIN chambre c  ON c.id=lrc.id_chambre
            LEFT JOIN hotel h   ON h.id=c.id_hotel
            {where_c}
            ORDER BY cp.date_creation DESC LIMIT %s
        """, *p_c)

        # ── Visiteurs (commission_visiteur) ──────────────────────────────
        w_v, p_v = [], []
        if statut:           w_v.append("cv.statut=%s");            p_v.append(statut)
        if partenaire_email: w_v.append("u.email ILIKE %s");        p_v.append(f"%{partenaire_email}%")
        if date_debut:       w_v.append("cv.date_creation>=%s");    p_v.append(date_debut)
        if date_fin:         w_v.append("cv.date_creation<=%s");    p_v.append(date_fin)
        where_v = ("WHERE " + " AND ".join(w_v)) if w_v else ""
        p_v.append(limit)

        rows_v = db_fetch(f"""
            SELECT
                'visiteur'            AS source,
                u.nom||' '||u.prenom   AS partenaire_nom,
                u.email                AS partenaire_email,
                p.nom_entreprise,
                h.nom                  AS hotel_nom,
                cv.montant_total       AS montant_total,
                cv.taux_commission,
                cv.montant_commission,
                cv.montant_partenaire,
                cv.statut,
                cv.date_creation,
                cv.date_paiement
            FROM commission_visiteur cv
            JOIN utilisateur u  ON u.id=cv.id_partenaire
            JOIN partenaire p   ON p.id=cv.id_partenaire
            LEFT JOIN reservation_visiteur rv ON rv.id=cv.id_reservation_visiteur
            LEFT JOIN chambre c  ON c.id=rv.id_chambre
            LEFT JOIN hotel h   ON h.id=c.id_hotel
            {where_v}
            ORDER BY cv.date_creation DESC LIMIT %s
        """, *p_v)

        # ── Combinaison ──────────────────────────────────────────────────
        all_rows = rows_c + rows_v
        all_rows.sort(key=lambda x: str(x.get("date_creation","")), reverse=True)

        # Totaux groupés par partenaire
        from collections import defaultdict
        par_partenaire = defaultdict(lambda: {
            "nb_clients":0,"nb_visiteurs":0,
            "commission_clients":0.0,"commission_visiteurs":0.0,
            "partenaire_clients":0.0,"partenaire_visiteurs":0.0,
        })
        for r in all_rows:
            nom = r["partenaire_nom"]
            src = r["source"]
            comm = float(r.get("montant_commission") or 0)
            part = float(r.get("montant_partenaire") or 0)
            if src == "client":
                par_partenaire[nom]["nb_clients"] += 1
                par_partenaire[nom]["commission_clients"] += comm
                par_partenaire[nom]["partenaire_clients"] += part
            else:
                par_partenaire[nom]["nb_visiteurs"] += 1
                par_partenaire[nom]["commission_visiteurs"] += comm
                par_partenaire[nom]["partenaire_visiteurs"] += part

        resume = []
        for nom, v in par_partenaire.items():
            resume.append({
                "partenaire_nom":        nom,
                "nb_total":              v["nb_clients"]+v["nb_visiteurs"],
                "nb_clients":            v["nb_clients"],
                "nb_visiteurs":          v["nb_visiteurs"],
                "commission_totale":     round(v["commission_clients"]+v["commission_visiteurs"],2),
                "commission_clients":    round(v["commission_clients"],2),
                "commission_visiteurs":  round(v["commission_visiteurs"],2),
                "part_partenaire_totale":round(v["partenaire_clients"]+v["partenaire_visiteurs"],2),
                "part_partenaire_clients":  round(v["partenaire_clients"],2),
                "part_partenaire_visiteurs":round(v["partenaire_visiteurs"],2),
            })

        total_commission = sum(float(r.get("montant_commission") or 0) for r in all_rows)
        total_partenaire = sum(float(r.get("montant_partenaire") or 0) for r in all_rows)

        return json.dumps({
            "ok":              True,
            "total":           len(all_rows),
            "total_clients":   len(rows_c),
            "total_visiteurs": len(rows_v),
            "total_commission": round(total_commission, 2),
            "total_partenaire": round(total_partenaire, 2),
            "resume_par_partenaire": resume,
            "detail": all_rows[:limit],
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)



@mcp.tool(description=(
    "Soldes a payer aux partenaires — correspond exactement a l'onglet Soldes a payer du frontend. "
    "Calcul : solde_du = (revenu_hotel × 90%) − montant_deja_paye. "
    "Inclut clients ET visiteurs. "
    "Utiliser pour : qui doit etre paye, combien on doit, soldes en attente, partenaires non payes."
))
def admin_finances_soldes() -> str:
    try:
        # Verifier si commission_visiteur existe
        from easyvoyage_mcp.database import db_fetchrow as _dbr
        has_cv = False
        try:
            _dbr("SELECT 1 FROM commission_visiteur LIMIT 1")
            has_cv = True
        except Exception:
            has_cv = False

        if has_cv:
            rows = db_fetch("""
                SELECT
                    u.nom||' '||u.prenom     AS partenaire_nom,
                    u.email                  AS partenaire_email,
                    p.nom_entreprise,
                    COALESCE(rh.ca,0)        AS revenu_hotel,
                    ROUND(COALESCE(rh.ca,0)*10.0/100,2) AS commission_agence,
                    ROUND(COALESCE(rh.ca,0)*90.0/100,2) AS part_partenaire,
                    COALESCE(pp.montant_paye,0) AS montant_deja_paye,
                    GREATEST(0, ROUND(COALESCE(rh.ca,0)*90.0/100,2) - COALESCE(pp.montant_paye,0)) AS solde_du,
                    COALESCE(cp_c.nb,0)+COALESCE(cp_v.nb,0) AS nb_commissions_en_attente
                FROM utilisateur u
                JOIN partenaire p ON p.id=u.id
                LEFT JOIN (
                    SELECT h.id_partenaire,
                        COALESCE(SUM(r_ca.ca),0)+COALESCE(SUM(rv_ca.ca),0) AS ca
                    FROM hotel h
                    LEFT JOIN (
                        SELECT ch.id_hotel, COALESCE(SUM(r.total_ttc),0) AS ca
                        FROM reservation r
                        JOIN ligne_reservation_chambre lrc ON lrc.id_reservation=r.id
                        JOIN chambre ch ON ch.id=lrc.id_chambre
                        WHERE r.id_voyage IS NULL AND r.statut IN ('CONFIRMEE','TERMINEE')
                        GROUP BY ch.id_hotel
                    ) r_ca ON r_ca.id_hotel=h.id
                    LEFT JOIN (
                        SELECT ch.id_hotel, COALESCE(SUM(rv.total_ttc),0) AS ca
                        FROM reservation_visiteur rv JOIN chambre ch ON ch.id=rv.id_chambre
                        WHERE rv.statut IN ('CONFIRMEE','TERMINEE')
                        GROUP BY ch.id_hotel
                    ) rv_ca ON rv_ca.id_hotel=h.id
                    GROUP BY h.id_partenaire
                ) rh ON rh.id_partenaire=u.id
                LEFT JOIN (
                    SELECT id_partenaire, COALESCE(SUM(montant),0) AS montant_paye
                    FROM paiement_partenaire GROUP BY id_partenaire
                ) pp ON pp.id_partenaire=u.id
                LEFT JOIN (
                    SELECT id_partenaire, COUNT(*) AS nb
                    FROM commission_partenaire WHERE statut='EN_ATTENTE'
                    GROUP BY id_partenaire
                ) cp_c ON cp_c.id_partenaire=u.id
                LEFT JOIN (
                    SELECT cv.id_partenaire, COUNT(*) AS nb
                    FROM commission_visiteur cv WHERE cv.statut='EN_ATTENTE'
                    GROUP BY cv.id_partenaire
                ) cp_v ON cp_v.id_partenaire=u.id
                WHERE u.role='PARTENAIRE'
                  AND GREATEST(0, ROUND(COALESCE(rh.ca,0)*90.0/100,2) - COALESCE(pp.montant_paye,0)) > 0
                ORDER BY solde_du DESC
            """)
        else:
            # Sans commission_visiteur
            rows = db_fetch("""
                SELECT
                    u.nom||' '||u.prenom     AS partenaire_nom,
                    u.email                  AS partenaire_email,
                    p.nom_entreprise,
                    COALESCE(rh.ca,0)        AS revenu_hotel,
                    ROUND(COALESCE(rh.ca,0)*10.0/100,2) AS commission_agence,
                    ROUND(COALESCE(rh.ca,0)*90.0/100,2) AS part_partenaire,
                    COALESCE(pp.montant_paye,0) AS montant_deja_paye,
                    GREATEST(0, ROUND(COALESCE(rh.ca,0)*90.0/100,2) - COALESCE(pp.montant_paye,0)) AS solde_du,
                    COALESCE(cp.nb,0) AS nb_commissions_en_attente
                FROM utilisateur u
                JOIN partenaire p ON p.id=u.id
                LEFT JOIN (
                    SELECT h.id_partenaire,
                        COALESCE(SUM(r_ca.ca),0)+COALESCE(SUM(rv_ca.ca),0) AS ca
                    FROM hotel h
                    LEFT JOIN (
                        SELECT ch.id_hotel, COALESCE(SUM(r.total_ttc),0) AS ca
                        FROM reservation r
                        JOIN ligne_reservation_chambre lrc ON lrc.id_reservation=r.id
                        JOIN chambre ch ON ch.id=lrc.id_chambre
                        WHERE r.id_voyage IS NULL AND r.statut IN ('CONFIRMEE','TERMINEE')
                        GROUP BY ch.id_hotel
                    ) r_ca ON r_ca.id_hotel=h.id
                    LEFT JOIN (
                        SELECT ch.id_hotel, COALESCE(SUM(rv.total_ttc),0) AS ca
                        FROM reservation_visiteur rv JOIN chambre ch ON ch.id=rv.id_chambre
                        WHERE rv.statut IN ('CONFIRMEE','TERMINEE')
                        GROUP BY ch.id_hotel
                    ) rv_ca ON rv_ca.id_hotel=h.id
                    GROUP BY h.id_partenaire
                ) rh ON rh.id_partenaire=u.id
                LEFT JOIN (
                    SELECT id_partenaire, COALESCE(SUM(montant),0) AS montant_paye
                    FROM paiement_partenaire GROUP BY id_partenaire
                ) pp ON pp.id_partenaire=u.id
                LEFT JOIN (
                    SELECT id_partenaire, COUNT(*) AS nb
                    FROM commission_partenaire WHERE statut='EN_ATTENTE'
                    GROUP BY id_partenaire
                ) cp ON cp.id_partenaire=u.id
                WHERE u.role='PARTENAIRE'
                  AND GREATEST(0, ROUND(COALESCE(rh.ca,0)*90.0/100,2) - COALESCE(pp.montant_paye,0)) > 0
                ORDER BY solde_du DESC
            """)

        total_a_payer = sum(float(r.get("solde_du") or 0) for r in rows)

        return json.dumps({
            "ok": True,
            "total_partenaires": len(rows),
            "total_a_payer": round(total_a_payer, 2),
            "data": rows,
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)