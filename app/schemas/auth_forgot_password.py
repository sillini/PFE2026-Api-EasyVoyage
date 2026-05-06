"""
app/schemas/auth_forgot_password.py
====================================
Schémas Pydantic pour le flux "Mot de passe oublié".

3 étapes :
  1. ForgotPasswordRequest      → POST /auth/forgot-password/request
  2. ForgotPasswordVerifyRequest → POST /auth/forgot-password/verify
  3. ForgotPasswordResetRequest  → POST /auth/forgot-password/reset

Note : à fusionner dans `app/schemas/auth.py` à la fin du fichier
       (gardé séparé ici pour clarté de la livraison).
"""
import re
from pydantic import BaseModel, EmailStr, Field, model_validator


# ── Étape 1 : demander un code (email) ───────────────────────────
class ForgotPasswordRequest(BaseModel):
    """Body pour POST /auth/forgot-password/request"""
    email: EmailStr = Field(..., examples=["client@example.com"])


# ── Étape 2 : vérifier le code ───────────────────────────────────
class ForgotPasswordVerifyRequest(BaseModel):
    """Body pour POST /auth/forgot-password/verify"""
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


# ── Étape 3 : reset du mot de passe ──────────────────────────────
class ForgotPasswordResetRequest(BaseModel):
    """Body pour POST /auth/forgot-password/reset"""
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_passwords(self) -> "ForgotPasswordResetRequest":
        # 1. Confirmation identique
        if self.new_password != self.confirm_password:
            raise ValueError("Les mots de passe ne correspondent pas")

        # 2. Force du mot de passe (cohérent avec l'inscription)
        pwd = self.new_password
        if len(pwd) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        if not re.search(r"[A-Z]", pwd):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not re.search(r"[a-z]", pwd):
            raise ValueError("Le mot de passe doit contenir au moins une minuscule")
        if not re.search(r"\d", pwd):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        return self


# ── Réponses ──────────────────────────────────────────────────────
class ForgotPasswordResponse(BaseModel):
    """Réponse standard pour les étapes 1 & 2."""
    message: str
    email: str


class ForgotPasswordVerifyResponse(BaseModel):
    """Réponse pour la vérification du code (étape 2)."""
    valid: bool
    message: str


class ForgotPasswordResetResponse(BaseModel):
    """Réponse pour le reset final (étape 3)."""
    message: str