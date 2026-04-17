"""
mcp/tools/admin_fiscal.py
==========================
VERSION CORRIGÉE — bon nom de table (fiscal_rules, pas regle_fiscale)

Tools MCP — Règles fiscales.
Correspond à : FiscalConfig.jsx

Tools :
  admin_fiscal_regles → toutes les règles (TVA, taxe séjour, droit timbre)

═══════════════════════════════════════════════════════════════════
SCHÉMA RÉEL (voir app/models/fiscal.py)
═══════════════════════════════════════════════════════════════════

  Table: fiscal_rules   ⚠️  Le nom réel est "fiscal_rules" (PAS "regle_fiscale")
  ──────────────────
    id, cle, libelle, valeur, type_valeur, description, actif,
    nb_nuits_max, etoiles_min, etoiles_max, created_at, updated_at

  ⚠️  L'ancien code utilisait : type_taxe, taux, conditions_application
      qui N'EXISTENT PAS. Les vraies colonnes sont :
        - cle          (identifiant metier: "tva", "taxe_sejour_2_3"...)
        - libelle      (texte affiche)
        - valeur       (montant ou pourcentage)
        - type_valeur  (PAR_NUIT | POURCENTAGE | MONTANT_FIXE)

  Exemples de règles en base :
    cle='tva'               libelle='TVA 7%'                     valeur=7.0  type_valeur='POURCENTAGE'
    cle='taxe_sejour_2_3'   libelle='Taxe sejour 2-3 etoiles'    valeur=2.0  type_valeur='PAR_NUIT'
    cle='taxe_sejour_4_5'   libelle='Taxe sejour 4-5 etoiles'    valeur=3.0  type_valeur='PAR_NUIT'
    cle='droit_timbre'      libelle='Droit de timbre'             valeur=1.0  type_valeur='MONTANT_FIXE'
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lire les regles fiscales configurees — page FiscalConfig. "
    "Retourne toutes les regles actives et inactives : "
    "id, cle (tva | taxe_sejour_2_3 | taxe_sejour_4_5 | droit_timbre), "
    "libelle, valeur, type_valeur (PAR_NUIT | POURCENTAGE | MONTANT_FIXE), "
    "description, actif, nb_nuits_max, etoiles_min, etoiles_max, "
    "created_at, updated_at. "
    "Parametre optionnel : actif (bool) — filtrer actives/inactives. "
    "Sans parametre : retourne tout, triees par cle."
))
def admin_fiscal_regles(actif: bool = None) -> str:
    try:
        # Defense anti-filtre-fantome : on applique actif uniquement si True/False explicite
        where_sql = ""
        params    = []
        if actif is True or actif is False:
            where_sql = "WHERE actif = %s"
            params.append(actif)

        rows = db_fetch(f"""
            SELECT
                id,
                cle,
                libelle,
                valeur,
                type_valeur,
                description,
                actif,
                nb_nuits_max,
                etoiles_min,
                etoiles_max,
                created_at,
                updated_at
            FROM fiscal_rules
            {where_sql}
            ORDER BY actif DESC, cle ASC
        """, *params)

        # Stats globales
        stats = db_fetch("""
            SELECT
                COUNT(*)                          AS total,
                COUNT(*) FILTER (WHERE actif)     AS nb_actives,
                COUNT(*) FILTER (WHERE NOT actif) AS nb_inactives
            FROM fiscal_rules
        """)
        stats_globales = dict(stats[0]) if stats else {}

        return json.dumps({
            "ok":             True,
            "total_filtre":   len(rows),
            "stats_globales": stats_globales,
            "data":           rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)