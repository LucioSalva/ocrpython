"""CFDI 4.0 extraction model."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CfdiExtraction(Base):
    __tablename__ = "cfdi_extractions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uuid_sat: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    rfc_emisor: Mapped[str | None] = mapped_column(String(13), nullable=True)
    rfc_receptor: Mapped[str | None] = mapped_column(String(13), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_iva: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    fecha: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    serie: Mapped[str | None] = mapped_column(String(64), nullable=True)
    folio: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_xml: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship(  # noqa: F821
        "Document", back_populates="cfdi"
    )
