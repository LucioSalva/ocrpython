"""
Document processing pipeline (orchestrator).

Stages:
  1. Persist `Document` row.
  2. Save the original file to STORAGE/originals/{id}/{id}.{ext}
  3. Detect kind (XML CFDI / PDF / image).
  4. For PDFs: detect encryption + native vs scanned (60% rule).
     - native       -> read text via PyMuPDF
     - scanned      -> ocrmypdf -> searchable PDF + extracted text
     - encrypted    -> set status=password_required and stop
  5. For images: tesseract directly + image_to_searchable_pdf for export.
  6. For CFDI XML: parse via lxml, write cfdi_extractions, mark done.
  7. Detect language, run regex field extractor.
  8. Update DB row, pre-generate TXT/JSON/searchable-PDF exports.
  9. On error: status=error, error_message=<sanitized>.

Concurrency: a global asyncio.Semaphore (created in api/deps.py) bounds
how many heavy CPU jobs run at once; this module just `await`s it.
"""
from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.logging_config import get_logger
from app.models.document import DocumentStatus
from app.repositories.document_repo import DocumentRepository
from app.services.cfdi_parser import (
    CfdiParseError,
    is_cfdi_xml,
    parse_cfdi,
)
from app.services.exporters.json_export import export_json
from app.services.exporters.searchable_pdf import (
    image_to_searchable_pdf,
    passthrough_pdf,
)
from app.services.exporters.txt import export_txt
from app.services.field_extractor import extract_fields
from app.services.language_detector import detect_language
from app.services.layout_renderer import (
    write_layout_html_for_image,
    write_layout_html_for_pdf,
)
from app.services.ocr.factory import build_ocr_engine
from app.services.pdf_inspector import inspect_pdf
from app.services.pdf_password import PdfPasswordError, decrypt_pdf
from app.services.searchable_pdf import SearchablePdfError, make_searchable_pdf

logger = get_logger(__name__)


# --- File-system helpers --------------------------------------------

