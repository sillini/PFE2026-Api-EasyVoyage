"""
app/services/factures_admin_service.py
========================================
Service — Page Admin Factures.

Fonctions principales :
  - get_kpis()           → FacturesKpis
  - list_factures_admin() → FacturesAdminListResponse (clients + visiteurs + partenaires)
  - get_facture_detail()  → FactureAdminDetail
  - get_pdf_bytes()       → bytes  (PDF téléchargeable)

Architecture :
  Les trois types de factures sont récupérés séparément puis fusionnés/triés.
  Le filtre `type` permet de n'afficher qu'une seule catégorie (utile pour les onglets).
"""
from datetime import datetime, date
from typing import Optional, Literal, List
from sqlalchemy import select, func, and_, or_, cast, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.reservation import (
    Facture, StatutFacture,
    Reservation, ReservationVisiteur,
    LigneReservationChambre,
)
from app.models.finances import PaiementPartenaire
from app.models.utilisateur import Utilisateur, Partenaire
from app.models.hotel import Chambre, Hotel
from app.models.voyage import Voyage
from app.core.exceptions import NotFoundException
from app.schemas.factures_admin import (
    FacturesKpis,
    FactureAdminItem,
    FactureAdminDetail,
    FacturesAdminListResponse,
    LigneFactureDetail,
)


# ═══════════════════════════════════════════════════════════
#  HELPERS INTERNES
# ═══════════════════════════════════════════════════════════

async def _get_hotel_nom(id_chambre: int, session: AsyncSession) -> str:
    """Retourne le nom de l'hôtel d'une chambre."""
    result = await session.execute(
        select(Hotel.nom)
        .join(Chambre, Chambre.id_hotel == Hotel.id)
        .where(Chambre.id == id_chambre)
    )
    return result.scalar_one_or_none() or "—"


async def _get_contexte_reservation(resa: Reservation, session: AsyncSession) -> str:
    """Retourne le contexte d'une réservation client (hôtel ou voyage)."""
    if resa.id_voyage:
        r = await session.execute(
            select(Voyage.titre).where(Voyage.id == resa.id_voyage)
        )
        titre = r.scalar_one_or_none() or "Voyage"
        return f"Voyage — {titre}"

    # Réservation chambre → récupérer le nom de l'hôtel via la première ligne
    r = await session.execute(
        select(LigneReservationChambre)
        .where(LigneReservationChambre.id_reservation == resa.id)
        .limit(1)
    )
    ligne = r.scalar_one_or_none()
    if ligne:
        return await _get_hotel_nom(ligne.id_chambre, session)
    return "—"


def _match_search(search: str, *fields: Optional[str]) -> bool:
    """Vérifie si le terme de recherche est présent dans l'un des champs."""
    s = search.lower().strip()
    return any(s in (f or "").lower() for f in fields)


# ═══════════════════════════════════════════════════════════
#  KPIs GLOBAUX
# ═══════════════════════════════════════════════════════════

