"""
app/schemas/agent_ia.py
========================
Schémas Pydantic pour les endpoints Agent IA.
"""
from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


# ══════════════════════════════════════════════════════════
#  MESSAGE
# ══════════════════════════════════════════════════════════

class MessageBase(BaseModel):
    role:    str
    contenu: str


class MessageResponse(MessageBase):
    model_config = ConfigDict(from_attributes=True)
    id:         int
    tokens:     Optional[int] = None
    duree_ms:   Optional[int] = None
    is_error:   bool = False
    extra_data: Optional[Dict[str, Any]] = None   # ← renommé (anciennement 'metadata')
    created_at: datetime


class SendMessageRequest(BaseModel):
    """Payload envoyé par le frontend pour envoyer un message."""
    message: str = Field(..., min_length=1, max_length=8000)
    # Si absent → créer une nouvelle conversation
    conversation_id: Optional[int] = None


class SendMessageResponse(BaseModel):
    """Réponse non-streaming après envoi complet."""
    conversation_id: int
    session_id:      str
    user_message:    MessageResponse
    assistant_message: MessageResponse
    titre:           str


# ══════════════════════════════════════════════════════════
#  CONVERSATION
# ══════════════════════════════════════════════════════════

class ConversationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:              int
    titre:           str
    nb_messages:     int
    last_message_at: datetime
    created_at:      datetime


class ConversationListResponse(BaseModel):
    total: int
    items: List[ConversationListItem]


class ConversationDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:              int
    session_id:      str
    titre:           str
    nb_messages:     int
    tokens_total:    int
    created_at:      datetime
    updated_at:      datetime
    last_message_at: datetime
    messages:        List[MessageResponse]


class UpdateConversationRequest(BaseModel):
    titre: str = Field(..., min_length=1, max_length=200)


class SimpleOkResponse(BaseModel):
    ok: bool = True
    message: Optional[str] = None