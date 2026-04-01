"""
app/models/finances.py
======================
Modèles SQLAlchemy pour le module de gestion financière.

Tables :
  - commission_partenaire  : commission par réservation (10% agence, 90% partenaire)
  - paiement_partenaire    : historique des paiements validés aux partenaires
  - withdraw_requests      : demandes de retrait soumises par les partenaires
                             (EN_ATTENTE → APPROUVEE ou REFUSEE par l'admin)
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
from sqlalchemy import (
    Column, Integer, Numeric, String, Text, LargeBinary,
    ForeignKey, DateTime, Enum as SAEnum,
)

# ═══════════════════════════════════════════════════════════
#  ENUMS
# ═══════════════════════════════════════════════════════════

class StatutCommission(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    PAYEE      = "PAYEE"


class StatutDemande(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    APPROUVEE  = "APPROUVEE"
    REFUSEE    = "REFUSEE"


# ═══════════════════════════════════════════════════════════
#  COMMISSION PARTENAIRE
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
#  PAIEMENT PARTENAIRE
# ═══════════════════════════════════════════════════════════

class PaiementPartenaire(Base):
    __tablename__ = "paiement_partenaire"

    id            = Column(Integer, primary_key=True, index=True)
    id_partenaire = Column(
        Integer,
        ForeignKey("utilisateur.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    montant        = Column(Numeric(12, 2), nullable=False)
    note           = Column(Text, nullable=True)
    # ✅ NOUVEAU
    numero_facture = Column(String(30), nullable=True, unique=True, index=True)
    pdf_data       = Column(LargeBinary, nullable=True)   # PDF en bytes
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    partenaire = relationship(
        "Utilisateur",
        foreign_keys=[id_partenaire],
        lazy="selectin",
    )

# ═══════════════════════════════════════════════════════════
#  WITHDRAW REQUEST (demande de retrait)
# ═══════════════════════════════════════════════════════════

class WithdrawRequest(Base):
    """
    Demande de retrait soumise par un partenaire.

    Cycle de vie :
      EN_ATTENTE → (admin valide)  → APPROUVEE + INSERT paiement_partenaire
      EN_ATTENTE → (admin refuse)  → REFUSEE   (rien dans paiement_partenaire)

    Le solde disponible du partenaire tient compte des montants EN_ATTENTE
    pour éviter qu'il soumette plusieurs demandes dépassant son solde réel.
    """
    __tablename__ = "withdraw_requests"

    id            = Column(Integer, primary_key=True, index=True)
    id_partenaire = Column(
        Integer,
        ForeignKey("utilisateur.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    montant    = Column(Numeric(12, 2), nullable=False)
    note       = Column(Text, nullable=True)
    statut     = Column(
        SAEnum(StatutDemande, name="statut_demande", create_type=False),
        nullable=False,
        default=StatutDemande.EN_ATTENTE,
    )
    note_admin = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    partenaire = relationship(
        "Utilisateur",
        foreign_keys=[id_partenaire],
        lazy="selectin",
    )
