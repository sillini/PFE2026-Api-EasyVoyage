"""
easyvoyage_mcp/client_http.py
==============================
Client HTTP partage pour les tools MCP CLIENT.
VERSION AVEC CACHE JWT + RESOLUTION FUZZY DES NOMS.

CHANGEMENTS :
  - Les tools acceptent session_id (20 chars) au lieu de jwt_token
  - Le JWT est recupere depuis le cache local via HTTP
  - resolve_hotel_id_by_name essaie plusieurs variantes intelligentes
    avant d'abandonner (tolere accents, prefixe Hotel, typos partiels)

API PUBLIQUE :
  api_get(path, session_id="cli_5_abc", **params)
  api_post(path, session_id="cli_5_abc", json={...})
  api_patch(path, session_id="cli_5_abc", json={...})
  api_delete(path, session_id="cli_5_abc")
  resolve_hotel_id_by_name(nom)
  resolve_voyage_id_by_name(titre_ou_destination)

Retro-compatible : accepte aussi `jwt=` directement si fourni (fallback).
"""

import os
import logging
import httpx
import unicodedata
from typing import Any, Optional, List

from dotenv import load_dotenv
load_dotenv()

# Import du cache local
from easyvoyage_mcp.session_cache import get_jwt

logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1").rstrip("/")
TIMEOUT     = float(os.getenv("MCP_CLIENT_HTTP_TIMEOUT", "30.0"))


# ══════════════════════════════════════════════════════════
#  HELPERS INTERNES
# ══════════════════════════════════════════════════════════

def _resolve_jwt(session_id: Optional[str], jwt: Optional[str]) -> Optional[str]:
    """
    Resout le JWT a utiliser :
      1. Si jwt est fourni directement (compat) -> utilise
      2. Sinon, si session_id fourni -> cherche dans le cache
      3. Sinon -> None (endpoint public)
    """
    if jwt:
        return jwt
    if session_id:
        cached = get_jwt(session_id)
        if cached:
            return cached
        logger.warning(f"[MCP] session_id={session_id} introuvable dans le cache")
    return None


def _headers(jwt: Optional[str] = None) -> dict:
    """Construit les headers HTTP, avec JWT Bearer si fourni."""
    h = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
    }
    if jwt:
        h["Authorization"] = f"Bearer {jwt}"
    return h


def _clean_params(params: dict) -> dict:
    """Retire les params vides avant envoi HTTP."""
    clean = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, str):
            s = v.strip()
            if s == "" or s.lower() in ("null", "none", "undefined"):
                continue
            clean[k] = s
        else:
            clean[k] = v
    return clean


def _handle(r: httpx.Response) -> Any:
    """Gere la reponse HTTP."""
    if r.status_code >= 400:
        try:
            payload = r.json()
            detail  = payload.get("detail", payload)
        except Exception:
            detail = r.text or f"HTTP {r.status_code}"
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")

    if r.status_code == 204 or not r.content:
        return {"ok": True, "status": r.status_code}
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


# ══════════════════════════════════════════════════════════
#  API PUBLIQUE
# ══════════════════════════════════════════════════════════

def api_get(
    path: str,
    session_id: Optional[str] = None,
    jwt: Optional[str] = None,
    **params,
) -> Any:
    """GET /api/v1/<path>?param1=..."""
    effective_jwt = _resolve_jwt(session_id, jwt)
    url = f"{BACKEND_URL}/{path.lstrip('/')}"
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.get(url, headers=_headers(effective_jwt), params=_clean_params(params))
    return _handle(r)


def api_post(
    path: str,
    session_id: Optional[str] = None,
    jwt: Optional[str] = None,
    json: Optional[dict] = None,
) -> Any:
    """POST /api/v1/<path> avec body JSON."""
    effective_jwt = _resolve_jwt(session_id, jwt)
    url = f"{BACKEND_URL}/{path.lstrip('/')}"
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(url, headers=_headers(effective_jwt), json=json or {})
    return _handle(r)


def api_patch(
    path: str,
    session_id: Optional[str] = None,
    jwt: Optional[str] = None,
    json: Optional[dict] = None,
) -> Any:
    """PATCH /api/v1/<path>."""
    effective_jwt = _resolve_jwt(session_id, jwt)
    url = f"{BACKEND_URL}/{path.lstrip('/')}"
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.patch(url, headers=_headers(effective_jwt), json=json or {})
    return _handle(r)


def api_delete(
    path: str,
    session_id: Optional[str] = None,
    jwt: Optional[str] = None,
) -> Any:
    """DELETE /api/v1/<path>."""
    effective_jwt = _resolve_jwt(session_id, jwt)
    url = f"{BACKEND_URL}/{path.lstrip('/')}"
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.delete(url, headers=_headers(effective_jwt))
    return _handle(r)


# ══════════════════════════════════════════════════════════
#  HELPERS DE RESOLUTION NOM → ID (avec fuzzy matching)
# ══════════════════════════════════════════════════════════

def _normalize(s: str) -> str:
    """
    Normalise une chaine pour comparaison :
      - Retire les accents
      - Passe en minuscules
      - Normalise les espaces multiples
    """
    if not s:
        return ""
    nfkd = unicodedata.normalize('NFKD', s)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(no_accents.lower().split())


