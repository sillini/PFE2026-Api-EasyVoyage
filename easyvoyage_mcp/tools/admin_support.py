"""
mcp/tools/admin_support.py
===========================
VERSION v3 — Recherche UNIQUEMENT par email/nom/sujet (JAMAIS par ID)

Principe : un administrateur ne connait pas les IDs internes. Il connait :
  - l'email du partenaire
  - le nom et prenom du partenaire
  - le sujet de la conversation (texte partiel)

Tools MCP — Support chat partenaire ↔ admin.
Correspond a : AdminSupport.jsx

Tools :
  admin_support_conversations        → lister conversations (filtres texte)
  admin_support_messages             → messages d'UNE conversation par email/sujet
  admin_support_conversations_partenaire → toutes les conversations d'un partenaire
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


# ═══════════════════════════════════════════════════════════
#  1. LISTER LES CONVERSATIONS
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lister les conversations support. "
    "Filtres : "
    "statut (EN_ATTENTE | ACCEPTEE | FERMEE | RESOLUE), "
    "search (cherche dans sujet OU email/nom/prenom du partenaire), "
    "limit (defaut 50). "
    "Retourne : sujet, statut, dates, partenaire_nom, partenaire_email, "
    "admin_nom, nb_messages, nb_non_lus, dernier_message_extrait. "
    "Les IDs techniques ne sont JAMAIS exposes."
))
def admin_support_conversations(
    statut: str = None,
    search: str = None,
    limit:  int = 50,
) -> str:
    try:
        if isinstance(statut, str) and statut.strip() == "": statut = None
        if isinstance(search, str) and search.strip() == "": search = None

        w, p = [], []
        if statut:
            w.append("sc.statut = %s")
            p.append(statut.upper())
        if search:
            w.append("(sc.sujet ILIKE %s OR up.email ILIKE %s OR up.nom ILIKE %s OR up.prenom ILIKE %s)")
            p += [f"%{search}%"] * 4
        where_sql = ("WHERE " + " AND ".join(w)) if w else ""
        p.append(limit)

        rows = db_fetch(f"""
            SELECT
                sc.sujet,
                sc.statut,
                sc.created_at,
                sc.updated_at,
                up.nom || ' ' || up.prenom    AS partenaire_nom,
                up.email                       AS partenaire_email,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS admin_nom,
                ua.email                       AS admin_email,
                (SELECT COUNT(*) FROM voyage_hotel.support_message sm
                 WHERE sm.id_conversation = sc.id)               AS nb_messages,
                (SELECT COUNT(*) FROM voyage_hotel.support_message sm
                 WHERE sm.id_conversation = sc.id AND sm.lu = false) AS nb_non_lus,
                (SELECT LEFT(sm.contenu, 150) FROM voyage_hotel.support_message sm
                 WHERE sm.id_conversation = sc.id
                 ORDER BY sm.created_at DESC LIMIT 1)            AS dernier_message_extrait,
                (SELECT sm.created_at FROM voyage_hotel.support_message sm
                 WHERE sm.id_conversation = sc.id
                 ORDER BY sm.created_at DESC LIMIT 1)            AS dernier_message_date
            FROM voyage_hotel.support_conversation sc
            JOIN utilisateur up     ON up.id = sc.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id = sc.id_admin
            {where_sql}
            ORDER BY sc.updated_at DESC
            LIMIT %s
        """, *p)

        stats = db_fetch("""
            SELECT statut, COUNT(*) AS nb
            FROM voyage_hotel.support_conversation
            GROUP BY statut
        """)
        stats_globales = {r["statut"]: int(r["nb"]) for r in stats}

        return json.dumps({
            "ok": True,
            "total_filtre":   len(rows),
            "stats_globales": stats_globales,
            "data":           rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════
#  2. MESSAGES D'UNE CONVERSATION — par email OU sujet
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lire l'historique complet des messages d'UNE conversation support. "
    "IMPORTANT : la conversation s'identifie UNIQUEMENT par email/nom/sujet, "
    "JAMAIS par un numero ou un ID. "
    "Parametres (au moins UN obligatoire) : "
    "  - partenaire_email : email complet ou partiel du partenaire "
    "  - partenaire_nom   : nom ou prenom du partenaire "
    "  - sujet            : texte partiel du sujet de la conversation "
    "Si plusieurs conversations matchent, retourne la PLUS RECENTE. "
    "Retourne : infos de la conversation + tous ses messages ordonnes "
    "chronologiquement (expediteur nom, email, role, contenu, date, lu)."
))
def admin_support_messages(
    partenaire_email: str = None,
    partenaire_nom:   str = None,
    sujet:            str = None,
) -> str:
    try:
        # Defense anti-filtre-fantome
        if isinstance(partenaire_email, str) and partenaire_email.strip() == "":
            partenaire_email = None
        if isinstance(partenaire_nom, str) and partenaire_nom.strip() == "":
            partenaire_nom = None
        if isinstance(sujet, str) and sujet.strip() == "":
            sujet = None

        if not partenaire_email and not partenaire_nom and not sujet:
            return json.dumps({
                "ok":    False,
                "error": "Identifier la conversation via partenaire_email, partenaire_nom OU sujet."
            }, indent=2)

        w, p = [], []
        if partenaire_email:
            w.append("up.email ILIKE %s")
            p.append(f"%{partenaire_email}%")
        if partenaire_nom:
            w.append("(up.nom ILIKE %s OR up.prenom ILIKE %s)")
            p += [f"%{partenaire_nom}%"] * 2
        if sujet:
            w.append("sc.sujet ILIKE %s")
            p.append(f"%{sujet}%")
        where_sql = "WHERE " + " AND ".join(w)

        conv = db_fetchrow(f"""
            SELECT
                sc.sujet,
                sc.statut,
                sc.created_at,
                sc.updated_at,
                up.nom || ' ' || up.prenom    AS partenaire_nom,
                up.email                       AS partenaire_email,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS admin_nom,
                ua.email                       AS admin_email,
                sc.id AS _cid
            FROM voyage_hotel.support_conversation sc
            JOIN utilisateur up     ON up.id = sc.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id = sc.id_admin
            {where_sql}
            ORDER BY sc.updated_at DESC
            LIMIT 1
        """, *p)

        if not conv:
            return json.dumps({
                "ok":    False,
                "error": "Aucune conversation ne correspond aux criteres fournis."
            }, indent=2)

        cid = conv.pop("_cid")

        messages = db_fetch("""
            SELECT
                sm.contenu,
                sm.lu,
                sm.created_at,
                u.nom || ' ' || u.prenom       AS expediteur_nom,
                u.email                         AS expediteur_email,
                CAST(u.role AS VARCHAR)         AS expediteur_role
            FROM voyage_hotel.support_message sm
            JOIN utilisateur u ON u.id = sm.id_expediteur
            WHERE sm.id_conversation = %s
            ORDER BY sm.created_at ASC
        """, cid)

        # Compter aussi les derniers messages non lus
        nb_non_lus = sum(1 for m in messages if not m.get("lu"))

        return json.dumps({
            "ok":           True,
            "conversation": conv,
            "nb_messages":  len(messages),
            "nb_non_lus":   nb_non_lus,
            "messages":     messages,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════
#  3. TOUTES LES CONVERSATIONS D'UN PARTENAIRE
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lister toutes les conversations support d'UN partenaire specifique. "
    "Identification du partenaire par email OU nom (jamais par ID). "
    "Parametres (au moins UN obligatoire) : "
    "  - partenaire_email : email du partenaire "
    "  - partenaire_nom   : nom ou prenom du partenaire "
    "Retourne : liste des conversations de ce partenaire avec leurs statuts, "
    "sujets, dates, nombre de messages."
))
def admin_support_conversations_partenaire(
    partenaire_email: str = None,
    partenaire_nom:   str = None,
) -> str:
    try:
        if isinstance(partenaire_email, str) and partenaire_email.strip() == "":
            partenaire_email = None
        if isinstance(partenaire_nom, str) and partenaire_nom.strip() == "":
            partenaire_nom = None

        if not partenaire_email and not partenaire_nom:
            return json.dumps({
                "ok":    False,
                "error": "Identifier le partenaire via partenaire_email OU partenaire_nom."
            }, indent=2)

        w, p = [], []
        if partenaire_email:
            w.append("up.email ILIKE %s")
            p.append(f"%{partenaire_email}%")
        if partenaire_nom:
            w.append("(up.nom ILIKE %s OR up.prenom ILIKE %s)")
            p += [f"%{partenaire_nom}%"] * 2
        where_sql = "WHERE " + " AND ".join(w)

        # Verifier d'abord que le partenaire existe
        partenaire = db_fetchrow(f"""
            SELECT
                up.nom || ' ' || up.prenom AS nom_complet,
                up.email,
                up.id AS _pid
            FROM utilisateur up
            {where_sql}
              AND CAST(up.role AS VARCHAR) = 'PARTENAIRE'
            LIMIT 1
        """, *p)

        if not partenaire:
            return json.dumps({
                "ok":    False,
                "error": "Aucun partenaire ne correspond aux criteres fournis."
            }, indent=2)

        pid = partenaire.pop("_pid")

        rows = db_fetch("""
            SELECT
                sc.sujet,
                sc.statut,
                sc.created_at,
                sc.updated_at,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS admin_nom,
                (SELECT COUNT(*) FROM voyage_hotel.support_message sm
                 WHERE sm.id_conversation = sc.id)                        AS nb_messages,
                (SELECT COUNT(*) FROM voyage_hotel.support_message sm
                 WHERE sm.id_conversation = sc.id AND sm.lu = false)      AS nb_non_lus,
                (SELECT LEFT(sm.contenu, 150) FROM voyage_hotel.support_message sm
                 WHERE sm.id_conversation = sc.id
                 ORDER BY sm.created_at DESC LIMIT 1)                     AS dernier_message
            FROM voyage_hotel.support_conversation sc
            LEFT JOIN utilisateur ua ON ua.id = sc.id_admin
            WHERE sc.id_partenaire = %s
            ORDER BY sc.updated_at DESC
        """, pid)

        return json.dumps({
            "ok":         True,
            "partenaire": partenaire,
            "total":      len(rows),
            "data":       rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)