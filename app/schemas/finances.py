"""
app/schemas/finances.py
========================
Schémas Pydantic pour le module de gestion financière / comptabilité.
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
#  REVENUS
# ═══════════════════════════════════════════════════════════

class RevenuPeriode(BaseModel):
    periode:           str        # ex: "2024-01", "2024", "2024-01-15"
    revenu_hotel:      float
    revenu_voyage:     float
    revenu_total:      float
    commission_total:  float      # part agence (10%)
    nb_reservations:   int


class RevenusResponse(BaseModel):
    periode:           str        # "jour" | "mois" | "annee"
    revenu_total:      float
    commission_total:  float
    revenu_hotel:      float
    revenu_voyage:     float
    nb_reservations:   int
    evolution:         List[RevenuPeriode]


# ═══════════════════════════════════════════════════════════
#  COMMISSIONS PARTENAIRES
# ═══════════════════════════════════════════════════════════

class CommissionItem(BaseModel):
    id:                 int
    id_reservation:     int
    id_partenaire:      int
    partenaire_nom:     str
    partenaire_prenom:  str
    partenaire_email:   str
    type_resa:          str
    montant_total_resa: float
    taux_commission:    float
    montant_commission: float
    montant_partenaire: float
    statut:             str
    date_creation:      datetime
    date_paiement:      Optional[datetime] = None

    class Config:
        from_attributes = True


class CommissionListResponse(BaseModel):
    total:              int
    page:               int
    per_page:           int
    items:              List[CommissionItem]


class SoldePartenaire(BaseModel):
    id_partenaire:      int
    partenaire_nom:     str
    partenaire_prenom:  str
    partenaire_email:   str
    nom_entreprise:     str
    solde_du:           float       # total à payer (commissions EN_ATTENTE)
    nb_commissions:     int


class SoldesPartenairesResponse(BaseModel):
    items: List[SoldePartenaire]


class PayerPartenaireRequest(BaseModel):
    note: Optional[str] = Field(None, description="Note optionnelle pour le paiement")


class PayerPartenaireResponse(BaseModel):
    id_partenaire:  int
    montant_paye:   float
    message:        str


class PaiementHistoriqueItem(BaseModel):
    id:             int
    id_partenaire:  int
    partenaire_nom: str
    partenaire_prenom: str
    montant:        float
    note:           Optional[str] = None
    created_at:     datetime

    class Config:
        from_attributes = True


class PaiementHistoriqueResponse(BaseModel):
    total: int
    page:  int
    per_page: int
    items: List[PaiementHistoriqueItem]


# ═══════════════════════════════════════════════════════════
#  ANALYSE CLIENTS
# ═══════════════════════════════════════════════════════════

class ClientRentabilite(BaseModel):
    id_client:       int
    nom:             str
    prenom:          str
    email:           str
    telephone:       Optional[str] = None
    total_depenses:  float
    nb_reservations: int
    derniere_resa:   Optional[datetime] = None


class ClientsRentabiliteResponse(BaseModel):
    total:  int
    items:  List[ClientRentabilite]


# ═══════════════════════════════════════════════════════════
#  DASHBOARD GLOBAL
# ═══════════════════════════════════════════════════════════

class FinanceDashboard(BaseModel):
    revenu_total_mois:        float
    revenu_total_annee:       float
    commission_mois:          float
    commission_annee:         float
    total_du_partenaires:     float    # somme de tous les soldes EN_ATTENTE
    nb_partenaires_en_attente: int
    revenu_hotel_annee:       float
    revenu_voyage_annee:      float
    nb_reservations_mois:     int
    nb_reservations_annee:    int