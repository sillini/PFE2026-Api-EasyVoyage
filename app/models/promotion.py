"""
app/models/promotion.py
========================
ORM model pour la table `promotion`.

Une promotion est liée à un hôtel et s'applique sur une période donnée
avec un pourcentage de réduction.

Types supportés :
  - STANDARD      : promotion classique sur toute la période
  - EARLY_BOOKING : réservation anticipée (ex: -15% si réservé 60j à l'avance)
  - LAST_MINUTE   : réservation de dernière minute (ex: -25% si réservé < 7j avant)
"""
import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum,
    ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TypePromotion(str, enum.Enum):
    STANDARD      = "STANDARD"
    EARLY_BOOKING = "EARLY_BOOKING"
    LAST_MINUTE   = "LAST_MINUTE"


class Promotion(Base):
    __tablename__  = "promotion"
    __table_args__ = {"schema": "voyage_hotel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Identification ──────────────────────────────────────
    titre: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="Titre affiché, ex: 'Offre d'été -20%'"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Lien avec l'hôtel ───────────────────────────────────
    id_hotel: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("hotel.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Réduction ───────────────────────────────────────────
    pourcentage: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False,
        comment="Pourcentage de réduction entre 1 et 99"
    )

    # ── Type de promotion ───────────────────────────────────
    type_promotion: Mapped[TypePromotion] = mapped_column(
        Enum(TypePromotion, name="type_promotion_enum", schema="voyage_hotel"),
        nullable=False, default=TypePromotion.STANDARD,
    )

    # Pour EARLY_BOOKING : nombre de jours minimum avant l'arrivée
    jours_avant_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Pour LAST_MINUTE : nombre de jours maximum avant l'arrivée
    jours_avant_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Période de validité ─────────────────────────────────
    date_debut: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    date_fin:   Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ── Types de chambres concernés (JSON array, optionnel) ─
    # Si NULL → s'applique à toutes les chambres de l'hôtel
    # Si [1, 3] → s'applique seulement aux types de chambre d'ID 1 et 3
    types_chambre_ids: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Liste d'IDs de type_chambre au format JSON, NULL = tous les types"
    )

    # ── Statut ──────────────────────────────────────────────
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    # ── Timestamps ──────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    # ── Relations ───────────────────────────────────────────
    hotel: Mapped["Hotel"] = relationship(  # type: ignore[name-defined]
        "Hotel",
        foreign_keys=[id_hotel],
        primaryjoin="Promotion.id_hotel == Hotel.id",
        back_populates="promotions",
    )

    def __repr__(self) -> str:
        return (
            f"<Promotion id={self.id} hotel={self.id_hotel} "
            f"-{self.pourcentage}% {self.date_debut}→{self.date_fin}>"
        )