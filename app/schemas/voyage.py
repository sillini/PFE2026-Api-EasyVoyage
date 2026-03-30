"""
Pydantic schemas pour les voyages.
"""
from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator


# ── Admin info embarqué ───────────────────────────────────────────────────────
class AdminInfo(BaseModel):
    id: int
    nom: str
    prenom: str
    email: str
    model_config = {"from_attributes": True}


# ── Create ────────────────────────────────────────────────────────────────────
class VoyageCreate(BaseModel):
    titre: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None
    destination: str = Field(..., max_length=200)
    duree: int = Field(..., gt=0)
    prix_base: float = Field(..., ge=0)
    date_depart: date
    date_retour: date
    capacite_max: int = Field(..., gt=0)

    @model_validator(mode="after")
    def dates_valides(self) -> "VoyageCreate":
        if self.date_retour <= self.date_depart:
            raise ValueError("La date de retour doit être après la date de départ")
        return self


# ── Update ────────────────────────────────────────────────────────────────────
class VoyageUpdate(BaseModel):
    titre: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = None
    destination: Optional[str] = Field(None, max_length=200)
    duree: Optional[int] = Field(None, gt=0)
    prix_base: Optional[float] = Field(None, ge=0)
    date_depart: Optional[date] = None
    date_retour: Optional[date] = None
    capacite_max: Optional[int] = Field(None, gt=0)
    actif: Optional[bool] = None

    @model_validator(mode="after")
    def dates_valides(self) -> "VoyageUpdate":
        if self.date_depart and self.date_retour:
            if self.date_retour <= self.date_depart:
                raise ValueError("La date de retour doit être après la date de départ")
        return self


# ── Response ──────────────────────────────────────────────────────────────────
class VoyageResponse(BaseModel):
    id: int
    titre: str
    description: Optional[str]
    destination: str
    duree: int
    prix_base: float
    date_depart: date
    date_retour: date
    capacite_max: int
    nb_inscrits: int = 0         # ← nombre de personnes avec réservation CONFIRMEE
    places_restantes: int = 0    # ← calculé côté service : capacite_max - nb_inscrits
    actif: bool
    id_admin: Optional[int] = None
    admin: Optional[AdminInfo] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Liste paginée ─────────────────────────────────────────────────────────────
class VoyageListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[VoyageResponse]