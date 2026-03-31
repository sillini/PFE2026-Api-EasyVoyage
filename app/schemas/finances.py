"""
app/schemas/finances.py
========================
Schémas Pydantic pour le module de gestion financière / comptabilité.
Version avancée avec drill-down partenaire → hôtel → réservation.
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
    id_partenaire:     int
    partenaire_nom:    str
    partenaire_prenom: str
    partenaire_email:  str
    nom_entreprise:    str
    solde_du:          float
    # ── Champs enrichis ──────────────────────────────────
    revenu_hotel:      float = 0.0   # revenu hôtel total (clients + visiteurs)
    commission_agence: float = 0.0   # 10% du revenu hôtel
    montant_paye:      float = 0.0   # déjà versé
    nb_commissions:    int            # clients EN_ATTENTE dans commission_partenaire
    nb_reservations_visiteurs: int = 0  # visiteurs confirmés/terminés
    nb_reservations_total:     int = 0  # total = clients + visiteurs
 
 
class SoldesPartenairesResponse(BaseModel):
    items: List[SoldePartenaire]


class PayerPartenaireRequest(BaseModel):
    note: Optional[str] = Field(None, description="Note optionnelle pour le paiement")


class PayerPartenaireResponse(BaseModel):
    id_partenaire: int
    montant_paye:  float
    message:       str


class PaiementHistoriqueItem(BaseModel):
    # id supprimé — non affiché côté interface
    id_partenaire:     int
    partenaire_nom:    str
    partenaire_prenom: str
    partenaire_email:  str                   # ← NOUVEAU
    partenaire_tel:    Optional[str] = None  # ← NOUVEAU
    nom_entreprise:    str = "—"             # ← NOUVEAU
    montant:           float
    note:              Optional[str] = None
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
    # ── Nouveaux champs ──────────────────────────────────
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
    """
    Réservation dans le drill-down hôtel — clients ET visiteurs.
    client_email ajouté pour l'affichage et la recherche frontend.
    """
    type_source:       str
    client_nom:        str
    client_email:      Optional[str]  = None   # ← NOUVEAU
    date_debut:        Optional[date]     = None
    date_fin:          Optional[date]     = None
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
#  CLIENTS + VISITEURS — CLASSEMENT MULTI-CRITÈRES
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