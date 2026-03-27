"""ORM models pour le support chat partenaire ↔ admin."""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class SupportConversation(Base):
    __tablename__ = "support_conversation"
    __table_args__ = {"schema": "voyage_hotel"}

    id:            Mapped[int]           = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_partenaire: Mapped[int]           = mapped_column(BigInteger, ForeignKey("utilisateur.id", ondelete="CASCADE"), nullable=False, index=True)
    id_admin:      Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("utilisateur.id", ondelete="SET NULL"), nullable=True, index=True)
    sujet:         Mapped[str]           = mapped_column(String(300), nullable=False, default="Support général")
    statut:        Mapped[str]           = mapped_column(String(50),  nullable=False, default="EN_ATTENTE", index=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    partenaire: Mapped["Utilisateur"] = relationship(
        "Utilisateur",
        foreign_keys=[id_partenaire],
        primaryjoin="SupportConversation.id_partenaire == Utilisateur.id",
    )
    admin: Mapped[Optional["Utilisateur"]] = relationship(
        "Utilisateur",
        foreign_keys=[id_admin],
        primaryjoin="SupportConversation.id_admin == Utilisateur.id",
    )
    messages: Mapped[List["SupportMessage"]] = relationship(
        "SupportMessage", back_populates="conversation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<SupportConversation id={self.id} statut={self.statut}>"


class SupportMessage(Base):
    __tablename__ = "support_message"
    __table_args__ = {"schema": "voyage_hotel"}

    id:              Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_conversation: Mapped[int]      = mapped_column(BigInteger, ForeignKey("voyage_hotel.support_conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    id_expediteur:   Mapped[int]      = mapped_column(BigInteger, ForeignKey("utilisateur.id", ondelete="CASCADE"), nullable=False, index=True)
    contenu:         Mapped[str]      = mapped_column(Text, nullable=False)
    lu:              Mapped[bool]     = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    conversation: Mapped[SupportConversation] = relationship(
        "SupportConversation", back_populates="messages"
    )
    expediteur: Mapped["Utilisateur"] = relationship(
        "Utilisateur",
        foreign_keys=[id_expediteur],
        primaryjoin="SupportMessage.id_expediteur == Utilisateur.id",
    )

    def __repr__(self) -> str:
        return f"<SupportMessage id={self.id} lu={self.lu}>"


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = {"schema": "voyage_hotel"}

    id:              Mapped[int]           = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_destinataire: Mapped[int]           = mapped_column(BigInteger, ForeignKey("utilisateur.id", ondelete="CASCADE"), nullable=False, index=True)
    type:            Mapped[str]           = mapped_column(String(100), nullable=False)
    titre:           Mapped[str]           = mapped_column(String(200), nullable=False)
    message:         Mapped[str]           = mapped_column(Text, nullable=False)
    lue:             Mapped[bool]          = mapped_column(Boolean, nullable=False, default=False, index=True)
    id_conversation: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("voyage_hotel.support_conversation.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    destinataire: Mapped["Utilisateur"] = relationship(
        "Utilisateur",
        foreign_keys=[id_destinataire],
        primaryjoin="Notification.id_destinataire == Utilisateur.id",
    )
    conversation: Mapped[Optional[SupportConversation]] = relationship(
        "SupportConversation",
        foreign_keys=[id_conversation],
    )

    def __repr__(self) -> str:
        return f"<Notification id={self.id} type={self.type} lue={self.lue}>"