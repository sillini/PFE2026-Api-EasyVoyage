"""
mcp/tools/client_catalog.py
============================
Tools MCP — Catalogue public EasyVoyage (cote CLIENT).

Correspond aux pages publiques du frontend :
  - EasyVoyage.jsx          (landing + liste hotels)
  - HotelDetail.jsx         (detail hotel + chambres + avis)
  - VoyagesOrganises.jsx    (liste voyages organises)
  - VoyageDetail.jsx        (detail voyage)

Tools exposes (9) :
  client_hotels_liste                → GET /hotels
  client_hotel_detail_par_nom        → GET /hotels?nom=... (+ promo active)
  client_hotels_featured             → GET /hotels/featured
  client_villes_vedettes             → GET /hotels/villes-vedettes
  client_hotel_disponibilites        → GET /hotels/{id}/disponibilites/public
  client_voyages_liste               → GET /voyages
  client_voyage_detail_par_titre     → GET /voyages?destination=... + GET /voyages/{id}
  client_promotion_hotel             → GET /promotions/hotels/{id}/active
  client_fiscal_preview              → GET /fiscal/preview

AUCUN JWT REQUIS — tous les endpoints appeles sont publics.

PRINCIPES (identiques au MCP admin) :
  - Recherche par NOM (jamais par ID technique)
  - Defense anti-filtre-fantome (chaines vides → None)
  - Retour JSON normalise : {"ok": True, ...} ou {"ok": False, "error": str}
"""

import json
from typing import Optional

from easyvoyage_mcp.client_http import api_get, resolve_hotel_id_by_name


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


# ══════════════════════════════════════════════════════════
#  1. HOTELS — LISTE
# ══════════════════════════════════════════════════════════

def client_hotels_liste(
    ville:       Optional[str]   = None,
    nom:         Optional[str]   = None,
    etoiles_min: Optional[int]   = None,
    etoiles_max: Optional[int]   = None,
    note_min:    Optional[float] = None,
    page:        int             = 1,
    per_page:    int             = 10,
) -> str:
    """
    Lister les hotels disponibles sur EasyVoyage.

    Filtres OPTIONNELS (OMETTRE si non demandes par l'utilisateur) :
      - ville (str)        : 'Sousse', 'Djerba', 'Tunis', 'Hammamet', 'Monastir'...
      - nom (str)          : recherche partielle dans le nom de l'hotel
      - etoiles_min (1-5)  : etoiles minimum
      - etoiles_max (1-5)  : etoiles maximum
      - note_min (0-5)     : note moyenne minimum (avis clients)
      - page (int)         : defaut 1
      - per_page (int)     : defaut 10, max 100

    Retourne : total, page, per_page, items [id, nom, ville, pays, etoiles,
    note_moyenne, adresse, description, prix_min, prix_min_promo,
    promotion_active, promotion_pourcentage, promotion_titre, partenaire].

    IMPORTANT : ne JAMAIS passer de chaine vide '' — OMETTRE le parametre.
    """
    try:
        data = api_get(
            "hotels",
            ville       = _clean_str(ville),
            nom         = _clean_str(nom),
            etoiles_min = etoiles_min,
            etoiles_max = etoiles_max,
            note_min    = note_min,
            page        = page,
            per_page    = per_page,
        )
        return _ok(data)
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  2. HOTEL — DETAIL PAR NOM
# ══════════════════════════════════════════════════════════

def client_hotel_detail_par_nom(nom: str) -> str:
    """
    Profil detaille d'un hotel par son NOM (jamais par ID technique).

    Parametre OBLIGATOIRE :
      - nom (str) : nom exact ou partiel (ex. 'Carthage', 'Royal Garden')

    Retourne : infos de l'hotel + promotion active si existante.
    Pour voir les chambres disponibles a une date donnee, utiliser ensuite
    client_hotel_disponibilites avec le nom de l'hotel.
    """
    try:
        nom_clean = _clean_str(nom)
        if not nom_clean:
            return _err("Le nom de l'hotel est obligatoire")

        resp = api_get("hotels", nom=nom_clean, per_page=1)
        items = resp.get("items") or []
        if not items:
            return _err(f"Aucun hotel trouve avec le nom '{nom_clean}'")

        hotel = items[0]
        hotel_id = hotel["id"]

        # Promotion active (optionnelle)
        promo = None
        try:
            promo = api_get(f"promotions/hotels/{hotel_id}/active")
        except RuntimeError:
            promo = None

        return _ok({
            "hotel":            hotel,
            "promotion_active": promo,
        })
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  3. HOTELS FEATURED (landing page)
# ══════════════════════════════════════════════════════════

