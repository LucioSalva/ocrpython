# syntax=docker/dockerfile:1.7
# =========================================================
# Frontend image: PHP 8.2 + Apache serving static HTML.
# PHP is NOT a proxy: the browser calls FastAPI directly.
# =========================================================
FROM php:8.2.23-apache-bookworm

ENV APACHE_DOCUMENT_ROOT=/var/www/html

# curl is needed by the healthcheck; ca-certificates is good hygiene.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Make sure DocumentRoot points at /var/www/html (default already, but explicit).
RUN sed -ri -e "s!/var/www/html!${APACHE_DOCUMENT_ROOT}!g" /etc/apache2/sites-available/*.conf \
 && sed -ri -e "s!/var/www/!${APACHE_DOCUMENT_ROOT}/!g"   /etc/apache2/apache2.conf /etc/apache2/conf-available/*.conf

# Serve the app under /ocr/ (project name in URL).
# Static assets live in /var/www/html/ocr/, and / redirects to /ocr/.
COPY --chown=www-data:www-data html/ /var/www/html/ocr/

# Root redirect: hitting http://localhost:8080/ takes you to /ocr/.
RUN printf '%s\n' \
      '<!doctype html>' \
      '<html><head><meta charset="utf-8">' \
      '<meta http-equiv="refresh" content="0; url=/ocr/">' \
      '<title>OCR Local</title></head>' \
      '<body><a href="/ocr/">Ir a /ocr/</a></body></html>' \
      > /var/www/html/index.html \
 && chown www-data:www-data /var/www/html/index.html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
  CMD curl -fsS http://127.0.0.1/ocr/ >/dev/null || exit 1
