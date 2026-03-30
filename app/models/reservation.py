"""
ORM models pour :
  - Reservation
  - LigneReservationChambre  (table d'association M-N)
  - Facture
  - Paiement
  - ReservationVisiteur  ← ajout id_facture + relation facture
"""
import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum,
    ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ── Enums ─────────────────────────────────────────────────────────────────────
class StatutReservation(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    CONFIRMEE  = "CONFIRMEE"
    ANNULEE    = "ANNULEE"
    TERMINEE   = "TERMINEE"


class StatutFacture(str, enum.Enum):
    EMISE     = "EMISE"
    PAYEE     = "PAYEE"
    ANNULEE   = "ANNULEE"
    EN_RETARD = "EN_RETARD"


class StatutPaiement(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    CONFIRME   = "CONFIRME"
    ECHOUE     = "ECHOUE"
    REMBOURSE  = "REMBOURSE"


class MethodePaiement(str, enum.Enum):
    CARTE_BANCAIRE = "CARTE_BANCAIRE"
    VIREMENT       = "VIREMENT"
    ESPECES        = "ESPECES"
    PAYPAL         = "PAYPAL"
    CHEQUE         = "CHEQUE"


# ── Reservation ───────────────────────────────────────────────────────────────
class Reservation(Base):
    __tablename__ = "reservation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date_reservation: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    date_debut: Mapped[date]  = mapped_column(Date, nullable=False)
    date_fin:   Mapped[date]  = mapped_column(Date, nullable=False)
    statut: Mapped[StatutReservation] = mapped_column(
        Enum(StatutReservation, name="statut_reservation", schema="voyage_hotel"),
        nullable=False, default=StatutReservation.EN_ATTENTE,
    )
    total_ttc: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.00)
    id_client: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("client.id", ondelete="RESTRICT"), nullable=False
    )
    id_voyage: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("voyage.id", ondelete="RESTRICT"), nullable=True
    )

    # ── Nombre de voyageurs (utilisé uniquement pour les réservations voyage) ─
    # Pour les réservations hôtel, ces champs sont dans LigneReservationChambre
    nb_adultes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nb_enfants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    lignes_chambres: Mapped[list["LigneReservationChambre"]] = relationship(
        "LigneReservationChambre", back_populates="reservation"
    )
    facture: Mapped[Optional["Facture"]] = relationship(
        "Facture", back_populates="reservation", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Reservation id={self.id} statut={self.statut}>"


# ── LigneReservationChambre ───────────────────────────────────────────────────
class LigneReservationChambre(Base):
    __tablename__ = "ligne_reservation_chambre"

    id_reservation: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reservation.id", ondelete="CASCADE"), primary_key=True
    )
    id_chambre: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chambre.id", ondelete="RESTRICT"), primary_key=True
    )
    prix_unitaire: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    quantite:      Mapped[int]   = mapped_column(Integer, nullable=False, default=1)
    nb_adultes:    Mapped[int]   = mapped_column(Integer, nullable=False, default=1)
    nb_enfants:    Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    reservation: Mapped[Reservation] = relationship(
        "Reservation", back_populates="lignes_chambres"
    )

    def __repr__(self) -> str:
        return f"<LigneReservationChambre res={self.id_reservation} chambre={self.id_chambre}>"


# ── Facture ───────────────────────────────────────────────────────────────────
class Facture(Base):
    __tablename__ = "facture"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    numero: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    date_emission: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    montant_total: Mapped[float]  = mapped_column(Numeric(12, 2), nullable=False)
    statut: Mapped[StatutFacture] = mapped_column(
        Enum(StatutFacture, name="statut_facture", schema="voyage_hotel"),
        nullable=False, default=StatutFacture.EMISE,
    )
    fichier_pdf: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # nullable=True pour supporter aussi les factures visiteurs
    id_reservation: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("reservation.id", ondelete="RESTRICT"),
        nullable=True, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    reservation: Mapped[Optional[Reservation]] = relationship(
        "Reservation", back_populates="facture"
    )
    paiements: Mapped[list["Paiement"]] = relationship(
        "Paiement", back_populates="facture"
    )
    # Relation inverse vers ReservationVisiteur
    reservation_visiteur: Mapped[Optional["ReservationVisiteur"]] = relationship(
        "ReservationVisiteur", back_populates="facture", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Facture id={self.id} numero={self.numero}>"


# ── Paiement ──────────────────────────────────────────────────────────────────
class Paiement(Base):
    __tablename__ = "paiement"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date_paiement: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    montant: Mapped[float]           = mapped_column(Numeric(12, 2), nullable=False)
    methode: Mapped[MethodePaiement] = mapped_column(
        Enum(MethodePaiement, name="methode_paiement", schema="voyage_hotel"),
        nullable=False,
    )
    statut: Mapped[StatutPaiement] = mapped_column(
        Enum(StatutPaiement, name="statut_paiement", schema="voyage_hotel"),
        nullable=False, default=StatutPaiement.EN_ATTENTE,
    )
    transaction_id: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, unique=True
    )
    id_facture: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("facture.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    facture: Mapped[Facture] = relationship("Facture", back_populates="paiements")

    def __repr__(self) -> str:
        return f"<Paiement id={self.id} montant={self.montant} statut={self.statut}>"


# ── ReservationVisiteur ───────────────────────────────────────────────────────
class ReservationVisiteur(Base):
    __tablename__ = "reservation_visiteur"

    id:               Mapped[int]           = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nom:              Mapped[str]            = mapped_column(String(100), nullable=False)
    prenom:           Mapped[str]            = mapped_column(String(100), nullable=False)
    email:            Mapped[str]            = mapped_column(String(255), nullable=False)
    telephone:        Mapped[str]            = mapped_column(String(30),  nullable=False)
    id_chambre:       Mapped[int]            = mapped_column(BigInteger, ForeignKey("chambre.id", ondelete="RESTRICT"), nullable=False)
    date_debut:       Mapped[date]           = mapped_column(Date, nullable=False)
    date_fin:         Mapped[date]           = mapped_column(Date, nullable=False)
    nb_adultes:       Mapped[int]            = mapped_column(Integer, nullable=False, default=1)
    nb_enfants:       Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    total_ttc:        Mapped[float]          = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    methode_paiement: Mapped[str]            = mapped_column(String(30), nullable=False, default="CARTE_BANCAIRE")
    transaction_id:   Mapped[Optional[str]]  = mapped_column(String(200), nullable=True, unique=True)
    statut:           Mapped[str]            = mapped_column(String(30), nullable=False, default="CONFIRMEE")
    numero_voucher:   Mapped[str]            = mapped_column(String(50), nullable=False, unique=True)

    # Lien vers la facture
    id_facture: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("facture.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    facture: Mapped[Optional[Facture]] = relationship(
        "Facture",
        back_populates="reservation_visiteur",
        foreign_keys=[id_facture],
    )

    def __repr__(self) -> str:
        return f"<ReservationVisiteur id={self.id} email={self.email}>"