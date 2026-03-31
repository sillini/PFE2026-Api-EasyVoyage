"""
app/schemas/finances_partenaire.py
===================================
Schémas Pydantic exclusifs à l'espace partenaire (finance).

Ces schémas sont SÉPARÉS de finances.py (admin) pour ne pas modifier
l'existant et garder une totale indépendance entre les deux espaces.
"""
from __future__ import annotations
from datetime import datetime, date
from typing import List, Optional
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════
#  DASHBOARD PARTENAIRE
# ═══════════════════════════════════════════════════════════

class PartDashboard(BaseModel):
    """KPIs affichés en haut de l'espace finance partenaire."""
    solde_disponible:    float   # montant_paye_total - déjà versé → à retirer
    revenu_mois:         float   # revenu brut ce mois (clients + visiteurs)
    revenu_mois_precedent: float # pour calcul évolution %
    evolution_pct:       float   # (revenu_mois - revenu_mois_precedent) / revenu_mois_precedent * 100
    nb_reservations_mois: int    # clients + visiteurs ce mois
    revenu_annee:        float   # revenu brut cette année


# ═══════════════════════════════════════════════════════════
#  REVENUS MENSUELS (graphique)
# ═══════════════════════════════════════════════════════════

class PartRevenuMois(BaseModel):
    """Un point de données pour le graphique revenus mensuels."""
    mois:        str    # "Jan", "Fév", …
    annee:       int
    revenu:      float  # clients + visiteurs
    nb_resas:    int


class PartRevenusResponse(BaseModel):
    annee:       int
    mois_liste:  List[PartRevenuMois]


# ═══════════════════════════════════════════════════════════
#  MES HÔTELS (liste niveau 1)
# ═══════════════════════════════════════════════════════════

class PartHotelItem(BaseModel):
    """Résumé financier d'un hôtel appartenant au partenaire."""
    id_hotel:        int
    hotel_nom:       str
    hotel_ville:     str
    hotel_actif:     bool
    revenu_mois:     float   # clients + visiteurs ce mois
    revenu_total:    float   # clients + visiteurs tout temps
    nb_resas_mois:   int     # clients + visiteurs ce mois
    nb_resas_total:  int     # clients + visiteurs tout temps
    solde_restant:   float   # part partenaire non encore versée

    class Config:
        from_attributes = True


class PartHotelListResponse(BaseModel):
    items: List[PartHotelItem]


# ═══════════════════════════════════════════════════════════
#  RÉSERVATIONS D'UN HÔTEL (drill-down niveau 2)
# ═══════════════════════════════════════════════════════════

class PartReservationItem(BaseModel):
    """
    Une réservation dans le drill-down d'un hôtel.
    Couvre les DEUX sources : clients (table reservation) et
    visiteurs (table reservation_visiteur).
    """
    id:               int
    source:           str              # "client" | "visiteur"
    reference:        str              # numéro facture (client) ou voucher (visiteur)
    client_nom:       str              # nom complet ou "Visiteur"
    client_email:     str
    date_debut:       date
    date_fin:         date
    nb_nuits:         int
    montant_total:    float            # total_ttc
    part_partenaire:  float            # 90% du montant_total
    statut:           str              # CONFIRMEE / TERMINEE / ANNULEE
    statut_paiement:  str              # "PAYEE" | "EN_ATTENTE" (commission partenaire)
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
    """Un virement reçu de l'admin."""
    id:         int
    montant:    float
    note:       Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PartPaiementsResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[PartPaiementItem]


# ═══════════════════════════════════════════════════════════
#  DEMANDE DE RETRAIT
# ═══════════════════════════════════════════════════════════

class PartDemandeRetraitRequest(BaseModel):
    montant: float
    note:    Optional[str] = None


class PartDemandeRetraitResponse(BaseModel):
    message:          str
    montant_demande:  float
    solde_disponible: float