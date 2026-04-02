# app/models/catalogue.py
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, Enum, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class StatutCatalogue(str, enum.Enum):
    BROUILLON = "BROUILLON"
    ENVOYE    = "ENVOYE"
    ECHOUE    = "ECHOUE"

class Catalogue(Base):
    __tablename__ = "catalogue"

    id:              Mapped[int]           = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    titre:           Mapped[str]           = mapped_column(String(300), nullable=False)
    destinataires:   Mapped[str]           = mapped_column(String(20),  nullable=False, default="tous")
    hotel_ids:       Mapped[Optional[str]] = mapped_column(JSON,        nullable=True)
    voyage_ids:      Mapped[Optional[str]] = mapped_column(JSON,        nullable=True)
    description_ia:  Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    html_contenu:    Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    nb_envoyes:      Mapped[int]           = mapped_column(BigInteger,  nullable=False, default=0)
    statut:          Mapped[StatutCatalogue] = mapped_column(
        Enum(StatutCatalogue, name="statut_catalogue", schema="voyage_hotel"),
        nullable=False, default=StatutCatalogue.BROUILLON
    )
    created_by:      Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    envoye_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)