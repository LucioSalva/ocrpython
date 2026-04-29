"""OCR engines."""
from app.services.ocr.base import OCREngine, OCRResult
from app.services.ocr.factory import build_ocr_engine

__all__ = ["OCREngine", "OCRResult", "build_ocr_engine"]
