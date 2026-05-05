"""
app/services/promotion_service.py
==================================
Service pour la gestion des promotions avec workflow de validation admin.

Workflow :
  1. Partenaire crée → statut PENDING
                     → notification ADMIN "Nouvelle promotion à valider"
  2. Admin approuve  → statut APPROVED
                     → email partenaire
                     → ✨ notification PARTENAIRE "Promotion approuvée"
  3. Admin refuse    → statut REJECTED + raison
                     → email partenaire
                     → ✨ notification PARTENAIRE "Promotion refusée"
  4. Côté visiteur   → seules les promos APPROVED + actif + dans dates sont visibles
"""
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.models.hotel import Hotel
from app.models.promotion import Promotion, StatutPromotion
from app.models.utilisateur import Utilisateur
from app.schemas.promotion import (
    DecisionAdmin,
    HotelMini,
    PromotionCreate,
    PromotionListResponse,
    PromotionResponse,
    PromotionUpdate,
    UserMini,
)
# ✅ Helpers de notification centralisés
from app.services.notification_helper import (
    notify_all_admins,
    notify_partenaire,   # ← AJOUT
    NotifType,
)

# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def _to_response(promo: Promotion) -> PromotionResponse:
    today = date.today()
    est_valide = (
        promo.statut == StatutPromotion.APPROVED
        and promo.actif
        and promo.date_debut <= today <= promo.date_fin
    )
    jours_restants = (promo.date_fin - today).days if est_valide else None

    hotel_mini = None
    if promo.hotel:
        hotel_mini = HotelMini(
            id=promo.hotel.id,
            nom=promo.hotel.nom,
            ville=getattr(promo.hotel, "ville", None),
        )

    partenaire_mini = None
    if promo.partenaire:
        partenaire_mini = UserMini(
            id=promo.partenaire.id,
            nom=promo.partenaire.nom,
            prenom=promo.partenaire.prenom,
            email=promo.partenaire.email,
        )

    validateur_mini = None
    if promo.validateur:
        validateur_mini = UserMini(
            id=promo.validateur.id,
            nom=promo.validateur.nom,
            prenom=promo.validateur.prenom,
            email=promo.validateur.email,
        )

    return PromotionResponse(
        id                    = promo.id,
        titre                 = promo.titre,
        description           = promo.description,
        id_hotel              = promo.id_hotel,
        hotel                 = hotel_mini,
        pourcentage           = float(promo.pourcentage),
        date_debut            = promo.date_debut,
        date_fin              = promo.date_fin,
        statut                = promo.statut.value,
        actif                 = promo.actif,
        raison_refus          = promo.raison_refus,
        date_decision         = promo.date_decision,
        id_admin_validateur   = promo.id_admin_validateur,
        validateur            = validateur_mini,
        id_partenaire         = promo.id_partenaire,
        partenaire            = partenaire_mini,
        est_valide_maintenant = est_valide,
        jours_restants        = jours_restants,
        created_at            = promo.created_at,
        updated_at            = promo.updated_at,
    )


