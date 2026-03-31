"""
app/services/finances/__init__.py
==================================
Package service financier — exports publics.
"""
from app.services.finances.service import (
    get_dashboard,
    get_revenus,
    get_partenaires_finances,
    get_hotels_finances_partenaire,
    get_reservations_finances_hotel,
    get_soldes_partenaires,
    payer_partenaire,
    get_historique_paiements,
    get_clients_visiteurs_classement,
    list_commissions,
    sync_commission_reservation,
)

__all__ = [
    "get_dashboard",
    "get_revenus",
    "get_partenaires_finances",
    "get_hotels_finances_partenaire",
    "get_reservations_finances_hotel",
    "get_soldes_partenaires",
    "payer_partenaire",
    "get_historique_paiements",
    "get_clients_visiteurs_classement",
    "list_commissions",
    "sync_commission_reservation",
]