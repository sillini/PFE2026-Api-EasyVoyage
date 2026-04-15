# app/schemas/video_campaign.py
"""
Schémas Pydantic pour le module Video Campaigns.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
#  CRÉATION
# ══════════════════════════════════════════════════════════

class VideoCampaignCreate(BaseModel):
    titre: str = Field(..., min_length=3, max_length=300)
    destination: str = Field(..., min_length=2, max_length=200)
    hotel_id: Optional[int] = None
    voyage_id: Optional[int] = None
    ton: str = Field("LUXE", description="LUXE | AVENTURE | FAMILLE | ROMANTIQUE | AFFAIRES")
    formats: List[str] = Field(
        default=["LANDSCAPE"],
        description="Liste de formats : LANDSCAPE, PORTRAIT, SQUARE"
    )
    segment: str = Field("tous", description="tous | client | visiteur")
    contact_ids: Optional[List[int]] = None
    scheduled_at: Optional[datetime] = None
    ab_enabled: bool = False


# ══════════════════════════════════════════════════════════
#  GÉNÉRATION CONTENU (étape 1 : Claude)
# ══════════════════════════════════════════════════════════

class GenererContenuRequest(BaseModel):
    campaign_id: int


class ContenuGenereResponse(BaseModel):
    script_video: str
    sujet_email: str
    description_marketing: str
    cta_texte: str
    hashtags: str
    prompts_images: List[str]


# ══════════════════════════════════════════════════════════
#  GÉNÉRATION VIDÉO (étape 2 : Replicate)
# ══════════════════════════════════════════════════════════

class GenererVideoRequest(BaseModel):
    campaign_id: int
    formats: Optional[List[str]] = None  # override les formats de la campaign si fourni


class VideoStatusResponse(BaseModel):
    campaign_id: int
    statut: str
    replicate_prediction_id: Optional[str] = None
    video_url_landscape: Optional[str] = None
    video_url_portrait: Optional[str] = None
    video_url_square: Optional[str] = None
    thumbnail_url: Optional[str] = None
    erreur: Optional[str] = None


# ══════════════════════════════════════════════════════════
#  ENVOI EMAIL (étape 3 : Brevo)
# ══════════════════════════════════════════════════════════

class EnvoyerVideoCampaignRequest(BaseModel):
    segment: str = "tous"
    contact_ids: Optional[List[int]] = None
    nb_contacts: int = Field(50, ge=1, le=500)
    scheduled_at: Optional[datetime] = None


# ══════════════════════════════════════════════════════════
#  RÉPONSE COMPLÈTE
# ══════════════════════════════════════════════════════════

class VideoCampaignResponse(BaseModel):
    id: int
    titre: str
    destination: str
    hotel_id: Optional[int] = None
    voyage_id: Optional[int] = None
    ton: str
    formats: Optional[List[str]] = None
    segment: str
    statut: str
    erreur: Optional[str] = None

    # Contenu Claude
    script_video: Optional[str] = None
    sujet_email: Optional[str] = None
    description_marketing: Optional[str] = None
    cta_texte: Optional[str] = None
    hashtags: Optional[str] = None
    prompts_images: Optional[List[str]] = None

    # Vidéos Replicate
    replicate_prediction_id: Optional[str] = None
    video_url_landscape: Optional[str] = None
    video_url_portrait: Optional[str] = None
    video_url_square: Optional[str] = None
    thumbnail_url: Optional[str] = None

    # Envoi
    nb_envoyes: int = 0
    nb_echecs: int = 0
    scheduled_at: Optional[datetime] = None
    envoye_at: Optional[datetime] = None

    # A/B
    ab_enabled: bool = False
    ab_variante_sujet: Optional[str] = None
    ab_variante_cta: Optional[str] = None
    ab_gagnant: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VideoCampaignListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[VideoCampaignResponse]


# ══════════════════════════════════════════════════════════
#  COMPTAGE DESTINATAIRES
# ══════════════════════════════════════════════════════════

class DestinataireCountResponse(BaseModel):
    total: int
    segment: str