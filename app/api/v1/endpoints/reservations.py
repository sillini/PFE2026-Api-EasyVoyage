"""
app/api/v1/endpoints/reservations.py
=====================================
Routes :
  POST  /reservations/voyage                        → Réserver voyage [CLIENT]
  POST  /reservations/chambres                      → Réserver chambre hôtel [CLIENT]
  POST  /reservations/visiteur                      → Réservation hôtel visiteur sans compte
                                                      + envoi automatique du voucher par email
                                                      + création automatique de la facture
  GET   /reservations/mes-reservations              → Mes réservations [CLIENT]
  GET   /reservations                               → Toutes [ADMIN]
  GET   /reservations/admin/enrichi                 → Clients + Visiteurs enrichis [ADMIN]
  GET   /reservations/partenaire/mes-hotels         → Hôtels du partenaire + stats [PARTENAIRE]
  GET   /reservations/partenaire/hotel/{hotel_id}   → Réservations d'un hôtel [PARTENAIRE]
  GET   /reservations/{id}                          → Détail [CLIENT|ADMIN]
  POST  /reservations/{id}/paiement                 → Payer [CLIENT]
  POST  /reservations/{id}/annuler                  → Annuler [CLIENT|ADMIN]
  GET   /reservations/visiteur/{v}/pdf              → Voucher PDF visiteur hôtel
  GET   /reservations/visiteur/{v}/facture-pdf      → Facture PDF visiteur [ADMIN]
  POST  /reservations/visiteur/{id}/annuler         → Annuler réservation visiteur [ADMIN]
  GET   /reservations/{id}/voucher-pdf              → Voucher PDF client (hôtel ou voyage)

  💡 Les commissions partenaires (10%) sont créées automatiquement
     par le trigger PostgreSQL trg_commission_auto sur voyage_hotel.reservation.
"""
from typing import Optional, List
import asyncio as _asyncio
import uuid as _uuid
import io as _io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse as _SR
from pydantic import BaseModel as _BM
from sqlalchemy import select as _sel, func as _func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload as _sil

from app.api.v1.dependencies import (
    get_current_user,
    require_admin,
    require_client,
    require_partenaire,
)
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.reservation import (
    FactureResponse, PaiementRequest,
    ReservationChambresCreate, ReservationListResponse,
    ReservationResponse, ReservationVoyageCreate,
)
from app.models.reservation import (
    Reservation, Facture, StatutFacture,
    ReservationVisiteur as _RV,
)
from app.models.hotel import Chambre as _Ch, Tarif as _T
from app.models.voyage import Voyage as _Voyage
from app.services.email_service import send_voucher_email as _send_voucher_email
from app.services.contact_service import upsert_contact   # ← NOUVEAU
import app.services.reservation_service as reservation_service

router = APIRouter(prefix="/reservations", tags=["Réservations"])


# ══════════════════════════════════════════════════════════
#  CLIENT — VOYAGE
# ══════════════════════════════════════════════════════════
@router.post("/voyage", response_model=ReservationResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Réserver un voyage [CLIENT]")
async def reserver_voyage(
    data: ReservationVoyageCreate,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_client),
) -> ReservationResponse:
    return await reservation_service.create_reservation_voyage(data, token.user_id, session)


# ══════════════════════════════════════════════════════════
#  CLIENT — CHAMBRES HÔTEL
# ══════════════════════════════════════════════════════════
@router.post("/chambres", response_model=ReservationResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Réserver des chambres [CLIENT]")
async def reserver_chambres(
    data: ReservationChambresCreate,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_client),
) -> ReservationResponse:
    return await reservation_service.create_reservation_chambres(data, token.user_id, session)


# ══════════════════════════════════════════════════════════
#  VISITEUR SANS COMPTE — HÔTEL
# ══════════════════════════════════════════════════════════
class VisiteurReservationRequest(_BM):
    nom:        str
    prenom:     str
    email:      str
    telephone:  str
    date_debut: str
    date_fin:   str
    id_chambre: int
    nb_adultes: int = 1
    nb_enfants: int = 0
    methode:    str = "CARTE_BANCAIRE"


class VisiteurReservationResponse(_BM):
    id:             int
    numero_voucher: str
    numero_facture: Optional[str] = None
    montant_total:  float
    statut:         str
    email:          str
    nom:            str
    prenom:         str
    date_debut:     str
    date_fin:       str
    hotel_nom:      str
    chambre_nom:    str
    nb_adultes:     int
    nb_enfants:     int
    nb_nuits:       int


