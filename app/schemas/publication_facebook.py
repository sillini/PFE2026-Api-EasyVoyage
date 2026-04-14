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

    # ── Interactions (mise à jour manuelle si besoin) ─────
    likes_count:      Optional[int]      = None
    comments_count:   Optional[int]      = None
    shares_count:     Optional[int]      = None
    reactions_count:  Optional[int]      = None
    clicks_count:     Optional[int]      = None
    reach_count:      Optional[int]      = None
    impressions:      Optional[int]      = None
    stats_updated_at: Optional[datetime] = None


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

    # ── Interactions Facebook ─────────────────────────────
    likes_count:      Optional[int]      = 0
    comments_count:   Optional[int]      = 0
    shares_count:     Optional[int]      = 0
    reactions_count:  Optional[int]      = 0
    clicks_count:     Optional[int]      = 0
    reach_count:      Optional[int]      = 0
    impressions:      Optional[int]      = 0
    stats_updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  PUBLICATION — LIST RESPONSE
# ═══════════════════════════════════════════════════════════
class PublicationListResponse(BaseModel):
    total: int
    page:  int
    items: List[PublicationResponse]


# ═══════════════════════════════════════════════════════════
#  INTERACTIONS — SYNC RESPONSE (pour un post)
# ═══════════════════════════════════════════════════════════
class PostInteractionsResponse(BaseModel):
    id:               int
    fb_post_id:       Optional[str]
    likes_count:      int = 0
    comments_count:   int = 0
    shares_count:     int = 0
    reactions_count:  int = 0
    clicks_count:     int = 0
    reach_count:      int = 0
    impressions:      int = 0
    stats_updated_at: Optional[datetime] = None
    synced:           bool = False
    error:            Optional[str] = None


# ═══════════════════════════════════════════════════════════
#  INTERACTIONS — SYNC ALL RESPONSE
# ═══════════════════════════════════════════════════════════
class SyncAllResponse(BaseModel):
    synced:  int
    total:   int
    errors:  List[dict] = []
    message: str


# ═══════════════════════════════════════════════════════════
#  DASHBOARD — RESPONSE GLOBAL
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  DASHBOARD — RESPONSE GLOBAL
# ═══════════════════════════════════════════════════════════
class DashboardResponse(BaseModel):
    # Compteurs de publications
    total_publications: int = 0
    published_count:    int = 0
    draft_count:        int = 0

    # Totaux agrégés des interactions
    total_likes:       int = 0
    total_comments:    int = 0
    total_shares:      int = 0
    total_reactions:   int = 0
    total_clicks:      int = 0
    total_reach:       int = 0
    total_impressions: int = 0

    # Top publication (la plus engagée) — ENRICHI
    top_post_id:            Optional[int]      = None
    top_post_fb_id:         Optional[str]      = None
    top_post_message:       Optional[str]      = None
    top_post_image_url:     Optional[str]      = None
    top_post_type:          Optional[str]      = None
    top_post_published_at:  Optional[datetime] = None
    top_post_likes:         int = 0
    top_post_comments:      int = 0
    top_post_shares:        int = 0
    top_post_engagement:    int = 0

    # Taux d'engagement moyen
    avg_engagement_rate: float = 0.0

    last_sync_at: Optional[datetime] = None

# ═══════════════════════════════════════════════════════════
#  FACEBOOK CONFIG — UPDATE
# ═══════════════════════════════════════════════════════════
class FacebookConfigUpdate(BaseModel):
    page_access_token: str = Field(..., min_length=10)
    page_id:           str = Field(..., min_length=5)
    page_name:         Optional[str]      = None
    token_expires_at:  Optional[datetime] = None


# ═══════════════════════════════════════════════════════════
#  FACEBOOK CONFIG — RESPONSE (sans token pour sécurité)
# ═══════════════════════════════════════════════════════════
class FacebookConfigResponse(BaseModel):
    id:               int
    page_id:          Optional[str]
    page_name:        Optional[str]
    token_actif:      bool
    token_expires_at: Optional[datetime]
    updated_at:       datetime

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