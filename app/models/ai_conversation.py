"""
app/models/ai_conversation.py
==============================
Modèles ORM pour les conversations avec l'Agent IA.
"""
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AiConversation(Base):
    __tablename__  = "ai_conversation"
    __table_args__ = {"schema": "voyage_hotel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # FK vers utilisateur — pas de schéma car utilisateur est la table par défaut
    id_utilisateur: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("utilisateur.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    session_id:      Mapped[str]  = mapped_column(String(80),  nullable=False, unique=True, index=True)
    titre:           Mapped[str]  = mapped_column(String(200), nullable=False, default="Nouvelle conversation")
    role_contexte:   Mapped[str]  = mapped_column(String(30),  nullable=False, default="ADMIN")
    archivee:        Mapped[bool] = mapped_column(Boolean,     nullable=False, default=False)
    nb_messages:     Mapped[int]  = mapped_column(Integer,     nullable=False, default=0)
    tokens_total:    Mapped[int]  = mapped_column(Integer,     nullable=False, default=0)

    created_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    utilisateur: Mapped["Utilisateur"] = relationship(  # type: ignore[name-defined]
        "Utilisateur",
        foreign_keys=[id_utilisateur],
        primaryjoin="AiConversation.id_utilisateur == Utilisateur.id",
        lazy="select",
    )

    messages: Mapped[List["AiMessage"]] = relationship(
        "AiMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AiMessage.created_at",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<AiConversation id={self.id} user={self.id_utilisateur} titre='{self.titre[:30]}'>"


class AiMessage(Base):
    __tablename__  = "ai_message"
    __table_args__ = {"schema": "voyage_hotel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ⚠️ FK avec schéma explicite car ai_conversation est dans voyage_hotel
    id_conversation: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("voyage_hotel.ai_conversation.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    # 'user' | 'assistant' | 'system' | 'tool'
    role:       Mapped[str]            = mapped_column(String(20), nullable=False)
    contenu:    Mapped[str]            = mapped_column(Text, nullable=False)
    # Attribut Python renommé car 'metadata' est réservé par SQLAlchemy
    # La colonne SQL reste 'metadata'
    extra_data: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    tokens:     Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)
    duree_ms:   Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)
    is_error:   Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped[AiConversation] = relationship(
        "AiConversation", back_populates="messages"
    )

    def __repr__(self) -> str:
        return f"<AiMessage id={self.id} role={self.role} conv={self.id_conversation}>"