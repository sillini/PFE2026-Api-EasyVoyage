"""
app/services/finances/utils.py
==============================
Fonctions de calcul financier pures — aucune dépendance externe.

RÈGLES MÉTIER IMMUABLES :
  1. commission_agence = TAUX % × revenu_hotel  (JAMAIS sur revenu_voyage)
  2. part_partenaire   = revenu_hotel − commission_agence
  3. solde_a_payer     = part_partenaire − montant_deja_paye
"""
from __future__ import annotations

TAUX_COMMISSION_DEFAULT: float = 10.0


def calc_commission_agence(revenu_hotel: float, taux: float = TAUX_COMMISSION_DEFAULT) -> float:
    """Commission agence = taux% du revenu hôtel uniquement."""
    return round(revenu_hotel * taux / 100, 2)


def calc_part_partenaire(revenu_hotel: float, taux: float = TAUX_COMMISSION_DEFAULT) -> float:
    """Part partenaire = revenu hôtel − commission agence."""
    return round(revenu_hotel - calc_commission_agence(revenu_hotel, taux), 2)


def calc_solde_restant(part_partenaire: float, montant_deja_paye: float) -> float:
    """Solde encore dû au partenaire."""
    return round(max(0.0, part_partenaire - montant_deja_paye), 2)