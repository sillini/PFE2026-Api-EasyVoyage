"""
ORM models pour :
  - Hotel
  - TypeChambre
  - TypeReservation
  - Chambre
  - Tarif
  - Avis
"""
import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum,
    ForeignKey, Integer, Numeric, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ── Hotel ─────────────────────────────────────────────────────────────────────
class Hotel(Base):
    __tablename__ = "hotel"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    etoiles: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    adresse: Mapped[str] = mapped_column(String(500), nullable=False)
    pays: Mapped[str] = mapped_column(String(100), nullable=False, default="Tunisie")
    ville: Mapped[str] = mapped_column(String(100), nullable=False, default="Tunis", index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note_moyenne: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), default=0.00)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mis_en_avant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    id_partenaire: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    chambres:   Mapped[list["Chambre"]] = relationship("Chambre", back_populates="hotel")
    avis:       Mapped[list["Avis"]]    = relationship("Avis",    back_populates="hotel")
    partenaire: Mapped[Optional["Utilisateur"]] = relationship(  # type: ignore[name-defined]
        "Utilisateur", foreign_keys=[id_partenaire], lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Hotel id={self.id} nom={self.nom}>"


# ── VilleVedette ──────────────────────────────────────────────────────────────
class VilleVedette(Base):
    __tablename__ = "ville_vedette"
    __table_args__ = {"schema": "voyage_hotel"}

    id:    Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nom:   Mapped[str]      = mapped_column(String(100), nullable=False, unique=True)
    ordre: Mapped[int]      = mapped_column(Integer, nullable=False, default=0, index=True)
    actif: Mapped[bool]     = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return f"<VilleVedette id={self.id} nom={self.nom}>"


# ── TypeChambre ───────────────────────────────────────────────────────────────
class TypeChambre(Base):
    __tablename__ = "type_chambre"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nom: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    chambres: Mapped[list["Chambre"]] = relationship("Chambre", back_populates="type_chambre")

    def __repr__(self) -> str:
        return f"<TypeChambre id={self.id} nom={self.nom}>"


# ── TypeReservation ───────────────────────────────────────────────────────────
class TypeReservation(Base):
    __tablename__ = "type_reservation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nom: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return f"<TypeReservation id={self.id} nom={self.nom}>"


# ── Chambre ───────────────────────────────────────────────────────────────────
class Chambre(Base):
    __tablename__ = "chambre"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    capacite: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    id_hotel: Mapped[int] = mapped_column(BigInteger, ForeignKey("hotel.id", ondelete="CASCADE"), nullable=False)
    id_type_chambre: Mapped[int] = mapped_column(BigInteger, ForeignKey("type_chambre.id", ondelete="RESTRICT"), nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    hotel: Mapped[Hotel] = relationship("Hotel", back_populates="chambres")
    type_chambre: Mapped[TypeChambre] = relationship("TypeChambre", back_populates="chambres")
    tarifs: Mapped[list["Tarif"]] = relationship("Tarif", back_populates="chambre")

    def __repr__(self) -> str:
        return f"<Chambre id={self.id} hotel={self.id_hotel}>"


# ── Tarif ─────────────────────────────────────────────────────────────────────
class Tarif(Base):
    __tablename__ = "tarif"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prix: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)
    id_chambre: Mapped[int] = mapped_column(BigInteger, ForeignKey("chambre.id", ondelete="CASCADE"), nullable=False)
    id_type_reservation: Mapped[int] = mapped_column(BigInteger, ForeignKey("type_reservation.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    chambre: Mapped[Chambre] = relationship("Chambre", back_populates="tarifs")
    type_reservation: Mapped[TypeReservation] = relationship("TypeReservation")

    def __repr__(self) -> str:
        return f"<Tarif id={self.id} prix={self.prix}>"


# ── Avis ──────────────────────────────────────────────────────────────────────
class Avis(Base):
    __tablename__ = "avis"

    __table_args__ = (
        UniqueConstraint("id_client", "id_hotel", name="uq_avis_client_hotel"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    note: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    commentaire: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    id_client: Mapped[int] = mapped_column(BigInteger, ForeignKey("client.id", ondelete="CASCADE"), nullable=False)
    id_hotel: Mapped[int] = mapped_column(BigInteger, ForeignKey("hotel.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    hotel: Mapped[Hotel] = relationship("Hotel", back_populates="avis")

    def __repr__(self) -> str:
        return f"<Avis id={self.id} note={self.note}>"