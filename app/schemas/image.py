"""
Pydantic schemas pour les images de voyage.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ── Create ────────────────────────────────────────────────────────────────────
class ImageCreate(BaseModel):
    url: str = Field(
        ...,
        examples=["https://res.cloudinary.com/demo/image/upload/sample.jpg"],
        description="URL complète de l'image (https uniquement)",
    )
    type: str = Field(
        default="GALERIE",
        examples=["PRINCIPALE"],
        description="Type : PRINCIPALE | GALERIE | MINIATURE | BANNIERE",
    )

    @field_validator("url")
    @classmethod
    def url_must_be_https(cls, v: str) -> str:
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("L'URL doit commencer par http:// ou https://")
        return v

    @field_validator("type")
    @classmethod
    def type_valide(cls, v: str) -> str:
        allowed = {"PRINCIPALE", "GALERIE", "MINIATURE", "BANNIERE"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"Type invalide. Valeurs acceptées : {allowed}")
        return v


# ── Update (changer uniquement le type) ──────────────────────────────────────
class ImageUpdateType(BaseModel):
    type: str = Field(
        ...,
        examples=["PRINCIPALE"],
        description="Nouveau type : PRINCIPALE | GALERIE | MINIATURE | BANNIERE",
    )

    @field_validator("type")
    @classmethod
    def type_valide(cls, v: str) -> str:
        allowed = {"PRINCIPALE", "GALERIE", "MINIATURE", "BANNIERE"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"Type invalide. Valeurs acceptées : {allowed}")
        return v


# ── Response ──────────────────────────────────────────────────────────────────
class ImageResponse(BaseModel):
    id: int
    url: str
    type: str
    id_voyage: Optional[int]
    id_hotel: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Liste ─────────────────────────────────────────────────────────────────────
class ImageListResponse(BaseModel):
    total: int
    items: List[ImageResponse]