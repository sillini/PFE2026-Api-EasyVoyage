# ══════════════════════════════════════════════════════════════════════════
#  app/api/v1/endpoints/hotel_description_ai.py
#  Génération / amélioration de la description d'un hôtel via Claude API
#
#  Accessible par : PARTENAIRE (pour ses hôtels) et ADMIN
#
#  POST /hotels/description/generate-ai
#  ─────────────────────────────────────
#  Le partenaire envoie sa description brute (+ quelques méta-infos :
#  nom, ville, étoiles), Claude la réécrit en version marketing
#  professionnelle et évocatrice. Le partenaire peut ensuite éditer
#  le résultat AVANT validation dans le formulaire.
# ══════════════════════════════════════════════════════════════════════════
import os
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
    prefix="/hotels/description",
    tags=["Hôtels — IA Description"],
)


# ─── Schémas de requête / réponse ───────────────────────────────────────────

class GenerateDescriptionRequest(BaseModel):
    nom:         str           = Field(..., min_length=1, max_length=150,
                                       description="Nom de l'établissement")
    ville:       Optional[str] = Field(None, description="Ville (ex: Tunis, Sfax)")
    etoiles:     Optional[int] = Field(None, ge=1, le=5,
                                       description="Classification 1-5 étoiles")
    description_brute: str     = Field(..., min_length=1,
                                       description="Description brute écrite par le partenaire")
    adresse:     Optional[str] = Field(None, description="Adresse complète (contexte supplémentaire)")


class GenerateDescriptionResponse(BaseModel):
    description_amelioree: str


# ─── Helper : client Claude ─────────────────────────────────────────────────

def _claude_client() -> anthropic.AsyncAnthropic:
    """Réutilise exactement le même pattern que hotel_ai_analysis.py."""
    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY manquant — configurez-le dans .env"
        )
    return anthropic.AsyncAnthropic(api_key=api_key)


# ─── Endpoint ───────────────────────────────────────────────────────────────

@router.post(
    "/generate-ai",
    response_model=GenerateDescriptionResponse,
    summary="Améliorer la description d'un hôtel via Claude IA [PARTENAIRE | ADMIN]",
)
async def generate_description_ai(
    data: GenerateDescriptionRequest,
    _session: AsyncSession = Depends(get_db),
    _:       TokenData     = Depends(require_admin_or_partenaire),
):
    """
    Prend la description brute du partenaire et la transforme en description
    marketing professionnelle, chaleureuse et évocatrice.

    Le partenaire peut ensuite éditer librement le résultat dans le formulaire
    AVANT d'enregistrer l'hôtel.
    """

    # ── 1. Construire le contexte ──
    contexte_parts = [f'Nom de l\'établissement : "{data.nom}"']
    if data.ville:
        contexte_parts.append(f'Ville : {data.ville}, Tunisie')
    if data.etoiles:
        etoiles_str = "★" * data.etoiles
        contexte_parts.append(f'Classification : {data.etoiles} étoiles ({etoiles_str})')
    if data.adresse:
        contexte_parts.append(f'Adresse : {data.adresse}')

    contexte = "\n".join(contexte_parts)

    # ── 2. Prompt optimisé ──
    prompt = f"""Tu es un expert en rédaction marketing pour l'hôtellerie de luxe et le tourisme tunisien.

CONTEXTE DE L'ÉTABLISSEMENT :
{contexte}

DESCRIPTION BRUTE FOURNIE PAR LE PARTENAIRE :
\"\"\"{data.description_brute}\"\"\"

MISSION :
Transforme cette description brute en une description marketing professionnelle,
chaleureuse et évocatrice qui donnera envie aux voyageurs de réserver.

RÈGLES STRICTES :
- Rédige en FRANÇAIS, ton chaleureux et inspirant
- Longueur : entre 80 et 200 mots (3-5 phrases fluides, pas de liste à puces)
- Mets en valeur l'expérience client, l'atmosphère, l'emplacement, les points forts
- Utilise un vocabulaire riche mais accessible (pas de jargon publicitaire exagéré)
- Si la ville est fournie, intègre subtilement sa culture / ses atouts touristiques
- Adapte le niveau de prestige au nombre d'étoiles (1-2★ : convivial/familial ; 3★ : confort ; 4-5★ : haut de gamme/luxe)
- Garde fidèlement les informations factuelles de la description brute — n'invente pas de prestations qui ne sont pas mentionnées
- Corrige les fautes d'orthographe et de grammaire
- NE PAS inclure de formule d'introduction du style "Voici la description améliorée :"
- NE PAS utiliser de guillemets englobants ni de markdown
- Réponds UNIQUEMENT avec le texte final de la description, rien d'autre
"""

    # ── 3. Appeler Claude ──
    try:
        client = _claude_client()
        msg = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        description_amelioree = msg.content[0].text.strip()

        # Nettoyage défensif : enlever d'éventuels guillemets ou ``` résiduels
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

    # ── 4. Retourner la description améliorée ──
    return GenerateDescriptionResponse(
        description_amelioree=description_amelioree
    )