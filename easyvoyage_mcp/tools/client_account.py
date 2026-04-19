"""
easyvoyage_mcp/tools/client_account.py
=======================================
VERSION AVEC DEBUG COMPLET pour diagnostic.
"""

import json
from typing import Optional

from easyvoyage_mcp.client_http import api_get
from easyvoyage_mcp.session_cache import get_jwt


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
    """Affiche ce que le tool reçoit comme session_id."""
    print("=" * 70)
    print(f"[TOOL DEBUG] {tool_name} appelé")
    print(f"[TOOL DEBUG] session_id reçu  = {repr(session_id)}")
    print(f"[TOOL DEBUG] type             = {type(session_id).__name__}")
    if isinstance(session_id, str) and session_id.strip():
        cached = get_jwt(session_id.strip())
        print(f"[TOOL DEBUG] JWT dans cache    = {bool(cached)} (len={len(cached) if cached else 0})")
    print("=" * 70)


def _require_session(session_id: Optional[str]) -> Optional[str]:
    if not session_id or not isinstance(session_id, str) or not session_id.strip():
        return "Authentification requise : session_id manquant"
    if not get_jwt(session_id.strip()):
        return "Session expiree ou invalide — le client doit renvoyer un message"
    return None


# ══════════════════════════════════════════════════════════

def client_profil(session_id: str) -> str:
    """Profil du client connecte."""
    _debug_session("client_profil", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get("auth/me", session_id=session_id.strip())
        return _ok({"profil": data})
    except Exception as e:
        return _err(e)


def client_mes_reservations(
    session_id: str,
    statut:     Optional[str] = None,
    page:       int           = 1,
    per_page:   int           = 10,
) -> str:
    """Liste des reservations du client."""
    _debug_session("client_mes_reservations", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get(
            "reservations/mes-reservations",
            session_id=session_id.strip(),
            statut=_clean_str(statut),
            page=page,
            per_page=per_page,
        )
        return _ok(data)
    except Exception as e:
        return _err(e)


def client_reservation_detail(session_id: str, reservation_id: int) -> str:
    """Detail d'UNE reservation."""
    _debug_session("client_reservation_detail", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    if not reservation_id:
        return _err("reservation_id est obligatoire")
    try:
        data = api_get(f"reservations/{reservation_id}", session_id=session_id.strip())
        return _ok({"reservation": data})
    except Exception as e:
        return _err(e)


def client_mes_favoris(
    session_id: str,
    type:       Optional[str] = None,
    page:       int           = 1,
    per_page:   int           = 12,
) -> str:
    """Liste paginee des favoris."""
    _debug_session("client_mes_favoris", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get(
            "favoris",
            session_id=session_id.strip(),
            type=_clean_str(type),
            page=page,
            per_page=per_page,
        )
        return _ok(data)
    except Exception as e:
        return _err(e)


def client_favori_status(
    session_id:   str,
    hotel_nom:    Optional[str] = None,
    voyage_titre: Optional[str] = None,
) -> str:
    """Verifie si un item est en favoris."""
    _debug_session("client_favori_status", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)

    from easyvoyage_mcp.client_http import (
        resolve_hotel_id_by_name,
        resolve_voyage_id_by_name,
    )

    h_nom = _clean_str(hotel_nom)
    v_titre = _clean_str(voyage_titre)

    if not h_nom and not v_titre:
        return _err("Fournir hotel_nom OU voyage_titre")
    if h_nom and v_titre:
        return _err("Fournir SOIT hotel_nom SOIT voyage_titre")

    try:
        sid = session_id.strip()
        if h_nom:
            id_h = resolve_hotel_id_by_name(h_nom)
            if not id_h:
                return _err(f"Aucun hotel trouve pour '{h_nom}'")
            data = api_get("favoris/status", session_id=sid, id_hotel=id_h)
            return _ok({"item": "hotel", "nom": h_nom, **data})
        else:
            id_v = resolve_voyage_id_by_name(v_titre)
            if not id_v:
                return _err(f"Aucun voyage trouve pour '{v_titre}'")
            data = api_get("favoris/status", session_id=sid, id_voyage=id_v)
            return _ok({"item": "voyage", "titre": v_titre, **data})
    except Exception as e:
        return _err(e)


def client_mes_factures(session_id: str) -> str:
    """Liste des factures du client."""
    _debug_session("client_mes_factures", session_id)
    err = _require_session(session_id)
    if err:
        return _err(err)
    try:
        data = api_get(
            "reservations/mes-reservations",
            session_id=session_id.strip(),
            per_page=100,
        )
        factures = []
        for r in data.get("items", []):
            if r.get("numero_facture"):
                factures.append({
                    "numero_facture":   r["numero_facture"],
                    "statut_facture":   r.get("statut_facture"),
                    "reservation_id":   r["id"],
                    "date_reservation": r.get("date_reservation"),
                    "montant_total":    r.get("total_ttc"),
                    "date_debut":       r.get("date_debut"),
                    "date_fin":         r.get("date_fin"),
                    "type_resa":        "voyage" if r.get("id_voyage") else "hotel",
                })
        return _ok({"total": len(factures), "factures": factures})
    except Exception as e:
        return _err(e)