@router.post(
    "/visiteur",
    response_model=VisiteurReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Réservation hôtel visiteur sans compte (+ voucher email + facture auto)",
)
async def reserver_visiteur(
    data: VisiteurReservationRequest,
    session: AsyncSession = Depends(get_db),
):
    from datetime import date as _date
    from app.models.hotel import Hotel as _H
    from app.services.reservation_service import _generate_numero_facture

    # ── 1. Valider les dates ───────────────────────────────
    try:
        d1 = _date.fromisoformat(data.date_debut)
        d2 = _date.fromisoformat(data.date_fin)
    except ValueError:
        raise HTTPException(400, "Format de date invalide (attendu : YYYY-MM-DD)")

    if d2 <= d1:
        raise HTTPException(422, "date_fin doit être après date_debut")

    nb_nuits = (d2 - d1).days

    # ── 2. Charger la chambre (active) ─────────────────────
    ch_res = await session.execute(
        _sel(_Ch)
        .options(_sil(_Ch.type_chambre))
        .where(_Ch.id == data.id_chambre, _Ch.actif == True)
    )
    chambre = ch_res.scalar_one_or_none()
    if not chambre:
        raise HTTPException(404, "Chambre introuvable ou inactive")

    # ── 3. Trouver le tarif applicable ─────────────────────
    t_res = await session.execute(
        _sel(_T).where(
            _T.id_chambre == data.id_chambre,
            _T.date_debut <= d1,
            _T.date_fin   >= d2,
        ).order_by(_T.prix.asc()).limit(1)
    )
    tarif = t_res.scalar_one_or_none()
    if not tarif:
        raise HTTPException(422, f"Aucun tarif disponible pour la période {d1} → {d2}")

    total_ttc = round(float(tarif.prix) * nb_nuits, 2)

    # ── 4. Générer un numéro de voucher unique ─────────────
    annee  = d1.year
    cnt_r  = await session.execute(_sel(_func.count(_RV.id)))
    cnt    = cnt_r.scalar_one() + 1
    numero_voucher = f"VIS-{annee}-{cnt:05d}-{_uuid.uuid4().hex[:4].upper()}"

    # ── 5. Créer la réservation visiteur ───────────────────
    resa = _RV(
        nom              = data.nom,
        prenom           = data.prenom,
        email            = data.email,
        telephone        = data.telephone,
        id_chambre       = data.id_chambre,
        date_debut       = d1,
        date_fin         = d2,
        nb_adultes       = data.nb_adultes,
        nb_enfants       = data.nb_enfants,
        total_ttc        = total_ttc,
        methode_paiement = data.methode,
        transaction_id   = "T-" + _uuid.uuid4().hex[:8].upper(),
        statut           = "CONFIRMEE",
        numero_voucher   = numero_voucher,
    )
    session.add(resa)
    await session.flush()

    # ── 5b. Créer la facture et la lier à la réservation ───
    numero_facture = await _generate_numero_facture(session)
    facture_vis = Facture(
        numero         = numero_facture,
        montant_total  = total_ttc,
        statut         = StatutFacture.PAYEE,
        id_reservation = None,
    )
    session.add(facture_vis)
    await session.flush()

    resa.id_facture = facture_vis.id

    # ── 5c. Sync contact visiteur ──────────────────────────
    await upsert_contact(
        session,
        email     = data.email,
        telephone = data.telephone,
        nom       = data.nom,
        prenom    = data.prenom,
        type      = "visiteur",
        source_id = resa.id,
    )

    await session.commit()
    await session.refresh(resa)

    # ── 6. Charger les infos hôtel pour la réponse + email ─
    h_res = await session.execute(_sel(_H).where(_H.id == chambre.id_hotel))
    hotel = h_res.scalar_one_or_none()

    chambre_nom = chambre.type_chambre.nom if chambre.type_chambre else "Chambre"
    hotel_nom   = hotel.nom   if hotel else "Hôtel"
    hotel_ville = hotel.ville if hotel else "—"

    # ── 7. Générer le PDF voucher ───────────────────────────
    pdf_bytes = _generate_voucher_pdf(
        type_resa   = "hotel",
        numero      = numero_voucher,
        nom         = f"{data.prenom} {data.nom}",
        email       = data.email,
        telephone   = data.telephone,
        hotel_nom   = hotel_nom,
        hotel_ville = hotel_ville,
        chambre_nom = chambre_nom,
        date_debut  = data.date_debut,
        date_fin    = data.date_fin,
        nb_nuits    = nb_nuits,
        nb_adultes  = data.nb_adultes,
        nb_enfants  = data.nb_enfants,
        montant     = total_ttc,
        methode     = data.methode,
    )

    # ── 8. Envoyer le voucher PDF par email (non-bloquant) ──
    _asyncio.create_task(
        _send_voucher_email(
            to             = data.email,
            prenom         = data.prenom,
            nom            = data.nom,
            numero_voucher = numero_voucher,
            hotel_nom      = hotel_nom,
            hotel_ville    = hotel_ville,
            chambre_nom    = chambre_nom,
            date_debut     = data.date_debut,
            date_fin       = data.date_fin,
            nb_nuits       = nb_nuits,
            nb_adultes     = data.nb_adultes,
            nb_enfants     = data.nb_enfants,
            montant        = total_ttc,
            methode        = data.methode,
            pdf_bytes      = pdf_bytes,
        )
    )

    # ── 9. Retourner la réponse ─────────────────────────────
    return VisiteurReservationResponse(
        id             = resa.id,
        numero_voucher = numero_voucher,
        numero_facture = numero_facture,
        montant_total  = total_ttc,
        statut         = resa.statut,
        email          = data.email,
        nom            = data.nom,
        prenom         = data.prenom,
        date_debut     = data.date_debut,
        date_fin       = data.date_fin,
        hotel_nom      = hotel_nom,
        chambre_nom    = chambre_nom,
        nb_adultes     = data.nb_adultes,
        nb_enfants     = data.nb_enfants,
        nb_nuits       = nb_nuits,
    )


# ══════════════════════════════════════════════════════════
#  MES RÉSERVATIONS
# ══════════════════════════════════════════════════════════
@router.get("/mes-reservations", response_model=ReservationListResponse,
            summary="Mes réservations [CLIENT]")
async def mes_reservations(
    statut: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_client),
) -> ReservationListResponse:
    return await reservation_service.mes_reservations(
        token.user_id, session, statut=statut, page=page, per_page=per_page
    )


# ══════════════════════════════════════════════════════════
#  ADMIN — TOUTES (basique)
# ══════════════════════════════════════════════════════════
@router.get("", response_model=ReservationListResponse,
            summary="Toutes les réservations clients [ADMIN]")
