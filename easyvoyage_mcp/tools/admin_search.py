"""
mcp/tools/admin_search.py
==========================
Tools MCP — Recherche globale transversale.
Utilitaire admin : cherche sur toutes les tables en une seule requête.

Tools :
  admin_recherche_globale → hôtels + clients + partenaires + factures + promotions
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Recherche globale sur toute la plateforme par mot-clé. "
    "Cherche simultanément dans : "
    "hôtels (nom/ville), clients (nom/prénom/email), "
    "partenaires (nom/prénom/email/nom_entreprise), "
    "factures (numéro), promotions (titre). "
    "Paramètres : keyword (str), limit_per_category (int, défaut 5). "
    "Retourne les résultats groupés par catégorie + total_resultats global."
))
def admin_recherche_globale(keyword: str, limit_per_category: int = 5) -> str:
    try:
        hotels = db_fetch("""
            SELECT id, nom, ville, pays, etoiles, actif
            FROM hotel
            WHERE nom ILIKE %s OR ville ILIKE %s
            LIMIT %s
        """, f"%{keyword}%", f"%{keyword}%", limit_per_category)

        clients = db_fetch("""
            SELECT id, nom, prenom, email, telephone
            FROM utilisateur
            WHERE role = 'CLIENT'
              AND (nom ILIKE %s OR prenom ILIKE %s OR email ILIKE %s)
            LIMIT %s
        """, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit_per_category)

        partenaires = db_fetch("""
            SELECT u.id, u.nom, u.prenom, u.email, p.nom_entreprise, p.statut
            FROM utilisateur u
            JOIN partenaire p ON p.id = u.id
            WHERE u.nom ILIKE %s OR u.prenom ILIKE %s
               OR u.email ILIKE %s OR p.nom_entreprise ILIKE %s
            LIMIT %s
        """, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit_per_category)

        factures = db_fetch("""
            SELECT f.id, f.numero, f.statut, f.total_ttc, f.created_at
            FROM facture f
            WHERE f.numero ILIKE %s
            LIMIT %s
        """, f"%{keyword}%", limit_per_category)

        promotions = db_fetch("""
            SELECT p.id, p.titre, p.statut, p.pourcentage,
                   h.nom AS hotel_nom
            FROM promotion p
            LEFT JOIN hotel h ON h.id = p.id_hotel
            WHERE p.titre ILIKE %s
            LIMIT %s
        """, f"%{keyword}%", limit_per_category)

        total = (
            len(hotels) + len(clients) + len(partenaires)
            + len(factures) + len(promotions)
        )

        return json.dumps({
            "ok":              True,
            "keyword":         keyword,
            "total_resultats": total,
            "hotels":          {"total": len(hotels),      "data": hotels},
            "clients":         {"total": len(clients),     "data": clients},
            "partenaires":     {"total": len(partenaires), "data": partenaires},
            "factures":        {"total": len(factures),    "data": factures},
            "promotions":      {"total": len(promotions),  "data": promotions},
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)