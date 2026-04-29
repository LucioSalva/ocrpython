"""
Searchable-PDF export entry point.

The searchable PDF is generated during the processing pipeline (when the
input is a scanned PDF). For native PDFs, we just copy the original file.
For images, we ocrmypdf-wrap the image into a PDF.

This module is here so the exports/* layer is uniform and importable.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import ocrmypdf

from app.config import settings
from app.logging_config import get_logger
from app.services.searchable_pdf import SearchablePdfError

logger = get_logger(__name__)


def passthrough_pdf(source_pdf: Path, output_pdf: Path) -> Path:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_pdf, output_pdf)
    return output_pdf


def image_to_searchable_pdf(
    image_path: Path,
    output_pdf: Path,
    languages: str | None = None,
) -> Path:
    """Wrap a single image into a searchable PDF using ocrmypdf."""
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    lang = languages or settings.OCR_LANGUAGES
    try:
        ocrmypdf.ocr(
            input_file=str(image_path),
            output_file=str(output_pdf),
            language=lang,
            image_dpi=300,
            output_type="pdf",
            progress_bar=False,
            jobs=1,
            optimize=0,
        )
    except Exception as exc:
        logger.exception("ocrmypdf_image_failed")
        raise SearchablePdfError(str(exc)) from exc
    return output_pdf
