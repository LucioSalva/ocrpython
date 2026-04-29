# OCR Local - Proyecto multi-modo

Proyecto para extraer texto de PDFs escaneados (especialmente documentos
oficiales mexicanos: cedulas municipales, tramites, catastro).

## Modos disponibles

1. **OCR local con Docker (RECOMENDADO)** - usa OCRmyPDF + Poppler en
   contenedor Docker. No requiere instalar Python ni Tesseract en el host.
2. **CLI Python con Tesseract** (`python main.py`) - modo experimental
   con deteccion de bloques negros. Detalles en `README_CLI.md`.
3. **Stack web (Docker Compose)** (`docker compose up`) - backend
   FastAPI + frontend PHP, para uso con interfaz grafica.

---

## Modo 1 - OCR local con Docker

### Pre-requisitos

- Docker Desktop instalado y corriendo. Descarga: https://www.docker.com/products/docker-desktop/
- (Opcional) Poppler para `pdftotext` en host. La pipeline tiene
  fallback automatico que ejecuta `pdftotext` dentro del contenedor
  Docker, asi que NO es estrictamente necesario.

### Verificar dependencias

```powershell
.\scripts\verificar_dependencias.ps1
```

Codigos de salida:

- `0` - todo OK.
- `1` - falta dependencia critica (Docker). El pipeline NO puede correr.
- `2` - solo faltan opcionales (imagen no descargada o pdftotext en host).
  El pipeline puede correr (la imagen se descarga automaticamente con
  `-PullImage` y pdftotext tiene fallback Docker).

### Procesar PDFs

1. Coloca tus PDFs en `input/`.
2. Ejecuta:

```powershell
.\scripts\ocr_local.ps1
```

   o doble-click en `scripts\ocr_local.bat`.

3. Resultados en `output/<nombre_pdf>/`:
   - `salida_ocr.pdf` - PDF buscable (texto seleccionable).
   - `texto_extraido_layout.txt` - texto plano respetando columnas/tablas.
   - `reporte_ocr.txt` - metricas y secciones a revisar.
   - `run.log` - bitacora de la ejecucion.

### Opciones avanzadas

```powershell
# Procesar un PDF especifico
.\scripts\ocr_local.ps1 -Pdf input/foo.pdf

# Multi-idioma
.\scripts\ocr_local.ps1 -Lang spa+eng

# Forzar reprocesado (sobrescribe salida_ocr.pdf existente)
.\scripts\ocr_local.ps1 -Force

# Descargar / actualizar la imagen Docker antes de procesar
.\scripts\ocr_local.ps1 -PullImage

# Saltar --clean (si la imagen no incluye unpaper)
.\scripts\ocr_local.ps1 -NoClean

# Cambiar imagen Docker (avanzado)
.\scripts\ocr_local.ps1 -DockerImage ocrmypdf/ocrmypdf:latest
```

### Como funciona internamente

1. `verificar_dependencias.ps1` valida Docker CLI, daemon, imagen, pdftotext.
2. `ocr_local.ps1` lista los PDFs (uno o todos los de `input/`).
3. Por cada PDF lanza `docker run jbarlow83/ocrmypdf` con `--force-ocr
   --deskew --rotate-pages --clean --language <Lang>`. Si `--clean`
   falla, reintenta sin `--clean`.
4. Toma el PDF buscable resultante y extrae texto con `pdftotext -layout`
   (host si esta disponible, si no dentro del contenedor Docker).
5. Calcula metricas heuristicas (chars por pagina, runs no imprimibles)
   y genera `reporte_ocr.txt` con secciones a revisar manualmente.
6. Toda la salida de `docker run` queda en `run.log`.

### Limitaciones del OCR local

- No reconstruye tablas como estructura (solo respeta columnas en TXT).
- Bloques negros con texto blanco se leen pero con menor precision.
- Sellos / firmas sobre texto pueden ensuciar la extraccion.
- Calidad fuertemente dependiente de la calidad del escaneo.

---

## Modo 2 - CLI Python (modo legacy / experimental)

Ver `README_CLI.md`. Util cuando quieres deteccion manual de bloques
oscuros y debug visual con imagenes intermedias.

---

## Modo 3 - Stack web

Ver `README_LEGACY.md` (Docker Compose con FastAPI + PHP + PostgreSQL).

---

## Cuando OCR local no es suficiente

Para documentos con tablas complejas, columnas muy pegadas, sellos sobre
texto, o documentos oficiales mal escaneados, el OCR local de Tesseract
puede no ser suficiente. En esos casos conviene usar un motor de
**Document Intelligence / Layout OCR** comercial.

### Integracion futura con Azure Document Intelligence

El proyecto esta preparado para integracion OPCIONAL con Azure Document
Intelligence (pendiente de implementacion). Cuando se active:

- Sera un modo separado, NO activo por default.
- Requerira configurar credenciales explicitamente en `.env.cloud`.
- NUNCA mandara documentos a la nube automaticamente.
- El usuario tendra que pasar un flag explicito `-Cloud` para usarlo.

Esto se documentara cuando se implemente. Por defecto el proyecto
opera 100% local.

---

## Privacidad

- Modo local: ningun archivo sale de tu equipo.
- Modo nube: requerira activacion explicita por el usuario.
