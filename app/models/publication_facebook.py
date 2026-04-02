"""
app/models/publication_facebook.py
===================================
Modèle SQLAlchemy pour les publications Facebook.

Tables :
  - publication_facebook  : publications créées par l'admin
  - facebook_config       : configuration du token Facebook de l'admin
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum as SAEnum,
    ForeignKey, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StatutPublication(str, enum.Enum):
    DRAFT     = "DRAFT"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED    = "FAILED"
    DELETED   = "DELETED"


class TypePublication(str, enum.Enum):
    HOTEL     = "hotel"
    VOYAGE    = "voyage"
    PROMOTION = "promotion"
    OFFRE     = "offre"


class PublicationFacebook(Base):
    __tablename__  = "publication_facebook"
    __table_args__ = {"schema": "voyage_hotel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Contenu
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # ✅ values_callable force "hotel" au lieu de "HOTEL"
    type_contenu: Mapped[TypePublication] = mapped_column(
        SAEnum(
            TypePublication,
            name="type_publication",
            schema="voyage_hotel",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=TypePublication.HOTEL,
    )

    image_url:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fb_post_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # ✅ values_callable pour statut aussi
    statut: Mapped[StatutPublication] = mapped_column(
        SAEnum(
            StatutPublication,
            name="statut_publication",
            schema="voyage_hotel",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=StatutPublication.DRAFT,
    )

    scheduled_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]]      = mapped_column(Text, nullable=True)

    # FK vers utilisateur — sans schema dans ForeignKey car utilisateur
    # est déjà dans voyage_hotel via son propre __table_args__
    id_admin: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    # ✅ primaryjoin explicite pour éviter l'ambiguïté cross-schema
    admin: Mapped[Optional["Utilisateur"]] = relationship(  # type: ignore
        "Utilisateur",
        foreign_keys=[id_admin],
        primaryjoin="PublicationFacebook.id_admin == Utilisateur.id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<PublicationFacebook id={self.id} statut={self.statut}>"


class FacebookConfig(Base):
    """Configuration du token Facebook — une seule ligne."""
    __tablename__  = "facebook_config"
    __table_args__ = {"schema": "voyage_hotel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    page_access_token: Mapped[Optional[str]]      = mapped_column(Text, nullable=True)
    page_id:           Mapped[Optional[str]]      = mapped_column(String(50), nullable=True)
    page_name:         Mapped[Optional[str]]      = mapped_column(String(200), nullable=True)
    token_expires_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    token_actif:       Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    updated_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<FacebookConfig page_id={self.page_id} actif={self.token_actif}>"