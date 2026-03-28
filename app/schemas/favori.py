"""
Schémas Pydantic — Favoris client.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ── Réponse hôtel simplifié ────────────────────────────────
class HotelBriefFavori(BaseModel):
    id:           int
    nom:          str
    ville:        Optional[str]
    pays:         str
    etoiles:      int
    note_moyenne: Optional[float]
    model_config = {"from_attributes": True}


# ── Réponse voyage simplifié ───────────────────────────────
class VoyageBriefFavori(BaseModel):
    id:          int
    titre:       str
    destination: str
    prix_base:   float
    duree:       int
    date_depart: str
    model_config = {"from_attributes": True}


# ── Réponse favori ─────────────────────────────────────────
class FavoriResponse(BaseModel):
    id:         int
    type:       str               # "hotel" | "voyage"
    id_hotel:   Optional[int]
    id_voyage:  Optional[int]
    hotel:      Optional[HotelBriefFavori]
    voyage:     Optional[VoyageBriefFavori]
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Liste paginée ──────────────────────────────────────────
class FavoriListResponse(BaseModel):
    total:        int
    nb_hotels:    int
    nb_voyages:   int
    items:        List[FavoriResponse]


# ── Réponse toggle ─────────────────────────────────────────
class FavoriToggleResponse(BaseModel):
    favori:  bool     # True = ajouté, False = retiré
    message: str


# ── Réponse status ─────────────────────────────────────────
class FavoriStatusResponse(BaseModel):
    id_hotel:  Optional[int]
    id_voyage: Optional[int]
    favori:    bool