async def list_all_reservations(
    statut: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> ReservationListResponse:
    return await reservation_service.list_all_reservations(
        session, statut=statut, client_id=client_id, page=page, per_page=per_page
    )


# ══════════════════════════════════════════════════════════
#  ADMIN — ENRICHI : clients + visiteurs fusionnés
#  ⚠️  DOIT être AVANT /{reservation_id}
# ══════════════════════════════════════════════════════════

class ReservationAdminItem(_BM):
    """Représente une réservation unifiée — client ou visiteur."""
    id:                  int
    source:              str
    date_reservation:    str
    date_debut:          str
    date_fin:            str
    nb_nuits:            int
    statut:              str
    total_ttc:           float
    client_nom:          str
    client_prenom:       str
    client_email:        str
    client_telephone:    Optional[str]  = None
    type_resa:           str
    hotel_nom:           Optional[str]  = None
    hotel_ville:         Optional[str]  = None
    voyage_titre:        Optional[str]  = None
    voyage_destination:  Optional[str]  = None
    numero_facture:      Optional[str]  = None
    statut_facture:      Optional[str]  = None
    numero_voucher:      Optional[str]  = None
    methode_paiement:    Optional[str]  = None


class ReservationAdminListResponse(_BM):
    total:        int
    page:         int
    per_page:     int
    nb_clients:   int
    nb_visiteurs: int
    items:        List[ReservationAdminItem]


async def _get_hotel_info(id_chambre: int, session) -> tuple:
    """Retourne (hotel_nom, hotel_ville) depuis un id_chambre."""
    from app.models.hotel import Hotel as _H
    ch_r = await session.execute(_sel(_Ch).where(_Ch.id == id_chambre))
    ch   = ch_r.scalar_one_or_none()
    if not ch:
        return (None, None)
    h_r = await session.execute(_sel(_H).where(_H.id == ch.id_hotel))
    h   = h_r.scalar_one_or_none()
    return (h.nom if h else None, h.ville if h else None)


@router.get(
    "/admin/enrichi",
    response_model=ReservationAdminListResponse,
    summary="Toutes les réservations enrichies — clients ET visiteurs [ADMIN]",
)
async def list_reservations_enrichi(
    statut:    Optional[str] = Query(None),
    type_resa: Optional[str] = Query(None),
    source:    Optional[str] = Query(None),
    search:    Optional[str] = Query(None),
    page:      int           = Query(1, ge=1),
    per_page:  int           = Query(20, ge=1, le=100),
    session: AsyncSession    = Depends(get_db),
    _: TokenData             = Depends(require_admin),
):
    from app.models.utilisateur import Utilisateur as _Usr
    from app.models.reservation import StatutReservation as _SR2

    items: List[ReservationAdminItem] = []

    # ── 1. Réservations clients ────────────────────────────
    if source in (None, "client"):
        query = (
            _sel(Reservation)
            .options(
                _sil(Reservation.lignes_chambres),
                _sil(Reservation.facture),
            )
            .order_by(Reservation.date_reservation.desc())
        )
        if statut:
            try:
                query = query.where(Reservation.statut == _SR2(statut))
            except ValueError:
                pass
        if type_resa == "hotel":
            query = query.where(Reservation.id_voyage == None)
        elif type_resa == "voyage":
            query = query.where(Reservation.id_voyage != None)

        result = await session.execute(query)
        resas  = result.scalars().all()

        for resa in resas:
            usr_r = await session.execute(_sel(_Usr).where(_Usr.id == resa.id_client))
            usr   = usr_r.scalar_one_or_none()
            hotel_nom = hotel_ville = voyage_titre = voyage_dest = None

            if resa.id_voyage:
                v_r = await session.execute(_sel(_Voyage).where(_Voyage.id == resa.id_voyage))
                v   = v_r.scalar_one_or_none()
                voyage_titre = v.titre       if v else f"Voyage #{resa.id_voyage}"
                voyage_dest  = v.destination if v else "—"
                type_r = "voyage"
            else:
                if resa.lignes_chambres:
                    hotel_nom, hotel_ville = await _get_hotel_info(
                        resa.lignes_chambres[0].id_chambre, session
                    )
                type_r = "hotel"

            items.append(ReservationAdminItem(
                id                 = resa.id,
                source             = "client",
                date_reservation   = resa.date_reservation.strftime("%d/%m/%Y %H:%M"),
                date_debut         = str(resa.date_debut),
                date_fin           = str(resa.date_fin),
                nb_nuits           = (resa.date_fin - resa.date_debut).days,
                statut             = resa.statut.value,
                total_ttc          = float(resa.total_ttc),
                client_nom         = usr.nom       if usr else "—",
                client_prenom      = usr.prenom    if usr else "—",
                client_email       = usr.email     if usr else "—",
                client_telephone   = getattr(usr, "telephone", None),
                type_resa          = type_r,
                hotel_nom          = hotel_nom,
                hotel_ville        = hotel_ville,
                voyage_titre       = voyage_titre,
                voyage_destination = voyage_dest,
                numero_facture     = resa.facture.numero       if resa.facture else None,
                statut_facture     = resa.facture.statut.value if resa.facture else None,
                numero_voucher     = None,
                methode_paiement   = None,
            ))

    nb_clients = len(items)

    # ── 2. Réservations visiteurs ──────────────────────────
    if source in (None, "visiteur") and type_resa in (None, "hotel"):
        vis_query = (
            _sel(_RV)
            .options(_sil(_RV.facture))
            .order_by(_RV.created_at.desc())
        )
        if statut:
            vis_query = vis_query.where(_RV.statut == statut)

        vis_result = await session.execute(vis_query)
        visiteurs  = vis_result.scalars().all()

        for vis in visiteurs:
            hotel_nom, hotel_ville = await _get_hotel_info(vis.id_chambre, session)

            num_fac  = vis.facture.numero         if vis.facture else None
            stat_fac = vis.facture.statut.value   if vis.facture else None

            items.append(ReservationAdminItem(
                id                 = vis.id,
                source             = "visiteur",
                date_reservation   = vis.created_at.strftime("%d/%m/%Y %H:%M"),
                date_debut         = str(vis.date_debut),
                date_fin           = str(vis.date_fin),
                nb_nuits           = (vis.date_fin - vis.date_debut).days,
                statut             = vis.statut,
                total_ttc          = float(vis.total_ttc),
                client_nom         = vis.nom,
                client_prenom      = vis.prenom,
                client_email       = vis.email,
                client_telephone   = vis.telephone,
                type_resa          = "hotel",
                hotel_nom          = hotel_nom,
                hotel_ville        = hotel_ville,
                voyage_titre       = None,
                voyage_destination = None,
                numero_facture     = num_fac,
                statut_facture     = stat_fac,
                numero_voucher     = vis.numero_voucher,
                methode_paiement   = vis.methode_paiement,
            ))

    nb_visiteurs = len(items) - nb_clients

    # ── 3. Filtre search ───────────────────────────────────
    if search:
        s = search.lower().strip()
        items = [
            it for it in items
            if s in (it.client_nom        or "").lower()
            or s in (it.client_prenom     or "").lower()
            or s in (it.client_email      or "").lower()
            or s in (it.hotel_nom         or "").lower()
            or s in (it.voyage_titre      or "").lower()
            or s in (it.numero_facture    or "").lower()
            or s in (it.numero_voucher    or "").lower()
        ]
        nb_clients   = sum(1 for it in items if it.source == "client")
        nb_visiteurs = sum(1 for it in items if it.source == "visiteur")

    items.sort(key=lambda x: x.date_reservation, reverse=True)

    total      = len(items)
    offset     = (page - 1) * per_page
    items_page = items[offset: offset + per_page]

    return ReservationAdminListResponse(
        total=total, page=page, per_page=per_page,
        nb_clients=nb_clients, nb_visiteurs=nb_visiteurs,
        items=items_page,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PARTENAIRE — RÉSERVATIONS DE SES HÔTELS
#  ⚠️  DOIT être AVANT /{reservation_id}
# ══════════════════════════════════════════════════════════════════════════════

class PartenaireHotelStats(_BM):
    hotel_id:          int
    hotel_nom:         str
    hotel_ville:       str
    hotel_image:       Optional[str] = None
    nb_reservations:   int
    nb_clients:        int
    nb_visiteurs:      int
    ca_total:          float


class PartenaireHotelListResponse(_BM):
    items: List[PartenaireHotelStats]


class PartenaireResaItem(_BM):
    id:                int
    source:            str
    date_reservation:  str
    date_debut:        str
    date_fin:          str
    nb_nuits:          int
    statut:            str
    total_ttc:         float
    client_nom:        str
    client_prenom:     str
    client_email:      str
    client_telephone:  Optional[str] = None
    chambre_nom:       Optional[str] = None
    numero_facture:    Optional[str] = None
    statut_facture:    Optional[str] = None
    numero_voucher:    Optional[str] = None
    methode_paiement:  Optional[str] = None
    nb_adultes:        int
    nb_enfants:        int


class PartenaireResaListResponse(_BM):
    hotel_id:     int
    hotel_nom:    str
    total:        int
    nb_clients:   int
    nb_visiteurs: int
    items:        List[PartenaireResaItem]


async def _hotel_appartient_partenaire(hotel_id: int, partenaire_id: int, session) -> bool:
    from app.models.hotel import Hotel
    res = await session.execute(
        _sel(Hotel).where(Hotel.id == hotel_id, Hotel.id_partenaire == partenaire_id)
    )
    return res.scalar_one_or_none() is not None


async def _get_chambre_ids_hotel(hotel_id: int, session) -> list:
    res = await session.execute(_sel(_Ch.id).where(_Ch.id_hotel == hotel_id))
    return [r[0] for r in res.all()]


async def _get_chambre_nom(id_chambre: int, session) -> str:
    from app.models.hotel import TypeChambre
    ch_res = await session.execute(_sel(_Ch).where(_Ch.id == id_chambre))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return f"Chambre #{id_chambre}"
    if ch.id_type_chambre:
        tc_res = await session.execute(
            _sel(TypeChambre).where(TypeChambre.id == ch.id_type_chambre)
        )
        tc = tc_res.scalar_one_or_none()
        return tc.nom if tc else f"Chambre #{id_chambre}"
    return f"Chambre #{id_chambre}"


@router.get(
    "/partenaire/mes-hotels",
    response_model=PartenaireHotelListResponse,
    summary="Hôtels du partenaire avec stats réservations [PARTENAIRE]",
)
async def partenaire_mes_hotels(
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
):
    from app.models.hotel import Hotel
    from app.models.image import Image as _Img
    from app.models.reservation import LigneReservationChambre

    res = await session.execute(
        _sel(Hotel)
        .where(Hotel.id_partenaire == token.user_id, Hotel.actif == True)
        .order_by(Hotel.nom.asc())
    )
    hotels = res.scalars().all()

    items = []
    for hotel in hotels:
        chambre_ids = await _get_chambre_ids_hotel(hotel.id, session)

        nb_clients   = 0
        nb_visiteurs = 0
        ca_total     = 0.0

        if chambre_ids:
            lrc_res = await session.execute(
                _sel(LigneReservationChambre.id_reservation)
                .where(LigneReservationChambre.id_chambre.in_(chambre_ids))
                .distinct()
            )
            resa_ids = [r[0] for r in lrc_res.all()]

            if resa_ids:
                count_res = await session.execute(
                    _sel(
                        _func.count(Reservation.id),
                        _func.coalesce(_func.sum(Reservation.total_ttc), 0),
                    ).where(Reservation.id.in_(resa_ids))
                )
                row = count_res.one()
                nb_clients = row[0] or 0
                ca_total  += float(row[1] or 0)

            vis_count_res = await session.execute(
                _sel(
                    _func.count(_RV.id),
                    _func.coalesce(_func.sum(_RV.total_ttc), 0),
                ).where(_RV.id_chambre.in_(chambre_ids))
            )
            vis_row = vis_count_res.one()
            nb_visiteurs = vis_row[0] or 0
            ca_total    += float(vis_row[1] or 0)

        img_res = await session.execute(
            _sel(_Img.url)
            .where(_Img.id_hotel == hotel.id, _Img.type == "PRINCIPALE")
            .limit(1)
        )
        img_url = img_res.scalar_one_or_none()
        if not img_url:
            img_res2 = await session.execute(
                _sel(_Img.url).where(_Img.id_hotel == hotel.id).limit(1)
            )
            img_url = img_res2.scalar_one_or_none()

        items.append(PartenaireHotelStats(
            hotel_id        = hotel.id,
            hotel_nom       = hotel.nom,
            hotel_ville     = hotel.ville or "—",
            hotel_image     = img_url,
            nb_reservations = nb_clients + nb_visiteurs,
            nb_clients      = nb_clients,
            nb_visiteurs    = nb_visiteurs,
            ca_total        = round(ca_total, 2),
        ))

    return PartenaireHotelListResponse(items=items)


@router.get(
    "/partenaire/hotel/{hotel_id}",
    response_model=PartenaireResaListResponse,
    summary="Réservations d'un hôtel [PARTENAIRE]",
)
async def partenaire_reservations_hotel(
    hotel_id:       int,
    source:         Optional[str] = Query(None, description="client | visiteur"),
    statut:         Optional[str] = Query(None, description="EN_ATTENTE | CONFIRMEE | ANNULEE | TERMINEE"),
    search:         Optional[str] = Query(None, description="Nom, prénom, email ou téléphone"),
    numero_facture: Optional[str] = Query(None, description="Numéro de facture (clients) ou voucher (visiteurs)"),
    session:        AsyncSession  = Depends(get_db),
    token:          TokenData     = Depends(require_partenaire),
):
    from app.models.hotel import Hotel
    from app.models.reservation import LigneReservationChambre, StatutReservation
    from app.models.utilisateur import Utilisateur as _Usr

    if not await _hotel_appartient_partenaire(hotel_id, token.user_id, session):
        raise HTTPException(status_code=403, detail="Cet hôtel ne vous appartient pas.")

    hotel_res = await session.execute(_sel(Hotel).where(Hotel.id == hotel_id))
    hotel     = hotel_res.scalar_one_or_none()
    hotel_nom = hotel.nom if hotel else f"Hôtel #{hotel_id}"

    chambre_ids = await _get_chambre_ids_hotel(hotel_id, session)

    items: List[PartenaireResaItem] = []

    if not chambre_ids:
        return PartenaireResaListResponse(
            hotel_id=hotel_id, hotel_nom=hotel_nom,
            total=0, nb_clients=0, nb_visiteurs=0, items=[],
        )

    # ── CLIENTS ───────────────────────────────────────────
    if source in (None, "client"):
        lrc_res = await session.execute(
            _sel(LigneReservationChambre)
            .where(LigneReservationChambre.id_chambre.in_(chambre_ids))
        )
        lignes   = lrc_res.scalars().all()
        resa_ids = list({l.id_reservation for l in lignes})

        if resa_ids:
            query = _sel(Reservation).where(Reservation.id.in_(resa_ids))
            if statut:
                try:
                    query = query.where(Reservation.statut == StatutReservation(statut))
                except ValueError:
                    pass
            query = query.order_by(Reservation.date_reservation.desc())
            resa_result = await session.execute(
                query.options(
                    _sil(Reservation.lignes_chambres),
                    _sil(Reservation.facture),
                )
            )
            resas = resa_result.scalars().all()

            for resa in resas:
                usr_res = await session.execute(_sel(_Usr).where(_Usr.id == resa.id_client))
                usr = usr_res.scalar_one_or_none()

                if search and usr:
                    s = search.lower()
                    haystack = (
                        f"{usr.nom} {usr.prenom} {usr.email} "
                        f"{getattr(usr, 'telephone', '') or ''}"
                    ).lower()
                    if s not in haystack:
                        continue
                elif search and not usr:
                    continue

                if numero_facture:
                    fac_num = resa.facture.numero if resa.facture else ""
                    if numero_facture.lower() not in (fac_num or "").lower():
                        continue

                lrc = next(
                    (l for l in lignes if l.id_reservation == resa.id),
                    resa.lignes_chambres[0] if resa.lignes_chambres else None,
                )
                ch_id  = lrc.id_chambre if lrc else None
                ch_nom = await _get_chambre_nom(ch_id, session) if ch_id else "—"

                items.append(PartenaireResaItem(
                    id               = resa.id,
                    source           = "client",
                    date_reservation = resa.date_reservation.strftime("%d/%m/%Y %H:%M"),
                    date_debut       = str(resa.date_debut),
                    date_fin         = str(resa.date_fin),
                    nb_nuits         = (resa.date_fin - resa.date_debut).days,
                    statut           = resa.statut.value,
                    total_ttc        = float(resa.total_ttc),
                    client_nom       = usr.nom       if usr else "—",
                    client_prenom    = usr.prenom    if usr else "—",
                    client_email     = usr.email     if usr else "—",
                    client_telephone = getattr(usr, "telephone", None),
                    chambre_nom      = ch_nom,
                    numero_facture   = resa.facture.numero       if resa.facture else None,
                    statut_facture   = resa.facture.statut.value if resa.facture else None,
                    numero_voucher   = None,
                    methode_paiement = None,
                    nb_adultes       = lrc.nb_adultes if lrc else 0,
                    nb_enfants       = lrc.nb_enfants if lrc else 0,
                ))

    nb_clients = len(items)

    # ── VISITEURS ─────────────────────────────────────────
    if source in (None, "visiteur"):
        vis_query = (
            _sel(_RV)
            .options(_sil(_RV.facture))
            .where(_RV.id_chambre.in_(chambre_ids))
        )
        if statut:
            vis_query = vis_query.where(_RV.statut == statut)
        vis_query = vis_query.order_by(_RV.created_at.desc())
        vis_result = await session.execute(vis_query)
        visiteurs  = vis_result.scalars().all()

        for vis in visiteurs:
            if search:
                s = search.lower()
                haystack = (
                    f"{vis.nom} {vis.prenom} {vis.email} {vis.telephone or ''}"
                ).lower()
                if s not in haystack:
                    continue

            if numero_facture:
                fac_num = vis.facture.numero if vis.facture else ""
                vch_num = vis.numero_voucher or ""
                if numero_facture.lower() not in fac_num.lower() and \
                   numero_facture.lower() not in vch_num.lower():
                    continue

            ch_nom = await _get_chambre_nom(vis.id_chambre, session)

            items.append(PartenaireResaItem(
                id               = vis.id,
                source           = "visiteur",
                date_reservation = vis.created_at.strftime("%d/%m/%Y %H:%M"),
                date_debut       = str(vis.date_debut),
                date_fin         = str(vis.date_fin),
                nb_nuits         = (vis.date_fin - vis.date_debut).days,
                statut           = vis.statut,
                total_ttc        = float(vis.total_ttc),
                client_nom       = vis.nom,
                client_prenom    = vis.prenom,
                client_email     = vis.email,
                client_telephone = vis.telephone,
                chambre_nom      = ch_nom,
                numero_facture   = vis.facture.numero         if vis.facture else None,
                statut_facture   = vis.facture.statut.value   if vis.facture else None,
                numero_voucher   = vis.numero_voucher,
                methode_paiement = vis.methode_paiement,
                nb_adultes       = vis.nb_adultes,
                nb_enfants       = vis.nb_enfants,
            ))

    nb_visiteurs = len(items) - nb_clients
    items.sort(key=lambda x: x.date_reservation, reverse=True)

    return PartenaireResaListResponse(
        hotel_id     = hotel_id,
        hotel_nom    = hotel_nom,
        total        = len(items),
        nb_clients   = nb_clients,
        nb_visiteurs = nb_visiteurs,
        items        = items,
    )


# ══════════════════════════════════════════════════════════
#  DÉTAIL
#  ⚠️  Route dynamique — DOIT rester après toutes les routes statiques
# ══════════════════════════════════════════════════════════
@router.get("/{reservation_id}", response_model=ReservationResponse,
            summary="Détail réservation [CLIENT|ADMIN]")
async def get_reservation(
    reservation_id: int,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(get_current_user),
) -> ReservationResponse:
    return await reservation_service.get_reservation(
        reservation_id, token.user_id, token.role, session
    )


# ══════════════════════════════════════════════════════════
#  PAYER
# ══════════════════════════════════════════════════════════
@router.post("/{reservation_id}/paiement", response_model=FactureResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Payer une réservation [CLIENT]")
async def payer_reservation(
    reservation_id: int,
    data: PaiementRequest,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_client),
) -> FactureResponse:
    return await reservation_service.payer_reservation(
        reservation_id, data, token.user_id, session
    )


# ══════════════════════════════════════════════════════════
#  ANNULER — CLIENT ou ADMIN (réservations clients)
# ══════════════════════════════════════════════════════════
@router.post("/{reservation_id}/annuler", response_model=ReservationResponse,
             summary="Annuler une réservation [CLIENT|ADMIN]")
async def annuler_reservation(
    reservation_id: int,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(get_current_user),
) -> ReservationResponse:
    return await reservation_service.annuler_reservation(
        reservation_id, token.user_id, token.role, session
    )


# ══════════════════════════════════════════════════════════
#  GÉNÉRATION PDF VOUCHER (fonction partagée)
# ══════════════════════════════════════════════════════════
def _generate_voucher_pdf(**kw) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        buf  = _io.BytesIO()
        doc  = SimpleDocTemplate(buf, pagesize=A4,
                                  leftMargin=2*cm, rightMargin=2*cm,
                                  topMargin=2*cm,  bottomMargin=2*cm)
        navy = colors.HexColor("#0F2235")
        gold = colors.HexColor("#C4973A")
        gray = colors.HexColor("#8A9BB0")
        story = []

        h_style = ParagraphStyle("h", fontSize=22, textColor=colors.white,
                                   fontName="Helvetica-Bold", alignment=1)
        s_style = ParagraphStyle("s", fontSize=11,
                                   textColor=colors.HexColor("#C4973A"),
                                   fontName="Helvetica", alignment=1)
        hdr = Table(
            [[Paragraph("EasyVoyage", h_style)],
             [Paragraph("Voucher de réservation", s_style)]],
            colWidths=[17*cm]
        )
        hdr.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), navy),
            ("TOPPADDING",    (0, 0), (-1, -1), 20),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
        ]))
        story.append(hdr)
        story.append(Spacer(1, 16))

        is_voyage  = kw.get("type_resa") == "voyage"
        type_label = "✈  VOYAGE" if is_voyage else "HOTEL"

        story.append(Paragraph(
            f'<font color="#C4973A"><b>{type_label}</b></font>',
            ParagraphStyle("tl", fontSize=14, fontName="Helvetica-Bold", spaceAfter=4)
        ))
        story.append(Paragraph(
            f'Voucher N° <b>{kw.get("numero", "—")}</b>',
            ParagraphStyle("num", fontSize=12, fontName="Helvetica-Bold",
                           textColor=navy, spaceAfter=10)
        ))
        story.append(HRFlowable(width="100%", thickness=1.5, color=gold, spaceAfter=14))

        ks = ParagraphStyle("k", fontSize=10, textColor=navy,
                             fontName="Helvetica-Bold", leftIndent=4)
        vs = ParagraphStyle("v", fontSize=10, fontName="Helvetica", leftIndent=4)

        def row(k, v):
            return [Paragraph(k, ks), Paragraph(str(v), vs)]

        rows = [
            row("Client",    kw.get("nom",    "—")),
            row("Email",     kw.get("email",  "—")),
            row("Téléphone", kw.get("telephone", "—")),
        ]

        if is_voyage:
            rows += [
                row("Voyage",         kw.get("voyage_titre", "—")),
                row("Destination",    kw.get("destination",  "—")),
                row("Date de départ", kw.get("date_debut",   "—")),
                row("Date de retour", kw.get("date_fin",     "—")),
                row("Durée",          f'{kw.get("duree", 0)} jour(s)'),
                row("Nb personnes",   str(kw.get("nb_personnes", 1))),
            ]
        else:
            rows += [
                row("Hôtel",   kw.get("hotel_nom",   "—")),
                row("Ville",   kw.get("hotel_ville", "—")),
                row("Chambre", kw.get("chambre_nom", "—")),
                row("Arrivée", kw.get("date_debut",  "—")),
                row("Départ",  kw.get("date_fin",    "—")),
                row("Durée",   f'{kw.get("nb_nuits", 0)} nuit(s)'),
                row("Adultes", str(kw.get("nb_adultes", 1))),
                row("Enfants", str(kw.get("nb_enfants", 0))),
            ]

        rows += [
            row("Méthode de paiement",
                kw.get("methode", "—").replace("_", " ").title()),
            row("Montant TTC", f'{kw.get("montant", 0):.2f} DT'),
        ]

        t = Table(rows, colWidths=[5.5*cm, 11.5*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (0, -1), colors.HexColor("#F4F7FB")),
            ("FONTSIZE",       (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1),
             [colors.white, colors.HexColor("#F9FAFC")]),
            ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#E4ECF5")),
            ("TOPPADDING",     (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
            ("TEXTCOLOR",      (0, -1), (-1, -1), gold),
            ("FONTNAME",       (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",       (1, -1), (1, -1),  14),
            ("BACKGROUND",     (0, -1), (-1, -1), colors.HexColor("#FFF8EC")),
        ]))
        story.append(t)
        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=0.8,
                                 color=colors.HexColor("#DDE3EC"), spaceAfter=10))

        note = ParagraphStyle("note", fontSize=9, textColor=gray,
                               fontName="Helvetica", spaceAfter=4)
        if is_voyage:
            story.append(Paragraph(
                "Présentez ce voucher à l'agence ou au guide lors du départ.", note))
        else:
            story.append(Paragraph(
                "Présentez ce voucher à la réception de l'hôtel lors de votre arrivée.", note))
        story.append(Paragraph(
            "EasyVoyage — www.easyvoyage.tn — contact@easyvoyage.tn", note))

        doc.build(story)
        return buf.getvalue()

    except ImportError:
        lines = [
            f"EasyVoyage - Voucher N: {kw.get('numero','?')}",
            f"Client: {kw.get('nom','?')}",
            f"Email: {kw.get('email','?')}",
        ]
        if kw.get("type_resa") == "voyage":
            lines += [
                f"Voyage: {kw.get('voyage_titre','?')}",
                f"Destination: {kw.get('destination','?')}",
                f"Depart: {kw.get('date_debut','?')}",
                f"Retour: {kw.get('date_fin','?')}",
                f"Personnes: {kw.get('nb_personnes',1)}",
            ]
        else:
            lines += [
                f"Hotel: {kw.get('hotel_nom','?')}",
                f"Chambre: {kw.get('chambre_nom','?')}",
                f"Arrivee: {kw.get('date_debut','?')}",
                f"Depart: {kw.get('date_fin','?')}",
                f"Nuits: {kw.get('nb_nuits',0)}",
            ]
        lines.append(f"Montant: {kw.get('montant',0):.2f} DT")
        return "\n".join(lines).encode("utf-8")


