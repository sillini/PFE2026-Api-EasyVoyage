"""
easyvoyage_mcp/tools/partenaire_finances.py
============================================
Tools MCP — Espace PARTENAIRE : Finances, Revenus, Reservations.

Correspond aux pages :
  - PartenaireFinances.jsx   (dashboard financier + retraits)
  - MesReservations.jsx      (reservations par hotel)

Tools exposes (9) :
  partenaire_dashboard                   → GET /finances-partenaire/dashboard
  partenaire_revenus_mensuels            → GET /finances-partenaire/revenus
  partenaire_finances_mes_hotels         → GET /finances-partenaire/mes-hotels
  partenaire_reservations_financieres    → GET /finances-partenaire/mes-hotels/{id}/reservations
  partenaire_paiements_recus             → GET /finances-partenaire/paiements
  partenaire_mes_demandes_retrait        → GET /finances-partenaire/mes-demandes
  partenaire_reservations_mes_hotels     → GET /reservations/partenaire/mes-hotels
  partenaire_reservations_par_hotel      → GET /reservations/partenaire/hotel/{id}
  partenaire_bilan_financier             → agrege dashboard + revenus + paiements

PRINCIPES (identiques aux MCP admin et client) :
  - Recherche par NOM (jamais par ID technique)
  - Defense anti-filtre-fantome (chaines vides -> None)
  - Retour JSON normalise : {"ok": True, ...} ou {"ok": False, "error": str}
  - session_id obligatoire (JWT recupere depuis le cache HTTP)
  - Le backend filtre automatiquement par partenaire via require_partenaire

SECURITE :
  Ces tools sont en LECTURE SEULE. Les demandes de retrait, paiements reels
  et virements doivent passer par l'interface officielle, pas par l'agent IA.
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


# ══════════════════════════════════════════════════════════
#  RESOLUTION FUZZY — mes hotels financiers
# ══════════════════════════════════════════════════════════

def _resolve_mon_hotel_id_finances(session_id: str, hotel_nom: str) -> Optional[int]:
    """
    Resout l'ID d'un hotel du partenaire en utilisant l'endpoint
    /finances-partenaire/mes-hotels (contient id_hotel + hotel_nom).
    """
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.lower().strip()

    if not hotel_nom:
        return None

    try:
        data = api_get("finances-partenaire/mes-hotels", session_id=session_id)
        items = data.get("items", []) if isinstance(data, dict) else data
        if not items:
            return None

        target = _norm(hotel_nom)

        # 1. Match exact
        for h in items:
            if _norm(h.get("hotel_nom", "")) == target:
                return h.get("id_hotel")

        # 2. Contient
        for h in items:
            if target in _norm(h.get("hotel_nom", "")):
                return h.get("id_hotel")

        # 3. Inverse
        for h in items:
            nom_n = _norm(h.get("hotel_nom", ""))
            if nom_n and nom_n in target:
                return h.get("id_hotel")

        return None
    except Exception as e:
        print(f"[PARTENAIRE] _resolve_mon_hotel_id_finances error: {e}")
        return None


# ══════════════════════════════════════════════════════════
#  1. DASHBOARD FINANCIER — KPIs PRINCIPAUX
# ══════════════════════════════════════════════════════════

def partenaire_dashboard(session_id: str) -> str:
    """
    Dashboard financier du partenaire connecte : KPIs principaux (solde disponible,
    revenu du mois, evolution, nombre de reservations). A utiliser pour : mes
    revenus, mon solde, combien j'ai gagne ce mois, mon tableau de bord,
    resume financier.

    Aucun parametre requis.

    Retourne : solde_disponible, revenu_mois, revenu_mois_precedent,
    evolution_pct (vs mois precedent), nb_reservations_mois, revenu_annee.
    """
    _debug_session("partenaire_dashboard", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get("finances-partenaire/dashboard", session_id=session_id.strip())
        return _ok({"dashboard": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  2. REVENUS MENSUELS — 12 MOIS (GRAPHIQUE)
# ══════════════════════════════════════════════════════════

def partenaire_revenus_mensuels(
    session_id: str,
    annee:      Optional[int] = None,
) -> str:
    """
    Revenus mensuels du partenaire sur 12 mois d'une annee donnee.
    Utiliser pour : evolution de mes revenus, mes gains par mois, graphique
    annuel, comparaison des mois, quel mois a le mieux marche.

    Parametre optionnel :
      - annee (int) : annee (defaut = annee courante)

    Retourne : annee + liste des 12 mois (mois, revenu, nb_resas).
    """
    _debug_session("partenaire_revenus_mensuels", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        params = {}
        if annee is not None:
            params["annee"] = annee

        data = api_get(
            "finances-partenaire/revenus",
            session_id=session_id.strip(),
            **params,
        )
        return _ok({"revenus": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  3. MES HOTELS AVEC RESUME FINANCIER
# ══════════════════════════════════════════════════════════

def partenaire_finances_mes_hotels(session_id: str) -> str:
    """
    Liste des hotels du partenaire avec leur resume financier (revenus, nb_resas,
    solde restant). Utiliser pour : quel est l'hotel le plus rentable, revenus
    par hotel, classer mes hotels par CA, performance financiere par
    etablissement.

    Aucun parametre requis.

    Retourne : liste d'hotels avec id_hotel, hotel_nom, hotel_ville, revenu_mois,
    revenu_total, nb_resas_mois, nb_resas_total, solde_restant.
    """
    _debug_session("partenaire_finances_mes_hotels", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get("finances-partenaire/mes-hotels", session_id=session_id.strip())
        return _ok(data)
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  4. RESERVATIONS FINANCIERES D'UN HOTEL (DRILL-DOWN)
# ══════════════════════════════════════════════════════════

def partenaire_reservations_financieres(
    session_id: str,
    hotel_nom:  str,
    statut:     Optional[str] = None,
    search:     Optional[str] = None,
    page:       int           = 1,
    per_page:   int           = 20,
) -> str:
    """
    Reservations financieres d'UN de mes hotels (clients + visiteurs fusionnes,
    avec part partenaire calculee). Utiliser pour : reservations de tel hotel,
    qui a reserve chez moi, detail des reservations payees, clients ayant
    reserve l'hotel X.

    Parametre OBLIGATOIRE :
      - hotel_nom (str) : nom de l'hotel

    Filtres :
      - statut (str)   : CONFIRMEE | TERMINEE | ANNULEE
      - search (str)   : nom ou email client
      - page, per_page : pagination

    Retourne : total, items [reference, client_nom, dates, montant_total,
    part_partenaire, statut, statut_paiement].
    """
    _debug_session("partenaire_reservations_financieres", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    nom_clean = _clean_str(hotel_nom)
    if not nom_clean:
        return _err("Le nom de l'hotel est obligatoire")

    try:
        sid = session_id.strip()
        hotel_id = _resolve_mon_hotel_id_finances(sid, nom_clean)
        if not hotel_id:
            return _err(f"Aucun de vos hotels ne correspond a '{nom_clean}'")

        params = {"page": page, "per_page": per_page}
        s = _clean_str(statut)
        if s:
            params["statut"] = s.upper()
        sr = _clean_str(search)
        if sr:
            params["search"] = sr

        data = api_get(
            f"finances-partenaire/mes-hotels/{hotel_id}/reservations",
            session_id=sid,
            **params,
        )
        return _ok({"hotel_nom": nom_clean, "reservations": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  5. PAIEMENTS RECUS — HISTORIQUE DES VIREMENTS
# ══════════════════════════════════════════════════════════

def partenaire_paiements_recus(
    session_id: str,
    date_debut: Optional[str] = None,
    date_fin:   Optional[str] = None,
    page:       int           = 1,
    per_page:   int           = 50,
) -> str:
    """
    Historique des paiements (virements) recus de la part d'EasyVoyage.
    Utiliser pour : combien j'ai recu, derniers virements, paiements regles,
    historique des retraits effectues, j'ai recu combien ce mois.

    Filtres optionnels :
      - date_debut (str) : YYYY-MM-DD
      - date_fin (str)   : YYYY-MM-DD
      - page, per_page   : pagination

    Retourne : liste des paiements (id, montant, note, numero_facture, has_pdf,
    date).
    """
    _debug_session("partenaire_paiements_recus", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        params = {"page": page, "per_page": per_page}
        dd = _clean_str(date_debut)
        df = _clean_str(date_fin)
        if dd:
            params["date_debut"] = dd
        if df:
            params["date_fin"] = df

        data = api_get(
            "finances-partenaire/paiements",
            session_id=session_id.strip(),
            **params,
        )
        return _ok({"paiements": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  6. MES DEMANDES DE RETRAIT
# ══════════════════════════════════════════════════════════

def partenaire_mes_demandes_retrait(
    session_id: str,
    statut:     Optional[str] = None,
) -> str:
    """
    Lister mes demandes de retrait envoyees a EasyVoyage avec leur statut
    (EN_ATTENTE, ACCEPTEE, REFUSEE). Utiliser pour : mes demandes de retrait,
    suivi des retraits, mes virements en attente, demande de paiement validee
    ou refusee.

    Filtre optionnel :
      - statut (str) : EN_ATTENTE | ACCEPTEE | REFUSEE

    Retourne : liste des demandes avec id, montant, statut, motif, dates.
    """
    _debug_session("partenaire_mes_demandes_retrait", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        params = {}
        s = _clean_str(statut)
        if s:
            params["statut"] = s.upper()

        data = api_get(
            "finances-partenaire/mes-demandes",
            session_id=session_id.strip(),
            **params,
        )
        return _ok({"demandes": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  7. RESERVATIONS — VUE GESTION (MES HOTELS + STATS)
# ══════════════════════════════════════════════════════════

def partenaire_reservations_mes_hotels(session_id: str) -> str:
    """
    Vue de gestion de toutes les reservations par hotel (stats rapides).
    Utiliser pour : combien de reservations au total, repartition clients vs
    visiteurs, vue globale des reservations.

    Aucun parametre requis.

    Retourne : liste d'hotels avec hotel_nom, nb_reservations, nb_clients,
    nb_visiteurs, ca_total.
    """
    _debug_session("partenaire_reservations_mes_hotels", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get(
            "reservations/partenaire/mes-hotels",
            session_id=session_id.strip(),
        )
        return _ok({"hotels_stats": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  8. RESERVATIONS — DETAIL PAR HOTEL (VUE GESTION)
# ══════════════════════════════════════════════════════════

def partenaire_reservations_par_hotel(
    session_id: str,
    hotel_nom:  str,
    statut:     Optional[str] = None,
    source:     Optional[str] = None,
    page:       int           = 1,
    per_page:   int           = 20,
) -> str:
    """
    Detail des reservations d'UN de mes hotels (vue gestion avec infos client
    completes, numero facture, voucher, methode paiement).
    Utiliser pour : qui a reserve la chambre X, detail client, contacts des
    clients, suivi operationnel des reservations.

    Parametre OBLIGATOIRE :
      - hotel_nom (str) : nom de l'hotel

    Filtres :
      - statut (str) : CONFIRMEE | TERMINEE | ANNULEE | EN_ATTENTE
      - source (str) : 'client' ou 'visiteur'
      - page, per_page : pagination

    Retourne : items avec client_nom, client_prenom, client_email, client_telephone,
    chambre_nom, numero_facture, numero_voucher, methode_paiement, dates,
    nb_adultes, nb_enfants, montant.
    """
    _debug_session("partenaire_reservations_par_hotel", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    nom_clean = _clean_str(hotel_nom)
    if not nom_clean:
        return _err("Le nom de l'hotel est obligatoire")

    try:
        sid = session_id.strip()
        hotel_id = _resolve_mon_hotel_id_finances(sid, nom_clean)
        if not hotel_id:
            return _err(f"Aucun de vos hotels ne correspond a '{nom_clean}'")

        params = {"page": page, "per_page": per_page}
        s = _clean_str(statut)
        src = _clean_str(source)
        if s:
            params["statut"] = s.upper()
        if src:
            params["source"] = src.lower()

        data = api_get(
            f"reservations/partenaire/hotel/{hotel_id}",
            session_id=sid,
            **params,
        )
        return _ok({"hotel_nom": nom_clean, "reservations": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  9. BILAN FINANCIER — VUE SYNTHETIQUE
# ══════════════════════════════════════════════════════════

def partenaire_bilan_financier(session_id: str) -> str:
    """
    Bilan financier synthetique : combine dashboard + revenus 12 mois + paiements
    recents. Utiliser pour : bilan global, vue synthetique de mes finances,
    ou en suis-je financierement, synthese rapide.

    Aucun parametre requis.

    Retourne : dashboard KPIs + revenus_mensuels (12 mois) + paiements recents.
    """
    _debug_session("partenaire_bilan_financier", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        sid = session_id.strip()

        # Recupere tout en parallele (dashboard + revenus + paiements)
        dashboard = api_get("finances-partenaire/dashboard", session_id=sid)
        revenus   = api_get("finances-partenaire/revenus",   session_id=sid)
        paiements = api_get(
            "finances-partenaire/paiements",
            session_id=sid,
            page=1,
            per_page=10,
        )

        return _ok({
            "dashboard":           dashboard,
            "revenus_mensuels":    revenus,
            "paiements_recents":   paiements,
        })
    except Exception as e:
        return _err(e)