"""
app/schemas/finances_partenaire.py
===================================
Schémas Pydantic exclusifs à l'espace partenaire (finance).
"""
from __future__ import annotations
from datetime import datetime, date
from typing import List, Optional
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════
#  DASHBOARD PARTENAIRE
# ═══════════════════════════════════════════════════════════

class PartDashboard(BaseModel):
    solde_disponible:      float
    revenu_mois:           float
    revenu_mois_precedent: float
    evolution_pct:         float
    nb_reservations_mois:  int
    revenu_annee:          float


# ═══════════════════════════════════════════════════════════
#  REVENUS MENSUELS (graphique)
# ═══════════════════════════════════════════════════════════

class PartRevenuMois(BaseModel):
    mois:     str
    annee:    int
    revenu:   float
    nb_resas: int


class PartRevenusResponse(BaseModel):
    annee:      int
    mois_liste: List[PartRevenuMois]


# ═══════════════════════════════════════════════════════════
#  MES HÔTELS
# ═══════════════════════════════════════════════════════════

class PartHotelItem(BaseModel):
    id_hotel:       int
    hotel_nom:      str
    hotel_ville:    str
    hotel_actif:    bool
    revenu_mois:    float
    revenu_total:   float
    nb_resas_mois:  int
    nb_resas_total: int
    solde_restant:  float

    class Config:
        from_attributes = True


class PartHotelListResponse(BaseModel):
    items: List[PartHotelItem]


# ═══════════════════════════════════════════════════════════
#  RÉSERVATIONS D'UN HÔTEL (drill-down)
# ═══════════════════════════════════════════════════════════

class PartReservationItem(BaseModel):
    id:               int
    source:           str
    reference:        str
    client_nom:       str
    client_email:     str
    date_debut:       date
    date_fin:         date
    nb_nuits:         int
    montant_total:    float
    part_partenaire:  float
    statut:           str
    statut_paiement:  str
    date_reservation: datetime

    class Config:
        from_attributes = True


class PartReservationListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[PartReservationItem]


# ═══════════════════════════════════════════════════════════
#  PAIEMENTS REÇUS (historique)
# ═══════════════════════════════════════════════════════════

class PartPaiementItem(BaseModel):
    id:             int
    montant:        float
    note:           Optional[str] = None
    numero_facture: Optional[str] = None   # ✅ NOUVEAU
    has_pdf:        bool          = False  # ✅ NOUVEAU — indique si PDF dispo
    created_at:     datetime

    class Config:
        from_attributes = True
class PartPaiementsResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[PartPaiementItem]


# ═══════════════════════════════════════════════════════════
#  DEMANDE DE RETRAIT — SOUMETTRE
# ═══════════════════════════════════════════════════════════

class PartDemandeRetraitRequest(BaseModel):
    montant: float
    note:    Optional[str] = None


class PartDemandeRetraitResponse(BaseModel):
    success:          bool
    message:          str
    montant_demande:  float
    solde_disponible: float


# ═══════════════════════════════════════════════════════════
#  DEMANDES DE RETRAIT — HISTORIQUE (vue partenaire)
# ═══════════════════════════════════════════════════════════

class PartDemandeItem(BaseModel):
    id:         int
    montant:    float
    note:       Optional[str] = None
    statut:     str            # EN_ATTENTE | APPROUVEE | REFUSEE
    note_admin: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PartDemandesResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[PartDemandeItem]