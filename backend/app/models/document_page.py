"""DocumentPage ORM model (per-page text storage, optional)."""
from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Computed, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('spanish_unaccent', coalesce(text_content,''))",
            persisted=True,
        ),
        nullable=True,
    )

    document: Mapped["Document"] = relationship(  # noqa: F821
        "Document", back_populates="pages"
    )
