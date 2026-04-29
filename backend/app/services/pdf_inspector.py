"""
PDF inspection helpers.

Detect:
- Whether a PDF is encrypted.
- Whether it carries native (selectable) text vs being a scan.

Native-vs-scan rule (final, agreed upstream):
For each page, extract text via PyMuPDF, drop whitespace, drop characters
in the Unicode Private Use Area (PUA, U+E000..U+F8FF, U+F0000..U+FFFFD,
U+100000..U+10FFFD) and the replacement char `\\ufffd`. Compare the
resulting "valid" character count with total non-whitespace characters.
A document is considered native if (valid / total) >= 0.60.

If the page yields no text at all, that page contributes 0 valid / 0 total
(it does NOT auto-fail the document — the average ratio across pages with
text is what matters).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from app.logging_config import get_logger

logger = get_logger(__name__)

NATIVE_PDF_RATIO = 0.60


def _is_pua(cp: int) -> bool:
    return (
        0xE000 <= cp <= 0xF8FF
        or 0xF0000 <= cp <= 0xFFFFD
        or 0x100000 <= cp <= 0x10FFFD
    )


def _classify_chars(text: str) -> tuple[int, int]:
    """Return (valid_count, total_non_whitespace_count) using the rules above."""
    total = 0
    valid = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        cp = ord(ch)
        if ch == "�" or _is_pua(cp):
            continue
        # Drop unassigned code points too (defensive)
        if unicodedata.category(ch) == "Cn":
            continue
        valid += 1
    return valid, total


@dataclass(slots=True)
class PdfInspection:
    is_encrypted: bool
    is_native: bool
    ratio: float
    page_count: int
    native_text: str  # only meaningful when is_native is True
    native_pages: list[str]


def inspect_pdf(pdf_path: Path) -> PdfInspection:
    """Open PDF (without password) and report encryption + native-text status."""
    with fitz.open(pdf_path) as doc:
        if doc.is_encrypted:
            logger.info("pdf_encrypted", extra={"path": str(pdf_path)})
            return PdfInspection(
                is_encrypted=True,
                is_native=False,
                ratio=0.0,
                page_count=doc.page_count,
                native_text="",
                native_pages=[],
            )

        page_count = doc.page_count
        page_texts: list[str] = []
        valid_total = 0
        total_total = 0

        for page in doc:
            page_text = page.get_text("text") or ""
            page_texts.append(page_text)
            v, t = _classify_chars(page_text)
            valid_total += v
            total_total += t

        if total_total == 0:
            ratio = 0.0
        else:
            ratio = valid_total / total_total

        is_native = ratio >= NATIVE_PDF_RATIO and total_total > 0
        logger.info(
            "pdf_inspection",
            extra={
                "ratio": round(ratio, 4),
                "is_native": is_native,
                "pages": page_count,
                "valid_chars": valid_total,
                "total_chars": total_total,
            },
        )
        return PdfInspection(
            is_encrypted=False,
            is_native=is_native,
            ratio=ratio,
            page_count=page_count,
            native_text="\n".join(page_texts) if is_native else "",
            native_pages=page_texts if is_native else [],
        )