# ══════════════════════════════════════════════════════════
#  VOUCHER PDF — VISITEUR HÔTEL
# ══════════════════════════════════════════════════════════
@router.get("/visiteur/{voucher_num}/pdf", summary="Voucher PDF visiteur hôtel")
async def download_voucher_visiteur(
    voucher_num: str,
    session: AsyncSession = Depends(get_db),
):
    res  = await session.execute(_sel(_RV).where(_RV.numero_voucher == voucher_num))
    resa = res.scalar_one_or_none()
    if not resa:
        raise HTTPException(404, "Voucher introuvable")

    from app.models.hotel import Hotel as _H

    ch_res  = await session.execute(
        _sel(_Ch)
        .options(_sil(_Ch.type_chambre))
        .where(_Ch.id == resa.id_chambre)
    )
    chambre = ch_res.scalar_one_or_none()

    hotel = None
    if chambre:
        h_res = await session.execute(_sel(_H).where(_H.id == chambre.id_hotel))
        hotel = h_res.scalar_one_or_none()

    chambre_nom = "Chambre"
    if chambre and chambre.type_chambre:
        chambre_nom = chambre.type_chambre.nom

    pdf_bytes = _generate_voucher_pdf(
        type_resa   = "hotel",
        numero      = resa.numero_voucher,
        nom         = f"{resa.prenom} {resa.nom}",
        email       = resa.email,
        telephone   = resa.telephone,
        hotel_nom   = hotel.nom   if hotel else "—",
        hotel_ville = hotel.ville if hotel else "—",
        chambre_nom = chambre_nom,
        date_debut  = str(resa.date_debut),
        date_fin    = str(resa.date_fin),
        nb_adultes  = resa.nb_adultes,
        nb_enfants  = resa.nb_enfants,
        nb_nuits    = (resa.date_fin - resa.date_debut).days,
        montant     = float(resa.total_ttc),
        methode     = resa.methode_paiement,
    )
    return _SR(
        _io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="voucher-{voucher_num}.pdf"'},
    )


