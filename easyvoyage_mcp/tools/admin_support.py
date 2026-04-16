"""
mcp/tools/admin_support.py
===========================
Tools MCP — Support partenaire ↔ admin.
Correspond à : AdminSupport.jsx

Tools :
  admin_support_conversations → liste des conversations avec filtres
  admin_support_messages      → messages d'une conversation
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les conversations support — page AdminSupport. "
    "Filtres : statut ('EN_ATTENTE'|'ACCEPTEE'|'FERMEE'), "
    "partenaire_id (int), search (sujet / nom partenaire / email), "
    "limit (int, défaut 30). "
    "Retourne : id, sujet, statut, created_at, updated_at, "
    "partenaire_id, partenaire_nom, partenaire_email, admin_nom, "
    "nb_messages, nb_non_lus. "
    "Trié : EN_ATTENTE en premier, puis ACCEPTEE, puis FERMEE."
))
def admin_support_conversations(
    statut:        str = None,
    partenaire_id: int = None,
    search:        str = None,
    limit:         int = 30,
) -> str:
    try:
        wheres, params = [], []
        if statut:
            wheres.append("sc.statut = %s"); params.append(statut)
        if partenaire_id:
            wheres.append("sc.id_partenaire = %s"); params.append(partenaire_id)
        if search:
            wheres.append(
                "(sc.sujet ILIKE %s OR up.nom ILIKE %s OR up.email ILIKE %s)"
            )
            params += [f"%{search}%"] * 3
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                sc.id, sc.sujet, sc.statut,
                sc.created_at, sc.updated_at,
                up.id   AS partenaire_id,
                up.nom || ' ' || up.prenom AS partenaire_nom,
                up.email                   AS partenaire_email,
                ua.nom || ' ' || ua.prenom AS admin_nom,
                COUNT(sm.id)               AS nb_messages,
                COUNT(
                    CASE WHEN sm.lu = false
                         AND sm.id_expediteur = up.id THEN 1 END
                ) AS nb_non_lus
            FROM support_conversation sc
            JOIN utilisateur up ON up.id = sc.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id = sc.id_admin
            LEFT JOIN support_message sm ON sm.id_conversation = sc.id
            {where_sql}
            GROUP BY sc.id, up.id, up.nom, up.prenom, up.email, ua.nom, ua.prenom
            ORDER BY
                CASE sc.statut
                    WHEN 'EN_ATTENTE' THEN 0
                    WHEN 'ACCEPTEE'   THEN 1
                    ELSE 2
                END,
                sc.updated_at DESC
            LIMIT %s
        """, *params)

        nb_en_attente = sum(1 for r in rows if r.get("statut") == "EN_ATTENTE")

        return json.dumps({
            "ok":            True,
            "total":         len(rows),
            "nb_en_attente": nb_en_attente,
            "data":          rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Lire tous les messages d'une conversation support par son ID. "
    "Paramètre : conversation_id (int). "
    "Retourne : infos de la conversation (sujet, statut, noms), "
    "liste complète des messages triés par date croissante "
    "(contenu, lu, created_at, expediteur_nom, expediteur_role)."
))
def admin_support_messages(conversation_id: int) -> str:
    try:
        conv = db_fetchrow("""
            SELECT
                sc.id, sc.sujet, sc.statut,
                up.nom || ' ' || up.prenom AS partenaire_nom,
                up.email                   AS partenaire_email,
                ua.nom || ' ' || ua.prenom AS admin_nom
            FROM support_conversation sc
            JOIN utilisateur up ON up.id = sc.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id = sc.id_admin
            WHERE sc.id = %s
        """, conversation_id)
        if not conv:
            return json.dumps({"ok": False, "error": f"Conversation {conversation_id} introuvable"})

        messages = db_fetch("""
            SELECT
                sm.id, sm.contenu, sm.lu, sm.created_at,
                u.nom || ' ' || u.prenom AS expediteur_nom,
                u.role                   AS expediteur_role
            FROM support_message sm
            JOIN utilisateur u ON u.id = sm.id_expediteur
            WHERE sm.id_conversation = %s
            ORDER BY sm.created_at ASC
        """, conversation_id)

        return json.dumps({
            "ok":           True,
            "conversation": conv,
            "nb_messages":  len(messages),
            "messages":     messages,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)