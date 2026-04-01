"""
app/schemas/finances.py
========================
Schémas Pydantic pour le module de gestion financière / comptabilité.
"""
from __future__ import annotations
from datetime import datetime, date
from typing import List, Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
#  REVENUS
# ═══════════════════════════════════════════════════════════

class RevenuPeriode(BaseModel):
    periode:          str
    revenu_hotel:     float
    revenu_voyage:    float
    revenu_total:     float
    commission_total: float
    nb_reservations:  int


class RevenusResponse(BaseModel):
    periode:          str
    revenu_total:     float
    commission_total: float
    revenu_hotel:     float
    revenu_voyage:    float
    nb_reservations:  int
    evolution:        List[RevenuPeriode]


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
    total:    int
    page:     int
    per_page: int
    items:    List[CommissionItem]


class SoldePartenaire(BaseModel):
    id_partenaire:             int
    partenaire_nom:            str
    partenaire_prenom:         str
    partenaire_email:          str
    nom_entreprise:            str
    solde_du:                  float
    revenu_hotel:              float = 0.0
    commission_agence:         float = 0.0
    montant_paye:              float = 0.0
    nb_commissions:            int
    nb_reservations_visiteurs: int   = 0
    nb_reservations_total:     int   = 0


class SoldesPartenairesResponse(BaseModel):
    items: List[SoldePartenaire]


class PayerPartenaireRequest(BaseModel):
    note: Optional[str] = Field(None, description="Note optionnelle pour le paiement")


class PayerPartenaireResponse(BaseModel):
    success:       bool
    id_partenaire: int
    montant_paye:  float
    message:       str
    nb_commissions: int = 0

class PaiementHistoriqueItem(BaseModel):
    id:                int          # ✅ nécessaire pour les actions PDF/email
    id_partenaire:     int
    partenaire_nom:    str
    partenaire_prenom: str
    partenaire_email:  str
    partenaire_tel:    Optional[str] = None
    nom_entreprise:    str = "—"
    montant:           float
    note:              Optional[str] = None
    numero_facture:    Optional[str] = None   # ✅ NOUVEAU
    has_pdf:           bool          = False  # ✅ NOUVEAU
    created_at:        datetime

    class Config:
        from_attributes = True
        
class PaiementHistoriqueResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[PaiementHistoriqueItem]


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
    total: int
    items: List[ClientRentabilite]


# ═══════════════════════════════════════════════════════════
#  DASHBOARD GLOBAL
# ═══════════════════════════════════════════════════════════

class FinanceDashboard(BaseModel):
    revenu_total_mois:         float
    revenu_total_annee:        float
    commission_mois:           float
    commission_annee:          float
    total_du_partenaires:      float
    nb_partenaires_en_attente: int
    revenu_hotel_annee:        float
    revenu_voyage_annee:       float
    nb_reservations_mois:      int
    nb_reservations_annee:     int
    total_part_partenaires:    float = 0.0
    total_commissions_agence:  float = 0.0


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN : PARTENAIRES
# ═══════════════════════════════════════════════════════════

class PartenaireFinanceDetail(BaseModel):
    id_partenaire:     int
    partenaire_nom:    str
    partenaire_prenom: str
    partenaire_email:  str
    nom_entreprise:    str
    commission_taux:   float
    revenu_total:      float
    commission_agence: float
    part_partenaire:   float
    montant_paye:      float
    solde_restant:     float
    nb_reservations:   int

    class Config:
        from_attributes = True


class PartenaireFinanceListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[PartenaireFinanceDetail]


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN : HÔTELS
# ═══════════════════════════════════════════════════════════

class HotelFinanceDetail(BaseModel):
    id_hotel:          int
    hotel_nom:         str
    hotel_ville:       str
    revenu_total:      float
    commission_agence: float
    part_partenaire:   float
    montant_paye:      float
    solde_restant:     float
    nb_reservations:   int

    class Config:
        from_attributes = True


class HotelFinanceListResponse(BaseModel):
    items: List[HotelFinanceDetail]


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN : RÉSERVATIONS
# ═══════════════════════════════════════════════════════════

class ReservationFinanceItem(BaseModel):
    type_source:       str
    client_nom:        str
    client_email:      Optional[str]  = None
    date_debut:        Optional[date] = None
    date_fin:          Optional[date] = None
    montant_total:     float
    commission_agence: float
    part_partenaire:   float
    taux_commission:   float
    statut_commission: str
    date_paiement:     Optional[datetime] = None

    class Config:
        from_attributes = True


class ReservationFinanceListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[ReservationFinanceItem]


# ═══════════════════════════════════════════════════════════
#  CLIENTS + VISITEURS — CLASSEMENT
# ═══════════════════════════════════════════════════════════

class ClientVisiteurItem(BaseModel):
    type_source:          str
    id:                   Optional[int] = None
    nom:                  str
    email:                str
    total_depenses:       float
    commissions_generees: float
    nb_reservations:      int
    nb_hotel:             int
    nb_voyage:            int


class ClientsVisiteursRentabiliteResponse(BaseModel):
    total:   int
    critere: str
    items:   List[ClientVisiteurItem]


# ═══════════════════════════════════════════════════════════
#  DEMANDES DE RETRAIT — VUE ADMIN
# ═══════════════════════════════════════════════════════════

class DemandeRetraitItem(BaseModel):
    id:                int
    id_partenaire:     int
    partenaire_nom:    str
    partenaire_prenom: str
    partenaire_email:  str
    nom_entreprise:    str = "—"
    montant:           float
    note:              Optional[str] = None
    statut:            str           # EN_ATTENTE | APPROUVEE | REFUSEE
    note_admin:        Optional[str] = None
    created_at:        datetime
    updated_at:        Optional[datetime] = None

    class Config:
        from_attributes = True


class DemandesRetraitResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[DemandeRetraitItem]


class ValiderDemandeRequest(BaseModel):
    note_admin: Optional[str] = None


class RefuserDemandeRequest(BaseModel):
    note_admin: Optional[str] = Field(None, description="Motif du refus")


class DemandeActionResponse(BaseModel):
    success: bool
    message: str