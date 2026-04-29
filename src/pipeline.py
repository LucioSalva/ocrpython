"""End-to-end pipeline: PDF -> rendered pages -> preprocess -> dark-block
detection -> multi-PSM OCR -> formatted text file.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Sequence

import cv2

from src.dark_block_detector import (
    add_padding,
    build_dark_mask,
    detect_dark_blocks,
    draw_blocks_overlay,
)
from src.image_preprocessing import (
    preprocess_dark_crop,
    preprocess_normal_page,
)
from src.ocr_engine import ocr_multi_psm
from src.pdf_renderer import iter_pdf_pages
from src.text_cleaner import clean

logger = logging.getLogger(__name__)

SEPARATOR = "=" * 60


class PipelineStats:
    __slots__ = ("pages", "blocks", "chars")

    def __init__(self) -> None:
        self.pages = 0
        self.blocks = 0
        self.chars = 0


def _write_image(path: Path, img) -> None:
    """cv2.imwrite that handles non-ASCII paths on Windows."""
    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise RuntimeError(f"imencode fallo para {path}")
    path.write_bytes(buf.tobytes())


def _attach_run_log(out_dir: Path) -> logging.FileHandler:
    """Attach a per-PDF FileHandler under <out_dir>/run.log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logging.getLogger().addHandler(fh)
    return fh


def _detach_run_log(fh: logging.FileHandler) -> None:
    try:
        logging.getLogger().removeHandler(fh)
        fh.close()
    except Exception:  # pragma: no cover
        pass


