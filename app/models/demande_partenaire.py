"""
ORM model pour la table demande_partenaire.
Un visiteur soumet une demande depuis la landing page.
L'admin peut CONFIRMER ou ANNULER la demande.
Si confirmée → création automatique du compte partenaire.
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, Enum, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StatutDemande(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    CONFIRMEE  = "CONFIRMEE"
    ANNULEE    = "ANNULEE"


class DemandePartenaire(Base):
    __tablename__ = "demande_partenaire"
    __table_args__ = {"schema": "voyage_hotel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Informations du demandeur
    nom: Mapped[str] = mapped_column(String(100), nullable=False)
    prenom: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    telephone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Informations de l'entreprise
    nom_entreprise: Mapped[str] = mapped_column(String(200), nullable=False)
    type_partenaire: Mapped[str] = mapped_column(String(100), nullable=False, default="HOTEL")
    site_web: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    adresse: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Statut & traitement
    statut: Mapped[StatutDemande] = mapped_column(
        Enum(StatutDemande, name="statut_demande_partenaire", schema="voyage_hotel"),
        nullable=False,
        default=StatutDemande.EN_ATTENTE,
        index=True,
    )
    note_admin: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    traite_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<DemandePartenaire id={self.id} email={self.email} statut={self.statut}>"