# ══════════════════════════════════════════════════════════
#  FACTURE PDF — VISITEUR HÔTEL [ADMIN]
# ══════════════════════════════════════════════════════════
@router.get("/visiteur/{voucher_num}/facture-pdf", summary="Facture PDF visiteur [ADMIN]")
async def download_facture_visiteur_admin(
    voucher_num: str,
    session: AsyncSession = Depends(get_db),
    _token: TokenData = Depends(require_admin),
):
    from app.models.hotel import Hotel as _H
    from app.utils.pdf_generator import generer_facture_pdf
    from datetime import datetime

    res  = await session.execute(
        _sel(_RV).options(_sil(_RV.facture)).where(_RV.numero_voucher == voucher_num)
    )
    resa = res.scalar_one_or_none()
    if not resa:
        raise HTTPException(404, "Voucher introuvable")

    ch_res = await session.execute(
        _sel(_Ch).options(_sil(_Ch.type_chambre)).where(_Ch.id == resa.id_chambre)
    )
    chambre = ch_res.scalar_one_or_none()

    hotel = None
    if chambre:
        h_res = await session.execute(_sel(_H).where(_H.id == chambre.id_hotel))
        hotel = h_res.scalar_one_or_none()

    chambre_nom  = chambre.type_chambre.nom if (chambre and chambre.type_chambre) else "Chambre"
    hotel_nom    = hotel.nom if hotel else "—"
    nb_nuits     = max((resa.date_fin - resa.date_debut).days, 1)
    total_ttc    = float(resa.total_ttc)
    prix_ht_nuit = round((total_ttc / 1.19) / nb_nuits, 3)

    num_doc       = resa.facture.numero if resa.facture else resa.numero_voucher
    date_emission = getattr(resa, "created_at", None) or datetime.now()

    prestations = [{
        "type":          "chambre",
        "description":   f"{chambre_nom} — {hotel_nom}",
        "nb_nuits":      nb_nuits,
        "prix_unitaire": prix_ht_nuit,
        "quantite":      nb_nuits,
    }]

    pdf_bytes = generer_facture_pdf(
        numero_facture   = num_doc,
        date_emission    = date_emission,
        statut_facture   = "PAYEE",
        client_nom       = resa.nom,
        client_prenom    = resa.prenom,
        client_email     = resa.email,
        client_telephone = getattr(resa, "telephone", None),
        date_debut       = resa.date_debut.strftime("%d/%m/%Y"),
        date_fin         = resa.date_fin.strftime("%d/%m/%Y"),
        nb_nuits         = nb_nuits,
        prestations      = prestations,
        total_ttc        = total_ttc,
    )

    filename = f"facture-{num_doc}.pdf"
    return _SR(
        _io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ══════════════════════════════════════════════════════════
#  ANNULER — RÉSERVATION VISITEUR [ADMIN]
# ══════════════════════════════════════════════════════════
@router.post(
    "/visiteur/{visiteur_id}/annuler",
    summary="Annuler une réservation visiteur [ADMIN]",
)
async def annuler_reservation_visiteur(
    visiteur_id: int,
    session: AsyncSession = Depends(get_db),
    _token: TokenData = Depends(require_admin),
):
    res  = await session.execute(
        _sel(_RV)
        .options(_sil(_RV.facture))
        .where(_RV.id == visiteur_id)
    )
    resa = res.scalar_one_or_none()
    if not resa:
        raise HTTPException(404, "Réservation visiteur introuvable")

    if resa.statut == "ANNULEE":
        raise HTTPException(409, "Cette réservation est déjà annulée")

    if resa.statut == "TERMINEE":
        raise HTTPException(409, "Impossible d'annuler une réservation terminée")

    resa.statut = "ANNULEE"

    if resa.facture:
        resa.facture.statut = StatutFacture.ANNULEE

    await session.commit()

    return {
        "message":        f"Réservation visiteur #{visiteur_id} annulée avec succès",
        "id":             visiteur_id,
        "statut":         "ANNULEE",
        "numero_facture": resa.facture.numero if resa.facture else None,
        "numero_voucher": resa.numero_voucher,
    }


# ══════════════════════════════════════════════════════════
#  VOUCHER PDF — CLIENT (hôtel ou voyage)
# ══════════════════════════════════════════════════════════
@router.get("/{reservation_id}/voucher-pdf", summary="Voucher PDF client")
async def download_voucher_client(
    reservation_id: int,
    session: AsyncSession = Depends(get_db),
    token=Depends(get_current_user),
):
    from app.models.hotel import Hotel as _H, Chambre as _Ch2
    from app.models.utilisateur import Utilisateur as _Usr

    resa_res = await session.execute(
        _sel(Reservation)
        .options(
            _sil(Reservation.lignes_chambres),
            _sil(Reservation.facture).selectinload(Facture.paiements),
        )
        .where(Reservation.id == reservation_id)
    )
    resa = resa_res.scalar_one_or_none()
    if not resa:
        raise HTTPException(404, "Réservation introuvable")
    if token.role == "CLIENT" and resa.id_client != token.user_id:
        raise HTTPException(403, "Accès refusé")

    usr_res = await session.execute(_sel(_Usr).where(_Usr.id == resa.id_client))
    usr = usr_res.scalar_one_or_none()
    nom_client  = f"{usr.prenom} {usr.nom}" if usr else "Client"
    email_cl    = usr.email                  if usr else "—"
    tel_cl      = getattr(usr, "telephone", "—") or "—"
    numero      = resa.facture.numero if resa.facture else f"RES-{resa.id}"
    methode_str = (
        resa.facture.paiements[0].methode.value
        if resa.facture and resa.facture.paiements else "—"
    )
    montant = float(resa.total_ttc)

    if resa.id_voyage:
        v_res  = await session.execute(_sel(_Voyage).where(_Voyage.id == resa.id_voyage))
        voyage = v_res.scalar_one_or_none()
        nb_personnes = 1
        if voyage and voyage.prix_base and float(voyage.prix_base) > 0:
            nb_personnes = max(1, round(montant / float(voyage.prix_base)))

        pdf_bytes = _generate_voucher_pdf(
            type_resa    = "voyage",
            numero       = numero,
            nom          = nom_client,
            email        = email_cl,
            telephone    = tel_cl,
            voyage_titre = voyage.titre       if voyage else "—",
            destination  = voyage.destination if voyage else "—",
            date_debut   = str(resa.date_debut),
            date_fin     = str(resa.date_fin),
            duree        = voyage.duree       if voyage else 0,
            nb_personnes = nb_personnes,
            montant      = montant,
            methode      = methode_str,
        )
    else:
        hotel_nom, hotel_ville, chambre_nom = "—", "—", "Chambre"
        nb_adultes, nb_enfants = 1, 0

        if resa.lignes_chambres:
            lc         = resa.lignes_chambres[0]
            nb_adultes = lc.nb_adultes
            nb_enfants = lc.nb_enfants

            ch_res = await session.execute(
                _sel(_Ch)
                .options(_sil(_Ch.type_chambre))
                .where(_Ch.id == lc.id_chambre)
            )
            ch = ch_res.scalar_one_or_none()
            if ch:
                chambre_nom = ch.type_chambre.nom if ch.type_chambre else "Chambre"
                from app.models.hotel import Hotel as _H2
                h_res = await session.execute(_sel(_H2).where(_H2.id == ch.id_hotel))
                h = h_res.scalar_one_or_none()
                if h:
                    hotel_nom, hotel_ville = h.nom, h.ville

        pdf_bytes = _generate_voucher_pdf(
            type_resa   = "hotel",
            numero      = numero,
            nom         = nom_client,
            email       = email_cl,
            telephone   = tel_cl,
            hotel_nom   = hotel_nom,
            hotel_ville = hotel_ville,
            chambre_nom = chambre_nom,
            date_debut  = str(resa.date_debut),
            date_fin    = str(resa.date_fin),
            nb_nuits    = (resa.date_fin - resa.date_debut).days,
            nb_adultes  = nb_adultes,
            nb_enfants  = nb_enfants,
            montant     = montant,
            methode     = methode_str,
        )

    return _SR(
        _io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="voucher-{reservation_id}.pdf"'
        },
    )