async def _load_promo(promo_id: int, session: AsyncSession) -> Promotion:
    result = await session.execute(
        select(Promotion)
        .options(
            selectinload(Promotion.hotel),
            selectinload(Promotion.partenaire),
            selectinload(Promotion.validateur),
        )
        .where(Promotion.id == promo_id)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise NotFoundException(f"Promotion {promo_id} introuvable")
    return promo


async def _check_hotel_owner(hotel_id: int, partenaire_id: int, session: AsyncSession) -> Hotel:
    hotel = (await session.execute(
        select(Hotel).where(Hotel.id == hotel_id)
    )).scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    if hotel.id_partenaire != partenaire_id:
        raise ForbiddenException("Cet hôtel ne vous appartient pas")
    return hotel


# ═══════════════════════════════════════════════════════════
#  EMAILS
# ═══════════════════════════════════════════════════════════

async def _send_decision_email(
    partenaire_email: str,
    partenaire_prenom: str,
    promo_titre: str,
    approved: bool,
    raison_refus: Optional[str] = None,
) -> None:
    """Envoie un email au partenaire pour l'informer de la décision admin."""
    try:
        from app.services.email_service import send_email

        if approved:
            subject = f"✅ Votre promotion « {promo_titre} » a été approuvée"
            color_header = "linear-gradient(135deg,#0F2235,#1A3F63)"
            icon = "✅"
            titre_bloc = "Promotion approuvée !"
            message_bloc = f"""
            <p style="color:#374151;font-size:14px;line-height:1.6;">
              Bonjour <strong>{partenaire_prenom}</strong>,<br><br>
              Bonne nouvelle ! Votre promotion <strong>« {promo_titre} »</strong>
              a été <span style="color:#27AE60;font-weight:700;">approuvée</span>
              par notre équipe. Elle est maintenant visible pour tous les visiteurs
              sur notre plateforme.
            </p>
            <div style="margin:20px 0;padding:16px 20px;background:#F0FBF4;
                        border-left:4px solid #27AE60;border-radius:8px;">
              <p style="color:#155724;font-size:13px;margin:0;font-weight:600;">
                🎉 Votre promotion est en ligne — les clients peuvent dès maintenant
                la voir et en profiter !
              </p>
            </div>
            """
        else:
            subject = f"❌ Votre promotion « {promo_titre} » a été refusée"
            color_header = "linear-gradient(135deg,#0F2235,#1A3F63)"
            icon = "❌"
            titre_bloc = "Promotion refusée"
            raison_html = f"""
            <div style="margin:20px 0;padding:16px 20px;background:#FEF2F2;
                        border-left:4px solid #E74C3C;border-radius:8px;">
              <p style="color:#7F1D1D;font-size:13px;margin:0 0 6px;font-weight:700;">
                Motif du refus :
              </p>
              <p style="color:#7F1D1D;font-size:13px;margin:0;">
                {raison_refus or "Aucune raison spécifiée."}
              </p>
            </div>
            """ if raison_refus else ""
            message_bloc = f"""
            <p style="color:#374151;font-size:14px;line-height:1.6;">
              Bonjour <strong>{partenaire_prenom}</strong>,<br><br>
              Nous vous informons que votre promotion <strong>« {promo_titre} »</strong>
              a été <span style="color:#E74C3C;font-weight:700;">refusée</span>
              par notre équipe de modération.
            </p>
            {raison_html}
            <p style="color:#374151;font-size:14px;">
              Vous pouvez modifier votre promotion et la resoumettre depuis
              votre espace partenaire.
            </p>
            """

        html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#F0F4F8;font-family:'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:40px 20px;">
    <table width="580" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:16px;overflow:hidden;
                  box-shadow:0 4px 24px rgba(0,0,0,.10);">
      <tr><td style="background:{color_header};padding:32px 40px;text-align:center;">
        <h1 style="color:#C4973A;font-size:28px;margin:0;">EasyVoyage</h1>
        <p style="color:rgba(255,255,255,.7);font-size:13px;margin:8px 0 0;">
          Espace Partenaire
        </p>
      </td></tr>
      <tr><td style="padding:32px 40px 16px;text-align:center;">
        <div style="font-size:48px;margin-bottom:12px;">{icon}</div>
        <h2 style="color:#1A3F63;font-size:20px;margin:0 0 4px;">{titre_bloc}</h2>
        <p style="color:#7A8FA6;font-size:13px;margin:0;">
          Promotion : <strong>{promo_titre}</strong>
        </p>
      </td></tr>
      <tr><td style="padding:0 40px 32px;">{message_bloc}</td></tr>
      <tr><td style="padding:20px 40px 32px;text-align:center;">
        <a href="http://localhost:3000"
           style="display:inline-block;background:linear-gradient(135deg,#0F2235,#1A3F63);
                  color:white;text-decoration:none;padding:14px 36px;
                  border-radius:10px;font-weight:bold;font-size:14px;">
          Accéder à mon espace partenaire
        </a>
      </td></tr>
      <tr><td style="background:#F8FAFC;padding:20px 48px;text-align:center;">
        <p style="color:#B0BEC8;font-size:12px;margin:0;">
          EasyVoyage — Votre partenaire de confiance
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

        await send_email(partenaire_email, subject, html)
    except Exception as e:
        print(f"[EMAIL PROMOTION] ❌ Erreur envoi à {partenaire_email}: {e}")


# ═══════════════════════════════════════════════════════════
#  CRUD — PARTENAIRE
# ═══════════════════════════════════════════════════════════

async def list_promotions_partenaire(
    partenaire_id: int,
    session: AsyncSession,
    hotel_id: Optional[int] = None,
    statut: Optional[str] = None,
) -> PromotionListResponse:
    """Liste toutes les promotions des hôtels du partenaire connecté."""
    q = (
        select(Promotion)
        .options(
            selectinload(Promotion.hotel),
            selectinload(Promotion.partenaire),
            selectinload(Promotion.validateur),
        )
        .where(Promotion.id_partenaire == partenaire_id)
        .order_by(Promotion.created_at.desc())
    )
    if hotel_id:
        q = q.where(Promotion.id_hotel == hotel_id)
    if statut:
        try:
            q = q.where(Promotion.statut == StatutPromotion(statut))
        except ValueError:
            pass

    result = await session.execute(q)
    promos = result.scalars().all()
    return PromotionListResponse(total=len(promos), items=[_to_response(p) for p in promos])


async def get_promotion(
    promo_id: int,
    partenaire_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    promo = await _load_promo(promo_id, session)
    if promo.id_partenaire != partenaire_id:
        raise ForbiddenException("Accès refusé")
    return _to_response(promo)


async def create_promotion(
    hotel_id: int,
    data: PromotionCreate,
    partenaire_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    await _check_hotel_owner(hotel_id, partenaire_id, session)

    promo = Promotion(
        titre         = data.titre,
        description   = data.description,
        id_hotel      = hotel_id,
        pourcentage   = data.pourcentage,
        date_debut    = data.date_debut,
        date_fin      = data.date_fin,
        statut        = StatutPromotion.PENDING,   # ← toujours PENDING à la création
        actif         = True,
        id_partenaire = partenaire_id,
    )
    session.add(promo)
    await session.flush()

    result = await session.execute(
        select(Promotion)
        .options(
            selectinload(Promotion.hotel),
            selectinload(Promotion.partenaire),
            selectinload(Promotion.validateur),
        )
        .where(Promotion.id == promo.id)
    )
    promo = result.scalar_one()

    # 🔔 Notifier tous les admins (à valider)
    hotel_nom      = promo.hotel.nom if promo.hotel else "?"
    partenaire_nom = (
        f"{promo.partenaire.prenom} {promo.partenaire.nom}"
        if promo.partenaire else "Un partenaire"
    )
    await notify_all_admins(
        session,
        type_   = NotifType.NOUVELLE_PROMOTION,
        titre   = "Nouvelle promotion à valider",
        message = f"{partenaire_nom} a soumis « {promo.titre} » (-{int(promo.pourcentage)}%) pour {hotel_nom}",
    )

    await session.commit()
    return _to_response(promo)


async def update_promotion(
    promo_id: int,
    data: PromotionUpdate,
    partenaire_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    promo = await _load_promo(promo_id, session)
    if promo.id_partenaire != partenaire_id:
        raise ForbiddenException("Accès refusé")
    if promo.statut not in (StatutPromotion.PENDING, StatutPromotion.REJECTED):
        raise ConflictException(
            "Seules les promotions en attente ou refusées peuvent être modifiées"
        )

    update_data = data.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(promo, k, v)

    # Remettre en PENDING si modification après refus
    if promo.statut == StatutPromotion.REJECTED:
        promo.statut        = StatutPromotion.PENDING
        promo.raison_refus  = None
        promo.date_decision = None
        promo.id_admin_validateur = None

    await session.flush()
    await session.commit()
    await session.refresh(promo)
    return _to_response(promo)


async def delete_promotion(
    promo_id: int,
    partenaire_id: int,
    session: AsyncSession,
) -> None:
    promo = await _load_promo(promo_id, session)
    if promo.id_partenaire != partenaire_id:
        raise ForbiddenException("Accès refusé")
    if promo.statut == StatutPromotion.APPROVED:
        raise ConflictException(
            "Impossible de supprimer une promotion approuvée — désactivez-la d'abord"
        )
    await session.delete(promo)
    await session.commit()


# ═══════════════════════════════════════════════════════════
#  CRUD — ADMIN
# ═══════════════════════════════════════════════════════════

async def list_promotions_admin(
    session: AsyncSession,
    statut: Optional[str] = None,
    hotel_id: Optional[int] = None,
    partenaire_id: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
) -> PromotionListResponse:
    """Liste toutes les promotions (vue admin)."""
    q = (
        select(Promotion)
        .options(
            selectinload(Promotion.hotel),
            selectinload(Promotion.partenaire),
            selectinload(Promotion.validateur),
        )
        .order_by(Promotion.created_at.desc())
    )
    if statut:
        try:
            q = q.where(Promotion.statut == StatutPromotion(statut))
        except ValueError:
            pass
    if hotel_id:
        q = q.where(Promotion.id_hotel == hotel_id)
    if partenaire_id:
        q = q.where(Promotion.id_partenaire == partenaire_id)

    total_res = await session.execute(select(func.count()).select_from(q.subquery()))
    total = total_res.scalar_one()

    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await session.execute(q)
    promos = result.scalars().all()
    return PromotionListResponse(total=total, items=[_to_response(p) for p in promos])


async def get_pending_count(session: AsyncSession) -> int:
    """Retourne le nombre de promotions en attente de validation."""
    result = await session.execute(
        select(func.count()).where(Promotion.statut == StatutPromotion.PENDING)
    )
    return result.scalar_one()


async def traiter_promotion(
    promo_id: int,
    data: DecisionAdmin,
    admin_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    """
    Admin accepte ou refuse une promotion.

    Side-effects :
      - Met à jour le statut + date_decision + raison_refus
      - Envoie un email au partenaire
      - ✨ NEW : Crée une notification dans la cloche du partenaire
    """
    promo = await _load_promo(promo_id, session)

    if promo.statut != StatutPromotion.PENDING:
        raise ConflictException(
            f"Cette promotion est déjà en statut {promo.statut.value}"
        )

    promo.statut              = StatutPromotion(data.action)
    promo.id_admin_validateur = admin_id
    promo.date_decision       = datetime.now(timezone.utc)
    promo.raison_refus        = data.raison_refus if data.action == "REJECTED" else None

    await session.flush()
    await session.commit()

    # Recharger pour avoir les relations à jour
    promo = await _load_promo(promo_id, session)

    # Envoyer email au partenaire
    if promo.partenaire:
        await _send_decision_email(
            partenaire_email  = promo.partenaire.email,
            partenaire_prenom = promo.partenaire.prenom,
            promo_titre       = promo.titre,
            approved          = data.action == "APPROVED",
            raison_refus      = data.raison_refus,
        )

    # ───────────────────────────────────────────────────────
    # ✨ NEW : Notification cloche pour le partenaire
    # ───────────────────────────────────────────────────────
    try:
        if data.action == "APPROVED":
            await notify_partenaire(
                session,
                partenaire_id = promo.id_partenaire,
                type_         = NotifType.PROMOTION_APPROUVEE,
                titre         = "✅ Promotion approuvée",
                message       = (
                    f"Votre promotion « {promo.titre} » (-{int(promo.pourcentage)}%) "
                    f"a été approuvée et est maintenant visible sur la plateforme."
                ),
            )
        else:  # REJECTED
            raison = data.raison_refus or "Aucune raison spécifiée"
            await notify_partenaire(
                session,
                partenaire_id = promo.id_partenaire,
                type_         = NotifType.PROMOTION_REFUSEE,
                titre         = "❌ Promotion refusée",
                message       = (
                    f"Votre promotion « {promo.titre} » a été refusée. "
                    f"Motif : {raison}"
                ),
            )
        await session.commit()
    except Exception as exc:
        # Ne jamais bloquer à cause d'une notif
        import logging
        logging.getLogger(__name__).warning(
            f"[NOTIF promo] Échec création notif partenaire : {exc}"
        )

    return _to_response(promo)


async def toggle_actif_admin(
    promo_id: int,
    actif: bool,
    admin_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    """Admin active/désactive une promotion approuvée."""
    promo = await _load_promo(promo_id, session)
    if promo.statut != StatutPromotion.APPROVED:
        raise ConflictException("Seules les promotions approuvées peuvent être activées/désactivées")
    promo.actif = actif
    await session.flush()
    await session.commit()
    await session.refresh(promo)
    return _to_response(promo)


# ═══════════════════════════════════════════════════════════
#  FONCTIONS PUBLIQUES — Côté visiteur
# ═══════════════════════════════════════════════════════════

def calculer_prix_promo(prix: float, pourcentage: float) -> float:
    """Applique un pourcentage de réduction à un prix."""
    return round(prix * (1 - pourcentage / 100), 2)


async def enrichir_hotels_avec_promos(
    hotels: list,
    hotel_ids: List[int],
    session: AsyncSession,
) -> Dict[int, "Promotion"]:
    """Retourne un dict {hotel_id: Promotion} pour les promos APPROVED actives."""
    if not hotel_ids:
        return {}

    today = date.today()
    result = await session.execute(
        select(Promotion)
        .where(
            Promotion.id_hotel.in_(hotel_ids),
            Promotion.statut   == StatutPromotion.APPROVED,
            Promotion.actif    == True,
            Promotion.date_debut <= today,
            Promotion.date_fin   >= today,
        )
        .order_by(Promotion.id_hotel, Promotion.pourcentage.desc())
    )
    promos = result.scalars().all()

    best_per_hotel: Dict[int, Promotion] = {}
    for p in promos:
        if p.id_hotel not in best_per_hotel:
            best_per_hotel[p.id_hotel] = p
    return best_per_hotel


# ═══════════════════════════════════════════════════════════
#  ALIAS DE COMPATIBILITÉ — utilisés par hotel_service.py
# ═══════════════════════════════════════════════════════════

async def get_promotions_actives_multi_hotels(
    hotel_ids: List[int],
    session: AsyncSession,
) -> Dict[int, "Promotion"]:
    """
    Alias de `enrichir_hotels_avec_promos` pour la compatibilité
    avec hotel_service.py qui importe ce nom.
    Retourne un dict {hotel_id: Promotion ORM} — seules les APPROVED actives.
    """
    if not hotel_ids:
        return {}

    today = date.today()
    result = await session.execute(
        select(Promotion)
        .where(
            Promotion.id_hotel.in_(hotel_ids),
            Promotion.statut     == StatutPromotion.APPROVED,
            Promotion.actif      == True,   # noqa: E712
            Promotion.date_debut <= today,
            Promotion.date_fin   >= today,
        )
        .order_by(Promotion.id_hotel, Promotion.pourcentage.desc())
    )
    promos = result.scalars().all()

    best: Dict[int, Promotion] = {}
    for p in promos:
        if p.id_hotel not in best:
            best[p.id_hotel] = p
    return best


async def get_promotion_active_hotel(
    hotel_id: int,
    session: AsyncSession,
    at_date: Optional[date] = None,
) -> Optional["Promotion"]:
    """
    Retourne l'objet ORM Promotion APPROVED actif pour un hôtel.
    Compatibilité avec hotel_service.py (get_hotel, _to_hotel_response).
    """
    ref_date = at_date or date.today()
    result = await session.execute(
        select(Promotion)
        .where(
            Promotion.id_hotel   == hotel_id,
            Promotion.statut     == StatutPromotion.APPROVED,
            Promotion.actif      == True,   # noqa: E712
            Promotion.date_debut <= ref_date,
            Promotion.date_fin   >= ref_date,
        )
        .order_by(Promotion.pourcentage.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_promotions_catalogue_admin(
    hotel_ids: List[int],
    session: AsyncSession,
) -> Dict[int, "Promotion"]:
    """
    Variante pour les catalogues admin.
    Retourne toutes les promos APPROVED dans les dates,
    SANS filtrer sur actif — cohérent avec la liste UI admin.
    """
    if not hotel_ids:
        return {}

    today = date.today()
    result = await session.execute(
        select(Promotion)
        .where(
            Promotion.id_hotel.in_(hotel_ids),
            Promotion.statut     == StatutPromotion.APPROVED,
            Promotion.date_debut <= today,
            Promotion.date_fin   >= today,
            # ← actif == True intentionnellement absent
        )
        .order_by(Promotion.id_hotel, Promotion.pourcentage.desc())
    )
    promos = result.scalars().all()

    best: Dict[int, Promotion] = {}
    for p in promos:
        if p.id_hotel not in best:
            best[p.id_hotel] = p
    return best