async def get_kpis(session: AsyncSession) -> FacturesKpis:
    """
    Calcule les KPIs globaux de la page Factures :
      - Totaux par type (clients / visiteurs / partenaires)
      - Compteurs par statut
    """

    # ── 1. Factures clients ───────────────────────────────
    r_clients = await session.execute(
        select(Facture.statut, func.count(Facture.id), func.sum(Facture.montant_total))
        .where(Facture.id_reservation.isnot(None))
        .group_by(Facture.statut)
    )
    clients_stats: dict[str, dict] = {}
    for statut, count, total in r_clients.all():
        clients_stats[str(statut.value if hasattr(statut, "value") else statut)] = {
            "count": count or 0,
            "total": float(total or 0),
        }

    # ── 2. Factures visiteurs ─────────────────────────────
    # Factures liées à reservation_visiteur (id_reservation IS NULL et id_facture sur rv)
    r_visiteurs = await session.execute(
        select(Facture.statut, func.count(Facture.id), func.sum(Facture.montant_total))
        .join(ReservationVisiteur, ReservationVisiteur.id_facture == Facture.id)
        .group_by(Facture.statut)
    )
    visiteurs_stats: dict[str, dict] = {}
    for statut, count, total in r_visiteurs.all():
        visiteurs_stats[str(statut.value if hasattr(statut, "value") else statut)] = {
            "count": count or 0,
            "total": float(total or 0),
        }

    # ── 3. Paiements partenaires ──────────────────────────
    r_part = await session.execute(
        select(func.count(PaiementPartenaire.id), func.sum(PaiementPartenaire.montant))
    )
    nb_part, total_part = r_part.one()
    nb_part    = nb_part or 0
    total_part = float(total_part or 0)

    # ── Extraction des valeurs ────────────────────────────
    def _c(stats: dict, statut: str, key: str):
        return stats.get(statut, {}).get(key, 0)

    total_clients   = _c(clients_stats,   "PAYEE", "total")
    total_visiteurs = _c(visiteurs_stats, "PAYEE", "total")

    return FacturesKpis(
        total_facture_clients       = total_clients,
        total_facture_visiteurs     = total_visiteurs,
        total_paiements_partenaires = total_part,

        nb_clients_payee    = _c(clients_stats, "PAYEE",     "count"),
        nb_clients_emise    = _c(clients_stats, "EMISE",     "count"),
        nb_clients_retard   = _c(clients_stats, "EN_RETARD", "count"),
        nb_clients_annulee  = _c(clients_stats, "ANNULEE",   "count"),

        nb_visiteurs_payee   = _c(visiteurs_stats, "PAYEE",   "count"),
        nb_visiteurs_annulee = _c(visiteurs_stats, "ANNULEE", "count"),

        nb_paiements_partenaires = nb_part,

        total_global_facture = total_clients + total_visiteurs,
        nb_total_payees      = _c(clients_stats, "PAYEE", "count") + _c(visiteurs_stats, "PAYEE", "count"),
        nb_total_emises      = _c(clients_stats, "EMISE", "count"),
        nb_total_retard      = _c(clients_stats, "EN_RETARD", "count"),
    )


# ═══════════════════════════════════════════════════════════
#  RÉCUPÉRATION PAR TYPE
# ═══════════════════════════════════════════════════════════

async def _fetch_factures_clients(
    session:    AsyncSession,
    search:     Optional[str],
    statut:     Optional[str],
    date_debut: Optional[date],
    date_fin:   Optional[date],
) -> List[FactureAdminItem]:
    """Charge les factures liées aux réservations clients."""

    query = (
        select(Facture, Reservation, Utilisateur)
        .join(Reservation, Facture.id_reservation == Reservation.id)
        .join(Utilisateur, Utilisateur.id == Reservation.id_client)
        .where(Facture.id_reservation.isnot(None))
        .options(selectinload(Facture.paiements))
        .order_by(Facture.date_emission.desc())
    )

    # Filtre statut
    if statut:
        query = query.where(Facture.statut == StatutFacture(statut))

    # Filtre dates
    if date_debut:
        query = query.where(func.date(Facture.date_emission) >= date_debut)
    if date_fin:
        query = query.where(func.date(Facture.date_emission) <= date_fin)

    result = await session.execute(query)
    rows   = result.all()

    items: List[FactureAdminItem] = []
    for facture, resa, user in rows:
        nom    = f"{user.prenom or ''} {user.nom or ''}".strip() or user.email
        email  = user.email or "—"
        tel    = getattr(user, "telephone", None)

        # Contexte : hôtel ou voyage
        contexte = await _get_contexte_reservation(resa, session)

        # Filtre search (appliqué côté Python pour simplicité)
        if search and not _match_search(search, nom, email, facture.numero, contexte):
            continue

        items.append(FactureAdminItem(
            id             = facture.id,
            type           = "client",
            numero         = facture.numero,
            date_emission  = facture.date_emission,
            personne_nom   = nom,
            personne_email = email,
            personne_tel   = tel,
            contexte       = contexte,
            montant_total  = float(facture.montant_total),
            statut         = facture.statut.value if hasattr(facture.statut, "value") else str(facture.statut),
            has_pdf        = True,   # les factures clients ont toujours un PDF générable
        ))

    return items


