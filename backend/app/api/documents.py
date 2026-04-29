"""
Document endpoints.

- POST /documents               -> upload + queue
- POST /documents/{id}/password -> resume processing of an encrypted PDF
- GET  /documents/{id}/status   -> lightweight polling
- GET  /documents/{id}          -> full payload
- GET  /documents/{id}/export   -> StreamingResponse of one of the
                                   pre-generated or on-demand exports
- GET  /documents                -> historic search w/ FTS
"""
from __future__ import annotations

import asyncio
import mimetypes
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_semaphore
from app.config import settings
from app.logging_config import get_logger
from app.models.document import DocumentStatus
from app.repositories.document_repo import DocumentRepository
from app.repositories.template_repo import TemplateRepository
from app.schemas.document import (
    DocumentCreateResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentOut,
    DocumentStatusResponse,
    PasswordRequest,
)
from app.services.document_service import (
    _exports_dir,
    run_pipeline_sync,
    save_original,
)
from app.services.exporters.docx import export_docx
from app.services.exporters.xlsx import export_xlsx

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


# --- Allowed input types ---------------------------------------------

_ALLOWED_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/jpg",
    "application/xml",
    "text/xml",
}
_ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".xml"}


def _validate_kind(filename: str, mime_type: str) -> tuple[str, str]:
    """Return (sanitized_extension, normalized_mime). Raises HTTPException."""
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension: {ext or '(none)'}",
        )
    mime = (mime_type or "").lower().strip()
    if mime not in _ALLOWED_MIME:
        # Some browsers send weird mimes for XML; allow when extension matches
        guess, _ = mimetypes.guess_type(filename)
        if guess and guess.lower() in _ALLOWED_MIME:
            mime = guess.lower()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported MIME type: {mime_type!r}",
            )
    # Cross-check: ext must match mime family
    if ext == ".pdf" and mime != "application/pdf":
        raise HTTPException(status_code=400, detail="MIME/extension mismatch (PDF)")
    if ext in {".jpg", ".jpeg"} and "jpeg" not in mime:
        raise HTTPException(status_code=400, detail="MIME/extension mismatch (JPEG)")
    if ext == ".png" and "png" not in mime:
        raise HTTPException(status_code=400, detail="MIME/extension mismatch (PNG)")
    if ext == ".xml" and "xml" not in mime:
        raise HTTPException(status_code=400, detail="MIME/extension mismatch (XML)")
    return ext, mime


# --- Background-task launchers -----------------------------------------

async def _run_with_semaphore(
    document_id: uuid.UUID,
    template_code: str | None,
    password: str | None,
    semaphore: asyncio.Semaphore,
) -> None:
    """Schedule the sync pipeline behind the global semaphore.

    BackgroundTasks awaits coroutines on the running event loop, so the
    OCR work (CPU-bound) is offloaded to the default thread pool with
    `run_in_executor`, while the semaphore bounds concurrent jobs.
    """
    async with semaphore:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            run_pipeline_sync,
            document_id,
            template_code,
            password,
        )


# --- Endpoints ---------------------------------------------------------

@router.post(
    "",
    response_model=DocumentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    template_code: str = Form(...),
    password: str | None = Form(default=None),
    db: Session = Depends(get_db),
    semaphore: asyncio.Semaphore = Depends(get_semaphore),
) -> DocumentCreateResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    ext, mime = _validate_kind(file.filename, file.content_type or "")

    # Stream upload to a temp file with size enforcement
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    total = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.max_upload_bytes:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds {settings.MAX_UPLOAD_MB} MB limit",
                )
            tmp.write(chunk)
    finally:
        tmp.close()
        await file.close()

    # Resolve template
    template_repo = TemplateRepository(db)
    template = template_repo.get_by_code(template_code)
    if template is None:
        Path(tmp.name).unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Unknown template: {template_code}"
        )

    # Persist Document row
    doc_repo = DocumentRepository(db)
    document = doc_repo.create(
        template_id=template.id,
        original_filename=file.filename,
        mime_type=mime,
        size_bytes=total,
    )

    # Move temp file to storage as {id}{ext}
    save_original(document.id, Path(tmp.name), ext)

    # Schedule processing
    background_tasks.add_task(
        _run_with_semaphore,
        document.id,
        template.code,
        password,
        semaphore,
    )

    logger.info(
        "document_uploaded",
        extra={
            "id": str(document.id),
            "template": template.code,
            "size": total,
            "mime": mime,
        },
    )
    return DocumentCreateResponse(id=document.id, status=document.status)


