"""
mcp/tools/admin_support.py — recherche par email/sujet (jamais par ID)
"""
import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


@mcp.tool(description=(
    "Lister les conversations support. "
    "Filtres : statut (EN_ATTENTE|ACCEPTEE|RESOLUE|FERMEE), "
    "search (sujet ou email partenaire), limit (defaut 50)."
))
def admin_support_conversations(statut: str=None, search: str=None, limit: int=50) -> str:
    try:
        w, p = [], []
        if statut: w.append("sc.statut=%s"); p.append(statut)
        if search:
            w.append("(sc.sujet ILIKE %s OR up.email ILIKE %s OR up.nom ILIKE %s OR up.prenom ILIKE %s)")
            p += [f"%{search}%"]*4
        where_sql = ("WHERE "+" AND ".join(w)) if w else ""
        p.append(limit)

        rows = db_fetch(f"""
            SELECT sc.sujet, sc.statut, sc.created_at, sc.updated_at,
                up.nom||' '||up.prenom AS partenaire_nom,
                up.email               AS partenaire_email,
                ua.nom||' '||ua.prenom AS admin_nom,
                sc.id AS _cid
            FROM support_conversation sc
            JOIN utilisateur up ON up.id=sc.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id=sc.id_admin
            {where_sql}
            ORDER BY sc.updated_at DESC LIMIT %s
        """, *p)

        for r in rows: r.pop("_cid", None)
        return json.dumps({"ok": True, "total": len(rows), "data": rows}, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool(description=(
    "Lire les messages d'une conversation support par EMAIL du partenaire ou SUJET. "
    "Parametre : partenaire_email (email) OU sujet (texte partiel du sujet). "
    "Retourne tous les messages de la conversation."
))
def admin_support_messages(partenaire_email: str=None, sujet: str=None) -> str:
    try:
        if not partenaire_email and not sujet:
            return json.dumps({"ok": False, "error": "Fournir partenaire_email ou sujet"})

        w, p = [], []
        if partenaire_email:
            w.append("up.email ILIKE %s"); p.append(f"%{partenaire_email}%")
        if sujet:
            w.append("sc.sujet ILIKE %s"); p.append(f"%{sujet}%")
        where_sql = "WHERE " + " AND ".join(w)

        conv = db_fetchrow(f"""
            SELECT sc.sujet, sc.statut, sc.id AS _cid,
                up.nom||' '||up.prenom AS partenaire_nom,
                up.email               AS partenaire_email,
                ua.nom||' '||ua.prenom AS admin_nom
            FROM support_conversation sc
            JOIN utilisateur up ON up.id=sc.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id=sc.id_admin
            {where_sql}
            ORDER BY sc.updated_at DESC LIMIT 1
        """, *p)

        if not conv:
            return json.dumps({"ok": False, "error": "Aucune conversation trouvée"})

        cid = conv.pop("_cid")

        messages = db_fetch("""
            SELECT sm.contenu, sm.lu, sm.created_at,
                u.nom||' '||u.prenom AS expediteur_nom,
                CAST(u.role AS VARCHAR) AS expediteur_role
            FROM support_message sm
            JOIN utilisateur u ON u.id=sm.id_expediteur
            WHERE sm.id_conversation=%s
            ORDER BY sm.created_at ASC
        """, cid)

        return json.dumps({
            "ok": True, "conversation": conv,
            "nb_messages": len(messages), "messages": messages,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)