"""
Pydantic schemas for authentication:
  - Registration (client, partenaire)
  - Login request / response
  - Token payload
  - Current user response
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


# ── Shared base ───────────────────────────────────────────────────────────────
class _UserBase(BaseModel):
    nom: str = Field(..., min_length=2, max_length=100, examples=["Ben Ali"])
    prenom: str = Field(..., min_length=2, max_length=100, examples=["Mohamed"])
    email: EmailStr = Field(..., examples=["contact@example.com"])
    telephone: str | None = Field(None, examples=["+21698765432"])


# ── Registration schemas ──────────────────────────────────────────────────────
class ClientRegisterRequest(_UserBase):
    """Body for POST /auth/register/client"""
    password: str = Field(..., min_length=8, examples=["StrongPass1!"])
    password_confirm: str = Field(..., examples=["StrongPass1!"])

    @model_validator(mode="after")
    def passwords_match(self) -> "ClientRegisterRequest":
        if self.password != self.password_confirm:
            raise ValueError("Les mots de passe ne correspondent pas")
        return self


class PartenaireRegisterRequest(_UserBase):
    """Body for POST /auth/register/partenaire"""
    password: str = Field(..., min_length=8, examples=["StrongPass1!"])
    password_confirm: str = Field(..., examples=["StrongPass1!"])
    nom_entreprise: str = Field(..., min_length=2, max_length=200, examples=["Hôtel Carthage"])
    type_partenaire: str = Field(..., max_length=100, examples=["HOTEL"])

    @model_validator(mode="after")
    def passwords_match(self) -> "PartenaireRegisterRequest":
        if self.password != self.password_confirm:
            raise ValueError("Les mots de passe ne correspondent pas")
        return self


# ── Login ─────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    """Body for POST /auth/login"""
    email: EmailStr = Field(..., examples=["contact@example.com"])
    password: str = Field(..., examples=["StrongPass1!"])


class TokenResponse(BaseModel):
    """Returned after successful login or token refresh."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


class RefreshTokenRequest(BaseModel):
    """Body for POST /auth/refresh"""
    refresh_token: str


# ── Current user ──────────────────────────────────────────────────────────────
class UserMeResponse(BaseModel):
    """Returned by GET /auth/me"""
    id: int
    nom: str
    prenom: str
    email: str
    telephone: str | None
    role: str
    actif: bool
    date_inscription: datetime
    derniere_connexion: datetime | None

    # Extra fields for partenaire
    nom_entreprise: str | None = None
    type_partenaire: str | None = None
    commission: float | None = None
    statut_partenaire: str | None = None

    model_config = {"from_attributes": True}


# ── Token data (internal) ─────────────────────────────────────────────────────
class TokenData(BaseModel):
    """Decoded JWT payload (used internally by dependencies)."""
    user_id: int
    role: str
    token_type: str


# ── Profil Update ─────────────────────────────────────────
class UpdateProfileRequest(BaseModel):
    """Mise à jour champs simples (sans vérification email)"""
    nom:            Optional[str] = Field(None, min_length=2, max_length=100)
    prenom:         Optional[str] = Field(None, min_length=2, max_length=100)
    telephone:      Optional[str] = Field(None, max_length=20)
    nom_entreprise: Optional[str] = Field(None, min_length=2, max_length=200)

class RequestEmailChangeRequest(BaseModel):
    """Étape 1 : demander changement email — envoie OTP"""
    new_email: EmailStr

class ConfirmEmailChangeRequest(BaseModel):
    """Étape 2 : confirmer avec OTP"""
    new_email: EmailStr
    code:      str = Field(..., min_length=6, max_length=6)

class RequestPasswordChangeRequest(BaseModel):
    """Étape 1 : demander changement mot de passe — envoie OTP"""
    pass  # juste envoyer OTP à l'email courant

class ConfirmPasswordChangeRequest(BaseModel):
    """Étape 2 : confirmer avec OTP + nouveau mdp"""
    code:             str = Field(..., min_length=6, max_length=6)
    new_password:     str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

    @model_validator(mode="after")
    def passwords_match(self) -> "ConfirmPasswordChangeRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Les mots de passe ne correspondent pas")
        return self

class ProfileOTPResponse(BaseModel):
    message: str
    email:   str