def client_hotels_featured() -> str:
    """
    Liste des hotels MIS EN AVANT sur la page d'accueil EasyVoyage.
    Aucun parametre.
    Utile pour suggerer une selection de qualite au client sans destination precise.

    Retourne : total, items [id, nom, ville, etoiles, note_moyenne,
    prix_min, promotion_active, ...].
    """
    try:
        data = api_get("hotels/featured")
        return _ok(data)
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  4. VILLES VEDETTES
# ══════════════════════════════════════════════════════════

def client_villes_vedettes() -> str:
    """
    Liste des VILLES VEDETTES actives sur EasyVoyage (destinations populaires).
    Aucun parametre.

    Retourne : liste de villes avec leur ordre d'affichage et statut actif.
    """
    try:
        data = api_get("hotels/villes-vedettes")
        items = data if isinstance(data, list) else data.get("items", [])
        return _ok({"items": items, "total": len(items)})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  5. DISPONIBILITES D'UN HOTEL
# ══════════════════════════════════════════════════════════

def client_hotel_disponibilites(
    hotel_nom:    str,
    date_debut:   str,
    date_fin:     str,
    capacite_min: Optional[int] = None,
) -> str:
    """
    Chambres DISPONIBLES dans un hotel entre deux dates (endpoint public).
    Les types de chambres entierement reservees sont automatiquement masques.

    Parametres OBLIGATOIRES :
      - hotel_nom (str)   : nom (exact ou partiel) de l'hotel
      - date_debut (str)  : format YYYY-MM-DD (ex. '2026-06-15')
      - date_fin (str)    : format YYYY-MM-DD (ex. '2026-06-22')

    Parametre OPTIONNEL :
      - capacite_min (int) : filtrer sur capacite minimum (adultes+enfants)

    Retourne : hotel_nom, hotel_ville, disponibilites {hotel_id, date_debut,
    date_fin, chambres [chambre_id, disponible, nb_disponibles, prix_min,
    prix_max, type_chambre, capacite, description]}.
    """
    try:
        nom_clean = _clean_str(hotel_nom)
        dd = _clean_str(date_debut)
        df = _clean_str(date_fin)

        if not nom_clean or not dd or not df:
            return _err("hotel_nom, date_debut et date_fin sont obligatoires")

        hotel_id = resolve_hotel_id_by_name(nom_clean)
        if not hotel_id:
            return _err(f"Aucun hotel trouve avec le nom '{nom_clean}'")

        dispo = api_get(
            f"hotels/{hotel_id}/disponibilites/public",
            date_debut   = dd,
            date_fin     = df,
            capacite_min = capacite_min,
        )

        return _ok({
            "hotel_nom":      nom_clean,
            "disponibilites": dispo,
        })
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  6. VOYAGES — LISTE
# ══════════════════════════════════════════════════════════

