# app/models/send_log.py
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class SendLog(Base):
    __tablename__ = "send_log"

    id:            Mapped[int]           = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    catalogue_id:  Mapped[int]           = mapped_column(BigInteger, ForeignKey("catalogue.id", ondelete="CASCADE"), nullable=False, index=True)
    email:         Mapped[str]           = mapped_column(String(255), nullable=False)
    nom:           Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    statut:        Mapped[str]           = mapped_column(String(20),  nullable=False, default="pending")
    # pending | sent | failed
    retry_count:   Mapped[int]           = mapped_column(Integer,     nullable=False, default=0)
    error_msg:     Mapped[Optional[str]] = mapped_column(Text,        nullable=True)

    # Tracking
    opened_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:    Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<SendLog id={self.id} email={self.email} statut={self.statut}>"