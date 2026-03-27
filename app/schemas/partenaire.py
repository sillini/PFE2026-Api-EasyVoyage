"""
Pydantic schemas pour la gestion admin des partenaires.
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


# ── Étape 1 : invitation (envoi OTP) ──────────────────────
class InvitePartenaireRequest(BaseModel):
    email: EmailStr = Field(..., description="Email du futur partenaire")


class InvitePartenaireResponse(BaseModel):
    message: str
    email: str


# ── Étape 2 : vérification du code OTP ───────────────────
class VerifyOTPRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class VerifyOTPResponse(BaseModel):
    valid: bool
    message: str
    token: Optional[str] = None   # Token temporaire pour l'étape 3


# ── Étape 3 : création du compte partenaire ──────────────
class CreatePartenaireRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    nom: str = Field(..., min_length=2, max_length=100)
    prenom: str = Field(..., min_length=2, max_length=100)
    telephone: Optional[str] = Field(None, max_length=20)
    nom_entreprise: str = Field(..., min_length=2, max_length=200)
    type_partenaire: str = Field(default="HOTEL", max_length=100)


class CreatePartenaireResponse(BaseModel):
    id: int
    nom: str
    prenom: str
    email: str
    nom_entreprise: str
    type_partenaire: str
    statut: str
    message: str


# ── Partenaire info embarqué dans les listes ─────────────
class HotelBriefResponse(BaseModel):
    id: int
    nom: str
    etoiles: int
    pays: str
    actif: bool
    model_config = {"from_attributes": True}


class PartenaireAdminResponse(BaseModel):
    id: int
    nom: str
    prenom: str
    email: str
    telephone: Optional[str]
    actif: bool
    nom_entreprise: str
    type_partenaire: str
    statut: str
    commission: float
    date_inscription: datetime
    hotels: List[HotelBriefResponse] = []
    model_config = {"from_attributes": True}


class PartenaireListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[PartenaireAdminResponse]


# ── Toggle actif ─────────────────────────────────────────
class TogglePartenaireRequest(BaseModel):
    actif: bool