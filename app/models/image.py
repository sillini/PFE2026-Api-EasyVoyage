"""
ORM model pour la table image.
Une image appartient soit à un voyage, soit à un hôtel — jamais les deux.
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, Enum, ForeignKey, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TypeImage(str, enum.Enum):
    PRINCIPALE = "PRINCIPALE"
    GALERIE    = "GALERIE"
    MINIATURE  = "MINIATURE"
    BANNIERE   = "BANNIERE"


class Image(Base):
    __tablename__ = "image"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    type: Mapped[TypeImage] = mapped_column(
        Enum(TypeImage, name="type_image", schema="voyage_hotel"),
        nullable=False,
        default=TypeImage.GALERIE,
    )
    id_voyage: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("voyage.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    id_hotel: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("hotel.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Image id={self.id} type={self.type} url={self.url[:40]}>"