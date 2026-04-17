"""
mcp/tools/admin_marketing.py
=============================
VERSION v3 — ENRICHIE avec Facebook Management + Video Campaigns

Tools MCP — Marketing : campagnes + catalogues + Facebook + Videos

Tools exposes :
  admin_marketing_liste         → campagnes marketing (partenaires)
  admin_catalogue_liste         → catalogues email
  admin_facebook_publications   → publications Facebook (brouillons, publies, programmes)
  admin_facebook_config         → configuration Facebook (token, page)
  admin_video_campaigns_liste   → campagnes video (Claude+Replicate+Brevo)
  admin_video_campaign_detail   → detail d'une campagne video par titre
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


# ═══════════════════════════════════════════════════════════
#  1. MARKETING (campagnes partenaires)
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lister les campagnes marketing des partenaires — page AdminMarketing. "
    "Filtres : statut (EN_ATTENTE | ACCEPTEE | REFUSEE | ACTIVE | EXPIREE), "
    "type (str), search (nom ou contenu), limit (int, defaut 50). "
    "Retourne pour chaque campagne : nom, type, budget, segment_cible, contenu, "
    "statut, date_debut, date_fin, partenaire_nom, partenaire_email. "
    "Pour 'campagnes actives' utiliser statut='ACTIVE'."
))
def admin_marketing_liste(
    statut: str = None,
    type:   str = None,
    search: str = None,
    limit:  int = 50,
) -> str:
    try:
        if isinstance(statut, str) and statut.strip() == "": statut = None
        if isinstance(type,   str) and type.strip()   == "": type   = None
        if isinstance(search, str) and search.strip() == "": search = None

        wheres, params = [], []
        if statut:
            wheres.append("CAST(m.statut AS VARCHAR) = %s")
            params.append(statut.upper())
        if type:
            wheres.append("m.type ILIKE %s")
            params.append(f"%{type}%")
        if search:
            wheres.append("(m.nom ILIKE %s OR m.contenu ILIKE %s)")
            params += [f"%{search}%"] * 2
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                m.nom, m.type, m.budget, m.segment_cible, m.contenu,
                CAST(m.statut AS VARCHAR) AS statut,
                m.date_demande, m.date_debut, m.date_fin, m.created_at,
                u.nom || ' ' || u.prenom   AS partenaire_nom,
                u.email                    AS partenaire_email,
                p.nom_entreprise
            FROM marketing m
            JOIN partenaire  p ON p.id = m.id_partenaire
            JOIN utilisateur u ON u.id = p.id
            {where_sql}
            ORDER BY m.created_at DESC
            LIMIT %s
        """, *params)

        stats = db_fetch("""
            SELECT CAST(statut AS VARCHAR) AS statut, COUNT(*) AS nb
            FROM marketing GROUP BY statut
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
#  2. CATALOGUE (emails de produits)
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lister les catalogues email envoyes aux clients — page AdminCatalogue. "
    "Filtres : statut (BROUILLON | PLANIFIE | EN_COURS | ENVOYE | ECHOUE), "
    "search (titre), limit (int, defaut 30). "
    "Retourne : titre, statut, destinataires, description_ia, nb_envoyes, "
    "nb_echecs, scheduled_at, envoye_at, cree_par (nom admin)."
))
def admin_catalogue_liste(
    statut: str = None,
    search: str = None,
    limit:  int = 30,
) -> str:
    try:
        if isinstance(statut, str) and statut.strip() == "": statut = None
        if isinstance(search, str) and search.strip() == "": search = None

        wheres, params = [], []
        if statut:
            wheres.append("CAST(c.statut AS VARCHAR) = %s")
            params.append(statut.upper())
        if search:
            wheres.append("c.titre ILIKE %s")
            params.append(f"%{search}%")
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                c.titre,
                CAST(c.statut AS VARCHAR) AS statut,
                c.destinataires,
                c.description_ia,
                c.nb_envoyes, c.nb_echecs,
                c.scheduled_at, c.envoye_at, c.created_at,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS cree_par
            FROM catalogue c
            LEFT JOIN utilisateur ua ON ua.id = c.created_by
            {where_sql}
            ORDER BY c.created_at DESC
            LIMIT %s
        """, *params)

        stats = db_fetch("""
            SELECT CAST(statut AS VARCHAR) AS statut, COUNT(*) AS nb
            FROM catalogue GROUP BY statut
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
#  3. FACEBOOK PUBLICATIONS
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lister les publications Facebook — page AdminMarketing (onglet Facebook). "
    "Filtres : "
    "statut (DRAFT | SCHEDULED | PUBLISHED | FAILED | DELETED), "
    "type_contenu (hotel | voyage | promotion | offre), "
    "search (texte dans le message), "
    "limit (int, defaut 30). "
    "Retourne : message (extrait), type_contenu, statut, scheduled_at, "
    "published_at, likes, commentaires, partages, portee, impressions, "
    "admin_nom (createur). "
    "Pour 'brouillons' utiliser statut='DRAFT', "
    "pour 'publications publiees' utiliser statut='PUBLISHED', "
    "pour 'publications programmees' utiliser statut='SCHEDULED'."
))
def admin_facebook_publications(
    statut: str = None,
    type_contenu: str = None,
    search: str = None,
    limit: int = 30,
) -> str:
    try:
        if isinstance(statut, str)       and statut.strip()       == "": statut = None
        if isinstance(type_contenu, str) and type_contenu.strip() == "": type_contenu = None
        if isinstance(search, str)       and search.strip()       == "": search = None

        wheres, params = [], []
        if statut:
            wheres.append("CAST(pf.statut AS VARCHAR) = %s")
            params.append(statut.upper())
        if type_contenu:
            wheres.append("CAST(pf.type_contenu AS VARCHAR) = %s")
            params.append(type_contenu.lower())
        if search:
            wheres.append("pf.message ILIKE %s")
            params.append(f"%{search}%")
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                LEFT(pf.message, 200)              AS message_extrait,
                LENGTH(pf.message)                  AS message_longueur,
                CAST(pf.type_contenu AS VARCHAR)   AS type_contenu,
                CAST(pf.statut AS VARCHAR)         AS statut,
                pf.image_url,
                pf.scheduled_at,
                pf.published_at,
                pf.error_message,
                pf.fb_post_id,
                COALESCE(pf.likes_count,      0)   AS likes_count,
                COALESCE(pf.comments_count,   0)   AS comments_count,
                COALESCE(pf.shares_count,     0)   AS shares_count,
                COALESCE(pf.reactions_count,  0)   AS reactions_count,
                COALESCE(pf.clicks_count,     0)   AS clicks_count,
                COALESCE(pf.reach_count,      0)   AS reach_count,
                COALESCE(pf.impressions,      0)   AS impressions,
                pf.stats_updated_at,
                pf.created_at,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS admin_nom,
                ua.email                            AS admin_email
            FROM voyage_hotel.publication_facebook pf
            LEFT JOIN utilisateur ua ON ua.id = pf.id_admin
            {where_sql}
            ORDER BY pf.created_at DESC
            LIMIT %s
        """, *params)

        stats_statut = db_fetch("""
            SELECT CAST(statut AS VARCHAR) AS statut, COUNT(*) AS nb
            FROM voyage_hotel.publication_facebook
            GROUP BY statut
        """)
        stats_globales = {r["statut"]: int(r["nb"]) for r in stats_statut}

        totaux = db_fetchrow("""
            SELECT
                COALESCE(SUM(likes_count),     0) AS total_likes,
                COALESCE(SUM(comments_count),  0) AS total_commentaires,
                COALESCE(SUM(shares_count),    0) AS total_partages,
                COALESCE(SUM(reactions_count), 0) AS total_reactions,
                COALESCE(SUM(clicks_count),    0) AS total_clicks,
                COALESCE(SUM(reach_count),     0) AS total_portee,
                COALESCE(SUM(impressions),     0) AS total_impressions
            FROM voyage_hotel.publication_facebook
            WHERE CAST(statut AS VARCHAR) = 'PUBLISHED'
        """)

        return json.dumps({
            "ok": True,
            "total_filtre":   len(rows),
            "stats_globales": stats_globales,
            "totaux_interactions_publiees": totaux,
            "data":           rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════
#  4. FACEBOOK CONFIG
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lire la configuration Facebook courante : page ID, nom de page, "
    "statut du token (actif/expire), date d'expiration, derniere mise a jour. "
    "Aucun parametre. Le token lui-meme n'est JAMAIS expose pour securite."
))
def admin_facebook_config() -> str:
    try:
        cfg = db_fetchrow("""
            SELECT
                fc.page_id,
                fc.page_name,
                fc.token_actif,
                fc.token_expires_at,
                fc.updated_at,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS updated_by_nom,
                CASE WHEN fc.page_access_token IS NOT NULL AND LENGTH(fc.page_access_token) > 0
                     THEN TRUE ELSE FALSE END                        AS token_configure
            FROM voyage_hotel.facebook_config fc
            LEFT JOIN utilisateur ua ON ua.id = fc.updated_by
            ORDER BY fc.id DESC
            LIMIT 1
        """)

        if not cfg:
            return json.dumps({
                "ok": True,
                "configure": False,
                "message": "Aucune configuration Facebook enregistree."
            }, default=str, indent=2)

        return json.dumps({
            "ok":        True,
            "configure": True,
            "data":      cfg,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════
#  5. VIDEO CAMPAIGNS — LISTE
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Lister les campagnes video marketing (Claude + Replicate + Brevo) — "
    "page AdminMarketing (onglet Videos). "
    "Filtres : "
    "statut (BROUILLON | EN_GENERATION | PRET | EN_ENVOI | ENVOYE | ECHOUE), "
    "ton (LUXE | AVENTURE | FAMILLE | ROMANTIQUE | AFFAIRES), "
    "segment (tous | client | visiteur), "
    "search (titre ou destination), "
    "limit (int, defaut 30). "
    "Retourne : titre, destination, ton, statut, nb_envoyes, nb_echecs, "
    "envoye_at, cree_par_nom. "
    "Pour 'videos pretes' utiliser statut='PRET', "
    "pour 'videos envoyees' utiliser statut='ENVOYE'."
))
def admin_video_campaigns_liste(
    statut:  str = None,
    ton:     str = None,
    segment: str = None,
    search:  str = None,
    limit:   int = 30,
) -> str:
    try:
        if isinstance(statut, str)  and statut.strip()  == "": statut  = None
        if isinstance(ton, str)     and ton.strip()     == "": ton     = None
        if isinstance(segment, str) and segment.strip() == "": segment = None
        if isinstance(search, str)  and search.strip()  == "": search  = None

        wheres, params = [], []
        if statut:
            wheres.append("CAST(vc.statut AS VARCHAR) = %s")
            params.append(statut.upper())
        if ton:
            wheres.append("CAST(vc.ton AS VARCHAR) = %s")
            params.append(ton.upper())
        if segment:
            wheres.append("vc.segment = %s")
            params.append(segment.lower())
        if search:
            wheres.append("(vc.titre ILIKE %s OR vc.destination ILIKE %s)")
            params += [f"%{search}%"] * 2
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)

        rows = db_fetch(f"""
            SELECT
                vc.titre,
                vc.destination,
                CAST(vc.ton AS VARCHAR)      AS ton,
                vc.segment,
                CAST(vc.statut AS VARCHAR)   AS statut,
                vc.formats,
                vc.nb_envoyes,
                vc.nb_echecs,
                vc.scheduled_at,
                vc.envoye_at,
                vc.ab_enabled,
                vc.ab_gagnant,
                vc.erreur,
                vc.created_at,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS cree_par_nom,
                ua.email                              AS cree_par_email,
                CASE WHEN vc.video_url_landscape IS NOT NULL THEN TRUE ELSE FALSE END AS a_video_landscape,
                CASE WHEN vc.video_url_portrait  IS NOT NULL THEN TRUE ELSE FALSE END AS a_video_portrait,
                CASE WHEN vc.video_url_square    IS NOT NULL THEN TRUE ELSE FALSE END AS a_video_square
            FROM video_campaign vc
            LEFT JOIN utilisateur ua ON ua.id = vc.created_by
            {where_sql}
            ORDER BY vc.created_at DESC
            LIMIT %s
        """, *params)

        stats = db_fetch("""
            SELECT CAST(statut AS VARCHAR) AS statut, COUNT(*) AS nb
            FROM video_campaign GROUP BY statut
        """)
        stats_globales = {r["statut"]: int(r["nb"]) for r in stats}

        totaux = db_fetchrow("""
            SELECT
                COUNT(*)                        AS total,
                COALESCE(SUM(nb_envoyes), 0)   AS total_emails_envoyes,
                COALESCE(SUM(nb_echecs), 0)    AS total_echecs
            FROM video_campaign
        """)

        return json.dumps({
            "ok": True,
            "total_filtre":   len(rows),
            "stats_globales": stats_globales,
            "totaux":         totaux,
            "data":           rows,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════
#  6. VIDEO CAMPAIGN — DETAIL PAR TITRE
# ═══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Detail complet d'une campagne video PAR TITRE (jamais par ID). "
    "Parametre : titre (str, texte partiel du titre de la campagne). "
    "Si plusieurs campagnes matchent, retourne la plus recente. "
    "Retourne : titre, destination, ton, segment, statut, script_video, "
    "sujet_email, description_marketing, cta_texte, hashtags, prompts_images, "
    "nb_envoyes, nb_echecs, URLs des videos, infos A/B testing, cree_par."
))
def admin_video_campaign_detail(titre: str) -> str:
    try:
        if not titre or (isinstance(titre, str) and titre.strip() == ""):
            return json.dumps({
                "ok": False,
                "error": "Le titre de la campagne est obligatoire."
            }, indent=2)

        titre = titre.strip()

        camp = db_fetchrow("""
            SELECT
                vc.titre,
                vc.destination,
                CAST(vc.ton AS VARCHAR)      AS ton,
                vc.segment,
                CAST(vc.statut AS VARCHAR)   AS statut,
                vc.formats,
                vc.script_video,
                vc.sujet_email,
                vc.description_marketing,
                vc.cta_texte,
                vc.hashtags,
                vc.prompts_images,
                vc.nb_envoyes, vc.nb_echecs,
                vc.scheduled_at, vc.envoye_at,
                vc.ab_enabled, vc.ab_variante_sujet, vc.ab_variante_cta, vc.ab_gagnant,
                vc.erreur,
                vc.video_url_landscape,
                vc.video_url_portrait,
                vc.video_url_square,
                vc.thumbnail_url,
                vc.created_at, vc.updated_at,
                CASE WHEN ua.id IS NOT NULL
                     THEN ua.nom || ' ' || ua.prenom ELSE NULL END AS cree_par_nom,
                ua.email                              AS cree_par_email
            FROM video_campaign vc
            LEFT JOIN utilisateur ua ON ua.id = vc.created_by
            WHERE vc.titre ILIKE %s
            ORDER BY vc.created_at DESC
            LIMIT 1
        """, f"%{titre}%")

        if not camp:
            return json.dumps({
                "ok":    False,
                "error": f"Aucune campagne video ne correspond au titre '{titre}'."
            }, default=str, indent=2)

        return json.dumps({
            "ok":   True,
            "data": camp,
        }, default=str, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)