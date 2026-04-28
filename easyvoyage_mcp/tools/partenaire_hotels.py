"""
easyvoyage_mcp/tools/partenaire_hotels.py
==========================================
Tools MCP — Espace PARTENAIRE : Hotels, Chambres, Tarifs, Avis.

Correspond aux pages :
  - MesHotels.jsx            (liste et detail des hotels)
  - ChambresPage.jsx         (gestion chambres + tarifs)
  - PartenaireProfil.jsx     (profil partenaire)

Tools exposes (9) :
  partenaire_profil                   → GET /auth/me
  partenaire_mes_hotels               → GET /hotels/mes-hotels
  partenaire_hotel_detail_par_nom     → GET /hotels/{id} (resolution par nom)
  partenaire_hotel_avis               → GET /hotels/{id}/avis
  partenaire_chambres_liste           → GET /hotels/{id}/chambres
  partenaire_chambre_detail           → GET /hotels/{id}/chambres/{cid}
  partenaire_tarifs_liste             → GET /hotels/{id}/chambres/{cid}/tarifs
  partenaire_hotel_disponibilites     → GET /hotels/{id}/disponibilites
  partenaire_hotel_statistiques       → agrege mes-hotels + avis + chambres

PRINCIPES (identiques aux MCP admin et client) :
  - Recherche par NOM (jamais par ID technique)
  - Defense anti-filtre-fantome (chaines vides -> None)
  - Retour JSON normalise : {"ok": True, ...} ou {"ok": False, "error": str}
  - session_id obligatoire (JWT recupere depuis le cache HTTP)
  - Le backend filtre automatiquement par partenaire via require_partenaire

AUTHENTIFICATION :
  Tous les endpoints appeles sont proteges par require_partenaire.
  Le JWT partenaire est injecte via le cache sur session_id.
"""

import json
from typing import Optional

from easyvoyage_mcp.client_http import api_get
from easyvoyage_mcp.session_cache import get_jwt


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _clean_str(v):
    """Retourne None si la valeur est 'vide' (None, '', 'null', 'none')."""
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
    """Affiche ce que le tool recoit comme session_id."""
    print("=" * 70)
    print(f"[PARTENAIRE TOOL] {tool_name} appele")
    print(f"[PARTENAIRE TOOL] session_id recu  = {repr(session_id)}")
    print(f"[PARTENAIRE TOOL] type             = {type(session_id).__name__}")
    if isinstance(session_id, str) and session_id.strip():
        cached = get_jwt(session_id.strip())
        print(f"[PARTENAIRE TOOL] JWT dans cache    = {bool(cached)} (len={len(cached) if cached else 0})")
    print("=" * 70)


def _require_session(session_id: Optional[str]) -> Optional[str]:
    """Retourne None si OK, sinon message d'erreur."""
    if not session_id or not isinstance(session_id, str) or not session_id.strip():
        return "Authentification requise : session_id manquant"
    if not get_jwt(session_id.strip()):
        return "Session expiree ou invalide — le partenaire doit renvoyer un message"
    return None


# ══════════════════════════════════════════════════════════
#  RESOLUTION FUZZY PAR NOM — mes hotels uniquement
# ══════════════════════════════════════════════════════════

def _resolve_mon_hotel_id(session_id: str, hotel_nom: str) -> Optional[int]:
    """
    Resout l'ID d'un hotel APPARTENANT AU PARTENAIRE connecte par son nom.
    Utilise /hotels/mes-hotels (deja filtre par JWT backend).
    Tolere accents, casse et correspondances partielles.
    """
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.lower().strip()

    if not hotel_nom:
        return None

    try:
        data = api_get("hotels/mes-hotels", session_id=session_id, per_page=100)
        items = data.get("items", data) if isinstance(data, dict) else data
        if not items:
            return None

        target = _norm(hotel_nom)

        # 1. Match exact
        for h in items:
            if _norm(h.get("nom", "")) == target:
                return h.get("id")

        # 2. Contient la requete
        for h in items:
            if target in _norm(h.get("nom", "")):
                return h.get("id")

        # 3. La requete contient le nom (cas "Hotel Hilton" vs "Hilton")
        for h in items:
            nom_n = _norm(h.get("nom", ""))
            if nom_n and nom_n in target:
                return h.get("id")

        return None
    except Exception as e:
        print(f"[PARTENAIRE] _resolve_mon_hotel_id error: {e}")
        return None


