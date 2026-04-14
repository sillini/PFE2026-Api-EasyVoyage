"""
app/models/promotion.py
========================
ORM model pour la table `promotion`.

Workflow de validation :
  PENDING  → créée par le partenaire, en attente de validation admin
  APPROVED → validée par l'admin, visible côté visiteur
  REJECTED → refusée par l'admin, avec raison optionnelle

Le champ `actif` reste présent pour permettre à l'admin de désactiver
temporairement une promo approuvée sans la supprimer.
"""
import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum,
    ForeignKey, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StatutPromotion(str, enum.Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


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
    # ForeignKey sans schéma — cohérent avec hotel.py, chambre.py, favori.py…
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

    # ── Période de validité ─────────────────────────────────
    date_debut: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    date_fin:   Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ── Statut workflow (PENDING → APPROVED | REJECTED) ─────
    statut: Mapped[StatutPromotion] = mapped_column(
        Enum(StatutPromotion, name="statut_promotion_enum", schema="voyage_hotel"),
        nullable=False,
        default=StatutPromotion.PENDING,
        index=True,
    )

    # ── Activation manuelle (override admin) ────────────────
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Créateur (partenaire) ───────────────────────────────
    id_partenaire: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Validateur (admin) ──────────────────────────────────
    id_admin_validateur: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Raison de refus (optionnel) ─────────────────────────
    raison_refus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Date de décision admin ──────────────────────────────
    date_decision: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Timestamps ──────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )

    # ── Relations ───────────────────────────────────────────
    hotel: Mapped["Hotel"] = relationship(          # type: ignore[name-defined]
        "Hotel",
        foreign_keys=[id_hotel],
        primaryjoin="Promotion.id_hotel == Hotel.id",
        back_populates="promotions",
        lazy="select",
    )
    partenaire: Mapped[Optional["Utilisateur"]] = relationship(   # type: ignore[name-defined]
        "Utilisateur",
        foreign_keys=[id_partenaire],
        primaryjoin="Promotion.id_partenaire == Utilisateur.id",
        lazy="select",
    )
    validateur: Mapped[Optional["Utilisateur"]] = relationship(   # type: ignore[name-defined]
        "Utilisateur",
        foreign_keys=[id_admin_validateur],
        primaryjoin="Promotion.id_admin_validateur == Utilisateur.id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Promotion id={self.id} titre={self.titre!r} "
            f"statut={self.statut} hotel={self.id_hotel}>"
        )