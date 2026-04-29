"""
OCR engine factory.

Selects an `OCREngine` implementation by env-driven config.
Only Tesseract is implemented for the MVP. Future engines plug in
here by adding new branches; the rest of the pipeline does not change.
"""
from __future__ import annotations

from app.config import settings
from app.services.ocr.base import OCREngine
from app.services.ocr.tesseract import TesseractEngine

_SUPPORTED = {"tesseract"}
_FUTURE = {"paddleocr", "easyocr"}  # placeholders, not yet implemented


def build_ocr_engine(engine_name: str | None = None) -> OCREngine:
    name = (engine_name or settings.OCR_ENGINE or "tesseract").lower()
    if name == "tesseract":
        return TesseractEngine()
    if name in _FUTURE:
        raise NotImplementedError(
            f"OCR engine '{name}' is reserved for a later phase; "
            "set OCR_ENGINE=tesseract for now."
        )
    raise ValueError(
        f"Unsupported OCR engine '{name}'. "
        f"Supported: {sorted(_SUPPORTED)}; future: {sorted(_FUTURE)}."
    )
