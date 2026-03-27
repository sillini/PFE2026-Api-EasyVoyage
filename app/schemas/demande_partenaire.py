"""
Pydantic schemas pour les demandes d'inscription partenaire.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ── Création d'une demande (visiteur — public) ────────────
class DemandePartenaireCreate(BaseModel):
    nom: str = Field(..., min_length=2, max_length=100)
    prenom: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    telephone: Optional[str] = Field(None, max_length=20)
    nom_entreprise: str = Field(..., min_length=2, max_length=200)
    type_partenaire: str = Field(default="HOTEL", max_length=100)
    site_web: Optional[str] = Field(None, max_length=300)
    adresse: Optional[str] = Field(None, max_length=400)
    message: Optional[str] = Field(None, max_length=1000)


class DemandePartenaireResponse(BaseModel):
    id: int
    nom: str
    prenom: str
    email: str
    telephone: Optional[str]
    nom_entreprise: str
    type_partenaire: str
    site_web: Optional[str]
    adresse: Optional[str]
    message: Optional[str]
    statut: str
    note_admin: Optional[str]
    created_at: datetime
    updated_at: datetime
    traite_at: Optional[datetime]
    model_config = {"from_attributes": True}


class DemandePartenairePublicResponse(BaseModel):
    """Réponse minimale envoyée au visiteur après soumission."""
    id: int
    message: str
    statut: str


# ── Traitement par l'admin ────────────────────────────────
class TraiterDemandeRequest(BaseModel):
    action: str = Field(..., description="CONFIRMER ou ANNULER")
    note_admin: Optional[str] = Field(None, max_length=500)


class TraiterDemandeResponse(BaseModel):
    id: int
    statut: str
    message: str
    partenaire_id: Optional[int] = None  # Si confirmée, l'ID du compte créé


# ── Liste admin ───────────────────────────────────────────
class DemandeListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[DemandePartenaireResponse]