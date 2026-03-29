"""
Pydantic schemas pour Hôtels, Chambres, Tarifs et Avis.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════
#  DISPONIBILITE
# ═══════════════════════════════════════════════════════════
class OccupationPeriode(BaseModel):
     date_debut:     date
     date_fin:       date
     id_reservation: Optional[int] = None
     numero_ref:     Optional[str] = None   # N° facture (client) ou N° voucher (visiteur)
     source:         Optional[str] = None   # "client" | "visiteur"
     model_config = {"from_attributes": True}


class ChambreDisponibiliteResponse(BaseModel):
    """
    Représente un TYPE de chambre avec son stock et sa disponibilité sur une période.
    nb_total       = nb_chambres dans la table chambre
    nb_reservees   = nombre de réservations confirmées qui chevauchent la période
    nb_disponibles = nb_total - nb_reservees  (≥ 0)
    disponible     = nb_disponibles > 0
    """
    chambre_id:     int
    disponible:     bool
    nb_total:       int = 0          # stock total
    nb_reservees:   int = 0          # occupées sur la période
    nb_disponibles: int = 0          # restantes disponibles
    occupations:    List[OccupationPeriode] = []
    prix_min:       Optional[float] = None
    prix_max:       Optional[float] = None
    type_chambre:   Optional[Dict[str, Any]] = None
    capacite:       Optional[int]   = None
    description:    Optional[str]   = None
    model_config = {"from_attributes": True}


class HotelDisponibilitesResponse(BaseModel):
    hotel_id:   int
    date_debut: date
    date_fin:   date
    chambres:   List[ChambreDisponibiliteResponse]
    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  HOTEL
# ═══════════════════════════════════════════════════════════
class HotelCreate(BaseModel):
    nom:         str           = Field(..., min_length=2, max_length=200)
    etoiles:     int           = Field(..., ge=1, le=5)
    adresse:     str           = Field(..., max_length=500)
    ville:       str           = Field("Tunis", max_length=100)
    pays:        str           = Field("Tunisie", max_length=100)
    description: Optional[str] = None


class HotelAdminUpdate(BaseModel):
    actif: bool


class HotelFeaturedUpdate(BaseModel):
    mis_en_avant: bool


class HotelUpdate(BaseModel):
    nom:         Optional[str]  = Field(None, min_length=2, max_length=200)
    etoiles:     Optional[int]  = Field(None, ge=1, le=5)
    adresse:     Optional[str]  = Field(None, max_length=500)
    ville:       Optional[str]  = Field(None, max_length=100)
    pays:        Optional[str]  = Field(None, max_length=100)
    description: Optional[str]  = None
    actif:       Optional[bool] = None


class PartenaireInfo(BaseModel):
    id:     int
    nom:    str
    prenom: str
    email:  str
    model_config = {"from_attributes": True}


class HotelResponse(BaseModel):
    id:            int
    nom:           str
    etoiles:       int
    adresse:       str
    ville:         Optional[str]            = None
    pays:          str
    description:   Optional[str]
    note_moyenne:  Optional[float]
    actif:         bool
    mis_en_avant:  bool                     = False
    id_partenaire: Optional[int]            = None
    partenaire:    Optional[PartenaireInfo] = None
    created_at:    datetime
    updated_at:    datetime
    model_config = {"from_attributes": True}


class VilleVedetteCreate(BaseModel):
    nom:   str  = Field(..., min_length=2, max_length=100)
    ordre: int  = Field(0, ge=0)
    actif: bool = True


class VilleVedetteUpdate(BaseModel):
    ordre: Optional[int]  = None
    actif: Optional[bool] = None


class VilleVedetteResponse(BaseModel):
    id:    int
    nom:   str
    ordre: int
    actif: bool
    model_config = {"from_attributes": True}


class HotelListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[HotelResponse]


# ═══════════════════════════════════════════════════════════
#  TYPE CHAMBRE
# ═══════════════════════════════════════════════════════════
class TypeChambreResponse(BaseModel):
    id:          int
    nom:         str
    description: Optional[str]
    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  CHAMBRE
# ═══════════════════════════════════════════════════════════
class ChambreCreate(BaseModel):
    capacite:        int           = Field(..., gt=0, examples=[2])
    description:     Optional[str] = Field(None, examples=["Chambre avec vue sur mer"])
    id_type_chambre: int           = Field(..., examples=[1])
    nb_chambres:     int           = Field(1, gt=0, examples=[5],
                                           description="Nombre de chambres de ce type dans l'hôtel")


class ChambreUpdate(BaseModel):
    capacite:        Optional[int]  = Field(None, gt=0)
    description:     Optional[str]  = None
    id_type_chambre: Optional[int]  = None
    nb_chambres:     Optional[int]  = Field(None, gt=0)
    actif:           Optional[bool] = None


class ChambreResponse(BaseModel):
    id:              int
    capacite:        int
    description:     Optional[str]
    id_hotel:        int
    id_type_chambre: int
    type_chambre:    Optional[TypeChambreResponse] = None
    nb_chambres:     int = 1          # ← stock total
    actif:           bool
    created_at:      datetime
    updated_at:      datetime
    prix_min:        Optional[float] = None
    prix_max:        Optional[float] = None
    model_config = {"from_attributes": True}


class ChambreListResponse(BaseModel):
    total: int
    items: List[ChambreResponse]


# ═══════════════════════════════════════════════════════════
#  TYPE RESERVATION
# ═══════════════════════════════════════════════════════════
class TypeReservationResponse(BaseModel):
    id:          int
    nom:         str
    description: Optional[str]
    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
#  TARIF
# ═══════════════════════════════════════════════════════════
class TarifCreate(BaseModel):
    prix:                float = Field(..., ge=0, examples=[150.00])
    date_debut:          date  = Field(..., examples=["2026-06-01"])
    date_fin:            date  = Field(..., examples=["2026-08-31"])
    id_type_reservation: int   = Field(..., examples=[1])

    @field_validator("date_fin")
    @classmethod
    def date_fin_after_debut(cls, v, info) -> date:
        if "date_debut" in info.data and v < info.data["date_debut"]:
            raise ValueError("date_fin doit être >= date_debut")
        return v


class TarifUpdate(BaseModel):
    prix:                Optional[float] = Field(None, ge=0)
    date_debut:          Optional[date]  = None
    date_fin:            Optional[date]  = None
    id_type_reservation: Optional[int]   = None

    @field_validator("date_fin")
    @classmethod
    def date_fin_after_debut(cls, v, info) -> date:
        if v and "date_debut" in info.data and info.data["date_debut"] and v < info.data["date_debut"]:
            raise ValueError("date_fin doit être >= date_debut")
        return v


class TarifResponse(BaseModel):
    id:                  int
    prix:                float
    date_debut:          date
    date_fin:            date
    id_chambre:          int
    id_type_reservation: int
    type_reservation:    Optional[TypeReservationResponse] = None
    created_at:          datetime
    model_config = {"from_attributes": True}


class TarifListResponse(BaseModel):
    total: int
    items: List[TarifResponse]


# ═══════════════════════════════════════════════════════════
#  AVIS
# ═══════════════════════════════════════════════════════════
class AvisClientInfo(BaseModel):
    id:     int
    prenom: str
    nom:    str
    model_config = {"from_attributes": True}


class AvisCreate(BaseModel):
    note:        int           = Field(..., ge=1, le=5, examples=[4])
    commentaire: Optional[str] = Field(None, examples=["Excellent hôtel"])


class AvisResponse(BaseModel):
    id:          int
    note:        int
    commentaire: Optional[str]
    date:        datetime
    id_client:   int
    id_hotel:    int
    created_at:  datetime
    client:      Optional[AvisClientInfo] = None
    model_config = {"from_attributes": True}


class AvisListResponse(BaseModel):
    total:        int
    note_moyenne: float
    items:        List[AvisResponse]