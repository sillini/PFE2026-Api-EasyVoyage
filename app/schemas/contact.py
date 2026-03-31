# app/schemas/contact.py
"""
Pydantic schemas pour la table contact (base de contacts unifiée).
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field


# ══════════════════════════════════════════════════════════
#  RÉPONSE UNITAIRE
# ══════════════════════════════════════════════════════════
class ContactResponse(BaseModel):
    id:         int
    email:      str
    telephone:  Optional[str]
    nom:        Optional[str]
    prenom:     Optional[str]
    type:       str               # 'client' | 'visiteur'
    source_id:  Optional[int]     # id dans utilisateur ou reservation_visiteur
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════
#  LISTE PAGINÉE (admin)
# ══════════════════════════════════════════════════════════
class ContactListResponse(BaseModel):
    total:        int
    page:         int
    per_page:     int
    nb_clients:   int
    nb_visiteurs: int
    items:        List[ContactResponse]


# ══════════════════════════════════════════════════════════
#  STATISTIQUES (tableau de bord admin)
# ══════════════════════════════════════════════════════════
class ContactStatsResponse(BaseModel):
    total:        int
    nb_clients:   int
    nb_visiteurs: int