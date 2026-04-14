"""
app/schemas/fiscal.py
======================
Schémas Pydantic pour les règles fiscales et le détail de calcul.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class FiscalRuleBase(BaseModel):
    cle:          str            = Field(..., examples=["taxe_sejour_2_3"])
    libelle:      str            = Field(..., examples=["Taxe de séjour (2-3★)"])
    valeur:       float          = Field(..., ge=0, examples=[2.0])
    type_valeur:  str            = Field("MONTANT_FIXE", examples=["PAR_NUIT"])
    description:  Optional[str] = None
    actif:        bool           = True
    nb_nuits_max: Optional[int] = None
    etoiles_min:  Optional[int] = None
    etoiles_max:  Optional[int] = None


class FiscalRuleCreate(FiscalRuleBase):
    pass


class FiscalRuleUpdate(BaseModel):
    libelle:      Optional[str]   = None
    valeur:       Optional[float] = Field(None, ge=0)
    type_valeur:  Optional[str]   = None
    description:  Optional[str]   = None
    actif:        Optional[bool]  = None
    nb_nuits_max: Optional[int]   = None
    etoiles_min:  Optional[int]   = None
    etoiles_max:  Optional[int]   = None


class FiscalRuleResponse(FiscalRuleBase):
    id:         int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class FiscalRuleListResponse(BaseModel):
    total: int
    items: List[FiscalRuleResponse]


class DetailFiscal(BaseModel):
    """Décomposition fiscale complète d'une facture."""
    montant_ht:        float = Field(..., description="Montant HT de base")
    taxe_sejour:       float = Field(..., description="Taxe de séjour totale (tarif × nuits_taxables × nb_personnes)")
    nb_nuits_taxables: int   = Field(..., description="Nuits effectivement taxées")
    nb_personnes:      int   = Field(default=1, description="Nombre de personnes (adultes + enfants)")
    tva_base:          float = Field(..., description="Base de calcul TVA (= montant_ht)")
    tva_montant:       float = Field(..., description="Montant TVA")
    taux_tva:          float = Field(..., description="Taux TVA en %")
    droit_timbre:      float = Field(..., description="Droit de timbre fixe")
    total_ttc:         float = Field(..., description="Total TTC")