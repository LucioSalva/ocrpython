# OCR local stack

Stack 100% local para una app personal de OCR.

- Backend: FastAPI (Python 3.11) en `http://localhost:8000`
- Frontend: PHP 8.2 + Apache (HTML estatico) en `http://localhost:8080`
- DB: PostgreSQL 16 (con `unaccent` y FTS `spanish_unaccent`) en `127.0.0.1:5432`

## Primer arranque

```bash
cp .env.example .env
# edita .env y cambia POSTGRES_PASSWORD
docker compose up -d --build
```

## Verificacion

```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8080/
```

## Notas

- Todos los puertos publicados estan ligados a `127.0.0.1` (no se exponen a la red).
- Datos persistentes: volumenes nombrados `ocr_pgdata` y `ocr_storage`.
- Los binarios OCR (tesseract, ghostscript, qpdf, ocrmypdf) viven dentro del contenedor `backend`.
- El navegador llama directo a FastAPI; el frontend PHP no actua como proxy (CORS estricto via `CORS_ORIGINS`).
