"""Document ORM model."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    PASSWORD_REQUIRED = "password_required"
    DONE = "done"
    ERROR = "error"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DocumentStatus.QUEUED.value, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    is_native_pdf: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('spanish_unaccent', coalesce(text_content,''))",
            persisted=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    template: Mapped["Template"] = relationship(  # noqa: F821
        "Template", lazy="joined"
    )
    pages: Mapped[list["DocumentPage"]] = relationship(  # noqa: F821
        "DocumentPage",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    cfdi: Mapped["CfdiExtraction | None"] = relationship(  # noqa: F821
        "CfdiExtraction",
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document {self.id} status={self.status}>"
