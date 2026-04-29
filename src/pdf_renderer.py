"""Render PDF pages to BGR numpy arrays using PyMuPDF."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import fitz  # PyMuPDF
import numpy as np

logger = logging.getLogger(__name__)


class EncryptedPDFError(RuntimeError):
    """Raised when a PDF is password-protected and cannot be opened."""


class PdfTooLargeError(RuntimeError):
    """Raised when a PDF would render to absurd memory (defensive cap)."""


# Defensive caps to avoid runaway memory on malformed / malicious PDFs.
MAX_PAGES = 1000
# 500 MB worth of 8-bit RGB samples per page (w * h * 3 bytes).
MAX_PIXMAP_BYTES = 500 * 1024 * 1024


def _pix_to_bgr(pix: fitz.Pixmap) -> np.ndarray:
    """Convert a PyMuPDF Pixmap to a BGR numpy array (cv2-friendly)."""
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    samples = np.frombuffer(pix.samples, dtype=np.uint8)
    arr = samples.reshape(pix.height, pix.width, pix.n).copy()
    # PyMuPDF gives us RGB; cv2 expects BGR.
    if pix.n >= 3:
        arr = arr[:, :, [2, 1, 0]]
    return arr


def iter_pdf_pages(pdf_path: Path, dpi: int = 400) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (page_index_1based, bgr_image) for each page.

    Raises EncryptedPDFError if the document is password-protected.
    """
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        if doc.is_encrypted:
            # Try empty-password unlock; otherwise refuse.
            if not doc.authenticate(""):
                raise EncryptedPDFError(
                    f"PDF cifrado o protegido por contrasena: {pdf_path.name}"
                )
        if doc.page_count > MAX_PAGES:
            raise PdfTooLargeError(
                f"PDF excede el limite de paginas ({doc.page_count} > {MAX_PAGES})"
            )
        for index, page in enumerate(doc):
            # Pre-flight: estimate pixmap size and refuse absurdly large pages.
            est_w = int(page.rect.width * zoom)
            est_h = int(page.rect.height * zoom)
            est_bytes = max(est_w, 0) * max(est_h, 0) * 3
            if est_bytes > MAX_PIXMAP_BYTES:
                raise PdfTooLargeError(
                    f"Pagina {index + 1} estimaria {est_bytes / 1024**2:.0f}MB "
                    f"a {dpi} DPI (limite {MAX_PIXMAP_BYTES / 1024**2:.0f}MB). "
                    "Reduce --dpi."
                )
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            arr = _pix_to_bgr(pix)
            yield index + 1, arr


def render_pdf_to_images(
    pdf_path: Path, dpi: int = 400
) -> list[tuple[int, np.ndarray]]:
    """Eager wrapper around iter_pdf_pages — only for small PDFs."""
    return list(iter_pdf_pages(pdf_path, dpi=dpi))
