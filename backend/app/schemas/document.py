"""Document-related Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreateResponse(BaseModel):
    id: uuid.UUID
    status: str


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    error_message: str | None = None


class CfdiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid_sat: str
    rfc_emisor: str | None = None
    rfc_receptor: str | None = None
    total: float | None = None
    subtotal: float | None = None
    total_iva: float | None = None
    fecha: datetime | None = None
    serie: str | None = None
    folio: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    template_id: int | None = None
    template_code: str | None = None
    original_filename: str
    mime_type: str
    size_bytes: int
    status: str
    error_message: str | None = None
    language: str | None = None
    is_native_pdf: bool | None = None
    ocr_engine: str | None = None
    text_content: str | None = None
    extracted_fields: dict[str, Any] | None = None
    # Stored as `meta` on the ORM (column "metadata"); exposed as JSON key "metadata".
    meta: dict[str, Any] | None = Field(default=None, alias="metadata")
    created_at: datetime
    completed_at: datetime | None = None
    cfdi: CfdiOut | None = None


class DocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: int | None
    template_code: str | None
    original_filename: str
    status: str
    language: str | None
    created_at: datetime
    completed_at: datetime | None
    rank: float | None = None
    snippet: str | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    limit: int
    offset: int


class PasswordRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=512)
