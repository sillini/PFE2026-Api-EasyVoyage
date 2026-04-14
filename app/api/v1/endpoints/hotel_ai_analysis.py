# ══════════════════════════════════════════════════════════════════════════
#  app/api/v1/endpoints/hotel_ai_analysis.py
#  Analyse IA des avis clients d'un hôtel via Claude API
#
#  POST /admin/hotels/{hotel_id}/avis/analyse-ia
# ══════════════════════════════════════════════════════════════════════════
import json
import os
from typing import List

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.hotel import Avis, Hotel
from app.models.utilisateur import Utilisateur
from app.schemas.auth import TokenData

router = APIRouter(
    prefix="/admin/hotels",
    tags=["Admin — Analyse IA Avis"],
)


# ─── Schémas de réponse ─────────────────────────────────────────────────────

class ClassificationAvis(BaseModel):
    positif: int
    neutre:  int
    negatif: int


class AnalyseIAResponse(BaseModel):
    hotel_id:           int
    hotel_nom:          str
    nb_avis:            int
    note_moyenne:       float
    score_satisfaction: int              # 0-100 généré par IA
    resume_global:      str              # paragraphe de synthèse
    points_positifs:    List[str]        # liste de points forts
    points_negatifs:    List[str]        # liste de points faibles
    recommandations:    List[str]        # actions concrètes
    classification:     ClassificationAvis
    sentiment_dominant: str              # "positif" | "neutre" | "négatif"


# ─── Helper : client Claude ─────────────────────────────────────────────────

def _claude_client() -> anthropic.AsyncAnthropic:
    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY manquant — configurez-le dans .env"
        )
    return anthropic.AsyncAnthropic(api_key=api_key)


# ─── Endpoint ───────────────────────────────────────────────────────────────

@router.post(
    "/{hotel_id}/avis/analyse-ia",
    response_model=AnalyseIAResponse,
    summary="Générer un rapport IA d'analyse des avis clients d'un hôtel",
)
async def analyser_avis_ia(
    hotel_id: int,
    session:  AsyncSession = Depends(get_db),
    _:        TokenData    = Depends(require_admin),
):
    """
    Collecte tous les avis d'un hôtel et demande à Claude une analyse
    structurée : résumé, points forts/faibles, recommandations, score.
    """
    # ── 1. Vérifier que l'hôtel existe ──
    hotel = (await session.execute(
        select(Hotel).where(Hotel.id == hotel_id)
    )).scalar_one_or_none()

    if not hotel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hôtel {hotel_id} introuvable"
        )

    # ── 2. Récupérer tous les avis ──
    avis_result = await session.execute(
        select(Avis)
        .where(Avis.id_hotel == hotel_id)
        .order_by(Avis.date.desc())
    )
    avis_list = avis_result.scalars().all()

    if not avis_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun avis disponible pour cet hôtel — impossible d'analyser"
        )

    # ── 3. Charger les auteurs en une seule requête ──
    client_ids = list({a.id_client for a in avis_list})
    users_result = await session.execute(
        select(Utilisateur).where(Utilisateur.id.in_(client_ids))
    )
    users = {u.id: u for u in users_result.scalars().all()}

    # ── 4. Construire le contexte pour Claude ──
    note_moyenne = round(sum(a.note for a in avis_list) / len(avis_list), 2)

    avis_formatted = []
    for a in avis_list:
        user = users.get(a.id_client)
        client_name = f"{user.prenom} {user.nom[0]}." if user else f"Client #{a.id_client}"
        date_str = a.date.strftime("%d/%m/%Y") if a.date else "date inconnue"
        commentaire = a.commentaire or "(aucun commentaire)"
        avis_formatted.append(
            f"- [{date_str}] {client_name} — Note: {a.note}/5\n  \"{commentaire}\""
        )

    avis_block = "\n".join(avis_formatted)

    # ── 5. Prompt optimisé ──
    prompt = f"""Tu es un expert en analyse de satisfaction client pour l'hôtellerie.

Voici les avis réels laissés par les clients de l'hôtel "{hotel.nom}" situé à {hotel.ville or ''}, {hotel.pays}.

DONNÉES :
- Nombre total d'avis : {len(avis_list)}
- Note moyenne : {note_moyenne}/5

AVIS CLIENTS :
{avis_block}

MISSION :
Analyse ces avis de manière professionnelle et produis un rapport structuré en JSON.
Tu dois répondre UNIQUEMENT avec un objet JSON valide, sans markdown, sans commentaire, sans ```.

STRUCTURE ATTENDUE :
{{
  "score_satisfaction": <entier 0-100 représentant la satisfaction globale>,
  "resume_global": "<paragraphe de 3-4 phrases en français synthétisant la perception générale des clients>",
  "points_positifs": ["<point fort 1>", "<point fort 2>", "<point fort 3>", "..."],
  "points_negatifs": ["<point faible 1>", "<point faible 2>", "..."],
  "recommandations": ["<action concrète 1>", "<action concrète 2>", "<action concrète 3>", "..."],
  "classification": {{
    "positif": <nombre d'avis positifs>,
    "neutre":  <nombre d'avis neutres>,
    "negatif": <nombre d'avis négatifs>
  }},
  "sentiment_dominant": "<'positif' | 'neutre' | 'négatif'>"
}}

RÈGLES :
- Points positifs : 3 à 6 éléments, courts (max 10 mots chacun), concrets et extraits des avis
- Points négatifs : 0 à 5 éléments (liste vide [] si aucun), courts et factuels
- Recommandations : 3 à 5 actions concrètes et actionnables pour le manager
- Classification : la somme positif + neutre + negatif DOIT être égale à {len(avis_list)}
- Tout en FRANÇAIS
- Score de satisfaction : basé sur les notes ET le ton des commentaires
"""

    # ── 6. Appeler Claude ──
    try:
        client = _claude_client()
        msg = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)

    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude a retourné un JSON invalide : {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erreur Claude API : {str(e)}"
        )

    # ── 7. Construire la réponse ──
    classif = parsed.get("classification", {})
    return AnalyseIAResponse(
        hotel_id           = hotel.id,
        hotel_nom          = hotel.nom,
        nb_avis            = len(avis_list),
        note_moyenne       = note_moyenne,
        score_satisfaction = int(parsed.get("score_satisfaction", 0)),
        resume_global      = parsed.get("resume_global", ""),
        points_positifs    = parsed.get("points_positifs", []),
        points_negatifs    = parsed.get("points_negatifs", []),
        recommandations    = parsed.get("recommandations", []),
        classification     = ClassificationAvis(
            positif = int(classif.get("positif", 0)),
            neutre  = int(classif.get("neutre",  0)),
            negatif = int(classif.get("negatif", 0)),
        ),
        sentiment_dominant = parsed.get("sentiment_dominant", "neutre"),
    )