"""
Layout-preserving HTML renderer.

Builds an HTML file that places each recognised word at its original
coordinates, page by page, so the result reads like a faithful
transcription of the source layout. For native PDFs we use PyMuPDF
spans (with font size and family). For scanned PDFs / images we use
Tesseract's `image_to_data` to obtain word-level bounding boxes.
"""
from __future__ import annotations

import html
import io
from pathlib import Path
from typing import Iterable

import cv2
import fitz  # PyMuPDF
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

from app.logging_config import get_logger

logger = get_logger(__name__)

_OCR_DPI = 300  # rendering DPI for layout pages (72 -> *N for fidelity)
_OCR_CONFIG = "--oem 1 --psm 3"


# ----------------- HTML template helpers ---------------------------

_PAGE_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: #f1f3f5;
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  background: #1f2933;
  color: #fff;
  padding: 8px 16px;
  font-size: 13px;
  display: flex;
  gap: 12px;
  align-items: center;
  border-bottom: 1px solid #0b1015;
}
.toolbar small { opacity: .75; }
.pages { padding: 24px; display: flex; flex-direction: column; gap: 24px; align-items: center; }
.page {
  position: relative;
  background: #fff;
  box-shadow: 0 2px 14px rgba(0,0,0,.12);
  border: 1px solid #d0d4d9;
  overflow: hidden;
}
.page .word, .page .span {
  position: absolute;
  white-space: pre;
  line-height: 1;
  color: #111;
}
.page .word { color: #111; }
.empty {
  text-align: center;
  color: #6c757d;
  padding: 40px 16px;
}
"""

_HTML_HEADER = """<!doctype html>
<html lang="es"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Layout reconstruido</title>
<style>%s</style>
</head><body>
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _toolbar(page_count: int, kind: str) -> str:
    return (
        '<div class="toolbar">'
        f'<strong>Layout reconstruido</strong>'
        f'<small>{page_count} pagina(s) &middot; origen: {_esc(kind)}</small>'
        '</div>\n'
    )


# ----------------- Native-PDF path ---------------------------------

def _render_native_pdf_html(pdf_path: Path) -> tuple[str, int]:
    """Render a native PDF: each text span placed by PyMuPDF coordinates."""
    parts: list[str] = []
    page_count = 0
    with fitz.open(pdf_path) as doc:
        for page in doc:
            page_count += 1
            width_pt, height_pt = page.rect.width, page.rect.height
            # Use 1pt = 1px (1:1) so the page mirrors the original geometry.
            parts.append(
                f'<div class="page" '
                f'style="width:{width_pt:.1f}px;height:{height_pt:.1f}px;">'
            )
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type", 0) != 0:
                    continue  # skip image blocks
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if not text.strip():
                            continue
                        x0, y0, x1, y1 = span["bbox"]
                        size = span.get("size", 11)
                        font = span.get("font", "")
                        is_bold = "Bold" in font or "bold" in font
                        is_italic = "Italic" in font or "Oblique" in font
                        style = (
                            f"left:{x0:.1f}px;top:{y0:.1f}px;"
                            f"font-size:{size:.1f}px;"
                            f"width:{(x1 - x0):.1f}px;"
                            f"height:{(y1 - y0):.1f}px;"
                        )
                        if is_bold:
                            style += "font-weight:700;"
                        if is_italic:
                            style += "font-style:italic;"
                        parts.append(
                            f'<span class="span" style="{style}">'
                            f'{_esc(text)}</span>'
                        )
            parts.append("</div>")
    return "".join(parts), page_count


# ----------------- OCR path (scanned PDF / image) ------------------

def _ocr_words_to_spans(
    image_arr: np.ndarray,
    page_w: int,
    page_h: int,
    languages: str,
) -> list[str]:
    """Run Tesseract on a single image, return list of <span> chunks."""
    data = pytesseract.image_to_data(
        image_arr,
        lang=languages,
        config=_OCR_CONFIG,
        output_type=Output.DICT,
    )
    spans: list[str] = []
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 30:  # skip very low-confidence noise
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        font_px = max(8, int(h * 0.85))
        style = (
            f"left:{x}px;top:{y}px;"
            f"width:{w}px;height:{h}px;"
            f"font-size:{font_px}px;"
        )
        spans.append(
            f'<span class="word" style="{style}">{_esc(word)}</span>'
        )
    return spans


def _preprocess_for_layout(image_bgr: np.ndarray) -> np.ndarray:
    if image_bgr.ndim == 3:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_bgr
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _render_scanned_pdf_html(pdf_path: Path, languages: str) -> tuple[str, int]:
    parts: list[str] = []
    page_count = 0
    zoom = _OCR_DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        for page in doc:
            page_count += 1
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            with Image.open(io.BytesIO(pix.tobytes("png"))) as pil_img:
                pil_img = pil_img.convert("RGB")
                arr = np.array(pil_img)[:, :, ::-1].copy()
            prepared = _preprocess_for_layout(arr)
            page_h, page_w = prepared.shape[:2]
            parts.append(
                f'<div class="page" '
                f'style="width:{page_w}px;height:{page_h}px;">'
            )
            parts.extend(_ocr_words_to_spans(prepared, page_w, page_h, languages))
            parts.append("</div>")
    return "".join(parts), page_count


def _render_image_html(image_path: Path, languages: str) -> tuple[str, int]:
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        with Image.open(image_path) as pil_img:
            pil_img = pil_img.convert("RGB")
            img = np.array(pil_img)[:, :, ::-1].copy()
    prepared = _preprocess_for_layout(img)
    h, w = prepared.shape[:2]
    parts: list[str] = [
        f'<div class="page" style="width:{w}px;height:{h}px;">'
    ]
    parts.extend(_ocr_words_to_spans(prepared, w, h, languages))
    parts.append("</div>")
    return "".join(parts), 1


# ----------------- Public entry points -----------------------------

def write_layout_html_for_pdf(
    pdf_path: Path,
    output_html: Path,
    *,
    languages: str,
    is_native: bool,
) -> Path:
    body, page_count = (
        _render_native_pdf_html(pdf_path)
        if is_native
        else _render_scanned_pdf_html(pdf_path, languages)
    )
    kind = "PDF nativo" if is_native else "PDF escaneado (OCR)"
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        (_HTML_HEADER % _PAGE_CSS)
        + _toolbar(page_count, kind)
        + '<div class="pages">'
        + (body or '<div class="empty">Sin contenido reconocido.</div>')
        + "</div></body></html>",
        encoding="utf-8",
    )
    logger.info(
        "layout_html_written",
        extra={"path": str(output_html), "pages": page_count, "kind": kind},
    )
    return output_html


def write_layout_html_for_image(
    image_path: Path,
    output_html: Path,
    *,
    languages: str,
) -> Path:
    body, page_count = _render_image_html(image_path, languages)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        (_HTML_HEADER % _PAGE_CSS)
        + _toolbar(page_count, "Imagen (OCR)")
        + '<div class="pages">'
        + (body or '<div class="empty">Sin contenido reconocido.</div>')
        + "</div></body></html>",
        encoding="utf-8",
    )
    logger.info(
        "layout_html_written",
        extra={"path": str(output_html), "pages": page_count, "kind": "image"},
    )
    return output_html
