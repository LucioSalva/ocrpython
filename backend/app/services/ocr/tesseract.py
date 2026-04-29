"""
Tesseract OCR engine implementation (relaxed-filter mode).

Pipeline per page:
  1. Render scanned PDFs at 400 DPI.
  2. Pre-process: grayscale -> CLAHE -> deskew -> denoise -> sharpen
     -> adaptive threshold.
  3. Run Tesseract under multiple PSMs using `image_to_data`. Score
     each variant by sum(confidence * len(word)) and pick the best.
  4. Reconstruct text using Tesseract's own block/par/line/word indices
     (preserves multi-column layout, doesn't fight Tesseract's
     own segmentation).
  5. Keep words >=30 confidence; keep short tokens that are valid
     form values ("SI", "NO", "X", "N/A", roman numerals, digits).
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

from app.logging_config import get_logger
from app.services.ocr.base import OCREngine, OCRResult

logger = get_logger(__name__)

_RASTER_DPI = 400
_TESS_CONFIGS = [
    "--oem 1 --psm 1",
    "--oem 1 --psm 3",
    "--oem 1 --psm 4",
]
_MIN_CONF = 30
_NATIVE_PREFER_FACTOR = 0.6
_KEEP_SHORT_TOKENS = {
    "SI", "NO", "N/A", "NA", "OK",
    "X", "Y",
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "A", "B", "C", "D", "E",
}
_VALID_CHAR_RE = re.compile(r"[\wÀ-ɏÑñ]", re.UNICODE)


def _deskew(gray: np.ndarray) -> np.ndarray:
    inv = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(inv > 0))
    if coords.size == 0:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.3:
        return gray
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _preprocess_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    if image_bgr.ndim == 3:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_bgr
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(gray)
    deskewed = _deskew(contrasted)
    denoised = cv2.fastNlMeansDenoising(deskewed, h=10)
    blurred = cv2.GaussianBlur(denoised, (0, 0), sigmaX=1.0)
    sharpened = cv2.addWeighted(denoised, 1.4, blurred, -0.4, 0)
    return cv2.adaptiveThreshold(
        sharpened,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        15,
    )


def _is_keepable_word(word: str) -> bool:
    if not word:
        return False
    if word.upper() in _KEEP_SHORT_TOKENS:
        return True
    if any(ch.isdigit() for ch in word):
        return True
    has_alpha = any(_VALID_CHAR_RE.match(ch) for ch in word)
    if not has_alpha:
        return False
    if len(word) == 1:
        return False
    return True


def _reconstruct(data: dict) -> tuple[str, float]:
    """Build text using Tesseract's block/par/line indices and return
    (text, weighted_score) for variant comparison."""
    n = len(data.get("text", []))
    rows: list[tuple[int, int, int, int, str, float]] = []
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not _is_keepable_word(word):
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < _MIN_CONF:
            continue
        block = int(data.get("block_num", [0] * n)[i])
        par = int(data.get("par_num", [0] * n)[i])
        line = int(data.get("line_num", [0] * n)[i])
        wn = int(data.get("word_num", [0] * n)[i])
        rows.append((block, par, line, wn, word, conf))
    if not rows:
        return "", 0.0
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    lines: list[list[str]] = []
    current: list[str] = []
    last_key: tuple[int, int, int] | None = None
    score = 0.0
    for block, par, line, _wn, word, conf in rows:
        key = (block, par, line)
        if last_key is None or key == last_key:
            current.append(word)
        else:
            lines.append(current)
            if last_key[:2] != key[:2]:
                lines.append([])
            current = [word]
        last_key = key
        score += conf * len(word)
    if current:
        lines.append(current)
    text = "\n".join(" ".join(line) for line in lines if line is not None).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text, score


def _ocr_best(prepared: np.ndarray, languages: str) -> str:
    best_text = ""
    best_score = -1.0
    for cfg in _TESS_CONFIGS:
        try:
            data = pytesseract.image_to_data(
                prepared,
                lang=languages,
                config=cfg,
                output_type=Output.DICT,
            )
        except Exception:
            logger.exception("tesseract_config_failed", extra={"config": cfg})
            continue
        text, score = _reconstruct(data)
        if text and score > best_score:
            best_score = score
            best_text = text
    return best_text


def _native_score(text: str) -> int:
    return sum(1 for ch in text if ch.isalnum())


class TesseractEngine(OCREngine):
    name = "tesseract"

    def ocr_image(self, image_path: Path, languages: str) -> OCRResult:
        logger.info(
            "ocr_image_start",
            extra={"path": str(image_path), "lang": languages},
        )
        img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if img is None:
            with Image.open(image_path) as pil_img:
                pil_img = pil_img.convert("RGB")
                img = np.array(pil_img)[:, :, ::-1].copy()
        prepared = _preprocess_for_ocr(img)
        text = _ocr_best(prepared, languages)
        return OCRResult(
            text=text,
            pages=[text],
            engine=self.name,
            languages=languages,
        )

    def ocr_pdf_pages(self, pdf_path: Path, languages: str) -> OCRResult:
        logger.info(
            "ocr_pdf_start",
            extra={"path": str(pdf_path), "lang": languages},
        )
        zoom = _RASTER_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        page_texts: list[str] = []
        with fitz.open(pdf_path) as doc:
            for index, page in enumerate(doc):
                native_text = (page.get_text("text") or "").strip()
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                with Image.open(io.BytesIO(pix.tobytes("png"))) as pil_img:
                    pil_img = pil_img.convert("RGB")
                    arr = np.array(pil_img)[:, :, ::-1].copy()
                prepared = _preprocess_for_ocr(arr)
                ocr_text = _ocr_best(prepared, languages)

                if (
                    _native_score(native_text)
                    >= _native_score(ocr_text) * _NATIVE_PREFER_FACTOR
                    and _native_score(native_text) > 50
                ):
                    page_text = native_text
                    src = "native"
                else:
                    page_text = ocr_text
                    src = "ocr"
                page_texts.append(page_text)
                logger.info(
                    "ocr_pdf_page_done",
                    extra={
                        "page": index + 1,
                        "chars": len(page_text),
                        "source": src,
                    },
                )
        full_text = "\n\n".join(t for t in page_texts if t)
        return OCRResult(
            text=full_text,
            pages=page_texts,
            engine=self.name,
            languages=languages,
        )
