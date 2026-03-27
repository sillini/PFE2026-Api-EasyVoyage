"""
app/api/v1/endpoints/reservations.py
=====================================
Endpoints Réservations — version corrigée complète.

Corrections appliquées :
  - reserver_visiteur      : selectinload(type_chambre) sur chambre
  - download_voucher_visiteur : selectinload(type_chambre) sur chambre
  - download_voucher_client   : selectinload(facture → paiements) + selectinload(type_chambre)

Routes :
  POST  /reservations/voyage              → Réserver voyage [CLIENT]
  POST  /reservations/chambres            → Réserver chambre hôtel [CLIENT]
  POST  /reservations/visiteur            → Réservation hôtel visiteur sans compte
  GET   /reservations/mes-reservations    → Mes réservations [CLIENT]
  GET   /reservations                     → Toutes [ADMIN]
  GET   /reservations/{id}               → Détail [CLIENT|ADMIN]
  POST  /reservations/{id}/paiement      → Payer [CLIENT]
  POST  /reservations/{id}/annuler       → Annuler [CLIENT|ADMIN]
  GET   /reservations/visiteur/{v}/pdf   → Voucher PDF visiteur hôtel
  GET   /reservations/{id}/voucher-pdf   → Voucher PDF client (hôtel ou voyage)
"""
from typing import Optional
import uuid as _uuid
import io as _io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse as _SR
from pydantic import BaseModel as _BM
from sqlalchemy import select as _sel, func as _func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload as _sil

from app.api.v1.dependencies import get_current_user, require_admin, require_client
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.reservation import (
    FactureResponse, PaiementRequest,
    ReservationChambresCreate, ReservationListResponse,
    ReservationResponse, ReservationVoyageCreate,
)
from app.models.reservation import (
    Reservation, Facture,
    ReservationVisiteur as _RV,
)
from app.models.hotel import Chambre as _Ch, Tarif as _T
from app.models.voyage import Voyage as _Voyage
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


