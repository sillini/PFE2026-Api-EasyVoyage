"""ORM model pour la table invitation_otp."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class InvitationOTP(Base):
    __tablename__ = "invitation_otp"

    id:         Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email:      Mapped[str]      = mapped_column(String(255), nullable=False, index=True)
    code:       Mapped[str]      = mapped_column(String(10), nullable=False)
    expire_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used:       Mapped[bool]     = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<InvitationOTP email={self.email} used={self.used}>"