# ══════════════════════════════════════════════════════════════════════════
#  app/api/v1/endpoints/promotion_description_ai.py
#  Génération / amélioration de la description d'une PROMOTION via Claude API
#
#  Accessible par : PARTENAIRE (pour ses promotions) et ADMIN
#
#  POST /promotions/description/generate-ai
#  ────────────────────────────────────────
#  Le partenaire envoie la description brute de sa promotion (+ méta-infos :
#  titre, pourcentage, dates, hôtel), Claude la réécrit en version marketing
#  professionnelle et attractive pour stimuler les réservations.
# ══════════════════════════════════════════════════════════════════════════
import os
from datetime import date
from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin_or_partenaire
from app.core.config import settings
from app.db.session import get_db
from app.schemas.auth import TokenData

router = APIRouter(
    prefix="/promotions/description",
    tags=["Promotions — IA Description"],
)


# ─── Schémas de requête / réponse ───────────────────────────────────────────

class GeneratePromoDescriptionRequest(BaseModel):
    titre:             str           = Field(..., min_length=1, max_length=200,
                                              description="Titre de la promotion (ex: 'Offre d'été', 'Spécial Ramadan')")
    pourcentage:       float         = Field(..., gt=0, lt=100,
                                              description="Pourcentage de réduction (1-99)")
    date_debut:        Optional[date] = Field(None, description="Date de début de la promotion")
    date_fin:          Optional[date] = Field(None, description="Date de fin de la promotion")
    description_brute: str           = Field(..., min_length=1,
                                              description="Description brute écrite par le partenaire")
    hotel_nom:         Optional[str] = Field(None, description="Nom de l'hôtel concerné (contexte optionnel)")
    hotel_ville:       Optional[str] = Field(None, description="Ville de l'hôtel (contexte optionnel)")
    hotel_etoiles:     Optional[int] = Field(None, ge=1, le=5,
                                              description="Classification de l'hôtel (contexte optionnel)")


class GeneratePromoDescriptionResponse(BaseModel):
    description_amelioree: str


# ─── Helper : client Claude ─────────────────────────────────────────────────

def _claude_client() -> anthropic.AsyncAnthropic:
    """Même pattern que les autres endpoints IA."""
    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY manquant — configurez-le dans .env"
        )
    return anthropic.AsyncAnthropic(api_key=api_key)


# ─── Helper : détecter le type de saison / occasion ─────────────────────────

def _detecter_saison(titre: str, date_debut: Optional[date]) -> str:
    """Détecte le contexte saisonnier pour adapter le ton."""
    titre_lower = titre.lower()

    # Mots-clés dans le titre
    if any(k in titre_lower for k in ["été", "ete", "summer", "plage", "mer"]):
        return "estival, évocateur de soleil, plage, détente"
    if any(k in titre_lower for k in ["hiver", "winter", "neige", "ski"]):
        return "hivernal, cosy, chaleureux"
    if any(k in titre_lower for k in ["ramadan", "aïd", "aid", "eid"]):
        return "festif, spirituel, familial, évoquant les traditions du Ramadan / Aïd"
    if any(k in titre_lower for k in ["noël", "noel", "christmas", "nouvel an", "réveillon", "reveillon"]):
        return "festif, magique, chaleureux, évocateur des fêtes de fin d'année"
    if any(k in titre_lower for k in ["saint valentin", "saint-valentin", "valentine", "romantique", "couple", "lune de miel"]):
        return "romantique, tendre, intime"
    if any(k in titre_lower for k in ["famille", "family", "enfants", "kids"]):
        return "familial, convivial, ludique"
    if any(k in titre_lower for k in ["weekend", "week-end", "escapade"]):
        return "court séjour, évasion, détente express"
    if any(k in titre_lower for k in ["early", "avance", "early booking", "early bird"]):
        return "incitatif à la réservation anticipée, avec une idée d'opportunité à saisir"
    if any(k in titre_lower for k in ["last minute", "dernière minute", "derniere minute", "flash"]):
        return "urgent, exclusif, opportunité à saisir rapidement"

    # Selon la date de début
    if date_debut:
        mois = date_debut.month
        if mois in (6, 7, 8):
            return "estival, évocateur de soleil et détente"
        if mois in (12, 1, 2):
            return "hivernal, cosy, réconfortant"
        if mois in (3, 4, 5):
            return "printanier, frais, léger, renaissant"
        if mois in (9, 10, 11):
            return "automnal, doux, serein"

    return "attractif, convivial et engageant"


# ─── Endpoint ───────────────────────────────────────────────────────────────

