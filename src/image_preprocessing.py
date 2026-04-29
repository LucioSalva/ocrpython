"""Image preprocessing routines for full pages and dark-block crops."""
from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def light_deskew(gray: np.ndarray) -> np.ndarray:
    """Correct small rotations (<15 deg). Returns grayscale image."""
    inv = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(inv > 0))
    if coords.size == 0:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.3 or abs(angle) > 15:
        return gray
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def preprocess_normal_page(img_bgr: np.ndarray) -> np.ndarray:
    """Standard pipeline for the full page: gray -> CLAHE -> deskew ->
    denoise -> sharpen -> adaptive threshold. Returns binary image (uint8).

    Note: medianBlur is used instead of fastNlMeansDenoising because at
    400 DPI on A4 NL-Means is dramatically slower (5-30s per page) for
    a marginal quality gain on typical scanned forms.
    """
    gray = _to_gray(img_bgr)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
    contrasted = clahe.apply(gray)
    deskewed = light_deskew(contrasted)
    denoised = cv2.medianBlur(deskewed, 3)
    blurred = cv2.GaussianBlur(denoised, (0, 0), sigmaX=1.0)
    sharpened = cv2.addWeighted(denoised, 1.4, blurred, -0.4, 0)
    thresh = cv2.adaptiveThreshold(
        sharpened,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        15,
    )
    return thresh


def preprocess_dark_crop(crop_bgr: np.ndarray) -> np.ndarray:
    """Pipeline for crops that contain white-on-dark text:
    gray -> invert -> Otsu binarize -> upscale 2.5x with cubic.
    """
    gray = _to_gray(crop_bgr)
    inverted = cv2.bitwise_not(gray)
    _, otsu = cv2.threshold(
        inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    h, w = otsu.shape[:2]
    if h == 0 or w == 0:
        return otsu
    upscaled = cv2.resize(
        otsu,
        (int(w * 2.5), int(h * 2.5)),
        interpolation=cv2.INTER_CUBIC,
    )
    return upscaled