def _resolve_chambre_id_par_type(
    session_id: str,
    hotel_id: int,
    type_nom: str,
) -> Optional[int]:
    """
    Resout l'ID d'une chambre par son type (Standard, Suite, Deluxe, ...).
    Le partenaire dit "la suite" et non "chambre #42".
    """
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.lower().strip()

    if not type_nom:
        return None

    try:
        data = api_get(
            f"hotels/{hotel_id}/chambres",
            session_id=session_id,
            per_page=100,
        )
        items = data.get("items", data) if isinstance(data, dict) else data
        if not items:
            return None

        target = _norm(type_nom)

        # On regarde plusieurs champs possibles selon le schema retourne
        def _chambre_label(ch: dict) -> str:
            return (
                ch.get("type_chambre_nom")
                or (ch.get("type_chambre") or {}).get("nom")
                or ch.get("description")
                or ""
            )

        # 1. Match exact
        for ch in items:
            if _norm(_chambre_label(ch)) == target:
                return ch.get("id")

        # 2. Contient
        for ch in items:
            if target in _norm(_chambre_label(ch)):
                return ch.get("id")

        return None
    except Exception as e:
        print(f"[PARTENAIRE] _resolve_chambre_id error: {e}")
        return None


# ══════════════════════════════════════════════════════════
#  1. PROFIL PARTENAIRE
# ══════════════════════════════════════════════════════════

