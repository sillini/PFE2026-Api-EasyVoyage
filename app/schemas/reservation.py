"""
Pydantic schemas pour Réservations, Paiements et Factures.

Structure de la base :
  - reservation.id_voyage  → réservation de voyage (id_voyage non NULL, pas de lignes chambres)
  - ligne_reservation_chambre → réservation de chambres (id_voyage NULL dans reservation)
  PK de ligne_reservation_chambre = (id_reservation, id_chambre) — une chambre une seule fois par réservation
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# ═══════════════════════════════════════════════════════════
#  LIGNE CHAMBRE
#  PK = (id_reservation, id_chambre) → une chambre par réservation
# ═══════════════════════════════════════════════════════════
class LigneChambreCreate(BaseModel):
    id_chambre: int = Field(
        ...,
        examples=[1],
        description="ID de la chambre — une chambre ne peut apparaître qu'une seule fois par réservation",
    )
    nb_adultes: int = Field(
        default=1, ge=1, examples=[2],
        description="Nombre d'adultes (minimum 1)",
    )
    nb_enfants: int = Field(
        default=0, ge=0, examples=[1],
        description="Nombre d'enfants",
    )


class LigneChambreResponse(BaseModel):
    id_chambre: int
    prix_unitaire: float
    quantite: int
    nb_adultes: int
    nb_enfants: int
    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  RESERVATION CREATE — VOYAGE
#  nb_adultes + nb_enfants obligatoires pour :
#    - calculer total_ttc = prix_base × (nb_adultes + nb_enfants)
#    - incrémenter/décrémenter nb_inscrits du voyage
# ═══════════════════════════════════════════════════════════
class ReservationVoyageCreate(BaseModel):
    """Réservation d'un voyage — id_voyage obligatoire."""
    date_debut: date = Field(..., examples=["2026-06-01"])
    date_fin:   date = Field(..., examples=["2026-06-08"])
    id_voyage:  int  = Field(..., examples=[1], description="ID du voyage à réserver")
    nb_adultes: int  = Field(default=1, ge=1, examples=[2], description="Nombre d'adultes (min 1)")
    nb_enfants: int  = Field(default=0, ge=0, examples=[0], description="Nombre d'enfants")

    @model_validator(mode="after")
    def dates_valides(self) -> "ReservationVoyageCreate":
        if self.date_fin <= self.date_debut:
            raise ValueError("date_fin doit être après date_debut")
        return self

    @property
    def nb_personnes(self) -> int:
        return self.nb_adultes + self.nb_enfants


# ═══════════════════════════════════════════════════════════
#  RESERVATION CREATE — CHAMBRES
# ═══════════════════════════════════════════════════════════
class ReservationChambresCreate(BaseModel):
    """Réservation de chambres d'hôtel — liste de chambres obligatoire."""
    date_debut: date = Field(..., examples=["2026-06-01"])
    date_fin:   date = Field(..., examples=["2026-06-08"])
    chambres: List[LigneChambreCreate] = Field(
        ...,
        min_length=1,
        examples=[[{"id_chambre": 1, "nb_adultes": 2, "nb_enfants": 0}]],
        description="Liste de chambres — chaque chambre unique (PK composée dans la DB)",
    )

    @model_validator(mode="after")
    def valider(self) -> "ReservationChambresCreate":
        if self.date_fin <= self.date_debut:
            raise ValueError("date_fin doit être après date_debut")
        ids = [c.id_chambre for c in self.chambres]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "Une même chambre ne peut pas apparaître deux fois dans la même réservation"
            )
        return self


# ═══════════════════════════════════════════════════════════
#  RESERVATION RESPONSE
# ═══════════════════════════════════════════════════════════
class ReservationResponse(BaseModel):
    id: int
    date_reservation: datetime
    date_debut: date
    date_fin: date
    statut: str
    total_ttc: float
    id_client: int
    id_voyage: Optional[int] = None
    nb_adultes: int = 0   # ← nb voyageurs adultes (voyage uniquement)
    nb_enfants: int = 0   # ← nb voyageurs enfants (voyage uniquement)
    lignes_chambres: List[LigneChambreResponse] = []
    numero_facture: Optional[str] = None
    statut_facture: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ReservationListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[ReservationResponse]


# ═══════════════════════════════════════════════════════════
#  PAIEMENT
# ═══════════════════════════════════════════════════════════
class PaiementRequest(BaseModel):
    methode: str = Field(
        default="CARTE_BANCAIRE",
        examples=["CARTE_BANCAIRE"],
        description="Méthode : CARTE_BANCAIRE | VIREMENT | ESPECES | PAYPAL | CHEQUE",
    )
    transaction_id: Optional[str] = Field(
        None,
        examples=["TXN-20260601-ABC123"],
        description="Référence de transaction du prestataire de paiement",
    )


class PaiementResponse(BaseModel):
    id: int
    date_paiement: datetime
    montant: float
    methode: str
    statut: str
    transaction_id: Optional[str]
    id_facture: int
    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  FACTURE
# ═══════════════════════════════════════════════════════════
class FactureResponse(BaseModel):
    id: int
    numero: str
    date_emission: datetime
    montant_total: float
    statut: str
    fichier_pdf: Optional[str]
    id_reservation: Optional[int] = None   # nullable (factures visiteurs)
    paiements: List[PaiementResponse] = []
    model_config = {"from_attributes": True}