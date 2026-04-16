"""
mcp/tools/admin_factures.py
=============================
Tools MCP — Gestion des factures.
Correspond à : AdminFactures.jsx

Tools :
  admin_factures_liste → liste unifiée (clients + visiteurs) avec filtres
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
    "search (numéro facture / nom client / email), "
    "date_debut (YYYY-MM-DD), date_fin (YYYY-MM-DD), limit (int, défaut 50). "
    "Retourne : id, type, numero, statut, total_ht, tva, total_ttc, "
    "created_at, client_nom, client_email, reservation_id. "
    "Retourne aussi total_ttc agrégé de la sélection."
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

        # ── Factures clients ──────────────────────────────
        if type in (None, "client"):
            w, p = ["f.id_reservation IS NOT NULL"], []
            if statut:     w.append("f.statut = %s");      p.append(statut)
            if date_debut: w.append("f.created_at >= %s"); p.append(date_debut)
            if date_fin:   w.append("f.created_at <= %s"); p.append(date_fin)
            if search:
                w.append("(f.numero ILIKE %s OR u.nom ILIKE %s OR u.email ILIKE %s)")
                p += [f"%{search}%"] * 3
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    f.id, 'client' AS type,
                    f.numero, f.statut,
                    f.total_ht, f.tva, f.taxe_sejour, f.droit_timbre, f.total_ttc,
                    f.created_at,
                    u.nom || ' ' || u.prenom AS client_nom,
                    u.email                  AS client_email,
                    r.id AS reservation_id
                FROM facture f
                JOIN reservation r   ON r.id = f.id_reservation
                JOIN utilisateur u   ON u.id = r.id_client
                WHERE {' AND '.join(w)}
                ORDER BY f.created_at DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        # ── Factures visiteurs ────────────────────────────
        if type in (None, "visiteur"):
            w, p = ["f.id_reservation_visiteur IS NOT NULL"], []
            if statut:     w.append("f.statut = %s");      p.append(statut)
            if date_debut: w.append("f.created_at >= %s"); p.append(date_debut)
            if date_fin:   w.append("f.created_at <= %s"); p.append(date_fin)
            if search:
                w.append("(f.numero ILIKE %s OR rv.nom ILIKE %s OR rv.email ILIKE %s)")
                p += [f"%{search}%"] * 3
            p.append(limit)

            rows = db_fetch(f"""
                SELECT
                    f.id, 'visiteur' AS type,
                    f.numero, f.statut,
                    f.total_ht, f.tva, f.taxe_sejour, f.droit_timbre, f.total_ttc,
                    f.created_at,
                    rv.nom || ' ' || rv.prenom AS client_nom,
                    rv.email                   AS client_email,
                    rv.id AS reservation_id
                FROM facture f
                JOIN reservation_visiteur rv ON rv.id = f.id_reservation_visiteur
                WHERE {' AND '.join(w)}
                ORDER BY f.created_at DESC
                LIMIT %s
            """, *p)
            results.extend(rows)

        results.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
        results = results[:limit]
        total_ttc = sum(float(r.get("total_ttc") or 0) for r in results)

        return json.dumps({
            "ok":       True,
            "total":    len(results),
            "total_ttc": round(total_ttc, 2),
            "data":     results,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)