async def _fetch_factures_visiteurs(
    session:    AsyncSession,
    search:     Optional[str],
    statut:     Optional[str],
    date_debut: Optional[date],
    date_fin:   Optional[date],
) -> List[FactureAdminItem]:
    """Charge les factures liées aux réservations visiteurs."""

    query = (
        select(Facture, ReservationVisiteur)
        .join(ReservationVisiteur, ReservationVisiteur.id_facture == Facture.id)
        .order_by(Facture.date_emission.desc())
    )

    if statut:
        query = query.where(Facture.statut == StatutFacture(statut))

    if date_debut:
        query = query.where(func.date(Facture.date_emission) >= date_debut)
    if date_fin:
        query = query.where(func.date(Facture.date_emission) <= date_fin)

    result = await session.execute(query)
    rows   = result.all()

    items: List[FactureAdminItem] = []
    for facture, rv in rows:
        nom   = f"{rv.prenom or ''} {rv.nom or ''}".strip() or rv.email
        email = rv.email or "—"
        tel   = rv.telephone

        contexte = await _get_hotel_nom(rv.id_chambre, session)

        if search and not _match_search(
            search, nom, email, facture.numero, rv.numero_voucher, contexte
        ):
            continue

        items.append(FactureAdminItem(
            id                = facture.id,
            type              = "visiteur",
            numero            = facture.numero,
            date_emission     = facture.date_emission,
            personne_nom      = nom,
            personne_email    = email,
            personne_tel      = tel,
            contexte          = contexte,
            montant_total     = float(facture.montant_total),
            statut            = facture.statut.value if hasattr(facture.statut, "value") else str(facture.statut),
            methode_paiement  = rv.methode_paiement,
            has_pdf           = True,
        ))

    return items


async def _fetch_paiements_partenaires(
    session:    AsyncSession,
    search:     Optional[str],
    date_debut: Optional[date],
    date_fin:   Optional[date],
) -> List[FactureAdminItem]:
    """Charge les paiements versés aux partenaires."""

    query = (
        select(PaiementPartenaire, Utilisateur, Partenaire)
        .join(Utilisateur,  Utilisateur.id == PaiementPartenaire.id_partenaire)
        .join(Partenaire,   Partenaire.id  == Utilisateur.id, isouter=True)
        .order_by(PaiementPartenaire.created_at.desc())
    )

    if date_debut:
        query = query.where(func.date(PaiementPartenaire.created_at) >= date_debut)
    if date_fin:
        query = query.where(func.date(PaiementPartenaire.created_at) <= date_fin)

    result = await session.execute(query)
    rows   = result.all()

    items: List[FactureAdminItem] = []
    for pp, user, part in rows:
        nom       = f"{user.prenom or ''} {user.nom or ''}".strip() or user.email
        email     = user.email or "—"
        tel       = getattr(user, "telephone", None)
        entreprise = getattr(part, "nom_entreprise", None) if part else None
        numero    = pp.numero_facture or f"PP-{pp.id}"

        if search and not _match_search(search, nom, email, numero, entreprise):
            continue

        items.append(FactureAdminItem(
            id             = pp.id,
            type           = "partenaire",
            numero         = numero,
            date_emission  = pp.created_at,
            personne_nom   = nom,
            personne_email = email,
            personne_tel   = tel,
            contexte       = entreprise,
            montant_total  = float(pp.montant),
            statut         = "PAYEE",  # les paiements partenaires sont toujours payés
            has_pdf        = bool(pp.pdf_data),
            note           = pp.note or None,
        ))

    return items


# ═══════════════════════════════════════════════════════════
#  LISTE UNIFIÉE PAGINÉE
# ═══════════════════════════════════════════════════════════

