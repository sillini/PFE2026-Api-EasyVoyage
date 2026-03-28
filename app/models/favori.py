"""
ORM model pour la table favori.

Un client peut mettre en favori :
  - un hôtel   (id_hotel  non NULL, id_voyage NULL)
  - un voyage  (id_voyage non NULL, id_hotel  NULL)

Contraintes UNIQUE : (id_client, id_hotel) et (id_client, id_voyage)
Index PostgreSQL : idx_favori_client, idx_favori_hotel, idx_favori_voyage
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Favori(Base):
    __tablename__ = "favori"
    __table_args__ = (
        UniqueConstraint("id_client", "id_hotel",  name="uq_favori_client_hotel"),
        UniqueConstraint("id_client", "id_voyage", name="uq_favori_client_voyage"),
        {"schema": "voyage_hotel"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    # ── FK sans schéma explicite — SQLAlchemy résout via la table enregistrée ──
    id_client: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    id_hotel: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("hotel.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )
    id_voyage: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("voyage.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # ── Relations avec primaryjoin explicite pour éviter toute ambiguïté ──
    client: Mapped["Utilisateur"] = relationship(   # type: ignore[name-defined]
        "Utilisateur",
        foreign_keys=[id_client],
        primaryjoin="Favori.id_client == Utilisateur.id",
    )
    hotel: Mapped[Optional["Hotel"]] = relationship(  # type: ignore[name-defined]
        "Hotel",
        foreign_keys=[id_hotel],
        primaryjoin="Favori.id_hotel == Hotel.id",
    )
    voyage: Mapped[Optional["Voyage"]] = relationship(  # type: ignore[name-defined]
        "Voyage",
        foreign_keys=[id_voyage],
        primaryjoin="Favori.id_voyage == Voyage.id",
    )

    def __repr__(self) -> str:
        t = f"hotel={self.id_hotel}" if self.id_hotel else f"voyage={self.id_voyage}"
        return f"<Favori id={self.id} client={self.id_client} {t}>"