def partenaire_profil(session_id: str) -> str:
    """
    Recuperer le profil du partenaire connecte (informations personnelles et
    professionnelles). A utiliser quand le partenaire demande : mon profil, mes
    informations, mon compte, qui suis-je, mon email, mon nom de societe, etc.

    Retourne : nom, prenom, email, telephone, role, nom_societe, adresse, etc.
    """
    _debug_session("partenaire_profil", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get("auth/me", session_id=session_id.strip())
        return _ok({"profil": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  2. MES HOTELS — LISTE
# ══════════════════════════════════════════════════════════

def partenaire_mes_hotels(
    session_id: str,
    search:     Optional[str] = None,
    actif:      Optional[bool] = None,
    page:       int            = 1,
    per_page:   int            = 50,
) -> str:
    """
    Lister TOUS les hotels du partenaire connecte. Utiliser pour : mes hotels,
    combien d'hotels j'ai, liste de mes etablissements, quels hotels je gere.

    Filtres :
      - search (str)   : recherche par nom ou ville (partiel, insensible a la casse)
      - actif (bool)   : True=uniquement actifs, False=inactifs, None=tous
      - page, per_page : pagination

    Retourne : liste des hotels avec id, nom, ville, etoiles, note_moyenne,
    nb_chambres, actif, mis_en_avant, etc.
    """
    _debug_session("partenaire_mes_hotels", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        params = {
            "page":     page,
            "per_page": per_page,
        }
        s = _clean_str(search)
        if s:
            params["search"] = s
        if actif is not None:
            params["actif"] = str(actif).lower()

        data = api_get(
            "hotels/mes-hotels",
            session_id=session_id.strip(),
            **params,
        )
        return _ok(data)
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  3. HOTEL — DETAIL PAR NOM
# ══════════════════════════════════════════════════════════

def partenaire_hotel_detail_par_nom(
    session_id: str,
    hotel_nom:  str,
) -> str:
    """
    Detail complet d'UN de mes hotels, recherche par son NOM.
    Utiliser pour : infos completes sur mon hotel, voir les details de X,
    description, adresse, services, photos.

    Parametre OBLIGATOIRE :
      - hotel_nom (str) : nom exact ou partiel de l'hotel

    Retourne : id, nom, ville, pays, adresse, description, etoiles, note_moyenne,
    nb_avis, actif, mis_en_avant, services, images, chambres.
    """
    _debug_session("partenaire_hotel_detail_par_nom", session_id)
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

        data = api_get(f"hotels/{hotel_id}", session_id=sid)
        return _ok({"hotel_nom": nom_clean, "hotel": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  4. AVIS CLIENTS D'UN HOTEL
# ══════════════════════════════════════════════════════════

def partenaire_hotel_avis(
    session_id: str,
    hotel_nom:  str,
    page:       int = 1,
    per_page:   int = 20,
) -> str:
    """
    Avis clients laisses sur UN de mes hotels (par nom).
    Utiliser pour : qu'est-ce que mes clients disent de X, avis sur mon hotel,
    commentaires clients, satisfaction, notes.

    Parametre OBLIGATOIRE :
      - hotel_nom (str) : nom de l'hotel

    Retourne : liste d'avis (note 1-5, commentaire, date, nom client),
    note_moyenne et total.
    """
    _debug_session("partenaire_hotel_avis", session_id)
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

        data = api_get(
            f"hotels/{hotel_id}/avis",
            session_id=sid,
            page=page,
            per_page=per_page,
        )
        return _ok({"hotel_nom": nom_clean, "avis": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  5. CHAMBRES — LISTE D'UN HOTEL
# ══════════════════════════════════════════════════════════

def partenaire_chambres_liste(
    session_id: str,
    hotel_nom:  str,
    actif:      Optional[bool] = None,
    page:       int            = 1,
    per_page:   int            = 50,
) -> str:
    """
    Lister les chambres d'UN de mes hotels (par nom).
    Utiliser pour : mes chambres, types de chambres, capacite, nombre de
    chambres disponibles, inventaire.

    Parametre OBLIGATOIRE :
      - hotel_nom (str) : nom de l'hotel

    Filtres :
      - actif (bool) : True=actives, False=desactivees, None=toutes

    Retourne : liste des chambres avec id, type_chambre_nom, capacite,
    description, nb_chambres, actif.
    """
    _debug_session("partenaire_chambres_liste", session_id)
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

        params = {"page": page, "per_page": per_page}
        if actif is not None:
            params["actif"] = str(actif).lower()

        data = api_get(
            f"hotels/{hotel_id}/chambres",
            session_id=sid,
            **params,
        )
        return _ok({"hotel_nom": nom_clean, "chambres": data})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  6. CHAMBRE — DETAIL
# ══════════════════════════════════════════════════════════

def partenaire_chambre_detail(
    session_id: str,
    hotel_nom:  str,
    type_chambre_nom: str,
) -> str:
    """
    Detail d'UNE chambre specifique d'un hotel (par nom de type : Standard, Suite,
    Deluxe, Familiale, etc.).
    Utiliser pour : info sur ma suite a l'hotel X, capacite de la chambre Deluxe,
    details d'un type de chambre.

    Parametres OBLIGATOIRES :
      - hotel_nom (str)        : nom de l'hotel
      - type_chambre_nom (str) : type de chambre (Suite, Deluxe, Standard...)

    Retourne : id, capacite, description, nb_chambres, type_chambre, actif.
    """
    _debug_session("partenaire_chambre_detail", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    nom_clean  = _clean_str(hotel_nom)
    type_clean = _clean_str(type_chambre_nom)
    if not nom_clean or not type_clean:
        return _err("hotel_nom et type_chambre_nom sont obligatoires")

    try:
        sid = session_id.strip()
        hotel_id = _resolve_mon_hotel_id(sid, nom_clean)
        if not hotel_id:
            return _err(f"Aucun de vos hotels ne correspond a '{nom_clean}'")

        chambre_id = _resolve_chambre_id_par_type(sid, hotel_id, type_clean)
        if not chambre_id:
            return _err(f"Aucune chambre de type '{type_clean}' dans l'hotel '{nom_clean}'")

        data = api_get(
            f"hotels/{hotel_id}/chambres/{chambre_id}",
            session_id=sid,
        )
        return _ok({
            "hotel_nom": nom_clean,
            "type_chambre": type_clean,
            "chambre": data,
        })
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  7. TARIFS — GRILLE TARIFAIRE D'UNE CHAMBRE
# ══════════════════════════════════════════════════════════

def partenaire_tarifs_liste(
    session_id: str,
    hotel_nom:  str,
    type_chambre_nom: str,
) -> str:
    """
    Grille tarifaire (tarifs par saison/periode) d'une chambre d'un hotel.
    Utiliser pour : mes prix, tarifs saisonniers, grille de tarifs, combien je
    facture la chambre X, prix basse/haute saison.

    Parametres OBLIGATOIRES :
      - hotel_nom (str)        : nom de l'hotel
      - type_chambre_nom (str) : type de chambre

    Retourne : liste de tarifs avec prix, date_debut, date_fin, type_reservation.
    """
    _debug_session("partenaire_tarifs_liste", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    nom_clean  = _clean_str(hotel_nom)
    type_clean = _clean_str(type_chambre_nom)
    if not nom_clean or not type_clean:
        return _err("hotel_nom et type_chambre_nom sont obligatoires")

    try:
        sid = session_id.strip()
        hotel_id = _resolve_mon_hotel_id(sid, nom_clean)
        if not hotel_id:
            return _err(f"Aucun de vos hotels ne correspond a '{nom_clean}'")

        chambre_id = _resolve_chambre_id_par_type(sid, hotel_id, type_clean)
        if not chambre_id:
            return _err(f"Aucune chambre de type '{type_clean}' dans '{nom_clean}'")

        data = api_get(
            f"hotels/{hotel_id}/chambres/{chambre_id}/tarifs",
            session_id=sid,
            per_page=100,
        )
        return _ok({
            "hotel_nom": nom_clean,
            "type_chambre": type_clean,
            "tarifs": data,
        })
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  8. DISPONIBILITES — D'UN HOTEL SUR UNE PERIODE
# ══════════════════════════════════════════════════════════

def partenaire_hotel_disponibilites(
    session_id: str,
    hotel_nom:  str,
    date_debut: str,
    date_fin:   str,
) -> str:
    """
    Disponibilites de toutes les chambres d'un hotel sur une periode.
    Utiliser pour : quelles chambres libres du X au Y, taux d'occupation,
    disponibilite sur une periode, chambres encore reservables.

    Parametres OBLIGATOIRES :
      - hotel_nom (str)  : nom de l'hotel
      - date_debut (str) : format YYYY-MM-DD
      - date_fin (str)   : format YYYY-MM-DD

    Retourne : pour chaque type de chambre, nb_total, nb_disponibles,
    nb_reservees, taux_occupation.
    """
    _debug_session("partenaire_hotel_disponibilites", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    nom_clean = _clean_str(hotel_nom)
    dd_clean  = _clean_str(date_debut)
    df_clean  = _clean_str(date_fin)

    if not nom_clean:
        return _err("Le nom de l'hotel est obligatoire")
    if not dd_clean or not df_clean:
        return _err("date_debut et date_fin (YYYY-MM-DD) sont obligatoires")

    try:
        sid = session_id.strip()
        hotel_id = _resolve_mon_hotel_id(sid, nom_clean)
        if not hotel_id:
            return _err(f"Aucun de vos hotels ne correspond a '{nom_clean}'")

        data = api_get(
            f"hotels/{hotel_id}/disponibilites",
            session_id=sid,
            date_debut=dd_clean,
            date_fin=df_clean,
        )
        return _ok({
            "hotel_nom": nom_clean,
            "periode": {"debut": dd_clean, "fin": df_clean},
            "disponibilites": data,
        })
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  9. STATISTIQUES GLOBALES — VUE CONSOLIDEE DE MES HOTELS
# ══════════════════════════════════════════════════════════

def partenaire_hotel_statistiques(session_id: str) -> str:
    """
    Vue consolidee et synthetique de TOUS mes hotels avec KPIs principaux.
    Utiliser pour : bilan global de mes etablissements, vue d'ensemble,
    comparer mes hotels entre eux, quel est mon hotel le mieux note,
    combien de chambres au total.

    Aucun parametre requis.

    Retourne : total hotels, total chambres, note_moyenne_globale,
    classement des hotels par note, liste avec stats par hotel.
    """
    _debug_session("partenaire_hotel_statistiques", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        sid = session_id.strip()
        data = api_get("hotels/mes-hotels", session_id=sid, per_page=100)
        items = data.get("items", data) if isinstance(data, dict) else data

        if not items:
            return _ok({
                "total_hotels": 0,
                "hotels": [],
                "message": "Vous n'avez aucun hotel enregistre",
            })

        # Aggregations
        total         = len(items)
        total_actifs  = sum(1 for h in items if h.get("actif"))
        total_chamb   = sum(h.get("nb_chambres", 0) or 0 for h in items)
        notes         = [h.get("note_moyenne") for h in items if h.get("note_moyenne")]
        note_moyenne  = round(sum(notes) / len(notes), 2) if notes else None

        # Classement par note (desc)
        classement = sorted(
            [h for h in items if h.get("note_moyenne") is not None],
            key=lambda h: h.get("note_moyenne") or 0,
            reverse=True,
        )

        return _ok({
            "total_hotels":         total,
            "total_hotels_actifs":  total_actifs,
            "total_chambres":       total_chamb,
            "note_moyenne_globale": note_moyenne,
            "meilleur_hotel":       classement[0] if classement else None,
            "moins_bon_hotel":      classement[-1] if len(classement) > 1 else None,
            "hotels":               items,
        })
    except Exception as e:
        return _err(e)