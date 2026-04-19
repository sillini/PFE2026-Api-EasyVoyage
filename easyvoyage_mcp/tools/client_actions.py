"""
easyvoyage_mcp/tools/client_actions.py
=======================================
Tools MCP — Actions sur le compte du CLIENT.
VERSION AVEC SESSION_ID + ACTIONS FINANCIERES DESACTIVEES + SIMULATION ROBUSTE.

POLITIQUE DE SECURITE :
  L'agent IA est un CONSEILLER, pas un executant d'actions financieres.
  Les reservations/paiements/annulations sont INTERDITS via l'assistant.
  Seuls les favoris et les simulations sont autorises.
"""

import json
from typing import Optional, List, Dict

from easyvoyage_mcp.client_http import (
    api_get, api_post,
    resolve_hotel_id_by_name,
    resolve_voyage_id_by_name,
)
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


def _blocked(action_label: str, redirection: str = "Mon compte > Mes reservations") -> str:
    """Reponse standard pour les actions desactivees par securite."""
    return json.dumps({
        "ok": False,
        "blocked": True,
        "error": (
            f"L'action '{action_label}' n'est pas autorisee via l'assistant IA. "
            f"Pour votre securite et la conformite reglementaire, veuillez "
            f"l'effectuer depuis l'interface officielle EasyVoyage."
        ),
        "redirection": redirection,
    }, ensure_ascii=False, indent=2)


def _require_session(session_id: Optional[str]) -> Optional[str]:
    if not session_id or not isinstance(session_id, str) or not session_id.strip():
        return "Authentification requise : session_id manquant"
    if not get_jwt(session_id.strip()):
        return "Session expiree ou invalide"
    return None


# ══════════════════════════════════════════════════════════
#  1. FAVORI TOGGLE (AUTORISE)
# ══════════════════════════════════════════════════════════

def client_favori_toggle(
    session_id:   str,
    hotel_nom:    Optional[str] = None,
    voyage_titre: Optional[str] = None,
) -> str:
    """Ajoute OU retire un hotel/voyage des favoris (sans impact financier)."""
    err = _require_session(session_id)
    if err:
        return _err(err)

    h_nom = _clean_str(hotel_nom)
    v_titre = _clean_str(voyage_titre)

    if not h_nom and not v_titre:
        return _err("Fournir hotel_nom OU voyage_titre")
    if h_nom and v_titre:
        return _err("Fournir SOIT hotel_nom SOIT voyage_titre")

    try:
        sid = session_id.strip()
        body: Dict = {}
        if h_nom:
            id_h = resolve_hotel_id_by_name(h_nom)
            if not id_h:
                return _err(f"Aucun hotel trouve pour '{h_nom}'")
            body["id_hotel"] = id_h
        else:
            id_v = resolve_voyage_id_by_name(v_titre)
            if not id_v:
                return _err(f"Aucun voyage trouve pour '{v_titre}'")
            body["id_voyage"] = id_v

        data = api_post("favoris/toggle", session_id=sid, json=body)
        return _ok({
            "item": "hotel" if h_nom else "voyage",
            "cible": h_nom or v_titre,
            **data,
        })
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  2, 3, 4, 5 — DESACTIVES PAR SECURITE
# ══════════════════════════════════════════════════════════

def client_reserver_voyage(
    session_id:   str,
    voyage_titre: str,
    date_debut:   str,
    date_fin:     str,
    nb_adultes:   int = 1,
    nb_enfants:   int = 0,
) -> str:
    """[DESACTIVE] Reserver un voyage via l'IA n'est pas autorise."""
    return _blocked(
        "reservation de voyage",
        redirection="Page du voyage > bouton 'Reserver'",
    )


def client_reserver_chambres(
    session_id: str,
    date_debut: str,
    date_fin:   str,
    chambres:   List[Dict],
) -> str:
    """[DESACTIVE] Reserver une chambre via l'IA n'est pas autorise."""
    return _blocked(
        "reservation de chambre",
        redirection="Page de l'hotel > bouton 'Reserver'",
    )


def client_payer_reservation(
    session_id:     str,
    reservation_id: int,
    methode:        str = "CARTE_BANCAIRE",
    transaction_id: Optional[str] = None,
) -> str:
    """[DESACTIVE] Le paiement via l'IA n'est pas autorise."""
    return _blocked(
        "paiement de reservation",
        redirection="Mon compte > Mes reservations > Payer",
    )


def client_annuler_reservation(session_id: str, reservation_id: int) -> str:
    """[DESACTIVE] L'annulation via l'IA n'est pas autorisee."""
    return _blocked(
        "annulation de reservation",
        redirection="Mon compte > Mes reservations > Annuler",
    )


# ══════════════════════════════════════════════════════════
#  6. SIMULATION ROBUSTE (AUTORISE — aide a la decision)
# ══════════════════════════════════════════════════════════

