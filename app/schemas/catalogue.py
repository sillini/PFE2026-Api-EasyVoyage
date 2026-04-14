# app/schemas/catalogue.py  — REMPLACEZ ENTIÈREMENT CE FICHIER
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class CatalogueGenererRequest(BaseModel):
    hotel_ids:  List[int] = []
    voyage_ids: List[int] = []
    titre:      str = "Notre sélection EasyVoyage"


class CatalogueModifierRequest(BaseModel):
    titre:          Optional[str]       = None
    description_ia: Optional[str]       = None
    hotel_ids:      Optional[List[int]] = None
    voyage_ids:     Optional[List[int]] = None


class CatalogueEnvoyerRequest(BaseModel):
    # Mode automatique
    destinataires:    str  = "tous"          # "tous" | "client" | "visiteur"
    nb_contacts:      int  = Field(50, ge=1, le=500)

    # Mode manuel — PRIORITAIRE si fourni et non vide
    contact_ids:      Optional[List[int]] = None

    # Options
    scheduled_at:     Optional[datetime] = None
    inscrit_depuis:   Optional[datetime] = None
    tracking_enabled: bool = True


class DestinatairesFiltreRequest(BaseModel):
    destinataires:  str            = "tous"
    nb_contacts:    int            = Field(50, ge=1, le=500)
    inscrit_depuis: Optional[datetime] = None


class CatalogueCreate(BaseModel):
    titre:         str
    destinataires: str       = "tous"
    hotel_ids:     List[int] = []
    voyage_ids:    List[int] = []


class SendLogResponse(BaseModel):
    id:          int
    email:       str
    nom:         Optional[str]   = None
    statut:      str
    retry_count: int             = 0
    error_msg:   Optional[str]  = None
    opened_at:   Optional[datetime] = None
    clicked_at:  Optional[datetime] = None
    sent_at:     Optional[datetime] = None
    created_at:  datetime
    model_config = {"from_attributes": True}


class CatalogueResponse(BaseModel):
    id:               int
    titre:            str
    destinataires:    str
    hotel_ids:        Optional[List[int]] = None
    voyage_ids:       Optional[List[int]] = None
    description_ia:   Optional[str]       = None
    nb_envoyes:       int                 = 0
    nb_echecs:        int                 = 0
    statut:           str
    scheduled_at:     Optional[datetime]  = None
    tracking_enabled: bool                = True
    created_at:       datetime
    envoye_at:        Optional[datetime]  = None
    model_config = {"from_attributes": True}


class CatalogueListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[CatalogueResponse]


class CatalogueDetailResponse(CatalogueResponse):
    """Réponse enrichie — utilisée par /detail"""
    hotels:    List[dict] = []
    voyages:   List[dict] = []
    send_logs: List[SendLogResponse] = []