def _originals_dir(document_id: uuid.UUID) -> Path:
    p = settings.originals_dir / str(document_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _exports_dir(document_id: uuid.UUID) -> Path:
    p = settings.exports_dir / str(document_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_original(document_id: uuid.UUID, source_path: Path, extension: str) -> Path:
    """Move the temp upload into originals/{id}/{id}.{ext}."""
    target = _originals_dir(document_id) / f"{document_id}{extension.lower()}"
    shutil.move(str(source_path), target)
    return target


def find_original(document_id: uuid.UUID) -> Path | None:
    folder = settings.originals_dir / str(document_id)
    if not folder.exists():
        return None
    candidates = sorted(folder.iterdir())
    # Skip decrypted variants when picking the source
    primary = [
        c for c in candidates
        if c.is_file() and ".decrypted" not in c.name
    ]
    return primary[0] if primary else None


# --- Pipeline (sync core, called inside `run_in_executor`) ----------

def run_pipeline_sync(
    document_id: uuid.UUID,
    template_code: str | None,
    password: str | None,
) -> None:
    """Synchronous pipeline entry point (executed inside a worker thread)."""
    db: Session = SessionLocal()
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        logger.error("pipeline_doc_missing", extra={"id": str(document_id)})
        db.close()
        return

    repo.set_status(document_id, DocumentStatus.PROCESSING)

    try:
        original = find_original(document_id)
        if original is None:
            raise RuntimeError("Original file missing on disk")

        suffix = original.suffix.lower()
        text_content: str | None = None
        is_native_pdf: bool | None = None
        ocr_engine_name: str | None = None
        extracted: dict[str, Any] = {}
        metadata: dict[str, Any] = {
            "source_extension": suffix,
            "languages": settings.OCR_LANGUAGES,
        }

        # --- XML CFDI path ---------------------------------------
        if suffix == ".xml":
            if not is_cfdi_xml(original):
                raise RuntimeError("XML is not a CFDI cfdi:Comprobante")
            try:
                cfdi = parse_cfdi(original)
            except CfdiParseError as exc:
                raise RuntimeError(f"Invalid CFDI: {exc}") from exc

            existing = repo.get_cfdi_by_uuid(cfdi.uuid_sat)
            if existing is not None:
                # Reject as duplicate: uuid_sat is UNIQUE and 1:1 with a document.
                # Mark this upload as error pointing at the previous document.
                repo.set_status(
                    document_id,
                    DocumentStatus.ERROR,
                    error_message=(
                        f"CFDI duplicado: el UUID SAT {cfdi.uuid_sat} ya existe "
                        f"como documento {existing.document_id}"
                    ),
                )
                logger.info(
                    "cfdi_duplicate_rejected",
                    extra={
                        "id": str(document_id),
                        "duplicate_of": str(existing.document_id),
                        "uuid_sat": cfdi.uuid_sat,
                    },
                )
                db.close()
                return

            try:
                repo.upsert_cfdi(
                    document_id=document_id,
                    uuid_sat=cfdi.uuid_sat,
                    payload={
                        "rfc_emisor": cfdi.rfc_emisor,
                        "rfc_receptor": cfdi.rfc_receptor,
                        "total": cfdi.total,
                        "subtotal": cfdi.subtotal,
                        "total_iva": cfdi.total_iva,
                        "fecha": cfdi.fecha,
                        "serie": cfdi.serie,
                        "folio": cfdi.folio,
                    },
                    raw_xml=cfdi.raw_xml,
                )
            except IntegrityError:
                # Race: another upload of the same UUID landed first.
                db.rollback()
                winner = repo.get_cfdi_by_uuid(cfdi.uuid_sat)
                winner_id = str(winner.document_id) if winner else "?"
                repo.set_status(
                    document_id,
                    DocumentStatus.ERROR,
                    error_message=(
                        f"CFDI duplicado: el UUID SAT {cfdi.uuid_sat} ya existe "
                        f"como documento {winner_id}"
                    ),
                )
                db.close()
                return

            text_content = cfdi.text_summary
            extracted = {
                "uuid_sat": cfdi.uuid_sat,
                "rfc_emisor": cfdi.rfc_emisor,
                "rfc_receptor": cfdi.rfc_receptor,
                "total": float(cfdi.total) if cfdi.total is not None else None,
                "subtotal": float(cfdi.subtotal) if cfdi.subtotal is not None else None,
                "total_iva": float(cfdi.total_iva) if cfdi.total_iva is not None else None,
                "fecha": cfdi.fecha.isoformat() if cfdi.fecha else None,
                "serie": cfdi.serie,
                "folio": cfdi.folio,
                **cfdi.extra_fields,
            }
            metadata["kind"] = "cfdi"

        # --- PDF path --------------------------------------------
        elif suffix == ".pdf":
            working_pdf = original
            inspection = inspect_pdf(working_pdf)

            if inspection.is_encrypted:
                if not password:
                    repo.set_status(document_id, DocumentStatus.PASSWORD_REQUIRED)
                    logger.info("pipeline_password_required", extra={"id": str(document_id)})
                    db.close()
                    return
                try:
                    working_pdf = decrypt_pdf(working_pdf, password)
                except PdfPasswordError as exc:
                    raise RuntimeError(str(exc)) from exc
                inspection = inspect_pdf(working_pdf)
                if inspection.is_encrypted:
                    raise RuntimeError("PDF still encrypted after decrypt")

            metadata["page_count"] = inspection.page_count
            metadata["native_ratio"] = round(inspection.ratio, 4)

            if inspection.is_native:
                is_native_pdf = True
                text_content = inspection.native_text
                # For exports: searchable PDF is just the original
                searchable_target = _exports_dir(document_id) / "searchable.pdf"
                passthrough_pdf(working_pdf, searchable_target)
                metadata["kind"] = "pdf_native"
            else:
                is_native_pdf = False
                ocr_engine = build_ocr_engine()
                ocr_engine_name = ocr_engine.name
                # Always use the aggressive OCR engine for the canonical
                # text_content (DPI 400, CLAHE, deskew, multi-PSM).
                res = ocr_engine.ocr_pdf_pages(working_pdf, settings.OCR_LANGUAGES)
                text_content = res.text
                # Generate the searchable PDF for the export button as a
                # best-effort step; failure here does not stop the pipeline.
                searchable_target = _exports_dir(document_id) / "searchable.pdf"
                try:
                    make_searchable_pdf(
                        input_pdf=working_pdf,
                        output_pdf=searchable_target,
                        languages=settings.OCR_LANGUAGES,
                    )
                except SearchablePdfError:
                    logger.warning(
                        "searchable_pdf_failed",
                        extra={"id": str(document_id)},
                    )
                metadata["kind"] = "pdf_scanned"

            # Layout-preserving HTML (best effort).
            try:
                write_layout_html_for_pdf(
                    pdf_path=working_pdf,
                    output_html=_exports_dir(document_id) / "layout.html",
                    languages=settings.OCR_LANGUAGES,
                    is_native=bool(is_native_pdf),
                )
            except Exception:
                logger.exception(
                    "layout_html_failed",
                    extra={"id": str(document_id)},
                )

        # --- Image path ------------------------------------------
        elif suffix in {".jpg", ".jpeg", ".png"}:
            ocr_engine = build_ocr_engine()
            ocr_engine_name = ocr_engine.name
            res = ocr_engine.ocr_image(original, settings.OCR_LANGUAGES)
            text_content = res.text
            metadata["kind"] = "image"
            try:
                searchable_target = _exports_dir(document_id) / "searchable.pdf"
                image_to_searchable_pdf(original, searchable_target, settings.OCR_LANGUAGES)
            except SearchablePdfError:
                logger.warning(
                    "image_searchable_pdf_failed",
                    extra={"id": str(document_id)},
                )
            # Layout-preserving HTML (best effort).
            try:
                write_layout_html_for_image(
                    image_path=original,
                    output_html=_exports_dir(document_id) / "layout.html",
                    languages=settings.OCR_LANGUAGES,
                )
            except Exception:
                logger.exception(
                    "layout_html_failed",
                    extra={"id": str(document_id)},
                )

        else:
            raise RuntimeError(f"Unsupported file extension: {suffix}")

        # --- Language + fields -----------------------------------
        language = detect_language(text_content or "")
        if not extracted:
            extracted = extract_fields(template_code or "texto_libre", text_content or "")

        # --- Persist results -------------------------------------
        repo.update_processing_result(
            document_id,
            text_content=text_content,
            extracted_fields=extracted,
            metadata=metadata,
            language=language,
            is_native_pdf=is_native_pdf,
            ocr_engine=ocr_engine_name,
        )

        # --- Pre-generate TXT and JSON exports -------------------
        export_txt(text_content or "", _exports_dir(document_id) / "result.txt")
        export_json(
            {
                "id": str(document_id),
                "language": language,
                "is_native_pdf": is_native_pdf,
                "ocr_engine": ocr_engine_name,
                "extracted_fields": extracted,
                "metadata": metadata,
                "text_content": text_content or "",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            _exports_dir(document_id) / "result.json",
        )

        logger.info(
            "pipeline_done",
            extra={
                "id": str(document_id),
                "kind": metadata.get("kind"),
                "lang": language,
                "chars": len(text_content or ""),
            },
        )

    except Exception as exc:
        logger.exception("pipeline_failed", extra={"id": str(document_id)})
        message = _sanitize_error(exc)
        repo.set_status(
            document_id,
            DocumentStatus.ERROR,
            error_message=message,
        )
    finally:
        db.close()


def _sanitize_error(exc: Exception) -> str:
    """Strip filesystem paths and sensitive substrings from error output."""
    raw = str(exc) or exc.__class__.__name__
    # Truncate so the DB column stays small
    raw = raw.strip().replace("\n", " ")
    return raw[:512]


# --- Async entry points ---------------------------------------------

async def schedule_processing(
    document_id: uuid.UUID,
    *,
    semaphore: asyncio.Semaphore,
    template_code: str | None,
    password: str | None,
) -> None:
    """Run the pipeline in a worker thread, gated by the global semaphore."""
    async with semaphore:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            run_pipeline_sync,
            document_id,
            template_code,
            password,
        )
