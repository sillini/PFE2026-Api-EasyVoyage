"""
app/schemas/promotion.py
=========================
Schémas Pydantic pour la gestion des promotions.

Workflow :
  PromotionCreate  → partenaire crée (statut PENDING automatique)
  PromotionUpdate  → partenaire modifie (uniquement si PENDING)
  DecisionAdmin    → admin accepte ou refuse
  PromotionResponse → réponse complète avec statut + infos admin
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════
#  CRÉATION — PARTENAIRE
# ═══════════════════════════════════════════════════════════

class PromotionCreate(BaseModel):
    titre:       str           = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None
    pourcentage: float         = Field(..., gt=0, lt=100, examples=[20])
    date_debut:  date
    date_fin:    date

    @field_validator("date_fin")
    @classmethod
    def date_fin_after_debut(cls, v, info):
        if "date_debut" in info.data and v < info.data["date_debut"]:
            raise ValueError("date_fin doit être >= date_debut")
        return v


# ═══════════════════════════════════════════════════════════
#  MODIFICATION — PARTENAIRE (uniquement si PENDING)
# ═══════════════════════════════════════════════════════════

class PromotionUpdate(BaseModel):
    titre:       Optional[str]   = Field(None, min_length=3, max_length=200)
    description: Optional[str]   = None
    pourcentage: Optional[float] = Field(None, gt=0, lt=100)
    date_debut:  Optional[date]  = None
    date_fin:    Optional[date]  = None


# ═══════════════════════════════════════════════════════════
#  DÉCISION ADMIN — accepter ou refuser
# ═══════════════════════════════════════════════════════════

class DecisionAdmin(BaseModel):
    action:       str            = Field(..., description="APPROVED | REJECTED")
    raison_refus: Optional[str] = Field(None, max_length=500)

    @field_validator("action")
    @classmethod
    def valid_action(cls, v):
        if v not in ("APPROVED", "REJECTED"):
            raise ValueError("action doit être APPROVED ou REJECTED")
        return v


# ═══════════════════════════════════════════════════════════
#  SOUS-SCHÉMAS EMBARQUÉS
# ═══════════════════════════════════════════════════════════

class HotelMini(BaseModel):
    id:    int
    nom:   str
    ville: Optional[str] = None
    model_config = {"from_attributes": True}


class UserMini(BaseModel):
    id:     int
    nom:    str
    prenom: str
    email:  str
    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  RÉPONSE COMPLÈTE
# ═══════════════════════════════════════════════════════════

class PromotionResponse(BaseModel):
    id:          int
    titre:       str
    description: Optional[str]
    id_hotel:    int
    hotel:       Optional[HotelMini] = None

    pourcentage: float
    date_debut:  date
    date_fin:    date

    # ── Workflow ─────────────────────────────────────────
    statut:              str  # PENDING | APPROVED | REJECTED
    actif:               bool
    raison_refus:        Optional[str]    = None
    date_decision:       Optional[datetime] = None
    id_admin_validateur: Optional[int]    = None
    validateur:          Optional[UserMini] = None
    id_partenaire:       Optional[int]    = None
    partenaire:          Optional[UserMini] = None

    # ── Champs calculés ──────────────────────────────────
    est_valide_maintenant: bool          = False
    jours_restants:        Optional[int] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromotionListResponse(BaseModel):
    total: int
    items: List[PromotionResponse]


# ═══════════════════════════════════════════════════════════
#  COMPTEUR ADMIN — nombre de demandes en attente
# ═══════════════════════════════════════════════════════════

class PromotionPendingCount(BaseModel):
    pending: int