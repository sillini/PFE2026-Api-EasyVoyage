# app/models/contact.py
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Contact(Base):
    __tablename__ = "contact"

    id:         Mapped[int]           = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email:      Mapped[str]           = mapped_column(String(255), nullable=False, unique=True, index=True)
    telephone:  Mapped[Optional[str]] = mapped_column(String(30),  nullable=True)
    nom:        Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prenom:     Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    type:       Mapped[str]           = mapped_column(String(20),  nullable=False)  # 'client' | 'visiteur'
    source_id:  Mapped[Optional[int]] = mapped_column(BigInteger,  nullable=True)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Contact email={self.email} type={self.type}>"