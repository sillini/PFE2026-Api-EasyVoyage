# app/models/video_campaign.py
"""
ORM model pour les campagnes vidéo marketing.

Workflow :
  BROUILLON → EN_GENERATION → PRET → EN_ENVOI → ENVOYE / ECHOUE

Chaque campagne :
  - est liée à une destination (hôtel ou voyage ou texte libre)
  - génère un script via Claude AI
  - génère une vidéo via Replicate
  - est ensuite envoyée par email via Brevo
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum,
    Integer, JSON, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StatutVideoCampaign(str, enum.Enum):
    BROUILLON      = "BROUILLON"       # créé, pas encore généré
    EN_GENERATION  = "EN_GENERATION"   # Replicate en cours
    PRET           = "PRET"            # vidéo prête, pas encore envoyée
    EN_ENVOI       = "EN_ENVOI"        # envoi en cours
    ENVOYE         = "ENVOYE"          # envoi terminé avec succès
    ECHOUE         = "ECHOUE"          # erreur génération ou envoi


class TonVideoCampaign(str, enum.Enum):
    LUXE       = "LUXE"
    AVENTURE   = "AVENTURE"
    FAMILLE    = "FAMILLE"
    ROMANTIQUE = "ROMANTIQUE"
    AFFAIRES   = "AFFAIRES"


class FormatVideo(str, enum.Enum):
    LANDSCAPE = "LANDSCAPE"   # 16:9 — email / web
    PORTRAIT  = "PORTRAIT"    # 9:16 — Reels / Stories
    SQUARE    = "SQUARE"      # 1:1  — posts


class SegmentDestinataire(str, enum.Enum):
    TOUS      = "tous"
    CLIENTS   = "client"
    VISITEURS = "visiteur"


class VideoCampaign(Base):
    __tablename__ = "video_campaign"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Informations de base ──────────────────────────────
    titre: Mapped[str] = mapped_column(String(300), nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)  # texte libre

    # IDs optionnels si la destination est un hôtel ou voyage existant
    hotel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    voyage_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # ── Paramètres de génération ──────────────────────────
    ton: Mapped[TonVideoCampaign] = mapped_column(
        Enum(TonVideoCampaign, name="ton_video_campaign", schema="voyage_hotel"),
        nullable=False, default=TonVideoCampaign.LUXE,
    )
    formats: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True, default=["LANDSCAPE"]
    )  # liste de FormatVideo

    # ── Contenu généré par Claude ─────────────────────────
    script_video: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sujet_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description_marketing: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cta_texte: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hashtags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    prompts_images: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # ── Résultats Replicate ───────────────────────────────
    replicate_prediction_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    video_url_landscape: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    video_url_portrait: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    video_url_square: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # ── Envoi email ───────────────────────────────────────
    segment: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tous"
    )
    contact_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    nb_envoyes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nb_echecs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    envoye_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── A/B Testing ───────────────────────────────────────
    ab_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ab_variante_sujet: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ab_variante_cta: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ab_gagnant: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "A" | "B"

    # ── Statut et erreurs ─────────────────────────────────
    statut: Mapped[StatutVideoCampaign] = mapped_column(
        Enum(StatutVideoCampaign, name="statut_video_campaign", schema="voyage_hotel"),
        nullable=False, default=StatutVideoCampaign.BROUILLON,
    )
    erreur: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Métadonnées ───────────────────────────────────────
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<VideoCampaign id={self.id} titre={self.titre} statut={self.statut}>"