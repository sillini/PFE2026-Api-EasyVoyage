"""Schemas Pydantic pour HeroSlide."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, HttpUrl


class HeroSlideCreate(BaseModel):
    titre:      str           = Field(..., min_length=2, max_length=200)
    sous_titre: Optional[str] = Field(None, max_length=300)
    tag:        Optional[str] = Field("Offre Spéciale", max_length=100)
    image_url:  str           = Field(..., description="URL Cloudinary de l'image")
    lien:       Optional[str] = Field(None, max_length=500)
    ordre:      int           = Field(0, ge=0)
    actif:      bool          = True


class HeroSlideUpdate(BaseModel):
    titre:      Optional[str] = Field(None, min_length=2, max_length=200)
    sous_titre: Optional[str] = None
    tag:        Optional[str] = Field(None, max_length=100)
    image_url:  Optional[str] = None
    lien:       Optional[str] = None
    ordre:      Optional[int] = Field(None, ge=0)
    actif:      Optional[bool] = None


class HeroSlideResponse(BaseModel):
    id:         int
    titre:      str
    sous_titre: Optional[str]
    tag:        Optional[str]
    image_url:  str
    lien:       Optional[str]
    ordre:      int
    actif:      bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class HeroSlideListResponse(BaseModel):
    total: int
    items: List[HeroSlideResponse]