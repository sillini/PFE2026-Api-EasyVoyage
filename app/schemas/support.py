"""Schemas Pydantic pour le support chat."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ── Utilisateur compact (enrichi pour la recherche admin) ─
class UserCompact(BaseModel):
    id:          int
    nom:         str
    prenom:      str
    role:        str
    email:       Optional[str]       = None   # ← AJOUTÉ : recherche par email
    hotels_noms: Optional[List[str]] = None   # ← AJOUTÉ : noms des hôtels du partenaire
    model_config = {"from_attributes": True}


# ── Message ───────────────────────────────────────────────
class MessageCreate(BaseModel):
    contenu: str = Field(..., min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    id:              int
    id_conversation: int
    id_expediteur:   int
    contenu:         str
    lu:              bool
    created_at:      datetime
    expediteur:      Optional[UserCompact] = None
    model_config = {"from_attributes": True}


# ── Conversation ──────────────────────────────────────────
class ConversationCreate(BaseModel):
    sujet: str = Field("Support général", min_length=2, max_length=300)


class AdminConversationCreate(BaseModel):
    id_partenaire:   int = Field(..., description="ID du partenaire à contacter")
    sujet:           str = Field("Message de l'administration", min_length=2, max_length=300)
    premier_message: Optional[str] = Field(None, max_length=5000)


class ConversationResponse(BaseModel):
    id:            int
    id_partenaire: int
    id_admin:      Optional[int]
    sujet:         str
    statut:        str
    created_at:    datetime
    updated_at:    datetime
    partenaire:    Optional[UserCompact] = None
    admin:         Optional[UserCompact] = None
    messages:      List[MessageResponse] = []
    nb_non_lus:    int = 0
    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    total: int
    items: List[ConversationResponse]


# ── Notification ──────────────────────────────────────────
class NotificationResponse(BaseModel):
    id:              int
    type:            str
    titre:           str
    message:         str
    lue:             bool
    id_conversation: Optional[int]
    created_at:      datetime
    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    total:    int
    nb_lues:  int
    items:    List[NotificationResponse]