async def list_factures_admin(
    session:    AsyncSession,
    type_:      Optional[Literal["client", "visiteur", "partenaire"]] = None,
    statut:     Optional[str]  = None,
    search:     Optional[str]  = None,
    date_debut: Optional[date] = None,
    date_fin:   Optional[date] = None,
    page:       int            = 1,
    per_page:   int            = 20,
) -> FacturesAdminListResponse:
    """
    Retourne la liste unifiée paginée des factures.
    Si `type_` est fourni, seule la catégorie concernée est chargée.
    """
    all_items: List[FactureAdminItem] = []

    # Charger selon le filtre de type
    if type_ in (None, "client"):
        all_items += await _fetch_factures_clients(
            session, search, statut, date_debut, date_fin
        )

    if type_ in (None, "visiteur"):
        # Les visiteurs n'ont que PAYEE et ANNULEE
        statut_vis = statut if statut in (None, "PAYEE", "ANNULEE") else None
        all_items += await _fetch_factures_visiteurs(
            session, search, statut_vis, date_debut, date_fin
        )

    if type_ in (None, "partenaire"):
        # Les paiements partenaires sont toujours inclus (pas de filtre statut applicable)
        all_items += await _fetch_paiements_partenaires(
            session, search, date_debut, date_fin
        )

    # Tri global par date décroissante
    all_items.sort(key=lambda x: x.date_emission, reverse=True)

    total  = len(all_items)
    offset = (page - 1) * per_page
    page_items = all_items[offset : offset + per_page]

    return FacturesAdminListResponse(
        total    = total,
        page     = page,
        per_page = per_page,
        items    = page_items,
    )


# ═══════════════════════════════════════════════════════════
#  DÉTAIL D'UNE FACTURE
# ═══════════════════════════════════════════════════════════

async def get_facture_detail(
    facture_id: int,
    type_:      Literal["client", "visiteur", "partenaire"],
    session:    AsyncSession,
) -> FactureAdminDetail:
    """
    Retourne le détail enrichi d'une facture selon son type.
    `facture_id` est l'ID de la Facture (client/visiteur) ou du PaiementPartenaire.
    """

    if type_ == "client":
        return await _detail_client(facture_id, session)
    elif type_ == "visiteur":
        return await _detail_visiteur(facture_id, session)
    elif type_ == "partenaire":
        return await _detail_partenaire(facture_id, session)

    raise NotFoundException(f"Type de facture inconnu : {type_}")


async def _detail_client(facture_id: int, session: AsyncSession) -> FactureAdminDetail:
    result = await session.execute(
        select(Facture)
        .options(
            selectinload(Facture.reservation)
            .selectinload(Reservation.lignes_chambres),
            selectinload(Facture.paiements),
        )
        .where(Facture.id == facture_id, Facture.id_reservation.isnot(None))
    )
    facture = result.scalar_one_or_none()
    if not facture:
        raise NotFoundException(f"Facture client {facture_id} introuvable")

    resa = facture.reservation

    # Infos client
    r_user = await session.execute(
        select(Utilisateur).where(Utilisateur.id == resa.id_client)
    )
    user = r_user.scalar_one_or_none()
    nom   = f"{user.prenom or ''} {user.nom or ''}".strip() if user else "—"
    email = user.email if user else "—"
    tel   = getattr(user, "telephone", None) if user else None

    # Lignes de détail
    lignes: List[LigneFactureDetail] = []

    if resa.id_voyage:
        # Voyage
        r_v = await session.execute(select(Voyage).where(Voyage.id == resa.id_voyage))
        voyage = r_v.scalar_one_or_none()
        titre  = voyage.titre if voyage else "Voyage"
        lignes.append(LigneFactureDetail(
            description   = f"Voyage — {titre}",
            date_debut    = str(resa.date_debut),
            date_fin      = str(resa.date_fin),
            prix_unitaire = float(voyage.prix_base) if voyage else float(resa.total_ttc),
            quantite      = resa.nb_adultes + resa.nb_enfants,
            sous_total    = float(resa.total_ttc),
        ))
    else:
        # Chambres
        for ligne in resa.lignes_chambres:
            nb_nuits = (resa.date_fin - resa.date_debut).days
            hotel_nom = await _get_hotel_nom(ligne.id_chambre, session)
            r_ch = await session.execute(
                select(Chambre).where(Chambre.id == ligne.id_chambre)
            )
            chambre = r_ch.scalar_one_or_none()
            ch_nom = chambre.type_chambre.nom if chambre and chambre.type_chambre else f"Chambre #{ligne.id_chambre}"
            prix_u  = float(resa.total_ttc) / nb_nuits if nb_nuits > 0 else 0

            lignes.append(LigneFactureDetail(
                description   = f"{hotel_nom} — {ch_nom}",
                date_debut    = str(resa.date_debut),
                date_fin      = str(resa.date_fin),
                nb_nuits      = nb_nuits,
                prix_unitaire = round(prix_u, 2),
                quantite      = nb_nuits,
                sous_total    = float(resa.total_ttc),
            ))

    statut_str = facture.statut.value if hasattr(facture.statut, "value") else str(facture.statut)

    return FactureAdminDetail(
        id             = facture.id,
        type           = "client",
        numero         = facture.numero,
        date_emission  = facture.date_emission,
        montant_total  = float(facture.montant_total),
        statut         = statut_str,
        has_pdf        = True,
        personne_nom   = nom,
        personne_email = email,
        personne_tel   = tel,
        lignes         = lignes,
        reservation_id = resa.id,
    )


