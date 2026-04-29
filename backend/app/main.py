"""
FastAPI entrypoint.

Wires:
  - JSON logging
  - CORS (strict, env-driven origin list)
  - Router registration (/health, /templates, /documents)
  - Global concurrency Semaphore stored in `app.state.semaphore`.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import documents, health, templates
from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure storage tree exists
    settings.originals_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)

    # Reap zombie jobs left in-flight by a previous container run.
    # BackgroundTasks live in-process, so a restart kills any pending
    # work; without this sweep, those rows stay forever in queued/processing.
    reaped = 0
    try:
        with SessionLocal() as db:
            result = db.execute(
                text(
                    "UPDATE documents SET status = 'error', "
                    "error_message = 'Interrumpido por reinicio del servicio' "
                    "WHERE status IN ('queued', 'processing')"
                )
            )
            db.commit()
            reaped = result.rowcount or 0
    except Exception:
        logger.exception("zombie_reap_failed")

    # Global concurrency gate for the OCR pipeline
    concurrency = settings.effective_concurrency
    app.state.semaphore = asyncio.Semaphore(concurrency)
    logger.info(
        "app_startup",
        extra={
            "concurrency": concurrency,
            "ocr_engine": settings.OCR_ENGINE,
            "max_upload_mb": settings.MAX_UPLOAD_MB,
            "cors": settings.cors_origin_list,
            "zombies_reaped": reaped,
        },
    )
    try:
        yield
    finally:
        logger.info("app_shutdown")


app = FastAPI(
    title="OCR backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Standardize HTTP error responses (no stack traces leak)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={"path": request.url.path, "method": request.method},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(health.router)
app.include_router(templates.router)
app.include_router(documents.router)
