"""ORM model pour la table hero_slide."""
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class HeroSlide(Base):
    __tablename__ = "hero_slide"
    __table_args__ = {"schema": "voyage_hotel"}

    id:         Mapped[int]           = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    titre:      Mapped[str]           = mapped_column(String(200), nullable=False)
    sous_titre: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    tag:        Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="Offre Spéciale")
    image_url:  Mapped[str]           = mapped_column(Text, nullable=False)
    lien:       Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ordre:      Mapped[int]           = mapped_column(Integer, nullable=False, default=0, index=True)
    actif:      Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return f"<HeroSlide id={self.id} titre={self.titre}>"