@router.post("/visiteur", response_model=VisiteurReservationResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Réservation hôtel visiteur sans compte")
async def reserver_visiteur(
    data: VisiteurReservationRequest,
    session: AsyncSession = Depends(get_db),
):
    from datetime import date as _date

    d1 = _date.fromisoformat(data.date_debut)
    d2 = _date.fromisoformat(data.date_fin)
    if d2 <= d1:
        raise HTTPException(422, "date_fin doit être après date_debut")

    nb_nuits = (d2 - d1).days

    # ── CORRECTION : charger type_chambre avec selectinload ──────────
    # Sans ça → MissingGreenlet sur chambre.type_chambre → 500
    ch_res = await session.execute(
        _sel(_Ch)
        .options(_sil(_Ch.type_chambre))          # ← OBLIGATOIRE
        .where(_Ch.id == data.id_chambre, _Ch.actif == True)
    )
    chambre = ch_res.scalar_one_or_none()
    if not chambre:
        raise HTTPException(404, "Chambre introuvable ou inactive")

    # Récupérer tarif valide
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

    total_ttc = float(tarif.prix) * nb_nuits

    # Générer numéro voucher unique
    annee = d1.year
    cnt_r = await session.execute(_sel(_func.count(_RV.id)))
    cnt   = cnt_r.scalar_one() + 1
    numero_voucher = f"VIS-{annee}-{cnt:05d}-{_uuid.uuid4().hex[:4].upper()}"

    resa = _RV(
        nom=data.nom, prenom=data.prenom,
        email=data.email, telephone=data.telephone,
        id_chambre=data.id_chambre,
        date_debut=d1, date_fin=d2,
        nb_adultes=data.nb_adultes, nb_enfants=data.nb_enfants,
        total_ttc=total_ttc,
        methode_paiement=data.methode,
        transaction_id="T-" + _uuid.uuid4().hex[:8].upper(),
        statut="CONFIRMEE",
        numero_voucher=numero_voucher,
    )
    session.add(resa)
    await session.commit()
    await session.refresh(resa)

    # Récupérer hôtel
    from app.models.hotel import Hotel as _H
    h_res = await session.execute(_sel(_H).where(_H.id == chambre.id_hotel))
    hotel = h_res.scalar_one_or_none()

    # type_chambre déjà chargé → pas de lazy load
    chambre_nom = chambre.type_chambre.nom if chambre.type_chambre else "Chambre"

    return VisiteurReservationResponse(
        id=resa.id,
        numero_voucher=resa.numero_voucher,
        montant_total=float(resa.total_ttc),
        statut=resa.statut,
        email=resa.email, nom=resa.nom, prenom=resa.prenom,
        date_debut=str(resa.date_debut), date_fin=str(resa.date_fin),
        hotel_nom=hotel.nom if hotel else "Hôtel",
        chambre_nom=chambre_nom,
        nb_adultes=resa.nb_adultes, nb_enfants=resa.nb_enfants,
        nb_nuits=nb_nuits,
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
#  ADMIN — TOUTES
# ══════════════════════════════════════════════════════════
@router.get("", response_model=ReservationListResponse,
            summary="Toutes les réservations [ADMIN]")
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
#  DÉTAIL
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
#  ANNULER
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
    """
    Génère un PDF voucher avec reportlab.
    Fonctionne pour hôtel (type_resa='hotel') et voyage (type_resa='voyage').
    Fallback texte brut si reportlab absent.
    """
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

        # En-tête
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

        is_voyage = kw.get("type_resa") == "voyage"
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
        # Fallback texte si reportlab non installé
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
    # Charger la réservation visiteur
    res  = await session.execute(_sel(_RV).where(_RV.numero_voucher == voucher_num))
    resa = res.scalar_one_or_none()
    if not resa:
        raise HTTPException(404, "Voucher introuvable")

    from app.models.hotel import Hotel as _H

    # ── CORRECTION : charger chambre AVEC type_chambre ───────────────
    # Sans _sil(_Ch.type_chambre) → MissingGreenlet → 500 → "Failed to fetch"
    ch_res  = await session.execute(
        _sel(_Ch)
        .options(_sil(_Ch.type_chambre))          # ← OBLIGATOIRE
        .where(_Ch.id == resa.id_chambre)
    )
    chambre = ch_res.scalar_one_or_none()

    hotel = None
    if chambre:
        h_res = await session.execute(_sel(_H).where(_H.id == chambre.id_hotel))
        hotel = h_res.scalar_one_or_none()

    # type_chambre maintenant chargé → accès direct sans lazy load
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
#  VOUCHER PDF — CLIENT (hôtel ou voyage automatique)
# ══════════════════════════════════════════════════════════
@router.get("/{reservation_id}/voucher-pdf", summary="Voucher PDF client")
async def download_voucher_client(
    reservation_id: int,
    session: AsyncSession = Depends(get_db),
    token=Depends(get_current_user),
):
    from app.models.hotel import Hotel as _H, Chambre as _Ch2
    from app.models.utilisateur import Utilisateur as _Usr

    # ── CORRECTION : charger facture → paiements en une seule requête
    # Sans selectinload(Facture.paiements) → MissingGreenlet sur paiements[0]
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

    # Infos client
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

    # ── CAS VOYAGE ────────────────────────────────────────────────────
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

    # ── CAS HÔTEL ─────────────────────────────────────────────────────
    else:
        hotel_nom, hotel_ville, chambre_nom = "—", "—", "Chambre"
        nb_adultes, nb_enfants = 1, 0

        if resa.lignes_chambres:
            lc         = resa.lignes_chambres[0]
            nb_adultes = lc.nb_adultes
            nb_enfants = lc.nb_enfants

            # ── CORRECTION : charger type_chambre avec selectinload ──
            ch_res = await session.execute(
                _sel(_Ch2)
                .options(_sil(_Ch2.type_chambre))  # ← OBLIGATOIRE
                .where(_Ch2.id == lc.id_chambre)
            )
            ch = ch_res.scalar_one_or_none()
            if ch:
                chambre_nom = ch.type_chambre.nom if ch.type_chambre else "Chambre"
                h_res = await session.execute(_sel(_H).where(_H.id == ch.id_hotel))
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