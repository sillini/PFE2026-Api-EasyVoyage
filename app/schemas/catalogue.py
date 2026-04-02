# app/schemas/catalogue.py
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class CatalogueGenererRequest(BaseModel):
    hotel_ids:  List[int] = []
    voyage_ids: List[int] = []
    titre:      str = "Notre sélection EasyVoyage"


class CatalogueModifierRequest(BaseModel):
    """Modification manuelle avant envoi"""
    titre:          Optional[str]      = None
    description_ia: Optional[str]      = None
    hotel_ids:      Optional[List[int]] = None
    voyage_ids:     Optional[List[int]] = None


class CatalogueEnvoyerRequest(BaseModel):
    destinataires: str = "tous"
    nb_contacts:   int = Field(10, ge=1, le=100)


class CatalogueCreate(BaseModel):
    titre:         str
    destinataires: str       = "tous"
    hotel_ids:     List[int] = []
    voyage_ids:    List[int] = []


class CatalogueResponse(BaseModel):
    id:             int
    titre:          str
    destinataires:  str
    hotel_ids:      Optional[List[int]]
    voyage_ids:     Optional[List[int]]
    description_ia: Optional[str]
    nb_envoyes:     int
    statut:         str
    created_at:     datetime
    envoye_at:      Optional[datetime]
    model_config = {"from_attributes": True}


class CatalogueListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[CatalogueResponse]