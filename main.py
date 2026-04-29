"""Standalone OCR CLI for Mexican municipal scanned PDFs.

Usage:
    python main.py --pdf input/foo.pdf
    python main.py --pdf input/bar.pdf --dpi 400 --lang spa
    python main.py                            # processes all input/*.pdf
    python main.py --no-debug --force         # skip debug images, regenerate
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Make `src` importable when running `python main.py` directly.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ocr_engine import tesseract_check  # noqa: E402
from src.pdf_renderer import EncryptedPDFError, PdfTooLargeError  # noqa: E402
from src.pipeline import process_pdf  # noqa: E402


def _setup_logging() -> None:
    """Console at INFO (or DEBUG if OCR_DEBUG=1), but the root logger stays
    at DEBUG so per-PDF FileHandlers can capture full detail without
    polluting stdout."""
    console_level = (
        logging.DEBUG if os.environ.get("OCR_DEBUG") == "1" else logging.INFO
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(console_level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Avoid duplicate handlers on re-runs (e.g. in REPL).
    root.handlers = [handler]


def _gather_pdfs(input_dir: Path, explicit: Path | None) -> list[Path]:
    if explicit is not None:
        if not explicit.exists():
            raise FileNotFoundError(f"PDF no existe: {explicit}")
        return [explicit]
    if not input_dir.exists():
        return []
    seen: set[Path] = set()
    pdfs: list[Path] = []
    # Case-insensitive on Windows; on Linux match both.
    for pattern in ("*.pdf", "*.PDF"):
        for p in input_dir.glob(pattern):
            if p in seen:
                continue
            seen.add(p)
            pdfs.append(p)
    return sorted(pdfs)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "OCR avanzado para PDFs escaneados (documentos municipales MX). "
            "Detecta bloques oscuros con texto blanco, los invierte y los OCRea "
            "ademas de la pagina completa."
        )
    )
    p.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Ruta a un PDF especifico. Si se omite, procesa input/*.pdf.",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=400,
        help="DPI de renderizado (default: 400, rango: 50-1200).",
    )
    p.add_argument(
        "--lang",
        type=str,
        default="spa",
        help="Idioma(s) Tesseract (ej. 'spa', 'spa+eng'). Default: spa.",
    )
    p.add_argument(
        "--psms",
        type=str,
        default="4,6,11,12",
        help="PSMs a probar separados por coma (default: 4,6,11,12).",
    )
    p.add_argument(
        "--no-debug",
        action="store_true",
        help="Omite la generacion de imagenes debug (mas rapido).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Reprocesa aunque ya exista output/<nombre>/texto_extraido.txt.",
    )
    return p.parse_args()


def _parse_psms(raw: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError as e:
            raise ValueError(f"PSM invalido: {part!r}") from e
        if not 0 <= n <= 13:
            raise ValueError(f"PSM fuera de rango (0-13): {n}")
        out.append(n)
    if not out:
        raise ValueError("Lista de PSMs vacia")
    return tuple(out)


def main() -> int:
    _setup_logging()
    args = _parse_args()

    if not 50 <= args.dpi <= 1200:
        print(
            f"[ERROR] --dpi fuera de rango (50-1200): {args.dpi}",
            file=sys.stderr,
        )
        return 2

    try:
        psms = _parse_psms(args.psms)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    ok, err = tesseract_check(required_lang=args.lang)
    if not ok:
        print(f"[ERROR] {err}", file=sys.stderr)
        return 2

    input_dir = ROOT / "input"
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    try:
        pdfs = _gather_pdfs(input_dir, args.pdf)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if not pdfs:
        print(
            f"No se encontraron PDFs en '{input_dir}'. "
            "Coloca archivos .pdf ahi o pasa --pdf <ruta>."
        )
        return 0

    total_pages = 0
    total_blocks = 0
    total_chars = 0
    procesados = 0
    saltados = 0
    fallidos: list[tuple[Path, str]] = []

    for pdf in pdfs:
        out_for_pdf = output_dir / pdf.stem
        try:
            result = process_pdf(
                pdf_path=pdf,
                output_dir=out_for_pdf,
                dpi=args.dpi,
                lang=args.lang,
                debug=not args.no_debug,
                force=args.force,
                psms=psms,
            )
        except EncryptedPDFError as e:
            print(f"[WARN] {e} -- se omite.", file=sys.stderr)
            fallidos.append((pdf, str(e)))
            continue
        except PdfTooLargeError as e:
            print(f"[WARN] {e}", file=sys.stderr)
            fallidos.append((pdf, str(e)))
            continue
        except Exception as e:
            logging.exception("Fallo procesando %s", pdf)
            fallidos.append((pdf, str(e)))
            continue
        if result is None:
            saltados += 1
            continue
        text_path, stats = result
        procesados += 1
        total_pages += stats.pages
        total_blocks += stats.blocks
        total_chars += stats.chars
        print(
            f"[OK] {pdf.name} -> {text_path.relative_to(ROOT)} "
            f"(paginas={stats.pages}, bloques={stats.blocks}, "
            f"chars={stats.chars})"
        )

    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"Procesados : {procesados}")
    print(f"Saltados   : {saltados} (ya existian; usa --force para rehacer)")
    print(f"Fallidos   : {len(fallidos)}")
    print(f"Paginas    : {total_pages}")
    print(f"Bloques    : {total_blocks}")
    print(f"Chars      : {total_chars}")
    if fallidos:
        print("\nDetalle de fallidos:")
        for pdf, err in fallidos:
            print(f"  - {pdf.name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