@router.post(
    "/generate-ai",
    response_model=GeneratePromoDescriptionResponse,
    summary="Améliorer la description d'une promotion via Claude IA [PARTENAIRE | ADMIN]",
)
async def generate_promo_description_ai(
    data: GeneratePromoDescriptionRequest,
    _session: AsyncSession = Depends(get_db),
    _:       TokenData     = Depends(require_admin_or_partenaire),
):
    """
    Prend la description brute d'une promotion et la transforme en texte
    marketing professionnel qui donne envie de profiter de l'offre.

    Le partenaire peut ensuite éditer librement le résultat dans le formulaire
    AVANT de soumettre la promotion à validation.
    """

    # ── 1. Construire le contexte ──
    contexte_parts = [
        f'Titre de la promotion : "{data.titre}"',
        f'Réduction : -{int(data.pourcentage) if data.pourcentage == int(data.pourcentage) else data.pourcentage}%',
    ]

    if data.date_debut and data.date_fin:
        try:
            nb_jours = (data.date_fin - data.date_debut).days + 1
            contexte_parts.append(
                f'Période : du {data.date_debut.strftime("%d/%m/%Y")} '
                f'au {data.date_fin.strftime("%d/%m/%Y")} ({nb_jours} jour{"s" if nb_jours > 1 else ""})'
            )
        except Exception:
            pass

    if data.hotel_nom:
        contexte_parts.append(f'Hôtel concerné : "{data.hotel_nom}"')
    if data.hotel_ville:
        contexte_parts.append(f'Ville : {data.hotel_ville}, Tunisie')
    if data.hotel_etoiles:
        etoiles_str = "★" * data.hotel_etoiles
        contexte_parts.append(f'Standing : {data.hotel_etoiles} étoiles ({etoiles_str})')

    contexte = "\n".join(f"- {p}" for p in contexte_parts)

    # ── 2. Détecter le ton selon saison / occasion ──
    ton_indication = _detecter_saison(data.titre, data.date_debut)

    # ── 3. Prompt optimisé ──
    prompt = f"""Tu es un expert en marketing hôtelier et en rédaction d'offres promotionnelles pour le tourisme tunisien.

CONTEXTE DE LA PROMOTION :
{contexte}

DESCRIPTION BRUTE FOURNIE PAR LE PARTENAIRE :
\"\"\"{data.description_brute}\"\"\"

MISSION :
Transforme cette description brute en un texte marketing accrocheur et professionnel
qui donnera envie aux voyageurs de profiter de cette offre promotionnelle.

TON ATTENDU : {ton_indication}

RÈGLES STRICTES :
- Rédige en FRANÇAIS, ton engageant et incitatif (mais pas racoleur ni exagéré)
- Longueur : entre 40 et 130 mots (2-4 phrases fluides, pas de liste à puces)
- Mets en valeur l'intérêt de l'offre et l'urgence / l'exclusivité quand c'est pertinent
- Intègre subtilement la réduction ({int(data.pourcentage) if data.pourcentage == int(data.pourcentage) else data.pourcentage}%) si la description brute l'évoque, sinon concentre-toi sur l'expérience
- Adapte-toi au contexte saisonnier / thématique détecté ci-dessus
- Garde FIDÈLEMENT les avantages mentionnés dans la description brute
- N'invente AUCUN avantage supplémentaire (pas de "petit-déjeuner offert", "spa inclus", etc. s'ils ne sont pas cités)
- Corrige orthographe et grammaire
- Utilise des verbes d'action engageants : "profitez", "découvrez", "savourez", "évadez-vous"
- Tu peux suggérer un sentiment d'opportunité ("offre limitée", "places restreintes") UNIQUEMENT si cela correspond au contexte
- NE PAS inclure de formule d'introduction ("Voici la description :", "Cette promotion offre...")
- NE PAS utiliser de guillemets englobants, ni de markdown, ni de titres
- NE PAS répéter le pourcentage plusieurs fois (une fois suffit)
- NE PAS inclure d'emoji
- Réponds UNIQUEMENT avec le texte final de la description, rien d'autre
"""

    # ── 4. Appeler Claude ──
    try:
        client = _claude_client()
        msg = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        description_amelioree = msg.content[0].text.strip()

        # Nettoyage défensif
        description_amelioree = description_amelioree.strip('"').strip("'").strip()
        description_amelioree = description_amelioree.replace("```", "").strip()

        if not description_amelioree:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Claude a retourné une réponse vide"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erreur Claude API : {str(e)}"
        )

    # ── 5. Retourner la description améliorée ──
    return GeneratePromoDescriptionResponse(
        description_amelioree=description_amelioree
    )