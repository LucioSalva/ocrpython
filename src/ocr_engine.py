"""Tesseract OCR wrappers with multi-PSM scoring."""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Sequence

import numpy as np
import pytesseract

logger = logging.getLogger(__name__)

# Domain keywords used to bias scoring toward Mexican municipal docs.
DOMAIN_KEYWORDS: tuple[str, ...] = (
    "NOMBRE",
    "DESCRIPCION",
    "DESCRIPCIÓN",
    "FUNDAMENTO",
    "REQUISITOS",
    "ORIGINAL",
    "COPIAS",
    "COSTO",
    "FORMA DE PAGO",
    "RESPUESTA",
    "TRAMITES",
    "TRÁMITES",
    "SERVICIOS",
    "FECHA",
    "ELABORO",
    "ELABORÓ",
    "VISTO BUENO",
)

# ASCII + Spanish accented characters considered "valid".
_VALID_CHARS_RE = re.compile(
    r"[A-Za-z0-9\s\.\,\;\:\-\(\)\/\%\$\#\&\'\"\!\?À-ſ¿¡\n\r\t]"
)
# Match runs of 3+ chars that are NOT in the valid set (real OCR garbage).
_INVALID_RUN_RE = re.compile(
    r"[^A-Za-z0-9\s\.\,\;\:\-\(\)\/\%\$\#\&\'\"\!\?À-ſ¿¡\n\r\t]{3,}"
)


def _autodetect_tesseract_windows() -> str | None:
    if os.name != "nt":
        return None
    candidate = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if candidate.exists():
        return str(candidate)
    candidate2 = Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")
    if candidate2.exists():
        return str(candidate2)
    return None


def _ensure_tesseract_cmd() -> str | None:
    """Make sure pytesseract knows where tesseract.exe is. Returns the
    resolved path (or None if relying on PATH worked)."""
    # Highest priority: explicit env var override.
    env_override = os.environ.get("OCR_TESSERACT_PATH")
    if env_override:
        p = Path(env_override)
        if p.exists():
            pytesseract.pytesseract.tesseract_cmd = str(p)
            return str(p)
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    auto = _autodetect_tesseract_windows()
    if auto:
        pytesseract.pytesseract.tesseract_cmd = auto
        return auto
    return None


def tesseract_check(required_lang: str = "spa") -> tuple[bool, str | None]:
    """Verify Tesseract is callable and the requested language is installed.

    `required_lang` may be a single code ("spa") or a `+`-joined combination
    ("spa+eng"). All sub-codes must be present.
    Returns (ok, error_message_or_None).
    """
    resolved = _ensure_tesseract_cmd()
    if resolved is None:
        return (
            False,
            "No se encontro el binario de Tesseract. Instalalo con "
            "'winget install UB-Mannheim.TesseractOCR' y agrega "
            r"'C:\Program Files\Tesseract-OCR' al PATH "
            "(o reinicia la terminal).",
        )
    try:
        langs = pytesseract.get_languages(config="")
    except Exception as e:
        return (
            False,
            f"Tesseract instalado en '{resolved}' pero falla al ejecutarse: {e}",
        )
    # Defense-in-depth: only accept simple lowercase 3-letter codes joined
    # by '+'. Stops accidental injection of weird strings into the lang
    # parameter that pytesseract forwards to the binary.
    if not re.fullmatch(r"[a-z]{3}(\+[a-z]{3})*", required_lang or ""):
        return (
            False,
            f"Idioma invalido: {required_lang!r}. Usa codigos como 'spa' o 'spa+eng'.",
        )
    needed = [c.strip() for c in required_lang.split("+") if c.strip()]
    missing = [c for c in needed if c not in langs]
    if missing:
        return (
            False,
            (
                f"Falta(n) idioma(s) en Tesseract: {missing}. "
                f"Instalados: {sorted(langs)}. "
                "Para espanol descarga 'spa.traineddata' (UB-Mannheim ya lo "
                "incluye en su instalador) y copialo a "
                r"'C:\Program Files\Tesseract-OCR\tessdata'."
            ),
        )
    return True, None


def ocr_image(img: np.ndarray, lang: str, psm: int) -> str:
    """Run pytesseract.image_to_string with a fixed PSM."""
    config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"
    return pytesseract.image_to_string(img, lang=lang, config=config)


def score_text(text: str) -> float:
    """Heuristic score: rewards alpha+digits+keywords, penalizes garbage."""
    if not text:
        return 0.0
    score = 0.0
    for ch in text:
        if ch.isalpha():
            score += 1.0
        elif ch.isdigit():
            score += 0.5
        elif ch == "\n":
            score += 0.2
    upper = text.upper()
    # Word-boundary keyword matches (avoid 'COSTO' matching 'COSTOSO').
    for kw in DOMAIN_KEYWORDS:
        score += 2.0 * len(
            re.findall(r"\b" + re.escape(kw) + r"\b", upper)
        )
    # Penalize real runs of >=3 consecutive invalid chars in the original
    # text (NOT on a stripped string, which would conflate non-adjacent
    # noise into spurious clusters).
    for _ in _INVALID_RUN_RE.finditer(text):
        score -= 5.0
    # Penalize low character diversity (e.g. "OOOOOO" or "III IIII II"
    # often emitted by Tesseract on degraded dark-block crops).
    stripped = text.strip()
    if len(stripped) >= 8:
        unique_ratio = len(set(stripped)) / len(stripped)
        if unique_ratio < 0.15:
            score -= 10.0
    return score


def ocr_multi_psm(
    img: np.ndarray,
    lang: str,
    psms: Sequence[int] = (4, 6, 11, 12),
) -> tuple[str, int]:
    """Run OCR with several PSMs, score each, return (best_text, best_psm).

    If every PSM fails or returns nothing useful, returns ("", -1) so the
    caller can mark the page as "psm desconocido" instead of falsely
    attributing the empty result to psms[0].
    """
    best_text = ""
    best_psm = -1
    best_score = float("-inf")
    for psm in psms:
        try:
            text = ocr_image(img, lang=lang, psm=psm)
        except Exception as e:
            logger.warning("OCR fallo con psm=%s: %s", psm, e)
            continue
        s = score_text(text)
        logger.debug("psm=%s score=%.2f chars=%s", psm, s, len(text))
        if s > best_score:
            best_score = s
            best_text = text
            best_psm = psm
    return best_text.strip(), best_psm
