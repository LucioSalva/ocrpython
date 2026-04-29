"""Detect dark rectangular regions that typically contain white text
(headers and table bands in Mexican municipal/administrative documents).
"""
from __future__ import annotations

import logging
from typing import Iterable

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Tunables
_DARK_LOW = 0  # min pixel value considered "dark"
_DARK_HIGH = 90  # max pixel value considered "dark"
_MORPH_KERNEL = (35, 7)  # close horizontally to merge text-band into a block
_MIN_AREA = 1500
_MIN_W = 80
_MIN_H = 15


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def build_dark_mask(img_bgr: np.ndarray) -> np.ndarray:
    """Return uint8 binary mask where dark regions = 255."""
    gray = _to_gray(img_bgr)
    mask = cv2.inRange(gray, _DARK_LOW, _DARK_HIGH)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, _MORPH_KERNEL)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return closed


def detect_dark_blocks(img_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find dark blocks. Returns list of (x, y, w, h) sorted top-to-bottom,
    left-to-right.
    """
    mask = build_dark_mask(img_bgr)
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    blocks: list[tuple[int, int, int, int]] = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < _MIN_W or h < _MIN_H:
            continue
        if w * h < _MIN_AREA:
            continue
        blocks.append((x, y, w, h))
    # Sort top-to-bottom, then left-to-right (with row tolerance).
    row_tol = 20
    blocks.sort(key=lambda b: (b[1] // row_tol, b[0]))
    return blocks


def add_padding(
    box: tuple[int, int, int, int],
    img_shape: tuple[int, ...],
    padding: int = 4,
) -> tuple[int, int, int, int]:
    """Expand a (x,y,w,h) box by `padding` px, clamped to image bounds."""
    x, y, w, h = box
    H, W = img_shape[:2]
    nx = max(0, x - padding)
    ny = max(0, y - padding)
    nw = min(W - nx, w + padding * 2)
    nh = min(H - ny, h + padding * 2)
    return nx, ny, nw, nh


def draw_blocks_overlay(
    img_bgr: np.ndarray, blocks: Iterable[tuple[int, int, int, int]]
) -> np.ndarray:
    """Return a copy of the image with red rectangles for each block."""
    out = img_bgr.copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    for i, (x, y, w, h) in enumerate(blocks, start=1):
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 2)
        label = str(i)
        cv2.putText(
            out,
            label,
            (x + 4, y + max(18, h // 2)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    return out
