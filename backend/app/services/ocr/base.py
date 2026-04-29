"""
Abstract OCR engine interface.

Concrete implementations (tesseract, paddleocr, easyocr, ...) must
inherit from `OCREngine`. Selection at runtime is done via the
factory in `app.services.ocr.factory`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class OCRResult:
    """Engine-agnostic OCR output."""

    text: str
    pages: list[str] = field(default_factory=list)
    confidence: float | None = None
    engine: str = ""
    languages: str = ""


class OCREngine(ABC):
    """Common interface for all OCR engines."""

    name: str = "abstract"

    @abstractmethod
    def ocr_image(self, image_path: Path, languages: str) -> OCRResult:
        """Run OCR on a single image (jpg/png/tiff)."""

    @abstractmethod
    def ocr_pdf_pages(self, pdf_path: Path, languages: str) -> OCRResult:
        """Run OCR over a (scanned) PDF, returning per-page text + concatenated text."""