def _prepare_output_dir(output_dir: Path, force: bool) -> bool:
    """Create / clean the output directory. Returns True if processing
    should proceed, False if a previous run exists and force=False."""
    text_file = output_dir / "texto_extraido.txt"
    # Treat truncated/zero-byte outputs as needing reprocess so a previous
    # interrupted run doesn't masquerade as completed.
    if text_file.exists() and not force:
        try:
            if text_file.stat().st_size > 0:
                return False
        except OSError:
            pass
    if output_dir.exists():
        # Wipe sub-folders we own. Do NOT touch siblings.
        for sub in ("paginas", "bloques_negros", "debug"):
            d = output_dir / sub
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        for fname in ("texto_extraido.txt", "run.log"):
            f = output_dir / fname
            if f.exists():
                try:
                    f.unlink()
                except OSError as e:
                    logger.warning("No pude borrar %s: %s", f, e)
    output_dir.mkdir(parents=True, exist_ok=True)
    return True


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 400,
    lang: str = "spa",
    debug: bool = True,
    force: bool = False,
    psms: Sequence[int] = (4, 6, 11, 12),
) -> tuple[Path, PipelineStats] | None:
    """Run the full pipeline on a single PDF.

    Returns (path_to_text_file, stats) on success, None if skipped (because
    the output already exists and force=False).
    Raises EncryptedPDFError for password-protected PDFs.
    """
    output_dir = output_dir.resolve()
    if not _prepare_output_dir(output_dir, force=force):
        logger.info(
            "Salida ya existe (%s). Usa --force para regenerar.",
            output_dir,
        )
        return None

    fh = _attach_run_log(output_dir)
    stats = PipelineStats()
    try:
        # Log the file name only — full paths leak username on shared logs.
        logger.info("Procesando %s", pdf_path.name)
        paginas_dir = output_dir / "paginas"
        bloques_dir = output_dir / "bloques_negros"
        debug_dir = output_dir / "debug"
        paginas_dir.mkdir(exist_ok=True)
        bloques_dir.mkdir(exist_ok=True)
        if debug:
            debug_dir.mkdir(exist_ok=True)

        text_path = output_dir / "texto_extraido.txt"
        with text_path.open("w", encoding="utf-8") as fout:
            fout.write(SEPARATOR + "\n")
            fout.write(f"ARCHIVO: {pdf_path.name}\n")
            fout.write(SEPARATOR + "\n\n")

            for page_no, img_bgr in iter_pdf_pages(pdf_path, dpi=dpi):
                stats.pages += 1
                logger.info(
                    "Pagina %d (%dx%d)",
                    page_no,
                    img_bgr.shape[1],
                    img_bgr.shape[0],
                )
                page_tag = f"pagina_{page_no:02d}"
                _write_image(paginas_dir / f"{page_tag}.png", img_bgr)

                # --- General-page OCR ---
                try:
                    prepared = preprocess_normal_page(img_bgr)
                    if debug:
                        _write_image(
                            debug_dir / f"{page_tag}_preprocesada.png",
                            prepared,
                        )
                    general_text, general_psm = ocr_multi_psm(
                        prepared, lang=lang, psms=psms
                    )
                    general_text = clean(general_text)
                except Exception:
                    logger.exception(
                        "Fallo OCR general en pagina %d, continuo", page_no
                    )
                    general_text = ""
                    general_psm = -1

                # --- Dark-block detection ---
                try:
                    blocks = detect_dark_blocks(img_bgr)
                except Exception:
                    logger.exception(
                        "Fallo deteccion de bloques en pagina %d", page_no
                    )
                    blocks = []

                if debug:
                    try:
                        mask = build_dark_mask(img_bgr)
                        _write_image(
                            debug_dir / f"{page_tag}_mascara_bloques.png",
                            mask,
                        )
                        overlay = draw_blocks_overlay(img_bgr, blocks)
                        _write_image(
                            debug_dir / f"{page_tag}_bloques_detectados.png",
                            overlay,
                        )
                    except Exception:
                        logger.exception(
                            "Fallo escritura de debug en pagina %d", page_no
                        )

                # --- Per-block OCR ---
                block_results: list[
                    tuple[int, tuple[int, int, int, int], str, int]
                ] = []
                for idx, box in enumerate(blocks, start=1):
                    px, py, pw, ph = add_padding(box, img_bgr.shape, padding=4)
                    crop = img_bgr[py : py + ph, px : px + pw]
                    if crop.size == 0:
                        continue
                    try:
                        prepared_crop = preprocess_dark_crop(crop)
                        _write_image(
                            bloques_dir / f"{page_tag}_bloque_{idx:02d}.png",
                            prepared_crop,
                        )
                        btext, bpsm = ocr_multi_psm(
                            prepared_crop, lang=lang, psms=psms
                        )
                        btext = clean(btext)
                    except Exception:
                        logger.exception(
                            "Fallo OCR del bloque %d en pagina %d",
                            idx,
                            page_no,
                        )
                        btext = ""
                        bpsm = -1
                    block_results.append((idx, (px, py, pw, ph), btext, bpsm))
                    stats.blocks += 1

                # --- Write page section ---
                fout.write(SEPARATOR + "\n")
                fout.write(f"PÁGINA {page_no}\n")
                fout.write(SEPARATOR + "\n\n")
                fout.write("[OCR GENERAL]\n")
                if general_psm >= 0:
                    fout.write(f"(psm={general_psm})\n")
                fout.write((general_text or "(sin texto extraido)") + "\n\n")

                fout.write("[OCR DE BLOQUES NEGROS]\n")
                fout.write(f"Bloques detectados: {len(block_results)}\n\n")
                for idx, (x, y, w, h), btext, bpsm in block_results:
                    psm_part = f" (psm={bpsm})" if bpsm >= 0 else ""
                    fout.write(
                        f"[Bloque negro {idx}] (x={x}, y={y}, w={w}, h={h})"
                        f"{psm_part}\n"
                    )
                    fout.write((btext or "(sin texto extraido)") + "\n\n")

                stats.chars += len(general_text) + sum(
                    len(b[2]) for b in block_results
                )

        logger.info(
            "Hecho: paginas=%d bloques=%d chars=%d",
            stats.pages,
            stats.blocks,
            stats.chars,
        )
        return text_path, stats
    finally:
        _detach_run_log(fh)
