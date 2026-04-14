"""
app/schemas/promotion.py
=========================
Schémas Pydantic pour la gestion des promotions.
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════
#  PROMOTION — CRUD
# ═══════════════════════════════════════════════════════════

class PromotionCreate(BaseModel):
    titre:             str           = Field(..., min_length=3, max_length=200)
    description:       Optional[str] = None
    pourcentage:       float         = Field(..., gt=0, lt=100, examples=[20])
    date_debut:        date
    date_fin:          date
    type_promotion:    str           = Field("STANDARD", examples=["STANDARD"])
    jours_avant_min:   Optional[int] = Field(None, ge=1, le=365)
    jours_avant_max:   Optional[int] = Field(None, ge=1, le=365)
    types_chambre_ids: Optional[List[int]] = None
    actif:             bool          = True

    @field_validator("date_fin")
    @classmethod
    def date_fin_after_debut(cls, v, info):
        if "date_debut" in info.data and v < info.data["date_debut"]:
            raise ValueError("date_fin doit être >= date_debut")
        return v

    @field_validator("type_promotion")
    @classmethod
    def valid_type(cls, v):
        if v not in ("STANDARD", "EARLY_BOOKING", "LAST_MINUTE"):
            raise ValueError("type_promotion invalide")
        return v


class PromotionUpdate(BaseModel):
    titre:             Optional[str]        = Field(None, min_length=3, max_length=200)
    description:       Optional[str]        = None
    pourcentage:       Optional[float]      = Field(None, gt=0, lt=100)
    date_debut:        Optional[date]       = None
    date_fin:          Optional[date]       = None
    type_promotion:    Optional[str]        = None
    jours_avant_min:   Optional[int]        = Field(None, ge=1, le=365)
    jours_avant_max:   Optional[int]        = Field(None, ge=1, le=365)
    types_chambre_ids: Optional[List[int]]  = None
    actif:             Optional[bool]       = None


class HotelMini(BaseModel):
    id:    int
    nom:   str
    ville: Optional[str] = None
    model_config = {"from_attributes": True}


class PromotionResponse(BaseModel):
    id:                int
    titre:             str
    description:       Optional[str]
    id_hotel:          int
    hotel:             Optional[HotelMini] = None
    pourcentage:       float
    type_promotion:    str
    jours_avant_min:   Optional[int]
    jours_avant_max:   Optional[int]
    date_debut:        date
    date_fin:          date
    types_chambre_ids: Optional[List[int]] = None
    actif:             bool
    created_at:        datetime
    updated_at:        datetime

    # ── Champs calculés ─────────────────────────────────
    est_valide_maintenant: bool = False  # promo active ET dans la période
    jours_restants:        Optional[int] = None

    model_config = {"from_attributes": True}


class PromotionListResponse(BaseModel):
    total:    int
    items:    List[PromotionResponse]