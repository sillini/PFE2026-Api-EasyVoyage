"""
easyvoyage_mcp/tools/partenaire_promotions_support.py
======================================================
Tools MCP — Espace PARTENAIRE : Promotions et Support.

Correspond aux pages :
  - MesPromotions.jsx              (promotions sur mes hotels)
  - PartenaireSupportPage.jsx      (chat support avec admin)

NOTE : Le partenaire N'A PAS acces au module Marketing (reserve a l'admin).
       Ce fichier couvre uniquement Promotions + Support + Notifications.

Tools exposes (7) :
  partenaire_promotions_liste          → GET /promotions/mes-promotions
  partenaire_promotion_detail          → GET /promotions/{id}
  partenaire_promotion_active_hotel    → GET /promotions/hotels/{id}/active
  partenaire_support_conversations     → GET /partenaire/support/conversations
  partenaire_support_messages          → GET /partenaire/support/conversations/{id}
  partenaire_notifications             → GET /support/notifications
  partenaire_vue_globale               → agrege promotions + support + notifications

PRINCIPES (identiques aux MCP admin et client) :
  - Recherche par NOM / sujet / titre (jamais par ID technique)
  - Defense anti-filtre-fantome (chaines vides -> None)
  - Retour JSON normalise : {"ok": True, ...} ou {"ok": False, "error": str}
  - session_id obligatoire (JWT recupere depuis le cache HTTP)
  - Le backend filtre automatiquement par partenaire via require_partenaire

LECTURE SEULE :
  Ces tools sont en lecture seule. Creer/modifier/supprimer des promotions
  ou envoyer des messages support doit se faire via l'interface officielle
  (l'IA n'est pas un executant d'actions).
"""

import json
from typing import Optional

from easyvoyage_mcp.client_http import api_get
from easyvoyage_mcp.session_cache import get_jwt


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _clean_str(v):
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s == "" or s.lower() in ("null", "none", "undefined"):
        return None
    return s


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, **data}, default=str, ensure_ascii=False, indent=2)


def _err(msg) -> str:
    return json.dumps({"ok": False, "error": str(msg)}, ensure_ascii=False, indent=2)


def _debug_session(tool_name: str, session_id) -> None:
    print("=" * 70)
    print(f"[PARTENAIRE TOOL] {tool_name} appele")
    print(f"[PARTENAIRE TOOL] session_id recu  = {repr(session_id)}")
    print(f"[PARTENAIRE TOOL] type             = {type(session_id).__name__}")
    if isinstance(session_id, str) and session_id.strip():
        cached = get_jwt(session_id.strip())
        print(f"[PARTENAIRE TOOL] JWT dans cache    = {bool(cached)} (len={len(cached) if cached else 0})")
    print("=" * 70)


def _require_session(session_id: Optional[str]) -> Optional[str]:
    if not session_id or not isinstance(session_id, str) or not session_id.strip():
        return "Authentification requise : session_id manquant"
    if not get_jwt(session_id.strip()):
        return "Session expiree ou invalide — le partenaire doit renvoyer un message"
    return None


