"""
ORM model pour la table voyage.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime,
    ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Voyage(Base):
    __tablename__ = "voyage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    titre: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    duree: Mapped[int] = mapped_column(Integer, nullable=False)
    prix_base: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    date_depart: Mapped[date] = mapped_column(Date, nullable=False)
    date_retour: Mapped[date] = mapped_column(Date, nullable=False)
    capacite_max: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Compteur d'inscrits ───────────────────────────────────────────────────
    # Incrémenté au paiement (CONFIRMEE), décrémenté à l'annulation (ANNULEE)
    nb_inscrits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    id_admin: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relation vers l'admin créateur
    admin: Mapped[Optional["Utilisateur"]] = relationship(  # type: ignore[name-defined]
        "Utilisateur",
        foreign_keys=[id_admin],
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Voyage id={self.id} titre={self.titre} destination={self.destination}>"