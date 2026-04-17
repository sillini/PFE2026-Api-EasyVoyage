"""
mcp/tools/admin_promotions.py
==============================
VERSION CORRIGÉE v3 — robuste aux filtres fantômes

CORRECTIONS APPORTEES :
  v1 → v2 : stats_globales calculees par requete SEPAREE sur TOUTE la table
            => compteurs corrects peu importe le filtre.
  v2 → v3 : DEFENSE EN PROFONDEUR contre les filtres fantomes de l'agent IA
            (chaines vides "", false par defaut, None explicites).

            Meme si l'agent IA envoie par erreur :
              { "statut": "APPROVED", "actif": false, "hotel_nom": "",
                "partenaire_email": "", "search": "" }
            le tool IGNORE les valeurs "vides non demandees" et ne passe
            dans WHERE que les filtres VRAIMENT definis.

            Detection "valeur vide" :
              - None                    → ignore
              - ""  (chaine vide)       → ignore
              - "null" / "none"         → ignore (texte)
              - pour actif (booleen) : seul True/False EXPLICITE passe,
                None et chaine vide ignores.

  NOTE IMPORTANTE : l'ambiguite "actif=false non demande" vs "actif=false demande"
  ne peut pas etre resolue cote tool (le booleen false est transmis dans les
  deux cas). La regle de non-envoi de filtre fantome DOIT etre dans le prompt.

Colonnes reelles verifiees :
  promotion : id, titre, description, id_hotel, pourcentage,
              date_debut, date_fin, actif, statut (USER-DEFINED enum),
              id_partenaire, id_admin_validateur, raison_refus, date_decision

Statuts reels en base : APPROVED | REJECTED | PENDING
IMPORTANT : statut est un type enum PostgreSQL → utiliser CAST(statut AS VARCHAR)
"""

import json
from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

mcp = FastMCP("easyvoyage-admin-mcp")


def _clean_str(v):
    """Retourne None si la valeur est 'vide' (None, '', 'null', 'none', whitespace)."""
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s == "" or s.lower() in ("null", "none", "undefined"):
        return None
    return s


def _clean_int(v):
    """Retourne None si la valeur est 'vide' (None, 0, '', 'null')."""
    if v is None or v == 0 or v == "":
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("", "null", "none", "0"):
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return v


