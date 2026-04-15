# app/services/video_campaign_service.py
"""
Service principal — orchestre tout le pipeline Video Campaign :

  1. CRUD (créer, lister, détail, supprimer)
  2. Génération contenu Claude
  3. Génération vidéo Replicate
  4. Construction email HTML
  5. Envoi Brevo via email_service
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.video_campaign import VideoCampaign, StatutVideoCampaign
from app.models.contact import Contact
from app.schemas.video_campaign import (
    VideoCampaignCreate,
    VideoCampaignResponse,
    VideoCampaignListResponse,
    EnvoyerVideoCampaignRequest,
)
from app.services import video_campaign_claude_service as claude_svc
from app.services import video_campaign_replicate_service as replicate_svc
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

BATCH_SIZE  = 20
BATCH_DELAY = 2.0


# ══════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════

async def creer_campaign(
    data: VideoCampaignCreate,
    created_by: int,
    session: AsyncSession,
) -> VideoCampaignResponse:
    """Crée une nouvelle campagne vidéo en BROUILLON."""
    campaign = VideoCampaign(
        titre        = data.titre,
        destination  = data.destination,
        hotel_id     = data.hotel_id,
        voyage_id    = data.voyage_id,
        ton          = data.ton,
        formats      = data.formats,
        segment      = data.segment,
        contact_ids  = data.contact_ids,
        scheduled_at = data.scheduled_at,
        ab_enabled   = data.ab_enabled,
        statut       = StatutVideoCampaign.BROUILLON,
        created_by   = created_by,
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    logger.info(f"[VIDEO_CAMPAIGN] Créée : id={campaign.id} titre={campaign.titre}")
    return VideoCampaignResponse.model_validate(campaign)


async def lister_campaigns(
    page: int,
    per_page: int,
    statut: Optional[str],
    session: AsyncSession,
) -> VideoCampaignListResponse:
    """Liste les campagnes avec pagination et filtre statut."""
    q = select(VideoCampaign)
    if statut:
        q = q.where(VideoCampaign.statut == statut)

    total = (await session.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar_one()

    q = q.order_by(VideoCampaign.created_at.desc())
    q = q.offset((page - 1) * per_page).limit(per_page)
    rows = (await session.execute(q)).scalars().all()

    return VideoCampaignListResponse(
        total    = total,
        page     = page,
        per_page = per_page,
        items    = [VideoCampaignResponse.model_validate(r) for r in rows],
    )


async def get_campaign(campaign_id: int, session: AsyncSession) -> VideoCampaignResponse:
    """Retourne une campagne par son ID."""
    camp = await _get_or_404(campaign_id, session)
    return VideoCampaignResponse.model_validate(camp)


async def supprimer_campaign(campaign_id: int, session: AsyncSession) -> dict:
    """Supprime une campagne (seulement si BROUILLON ou ECHOUE)."""
    camp = await _get_or_404(campaign_id, session)
    if camp.statut not in (StatutVideoCampaign.BROUILLON, StatutVideoCampaign.ECHOUE):
        raise ValueError(f"Impossible de supprimer une campagne avec statut '{camp.statut.value}'")
    await session.delete(camp)
    await session.commit()
    return {"message": f"Campagne #{campaign_id} supprimée"}


# ══════════════════════════════════════════════════════════
#  ÉTAPE 1 : GÉNÉRER CONTENU CLAUDE
# ══════════════════════════════════════════════════════════

async def generer_contenu(
    campaign_id: int,
    session: AsyncSession,
) -> VideoCampaignResponse:
    """
    Appelle Claude pour générer le script, le sujet email,
    les prompts images, etc. Met à jour la campagne en DB.
    """
    camp = await _get_or_404(campaign_id, session)

    if camp.statut not in (StatutVideoCampaign.BROUILLON, StatutVideoCampaign.ECHOUE):
        raise ValueError(f"Contenu déjà généré ou campagne en cours (statut: {camp.statut.value})")

    try:
        contenu = await claude_svc.generer_contenu(
            destination  = camp.destination,
            ton          = camp.ton.value if hasattr(camp.ton, "value") else camp.ton,
            segment      = camp.segment,
            voyage_id    = camp.voyage_id,   # Claude charge les vraies données BDD
            session      = session,
        )

        # Persister le contenu
        camp.script_video           = contenu["script_video"]
        camp.sujet_email            = contenu["sujet_email"]
        camp.description_marketing  = contenu["description_marketing"]
        camp.cta_texte              = contenu["cta_texte"]
        camp.hashtags               = contenu["hashtags"]
        camp.prompts_images         = contenu["prompts_images"]
        camp.ab_variante_sujet      = contenu.get("ab_variante_sujet")
        camp.ab_variante_cta        = contenu.get("ab_variante_cta")
        camp.erreur                 = None

        await session.commit()
        await session.refresh(camp)
        logger.info(f"[VIDEO_CAMPAIGN] Contenu Claude OK — id={campaign_id}")

    except Exception as e:
        camp.erreur = str(e)
        camp.statut = StatutVideoCampaign.ECHOUE
        await session.commit()
        logger.error(f"[VIDEO_CAMPAIGN] Erreur Claude — id={campaign_id} : {e}")
        raise

    return VideoCampaignResponse.model_validate(camp)


# ══════════════════════════════════════════════════════════
#  ÉTAPE 2 : GÉNÉRER VIDÉO REPLICATE
# ══════════════════════════════════════════════════════════

async def generer_video(
    campaign_id: int,
    session: AsyncSession,
) -> VideoCampaignResponse:
    """
    Lance la génération vidéo via Replicate.
    Bloque jusqu'à completion (max 5 min).
    """
    camp = await _get_or_404(campaign_id, session)

    if not camp.prompts_images:
        raise ValueError("Contenu Claude non généré — appelez d'abord /generer-contenu")

    if camp.statut == StatutVideoCampaign.EN_GENERATION:
        raise ValueError("Génération vidéo déjà en cours")

    # Passer en EN_GENERATION
    camp.statut = StatutVideoCampaign.EN_GENERATION
    camp.erreur = None
    await session.commit()

    ton = camp.ton.value if hasattr(camp.ton, "value") else camp.ton
    formats = camp.formats or ["LANDSCAPE"]

    try:
        media = await replicate_svc.generer_campagne_media(
            prompts_images = camp.prompts_images,
            formats        = formats,
            destination    = camp.destination,
            ton            = ton,
            hotel_id       = camp.hotel_id,
            voyage_id      = camp.voyage_id,
            session        = session,
        )

        camp.video_url_landscape = media.get("video_url_landscape")
        camp.video_url_portrait  = media.get("video_url_portrait")
        camp.video_url_square    = media.get("video_url_square")
        camp.thumbnail_url       = media.get("thumbnail_url")
        camp.statut              = StatutVideoCampaign.PRET
        camp.erreur              = None

        await session.commit()
        await session.refresh(camp)
        logger.info(f"[VIDEO_CAMPAIGN] Vidéo générée OK — id={campaign_id}")

    except Exception as e:
        camp.statut = StatutVideoCampaign.ECHOUE
        camp.erreur = str(e)
        await session.commit()
        logger.error(f"[VIDEO_CAMPAIGN] Erreur Replicate — id={campaign_id} : {e}")
        raise

    return VideoCampaignResponse.model_validate(camp)


# ══════════════════════════════════════════════════════════
#  ÉTAPE 3 : ENVOYER PAR EMAIL
# ══════════════════════════════════════════════════════════

async def envoyer_campaign(
    campaign_id: int,
    data: EnvoyerVideoCampaignRequest,
    session: AsyncSession,
) -> VideoCampaignResponse:
    """
    Envoie la campagne vidéo par email à tous les contacts du segment.
    """
    camp = await _get_or_404(campaign_id, session)

    if camp.statut != StatutVideoCampaign.PRET:
        raise ValueError(
            f"La campagne doit être à l'état PRET pour être envoyée (actuel: {camp.statut.value})"
        )

    # Résoudre les contacts
    contacts = await _resoudre_contacts(data, session)
    if not contacts:
        raise ValueError("Aucun contact trouvé pour ce segment")

    # Passer en EN_ENVOI
    camp.statut  = StatutVideoCampaign.EN_ENVOI
    camp.segment = data.segment
    await session.commit()

    sujet = camp.sujet_email or f"Découvrez {camp.destination} avec EasyVoyage"

    envoyes = 0
    echecs  = 0

    for i in range(0, len(contacts), BATCH_SIZE):
        batch = contacts[i:i + BATCH_SIZE]
        tasks = [
            _envoyer_a_contact(camp, contact, sujet)
            for contact in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                echecs += 1
                logger.warning(f"[VIDEO_CAMPAIGN] Échec envoi : {r}")
            else:
                envoyes += 1

        if i + BATCH_SIZE < len(contacts):
            await asyncio.sleep(BATCH_DELAY)

    camp.nb_envoyes = envoyes
    camp.nb_echecs  = echecs
    camp.statut     = StatutVideoCampaign.ENVOYE if envoyes > 0 else StatutVideoCampaign.ECHOUE
    camp.envoye_at  = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(camp)

    logger.info(f"[VIDEO_CAMPAIGN] Envoi terminé — id={campaign_id} : {envoyes} OK / {echecs} KO")
    return VideoCampaignResponse.model_validate(camp)


# ══════════════════════════════════════════════════════════
#  COMPTAGE DESTINATAIRES
# ══════════════════════════════════════════════════════════

async def compter_destinataires(segment: str, session: AsyncSession) -> dict:
    """Compte les contacts qui seront ciblés."""
    q = select(func.count(Contact.id))
    if segment in ("client", "visiteur"):
        q = q.where(Contact.type == segment)
    total = (await session.execute(q)).scalar_one()
    return {"total": total, "segment": segment}


# ══════════════════════════════════════════════════════════
#  HELPERS PRIVÉS
# ══════════════════════════════════════════════════════════

async def _get_or_404(campaign_id: int, session: AsyncSession) -> VideoCampaign:
    camp = await session.get(VideoCampaign, campaign_id)
    if not camp:
        from fastapi import HTTPException
        raise HTTPException(404, f"Campagne vidéo #{campaign_id} introuvable")
    return camp


async def _load_hotel_info(hotel_id: Optional[int], session: AsyncSession) -> Optional[dict]:
    if not hotel_id:
        return None
    try:
        from app.models.hotel import Hotel, Chambre, Tarif
        from app.models.promotion import Promotion, StatutPromotion
        from datetime import date

        today = date.today()

        hotel = await session.get(Hotel, hotel_id)
        if not hotel:
            return None

        # Prix min
        prix_row = (await session.execute(
            select(func.min(Tarif.prix))
            .join(Chambre, Tarif.id_chambre == Chambre.id)
            .where(
                Chambre.id_hotel == hotel_id,
                Chambre.actif == True,
                Tarif.date_debut <= today,
                Tarif.date_fin >= today,
            )
        )).scalar()

        # Promo active
        promo_row = (await session.execute(
            select(Promotion)
            .where(
                Promotion.id_hotel == hotel_id,
                Promotion.statut == StatutPromotion.APPROVED,
                Promotion.actif == True,
                Promotion.date_debut <= today,
                Promotion.date_fin >= today,
            )
            .limit(1)
        )).scalar_one_or_none()

        info = {
            "nom":     hotel.nom,
            "ville":   hotel.ville,
            "etoiles": hotel.etoiles,
            "prix_min": float(prix_row) if prix_row else None,
        }

        if promo_row and prix_row:
            pct = float(promo_row.pourcentage)
            prix_promo = round(float(prix_row) * (1 - pct / 100), 2)
            info["promo"] = {
                "pourcentage": pct,
                "prix_original": float(prix_row),
                "prix_promo": prix_promo,
            }

        return info
    except Exception as e:
        logger.warning(f"[VIDEO_CAMPAIGN] Erreur chargement hôtel {hotel_id}: {e}")
        return None


async def _load_voyage_info(voyage_id: Optional[int], session: AsyncSession) -> Optional[dict]:
    if not voyage_id:
        return None
    try:
        from app.models.voyage import Voyage
        voyage = await session.get(Voyage, voyage_id)
        if not voyage:
            return None
        return {
            "titre":       voyage.titre,
            "destination": voyage.destination,
            "duree":       voyage.duree,
            "prix_base":   float(voyage.prix_base),
            "date_depart": str(voyage.date_depart),
        }
    except Exception as e:
        logger.warning(f"[VIDEO_CAMPAIGN] Erreur chargement voyage {voyage_id}: {e}")
        return None


async def _resoudre_contacts(
    data: EnvoyerVideoCampaignRequest,
    session: AsyncSession,
) -> list[dict]:
    """Résout la liste des contacts selon mode manuel ou automatique."""
    if data.contact_ids:
        contacts = []
        for cid in data.contact_ids:
            c = await session.get(Contact, cid)
            if c:
                contacts.append({"email": c.email, "prenom": c.prenom or "", "nom": c.nom or ""})
        return contacts

    q = select(Contact).order_by(Contact.created_at.desc())
    if data.segment in ("client", "visiteur"):
        q = q.where(Contact.type == data.segment)
    q = q.limit(data.nb_contacts)
    rows = (await session.execute(q)).scalars().all()
    return [{"email": c.email, "prenom": c.prenom or "", "nom": c.nom or ""} for c in rows]


async def _envoyer_a_contact(camp: VideoCampaign, contact: dict, sujet: str) -> bool:
    """Construit et envoie l'email vidéo à un contact."""
    html = _build_email_html(camp, contact)
    await send_email(contact["email"], sujet, html)
    return True


