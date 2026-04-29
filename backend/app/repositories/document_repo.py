"""Document repository (CRUD + FTS)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, desc, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from app.models.cfdi_extraction import CfdiExtraction
from app.models.document import Document, DocumentStatus
from app.models.template import Template


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Create ---
    def create(
        self,
        *,
        template_id: int | None,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        status: DocumentStatus = DocumentStatus.QUEUED,
    ) -> Document:
        doc = Document(
            template_id=template_id,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            status=status.value,
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    # --- Read ---
    def get(self, document_id: uuid.UUID) -> Document | None:
        return self.db.get(Document, document_id)

    def get_cfdi_by_uuid(self, uuid_sat: str) -> CfdiExtraction | None:
        return self.db.execute(
            select(CfdiExtraction).where(CfdiExtraction.uuid_sat == uuid_sat)
        ).scalar_one_or_none()

    # --- Update ---
    def set_status(
        self,
        document_id: uuid.UUID,
        status: DocumentStatus,
        *,
        error_message: str | None = None,
    ) -> None:
        doc = self.db.get(Document, document_id)
        if doc is None:
            return
        doc.status = status.value
        if error_message is not None:
            doc.error_message = error_message
        self.db.commit()

    def update_processing_result(
        self,
        document_id: uuid.UUID,
        *,
        text_content: str | None,
        extracted_fields: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
        language: str | None,
        is_native_pdf: bool | None,
        ocr_engine: str | None,
    ) -> Document | None:
        doc = self.db.get(Document, document_id)
        if doc is None:
            return None
        doc.text_content = text_content
        doc.extracted_fields = extracted_fields
        doc.meta = metadata
        doc.language = language
        doc.is_native_pdf = is_native_pdf
        doc.ocr_engine = ocr_engine
        doc.status = DocumentStatus.DONE.value
        doc.error_message = None
        doc.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    # --- CFDI ---
    def upsert_cfdi(
        self,
        *,
        document_id: uuid.UUID,
        uuid_sat: str,
        payload: dict[str, Any],
        raw_xml: str,
    ) -> CfdiExtraction:
        cfdi = CfdiExtraction(
            document_id=document_id,
            uuid_sat=uuid_sat,
            rfc_emisor=payload.get("rfc_emisor"),
            rfc_receptor=payload.get("rfc_receptor"),
            total=payload.get("total"),
            subtotal=payload.get("subtotal"),
            total_iva=payload.get("total_iva"),
            fecha=payload.get("fecha"),
            serie=payload.get("serie"),
            folio=payload.get("folio"),
            raw_xml=raw_xml,
        )
        self.db.add(cfdi)
        # Let the UNIQUE(uuid_sat) constraint enforce duplicates atomically;
        # callers handle IntegrityError.
        self.db.commit()
        self.db.refresh(cfdi)
        return cfdi

    # --- Delete ---
    def delete(self, document_id: uuid.UUID) -> bool:
        """Delete a Document row (cascades to pages and cfdi)."""
        result = self.db.execute(
            delete(Document).where(Document.id == document_id)
        )
        self.db.commit()
        return result.rowcount > 0

    # --- Search / list ---
    def search(
        self,
        *,
        query: str | None,
        template_code: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(
            Document,
            Template.code.label("template_code"),
        ).outerjoin(Template, Document.template_id == Template.id)

        rank_expr = None
        snippet_expr = None
        if query:
            regconfig = literal("spanish_unaccent", type_=REGCONFIG)
            ts_query = func.plainto_tsquery(regconfig, query)
            rank_expr = func.ts_rank(Document.text_search, ts_query).label("rank")
            snippet_expr = func.ts_headline(
                regconfig,
                func.coalesce(Document.text_content, ""),
                ts_query,
                "MaxFragments=1, MaxWords=20, MinWords=5",
            ).label("snippet")
            stmt = stmt.where(Document.text_search.op("@@")(ts_query))
            stmt = stmt.add_columns(rank_expr, snippet_expr)
            stmt = stmt.order_by(desc(rank_expr), desc(Document.created_at))
        else:
            stmt = stmt.order_by(desc(Document.created_at))

        if template_code:
            stmt = stmt.where(Template.code == template_code)

        # Total count (without limit/offset)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self.db.execute(count_stmt).scalar_one())

        stmt = stmt.limit(limit).offset(offset)
        rows = self.db.execute(stmt).all()

        items: list[dict[str, Any]] = []
        for row in rows:
            doc: Document = row[0]
            template_code_val: str | None = row[1]
            rank_val = row[2] if query else None
            snippet_val = row[3] if query else None
            items.append(
                {
                    "id": doc.id,
                    "template_id": doc.template_id,
                    "template_code": template_code_val,
                    "original_filename": doc.original_filename,
                    "status": doc.status,
                    "language": doc.language,
                    "created_at": doc.created_at,
                    "completed_at": doc.completed_at,
                    "rank": float(rank_val) if rank_val is not None else None,
                    "snippet": snippet_val,
                }
            )
        return items, total
