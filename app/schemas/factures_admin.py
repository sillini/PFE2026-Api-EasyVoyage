"""
app/schemas/factures_admin.py
==============================
Schémas Pydantic pour la page Admin — Factures.

Trois types de factures unifiées :
  - "client"     : réservation d'un client connecté (Reservation → Facture)
  - "visiteur"   : réservation sans compte (ReservationVisiteur → Facture)
  - "partenaire" : paiement admin → partenaire (PaiementPartenaire)

KPIs globaux + liste paginée + détail.
"""
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
#  KPIs GLOBAUX
# ═══════════════════════════════════════════════════════════

class FacturesKpis(BaseModel):
    """Statistiques globales affichées en haut de la page."""

    # Montants
    total_facture_clients:     float  # somme montants factures clients PAYEE
    total_facture_visiteurs:   float  # somme montants factures visiteurs PAYEE
    total_paiements_partenaires: float  # somme paiements partenaires

    # Compteurs clients
    nb_clients_payee:   int
    nb_clients_emise:   int
    nb_clients_retard:  int
    nb_clients_annulee: int

    # Compteurs visiteurs
    nb_visiteurs_payee:   int
    nb_visiteurs_annulee: int

    # Compteurs partenaires
    nb_paiements_partenaires: int

    # Totaux globaux pratiques pour les KPI cards du frontend
    total_global_facture: float   # total_facture_clients + total_facture_visiteurs
    nb_total_payees:      int     # nb_clients_payee + nb_visiteurs_payee
    nb_total_emises:      int     # nb_clients_emise
    nb_total_retard:      int     # nb_clients_retard


# ═══════════════════════════════════════════════════════════
#  ITEM UNIFIÉ (une ligne dans le tableau)
# ═══════════════════════════════════════════════════════════

class FactureAdminItem(BaseModel):
    """
    Représente une facture unifiée dans le tableau admin.
    Le champ `type` discrimine les trois catégories.
    """

    # ── Identifiant
    id:   int                                           # id de la facture ou du paiement partenaire
    type: Literal["client", "visiteur", "partenaire"]  # discriminant

    # ── Numéro & dates
    numero:        str            # FAC-2025-00042 ou PP-2025-00001
    date_emission: datetime

    # ── Client / Visiteur / Partenaire
    personne_nom:    str           # nom + prénom concaténés
    personne_email:  str
    personne_tel:    Optional[str] = None

    # ── Contexte (hôtel, voyage, entreprise…)
    contexte: Optional[str] = None  # ex: "Hôtel Royal Hammamet" | "Voyage Djerba" | "TourSud Voyages"

    # ── Financier
    montant_total: float

    # ── Statut (s'applique uniquement aux factures clients/visiteurs)
    statut: Optional[str] = None   # EMISE | PAYEE | ANNULEE | EN_RETARD | None (partenaires)

    # ── Méthode paiement (visiteurs)
    methode_paiement: Optional[str] = None

    # ── PDF disponible
    has_pdf: bool = False

    # ── Note (paiements partenaires)
    note: Optional[str] = None

    class Config:
        from_attributes = True


class FacturesAdminListResponse(BaseModel):
    """Réponse paginée pour la liste admin."""
    total:    int
    page:     int
    per_page: int
    items:    List[FactureAdminItem]


# ═══════════════════════════════════════════════════════════
#  DÉTAIL ENRICHI D'UNE FACTURE
# ═══════════════════════════════════════════════════════════

class LigneFactureDetail(BaseModel):
    """Une ligne de détail dans la facture (chambre ou voyage)."""
    description:   str    # "Chambre Deluxe — 3 nuits" ou "Voyage Djerba"
    date_debut:    Optional[str] = None
    date_fin:      Optional[str] = None
    nb_nuits:      Optional[int] = None
    prix_unitaire: Optional[float] = None
    quantite:      Optional[int] = None
    sous_total:    float


class FactureAdminDetail(BaseModel):
    """Détail complet d'une facture — affiché dans la modale ou page détail."""

    id:            int
    type:          Literal["client", "visiteur", "partenaire"]
    numero:        str
    date_emission: datetime
    montant_total: float
    statut:        Optional[str] = None
    note:          Optional[str] = None
    has_pdf:       bool = False

    # ── Infos personne
    personne_nom:   str
    personne_email: str
    personne_tel:   Optional[str] = None

    # ── Lignes de détail
    lignes: List[LigneFactureDetail] = []

    # ── Réservation source (pour clients/visiteurs)
    reservation_id:     Optional[int] = None
    numero_voucher:     Optional[str] = None   # visiteurs uniquement
    methode_paiement:   Optional[str] = None

    # ── Partenaire (pour paiements partenaires)
    partenaire_entreprise: Optional[str] = None
    partenaire_id:         Optional[int] = None


# ═══════════════════════════════════════════════════════════
#  PARAMÈTRES DE FILTRE (documentés pour l'endpoint)
# ═══════════════════════════════════════════════════════════

class FacturesAdminFilters(BaseModel):
    """
    Paramètres de filtrage acceptés par GET /factures/admin.
    (Utilisé uniquement pour la documentation — les params viennent de Query())
    """
    type:       Optional[Literal["client", "visiteur", "partenaire"]] = None
    statut:     Optional[str]  = None   # EMISE | PAYEE | ANNULEE | EN_RETARD
    search:     Optional[str]  = None   # recherche nom, email, n° facture
    date_debut: Optional[str]  = None   # ISO date YYYY-MM-DD
    date_fin:   Optional[str]  = None   # ISO date YYYY-MM-DD
    page:       int            = Field(1,  ge=1)
    per_page:   int            = Field(20, ge=1, le=100)