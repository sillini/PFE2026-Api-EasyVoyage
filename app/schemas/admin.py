"""
app/schemas/admin.py
====================
Pydantic schemas pour la gestion Super Admin des administrateurs.

Workflow d'invitation (3 étapes, identique aux partenaires) :
  1. invite       → POST /admin/admins/invite       (email)
  2. verify-code  → POST /admin/admins/verify-code  (email + code)
  3. create       → POST /admin/admins/create       (email + code + nom + prénom + tél)
                    ↳ génère un mot de passe + envoie email de bienvenue
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# ── Étape 1 : invitation (envoi OTP) ──────────────────────
class InviteAdminRequest(BaseModel):
    email: EmailStr = Field(..., description="Email du futur administrateur")


class InviteAdminResponse(BaseModel):
    message: str
    email: str


# ── Étape 2 : vérification du code OTP ────────────────────
class VerifyAdminOTPRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class VerifyAdminOTPResponse(BaseModel):
    valid: bool
    message: str


# ── Étape 3 : création du compte admin ────────────────────
class CreateAdminRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    nom: str = Field(..., min_length=2, max_length=100)
    prenom: str = Field(..., min_length=2, max_length=100)
    telephone: Optional[str] = Field(None, max_length=20)
    # ⚠️ Volontairement PAS d'option is_super_admin ici :
    # Un Super Admin ne peut être créé que manuellement en BDD (sécurité).
    # Tous les admins créés via cette interface sont des admins standards.


class CreateAdminResponse(BaseModel):
    id: int
    nom: str
    prenom: str
    email: str
    is_super_admin: bool
    actif: bool
    message: str


# ── Lecture / liste ───────────────────────────────────────
class AdminResponse(BaseModel):
    id: int
    nom: str
    prenom: str
    email: str
    telephone: Optional[str] = None
    actif: bool
    is_super_admin: bool
    date_inscription: datetime
    derniere_connexion: Optional[datetime] = None
    model_config = {"from_attributes": True}


class AdminListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[AdminResponse]


# ── Toggle actif ──────────────────────────────────────────
class ToggleAdminRequest(BaseModel):
    actif: bool


# ── Update (édition partielle nom/prénom/téléphone) ───────
class UpdateAdminRequest(BaseModel):
    nom: Optional[str] = Field(None, min_length=2, max_length=100)
    prenom: Optional[str] = Field(None, min_length=2, max_length=100)
    telephone: Optional[str] = Field(None, max_length=20)