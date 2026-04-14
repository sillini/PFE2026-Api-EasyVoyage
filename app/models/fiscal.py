"""
app/models/fiscal.py
=====================
ORM model pour la table fiscal_rules.
Stocke tous les paramètres fiscaux configurables par l'administrateur.

Règles métier :
  - taxe_sejour_2_3  : 2 DT/nuit pour hôtels 2-3 étoiles (max 7 nuits)
  - taxe_sejour_4_5  : 3 DT/nuit pour hôtels 4-5 étoiles (max 7 nuits)
  - tva              : 7% sur montant HT
  - droit_timbre     : 1 DT fixe par facture

Toutes ces valeurs sont modifiables via l'interface admin sans toucher au code.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Integer,
    Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FiscalRule(Base):
    __tablename__ = "fiscal_rules"
    __table_args__ = {"schema": "voyage_hotel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Identifiant métier unique (ex: "taxe_sejour_2_3", "tva", "droit_timbre")
    cle: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)

    # Libellé affiché sur la facture PDF
    libelle: Mapped[str] = mapped_column(String(200), nullable=False)

    # Valeur numérique (montant ou pourcentage selon type_valeur)
    valeur: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)

    # "PAR_NUIT" | "POURCENTAGE" | "MONTANT_FIXE"
    type_valeur: Mapped[str] = mapped_column(String(50), nullable=False, default="MONTANT_FIXE")

    # Description affichée dans l'interface admin
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Activer / désactiver la règle sans la supprimer
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Paramètres contextuels pour les taxes de séjour
    nb_nuits_max: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Nombre de nuits maximum taxables (ex: 7 pour la taxe de séjour)"
    )
    etoiles_min: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Classement minimum de l'hôtel pour appliquer cette règle"
    )
    etoiles_max: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Classement maximum de l'hôtel pour appliquer cette règle"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<FiscalRule cle={self.cle} valeur={self.valeur} type={self.type_valeur}>"