@mcp.tool(description=(
    "Lister les promotions — page AdminPromotions. "
    "Filtres OPTIONNELS (a OMETTRE si non demandes par l'utilisateur) : "
    "statut ('PENDING'|'APPROVED'|'REJECTED'), "
    "hotel_nom (nom partiel), partenaire_email, actif (bool), "
    "search (titre), limit (defaut 50). "
    "IMPORTANT : ne PAS passer de chaine vide '' — omettre le parametre. "
    "Ne PAS passer actif=false sauf si l'utilisateur demande EXPLICITEMENT "
    "les promotions desactivees (mot-cle 'inactives', 'desactivees'). "
    "Retourne : "
    "  - data : lignes filtrees. "
    "  - total_filtre : nb lignes retournees par le filtre. "
    "  - stats_globales : {nb_pending, nb_approved, nb_rejected, total_en_base} "
    "    CALCULEES SUR TOUTE LA TABLE — ne changent JAMAIS selon les filtres. "
    "Pour repondre a 'Combien de promotions en attente ?' "
    "utiliser stats_globales.nb_pending, JAMAIS total_filtre."
))
def admin_promotions_liste(
    statut:           str  = None,
    hotel_nom:        str  = None,
    partenaire_email: str  = None,
    actif:            bool = None,
    search:           str  = None,
    limit:            int  = 50,
    hotel_id:         int  = None,
    partenaire_id:    int  = None,
) -> str:
    try:
        # ═════════════════════════════════════════════════════════
        #  NORMALISATION DES PARAMETRES — defense anti-filtre-fantome
        # ═════════════════════════════════════════════════════════
        statut           = _clean_str(statut)
        hotel_nom        = _clean_str(hotel_nom)
        partenaire_email = _clean_str(partenaire_email)
        search           = _clean_str(search)
        hotel_id         = _clean_int(hotel_id)
        partenaire_id    = _clean_int(partenaire_id)

        # Validation du statut (doit etre dans la whitelist)
        if statut is not None:
            statut_up = statut.upper()
            if statut_up not in ("PENDING", "APPROVED", "REJECTED"):
                return json.dumps({
                    "ok": False,
                    "error": f"Statut invalide '{statut}'. "
                             f"Valeurs autorisees : PENDING, APPROVED, REJECTED.",
                }, indent=2)
            statut = statut_up

        # limit : borner entre 1 et 200
        try:
            limit = int(limit) if limit else 50
            limit = max(1, min(limit, 200))
        except (ValueError, TypeError):
            limit = 50

        # ─────────────────────────────────────────────────────────
        #  1) STATS GLOBALES — TOUJOURS sur TOUTE la table
        # ─────────────────────────────────────────────────────────
        stats = db_fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE CAST(statut AS VARCHAR) = 'PENDING')   AS nb_pending,
                COUNT(*) FILTER (WHERE CAST(statut AS VARCHAR) = 'APPROVED')  AS nb_approved,
                COUNT(*) FILTER (WHERE CAST(statut AS VARCHAR) = 'REJECTED')  AS nb_rejected,
                COUNT(*)                                                      AS total_en_base
            FROM promotion
        """)

        # ─────────────────────────────────────────────────────────
        #  2) REQUETE FILTREE — pour l'affichage des lignes
        # ─────────────────────────────────────────────────────────
        w, p = [], []

        # CAST obligatoire car statut est un type enum PostgreSQL
        if statut:
            w.append("CAST(p.statut AS VARCHAR) = %s")
            p.append(statut)
        if hotel_nom:
            w.append("h.nom ILIKE %s")
            p.append(f"%{hotel_nom}%")
        if hotel_id:
            w.append("p.id_hotel = %s")
            p.append(hotel_id)
        if partenaire_email:
            w.append("u.email ILIKE %s")
            p.append(f"%{partenaire_email}%")
        if partenaire_id:
            w.append("p.id_partenaire = %s")
            p.append(partenaire_id)
        # NOTE: actif n'est applique QUE s'il est explicitement True ou False
        # (None est ignore — c'est le cas par defaut si non mentionne)
        if actif is True or actif is False:
            w.append("p.actif = %s")
            p.append(actif)
        if search:
            w.append("p.titre ILIKE %s")
            p.append(f"%{search}%")

        where_sql = ("WHERE " + " AND ".join(w)) if w else ""
        p.append(limit)

        rows = db_fetch(f"""
            SELECT
                p.id,
                p.titre,
                p.description,
                p.pourcentage,
                CAST(p.statut AS VARCHAR)  AS statut,
                p.actif,
                p.date_debut,
                p.date_fin,
                p.raison_refus,
                p.date_decision,
                p.created_at,
                h.nom                      AS hotel_nom,
                h.ville                    AS hotel_ville,
                u.nom||' '||u.prenom       AS partenaire_nom,
                u.email                    AS partenaire_email,
                ua.nom||' '||ua.prenom     AS admin_validateur
            FROM promotion p
            LEFT JOIN hotel h        ON h.id  = p.id_hotel
            LEFT JOIN utilisateur u  ON u.id  = p.id_partenaire
            LEFT JOIN utilisateur ua ON ua.id = p.id_admin_validateur
            {where_sql}
            ORDER BY
                CASE CAST(p.statut AS VARCHAR)
                    WHEN 'PENDING'  THEN 0
                    WHEN 'APPROVED' THEN 1
                    ELSE 2
                END,
                p.created_at DESC
            LIMIT %s
        """, *p)

        return json.dumps({
            "ok":             True,
            "total_filtre":   len(rows),
            "stats_globales": {
                "nb_pending":    int(stats["nb_pending"]),
                "nb_approved":   int(stats["nb_approved"]),
                "nb_rejected":   int(stats["nb_rejected"]),
                "total_en_base": int(stats["total_en_base"]),
            },
            "filtres_appliques": {
                "statut":           statut,
                "hotel_nom":        hotel_nom,
                "partenaire_email": partenaire_email,
                "actif":            actif,
                "search":           search,
                "limit":            limit,
            },
            "data":           rows,
        }, default=str, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)