def client_simuler_reservation_chambres(
    hotel_nom:  str,
    date_debut: str,
    date_fin:   str,
    nb_adultes: int = 2,
    nb_enfants: int = 0,
) -> str:
    """
    Simulation du prix d'un sejour hotelier. NE RESERVE RIEN.

    STRATEGIE ROBUSTE :
      1. Essaye d'abord via /disponibilites/public (prix par date)
      2. Si pas de prix, fallback sur les prix de base des chambres de l'hotel
      3. Calcule taxes + TVA + timbre via /fiscal/preview
      4. Retourne TOUJOURS une reponse utile (meme avec prix estimatifs)

    Parametres :
      - hotel_nom (str) : nom de l'hotel
      - date_debut (str) : format YYYY-MM-DD
      - date_fin (str)   : format YYYY-MM-DD
      - nb_adultes (int) : defaut 2
      - nb_enfants (int) : defaut 0
    """
    from datetime import date as _d

    nom_clean = _clean_str(hotel_nom)
    dd = _clean_str(date_debut)
    df = _clean_str(date_fin)
    if not nom_clean or not dd or not df:
        return _err("hotel_nom, date_debut et date_fin obligatoires")

    try:
        # ── 1. Calcul du nombre de nuits ──
        try:
            nb_nuits = (_d.fromisoformat(df) - _d.fromisoformat(dd)).days
        except ValueError:
            return _err("Dates invalides (format attendu YYYY-MM-DD)")
        if nb_nuits <= 0:
            return _err("date_fin doit etre apres date_debut")

        # ── 2. Trouve l'hotel ──
        resp = api_get("hotels", nom=nom_clean, per_page=1)
        items = resp.get("items") or []
        if not items:
            return _err(f"Aucun hotel trouve pour '{nom_clean}'")

        hotel = items[0]
        hotel_id = hotel["id"]
        etoiles = hotel.get("etoiles", 3)
        hotel_nom_reel = hotel.get("nom", nom_clean)
        capacite_min = nb_adultes + nb_enfants

        # ── 3. Strategie A : prix dynamique par disponibilites ──
        simulations = []
        source_prix = "disponibilites"

        try:
            dispo = api_get(
                f"hotels/{hotel_id}/disponibilites/public",
                date_debut=dd, date_fin=df,
                capacite_min=capacite_min,
            )
            chambres_dispo = dispo.get("chambres") or []
        except Exception:
            chambres_dispo = []

        for c in chambres_dispo:
            if not c.get("disponible"):
                continue
            prix_nuit = c.get("prix_min")
            if not prix_nuit:
                continue
            simulations.append({
                "type_chambre": (c.get("type_chambre") or {}).get("nom") or "Chambre",
                "capacite":     c.get("capacite"),
                "prix_nuit":    float(prix_nuit),
                "source":       "prix_dynamique",
            })

        # ── 4. Strategie B : fallback sur prix de base des chambres ──
        if not simulations:
            source_prix = "prix_de_base"
            try:
                chambres_resp = api_get(f"hotels/{hotel_id}/chambres")
                # chambres_resp peut etre une liste ou un dict avec items
                if isinstance(chambres_resp, dict):
                    all_chambres = chambres_resp.get("items") or chambres_resp.get("chambres") or []
                else:
                    all_chambres = chambres_resp or []
            except Exception:
                all_chambres = []

            for c in all_chambres:
                # Filtre par capacite
                cap = c.get("capacite", 0)
                if cap < capacite_min:
                    continue
                prix_base = c.get("prix_base") or c.get("prix_nuit") or c.get("prix")
                if not prix_base:
                    continue
                simulations.append({
                    "type_chambre": (
                        c.get("type_chambre_nom")
                        or (c.get("type_chambre") or {}).get("nom")
                        or c.get("nom")
                        or "Chambre"
                    ),
                    "capacite":  cap,
                    "prix_nuit": float(prix_base),
                    "source":    "prix_de_base_estimatif",
                })

        # ── 5. Si toujours rien, retourne info hotel + message clair ──
        if not simulations:
            return _ok({
                "hotel": {
                    "nom": hotel_nom_reel,
                    "ville": hotel.get("ville"),
                    "etoiles": etoiles,
                },
                "date_debut": dd,
                "date_fin": df,
                "nb_nuits": nb_nuits,
                "nb_personnes": capacite_min,
                "simulations": [],
                "message": (
                    f"L'hotel {hotel_nom_reel} n'a pas de prix configures pour "
                    f"{capacite_min} personne(s) du {dd} au {df}. "
                    "Pour obtenir un devis precis, contactez l'hotel via la "
                    "page officielle sur EasyVoyage."
                ),
            })

        # ── 6. Calcule fiscal pour chaque simulation ──
        for sim in simulations:
            montant_ht = round(sim["prix_nuit"] * nb_nuits, 2)
            sim["montant_ht_total"] = montant_ht
            try:
                fiscal = api_get(
                    "fiscal/preview",
                    montant_ht=montant_ht,
                    nb_nuits=nb_nuits,
                    nb_personnes=capacite_min,
                    etoiles_hotel=etoiles,
                )
                sim["fiscal"] = fiscal
                # Ajoute un TTC lisible
                sim["prix_ttc_total"] = fiscal.get("montant_ttc") or fiscal.get("total_ttc")
            except Exception as fe:
                sim["fiscal"] = {"error": str(fe)}

        # ── 7. Tri par prix croissant ──
        simulations.sort(key=lambda s: s.get("prix_ttc_total") or s.get("montant_ht_total") or 9e9)

        # ── 8. Message adapte selon la source des prix ──
        if source_prix == "disponibilites":
            message = (
                f"Simulation pour {nb_nuits} nuit(s) a {hotel_nom_reel} du {dd} au {df} "
                f"pour {capacite_min} personne(s). Prix TTC taxes incluses. "
                "Pour reserver, rendez-vous sur la page de l'hotel sur EasyVoyage."
            )
        else:
            message = (
                f"Simulation ESTIMATIVE basee sur les prix de base (pas de tarification "
                f"dynamique pour ces dates). Prix reels susceptibles de varier. "
                "Pour un devis exact, consultez la page de l'hotel sur EasyVoyage."
            )

        return _ok({
            "hotel": {
                "nom": hotel_nom_reel,
                "ville": hotel.get("ville"),
                "etoiles": etoiles,
            },
            "date_debut": dd,
            "date_fin": df,
            "nb_nuits": nb_nuits,
            "nb_personnes": capacite_min,
            "source_prix": source_prix,
            "simulations": simulations,
            "message": message,
        })
    except Exception as e:
        return _err(e)