def client_voyages_liste(
    destination:     Optional[str]   = None,
    prix_min:        Optional[float] = None,
    prix_max:        Optional[float] = None,
    duree_min:       Optional[int]   = None,
    duree_max:       Optional[int]   = None,
    date_depart_min: Optional[str]   = None,
    date_depart_max: Optional[str]   = None,
    page:            int             = 1,
    per_page:        int             = 10,
) -> str:
    """
    Lister les voyages organises disponibles sur EasyVoyage.

    Filtres OPTIONNELS (OMETTRE si non demandes) :
      - destination (str)       : 'Djerba', 'Sahara', 'Medina', 'Cap Bon'...
      - prix_min / prix_max     : fourchette de prix par personne (DT)
      - duree_min / duree_max   : duree en jours
      - date_depart_min / max   : format YYYY-MM-DD
      - page / per_page         : pagination

    Retourne : total, items [id, titre, destination, duree, prix_base,
    date_depart, date_retour, capacite_max, nb_inscrits, places_restantes,
    actif, admin createur].
    """
    try:
        data = api_get(
            "voyages",
            destination     = _clean_str(destination),
            prix_min        = prix_min,
            prix_max        = prix_max,
            duree_min       = duree_min,
            duree_max       = duree_max,
            date_depart_min = _clean_str(date_depart_min),
            date_depart_max = _clean_str(date_depart_max),
            page            = page,
            per_page        = per_page,
        )
        return _ok(data)
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  7. VOYAGE — DETAIL PAR TITRE OU DESTINATION
# ══════════════════════════════════════════════════════════

def client_voyage_detail_par_titre(titre_ou_destination: str) -> str:
    """
    Detail complet d'un voyage organise par son TITRE ou sa DESTINATION.

    Parametre OBLIGATOIRE :
      - titre_ou_destination (str) : texte de recherche (ex. 'Sahara',
        'Cap Bon', 'Decouverte du Sud')

    Retourne : tous les details du voyage (description, dates, prix par
    personne, capacite, places restantes, duree, admin createur).
    """
    try:
        q = _clean_str(titre_ou_destination)
        if not q:
            return _err("Le titre ou la destination est obligatoire")

        resp = api_get("voyages", destination=q, per_page=1)
        items = resp.get("items") or []
        if not items:
            return _err(f"Aucun voyage trouve pour '{q}'")

        # Recuperer le detail enrichi
        try:
            detail = api_get(f"voyages/{items[0]['id']}")
            voyage = detail
        except Exception:
            voyage = items[0]

        return _ok({"voyage": voyage})
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════
#  8. PROMOTION ACTIVE SUR UN HOTEL
# ══════════════════════════════════════════════════════════

def client_promotion_hotel(hotel_nom: str) -> str:
    """
    Promotion ACTIVE sur un hotel, recherche par son nom.
    Retourne la promo en cours ou indique qu'il n'y en a pas.

    Parametre OBLIGATOIRE :
      - hotel_nom (str) : nom exact ou partiel de l'hotel
    """
    try:
        nom_clean = _clean_str(hotel_nom)
        if not nom_clean:
            return _err("Le nom de l'hotel est obligatoire")

        hotel_id = resolve_hotel_id_by_name(nom_clean)
        if not hotel_id:
            return _err(f"Aucun hotel trouve avec le nom '{nom_clean}'")

        try:
            promo = api_get(f"promotions/hotels/{hotel_id}/active")
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
#  9. FISCAL — PREVIEW (taxe sejour + TVA + timbre)
# ══════════════════════════════════════════════════════════

def client_fiscal_preview(
    montant_ht:    float,
    nb_nuits:      int,
    nb_personnes:  int,
    etoiles_hotel: int,
) -> str:
    """
    Previsualiser le detail fiscal d'une reservation d'hotel (taxe de
    sejour + TVA + droit de timbre) AVANT reservation. Endpoint public.

    Parametres OBLIGATOIRES :
      - montant_ht (float)    : prix hors taxes (DT)
      - nb_nuits (int)        : nombre de nuits
      - nb_personnes (int)    : nombre de personnes (adultes + enfants)
      - etoiles_hotel (1-5)   : etoiles de l'hotel (influence la taxe de sejour)

    Retourne : montant_ht, taxe_sejour, tva_montant, droit_timbre,
    montant_total_ttc, details des regles appliquees.
    """
    try:
        if montant_ht is None or nb_nuits is None or nb_personnes is None or etoiles_hotel is None:
            return _err("Tous les parametres sont obligatoires")

        data = api_get(
            "fiscal/preview",
            montant_ht    = montant_ht,
            nb_nuits      = nb_nuits,
            nb_personnes  = nb_personnes,
            etoiles_hotel = etoiles_hotel,
        )
        return _ok({"detail_fiscal": data})
    except Exception as e:
        return _err(e)