async def _detail_visiteur(facture_id: int, session: AsyncSession) -> FactureAdminDetail:
    result = await session.execute(
        select(Facture, ReservationVisiteur)
        .join(ReservationVisiteur, ReservationVisiteur.id_facture == Facture.id)
        .where(Facture.id == facture_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundException(f"Facture visiteur {facture_id} introuvable")

    facture, rv = row

    hotel_nom = await _get_hotel_nom(rv.id_chambre, session)
    nb_nuits  = (rv.date_fin - rv.date_debut).days

    lignes = [LigneFactureDetail(
        description   = f"{hotel_nom} — Chambre #{rv.id_chambre}",
        date_debut    = str(rv.date_debut),
        date_fin      = str(rv.date_fin),
        nb_nuits      = nb_nuits,
        prix_unitaire = round(float(rv.total_ttc) / nb_nuits, 2) if nb_nuits > 0 else 0,
        quantite      = nb_nuits,
        sous_total    = float(rv.total_ttc),
    )]

    nom   = f"{rv.prenom or ''} {rv.nom or ''}".strip() or rv.email
    statut_str = facture.statut.value if hasattr(facture.statut, "value") else str(facture.statut)

    return FactureAdminDetail(
        id               = facture.id,
        type             = "visiteur",
        numero           = facture.numero,
        date_emission    = facture.date_emission,
        montant_total    = float(facture.montant_total),
        statut           = statut_str,
        has_pdf          = True,
        personne_nom     = nom,
        personne_email   = rv.email,
        personne_tel     = rv.telephone,
        lignes           = lignes,
        reservation_id   = rv.id,
        numero_voucher   = rv.numero_voucher,
        methode_paiement = rv.methode_paiement,
    )


async def _detail_partenaire(pp_id: int, session: AsyncSession) -> FactureAdminDetail:
    result = await session.execute(
        select(PaiementPartenaire, Utilisateur, Partenaire)
        .join(Utilisateur, Utilisateur.id == PaiementPartenaire.id_partenaire)
        .join(Partenaire,  Partenaire.id == Utilisateur.id, isouter=True)
        .where(PaiementPartenaire.id == pp_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundException(f"Paiement partenaire {pp_id} introuvable")

    pp, user, part = row
    nom        = f"{user.prenom or ''} {user.nom or ''}".strip() or user.email
    entreprise = getattr(part, "nom_entreprise", None) if part else None
    numero     = pp.numero_facture or f"PP-{pp.id}"

    lignes = [LigneFactureDetail(
        description = "Paiement commission partenaire",
        sous_total  = float(pp.montant),
    )]

    return FactureAdminDetail(
        id                     = pp.id,
        type                   = "partenaire",
        numero                 = numero,
        date_emission          = pp.created_at,
        montant_total          = float(pp.montant),
        statut                 = None,
        has_pdf                = bool(pp.pdf_data),
        note                   = pp.note or None,
        personne_nom           = nom,
        personne_email         = user.email or "—",
        personne_tel           = getattr(user, "telephone", None),
        lignes                 = lignes,
        partenaire_entreprise  = entreprise,
        partenaire_id          = pp.id_partenaire,
    )


# ═══════════════════════════════════════════════════════════
#  PDF ADMIN (téléchargement)
# ═══════════════════════════════════════════════════════════

async def get_pdf_bytes(
    facture_id: int,
    type_:      Literal["client", "visiteur", "partenaire"],
    session:    AsyncSession,
) -> tuple[bytes, str]:
    """
    Retourne (pdf_bytes, filename).
    Pour les clients/visiteurs on délègue au service existant.
    Pour les partenaires on lit directement le pdf_data stocké en base.
    """

    if type_ == "partenaire":
        r = await session.execute(
            select(PaiementPartenaire).where(PaiementPartenaire.id == facture_id)
        )
        pp = r.scalar_one_or_none()
        if not pp or not pp.pdf_data:
            raise NotFoundException("PDF partenaire introuvable")
        numero   = pp.numero_facture or f"PP-{pp.id}"
        filename = f"facture_{numero}.pdf"
        return pp.pdf_data, filename

    # Clients & visiteurs : déléguer au service existant
    import app.services.facture_service as facture_svc

    if type_ == "client":
        r = await session.execute(
            select(Facture).where(Facture.id == facture_id)
        )
        facture = r.scalar_one_or_none()
        if not facture:
            raise NotFoundException(f"Facture {facture_id} introuvable")
        pdf_bytes = await facture_svc.generer_pdf(
            facture_id, client_id=0, role="ADMIN", session=session
        )
        filename = f"facture_{facture.numero}.pdf"
        return pdf_bytes, filename

    if type_ == "visiteur":
        from app.utils.pdf_generator import generer_facture_pdf
        from app.models.hotel import Chambre, Hotel
        from datetime import datetime

        r = await session.execute(
            select(ReservationVisiteur)
            .options(selectinload(ReservationVisiteur.facture))
            .where(ReservationVisiteur.id_facture == facture_id)
        )
        rv = r.scalar_one_or_none()
        if not rv:
            raise NotFoundException("Réservation visiteur introuvable pour cette facture")

        ch_res = await session.execute(
            select(Chambre)
            .options(selectinload(Chambre.type_chambre))
            .where(Chambre.id == rv.id_chambre)
        )
        chambre = ch_res.scalar_one_or_none()

        hotel = None
        if chambre:
            h_res = await session.execute(select(Hotel).where(Hotel.id == chambre.id_hotel))
            hotel = h_res.scalar_one_or_none()

        chambre_nom  = (chambre.type_chambre.nom if chambre and chambre.type_chambre else f"Chambre #{rv.id_chambre}")
        hotel_nom    = hotel.nom if hotel else "—"
        nb_nuits     = max((rv.date_fin - rv.date_debut).days, 1)
        total_ttc    = float(rv.total_ttc)
        prix_ht_nuit = round((total_ttc / 1.19) / nb_nuits, 3)
        num_doc      = rv.facture.numero if rv.facture else rv.numero_voucher
        date_emission = getattr(rv, "created_at", None) or datetime.now()

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
            client_nom       = rv.nom,
            client_prenom    = rv.prenom,
            client_email     = rv.email,
            client_telephone = rv.telephone,
            date_debut       = rv.date_debut.strftime("%d/%m/%Y"),
            date_fin         = rv.date_fin.strftime("%d/%m/%Y"),
            nb_nuits         = nb_nuits,
            prestations      = prestations,
            total_ttc        = total_ttc,
        )
        filename = f"facture_{num_doc}.pdf"
        return pdf_bytes, filename

    raise NotFoundException(f"Type inconnu : {type_}")