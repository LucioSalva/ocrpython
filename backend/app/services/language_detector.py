"""
Language detection wrapper around `langdetect`.

`langdetect.detect` is non-deterministic by default (uses a random
seed); we pin `DetectorFactory.seed = 0` to make CI/runs reproducible.
"""
from __future__ import annotations

from langdetect import DetectorFactory, LangDetectException, detect

from app.logging_config import get_logger

DetectorFactory.seed = 0

logger = get_logger(__name__)

_SUPPORTED = {"es", "en"}
_MIN_TEXT_LEN = 30


def detect_language(text: str) -> str | None:
    """Return ISO-639-1 code ('es'/'en') or None if confidence is too low."""
    if not text or len(text.strip()) < _MIN_TEXT_LEN:
        return None
    try:
        code = detect(text)
    except LangDetectException:
        return None
    if code in _SUPPORTED:
        return code
    # Map close variants to the supported set
    if code.startswith("es"):
        return "es"
    if code.startswith("en"):
        return "en"
    logger.debug("lang_unsupported", extra={"raw": code})
    return None
