"""
Pydantic schemas pour les campagnes marketing.
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Create ────────────────────────────────────────────────────────────────────
class MarketingCreate(BaseModel):
    nom: str = Field(..., min_length=3, max_length=200,
                     examples=["Promo Été 2026"])
    type: str = Field(..., max_length=100,
                      examples=["EMAIL", "RESEAUX_SOCIAUX", "AFFICHAGE", "SMS"])
    budget: float = Field(..., ge=0, examples=[5000.00])
    segment_cible: Optional[str] = Field(
        None, max_length=200, examples=["Familles 30-45 ans"]
    )
    contenu: Optional[str] = Field(
        None, examples=["Profitez de -20% sur tous nos voyages cet été !"]
    )
    date_debut: Optional[date] = Field(None, examples=["2026-06-01"])
    date_fin: Optional[date] = Field(None, examples=["2026-08-31"])

    @model_validator(mode="after")
    def dates_valides(self) -> "MarketingCreate":
        if self.date_debut and self.date_fin:
            if self.date_fin < self.date_debut:
                raise ValueError("date_fin doit être >= date_debut")
        return self


# ── Update ────────────────────────────────────────────────────────────────────
class MarketingUpdate(BaseModel):
    nom: Optional[str] = Field(None, min_length=3, max_length=200)
    type: Optional[str] = Field(None, max_length=100)
    budget: Optional[float] = Field(None, ge=0)
    segment_cible: Optional[str] = None
    contenu: Optional[str] = None
    date_debut: Optional[date] = None
    date_fin: Optional[date] = None

    @model_validator(mode="after")
    def dates_valides(self) -> "MarketingUpdate":
        if self.date_debut and self.date_fin:
            if self.date_fin < self.date_debut:
                raise ValueError("date_fin doit être >= date_debut")
        return self


# ── Action admin (valider / refuser) ─────────────────────────────────────────
class MarketingActionAdmin(BaseModel):
    decision: str = Field(
        ...,
        examples=["ACCEPTEE"],
        description="ACCEPTEE ou REFUSEE",
    )
    commentaire: Optional[str] = Field(
        None, examples=["Campagne conforme à notre charte graphique"]
    )

    @field_validator("decision")
    @classmethod
    def decision_valide(cls, v: str) -> str:
        allowed = {"ACCEPTEE", "REFUSEE"}
        if v not in allowed:
            raise ValueError(f"Decision invalide. Valeurs acceptées : {allowed}")
        return v


# ── Action admin (activer) ────────────────────────────────────────────────────
class MarketingActiverRequest(BaseModel):
    commentaire: Optional[str] = Field(
        None, examples=["Campagne activée — bonne diffusion !"]
    )


# ── Response action admin ─────────────────────────────────────────────────────
class MarketingAdminActionResponse(BaseModel):
    id_marketing: int
    id_admin: int
    date_action: datetime
    commentaire: Optional[str]
    model_config = {"from_attributes": True}


# ── Response ──────────────────────────────────────────────────────────────────
class MarketingResponse(BaseModel):
    id: int
    nom: str
    type: str
    budget: float
    segment_cible: Optional[str]
    contenu: Optional[str]
    statut: str
    date_demande: datetime
    date_debut: Optional[date]
    date_fin: Optional[date]
    id_partenaire: int
    actions_admin: List[MarketingAdminActionResponse] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Liste paginée ─────────────────────────────────────────────────────────────
class MarketingListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[MarketingResponse]