def _extract_search_terms(nom: str) -> List[str]:
    """
    Extrait des termes de recherche intelligents depuis un nom.
    Strategie multi-passes pour tolerer typos et accents.
    """
    if not nom:
        return []

    terms = []
    cleaned = nom.strip()

    # 1. Nom complet
    terms.append(cleaned)

    # 2. Sans prefixe "hotel"/"hôtel"/"hotal"
    norm = _normalize(cleaned)
    for prefix in ("hotel ", "hotal ", "residence ", "riad "):
        if norm.startswith(prefix):
            # Trouver l'index reel dans la chaine d'origine (preserver casse)
            idx = len(prefix)
            stripped = cleaned[idx:].strip() if len(cleaned) > idx else cleaned
            if stripped and stripped not in terms:
                terms.append(stripped)
            break

    # 3. Mots distinctifs (pour recherche partielle)
    stop_words = {"le", "la", "les", "de", "du", "des", "au", "aux",
                  "hotel", "hôtel", "hotal", "residence", "riad",
                  "a", "et", "ou", "un", "une"}
    words = []
    for w in cleaned.split():
        w_clean = w.strip(",.;:!?-()[]")
        if len(w_clean) > 2 and _normalize(w_clean) not in stop_words:
            words.append(w_clean)

    for w in words:
        if w not in terms:
            terms.append(w)

    return terms


def resolve_hotel_id_by_name(nom: str) -> Optional[int]:
    """
    Retourne l'id d'un hotel par son nom, avec recherche tolerante.

    Strategie :
      1. Recherche avec le nom tel quel
      2. Si rien : recherche sans prefixe "Hotel/Hôtel"
      3. Si rien : recherche par mot-cle distinctif
      4. Trouve la meilleure correspondance via similarite normalisee
    """
    if not nom or not nom.strip():
        return None

    target_norm = _normalize(nom)
    search_terms = _extract_search_terms(nom)

    logger.info(f"resolve_hotel_id_by_name({nom!r}): variants={search_terms}")

    all_candidates = {}  # {id: (nom, score)}

    for term in search_terms:
        try:
            resp = api_get("hotels", nom=term, per_page=10)
            items = resp.get("items") or []

            for item in items:
                item_id = item["id"]
                if item_id in all_candidates:
                    continue
                item_nom = item.get("nom", "")
                item_norm = _normalize(item_nom)

                # Score de similarite
                score = 0
                if target_norm == item_norm:
                    score = 100  # match exact apres normalisation
                elif target_norm in item_norm or item_norm in target_norm:
                    score = 80   # inclusion
                else:
                    # Nombre de mots communs
                    target_words = set(target_norm.split())
                    item_words = set(item_norm.split())
                    common = target_words & item_words
                    if common:
                        score = 50 + 10 * len(common)
                    else:
                        score = 10

                all_candidates[item_id] = (item_nom, score)

            # Si match exact trouve, retour immediat
            if any(s == 100 for _, s in all_candidates.values()):
                best = max(all_candidates.items(), key=lambda x: x[1][1])
                logger.info(f"resolve_hotel: match exact id={best[0]} nom={best[1][0]!r}")
                return best[0]

        except Exception as e:
            logger.warning(f"resolve variant {term!r} failed: {e}")
            continue

    if not all_candidates:
        logger.info(f"resolve_hotel: aucun candidat trouve pour {nom!r}")
        return None

    # Retourne le meilleur candidat
    best_id, (best_nom, best_score) = max(
        all_candidates.items(), key=lambda x: x[1][1]
    )
    logger.info(f"resolve_hotel: best match id={best_id} nom={best_nom!r} score={best_score}")
    return best_id


def resolve_voyage_id_by_name(titre_ou_destination: str) -> Optional[int]:
    """
    Retourne l'id d'un voyage par son titre/destination, avec fuzzy.
    Essaie successivement par destination, puis par mots-cles.
    """
    if not titre_ou_destination or not titre_ou_destination.strip():
        return None

    target = titre_ou_destination.strip()
    target_norm = _normalize(target)

    all_candidates = {}  # {id: (titre, score)}

    # Strategie 1 : par destination (nom complet)
    try:
        resp = api_get("voyages", destination=target, per_page=10)
        for item in resp.get("items") or []:
            if item["id"] not in all_candidates:
                titre = item.get("titre", "")
                dest = item.get("destination", "")
                item_norm = _normalize(f"{titre} {dest}")

                if target_norm == _normalize(titre) or target_norm == _normalize(dest):
                    score = 100
                elif target_norm in item_norm:
                    score = 80
                else:
                    score = 40
                all_candidates[item["id"]] = (titre, score)
    except Exception as e:
        logger.warning(f"resolve_voyage destination failed: {e}")

    # Match exact ? on retourne
    if any(s == 100 for _, s in all_candidates.values()):
        best = max(all_candidates.items(), key=lambda x: x[1][1])
        return best[0]

    # Strategie 2 : chaque mot distinctif
    stop_words = {"le", "la", "les", "de", "du", "des", "voyage", "circuit", "sejour"}
    words = [w for w in target.split()
             if len(w) > 2 and _normalize(w) not in stop_words]

    for w in words:
        try:
            resp = api_get("voyages", destination=w, per_page=10)
            for item in resp.get("items") or []:
                if item["id"] not in all_candidates:
                    titre = item.get("titre", "")
                    dest = item.get("destination", "")
                    item_norm = _normalize(f"{titre} {dest}")
                    score = 60 if target_norm in item_norm else 30
                    all_candidates[item["id"]] = (titre, score)
        except Exception:
            continue

    if not all_candidates:
        logger.info(f"resolve_voyage: aucun candidat trouve pour {titre_ou_destination!r}")
        return None

    best_id, (best_titre, best_score) = max(
        all_candidates.items(), key=lambda x: x[1][1]
    )
    logger.info(f"resolve_voyage: best match id={best_id} titre={best_titre!r} score={best_score}")
    return best_id