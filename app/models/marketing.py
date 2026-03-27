"""
ORM models pour :
  - Marketing   (campagnes)
  - MarketingAdmin  (table d'association M-N)
"""
import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Date, DateTime, Enum,
    ForeignKey, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StatutMarketing(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    ACCEPTEE   = "ACCEPTEE"
    REFUSEE    = "REFUSEE"
    ACTIVE     = "ACTIVE"
    EXPIREE    = "EXPIREE"


class Marketing(Base):
    __tablename__ = "marketing"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    budget: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    segment_cible: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    contenu: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    statut: Mapped[StatutMarketing] = mapped_column(
        Enum(StatutMarketing, name="statut_marketing", schema="voyage_hotel"),
        nullable=False, default=StatutMarketing.EN_ATTENTE,
    )
    date_demande: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    date_debut: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_fin: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    id_partenaire: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("partenaire.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    actions_admin: Mapped[list["MarketingAdmin"]] = relationship(
        "MarketingAdmin", back_populates="marketing"
    )

    def __repr__(self) -> str:
        return f"<Marketing id={self.id} nom={self.nom} statut={self.statut}>"


class MarketingAdmin(Base):
    __tablename__ = "marketing_admin"

    id_marketing: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("marketing.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id_admin: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin.id", ondelete="CASCADE"),
        primary_key=True,
    )
    date_action: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    commentaire: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    marketing: Mapped[Marketing] = relationship(
        "Marketing", back_populates="actions_admin"
    )

    def __repr__(self) -> str:
        return f"<MarketingAdmin marketing={self.id_marketing} admin={self.id_admin}>"