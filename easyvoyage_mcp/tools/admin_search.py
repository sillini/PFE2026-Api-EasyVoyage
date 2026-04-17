"""
mcp/tools/admin_search.py
==========================
VERSION CORRIGÉE — noms de colonnes alignés sur les modèles ORM

Tools MCP — Recherche globale transversale.
Utilitaire admin : cherche sur toutes les tables en une seule requête.

Tools :
  admin_recherche_globale → hôtels + clients + partenaires + factures + promotions

═══════════════════════════════════════════════════════════════════
BUGS CORRIGÉS
═══════════════════════════════════════════════════════════════════
  v1 → v2 :
    - f.total_ttc  →  f.montant_total       (voir modèle Facture)
    - p.statut (promotion) est un enum PostgreSQL → CAST nécessaire
    - Ajout du CAST pour u.role (enum PostgreSQL) dans le WHERE clients
    - Défense anti-filtre-fantôme (chaîne vide → résultat vide normal)
    - Suppression des IDs techniques du retour (interdits par le prompt)
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Recherche globale sur toute la plateforme par mot-cle. "
    "Cherche simultanement dans : "
    "hotels (nom/ville), clients (nom/prenom/email), "
    "partenaires (nom/prenom/email/nom_entreprise), "
    "factures (numero), promotions (titre). "
    "Parametres : keyword (str), limit_per_category (int, defaut 5). "
    "Retourne les resultats groupes par categorie + total_resultats global."
))
def admin_recherche_globale(keyword: str, limit_per_category: int = 5) -> str:
    try:
        # Defense anti-filtre-fantome
        if not keyword or (isinstance(keyword, str) and keyword.strip() == ""):
            return json.dumps({
                "ok": False,
                "error": "Le mot-cle de recherche est obligatoire et ne peut pas etre vide."
            }, indent=2)

        keyword = keyword.strip()
        like = f"%{keyword}%"

        # Borner limit_per_category entre 1 et 20
        try:
            limit_per_category = int(limit_per_category) if limit_per_category else 5
            limit_per_category = max(1, min(limit_per_category, 20))
        except (ValueError, TypeError):
            limit_per_category = 5

        # ─────────────────────────────────────────────────────────
        #  HOTELS
        # ─────────────────────────────────────────────────────────
        hotels = db_fetch("""
            SELECT
                nom,
                ville,
                pays,
                etoiles,
                actif
            FROM hotel
            WHERE nom ILIKE %s OR ville ILIKE %s
            ORDER BY actif DESC, nom ASC
            LIMIT %s
        """, like, like, limit_per_category)

        # ─────────────────────────────────────────────────────────
        #  CLIENTS (role est un enum PostgreSQL → CAST)
        # ─────────────────────────────────────────────────────────
        clients = db_fetch("""
            SELECT
                nom,
                prenom,
                email,
                telephone,
                actif
            FROM utilisateur
            WHERE CAST(role AS VARCHAR) = 'CLIENT'
              AND (nom ILIKE %s OR prenom ILIKE %s OR email ILIKE %s)
            ORDER BY nom ASC
            LIMIT %s
        """, like, like, like, limit_per_category)

        # ─────────────────────────────────────────────────────────
        #  PARTENAIRES
        # ─────────────────────────────────────────────────────────
        partenaires = db_fetch("""
            SELECT
                u.nom,
                u.prenom,
                u.email,
                p.nom_entreprise,
                p.type_partenaire,
                p.statut
            FROM utilisateur u
            JOIN partenaire p ON p.id = u.id
            WHERE u.nom ILIKE %s
               OR u.prenom ILIKE %s
               OR u.email ILIKE %s
               OR p.nom_entreprise ILIKE %s
            ORDER BY u.nom ASC
            LIMIT %s
        """, like, like, like, like, limit_per_category)

        # ─────────────────────────────────────────────────────────
        #  FACTURES
        #  ⚠️  montant_total (PAS total_ttc — qui n'existe pas dans facture)
        #  ⚠️  statut est un enum PostgreSQL → CAST
        # ─────────────────────────────────────────────────────────
        factures = db_fetch("""
            SELECT
                f.numero,
                CAST(f.statut AS VARCHAR)  AS statut,
                f.montant_total,
                f.date_emission,
                f.created_at
            FROM facture f
            WHERE f.numero ILIKE %s
            ORDER BY f.date_emission DESC
            LIMIT %s
        """, like, limit_per_category)

        # ─────────────────────────────────────────────────────────
        #  PROMOTIONS
        #  ⚠️  statut est un enum PostgreSQL → CAST
        # ─────────────────────────────────────────────────────────
        promotions = db_fetch("""
            SELECT
                p.titre,
                CAST(p.statut AS VARCHAR)  AS statut,
                p.pourcentage,
                p.actif,
                p.date_debut,
                p.date_fin,
                h.nom                      AS hotel_nom,
                h.ville                    AS hotel_ville
            FROM promotion p
            LEFT JOIN hotel h ON h.id = p.id_hotel
            WHERE p.titre ILIKE %s
            ORDER BY p.created_at DESC
            LIMIT %s
        """, like, limit_per_category)

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