def _build_email_html(camp: VideoCampaign, contact: dict) -> str:
    """Construit le HTML de l'email vidéo personnalisé."""
    prenom = contact.get("prenom") or "Voyageur"
    video_url = (
        camp.video_url_landscape
        or camp.video_url_portrait
        or camp.video_url_square
        or ""
    )
    thumbnail = camp.thumbnail_url or ""
    cta = camp.cta_texte or "Réserver maintenant"
    description = camp.description_marketing or ""
    destination = camp.destination

    # Lien vers la plateforme
    lien_reservation = "http://localhost:3000"

    # Section vidéo : GIF animé si disponible, sinon thumbnail statique
    if video_url:
        video_section = f"""
        <div style="text-align:center;margin:20px 0;">
          <a href="{lien_reservation}" style="display:block;">
            <video width="100%" style="max-width:600px;border-radius:12px;"
                   autoplay muted loop playsinline poster="{thumbnail}">
              <source src="{video_url}" type="video/mp4">
              <!-- Fallback image si vidéo non supportée -->
              <img src="{thumbnail}" alt="{destination}" style="width:100%;border-radius:12px;">
            </video>
          </a>
          <p style="font-size:12px;color:#8A9BB0;margin-top:8px;">
            ▶ Vidéo non visible ? <a href="{video_url}" style="color:#C4973A;">Cliquez ici</a>
          </p>
        </div>"""
    elif thumbnail:
        video_section = f"""
        <div style="text-align:center;margin:20px 0;">
          <a href="{lien_reservation}">
            <img src="{thumbnail}" alt="{destination}"
                 style="width:100%;max-width:600px;border-radius:12px;">
          </a>
        </div>"""
    else:
        video_section = ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{destination} — EasyVoyage</title></head>
