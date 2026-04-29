# syntax=docker/dockerfile:1.7
# =========================================================
# Backend image: FastAPI + Tesseract + Ghostscript + qpdf
# =========================================================
FROM python:3.11.9-slim-bookworm AS base

# --- Build args / env ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# --- System deps: OCR binaries + native libs for PyMuPDF / Pillow / OpenCV ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-spa \
        tesseract-ocr-eng \
        ghostscript \
        qpdf \
        pngquant \
        unpaper \
        poppler-utils \
        libxml2 \
        libxslt1.1 \
        libjpeg62-turbo \
        libpng16-16 \
        libtiff6 \
        libopenjp2-7 \
        zlib1g \
        libfreetype6 \
        liblept5 \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- App user (non-root) ---
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --system --gid ${APP_GID} app \
 && useradd  --system --uid ${APP_UID} --gid ${APP_GID} \
             --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# --- Python deps ---
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /app/requirements.txt

# --- Storage path (volume mount target) ---
RUN mkdir -p /storage && chown -R app:app /storage /app

# --- App code (placeholder; real code added in later phases) ---
COPY --chown=app:app app /app/app

USER app

EXPOSE 8000

# Healthcheck is also defined at compose level; this is a fallback for `docker run`.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
