"""
mcp/tools/admin_factures.py
=============================
VERSION CORRIGÉE — noms de colonnes alignés sur le modèle Facture

Tools MCP — Gestion des factures.
Correspond à : AdminFactures.jsx

Tools :
  admin_factures_liste → liste unifiée (clients + visiteurs) avec filtres

BUG CORRIGÉ :
  Les colonnes référencées dans le SQL ne correspondaient pas au modèle ORM :

    Ancien SQL (FAUX)     →  Nom réel de la colonne
    ─────────────────────    ──────────────────────────
    f.total_ht            →  f.montant_ht
    f.tva                 →  f.tva_montant
    f.total_ttc           →  f.montant_total

  Schéma complet : voir app/models/reservation.py (class Facture)
    Colonnes réelles :
      id, numero, date_emission, montant_total, montant_ht,
      taxe_sejour, tva_montant, taux_tva, droit_timbre,
      nb_nuits_taxables, statut, fichier_pdf, id_reservation,
      created_at, updated_at

  NOTE : la table facture a id_reservation mais pas id_reservation_visiteur.
  La liaison visiteur se fait via ReservationVisiteur.id_facture → facture.id
  (voir app/models/reservation.py).
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les factures — page AdminFactures. "
    "Fusionne factures clients ET visiteurs. "
    "Filtres : type ('client'|'visiteur', None = les deux), "
    "statut (str: EMISE|PAYEE|ANNULEE|EN_RETARD), "
    "search (numero facture / nom client / email), "
    "date_debut (YYYY-MM-DD), date_fin (YYYY-MM-DD), limit (int, defaut 50). "
    "Retourne : id, type, numero, statut, montant_ht, tva_montant, "
    "taxe_sejour, droit_timbre, montant_total, date_emission, "
    "client_nom, client_email. "
    "Retourne aussi montant_total_cumul agrege de la selection."
))
def admin_factures_liste(
    type:       str = None,
    statut:     str = None,
    search:     str = None,
    date_debut: str = None,
    date_fin:   str = None,
    limit:      int = 50,
) -> str:
    try:
        results = []

        # ═════════════════════════════════════════════════════════
        #  FACTURES CLIENTS
        #  (facture.id_reservation NOT NULL)
        # ═════════════════════════════════════════════════════════
        if type in (None, "", "client"):
            w, p = ["f.id_reservation IS NOT NULL"], []
            if statut:     w.append("CAST(f.statut AS VARCHAR) = %s"); p.append(statut)
            if date_debut: w.append("f.date_emission >= %s");          p.append(date_debut)
            if date_fin:   w.append("f.date_emission <= %s");          p.append(date_fin)
            if search:
                w.append("(f.numero ILIKE %s OR u.nom ILIKE %s OR u.email ILIKE %s)")
                p += [f"%{search}%"] * 3
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    'client'                       AS type,
                    f.numero,
                    CAST(f.statut AS VARCHAR)      AS statut,
                    f.montant_ht,
                    f.tva_montant,
                    f.taxe_sejour,
                    f.droit_timbre,
                    f.montant_total,
                    f.date_emission,
                    u.nom || ' ' || u.prenom       AS client_nom,
                    u.email                        AS client_email
                FROM facture f
                JOIN reservation r   ON r.id = f.id_reservation
                JOIN utilisateur u   ON u.id = r.id_client
                WHERE {' AND '.join(w)}
                ORDER BY f.date_emission DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        # ═════════════════════════════════════════════════════════
        #  FACTURES VISITEURS
        #  (facture liee via reservation_visiteur.id_facture = f.id)
        # ═════════════════════════════════════════════════════════
        if type in (None, "", "visiteur"):
            w, p = ["rv.id IS NOT NULL"], []
            if statut:     w.append("CAST(f.statut AS VARCHAR) = %s"); p.append(statut)
            if date_debut: w.append("f.date_emission >= %s");          p.append(date_debut)
            if date_fin:   w.append("f.date_emission <= %s");          p.append(date_fin)
            if search:
                w.append("(f.numero ILIKE %s OR rv.nom ILIKE %s OR rv.email ILIKE %s)")
                p += [f"%{search}%"] * 3
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    'visiteur'                     AS type,
                    f.numero,
                    CAST(f.statut AS VARCHAR)      AS statut,
                    f.montant_ht,
                    f.tva_montant,
                    f.taxe_sejour,
                    f.droit_timbre,
                    f.montant_total,
                    f.date_emission,
                    rv.nom || ' ' || rv.prenom     AS client_nom,
                    rv.email                       AS client_email,
                    rv.numero_voucher
                FROM facture f
                JOIN reservation_visiteur rv ON rv.id_facture = f.id
                WHERE {' AND '.join(w)}
                ORDER BY f.date_emission DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        # Tri final et troncature
        results.sort(key=lambda x: str(x.get("date_emission") or ""), reverse=True)
        results = results[:limit]

        montant_total_cumul = sum(float(r.get("montant_total") or 0) for r in results)

        return json.dumps({
            "ok":                   True,
            "total":                len(results),
            "montant_total_cumul":  round(montant_total_cumul, 2),
            "data":                 results,
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)