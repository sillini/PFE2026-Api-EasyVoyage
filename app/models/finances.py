"""
app/models/finances.py
======================
Modèles SQLAlchemy pour le module de gestion financière.

Tables :
  - commission_partenaire  : commission par réservation (10% agence, 90% partenaire)
  - paiement_partenaire    : historique des paiements effectués aux partenaires

⚠️  Pas de back_populates vers Reservation pour éviter de modifier
    le modèle existant. La relation est unidirectionnelle (finances → reservation).
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, Numeric, String, Text,
    ForeignKey, DateTime, Enum as SAEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class StatutCommission(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    PAYEE      = "PAYEE"


class CommissionPartenaire(Base):
    """
    Une ligne de commission par réservation confirmée.
    Créée automatiquement par le trigger PostgreSQL trg_commission_auto.
    """
    __tablename__ = "commission_partenaire"

    id                  = Column(Integer, primary_key=True, index=True)
    id_reservation      = Column(
        Integer,
        ForeignKey("reservation.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    id_partenaire       = Column(
        Integer,
        ForeignKey("utilisateur.id", ondelete="CASCADE"),
        nullable=False,
    )
    type_resa           = Column(String(20), nullable=False, default="hotel")
    montant_total_resa  = Column(Numeric(12, 2), nullable=False)
    taux_commission     = Column(Numeric(5, 2),  nullable=False, default=10.00)
    montant_commission  = Column(Numeric(12, 2), nullable=False)
    montant_partenaire  = Column(Numeric(12, 2), nullable=False)
    statut              = Column(
        SAEnum(StatutCommission, name="statut_commission", create_type=False),
        nullable=False,
        default=StatutCommission.EN_ATTENTE,
    )
    date_creation       = Column(DateTime(timezone=True), server_default=func.now())
    date_paiement       = Column(DateTime(timezone=True), nullable=True)

    # ── Relations ─────────────────────────────────────────
    # Pas de back_populates="commission" sur Reservation → relation simple
    reservation = relationship(
        "Reservation",
        foreign_keys=[id_reservation],
        lazy="selectin",
    )
    partenaire = relationship(
        "Utilisateur",
        foreign_keys=[id_partenaire],
        lazy="selectin",
    )


class PaiementPartenaire(Base):
    """
    Historique des paiements effectués aux partenaires.
    Chaque paiement remet le solde dû au partenaire à zéro.
    """
    __tablename__ = "paiement_partenaire"

    id            = Column(Integer, primary_key=True, index=True)
    id_partenaire = Column(
        Integer,
        ForeignKey("utilisateur.id", ondelete="CASCADE"),
        nullable=False,
    )
    montant       = Column(Numeric(12, 2), nullable=False)
    note          = Column(Text, nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    partenaire = relationship(
        "Utilisateur",
        foreign_keys=[id_partenaire],
        lazy="selectin",
    )