def _norm(s: str) -> str:
    """Normalise une chaine pour comparaison fuzzy (accents, casse)."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


# ══════════════════════════════════════════════════════════
#  RESOLUTION FUZZY — mes hotels
# ══════════════════════════════════════════════════════════

def _resolve_mon_hotel_id(session_id: str, hotel_nom: str) -> Optional[int]:
    """Resout l'ID d'un hotel du partenaire via /hotels/mes-hotels."""
    if not hotel_nom:
        return None
    try:
        data = api_get("hotels/mes-hotels", session_id=session_id, per_page=100)
        items = data.get("items", data) if isinstance(data, dict) else data
        if not items:
            return None

        target = _norm(hotel_nom)
        for h in items:
            if _norm(h.get("nom", "")) == target:
                return h.get("id")
        for h in items:
            if target in _norm(h.get("nom", "")):
                return h.get("id")
        return None
    except Exception as e:
        print(f"[PARTENAIRE] _resolve_mon_hotel_id error: {e}")
        return None


# ══════════════════════════════════════════════════════════
#  1. PROMOTIONS — LISTE DE MES PROMOS
# ══════════════════════════════════════════════════════════

def partenaire_promotions_liste(
    session_id: str,
    hotel_nom:  Optional[str] = None,
    statut:     Optional[str] = None,
) -> str:
    """
    Liste mes promotions (toutes ou filtrees par hotel et/ou statut).
    Utiliser pour : mes promos, promotions actives, offres en cours, promos en
    attente de validation, promos refusees.

    Filtres optionnels :
      - hotel_nom (str) : filtrer par hotel (par nom)
      - statut (str)    : PENDING | APPROVED | REJECTED

    Retourne : liste de promotions avec id, titre, pourcentage, date_debut,
    date_fin, hotel, statut, est_valide_maintenant.
    """
    _debug_session("partenaire_promotions_liste", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    try:
        sid = session_id.strip()
        params = {}

        # Resolution hotel par nom si fourni
        h_nom_clean = _clean_str(hotel_nom)
        if h_nom_clean:
            hotel_id = _resolve_mon_hotel_id(sid, h_nom_clean)
            if not hotel_id:
                return _err(f"Aucun de vos hotels ne correspond a '{h_nom_clean}'")
            params["hotel_id"] = hotel_id

        s = _clean_str(statut)
        if s:
            params["statut"] = s.upper()

        data = api_get("promotions/mes-promotions", session_id=sid, **params)
        return _ok({"promotions": data, "filtres": {
            "hotel_nom": h_nom_clean,
            "statut": params.get("statut"),
        }})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  2. PROMOTION — DETAIL PAR TITRE
# ══════════════════════════════════════════════════════════

def partenaire_promotion_detail(
    session_id:  str,
    promo_titre: str,
) -> str:
    """
    Detail complet d'UNE promotion, recherche par son TITRE.
    Utiliser pour : detail de la promo X, infos completes sur ma promotion,
    statut d'une promo par son nom, motif de rejet eventuel.

    Parametre OBLIGATOIRE :
      - promo_titre (str) : titre exact ou partiel de la promotion

    Retourne : id, titre, description, pourcentage, date_debut, date_fin,
    statut, hotel associe, motif_rejet eventuel.
    """
    _debug_session("partenaire_promotion_detail", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    titre_clean = _clean_str(promo_titre)
    if not titre_clean:
        return _err("Le titre de la promotion est obligatoire")

    try:
        sid = session_id.strip()

        # Liste mes promos et cherche par titre
        data = api_get("promotions/mes-promotions", session_id=sid)
        items = data.get("items", data) if isinstance(data, dict) else data
        if not items:
            return _err("Vous n'avez aucune promotion enregistree")

        target = _norm(titre_clean)
        match = None

        # 1. Match exact
        for p in items:
            if _norm(p.get("titre", "")) == target:
                match = p
                break

        # 2. Contient
        if not match:
            for p in items:
                if target in _norm(p.get("titre", "")):
                    match = p
                    break

        if not match:
            return _err(f"Aucune promotion correspondant a '{titre_clean}'")

        # Recupere le detail complet
        detail = api_get(f"promotions/{match['id']}", session_id=sid)
        return _ok({"promo_titre": titre_clean, "promotion": detail})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  3. PROMOTION ACTIVE SUR UN HOTEL
# ══════════════════════════════════════════════════════════

def partenaire_promotion_active_hotel(
    session_id: str,
    hotel_nom:  str,
) -> str:
    """
    Promotion actuellement ACTIVE sur un de mes hotels (par nom).
    Utiliser pour : quelle promo est active sur mon hotel X, offre en cours,
    reduction actuelle visible par les clients.

    Parametre OBLIGATOIRE :
      - hotel_nom (str) : nom de l'hotel

    Retourne : la promotion active (titre, pourcentage, date_fin) ou null.
    """
    _debug_session("partenaire_promotion_active_hotel", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    nom_clean = _clean_str(hotel_nom)
    if not nom_clean:
        return _err("Le nom de l'hotel est obligatoire")

    try:
        sid = session_id.strip()
        hotel_id = _resolve_mon_hotel_id(sid, nom_clean)
        if not hotel_id:
            return _err(f"Aucun de vos hotels ne correspond a '{nom_clean}'")

        try:
            promo = api_get(
                f"promotions/hotels/{hotel_id}/active",
                session_id=sid,
            )
            return _ok({
                "hotel_nom":        nom_clean,
                "promotion_active": promo,
            })
        except RuntimeError:
            return _ok({
                "hotel_nom":        nom_clean,
                "promotion_active": None,
                "message":          "Aucune promotion active actuellement sur cet hotel",
            })
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  4. SUPPORT — CONVERSATIONS
# ══════════════════════════════════════════════════════════

def partenaire_support_conversations(
    session_id: str,
    statut:     Optional[str] = None,
) -> str:
    """
    Lister mes conversations support avec l'equipe EasyVoyage.
    Utiliser pour : mes discussions support, mes tickets, echanges avec admin,
    mes demandes d'aide.

    Filtre optionnel :
      - statut (str) : EN_ATTENTE | ACCEPTEE | FERMEE | RESOLUE

    Retourne : liste de conversations (id, sujet, statut, nb_messages,
    derniere_activite, admin_nom).
    """
    _debug_session("partenaire_support_conversations", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        sid = session_id.strip()
        data = api_get("partenaire/support/conversations", session_id=sid)

        # Filtrage cote client si un statut est demande (backend peut ne pas l'exposer)
        s = _clean_str(statut)
        if s:
            s_upper = s.upper()
            items = data.get("items", data) if isinstance(data, dict) else data
            filtered = [c for c in (items or []) if (c.get("statut") or "").upper() == s_upper]
            return _ok({
                "total":         len(filtered),
                "statut_filtre": s_upper,
                "items":         filtered,
            })

        return _ok({"conversations": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  5. SUPPORT — MESSAGES D'UNE CONVERSATION (PAR SUJET)
# ══════════════════════════════════════════════════════════

def partenaire_support_messages(
    session_id: str,
    sujet:      str,
) -> str:
    """
    Messages d'UNE de mes conversations support, recherche par SUJET.
    Utiliser pour : voir les messages de la conversation X, historique d'un
    ticket, que m'a dit l'admin.

    Parametre OBLIGATOIRE :
      - sujet (str) : sujet exact ou partiel de la conversation

    Retourne : conversation avec sujet, statut, messages [auteur, contenu,
    date].
    """
    _debug_session("partenaire_support_messages", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    sujet_clean = _clean_str(sujet)
    if not sujet_clean:
        return _err("Le sujet de la conversation est obligatoire")

    try:
        sid = session_id.strip()

        # Liste mes conversations et cherche par sujet
        data = api_get("partenaire/support/conversations", session_id=sid)
        items = data.get("items", data) if isinstance(data, dict) else data
        if not items:
            return _err("Vous n'avez aucune conversation support")

        target = _norm(sujet_clean)
        match = None

        for c in items:
            if _norm(c.get("sujet", "")) == target:
                match = c
                break
        if not match:
            for c in items:
                if target in _norm(c.get("sujet", "")):
                    match = c
                    break

        if not match:
            return _err(f"Aucune conversation correspondant au sujet '{sujet_clean}'")

        detail = api_get(
            f"partenaire/support/conversations/{match['id']}",
            session_id=sid,
        )
        return _ok({"sujet": sujet_clean, "conversation": detail})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  6. NOTIFICATIONS
# ══════════════════════════════════════════════════════════

def partenaire_notifications(
    session_id:  str,
    non_lues:    Optional[bool] = None,
) -> str:
    """
    Mes notifications (support, validations de promos, messages systeme).
    Utiliser pour : mes notifications, nouveautes, alertes non lues,
    combien de notifications j'ai en attente.

    Filtre optionnel :
      - non_lues (bool) : True=uniquement non lues, None=toutes

    Retourne : liste des notifications avec type, titre, message, lue, date.
    """
    _debug_session("partenaire_notifications", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        sid = session_id.strip()
        data = api_get("support/notifications", session_id=sid)

        if non_lues is True:
            items = data.get("items", data) if isinstance(data, dict) else data
            filtered = [n for n in (items or []) if not n.get("lue", False)]
            return _ok({
                "total_non_lues": len(filtered),
                "items":          filtered,
            })

        return _ok({"notifications": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  7. VUE GLOBALE — SYNTHESE PROMOS + SUPPORT + NOTIFICATIONS
# ══════════════════════════════════════════════════════════

def partenaire_vue_globale(session_id: str) -> str:
    """
    Vue synthetique de mon activite promotions + communication avec EasyVoyage :
    promotions + support + notifications. Utiliser pour : bilan communication,
    que dois-je traiter, quoi de neuf, synthese d'activite rapide.

    Aucun parametre requis.

    Retourne :
      - promotions    : nb total, par statut (pending/approved/rejected), actives
      - support       : nb conversations ouvertes vs fermees
      - notifications : nb total, nb non lues
    """
    _debug_session("partenaire_vue_globale", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        sid = session_id.strip()

        promos        = api_get("promotions/mes-promotions",         session_id=sid)
        support       = api_get("partenaire/support/conversations",  session_id=sid)
        notifications = api_get("support/notifications",             session_id=sid)

        # Aggregations promotions
        p_items = promos.get("items", promos) if isinstance(promos, dict) else promos
        p_items = p_items or []
        p_stats = {
            "total":    len(p_items),
            "pending":  sum(1 for p in p_items if (p.get("statut") or "").upper() == "PENDING"),
            "approved": sum(1 for p in p_items if (p.get("statut") or "").upper() == "APPROVED"),
            "rejected": sum(1 for p in p_items if (p.get("statut") or "").upper() == "REJECTED"),
            "actives":  sum(1 for p in p_items if p.get("est_valide_maintenant")),
        }

        # Aggregations support
        s_items = support.get("items", support) if isinstance(support, dict) else support
        s_items = s_items or []
        s_stats = {
            "total":    len(s_items),
            "ouvertes": sum(
                1 for c in s_items
                if (c.get("statut") or "").upper() in ("EN_ATTENTE", "ACCEPTEE")
            ),
            "fermees":  sum(
                1 for c in s_items
                if (c.get("statut") or "").upper() in ("FERMEE", "RESOLUE")
            ),
        }

        # Notifications non lues
        n_items = notifications.get("items", notifications) if isinstance(notifications, dict) else notifications
        n_items = n_items or []
        n_stats = {
            "total":    len(n_items),
            "non_lues": sum(1 for n in n_items if not n.get("lue", False)),
        }

        return _ok({
            "promotions":    p_stats,
            "support":       s_stats,
            "notifications": n_stats,
        })
    except Exception as e:
        return _err(e)