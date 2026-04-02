"""
app/schemas/publication_facebook.py
=====================================
Pydantic schemas pour les publications Facebook et la config.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
#  PUBLICATION — CREATE
# ═══════════════════════════════════════════════════════════
class PublicationCreate(BaseModel):
    message:       str
    type_contenu:  str = "hotel"
    image_url:     Optional[str] = None
    statut:        str = "DRAFT"
    scheduled_at:  Optional[datetime] = None
    fb_post_id:    Optional[str] = None
    published_at:  Optional[datetime] = None


# ═══════════════════════════════════════════════════════════
#  PUBLICATION — UPDATE
# ═══════════════════════════════════════════════════════════
class PublicationUpdate(BaseModel):
    message:       Optional[str]      = None
    type_contenu:  Optional[str]      = None
    image_url:     Optional[str]      = None
    statut:        Optional[str]      = None
    scheduled_at:  Optional[datetime] = None
    fb_post_id:    Optional[str]      = None
    published_at:  Optional[datetime] = None
    error_message: Optional[str]      = None


# ═══════════════════════════════════════════════════════════
#  PUBLICATION — RESPONSE
# ═══════════════════════════════════════════════════════════
class PublicationResponse(BaseModel):
    id:            int
    message:       str
    type_contenu:  str
    image_url:     Optional[str]
    statut:        str
    fb_post_id:    Optional[str]
    scheduled_at:  Optional[datetime]
    published_at:  Optional[datetime]
    error_message: Optional[str]
    id_admin:      Optional[int]
    created_at:    datetime
    updated_at:    datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  PUBLICATION — LIST RESPONSE
# ═══════════════════════════════════════════════════════════
class PublicationListResponse(BaseModel):
    total:   int
    page:    int
    items:   List[PublicationResponse]


# ═══════════════════════════════════════════════════════════
#  FACEBOOK CONFIG — UPDATE
# ═══════════════════════════════════════════════════════════
class FacebookConfigUpdate(BaseModel):
    page_access_token: str = Field(..., min_length=10)
    page_id:           str = Field(..., min_length=5)
    page_name:         Optional[str] = None
    token_expires_at:  Optional[datetime] = None


# ═══════════════════════════════════════════════════════════
#  FACEBOOK CONFIG — RESPONSE (sans token pour sécurité)
# ═══════════════════════════════════════════════════════════
class FacebookConfigResponse(BaseModel):
    id:                int
    page_id:           Optional[str]
    page_name:         Optional[str]
    token_actif:       bool
    token_expires_at:  Optional[datetime]
    updated_at:        datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  FACEBOOK CONFIG — TOKEN RESPONSE (avec token complet)
#  Utilisé uniquement pour les publications internes
# ═══════════════════════════════════════════════════════════
class FacebookTokenResponse(BaseModel):
    page_access_token: str
    page_id:           str
    page_name:         Optional[str]


# ═══════════════════════════════════════════════════════════
#  DELETE FROM FACEBOOK — REQUEST
# ═══════════════════════════════════════════════════════════
class DeleteFromFacebookRequest(BaseModel):
    delete_from_facebook: bool = True