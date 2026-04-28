# ══════════════════════════════════════════════════════════════════════════
#  app/api/v1/endpoints/chambre_description_ai.py
#  Génération / amélioration de la description d'une CHAMBRE via Claude API
#
#  Accessible par : PARTENAIRE (pour ses hôtels) et ADMIN
#
#  POST /chambres/description/generate-ai
#  ──────────────────────────────────────
#  Le partenaire envoie sa description brute d'une chambre (+ méta-infos :
#  type de chambre, capacité, nombre de chambres), Claude la réécrit en
#  version marketing professionnelle et évocatrice, adaptée au standing
#  du type de chambre.
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
    prefix="/chambres/description",
    tags=["Chambres — IA Description"],
)


# ─── Schémas de requête / réponse ───────────────────────────────────────────

class GenerateChambreDescriptionRequest(BaseModel):
    type_chambre:      str           = Field(..., min_length=1, max_length=100,
                                              description="Nom du type de chambre (ex: Deluxe, Familiale, Simple, Suite)")
    capacite:          int           = Field(..., ge=1, le=20,
                                              description="Capacité en personnes par chambre")
    nb_chambres:       Optional[int] = Field(None, ge=1,
                                              description="Nombre de chambres de ce type dans l'hôtel (stock)")
    description_brute: str           = Field(..., min_length=1,
                                              description="Description brute écrite par le partenaire")
    hotel_nom:         Optional[str] = Field(None, description="Nom de l'hôtel (contexte optionnel)")
    hotel_etoiles:     Optional[int] = Field(None, ge=1, le=5,
                                              description="Classification de l'hôtel (contexte optionnel)")


class GenerateChambreDescriptionResponse(BaseModel):
    description_amelioree: str


# ─── Helper : client Claude ─────────────────────────────────────────────────

def _claude_client() -> anthropic.AsyncAnthropic:
    """Même pattern que hotel_description_ai.py et hotel_ai_analysis.py."""
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
    response_model=GenerateChambreDescriptionResponse,
    summary="Améliorer la description d'une chambre via Claude IA [PARTENAIRE | ADMIN]",
)
async def generate_chambre_description_ai(
    data: GenerateChambreDescriptionRequest,
    _session: AsyncSession = Depends(get_db),
    _:       TokenData     = Depends(require_admin_or_partenaire),
):
    """
    Prend la description brute du partenaire sur une chambre et la transforme
    en description marketing professionnelle, évocatrice et adaptée au type /
    standing de la chambre.

    Le partenaire peut ensuite éditer librement le résultat dans le formulaire
    AVANT d'enregistrer la chambre.
    """

    # ── 1. Construire le contexte ──
    contexte_parts = [
        f'Type de chambre : {data.type_chambre}',
        f'Capacité : {data.capacite} personne{"s" if data.capacite > 1 else ""} par chambre',
    ]
    if data.nb_chambres:
        contexte_parts.append(f'Stock : {data.nb_chambres} chambre{"s" if data.nb_chambres > 1 else ""} de ce type')
    if data.hotel_nom:
        contexte_parts.append(f'Hôtel : "{data.hotel_nom}"')
    if data.hotel_etoiles:
        etoiles_str = "★" * data.hotel_etoiles
        contexte_parts.append(f'Standing de l\'hôtel : {data.hotel_etoiles} étoiles ({etoiles_str})')

    contexte = "\n".join(f"- {p}" for p in contexte_parts)

    # ── 2. Adapter le ton selon le type de chambre ──
    type_lower = data.type_chambre.lower()
    if any(k in type_lower for k in ["suite", "presidential", "royal", "luxe", "luxury"]):
        ton_indication = "haut de gamme, raffiné, évocateur de luxe et d'exclusivité"
    elif any(k in type_lower for k in ["deluxe", "premium", "executive", "superior"]):
        ton_indication = "élégant, confortable, avec un sens du détail"
    elif any(k in type_lower for k in ["famil", "family", "triple", "quad"]):
        ton_indication = "chaleureux, convivial, centré sur le confort familial"
    elif any(k in type_lower for k in ["simple", "standard", "single", "classique", "basic", "économique"]):
        ton_indication = "accueillant, sobre, axé sur le confort essentiel"
    else:
        ton_indication = "professionnel et chaleureux"

    # ── 3. Prompt optimisé ──
    prompt = f"""Tu es un expert en rédaction marketing pour l'hôtellerie et le tourisme tunisien.

CONTEXTE DE LA CHAMBRE :
{contexte}

DESCRIPTION BRUTE FOURNIE PAR LE PARTENAIRE :
\"\"\"{data.description_brute}\"\"\"

MISSION :
Transforme cette description brute en une description marketing professionnelle
et évocatrice qui donnera envie aux voyageurs de réserver cette chambre.

TON ATTENDU : {ton_indication}

RÈGLES STRICTES :
- Rédige en FRANÇAIS, ton adapté au standing de la chambre
- Longueur : entre 40 et 120 mots (2-4 phrases fluides, pas de liste à puces)
- Mets en valeur l'ambiance, les équipements mentionnés, le confort offert
- Adapte la description au type de chambre ({data.type_chambre}) et à sa capacité ({data.capacite} pers.)
- Garde FIDÈLEMENT les équipements et caractéristiques mentionnés dans la description brute
- N'invente AUCUN équipement qui n'est pas mentionné (pas de piscine, spa, minibar si non cités)
- Corrige orthographe et grammaire
- Privilégie des verbes d'évocation sensorielle : "offrant", "baignée", "dotée", "aménagée", "bénéficiant"
- NE PAS inclure de formule d'introduction ("Voici la description :", "Cette chambre offre...")
- NE PAS utiliser de guillemets englobants, ni de markdown, ni de titres
- NE PAS répéter le type de chambre au début (évite "Chambre Deluxe offrant...")
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
    return GenerateChambreDescriptionResponse(
        description_amelioree=description_amelioree
    )