@router.post("/{document_id}/password", response_model=DocumentStatusResponse)
def submit_password(
    document_id: uuid.UUID,
    payload: PasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    semaphore: asyncio.Semaphore = Depends(get_semaphore),
) -> DocumentStatusResponse:
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status != DocumentStatus.PASSWORD_REQUIRED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Document is not awaiting password (status={doc.status})",
        )

    repo.set_status(document_id, DocumentStatus.QUEUED)
    template_code = doc.template.code if doc.template else None
    background_tasks.add_task(
        _run_with_semaphore,
        document_id,
        template_code,
        payload.password,
        semaphore,
    )
    return DocumentStatusResponse(
        id=document_id,
        status=DocumentStatus.QUEUED.value,
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def get_status(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DocumentStatusResponse:
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentStatusResponse(
        id=doc.id, status=doc.status, error_message=doc.error_message
    )


@router.get(
    "/{document_id}",
    response_model=DocumentOut,
    response_model_by_alias=True,
)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DocumentOut:
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut.model_validate(
        {
            "id": doc.id,
            "template_id": doc.template_id,
            "template_code": doc.template.code if doc.template else None,
            "original_filename": doc.original_filename,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes,
            "status": doc.status,
            "error_message": doc.error_message,
            "language": doc.language,
            "is_native_pdf": doc.is_native_pdf,
            "ocr_engine": doc.ocr_engine,
            "text_content": doc.text_content,
            "extracted_fields": doc.extracted_fields,
            "metadata": doc.meta,
            "created_at": doc.created_at,
            "completed_at": doc.completed_at,
            "cfdi": doc.cfdi,
        }
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Delete a document, its DB rows (cascade) and on-disk artifacts.

    Used by the UI when the user cancels the password prompt for an
    encrypted PDF, and as a general cleanup endpoint.
    """
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    deleted = repo.delete(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")

    # Best-effort cleanup of disk artifacts.
    for folder in (
        settings.originals_dir / str(document_id),
        settings.exports_dir / str(document_id),
    ):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

    logger.info("document_deleted", extra={"id": str(document_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_ORIGINAL_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".xml": "application/xml",
}


@router.get("/{document_id}/original")
def get_original(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve the original uploaded file inline (for embed/iframe preview)."""
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    folder = settings.originals_dir / str(document_id)
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Original missing on disk")

    # Prefer the canonical {id}{ext} file; ignore decrypted variants for preview.
    candidates = sorted(
        c for c in folder.iterdir()
        if c.is_file() and ".decrypted" not in c.name
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="Original missing on disk")
    path = candidates[0]
    media_type = _ORIGINAL_MEDIA_TYPES.get(
        path.suffix.lower(), "application/octet-stream"
    )
    safe_name = Path(doc.original_filename or path.name).name
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=safe_name,
        content_disposition_type="inline",
    )


@router.get("/{document_id}/layout")
def get_layout(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve the layout-preserving HTML reconstruction inline."""
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = settings.exports_dir / str(document_id) / "layout.html"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Layout reconstruction unavailable for this document",
        )
    return FileResponse(
        path=path,
        media_type="text/html; charset=utf-8",
        content_disposition_type="inline",
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    q: str | None = Query(default=None, max_length=512),
    template: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    repo = DocumentRepository(db)
    normalized_query = (q or "").strip() or None
    normalized_template = (template or "").strip() or None
    items, total = repo.search(
        query=normalized_query,
        template_code=normalized_template,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        items=[DocumentListItem(**i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Exports ---------------------------------------------------------

ExportFormat = Literal["txt", "json", "pdf", "xlsx", "docx"]


@router.get("/{document_id}/export")
def export_document(
    document_id: uuid.UUID,
    format: ExportFormat = Query(...),
    db: Session = Depends(get_db),
) -> FileResponse:
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status != DocumentStatus.DONE.value:
        raise HTTPException(
            status_code=409,
            detail=f"Document is not ready (status={doc.status})",
        )

    out_dir = _exports_dir(doc.id)
    base_name = Path(doc.original_filename).stem or str(doc.id)

    if format == "txt":
        path = out_dir / "result.txt"
        if not path.exists():
            from app.services.exporters.txt import export_txt as _txt
            _txt(doc.text_content or "", path)
        return FileResponse(
            path=path,
            media_type="text/plain; charset=utf-8",
            filename=f"{base_name}.txt",
        )

    if format == "json":
        path = out_dir / "result.json"
        if not path.exists():
            from app.services.exporters.json_export import export_json as _json
            _json(
                {
                    "id": str(doc.id),
                    "language": doc.language,
                    "is_native_pdf": doc.is_native_pdf,
                    "ocr_engine": doc.ocr_engine,
                    "extracted_fields": doc.extracted_fields,
                    "metadata": doc.meta,
                    "text_content": doc.text_content,
                },
                path,
            )
        return FileResponse(
            path=path,
            media_type="application/json",
            filename=f"{base_name}.json",
        )

    if format == "pdf":
        path = out_dir / "searchable.pdf"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="Searchable PDF unavailable for this document",
            )
        return FileResponse(
            path=path,
            media_type="application/pdf",
            filename=f"{base_name}.searchable.pdf",
        )

    document_info = {
        "id": doc.id,
        "original_filename": doc.original_filename,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "status": doc.status,
        "language": doc.language,
        "is_native_pdf": doc.is_native_pdf,
        "ocr_engine": doc.ocr_engine,
        "template_code": doc.template.code if doc.template else None,
        "created_at": doc.created_at,
        "completed_at": doc.completed_at,
    }

    if format == "xlsx":
        path = out_dir / "result.xlsx"
        export_xlsx(
            text_content=doc.text_content,
            extracted_fields=doc.extracted_fields,
            metadata=doc.meta,
            document_info=document_info,
            output_path=path,
        )
        return FileResponse(
            path=path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=f"{base_name}.xlsx",
        )

    if format == "docx":
        path = out_dir / "result.docx"
        export_docx(
            text_content=doc.text_content,
            extracted_fields=doc.extracted_fields,
            document_info=document_info,
            output_path=path,
        )
        return FileResponse(
            path=path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{base_name}.docx",
        )

    raise HTTPException(status_code=400, detail=f"Unknown format: {format}")
