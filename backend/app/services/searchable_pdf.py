"""
Generate a searchable PDF from a scanned PDF using ocrmypdf.

We use `skip_text=True` so already-textual pages are left intact and only
imaged pages get an OCR text layer.
"""
from __future__ import annotations

from pathlib import Path

import ocrmypdf

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class SearchablePdfError(Exception):
    """Raised when ocrmypdf fails."""


def make_searchable_pdf(
    *,
    input_pdf: Path,
    output_pdf: Path,
    languages: str | None = None,
) -> tuple[Path, str]:
    """
    Run ocrmypdf to produce a searchable PDF and the extracted sidecar text.
    Returns (output_pdf_path, extracted_text).
    """
    lang = languages or settings.OCR_LANGUAGES
    sidecar = output_pdf.with_suffix(".txt")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        # NOTE: we use force_ocr instead of skip_text because the
        # Ghostscript 10.0.0 shipped by Debian Bookworm has a known
        # regression that ocrmypdf refuses to use with skip_text/redo_ocr.
        # By the time we reach this function the pdf_inspector has already
        # classified the file as scanned, so there is no native text layer
        # to preserve.
        ocrmypdf.ocr(
            input_file=str(input_pdf),
            output_file=str(output_pdf),
            language=lang,
            force_ocr=True,
            optimize=0,
            output_type="pdf",
            progress_bar=False,
            sidecar=str(sidecar),
            deskew=True,
            clean=False,
            jobs=1,
        )
    except ocrmypdf.exceptions.PriorOcrFoundError:
        # PDF already had OCR layer — copy bytes through.
        output_pdf.write_bytes(input_pdf.read_bytes())
        logger.info("ocrmypdf_skipped_existing_layer", extra={"path": str(input_pdf)})
        return output_pdf, ""
    except Exception as exc:  # ocrmypdf raises a variety of exceptions
        logger.exception("ocrmypdf_failed")
        raise SearchablePdfError(str(exc)) from exc

    text = ""
    if sidecar.exists():
        try:
            text = sidecar.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        finally:
            try:
                sidecar.unlink()
            except OSError:
                pass
    logger.info(
        "ocrmypdf_done",
        extra={"output": str(output_pdf), "chars": len(text)},
    )
    return output_pdf, text
