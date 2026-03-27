"""
ORM models for the user hierarchy:
  Utilisateur  (super-class)
  ├── Client
  ├── Partenaire
  └── Admin
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RoleUtilisateur(str, enum.Enum):
    CLIENT = "CLIENT"
    PARTENAIRE = "PARTENAIRE"
    ADMIN = "ADMIN"


class Utilisateur(Base):
    __tablename__ = "utilisateur"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nom: Mapped[str] = mapped_column(String(100), nullable=False)
    prenom: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    mot_de_passe: Mapped[str] = mapped_column(String(255), nullable=False)
    telephone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    role: Mapped[RoleUtilisateur] = mapped_column(
        Enum(RoleUtilisateur, name="role_utilisateur", schema="voyage_hotel"),
        nullable=False,
    )
    date_inscription: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    derniere_connexion: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    client: Mapped[Optional["Client"]] = relationship(
        "Client", back_populates="utilisateur", uselist=False
    )
    partenaire: Mapped[Optional["Partenaire"]] = relationship(
        "Partenaire", back_populates="utilisateur", uselist=False
    )
    admin: Mapped[Optional["Admin"]] = relationship(
        "Admin", back_populates="utilisateur", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Utilisateur id={self.id} email={self.email} role={self.role}>"


class Client(Base):
    __tablename__ = "client"

    id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    utilisateur: Mapped[Utilisateur] = relationship("Utilisateur", back_populates="client")

    def __repr__(self) -> str:
        return f"<Client id={self.id}>"


class Partenaire(Base):
    __tablename__ = "partenaire"

    id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    nom_entreprise: Mapped[str] = mapped_column(String(200), nullable=False)
    type_partenaire: Mapped[str] = mapped_column(String(100), nullable=False)
    commission: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.00)
    statut: Mapped[str] = mapped_column(String(50), nullable=False, default="EN_ATTENTE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    utilisateur: Mapped[Utilisateur] = relationship("Utilisateur", back_populates="partenaire")

    def __repr__(self) -> str:
        return f"<Partenaire id={self.id} entreprise={self.nom_entreprise}>"


class Admin(Base):
    __tablename__ = "admin"

    id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    utilisateur: Mapped[Utilisateur] = relationship("Utilisateur", back_populates="admin")

    def __repr__(self) -> str:
        return f"<Admin id={self.id}>"