"""
app/services/fiscal_service.py
================================
Service fiscal centralisé.

Règles :
  PAR_NUIT     → taxe × min(nb_nuits, nb_nuits_max) × nb_personnes
  POURCENTAGE  → taux appliqué sur montant_ht (TVA)
  MONTANT_FIXE → montant fixe par facture (droit de timbre)

Changement : taxe de séjour calculée PAR PERSONNE × nuit.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fiscal import FiscalRule
from app.schemas.fiscal import DetailFiscal, FiscalRuleResponse, FiscalRuleListResponse


# ═══════════════════════════════════════════════════════════
#  CRUD
# ═══════════════════════════════════════════════════════════

async def list_rules(session: AsyncSession) -> FiscalRuleListResponse:
    result = await session.execute(select(FiscalRule).order_by(FiscalRule.id))
    rules  = result.scalars().all()
    return FiscalRuleListResponse(
        total=len(rules),
        items=[FiscalRuleResponse.model_validate(r) for r in rules],
    )


async def get_rule_by_id(rule_id: int, session: AsyncSession) -> FiscalRule:
    result = await session.execute(select(FiscalRule).where(FiscalRule.id == rule_id))
    rule   = result.scalar_one_or_none()
    if not rule:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(f"Règle fiscale {rule_id} introuvable")
    return rule


async def update_rule(rule_id: int, data: dict, session: AsyncSession) -> FiscalRuleResponse:
    rule = await get_rule_by_id(rule_id, session)
    for field, value in data.items():
        if value is not None and hasattr(rule, field):
            setattr(rule, field, value)
    await session.commit()
    await session.refresh(rule)
    return FiscalRuleResponse.model_validate(rule)


# ═══════════════════════════════════════════════════════════
#  HELPER
# ═══════════════════════════════════════════════════════════

async def _load_active_rules(session: AsyncSession) -> dict:
    result = await session.execute(select(FiscalRule).where(FiscalRule.actif == True))
    return {r.cle: r for r in result.scalars().all()}


# ═══════════════════════════════════════════════════════════
#  CALCUL FISCAL HÔTEL
# ═══════════════════════════════════════════════════════════

async def calculer_fiscal(
    *,
    montant_ht:    float,
    nb_nuits:      int,
    nb_personnes:  int,
    etoiles_hotel: int,
    session:       AsyncSession,
) -> DetailFiscal:
    """
    Taxe de séjour = tarif × min(nb_nuits, nb_nuits_max) × nb_personnes

    Exemple : hôtel 4★, 3 nuits, 2 adultes, 200 DT HT
        taxe  = 3 DT × 3 × 2 = 18 DT
        TVA   = 200 × 7% = 14 DT
        timbre = 1 DT
        TTC   = 233 DT
    """
    rules = await _load_active_rules(session)
    nb_pers = max(nb_personnes, 1)

    # 1. Taxe de séjour
    taxe_sejour       = 0.0
    nb_nuits_taxables = 0

    for cle, rule in rules.items():
        if rule.type_valeur != "PAR_NUIT":
            continue
        if rule.etoiles_min is None or rule.etoiles_max is None:
            continue
        if rule.etoiles_min <= etoiles_hotel <= rule.etoiles_max:
            nb_max            = rule.nb_nuits_max or 7
            nb_nuits_taxables = min(nb_nuits, nb_max)
            taxe_sejour       = round(float(rule.valeur) * nb_nuits_taxables * nb_pers, 3)
            break

    # 2. TVA sur montant HT
    taux_tva    = float(rules["tva"].valeur) if "tva" in rules else 0.0
    tva_montant = round(montant_ht * taux_tva / 100, 3)

    # 3. Droit de timbre
    droit_timbre = round(float(rules["droit_timbre"].valeur), 3) if "droit_timbre" in rules else 0.0

    # 4. Total
    total_ttc = round(montant_ht + taxe_sejour + tva_montant + droit_timbre, 3)

    return DetailFiscal(
        montant_ht        = round(montant_ht, 3),
        taxe_sejour       = taxe_sejour,
        nb_nuits_taxables = nb_nuits_taxables,
        nb_personnes      = nb_pers,
        tva_base          = round(montant_ht, 3),
        tva_montant       = tva_montant,
        taux_tva          = taux_tva,
        droit_timbre      = droit_timbre,
        total_ttc         = total_ttc,
    )


# ═══════════════════════════════════════════════════════════
#  CALCUL FISCAL VOYAGE
# ═══════════════════════════════════════════════════════════

async def calculer_fiscal_voyage(
    *,
    montant_ht: float,
    session:    AsyncSession,
) -> DetailFiscal:
    """Voyage : TVA + timbre uniquement, pas de taxe de séjour."""
    rules = await _load_active_rules(session)

    taux_tva     = float(rules["tva"].valeur)           if "tva"           in rules else 0.0
    tva_montant  = round(montant_ht * taux_tva / 100, 3)
    droit_timbre = round(float(rules["droit_timbre"].valeur), 3) if "droit_timbre" in rules else 0.0
    total_ttc    = round(montant_ht + tva_montant + droit_timbre, 3)

    return DetailFiscal(
        montant_ht        = round(montant_ht, 3),
        taxe_sejour       = 0.0,
        nb_nuits_taxables = 0,
        nb_personnes      = 0,
        tva_base          = round(montant_ht, 3),
        tva_montant       = tva_montant,
        taux_tva          = taux_tva,
        droit_timbre      = droit_timbre,
        total_ttc         = total_ttc,
    )