<body style="margin:0;padding:0;background:#F0F4F8;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:32px 16px;">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

      <!-- Header -->
      <tr><td style="background:#0F2235;padding:28px 40px;border-radius:16px 16px 0 0;text-align:center;">
        <p style="color:#C4973A;font-size:11px;letter-spacing:3px;margin:0 0 6px;text-transform:uppercase;">
          Catalogues &amp; Offres Exclusives
        </p>
        <h1 style="color:#ffffff;font-size:26px;font-weight:700;margin:0;">EasyVoyage</h1>
      </td></tr>

      <!-- Titre destination -->
      <tr><td style="background:#C4973A;padding:18px 40px;text-align:center;">
        <h2 style="color:#0F2235;font-size:20px;font-weight:700;margin:0;">
          {destination}
        </h2>
      </td></tr>

      <!-- Corps -->
      <tr><td style="background:#ffffff;padding:32px 40px;">
        <p style="color:#1C2E42;font-size:16px;margin:0 0 20px;">
          Bonjour <strong>{prenom}</strong>,
        </p>

        {video_section}

        <p style="color:#4A5568;font-size:15px;line-height:1.7;margin:20px 0;">
          {description}
        </p>

        <!-- CTA -->
        <div style="text-align:center;margin:28px 0;">
          <a href="{lien_reservation}"
             style="display:inline-block;background:linear-gradient(135deg,#C4973A,#E8B84B);
                    color:#0F2235;text-decoration:none;padding:14px 40px;
                    border-radius:10px;font-weight:700;font-size:15px;">
            {cta}
          </a>
        </div>

      </td></tr>

      <!-- Footer -->
      <tr><td style="background:#F8FAFC;padding:20px 40px;text-align:center;
                     border-top:1px solid #EEF2F7;border-radius:0 0 16px 16px;">
        <p style="color:#B0BEC8;font-size:12px;margin:0;">
          EasyVoyage Tunisie — <a href="{lien_reservation}" style="color:#C4973A;">www.easyvoyage.tn</a>
        </p>
        <p style="color:#C8D0DA;font-size:11px;margin:6px 0 0;">
          Vous recevez cet email car vous êtes inscrit sur EasyVoyage.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""